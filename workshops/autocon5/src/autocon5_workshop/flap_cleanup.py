"""Detached cleanup subprocess for `nobs autocon5 flap-interface`.

When the parent flap-interface command DELETEs the baseline octet
scenarios for the flapped interface and POSTs the cascade body that
contains gated step counters as the new emitters, it spawns this module
as a detached subprocess to handle the post-cascade restore:

1. Poll the cascade scenario UUIDs until they all reach `finished`
   (or until a generous timeout elapses).
2. DELETE the cascade scenarios so they don't linger in the registry.
3. POST a fresh baseline body for the affected interface, mirroring
   what `sonda-setup.sh` would have POSTed at lab boot.

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

_RESTORE_BODIES: dict[str, dict[str, Any]] = {
    "srl1": {
        "version": 2,
        "kind": "runnable",
        "defaults": {"rate": 0.1},
        "scenarios": [
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
    },
    "srl2": {
        "version": 2,
        "kind": "runnable",
        "defaults": {"rate": 0.1},
        "scenarios": [
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
    },
}


def _wait_for_finished(
    base: str, ids: list[str], headers: dict[str, str], timeout_secs: int
) -> None:
    pending = set(ids)
    deadline = time.time() + timeout_secs
    while pending and time.time() < deadline:
        time.sleep(3)
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


def _restore_body(device: str, interface: str) -> dict[str, Any] | None:
    template = _RESTORE_BODIES.get(device)
    if template is None:
        return None
    body: dict[str, Any] = {
        "version": template["version"],
        "kind": template["kind"],
        "scenario_name": f"autocon5-restore-{device}-{interface.replace('/', '-')}-{int(time.time())}",
        "defaults": dict(template["defaults"]),
        "scenarios": [],
    }
    for entry in template["scenarios"]:
        new_entry = {
            **entry,
            "labels": {
                k: (interface if v == "__INTERFACE__" else v) for k, v in entry["labels"].items()
            },
        }
        body["scenarios"].append(new_entry)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="autocon5_workshop.flap_cleanup")
    parser.add_argument("--sonda-url", required=True)
    parser.add_argument("--device", required=True)
    parser.add_argument("--interface", required=True)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--cascade-id", action="append", default=[])
    parser.add_argument("--timeout-secs", type=int, default=600)
    args = parser.parse_args(argv)

    base = args.sonda_url.rstrip("/")
    headers = {"Content-Type": "application/json"}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    if args.cascade_id:
        _wait_for_finished(base, args.cascade_id, headers, args.timeout_secs)
        for sid in args.cascade_id:
            with contextlib.suppress(requests.RequestException):
                requests.delete(f"{base}/scenarios/{sid}", headers=headers, timeout=5)

    body = _restore_body(args.device, args.interface)
    if body is None:
        return 0
    try:
        requests.post(f"{base}/scenarios", json=body, headers=headers, timeout=10)
    except requests.RequestException:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
