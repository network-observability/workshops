"""`nobs autocon5 incident` — drive a sonda-native cascade scenario.

Field-tests sonda's `POST /scenarios` ergonomics with a v2 cascade
scenario assembled in memory. The first kind, `link-failover`, mirrors
sonda's canonical example: primary interface flap → backup link
saturates after primary drops below 1 → latency degrades after backup
exceeds 70%. All three signals are linked declaratively via `after:`
clauses, so sonda's compiler resolves the causal order and emits each
signal at the right phase offset.

Unlike `flap-interface` (which times the cascade in CLI code with
`time.sleep` between `/events` POSTs), this command hands the entire
cascade to sonda once and lets the server schedule emission.
"""

from __future__ import annotations

import contextlib
import json
import time
from typing import Annotated

import requests
import typer
from nobs._console import console, fail, ok
from rich.table import Table

_KIND_HELP = "Cascade story to run. `link-failover` mirrors sonda's canonical v2 example."


def incident(
    device: Annotated[
        str,
        typer.Option("--device", "-d", help="Lab device label applied to every signal."),
    ] = "srl1",
    primary_interface: Annotated[
        str,
        typer.Option(
            "--primary-interface",
            help="Interface that flaps in Phase 1 (link goes intermittent).",
        ),
    ] = "ethernet-1/10",
    backup_interface: Annotated[
        str,
        typer.Option(
            "--backup-interface",
            help="Interface that absorbs the failover in Phase 2 (utilisation rises).",
        ),
    ] = "ethernet-1/1",
    kind: Annotated[
        str,
        typer.Option("--kind", "-k", help=_KIND_HELP),
    ] = "link-failover",
    duration: Annotated[
        str,
        typer.Option(
            "--duration",
            help="Scenario duration in sonda's format (e.g. `2m`, `5m`, `30s`).",
        ),
    ] = "3m",
    sonda_url: Annotated[
        str,
        typer.Option(
            "--sonda-url",
            envvar="SONDA_SERVER_URL",
            help="Base sonda-server URL.",
        ),
    ] = "http://localhost:8085",
    prom_url: Annotated[
        str,
        typer.Option(
            "--prom-url",
            envvar="SONDA_PROM_REMOTE_WRITE_URL",
            help="Prometheus remote_write URL passed as the metric sink.",
        ),
    ] = "http://prometheus:9090/api/v1/write",
    api_key: Annotated[
        str,
        typer.Option(
            "--sonda-api-key",
            envvar="SONDA_API_KEY",
            help="Bearer token if sonda-server has SONDA_API_KEY set; empty otherwise.",
        ),
    ] = "",
    follow: Annotated[
        bool,
        typer.Option(
            "--follow/--no-follow",
            help="Poll the running scenario(s) until completion. `--no-follow` returns immediately after registration.",
        ),
    ] = False,
) -> None:
    """Register a sonda-native cascade scenario via `POST /scenarios`."""
    if kind != "link-failover":
        fail(f"unknown kind {kind!r}; supported: link-failover")
        raise typer.Exit(code=1)

    body = _build_link_failover(
        device=device,
        primary=primary_interface,
        backup=backup_interface,
        duration=duration,
        prom_url=prom_url,
    )

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    scenarios_url = f"{sonda_url.rstrip('/')}/scenarios"
    console.print(
        f"Posting [label]{kind}[/] cascade for [label]{device}[/] "
        f"({primary_interface} → {backup_interface}, duration {duration}) "
        f"to [muted]{scenarios_url}[/]"
    )

    try:
        response = requests.post(scenarios_url, json=body, headers=headers, timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = ""
        if exc.response is not None:
            with contextlib.suppress(Exception):
                detail = f" — {exc.response.text}"
        fail(f"POST /scenarios failed: {exc}{detail}")
        raise typer.Exit(code=1) from exc

    payload = response.json()
    created = _flatten_created(payload)
    if not created:
        fail(f"unexpected response shape: {json.dumps(payload)[:300]}")
        raise typer.Exit(code=1)

    table = Table(show_header=True, header_style="bold")
    table.add_column("id")
    table.add_column("name")
    table.add_column("status")
    for item in created:
        table.add_row(item.get("id", ""), item.get("name", ""), item.get("status", ""))
    console.print(table)

    for w in payload.get("warnings", []) or []:
        console.print(f"  [yellow]warning:[/] {w}")

    if not follow:
        ids = ", ".join(item["id"] for item in created)
        ok(f"registered {len(created)} scenario(s): {ids}")
        console.print(
            "  Inspect:  [muted]curl {url}/scenarios[/]\n"
            "  Stop:     [muted]curl -X DELETE {url}/scenarios/<id>[/]".format(
                url=sonda_url.rstrip("/")
            )
        )
        return

    _follow_until_done(sonda_url, [item["id"] for item in created], headers)
    ok("all scenarios completed")


def _build_link_failover(
    *,
    device: str,
    primary: str,
    backup: str,
    duration: str,
    prom_url: str,
) -> dict:
    """v2 scenario body — three signals linked by `after:` clauses."""
    return {
        "version": 2,
        "scenario_name": f"incident-link-failover-{device}",
        "category": "network",
        "description": f"Link failover cascade on {device} ({primary} → {backup})",
        "defaults": {
            "rate": 1,
            "duration": duration,
            "encoder": {"type": "remote_write"},
            "sink": {"type": "remote_write", "url": prom_url},
            "labels": {
                "device": device,
                "pipeline": "direct",
                "collection_type": "gnmi",
                "intf_role": "peer",
                "source": "incident-cascade",
            },
        },
        "scenarios": [
            {
                "id": "primary_flap",
                "signal_type": "metrics",
                "name": "interface_oper_state",
                "generator": {
                    "type": "flap",
                    "up_duration": "60s",
                    "down_duration": "30s",
                },
                "labels": {"name": primary},
            },
            {
                "id": "backup_saturation",
                "signal_type": "metrics",
                "name": "incident_backup_link_utilization",
                "generator": {
                    "type": "saturation",
                    "baseline": 20,
                    "ceiling": 85,
                    "time_to_saturate": "2m",
                },
                "labels": {"name": backup, "path": "backup"},
                "after": {"ref": "primary_flap", "op": "<", "value": 1},
            },
            {
                "id": "latency_degrade",
                "signal_type": "metrics",
                "name": "incident_latency_ms",
                "generator": {
                    "type": "degradation",
                    "baseline": 5,
                    "ceiling": 150,
                    "time_to_degrade": "3m",
                },
                "labels": {"name": backup, "path": "backup"},
                "after": {"ref": "backup_saturation", "op": ">", "value": 70},
            },
        ],
    }


def _flatten_created(payload: dict) -> list[dict]:
    """Normalise the single vs multi-scenario response shapes."""
    if isinstance(payload.get("scenarios"), list):
        return list(payload["scenarios"])
    if "id" in payload:
        return [payload]
    return []


def _follow_until_done(sonda_url: str, ids: list[str], headers: dict[str, str]) -> None:
    """Poll each scenario until it exits the running state."""
    base = sonda_url.rstrip("/")
    pending = set(ids)
    while pending:
        time.sleep(5)
        for sid in list(pending):
            try:
                r = requests.get(f"{base}/scenarios/{sid}", headers=headers, timeout=5)
                r.raise_for_status()
            except requests.RequestException as exc:
                console.print(f"  [yellow]poll error on {sid}: {exc}[/]")
                continue
            doc = r.json()
            status = doc.get("status", "unknown")
            console.print(f"  {sid[:8]} status={status}")
            if status not in ("running", "starting"):
                pending.discard(sid)
