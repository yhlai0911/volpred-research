#!/bin/bash
cd /Users/yhlai0911/volpred-research
echo "=== [audit_publish_sync] start at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
/opt/homebrew/bin/uv run python scripts/audit_publish_sync.py 2>&1
EC=$?
if [ "audit_publish_sync" = "ops_dashboard" ]; then
  # also write snapshot
  /opt/homebrew/bin/uv run python scripts/audit_publish_sync.py > storage/ops/dashboard_latest.json 2>/dev/null
fi
echo "=== [audit_publish_sync] exit $EC at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exit $EC
