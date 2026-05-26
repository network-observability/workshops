# Advanced — Investigation, end-to-end

## What you'll do here

It's 02:14. Your phone just buzzed. By the end of this guide you'll have triaged the page with PromQL and LogQL, watched a real cascade unfold across the dashboards, built a panel that would have caught it sooner, contained the noise with the maintenance flow, simulated the fix, and written the top of your own runbook entry.

This is the workshop's capstone. It assumes Parts 1, 2, and 3 are already behind you — every skill you built across the day is going to come out under time pressure here. Budget **60 to 90 minutes** of wall-clock — longer than the part-guides on purpose, because you're integrating everything.

## Setup check

Confirm the command is available:

```bash
nobs autocon5 incident --help
```

You should see options for `--device`, `--primary-interface`, `--backup-interface`, `--duration`, and `--kind` (default `link-failover`). If `incident` isn't a recognised subcommand, pull and re-run.

Reset to known-good baseline and confirm the stack is healthy. The investigation puts the lab into states the part guides didn't — so the reset matters more here. Run it before you start:

```bash
nobs autocon5 reset
nobs autocon5 status
```

`reset` is safe to run repeatedly — it re-loads the Infrahub source-of-truth, clears any device maintenance flags, re-applies sonda's baseline scenarios (so the steady-state broken peers stay firing), and expires any workshop-related Alertmanager silences. `status` should show every row `ok`; if anything is yellow or red, flag it before continuing.

Two browser tabs ready:

- **Workshop Home** at <http://localhost:3000/d/workshop-home> — situational awareness, alerts table, recent events feed.
- **Workshop Lab 2026** at <http://localhost:3000/d/dfb5dpyjbh2wwa> — the dashboard you'll be modifying in Act 4.

A scratch text file open on the side. The closing act has you write the top five lines of your own runbook entry, and you'll want somewhere to put them.

This guide assumes you've walked Parts 1, 2, and 3 — you know the metric names, the basic PromQL/LogQL patterns, the dashboard layouts, and what `nobs autocon5 alerts`, `flap-interface`, and `maintenance` do. If you haven't, go back to the three core guides first; the pacing here will leave you behind otherwise.

## The exercises

### Act 1 — The page

```
PAGED 02:14
BgpSessionNotUp on srl1 — peer 10.1.99.2 not reaching Established
last seen Established: ~3 minutes ago
You're awake. The dashboard is your only friend.
```

Recognise that peer? `10.1.99.2` is the deliberately broken peer you found in Part 1 with the intent-vs-reality query. The alert has been firing in the background of the lab the whole day — it's been there waiting for someone to actually respond to it. Tonight, that's you.

First move from the couch: confirm the page is real and the alert is still firing.

```bash
nobs autocon5 alerts
```

You'll see four alerts firing — the two `BgpSessionNotUp` rows (one per broken peer) and the two `InterfaceAdminUpOperDown` rows you met in Part 3. Tonight's page is the **srl1 → 10.1.99.2** row in the first group. The other three are the same steady-state noise that's been on the dashboard all day. **Stop and notice.** This isn't an alert a cascade we just kicked off invented — it's the alert that's been firing since the lab booted, because the topology has a deliberately broken peer wired in. The page is real in lab terms. So: what do you do next?

### Act 2 — Triage with PromQL and LogQL

Triage is a decision tree, not a single query. You don't yet know what kind of failure this is. Walk it out — each step rules out a class of failure.

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

**Stop and notice.** You localised the problem from a single alert payload to a specific peer with a specific configured intent that reality isn't matching. This is the triage every on-call walks. The fact that it took four queries instead of one says you're doing it right — `count by` collapses noise, `bgp_oper_state` answers the targeted question, the LogQL bridge explains the why. You worked top-down: device, interface, peer, log evidence. Each layer ruled out a class of failure before you went deeper.

### Act 3 — Diagnose: drive the cascade and walk the shape

While you were triaging, things escalated. A different problem started developing on the same device — the kind of cascade that starts with a flap and ends with customers complaining about latency. Time to drive it and read it as it unfolds:

```bash
nobs autocon5 incident --device srl1
```

The CLI returns immediately and prints three IDs (one per cascade stage). The cascade is now unfolding in the lab — wall-clock timing is in the callout below. Open the **Workshop Lab 2026** dashboard — you'll be running three queries against the `prometheus` datasource in Explore as the incident develops. The Workshop Home dashboard's **Recent events** feed is also reflecting it; switch tabs occasionally to keep both in view.

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

Empty even longer. Only starts climbing once backup utilisation crosses ~70%. From there it ramps from ~5ms toward 150ms over three minutes.

**Stop and notice.** By the time latency is the visible problem, the actual root cause — the primary uplink fault — happened minutes ago. This is why incident timelines matter. The latency spike is a *symptom*. The flapping interface was the *cause*. If your alert fires on latency, your runbook needs to walk back through the cascade to find the real failure. The cascade is the story; the metrics are the chapters. Operators read incidents this way every day.

There's a wall-clock detail worth calling out. The default `--duration 3m` is the bounded lifetime of *each* signal in the cascade, not the total lifetime end-to-end. Each phase has to wait for the previous one to escalate before it starts (the flap has to drop, then backup has to saturate past 70%), so the cascade as a whole takes longer than three minutes to fully unfold. Root cause leads symptoms by minutes — that's the lesson, regardless of the wall-clock numbers.

### Act 4 — Build the dashboard for next time

The cascade is still running. Dashboards are noisy, latency is climbing, and you've just realised something: there's an alert rule for interface flap (`PeerInterfaceFlapping` fires above 3 UPDOWN log events in 2 minutes), and Part 3's `flap-interface` cascade trips it routinely — but nothing on this dashboard makes the flap signature visible. The next time someone gets paged on a flap, they'll be staring at metrics panels with no view of the log evidence behind the alert. A real on-call would build that panel — right now, while the lessons are fresh.

You're adding a **Flap rate** panel to **Workshop Lab 2026**, with thresholds that match the actual alert rule:

1. Open **Workshop Lab 2026**, top right click **Edit**, then **Add panel** → **Add visualization**.
2. Datasource: choose `loki`. Flap rate is a log-derived metric, not a Prometheus counter.
3. Paste the query:

   ```logql
   sum by (interface)(count_over_time({device="$device", vendor_facility_process="UPDOWN"}[1m]))
   ```

   `$device` is the dashboard variable — Grafana substitutes it so the panel works for either device. `count_over_time(...[1m])` counts UPDOWN log lines per minute; `sum by (interface)` gives each interface its own line.
4. Panel type (right-hand panel-type dropdown): **Time series**.
5. **Panel options** → **Title**: `Flap rate (per minute)`.
6. **Description**: `UPDOWN log events per interface, counted in a 1-minute window. Above 3 in 2 minutes, the PeerInterfaceFlapping alert fires.`
7. **Thresholds**: keep green at base, add **Orange** at `1`, add **Red** at `3`. Under **Graph styles** → **Show thresholds**, pick `As lines`. The panel now has a horizontal red line at 3 — a flap rate above it means the alert is firing.
8. **Apply** to drop back to the dashboard, then **Save dashboard** (disk icon).

Set the dashboard's `Device` dropdown to `srl1` and confirm the panel renders. You should see a baseline trickle of UPDOWN events from the lab's continuous emitters — well below the red threshold. The `incident` cascade you started in Act 3 is metrics-only (the three signals are `interface_oper_state`, `incident_backup_link_utilization`, `incident_latency_ms` — no log stream), so it won't move this panel; that's expected. To prove the panel reacts the way you want it to, run a one-off flap from a separate terminal:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1 --no-cascade
```

Within a minute the line for `ethernet-1/1` should climb past the orange threshold, and on a noisy moment past the red one — exactly the shape `PeerInterfaceFlapping` fires on.

**Stop and notice.** Real on-call teams build dashboards in the wake of incidents, not before them. The panel you just added makes the alert rule's log-derived condition visible — so the next time someone gets paged on `PeerInterfaceFlapping`, they have a panel that *is* the alert condition rather than guessing what tripped it. That's how dashboards earn their keep: they encode the lessons of yesterday's incidents. The threshold lines in the panel match the rule's condition, so reading the panel and reading the rule give the same answer.

### Act 5 — Contain: silence the noise with maintenance

The cascade is still running and the dashboards are still on fire. You're going to need quiet to investigate without the automated alert response also firing on every BGP wobble and flap. The on-call's containment move: flag `srl1` as in maintenance.

```bash
nobs autocon5 maintenance --device srl1 --state
```

Verify the alert flow's response will now change for this device:

```bash
nobs autocon5 alerts
```

The `BgpSessionNotUp` row is still in the firing list — that's expected. The alert isn't "fixed" by going into maintenance; what changes is the *response* path. The webhook flow consults Infrahub on every alert payload, sees `srl1.maintenance=true`, and decides `skip` (reason: `device under maintenance`) instead of `quarantine`. Open Workshop Home and look at the **Recent events** feed: the next time Alertmanager's webhook fires for this alert, the new annotation reads `skip` rather than `quarantine`. Alertmanager's `repeat_interval` for this alert is 20 minutes, so you may not see the `skip` annotation appear within the time you spend in this guide. Part 3's `try-it` tour, Path 2, walks exactly this transition with an immediate replay if you want to see it land.

**Stop and notice.** Maintenance isn't a static config attribute on the device — it's a *containment lever* the on-call uses live during an incident. Flipping the flag tells the automation "I'm in here; please don't fire automated actions while I'm working." The flow consults the source of truth at decision time, so the change has effect on the very next alert that arrives. This is what the workshop's source-of-truth integration was for.

### Act 6 — Fix and recover

Time to simulate the fix landing. Stop the cascade mid-flight — `nobs autocon5 reset` is the standard way to clear in-flight cascade scenarios:

```bash
nobs autocon5 reset
```

Reset is safe to run repeatedly — it re-loads Infrahub, clears any device maintenance flags, re-applies sonda's baseline scenarios, deletes any cascade scenarios still running, and expires any workshop-related Alertmanager silences. Watch the dashboards. Within ~30 seconds the cascade signals stop changing, the lab's continuous emitters take over, the panels drift back toward green. Latency drops on `incident_latency_ms`. `incident_backup_link_utilization` flatlines.

Note that `reset` already cleared the maintenance flag for `srl1` as part of returning the lab to known-good state. Re-run `nobs autocon5 alerts`: the original `BgpSessionNotUp` is still firing — the deliberately broken peer hasn't been "fixed" because that's a configuration issue on the topology side, not what we just simulated. But the *response* path is back to default: the next alert payload routing through the flow will get the full policy treatment again.

**Stop and notice.** The dashboard goes green. Latency drops. The metrics tell the recovery story the same way they told the failure story — in causal order, with timing that matches what an operator's intuition would expect. Real fixes don't always look this clean — the lab's synthetic data lets us show recovery as a proper signal so you see the full arc, not just the degradation half.

### Act 7 — Write the runbook stub

Last act. You've just walked an incident end-to-end. The most valuable thing you can do with that fresh memory is write down what would help the next on-call. Open your scratch file and finish this template in your own words:

```markdown
## Runbook — primary uplink degradation cascade

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

## Stretch goals

- **Drive the same investigation on srl2.** Re-run the cascade with `--device srl2`. Notice that the existing `BgpSessionNotUp` alert was for srl1's broken peer; on srl2 the broken peer is `10.1.11.1`. The triage decision tree from Act 2 works the same; only the device label changes. Confirm your runbook stub still applies — if it doesn't, either it was too device-specific or you've found a real shape difference worth writing down.
- **Predict the customer-impact window.** Given the timing you observed (backup utilisation crossing 70% around t=2½ min, latency ramping from there toward 150ms over the next three minutes), at what point would a customer's response-time SLO break? Use the queries from Act 3 to back the answer with data, not feel.
- **Compare the investigation arc to the automated path.** Run `nobs autocon5 try-it` from Part 3 — it walks the four alert paths automatically. Contrast: `try-it` is the automation handling routine cases without you. The investigation game you just walked is what you do when *automation isn't enough* — when you need to know what the workflow would have done, why, and whether to override it.

## What you took away

- The shape of an interface-degradation incident — primary fault → failover → backup pressure → latency — is universal. Recognise the shape and you've started triaging.
- Triage is a decision tree, not a single query. Localise top-down: device → link → peer → log evidence. Each step rules out a class of failure.
- The metric-to-log bridge from Part 1 is the single most useful pattern under pressure. Metric tells you *what*; log tells you *why*; the same labels on both sides make it cheap.
- Empty panels at the start of an incident aren't a bug. Some signals only exist once an upstream failure has happened, and that gap is information — it tells you when each stage of the cascade actually fired.
- Latency is almost always a symptom, not a cause. When latency alerts fire, walk *back* through the cascade to find the real failure.
- Dashboards earn their keep when they encode lessons from real incidents. Build them after the page lands, not before. The thresholds on a panel should match the alert rule, so the line you see on screen *is* the alert condition.
- Maintenance is a containment lever, not a static attribute. Use it live to silence noise while you investigate; clear it the moment the device is back in production.
- Recovery has a shape too. The metrics tell the resolution story the same way they told the failure story — in causal order. Watch for the dashboards going green as confirmation the fix landed.
- Runbooks are the artefact every observability investment ultimately funnels into. Five good lines, written while the memory is fresh, beats a hundred mediocre ones written months later.
