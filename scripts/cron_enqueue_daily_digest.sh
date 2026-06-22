#!/bin/bash
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/enqueue_daily_digest.log 2>&1
# Canonical source. cron-exec target at ~/.volpred/bin/cron_enqueue_daily_digest.sh
# IMPORTANT: host cron does NOT exec files under Desktop/ (macOS TCC blocks the
# cron daemon). After editing this file, sync with:
#   cp scripts/cron_enqueue_daily_digest.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_enqueue_daily_digest.sh
#
# 目的（boss directive 2026-06-22「每日精選導讀是例行任務」）：每天 09:00 台北把一個
# daily_digest P1 任務冪等地排進 next_tasks，讓 hourly dispatch 接手寫作+發佈。
# 冪等：今日已發 digest 或池中已有今日 digest 任務 → skip（見 enqueue_daily_digest.py）。
# 由 piggy-back run_due_jobs 執行（host cron 只可靠 0 * * * *；0 9 * * * 走 piggy-back）。
cd /Users/yhlai0911/Desktop/volpred-research
source /Users/yhlai0911/Desktop/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "enqueue_daily_digest"
/opt/homebrew/bin/uv run python scripts/enqueue_daily_digest.py
_ec=$?
cron_emit_exit "enqueue_daily_digest" "$_ec" "$_start"
exit "$_ec"
