#!/bin/bash
# Legacy codex_loop rollback entrypoint.
#
# The SessionStart hook still calls this file, but the 2026-07-26 Operations
# Core cutover made the old always-on loop a second independent dispatch clock.
# Default is therefore a deliberate no-op. An operator may temporarily restore
# the rollback path with VOLPRED_ENABLE_LEGACY_CODEX_LOOP=1 after first disabling
# agent_dispatch_tick in config/runtime_schedules.json.

set -e
REPO="${VOLPRED_REPO_ROOT:-/Users/yhlai0911/volpred-research}"
LOG="${VOLPRED_CODEX_LOOP_LOG:-/Users/yhlai0911/.volpred/logs/codex_loop.log}"
LOOP=$REPO/scripts/codex_loop.sh

mkdir -p "$(dirname "$LOG")"
if [ "${VOLPRED_ENABLE_LEGACY_CODEX_LOOP:-0}" != "1" ]; then
  echo "[auto_start_codex_loop] retired: Operations Core agent_dispatch_tick owns the clock" >> "$LOG"
  exit 0
fi

# Already running → no-op
if pgrep -f "scripts/codex_loop.sh" >/dev/null 2>&1; then
  exit 0
fi

# Codex CLI must be installed
if [ ! -x /Users/yhlai0911/.nvm/versions/node/v22.20.0/bin/codex ]; then
  echo "[auto_start_codex_loop] codex binary not found, skip" >> "$LOG"
  exit 0
fi

echo "[auto_start_codex_loop] launching at $(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"

# Detached background launch
nohup bash "$LOOP" >> "$LOG" 2>&1 < /dev/null &
disown $! 2>/dev/null || true

exit 0
