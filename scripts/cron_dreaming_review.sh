#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings); self-redirect to
# Desktop log avoids launchd-process-level TCC denial.
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/dreaming_review.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks the cron
# daemon from exec'ing .sh files under Desktop/. The cron-exec target lives at
# ~/.volpred/bin/cron_dreaming_review.sh. After editing this file, sync with:
#   uv run python scripts/sync_cron_wrappers.py --apply
#
# Loop-engineering slow loop (2026-06-29): daily cross-session failure-pattern
# review. dreaming_review.py writes storage/ops/dreaming/<date>.json, emails the
# boss on new findings/escalations, and ALWAYS exits 0 (reporting surface), so
# host_cron_fail never false-alarms on it.
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "dreaming_review"
/opt/homebrew/bin/uv run volpred ops dreaming-run
_ec=$?
cron_emit_exit "dreaming_review" "$_ec" "$_start"
exit "$_ec"
