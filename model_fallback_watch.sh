#!/bin/zsh
set -euo pipefail

LOG="$HOME/.openclaw/logs/gateway.err.log"
STATE_DIR="$HOME/.openclaw-autoclaw/workspace-tk/.state"
STATE_FILE="$STATE_DIR/model_fallback_watch.state"
LOCK_DIR="$STATE_DIR/model_fallback_watch.lock"
mkdir -p "$STATE_DIR"

PRIMARY_MODEL="custom__jarvis-gpt54/gpt-5.4"
FAIL_PATTERN='embedded run agent end: .*isError=true|API rate limit reached|insufficient|quota|payment required|401|429|auth.*fail'
RECOVERY_PATTERN='embedded run agent end: .*isError=false'
FAIL_COOLDOWN=21600  # 6h
RECOVERY_COOLDOWN=3600  # 1h

# cheap lock to avoid overlap
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  exit 0
fi
cleanup() { rmdir "$LOCK_DIR" 2>/dev/null || true; }
trap cleanup EXIT

last_size=0
last_fail_ts=""
last_fail_notify_epoch=0
last_recovery_notify_epoch=0
last_status="unknown"
if [[ -f "$STATE_FILE" ]]; then
  source "$STATE_FILE" || true
fi

if [[ ! -f "$LOG" ]]; then
  exit 0
fi

curr_size=$(wc -c < "$LOG" | tr -d ' ')
if [[ "$curr_size" -lt "$last_size" ]]; then
  last_size=0
fi

tmp=$(mktemp)
tail -c +$((last_size + 1)) "$LOG" > "$tmp" || true
now=$(date +%s)

new_fail=$(grep -iE "$FAIL_PATTERN" "$tmp" | tail -n 1 || true)
new_recovery=$(grep -iE "$RECOVERY_PATTERN" "$tmp" | tail -n 1 || true)
notified=0

if [[ -n "$new_fail" ]]; then
  fail_ts=$(printf '%s' "$new_fail" | sed -E 's/^([^ ]+).*/\1/')
  if [[ "$fail_ts" != "$last_fail_ts" ]]; then
    if (( now - ${last_fail_notify_epoch:-0} >= FAIL_COOLDOWN )); then
      openclaw wake "提醒：检测到模型/Provider 故障日志。主模型 ${PRIMARY_MODEL} 可能已不可用，系统可能正在依赖 fallback。\n\n日志摘要：$new_fail" >/dev/null 2>&1 || true
      last_fail_notify_epoch=$now
      notified=1
    fi
    last_fail_ts="$fail_ts"
    last_status="failing"
  fi
fi

# Recovery only after a known failing state, and rate-limited.
if [[ "$last_status" == "failing" && -n "$new_recovery" ]]; then
  if (( now - ${last_recovery_notify_epoch:-0} >= RECOVERY_COOLDOWN )); then
    openclaw wake "提醒：模型运行日志出现恢复信号。主模型 ${PRIMARY_MODEL} 可能已恢复正常。你可以留意后续是否还继续依赖 fallback。" >/dev/null 2>&1 || true
    last_recovery_notify_epoch=$now
    last_status="healthy"
    notified=1
  fi
fi

cat > "$STATE_FILE" <<EOF
last_size=$curr_size
last_fail_ts="$last_fail_ts"
last_fail_notify_epoch=${last_fail_notify_epoch:-0}
last_recovery_notify_epoch=${last_recovery_notify_epoch:-0}
last_status="$last_status"
EOF

rm -f "$tmp"
exit 0
