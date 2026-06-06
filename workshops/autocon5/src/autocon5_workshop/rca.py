"""`nobs autocon5 rca [DEVICE] [PEER]` — print the most recent AI RCA narrative.

Fetches Prefect workflow annotations tagged `ai_rca="true"` from Loki and
renders the `message` field as Markdown in the terminal. Useful when reading
on a laptop without flipping to Grafana, or when comparing narratives across
several recent flow runs.
"""

from __future__ import annotations

import json
from typing import Annotated

import typer
from nobs._console import console, fail, note
from nobs.clients import LokiClient
from rich.markdown import Markdown
from rich.panel import Panel


def rca(
    device: Annotated[
        str | None,
        typer.Argument(help="Device name (e.g. srl1). Optional — defaults to any device."),
    ] = None,
    peer: Annotated[
        str | None,
        typer.Argument(help="Peer IP (e.g. 10.1.99.2). Optional — defaults to any peer."),
    ] = None,
    last: Annotated[int, typer.Option("--last", help="Number of most-recent records to show.")] = 1,
    minutes: Annotated[int, typer.Option("--minutes", help="How far back to look.")] = 60,
    loki_url: Annotated[str, typer.Option(envvar="LOKI_URL")] = "http://localhost:3001",
) -> None:
    """Print the most recent AI RCA narratives from Loki, rendered as Markdown."""
    selector = '{source="prefect", ai_rca="true"'
    if device:
        selector += f', device="{device}"'
    if peer:
        selector += f', peer_address="{peer}"'
    selector += "}"

    client = LokiClient(loki_url)
    try:
        lines = client.query_range(selector, minutes=minutes, limit=last)
    except Exception as e:  # noqa: BLE001 — surface any failure cleanly to the user
        fail(f"Failed to query Loki at {loki_url}: {e}")
        raise typer.Exit(code=1) from e

    if not lines:
        scope_parts: list[str] = []
        if device:
            scope_parts.append(f"device={device}")
        if peer:
            scope_parts.append(f"peer={peer}")
        scope_label = " ".join(scope_parts) or "any device/peer"
        note(
            f"No AI RCA records found in the last {minutes}m for {scope_label}. "
            "If you haven't enabled it yet, set ENABLE_AI_RCA=true in workshops/autocon5/.env "
            "and re-run `nobs autocon5 up`."
        )
        return

    console.print()
    for i, raw in enumerate(lines):
        try:
            record = json.loads(raw)
        except json.JSONDecodeError:
            note(f"(skipping unparseable record #{i + 1})")
            continue

        message = record.get("message", "") or ""
        if message.startswith("AI RCA:"):
            message = message[len("AI RCA:") :].lstrip("\n")

        labels = record.get("labels") or {}
        timestamp = record.get("timestamp", "")
        header = f"{timestamp}  device={labels.get('device', '?')}  peer={labels.get('peer_address', '?')}"

        console.print(Panel.fit(header, border_style="cyan", padding=(0, 1)))
        console.print(Markdown(message))
        console.print()
