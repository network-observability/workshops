"""nobs - the single Typer entry point for the workshops repo.

Surface
-------
    Root:           setup, preflight, workshops
    Per workshop:   setup, up, down, destroy, restart, ps, logs, exec, build,
                    status, alerts, maintenance, schema  (gated by `Workshop.capabilities`),
                    plus `Workshop.extra_commands`

When `nobs` runs from inside a workshop's directory, that workshop's
commands are also mounted at root so the workshop name can be elided
(`cd workshops/autocon5 && nobs alerts` == `nobs autocon5 alerts`). The
three root primitives are not shadowed.
"""
from __future__ import annotations

from pathlib import Path

import typer
from rich.traceback import install as _install_rich_tb

# Rich tracebacks for any unhandled exception, with locals suppressed so
# accidental secrets don't end up on screen.
_install_rich_tb(show_locals=False)

from . import workshops as _workshops_module  # noqa: E402
from .commands import alerts, maintenance, schema, status  # noqa: E402
from .lifecycle import commands as lifecycle  # noqa: E402
from .lifecycle import env as _env  # noqa: E402
from .lifecycle import preflight as preflight_module  # noqa: E402
from .lifecycle import setup as setup_module  # noqa: E402
from .workshops import Workshop  # noqa: E402

# Names always reserved for the top-level meta commands. The auto-mount
# of the current workshop's commands skips these so the root primitives
# stay stable regardless of cwd.
_ROOT_PRIMITIVES: frozenset[str] = frozenset({"setup", "preflight", "workshops"})


def _detect_current_workshop(cwd: Path | None = None) -> Workshop | None:
    """Return the workshop whose `dir` contains `cwd`, or None."""
    cwd = (cwd or Path.cwd()).resolve()
    for ws in _workshops_module.REGISTRY:
        try:
            cwd.relative_to(ws.dir)
            return ws
        except ValueError:
            continue
    return None


def _register_workshop_commands(
    target: typer.Typer, ws: Workshop, *, skip: frozenset[str] = frozenset()
) -> None:
    """Mount a workshop's commands on `target`. `skip` drops named commands."""

    def add(name: str, fn) -> None:
        if name in skip:
            return
        target.command(name)(fn)

    def add_group(name: str, sub_app: typer.Typer) -> None:
        if name in skip:
            return
        target.add_typer(sub_app, name=name)

    # Lifecycle (always available)
    add("setup", setup_module.run_for(ws))
    add("up", lifecycle.up_for(ws))
    add("down", lifecycle.down_for(ws))
    add("destroy", lifecycle.destroy_for(ws))
    add("restart", lifecycle.restart_for(ws))
    add("ps", lifecycle.ps_for(ws))
    add("logs", lifecycle.logs_for(ws))
    add("exec", lifecycle.exec_for(ws))
    add("build", lifecycle.build_for(ws))

    # Operational primitives (gated by capabilities)
    if "status" in ws.capabilities:
        add("status", status.status_for(ws))
    if "alerts" in ws.capabilities:
        add("alerts", alerts.alerts_for(ws))
    if "maintenance" in ws.capabilities:
        add("maintenance", maintenance.maintenance_for(ws))
    if "schema" in ws.capabilities:
        add_group("schema", schema.app_for(ws))

    # Workshop-specific commands
    for cmd in ws.extra_commands:
        add(cmd.__name__.replace("_", "-"), cmd)


app = typer.Typer(
    name="nobs",
    help="Network observability operator toolkit (workshops + ad-hoc).",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.callback()
def _root_callback() -> None:
    """Load the current workshop's `.env` if cwd is inside one."""
    ws = _detect_current_workshop()
    if ws:
        _env.load_env(ws.dir)


# Top-level meta commands (workshop-agnostic).
app.command("setup")(setup_module.run)
app.command("preflight")(preflight_module.run)
app.command("workshops")(lifecycle.list_workshops)


# Per-workshop subcommand group (always available with prefix).
def _make_callback(ws: Workshop):
    """Workshop subgroup callback that loads the workshop's `.env`."""

    def _cb() -> None:
        _env.load_env(ws.dir)

    return _cb


for _ws in _workshops_module.REGISTRY:
    _sub = typer.Typer(
        name=_ws.name,
        help=f"{_ws.title} - workshop commands.",
        no_args_is_help=True,
        rich_markup_mode="rich",
        callback=_make_callback(_ws),
    )
    _register_workshop_commands(_sub, _ws)
    app.add_typer(_sub)


# Auto-mount the current workshop's commands at root level so prefix-free
# invocations work from inside the workshop dir. Skips the three root
# primitives so they're not shadowed.
_current_ws = _detect_current_workshop()
if _current_ws is not None:
    _register_workshop_commands(app, _current_ws, skip=_ROOT_PRIMITIVES)


def main() -> None:  # pragma: no cover - entry point
    app()


if __name__ == "__main__":
    main()
