#!/bin/bash
cd /Users/yhlai0911/volpred-research
echo "=== [ops_dashboard] start at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
/opt/homebrew/bin/uv run python scripts/ops_dashboard.py 2>&1
EC=$?
if [ "ops_dashboard" = "ops_dashboard" ]; then
  # also write snapshot
  /opt/homebrew/bin/uv run python scripts/ops_dashboard.py > storage/ops/dashboard_latest.json 2>/dev/null
fi
echo "=== [ops_dashboard] exit $EC at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exit $EC
