"""`nobs schema load` - wrap `infrahubctl schema load`."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from .._console import fail, ok, step
from ..lifecycle import env as _env
from ..workshops import Workshop

app = typer.Typer(help="Manage Infrahub schemas.", no_args_is_help=True, rich_markup_mode="rich")


@app.command("load")
def load(
    path: Annotated[Path, typer.Argument(help="Path to the schema YAML file.")],
    address: Annotated[
        str,
        typer.Option("--address", envvar="INFRAHUB_ADDRESS", help="Infrahub URL."),
    ] = "http://localhost:8000",
    token: Annotated[
        str,
        typer.Option("--token", envvar="INFRAHUB_API_TOKEN", help="Infrahub API token."),
    ] = "",
) -> None:
    """Apply (or migrate) an Infrahub schema YAML."""
    if not path.exists():
        fail(f"schema file not found: {path}")
        raise typer.Exit(code=1)
    if not token:
        fail("INFRAHUB_API_TOKEN is required (set it in .env or pass --token).")
        raise typer.Exit(code=1)
    if shutil.which("infrahubctl") is None:
        fail("`infrahubctl` is not on PATH. Did you run `nobs setup` (uv sync)?")
        raise typer.Exit(code=1)

    step(f"Applying schema [label]{path}[/]")
    host_addr = _env.host_address(address)
    env = {**os.environ, "INFRAHUB_ADDRESS": host_addr, "INFRAHUB_API_TOKEN": token}
    result = subprocess.run(
        ["infrahubctl", "schema", "load", str(path)],
        env=env,
        check=False,
    )
    if result.returncode != 0:
        fail(f"infrahubctl schema load exited {result.returncode}")
        raise typer.Exit(code=result.returncode)
    ok("Schema applied")


def app_for(ws: Workshop) -> typer.Typer:
    """Return a `schema` Typer sub-app bound to the workshop's `.env`.

    Loads the workshop's `.env` once before delegating to the underlying
    `load` callback, so `INFRAHUB_ADDRESS` / `INFRAHUB_API_TOKEN` defaults
    reflect the workshop's stack.
    """
    sub = typer.Typer(
        help=f"Manage Infrahub schemas (defaults: {ws.title}).",
        no_args_is_help=True,
        rich_markup_mode="rich",
    )

    @sub.command("load")
    def load_ws(
        path: Annotated[Path, typer.Argument(help="Path to the schema YAML file.")],
        address: Annotated[
            str,
            typer.Option("--address", envvar="INFRAHUB_ADDRESS", help="Infrahub URL."),
        ] = "http://localhost:8000",
        token: Annotated[
            str,
            typer.Option("--token", envvar="INFRAHUB_API_TOKEN", help="Infrahub API token."),
        ] = "",
    ) -> None:
        _env.load_env(ws.dir)
        load(path=path, address=address, token=token)

    load_ws.__doc__ = f"Apply an Infrahub schema YAML against the {ws.title} stack."
    return sub
