"""Tests for the peer-scoped log queries used in the Packt evidence step."""

from __future__ import annotations

from unittest.mock import Mock, patch

from packt_workshop.evidence import _fetch_logs

from workshops.packt.automation.workshop_sdk import WorkshopSDK


def test_cli_evidence_filters_logs_by_device_and_peer() -> None:
    client = Mock()
    client.query_range.return_value = ["line"]

    with patch("packt_workshop.evidence.LokiClient", return_value=client):
        result = _fetch_logs("http://loki:3001", "srl1", "10.1.99.2", minutes=10, limit=20)

    assert result == ["line"]
    client.query_range.assert_called_once_with(
        '{device="srl1",peer_address="10.1.99.2"} != "license"',
        minutes=10,
        limit=20,
    )


def test_workflow_evidence_filters_logs_by_device_and_peer() -> None:
    assert WorkshopSDK().bgp_logql("srl1", "10.1.99.2") == (
        '{device="srl1",peer_address="10.1.99.2"} != "license"'
    )
