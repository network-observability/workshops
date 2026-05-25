# Part 2 — Dashboards

## What you'll do here

You're back from the short break. The team standup is wrapping in the next room. Your senior slides their laptop across with an email open on it.

```
From: oncall@example.com
Subject: Post-mortem action — flap-rate panel

Yesterday's page was BgpSessionNotUp on srl1, 10.1.99.2.
We could see BGP was wobbly but couldn't see WHY without
scrolling. Standby lost about ten minutes recognising the
flap shape. Need a flap-rate panel on Workshop Lab so the
next page lands with the right view already on screen.
Whoever's free, take it.
```

> Your senior taps the screen. *"Last night's page. Read it. Standby lost ten minutes because a flap-rate panel didn't exist yet. The post-mortem decided it should. Would you take this? You've got 40 minutes — the panel needs to be on Workshop Lab 2026 with thresholds matching the actual alert rule, so when someone gets paged on this shape next time, the view's already there."*

Add one panel to the **Workshop Lab 2026** dashboard that answers a real operational question: *is this interface flapping right now?* You'll wire it to the dashboard's `device` variable so it works for either device, set thresholds that match the actual alert rule, then drive a flap from the CLI and watch the panel react.

A dashboard is an operational tool, not wall decor. One dashboard, one story. The exercise is small on purpose — by the end you'll know enough to extend any panel in this lab.

## Setup check

Reset workshop state (safe to skip if you ran it earlier this morning) and confirm the stack is healthy:

```bash
nobs autocon5 reset
nobs autocon5 status
```

Open Grafana at <http://localhost:3000> and navigate to **Workshop Lab 2026** (`/d/dfb5dpyjbh2wwa`). The existing panels you'll see:

- **Health summary row** — Devices / Interfaces / Firing alerts / Log lines (5m)
- **Interface Admin State** and **Interface Operational Status** — what intent says and what reality says
- **Interface Traffic** — bandwidth per interface, drawn from `rate(interface_in_octets[...])`
- **Interface Logs** — raw log lines for `$device`

At the top of the dashboard there's a **Device** dropdown — that's the `$device` template variable. Toggle it between `srl1` and `srl2` and watch every panel re-query.

> Your senior glances at the screen. *"Notice the dashboard didn't break when you toggled. That's the variable doing its job. Every panel here uses `$device` — same panel, two subjects."*

The dashboard is provisioned `editable: true, allowUiUpdates: true`. UI changes save back to Grafana for the workshop session. **They don't persist past `nobs autocon5 restart grafana`** — that's intentional, and a useful thing to know about provisioned dashboards. Treat the dashboard as a scratchpad, not a deliverable.

## The exercise

You're adding a **flap rate** panel: how many UPDOWN log events per minute, broken out per interface, with thresholds that match the `PeerInterfaceFlapping` alert rule.

### 1. Enter edit mode

> *"Click Edit, top right. Then Add panel → Add visualization."*

You should land in Grafana's panel editor — query box at the bottom, panel preview at the top, options on the right.

### 2. Pick the datasource

> *"What datasource? Think about the data shape — flap rate is a count of log events, not a metric Prometheus is scraping for us."*

Choose **`loki`** in the datasource picker. Flap rate is a *log-derived metric*, not a Prometheus counter — same pattern you saw in Part 1 exercise 10.

### 3. Write the query

> *"Same shape as the LogQL aggregation we wrote together earlier. UPDOWN log events, grouped per interface, counted in a 1-minute window. Use the dashboard variable so this panel works for both devices."*

In the Loki query box, paste:

```logql
sum by (interface)(count_over_time({device="$device", vendor_facility_process="UPDOWN"}[2m]))
```

Two things to notice:

- `$device` is the dashboard variable. Grafana substitutes it before sending the query, so this panel becomes `srl1`-aware or `srl2`-aware automatically.
- `count_over_time(...[2m])` counts UPDOWN log lines in a rolling 2-minute window — the same window the `PeerInterfaceFlapping` alert rule uses. `sum by (interface)` groups so each interface gets its own line.

Click **Run query**. **At rest you'll see at most one line — `ethernet-1/11`, the always-broken interface — hovering at 1**, well below the alert threshold of 3. Healthy interfaces don't show up at all; if nothing is flapping, the panel is honest about that:

<figure class="section-preview" markdown>

![Flap rate panel at baseline](../../../docs/assets/screenshots/flap-rate-baseline-light.png#only-light){ .screenshot loading=lazy }
![Flap rate panel at baseline](../../../docs/assets/screenshots/flap-rate-baseline-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>Baseline (no flap in progress)</strong> — one line for <code>ethernet-1/11</code> at 1 (the only interface that's actually flapping at rest, because it's broken by design). The other peer interfaces are silent. Anything else here means a real flap is in progress.</figcaption>

</figure>

!!! tip "Empty panel?"

    If you see "No data" instead of the expected lines, check the `Device` dropdown above the dashboard is set to a real device.

### 4. Pick the panel type

> *"Time series for this. Aggregations over time always read better as a line graph than a table."*

In the right-hand options panel, panel-type dropdown at the top: choose **Time series**. (It usually defaults to time series for Loki aggregation queries — confirm it.)

### 5. Title and description

> *"Title and description matter. The panel needs to tell the next on-call what they're looking at without you being there to explain it."*

Scroll the right-hand options to **Panel options**:

- **Title**: `Flap rate (per 2 minutes)`
- **Description**: `UPDOWN log events per interface in a rolling 2-minute window. Above 3, the PeerInterfaceFlapping alert fires — the panel uses the same window so the red threshold line is the alert condition.`

Description shows up as a small `i` icon on the panel — students hovering it later get the context without leaving the dashboard.

### 6. Set thresholds that match reality

> *"Now thresholds. The PeerInterfaceFlapping alert fires when count_over_time over 2 minutes exceeds 3. Match that — when the threshold line moves, the alert is right behind it."*

The `PeerInterfaceFlapping` alert fires when `count_over_time({vendor_facility_process="UPDOWN"}[2m]) > 3`. Mirror that on the panel so the threshold line *is* the alert condition:

In the right-hand options, scroll to **Thresholds**. Set:

| Color | Value |
|-------|-------|
| Green | base (default — keep it) |
| Orange | `1` |
| Red | `3` |

??? info "What's an alert rule?"

    An **alert rule** is a query the rule evaluator runs on a schedule, plus a firing condition, an optional `for:` duration that filters out transients, and labels + annotations that travel with each firing instance. Here's the `PeerInterfaceFlapping` rule the thresholds above are mirroring:

    ```yaml
    - alert: PeerInterfaceFlapping
      expr: sum by(device, interface) (count_over_time({vendor_facility_process="UPDOWN"}[2m])) > 3
      for: 30s
      labels:
        severity: critical
        source: loki
        environment: network-observability-lab
        device: '{{ $labels.device }}'
        interface: '{{ $labels.interface }}'
      annotations:
        summary: "[NET] Flapping interface in {{ $labels.device }}/{{ $labels.interface }}"
        description: "The interface {{ $labels.device }}/{{ $labels.interface }} is flapping"
    ```

    - **`expr`** — the firing condition. The same LogQL query the panel uses, with `> 3` appended. When the expression returns at least one series, the rule is matching.
    - **`for: 30s`** — the condition must hold continuously for 30 seconds before the alert moves from `pending` to `firing`. Filters out transient noise.
    - **`labels`** — attached to every firing instance. `severity` and `source` are what Alertmanager routes on; `device` / `interface` propagate the offending instance's identity through to the page.
    - **`annotations`** — human-readable text rendered into notifications. `{{ $labels.x }}` interpolates from the firing series' labels.

    **Where to see this rule live.** `PeerInterfaceFlapping` is evaluated by the **Loki ruler**, not Prometheus, so it does NOT show up on Prometheus `/alerts`:

    - **When firing**: [Alertmanager](http://localhost:9093/#/alerts) — the Loki ruler pushes alerts here just like Prometheus does. Loki-evaluated rules and Prometheus-evaluated rules land in the same queue.
    - **Always**: the rule lives in the repo at [`workshops/autocon5/loki/rules/alerting_rules.yml`](https://github.com/network-observability/workshops/blob/main/workshops/autocon5/loki/rules/alerting_rules.yml#L5) — that link jumps straight to the `PeerInterfaceFlapping` definition. There's no equivalent UI to Prometheus `/alerts` for Loki-defined rules — the Loki ruler doesn't ship one. The [Prometheus alerts page](../../../docs/workshop/tour.md#prometheus-the-metrics-store) in the Tour shows what that UI looks like for the rules Prometheus does evaluate.

    Part 3 walks the full lifecycle — alert fires, Alertmanager routes, webhook hands off, Prefect flow decides what to do.

Then under **Graph styles** → **Show thresholds**, pick `As lines`. **You should now see two horizontal lines on the panel preview — orange at 1, red at 3.** A flap rate above the red line means an alert is firing.

> Your senior glances over. *"Thresholds matching the alert rule? Good. When the line crosses the orange one, the alert is firing. The panel should make the alert visible, not duplicate it."*

### 7. Save

Top right, **Apply** to drop back to the dashboard, then **Save dashboard** (disk icon, top right of the dashboard). Grafana confirms `Dashboard saved`. The new panel is now part of `Workshop Lab 2026`.

### 8. Drive a flap

> *"OK. Panel's there. Doesn't mean anything until we see it react. Drive a flap."*

In a terminal:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

This kicks off a 4-minute cascade with the interface cycling 30s up, 60s down. UPDOWN log lines emit at a steady cadence (~one every two seconds) during each down window. Switch the dashboard's `Device` dropdown to `srl1` if you aren't already there.

<figure class="section-preview" markdown>

![Flap rate panel during a flap](../../../docs/assets/screenshots/flap-rate-flapping-light.png#only-light){ .screenshot loading=lazy }
![Flap rate panel during a flap](../../../docs/assets/screenshots/flap-rate-flapping-dark.png#only-dark){ .screenshot loading=lazy }

<figcaption><strong>During a flap (~2 min in)</strong> — green line is <code>ethernet-1/1</code>, climbing fast past the orange threshold (1) and through the red threshold (3) on its way to 16+. The yellow line is <code>ethernet-1/11</code>'s baseline (always-broken interface, value 2 in the rolling window). The flapped interface is the obvious anomaly against an otherwise quiet panel.</figcaption>

</figure>

**What you should see, in order:**

- **First ~45 seconds** are quiet. The cascade starts the interface in the *up* state and walks through one 30-second up phase before the first down phase begins. UPDOWN log emission begins ~10 seconds into the down phase.
- **Around t+60s**: a line for `interface=ethernet-1/1` appears at around `10`. It's already past both the orange (1) and red (3) thresholds — the down phase's emission rate (~one log every two seconds) means the rolling 2-minute count climbs fast.
- **Around t+90s**: the line is somewhere in the `25–40` range — well above red, matching the alert rule's "> 3 events in 2 minutes" condition many times over.
- **Between cycles 1 and 2**: the line **plateaus** around `25` rather than dropping. The rolling 2-minute window still contains the events from cycle 1's down phase — they haven't aged out yet.
- **Cycle 2 around t+120s**: cycle 2's down-phase events stack onto the still-in-window events from cycle 1, so the count climbs higher — typically `40–60`. The plateau-then-climb shape is what real flap-rate dashboards look like during an active flap.

> Your senior taps the screen. *"Watch the orange line — that's where the alert is starting to fire. Watch the red line — that's where someone's pager goes off. The panel makes both moments visible without a separate alerts pane."*

**Stop and notice.** This is the same query pattern that drives the `PeerInterfaceFlapping` alert in Part 3. The panel isn't decoration — it's a visual representation of the rule that's about to fire. When the on-call gets paged, this panel is what they look at first.

### 9. Switch device variable

> *"Now the proof that the variable was worth it. Toggle to srl2 and drive a flap there. No editing the panel — the dashboard does the work."*

Toggle the `Device` dropdown to `srl2`. The flap-rate panel re-queries and now shows `srl2`'s steady-state — mostly silent, with at most a single tick from the always-broken `ethernet-1/11` every two minutes. Same as `srl1` before you triggered its flap.

Trigger:

```bash
nobs autocon5 flap-interface --device srl2 --interface ethernet-1/10
```

Watch the spike land on `srl2`'s `ethernet-1/10` line — same ramp shape, same threshold crossings, same recovery — without you editing the query.

**Stop and notice.** One panel, two devices. That's what the dashboard variable bought you. If you'd hard-coded `device="srl1"` in the query, you'd need a duplicate panel for every device you ever add — and one to maintain per device when the schema changes.

Worth noting: `srl1` and `srl2` arrive through different upstream pipelines (gNMI vs SNMP), but the panel queries them identically — that's normalization paying off at the dashboard layer.

??? tip "Bonus — same panel, two pipelines"

    `srl1`'s metrics emit as raw gNMI shapes (`srl_*` field names) and Telegraf-srl1 normalizes them; `srl2`'s metrics emit as raw SNMP shapes (`ifHC*`, `bgpPeer*`) and Telegraf-srl2 normalizes them. By the time your panel queries them, both look identical — same metric names, same label keys. Hover the **Collection Type** panel on the Device Health dashboard to see which raw shape each device came in as.

> Your senior nods at the screen. *"That's the panel. Six hours from now when somebody on the rotation gets paged on a similar shape, this view is on screen the moment they open the dashboard. Ten minutes saved off the next triage. That's the work."*

## Stretch goals (optional — pick one if you have time)

### Extend the Interface Traffic panel with a per-device aggregate

Open the existing **Interface Traffic** panel in edit mode. Add a second query (the **+ Query** button below the first one):

```promql
sum(rate(interface_in_octets{device="$device"}[1m]))
```

In the right-hand options, find **Overrides** and add an override on the new series — set its line width to `3` and its colour to something that stands out. Now the panel shows per-interface lines plus a single thicker line for the device-wide total.

### Write a panel description in the workshop's voice

Pick any panel that doesn't already have one. Click edit, scroll to **Panel options** → **Description**. Write one or two sentences in the same student-facing prose style — what to look for, when to worry. Save. Hover the `i` icon to confirm.

### Build a flap-history table with drill-through

> Your senior leans back in. *"Time-series tells you the shape. A table tells you the list — which device, which interface, how many flaps, click here to investigate. Build the second one. Make the device column a link into Device Health so a click takes you straight to the right view."*

You're adding a second panel: a table that summarises flap activity per device + interface over the last hour, with the **device** column as a clickable link into the **Device Health** dashboard, preserving the time window.

#### 1. Add the panel

Back on the **Workshop Lab 2026** dashboard, **Edit** → **Add panel → Add visualization**. Pick the **`loki`** datasource.

#### 2. Write the query

```logql
sum by (device, interface) (count_over_time({vendor_facility_process="UPDOWN"}[1h]))
```

A 1-hour window is "what's been flapping today" — wider than the 2-minute alert window so the table holds stable rows even between flaps. Click **Run query**.

#### 3. Switch the panel type

Right-hand options, panel-type dropdown at the top: choose **Table**. The result lands as a single-row table with a value column and the labels mashed into one cell — that's because Loki returns time-series-shaped data and the table needs help turning labels into proper columns.

#### 4. Reshape with transformations

Below the query box, click the **Transformations** tab → **+ Add transformation**.

- Pick **Labels to fields**. Each Loki label (`device`, `interface`) becomes its own column.
- Add a second transformation: **Organize fields**. Hide `Time` (the table doesn't need it), reorder so `device` is first and `interface` second, and rename the value column to `Total flaps`.

You should now see one row per `device + interface` pair, with three clean columns: `device`, `interface`, `Total flaps`.

#### 5. Title and description

Right-hand options → **Panel options**:

- **Title**: `Flap history (last 1h)`
- **Description**: `UPDOWN events per device + interface over the last hour. Click any device cell to drill into Device Health for that device, time range preserved.`

#### 6. Make the device cell a link

Still in the right-hand options, scroll to **Overrides** → **Add field override** → **Fields with name** → pick `device`. On the override:

- **Cell type**: `Auto` (or `Color text` if you want the link visually distinct).
- **Data links** → **Add link**:
    - **Title**: `Open Device Health for ${__value.text}`
    - **URL**: `/d/c78e686b-138b-4deb-b6ae-3239dc10a162?var-device=${__value.raw}&from=${__from}&to=${__to}`

`${__value.raw}` is the cell's raw label value (`srl1`, `srl2`). `${__from}` and `${__to}` are the dashboard's current time-range bounds — the link carries the window forward so the destination dashboard opens on the same minutes you were just looking at.

#### 7. Save and try it

**Apply**, then **Save dashboard**. Trigger a flap:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/10
```

Within a minute, a row for `srl1 / ethernet-1/10` shows up with a climbing `Total flaps` count. Click the `srl1` cell. Grafana jumps to **Device Health**, scoped to `srl1`, on the same time range you were on.

**Stop and notice.** Tables are the dashboard equivalent of "a list of things to investigate, each row a one-click entry into deeper context". The time-series panel above tells you *something is flapping*. The table tells you *which one, how badly, and here's the next dashboard*. The data-link override is what binds the two dashboards into one navigation flow — no copy-pasting device names, no losing the time range.

## What you took away

- Dashboard variables (`$device`) make one panel work across many subjects. Always prefer a variable over hard-coding a label value.
- Log-derived metrics (`sum(count_over_time(...))`) belong in dashboards just as much as Prometheus metrics.
- Thresholds should match the alert rule, not your aesthetic taste — when the threshold line moves, the alert is right behind it.
- Provisioned dashboards in this lab are editable for the session but reset on `restart grafana`. Treat them as a scratchpad, not state to protect.
- Panel descriptions and panel links are how a dashboard guides the next person. Adding them is part of building a dashboard, not optional polish.
