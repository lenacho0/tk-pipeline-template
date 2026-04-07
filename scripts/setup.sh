#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV_DIR="${VENV_DIR:-$PROJECT_ROOT/.venv}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "初始化 TK Pipeline 模板环境"
echo "项目目录: $PROJECT_ROOT"

"$PYTHON_BIN" --version

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

mkdir -p "$PROJECT_ROOT/workspace/default"

echo ""
echo "初始化完成。"
echo "下一步："
echo "1. 复制 config/config.template.json 为 config/config.<name>.json"
echo "2. 填写飞书和多维表配置"
echo "3. 运行健康检查"
