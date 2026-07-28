#!/bin/bash
# Compute Worker — drains the compute queue continuously (no Claude tokens).
#
# D6 (owner directive 2026-07-20): work-conserving drain loop with bounded
# parallelism (default min(3, cpu//3); override via `max_parallel` on the
# volpred-compute-worker entry in config/runtime_schedules.json). The launchd
# */15 tick is RESTART INSURANCE only: if a drain loop is already running, this
# invocation loses the flock worker mutex inside `run-loop` and exits
# immediately. Jobs sleeping on not_before are picked up by a later tick.
#
# Canonical: scripts/cron_compute_worker.sh
# TCC copy:  ~/.volpred/bin/cron_compute_worker.sh
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply

exec >> /Users/yhlai0911/.volpred/logs/compute_worker.log 2>&1
cd /Users/yhlai0911/volpred-research || exit 1

echo "[wrapper $(date '+%H:%M:%S')] STARTED label=com.volpred.compute-worker pid=$$"
trap 'echo "[wrapper $(date +%H:%M:%S)] EXIT rc=$?"' EXIT

/opt/homebrew/bin/uv run python scripts/compute_queue.py run-loop
