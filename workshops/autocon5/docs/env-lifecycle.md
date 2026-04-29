# The `.env` lifecycle

The workshop uses a single `.env` file at `workshops/autocon5/.env` to hold secrets and overrides.
It looks small from the outside but it has **two independent consumers**, each loading it slightly differently.
This doc walks through who creates it, who reads it, why the duplication exists, and the one nuance (`infrahub-server` vs `localhost`) that used to bite operators on the host.

## TL;DR

```
.env.example  (committed template)
│
│  cp on first `nobs autocon5 up`  (handled by the workshop bootstrap hook)
▼
.env          (gitignored, edited by the operator)
│
├─► docker compose            (auto-loaded; expands ${VAR} in compose.yml)
└─► nobs CLI startup          (load_env() in nobs.lifecycle.env)
```

`.env` is gitignored.
`.env.example` is the tracked template.

## Who creates it

The autocon5 workshop registers a `bootstrap()` hook with `nobs` (see [`src/autocon5_workshop/__init__.py`](../src/autocon5_workshop/__init__.py)).
`nobs setup`, `nobs autocon5 setup`, and `nobs autocon5 up` all call it as a precondition.
On first invocation it copies `.env.example` to `.env` if `.env` is missing.

After that the operator owns `.env` — edits stick across `nobs autocon5 up`, `nobs autocon5 down`, `nobs autocon5 destroy`.
The only way `.env` gets recreated is if you delete it and re-run a command that triggers the bootstrap.

## What's in it

The committed `.env.example` defines:

| Variable | Default | Purpose |
|----------|---------|---------|
| `GRAFANA_USER` | `admin` | Grafana admin login. |
| `GRAFANA_PASSWORD` | `admin` | Grafana admin password. |
| `INFRAHUB_ADDRESS` | `http://infrahub-server:8000` | Infrahub URL. The default is the **container DNS** name — see [the host vs container nuance](#the-host-vs-container-nuance) below. |
| `INFRAHUB_API_TOKEN` | `06438eb2-...` | Token seeded into Infrahub on first boot via `INFRAHUB_INITIAL_ADMIN_TOKEN`. Both Grafana's GraphQL datasource and `nobs` read this. |
| `ENABLE_AI_RCA` | `false` | Toggles the LLM RCA step in the Prefect quarantine flow. |
| `AI_RCA_PROVIDER` | `openai` | `openai` or `anthropic`. |
| `AI_RCA_MODEL` | `gpt-4o-mini` | The model id; e.g. `claude-haiku-4-5-20251001` for anthropic. |
| `OPENAI_API_KEY` | empty | Required when `AI_RCA_PROVIDER=openai` and `ENABLE_AI_RCA=true`. |
| `ANTHROPIC_API_KEY` | empty | Required when `AI_RCA_PROVIDER=anthropic` and `ENABLE_AI_RCA=true`. |
| `SONDA_SERVER_URL` | `http://localhost:8085` | Where the workshop CLI POSTs annotations via `/events`. Container-side callers use `http://sonda-server:8080` (set explicitly in `docker-compose.yml`). |
| `SONDA_API_KEY` | empty | Bearer for sonda's `/events` and `/scenarios`. Empty disables auth (workshop default). |
| `SONDA_LOKI_SINK_URL` | `http://loki:3001` | URL sonda's `/events` handler uses to forward to Loki — sonda's container-network view of Loki, distinct from `LOKI_URL`. |

`.env.example` also ships commented `*_IMAGE` overrides (`SONDA_IMAGE`, `PROMETHEUS_IMAGE`, `LOKI_IMAGE`, `GRAFANA_IMAGE`, `ALERTMANAGER_IMAGE`, `TELEGRAF_IMAGE`, `INFRAHUB_IMAGE`).
Uncomment one to pin or upgrade an image without editing `docker-compose.yml`.

## Two consumers, two loaders

Both consumers run from `workshops/autocon5/`.
The loading mechanism differs because each consumer has a different default for "what counts as the environment."

### 1. `docker compose` — automatic

Compose v2 auto-loads a file named `.env` from the directory it's invoked in.
It interpolates `${VAR}` references in `docker-compose.yml`:

```yaml
# excerpt from docker-compose.yml
grafana:
  image: ${GRAFANA_IMAGE:-docker.io/grafana/grafana:10.4.4}
  environment:
    GF_SECURITY_ADMIN_USER: ${GRAFANA_USER:-admin}
    GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD:-admin}
    INFRAHUB_API_TOKEN: ${INFRAHUB_API_TOKEN}
```

No explicit loading is needed — it's compose's built-in behaviour.
`nobs` `cd`s into the workshop directory before running `docker compose`, so the right `.env` is in scope.

This consumer is **mandatory**.
Every container with `${VAR}` in `docker-compose.yml` depends on it.
Image pins, the Infrahub initial token, the AI RCA toggle, and Grafana credentials all flow through this path.

### 2. `nobs` startup — `load_env()`

Every `nobs autocon5 ...` command calls `nobs.lifecycle.env.load_env(workshop_dir)` once at startup.
The loader uses [`python-dotenv`][dotenv]'s `dotenv_values()` to read the file, merges the values into `os.environ` (process env wins on conflict, matching docker-compose semantics), and applies the `infrahub-server → localhost` rewrite (see below) before any Typer command runs.

```python
# packages/nobs/src/nobs/lifecycle/env.py
def load_env(workshop_dir: Path) -> dict[str, str]:
    env_file = workshop_dir / ".env"
    values = dotenv_values(env_file) if env_file.is_file() else {}
    # merge, then rewrite infrahub-server -> localhost in INFRAHUB_ADDRESS
    ...
```

Each Typer command then reads its env via `envvar=...` declarations on its parameters.
Without this startup load, the CLI would start with an empty `INFRAHUB_API_TOKEN` and exit early.

[dotenv]: https://pypi.org/project/python-dotenv/

## Why two consumers, not one

It boils down to two constraints:

1. **Compose auto-load is non-negotiable.**
   Every container with `${VAR}` in `docker-compose.yml` depends on it.
   Removing it isn't an option.
2. **`uv run` doesn't read `.env` itself.**
   It runs the command in a pristine subprocess inheriting only the calling shell's environment.
   So `nobs` reads `.env` itself at startup via `python-dotenv`, before any Typer command dispatches.

The result is one `.env` file with two readers, both converging on the same values.

## The host vs container nuance

`INFRAHUB_ADDRESS=http://infrahub-server:8000` is the **container DNS name** of the Infrahub server inside the workshop's docker network.
That's the value Grafana and the Prefect alert-receiver flow need — they run inside the network and resolve `infrahub-server` correctly.

`nobs` runs on the **host**.
From there, `infrahub-server` doesn't resolve at all.
To keep `.env` correct for both audiences without forcing the operator to swap values, the rewrite happens **once**, centrally, at CLI startup:

| File | Behaviour |
|------|-----------|
| [`packages/nobs/src/nobs/lifecycle/env.py`](../../../packages/nobs/src/nobs/lifecycle/env.py) (`load_env`) | If `infrahub-server` is in `INFRAHUB_ADDRESS`, rewrite it to `http://localhost:8000` and re-export to `os.environ` before any command runs. |

Every `nobs ...` invocation — `status`, `alerts`, `evidence`, `try-it`, `maintenance`, `load-infrahub`, `schema load` — sees the host-reachable URL automatically.
No per-command rewrite, no caveat.

## Editing `.env` after first boot

Most edits are picked up cleanly:

- **Image overrides, AI RCA toggles, AI keys, Grafana password**: edit `.env`, then `nobs autocon5 restart` (or `nobs autocon5 restart prefect-flows` for AI/Prefect-only changes).
- **`INFRAHUB_API_TOKEN`**: this one is special.
  Infrahub seeds the token via `INFRAHUB_INITIAL_ADMIN_TOKEN`, which is **only honoured on the first boot of `infrahub-server`**.
  Changing it after first boot desyncs the value in `.env` (used by Grafana + `nobs`) from the value Infrahub actually accepts.
  Recover with:

  ```bash
  nobs autocon5 destroy   # drops infrahub_db_data so the token re-seeds
  nobs autocon5 up
  nobs autocon5 load-infrahub
  ```

Anything else (`GRAFANA_USER`, `INFRAHUB_ADDRESS`, etc.) follows the restart pattern — no destroy needed.

## Where the pieces live

| File | Role |
|------|------|
| [`../.env.example`](../.env.example) | Tracked template. The seed for the operator's `.env`. |
| [`../src/autocon5_workshop/bootstrap.py`](../src/autocon5_workshop/bootstrap.py) | Workshop bootstrap hook — copies `.env.example` to `.env` if missing. |
| [`../../../packages/nobs/src/nobs/lifecycle/env.py`](../../../packages/nobs/src/nobs/lifecycle/env.py) | The single startup loader. Reads `.env` via `python-dotenv` and applies the `infrahub-server → localhost` rewrite. |
| [`../docker-compose.yml`](../docker-compose.yml) | The other consumer; uses `${VAR}` interpolation throughout. |
