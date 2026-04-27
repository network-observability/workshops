"""`nobs autocon5 scenarios` - list the scenarios registered with sonda-server.

Replaces the old `task autocon5:scenarios` (`curl /scenarios | jq`) with
a Rich table.
"""
from __future__ import annotations

from typing import Annotated, Any

import requests
import typer
from nobs._console import console, fail
from rich.table import Table


def scenarios(
    sonda_url: Annotated[
        str,
        typer.Option(
            "--sonda-url",
            envvar="SONDA_SERVER_URL",
            help="Base URL of the sonda-server.",
        ),
    ] = "http://localhost:8085",
) -> None:
    """List the scenarios registered with sonda-server as a Rich table."""
    url = f"{sonda_url.rstrip('/')}/scenarios"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        fail(f"could not reach sonda-server at {url}: {exc}")
        raise typer.Exit(code=1) from exc

    try:
        body = response.json()
    except ValueError as exc:
        fail(f"sonda-server returned non-JSON body: {exc}")
        raise typer.Exit(code=1) from exc

    records = _normalize(body)

    table = Table(title="Sonda scenarios", show_lines=False, header_style="label")
    table.add_column("ID", no_wrap=True)
    table.add_column("Name")
    table.add_column("Status", justify="right")
    table.add_column("Elapsed", justify="right")

    if not records:
        console.print()
        console.print(table)
        console.print("\n[muted]No scenarios registered.[/]")
        return

    for rec in records:
        status = (rec.get("status") or "").lower()
        if status in {"running", "active"}:
            status_styled = f"[ok]{status}[/]"
        elif status in {"failed", "error"}:
            status_styled = f"[fail]{status}[/]"
        elif status:
            status_styled = f"[warn]{status}[/]"
        else:
            status_styled = "—"

        elapsed = rec.get("elapsed") or rec.get("duration") or "—"
        table.add_row(
            str(rec.get("id", "—")),
            str(rec.get("name", "—")),
            status_styled,
            str(elapsed),
        )

    console.print()
    console.print(table)


def _normalize(body: Any) -> list[dict[str, Any]]:
    """Coerce sonda's `/scenarios` response into a list of dicts."""
    if isinstance(body, list):
        return [b for b in body if isinstance(b, dict)]
    if isinstance(body, dict):
        # Some sonda builds return {"scenarios": [...]}.
        nested = body.get("scenarios")
        if isinstance(nested, list):
            return [b for b in nested if isinstance(b, dict)]
        # Or {"id": {...}, ...}
        return [{"id": k, **v} for k, v in body.items() if isinstance(v, dict)]
    return []
