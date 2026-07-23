#!/bin/bash
# Hourly liveness reconciler — refactor_plan_ops_master_2026_07 §WS-A4.
# Compares next_tasks in-flight declarations against disk (worktree) + process
# (pid via dispatch_supervisor.procutil) reality, and re-pends claims that both
# facts prove detached. Canonical source: scripts/liveness_reconcile.py
# Schedule: 45 * * * * via run_due_jobs piggy-back (config/runtime_schedules.json).
# TCC copy: ~/.volpred/bin/cron_liveness_reconcile.sh

cd /Users/yhlai0911/volpred-research || exit 1

echo "=== [liveness_reconcile] start at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

PYTHON_BIN="/Users/yhlai0911/volpred-research/.venv/bin/python"
if [[ -x "$PYTHON_BIN" ]]; then
  PYTHON_RUN=("$PYTHON_BIN")
else
  PYTHON_RUN=(/opt/homebrew/bin/uv run python)
fi

# Cap well under the piggy-back's 240s subprocess budget: the reconciler only
# does a handful of `ps` probes and one locked pool write, so anything near the
# cap means something is wedged and the sweep should yield rather than block the
# rest of the hourly fan-out.
/usr/bin/perl -e 'alarm shift; exec @ARGV' 120 \
  "${PYTHON_RUN[@]}" scripts/liveness_reconcile.py --apply
EC=$?

echo "=== [liveness_reconcile] exit $EC at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exit $EC
