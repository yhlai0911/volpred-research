#!/bin/bash

# Auto-injected: TCC bypass — self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/Desktop/volpred-research/storage/logs/cron/log_rotate.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec files under Desktop/ (macOS TCC/FDA blocks
# the cron daemon). The cron-exec target lives at ~/.volpred/bin/cron_log_rotate.sh.
# After editing this file, sync with:
#   cp scripts/cron_log_rotate.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_log_rotate.sh
#
# 目的：volpred 各 cron/LaunchAgent log 無 rotation 機制，codex_loop.log 曾達 46MB。
# 此 job 每日把超過 MAX_BYTES 的 log 截斷為最後 KEEP_LINES 行（原子替換，保留近期可觀測性）。

set -u

MAX_BYTES=$((5 * 1024 * 1024))   # 5 MB 門檻
KEEP_LINES=4000                   # 截斷後保留最後 N 行

LOG_DIRS=(
  "/Users/yhlai0911/Desktop/volpred-research/storage/logs/cron"
  "/Users/yhlai0911/.volpred/logs"
)

echo "=== [log_rotate] $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="
rotated=0
for dir in "${LOG_DIRS[@]}"; do
  [ -d "$dir" ] || continue
  for f in "$dir"/*.log; do
    [ -f "$f" ] || continue
    size=$(stat -f%z "$f" 2>/dev/null || echo 0)
    if [ "$size" -gt "$MAX_BYTES" ]; then
      tmp="${f}.rotate.$$"
      if tail -n "$KEEP_LINES" "$f" > "$tmp" 2>/dev/null; then
        mv "$tmp" "$f"
        echo "rotated: $f (was $((size/1024/1024))MB -> last ${KEEP_LINES} lines)"
        rotated=$((rotated + 1))
      else
        rm -f "$tmp"
        echo "WARN: rotate failed for $f"
      fi
    fi
  done
done
echo "=== [log_rotate] exit 0 ($rotated files rotated) at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
