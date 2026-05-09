---
title: Network Observability Workshops
description: Hands-on workshops for Modern Network Observability — one continuous on-call investigation, the whole stack on your laptop.
hide:
  - navigation
---

# Network Observability Workshops

<p style="font-size: 1.15rem; line-height: 1.6;">
  <em>Hands-on workshops for <strong>Modern Network Observability</strong>. You arrive on a new on-call rotation. Over four hours you learn the lab's telemetry, build the dashboard your team needed yesterday, and watch the automation handle a real alert — with a senior engineer over your shoulder until lunch.</em>
</p>

By the time you close the laptop you'll have queried real-shape telemetry, made a Grafana panel answer an operational question, walked through how Alertmanager → Prefect routes a live alert, and decided which paths you'd trust an LLM-assisted RCA on at 02:14. The whole stack runs locally. No shared backend. No live network gear. :rocket:

[Quickstart :material-arrow-right:](quickstart.md){ .md-button .md-button--primary }
[Install Docker and uv :material-arrow-right:](install.md){ .md-button }
[Open the workshop :material-arrow-right:](workshop/index.md){ .md-button }

---

## What you'll do

<div class="grid cards" markdown>

-   :material-binoculars:{ .lg .middle } **Part 1 — Telemetry and queries**

    ---

    Morning of your first deep day on the rotation. Walk the lab's metrics and logs with your senior buddy. Find the broken peer. Bridge a metric anomaly to the log line that explains it.

    [:octicons-arrow-right-24: Open Part 1](workshop/part-1.md)

-   :material-view-dashboard-outline:{ .lg .middle } **Part 2 — Dashboards**

    ---

    Mid-morning. A post-mortem email lands — last night's page lost ten minutes because a flap-rate panel didn't exist. Build it now, with thresholds matching the alert rule, while the team is still in the room.

    [:octicons-arrow-right-24: Open Part 2](workshop/part-2.md)

-   :material-bell-ring-outline:{ .lg .middle } **Part 3 — Alerts, automation, AI**

    ---

    Late morning. A real alert lands and your senior narrates how the workflow handles it. Walk the four canonical paths, toggle the AI RCA step, and decide what you'd trust the LLM narrative on.

    [:octicons-arrow-right-24: Open Part 3](workshop/part-3.md)

-   :material-flashlight:{ .lg .middle } **Advanced — The 02:14 page**

    ---

    The optional capstone. Hours after the senior signs off, your phone rings. Triage with PromQL and LogQL, contain with maintenance, fix the root cause, write the runbook. End-to-end, alone on the rotation.

    [:octicons-arrow-right-24: Open the capstone](workshop/advanced.md)

</div>

---

## Why this workshop is different :sparkles:

<div class="grid cards" markdown>

-   :material-timeline-text:{ .lg .middle } **One continuous investigation**

    ---

    Not four disconnected exercises. The same broken peer, the same dashboard, the same alert — followed across the morning. The story carries the technique.

-   :material-network-outline:{ .lg .middle } **Real-shape telemetry**

    ---

    Synthetic telemetry that mirrors what real gNMI streams and syslog UPDOWN events look like, with Telegraf normalizing the inputs into the canonical schema you'd query in production.

-   :material-account-voice:{ .lg .middle } **Senior-engineer voice**

    ---

    The guides talk to you the way a good buddy on rotation would. Story beats up front, click-and-run when it's time to type, expected output for every command.

-   :material-laptop:{ .lg .middle } **Your laptop is enough**

    ---

    No shared backend. No real or containerized network devices. ~8 GB of RAM and Docker is all you need — `nobs autocon5 up` brings up the entire stack.

-   :material-check-decagram-outline:{ .lg .middle } **Concrete expected values**

    ---

    Every exercise tells you what to see when you run it. If your numbers disagree, that's a real signal, not "did I type it right?"

-   :material-weather-night:{ .lg .middle } **The 02:14 capstone**

    ---

    An optional final exercise: the page that lands when the senior is gone. End-to-end on-call investigation, designed for the attendee who wants to stress-test what they learned.

</div>

---

## Get the lab on your laptop

Three commands, after Docker and uv are installed:

```bash
git clone https://github.com/network-observability/workshops.git
cd workshops
uv run nobs autocon5 up
```

The first `up` pulls 3–5 GB of images. After that, restarts are seconds.

!!! tip "New to Docker or uv?"

    The [Install Docker and uv](install.md) page has per-platform pointers and a `nobs preflight` command that catches the common gotchas before the workshop starts. Run it the night before — image pulls are the slow step.

!!! info "What runs locally"

    Prometheus, Loki, Grafana, Alertmanager, Telegraf, Vector, Infrahub, Prefect, a FastAPI webhook receiver, and [`sonda`](https://github.com/davidban77/sonda) generating the synthetic telemetry. About 21 containers, ~5.5 GB of RAM while the stack is running, fully torn down by `nobs autocon5 destroy`.

??? question "What if I've never written PromQL or LogQL?"

    A sketch-level idea of "metrics database" and "log database" is enough. Part 1 builds both query languages from first principles against live data — your senior is walking you through it.

---

## Want the deeper lab? :books:

The companion repo [**`network-observability-lab`**](https://github.com/network-observability/network-observability-lab) is the book's full chapter-by-chapter playground — every collector, every variant, every scenario, with real cEOS / SR Linux containers in the loop. Larger surface area, more RAM, more network-engineering depth.

This workshops repo is the opposite trade-off: one CLI, one `docker compose`, one observability stack, one investigation arc. Pick it up if you want a tight four-hour on-ramp; pick the lab up if you want the full book experience.

---

[:material-rocket-launch: Start the quickstart](quickstart.md){ .md-button .md-button--primary }
[:material-book-open-variant: Read the workshop overview](workshop/index.md){ .md-button }
