#!/bin/bash
set -euo pipefail

REPO_ROOT="/Users/yhlai0911/Desktop/volpred-research"
CRON_LINE="*/10 * * * * $REPO_ROOT/scripts/run_scheduler_tick.sh # volpred-scheduler-tick"

current="$(crontab -l 2>/dev/null || true)"
filtered="$(printf '%s\n' "$current" | grep -v 'volpred-scheduler-tick' || true)"
{
  printf '%s\n' "$filtered" | sed '/^[[:space:]]*$/d'
  printf '%s\n' "$CRON_LINE"
} | crontab -

echo "Installed scheduler cron:"
echo "$CRON_LINE"
