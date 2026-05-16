"""`nobs autocon5 flap-interface` — declarative BGP cascade via sonda /scenarios.

Builds a v2 scenario body that flaps `interface_oper_state` and gates
per-peer BGP metrics (and a UPDOWN log stream) behind a `while:` clause
on the flap signal. Posts the body once to `/scenarios`; sonda's runtime
drives the cascade. Restore is automatic via gate-close: when the flap
returns to up, the gated entries pause and the lab's continuous emitters
resume publishing baseline values via Prometheus latest-sample-wins.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Annotated, Any

import requests
import typer
from nobs._console import console, fail, ok, warn
from rich.table import Table

from autocon5_workshop.flap_topology import Peer, bgp_labels, interface_labels, peers_for

_BGP_DOWN_OPER = 2.0
_BGP_DOWN_NEIGHBOR = 1.0
_BGP_DOWN_PREFIXES = 0.0

_BGP_UP_OPER = 1.0
_BGP_UP_NEIGHBOR = 1.0
_BGP_UP_PREFIXES = 10.0

_BGP_PREFIX_METRICS = (
    "bgp_prefixes_accepted",
    "bgp_received_routes",
    "bgp_sent_routes",
    "bgp_active_routes",
)

_CASCADE_PROVENANCE_KEYS = ("host", "instance", "job", "pipeline", "collection_type")

_SCRAPE_PROVENANCE_KEYS = ("host", "instance", "job")

_DEVICE_TELEGRAF_URLS = {
    "srl1": "http://telegraf-srl1:1316/api/v1/write",
}


def _resolve_routing(device: str, explicit_url: str) -> tuple[str, bool]:
    if explicit_url:
        return explicit_url, False
    telegraf_url = _DEVICE_TELEGRAF_URLS.get(device)
    if telegraf_url:
        return telegraf_url, True
    return "http://prometheus:9090/api/v1/write", False


def _cascade_default_labels(device: str, intf_labels: dict[str, str]) -> dict[str, str]:
    return {"device": device}


def _metric_provenance(intf_labels: dict[str, str]) -> dict[str, str]:
    """Provenance labels (host/instance/job/pipeline/collection_type) for metric entries."""
    return {key: intf_labels[key] for key in _CASCADE_PROVENANCE_KEYS if key in intf_labels}


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
            help="Bounded lifetime for every entry in the cascade (sonda duration string).",
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
            help="Hold-down between interface down and BGP collapse (maps to delay.open on the gated entries).",
        ),
    ] = "10s",
    no_cascade: Annotated[
        bool,
        typer.Option(
            "--no-cascade",
            help="Skip the BGP cascade — emit the interface flap and UPDOWN "
            "log stream only. Use to trip PeerInterfaceFlapping without "
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
    prom_url: Annotated[
        str,
        typer.Option(
            "--prom-url",
            envvar="SONDA_PROM_REMOTE_WRITE_URL",
            help="Remote_write URL for cascade metrics. Empty auto-routes per device.",
        ),
    ] = "",
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
            help="Poll the running scenario(s) until completion. `--no-follow` returns immediately after registration.",
        ),
    ] = False,
) -> None:
    """Register a declarative BGP cascade scenario via `POST /scenarios`."""
    peers = [] if no_cascade else peers_for(device, interface)
    if not peers and not no_cascade:
        warn(f"no BGP peers mapped to {device}:{interface}; running interface flap only.")

    resolved_prom_url, strip_provenance = _resolve_routing(device, prom_url)
    body = _build_cascade(
        device=device,
        interface=interface,
        peers=peers,
        duration=duration,
        up_duration=up_duration,
        down_duration=down_duration,
        cascade_delay=cascade_delay,
        prom_url=resolved_prom_url,
        loki_url=loki_url,
        strip_scrape_provenance=strip_provenance,
    )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    scenarios_url = f"{sonda_url.rstrip('/')}/scenarios"
    peer_summary = ", ".join(p.address for p in peers) if peers else "no BGP peers"
    console.print(
        f"Posting cascade for [label]{device}:{interface}[/] "
        f"(peers: [label]{peer_summary}[/], hold-down [label]{cascade_delay}[/], "
        f"down [label]{down_duration}[/]) to [muted]{scenarios_url}[/]"
    )

    try:
        response = requests.post(scenarios_url, json=body, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = ""
        if exc.response is not None:
            with contextlib.suppress(Exception):
                detail = f" — {exc.response.text}"
        fail(f"POST /scenarios failed: {exc}{detail}")
        raise typer.Exit(code=1) from exc

    payload = response.json()
    created = _flatten_created(payload)
    if not created:
        fail(f"unexpected response shape: {json.dumps(payload)[:300]}")
        raise typer.Exit(code=1)

    table = Table(show_header=True, header_style="bold")
    table.add_column("id")
    table.add_column("name")
    table.add_column("state")
    for item in created:
        table.add_row(item.get("id", ""), item.get("name", ""), item.get("state", ""))
    console.print(table)

    for w in payload.get("warnings", []) or []:
        console.print(f"  [yellow]warning:[/] {w}")

    if not follow:
        ids = ", ".join(item["id"] for item in created)
        ok(f"registered {len(created)} scenario(s): {ids}")
        console.print(
            "  Inspect:  [muted]curl {url}/scenarios[/]\n"
            "  Stop:     [muted]curl -X DELETE {url}/scenarios/<id>[/]".format(url=sonda_url.rstrip("/"))
        )
        return

    _follow_until_done(sonda_url, [item["id"] for item in created], headers)
    ok("all scenarios completed")


def _build_cascade(
    *,
    device: str,
    interface: str,
    peers: list[Peer],
    duration: str,
    up_duration: str,
    down_duration: str,
    cascade_delay: str,
    prom_url: str,
    loki_url: str,
    strip_scrape_provenance: bool = False,
) -> dict[str, Any]:
    """Assemble the v2 scenario body for the interface→BGP cascade."""
    intf_labels = interface_labels(device, interface)
    if strip_scrape_provenance:
        intf_labels = {k: v for k, v in intf_labels.items() if k not in _SCRAPE_PROVENANCE_KEYS}
    metric_prov = _metric_provenance(intf_labels)
    primary_id = "primary_flap"

    scenarios: list[dict[str, Any]] = [
        {
            "id": primary_id,
            "signal_type": "metrics",
            "name": "interface_oper_state",
            "generator": {
                "type": "flap",
                "up_duration": up_duration,
                "down_duration": down_duration,
                "enum": "oper_state",
            },
            "labels": {
                "name": interface,
                "intf_role": intf_labels.get("intf_role", "peer"),
                **metric_prov,
            },
        }
    ]

    for peer in peers:
        scenarios.extend(
            _gated_bgp_entries(
                device=device,
                peer=peer,
                upstream_id=primary_id,
                cascade_delay=cascade_delay,
                extra_labels=metric_prov,
            )
        )

    scenarios.append(
        _gated_updown_log_entry(
            interface=interface,
            upstream_id=primary_id,
            cascade_delay=cascade_delay,
            loki_url=loki_url,
        )
    )

    return {
        "version": 2,
        "scenario_name": f"autocon5-cascade-{device}-{interface.replace('/', '-')}",
        "category": "network",
        "description": f"AutoCon5 BGP cascade — declarative while: gating on {device}:{interface}.",
        "defaults": {
            "rate": 1,
            "duration": duration,
            "encoder": {"type": "remote_write"},
            "sink": {"type": "remote_write", "url": prom_url},
            "labels": _cascade_default_labels(device, intf_labels),
        },
        "scenarios": scenarios,
    }


def _gated_bgp_entries(
    *,
    device: str,
    peer: Peer,
    upstream_id: str,
    cascade_delay: str,
    extra_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    base_labels = {**_entry_only_bgp_labels(device, peer), **(extra_labels or {})}
    while_clause = {"ref": upstream_id, "op": ">", "value": 1}
    safe_peer = peer.address.replace(".", "_")

    entries: list[dict[str, Any]] = [
        _gated_metric_entry(
            entry_id=f"bgp_oper_state_{safe_peer}",
            metric_name="bgp_oper_state",
            value=_BGP_DOWN_OPER,
            snap_to=_BGP_UP_OPER,
            labels=base_labels,
            while_clause=while_clause,
            cascade_delay=cascade_delay,
        ),
        _gated_metric_entry(
            entry_id=f"bgp_neighbor_state_{safe_peer}",
            metric_name="bgp_neighbor_state",
            value=_BGP_DOWN_NEIGHBOR,
            snap_to=_BGP_UP_NEIGHBOR,
            labels=base_labels,
            while_clause=while_clause,
            cascade_delay=cascade_delay,
        ),
    ]
    for metric in _BGP_PREFIX_METRICS:
        entries.append(
            _gated_metric_entry(
                entry_id=f"{metric}_{safe_peer}",
                metric_name=metric,
                value=_BGP_DOWN_PREFIXES,
                snap_to=_BGP_UP_PREFIXES,
                labels=base_labels,
                while_clause=while_clause,
                cascade_delay=cascade_delay,
            )
        )
    return entries


def _gated_metric_entry(
    *,
    entry_id: str,
    metric_name: str,
    value: float,
    snap_to: float,
    labels: dict[str, str],
    while_clause: dict[str, Any],
    cascade_delay: str,
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "signal_type": "metrics",
        "name": metric_name,
        "generator": {"type": "constant", "value": value},
        "while": while_clause,
        "delay": {
            "open": cascade_delay,
            "close": {"duration": "0s", "snap_to": snap_to},
        },
        "labels": labels,
    }


def _gated_updown_log_entry(
    *,
    interface: str,
    upstream_id: str,
    cascade_delay: str,
    loki_url: str,
) -> dict[str, Any]:
    return {
        "id": "updown_logs_down",
        "signal_type": "logs",
        "name": "updown_logs_down",
        "rate": 0.5,
        "while": {"ref": upstream_id, "op": ">", "value": 1},
        "delay": {"open": cascade_delay, "close": "0s"},
        "labels": {
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


def _entry_only_bgp_labels(device: str, peer: Peer) -> dict[str, str]:
    """Per-peer labels that should land on the entry, not in defaults."""
    full = bgp_labels(device, peer.address, peer.asn)
    inherited = {"device", *_CASCADE_PROVENANCE_KEYS}
    return {k: v for k, v in full.items() if k not in inherited}


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
            if state == "finished":
                pending.discard(sid)
