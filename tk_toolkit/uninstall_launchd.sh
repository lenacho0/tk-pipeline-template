#!/usr/bin/env bash
set -euo pipefail
PLIST_DST="$HOME/Library/LaunchAgents/com.ryan.tk-dispatcher.plist"
launchctl bootout gui/$(id -u) com.ryan.tk-dispatcher >/dev/null 2>&1 || true
rm -f "$PLIST_DST"
echo "launchd service removed: com.ryan.tk-dispatcher"
