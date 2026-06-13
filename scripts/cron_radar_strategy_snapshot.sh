#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/radar_strategy_snapshot.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The piggy-back dispatcher
# (run_due_jobs.py) execs ~/.volpred/bin/cron_radar_strategy_snapshot.sh.
# After editing this file, sync with:
#   cp scripts/cron_radar_strategy_snapshot.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_radar_strategy_snapshot.sh
cd /Users/yhlai0911/Desktop/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "radar_strategy_snapshot"
/opt/homebrew/bin/uv run python scripts/radar_strategy_snapshot_daily.py
_ec=$?
cron_emit_exit "radar_strategy_snapshot" "$_ec" "$_start"
exit "$_ec"
