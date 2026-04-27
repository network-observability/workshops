"""Single startup loader for a workshop's `.env` file.

Two responsibilities, deliberately separated:

* `load_env()` merges `<workshop_dir>/.env` into `os.environ` so subsequent
  Typer commands and any `docker compose` subprocess (which inherits
  `os.environ`) see the workshop's values. This is a plain dotenv merge
  with no value mutation.

* `host_address()` returns the host-reachable form of a URL whose host
  defaults to the docker-network DNS name `infrahub-server`. Host-side
  CLI commands (those that talk to Infrahub from outside the docker
  network) call this on the URL they receive from Typer, just before
  constructing the SDK client. The rewrite is NOT applied to
  `os.environ` because compose subprocesses then inherit the wrong
  value and inject `localhost:8000` into `prefect-flows`'s container,
  which breaks the in-network Prefect → Infrahub queries.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

# Container DNS name of the in-network Infrahub server. The workshop's
# `.env.example` defaults `INFRAHUB_ADDRESS` to this value because compose
# auto-loads `.env` and substitutes it into other containers' env. CLI
# commands running on the host can't resolve this, so they swap to
# localhost via `host_address()` at the call site.
_CONTAINER_INFRAHUB_HOST = "infrahub-server"
_HOST_INFRAHUB_FALLBACK = "http://localhost:8000"


def load_env(workshop_dir: Path) -> dict[str, str]:
    """Merge `<workshop_dir>/.env` into `os.environ` and return the merged dict.

    `os.environ` wins over `.env` (matches docker-compose precedence).
    No value mutation: callers that need a host-reachable URL must call
    `host_address()` on the value they receive from Typer.

    Parameters
    ----------
    workshop_dir
        Workshop directory that contains a `.env` file. Missing file is
        allowed - merge becomes a no-op (returns `os.environ` snapshot).
    """
    env_file = workshop_dir / ".env"
    file_values: dict[str, str] = {}
    if env_file.is_file():
        for k, v in dotenv_values(env_file).items():
            if v is not None:
                file_values[k] = v

    merged: dict[str, str] = {**file_values, **os.environ}
    for k, v in merged.items():
        os.environ[k] = str(v)
    return merged


def host_address(value: str | None) -> str:
    """Return a host-reachable URL for an Infrahub address.

    If the supplied value contains the in-network container DNS name
    `infrahub-server`, swap to `http://localhost:8000`. Otherwise return
    the value unchanged (so users who set `INFRAHUB_ADDRESS` to a real
    external host still get what they asked for).

    Returns the empty string for `None` / empty inputs so callers can
    chain it directly into a `typer.Option` default check.
    """
    if not value:
        return ""
    if _CONTAINER_INFRAHUB_HOST in value:
        return _HOST_INFRAHUB_FALLBACK
    return value
