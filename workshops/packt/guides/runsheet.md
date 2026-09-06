# Runsheet — proctor-facing

Not for attendees. This is the minute-by-minute script for the two people running the session.

**Session**: Building a Network Observability Stack with Tools, Automation, and AI — Packt Publishing, online.
**When**: Saturday 19 September 2026, 09:00–12:00 EDT / 14:00–17:00 Europe/Dublin. Three hours, no hard stop mid-block.
**Speakers**: Christian Adell, David Flores.
**Recording**: Packt records the session. Attendee questions arrive through Packt's web app, not chat.

## Roles

Two roles, swapped at the break so both speakers drive and both monitor.

| Role | What they do |
|---|---|
| **Driver** | Shares screen, types every command, narrates. Owns the clock — if a block runs long, the driver cuts, not the monitor. |
| **Monitor** | Watches Packt's Q&A app the whole time. Does **not** interrupt mid-explanation. Reads questions out at block boundaries only, batched — "three people are asking X". Also watches for the room-is-red signal (see Fallback). |

Swap at 15:20 / 10:20 (the break). Whoever drove Parts 1 and 2 monitors Part 3.

## Before you start

Both machines, the evening before and again 30 minutes ahead:

```bash
nobs packt destroy          # clean slate
nobs packt up
nobs packt status           # every row ok
nobs packt load-infrahub
nobs packt preflight
```

The driver's stack is the one on screen. The monitor keeps a second stack up as a hot spare — if the driver's Grafana wedges mid-demo, swap screen share rather than debug live.

Have open on the driver's machine before 14:00: a terminal in `workshops/packt/`, Grafana (`localhost:3000`, already past both first-login modals), Prometheus (`localhost:9090`), Alertmanager (`localhost:9093`), Prefect (`localhost:4200`).

## The runsheet

| Dublin | EDT | Min | Block | Driver runs |
|---|---|---|---|---|
| 14:00 | 09:00 | 10 | **Stack check.** Welcome, what today is, everyone runs preflight. Take the room's temperature — this is where you learn whether to use the fallback. | `nobs packt preflight`<br>`nobs packt status` |
| 14:10 | 09:10 | 15 | **Framing.** Why observability, the two-device lab, the normalization idea, what the three parts are. No commands. | — |
| 14:25 | 09:25 | 25 | **Part 1 — metrics.** PromQL from scratch: normalization, discovery, `rate()`, intent-vs-reality, find the broken peer. | `nobs packt reset` at the top |
| 14:50 | 09:50 | 20 | **Part 1 — logs.** LogQL: stream selection, line filters, JSON parse, aggregation, the metric-to-log bridge. | — |
| 15:10 | 10:10 | 10 | **Part 1 — your turn.** Attendees work the two questions. Monitor collects answers from the Q&A app; driver reads out two before the break. | — |
| 15:20 | 10:20 | 10 | **Break.** Swap roles. Say the exact return time in both time zones. | — |
| 15:30 | 10:30 | 10 | **Part 2 — demo: panel build + flap.** Four steps: query, thresholds, drive a flap, switch device. Say up front that this block is watch-only. | `nobs packt flap-interface --device srl1 --interface ethernet-1/1`<br>then `--device srl2 --interface ethernet-1/10` |
| 15:40 | 10:40 | 10 | **Part 2 — demo: alert lifecycle.** The rule live, Alertmanager UI, `ALERTS` in Grafana, what a silence is, create one by hand and expire it. | Silence created in the Alertmanager UI |
| 15:50 | 10:50 | 15 | **Part 3 — setup + enable AI RCA + the cycle.** Everyone resets, sets `ENABLE_AI_RCA=true`, brings the flow container back. Then the alert → evidence → policy → action diagram. | `nobs packt reset`<br>edit `.env` → `ENABLE_AI_RCA=true`<br>`nobs packt up` |
| 16:05 | 11:05 | 35 | **Part 3 — walk steps 1–5.** Alert fires, evidence, policy, action, then the maintenance branch: same alert, opposite decision. This is the longest hands-on block — pace it. | `nobs packt cycle srl1 10.1.99.2 --trigger`<br>`nobs packt evidence srl1 10.1.99.2`<br>`nobs packt maintenance --device srl1 --state`<br>`nobs packt cycle srl1 10.1.99.2 --trigger`<br>`nobs packt maintenance --device srl1 --clear` |
| 16:40 | 11:40 | 15 | **Part 3 — your turn + reflection.** Step 6: aggregate the audit trail by decision. Then the reflection question — which path would you trust the AI narrative on? Take answers live. | — |
| 16:55 | 11:55 | 5 | **Wrap.** Take-home page, the recording, the book, where to ask afterwards. Thank the room. | — |

## Commands the driver must not get wrong

Three commands carry the demos. Rehearse these; everything else is recoverable.

**Part 2 flap** — drives the flap-rate panel and, ~90 seconds later, the `PeerInterfaceFlapping` alert:

```bash
nobs packt flap-interface --device srl1 --interface ethernet-1/1
```

**Part 3 incident trigger** — fires the alert into the webhook and runs the Prefect flow end to end:

```bash
nobs packt cycle srl1 10.1.99.2 --trigger
```

**Part 3 maintenance toggle** — the opposite-decision branch. Flip it, re-trigger, show `decision=skip`, then always clear it:

```bash
nobs packt maintenance --device srl1 --state
nobs packt cycle srl1 10.1.99.2 --trigger
nobs packt maintenance --device srl1 --clear
```

Alertmanager will not re-fire the *same* alert for 30 minutes (`repeat_interval`). `cycle --trigger` bypasses that by posting the payload directly — which is exactly why it is the demo command rather than waiting for a natural fire.

## Timing pressure — what to cut, in order

If you are behind at 16:05 / 11:05, cut in this order. Do not cut from the top of Part 3; cut from the bottom.

1. The Part 3 reflection discussion (16:40 block) — pose the question, do not take answers live, point at the take-home page.
2. Part 3 step 5, the maintenance branch. Narrate the idea from the diagram instead of running it.
3. Part 2's alert-lifecycle demo down to the Alertmanager UI only — skip the Grafana `ALERTS` overlay and the manual silence.

Never cut Part 1's "your turn" or Part 3 steps 1–4. Those are the session.

## Fallback — if the room is red

At 14:10 / 09:10, after the stack check, the monitor reports roughly what fraction of the room has a working stack.

**If more than 30% report red**, switch to demo-first for the whole session:

- The driver's stack is the only one that has to work. Say so explicitly — "follow along if yours is up, watch if it isn't, everything is written down and the recording is yours".
- Shrink both hands-on windows to **5 minutes** each (Part 1 your turn at 15:10, Part 3 your turn at 16:40). The 10 minutes you recover absorb the slippage the red stacks will cause anyway.
- Point at the pre-work email's preflight step in the Q&A app once, then stop troubleshooting individual machines on air. The monitor can answer specific errors in the Q&A app in parallel.

The failure mode to avoid is 40 minutes of live troubleshooting for six people while ninety wait. The lab is a means; the arc is the session.
