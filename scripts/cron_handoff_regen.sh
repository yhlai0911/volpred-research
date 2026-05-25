#!/bin/bash
# Hourly handoff regenerator — writes storage/ops/handoff_latest.md.
# Schedule: 50 * * * * via host crontab (10 min before hourly-dispatch fires at :07).
# Canonical source: scripts/generate_handoff.py
# TCC copy: ~/.volpred/bin/cron_handoff_regen.sh

exec >> /Users/yhlai0911/.volpred/logs/handoff_regen.log 2>&1
cd /Users/yhlai0911/Desktop/volpred-research || exit 1

ulimit -Sn 65536 2>/dev/null || true

echo "=== handoff-regen $(date '+%Y-%m-%d %H:%M:%S %Z') ==="

/usr/bin/perl -e 'alarm shift; exec @ARGV' 60 \
  /Users/yhlai0911/.local/bin/uv run python /Users/yhlai0911/Desktop/volpred-research/scripts/generate_handoff.py
RC1=$?

# Also: cleanup stale claims (>2h) so claim mechanism self-heals.
# 2h chosen because hourly-dispatch cap = 50min and Codex sessions are
# usually short-lived in VSCode; a 2h-stuck claim almost certainly = crash
# or forgotten release rather than legitimate long work.
/Users/yhlai0911/.local/bin/uv run python /Users/yhlai0911/Desktop/volpred-research/scripts/task_pool_claim.py cleanup --stale-hours 2
RC2=$?

EXIT_CODE=$((RC1 + RC2))
echo "=== handoff-regen end $(date '+%Y-%m-%d %H:%M:%S %Z') (rc1=$RC1 rc2=$RC2 exit=$EXIT_CODE) ==="
echo "=== [handoff_regen] exit $EXIT_CODE at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
