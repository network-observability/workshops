"""nobs — root Typer app.

Subcommands
-----------
    nobs status              # quick health snapshot of the stack
    nobs alerts              # active alerts (Alertmanager) as a Rich table
    nobs schema load PATH    # apply/migrate an Infrahub schema
    nobs maintenance         # toggle a SoT device's maintenance flag

Other workshops in this repo (or downstream) can either invoke `nobs`
directly or import the subcommand callables and register them under
their own Typer app — see workshops/autocon5/src/autocon5_cli/main.py.
"""
from __future__ import annotations

import typer

from .commands import alerts, maintenance, schema, status

app = typer.Typer(
    name="nobs",
    help="Network observability operator toolkit (workshops + ad-hoc).",
    no_args_is_help=True,
    rich_markup_mode="rich",
    add_completion=False,
    pretty_exceptions_show_locals=False,
)

app.command("status")(status.status)
app.command("alerts")(alerts.alerts)
app.command("maintenance")(maintenance.maintenance)
app.add_typer(schema.app, name="schema")


def main() -> None:  # pragma: no cover — entry point
    app()


if __name__ == "__main__":
    main()
