"""docker compose command builder and subprocess wrapper.

We require Compose v2 (`docker compose`, not `docker-compose`); the
preflight check enforces this. The legacy `DOCKER_COMPOSE_WITH_HASH`
fallback used by netobs is intentionally dropped.
"""
from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Sequence

from ..workshops import Workshop


def compose_cmd(
    action: str,
    ws: Workshop,
    *,
    services: Sequence[str] | None = None,
    extra: str = "",
) -> list[str]:
    """Build the `docker compose ...` argv list for a workshop action.

    Parameters
    ----------
    action
        The compose subcommand string (e.g. ``"up -d --build"``, ``"ps"``,
        ``"logs -f --tail=200"``). May contain whitespace-separated args.
    ws
        Workshop whose compose project / file we operate against.
    services
        Optional service names to append after the action.
    extra
        Optional additional whitespace-separated args appended after the
        action and before services.
    """
    cmd: list[str] = [
        "docker",
        "compose",
        "--project-name",
        ws.name,
        "-f",
        str(ws.resolved_compose_file()),
        *shlex.split(action),
    ]
    if extra:
        cmd.extend(shlex.split(extra))
    if services:
        cmd.extend(services)
    return cmd


def run_compose(
    action: str,
    ws: Workshop,
    *,
    services: Sequence[str] | None = None,
    extra: str = "",
    capture: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run a compose command in the workshop's directory.

    Streams stdout/stderr to the terminal when ``capture=False``; captures
    both when ``capture=True`` (returned on the `CompletedProcess`).
    """
    cmd = compose_cmd(action, ws, services=services, extra=extra)
    return subprocess.run(
        cmd,
        cwd=str(ws.dir),
        env=os.environ.copy(),
        check=check,
        capture_output=capture,
        text=True,
    )
