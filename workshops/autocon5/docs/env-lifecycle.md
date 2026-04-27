# The `.env` lifecycle

The workshop uses a single `.env` file at `workshops/autocon5/.env` to hold
secrets and overrides. It looks small from the outside but it has **three
independent consumers**, each loading it slightly differently. This doc
walks through who creates it, who reads it, why the duplication exists,
and the one nuance that catches operators running the workshop CLI on
their host.

## TL;DR

```
.env.example  (committed template)
     │
     │  cp on first `task autocon5:up`  (handled by `.ensure-env`)
     ▼
   .env  (gitignored, edited by the operator)
     │
     ├─► docker compose          (auto-loaded; expands ${VAR} in compose.yml)
     ├─► scripts/load-infrahub.sh (sources `.env` into the shell, then `uv run`)
     └─► Taskfile direct-CLI tasks (inline `set -a; . ./.env; set +a`)
```

`.env` is gitignored. `.env.example` is the tracked template.

## Who creates it

The internal task **`.ensure-env`** in
[`Taskfile.yml`](../Taskfile.yml) (under the `tasks:` block) runs as a
`deps:` of `task autocon5:up`. On first invocation it copies
`.env.example` to `.env` if `.env` is missing:

```yaml
.ensure-env:
  internal: true
  cmds:
    - |
      if [ ! -f .env ]; then
        echo "Copying .env.example to .env (edit it if you want to override defaults)"
        cp .env.example .env
      fi
```

After that the operator owns `.env` — edits stick across `task up`,
`task down`, `task destroy`. The only way `.env` gets recreated is if
you delete it and run `task autocon5:up` again.

## What's in it

The committed `.env.example` defines:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GRAFANA_USER` | `admin` | Grafana admin login. |
| `GRAFANA_PASSWORD` | `admin` | Grafana admin password. |
| `INFRAHUB_ADDRESS` | `http://infrahub-server:8000` | Infrahub URL. The default is the **container DNS** name — see [the host vs container nuance](#the-host-vs-container-nuance) below. |
| `INFRAHUB_API_TOKEN` | `06438eb2-...` | Token seeded into Infrahub on first boot via `INFRAHUB_INITIAL_ADMIN_TOKEN`. Both Grafana's GraphQL datasource and the workshop CLI read this. |
| `ENABLE_AI_RCA` | `false` | Toggles the LLM RCA step in the Prefect quarantine flow. |
| `AI_RCA_PROVIDER` | `openai` | `openai` or `anthropic`. |
| `AI_RCA_MODEL` | `gpt-4o-mini` | The model id; e.g. `claude-haiku-4-5-20251001` for anthropic. |
| `OPENAI_API_KEY` | empty | Required when `AI_RCA_PROVIDER=openai` and `ENABLE_AI_RCA=true`. |
| `ANTHROPIC_API_KEY` | empty | Required when `AI_RCA_PROVIDER=anthropic` and `ENABLE_AI_RCA=true`. |

`.env.example` also ships commented `*_IMAGE` overrides (`SONDA_IMAGE`,
`PROMETHEUS_IMAGE`, `LOKI_IMAGE`, `GRAFANA_IMAGE`, `ALERTMANAGER_IMAGE`,
`LOGSTASH_LOKI_IMAGE`, `TELEGRAF_IMAGE`, `INFRAHUB_IMAGE`,
`INFRAHUB_RAY_VERSION`). Uncomment one to pin or upgrade an image without
editing `docker-compose.yml`.

## Three consumers, three loaders

Every consumer runs from `workshops/autocon5/`. The loading mechanism
differs because each consumer has a different default for "what counts
as the environment."

### 1. `docker compose` — automatic

Compose v2 auto-loads a file named `.env` from the directory it's invoked
in. It interpolates `${VAR}` references in `docker-compose.yml`:

```yaml
# excerpt from docker-compose.yml
grafana:
  image: ${GRAFANA_IMAGE:-docker.io/grafana/grafana:10.4.4}
  environment:
    GF_SECURITY_ADMIN_USER: ${GRAFANA_USER:-admin}
    GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
    INFRAHUB_API_TOKEN: ${INFRAHUB_API_TOKEN}
```

No explicit loading is needed — it's compose's built-in behaviour. The
Taskfile `cd`s into `workshops/autocon5/` (it's where `Taskfile.yml`
lives) before running `docker compose`, so the right `.env` is in scope.

This consumer is **mandatory**. Every container with `${VAR}` in
`docker-compose.yml` depends on it. Image pins, the Infrahub initial
token, the AI RCA toggle, and Grafana credentials all flow through this
path.

### 2. `scripts/load-infrahub.sh` — explicit

The schema/data loader sources `.env` into the bash environment, then
hands off to the Typer CLI:

```bash
# from scripts/load-infrahub.sh
if [ -f .env ]; then
  set -o allexport
  . ./.env
  set +o allexport
fi
# ... waits for Infrahub to be reachable ...
INFRAHUB_ADDRESS="$ADDRESS" \
INFRAHUB_API_TOKEN="$INFRAHUB_API_TOKEN" \
  uv run --project ../.. --package autocon5-workshop autocon5 load-infrahub
```

`autocon5 load-infrahub` reads the env via Typer `envvar=...` declarations
on its parameters. Without this explicit source step, the CLI starts with
an empty environment and exits with `INFRAHUB_API_TOKEN is required`.

### 3. The direct-CLI Taskfile tasks — inline

`status`, `alerts`, `evidence`, `set-maintenance`, and `try-it` invoke
the workshop CLI directly (no shell wrapper). They use a `LOAD_ENV` var
declared at the top of `Taskfile.yml`:

```yaml
vars:
  LOAD_ENV: 'set -a; [ -f .env ] && . ./.env; set +a'
```

Each task inlines it into its `cmds:`, e.g.:

```yaml
status:
  deps: [.ensure-uv]
  cmds:
    - |
      {{.LOAD_ENV}}
      cd ../.. && uv run --package autocon5-workshop autocon5 status
```

The pattern is identical to `load-infrahub.sh`'s — sourcing `.env` into
the shell so Typer can pick up the env vars. It's inlined because
**go-task disallows top-level `dotenv:` in included Taskfiles**; the
workshop's Taskfile is included from the umbrella `Taskfile.yml` at the
repo root, so a clean `dotenv:` directive isn't an option.

## Why three consumers, not one

It boils down to three constraints stacked on each other:

1. **Compose auto-load is non-negotiable.** Every container with
   `${VAR}` in `docker-compose.yml` depends on it. Removing it isn't
   an option.
2. **`uv run` doesn't read `.env` itself.** It runs the command in a
   pristine subprocess inheriting only the calling shell's environment.
   So the calling shell has to source `.env` first.
3. **The included Taskfile can't use `dotenv:`.** That would have been
   the cleanest single-source path for the CLI tasks, but go-task
   rejects `dotenv:` in included files. Hence the inline pattern.

The result is one `.env` file with three readers, all converging on the
same values.

## The host vs container nuance

`INFRAHUB_ADDRESS=http://infrahub-server:8000` is the **container DNS
name** of the Infrahub server inside the workshop's docker network.
That's the value Grafana and the Prefect alert-receiver flow need —
they run inside the network and resolve `infrahub-server` correctly.

The workshop CLI runs on the **host**. From there, `infrahub-server`
doesn't resolve at all. To keep `.env` correct for both audiences
without forcing the operator to swap values when running CLI commands,
three CLI entry points silently rewrite the address:

| File | Line | Behaviour |
|------|------|-----------|
| [`src/autocon5_cli/load.py`](../src/autocon5_cli/load.py) | 55 | If `infrahub-server` is in `INFRAHUB_ADDRESS`, rewrite to `http://localhost:8000`. |
| [`src/autocon5_cli/try_it.py`](../src/autocon5_cli/try_it.py) | 41 | Same rewrite. |
| [`packages/nobs/src/nobs/commands/maintenance.py`](../../../packages/nobs/src/nobs/commands/maintenance.py) | 41 | Same rewrite, plus prints `INFRAHUB_ADDRESS rewritten to host-reachable http://localhost:8000`. |
| [`packages/nobs/src/nobs/commands/schema.py`](../../../packages/nobs/src/nobs/commands/schema.py) | 30 | Same rewrite. |

The `note(...)` line in `maintenance.py` is what attendees see when
they run `task autocon5:set-maintenance` — that informational message
is intentional and confirms `.env` is being loaded correctly.

> **⚠️ Known limitation.** `nobs status` (called by `task autocon5:status`)
> reads `INFRAHUB_ADDRESS` from env but does **not** apply the
> `infrahub-server → localhost` rewrite. If you customise
> `INFRAHUB_ADDRESS` to something host-unreachable, `nobs status` will show
> Infrahub as unreachable even when it isn't. Cosmetic only — every other
> CLI path handles it correctly.

## Editing `.env` after first boot

Most edits are picked up cleanly:

- **Image overrides, AI RCA toggles, AI keys, Grafana password**: edit
  `.env`, then `task autocon5:restart` (or `task autocon5:restart-flows`
  for AI/Prefect-only changes).
- **`INFRAHUB_API_TOKEN`**: this one is special. Infrahub seeds the token
  via `INFRAHUB_INITIAL_ADMIN_TOKEN`, which is **only honoured on the
  first boot of `infrahub-server`**. Changing it after first boot
  desyncs the value in `.env` (used by Grafana + the CLI) from the
  value Infrahub actually accepts. Recover with:

  ```bash
  task autocon5:destroy   # drops infrahub_db_data so the token re-seeds
  task autocon5:up
  task autocon5:load-infrahub
  ```

Anything else (`GRAFANA_USER`, `INFRAHUB_ADDRESS`, etc.) follows the
restart pattern — no destroy needed.

## Where the pieces live

| File | Role |
|------|------|
| [`../.env.example`](../.env.example) | Tracked template. The seed for the operator's `.env`. |
| [`../Taskfile.yml`](../Taskfile.yml) | Defines `.ensure-env`, `LOAD_ENV`, and the tasks that consume `.env`. |
| [`../scripts/load-infrahub.sh`](../scripts/load-infrahub.sh) | The bash wrapper that sources `.env` for the data loader. |
| [`../docker-compose.yml`](../docker-compose.yml) | The third consumer; uses `${VAR}` interpolation throughout. |
