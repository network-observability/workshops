#!/bin/bash
# sonda-setup.sh — register each device's scenarios on sonda-server.
#
# Runs as an init container. Waits for sonda-server, POSTs each `*.yaml` in
# `$SCENARIOS_DIR`, and writes one IDs file per source YAML so each telegraf
# only scrapes its own device's `/scenarios/{id}/metrics` endpoints.
#
# Source file → IDs file:
#   srl1-metrics.yaml → /shared/scenario-ids-srl1.txt
#   srl2-metrics.yaml → /shared/scenario-ids-srl2.txt

set -e

# pyyaml: pure-Python, fast install, no compile.
pip install --no-cache-dir --quiet pyyaml

SONDA_SERVER_URL="${SONDA_SERVER_URL:-http://sonda-server:8080}"
SCENARIOS_DIR="${SCENARIOS_DIR:-/scenarios}"
MAX_RETRIES=30
RETRY_INTERVAL=2

echo "Waiting for sonda-server at ${SONDA_SERVER_URL}..."
retries=0
until python3 -c "import urllib.request; urllib.request.urlopen('${SONDA_SERVER_URL}/health')" 2>/dev/null; do
    retries=$((retries + 1))
    if [ "$retries" -ge "$MAX_RETRIES" ]; then
        echo "ERROR: sonda-server not healthy after ${MAX_RETRIES} attempts"
        exit 1
    fi
    echo "  Retry ${retries}/${MAX_RETRIES}..."
    sleep "$RETRY_INTERVAL"
done
echo "sonda-server is healthy."

python3 << 'PYEOF'
import json
import os
import sys
import urllib.error
import urllib.request

import yaml

server_url = os.environ.get("SONDA_SERVER_URL", "http://sonda-server:8080")
scenarios_dir = os.environ.get("SCENARIOS_DIR", "/scenarios")


def post_scenario_file(path: str) -> list[dict]:
    """POST a v2 scenario file (as a single envelope) and return the
    sonda-server's response list. We try the v2 envelope first, then fall
    back to per-entry POSTs in case the server's /scenarios route is the
    older bare-entry shape."""
    with open(path) as fh:
        config = yaml.safe_load(fh)

    # Strategy A: POST the whole v2 file (preserves `version`, `defaults`).
    body = json.dumps(config).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/scenarios",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and isinstance(result.get("scenarios"), list):
                return result["scenarios"]
            return [result]
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        # 4xx/5xx — fall through to per-entry retry.
        print(
            f"  v2-envelope POST returned {e.code}: {error_body}",
            file=sys.stderr,
        )
        print("  retrying per-entry with v2 envelope wrappers...")

    # Strategy B: per-entry, each wrapped in its own minimal v2 envelope.
    out: list[dict] = []
    defaults = config.get("defaults") or {}
    for i, entry in enumerate(config.get("scenarios") or []):
        wrapped = {"version": 2, "defaults": defaults, "scenarios": [entry]}
        body = json.dumps(wrapped).encode("utf-8")
        req = urllib.request.Request(
            f"{server_url}/scenarios",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
                if isinstance(result, list):
                    out.extend(result)
                else:
                    out.append(result)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            print(
                f"  [{i+1}] FAILED ({e.code}): {error_body}",
                file=sys.stderr,
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [{i+1}] FAILED: {e}", file=sys.stderr)
    return out


def list_scenario_ids() -> list[str]:
    """Read back the registered scenarios via GET /scenarios."""
    try:
        with urllib.request.urlopen(f"{server_url}/scenarios") as resp:
            payload = json.loads(resp.read())
    except Exception as e:  # noqa: BLE001
        print(f"  could not list scenarios: {e}", file=sys.stderr)
        return []
    items = payload.get("scenarios") if isinstance(payload, dict) else payload
    ids: list[str] = []
    for item in items or []:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
    return ids


def _ids_of(results: list[dict]) -> list[str]:
    return [r["id"] for r in results if isinstance(r, dict) and r.get("id")]


# `{stem}-metrics.yaml` → `/shared/scenario-ids-{stem}.txt`.
def _ids_file_for(filename: str) -> str:
    stem = filename.removesuffix(".yaml").removesuffix(".yml")
    if stem.endswith("-metrics"):
        stem = stem[: -len("-metrics")]
    return f"/shared/scenario-ids-{stem}.txt"


os.makedirs("/shared", exist_ok=True)
for filename in sorted(os.listdir(scenarios_dir)):
    if not filename.endswith((".yaml", ".yml")):
        continue
    filepath = os.path.join(scenarios_dir, filename)
    print(f"Loading {filepath}...")
    results = post_scenario_file(filepath)
    ids = _ids_of(results)
    out = _ids_file_for(filename)
    with open(out, "w") as fh:
        for sid in ids:
            fh.write(sid + "\n")
    print(f"  -> {len(results)} entry/entries, {len(ids)} id(s) → {out}")
PYEOF
