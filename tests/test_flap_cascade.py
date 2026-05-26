"""Tests for the autocon5 flap-interface cascade body builder."""

from __future__ import annotations

import pytest
from autocon5_workshop.flap import _build_cascade
from autocon5_workshop.flap_cleanup import _restore_body
from autocon5_workshop.flap_topology import Peer


@pytest.fixture
def two_peers() -> list[Peer]:
    return [
        Peer(address="10.1.2.2", asn="65102"),
        Peer(address="10.1.7.2", asn="65102"),
    ]


def _entries_by_id(body: dict) -> dict[str, dict]:
    return {e["id"]: e for e in body["scenarios"]}


def _build(device: str, peers: list[Peer], interface: str = "ethernet-1/1") -> dict:
    return _build_cascade(
        device=device,
        interface=interface,
        peers=peers,
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        loki_url="http://loki:3001",
    )


def test_cascade_has_primary_flap_and_one_log_entry(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    assert body["version"] == 2
    entries = _entries_by_id(body)
    assert "primary_flap" in entries
    assert "updown_logs_down" in entries
    primary = entries["primary_flap"]
    assert primary["name"] == "srl_interface_oper_state"
    assert primary["generator"] == {
        "type": "flap",
        "up_duration": "30s",
        "down_duration": "60s",
        "enum": "oper_state",
    }
    assert "while" not in primary
    assert "delay" not in primary


def test_cascade_emits_six_bgp_metrics_per_peer_srl1(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    entries = body["scenarios"]
    expected_bgp = {
        "srl_bgp_oper_state",
        "srl_bgp_neighbor_state",
        "srl_bgp_prefixes_accepted",
        "srl_bgp_received_routes",
        "srl_bgp_sent_routes",
        "srl_bgp_active_routes",
    }
    # 1 primary flap + 6 BGP metrics per peer + 2 gated octets + 1 UPDOWN log
    assert len(entries) == 1 + 6 * len(two_peers) + 2 + 1
    for peer in two_peers:
        per_peer = [e for e in entries if e["id"].endswith(peer.address.replace(".", "_"))]
        assert {e["name"] for e in per_peer} == expected_bgp


def test_cascade_emits_six_bgp_metrics_per_peer_srl2() -> None:
    peer = Peer(address="10.1.2.1", asn="65101")
    body = _build("srl2", [peer])
    entries = body["scenarios"]
    expected_bgp = {
        "cbgpPeerOperStatus",
        "bgpPeerState",
        "cbgpPeerAcceptedPrefixes",
        "bgpPeerInPrefixes",
        "bgpPeerOutPrefixes",
        "cbgpPeerActivePrefixes",
    }
    per_peer = [e for e in entries if e["id"].endswith(peer.address.replace(".", "_"))]
    assert {e["name"] for e in per_peer} == expected_bgp


def test_gated_octet_entries_use_step_and_while_clause(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    entries = _entries_by_id(body)
    in_entry = entries["interface_in_octets_gated"]
    out_entry = entries["interface_out_octets_gated"]
    assert in_entry["name"] == "srl_interface_in_octets"
    assert out_entry["name"] == "srl_interface_out_octets"
    for entry in (in_entry, out_entry):
        assert entry["metric_type"] == "counter"
        assert entry["generator"]["type"] == "step"
        assert entry["while"] == {"ref": "primary_flap", "op": "<", "value": 2}
        assert entry["delay"]["open"] == "10s"
        assert entry["delay"]["close"] == {"duration": "0s", "snap_to": None}


def test_gated_octet_entries_srl2_use_snmp_metric_names() -> None:
    body = _build("srl2", [Peer(address="10.1.2.1", asn="65101")])
    entries = _entries_by_id(body)
    assert entries["interface_in_octets_gated"]["name"] == "ifHCInOctets"
    assert entries["interface_out_octets_gated"]["name"] == "ifHCOutOctets"


def test_log_entry_keeps_bare_close_duration(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    log_entry = next(e for e in body["scenarios"] if e["id"] == "updown_logs_down")
    assert log_entry["delay"]["close"] == "0s"


def test_log_entry_carries_device_label_for_dashboard_match(two_peers: list[Peer]) -> None:
    for device in ("srl1", "srl2"):
        body = _build(device, two_peers)
        log_entry = next(e for e in body["scenarios"] if e["id"] == "updown_logs_down")
        assert log_entry["labels"]["device"] == device


def test_bgp_neighbor_state_flips_to_idle_so_states_panel_turns_red(two_peers: list[Peer]) -> None:
    for device, neighbor_metric in (("srl1", "srl_bgp_neighbor_state"), ("srl2", "bgpPeerState")):
        body = _build(device, two_peers)
        entry = next(e for e in body["scenarios"] if e["name"] == neighbor_metric)
        gen = entry["generator"]
        assert gen["type"] == "flap"
        assert gen["up_value"] == 1.0
        assert gen["down_value"] == 2.0


def test_no_peers_drops_bgp_entries_but_keeps_flap_octets_and_log() -> None:
    body = _build("srl1", peers=[], interface="ethernet-1/99")
    ids = {e["id"] for e in body["scenarios"]}
    assert ids == {
        "primary_flap",
        "updown_logs_down",
        "interface_in_octets_gated",
        "interface_out_octets_gated",
    }


def test_defaults_carry_only_device_label_srl1(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    defaults = body["defaults"]
    assert defaults["duration"] == "4m"
    assert defaults["rate"] == 1
    assert "encoder" not in defaults
    assert "sink" not in defaults
    assert defaults["labels"] == {"source": "srl1"}


def test_defaults_carry_only_device_label_srl2() -> None:
    body = _build("srl2", [Peer(address="10.1.2.1", asn="65101")])
    defaults = body["defaults"]
    assert "encoder" not in defaults
    assert "sink" not in defaults
    assert defaults["labels"] == {"agent_host": "srl2"}


def test_primary_flap_labels_match_baseline_shape_srl1(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    primary = _entries_by_id(body)["primary_flap"]
    assert primary["labels"] == {"name": "ethernet-1/1", "collection_type": "gnmi"}


def test_primary_flap_labels_match_baseline_shape_srl2() -> None:
    body = _build("srl2", [Peer(address="10.1.2.1", asn="65101")])
    primary = _entries_by_id(body)["primary_flap"]
    assert primary["labels"] == {"ifDescr": "ethernet-1/1", "collection_type": "snmp"}


def test_bgp_entry_labels_match_baseline_shape_srl1(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    bgp_entries = [e for e in body["scenarios"] if e["name"].startswith("srl_bgp_")]
    assert bgp_entries
    for entry in bgp_entries:
        labels = entry["labels"]
        assert set(labels.keys()) == {
            "peer_address",
            "neighbor_asn",
            "afi_safi_name",
            "name",
            "collection_type",
        }
        assert labels["afi_safi_name"] == "ipv4-unicast"
        assert labels["name"] == "default"
        assert labels["collection_type"] == "gnmi"


def test_bgp_entry_labels_match_baseline_shape_srl2() -> None:
    peer = Peer(address="10.1.2.1", asn="65101")
    body = _build("srl2", [peer])
    bgp_entry = next(e for e in body["scenarios"] if e["name"] == "bgpPeerState")
    assert bgp_entry["labels"] == {
        "bgpPeerRemoteAddr": "10.1.2.1",
        "bgpPeerRemoteAs": "65101",
        "afi_safi_name": "ipv4-unicast",
        "name": "default",
        "collection_type": "snmp",
    }


def test_metric_entries_have_no_scrape_provenance(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    metric_entries = [e for e in body["scenarios"] if e["signal_type"] == "metrics"]
    assert metric_entries
    forbidden = {"instance", "job", "pipeline", "host"}
    for entry in metric_entries:
        assert forbidden.isdisjoint(entry["labels"].keys())


def test_log_entry_keeps_pipeline_direct(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    log_entry = next(e for e in body["scenarios"] if e["id"] == "updown_logs_down")
    assert log_entry["labels"]["pipeline"] == "direct"


def test_log_entry_targets_loki_and_carries_interface_label(two_peers: list[Peer]) -> None:
    body = _build("srl1", two_peers)
    log_entry = next(e for e in body["scenarios"] if e["id"] == "updown_logs_down")
    assert log_entry["sink"] == {"type": "loki", "url": "http://loki:3001"}
    assert log_entry["labels"]["interface"] == "ethernet-1/1"
    assert log_entry["signal_type"] == "logs"
    assert log_entry["log_generator"]["type"] == "template"


def _bgp_values_by_metric(body: dict, peer_addr: str, addr_label_key: str) -> dict[str, float]:
    return {
        e["name"]: e["generator"]["value"]
        for e in body["scenarios"]
        if e["signal_type"] == "metrics"
        and e["labels"].get(addr_label_key) == peer_addr
        and e["name"]
        not in {
            "srl_interface_oper_state",
            "srl_interface_in_octets",
            "srl_interface_out_octets",
            "ifOperStatus",
            "ifHCInOctets",
            "ifHCOutOctets",
        }
    }


def test_restore_body_srl1_broken_peer_carries_override_values() -> None:
    body = _restore_body(
        "srl1",
        "ethernet-1/11",
        [("10.1.99.2", "65102")],
    )
    assert body is not None
    values = _bgp_values_by_metric(body, "10.1.99.2", "peer_address")
    assert values["srl_bgp_oper_state"] == 5.0
    assert values["srl_bgp_neighbor_state"] == 4.0
    assert values["srl_bgp_received_routes"] == 0.0
    assert values["srl_bgp_prefixes_accepted"] == 0.0
    # Metrics with no override fall through to baseline defaults.
    assert values["srl_bgp_sent_routes"] == 10.0
    assert values["srl_bgp_active_routes"] == 10.0


def test_restore_body_srl1_healthy_peer_keeps_default_values() -> None:
    body = _restore_body(
        "srl1",
        "ethernet-1/1",
        [("10.1.2.2", "65102")],
    )
    assert body is not None
    values = _bgp_values_by_metric(body, "10.1.2.2", "peer_address")
    assert values["srl_bgp_oper_state"] == 1.0
    assert values["srl_bgp_neighbor_state"] == 1.0
    assert values["srl_bgp_prefixes_accepted"] == 10.0
    assert values["srl_bgp_received_routes"] == 10.0
    assert values["srl_bgp_sent_routes"] == 10.0
    assert values["srl_bgp_active_routes"] == 10.0


def test_restore_body_srl2_broken_peer_carries_override_values() -> None:
    body = _restore_body(
        "srl2",
        "ethernet-1/11",
        [("10.1.11.1", "65101")],
    )
    assert body is not None
    values = _bgp_values_by_metric(body, "10.1.11.1", "bgpPeerRemoteAddr")
    assert values["cbgpPeerOperStatus"] == 5.0
    assert values["bgpPeerState"] == 4.0
    assert values["bgpPeerInPrefixes"] == 0.0
    assert values["cbgpPeerAcceptedPrefixes"] == 0.0
    assert values["bgpPeerOutPrefixes"] == 10.0
    assert values["cbgpPeerActivePrefixes"] == 10.0
