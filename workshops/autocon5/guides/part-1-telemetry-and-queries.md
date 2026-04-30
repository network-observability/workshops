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

In a terminal:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

This pushes 6 alternating up/down events into the log stream, and the synthetic interface state metric flips along with them. Back in Explore, run:

```promql
interface_oper_state{device="srl1", name="ethernet-1/1"}
```

Switch to `Time series` if you aren't already there. Within ~30 seconds you'll see the value bounce between `1` (up) and `2` (down).

**Stop and notice.** Synthetic data, real shapes. The query bar reacts to lab state in real time — there's no batch refresh, no caching layer hiding your changes.

#### 6. Pipeline awareness

The hybrid pipeline is the workshop's signature point: srl1 ships metrics straight to Prometheus; srl2 ships through Telegraf which renames vendor paths into the canonical schema. Same metric name comes out either way. Prove it:

```promql
count by (pipeline) (bgp_oper_state{device="srl2"})
```

Returns one row: `pipeline=telegraf`. Now:

```promql
count by (pipeline) (bgp_oper_state{device="srl1"})
```

Returns: `pipeline=direct`. **Same metric name, two transports, one query.** That's the schema-as-contract pattern — every dashboard, alert rule, and Prefect flow you'll see today is written *only* against the canonical names. The pipeline label is for debugging which transport is healthy, not for branching query logic.

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

Same hybrid story, this time on the log side. srl1 emits direct to Loki, srl2 ships RFC 5424 syslog through Vector which normalizes it.

```logql
count by (pipeline) (count_over_time({device="srl2"}[5m]))
```

Returns `pipeline=vector`. Compare:

```logql
count by (pipeline) (count_over_time({device="srl1"}[5m]))
```

Returns `pipeline=direct`. Different shipper, same labels arriving in Loki.

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
- The `pipeline` label tells you which transport carried the data. Your queries don't care; your debugging does.
