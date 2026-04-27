# Troubleshooting (operator)

The recurring failure modes when running, extending, or handing off the
workshop. Each entry names the symptom, says **why** it happens, and
gives the exact recovery command. If you hit something not in here,
add it — future-you will thank present-you.

## `task autocon5:up` succeeds but Grafana can't reach Infrahub

**Why.** First boot of `infrahub-server` runs migrations and seeds the
admin token. Takes ~60 seconds on a fresh laptop. During that window
Grafana's GraphQL datasource health-check will fail.

**Recovery.**
```bash
task autocon5:status            # repeat until every row says 'ok'
task autocon5:load-infrahub
```

`status` is idempotent — run it as many times as you want.

## `task autocon5:load-infrahub` says token mismatch

**Why.** `INFRAHUB_API_TOKEN` in `.env` is seeded into the running
`infrahub-server` via `INFRAHUB_INITIAL_ADMIN_TOKEN` — and that env var
is **only honoured on the first boot**. If you changed the token in
`.env` after first boot, `.env` and the live database are now out of
sync.

**Recovery.**
```bash
task autocon5:destroy   # drops infrahub_db_data
task autocon5:up        # re-seeds with the .env token
task autocon5:load-infrahub
```

See [`env-lifecycle.md`](env-lifecycle.md#editing-env-after-first-boot)
for the broader edit-after-boot rules.

## No metrics in Grafana

**Why.** Either sonda hasn't registered a scenario yet, or
`telegraf-02` isn't scraping it. The first ~30 seconds after `task up`
are normal — the scenarios register asynchronously.

**Recovery.**
1. Open http://localhost:9090/targets — `telegraf-02` should be `UP`.
2. Run `task autocon5:scenarios` — at least one scenario should be
   registered with `sonda-server`.
3. If `telegraf-02` is `DOWN`, tail it: `task autocon5:logs SVC=telegraf-02`.
4. If `sonda-server` has no scenarios, tail it: `task autocon5:logs SVC=sonda-server`.

## Alerts never fire

**Why.** The "broken peer" data only fires after the alert's `for:`
window. `BgpSessionNotUp` waits 30s; `PeerInterfaceFlapping` evaluates
`count_over_time(...[2m]) > 3`, so it needs at least four log lines
within a 2-minute window plus its own `for:` window on top.

**Recovery.** Be patient (give it 2-3 minutes after `task up`), then:
```bash
task autocon5:alerts            # active alerts in Alertmanager
task autocon5:flap-interface DEVICE=srl1 INTERFACE=ethernet-1/1
```

The flap helper pushes a burst of UPDOWN log lines into `srl1`'s
stream, which trips `PeerInterfaceFlapping` reliably within ~30 seconds.

## Webhook errors trying to call Prefect

**Why.** The `prefect-flows` container registers and serves the
`alert-receiver` deployment as soon as it boots. On a slow laptop the
webhook can start firing before the deployment is ready, causing
"deployment not found" errors.

**Recovery.**
```bash
task autocon5:restart-flows   # re-registers the deployment
```

This is faster than a full `task autocon5:restart` and doesn't disturb
the rest of the stack.

## Stack feels slow / runs out of memory

**Why.** Infrahub alone runs a half-dozen containers (server, db, cache,
mq, storage, ray-worker). Add Prometheus + Loki + Grafana + Prefect +
sonda + telegraf + logstash + webhook and you're looking at ~25
containers and ~6 GB RSS at steady state.

**Recovery.** First check `docker stats` — usually one container is
runaway (often Loki or Prefect). If you're tight on RAM:
- Close Slack, Chrome tabs, etc. — the stack assumes ~8 GB free.
- `task autocon5:destroy` between sessions to drop volumes (saves
  several GB of disk too).

## I edited a config / scenario / dashboard and nothing changed

**Why.** Most volume mounts are read-only at container start. Compose
caches the build for services with a `Dockerfile` (webhook, prefect-flows,
telegraf-02). And Grafana provisioning reloads on container restart, not
on file change.

**Recovery.**
- Config or YAML change for an existing service:
  `task autocon5:restart`.
- Dockerfile change: `task autocon5:build SVC=<name>`.
- Grafana dashboard JSON: `docker compose restart grafana` (or
  `task autocon5:restart`).

## I want to capture an active session for handoff

This isn't a failure mode, but it comes up. The maintainer's session
log lives outside the repo (under `notes/`, gitignored). If you want
shareable artifacts for a handoff, lean on the operator docs in this
folder — they're the canonical record of *how the pieces fit together*.
The session log is for in-progress thinking, not for the hand-off
audience.
