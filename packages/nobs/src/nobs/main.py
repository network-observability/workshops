"""nobs - the single Typer entry point for the workshops repo.

Top-level subcommands
---------------------
    nobs setup              # uv sync + per-workshop bootstrap + preflight
    nobs preflight          # host environment check (Docker, RAM, disk, network)
    nobs workshops          # list registered workshops as a Rich tree

    nobs status             # ad-hoc stack health snapshot (env-defined URLs)
    nobs alerts             # ad-hoc Alertmanager listing
    nobs maintenance        # ad-hoc Infrahub maintenance toggle
    nobs schema load PATH   # ad-hoc Infrahub schema apply

Per-workshop subcommand groups (e.g. `nobs autocon5 ...`) are built
dynamically from each registered Workshop. Workshops self-register at
package-import time (see `nobs/__init__.py`).
"""
from __future__ import annotations

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

app = typer.Typer(
    name="nobs",
    help="Network observability operator toolkit (workshops + ad-hoc).",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
    pretty_exceptions_enable=False,
)

# Top-level (workshop-agnostic).
app.command("setup")(setup_module.run)
app.command("preflight")(preflight_module.run)
app.command("workshops")(lifecycle.list_workshops)
app.command("status")(status.status)
app.command("alerts")(alerts.alerts)
app.command("maintenance")(maintenance.maintenance)
app.add_typer(schema.app, name="schema")

# Per-workshop subcommand group.
def _make_callback(ws):
    """Build a Typer callback that loads the workshop's `.env` BEFORE Typer
    parses any subcommand's `envvar=`-driven options. Without this, options
    like `--infrahub-url` resolve from a stale `os.environ` (whatever the
    user's shell happened to have) instead of the workshop's `.env`."""

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
    _sub.command("setup")(setup_module.run_for(_ws))
    _sub.command("up")(lifecycle.up_for(_ws))
    _sub.command("down")(lifecycle.down_for(_ws))
    _sub.command("destroy")(lifecycle.destroy_for(_ws))
    _sub.command("restart")(lifecycle.restart_for(_ws))
    _sub.command("ps")(lifecycle.ps_for(_ws))
    _sub.command("logs")(lifecycle.logs_for(_ws))
    _sub.command("exec")(lifecycle.exec_for(_ws))
    _sub.command("build")(lifecycle.build_for(_ws))
    _sub.command("status")(status.status_for(_ws))
    _sub.command("alerts")(alerts.alerts_for(_ws))
    _sub.command("maintenance")(maintenance.maintenance_for(_ws))
    _sub.add_typer(schema.app_for(_ws), name="schema")
    for _cmd in _ws.extra_commands:
        _sub.command(_cmd.__name__.replace("_", "-"))(_cmd)
    app.add_typer(_sub)


def main() -> None:  # pragma: no cover - entry point
    app()


if __name__ == "__main__":
    main()
