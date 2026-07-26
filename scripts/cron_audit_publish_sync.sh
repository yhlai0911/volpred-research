#!/bin/bash
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "audit_publish_sync"
/opt/homebrew/bin/uv run python scripts/audit_publish_sync.py 2>&1
EC=$?
if [ "audit_publish_sync" = "ops_dashboard" ]; then
  # also write snapshot
  /opt/homebrew/bin/uv run python scripts/audit_publish_sync.py > storage/ops/dashboard_latest.json 2>/dev/null
fi
cron_emit_exit "audit_publish_sync" "$EC" "$_start"
exit $EC
