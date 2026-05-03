"""`nobs autocon5 page` — render a stylized on-call page from a live alert.

The page is the workshop's recurring story beat. Calling this command pulls
a currently-firing alert from Alertmanager and prints it as if a pager just
buzzed at 2am. The alert is real; the dramatization is the only thing this
adds.

Defaults to the first firing `BgpSessionNotUp` alert (one is always firing
in the lab thanks to the deliberately broken peer). `--alert`, `--device`,
and `--peer` filters narrow further. `--now` overrides the printed
wall-clock for tests / demos.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

import requests
import typer
from nobs._console import console, fail
from rich.panel import Panel
from rich.text import Text


def page(
    alert: Annotated[
        str,
        typer.Option(
            "--alert",
            "-a",
            help="Alertname to filter by (e.g. BgpSessionNotUp). Default: first firing alert.",
        ),
    ] = "BgpSessionNotUp",
    device: Annotated[
        str,
        typer.Option("--device", "-d", help="Filter to alerts on this device."),
    ] = "",
    peer: Annotated[
        str,
        typer.Option("--peer", "-p", help="Filter to alerts on this peer_address."),
    ] = "",
    alertmanager_url: Annotated[
        str,
        typer.Option(
            "--alertmanager-url",
            envvar="ALERTMANAGER_URL",
            help="Alertmanager base URL.",
        ),
    ] = "http://localhost:9093",
    now: Annotated[
        str,
        typer.Option(
            "--now",
            help="Override the wall-clock printed in the page (HH:MM). Default: real time.",
        ),
    ] = "",
) -> None:
    """Render a fake on-call page from a live alert."""
    try:
        response = requests.get(f"{alertmanager_url.rstrip('/')}/api/v2/alerts", timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        fail(f"Alertmanager fetch failed: {exc}")
        raise typer.Exit(code=1) from exc

    alerts = response.json()
    if not isinstance(alerts, list):
        fail(f"Unexpected response shape: {type(alerts).__name__}")
        raise typer.Exit(code=1)

    candidates = [
        a
        for a in alerts
        if a.get("status", {}).get("state") == "active"
        and (not alert or a.get("labels", {}).get("alertname") == alert)
        and (not device or a.get("labels", {}).get("device") == device)
        and (not peer or a.get("labels", {}).get("peer_address") == peer)
    ]
    if not candidates:
        fail(
            "no firing alert matched the filters. "
            "Run `nobs autocon5 alerts` to see what's currently firing."
        )
        raise typer.Exit(code=1)

    chosen = candidates[0]
    labels = chosen.get("labels") or {}
    starts_at = chosen.get("startsAt") or ""

    age = _age_string(starts_at) if starts_at else "unknown"
    wall_clock = now or dt.datetime.now().strftime("%H:%M")

    body = Text()
    body.append(f"PAGED {wall_clock}\n", style="bold red")
    body.append(f"{labels.get('alertname', 'unknown alert')}", style="bold")
    if labels.get("device"):
        body.append(f" on {labels['device']}", style="bold")
    if labels.get("peer_address"):
        body.append(f" — peer {labels['peer_address']}", style="bold")
    body.append("\n")
    summary = labels.get("summary") or _default_summary(labels)
    body.append(summary)
    body.append(f"\nfiring for: {age}", style="dim")
    body.append("\nseverity: ")
    body.append(labels.get("severity", "unknown"), style="yellow")
    body.append("\n\nYou're awake. The dashboard is your only friend.", style="italic")

    console.print(Panel(body, border_style="red", title="on-call", title_align="left"))
    console.print(
        "\n  Confirm the alert: [muted]nobs autocon5 alerts[/]\n"
        "  Open the runbook:  [muted]workshops/autocon5/guides/[/]"
    )


def _age_string(iso_ts: str) -> str:
    try:
        ts = dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return "unknown"
    delta = dt.datetime.now(dt.UTC) - ts
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "<1 min"
    if minutes < 60:
        return f"~{minutes} min"
    hours = minutes // 60
    return f"~{hours}h{minutes % 60:02d}m"


def _default_summary(labels: dict) -> str:
    name = labels.get("alertname", "")
    if name == "BgpSessionNotUp":
        return f"BGP peer {labels.get('peer_address', '?')} not reaching Established"
    if name == "PeerInterfaceFlapping":
        return f"interface {labels.get('interface', '?')} flapping above threshold"
    return f"alert {name} firing"
