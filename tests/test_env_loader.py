"""Tests for `nobs.lifecycle.env.load_env` + `host_address`.

These pin the two BLOCKERs the Opus reviewer caught in PR #4:

  1. `load_env` must NOT mutate `INFRAHUB_ADDRESS` in `os.environ` to the
     host-localhost value, because `os.environ` is then passed verbatim to
     compose subprocesses, which propagate the wrong host into containers.

  2. `host_address` is the host-side rewrite helper. It returns the
     localhost form when the input contains the in-network DNS name; it
     leaves anything else alone.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from nobs.lifecycle.env import host_address, load_env


@pytest.fixture
def workshop_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Yield a workshop dir with a `.env` file. Snapshot+restore os.environ
    so individual tests can mutate it freely."""
    env = tmp_path / ".env"
    env.write_text(
        "INFRAHUB_ADDRESS=http://infrahub-server:8000\n"
        "INFRAHUB_API_TOKEN=test-token-123\n"
        "GRAFANA_USER=admin\n"
    )
    monkeypatch.delenv("INFRAHUB_ADDRESS", raising=False)
    monkeypatch.delenv("INFRAHUB_API_TOKEN", raising=False)
    monkeypatch.delenv("GRAFANA_USER", raising=False)
    return tmp_path


def test_load_env_merges_dotenv_into_os_environ(workshop_dir: Path) -> None:
    load_env(workshop_dir)
    assert os.environ["INFRAHUB_API_TOKEN"] == "test-token-123"
    assert os.environ["GRAFANA_USER"] == "admin"


def test_load_env_does_not_rewrite_infrahub_address_in_os_environ(workshop_dir: Path) -> None:
    """BLOCKER #1 — compose subprocesses inherit os.environ, so the
    in-network value MUST survive the merge unchanged. The host-side
    rewrite happens at host_address() call sites only."""
    load_env(workshop_dir)
    assert os.environ["INFRAHUB_ADDRESS"] == "http://infrahub-server:8000"


def test_load_env_existing_os_environ_wins(
    workshop_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If a value is already set in os.environ, it must override `.env`
    (matches docker-compose precedence)."""
    monkeypatch.setenv("GRAFANA_USER", "shell-override")
    load_env(workshop_dir)
    assert os.environ["GRAFANA_USER"] == "shell-override"


def test_load_env_missing_dotenv_is_no_op(tmp_path: Path) -> None:
    """No .env file must not crash; just merges the existing os.environ."""
    merged = load_env(tmp_path)
    assert isinstance(merged, dict)


def test_load_env_idempotent(workshop_dir: Path) -> None:
    load_env(workshop_dir)
    snapshot = dict(os.environ)
    load_env(workshop_dir)
    assert dict(os.environ) == snapshot


def test_host_address_rewrites_in_network_name() -> None:
    """The rewrite helper returns localhost when given the container DNS."""
    assert host_address("http://infrahub-server:8000") == "http://localhost:8000"


def test_host_address_passes_through_external_urls() -> None:
    """A user-supplied external URL must NOT be touched."""
    assert host_address("https://infrahub.example.com") == "https://infrahub.example.com"
    assert host_address("http://localhost:8000") == "http://localhost:8000"


def test_host_address_handles_empty_input() -> None:
    """Empty / None inputs return empty string for chaining safety."""
    assert host_address("") == ""
    assert host_address(None) == ""
