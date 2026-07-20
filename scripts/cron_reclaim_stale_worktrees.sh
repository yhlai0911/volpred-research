#!/bin/bash
# Stale-worktree salvage sweep — WS-I (work-artifact landing guarantee).
# Dry-run inventory of stale worktrees + the --open-tasks actuator: every held
# (dirty or unmerged) worktree becomes ONE idempotent P3 adjudication task
# (worktree_salvage_<name>) so stranded work reaches a decision-maker instead
# of rotting in a report nobody reads. DELIBERATELY NO --apply here: the
# destructive kill/remove path stays a manual, main-thread decision.
# Canonical source: scripts/reclaim_stale_worktrees.py
# Schedule: 25 */6 * * * via run_due_jobs piggy-back (config/runtime_schedules.json).
# TCC copy: ~/.volpred/bin/cron_reclaim_stale_worktrees.sh (sync_cron_wrappers.py --apply)

cd /Users/yhlai0911/volpred-research || exit 1

echo "=== [reclaim_stale_worktrees] start at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

PYTHON_BIN="/Users/yhlai0911/volpred-research/.venv/bin/python"
if [[ -x "$PYTHON_BIN" ]]; then
  PYTHON_RUN=("$PYTHON_BIN")
else
  PYTHON_RUN=(/opt/homebrew/bin/uv run python)
fi

# lsof over ~16 worktrees is the slow part; cap well under the piggy-back's
# subprocess budget so a wedged scan yields instead of blocking the fan-out.
/usr/bin/perl -e 'alarm shift; exec @ARGV' 180 \
  "${PYTHON_RUN[@]}" scripts/reclaim_stale_worktrees.py --open-tasks
EC=$?

echo "=== [reclaim_stale_worktrees] exit $EC at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exit $EC
