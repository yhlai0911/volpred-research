#!/bin/bash
# Compute Worker — picks 1 queued compute job and runs it (no Claude tokens).
#
# Architecture: heavy CPU work (MLE, bootstrap, data fetch, backtest) decoupled
# from Claude decision/writing. Runs via cron */15 min; locks prevent concurrent
# runs. Each invocation: try acquire lock → find oldest queued job → run with
# timeout → mark completed/failed → release lock → exit.
#
# Canonical: scripts/cron_compute_worker.sh
# TCC copy:  ~/.volpred/bin/cron_compute_worker.sh
# After edit: cp scripts/cron_compute_worker.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_compute_worker.sh

exec >> /Users/yhlai0911/.volpred/logs/compute_worker.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

echo "=== compute-worker $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
/opt/homebrew/bin/uv run python scripts/compute_queue.py run-next
echo "=== compute-worker end $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
