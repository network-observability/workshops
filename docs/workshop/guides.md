---
title: One workday, one investigation
---

<div class="autocon5-section-hero" markdown>

<span class="autocon5-section-hero__badge">The arc · Four parts · One investigation</span>

<h1 class="autocon5-section-hero__title">One workday, one investigation</h1>

<p class="autocon5-section-hero__subtitle">Not four disconnected exercises — the same broken peer, the same dashboard, the same alert, followed across the morning.</p>

You arrive on a new on-call rotation. Learn the lab's baseline. Build the dashboard your team needed yesterday. Walk through how the automation handles a real alert. A senior engineer is at your shoulder all morning. By the time the lunch break lands, you're ready for the page that arrives at 02:14 that night — the optional advanced capstone.

<p class="autocon5-section-hero__meta">
  <span>~4 hours total (with breaks)</span>
  <span>One continuous story, three parts</span>
  <span>Capstone is optional</span>
</p>

</div>

| Part | Guide | What you'll do |
|------|-------|----------------|
| 1 | [Telemetry and queries](part-1.md) | Morning — your senior walks you through the lab's telemetry shape. Find the broken peer, learn the metric-to-log bridge, build a baseline mental model |
| 2 | [Dashboards](part-2.md) | Mid-morning — a post-mortem email lands. Build the flap-rate panel the team needed yesterday, with thresholds matching the actual alert rule |
| 3 | [Alerts, automation, AI](part-3.md) | Late morning — a real alert fires and your senior narrates how the automation handles it. Walk the four canonical paths, toggle AI RCA, sign off before lunch |
| Advanced | [Investigation — end-to-end](advanced.md) | Get paged, triage with PromQL+LogQL, diagnose the cascade, build the dashboard for next time, contain with maintenance, fix, and write the runbook |

!!! tip "Before you start"

    Run `nobs autocon5 status` from the repo root. Every row should say `ok`. If anything is yellow or red, ask the instructor — the guides assume the stack is healthy.

The lab keeps working between parts. You don't need to tear anything down. The story arc carries through — Parts 1 to 3 are one workday with a senior over your shoulder; the advanced guide is the page that lands hours later when you're alone on the rotation. If you fall behind in one part, skim the **What you took away** bullets at the end and join the next part fresh.

The advanced guide is the workshop's capstone and is optional — it assumes Parts 1, 2, and 3 are already behind you, and integrates every skill from the day into a single end-to-end on-call investigation. Budget 60 to 90 minutes if you take it on. Pick it up if you finish the three core parts early, or follow along when the proctor demos it on stage.
