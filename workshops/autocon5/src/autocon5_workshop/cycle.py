"""`nobs autocon5 cycle DEVICE PEER` — observe a peer's full Part-3 cycle.

Renders four panels in one shot for the given (device, peer):

  1. Alert state in Alertmanager (firing / suppressed, silencedBy)
  2. Silences scoped to this peer (active + recent)
  3. Recent Prefect flow runs (workflow activity for this peer)
  4. Most recent decision in Loki (the audit-record bookend)

With `--trigger`, posts an alert payload straight to the Prefect webhook,
waits up to 30s for a fresh flow run to appear, then re-renders the panels.
This bypasses Alertmanager's `repeat_interval` — handy in the workshop
when you want to re-observe a step without waiting 30 minutes.
"""

from __future__ import annotations

import datetime as dt
import json
import time
from typing import Annotated, Any

import requests
import typer
from nobs._console import console, fail, note, ok
from nobs.clients import AlertmanagerClient, LokiClient
from rich.panel import Panel
from rich.table import Table


def cycle(
    device: Annotated[str, typer.Argument(help="Device name (e.g. srl1).")],
    peer: Annotated[str, typer.Argument(help="Peer IP (e.g. 10.1.99.2).")],
    trigger: Annotated[
        bool,
        typer.Option("--trigger", help="Post a fresh alert payload through the webhook before rendering."),
    ] = False,
    status: Annotated[
        str,
        typer.Option(
            "--status",
            help="Alert status to post with --trigger: 'firing' (default) or 'resolved'.",
        ),
    ] = "firing",
    minutes: Annotated[int, typer.Option("--minutes", help="Lookback window for recent panels.")] = 30,
    am_url: Annotated[str, typer.Option(envvar="ALERTMANAGER_URL")] = "http://localhost:9093",
    loki_url: Annotated[str, typer.Option(envvar="LOKI_URL")] = "http://localhost:3001",
    prefect_url: Annotated[str, typer.Option(envvar="PREFECT_API_URL")] = "http://localhost:4200",
    webhook_url: Annotated[str, typer.Option(envvar="WEBHOOK_URL")] = "http://localhost:9997/v1/api/webhook",
) -> None:
    """Capture the workflow's full cycle state for one (device, peer); optionally re-drive it."""
    am = AlertmanagerClient(am_url)
    loki = LokiClient(loki_url)

    if trigger:
        if status not in {"firing", "resolved"}:
            fail(f"--status must be 'firing' or 'resolved' (got {status!r}).")
            raise typer.Exit(code=1)
        baseline = _latest_flow_run_time(prefect_url, device, peer)
        _post_alert(webhook_url, status, device, peer)
        note(f"posted {status} payload for {device} → {peer}; waiting for new flow run …")
        new_run_time = _wait_for_new_flow_run(prefect_url, device, peer, baseline, timeout=30)
        if new_run_time:
            ok(f"new flow run started at {new_run_time}")
        else:
            note("no new flow run appeared within 30s; rendering current state anyway.")
        time.sleep(2)

    _render_alert_panel(am, device, peer)
    _render_silences_panel(am, device, peer)
    _render_flow_runs_panel(prefect_url, device, peer, minutes)
    _render_decision_panel(loki, device, peer, minutes)

    if not trigger:
        console.print()
        console.print("  [dim]To drive a fresh cycle (bypassing Alertmanager's repeat_interval):[/]")
        console.print(f"    [bold]nobs autocon5 cycle {device} {peer} --trigger[/]")


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def _render_alert_panel(am: AlertmanagerClient, device: str, peer: str) -> None:
    try:
        alerts = [
            a
            for a in am.alerts()
            if a.get("labels", {}).get("device") == device
            and a.get("labels", {}).get("peer_address") == peer
            and a.get("labels", {}).get("alertname") == "BgpSessionNotUp"
        ]
    except Exception as e:  # noqa: BLE001
        console.print(Panel.fit(f"[red]Alertmanager query failed: {e}[/]", title="Alert", border_style="red"))
        return

    console.print()
    if not alerts:
        console.print(
            Panel.fit(
                f"[dim]No BgpSessionNotUp alert active for {device} → {peer}.[/]",
                title="Alert",
                border_style="dim",
            )
        )
        return

    # Alertmanager's API uses different state names than its UI / `nobs autocon5
    # alerts`. Translate so the workshop has one consistent vocabulary.
    _STATE_MAP = {"active": "firing", "suppressed": "suppressed", "unprocessed": "pending"}

    lines = []
    for a in alerts:
        labels = a.get("labels", {})
        status = a.get("status", {})
        raw_state = status.get("state", "?")
        state = _STATE_MAP.get(raw_state, raw_state)
        silenced = status.get("silencedBy") or []
        started = a.get("startsAt", "")
        age = _duration_since(started)
        line = f"BgpSessionNotUp · {labels.get('severity', '?')} · state={state} · age {age}"
        if silenced:
            sid = silenced[0]
            short = sid[:12] + "…"
            link = f"[link={am.base_url}/#/silences/{sid}]{short}[/link]"
            line += (
                f"\nsilencedBy: {link} (+{len(silenced) - 1} more)" if len(silenced) > 1 else f"\nsilencedBy: {link}"
            )
        else:
            line += "\nsilencedBy: [dim](none)[/]"
        lines.append(line)
    console.print(Panel.fit("\n".join(lines), title="Alert", border_style="cyan"))


def _render_silences_panel(am: AlertmanagerClient, device: str, peer: str) -> None:
    try:
        sils = am.silences()
    except Exception as e:  # noqa: BLE001
        console.print(Panel.fit(f"[red]silences query failed: {e}[/]", title="Silences", border_style="red"))
        return

    now = dt.datetime.now(dt.UTC)
    matching: list[dict] = []
    for s in sils:
        m = {x["name"]: x["value"] for x in s.get("matchers", [])}
        if m.get("device") == device and m.get("peer_address") == peer:
            matching.append(s)

    matching.sort(key=lambda s: s.get("startsAt", ""), reverse=True)
    matching = matching[:5]

    console.print()
    if not matching:
        console.print(
            Panel.fit(
                f"[dim]No silences scoped to {device} → {peer}.[/]",
                title="Silences (this peer)",
                border_style="dim",
            )
        )
        return

    table = Table(title="Silences (this peer)", show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("State")
    table.add_column("Starts")
    table.add_column("Ends")
    table.add_column("Remaining")
    for s in matching:
        state = s.get("status", {}).get("state", "?")
        try:
            ends = dt.datetime.fromisoformat(s["endsAt"].replace("Z", "+00:00"))
            rem_s = (ends - now).total_seconds()
            remaining = f"{int(rem_s // 60)}m{int(rem_s % 60)}s" if rem_s > 0 else "—"
        except Exception:
            remaining = "?"
        state_style = {"active": "bold green", "pending": "yellow", "expired": "dim"}.get(state, "")
        full_id = s.get("id", "")
        short_id = full_id[:12] + "…" if full_id else "?"
        id_cell = f"[link={am.base_url}/#/silences/{full_id}]{short_id}[/link]" if full_id else short_id
        table.add_row(
            id_cell,
            f"[{state_style}]{state}[/]" if state_style else state,
            s.get("startsAt", "")[11:19],
            s.get("endsAt", "")[11:19],
            remaining,
        )
    console.print(table)


def _render_flow_runs_panel(prefect_url: str, device: str, peer: str, minutes: int) -> None:
    try:
        runs = _flow_runs(prefect_url, device, peer, minutes)
    except Exception as e:  # noqa: BLE001
        console.print(Panel.fit(f"[red]Prefect query failed: {e}[/]", title="Prefect flow runs", border_style="red"))
        return

    console.print()
    if not runs:
        console.print(
            Panel.fit(
                f"[dim]No quarantine_bgp / resolved_bgp runs for {device}:{peer} in the last {minutes}m.[/]",
                title=f"Prefect flow runs (last {minutes}m)",
                border_style="dim",
            )
        )
        return

    table = Table(title=f"Prefect flow runs (last {minutes}m)", show_header=True, header_style="bold")
    table.add_column("Started")
    table.add_column("State")
    table.add_column("Flow")
    for r in runs[:5]:
        state = r.get("state", {}).get("type", "?")
        state_style = {"COMPLETED": "green", "FAILED": "red", "RUNNING": "yellow"}.get(state, "")
        run_id = r.get("id", "")
        started_cell = r.get("start_time", "")[11:19]
        if run_id:
            started_cell = f"[link={prefect_url}/runs/flow-run/{run_id}]{started_cell}[/link]"
        table.add_row(
            started_cell,
            f"[{state_style}]{state}[/]" if state_style else state,
            r.get("name", "?"),
        )
    console.print(table)


def _render_decision_panel(loki: LokiClient, device: str, peer: str, minutes: int) -> None:
    # The `decision=~".+"` matcher keeps annotate_action records (which carry no
    # `decision` label) out of the result, so we land on the actual decision.
    query = (
        f'{{source="prefect", workflow="autocon5_quarantine_bgp", '
        f'device="{device}", peer_address="{peer}", decision=~".+"}} | json'
    )
    try:
        lines = loki.query_range(query, minutes=minutes, limit=1)
    except Exception as e:  # noqa: BLE001
        console.print(Panel.fit(f"[red]Loki query failed: {e}[/]", title="Decision", border_style="red"))
        return

    console.print()
    if not lines:
        console.print(
            Panel.fit(
                f"[dim]No decision audit records for {device} → {peer} in the last {minutes}m.[/]",
                title="Most recent decision",
                border_style="dim",
            )
        )
        return

    try:
        body = json.loads(lines[0])
    except json.JSONDecodeError:
        console.print(
            Panel.fit("[red]Could not parse latest decision JSON.[/]", title="Most recent decision", border_style="red")
        )
        return

    ts = body.get("timestamp", "")[11:19]
    message = body.get("message", "")
    labels = body.get("labels", {}) or {}
    decision = labels.get("decision", "?")
    color = {"proceed": "green", "skip": "yellow", "resolved": "blue"}.get(decision, "")
    decision_pretty = f"[{color}]{decision}[/]" if color else decision
    console.print(
        Panel.fit(
            f"{ts}  decision={decision_pretty}\nreason: {message}",
            title="Most recent decision",
            border_style="cyan",
        )
    )


# ---------------------------------------------------------------------------
# Prefect helpers
# ---------------------------------------------------------------------------


def _flow_runs(prefect_url: str, device: str, peer: str, minutes: int) -> list[dict]:
    # Prefect attaches `with tags(...)` to task runs, not flow runs — so the
    # flow_runs tag filter never matches. Fetch a broader window and filter
    # client-side on the `device` / `peer_address` flow-run parameters instead.
    body = {"sort": "START_TIME_DESC", "limit": 100}
    r = requests.post(f"{prefect_url}/api/flow_runs/filter", json=body, timeout=10)
    r.raise_for_status()
    runs = r.json()
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=minutes)
    out: list[dict] = []
    for run in runs:
        params = run.get("parameters") or {}
        if params.get("device") != device or params.get("peer_address") != peer:
            continue
        st = run.get("start_time")
        if not st:
            continue
        try:
            start = dt.datetime.fromisoformat(st.replace("Z", "+00:00"))
        except Exception:
            continue
        if start >= cutoff:
            out.append(run)
    return out


def _latest_flow_run_time(prefect_url: str, device: str, peer: str) -> str:
    try:
        runs = _flow_runs(prefect_url, device, peer, minutes=120)
        return runs[0].get("start_time", "") if runs else ""
    except Exception:
        return ""


def _wait_for_new_flow_run(prefect_url: str, device: str, peer: str, baseline: str, timeout: int = 30) -> str | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            runs = _flow_runs(prefect_url, device, peer, minutes=120)
            for r in runs:
                st = r.get("start_time", "")
                if st and st > baseline:
                    return st[11:19]
        except Exception:
            pass
        time.sleep(2)
    return None


# ---------------------------------------------------------------------------
# Webhook poster — mirrors workshops/autocon5/src/autocon5_workshop/try_it.py
# ---------------------------------------------------------------------------


def _post_alert(webhook_url: str, status: str, device: str, peer: str) -> None:
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload: dict[str, Any] = {
        "version": "4",
        "groupKey": f"cycle-{device}-{peer}",
        "truncatedAlerts": 0,
        "status": status,
        "receiver": "webhook-receiver",
        "groupLabels": {"alertname": "BgpSessionNotUp", "device": device, "peer_address": peer},
        "commonLabels": {"alertname": "BgpSessionNotUp"},
        "commonAnnotations": {},
        "externalURL": "http://localhost:9093",
        "alerts": [
            {
                "status": status,
                "labels": {
                    "alertname": "BgpSessionNotUp",
                    "device": device,
                    "peer_address": peer,
                    "afi_safi_name": "ipv4-unicast",
                    "name": "default",
                },
                "annotations": {},
                "startsAt": now,
                "endsAt": now if status == "resolved" else "0001-01-01T00:00:00Z",
                "generatorURL": "",
                "fingerprint": f"cycle-{device}-{peer}",
            }
        ],
    }
    try:
        requests.post(webhook_url, json=payload, timeout=15).raise_for_status()
    except requests.RequestException as e:
        fail(f"could not POST to webhook: {e}")
        raise typer.Exit(code=1) from e


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------


def _duration_since(iso_ts: str) -> str:
    try:
        ts = dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        secs = int((dt.datetime.now(dt.UTC) - ts).total_seconds())
        if secs < 60:
            return f"{secs}s"
        m, s = divmod(secs, 60)
        if m < 60:
            return f"{m}m{s}s"
        h, m = divmod(m, 60)
        return f"{h}h{m}m"
    except Exception:
        return "?"
