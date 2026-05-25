"""`nobs autocon5 flap-interface` — declarative BGP cascade via sonda /scenarios.

Builds a v2 scenario body that flaps the per-device `oper_state` metric,
gates per-peer BGP metrics (and a UPDOWN log stream) behind a `while:`
clause on the flap signal, and freezes the in/out octet counters during
the down phase via gated `step` entries with `delay.close.snap_to: null`.
Posts the body once to `/scenarios`; sonda's runtime drives the cascade
and Telegraf scrapes sonda's aggregate `/metrics` endpoint the same way
it scrapes the baseline.

Sonda resolves `while: ref:` per compilation unit (one ref namespace per
POST), so gated counters and their gate signal must be colocated in the
same POST. The cascade DELETEs baseline scenarios for the flapped
interface and per-peer BGP, POSTs the cascade body as the sole emitter
during the window, and a detached cleanup subprocess re-POSTs the
baselines once the cascade reaches `finished`.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import time
from typing import Annotated, Any

import requests
import typer
from nobs._console import console, fail, ok, warn
from rich.table import Table

from autocon5_workshop.flap_topology import Peer, peers_for

_BGP_DOWN_OPER = 2.0
_BGP_DOWN_NEIGHBOR = 1.0
_BGP_DOWN_PREFIXES = 0.0

_BGP_UP_OPER = 1.0
_BGP_UP_NEIGHBOR = 1.0
_BGP_UP_PREFIXES = 10.0

# Per-device baseline metric names and label-key conventions. The cascade
# emits via sonda's aggregate /metrics endpoint, same as baseline, with
# matching raw names and labels — Telegraf renames both alike. The
# cascade DELETEs baseline scenarios for the affected interface and peers
# so its samples replace baseline in the aggregated output rather than
# competing with it.
_BASELINE_METRICS: dict[str, dict[str, Any]] = {
    "srl1": {
        "interface_metrics": [
            "srl_interface_oper_state",
            "srl_interface_in_octets",
            "srl_interface_out_octets",
        ],
        "bgp_metrics": [
            "srl_bgp_oper_state",
            "srl_bgp_neighbor_state",
            "srl_bgp_prefixes_accepted",
            "srl_bgp_received_routes",
            "srl_bgp_sent_routes",
            "srl_bgp_active_routes",
        ],
        "in_octets_metric": "srl_interface_in_octets",
        "out_octets_metric": "srl_interface_out_octets",
        "oper_state_metric": "srl_interface_oper_state",
        "interface_label": "name",
        "device_label": "source",
        "peer_label": "peer_address",
        "asn_label": "neighbor_asn",
        "collection_type": "gnmi",
        "in_step": 125000.0,
        "out_step": 62500.0,
    },
    "srl2": {
        "interface_metrics": [
            "ifOperStatus",
            "ifHCInOctets",
            "ifHCOutOctets",
        ],
        "bgp_metrics": [
            "cbgpPeerOperStatus",
            "bgpPeerState",
            "cbgpPeerAcceptedPrefixes",
            "bgpPeerInPrefixes",
            "bgpPeerOutPrefixes",
            "cbgpPeerActivePrefixes",
        ],
        "in_octets_metric": "ifHCInOctets",
        "out_octets_metric": "ifHCOutOctets",
        "oper_state_metric": "ifOperStatus",
        "interface_label": "ifDescr",
        "device_label": "agent_host",
        "peer_label": "bgpPeerRemoteAddr",
        "asn_label": "bgpPeerRemoteAs",
        "collection_type": "snmp",
        "in_step": 125000.0,
        "out_step": 62500.0,
    },
}


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
    prom_query_url: Annotated[
        str,
        typer.Option(
            "--prom-query-url",
            envvar="SONDA_PROM_QUERY_URL",
            help="Prometheus query API (used to seed the cascade's gated counter from the canonical series' current value).",
        ),
    ] = "http://localhost:9090",
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

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Discover every baseline scenario the cascade should replace (per-interface
    # metrics for the affected interface + per-peer BGP metrics for each
    # peer) and capture the canonical octet counter values from Prometheus,
    # then DELETE the baselines so cascade entries become the sole emitter.
    # A detached cleanup subprocess re-POSTs the baselines after the cascade
    # reaches `finished` — see flap_cleanup.py.
    cascade_baseline_ids = _discover_cascade_baseline_ids(sonda_url, device, interface, peers, headers)
    in_octet_start, out_octet_start = _query_baseline_octet_values(prom_query_url, device, interface)
    if cascade_baseline_ids:
        _delete_scenarios(sonda_url, cascade_baseline_ids, headers)

    body = _build_cascade(
        device=device,
        interface=interface,
        peers=peers,
        duration=duration,
        up_duration=up_duration,
        down_duration=down_duration,
        cascade_delay=cascade_delay,
        loki_url=loki_url,
        in_octet_start=in_octet_start,
        out_octet_start=out_octet_start,
    )

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
        if cascade_baseline_ids:
            _spawn_baseline_cleanup(
                sonda_url=sonda_url,
                device=device,
                interface=interface,
                peers=peers,
                cascade_ids=[],
                api_key=api_key,
                duration=duration,
            )
        raise typer.Exit(code=1) from exc

    payload = response.json()
    created = _flatten_created(payload)
    if not created:
        fail(f"unexpected response shape: {json.dumps(payload)[:300]}")
        raise typer.Exit(code=1)

    cascade_ids = [item["id"] for item in created]
    if cascade_baseline_ids:
        _spawn_baseline_cleanup(
            sonda_url=sonda_url,
            device=device,
            interface=interface,
            peers=peers,
            cascade_ids=cascade_ids,
            api_key=api_key,
            duration=duration,
        )

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
    loki_url: str,
    in_octet_start: float = 0.0,
    out_octet_start: float = 0.0,
) -> dict[str, Any]:
    """Assemble the v2 scenario body for the interface→BGP cascade."""
    cfg = _BASELINE_METRICS[device]
    interface_label = cfg["interface_label"]
    primary_id = "primary_flap"
    interface_labels = {
        interface_label: interface,
        "collection_type": cfg["collection_type"],
    }

    scenarios: list[dict[str, Any]] = [
        {
            "id": primary_id,
            "signal_type": "metrics",
            "name": cfg["oper_state_metric"],
            "generator": {
                "type": "flap",
                "up_duration": up_duration,
                "down_duration": down_duration,
                "enum": "oper_state",
            },
            "labels": dict(interface_labels),
        }
    ]

    for peer in peers:
        scenarios.extend(
            _flap_bgp_entries(
                device=device,
                peer=peer,
                up_duration=up_duration,
                down_duration=down_duration,
                cascade_delay=cascade_delay,
            )
        )

    scenarios.extend(
        _gated_octet_entries(
            device=device,
            interface=interface,
            primary_id=primary_id,
            interface_labels=interface_labels,
            in_start=in_octet_start,
            out_start=out_octet_start,
            cascade_delay=cascade_delay,
        )
    )

    scenarios.append(
        _gated_updown_log_entry(
            device=device,
            interface=interface,
            upstream_id=primary_id,
            cascade_delay=cascade_delay,
            loki_url=loki_url,
        )
    )

    return {
        "version": 2,
        "kind": "runnable",
        "scenario_name": f"autocon5-cascade-{device}-{interface.replace('/', '-')}",
        "category": "network",
        "description": f"AutoCon5 BGP cascade — declarative while: gating on {device}:{interface}.",
        "defaults": {
            "rate": 1,
            "duration": duration,
            "labels": {cfg["device_label"]: device},
        },
        "scenarios": scenarios,
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


def _flap_bgp_entries(
    *,
    device: str,
    peer: Peer,
    up_duration: str,
    down_duration: str,
    cascade_delay: str,
) -> list[dict[str, Any]]:
    """Build cascade BGP entries using `flap` generators with phase-shifted timing.

    Each BGP metric per peer becomes one cascade scenario that cycles in
    lockstep with `primary_flap`'s cycle, but offset so BGP lags interface
    on the down transition (matching real BGP hold-down timer behavior)
    and recovers simultaneously on the up transition.

    BGP up_duration   = primary_up + cascade_delay
    BGP down_duration = primary_down - cascade_delay
    BGP cycle         = primary cycle (so they re-sync each cycle).
    """
    cfg = _BASELINE_METRICS[device]
    bgp_metric_names = cfg["bgp_metrics"]
    base_labels = _bgp_entry_labels(device, peer)
    safe_peer = peer.address.replace(".", "_")

    up_s = _parse_duration_secs(up_duration)
    down_s = _parse_duration_secs(down_duration)
    delay_s = _parse_duration_secs(cascade_delay)
    bgp_up = f"{up_s + delay_s:g}s"
    bgp_down = f"{max(down_s - delay_s, 0.0):g}s"

    up_down_pairs = [
        (_BGP_UP_OPER, _BGP_DOWN_OPER),
        (_BGP_UP_NEIGHBOR, _BGP_DOWN_NEIGHBOR),
        (_BGP_UP_PREFIXES, _BGP_DOWN_PREFIXES),
        (_BGP_UP_PREFIXES, _BGP_DOWN_PREFIXES),
        (_BGP_UP_PREFIXES, _BGP_DOWN_PREFIXES),
        (_BGP_UP_PREFIXES, _BGP_DOWN_PREFIXES),
    ]

    entries: list[dict[str, Any]] = []
    for metric_name, (up_val, down_val) in zip(bgp_metric_names, up_down_pairs, strict=True):
        if up_val == down_val:
            entries.append(
                {
                    "id": f"{metric_name}_{safe_peer}",
                    "signal_type": "metrics",
                    "name": metric_name,
                    "generator": {"type": "constant", "value": up_val},
                    "labels": base_labels,
                }
            )
        else:
            entries.append(
                {
                    "id": f"{metric_name}_{safe_peer}",
                    "signal_type": "metrics",
                    "name": metric_name,
                    "generator": {
                        "type": "flap",
                        "up_duration": bgp_up,
                        "down_duration": bgp_down,
                        "up_value": up_val,
                        "down_value": down_val,
                    },
                    "labels": base_labels,
                }
            )
    return entries


def _gated_updown_log_entry(
    *,
    device: str,
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


def _bgp_entry_labels(device: str, peer: Peer) -> dict[str, str]:
    """Per-peer BGP labels mirroring the baseline shape for `device`."""
    cfg = _BASELINE_METRICS[device]
    return {
        cfg["peer_label"]: peer.address,
        cfg["asn_label"]: str(peer.asn),
        "afi_safi_name": "ipv4-unicast",
        "name": "default",
        "collection_type": cfg["collection_type"],
    }


def _flatten_created(payload: dict) -> list[dict]:
    if isinstance(payload.get("scenarios"), list):
        return list(payload["scenarios"])
    if "id" in payload:
        return [payload]
    return []


def _discover_cascade_baseline_ids(
    sonda_url: str,
    device: str,
    interface: str,
    peers: list[Peer],
    headers: dict[str, str],
) -> list[str]:
    """Find baseline scenario UUIDs the cascade should DELETE.

    sonda's /scenarios listing doesn't expose labels, so we filter by
    metric name then GET each candidate's /metrics to inspect labels.
    """
    cfg = _BASELINE_METRICS.get(device)
    if cfg is None:
        return []
    interface_metric_names = set(cfg["interface_metrics"])
    bgp_metric_names = set(cfg["bgp_metrics"])
    intf_token = f'{cfg["interface_label"]}="{interface}"'
    device_token = f'{cfg["device_label"]}="{device}"'
    peer_tokens = [f'{cfg["peer_label"]}="{p.address}"' for p in peers]
    base = sonda_url.rstrip("/")

    try:
        r = requests.get(f"{base}/scenarios", headers=headers, timeout=5)
        r.raise_for_status()
    except requests.RequestException as exc:
        warn(f"failed to list scenarios for cascade baseline discovery: {exc}")
        return []

    all_scenarios = r.json().get("scenarios", [])
    interface_candidates = [
        s["id"] for s in all_scenarios if s.get("name") in interface_metric_names and s.get("state") == "running"
    ]
    bgp_candidates = [
        s["id"] for s in all_scenarios if s.get("name") in bgp_metric_names and s.get("state") == "running"
    ]

    matching: list[str] = []
    for sid in interface_candidates:
        try:
            m = requests.get(f"{base}/scenarios/{sid}/metrics", headers=headers, timeout=5)
        except requests.RequestException:
            continue
        if m.ok and intf_token in m.text and device_token in m.text:
            matching.append(sid)
    if peer_tokens:
        for sid in bgp_candidates:
            try:
                m = requests.get(f"{base}/scenarios/{sid}/metrics", headers=headers, timeout=5)
            except requests.RequestException:
                continue
            if not m.ok or device_token not in m.text:
                continue
            if any(pt in m.text for pt in peer_tokens):
                matching.append(sid)
    return matching


def _query_baseline_octet_values(prom_query_url: str, device: str, interface: str) -> tuple[float, float]:
    """Return current `interface_in/out_octets` values from Prometheus."""
    base = prom_query_url.rstrip("/")
    queries = {
        "in": f'interface_in_octets{{device="{device}",name="{interface}"}}',
        "out": f'interface_out_octets{{device="{device}",name="{interface}"}}',
    }
    values: dict[str, float] = {"in": 0.0, "out": 0.0}
    for direction, query in queries.items():
        try:
            r = requests.get(
                f"{base}/api/v1/query",
                params={"query": query},
                timeout=5,
            )
            r.raise_for_status()
            results = r.json().get("data", {}).get("result", [])
        except requests.RequestException:
            continue
        if not results:
            continue
        try:
            values[direction] = float(results[0]["value"][1])
        except (KeyError, IndexError, ValueError, TypeError):
            continue
    return values["in"], values["out"]


def _delete_scenarios(sonda_url: str, ids: list[str], headers: dict[str, str]) -> None:
    """Best-effort DELETE for each id. Silent on individual failure."""
    base = sonda_url.rstrip("/")
    for sid in ids:
        with contextlib.suppress(requests.RequestException):
            requests.delete(f"{base}/scenarios/{sid}", headers=headers, timeout=5)


def _gated_octet_entries(
    *,
    device: str,
    interface: str,
    primary_id: str,
    interface_labels: dict[str, str],
    in_start: float,
    out_start: float,
    cascade_delay: str,
) -> list[dict[str, Any]]:
    """Build the gated in/out octet step counters for the cascade.

    The counters tick during the cascade's up phase and pause (with position
    preserved via `delay.close.snap_to: null`) during the down phase, then
    resume from the frozen value when the gate reopens.
    """
    cfg = _BASELINE_METRICS[device]
    while_clause = {"ref": primary_id, "op": "<", "value": 2}
    return [
        {
            "id": "interface_in_octets_gated",
            "signal_type": "metrics",
            "name": cfg["in_octets_metric"],
            "metric_type": "counter",
            "generator": {"type": "step", "start": in_start, "step_size": cfg["in_step"] / 10.0},
            "while": while_clause,
            "delay": {"open": cascade_delay, "close": {"duration": "0s", "snap_to": None}},
            "labels": dict(interface_labels),
        },
        {
            "id": "interface_out_octets_gated",
            "signal_type": "metrics",
            "name": cfg["out_octets_metric"],
            "metric_type": "counter",
            "generator": {"type": "step", "start": out_start, "step_size": cfg["out_step"] / 10.0},
            "while": while_clause,
            "delay": {"open": cascade_delay, "close": {"duration": "0s", "snap_to": None}},
            "labels": dict(interface_labels),
        },
    ]


def _spawn_baseline_cleanup(
    *,
    sonda_url: str,
    device: str,
    interface: str,
    peers: list[Peer],
    cascade_ids: list[str],
    api_key: str,
    duration: str,
) -> None:
    """Detach a subprocess that re-POSTs the deleted baseline after cascade ends.

    Passes the cascade duration so the subprocess can sleep for that
    window instead of polling every few seconds — cleanup runs ~5s after
    cascade scenarios finish.
    """
    args = [
        sys.executable,
        "-m",
        "autocon5_workshop.flap_cleanup",
        "--sonda-url",
        sonda_url,
        "--device",
        device,
        "--interface",
        interface,
        "--api-key",
        api_key,
        "--cascade-duration",
        duration,
    ]
    for cid in cascade_ids:
        args.extend(["--cascade-id", cid])
    for p in peers:
        args.extend(["--peer", f"{p.address}:{p.asn}"])
    with contextlib.suppress(Exception):
        subprocess.Popen(  # noqa: S603
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


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
