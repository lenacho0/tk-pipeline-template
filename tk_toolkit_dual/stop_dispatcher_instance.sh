#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCE="${TK_INSTANCE:-default}"
PID_FILE="$SCRIPT_DIR/dispatcher.${INSTANCE}.pid"
HEARTBEAT_FILE="$SCRIPT_DIR/.dispatcher_heartbeat.${INSTANCE}.json"

rm -f "$HEARTBEAT_FILE"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    echo "dispatcher stopped: instance=$INSTANCE pid=$pid"
  fi
  rm -f "$PID_FILE"
else
  echo "dispatcher not running: instance=$INSTANCE"
fi
