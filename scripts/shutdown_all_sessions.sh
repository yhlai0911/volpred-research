#!/usr/bin/env bash
# shutdown_all_sessions.sh — 完全關閉 3-terminal 多 agent 作業模式
#
# 做什麼（依序）：
#   1. 對每個 session 跑 `ops session-shutdown` → status=offline, claimed_task_id=None
#   2. 若仍有 claimed/running 狀態的 task（worker 未收尾），印警告讓你決定 fail/requeue
#   3. 刪除 storage/ops/agents/*.json 讓 control plane 乾淨
#   4. 終止本機 claude / codex 進程（可選；預設 --no-kill，避免誤殺其他 CLI）
#
# 用法：
#   bash scripts/shutdown_all_sessions.sh           # 標記 offline + 清 agent 檔，不殺 process
#   bash scripts/shutdown_all_sessions.sh --kill    # 順便 kill 本專案 CLI process（含 claude/codex）
#
# 關閉 terminal tab / 視窗前跑此腳本，才能避免殘留：
#   - 錯誤：直接 ⌘W 關 tab → agent 檔留在 online/busy，要等 300 秒 stale 才被回收
#   - 正確：先跑這支 → session offline + claimed tasks 可見 → 關 tab
#

set -eu

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${PROJECT_DIR}"

KILL_PROCESSES=0
if [[ "${1:-}" == "--kill" ]]; then
  KILL_PROCESSES=1
fi

echo "🛑 Shutdown 3-terminal 多 agent 作業模式"
echo

# Kill switch：寫 auto_loop.disabled flag，讓殘留的 /loop cron tick 到 session 時
# model 檢查 flag 就秒退，不浪費 token。launch_all_sessions.sh 啟動時會清掉 flag。
AUTO_LOOP_FLAG="${PROJECT_DIR}/storage/ops/auto_loop.disabled"
mkdir -p "$(dirname "${AUTO_LOOP_FLAG}")"
date -u +%Y-%m-%dT%H:%M:%SZ > "${AUTO_LOOP_FLAG}"
echo "→ 寫 kill-switch flag: ${AUTO_LOOP_FLAG}"
echo "  殘留 /loop cron tick 時 model 會檢查此 flag 立即 no-op 結束本輪。"
echo

declare -a SESSIONS=(
  "claude-supervisor:claude"
  "claude-worker:claude"
  "codex-worker:codex"
)

_shutdown_session() {
  local session_key="$1"
  local agent="$2"

  echo "→ ${session_key} (agent=${agent})"
  if VOLPRED_ACTOR="${agent}" uv run volpred ops session-shutdown \
      --session-key "${session_key}" 2>&1 | tail -1; then
    :
  else
    echo "  ⚠ session-shutdown 失敗（可能 session 根本沒被 bootstrap）"
  fi
}

for entry in "${SESSIONS[@]}"; do
  IFS=":" read -r key agent <<<"${entry}"
  _shutdown_session "${key}" "${agent}"
done

echo
echo "→ 檢查是否仍有 claimed/running task 未收尾"
IN_FLIGHT_JSON="$(uv run volpred ops tasks --status claimed 2>/dev/null | grep -E '^JSON:' | sed 's/^JSON: //' || true)"
IN_FLIGHT_RUNNING="$(uv run volpred ops tasks --status running 2>/dev/null | grep -E '^JSON:' | sed 's/^JSON: //' || true)"
_count_tasks() {
  local json="$1"
  # Count tasks by grepping for id field
  printf '%s' "${json}" | grep -oE '"id":' | wc -l | tr -d ' '
}
CLAIMED=$(_count_tasks "${IN_FLIGHT_JSON}")
RUNNING=$(_count_tasks "${IN_FLIGHT_RUNNING}")
if [[ "${CLAIMED}" != "0" || "${RUNNING}" != "0" ]]; then
  echo "  ⚠ 仍有 ${CLAIMED} 個 claimed + ${RUNNING} 個 running task"
  echo "    這些 task 未被 complete/fail 收尾；300 秒 stale 後會自動 reclaim"
  echo "    或手動處理：uv run volpred ops tasks --status claimed"
  echo "               uv run volpred ops fail <task_id> --agent <claude|codex> --error 'manual shutdown'"
else
  echo "  ✓ 無 in-flight task"
fi

echo
echo "→ 清除 storage/ops/agents/*.json"
AGENTS_DIR="${PROJECT_DIR}/storage/ops/agents"
for f in "${AGENTS_DIR}"/*.json; do
  [[ -e "${f}" ]] || continue
  rm -f "${f}"
  echo "  刪 $(basename "${f}")"
done

if [[ "${KILL_PROCESSES}" == "1" ]]; then
  echo
  echo "→ 終止本專案的 claude / codex 進程"
  # 只殺 cwd 在本專案的 process，避免誤殺其他 CLI session
  for name in claude codex; do
    pids="$(pgrep -f -- "^${name}$" 2>/dev/null || true)"
    for pid in ${pids}; do
      cwd_link="/proc/${pid}/cwd"
      # macOS 沒有 /proc；改用 lsof
      cwd="$(lsof -a -p "${pid}" -d cwd -Fn 2>/dev/null | grep '^n' | head -1 | sed 's/^n//')"
      if [[ "${cwd}" == "${PROJECT_DIR}"* ]]; then
        kill "${pid}" && echo "  kill ${name} pid=${pid}"
      fi
    done
  done
else
  echo
  echo "ℹ CLI 進程未殺（保留互動 session）。若要一併終止：bash scripts/shutdown_all_sessions.sh --kill"
fi

echo
echo "✅ 完成。現在可以安全關 terminal tab / 視窗。"
