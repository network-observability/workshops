"""Building a Network Observability Stack workshop plugin for `nobs` (slug: packt).

This package self-registers with `nobs` at import time. Importing
`packt_workshop` (e.g. via `nobs.main`) calls
`nobs.workshops.register(WORKSHOP)` and the per-workshop subcommand group
(`nobs packt ...`) becomes available.
"""

from __future__ import annotations

from pathlib import Path

from nobs.workshops import Workshop, register

from . import (
    bootstrap,
    cycle,
    evidence,
    flap,
    incident,
    load,
    page,
    rca,
    reset,
    scenarios,
    silences,
    try_it,
)
from .preflight import runner as preflight_runner

__version__ = "0.1.0"

WORKSHOP = Workshop(
    name="packt",
    title="Packt — Building a Network Observability Stack with Tools, Automation, and AI",
    # __init__.py is at workshops/packt/src/packt_workshop/__init__.py
    # parents[0] = packt_workshop, parents[1] = src, parents[2] = workshops/packt/.
    dir=Path(__file__).resolve().parents[2],
    bootstrap=bootstrap.run,
    extra_commands=[
        load.load_infrahub,
        evidence.evidence,
        rca.rca,
        cycle.cycle,
        silences.silences,
        try_it.try_it,
        flap.flap_interface,
        incident.incident,
        page.page,
        reset.reset,
        scenarios.scenarios,
        preflight_runner.preflight,
    ],
)
register(WORKSHOP)
