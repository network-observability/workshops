"""Tests for the workshop flap-interface inversion-pattern cascade builder.

The inversion pattern (sonda 1.13.1 + PR #438 docs) replaces DELETE-and-
replace: baselines stay POSTed with `while: scenario_name=<cascade>` and
`if_unresolved: open`; flap-interface POSTs short-lived cascade scenarios
that pause the matching baseline via cross-POST resolution. See each
workshop's `src/<plugin>/flap.py` for the wiring.

Every test runs against each registered workshop plugin, so a rename that
misses a slug fails here.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

PLUGINS = ["autocon5_workshop", "packt_workshop"]

_REPO_ROOT = Path(__file__).resolve().parents[1]

_OCTET_METRICS = {
    "srl1": ("srl_interface_in_octets", "srl_interface_out_octets"),
    "srl2": ("ifHCInOctets", "ifHCOutOctets"),
}


@pytest.fixture(params=PLUGINS)
def plugin(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def slug(plugin: str) -> str:
    return plugin.removesuffix("_workshop")


@pytest.fixture
def flap(plugin: str) -> ModuleType:
    return importlib.import_module(f"{plugin}.flap")


@pytest.fixture
def peer_cls(plugin: str) -> type:
    return importlib.import_module(f"{plugin}.flap_topology").Peer


@pytest.fixture
def two_peers(peer_cls: type) -> list[Any]:
    return [
        peer_cls(address="10.1.2.2", asn="65102"),
        peer_cls(address="10.1.7.2", asn="65102"),
    ]


@pytest.fixture
def interface_body(flap: ModuleType) -> Callable[..., dict]:
    def _body(device: str, interface: str = "ethernet-1/1") -> dict:
        return flap._build_interface_cascade(
            device=device,
            interface=interface,
            duration="4m",
            up_duration="30s",
            down_duration="60s",
            cascade_delay="10s",
            loki_url="http://loki:3001",
        )

    return _body


@pytest.fixture
def bgp_body(flap: ModuleType) -> Callable[..., dict]:
    def _body(device: str, peer: Any) -> dict:
        return flap._build_bgp_cascade(
            device=device,
            peer=peer,
            duration="4m",
            up_duration="30s",
            down_duration="60s",
            cascade_delay="10s",
        )

    return _body


@pytest.fixture
def baseline_entries(slug: str) -> Callable[[str], list[dict]]:
    catalog = _REPO_ROOT / "workshops" / slug / "sonda" / "catalog"

    def _entries(device: str) -> list[dict]:
        return yaml.safe_load((catalog / f"{device}-metrics.yaml").read_text())["scenarios"]

    return _entries


def _entries_by_id(body: dict) -> dict[str, dict]:
    return {e["id"]: e for e in body["scenarios"]}


# --- scenario_name helpers (must match what the baseline YAMLs reference) ---


def test_interface_cascade_name_format(flap: ModuleType, slug: str) -> None:
    assert flap.interface_cascade_name("srl1", "ethernet-1/1") == f"{slug}-cascade-srl1-intf-ethernet-1-1"
    assert flap.interface_cascade_name("srl2", "ethernet-1/10") == f"{slug}-cascade-srl2-intf-ethernet-1-10"


def test_bgp_cascade_name_format(flap: ModuleType, slug: str) -> None:
    assert flap.bgp_cascade_name("srl1", "10.1.2.2") == f"{slug}-cascade-srl1-bgp-10-1-2-2"
    assert flap.bgp_cascade_name("srl2", "10.1.7.1") == f"{slug}-cascade-srl2-bgp-10-1-7-1"


# --- interface cascade body ----------------------------------------------------


def test_interface_cascade_has_signal_oper_state_and_log(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl1")
    entries = _entries_by_id(body)
    assert set(entries) == {
        "cascade_active",
        "cascade_oper_state",
        "updown_logs_down",
    }


def test_interface_cascade_scenario_name_matches_helper(interface_body: Callable[..., dict], flap: ModuleType) -> None:
    body = interface_body("srl1", interface="ethernet-1/10")
    assert body["scenario_name"] == flap.interface_cascade_name("srl1", "ethernet-1/10")


def test_interface_cascade_signal_is_flap_0_1(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl1")
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


def test_interface_cascade_oper_state_is_gated_on_signal(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl1")
    entries = _entries_by_id(body)
    entry = entries["cascade_oper_state"]
    assert entry["while"] == {"ref": "cascade_active", "op": ">", "value": 0}


def test_interface_cascade_oper_state_emits_down_value_srl1(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl1")
    entry = _entries_by_id(body)["cascade_oper_state"]
    assert entry["name"] == "srl_interface_oper_state"
    assert entry["generator"] == {"type": "constant", "value": 2.0}
    assert entry["labels"]["name"] == "ethernet-1/1"
    assert entry["labels"]["collection_type"] == "gnmi"


def test_interface_cascade_oper_state_uses_srl2_metric_name(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl2", interface="ethernet-1/1")
    entry = _entries_by_id(body)["cascade_oper_state"]
    assert entry["name"] == "ifOperStatus"
    assert entry["labels"]["ifDescr"] == "ethernet-1/1"
    assert entry["labels"]["collection_type"] == "snmp"


def test_interface_cascade_emits_no_octet_entries(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl1")
    assert [e["id"] for e in body["scenarios"] if "octet" in e["id"]] == []


def test_interface_cascade_defaults_carry_only_device_label_srl1(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl1")
    defaults = body["defaults"]
    assert defaults["duration"] == "4m"
    assert defaults["rate"] == 1
    assert defaults["labels"] == {"source": "srl1"}


def test_interface_cascade_defaults_carry_only_device_label_srl2(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl2")
    defaults = body["defaults"]
    assert defaults["labels"] == {"agent_host": "srl2"}


def test_interface_cascade_log_entry_targets_loki_with_device_label(interface_body: Callable[..., dict]) -> None:
    body = interface_body("srl1")
    log = _entries_by_id(body)["updown_logs_down"]
    assert log["signal_type"] == "logs"
    assert log["sink"] == {"type": "loki", "url": "http://loki:3001"}
    assert log["labels"]["device"] == "srl1"
    assert log["labels"]["interface"] == "ethernet-1/1"
    assert log["labels"]["vendor_facility_process"] == "UPDOWN"
    assert log["while"] == {"ref": "cascade_active", "op": ">", "value": 0}


# --- BGP cascade body ----------------------------------------------------------


def test_bgp_cascade_scenario_name_matches_helper(
    bgp_body: Callable[..., dict], peer_cls: type, flap: ModuleType
) -> None:
    peer = peer_cls(address="10.1.2.2", asn="65102")
    body = bgp_body("srl1", peer)
    assert body["scenario_name"] == flap.bgp_cascade_name("srl1", "10.1.2.2")


def test_bgp_cascade_signal_is_phase_shifted_srl1(bgp_body: Callable[..., dict], peer_cls: type) -> None:
    body = bgp_body("srl1", peer_cls(address="10.1.2.2", asn="65102"))
    sig = _entries_by_id(body)["cascade_active"]
    # BGP up_duration = primary_up + cascade_delay = 30 + 10 = 40s
    # BGP down_duration = primary_down - cascade_delay = 60 - 10 = 50s
    assert sig["generator"]["up_duration"] == "40s"
    assert sig["generator"]["down_duration"] == "50s"


def test_bgp_cascade_emits_all_six_bgp_metrics_srl1(bgp_body: Callable[..., dict], peer_cls: type) -> None:
    body = bgp_body("srl1", peer_cls(address="10.1.2.2", asn="65102"))
    metric_names = {e["name"] for e in body["scenarios"] if e["name"] != "cascade_active"}
    assert metric_names == {
        "srl_bgp_oper_state",
        "srl_bgp_neighbor_state",
        "srl_bgp_prefixes_accepted",
        "srl_bgp_received_routes",
        "srl_bgp_sent_routes",
        "srl_bgp_active_routes",
    }


def test_bgp_cascade_emits_all_six_bgp_metrics_srl2(bgp_body: Callable[..., dict], peer_cls: type) -> None:
    body = bgp_body("srl2", peer_cls(address="10.1.2.1", asn="65101"))
    metric_names = {e["name"] for e in body["scenarios"] if e["name"] != "cascade_active"}
    assert metric_names == {
        "cbgpPeerOperStatus",
        "bgpPeerState",
        "cbgpPeerAcceptedPrefixes",
        "bgpPeerInPrefixes",
        "bgpPeerOutPrefixes",
        "cbgpPeerActivePrefixes",
    }


def test_bgp_cascade_neighbor_state_drops_to_idle_for_states_panel(
    bgp_body: Callable[..., dict], peer_cls: type
) -> None:
    for device, metric in (("srl1", "srl_bgp_neighbor_state"), ("srl2", "bgpPeerState")):
        body = bgp_body(device, peer_cls(address="10.1.2.2", asn="65102"))
        entry = next(e for e in body["scenarios"] if e["name"] == metric)
        assert entry["generator"]["value"] == 2.0


def test_bgp_cascade_labels_include_peer_asn_and_afi(bgp_body: Callable[..., dict], peer_cls: type) -> None:
    body = bgp_body("srl1", peer_cls(address="10.1.2.2", asn="65102"))
    bgp_entries = [e for e in body["scenarios"] if e["name"] != "cascade_active"]
    for entry in bgp_entries:
        labels = entry["labels"]
        assert labels["peer_address"] == "10.1.2.2"
        assert labels["neighbor_asn"] == "65102"
        assert labels["afi_safi_name"] == "ipv4-unicast"
        assert labels["name"] == "default"
        assert labels["collection_type"] == "gnmi"


def test_bgp_cascade_overrides_are_gated_on_signal(bgp_body: Callable[..., dict], peer_cls: type) -> None:
    body = bgp_body("srl1", peer_cls(address="10.1.2.2", asn="65102"))
    bgp_entries = [e for e in body["scenarios"] if e["name"] != "cascade_active"]
    for entry in bgp_entries:
        assert entry["while"] == {"ref": "cascade_active", "op": ">", "value": 0}


# --- topology / broken-peer awareness ----------------------------------------


def test_broken_peers_set_matches_lab_vars(flap: ModuleType) -> None:
    assert {("srl1", "10.1.99.2"), ("srl2", "10.1.11.1")} == set(flap._BROKEN_PEERS)


def test_device_config_has_both_supported_devices(flap: ModuleType) -> None:
    assert set(flap._DEVICE_CONFIG) == {"srl1", "srl2"}


def test_device_config_srl1_has_gnmi_shape(flap: ModuleType) -> None:
    cfg = flap._DEVICE_CONFIG["srl1"]
    assert cfg["device_label"] == "source"
    assert cfg["interface_label"] == "name"
    assert cfg["peer_label"] == "peer_address"
    assert cfg["collection_type"] == "gnmi"
    assert "srl_bgp_oper_state" in cfg["bgp_metrics"]


def test_device_config_srl2_has_snmp_shape(flap: ModuleType) -> None:
    cfg = flap._DEVICE_CONFIG["srl2"]
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
def test_parse_duration_secs(flap: ModuleType, input: str, expected: float) -> None:
    assert flap._parse_duration_secs(input) == expected


# --- Pattern C: the baseline half of the octet-freeze contract -----------------


@pytest.mark.parametrize("device", ["srl1", "srl2"])
def test_cascade_targetable_interfaces_freeze_octets(
    device: str,
    flap: ModuleType,
    slug: str,
    baseline_entries: Callable[[str], list[dict]],
) -> None:
    """Every interface a cascade can pause must snap its octet counters.

    The cascade emits no octet entries, so a baseline missing `snap_to` drops
    its octet series entirely while the interface is down.
    """
    interface_label = flap._DEVICE_CONFIG[device]["interface_label"]
    targetable = [
        e
        for e in baseline_entries(device)
        if e.get("while", {}).get("scenario_name", "").startswith(f"{slug}-cascade-{device}-intf-")
    ]
    assert targetable, f"no cascade-targetable interfaces found for {device}"

    for entry in targetable:
        interface = entry["labels"][interface_label]
        assert entry["while"]["scenario_name"] == flap.interface_cascade_name(device, interface)
        overrides = entry.get("overrides", {})
        for metric in _OCTET_METRICS[device]:
            assert overrides.get(metric, {}).get("delay", {}).get("close", {}).get("snap_to") is not None, (
                f"{device} {interface}: {metric} has no delay.close.snap_to"
            )


@pytest.mark.parametrize("device", ["srl1", "srl2"])
def test_cascade_gated_bgp_peers_match_generated_names(
    device: str,
    flap: ModuleType,
    slug: str,
    baseline_entries: Callable[[str], list[dict]],
) -> None:
    peer_label = flap._DEVICE_CONFIG[device]["peer_label"]
    gated = [
        e
        for e in baseline_entries(device)
        if e.get("while", {}).get("scenario_name", "").startswith(f"{slug}-cascade-{device}-bgp-")
    ]
    assert gated, f"no cascade-gated BGP peers found for {device}"

    for entry in gated:
        peer = entry["labels"][peer_label]
        assert entry["while"]["scenario_name"] == flap.bgp_cascade_name(device, peer)
