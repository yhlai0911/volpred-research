#!/bin/bash

# Canonical source for the launchd-safe wrapper installed at
# ~/.volpred/bin/cron_event_jobs_materialize.sh.
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/event_jobs_materialize.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source /Users/yhlai0911/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "event_jobs_materialize"
/opt/homebrew/bin/uv run python scripts/materialize_event_jobs.py
_ec=$?
cron_emit_exit "event_jobs_materialize" "$_ec" "$_start"
exit "$_ec"
