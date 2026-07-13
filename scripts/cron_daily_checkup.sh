#!/bin/bash
# 每日大體檢 LaunchAgent wrapper（canonical source）。
# Runtime copy: ~/.volpred/bin/cron_daily_checkup.sh；修改後執行：
#   uv run python scripts/sync_cron_wrappers.py --apply

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/daily_checkup.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh

# LaunchAgent 是唯一排程 owner；lock 仍防止人工 kickstart 與自然 fire 重疊。
LOCKDIR=/tmp/volpred_daily_checkup.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "=== [daily_checkup] $(date '+%Y-%m-%d %H:%M:%S %Z') skip — prior run still holds lock ==="
  exit 0
fi

set -m
CHECKUP_CAP_SEC=300
CHECKUP_PID=""
cleanup() {
  local exit_status=$?
  if [ -n "$CHECKUP_PID" ] && kill -0 "$CHECKUP_PID" 2>/dev/null; then
    kill -TERM -- "-$CHECKUP_PID" 2>/dev/null || kill -TERM "$CHECKUP_PID" 2>/dev/null
  fi
  rmdir "$LOCKDIR" 2>/dev/null || true
  return "$exit_status"
}
trap cleanup EXIT TERM INT HUP

_start=$SECONDS
cron_emit_start "daily_checkup"
/usr/bin/perl -e 'alarm shift; exec @ARGV' "$CHECKUP_CAP_SEC" \
  /Users/yhlai0911/.local/bin/uv run python scripts/daily_checkup.py --alert &
CHECKUP_PID=$!
wait "$CHECKUP_PID"
_ec=$?
CHECKUP_PID=""
if [ "$_ec" -eq 142 ]; then
  echo "[HANG-KILLED] daily_checkup.py exceeded ${CHECKUP_CAP_SEC}s cap (SIGALRM)"
fi
cron_emit_exit "daily_checkup" "$_ec" "$_start"
exit "$_ec"
