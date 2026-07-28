#!/bin/bash
# Weekly reader-preference analysis (2026-07-15, Phase 1 owner directive).
# Runs Mondays 06:45 via piggy-back run_due_jobs (system_crontab item
# reader_preferences). Analyses article features x reader engagement and writes
# storage/analytics/reader_preferences.{json,md} for topic selection + figure/
# table usage guidance.
# TCC: cron daemon can't exec .sh under the repo path directly — the exec target
# is ~/.volpred/bin/cron_reader_preferences.sh. After editing this canonical
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/reader_preferences.log 2>&1
echo "[wrapper $(date '+%Y-%m-%d %H:%M:%S %Z')] STARTED reader_preferences pid=$$"
cd /Users/yhlai0911/volpred-research
exec /opt/homebrew/bin/uv run python scripts/analyze_reader_preferences.py --days 365
