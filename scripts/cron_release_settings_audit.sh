#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/release_settings_audit.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_release_settings_audit.sh. After editing
# this file, sync with:
#   cp scripts/cron_release_settings_audit.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_release_settings_audit.sh
cd /Users/yhlai0911/Desktop/volpred-research
source /Users/yhlai0911/Desktop/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "release_settings_audit"
/opt/homebrew/bin/uv run python scripts/audit_release_settings.py --fix --json
_ec=$?
cron_emit_exit "release_settings_audit" "$_ec" "$_start"
exit "$_ec"
