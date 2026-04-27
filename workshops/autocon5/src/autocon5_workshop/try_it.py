"""`nobs autocon5 try-it` - guided tour through the four canonical Part 3 paths.

Python rewrite of the original `scripts/try-it.sh`, with Rich panels +
progress so each step is a clearer story for the audience.
"""
from __future__ import annotations

import datetime as dt
import sys
import time
from typing import Annotated

import requests
import typer
from nobs._console import console, fail, note, ok, warn
from nobs.clients import LokiClient
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)


def try_it(
    auto: Annotated[bool, typer.Option("--auto", help="Skip the between-step prompts (CI mode).")] = False,
    prom_url: Annotated[str, typer.Option(envvar="PROMETHEUS_URL")] = "http://localhost:9090",
    loki_url: Annotated[str, typer.Option(envvar="LOKI_URL")] = "http://localhost:3001",
    am_url: Annotated[str, typer.Option(envvar="ALERTMANAGER_URL")] = "http://localhost:9093",
    infrahub_url: Annotated[str, typer.Option(envvar="INFRAHUB_ADDRESS")] = "http://localhost:8000",
    webhook_url: Annotated[str, typer.Option(envvar="WEBHOOK_URL")] = "http://localhost:9997/v1/api/webhook",
    token: Annotated[str, typer.Option(envvar="INFRAHUB_API_TOKEN")] = "",
) -> None:
    """Walk the four canonical paths (quarantine / maintenance-skip / healthy-skip / resolved)
    one at a time, polling Loki for the Prefect annotation that proves the chain ran."""
    if not token:
        fail("INFRAHUB_API_TOKEN is required.")
        raise typer.Exit(code=1)

    _preflight(prom_url, loki_url, am_url, infrahub_url)
    _pause(auto)

    loki = LokiClient(loki_url)

    # Path 1 - quarantine for the broken peer
    _header(
        "Path 1 - Actionable / mismatch → quarantine",
        "The lab ships srl1→10.1.99.2 and srl2→10.1.11.1 as intentionally broken.\n"
        "BgpSessionNotUp should already be firing; we wait for the Prefect annotation.",
    )
    _wait_for_loki(
        loki,
        '{source="prefect", workflow="autocon5_quarantine_bgp", decision="proceed"}',
        "quarantine flow ran and decided 'proceed'",
        timeout=120,
    )
    _pause(auto)

    # Path 2 - maintenance-skip
    _header(
        "Path 2 - In-maintenance → skip",
        "Mark srl1 as in maintenance, replay an alert, expect decision='skip'.",
    )
    _set_maintenance("srl1", True, infrahub_url, token)
    _post_alert(webhook_url, "firing", "srl1", "10.1.99.2", "try-it-2")
    _wait_for_loki(
        loki,
        '{source="prefect", workflow="autocon5_quarantine_bgp", device="srl1", decision="skip"}',
        "quarantine flow saw maintenance=true and skipped",
        timeout=60,
    )
    note("Clearing srl1 maintenance back to false.")
    _set_maintenance("srl1", False, infrahub_url, token)
    _pause(auto)

    # Path 3 - healthy-skip
    _header(
        "Path 3 - Healthy peer → skip",
        "Replay an alert payload for srl1→10.1.2.2 (a healthy peer). Decision should be 'skip'.",
    )
    _post_alert(webhook_url, "firing", "srl1", "10.1.2.2", "try-it-3")
    _wait_for_loki(
        loki,
        '{source="prefect", workflow="autocon5_quarantine_bgp", device="srl1", peer_address="10.1.2.2", decision="skip"}',
        "quarantine flow decided 'skip' for healthy peer",
        timeout=60,
    )
    _pause(auto)

    # Path 4 - resolved → audit
    _header(
        "Path 4 - Resolved → audit",
        "Replay a 'resolved' payload. The resolved_bgp_flow should annotate decision='resolved'.",
    )
    _post_alert(webhook_url, "resolved", "srl1", "10.1.99.2", "try-it-4")
    _wait_for_loki(
        loki,
        '{source="prefect", workflow="autocon5_quarantine_bgp", device="srl1", decision="resolved"}',
        "resolved_bgp_flow ran and annotated 'resolved'",
        timeout=60,
    )

    console.print()
    console.print(
        Panel.fit(
            "[ok]All four canonical paths exercised.[/]\n"
            "Open Grafana → Explore → Loki and run:\n"
            '  [kbd]{workflow="autocon5_quarantine_bgp"}[/]\n'
            "to see the audit trail.",
            title="Done",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------


def _header(title: str, body: str) -> None:
    console.print()
    console.print(Panel(body, title=title, border_style="cyan"))


def _pause(auto: bool) -> None:
    if auto:
        time.sleep(2)
        return
    try:
        input("\n  [Enter to continue, Ctrl-C to bail] ")
    except (EOFError, KeyboardInterrupt):
        sys.exit(1)


def _preflight(prom_url: str, loki_url: str, am_url: str, infrahub_url: str) -> None:
    targets = [
        ("Prometheus", f"{prom_url.rstrip('/')}/-/ready"),
        ("Loki",       f"{loki_url.rstrip('/')}/ready"),
        ("Alertmanager", f"{am_url.rstrip('/')}/-/ready"),
    ]
    console.print(Panel.fit("Checking the stack is reachable...", title="Pre-flight", border_style="cyan"))
    for name, url in targets:
        try:
            r = requests.get(url, timeout=3)
            # Loki's /ready returns 503 with body "Ingester not ready: waiting for
            # 15s after being ready" during a self-imposed warm-up - the service
            # is fully functional. Treat that specific body as ready.
            if r.ok or (name == "Loki" and r.status_code == 503 and "Ingester not ready" in r.text):
                ok(f"{name} reachable")
                continue
        except requests.RequestException:
            pass
        fail(f"{name} NOT reachable at {url} - bring the stack up first (nobs autocon5 up)")
        raise typer.Exit(code=1)
    # Infrahub: try both common paths
    for path in ("/api/healthcheck", "/health"):
        try:
            r = requests.get(f"{infrahub_url.rstrip('/')}{path}", timeout=3)
            if r.ok:
                ok("Infrahub reachable")
                return
        except requests.RequestException:
            continue
    fail("Infrahub NOT reachable - bring the stack up first (nobs autocon5 up)")
    raise typer.Exit(code=1)


def _set_maintenance(device: str, state: bool, infrahub_url: str, token: str) -> None:
    try:
        from infrahub_sdk import Config, InfrahubClientSync
    except ImportError:
        fail("infrahub-sdk is not installed. Run `nobs setup` first.")
        sys.exit(1)
    client = InfrahubClientSync(address=infrahub_url, config=Config(api_token=token))
    matches = client.filters(kind="WorkshopDevice", name__value=device)
    if not matches:
        warn(f"could not find {device} in Infrahub (maintenance toggle skipped)")
        return
    node = matches[0]
    node.maintenance.value = state
    node.save()
    ok(f"{device}.maintenance = {state}")


def _post_alert(webhook_url: str, status: str, device: str, peer: str, fingerprint: str) -> None:
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload = {
        "version": "4", "groupKey": f"try-it-{fingerprint}", "truncatedAlerts": 0,
        "status": status, "receiver": "webhook-receiver",
        "groupLabels": {"alertname": "BgpSessionNotUp", "device": device, "peer_address": peer},
        "commonLabels": {"alertname": "BgpSessionNotUp"},
        "commonAnnotations": {},
        "externalURL": "http://localhost:9093",
        "alerts": [{
            "status": status,
            "labels": {
                "alertname": "BgpSessionNotUp", "device": device, "peer_address": peer,
                "afi_safi_name": "ipv4-unicast", "name": "default",
            },
            "annotations": {},
            "startsAt": now, "endsAt": now if status == "resolved" else "0001-01-01T00:00:00Z",
            "generatorURL": "", "fingerprint": fingerprint,
        }],
    }
    try:
        requests.post(webhook_url, json=payload, timeout=5).raise_for_status()
        ok(f"replayed {status} payload for {device} → {peer}")
    except requests.RequestException as e:
        warn(f"could not POST to webhook ({e})")


def _wait_for_loki(client: LokiClient, query: str, label: str, timeout: int) -> None:
    poll = 5
    elapsed = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:
        task = progress.add_task(f"Waiting for: {label}", total=timeout)
        while elapsed < timeout:
            try:
                count = client.query_count(query, minutes=5)
            except Exception:
                count = 0
            if count > 0:
                progress.update(task, completed=timeout)
                ok(f"{label} (Loki match count={count})")
                return
            time.sleep(poll)
            elapsed += poll
            progress.update(task, completed=elapsed)
    fail(f"{label} - no Loki match after {timeout}s")
