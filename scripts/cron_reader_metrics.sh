#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/reader_metrics.log 2>&1
# Canonical source for the reader-metrics daily wrapper.
# Launched by LaunchAgent com.volpred.reader-metrics-daily (daily 06:30), which
# execs the copy at ~/.volpred/bin/cron_reader_metrics.sh (NOT host cron — macOS
# TCC blocks this process from modifying the crontab; LaunchAgents are the
# drift-free mechanism the other daily jobs use). After editing this file, sync:
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
#
# Why this job exists (2026-07-10): reader_metrics feeds daily_checkup's
# reader_metrics dimension (48h staleness threshold) + content decisions, but
# had NO scheduler — it only refreshed when someone ran the recovery by hand,
# so it silently went stale (last pull 2026-07-05 → 112h on 2026-07-10 checkup).
# A monitored metric with no producer is a process gap; this closes it.
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "reader_metrics_daily"
RESULT=$(/opt/homebrew/bin/uv run python scripts/pull_reader_metrics.py --top 20 --days 30 2>&1)
_ec=$?
echo "$RESULT"
if [ "$_ec" -ne 0 ]; then
  /opt/homebrew/bin/uv run volpred ops send-alert \
    --level warn \
    --title "reader_metrics pull failed (exit=$_ec)" \
    --body "每日 reader_metrics 拉取失敗（exit=$_ec）。recovery: uv run python scripts/pull_reader_metrics.py --top 20 --days 30。log: storage/logs/cron/reader_metrics.log"
fi
cron_emit_exit "reader_metrics_daily" "$_ec" "$_start"
exit "$_ec"
