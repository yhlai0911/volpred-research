#!/bin/bash
# Compute Worker — drains the compute queue continuously (no Claude tokens).
#
# D6 (owner directive 2026-07-20): work-conserving drain loop with bounded
# parallelism (default min(3, cpu//3); override via `max_parallel` on the
# volpred-compute-worker entry in config/runtime_schedules.json). Operations
# Core's */15 tick is RESTART INSURANCE only. The wrapper launches the durable
# queue executor as a detached process and returns quickly so a long
# compute job can never block or outlive the scheduler's synchronous wrapper
# timeout. The queue flock still guarantees exactly one drain loop.
#
# Canonical: scripts/cron_compute_worker.sh
# TCC copy:  ~/.volpred/bin/cron_compute_worker.sh
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply

exec >> /Users/yhlai0911/.volpred/logs/compute_worker.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1

source /Users/yhlai0911/volpred-research/scripts/cron_lib.sh || exit 1
STARTED_AT=$SECONDS
cron_emit_start volpred-compute-worker

echo "[wrapper $(date '+%H:%M:%S')] DISPATCH label=operations-core.compute-worker pid=$$ fire_key=${VOLPRED_SCHEDULE_FIRE_KEY:-legacy}"
nohup /opt/homebrew/bin/uv run python scripts/compute_queue.py run-loop \
  >> /Users/yhlai0911/.volpred/logs/compute_worker.log 2>&1 </dev/null &
WORKER_PID=$!

# Popen succeeded once the child has a PID. It may legitimately exit
# immediately with rc=0 after losing the queue flock to an existing drain.
sleep 0.2
if kill -0 "$WORKER_PID" 2>/dev/null; then
  EXIT_CODE=0
  echo "[wrapper $(date '+%H:%M:%S')] DISPATCHED worker_pid=$WORKER_PID"
else
  wait "$WORKER_PID"
  EXIT_CODE=$?
  echo "[wrapper $(date '+%H:%M:%S')] CHILD_EXIT worker_pid=$WORKER_PID rc=$EXIT_CODE"
fi

cron_emit_exit volpred-compute-worker "$EXIT_CODE" "$STARTED_AT"
exit "$EXIT_CODE"
