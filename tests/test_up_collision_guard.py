"""Tests for the cross-workshop container-collision guard.

Every workshop stack pins the same container names and host ports, so no
workshop may create containers while another registered workshop's
containers exist. That holds for every lifecycle verb that issues a compose
`up`, not just `nobs <workshop> up`.
"""

from __future__ import annotations

import inspect
import subprocess
from collections.abc import Callable, Iterator
from functools import partial
from itertools import product
from pathlib import Path
from typing import Any, get_args, get_origin, get_type_hints
from unittest.mock import MagicMock, patch

import pytest
import typer
from nobs.lifecycle import commands
from nobs.lifecycle.commands import build_for, restart_for, up_for
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
    assert "nobs beta down" in out
    assert "grafana, loki" in out


def test_collision_message_truncates_a_long_container_list(
    up: Callable[[], None],
    docker_ps: MagicMock,
    run_compose: MagicMock,
    capsys: pytest.CaptureFixture[str],
) -> None:
    names = [f"svc{i:02d}" for i in range(22)]
    docker_ps.side_effect = _docker_ps({"beta": names})
    with pytest.raises(typer.Exit):
        up()
    out = " ".join(capsys.readouterr().out.split())
    assert "svc00, svc01, svc02 (+19 more)" in out
    assert "svc21" not in out


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
    projects = {next(a for a in call.args[0] if a.startswith("label=")) for call in docker_ps.call_args_list}
    assert projects == {
        "label=com.docker.compose.project=beta",
        "label=com.docker.compose.project=gamma",
    }


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


LIFECYCLE_FACTORIES = [
    fn
    for name, fn in vars(commands).items()
    if name.endswith("_for") and inspect.isfunction(fn) and fn.__module__ == commands.__name__
]


def _completed() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["docker", "compose"], 0, stdout="", stderr="")


def _accepts_list(annotation: Any) -> bool:
    return get_origin(annotation) is list or any(get_origin(arg) is list for arg in get_args(annotation))


def _candidate_values(param: inspect.Parameter, annotation: Any) -> list[Any]:
    if param.default is inspect.Parameter.empty:
        return ["svc"]
    if isinstance(param.default, bool):
        return [False, True]
    if param.default is None:
        return [None, ["svc"] if _accepts_list(annotation) else "svc"]
    return [param.default]


def _argument_matrix(closure: Callable[..., None]) -> list[dict[str, Any]]:
    hints = get_type_hints(closure, include_extras=False)
    params = inspect.signature(closure).parameters
    choices = [_candidate_values(param, hints.get(name)) for name, param in params.items()]
    return [dict(zip(params, combo, strict=True)) for combo in product(*choices)]


def _compose_calls(closure: Callable[..., None], kwargs: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Actions this invocation sends straight to `run_compose`, and those it sends through `_guarded_up`."""
    with (
        patch("nobs.lifecycle.commands.run_compose") as direct,
        patch("nobs.lifecycle.commands._guarded_up") as seam,
    ):
        direct.return_value = _completed()
        seam.return_value = _completed()
        closure(**kwargs)
    return (
        [call.args[0] for call in direct.call_args_list],
        [call.args[0] for call in seam.call_args_list],
    )


def _invocations_issuing_up(ws: Workshop) -> list[tuple[str, Callable[[], None]]]:
    """Every (label, callable) over the lifecycle closures whose compose calls include an `up`."""
    issuing: list[tuple[str, Callable[[], None]]] = []
    for factory in LIFECYCLE_FACTORIES:
        closure = factory(ws)
        for kwargs in _argument_matrix(closure):
            direct, seam = _compose_calls(closure, kwargs)
            if any(action.startswith("up") for action in [*direct, *seam]):
                issuing.append((f"{factory.__name__}({kwargs})", partial(closure, **kwargs)))
    return issuing


def test_up_issuing_closures_cover_the_known_container_creating_verbs(
    registry: dict[str, Workshop], docker_ps: MagicMock, urls_panel: MagicMock
) -> None:
    factories = {label.split("(")[0] for label, _ in _invocations_issuing_up(registry["alpha"])}
    assert {"up_for", "build_for", "restart_for"} <= factories


def test_no_lifecycle_closure_issues_an_unguarded_up(
    registry: dict[str, Workshop], docker_ps: MagicMock, urls_panel: MagicMock
) -> None:
    for factory in LIFECYCLE_FACTORIES:
        closure = factory(registry["alpha"])
        for kwargs in _argument_matrix(closure):
            direct, _ = _compose_calls(closure, kwargs)
            assert [action for action in direct if action.startswith("up")] == [], f"{factory.__name__}({kwargs})"


def test_every_lifecycle_closure_that_issues_up_refuses_before_any_compose_work(
    registry: dict[str, Workshop], docker_ps: MagicMock, urls_panel: MagicMock
) -> None:
    invocations = _invocations_issuing_up(registry["alpha"])
    assert invocations

    docker_ps.side_effect = _docker_ps({"beta": ["grafana"]})
    for label, invoke in invocations:
        with patch("nobs.lifecycle.commands.run_compose") as mock:
            mock.return_value = _completed()
            with pytest.raises(typer.Exit) as exc:
                invoke()
            assert exc.value.exit_code == 1, label
            assert [call.args[0] for call in mock.call_args_list] == [], label


def test_build_rebuilds_then_brings_services_up_when_no_conflict(
    registry: dict[str, Workshop], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    build_for(registry["alpha"])(services=["sonda-server"])
    assert [call.args[0] for call in run_compose.call_args_list] == ["build", "up -d"]


def test_restart_downs_then_ups_when_no_conflict(
    registry: dict[str, Workshop], docker_ps: MagicMock, run_compose: MagicMock
) -> None:
    restart_for(registry["alpha"])()
    assert [call.args[0] for call in run_compose.call_args_list] == ["down", "up -d --build"]
