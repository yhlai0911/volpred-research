#!/bin/bash
set -euo pipefail

current="$(crontab -l 2>/dev/null || true)"
printf '%s\n' "$current" | grep -v 'volpred-scheduler-tick' | crontab -
echo "Removed volpred scheduler cron."
