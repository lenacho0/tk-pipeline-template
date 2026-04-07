#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTANCE="${TK_INSTANCE:-default}"
CONFIG_FILE="${TK_CONFIG_FILE:-$PROJECT_ROOT/config/config.json}"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_ROOT/.venv/bin/python}"
LABEL="com.openclaw.tk-dispatcher.${INSTANCE}"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"

mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${SCRIPT_DIR}/run_dispatcher.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${PROJECT_ROOT}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${PROJECT_ROOT}/launchd.${INSTANCE}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_ROOT}/launchd.${INSTANCE}.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
    <key>TK_INSTANCE</key>
    <string>${INSTANCE}</string>
    <key>TK_CONFIG_FILE</key>
    <string>${CONFIG_FILE}</string>
    <key>PYTHON_BIN</key>
    <string>${PYTHON_BIN}</string>
  </dict>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/${LABEL}" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/${LABEL}" || true
launchctl kickstart -k "gui/$(id -u)/${LABEL}"

echo "已安装 launchd: $LABEL"
echo "plist: $PLIST_PATH"
