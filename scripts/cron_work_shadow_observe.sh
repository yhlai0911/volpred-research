#!/bin/bash
# Hourly append-only Work Coordinator shadow observer.
# Runtime copy: ~/.volpred/bin/cron_work_shadow_observe.sh

cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh

LOCKDIR=/tmp/volpred_work_shadow_observe.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "=== [work_shadow_observe] $(date '+%Y-%m-%d %H:%M:%S %Z') skip — prior run still holds lock ==="
  exit 0
fi

cleanup() {
  local exit_status=$?
  rmdir "$LOCKDIR" 2>/dev/null || true
  return "$exit_status"
}
trap cleanup EXIT TERM INT HUP

_start=$SECONDS
cron_emit_start "work_shadow_observe"
/usr/bin/perl -e 'alarm shift; exec @ARGV' 120 \
  /Users/yhlai0911/.local/bin/uv run python scripts/observe_work_shadow.py
_ec=$?
if [ "$_ec" -eq 142 ]; then
  echo "[HANG-KILLED] observe_work_shadow.py exceeded 120s cap (SIGALRM)"
fi
cron_emit_exit "work_shadow_observe" "$_ec" "$_start"
exit "$_ec"
