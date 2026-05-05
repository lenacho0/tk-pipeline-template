#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"
LOG_FILE="$SCRIPT_DIR/ugc_video_review_trigger.log"

cd "$SCRIPT_DIR"
echo "$(date '+%Y-%m-%d %H:%M:%S') ugc-video-review-trigger tick python=$PYTHON_BIN" >> "$LOG_FILE"
exec "$PYTHON_BIN" "$SCRIPT_DIR/tk_ugc_video_review_trigger.py" --limit 20 --write --call-models >> "$LOG_FILE" 2>&1
