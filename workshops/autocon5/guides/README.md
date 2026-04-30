# Workshop hands-on guides

Three guides, one per workshop part. Each is roughly 30–45 minutes of laptop time, exercise-first. Read on the day, run the queries, drive the lab.

| Part | Guide | What you'll do |
|------|-------|----------------|
| 1 | [Telemetry and queries](part-1-telemetry-and-queries.md) | PromQL and LogQL against the running stack — discover the schema, find the broken peer, correlate metrics to logs |
| 2 | [Dashboards](part-2-dashboards.md) | Add a panel to `Workshop Lab 2026` that answers an operational question, and watch it react in real time |
| 3 | [Alerts, automation, AI](part-3-alerts-automation-ai.md) | Drive the four canonical alert paths (quarantine, healthy-skip, maintenance-skip, resolved) and see the workflow act |
| Advanced | [Investigation — end-to-end](advanced-cascades.md) | Get paged, triage with PromQL+LogQL, diagnose the cascade, build the dashboard for next time, contain with maintenance, fix, and write the runbook |

Before you start, run `nobs autocon5 status` from the repo root. Every row should say `ok`. If anything is yellow or red, ask the instructor — the guides assume the stack is healthy.

The lab keeps working between parts. You don't need to tear anything down. If you fall behind in one part, skim the "What you took away" bullets at the end and join the next part fresh.

The advanced guide is the workshop's capstone and is optional — it assumes Parts 1, 2, and 3 are already behind you, and integrates every skill from the day into a single end-to-end on-call investigation. Budget 60 to 90 minutes if you take it on. Pick it up if you finish the three core parts early, or follow along when the proctor demos it on stage.
