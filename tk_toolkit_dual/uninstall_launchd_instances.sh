#!/usr/bin/env bash
set -euo pipefail
for name in ryan; do
  label="com.ryan.tk-dispatcher.${name}"
  dst="$HOME/Library/LaunchAgents/${label}.plist"
  launchctl bootout gui/$(id -u) "$label" >/dev/null 2>&1 || true
  if [[ -e "$dst" ]]; then
    if command -v trash >/dev/null 2>&1; then
      trash "$dst"
    else
      rm -f "$dst"
    fi
  fi
  echo "removed: $label"
done
