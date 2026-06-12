#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${1:-${TK_INSTANCE:-colleague}}"
TABLE_KEY="${2:-${TK_DISPATCHER_TABLE_KEY:-}}"
SCOPE="$INSTANCE"
if [[ -n "$TABLE_KEY" ]]; then
  SCOPE="${INSTANCE}.${TABLE_KEY}"
fi
LABEL="com.tk-pipeline.dispatcher.${SCOPE}"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"
echo "uninstalled: ${LABEL}"
