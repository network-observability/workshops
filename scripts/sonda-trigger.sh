#!/usr/bin/env bash
# sonda-trigger.sh — push ad-hoc telemetry into the running stack to drive
# alert/dashboard behaviour during the workshop.
#
# Usage:
#   sonda-trigger.sh flap-interface <device> <interface> [count]
#
# Sends N (default 6) UPDOWN log events into Loki tagged with
# vendor_facility_process="UPDOWN" and the requested device + interface.
# That is enough to trip the PeerInterfaceFlapping Loki rule (>3 in 2m).

set -euo pipefail

LOKI_URL="${LOKI_URL:-http://localhost:3001}"

cmd="${1:-}"
case "$cmd" in
  flap-interface)
    device="${2:?device required}"
    interface="${3:?interface required}"
    count="${4:-6}"
    echo "Pushing $count UPDOWN events for $device:$interface to $LOKI_URL ..."
    for i in $(seq 1 "$count"); do
      ts_ns=$(date +%s%N)
      payload=$(printf '{"streams":[{"stream":{"device":"%s","interface":"%s","level":"warning","vendor_facility_process":"UPDOWN","type":"syslog","source":"workshop-trigger"},"values":[["%s","Interface %s changed state to %s"]]}]}' \
        "$device" "$interface" "$ts_ns" "$interface" \
        "$([ $((i % 2)) -eq 0 ] && echo down || echo up)")
      curl -sS -H 'Content-Type: application/json' -X POST "${LOKI_URL}/loki/api/v1/push" -d "$payload" >/dev/null
      sleep 1
    done
    echo "Done. The PeerInterfaceFlapping alert should fire within ~30s."
    ;;
  ""|-h|--help)
    cat <<EOF
Usage: sonda-trigger.sh <subcommand> [args]
  flap-interface <device> <interface> [count=6]
EOF
    ;;
  *)
    echo "Unknown subcommand: $cmd" >&2
    exit 2
    ;;
esac
