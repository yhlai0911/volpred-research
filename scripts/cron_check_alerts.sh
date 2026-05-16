#!/bin/bash
# Canonical source for the check-alerts wrapper.
# Trigger: LaunchAgent com.volpred.check-alerts (24 Hour entries StartCalendarInterval).
# 2026-05-16 dual-cron refactor: host crontab entry REMOVED (was firing
# alongside LaunchAgent → 4 simultaneous processes per hour, lock
# contention, log pipe race, 10min execution delays). LaunchAgent is now
# the SINGLE source per config/runtime_schedules.json host_crontab_managed:false.
#
# IMPORTANT: macOS TCC (FDA) blocks daemons from exec'ing .sh under Desktop/.
# The actual exec target is ~/.volpred/bin/cron_check_alerts.sh.
# After editing this file:
#   cp scripts/cron_check_alerts.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_check_alerts.sh

exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/check_alerts.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

# Enable process group so cleanup signals propagate (Codex review pattern
# applied to hourly_dispatch.sh 2026-05-14, mirrored here for consistency).
set -m

# Single-fire lock: prevent overlapping runs even if LaunchAgent somehow
# double-fires same Label. flock-based (BSD compatible).
LOCKFILE="/tmp/volpred_check_alerts.lock"
exec 200>"$LOCKFILE"
if ! /usr/bin/python3 -c "import fcntl,sys; fcntl.flock(open('$LOCKFILE'), fcntl.LOCK_EX | fcntl.LOCK_NB)" 2>/dev/null; then
  echo "=== [check_alerts] $(date '+%Y-%m-%d %H:%M:%S %Z') skip — prior run still holds lock ==="
  exit 0
fi

# Hang detect: cap at 5 minutes (LaunchAgent fires hourly, well under 1h).
# Perl alarm pattern verified working on macOS 25.3 (hourly_dispatch.sh
# precedent, exit 142 on SIGALRM).
CHECK_ALERTS_CAP_SEC=300

# Cleanup trap: kill descendants if parent terminated mid-flight.
cleanup() {
  local exit_status=$?
  if [ -n "${ALERTS_PID:-}" ] && kill -0 "$ALERTS_PID" 2>/dev/null; then
    echo "[CLEANUP] parent exiting (status=$exit_status); killing alerts PGID $ALERTS_PID"
    kill -TERM -- "-$ALERTS_PID" 2>/dev/null || kill -TERM "$ALERTS_PID" 2>/dev/null
    sleep 2
    kill -KILL -- "-$ALERTS_PID" 2>/dev/null || kill -KILL "$ALERTS_PID" 2>/dev/null
  fi
}
trap cleanup EXIT TERM INT HUP

echo "=== [check_alerts] $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="

/usr/bin/perl -e 'alarm shift; exec @ARGV' "$CHECK_ALERTS_CAP_SEC" \
  /opt/homebrew/bin/uv run python scripts/check_alerts.py &
ALERTS_PID=$!

wait $ALERTS_PID
EXIT_CODE=$?

if [ $EXIT_CODE -eq 142 ]; then
  echo "[HANG-KILLED] check_alerts.py exceeded ${CHECK_ALERTS_CAP_SEC}s cap (SIGALRM)"
fi

echo "=== [check_alerts] exit $EXIT_CODE at $(date '+%Y-%m-%d %H:%M:%S %Z') (duration=${SECONDS}s) ==="
