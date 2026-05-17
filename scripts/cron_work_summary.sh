#!/bin/bash
# Canonical source for the work-summary wrapper.
# Trigger: LaunchAgent com.volpred.work-summary (4 entries every 6h UTC-aligned).
# 2026-05-17 user-requested: every 6h email summary of past 6h work.
#
# Architecture mirrors check_alerts dual-cron refactor (LaunchAgent canonical,
# no host crontab) per CLAUDE.md Three-Strike rule.
#
# IMPORTANT: macOS TCC blocks daemons from exec'ing .sh under Desktop/.
# Actual exec target: ~/.volpred/bin/cron_work_summary.sh
# After editing:
#   cp scripts/cron_work_summary.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_work_summary.sh

exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/work_summary.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

set -m

# Single-fire lock
LOCKFILE="/tmp/volpred_work_summary.lock"
exec 200>"$LOCKFILE"
if ! /usr/bin/python3 -c "import fcntl,sys; fcntl.flock(open('$LOCKFILE'), fcntl.LOCK_EX | fcntl.LOCK_NB)" 2>/dev/null; then
  echo "=== [work_summary] $(date '+%Y-%m-%d %H:%M:%S %Z') skip — prior run still holds lock ==="
  exit 0
fi

# Hang cap 3 min (send-alert is mostly network I/O + small read)
WORK_SUMMARY_CAP_SEC=180

cleanup() {
  local exit_status=$?
  if [ -n "${SUMMARY_PID:-}" ] && kill -0 "$SUMMARY_PID" 2>/dev/null; then
    echo "[CLEANUP] parent exiting (status=$exit_status); killing summary PGID $SUMMARY_PID"
    kill -TERM -- "-$SUMMARY_PID" 2>/dev/null || kill -TERM "$SUMMARY_PID" 2>/dev/null
    sleep 2
    kill -KILL -- "-$SUMMARY_PID" 2>/dev/null || kill -KILL "$SUMMARY_PID" 2>/dev/null
  fi
}
trap cleanup EXIT TERM INT HUP

echo "=== [work_summary] $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="

/usr/bin/perl -e 'alarm shift; exec @ARGV' "$WORK_SUMMARY_CAP_SEC" \
  /opt/homebrew/bin/uv run python scripts/work_summary_6h.py &
SUMMARY_PID=$!

wait $SUMMARY_PID
EXIT_CODE=$?

if [ $EXIT_CODE -eq 142 ]; then
  echo "[HANG-KILLED] work_summary_6h.py exceeded ${WORK_SUMMARY_CAP_SEC}s cap (SIGALRM)"
fi

echo "=== [work_summary] exit $EXIT_CODE at $(date '+%Y-%m-%d %H:%M:%S %Z') (duration=${SECONDS}s) ==="
