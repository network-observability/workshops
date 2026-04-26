"""`nobs schema load` — wrap `infrahubctl schema load`."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Annotated

import typer

from .._console import fail, ok, step

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
    if "infrahub-server" in address:
        address = "http://localhost:8000"

    if not path.exists():
        fail(f"schema file not found: {path}")
        raise typer.Exit(code=1)
    if not token:
        fail("INFRAHUB_API_TOKEN is required (set it in .env or pass --token).")
        raise typer.Exit(code=1)
    if shutil.which("infrahubctl") is None:
        fail("`infrahubctl` is not on PATH. Did you run `task setup` (uv sync)?")
        raise typer.Exit(code=1)

    step(f"Applying schema [label]{path}[/]")
    env = {**os.environ, "INFRAHUB_ADDRESS": address, "INFRAHUB_API_TOKEN": token}
    result = subprocess.run(
        ["infrahubctl", "schema", "load", str(path)],
        env=env,
        check=False,
    )
    if result.returncode != 0:
        fail(f"infrahubctl schema load exited {result.returncode}")
        raise typer.Exit(code=result.returncode)
    ok("Schema applied")
