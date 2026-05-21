#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA, self-redirect to Desktop log
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/paper_sync_all.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file directly — macOS TCC (FDA)
# blocks cron daemon from exec'ing .sh files under Desktop/. The cron-exec
# target lives at ~/.volpred/bin/cron_paper_sync_all.sh. After editing this
# file, sync with:
#   cp scripts/cron_paper_sync_all.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_paper_sync_all.sh
cd /Users/yhlai0911/Desktop/volpred-research
echo "=== paper-sync-all $(date '+%Y-%m-%d %H:%M:%S') ==="
exec /opt/homebrew/bin/uv run volpred ops paper-sync-all
