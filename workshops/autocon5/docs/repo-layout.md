# Repo layout (operator)

The shape of `workshops/autocon5/` and what each piece does.
Use this when you're tracing a feature end-to-end (e.g. "an alert fires — where's the rule, where's the receiver, where's the flow?") or auditing what's in scope for a change.

```text
workshops/autocon5/
  pyproject.toml       # workshop's Python deps (uv workspace member)
  docker-compose.yml   # the stack — ~25 services
  .env.example         # tracked template; copied to .env on first `nobs autocon5 up`
  lab_vars.yml         # source-of-truth data fed into Infrahub
  docs/                # operator/maintainer docs (you are here)
  sonda/
    scenarios/         # synthetic metric + log scenarios (srl1, srl2, all-logs)
    packs/             # custom srlinux gNMI packs (referenced via SONDA_PACK_PATH)
    scripts/           # sonda-server bootstrap + telegraf scrape script
  prometheus/          # config + alert/recording rules
  loki/                # config + alert/recording rules
  alertmanager/        # routing config
  grafana/             # provisioning + the three dashboards
  telegraf/            # scrape config for sonda-server (the "srl2" pipeline)
  logstash/            # GELF -> Loki ingest (currently disabled in compose)
  infrahub/            # schema YAML + design notes — see infrahub/README.md
  src/autocon5_workshop/   # workshop-specific commands; registers itself with `nobs`
  webhook/             # FastAPI receiver for Alertmanager
  automation/          # Prefect flows + workshop SDK + Dockerfile
```

Workshop-agnostic helpers live one level up under [`../../packages/nobs/src/nobs/lifecycle/`](../../../packages/nobs/src/nobs/lifecycle/) — `preflight.py` (generic env check), `env.py` (the single `.env` loader with the centralised `infrahub-server → localhost` rewrite), `compose.py` + `commands.py` (compose lifecycle closures), and `setup.py` (one-shot uv sync + bootstrap).

## Where major flows touch what

A few common operator questions:

**"An attendee says alerts aren't firing — where do I look?"** `prometheus/rules/` and `loki/rules/` for the rule definitions, `alertmanager/` for routing, then `webhook/` (FastAPI) and `automation/` (Prefect flows) for what runs after Alertmanager.

**"How does sonda's telemetry get into Prometheus?"** Two paths — `sonda/scenarios/srl1-metrics.yaml` runs as `sonda-srl1` and uses sonda's own `remote_write` directly into Prometheus.
`sonda/scenarios/srl2-metrics.yaml` runs under `sonda-server`, and `telegraf-02` (config in `telegraf/`) scrapes it on an interval.
Both paths land in the same Prometheus.

**"How does Infrahub get its data?"** Schema in `infrahub/schema.yml`, data in `lab_vars.yml`.
Both are applied by `nobs autocon5 load-infrahub`, which delegates to `src/autocon5_workshop/load.py`.
See [`../infrahub/README.md`](../infrahub/README.md) for the schema walkthrough.

**"How does `.env` flow into all of this?"** Two independent loaders; see [`env-lifecycle.md`](env-lifecycle.md).

**"Where do the workshop commands live?"** `src/autocon5_workshop/` — workshop-specific commands (`load-infrahub`, `evidence`, `try-it`, `flap-interface`, `scenarios`).
The generic ones (`status`, `alerts`, `schema load`, `maintenance`, plus the compose lifecycle) live in [`../../../packages/nobs/`](../../../packages/nobs/) and are exposed under the `nobs autocon5` subcommand group.

## One CLI, one workspace

`nobs setup` (or `uv sync` from the repo root) installs the single CLI:

- **`nobs`** — the operator toolkit.
  Generic commands (`nobs status`, `nobs alerts`, `nobs maintenance`, `nobs schema load`) work against any stack via env-defined URLs.
  Per-workshop subcommand groups (`nobs autocon5 ...`) are built dynamically from each registered workshop.
  Lives at `packages/nobs/`; the `nobs` console script lands in `.venv/bin/`.

`autocon5_workshop` is **not** a CLI — it's a Python plugin package that imports `nobs.workshops.register(WORKSHOP)` at module load.
When `nobs.main` imports `autocon5_workshop`, the plugin registers a `Workshop` instance describing autocon5's directory, bootstrap hook, and extra commands; `nobs` then attaches an `autocon5` Typer subcommand group with the generic lifecycle (`up`, `down`, `restart`, `ps`, `logs`, `exec`, `build`) plus the workshop-specific commands.

For ad-hoc work outside any workshop — applying a schema to a different Infrahub instance, for example — the top-level commands keep working: `uv run nobs schema load some-other-schema.yml`.
