# Repo layout (operator)

The shape of `workshops/autocon5/` and what each piece does.
Use this when you're tracing a feature end-to-end (e.g. "an alert fires — where's the rule, where's the receiver, where's the flow?") or auditing what's in scope for a change.

```text
workshops/autocon5/
  Taskfile.yml         # the commands attendees and operators actually use
  pyproject.toml       # workshop's Python deps (uv workspace member)
  docker-compose.yml   # the stack — ~25 services
  .env.example         # tracked template; copied to .env on first `task up`
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
  src/autocon5_cli/    # workshop-specific Typer commands (load, evidence, try-it)
  scripts/             # shell glue (load-infrahub.sh waits for Infrahub then runs the CLI)
  webhook/             # FastAPI receiver for Alertmanager
  automation/          # Prefect flows + workshop SDK + Dockerfile
```

Workshop-agnostic helpers live one level up at [`../../scripts/`](../../../scripts/) — currently `preflight.sh` (generic env check) and `sonda-trigger.sh` (the `flap-interface` backend).

## Where major flows touch what

A few common operator questions:

**"An attendee says alerts aren't firing — where do I look?"** `prometheus/rules/` and `loki/rules/` for the rule definitions, `alertmanager/` for routing, then `webhook/` (FastAPI) and `automation/` (Prefect flows) for what runs after Alertmanager.

**"How does sonda's telemetry get into Prometheus?"** Two paths — `sonda/scenarios/srl1-metrics.yaml` runs as `sonda-srl1` and uses sonda's own `remote_write` directly into Prometheus.
`sonda/scenarios/srl2-metrics.yaml` runs under `sonda-server`, and `telegraf-02` (config in `telegraf/`) scrapes it on an interval.
Both paths land in the same Prometheus.

**"How does Infrahub get its data?"** Schema in `infrahub/schema.yml`, data in `lab_vars.yml`.
Both are applied by `task autocon5:load-infrahub`, which delegates to `src/autocon5_cli/load.py`.
See [`../infrahub/README.md`](../infrahub/README.md) for the schema walkthrough.

**"How does `.env` flow into all of this?"** Three independent loaders; see [`env-lifecycle.md`](env-lifecycle.md).

**"Where do the workshop CLIs live?"** `src/autocon5_cli/` — workshop-specific commands (`load-infrahub`, `evidence`, `try-it`).
The generic ones (`status`, `alerts`, `schema load`, `maintenance`) live in [`../../../packages/nobs/`](../../../packages/nobs/) and are re-exported by the `autocon5` CLI.

## Two CLIs, one workspace

`uv sync` from the repo root installs both:

- **`nobs`** — generic operator toolkit.
  Reusable across workshops and ad-hoc work.
  Lives at `packages/nobs/`.
- **`autocon5`** — workshop CLI.
  Re-exports every `nobs` subcommand and adds workshop-specific ones (`load-infrahub`, `evidence`, `try-it`).
  Lives at `workshops/autocon5/src/autocon5_cli/`.

Attendees only ever invoke `autocon5` (via `task autocon5:*`).
`nobs` is exposed for operators driving an arbitrary stack — for example, applying a schema to a different Infrahub instance with `uv run nobs schema load some-other-schema.yml`.
