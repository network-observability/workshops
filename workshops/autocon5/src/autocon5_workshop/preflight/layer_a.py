"""Layer A — wait for the right data shape across both pipelines.

Polls Prometheus + Loki until expected series counts arrive, calls the
in-process flap-interface + maintenance helpers to seed events, and
sleeps for `[2m]` rate windows to fill. Writes layer_a.json.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

# preflight/layer_a.py -> workshops/autocon5/
WORKSHOP_DIR = Path(os.environ.get("PREFLIGHT_WORKSHOP_DIR",
                                   Path(__file__).resolve().parents[3]))
OUT_DIR = Path(os.environ.get("PREFLIGHT_OUT_DIR", "/tmp/preflight-out"))

PROM = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
LOKI = os.environ.get("LOKI_URL", "http://localhost:3001")

TIMEOUT_DEFAULT = 180
PROBE_INTERVAL = 4
WINDOW_FILL_S = 130


def prom_count(query: str) -> int:
    r = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=10)
    r.raise_for_status()
    res = r.json().get("data", {}).get("result", [])
    return int(float(res[0]["value"][1])) if res else 0


def loki_pipelines_seen(label_match: str) -> set[str]:
    end = int(time.time() * 1e9)
    start = end - 300 * 10**9
    r = requests.get(
        f"{LOKI}/loki/api/v1/series",
        params={"match[]": label_match, "start": start, "end": end},
        timeout=10,
    )
    r.raise_for_status()
    return {s.get("pipeline", "") for s in r.json().get("data", []) if s.get("pipeline")}


def loki_count(query: str, minutes: int = 5) -> int:
    end = int(time.time() * 1e9)
    start = end - minutes * 60 * 10**9
    r = requests.get(
        f"{LOKI}/loki/api/v1/query_range",
        params={"query": query, "start": start, "end": end, "limit": 200},
        timeout=10,
    )
    r.raise_for_status()
    streams = r.json().get("data", {}).get("result", [])
    return sum(len(s.get("values", [])) for s in streams)


def wait(label: str, predicate, timeout: int = TIMEOUT_DEFAULT, expected: str = "") -> dict:
    start = time.time()
    last_detail = last_err = ""
    while time.time() - start < timeout:
        try:
            ok, detail = predicate()
            last_detail = detail
            if ok:
                elapsed = time.time() - start
                print(f"  [{elapsed:5.1f}s] OK   {label} — {detail}", flush=True)
                return {"label": label, "ok": True, "elapsed_s": round(elapsed, 1),
                        "detail": detail, "expected": expected}
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
        time.sleep(PROBE_INTERVAL)
    elapsed = time.time() - start
    detail = last_detail or last_err or "no data"
    print(f"  [{elapsed:5.1f}s] FAIL {label} — {detail}", flush=True)
    return {"label": label, "ok": False, "elapsed_s": round(elapsed, 1),
            "detail": detail, "expected": expected}


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "layer_a.json"
    results: list[dict] = []

    print("Layer A — wait for data shape", flush=True)

    Q_BGP = 'count(bgp_oper_state{pipeline=~".+"})'
    Q_INTF = 'count(interface_oper_state{intf_role="peer", pipeline=~".+"})'
    Q_LOKI_UPDOWN = '{vendor_facility_process="UPDOWN"}'
    Q_LOKI_FLAP = ('{device="srl1", vendor_facility_process="UPDOWN"} '
                   '|~ "Interface .* changed state"')
    Q_LOKI_CONFIG = '{device="srl1", source="workshop-trigger", event="config-push"}'

    results.append(wait(
        "bgp_oper_state pipeline convergence",
        lambda: (prom_count(Q_BGP) >= 6, f"count = {prom_count(Q_BGP)}"),
        expected=">= 6 series",
    ))
    results.append(wait(
        "interface_oper_state intf_role=peer convergence",
        lambda: (prom_count(Q_INTF) >= 6, f"count = {prom_count(Q_INTF)}"),
        expected=">= 6 series",
    ))
    results.append(wait(
        "logs pipeline convergence (UPDOWN)",
        lambda: ({"direct", "vector"}.issubset(loki_pipelines_seen(Q_LOKI_UPDOWN)),
                 f"pipelines = {sorted(loki_pipelines_seen(Q_LOKI_UPDOWN))}"),
        expected="{direct, vector}",
    ))

    # In-process triggers — call the workshop's command functions directly
    # rather than re-spawning `nobs`. Both functions are Typer-decorated but
    # callable as plain Python with explicit kwargs.
    print("Layer A — flap-interface (in-process)", flush=True)
    from autocon5_workshop.flap import flap_interface
    flap_interface(
        device="srl1", interface="ethernet-1/1", count=6, delay=0.5,
        loki_url=os.environ.get("LOKI_URL", "http://localhost:3001"),
    )

    print("Layer A — maintenance toggle (in-process)", flush=True)
    from nobs.commands.maintenance import maintenance
    maintenance(
        device="srl1", state=True, kind="WorkshopDevice",
        address=os.environ.get("INFRAHUB_ADDRESS", "http://localhost:8000"),
        token=os.environ.get("INFRAHUB_API_TOKEN", ""),
        loki_url=os.environ.get("LOKI_URL", "http://localhost:3001"),
    )

    print(f"Layer A — sleeping {WINDOW_FILL_S}s for [2m] windows to fill", flush=True)
    for remaining in range(WINDOW_FILL_S, 0, -20):
        print(f"  ... {remaining}s left", flush=True)
        time.sleep(20)

    results.append(wait(
        "Loki has UPDOWN events from both producers",
        lambda: (loki_count(Q_LOKI_UPDOWN) >= 8,
                 f"events last 5m = {loki_count(Q_LOKI_UPDOWN)}"),
        timeout=30, expected=">= 8 events",
    ))
    results.append(wait(
        "Interface Flap annotation source has lines",
        lambda: (loki_count(Q_LOKI_FLAP) >= 4,
                 f"flap lines = {loki_count(Q_LOKI_FLAP)}"),
        timeout=30, expected=">= 4 lines",
    ))
    results.append(wait(
        "Device Config Push annotation source has lines",
        lambda: (loki_count(Q_LOKI_CONFIG) >= 1,
                 f"config-push lines = {loki_count(Q_LOKI_CONFIG)}"),
        timeout=30, expected=">= 1 line",
    ))

    out.write_text(json.dumps(results, indent=2))
    print(f"\nLayer A — wrote {out}", flush=True)
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
