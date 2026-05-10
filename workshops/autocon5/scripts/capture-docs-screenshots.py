"""Capture full-page Grafana dashboard screenshots for the docs site.

Runs against the local stack (http://localhost:3000), grabs each canonical
dashboard view in kiosk=tv mode, and saves as PNG. Cascade is assumed to be
running so the dashboards have something to show.

Usage:
    nobs autocon5 up
    nobs autocon5 load-infrahub
    nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
    sleep 30                            # let the cascade populate
    uv run --with "playwright>=1.58" python workshops/autocon5/scripts/capture-docs-screenshots.py

Output lands in docs/assets/screenshots/. Re-run after dashboard edits to
refresh the docs visuals.
"""

import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("docs/assets/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

GRAFANA = "http://localhost:3000"

# (slug, url, viewport)
SHOTS = [
    (
        "workshop-home",
        f"{GRAFANA}/d/workshop-home/workshop-home?orgId=1&kiosk=tv",
        {"width": 1600, "height": 1400},
    ),
    (
        "device-health-srl1",
        f"{GRAFANA}/d/c78e686b-138b-4deb-b6ae-3239dc10a162/device-health?orgId=1&var-device=srl1&kiosk=tv",
        {"width": 1600, "height": 1600},
    ),
    (
        "device-health-srl2",
        f"{GRAFANA}/d/c78e686b-138b-4deb-b6ae-3239dc10a162/device-health?orgId=1&var-device=srl2&kiosk=tv",
        {"width": 1600, "height": 1600},
    ),
    (
        "workshop-lab",
        f"{GRAFANA}/d/dfb5dpyjbh2wwa/workshop-lab-2026?orgId=1&var-device=srl1&kiosk=tv",
        {"width": 1600, "height": 1200},
    ),
]


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for slug, url, viewport in SHOTS:
            ctx = browser.new_context(viewport=viewport, device_scale_factor=2)
            page = ctx.new_page()
            print(f"-> {slug}  ({viewport['width']}x{viewport['height']})")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # Try to log in as admin/admin if Grafana shows a login form.
                if "/login" in page.url:
                    page.fill("input[name='user']", "admin")
                    page.fill("input[name='password']", "admin")
                    page.click("button[aria-label='Login button']")
                    page.wait_for_url(lambda u: "/login" not in u, timeout=10_000)
                    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                # No specific selector wait — Grafana's panel selectors vary
                # by version. Just give the dashboard time to render.
                page.wait_for_load_state("networkidle", timeout=20_000)
                time.sleep(6)
                out = OUT / f"{slug}.png"
                page.screenshot(path=str(out), full_page=True)
                size = out.stat().st_size
                print(f"   {out}  ({size:,} bytes)")
            except Exception as e:
                print(f"   FAIL: {e}", file=sys.stderr)
            finally:
                ctx.close()
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
