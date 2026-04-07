#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INSTANCE="${TK_INSTANCE:-default}"

PID_FILE="$PROJECT_ROOT/dispatcher.${INSTANCE}.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "未找到 PID 文件: $PID_FILE"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if kill "$PID" >/dev/null 2>&1; then
  rm -f "$PID_FILE"
  echo "已停止实例: $INSTANCE (pid=$PID)"
else
  echo "停止失败，可能进程已不存在: $PID"
fi
