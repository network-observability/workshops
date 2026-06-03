# Part 1 — Network telemetry and queries

## What you'll do here

It's Monday morning. You just rotated onto the on-call team for your company's network observability platform and today is your first deep day. You've got coffee. Your senior buddy is leaning on the desk next to you, laptop open. They're going to walk you through the lab over the next 75 minutes — what "normal" looks like, where the broken things hide, how to bridge from a metric anomaly to a log line that explains it. From tomorrow you'll be primary on the rotation, so today the goal is simple: build a baseline mental model of this network so every future triage has something to compare against.

Write PromQL and LogQL by hand against the running lab. Discover the metric schema, find the deliberately broken BGP peer with a single intent-vs-reality query, and correlate metrics to logs to explain *why* a session is down. By the end you'll know enough query syntax to read any dashboard in this workshop.

This part is the longest of the day on purpose — every later part depends on you being comfortable in the query bar.

## Setup check

Your senior already has Grafana up on their screen. They've reset the lab to known-good baseline and confirmed every row says `ok`. Your turn.

If this is your first time bringing up the lab solo, run the four-command **Bring it up** sequence from the workshop README first (`uv sync --all-packages` → `nobs setup` → `nobs autocon5 up` → `nobs autocon5 load-infrahub`) — `nobs autocon5 up` alone doesn't seed Infrahub, and `reset` will fail with `SchemaNotFoundError` until `load-infrahub` has run once.

In a terminal:

```bash
nobs autocon5 reset
nobs autocon5 status
```

`reset` is safe to run repeatedly — it clears any leftover maintenance flags, expires any silences from a prior workshop run, removes any cascade scenarios still hanging around, and restarts the log shipper if it has gone quiet. Safe to run at the start of every part. `status` then confirms every row reports `ok`. If `prometheus`, `loki`, or `sonda` is anything else, flag it before continuing — your senior wants to know about a degraded stack before you lean on it.

Open Grafana at <http://localhost:3000> (login `admin` / `admin` unless you changed `.env`). On the very first login you'll see two pop-ups — click **Skip** on the "change password" prompt and the **×** on the "Grafana Assistant is now available" what's-new modal. Both are unrelated to the workshop. Then click the compass icon in the left rail to open **Explore**. The datasource picker at the top is how you switch between Prometheus and Loki. You'll bounce between them throughout this part.

Open the **Workshop Home** dashboard once (`/d/workshop-home`) so you've seen the stat row — Devices, Interfaces, Firing alerts, Log lines (5m). Those four numbers are your sanity check throughout the workshop.

## The exercises

### Metrics — PromQL

> Your senior taps the screen. *"Pull up Explore. Before we touch anything else this morning, you need to know what's even talking to us right now. Start with the metric name everything in this lab keys off of."*

#### 1. Discover what's in the lab

In Explore, pick the `prometheus` datasource. In the query bar, run:

```promql
interface_oper_state
```

Click `Run query`. **You should see exactly 6 results** — three interfaces per device, two devices. Click any row's labels and the inspector shows the full label set:

- `device` — `srl1` or `srl2`
- `name` — interface name (`ethernet-1/1`, `ethernet-1/10`, `ethernet-1/11`)
- `intf_role` — `peer` for the three real ones
- `collection_type` — `gnmi` (srl1) or `snmp` (srl2)
- `pipeline` — `telegraf` (both devices route through Telegraf today)
- `host`, `instance`, `job` — where Prometheus scraped from

> Your senior nods at the screen. *"Notice anything? Same metric name, same value semantics on both sides — but the `collection_type` label says one device emits gNMI and the other emits SNMP. That's the workshop's normalization story. We'll come back to it. For now: the metric is the same downstream regardless."*

**Stop and notice.** The metric *name* tells you what (operational state of an interface). The *labels* tell you which one and where it came from. Every query you write from now on is a filter or aggregation on labels.

Now try an aggregation. How many peer interfaces are operationally up per device?

```promql
count by (device) (interface_oper_state{intf_role="peer"} == 1)
```

`== 1` filters to only up interfaces (1 = UP, 2 = DOWN). `count by (device)` collapses every label *except* `device` — list the labels you want to keep and everything else flattens. You should see `srl1` returning `2` and `srl2` returning `2` — two healthy peer interfaces per device, with one down on each.

#### 2. Normalization — two raw shapes, one shared schema

> Your senior swivels their laptop toward you. *"Before we go further — notice that `intf_role` label on every series? That didn't come from the device. It was added by Telegraf during normalization. Let me show you what the raw shape looks like before it's touched. This is the part that bites every operator who jumps from one vendor's network to another."*

The two devices speak different protocols at the source:

- **`srl1` emits gNMI** — that's the telemetry shape SR Linux puts on the wire natively. Field names like `srl_interface_oper_state`, tags like `source`. **Telegraf-srl1** scrapes this raw shape, renames `srl_*` to canonical (`interface_*`, `bgp_*`) and `source` to `device`. Out the other side: the shared schema this workshop's dashboards and alerts speak.
- **`srl2` emits SNMP** — the classic shape from IF-MIB / BGP4-MIB. Field names like `ifOperStatus`, `ifHCInOctets`; tags like `agent_host`, `ifDescr`. **Telegraf-srl2** scrapes the raw SNMP shape and renames every field and every tag to the same canonical schema. Out the other side: byte-for-byte identical to what srl1 produces.

Both raw shapes live on `sonda-server` (the lab's synthetic-telemetry runtime). Each Telegraf scrapes its device's per-scenario `/metrics` endpoints on a 10-second cadence — same scrape pattern Prometheus would use against real exporters in production.

#### See the raw shape, before Telegraf touches it

> Your senior pulls up a terminal. *"You don't have to take the bullet list on faith. Each layer of the pipeline has its own URL — just click them and see the same fact in three different shapes."*

The pipeline has three layers you can inspect directly from your browser:

1. **Raw gNMI from srl1** (sonda-server, before Telegraf): <http://localhost:8085/metrics?label=source:srl1>

    Look for `srl_*` metric names and the `source="srl1"` tag. This is what an SR Linux device emits on its gNMI stream. For example:

    ```
    srl_interface_oper_state{collection_type="gnmi",name="ethernet-1/1",intf_role="peer",source="srl1"} 1
    ```

    The pack `workshops/autocon5/sonda/catalog/srlinux-gnmi-interfaces-raw.yaml` lists every metric in this shape.

2. **Raw SNMP from srl2** (sonda-server, before Telegraf): <http://localhost:8085/metrics?label=agent_host:srl2>

    Different shape entirely — IF-MIB names (`ifOperStatus`, `ifHCInOctets`) and the `agent_host="srl2"` tag. For example:

    ```
    ifOperStatus{agent_host="srl2",collection_type="snmp",ifDescr="ethernet-1/1"} 1
    ```

    Same logical concept (interface operational state) as srl1's `srl_interface_oper_state`, completely different field name, completely different label keys. Pack: `workshops/autocon5/sonda/catalog/cisco-snmp-interfaces-raw.yaml`.

3. **Telegraf-srl1's normalized output** (after gNMI → canonical rename): <http://localhost:9005/metrics>

    Now `srl_interface_oper_state` is plain `interface_oper_state`. The `source="srl1"` tag is now `device="srl1"`. Same data, canonical shape.

4. **Telegraf-srl2's normalized output** (after SNMP → canonical rename): <http://localhost:9006/metrics>

    `ifOperStatus` is now also `interface_oper_state`. The `agent_host="srl2"` tag is now `device="srl2"`. Identical structure to telegraf-srl1's output — except for one label we keep on purpose: `collection_type=gnmi` vs `collection_type=snmp`, so you can debug which pipeline a sample came from.

5. **Final view in Prometheus**: <http://localhost:9090/graph?g0.expr=interface_oper_state&g0.tab=1>

    A single PromQL query for `interface_oper_state` returns rows from both devices in the same shape. The vendor difference is invisible at this layer.

??? info "Why the sonda `/metrics` endpoint is safe for two readers at once"

    `sonda-server` exposes two shapes of metric endpoint: the **aggregate** `/metrics?label=key:value` you just used, and a **per-scenario** `/scenarios/{id}/metrics` for a single scenario by ID.

    - The aggregate endpoint is **snapshot-style**: each scrape gets a consistent picture without consuming anything. Telegraf reads it every 10 seconds; you can read it concurrently from your browser; both see the same bytes.
    - The per-scenario endpoint is **drain-on-read**: each read consumes the scenario's emission buffer. Telegraf doesn't use this endpoint precisely because two consumers can't share a drain-on-read buffer without racing.

    That difference is the production scrape architecture in miniature: **single-consumer endpoints drain, multi-consumer endpoints snapshot**. The aggregate endpoint is what Telegraf actually scrapes; the per-scenario endpoint is there for the scenario's own tooling.

Now flip to the Prometheus query browser and look at the same data after all the renames:

```promql
interface_oper_state{intf_role="peer"}
```

Six rows, all `interface_oper_state{device=..., name=..., intf_role="peer", ...}`. Same metric name, same label keys, regardless of whether the upstream was `srl_interface_oper_state{source=srl1}` or `ifOperStatus{agent_host=srl2}`. That's the rename rules in `telegraf-{srl1,srl2}.conf.toml` doing the lift.

The label that records which raw shape a series came from is `collection_type`. Run this once per device:

```promql
count by (collection_type) (interface_oper_state{device="srl1"})
```

You should see one row: `collection_type=gnmi` returning `3`.

```promql
count by (collection_type) (interface_oper_state{device="srl2"})
```

One row: `collection_type=snmp` returning `3`. Same metric, same number of series, different vendor shape upstream.

Now click into a result on each side and compare the full label set — `device`, `name`, `intf_role`, `collection_type`. The *only* meaningful difference is the `collection_type` value. Everything else lines up.

That alignment is what "normalization" actually buys you:

- The query layer doesn't see the dialects. `bgp_oper_state{device="srl1"}` and `bgp_oper_state{device="srl2"}` return rows in the same shape, even though one came in as gNMI and the other as SNMP.
- Real fleets are mixed. Nokia SR Linux via gNMI, Cisco IOS-XR via Model-Driven Telemetry, Juniper via OpenConfig, legacy boxes via SNMP — each speaks its own dialect. Without normalization, every dashboard, alert rule, and runbook fragments per vendor. With it, the *query layer* doesn't see the dialects at all.
- Telegraf is doing the renaming work for both devices in this lab. In production it might be Telegraf, OpenTelemetry collectors, custom processors — different tools, same job.

Prove the normalization holds end-to-end:

```promql
bgp_oper_state
```

Returns rows for *both* devices, *both* collection types. A dashboard panel querying `bgp_oper_state{device="$device"}` doesn't care which protocol delivered the data — it asks for the shared name and gets it.

> Your senior closes the laptop slightly. *"You'll meet engineers who hate normalization because it abstracts away vendor specifics. They're not wrong about the cost — but the cost of not normalizing, in this lab and in production, is that every alert rule has to be written six times and every dashboard has six panels for the same thing. Pick your trade. We've picked normalization."*

**Stop and notice.** The `collection_type` label is for inspecting the normalization itself: *"which raw shape did this sample come from, is that path healthy?"* It's not for branching your query logic. If you write `bgp_oper_state{collection_type="gnmi"}` into a dashboard, you've narrowed to one vendor — useful for debugging that pipeline, but you'll miss every device whose data arrives via any other protocol. Default to collection-type-agnostic queries; reach for the label when you're debugging the normalization, not the network.

#### 3. Rate of change on a counter

> *"Counters in Prometheus only ever go up. Reading them raw is useless. Show me the rate."*

```promql
rate(interface_in_octets{device="srl1"}[1m])
```

In the panel options on the right of Explore, switch from `Table` to `Time series`. You should see three lines, one per srl1 interface. The two healthy ones (`ethernet-1/1`, `ethernet-1/10`) hover around **~12,500 bytes/sec** — that's the synthetic emitter's `step_size` of 125 KB per 10s. `ethernet-1/11` (the broken interface) sits at **0 bytes/sec** — its counter doesn't tick because the interface is operationally down.

Now widen the window:

```promql
rate(interface_in_octets{device="srl1"}[5m])
```

The lines smooth out. The window inside the brackets is how much history `rate()` averages over — short windows are twitchy, long windows hide spikes.

> *"Throw in srl2 too — same query, no device filter."*

```promql
rate(interface_in_octets[5m])
```

Six lines now. srl2's healthy interfaces hit **~12,500 bytes/sec**, the broken `ethernet-1/11` flatlines at zero — same shape as srl1. Same query, same units, both vendor pipelines, no special-casing.

Now aggregate. What is the total inbound throughput per device?

```promql
sum by (device) (rate(interface_in_octets{name!~"mgmt0.*"}[5m])) * 8
```

`name!~"mgmt0.*"` excludes management interfaces. `sum by (device)` adds all interface rates together per device. `* 8` converts bytes/sec to bits/sec. Two rows — one per device, total inbound throughput.

**Stop and notice.** Anything that ends in `_octets`, `_packets`, `_total`, `_bytes` is a counter. Wrap it in `rate()` or `increase()`. Plotting a raw counter gives you a saw-tooth or a monotonic line that tells you nothing operationally. The window inside `rate()` controls smoothness — short windows are reactive, long windows hide spikes.

#### 4. Intent-vs-reality — interface metrics

> Your senior gestures at the screen. *"You've got the building blocks. Now answer an operational question: which peer interfaces are supposed to be up but aren't? You have everything you need — two metrics, one join."*

Two metrics encode the two sides of intent and reality:

- `interface_admin_state` — what the operator configured (1 = enabled)
- `interface_oper_state` — what the network is actually doing (1 = up, 2 = down)

Start with each side in isolation. First, which peer interfaces are admin-enabled?

```promql
interface_admin_state{intf_role="peer"} == 1
```

Now, which peer interfaces are operationally down?

```promql
interface_oper_state{intf_role="peer"} != 1
```

Join them — admin-enabled interfaces where oper state is not up:

```promql
interface_admin_state{intf_role="peer"} == 1
  and on (device, name)
interface_oper_state{intf_role="peer"} != 1
```

You should get one row per device — `ethernet-1/11` on each, the deliberately broken interface.

> Your senior nods. *"`and on (device, name)` joins only on the labels you name — device and interface name. Left side is intent (admin says enabled). Right side is reality (oper says not up). The result keeps the left side's value. Read it as: give me all admin-enabled peer interfaces, but only those where the same device + interface is also not operationally up. That's intent-vs-reality in one expression."*

**Stop and notice.** The pattern has three parts: a filter on the intent side, a filter on the reality side, and `and on (...)` naming the labels they share. The left side's value is preserved in the result. This shape generalises to any metric pair that encodes "what should be" and "what is" — the join clause is what makes it precise.

#### 5. Find the broken peer — BGP

> Your senior swivels toward you. *"Same pattern. Same join operator. Different metric pair. Apply it to BGP."*

```promql
bgp_oper_state != 1
  and on (device, peer_address)
bgp_admin_state == 1
```

You should get **exactly two rows**:

- `device=srl1, peer_address=10.1.99.2` — `bgp_oper_state` value is `5` (active, retrying)
- `device=srl2, peer_address=10.1.11.1` — `bgp_oper_state` value is `5`

> Your senior leans back in their chair. *"You just found two peers that have been in mismatch for weeks. Each has a `BgpSessionNotUp` alert that's been firing the whole time and nobody's owned it. Welcome to on-call. We're not going to fix them today; we're going to learn from them. The shape of the query you just ran is the shape of the alert that's been paging the rotation."*

**Stop and notice.** The only difference from exercise 4 is the metric names and the join labels — `and on (device, peer_address)` instead of `and on (device, name)`. The intent-vs-reality pattern is identical. This single query is the core of how the `BgpSessionNotUp` alert fires later in Part 3 — same shape, just with `for: 30s` wrapped around it.

### Recording rules — composed metrics

> Your senior opens a file. *"Every query you just wrote in Explore can be baked into Prometheus as a recording rule. Instead of recomputing it on every dashboard load, Prometheus evaluates it on a schedule and stores the result as a new metric. Dashboards and alerts reference the pre-computed name — fast, consistent, one definition."*

The naming convention is `<aggregation_labels>:<metric_name>:<time_window>`. This lab ships two traffic recording rules and one that fans a Loki-derived UPDOWN rate back into Prometheus:

```yaml
groups:
  - name: network_traffic_overview
    rules:
      - record: device:network_traffic_in_bps:rate_2m
        expr: sum(rate(interface_in_octets[2m])) by (device) * 8
      - record: device:network_traffic_out_bps:rate_2m
        expr: sum(rate(interface_out_octets[2m])) by (device) * 8

  - name: interface_updown_events
    rules:
      - record: device:interface_updown_rate:2m
        expr: events:interface_updown_rate:2m or (sum by (device) (interface_admin_state) * 0)
```

Try querying the pre-computed metric directly in Explore:

```promql
device:network_traffic_in_bps:rate_2m
```

Two rows — one per device, total inbound throughput in bits/sec, already computed. No `rate()`, no `sum by` needed at query time. The dashboard panel that shows device traffic references this name, not the raw expression.

**Stop and notice.** A recording rule is just a query that Prometheus runs on a schedule and stores. The result is a first-class metric — you can filter it, alert on it, and reference it from other rules. The naming convention is a readability contract, not a technical requirement: `aggregation:source_metric:window` tells you at a glance what the number represents and over what window it was computed.

### Alerts

> Your senior closes the rules file. *"A query answers a question. An alert is the same query with one addition: if the answer is true, act. That's all an alert rule is."*

#### The expression

Start from the intent-vs-reality query you already know. The operational question is: *"Alert when a peer interface is configured UP but operationally DOWN."*

```promql
count by (device, name) (
  (interface_admin_state{intf_role="peer"} == 1)
  and on (device, name)
  (interface_oper_state{intf_role="peer"} == 2)
) > 0
```

`> 0` is the firing condition — the alert fires whenever at least one interface matches. The `count by (device, name)` keeps the `device` and `name` labels in the alert so the notification knows *which* interface.

#### The rule

Wrap the expression in an alert rule and add three things that make it operationally useful:

```yaml
groups:
  - name: interface_intent_mismatch
    rules:
      - alert: InterfaceAdminUpOperDown
        expr: |
          count by (device, name) (
            (interface_admin_state{intf_role="peer"} == 1)
            and on (device, name)
            (interface_oper_state{intf_role="peer"} == 2)
          ) > 0
        for: 2m
        labels:
          severity: warning
          category: network
        annotations:
          summary: "Interface intent mismatch detected"
          description: |
            Interface {{ $labels.name }} on device {{ $labels.device }}
            is configured as UP (admin state) but is currently DOWN (oper state).

            This usually indicates a cabling, peer, or physical-layer issue.
```

- **`for: 2m`** — the condition must hold for 2 minutes before the alert fires. Filters out flap noise.
- **`labels:`** — static key-value pairs attached to the alert. `severity` and `category` are what Alertmanager routes on in Part 3.
- **`annotations:`** — human-readable context. `{{ $labels.name }}` and `{{ $labels.device }}` are template variables that expand to the alert's label values — the notification tells you exactly which interface on which device.

#### Lab: see this alert in the stack

The `InterfaceAdminUpOperDown` alert is already loaded. The lab's deliberately broken interfaces (`ethernet-1/11` on both devices) satisfy the expression right now.

1. **Prometheus** — open [http://localhost:9090/#/alerts](http://localhost:9090/#/alerts) and find `InterfaceAdminUpOperDown`. It should be in `FIRING` state with one entry per device.

2. **Grafana Explore** — the `ALERTS` metric exposes firing alerts as a queryable time series:

    ```promql
    ALERTS{alertname="InterfaceAdminUpOperDown"}
    ```

    Each row is a firing instance. The label set is the alert's labels merged with the expression's output labels — `device`, `name`, `severity`, `category` all present.

3. **Alertmanager** — open [http://localhost:9093](http://localhost:9093) and confirm the alert arrived and was routed. In Part 3 you'll trace exactly what happens next.

**Stop and notice.** The alert rule you just read is the same intent-vs-reality query from exercise 4, with `> 0`, `for:`, `labels:`, and `annotations:` added. The query is the logic; everything else is operational scaffolding — how long to wait before paging, what labels to route on, what message to show on call. This is the pattern every alert in this lab follows.

### Logs — LogQL

> Your senior pushes back from the desk. *"OK, you've got a sense of the metric shape. Now: when something looks wrong in metrics, you need to find a log line that explains it. Logs are where the why lives. Same lab, different query language. Switch the datasource."*

Switch the Explore datasource to `loki`.

#### 6. Stream selection

```logql
{device="srl1"}
```

Run it. You'll see a stream of recent log lines from `srl1`. The dropdown on the right lets you switch between log view and table view.

**Stop and notice.** Curly braces with label selectors look like Prometheus, but they pick *log streams*, not metric series. A LogQL query always starts with `{...}`. Without label selectors Loki doesn't know what to query.

#### 7. Line filter

```logql
{device="srl1"} |~ "BGP"
```

`|~` is regex match against the log line body. Try a few:

```logql
{device="srl1"} |~ "Interface"
{device="srl1"} != "DEBUG"
```

`|=`, `!=`, `|~`, `!~` are the four line-filter operators (substring match, substring exclude, regex match, regex exclude). Stack as many as you want.

**Stop and notice.** Stream selectors filter *which streams* Loki reads. Line filters filter *which lines* inside those streams. Always narrow the streams first — line filters scan, stream selectors index.

#### 8. JSON parse

Sonda emits structured logs. You can query parsed fields, not just substrings:

```logql
{device="srl1"} | json | severity="warn"
```

The `| json` stage parses each line as JSON; `| severity="warn"` filters on a parsed field. Try:

```logql
{device="srl1"} | json | line_format "{{.severity}} {{.message}}"
```

`line_format` is a template over parsed fields — it reshapes how each line is displayed.

**Stop and notice.** Structured logs let you query and reshape; unstructured logs force regex against text. The pipelines in this lab emit JSON on purpose.

#### 9. Aggregation — log queries that produce metrics

Aggregating logs over time turns a log query into a metric:

```logql
sum by (device) (count_over_time({vendor_facility_process="UPDOWN"}[5m]))
```

Switch the panel to `Time series`. You should see two lines (one per device) showing UPDOWN events per 5-minute window. With the lab in steady state the count sits at **a handful per device** — sonda emits a slow trickle, well below the `PeerInterfaceFlapping` alert's `> 3 events in 2 minutes` threshold.

**Stop and notice.** This is exactly how the `PeerInterfaceFlapping` alert reads logs in Part 3 — same shape, just with a `> 3` threshold and a `for: 30s` clause. Any LogQL aggregation query is a candidate alert rule.

??? tip "Want to see the line jump now?"

    If you're running ahead or want to verify the query before the capstone, trigger a quick flap: `nobs autocon5 flap-interface --device srl1 --interface ethernet-1/10`. Within ~30 seconds the `srl1` line climbs. The capstone exercise (12) drives a full cascade that will show this too — no need to run it twice.

#### 10. Pipeline awareness on logs

The same normalization story plays out on the log side, with one important difference from metrics: logs don't go through Telegraf. Telegraf is a metrics pipeline — it scrapes and normalizes time-series samples. Logs are a different data shape (timestamped text streams), so the lab uses a dedicated log shipper instead: **Vector** for `srl2`, and a direct push path for `srl1`.

`srl1` emits structured logs directly to Loki — that's the **normalized log**, `pipeline=direct`. `srl2` emits raw RFC 5424 syslog over UDP to Vector; Vector parses the syslog, extracts SD-IDs, and rewrites them into the same label vocabulary `srl1` already uses — that's the same log **still being processed to become normalized**, `pipeline=vector`.

```logql
count by (pipeline) (count_over_time({device="srl1"}[5m]))
count by (pipeline) (count_over_time({device="srl2"}[5m]))
```

Returns `pipeline=direct` and `pipeline=vector` respectively. Now run a query that doesn't pin the pipeline:

```logql
{vendor_facility_process="UPDOWN"}
```

You should see streams from both devices. The `device`, `vendor_facility_process`, `interface`, `severity` labels look identical — Vector did the work to make `srl2`'s raw syslog land in Loki with the same shape `srl1`'s structured logs already have. Same normalization story, log edition.

**Stop and notice.** Two normalization stories in this lab — `collection_type=gnmi/snmp` on metrics, `pipeline=direct/vector` on logs — but they share the same payoff: queries don't have to know which transport delivered the signal. The label that tags the source path exists for *debugging* the pipeline, not for *branching* your queries.

### The bridge — metric to log

> Your senior looks over. *"This is the move that pays off most often under pressure. Find the broken thing in metrics, then jump to logs with the same labels and read the why. If you only remember one thing from this morning, remember this."*

#### 11. Why is the peer down?

This is the payoff exercise. Use the broken-peer query from #5 to find a mismatched peer, then jump to logs to find out *why*.

In the `prometheus` datasource:

```promql
bgp_oper_state{device="srl1"} != 1
  and on (device, peer_address)
bgp_admin_state{device="srl1"} == 1
```

On a clean lab, this returns **one row** — `peer_address=10.1.99.2`, value `5` (active, retrying). That's the deliberately broken peer.

??? info "Seeing more than one row? Check the query type."

    Grafana Explore's default is **Range** (plots samples over the time window). If a flap or cascade has run inside the window, peers that were briefly `oper_state != 1` will appear as series even after they've recovered. Switch the **Type** dropdown next to the query to **Instant** for a "right now" snapshot — that should drop you back to one row.

??? tip "Or — Prometheus is carrying stale data from a previous session"

    `nobs autocon5 up` reattaches to an existing Prometheus volume if one exists, so historical samples from earlier sessions linger. `nobs autocon5 destroy && nobs autocon5 up` gives a true clean slate. (`nobs autocon5 reset` clears scenarios and maintenance but leaves the Prometheus TSDB intact.)

Switch to the `loki` datasource:

```logql
{device="srl1", peer_address="10.1.99.2"}
```

You'll see BGP-related lines for that specific peer. Add a filter to narrow:

```logql
{device="srl1", peer_address="10.1.99.2"} |~ "BGP"
```

**Stop and notice.** Metrics told you *something* is wrong (admin says up, oper says down). Logs tell you *why* (peer didn't reply, fsm transition, whatever the message says). The labels are the same on both sides — that's what makes correlation cheap. This is the single most important pattern in the entire workshop. Every dashboard panel you'll build in Part 2, every alert path in Part 3, leans on this metric-to-log bridge.

> *"Same query shape works on srl2 — try it. Different `peer_address`, same answer-the-why pattern. The fact that one device's metric came in as gNMI and the other's came in as SNMP doesn't change the bridge query at all."*

## Capstone — everything at once

#### 12. Trigger a cascade and watch metrics, logs, and alerts react

> Your senior gestures at the keyboard. *"You've now seen metrics, normalization, recording rules, alerts, and logs as separate concepts. This exercise puts them all on screen at the same time. One command, one cascade — you watch every layer respond in causal order."*

This is the capstone exercise for Part 1. Open four browser tabs before you run anything:

| Tab | What to open |
|-----|-------------|
| Metrics | Grafana Explore — `prometheus` datasource |
| Logs | Grafana Explore — `loki` datasource |
| Alerts | [Prometheus alerts](http://localhost:9090/#/alerts) |
| Alertmanager | [http://localhost:9093](http://localhost:9093) |

**Step 1 — set up your metric queries.** In the metrics tab, load these four queries (use split view or separate tabs):

```promql
interface_oper_state{device="srl1", name="ethernet-1/1"}
```

```promql
bgp_oper_state{device="srl1", peer_address="10.1.2.2"}
```

```promql
bgp_prefixes_accepted{device="srl1", peer_address="10.1.2.2"}
```

```promql
rate(interface_in_octets{device="srl1", name="ethernet-1/1"}[1m]) * 8 / 1000
```

Switch all four to `Time series` view. Leave them running — Grafana auto-refreshes.

**Step 2 — set up your log stream.** In the logs tab, run:

```logql
{device="srl1", vendor_facility_process="UPDOWN"}
```

Switch to `Live` mode (the toggle in the top-right of Explore). Log lines will stream in as they arrive.

**Step 3 — trigger the cascade.** In a terminal:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

One command posts a 4-minute cascade to sonda: the interface flaps on a 30s-up / 60s-down cadence, BGP follows after a 10s hold-down, and every signal snaps back cleanly when the gate closes.

??? tip "Trip just the flap, not BGP"

    Pass `--no-cascade` and only the interface metric and UPDOWN log stream fire — BGP stays clean. Useful for testing the `PeerInterfaceFlapping` alert without bringing a session down.

**Step 4 — watch each layer respond in order.**

*Metrics:*

- `interface_oper_state` flips from `1` → `2` immediately when the interface goes down.
- ~10 seconds later, `bgp_oper_state` follows from `1` → `2` (BGP hold-down timer).
- `bgp_prefixes_accepted` drops to `0` on the same beat.
- Interface traffic drops to `0 kb/s` during each DOWN phase. Here's the chain of cause and effect:
    - `rate()` measures how fast the byte counter is going up.
    - During DOWN, no traffic is flowing through the interface, so no bytes get added to the counter.
    - The counter itself doesn't disappear — it just sits at whatever number it had reached when the interface went down.
    - When the interface comes back up, traffic starts flowing again and the counter picks up where it left off — no fake spike, no false alarm.
- When the interface recovers, every gated series snaps back: `bgp_oper_state` → `1`, prefix counters → `10`. Dashboards go green within one scrape cycle.

*Logs:*

UPDOWN log lines start appearing in the live stream within seconds of the first down phase. Each line carries the same `device`, `interface`, and `vendor_facility_process` labels as the metrics — that label alignment is what makes the bridge exercise possible.

*Alerts:*

- After ~30 seconds in the down state, check the Prometheus alerts page. You should see `PeerInterfaceFlapping` move from `INACTIVE` → `PENDING` → `FIRING` as the UPDOWN event count crosses the threshold and holds for `for: 30s`.
- Once `FIRING`, switch to Alertmanager — the alert arrives there routed by its `severity` and `category` labels. In Part 3 you'll trace exactly what the webhook does with it.

**Stop and notice.** Everything you used today is on screen at the same time: a metric query (interface state), a causal chain (interface → BGP → prefixes), a log stream with matching labels, a recording rule feeding the alert expression, and an alert firing and routing. Each layer was a separate concept earlier in Part 1. Under pressure at 2am, this is the view you'll have open — and every piece of it is a query you now know how to write.

## Stretch goals (optional — pick one if you have time)

- **Find the busiest interface in the last 5 minutes.** Combine `topk` with `rate()` on `interface_in_octets`. Which interfaces show up?

    ??? success "Solution — the query + what it returns"

        ```promql
        topk(3, rate(interface_in_octets[5m]))
        ```

        Three rows, one per "busiest" interface across both devices:

        ```
        srl2 / ethernet-1/10    ~12,700 bytes/sec
        srl2 / ethernet-1/1     ~12,700 bytes/sec
        srl1 / ethernet-1/1     ~12,700 bytes/sec
        ```

        At rest the synthetic emitter ticks every healthy interface at roughly the same `step_size`, so the three winners are essentially tied — `topk` picks 3 of them somewhat arbitrarily. Drive a flap (`nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1`) and the broken/flapping interface stops contributing during DOWN phases — the result list changes accordingly.

- **List every distinct severity level present in srl1 logs in the last hour.** What does the lab actually seed?

    ??? success "Solution — the query + three severity buckets"

        Parse the lines with `| json` then aggregate by the parsed field:

        ```logql
        sum by (severity) (count_over_time({device="srl1"} | json [1h]))
        ```

        Three rows fall out:

        | severity | count (varies, ballpark) |
        |---|---|
        | `info`  | ~120 (BGP state changes, link UP events) |
        | `warn`  | ~70 (broken peer retries, admin-up/oper-down events) |
        | `error` | ~15 (BGP neighbor "connection refused" lines) |

        The lab seeds three severity buckets on purpose — `info` is the baseline noise, `warn` is the steady-state broken-interface emission, `error` is what the broken peer actively produces. In a real network the distribution looks similar: most lines are routine, a fraction are warnings about expected state, and a smaller fraction are errors worth paging on.

- **Run the broken-peer query against srl2 only.** Same shape as exercise 5 (the intent-vs-reality BGP query), but scoped to one device. Confirm you get exactly one row.

    ??? success "Solution — the query + the one row it returns"

        ```promql
        bgp_admin_state{device="srl2"} == 1
          and on (device, peer_address)
        bgp_oper_state{device="srl2"} != 1
        ```

        Returns exactly one row:

        ```
        bgp_admin_state{device="srl2", peer_address="10.1.11.1", ...} = 1
        ```

        That's srl2's deliberately broken peer — admin says "should be up", oper says it isn't. Same shape as srl1's broken peer (`10.1.99.2` from exercise 5), just on the SNMP-shape device. The intent-vs-reality pattern is device-shape-agnostic because the normalization step gives both pipelines the same metric names and labels.

- **Plot CPU and memory side by side.** Two queries in one Explore panel — what should both lines look like at rest?

    ??? success "Solution — the queries + expected ranges"

        ```promql
        cpu_used{device="srl1"}
        ```

        ```promql
        memory_utilization{device="srl1"}
        ```

        Both metrics are sine waves the synthetic emitter produces:

        - `cpu_used{device="srl1"}` ≈ 10–40% (amplitude 15, offset 25, period 120s)
        - `memory_utilization{device="srl1"}` ≈ 34–50% (amplitude 8, offset 42, period 240s)

        Both lines sit comfortably below any operationally interesting threshold — the lab seeds these as "the box is healthy" baseline so you can compare them against the genuinely interesting interface/BGP signals. If either climbed into the 80–90% range, that'd be a "device itself is unhealthy" signal worth investigating (we ruled this out at the top of Act 2 in Advanced exactly for this reason).

- **Inspect the raw shape Telegraf normalizes.** Compare the three layers of the pipeline directly — what does the same fact look like before Telegraf, after Telegraf, and after Prometheus has stored it?

    ??? success "Solution — three URLs walking the same fact through three shapes"

        Click each URL and grep for one specific metric:

        - <http://localhost:8085/metrics?label=agent_host:srl2> — raw SNMP (pre-Telegraf): `bgpPeerState`, `ifHCInOctets`, `agent_host=srl2`
        - <http://localhost:9006/metrics> — telegraf-srl2's normalized output: `bgp_oper_state`, `interface_in_octets`, `device=srl2`
        - <http://localhost:9090/graph?g0.expr=bgp_oper_state%7Bdevice%3D%22srl2%22%7D&g0.tab=1> — Prometheus stores the same data after one more scrape hop

        For one line of `bgp_active_routes` on srl2, you'll see roughly:

        | Layer | What it looks like |
        |---|---|
        | Sonda raw (before Telegraf) | `bgpPeerInPrefixes{agent_host="srl2", bgpPeerRemoteAddr="10.1.11.1", ...} 10` |
        | Telegraf `/metrics` (after rename) | `bgp_active_routes{collection_type="snmp", device="srl2", peer_address="10.1.11.1", ..., pipeline="telegraf"} 10` |
        | Prometheus (after one more scrape) | identical to the line above — Prometheus just stores it |

        Same number (`10`), same physical fact (this peer has 10 active routes), three different shapes depending on which layer you sample at. The rename ruleset that bridges them lives in `telegraf/telegraf-srl2.conf.toml` — `tag.source → device`, `bgpPeerRemoteAddr → peer_address`, plus the metric-name rewrites. The point of the exercise is to convince yourself that "normalization" isn't a black box — it's a config file you can read.

## What you took away

- You now know what "normal" looks like in this network. That baseline is what every triage in your future is going to compare against.
- Every metric is `name + labels + value`. Aggregations collapse labels you don't list.
- Counters need `rate()`. The window inside the brackets controls smoothness.
- Intent-vs-reality is two clauses joined by `and on (...)` — the workshop's broken peers are caught by exactly that shape.
- Recording rules pre-compute expensive aggregations into new metric names (`aggregation:metric:window`). Query the recording rule, not the raw counter — it's faster and already aligned with the alert threshold.
- Alert rules are just PromQL expressions plus a `for:` duration and a set of labels and annotations. When the expression returns results for longer than `for:`, the alert fires. The lifecycle is INACTIVE → PENDING → FIRING.
- LogQL stream selectors look like PromQL but pick log streams. Line filters narrow inside those streams.
- `count_over_time({...}[N])` turns a log query into a metric — same pattern any LogQL alert rule uses.
- Same labels on metrics and logs means correlation is one query change away. Metric tells you *what*; log tells you *why*.
- A real incident moves through all three layers at once: the metric catches the anomaly first, the log explains the event, the alert fires when the anomaly persists. The capstone exercise walked you through that chain live.
- Two normalization stories on this lab — `collection_type=gnmi/snmp` on metrics, `pipeline=direct/vector` on logs. The label that records the source pipeline exists for inspecting the normalization itself; default to pipeline-agnostic queries and reach for the label only when you're debugging the path, not the network.
