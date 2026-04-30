# Part 3 — Alerts, automation, AI-assisted ops

## What you'll do here

Drive each of the four canonical alert paths by hand, watch the Prefect workflow decide what to do with each, then optionally turn on the AI RCA step and compare its narrative against the deterministic policy. By the end you'll know exactly what the automation will and won't do for you — and which calls still belong to a human.

## Setup check

Two `BgpSessionNotUp` alerts should already be firing in the lab — the deliberately broken peers from Part 1.

```bash
nobs autocon5 alerts
```

You should see two rows, one for `srl1 ↔ 10.1.99.2` and one for `srl2 ↔ 10.1.11.1`. If you see fewer than two, give the stack 60 seconds and try again — alert evaluation has a `for: 30s` clause.

Open **Workshop Home** at <http://localhost:3000/d/workshop-home>. The **Currently firing alerts** table at the bottom should show those same two rows. Keep this dashboard open in a tab — you'll watch it react to your CLI commands throughout this part.

## The four canonical paths

The webhook flow runs the same decision tree on every alert payload. The four outcomes:

| Path | Trigger | Outcome |
|------|---------|---------|
| **Mismatch → quarantine** | Intent says peer up, metrics disagree | Silence in Alertmanager + audit annotation in Loki |
| **Healthy → skip** | Intent and metrics agree (no real problem) | Audit annotation only |
| **In-maintenance → skip** | Device's `maintenance` flag is `true` in Infrahub | Audit annotation only |
| **Resolved → audit trail** | Alert resolved | Audit annotation only |

Annotations land in Loki with `{source="workshop-trigger"}`. They're visible in **Recent events** feeds on both **Workshop Home** and **Device Health**.

## The exercises

### 1. Inspect what's already firing

```bash
nobs autocon5 alerts
```

Two `BgpSessionNotUp` rows. Each has `device` and `peer_address` labels. **Stop and notice.** Those labels are how the flow correlates the alert back to source-of-truth: it asks Infrahub "is this peer expected up? is this device in maintenance?" using exactly those keys.

### 2. Walk all four paths in one shot

```bash
nobs autocon5 try-it
```

This walks every path and reports each outcome. It takes ~2 minutes. Read the panels as they print:

- **Healthy** — sends a webhook for a peer that is actually fine; the flow annotates `skipped (healthy)` and exits.
- **Mismatch** — sends a webhook for one of the broken peers; the flow silences in Alertmanager and annotates `quarantined`.
- **Maintenance** — toggles `srl1.maintenance=true`, re-sends the mismatch webhook; the flow annotates `skipped (maintenance)` and clears the flag.
- **Resolved** — sends a `resolved` webhook; the flow annotates `resolved`.

When it finishes, run:

```bash
nobs autocon5 alerts
```

State should be back where it started — two BgpSessionNotUp rows. **Stop and notice.** The deterministic policy is what makes this useful in production. Same alert, four different actions, decided by enrichment data the flow pulls itself.

Open **Workshop Home** and look at the **Recent events** feed. You should see the four annotations the flow wrote.

### 3. Drive mismatch → quarantine by hand

Now do the path manually so you see the moving parts. A single `flap-interface` invocation now cascades through three signals automatically (interface metric flip → 10s hold-down → BGP collapse + prefix drop → restore), so even one call is enough to surface the mismatch path.

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

The command runs for ~46 seconds end-to-end. While it's running, in another terminal:

```bash
nobs autocon5 alerts
```

You should see a `PeerInterfaceFlapping` row appear within ~30 seconds (the rule fires on `> 3 UPDOWN events in a 2-minute window`, and Phase A pushes 6). Once the cascade enters Phase B, `BgpSessionNotUp` will *also* fire for `srl1 ↔ 10.1.2.2` because the BGP session's `bgp_oper_state` is now `2`.

Open **Workshop Home** in your browser — the **Currently firing alerts** table populates with both alerts. The webhook flow has already run by the time you look; check **Recent events** for the `quarantined` annotation.

If you want to trip *only* `PeerInterfaceFlapping` (without dragging BGP down), use `--no-cascade` and run the CLI four times in two minutes — the historical workshop path:

```bash
for i in 1 2 3 4; do
  nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1 --no-cascade
done
```

**Stop and notice.** From "press Enter on a CLI" to "alert fired, flow ran, action recorded" is under 60 seconds end-to-end. The cascade matches the shape of a real outage — interface degrades, BGP follows, prefixes drop — so the alert path you're exercising is the same one your on-call would face in production, just compressed in time.

### 4. Drive in-maintenance → skip

```bash
nobs autocon5 maintenance --device srl1 --state
```

This sets `srl1.maintenance=true` in Infrahub and writes a `Configured from CLI: srl1.maintenance = true` line to Loki. You can confirm:

```logql
{source="workshop-trigger"} |~ "maintenance"
```

Now re-trigger the flap:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

Wait ~30 seconds. Re-check alerts and the **Recent events** feed. The flow should have written `skipped (maintenance)` instead of `quarantined`. **Stop and notice.** Same metric data, same alert payload, completely different decision — because the flow consulted Infrahub before acting. This is what "context-aware alerting" actually means.

Reset before moving on:

```bash
nobs autocon5 maintenance --device srl1 --clear
```

### 5. Inspect the evidence bundle

The flow doesn't decide blindly. It pulls a correlated bundle of evidence — recent metrics, recent logs, source-of-truth state — and decides on that. Look at what it sees:

```bash
nobs autocon5 evidence srl1 10.1.99.2
```

You'll get a printed bundle with three sections:

- **Metrics** — recent `bgp_admin_state` / `bgp_oper_state` / interface state samples for the device + peer
- **Logs** — recent log lines filtered to that device + peer
- **Source of truth** — Infrahub's view: is the peer expected up, is the device in maintenance, what's the role

**Stop and notice.** This bundle is the input to *both* the deterministic policy *and* (when it's enabled) the AI RCA step. Same evidence, two consumers — one decides mechanically, one writes a narrative. Neither sees more than what the other sees.

### 6. Toggle the AI RCA step

By default, the AI step runs but writes a "AI RCA disabled" annotation — the flow finishes end-to-end either way.

To turn it on, edit `.env` in the workshop directory:

```bash
ENABLE_AI_RCA=true
AI_RCA_PROVIDER=openai          # or anthropic
AI_RCA_MODEL=gpt-4o-mini        # or e.g. claude-haiku-4-5-20251001
OPENAI_API_KEY=sk-...           # only the one matching AI_RCA_PROVIDER is required
```

Then:

```bash
nobs autocon5 restart prefect-flows
```

Re-trigger any path — the easiest is `nobs autocon5 try-it`. Watch the **Recent events** feed. For each path you'll now see two annotations: the deterministic policy result, and the LLM's narrative explanation right next to it.

If you don't have an API key handy, leave `ENABLE_AI_RCA=false`. Look at the disabled-fallback annotation — that itself is the lesson: the workflow runs end-to-end whether or not the AI step is enabled. The AI is opt-in commentary, not load-bearing.

**Stop and notice.** The LLM gets the same evidence bundle as the deterministic policy. It can't see the network, the runbooks, or last week's incident. Its output is annotated *next to* the policy result, not in place of it. The policy decided what action to take; the LLM wrote a paragraph about why the situation might exist. Two different jobs, both grounded in the same evidence.

### 7. Reflection (no clicking — just think)

Pick any of the paths you ran. Ask yourself:

> Which path would I trust the AI's narrative on without a second look? Which would I always double-check by hand? Why?

Some hints to guide the discussion:

- The mismatch-quarantine path acts on real production state. If the AI is wrong, what's the blast radius?
- The healthy-skip path is a no-op. Does the LLM narrative add anything for an on-call?
- The maintenance-skip path depends on Infrahub being right. What if Infrahub's wrong?
- The resolved path is post-hoc. Is "what just happened" a stronger or weaker case for AI than "what should I do now"?

There's no single right answer. The point is that the same tool isn't equally valuable for all four paths, and you should know which is which before you trust the narrative in the heat of an incident.

## Stretch goals

- **Tail the Prefect flow logs in real time.** `nobs autocon5 logs prefect-flows`. Re-run `try-it` and watch the flow narrate each path from the inside.
- **Compare evidence between a healthy peer and a broken one.** `nobs autocon5 evidence srl1 10.1.2.2` (a healthy peer) vs `nobs autocon5 evidence srl1 10.1.99.2` (a broken one). Pay attention to which fields differ — that's the signal the deterministic policy keys on.
- **Toggle maintenance on srl2 instead of srl1.** Re-run `try-it` after toggling. Confirm the maintenance-skip path swaps which device gets skipped. (Reset with `--clear` afterwards.)
- **Watch a path's annotations in Loki directly.** `{source="workshop-trigger"} | json` in Explore. Filter by `workflow="alert-receiver"` (or whatever the JSON shows) and watch annotations land while you trigger paths.

## What you took away

- Alerts are an explicit operational decision, not a notification. The deterministic flow turns each alert into a *specific action* by enriching with source-of-truth.
- The same alert payload routes to four different outcomes depending on context. Without enrichment, every alert looks the same.
- The evidence bundle is the contract between the deterministic policy and the AI RCA — both consume it, neither sees more than the other.
- Maintenance windows aren't a separate alerting layer. They're a label the flow consults at decision time. One source of truth, one decision point.
- AI RCA is opt-in narrative around the same evidence. It's annotation, not autonomy. Human judgment still owns the "act / don't act" call.
- The four paths are the recipe: mismatch → quarantine, healthy → skip, maintenance → skip, resolved → audit. Memorise them — they generalise to any alert your team writes.
