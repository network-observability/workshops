"""`nobs autocon5 flap-interface` — declarative BGP cascade via sonda /scenarios.

Builds a v2 scenario body that flaps `interface_oper_state`, gates per-peer
BGP metrics (and a UPDOWN log stream) behind a `while:` clause on the flap
signal, and freezes `interface_in/out_octets` counters during the down phase
via gated `step` entries with `delay.close.snap_to: null`. Posts the body
once to `/scenarios`; sonda's runtime drives the cascade.

The octet counters can't be gated against the baseline scenarios in
`srl1-metrics.yaml` directly because sonda resolves `while: ref:` per
compilation unit (one ref namespace per POST). The cascade is a separate
POST, so the gated counter and its gate signal have to be colocated in
the cascade body. We achieve that with DELETE-and-replace: the cascade
discovers the baseline octet scenarios for the flapped interface, deletes
them, POSTs the cascade (which includes gated step counters as the new
emitters), and a detached cleanup subprocess re-POSTs the baseline once
the cascade reaches `finished`. The pattern is explained in detail in
`~/.claude/projects/-Users-netpanda-projects-workshops/notes/
sonda-while-clause-cross-post-scoping.md` along with the upstream sonda
feature request (cross-POST `while:` ref resolution) that would let us
drop the orchestration.
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

_CASCADE_PROVENANCE_KEYS = ("instance", "job", "pipeline", "collection_type")

_SCRAPE_PROVENANCE_KEYS = ("instance", "job")

_DEVICE_TELEGRAF_URLS = {
    "srl1": "http://telegraf-srl1:1316/api/v1/write",
    "srl2": "http://telegraf-srl2:1326/api/v1/write",
}

# Per-device baseline metric names and label-key conventions. The cascade
# DELETEs baseline scenarios for the affected interface and peers, then
# becomes the sole emitter — eliminating Telegraf's prom_client merge
# race where baseline samples (interval-rounded timestamps) overwhelm
# cascade samples (sub-second timestamps) and make the cascade signal
# invisible in Prometheus.
_BASELINE_METRICS: dict[str, dict[str, Any]] = {
    "srl1": {
        # Per-interface raw metrics sonda emits (pre-Telegraf rename).
        "interface_metrics": [
            "srl_interface_oper_state",
            "srl_interface_in_octets",
            "srl_interface_out_octets",
        ],
        # Per-peer raw BGP metrics sonda emits.
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
        "collection_type": "snmp",
        "in_step": 125000.0,
        "out_step": 62500.0,
    },
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
    """Provenance labels (instance/job/pipeline/collection_type) for metric entries."""
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

    resolved_prom_url, strip_provenance = _resolve_routing(device, prom_url)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # Discover every baseline scenario the cascade should replace (per-interface
    # metrics for the affected interface + per-peer BGP metrics for each
    # peer) and capture the canonical octet counter values from Prometheus,
    # then DELETE the baselines so cascade entries become the sole emitter.
    # A detached cleanup subprocess re-POSTs the baselines after the cascade
    # reaches `finished` — see flap_cleanup.py.
    cascade_baseline_ids = _discover_cascade_baseline_ids(
        sonda_url, device, interface, peers, headers
    )
    in_octet_start, out_octet_start = _query_baseline_octet_values(
        prom_query_url, device, interface
    )
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
        prom_url=resolved_prom_url,
        loki_url=loki_url,
        strip_scrape_provenance=strip_provenance,
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
        # If the cascade POST fails, attempt to restore the baseline immediately
        # so the lab doesn't sit in a half-deleted state.
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
    prom_url: str,
    loki_url: str,
    strip_scrape_provenance: bool = False,
    in_octet_start: float = 0.0,
    out_octet_start: float = 0.0,
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
            _flap_bgp_entries(
                device=device,
                peer=peer,
                up_duration=up_duration,
                down_duration=down_duration,
                cascade_delay=cascade_delay,
                extra_labels=metric_prov,
            )
        )

    scenarios.extend(
        _gated_octet_entries(
            device=device,
            interface=interface,
            primary_id=primary_id,
            metric_prov=metric_prov,
            intf_role=intf_labels.get("intf_role", "peer"),
            in_start=in_octet_start,
            out_start=out_octet_start,
            cascade_delay=cascade_delay,
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
        "kind": "runnable",
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
    extra_labels: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build cascade BGP entries using `flap` generators with phase-shifted timing.

    Each BGP metric per peer becomes one cascade scenario that cycles in
    lockstep with `primary_flap`'s 90s cycle, but offset so BGP lags
    interface on the down transition (matching real BGP hold-down timer
    behavior) and recovers simultaneously on the up transition.

    BGP up_duration  = primary_up + cascade_delay   (e.g. 30s + 10s = 40s)
    BGP down_duration = primary_down - cascade_delay (e.g. 60s - 10s = 50s)
    BGP cycle = primary cycle (e.g. both 90s) so they re-sync each cycle.

    Replaces the older `_gated_bgp_entries` (while:+delay.open) pattern,
    which produced no continuous emission during cascade up phases — with
    baseline DELETEd that left the merged series stale and dashboards
    showed gaps. The flap-based entries emit continuously for the full
    cascade lifetime.
    """
    base_labels = {**_entry_only_bgp_labels(device, peer), **(extra_labels or {})}
    safe_peer = peer.address.replace(".", "_")

    up_s = _parse_duration_secs(up_duration)
    down_s = _parse_duration_secs(down_duration)
    delay_s = _parse_duration_secs(cascade_delay)
    bgp_up = f"{up_s + delay_s:g}s"
    bgp_down = f"{max(down_s - delay_s, 0.0):g}s"

    bgp_specs: list[tuple[str, float, float]] = [
        ("bgp_oper_state", _BGP_UP_OPER, _BGP_DOWN_OPER),
        ("bgp_neighbor_state", _BGP_UP_NEIGHBOR, _BGP_DOWN_NEIGHBOR),
    ]
    for metric in _BGP_PREFIX_METRICS:
        bgp_specs.append((metric, _BGP_UP_PREFIXES, _BGP_DOWN_PREFIXES))

    entries: list[dict[str, Any]] = []
    for metric, up_val, down_val in bgp_specs:
        if up_val == down_val:
            entries.append(
                {
                    "id": f"{metric}_{safe_peer}",
                    "signal_type": "metrics",
                    "name": metric,
                    "generator": {"type": "constant", "value": up_val},
                    "labels": base_labels,
                }
            )
        else:
            entries.append(
                {
                    "id": f"{metric}_{safe_peer}",
                    "signal_type": "metrics",
                    "name": metric,
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


def _discover_cascade_baseline_ids(
    sonda_url: str,
    device: str,
    interface: str,
    peers: list[Peer],
    headers: dict[str, str],
) -> list[str]:
    """Find every baseline scenario UUID the cascade should DELETE.

    Covers two categories per device:
      - Per-interface metrics (oper_state, in_octets, out_octets) matching
        labels {<interface_label>=<interface>, <device_label>=<device>}.
      - Per-peer BGP metrics matching labels {<peer_label>=<peer.address>,
        <device_label>=<device>} for each peer in `peers`.

    sonda's /scenarios listing doesn't expose labels, so we list candidate
    IDs by metric name then GET each candidate's /metrics to inspect its
    labels.
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
        s["id"]
        for s in all_scenarios
        if s.get("name") in interface_metric_names and s.get("state") == "running"
    ]
    bgp_candidates = [
        s["id"]
        for s in all_scenarios
        if s.get("name") in bgp_metric_names and s.get("state") == "running"
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


def _query_baseline_octet_values(
    prom_query_url: str, device: str, interface: str
) -> tuple[float, float]:
    """Read the canonical interface_in/out_octets values from Prometheus.

    Prometheus is the authoritative source for what Telegraf has been
    feeding into the TSDB. Seeding the cascade's gated step counter from
    here (rather than from sonda's per-scenario /metrics) means there is
    no value discontinuity between the baseline scenario being DELETEd
    and the cascade's first emitted sample — `rate()` doesn't see a
    spurious large increment.
    """
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
    metric_prov: dict[str, str],
    intf_role: str,
    in_start: float,
    out_start: float,
    cascade_delay: str,
) -> list[dict[str, Any]]:
    """Build the gated `interface_in/out_octets` step counters for the cascade.

    The counters tick during the cascade's up phase and pause (with position
    preserved via `delay.close.snap_to: null`) during the down phase, then
    resume from the frozen value when the gate reopens — same pattern as
    sonda's `bytes_total + link_state` example.
    """
    cfg = _BASELINE_METRICS.get(device)
    if cfg is None:
        return []
    octet_labels = {
        "name": interface,
        "intf_role": intf_role,
        **metric_prov,
    }
    while_clause = {"ref": primary_id, "op": "<", "value": 2}
    return [
        {
            "id": "interface_in_octets_gated",
            "signal_type": "metrics",
            "name": "interface_in_octets",
            "metric_type": "counter",
            "generator": {"type": "step", "start": in_start, "step_size": cfg["in_step"] / 10.0},
            "while": while_clause,
            "delay": {"open": cascade_delay, "close": {"duration": "0s", "snap_to": None}},
            "labels": octet_labels,
        },
        {
            "id": "interface_out_octets_gated",
            "signal_type": "metrics",
            "name": "interface_out_octets",
            "metric_type": "counter",
            "generator": {"type": "step", "start": out_start, "step_size": cfg["out_step"] / 10.0},
            "while": while_clause,
            "delay": {"open": cascade_delay, "close": {"duration": "0s", "snap_to": None}},
            "labels": octet_labels,
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
