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
        "Uppercase",          # must be lowercase
        "1starts-with-digit", # must start with a-z
        "has_underscore",     # underscore not allowed
        "",                   # empty
        "x" * 40,             # too long
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
