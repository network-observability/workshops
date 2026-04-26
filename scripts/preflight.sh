#!/usr/bin/env bash
# preflight.sh — sanity-check an attendee's environment before the workshop.
#
# Validates: docker present, compose v2, python3 present, RAM >= ~6 GiB,
# disk free >= 5 GiB, and outbound reachability to ghcr.io and docker.io.

set -uo pipefail

PASS=0
FAIL=0
WARN=0

ok()    { printf "  [ok]   %s\n" "$1"; PASS=$((PASS+1)); }
fail()  { printf "  [FAIL] %s\n" "$1"; FAIL=$((FAIL+1)); }
warn()  { printf "  [warn] %s\n" "$1"; WARN=$((WARN+1)); }

echo "AutoCon5 workshop preflight"
echo "==========================="

echo ""
echo "Tooling:"
if command -v docker >/dev/null 2>&1; then
  ok "docker on PATH ($(docker --version))"
else
  fail "docker is not on PATH"
fi

if docker compose version >/dev/null 2>&1; then
  ok "docker compose v2 ($(docker compose version --short))"
elif command -v docker-compose >/dev/null 2>&1; then
  fail "docker-compose v1 detected — please install Docker Compose v2 (the 'docker compose' subcommand)"
else
  fail "docker compose is not available"
fi

if command -v python3 >/dev/null 2>&1; then
  ok "python3 ($(python3 --version 2>&1))"
else
  warn "python3 not on PATH — needed for the Infrahub loader (task load-infrahub)"
fi

if command -v task >/dev/null 2>&1; then
  ok "task ($(task --version 2>/dev/null))"
else
  warn "task is not on PATH — install go-task or run 'docker compose ...' directly"
fi

echo ""
echo "Capacity:"
# RAM
if command -v free >/dev/null 2>&1; then
  total_kb=$(free -k | awk '/^Mem:/ {print $2}')
elif [ -r /proc/meminfo ]; then
  total_kb=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)
elif command -v sysctl >/dev/null 2>&1; then
  total_bytes=$(sysctl -n hw.memsize 2>/dev/null || echo 0)
  total_kb=$((total_bytes / 1024))
else
  total_kb=0
fi
total_gib=$((total_kb / 1024 / 1024))
if [ "$total_gib" -ge 8 ]; then
  ok  "RAM detected: ${total_gib} GiB"
elif [ "$total_gib" -ge 6 ]; then
  warn "RAM detected: ${total_gib} GiB — expect tight headroom; close other apps before running 'task up'"
else
  fail "RAM detected: ${total_gib} GiB — need ~8 GiB for the full stack"
fi

# Free disk
free_gib=$(df -k . | awk 'NR==2 {printf "%d", $4/1024/1024}')
if [ "$free_gib" -ge 5 ]; then
  ok  "Free disk in repo dir: ${free_gib} GiB"
else
  fail "Free disk in repo dir: ${free_gib} GiB — need ~5 GiB for image pulls"
fi

echo ""
echo "Network:"
for url in https://ghcr.io https://registry-1.docker.io https://github.com; do
  if curl -fsS -m 5 -o /dev/null -w '%{http_code}\n' "$url" >/dev/null 2>&1; then
    ok "reachable: $url"
  else
    warn "could not reach $url within 5s"
  fi
done

echo ""
echo "Result: ${PASS} ok, ${WARN} warn, ${FAIL} fail"
if [ "$FAIL" -gt 0 ]; then
  echo "Resolve the failures above before running 'task up'."
  exit 1
fi
exit 0
