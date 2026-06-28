#!/bin/bash
# 自動 push 本機研究 commit 到 origin/main 備份
# 2026-06-24 建：雲端 routines (platform-ops-patrol / token-usage-daily-report) 已停用，
#   本地 Mac Studio 成為唯一 push 源 → push 永遠 fast-forward，簡單可靠。
# 根治 dual-source 分岔 incident（origin 從 6/14 停在遠端、本地積壓 1100+ commit 無備份）。
# 詳見 memory project_cloud_agent_git_divergence + docs/error_log.md。
set -uo pipefail
REPO=/Users/yhlai0911/Desktop/volpred-research
export HOME="${HOME:-/Users/yhlai0911}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export GH_CONFIG_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"
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
    --body "origin/main 領先本地 ${behind} commit，可能有未知 push 源（雲端 routines 應已全關）。自動 push 已暫停避免複雜 merge，需主線程檢查 RemoteTrigger list + git log。" >> "$LOG" 2>&1 || true
  exit 1
fi

# 2.5) silent-fallback gate (2026-06-28, boss「這問題一直無法解決」)
# CI Silent Fallback Gate 反覆紅的根因：codex/agent commit 帶新 silent fallback
# → push 上 origin → CI 才抓 → 紅信轟炸 boss。改成 push 前本地擋：HEAD 帶 new>0
# 就 hold push（紅碼永不到 origin、CI 不會紅），發 calmer warn 讓下一班 dispatch 先修。
# Fail-open：audit 本身出錯（uv 缺 / baseline 缺）→ 照推，備份優先不被 audit 故障擋。
AUDIT_OUT=$("$UV_BIN" run python "$REPO/scripts/audit_silent_fallbacks.py" --strict \
  --baseline "$REPO/storage/qa/silent_fallback_baseline.json" 2>&1)
AUDIT_RC=$?
NEW_COUNT=$(echo "$AUDIT_OUT" | grep -oE "new=[0-9]+" | head -1 | cut -d= -f2)
if [ "$AUDIT_RC" -ne 0 ] && [ -n "$NEW_COUNT" ] && [ "$NEW_COUNT" -gt 0 ]; then
  echo "[$(ts)] HELD: ${NEW_COUNT} new silent fallback(s) at HEAD — NOT pushing (CI would go red)" >> "$LOG"
  echo "$AUDIT_OUT" | grep "^NEW " >> "$LOG"
  NEWLINES=$(echo "$AUDIT_OUT" | grep "^NEW " | head -10)
  "$UV_BIN" run volpred ops send-alert --level warn \
    --title "git-push-backup: push held — ${NEW_COUNT} new silent fallback(s)" \
    --body "本地領先 ${ahead} commit 但 HEAD 帶 ${NEW_COUNT} 個新 silent fallback，push 會讓 CI Silent Fallback Gate 紅。已暫停 push（紅碼不上 origin、CI 不會紅）。下一班 hourly dispatch 必須先修（每處加 'from volpred.ops.diagnostics import warn' 再 fallback，或標 '# silent-ok: 理由'）再讓 push 恢復。新發現：
${NEWLINES}" >> "$LOG" 2>&1 || true
  exit 1
elif [ "$AUDIT_RC" -ne 0 ]; then
  echo "[$(ts)] WARN audit rc=$AUDIT_RC new=${NEW_COUNT:-?} — audit error not a fallback breach, pushing anyway (backup priority)" >> "$LOG"
fi

# 3) fast-forward push
if git_auth push origin main >> "$LOG" 2>&1; then
  echo "[$(ts)] pushed ${ahead} commit(s) OK" >> "$LOG"
  exit 0
else
  echo "[$(ts)] PUSH FAILED" >> "$LOG"
  "$UV_BIN" run volpred ops send-alert --level warn \
    --title "git-push-backup: push 失敗" \
    --body "git push origin main 失敗，本地領先 ${ahead} commit 未備份到遠端。需檢查認證 / 網路。" >> "$LOG" 2>&1 || true
  exit 1
fi
