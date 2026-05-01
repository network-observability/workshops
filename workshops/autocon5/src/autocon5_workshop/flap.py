"""`nobs autocon5 flap-interface` — cascade interface + BGP signals via sonda /events.

Three-phase cascade:
- Phase A: alternating UPDOWN log events paired with `interface_oper_state` metric flips.
- Phase B (after a hold-down pause): for each BGP peer on the link, push
  `bgp_oper_state=2`, `bgp_neighbor_state=1`, and zero out the prefix counters,
  re-pushing every ~2s for the configured BGP-down duration.
- Phase C: restore BGP to established and prefix counters to a nominal value
  so the dashboard recovers when the lab's continuous generator resumes.

`--no-cascade` runs Phase A only.
"""

from __future__ import annotations

import time
from typing import Annotated

import requests
import typer
from nobs._console import console, fail, ok, warn
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from autocon5_workshop.flap_topology import (
    Peer,
    bgp_labels,
    interface_labels,
    peers_for,
)

_BGP_RESTORE_TICK_SECS = 2.0
_BGP_DOWN_PREFIXES = 0.0
_BGP_DOWN_OPER = 2.0
_BGP_DOWN_NEIGHBOR = 1.0
_BGP_UP_OPER = 1.0
_BGP_UP_NEIGHBOR = 6.0
_BGP_PREFIX_METRICS = (
    "bgp_prefixes_accepted",
    "bgp_received_routes",
    "bgp_sent_routes",
    "bgp_active_routes",
)


def flap_interface(
    device: Annotated[
        str, typer.Option("--device", "-d", help="Device name (e.g. srl1).")
    ] = "srl1",
    interface: Annotated[
        str,
        typer.Option("--interface", "-i", help="Interface name (e.g. ethernet-1/1)."),
    ] = "ethernet-1/1",
    count: Annotated[
        int,
        typer.Option(
            "--count",
            "-n",
            help="Number of UPDOWN events to push (alternating up/down). Ends on `up`.",
        ),
    ] = 6,
    sonda_url: Annotated[
        str,
        typer.Option(
            "--sonda-url",
            envvar="SONDA_SERVER_URL",
            help="Base sonda-server URL (events go to /events).",
        ),
    ] = "http://localhost:8085",
    loki_url: Annotated[
        str,
        typer.Option(
            "--loki-url",
            envvar="SONDA_LOKI_SINK_URL",
            help="Loki URL passed as the sink in the /events payload "
            "(sonda's container-network view of Loki, not the host CLI's).",
        ),
    ] = "http://loki:3001",
    prom_url: Annotated[
        str,
        typer.Option(
            "--prom-url",
            envvar="SONDA_PROM_REMOTE_WRITE_URL",
            help="Prometheus remote_write URL passed as the metric sink "
            "(sonda's container-network view of Prometheus).",
        ),
    ] = "http://prometheus:9090/api/v1/write",
    api_key: Annotated[
        str,
        typer.Option(
            "--sonda-api-key",
            envvar="SONDA_API_KEY",
            help="Bearer token if sonda-server has SONDA_API_KEY set; empty otherwise.",
        ),
    ] = "",
    delay: Annotated[
        float,
        typer.Option("--delay", help="Seconds to sleep between Phase A events."),
    ] = 1.0,
    cascade: Annotated[
        bool,
        typer.Option(
            "--cascade/--no-cascade",
            help="Run BGP collapse + restore after the interface flap. "
            "`--no-cascade` runs Phase A only.",
        ),
    ] = True,
    cascade_delay: Annotated[
        float,
        typer.Option(
            "--cascade-delay",
            help="Seconds to wait between Phase A end and Phase B start "
            "(simulates BGP hold-timer / damping).",
        ),
    ] = 10.0,
    bgp_down_duration: Annotated[
        float,
        typer.Option(
            "--bgp-down-duration",
            help="Seconds to keep BGP in the down state during Phase B. "
            "Long enough for `BgpSessionNotUp` (for: 30s) to fire by default.",
        ),
    ] = 30.0,
    restored_prefixes: Annotated[
        int,
        typer.Option(
            "--restored-prefixes",
            help="Prefix counter value Phase C restores accepted/received/sent/active to.",
        ),
    ] = 5,
) -> None:
    """Cascade interface flap → BGP collapse → BGP restore via sonda /events."""
    events_url = f"{sonda_url.rstrip('/')}/events"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    peers: list[Peer] = peers_for(device, interface) if cascade else []
    if cascade and not peers:
        warn(f"no BGP peers mapped to {device}:{interface}; running Phase A only (no cascade).")

    console.print(
        f"Pushing [label]{count}[/] UPDOWN events for "
        f"[label]{device}:{interface}[/] via [muted]{events_url}[/]"
    )
    if peers:
        peer_list = ", ".join(p.address for p in peers)
        console.print(
            f"Cascade peers: [label]{peer_list}[/] "
            f"(hold-down [label]{cascade_delay:g}s[/], "
            f"BGP down [label]{bgp_down_duration:g}s[/])"
        )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        flap_task = progress.add_task(f"flap {device}:{interface}", total=count)
        _phase_a(
            progress=progress,
            task=flap_task,
            events_url=events_url,
            headers=headers,
            loki_url=loki_url,
            prom_url=prom_url,
            device=device,
            interface=interface,
            count=count,
            delay=delay,
        )

        if not peers:
            ok(
                f"pushed {count} UPDOWN events + interface_oper_state flips; "
                "PeerInterfaceFlapping should fire within ~30s."
            )
            return

        _hold_down(progress=progress, seconds=cascade_delay)

        bgp_task = progress.add_task(
            f"BGP collapse ({bgp_down_duration:g}s)", total=bgp_down_duration
        )
        _phase_b(
            progress=progress,
            task=bgp_task,
            events_url=events_url,
            headers=headers,
            prom_url=prom_url,
            device=device,
            peers=peers,
            duration=bgp_down_duration,
        )

        restore_task = progress.add_task(
            f"BGP restore ({len(peers)} peer{'s' if len(peers) != 1 else ''})",
            total=len(peers),
        )
        _phase_c(
            progress=progress,
            task=restore_task,
            events_url=events_url,
            headers=headers,
            prom_url=prom_url,
            device=device,
            peers=peers,
            restored_prefixes=float(restored_prefixes),
        )

    ok(
        f"pushed {count} UPDOWN events + interface flips; "
        f"cascaded to {len(peers)} BGP peer(s) for {bgp_down_duration:g}s, then restored."
    )


def _phase_a(
    *,
    progress: Progress,
    task: TaskID,
    events_url: str,
    headers: dict[str, str],
    loki_url: str,
    prom_url: str,
    device: str,
    interface: str,
    count: int,
    delay: float,
) -> None:
    intf_labels = interface_labels(device, interface)
    for i in range(1, count + 1):
        new_state = "down" if i % 2 == 0 else "up"
        oper_value = 2.0 if new_state == "down" else 1.0

        log_payload = {
            "signal_type": "logs",
            "labels": {
                "device": device,
                "interface": interface,
                "level": "warning",
                "vendor_facility_process": "UPDOWN",
                "type": "syslog",
                "source": "workshop-trigger",
            },
            "log": {
                "severity": "warn",
                "message": f"Interface {interface} changed state to {new_state}",
                "fields": {},
            },
            "encoder": {"type": "json_lines"},
            "sink": {"type": "loki", "url": loki_url},
        }
        _post(events_url, log_payload, headers, what=f"flap log {i}/{count}")

        metric_payload = _metric_payload(
            metric_name="interface_oper_state",
            value=oper_value,
            labels=intf_labels,
            prom_url=prom_url,
        )
        _post(events_url, metric_payload, headers, what=f"flap metric {i}/{count}")

        # Counter coupling: when the interface is operationally down, no
        # traffic flows. Push 0 on the byte counters so a student querying
        # `rate(interface_in_octets[...])` for this interface during the
        # flap sees the realistic shape — counters flatline while the link
        # is down. When the interface comes back up we don't push; the
        # lab's continuous emitter resumes its normal traffic pattern from
        # the next scrape onward.
        if new_state == "down":
            for counter_name in ("interface_in_octets", "interface_out_octets"):
                _post(
                    events_url,
                    _metric_payload(
                        metric_name=counter_name,
                        value=0.0,
                        labels=intf_labels,
                        prom_url=prom_url,
                    ),
                    headers,
                    what=f"flap {counter_name} {i}/{count}",
                )

        progress.update(task, completed=i, description=f"event {i}/{count} ({new_state})")
        if i < count:
            time.sleep(delay)


def _hold_down(*, progress: Progress, seconds: float) -> None:
    if seconds <= 0:
        return
    hold_task = progress.add_task(f"BGP hold-down (waiting {seconds:g}s)", total=seconds)
    deadline = time.monotonic() + seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            progress.update(hold_task, completed=seconds)
            break
        progress.update(hold_task, completed=seconds - remaining)
        time.sleep(min(0.5, remaining))


def _phase_b(
    *,
    progress: Progress,
    task: TaskID,
    events_url: str,
    headers: dict[str, str],
    prom_url: str,
    device: str,
    peers: list[Peer],
    duration: float,
) -> None:
    start = time.monotonic()
    deadline = start + duration
    tick = 0
    while True:
        now = time.monotonic()
        if now >= deadline:
            progress.update(task, completed=duration, description="BGP collapse complete")
            break
        tick += 1
        for peer in peers:
            _push_bgp_state(
                events_url=events_url,
                headers=headers,
                prom_url=prom_url,
                device=device,
                peer=peer,
                oper_state=_BGP_DOWN_OPER,
                neighbor_state=_BGP_DOWN_NEIGHBOR,
                prefix_value=_BGP_DOWN_PREFIXES,
                what=f"phase-b tick {tick}",
            )
        elapsed = now - start
        progress.update(
            task,
            completed=elapsed,
            description=f"BGP collapse tick {tick} ({len(peers)} peer{'s' if len(peers) != 1 else ''})",
        )
        sleep_for = min(_BGP_RESTORE_TICK_SECS, max(0.0, deadline - time.monotonic()))
        if sleep_for > 0:
            time.sleep(sleep_for)


def _phase_c(
    *,
    progress: Progress,
    task: TaskID,
    events_url: str,
    headers: dict[str, str],
    prom_url: str,
    device: str,
    peers: list[Peer],
    restored_prefixes: float,
) -> None:
    for i, peer in enumerate(peers, start=1):
        _push_bgp_state(
            events_url=events_url,
            headers=headers,
            prom_url=prom_url,
            device=device,
            peer=peer,
            oper_state=_BGP_UP_OPER,
            neighbor_state=_BGP_UP_NEIGHBOR,
            prefix_value=restored_prefixes,
            what=f"phase-c restore {peer.address}",
        )
        progress.update(task, completed=i, description=f"restored {peer.address}")


def _push_bgp_state(
    *,
    events_url: str,
    headers: dict[str, str],
    prom_url: str,
    device: str,
    peer: Peer,
    oper_state: float,
    neighbor_state: float,
    prefix_value: float,
    what: str,
) -> None:
    labels = bgp_labels(device, peer.address, peer.asn)
    samples: list[tuple[str, float]] = [
        ("bgp_oper_state", oper_state),
        ("bgp_neighbor_state", neighbor_state),
    ]
    samples.extend((m, prefix_value) for m in _BGP_PREFIX_METRICS)
    for metric_name, value in samples:
        payload = _metric_payload(
            metric_name=metric_name,
            value=value,
            labels=labels,
            prom_url=prom_url,
        )
        _post(events_url, payload, headers, what=f"{what} {metric_name}")


def _metric_payload(
    *,
    metric_name: str,
    value: float,
    labels: dict[str, str],
    prom_url: str,
) -> dict:
    return {
        "signal_type": "metrics",
        "labels": labels,
        "metric": {"name": metric_name, "value": value},
        "encoder": {"type": "remote_write"},
        "sink": {"type": "remote_write", "url": prom_url},
    }


def _post(
    url: str,
    payload: dict,
    headers: dict[str, str],
    *,
    what: str,
) -> None:
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        fail(f"sonda /events post failed ({what}): {exc}")
        raise typer.Exit(code=1) from exc
