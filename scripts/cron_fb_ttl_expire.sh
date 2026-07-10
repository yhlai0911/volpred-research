#!/bin/bash
# FB TTL auto-expire: flip awaiting_interactive_session > 14d → wont_fix.
# Final purge after audit_fb_pipeline's 48h expired_skip pass — clears the
# verification_fb_pipeline dashboard awaiting count for items that the
# personal-FB Chrome MCP workflow effectively abandoned.
#
# Canonical script — runtime copy at ~/.volpred/bin/cron_fb_ttl_expire.sh
# (macOS TCC requires wrappers under HOME, not Desktop). Sync after edit:
#   uv run python scripts/sync_cron_wrappers.py --apply
cd /Users/yhlai0911/volpred-research
echo "=== [fb_ttl_expire] start at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
/opt/homebrew/bin/uv run python scripts/mark_fb_post_status.py --auto-expire 14 2>&1
EC=$?
echo "=== [fb_ttl_expire] exit $EC at $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
exit $EC
