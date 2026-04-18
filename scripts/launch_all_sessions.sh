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
  local sleep_seconds="$5"  # shell-wrapper loop interval (seconds) between CLI exec calls

  # 組合要在 Terminal.app 裡跑的指令：shell-level while-loop，每次 CLI 非互動執行
  # 一次 prompt（single-shot），跑完退出→ sleep → 下一輪 re-exec。這比 /loop skill
  # 可靠（/loop skill 不支援 CLI positional arg 觸發）。
  # 使用 -p 讓 Claude 跑 non-interactive mode；Codex 原生 single-shot。
  local exec_cmd
  if [[ "${cli_cmd}" == claude* ]]; then
    exec_cmd="${cli_cmd} -p \"\$(cat scripts/agent_prompts/${session_key}.txt)\""
  else
    exec_cmd="${cli_cmd} \"\$(cat scripts/agent_prompts/${session_key}.txt)\""
  fi

  local inner_cmd
  inner_cmd="cd '${PROJECT_DIR}' && "
  inner_cmd+="source scripts/bootstrap_agent_session.sh ${role} && "
  inner_cmd+="echo '[auto-loop] ${session_key} starting shell-wrapper loop (sleep ${sleep_seconds}s between rounds)' && "
  inner_cmd+="while true; do "
  inner_cmd+="echo '[auto-loop] === $(date +%H:%M:%S) round start ==='; "
  inner_cmd+="${exec_cmd}; "
  inner_cmd+="echo '[auto-loop] === round done, sleep ${sleep_seconds}s ==='; "
  inner_cmd+="sleep ${sleep_seconds}; "
  inner_cmd+="done"

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

# 全部用 shell-wrapper while-sleep-re-exec 模式，interval 從 config/supervisor_rules.json 讀
# 預設：supervisor 900s (15 min)、worker 600s (10 min)、codex 300s (5 min)
# 不再用 /loop skill — Claude Code CLI positional arg 不觸發 slash command，/loop 路線走不通
_open_window supervisor    "claude --dangerously-skip-permissions"              "T1 supervisor (claude-supervisor)" "claude-supervisor" 900
sleep 1
_open_window worker-claude "claude --dangerously-skip-permissions"              "T2 claude-worker"                   "claude-worker"     600
sleep 1
_open_window worker-codex  "codex --dangerously-bypass-approvals-and-sandbox"   "T3 codex-worker"                    "codex-worker"      300

cat <<EOF

✅ 三個 Terminal.app 視窗已開啟，**shell-wrapper 自動循環模式**：
   T1 supervisor：每 900s (15 min) claude -p 跑一次首發 prompt
   T2 claude-worker：每 600s (10 min) claude -p 跑一次
   T3 codex-worker：每 300s (5 min) codex 跑一次

每輪 CLI 都是 non-interactive single-shot 執行（-p 模式），讀 CLAUDE.md 規則 + prompt →
執行工作循環 → 退出 → sleep → 下一輪。用戶不需輸入任何指令。

停止方式：bash scripts/shutdown_all_sessions.sh --kill（或在各 terminal Ctrl+C 再關 tab）
EOF
