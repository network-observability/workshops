"""Detached cleanup subprocess for `nobs autocon5 flap-interface`.

When the parent flap-interface command DELETEs the baseline scenarios for
the flapped interface (and per-peer BGP) and POSTs the cascade body, it
spawns this module as a detached subprocess to handle the post-cascade
restore:

1. Sleep for the cascade duration plus a small buffer.
2. DELETE the cascade scenarios so they don't linger as `finished` rows
   in the registry.
3. POST a fresh baseline body covering the per-interface and per-peer
   scenarios that were DELETEd at flap time.

Idempotent and best-effort. If the parent dies or the cleanup is killed,
`nobs autocon5 reset` will catch the lingering state.
"""

from __future__ import annotations

import argparse
import contextlib
import re
import sys
import time
from typing import Any

import requests

_BROKEN_PEER_VALUES: dict[tuple[str, str], dict[str, float]] = {
    ("srl1", "10.1.99.2"): {
        "srl_bgp_oper_state": 5.0,
        "srl_bgp_neighbor_state": 4.0,
        "srl_bgp_received_routes": 0.0,
        "srl_bgp_prefixes_accepted": 0.0,
    },
    ("srl2", "10.1.11.1"): {
        "cbgpPeerOperStatus": 5.0,
        "bgpPeerState": 4.0,
        "bgpPeerInPrefixes": 0.0,
        "cbgpPeerAcceptedPrefixes": 0.0,
    },
}

# Per-device baseline scenario shape, in the form sonda POSTs at lab boot.
# Each entry uses `__INTERFACE__` / `__PEER_ADDRESS__` / `__PEER_ASN__`
# placeholders that the cleanup substitutes before POSTing.
_BASELINE_TEMPLATES: dict[str, dict[str, Any]] = {
    "srl1": {
        "defaults": {"rate": 0.1},
        "interface_scenarios": [
            {
                "signal_type": "metrics",
                "name": "srl_interface_oper_state",
                "metric_type": "gauge",
                "generator": {"type": "constant", "value": 1.0},
                "labels": {
                    "source": "srl1",
                    "name": "__INTERFACE__",
                    "collection_type": "gnmi",
                },
            },
            {
                "signal_type": "metrics",
                "name": "srl_interface_in_octets",
                "metric_type": "counter",
                "generator": {"type": "step", "start": 0.0, "step_size": 125000.0},
                "labels": {
                    "source": "srl1",
                    "name": "__INTERFACE__",
                    "collection_type": "gnmi",
                },
            },
            {
                "signal_type": "metrics",
                "name": "srl_interface_out_octets",
                "metric_type": "counter",
                "generator": {"type": "step", "start": 0.0, "step_size": 62500.0},
                "labels": {
                    "source": "srl1",
                    "name": "__INTERFACE__",
                    "collection_type": "gnmi",
                },
            },
        ],
        "bgp_scenarios": [
            ("srl_bgp_oper_state", 1.0),
            ("srl_bgp_neighbor_state", 1.0),
            ("srl_bgp_prefixes_accepted", 10.0),
            ("srl_bgp_received_routes", 10.0),
            ("srl_bgp_sent_routes", 10.0),
            ("srl_bgp_active_routes", 10.0),
        ],
        "bgp_label_template": {
            "source": "srl1",
            "peer_address": "__PEER_ADDRESS__",
            "neighbor_asn": "__PEER_ASN__",
            "afi_safi_name": "ipv4-unicast",
            "name": "default",
            "collection_type": "gnmi",
        },
    },
    "srl2": {
        "defaults": {"rate": 0.1},
        "interface_scenarios": [
            {
                "signal_type": "metrics",
                "name": "ifOperStatus",
                "metric_type": "gauge",
                "generator": {"type": "constant", "value": 1.0},
                "labels": {
                    "agent_host": "srl2",
                    "ifDescr": "__INTERFACE__",
                    "collection_type": "snmp",
                },
            },
            {
                "signal_type": "metrics",
                "name": "ifHCInOctets",
                "metric_type": "counter",
                "generator": {"type": "step", "start": 0.0, "step_size": 125000.0},
                "labels": {
                    "agent_host": "srl2",
                    "ifDescr": "__INTERFACE__",
                    "collection_type": "snmp",
                },
            },
            {
                "signal_type": "metrics",
                "name": "ifHCOutOctets",
                "metric_type": "counter",
                "generator": {"type": "step", "start": 0.0, "step_size": 62500.0},
                "labels": {
                    "agent_host": "srl2",
                    "ifDescr": "__INTERFACE__",
                    "collection_type": "snmp",
                },
            },
        ],
        "bgp_scenarios": [
            ("cbgpPeerOperStatus", 1.0),
            ("bgpPeerState", 1.0),
            ("cbgpPeerAcceptedPrefixes", 10.0),
            ("bgpPeerInPrefixes", 10.0),
            ("bgpPeerOutPrefixes", 10.0),
            ("cbgpPeerActivePrefixes", 10.0),
        ],
        "bgp_label_template": {
            "agent_host": "srl2",
            "bgpPeerRemoteAddr": "__PEER_ADDRESS__",
            "bgpPeerRemoteAs": "__PEER_ASN__",
            "afi_safi_name": "ipv4-unicast",
            "name": "default",
            "collection_type": "snmp",
        },
    },
}


def _parse_duration_secs(duration: str) -> float:
    m = re.match(r"^\s*([0-9.]+)\s*(ms|s|m|h)?\s*$", duration)
    if not m:
        return 240.0
    value = float(m.group(1))
    unit = m.group(2) or "s"
    return {
        "ms": value / 1000.0,
        "s": value,
        "m": value * 60.0,
        "h": value * 3600.0,
    }[unit]


def _substitute(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, dict):
        return {k: _substitute(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, mapping) for v in value]
    return value


def _restore_body(device: str, interface: str, peers: list[tuple[str, str]]) -> dict[str, Any] | None:
    template = _BASELINE_TEMPLATES.get(device)
    if template is None:
        return None

    scenarios: list[dict[str, Any]] = []
    for entry in template["interface_scenarios"]:
        scenarios.append(_substitute(entry, {"__INTERFACE__": interface}))

    for peer_addr, peer_asn in peers:
        labels = _substitute(
            template["bgp_label_template"],
            {"__PEER_ADDRESS__": peer_addr, "__PEER_ASN__": peer_asn},
        )
        overrides = _BROKEN_PEER_VALUES.get((device, peer_addr), {})
        for metric_name, default_value in template["bgp_scenarios"]:
            value = overrides.get(metric_name, default_value)
            scenarios.append(
                {
                    "signal_type": "metrics",
                    "name": metric_name,
                    "metric_type": "gauge",
                    "generator": {"type": "constant", "value": value},
                    "labels": labels,
                }
            )

    return {
        "version": 2,
        "kind": "runnable",
        "scenario_name": f"autocon5-restore-{device}-{interface.replace('/', '-')}-{int(time.time())}",
        "defaults": dict(template["defaults"]),
        "scenarios": scenarios,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autocon5_workshop.flap_cleanup")
    parser.add_argument("--sonda-url", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--cascade-id", action="append", default=[])
    parser.add_argument(
        "--peer",
        action="append",
        default=[],
        help="Peer in 'address:asn' form. Repeat for multiple peers.",
    )
    parser.add_argument("--cascade-duration", default="4m")
    parser.add_argument("--cleanup-buffer-secs", type=float, default=5.0)
    args = parser.parse_args(argv)

    base = args.sonda_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    peers: list[tuple[str, str]] = []
    for raw in args.peer:
        if ":" not in raw:
            continue
        addr, asn = raw.split(":", 1)
        peers.append((addr, asn))

    sleep_secs = _parse_duration_secs(args.cascade_duration) + args.cleanup_buffer_secs
    time.sleep(sleep_secs)

    for sid in args.cascade_id:
        with contextlib.suppress(requests.RequestException):
            requests.delete(f"{base}/scenarios/{sid}", headers=headers, timeout=5)

    body = _restore_body(args.device, args.interface, peers)
    if body is None:
        return 0
    try:
        requests.post(f"{base}/scenarios", json=body, headers=headers, timeout=10)
    except requests.RequestException:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
