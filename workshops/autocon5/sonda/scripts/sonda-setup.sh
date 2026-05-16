#!/bin/bash
# sonda-setup.sh — register each device's scenarios on sonda-server.
#
# Runs as an init container. Waits for sonda-server, expands any `pack:` refs
# against the local catalog, POSTs each `*.yaml` in `$SCENARIOS_DIR`, and
# writes one IDs file per source YAML so each telegraf only scrapes its own
# device's `/scenarios/{id}/metrics` endpoints.
#
# Source file -> IDs file:
#   srl1-metrics.yaml -> /shared/scenario-ids-srl1.txt
#   srl2-metrics.yaml -> /shared/scenario-ids-srl2.txt

set -e

pip install --no-cache-dir --quiet pyyaml

SONDA_SERVER_URL="${SONDA_SERVER_URL:-http://sonda-server:8080}"
SCENARIOS_DIR="${SCENARIOS_DIR:-/scenarios}"
SONDA_CATALOG_DIR="${SONDA_CATALOG_DIR:-/catalog}"
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
import copy
import json
import os
import sys
import urllib.error
import urllib.request

import yaml

server_url = os.environ.get("SONDA_SERVER_URL", "http://sonda-server:8080")
scenarios_dir = os.environ.get("SCENARIOS_DIR", "/scenarios")
catalog_dir = os.environ.get("SONDA_CATALOG_DIR", "/catalog")


class PackExpansionError(RuntimeError):
    """Raised when a `pack:` reference cannot be resolved or expanded."""


def _load_catalog(directory: str) -> dict[str, dict]:
    """Index `kind: composable` packs by their top-level `name:` field."""
    packs: dict[str, dict] = {}
    if not os.path.isdir(directory):
        return packs
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(directory, filename)
        with open(path) as fh:
            doc = yaml.safe_load(fh)
        if not isinstance(doc, dict):
            continue
        if doc.get("kind") != "composable":
            continue
        name = doc.get("name")
        if not isinstance(name, str) or not name:
            continue
        packs[name] = doc
    return packs


def _pack_body(pack_doc: dict) -> dict:
    """Return the inner `pack:` block (shared_labels, metrics)."""
    body = pack_doc.get("pack")
    if not isinstance(body, dict):
        raise PackExpansionError(
            f"pack {pack_doc.get('name')!r} has no top-level `pack:` block"
        )
    return body


def _expand_pack_entry(entry: dict, packs: dict[str, dict]) -> list[dict]:
    """Expand a runnable entry's `pack: <name>` ref into one entry per metric."""
    pack_name = entry["pack"]
    pack_doc = packs.get(pack_name)
    if pack_doc is None:
        raise PackExpansionError(
            f"pack {pack_name!r} not found in catalog (looked in {catalog_dir})"
        )
    body = _pack_body(pack_doc)
    pack_shared = body.get("shared_labels") or {}
    metrics = body.get("metrics") or []
    if not metrics:
        raise PackExpansionError(f"pack {pack_name!r} has no metrics")

    entry_labels = entry.get("labels") or {}
    overrides = entry.get("overrides") or {}
    metric_names = {m.get("name") for m in metrics if isinstance(m, dict)}
    for override_key in overrides:
        if override_key not in metric_names:
            raise PackExpansionError(
                f"override {override_key!r} on entry {entry.get('id')!r} "
                f"does not match any metric in pack {pack_name!r} "
                f"(valid: {sorted(n for n in metric_names if n)})"
            )

    base_id = entry.get("id") or pack_name
    carry_keys = {
        k: v
        for k, v in entry.items()
        if k not in {"pack", "overrides", "labels", "id", "name", "generator"}
    }

    expanded: list[dict] = []
    for metric in metrics:
        metric_name = metric["name"]
        merged_labels: dict = {}
        merged_labels.update(pack_shared)
        merged_labels.update(metric.get("labels") or {})
        merged_labels.update(entry_labels)
        override_for_metric = overrides.get(metric_name) or {}
        merged_labels.update(override_for_metric.get("labels") or {})
        merged_labels = {k: v for k, v in merged_labels.items() if v != ""}

        out: dict = copy.deepcopy(carry_keys)
        out["id"] = f"{base_id}__{metric_name}"
        out["name"] = metric_name
        out["labels"] = merged_labels
        generator = override_for_metric.get("generator") or metric.get("generator")
        if generator is not None:
            out["generator"] = copy.deepcopy(generator)
        for key in ("jitter",):
            if key in metric and key not in out:
                out[key] = metric[key]
        expanded.append(out)
    return expanded


def _materialize(config: dict, packs: dict[str, dict]) -> dict:
    """Return a copy of `config` with every `pack:` ref expanded inline."""
    out = copy.deepcopy(config)
    new_entries: list[dict] = []
    for entry in out.get("scenarios") or []:
        if isinstance(entry, dict) and "pack" in entry:
            new_entries.extend(_expand_pack_entry(entry, packs))
        else:
            new_entries.append(entry)
    out["scenarios"] = new_entries
    return out


def post_scenario_file(path: str, packs: dict[str, dict]) -> list[dict]:
    """POST a v2 runnable file (pack refs expanded) and return the response list."""
    with open(path) as fh:
        config = yaml.safe_load(fh)
    materialized = _materialize(config, packs)

    body = json.dumps(materialized).encode("utf-8")
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


packs = _load_catalog(catalog_dir)
print(f"Loaded {len(packs)} pack(s) from {catalog_dir}: {sorted(packs)}")

os.makedirs("/shared", exist_ok=True)
exit_code = 0
for filename in sorted(os.listdir(scenarios_dir)):
    if not filename.endswith((".yaml", ".yml")):
        continue
    filepath = os.path.join(scenarios_dir, filename)
    print(f"Loading {filepath}...")
    try:
        results = post_scenario_file(filepath, packs)
    except PackExpansionError as exc:
        print(f"  ERROR expanding {filepath}: {exc}", file=sys.stderr)
        exit_code = 1
        continue
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
