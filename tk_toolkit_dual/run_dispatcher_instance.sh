#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTANCE="${TK_INSTANCE:-colleague}"
TABLE_KEY="${TK_DISPATCHER_TABLE_KEY:-}"
CONFIG_FILE="${TK_CONFIG_FILE:-$SCRIPT_DIR/config.local.json}"
SCOPE="$INSTANCE"
if [[ -n "$TABLE_KEY" ]]; then
  SCOPE="${INSTANCE}.${TABLE_KEY}"
fi
LOG_FILE="$SCRIPT_DIR/dispatcher.${SCOPE}.log"
HEARTBEAT_FILE="$SCRIPT_DIR/.dispatcher_heartbeat.${SCOPE}.json"
PYTHON_BIN="${PYTHON_BIN:-$SCRIPT_DIR/../.venv/bin/python}"
FEISHU_NO_PROXY="open.feishu.cn,.feishu.cn,feishu.cn,*.feishu.cn"

cd "$SCRIPT_DIR"
rm -f "$HEARTBEAT_FILE"

echo "dispatcher exec: instance=$INSTANCE table_key=${TABLE_KEY:-<all>} log=$LOG_FILE config=$CONFIG_FILE python=$PYTHON_BIN"

CA_BUNDLE="$("$PYTHON_BIN" - <<'PY' 2>/dev/null || true
try:
    import certifi
    print(certifi.where())
except Exception:
    print("")
PY
)"

if [[ -n "$CA_BUNDLE" && -f "$CA_BUNDLE" ]]; then
  exec env TK_INSTANCE="$INSTANCE" TK_CONFIG_FILE="$CONFIG_FILE" TK_DISPATCHER_TABLE_KEY="$TABLE_KEY" NO_PROXY="${NO_PROXY:+$NO_PROXY,}$FEISHU_NO_PROXY" no_proxy="${no_proxy:+$no_proxy,}$FEISHU_NO_PROXY" REQUESTS_CA_BUNDLE="$CA_BUNDLE" SSL_CERT_FILE="$CA_BUNDLE" "$PYTHON_BIN" "$SCRIPT_DIR/tk_dispatcher.py" >> "$LOG_FILE" 2>&1
fi

exec env -u REQUESTS_CA_BUNDLE -u SSL_CERT_FILE TK_INSTANCE="$INSTANCE" TK_CONFIG_FILE="$CONFIG_FILE" TK_DISPATCHER_TABLE_KEY="$TABLE_KEY" NO_PROXY="${NO_PROXY:+$NO_PROXY,}$FEISHU_NO_PROXY" no_proxy="${no_proxy:+$no_proxy,}$FEISHU_NO_PROXY" "$PYTHON_BIN" "$SCRIPT_DIR/tk_dispatcher.py" >> "$LOG_FILE" 2>&1
