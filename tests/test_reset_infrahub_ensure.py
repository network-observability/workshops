"""Tests for each workshop's `reset._ensure_infrahub_loaded` — probe-then-load behavior."""

from __future__ import annotations

import importlib
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
import requests

PLUGINS = ["autocon5_workshop", "packt_workshop"]


@pytest.fixture(params=PLUGINS)
def plugin(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def slug(plugin: str) -> str:
    return plugin.removesuffix("_workshop")


@pytest.fixture
def reset(plugin: str) -> ModuleType:
    return importlib.import_module(f"{plugin}.reset")


def _mock_graphql_response(edges: list[dict]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json.return_value = {"data": {"WorkshopDevice": {"edges": edges}}}
    return response


@pytest.fixture
def device_edges_two() -> list[dict]:
    return [
        {"node": {"name": {"value": "srl1"}}},
        {"node": {"name": {"value": "srl2"}}},
    ]


def test_probe_returns_two_devices_skips_subprocess_invocation(reset: ModuleType, device_edges_two: list[dict]) -> None:
    with (
        patch.object(reset.requests, "post", return_value=_mock_graphql_response(device_edges_two)) as mock_post,
        patch("subprocess.run") as mock_run,
    ):
        reset._ensure_infrahub_loaded("http://localhost:8000")

    mock_post.assert_called_once()
    mock_run.assert_not_called()


def test_probe_returns_zero_devices_invokes_load_infrahub(reset: ModuleType, slug: str) -> None:
    with (
        patch.object(reset.requests, "post", return_value=_mock_graphql_response([])),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        reset._ensure_infrahub_loaded("http://localhost:8000")

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    assert args[0] == ["uv", "run", "nobs", slug, "load-infrahub"]
    assert kwargs["timeout"] == 60
    assert kwargs["capture_output"] is True


def test_probe_returns_one_device_invokes_load_infrahub(reset: ModuleType) -> None:
    one_edge = [{"node": {"name": {"value": "srl1"}}}]
    with (
        patch.object(reset.requests, "post", return_value=_mock_graphql_response(one_edge)),
        patch("subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        reset._ensure_infrahub_loaded("http://localhost:8000")

    mock_run.assert_called_once()


def test_probe_failure_warns_and_skips_subprocess(reset: ModuleType) -> None:
    with (
        patch.object(reset.requests, "post", side_effect=requests.ConnectionError("boom")),
        patch("subprocess.run") as mock_run,
    ):
        reset._ensure_infrahub_loaded("http://localhost:8000")

    mock_run.assert_not_called()


def test_probe_url_strips_trailing_slash(reset: ModuleType, device_edges_two: list[dict]) -> None:
    with (
        patch.object(reset.requests, "post", return_value=_mock_graphql_response(device_edges_two)) as mock_post,
        patch("subprocess.run"),
    ):
        reset._ensure_infrahub_loaded("http://localhost:8000/")

    called_url = mock_post.call_args[0][0]
    assert called_url == "http://localhost:8000/graphql"
