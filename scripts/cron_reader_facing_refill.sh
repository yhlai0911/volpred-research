#!/bin/bash
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/reader_facing_refill.log 2>&1
# Canonical source. cron-exec target at ~/.volpred/bin/cron_reader_facing_refill.sh
# After editing this file, sync with:
#   cp scripts/cron_reader_facing_refill.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_reader_facing_refill.sh
cd /Users/yhlai0911/Desktop/volpred-research
echo "=== reader-facing-refill $(date '+%Y-%m-%d %H:%M:%S') ==="
source /Users/yhlai0911/Desktop/volpred-research/scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "reader_facing_refill"
# 2026-05-29: trending 候選自動掃描走免費 agy（用戶指定無付費 API）。scanner 只 seed 主題；
# trending_repost 寫作 agent 仍強制 WebSearch 驗證 + 證據包。詳見 scripts/scan_trending_agy.py。
export VOLPRED_TRENDING_SCAN_CMD="/opt/homebrew/bin/uv run python scripts/scan_trending_agy.py"
/opt/homebrew/bin/uv run python scripts/refill_reader_facing_pool.py
_ec=$?
cron_emit_exit "reader_facing_refill" "$_ec" "$_start"
exit "$_ec"
