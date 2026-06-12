"""
Prefect flows for AutoCon5 — Part 3 of the workshop.

The flow structure mirrors the Part 3 teaching diagram one-to-one: each block
in `alert → evidence → policy → action` is a flow, and each step inside a
block is a task.

    alert_receiver                                (Alert — webhook entrypoint)
       └── quarantine_bgp_flow                    (status=firing; orchestrates the cycle)
              ├── evidence_flow                   (Evidence)
              │      ├── fetch_sot                (Infrahub GraphQL — intent)
              │      ├── fetch_metrics            (Prometheus PromQL — reality)
              │      ├── fetch_logs               (Loki LogQL — recent history)
              │      └── assemble_evidence        (decode enums, bundle the three)
              ├── policy_flow                     (Policy)
              │      ├── evaluate_sot_gate        (stage 1 — SoT only)
              │      ├── evaluate_metrics_gate    (stage 2 — SoT + metrics; only if stage 1 passes)
              │      └── annotate_decision        (audit trail to Loki)
              └── action_flow                     (Action)
                     ├── ai_rca / ai_rca_skipped  (narrative — always writes a record)
                     └── if proceed:
                           ├── quarantine         (Alertmanager silence)
                           └── annotate_action    (audit trail to Loki)

       └── resolved_bgp_flow                      (status=resolved)
              └── annotate_decision

The three fetch tasks inside evidence_flow are submitted concurrently — the
sources are independent, and a retry on one source no longer re-fetches the
other two.

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
from workshop_sdk import (
    Decision,
    DecisionPolicy,
    EvidenceBundle,
    WorkshopSDK,
    decode_bgp_states,
    is_ai_rca_enabled,
)

# ---------------------------------------------------------------------------
# Evidence tasks
# ---------------------------------------------------------------------------


@task(retries=2, retry_delay_seconds=3, log_prints=True, task_run_name="fetch_sot[{device}:{peer_address}]")
def fetch_sot_task(device: str, peer_address: str, afi_safi: str) -> dict[str, Any]:
    print(f"🔎 [evidence] SoT gate for {device}:{peer_address} ({afi_safi})")
    return WorkshopSDK().bgp_gate(device=device, peer_address=peer_address, afi_safi=afi_safi)


@task(retries=2, retry_delay_seconds=3, log_prints=True, task_run_name="fetch_metrics[{device}:{peer_address}]")
def fetch_metrics_task(device: str, peer_address: str, afi_safi: str, instance_name: str) -> dict[str, float]:
    print(f"🔎 [evidence] BGP metrics snapshot for {device}:{peer_address}")
    return WorkshopSDK().bgp_metrics_snapshot(
        device=device, peer_address=peer_address, afi_safi=afi_safi, instance_name=instance_name
    )


@task(retries=2, retry_delay_seconds=3, log_prints=True, task_run_name="fetch_logs[{device}:{peer_address}]")
def fetch_logs_task(device: str, peer_address: str, log_minutes: int, log_limit: int) -> list[str]:
    print(f"🔎 [evidence] last {log_minutes}m of logs for {device}:{peer_address}")
    return WorkshopSDK().bgp_logs(device=device, peer_address=peer_address, minutes=log_minutes, limit=log_limit)


@task(log_prints=True, task_run_name="assemble_evidence[{device}:{peer_address}]")
def assemble_evidence_task(
    device: str,
    peer_address: str,
    afi_safi: str,
    instance_name: str,
    sot: dict[str, Any],
    metrics: dict[str, float],
    logs: list[str],
) -> EvidenceBundle:
    ev = EvidenceBundle(device=device, peer_address=peer_address, afi_safi=afi_safi, instance_name=instance_name)
    ev.sot = sot
    ev.metrics = metrics
    ev.sot["decoded"] = decode_bgp_states(metrics)
    ev.logs = logs
    print(
        "✅ [evidence] sot.found={} maintenance={} intended={} expected_state={} reason={!r}".format(
            ev.sot.get("found"),
            ev.sot.get("maintenance"),
            ev.sot.get("intended_peer"),
            ev.sot.get("expected_state"),
            ev.sot.get("reason"),
        )
    )
    print(f"   metrics={ev.metrics}")
    print(f"   logs collected: {len(ev.logs)} lines")
    return ev


# ---------------------------------------------------------------------------
# Policy tasks
# ---------------------------------------------------------------------------


@task(log_prints=True, task_run_name="evaluate_sot_gate[{device}:{peer_address}]")
def evaluate_sot_gate_task(device: str, peer_address: str, ev: EvidenceBundle) -> Decision:
    decision = DecisionPolicy().evaluate(ev.sot, metrics=None)
    print(f"🧠 [policy] stage1 SoT-only → {decision.decision} ({decision.reason})")
    return decision


@task(log_prints=True, task_run_name="evaluate_metrics_gate[{device}:{peer_address}]")
def evaluate_metrics_gate_task(device: str, peer_address: str, ev: EvidenceBundle) -> Decision:
    decision = DecisionPolicy().evaluate(ev.sot, metrics=ev.metrics)
    print(f"🧠 [policy] stage2 SoT+metrics → {decision.decision} ({decision.reason})")
    return decision


@task(log_prints=True, task_run_name="annotate_decision[{device}:{peer_address}]")
def annotate_decision_task(workflow: str, device: str, peer_address: str, decision: Decision) -> None:
    print(f"📝 [annotate] decision={decision.decision} reason={decision.reason}")
    sdk = WorkshopSDK()
    sdk.annotate_decision(
        workflow=workflow,
        device=device,
        peer_address=peer_address,
        decision=decision.decision,
        message=decision.reason,
    )


# ---------------------------------------------------------------------------
# Action tasks
# ---------------------------------------------------------------------------


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


@task(log_prints=True, task_run_name="ai_rca_skipped[{device}:{peer_address}]")
def ai_rca_skipped_task(workflow: str, device: str, peer_address: str, decision: Decision) -> str:
    """Write a brief annotation explaining why AI RCA was not run for this decision.

    Called when the policy decided anything other than `proceed`. Running an LLM
    on a decision the policy has already chosen *not* to act on wastes compute
    (and real money with a paid provider) and muddies the audit trail. We still
    write an `ai_rca=true` record so the existing Loki query surfaces *what was
    considered* — just with an explanatory message instead of a multi-section RCA.
    """
    msg = (
        f"AI RCA not run — policy decided {decision.decision} ({decision.reason}). "
        "Conserves compute / API cost when the policy has already decided not to act."
    )
    print(f"⏭️  [ai_rca] skipped (decision={decision.decision})")
    sdk = WorkshopSDK()
    sdk.annotate(
        labels={
            "source": "prefect",
            "workflow": workflow,
            "device": device,
            "peer_address": peer_address,
            "ai_rca": "true",
        },
        message=msg,
    )
    return msg


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
# Block flows — one per diagram block (evidence / policy / action)
# ---------------------------------------------------------------------------


@flow(log_prints=True, flow_run_name="evidence | {device}:{peer_address}")
def evidence_flow(
    device: str,
    peer_address: str,
    afi_safi: str = "ipv4-unicast",
    instance_name: str = "default",
    log_minutes: int = 30,
    log_limit: int = 50,
) -> EvidenceBundle:
    """Evidence block: three concurrent fetches (intent / reality / history), one bundle."""
    sot = fetch_sot_task.submit(device=device, peer_address=peer_address, afi_safi=afi_safi)
    metrics = fetch_metrics_task.submit(
        device=device, peer_address=peer_address, afi_safi=afi_safi, instance_name=instance_name
    )
    logs = fetch_logs_task.submit(
        device=device, peer_address=peer_address, log_minutes=log_minutes, log_limit=log_limit
    )
    return assemble_evidence_task(
        device=device,
        peer_address=peer_address,
        afi_safi=afi_safi,
        instance_name=instance_name,
        sot=sot,
        metrics=metrics,
        logs=logs,
    )


@flow(log_prints=True, flow_run_name="policy | {device}:{peer_address}")
def policy_flow(
    device: str,
    peer_address: str,
    ev: EvidenceBundle,
    workflow: str = "autocon5_quarantine_bgp",
) -> Decision:
    """Policy block: two-stage deterministic evaluation, then the audit record.

    Stage 2 only runs when stage 1 (SoT-only) doesn't short-circuit — so a
    maintenance-skip run shows a single evaluate task in the UI, while a
    proceed run shows both stages.
    """
    print(f"🧠 [policy] {device}:{peer_address}")
    decision = evaluate_sot_gate_task(device=device, peer_address=peer_address, ev=ev)
    if decision.decision not in {"stop", "skip"}:
        decision = evaluate_metrics_gate_task(device=device, peer_address=peer_address, ev=ev)
    annotate_decision_task(workflow=workflow, device=device, peer_address=peer_address, decision=decision)
    return decision


@flow(log_prints=True, flow_run_name="action | {device}:{peer_address}")
def action_flow(
    device: str,
    peer_address: str,
    decision: Decision,
    ev: EvidenceBundle,
    quarantine_minutes: int = 20,
    workflow: str = "autocon5_quarantine_bgp",
) -> dict[str, Any]:
    """Action block: AI narrative (always writes) + deterministic action (proceed only)."""
    # AI RCA branching:
    #   1. ENABLE_AI_RCA=false  → ai_rca_task writes the "disabled" annotation
    #      regardless of decision (the feature is off; that's the only honest
    #      message to write).
    #   2. ENABLE_AI_RCA=true + decision=proceed → real LLM narrative.
    #   3. ENABLE_AI_RCA=true + decision != proceed → ai_rca_skipped_task
    #      writes a brief "not run because policy said skip" annotation.
    #      Skips the LLM call entirely (saves compute / API cost, keeps the
    #      audit trail honest — SoT says "don't act", so we don't act
    #      anywhere, including the LLM step).
    if is_ai_rca_enabled() and decision.decision != "proceed":
        rca_text = ai_rca_skipped_task(
            workflow=workflow,
            device=device,
            peer_address=peer_address,
            decision=decision,
        )
    else:
        rca_text = ai_rca_task(
            workflow=workflow,
            device=device,
            peer_address=peer_address,
            ev=ev,
        )

    if decision.decision != "proceed":
        print(f"✅ [action] no deterministic action ({decision.decision} — {decision.reason})")
        return {"action": "none", "silence_id": None, "ai_rca": rca_text}

    silence_id = quarantine_task(device=device, peer_address=peer_address, minutes=quarantine_minutes)
    annotate_action_task(
        workflow=workflow,
        device=device,
        peer_address=peer_address,
        silence_id=silence_id,
    )
    return {"action": "quarantine", "silence_id": silence_id, "ai_rca": rca_text}


# ---------------------------------------------------------------------------
# Orchestrating flows
# ---------------------------------------------------------------------------


@flow(log_prints=True, flow_run_name="quarantine_bgp | {device}:{peer_address}")
def quarantine_bgp_flow(
    device: str,
    peer_address: str,
    afi_safi: str = "ipv4-unicast",
    instance_name: str = "default",
    log_minutes: int = 30,
    log_limit: int = 50,
    quarantine_minutes: int = 20,
) -> dict[str, Any]:
    logger = get_run_logger()
    print(f"⚙️  [flow] quarantine_bgp_flow {device}:{peer_address}")

    with tags(
        f"device:{device}",
        f"peer_address:{peer_address}",
        f"afi_safi:{afi_safi}",
        f"instance:{instance_name}",
        "action:quarantine",
    ):
        ev = evidence_flow(
            device=device,
            peer_address=peer_address,
            afi_safi=afi_safi,
            instance_name=instance_name,
            log_minutes=log_minutes,
            log_limit=log_limit,
        )

        decision = policy_flow(device=device, peer_address=peer_address, ev=ev)

        outcome = action_flow(
            device=device,
            peer_address=peer_address,
            decision=decision,
            ev=ev,
            quarantine_minutes=quarantine_minutes,
        )

        if outcome["action"] == "quarantine":
            logger.info("Quarantine applied: silence_id=%s", outcome["silence_id"])
        else:
            print(f"✅ [flow] no action ({decision.decision} — {decision.reason})")

        result: dict[str, Any] = {
            "device": device,
            "peer_address": peer_address,
            "action": outcome["action"],
            "decision": {
                "ok": decision.ok,
                "decision": decision.decision,
                "reason": decision.reason,
                "details": decision.details,
            },
            "evidence_summary": ev.summary(),
            "ai_rca": outcome["ai_rca"],
        }
        if outcome["action"] == "quarantine":
            result["silence_id"] = outcome["silence_id"]
        return result


@flow(log_prints=True, flow_run_name="resolved_bgp | {device}:{peer_address}")
def resolved_bgp_flow(
    device: str,
    peer_address: str,
    afi_safi: str = "ipv4-unicast",
    instance_name: str = "default",
) -> None:
    print(f"🧊 [flow] resolved_bgp_flow {device}:{peer_address}")
    with tags(
        f"device:{device}",
        f"peer_address:{peer_address}",
        f"afi_safi:{afi_safi}",
        f"instance:{instance_name}",
        "status:resolved",
    ):
        decision = Decision(ok=False, decision="resolved", reason="Alert resolved")
        annotate_decision_task(
            workflow="autocon5_quarantine_bgp",
            device=device,
            peer_address=peer_address,
            decision=decision,
        )


# ---------------------------------------------------------------------------
# Alert receiver — entrypoint that the webhook invokes via run_deployment().
# ---------------------------------------------------------------------------


def _extract_bgp_fields(labels: dict[str, str]) -> dict[str, str]:
    return {
        "device": labels.get("device") or labels.get("hostname") or "",
        "peer_address": labels.get("peer_address")
        or labels.get("peer")
        or labels.get("neighbor")
        or labels.get("interface")
        or "",
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
                device=device,
                peer_address=peer_address,
                afi_safi=fields["afi_safi"],
                instance_name=fields["instance_name"],
            )
        else:
            resolved_bgp_flow(
                device=device,
                peer_address=peer_address,
                afi_safi=fields["afi_safi"],
                instance_name=fields["instance_name"],
            )
