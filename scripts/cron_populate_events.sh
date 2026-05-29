#!/bin/bash

# Auto-injected: TCC bypass
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/populate_events.log 2>&1
# Canonical source for the host-cron wrapper. cron-exec target at
# ~/.volpred/bin/cron_populate_events.sh. After editing this file:
#   cp scripts/cron_populate_events.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_populate_events.sh
cd /Users/yhlai0911/Desktop/volpred-research
echo "=== populate-upcoming-events $(date '+%Y-%m-%d %H:%M:%S') ==="
source /Users/yhlai0911/Desktop/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "populate_events"
/opt/homebrew/bin/uv run python scripts/populate_upcoming_events.py --apply
_ec=$?
cron_emit_exit "populate_events" "$_ec" "$_start"
exit "$_ec"
