#!/bin/bash
cd /Users/yhlai0911/volpred-research
echo "=== [audit_fb_pipeline] start at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
/opt/homebrew/bin/uv run python scripts/audit_fb_pipeline.py 2>&1
EC=$?
if [ "audit_fb_pipeline" = "ops_dashboard" ]; then
  # also write snapshot
  /opt/homebrew/bin/uv run python scripts/audit_fb_pipeline.py > storage/ops/dashboard_latest.json 2>/dev/null
fi
echo "=== [audit_fb_pipeline] exit $EC at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exit $EC
