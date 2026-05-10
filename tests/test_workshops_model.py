"""Tests for `nobs.workshops.Workshop` validators + `register()`."""

from __future__ import annotations

from pathlib import Path

import pytest
from nobs.workshops import REGISTRY, Workshop, register
from pydantic import ValidationError


def _ws(tmp_path: Path, **overrides) -> Workshop:
    """Build a Workshop with sane defaults rooted in `tmp_path`."""
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services: {}\n")
    defaults = dict(
        name="testworkshop",
        title="Test Workshop",
        dir=tmp_path,
        compose_file=compose,
    )
    defaults.update(overrides)
    return Workshop(**defaults)


def test_valid_workshop(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    assert ws.name == "testworkshop"
    assert ws.dir == tmp_path.resolve()
    assert ws.resolved_compose_file() == (tmp_path / "docker-compose.yml")


@pytest.mark.parametrize(
    "bad",
    [
        "Uppercase",  # must be lowercase
        "1starts-with-digit",  # must start with a-z
        "has_underscore",  # underscore not allowed
        "",  # empty
        "x" * 40,  # too long
        "has space",
    ],
)
def test_invalid_name(tmp_path: Path, bad: str) -> None:
    with pytest.raises(ValidationError):
        _ws(tmp_path, name=bad)


def test_dir_must_exist(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _ws(tmp_path, dir=tmp_path / "does-not-exist")


def test_compose_file_must_exist_when_set(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _ws(tmp_path, compose_file=tmp_path / "missing.yml")


def test_compose_file_default_resolves_under_dir(tmp_path: Path) -> None:
    ws = Workshop(name="defaults", title="Defaults", dir=tmp_path)
    assert ws.compose_file is None
    assert ws.resolved_compose_file() == tmp_path / "docker-compose.yml"


def test_capabilities_default_is_full_set(tmp_path: Path) -> None:
    ws = _ws(tmp_path)
    assert ws.capabilities == frozenset({"status", "alerts", "maintenance", "schema"})


def test_capabilities_can_be_subset(tmp_path: Path) -> None:
    ws = _ws(tmp_path, capabilities={"status", "alerts"})
    assert "status" in ws.capabilities
    assert "alerts" in ws.capabilities
    assert "maintenance" not in ws.capabilities
    assert "schema" not in ws.capabilities


def test_capabilities_accepts_list(tmp_path: Path) -> None:
    ws = _ws(tmp_path, capabilities=["status"])
    assert ws.capabilities == frozenset({"status"})


def test_capabilities_rejects_unknown(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="Unknown capability"):
        _ws(tmp_path, capabilities={"status", "not-a-real-cap"})


def test_capabilities_rejects_non_collection(tmp_path: Path) -> None:
    """The mode='before' coercion must raise ValueError (not TypeError) so
    Pydantic wraps it into ValidationError instead of leaking a raw type error."""
    with pytest.raises(ValidationError, match="must be a collection"):
        _ws(tmp_path, capabilities=42)
    with pytest.raises(ValidationError, match="must be a collection"):
        _ws(tmp_path, capabilities="status")


def test_extra_commands_rejects_lifecycle_collision(tmp_path: Path) -> None:
    """extra_commands names must not collide with lifecycle / capability slots."""

    def up() -> None:  # collides with lifecycle "up"
        pass

    with pytest.raises(ValidationError, match="reserved lifecycle/capability slot"):
        _ws(tmp_path, extra_commands=[up])


def test_extra_commands_rejects_capability_collision(tmp_path: Path) -> None:
    def alerts() -> None:  # collides with capability "alerts"
        pass

    with pytest.raises(ValidationError, match="reserved lifecycle/capability slot"):
        _ws(tmp_path, extra_commands=[alerts])


def test_extra_commands_allows_root_primitive_names(tmp_path: Path) -> None:
    """`preflight` and `setup` ARE allowed as extras — they resolve under the
    workshop prefix; the auto-mount's skip set keeps the root meta version."""

    def preflight() -> None:
        pass

    ws = _ws(tmp_path, extra_commands=[preflight])
    assert preflight in ws.extra_commands


def test_extra_commands_rejects_duplicate_names(tmp_path: Path) -> None:
    def reset() -> None:
        pass

    def reset_again() -> None:  # different function, same surfaced name
        pass

    reset_again.__name__ = "reset"
    with pytest.raises(ValidationError, match="duplicate command name"):
        _ws(tmp_path, extra_commands=[reset, reset_again])


def test_capabilities_empty_set_allowed(tmp_path: Path) -> None:
    """A workshop with no operational primitives only ships lifecycle + extra commands."""
    ws = _ws(tmp_path, capabilities=set())
    assert ws.capabilities == frozenset()


def test_register_rejects_duplicate_names(tmp_path: Path) -> None:
    """Re-registering a workshop with a colliding name must raise."""
    initial_len = len(REGISTRY)
    ws = _ws(tmp_path, name="duplicate-test")
    register(ws)
    try:
        with pytest.raises(ValueError, match="already registered"):
            register(_ws(tmp_path, name="duplicate-test"))
    finally:
        # leave REGISTRY clean so the rest of the suite isn't poisoned
        while len(REGISTRY) > initial_len:
            REGISTRY.pop()
