#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCE="${TK_INSTANCE:-default}"
CONFIG_FILE="${TK_CONFIG_FILE:-$SCRIPT_DIR/config.${INSTANCE}.json}"
LOG_FILE="$SCRIPT_DIR/dispatcher.${INSTANCE}.log"
HEARTBEAT_FILE="$SCRIPT_DIR/.dispatcher_heartbeat.${INSTANCE}.json"
PYTHON_BIN="${PYTHON_BIN:-/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/.venv312/bin/python}"

cd "$SCRIPT_DIR"
rm -f "$HEARTBEAT_FILE"

echo "dispatcher exec: instance=$INSTANCE log=$LOG_FILE config=$CONFIG_FILE python=$PYTHON_BIN"

exec env TK_INSTANCE="$INSTANCE" TK_CONFIG_FILE="$CONFIG_FILE" "$PYTHON_BIN" "$SCRIPT_DIR/tk_dispatcher.py" >> "$LOG_FILE" 2>&1
