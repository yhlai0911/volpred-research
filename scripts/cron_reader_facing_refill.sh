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
/opt/homebrew/bin/uv run python scripts/refill_reader_facing_pool.py
_ec=$?
cron_emit_exit "reader_facing_refill" "$_ec" "$_start"
exit "$_ec"
