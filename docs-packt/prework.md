---
title: Pre-work
description: Install Docker and uv, run the preflight, and pull the images before the session — about 20 minutes, best done a few days ahead.
---

<div class="packt-section-hero" markdown>

<span class="packt-section-hero__badge">Before the session · ~20 minutes</span>

<h1 class="packt-section-hero__title">Pre-work</h1>

<p class="packt-section-hero__subtitle">Do this a few days ahead. The slow step is image pulls, and it only happens once.</p>

The whole workshop runs on your own laptop — a complete observability stack in Docker, no shared backend, nothing to sign up for. Almost all of the 20 minutes below is containers downloading in the background while you do something else. Getting it out of the way this week is the difference between spending 09:00 EDT querying telemetry and spending it watching a progress bar.

<p class="packt-section-hero__meta">
  <span>Docker + uv</span>
  <span>~5.5 GB RAM · ~5 GB disk</span>
  <span>Windows = WSL 2 only</span>
</p>

</div>

## Two lanes

**Hands-on lane.** Your laptop runs the stack and you type along with us. This is the better experience and the rest of this page is how you get there.

**Watching lane.** If your laptop can't run the stack — a locked-down corporate machine, not enough RAM, no time to prepare — come anyway. Every command and every expected output is written out in the guides, we drive the whole session on screen, and Packt records it. You will get the ideas either way, and the [Take it home](take-home.md) page lets you do the hands-on parts later with more time than three hours allows. It is not a consolation prize.

Part 2 is a guided demo for everybody, so a stack that's still pulling images at 15:30 Dublin costs you nothing.

## What you need

- **Docker** with Compose v2 — Docker Desktop, Colima, OrbStack or Rancher Desktop all work. `docker compose version` should report v2 or later.
- **[uv](https://docs.astral.sh/uv/)** for the Python tooling. One install command, and it brings its own Python.
- **~5.5 GB of free RAM** while the stack is running, and **~5 GB of free disk** for images.
- **Git**, and outbound HTTPS to `github.com`, `ghcr.io`, `docker.io` and `quay.io` for the image pulls.

### Installing Docker

=== "macOS"

    Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) (the easy default), [Colima](https://github.com/abiosoft/colima), or [Rancher Desktop](https://rancherdesktop.io/). For Docker Desktop, run the installer and open the Docker app once so the daemon starts. Official guide: <https://docs.docker.com/desktop/setup/install/mac-install/>.

=== "Linux"

    Follow the [Docker Engine install guide](https://docs.docker.com/engine/install/) for your distro, then add your user to the `docker` group so commands don't need `sudo`:

    ```bash
    sudo usermod -aG docker $USER
    newgrp docker
    ```

=== "Windows"

    Install [Docker Desktop with the WSL 2 backend](https://docs.docker.com/desktop/setup/install/windows-install/) and run **every** workshop command inside a WSL 2 shell — not PowerShell, not Git Bash. If you have never set WSL up before, do it a few days ahead; it is the single most common thing that goes wrong on the morning.

Verify:

```bash
docker compose version
# Docker Compose version v2.x.x
docker ps
# (an empty table is a healthy result — daemon's up, no containers yet)
```

If you only see `docker-compose` (with a hyphen) reporting v1.x, install Compose v2 alongside it. The workshop expects v2.

### Installing uv

One command on macOS, Linux and WSL:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

uv installs its own pinned Python from the repo's `.python-version`, so you don't need a system Python.

## Run the preflight

Clone the repo and let the preflight check Docker, Compose v2, RAM, disk and registry reachability in one shot:

```bash
git clone https://github.com/network-observability/workshops.git
cd workshops

uv sync --all-packages          # install workspace deps into .venv/
uv run nobs preflight
```

You want every row `ok`. A `warn` on a registry reachability row is usually fine — some registries answer the probe with a 404 or 405 — but any `fail` needs sorting out before the day.

## Pull the images

This is the slow part. Run it once, well ahead of the session, on a connection you trust:

```bash
source .venv/bin/activate       # put nobs on PATH for the rest of the session
nobs packt up                   # first run pulls 3–5 GB of images, ~5–10 min
nobs packt status               # repeat until every row says 'ok'
nobs packt load-infrahub
```

Activating `.venv/` is what lets you drop the `uv run` prefix. If you'd rather not, prefix everything with `uv run` (`uv run nobs packt up`, and so on) — the guides read the same either way.

When every row says `ok` and `load-infrahub` has completed once, you're done. Stop the stack and leave it:

```bash
nobs packt down                 # images stay cached; comes back in seconds
```

!!! warning "Only one workshop stack at a time"

    This repo also hosts a longer in-person workshop whose stack binds the same container names and host ports. `nobs packt up` will refuse to start while the other one's containers exist, and tells you which `destroy` command clears them. If you have never run the other workshop, this will never come up.

## What you'll have running

| Service | URL | Notes |
|---------|-----|-------|
| Grafana | <http://localhost:3000> | login `admin` / `admin` (or whatever you set in `.env`) |
| Prometheus | <http://localhost:9090> | targets, rules, query browser |
| Alertmanager | <http://localhost:9093> | active alerts + silences |
| Loki | <http://localhost:3001> | LogQL endpoint (queried through Grafana) |
| Infrahub | <http://localhost:8000> | source-of-truth UI + GraphQL playground |
| Prefect | <http://localhost:4200> | workflow runs in Part 3 |
| Sonda HTTP API | <http://localhost:8085> | the synthetic telemetry control plane |

## On the morning

Fifteen minutes before we start:

```bash
cd workshops
source .venv/bin/activate
nobs packt up
nobs packt status               # every row ok
nobs packt reset                # clean baseline
```

Open Grafana once and click past both first-login pop-ups — the "change password" prompt (**Skip**) and the "Grafana Assistant is now available" modal (**×**). Doing that ahead of time saves you fumbling through them while we're talking.

Then head to [Part 1](part-1.md).

## If something is red

Reply to Packt's T-2 email with your `nobs preflight` output — the whole block, copied out of your terminal — and we'll look at it before the day. A red preflight two days out is fixable by email; a red one at 09:00 EDT is not, and we won't spend the session debugging individual machines.

The usual culprits: Docker Desktop not actually running, Compose v1 still first on `PATH`, low disk, a corporate proxy blocking `ghcr.io`, and WSL 2 not enabled on Windows.

<nav class="packt-nav-footer" markdown>

<div class="packt-nav-footer__placeholder" aria-hidden="true"></div>

<a class="packt-nav-footer__next" href="../part-1/">
  <span class="packt-nav-footer__label">Next →</span>
  <span class="packt-nav-footer__title">Part 1 — Telemetry and queries</span>
</a>

</nav>
