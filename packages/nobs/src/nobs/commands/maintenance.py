"""`nobs maintenance` - toggle a SoT device's maintenance flag.

Generic over the schema kind (defaults to `WorkshopDevice` for the
AutoCon5 workshop). Future workshops with a different node type can
override `--kind` without forking the command.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from typing import Annotated

import requests
import typer
from rich.panel import Panel

from .._console import console, fail, note
from ..clients.loki import LokiClient
from ..lifecycle import env as _env
from ..workshops import Workshop


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
    loki_url: Annotated[
        str,
        typer.Option("--loki-url", envvar="LOKI_URL"),
    ] = "http://localhost:3001",
) -> None:
    """Toggle a device's `maintenance` boolean attribute."""
    if not token:
        fail("INFRAHUB_API_TOKEN is required.")
        raise typer.Exit(code=1)

    host_addr = _env.host_address(address)
    if host_addr != address:
        note(f"INFRAHUB_ADDRESS rewritten to host-reachable {host_addr}")

    try:
        from infrahub_sdk import Config, InfrahubClientSync
    except ImportError:
        fail("infrahub-sdk is not installed. Run `nobs setup` first.")
        sys.exit(1)

    client = InfrahubClientSync(address=host_addr, config=Config(api_token=token))
    matches = client.filters(kind=kind, name__value=device)
    if not matches:
        fail(f"{kind} [label]{device}[/] not found in Infrahub.")
        raise typer.Exit(code=1)

    node = matches[0]
    previous = bool(node.maintenance.value)
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

    # Labels contracted with device-health.json's "Device Config Push" annotation.
    # Routes through sonda /events; failure is loud — the SoT panel above
    # confirms the maintenance flag was committed even if the annotation didn't
    # land.
    try:
        LokiClient(loki_url).annotate(
            labels={
                "device": device,
                "source": "workshop-trigger",
                "event": "config-push",
                "level": "info",
            },
            message=f"Configured from CLI: {device}.maintenance = {state}",
        )
    except requests.RequestException as exc:
        fail(f"sonda /events post failed: {exc}")
        raise typer.Exit(code=1) from exc

    if state:
        note("The next alert for this device will be SKIPPED by the policy.")
    else:
        note("The next alert for this device will be evaluated normally.")


def maintenance_for(ws: Workshop) -> Callable[..., None]:
    """Return a `maintenance` callable bound to the workshop's `.env` URLs."""

    def maintenance_ws(
        device: Annotated[
            str,
            typer.Option(
                "--device", "-d", help="Device name (matches the kind's `name` attribute)."
            ),
        ],
        state: Annotated[
            bool,
            typer.Option(
                "--state/--clear",
                help="Set maintenance to true (--state) or false (--clear).",
            ),
        ] = True,
        kind: Annotated[
            str, typer.Option("--kind", help="Infrahub node kind to update.")
        ] = "WorkshopDevice",
        address: Annotated[
            str, typer.Option("--address", envvar="INFRAHUB_ADDRESS")
        ] = "http://localhost:8000",
        token: Annotated[
            str, typer.Option("--token", envvar="INFRAHUB_API_TOKEN")
        ] = "",
        loki_url: Annotated[
            str, typer.Option("--loki-url", envvar="LOKI_URL")
        ] = "http://localhost:3001",
    ) -> None:
        _env.load_env(ws.dir)
        maintenance(
            device=device,
            state=state,
            kind=kind,
            address=address,
            token=token,
            loki_url=loki_url,
        )

    maintenance_ws.__doc__ = f"Toggle a {ws.title} device's maintenance flag."
    maintenance_ws.__name__ = "maintenance"
    return maintenance_ws
