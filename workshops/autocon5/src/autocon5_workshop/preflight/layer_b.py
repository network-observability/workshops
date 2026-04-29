"""Layer B — per-panel shape validation via Grafana's /api/ds/query.

Iterates every panel in every dashboard JSON, runs the targets through
Grafana's frontend-equivalent endpoint with $device substituted to both
srl1 and srl2. Validates frame + row count.

All datasources used by the workshop (prometheus, loki, infinity) are
backend plugins, so /api/ds/query is the truthful test for every panel.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

WORKSHOP_DIR = Path(os.environ.get("PREFLIGHT_WORKSHOP_DIR",
                                   Path(__file__).resolve().parents[3]))
OUT_DIR = Path(os.environ.get("PREFLIGHT_OUT_DIR", "/tmp/preflight-out"))

GRAFANA = os.environ.get("GRAFANA_URL", "http://localhost:3000")
GRAFANA_AUTH = (os.environ.get("GRAFANA_USER", "admin"),
                os.environ.get("GRAFANA_PASSWORD", "admin"))

DEVICES = ["srl1", "srl2"]
WINDOW_SECONDS = 5 * 60


def render_template(s: str, device: str) -> str:
    return s.replace("$device", device).replace("${device}", device)


def render_target(target: dict[str, Any], device: str) -> dict[str, Any]:
    """Substitute $device recursively into all string values, including nested
    dicts (e.g. Infinity's `url_options.body_graphql_query`)."""

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            return render_template(v, device)
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x) for x in v]
        return v

    return walk(target)


def grafana_ds_query(target: dict[str, Any]) -> dict[str, Any]:
    end = int(time.time() * 1000)
    start = end - WINDOW_SECONDS * 1000
    body = {
        "queries": [{**target, "refId": target.get("refId", "A"),
                     "intervalMs": 30_000, "maxDataPoints": 600}],
        "from": str(start), "to": str(end),
    }
    r = requests.post(f"{GRAFANA}/api/ds/query", json=body, auth=GRAFANA_AUTH, timeout=15)
    return {"status": r.status_code,
            "json": r.json() if r.headers.get("content-type", "").startswith("application/json")
            else {"_text": r.text[:300]}}


def collect_panels(dashboard_path: Path) -> tuple[str, list[dict[str, Any]]]:
    d = json.loads(dashboard_path.read_text())
    panels: list[dict[str, Any]] = []

    def walk(ps):
        for p in ps:
            if p.get("type") == "row":
                walk(p.get("panels", []) or [])
            else:
                panels.append(p)

    walk(d.get("panels", []) or [])
    return d.get("title", dashboard_path.stem), panels


def shape_check(response: dict[str, Any]) -> tuple[bool, str]:
    if response.get("status") != 200:
        return False, f"http {response.get('status')}"
    j = response.get("json", {})
    results = j.get("results", {})
    if not results:
        return False, "no results"
    res = next(iter(results.values()))
    if res.get("status", 200) >= 400 or res.get("error"):
        return False, f"ds error: {res.get('error') or res.get('status')}"
    frames = res.get("frames", []) or []
    if not frames:
        return False, "0 frames"
    series = sum(1 for f in frames if (f.get("data", {}).get("values", [])))
    rows = sum(len(f.get("data", {}).get("values", [[]])[0]) for f in frames if f.get("data", {}).get("values"))
    if rows == 0:
        return False, f"{series} frames, 0 rows"
    return True, f"{series} frames, {rows} rows"


def datasource_type(panel: dict[str, Any], target: dict[str, Any]) -> str:
    ds = target.get("datasource") or panel.get("datasource") or {}
    if isinstance(ds, str):
        return ds.lower()
    return (ds.get("type") or "").lower()


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dashboards_dir = WORKSHOP_DIR / "grafana/dashboards"
    out = OUT_DIR / "layer_b.json"

    report: list[dict[str, Any]] = []
    pass_count = fail_count = skip_count = 0

    for dashboard_path in sorted(dashboards_dir.glob("*.json")):
        title, panels = collect_panels(dashboard_path)
        print(f"\n=== {title} ({dashboard_path.name}) — {len(panels)} panels ===", flush=True)
        dashboard_results: list[dict[str, Any]] = []

        for panel in panels:
            panel_id = panel.get("id")
            panel_title = panel.get("title", "") or ""
            panel_type = panel.get("type", "")
            targets = panel.get("targets", []) or []
            uses_template = "$device" in json.dumps(targets)
            devices = DEVICES if uses_template else ["(no template)"]

            for device in devices:
                target_results = []
                for tgt in targets:
                    rendered = render_target(tgt, device if device != "(no template)" else "srl1")
                    ds_type = datasource_type(panel, rendered)
                    try:
                        resp = grafana_ds_query(rendered)
                        ok, summary = shape_check(resp)
                    except Exception as e:  # noqa: BLE001
                        ok, summary = False, f"{type(e).__name__}: {e}"
                    target_results.append({
                        "ok": ok, "ds": ds_type, "summary": summary,
                        "expr": (rendered.get("expr") or rendered.get("queryText") or "")[:200],
                    })

                if not target_results:
                    status = "SKIP"
                    skip_count += 1
                elif any(r["ok"] for r in target_results):
                    status = "PASS"
                    pass_count += 1
                else:
                    status = "FAIL"
                    fail_count += 1

                marker = {"PASS": "OK  ", "FAIL": "FAIL", "SKIP": "SKIP"}[status]
                summary_str = "; ".join(f"{r['ds']}:{r['summary']}" for r in target_results) or "no targets"
                print(f"  [{marker}] panel #{panel_id} {panel_type:14s} "
                      f"device={device:12s} {panel_title[:38]!r:40s} → {summary_str[:140]}", flush=True)

                dashboard_results.append({
                    "panel_id": panel_id, "panel_title": panel_title, "panel_type": panel_type,
                    "device": device, "status": status, "summary": summary_str,
                    "targets": target_results,
                })

        report.append({"dashboard": title, "file": dashboard_path.name, "panels": dashboard_results})

    out.write_text(json.dumps(report, indent=2))
    print(f"\nLayer B summary: PASS={pass_count} FAIL={fail_count} SKIP={skip_count}")
    print(f"Layer B — wrote {out}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
