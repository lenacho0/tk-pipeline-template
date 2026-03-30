#!/usr/bin/env bash
set -euo pipefail
for name in ryan colleague; do
  label="com.ryan.tk-dispatcher.${name}"
  dst="$HOME/Library/LaunchAgents/${label}.plist"
  launchctl bootout gui/$(id -u) "$label" >/dev/null 2>&1 || true
  rm -f "$dst"
  echo "removed: $label"
done
