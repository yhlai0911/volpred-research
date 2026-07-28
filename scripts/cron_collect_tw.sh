#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/collect_tw.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_collect_tw.sh. After editing this file,
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "collect_tw"
/opt/homebrew/bin/uv run python scripts/collect_tw_data.py
_ec=$?
cron_emit_exit "collect_tw" "$_ec" "$_start"
exit "$_ec"
