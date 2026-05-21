#!/bin/bash
# Canonical source for continue_task host-cron wrapper.
#
# Purpose (v3 2026-05-16):
#  1. 寫 pending_continue.json 旗標 + history（session_startup.md replay 仰賴）
#  2. 跑 dispatch.py --report 寫 dispatch_report_latest.json（slot-fill 候選清單）
#  主線程下次 idle wake 必讀 dispatch_report_latest.json 派工，不靠 next-session replay。
#
# 2026-05-16 hardening (code review C1 / three-strike rule applied early):
#  - Added flock single-fire lock (mirrors cron_check_alerts.sh).
#  - Added perl alarm hang cap at 8 min (well under hourly cadence).
#  - Process group + cleanup trap to reap descendants on parent termination.
#  - Separate exit code tracking for stub.py vs dispatch.py so a true stub
#    failure surfaces in host_cron_fail (previously $? captured only the
#    last command's exit — silent stub failures were unreachable).
#
# IMPORTANT: macOS TCC (FDA) blocks daemons from exec'ing .sh under Desktop/.
# The cron-exec target is ~/.volpred/bin/cron_continue_task_stub.sh.
# After editing this file run:
#   cp scripts/cron_continue_task_stub.sh ~/.volpred/bin/ && \
#   chmod +x ~/.volpred/bin/cron_continue_task_stub.sh

exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/continue_task_stub.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

# Enable job control so kill -PGID propagates
set -m

# Single-fire lock: prevent overlapping runs if cron / LaunchAgent
# double-fires same Label. flock-based (BSD compatible).
LOCKFILE="/tmp/volpred_continue_task_stub.lock"
# PID-file lock: works on macOS without GNU flock. The previous flock(open())
# approach released the lock when the Python child exited (bug: lock was held
# by a short-lived subprocess, not this shell process).
if [ -f "$LOCKFILE" ]; then
  LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null)
  if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
    echo "=== [continue_task_stub] $(date '+%Y-%m-%d %H:%M:%S %Z') skip — prior run ($LOCK_PID) still holds lock ==="
    exit 0
  fi
fi
echo $$ > "$LOCKFILE"
trap "rm -f '$LOCKFILE'" EXIT

# Hang cap: 8 minutes — generous vs typical sub-30s run, well under hourly
# cadence so a hung child can never stack with the next firing.
STUB_CAP_SEC=480

# Cleanup trap: kill descendants if parent terminated mid-flight.
cleanup() {
  local exit_status=$?
  for pid in "${STUB_PID:-}" "${DISPATCH_PID:-}"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      echo "[CLEANUP] parent exiting (status=$exit_status); killing PGID $pid"
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
      sleep 2
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
    fi
  done
}
trap cleanup EXIT TERM INT HUP

echo "=== [continue_task_stub] $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="

/usr/bin/perl -e 'alarm shift; exec @ARGV' "$STUB_CAP_SEC" \
  /opt/homebrew/bin/uv run python scripts/continue_task_stub.py &
STUB_PID=$!
wait $STUB_PID
STUB_RC=$?
if [ $STUB_RC -eq 142 ]; then
  echo "[HANG-KILLED] continue_task_stub.py exceeded ${STUB_CAP_SEC}s cap (SIGALRM)"
fi

echo "--- [continue_task_dispatch report] ---"
/usr/bin/perl -e 'alarm shift; exec @ARGV' "$STUB_CAP_SEC" \
  /opt/homebrew/bin/uv run python scripts/continue_task_dispatch.py --report &
DISPATCH_PID=$!
wait $DISPATCH_PID
DISPATCH_RC=$?
if [ $DISPATCH_RC -eq 142 ]; then
  echo "[HANG-KILLED] continue_task_dispatch.py exceeded ${STUB_CAP_SEC}s cap (SIGALRM)"
fi

echo "=== [continue_task_stub] exit stub=$STUB_RC dispatch=$DISPATCH_RC at $(date '+%Y-%m-%d %H:%M:%S %Z') (duration=${SECONDS}s) ==="

# Non-zero exit propagates to LaunchAgent / cron so host_cron_fail can detect
# either component's failure (previously the wrapper always exited 0).
if [ $STUB_RC -ne 0 ]; then
  exit $STUB_RC
fi
exit $DISPATCH_RC
