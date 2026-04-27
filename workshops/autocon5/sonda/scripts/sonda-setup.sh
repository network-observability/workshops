#!/bin/bash
# sonda-setup.sh — initialise sonda-server with the workshop's v2 scenario file.
#
# Runs as an init container (python:3.12-slim). Waits for sonda-server to be
# healthy, then POSTs the v2 scenario file to /scenarios. Once accepted,
# fetches the registered scenario IDs and writes them to /shared/scenario-ids.txt
# so telegraf-02's scrape script knows which /scenarios/{id}/metrics endpoints
# to hit.
#
# Per https://docs.davidban77.com/sonda/configuration/v2-scenarios/ the
# server expects a v2 envelope (`version: 2` at the top + a `scenarios:`
# array). We POST the file as-is — sonda-server registers each entry and
# returns a list (or summary) we can read back via GET /scenarios.

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


for filename in sorted(os.listdir(scenarios_dir)):
    if not filename.endswith((".yaml", ".yml")):
        continue
    filepath = os.path.join(scenarios_dir, filename)
    print(f"Loading {filepath}...")
    results = post_scenario_file(filepath)
    print(f"  -> server returned {len(results)} entry/entries")

# Always read the ID list back from the server — works regardless of which
# strategy above succeeded.
scenario_ids = list_scenario_ids()
ids_file = "/shared/scenario-ids.txt"
os.makedirs(os.path.dirname(ids_file), exist_ok=True)
with open(ids_file, "w") as fh:
    for sid in scenario_ids:
        fh.write(sid + "\n")
print(f"\nRegistered {len(scenario_ids)} scenario(s). IDs written to {ids_file}")
PYEOF
