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

Confirm the stack is up:

```bash
nobs autocon5 status
```

Open Grafana at <http://localhost:3000> and navigate to **Workshop Lab 2026** (`/d/dfb5dpyjbh2wwa`). The existing panels you'll see:

- **Health summary row** — Devices / Interfaces / Firing alerts / Log lines (5m)
- **Interface Admin State** and **Interface Operational Status** — what intent says and what reality says
- **Interface Traffic** — bandwidth per interface, drawn from `rate(interface_in_octets[...])`
- **Interface Logs** — raw log lines for `$device`

At the top of the dashboard there's a **Device** dropdown — that's the `$device` template variable. Toggle it between `srl1` and `srl2` and watch every panel re-query.

The dashboard is provisioned `editable: true, allowUiUpdates: true`. UI changes save back to Grafana for the workshop session. **They don't persist past `nobs autocon5 restart grafana`** — that's intentional, and a useful thing to know about provisioned dashboards. Treat the dashboard as a scratchpad, not a deliverable.

## The exercise

You're adding a **flap rate** panel: how many UPDOWN log events per minute, broken out per interface, with thresholds that match the `PeerInterfaceFlapping` alert rule.

### 1. Enter edit mode

Top right of the dashboard, click **Edit**, then **Add panel** → **Add visualization**.

### 2. Pick the datasource

You'll see a datasource picker. Choose `loki`. Flap rate is a *log-derived metric*, not a Prometheus counter — same pattern you saw in Part 1 exercise 10.

### 3. Write the query

In the Loki query box, paste:

```logql
sum by (interface)(count_over_time({device="$device", vendor_facility_process="UPDOWN"}[1m]))
```

Two things to notice:

- `$device` is the dashboard variable. Grafana substitutes it before sending the query, so this panel becomes `srl1`-aware or `srl2`-aware automatically.
- `count_over_time(...[1m])` counts UPDOWN log lines per minute. `sum by (interface)` groups so each interface gets its own line.

Click **Run query**. You should see one line per interface, all flat at zero (no flaps yet). If you see "No data", check that the dropdown variable above the dashboard is set to a real device.

### 4. Pick the panel type

In the right-hand options panel, panel-type dropdown at the top: choose **Time series**. (It usually defaults to time series for Loki aggregation queries — confirm it.)

### 5. Title and description

Scroll the right-hand options to **Panel options**:

- **Title**: `Flap rate (per minute)`
- **Description**: `UPDOWN log events per interface, counted in a 1-minute window. Above 3 in 2 minutes, the PeerInterfaceFlapping alert fires.`

Description shows up as a small `i` icon on the panel — students hovering it later get the context without leaving the dashboard.

### 6. Set thresholds that match reality

The `PeerInterfaceFlapping` alert fires when `count_over_time({vendor_facility_process="UPDOWN"}[2m]) > 3`. Mirror that on the panel so the threshold line *is* the alert condition:

In the right-hand options, scroll to **Thresholds**. Set:

| Color | Value |
|-------|-------|
| Green | base (default — keep it) |
| Orange | `1` |
| Red | `3` |

Then under **Graph styles** → **Show thresholds**, pick `As lines`. Now the panel has a horizontal red line at 3 — a flap rate above it means an alert is firing.

> Your senior glances over. *"Thresholds matching the alert rule? Good. When the line crosses the orange one, the alert is firing. The panel should make the alert visible, not duplicate it."*

### 7. Save

Top right, **Apply** to drop back to the dashboard, then **Save dashboard** (disk icon, top right of the dashboard).

### 8. Drive a flap

In a terminal:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

The default count is 6 events in ~6 seconds. Switch the dashboard's `Device` dropdown to `srl1` if you aren't already there. Within ~30 seconds the new panel should show a spike on `interface=ethernet-1/1` crossing the orange and red threshold lines.

**Stop and notice.** This is the same query pattern that drives the alert. The panel isn't decoration — it's a visual representation of the rule that's about to fire in Part 3. When the on-call gets paged, this panel is what they look at first.

### 9. Switch device variable

Toggle the `Device` dropdown to `srl2`. The flap-rate panel now queries `srl2` UPDOWN events. Trigger one:

```bash
nobs autocon5 flap-interface --device srl2 --interface ethernet-1/10
```

Watch the spike land on `srl2`'s panel without you editing the query.

**Stop and notice.** One panel, two devices. That's what the dashboard variable bought you. If you'd hard-coded `device="srl1"` in the query, you'd need a duplicate panel for every device you ever add.

> Your senior nods at the screen. *"That's the panel. Six hours from now when somebody on the rotation gets paged on a similar shape, this view is on screen the moment they open the dashboard. Ten minutes saved off the next triage. That's the work."*

## Stretch goals

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
