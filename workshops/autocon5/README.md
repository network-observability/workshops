# AutoCon5 — Modern Network Observability Workshop

A four-hour, laptop-friendly workshop. You bring a laptop with Docker; we
bring a self-contained observability stack (Prometheus, Loki, Grafana,
Alertmanager) plus a synthetic telemetry generator that stands in for a small
network. By lunchtime you'll have queried real-shaped telemetry, made a
dashboard answer an operational question, watched alerts route through an
automated workflow, and seen what an opt-in AI RCA step does next to that
workflow.

> **Format:** ~20% framing and guided demos, ~80% hands-on. The whole stack
> runs locally — no shared backend, no live network gear.

## Agenda (Tuesday, 09:00 – 13:00)

| Time | Part | What |
|------|------|------|
| 09:00 – 09:30 | Framing | From monitoring to modern observability; lab tour |
| 09:30 – 10:45 | **Part 1** | Network telemetry & queries — metrics + logs |
| 10:45 – 11:15 | Break | ☕ |
| 11:15 – 11:55 | **Part 2** | Making the data usable — dashboards |
| 11:55 – 12:55 | **Part 3** | Alerts, automation, AI-assisted operations |
| 12:55 – 13:00 | Close | Key takeaways |

## Before you arrive

Run the preflight from the repo root:

```bash
cd workshops
task preflight
```

It checks Docker, Compose v2, Python, RAM, free disk, and outbound
reachability to `ghcr.io`, `docker.io`, and `github.com`. Resolve any
`[FAIL]` lines before the workshop.

You also need:

- **Docker** (or Docker Desktop / Colima / Rancher Desktop) with **Compose v2**.
  On Windows, run everything inside **WSL 2**.
- **[go-task](https://taskfile.dev/installation/)** (`brew install go-task` on macOS)
- **[uv](https://docs.astral.sh/uv/)** for the workshop's Python helpers
  (Infrahub loader, maintenance toggle). Install with
  `curl -LsSf https://astral.sh/uv/install.sh | sh`. uv installs its own
  pinned Python, so a system Python isn't required.
- ~8 GB of free RAM and ~5 GB of free disk while the stack is running

## Bring it up

The very first time, in this order:

```bash
# 1. From the repo root: install the Python deps once. Creates .venv/.
task setup

# 2. Bring up the stack. The first run pulls a few GB of images (5–10 minutes
#    on the first run, then cached). The Taskfile auto-creates .env from
#    .env.example if it's missing.
task autocon5:up

# 3. Wait ~60 seconds for Infrahub to finish its first-boot init, then check.
task autocon5:status            # repeat until every row says 'ok'

# 4. Apply the schema and seed lab_vars.yml into Infrahub.
task autocon5:load-infrahub

# 5. Useful any time:
task autocon5:ps                # see what's running
task autocon5:logs SVC=webhook  # tail a single container
```

(Or `cd workshops/autocon5 && task up` and use the workshop-scoped names —
both work, the umbrella tasks are just thin wrappers.)

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
task down       # stop everything but keep volumes
task destroy    # full reset (drops volumes too)
```

## What's actually running

![AutoCon5 architecture](docs/architecture.svg)

In words: synthetic telemetry from sonda lands in Prometheus and Loki via two
different patterns (direct push for `srl1`, server + telegraf-scrape for
`srl2`). Alerting rules in both stores route through Alertmanager into a
FastAPI webhook, which fans out to a Prefect flow. The flow consults
**Infrahub** for source-of-truth intent (is this peer expected up? is the
device in maintenance?) before deciding to **quarantine**, **skip**, or just
**audit** — and optionally runs an AI RCA against the same evidence bundle.
Every decision is annotated back into Loki for the audit trail.

The telemetry shape (metric names, labels, log streams) is real — sonda emits
the same patterns a Nokia SR Linux device would. That's why the queries,
dashboards, and alerts you build look exactly like what you'd write against a
production network.

## Part 1 — Network telemetry and queries

Open Grafana → **Explore**, pick the `prometheus` datasource, and try:

```promql
interface_admin_state{intf_role="peer"}
interface_oper_state{intf_role="peer"}

# What links does intent say should be UP that aren't?
(interface_admin_state{intf_role="peer"} == 1)
  and on (device, name)
(interface_oper_state{intf_role="peer"} == 2)
```

Then switch to the `loki` datasource:

```logql
{device="srl1"}
{vendor_facility_process="UPDOWN"} | line_format "{{.device}} {{.interface}} {{.message}}"
sum by (device, interface) (count_over_time({vendor_facility_process="UPDOWN"}[2m]))
```

The "broken" peers are wired in on purpose: `srl1 → 10.1.99.2` and
`srl2 → 10.1.11.1`. Those drive the BGP alerts in Part 3.

## Part 2 — Dashboards

Three dashboards ship pre-provisioned under `/var/lib/grafana/dashboards`:

- **Workshop Lab 1** — the attendee scratchpad. You'll add a panel here.
- **Device Health** — the "one dashboard, one story" reference.
- **Meta-monitoring** — health of the observability stack itself.

The hands-on exercise is in the workshop slides; you'll add a panel to
**Workshop Lab 1** that uses a `device` variable so it works across both
`srl1` and `srl2`.

## Part 3 — Alerts, automation, AI-assisted ops

Two alerts fire automatically against the running telemetry:

- **`BgpSessionNotUp`** — `bgp_admin_state=1` and `bgp_oper_state≠1` for the
  intentionally broken peers (`srl1 → 10.1.99.2`, `srl2 → 10.1.11.1`).
- **`PeerInterfaceFlapping`** — `count_over_time({vendor_facility_process="UPDOWN"}[2m]) > 3`.

Alertmanager forwards both to a FastAPI webhook, which kicks off the Prefect
`alert-receiver` flow. That flow runs the four canonical paths from the
outline:

| Path | When | What happens |
|------|------|--------------|
| **Actionable / mismatch → quarantine** | Intent says peer up, metrics disagree | Silence + annotation |
| **Healthy → skip** | Intent and metrics agree | Audit annotation only |
| **In-maintenance → skip** | Device's `maintenance` flag is true in Infrahub | Audit annotation only |
| **Resolved → audit trail** | Alert resolves | Audit annotation only |

You drive these by hand:

```bash
# Force an interface flap into the log stream — trips PeerInterfaceFlapping in ~30s.
task autocon5:flap-interface DEVICE=srl1 INTERFACE=ethernet-1/1

# Toggle a device into maintenance and watch the next quarantine flow skip.
task autocon5:set-maintenance DEVICE=srl1 STATE=true
task autocon5:set-maintenance DEVICE=srl1 STATE=false

# Inspect what the Prefect flow would see for a given peer.
task autocon5:evidence DEVICE=srl1 PEER=10.1.99.2

# List what's currently firing.
task autocon5:alerts

# Walk all four canonical Part 3 paths in one go.
task autocon5:try-it

# Inspect what's currently registered with sonda-server.
task autocon5:scenarios
```

### AI-assisted RCA toggle

The Prefect flow runs an opt-in LLM RCA step against the same evidence
bundle (metrics + logs + source-of-truth). When `ENABLE_AI_RCA=false` (the
default), the step still runs but annotates a clear "AI RCA disabled"
message into Loki — the workflow finishes end-to-end either way.

Turn it on by editing `.env`:

```bash
ENABLE_AI_RCA=true
AI_RCA_PROVIDER=openai          # or anthropic
AI_RCA_MODEL=gpt-4o-mini        # or e.g. claude-haiku-4-5-20251001
OPENAI_API_KEY=sk-...           # only the one matching AI_RCA_PROVIDER is required
```

Then `task restart`. Honest framing: the LLM output is annotated next to the
deterministic policy result, not in place of it. Human judgement still owns
the call to act — the AI gives you a faster narrative around the evidence,
not an autonomous decision.

## Going deeper

- [`infrahub/README.md`](infrahub/README.md) — the source-of-truth schema
  walkthrough: what the three node types are, why they look the way they
  do, how the upstream Nautobot model maps onto them, and the GraphQL
  queries Grafana + the Prefect flow run against them. Read this before
  extending the schema or adding new alert/automation logic that depends
  on intent.

## Repo layout (what's where)

```text
workshops/autocon5/
  Taskfile.yml         # the commands you actually use
  pyproject.toml       # workshop's Python deps (uv workspace member)
  docker-compose.yml   # the stack
  .env.example         # copy to .env to override defaults
  lab_vars.yml         # source-of-truth data fed into Infrahub
  sonda/
    scenarios/         # synthetic metric + log scenarios (srl1, srl2, all-logs)
    scripts/           # sonda-server bootstrap + telegraf scrape script
  prometheus/          # config + alert/recording rules
  loki/                # config + alert/recording rules
  alertmanager/        # routing config
  grafana/             # provisioning + the three dashboards
  telegraf/            # scrape config for sonda-server
  logstash/            # GELF -> Loki ingest
  infrahub/            # schema YAML + design notes (see infrahub/README.md)
  src/autocon5_cli/    # workshop-specific Typer commands (load, evidence, try-it)
  scripts/             # shell glue (load-infrahub.sh — waits for Infrahub then runs the CLI)
  webhook/             # FastAPI receiver for Alertmanager
  automation/          # Prefect flows + workshop SDK + Dockerfile
```

Workshop-agnostic helpers live one level up at `../../scripts/` — currently
`preflight.sh` and `sonda-trigger.sh`.

## Troubleshooting

- **`task autocon5:up` succeeds but Grafana can't reach Infrahub.** First
  boot of Infrahub takes ~60s. Run `task autocon5:status` until every row
  reads `ok`, then `task autocon5:load-infrahub`.
- **`task autocon5:load-infrahub` says token mismatch.** The token in
  `.env` must match `INFRAHUB_INITIAL_ADMIN_TOKEN`, which is seeded only
  on the *first* boot of `infrahub-server`. If you changed the token after
  first boot, run `task autocon5:destroy && task autocon5:up`.
- **No metrics in Grafana.** Check the Prometheus targets at
  http://localhost:9090/targets. `telegraf-02` should be `UP` and
  `sonda-server` should have at least one registered scenario
  (`task autocon5:scenarios`).
- **Alerts never fire.** The "broken peer" data only fires after the alert's
  `for:` window (30s for BGP, 30s for the flap rule on top of a 2m count).
  Be patient, then `task autocon5:alerts` to see what's active.
- **Webhook errors trying to call Prefect.** The `prefect-flows` container
  registers and serves the `alert-receiver` deployment as soon as it boots.
  If on a slow laptop the webhook starts firing before that's ready,
  `task autocon5:restart-flows` re-registers the deployment.
