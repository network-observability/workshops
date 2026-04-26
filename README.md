# Network Observability Workshops

Self-contained, laptop-friendly workshops for **Modern Network Observability** —
the book and the talks. Each workshop spins up a complete observability stack
(Prometheus, Loki, Grafana, Alertmanager, Telegraf, Infrahub, Prefect) plus a
synthetic telemetry generator ([sonda](https://github.com/davidban77/sonda)) that
stands in for a small network. No real or containerized network devices required.

## Why this repo exists

The companion repo [`network-observability-lab`][lab] grew out of the book's
chapter exercises. It is excellent if you want depth — every chapter, every
variant, every collector — but the surface area is large and the setup assumes
you can run cEOS / SR Linux containers locally.

This repo is the opposite trade-off: **one Taskfile, one `docker compose up`,
one observability stack per workshop**, and `sonda` doing the network-shaped
telemetry instead of real devices.

[lab]: https://github.com/network-observability/network-observability-lab

## Repo layout

```text
Taskfile.yml             # umbrella tasks; namespaces into each workshop
pyproject.toml           # uv workspace root (members = packages/*, workshops/*)
.python-version          # Python version pin (uv reads this)
scripts/                 # shared shell helpers (workshop-agnostic)
  preflight.sh           # check docker, RAM, disk, network reachability
  sonda-trigger.sh       # generic sonda/Loki triggers (e.g. flap-interface)
packages/
  nobs/                  # shared Python CLI used by every workshop
                         #   nobs status / alerts / schema load / maintenance
notes/                   # local-only scratchpad — gitignored, see notes/README.md
workshops/
  autocon5/              # AutoCon5 — Modern Network Observability workshop
    README.md            # attendee-facing instructions
    Taskfile.yml         # workshop-scoped tasks
    pyproject.toml       # workshop's Python deps (uv workspace member)
    docker-compose.yml
    .env.example
    lab_vars.yml         # source-of-truth data fed into Infrahub
    sonda/               # synthetic telemetry scenarios + helper scripts
    prometheus/          # config + alert/recording rules
    loki/                # config + alert/recording rules
    alertmanager/        # routing config
    grafana/             # provisioning + dashboards
    telegraf/            # scrape config for sonda-server
    logstash/            # GELF -> Loki ingest
    infrahub/            # schema YAML
    scripts/             # workshop-specific helpers (Infrahub loader, set-maintenance)
    webhook/             # FastAPI receiver for Alertmanager
    automation/          # Prefect flows (alert -> evidence -> decision -> action -> RCA)
```

The umbrella `Taskfile.yml` namespaces tasks per workshop:

```bash
task setup                                          # uv sync (Python deps)
task preflight                                      # generic env check
task autocon5:up                                    # bring up the AutoCon5 stack
task autocon5:down
task autocon5:flap-interface DEVICE=srl1 INTERFACE=ethernet-1/1
```

**Two CLIs** are installed when you `uv sync`:

- `nobs` — generic operator toolkit (status, alerts, schema load, maintenance).
  Reusable across workshops and ad-hoc work. Lives at `packages/nobs/`.
- `autocon5` — workshop CLI. Re-exports every `nobs` subcommand and adds
  workshop-specific ones (`load-infrahub`, `evidence`, `try-it`). Lives at
  `workshops/autocon5/src/autocon5_cli/`.

Attendees only need `autocon5`. `nobs` is exposed for anyone driving an
arbitrary stack.

## Prerequisites

- A laptop with **Docker** (or Docker Desktop / Colima / Rancher Desktop) and
  **Docker Compose v2** — `docker compose version` should report v2+.
- **[go-task](https://taskfile.dev/installation/)** — `brew install go-task` on
  macOS, or grab a binary from the releases page.
- **[uv](https://docs.astral.sh/uv/)** for the Python tooling
  (`curl -LsSf https://astral.sh/uv/install.sh | sh`). uv handles Python
  installation too, so you don't need a system Python.
- **Git** to clone the repo and a few GB of free disk for container images.
- Approximately **8 GB of free RAM** while the stack is running.
- Outbound HTTPS to `github.com`, `ghcr.io`, `docker.io`, `quay.io` for image
  pulls.

## Quickstart

```bash
git clone https://github.com/network-observability/workshops.git
cd workshops

# One-time: sync the Python helpers into a workspace .venv/.
task setup

# Generic environment check (works for any workshop).
task preflight

# Bring up the AutoCon5 stack.
task autocon5:up

# Seed the source-of-truth (Infrahub).
task autocon5:load-infrahub

# When you're done.
task autocon5:down
```

Each workshop's own README walks through the agenda and the hands-on parts.

## Available workshops

| Workshop | When | Outline |
|----------|------|---------|
| [`autocon5`](workshops/autocon5/README.md) | AutoCon5, Mon 4 May 2026 | Telemetry & queries → dashboards → alerts, automation, AI-assisted ops |

## License

[MIT](LICENSE).
