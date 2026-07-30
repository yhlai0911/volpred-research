#!/bin/bash

# Auto-injected: TCC bypass — self-redirect to Desktop log avoids launchd-process-level TCC denial
LOG_ROTATE_STDIO_PATH=${VOLPRED_LOG_ROTATE_STDIO_PATH:-/Users/yhlai0911/volpred-research/storage/logs/cron/log_rotate.log}
exec >> "$LOG_ROTATE_STDIO_PATH" 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec files under Desktop/ (macOS TCC/FDA blocks
# the cron daemon). The cron-exec target lives at ~/.volpred/bin/cron_log_rotate.sh.
# After editing this file, sync with:
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
#
# 目的：volpred 各 cron/LaunchAgent log 無 rotation 機制，codex_loop.log 曾達 46MB。
# 此 job 每日把超過 MAX_BYTES 的 log 截斷為最後 KEEP_LINES 行（原子替換，保留近期可觀測性）。

set -u
umask 077

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

# Portable permission bits. A replaced log inode must not inherit the shell's
# default umask and become world-readable between rotation and the daemon's
# next append (Telegram logs can contain boss-message excerpts).
file_mode_bits() {
  local target=$1 value
  value=$(stat -c %a "$target" 2>/dev/null || true)
  case "$value" in
    ""|*[!0-9]*) value=$(stat -f %Lp "$target" 2>/dev/null || true) ;;
  esac
  case "$value" in
    ""|*[!0-9]*|*[!0-7]*) return 1 ;;
  esac
  printf '%s\n' "$value"
}

MAX_BYTES=${VOLPRED_LOG_ROTATE_MAX_BYTES:-$((5 * 1024 * 1024))}   # 5 MB 門檻
KEEP_LINES=${VOLPRED_LOG_ROTATE_KEEP_LINES:-4000}                   # 截斷後保留最後 N 行
case "$MAX_BYTES:$KEEP_LINES" in
  *[!0-9:]*|:*|*:) echo "ERROR: invalid log rotation numeric override"; exit 2 ;;
esac

if [ -n "${VOLPRED_LOG_ROTATE_LOG_DIR:-}" ]; then
  LOG_DIRS=("$VOLPRED_LOG_ROTATE_LOG_DIR")
else
  LOG_DIRS=(
    "/Users/yhlai0911/volpred-research/storage/logs/cron"
    "/Users/yhlai0911/.volpred/logs"
  )
fi

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
      mode=$(file_mode_bits "$f" || printf '600\n')
      if tail -n "$KEEP_LINES" "$f" > "$tmp" 2>/dev/null; then
        if ! chmod "$mode" "$tmp"; then
          rm -f "$tmp"
          echo "WARN: rotate chmod failed for $f"
          continue
        fi
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
# --- Retention（2026-07-14 refactor_plan_token_ops_waste WS3a）---
# 累積性目錄的裁切收編進本 job（anti-stacking：log_rotate 是唯一 retention owner）。
# rollback_points：session 級重構安全網，超過 14 天的 session 早已結束，無復原價值
#（2026-07-14 盤點：81 目錄 1.7GB 全部停在 5/18，從未有清理機制）。
# logs/hooks：hook debug tail，7 天後無診斷價值（盤點：4,549 檔自 4/25 累積未輪替）。
RB_DIR="/Users/yhlai0911/volpred-research/storage/ops/rollback_points"
HOOKS_LOG_DIR="/Users/yhlai0911/volpred-research/storage/logs/hooks"

if [ "${VOLPRED_LOG_ROTATE_SKIP_RETENTION:-0}" = "1" ]; then
  echo "retention: skipped by explicit test override"
elif [ -d "$RB_DIR" ]; then
  rb_n=$(find "$RB_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +14 | wc -l | tr -d ' ')
  if [ "$rb_n" -gt 0 ]; then
    find "$RB_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
    echo "retention: rollback_points pruned $rb_n dirs (>14d)"
  fi
fi

if [ "${VOLPRED_LOG_ROTATE_SKIP_RETENTION:-0}" != "1" ] && [ -d "$HOOKS_LOG_DIR" ]; then
  hk_n=$(find "$HOOKS_LOG_DIR" -type f -mtime +7 | wc -l | tr -d ' ')
  if [ "$hk_n" -gt 0 ]; then
    find "$HOOKS_LOG_DIR" -type f -mtime +7 -delete
    echo "retention: hooks logs pruned $hk_n files (>7d)"
  fi
fi

echo "=== [log_rotate] exit 0 ($rotated files rotated) at $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
