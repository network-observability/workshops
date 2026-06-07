"""`nobs autocon5 silences` — list Alertmanager silences in a Rich table.

Companion to `nobs autocon5 alerts`. Useful in Part 3 / Advanced when you
want to capture what the workflow has silenced (or what `reset` truncated)
without curling Alertmanager's API by hand.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

import typer
from nobs._console import console, fail, note
from nobs.clients import AlertmanagerClient
from rich.table import Table


def silences(
    show_expired: Annotated[
        bool,
        typer.Option("--show-expired", help="Include expired silences (default: active + pending only)."),
    ] = False,
    am_url: Annotated[str, typer.Option(envvar="ALERTMANAGER_URL")] = "http://localhost:9093",
) -> None:
    """List Alertmanager silences with their startsAt / endsAt / remaining / matchers."""
    client = AlertmanagerClient(am_url)
    try:
        all_silences = client.silences()
    except Exception as e:  # noqa: BLE001
        fail(f"Failed to query Alertmanager at {am_url}: {e}")
        raise typer.Exit(code=1) from e

    rows = []
    now = dt.datetime.now(dt.UTC)
    for s in all_silences:
        state = s.get("status", {}).get("state", "?")
        if not show_expired and state == "expired":
            continue
        try:
            ends = dt.datetime.fromisoformat(s["endsAt"].replace("Z", "+00:00"))
            remaining_s = (ends - now).total_seconds()
            remaining = f"{int(remaining_s // 60)}m{int(remaining_s % 60)}s" if remaining_s > 0 else "—"
        except Exception:
            remaining = "?"
        matchers = ", ".join(f"{m['name']}={m['value']}" for m in s.get("matchers", []))
        rows.append(
            {
                "id": s.get("id", "")[:12] + "…",
                "state": state,
                "starts": s.get("startsAt", "")[11:19],
                "ends": s.get("endsAt", "")[11:19],
                "remaining": remaining,
                "matchers": matchers,
                "creator": s.get("createdBy", "")[:14],
            }
        )

    if not rows:
        note(
            "No silences " + ("(any state)" if show_expired else "active or pending") + f" in Alertmanager at {am_url}."
        )
        return

    table = Table(title="Alertmanager silences", show_lines=False)
    table.add_column("ID")
    table.add_column("State")
    table.add_column("Starts (UTC)")
    table.add_column("Ends (UTC)")
    table.add_column("Remaining")
    table.add_column("Matchers")
    table.add_column("Creator")
    for r in rows:
        state_style = {"active": "bold green", "pending": "yellow", "expired": "dim"}.get(r["state"], "")
        table.add_row(
            r["id"],
            f"[{state_style}]{r['state']}[/]" if state_style else r["state"],
            r["starts"],
            r["ends"],
            r["remaining"],
            r["matchers"],
            r["creator"],
        )
    console.print()
    console.print(table)
