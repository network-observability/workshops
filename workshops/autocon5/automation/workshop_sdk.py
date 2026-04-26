"""
Workshop SDK for the AutoCon5 hands-on lab.

Adapted from the `netobs_workshop_sdk` shipped with `network-observability-lab`,
with two material differences:

  - **InfrahubClient** replaces `NautobotClient`. The query surface used by the
    Prefect flow is identical (`build_bgp_intent_gate`, `is_device_in_maintenance`,
    `get_intended_bgp_session`) so the flow code didn't need to change.

  - **AI-assisted RCA** is wired into the `WorkshopSDK` and gated by the
    `ENABLE_AI_RCA` env var. Two providers are supported (OpenAI, Anthropic);
    when the flag is off the helper returns a clear "AI RCA disabled" message
    so the workflow still runs end-to-end without an external API key.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Telegraf enum decode helpers — keep symbol/numeric mappings together so
# alert/dashboard authors and flow authors agree on what 1 vs 5 means.
# ---------------------------------------------------------------------------

ADMIN_MAP = {1: "enable", 2: "disable"}
OPER_MAP = {1: "up", 2: "down", 3: "idle", 4: "connect", 5: "active"}


def decode_bgp_states(metrics: dict[str, float]) -> dict[str, str]:
    def _as_int(v: float | int | None) -> int | None:
        if v is None:
            return None
        try:
            return int(v)
        except Exception:
            return None

    out: dict[str, str] = {}
    admin = _as_int(metrics.get("admin_state"))
    oper = _as_int(metrics.get("oper_state"))
    if admin is not None:
        out["admin_state"] = ADMIN_MAP.get(admin, str(admin))
    if oper is not None:
        out["oper_state"] = OPER_MAP.get(oper, str(oper))
    return out


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def to_rfc3339(ts: dt.datetime) -> str:
    return ts.isoformat(timespec="seconds").replace("+00:00", "Z")


def first_prom_value(result: list[dict], default: float = 0.0) -> float:
    if not result:
        return float(default)
    try:
        return float(result[0]["value"][1])
    except Exception:
        return float(default)


def bgp_metrics_hint(metrics: dict[str, float], decoded: dict[str, str] | None = None) -> str:
    admin = metrics.get("admin_state", -1)
    oper = metrics.get("oper_state", -1)
    rx = metrics.get("received_routes", 0)
    tx = metrics.get("sent_routes", 0)
    sup = metrics.get("suppressed_routes", 0)
    act = metrics.get("active_routes", 0)

    if admin in (-1, None) or oper in (-1, None):
        return "Insufficient metrics to infer a hint (missing admin_state/oper_state)."
    if admin == 2:
        return "Admin DISABLED → likely intentionally shut (maintenance / config intent)."
    if oper != 1:
        oper_txt = (decoded or {}).get("oper_state") or str(int(oper))
        return f"Oper not UP ({oper_txt}) → likely session not established (reachability/auth/timers)."
    if rx == 0 and tx == 0 and act == 0:
        return "Session UP but no routes → possible policy/filtering/AFI mismatch or peer not advertising."
    if sup > 0:
        return "Routes are being suppressed → likely policy/validation suppressing candidates."
    if rx > 0 and act == 0:
        return "Routes received but none active → import policy/validation rejecting routes."
    if act > 0:
        return "Session UP with active routes → looks healthy; check logs for intermittent flaps."
    return "Metrics present but inconclusive (need more context)."


# ---------------------------------------------------------------------------
# Endpoints + Decision policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Endpoints:
    infrahub_url: str = "http://infrahub-server:8000"
    prom_url: str = "http://prometheus:9090"
    alertmanager_url: str = "http://alertmanager:9093"
    loki_url: str = "http://loki:3001"


@dataclass
class EvidenceBundle:
    device: str
    peer_address: str
    afi_safi: str
    instance_name: str

    metrics: dict[str, float] = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    sot: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        decoded = self.sot.get("decoded") or {}
        return {
            "device": self.device,
            "peer_address": self.peer_address,
            "afi_safi": self.afi_safi,
            "instance_name": self.instance_name,
            "bgp_metrics_hint": bgp_metrics_hint(self.metrics or {}, decoded=decoded),
            "metrics": self.metrics,
            "log_lines": len(self.logs),
            "sot": {
                "found": self.sot.get("found"),
                "maintenance": self.sot.get("maintenance"),
                "intended_peer": self.sot.get("intended_peer"),
                "expected_state": self.sot.get("expected_state"),
                "site": self.sot.get("site"),
                "role": self.sot.get("role"),
                "reason": self.sot.get("reason"),
            },
            "decoded": decoded,
        }

    def to_rca_payload(self, max_log_lines: int = 40) -> dict[str, Any]:
        return {
            "metrics": self.metrics,
            "logs": self.logs[:max_log_lines],
            "sot": self.sot,
        }


@dataclass(frozen=True)
class Decision:
    ok: bool
    decision: str  # "proceed" | "skip" | "stop" | "resolved"
    reason: str
    details: dict[str, Any] = field(default_factory=dict)


class DecisionPolicy:
    """
    Two-stage policy used by Part 3:
      1) SoT-only: stop if device unknown, skip if maintenance/not-intended/
         expected-down.
      2) SoT + metrics: skip if metrics match intent, otherwise proceed.
    """

    def __init__(self, require_admin_up_for_quarantine: bool = False):
        self.require_admin_up_for_quarantine = require_admin_up_for_quarantine

    @staticmethod
    def _as_int(x: object, default: int = -1) -> int:
        try:
            return int(float(x))  # type: ignore[arg-type]
        except Exception:
            return default

    def evaluate(self, sot_gate: dict[str, Any], metrics: dict[str, float] | None = None) -> Decision:
        if not sot_gate.get("found", True):
            return Decision(False, "stop", sot_gate.get("reason", "device not found in SoT"))

        if sot_gate.get("maintenance"):
            return Decision(False, "skip", "device under maintenance")

        if not sot_gate.get("intended_peer"):
            return Decision(False, "skip", "peer not intended in SoT")

        expected = (sot_gate.get("expected_state") or "established").lower()
        if expected in {"down", "disabled"}:
            return Decision(False, "skip", "SoT expects this peer to be down/disabled")

        if metrics is None:
            return Decision(True, "proceed", "SoT expects up; metrics not provided (collect evidence)")

        admin = self._as_int(metrics.get("admin_state", -1))
        oper = self._as_int(metrics.get("oper_state", -1))
        admin_ok = (admin == 1)
        oper_ok = (oper == 1)

        if admin_ok and oper_ok:
            return Decision(False, "skip", "peer matches SoT intent (enabled + up)")

        if self.require_admin_up_for_quarantine and not (admin_ok and not oper_ok):
            return Decision(
                False,
                "skip",
                "metrics gate not met (expected admin_state=enable and oper_state!=up)",
                {"admin_state": admin, "oper_state": oper, "expected_state": expected},
            )

        return Decision(
            True,
            "proceed",
            "SoT expects peer up, but metrics show mismatch",
            {"expected_state": expected, "admin_state": admin, "oper_state": oper},
        )


# ---------------------------------------------------------------------------
# Infrastructure clients
# ---------------------------------------------------------------------------


class PromClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def instant(self, query: str) -> list[dict]:
        r = requests.get(
            f"{self.base_url}/api/v1/query",
            params={"query": query},
            timeout=self.timeout,
        )
        r.raise_for_status()
        return r.json().get("data", {}).get("result", [])


class LokiClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def query_range(self, query: str, minutes: int = 10, limit: int = 200) -> list[str]:
        end = now_utc()
        start = end - dt.timedelta(minutes=minutes)
        params = {
            "query": query,
            "start": int(start.timestamp() * 1e9),
            "end": int(end.timestamp() * 1e9),
            "limit": limit,
            "direction": "BACKWARD",
        }
        r = requests.get(f"{self.base_url}/loki/api/v1/query_range", params=params, timeout=self.timeout)
        r.raise_for_status()
        out: list[str] = []
        for stream in r.json().get("data", {}).get("result", []):
            for _, line in stream.get("values", []):
                out.append(line)
        return out[:limit]

    def annotate(self, labels: dict[str, str], message: str) -> None:
        ts = str(time.time_ns())
        payload = {"streams": [{"stream": labels, "values": [[ts, message]]}]}
        r = requests.post(f"{self.base_url}/loki/api/v1/push", json=payload, timeout=self.timeout)
        r.raise_for_status()


class AlertmanagerClient:
    def __init__(self, base_url: str, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def create_silence(
        self,
        matchers: list[dict[str, Any]],
        minutes: int = 20,
        created_by: str = "prefect-workshop",
        comment: str = "Workshop quarantine: suppress repeat notifications while investigating.",
    ) -> str:
        starts = now_utc()
        ends = starts + dt.timedelta(minutes=minutes)
        body = {
            "matchers": matchers,
            "startsAt": to_rfc3339(starts),
            "endsAt": to_rfc3339(ends),
            "createdBy": created_by,
            "comment": comment,
        }
        r = requests.post(f"{self.base_url}/api/v2/silences", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("silenceID", "")


class InfrahubClient:
    """GraphQL client for the workshop's Infrahub schema.

    Implements the same surface as the original Nautobot helper:
    - get_device(name) -> dict | None
    - is_device_in_maintenance(device_dict) -> bool
    - get_intended_bgp_session(device_dict, afi_safi, peer_address) -> dict | None
    - build_bgp_intent_gate(device, peer_address, afi_safi) -> dict
    """

    QUERY = """
    query DeviceIntent($name: String!) {
      WorkshopDevice(name__value: $name) {
        edges {
          node {
            id
            name { value }
            maintenance { value }
            site_name { value }
            role { value }
            bgp_sessions {
              edges {
                node {
                  id
                  peer_address { value }
                  afi_safi { value }
                  expected_state { value }
                  remote_as { value }
                  expected_prefixes_received { value }
                  reason { value }
                }
              }
            }
          }
        }
      }
    }
    """

    def __init__(self, base_url: str, token: str | None = None, timeout: int = 10):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._token = token or os.environ.get("INFRAHUB_API_TOKEN", "")

    def _post(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "X-INFRAHUB-KEY": self._token,
        }
        r = requests.post(
            f"{self.base_url}/graphql",
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=self.timeout,
        )
        r.raise_for_status()
        payload = r.json()
        if "errors" in payload:
            raise RuntimeError(f"Infrahub GraphQL error: {payload['errors']}")
        return payload.get("data") or {}

    def get_device(self, device_name: str) -> dict | None:
        data = self._post(self.QUERY, {"name": device_name})
        edges = ((data.get("WorkshopDevice") or {}).get("edges")) or []
        if not edges:
            return None
        node = edges[0]["node"]
        bgp_edges = ((node.get("bgp_sessions") or {}).get("edges")) or []

        def _v(field: dict | None) -> Any:
            return field.get("value") if isinstance(field, dict) else None

        return {
            "id": node.get("id"),
            "name": _v(node.get("name")),
            "maintenance": bool(_v(node.get("maintenance"))),
            "site": _v(node.get("site_name")),
            "role": _v(node.get("role")),
            "bgp_sessions": [
                {
                    "id": e["node"].get("id"),
                    "peer_address": _v(e["node"].get("peer_address")),
                    "afi_safi": _v(e["node"].get("afi_safi")),
                    "expected_state": _v(e["node"].get("expected_state")),
                    "remote_as": _v(e["node"].get("remote_as")),
                    "expected_prefixes_received": _v(e["node"].get("expected_prefixes_received")),
                    "reason": _v(e["node"].get("reason")),
                }
                for e in bgp_edges
            ],
        }

    @staticmethod
    def is_device_in_maintenance(device_obj: dict) -> bool:
        return bool(device_obj.get("maintenance", False))

    @staticmethod
    def get_intended_bgp_session(device_obj: dict, afi_safi: str, peer_address: str) -> dict | None:
        for s in device_obj.get("bgp_sessions") or []:
            if s.get("peer_address") == peer_address and (s.get("afi_safi") or "ipv4-unicast") == afi_safi:
                return s
        return None

    def build_bgp_intent_gate(self, device: str, peer_address: str, afi_safi: str) -> dict[str, Any]:
        dev = self.get_device(device)
        if not dev:
            return {"found": False, "reason": "device not found in Infrahub"}

        session = self.get_intended_bgp_session(dev, afi_safi=afi_safi, peer_address=peer_address)
        return {
            "found": True,
            "maintenance": self.is_device_in_maintenance(dev),
            "intended_peer": session is not None,
            "expected_state": (session or {}).get("expected_state"),
            "session": session,
            "device": dev.get("name"),
            "site": dev.get("site"),
            "role": dev.get("role"),
            "reason": (session or {}).get("reason"),
        }


# ---------------------------------------------------------------------------
# AI RCA — opt-in, gated by env var
# ---------------------------------------------------------------------------


_AI_DISABLED_MSG = (
    "AI RCA disabled (set ENABLE_AI_RCA=true and provide an API key to enable). "
    "The deterministic decision-policy result above is still authoritative."
)


def _build_rca_prompt(device: str, peer_address: str, evidence: dict[str, Any]) -> str:
    return (
        "You are a network ops assistant.\n"
        "We detected a BGP session issue.\n\n"
        f"ALERT:\n- device: {device}\n- peer: {peer_address}\n\n"
        "EVIDENCE (Prom metrics snapshot):\n"
        f"{json.dumps(evidence.get('metrics', {}), indent=2)}\n\n"
        "EVIDENCE (Relevant log lines):\n"
        f"{json.dumps(evidence.get('logs', [])[:40], indent=2)}\n\n"
        "EVIDENCE (Source-of-truth gate):\n"
        f"{json.dumps(evidence.get('sot', {}), indent=2, default=str)}\n\n"
        "TASK:\n"
        "Write a short RCA for a workshop demo.\n"
        "- Max 1200 characters\n"
        "- Use headings: Most likely cause / Immediate actions / What to verify next\n"
        "- Be specific: mention device + peer IP.\n"
        "- If evidence is insufficient, say what is missing.\n"
    )


def llm_rca(device: str, peer_address: str, evidence: dict[str, Any]) -> str:
    """Run an opt-in LLM RCA call.

    Honours `ENABLE_AI_RCA`, `AI_RCA_PROVIDER` (openai|anthropic), `AI_RCA_MODEL`,
    and the relevant API-key env vars. On any failure (flag off, key missing,
    HTTP error) returns a clear sentinel string instead of raising — the caller
    annotates whatever comes back into Loki, so the workshop demo never gets
    stuck on a missing token.
    """
    if (os.environ.get("ENABLE_AI_RCA", "false").lower() not in {"1", "true", "yes"}):
        return _AI_DISABLED_MSG

    provider = (os.environ.get("AI_RCA_PROVIDER") or "openai").lower()
    model = os.environ.get("AI_RCA_MODEL") or ("gpt-4o-mini" if provider == "openai" else "claude-haiku-4-5-20251001")
    prompt = _build_rca_prompt(device, peer_address, evidence)

    try:
        if provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                return "AI RCA disabled (OPENAI_API_KEY not set)."
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": prompt}]},
                timeout=30,
            )
            r.raise_for_status()
            return (r.json()["choices"][0]["message"].get("content") or "").strip() or _AI_DISABLED_MSG

        if provider == "anthropic":
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                return "AI RCA disabled (ANTHROPIC_API_KEY not set)."
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 600,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            r.raise_for_status()
            content = r.json().get("content") or []
            if isinstance(content, list) and content:
                return (content[0].get("text") or "").strip() or _AI_DISABLED_MSG
            return _AI_DISABLED_MSG

        return f"AI RCA disabled (unknown AI_RCA_PROVIDER={provider!r})."
    except Exception as e:  # noqa: BLE001 — we never want the demo to crash here
        return f"AI RCA call failed: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Top-level SDK aggregating the above
# ---------------------------------------------------------------------------


@dataclass
class WorkshopSDK:
    endpoints: Endpoints = field(
        default_factory=lambda: Endpoints(
            infrahub_url=os.environ.get("INFRAHUB_ADDRESS", "http://infrahub-server:8000"),
            prom_url=os.environ.get("PROMETHEUS_URL", "http://prometheus:9090"),
            alertmanager_url=os.environ.get("ALERTMANAGER_URL", "http://alertmanager:9093"),
            loki_url=os.environ.get("LOKI_URL", "http://loki:3001"),
        )
    )
    timeout: int = 10

    def __post_init__(self) -> None:
        self.prom = PromClient(self.endpoints.prom_url, timeout=self.timeout)
        self.loki = LokiClient(self.endpoints.loki_url, timeout=self.timeout)
        self.am = AlertmanagerClient(self.endpoints.alertmanager_url, timeout=self.timeout)
        self.sot = InfrahubClient(self.endpoints.infrahub_url, timeout=self.timeout)

    # --- gates / queries --------------------------------------------------
    def bgp_gate(self, device: str, peer_address: str, afi_safi: str) -> dict[str, Any]:
        return self.sot.build_bgp_intent_gate(device=device, peer_address=peer_address, afi_safi=afi_safi)

    def annotate(self, labels: dict[str, str], message: str) -> None:
        self.loki.annotate(labels=labels, message=message)

    def annotate_decision(self, workflow: str, device: str, peer_address: str, decision: str, message: str) -> None:
        self.annotate(
            labels={
                "source": "prefect",
                "workflow": workflow,
                "device": device,
                "peer_address": peer_address,
                "decision": decision,
            },
            message=message,
        )

    # --- BGP-specific helpers --------------------------------------------
    def bgp_queries(self, device: str, peer_address: str, afi_safi: str, instance_name: str) -> dict[str, str]:
        base = (
            f'device="{device}",peer_address="{peer_address}",'
            f'afi_safi_name="{afi_safi}",name="{instance_name}"'
        )
        return {
            "admin_state": f"bgp_admin_state{{{base}}}",
            "oper_state": f"bgp_oper_state{{{base}}}",
            "received_routes": f"bgp_received_routes{{{base}}}",
            "sent_routes": f"bgp_sent_routes{{{base}}}",
            "suppressed_routes": f"bgp_suppressed_routes{{{base}}}",
            "active_routes": f"bgp_active_routes{{{base}}}",
        }

    def bgp_metrics_snapshot(
        self, device: str, peer_address: str, afi_safi: str, instance_name: str
    ) -> dict[str, float]:
        qs = self.bgp_queries(device, peer_address, afi_safi, instance_name)
        return {
            "admin_state": first_prom_value(self.prom.instant(qs["admin_state"]), default=-1),
            "oper_state": first_prom_value(self.prom.instant(qs["oper_state"]), default=-1),
            "received_routes": first_prom_value(self.prom.instant(qs["received_routes"]), default=0),
            "sent_routes": first_prom_value(self.prom.instant(qs["sent_routes"]), default=0),
            "suppressed_routes": first_prom_value(self.prom.instant(qs["suppressed_routes"]), default=0),
            "active_routes": first_prom_value(self.prom.instant(qs["active_routes"]), default=0),
        }

    def bgp_logql(self, device: str, peer_address: str) -> str:
        return f'{{device="{device}"}} != "license" |~ "(bgp|BGP|neighbor|session|route|ipv4-unicast|{peer_address})"'

    def bgp_logs(self, device: str, peer_address: str, minutes: int = 10, limit: int = 200) -> list[str]:
        return self.loki.query_range(
            self.bgp_logql(device=device, peer_address=peer_address), minutes=minutes, limit=limit
        )

    def quarantine_bgp(self, device: str, peer_address: str, minutes: int = 20) -> str:
        return self.am.create_silence(
            matchers=[
                {"name": "alertname", "value": "BgpSessionNotUp", "isRegex": False},
                {"name": "device", "value": device, "isRegex": False},
                {"name": "peer_address", "value": peer_address, "isRegex": False},
            ],
            minutes=minutes,
        )

    def collect_bgp_evidence(
        self,
        device: str,
        peer_address: str,
        afi_safi: str,
        instance_name: str,
        log_minutes: int = 10,
        log_limit: int = 200,
    ) -> EvidenceBundle:
        ev = EvidenceBundle(device=device, peer_address=peer_address, afi_safi=afi_safi, instance_name=instance_name)
        ev.sot = self.bgp_gate(device=device, peer_address=peer_address, afi_safi=afi_safi)
        ev.metrics = self.bgp_metrics_snapshot(device=device, peer_address=peer_address, afi_safi=afi_safi, instance_name=instance_name)
        ev.sot["decoded"] = decode_bgp_states(ev.metrics)
        ev.logs = self.bgp_logs(device=device, peer_address=peer_address, minutes=log_minutes, limit=log_limit)
        return ev

    def rca(self, device: str, peer_address: str, evidence: EvidenceBundle) -> str:
        return llm_rca(device=device, peer_address=peer_address, evidence=evidence.to_rca_payload())
