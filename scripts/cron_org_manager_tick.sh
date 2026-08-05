#!/bin/bash

# Canonical source for the launchd-safe wrapper installed at
# ~/.volpred/bin/cron_org_manager_tick.sh.
# P1 shadow phase: zero-cost hard-fact gate + receipt only, never spawns an LLM.
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/org_manager_tick.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source /Users/yhlai0911/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "org_manager_tick"
/opt/homebrew/bin/uv run python scripts/org/manager_tick.py --shadow
_ec=$?
cron_emit_exit "org_manager_tick" "$_ec" "$_start"
exit "$_ec"
