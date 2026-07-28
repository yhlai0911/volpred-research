#!/bin/bash

exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/refresh_paper_snapshots.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file directly — macOS TCC blocks
# cron daemon from exec'ing .sh files under Desktop/. Sync to ~/.volpred/bin/:
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "refresh_paper_snapshots"
/opt/homebrew/bin/uv run python scripts/refresh_paper_snapshots.py --apply
_ec=$?
cron_emit_exit "refresh_paper_snapshots" "$_ec" "$_start"
exit "$_ec"
