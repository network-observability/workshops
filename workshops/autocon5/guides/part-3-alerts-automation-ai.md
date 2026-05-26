# Part 3 — Alerts, automation, AI-assisted ops

## What you'll do here

Late morning. The clock is creeping toward lunch. The flap-rate panel you built before the break is still pinned in a tab. You're both finishing coffee when a `BgpSessionNotUp` alert lands — a real one, on the lab. Your senior glances at the dashboard, then at you.

> *"Watch what happens automatically. The flow's going to handle this without us. Then I'll walk you through the four cases it covers, and you can drive each one yourself. By the end of the hour you'll know exactly what the automation can and can't do for you — and which calls still belong to a human."*

Drive each of the four alert paths by hand, watch the Prefect workflow decide what to do with each, then optionally turn on the AI RCA step and compare its narrative against the deterministic policy.

??? info "Visual — the full arc, Steps 1 through 8"

    ```text
                              Setup
                                │
                                ▼
                          ┌─────────────┐
                          │  Step 1     │  inspect what's firing
                          └──────┬──────┘  (2 suppressed rows)
                                 │
                                 ▼
                          ┌─────────────┐
                          │  Step 2     │  try-it --auto
                          └──────┬──────┘  (4 paths in 30s)
                                 │
                                 ▼
                          ┌─────────────┐
                          │  Step 3     │  incident drill:
                          │  flap →     │   A. page lands
                          │  proceed    │   B. investigate (evidence)
                          └──────┬──────┘   C. flow decided
                                 │           D. recovery
                                 ▼
                          ┌─────────────┐
                          │  Step 4     │  same drill,
                          │  maintenance│  maintenance=true
                          │  → skip     │  → opposite decision
                          └──────┬──────┘
                                 │
                                 ▼
                          ┌─────────────┐
                          │  Step 5     │  unguided LogQL
                          │  what did   │  sum by (decision)
                          │  the flow do│   (count_over_time …)
                          └──────┬──────┘
                                 │
                                 ▼
                          ┌─────────────┐
                          │  Step 6     │  AI RCA on (demo provider)
                          │  same       │  same evidence →
                          │  evidence,  │   two annotations
                          │  two voices │
                          └──────┬──────┘
                                 │
                                 ▼
                          ┌─────────────┐
                          │  Step 7     │  compose another
                          │  Prefect    │  trigger → match → action
                          │  automation │  (one layer up)
                          └──────┬──────┘
                                 │
                                 ▼
                          ┌─────────────┐
                          │  Step 8     │  reflection
                          └─────────────┘
    ```

## Setup check

Reset to known-good baseline first — this expires any silences a prior `try-it` run might have created and clears any maintenance flags from earlier exercises:

```bash
nobs autocon5 reset
```

Four alerts should be firing in the lab — two per category, one per device:

- **`BgpSessionNotUp` × 2** — the deliberately broken peers from this morning (`srl1 → 10.1.99.2`, `srl2 → 10.1.11.1`). State cycles `firing` ↔ `suppressed` as the webhook flow runs and Alertmanager silences expire on a 20-minute window.
- **`InterfaceAdminUpOperDown` × 2** — `ethernet-1/11` on each device is configured as `admin up` but its `oper` state is `down`. That's a permanent intent-vs-reality mismatch, so the rule fires continuously and never ages out.

```bash
nobs autocon5 alerts
```

```
| Alertname                | Severity | Device / target  |      State | Age |
| BgpSessionNotUp          | warning  | srl1 → 10.1.99.2 | suppressed | ... |
| BgpSessionNotUp          | warning  | srl2 → 10.1.11.1 | suppressed | ... |
| InterfaceAdminUpOperDown | warning  | srl1             |     firing | ... |
| InterfaceAdminUpOperDown | warning  | srl2             |     firing | ... |
```

`InterfaceAdminUpOperDown` is steady-state — the underlying mismatch is permanent, so the rule will never age out. Step 3.A revisits this when you flap an interface. The only alert that should ever move between `firing` and `suppressed` here is `BgpSessionNotUp`: it's `firing` immediately after the rule trips, then `suppressed` once the webhook flow applies its 20-minute `quarantine` silence, then `firing` again when the silence expires.

If you see fewer than two `BgpSessionNotUp` rows, give the stack 60 seconds and try again — alert evaluation has a `for: 30s` clause and you might have caught it before promotion. If you ran Part 2 and see a `PeerInterfaceFlapping` row, that's residue from the flap cascade — it ages out within ~5 minutes of the last flap. None of these conditions block the four paths below.

Open **Workshop Home** at <http://localhost:3000/d/workshop-home>. The **Currently firing alerts** table at the bottom should show those same four rows. Keep this dashboard open in a tab — you'll watch it react to your CLI commands throughout this part.

## The four paths

Every `BgpSessionNotUp` payload that lands on the webhook gets fed through the same **decision tree**: a deterministic Python function that pulls **intent** (from Infrahub) and **reality** (from Prometheus metrics) for the affected peer, compares them, and returns one of a fixed set of outcomes. "Deterministic" here means the same inputs always produce the same decision — no probabilistic step, no LLM judgment in the path. You can replay any historical alert and get bit-identical reasoning, which is what makes the flow reviewable in code review and replayable in a post-mortem. The AI RCA step you'll turn on in Step 6 sits *alongside* this decision, not inside it.

```text
   alert payload
        │
        ▼
   collect_evidence  ── SoT (Infrahub) + metrics (Prom) + logs (Loki)
        │
        ▼
   evaluate_policy  ── deterministic decision tree
        │
        ▼
   one of: proceed · skip · resolved · stop
```

Why these four outcomes specifically (three skips and one proceed)? Because the policy needs to distinguish three different *reasons not to act* — the peer is healthy, the device is in a maintenance window, or the alert already resolved itself — from the single reason *to act*: source-of-truth and metrics disagree and a human probably needs to know. Collapsing any pair into one outcome would lose audit signal; splitting any further would mean the policy is doing something the SoT schema can't yet express.

Every decision the flow makes lands in Loki as an **audit annotation** — one log line per evaluation, written by the `annotate_decision` task right after `evaluate_policy` returns. The annotation carries the device, the peer, and a `decision` label, which is what lets you ask Loki "how many alerts has the flow decided `proceed` on in the last hour?" without scrolling. Step 5 is the unguided exercise where you answer that question yourself.

| Path | Trigger | Decision | Outcome |
|------|---------|---------|---------|
| **Mismatch → proceed** | Intent says peer up, metrics disagree | `proceed` | The flow signals "this needs human attention" — visible in the audit annotation, no silence |
| **Healthy → skip** | Intent and metrics agree (no real problem) | `skip` | Audit annotation only |
| **In-maintenance → skip** | Device's `maintenance` flag is `true` in Infrahub | `skip` | Audit annotation only |
| **Resolved → audit trail** | Alert resolved | `resolved` | Audit annotation only |

There's a fifth outcome the policy can emit but that `try-it` doesn't exercise: **`stop`** — fires when the device on the alert isn't in Infrahub at all (the SoT lookup returns nothing). The flow can't decide `proceed` vs `skip` without intent data, so it bails early with `decision=stop` and a `device not found in Infrahub` reason. You'll typically only see it if an alert fires before `nobs autocon5 load-infrahub` has finished seeding the schema — rare, but real.

Annotations land in Loki under `{source="prefect", workflow="autocon5_quarantine_bgp"}` with a `decision` label that takes one of: `proceed`, `skip`, `resolved`, `stop`. They're visible in **Recent events** feeds on both **Workshop Home** and **Device Health**.

??? info "What's a decision tree — and why deterministic?"

    A **decision tree** in this context is a small Python function (`DecisionPolicy.evaluate` in [`workshops/autocon5/automation/workshop_sdk.py`](https://github.com/network-observability/workshops/blob/main/workshops/autocon5/automation/workshop_sdk.py)) that takes the evidence bundle and walks a fixed set of `if / elif` branches to pick one of `proceed` / `skip` / `resolved` / `stop`. Two stages: first the source-of-truth gate (is the device in maintenance? is this peer even *supposed* to be up?), then — only if the SoT gate doesn't short-circuit — the metrics check.

    "Deterministic" matters here for four reasons:

    - **Predictable.** Same evidence in, same decision out. No model temperature, no roll of the dice at 02:14.
    - **Replayable.** Six months from now, you can rerun the same alert payload through the same policy version and see the same outcome — the audit trail is meaningful.
    - **Version-controlled.** The policy is code. Changes go through a PR like everything else; a reviewer can read what changed before it ships to production.
    - **Reviewable in incident review.** When the on-call asks "why did the flow silence this?", the answer is a function call you can step through, not a model output to argue about.

    The AI RCA step you'll turn on in Step 6 is the opposite end of this trade-off — a narrative-generating model that consumes the same evidence bundle but produces prose, not a decision. The deterministic policy acts; the AI annotates. They're separate jobs by design.

??? info "What's an audit annotation — and where does it land?"

    An **audit annotation** is a single Loki log line that the flow writes immediately after `evaluate_policy` returns. The `annotate_decision` task is what produces it — one annotation per alert payload, regardless of which path the policy took. Skips and proceeds and resolveds all get one. That's how you get a complete record of every decision the flow ever made.

    The canonical query in Explore:

    ```logql
    {source="prefect", workflow="autocon5_quarantine_bgp"} | json
    ```

    Every line carries a `decision` label set to one of `proceed`, `skip`, `resolved`, `stop`, plus `device` and `peer_address` for correlation. The annotations land in the same Loki the workshop uses for every other log stream. Step 5 is where you'll write the LogQL that turns this label set into a "how many `proceed` vs `skip` decisions in the last hour?" breakdown.

??? info "What's a maintenance window — and how does it differ from a silence?"

    A **maintenance window** is intent expressed in the source of truth: `WorkshopDevice.maintenance = true` on a device in Infrahub. It says "we know this device is being worked on; alerts about it are expected and should be skipped." The policy reads this flag in stage 1 of the decision tree, *before* it ever looks at metrics, and short-circuits to `skip` if it's set.

    A **silence** is a per-alert mute applied in Alertmanager after a decision is already made. When the policy decides `proceed` on a real mismatch, the flow's `quarantine` task asks Alertmanager to silence the matching alert for 20 minutes so the same page doesn't fire repeatedly while the situation is being investigated.

    One is **upstream** of the decision (maintenance shapes which decision the policy returns); the other is **downstream** of it (a silence is one of the actions a `proceed` decision triggers). Conflating them is the most common confusion in this part of the workshop — Step 4 walks the maintenance path explicitly to drive the distinction home.

## The exercises

### 1. Inspect what's already firing

> *"Run this. We'll look at the raw alert state before we touch the workflow."*

```bash
nobs autocon5 alerts
```

Four rows. Two `BgpSessionNotUp` (the actionable ones — each has `device` and `peer_address` labels) and two `InterfaceAdminUpOperDown` (always-firing, steady-state). For the rest of this part, focus on the `BgpSessionNotUp` pair — those are the alerts the webhook flow acts on. **Stop and notice.** Those `device` and `peer_address` labels are how the flow correlates the alert back to source-of-truth: it asks Infrahub "is this peer expected up? is this device in maintenance?" using exactly those keys. The `suppressed` state on each row *is* the workflow's containment action visible in the alert plane — the flow decided `proceed` on each of these and silenced the alert for 20 minutes.

### 2. Walk all four paths in one shot

> *"This walks every path in one shot. Don't worry about following each one — just watch what fires and what gets annotated. We'll go slowly the second time around."*

```bash
nobs autocon5 try-it --auto
```

This walks every path and reports each outcome. It takes around 30 seconds end-to-end. You should see panels print like:

```
╭─── Path 1 - Actionable / mismatch → proceed ───╮
   ✓ replayed firing payload for srl1 → 10.1.99.2
   ✓ quarantine flow decided 'proceed' for the actionable mismatch (Loki match count=1)

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

### 3. Incident drill — the page lands

> *"Stop watching for a second. Imagine this is 2am. Your phone goes off. We're going to walk it like a real incident — page lands, you investigate, you decide, you watch the dust settle. Same four paths you saw in `try-it`, but you're driving and there's no commentary track."*

#### A. The page lands

Drive the interface flap. Sonda's runtime takes over from here — the CLI returns immediately and the cascade plays out over the next four minutes (30s up / 60s down):

```bash
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

In another terminal, watch alerts fire:

```bash
nobs autocon5 alerts
```

**What you'll see roll in, in order:**

- **Within ~90 seconds**: `PeerInterfaceFlapping` appears in the firing list. The rule needs `> 3 UPDOWN events in 2 minutes` plus a `for: 30s` clause, on top of the cascade's UP-first-then-DOWN cadence.
- **`InterfaceAdminUpOperDown`** is already firing for both devices in steady state (the always-broken `ethernet-1/11` keeps it active). The flap doesn't add a new alert here — it confirms the rule keeps firing while `ethernet-1/1` is also down.
- **Around the same window**: `BgpSessionNotUp` *also* fires for `srl1 ↔ 10.1.2.2`. That's the cascade dragging the BGP session down with the interface. This is the alert the webhook flow will act on.

Open **Workshop Home** at <http://localhost:3000/d/workshop-home> in a tab and keep it visible — you'll watch the firing-alerts table and the Recent events feed react.

#### B. Investigate — pull the evidence bundle

Before the flow's decision lands, look at the same evidence the flow is about to see:

```bash
nobs autocon5 evidence srl1 10.1.2.2
```

**Four sections print:**

1. **Source of truth (Infrahub)** — device + intent: `expected_state=established`, `maintenance=false`, no `reason` (this peer is supposed to be healthy).
2. **BGP metrics snapshot (Prometheus)** — `admin_state=1` (enable), `oper_state=2` (down — the cascade is dragging it), `received_routes=0`.
3. **Loki — last 20 relevant line(s)** — recent BGP traffic for this peer plus any prior Prefect annotations (the audit trail).
4. **Policy hint** — what the deterministic policy *would* decide given the bundle (`proceed` / `skip` / `resolved`) and why.

**Stop and notice.** This bundle is the input the flow's `collect_evidence` task pulls every time it runs. Same evidence, two downstream consumers — the deterministic policy decides mechanically, the AI RCA step (next exercise) writes a narrative. Neither sees more than what the other sees.

#### C. The flow has already decided — see what it did

While you were reading the evidence bundle, the cascade-driven `BgpSessionNotUp(srl1 ↔ 10.1.2.2)` payload was racing through the webhook and into `quarantine_bgp_flow`. Whether it landed depends on scrape timing — the cascade flips the BGP session for ~50s, and the alert needs `for: 30s` to satisfy. On a fast scrape window it fires and the flow runs; on a slow one BGP recovers before the alert promotes from `pending` to `firing`.

Check **Recent events** on Workshop Home — if you see a fresh annotation for `peer_address=10.1.2.2` with `decision=proceed`, you caught the natural path. If not (the common case), use the direct trigger below — same flow, same decision, no waiting on scrape windows:

```bash
docker compose --project-name autocon5 exec prefect-flows \
  prefect deployment run alert-receiver/alert-receiver \
  --param alertname=BgpSessionNotUp \
  --param status=firing \
  --param 'alert_group={"alerts":[{"labels":{"device":"srl1","peer_address":"10.1.2.2","afi_safi_name":"ipv4-unicast"}}],"groupLabels":{"alertname":"BgpSessionNotUp"},"status":"firing"}'
```

Recheck Recent events — `decision=proceed` for `peer_address=10.1.2.2` should be there now.

> Your senior taps the screen. *"That's the flow signalling 'this looks real, escalate it.' In production this is where a runbook fires, a ticket opens, an on-call gets paged. The flow doesn't pretend to fix the underlying problem — it categorises and routes."*

Now switch to the Prefect UI to inspect *this specific* run. Open <http://localhost:4200/runs>, find `quarantine_bgp | srl1:10.1.2.2` in the recent list (sort by start time if needed), and click into it:

![Prefect flow run for the cascade-driven quarantine_bgp on srl1:10.1.2.2](../../../docs/assets/screenshots/prefect-flow-run-cascade-peer-light.png#only-light){ .screenshot loading=lazy }
![Prefect flow run for the cascade-driven quarantine_bgp on srl1:10.1.2.2](../../../docs/assets/screenshots/prefect-flow-run-cascade-peer-dark.png#only-dark){ .screenshot loading=lazy }

- The full six-task graph for the `proceed` path: `collect_evidence → evaluate_policy → annotate_decision → ai_rca → quarantine → annotate_action`.
- Per-task logs for *this* run: `collect_evidence` shows the SoT lookup + metrics snapshot the flow pulled — the same shape you just saw at the CLI. `evaluate_policy` shows the two-stage decision. `quarantine` shows the `silence_id` Alertmanager returned.
- Task tags on the task nodes: `device:srl1`, `peer_address:10.1.2.2`, `afi_safi:ipv4-unicast`, `action:quarantine`. Tags live on tasks (not the parent flow run), so the natural way to find a specific flow run in the list is by name (`quarantine_bgp | srl1:10.1.2.2`) rather than by tag filter. Step 2's UI tour used the synthetic `try-it` runs; this is the same view on *your* live event.

#### D. Recovery beat

When the interface cycles back to up, every gated metric snaps to its established-state value: `bgp_oper_state=1`, prefix counters back to `10`. Alerts resolve on the next scrape — dashboards go green within seconds of the interface returning. That's the cascade's restore signal landing, mirrored on every panel that queries the affected series.

??? tip "Trigger the same flow without an alert"

    The webhook is one event source. The Prefect deployment is the universal handle — you can run it from the UI's **Run** button or directly from the CLI:

    ```bash
    docker compose --project-name autocon5 exec prefect-flows \
      prefect deployment run alert-receiver/alert-receiver \
      --param alertname=BgpSessionNotUp \
      --param status=firing \
      --param 'alert_group={"alerts":[{"labels":{"device":"srl1","peer_address":"10.1.99.2","afi_safi_name":"ipv4-unicast"}}],"groupLabels":{"alertname":"BgpSessionNotUp"},"status":"firing"}'
    ```

    Same flow, same decision, no alert. Useful when you're iterating on the policy and don't want to wait for Alertmanager — or as a fallback when a leftover silence is damping the cascade-driven payload.

??? tip "Flap without the BGP cascade"

    Pass `--no-cascade` and you'll trip `PeerInterfaceFlapping` (UPDOWN log volume) without dragging BGP down — `BgpSessionNotUp` stays clean and the workflow never fires. Useful when you want to exercise the Loki alert path in isolation.

??? info "What does the flow actually look like in Python?"

    `quarantine_bgp_flow` in `automation/flows.py` is short enough to read end-to-end. The six task calls match the task graph above:

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

**Stop and notice.** From "press Enter on a CLI" to "alert fired, flow ran, action recorded, recovery snapped" is under 4 minutes end-to-end. The cascade matches the shape of a real outage — interface degrades, BGP follows, prefixes drop, recovery snaps everything back — so the path you just walked is the same one your on-call would face in production, just compressed in time.

### 4. Branch — same drill, maintenance flipped

> *"Same incident shape. But this time pretend the device is in a planned change window. Same alert, same evidence, completely different right answer."*

#### A. Set maintenance and see the source-of-truth flip

```bash
nobs autocon5 maintenance --device srl1 --state
```

```
╭──── WorkshopDevice updated ────╮
│ srl1.maintenance: False → True │
╰────────────────────────────────╯
   The next alert for this device will be SKIPPED by the policy.
```

The CLI flipped `srl1.maintenance=true` in Infrahub and dropped a `Configured from CLI: srl1.maintenance = True` line into Loki. Confirm both:

```logql
{source="workshop-trigger"} |~ "maintenance"
```

— the most recent line ends in `srl1.maintenance = True`.

Then open the Infrahub UI at <http://localhost:8000> and navigate to **Object Management → WorkshopDevice → srl1**. `maintenance` just flipped to `true`. The surrounding attributes (`intended_peer`, `expected_state`, `reason`, `asn`, `role`, `site_name`) are the schema fields the flow's policy reads when deciding `proceed` vs `skip`. From the device page, click any row in the **bgp_sessions** list — for example `10.1.99.2`:

![Infrahub WorkshopBgpSession detail for the broken peer 10.1.99.2](../../../docs/assets/screenshots/infrahub-bgp-session-broken.png#only-light){ .screenshot loading=lazy }
![Infrahub WorkshopBgpSession detail for the broken peer 10.1.99.2](../../../docs/assets/screenshots/infrahub-bgp-session-broken.png#only-dark){ .screenshot loading=lazy }

`Expected State = Established`, `Reason = ip-mismatch-demo`, `Remote As = 65102`, `Device → srl1`. This is the per-peer intent the flow's policy reads in stage 1 (alongside the device's `maintenance` flag) before it ever looks at metrics.

??? tip "See the exact query the flow runs"

    The Prefect flow asks Infrahub for intent via this GraphQL query (verbatim from `automation/workshop_sdk.py`). Paste it into the playground at <http://localhost:8000/graphql> and you'll see the same answer the policy got — the flow has no secret access, just this query.

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

#### B. Drive the same alert, get the opposite decision

Step 3's quarantine action silenced `BgpSessionNotUp(srl1 ↔ 10.1.99.2)` for 20 minutes, so re-flapping won't reach the webhook this run. Use the direct trigger instead — same flow, no Alertmanager:

```bash
docker compose --project-name autocon5 exec prefect-flows \
  prefect deployment run alert-receiver/alert-receiver \
  --param alertname=BgpSessionNotUp \
  --param status=firing \
  --param 'alert_group={"alerts":[{"labels":{"device":"srl1","peer_address":"10.1.99.2","afi_safi_name":"ipv4-unicast"}}],"groupLabels":{"alertname":"BgpSessionNotUp"},"status":"firing"}'
```

Wait ~10 seconds, then in Loki:

```logql
{source="prefect", workflow="autocon5_quarantine_bgp", device="srl1"} | json
```

The most recent annotation carries `decision=skip` with message *"device under maintenance"*. The flow consulted the source of truth, saw `maintenance=true`, and skipped before metrics even came into the picture.

**Stop and notice.** Same alert payload, same SoT schema, same metrics in the lab — completely different decision, because the operator's intent was different. This is what context-aware alerting actually means in production: the alert isn't the decision, it's the *trigger* to fetch context and decide.

#### C. Clear maintenance

```bash
nobs autocon5 maintenance --device srl1 --clear
```

`srl1.maintenance: True → False`. The next alert for this device will be evaluated normally.

??? info "Visual — the decision tree inside the flow"

    Steps 3 and 4 walked two branches of the same `evaluate_policy` task. Same alert payload feeds in, same evidence is collected — `DecisionPolicy` checks the SoT first, falls through to metrics only if the SoT doesn't already short-circuit the decision.

    ```text
                  BgpSessionNotUp payload
                            │
                            ▼
                  ┌──────────────────┐
                  │ collect_evidence │   ← same shape Step 3B's
                  │  • SoT (Infrahub)│     `nobs evidence` prints
                  │  • Metrics (Prom)│
                  │  • Logs (Loki)   │
                  └────────┬─────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │ evaluate_policy  │   two-stage DecisionPolicy
                  │ ────────────     │
                  │ stage 1: SoT     │
                  │ stage 2: + metrics│
                  └────────┬─────────┘
                           │
       ┌───────────────────┼───────────────────┬────────────────┐
       │ stage 1           │ stage 1           │ stage 2        │
       │ maintenance=true  │ intended=false    │ admin=1,oper=1 │
       ▼                   ▼                   ▼                ▼
     skip                skip                skip            proceed
     "device             "peer not          "matches         "SoT vs
      under               intended"          SoT intent"     metrics
      maint"                                                  mismatch"
       │                   │                   │                │
       │                   │                   │                ▼
       │                   │                   │         quarantine_task
       │                   │                   │         (silence 20m)
       │                   │                   │                │
       ▼                   ▼                   ▼                ▼
    annotate_decision  annotate_decision   annotate_decision annotate_action

    Step 4 ────────────┘                                       │
                                                Step 3 ────────┘
    ```

    The teaching beat: **same drill, same evidence, opposite decision** — the only thing that changed between Step 3 and Step 4 was a flag in Infrahub. Maintenance windows are a label the policy consults, not a separate alerting layer.

### 5. Your turn — find what the flow actually did

> Your senior gestures at the screen. *"You've watched the paths run. Now show me — without scrolling the dashboard — how many alert payloads the flow has handled in the last hour, broken down by decision. One LogQL line. The annotations carry everything you need."*

This is unguided. The flow writes its audit trail into Loki with `source="prefect"` and a few labels that distinguish each path (`workflow`, `decision`, `device`, `peer_address`, `ai_rca` — explore them).

Take a minute on it before you scroll. Two hints if you're stuck:

- `count_over_time({...}[1h])` turns a Loki query into a metric just like in Part 1 Exercise 10. A one-hour window catches anything you ran earlier in the part even if you paused for coffee between exercises.
- `sum by (label) (...)` collapses everything except the label you list. Pick the label that gives the most informative breakdown — try `workflow` first (one row, not very useful), then try `decision` (a small handful of rows, much more useful).

**You should land on a query that returns a small handful of rows** — something like:

```
| decision  | count |
| proceed   |   1-3 |
| skip      |   1-2 |
| resolved  |   1-2 |
| (empty)   |   1-3 |  ← AI RCA annotations, which carry an `ai_rca` label, not `decision`
| stop      |   0-1 |  ← only present if an alert beat Infrahub schema load (see "four paths" above)
```

The exact counts depend on how many paths you've driven by hand on top of `try-it`. The `stop` row may or may not be there — both states are valid. If you get a single row total, you've collapsed too aggressively. If you get dozens of rows, you've left a high-cardinality label unaggregated.

### 6. Turn on AI RCA — same evidence, different voice

> *"Would an LLM narrative have helped at 2am? Let's see one. We ship a demo provider that returns a canned, evidence-grounded narrative — no API key needed. If you have one, swap to `openai` or `anthropic` instead."*

By default the AI step runs but writes the disabled-fallback annotation you've been seeing since Step 1. Flip three lines in `.env` to enable the **demo** provider:

```bash
ENABLE_AI_RCA=true
AI_RCA_PROVIDER=demo            # or `openai` / `anthropic` if you have a key
# AI_RCA_MODEL, OPENAI_API_KEY, ANTHROPIC_API_KEY — only needed for the real providers
```

Container env is baked at create-time, so `docker compose restart` won't pick up the change — `prefect-flows` needs to be re-created:

```bash
nobs autocon5 up
```

Re-trigger any path. The easiest:

```bash
nobs autocon5 try-it --auto
```

Watch the **Recent events** feed on Workshop Home. For each path you'll now see two annotations side by side: the deterministic policy result, and the AI narrative explaining why the situation might exist. Isolate just the AI annotations in Loki:

```logql
{source="prefect", ai_rca="true"} | json
```

The demo narrative is templated from the evidence bundle (it pulls `expected_state`, `reason`, `oper_state`, recent log labels, etc.), so it reads like a junior writeup rather than canned filler. Swap `AI_RCA_PROVIDER` to `openai` or `anthropic` with a real key and you'll get a full LLM response instead — same evidence, different model.

**Stop and notice.** The LLM (or the demo) gets the same evidence bundle the deterministic policy got. It can't see the network, the runbooks, or last week's incident. Its output is annotated *next to* the policy result, not in place of it. The policy decided what action to take; the narrative wrote a paragraph about why. Two different jobs, both grounded in the same evidence.

??? info "Visual — how the evidence bundle feeds both consumers"

    ```text
                  collect_evidence
                        │
                        ▼
              ┌────────────────────┐
              │   EvidenceBundle   │
              │     SoT            │
              │     metrics        │
              │     logs           │
              └─────────┬──────────┘
                        │  same dict
            ┌───────────┴───────────┐
            │                       │
            ▼                       ▼
      evaluate_policy           ai_rca_task
      (deterministic)           (demo / openai / anthropic)
            │                       │
            ▼                       ▼
      annotate_decision         annotate (ai_rca="true")
      decision=proceed          ## Most likely cause
      reason="SoT vs            ## Immediate actions
       metrics mismatch"        ## What to verify next
    ```

    Neither path sees more than the other. The deterministic policy is the action-taker; the narrative is annotation, not autonomy.

### 7. Wire a Prefect automation on the quarantine action

> *"Same intent → match → action pattern as the alert pipeline, one layer up. The flow ran. Now you want something to happen *when* the flow ran — a notification, a follow-up workflow, a webhook to your incident tooling. Prefect's `Automations` are that hook."*

Open the Prefect UI's Automations page: <http://localhost:4200/automations>.

1. Click **New automation**.
2. **Trigger** → **Flow run state changed**. Pick the flow `quarantine-bgp-flow`. Target state: `Completed`.
3. **Action** → choose one:
    - **Run a deployment** (simplest, no setup) — chain to another flow. Pick the `alert-receiver` deployment and paste this into the parameters form (the UI pre-fills the schema from the deployment; you fill the values):
        ```json
        {
          "alertname": "automation-fired",
          "status": "firing",
          "alert_group": {"alerts": [{"labels": {"device": "srl1", "peer_address": "10.1.2.2", "afi_safi_name": "ipv4-unicast"}}], "groupLabels": {"alertname": "automation-fired"}, "status": "firing"}
        }
        ```
        This is the same payload shape Step 4B used as a direct trigger — the automation will kick `alert-receiver` with a synthesised alert each time `quarantine_bgp_flow` completes.
    - **Send a notification** — needs a notification block (Slack, Discord, Mattermost, PagerDuty, email, etc.) configured with credentials first. None ship pre-wired in the lab. Skip unless you have a target system you want to wire up live.
4. Save the automation.

Now re-trigger any path:

```bash
nobs autocon5 try-it --auto
```

Open <http://localhost:4200/runs> and sort by **Start Time** (newest first). Each `quarantine_bgp_flow` completion should fire the automation, which kicks off a new `alert-receiver` flow run — visible as a fresh `alert-receiver` row with a random run-name. Click into it and the `alert_receiver` task logs will show the synthesised payload being routed. The full chain is also tailable from the CLI:

```bash
nobs autocon5 logs prefect-flows
```

**Stop and notice.** You just composed two layers of "trigger → match → action":

- Layer 1 (the alert pipeline): Alertmanager fires `BgpSessionNotUp` → webhook → `quarantine_bgp_flow` → `decision=proceed` → silence.
- Layer 2 (the automation): `quarantine_bgp_flow` completed → automation matched → `alert-receiver` deployment ran.

Same shape, different transport. In production this is how an incident-response platform composes — each layer narrows the trigger and adds context for the next layer.

??? info "Visual — the two layers, side by side"

    ```text
       ALERT PIPELINE                       AUTOMATION LAYER
       ──────────────                       ────────────────

       Alertmanager                         Prefect Automation
       fires alert                          (configured in UI)
            │                                    │
            │  TRIGGER                           │  TRIGGER
            ▼                                    ▼
       Webhook receives                     Flow run state changed
       BgpSessionNotUp payload              (quarantine_bgp_flow
            │                                → Completed)
            │  MATCH                            │
            ▼                                   │  MATCH
       quarantine_bgp_flow                      ▼
       (DecisionPolicy)                     Automation criteria met
            │                                    │
            │  ACTION                            │  ACTION
            ▼                                    ▼
       silence + annotate                   Send notification
                                            or Run deployment
                                            or webhook out
    ```

    Layer 1 reacts to alerts. Layer 2 reacts to Layer 1's completions. Stackable indefinitely — each layer narrows the trigger and adds context for the next.

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
- **Swap the AI RCA provider.** If you have an OpenAI or Anthropic key, change `AI_RCA_PROVIDER` to `openai` or `anthropic` and re-run a path. Compare the real LLM narrative against the demo provider's templated one — what does the LLM add that the template can't?

## What you took away

> Your senior signs off as the lunch break lands. *"You're ready to take primary tomorrow. If something fires, walk the same arc — triage, diagnose, contain, fix, document. The advanced guide is yours when you've eaten; if you take it, you'll know what 02:14 looks like by the time you get to it."*

- Alerts are an explicit operational decision, not a notification. The deterministic flow turns each alert payload into a *categorised action* by enriching with source-of-truth.
- The same alert payload routes to four different decisions depending on context (`proceed`, `skip` for healthy, `skip` for maintenance, `resolved`). Without enrichment, every alert looks the same.
- The evidence bundle is the contract between the deterministic policy and the AI RCA — both consume it, neither sees more than the other.
- Maintenance windows aren't a separate alerting layer. They're a label the flow consults at decision time. One source of truth, one decision point.
- AI RCA is opt-in narrative around the same evidence. It's annotation, not autonomy. Human judgment still owns the "act / don't act" call.
- The four paths are the recipe: mismatch → proceed, healthy → skip, maintenance → skip, resolved → audit. Memorise them — they generalise to any alert your team writes.
