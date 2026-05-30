# Part 3 — Alerts, automation, AI-assisted ops

## What you'll do here

Late morning. The clock is creeping toward lunch. The flap-rate panel you built before the break is still pinned in a tab. You're both finishing coffee when a `BgpSessionNotUp` alert lands — a real one, on the lab. Your senior glances at the dashboard, then at you.

> *"Watch what happens automatically. The flow's going to handle this without us. Then I'll walk you through the four cases it covers, and you can drive each one yourself. By the end of the hour you'll know exactly what the automation can and can't do for you — and which calls still belong to a human."*

Drive each of the four alert paths by hand, watch the Prefect workflow decide what to do with each, then optionally turn on the AI RCA step and compare its narrative against the rule-based decision the workflow already made. (Rule-based here means the workflow uses a fixed set of if/else rules — same alert payload in, same decision out every time. We unpack what that means a little further down in "The four paths".) By the end you'll have seen all four decisions land in the audit log and know which calls still belong to a human.

## Setup check

Reset to known-good baseline first — this expires any silences a prior `try-it` run might have created and clears any maintenance flags from earlier exercises:

```bash
nobs autocon5 reset
```

Four alerts should be firing in the lab — two per category, one per device:

- **`BgpSessionNotUp` × 2** — the deliberately broken peers from this morning (`srl1 → 10.1.99.2`, `srl2 → 10.1.11.1`). All four start `firing` after the reset above (it cleared any silences left from earlier exercises). Once you walk Step 3, you'll see `BgpSessionNotUp` cycle `firing` ↔ `suppressed` as the webhook flow silences each for 20 minutes and the silence then expires.
- **`InterfaceAdminUpOperDown` × 2** — `ethernet-1/11` on each device is configured as `admin up` but its `oper` state is `down`. That's a permanent intent-vs-reality mismatch (intent says "should be up", reality says "isn't" — the framing we use throughout Part 3, defined in [The four paths](#the-four-paths) below), so the rule fires continuously and never ages out.

```bash
nobs autocon5 alerts
```

```
| Alertname                | Severity | Device / target  |      State | Age |
| BgpSessionNotUp          | warning  | srl1 → 10.1.99.2 |     firing | ... |
| BgpSessionNotUp          | warning  | srl2 → 10.1.11.1 |     firing | ... |
| InterfaceAdminUpOperDown | warning  | srl1             |     firing | ... |
| InterfaceAdminUpOperDown | warning  | srl2             |     firing | ... |
```

`InterfaceAdminUpOperDown` is steady-state — the underlying mismatch is permanent, so the rule will never age out. Step 3 (the incident drill below) revisits this row when you flap an interface alongside it. The only alert that should ever move between `firing` and `suppressed` here is `BgpSessionNotUp`: it's `firing` immediately after the rule trips, then `suppressed` once the webhook flow applies its 20-minute `quarantine` silence, then `firing` again when the silence expires.

If you see fewer than two `BgpSessionNotUp` rows, give the stack 60 seconds and try again — alert evaluation has a `for: 30s` clause (the underlying condition must hold true for 30 seconds straight before the alert is `firing`; until then it sits in `pending` state), and you might have caught it before promotion. If you ran Part 2 and see a `PeerInterfaceFlapping` row, that's residue from the flap cascade — it ages out within ~5 minutes of the last flap. None of these conditions block the four paths below.

> Tip: you'll bounce between query languages from Part 1 throughout this part — **PromQL** for metrics (`bgp_oper_state{device="srl1", ...}`) and **LogQL** for logs and audit annotations (`{source="prefect", ...}`). Both query the same Grafana Explore tab; you switch by changing the datasource picker at the top.

Open **Workshop Home** at <http://localhost:3000/d/workshop-home>. The **Currently firing alerts** table at the bottom should show those same four rows. Keep this dashboard open in a tab — you'll watch it react to your CLI commands throughout this part. (New to Grafana? The [Grafana section of the Tour](../../../docs/workshop/tour.md#grafana-dashboards-and-explore) walks the dashboards and Explore mode.)

## The four paths

> Reading material — skim once, then jump to the exercises below. The folds in this section are deep dives you can come back to when something feels unclear during the exercises.

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

??? info "What does intent actually look like in Infrahub?"

    The flow asks Infrahub two questions per alert payload — *is this peer expected to be up?* (`expected_state`) and *is the device in a maintenance window?* (`maintenance`). Both come from the same `WorkshopDevice` GraphQL query with its `bgp_sessions` relationship expanded.

    (If GraphQL is new: it's a query language where you ask for the exact fields you want — including fields on related objects — and the server returns nested JSON in the same shape. The `WorkshopDevice { … bgp_sessions { … } }` block below reads as *"give me a `WorkshopDevice`, and for each one also include its `bgp_sessions` with these per-session fields."* The Infrahub Sandbox links the schema, so you can autocomplete the field names without memorising them.)

    Two paths to run it yourself — both valid, both worth knowing:

    1. **Via the Infrahub UI** at <http://localhost:8000>. Login `admin` / `infrahub`. Navigate **Object Management → WorkshopDevice → srl1**. The `maintenance` boolean, `site_name`, `role` are on the detail panel; the BGP sessions list is below. Click any peer (e.g., `10.1.99.2`) to see its `expected_state` and `reason`.
    2. **Via the GraphQL Sandbox** at <http://localhost:8000/graphql>. Paste the query below and hit run. This is the same query the Prefect flow makes from `automation/workshop_sdk.py` — Step 4A's "See the exact query the flow runs" fold (in [#a-set-maintenance-and-see-the-source-of-truth-flip](#a-set-maintenance-and-see-the-source-of-truth-flip)) covers the verbatim version.

    ```graphql
    {
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

    What you get back (trimmed to the broken peer's `bgp_session` for readability):

    ```json
    {
      "data": {
        "WorkshopDevice": {
          "edges": [{
            "node": {
              "name": { "value": "srl1" },
              "maintenance": { "value": false },
              "site_name": { "value": "lab" },
              "role": { "value": "edge" },
              "bgp_sessions": {
                "edges": [{
                  "node": {
                    "peer_address": { "value": "10.1.99.2" },
                    "expected_state": { "value": "established" },
                    "remote_as": { "value": 65102 },
                    "reason": { "value": null }
                  }
                }]
              }
            }
          }]
        }
      }
    }
    ```

    Read it back to the concepts: `maintenance: false` means the policy proceeds to the metrics check (no short-circuit); `expected_state: "established"` for `10.1.99.2` means the SoT believes this peer should be up — so if metrics disagree, the policy returns `proceed`. That's Path 1 (mismatch → proceed) sitting in the data.

    For the deeper "what is Infrahub, why a source of truth" framing, see the Tour's [Infrahub section](../../../docs/workshop/tour.md#infrahub-source-of-truth).

??? info "What does reality actually look like in the metrics?"

    The flow asks Prometheus for the *current* per-peer BGP state — `bgp_admin_state`, `bgp_oper_state`, plus the prefix counters. These are the same metric names you queried in Part 1.

    Three paths, in order of friction (lowest to highest):

    1. **Via `nobs autocon5 evidence`** — the workshop's pre-built convenience command that consolidates SoT + metrics + recent logs into one CLI output. The `BGP metrics snapshot` panel is exactly what the flow's `collect_evidence` task pulls. Step 3.B's [evidence walkthrough](#b-investigate-pull-the-evidence-bundle) drives it directly.
    2. **Via Grafana Explore** at <http://localhost:3000>. Pick the Prometheus datasource and paste:
        ```promql
        bgp_admin_state{device="srl1", peer_address="10.1.99.2"}
        bgp_oper_state{device="srl1", peer_address="10.1.99.2"}
        bgp_received_routes{device="srl1", peer_address="10.1.99.2"}
        bgp_prefixes_accepted{device="srl1", peer_address="10.1.99.2"}
        ```
    3. **Via the Prometheus HTTP API directly**, for scripting:
        ```bash
        curl -sG 'http://localhost:9090/api/v1/query' \
          --data-urlencode 'query=bgp_oper_state{device="srl1",peer_address="10.1.99.2"}'
        ```

    What you'll see on the broken peer:

    ```
    bgp_admin_state       = 1   (enable)
    bgp_oper_state        = 5   (active — retrying)
    bgp_received_routes   = 0
    bgp_prefixes_accepted = 0
    ```

    Read it back to the concepts: `admin_state: 1` (enable) means the device intends this session up; `oper_state: 5` (active, not 1=established) means it isn't actually up; the prefix counters at zero confirm no routes are flowing. Combined with the SoT's `expected_state: established`, that's a clear intent-vs-reality mismatch — exactly what triggers the `proceed` path. The numeric-to-meaning decoding (`1=enable`, `5=active/retrying`) is what the `Decoded` column in `nobs autocon5 evidence`'s output shows; Step 3.B walks the full mapping table.

??? info "Why deterministic, and not an LLM in the loop?"

    The policy is `DecisionPolicy.evaluate` in [`workshops/autocon5/automation/workshop_sdk.py`](https://github.com/network-observability/workshops/blob/main/workshops/autocon5/automation/workshop_sdk.py) — a two-stage `if / elif` chain. Four reasons that's the right shape here:

    - **Predictable.** Same evidence in, same decision out. No model temperature, no roll of the dice at 02:14.
    - **Replayable.** Six months from now, you can rerun the same alert payload through the same policy version and see the same outcome — the audit trail is meaningful.
    - **Version-controlled.** The policy is code. Changes go through a PR like everything else; a reviewer can read what changed before it ships to production.
    - **Reviewable in incident review.** When the on-call asks "why did the flow silence this?", the answer is a function call you can step through, not a model output to argue about.

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

`try-it --auto` is the workshop's pre-built rehearsal command — it walks every path with synthetic payloads so you see the whole arc in 30 seconds before driving each path by hand.

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
- **Tags** on each task: `device:srl1`, `peer_address:10.1.99.2`, `afi_safi:ipv4-unicast` (BGP address-family identifier — IPv4-unicast is the bog-standard internet routing table), `action:quarantine`. These are how a future operator filters "all flows that touched this peer" without scrolling.

**Stop and notice.** The Loki annotations are the audit *record*; the Prefect UI is the audit *workshop*. Annotations are searchable but flat; the UI lets you drill into a specific task's logs without writing a LogQL query.

??? info "What does an audit annotation actually look like in Loki?"

    The flow's `annotate_decision` task writes one Loki log line per evaluation — these are the "audit annotations" you've heard about since the [four-paths section](#the-four-paths). Here's exactly what one looks like.

    In Grafana Explore on the Loki datasource, paste:

    ```logql
    {source="prefect", workflow="autocon5_quarantine_bgp", decision="proceed"} | json
    ```

    Click any line and Grafana shows the parsed JSON body in the right-hand panel. Two annotations side by side — `decision=proceed` (what `try-it` just walked) and `decision=stop` (the rare path where the device isn't in Infrahub at all):

    ```json
    // decision=proceed (the actionable mismatch path)
    {
      "timestamp": "2026-05-26T11:15:26.971Z",
      "severity": "info",
      "message": "SoT expects peer up, but metrics show mismatch",
      "labels": {
        "decision": "proceed",
        "device": "srl2",
        "peer_address": "10.1.11.1",
        "source": "prefect",
        "workflow": "autocon5_quarantine_bgp"
      },
      "fields": {}
    }

    // decision=stop (would only appear if Infrahub didn't have the device)
    {
      "timestamp": "2026-05-26T10:43:31.234Z",
      "severity": "info",
      "message": "device not found in Infrahub",
      "labels": {
        "decision": "stop",
        "device": "srl2",
        "peer_address": "10.1.11.1",
        "source": "prefect",
        "workflow": "autocon5_quarantine_bgp"
      },
      "fields": {}
    }
    ```

    Read it back to the concepts: every annotation has the same five-label envelope (`source`, `workflow`, `decision`, `device`, `peer_address`) plus a free-form `message`. That label set is what makes Step 5's `sum by (decision) (count_over_time(...))` work — collapsing on the label that distinguishes paths is the whole game. The `message` field carries human-readable reasoning ("SoT expects peer up, but metrics show mismatch" vs "device not found in Infrahub") — Loki indexes the labels, not the message, so queries filter on the former and read the latter.

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

Before the flow's decision lands, look at the same evidence the flow is about to see. `nobs autocon5 evidence` is the workshop's CLI shortcut that bundles up the SoT lookup + metric snapshot + recent logs in one go — exactly what the flow's `collect_evidence` task pulls.

```bash
nobs autocon5 evidence srl1 10.1.2.2
```

**Four sections print:**

1. **Source of truth (Infrahub)** — device + intent: `expected_state=established`, `maintenance=false`, no `reason` (this peer is supposed to be healthy).
2. **BGP metrics snapshot (Prometheus)** — `admin_state=1` (enable), `oper_state=2` (down — the cascade is dragging it), `received_routes=0`.
3. **Loki — last 20 relevant line(s)** — recent BGP traffic for this peer plus any prior Prefect annotations (the audit trail).
4. **Policy hint** — what the deterministic policy *would* decide given the bundle (`proceed` / `skip` / `resolved`) and why.

??? info "What does the evidence bundle actually print?"

    Running `nobs autocon5 evidence srl1 10.1.99.2` against the broken peer produces four panels. Here's what each one actually looks like in the terminal, with the connecting thread between them called out.

    ```text
    ╭───────────────────── Source of truth (Infrahub) ─────────────────────╮
    │ device          srl1   site=lab  role=edge                           │
    │ maintenance     false                                                │
    │ intended peer   yes                                                  │
    │ expected state  established                                          │
    │ reason          ip-mismatch-demo                                     │
    │ remote_as       65102                                                │
    ╰──────────────────────────────────────────────────────────────────────╯
            ↑ Same fields the Prefect flow's `collect_evidence` task reads via GraphQL.
              `maintenance=false` → stage 1 of the policy proceeds to the metrics check.
              `expected_state=established` → SoT says this peer should be up.

       BGP metrics snapshot (Prometheus)
    ┏━━━━━━━━━━━━━━━━━━━┳━━━━━━━┳━━━━━━━━━┓
    ┃ Metric            ┃ Value ┃ Decoded ┃
    ┡━━━━━━━━━━━━━━━━━━━╇━━━━━━━╇━━━━━━━━━┩
    │ admin_state       │     1 │ enable  │
    │ oper_state        │     5 │ active  │
    │ received_routes   │     0 │ —       │
    │ sent_routes       │    10 │ —       │
    │ active_routes     │    10 │ —       │
    │ suppressed_routes │     0 │ —       │
    └───────────────────┴───────┴─────────┘
            ↑ The `Decoded` column is the enum-to-text mapping — `oper_state=5`
              decodes to `active` (retrying, not yet established). admin=1, oper=5
              on a peer the SoT expects `established` is the intent-vs-reality mismatch.

    ╭─────────────── Loki — last 20 relevant line(s) ──────────────────────╮
    │ {"timestamp":"...","severity":"warn","message":"BGP neighbor         │
    │  10.1.99.2: connection refused — peer not reachable on configured    │
    │  subnet",...}                                                        │
    │ {"timestamp":"...","severity":"warn","message":"BGP neighbor         │
    │  10.1.99.2: configured remote-as 65102 but peer never responded;     │
    │  FSM stuck in active",...}                                           │
    │ {"timestamp":"...","severity":"info","message":"QUARANTINE applied   │
    │  (silence_id=...)",...}                                              │
    ╰──────────────────────────────────────────────────────────────────────╯
            ↑ Mixed log streams: device-emitted BGP errors (the "why") and prior
              Prefect annotations (the "what the flow did"). One bundle, multiple
              sources. ("FSM" in the sample is BGP's finite state machine — the
              progression Idle → Active → Connect → OpenSent → Established;
              "stuck in active" means the peer is retrying but never reaching
              Established.)

    ╭──────────────── Policy hint ────────────────╮
    │ decision: proceed                           │
    │ reason  : SoT expects peer up, but metrics  │
    │           show mismatch                     │
    ╰─────────────────────────────────────────────╯
            ↑ The deterministic policy's verdict on this exact bundle. The Prefect
              flow's `evaluate_policy` task computes the same answer and writes it
              to Loki as the `decision=proceed` annotation you saw in [Step 2's audit-annotation fold](#2-walk-all-four-paths-in-one-shot).
    ```

    Read it back to the concepts: all four panels share one peer's worth of context — what the SoT believes, what the metrics measure, what the recent logs say, what the policy concluded. The `Policy hint` is the same answer the Prefect flow lands at in production; the difference is `nobs autocon5 evidence` shows it to you on the CLI before the flow runs, so you can predict the decision before triggering an alert.

**Stop and notice.** This bundle is the input the flow's `collect_evidence` task pulls every time it runs. Same evidence, two downstream consumers — the deterministic policy decides mechanically, the AI RCA step (next exercise) writes a narrative. Neither sees more than what the other sees.

#### C. The flow has already decided — see what it did

While you were reading the evidence bundle, the cascade-driven `BgpSessionNotUp(srl1 ↔ 10.1.2.2)` payload was racing through the webhook and into `quarantine_bgp_flow`. Whether it landed depends on timing — the cascade flips the BGP session down for ~50s, and the alert needs the underlying condition to hold for 30 straight seconds (the `for: 30s` clause from Setup) before it promotes from `pending` to `firing`. Prometheus checks the condition once per scrape (every 15s in this lab), so on a lucky cadence the alert fires and the flow runs; on an unlucky one BGP recovers before three consecutive scrapes have logged it down.

Check **Recent events** on Workshop Home — if you see a fresh annotation for `peer_address=10.1.2.2` with `decision=proceed`, you caught the natural path. If not (the common case), use the direct trigger below — same flow, same decision, no waiting on scrape windows:

```bash
docker compose --project-name autocon5 exec prefect-flows \
  prefect deployment run alert-receiver/alert-receiver \
  --param alertname=BgpSessionNotUp \
  --param status=firing \
  --param 'alert_group={"alerts":[{"labels":{"device":"srl1","peer_address":"10.1.2.2","afi_safi_name":"ipv4-unicast"}}],"groupLabels":{"alertname":"BgpSessionNotUp"},"status":"firing"}'
```

??? info "What does the webhook payload actually look like?"

    The `alert_group` parameter the direct trigger feeds the deployment is the same JSON shape Alertmanager POSTs to the webhook in production — one envelope per alert group, with the alert(s) and a few group-level fields.

    ```jsonc
    {
      // every payload starts with these three top-level fields
      "alertname": "BgpSessionNotUp",
      "status": "firing",              // or "resolved"

      "alert_group": {
        // one entry per firing instance — usually 1 in this lab
        "alerts": [{
          "labels": {
            "device": "srl1",
            "peer_address": "10.1.2.2",
            "afi_safi_name": "ipv4-unicast"
          }
        }],

        // Alertmanager's grouping keys — what causes alerts to fan in
        "groupLabels": {"alertname": "BgpSessionNotUp"},

        "status": "firing"
      }
    }
    ```

    Two things to notice. First, the `labels` dict inside each `alert` carries the keys the flow correlates against the SoT — `device`, `peer_address` — exactly as you'd write them in PromQL or LogQL. Same shape, three consumers (alert rule expression, dashboard panel, webhook payload). Second, the `groupLabels` field is what Alertmanager uses to fan multiple firing instances into one webhook delivery — the lab keeps it simple (one alert per group), but the schema is built for the real world where one upstream root cause can fire 20 BGP alerts at once.

Recheck Recent events — `decision=proceed` for `peer_address=10.1.2.2` should be there now.

> Your senior taps the screen. *"That's the flow signalling 'this looks real, escalate it.' In production this is where a runbook fires, a ticket opens, an on-call gets paged. The flow doesn't pretend to fix the underlying problem — it categorises and routes."*

Now switch to the Prefect UI to inspect *this specific* run. Open <http://localhost:4200/runs>, find `quarantine_bgp | srl1:10.1.2.2` in the recent list (sort by start time if needed), and click into it:

![Prefect flow run for the cascade-driven quarantine_bgp on srl1:10.1.2.2](../../../docs/assets/screenshots/prefect-flow-run-cascade-peer-light.png#only-light){ .screenshot loading=lazy }
![Prefect flow run for the cascade-driven quarantine_bgp on srl1:10.1.2.2](../../../docs/assets/screenshots/prefect-flow-run-cascade-peer-dark.png#only-dark){ .screenshot loading=lazy }

- The full six-task graph for the `proceed` path: `collect_evidence → evaluate_policy → annotate_decision → ai_rca → quarantine → annotate_action`.
- Per-task logs for *this* run: `collect_evidence` shows the SoT lookup + metrics snapshot the flow pulled — the same shape you just saw at the CLI. `evaluate_policy` shows the two-stage decision. `quarantine` shows the `silence_id` (the unique handle Alertmanager assigns to a silence — you can use it later to expire the silence early; see the [Alertmanager section of the Tour](../../../docs/workshop/tour.md#alertmanager-the-alert-router-and-silence-store)) returned by Alertmanager.
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

??? info "What does the maintenance log line actually look like?"

    The same `nobs autocon5 maintenance` invocation that flipped `srl1.maintenance=true` in Infrahub also dropped an audit annotation into Loki — same envelope shape as the Prefect annotations, different `source` label.

    ```json
    {
      "timestamp": "2026-05-26T10:55:24.426Z",
      "severity": "info",
      "message": "Configured from CLI: srl1.maintenance = True",
      "labels": {
        "device": "srl1",
        "event": "config-push",
        "level": "info",
        "source": "workshop-trigger"
      },
      "fields": {}
    }
    ```

    Two labels are worth highlighting. `source="workshop-trigger"` distinguishes lines this CLI wrote from the `source="prefect"` lines the flow writes — both are audit annotations, both are queryable with the same LogQL grammar, but they describe different actors. `event="config-push"` is the action type — every change `nobs autocon5 maintenance` makes carries this label, so an operator can ask Loki "show me every config push in the last 24h" with `{source="workshop-trigger", event="config-push"}`. Same correlation pattern as the alert pipeline, just with the CLI as the actor instead of the flow.

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
| decision  | count                                                            |
| proceed   | a few                                                            |
| skip      | a few                                                            |
| resolved  | a few                                                            |
| (empty)   | several — grows with every `try-it` run (AI RCA annotations, which carry an `ai_rca` label, not `decision`) |
| stop      | 0 (would only appear if an alert beat Infrahub schema load — see "four paths" above) |
```

The exact counts depend on how many paths you've driven by hand on top of `try-it`. The `stop` row may or may not be there — both states are valid. If you get a single row total, you've collapsed too aggressively. If you get dozens of rows, you've left a high-cardinality label unaggregated.

### 6. Turn on AI RCA — same evidence, different voice

> *"Would an LLM narrative have helped at 2am? Let's see one. We ship a demo provider that returns a canned, evidence-grounded narrative — no API key needed. If you have one, swap to `openai` or `anthropic` instead."*

By default the AI step runs but writes the disabled-fallback annotation you've been seeing since Step 1. Flip two lines in `.env` to enable the **demo** provider (the third line below is a no-op reminder, only relevant if you're using a real provider):

```bash
ENABLE_AI_RCA=true
AI_RCA_PROVIDER=demo            # or `openai` / `anthropic` if you have a key
# AI_RCA_MODEL, OPENAI_API_KEY, ANTHROPIC_API_KEY — only needed for the real providers
```

Docker reads `.env` only when a container is first created, not on every restart — so a plain restart won't pick up your change. The `nobs autocon5 up` command below recreates `prefect-flows` so the new settings take effect:

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

??? info "What does the demo AI RCA annotation look like?"

    With `AI_RCA_PROVIDER=demo`, the workshop ships a templated narrative that fills three sections (Most likely cause / Immediate actions / What to verify next) from the same evidence bundle the deterministic policy reads. Here's what the demo emits for the broken peer:

    ```text
    AI RCA:
    (demo narrative — set AI_RCA_PROVIDER=openai|anthropic with an API key
    for a real model response.)

    ## Most likely cause
    SoT expects peer 10.1.99.2 on srl1 to be established, with intent reason 'ip-mismatch-demo',
    but oper_state=5 (active), admin_state=1 (enable), received_routes=0.

    ## Immediate actions
    - Inspect reachability and timers between srl1 and 10.1.99.2

    ## What to verify next
    - Tail Loki for device=srl1 around the alert window for BGP state transitions
    - Check whether the SoT reason 'ip-mismatch-demo' matches a known fault class
    - Compare received_routes=0 against expected_prefixes_received in the SoT
    ```

    This lands in Loki as one annotation with these labels:

    ```
    ai_rca=true
    device=srl1
    peer_address=10.1.99.2
    source=prefect
    workflow=autocon5_quarantine_bgp
    severity=info
    ```

    Read it back to the concepts: the narrative is grounded in the *same* `EvidenceBundle` the deterministic policy used — the SoT's `expected_state`, `intent reason`, the metric values, the prefix counter. The template doesn't invent facts; it stitches the evidence into prose. When you flip `AI_RCA_PROVIDER` to `openai` or `anthropic` later, the model gets that same evidence dict and writes its own three-section response — different voice, identical inputs. The `ai_rca="true"` label is what distinguishes these annotations from the deterministic `decision=...` annotations in the same Loki stream.

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

Open the Prefect UI's Automations page: <http://localhost:4200/automations>. (New to Prefect? The [Prefect section of the Tour](../../../docs/workshop/tour.md#prefect-workflows-deployments-runs) explains workflows, deployments, and runs.)

1. Click **New automation**.
2. **Trigger** → **Flow run state changed**. Pick the flow `quarantine-bgp-flow`. Target state: `Completed`.
3. **Action** → choose one:
    - **Run a deployment** (simplest, no setup) — chain to another flow. Pick the `alert-receiver` deployment. The UI generates a form with one input per parameter the deployment expects. Fill it from the snippet below:
        - **`alertname`**: `automation-fired`
        - **`status`**: `firing`
        - **`alert_group`**: paste this JSON object as-is (everything from `{` to `}`):
            ```json
            {"alerts": [{"labels": {"device": "srl1", "peer_address": "10.1.2.2", "afi_safi_name": "ipv4-unicast"}}], "groupLabels": {"alertname": "automation-fired"}, "status": "firing"}
            ```
        This is the same payload shape Step 4B used as a direct trigger — the automation will kick `alert-receiver` with a synthesised alert each time `quarantine_bgp_flow` completes.
    - **Send a notification** — needs a notification block (Slack, Discord, Mattermost, PagerDuty, email, etc.) configured with credentials first. None ship pre-wired in the lab. Skip unless you have a target system you want to wire up live.
4. Save the automation.

??? info "What does the automation look like once configured?"

    Behind the UI form, Prefect stores the automation as a structured record — trigger + actions — that the API can list, create, or delete. Once you've saved your automation, here's what it looks like.

    ```bash
    curl -s -X POST 'http://localhost:4200/api/automations/filter' \
      -H 'content-type: application/json' -d '{"limit": 10}' | jq '.[] | {name, enabled, trigger, actions}'
    ```

    ```json
    {
      "name": "chain-after-quarantine",
      "description": "Demo: fire alert-receiver when quarantine_bgp_flow completes",
      "enabled": true,
      "trigger": {
        "type": "event",
        "match": {"prefect.resource.id": "prefect.flow-run.*"},
        "match_related": {
          "prefect.resource.id": "prefect.flow.<quarantine_bgp_flow_id>",
          "prefect.resource.role": "flow"
        },
        "expect": ["prefect.flow-run.Completed"],
        "for_each": ["prefect.resource.id"],
        "posture": "Reactive",
        "threshold": 1
      },
      "actions": [{
        "type": "run-deployment",
        "deployment_id": "<alert-receiver-deployment-id>",
        "parameters": {
          "alertname": "automation-fired",
          "status": "firing"
        }
      }]
    }
    ```

    The `trigger` block is what the UI's "Trigger" panel writes — `match` and `match_related` together pin the trigger to a specific flow's run-completion events; `expect: ["prefect.flow-run.Completed"]` is the state filter the UI exposes as a dropdown; `posture: "Reactive"` means fire-on-event (as opposed to "Proactive" which fires on absence-of-event). The `actions` array is what the "Action" panel writes — `run-deployment` here, but the same array can hold notification or webhook actions. This whole record can be exported, edited, and POST'd back to the API — same shape as a Terraform resource for an automation, if your team works that way.

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
