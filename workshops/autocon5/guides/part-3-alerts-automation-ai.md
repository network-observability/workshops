# Part 3 — Alerts, automation, AI-assisted ops

## What you'll do here

Late morning. The clock is creeping toward lunch. The flap-rate panel you built before the break is still pinned in a tab. You're both finishing coffee when a `BgpSessionNotUp` alert lands — a real one, on the lab. Your senior glances at the dashboard, then at you.

> *"Watch what happens automatically. The flow's going to handle this without us. Then I'll walk you through the four cases it covers, and you can drive each one yourself. By the end of the hour you'll know exactly what the automation can and can't do for you — and which calls still belong to a human."*

Drive each of the four alert paths by hand, watch the Prefect workflow decide what to do with each, then optionally turn on the AI RCA step and compare its narrative against the deterministic policy.

## Setup check

Reset to known-good baseline first — this expires any silences a prior `try-it` run might have created and clears any maintenance flags from earlier exercises:

```bash
nobs autocon5 reset
```

Two `BgpSessionNotUp` alerts should be firing in the lab — the deliberately broken peers from this morning.

```bash
nobs autocon5 alerts
```

You should see two rows. State will read either `firing` (caught right after the rule trips) or `suppressed` (more common — the webhook flow already ran on the alert and applied a `quarantine` silence). Both states mean the same thing: the alert is real and the workflow has decided what to do with it.

```
| Alertname       | Severity | Device / target  |      State | Age |
| BgpSessionNotUp | warning  | srl1 → 10.1.99.2 | suppressed | ... |
| BgpSessionNotUp | warning  | srl2 → 10.1.11.1 | suppressed | ... |
```

If you see fewer than two, give the stack 60 seconds and try again — alert evaluation has a `for: 30s` clause. If you see *more* than two — common after running Part 2 — give it about five minutes for the prior cascade's `PeerInterfaceFlapping` and `InterfaceAdminUpOperDown` alerts to age out. None of the residue blocks the four paths below.

Open **Workshop Home** at <http://localhost:3000/d/workshop-home>. The **Currently firing alerts** table at the bottom should show those same two rows. Keep this dashboard open in a tab — you'll watch it react to your CLI commands throughout this part.

## The four paths

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

Two `BgpSessionNotUp` rows. Each has `device` and `peer_address` labels. **Stop and notice.** Those labels are how the flow correlates the alert back to source-of-truth: it asks Infrahub "is this peer expected up? is this device in maintenance?" using exactly those keys. The `suppressed` state on each row *is* the workflow's containment action visible in the alert plane — the flow decided `proceed` on each of these and silenced the alert for 20 minutes.

### 2. Walk all four paths in one shot

> *"This walks every path in one shot. Don't worry about following each one — just watch what fires and what gets annotated. We'll go slowly the second time around."*

```bash
nobs autocon5 try-it --auto
```

This walks every path and reports each outcome. It takes ~3 minutes. You should see panels print like:

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

Each path POSTs an alert payload directly to the webhook and waits for the matching Prefect annotation to land in Loki. Four `✓` rows means the deterministic policy walked every branch correctly.

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

#### Tour the Prefect UI

> Your senior nods at the Loki feed. *"That's the audit trail. The flow itself has a UI on top of it — go look."*

Open Prefect at <http://localhost:4200/runs>. Sort by **Start Time** (newest first) and you'll see four `quarantine_bgp | …` (or `resolved_bgp | …`) flow runs from the `try-it` you just ran. Click the most recent `quarantine_bgp` run. You'll see:

- The **task graph** — `collect_evidence` → `evaluate_policy` → `annotate_decision` → `ai_rca`, plus (if the path was `proceed`) `quarantine` → `annotate_action`. The same pipeline you read about earlier, drawn for you.
- Per-task **state** and **duration** — which tasks ran, in what order, how long each took.
- Per-task **logs** — every `print()` and `get_run_logger()` line, indexed by task. Same content as `nobs autocon5 logs prefect-flows`, but searchable per task.
- **Tags** on each task: `device:srl1`, `peer_address:10.1.99.2`, `afi_safi:ipv4-unicast`, `action:quarantine`. These are how a future operator filters "all flows that touched this peer" without scrolling.

**Stop and notice.** The Loki annotations are the audit *record*; the Prefect UI is the audit *workshop*. Annotations are searchable but flat; the UI lets you drill into a specific task's logs without writing a LogQL query.

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

- **Within ~40–60 seconds**: a `PeerInterfaceFlapping` row appears. The rule needs `> 3 UPDOWN events in a 2-minute window`, plus a `for: 30s` clause and a Loki ruler eval cycle on top.
- **Within ~2 minutes**: `InterfaceAdminUpOperDown` for `srl1` appears (the alert needs the oper-state to be `2` consistently for `for: 2m`).
- **About a minute after the BGP session collapses**: `BgpSessionNotUp` *also* fires for `srl1 ↔ 10.1.2.2`. The chain is the 10s hold-down → next Prometheus scrape (≤15s) → `for: 30s` accumulation → ~55 seconds total before the alert is firing.

Open **Workshop Home** in your browser — the **Currently firing alerts** table populates with all of these. The webhook flow has already run by the time you look; check **Recent events** for the new `decision=proceed` annotation on `srl1 ↔ 10.1.2.2`. If the annotation hasn't shown up within ~30 seconds, use the **Trigger the same flow without an alert** tip below.

> Your senior taps the screen. *"That's the flow signaling 'this looks real, escalate it.' In production this is where a runbook fires, a ticket opens, an on-call gets paged. The flow doesn't pretend to fix the underlying problem — it categorises and routes."*

Switch to the Prefect UI for *your* run. Open <http://localhost:4200/runs> and filter by tag `peer_address:10.1.2.2` — the top result is the flow run the cascade just triggered. Click it and you'll see:

![Prefect flow run for the cascade-driven quarantine_bgp on srl1:10.1.2.2](../../../docs/assets/screenshots/prefect-flow-run-cascade-peer-light.png#only-light){ .screenshot loading=lazy }
![Prefect flow run for the cascade-driven quarantine_bgp on srl1:10.1.2.2](../../../docs/assets/screenshots/prefect-flow-run-cascade-peer-dark.png#only-dark){ .screenshot loading=lazy }

- The full six-task graph for the `proceed` path: `collect_evidence → evaluate_policy → annotate_decision → ai_rca → quarantine → annotate_action`.
- Per-task logs for *this* run: `collect_evidence` shows the SoT lookup result (`maintenance=False, expected_state=established`) and the metrics snapshot it pulled from Prometheus. `evaluate_policy` shows the two-stage decision. `quarantine` shows the `silence_id` Alertmanager returned.
- Task tags on the right-hand panel: `device:srl1`, `peer_address:10.1.2.2`, `afi_safi:ipv4-unicast`, `action:quarantine`. The Step 2 UI tour used the synthetic `try-it` runs; this is the same view on *your* live event.

When the interface cycles back to up, every gated metric snaps to its established-state value: `bgp_oper_state=1`, prefix counters back to `10`. Alerts resolve on the next scrape. That recovery beat — dashboard goes green within seconds of the interface returning — is the cascade's restore signal landing.

If you want to trip *only* `PeerInterfaceFlapping` (without dragging BGP down), use `--no-cascade`:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1 --no-cascade
```

That one call emits the interface flap and UPDOWN log stream alone, with no BGP gated entries — `PeerInterfaceFlapping` trips on the UPDOWN volume but `BgpSessionNotUp` stays clean.

??? tip "Trigger the same flow without an alert"

    The webhook is one event source. The Prefect deployment is the universal handle — you can run it from the UI's **Run** button or directly from the CLI:

    ```bash
    docker compose --project-name autocon5 exec prefect-flows \
      prefect deployment run alert-receiver/alert-receiver \
      --param alertname=BgpSessionNotUp \
      --param status=firing \
      --param 'alert_group={"alerts":[{"labels":{"device":"srl1","peer_address":"10.1.99.2","afi_safi_name":"ipv4-unicast"}}],"groupLabels":{"alertname":"BgpSessionNotUp"},"status":"firing"}'
    ```

    Same flow, same decision, no alert. Useful when you're iterating on the policy and don't want to wait for Alertmanager — or as a fallback if the cascade-driven annotation hasn't shown up.

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

This sets `srl1.maintenance=true` in Infrahub and writes a `Configured from CLI: srl1.maintenance = True` line to Loki. You can confirm two ways:

1. **In Loki** —

    ```logql
    {source="workshop-trigger"} |~ "maintenance"
    ```

    The most recent line should end in `srl1.maintenance = True`.

2. **In the Infrahub UI** — open <http://localhost:8000>, navigate to **Object Management → WorkshopDevice → srl1**. The `maintenance` attribute has just flipped to `true`. Notice the surrounding attributes: `intended_peer` / `expected_state` / `reason` / `asn` / `role` / `site_name`. Those are the schema fields the flow's policy reads when deciding `proceed` vs `skip` — the same shape you saw in Step 5's evidence bundle's first section, but at the source.

    From the device page, click any row in the **bgp_sessions** list to open the **BGP Session** detail — for example `10.1.99.2`:

    ![Infrahub WorkshopBgpSession detail for the broken peer 10.1.99.2](../../../docs/assets/screenshots/infrahub-bgp-session-broken.png#only-light){ .screenshot loading=lazy }
    ![Infrahub WorkshopBgpSession detail for the broken peer 10.1.99.2](../../../docs/assets/screenshots/infrahub-bgp-session-broken.png#only-dark){ .screenshot loading=lazy }

    `Expected State = Established`, `Reason = ip-mismatch-demo`, `Remote As = 65102`, `Device → srl1`. This is the per-peer intent the flow's policy reads in stage 1 (alongside the device's `maintenance` flag) before it ever looks at metrics. The `??? tip` below shows the GraphQL the flow runs to fetch the same fields.

If you prefer queries to UIs, the same answer is one GraphQL call away — the playground at <http://localhost:8000/graphql> runs the exact query the flow uses. The full query is below.

??? tip "See the exact query the flow runs"

    The Prefect flow asks Infrahub for intent via this GraphQL query (verbatim from `automation/workshop_sdk.py`). Paste it into the playground and you'll see the same answer the policy got — the flow has no secret access, just this query.

    ```graphql
    query DeviceIntent {
      WorkshopDevice(name__value: "srl1") {
        edges {
          node {
            name { value }
            maintenance { value }
            site_name { value }
            role { value }
            bgp_sessions {
              edges {
                node {
                  peer_address { value }
                  expected_state { value }
                  remote_as { value }
                  reason { value }
                }
              }
            }
          }
        }
      }
    }
    ```

Now re-trigger the flap:

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

Wait ~30 seconds, then in Loki:

```logql
{source="prefect", workflow="autocon5_quarantine_bgp", device="srl1"} | json
```

You should see the most recent annotation carry `decision=skip` with a message mentioning maintenance — the flow saw `srl1.maintenance=true` and skipped. If the new annotation hasn't shown up within ~30 seconds, Step 3's quarantine action silenced the alert; use the **Trigger the same flow without an alert** tip from Step 3 to surface the skip path.

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

**You should see a printed bundle with four sections:**

1. **Source of truth (Infrahub)** — device + intent: `expected_state=established`, `reason=ip-mismatch-demo`, `remote_as=65102`, `maintenance=false`.
2. **BGP metrics snapshot (Prometheus)** — a small table with `admin_state=1` (enable), `oper_state=5` (active — i.e. trying to establish), `received_routes=0`. Exactly the mismatch the alert fires on.
3. **Loki — last 20 relevant line(s)** — raw JSON log lines for the broken peer's BGP traffic *plus* prior Prefect annotations for this same peer (the audit trail). Verbose on purpose — every log line in full so you can grep / inspect labels.
4. **Policy hint** — what the deterministic policy *would* decide given the bundle above (`proceed` / `skip` / `resolved`), with the reason it would attach.

**Stop and notice.** This bundle is the input to *both* the deterministic policy *and* (when it's enabled) the AI RCA step. Same evidence, two consumers — one decides mechanically, one writes a narrative. Neither sees more than what the other sees.

??? info "What does the flow actually look like in Python?"

    `quarantine_bgp_flow` in `automation/flows.py` is short enough to read end-to-end. The six task calls match the task graph you saw in the Prefect UI:

    ```python
    @flow(log_prints=True, flow_run_name="quarantine_bgp | {device}:{peer_address}")
    def quarantine_bgp_flow(device, peer_address, ...):
        ev = collect_bgp_evidence_task(device=device, peer_address=peer_address, ...)
        decision = evaluate_policy_task(device=device, peer_address=peer_address, ev=ev)
        annotate_decision_task(workflow="autocon5_quarantine_bgp", ..., decision=decision)
        rca_text = ai_rca_task(workflow="autocon5_quarantine_bgp", ..., ev=ev)
        if decision.decision != "proceed":
            return {...}
        silence_id = quarantine_task(device=device, peer_address=peer_address, minutes=20)
        annotate_action_task(...)
        return {...}
    ```

    Six function calls. The `@flow` / `@task` decorators do the rest — retries, state transitions, the UI view, the tag-based search you used in Step 2. "Automation" here is a Python function with decorators on top.

### 6. Your turn — find what the flow actually did

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
| (empty)   |   1-3 |  ← AI RCA annotations, which carry an `ai_rca` label, not `decision`
```

The exact counts depend on how many paths you've driven by hand on top of `try-it`. If you get a single row, you've collapsed too aggressively. If you get dozens of rows, you've left a high-cardinality label unaggregated.

### 7. Toggle the AI RCA step

> *"Would the LLM narrative have helped you at 2am? Let's turn it on and find out."*

By default, the AI step runs but writes a "AI RCA disabled" annotation — the flow finishes end-to-end either way.

!!! info "No API key handy? Skip the toggle, the lesson still lands."

    Look at the disabled-fallback annotation in Step 5's evidence bundle — that itself is the lesson. The workflow runs end-to-end whether or not the AI step is enabled. The AI is opt-in commentary, not load-bearing. Read this section as reference, then go straight to Step 8.

With it on, every annotation gets a paired LLM narrative right next to the deterministic decision — same evidence, two voices.

To turn it on, edit `.env` in the workshop directory:

```bash
ENABLE_AI_RCA=true
AI_RCA_PROVIDER=openai          # or anthropic
AI_RCA_MODEL=gpt-4o-mini        # or e.g. claude-haiku-4-5-20251001
OPENAI_API_KEY=sk-...           # only the one matching AI_RCA_PROVIDER is required
```

Container env is baked at create-time, so `docker compose restart` won't pick up the new values — `prefect-flows` needs to be re-created. The cleanest way is to re-run `up` (it reads `.env` again and re-creates services whose effective config changed):

```bash
nobs autocon5 up
```

Or, if you want to force just the one container without touching anything else:

```bash
docker compose --project-name autocon5 up -d --force-recreate prefect-flows
```

Re-trigger any path — the easiest is `nobs autocon5 try-it --auto`. Watch the **Recent events** feed. For each path you'll now see two annotations: the deterministic policy result, and the LLM's narrative explanation right next to it. The LLM annotation carries an `ai_rca` label so you can isolate it:

```logql
{source="prefect", ai_rca!=""} | json
```

**Stop and notice.** The LLM gets the same evidence bundle as the deterministic policy. It can't see the network, the runbooks, or last week's incident. Its output is annotated *next to* the policy result, not in place of it. The policy decided what action to take; the LLM wrote a paragraph about why the situation might exist. Two different jobs, both grounded in the same evidence.

### 8. Reflection (no clicking — just think)

> Your senior leans back. *"Last one's a thinking exercise. Pick any of the paths you just ran and answer this for yourself."*

> Which path would I trust the AI's narrative on without a second look? Which would I always double-check by hand? Why?

Some hints to guide the discussion:

- The mismatch-proceed path acts on real production state. If the AI narrative is wrong, what's the blast radius?
- The healthy-skip path is a no-op. Does the LLM narrative add anything for an on-call?
- The maintenance-skip path depends on Infrahub being right. What if Infrahub's wrong?
- The resolved path is post-hoc. Is "what just happened" a stronger or weaker case for AI than "what should I do now"?

There's no single right answer. The point is that the same tool isn't equally valuable for all four paths, and you should know which is which before you trust the narrative in the heat of an incident.

## Stretch goals (optional — pick one if you have time)

- **Tail the Prefect flow logs in real time.** `nobs autocon5 logs prefect-flows`. Re-run `try-it --auto` and watch the flow narrate each path from the inside.
- **Compare evidence between a healthy peer and a broken one.** `nobs autocon5 evidence srl1 10.1.2.2` (a healthy peer) vs `nobs autocon5 evidence srl1 10.1.99.2` (a broken one). Pay attention to which fields differ — that's the signal the deterministic policy keys on.
- **Toggle maintenance on srl2 instead of srl1.** Re-run `try-it --auto` after toggling. Confirm the maintenance-skip path swaps which device gets skipped. (Reset with `--clear` afterwards.)
- **Watch a path's annotations in Loki directly.** `{source="prefect"} | json` in Explore. Filter by `workflow="autocon5_quarantine_bgp"` and watch annotations land while you trigger paths.
- **Wire a Prefect automation on the quarantine action.** In the Prefect UI at <http://localhost:4200/automations>, click **New automation**. Trigger: `Flow run state changed` → `quarantine_bgp_flow` → `Completed`. Action: `Send a notification` (or `Run a deployment` if you want to chain flows). Re-trigger a flap and confirm the automation fires. Same intent → match → action pattern as the alert pipeline, one layer up.

## What you took away

> Your senior signs off as the lunch break lands. *"You're ready to take primary tomorrow. If something fires, walk the same arc — triage, diagnose, contain, fix, document. The advanced guide is yours when you've eaten; if you take it, you'll know what 02:14 looks like by the time you get to it."*

- Alerts are an explicit operational decision, not a notification. The deterministic flow turns each alert payload into a *categorised action* by enriching with source-of-truth.
- The same alert payload routes to four different decisions depending on context (`proceed`, `skip` for healthy, `skip` for maintenance, `resolved`). Without enrichment, every alert looks the same.
- The evidence bundle is the contract between the deterministic policy and the AI RCA — both consume it, neither sees more than the other.
- Maintenance windows aren't a separate alerting layer. They're a label the flow consults at decision time. One source of truth, one decision point.
- AI RCA is opt-in narrative around the same evidence. It's annotation, not autonomy. Human judgment still owns the "act / don't act" call.
- The four paths are the recipe: mismatch → proceed, healthy → skip, maintenance → skip, resolved → audit. Memorise them — they generalise to any alert your team writes.
