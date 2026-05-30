#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCE="${TK_INSTANCE:-default}"
CONFIG_FILE="${TK_CONFIG_FILE:-$SCRIPT_DIR/config.${INSTANCE}.json}"
LOG_FILE="$SCRIPT_DIR/dispatcher.${INSTANCE}.log"
HEARTBEAT_FILE="$SCRIPT_DIR/.dispatcher_heartbeat.${INSTANCE}.json"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3}"

cd "$SCRIPT_DIR"
rm -f "$HEARTBEAT_FILE"

echo "dispatcher exec: instance=$INSTANCE log=$LOG_FILE config=$CONFIG_FILE python=$PYTHON_BIN"

CA_BUNDLE="$("$PYTHON_BIN" - <<'PY' 2>/dev/null || true
try:
    import certifi
    print(certifi.where())
except Exception:
    print("")
PY
)"

if [[ -n "$CA_BUNDLE" && -f "$CA_BUNDLE" ]]; then
  exec env TK_INSTANCE="$INSTANCE" TK_CONFIG_FILE="$CONFIG_FILE" REQUESTS_CA_BUNDLE="$CA_BUNDLE" SSL_CERT_FILE="$CA_BUNDLE" "$PYTHON_BIN" "$SCRIPT_DIR/tk_dispatcher.py" >> "$LOG_FILE" 2>&1
fi

exec env -u REQUESTS_CA_BUNDLE -u SSL_CERT_FILE TK_INSTANCE="$INSTANCE" TK_CONFIG_FILE="$CONFIG_FILE" "$PYTHON_BIN" "$SCRIPT_DIR/tk_dispatcher.py" >> "$LOG_FILE" 2>&1
