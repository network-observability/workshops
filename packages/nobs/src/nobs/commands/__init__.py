"""nobs subcommand modules.

Each module exposes a single Typer-decorated callable so the root app can
register them flat (no nested groups today). Workshops can also import
these to re-export them under their own CLI surface — e.g.

    from nobs.commands import status
    app.command("status")(status.status)
"""
