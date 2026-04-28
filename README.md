# Network Observability Workshops

Self-contained, laptop-friendly workshops for **Modern Network Observability** —
the book and the talks.
Each workshop spins up a complete observability stack
(Prometheus, Loki, Grafana, Alertmanager, Telegraf, Infrahub, Prefect) plus a
synthetic telemetry generator ([sonda](https://github.com/davidban77/sonda)) that
stands in for a small network.
No real or containerized network devices required.

## Why this repo exists

The companion repo [`network-observability-lab`][lab] grew out of the book's
chapter exercises.
It is excellent if you want depth — every chapter, every variant, every collector — but the surface area is large and the setup assumes you can run cEOS / SR Linux containers locally.

This repo is the opposite trade-off: **one CLI, one `docker compose` per workshop,
one observability stack**, and `sonda` doing the network-shaped telemetry instead of real devices.

[lab]: https://github.com/network-observability/network-observability-lab

## Repo layout

```text
pyproject.toml           # uv workspace root (members = packages/*, workshops/*)
.python-version          # Python version pin (uv reads this)
packages/
  nobs/                  # the single CLI for every workshop
                         #   nobs setup / preflight / workshops
                         #   nobs <workshop> up / down / status / alerts / ...
notes/                   # local-only scratchpad — gitignored, see notes/README.md
workshops/
  autocon5/              # AutoCon5 — Modern Network Observability workshop
    README.md            # attendee-facing instructions
    pyproject.toml       # workshop's Python deps (uv workspace member)
    docker-compose.yml
    .env.example
    lab_vars.yml         # source-of-truth data fed into Infrahub
    src/autocon5_workshop/  # workshop-specific commands, registered with nobs
    sonda/               # synthetic telemetry scenarios
    prometheus/          # config + alert/recording rules
    loki/                # config + alert/recording rules
    alertmanager/        # routing config
    grafana/             # provisioning + dashboards
    telegraf/            # scrape config for sonda-server
    infrahub/            # schema YAML
    webhook/             # FastAPI receiver for Alertmanager
    automation/          # Prefect flows (alert -> evidence -> decision -> action -> RCA)
```

**One CLI: `nobs`.**
Workshops are subcommand groups (`nobs autocon5 ...`).
Each workshop ships a small Python plugin under `workshops/<name>/src/<name>_workshop/` that registers itself with `nobs` at import time and contributes its workshop-specific commands.
Generic commands (`nobs status`, `nobs alerts`, `nobs maintenance`, `nobs schema load`) keep working without a workshop prefix for ad-hoc ops against any stack.

```bash
nobs setup                                          # uv sync + bootstrap + preflight
nobs preflight                                      # generic env check
nobs autocon5 up                                    # bring up the AutoCon5 stack
nobs autocon5 down
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

## Prerequisites

- A laptop with **Docker** (or Docker Desktop / Colima / Rancher Desktop) and
  **Docker Compose v2** — `docker compose version` should report v2+.
- **[uv](https://docs.astral.sh/uv/)** for the Python tooling
  (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
  uv handles Python installation too, so you don't need a system Python.
- **Git** to clone the repo and a few GB of free disk for container images.
- Approximately **8 GB of free RAM** while the stack is running.
- Outbound HTTPS to `github.com`, `ghcr.io`, `docker.io`, `quay.io` for image
  pulls.

## Quickstart

```bash
git clone https://github.com/network-observability/workshops.git
cd workshops

uv sync --all-packages
uv run nobs setup
uv run nobs autocon5 up
uv run nobs autocon5 load-infrahub
# ... when you're done ...
uv run nobs autocon5 down
```

Each workshop's own README walks through the agenda and the hands-on parts.

## Available workshops

| Workshop | When | Outline |
|----------|------|---------|
| [`autocon5`](workshops/autocon5/README.md) | AutoCon5, Mon 4 May 2026 | Telemetry & queries → dashboards → alerts, automation, AI-assisted ops |

## License

[MIT](LICENSE).
