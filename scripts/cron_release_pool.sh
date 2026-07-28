#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/release_pool.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_release_pool.sh. After editing this file,
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "release_pool"
/opt/homebrew/bin/uv run volpred ops release-pool-by-settings
_ec=$?
cron_emit_exit "release_pool" "$_ec" "$_start"
exit "$_ec"
