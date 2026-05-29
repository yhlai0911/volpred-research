#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/market_cal.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_market_cal.sh. After editing this file,
# sync with:   cp scripts/cron_market_cal.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_market_cal.sh
cd /Users/yhlai0911/Desktop/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "market_cal"
/opt/homebrew/bin/uv run python -m volpred.market_calendar sync
_ec=$?
cron_emit_exit "market_cal" "$_ec" "$_start"
exit "$_ec"
