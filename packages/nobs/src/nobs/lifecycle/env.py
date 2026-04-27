"""Single startup loader for a workshop's `.env` file.

Centralises the historical `infrahub-server -> localhost` rewrite that used
to live in each command. Idempotent: safe to call multiple times.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def load_env(workshop_dir: Path) -> dict[str, str]:
    """Load `<workshop_dir>/.env` into `os.environ`, applying the
    `infrahub-server -> localhost` rewrite once.

    Parameters
    ----------
    workshop_dir
        The workshop directory that contains a `.env` file. Missing file
        is allowed - the function just merges the existing `os.environ`.

    Returns
    -------
    dict
        The merged environment dict (file values overlaid with the existing
        `os.environ`, then the rewrite applied). Useful for diagnostics.
    """
    env_file = workshop_dir / ".env"
    values = dotenv_values(env_file) if env_file.is_file() else {}
    merged: dict[str, str] = {}
    for k, v in values.items():
        if v is not None:
            merged[k] = v
    # os.environ wins over .env file (matches docker-compose semantics).
    for k, v in os.environ.items():
        merged[k] = v

    addr = merged.get("INFRAHUB_ADDRESS", "")
    if "infrahub-server" in addr:
        merged["INFRAHUB_ADDRESS"] = "http://localhost:8000"

    for k, v in merged.items():
        os.environ[k] = str(v)
    return merged
