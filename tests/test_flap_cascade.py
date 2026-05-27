"""Tests for the autocon5 flap-interface inversion-pattern cascade builder.

The inversion pattern (sonda 1.13.1 + PR #438 docs) replaces DELETE-and-
replace: baselines stay POSTed with `while: scenario_name=<cascade>` and
`if_unresolved: open`; flap-interface POSTs short-lived cascade scenarios
that pause the matching baseline via cross-POST resolution. See
`workshops/autocon5/src/autocon5_workshop/flap.py` for the wiring.
"""

from __future__ import annotations

import pytest
from autocon5_workshop.flap import (
    _BROKEN_PEERS,
    _DEVICE_CONFIG,
    _build_bgp_cascade,
    _build_interface_cascade,
    _parse_duration_secs,
    bgp_cascade_name,
    interface_cascade_name,
)
from autocon5_workshop.flap_topology import Peer


@pytest.fixture
def two_peers() -> list[Peer]:
    return [
        Peer(address="10.1.2.2", asn="65102"),
        Peer(address="10.1.7.2", asn="65102"),
    ]


def _entries_by_id(body: dict) -> dict[str, dict]:
    return {e["id"]: e for e in body["scenarios"]}


def _interface_body(device: str, interface: str = "ethernet-1/1") -> dict:
    return _build_interface_cascade(
        device=device,
        interface=interface,
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
        loki_url="http://loki:3001",
        in_octet_start=5_000_000.0,
        out_octet_start=2_500_000.0,
    )


def _bgp_body(device: str, peer: Peer) -> dict:
    return _build_bgp_cascade(
        device=device,
        peer=peer,
        duration="4m",
        up_duration="30s",
        down_duration="60s",
        cascade_delay="10s",
    )


# --- scenario_name helpers (must match what the baseline YAMLs reference) ---


def test_interface_cascade_name_format() -> None:
    assert interface_cascade_name("srl1", "ethernet-1/1") == "autocon5-cascade-srl1-intf-ethernet-1-1"
    assert interface_cascade_name("srl2", "ethernet-1/10") == "autocon5-cascade-srl2-intf-ethernet-1-10"


def test_bgp_cascade_name_format() -> None:
    assert bgp_cascade_name("srl1", "10.1.2.2") == "autocon5-cascade-srl1-bgp-10-1-2-2"
    assert bgp_cascade_name("srl2", "10.1.7.1") == "autocon5-cascade-srl2-bgp-10-1-7-1"


# --- interface cascade body ----------------------------------------------------


def test_interface_cascade_has_signal_oper_state_octets_and_log() -> None:
    body = _interface_body("srl1")
    entries = _entries_by_id(body)
    assert set(entries) == {
        "cascade_active",
        "cascade_oper_state",
        "cascade_in_octets",
        "cascade_out_octets",
        "updown_logs_down",
    }


def test_interface_cascade_scenario_name_matches_helper() -> None:
    body = _interface_body("srl1", interface="ethernet-1/10")
    assert body["scenario_name"] == interface_cascade_name("srl1", "ethernet-1/10")


def test_interface_cascade_signal_is_flap_0_1() -> None:
    body = _interface_body("srl1")
    sig = _entries_by_id(body)["cascade_active"]
    assert sig["name"] == "cascade_active"
    assert sig["generator"] == {
        "type": "flap",
        "up_duration": "30s",
        "down_duration": "60s",
        "up_value": 0,
        "down_value": 1,
    }
    assert "while" not in sig


def test_interface_cascade_overrides_are_gated_on_signal() -> None:
    body = _interface_body("srl1")
    entries = _entries_by_id(body)
    for eid in ("cascade_oper_state", "cascade_in_octets", "cascade_out_octets"):
        entry = entries[eid]
        assert entry["while"] == {"ref": "cascade_active", "op": ">", "value": 0}


def test_interface_cascade_oper_state_emits_down_value_srl1() -> None:
    body = _interface_body("srl1")
    entry = _entries_by_id(body)["cascade_oper_state"]
    assert entry["name"] == "srl_interface_oper_state"
    assert entry["generator"] == {"type": "constant", "value": 2.0}
    assert entry["labels"]["name"] == "ethernet-1/1"
    assert entry["labels"]["collection_type"] == "gnmi"


def test_interface_cascade_oper_state_uses_srl2_metric_name() -> None:
    body = _interface_body("srl2", interface="ethernet-1/1")
    entry = _entries_by_id(body)["cascade_oper_state"]
    assert entry["name"] == "ifOperStatus"
    assert entry["labels"]["ifDescr"] == "ethernet-1/1"
    assert entry["labels"]["collection_type"] == "snmp"


def test_interface_cascade_octets_seeded_from_prom_value() -> None:
    body = _interface_body("srl1")
    in_entry = _entries_by_id(body)["cascade_in_octets"]
    out_entry = _entries_by_id(body)["cascade_out_octets"]
    assert in_entry["generator"] == {"type": "constant", "value": 5_000_000.0}
    assert out_entry["generator"] == {"type": "constant", "value": 2_500_000.0}
    assert in_entry["metric_type"] == "counter"
    assert out_entry["metric_type"] == "counter"


def test_interface_cascade_defaults_carry_only_device_label_srl1() -> None:
    body = _interface_body("srl1")
    defaults = body["defaults"]
    assert defaults["duration"] == "4m"
    assert defaults["rate"] == 1
    assert defaults["labels"] == {"source": "srl1"}


def test_interface_cascade_defaults_carry_only_device_label_srl2() -> None:
    body = _interface_body("srl2")
    defaults = body["defaults"]
    assert defaults["labels"] == {"agent_host": "srl2"}


def test_interface_cascade_log_entry_targets_loki_with_device_label() -> None:
    body = _interface_body("srl1")
    log = _entries_by_id(body)["updown_logs_down"]
    assert log["signal_type"] == "logs"
    assert log["sink"] == {"type": "loki", "url": "http://loki:3001"}
    assert log["labels"]["device"] == "srl1"
    assert log["labels"]["interface"] == "ethernet-1/1"
    assert log["labels"]["vendor_facility_process"] == "UPDOWN"
    assert log["while"] == {"ref": "cascade_active", "op": ">", "value": 0}


# --- BGP cascade body ----------------------------------------------------------


def test_bgp_cascade_scenario_name_matches_helper() -> None:
    peer = Peer(address="10.1.2.2", asn="65102")
    body = _bgp_body("srl1", peer)
    assert body["scenario_name"] == bgp_cascade_name("srl1", "10.1.2.2")


def test_bgp_cascade_signal_is_phase_shifted_srl1() -> None:
    body = _bgp_body("srl1", Peer(address="10.1.2.2", asn="65102"))
    sig = _entries_by_id(body)["cascade_active"]
    # BGP up_duration = primary_up + cascade_delay = 30 + 10 = 40s
    # BGP down_duration = primary_down - cascade_delay = 60 - 10 = 50s
    assert sig["generator"]["up_duration"] == "40s"
    assert sig["generator"]["down_duration"] == "50s"


def test_bgp_cascade_emits_all_six_bgp_metrics_srl1() -> None:
    body = _bgp_body("srl1", Peer(address="10.1.2.2", asn="65102"))
    metric_names = {e["name"] for e in body["scenarios"] if e["name"] != "cascade_active"}
    assert metric_names == {
        "srl_bgp_oper_state",
        "srl_bgp_neighbor_state",
        "srl_bgp_prefixes_accepted",
        "srl_bgp_received_routes",
        "srl_bgp_sent_routes",
        "srl_bgp_active_routes",
    }


def test_bgp_cascade_emits_all_six_bgp_metrics_srl2() -> None:
    body = _bgp_body("srl2", Peer(address="10.1.2.1", asn="65101"))
    metric_names = {e["name"] for e in body["scenarios"] if e["name"] != "cascade_active"}
    assert metric_names == {
        "cbgpPeerOperStatus",
        "bgpPeerState",
        "cbgpPeerAcceptedPrefixes",
        "bgpPeerInPrefixes",
        "bgpPeerOutPrefixes",
        "cbgpPeerActivePrefixes",
    }


def test_bgp_cascade_neighbor_state_drops_to_idle_for_states_panel() -> None:
    """`bgp_neighbor_state` (after telegraf rename) maps 1=ESTABLISHED, 2=IDLE.
    Cascade must emit 2 so the BGP States panel turns red.
    """
    for device, metric in (("srl1", "srl_bgp_neighbor_state"), ("srl2", "bgpPeerState")):
        body = _bgp_body(device, Peer(address="10.1.2.2", asn="65102"))
        entry = next(e for e in body["scenarios"] if e["name"] == metric)
        assert entry["generator"]["value"] == 2.0


def test_bgp_cascade_labels_include_peer_asn_and_afi() -> None:
    body = _bgp_body("srl1", Peer(address="10.1.2.2", asn="65102"))
    bgp_entries = [e for e in body["scenarios"] if e["name"] != "cascade_active"]
    for entry in bgp_entries:
        labels = entry["labels"]
        assert labels["peer_address"] == "10.1.2.2"
        assert labels["neighbor_asn"] == "65102"
        assert labels["afi_safi_name"] == "ipv4-unicast"
        assert labels["name"] == "default"
        assert labels["collection_type"] == "gnmi"


def test_bgp_cascade_overrides_are_gated_on_signal() -> None:
    body = _bgp_body("srl1", Peer(address="10.1.2.2", asn="65102"))
    bgp_entries = [e for e in body["scenarios"] if e["name"] != "cascade_active"]
    for entry in bgp_entries:
        assert entry["while"] == {"ref": "cascade_active", "op": ">", "value": 0}


# --- topology / broken-peer awareness ----------------------------------------


def test_broken_peers_set_matches_lab_vars() -> None:
    assert {("srl1", "10.1.99.2"), ("srl2", "10.1.11.1")} == set(_BROKEN_PEERS)


def test_device_config_has_both_supported_devices() -> None:
    assert set(_DEVICE_CONFIG) == {"srl1", "srl2"}


def test_device_config_srl1_has_gnmi_shape() -> None:
    cfg = _DEVICE_CONFIG["srl1"]
    assert cfg["device_label"] == "source"
    assert cfg["interface_label"] == "name"
    assert cfg["peer_label"] == "peer_address"
    assert cfg["collection_type"] == "gnmi"
    assert "srl_bgp_oper_state" in cfg["bgp_metrics"]


def test_device_config_srl2_has_snmp_shape() -> None:
    cfg = _DEVICE_CONFIG["srl2"]
    assert cfg["device_label"] == "agent_host"
    assert cfg["interface_label"] == "ifDescr"
    assert cfg["peer_label"] == "bgpPeerRemoteAddr"
    assert cfg["collection_type"] == "snmp"
    assert "cbgpPeerOperStatus" in cfg["bgp_metrics"]


# --- duration parser --------------------------------------------------------


@pytest.mark.parametrize(
    ("input", "expected"),
    [
        ("500ms", 0.5),
        ("30s", 30.0),
        ("4m", 240.0),
        ("1h", 3600.0),
    ],
)
def test_parse_duration_secs(input: str, expected: float) -> None:
    assert _parse_duration_secs(input) == expected
