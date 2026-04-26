"""
Prefect flows for AutoCon5 — Part 3 of the workshop.

Pipeline (per BgpSessionNotUp alert):

    alert_receiver
       └── quarantine_bgp_flow                 (fires on status=firing)
              ├── collect_bgp_evidence_task   (metrics + logs + SoT)
              ├── evaluate_policy_task        (DecisionPolicy: stop/skip/proceed)
              ├── annotate_decision_task      (audit trail to Loki)
              ├── ai_rca_task                 (opt-in; ENABLE_AI_RCA toggle)
              └── if proceed:
                    ├── quarantine_task        (Alertmanager silence)
                    └── annotate_action_task   (audit trail to Loki)

       └── resolved_bgp_flow                  (fires on status=resolved)
              └── annotate_decision_task

The four canonical paths from the AutoCon5 outline map to:
    actionable / mismatch    → quarantine
    healthy                  → skip (decision = "skip", reason references intent)
    in-maintenance           → skip (decision = "skip", reason "device under maintenance")
    resolved                 → audit (resolved_bgp_flow only annotates)
"""

from __future__ import annotations

from typing import Any

from prefect import flow, tags, task
from prefect.logging import get_run_logger
from workshop_sdk import Decision, DecisionPolicy, EvidenceBundle, WorkshopSDK

# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


@task(retries=2, retry_delay_seconds=3, log_prints=True,
      task_run_name="collect_evidence[{device}:{peer_address}]")
def collect_bgp_evidence_task(
    device: str, peer_address: str, afi_safi: str, instance_name: str,
    log_minutes: int, log_limit: int,
) -> EvidenceBundle:
    print(f"🔎 [collect] device={device} peer={peer_address} afi={afi_safi} instance={instance_name}")
    sdk = WorkshopSDK()
    ev = sdk.collect_bgp_evidence(
        device=device, peer_address=peer_address, afi_safi=afi_safi, instance_name=instance_name,
        log_minutes=log_minutes, log_limit=log_limit,
    )
    print(
        "✅ [collect] sot.found={} maintenance={} intended={} expected_state={} reason={!r}".format(
            ev.sot.get("found"), ev.sot.get("maintenance"),
            ev.sot.get("intended_peer"), ev.sot.get("expected_state"),
            ev.sot.get("reason"),
        )
    )
    print(f"   metrics={ev.metrics}")
    print(f"   logs collected: {len(ev.logs)} lines")
    return ev


@task(log_prints=True, task_run_name="evaluate_policy[{device}:{peer_address}]")
def evaluate_policy_task(device: str, peer_address: str, ev: EvidenceBundle) -> Decision:
    print(f"🧠 [policy] {device}:{peer_address}")
    policy = DecisionPolicy()

    sot_decision = policy.evaluate(ev.sot, metrics=None)
    print(f"   stage1 SoT-only → {sot_decision.decision} ({sot_decision.reason})")
    if sot_decision.decision in {"stop", "skip"}:
        return sot_decision

    metrics_decision = policy.evaluate(ev.sot, metrics=ev.metrics)
    print(f"   stage2 SoT+metrics → {metrics_decision.decision} ({metrics_decision.reason})")
    return metrics_decision


@task(log_prints=True, task_run_name="annotate_decision[{device}:{peer_address}]")
def annotate_decision_task(workflow: str, device: str, peer_address: str, decision: Decision) -> None:
    print(f"📝 [annotate] decision={decision.decision} reason={decision.reason}")
    sdk = WorkshopSDK()
    sdk.annotate_decision(
        workflow=workflow, device=device, peer_address=peer_address,
        decision=decision.decision, message=decision.reason,
    )


@task(log_prints=True, task_run_name="ai_rca[{device}:{peer_address}]")
def ai_rca_task(workflow: str, device: str, peer_address: str, ev: EvidenceBundle) -> str:
    """Opt-in LLM RCA. Always returns SOMETHING — disabled-fallback or model output."""
    print("🤖 [ai_rca] running (gated by ENABLE_AI_RCA)")
    sdk = WorkshopSDK()
    rca_text = sdk.rca(device=device, peer_address=peer_address, evidence=ev)
    sdk.annotate(
        labels={
            "source": "prefect",
            "workflow": workflow,
            "device": device,
            "peer_address": peer_address,
            "ai_rca": "true",
        },
        message=f"AI RCA:\n{rca_text}",
    )
    print(f"📝 [ai_rca] annotated: {rca_text[:120]}{'…' if len(rca_text) > 120 else ''}")
    return rca_text


@task(log_prints=True, task_run_name="quarantine[{device}:{peer_address}]")
def quarantine_task(device: str, peer_address: str, minutes: int) -> str:
    print(f"🔕 [quarantine] silencing {device}:{peer_address} for {minutes}m")
    sdk = WorkshopSDK()
    silence_id = sdk.quarantine_bgp(device=device, peer_address=peer_address, minutes=minutes)
    print(f"✅ [quarantine] silence id={silence_id}")
    return silence_id


@task(log_prints=True, task_run_name="annotate_action[{device}:{peer_address}]")
def annotate_action_task(workflow: str, device: str, peer_address: str, silence_id: str) -> None:
    sdk = WorkshopSDK()
    sdk.annotate(
        labels={
            "source": "prefect",
            "workflow": workflow,
            "device": device,
            "peer_address": peer_address,
        },
        message=f"QUARANTINE applied (silence_id={silence_id})",
    )


# ---------------------------------------------------------------------------
# Action flows
# ---------------------------------------------------------------------------


@flow(log_prints=True, flow_run_name="quarantine_bgp | {device}:{peer_address}")
def quarantine_bgp_flow(
    device: str, peer_address: str,
    afi_safi: str = "ipv4-unicast", instance_name: str = "default",
    log_minutes: int = 30, log_limit: int = 50, quarantine_minutes: int = 20,
) -> dict[str, Any]:
    logger = get_run_logger()
    print(f"⚙️  [flow] quarantine_bgp_flow {device}:{peer_address}")

    with tags(
        f"device:{device}", f"peer_address:{peer_address}",
        f"afi_safi:{afi_safi}", f"instance:{instance_name}",
        "action:quarantine",
    ):
        ev = collect_bgp_evidence_task(
            device=device, peer_address=peer_address, afi_safi=afi_safi,
            instance_name=instance_name, log_minutes=log_minutes, log_limit=log_limit,
        )

        decision = evaluate_policy_task(device=device, peer_address=peer_address, ev=ev)
        annotate_decision_task(
            workflow="autocon5_quarantine_bgp",
            device=device, peer_address=peer_address, decision=decision,
        )

        # AI RCA runs regardless of decision so the user can see the LLM's
        # take alongside the deterministic policy outcome. The function is a
        # no-op (returns a clear sentinel) when ENABLE_AI_RCA is false.
        rca_text = ai_rca_task(
            workflow="autocon5_quarantine_bgp",
            device=device, peer_address=peer_address, ev=ev,
        )

        if decision.decision != "proceed":
            print(f"✅ [flow] no action ({decision.decision} — {decision.reason})")
            return {
                "device": device, "peer_address": peer_address, "action": "none",
                "decision": {"ok": decision.ok, "decision": decision.decision,
                             "reason": decision.reason, "details": decision.details},
                "evidence_summary": ev.summary(),
                "ai_rca": rca_text,
            }

        silence_id = quarantine_task(device=device, peer_address=peer_address, minutes=quarantine_minutes)
        logger.info("Quarantine applied: silence_id=%s", silence_id)
        annotate_action_task(
            workflow="autocon5_quarantine_bgp",
            device=device, peer_address=peer_address, silence_id=silence_id,
        )
        return {
            "device": device, "peer_address": peer_address,
            "action": "quarantine", "silence_id": silence_id,
            "decision": {"ok": decision.ok, "decision": decision.decision,
                         "reason": decision.reason, "details": decision.details},
            "evidence_summary": ev.summary(),
            "ai_rca": rca_text,
        }


@flow(log_prints=True, flow_run_name="resolved_bgp | {device}:{peer_address}")
def resolved_bgp_flow(
    device: str, peer_address: str,
    afi_safi: str = "ipv4-unicast", instance_name: str = "default",
) -> None:
    print(f"🧊 [flow] resolved_bgp_flow {device}:{peer_address}")
    with tags(
        f"device:{device}", f"peer_address:{peer_address}",
        f"afi_safi:{afi_safi}", f"instance:{instance_name}",
        "status:resolved",
    ):
        decision = Decision(ok=False, decision="resolved", reason="Alert resolved")
        annotate_decision_task(
            workflow="autocon5_quarantine_bgp",
            device=device, peer_address=peer_address, decision=decision,
        )


# ---------------------------------------------------------------------------
# Alert receiver — entrypoint that the webhook invokes via run_deployment().
# ---------------------------------------------------------------------------


def _extract_bgp_fields(labels: dict[str, str]) -> dict[str, str]:
    return {
        "device": labels.get("device") or labels.get("hostname") or "",
        "peer_address": labels.get("peer_address") or labels.get("peer") or labels.get("neighbor") or labels.get("interface") or "",
        "afi_safi": labels.get("afi_safi_name") or labels.get("afi_safi") or "ipv4-unicast",
        "instance_name": labels.get("name") or labels.get("instance_name") or "default",
    }


@flow(log_prints=True, flow_run_name="alert_receiver | {alertname}:{status}")
def alert_receiver(alertname: str, status: str, alert_group: dict[str, Any]) -> None:
    logger = get_run_logger()
    status = alert_group.get("status", status)
    group_labels = alert_group.get("groupLabels") or {}
    alertname = group_labels.get("alertname") or alertname
    alerts = alert_group.get("alerts") or []

    print(f"📩 [receiver] alertname={alertname} status={status} alerts_in_group={len(alerts)}")

    if alertname not in {"BgpSessionNotUp"}:
        print(f"🙈 [receiver] ignoring alertname={alertname} (only BgpSessionNotUp drives the demo today)")
        return

    for idx, a in enumerate(alerts, start=1):
        labels = a.get("labels") or {}
        fields = _extract_bgp_fields(labels)
        device, peer_address = fields["device"], fields["peer_address"]

        if not device or not peer_address:
            logger.warning("skipping alert %d/%d: missing device/peer_address. labels=%s", idx, len(alerts), labels)
            continue

        if status == "firing":
            quarantine_bgp_flow(
                device=device, peer_address=peer_address,
                afi_safi=fields["afi_safi"], instance_name=fields["instance_name"],
            )
        else:
            resolved_bgp_flow(
                device=device, peer_address=peer_address,
                afi_safi=fields["afi_safi"], instance_name=fields["instance_name"],
            )
