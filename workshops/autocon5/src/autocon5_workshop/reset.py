"""`nobs autocon5 reset` — return the lab to known-good state between runs.

The workshop story arc relies on every part starting from the same baseline:
both deliberately broken peers firing, no devices flagged in maintenance,
no workshop-driven cascades or silences left over from a previous run, and
sonda's `loki` sink actively delivering srl1 logs.

This command idempotently brings the lab back to that baseline. Safe to run
at the start of every workshop session — and at the start of every part —
without unwanted side effects on healthy state.
"""

from __future__ import annotations

import time
from typing import Annotated

import requests
import typer
from nobs._console import console, note, ok, warn

_WORKSHOP_DEVICES = ("srl1", "srl2")
_CASCADE_NAMES = (
    "incident_backup_link_utilization",
    "incident_latency_ms",
    "interface_oper_state",
)
_WORKSHOP_SILENCE_HINTS = ("Workshop", "workshop", "autocon")


def reset(
    alertmanager_url: Annotated[
        str,
        typer.Option(
            "--alertmanager-url",
            envvar="ALERTMANAGER_URL",
            help="Alertmanager base URL (used to expire workshop silences).",
        ),
    ] = "http://localhost:9093",
    sonda_url: Annotated[
        str,
        typer.Option(
            "--sonda-url",
            envvar="SONDA_SERVER_URL",
            help="Sonda-server base URL (used to delete cascade scenarios).",
        ),
    ] = "http://localhost:8085",
    loki_url: Annotated[
        str,
        typer.Option(
            "--loki-url",
            envvar="LOKI_URL",
            help="Loki base URL (used to detect a wedged sonda-logs sink).",
        ),
    ] = "http://localhost:3001",
    skip_sonda_logs: Annotated[
        bool,
        typer.Option(
            "--skip-sonda-logs",
            help="Don't restart sonda-logs even if the loki sink looks wedged.",
        ),
    ] = False,
) -> None:
    """Return the lab to the workshop's known-good baseline."""
    note("Resetting lab to known-good state.")

    _clear_maintenance_flags()
    _expire_workshop_silences(alertmanager_url)
    _delete_cascade_scenarios(sonda_url)
    if not skip_sonda_logs:
        _restart_sonda_logs_if_wedged(loki_url)

    ok("lab reset complete — both broken peers should be firing within ~30s")


def _clear_maintenance_flags() -> None:
    import subprocess

    cleared: list[str] = []
    for device in _WORKSHOP_DEVICES:
        try:
            r = subprocess.run(
                ["uv", "run", "nobs", "autocon5", "maintenance", "--device", device, "--clear"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=_repo_root(),
            )
            if r.returncode == 0:
                cleared.append(device)
            else:
                warn(
                    f"maintenance --clear failed for {device}: {r.stderr.splitlines()[-1] if r.stderr else 'unknown error'}"
                )
        except subprocess.TimeoutExpired:
            warn(f"maintenance --clear timed out for {device}")
    if cleared:
        console.print(f"  cleared maintenance on: {', '.join(cleared)}")


def _expire_workshop_silences(alertmanager_url: str) -> None:
    base = alertmanager_url.rstrip("/")
    try:
        response = requests.get(f"{base}/api/v2/silences", timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        warn(f"Alertmanager fetch failed: {exc} — skipping silence cleanup")
        return

    expired = 0
    for silence in response.json():
        if silence.get("status", {}).get("state") != "active":
            continue
        comment = silence.get("comment", "")
        created_by = silence.get("createdBy", "")
        if not any(hint in comment or hint in created_by for hint in _WORKSHOP_SILENCE_HINTS):
            continue
        sid = silence.get("id")
        if not sid:
            continue
        try:
            r = requests.delete(f"{base}/api/v2/silence/{sid}", timeout=5)
            if r.status_code == 200:
                expired += 1
        except requests.RequestException:
            pass

    if expired:
        console.print(f"  expired {expired} workshop-related Alertmanager silence(s)")


def _delete_cascade_scenarios(sonda_url: str) -> None:
    base = sonda_url.rstrip("/")
    try:
        response = requests.get(f"{base}/scenarios", timeout=5)
        response.raise_for_status()
    except requests.RequestException as exc:
        warn(f"Sonda /scenarios fetch failed: {exc} — skipping cascade cleanup")
        return

    deleted = 0
    payload = response.json()
    scenarios = payload.get("scenarios", []) if isinstance(payload, dict) else []
    for scenario in scenarios:
        name = scenario.get("name", "")
        if name not in _CASCADE_NAMES:
            continue
        sid = scenario.get("id")
        if not sid:
            continue
        try:
            r = requests.delete(f"{base}/scenarios/{sid}", timeout=5)
            if r.status_code == 200:
                deleted += 1
        except requests.RequestException:
            pass

    if deleted:
        console.print(f"  deleted {deleted} lingering cascade scenario(s)")


def _restart_sonda_logs_if_wedged(loki_url: str) -> None:
    """Detect the silent-sink wedge from sonda-logs' loki path and restart if needed.

    The wedge is specific to sonda's `loki` sink — the `srl1_*` log scenarios
    stop delivering events while sonda-logs' UDP path (srl2 → Vector) keeps
    working. Detect by querying Loki for any srl1 log activity in the last
    minute that ISN'T a Prefect annotation.
    """
    base = loki_url.rstrip("/")
    end = int(time.time())
    start = end - 60
    query = '{device="srl1", source!="prefect"}'
    try:
        response = requests.get(
            f"{base}/loki/api/v1/query_range",
            params={
                "query": query,
                "start": f"{start}000000000",
                "end": f"{end}000000000",
                "limit": 1,
            },
            timeout=5,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        warn(f"Loki probe failed: {exc} — skipping sonda-logs check")
        return

    streams = response.json().get("data", {}).get("result", []) or []
    if streams:
        return

    note("sonda-logs srl1 streams look wedged (no Loki activity in last 60s); restarting")
    import subprocess

    try:
        r = subprocess.run(
            ["docker", "compose", "--project-name", "autocon5", "restart", "sonda-logs"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=_repo_root() / "workshops" / "autocon5",
        )
        if r.returncode == 0:
            console.print("  restarted sonda-logs (loki sink reset)")
        else:
            warn(
                f"sonda-logs restart failed: {r.stderr.splitlines()[-1] if r.stderr else 'unknown error'}"
            )
    except subprocess.TimeoutExpired:
        warn("sonda-logs restart timed out")


def _repo_root():
    from pathlib import Path

    # __file__ = .../workshops/autocon5/src/autocon5_workshop/reset.py
    return Path(__file__).resolve().parents[4]
