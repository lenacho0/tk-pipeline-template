#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTANCE="${1:-${TK_INSTANCE:-colleague}}"
LABEL="com.tk-pipeline.dispatcher.${INSTANCE}"
CONFIG_FILE="${TK_CONFIG_FILE:-$SCRIPT_DIR/config.local.json}"
PYTHON_BIN="${PYTHON_BIN:-$REPO_ROOT/.venv/bin/python}"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/${LABEL}.plist"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python not found or not executable: $PYTHON_BIN" >&2
  echo "Run: bash $SCRIPT_DIR/setup_local.sh" >&2
  exit 1
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "Config not found: $CONFIG_FILE" >&2
  echo "Run setup_local.sh and fill config.local.json first." >&2
  exit 1
fi

mkdir -p "$PLIST_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${SCRIPT_DIR}/run_dispatcher_instance.sh</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${SCRIPT_DIR}</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${SCRIPT_DIR}/launchd.${INSTANCE}.out.log</string>
  <key>StandardErrorPath</key>
  <string>${SCRIPT_DIR}/launchd.${INSTANCE}.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>TK_INSTANCE</key>
    <string>${INSTANCE}</string>
    <key>TK_CONFIG_FILE</key>
    <string>${CONFIG_FILE}</string>
    <key>PYTHON_BIN</key>
    <string>${PYTHON_BIN}</string>
  </dict>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
launchctl enable "gui/$(id -u)/${LABEL}" || true
launchctl kickstart -k "gui/$(id -u)/${LABEL}"
echo "installed: ${LABEL}"
echo "plist: ${PLIST_PATH}"
