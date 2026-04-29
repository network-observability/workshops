# `nobs autocon5 preflight`

Three-layer end-to-end check against the live workshop stack. Run before every workshop delivery (and after meaningful PRs) to catch the failure modes a manual smoke test would miss.

## What it checks

| Layer | What | Catches |
|---|---|---|
| **A** | Polls Prometheus + Loki until both pipelines (`direct` and `telegraf` / `vector`) deliver expected series counts; sleeps 130s for `[2m]` rate windows to fill; calls `flap-interface` + `maintenance` in-process to seed annotation producers. | Stack-up regressions; pipeline-label drift; missing producers behind windowed queries. |
| **B** | For every panel in every dashboard JSON, runs each target through Grafana's `/api/ds/query` (the same path the frontend uses) with `$device` substituted to both `srl1` and `srl2`. Validates frame + row count per response. | Datasource UID drift; PromQL/LogQL templates that fail to render; missing label substitutions; broken series shape. |
| **C** | Per-panel headless Chromium captures of Grafana's `d-solo` view, both devices. Inspects the rendered DOM for `No data` / `Datasource not found` / `Plugin unavailable` / spinner-stuck states. | Frontend-plugin issues that don't surface via `/api/ds/query` (e.g. fifemon-graphql), table-join transformations that drop rows when one target fails, panel-config bugs Layer B can't see. |

Each layer writes its own JSON manifest plus a log. The runner aggregates everything into `REPORT.md`.

## Prereqs

- Stack up: `nobs autocon5 up`, then wait for `nobs autocon5 status` to show 7/7 ok.
- Infrahub seeded: `nobs autocon5 load-infrahub`.
- For Layer C only: install Playwright as an optional dep:

  ```bash
  uv sync --all-packages --extra preflight
  uv run playwright install chromium
  ```

  Skip if you only need data-shape validation (`--skip-c`).

## Run it

```bash
# Full preflight (A → B → C). ~12 min wall clock, mostly Layer C screenshots.
nobs autocon5 preflight

# Data-shape only — no Playwright required.
nobs autocon5 preflight --skip-c

# Override output dir
nobs autocon5 preflight --out-dir /tmp/my-preflight
```

Output ends up at `--out-dir` (default `/tmp/preflight-out/`):

```
preflight-out/
├── REPORT.md            ← aggregated summary
├── layer_a.{json,log}
├── layer_b.{json,log}
├── layer_c.{json,log}
└── screenshots/
    ├── device-health-srl1-07-device-details.png
    ├── ... (one PNG per panel × device)
    └── workshop-lab-1-srl2-03-interface-logs.png
```

After a green run, scan `screenshots/` in Finder/Preview for a 30-second visual sanity check.

## Environment overrides

| Var | Default | Purpose |
|---|---|---|
| `PREFLIGHT_OUT_DIR` | `/tmp/preflight-out` | Where logs + JSON + screenshots land. |
| `PROMETHEUS_URL` | `http://localhost:9090` | Layer A direct query target. |
| `LOKI_URL` | `http://localhost:3001` | Layer A direct query target. |
| `GRAFANA_URL` | `http://localhost:3000` | Grafana base for Layer B. |
| `GRAFANA_USER` / `GRAFANA_PASSWORD` | `admin` / `admin` | Grafana login. |

Layer C uses `127.0.0.1` instead of `localhost` because some macOS + Docker setups break Chromium's loopback resolution.

## When something fails

- **Layer A FAIL on pipeline convergence**: usually means sonda-server lost its scenarios after a `docker compose restart`. Re-kick `sonda-setup`:

  ```bash
  docker compose --project-name autocon5 restart sonda-setup
  ```

- **Layer B FAIL on a Prometheus / Loki target**: read the `summary` column for HTTP status / parse error. Re-run the same query in Grafana → Explore to reproduce.

- **Layer B FAIL with `plugin unavailable`**: the panel uses a frontend-only Grafana plugin. Layer B can't validate it; trust Layer C's verdict for that panel.

- **Layer C FAIL with `No data`**: the panel rendered but produced no data. Open the saved screenshot to see what it looks like, then check the panel's targets against the live datasource.

- **Layer C TimeoutError on `goto`**: the scripts use `wait_until="commit"` because Grafana's long-polling JS prevents `load` from firing. If it still hangs, check Grafana is reachable from `127.0.0.1` rather than via Docker bridge networking.

## Adding new layers

Each layer is a self-contained Python module with a `main() -> int` entry point. Add a new `layer_d.py` next to the existing ones, register it in `runner.preflight()`, and write its own JSON + log alongside the others.

Layers worth adding when they become useful:
- **Layer D — alert-rule semantic check**: assert each alert rule matches both devices, dedups correctly.
- **Layer E — Prefect flow correctness**: drive `try-it --auto` and assert decision labels in Loki match the canonical 4-path matrix.

## For other workshops

Each workshop's `*_workshop` package can ship its own `preflight/` subpackage following this same pattern. Copy + adapt — the device names, dashboards, and pipeline labels are workshop-specific, so a generic harness adds more abstraction than it removes.
