"""`nobs alerts` — list active alerts from Alertmanager."""
from __future__ import annotations

import datetime as dt
from typing import Annotated

import typer
from rich.table import Table

from .._console import console, fail
from ..clients import AlertmanagerClient


def _parse_iso(s: str) -> dt.datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _humanize_age(start: dt.datetime | None) -> str:
    if start is None:
        return "—"
    now = dt.datetime.now(dt.UTC)
    delta = now - start
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    if seconds < 86400:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    return f"{seconds // 86400}d{(seconds % 86400) // 3600}h"


def alerts(
    am_url: Annotated[str, typer.Option("--am-url", envvar="ALERTMANAGER_URL", help="Alertmanager URL.")] = "http://localhost:9093",
    label: Annotated[
        list[str] | None,
        typer.Option("--label", "-l", help="Filter by label, e.g. -l alertname=BgpSessionNotUp. Can be repeated."),
    ] = None,
    show_silenced: Annotated[bool, typer.Option("--silenced/--no-silenced", help="Include silenced alerts.")] = True,
    show_inhibited: Annotated[bool, typer.Option("--inhibited/--no-inhibited", help="Include inhibited alerts.")] = True,
) -> None:
    """List active alerts from Alertmanager as a Rich table.

    Filters can be repeated, e.g.:
        nobs alerts -l alertname=BgpSessionNotUp -l device=srl1
    """
    client = AlertmanagerClient(am_url)

    try:
        records = client.alerts(active=True, silenced=show_silenced, inhibited=show_inhibited)
    except Exception as e:  # noqa: BLE001
        fail(f"could not reach Alertmanager at {am_url}: {e}")
        raise typer.Exit(code=1) from e

    # Apply label filters
    filters: dict[str, str] = {}
    for kv in label or []:
        if "=" not in kv:
            fail(f"--label must be key=value (got {kv!r})")
            raise typer.Exit(code=2)
        k, v = kv.split("=", 1)
        filters[k.strip()] = v.strip()

    def _match(rec: dict) -> bool:
        labels = rec.get("labels") or {}
        return all(labels.get(k) == v for k, v in filters.items())

    records = [r for r in records if _match(r)]

    title = "Active alerts"
    if filters:
        title += " (filtered: " + ", ".join(f"{k}={v}" for k, v in filters.items()) + ")"

    table = Table(title=title, show_lines=False, header_style="label")
    table.add_column("Alertname", no_wrap=True)
    table.add_column("Severity")
    table.add_column("Device / target")
    table.add_column("State", justify="right")
    table.add_column("Age", justify="right")

    if not records:
        console.print()
        console.print(table)
        console.print("\n[muted]No alerts match.[/]")
        return

    for rec in records:
        labels = rec.get("labels") or {}
        status_block = rec.get("status") or {}
        state = (status_block.get("state") or "").lower()
        if state == "active" and status_block.get("silencedBy"):
            state_styled = "[muted]silenced[/]"
        elif state == "active" and status_block.get("inhibitedBy"):
            state_styled = "[muted]inhibited[/]"
        elif state == "active":
            state_styled = "[fail]firing[/]"
        else:
            state_styled = state or "—"

        target = labels.get("device") or "—"
        peer = labels.get("peer_address") or labels.get("interface")
        if peer:
            target = f"{target} → {peer}"
        sev = labels.get("severity") or "—"
        sev_styled = "[fail]critical[/]" if sev == "critical" else f"[warn]{sev}[/]" if sev == "warning" else sev

        age = _humanize_age(_parse_iso(rec.get("startsAt", "")))
        table.add_row(labels.get("alertname", "—"), sev_styled, target, state_styled, age)

    console.print()
    console.print(table)
