"""`nobs status` — quick health snapshot of the running stack."""
from __future__ import annotations

from typing import Annotated

import requests
import typer
from rich.table import Table

from .._console import console


def status(
    prom_url: Annotated[str, typer.Option(envvar="PROMETHEUS_URL")] = "http://localhost:9090",
    loki_url: Annotated[str, typer.Option(envvar="LOKI_URL")] = "http://localhost:3001",
    am_url: Annotated[str, typer.Option(envvar="ALERTMANAGER_URL")] = "http://localhost:9093",
    infrahub_url: Annotated[str, typer.Option(envvar="INFRAHUB_ADDRESS")] = "http://localhost:8000",
    grafana_url: Annotated[str, typer.Option()] = "http://localhost:3000",
    prefect_url: Annotated[str, typer.Option()] = "http://localhost:4200",
    sonda_url: Annotated[str, typer.Option()] = "http://localhost:8085",
) -> None:
    """Hit each service's health endpoint and report a tidy table.

    Useful as the first thing to run after bringing the stack up — confirms
    the stack is ready before you start loading data or driving demos.
    """
    targets = [
        ("Grafana", grafana_url, "/api/health"),
        ("Prometheus", prom_url, "/-/ready"),
        ("Loki", loki_url, "/ready"),
        ("Alertmanager", am_url, "/-/ready"),
        ("Infrahub", infrahub_url, "/api/healthcheck"),
        ("Prefect", prefect_url, "/api/health"),
        ("Sonda server", sonda_url, "/health"),
    ]

    table = Table(title="Stack status", show_lines=False, header_style="label")
    table.add_column("Service")
    table.add_column("URL")
    table.add_column("State", justify="right")

    any_down = False
    for name, base, path in targets:
        url = f"{base.rstrip('/')}{path}"
        try:
            r = requests.get(url, timeout=3)
            state = "[ok]ok[/]" if r.ok else f"[warn]http {r.status_code}[/]"
            if not r.ok:
                any_down = True
        except requests.RequestException as e:  # noqa: BLE001
            state = f"[fail]down[/] [muted]({type(e).__name__})[/]"
            any_down = True
        table.add_row(name, base, state)

    console.print()
    console.print(table)
    if any_down:
        console.print("\n[warn]Some services aren't ready yet — give them a minute, or check `task logs`.[/]")
        raise typer.Exit(code=1)
