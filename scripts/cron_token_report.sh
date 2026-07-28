#!/bin/bash
# Daily token-usage job — the SOLE token cadence (one owner, one email/day; WS-H2).
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
#
# Step 1: token-usage-maintain persists the daily/weekly report JSON under
#         storage/reports/token_usage/ (moved here 2026-07-20 WS-H2 from the
#         retired token_usage_daily session cron, which depended on a live
#         Claude session and silently missed for days).
# Step 2: token_report_email.py renders + emails the multi-angle HTML report
#         (reads live JSONL directly, so a maintain failure degrades to
#         file-staleness, never to a missing email — logged loudly below).
REPO_ROOT="${VOLPRED_REPO_ROOT:-/Users/yhlai0911/volpred-research}"
UV_BIN="${UV_BIN:-/Users/yhlai0911/.local/bin/uv}"
LOG="${REPO_ROOT}/storage/logs/cron/token_report.log"
mkdir -p "$(dirname "$LOG")"
exec >> "$LOG" 2>&1
cd "$REPO_ROOT" || exit 1
echo "=== token-report $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
"$UV_BIN" run volpred ops token-usage-maintain --stub-if-no-work
MAINTAIN_EC=$?
if [ $MAINTAIN_EC -ne 0 ]; then
  echo "[token-report] WARN token-usage-maintain exit $MAINTAIN_EC — stored reports may be stale; email still renders from live JSONL"
fi
exec "$UV_BIN" run python "$REPO_ROOT/scripts/token_report_email.py"
