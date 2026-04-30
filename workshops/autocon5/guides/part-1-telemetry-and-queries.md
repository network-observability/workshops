# Part 1 — Network telemetry and queries

## What you'll do here

Write PromQL and LogQL by hand against the running lab. You'll discover the metric schema, find the deliberately broken BGP peer with a single intent-vs-reality query, and correlate metrics to logs to explain *why* a session is down. By the end you'll know enough query syntax to read any dashboard in this workshop.

This part is the longest of the day on purpose — every later part depends on you being comfortable in the query bar.

## Setup check

In a terminal, from the repo root:

```bash
nobs autocon5 status
```

Every row should report `ok`. If `prometheus`, `loki`, or `sonda` is anything else, flag it before continuing.

Open Grafana at <http://localhost:3000> (login `admin` / `admin` unless you changed `.env`). Click the compass icon in the left rail to open **Explore**. The datasource picker at the top is how you switch between Prometheus and Loki. You'll bounce between them throughout this part.

Open the **Workshop Home** dashboard once (`/d/workshop-home`) so you've seen the stat row — Devices, Interfaces, Firing alerts, Log lines (5m). Those four numbers are your sanity check throughout the workshop.

## The exercises

### Metrics — PromQL

#### 1. Discover what's in the lab

In Explore, pick the `prometheus` datasource. In the query bar, run:

```promql
interface_oper_state
```

Click `Run query`. You should see a table of results, one row per interface per device. Click any row's labels — the inspector shows the full label set:

- `device` — `srl1` or `srl2`
- `name` — interface name (`ethernet-1/1`, `ethernet-1/10`, `ethernet-1/11`)
- `intf_role` — `peer` for the three real ones
- `pipeline` — `direct` (srl1) or `telegraf` (srl2)
- `collection_type` — how the metric was collected

**Stop and notice.** The metric *name* tells you what (operational state of an interface). The *labels* tell you which one and where it came from. Every query you write from now on is a filter or aggregation on labels.

#### 2. Per-device counts

```promql
count by (device) (bgp_oper_state)
```

You should see two rows: `device=srl1` returning 3, and `device=srl2` returning 3. Three configured BGP peers per device.

**Stop and notice.** `count by (device)` collapsed every label *except* `device`. PromQL aggregations work that way — list the labels you want to keep; everything else flattens. Try it without the `by`:

```promql
count(bgp_oper_state)
```

One row, value 6. Six BGP peer series total.

#### 3. Find the broken peer

Two peers in the lab are wired to be broken on purpose: intent says they should be up, reality disagrees. Find them in two lines:

```promql
bgp_admin_state == 1
  and on (device, peer_address)
bgp_oper_state != 1
```

You should get exactly two rows:

- `device=srl1, peer_address=10.1.99.2`
- `device=srl2, peer_address=10.1.11.1`

**Stop and notice.** `and on (device, peer_address)` is the intent-vs-reality pattern. Left side: where admin says `enabled`. Right side: where operational state isn't `up`. Match them on the labels they share. This single query is the core of how the `BgpSessionNotUp` alert fires later in Part 3 — same intent-vs-reality, just with `for: 30s` wrapped around it.

#### 4. Rate of change on a counter

Counters in Prometheus only ever go up. Reading them raw is useless — you want the *rate*.

```promql
rate(interface_in_octets{device="srl1"}[1m])
```

In the panel options on the right of Explore, switch from `Table` to `Time series`. You should see one line per interface, each in bytes-per-second.

Now widen the window:

```promql
rate(interface_in_octets{device="srl1"}[5m])
```

The lines smooth out. The window inside the brackets is how much history `rate()` averages over — short windows are twitchy, long windows hide spikes.

**Stop and notice.** Anything that ends in `_octets`, `_packets`, `_total`, `_bytes` is a counter. Wrap it in `rate()` or `increase()`. Plotting a raw counter gives you a saw-tooth or a monotonic line that tells you nothing operationally.

#### 5. Trigger something and watch the query react

The lab generates synthetic data on a schedule, but you can also drive events into it yourself. The CLI command for that:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

This pushes 6 UPDOWN events into Loki over about 6 seconds. It's a log-event injection by design — the canonical interface-state *metric* keeps its underlying schedule so the rest of the lab's queries stay stable for everyone in the room. The events you're injecting show up on the log side.

To watch it react, briefly switch your Explore datasource to `loki` and run:

```logql
{device="srl1", vendor_facility_process="UPDOWN", interface="ethernet-1/1"}
```

Click `Run query`. Then run the flap CLI again from your terminal. Watch new lines arrive in the log panel within ~5 seconds. Switch back to `prometheus` when you're done — you'll come back to `flap-interface` in Exercise 10 to see how this same event stream becomes a *metric* via `count_over_time`.

**Stop and notice.** Synthetic data, real shapes — and you can drive it. The query bar reacts to lab state in real time, no batch refresh, no caching layer hiding your changes. Live data is the whole point of running queries in the first place; if your dashboards lag, you're not observing, you're reading history.

#### 6. Pipeline awareness — metrics normalization

The two devices are wired through different metric pipelines on purpose. What you're looking at is **the same metric in two places along a normalization journey**.

Run this twice, once per device:

```promql
count by (pipeline) (bgp_oper_state{device="srl1"})
count by (pipeline) (bgp_oper_state{device="srl2"})
```

`srl1` returns `pipeline=direct`. `srl2` returns `pipeline=telegraf`. Now click into a result on each side and compare the full label set — `device`, `peer_address`, `neighbor_asn`, `name`, `afi_safi_name`. The *only* meaningful difference is the `pipeline` value. Everything else lines up.

That alignment is what "normalization" actually buys you:

- **`pipeline=direct` is the normalized metric** — it already has the metric name, label keys, and value semantics you want to query against. Sonda emits it that way directly because we control its shape.
- **`pipeline=telegraf` is the same metric still being processed to *become* normalized.** The raw input is whatever the vendor emits — vendor-specific metric names, different label keys, sometimes different units or value encodings. Telegraf renames, relabels, and rescales until what comes out the other end matches the normalized shape. The `pipeline` label is a tag that records which normalization path the data took to get here.
- **Real fleets are heterogeneous and this is why normalization exists.** Nokia SR Linux via gNMI, Cisco IOS-XR via Model-Driven Telemetry, Juniper via OpenConfig, legacy boxes via SNMP — each speaks its own dialect. Without normalization, every dashboard, alert rule, and runbook fragments per vendor. With it, the *query layer* doesn't see the dialects at all.

Prove the normalization holds end-to-end:

```promql
bgp_oper_state
```

Returns rows for *both* devices, *both* pipelines. A dashboard panel querying `bgp_oper_state{device="$device"}` doesn't care which transport delivered the data — it asks for the normalized name and gets it.

**Stop and notice.** The `pipeline` label is for inspecting the normalization itself: *"which path did this sample take, is that path healthy?"* It's not for branching your query logic. If you write `bgp_oper_state{pipeline="direct"}` into a dashboard, you've narrowed to one path — useful for debugging that path, but you'll miss every device whose data flows through any other pipeline. Default to pipeline-agnostic queries; reach for the `pipeline` label when you're debugging the normalization, not the network.

### Logs — LogQL

Switch the Explore datasource to `loki`.

#### 7. Stream selection

```logql
{device="srl1"}
```

Run it. You'll see a stream of recent log lines from `srl1`. The dropdown on the right lets you switch between log view and table view.

**Stop and notice.** Curly braces with label selectors look like Prometheus, but they pick *log streams*, not metric series. A LogQL query always starts with `{...}`. Without label selectors Loki doesn't know what to query.

#### 8. Line filter

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

#### 9. JSON parse

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

#### 10. Aggregation — log queries that produce metrics

Aggregating logs over time turns a log query into a metric:

```logql
sum by (device) (count_over_time({vendor_facility_process="UPDOWN"}[5m]))
```

Switch the panel to `Time series`. You should see two lines (one per device) showing UPDOWN events per 5-minute window.

Trigger another flap:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/10
```

Within ~30 seconds the `srl1` line jumps. **Stop and notice.** This is exactly how the `PeerInterfaceFlapping` alert reads logs in Part 3 — same shape, just with a `> 3` threshold and a `for: 30s` clause. Any LogQL aggregation query is a candidate alert rule.

#### 11. Pipeline awareness on logs

The same normalization story plays out on the log side. `srl1` emits structured logs directly to Loki — that's the **normalized log**, `pipeline=direct`. `srl2` emits raw RFC 5424 syslog; Vector parses it, extracts fields, and rewrites them into the same label vocabulary `srl1` already uses — that's the same log **still being processed to become normalized**, `pipeline=vector`.

```logql
count by (pipeline) (count_over_time({device="srl1"}[5m]))
count by (pipeline) (count_over_time({device="srl2"}[5m]))
```

Returns `pipeline=direct` and `pipeline=vector` respectively. Now run a query that doesn't pin the pipeline:

```logql
{vendor_facility_process="UPDOWN"}
```

You should see streams from both devices. The `device`, `vendor_facility_process`, `interface`, `severity` labels look identical — Vector did the work to make `srl2`'s raw syslog land in Loki with the same shape `srl1`'s structured logs already have. Same normalization story, log edition.

### The bridge — metric to log

#### 12. Why is the peer down?

This is the payoff exercise. Use the broken-peer query from #3 to find a mismatched peer, then jump to logs to find out *why*.

In the `prometheus` datasource:

```promql
bgp_admin_state{device="srl1"} == 1
  and on (device, peer_address)
bgp_oper_state{device="srl1"} != 1
```

Note the broken peer's `peer_address` — for `srl1` it should be `10.1.99.2`. Switch to the `loki` datasource:

```logql
{device="srl1", peer_address="10.1.99.2"}
```

You'll see BGP-related lines for that specific peer. Add a filter to narrow:

```logql
{device="srl1", peer_address="10.1.99.2"} |~ "BGP"
```

**Stop and notice.** Metrics told you *something* is wrong (admin says up, oper says down). Logs tell you *why* (peer didn't reply, fsm transition, whatever the message says). The labels are the same on both sides — that's what makes correlation cheap. This is the single most important pattern in the entire workshop. Every dashboard panel you'll build in Part 2, every alert path in Part 3, leans on this metric-to-log bridge.

## Stretch goals

- **Find the busiest interface in the last 5 minutes.** Combine `topk` with `rate()` on `interface_in_octets`. Hint: `topk(3, rate(interface_in_octets[5m]))`.
- **List every distinct severity level present in srl1 logs in the last hour.** LogQL: parse with `| json`, then check the unique values of `severity` — the Explore log inspector shows distinct values per parsed field after a JSON parse stage.
- **Run the broken-peer query against srl2 only.** Same shape as #3 but scoped to one device. Confirm you get exactly one row (`peer_address=10.1.11.1`).
- **Plot CPU and memory side by side.** Two queries in one panel: `cpu_used{device="srl1"}` and `memory_utilization{device="srl1"}`. The legend should show two lines.

## What you took away

- Every metric is `name + labels + value`. Aggregations collapse labels you don't list.
- Counters need `rate()`. The window inside the brackets controls smoothness.
- Intent-vs-reality is two clauses joined by `and on (...)` — the workshop's broken peers are caught by exactly that shape.
- LogQL stream selectors look like PromQL but pick log streams. Line filters narrow inside those streams.
- `count_over_time({...}[N])` turns a log query into a metric — same pattern any LogQL alert rule uses.
- Same labels on metrics and logs means correlation is one query change away. Metric tells you *what*; log tells you *why*.
- `pipeline=direct` is the normalized signal — already in the shape you want to query. `pipeline=telegraf` and `pipeline=vector` are the same signal still being processed to become normalized. Write your queries pipeline-agnostic; reach for the `pipeline` label only when you're debugging the normalization itself.
