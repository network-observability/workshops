"""Workshop registration model and registry.

Each workshop ships a `Workshop` instance in its package `__init__.py` and
calls `register(WORKSHOP)` as a side-effect of import. `nobs.main` then
builds a Typer subcommand group from each registered workshop.

Example
-------
```python
from pathlib import Path
from nobs.workshops import Workshop, register

WORKSHOP = Workshop(
    name="autocon5",
    title="AutoCon5 - Modern Network Observability",
    dir=Path(__file__).resolve().parents[3],
)
register(WORKSHOP)
```
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")

VALID_CAPABILITIES: frozenset[str] = frozenset({"status", "alerts", "maintenance", "schema"})

_RESERVED_EXTRA_NAMES: frozenset[str] = frozenset({
    "up", "down", "destroy", "restart", "ps", "logs", "exec", "build",
}) | VALID_CAPABILITIES


class Workshop(BaseModel):
    """Self-describing handle a workshop registers with `nobs`.

    The Pydantic model gives us field descriptions (so introspection
    surfaces them in `nobs workshops --json` style output) and validators
    (so a misregistered workshop fails at import time, before any Typer
    dispatch).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    name: str = Field(
        description=(
            "Lowercase, URL-safe workshop slug. Used as the CLI subcommand name "
            "(`nobs <name> ...`) and the `docker compose --project-name`."
        ),
        examples=["autocon5"],
    )
    title: str = Field(
        description="Human-readable workshop title.",
        examples=["AutoCon5 - Modern Network Observability"],
    )
    dir: Path = Field(
        description=(
            "Workshop directory (where docker-compose.yml + .env live). "
            "Resolved once at registration time."
        ),
        examples=[Path("/repo/workshops/autocon5")],
    )
    compose_file: Path | None = Field(
        default=None,
        description="Override path to the compose file; defaults to `dir / docker-compose.yml`.",
        examples=[None],
    )
    bootstrap: Callable[[], None] | None = Field(
        default=None,
        description=(
            "Workshop-specific setup hook (e.g. copy .env.example to .env). "
            "Called by `nobs setup` and as a `deps` of `nobs <name> up`."
        ),
    )
    extra_commands: list[Callable] = Field(
        default_factory=list,
        description="Workshop-specific Typer command callables added to the subcommand group.",
    )
    capabilities: frozenset[str] = Field(
        default_factory=lambda: VALID_CAPABILITIES,
        description="Operational primitives this workshop exposes. See `VALID_CAPABILITIES`.",
        examples=[frozenset({"status", "alerts", "maintenance", "schema"})],
    )

    @field_validator("capabilities", mode="before")
    @classmethod
    def _coerce_capabilities(cls, v: object) -> frozenset[str]:
        if isinstance(v, frozenset):
            return v
        if isinstance(v, (list, set, tuple)):
            return frozenset(str(x) for x in v)
        raise ValueError(f"capabilities must be a collection of strings, got {type(v).__name__}")

    @field_validator("capabilities")
    @classmethod
    def _check_capabilities(cls, v: frozenset[str]) -> frozenset[str]:
        unknown = v - VALID_CAPABILITIES
        if unknown:
            raise ValueError(
                f"Unknown capability/capabilities: {sorted(unknown)}. "
                f"Valid: {sorted(VALID_CAPABILITIES)}"
            )
        return v

    @field_validator("extra_commands")
    @classmethod
    def _check_extra_commands(cls, v: list[Callable]) -> list[Callable]:
        seen: set[str] = set()
        for cmd in v:
            name = getattr(cmd, "__name__", "").replace("_", "-")
            if not name:
                raise ValueError("extra_commands entry has no __name__")
            if name in _RESERVED_EXTRA_NAMES:
                raise ValueError(
                    f"extra_commands name {name!r} collides with a reserved "
                    f"lifecycle/capability slot. Reserved: {sorted(_RESERVED_EXTRA_NAMES)}"
                )
            if name in seen:
                raise ValueError(f"extra_commands has duplicate command name {name!r}")
            seen.add(name)
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(f"Workshop name must match {_NAME_RE.pattern!r} (got {v!r}).")
        return v

    @field_validator("dir")
    @classmethod
    def _check_dir(cls, v: Path) -> Path:
        v = v.resolve()
        if not v.is_dir():
            raise ValueError(f"Workshop dir does not exist: {v}")
        return v

    @field_validator("compose_file")
    @classmethod
    def _check_compose_file(cls, v: Path | None) -> Path | None:
        if v is not None and not v.is_file():
            raise ValueError(f"Workshop compose_file does not exist: {v}")
        return v

    def resolved_compose_file(self) -> Path:
        """Return the compose file to use (override or default `dir/docker-compose.yml`)."""
        return self.compose_file or (self.dir / "docker-compose.yml")


REGISTRY: list[Workshop] = []


def register(ws: Workshop) -> None:
    """Register a workshop with `nobs`.

    Called from each workshop package's `__init__.py` as a side-effect of
    import. Raises `ValueError` if a workshop with the same name is already
    registered.
    """
    if any(w.name == ws.name for w in REGISTRY):
        raise ValueError(f"Workshop name conflict: {ws.name!r} already registered.")
    REGISTRY.append(ws)
