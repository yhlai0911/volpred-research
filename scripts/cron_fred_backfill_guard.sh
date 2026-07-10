#!/bin/bash
# Self-healing FRED daily-rate backfill guard (2026-05-29).
# Runs */30 until the 4/16 stale gap closes, then self-noops when fresh.
# TCC: cron daemon can't exec .sh under Desktop/ — exec target is
# ~/.volpred/bin/cron_fred_backfill_guard.sh. After editing this canonical
# source: uv run python scripts/sync_cron_wrappers.py --apply
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/fred_backfill_guard.log 2>&1
cd /Users/yhlai0911/volpred-research
echo "=== [fred_backfill_guard] fire $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
exec /opt/homebrew/bin/uv run python scripts/fred_backfill_guard.py
