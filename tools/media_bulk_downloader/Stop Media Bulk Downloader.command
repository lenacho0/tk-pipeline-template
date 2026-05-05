#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/ryanlynn/.openclaw/workspace-tk"
OLD_ROOT="$ROOT/tools/media_bulk_downloader"
PID_FILE="$OLD_ROOT/runtime/web_ui.pid"

echo "[redirect] Stopping shared Media Bulk Downloader instance launched from tk wrapper..."

if [[ ! -f "$PID_FILE" ]]; then
  echo "No PID file found."
  exit 0
fi

PID="$(cat "$PID_FILE" || true)"
if [[ -n "$PID" ]] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
fi
rm -f "$PID_FILE"

echo "Media Bulk Downloader web UI stopped."
