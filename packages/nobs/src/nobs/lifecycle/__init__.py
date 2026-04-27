"""Generic stack-lifecycle plumbing for `nobs`.

Submodules:
- `compose` - docker compose command builder + subprocess wrapper.
- `env` - dotenv loader with the centralised infrahub-server -> localhost rewrite.
- `commands` - per-workshop closures (`up_for(ws)`, `down_for(ws)`, ...) wired by `nobs.main`.
- `preflight` - host environment check (Docker, RAM, disk, network).
- `setup` - top-level orchestration (`uv sync` + preflight + per-workshop bootstrap).
"""
