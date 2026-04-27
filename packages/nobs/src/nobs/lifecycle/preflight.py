"""`nobs preflight` - host environment sanity check.

Python port of the previous `scripts/preflight.sh`. Validates:

- Docker is on PATH.
- Docker Compose v2 is available (the `docker compose` subcommand).
- RAM >= 8 GiB ok / >= 6 GiB warn / < 6 GiB fail.
- Free disk in the current directory >= 5 GiB.
- Outbound reachability to `ghcr.io`, `registry-1.docker.io`, `github.com`.

The `task` (go-task) check is intentionally dropped - go-task is being
removed from the workshops repo as part of the `nobs`-as-single-CLI
migration.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import httpx
import psutil
import typer
from rich.panel import Panel
from rich.table import Table

from .._console import console

CheckState = Literal["ok", "warn", "fail"]


@dataclass(frozen=True)
class CheckResult:
    """One row of the preflight table."""

    name: str
    state: CheckState
    detail: str


def run() -> None:
    """Run all preflight checks and render a Rich table + summary panel.

    Exits with code 1 if any check returned ``fail``. Warnings do not
    block.
    """
    results: list[CheckResult] = []
    results.extend(_check_tooling())
    results.extend(_check_capacity())
    results.extend(_check_network())

    pass_n = sum(1 for r in results if r.state == "ok")
    warn_n = sum(1 for r in results if r.state == "warn")
    fail_n = sum(1 for r in results if r.state == "fail")

    table = Table(title="Preflight checks", show_lines=False, header_style="label")
    table.add_column("Check", no_wrap=True)
    table.add_column("State", justify="right")
    table.add_column("Detail")

    state_styles = {
        "ok": "[ok]ok[/]",
        "warn": "[warn]warn[/]",
        "fail": "[fail]FAIL[/]",
    }
    for r in results:
        table.add_row(r.name, state_styles[r.state], r.detail)

    console.print()
    console.print(table)

    summary = f"[ok]{pass_n} ok[/]   [warn]{warn_n} warn[/]   [fail]{fail_n} fail[/]"
    border = "red" if fail_n else ("yellow" if warn_n else "green")
    console.print()
    console.print(Panel.fit(summary, title="Result", border_style=border))

    if fail_n:
        console.print()
        console.print(
            Panel.fit(
                "Resolve the failures above before running [label]nobs <workshop> up[/].",
                title="What to fix",
                border_style="red",
            )
        )
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_tooling() -> list[CheckResult]:
    out: list[CheckResult] = []
    if shutil.which("docker"):
        version = _silent_run(["docker", "--version"]) or "(version unknown)"
        out.append(CheckResult("docker on PATH", "ok", version))
    else:
        out.append(CheckResult("docker on PATH", "fail", "docker is not on PATH"))

    compose_version = _silent_run(["docker", "compose", "version", "--short"])
    if compose_version:
        out.append(CheckResult("docker compose v2", "ok", compose_version))
    elif shutil.which("docker-compose"):
        out.append(
            CheckResult(
                "docker compose v2",
                "fail",
                "docker-compose v1 detected - install Compose v2 (the `docker compose` subcommand)",
            )
        )
    else:
        out.append(
            CheckResult("docker compose v2", "fail", "docker compose subcommand not available")
        )
    return out


def _check_capacity() -> list[CheckResult]:
    out: list[CheckResult] = []
    total_gib = psutil.virtual_memory().total // (1024**3)
    if total_gib >= 8:
        out.append(CheckResult("RAM available", "ok", f"{total_gib} GiB"))
    elif total_gib >= 6:
        out.append(
            CheckResult(
                "RAM available",
                "warn",
                f"{total_gib} GiB - tight headroom; close other apps before running `up`",
            )
        )
    else:
        out.append(
            CheckResult(
                "RAM available",
                "fail",
                f"{total_gib} GiB - need ~8 GiB for the full stack",
            )
        )

    free_gib = shutil.disk_usage(Path.cwd()).free // (1024**3)
    if free_gib >= 5:
        out.append(CheckResult("Free disk (cwd)", "ok", f"{free_gib} GiB"))
    else:
        out.append(
            CheckResult(
                "Free disk (cwd)",
                "fail",
                f"{free_gib} GiB - need ~5 GiB for image pulls",
            )
        )
    return out


def _check_network() -> list[CheckResult]:
    targets = [
        "https://ghcr.io",
        "https://registry-1.docker.io",
        "https://github.com",
    ]
    out: list[CheckResult] = []
    for url in targets:
        try:
            r = httpx.head(url, timeout=5.0, follow_redirects=False)
            if 200 <= r.status_code < 400:
                out.append(CheckResult(f"reach {url}", "ok", f"http {r.status_code}"))
            else:
                out.append(CheckResult(f"reach {url}", "warn", f"http {r.status_code}"))
        except (httpx.HTTPError, OSError) as e:
            out.append(CheckResult(f"reach {url}", "warn", f"{type(e).__name__}: {e}"))
    return out


def _silent_run(cmd: list[str]) -> str | None:
    """Run ``cmd``, return stripped stdout on success, ``None`` on any failure."""
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None
