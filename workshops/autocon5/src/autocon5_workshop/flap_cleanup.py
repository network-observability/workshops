"""Detached cleanup subprocess for `nobs autocon5 flap-interface`.

When the parent flap-interface command DELETEs the baseline scenarios
the cascade will override (interface oper_state + octets for the flapped
interface; bgp_* per cascading peer) and POSTs the cascade body, it
spawns this module as a detached subprocess to handle the post-cascade
restore:

1. Poll the cascade scenario UUIDs until they all reach `finished`
   (or until a generous timeout elapses).
2. DELETE the cascade scenarios so they don't linger in the registry.
3. POST a fresh baseline body for the affected interface and peers,
   mirroring what `sonda-setup.sh` would have POSTed at lab boot.

Idempotent and best-effort. If the parent dies or the cleanup is killed,
`nobs autocon5 reset` will detect a missing baseline and re-POST it.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from typing import Any

import requests

# Per-device baseline restore templates. Interface scenarios cover the
# flapped interface (oper_state + octets); BGP scenarios are POSTed once
# per cascading peer (oper, neighbor, prefix counters — admin_state stays
# untouched because the cascade never overrides it). Tokens substituted
# at runtime: __INTERFACE__, __PEER__, __ASN__.
_INTERFACE_BGP_BASELINES: dict[str, dict[str, list[dict[str, Any]]]] = {
    "srl1": {
        "interface": [
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
        "bgp_per_peer": [
            {"name": "srl_bgp_oper_state", "value": 1.0},
            {"name": "srl_bgp_neighbor_state", "value": 1.0},
            {"name": "srl_bgp_prefixes_accepted", "value": 10.0},
            {"name": "srl_bgp_received_routes", "value": 10.0},
            {"name": "srl_bgp_sent_routes", "value": 10.0},
            {"name": "srl_bgp_active_routes", "value": 10.0},
        ],
    },
    "srl2": {
        "interface": [
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
        "bgp_per_peer": [
            {"name": "cbgpPeerOperStatus", "value": 1.0},
            {"name": "bgpPeerState", "value": 1.0},
            {"name": "cbgpPeerAcceptedPrefixes", "value": 10.0},
            {"name": "bgpPeerInPrefixes", "value": 10.0},
            {"name": "bgpPeerOutPrefixes", "value": 10.0},
            {"name": "cbgpPeerActivePrefixes", "value": 10.0},
        ],
    },
}

_BGP_PEER_SHARED_LABELS: dict[str, dict[str, str]] = {
    "srl1": {
        "source": "srl1",
        "peer_address": "__PEER__",
        "neighbor_asn": "__ASN__",
        "name": "default",
        "afi_safi_name": "ipv4-unicast",
        "collection_type": "gnmi",
    },
    "srl2": {
        "agent_host": "srl2",
        "bgpPeerRemoteAddr": "__PEER__",
        "bgpPeerRemoteAs": "__ASN__",
        "afi_safi_name": "ipv4-unicast",
        "name": "default",
        "collection_type": "snmp",
    },
}


def _wait_for_finished(base: str, ids: list[str], headers: dict[str, str], timeout_secs: int) -> None:
    pending = set(ids)
    deadline = time.time() + timeout_secs
    while pending and time.time() < deadline:
        time.sleep(10)
        for sid in list(pending):
            try:
                r = requests.get(f"{base}/scenarios/{sid}", headers=headers, timeout=5)
            except requests.RequestException:
                continue
            if r.status_code == 404:
                pending.discard(sid)
                continue
            if not r.ok:
                continue
            if r.json().get("state") == "finished":
                pending.discard(sid)


def _substitute(value: str, interface: str, peer: str, asn: str) -> str:
    return value.replace("__INTERFACE__", interface).replace("__PEER__", peer).replace("__ASN__", asn)


def _restore_body(device: str, interface: str, peers: list[tuple[str, str]]) -> dict[str, Any] | None:
    """Build the restore body: interface oper_state + octets for the flapped interface,
    plus the cascade-affected BGP metrics for each cascading peer.
    """
    templates = _INTERFACE_BGP_BASELINES.get(device)
    if templates is None:
        return None

    scenarios: list[dict[str, Any]] = []
    for entry in templates["interface"]:
        scenarios.append(
            {
                **entry,
                "labels": {k: _substitute(v, interface, "", "") for k, v in entry["labels"].items()},
            }
        )

    bgp_label_template = _BGP_PEER_SHARED_LABELS.get(device, {})
    for peer_address, neighbor_asn in peers:
        peer_labels = {k: _substitute(v, "", peer_address, neighbor_asn) for k, v in bgp_label_template.items()}
        for metric in templates["bgp_per_peer"]:
            scenarios.append(
                {
                    "signal_type": "metrics",
                    "name": metric["name"],
                    "metric_type": "gauge",
                    "generator": {"type": "constant", "value": metric["value"]},
                    "labels": dict(peer_labels),
                }
            )

    return {
        "version": 2,
        "kind": "runnable",
        "scenario_name": f"autocon5-restore-{device}-{interface.replace('/', '-')}-{int(time.time())}",
        "defaults": {"rate": 0.1},
        "scenarios": scenarios,
    }


def _parse_peer(spec: str) -> tuple[str, str]:
    address, _, asn = spec.partition(":")
    return address, asn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autocon5_workshop.flap_cleanup")
    parser.add_argument("--sonda-url", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument(
        "--primary-id",
        default="",
        help="UUID of the cascade's primary_flap scenario. When set, "
        "the wait blocks only on this ID (others are force-deleted "
        "unconditionally). Sonda leaves gated `while:` entries stuck "
        "in `state=running` after the ref finishes, so waiting on all "
        "cascade IDs would hit the timeout every run.",
    )
    parser.add_argument("--cascade-id", action="append", default=[])
    parser.add_argument("--peer", action="append", default=[], help="Repeatable, format ADDRESS:ASN")
    parser.add_argument("--timeout-secs", type=int, default=600)
    args = parser.parse_args(argv)

    base = args.sonda_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    if args.cascade_id:
        wait_ids = [args.primary_id] if args.primary_id else args.cascade_id
        _wait_for_finished(base, wait_ids, headers, args.timeout_secs)
        for sid in args.cascade_id:
            with contextlib.suppress(requests.RequestException):
                requests.delete(f"{base}/scenarios/{sid}", headers=headers, timeout=5)

    peers = [_parse_peer(p) for p in args.peer]
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
