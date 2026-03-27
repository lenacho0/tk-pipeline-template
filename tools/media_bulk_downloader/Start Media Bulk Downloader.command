#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/ryanlynn/.openclaw/workspace-tk"
LOG_DIR="$ROOT/tools/media_bulk_downloader/runtime"
LOG_FILE="$LOG_DIR/web_ui.log"
PID_FILE="$LOG_DIR/web_ui.pid"
URL="http://127.0.0.1:8765"

mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    open "$URL"
    exit 0
  fi
fi

cd "$ROOT"
nohup python3 -m tools.media_bulk_downloader.web_app > "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 2
open "$URL"
