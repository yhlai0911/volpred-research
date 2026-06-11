#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/indicator_arena_daily.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_indicator_arena_daily.sh. After editing this file,
# sync with:   cp scripts/cron_indicator_arena_daily.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_indicator_arena_daily.sh
#
# Indicator Arena daily pipeline (task indicator_arena_phase1d_cron_job_2026_06_11):
# emit 6 indicator signals (ex-ante, idempotent) + resolve due outcome reviews
# + sync Supabase. 07:00 Taipei Mon-Sat (after US close ~05:00, before TW open
# 09:00). Non-zero exit (fetch failure / stale-data skip / sync fail) fires a
# warn alert — §4.5 skips must be visible, never silent.
cd /Users/yhlai0911/Desktop/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "indicator_arena_daily"
RESULT=$(/opt/homebrew/bin/uv run python scripts/indicator_arena_daily.py 2>&1)
_ec=$?
echo "$RESULT"
if [ "$_ec" -ne 0 ]; then
  /opt/homebrew/bin/uv run volpred ops send-alert \
    --level warn \
    --title "Indicator Arena daily pipeline: exit=$_ec (skip/failure present)" \
    --body "$(echo "$RESULT" | tail -c 4000)"
fi
cron_emit_exit "indicator_arena_daily" "$_ec" "$_start"
exit "$_ec"
