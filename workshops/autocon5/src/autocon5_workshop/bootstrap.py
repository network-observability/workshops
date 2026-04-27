"""Workshop-specific setup: copy `.env.example` to `.env` if missing."""
from __future__ import annotations

import shutil
from pathlib import Path

from nobs._console import note, ok

WORKSHOP_DIR = Path(__file__).resolve().parents[2]


def run() -> None:
    """Ensure the workshop has a `.env` file (copying from `.env.example`)."""
    env = WORKSHOP_DIR / ".env"
    example = WORKSHOP_DIR / ".env.example"
    if env.exists():
        note(f".env already exists at {env}")
        return
    if not example.exists():
        raise RuntimeError(f"{example} not found - cannot bootstrap")
    shutil.copy2(example, env)
    ok(f"created {env} from .env.example")
