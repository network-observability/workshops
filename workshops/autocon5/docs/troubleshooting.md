# Troubleshooting (operator)

The recurring failure modes when running, extending, or handing off the workshop.
Each entry names the symptom, says **why** it happens, and gives the exact recovery command.
If you hit something not in here, add it — future-you will thank present-you.

## `nobs autocon5 up` succeeds but Grafana can't reach Infrahub

**Why.** First boot of `infrahub-server` runs migrations and seeds the admin token.
Takes ~60 seconds on a fresh laptop.
During that window Grafana's GraphQL datasource health-check will fail.

**Recovery.**
```bash
nobs autocon5 status            # repeat until every row says 'ok'
nobs autocon5 load-infrahub
```

`status` is idempotent — run it as many times as you want.

## `nobs autocon5 load-infrahub` says token mismatch

**Why.** `INFRAHUB_API_TOKEN` in `.env` is seeded into the running `infrahub-server` via `INFRAHUB_INITIAL_ADMIN_TOKEN` — and that env var is **only honoured on the first boot**.
If you changed the token in `.env` after first boot, `.env` and the live database are now out of sync.

**Recovery.**
```bash
nobs autocon5 destroy   # drops infrahub_db_data
nobs autocon5 up        # re-seeds with the .env token
nobs autocon5 load-infrahub
```

See [`env-lifecycle.md`](env-lifecycle.md#editing-env-after-first-boot) for the broader edit-after-boot rules.

## No metrics in Grafana

**Why.** Either sonda hasn't registered a scenario yet, or `telegraf-02` isn't scraping it.
The first ~30 seconds after `nobs autocon5 up` are normal — the scenarios register asynchronously.

**Recovery.**
1. Open http://localhost:9090/targets — `telegraf-02` should be `UP`.
2. Run `nobs autocon5 scenarios` — at least one scenario should be registered with `sonda-server`.
3. If `telegraf-02` is `DOWN`, tail it: `nobs autocon5 logs telegraf-02`.
4. If `sonda-server` has no scenarios, tail it: `nobs autocon5 logs sonda-server`.

## Alerts never fire

**Why.** The "broken peer" data only fires after the alert's `for:` window.
`BgpSessionNotUp` waits 30s; `PeerInterfaceFlapping` evaluates `count_over_time(...[2m]) > 3`, so it needs at least four log lines within a 2-minute window plus its own `for:` window on top.

**Recovery.** Be patient (give it 2-3 minutes after `nobs autocon5 up`), then:
```bash
nobs autocon5 alerts            # active alerts in Alertmanager
nobs autocon5 flap-interface --device srl1 --interface ethernet-1/1
```

The flap helper pushes a burst of UPDOWN log lines into `srl1`'s stream, which trips `PeerInterfaceFlapping` reliably within ~30 seconds.

## `flap-interface` or `maintenance` fails with `sonda /events post failed`

**Why.** Both commands route annotations through `sonda-server`'s `POST /events` endpoint.
A `502 Bad Gateway` from `/events` means sonda received the request but couldn't push to its configured Loki sink.
A connection error means sonda-server itself isn't reachable from where the CLI is running.

**Recovery.**
1. `nobs autocon5 status` — `Sonda server` should be `ok`. If not, check `nobs autocon5 logs sonda-server`.
2. Verify Loki is healthy too: the `/events` payload's `sink.url` defaults to `http://loki:3001` (sonda's container view). If Loki is restarting, give it 30s.
3. Probe `/events` directly: `curl http://localhost:8085/health` should return `{"status":"ok"}`.
4. If sonda-server has been restarted, its scenarios are in-memory only — re-kick `sonda-setup`:
   ```bash
   docker compose --project-name autocon5 restart sonda-setup
   ```

## Grafana shows a "What's new" splash on first load

**Why.** Grafana 13 ships a per-user "What's new" splash modal advertising
Grafana Assistant and other 13.x features. It's gated through Grafana's
internal user-storage API (`userstorage.grafana.app`), not through the
plugin system or the news feed — so disabling those doesn't suppress it.

**Recovery.** Press <kbd>Esc</kbd> once. Grafana records the dismissal
under the current user (admin or anonymous viewer), and you won't see it
again on that browser/session unless storage is cleared.

The workshop's docker-compose disables the *plugins* the splash promotes
(`grafana-assistant-app`, `grafana-pyroscope-app`, etc.) so they don't
clutter the nav even if the modal links to them.

## Annotation markers don't appear on the dashboard

**Why.** Loki-backed annotations (Interface Flap, Device Config Push) only render markers within the dashboard's current time range.
If you triggered `flap-interface` or `maintenance` just before navigating to the dashboard, you may be looking at a window that ends before the event timestamp.

**Recovery.**
- Refresh the dashboard (`R` keybind, or the refresh button).
- Zoom the time range out to `Last 15 minutes` (the new default).
- Verify the annotation source produced lines in Loki:
  ```bash
  curl -sG http://localhost:3001/loki/api/v1/query_range \
    --data-urlencode 'query={source="workshop-trigger"}' \
    --data-urlencode 'limit=5'
  ```

## Webhook errors trying to call Prefect

**Why.** The `prefect-flows` container registers and serves the `alert-receiver` deployment as soon as it boots.
On a slow laptop the webhook can start firing before the deployment is ready, causing "deployment not found" errors.

**Recovery.**
```bash
nobs autocon5 restart prefect-flows   # re-registers the deployment
```

This is faster than a full `nobs autocon5 restart` and doesn't disturb the rest of the stack.

## Stack feels slow / runs out of memory

**Why.** Infrahub alone runs a half-dozen containers (server, db, cache, mq, storage, ray-worker).
Add Prometheus + Loki + Grafana + Prefect + sonda + telegraf + vector + webhook and you're looking at ~25 containers and ~6 GB RSS at steady state.

**Recovery.** First check `docker stats` — usually one container is runaway (often Loki or Prefect).
If you're tight on RAM:
- Close Slack, Chrome tabs, etc. — the stack assumes ~8 GB free.
- `nobs autocon5 destroy` between sessions to drop volumes (saves several GB of disk too).

## I edited a config / scenario / dashboard and nothing changed

**Why.** Most volume mounts are read-only at container start.
Compose caches the build for services with a `Dockerfile` (webhook, prefect-flows, telegraf-02), and `nobs autocon5 up` defaults to `--no-build` — re-running `up` will reuse the cached image even if you've edited the Dockerfile or the code it copies in.
Grafana provisioning reloads on container restart, not on file change.

**Recovery.**
- Config or YAML change for an existing service: `nobs autocon5 restart`.
- Dockerfile or service-code change: `nobs autocon5 up --build <name>` (or `nobs autocon5 build <name>`).
- `.env` change picked up by an already-built service (e.g. `ENABLE_AI_RCA=true` for `prefect-flows`): `nobs autocon5 restart prefect-flows`.
- Grafana dashboard JSON: `docker compose restart grafana` (or `nobs autocon5 restart`).

## I want to capture an active session for handoff

This isn't a failure mode, but it comes up.
The maintainer's session log lives outside the repo (under `notes/`, gitignored).
If you want shareable artifacts for a handoff, lean on the operator docs in this folder — they're the canonical record of *how the pieces fit together*.
The session log is for in-progress thinking, not for the hand-off audience.
