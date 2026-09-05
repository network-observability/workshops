# Part 1 — Network telemetry and queries

## What you'll do here

It's Monday morning. You just rotated onto the on-call team for your company's network observability platform and today is your first deep day. You've got coffee. Your senior buddy is leaning on the desk next to you, laptop open. They're going to walk you through the lab over the next 55 minutes — what "normal" looks like, where the broken things hide, how to bridge from a metric anomaly to a log line that explains it. From tomorrow you'll be primary on the rotation, so today the goal is simple: build a baseline mental model of this network so every future triage has something to compare against.

Write PromQL and LogQL by hand against the running lab. Discover the metric schema, find the deliberately broken BGP peer with a single intent-vs-reality query, and correlate metrics to logs to explain *why* a session is down. By the end you'll know enough query syntax to read any dashboard in this workshop.

This part is the longest block of the session on purpose — every later part depends on you being comfortable in the query bar.

## Setup check

Your senior already has Grafana up on their screen. They've reset the lab to known-good baseline and confirmed every row says `ok`. Your turn.

If this is your first time bringing up the lab solo, run the four-command **Bring it up** sequence from the workshop README first (`uv sync --all-packages` → `nobs setup` → `nobs packt up` → `nobs packt load-infrahub`) — `nobs packt up` alone doesn't seed Infrahub, and `reset` will fail with `SchemaNotFoundError` until `load-infrahub` has run once.

In a terminal:

```bash
nobs packt reset
nobs packt status
```

`reset` is safe to run repeatedly — it clears any leftover maintenance flags, expires any silences from a prior workshop run, removes any cascade scenarios still hanging around, and restarts the log shipper if it has gone quiet. Safe to run at the start of every part. `status` then confirms every row reports `ok`. If `prometheus`, `loki`, or `sonda` is anything else, flag it before continuing — your senior wants to know about a degraded stack before you lean on it.

Open Grafana at <http://localhost:3000> (login `admin` / `admin` unless you changed `.env`). On the very first login you'll see two pop-ups — click **Skip** on the "change password" prompt and the **×** on the "Grafana Assistant is now available" what's-new modal. Both are unrelated to the workshop. Then click the compass icon in the left rail to open **Explore**. The datasource picker at the top is how you switch between Prometheus and Loki. You'll bounce between them throughout this part.

Open the **Workshop Home** dashboard once (`/d/workshop-home`) so you've seen the stat row — Devices, Interfaces, Firing alerts, Log lines (5m). Those four numbers are your sanity check throughout the workshop.

## The exercises

### Metrics — PromQL

> Your senior taps the screen. *"Before we touch anything else this morning, you need to know what's even talking to us — and what shape it arrives in. Two devices, two telemetry dialects on the wire, and yet every query you write today is going to treat them as one shape. Let's start at the source, before any of it is cleaned up. This is the part that bites every operator who jumps from one vendor's network to another."*

#### 1. Normalization — two raw shapes, one shared schema

The two devices speak different protocols at the source:

- **`srl1` emits gNMI** — that's the telemetry shape SR Linux puts on the wire natively. Field names like `srl_interface_oper_state`, tags like `source`. **Telegraf-srl1** scrapes this raw shape, renames `srl_*` to canonical (`interface_*`, `bgp_*`) and `source` to `device`. Out the other side: the shared schema this workshop's dashboards and alerts speak.
- **`srl2` emits SNMP** — the classic shape from IF-MIB / BGP4-MIB. Field names like `ifOperStatus`, `ifHCInOctets`; tags like `agent_host`, `ifDescr`. **Telegraf-srl2** scrapes the raw SNMP shape and renames every field and every tag to the same canonical schema. Out the other side: byte-for-byte identical to what srl1 produces.

Both raw shapes live on `sonda-server` (the lab's synthetic-telemetry runtime). Each Telegraf scrapes its device's per-scenario `/scenarios/metrics` endpoints on a 10-second cadence — same scrape pattern Prometheus would use against real exporters in production.

#### See the raw shape, before Telegraf touches it

> Your senior pulls up a terminal. *"You don't have to take the bullet list on faith. Each layer of the pipeline has its own URL — just click them and see the same fact in three different shapes."*

The pipeline has three layers you can inspect directly from your browser:

1. **Raw gNMI from srl1** (sonda-server, before Telegraf): <http://localhost:8085/scenarios/metrics?label=source:srl1>

    Look for `srl_*` metric names and the `source="srl1"` tag. This is what an SR Linux device emits on its gNMI stream. For example:

    ```
    srl_interface_oper_state{collection_type="gnmi",name="ethernet-1/1",intf_role="peer",source="srl1"} 1
    ```

    The pack `workshops/packt/sonda/catalog/srlinux-gnmi-interfaces-raw.yaml` lists every metric in this shape.

2. **Raw SNMP from srl2** (sonda-server, before Telegraf): <http://localhost:8085/scenarios/metrics?label=agent_host:srl2>

    Different shape entirely — IF-MIB names (`ifOperStatus`, `ifHCInOctets`) and the `agent_host="srl2"` tag. For example:

    ```
    ifOperStatus{agent_host="srl2",collection_type="snmp",ifDescr="ethernet-1/1"} 1
    ```

    Same logical concept (interface operational state) as srl1's `srl_interface_oper_state`, completely different field name, completely different label keys. Pack: `workshops/packt/sonda/catalog/cisco-snmp-interfaces-raw.yaml`.

3. **Telegraf-srl1's normalized output** (after gNMI → canonical rename): <http://localhost:9005/metrics>

    Now `srl_interface_oper_state` is plain `interface_oper_state`. The `source="srl1"` tag is now `device="srl1"`. Same data, canonical shape.

4. **Telegraf-srl2's normalized output** (after SNMP → canonical rename): <http://localhost:9006/metrics>

    `ifOperStatus` is now also `interface_oper_state`. The `agent_host="srl2"` tag is now `device="srl2"`. Identical structure to telegraf-srl1's output — except for one label we keep on purpose: `collection_type=gnmi` vs `collection_type=snmp`, so you can debug which pipeline a sample came from.

5. **Final view in Prometheus**: <http://localhost:9090/graph?g0.expr=interface_oper_state&g0.tab=1>

    A single PromQL query for `interface_oper_state` returns rows from both devices in the same shape. The vendor difference is invisible at this layer.

??? info "Why the sonda `/scenarios/metrics` endpoint is safe for two readers at once"

    `sonda-server` exposes two shapes of metric endpoint: the **aggregate** `/scenarios/metrics?label=key:value` you just used, and a **per-scenario** `/scenarios/{id}/metrics` for a single scenario by ID.

    - The aggregate endpoint is **snapshot-style**: each scrape gets a consistent picture without consuming anything. Telegraf reads it every 10 seconds; you can read it concurrently from your browser; both see the same bytes.
    - The per-scenario endpoint is **drain-on-read**: each read consumes the scenario's emission buffer. Telegraf doesn't use this endpoint precisely because two consumers can't share a drain-on-read buffer without racing.

    That difference is the production scrape architecture in miniature: **single-consumer endpoints drain, multi-consumer endpoints snapshot**. The aggregate endpoint is what Telegraf actually scrapes; the per-scenario endpoint is there for the scenario's own tooling.

Now flip to the Prometheus query browser and look at the same data after all the renames:

```promql
interface_oper_state{intf_role="peer"}
```

Six rows, all `interface_oper_state{device=..., name=..., intf_role="peer", ...}`. Same metric name, same label keys, regardless of whether the upstream was `srl_interface_oper_state{source=srl1}` or `ifOperStatus{agent_host=srl2}`. That's the rename rules in `telegraf-{srl1,srl2}.conf.toml` doing the lift.

But look closer at the filter you just ran. `interface_oper_state` and `device` are *renames* — the raw stream already carried that fact (`srl_interface_oper_state`, `source=srl1`), Telegraf just relabelled it to the canonical schema. `intf_role="peer"`, though, is a label that *did not exist on the wire at all*. No SR Linux gNMI message and no SNMP MIB emits an "interface role." Telegraf derives it from the interface name with a regex processor (`telegraf-{srl1,srl2}.conf.toml`, the `[[processors.regex]]` block with `result_key = "intf_role"`). That's a second, distinct operation:

- **Normalization** — *renaming* what's already there to a shared shape. `srl_interface_oper_state` → `interface_oper_state`, `source` → `device`. No new facts, just a common vocabulary. Lossless and mechanical.
- **Enrichment** — *adding* context the device never sent. `intf_role="peer"` is inferred here from the name; in a real fleet it more often comes from a source of truth (which interface is a peer link, which site a device sits in, who owns it). New facts, joined in at ingest.

You filter on both kinds of label the same way in PromQL — `{device="srl1"}` (normalized) and `{intf_role="peer"}` (enriched) read identically. The difference is in *where the value came from*: one was renamed off the wire, the other was attached by the pipeline. Keep the two straight, because they fail differently — a broken rename means a vendor's data goes missing from a query; broken enrichment means the data is all there but you can't slice it by the business context you expected. (Part 3 leans hard on enrichment: alerts get routed and annotated using exactly this kind of source-of-truth context.)

The one label that records which raw shape a series came from is `collection_type` — `gnmi` for srl1, `snmp` for srl2. Click into a srl1 result and a srl2 result and compare the full label set — `device`, `name`, `intf_role`, `collection_type`. The *only* meaningful difference is the `collection_type` value. Everything else lines up: same metric name, same label keys, three peer interfaces on each side. The same fact two vendor dialects were carrying, now expressed once.

That alignment is what "normalization" actually buys you:

- The query layer doesn't see the dialects. `interface_oper_state{device="srl1"}` and `interface_oper_state{device="srl2"}` return rows in the same shape, even though one came in as gNMI and the other as SNMP.
- Real fleets are mixed. Nokia SR Linux via gNMI, Cisco IOS-XR via Model-Driven Telemetry, Juniper via OpenConfig, legacy boxes via SNMP — each speaks its own dialect. Without normalization, every dashboard, alert rule, and runbook fragments per vendor. With it, the *query layer* doesn't see the dialects at all.
- Telegraf is doing the renaming work for both devices in this lab. In production it might be Telegraf, OpenTelemetry collectors, custom processors — different tools, same job.

> Your senior closes the laptop slightly. *"You'll meet engineers who hate normalization because it abstracts away vendor specifics. They're not wrong about the cost — but the cost of not normalizing, in this lab and in production, is that every alert rule has to be written six times and every dashboard has six panels for the same thing. Pick your trade. We've picked normalization."*

**Stop and notice.** The `collection_type` label is for inspecting the normalization itself: *"which raw shape did this sample come from, is that path healthy?"* It's not for branching your query logic. If you write `interface_oper_state{collection_type="gnmi"}` into a dashboard, you've narrowed to one vendor — useful for debugging that pipeline, but you'll miss every device whose data arrives via any other protocol. Default to collection-type-agnostic queries; reach for the label when you're debugging the normalization, not the network.

#### 2. Discover what's in the lab

You've watched the metric get *built* — raw dialects in, one canonical shape out. Now work with the finished article. Switch to Grafana **Explore**, pick the `prometheus` datasource, and run the bare metric with no filter:

```promql
interface_oper_state
```

Click `Run query`. **You should see exactly 6 results** — three interfaces per device, two devices, both collection types, all in the same shape. That one query returning rows for both vendors *is* the normalization paying off end-to-end: a dashboard panel querying `interface_oper_state{device="$device"}` doesn't care which protocol delivered the data — it asks for the shared name and gets it.

Click any row's labels and the inspector shows the full label set:

- `device` — `srl1` or `srl2`
- `name` — interface name (`ethernet-1/1`, `ethernet-1/10`, `ethernet-1/11`)
- `intf_role` — `peer` for the three real ones
- `collection_type` — `gnmi` (srl1) or `snmp` (srl2)
- `pipeline` — `telegraf` (both devices route through Telegraf today)
- `host`, `instance`, `job` — where Prometheus scraped from

**Stop and notice.** The metric *name* tells you what (operational state of an interface). The *labels* tell you which one and where it came from — some renamed off the wire, some enriched in, as you just traced. Every query you write from now on is a filter or aggregation on labels.

Now try an aggregation. How many peer interfaces are operationally up per device?

```promql
count by (device) (interface_oper_state{intf_role="peer"} == 1)
```

`== 1` filters to only up interfaces (1 = UP, 2 = DOWN). `count by (device)` collapses every label *except* `device` — list the labels you want to keep and everything else flattens. You should see `srl1` returning `2` and `srl2` returning `2` — two healthy peer interfaces per device, with one down on each.

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

The same normalization idea applies to BGP session state. `bgp_oper_state` and `bgp_admin_state` are collected from both devices — one via gNMI, one via SNMP — and normalized into the same metric names with the same label set. That matters here because the on-call alert covers the whole fleet: if the query had to branch by vendor, a broken peer on a device using the other collection path would silently slip through.

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

Switch the panel to `Time series`. You should see two lines (one per device) showing UPDOWN events per 5-minute window. With the lab in steady state the count sits at **a handful per device** — sonda emits a slow trickle.

**Stop and notice.** This is the bridge between logs and alerting. Raw log lines are strings — you can search them, but you can't alert on them directly. Aggregating them over time produces a number, and a number can be compared against a threshold in an alert rule. Any LogQL aggregation query — count of error lines, rate of state changes, volume of dropped packets per device — is a candidate alert rule. Logs stop being a post-mortem tool and become part of your real-time detection layer.

??? tip "Want to see the line jump now?"

    If you're running ahead or want to verify the query, trigger a quick flap: `nobs packt flap-interface --device srl1 --interface ethernet-1/10`. Within ~30 seconds the `srl1` line climbs.

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

#### 11. The bridge — metric to log

> Your senior looks over. *"This is the move that pays off most often under pressure. Find the broken thing in metrics, then jump to logs with the same labels and read the why. If you only remember one thing from this morning, remember this."*

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

    `nobs packt up` reattaches to an existing Prometheus volume if one exists, so historical samples from earlier sessions linger. `nobs packt destroy && nobs packt up` gives a true clean slate. (`nobs packt reset` clears scenarios and maintenance but leaves the Prometheus TSDB intact.)

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

## Your turn (10 minutes)

Two questions. The first one everybody should get; the second is there if you finish early. Everything you need is in the exercises above — no new syntax.

!!! question "Basic — which peer is broken, and since when?"

    `srl1` has three configured BGP peers. One of them is not `ESTABLISHED`.

    1. Write a **PromQL** query that returns just the broken peer — not all three, not a manual `!=` on an address you already know. Use the intent-vs-reality shape from exercise 5, so the query would still find the right peer if a different one broke tomorrow.
    2. Then write the **LogQL** line that explains *why* it is down. Same labels, other datasource — the bridge from exercise 11.
    3. Read the timestamp on that log line. How long has this peer been down?

    You should end up with one peer address, one log message, and one answer to "since when". If your PromQL returns three rows, you are describing the peers rather than comparing intent against reality.

!!! question "Stretch — catch the same event on a counter"

    The bridge query above finds the event in the logs. Find it in the *metrics* instead, on a counter rather than a gauge.

    Write a **rate-of-change** query (exercise 3's shape) over a counter that moves when this peer's session breaks or its interface flaps — and pick a range window that makes the event visible rather than smoothing it away. Two peers on the same device give you a control: the broken one should look different from the healthy ones on the same graph.

    Worth noticing when you have it: the gauge tells you the *state* right now, the counter tells you *how often it changed*. Part 2's alert threshold is set on the second one, not the first.

**Post your answers in the Q&A panel** — we will read a couple of them out before the break, including any query that found a shape we did not expect.

## What you took away

- You now know what "normal" looks like in this network. That baseline is what every triage in your future is going to compare against.
- Every metric is `name + labels + value`. Aggregations collapse labels you don't list.
- Counters need `rate()`. The window inside the brackets controls smoothness.
- Intent-vs-reality is two clauses joined by `and on (...)` — the workshop's broken peers are caught by exactly that shape.
- LogQL stream selectors look like PromQL but pick log streams. Line filters narrow inside those streams.
- `count_over_time({...}[N])` turns a log query into a metric — same pattern any LogQL alert rule uses.
- Same labels on metrics and logs means correlation is one query change away. Metric tells you *what*; log tells you *why*.
- Two normalization stories on this lab — `collection_type=gnmi/snmp` on metrics, `pipeline=direct/vector` on logs. The label that records the source pipeline exists for inspecting the normalization itself; default to pipeline-agnostic queries and reach for the label only when you're debugging the path, not the network.
