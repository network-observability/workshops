#!/bin/sh
# scrape-sonda-metrics.sh — Fetch metrics from all sonda-server scenarios
#
# Used by telegraf's exec input plugin to scrape metrics from sonda-server.
# Discovers scenario IDs from a shared file written by sonda-setup,
# then fetches Prometheus text metrics from each scenario's scrape endpoint.

SONDA_SERVER_URL="${SONDA_SERVER_URL:-http://sonda-server:8080}"
IDS_FILE="/shared/scenario-ids.txt"

# Fallback: if IDs file doesn't exist yet, discover from API
if [ ! -f "$IDS_FILE" ]; then
    # Try to discover from the scenarios list API
    IDS=$(curl -sf "${SONDA_SERVER_URL}/scenarios" 2>/dev/null | \
        python3 -c "import sys,json; [print(s['id']) for s in json.loads(sys.stdin.read())['scenarios']]" 2>/dev/null)
else
    IDS=$(cat "$IDS_FILE")
fi

if [ -z "$IDS" ]; then
    exit 0
fi

# Fetch metrics from each scenario and output to stdout
for id in $IDS; do
    curl -sf "${SONDA_SERVER_URL}/scenarios/${id}/metrics" 2>/dev/null
done
