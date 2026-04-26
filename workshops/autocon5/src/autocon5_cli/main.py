"""autocon5 — workshop CLI entry point.

Two kinds of subcommands:

  * **Re-exported from `nobs`** — the shared operator toolkit. So
    `autocon5 status`, `autocon5 alerts`, `autocon5 maintenance`,
    `autocon5 schema load` all work without attendees needing to know
    about the second binary.

  * **Workshop-specific** — `load-infrahub` (knows lab_vars.yml),
    `evidence` (knows the WorkshopBgpSession schema), `try-it` (walks
    the four canonical Part 3 paths).

`nobs` is also installed as its own console script — handy when you
want to drive arbitrary stacks not tied to AutoCon5.
"""
from __future__ import annotations

import typer
from nobs.commands import alerts as nobs_alerts
from nobs.commands import maintenance as nobs_maintenance
from nobs.commands import schema as nobs_schema
from nobs.commands import status as nobs_status

from . import evidence, load, try_it

app = typer.Typer(
    name="autocon5",
    help="AutoCon5 workshop CLI — load Infrahub, drive demos, peek at the stack.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
    pretty_exceptions_show_locals=False,
)

# --- Re-exported from nobs (generic, work against any compatible stack) ---
app.command("status",      help="Quick health snapshot of every service.")(nobs_status.status)
app.command("alerts",      help="List active Alertmanager alerts.")(nobs_alerts.alerts)
app.command("maintenance", help="Toggle a SoT device's maintenance flag.")(nobs_maintenance.maintenance)
app.add_typer(nobs_schema.app, name="schema", help="Manage Infrahub schemas.")

# --- Workshop-specific ---
app.command("load-infrahub", help="Apply the workshop schema + load lab_vars.yml.")(load.load_infrahub)
app.command("evidence",      help="Show the evidence bundle the Prefect flow would collect.")(evidence.evidence)
app.command("try-it",        help="Walk the four canonical Part 3 paths.")(try_it.try_it)


def main() -> None:  # pragma: no cover
    app()


if __name__ == "__main__":
    main()
