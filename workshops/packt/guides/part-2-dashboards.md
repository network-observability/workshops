# Part 2 — Dashboards and Alerts

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

> Your senior taps the screen. *"Last night's page. Read it. Standby lost ten minutes because a flap-rate panel didn't exist yet. The post-mortem decided it should. Watch me take this — the panel needs to be on Workshop Lab 2026 with thresholds matching the actual alert rule, so when someone gets paged on this shape next time, the view's already there."*

!!! info "This part is a guided demo — about 20 minutes"

    **Nothing here is required for Part 3.** We drive; you watch. Follow along on your own Grafana if you like — every command and query is written out below — but if your stack is slow, if you are still finishing Part 1, or if you would simply rather watch, that is the intended way to take this block. Part 3 starts from a clean `nobs packt reset` and does not depend on anything you build here.

    We are walking four of the ten panel-build steps and five of the seven alert-lifecycle steps — the ones that carry the ideas. The **full ten-step build**, the steps we skip, and the stretch goals are all on the [Take it home](../../../docs-packt/take-home.md) page, written so you can work through them at your own pace afterwards.

A "flap" is an interface bouncing up and down in quick succession. The flap-rate panel counts UPDOWN log events per interface in a rolling window — a number that climbs fast when something is flapping and sits at the floor when it isn't.

An **alert rule** here is a small query the lab runs on a schedule, with a "fires if this is true" condition attached — when the condition holds, the lab calls it an *active alert*. (Full anatomy comes up later when we walk the alert lifecycle — for now, just know it's a query + a firing condition.)

We add one panel to the **Workshop Lab 2026** dashboard that answers a real operational question: *is this interface flapping right now?* It gets wired to the dashboard's `device` variable so the same panel works for either device, with thresholds that match the actual alert rule — then we drive a flap from the CLI and watch the panel react.

A dashboard is an operational tool, not wall decor. One dashboard, one story.

## Setup check

Reset workshop state (safe to skip if you ran it earlier this morning) and confirm the stack is healthy:

```bash
nobs packt reset
nobs packt status
```

Open Grafana at <http://localhost:3000> and navigate to **Workshop Lab 2026** (`/d/dfb5dpyjbh2wwa`). The existing panels you'll see:

- **Health summary row** — Devices / Interfaces / Firing alerts / Log lines (5m)
- **Interface Admin State** and **Interface Operational Status** — what intent says and what reality says
- **Interface Traffic** — bandwidth per interface, drawn from `rate(interface_in_octets[...])`
- **Interface Logs** — raw log lines for `$device`

At the top of the dashboard there's a **Device** dropdown — that's the `$device` **dashboard variable** (Grafana's UI also calls these "template variables" — same thing; we'll stick with "dashboard variable" in this guide). Toggle it between `srl1` and `srl2` and watch every panel re-query.

> Your senior glances at the screen. *"Notice the dashboard didn't break when you toggled. That's the variable doing its job. Every panel here uses `$device` — same panel, two subjects."*

When you save changes to this dashboard, they stick for the rest of your workshop session — but they don't survive a full restart. If you run `nobs packt restart grafana`, anything you customised resets back to the original layout the workshop ships with. Treat this dashboard as a scratchpad: experiment freely, but don't expect your changes to be permanent.


## Build the dashboard panel

You're adding a **flap rate** panel: how many UPDOWN log events per minute, broken out per interface, with thresholds that match the `PeerInterfaceFlapping` alert rule.

### 1. Write the query

> *"Same shape as the LogQL aggregation we wrote together earlier. UPDOWN log events, grouped per interface, counted in a 1-minute window. Use the dashboard variable so this panel works for both devices."*

Getting to the query box: **Edit** (top right of the dashboard) → add a new panel → pick **`loki`** in the datasource picker. Loki, not Prometheus — flap rate is a *log-derived metric*, a count of log lines rather than a metric Prometheus is scraping.

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

### 2. Set thresholds that match reality

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

### 3. Drive a flap

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

### 4. Switch device variable

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

## Walk the alert lifecycle

You've made the panel react to a flap. The line crossed the orange and red thresholds; visually you got both the early heads-up and the page moment. Now the question every on-call asks themselves at 02:14: *did anything else actually fire?* Where does that information live, and what happens to it next?

This walk uses the observability surfaces the workshop already has running — the Alertmanager UI and Grafana — to follow the alert from rule match → firing → silence → resolved.

> Heads-up: this walk is foundational for Part 3, which is hands-on. Watch it closely even if you are not following along in your own Grafana — Part 3 assumes you have seen `firing → suppressed → resolved` happen once.

### 1. The rule, live

The `PeerInterfaceFlapping` rule you mirrored in the panel hasn't been hypothetical — it's been running against the same set of UPDOWN log lines you queried in the panel, this whole time. Expand the fold below for the full yaml anatomy and where the rule lives in the repo; what matters for this walk is *when* it fires.

<a id="whats-an-alert-rule"></a>

??? info "What's an alert rule? — yaml anatomy and where to see it"

    An **alert rule** is five pieces of YAML that together say *"watch this; fire if this holds; tag the alert this way; describe it like this."* Let's break it down:

    - A **query** — the thing the rule keeps re-evaluating against your metrics or logs.
    - A **firing condition** — what makes the query "true" (e.g., `> 3 events in 2 minutes`).
    - An optional **`for:` duration** — how long the condition must hold before the rule actually fires. Filters out blips that come and go.
    - **Labels** — key/value pairs attached to every firing instance, used downstream for routing and filtering.
    - **Annotations** — human-readable text that travels with the alert into notifications. (Don't confuse these *Prometheus rule annotations* with the **alert markers** you'll add to a dashboard panel in step 3 of the next section — different system, same word; we'll come back to this.)

    The thing that runs the rule on a schedule and decides when it's "matching" is called the **rule evaluator** — Prometheus has one for its PromQL-based rules, Loki has one (called the **Loki ruler**) for its LogQL-based rules.

    Here's the `PeerInterfaceFlapping` rule the thresholds you set on the panel are mirroring:

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
    - **`for: 30s`** — the condition must hold continuously for 30 seconds before the alert moves from `pending` (rule has matched but the duration hasn't elapsed) to `firing` (notification dispatched). Filters out transient noise.
    - **`labels`** — attached to every firing instance. `severity` and `source` are what Alertmanager routes on; `device` / `interface` propagate the offending instance's identity through to the page.
    - **`annotations`** — human-readable text rendered into notifications. `{{ $labels.x }}` interpolates from the firing series' labels.

    **Where to see this rule live.** Loki has its own rule evaluator — the **Loki ruler**, a component inside Loki that runs LogQL-based alert rules on a schedule, mirroring what Prometheus does for PromQL rules. `PeerInterfaceFlapping` is evaluated by the Loki ruler, not Prometheus, so it does NOT show up on Prometheus `/alerts`:

    - **When firing**: [Alertmanager](http://localhost:9093/#/alerts) — the Loki ruler pushes alerts here just like Prometheus does. Loki-evaluated rules and Prometheus-evaluated rules land in the same queue.
    - **Always**: the rule lives in the repo at [`workshops/packt/loki/rules/alerting_rules.yml`](https://github.com/network-observability/workshops/blob/main/workshops/packt/loki/rules/alerting_rules.yml#L5) — that link jumps straight to the `PeerInterfaceFlapping` definition. There's no equivalent UI to Prometheus `/alerts` for Loki-defined rules — the Loki ruler doesn't ship one.

    Part 3 walks the full lifecycle — alert fires, Alertmanager routes, webhook hands off, Prefect flow decides what to do.

Two transitions to keep in mind as you watch the rule fire:

- **Match ≠ firing.** The query returning a series means the *condition* is true right now — but with `for: 30s` set, the alert sits in `pending` (matched, but not firing yet) for 30 seconds first. Only if the condition holds for the full 30s does it promote to `firing`.
- **Resolved is also an event.** When the condition stops being true and stays gone, the alert flips to `resolved` and (after Alertmanager's `resolve_timeout` — the grace period it waits before treating the alert as definitely gone, default 5 min) ages out of the active alerts list.

You flapped `srl1/ethernet-1/1` a minute ago. The condition is matching. After 30s it'll be `firing`. Let's confirm.

### 2. Inspect alerts in the Alertmanager UI

Open <http://localhost:9093/#/alerts>. This is the central queue every rule evaluator (the **Loki ruler** for LogQL-based rules, the **Prometheus rule evaluator** for PromQL-based rules — both defined in step 1's fold above) pushes firing alerts into.

What to look at:

- **The alerts list** — every alert the lab currently holds, grouped by label set. Click any row to expand and see all its labels (`device`, `interface`, `severity`, …) and annotations (`summary`, `description`).
- **The filter box** at the top — paste `alertname="PeerInterfaceFlapping"` to scope down. Filters use the same label-matcher syntax as PromQL/LogQL selectors.
- **The generator URL** on an expanded alert — the link back to the rule that fired this alert. For `PeerInterfaceFlapping` it points at the Loki ruler's evaluation.
- **The Silences tab** in the top nav — currently empty. You'll create one in step 5.

### 3. See alerts in Grafana — and overlay them on your panel

Prometheus exposes alert state as a metric. In Grafana Explore, pick the **prometheus** datasource and paste:

```promql
ALERTS{alertstate="firing"}
```

Every currently-firing alert returns a series with value `1` and labels copying the alert's `alertname` / `severity` / etc. Filter further:

```promql
ALERTS{alertname="PeerInterfaceFlapping"}
```

This is how dashboards surface alert state — the **Currently firing alerts** panel on the Workshop Home dashboard (`/d/workshop-home`) queries this exact metric and renders it as a table. Same data, different surface.

There's a second way to put `ALERTS` to work on a dashboard: as an **alert marker** that shades the panel during the exact minutes the alert was firing. That makes the rule's firing window and the panel's threshold crossing line up visually on the same plot.

!!! info "Naming heads-up: 'alert marker' = Grafana 'annotation'"

    Grafana's UI calls this feature **annotations** — confusingly, the same word the Prometheus alert rule yaml uses for its `annotations:` block (the human-readable text travelling with each firing alert; you saw that in step 1's fold). They're **two different systems** that happen to share a name. To avoid the collision, this guide uses **alert marker** when we mean the Grafana panel overlay, and **annotation** only when you literally need to type the word in Grafana's UI. (Part 3 uses **audit record** for the workflow's Loki log lines — a third related-but-different concept.)

Add one now (Grafana 13 split the alert-marker editor across a right-panel pane and a query-editor modal — both steps are below):

1. Click **Edit** (top-right of the dashboard). The right sidebar appears.
2. In the sidebar, click **Dashboard options** (gear icon — hover tooltip says *"Dashboard options"*). The right panel switches to a settings view.
3. Scroll the right panel down to the **Annotations** section (this is Grafana's UI label — what we're calling alert markers). Click **Add annotation query**.
4. The right panel now shows the new alert marker's outer settings. Fill in:

    | Field | Value |
    |---|---|
    | **Name** | `PeerInterfaceFlapping firing` |
    | **Color** | red (or any colour you like) |
    | **Show annotation controls in** | `Above dashboard` (default) |
    | **Show in** | `All panels` (default) |

5. Click **Open query editor** (blue button under the *Query* sub-heading). A modal titled **Annotation Query** opens. Fill in:

    | Field | Value |
    |---|---|
    | **Data source** | `prometheus` |
    | **Query** (PromQL input) | `ALERTS{alertname="PeerInterfaceFlapping", alertstate="firing"}` |
    | **Title** | `{{alertname}}` |
    | **Text** | `{{device}}/{{interface}}` |

    The double-brace syntax in **Title** and **Text** is Grafana's template interpolation: at draw time, Grafana replaces `{{alertname}}` with the firing alert's `alertname` label value, `{{device}}` with its `device` label, and so on. The hover tooltip on each marker ends up reading something like *"PeerInterfaceFlapping — srl1/ethernet-1/1"* instead of the raw template text.

6. Click **Test annotation query** in the modal. If a flap-driven firing exists in the time window, you'll see one or more events listed. If you flapped 5+ minutes ago and the alert has resolved, "No events found" is also fine — the marker will pick up the next firing.
7. Click **Close** to dismiss the modal.
8. Click **Save** (top-right of the dashboard), then **Exit edit**.

A toggle now appears in the dashboard header: **PeerInterfaceFlapping firing**, enabled. Drive another flap:

```bash
nobs packt flap-interface --device srl1 --interface ethernet-1/1
```

Wait ~90 seconds (rule needs `> 3 events in 2 minutes` plus the `for: 30s` clause). Your Flap rate panel climbs past the red threshold — and on the *same panel*, a red shaded vertical region appears spanning the exact minutes `PeerInterfaceFlapping` was firing. Hover the region: the tooltip shows the device and interface from the alert's labels (`srl1 / ethernet-1/1`).

> Your senior nods. *"Now the panel doesn't just visualise the condition — it tells you when the rule actually said yes. Threshold lines tell you what *should* trigger a page; alert-marker regions tell you when it *actually* did. Both on the same plot."*

Two ways to read this once you have it on every panel:

- **During triage**: a glance at the panel tells you whether the page that woke you up is the same page someone got 30 minutes ago. The alert-marker regions are the historical record of the rule firing alongside the underlying metric shape.
- **When tuning thresholds**: if a rule fires too often (or not enough), comparing the alert-marker regions against the panel data is how you decide whether to move the threshold, widen the rolling window, or extend the `for:` clause.

(To scope the marker to a single panel instead of `All panels`, set **Show in** → **Selected panels** and pick the panel — useful when a marker only makes sense for one panel's question.)

### 4. What's a silence?

A **silence** is a per-label-set mute applied at the Alertmanager layer. It has four pieces:

- **Matchers** — label key/value pairs (regex allowed). Any active alert whose labels match all matchers is silenced.
- **Duration** — how long the silence is active. Auto-expires after.
- **Creator** — username, for audit.
- **Comment** — free text. Why the silence exists. *Always write one in production.*

What a silence does *not* do: stop the rule from matching. The condition is still being evaluated and the alert is still active in the rule evaluator's state. The silence only stops the notification path. The matching alert is marked `suppressed` in the Alertmanager UI and carries `silenced_by=<silence-id>` in its metadata.

This distinction matters: silencing isn't fixing. It's saying *"we know about this, stop paging us about it for the next N minutes."* The rule keeps watching; the page just doesn't fire.

### 5. Create a silence by hand

We'll silence one of the always-firing `InterfaceAdminUpOperDown` alerts. Safe target — silencing it doesn't break anything in the lab, and seeing it flip from `firing` to `suppressed` is the whole point of this step.

1. Open Alertmanager at <http://localhost:9093/#/silences> (the **Silences** tab) → **New Silence**.
2. Add matchers (click **+ Add matcher** for each):
    - `alertname` = `InterfaceAdminUpOperDown`
    - `device` = `srl1`
3. **Duration**: `5m`.
4. **Creator**: your name or `workshop`.
5. **Comment**: `Testing silences in workshop`.
6. Click **Confirm**.

Return to the **Alerts** tab. The `InterfaceAdminUpOperDown(srl1)` row now shows as `suppressed`, not `firing`. Click it — labels and annotations are unchanged, but a new `silenced_by` field carries the silence ID. The same transition is visible from the terminal with `nobs packt alerts` — same data, two surfaces.

Now flip it back: in **Silences**, find your silence, click **Expire**. Refresh Alerts — the row is back to `firing`.

> *"That's the dance the on-call does every time something fires while a known maintenance is in progress. Whoever takes the alert clicks Silence, picks the right matchers, sets a duration, writes a comment. The rule keeps watching, the pager stops yelling, the audit trail shows who silenced what and why."*


## What you took away

- Dashboard variables (`$device`) make one panel work across many subjects. Always prefer a variable over hard-coding a label value.
- Log-derived metrics (`sum(count_over_time(...))`) belong in dashboards just as much as Prometheus metrics.
- Thresholds should match the alert rule, not your aesthetic taste — when the threshold line moves, the alert is right behind it.
- Provisioned dashboards in this lab are editable for the session but reset on `restart grafana`. Treat them as a scratchpad, not state to protect.
- Panel descriptions and panel links are how a dashboard guides the next person. Adding them is part of building a dashboard, not optional polish.
