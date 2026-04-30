"""Modern Network Observability workshop plugin for `nobs` (slug: autocon5).

This package self-registers with `nobs` at import time. Importing
`autocon5_workshop` (e.g. via `nobs.main`) calls
`nobs.workshops.register(WORKSHOP)` and the per-workshop subcommand group
(`nobs autocon5 ...`) becomes available.
"""
from __future__ import annotations

from pathlib import Path

from nobs.workshops import Workshop, register

from . import bootstrap, evidence, flap, incident, load, page, scenarios, try_it
from .preflight import runner as preflight_runner

__version__ = "0.1.0"

WORKSHOP = Workshop(
    name="autocon5",
    title="Modern Network Observability",
    # __init__.py is at workshops/autocon5/src/autocon5_workshop/__init__.py
    # parents[0] = autocon5_workshop, parents[1] = src, parents[2] = workshops/autocon5/.
    dir=Path(__file__).resolve().parents[2],
    bootstrap=bootstrap.run,
    extra_commands=[
        load.load_infrahub,
        evidence.evidence,
        try_it.try_it,
        flap.flap_interface,
        incident.incident,
        page.page,
        scenarios.scenarios,
        preflight_runner.preflight,
    ],
)
register(WORKSHOP)
