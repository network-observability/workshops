"""Tests for the autocon5 flap-interface cascade body builder."""

from __future__ import annotations

import pytest
from autocon5_workshop.flap import _build_cascade, _label_present
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
        "enum": "oper_state",
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
    # 1 primary + 6 BGP metrics * N peers + 2 gated octets + 1 UPDOWN log
    assert len(entries) == 1 + 6 * len(two_peers) + 2 + 1
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


def test_gated_bgp_entries_open_on_oper_state_down(two_peers: list[Peer]) -> None:
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
    bgp_entries = [e for e in body["scenarios"] if e["name"].startswith("bgp_")]
    log_entries = [e for e in body["scenarios"] if e["id"] == "updown_logs_down"]
    for entry in bgp_entries + log_entries:
        assert entry["while"] == {"ref": "primary_flap", "op": ">", "value": 1}
        assert entry["delay"]["open"] == "10s"


def test_gated_octet_entries_open_on_oper_state_up(two_peers: list[Peer]) -> None:
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
    octet_entries = [
        e for e in body["scenarios"] if e["name"].startswith("interface_") and e["name"].endswith("_octets")
    ]
    assert {e["name"] for e in octet_entries} == {"interface_in_octets", "interface_out_octets"}
    for entry in octet_entries:
        # Octets tick during the UP phase and freeze during DOWN.
        assert entry["while"] == {"ref": "primary_flap", "op": "<", "value": 2}
        assert entry["delay"]["close"]["snap_to"] is None


def test_gated_bgp_entries_snap_to_established_baseline(two_peers: list[Peer]) -> None:
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
    expected_snap_to = {
        "bgp_oper_state": 1.0,
        "bgp_neighbor_state": 1.0,
        "bgp_prefixes_accepted": 10.0,
        "bgp_received_routes": 10.0,
        "bgp_sent_routes": 10.0,
        "bgp_active_routes": 10.0,
    }
    bgp_entries = [e for e in body["scenarios"] if e["name"].startswith("bgp_")]
    assert bgp_entries, "expected at least one BGP entry"
    for entry in bgp_entries:
        close = entry["delay"]["close"]
        assert close["duration"] == "0s"
        assert close["snap_to"] == expected_snap_to[entry["name"]]


def test_log_entry_keeps_bare_close_duration(two_peers: list[Peer]) -> None:
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
    assert log_entry["delay"]["close"] == "0s"


def test_no_peers_drops_bgp_entries_but_keeps_flap_octets_and_log() -> None:
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
    assert ids == {
        "primary_flap",
        "interface_in_octets_gated",
        "interface_out_octets_gated",
        "updown_logs_down",
    }


def test_defaults_carry_only_device_label(two_peers: list[Peer]) -> None:
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
    assert defaults["labels"] == {"device": "srl1"}


def test_metric_entries_carry_telegraf_provenance(two_peers: list[Peer]) -> None:
    # strip_scrape_provenance=False keeps instance/job in the cascade body;
    # the production path with telegraf routing flips this to True so the
    # provenance is added by Prom at scrape time instead.
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
        strip_scrape_provenance=False,
    )
    metric_entries = [e for e in body["scenarios"] if e["signal_type"] == "metrics"]
    assert metric_entries
    for entry in metric_entries:
        labels = entry["labels"]
        assert labels["pipeline"] == "telegraf"
        assert labels["collection_type"] == "gnmi"
        assert labels["instance"] == "telegraf-srl1:9005"
        assert labels["job"] == "telegraf-srl1"


def test_strip_scrape_provenance_removes_instance_and_job(two_peers: list[Peer]) -> None:
    # When routing through the telegraf:1316 listener, Prom will add
    # instance/job at scrape time from its own config — the cascade body
    # must NOT set them or Prom relabels them to exported_instance/_job
    # and we get a parallel series alongside baseline.
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
        strip_scrape_provenance=True,
    )
    metric_entries = [e for e in body["scenarios"] if e["signal_type"] == "metrics"]
    for entry in metric_entries:
        assert "instance" not in entry["labels"]
        assert "job" not in entry["labels"]


def test_srl2_metric_entries_carry_snmp_collection_type() -> None:
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
        strip_scrape_provenance=False,
    )
    bgp_entry = next(e for e in body["scenarios"] if e["name"].startswith("bgp_"))
    assert bgp_entry["labels"]["pipeline"] == "telegraf"
    assert bgp_entry["labels"]["collection_type"] == "snmp"
    assert bgp_entry["labels"]["instance"] == "telegraf-srl2:9005"
    assert bgp_entry["labels"]["job"] == "telegraf-srl2"


def test_log_entry_keeps_pipeline_direct_not_telegraf(two_peers: list[Peer]) -> None:
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
    assert log_entry["labels"]["pipeline"] == "direct"
    for key in ("host", "instance", "job", "collection_type"):
        assert key not in log_entry["labels"]


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


# --- flap_cleanup restore body --------------------------------------------------


def test_restore_body_srl1_covers_oper_state_octets_and_per_peer_bgp() -> None:
    body = _restore_body("srl1", "ethernet-1/1", [("10.1.2.2", "65102")])
    assert body is not None
    names = [s["name"] for s in body["scenarios"]]
    # 1 oper_state + 2 octets (interface) + 6 BGP metrics * 1 peer = 9
    assert len(names) == 9
    assert "srl_interface_oper_state" in names
    assert "srl_interface_in_octets" in names
    assert "srl_interface_out_octets" in names
    assert names.count("srl_bgp_oper_state") == 1
    assert names.count("srl_bgp_neighbor_state") == 1


def test_restore_body_srl1_bgp_labels_use_peer_address_and_asn() -> None:
    body = _restore_body("srl1", "ethernet-1/1", [("10.1.2.2", "65102"), ("10.1.7.2", "65102")])
    assert body is not None
    bgp_entries = [s for s in body["scenarios"] if s["name"].startswith("srl_bgp_")]
    # 6 metrics per peer * 2 peers
    assert len(bgp_entries) == 12
    addrs = {s["labels"]["peer_address"] for s in bgp_entries}
    assert addrs == {"10.1.2.2", "10.1.7.2"}
    for entry in bgp_entries:
        labels = entry["labels"]
        assert labels["source"] == "srl1"
        assert labels["neighbor_asn"] == "65102"
        assert labels["name"] == "default"
        assert labels["afi_safi_name"] == "ipv4-unicast"
        assert labels["collection_type"] == "gnmi"


def test_restore_body_srl2_uses_snmp_label_keys() -> None:
    body = _restore_body("srl2", "ethernet-1/1", [("10.1.2.1", "65101")])
    assert body is not None
    intf = next(s for s in body["scenarios"] if s["name"] == "ifOperStatus")
    assert intf["labels"]["agent_host"] == "srl2"
    assert intf["labels"]["ifDescr"] == "ethernet-1/1"
    bgp = next(s for s in body["scenarios"] if s["name"] == "cbgpPeerOperStatus")
    assert bgp["labels"]["bgpPeerRemoteAddr"] == "10.1.2.1"
    assert bgp["labels"]["bgpPeerRemoteAs"] == "65101"


def test_restore_body_no_peers_still_restores_interface_baseline() -> None:
    body = _restore_body("srl1", "ethernet-1/1", [])
    assert body is not None
    names = {s["name"] for s in body["scenarios"]}
    assert names == {"srl_interface_oper_state", "srl_interface_in_octets", "srl_interface_out_octets"}


# --- label-token word boundary -----------------------------------------------


def test_label_present_does_not_match_substring_interfaces() -> None:
    # The bug: `name="ethernet-1/1"` is a substring of `name="ethernet-1/10"`
    # and `name="ethernet-1/11"`. The Prometheus exposition format always
    # terminates a label with `,` or `}`, so we require one of those.
    one = 'srl_interface_in_octets{collection_type="gnmi",name="ethernet-1/1",source="srl1"} 100\n'
    ten = 'srl_interface_in_octets{collection_type="gnmi",name="ethernet-1/10",source="srl1"} 200\n'
    eleven = 'srl_interface_in_octets{collection_type="gnmi",name="ethernet-1/11",source="srl1"} 0\n'
    assert _label_present(one, "name", "ethernet-1/1") is True
    assert _label_present(ten, "name", "ethernet-1/1") is False
    assert _label_present(eleven, "name", "ethernet-1/1") is False


def test_label_present_handles_trailing_label() -> None:
    # Label is the LAST one before the closing brace.
    line = 'srl_bgp_oper_state{collection_type="gnmi",source="srl1",peer_address="10.1.2.2"} 1\n'
    assert _label_present(line, "peer_address", "10.1.2.2") is True
    assert _label_present(line, "peer_address", "10.1.2.22") is False
