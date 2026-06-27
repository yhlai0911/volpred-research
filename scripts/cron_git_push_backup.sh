#!/bin/bash
# 自動 push 本機研究 commit 到 origin/main 備份
# 2026-06-24 建：雲端 routines (platform-ops-patrol / token-usage-daily-report) 已停用，
#   本地 Mac Studio 成為唯一 push 源 → push 永遠 fast-forward，簡單可靠。
# 根治 dual-source 分岔 incident（origin 從 6/14 停在遠端、本地積壓 1100+ commit 無備份）。
# 詳見 memory project_cloud_agent_git_divergence + docs/error_log.md。
set -uo pipefail
REPO=/Users/yhlai0911/Desktop/volpred-research
UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"
GH_BIN="${GH_BIN:-/opt/homebrew/bin/gh}"
cd "$REPO" || exit 1
LOG="$REPO/storage/logs/cron/git_push_backup.log"
mkdir -p "$(dirname "$LOG")"
ts() { TZ='Asia/Taipei' date '+%Y-%m-%d %H:%M:%S'; }
git_auth() {
  git \
    -c credential.helper= \
    -c "credential.https://github.com.helper=!$GH_BIN auth git-credential" \
    "$@"
}

echo "=== git-push-backup $(ts) ===" >> "$LOG"

# 1) 只在有未 push commit 時才動作
ahead=$(git rev-list --count origin/main..main 2>/dev/null)
if [ -z "$ahead" ] || [ "$ahead" = "0" ]; then
  echo "[$(ts)] nothing to push (ahead=${ahead:-?})" >> "$LOG"
  exit 0
fi

# 2) fetch 確認沒有未知 push 源造成分岔（雲端已關，理論上永遠 0）
git_auth fetch origin main >> "$LOG" 2>&1
behind=$(git rev-list --count main..origin/main 2>/dev/null)
if [ -n "$behind" ] && [ "$behind" != "0" ]; then
  # 偵測到分岔 → 不強推，發 alert 讓主線程處理（絕不 force / 絕不自動複雜 merge）
  echo "[$(ts)] WARN: remote ahead by $behind — divergence, NOT pushing" >> "$LOG"
  "$UV_BIN" run volpred ops send-alert --level warn \
    --title "git-push-backup: 偵測到 origin 分岔" \
    --body-md "origin/main 領先本地 ${behind} commit，可能有未知 push 源（雲端 routines 應已全關）。自動 push 已暫停避免複雜 merge，需主線程檢查 RemoteTrigger list + git log。" >> "$LOG" 2>&1 || true
  exit 1
fi

# 3) fast-forward push
if git_auth push origin main >> "$LOG" 2>&1; then
  echo "[$(ts)] pushed ${ahead} commit(s) OK" >> "$LOG"
  exit 0
else
  echo "[$(ts)] PUSH FAILED" >> "$LOG"
  "$UV_BIN" run volpred ops send-alert --level warn \
    --title "git-push-backup: push 失敗" \
    --body-md "git push origin main 失敗，本地領先 ${ahead} commit 未備份到遠端。需檢查認證 / 網路。" >> "$LOG" 2>&1 || true
  exit 1
fi
