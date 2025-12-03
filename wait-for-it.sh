#!/usr/bin/env bash
# wait-for-it.sh
# Usage: ./wait-for-it.sh host:port [--timeout=seconds] [--strict] [-- command args]

set -e

HOSTPORT="$1"
TIMEOUT=30
STRICT=false
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --timeout=*) TIMEOUT="${1#*=}"; shift ;;
    --strict) STRICT=true; shift ;;
    *) break ;;
  esac
done

HOST="${HOSTPORT%%:*}"
PORT="${HOSTPORT##*:}"

echo "Waiting for $HOST:$PORT..."

for i in $(seq 1 "$TIMEOUT"); do
  if nc -z "$HOST" "$PORT" >/dev/null 2>&1; then
    echo "$HOST:$PORT is available!"
    exit 0
  fi
  sleep 1
done

echo "Timeout reached after $TIMEOUT seconds waiting for $HOST:$PORT"
if [ "$STRICT" = true ]; then
  exit 1
fi
exit 0
