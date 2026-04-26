"""`autocon5 evidence DEVICE PEER` — inspect what the Prefect flow would see.

Mirrors the evidence bundle the workshop SDK collects in
`automation/workshop_sdk.py`, but renders it as Rich panels + tables for a
human reader. Useful for:

  * teaching what's in an "evidence bundle" before showing the Prefect run
  * debugging when a quarantine flow does something unexpected
  * letting attendees write their own queries against the same shape
"""
from __future__ import annotations

import json
from typing import Annotated, Any

import typer
from nobs._console import console, fail, warn
from nobs.clients import InfrahubClient, LokiClient, PromClient
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table


# Mirror of the Telegraf enum mapping used elsewhere.
_ADMIN_MAP = {1: "enable", 2: "disable"}
_OPER_MAP = {1: "up", 2: "down", 3: "idle", 4: "connect", 5: "active"}


_DEVICE_QUERY = """
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


def evidence(
    device: Annotated[str, typer.Argument(help="Device name (e.g. srl1).")],
    peer: Annotated[str, typer.Argument(help="Peer IP address (e.g. 10.1.99.2).")],
    afi_safi: Annotated[str, typer.Option("--afi-safi")] = "ipv4-unicast",
    instance: Annotated[str, typer.Option("--instance")] = "default",
    log_minutes: Annotated[int, typer.Option("--log-minutes")] = 10,
    log_limit: Annotated[int, typer.Option("--log-limit")] = 20,
    prom_url: Annotated[str, typer.Option(envvar="PROMETHEUS_URL")] = "http://localhost:9090",
    loki_url: Annotated[str, typer.Option(envvar="LOKI_URL")] = "http://localhost:3001",
    infrahub_url: Annotated[str, typer.Option(envvar="INFRAHUB_ADDRESS")] = "http://localhost:8000",
    token: Annotated[str, typer.Option(envvar="INFRAHUB_API_TOKEN")] = "",
) -> None:
    """Print the SoT gate, BGP metrics snapshot, recent log lines, and a policy hint
    for the given (device, peer) pair."""
    if not token:
        fail("INFRAHUB_API_TOKEN is required.")
        raise typer.Exit(code=1)
    if "infrahub-server" in infrahub_url:
        infrahub_url = "http://localhost:8000"

    sot = _fetch_sot(infrahub_url, token, device, peer, afi_safi)
    metrics = _fetch_metrics(prom_url, device, peer, afi_safi, instance)
    logs = _fetch_logs(loki_url, device, peer, log_minutes, log_limit)
    decision = _policy_hint(sot, metrics)

    console.print()
    _render_sot(sot)
    _render_metrics(metrics)
    _render_logs(logs)
    _render_decision(decision)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def _fetch_sot(url: str, token: str, device: str, peer: str, afi_safi: str) -> dict[str, Any]:
    client = InfrahubClient(url, token=token)
    try:
        data = client.query(_DEVICE_QUERY, {"name": device})
    except Exception as e:  # noqa: BLE001
        return {"found": False, "reason": f"Infrahub query failed: {e}"}

    edges = ((data.get("WorkshopDevice") or {}).get("edges")) or []
    if not edges:
        return {"found": False, "reason": "device not found in Infrahub"}

    node = edges[0]["node"]
    bgp_edges = ((node.get("bgp_sessions") or {}).get("edges")) or []

    def _v(field: dict | None) -> Any:
        return field.get("value") if isinstance(field, dict) else None

    sessions = [
        {
            "peer_address": _v(e["node"].get("peer_address")),
            "afi_safi": _v(e["node"].get("afi_safi")),
            "expected_state": _v(e["node"].get("expected_state")),
            "remote_as": _v(e["node"].get("remote_as")),
            "expected_prefixes_received": _v(e["node"].get("expected_prefixes_received")),
            "reason": _v(e["node"].get("reason")),
        }
        for e in bgp_edges
    ]
    session = next(
        (s for s in sessions if s["peer_address"] == peer and (s["afi_safi"] or "ipv4-unicast") == afi_safi),
        None,
    )

    return {
        "found": True,
        "device": _v(node.get("name")),
        "site": _v(node.get("site_name")),
        "role": _v(node.get("role")),
        "maintenance": bool(_v(node.get("maintenance"))),
        "intended_peer": session is not None,
        "expected_state": (session or {}).get("expected_state"),
        "session": session,
        "reason": (session or {}).get("reason"),
        "all_sessions": sessions,
    }


def _fetch_metrics(prom_url: str, device: str, peer: str, afi_safi: str, instance: str) -> dict[str, float]:
    client = PromClient(prom_url)
    base = (
        f'device="{device}",peer_address="{peer}",'
        f'afi_safi_name="{afi_safi}",name="{instance}"'
    )

    def _first(query: str, default: float = 0.0) -> float:
        try:
            result = client.instant(query)
        except Exception:
            return default
        if not result:
            return default
        try:
            return float(result[0]["value"][1])
        except (KeyError, IndexError, ValueError):
            return default

    return {
        "admin_state": _first(f"bgp_admin_state{{{base}}}", default=-1),
        "oper_state": _first(f"bgp_oper_state{{{base}}}", default=-1),
        "received_routes": _first(f"bgp_received_routes{{{base}}}"),
        "sent_routes": _first(f"bgp_sent_routes{{{base}}}"),
        "active_routes": _first(f"bgp_active_routes{{{base}}}"),
        "suppressed_routes": _first(f"bgp_suppressed_routes{{{base}}}"),
    }


def _fetch_logs(loki_url: str, device: str, peer: str, minutes: int, limit: int) -> list[str]:
    client = LokiClient(loki_url)
    query = f'{{device="{device}"}} != "license" |~ "(bgp|BGP|neighbor|session|route|ipv4-unicast|{peer})"'
    try:
        return client.query_range(query, minutes=minutes, limit=limit)
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_sot(sot: dict[str, Any]) -> None:
    if not sot.get("found"):
        console.print(
            Panel.fit(
                f"[fail]device not found in Infrahub.[/]\n[muted]{sot.get('reason', '')}[/]",
                title="Source of truth",
                border_style="red",
            )
        )
        return
    body = (
        f"device          [label]{sot['device']}[/]   site=[muted]{sot.get('site')}[/]  role=[muted]{sot.get('role')}[/]\n"
        f"maintenance     {'[warn]true[/]' if sot.get('maintenance') else '[ok]false[/]'}\n"
        f"intended peer   {'[ok]yes[/]' if sot.get('intended_peer') else '[fail]no[/]'}"
    )
    if sot.get("intended_peer"):
        es = sot.get("expected_state") or "—"
        es_styled = "[ok]" + es + "[/]" if es == "established" else "[warn]" + es + "[/]"
        body += f"\nexpected state  {es_styled}"
        if sot.get("reason"):
            body += f"\nreason          [muted]{sot['reason']}[/]"
        sess = sot.get("session") or {}
        if sess.get("remote_as"):
            body += f"\nremote_as       {sess['remote_as']}"
    console.print(Panel(body, title="Source of truth (Infrahub)", border_style="green"))


def _render_metrics(metrics: dict[str, float]) -> None:
    table = Table(title="BGP metrics snapshot (Prometheus)", show_lines=False, header_style="label")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("Decoded")

    for name in ("admin_state", "oper_state", "received_routes", "sent_routes", "active_routes", "suppressed_routes"):
        v = metrics.get(name, 0)
        decoded = "—"
        if name == "admin_state":
            decoded = _ADMIN_MAP.get(int(v), "unknown") if v not in (-1, None) else "—"
        elif name == "oper_state":
            decoded = _OPER_MAP.get(int(v), "unknown") if v not in (-1, None) else "—"
        v_str = f"{int(v)}" if isinstance(v, (int, float)) and float(v).is_integer() else str(v)
        table.add_row(name, v_str, decoded)

    console.print()
    console.print(table)


def _render_logs(logs: list[str]) -> None:
    console.print()
    if not logs:
        console.print(Panel.fit("[muted]No relevant log lines in the window.[/]", title="Loki", border_style="yellow"))
        return
    body = "\n".join(logs)
    syntax = Syntax(body, "log", theme="ansi_dark", word_wrap=True)
    console.print(Panel(syntax, title=f"Loki — last {len(logs)} relevant line(s)", border_style="cyan"))


def _render_decision(decision: dict[str, str]) -> None:
    style = {"proceed": "red", "skip": "yellow", "stop": "magenta"}.get(decision["decision"], "blue")
    console.print()
    console.print(
        Panel.fit(
            f"[label]decision[/]: [{style}]{decision['decision']}[/]\n"
            f"[label]reason  [/]: {decision['reason']}",
            title="Policy hint",
            border_style=style,
        )
    )


# ---------------------------------------------------------------------------
# Policy (mirrors workshop_sdk.DecisionPolicy.evaluate)
# ---------------------------------------------------------------------------


def _policy_hint(sot: dict[str, Any], metrics: dict[str, float]) -> dict[str, str]:
    if not sot.get("found", False):
        return {"decision": "stop", "reason": sot.get("reason", "device not found in SoT")}
    if sot.get("maintenance"):
        return {"decision": "skip", "reason": "device under maintenance"}
    if not sot.get("intended_peer"):
        return {"decision": "skip", "reason": "peer not intended in SoT"}
    expected = (sot.get("expected_state") or "established").lower()
    if expected in {"down", "disabled"}:
        return {"decision": "skip", "reason": "SoT expects this peer to be down/disabled"}
    admin = int(metrics.get("admin_state", -1))
    oper = int(metrics.get("oper_state", -1))
    if admin == 1 and oper == 1:
        return {"decision": "skip", "reason": "peer matches SoT intent (enabled + up)"}
    return {"decision": "proceed", "reason": "SoT expects peer up, but metrics show mismatch"}
