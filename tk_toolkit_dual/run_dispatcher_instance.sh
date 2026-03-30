#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCE="${TK_INSTANCE:-default}"
CONFIG_FILE="${TK_CONFIG_FILE:-$SCRIPT_DIR/config.json}"
PID_FILE="$SCRIPT_DIR/dispatcher.${INSTANCE}.pid"
LOG_FILE="$SCRIPT_DIR/dispatcher.${INSTANCE}.log"
HEARTBEAT_FILE="$SCRIPT_DIR/.dispatcher_heartbeat.${INSTANCE}.json"
PYTHON_BIN="${PYTHON_BIN:-/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python}"

cd "$SCRIPT_DIR"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "dispatcher already running: instance=$INSTANCE pid=$old_pid"
    exit 0
  else
    rm -f "$PID_FILE"
  fi
fi
rm -f "$HEARTBEAT_FILE"

nohup env TK_INSTANCE="$INSTANCE" TK_CONFIG_FILE="$CONFIG_FILE" "$PYTHON_BIN" "$SCRIPT_DIR/tk_dispatcher.py" >> "$LOG_FILE" 2>&1 &
new_pid=$!
echo "$new_pid" > "$PID_FILE"
sleep 2

if kill -0 "$new_pid" 2>/dev/null; then
  echo "dispatcher started: instance=$INSTANCE pid=$new_pid log=$LOG_FILE config=$CONFIG_FILE"
else
  echo "dispatcher failed to start: instance=$INSTANCE"
  exit 1
fi
