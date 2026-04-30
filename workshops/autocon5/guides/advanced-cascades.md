# Advanced — sonda-native cascades

## What you'll do here

Drive a cascade where sonda — not the workshop CLI — owns the timing. You've already used `flap-interface` in Parts 1 and 3: that command times each phase imperatively in Python, sleeping between `/events` POSTs. `incident` is the other shape — a v2 scenario with `after:` clauses that link signals into a dependency graph, POSTed once to `/scenarios`, scheduled entirely server-side. Same lab, same labels, completely different control model. The exercises below make the contrast concrete.

This is a stretch primitive. The three core part-guides are the load-bearing arc. Reach for this one if you finished early or want to think about scenario design as code-as-config rather than ad-hoc CLI driving.

## Setup check

Confirm you're on a branch that has the command:

```bash
nobs autocon5 incident --help
```

You should see options for `--device`, `--primary-interface`, `--backup-interface`, `--kind`, `--duration`, and `--follow / --no-follow`. If `incident` isn't a recognised subcommand, you're on the wrong branch or haven't synced — pull and re-run.

Confirm the stack is up:

```bash
nobs autocon5 status
```

Sonda-server should report `ok`. Every exercise below talks to it on `http://localhost:8085`.

Open Grafana at <http://localhost:3000> and have **Explore** ready on the `prometheus` datasource — you'll be running queries against three new metric names that don't exist until the cascade registers.

## The exercises

### 1. Read the cascade body before you POST it

The CLI builds a v2 scenario in memory and POSTs it once. Before you fire it, look at the shape — three signals linked by `after:` clauses:

| Phase | Metric | Generator | Triggers when |
|-------|--------|-----------|---------------|
| 1 | `interface_oper_state` (on the primary interface) | `flap` (60s up / 30s down) | immediately at registration |
| 2 | `incident_backup_link_utilization` (on the backup interface) | `saturation` (20% → 85% over 2m) | Phase 1 value drops below 1 |
| 3 | `incident_latency_ms` (on the backup path) | `degradation` (5ms → 150ms over 3m) | Phase 2 value exceeds 70% |

All three signals carry `source="incident-cascade"` and `pipeline="direct"` plus the standard lab labels (`device`, `name`, `intf_role: peer`, `collection_type: gnmi`). The `source` label keeps these visually distinct from the lab's continuous emitters when you query.

**Stop and notice.** In `flap-interface`, the timing lives in Python — the CLI sleeps between events, deciding when each phase fires. Here, the timing lives in YAML. Phase 2 doesn't say "wait 60 seconds"; it says "wait until Phase 1 drops below 1". The CLI doesn't decide when Phase 2 fires — sonda does, by watching what Phase 1 emits. That's the whole difference between an imperative cascade and a declarative one. If you walked Part 1 Exercise 5 ([Telemetry and queries](part-1-telemetry-and-queries.md#5-trigger-something-and-watch-the-query-react)) and Part 3 Exercise 3 ([Alerts, automation, AI](part-3-alerts-automation-ai.md#3-drive-mismatch--quarantine-by-hand)), you watched `flap-interface` walk a cascade phase by phase, with the workshop CLI driving each step.

If you want to see the exact body the CLI builds, read the `_build_link_failover` function in `workshops/autocon5/src/autocon5_workshop/incident.py`. The three `scenarios:` entries are what you'll see go through `POST /scenarios`.

### 2. Run a short cascade and watch all three signals

```bash
nobs autocon5 incident --duration 90s
```

The CLI prints a table with three scenario IDs and exits — it doesn't block. Sonda is now running the cascade.

Open three Explore tabs (or one tab and toggle through three queries):

```promql
interface_oper_state{source="incident-cascade"}
```

```promql
incident_backup_link_utilization
```

```promql
incident_latency_ms
```

**Tip.** Every signal the cascade emits carries `source="incident-cascade"`. Use that label as a one-shot filter in any panel or Explore tab to scope a query to just the cascade output: `{source="incident-cascade"}` for Loki, `bgp_oper_state{source="incident-cascade"}` for Prometheus.

Switch each panel to **Time series**. Watch them in turn:

- Phase 1 starts immediately. The line flips between `1` (up) and `0` (down) on the 60s/30s rhythm.
- Phase 2 is empty for the first ~60 seconds, then ramps from 20 to 85 once Phase 1 drops below 1 for the first time.
- Phase 3 is empty even longer — only starts climbing once Phase 2 crosses 70%.

**Stop and notice the gaps.** Phase 2 has *no data* for the first ~60 seconds. Phase 3 has *no data* for the first 2-3 minutes. The cascade enforces causal order at the emission layer. Sonda doesn't emit Phase 2 samples until Phase 1's threshold is crossed, full stop. This is the dependency graph doing real work — the metric series literally don't exist in Prometheus until their predecessor fires.

### 3. Watch the runtime registry

While the cascade is running, in another terminal:

```bash
curl -s http://localhost:8085/scenarios | jq '.scenarios[] | select(.name == "interface_oper_state" or (.name | startswith("incident_"))) | {id, name, status}'
```

You should see three rows — one per signal — each with an `id` and a `status`. Pick one of those IDs and:

```bash
curl -s http://localhost:8085/scenarios/<id>/stats | jq
```

You'll get `total_events`, `current_rate`, `uptime_secs`, `state`. Those are the same fields a `--follow` poll would surface.

**Stop and notice.** `/scenarios` is sonda's runtime registry — it lists *every* running scenario, including the lab's continuous emitters (`srl_bgp_oper_state`, `ping_result_code`, and others). It's not a per-cascade view. The filter above narrows by metric name because the cascade doesn't tag entries with a cascade ID. In production you'd either keep the IDs sonda returned at POST time, or POST cascades with a discriminator label and filter on that.

### 4. `--follow` mode

Re-run with `--follow` and a short duration:

```bash
nobs autocon5 incident --duration 60s --follow
```

The terminal blocks and polls every 5 seconds. Each poll prints a status line per scenario. The CLI returns when every scenario reports `stopped` (sonda's terminal state for a scenario that has run its full duration).

**Stop and notice.** If you Ctrl-C out of `--follow`, the scenarios *keep running on sonda-server*. The CLI is a poll, not a lifecycle owner — it watches, it doesn't manage. The only way to actually stop a running scenario is `DELETE /scenarios/<id>`. This is intentional: the registration and the polling are independent calls, so a flaky terminal session can't accidentally tear down a cascade.

### 5. Clean up explicitly

Sonda doesn't auto-delete completed scenarios from the registry by default — and even if it did, you may want to stop a running cascade early. The recipe to DELETE just your cascade scenarios, leaving the lab's continuous ones alone:

```bash
for ID in $(curl -s http://localhost:8085/scenarios \
  | jq -r '.scenarios[] | select(.name | startswith("incident_") or . == "interface_oper_state") | .id'); do
  curl -s -X DELETE "http://localhost:8085/scenarios/$ID"
  echo "  deleted $ID"
done
```

**Stop and notice.** The filter has to enumerate the cascade's metric names because the registry doesn't tag entries with the cascade they came from. That's a real ergonomics finding — if you were building production scenario libraries on top of `/scenarios`, you'd either capture the IDs from the POST response and store them, or include a discriminator label (e.g. `cascade_id: "link-failover-2026-04-30T14:00"`) in `defaults.labels` and filter on that. The exercise prompt: what would you change in the workshop CLI to make cleanup a one-liner?

### 6. Predict the wall-clock duration

Now the gotcha. The cascade was registered with `--duration 90s`. Phase 1 starts immediately. Phase 2 starts when Phase 1 first drops below 1 — roughly t=60s on the 60-up/30-down rhythm. Phase 3 starts ~30s after Phase 2 reaches 70%, which itself takes some time to ramp from 20 to 85.

Question: if every entry inherits `--duration 90s`, when is the *whole cascade* done?

Walk through it:

- Phase 1 ends at t ≈ 90s.
- Phase 2 starts at t ≈ 60s and runs for 90s, so ends at t ≈ 150s.
- Phase 3 starts after Phase 2 crosses 70% — Phase 2 ramps from 20 to 85 over 2 minutes, so 70% (a value of ~59.5) lands roughly 40-50s into Phase 2's own ramp, i.e. wall-clock t ≈ 105-110s. Phase 3 runs for 90s from there, so ends at t ≈ 200s.

The cascade's wall-clock end isn't 90 seconds. It's roughly 3 to 3.5 minutes, even though every individual scenario was "90 seconds long".

**Stop and notice.** Scenario `duration` is per-scenario, measured from each scenario's own start time, not from the cascade's registration time. The end-to-end run time is the *longest path through the dependency graph*. With imperative cascades you decide when each phase starts, so the wall-clock duration is whatever your sleeps add up to. With declarative cascades the graph decides, and the duration semantics flow from that. Read a v2 scenario, find the longest causal chain, and you can predict the wall-clock duration before you ever hit the API.

## Stretch goals

- **Build your own cascade kind.** Copy `_build_link_failover` from `workshops/autocon5/src/autocon5_workshop/incident.py` into a scratch Python script. Change the metric names, swap `saturation` for `degradation`, change the `after:` thresholds. Save the body as `scenario.json` and POST it directly: `curl -X POST http://localhost:8085/scenarios -H 'Content-Type: application/json' -d @scenario.json`. Skip the workshop CLI entirely — talk straight to sonda. This is what writing a production scenario library looks like.
- **Run two cascades concurrently.** Register one for `srl1`, then immediately a second for `srl2`. Confirm via `/scenarios` that both run side by side and emit independently. Notice the two cascades don't share state — each has its own dependency graph evaluation.
- **Use `--follow` as a smoke test.** Wrap `nobs autocon5 incident --duration 60s --follow` in a shell script and check `$?` after it returns. The CLI exits zero when every scenario has reached a non-running state — that's a CI-grade "did the cascade finish?" gate. A non-zero exit means a poll error or the scenarios got stuck.
- **Propose a `--dry-run` flag.** The CLI today builds the cascade body and POSTs it in one shot. Sketch (don't implement) what `nobs autocon5 incident --dry-run` would do: print the v2 scenario JSON to stdout without hitting `/scenarios`. Bonus: how would you make the dumped body re-postable verbatim with `curl`? This is the same shape as `terraform plan` versus `terraform apply` — the dry-run is the part of the workflow most CLIs forget.

## What you took away

- Imperative cascades (`flap-interface`) put timing in CLI code with `time.sleep`. Declarative cascades (`incident`) put timing in the dependency graph and let sonda's compiler resolve order at registration time.
- `after:` clauses watch *emitted values*, not wall-clock offsets. That's the contract — Phase 2 fires when Phase 1's value crosses a threshold, regardless of how long that takes.
- `duration` is per-scenario and measured from each scenario's own start. Cascade wall-clock time is the longest path through the dependency graph, not the duration of any single entry.
- `/scenarios` is sonda's runtime registry, listing every active scenario. It's not a per-cascade view — production consumers should track their own IDs or POST with a discriminator label.
- `--follow` is a poll, not a lifecycle owner. Ctrl-C ends the watch; it doesn't end the cascade. `DELETE /scenarios/<id>` is the only way to actually stop one.
- Sonda-native cascades are the right model for production scenario libraries — versioned YAML, declarative dependencies, server-side scheduling. CLI-timed cascades are the right model for ad-hoc workshop interactivity, where you want one keystroke to fire one shape on demand. Pick the model that matches the use case.
