#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${1:-${TK_INSTANCE:-colleague}}"
LABEL="com.tk-pipeline.dispatcher.${INSTANCE}"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"
echo "uninstalled: ${LABEL}"
