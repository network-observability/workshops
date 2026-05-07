# Modern Network Observability Workshop

A four-hour, laptop-friendly workshop.
You bring a laptop with Docker; we bring a self-contained observability stack (Prometheus, Loki, Grafana, Alertmanager) plus a synthetic telemetry generator that stands in for a small network.
By lunchtime you'll have queried real-shaped telemetry, made a dashboard answer an operational question, watched alerts route through an automated workflow, and seen what an opt-in AI RCA step does next to that workflow.

> **Format:** ~20% framing and guided demos, ~80% hands-on.
> The whole stack runs locally — no shared backend, no live network gear.

## FAQ

**Do I need network engineering experience?**
Helpful, not required. Every concept (BGP peering, interface state, syslog UPDOWN events) is framed before you query it.

**Do I need to know Prometheus, Loki, or Grafana already?**
A sketch-level idea of "metrics database" and "log database" is enough. Part 1 builds PromQL and LogQL from first principles against live data.

**What if I've never used Docker?**
You need Docker installed and running, but you don't need to write a Dockerfile. If `docker ps` works on your laptop, you're set.

**Why do I need `uv` installed?**
We use [`uv`](https://docs.astral.sh/uv/) to install and run the workshop's `nobs` CLI — a thin wrapper that fronts every workshop command (`up`, `down`, `status`, `alerts`, `flap-interface`, and the rest). With `uv` set up the rest of the day flows through one-line commands instead of raw `docker compose` invocations.

**What if my laptop is on Windows?**
We recommend macOS or a Linux-based system — on Windows the workshop should run natively under WSL 2, but we haven't tested it there. Native Windows / PowerShell isn't supported.

**How big is the stack?**
Around 21 containers, ~5.5 GB of RAM, and ~5 GB of disk. The first `nobs autocon5 up` pulls 3–5 GB of images — that's the slow step. After that, restarts are fast.

**Can I run this offline?**
Yes, once images are pulled. The only outbound call during the workshop is the optional AI RCA step (needs a provider key and internet). If conference Wi-Fi melts, the lab keeps running.

**Is anything sent to a remote service?**
No, by default. All telemetry, alerts, and dashboards are local. The AI RCA step is opt-in (`ENABLE_AI_RCA=false` by default) and only calls OpenAI or Anthropic if you set a key in `.env`.

**Why simulated devices instead of real SR Linux containers?**
Real SR Linux containers need 4–6 GB of RAM each, which would price most laptops out of a multi-device lab. Sonda emits the same gNMI metric shapes and syslog events a real device would, so the queries you write here are the same ones you'd run against production. If you want the full lab with real containers, the companion repo is [`network-observability-lab`](https://github.com/network-observability/network-observability-lab).

**Can I keep using this after the workshop?**
Yes — fork the repo and the stack is yours. `nobs autocon5 destroy` cleanly tears it down when you're finished.

## Before you arrive

Run the preflight from anywhere in the repo:

```bash
nobs preflight
```

It checks Docker, Compose v2, Python, RAM, free disk, and outbound reachability to `ghcr.io`, `docker.io`, and `github.com`.
Resolve any `[FAIL]` lines before the workshop.

You also need:

- **Docker** (or Docker Desktop / Colima / Rancher Desktop) with **Compose v2**.
- **[uv](https://docs.astral.sh/uv/)** to install and run the workshop's `nobs` CLI.
  Install with `curl -LsSf https://astral.sh/uv/install.sh | sh`.
  uv installs its own pinned Python, so a system Python isn't required.
- ~8 GB of free RAM and ~5 GB of free disk while the stack is running

## Bring it up

The very first time, in this order:

```bash
uv sync --all-packages          # install workspace deps into .venv/
uv run nobs setup               # bootstrap .env + preflight
uv run nobs autocon5 up         # first run pulls images, ~5–10 min
uv run nobs autocon5 status     # repeat until every row says 'ok'
uv run nobs autocon5 load-infrahub
```

Once the stack is up and Infrahub is seeded, you'll have:

| Service | URL | Notes |
|---------|-----|-------|
| Grafana | http://localhost:3000 | login `admin` / `admin` (or whatever you set in `.env`) |
| Prometheus | http://localhost:9090 | targets, rules, query browser |
| Alertmanager | http://localhost:9093 | active alerts + silences |
| Loki | http://localhost:3001 | LogQL endpoint (queried from Grafana) |
| Infrahub | http://localhost:8000 | source-of-truth UI + GraphQL playground |
| Prefect | http://localhost:4200 | workflow runs in Part 3 |
| Sonda HTTP API | http://localhost:8085 | the synthetic telemetry control plane |

When you're done:

```bash
nobs autocon5 down       # stop everything but keep volumes
nobs autocon5 destroy    # full reset (drops volumes too)
```

If anything misbehaves during the workshop, ask the instructor — they have the operator runbook in [`docs/troubleshooting.md`](docs/troubleshooting.md).

## What's actually running

![Workshop architecture](docs/architecture.svg)

In words: synthetic telemetry from sonda lands in Prometheus and Loki.
Alerting rules in both stores route through Alertmanager into a FastAPI webhook, which fans out to a Prefect flow.
The flow consults **Infrahub** for source-of-truth intent (is this peer expected up? is the device in maintenance?) before deciding to **quarantine**, **skip**, or just **audit** — and optionally runs an AI RCA against the same evidence bundle.
Every decision is annotated back into Loki for the audit trail.

The telemetry shape (metric names, labels, log streams) is real — sonda emits the same patterns a Nokia SR Linux device would.
That's why the queries, dashboards, and alerts you build look exactly like what you'd write against a production network.

## Driving the BGP cascade (`flap-interface`)

`nobs autocon5 flap-interface` posts a single declarative cascade scenario to sonda's `/scenarios` endpoint. The interface flap drives `interface_oper_state` via the `enum: oper_state` shorthand on sonda's `flap` generator (UP=1, DOWN=2 — gNMI / openconfig convention); the BGP per-peer metrics and a UPDOWN log stream are gated by a `while: { ref: primary_flap, op: ">", value: 1 }` clause with `delay.open: 10s` (the BGP hold-down). When the gate closes, each gated entry writes one literal recovery sample via `delay.close.snap_to` (e.g. `bgp_oper_state=1`, prefix counters back to `10`), so dashboards snap green within seconds and `BgpSessionNotUp` resolves on the next scrape cycle. The default cascade runs for 4 minutes with 30s up / 60s down cycles. The static reference YAML for the default demo target (`srl1:ethernet-1/1`, peer `10.1.2.2`) lives at [`sonda/scenarios/cascade-incident.yaml`](sonda/scenarios/cascade-incident.yaml); the CLI rebuilds the body in memory whenever a different `--device`/`--interface` is requested.

Pass `--no-cascade` to emit the interface flap and UPDOWN log stream alone (no BGP collapse) — useful for the Part 1 exercise that trips `PeerInterfaceFlapping` without bringing a session down. The UPDOWN log stream emits at a steady cadence during each down window (one line every two seconds, ~30 events across a 60s down phase) rather than one log per state transition — the alert query (`count_over_time UPDOWN > 3 in 2m`) still fires, but the per-line content is a single down-state template rather than alternating up/down events. Counters such as `interface_in_octets` / `interface_out_octets` keep their last-observed values during a flap; sonda's gated value coupling is not in scope today.

## Part 1 — Network telemetry and queries

Morning of your first deep day on the on-call rotation. Your senior buddy walks you through the lab's telemetry shape — what "normal" looks like, where the broken things hide, how to bridge a metric anomaly to a log line that explains it. By the end you'll have a baseline you can compare every future triage against.

Hands-on guide: [`guides/part-1-telemetry-and-queries.md`](guides/part-1-telemetry-and-queries.md).

## Part 2 — Dashboards

Mid-morning — a post-mortem email lands. Last night's page lost ten minutes because a flap-rate panel didn't exist yet. You build it now, with thresholds matching the actual alert rule, while the team is still in the room.

Hands-on guide: [`guides/part-2-dashboards.md`](guides/part-2-dashboards.md).

## Part 3 — Alerts, automation, AI-assisted ops

Late morning, before lunch — a real alert lands while your senior narrates. Walk the four canonical paths the workflow handles, toggle the AI RCA step, and decide which paths you'd trust the LLM narrative on at 2am. As the lunch break lands your senior signs off and you're ready to take primary on the rotation tomorrow.

Hands-on guide: [`guides/part-3-alerts-automation-ai.md`](guides/part-3-alerts-automation-ai.md).

## Going deeper

For maintainers, instructors, and anyone forking this workshop:

- [`docs/`](docs/) — operator documentation index (architecture diagram, `.env` lifecycle, repo layout, troubleshooting).
- [`docs/env-lifecycle.md`](docs/env-lifecycle.md) — who creates `.env`, who reads it, and the host-vs-container nuance.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — the recurring failure modes and exact recovery commands.
- [`docs/repo-layout.md`](docs/repo-layout.md) — what every directory contributes and where to look when tracing a flow.
- [`docs/data-pipelines.md`](docs/data-pipelines.md) — the two-pipeline pattern (direct vs shipper) for metrics and logs, with curl commands to inspect raw vs normalized shapes.
- [`docs/preflight.md`](docs/preflight.md) — `nobs autocon5 preflight` regression check (Layer A data-shape waits, Layer B per-panel `/api/ds/query`, Layer C headless Grafana screenshots).
- [`infrahub/README.md`](infrahub/README.md) — the source-of-truth schema walkthrough: what the three node types are, why they look the way they do, how the upstream Nautobot model maps onto them, and the GraphQL queries Grafana + the Prefect flow run against them.
