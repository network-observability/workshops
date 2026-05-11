# Network Observability Workshops

Self-contained, laptop-friendly workshops for **Modern Network Observability** —
the book and the talks.
Each workshop spins up a complete observability stack
(Prometheus, Loki, Grafana, Alertmanager, Telegraf, Infrahub, Prefect) plus a
synthetic telemetry generator ([sonda](https://github.com/davidban77/sonda)) that
stands in for a small network.
No real or containerized network devices required.

> 📖 **Browse it as a website:** <https://network-observability.github.io/workshops/> — the same content rendered as a searchable, mobile-friendly docs site (handy on a phone during the workshop).

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
    vector/              # syslog -> Loki shipper (srl2 log leg)
    infrahub/            # schema YAML
    webhook/             # FastAPI receiver for Alertmanager
    automation/          # Prefect flows (alert -> evidence -> decision -> action -> RCA)
```

**One CLI: `nobs`.**
Workshops are subcommand groups (`nobs autocon5 ...`).
Each workshop ships a small Python plugin under `workshops/<name>/src/<name>_workshop/` that registers itself with `nobs` at import time and contributes its workshop-specific commands.
The bare root surface keeps three workshop-agnostic commands — `nobs setup`, `nobs preflight`, `nobs workshops` — and stops there. Workshop ops (`status`, `alerts`, `maintenance`, `schema load`, plus the docker-compose lifecycle) live on the workshop's subgroup. From inside a workshop directory you can drop the prefix entirely: `cd workshops/autocon5 && nobs alerts` is the same as `nobs autocon5 alerts`.

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

If Docker or uv aren't already installed, the next section walks through each.

## Installing Docker and uv

The workshop assumes you can run `docker compose` and `uv` from a terminal. New to either? Pick the path for your platform:

### Docker

- **macOS** — install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (the easy default), [Colima](https://github.com/abiosoft/colima), or [Rancher Desktop](https://rancherdesktop.io/). For Docker Desktop, run the installer and open the Docker app once so the daemon starts. The official setup guide: <https://docs.docker.com/desktop/setup/install/mac-install/>.
- **Linux** — follow the [Docker Engine install guide](https://docs.docker.com/engine/install/) for your distro (Ubuntu, Debian, Fedora, RHEL, etc.). Add your user to the `docker` group afterwards so commands don't need `sudo`:
  ```bash
  sudo usermod -aG docker $USER
  newgrp docker
  ```
- **Windows** — install [Docker Desktop with the WSL 2 backend](https://docs.docker.com/desktop/setup/install/windows-install/) and run every workshop command inside a WSL 2 shell, not from PowerShell. (Note: the workshop hasn't been tested on Windows; macOS or Linux is the recommended path.)

Verify the install:

```bash
docker compose version
# Docker Compose version v2.x.x
docker ps
# (an empty table is a healthy result — daemon's up, no containers yet)
```

If `docker compose version` reports v2+, you're set. If you only see `docker-compose` (with a hyphen) reporting v1.x, install Compose v2 alongside it — the workshop expects v2.

### uv

One install command works on macOS, Linux, and WSL:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

uv installs its own pinned Python from `.python-version`, so you don't need a system Python.

### One last sanity check

Once both are installed, clone this repo and run the preflight from anywhere inside it:

```bash
uv run nobs preflight
```

It checks Docker, Compose v2, RAM, free disk, and outbound reachability to the image registries the workshop pulls from. Run it the night before the workshop to catch issues with time to fix them.

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

| Workshop | Outline |
|----------|---------|
| [`autocon5`](workshops/autocon5/README.md) | Telemetry & queries → dashboards → alerts, automation, AI-assisted ops |

## License

[MIT](LICENSE).
