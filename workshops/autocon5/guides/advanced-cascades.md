# Advanced — walking an incident cascade

## What you'll do here

An edge router's primary uplink starts flapping intermittently. Traffic shifts to the backup link, which gets pushed harder than designed. Latency on the backup path starts to climb. You're going to drive this incident on the lab and walk through what an on-call engineer would see, in the order they'd see it.

One CLI command kicks off the whole shape. The exercises below take you through the dashboard, query by query, the way you'd read it during a real page.

## Setup check

Confirm the command is available:

```bash
nobs autocon5 incident --help
```

You should see options for `--device` and `--duration` (among others). If `incident` isn't a recognised subcommand, pull and re-run.

Reset to known-good baseline and confirm the stack is healthy:

```bash
nobs autocon5 reset
nobs autocon5 status
```

`reset` is idempotent — clears any leftover maintenance flags, expires workshop-related silences, removes any cascade scenarios from a prior run, and restarts the log shipper if it has gone quiet. `status` should report every row `ok`. Open Grafana at <http://localhost:3000> and have **Explore** ready on the `prometheus` datasource — you'll be running three queries against it as the incident unfolds.

## The exercises

### 1. Set the scene — what does "everything's fine" look like

Open the **Workshop Lab 2026** dashboard scoped to `srl1`. Set the time range to `Last 5 minutes`. Interfaces are all UP. Traffic looks ordinary. No alerts firing. Take a mental snapshot — this is the picture you'd be staring at the second before a page lands. The contrast with the next few exercises is the point.

### 2. Drive the incident

```bash
nobs autocon5 incident --device srl1 --duration 90s
```

You've simulated a real incident shape. The primary uplink is going to start flapping. Once the primary actually goes down, the backup absorbs the traffic. Once the backup is loaded enough, latency on its path starts to climb.

The CLI returns immediately and prints three IDs. That's fine — the incident is now unfolding in the lab. From here on, you're the on-call engineer reading the dashboards.

### 3. The first thing that catches your eye — primary degrading

This is what makes the on-call engineer sit up. The interface starts flipping. In Grafana → Explore → `prometheus`:

```promql
interface_oper_state{device="srl1", source="incident-cascade"}
```

Switch to **Time series**. Within seconds you'll see the line flip between `1` (up) and `0` (down). The rhythm is roughly 60s up, 30s down.

**Stop and notice.** An interface flap is the classic *something physical is wrong* signal. In a real network this is what makes you walk to the rack. The synthetic data flips on the same shape — your eye should pick it up the same way it would in production.

The `source="incident-cascade"` label is your scoping handle. Add it to any query and you're looking only at signals this incident is emitting, not the lab's steady-state noise.

### 4. The next thing you check — did failover work

Once the operator sees an interface degrading, the immediate next question is: did traffic actually move to the backup, and how hard is the backup working?

```promql
incident_backup_link_utilization
```

Empty for the first ~60 seconds — you'll see "no data" or a flat panel. Once the primary actually goes down for the first time, the metric appears and ramps from around 20% toward 85%.

**Stop and notice.** The backup didn't start carrying traffic until the primary actually failed. That's failover working as intended. But notice the *direction* — utilisation is climbing past where the link is comfortable. This is the early-warning shape an experienced on-call reads as *we're going to have a latency problem in a couple of minutes if this doesn't recover*.

The metric was empty for a minute. That's not a query bug — the lab only emits backup-utilisation samples once the primary failure is real. In production you'd see the same gap in your TSDB if the metric is conditional on the failover happening.

### 5. The symptom your customers would actually feel — latency

```promql
incident_latency_ms
```

Empty even longer. Only starts climbing once backup utilisation crosses ~70%. From there it ramps from ~5ms toward 150ms.

**Stop and notice.** By the time latency is the visible problem, the actual root cause — the primary uplink fault — happened minutes ago. This is why incident timelines matter. The latency spike is a *symptom*. The flapping interface was the *cause*. If your alert fires on latency, your runbook needs to walk back through the cascade to find the real failure.

The cascade is the story. The metrics are the chapters. Operators read incidents this way every day.

### 6. Narrate the timeline

Now that the cascade has run, you should be able to tell the story from the metrics alone. Try answering these out loud:

- At t=0, what was the symptom you'd page on?
- At t=60s, what changed?
- At t=2 minutes, what would the customer-facing impact be?

A sample narration:

> *"Primary uplink started flapping around t=30s — `interface_oper_state` hit 0 for the first time. Failover to the backup happened next; backup utilisation appeared and started climbing. Around t=2 minutes, latency started degrading on the backup path. By the time customers complained about latency, the original cause was three minutes in the rear-view mirror."*

**Stop and notice.** This narration is what good runbooks help you do. The cascade isn't unique to this lab — it's the shape of every interface-degradation incident you'll see in production. Practising the narration here means recognising it faster when the dashboard is your real one.

There's a wall-clock detail worth calling out. You passed `--duration 90s`, but the whole incident takes roughly three to three-and-a-half minutes end-to-end. Each phase has to wait for the previous one to escalate before it starts. That's exactly how real incidents unfold — the root cause leads the symptoms by minutes. The duration you passed is per-phase, not the lifetime of the cascade.

### 7. Clean up

The cascade keeps running on the lab even after the CLI exits — each phase runs until its own duration is up. If you want to start fresh sooner, stop the active phases:

```bash
for ID in $(curl -s http://localhost:8085/scenarios \
  | jq -r '.scenarios[] | select(.name | startswith("incident_") or . == "interface_oper_state") | .id'); do
  curl -s -X DELETE "http://localhost:8085/scenarios/$ID"
done
```

That's an operational note, not a teardown ritual — leave the cascade running if you want to keep watching the dashboards react.

## Stretch goals

- **Drive the same incident on srl2.** Re-run with `--device srl2` and contrast the dashboards. Same shape, different device labels — the on-call playbook doesn't change.
- **Predict the customer-impact window.** Given the timing you just observed (primary starts flapping near t=30s, latency exceeds 100ms around t=3 min), at what point would a customer's response-time SLO break? Use the queries above to back the answer with data.
- **Tie the incident to the alert rules.** While the cascade is running, run `nobs autocon5 alerts`. Does `BgpSessionNotUp` fire? Does `PeerInterfaceFlapping`? Explain why each one does or doesn't fire. (Hint: the cascade emits to canonical metric names, but with `source="incident-cascade"`. Existing alert rules use a different label set.)

## What you took away

- The shape of an interface-degradation incident — primary fault → failover → backup pressure → latency — is universal. Recognise the shape, and you've already started triaging.
- An on-call engineer reads dashboards in causal order: the cause first (flap), then the mechanism (failover), then the symptom (latency). The query order in this guide mirrors that reading order on purpose.
- Empty panels at the start of an incident aren't a bug. Some signals only exist once an upstream failure has happened, and that gap is information — it tells you when each stage of the cascade actually fired.
- Latency is almost always a symptom, not a cause. When latency alerts fire, walk *back* through the cascade to find the real failure. The `source` label on synthetic incidents lets you scope a query to one cascade and read it in isolation.
- The wall-clock lifetime of an incident is longer than the duration of any single phase. Root cause leads symptoms by minutes — your runbook timing should reflect that.
