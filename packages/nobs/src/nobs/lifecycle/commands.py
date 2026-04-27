"""Per-workshop generic lifecycle closures.

Each `<verb>_for(ws)` returns a Typer-friendly callable bound to the
given `Workshop`. `nobs.main` wires these into the per-workshop
sub-Typer.

The `list_workshops` function (top-level `nobs workshops`) renders the
registry as a Rich tree.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

import typer
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.tree import Tree

from .. import workshops as _workshops_module
from .._console import console, fail, ok, step
from ..workshops import Workshop
from . import env as _env
from .compose import run_compose

# ---------------------------------------------------------------------------
# Top-level (registry-level) commands
# ---------------------------------------------------------------------------


def list_workshops() -> None:
    """List the workshops registered with `nobs` as a Rich tree."""
    tree = Tree("[label]Registered workshops[/]", guide_style="dim")
    if not _workshops_module.REGISTRY:
        tree.add("[muted](none registered)[/]")
        console.print()
        console.print(tree)
        return

    for ws in _workshops_module.REGISTRY:
        node = tree.add(f"[label]{ws.name}[/] - {ws.title}")
        node.add(f"dir         [muted]{ws.dir}[/]")
        node.add(f"compose     [muted]{ws.resolved_compose_file()}[/]")
        node.add(f"bootstrap   {'yes' if ws.bootstrap else '[muted]none[/]'}")
        node.add(f"commands    {len(ws.extra_commands)} extra")
    console.print()
    console.print(tree)


# ---------------------------------------------------------------------------
# Per-workshop closures
# ---------------------------------------------------------------------------


def up_for(ws: Workshop) -> Callable[..., None]:
    def up(
        build: Annotated[
            bool,
            typer.Option("--build/--no-build", help="Pass --build to docker compose up."),
        ] = True,
        services: Annotated[
            list[str] | None,
            typer.Argument(help="Specific services to bring up (default: all)."),
        ] = None,
    ) -> None:
        if ws.bootstrap is not None:
            ws.bootstrap()
        _env.load_env(ws.dir)

        action = "up -d --build" if build else "up -d"
        step(f"docker compose {action} (project={ws.name})")
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"Pulling / building {ws.name} stack",
                total=None,
            )
            result = run_compose(action, ws, services=services)
            progress.update(task, completed=1)
        if result.returncode != 0:
            fail(f"docker compose exited {result.returncode}")
            raise typer.Exit(code=result.returncode)
        ok("stack online")
        _print_urls_panel(ws)

    up.__doc__ = f"Bring the {ws.title} stack online."
    up.__name__ = "up"
    return up


def down_for(ws: Workshop) -> Callable[..., None]:
    def down() -> None:
        _env.load_env(ws.dir)
        step(f"docker compose down (project={ws.name})")
        result = run_compose("down", ws)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
        ok("stack stopped (volumes preserved)")

    down.__doc__ = f"Stop the {ws.title} stack (keeps volumes)."
    down.__name__ = "down"
    return down


def destroy_for(ws: Workshop) -> Callable[..., None]:
    def destroy() -> None:
        _env.load_env(ws.dir)
        step(f"docker compose down --volumes --remove-orphans (project={ws.name})")
        result = run_compose("down --volumes --remove-orphans", ws)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
        ok("stack destroyed (volumes removed)")

    destroy.__doc__ = f"Stop {ws.title} AND remove its volumes (full reset)."
    destroy.__name__ = "destroy"
    return destroy


def restart_for(ws: Workshop) -> Callable[..., None]:
    def restart(
        services: Annotated[
            list[str] | None,
            typer.Argument(help="Specific services to restart (default: full down + up)."),
        ] = None,
    ) -> None:
        _env.load_env(ws.dir)
        if services:
            step(f"docker compose restart {' '.join(services)} (project={ws.name})")
            result = run_compose("restart", ws, services=services)
            if result.returncode != 0:
                raise typer.Exit(code=result.returncode)
            ok(f"restarted: {', '.join(services)}")
            return

        # Full restart: down then up -d --build (matches the old Taskfile behavior).
        step(f"docker compose down (project={ws.name})")
        result = run_compose("down", ws)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
        step(f"docker compose up -d --build (project={ws.name})")
        result = run_compose("up -d --build", ws)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
        ok("stack restarted")

    restart.__doc__ = f"Restart the {ws.title} stack (down + up)."
    restart.__name__ = "restart"
    return restart


def ps_for(ws: Workshop) -> Callable[..., None]:
    def ps() -> None:
        _env.load_env(ws.dir)
        result = run_compose("ps", ws)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)

    ps.__doc__ = f"Show running services for {ws.title}."
    ps.__name__ = "ps"
    return ps


def logs_for(ws: Workshop) -> Callable[..., None]:
    def logs(
        service: Annotated[
            str | None,
            typer.Argument(help="Service name to follow (default: all services)."),
        ] = None,
        tail: Annotated[int, typer.Option("--tail", help="Number of lines to show.")] = 200,
        follow: Annotated[bool, typer.Option("--follow/--no-follow", "-f")] = True,
    ) -> None:
        _env.load_env(ws.dir)
        action = f"logs --tail={tail}"
        if follow:
            action += " -f"
        services = [service] if service else None
        result = run_compose(action, ws, services=services)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)

    logs.__doc__ = f"Follow logs for a service in the {ws.title} stack."
    logs.__name__ = "logs"
    return logs


def exec_for(ws: Workshop) -> Callable[..., None]:
    def exec_(
        service: Annotated[str, typer.Argument(help="Service name.")],
        command: Annotated[
            list[str] | None,
            typer.Argument(help="Command to run inside the container (default: sh)."),
        ] = None,
    ) -> None:
        _env.load_env(ws.dir)
        cmd = command or ["sh"]
        result = run_compose("exec", ws, services=[service, *cmd])
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)

    exec_.__doc__ = f"Exec a command inside a {ws.title} container."
    exec_.__name__ = "exec"
    return exec_


def build_for(ws: Workshop) -> Callable[..., None]:
    def build(
        services: Annotated[
            list[str] | None,
            typer.Argument(help="Services to rebuild (default: all)."),
        ] = None,
    ) -> None:
        _env.load_env(ws.dir)
        step(f"docker compose build (project={ws.name})")
        result = run_compose("build", ws, services=services)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
        # Bring rebuilt services back up.
        step("docker compose up -d (post-build)")
        result = run_compose("up -d", ws, services=services)
        if result.returncode != 0:
            raise typer.Exit(code=result.returncode)
        ok("rebuild complete")

    build.__doc__ = f"Rebuild service(s) in the {ws.title} stack."
    build.__name__ = "build"
    return build


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_urls_panel(ws: Workshop) -> None:
    body = (
        "Grafana       [muted]http://localhost:3000[/]\n"
        "Prometheus    [muted]http://localhost:9090[/]\n"
        "Alertmanager  [muted]http://localhost:9093[/]\n"
        "Loki          [muted]http://localhost:3001[/]\n"
        "Infrahub      [muted]http://localhost:8000[/]\n"
        "Prefect       [muted]http://localhost:4200[/]\n"
        "Sonda         [muted]http://localhost:8085[/]"
    )
    console.print()
    console.print(
        Panel.fit(
            body,
            title=f"{ws.title} - useful URLs",
            border_style="green",
        )
    )
