---
title: Tour the stack
---

<div class="autocon5-section-hero" markdown>

<span class="autocon5-section-hero__badge">Workshop overview · Reference</span>

<h1 class="autocon5-section-hero__title">Tour the stack</h1>

<p class="autocon5-section-hero__subtitle">Six UIs, six URLs, and what to click in each one.</p>

The workshop runs ~21 containers. You only ever look at six of them: **Sonda server**, **Prometheus**, **Alertmanager**, **Grafana**, **Prefect**, and **Infrahub**. This page is the single reference for how to reach each one, what to expect when you do, and where it shows up in the four parts.

<p class="autocon5-section-hero__meta">
  <span>Read it once, refer back when you're lost</span>
  <span>All URLs are localhost</span>
  <span>Defaults match the shipped <code>.env</code></span>
</p>

</div>

## Sonda server — the synthetic telemetry control plane

The Sonda HTTP API at <http://localhost:8085> is the box that pretends to be `srl1` and `srl2`. Every metric Prometheus stores and every log line Loki indexes during the workshop ultimately came out of a Sonda scenario. There's no UI — it's an HTTP API, and you'll mostly poke it with `curl` (or with `nobs autocon5 scenarios`).

### Endpoints worth knowing

| Endpoint | What it returns |
|----------|-----------------|
| `GET /health` | Liveness probe. Returns `{"status":"ok"}`. |
| `GET /scenarios` | Every scenario currently registered on the server, with `id`, `name`, `state`, `elapsed_secs`, `degraded`. |
| `GET /scenarios/{id}` | One scenario's full body (the YAML you POSTed). |
| `GET /scenarios/{id}/stats` | Per-scenario tick counter, emitted sample count, sink errors. |
| `GET /scenarios/{id}/metrics` | The raw Prometheus-text snapshot Telegraf scrapes. This is the ground truth for what the device "emits". |
| `POST /scenarios` | Register a new scenario. The cascade flap (`nobs autocon5 flap-interface`) is one of these. |
| `DELETE /scenarios/{id}` | Stop and unregister a scenario. |

### Try it

The friendly version — `nobs autocon5 scenarios` renders the same data as a Rich table:

```bash
nobs autocon5 scenarios
```

```text
                       Sonda scenarios
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━┓
┃ ID                         ┃ Name                          ┃ Status ┃ Elapsed ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━┩
│ bgp_peer_10_1_2_2          │ srlinux_gnmi_bgp_raw          │ running │ 312.4   │
│ bgp_peer_10_1_99_2_broken  │ srlinux_gnmi_bgp_raw          │ running │ 312.4   │
│ intf_ethernet_1_11_broken  │ srlinux_gnmi_interface_raw    │ running │ 312.4   │
│ …                          │ …                             │ …       │ …       │
└────────────────────────────┴───────────────────────────────┴─────────┴─────────┘
```

The raw version — same data, just `curl`:

```bash
curl -s http://localhost:8085/scenarios | jq '.scenarios[0]'
```

```json
{
  "id": "bgp_peer_10_1_99_2_broken",
  "name": "srlinux_gnmi_bgp_raw",
  "state": "running",
  "elapsed_secs": 312.4,
  "degraded": false
}
```

To see the actual Prometheus-text output a single scenario is emitting (this is the byte-for-byte input Telegraf reads, before any rename or normalization):

```bash
curl -s http://localhost:8085/scenarios/bgp_peer_10_1_99_2_broken/metrics
```

```text
# HELP srl_bgp_oper_state BGP peer operational state
# TYPE srl_bgp_oper_state gauge
srl_bgp_oper_state{source="srl1",peer_address="10.1.99.2",neighbor_asn="65102"} 5
# HELP srl_bgp_received_routes Routes received from this peer
# TYPE srl_bgp_received_routes gauge
srl_bgp_received_routes{source="srl1",peer_address="10.1.99.2",neighbor_asn="65102"} 0
```

Compare that raw shape with what Prometheus stores after Telegraf renames it (`bgp_oper_state{device="srl1",...}`) and you've seen the entire normalization pipeline end-to-end.

### Inspect the catalog from inside the container

The catalog of packs and scenarios Sonda resolves `pack:` refs against is mounted at `/catalog` inside the `sonda-server` container. The `sonda` CLI is also baked in — `sonda-server` dispatches `run`, `list`, `show`, `new` straight to it. Listing every composable pack the server can reference:

```bash
docker compose --project-name autocon5 exec sonda-server \
  /sonda --catalog /catalog list --kind composable
```

```text
ID                            KIND        SIGNAL
srlinux_gnmi_bgp_raw          composable  metrics
srlinux_gnmi_interface_raw    composable  metrics
cisco_snmp_bgp_raw            composable  metrics
cisco_snmp_interface_raw      composable  metrics
srlinux_ping                  composable  metrics
…
```

### Where you'll see this in the workshop

- **Part 1** — When you query Prometheus and see `bgp_oper_state{device="srl1"}` go from 6 to 5, that's a value Sonda is generating right now. `curl http://localhost:8085/scenarios/{id}/metrics` shows you the raw side of that same number.
- **Part 3** — `nobs autocon5 flap-interface` and `nobs autocon5 incident` both POST cascade scenarios to this server.
- **Advanced** — When you write your own scenario, you'll POST it here.

## Prometheus — the metrics store

Prometheus at <http://localhost:9090> stores every metric Telegraf scrapes. The same Prometheus instance also evaluates the alerting rules that drive Alertmanager and the recording rules that smooth out per-interval rate calculations.

### The four pages you'll actually use

| Page | URL | What it tells you |
|------|-----|-------------------|
| Query browser | <http://localhost:9090/graph> | Type PromQL, get a graph or a table. Your main tool in Part 1. |
| Targets | <http://localhost:9090/targets> | Every scrape target Prometheus knows about, with last-scrape time and `up{}` status. |
| Alerts | <http://localhost:9090/alerts> | Every alerting rule, with its current state (`inactive`, `pending`, `firing`). |
| Rules | <http://localhost:9090/rules> | Every recording and alerting rule, with last-eval time and error count. |

### Targets — verifying telemetry is flowing

Open <http://localhost:9090/targets>. You should see at least two scrape jobs **UP**:

- `telegraf-srl1` (port `9005` inside the workshop network) — feeds the gNMI-style raw metrics from Sonda.
- `telegraf-srl2` (port `9005`) — feeds the SNMP-style raw metrics.

<figure class="section-preview" markdown>

![Prometheus targets page](../assets/screenshots/prometheus-targets-light.png#only-light){ .screenshot loading=lazy }
![Prometheus targets page](../assets/screenshots/prometheus-targets-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Prometheus — Targets</strong> · <code>localhost:9090/targets</code>. Three jobs in this lab: <code>prometheus</code> scraping itself, <code>telegraf-srl1</code>, and <code>telegraf-srl2</code>. All green <strong>UP</strong> badges is what you want; one DOWN is the silent root cause of half the "my dashboard is empty" tickets.</figcaption>

</figure>

If either says **DOWN**, the rest of the lab breaks silently. The first thing to check when "my dashboard is empty" — far more often a target issue than a query issue.

### Queries to try

Open the query browser at <http://localhost:9090/graph>. These three queries are the spine of Part 1:

```promql
interface_oper_state
```

Returns one series per `{device, name}` interface pair. `1` is up, `2` is down — the SR Linux convention. Look for the one stuck at `2`.

```promql
bgp_oper_state{device="srl1"}
```

BGP per-peer operational state on srl1. `6` is `established`, `5` is `active`, anything else is degraded. One row should be stuck at `5`.

```promql
ALERTS{alertstate="firing"}
```

Every alert Prometheus has evaluated as `firing` in the last minute. This is the same set Alertmanager has live.

<figure class="section-preview" markdown>

![Prometheus query browser](../assets/screenshots/prometheus-query-browser-light.png#only-light){ .screenshot loading=lazy }
![Prometheus query browser](../assets/screenshots/prometheus-query-browser-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Prometheus — Query browser</strong> · <code>localhost:9090/graph</code>. The intent-vs-reality query from Part 1, evaluated against the live lab. Two rows — both broken peers — with the <code>oper_state=5</code> value preserved by the <code>and on (...)</code> join.</figcaption>

</figure>

### Alerts and rules

The alerts page (<http://localhost:9090/alerts>) groups every rule by file. `inactive` is normal — the rule is being evaluated, condition just isn't met. `pending` means the condition matched but hasn't been true for the rule's `for:` duration yet. `firing` means the alert has been sent to Alertmanager.

<figure class="section-preview" markdown>

![Prometheus alerts page](../assets/screenshots/prometheus-alerts-light.png#only-light){ .screenshot loading=lazy }
![Prometheus alerts page](../assets/screenshots/prometheus-alerts-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Prometheus — Alerts</strong> · <code>localhost:9090/alerts</code>. Rule files grouped by source (<code>autocon5_bgp_rules.yml</code>, <code>autocon5_interface_rules.yml</code>, …) with each rule's current state badge.</figcaption>

</figure>

The rules page (<http://localhost:9090/rules>) is where recording rules live. The workshop ships several — `device:network_traffic_in_bps:rate_2m` precomputes a 2-minute traffic rate per device so dashboards don't re-derive it for every panel. If a rule's "Health" column is `err`, expand it to see the query and the error.

### Where you'll see this in the workshop

- **Part 1** — the query browser is open the whole time.
- **Part 2** — when you build the flap-rate panel in Grafana, you're writing PromQL that runs against this Prometheus.
- **Part 3** — `BgpSessionNotUp` is one of the rules on this page; firing alerts here become webhook payloads to Prefect.

## Alertmanager — the alert router and silence store

Alertmanager at <http://localhost:9093> receives every `firing` alert from Prometheus, deduplicates and groups them, and routes them out — in the workshop, to the FastAPI webhook that hands off to a Prefect flow. It also stores **silences**: time-bounded suppressions the Prefect quarantine flow drops in to mute an alert it's already containing.

### The two pages you'll actually use

| Page | URL | What it tells you |
|------|-----|-------------------|
| Alerts | <http://localhost:9093/#/alerts> | Every active alert grouped by labels, with `Active` / `Suppressed` state. |
| Silences | <http://localhost:9093/#/silences> | Every silence the workshop has created, with creator, matchers, and expiry. |

### Alerts page

Each active alert shows its labels (`alertname=BgpSessionNotUp`, `device=srl1`, `peer_address=10.1.99.2`, …) plus a state badge. `Active` means the alert is being routed normally. **`Suppressed`** means a matching silence is in effect — for this workshop, that almost always means the Prefect quarantine flow caught the alert, decided it warranted containment, and silenced it for 20 minutes while it worked.

<figure class="section-preview" markdown>

![Alertmanager alerts page](../assets/screenshots/alertmanager-alerts.png){ .screenshot loading=lazy }

<figcaption><strong>Alertmanager — Alerts</strong> · <code>localhost:9093/#/alerts</code>. Groups by routing target — <code>default</code> (the two <code>InterfaceAdminUpOperDown</code> alerts that didn't match the BGP webhook route) and <code>webhook-receiver</code> (the <code>PeerInterfaceFlapping</code> that did). Click any group to expand the matching alerts and their full label set.</figcaption>

</figure>

You can click any alert to expand the full label set. The labels are what the Prefect flow reads when it asks Infrahub *"is this peer expected up?"* — `device` and `peer_address` are the keys.

### Silences page

The silences page is the auditable record of every containment action. When the quarantine flow runs successfully on an alert, you'll see a silence here with:

- **Matchers**: `alertname=BgpSessionNotUp`, `device=srl1`, `peer_address=10.1.99.2`
- **Creator**: `prefect-flow`
- **Comment**: `quarantine: cascade-protect (peer flapping with high rate)`
- **Ends**: 20 minutes after creation

You can manually expire a silence here too — the **Expire** button removes it immediately, and the alert returns to `Active` on the next evaluation cycle.

<figure class="section-preview" markdown>

![Alertmanager silences page](../assets/screenshots/alertmanager-silences.png){ .screenshot loading=lazy }

<figcaption><strong>Alertmanager — Silences</strong> · <code>localhost:9093/#/silences</code>. Three active silences in this snapshot: the two always-broken peers (<code>srl1→10.1.99.2</code>, <code>srl2→10.1.11.1</code>) that the Prefect flow quarantined on startup, plus a fresh one for <code>srl1→10.1.2.2</code> from a cascade <code>flap-interface</code>. Each shows its matchers, expiry timestamp, and an <strong>Expire</strong> button.</figcaption>

</figure>

### CLI equivalents

The `nobs autocon5 alerts` command renders the alerts page as a table:

```bash
nobs autocon5 alerts
```

Useful when you just want a quick "what's firing right now?" without leaving the terminal.

### Where you'll see this in the workshop

- **Part 1** — you check that morning's two `BgpSessionNotUp` alerts are here, then trace them backwards to a single PromQL query.
- **Part 3** — the entire flow lives in this page. Every `try-it` run either creates a silence (quarantine) or doesn't (skip/audit), and the silence is the visible evidence.

## Grafana — dashboards and Explore

Grafana at <http://localhost:3000> (login `admin` / `admin`, or whatever you set in `.env`) is the visualization layer. Three datasources are pre-wired — Prometheus, Loki, and Infrahub (GraphQL via the Infinity datasource) — so dashboards and Explore can query any of them without setup.

### Pre-provisioned dashboards

| Dashboard | URL | What it's for |
|-----------|-----|---------------|
| **Workshop Home** | <http://localhost:3000/d/workshop-home> | The landing page. Currently firing alerts, recent event feed, a list of starter queries with one-click links into Explore. |
| **Workshop Lab 2026** | <http://localhost:3000/d/dfb5dpyjbh2wwa> | Side-by-side panels for the day's exercises. Interface oper status timeline lives here. |
| **Device Health** | <http://localhost:3000/d/c78e686b-138b-4deb-b6ae-3239dc10a162> | Per-device deep dive. BGP peer states, interface state, device-level CPU/memory/uptime. |

### What the panels look like

<figure class="section-preview" markdown>

![BGP States panel](../assets/screenshots/device-health-bgp-states-light.png#only-light){ .screenshot loading=lazy }
![BGP States panel](../assets/screenshots/device-health-bgp-states-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>BGP States</strong> · Device Health (srl1) — three peers, two ESTABLISHED (green) and one stuck in ACTIVE (orange). That orange row is the deliberately-broken peer you find in Part 1 with a single intent-vs-reality query.</figcaption>

</figure>

<figure class="section-preview" markdown>

![Recent events panel](../assets/screenshots/workshop-home-recent-events-light.png#only-light){ .screenshot loading=lazy }
![Recent events panel](../assets/screenshots/workshop-home-recent-events-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Recent events</strong> · Workshop Home — every interface UPDOWN log line shows up here, regardless of which device or pipeline emitted it. The feed you watch when you trigger <code>flap-interface</code>.</figcaption>

</figure>

<figure class="section-preview" markdown>

![Currently firing alerts panel](../assets/screenshots/workshop-home-firing-alerts-light.png#only-light){ .screenshot loading=lazy }
![Currently firing alerts panel](../assets/screenshots/workshop-home-firing-alerts-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Currently firing alerts</strong> · Workshop Home — what Alertmanager has live right now. The input the Prefect automation reasons over in Part 3.</figcaption>

</figure>

<figure class="section-preview" markdown>

![Interface Operational Status panel](../assets/screenshots/workshop-lab-interface-oper-light.png#only-light){ .screenshot loading=lazy }
![Interface Operational Status panel](../assets/screenshots/workshop-lab-interface-oper-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Interface Operational Status</strong> · Workshop Lab — the state timeline for srl1's interfaces. You'll learn to read this in Part 1 and add a flap-rate panel right next to it in Part 2.</figcaption>

</figure>

### Explore mode

The compass icon in the left nav opens **Explore**. Pick a datasource at the top (`prometheus`, `loki`, or `infrahub`), type a query, pick a time range, hit **Run query**. This is where you'll iterate on PromQL and LogQL outside of any dashboard. Every "starter query" link on Workshop Home drops you straight into Explore with the query prefilled.

### Where you'll see this in the workshop

- **Part 1** — Explore mode for PromQL and LogQL practice, Workshop Home for the firing alerts feed.
- **Part 2** — you live in the dashboard editor adding the flap-rate panel.
- **Part 3** — Workshop Home's "Currently firing alerts" panel is your hand-off into the Prefect flow.

## Prefect — workflows, deployments, runs

Prefect at <http://localhost:4200> orchestrates the quarantine workflow that picks up alerts from the webhook. The lab runs Prefect 3 with a Postgres + Redis backend, a worker on the `local-pool` pool, and a flow-server container that registers the `alert-receiver` deployment on startup.

### The three concepts you need

| Concept | What it is | Example in the lab |
|---------|------------|--------------------|
| **Flow** | The Python function. The code. | `quarantine_bgp_flow` — collect evidence, evaluate policy, decide, act, annotate. |
| **Deployment** | A schedulable, invokable wrapper around a flow with default parameters and a target work pool. | `alert-receiver/alert-receiver` — what the webhook calls when an alert lands. |
| **Flow run** | One execution of a deployment (or an ad-hoc flow). Has its own logs and task graph. | Every `try-it` run, every cascade you flap, every direct trigger. |

### The four pages you'll actually use

| Page | URL | What it tells you |
|------|-----|-------------------|
| Runs | <http://localhost:4200/runs> | Every flow run, with state (`Completed`, `Failed`, `Running`), duration, parameters. |
| Deployments | <http://localhost:4200/deployments> | Every registered deployment. Click one to see its parameter schema and trigger an ad-hoc run. |
| Flows | <http://localhost:4200/flows> | Every flow the workers know about, with a count of runs and recent state distribution. |
| Automations | <http://localhost:4200/automations> | Triggers that fire on Prefect-side events (state changes, deployment completions). Empty in the default lab. |

### Runs page — the audit trail

<figure class="section-preview" markdown>

![Prefect flow runs list](../assets/screenshots/prefect-flow-runs-list-light.png#only-light){ .screenshot loading=lazy }
![Prefect flow runs list](../assets/screenshots/prefect-flow-runs-list-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Prefect — Runs</strong> · <code>localhost:4200/runs</code>. Every alert payload the webhook handed off shows up here as a completed flow run.</figcaption>

</figure>

Click a run to drill in. The detail page has the task graph, parameters, logs, and result.

<figure class="section-preview" markdown>

![Prefect flow run detail](../assets/screenshots/prefect-flow-run-detail-light.png#only-light){ .screenshot loading=lazy }
![Prefect flow run detail](../assets/screenshots/prefect-flow-run-detail-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Prefect — Flow run detail</strong> · the task graph for <code>quarantine_bgp</code> (collect_evidence → evaluate_policy → annotate_decision → ai_rca → quarantine → annotate_action) with the per-task log feed underneath.</figcaption>

</figure>

The task graph is the single best place to debug a quarantine decision — every task's output is visible, so you can see exactly what evidence the flow collected, what policy it evaluated, and which path it took. The per-task logs underneath stream live during a run.

### Where you'll see this in the workshop

- **Part 3** spends most of its time in here. You'll trigger four canonical paths from `try-it`, then watch each one render as a flow run.
- **Advanced** — you reason about Prefect runs as your audit trail when you write the final incident runbook.

## Infrahub — source of truth

Infrahub at <http://localhost:8000> (login `admin` / `infrahub`) is the source of truth for *what should be true* about the lab. It stores intent — device roles, expected BGP sessions, maintenance windows — that the Prefect flow consults before deciding what to do with an alert.

### What's loaded

`nobs autocon5 load-infrahub` (which you ran during setup) applies the workshop schema and seeds two `WorkshopDevice` records (`srl1`, `srl2`), each with their `BgpSession` relationships. The schema fields the policy reads:

- `name`, `asn`, `role`, `site_name` — basic identity.
- `maintenance` — boolean. If `true`, the flow skips quarantine.
- `bgp_sessions` (relationship) — each with `peer_address`, `afi_safi`, `expected_state`, `remote_as`, `expected_prefixes_received`, `reason`.

### The three places you'll actually use

| Where | URL | What it tells you |
|-------|-----|-------------------|
| WorkshopDevice list | <http://localhost:8000/objects/WorkshopDevice> | Browse `srl1` and `srl2`, click into the per-device attribute view. |
| GraphQL Sandbox | <http://localhost:8000/graphql> | Run the exact query the Prefect flow runs. Edit it, see what changes. |
| Branch indicator | top-right of every page | Infrahub is branch-aware. `main` is the live branch the flow reads. |

### WorkshopDevice detail

<figure class="section-preview" markdown>

![Infrahub WorkshopDevice srl1](../assets/screenshots/infrahub-device-detail.png){ .screenshot loading=lazy }

<figcaption><strong>Infrahub — <code>WorkshopDevice/srl1</code></strong> · the intent the flow consults: ASN, Maintenance, Site Name, Role, plus Interfaces and BGP Sessions on the tabs above. Toggle Maintenance here and the next alert for this device is skipped by the policy.</figcaption>

</figure>

Navigate via **Object Management → WorkshopDevice → srl1**. The **bgp_sessions** tab shows every BGP session relationship — click a row (e.g., `10.1.99.2`) and you'll see `Expected State = Established`, `Reason = ip-mismatch-demo`. That's the per-peer intent the flow's policy compares against the live `bgp_oper_state` metric in Prometheus.

### GraphQL Sandbox

<figure class="section-preview" markdown>

![Infrahub GraphQL Sandbox](../assets/screenshots/infrahub-graphql.png){ .screenshot loading=lazy }

<figcaption><strong>Infrahub — GraphQL Sandbox</strong> · <code>localhost:8000/graphql</code>. The exact <code>DeviceIntent</code> query the Prefect flow runs against Infrahub. No secret access — anyone can run this and see what the policy sees.</figcaption>

</figure>

This is the exact query the Prefect flow runs (verbatim from `automation/workshop_sdk.py`). Paste it in, hit run, and you'll see the same answer the policy got:

```graphql
query DeviceIntent {
  WorkshopDevice(name__value: "srl1") {
    edges {
      node {
        name { value }
        maintenance { value }
        site_name { value }
        role { value }
        bgp_sessions {
          edges {
            node {
              peer_address { value }
              expected_state { value }
              remote_as { value }
              reason { value }
            }
          }
        }
      }
    }
  }
}
```

The flow has no secret access — anything you can read here, it reads with the same query.

### Where you'll see this in the workshop

- **Part 1** — you cross-reference an alert against intent: *"Infrahub says this peer should be `established`; Prometheus says `active`."* That's the diff that turns a noisy alert into a real incident.
- **Part 3** — toggling `maintenance` on a device (via `nobs autocon5 maintenance --device srl1 --state` or directly in the UI) is what makes the policy take the skip path on the next alert. The flow re-reads Infrahub on every alert.
