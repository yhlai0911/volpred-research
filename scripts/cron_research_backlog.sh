#!/bin/bash
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/research_backlog.log 2>&1
# Canonical source. cron-exec target at ~/.volpred/bin/cron_research_backlog.sh
cd /Users/yhlai0911/Desktop/volpred-research
echo "=== research-backlog $(date '+%Y-%m-%d %H:%M:%S') ==="
exec /opt/homebrew/bin/uv run python scripts/generate_research_backlog.py --apply --max 5
