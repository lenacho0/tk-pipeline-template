#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${VENV_DIR:-$REPO_ROOT/.venv}"
PYTHON_BOOTSTRAP="${PYTHON_BOOTSTRAP:-python3}"
CONFIG_FILE="$SCRIPT_DIR/config.local.json"

echo "TK Pipeline local setup"
echo "repo: $REPO_ROOT"
echo "venv: $VENV_DIR"

"$PYTHON_BOOTSTRAP" --version >/dev/null

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BOOTSTRAP" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$SCRIPT_DIR/requirements.txt"

if [[ ! -f "$CONFIG_FILE" ]]; then
  cp "$SCRIPT_DIR/config.json.template" "$CONFIG_FILE"
  echo "created: $CONFIG_FILE"
else
  echo "exists: $CONFIG_FILE"
fi

mkdir -p "$SCRIPT_DIR/workspace"

cat <<EOF

Next steps:
1. Edit $CONFIG_FILE
   - Fill feishu.app_id
   - Fill feishu.app_secret
   - Fill feishu.bitable_app_token with the copied Base token
2. Rebind local table IDs:
   "$VENV_DIR/bin/python" "$SCRIPT_DIR/rebind_copied_base.py" --config "$CONFIG_FILE" --write
3. Run healthcheck:
   TK_INSTANCE=colleague TK_CONFIG_FILE="$CONFIG_FILE" "$VENV_DIR/bin/python" "$SCRIPT_DIR/tk_healthcheck.py"
4. Install launchd:
   PYTHON_BIN="$VENV_DIR/bin/python" TK_CONFIG_FILE="$CONFIG_FILE" bash "$SCRIPT_DIR/install_launchd_instances.sh" colleague
EOF
