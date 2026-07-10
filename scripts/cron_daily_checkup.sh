#!/bin/bash
# 每日大體檢 cron wrapper（canonical source；用 scripts/sync_cron_wrappers.py --apply 安裝到 ~/.volpred/bin/）
cd /Users/yhlai0911/volpred-research || exit 1
exec /Users/yhlai0911/.local/bin/uv run python scripts/daily_checkup.py --alert
