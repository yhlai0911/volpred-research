#!/bin/bash

# Auto-injected: TCC bypass — self-redirect to log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/market_closure.log 2>&1
# Canonical source for the market-closure detector wrapper.
# Launched by LaunchAgent com.volpred.market-closure-detect (hourly), which execs
# the copy at ~/.volpred/bin/cron_market_closure.sh. After editing this file, sync:
#   uv run python scripts/sync_cron_wrappers.py --apply
#
# Why (2026-07-10): exchange_calendars is blind to same-day typhoon closures.
# This reads the NCDR/DGPA 停班停課 feed hourly; if 臺北市 is fully suspended it
# auto-writes config/market_closures_adhoc.json + re-syncs market_status + alerts,
# so the live banner flips to 休市 within ~1h (+5min cache) even for a same-day
# announcement — independent of the 00:03 daily_update run.
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "market_closure_detect"
/opt/homebrew/bin/uv run python scripts/detect_market_closure.py
_ec=$?
# exit 3 = NCDR source unreachable (fail-open; next hour retries). Not a cron
# failure — don't trip host_cron_fail on a transient upstream outage.
[ "$_ec" -eq 3 ] && _ec=0
cron_emit_exit "market_closure_detect" "$_ec" "$_start"
exit "$_ec"
