#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/dispatcher.pid"
HEARTBEAT_FILE="$SCRIPT_DIR/.dispatcher_heartbeat.json"

rm -f "$HEARTBEAT_FILE"

if [[ -f "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
    echo "dispatcher stopped: pid=$pid"
  fi
  rm -f "$PID_FILE"
fi

existing_pids="$(pgrep -f "tk_dispatcher.py" || true)"
if [[ -n "${existing_pids:-}" ]]; then
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
  done <<< "$existing_pids"
fi
