#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/dispatcher.pid"
LOG_FILE="$SCRIPT_DIR/dispatcher.log"
HEARTBEAT_FILE="$SCRIPT_DIR/.dispatcher_heartbeat.json"
PYTHON_BIN="${PYTHON_BIN:-python3}"

cd "$SCRIPT_DIR"

if [[ -f "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${old_pid:-}" ]] && kill -0 "$old_pid" 2>/dev/null; then
    echo "dispatcher already running: pid=$old_pid"
    exit 0
  else
    rm -f "$PID_FILE"
  fi
fi
rm -f "$HEARTBEAT_FILE"

# 清掉历史残留 dispatcher，避免双进程抢任务
existing_pids="$(pgrep -f "tk_dispatcher.py" || true)"
if [[ -n "${existing_pids:-}" ]]; then
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    kill "$pid" 2>/dev/null || true
    sleep 1
    kill -9 "$pid" 2>/dev/null || true
  done <<< "$existing_pids"
fi

nohup "$PYTHON_BIN" "$SCRIPT_DIR/tk_dispatcher.py" >> "$LOG_FILE" 2>&1 &
new_pid=$!
echo "$new_pid" > "$PID_FILE"
sleep 2

if kill -0 "$new_pid" 2>/dev/null; then
  echo "dispatcher started: pid=$new_pid log=$LOG_FILE"
else
  echo "dispatcher failed to start"
  exit 1
fi
