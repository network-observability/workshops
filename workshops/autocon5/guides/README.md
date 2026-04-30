# Workshop hands-on guides

The workshop is one continuous investigation. Over four hours, you'll arrive on a new on-call rotation, learn the lab's baseline, build the dashboard your team needed yesterday, and walk through how the automation handles a real alert. A senior engineer is showing you around all morning and afternoon. By the end of the day, you'll be ready for the page that arrives at 02:14 — that's the optional advanced capstone.

| Part | Guide | What you'll do |
|------|-------|----------------|
| 1 | [Telemetry and queries](part-1-telemetry-and-queries.md) | Morning — your senior walks you through the lab's telemetry shape. Find the broken peer, learn the metric-to-log bridge, build a baseline mental model |
| 2 | [Dashboards](part-2-dashboards.md) | Mid-morning — a post-mortem email lands. Build the flap-rate panel the team needed yesterday, with thresholds matching the actual alert rule |
| 3 | [Alerts, automation, AI](part-3-alerts-automation-ai.md) | Afternoon — a real alert fires and your senior narrates how the automation handles it. Walk the four canonical paths, toggle AI RCA, sign off |
| Advanced | [Walking an incident cascade](advanced-cascades.md) | Get paged, triage with PromQL+LogQL, diagnose the cascade, build the dashboard for next time, contain with maintenance, fix, and write the runbook |

Before you start, run `nobs autocon5 status` from the repo root. Every row should say `ok`. If anything is yellow or red, ask the instructor — the guides assume the stack is healthy.

The lab keeps working between parts. You don't need to tear anything down. The story arc carries through — Parts 1 to 3 are one workday with a senior over your shoulder; the advanced guide is the page that lands hours later when you're alone on the rotation. If you fall behind in one part, skim the "What you took away" bullets at the end and join the next part fresh.

The advanced guide is the capstone. It assumes you've worked through Parts 1, 2, and 3 — pick it up if you finish the three core parts early, or follow along when the proctor demos it on stage.
