---
title: Building a Network Observability Stack with Tools, Automation, and AI
description: A 3-hour online Packt workshop — telemetry, queries, dashboards, alerts, automation and AI-assisted ops, running entirely on your own laptop.
hide:
  - navigation
---

<div class="packt-hero" markdown>

<span class="packt-hero__badge">Packt · 3-hour online workshop</span>

<h1 class="packt-hero__title">Building a Network Observability Stack with Tools, Automation, and AI</h1>

<p class="packt-hero__subtitle">The whole stack on your laptop, and one alert walked end to end.</p>

<p class="packt-hero__lead">
Three hours, one laptop, one on-call investigation. You'll write PromQL and LogQL against live telemetry and find the peer that's quietly broken. You'll watch a flap-rate dashboard get built with thresholds that match the alert rule. Then you'll drive an automated alert response yourself — alert, evidence, policy, action — flip one flag in the source of truth and watch the same alert reach the opposite decision, with an AI-written root-cause narrative stapled to the audit record. By the end you'll know which of those calls you'd hand to automation and which you'd keep.
</p>

[Start the pre-work :material-arrow-right:](prework.md){ .md-button .md-button--primary }
[Open Part 1 :material-arrow-right:](part-1.md){ .md-button }
[Register on Eventbrite :material-arrow-right:](https://www.eventbrite.co.uk/e/building-a-network-observability-stack-with-tools-automation-and-ai-tickets-1993849714168){ .md-button }

<p class="packt-hero__meta">
  <span>Sat 19 Sep 2026 · 09:00–12:00 EDT · 14:00–17:00 Dublin</span>
  <span>Christian Adell &amp; David Flores</span>
  <span>Everything runs locally — no shared backend, no live gear</span>
</p>

</div>

---

## What you'll do

<div class="grid cards" markdown>

-   :material-binoculars:{ .lg .middle } **Part 1 — Telemetry and queries**

    ---

    ~55 min · hands-on

    Morning of your first deep day on the rotation. Walk the lab's metrics and logs with your senior buddy, find the broken peer, and bridge a metric anomaly to the log line that explains it. Ends with ten minutes of your own queries.

    [:octicons-arrow-right-24: Open Part 1](part-1.md)

-   :material-view-dashboard-outline:{ .lg .middle } **Part 2 — Dashboards and alerts** · *guided demo*

    ---

    ~20 min · watch only

    A post-mortem email lands: last night's page lost ten minutes because a flap-rate panel didn't exist. We build it on screen, thresholds matching the real alert rule, then walk the alert from firing to silenced. **Nothing here is required for Part 3.**

    [:octicons-arrow-right-24: Open Part 2](part-2.md)

-   :material-bell-ring-outline:{ .lg .middle } **Part 3 — Alerts, automation and AI**

    ---

    ~65 min · hands-on

    A real alert lands. Walk the cycle — alert, evidence, policy, action — then flip one source-of-truth flag and watch the same alert reach the opposite decision. Toggle the AI RCA step and decide what you'd trust it on at 02:14.

    [:octicons-arrow-right-24: Open Part 3](part-3.md)

</div>

!!! tip "Two lanes — pick the one your laptop allows"

    **Hands-on.** Your laptop runs the stack and you type along. Better experience, and the [pre-work](prework.md) is what makes it work — do it a few days ahead, not on the morning.

    **Watching.** Locked-down machine, not enough RAM, no time to prepare? Come anyway. Every command and every expected output is written out in the guides, we drive the whole session on screen, and Packt records it. The [Take it home](take-home.md) page lets you do the hands-on parts later with more time than three hours allows.

    Part 2 is a guided demo for everybody, so a stack that's still pulling images by then costs you nothing.

---

## Questions people ask before signing up

??? question "Do I need network engineering experience?"

    Helpful, not required. Every concept the workshop leans on — BGP peering, interface state, syslog UPDOWN events — is framed before you query it. If you have run a network, you'll move faster; if you have run a platform, you'll recognise more of the tooling than you expect.

??? question "Do I need to know Prometheus, Loki, or Grafana already?"

    A sketch-level idea of "metrics database" and "log database" is enough. Part 1 builds PromQL and LogQL from first principles against live data — no prior query-language experience assumed.

??? question "What if I've never used Docker?"

    You need Docker installed and running, but you never write a Dockerfile. If `docker ps` works on your laptop, you're set. The [pre-work page](prework.md) has per-platform install pointers and a `nobs preflight` command that checks everything at once.

??? question "Why do I need `uv`?"

    [`uv`](https://docs.astral.sh/uv/) installs and runs the workshop's `nobs` CLI — the thin wrapper that fronts every command (`up`, `down`, `status`, `alerts`, `flap-interface`). One install line, and it brings its own Python, so you don't need a system Python at all.

??? question "I'm on Windows."

    Run everything inside **WSL 2**, with Docker Desktop on the WSL 2 backend. Not PowerShell, not Git Bash. If you have never set WSL up, do it a few days ahead rather than on the morning.

??? question "How big is the stack?"

    Around 21 containers, **~5.5 GB of RAM** while running, and **~5 GB of disk**. The first `nobs packt up` pulls 3–5 GB of images — that's the only genuinely slow step, and it's why the pre-work matters. After that, restarts are seconds. `nobs packt destroy` removes all of it.

??? question "Is anything sent to a remote service?"

    No, by default. All telemetry, alerts, dashboards and audit records are local. The AI RCA step defaults to a `demo` provider that writes its narrative from a local template — no network calls. It only reaches OpenAI or Anthropic if you put your own key in `.env`, which is entirely optional and not needed for any part of the session.

??? question "Is it recorded?"

    Yes — Packt records the session and distributes the replay through your Packt account.

??? question "Where do I ask questions?"

    During the session, through the Q&A panel in Packt's app — we read them out at block boundaries rather than mid-explanation, so keep them coming as you go. Afterwards, open an issue on [the workshops repo](https://github.com/network-observability/workshops/issues).

---

## After the three hours

The stack is still on your laptop and it costs nothing to leave it there. The [Take it home](take-home.md) page collects everything we couldn't fit — recording rules and alert rules, the full ten-step panel build, swapping the demo RCA provider for a real LLM, and the end-to-end 02:14 capstone where the page lands and you're alone on the rotation.

If you want the long-form version of all of it, [*Modern Network Observability*](https://network-observability.github.io/) is the book this workshop is drawn from, and [`network-observability-lab`](https://github.com/network-observability/network-observability-lab) is its chapter-by-chapter playground with real SR Linux and cEOS containers in the loop.
