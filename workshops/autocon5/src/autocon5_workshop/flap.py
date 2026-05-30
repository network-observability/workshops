"""`nobs autocon5 flap-interface` — inversion-pattern BGP cascade.

The baseline scenarios in `sonda/catalog/srl{1,2}-metrics.yaml` carry
`while: scenario_name=autocon5-cascade-<device>-<scope>` clauses with
`if_unresolved: open`. At rest the baselines run as `unresolved` and emit
normally via `?include_state=running,unresolved`. flap-interface POSTs
short-lived cascade scenarios with matching `scenario_name`s; baselines
transition to `paused` while a cascade runs and back to `unresolved`/
`running` when the cascade `finished`. No DELETE-and-replace, no
cleanup subprocess — sonda 1.13.1 handles the lifecycle.

One POST per affected scope:
  - Interface flap: `autocon5-cascade-<device>-intf-<interface-key>`
    (cascade_active signal + oper_state DOWN + frozen octets + UPDOWN log)
  - Each cascading healthy peer: `autocon5-cascade-<device>-bgp-<peer-key>`
    (cascade_active signal + BGP DOWN values for that peer; phase-shifted
    so BGP lags interface on DOWN and recovers simultaneously on UP)
"""

from __future__ import annotations

import contextlib
import time
from typing import Annotated, Any

import requests
import typer
from nobs._console import console, fail, ok, warn
from rich.table import Table

from autocon5_workshop.flap_topology import Peer, peers_for

# Cascade DOWN values per BGP metric. Values mirror the broken-peer
# baseline overrides so the cascade flap looks like a real BGP collapse.
# Per-device because srl2 uses Cisco SNMP raw names. `name` field below is
# the BGP4-MIB FSM enum (1=ESTABLISHED, 2=IDLE) — keeps `bgp_neighbor_state`
# panel mappings happy.
_DEVICE_CONFIG: dict[str, dict[str, Any]] = {
    "srl1": {
        "device_label": "source",
        "interface_label": "name",
        "peer_label": "peer_address",
        "asn_label": "neighbor_asn",
        "collection_type": "gnmi",
        "oper_state_metric": "srl_interface_oper_state",
        "bgp_metrics": {
            "srl_bgp_oper_state": 2.0,
            "srl_bgp_neighbor_state": 2.0,
            "srl_bgp_prefixes_accepted": 0.0,
            "srl_bgp_received_routes": 0.0,
            "srl_bgp_sent_routes": 0.0,
            "srl_bgp_active_routes": 0.0,
        },
    },
    "srl2": {
        "device_label": "agent_host",
        "interface_label": "ifDescr",
        "peer_label": "bgpPeerRemoteAddr",
        "asn_label": "bgpPeerRemoteAs",
        "collection_type": "snmp",
        "oper_state_metric": "ifOperStatus",
        "bgp_metrics": {
            "cbgpPeerOperStatus": 2.0,
            "bgpPeerState": 2.0,
            "cbgpPeerAcceptedPrefixes": 0.0,
            "bgpPeerInPrefixes": 0.0,
            "bgpPeerOutPrefixes": 0.0,
            "cbgpPeerActivePrefixes": 0.0,
        },
    },
}

# Broken peers — their baselines already emit down values and have no
# `while:` clause, so we skip the cascade for them.
_BROKEN_PEERS: frozenset[tuple[str, str]] = frozenset(
    {
        ("srl1", "10.1.99.2"),
        ("srl2", "10.1.11.1"),
    }
)


def interface_cascade_name(device: str, interface: str) -> str:
    """Deterministic scenario_name the baseline's `while:` references."""
    return f"autocon5-cascade-{device}-intf-{interface.replace('/', '-')}"


def bgp_cascade_name(device: str, peer_address: str) -> str:
    """Deterministic scenario_name the baseline's `while:` references."""
    return f"autocon5-cascade-{device}-bgp-{peer_address.replace('.', '-')}"


def flap_interface(
    device: Annotated[str, typer.Option("--device", "-d", help="Device name (e.g. srl1).")] = "srl1",
    interface: Annotated[
        str,
        typer.Option("--interface", "-i", help="Interface name (e.g. ethernet-1/1)."),
    ] = "ethernet-1/1",
    duration: Annotated[
        str,
        typer.Option(
            "--duration",
            help="Bounded lifetime of the cascade (sonda duration string, e.g. 4m).",
        ),
    ] = "4m",
    up_duration: Annotated[
        str,
        typer.Option(
            "--up-duration",
            help="Time the interface stays up before each down phase (sonda duration string).",
        ),
    ] = "30s",
    down_duration: Annotated[
        str,
        typer.Option(
            "--down-duration",
            help="Time the interface stays down per cycle. Long enough for "
            "BgpSessionNotUp (for: 30s) to fire by default.",
        ),
    ] = "60s",
    cascade_delay: Annotated[
        str,
        typer.Option(
            "--cascade-delay",
            help="Hold-down between interface down and BGP collapse (BGP cascade is phase-shifted by this amount).",
        ),
    ] = "10s",
    no_cascade: Annotated[
        bool,
        typer.Option(
            "--no-cascade",
            help="Skip the BGP cascade — emit only the interface flap and "
            "UPDOWN log stream. Use to trip PeerInterfaceFlapping without "
            "bringing BGP down.",
        ),
    ] = False,
    sonda_url: Annotated[
        str,
        typer.Option(
            "--sonda-url",
            envvar="SONDA_SERVER_URL",
            help="Base sonda-server URL (the cascade is posted to /scenarios).",
        ),
    ] = "http://localhost:8085",
    loki_url: Annotated[
        str,
        typer.Option(
            "--loki-url",
            envvar="SONDA_LOKI_SINK_URL",
            help="Loki URL the UPDOWN log entry publishes to.",
        ),
    ] = "http://loki:3001",
    api_key: Annotated[
        str,
        typer.Option(
            "--sonda-api-key",
            envvar="SONDA_API_KEY",
            help="Bearer token if sonda-server has SONDA_API_KEY set; empty otherwise.",
        ),
    ] = "",
    follow: Annotated[
        bool,
        typer.Option(
            "--follow/--no-follow",
            help="Poll the cascade scenarios until they all `finished`. "
            "`--no-follow` returns immediately after registration.",
        ),
    ] = False,
) -> None:
    """Register a declarative inversion-pattern BGP cascade via `POST /scenarios`."""
    if device not in _DEVICE_CONFIG:
        fail(f"unknown device {device}; expected one of {sorted(_DEVICE_CONFIG)}")
        raise typer.Exit(code=1)

    peers = [] if no_cascade else peers_for(device, interface)
    healthy_peers = [p for p in peers if (device, p.address) not in _BROKEN_PEERS]
    if peers and not healthy_peers and not no_cascade:
        warn(f"no healthy BGP peers mapped to {device}:{interface}; running interface flap only.")

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    posts: list[tuple[str, str, dict[str, Any]]] = [
        (
            "interface",
            interface_cascade_name(device, interface),
            _build_interface_cascade(
                device=device,
                interface=interface,
                duration=duration,
                up_duration=up_duration,
                down_duration=down_duration,
                cascade_delay=cascade_delay,
                loki_url=loki_url,
            ),
        ),
    ]
    for peer in healthy_peers:
        posts.append(
            (
                f"bgp {peer.address}",
                bgp_cascade_name(device, peer.address),
                _build_bgp_cascade(
                    device=device,
                    peer=peer,
                    duration=duration,
                    up_duration=up_duration,
                    down_duration=down_duration,
                    cascade_delay=cascade_delay,
                ),
            )
        )

    peer_summary = ", ".join(p.address for p in healthy_peers) if healthy_peers else "interface only"
    if no_cascade:
        peer_summary = "no-cascade"
    scenarios_url = f"{sonda_url.rstrip('/')}/scenarios"
    console.print(
        f"Posting inversion cascade for [label]{device}:{interface}[/] "
        f"(peers: [label]{peer_summary}[/], duration [label]{duration}[/], "
        f"cycle [label]{up_duration} up / {down_duration} down[/]) to [muted]{scenarios_url}[/]"
    )

    all_created: list[tuple[str, str, list[dict]]] = []
    for label, scenario_name, body in posts:
        try:
            response = requests.post(scenarios_url, json=body, headers=headers, timeout=10)
            response.raise_for_status()
        except requests.RequestException as exc:
            detail = ""
            if exc.response is not None:
                with contextlib.suppress(Exception):
                    detail = f" — {exc.response.text}"
            fail(f"POST {scenario_name!r} failed: {exc}{detail}")
            raise typer.Exit(code=1) from exc
        all_created.append((label, scenario_name, _flatten_created(response.json())))

    table = Table(show_header=True, header_style="bold")
    table.add_column("cascade")
    table.add_column("scenario_name")
    table.add_column("entries")
    for label, scenario_name, created in all_created:
        ids = ", ".join(item.get("id", "")[:8] for item in created)
        table.add_row(label, scenario_name, ids or "—")
    console.print(table)

    if not follow:
        total = sum(len(c) for _, _, c in all_created)
        ok(f"registered {total} scenario(s) across {len(posts)} cascade body(s); duration {duration}")
        console.print(
            f"  Baselines auto-resume when cascade reaches `finished` (~{duration}).\n"
            f"  Inspect:  [muted]curl {sonda_url.rstrip('/')}/scenarios[/]\n"
            f"  Stop early: [muted]curl -X DELETE {sonda_url.rstrip('/')}/scenarios/<id>[/]"
        )
        return

    all_ids = [c["id"] for _, _, created in all_created for c in created if "id" in c]
    _follow_until_done(sonda_url, all_ids, headers)
    ok("all cascade scenarios finished; baselines back to running")


def _build_interface_cascade(
    *,
    device: str,
    interface: str,
    duration: str,
    up_duration: str,
    down_duration: str,
    cascade_delay: str,
    loki_url: str,
) -> dict[str, Any]:
    cfg = _DEVICE_CONFIG[device]
    intf_label = cfg["interface_label"]
    interface_labels = {intf_label: interface, "collection_type": cfg["collection_type"]}

    scenarios: list[dict[str, Any]] = [
        # The cascade signal — drives the cascade's oper_state override and
        # the baseline's `while:` clause (cross-POST resolution via scenario_name).
        # Octet counters use Pattern C (`delay.close.snap_to` on baseline
        # pack overrides) — they freeze at last value during DOWN via the
        # `held` lifecycle, no cascade-side emitter needed.
        {
            "id": "cascade_active",
            "signal_type": "metrics",
            "name": "cascade_active",
            "generator": {
                "type": "flap",
                "up_duration": up_duration,
                "down_duration": down_duration,
                "up_value": 0,
                "down_value": 1,
            },
        },
        # oper_state=DOWN while cascade_active>0. Baseline goes to paused
        # (no snap_to) so cascade's value takes over cleanly.
        {
            "id": "cascade_oper_state",
            "signal_type": "metrics",
            "name": cfg["oper_state_metric"],
            "generator": {"type": "constant", "value": 2.0},
            "while": {"ref": "cascade_active", "op": ">", "value": 0},
            "labels": dict(interface_labels),
        },
        _updown_log_entry(device=device, interface=interface, cascade_delay=cascade_delay, loki_url=loki_url),
    ]

    return {
        "version": 2,
        "kind": "runnable",
        "scenario_name": interface_cascade_name(device, interface),
        "category": "network",
        "description": f"AutoCon5 inversion cascade — pauses {device}:{interface} baseline during DOWN phase.",
        "defaults": {
            "rate": 1,
            "duration": duration,
            "labels": {cfg["device_label"]: device},
        },
        "scenarios": scenarios,
    }


def _build_bgp_cascade(
    *,
    device: str,
    peer: Peer,
    duration: str,
    up_duration: str,
    down_duration: str,
    cascade_delay: str,
) -> dict[str, Any]:
    """Per-peer BGP cascade body.

    Phase-shifted so BGP lags interface DOWN by `cascade_delay` and recovers
    simultaneously with interface UP. Implemented by extending up_duration
    and shrinking down_duration by `cascade_delay` — same total cycle so
    the two flap generators stay in lockstep.
    """
    cfg = _DEVICE_CONFIG[device]
    up_s = _parse_duration_secs(up_duration)
    down_s = _parse_duration_secs(down_duration)
    delay_s = _parse_duration_secs(cascade_delay)
    bgp_up = f"{up_s + delay_s:g}s"
    bgp_down = f"{max(down_s - delay_s, 0.0):g}s"

    peer_labels = {
        cfg["peer_label"]: peer.address,
        cfg["asn_label"]: str(peer.asn),
        "afi_safi_name": "ipv4-unicast",
        "name": "default",
        "collection_type": cfg["collection_type"],
    }

    scenarios: list[dict[str, Any]] = [
        {
            "id": "cascade_active",
            "signal_type": "metrics",
            "name": "cascade_active",
            "generator": {
                "type": "flap",
                "up_duration": bgp_up,
                "down_duration": bgp_down,
                "up_value": 0,
                "down_value": 1,
            },
        },
    ]
    for metric_name, down_value in cfg["bgp_metrics"].items():
        scenarios.append(
            {
                "id": f"cascade_{metric_name}",
                "signal_type": "metrics",
                "name": metric_name,
                "generator": {"type": "constant", "value": down_value},
                "while": {"ref": "cascade_active", "op": ">", "value": 0},
                "labels": dict(peer_labels),
            }
        )

    return {
        "version": 2,
        "kind": "runnable",
        "scenario_name": bgp_cascade_name(device, peer.address),
        "category": "network",
        "description": f"AutoCon5 inversion cascade — pauses {device} peer {peer.address} baseline during BGP-DOWN phase.",
        "defaults": {
            "rate": 1,
            "duration": duration,
            "labels": {cfg["device_label"]: device},
        },
        "scenarios": scenarios,
    }


def _updown_log_entry(*, device: str, interface: str, cascade_delay: str, loki_url: str) -> dict[str, Any]:
    """UPDOWN log entry — emits during DOWN phase, posts direct to Loki."""
    return {
        "id": "updown_logs_down",
        "signal_type": "logs",
        "name": "updown_logs_down",
        "rate": 0.5,
        "while": {"ref": "cascade_active", "op": ">", "value": 0},
        "delay": {"open": cascade_delay, "close": "0s"},
        "labels": {
            "device": device,
            "type": "srlinux",
            "vendor_facility": "srlinux",
            "vendor_facility_process": "UPDOWN",
            "interface": interface,
            "interface_status": "down",
            "pipeline": "direct",
        },
        "log_generator": {
            "type": "template",
            "templates": [
                {"message": f"Interface {interface} changed state to down"},
            ],
            "severity_weights": {"warning": 1.0},
        },
        "encoder": {"type": "json_lines"},
        "sink": {"type": "loki", "url": loki_url},
    }


def _parse_duration_secs(duration: str) -> float:
    """Parse a sonda duration string ('30s', '5m', '1h', '500ms') to seconds."""
    s = duration.strip().lower()
    if s.endswith("ms"):
        return float(s[:-2]) / 1000.0
    if s.endswith("s"):
        return float(s[:-1])
    if s.endswith("m"):
        return float(s[:-1]) * 60.0
    if s.endswith("h"):
        return float(s[:-1]) * 3600.0
    return float(s)


def _flatten_created(payload: dict) -> list[dict]:
    if isinstance(payload.get("scenarios"), list):
        return list(payload["scenarios"])
    if "id" in payload:
        return [payload]
    return []


def _follow_until_done(sonda_url: str, ids: list[str], headers: dict[str, str]) -> None:
    base = sonda_url.rstrip("/")
    pending = set(ids)
    while pending:
        time.sleep(5)
        for sid in list(pending):
            try:
                r = requests.get(f"{base}/scenarios/{sid}", headers=headers, timeout=5)
                r.raise_for_status()
            except requests.RequestException as exc:
                console.print(f"  [yellow]poll error on {sid}: {exc}[/]")
                continue
            doc = r.json()
            state = doc.get("state", "unknown")
            console.print(f"  {sid[:8]} state={state}")
            if state in ("finished", "stopped"):
                pending.discard(sid)
