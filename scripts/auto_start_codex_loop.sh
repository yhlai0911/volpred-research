#!/bin/bash
# Auto-start codex_loop on Claude Code session start.
# Idempotent: if already running, do nothing. Detached so Claude session
# startup is not blocked and loop survives Claude session end.
#
# Wired via SessionStart hook in .claude/settings.json.
# Stop manually: pkill -f 'scripts/codex_loop.sh'

set -e
REPO=/Users/yhlai0911/Desktop/volpred-research
LOG=/Users/yhlai0911/.volpred/logs/codex_loop.log
LOOP=$REPO/scripts/codex_loop.sh

# Already running → no-op
if pgrep -f "scripts/codex_loop.sh" >/dev/null 2>&1; then
  exit 0
fi

# Codex CLI must be installed
if [ ! -x /Users/yhlai0911/.nvm/versions/node/v22.20.0/bin/codex ]; then
  echo "[auto_start_codex_loop] codex binary not found, skip" >> "$LOG"
  exit 0
fi

mkdir -p "$(dirname "$LOG")"
echo "[auto_start_codex_loop] launching at $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"

# Detached background launch
nohup bash "$LOOP" >> "$LOG" 2>&1 < /dev/null &
disown $! 2>/dev/null || true

exit 0
