#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTANCE="${TK_INSTANCE:-default}"
CONFIG_FILE="${TK_CONFIG_FILE:-$PROJECT_ROOT/config/config.json}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
LOG_FILE="$PROJECT_ROOT/dispatcher.${INSTANCE}.log"
HEARTBEAT_FILE="$PROJECT_ROOT/.dispatcher_heartbeat.${INSTANCE}.json"

cd "$PROJECT_ROOT"
rm -f "$HEARTBEAT_FILE"

echo "dispatcher exec: instance=$INSTANCE log=$LOG_FILE config=$CONFIG_FILE python=$PYTHON_BIN"

exec env TK_INSTANCE="$INSTANCE" TK_CONFIG_FILE="$CONFIG_FILE" \
  "$PYTHON_BIN" "$SCRIPT_DIR/tk_dispatcher.py" >> "$LOG_FILE" 2>&1
