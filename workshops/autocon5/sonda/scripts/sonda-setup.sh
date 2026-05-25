#!/bin/bash
# sonda-setup.sh — register each device's scenarios on sonda-server.
#
# Runs as an init container. Waits for sonda-server, POSTs each `*.yaml` in
# `$SCENARIOS_DIR` (server resolves any `pack:` refs via its own `--catalog`),
# and exits. Telegraf scrapes the aggregate /metrics endpoint filtered by
# device label, so no per-device ID file is needed.
#
# Each top-level scenario in a file is POSTed as its OWN batch (one HTTP
# call per `- id: ...` entry). This is a workaround for an upstream sonda
# 1.12.2 lifecycle bug: when a scenario is DELETEd via the API, sibling
# scenarios from the same POST batch transition to state=finished. The
# `flap-interface` cascade DELETEs the flapped interface's baselines, and
# without per-scenario batches every other srl1 baseline (admin_state,
# unrelated peers, etc.) would finish in sympathy, leaving the dashboard
# blank. With per-scenario batches the blast radius is limited to the
# directly-targeted pack-expansion. See the autocon5 troubleshooting docs
# for the full write-up and the upstream sonda issue tracking the fix.

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


def _post_single_batch(body: dict, label: str) -> list[dict]:
    """POST one scenario-body batch. Returns the response list (or [] on 409)."""
    body_bytes = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{server_url}/scenarios",
        data=body_bytes,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        if e.code == 409:
            conflict = json.loads(error_body)
            conflicting = conflict.get("conflicting_scenarios") or []
            print(
                f"    -> {label}: already running ({len(conflicting)} conflicting); "
                f"skipping re-POST and re-using existing IDs"
            )
            return conflicting
        print(f"    POST /scenarios failed for {label} ({e.code}): {error_body}", file=sys.stderr)
        raise

    if isinstance(result, list):
        return result
    if isinstance(result, dict) and isinstance(result.get("scenarios"), list):
        return result["scenarios"]
    return [result]


def post_scenario_file(path: str) -> list[dict]:
    """POST each scenario in a v2 runnable file as its OWN batch.

    See header comment: per-scenario POSTs limit the sonda 1.12.2
    finish-cascade bug's blast radius to a single pack-expansion when the
    flap-interface cascade DELETEs baseline scenarios.
    """
    with open(path) as fh:
        config = yaml.safe_load(fh)

    base_name = config.get("scenario_name") or os.path.splitext(os.path.basename(path))[0]
    common = {k: v for k, v in config.items() if k not in ("scenarios", "scenario_name")}
    common.setdefault("version", 2)
    common.setdefault("kind", "runnable")

    results: list[dict] = []
    for index, scenario in enumerate(config.get("scenarios") or []):
        sid = scenario.get("id") or scenario.get("name") or f"entry{index}"
        body = {
            **common,
            "scenario_name": f"{base_name}--{sid}",
            "scenarios": [scenario],
        }
        results.extend(_post_single_batch(body, label=sid))
    return results


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
    print(f"  -> {len(results)} entry/entries registered")

sys.exit(exit_code)
PYEOF
