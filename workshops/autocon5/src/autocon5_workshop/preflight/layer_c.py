"""Layer C — per-panel visual validation via headless Chromium.

Captures one PNG per (dashboard, panel, device) tuple from Grafana's
`d-solo` view and inspects the rendered DOM for `No data`, plugin
errors, or stuck spinners. The truthful test for frontend-only Grafana
plugins (fifemon-graphql) where Layer B's path doesn't apply.

Playwright is imported lazily inside `main()` so `--skip-c` works
without the dev dep installed.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.sync_api import Page

WORKSHOP_DIR = Path(os.environ.get("PREFLIGHT_WORKSHOP_DIR",
                                   Path(__file__).resolve().parents[3]))
OUT_DIR = Path(os.environ.get("PREFLIGHT_OUT_DIR", "/tmp/preflight-out"))

# 127.0.0.1 instead of localhost: some macOS + Docker setups break Chromium's
# loopback resolution. The HTTP server on the host is reachable via 127.0.0.1.
GRAFANA = os.environ.get("GRAFANA_URL_LAYER_C",
                         os.environ.get("GRAFANA_URL", "http://localhost:3000")
                         .replace("localhost", "127.0.0.1"))
GRAFANA_USER = os.environ.get("GRAFANA_USER", "admin")
GRAFANA_PASSWORD = os.environ.get("GRAFANA_PASSWORD", "admin")

DEVICES = ["srl1", "srl2"]
WINDOW = "from=now-5m&to=now"
PANEL_VIEWPORT = {"width": 1280, "height": 480}
SETTLE_MS = 4000


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "panel"


def collect_panels(dashboard_path: Path) -> tuple[str | None, str, list[dict]]:
    d = json.loads(dashboard_path.read_text())
    panels: list[dict] = []

    def walk(ps):
        for p in ps:
            if p.get("type") == "row":
                walk(p.get("panels", []) or [])
            else:
                panels.append(p)

    walk(d.get("panels", []) or [])
    return d.get("uid"), d.get("title", dashboard_path.stem), panels


def login(ctx) -> None:
    r = ctx.request.post(
        f"{GRAFANA}/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"user": GRAFANA_USER, "password": GRAFANA_PASSWORD}),
        timeout=15_000,
    )
    if r.status >= 400:
        raise RuntimeError(f"login failed: {r.status} {r.text()[:200]}")


def resolve_uid(ctx, title: str) -> str:
    r = ctx.request.get(f"{GRAFANA}/api/search",
                        params={"query": title, "type": "dash-db"}, timeout=15_000)
    for it in r.json():
        if it.get("title") == title:
            return it["uid"]
    raise RuntimeError(f"could not resolve UID for {title!r}")


def inspect_panel(page: Page, screenshot_bytes: int) -> tuple[str, str]:
    if page.locator("text=No data").count() > 0:
        return "FAIL", "panel shows 'No data'"
    if page.locator("text=Datasource not found").count() > 0:
        return "FAIL", "datasource not found"
    if page.locator("text=Plugin unavailable").count() > 0:
        return "FAIL", "plugin unavailable"
    if page.locator("[data-testid='spinner']").count() > 0:
        return "WARN", "still spinning after settle"
    if screenshot_bytes < 5_000:
        return "WARN", f"screenshot is {screenshot_bytes} B (suspiciously empty)"
    return "PASS", f"no error, screenshot {screenshot_bytes} B"


def capture_panel(page: Page, dashboard_uid: str, panel_id: int, device: str, out_path: Path) -> None:
    url = f"{GRAFANA}/d-solo/{dashboard_uid}?orgId=1&panelId={panel_id}&var-device={device}&{WINDOW}"
    page.goto(url, wait_until="commit", timeout=20_000)
    with contextlib.suppress(Exception):
        page.wait_for_selector("[data-testid='data-testid panel content']",
                               timeout=10_000, state="visible")
    page.wait_for_timeout(SETTLE_MS)
    page.screenshot(path=str(out_path), full_page=False)


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Layer C — playwright not installed. Run:\n"
              "  uv add --dev playwright\n"
              "  uv run playwright install chromium\n"
              "Or skip Layer C with `nobs autocon5 preflight --skip-c`.")
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    screenshots = OUT_DIR / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    manifest = OUT_DIR / "layer_c.json"
    dashboards_dir = WORKSHOP_DIR / "grafana/dashboards"

    captures: list[dict] = []
    fail_count = warn_count = pass_count = 0
    started = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(viewport=PANEL_VIEWPORT, ignore_https_errors=True)

        print("Layer C — login", flush=True)
        login(ctx)
        page = ctx.new_page()

        for dashboard_path in sorted(dashboards_dir.glob("*.json")):
            uid, title, panels = collect_panels(dashboard_path)
            if uid is None:
                uid = resolve_uid(ctx, title)
            print(f"\n=== {title} ({dashboard_path.name}) — {len(panels)} panels ===", flush=True)

            for panel in panels:
                panel_id = panel.get("id")
                panel_title = panel.get("title", "") or "untitled"
                panel_type = panel.get("type", "")
                targets = panel.get("targets", []) or []
                uses_template = "$device" in json.dumps(targets) or "$device" in panel_title
                devices = DEVICES if uses_template else ["all"]

                for device in devices:
                    out_path = screenshots / (
                        f"{dashboard_path.stem}-{device}-{panel_id:02d}-{slugify(panel_title)}.png"
                    )
                    try:
                        capture_panel(page, uid, panel_id, device, out_path)
                        size = out_path.stat().st_size if out_path.exists() else 0
                        verdict, detail = inspect_panel(page, size)
                    except Exception as e:  # noqa: BLE001
                        verdict, detail = "FAIL", f"{type(e).__name__}: {str(e)[:120]}"

                    if verdict == "PASS":
                        pass_count += 1
                    elif verdict == "WARN":
                        warn_count += 1
                    else:
                        fail_count += 1

                    marker = {"PASS": "OK  ", "WARN": "WARN", "FAIL": "FAIL"}[verdict]
                    print(f"  [{marker}] panel #{panel_id:2d} {panel_type:14s} "
                          f"device={device:5s} {panel_title[:40]!r:42s} → {detail}", flush=True)
                    captures.append({
                        "dashboard": dashboard_path.stem,
                        "dashboard_title": title,
                        "uid": uid,
                        "panel_id": panel_id,
                        "panel_title": panel_title,
                        "panel_type": panel_type,
                        "device": device,
                        "verdict": verdict,
                        "detail": detail,
                        "screenshot": str(out_path),
                        "bytes": out_path.stat().st_size if out_path.exists() else 0,
                    })

        browser.close()

    manifest.write_text(json.dumps(captures, indent=2))
    elapsed = round(time.time() - started, 1)
    print(f"\nLayer C — PASS={pass_count} WARN={warn_count} FAIL={fail_count} "
          f"({len(captures)} captures in {elapsed}s)")
    print(f"Layer C — manifest: {manifest}")
    print(f"Layer C — screenshots: {screenshots}/")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
