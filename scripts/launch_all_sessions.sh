#!/usr/bin/env bash
# launch_all_sessions.sh — 一指令啟動 3-terminal 多 agent 作業模式
#
# 做什麼：
#   1. 用 osascript 開 3 個 Terminal.app 視窗（T1 supervisor / T2 claude-worker / T3 codex-worker）
#   2. 每個視窗 cd 到專案、source bootstrap script（登記 session 到 control plane）
#   3. 把對應 role 的 first-prompt 寫到剪貼簿 + /tmp 檔
#   4. 啟動對應 CLI（claude / codex）
#   5. 你在每個視窗按 ⌘V + Enter 就把 prompt 送進 CLI，進入工作循環
#
# 前提：
#   - macOS（腳本用 osascript + pbcopy）
#   - claude CLI、codex CLI 都已安裝且 OAuth 已登入
#   - agent-specs drift 已清（否則 session-bootstrap 會被擋；可先跑
#     `uv run volpred ops agent-spec sync --from claude` 修）
#
# 用法：
#   bash scripts/launch_all_sessions.sh
#

set -eu

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPTS_DIR="${PROJECT_DIR}/scripts/agent_prompts"

if ! command -v osascript >/dev/null 2>&1; then
  echo "❌ 需要 macOS 的 osascript。若你在別的 OS，請手動開 3 個 terminal 各自 source bootstrap_agent_session.sh" >&2
  exit 1
fi

if [[ ! -d "${PROMPTS_DIR}" ]]; then
  echo "❌ 找不到 prompts 目錄：${PROMPTS_DIR}" >&2
  exit 1
fi

# Prompt files live at scripts/agent_prompts/<session_key>.txt and are loaded
# by the SessionStart hook via VOLPRED_SESSION_KEY env var — no pbcopy needed.

_open_window() {
  local role="$1"
  local cli_cmd="$2"
  local title="$3"
  local session_key="$4"
  local auto_loop_prefix="$5"  # e.g. "/loop 15m " for Claude Code sessions; "" for codex

  # 組合要在 Terminal.app 裡跑的指令：
  #   cd → source bootstrap（設 VOLPRED_SESSION_KEY + session-bootstrap）
  #      → 啟動 CLI 並把 prompt 當 positional 參數送進互動 session
  #      → 若是 Claude Code session，prompt 前綴加 "/loop <interval> " 讓 session 啟動即自動循環
  local inner_cmd
  inner_cmd="cd '${PROJECT_DIR}' && "
  inner_cmd+="source scripts/bootstrap_agent_session.sh ${role} && "
  if [[ -n "${auto_loop_prefix}" ]]; then
    # Claude Code: 把 "/loop Nm <prompt>" 作為首發 user message，session 啟動就進自動循環
    inner_cmd+="${cli_cmd} \"${auto_loop_prefix}\$(cat scripts/agent_prompts/${session_key}.txt)\""
  else
    # Codex: 沒有 /loop skill，用 shell wrapper 包 while loop 週期 re-exec
    #   codex 跑完 prompt 退出 → sleep → 下一輪 re-exec
    #   task queue 空時 codex 自己 null-poll 結束，shell wrapper 接力
    inner_cmd+="while true; do ${cli_cmd} \"\$(cat scripts/agent_prompts/${session_key}.txt)\"; echo '[auto-loop] codex session ended, sleep 300s then restart'; sleep 300; done"
  fi

  # 轉義 double-quote 以便塞進 AppleScript
  local escaped_cmd="${inner_cmd//\\/\\\\}"
  escaped_cmd="${escaped_cmd//\"/\\\"}"

  osascript <<APPLESCRIPT
tell application "Terminal"
  activate
  do script "${escaped_cmd}"
  set custom title of front window to "${title}"
end tell
APPLESCRIPT
}

echo "🚀 啟動 3-terminal 多 agent 作業模式（自動循環模式）..."
echo

# 清掉 shutdown 時寫的 auto-loop kill switch flag，允許 session 正常循環
AUTO_LOOP_FLAG="${PROJECT_DIR}/storage/ops/auto_loop.disabled"
if [[ -f "${AUTO_LOOP_FLAG}" ]]; then
  rm -f "${AUTO_LOOP_FLAG}"
  echo "→ 清除 kill-switch flag，session 恢復自動循環"
fi
echo

# T1 supervisor: /loop 15m — 每 15 分鐘跑一次啟動檢查 + 派工判斷
_open_window supervisor    "claude --dangerously-skip-permissions"              "T1 supervisor (claude-supervisor)" "claude-supervisor" "/loop 15m "
sleep 1
# T2 claude-worker: /loop 10m — 每 10 分鐘 poll next-task；有 task 則執行，無則結束本輪
_open_window worker-claude "claude --dangerously-skip-permissions"              "T2 claude-worker"                   "claude-worker"     "/loop 10m "
sleep 1
# T3 codex-worker: 沒有 /loop skill，shell wrapper 包 while-sleep-restart
_open_window worker-codex  "codex --dangerously-bypass-approvals-and-sandbox"   "T3 codex-worker"                    "codex-worker"      ""

cat <<EOF

✅ 三個 Terminal.app 視窗已開啟，**全自動循環模式**：
   T1 supervisor：/loop 15m — 每 15 分鐘跑啟動檢查 + 派工判斷
   T2 claude-worker：/loop 10m — 每 10 分鐘 poll next-task + 執行
   T3 codex-worker：shell wrapper 包 while-sleep 300s — codex 跑完自動 re-exec

三個 session 啟動即自動運作，**用戶不需輸入任何指令**。
停止方式：bash scripts/shutdown_all_sessions.sh --kill（或在各 terminal Ctrl+C）
EOF
