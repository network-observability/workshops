"""Test that compose subprocesses do NOT receive the host-rewritten
`INFRAHUB_ADDRESS`.

This pins BLOCKER #1 from PR #4's review: an earlier draft mutated
`os.environ['INFRAHUB_ADDRESS']` from the in-network `infrahub-server` form
to `localhost`, then passed `os.environ.copy()` to `docker compose`. The
resulting compose process injected `localhost:8000` into the
`prefect-flows` container's environment, which broke the in-network
Prefect → Infrahub query path silently.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from nobs.lifecycle import env as _env
from nobs.lifecycle.compose import run_compose
from nobs.workshops import Workshop


@pytest.fixture
def fake_workshop(tmp_path: Path) -> Workshop:
    compose = tmp_path / "docker-compose.yml"
    compose.write_text("services:\n  noop:\n    image: alpine\n")
    return Workshop(
        name="testws",
        title="Test",
        dir=tmp_path,
        compose_file=compose,
    )


@pytest.fixture
def workshop_with_env(tmp_path: Path) -> Path:
    """Workshop dir with a .env file containing the in-network DNS name."""
    (tmp_path / "docker-compose.yml").write_text("services: {}\n")
    (tmp_path / ".env").write_text("INFRAHUB_ADDRESS=http://infrahub-server:8000\n")
    return tmp_path


def test_run_compose_passes_unrewritten_infrahub_address(
    fake_workshop: Workshop,
    workshop_with_env: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BLOCKER #1 pin — after `load_env(ws.dir)`, run_compose must
    pass an env to the subprocess where INFRAHUB_ADDRESS is still
    `http://infrahub-server:8000` (NOT rewritten to localhost)."""
    monkeypatch.delenv("INFRAHUB_ADDRESS", raising=False)
    _env.load_env(workshop_with_env)

    with patch("nobs.lifecycle.compose.subprocess.run") as mock_run:
        mock_run.return_value = type("CP", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        run_compose("ps", fake_workshop)

    assert mock_run.called
    kwargs = mock_run.call_args.kwargs
    passed_env = kwargs["env"]
    assert passed_env["INFRAHUB_ADDRESS"] == "http://infrahub-server:8000", (
        "compose subprocess received the rewritten host URL — that breaks "
        "in-network containers' INFRAHUB_ADDRESS substitution"
    )


def test_load_env_then_host_address_returns_localhost(
    workshop_with_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rewrite still happens — just at the host_address() call site,
    not as a global os.environ mutation. Confirm the host-side helper
    sees the in-network value and rewrites it."""
    monkeypatch.delenv("INFRAHUB_ADDRESS", raising=False)
    _env.load_env(workshop_with_env)
    raw = os.environ["INFRAHUB_ADDRESS"]
    rewritten = _env.host_address(raw)
    assert raw == "http://infrahub-server:8000"
    assert rewritten == "http://localhost:8000"
