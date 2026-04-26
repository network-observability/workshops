#!/bin/bash
# sonda-setup.sh — Initialize sonda-server with srl2 scenario configs
#
# This script runs as an init container (python:3.12-slim). It waits for
# sonda-server to be healthy, then splits the multi-scenario YAML file and
# POSTs each scenario individually to the sonda-server API.

set -e

# Install pyyaml (pure Python, quick install, no compilation needed)
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

# Split multi-scenario YAML into individual scenarios and POST each one.
python3 << 'PYEOF'
import json
import os
import sys
import urllib.request
import urllib.error
import yaml

server_url = os.environ.get("SONDA_SERVER_URL", "http://sonda-server:8080")
scenarios_dir = os.environ.get("SCENARIOS_DIR", "/scenarios")

scenario_ids = []

for filename in sorted(os.listdir(scenarios_dir)):
    if not filename.endswith(".yaml") and not filename.endswith(".yml"):
        continue

    filepath = os.path.join(scenarios_dir, filename)
    print(f"Loading {filepath}...")

    with open(filepath) as f:
        config = yaml.safe_load(f)

    # Handle both single scenario and multi-scenario configs
    entries = config.get("scenarios", [config])

    for i, entry in enumerate(entries):
        # POST each scenario as JSON (stdlib json encoder, no extra deps)
        body = json.dumps(entry).encode("utf-8")
        req = urllib.request.Request(
            f"{server_url}/scenarios",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
                sid = result["id"]
                name = result["name"]
                scenario_ids.append(sid)
                print(f"  [{i+1}/{len(entries)}] Created '{name}' -> id={sid}")
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            print(f"  [{i+1}/{len(entries)}] FAILED ({e.code}): {error_body}", file=sys.stderr)
        except Exception as e:
            print(f"  [{i+1}/{len(entries)}] FAILED: {e}", file=sys.stderr)

# Write scenario IDs for telegraf scrape script
ids_file = "/shared/scenario-ids.txt"
os.makedirs(os.path.dirname(ids_file), exist_ok=True)
with open(ids_file, "w") as f:
    for sid in scenario_ids:
        f.write(sid + "\n")

print(f"\nCreated {len(scenario_ids)} scenarios. IDs written to {ids_file}")
PYEOF
