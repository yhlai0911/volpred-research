#!/bin/bash
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_collect_us.sh. After editing this file,
# sync with:   cp scripts/cron_collect_us.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_collect_us.sh
cd /Users/yhlai0911/Desktop/volpred-research
exec /opt/homebrew/bin/uv run python scripts/collect_us_data.py
