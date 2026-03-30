#!/usr/bin/env bash
set -euo pipefail
PLIST_SRC="/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit/com.ryan.tk-dispatcher.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.ryan.tk-dispatcher.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl bootout gui/$(id -u) com.ryan.tk-dispatcher >/dev/null 2>&1 || true
launchctl bootstrap gui/$(id -u) "$PLIST_DST"
launchctl enable gui/$(id -u)/com.ryan.tk-dispatcher || true
launchctl kickstart -k gui/$(id -u)/com.ryan.tk-dispatcher
launchctl print gui/$(id -u)/com.ryan.tk-dispatcher | sed -n '1,120p'
