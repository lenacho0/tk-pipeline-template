#!/usr/bin/env bash
set -euo pipefail

ROOT="/Users/ryanlynn/.openclaw/workspace-tk"
TOOL_DIR="$ROOT/tools/media_bulk_downloader"
INBOX_DIR="$TOOL_DIR/inbox"
ARCHIVE_DIR="$TOOL_DIR/archive"
OUT_BASE="$ROOT/downloads/media_bulk"
ENV_FILE="$ROOT/.env"
QUEUE_FILE="${1:-$INBOX_DIR/urls.txt}"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$OUT_BASE/$RUN_TS"
ARCHIVE_FILE="$ARCHIVE_DIR/urls_$RUN_TS.txt"

mkdir -p "$INBOX_DIR" "$ARCHIVE_DIR" "$OUT_BASE"

if [[ ! -f "$QUEUE_FILE" ]]; then
  echo "Queue file not found: $QUEUE_FILE"
  echo "Put URLs into: $INBOX_DIR/urls.txt"
  exit 1
fi

if [[ ! -s "$QUEUE_FILE" ]]; then
  echo "Queue file is empty: $QUEUE_FILE"
  exit 1
fi

echo "Running bulk downloader..."
echo "Queue: $QUEUE_FILE"
echo "Output: $OUT_DIR"

cd "$ROOT"
python3 -m tools.media_bulk_downloader.cli \
  --input "$QUEUE_FILE" \
  --env-file "$ENV_FILE" \
  --output "$OUT_DIR"

cp "$QUEUE_FILE" "$ARCHIVE_FILE"
: > "$QUEUE_FILE"

echo "Done."
echo "Archived queue to: $ARCHIVE_FILE"
echo "Results in: $OUT_DIR"
