#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/drain_failed_syncs.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_drain_failed_syncs.sh. After editing this file,
# sync with:   cp scripts/cron_drain_failed_syncs.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_drain_failed_syncs.sh
#
# Drains the .failed_supabase_syncs.json dead-letter queue (re-sync transient
# Supabase sync failures, remove successes). Structural fix 2026-06-02: the
# queue was write-only with no consumer, so transient blips accumulated until
# manual intervention. See scripts/drain_failed_supabase_syncs.py.
cd /Users/yhlai0911/Desktop/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "drain_failed_syncs"
/opt/homebrew/bin/uv run python scripts/drain_failed_supabase_syncs.py
_ec=$?
cron_emit_exit "drain_failed_syncs" "$_ec" "$_start"
exit "$_ec"
