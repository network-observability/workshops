# Part 1 — Network telemetry and queries

## What you'll do here

It's Monday morning. You just rotated onto the on-call team for your company's network observability platform and today is your first deep day. You've got coffee. Your senior buddy is leaning on the desk next to you, laptop open. They're going to walk you through the lab over the next 55 minutes — what "normal" looks like, where the broken things hide, how to bridge from a metric anomaly to a log line that explains it. From tomorrow you'll be primary on the rotation, so today the goal is simple: build a baseline mental model of this network so every future triage has something to compare against.

Write PromQL and LogQL by hand against the running lab. Discover the metric schema, find the deliberately broken BGP peer with a single intent-vs-reality query, and correlate metrics to logs to explain *why* a session is down. By the end you'll know enough query syntax to read any dashboard in this workshop.

This part is the longest block of the session on purpose — every later part depends on you being comfortable in the query bar.

## Setup check

Your senior already has Grafana up on their screen. They've reset the lab to known-good baseline and confirmed every row says `ok`. Your turn.

If this is your first time bringing up the lab solo, run the **Before the session** sequence from the workshop README first (`uv sync --all-packages` → `nobs preflight` → `nobs packt up` → `nobs packt load-infrahub`) — `nobs packt up` alone doesn't seed Infrahub, and `reset` will fail with `SchemaNotFoundError` until `load-infrahub` has run once.

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

> Your senior taps the screen. *"Before we start querying, let's see how two devices report the same interface state. Once the names match, one query can cover both."*

#### 1. One fact, two device languages

Both devices report whether an interface is up, but they name that fact differently:

- **`srl1` uses gNMI:** the metric is `srl_interface_oper_state`, and the device name is stored in `source`.
- **`srl2` uses SNMP:** the metric is `ifOperStatus`, and the device name is stored in `agent_host`.

Telegraf translates both into the same format before Prometheus stores them:

```text
interface_oper_state{device="srl1",name="ethernet-1/1"} 1
interface_oper_state{device="srl2",name="ethernet-1/1"} 1
```

This translation is called **normalization**. The underlying fact and value stay the same; only the names are made consistent so one query can work across both devices.

#### See what each device sends before Telegraf { #see-the-raw-shape-before-telegraf-touches-it }

> Your senior pulls up a terminal. *"Let's look at what each device sends, then at what Prometheus stores."*

Open these links in your browser and follow the interface-state metric from its original name to the shared name. You do not need to understand every line; focus on the metric name and the label that identifies the device.

??? example "Source excerpts — the same interface state in two formats"

    === "srl1 · gNMI"

        From [`workshops/packt/sonda/catalog/srlinux-gnmi-interface-raw.yaml`](https://github.com/network-observability/workshops/blob/main/workshops/packt/sonda/catalog/srlinux-gnmi-interface-raw.yaml):

        ```yaml
        shared_labels:
          source: ""             # Telegraf renames -> device
          name: ""
          collection_type: gnmi

        metrics:
          - name: srl_interface_oper_state
            generator:
              type: constant
              value: 1.0
        ```

    === "srl2 · SNMP"

        From [`workshops/packt/sonda/catalog/cisco-snmp-interface-raw.yaml`](https://github.com/network-observability/workshops/blob/main/workshops/packt/sonda/catalog/cisco-snmp-interface-raw.yaml):

        ```yaml
        shared_labels:
          agent_host: ""         # Telegraf renames -> device
          ifDescr: ""            # Telegraf renames -> name
          collection_type: snmp

        metrics:
          - name: ifOperStatus
            generator:
              type: constant
              value: 1.0
        ```

1. **srl1 before Telegraf:** <http://localhost:8085/scenarios/metrics?label=source:srl1>

    Look for `srl_interface_oper_state` and `source="srl1"`. The value `1` means the interface is up:

    ```
    srl_interface_oper_state{collection_type="gnmi",name="ethernet-1/1",source="srl1"} 1
    ```

    The source file [`workshops/packt/sonda/catalog/srlinux-gnmi-interface-raw.yaml`](https://github.com/network-observability/workshops/blob/main/workshops/packt/sonda/catalog/srlinux-gnmi-interface-raw.yaml) lists every metric in this format.

2. **srl2 before Telegraf:** <http://localhost:8085/scenarios/metrics?label=agent_host:srl2>

    The same fact is called `ifOperStatus`, and the device is identified by `agent_host="srl2"`:

    ```
    ifOperStatus{agent_host="srl2",collection_type="snmp",ifDescr="ethernet-1/1"} 1
    ```

    This is still interface operational state; only the metric and label names differ. Source file: [`workshops/packt/sonda/catalog/cisco-snmp-interface-raw.yaml`](https://github.com/network-observability/workshops/blob/main/workshops/packt/sonda/catalog/cisco-snmp-interface-raw.yaml).

3. **srl1 after Telegraf:** <http://localhost:9005/metrics>

    Find the same sample under `interface_oper_state`. Telegraf has also changed `source="srl1"` to `device="srl1"`.

4. **srl2 after Telegraf:** <http://localhost:9006/metrics>

    `ifOperStatus` is now also `interface_oper_state`, and `agent_host="srl2"` is now `device="srl2"`. Both devices finally use the same names.

5. **Final view in Prometheus**: <http://localhost:9090/graph?g0.expr=interface_oper_state&g0.tab=1>

    A single query returns rows from both devices. It no longer needs to know whether the original data came from gNMI or SNMP.

Want to understand Sonda itself? The [Sonda server section of **Tour the stack**](https://network-observability.github.io/workshops/workshop/tour/#sonda-server-the-synthetic-telemetry-control-plane) explains its role, scenarios, and HTTP endpoints. That component detail applies to both workshop stacks but is not needed for this exercise.

Now flip to the Prometheus query browser and look at the same data after all the renames:

```promql
interface_oper_state{intf_role="peer"}
```

You should see six rows with the same metric name and label names. The rename rules live in [`telegraf-srl1.conf.toml`](https://github.com/network-observability/workshops/blob/main/workshops/packt/telegraf/telegraf-srl1.conf.toml) and [`telegraf-srl2.conf.toml`](https://github.com/network-observability/workshops/blob/main/workshops/packt/telegraf/telegraf-srl2.conf.toml).

There is one new label: `intf_role="peer"`. The devices did not send an interface role. Telegraf worked it out from the interface name and added it. That introduces a second useful term:

- **Normalization** renames existing data: `srl_interface_oper_state` becomes `interface_oper_state`.
- **Enrichment** adds useful context: Telegraf adds `intf_role="peer"`.

PromQL treats both the same way, but the distinction helps when troubleshooting: a bad rename can hide a device's data from a shared query, while missing enrichment leaves the data present but removes useful context.

Telegraf keeps one label from the original path: `collection_type="gnmi"` for srl1 and `collection_type="snmp"` for srl2. Use it when troubleshooting how data was collected. Leave it out of normal dashboards and alerts so the same query covers every device.

The payoff is simple:

- One query works for both devices.
- A new vendor does not require another copy of every dashboard and alert.
- The collection method remains available when you need to troubleshoot it.

> Your senior closes the laptop slightly. *"We haven't hidden where the data came from. We've just stopped every dashboard and alert from needing a version for each vendor."*

**Stop and notice.** `collection_type` answers *how did this data arrive?* Use `device` and `name` to ask *what is happening on the network?*

#### 2. Discover what's in the lab

You've seen Telegraf turn two device formats into one. Now work with the stored data. Switch to Grafana **Explore**, pick the `prometheus` datasource, and run the metric with no filter:

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

!!! tip "Numbers look low?"

    `rate()` averages over the window in the brackets, so a lab that only started a few minutes ago hasn't filled a `[5m]` window yet and will read under the true rate. Give it a few minutes and it settles.

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

Returns `pipeline=direct` and `pipeline=vector` respectively. You will also see a small unlabelled (`{}`) bucket — a few lines that carry no `pipeline` label at all; ignore it, the labelled rows are the point. Now run a query that doesn't pin the pipeline:

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

**Stop and notice.** Metrics told you *something* is wrong (admin says up, oper says down). Logs tell you *why* (peer didn't reply, fsm transition, whatever the message says). The labels are the same on both sides — that's what makes correlation cheap. This is the single most important pattern in the entire workshop. Every dashboard panel in Part 2, every alert path you walk in Part 3, leans on this metric-to-log bridge.

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
