#!/bin/bash

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/ndc_indicator_refresh.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "ndc_indicator_refresh"
/opt/homebrew/bin/uv run python scripts/materialize_ndc_indicator_task.py
_ec=$?
cron_emit_exit "ndc_indicator_refresh" "$_ec" "$_start"
exit "$_ec"
