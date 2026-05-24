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

Open Grafana at <http://localhost:3000> (login `admin` / `admin` unless you changed `.env`). Click the compass icon in the left rail to open **Explore**. The datasource picker at the top is how you switch between Prometheus and Loki. You'll bounce between them throughout this part.

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

#### 2. Per-device counts

> *"How many BGP peers does each device think it has?"*

```promql
count by (device) (bgp_oper_state)
```

You should see two rows: `device=srl1` returning `3`, and `device=srl2` returning `3`. Three configured BGP peers per device.

**Stop and notice.** `count by (device)` collapsed every label *except* `device`. PromQL aggregations work that way — list the labels you want to keep; everything else flattens. Try it without the `by`:

```promql
count(bgp_oper_state)
```

One row, value `6`. Six BGP peer series total.

#### 3. Find the broken peer

> Your senior leans in. *"Two peers in this lab are wired to be broken on purpose — intent says they should be up, reality disagrees. Find them with one query. Two clauses, joined."*

```promql
bgp_oper_state != 1
  and on (device, peer_address)
bgp_admin_state == 1
```

You should get **exactly two rows**:

- `device=srl1, peer_address=10.1.99.2` — `bgp_oper_state` value is `5` (active, retrying)
- `device=srl2, peer_address=10.1.11.1` — `bgp_oper_state` value is `5`

> Your senior leans back in their chair. *"You just found two peers that have been in mismatch for weeks. Each has a `BgpSessionNotUp` alert that's been firing the whole time and nobody's owned it. Welcome to on-call. We're not going to fix them today; we're going to learn from them. The shape of the query you just ran is the shape of the alert that's been paging the rotation."*

**Stop and notice.** `and on (device, peer_address)` is the intent-vs-reality pattern. Left side: where operational state isn't `up` (reality). Right side: where admin says `enabled` (intent). The result keeps the *left* side's value — that's why each row shows `5`, the oper_state, not `1`, the admin_state. Match them on the labels they share, and you've expressed "should be up, isn't" in one line. This single query is the core of how the `BgpSessionNotUp` alert fires later in Part 3 — same intent-vs-reality, just with `for: 30s` wrapped around it.

#### 4. Rate of change on a counter

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

**Stop and notice.** Anything that ends in `_octets`, `_packets`, `_total`, `_bytes` is a counter. Wrap it in `rate()` or `increase()`. Plotting a raw counter gives you a saw-tooth or a monotonic line that tells you nothing operationally.

#### 5. Trigger something and watch the query react

> Your senior gestures at the keyboard. *"The lab generates synthetic data on a schedule, but you can also drive events into it yourself. Try this — keep the queries open in Explore."*

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

One run of the command posts a single declarative cascade to sonda — interface flaps for 4 minutes on a 30s-up / 60s-down cadence, BGP follows after a 10s hold-down (real flaps don't take BGP down instantly), and every gated metric snaps back the moment the interface returns. The bullet list further down spells out the per-signal beats; you don't drive the recovery, the cascade does.

??? tip "Trip just the flap, not BGP"

    Pass `--no-cascade` and the same call emits the interface flap and UPDOWN log stream alone — no BGP gated entries. Useful when you want `PeerInterfaceFlapping` to trip but `BgpSessionNotUp` to stay clean.

To watch the cascade react, open three Explore tabs (or one tab and toggle):

```promql
interface_oper_state{device="srl1", name="ethernet-1/1"}
```

```promql
bgp_oper_state{device="srl1", peer_address="10.1.2.2"}
```

```promql
bgp_prefixes_accepted{device="srl1", peer_address="10.1.2.2"}
```

Switch all three to `Time series` view. Run `flap-interface` and watch each one in turn:

- The interface metric flips between `1` (up) and `2` (down) on the 30s-up / 60s-down cadence.
- About 10 seconds after the interface drops, `bgp_oper_state` follows from `1` down to `2`. It stays there until the interface comes back up.
- Prefix counters drop to `0` on the same beat as `bgp_oper_state`.
- The moment the interface returns to up, every gated series snaps back: `bgp_oper_state` goes to `1`, prefix counters go to `10`. Dashboards go green within seconds.

Then briefly switch one tab to the `loki` datasource:

```logql
{device="srl1", vendor_facility_process="UPDOWN", interface="ethernet-1/1"}
```

The log lines that drove the metric flip are right there with the same timestamps. Same labels, same correlation pattern you'll lean on heavily later in the bridge exercise.

**Stop and notice.** One CLI command, multiple signals reacting in causal order, and a clean recovery beat when the gate closes. Synthetic data with real shapes — and you can drive it. The query bar reacts to lab state in real time, no batch refresh, no caching layer hiding your changes. The shape of this cascade — interface degrades → BGP follows → prefixes drop → interface recovers → BGP snaps back — is what real outages and recoveries look like in your network. Memorise the shape; it generalises.

#### 6. Normalization — two raw shapes, one shared schema

> Your senior swivels their laptop toward you. *"Earlier I said `srl1` and `srl2` are wired through different pipelines on purpose. Now we look at it. This is the part that bites every operator who jumps from one vendor's network to another."*

The two devices speak different protocols at the source:

- **`srl1` emits gNMI** — that's the telemetry shape SR Linux puts on the wire natively. Field names like `srl_bgp_oper_state`, tags like `source`. **Telegraf-srl1** scrapes this raw shape, renames `srl_*` to canonical (`bgp_*`, `interface_*`) and `source` to `device`. Out the other side: the shared schema this workshop's dashboards and alerts speak.
- **`srl2` emits SNMP** — the classic shape from IF-MIB / BGP4-MIB / CISCO-BGP4-MIB. Field names like `ifHCInOctets`, `bgpPeerState`, `cbgpPeerOperStatus`; tags like `agent_host`, `ifDescr`, `bgpPeerRemoteAddr`. **Telegraf-srl2** scrapes the raw SNMP shape and renames every field and every tag to the same canonical schema. Out the other side: byte-for-byte identical to what srl1 produces.

Both raw shapes live on `sonda-server` (the lab's synthetic-telemetry runtime). Each Telegraf scrapes the server's aggregate `/metrics` endpoint on a 10-second cadence, filtered to its device by a label query — same scrape pattern Prometheus would use against real exporters in production.

#### See the raw shape, before Telegraf touches it

> Your senior pulls up a terminal. *"You don't have to take the bullet list on faith. Both raw shapes are sitting on sonda-server right now — let me show you."*

`sonda-server` exposes a single `/metrics` endpoint and lets you filter it down to one device with a `label=` query. For srl1, the device tag in the gNMI shape is `source`:

```bash
curl -s 'http://localhost:8085/metrics?label=source:srl1' | grep '^srl_bgp_oper_state' | head -1
```

```
srl_bgp_oper_state{afi_safi_name="ipv4-unicast",collection_type="gnmi",name="default",neighbor_asn="65102",peer_address="10.1.2.2",source="srl1"} 1 1779662362111
```

Note the metric name (`srl_bgp_oper_state`) and the device label (`source="srl1"`) — that's the gNMI shape SR Linux puts on the wire. The pack `workshops/autocon5/sonda/catalog/srlinux-gnmi-bgp-raw.yaml` lists every metric in this shape.

Same exercise on srl2 — same endpoint, different label key because the SNMP shape uses `agent_host`:

```bash
curl -s 'http://localhost:8085/metrics?label=agent_host:srl2' | grep '^bgpPeerState' | head -1
```

```
bgpPeerState{afi_safi_name="ipv4-unicast",agent_host="srl2",bgpPeerRemoteAddr="10.1.2.1",bgpPeerRemoteAs="65101",collection_type="snmp",name="default"} 1 1779662362111
```

Field name `bgpPeerState`, tag `agent_host`, value space matches SNMP enum semantics. Different name, different label keys than `srl_bgp_oper_state` — same logical concept, completely different shape. Pack: `workshops/autocon5/sonda/catalog/cisco-snmp-bgp-raw.yaml`.

> Your senior taps the screen. *"This is a snapshot endpoint — Telegraf reads it on its 10-second cadence, you can read it whenever, nobody steals samples from anyone. Same scrape model real production uses: one source of truth, many consumers."*

Now compare to the normalized view in Prometheus, post-Telegraf:

```promql
bgp_oper_state{peer_address=~"10.1.2.[12]"}
```

Two rows, both `bgp_oper_state{device=..., peer_address=..., afi_safi_name="ipv4-unicast", name="default", ...}`. Same metric name, same label keys, regardless of whether the upstream was `srl_bgp_oper_state{source=srl1}` or `bgpPeerState{agent_host=srl2}`. That's the rename rules in `telegraf-{srl1,srl2}.conf.toml` doing the lift.

The label that records which raw shape a series came from is `collection_type`. Run this once per device:

```promql
count by (collection_type) (bgp_oper_state{device="srl1"})
```

You should see one row: `collection_type=gnmi` returning `3`.

```promql
count by (collection_type) (bgp_oper_state{device="srl2"})
```

One row: `collection_type=snmp` returning `3`. Same metric, same number of series, different vendor shape upstream.

Now click into a result on each side and compare the full label set — `device`, `peer_address`, `neighbor_asn`, `name`, `afi_safi_name`. The *only* meaningful difference is the `collection_type` value. Everything else lines up.

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

#### Your turn (unguided) — find the busiest interface

> Your senior leans back. *"You've got the basic queries. Now answer one yourself, no scaffolding: which interface is moving the most bytes per second right now, across the whole lab? Get me the answer in one PromQL line."*

This is the first unguided exercise. No copy-paste. The metric you need is `interface_in_octets` (or `interface_out_octets`), the operator that turns a counter into a rate is `rate()`, and the function that picks the top N results is `topk()`. Compose them.

Take a minute on it before you scroll. Two quick hints if you're stuck:

- Counters need `rate()` over a window (Exercise 4).
- `topk(N, expression)` returns the N highest-valued series.

You should be able to land an answer with a single query that returns one or two rows. If you get more than that, narrow further — your senior won't want a list of every interface, they want the one that matters.

### Logs — LogQL

> Your senior pushes back from the desk. *"OK, you've got a sense of the metric shape. Now: when something looks wrong in metrics, you need to find a log line that explains it. Logs are where the why lives. Same lab, different query language. Switch the datasource."*

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

Switch the panel to `Time series`. You should see two flat lines (one per device) sitting around **two or three events per 5-minute window**. That floor is the always-broken `ethernet-1/11` on each device — the only interface that's actually flapping at rest. Healthy interfaces don't contribute because they don't emit anything when nothing's happening to them; that's the honest answer to "is anything flapping right now?".

Trigger a flap on a previously-silent healthy interface and watch the line jump:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/10
```

Within ~30 seconds the `srl1` line climbs sharply — past the `PeerInterfaceFlapping` alert's `> 3 events in 2 minutes` threshold and on toward 30+ as the cascade's down-phase log emissions stack into the rolling 5-minute window. The `srl2` line stays at its quiet baseline. **Stop and notice.** This is exactly how the `PeerInterfaceFlapping` alert reads logs in Part 3 — same shape, just with a `> 3` threshold and a `for: 30s` clause. Any LogQL aggregation query is a candidate alert rule.

#### 11. Pipeline awareness on logs

The same normalization story plays out on the log side, with one important difference from metrics: logs in this workshop don't go through Telegraf. They have their own shipper story.

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

#### 12. Why is the peer down?

This is the payoff exercise. Use the broken-peer query from #3 to find a mismatched peer, then jump to logs to find out *why*.

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

## Stretch goals (optional — pick one if you have time)

- **Find the busiest interface in the last 5 minutes.** Combine `topk` with `rate()` on `interface_in_octets`. Hint: `topk(3, rate(interface_in_octets[5m]))`.
- **List every distinct severity level present in srl1 logs in the last hour.** LogQL: parse with `| json`, then check the unique values of `severity` — the Explore log inspector shows distinct values per parsed field after a JSON parse stage.
- **Run the broken-peer query against srl2 only.** Same shape as #3 but scoped to one device. Confirm you get exactly one row (`peer_address=10.1.11.1`).
- **Plot CPU and memory side by side.** Two queries in one panel: `cpu_used{device="srl1"}` and `memory_utilization{device="srl1"}`. The legend should show two lines.
- **Inspect the raw shape Telegraf normalizes.** `docker exec telegraf-srl2 wget -qO- http://localhost:9005/metrics | grep -E '^(interface_|bgp_)'` shows what the shared names look like; `nobs autocon5 logs telegraf-srl2 | head -40` shows the raw SNMP-named samples *before* normalization. The rename ruleset that bridges them lives in `telegraf/telegraf-srl2.conf.toml`.

## What you took away

- You now know what "normal" looks like in this network. That baseline is what every triage in your future is going to compare against.
- Every metric is `name + labels + value`. Aggregations collapse labels you don't list.
- Counters need `rate()`. The window inside the brackets controls smoothness.
- Intent-vs-reality is two clauses joined by `and on (...)` — the workshop's broken peers are caught by exactly that shape.
- LogQL stream selectors look like PromQL but pick log streams. Line filters narrow inside those streams.
- `count_over_time({...}[N])` turns a log query into a metric — same pattern any LogQL alert rule uses.
- Same labels on metrics and logs means correlation is one query change away. Metric tells you *what*; log tells you *why*.
- Two normalization stories on this lab — `collection_type=gnmi/snmp` on metrics, `pipeline=direct/vector` on logs. The label that records the source pipeline exists for inspecting the normalization itself; default to pipeline-agnostic queries and reach for the label only when you're debugging the path, not the network.
