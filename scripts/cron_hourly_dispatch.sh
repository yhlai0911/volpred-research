#!/bin/bash
# 4-hourly dispatch trigger via macOS LaunchAgent.
# Schedule: 00:07 / 04:07 / 08:07 / 12:07 / 16:07 / 20:07 CST (6 slots/day).
# Why 4h: every fire MUST FULLY complete its dispatched task before stopping
# (no partial work tossed to next slot). 4h gap gives agent room to finish.
# Filename still says "hourly" (file rename has TCC + plist downstream costs;
# behavior change documented here + in prompt file + memory feedback).
#
# Canonical source: scripts/cron_hourly_dispatch.sh + scripts/cron_hourly_dispatch_prompt.md
# TCC copy: ~/.volpred/bin/cron_hourly_dispatch.sh
# After editing: cp scripts/cron_hourly_dispatch.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_hourly_dispatch.sh

exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/hourly_dispatch.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

echo "=== hourly-dispatch $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# Read prompt from external file to avoid bash quoting hell with Chinese + backticks
PROMPT=$(cat /Users/yhlai0911/Desktop/volpred-research/scripts/cron_hourly_dispatch_prompt.md)

# Two-layer hang defense (3.5h hard cap, 4h interval - 30min buffer):
# Layer 1: perl alarm SIGALRM (verified working across exec on macOS 25.3:
#   `perl -e 'alarm 2; exec sleep 10'` → exit 142). Cheap, no extra process.
# Layer 2: background subshell + parent watchdog SIGTERM→SIGKILL. Belt-and-
#   suspenders if claude binary's node runtime installs its own SIGALRM
#   handler that ignores the signal (Gemini review 2026-05-14 concern).
# Prior hang incidents 2026-05-13 10:07 + 15:07 = strike 2 of three-strike;
# next hang triggers worker-daemon refactor per CLAUDE.md three-strike rule.
HOURLY_CAP_SEC=12600

/usr/bin/perl -e 'alarm shift; exec @ARGV' "$HOURLY_CAP_SEC" \
  /Users/yhlai0911/.local/bin/claude -p --dangerously-skip-permissions --model claude-sonnet-4-6 "$PROMPT" &
CLAUDE_PID=$!

# Parent watchdog — fires only if perl alarm fails to deliver / claude ignored SIGALRM.
# Adds 60s grace beyond alarm cap, then SIGTERM, then SIGKILL after 10s.
(
  sleep $((HOURLY_CAP_SEC + 60))
  if kill -0 $CLAUDE_PID 2>/dev/null; then
    echo "[WATCHDOG] claude -p PID $CLAUDE_PID still alive past cap+60s; sending SIGTERM"
    kill -TERM $CLAUDE_PID 2>/dev/null
    sleep 10
    if kill -0 $CLAUDE_PID 2>/dev/null; then
      echo "[WATCHDOG] SIGTERM ignored; sending SIGKILL"
      kill -KILL $CLAUDE_PID 2>/dev/null
    fi
  fi
) &
WATCHDOG_PID=$!

wait $CLAUDE_PID
EXIT_CODE=$?
kill $WATCHDOG_PID 2>/dev/null  # Cleanup watchdog if claude finished normally.

if [ $EXIT_CODE -eq 142 ]; then
  echo "[HANG-KILLED] claude -p exceeded ${HOURLY_CAP_SEC}s cap (SIGALRM via perl alarm)"
elif [ $EXIT_CODE -eq 143 ] || [ $EXIT_CODE -eq 137 ]; then
  echo "[HANG-KILLED] claude -p killed by watchdog (SIGTERM=143 / SIGKILL=137)"
fi

echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=$EXIT_CODE) ==="

# macOS notification (heredoc avoids nested-quote issues)
LATEST_COMMIT=$(/usr/bin/git -C /Users/yhlai0911/Desktop/volpred-research log -1 --pretty=format:'%h %s' 2>&1 | head -c 100 | tr -d '"\\')
NOW=$(date '+%H:%M')
/usr/bin/osascript <<OSAEND 2>/dev/null || true
display notification "${LATEST_COMMIT}" with title "volpred hourly-dispatch ${NOW}" sound name "Pop"
OSAEND
