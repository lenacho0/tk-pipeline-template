#!/usr/bin/env bash
set -euo pipefail

WORKDIR="/Users/ryanlynn/.openclaw/workspace-tk"
OLD_ROOT="$WORKDIR/tools/media_bulk_downloader"
SHARED_ROOT="/Users/ryanlynn/.openclaw/skills/media_bulk_downloader"
LOG_DIR="$OLD_ROOT/runtime"
LOG_FILE="$LOG_DIR/web_ui.log"
PID_FILE="$LOG_DIR/web_ui.pid"
URL="http://127.0.0.1:8765"
ENV_FILE="$WORKDIR/.env"
DOWNLOAD_ROOT="$WORKDIR/downloads/media_bulk_web"

mkdir -p "$LOG_DIR"

echo "[redirect] This launcher now uses shared tool: $SHARED_ROOT"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    open "$URL"
    exit 0
  fi
fi

nohup env \
  MEDIA_BULK_WORKDIR="$WORKDIR" \
  MEDIA_BULK_ENV_FILE="$ENV_FILE" \
  MEDIA_BULK_DOWNLOAD_ROOT="$DOWNLOAD_ROOT" \
  python3 "$SHARED_ROOT/web_app.py" > "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

sleep 2
open "$URL"
