"""`nobs autocon5 flap-interface` - push UPDOWN log events into Loki.

Python port of `scripts/sonda-trigger.sh flap-interface`. Sends N
synthetic syslog events (alternating up / down) for a given device +
interface tuple to trip the `PeerInterfaceFlapping` Loki rule (>3 in 2m).
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
    loki_url: Annotated[
        str,
        typer.Option(
            "--loki-url",
            envvar="LOKI_URL",
            help="Base Loki URL (push goes to /loki/api/v1/push).",
        ),
    ] = "http://localhost:3001",
    delay: Annotated[
        float,
        typer.Option("--delay", help="Seconds to sleep between events."),
    ] = 1.0,
) -> None:
    """Push N UPDOWN log events into Loki to trip PeerInterfaceFlapping.

    Each event alternates between `up` and `down`. The receiver-side rule
    fires on >3 transitions in 2 minutes, so the default of 6 trips it
    with margin.
    """
    push_url = f"{loki_url.rstrip('/')}/loki/api/v1/push"
    console.print(
        f"Pushing [label]{count}[/] UPDOWN events for "
        f"[label]{device}:{interface}[/] to [muted]{push_url}[/]"
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
            ts_ns = str(time.time_ns())
            payload = {
                "streams": [
                    {
                        "stream": {
                            "device": device,
                            "interface": interface,
                            "level": "warning",
                            "vendor_facility_process": "UPDOWN",
                            "type": "syslog",
                            "source": "workshop-trigger",
                        },
                        "values": [
                            [ts_ns, f"Interface {interface} changed state to {new_state}"]
                        ],
                    }
                ]
            }
            try:
                response = requests.post(push_url, json=payload, timeout=5)
                response.raise_for_status()
            except requests.RequestException as exc:
                fail(f"Loki push failed on event {i}/{count}: {exc}")
                raise typer.Exit(code=1) from exc

            progress.update(task, completed=i, description=f"event {i}/{count} ({new_state})")
            if i < count:
                time.sleep(delay)

    ok(
        f"pushed {count} UPDOWN events; "
        "PeerInterfaceFlapping should fire within ~30s."
    )
