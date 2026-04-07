#!/usr/bin/env bash
set -euo pipefail

INSTANCE="${TK_INSTANCE:-default}"
LABEL="com.openclaw.tk-dispatcher.${INSTANCE}"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
rm -f "$PLIST_PATH"

echo "已卸载 launchd: $LABEL"
