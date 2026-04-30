# Advanced — Investigation, end-to-end

## What you'll do here

It's 02:14. Your phone just buzzed. By the end of this guide you'll have triaged the page with PromQL and LogQL, watched a real cascade unfold across the dashboards, built a panel that would have caught it sooner, contained the noise with the maintenance flow, simulated the fix, and written the top of your own runbook entry.

This is the workshop's capstone. It assumes Parts 1, 2, and 3 are already behind you — every skill you built across the day is going to come out under time pressure here. Budget **60 to 90 minutes** of wall-clock — longer than the part-guides on purpose, because you're integrating everything.

## Setup check

The investigation will leave the lab in a non-default state mid-flight (a cascade running, a device flagged in maintenance). Reset to known-good first:

```bash
nobs autocon5 maintenance --device srl1 --clear
nobs autocon5 status
```

`--clear` is always safe — running it on a device that's already in production state is a no-op. `status` should show every row `ok`. If anything is yellow or red, flag it before continuing.

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

You should see `BgpSessionNotUp` for `srl1 ↔ 10.1.99.2` in the output. **Stop and notice.** This isn't an alert a cascade we just kicked off invented — it's the alert that's been firing since the lab booted, because the topology has a deliberately broken peer wired in. The page is real in lab terms. So: what do you do next?

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

Every interface should be UP (value 1). **Conclusion:** no interface fault. Whatever is going on, it isn't on the wire — the link to the broken peer's network is intact. This is BGP-only.

**Is the peer reachable at the BGP layer?** Check intent and reality on this specific peer:

```promql
bgp_admin_state{device="srl1", peer_address="10.1.99.2"}
```

```promql
bgp_oper_state{device="srl1", peer_address="10.1.99.2"}
```

Admin reads `1` — the configured intent is "this peer should be up". Oper reads something other than `1` — reality says "it isn't established". **Conclusion:** intent-vs-reality mismatch on this specific peer. This is exactly what the alert is firing on.

**Is there a log line that explains why?** Bridge to Loki — same labels, different datasource:

```logql
{device="srl1", peer_address="10.1.99.2"} |~ "BGP|peer|session"
```

You'll see BGP-related lines for that specific peer — fsm transitions, retry attempts, whatever the lab's continuous emitters are producing for the broken session. The metric told you *something* is wrong. The logs tell you *why*.

**Stop and notice.** You localised the problem from a single alert payload to a specific peer with a specific configured intent that reality isn't matching. This is the triage every on-call walks. The fact that it took four queries instead of one says you're doing it right — `count by` collapses noise, `bgp_oper_state` answers the targeted question, the LogQL bridge explains the why. You worked top-down: device, interface, peer, log evidence. Each layer ruled out a class of failure before you went deeper.

### Act 3 — Diagnose: drive the cascade and walk the shape

While you were triaging, things escalated. A different problem started developing on the same device — the kind of cascade that starts with a flap and ends with customers complaining about latency. Time to drive it and read it as it unfolds:

```bash
nobs autocon5 incident --device srl1 --duration 90s
```

The CLI returns immediately and prints three IDs. The cascade is now unfolding in the lab. Open the **Workshop Lab 2026** dashboard — you'll be running three queries against the `prometheus` datasource in Explore as the incident develops. The Workshop Home dashboard's **Recent events** feed is also reflecting it; switch tabs occasionally to keep both in view.

**The first thing that catches your eye — primary degrading.** The interface starts flipping:

```promql
interface_oper_state{device="srl1", source="incident-cascade"}
```

Switch to **Time series**. Within seconds you'll see the line flip between `1` (up) and `0` (down). Roughly 60s up, 30s down. An interface flap is the classic *something physical is wrong* signal — in a real network this is what makes you walk to the rack. The `source="incident-cascade"` label scopes the query to the signals this incident is emitting, leaving the lab's steady-state noise out of view.

**Did failover work?**

```promql
incident_backup_link_utilization
```

Empty for the first ~60 seconds — you'll see "no data" or a flat panel. Once the primary actually goes down for the first time, the metric appears and ramps from around 20% toward 85%.

**Stop and notice.** The backup didn't start carrying traffic until the primary actually failed. That's failover working as intended. But notice the *direction* — utilisation is climbing past where the link is comfortable. This is the early-warning shape an experienced on-call reads as *we're going to have a latency problem in a couple of minutes if this doesn't recover*. The empty panel for the first minute isn't a query bug — backup-utilisation samples only start landing once the failover is real. Empty panels at the start of an incident are information, not bugs.

**The symptom your customers feel — latency:**

```promql
incident_latency_ms
```

Empty even longer. Only starts climbing once backup utilisation crosses ~70%. From there it ramps from ~5ms toward 150ms.

**Stop and notice.** By the time latency is the visible problem, the actual root cause — the primary uplink fault — happened minutes ago. This is why incident timelines matter. The latency spike is a *symptom*. The flapping interface was the *cause*. If your alert fires on latency, your runbook needs to walk back through the cascade to find the real failure. The cascade is the story; the metrics are the chapters. Operators read incidents this way every day.

There's a wall-clock detail worth calling out. You passed `--duration 90s`, but the whole incident takes roughly three to three-and-a-half minutes end-to-end. Each phase has to wait for the previous one to escalate before it starts. Root cause leads symptoms by minutes — the duration you passed is per-phase, not the lifetime of the cascade.

### Act 4 — Build the dashboard for next time

The cascade is still running. Dashboards are noisy, latency is climbing, and you've just realised something: nothing on this dashboard would have caught the *flap* before it cascaded. There's an alert rule that does (`PeerInterfaceFlapping` fires above 3 UPDOWN events in 2 minutes), but no panel making it visible. A real on-call would build it — right now, while the lessons are fresh.

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

Confirm the panel reacts to the still-running cascade. Set the dashboard's `Device` dropdown to `srl1`. The flap rate should be climbing on the interface the cascade is hitting; you should see the orange threshold line being crossed, and on a particularly noisy minute the red one too.

**Stop and notice.** Real on-call teams build dashboards in the wake of incidents, not before them. The panel you just added would have caught this incident's flap signature 30 seconds before the page fired in the first place. That's how dashboards earn their keep — they encode the lessons of yesterday's incidents. Six hours from now, when someone else gets paged on a similar shape, this panel will be on screen the moment they open the dashboard.

### Act 5 — Contain: silence the noise with maintenance

The cascade is still running and the dashboards are still on fire. You're going to need quiet to investigate without the automated alert response also firing on every BGP wobble and flap. The on-call's containment move: flag `srl1` as in maintenance.

```bash
nobs autocon5 maintenance --device srl1 --state
```

Verify the alert flow's response now changes for this device:

```bash
nobs autocon5 alerts
```

The `BgpSessionNotUp` row may still be in the firing list — what changes is the *response* path. The webhook flow now consults Infrahub on every alert payload, sees `srl1.maintenance=true`, and skips the automated action. Open Workshop Home, look at the **Recent events** feed: any new annotations from the flow about `srl1` should now read `skipped (maintenance)` instead of `quarantined`.

**Stop and notice.** Maintenance isn't a static config attribute on the device — it's a *containment primitive* the on-call uses live during an incident. Flipping the flag tells the automation "I'm in here; please don't fire automated actions while I'm working." The flow consults the source of truth at decision time, so the change has effect on the very next alert that arrives. This is what the workshop's source-of-truth integration was for.

### Act 6 — Fix and recover

Time to simulate the fix landing. Stop the cascade mid-flight:

```bash
for ID in $(curl -s http://localhost:8085/scenarios \
  | jq -r '.scenarios[] | select(.name | startswith("incident_") or . == "interface_oper_state") | .id'); do
  curl -s -X DELETE "http://localhost:8085/scenarios/$ID"
done
```

Watch the dashboards. Within ~30 seconds the cascade signals stop changing, the lab's continuous emitters take over, the panels drift back toward green. Latency drops on `incident_latency_ms`. `incident_backup_link_utilization` flatlines. The flap rate panel you just built falls back below the orange threshold line.

Clear the maintenance flag — the device is back in production:

```bash
nobs autocon5 maintenance --device srl1 --clear
```

Re-run `nobs autocon5 alerts`. The original `BgpSessionNotUp` is still firing — the deliberately broken peer hasn't been "fixed" because that's a configuration issue on the topology side, not what we just simulated. But the *response* path is back to default: the next alert payload routing through the flow will get the full deterministic policy treatment again.

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
- **Predict the customer-impact window.** Given the timing you observed (latency starts climbing around t=2 min, exceeds 100ms around t=3 min), at what point would a customer's response-time SLO break? Use the queries from Act 3 to back the answer with data, not feel.
- **Compare the investigation arc to the automated path.** Run `nobs autocon5 try-it` from Part 3 — it walks the four canonical alert paths automatically. Contrast: `try-it` is the automation handling routine cases without you. The investigation game you just walked is what you do when *automation isn't enough* — when you need to know what the workflow would have done, why, and whether to override it.

## What you took away

- The shape of an interface-degradation incident — primary fault → failover → backup pressure → latency — is universal. Recognise the shape and you've started triaging.
- Triage is a decision tree, not a single query. Localise top-down: device → link → peer → log evidence. Each step rules out a class of failure.
- The metric-to-log bridge from Part 1 is the single most useful pattern under pressure. Metric tells you *what*; log tells you *why*; the same labels on both sides make it cheap.
- Empty panels at the start of an incident aren't a bug. Some signals only exist once an upstream failure has happened, and that gap is information — it tells you when each stage of the cascade actually fired.
- Latency is almost always a symptom, not a cause. When latency alerts fire, walk *back* through the cascade to find the real failure.
- Dashboards earn their keep when they encode lessons from real incidents. Build them after the page lands, not before. The thresholds on a panel should match the alert rule, so the line you see on screen *is* the alert condition.
- Maintenance is a containment primitive, not a static attribute. Use it live to silence noise while you investigate; clear it the moment the device is back in production.
- Recovery has a shape too. The metrics tell the resolution story the same way they told the failure story — in causal order. Watch for the dashboards going green as confirmation the fix landed.
- Runbooks are the artefact every observability investment ultimately funnels into. Five good lines, written while the memory is fresh, beats a hundred mediocre ones written months later.
