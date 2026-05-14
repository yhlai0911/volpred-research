#!/bin/bash
# Hourly dispatch trigger via OS-level cron.
# Why: ScheduleWakeup in interactive session unreliable. OS cron + claude -p
# headless is reliable + diversity rules embedded in prompt file.
#
# Canonical source: scripts/cron_hourly_dispatch.sh + scripts/cron_hourly_dispatch_prompt.md
# TCC copy: ~/.volpred/bin/cron_hourly_dispatch.sh
# After editing: cp scripts/cron_hourly_dispatch.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_hourly_dispatch.sh

exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/hourly_dispatch.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

echo "=== hourly-dispatch $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# Read prompt from external file to avoid bash quoting hell with Chinese + backticks
PROMPT=$(cat /Users/yhlai0911/Desktop/volpred-research/scripts/cron_hourly_dispatch_prompt.md)

# Hard 50-min cap via perl alarm (macOS lacks `timeout`). If claude -p hangs,
# perl SIGALRM kills the exec'd child so the next hourly fire isn't blocked.
# Prior incidents (2026-05-13 10:07 and 15:07) ran ~17h before manual kill.
HOURLY_CAP_SEC=3000
/usr/bin/perl -e 'alarm shift; exec @ARGV' "$HOURLY_CAP_SEC" \
  /Users/yhlai0911/.local/bin/claude -p --dangerously-skip-permissions --model claude-sonnet-4-6 "$PROMPT"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 142 ] || [ $EXIT_CODE -eq 14 ]; then
  echo "[HANG-KILLED] claude -p exceeded ${HOURLY_CAP_SEC}s cap (SIGALRM)"
fi

echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=$EXIT_CODE) ==="

# macOS notification (heredoc avoids nested-quote issues)
LATEST_COMMIT=$(/usr/bin/git -C /Users/yhlai0911/Desktop/volpred-research log -1 --pretty=format:'%h %s' 2>&1 | head -c 100 | tr -d '"\\')
NOW=$(date '+%H:%M')
/usr/bin/osascript <<OSAEND 2>/dev/null || true
display notification "${LATEST_COMMIT}" with title "volpred hourly-dispatch ${NOW}" sound name "Pop"
OSAEND
