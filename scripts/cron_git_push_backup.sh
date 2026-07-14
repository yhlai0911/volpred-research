#!/bin/bash
# 自動 push 本機研究 commit 到 origin/main 備份
# 2026-06-24 建：雲端 routines (platform-ops-patrol / token-usage-daily-report) 已停用，
#   本地 Mac Studio 成為唯一 push 源 → push 永遠 fast-forward，簡單可靠。
# 根治 dual-source 分岔 incident（origin 從 6/14 停在遠端、本地積壓 1100+ commit 無備份）。
# 詳見 memory project_cloud_agent_git_divergence + docs/error_log.md。
set -uo pipefail
REPO=/Users/yhlai0911/volpred-research
export HOME="${HOME:-/Users/yhlai0911}"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"
export GH_CONFIG_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"
UV_BIN="${UV_BIN:-/opt/homebrew/bin/uv}"
GH_BIN="${GH_BIN:-/opt/homebrew/bin/gh}"
cd "$REPO" || exit 1
LOG="$REPO/storage/logs/cron/git_push_backup.log"
mkdir -p "$(dirname "$LOG")"
ts() { TZ='Asia/Taipei' date '+%Y-%m-%d %H:%M:%S'; }
# shellcheck disable=SC1091
source "$REPO/scripts/cron_lib.sh"
# 2026-06-30 (hourly-15 host_cron_fail root cause): wrapper 沒走 cron_lib
# 標準 emit_exit banner → alerts.py `_latest_cron_exit` 永遠讀到上一次 exit=1
# 即便 push 成功也不會 heal。違反 .claude/rules/hooks-exit-code.md。trap EXIT
# 確保即便 set -uo pipefail 提早 exit 也 emit。
_GPB_START=$SECONDS
if [ "${VOLPRED_SUPPRESS_PUSH_ALERTS:-0}" = "1" ]; then
  # On-demand CI remediation is not a scheduled git_push_backup fire. Recording
  # its real rc in cron_emit_exit would make the generic host_cron_fail owner send
  # a second intermediate alert after the CI watcher deliberately stayed quiet.
  trap 'rc=$?; echo "=== [git_push_backup] ci-remediation exit $rc at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"' EXIT
  echo "=== [git_push_backup] ci-remediation start at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" >> "$LOG"
else
  trap 'cron_emit_exit "git_push_backup" "$?" "$_GPB_START" >> "$LOG" 2>&1' EXIT
  cron_emit_start "git_push_backup" >> "$LOG"
fi
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
  if [ "${VOLPRED_SUPPRESS_PUSH_ALERTS:-0}" != "1" ]; then
    "$UV_BIN" run volpred ops send-alert --level warn \
      --title "git-push-backup: 偵測到 origin 分岔" \
      --body "origin/main 領先本地 ${behind} commit，可能有未知 push 源（雲端 routines 應已全關）。自動 push 已暫停避免複雜 merge，需主線程檢查 RemoteTrigger list + git log。" >> "$LOG" 2>&1 || true
  else
    echo "[$(ts)] child alert suppressed — CI incident watcher owns terminal notification" >> "$LOG"
  fi
  exit 1
fi

# 2.5) silent-fallback gate (2026-06-28, boss「這問題一直無法解決」)
# CI Silent Fallback Gate 反覆紅的根因：codex/agent commit 帶新 silent fallback
# → push 上 origin → CI 才抓 → 紅信轟炸 boss。改成 push 前本地擋：HEAD 帶 new>0
# 就 hold push（紅碼永不到 origin、CI 不會紅），建立固定 P1 給當班修；首次與
# 修復進行中不寄信（per feedback_fix_silent_fallback_immediately）。
# Fail-open：audit 本身出錯（uv 缺 / baseline 缺）→ 照推，備份優先不被 audit 故障擋。
#
# 2026-07-15: --rev HEAD。此 repo 的 checkout 是共享的（多 dispatch slot + 互動
# session + codex-vscode 同時在同一棵樹上工作），而這個 gate 判的是「即將 push 的
# 那個 commit」。掃工作區等於把別人**還沒 commit** 的在途編輯算到 HEAD 頭上：
# 2026-07-14 夜間 4 個乾淨 commit 被擋了一整晚，NEW 三行全部來自另一個 session
# 未提交的 diff（HEAD 本身 new=0），而 alert 卻寫著「HEAD 帶 3 個」。量錯樹 =
# 假陽性 hold + 假的 P1 修復任務。
AUDIT_STARTED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
AUDIT_OUT=$("$UV_BIN" run python "$REPO/scripts/audit_silent_fallbacks.py" --strict \
  --rev HEAD \
  --baseline "$REPO/storage/qa/silent_fallback_baseline.json" 2>&1)
AUDIT_RC=$?
AUDIT_FINISHED_AT=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
NEW_COUNT=$(echo "$AUDIT_OUT" | grep -oE "new=[0-9]+" | head -1 | cut -d= -f2)
if [ "$AUDIT_RC" -ne 0 ] && [ -n "$NEW_COUNT" ] && [ "$NEW_COUNT" -gt 0 ]; then
  echo "[$(ts)] HELD: ${NEW_COUNT} new silent fallback(s) at HEAD — NOT pushing (CI would go red)" >> "$LOG"
  echo "$AUDIT_OUT" | grep "^NEW " >> "$LOG"
  NEWLINES=$(echo "$AUDIT_OUT" | grep "^NEW " | head -10)
  # The hold and its silent-fallback NEW cause are one root incident.  Even a
  # CI-owned invocation must create the P1; it suppresses only child transport.
  INTERNAL_ROUTE_ARGS=(--internal-remediable-key git_push_backup_hold \
    --observed-at "$AUDIT_STARTED_AT" --level warn)
  if [ "${VOLPRED_SUPPRESS_PUSH_ALERTS:-0}" = "1" ]; then
    INTERNAL_ROUTE_ARGS+=(--suppress-owner-transport)
    echo "[$(ts)] child transport suppressed — CI incident watcher owns terminal notification" >> "$LOG"
  fi
  "$UV_BIN" run volpred ops send-alert "${INTERNAL_ROUTE_ARGS[@]}" \
    --title "git-push-backup: push held — ${NEW_COUNT} new silent fallback(s)" \
    --body "本地領先 ${ahead} commit 但 HEAD 帶 ${NEW_COUNT} 個新 silent fallback，push 會讓 CI Silent Fallback Gate 紅。已暫停 push 保護 CI（紅碼不上 origin、CI 不會紅）。路由器會建立固定 P1 任務，當班修每個 NEW 位置（先留下 warn，或對合法例外標 '# silent-ok: 理由'）並重跑本 wrapper 解封；首次與修復進行中不寄信。新發現：
${NEWLINES}" >> "$LOG" 2>&1 || true
  # 2026-07-03: distinct exit 120 (NOT 1) for the held path. The guard ran fine and
  # made a correct protective decision + routed its repair task above — it is NOT a
  # cron infra failure. alerts.py `_BENIGN_FINDINGS_EXIT_CODES` treats 120 as a
  # benign, self-reported findings signal (exempt from host_cron_fail), while the real
  # failure paths below (divergence line ~52, push failure line ~103) keep exit 1 →
  # host_cron_fail CRITICAL. Root cause of the 4-day 28x false-CRITICAL: a single
  # false-positive line-38 silent-fallback flag held every fire, each exit 1'd, and
  # host_cron_fail could not tell a benign hold from a real failure. See error_log
  # 2026-07-03 + alerts.py _PUSH_HELD_EXIT_CODE comment.
  exit 120
elif [ "$AUDIT_RC" -ne 0 ]; then
  echo "[$(ts)] WARN audit rc=$AUDIT_RC new=${NEW_COUNT:-?} — audit error not a fallback breach, pushing anyway (backup priority)" >> "$LOG"
fi

# A clean strict verdict is the explicit end of the internal incident.  Reset
# its episode so a future, unrelated NEW finding starts from zero attempts.
if [ "$AUDIT_RC" -eq 0 ] && [ "${NEW_COUNT:-0}" = "0" ]; then
  "$UV_BIN" run volpred ops resolve-internal-alert \
    --alert-key git_push_backup_hold --observed-at "$AUDIT_FINISHED_AT" >> "$LOG" 2>&1 || \
    echo "[$(ts)] WARN: could not mark git_push_backup_hold resolved" >> "$LOG"
fi

# 3) fast-forward push
if git_auth push origin main >> "$LOG" 2>&1; then
  echo "[$(ts)] pushed ${ahead} commit(s) OK" >> "$LOG"
  exit 0
else
  echo "[$(ts)] PUSH FAILED" >> "$LOG"
  # 2026-06-30 transient-suppress：直接 cron (`17 */2`) 走 macOS keychain credential helper
  # 失敗率 ~43%（131 次假警報轟炸 boss）；piggy-back HH:00 hourly 走 check_alerts
  # subprocess env 成功率 ~96%。若上一次成功 push 在 90 min 內，視為 transient
  # （piggy-back 已 / 即將補上），suppress alert 避免假警報；只記 log 供 audit。
  LAST_OK_TS=$(grep -E "pushed [0-9]+ commit\(s\) OK|nothing to push \(ahead=0\)" "$LOG" 2>/dev/null \
    | grep -oE "\[[0-9-]+ [0-9:]+\]" | tail -1 | tr -d '[]')
  if [ -n "$LAST_OK_TS" ]; then
    NOW_EPOCH=$(date '+%s')
    LAST_OK_EPOCH=$(date -j -f '%Y-%m-%d %H:%M:%S' "$LAST_OK_TS" '+%s' 2>/dev/null || echo 0)
    if [ "$LAST_OK_EPOCH" -gt 0 ]; then
      AGE_MIN=$(( (NOW_EPOCH - LAST_OK_EPOCH) / 60 ))
      if [ "$AGE_MIN" -lt 90 ]; then
        echo "[$(ts)] SUPPRESSED alert (last OK ${AGE_MIN}m ago < 90m, piggy-back covers)" >> "$LOG"
        exit 0
      fi
    fi
  fi
  if [ "${VOLPRED_SUPPRESS_PUSH_ALERTS:-0}" != "1" ]; then
    "$UV_BIN" run volpred ops send-alert --level warn \
      --title "git-push-backup: push 失敗" \
      --body "git push origin main 失敗，本地領先 ${ahead} commit 未備份到遠端。最近 90 min 內無成功 push（已超 piggy-back 寬限）。需檢查認證 / 網路 / gh keychain。" >> "$LOG" 2>&1 || true
  else
    echo "[$(ts)] child alert suppressed — CI incident watcher owns terminal notification" >> "$LOG"
  fi
  exit 1
fi
