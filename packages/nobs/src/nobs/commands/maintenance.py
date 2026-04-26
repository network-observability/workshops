"""`nobs maintenance` — toggle a SoT device's maintenance flag.

Generic over the schema kind (defaults to `WorkshopDevice` for the
AutoCon5 workshop). Future workshops with a different node type can
override `--kind` without forking the command.
"""
from __future__ import annotations

import sys
from typing import Annotated

import typer
from rich.panel import Panel

from .._console import console, fail, note


def maintenance(
    device: Annotated[
        str,
        typer.Option("--device", "-d", help="Device name (matches the kind's `name` attribute)."),
    ],
    state: Annotated[
        bool,
        typer.Option("--state/--clear", help="Set maintenance to true (--state) or false (--clear)."),
    ] = True,
    kind: Annotated[
        str,
        typer.Option("--kind", help="Infrahub node kind to update."),
    ] = "WorkshopDevice",
    address: Annotated[
        str,
        typer.Option("--address", envvar="INFRAHUB_ADDRESS"),
    ] = "http://localhost:8000",
    token: Annotated[
        str,
        typer.Option("--token", envvar="INFRAHUB_API_TOKEN"),
    ] = "",
) -> None:
    """Toggle a device's `maintenance` boolean attribute."""
    if "infrahub-server" in address:
        address = "http://localhost:8000"
        note(f"INFRAHUB_ADDRESS rewritten to host-reachable {address}")

    if not token:
        fail("INFRAHUB_API_TOKEN is required.")
        raise typer.Exit(code=1)

    try:
        from infrahub_sdk import InfrahubClientSync
    except ImportError:
        fail("infrahub-sdk is not installed. Run `task setup` first.")
        sys.exit(1)

    client = InfrahubClientSync(address=address, api_token=token)
    matches = client.filters(kind=kind, name__value=device)
    if not matches:
        fail(f"{kind} [label]{device}[/] not found in Infrahub.")
        raise typer.Exit(code=1)

    node = matches[0]
    previous = bool(getattr(node, "maintenance").value)
    node.maintenance.value = state
    node.save()

    arrow = f"[muted]{previous}[/] → [{('warn' if state else 'ok')}]{state}[/]"
    console.print()
    console.print(
        Panel.fit(
            f"[label]{device}[/].maintenance: {arrow}",
            title=f"{kind} updated",
            border_style="yellow" if state else "green",
        )
    )

    if state:
        note("The next alert for this device will be SKIPPED by the policy.")
    else:
        note("The next alert for this device will be evaluated normally.")
