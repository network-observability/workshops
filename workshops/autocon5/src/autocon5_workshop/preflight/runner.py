"""`nobs autocon5 preflight` — run Layer A → B → C, aggregate REPORT.md."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Annotated

import typer
from nobs._console import console, fail, note, ok, step

from . import layer_a, layer_b, layer_c


def preflight(
    skip_c: Annotated[
        bool,
        typer.Option("--skip-c/--with-c", help="Skip Layer C (Playwright screenshots)."),
    ] = False,
    out_dir: Annotated[
        Path,
        typer.Option("--out-dir", envvar="PREFLIGHT_OUT_DIR",
                     help="Where to write logs, JSON manifests, and screenshots."),
    ] = Path("/tmp/preflight-out"),
) -> None:
    """Run Layer A → B → C against the live workshop stack.

    Prereqs: stack up (`nobs autocon5 up`), Infrahub seeded
    (`nobs autocon5 load-infrahub`). Layer C requires Playwright:
        uv add --dev playwright
        uv run playwright install chromium
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["PREFLIGHT_OUT_DIR"] = str(out_dir)
    console.print()

    started = time.time()
    rc_a = _run("Layer A — data shape waits", layer_a.main)
    rc_b = _run("Layer B — per-panel /api/ds/query", layer_b.main)
    rc_c: int | None = None
    if not skip_c:
        rc_c = _run("Layer C — per-panel screenshots", layer_c.main)

    report = _render_report(out_dir, rc_a, rc_b, rc_c)
    elapsed = round(time.time() - started, 1)

    summary = (
        f"Layer A exit={rc_a} | Layer B exit={rc_b}"
        + (f" | Layer C exit={rc_c}" if rc_c is not None else " | Layer C skipped")
    )
    if max(rc_a, rc_b, rc_c or 0) == 0:
        ok(f"preflight green ({elapsed}s) — {summary}")
    else:
        fail(f"preflight failures ({elapsed}s) — {summary}")
    note(f"report: {report}")
    if not skip_c:
        note(f"screenshots: {out_dir / 'screenshots'}/")
    raise typer.Exit(code=max(rc_a, rc_b, rc_c or 0))


def _run(label: str, layer_main) -> int:
    step(label)
    return layer_main()


def _render_report(out_dir: Path, rc_a: int, rc_b: int, rc_c: int | None) -> Path:
    report = out_dir / "REPORT.md"
    parts: list[str] = [
        f"# AutoCon5 preflight — {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "## Summary\n",
        f"- Layer A (data shape): exit={rc_a}",
        f"- Layer B (per-panel /api/ds/query): exit={rc_b}",
    ]
    if rc_c is not None:
        parts.append(f"- Layer C (per-panel screenshots): exit={rc_c}")
    parts.append("")

    layer_a_json = out_dir / "layer_a.json"
    if layer_a_json.exists():
        parts.append("## Layer A — data shape waits\n")
        for r in json.loads(layer_a_json.read_text()):
            parts.append(f"- **{'PASS' if r['ok'] else 'FAIL'}** "
                         f"`{r['label']}` — {r['detail']} (elapsed {r['elapsed_s']}s)")
        parts.append("")

    layer_b_json = out_dir / "layer_b.json"
    if layer_b_json.exists():
        parts.append("## Layer B — per-panel /api/ds/query\n")
        for d in json.loads(layer_b_json.read_text()):
            parts.append(f"### {d['dashboard']} ({d['file']})\n")
            parts.append("| panel | type | device | status | summary |")
            parts.append("|---|---|---|---|---|")
            for p in d["panels"]:
                parts.append(f"| #{p['panel_id']} {p['panel_title']} | "
                             f"{p['panel_type']} | {p['device']} | "
                             f"**{p['status']}** | {p['summary']} |")
            parts.append("")

    layer_c_json = out_dir / "layer_c.json"
    if layer_c_json.exists():
        parts.append("## Layer C — per-panel screenshots\n")
        captures = json.loads(layer_c_json.read_text())
        verdicts = {"PASS": 0, "WARN": 0, "FAIL": 0}
        for c in captures:
            verdicts[c["verdict"]] = verdicts.get(c["verdict"], 0) + 1
        parts.append(f"- {len(captures)} captures: "
                     f"PASS={verdicts.get('PASS', 0)} "
                     f"WARN={verdicts.get('WARN', 0)} "
                     f"FAIL={verdicts.get('FAIL', 0)}")
        parts.append(f"- Screenshots: `{out_dir / 'screenshots'}/`\n")
        non_pass = [c for c in captures if c["verdict"] != "PASS"]
        if non_pass:
            parts.append("### Non-PASS panels\n")
            parts.append("| dashboard | panel | device | verdict | detail |")
            parts.append("|---|---|---|---|---|")
            for c in non_pass:
                parts.append(f"| {c['dashboard']} | #{c['panel_id']} {c['panel_title']} | "
                             f"{c['device']} | **{c['verdict']}** | {c['detail']} |")
        else:
            parts.append("All panels PASS.")
        parts.append("")

    report.write_text("\n".join(parts))
    return report
