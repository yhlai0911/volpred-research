#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/daily_update.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_daily_update.sh. After editing this file,
# sync with:   cp scripts/cron_daily_update.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_daily_update.sh
cd /Users/yhlai0911/Desktop/volpred-research

# Single-fire lock (belt-and-suspenders). daily_update double-published the
# 08:03 article on 2026-05-21/22 because it fired from BOTH host crontab and
# the com.volpred.daily-update LaunchAgent — two concurrent runs each passed
# the freshness guard before the other wrote feed.json. The host crontab
# entry is now removed (host_crontab_managed:false); this mkdir lock (atomic,
# no flock dependency) guarantees no overlap even if a job ever double-fires.
LOCKDIR=/tmp/volpred_daily_update.lock
if ! mkdir "$LOCKDIR" 2>/dev/null; then
  echo "=== [daily_update] $(date '+%Y-%m-%dT%H:%M:%S%z') skip — 另一 run 持有 lock ==="
  exit 0
fi
trap 'rmdir "$LOCKDIR" 2>/dev/null' EXIT

# Emit the canonical exit banner the host_cron_fail alert reads
# (src/volpred/ops/alerts.py _CRON_EXIT_RE). daily_update is in
# run_due_jobs SKIP_JOB_IDS, so the piggy-back dispatcher never writes
# its banner — without this the alert read a frozen 2026-04-25 exit 0
# and a crashing daily_update (e.g. 2026-05-19 JSONDecodeError) alerted
# nobody. NOT `exec` — the shell must survive to write the banner.
_start=$(date +%s)
/opt/homebrew/bin/uv run python scripts/daily_update.py
_ec=$?
echo "=== [daily_update] exit ${_ec} at $(date '+%Y-%m-%dT%H:%M:%S%z') (duration=$(($(date +%s) - _start))s) ==="
exit ${_ec}
