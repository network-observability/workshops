# Part 3 — Alerts, automation, AI-assisted ops

## What you'll do here

Late morning. The clock is creeping toward lunch. The flap-rate panel you built before the break is still pinned in a tab. You're both finishing coffee when a `BgpSessionNotUp` alert lands — a real one, on the lab. Your senior glances at the dashboard, then at you.

> *"Watch what happens automatically. The flow's going to handle this without us. Then I'll walk you through the four cases it covers, and you can drive each one yourself. By the end of the hour you'll know exactly what the automation can and can't do for you — and which calls still belong to a human."*

Drive each of the four canonical alert paths by hand, watch the Prefect workflow decide what to do with each, then optionally turn on the AI RCA step and compare its narrative against the deterministic policy.

## Setup check

Reset to known-good baseline first — this expires any silences a prior `try-it` run might have created and clears any maintenance flags from earlier exercises:

```bash
nobs autocon5 reset
```

Two `BgpSessionNotUp` alerts should be firing in the lab — the deliberately broken peers from this morning.

```bash
nobs autocon5 alerts
```

You should see two rows:

```
| Alertname       | Severity | Device / target  |  State | Age |
| BgpSessionNotUp | warning  | srl1 → 10.1.99.2 | firing | ... |
| BgpSessionNotUp | warning  | srl2 → 10.1.11.1 | firing | ... |
```

If you see fewer than two, give the stack 60 seconds and try again — alert evaluation has a `for: 30s` clause.

Open **Workshop Home** at <http://localhost:3000/d/workshop-home>. The **Currently firing alerts** table at the bottom should show those same two rows. Keep this dashboard open in a tab — you'll watch it react to your CLI commands throughout this part.

## The four canonical paths

The webhook flow runs the same decision tree on every alert payload. The four outcomes:

| Path | Trigger | Decision | Outcome |
|------|---------|---------|---------|
| **Mismatch → proceed** | Intent says peer up, metrics disagree | `proceed` | The flow signals "this needs human attention" — visible in the audit annotation, no silence |
| **Healthy → skip** | Intent and metrics agree (no real problem) | `skip` | Audit annotation only |
| **In-maintenance → skip** | Device's `maintenance` flag is `true` in Infrahub | `skip` | Audit annotation only |
| **Resolved → audit trail** | Alert resolved | `resolved` | Audit annotation only |

Annotations land in Loki under `{source="prefect", workflow="autocon5_quarantine_bgp"}` with a `decision` label that takes one of: `proceed`, `skip`, `resolved`. They're visible in **Recent events** feeds on both **Workshop Home** and **Device Health**.

## The exercises

### 1. Inspect what's already firing

> *"Run this. We'll look at the raw alert state before we touch the workflow."*

```bash
nobs autocon5 alerts
```

Two `BgpSessionNotUp` rows. Each has `device` and `peer_address` labels. **Stop and notice.** Those labels are how the flow correlates the alert back to source-of-truth: it asks Infrahub "is this peer expected up? is this device in maintenance?" using exactly those keys.

### 2. Walk all four paths in one shot

> *"This walks every path in one shot. Don't worry about following each one — just watch what fires and what gets annotated. We'll go slowly the second time around."*

```bash
nobs autocon5 try-it --auto
```

This walks every path and reports each outcome. It takes ~3 minutes. You should see panels print like:

```
╭─── Path 1 - Actionable / mismatch → quarantine ───╮
   ✗ quarantine flow ran and decided 'proceed' - ...

╭─── Path 2 - In-maintenance → skip ───╮
   ✓ srl1.maintenance = True
   ✓ replayed firing payload for srl1 → 10.1.99.2
   ✓ quarantine flow saw maintenance=true and skipped

╭─── Path 3 - Healthy peer → skip ───╮
   ✓ replayed firing payload for srl1 → 10.1.2.2
   ✗ quarantine flow decided 'skip' for healthy peer - ...

╭─── Path 4 - Resolved → audit ───╮
   ✓ replayed resolved payload for srl1 → 10.1.99.2
   ✓ resolved_bgp_flow ran and annotated 'resolved'
```

Don't worry about the `✗` markers on Paths 1 and 3 — try-it's polling tolerance is tight; the decisions still landed in Loki, just under labels try-it didn't grep for. We'll inspect them by hand below.

When it finishes, run:

```bash
nobs autocon5 alerts
```

State should be back where it started — two `BgpSessionNotUp` rows. **Stop and notice.** The deterministic policy is what makes this useful in production. Same alert payload shape, four different decisions, decided by enrichment data the flow pulls itself.

Open **Workshop Home** and look at the **Recent events** feed. You should see four annotations the flow wrote, one per path. In the Loki Explore tab:

```logql
{source="prefect", workflow="autocon5_quarantine_bgp"}
```

Returns the audit trail for every payload the flow handled. Each line carries a `decision` label — `proceed`, `skip`, or `resolved`.

### 3. Drive mismatch → proceed by hand

> *"Now do it slowly so you see the moving parts. Same path, but you're driving."*

A single `flap-interface` invocation posts one declarative cascade to sonda (interface flap → 10s hold-down → BGP collapse → automatic snap-back when the interface comes back up), so one call is enough to surface the mismatch path.

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

The cascade runs on the lab for 4 minutes by default, walking through 30s-up / 60s-down cycles. The CLI returns immediately — sonda is driving the cascade now. While it's running, in another terminal:

```bash
nobs autocon5 alerts
```

**What you should see, in order:**

- **Within ~30 seconds**: a `PeerInterfaceFlapping` row appears (the rule fires on `> 3 UPDOWN events in a 2-minute window`, and the down window emits one UPDOWN line every two seconds — about 30 lines per 60s down).
- **Within ~40-50 seconds**: `InterfaceAdminUpOperDown` for `srl1` appears (the alert needs the oper-state to be `2` consistently for `for: 2m`).
- **Once the interface drops and the 10s hold-down expires**: `BgpSessionNotUp` *also* fires for `srl1 ↔ 10.1.2.2` because the BGP session's `bgp_oper_state` is now `2`.

Open **Workshop Home** in your browser — the **Currently firing alerts** table populates with all of these. The webhook flow has already run by the time you look; check **Recent events** for the new `decision=proceed` annotation on `srl1 ↔ 10.1.2.2`.

> Your senior taps the screen. *"That's the flow signaling 'this looks real, escalate it.' In production this is where a runbook fires, a ticket opens, an on-call gets paged. The flow doesn't pretend to fix the underlying problem — it categorises and routes."*

When the interface cycles back to up, every gated metric snaps to its established-state value: `bgp_oper_state=1`, prefix counters back to `10`. Alerts resolve on the next scrape. That recovery beat — dashboard goes green within seconds of the interface returning — is the cascade's restore signal landing.

If you want to trip *only* `PeerInterfaceFlapping` (without dragging BGP down), use `--no-cascade`:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1 --no-cascade
```

That one call emits the interface flap and UPDOWN log stream alone, with no BGP gated entries — `PeerInterfaceFlapping` trips on the UPDOWN volume but `BgpSessionNotUp` stays clean.

**Stop and notice.** From "press Enter on a CLI" to "alert fired, flow ran, action recorded" is under 60 seconds end-to-end. The cascade matches the shape of a real outage — interface degrades, BGP follows, prefixes drop, recovery snaps everything back — so the alert path you're exercising is the same one your on-call would face in production, just compressed in time.

### 4. Drive in-maintenance → skip

> *"Same alert payload, completely different decision — because the flow consulted Infrahub before acting. This is what context-aware alerting actually means."*

```bash
nobs autocon5 maintenance --device srl1 --state
```

You should see:

```
╭──── WorkshopDevice updated ────╮
│ srl1.maintenance: False → True │
╰────────────────────────────────╯
   The next alert for this device will be SKIPPED by the policy.
```

This sets `srl1.maintenance=true` in Infrahub and writes a `Configured from CLI: srl1.maintenance = True` line to Loki. You can confirm:

```logql
{source="workshop-trigger"} |~ "maintenance"
```

You should see the most recent line ending in `srl1.maintenance = True`.

Now re-trigger the flap:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

Wait ~30 seconds, then in Loki:

```logql
{source="prefect", workflow="autocon5_quarantine_bgp", device="srl1"} | json
```

You should see the most recent annotation carry `decision=skip` with a message mentioning maintenance — the flow saw `srl1.maintenance=true` and skipped.

**Stop and notice.** Same metric data, same alert payload, completely different decision — because the flow consulted Infrahub before acting.

Reset before moving on:

```bash
nobs autocon5 maintenance --device srl1 --clear
```

Output mirrors the `--state` shape: `srl1.maintenance: True → False` and `The next alert for this device will be evaluated normally.`

### 5. Inspect the evidence bundle

> *"This bundle is the input to both the deterministic policy and the AI step. Same evidence, two consumers."*

The flow doesn't decide blindly. It pulls a correlated bundle of evidence — recent metrics, recent logs, source-of-truth state — and decides on that. Look at what it sees:

```bash
nobs autocon5 evidence srl1 10.1.99.2
```

**You should see a printed bundle with three sections:**

```
╭─── Source of truth (Infrahub) ───╮
│ device          srl1   site=lab  role=edge
│ maintenance     false
│ intended peer   yes
│ expected state  established
│ reason          ip-mismatch-demo
│ remote_as       65102
╰──────────────────────────────────╯

   BGP metrics snapshot (Prometheus)
| Metric            | Value | Decoded |
| admin_state       |     1 | enable  |
| oper_state        |     5 | active  |
| received_routes   |     0 |   —     |
| ...

╭─── Loki — last 20 relevant line(s) ───╮
│ {... "labels":{"decision":"resolved", "device":"srl1", "peer_address":"10.1.99.2", ...}}
│ {... BGP-related log lines for that peer ...}
╰────────────────────────────────────────╯
```

The metrics row tells you the peer is configured to be up (`admin_state=1`) but operationally trying-to-establish (`oper_state=5`) and receiving zero prefixes — exactly the mismatch the alert fires on. The Infrahub block tells you intent (`expected_state=established`, `reason=ip-mismatch-demo`). The Loki block carries both the broken-peer's BGP log lines AND prior Prefect annotations for this same peer — that's the audit trail.

**Stop and notice.** This bundle is the input to *both* the deterministic policy *and* (when it's enabled) the AI RCA step. Same evidence, two consumers — one decides mechanically, one writes a narrative. Neither sees more than what the other sees.

### 6. Toggle the AI RCA step

> *"Would the LLM narrative have helped you at 2am? Let's turn it on and find out."*

By default, the AI step runs but writes a "AI RCA disabled" annotation — the flow finishes end-to-end either way.

To turn it on, edit `.env` in the workshop directory:

```bash
ENABLE_AI_RCA=true
AI_RCA_PROVIDER=openai          # or anthropic
AI_RCA_MODEL=gpt-4o-mini        # or e.g. claude-haiku-4-5-20251001
OPENAI_API_KEY=sk-...           # only the one matching AI_RCA_PROVIDER is required
```

`nobs autocon5 up` reuses the cached image, so the new env vars won't reach Prefect until you restart the flows container:

```bash
nobs autocon5 restart prefect-flows
```

Re-trigger any path — the easiest is `nobs autocon5 try-it --auto`. Watch the **Recent events** feed. For each path you'll now see two annotations: the deterministic policy result, and the LLM's narrative explanation right next to it. The LLM annotation carries an `ai_rca` label so you can isolate it:

```logql
{source="prefect", ai_rca!=""} | json
```

If you don't have an API key handy, leave `ENABLE_AI_RCA=false`. Look at the disabled-fallback annotation — that itself is the lesson: the workflow runs end-to-end whether or not the AI step is enabled. The AI is opt-in commentary, not load-bearing.

**Stop and notice.** The LLM gets the same evidence bundle as the deterministic policy. It can't see the network, the runbooks, or last week's incident. Its output is annotated *next to* the policy result, not in place of it. The policy decided what action to take; the LLM wrote a paragraph about why the situation might exist. Two different jobs, both grounded in the same evidence.

### Your turn — find what the flow actually did

> Your senior gestures at the screen. *"You've watched the paths run. Now show me — without scrolling the dashboard — how many alert payloads the flow has handled in the last 30 minutes, broken down by decision. One LogQL line. The annotations carry everything you need."*

This is unguided. The flow writes its audit trail into Loki with `source="prefect"` and a few labels that distinguish each path (`workflow`, `decision`, `device`, `peer_address`, `ai_rca` — explore them).

Take a minute on it before you scroll. Two hints if you're stuck:

- `count_over_time({...}[30m])` turns a Loki query into a metric just like in Part 1 Exercise 10.
- `sum by (label) (...)` collapses everything except the label you list. Pick the label that gives the most informative breakdown — try `workflow` first (one row, not very useful), then try `decision` (a small handful of rows, much more useful).

**You should land on a query that returns a small handful of rows** — something like:

```
| decision  | count |
| proceed   |   1-3 |
| skip      |   1-2 |
| resolved  |   1-2 |
| (empty)   |   1-3 |  ← side annotations without a decision label
```

The exact counts depend on how many paths you've driven by hand on top of `try-it`. If you get a single row, you've collapsed too aggressively. If you get dozens of rows, you've left a high-cardinality label unaggregated.

### 7. Reflection (no clicking — just think)

> Your senior leans back. *"Last one's a thinking exercise. Pick any of the paths you just ran and answer this for yourself."*

> Which path would I trust the AI's narrative on without a second look? Which would I always double-check by hand? Why?

Some hints to guide the discussion:

- The mismatch-proceed path acts on real production state. If the AI narrative is wrong, what's the blast radius?
- The healthy-skip path is a no-op. Does the LLM narrative add anything for an on-call?
- The maintenance-skip path depends on Infrahub being right. What if Infrahub's wrong?
- The resolved path is post-hoc. Is "what just happened" a stronger or weaker case for AI than "what should I do now"?

There's no single right answer. The point is that the same tool isn't equally valuable for all four paths, and you should know which is which before you trust the narrative in the heat of an incident.

## Stretch goals

- **Tail the Prefect flow logs in real time.** `nobs autocon5 logs prefect-flows`. Re-run `try-it --auto` and watch the flow narrate each path from the inside.
- **Compare evidence between a healthy peer and a broken one.** `nobs autocon5 evidence srl1 10.1.2.2` (a healthy peer) vs `nobs autocon5 evidence srl1 10.1.99.2` (a broken one). Pay attention to which fields differ — that's the signal the deterministic policy keys on.
- **Toggle maintenance on srl2 instead of srl1.** Re-run `try-it --auto` after toggling. Confirm the maintenance-skip path swaps which device gets skipped. (Reset with `--clear` afterwards.)
- **Watch a path's annotations in Loki directly.** `{source="prefect"} | json` in Explore. Filter by `workflow="autocon5_quarantine_bgp"` and watch annotations land while you trigger paths.

## What you took away

> Your senior signs off as the lunch break lands. *"You're ready to take primary tomorrow. If something fires, walk the same arc — triage, diagnose, contain, fix, document. The advanced guide is yours when you've eaten; if you take it, you'll know what 02:14 looks like by the time you get to it."*

- Alerts are an explicit operational decision, not a notification. The deterministic flow turns each alert payload into a *categorised action* by enriching with source-of-truth.
- The same alert payload routes to four different decisions depending on context (`proceed`, `skip` for healthy, `skip` for maintenance, `resolved`). Without enrichment, every alert looks the same.
- The evidence bundle is the contract between the deterministic policy and the AI RCA — both consume it, neither sees more than the other.
- Maintenance windows aren't a separate alerting layer. They're a label the flow consults at decision time. One source of truth, one decision point.
- AI RCA is opt-in narrative around the same evidence. It's annotation, not autonomy. Human judgment still owns the "act / don't act" call.
- The four paths are the recipe: mismatch → proceed, healthy → skip, maintenance → skip, resolved → audit. Memorise them — they generalise to any alert your team writes.
