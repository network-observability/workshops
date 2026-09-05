"""Tests for the `nobs <workshop> up` cross-workshop collision guard.

Every workshop stack pins the same container names and host ports, so `up`
must refuse to start while another registered workshop's containers exist.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import typer
from nobs.lifecycle.commands import up_for
from nobs.workshops import REGISTRY, Workshop


def _make_workshop(root: Path, name: str, title: str, bootstrap: Callable[[], None] | None = None) -> Workshop:
    ws_dir = root / name
    ws_dir.mkdir()
    (ws_dir / "docker-compose.yml").write_text("services: {}\n")
    return Workshop(name=name, title=title, dir=ws_dir, bootstrap=bootstrap)


class _BootstrapSpy:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1


@pytest.fixture
def bootstrap_spy() -> _BootstrapSpy:
    return _BootstrapSpy()


@pytest.fixture
def registry(tmp_path: Path, bootstrap_spy: _BootstrapSpy) -> Iterator[dict[str, Workshop]]:
    """Replace REGISTRY in place with three fake workshops, restoring after."""
    saved = list(REGISTRY)
    REGISTRY.clear()
    workshops = {
        "alpha": _make_workshop(tmp_path, "alpha", "Alpha Workshop", bootstrap=bootstrap_spy),
        "beta": _make_workshop(tmp_path, "beta", "Beta Workshop"),
        "gamma": _make_workshop(tmp_path, "gamma", "Gamma Workshop"),
    }
    REGISTRY.extend(workshops.values())
    try:
        yield workshops
    finally:
        REGISTRY.clear()
        REGISTRY.extend(saved)


def _docker_ps(containers: dict[str, list[str]]) -> Callable[..., subprocess.CompletedProcess[str]]:
    """`subprocess.run` stand-in answering `docker ps` per compose project."""

    def _run(cmd: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        project = next(a for a in cmd if a.startswith("label=")).split("=")[-1]
        names = containers.get(project, [])
        return subprocess.CompletedProcess(cmd, 0, stdout="".join(f"{n}\n" for n in names), stderr="")

    return _run


@pytest.fixture
def docker_ps() -> Iterator[MagicMock]:
    with patch("nobs.lifecycle.compose.subprocess.run") as mock:
        mock.side_effect = _docker_ps({})
        yield mock


@pytest.fixture
def run_compose() -> Iterator[MagicMock]:
    with patch("nobs.lifecycle.commands.run_compose") as mock:
        mock.return_value = subprocess.CompletedProcess(["docker", "compose"], 0, stdout="", stderr="")
        yield mock


@pytest.fixture
def urls_panel() -> Iterator[MagicMock]:
    with patch("nobs.lifecycle.commands._print_urls_panel") as mock:
        yield mock


@pytest.fixture
def up(registry: dict[str, Workshop], urls_panel: MagicMock) -> Callable[[], None]:
    return up_for(registry["alpha"])


def test_up_exits_1_when_another_workshop_has_containers(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    docker_ps.side_effect = _docker_ps({"beta": ["grafana", "prometheus"]})
    with pytest.raises(typer.Exit) as exc:
        up()
    assert exc.value.exit_code == 1


def test_up_does_not_invoke_compose_on_collision(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    docker_ps.side_effect = _docker_ps({"beta": ["grafana"]})
    with pytest.raises(typer.Exit):
        up()
    run_compose.assert_not_called()


def test_up_does_not_run_bootstrap_on_collision(
    up: Callable[[], None],
    docker_ps: MagicMock,
    run_compose: MagicMock,
    bootstrap_spy: _BootstrapSpy,
) -> None:
    docker_ps.side_effect = _docker_ps({"beta": ["grafana"]})
    with pytest.raises(typer.Exit):
        up()
    assert bootstrap_spy.calls == 0


def test_collision_message_names_the_other_workshop_and_remediation(
    up: Callable[[], None],
    docker_ps: MagicMock,
    run_compose: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docker_ps.side_effect = _docker_ps({"beta": ["grafana", "loki"]})
    with pytest.raises(typer.Exit):
        up()
    out = " ".join(capsys.readouterr().out.split())
    assert "Beta Workshop" in out
    assert "nobs beta destroy" in out
    assert "grafana, loki" in out


def test_up_proceeds_when_no_other_workshop_has_containers(
    up: Callable[[], None],
    docker_ps: MagicMock,
    run_compose: MagicMock,
    bootstrap_spy: _BootstrapSpy,
) -> None:
    up()
    run_compose.assert_called_once()
    assert bootstrap_spy.calls == 1


def test_up_proceeds_when_only_own_project_has_containers(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    docker_ps.side_effect = _docker_ps({"alpha": ["grafana", "prometheus"]})
    up()
    run_compose.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError("docker"),
        subprocess.TimeoutExpired(cmd="docker ps", timeout=10.0),
        PermissionError("docker.sock"),
    ],
    ids=["binary-missing", "timeout", "permission-denied"],
)
def test_up_fails_open_when_docker_ps_raises(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock, failure: Exception
) -> None:
    docker_ps.side_effect = failure
    up()
    run_compose.assert_called_once()


def test_up_fails_open_when_docker_ps_exits_nonzero(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    docker_ps.side_effect = None
    docker_ps.return_value = subprocess.CompletedProcess(
        ["docker", "ps"], 1, stdout="", stderr="Cannot connect to the Docker daemon\n"
    )
    up()
    run_compose.assert_called_once()


def test_guard_queries_every_other_registered_workshop(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    up()
    projects = [next(a for a in call.args[0] if a.startswith("label=")) for call in docker_ps.call_args_list]
    assert projects == [
        "label=com.docker.compose.project=beta",
        "label=com.docker.compose.project=gamma",
    ]


def test_guard_never_queries_its_own_project(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    up()
    assert not any("=alpha" in arg for call in docker_ps.call_args_list for arg in call.args[0])


def test_guard_queries_stopped_containers_too(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    up()
    for call in docker_ps.call_args_list:
        assert call.args[0][:3] == ["docker", "ps", "-a"]


def test_guard_stops_at_the_first_conflicting_workshop(
    up: Callable[[], None], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    docker_ps.side_effect = _docker_ps({"beta": ["grafana"], "gamma": ["loki"]})
    with pytest.raises(typer.Exit):
        up()
    assert docker_ps.call_count == 1
