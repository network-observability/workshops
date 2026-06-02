# Part 3 — Alerts, automation, AI-assisted ops

## What you'll do here

Late morning. The clock is creeping toward lunch. The flap-rate panel you built before the break is still pinned in a tab. You're both finishing coffee when a `BgpSessionNotUp` alert lands — a real one, on the lab. Your senior glances at the dashboard, then at you.

> *"Watch what happens automatically. The flow's going to handle this without us. Then I'll walk you through the four cases it covers, and you can drive each one yourself. By the end of the hour you'll know exactly what the automation can and can't do for you — and which calls still belong to a human."*

Drive each of the four alert paths by hand, watch the Prefect workflow decide what to do with each, then optionally turn on the AI RCA step and compare its narrative against the rule-based decision the workflow already made. (Rule-based here means the workflow uses a fixed set of if/else rules — same alert payload in, same decision out every time. We unpack what that means a little further down in "The four paths".) By the end you'll have seen all four decisions land in the audit log and know which calls still belong to a human.

## Setup check

Reset to known-good baseline first — this expires any silences a prior `try-it` run might have created and clears any maintenance flags from earlier exercises:

```bash
nobs autocon5 reset
nobs autocon5 alerts
```

You should see four alerts firing — same shape you saw in Part 2:

```
| Alertname                | Severity | Device / target  |   State |  Age |
| BgpSessionNotUp          | warning  | srl1 → 10.1.99.2 |  firing |  ... |
| BgpSessionNotUp          | warning  | srl2 → 10.1.11.1 |  firing |  ... |
| InterfaceAdminUpOperDown | warning  | srl1             |  firing |  ... |
| InterfaceAdminUpOperDown | warning  | srl2             |  firing |  ... |
```

If you skipped Part 2 §[From panel to alert — walk the full lifecycle](../../../docs/workshop/part-2.md#from-panel-to-alert-walk-the-full-lifecycle), skim it now — the `nobs autocon5 alerts` CLI, the Alertmanager UI, the `ALERTS` metric, and what `firing ↔ suppressed` means are all explained there. Part 3 picks up where that leaves off.

The two `BgpSessionNotUp` rows are what this part is about. Once you walk Step 3, you'll see each cycle `firing` → `suppressed` (the workflow silences it for 20 minutes) → `firing` again (the silence expires). `InterfaceAdminUpOperDown` is steady-state noise that never moves; ignore it.

If you see fewer than two `BgpSessionNotUp` rows, give the stack 60 seconds and try again — the rule has a `for: 30s` clause, so you might have caught it before promotion. A `PeerInterfaceFlapping` row from Part 2's flap cascade ages out within ~5 minutes.

??? info "What's a workflow?"

    A **workflow** here is code that runs in response to an event. The event is an Alertmanager webhook delivery; the code is a Prefect *flow* — a sequence of named tasks that collect evidence, evaluate a policy, and either silence the alert or escalate it.

    The handoff at a glance:

    ```text
       alert fires
            │
            ▼
       Alertmanager  ── routes by label match
            │
            ▼
       webhook receiver  ── HTTP POST to Prefect
            │
            ▼
       quarantine_bgp_flow  ── the decision logic
    ```

    `quarantine_bgp_flow` is **deterministic**: same alert payload in, same decision out, every time. Replayable, reviewable in code review (the decision tree is `DecisionPolicy.evaluate` in [`workshops/autocon5/automation/workshop_sdk.py`](https://github.com/network-observability/workshops/blob/main/workshops/autocon5/automation/workshop_sdk.py)), and auditable through annotations it writes to Loki. The full decision tree is broken out in [The four paths](#the-four-paths) below.

> Tip: you'll bounce between query languages from Part 1 throughout this part — **PromQL** for metrics (`bgp_oper_state{device="srl1", ...}`) and **LogQL** for logs and audit annotations (`{source="prefect", ...}`). Both query the same Grafana Explore tab; you switch by changing the datasource picker at the top.

Open **Workshop Home** at <http://localhost:3000/d/workshop-home>. The **Currently firing alerts** table at the bottom should show those same four rows. Keep this dashboard open in a tab — you'll watch it react to your CLI commands throughout this part.

## The cycle — alert → evidence → policy → action

Two `BgpSessionNotUp` alerts are firing in your lab right now (you just saw them in the setup check above). In a traditional setup, each alert would sit in a queue waiting for a human to notice and react. In this lab, there's an **automated workflow** — a small Python program that watches for new alerts — and it runs the same four steps every time one lands:

1. **Alert** — the workflow notices a new alert. *You already saw this part in the setup check.*
2. **Evidence** — the workflow gathers facts about the peer the alert is about, from three different sources.
3. **Policy** — the workflow runs a decision rule on those facts: is this something to act on, or is it expected?
4. **Action** — depending on the decision, the workflow silences the alert, writes a record of why, and marks it on the dashboard.

![The Part 3 cycle — alert, evidence, policy, action](../../../docs/assets/diagrams/part-3-cycle-light.svg#only-light){ .screenshot loading=lazy }
![The Part 3 cycle — alert, evidence, policy, action](../../../docs/assets/diagrams/part-3-cycle-dark.svg#only-dark){ .screenshot loading=lazy }

The rest of Part 3 walks each step in turn — you'll run a CLI command to see the workflow's view of the evidence (Phase 2), read what it decided in Loki (Phase 3), look at the silence it created in Alertmanager and the record it wrote (Phase 4). At the end you'll flip a single flag in the source of truth and watch the *same* alert go through the *same* four steps but land at a *completely different* decision (Phase 5).

The bigger point — and the reason this matters even outside this lab — is that **alerts on their own aren't useful**. The loop that wraps each alert (gather context, decide, act, leave a record) is what turns a notification into an operational decision. Once you know the four steps, every alert your team writes follows the same pattern.

??? info "Deep dive — the four decision paths in full"

    Reading material — skim once, then jump to the exercises below. The nested folds are deeper dives you can come back to when something feels unclear during the exercises.

    Every `BgpSessionNotUp` payload that lands on the webhook gets fed through the same **decision tree**: a deterministic Python function that pulls **intent** (from Infrahub) and **reality** (from Prometheus metrics) for the affected peer, compares them, and returns one of a fixed set of outcomes. "Deterministic" here means the same inputs always produce the same decision — no probabilistic step, no LLM judgment in the path. You can replay any historical alert and get bit-identical reasoning, which is what makes the flow reviewable in code review and replayable in a post-mortem. The AI RCA step you'll turn on in Phase 6 sits *alongside* this decision, not inside it.

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

    Every decision the flow makes lands in Loki as an **audit annotation** — one log line per evaluation, written by the `annotate_decision` task right after `evaluate_policy` returns. The annotation carries the device, the peer, and a `decision` label, which is what lets you ask Loki "how many alerts has the flow decided `proceed` on in the last hour?" without scrolling. Phase 7 is the unguided exercise where you answer that question yourself.

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

        1. **Via the Infrahub UI** at <http://localhost:8000>. Login `admin` / `infrahub`. Click **Network Device** in the left nav, then click **srl1** in the list. The `maintenance` boolean, `site_name`, `role` show in the detail panel; the BGP sessions are on the **Bgp Sessions** tab. Click any peer (e.g., `10.1.99.2`) to see its `expected_state` and `reason`. (Infrahub's UI label for the schema is "Network Device" — the underlying GraphQL type is still `WorkshopDevice`, which is what the query below uses.)
        2. **Via the GraphQL Sandbox** at <http://localhost:8000/graphql>. Paste the query below and hit run. This is the same query the Prefect flow makes from `automation/workshop_sdk.py` — Phase 5's "See the exact query the flow runs" fold covers the verbatim version.

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

        1. **Via `nobs autocon5 evidence`** — the workshop's pre-built convenience command that consolidates SoT + metrics + recent logs into one CLI output. The `BGP metrics snapshot` panel is exactly what the flow's `collect_evidence` task pulls. Phase 2's evidence walkthrough drives it directly.
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

        Read it back to the concepts: `admin_state: 1` (enable) means the device intends this session up; `oper_state: 5` (active, not 1=established) means it isn't actually up; the prefix counters at zero confirm no routes are flowing. Combined with the SoT's `expected_state: established`, that's a clear intent-vs-reality mismatch — exactly what triggers the `proceed` path.

    ??? info "Why deterministic, and not an LLM in the loop?"

        The policy is `DecisionPolicy.evaluate` in [`workshops/autocon5/automation/workshop_sdk.py`](https://github.com/network-observability/workshops/blob/main/workshops/autocon5/automation/workshop_sdk.py) — a two-stage `if / elif` chain. Four reasons that's the right shape here:

        - **Predictable.** Same evidence in, same decision out. No model temperature, no roll of the dice at 02:14.
        - **Replayable.** Six months from now, you can rerun the same alert payload through the same policy version and see the same outcome — the audit trail is meaningful.
        - **Version-controlled.** The policy is code. Changes go through a PR like everything else; a reviewer can read what changed before it ships to production.
        - **Reviewable in incident review.** When the on-call asks "why did the flow silence this?", the answer is a function call you can step through, not a model output to argue about.

    ??? info "What's a maintenance window — and how does it differ from a silence?"

        A **maintenance window** is intent expressed in the source of truth: `WorkshopDevice.maintenance = true` on a device in Infrahub. It says "we know this device is being worked on; alerts about it are expected and should be skipped." The policy reads this flag in stage 1 of the decision tree, *before* it ever looks at metrics, and short-circuits to `skip` if it's set.

        A **silence** is a per-alert mute applied in Alertmanager after a decision is already made. When the policy decides `proceed` on a real mismatch, the flow's `quarantine` task asks Alertmanager to silence the matching alert for 20 minutes so the same page doesn't fire repeatedly while the situation is being investigated.

        One is **upstream** of the decision (maintenance shapes which decision the policy returns); the other is **downstream** of it (a silence is one of the actions a `proceed` decision triggers). Conflating them is the most common confusion in this part of the workshop — Phase 5 walks the maintenance path explicitly to drive the distinction home.

## Walk the cycle

!!! note "Refactor in progress"

    Phases 1 and 2 below are the new flow. Phases 3–7 will replace the corresponding "old" steps under `## The exercises` further down in follow-up commits. For now, walk Phase 1 → Phase 2, then continue with the existing Step 2 ("Walk all four paths in one shot") and onwards.

### 1. Alert — see it fire

The workflow can't do anything until an alert exists. Start here: confirm the lab has alerts to work with.

```bash
nobs autocon5 alerts
```

You should see four rows. Two of them are `BgpSessionNotUp` — those are the alerts we'll follow through the rest of this part:

```
| Alertname                | Severity | Device / target  |   State |  Age |
| BgpSessionNotUp          | warning  | srl1 → 10.1.99.2 |  firing |  ... |
| BgpSessionNotUp          | warning  | srl2 → 10.1.11.1 |  firing |  ... |
| InterfaceAdminUpOperDown | warning  | srl1             |  firing |  ... |
| InterfaceAdminUpOperDown | warning  | srl2             |  firing |  ... |
```

Two things to notice:

- **The `device` and `peer_address` labels.** These two labels are how the workflow finds the right peer in the source of truth — same keys, same values, no translation.
- **The State column.** All four should read `firing`. If a row shows `suppressed` instead, the workflow already silenced it in a previous run — that's fine, Phase 4 explains what `suppressed` means here.

Prefer the browser? Open Alertmanager at <http://localhost:9093/#/alerts>. Same four rows, with click-to-expand details. (If you skipped Part 2 §"From panel to alert", the alert lifecycle — `pending → firing → suppressed → resolved` — is walked in detail there.)

For Part 3, we focus on what happens *after* the alert is `firing`: the workflow picks it up and decides what to do. That starts with gathering facts.

### 2. Evidence — what the workflow collected

Before the workflow decides anything, it gathers facts about the peer the alert is firing on. We call this the **evidence**: three pieces of information, plus a hint of what the decision will be.

You can see exactly what the workflow sees with one command:

```bash
nobs autocon5 evidence srl1 10.1.99.2
```

(`10.1.99.2` is the broken peer on `srl1` — same one in the firing list from Phase 1.)

The output is four panels. Each answers a different question:

| Panel | Source | Answers |
|---|---|---|
| **Source of truth (Infrahub)** | The intent database | "Is this peer **supposed** to be up?" |
| **BGP metrics snapshot (Prometheus)** | The metrics store | "Is this peer **actually** up?" |
| **Loki — last 20 relevant log lines** | The log store | "What happened recently on this peer?" |
| **Policy hint** | The workflow's decision rule | "What would the workflow decide right now?" |

??? info "What the four panels actually look like in the terminal"

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
              to Loki as the `decision=proceed` annotation you'll see in Phase 3.
    ```

    Read it back to the concepts: all four panels share one peer's worth of context — what the SoT believes, what the metrics measure, what the recent logs say, what the policy concluded. The `Policy hint` is the same answer the Prefect flow lands at in production; the difference is `nobs autocon5 evidence` shows it to you on the CLI before the flow runs, so you can predict the decision before triggering an alert.

The first two panels are the key pair:

- **Source of truth** says **what should be true** — for this peer, `expected_state=established` means "should be up and exchanging routes."
- **Metrics** say **what is true** — for this peer, `oper_state=5` means the BGP session is stuck trying to come up.

The gap between those two is the reason the alert is firing.

You can see the same source-of-truth data in the Infrahub browser UI. Open <http://localhost:8000> (login `admin` / `infrahub`), click **Network Device** in the left nav, click **srl1**, then click the **Bgp Sessions** tab. The row for `10.1.99.2` shows `Expected State: Established`, `Reason: ip-mismatch-demo`. Same data the workflow reads, just rendered for humans.

![Infrahub WorkshopBgpSession detail for the broken peer 10.1.99.2](../../../docs/assets/screenshots/infrahub-bgp-session-broken.png#only-light){ .screenshot loading=lazy }
![Infrahub WorkshopBgpSession detail for the broken peer 10.1.99.2](../../../docs/assets/screenshots/infrahub-bgp-session-broken.png#only-dark){ .screenshot loading=lazy }

> Why pull all this for one alert? Because the alert on its own doesn't say enough. `BgpSessionNotUp` only tells us "a BGP session is down" — but the right *action* depends on whether the session was supposed to be up, whether the device is in maintenance, and whether the session has already come back. Those answers live in three different systems. The workflow pulls all three in one go.

### 3. Policy — what was decided and why

Phase 2 showed you the *facts* the workflow gathered. Phase 3 looks at the **decision** the workflow made from those facts — and where to find a written record of it.

When the workflow finishes looking at a peer, it writes one line to the **log store (Loki)** describing what it decided. We call this an **audit record** — same shape as a normal log line, with extra labels saying which workflow ran, which peer it was for, and what it decided. The record survives long after the alert is gone, so you can ask Loki *"what did the workflow do an hour ago?"* or *"what did it decide on srl1 last week?"* and get an answer.

Open Grafana, switch to the **Loki** datasource in Explore, and paste:

```logql
{source="prefect", workflow="autocon5_quarantine_bgp", device="srl1"} | json
```

You should see one log line per decision the workflow has made on `srl1` recently. Click the most recent one — Grafana opens a side panel parsing the JSON. The fields that matter:

| Field | Value (for the broken peer) | What it means |
|---|---|---|
| `decision` (label) | `proceed` | The workflow decided to take action |
| `peer_address` (label) | `10.1.99.2` | Which peer this decision was about |
| `message` (field) | `SoT expects peer up, but metrics show mismatch` | Plain-English reason |
| `timestamp` | `2026-…` | When the workflow ran |

That `message` is the same answer the **Policy hint** panel showed you in Phase 2 — just now it's permanent. Anyone who comes back to this alert tomorrow can run the same query and read what the workflow decided and why.

??? info "What does an audit record actually look like in Loki?"

    The flow's `annotate_decision` task writes one Loki log line per evaluation — these are the "audit records" the prose above talks about. Two of them side by side — `decision=proceed` (the actionable mismatch path you're seeing now) and `decision=stop` (the rare path where the device isn't in Infrahub at all):

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

    Every record carries the same five-label envelope (`source`, `workflow`, `decision`, `device`, `peer_address`) plus a free-form `message`. That label set is what makes Phase 7's aggregation query (`sum by (decision) (count_over_time(...))`) work — collapsing on the label that distinguishes paths is the whole game. The `message` field carries human-readable reasoning ("SoT expects peer up, but metrics show mismatch" vs "device not found in Infrahub") — Loki indexes the labels, not the message, so queries filter on the former and read the latter.

#### The three decisions, explained

The workflow can write one of three decisions for any given alert:

| Decision | When it fires | What happens next |
|---|---|---|
| **`proceed`** | The source of truth says this peer **should** be up, but the metrics say it **isn't**. | Something is actually wrong. The workflow takes action (Phase 4). |
| **`skip`** | Either the device is in a maintenance window, or the peer is healthy according to the metrics. | No action needed. The workflow just records that it checked. |
| **`resolved`** | The alert has stopped firing on its own (the underlying problem went away). | No action needed. The workflow records that it resolved. |

Three different decisions, all written to the same audit trail, all queryable with the same LogQL line you just ran. Phase 5 walks the **maintenance → skip** path — flipping a single flag in the source of truth so the *same* broken peer ends up at `skip` instead of `proceed`. For now, what matters is that the workflow's decision is **visible** and **explained** — not buried in code, not guessed from behaviour.

> Why write the decision instead of just doing the action? Because in a real on-call rotation, the next person who looks at this peer needs to know *what was decided and why* — not just *what happened*. A silenced alert tells you "someone or something muted this" but doesn't tell you the reasoning. An audit record carries the reasoning forward, queryable, forever.

### 4. Action — what `proceed` actually does

Phase 3 showed you the workflow decided `proceed` on the broken peer. The word `proceed` only means something if you know what it triggers. Here's what **actually happens** in the lab when the workflow returns `proceed` — three concrete things, each in a different system.

#### A · The silence — containment in Alertmanager

The workflow asks Alertmanager to **silence** the alert for 20 minutes. Same kind of silence you created by hand in Part 2 §F — only this one was created automatically, scoped to the specific peer.

Open Alertmanager at <http://localhost:9093/#/alerts>. Find the row for `BgpSessionNotUp` on `srl1 → 10.1.99.2`. Its **State** column reads `suppressed` (not `firing`) — the workflow silenced it.

Click into the row. The `silenced_by` field carries a unique ID. Click that ID and you land on the **Silences** tab for that specific silence. Three things worth noticing:

- **Matchers** — `alertname=BgpSessionNotUp`, `device=srl1`, `peer_address=10.1.99.2`. The workflow built these from the alert's own labels — same labels you saw in Phase 1.
- **Comment** — `QUARANTINE: SoT expects peer up, but metrics show mismatch`. Same reason as the audit record from Phase 3.
- **Created by** — the workflow itself, not a human.

!!! tip "Don't see `suppressed`?"

    If the row shows `firing` instead, the silence may have expired — silences last 20 minutes, and the workflow re-silences each time the alert fires again. Wait 30 seconds for Alertmanager to push another delivery to the workflow, then refresh the page. The row should flip back to `suppressed`.

> Why silence and not fix? Silencing stops the *page* from firing again for 20 minutes — the same alert won't wake the on-call up twice for the same issue. The underlying problem is still active in the rule evaluator's state; the silence just mutes the notification path. Part 2 §E walks the silence-vs-fixing distinction in detail.

#### B · The audit record — memory in Loki

You already saw this in Phase 3 — the workflow wrote a `decision=proceed` log line to Loki with the reason. This is the **institutional memory**: it survives long after the silence expires, the alert resolves, and the next person on the rotation logs in. One log line per decision, every decision, forever.

#### C · The dashboard mark — visibility in Grafana

In Part 2 §D you added a Grafana annotation that draws a red shaded region on the **Flap rate (2 min)** panel whenever `PeerInterfaceFlapping` is firing. The **same pattern** works for any alert exposed in the `ALERTS` metric — change the alertname filter to `BgpSessionNotUp` and you get the same red region on a different panel marking exactly when this alert was firing.

If you'd like to see it for `BgpSessionNotUp` too, add a second annotation using the same Part 2 §D walk, with this query instead:

```promql
ALERTS{alertname="BgpSessionNotUp", alertstate="firing"}
```

This step is optional — the silence and the audit record are already enough to verify the workflow's action. The dashboard mark is the third *type* of action the diagram showed, and the pattern is worth knowing whether you add the second annotation now or later.

#### What `proceed` doesn't do

Worth saying out loud, so it doesn't trip you up:

- It does **not** fix the underlying problem on the device. The broken peer stays broken until a human (or a separate remediation flow) addresses it.
- It does **not** open a ticket or page the on-call directly. In production this is where you'd hook in PagerDuty, OpsGenie, Jira, Slack — in this lab, the silence + audit record + dashboard mark is the full chain.
- It does **not** decide *what to do next*. That's a human's job: read the audit record, look at the dashboard, walk the runbook.

What `proceed` *does* do is contain the noise (silence), explain what was seen (audit record), and make the moment visible (dashboard mark). Three observable outcomes from one decision — the loop closing for this alert.

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

Open Prefect at <http://localhost:4200/runs>. If a "Join the Prefect Community" pop-up appears, click **Skip** to dismiss it — it's a sign-up prompt, unrelated to the lab. Sort by **Start Time** (newest first) and you'll see four `quarantine_bgp | …` (or `resolved_bgp | …`) flow runs from the `try-it` you just ran. Click the most recent `quarantine_bgp` run. You'll see:

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

Then open the Infrahub UI at <http://localhost:8000> (login `admin` / `infrahub`) and click **Network Device** in the left nav, then **srl1** in the list. `maintenance` just flipped to `true`. The surrounding attributes (`intended_peer`, `expected_state`, `reason`, `asn`, `role`, `site_name`) are the schema fields the flow's policy reads when deciding `proceed` vs `skip`. Click the **Bgp Sessions** tab on the device detail and pick a row — for example `10.1.99.2`:

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

Wait ~10 seconds — the Prefect flow doesn't fire instantly. The trigger queues the flow, then Prefect's worker process (a background runner that watches the queue) picks it up and executes it. The whole loop is usually a few seconds. Then in Loki:

```logql
{source="prefect", workflow="autocon5_quarantine_bgp", device="srl1"} | json
```

The most recent annotation carries `decision=skip` with message *"device under maintenance"*. The flow consulted the source of truth, saw `maintenance=true`, and skipped before metrics even came into the picture.

!!! warning "Don't clear maintenance until you've seen the `skip` annotation"

    Step 4.C below clears the maintenance flag. If you race ahead and clear before the flow has actually executed, the flow will re-read `maintenance=False` and return `proceed` instead of `skip`. Confirm the Loki annotation has landed first — then continue.

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

Open the Prefect UI's Automations page: <http://localhost:4200/automations>. (New to Prefect? The [Prefect section of the Tour](../../../docs/workshop/tour.md#prefect-workflows-deployments-runs) explains workflows, deployments, and runs.) If a "Join the Prefect Community" pop-up appears, click **Skip** to dismiss it — it's a sign-up prompt, unrelated to the lab.

The Prefect 3.x Automations form is a three-step wizard: **01 Trigger → 02 Actions → 03 Details**. The exact template names and form layout may shift slightly between Prefect releases — what stays the same is the shape: "when X happens, do Y."

1. Click **Add Automation**.
2. **01 Trigger** — pick a **Trigger Template** from the dropdown. Look for one along the lines of "Flow run state changed". Configure it to fire when the flow `quarantine-bgp-flow` reaches state `Completed`, then click **Next**.
3. **02 Actions** — pick **Run a deployment** (simplest, no setup) and choose the `alert-receiver` deployment. The form generates one input per parameter the deployment expects. Fill it from the snippet below:
    - **`alertname`**: `automation-fired`
    - **`status`**: `firing`
    - **`alert_group`**: paste this JSON object as-is (everything from `{` to `}`):
        ```json
        {"alerts": [{"labels": {"device": "srl1", "peer_address": "10.1.2.2", "afi_safi_name": "ipv4-unicast"}}], "groupLabels": {"alertname": "automation-fired"}, "status": "firing"}
        ```
    This is the same alert format Step 4.B used as a direct trigger — the automation will trigger `alert-receiver` with a synthesised alert each time `quarantine_bgp_flow` completes. Click **Next**.
    *Other action options exist* — **Send a notification** for example — but those need a notification block (Prefect's term for a stored credential bundle for an external system: Slack, Discord, Mattermost, PagerDuty, email, etc.) configured first. None are pre-configured in this workshop. Skip unless you have a target system you want to wire up live.
4. **03 Details** — give the automation a name like `chain-after-quarantine` and click **Save**.

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

- **Tail the Prefect flow logs in real time.** Watch a flow run from the inside, line-by-line, so you can correlate every decision in the annotation trail with the task that produced it.

    ??? success "Solution — how to tail, plus what you'll see in the log stream"

        Run `nobs autocon5 logs prefect-flows` in one terminal, then re-run `try-it --auto` in another.

        Each `try-it --auto` cycle produces a burst of log lines, one per task as the flow runs through it. For a `proceed` path:

        ```text
        [collect] device=srl1 peer=10.1.99.2 afi=ipv4-unicast instance=default
        [collect] sot.found=True maintenance=False intended=True expected_state=established reason='ip-mismatch-demo'
           metrics={'admin_state': 1.0, 'oper_state': 5.0, 'received_routes': 0.0, ...}
           logs collected: 50 lines
        [policy] srl1:10.1.99.2
           stage1 SoT-only → ok (intended, not in maintenance)
           stage2 SoT + metrics → proceed (mismatch)
        [annotate] decision=proceed reason=SoT expects peer up, but metrics show mismatch
        [ai_rca] annotated: AI RCA disabled ...
        [quarantine] silencing srl1:10.1.99.2 for 20m
        [flow] action=quarantine silence_id=...
        ```

        The `[collect]` lines show the exact SoT + metric values the policy will see. The `[policy]` lines show which stage matched and why. The `[annotate]` line carries the same `decision` and `reason` you find in Loki under `{source="prefect"}`. Tailing the logs is the fastest debug loop when the flow returns an unexpected decision — every intermediate value is visible without a single LogQL query.

- **Compare evidence between a healthy peer and a broken one.** Both peers share the same SoT intent, but the policy fires `proceed` on one and `skip` on the other. Find the field that drives the difference.

    ??? success "Solution — commands to run and what differs between the two"

        Run both:

        ```bash
        nobs autocon5 evidence srl1 10.1.2.2   # a healthy peer
        nobs autocon5 evidence srl1 10.1.99.2  # a broken one
        ```

        Both peers share the same *intent* in the SoT (`expected_state: established`) — the SoT can't tell which one is broken on its own. What separates them is **reality**, in the metrics:

        | Row | Healthy `10.1.2.2` | Broken `10.1.99.2` |
        |---|---|---|
        | SoT `expected_state` | `established` | `established` ← same |
        | SoT `reason` | empty | `ip-mismatch-demo` |
        | Metric `admin_state` | `1 (enable)` | `1 (enable)` ← same |
        | Metric `oper_state` | `1 (established)` | `5 (active)` |
        | Metric `received_routes` | `10` | `0` |
        | Policy hint | `skip — peer matches SoT intent` | `proceed — SoT vs metrics mismatch` |

        The policy fires `proceed` when `expected_state=established` AND `oper_state ≠ 1`. Both peers have the same SoT intent — the *gap* between intent and reality is what the policy keys on.

- **Toggle maintenance on srl2 instead of srl1.** The maintenance-skip path isn't hard-coded to a specific device. Confirm it by flipping maintenance on srl2 instead and verifying the skip swapped devices.

    ??? success "Solution — commands + verify in Loki that the skip swapped device"

        Run, in order:

        ```bash
        nobs autocon5 maintenance --device srl2 --state
        nobs autocon5 try-it --auto
        ```

        Then in Grafana Explore on the Loki datasource:

        ```logql
        {source="prefect", workflow="autocon5_quarantine_bgp", decision="skip"} | json
        ```

        The most recent `skip` annotation should now show `device="srl2"` instead of `srl1`. The `message` is still `"device under maintenance"` — only which device was being evaluated changed.

        The point of the exercise: the policy is **device-agnostic**. It consults the SoT for whichever device the alert payload names. Flipping maintenance on any device routes that device's alerts to skip, automatically. The decision logic isn't hard-coded to a particular device.

        Don't forget `nobs autocon5 maintenance --device srl2 --clear` afterwards (or run `nobs autocon5 reset` — it clears both devices).

- **Watch a path's annotations in Loki directly.** Every Prefect decision lands as a structured JSON annotation in Loki. Tail them live to see the audit trail being written as you trigger paths.

    ??? success "Solution — LogQL query + the audit-trail shape"

        In Grafana Explore on the Loki datasource, paste:

        ```logql
        {source="prefect", workflow="autocon5_quarantine_bgp"} | json
        ```

        Each annotation has this shape (Grafana parses the JSON into a side panel when you click a row):

        ```json
        {
          "timestamp": "...",
          "severity": "info",
          "message": "SoT expects peer up, but metrics show mismatch",
          "labels": {
            "decision": "proceed",
            "device": "srl1",
            "peer_address": "10.1.99.2",
            "source": "prefect",
            "workflow": "autocon5_quarantine_bgp"
          }
        }
        ```

        Add `| decision="proceed"` (or `decision="skip"` / `decision="resolved"`) to filter to one path. Triggering a flap or running `try-it --auto` in another tab produces fresh annotations in real time — flip the time picker's **Live** mode on to watch them stream in.

        Step 5's unguided LogQL query (`sum by (decision) (count_over_time({source="prefect"}[1h]))`) rolls these annotations up by `decision` label — the same audit-trail data, just aggregated.

- **Swap the AI RCA provider.** Compare the templated demo provider's RCA narrative against a real LLM's. What does the LLM add that the template can't?

    ??? success "Solution — how to switch providers + guidance on the comparison"

        If you have an OpenAI or Anthropic key, set `AI_RCA_PROVIDER=openai` (or `anthropic`) in your environment (or the relevant `.env`), restart the Prefect flow worker, and re-run a path with `nobs autocon5 try-it --auto`.

        The demo provider produces a templated narrative — it stitches evidence-bundle fields into the same paragraph structure every time:

        ```text
        ## Most likely cause
        SoT expects peer 10.1.99.2 on srl1 to be established, with intent reason
        'ip-mismatch-demo', but oper_state=5 (active), admin_state=1 (enable),
        received_routes=0.
        ```

        A real LLM (OpenAI or Anthropic) typically adds:

        - **Domain inference** — translates the raw numbers into operational hypotheses ("`oper_state=5` with `received_routes=0` is consistent with a TCP-level reachability failure or AS-number mismatch — the FSM is trying but not authenticating").
        - **Wider context** — references the BGP state machine, common causes for "stuck in active", suggested next debug steps (traceroute, configured remote-as check).
        - **Calibrated uncertainty** — phrases like "most likely" or "consistent with" rather than confident pronouncements.

        The template can't do any of this — it can only fill slots. But the template is **deterministic** and **free**; the LLM is **inference-richer** but **non-deterministic** and costs per call. The trade-off is the lesson: the policy *decides what to act on*; the narrative — template or LLM — *explains why for a human reader*. Pick the right narrative tool for the audience and the budget.

## What you took away

> Your senior signs off as the lunch break lands. *"You're ready to take primary tomorrow. If something fires, walk the same arc — triage, diagnose, contain, fix, document. The advanced guide is yours when you've eaten; if you take it, you'll know what 02:14 looks like by the time you get to it."*

- Alerts are an explicit operational decision, not a notification. The deterministic flow turns each alert payload into a *categorised action* by enriching with source-of-truth.
- The same alert payload routes to four different decisions depending on context (`proceed`, `skip` for healthy, `skip` for maintenance, `resolved`). Without enrichment, every alert looks the same.
- The evidence bundle is the contract between the deterministic policy and the AI RCA — both consume it, neither sees more than the other.
- Maintenance windows aren't a separate alerting layer. They're a label the flow consults at decision time. One source of truth, one decision point.
- AI RCA is opt-in narrative around the same evidence. It's annotation, not autonomy. Human judgment still owns the "act / don't act" call.
- The four paths are the recipe: mismatch → proceed, healthy → skip, maintenance → skip, resolved → audit. Memorise them — they generalise to any alert your team writes.
