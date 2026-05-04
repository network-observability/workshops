"""Tests for the autocon5 flap-interface cascade body builder."""

from __future__ import annotations

import pytest
from autocon5_workshop.flap import _build_cascade
from autocon5_workshop.flap_topology import Peer


@pytest.fixture
def two_peers() -> list[Peer]:
    return [
        Peer(address="10.1.2.2", asn="65102"),
        Peer(address="10.1.7.2", asn="65102"),
    ]


def _entries_by_id(body: dict) -> dict[str, dict]:
    return {e["id"]: e for e in body["scenarios"]}


def test_cascade_has_primary_flap_and_one_log_entry(two_peers: list[Peer]) -> None:
    body = _build_cascade(
        device="srl1",
        interface="ethernet-1/1",
        peers=two_peers,
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        prom_url="http://prom:9090/api/v1/write",
        loki_url="http://loki:3001",
    )
    assert body["version"] == 2
    entries = _entries_by_id(body)
    assert "primary_flap" in entries
    assert "updown_logs_down" in entries
    primary = entries["primary_flap"]
    assert primary["generator"] == {
        "type": "flap",
        "up_duration": "30s",
        "down_duration": "60s",
    }
    assert "while" not in primary
    assert "delay" not in primary


def test_cascade_emits_six_metrics_per_peer(two_peers: list[Peer]) -> None:
    body = _build_cascade(
        device="srl1",
        interface="ethernet-1/1",
        peers=two_peers,
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        prom_url="http://prom:9090/api/v1/write",
        loki_url="http://loki:3001",
    )
    entries = body["scenarios"]
    # 1 primary + 6 BGP metrics * 2 peers + 1 UPDOWN log
    assert len(entries) == 1 + 6 * len(two_peers) + 1
    expected_metrics = {
        "bgp_oper_state",
        "bgp_neighbor_state",
        "bgp_prefixes_accepted",
        "bgp_received_routes",
        "bgp_sent_routes",
        "bgp_active_routes",
    }
    for peer in two_peers:
        per_peer = [e for e in entries if e["id"].endswith(peer.address.replace(".", "_"))]
        assert {e["name"] for e in per_peer} == expected_metrics


def test_gated_entries_carry_while_and_delay_clauses(two_peers: list[Peer]) -> None:
    body = _build_cascade(
        device="srl1",
        interface="ethernet-1/1",
        peers=two_peers,
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        prom_url="http://prom:9090/api/v1/write",
        loki_url="http://loki:3001",
    )
    gated = [e for e in body["scenarios"] if e["id"] != "primary_flap"]
    assert gated, "expected at least one gated entry"
    for entry in gated:
        assert entry["while"] == {"ref": "primary_flap", "op": "<", "value": 1}
        assert entry["delay"] == {"open": "10s", "close": "0s"}


def test_no_peers_drops_bgp_entries_but_keeps_flap_and_log() -> None:
    body = _build_cascade(
        device="srl1",
        interface="ethernet-1/99",
        peers=[],
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        prom_url="http://prom:9090/api/v1/write",
        loki_url="http://loki:3001",
    )
    ids = {e["id"] for e in body["scenarios"]}
    assert ids == {"primary_flap", "updown_logs_down"}


def test_defaults_carry_device_pipeline_and_sinks(two_peers: list[Peer]) -> None:
    body = _build_cascade(
        device="srl1",
        interface="ethernet-1/1",
        peers=two_peers,
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        prom_url="http://prom:9090/api/v1/write",
        loki_url="http://loki:3001",
    )
    defaults = body["defaults"]
    assert defaults["duration"] == "4m"
    assert defaults["sink"] == {
        "type": "remote_write",
        "url": "http://prom:9090/api/v1/write",
    }
    assert defaults["labels"]["device"] == "srl1"
    assert defaults["labels"]["pipeline"] == "direct"
    assert defaults["labels"]["source"] == "workshop-cascade"


def test_srl2_pipeline_label_is_telegraf() -> None:
    body = _build_cascade(
        device="srl2",
        interface="ethernet-1/1",
        peers=[Peer(address="10.1.2.1", asn="65101")],
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        prom_url="http://prom:9090/api/v1/write",
        loki_url="http://loki:3001",
    )
    assert body["defaults"]["labels"]["pipeline"] == "telegraf"


def test_srl2_bgp_entries_carry_telegraf_labels() -> None:
    body = _build_cascade(
        device="srl2",
        interface="ethernet-1/1",
        peers=[Peer(address="10.1.2.1", asn="65101")],
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        prom_url="http://prom:9090/api/v1/write",
        loki_url="http://loki:3001",
    )
    bgp_entry = next(e for e in body["scenarios"] if e["name"].startswith("bgp_"))
    for key in ("host", "instance", "job"):
        assert key in bgp_entry["labels"]
        assert key not in body["defaults"]["labels"]


def test_log_entry_targets_loki_and_carries_interface_label(two_peers: list[Peer]) -> None:
    body = _build_cascade(
        device="srl1",
        interface="ethernet-1/1",
        peers=two_peers,
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        prom_url="http://prom:9090/api/v1/write",
        loki_url="http://loki:3001",
    )
    log_entry = next(e for e in body["scenarios"] if e["id"] == "updown_logs_down")
    assert log_entry["sink"] == {"type": "loki", "url": "http://loki:3001"}
    assert log_entry["labels"]["interface"] == "ethernet-1/1"
    assert log_entry["signal_type"] == "logs"
    assert log_entry["log_generator"]["type"] == "template"
