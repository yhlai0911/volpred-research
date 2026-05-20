#!/bin/bash
# Hourly dispatch trigger via macOS LaunchAgent.
# Schedule: HH:07 every hour (24 slots/day). Reverted from 4-hourly per user
# directive 2026-05-16. Task scoping must fit ~50min cap (smaller units;
# heavy work goes to compute_queue.py for async worker pickup).
#
# Canonical source: scripts/cron_hourly_dispatch.sh + scripts/cron_hourly_dispatch_prompt.md
# TCC copy: ~/.volpred/bin/cron_hourly_dispatch.sh
# After editing: cp scripts/cron_hourly_dispatch.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_hourly_dispatch.sh

exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/hourly_dispatch.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

# Raise file-descriptor SOFT limit. LaunchAgent-spawned processes inherit
# launchd's default (soft 256 / hard unlimited — `launchctl limit maxfiles`)
# and DO NOT source the login profile, so claude -p crashes instantly with
# "low max file descriptors" (2026-05-20: 6/12 hourly runs failed this way).
# Interactive shells get 1048576 from the profile; headless runs must set it.
# Use -Sn (soft only) — hard is unlimited so the soft raise always succeeds.
ulimit -Sn 65536 2>/dev/null || true

# Enable job control so background subshells get their own process group;
# `kill -- -PGID` then propagates to all descendants (claude + its forks).
set -m

echo "=== hourly-dispatch $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# Cleanup trap: if launchd / external kill / shell error terminates parent
# mid-flight, ensure claude + watchdog don't orphan. Codex review 2026-05-14
# CRITICAL #2.
cleanup() {
  local exit_status=$?
  if [ -n "${CLAUDE_PID:-}" ] && kill -0 "$CLAUDE_PID" 2>/dev/null; then
    echo "[CLEANUP] parent exiting (status=$exit_status); killing claude PGID $CLAUDE_PID"
    kill -TERM -- "-$CLAUDE_PID" 2>/dev/null || kill -TERM "$CLAUDE_PID" 2>/dev/null
    sleep 2
    kill -KILL -- "-$CLAUDE_PID" 2>/dev/null || kill -KILL "$CLAUDE_PID" 2>/dev/null
  fi
  if [ -n "${WATCHDOG_PID:-}" ] && kill -0 "$WATCHDOG_PID" 2>/dev/null; then
    kill -KILL "$WATCHDOG_PID" 2>/dev/null
  fi
}
trap cleanup EXIT TERM INT HUP

# Read prompt from external file to avoid bash quoting hell with Chinese + backticks
PROMPT=$(cat /Users/yhlai0911/Desktop/volpred-research/scripts/cron_hourly_dispatch_prompt.md)

# Two-layer hang defense (50min hard cap, 60min interval - 10min buffer):
# Layer 1: perl alarm SIGALRM (verified working across exec on macOS 25.3:
#   `perl -e 'alarm 2; exec sleep 10'` → exit 142). Cheap, no extra process.
# Layer 2: background subshell + parent watchdog SIGTERM→SIGKILL. Belt-and-
#   suspenders if claude binary's node runtime installs its own SIGALRM
#   handler that ignores the signal (Gemini review 2026-05-14 concern).
# Prior hang incidents 2026-05-13 10:07 + 15:07 = strike 2 of three-strike;
# next hang triggers worker-daemon refactor per CLAUDE.md three-strike rule.
HOURLY_CAP_SEC=3000

/usr/bin/perl -e 'alarm shift; exec @ARGV' "$HOURLY_CAP_SEC" \
  /Users/yhlai0911/.local/bin/claude -p --dangerously-skip-permissions --model claude-sonnet-4-6 "$PROMPT" &
CLAUDE_PID=$!
# Capture claude binary path for PID-reuse race protection (Codex CRITICAL #3).
# Before signaling watchdog target, verify command name still matches.
CLAUDE_CMD_PATTERN="claude"

# Parent watchdog — fires only if perl alarm fails to deliver / claude ignored SIGALRM.
# Adds 60s grace beyond alarm cap, then SIGTERM (full PGID), then SIGKILL after 10s.
# PID reuse mitigation: verify `ps -p <PID> -o comm=` still matches CLAUDE_CMD_PATTERN.
(
  sleep $((HOURLY_CAP_SEC + 60))
  ACTUAL_CMD=$(ps -p "$CLAUDE_PID" -o comm= 2>/dev/null | tr -d '[:space:]')
  if kill -0 "$CLAUDE_PID" 2>/dev/null && [[ "$ACTUAL_CMD" == *"$CLAUDE_CMD_PATTERN"* ]]; then
    echo "[WATCHDOG] claude PID $CLAUDE_PID (cmd=$ACTUAL_CMD) alive past cap+60s; SIGTERM to PGID"
    kill -TERM -- "-$CLAUDE_PID" 2>/dev/null || kill -TERM "$CLAUDE_PID" 2>/dev/null
    sleep 10
    ACTUAL_CMD2=$(ps -p "$CLAUDE_PID" -o comm= 2>/dev/null | tr -d '[:space:]')
    if kill -0 "$CLAUDE_PID" 2>/dev/null && [[ "$ACTUAL_CMD2" == *"$CLAUDE_CMD_PATTERN"* ]]; then
      echo "[WATCHDOG] SIGTERM ignored; SIGKILL to PGID"
      kill -KILL -- "-$CLAUDE_PID" 2>/dev/null || kill -KILL "$CLAUDE_PID" 2>/dev/null
    fi
  elif [ -n "$ACTUAL_CMD" ] && [[ "$ACTUAL_CMD" != *"$CLAUDE_CMD_PATTERN"* ]]; then
    echo "[WATCHDOG] aborted — PID $CLAUDE_PID now belongs to '$ACTUAL_CMD' (PID reuse)"
  fi
) &
WATCHDOG_PID=$!

wait $CLAUDE_PID
EXIT_CODE=$?
# Watchdog cleanup is also handled by trap cleanup() as belt-and-suspenders.
kill $WATCHDOG_PID 2>/dev/null
WATCHDOG_PID=""  # mark consumed so trap doesn't double-kill a reused PID

if [ $EXIT_CODE -eq 142 ]; then
  echo "[HANG-KILLED] claude -p exceeded ${HOURLY_CAP_SEC}s cap (SIGALRM via perl alarm)"
elif [ $EXIT_CODE -eq 143 ] || [ $EXIT_CODE -eq 137 ]; then
  echo "[HANG-KILLED] claude -p killed by watchdog (SIGTERM=143 / SIGKILL=137)"
fi

echo "=== hourly-dispatch end $(date '+%Y-%m-%d %H:%M:%S %Z') (exit=$EXIT_CODE) ==="
# Canonical exit banner — host_cron_fail alert (src/volpred/ops/alerts.py
# _CRON_EXIT_RE) only recognises the `=== [<job>] exit <N> at <ts> ===` form.
# Without this line a failed hourly-dispatch run never alerts.
echo "=== [hourly_dispatch] exit $EXIT_CODE at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

# macOS notification (heredoc avoids nested-quote issues)
LATEST_COMMIT=$(/usr/bin/git -C /Users/yhlai0911/Desktop/volpred-research log -1 --pretty=format:'%h %s' 2>&1 | head -c 100 | tr -d '"\\')
NOW=$(date '+%H:%M')
/usr/bin/osascript <<OSAEND 2>/dev/null || true
display notification "${LATEST_COMMIT}" with title "volpred hourly-dispatch ${NOW}" sound name "Pop"
OSAEND
