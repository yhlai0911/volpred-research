#!/bin/bash

exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/refresh_paper_snapshots.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file directly — macOS TCC blocks
# cron daemon from exec'ing .sh files under Desktop/. Sync to ~/.volpred/bin/:
#   cp scripts/cron_refresh_paper_snapshots.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_refresh_paper_snapshots.sh
cd /Users/yhlai0911/Desktop/volpred-research
exec /opt/homebrew/bin/uv run python scripts/refresh_paper_snapshots.py --apply
