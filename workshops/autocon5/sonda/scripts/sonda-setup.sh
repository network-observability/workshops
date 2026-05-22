#!/bin/bash
# sonda-setup.sh — register each device's scenarios on sonda-server.
#
# Runs as an init container. Waits for sonda-server, POSTs each `*.yaml` in
# `$SCENARIOS_DIR` (server resolves any `pack:` refs via its own `--catalog`),
# and writes one IDs file per source YAML so each telegraf only scrapes its
# own device's `/scenarios/{id}/metrics` endpoints.
#
# Source file -> IDs file:
#   srl1-metrics.yaml -> /shared/scenario-ids-srl1.txt
#   srl2-metrics.yaml -> /shared/scenario-ids-srl2.txt

set -e

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
    """POST a v2 runnable file and return the response list."""
    with open(path) as fh:
        config = yaml.safe_load(fh)

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
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        if e.code == 409:
            # 409 here means the scenarios were registered on a previous init run — treat as success.
            conflict = json.loads(error_body)
            conflicting = conflict.get("conflicting_scenarios") or []
            scenario_name = config.get("scenario_name") or os.path.basename(path)
            print(
                f"  -> already running (scenario_name={scenario_name!r}, "
                f"{len(conflicting)} conflicting entries); skipping re-POST and re-using existing IDs"
            )
            return conflicting
        print(f"  POST /scenarios failed ({e.code}): {error_body}", file=sys.stderr)
        raise

    if isinstance(result, list):
        return result
    if isinstance(result, dict) and isinstance(result.get("scenarios"), list):
        return result["scenarios"]
    return [result]


def _ids_of(results: list[dict]) -> list[str]:
    return [r["id"] for r in results if isinstance(r, dict) and r.get("id")]


def _ids_file_for(filename: str) -> str:
    """`{stem}-metrics.yaml` -> `/shared/scenario-ids-{stem}.txt`."""
    stem = filename.removesuffix(".yaml").removesuffix(".yml")
    if stem.endswith("-metrics"):
        stem = stem[: -len("-metrics")]
    return f"/shared/scenario-ids-{stem}.txt"


os.makedirs("/shared", exist_ok=True)
exit_code = 0
for filename in sorted(os.listdir(scenarios_dir)):
    if not filename.endswith((".yaml", ".yml")):
        continue
    filepath = os.path.join(scenarios_dir, filename)
    print(f"Loading {filepath}...")
    try:
        results = post_scenario_file(filepath)
    except urllib.error.HTTPError:
        exit_code = 1
        continue
    ids = _ids_of(results)
    out = _ids_file_for(filename)
    with open(out, "w") as fh:
        for sid in ids:
            fh.write(sid + "\n")
    print(f"  -> {len(results)} entry/entries, {len(ids)} id(s) -> {out}")

sys.exit(exit_code)
PYEOF
