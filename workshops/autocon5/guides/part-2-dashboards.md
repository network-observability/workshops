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

Click **Run query**. **You should see flat lines near zero** — typically hovering at 0 or 1. With `$device=srl1` you'll see a quiet line for `ethernet-1/11` (the always-broken interface). With `$device=srl2`, similar near-zero lines for one or two interfaces. None should be anywhere near the alert threshold (3) in steady state.

??? info "Why does srl1 sometimes show a label-less line?"

    `srl1` ships UPDOWN logs via Loki's direct push API, which doesn't promote the per-event `interface` tag to a Loki label. When you `sum by (interface)`, those events collapse into a series with no `interface` label — that's the label-less line. `srl2` ships its UPDOWN logs through Vector (syslog → Vector → Loki), and Vector promotes the `interface` label cleanly, so each interface gets its own line. Two valid ingestion pipelines, slightly different label shapes downstream — a curious side-effect worth knowing about.

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

**What you should see, in order:**

- **First ~45 seconds** are quiet. The cascade starts the interface in the *up* state and walks through one 30-second up phase before the first down phase begins. UPDOWN log emission begins ~10 seconds into the down phase.
- **Around t+60s**: a line for `interface=ethernet-1/1` appears at about `10`. It's already past both the orange (1) and red (3) thresholds — the down phase's emission rate (~one log every two seconds) means the rolling 2-minute count climbs fast.
- **Around t+90s**: the line reaches `25` — well above red, matching the alert rule's "> 3 events in 2 minutes" condition many times over.
- **Between cycles 1 and 2**: the line **plateaus** around `25` rather than dropping. The rolling 2-minute window still contains the events from cycle 1's down phase — they haven't aged out yet.
- **Cycle 2 around t+120s**: cycle 2's down-phase events stack onto the still-in-window events from cycle 1, so the count climbs higher — typically `35–40`. The plateau-then-climb shape is what real flap-rate dashboards look like during an active flap.

> Your senior taps the screen. *"Watch the orange line — that's where the alert is starting to fire. Watch the red line — that's where someone's pager goes off. The panel makes both moments visible without a separate alerts pane."*

**Stop and notice.** This is the same query pattern that drives the `PeerInterfaceFlapping` alert in Part 3. The panel isn't decoration — it's a visual representation of the rule that's about to fire. When the on-call gets paged, this panel is what they look at first.

### 9. Switch device variable

> *"Now the proof that the variable was worth it. Toggle to srl2 and drive a flap there. No editing the panel — the dashboard does the work."*

Toggle the `Device` dropdown to `srl2`. The flap-rate panel re-queries and now shows `srl2`'s steady-state lines — quiet, near zero, similar to what `srl1` looked like before you triggered its flap.

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

### Wire a "drill into Device Health" panel link

In edit mode on any panel, scroll to **Panel options** → **Panel links** → **Add link**.

- **Title**: `Open Device Health for $device`
- **URL**: `/d/c78e686b-138b-4deb-b6ae-3239dc10a162?var-device=$device`
- Tick **Include time range** so the link carries the current dashboard's window.

Save. The panel now has a small link icon at top — clicking it jumps to the **Device Health** dashboard with the device variable preserved. That's the dashboard equivalent of "if this panel goes red, here's where you go next".

## What you took away

- Dashboard variables (`$device`) make one panel work across many subjects. Always prefer a variable over hard-coding a label value.
- Log-derived metrics (`sum(count_over_time(...))`) belong in dashboards just as much as Prometheus metrics.
- Thresholds should match the alert rule, not your aesthetic taste — when the threshold line moves, the alert is right behind it.
- Provisioned dashboards in this lab are editable for the session but reset on `restart grafana`. Treat them as a scratchpad, not state to protect.
- Panel descriptions and panel links are how a dashboard guides the next person. Adding them is part of building a dashboard, not optional polish.
