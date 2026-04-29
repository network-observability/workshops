"""`nobs autocon5 flap-interface` — emit UPDOWN log events via sonda /events.

Synthetic interface flap. Posts N alternating up/down events to
sonda-server's /events endpoint, which forwards to Loki. Trips the
PeerInterfaceFlapping rule (>3 transitions in 2 min).
"""
from __future__ import annotations

import time
from typing import Annotated

import requests
import typer
from nobs._console import console, fail, ok
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


def flap_interface(
    device: Annotated[
        str, typer.Option("--device", "-d", help="Device name (e.g. srl1).")
    ] = "srl1",
    interface: Annotated[
        str,
        typer.Option(
            "--interface", "-i", help="Interface name (e.g. ethernet-1/1)."
        ),
    ] = "ethernet-1/1",
    count: Annotated[
        int,
        typer.Option(
            "--count", "-n", help="Number of UPDOWN events to push (alternating up/down)."
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
        typer.Option("--delay", help="Seconds to sleep between events."),
    ] = 1.0,
) -> None:
    """Push N UPDOWN log events into Loki via sonda /events.

    Each event alternates between `up` and `down`. The receiver-side rule
    fires on >3 transitions in 2 minutes, so the default of 6 trips it
    with margin.
    """
    events_url = f"{sonda_url.rstrip('/')}/events"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    console.print(
        f"Pushing [label]{count}[/] UPDOWN events for "
        f"[label]{device}:{interface}[/] via [muted]{events_url}[/]"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(f"flap {device}:{interface}", total=count)
        for i in range(1, count + 1):
            new_state = "down" if i % 2 == 0 else "up"
            payload = {
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
                    # Sonda's enum uses `warn` (not `warning`); the `level`
                    # label keeps the Loki-side value so dashboard filters
                    # `{level="warning"}` still match.
                    "severity": "warn",
                    "message": f"Interface {interface} changed state to {new_state}",
                    "fields": {},
                },
                "encoder": {"type": "json_lines"},
                "sink": {"type": "loki", "url": loki_url},
            }
            try:
                response = requests.post(events_url, json=payload, headers=headers, timeout=5)
                response.raise_for_status()
            except requests.RequestException as exc:
                fail(f"sonda /events post failed on event {i}/{count}: {exc}")
                raise typer.Exit(code=1) from exc

            progress.update(task, completed=i, description=f"event {i}/{count} ({new_state})")
            if i < count:
                time.sleep(delay)

    ok(
        f"pushed {count} UPDOWN events via /events; "
        "PeerInterfaceFlapping should fire within ~30s."
    )
