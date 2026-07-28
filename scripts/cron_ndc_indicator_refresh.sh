#!/bin/bash

# Canonical source. Runtime copy:
#   ~/.volpred/bin/cron_ndc_indicator_refresh.sh
# Install after edits:
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/ndc_indicator_refresh.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "ndc_indicator_refresh"
/opt/homebrew/bin/uv run python scripts/collect_ndc_bci.py
_ec=$?
cron_emit_exit "ndc_indicator_refresh" "$_ec" "$_start"
exit "$_ec"
