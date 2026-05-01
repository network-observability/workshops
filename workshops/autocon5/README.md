# Modern Network Observability Workshop

A four-hour, laptop-friendly workshop.
You bring a laptop with Docker; we bring a self-contained observability stack (Prometheus, Loki, Grafana, Alertmanager) plus a synthetic telemetry generator that stands in for a small network.
By lunchtime you'll have queried real-shaped telemetry, made a dashboard answer an operational question, watched alerts route through an automated workflow, and seen what an opt-in AI RCA step does next to that workflow.

> **Format:** ~20% framing and guided demos, ~80% hands-on.
> The whole stack runs locally — no shared backend, no live network gear.

## FAQ

**Do I need network engineering experience?**
Helpful, not required.
The workshop frames every concept (BGP peering, interface state, syslog UPDOWN events) before you query it.
If you've ever been on the receiving end of a "the dashboard says it's fine but the user says it's broken" page, you'll get the point.

**Do I need to know Prometheus, Loki, or Grafana already?**
A sketch-level idea of "metrics database" and "log database" is enough.
Part 1 builds PromQL and LogQL from first principles against live data, so you'll write queries from scratch rather than read pre-baked ones.

**What if I've never used Docker?**
You need Docker installed and running, but you don't need to write a Dockerfile.
The whole stack is `docker compose up` underneath, wrapped by the `nobs` CLI.
If `docker ps` works on your laptop, you're set.

**What if my laptop is on Windows?**
Run everything inside WSL 2 with Docker Desktop's WSL backend enabled.
Native Windows / PowerShell is not supported — paths and Compose volume semantics differ enough to bite you mid-workshop.

**How big is the stack?**
Around 21 containers, ~5.5 GB of RAM at idle, and ~5 GB of disk for images and volumes. CPU sits at low single-digit percent at idle. Driving a cascade with `nobs autocon5 flap-interface` or `nobs autocon5 incident` briefly pushes the stack to roughly one fully-saturated CPU core (Grafana refreshing dashboards and Prefect running the alert flow account for most of the spike); memory doesn't move with cascade activity. The first `nobs autocon5 up` pulls 3–5 GB of images, which is the slow step. After that, restarts are fast.

**Can I run this offline?**
Yes, once images are pulled.
The only outbound calls during the workshop are the optional AI RCA step (which needs a provider key and internet) and any `docker pull` you trigger by changing image tags.
If conference Wi-Fi melts, the lab keeps running.

**Is anything sent to a remote service?**
No, by default.
All telemetry, alerts, and dashboards are local.
The AI RCA step is opt-in (`ENABLE_AI_RCA=false` is the default) and only calls out to OpenAI or Anthropic if you set a key in `.env`.

**Why two simulated devices instead of one?**
`srl1` and `srl2` exercise two parallel telemetry pipelines so you can compare them side by side.
`srl1` ships canonical metrics and logs straight to Prometheus and Loki.
`srl2` ships raw vendor shapes through Telegraf (metrics) and Vector (syslog), which normalize them.
Both converge on the same canonical schema, distinguishable by the `pipeline` label — see [`docs/data-pipelines.md`](docs/data-pipelines.md).

**Why both Telegraf and Vector?**
Different shipper for each signal type.
Telegraf renames raw gNMI subscription paths into a canonical Prometheus schema; Vector decodes RFC 5424 syslog into Loki-shaped log events.
Running both demonstrates the two patterns most production stacks end up using.

**Why simulated devices instead of real SR Linux containers?**
Two reasons.
A real SR Linux container needs 4–6 GB of RAM each, which would price most laptops out of a multi-device lab.
And the workshop is about observability, not lab orchestration — sonda emits the exact gNMI metric shapes and syslog events a real SR Linux device would, so the PromQL and LogQL you write here is the same query you'd run against production.

**Why Infrahub?**
The Prefect quarantine flow needs to know intent before it acts — is this peer supposed to be up, is this device in maintenance.
Infrahub is the source of truth that answers those questions.
Without an SoT, the workflow can't tell signal from noise and every alert looks the same.

**What does the AI RCA step actually do?**
It takes the same evidence bundle the deterministic flow uses (metrics window, recent logs, intent from Infrahub) and asks an LLM for a narrative explanation.
The output is annotated into Loki next to the deterministic policy decision, not in place of it.
Human judgement still owns whether to act.

**A panel says "No data". What now?**
Check `nobs autocon5 status` first — if any row isn't `ok`, the data simply hasn't arrived yet.
If everything's `ok` and a specific panel is empty, [`docs/troubleshooting.md`](docs/troubleshooting.md) has the recurring failure modes and exact recovery commands.

**Can I keep using this after the workshop?**
Yes — fork the repo and the stack is yours.
Tweak scenarios, change the synthetic topology, point dashboards at your own metrics.
[`docs/env-lifecycle.md`](docs/env-lifecycle.md) covers `.env` mechanics, and `nobs autocon5 destroy` cleanly tears the whole stack down (volumes included) when you're finished.

## Before you arrive

Run the preflight from anywhere in the repo:

```bash
nobs preflight
```

It checks Docker, Compose v2, Python, RAM, free disk, and outbound reachability to `ghcr.io`, `docker.io`, and `github.com`.
Resolve any `[FAIL]` lines before the workshop.

You also need:

- **Docker** (or Docker Desktop / Colima / Rancher Desktop) with **Compose v2**.
  On Windows, run everything inside **WSL 2**.
- **[uv](https://docs.astral.sh/uv/)** for the workshop's Python helpers (Infrahub loader, maintenance toggle).
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
