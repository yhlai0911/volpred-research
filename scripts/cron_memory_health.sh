#!/bin/bash
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_memory_health.sh. After editing this file,
# sync with:   cp scripts/cron_memory_health.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_memory_health.sh
#
# Runs memory-health-summary daily; if status != ok, fire send-alert (24h dedup
# auto-handled by send-alert CLI). Prevents the 2026-04-10 knowledge.json bloat
# pattern (54.5MB / 50,304 entries / 96.4% duplicates) from recurring.
cd /Users/yhlai0911/Desktop/volpred-research
RESULT=$(/opt/homebrew/bin/uv run volpred ops memory-health-summary 2>&1)
echo "$RESULT"
STATUS=$(echo "$RESULT" | grep -oE 'overall=[a-z]+' | cut -d= -f2)
if [ "$STATUS" != "ok" ] && [ -n "$STATUS" ]; then
  /opt/homebrew/bin/uv run volpred ops send-alert \
    --level warn \
    --title "Memory health: status=$STATUS" \
    --body "$RESULT"
fi
