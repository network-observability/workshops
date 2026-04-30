"""Lab topology lookups for the flap-interface CLI.

Reads `lab_vars.yml` once at import time and exposes:
- `peers_for(device, interface)` — BGP peer addresses on the link.
- `interface_labels(device, name)` — Prometheus label set for `interface_oper_state`.
- `bgp_labels(device, peer_address, neighbor_asn)` — label set for BGP per-peer metrics.

The healthy interface↔peer mapping is derived from the YAML by `/24`
subnet membership. The deliberately-broken peers (`10.1.99.2` on srl1 and
`10.1.11.1` on srl2) are configured against interfaces whose addressing
doesn't match, so they live in an explicit override map.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

_WORKSHOP_DIR = Path(__file__).resolve().parents[2]
_LAB_VARS_PATH = _WORKSHOP_DIR / "lab_vars.yml"

# Peers configured against a non-matching subnet (intentional misconfig demo).
_BROKEN_PEER_OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("srl1", "ethernet-1/11"): ("10.1.99.2", "65102"),
    ("srl2", "ethernet-1/11"): ("10.1.11.1", "65101"),
}

# srl2's series carry telegraf-02 provenance labels post-normalization.
_TELEGRAF_LABELS: dict[str, str] = {
    "host": "telegraf-02",
    "instance": "telegraf-02:9005",
    "job": "telegraf",
}


@dataclass(frozen=True)
class Peer:
    address: str
    asn: str


def _load_lab_vars() -> dict:
    with _LAB_VARS_PATH.open() as fh:
        return yaml.safe_load(fh) or {}


def _intended_peers(lab: dict, device: str) -> list[dict]:
    intent = (lab.get("observability_intent") or {}).get("bgp") or {}
    return (intent.get("intended_peers") or {}).get(device) or []


def _interface_entry(lab: dict, device: str, interface: str) -> dict | None:
    node = (lab.get("nodes") or {}).get(device) or {}
    for entry in node.get("interfaces") or []:
        if entry.get("name") == interface:
            return entry
    return None


def _healthy_peers_for(lab: dict, device: str, interface: str) -> list[Peer]:
    entry = _interface_entry(lab, device, interface)
    if not entry:
        return []
    ipv4 = entry.get("ipv4")
    if not isinstance(ipv4, str):
        return []
    try:
        net = ipaddress.ip_network(ipv4, strict=False)
    except ValueError:
        return []
    matched: list[Peer] = []
    for peer in _intended_peers(lab, device):
        addr = peer.get("peer_ip")
        if not addr:
            continue
        try:
            if ipaddress.ip_address(addr) in net:
                matched.append(Peer(address=addr, asn=str(peer.get("remote_as", ""))))
        except ValueError:
            continue
    return matched


_LAB_VARS: dict = _load_lab_vars()


def peers_for(device: str, interface: str) -> list[Peer]:
    """Return the BGP peers on the link this interface terminates."""
    override = _BROKEN_PEER_OVERRIDES.get((device, interface))
    if override:
        addr, asn = override
        return [Peer(address=addr, asn=asn)]
    return _healthy_peers_for(_LAB_VARS, device, interface)


def known_devices() -> Iterable[str]:
    return tuple((_LAB_VARS.get("nodes") or {}).keys())


def interface_labels(device: str, name: str) -> dict[str, str]:
    """Label set for `interface_oper_state` matching the lab's continuous emitters."""
    base: dict[str, str] = {
        "device": device,
        "name": name,
        "intf_role": "peer",
        "collection_type": "gnmi",
    }
    if device == "srl2":
        base["pipeline"] = "telegraf"
        base.update(_TELEGRAF_LABELS)
    else:
        base["pipeline"] = "direct"
    return base


def bgp_labels(device: str, peer_address: str, neighbor_asn: str) -> dict[str, str]:
    """Label set for `bgp_oper_state`/`bgp_neighbor_state`/prefix counters."""
    base: dict[str, str] = {
        "device": device,
        "peer_address": peer_address,
        "neighbor_asn": neighbor_asn,
        "name": "default",
        "afi_safi_name": "ipv4-unicast",
        "collection_type": "gnmi",
    }
    if device == "srl2":
        base["pipeline"] = "telegraf"
        base.update(_TELEGRAF_LABELS)
    else:
        base["pipeline"] = "direct"
    return base
