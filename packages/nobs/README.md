# nobs

A small, opinionated **network observability operator toolkit**. It's the
shared CLI behind every workshop in this repo — and any future project
that wants the same operational surface.

```bash
nobs status                      # quick health check on the whole stack
nobs alerts                      # active alerts, prettily tabled
nobs schema load PATH            # apply an Infrahub schema (wraps infrahubctl)
nobs maintenance --device srl1   # toggle a SoT device's maintenance flag
```

Installed as the `nobs` console script when you `uv sync` from the repo
root. The `autocon5-workshop` package re-exports these subcommands so
attendees can use `autocon5 status` interchangeably.

## Why a separate package?

Most "operations on the running stack" are workshop-agnostic: a Prometheus
scrape, a Loki query, an Infrahub GraphQL call. Pulling them into one
place lets future workshops (and standalone scripts) reuse the same
clients, the same Rich-styled output, the same env-var bindings — without
copying.

Workshop-specific commands (loading workshop-specific YAML into a
workshop-specific Infrahub schema, walking workshop-specific demo paths)
stay in the workshop's own package.

## Conventions

- Every command takes endpoint URLs as flags, with envvar bindings:
  `--prom-url / PROMETHEUS_URL`, `--loki-url / LOKI_URL`,
  `--am-url / ALERTMANAGER_URL`, `--infrahub-url / INFRAHUB_ADDRESS`,
  `--token / INFRAHUB_API_TOKEN`.
- Every command returns a non-zero exit code on failure (so it works in
  CI / shell pipelines).
- Output uses one shared Rich `Console` (`nobs._console.console`) so
  styling is consistent across commands.

## Layout

```text
src/nobs/
  main.py              # Typer root app
  _console.py          # shared Rich console + step/ok/warn/fail helpers
  clients/
    prom.py            # PromClient — instant + range queries
    loki.py            # LokiClient — query_range + annotate (via sonda /events)
    alertmanager.py    # AlertmanagerClient — silences, /api/v2/alerts
    infrahub.py        # InfrahubClient — generic GraphQL helper
  commands/
    status.py          # nobs status
    alerts.py          # nobs alerts
    schema.py          # nobs schema load
    maintenance.py     # nobs maintenance
```
