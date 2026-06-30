#!/bin/bash

# 14:00 Asia/Taipei intraday refresh for daily_update.
# Canonical source for the LaunchAgent wrapper.
# Runtime copy lives at ~/.volpred/bin/cron_daily_update_intraday.sh.
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/daily_update_intraday.log 2>&1

cd /Users/yhlai0911/Desktop/volpred-research

# Share the same lock as the 08:03 daily_update job. If the morning run ever
# stretches into the intraday slot, skip rather than double-writing feed/sync state.
LOCKDIR=/tmp/volpred_daily_update.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "=== [daily_update_intraday] $(date '+%Y-%m-%dT%H:%M:%S%z') skip — daily_update lock already held ==="
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

if [ "${VOLPRED_ALLOW_OFFSCHEDULE_DAILY_UPDATE:-}" != "1" ]; then
  _guard_output=$(/opt/homebrew/bin/uv run volpred ops schedule-due daily_update_intraday --fail-if-not-scheduled 2>&1)
  _guard_ec=$?
  if [ "${_guard_ec}" -eq 75 ]; then
    printf '%s\n' "${_guard_output}"
    echo "=== [daily_update_intraday] $(date '+%Y-%m-%dT%H:%M:%S%z') skip — canonical intraday schedule not due; set VOLPRED_ALLOW_OFFSCHEDULE_DAILY_UPDATE=1 to override ==="
    exit 0
  elif [ "${_guard_ec}" -ne 0 ]; then
    printf '%s\n' "${_guard_output}"
    echo "=== [daily_update_intraday] guard failure exit ${_guard_ec} at $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
    exit "${_guard_ec}"
  fi
else
  echo "=== [daily_update_intraday] $(date '+%Y-%m-%dT%H:%M:%S%z') off-schedule guard override via VOLPRED_ALLOW_OFFSCHEDULE_DAILY_UPDATE=1 ==="
fi

_start=$(date +%s)
echo "=== [daily_update_intraday] start at $(date '+%Y-%m-%dT%H:%M:%S%z') ==="
/opt/homebrew/bin/uv run python scripts/daily_update.py
_ec=$?
echo "=== [daily_update_intraday] exit ${_ec} at $(date '+%Y-%m-%dT%H:%M:%S%z') (duration=$(($(date +%s) - _start))s) ==="
exit ${_ec}
