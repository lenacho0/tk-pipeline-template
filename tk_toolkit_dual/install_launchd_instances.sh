#!/usr/bin/env bash
set -euo pipefail
mkdir -p "$HOME/Library/LaunchAgents"
for name in ryan colleague; do
  label="com.ryan.tk-dispatcher.${name}"
  src="/Users/ryanlynn/.openclaw/workspace-tk/tk_toolkit_dual/${label}.plist"
  dst="$HOME/Library/LaunchAgents/${label}.plist"
  cp "$src" "$dst"
  launchctl bootout gui/$(id -u) "$label" >/dev/null 2>&1 || true
  launchctl bootstrap gui/$(id -u) "$dst"
  launchctl enable gui/$(id -u)/$label || true
  launchctl kickstart -k gui/$(id -u)/$label
  echo "installed: $label"
done
