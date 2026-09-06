# Workshop hands-on guides

The workshop is one continuous investigation. Over three hours you arrive on a new on-call rotation, learn the lab's baseline, watch the dashboard your team needed yesterday get built, and drive the automation as it handles a real alert.

| Part | Guide | Format | What you'll do |
|------|-------|--------|----------------|
| 1 | [Telemetry and queries](part-1-telemetry-and-queries.md) | ~55 min · hands-on | Your senior walks you through the lab's telemetry shape. Find the broken peer, learn the metric-to-log bridge, then answer two questions of your own |
| 2 | [Dashboards and Alerts](part-2-dashboards.md) | ~20 min · guided demo | A post-mortem email lands. We build the flap-rate panel on screen, then walk the same alert from panel to firing to silenced. Nothing here is required for Part 3 |
| 3 | [Alert response, Automation and AI](part-3-alerts-automation-ai.md) | ~65 min · hands-on | A real alert fires. Walk the cycle, flip one source-of-truth flag and reach the opposite decision, toggle AI RCA, and decide what you'd trust it on |
| — | [Take it home](take-home.md) | your own pace | Everything the three hours couldn't fit, in the order you'd do it: recording rules, alert rules, the full ten-step panel build, the real-LLM swap, and the end-to-end 02:14 capstone |

Before you start, run `nobs packt status` from the repo root. Every row should say `ok`. If anything is yellow or red, say so in the Q&A panel — the guides assume the stack is healthy.

The lab keeps working between parts. You don't need to tear anything down. If you fall behind in one part, skim the "What you took away" bullets at the end and join the next part fresh — Part 3 starts from a clean `nobs packt reset` and doesn't depend on anything you built earlier.
