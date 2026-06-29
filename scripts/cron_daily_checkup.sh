#!/bin/bash
# 每日大體檢 cron wrapper（canonical source；cp 到 ~/.volpred/bin/ 供 piggy-back 執行）
cd /Users/yhlai0911/Desktop/volpred-research || exit 1
exec /Users/yhlai0911/.local/bin/uv run python scripts/daily_checkup.py --alert
