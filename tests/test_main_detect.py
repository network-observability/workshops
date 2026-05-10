"""Tests for `nobs.main._detect_current_workshop`."""
from __future__ import annotations

from pathlib import Path

import pytest
from nobs.main import _detect_current_workshop
from nobs.workshops import REGISTRY, Workshop


@pytest.fixture
def autocon5_in_registry(tmp_path: Path):
    """Register an autocon5-shaped workshop rooted at tmp_path/autocon5/.

    Yields the workshop dir for caller convenience and pops the registry
    entry after the test so the suite isn't poisoned.
    """
    ws_dir = tmp_path / "autocon5"
    ws_dir.mkdir()
    (ws_dir / "docker-compose.yml").write_text("services: {}\n")

    initial_len = len(REGISTRY)
    ws = Workshop(name="autocon5-detect-test", title="Detect Test", dir=ws_dir)
    REGISTRY.append(ws)
    try:
        yield ws_dir
    finally:
        while len(REGISTRY) > initial_len:
            REGISTRY.pop()


def test_detect_returns_none_outside_any_workshop(tmp_path: Path) -> None:
    assert _detect_current_workshop(cwd=tmp_path) is None


def test_detect_returns_workshop_at_dir_root(autocon5_in_registry: Path) -> None:
    ws = _detect_current_workshop(cwd=autocon5_in_registry)
    assert ws is not None
    assert ws.dir == autocon5_in_registry.resolve()


def test_detect_returns_workshop_for_descendant(autocon5_in_registry: Path) -> None:
    """Anywhere inside the workshop's tree should resolve to the workshop."""
    nested = autocon5_in_registry / "docs" / "guides"
    nested.mkdir(parents=True)
    ws = _detect_current_workshop(cwd=nested)
    assert ws is not None
    assert ws.dir == autocon5_in_registry.resolve()


def test_detect_returns_none_for_sibling(autocon5_in_registry: Path) -> None:
    """A sibling directory (same parent, different name) is NOT a match."""
    sibling = autocon5_in_registry.parent / "other"
    sibling.mkdir()
    assert _detect_current_workshop(cwd=sibling) is None
