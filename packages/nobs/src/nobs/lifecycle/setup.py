"""`nobs setup` - one-shot bring-up orchestration.

Steps:
1. Verify `uv` is on PATH.
2. Run `uv sync --all-packages` (with a Rich progress spinner).
3. Run `nobs preflight` (warns do not block; only failures abort).
4. For each registered workshop, call its `bootstrap()` hook (if any).
5. Render a final summary panel.

Also exposes `run_for(ws)` - same as step 4 for a single workshop, used
by `nobs <workshop> setup`.
"""
from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable

import typer
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from .. import workshops as _workshops_module
from .._console import console, fail, ok, step, warn
from ..workshops import Workshop
from . import preflight as _preflight_module

_UV_INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"


def run() -> None:
    """Top-level `nobs setup` - install deps, preflight, bootstrap every workshop."""
    if shutil.which("uv") is None:
        fail(f"`uv` is not on PATH. Install it from {_UV_INSTALL_URL}, then re-run `nobs setup`.")
        raise typer.Exit(code=1)

    step("Installing workspace dependencies (uv sync --all-packages)")
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("uv sync --all-packages", total=None)
        result = subprocess.run(
            ["uv", "sync", "--all-packages"],
            check=False,
            capture_output=True,
            text=True,
        )
        progress.update(task, completed=1)
    if result.returncode != 0:
        fail("uv sync failed:")
        if result.stderr:
            console.print(result.stderr)
        raise typer.Exit(code=result.returncode)
    ok("Dependencies installed")

    # Preflight: only fail-blocking aborts; warns are surfaced but allowed.
    step("Running preflight checks")
    preflight_failed = False
    try:
        _preflight_module.run()
    except typer.Exit as exc:
        preflight_failed = exc.exit_code != 0

    bootstrapped: list[str] = []
    if _workshops_module.REGISTRY:
        step("Bootstrapping workshops")
    for ws in _workshops_module.REGISTRY:
        _bootstrap_one(ws)
        bootstrapped.append(ws.name)

    _summary(
        deps_installed=True,
        bootstrapped=bootstrapped,
        preflight_failed=preflight_failed,
    )

    if preflight_failed:
        raise typer.Exit(code=1)


def run_for(ws: Workshop) -> Callable[[], None]:
    """Return a Typer-friendly callable that bootstraps just `ws`.

    Used by `nobs <workshop> setup`. Skips uv sync + preflight (those are
    repo-global; the per-workshop flow assumes you already ran
    `nobs setup` once).
    """

    def setup() -> None:
        _bootstrap_one(ws)
        console.print()
        console.print(
            Panel.fit(
                f"[ok]{ws.title}[/] is ready.\n"
                f"Next: [label]nobs {ws.name} up[/]",
                title=f"nobs {ws.name} setup",
                border_style="green",
            )
        )

    setup.__doc__ = f"Bootstrap {ws.title} (workshop-scoped setup hook)."
    setup.__name__ = "setup"
    return setup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bootstrap_one(ws: Workshop) -> None:
    if ws.bootstrap is None:
        ok(f"{ws.name}: no bootstrap hook (nothing to do)")
        return
    try:
        ws.bootstrap()
    except Exception as exc:  # noqa: BLE001 - surface to operator + continue
        warn(f"{ws.name} bootstrap raised {type(exc).__name__}: {exc}")


def _summary(*, deps_installed: bool, bootstrapped: list[str], preflight_failed: bool) -> None:
    deps_line = "[ok]installed[/]" if deps_installed else "[fail]skipped[/]"
    ws_line = ", ".join(bootstrapped) if bootstrapped else "[muted]none registered[/]"
    pre_line = "[fail]FAILED[/]" if preflight_failed else "[ok]passed[/]"

    border = "red" if preflight_failed else "green"
    console.print()
    console.print(
        Panel.fit(
            f"deps          {deps_line}\n"
            f"workshops     {ws_line}\n"
            f"preflight     {pre_line}",
            title="nobs setup",
            border_style=border,
        )
    )
