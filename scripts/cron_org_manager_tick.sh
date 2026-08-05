#!/bin/bash

# Canonical source for the launchd-safe wrapper installed at
# ~/.volpred/bin/cron_org_manager_tick.sh.
# Live since 2026-08-05: the zero-cost hard-fact gate still runs first and skips
# without spawning anything; when it fires, it wakes the coordinator — its live
# cockpit pane if one is idle, otherwise one headless round under a lease.
# Roll back to observation-only by appending --shadow to the command below.
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/org_manager_tick.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source /Users/yhlai0911/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "org_manager_tick"
/opt/homebrew/bin/uv run python scripts/org/manager_tick.py
_ec=$?
cron_emit_exit "org_manager_tick" "$_ec" "$_start"
exit "$_ec"
