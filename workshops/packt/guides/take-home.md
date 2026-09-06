# Take it home

## What you'll do here

Three hours is enough to walk the arc once. It is not enough to walk it slowly. This page is everything we cut to fit the session, written in the order you would actually work through it at your own pace — no rush, no runsheet, nobody moving on without you.

The stack is still on your laptop and it costs nothing to leave it there. Bring it back up whenever you have an evening:

```bash
cd workshops
uv sync --all-packages
nobs packt up
nobs packt status          # repeat until every row says ok
nobs packt load-infrahub
```

Then pick a section. They are independent — you do not have to do them in order, though the order below is the one that builds on itself best.

!!! note "Numbering on this page is the original full sequence"

    These sections keep the step and exercise numbers from the complete, untrimmed workshop, because their internal cross-references depend on them. They do **not** line up with the numbering in the session guides — the session runs a subset and renumbers. When a section here says "step 6", it means step 6 *of this section*, not step 6 of Part 2.


| Section | Roughly | What it adds |
|---|---|---|
| [Part 1 — recording rules and alerts](#part-1-recording-rules-and-alerts) | 25 min | Where an alert rule actually comes from |
| [Part 1 — the capstone and stretch goals](#part-1-the-capstone-and-stretch-goals) | 40 min | All three layers reacting to one event, live |
| [Part 2 — the full ten-step panel build](#part-2-the-full-ten-step-panel-build) | 45 min | Build the panel yourself instead of watching |
| [Part 2 — the rest of the alert lifecycle](#part-2-the-rest-of-the-alert-lifecycle) | 15 min | The CLI view and the lifecycle diagram |
| [Part 2 — stretch goals](#part-2-stretch-goals) | 20–60 min | Three progressively harder dashboard builds |
| [Part 3 — swap in a real LLM](#part-3-swap-in-a-real-llm) | 20 min | Your own OpenAI or Anthropic key, side by side with the template |
| [Part 3 — deep dives](#part-3-deep-dives) | 30 min | All four paths at once, the Prefect UI, direct triggers |
| [Part 3 — stretch goals](#part-3-stretch-goals) | 30–60 min | Tail the flows, compare healthy vs broken, aggregate the audit trail |
| [Advanced — the 02:14 page](#advanced-the-0214-page) | 60–90 min | The whole thing again, alone, end to end |

---

## Part 1 — recording rules and alerts

We stopped Part 1 after the metric-to-log bridge. The two sections below are what comes next in the original arc: composing expensive queries into pre-computed metrics, then wrapping a query in an alert rule so it fires on its own. Read them in order — the alert rule in the second section is the intent-vs-reality query from exercise 4 with a `for:` clause bolted on, and it will not land unless the recording-rule idea is fresh.

#### Recording rules — composed metrics

##### 6. Query a pre-computed metric

> Your senior opens a file. *"Every query you just wrote in Explore can be baked into Prometheus as a recording rule. Instead of recomputing it on every dashboard load, Prometheus evaluates it on a schedule and stores the result as a new metric. Dashboards and alerts reference the pre-computed name — fast, consistent, one definition."*

A **recording rule** is Prometheus evaluating a PromQL expression on a fixed interval (typically every 15–60 seconds) and writing the result back as a new, named metric. You then query that name instead of the full expression. Three reasons this matters in practice:

- **Dashboards stay fast.** A `sum by (device) (rate(...)[5m])` over a large fleet scans thousands of raw samples on every panel refresh. The recording rule pays that cost once per interval; the dashboard reads a single pre-computed row.
- **Alerts are consistent.** When an alert rule and a dashboard panel reference the same recording rule name, they're looking at the same computed value — no drift from re-evaluating the same expression independently with slightly different timing.
- **Complex expressions get a stable name.** The intent-vs-reality join you just wrote is seven lines of PromQL. Wrapping it in a recording rule gives it a short, searchable name that runbooks and incident comments can reference.

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

Two rows — one per device, total inbound throughput in bits/sec, already computed. This is the same result you got in exercise 3 with `sum by (device) (rate(interface_in_octets{name!~"mgmt0.*"}[5m])) * 8` — but the PromQL complexity is gone from the query site. No `rate()`, no `sum by` needed at query time. The dashboard panel that shows device traffic references this name, not the raw expression.

**Stop and notice.** A recording rule is just a query that Prometheus runs on a schedule and stores. The result is a first-class metric — you can filter it, alert on it, and reference it from other rules. The naming convention is a readability contract, not a technical requirement: `aggregation:source_metric:window` tells you at a glance what the number represents and over what window it was computed.

#### Alerts

##### 7. Wrap a query in an alert rule

> Your senior closes the rules file. *"A query answers a question. An alert is the same query with one addition: if the answer is true, act. That's all an alert rule is."*

A **Prometheus alert rule** is a PromQL expression evaluated on a schedule — the same way a recording rule is — but instead of storing the result as a metric, Prometheus watches whether the expression returns any rows. If it does, the alert is *firing*; if it returns nothing, it's *inactive*. When an alert fires, Prometheus forwards it to **Alertmanager**, which handles routing, deduplication, and silencing before sending a notification to the on-call channel.

Two fields shape how the alert behaves in practice:

- **`for:`** — how long the condition must stay true before the alert actually fires. Without it, a single bad scrape triggers a page. With `for: 2m`, transient flaps and brief collection gaps are silently ignored.
- **`labels:` / `annotations:`** — labels route the alert (Alertmanager uses them to decide who gets paged and how); annotations carry human-readable context that lands in the notification itself.

You already have the PromQL for this — the intent-vs-reality query from exercise 4. Wrapping it in an alert rule is the mechanical step that turns a query you ran once in Explore into something that watches the network continuously.

###### The expression

Start from the intent-vs-reality query you already know. The operational question is: *"Alert when a peer interface is configured UP but operationally DOWN."*

```promql
count by (device, name) (
  (interface_admin_state{intf_role="peer"} == 1)
  and on (device, name)
  (interface_oper_state{intf_role="peer"} == 2)
) > 0
```

`> 0` is the firing condition — the alert fires whenever at least one interface matches. The `count by (device, name)` keeps the `device` and `name` labels in the alert so the notification knows *which* interface.

###### The rule

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

###### Lab: see this alert in the stack

The `InterfaceAdminUpOperDown` alert is already loaded. The lab's deliberately broken interfaces (`ethernet-1/11` on both devices) satisfy the expression right now.

1. **Prometheus** — open [http://localhost:9090](http://localhost:9090), paste `ALERTS{alertname="InterfaceAdminUpOperDown"}` into the expression bar and run it. You should see one row per device with `alertstate="firing"`. If the lab just started, wait two minutes for the `for: 2m` window to elapse — until then the expression returns no rows because the alert is still in its pending period. (Prefer the rendered list? The [alerts page](http://localhost:9090/alerts) shows the same alert with its `INACTIVE`/`PENDING`/`FIRING` state without writing any PromQL.)

2. **Grafana Explore** — the `ALERTS` metric exposes firing alerts as a queryable time series:

    ```promql
    ALERTS{alertname="InterfaceAdminUpOperDown"}
    ```

    Each row is a firing instance. The label set is the alert's labels merged with the expression's output labels — `device`, `name`, `severity`, `category` all present.

3. **Alertmanager** — open [http://localhost:9093](http://localhost:9093) and confirm the alert arrived and was routed. In Part 3 you'll trace exactly what happens next.

**Stop and notice.** The alert rule you just read is the same intent-vs-reality query from exercise 4, with `> 0`, `for:`, `labels:`, and `annotations:` added. The query is the logic; everything else is operational scaffolding — how long to wait before paging, what labels to route on, what message to show on call. This is the pattern every alert in this lab follows.

---

## Part 1 — the capstone and stretch goals

The capstone is the exercise worth doing first if you only do one thing on this page. Four browser tabs, one command, and every layer of the stack reacting in causal order — it is the moment the separate concepts stop being separate.

### Capstone — everything at once

##### 14. Trigger a cascade and watch metrics, logs, and alerts react

> Your senior gestures at the keyboard. *"You've now seen metrics, normalization, recording rules, alerts, and logs as separate concepts. This exercise puts them all on screen at the same time. One command, one cascade — you watch every layer respond in causal order."*

This is the capstone exercise for Part 1. Open four browser tabs before you run anything:

| Tab | What to open |
|-----|-------------|
| Metrics | Grafana Explore — `prometheus` datasource |
| Logs | Grafana Explore — `loki` datasource |
| Alerts | [Prometheus alerts](http://localhost:9090/alerts) |
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
nobs packt flap-interface --device srl1 --interface ethernet-1/1
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

### Stretch goals (optional — pick one if you have time)

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

        At rest the synthetic emitter ticks every healthy interface at roughly the same `step_size`, so the three winners are essentially tied — `topk` picks 3 of them somewhat arbitrarily. Drive a flap (`nobs packt flap-interface --device srl1 --interface ethernet-1/1`) and the broken/flapping interface stops contributing during DOWN phases — the result list changes accordingly.

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

        - <http://localhost:8085/scenarios/metrics?label=agent_host:srl2> — raw SNMP (pre-Telegraf): `bgpPeerState`, `ifHCInOctets`, `agent_host=srl2`
        - <http://localhost:9006/metrics> — telegraf-srl2's normalized output: `bgp_oper_state`, `interface_in_octets`, `device=srl2`
        - <http://localhost:9090/graph?g0.expr=bgp_oper_state%7Bdevice%3D%22srl2%22%7D&g0.tab=1> — Prometheus stores the same data after one more scrape hop

        For one line of `bgp_active_routes` on srl2, you'll see roughly:

        | Layer | What it looks like |
        |---|---|
        | Sonda raw (before Telegraf) | `bgpPeerInPrefixes{agent_host="srl2", bgpPeerRemoteAddr="10.1.11.1", ...} 10` |
        | Telegraf `/metrics` (after rename) | `bgp_active_routes{collection_type="snmp", device="srl2", peer_address="10.1.11.1", ..., pipeline="telegraf"} 10` |
        | Prometheus (after one more scrape) | identical to the line above — Prometheus just stores it |

        Same number (`10`), same physical fact (this peer has 10 active routes), three different shapes depending on which layer you sample at. The rename ruleset that bridges them lives in `telegraf/telegraf-srl2.conf.toml` — `tag.source → device`, `bgpPeerRemoteAddr → peer_address`, plus the metric-name rewrites. The point of the exercise is to convince yourself that "normalization" isn't a black box — it's a config file you can read.

---

## Part 2 — the full ten-step panel build

We drove four of these ten steps as a demo. Here is the whole build, in order, so you can do it yourself — including the four you watched. Start from a clean dashboard: if you followed along during the session and saved a panel, `nobs packt restart grafana` puts **Workshop Lab 2026** back to the layout the workshop ships with.

### Build the dashboard panel

You're adding a **flap rate** panel: how many UPDOWN log events per minute, broken out per interface, with thresholds that match the `PeerInterfaceFlapping` alert rule.

#### 1. Enter edit mode

> *"Click Edit, top right of the dashboard. The floating sidebar on the right is where you add things."*

Adding a panel in Grafana 13 takes a few clicks:

1. Click **Edit** (top-right corner of the dashboard). A right sidebar appears with a column of icons — hover each to see its name. From top to bottom they are:

    | Icon | Hover name | What it does |
    |---|---|---|
    | `+` | Add | Add a new panel, row, or dashboard control |
    | ⚙ | Dashboard options | Settings, variables, annotations, links |
    | 💬 | Give feedback | Grafana-internal feedback prompt (ignore) |
    | `{}` | Code | View the raw dashboard JSON |
    | ↓ | Export | Export the dashboard |
    | ≡ | Outline | Jump to any panel by name |

2. Click the **`+`** (Add) icon — top of that sidebar. An **Add** menu opens with **Panel**, **Group layouts** (Group into rows, Group into tabs), and **Dashboard controls** (Variable, Annotation query, Link).
3. Click **Panel**. An empty panel lands on the dashboard, and the right sidebar changes to show the new panel's settings — Title, Description, Transparent background, Repeat options.
4. Click the big blue **Configure** button at the top of those settings to open the panel editor — query box at the bottom, panel preview at the top, visualization options on the right.

> New to Grafana? For Grafana itself — panel editor internals, the time picker, dashboard variables — see the [upstream Grafana docs](https://grafana.com/docs/grafana/latest/). Keep one open in another tab while you build.

#### 2. Pick the datasource

> *"What datasource? Think about the data shape — flap rate is a count of log events, not a metric Prometheus is scraping for us."*

Choose **`loki`** in the datasource picker. Flap rate is a *log-derived metric* — Loki counts log lines, not Prometheus samples. (Part 1's [exercise 9 — log aggregation](../../../docs-packt/part-1.md#9-aggregation-log-queries-that-produce-metrics) walks the same `count_over_time(...)` shape if you want a refresher.)

#### 3. Write the query

> *"Same shape as the LogQL aggregation we wrote together earlier. UPDOWN log events, grouped per interface, counted in a 1-minute window. Use the dashboard variable so this panel works for both devices."*

The query box defaults to **Builder** mode — a click-to-build form with Label filters and Operations. To paste a raw LogQL query, toggle to **Code** mode using the `Builder | Code` switch on the right side of the query toolbar.

In the Loki query box (now in Code mode), paste:

```logql
sum by (interface)(count_over_time({device="$device", vendor_facility_process="UPDOWN"}[2m]))
```

Three things to notice:

- `$device` is the dashboard variable. Grafana substitutes it before sending the query, so this panel becomes `srl1`-aware or `srl2`-aware automatically.
- `{device="$device", vendor_facility_process="UPDOWN"}` is a **stream selector** — Loki's way of saying *"pick log streams whose labels match these values"*. The label `vendor_facility_process="UPDOWN"` matches every interface state-change log line emitted by either of the two log pipelines the lab runs (`direct` = sonda pushes the line straight to Loki; `vector` = the same line passes through a Vector router before landing in Loki — Part 1 walks both).
- `count_over_time(...[2m])` counts UPDOWN log lines in a rolling 2-minute window — the same window the `PeerInterfaceFlapping` alert rule uses. `sum by (interface)` groups so each interface gets its own line.

Click **Run query**. **Before you trigger any flap, you'll sometimes see a single line for `ethernet-1/11` at the value `1` — well below the alert threshold of 3.** That interface is wired into the lab as a permanent fault (we'll call it the **always-broken interface** from here on) so steady-state alerts are always visible. It emits one log line every ~2 minutes, so the panel briefly shows `1` right after each one and drops back to empty in between. Healthy interfaces don't show up at all — if nothing is flapping, the panel stays empty, which is what you want to see:

<figure class="section-preview" markdown>

![Flap rate panel at baseline](../../../docs-packt/assets/screenshots/flap-rate-baseline-light.png#only-light){ .screenshot loading=lazy }
![Flap rate panel at baseline](../../../docs-packt/assets/screenshots/flap-rate-baseline-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Baseline (no flap in progress)</strong> — one line for <code>ethernet-1/11</code> at 1 (the only interface that's actually flapping at rest, because it's broken by design). The other peer interfaces are silent. Anything else here means a real flap is in progress.</figcaption>

</figure>

!!! tip "Empty panel?"

    Two reasons the panel might look empty:

    - The `Device` dropdown above the dashboard isn't set to a real device. Toggle it to `srl1` or `srl2`.
    - The broken-interface log emitter fires only every ~2 minutes — the panel goes back to empty between events. Wait a minute or two for the next one to land.

#### 4. Pick the panel type

> *"Time series for this. Aggregations over time always read better as a line graph than a table."*

The right-hand sidebar has two tabs at the top: **Suggestions** (a curated short list based on your query shape) and **All visualizations** (the full set). Click **All visualizations** and pick **Time series**. (It usually shows up in Suggestions too — either path works.)

#### 5. Title and description

> *"Title and description matter. The panel needs to tell the next on-call what they're looking at without you being there to explain it."*

You can set these in two places — pick whichever is in front of you:

- **In the panel settings sidebar** before you clicked Configure (the Title and Description fields are right at the top).
- **In the panel editor**, scroll the right-hand options to **Panel options** → Title / Description.

Either way, use:

- **Title**: `Flap rate (per 2 minutes)`
- **Description**: `UPDOWN log events per interface in a rolling 2-minute window. Above 3, the PeerInterfaceFlapping alert fires — the panel uses the same window so the red threshold line is the alert condition.`

Description shows up as a small `i` icon on the panel — students hovering it later get the context without leaving the dashboard.

#### 6. Set thresholds that match reality

> *"Now thresholds. The PeerInterfaceFlapping alert fires when count_over_time over 2 minutes exceeds 3. Match that — when the threshold line moves, the alert is right behind it."*

The `PeerInterfaceFlapping` alert fires when `count_over_time({vendor_facility_process="UPDOWN"}[2m]) > 3`. Mirror that on the panel so the threshold line *is* the alert condition:

In the right-hand options pane, scroll down to find the **Thresholds** section — it's usually about eight sections down, past Panel options, Tooltip, Legend, Axis, and Graph styles. Set:

| Color | Value | What it means |
|-------|-------|---------------|
| :green_circle: Green | base (default — keep it) | "everything's quiet" |
| :orange_circle: Orange | `2` | "early heads-up — activity above the always-broken `ethernet-1/11` baseline (which sits at 1)" |
| :red_circle: Red | `3` | "alert firing — the `PeerInterfaceFlapping` rule's `> 3` condition has been crossed" |

Then under **Graph styles** → **Show thresholds**, pick `As lines`. **You should now see two horizontal lines on the panel preview — orange at 2, red at 3.** Setting orange at `2` (rather than `1`) keeps the threshold line visually separate from the always-broken `ethernet-1/11` line that sits at `1` — they'd otherwise overlap. A flap rate above the red line means an alert is firing.

> Your senior glances over. *"Thresholds matching the alert rule? Good. When the line crosses the orange one, an interface just logged a state change — that's your early heads-up. When it crosses the red one, the alert is firing and someone's pager goes off. The panel makes both moments visible without a separate alerts pane."*

#### 7. Smooth out the gaps

> *"That `count_over_time` query returns nothing when no logs land in the rolling window. By default Grafana renders those empty stretches as broken lines — easier to read as one continuous line."*

In the right-hand options, still in the **Graph styles** section where you set the threshold lines, find **Connect null values** and change it from `Never` to **Always**.

Now when the 2-minute window briefly has no matching log lines, the panel draws a continuous line through the gap instead of showing disconnected dots. Easier to read at a glance during a flap.

#### 8. Save

Top right of the panel editor, click **Save** to return to the dashboard. Then click **Save** (the blue button, top-right of the dashboard) to save your work. Grafana confirms `Dashboard saved`. The new panel is now part of `Workshop Lab 2026`. Use **Exit edit** next to it when you're done editing for the session.

#### 9. Drive a flap

> *"OK. Panel's there. Doesn't mean anything until we see it react. Drive a flap."*

In a terminal:

```bash
nobs packt flap-interface --device srl1 --interface ethernet-1/1
```

This kicks off a 4-minute **cascade** — a scripted sequence of state changes the lab plays back to imitate a real incident. For this command the interface cycles `30s up, 60s down` for four minutes. UPDOWN log lines emit at a steady cadence (~one every two seconds) during each down window. Switch the dashboard's `Device` dropdown to `srl1` if you aren't already there.

!!! tip "Turn on auto-refresh so the panel updates live"

    By default the dashboard only re-queries when you reload it. To watch the flap climb in real time, click the circular **arrow icon** at the top-right of the dashboard (next to the time-range picker) and pick **5s** from the dropdown. The panel will re-query every 5 seconds — fast enough to catch the cascade as it unfolds, slow enough not to hammer the backends. Set it back to **Off** when you're done.

<figure class="section-preview" markdown>

![Flap rate panel during a flap](../../../docs-packt/assets/screenshots/flap-rate-flapping-light.png#only-light){ .screenshot loading=lazy }
![Flap rate panel during a flap](../../../docs-packt/assets/screenshots/flap-rate-flapping-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>During a flap (~2 min in)</strong> — green line is <code>ethernet-1/1</code>, climbing fast past the orange threshold (2) and through the red threshold (3) on its way to 16+. You may also see a faint yellow series line for <code>ethernet-1/11</code> at 1–2 (that's the Grafana-assigned color for that interface, not a threshold) — the broken-interface log emitter fires at random intervals (roughly once every 2 minutes), so it isn't always inside the 2-minute window the panel is counting. Either way, the flapped interface is the obvious anomaly against an otherwise quiet panel.</figcaption>

</figure>

**What you should see, in order:**

- **First ~45 seconds** are quiet. The cascade starts the interface in the *up* state and walks through one 30-second up phase before the first down phase begins. UPDOWN log emission begins ~10 seconds into the down phase.
- **Around t+60s**: a line for `interface=ethernet-1/1` appears at around `10`. It's already past both the orange (2) and red (3) thresholds — the down phase's emission rate (~one log every two seconds) means the rolling 2-minute count climbs fast.
- **Around t+90s**: the line is somewhere in the `25–40` range — well above red, matching the alert rule's "> 3 events in 2 minutes" condition many times over.
- **Between cycles 1 and 2**: the line **plateaus** around `25` rather than dropping. The rolling 2-minute window still contains the events from cycle 1's down phase — they haven't aged out yet.
- **Cycle 2 around t+120s**: cycle 2's down-phase events stack onto the still-in-window events from cycle 1, so the count climbs higher — typically `40–60`. The plateau-then-climb shape is what real flap-rate dashboards look like during an active flap.

> Your senior taps the screen. *"Watch the orange line — that's the early heads-up, an interface just logged a state change. Watch the red line — that's where someone's pager goes off because the alert rule fired. The panel makes both moments visible without a separate alerts pane."*

**Stop and notice.** This is the same query pattern that drives the `PeerInterfaceFlapping` alert in Part 3. The panel isn't decoration — it's a visual representation of the rule that's about to fire. When the on-call gets paged, this panel is what they look at first.

#### 10. Switch device variable

> *"Now the proof that the variable was worth it. Toggle to srl2 and drive a flap there. No editing the panel — the dashboard does the work."*

Toggle the `Device` dropdown to `srl2`. The flap-rate panel re-queries and now shows `srl2`'s steady-state — mostly silent, with at most a single tick from the always-broken `ethernet-1/11` every two minutes. Same as `srl1` before you triggered its flap.

Trigger:

```bash
nobs packt flap-interface --device srl2 --interface ethernet-1/10
```

Watch the spike land on `srl2`'s `ethernet-1/10` line — same ramp shape, same threshold crossings, same recovery — without you editing the query.

**Stop and notice.** One panel, two devices. That's what the dashboard variable bought you. If you'd hard-coded `device="srl1"` in the query, you'd need a duplicate panel for every device you ever add — and one to maintain per device when the schema changes.

Worth noting: `srl1` and `srl2` arrive through different upstream pipelines (gNMI vs SNMP) — meaning the raw metric names and labels their devices emit look completely different. The lab **normalises** them in a layer above (renames the fields, re-keys the labels) so by the time your panel queries either device, they look identical. That's why the same `$device` variable works for both. The fold below walks the full normalisation pipeline if you want to see it end-to-end.

??? tip "Bonus — same panel, two pipelines"

    `srl1`'s metrics emit as raw gNMI shapes (`srl_*` field names) and Telegraf-srl1 normalizes them; `srl2`'s metrics emit as raw SNMP shapes (`ifHC*`, `bgpPeer*`) and Telegraf-srl2 normalizes them. By the time your panel queries them, both look identical — same metric names, same label keys. Hover the **Collection Type** panel on the Device Health dashboard to see which raw shape each device came in as.

    **See it yourself — five URLs walk the three layers of each pipeline:**

    1. **Raw gNMI from srl1** (sonda-server, before Telegraf): <http://localhost:8085/scenarios/metrics?label=source:srl1>. Look for `srl_*` metric names (`srl_interface_oper_state`, `srl_bgp_oper_state`) and the `source="srl1"` tag — what an SR Linux device emits on its gNMI stream.
    2. **Raw SNMP from srl2** (sonda-server, before Telegraf): <http://localhost:8085/scenarios/metrics?label=agent_host:srl2>. Look for the IF-MIB / BGP4-MIB names (`ifHCInOctets`, `bgpPeerState`, `cbgpPeerOperStatus`) and the `agent_host="srl2"` tag — the classic SNMP shape.
    3. **Telegraf-srl1's normalized output**: <http://localhost:9005/metrics>. The `srl_*` names are now plain `interface_*` / `bgp_*`, and the `source` tag has been renamed to `device`. Same data, canonical shape.
    4. **Telegraf-srl2's normalized output**: <http://localhost:9006/metrics>. The SNMP names (`ifHCInOctets`, etc.) are now also `interface_*` / `bgp_*`, and `agent_host` is now `device`. Identical to telegraf-srl1's output above — except for one label we keep on purpose: `collection_type=gnmi` vs `collection_type=snmp`, so you can debug which pipeline a sample came from.
    5. **Final view in Prometheus**: <http://localhost:9090/graph?g0.expr=interface_oper_state%7Bdevice%3D~%22srl1%7Csrl2%22%7D&g0.tab=1>. A single query for `interface_oper_state{device=~"srl1|srl2"}` returns rows from both devices in the same shape — the vendor difference is invisible at this layer.

> Your senior nods at the screen. *"That's the panel. Six hours from now when somebody on the rotation gets paged on a similar shape, this view is on screen the moment they open the dashboard. Ten minutes saved off the next triage. That's the work."*

---

## Part 2 — the rest of the alert lifecycle

Two steps from the alert-lifecycle walk that we skipped: reading alert state from the terminal, and the whole lifecycle drawn as one diagram. The CLI step slots in after step 1 (the rule, live); the diagram closes the walk.

#### 2. Inspect alerts from the CLI

The lab ships a small CLI that prints the current alert state in a table — same data Alertmanager has, just rendered for terminal use:

```bash
nobs packt alerts
```

> Give the cascade ~90 seconds from when you ran `flap-interface` before you expect the `PeerInterfaceFlapping` row to appear. The count crosses `> 3` after the first down phase, and the rule's `for: 30s` clause then has to hold before the alert promotes from `pending` to `firing`. If you check too early, you'll see only the four steady-state rows.

You'll see five rows once the alert fires. Before you look at them — a quick map of what to expect, because the lab is wired with a couple of *always-firing* alerts on top of whatever you just triggered. Two tiers:

- **Steady-state alerts** — always there, every time you walk this lab:
    - **`InterfaceAdminUpOperDown × 2`** — `ethernet-1/11` on each device is wired `admin up` but its `oper` state is `down` (the always-broken interface from step 3). The rule matches continuously; it never ages out.
    - **`BgpSessionNotUp × 2`** — two deliberately broken BGP peers (`srl1 → 10.1.99.2`, `srl2 → 10.1.11.1`). Same shape: the rule matches continuously. *Part 3 picks these up and acts on them.*
- **Transient alerts** — appear when something happens, age out when it stops:
    - **`PeerInterfaceFlapping`** — fires when your flap's rolling 2-minute count crosses `> 3`. Severity `critical`, scoped to the specific interface (`srl1/ethernet-1/1` if you flapped that). Resolves and ages out within ~5 minutes after the cascade ends.

Now run the command and read the output:

```
| Alertname                | Severity | Device / target  |   State |  Age |
| InterfaceAdminUpOperDown | warning  | srl1             |  firing |  ... |
| InterfaceAdminUpOperDown | warning  | srl2             |  firing |  ... |
| BgpSessionNotUp          | warning  | srl1 → 10.1.99.2 |  firing |  ... |
| BgpSessionNotUp          | warning  | srl2 → 10.1.11.1 |  firing |  ... |
| PeerInterfaceFlapping    | critical | srl1 → ethernet-1/1 |  firing | 30s |
```

Four steady-state rows + one transient — and the last column (`Age`) tells you which is which at a glance: `...` (long-running) vs `30s` (new).

> Your senior glances at the screen. *"Two-tier shape — the always-broken stuff sits there forever, and the things you actually want to know about come and go. Both are useful. The always-broken alerts tell you the lab knows about a problem someone hasn't fixed. The transient ones tell you something happened just now."*

#### 7. The lifecycle in one diagram

```text
   rule starts matching
            │
            ▼
        pending   ◄── for: 30s — the condition must hold this long first
            │
            ▼ (30s elapsed)
         firing   ◄── notifications go out (webhook, email, …)
            │
       ┌────┴────┐
       │         │
       ▼         ▼
  suppressed   resolved
  (silence    (condition
   applied)    stopped matching)
       │              │
       ▼              ▼
  (silence       (if the condition
   expires)      starts matching
       │         again, the alert
       ▼         re-enters `pending`)
     firing  ─── continues until condition resolves
```

Three transitions every alert can make — and `resolved` isn't a dead end: if the condition starts matching again later, the alert re-enters `pending` and the cycle restarts. Memorise this shape, it's the same on every alerting stack worth using.

??? info "Why has `BgpSessionNotUp` been sitting in `firing` this whole time? — preview of Part 3"

    `BgpSessionNotUp` has been sitting at `firing` for both devices the whole time you've been on this dashboard. They never resolved because the broken peers are *deliberately* broken — the lab keeps them that way as a steady-state target. In Part 3, a **workflow** (a small program that runs automatically when an alert fires) picks these alerts up via an **Alertmanager webhook** (an HTTP call Alertmanager makes to a configured URL every time an alert fires, so external systems can react to it), decides whether each one deserves human attention or can be silenced automatically, and applies the silence programmatically — exactly the same `firing → suppressed → firing` cycle you just walked by hand. Part 3 explains what the workflow is, how it's triggered, and what its decision policy looks like.

For now: you've seen the full alert surface. CLI, Alertmanager UI, Grafana ALERTS metric, manual silence. That's the substrate Part 3 builds on.

---

## Part 2 — stretch goals

### Stretch goals (optional — pick one if you have time)

#### Extend the Interface Traffic panel with a per-device aggregate

The existing **Interface Traffic** panel draws one line per interface. Add a second query that draws a single device-wide total on the same panel, styled so it visually stands out from the per-interface lines.

??? success "Solution — steps + what the panel looks like after"

    Open the **Interface Traffic** panel in edit mode. The per-interface queries already in the panel multiply by `* 8` to convert bytes/s into bits/s — anything you add must do the same or it'll render 8× smaller than the existing lines.

    **1. Add the aggregate query.** Click **+ Add query** below the first query. Paste the in+out aggregate, with the same unit conversion and the same rate window as the existing queries:

    ```promql
    sum(rate(interface_in_octets{device="$device"}[$__rate_interval])) * 8
      + sum(rate(interface_out_octets{device="$device"}[$__rate_interval])) * 8
    ```

    **2. Name the new series so the override can target it.** Below the query, in the per-query **Options** row, set **Legend** to **Custom** and type `Summary` in the field next to it. Without this step Grafana auto-names the series from its labels, which makes the next step harder — you'd have to target a label-based name like `{}` instead of a stable, friendly one.

    **3. Make it visually stand out.** In the right-hand options panel, scroll to **Overrides** → **+ Add field override** → **Fields with name** → pick `Summary` from the dropdown. Then click **+ Add override property** (once per property) and add:

    - **Graph styles → Line width**: `3` (thicker than the per-interface lines)
    - **Graph styles → Line style**: `Dash` (or pick a distinct colour instead — whichever reads more cleanly on your screen)

    **What the panel should look like after.** Two queries in the panel, both multiplied by `* 8` (bits/s):

    | Query | Expression | Legend |
    |---|---|---|
    | A (existing — in) | `rate(interface_in_octets{device="$device"}[$__rate_interval]) * 8` | (auto) |
    | A (existing — out) | `rate(interface_out_octets{device="$device"}[$__rate_interval]) * 8` | (auto) |
    | B (new) | `sum(rate(interface_in_octets{device="$device"}[$__rate_interval])) * 8 + sum(rate(interface_out_octets{device="$device"}[$__rate_interval])) * 8` | `Summary` (custom) |

    Plus one **Override** on `Fields with name = Summary`:

    - Graph styles → Line width: `3`
    - Graph styles → Line style: `Dash` (or a distinct colour)

    Result on screen: per-interface in/out lines tracking around ±50–100 kb/s, plus one thicker dashed `Summary` line sitting above them at roughly the absolute sum of the others.

#### Build a flap-history table with drill-through

> Your senior leans back in. *"Time-series tells you the shape. A table tells you the list — which device, which interface, how many flaps, click here to investigate. Build the second one. Make the device column a link into Device Health so a click takes you straight to the right view."*

Add a second panel: a table that summarises flap activity per device + interface over the last hour, with the **device** column as a clickable link into the **Device Health** dashboard, preserving the time window. This is the densest stretch goal — budget ~20 minutes if you're new to Grafana table panels, transformations, and data links.

??? success "Solution — full 8-step build + what the table looks like after"

    **1. Add the panel.** Back on the **Workshop Lab 2026** dashboard: click **Edit**, click the **`+`** in the right sidebar, click **Panel**, then click **Configure** in the panel settings that appear. Pick the **`loki`** datasource.

    **2. Write the query.** Toggle the query box to **Code** mode (the `Builder | Code` switch on the right of the query toolbar). Paste:

    ```logql
    sum by (device, interface) (count_over_time({vendor_facility_process="UPDOWN"}[1h]))
    ```

    A 1-hour window is "what's been flapping today" — wider than the 2-minute alert window so the table holds stable rows even between flaps.

    Below the query box, expand **Options** and switch **Type** from `Range` to `Instant`. For a table, we want one row per device + interface pair — not one row per time sample. Instant returns the most-recent value per series; Range would return a row per scrape interval, multiplying the table by 50× without adding signal.

    Click **Run query**.

    **3. Switch the panel type.** On the right-hand sidebar, click the **All visualizations** tab and pick **Table**. The result lands as a single-row table with a value column and the labels mashed into one cell — that's because Loki returns time-series-shaped data and the table needs help turning labels into proper columns.

    **4. Reshape with transformations.** Below the query box, click the **Transformations** tab → **Add transformation**. A search dialog opens with every available transformation as a tile.

    - Pick **Labels to fields**. Each Loki label (`device`, `interface`) becomes its own column.
    - Add a second transformation (click **Add another transformation**): **Organize fields by name**. Hide `Time` (click the eye icon next to it — the table doesn't need it), reorder so `device` is first and `interface` second, and rename `Value #A` to `Total flaps` in the rename input next to that row.

    You should now see one row per `device + interface` pair, with three clean columns: `device`, `interface`, `Total flaps`.

    **5. Title and description.** Right-hand options → **Panel options**:

    - **Title**: `Flap history (last 1h)`
    - **Description**: `UPDOWN events per device + interface over the last hour. Click any device cell to drill into Device Health for that device, time range preserved.`

    **6. Colour-code the flap counts with a gauge.** A glance at the table should tell you which rows are quiet and which are alarming without reading numbers. Right-hand options → **Overrides** → **Add field override** → **Fields with name** → pick `Total flaps`. Then click **Add override property** (once per property) and add:

    - **Cell options → Cell type**: `Gauge`
    - **Cell options → Gauge display mode**: `LCD gauge` (the retro pixel-bar style — coloured stripes that fill horizontally)
    - **Standard options → Min**: `0`
    - **Standard options → Max**: `100`
    - **Thresholds** (set them inside this same override): Green base, Orange at `30`, Red at `60`

    The threshold numbers are higher than the 2-minute flap-rate panel above because this table uses a **1-hour window**: the always-broken interfaces alone accumulate around 28 UPDOWN events per hour just sitting there. So below 30 is "background noise", 30–60 is "something extra is happening", and 60+ is "real flap activity in the last hour".

    Each row's `Total flaps` cell now renders as a horizontal LCD bar that fills green → yellow → red as the count climbs. At-a-glance triage without reading numbers.

    **7. Make the device cell a link.** Still in the right-hand options, scroll to **Overrides** → **Add field override** → **Fields with name** → pick `device`. On the override:

    - **Cell options → Cell type**: `Auto` (or `Color text` if you want the link visually distinct).
    - **Data links** → **Add link**:
        - **Title**: `Open Device Health for ${__value.text}`
        - **URL**: `/d/c78e686b-138b-4deb-b6ae-3239dc10a162?var-device=${__value.raw}&from=${__from}&to=${__to}`

    `${__value.raw}` is the cell's raw label value (`srl1`, `srl2`). `${__from}` and `${__to}` are the dashboard's current time-range bounds — the link carries the window forward so the destination dashboard opens on the same minutes you were just looking at.

    **8. Save and try it.** **Apply**, then **Save dashboard**. Trigger a flap:

    ```bash
    nobs packt flap-interface --device srl1 --interface ethernet-1/10
    ```

    Within a minute, a row for `srl1 / ethernet-1/10` shows up with a climbing `Total flaps` count. Click the `srl1` cell. Grafana jumps to **Device Health**, scoped to `srl1`, on the same time range you were on.

    **What the table should look like after.** Three clean columns (no `Time`, no `Value #A` — those got hidden / renamed by the Organize-fields transformation), four rows at rest:

    | device  | interface     | Total flaps                         |
    |---------|---------------|-------------------------------------|
    | srl1    | ethernet-1/1  | (number with horizontal LCD bar)    |
    | srl1    | ethernet-1/11 | ~28 (mostly green bar)              |
    | srl2    | ethernet-1/10 | (number with horizontal LCD bar)    |
    | srl2    | ethernet-1/11 | ~28 (mostly green bar)              |

    Visual cues:

    - The `device` cells are blue underlined links. Clicking `srl1` takes you to **Device Health** with `var-device=srl1` and the dashboard's current time range carried forward.
    - The `Total flaps` cells render as horizontal LCD gauges that fill green → orange → red as the count grows. Background noise (always-broken interfaces) sits around 28 (mostly green). An actively-flapping interface climbs past 60 in a few minutes and goes mostly red.

    **Stop and notice.** Tables are the dashboard equivalent of "a list of things to investigate, each row a one-click entry into deeper context". The time-series panel above tells you *something is flapping*. The table tells you *which one, how badly, and here's the next dashboard*. The data-link override is what binds the two dashboards into one navigation flow — no copy-pasting device names, no losing the time range.

#### Group the dashboard into tabs

The eight panels on **Workshop Lab 2026** are a lot to scroll past when you're triaging at 2am. Use Grafana 13's new **Group into tabs** feature to split the dashboard into a few tabs so each one answers one operational question instead of showing everything at once.

??? success "Solution — steps + what the dashboard looks like after"

    Grafana 13's **Group into tabs** works like browser tabs: only the active tab's panels render, so the page feels lighter and the queries run faster.

    In **Edit** mode, click **`+`** in the right sidebar, then **Group into tabs**. Drag panels into each tab using the layout below — a useful split for a real on-call:

    | Tab | Panels to include | What this tab answers |
    |---|---|---|
    | **Overview** | Devices · Interfaces · Firing alerts · Log lines (5m) | "Is anything wrong right now?" |
    | **Interfaces** | Interface Admin State · Interface Operational Status · Interface Traffic · Interface Logs | "What's the state of the device's interfaces?" |
    | **Flap** | Flap rate (per 2 minutes) · Flap history (the table you built above, if you did the table stretch goal) | "Which interface is flapping and how badly?" |

    **Save** the dashboard. Click between the tabs and check:

    - **Overview** shows the four stat panels (Devices · Interfaces · Firing alerts · Log lines).
    - **Interfaces** shows Interface Admin State · Interface Operational Status · Interface Traffic · Interface Logs.
    - **Flap** shows your Flap rate panel (and Flap history if you also did the table stretch goal).

    Drive a flap (`nobs packt flap-interface --device srl1 --interface ethernet-1/1`) and click into the **Flap** tab — the view is exactly what an on-call would open on a `PeerInterfaceFlapping` page.

    If a panel ended up in the wrong tab, drag it between tabs while in Edit mode. The provisioned YAML resets the layout on `nobs packt restart grafana`, so don't worry about breaking anything permanently.

    **Stop and notice.** Tabs only change how the dashboard is laid out — the panels and queries themselves don't change. What changes is *which questions the dashboard answers when you open it*. The Overview tab is for "is anything wrong"; the Flap tab is for "show me the symptom" — different operational questions, same dashboard, same data. Building this split before an incident means the page lands and the right view is already there.

---

## Part 3 — swap in a real LLM

The session ran the whole of Part 3 on the **demo** RCA provider — a deterministic template, free and offline, which is the right default for a room full of laptops. This section swaps it for a real model so you can read the two narratives side by side on the same evidence. You need an OpenAI or Anthropic API key; the cost is a few cents.

#### 6. (Optional) Swap to a real LLM provider for the narrative

Every decision you've seen so far has been **deterministic**: the workflow looks at the evidence and makes a yes/no call based on a fixed rule. *Same inputs, same outputs, every time.* That's by design — the workflow has to be replayable, reviewable, auditable.

What you've *also* been seeing since Setup is the **AI RCA** step — a short narrative the workflow writes alongside each `proceed` decision (the records with `ai_rca="true"` in your Loki queries). RCA stands for *Root Cause Analysis*. **The AI does not decide what to do.** The deterministic policy still picks `proceed` or `skip`. The AI just writes a paragraph alongside the decision — think of it as the on-call's first-draft writeup, generated automatically and stapled to the audit record.

The `demo` provider you enabled in Setup writes a *templated* narrative — deterministic, free, offline, but only as smart as the evidence dict it stitches together. **This phase is the optional upgrade**: swap to a real LLM (OpenAI or Anthropic) with an API key, and the workflow makes a real model call. Same evidence in, real reasoning out. Skip this phase if you don't have a key — none of Part 3's lessons depend on it.

??? tip "Going further — three common gotchas when wiring up a real OpenAI or Anthropic key"

    Worth a 30-second skim before you set a real API key.

    **ChatGPT Plus is not the same product as the OpenAI API.** They share a login but have separate billing — a Plus subscription gives you ChatGPT.com access only; it does **not** include API credits or higher API rate limits. A fresh API key on an account that's never funded the API will return `429 Too Many Requests` on the very first call (the free-tier API quota is $0). Fix: go to <https://platform.openai.com/settings/organization/billing/overview>, add a payment method, prepay $5 (a single RCA call costs roughly $​0.001–$​0.01 depending on the model), wait ~1–2 minutes for the credit to propagate, then retry.

    **`AI_RCA_MODEL` must be a real model identifier.** The string gets sent verbatim to the provider's `/chat/completions` (OpenAI) or `/messages` (Anthropic) endpoint, so a typo means a server-side error — usually `404 model_not_found`, sometimes wrapped as `429` depending on the account state. Use a real OpenAI model like `gpt-4o-mini`, `gpt-5`, or `gpt-5-mini`; for Anthropic, something like `claude-haiku-4-5-20251001`. If Loki shows `AI RCA call failed: HTTPError: 4xx ...`, the model string is the first thing to check.

    **After any `.env` edit, re-run `nobs packt up`** (or the underlying `docker compose --project-name packt up -d --force-recreate prefect-flows`). A plain `docker compose restart prefect-flows` will *not* pick up the new value — `restart` reuses the container's existing env, while `up -d` recreates it against the current `.env`. If you swap an API key and then see `401 Unauthorized` in Loki, the container is almost certainly still holding the old (revoked) key. Quick check that the container actually got the new key — compare `tail=` against the last four chars of the key in your `.env`:

    ```bash
    docker compose --project-name packt exec prefect-flows \
      python3 -c "import os; k=os.environ.get('OPENAI_API_KEY',''); print(f'len={len(k)} head={k[:7]} tail={k[-4:]}')"
    ```

    If they don't match, the container is stale — re-run `nobs packt up`.

    **Reasoning models (`gpt-5`, `o1`, `o3`) often exceed the workshop's HTTP timeout.** They think internally before answering and a single call can take 30–60+ seconds. The lab's HTTP client gives up after 60s and writes `AI RCA call failed: ReadTimeout: ...` to Loki. Stick with `gpt-4o-mini`, `gpt-5-mini`, or `claude-haiku-4-5-20251001` for the workshop — they respond in 1–3 seconds, the narrative is short and bounded, and you don't pay reasoning-model rates for output a faster model already nails.

##### Step 1 · Swap the provider and key in `.env`

Edit `workshops/packt/.env` — `ENABLE_AI_RCA=true` stays as-is from Setup; you're only swapping the provider and adding a key:

```bash
AI_RCA_PROVIDER=openai          # or anthropic
AI_RCA_MODEL=gpt-4o-mini        # or claude-haiku-4-5-20251001
OPENAI_API_KEY=sk-...           # or ANTHROPIC_API_KEY=sk-ant-...
```

Then reload the workflow container so the new env takes effect (a plain `docker compose restart` won't — see the gotchas fold above for why):

```bash
nobs packt up
```

##### Step 2 · Trigger a fresh cycle and read the new narrative

```bash
nobs packt cycle srl1 10.1.99.2 --trigger
nobs packt rca srl1 10.1.99.2
```

The first command posts a fresh alert payload (bypassing Alertmanager's `repeat_interval`) and re-renders the cycle state once the new flow run lands. The second renders the latest AI narrative for that peer as Markdown in the terminal.

Compare the rendered narrative to the demo voice you've been seeing all along. A real LLM (OpenAI or Anthropic) typically adds:

- **Domain inference** — translates raw metric values into operational hypotheses ("`oper_state=5` with `received_routes=0` is consistent with a TCP reachability failure or AS-number mismatch — the FSM is trying but not authenticating") instead of just restating them.
- **Wider context** — references the BGP state machine, common causes for "stuck in active", suggested next debug steps (traceroute, configured remote-as check).
- **Calibrated uncertainty** — phrases like "most likely" or "consistent with" rather than confident pronouncements.

The deterministic policy decision is **unchanged** between demo and real provider. The narrative is the only thing that swapped — different voice, identical evidence, identical decision.

!!! tip "Read the narrative in its rendered shape"

    The query above shows each JSON field on its own row — handy for inspecting structure, but hard on the eyes for prose. To render `message` with its markdown headers and bullets intact, swap to:

    ```logql
    {source="prefect", ai_rca="true"} | json | line_format "{{ .message }}"
    ```

    The `line_format` directive replaces the rendered log line with just the unescaped `message` value (the `| json` parser has already turned the `\n` escapes into real newlines). Turn on **Wrap lines** in the Grafana Logs view toolbar so the multi-line narrative wraps instead of scrolling sideways.

    Prefer the terminal? Same data, rendered as Markdown:

    ```bash
    nobs packt rca srl1 10.1.99.2
    ```

    Most-recent narrative for that device/peer pair. Both args are optional (omit to see the latest record across the lab); add `--last 3` to compare several recent runs side by side, `--minutes 180` to widen the lookback window.

??? info "What the demo AI RCA narrative actually contains"

    With `AI_RCA_PROVIDER=demo`, the workshop ships a templated narrative that fills three sections (Most likely cause / Immediate actions / What to verify next) from the same evidence the deterministic policy reads. Here's what the demo writes for the broken peer:

    ```text
    AI RCA:
    (demo narrative — set AI_RCA_PROVIDER=openai|anthropic with an API key
    for a real model response.)

    ## Most likely cause
    SoT expects peer 10.1.99.2 on srl1 to be established, with intent reason 'ip-mismatch-demo',
    but oper_state=5 (active), admin_state=1 (enable), received_routes=0.

    ## Immediate actions
    - Inspect reachability and timers between srl1 and 10.1.99.2

    ## What to verify next
    - Tail Loki for device=srl1 around the alert window for BGP state transitions
    - Check whether the SoT reason 'ip-mismatch-demo' matches a known fault class
    - Compare received_routes=0 against expected_prefixes_received in the SoT
    ```

    This lands in Loki as one log line with these labels:

    ```
    ai_rca=true
    device=srl1
    peer_address=10.1.99.2
    source=prefect
    workflow=packt_quarantine_bgp
    severity=info
    ```

    The narrative is grounded in the *same* evidence the deterministic policy used — SoT's `expected_state`, the metric values, the prefix counter. The template doesn't invent facts; it stitches the evidence into prose. When you flip `AI_RCA_PROVIDER` to `openai` or `anthropic` later, the model gets that same evidence dict and writes its own three-section response — different voice, identical inputs. The `ai_rca="true"` label is what distinguishes these records from the deterministic `decision=...` records in the same Loki stream.

The split between **decision** (deterministic) and **narrative** (AI) is the lesson the workshop is most insistent about — see [Part 3, step 4 §C](../../../docs-packt/part-3.md#c-the-ai-narrative-same-evidence-different-voice) for the *big idea* framing. With a real LLM provider, the narrative side gets richer; the deterministic decision is unchanged.

!!! tip "Done experimenting? Revert to the offline `demo` provider"

    Two-step revert. In `workshops/packt/.env`:

    ```bash
    AI_RCA_PROVIDER=demo
    ```

    Then reload the container so the new env takes effect (a plain `docker compose restart` won't pick up `.env` changes):

    ```bash
    nobs packt up
    ```

    The workflow keeps writing AI RCA annotations, but they're templated again — no API calls, no cost. (Leave your API key in `.env`; it's ignored when the provider is `demo`.) If you'd rather turn the step off entirely, set `ENABLE_AI_RCA=false` instead.

---

## Part 3 — deep dives

### Optional deep dives

The phases above walk one full cycle with all the concepts spelled out. If you want to go further — see all four paths run at once, look at the workflow in the Prefect UI, or trigger the workflow directly without an alert — pick whichever fold sounds useful. Each one is independent of the others.

??? info "Walk all four paths at once with `try-it --auto`"

    The phases above had you walk one path by hand (`proceed`) and then a second path by flipping a flag (`skip` via maintenance). The workshop also ships a single command that walks *all four* paths in about 30 seconds with synthetic payloads, so you can see the whole arc at once:

    ```bash
    nobs packt try-it --auto
    ```

    You should see four `✓` rows print:

    ```
    ╭─── Path 1 - Actionable / mismatch → proceed ───╮
       ✓ replayed firing payload for srl1 → 10.1.99.2
       ✓ quarantine flow decided 'proceed' for the actionable mismatch

    ╭─── Path 2 - In-maintenance → skip ───╮
       ✓ srl1.maintenance = True
       ✓ replayed firing payload for srl1 → 10.1.99.2
       ✓ quarantine flow saw maintenance=true and skipped

    ╭─── Path 3 - Healthy peer → skip ───╮
       ✓ replayed firing payload for srl1 → 10.1.2.2
       ✓ quarantine flow decided 'skip' for healthy peer

    ╭─── Path 4 - Resolved → audit ───╮
       ✓ replayed resolved payload for srl1 → 10.1.99.2
       ✓ resolved_bgp_flow ran and annotated 'resolved'
    ```

    Each path posts an alert payload directly to the webhook and waits for the matching log line to land in Loki. Four `✓` rows means the workflow walked every branch correctly. After it finishes, Phase 7's LogQL query gives you the aggregated counts across all four paths.

??? info "Tour the Prefect UI"

    Everything you've seen in this part has happened *through* a Prefect workflow. Prefect's UI lets you look at the workflow from a different angle — task graph, per-task logs, run history. The Loki audit trail is the record; the Prefect UI is the workshop.

    Open Prefect at <http://localhost:4200/runs>. If a "Join the Prefect Community" pop-up appears, click **Skip** to dismiss it — it's a sign-up prompt, unrelated to the lab. Sort by **Start Time** (newest first) and click the most recent `quarantine_bgp | …` flow run.

    You'll see:

    - **Subflow runs** — three rows nested under the parent run: `evidence`, `policy`, `action`. Same three blocks as the Phase 2–4 walk. Click one to see its tasks — `fetch_sot` / `fetch_metrics` / `fetch_logs` / `assemble_evidence` under `evidence`, `evaluate_sot_gate` / `evaluate_metrics_gate` / `annotate_decision` under `policy`, `ai_rca` / `quarantine` / `annotate_action` under `action`.
    - **Per-task logs** — every line the workflow printed, indexed by task. Same content as `nobs packt logs prefect-flows`, but searchable per task.
    - **Tags** — labels on each task like `device:srl1`, `peer_address:10.1.99.2`, `action:quarantine`. These are what an operator filters on to find "every run that touched this peer."


??? tip "Trigger the workflow directly without an alert"

    The webhook is one way to drive the workflow. You can also drive it manually from the CLI — useful when you want to skip the alert lifecycle entirely (no Alertmanager `repeat_interval` wait), test a payload shape, or iterate on the policy.

    The workshop wrapper is:

    ```bash
    nobs packt cycle srl1 10.1.99.2 --trigger
    ```

    Under the hood, the wrapper posts an `AlertmanagerAlert`-shaped payload to the Prefect `alert_receiver` flow's webhook, polls Prefect until a fresh flow run appears for this peer, then renders the resulting state. The raw `prefect deployment run` equivalent (useful when scripting outside the lab) is:

    ```bash
    docker compose --project-name packt exec prefect-flows \
      prefect deployment run alert-receiver/alert-receiver \
      --param alertname=BgpSessionNotUp \
      --param status=firing \
      --param 'alert_group={"alerts":[{"labels":{"device":"srl1","peer_address":"10.1.99.2","afi_safi_name":"ipv4-unicast"}}],"groupLabels":{"alertname":"BgpSessionNotUp"},"status":"firing"}'
    ```

    Same workflow, same decision logic, no alert. To exercise the resolved-bgp branch instead of quarantine, use `cycle --status resolved`.

??? tip "Flap without the BGP cascade"

    `nobs packt flap-interface --device srl1 --interface ethernet-1/1` causes a full cascade — the interface flap drags the BGP session down with it, which fires `BgpSessionNotUp` and runs the workflow. If you only want to exercise the `PeerInterfaceFlapping` alert (the Loki-rule one from Part 2) *without* touching BGP, pass `--no-cascade`:

    ```bash
    nobs packt flap-interface --device srl1 --interface ethernet-1/1 --no-cascade
    ```

    BGP stays up, `BgpSessionNotUp` stays clean, and the workflow never fires. Useful when you want to exercise the Loki alert path in isolation.

??? info "What the workflow actually looks like in Python"

    The `quarantine_bgp_flow` you've been walking is a Python function. The whole thing is short enough to read end-to-end:

    ```python
    @flow(log_prints=True, flow_run_name="quarantine_bgp | {device}:{peer_address}")
    def quarantine_bgp_flow(device, peer_address, ...):
        ev = evidence_flow(device=device, peer_address=peer_address, ...)
        decision = policy_flow(device=device, peer_address=peer_address, ev=ev)
        outcome = action_flow(device=device, peer_address=peer_address, decision=decision, ev=ev, ...)
        return {...}
    ```

    Three calls, one per block of the cycle you walked across Phases 2–4. Each block is a flow of its own with its own tasks, which is why `evidence`, `policy` and `action` appear as separate rows in the Prefect UI and in `nobs packt cycle`. The `@flow` decorator on top is what gives this a UI, retries, per-task logs, and a queryable record. "Automation" here is a Python function with decorators on top.

    Full source: [`workshops/packt/automation/flows.py`](https://github.com/network-observability/workshops/blob/main/workshops/packt/automation/flows.py).

??? info "Chain another workflow when this one completes"

    Prefect can also fire a *second* workflow whenever this one completes — useful for hooking in notifications, opening tickets, or kicking off a follow-up runbook. The pattern is called a **Prefect Automation** ("when X happens, do Y").

---

## Part 3 — stretch goals

### Stretch goals (optional — pick one if you have time)

- **Tail the Prefect flow logs in real time.** Watch a flow run from the inside, line-by-line, so you can correlate every decision in the audit-record trail with the task that produced it.

    ??? success "Solution — how to tail, plus what you'll see in the log stream"

        Run `nobs packt logs prefect-flows` in one terminal, then re-run `nobs packt try-it --auto` in another.

        Each `try-it --auto` cycle produces a burst of log lines, grouped by the three blocks. For a `proceed` path (trimmed):

        ```text
        Flow run 'evidence | srl1:10.1.99.2' - Beginning subflow run
        Task run 'fetch_sot[srl1:10.1.99.2]' - 🔎 [evidence] SoT gate for srl1:10.1.99.2 (ipv4-unicast)
        Task run 'fetch_metrics[srl1:10.1.99.2]' - 🔎 [evidence] BGP metrics snapshot for srl1:10.1.99.2
        Task run 'fetch_logs[srl1:10.1.99.2]' - 🔎 [evidence] last 30m of logs for srl1:10.1.99.2
        Task run 'assemble_evidence[srl1:10.1.99.2]' - ✅ [evidence] sot.found=True maintenance=False intended=True expected_state=established reason='ip-mismatch-demo'
        Task run 'assemble_evidence[srl1:10.1.99.2]' -    metrics={'admin_state': 1.0, 'oper_state': 5.0, 'received_routes': 0.0, ...}
        Task run 'assemble_evidence[srl1:10.1.99.2]' -    logs collected: 50 lines
        Flow run 'policy | srl1:10.1.99.2' - Beginning subflow run
        Task run 'evaluate_sot_gate[srl1:10.1.99.2]' - 🧠 [policy] stage1 SoT-only → proceed (SoT expects up; metrics not provided (collect evidence))
        Task run 'evaluate_metrics_gate[srl1:10.1.99.2]' - 🧠 [policy] stage2 SoT+metrics → proceed (SoT expects peer up, but metrics show mismatch)
        Task run 'annotate_decision[srl1:10.1.99.2]' - 📝 [annotate] decision=proceed reason=SoT expects peer up, but metrics show mismatch
        Flow run 'action | srl1:10.1.99.2' - Beginning subflow run
        Task run 'ai_rca[srl1:10.1.99.2]' - 🤖 [ai_rca] running (gated by ENABLE_AI_RCA)
        Task run 'quarantine[srl1:10.1.99.2]' - 🔕 [quarantine] silencing srl1:10.1.99.2 for 20m
        Task run 'quarantine[srl1:10.1.99.2]' - ✅ [quarantine] silence id=d9419759-0b0a-40ce-8bda-21e6298b0bb3
        ```

        The `[evidence]` lines show the exact SoT + metric values the policy will see. The `[policy]` lines show which stage answered and why — on a maintenance run, `evaluate_metrics_gate` is absent because stage 1 already returned `skip`. The `[annotate]` line carries the same `decision` and `reason` you find in Loki under `{source="prefect"}`. Tailing the logs is the fastest debug loop when the flow returns an unexpected decision — every intermediate value is visible without a single LogQL query.

- **Compare evidence between a healthy peer and a broken one.** Both peers share the same SoT intent, but the policy fires `proceed` on one and `skip` on the other. Find the field that drives the difference.

    ??? success "Solution — commands to run and what differs between the two"

        Run both:

        ```bash
        nobs packt evidence srl1 10.1.2.2   # a healthy peer
        nobs packt evidence srl1 10.1.99.2  # a broken one
        ```

        Both peers share the same *intent* in the SoT (`expected_state: established`) — the SoT can't tell which one is broken on its own. What separates them is **reality**, in the metrics:

        | Row | Healthy `10.1.2.2` | Broken `10.1.99.2` |
        |---|---|---|
        | SoT `expected_state` | `established` | `established` ← same |
        | SoT `reason` | empty | `ip-mismatch-demo` |
        | Metric `admin_state` | `1 (enable)` | `1 (enable)` ← same |
        | Metric `oper_state` | `1 (established)` | `5 (active)` |
        | Metric `received_routes` | `10` | `0` |
        | Policy hint | `skip — peer matches SoT intent` | `proceed — SoT vs metrics mismatch` |

        The policy fires `proceed` when `expected_state=established` AND `oper_state ≠ 1`. Both peers have the same SoT intent — the *gap* between intent and reality is what the policy keys on.

- **Toggle maintenance on srl2 instead of srl1.** The maintenance-skip path isn't hard-coded to a specific device. Confirm it by flipping maintenance on srl2 instead and verifying the skip swapped devices.

    ??? success "Solution — commands + verify in Loki that the skip swapped device"

        `nobs packt try-it --auto` only walks srl1 paths, so it won't exercise srl2. Use `cycle --trigger` pointed at srl2's broken peer instead:

        ```bash
        nobs packt maintenance --device srl2 --state
        nobs packt cycle srl2 10.1.11.1 --trigger
        ```

        The `cycle` command renders the fresh state once the flow run lands — you should see `decision=skip` in the Most-recent-decision panel with the reason `"device under maintenance"`. To confirm in Loki directly:

        ```logql
        {source="prefect", workflow="packt_quarantine_bgp", decision="skip", device="srl2"} | json
        ```

        Same record. The `message` is `"device under maintenance"` — same reason the policy gave for srl1 earlier, only the subject changed.

        The point of the exercise: the policy is **device-agnostic**. It consults the SoT for whichever device the alert payload names. Flipping maintenance on any device routes that device's alerts to skip, automatically. The decision logic isn't hard-coded to a particular device.

        Don't forget `nobs packt maintenance --device srl2 --clear` afterwards (or run `nobs packt reset` — it clears both devices).

- **Watch a path's audit records in Loki directly.** Every Prefect decision lands as a structured JSON record in Loki. Tail them live to see the audit trail being written as you trigger paths.

    ??? success "Solution — LogQL query + the audit-trail shape"

        In Grafana Explore on the Loki datasource, paste:

        ```logql
        {source="prefect", workflow="packt_quarantine_bgp"} | json
        ```

        Each record has this shape (Grafana parses the JSON inline, so every field renders right under the row):

        ```json
        {
          "timestamp": "...",
          "severity": "info",
          "message": "SoT expects peer up, but metrics show mismatch",
          "labels": {
            "decision": "proceed",
            "device": "srl1",
            "peer_address": "10.1.99.2",
            "source": "prefect",
            "workflow": "packt_quarantine_bgp"
          }
        }
        ```

        Add `| decision="proceed"` (or `decision="skip"` / `decision="resolved"`) to filter to one path. Triggering a flap or running `nobs packt try-it --auto` in another tab produces fresh annotations in real time — flip the time picker's **Live** mode on to watch them stream in.

        Step 5's unguided LogQL query (`sum by (decision) (count_over_time({source="prefect"}[1h]))`) rolls these annotations up by `decision` label — the same audit-trail data, just aggregated.

- **Swap the AI RCA provider.** Compare the templated demo provider's RCA narrative against a real LLM's. What does the LLM add that the template can't?

    ??? success "Solution — how to switch providers + guidance on the comparison"

        If you have an OpenAI or Anthropic key, set `AI_RCA_PROVIDER=openai` (or `anthropic`) in `workshops/packt/.env` along with the matching `AI_RCA_MODEL` and `OPENAI_API_KEY` / `ANTHROPIC_API_KEY`. Then run `nobs packt up` to recreate the flow container against the new env (a plain `docker compose restart` won't pick the values up — see the **Going further — three common gotchas** fold under Step 1 above for the full why).

        Trigger a quarantine path so the workflow runs end-to-end with AI RCA on:

        ```bash
        nobs packt try-it --auto
        ```

        Path 1 (firing → quarantine on `srl1:10.1.99.2`) lands on `decision=proceed`, which is the only decision that invokes AI RCA — so the new narrative lands in Loki under `ai_rca="true"`. (Paths that resolve to `skip` write a brief annotation instead, explaining why the LLM was not run — same `ai_rca="true"` label.) Read it straight from the terminal — same data the Loki query in Step 3 returned, rendered as Markdown in a Rich panel:

        ```bash
        nobs packt rca srl1 10.1.99.2
        ```

        Add `--last 3` to compare the most recent runs side by side — useful right after a provider swap to see the same evidence rendered by two different models.

        The demo provider produces a templated narrative — it stitches evidence-bundle fields into the same paragraph structure every time:

        ```text
        ## Most likely cause
        SoT expects peer 10.1.99.2 on srl1 to be established, with intent reason
        'ip-mismatch-demo', but oper_state=5 (active), admin_state=1 (enable),
        received_routes=0.
        ```

        A real LLM (OpenAI or Anthropic) typically adds:

        - **Domain inference** — translates the raw numbers into operational hypotheses ("`oper_state=5` with `received_routes=0` is consistent with a TCP-level reachability failure or AS-number mismatch — the FSM is trying but not authenticating").
        - **Wider context** — references the BGP state machine, common causes for "stuck in active", suggested next debug steps (traceroute, configured remote-as check).
        - **Calibrated uncertainty** — phrases like "most likely" or "consistent with" rather than confident pronouncements.

        The template can't do any of this — it can only fill slots. But the template is **deterministic** and **free**; the LLM is **inference-richer** but **non-deterministic** and costs per call. The trade-off is the lesson: the policy *decides what to act on*; the narrative — template or LLM — *explains why for a human reader*. Pick the right narrative tool for the audience and the budget.

---

## Advanced — the 02:14 page

The capstone the session never had room for. Hours after your senior signs off, your phone rings and you are alone on the rotation. Triage with PromQL and LogQL, contain with maintenance, fix the root cause, write the runbook — end to end, no buddy, no runsheet.

Do the rest of this page first. This one assumes Parts 1, 2 and 3 are behind you and does not re-explain anything.

### What you'll do here

It's 02:14. Your phone just buzzed. By the end of this guide you'll have triaged the page with PromQL and LogQL, watched a real cascade unfold across the dashboards, built a panel that would have caught it sooner, contained the noise with the maintenance flow, simulated the fix, and written the top of your own runbook entry.

This is the workshop's capstone. It assumes Parts 1, 2, and 3 are already behind you — the metric names, the basic PromQL/LogQL patterns, the dashboard layouts, and what `nobs packt alerts`, `flap-interface`, and `maintenance` do are all going to come out under time pressure here. If you haven't walked the three core guides yet, do those first; the pacing here will leave you behind otherwise. Budget **60 to 90 minutes** of wall-clock — longer than the part-guides on purpose, because you're integrating everything.

### Setup check

Confirm the command is available:

```bash
nobs packt incident --help
```

You should see options for `--device`, `--primary-interface`, `--backup-interface`, `--duration`, and `--kind` (default `link-failover`). If `incident` isn't a recognised subcommand, pull and re-run.

Reset to known-good baseline and confirm the stack is healthy. The investigation puts the lab into states the part guides didn't — so the reset matters more here. Run it before you start:

```bash
nobs packt reset
nobs packt status
```

`reset` is safe to run repeatedly — it re-loads the Infrahub source-of-truth, clears any device maintenance flags, re-applies sonda's baseline scenarios (so the steady-state broken peers stay firing), and expires any workshop-related Alertmanager silences. `status` should show every row `ok`; if anything is yellow or red, flag it before continuing.

Two browser tabs ready:

- **Workshop Home** at <http://localhost:3000/d/workshop-home> — situational awareness, alerts table, recent events feed.
- **Workshop Lab 2026** at <http://localhost:3000/d/dfb5dpyjbh2wwa> — the dashboard you'll lean on in Act 4 as the incident unfolds.

Ensure AI RCA analysis is enabled. Open the workshop's `.env` file at `workshops/packt/.env` and flip these two lines:

```bash
ENABLE_AI_RCA=true
AI_RCA_PROVIDER=demo
```

Don't forget to reload the workflow after enabling AI RCA:

```bash
nobs packt up
```

A scratch text file open on the side. The closing act has you write the top five lines of your own runbook entry, and you'll want somewhere to put them.

### The exercises

#### Act 1 — The page

```
PAGED 02:14
BgpSessionNotUp on srl1 — peer 10.1.99.2 not reaching Established
last seen Established: ~3 minutes ago
You're awake. The dashboard is your only friend.
```

Recognise that peer? `10.1.99.2` is the deliberately broken peer you found in Part 1 with the intent-vs-reality query. The alert has been firing in the background of the lab the whole day — it's been there waiting for someone to actually respond to it. Tonight, that's you.

First move from the couch: confirm the page is real and the alert is still firing.

```bash
nobs packt alerts
```

You'll see four alerts firing — the two `BgpSessionNotUp` rows (one per broken peer) and the two `InterfaceAdminUpOperDown` rows you met in Part 2. Tonight's page is the **srl1 → 10.1.99.2** row in the first group. The other three are the same steady-state noise that's been on the dashboard all day. **Stop and notice.** This isn't an alert the cascade just manufactured — it's the alert that's been firing since the lab started up, because the lab is set up with a deliberately broken peer wired in. The page is real in lab terms. So: what do you do next?

#### Act 2 — Triage with PromQL and LogQL

Triage is a decision tree, not a single query. You don't yet know what kind of failure this is. Work through it step by step — each query rules out a class of failure.

**Is the device itself unhealthy?** Check CPU and memory in the `prometheus` datasource:

```promql
cpu_used{device="srl1"}
```

```promql
memory_utilization{device="srl1"}
```

Both should sit in normal range. **Conclusion:** the device is fine. This isn't a CPU pegging or a memory leak; it's not the box.

**Are interfaces flapping?** Check the operational state:

```promql
interface_oper_state{device="srl1"}
```

Most interfaces read `1` (UP). You'll see one — `ethernet-1/11` — at `2` (DOWN). That's the always-broken interface you met in Part 1; it's why one of the `InterfaceAdminUpOperDown` alerts is firing. For tonight's page (a BGP session not coming up to a peer), it's a known-quantity background fault, not the symptom. **Conclusion:** no *new* interface fault. The lit interfaces are healthy — whatever is going on, it isn't on the wire to the broken peer's network. This is BGP-only.

**Is the peer reachable at the BGP layer?** Check intent and reality on this specific peer:

```promql
bgp_admin_state{device="srl1", peer_address="10.1.99.2"}
```

```promql
bgp_oper_state{device="srl1", peer_address="10.1.99.2"}
```

Admin reads `1` — the configured intent is "this peer should be up". Oper reads `5` — `active, retrying` in the gNMI enum convention from Part 1. Reality says "BGP is trying and not succeeding". **Conclusion:** intent-vs-reality mismatch on this specific peer. This is exactly what the alert is firing on.

**Is there a log line that explains why?** Bridge to Loki — same labels, different datasource:

```logql
{device="srl1", peer_address="10.1.99.2"} |~ "BGP|peer|session"
```

You'll see BGP-related lines for that specific peer — fsm transitions, retry attempts, whatever the lab's continuous emitters are producing for the broken session. The metric told you *something* is wrong. The logs tell you *why*.

**Stop and notice.** You narrowed down the problem from a single alert to a specific peer with a specific configured intent that reality isn't matching. This is the triage every on-call walks. The fact that it took four queries instead of one says you're doing it right — `count by` collapses noise, `bgp_oper_state` answers the targeted question, the LogQL bridge explains the why. You worked top-down: device, interface, peer, log evidence. Each layer ruled out a class of failure before you went deeper.

!!! tip "Want to see what the automation already thinks about this alert?"

    The workflow has been running on this alert in the background — it heard the same `BgpSessionNotUp` page you did, walked its own version of the triage tree, and wrote a narrative to Loki. Read it from the terminal:

    ```bash
    nobs packt rca srl1 10.1.99.2
    ```

    Compare it against your own conclusion. Where does the narrative agree with what you found? Where does it surface something you missed — or miss something you caught? A useful frame for the rest of the investigation: automation does the routine work, the human does the judgment. (If the output reads *"AI RCA disabled..."*, the AI step is off — go back and check the setup instructions at the top of this guide. You may also need to wait a moment for the Prefect workflow to complete, then try again.)

#### Act 3 — Diagnose: drive the cascade and walk the shape

While you were triaging, things escalated. A different problem started developing on the same device — the kind of cascade that starts with a flap and ends with customers complaining about latency. Time to drive it and read it as it unfolds:

```bash
nobs packt incident --device srl1
```

The CLI returns immediately and prints three IDs (one per cascade stage). The cascade is now unfolding in the lab — wall-clock timing is in the callout below. Open the **Workshop Lab 2026** dashboard — you'll be running three queries against the `prometheus` datasource in Explore as the incident develops. The **Workshop Home** dashboard's **Recent events** feed is also reflecting it; switch tabs occasionally to keep both in view.

**The first thing that catches your eye — primary degrading.** The interface starts flipping:

```promql
interface_oper_state{device="srl1", source="incident-cascade"}
```

Switch to **Time series**. Within seconds you'll see the line flip between `1` (up) and `0` (down). Roughly 60s up, 30s down. An interface flap is the classic *something physical is wrong* signal — in a real network this is what makes you walk to the rack. By default the cascade targets `ethernet-1/10` as the primary — that's the line that flips. The `source="incident-cascade"` filter scopes the query to this incident's signals and keeps the lab's baseline interface noise (Parts 1–3's always-broken `ethernet-1/11`, etc.) off this chart.

**Stop and notice.** The values are `0` and `1`, not the `1`/`2` gNMI-enum pair you saw in Parts 1–3. This cascade is a different shape of incident — generic up/down rather than the BGP-coupled interface story — so it emits with the simpler `0`/`1` scheme and the unique `source=incident-cascade` label. That's also why the existing `BgpSessionNotUp` alert doesn't trip on this incident: the alert rule matches on `bgp_oper_state`, and this cascade emits its own three signals, none of them `bgp_oper_state`. Different incidents, different signal shapes, different alerts. The label is the scoping handle that keeps them separable.

**Did failover work?**

```promql
incident_backup_link_utilization{source="incident-cascade"}
```

Empty for the first ~60 seconds — you'll see "no data" or a flat panel. Once the primary drops to `0` for the first time, the metric appears and ramps from around 20% toward 85% over the next two minutes.

**Stop and notice.** The backup didn't start carrying traffic until the primary actually failed. That's failover working as intended. But notice the *direction* — utilisation is climbing past where the link is comfortable. This is the early-warning shape an experienced on-call reads as *we're going to have a latency problem in a couple of minutes if this doesn't recover*. The empty panel for the first minute isn't a query bug — backup-utilisation samples only start landing once the failover is real. Empty panels at the start of an incident are information, not bugs.

**The symptom your customers feel — latency:**

```promql
incident_latency_ms{source="incident-cascade"}
```

Empty even longer — latency only starts emitting once the backup has saturated past its baseline, so for the first couple of minutes the panel is silent. Once it lights up, it ramps from ~5ms toward 150ms over three minutes. The chain effect is a feature, not a bug: latency-as-a-symptom typically arrives a few minutes after the root cause is already in motion.

**Stop and notice.** By the time latency is the visible problem, the actual root cause — the primary uplink fault — happened minutes ago. This is why incident timelines matter. The latency spike is a *symptom*. The flapping interface was the *cause*. If your alert fires on latency, your runbook needs to walk back through the cascade to find the real failure. The cascade is the story; the metrics are the chapters. Operators read incidents this way every day.

??? info "Why the cascade takes longer than the --duration flag suggests"

    There's a wall-clock detail worth calling out. The default `--duration 3m` is the bounded lifetime of *each* signal in the cascade, not the total lifetime end-to-end. Each phase has to wait for the previous one to escalate before it starts (the flap has to drop, then backup has to saturate past 70%), so the cascade as a whole takes longer than three minutes to fully unfold. Root cause leads symptoms by minutes — that's the lesson, regardless of the wall-clock numbers.

#### Act 4 — Read the dashboards you already have

The cascade is still unfolding. Latency is climbing, the backup is saturating, the primary is still flapping. The temptation under pressure is to open Grafana's panel editor and start building — *don't*. Real on-call doesn't build dashboards during a fire; you read what's already there.

> *"Your dashboards earned their keep this morning, when you built them in peacetime. Tonight, you just read them."*

Open **Workshop Lab 2026** and walk the panels you already have.

**The Flap rate panel you built in Part 2.** Set the `Device` dropdown to `srl1`, time range **Last 15 minutes**. You'll see a baseline trickle below the red threshold — and the panel stays quiet, which is itself information. Tonight's `incident` cascade emits three *metrics* (`interface_oper_state`, `incident_backup_link_utilization`, `incident_latency_ms`) and no UPDOWN log lines, so a log-derived flap panel has nothing to count. The panel you built is the right panel for a `PeerInterfaceFlapping` incident; tonight's incident is a different shape.

**Interface Operational Status and Interface Traffic.** Same dashboard, same `$device`. The cascade's metrics carry `source="incident-cascade"` rather than the `srl1`/`srl2` labels the provisioned panels filter on, so to see this incident's exact signals you bounce to **Explore** with Act 3's three queries. The dashboard panels show the *baseline* alongside the incident — the lab's steady-state shape during the same window, so you can read deviation against normal noise.

**Workshop Home.** Switch tabs. The **Currently Firing Alerts** table still shows the same four steady-state rows from Act 1 — this cascade has its own signals and doesn't trip the existing rules, so the table looks calm. The **Recent events** feed is reflecting cascade activity as it flows. One tab over keeps you aware without losing the detail view.

The dashboards together tell the cascade's story — flap on Operational Status, pressure rising on Interface Traffic, latency climbing in Explore. The chapters Act 3's queries walked, now visible without typing. Queries are how you discover something is wrong. Dashboards are how you stay aware while you fix it.

**Stop and notice.** Dashboards earn their keep *before* incidents, by being there when the page lands. You build during calm; you read during fire. The panel you built in Part 2 didn't move tonight — and that's the right outcome, because tonight wasn't a `PeerInterfaceFlapping` incident. Tomorrow's might be. The work is done before the page, not after.

#### Act 5 — Contain: silence the noise with maintenance

The cascade is still running and the dashboards are still on fire. You're going to need quiet to investigate without the automated alert response also firing on every BGP wobble and flap. The on-call's containment move: flag `srl1` as in maintenance.

```bash
nobs packt maintenance --device srl1 --state
```

Verify the alert flow's response will now change for this device:

```bash
nobs packt alerts
```

The `BgpSessionNotUp` row is still in the firing list — that's expected. The alert isn't "fixed" by going into maintenance; what changes is the *response* path. The webhook flow consults Infrahub on every alert it receives, sees `srl1.maintenance=true`, and decides `skip` (reason: `device under maintenance`) instead of `quarantine`. Open Workshop Home and look at the **Recent events** feed: the next time Alertmanager's webhook fires for this alert, the new annotation reads `skip` rather than `quarantine`. Alertmanager's `repeat_interval` for this alert is 30 minutes (covered in Part 3 Phase 1), so you may not see the `skip` annotation appear within the time you spend in this guide.

!!! tip "Want to see the skip annotation land *now*?"

    Drive a fresh cycle directly, bypassing Alertmanager's `repeat_interval`:

    ```bash
    nobs packt cycle srl1 10.1.99.2 --trigger
    ```

    Within ~15 seconds the four-panel cycle view re-renders with the fresh `decision=skip` audit record. For the AI narrative side of the same evidence:

    ```bash
    nobs packt rca srl1 10.1.99.2
    ```

    Either surface shows the `decision=skip` / `reason=device under maintenance` record the workflow just wrote.

**Stop and notice.** Maintenance isn't a static config attribute on the device — it's a *containment lever* the on-call engineer uses live during an incident. Setting the flag signals to the automation: "someone is actively working here; hold off on automated actions." The flow consults the source of truth at decision time, so the change takes effect on the very next alert that arrives. This is the source-of-truth integration paying off.

#### Act 6 — Fix and recover

Time to simulate the fix landing. Stop the cascade mid-flight — `nobs packt reset` is the standard way to clear in-flight cascade scenarios:

```bash
nobs packt reset
```

Reset is safe to run repeatedly — it re-loads Infrahub, clears any device maintenance flags, re-applies sonda's baseline scenarios, deletes any cascade scenarios still running, and expires any workshop-related Alertmanager silences. Watch the dashboards. Within ~30 seconds the cascade signals stop changing, the lab's continuous emitters take over, the panels drift back toward green. Latency drops on `incident_latency_ms`. `incident_backup_link_utilization` flatlines.

Note that `reset` already cleared the maintenance flag for `srl1` as part of returning the lab to known-good state. Re-run `nobs packt alerts`: the original `BgpSessionNotUp` is still firing — the deliberately broken peer hasn't been "fixed" because that's a configuration issue baked into the lab, not what we just simulated. But the *response* path is back to default: the next alert routing through the flow will get the full policy treatment again.

**Stop and notice.** The dashboard goes green. Latency drops. The metrics tell the recovery story the same way they told the failure story — in causal order, with timing that matches what an operator's intuition would expect. Real fixes don't always look this clean — the lab's synthetic data lets us show recovery as a proper signal so you see the full arc, not just the degradation half.

#### Act 7 — Write the runbook stub

Last act. You've just walked an incident end-to-end. The most valuable thing you can do with that fresh memory is write down what would help the next on-call. Open your scratch file and finish this template in your own words:

```markdown
### Runbook — primary uplink degradation cascade

**Symptom on the page:** _________________

**First three queries to run:**
1. _________________
2. _________________
3. _________________

**Containment action:** _________________

**What "fixed" looks like in the dashboard:** _________________
```

Fill the blanks based on what you actually walked through. Don't reach for textbook answers — what *did* you check first? What query gave you the most signal per second? What did you do to stop the bleeding so you could think?

Then re-read what you wrote.

> If a colleague got paged at 2am with this same symptom and you weren't around, would your five lines get them through it?

**Stop and notice.** Runbooks are the artefact every observability investment is ultimately for. Telemetry shapes you can query, dashboards you can read, alerts that fire at the right time — they all funnel into the runbook entries that make the next on-call's job survivable. You just walked through the shape; you wrote the entry. That's the loop.

### Stretch goals (optional — pick one if you have time)

- **Drive the same investigation on srl2.** The cascade you just walked was on srl1. Re-run it on srl2 and confirm your runbook stub still applies — if it doesn't, it was either too device-specific or you've found a real shape difference worth writing down.

    ??? success "Solution — command to run + what to expect on srl2"

        Run `nobs packt incident --device srl2`. It produces the same cascade shape on srl2. The pre-existing `BgpSessionNotUp` alert for `srl2 → 10.1.11.1` (the deliberately-broken peer on the SNMP-shape device) was visible in Act 1 already.

        Act 2's triage queries all work the same way — just change the device label and adjust the peer:

        ```promql
        bgp_oper_state{device="srl2", peer_address="10.1.11.1"}
        ```

        You'll see the same shape: `oper_state=5` (stuck in active) on a peer whose SoT says `expected_state=established`. The triage decision tree doesn't care about the device label — it's the same intent-vs-reality pattern.

        If your runbook stub *didn't* apply when you swapped to srl2, it was either too device-specific ("check srl1's config") or accidentally encoded a vendor-shape assumption that doesn't survive the SNMP path.

- **Predict the customer-impact window.** At what point in the cascade would a customer's response-time SLO break? Back the answer with data from Act 3's queries, not feel.

    ??? success "Solution — the math + customer-impact arithmetic"

        Given the timing you observed (backup utilisation crossing 70% around t=2½ min, latency ramping from there toward 150ms over the next three minutes), linear interpolation on latency:

        - At t ≈ 2:30, latency starts at 5 ms.
        - At t ≈ 5:30, latency hits 150 ms (3 min of ramp).
        - `latency ≈ 5 + (t − 2:30) × (150 − 5) / 3` ms.

        A typical web-service SLO target is **p99 < 200 ms total**, with maybe 30–50 ms of that budget allowed for backend round-trips. So latency above ~50 ms consumes the SLO budget; above ~100 ms breaks it.

        - **50 ms reached at t ≈ 3:25** (start eating SLO budget — about 55 seconds after the primary's first DOWN edge).
        - **100 ms reached at t ≈ 4:30** (SLO breach — about 2 minutes after the primary's first DOWN edge).

        The lesson: by the time customers complain (p99 broken), the primary uplink fault is **already 3–4 minutes old**. The alert needs to fire on a root-cause signal (the flap, or backup utilisation crossing threshold), not on the latency symptom — otherwise you're permanently 3 minutes behind the customer impact.

- **Compare the investigation arc to the automated path.** Contrast the manual investigation you just walked against Part 3's automated flow. Where does each one belong in a real operation?

    ??? success "Solution — command to run + the qualitative comparison"

        Run `nobs packt try-it` from Part 3 — it walks the four alert paths automatically. `try-it` is the automation handling routine cases without you; the investigation game you just walked is what you do when *automation isn't enough* — when you need to know what the workflow would have done, why, and whether to override it.

        Two different jobs, both useful:

        | Aspect | Investigation (Acts 1–6) | Automation (`try-it`) |
        |---|---|---|
        | When you do it | Reactive, post-page, under pressure | Pre-computed, in calm |
        | Latency | Minutes per query, hours for the full arc | Seconds end-to-end |
        | What it produces | A runbook entry, a hypothesis, a fix | A categorised decision + an audit annotation |
        | Where it excels | When you have time and a specific question | When alert volume exceeds human attention |
        | Where it falls short | At 2am with 50 alerts firing simultaneously | When the situation is novel — outside the policy's rule set |

        The lesson: automation handles routine cases (broken peer, BGP mismatch, device in maintenance — one second per alert). Investigation handles the unusual cases — where you need to question the policy's reasoning, decide whether to override, or change the policy itself.

        In production, both run in parallel: the flow handles 95% of alerts on autopilot, and the on-call engineer steps in only for the 5% the policy escalates or can't confidently classify.

### What you took away

- The shape of an interface-degradation incident — primary fault → failover → backup pressure → latency — is universal. Latency is almost always a symptom; walk back through the cascade to find the cause.
- Same labels on metrics and logs means correlation is one query change away. Metric tells you *what*; log tells you *why*. The metric-to-log bridge is the single most useful pattern under pressure.
- Dashboards are built in peacetime and read in crisis; runbooks are the durable artefact every observability investment funnels into. Five good lines, written while the memory is fresh, are worth more than a polished page nobody can find at 02:14.

---

## Where to go next

**The recording.** Packt records the session and distributes it — check your Packt account for the replay. Everything the recording shows is also written out in the guides you already have on your laptop, so you can follow along at your own speed rather than scrubbing video.

**The book.** [*Modern Network Observability*](https://network-observability.github.io/) is the long-form version of everything here — the collectors, the schema design, the alerting philosophy, the automation patterns, with far more depth than three hours allows.

**The deeper lab.** [`network-observability-lab`](https://github.com/network-observability/network-observability-lab) is the book's chapter-by-chapter playground: every collector, every variant, real cEOS and SR Linux containers in the loop. Bigger surface area, more RAM, more network-engineering depth. This workshop is the tight on-ramp; that repo is the full trip.

**Asking questions after the session.** Questions during the session go through Packt's Q&A panel. Afterwards, open an issue on [the workshops repo](https://github.com/network-observability/workshops/issues) — a broken step, a query that will not run on your machine, or a "why is it done this way" are all fair game, and a question that catches a real gap makes the workshop better for the next room.
