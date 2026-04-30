# Workshop hands-on guides

Three guides, one per workshop part. Each is roughly 30–45 minutes of laptop time, exercise-first. Read on the day, run the queries, drive the lab.

| Part | Guide | What you'll do |
|------|-------|----------------|
| 1 | [Telemetry and queries](part-1-telemetry-and-queries.md) | PromQL and LogQL against the running stack — discover the schema, find the broken peer, correlate metrics to logs |
| 2 | [Dashboards](part-2-dashboards.md) | Add a panel to `Workshop Lab 2026` that answers an operational question, and watch it react in real time |
| 3 | [Alerts, automation, AI](part-3-alerts-automation-ai.md) | Drive the four canonical alert paths (quarantine, healthy-skip, maintenance-skip, resolved) and see the workflow act |
| Advanced | [sonda-native cascades](advanced-cascades.md) | Drive a declarative cascade where sonda owns the timing — contrast with the imperative `flap-interface` model |

Before you start, run `nobs autocon5 status` from the repo root. Every row should say `ok`. If anything is yellow or red, ask the instructor — the guides assume the stack is healthy.

The lab keeps working between parts. You don't need to tear anything down. If you fall behind in one part, skim the "What you took away" bullets at the end and join the next part fresh.

The advanced guide is optional — pick it up if you finish the three core parts early, or follow along when the proctor demos it on stage.
