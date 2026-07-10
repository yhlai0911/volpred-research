#!/bin/bash

# Auto-injected: TCC bypass — self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/log_rotate.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec files under Desktop/ (macOS TCC/FDA blocks
# the cron daemon). The cron-exec target lives at ~/.volpred/bin/cron_log_rotate.sh.
# After editing this file, sync with:
#   cp scripts/cron_log_rotate.sh ~/.volpred/bin/ && chmod +x ~/.volpred/bin/cron_log_rotate.sh
#
# 目的：volpred 各 cron/LaunchAgent log 無 rotation 機制，codex_loop.log 曾達 46MB。
# 此 job 每日把超過 MAX_BYTES 的 log 截斷為最後 KEEP_LINES 行（原子替換，保留近期可觀測性）。

set -u

# Portable file size in bytes. BSD/macOS is `stat -f %z`; GNU/Linux is `stat -c %s`.
# GNU accepts `-f` with a wholly different meaning (--file-system) and prints a
# multi-line filesystem report, so a zero exit status alone proves nothing —
# validate the result is digits-only before trusting it. Same invariant as
# `file_mtime_epoch()` in cron_hourly_dispatch.sh, whose BSD-only `stat -f %m`
# silently rerouted the whole auth-preflight control flow on Linux (2026-07-10).
file_size_bytes() {
  local target=$1 value
  value=$(stat -c %s "$target" 2>/dev/null || true)
  case "$value" in
    ""|*[!0-9]*) value=$(stat -f %z "$target" 2>/dev/null || true) ;;
  esac
  case "$value" in
    ""|*[!0-9]*) return 1 ;;
  esac
  printf '%s\n' "$value"
}

MAX_BYTES=$((5 * 1024 * 1024))   # 5 MB 門檻
KEEP_LINES=4000                   # 截斷後保留最後 N 行

LOG_DIRS=(
  "/Users/yhlai0911/volpred-research/storage/logs/cron"
  "/Users/yhlai0911/.volpred/logs"
)

echo "=== [log_rotate] $(date '+%Y-%m-%d %H:%M:%S %Z') start ==="
rotated=0
for dir in "${LOG_DIRS[@]}"; do
  [ -d "$dir" ] || continue
  for f in "$dir"/*.log; do
    [ -f "$f" ] || continue
    if ! size=$(file_size_bytes "$f"); then
      echo "WARN: cannot read size of $f (stat unsupported?) — skipping rotation"
      continue
    fi
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
