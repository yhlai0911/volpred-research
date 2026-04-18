#!/usr/bin/env bash
# bootstrap_agent_session.sh — 啟動 3-terminal 多 agent 作業模式中的一個 terminal
#
# 用法（必須用 source，否則 VOLPRED_ACTOR 不會持久在你的 shell）：
#   source scripts/bootstrap_agent_session.sh supervisor
#   source scripts/bootstrap_agent_session.sh worker-claude
#   source scripts/bootstrap_agent_session.sh worker-codex
#
# Mapping:
#   supervisor    → session_key=claude-supervisor, agent=claude
#   worker-claude → session_key=claude-worker,     agent=claude
#   worker-codex  → session_key=codex-worker,      agent=codex
#
# 執行內容：
#   1. 設定 VOLPRED_ACTOR (session.py 的 actor-guard 要求)
#   2. 跑 `uv run volpred ops session-bootstrap --session-key <key>`
#   3. 印出後續常用指令備忘
#
# 要點：VSCode 三個 terminal 各自 source 一次即可，之後 terminal 內所有
# volpred ops 指令都會自動帶對的 VOLPRED_ACTOR。
#

# Deliberately NOT using `set -eu`: this script is designed to be sourced into
# an interactive shell, and `set -e` would either (a) kill the user's shell on
# any sub-command failure or (b) prevent VOLPRED_ACTOR from persisting when the
# bootstrap CLI reports pre-existing agent-spec drift.

_bootstrap_role="${1:-}"

if [[ -z "${_bootstrap_role}" ]]; then
  echo "Usage: source ${BASH_SOURCE[0]} <supervisor|claude-supervisor|worker-claude|claude-worker|worker-codex|codex-worker>" >&2
  return 1 2>/dev/null || exit 1
fi

case "${_bootstrap_role}" in
  supervisor|claude-supervisor)
    _bootstrap_session_key="claude-supervisor"
    _bootstrap_agent_name="claude"
    _bootstrap_terminal_label="VSCode T1 (supervisor)"
    ;;
  worker-claude|claude-worker)
    _bootstrap_session_key="claude-worker"
    _bootstrap_agent_name="claude"
    _bootstrap_terminal_label="VSCode T2 (claude worker)"
    ;;
  worker-codex|codex-worker)
    _bootstrap_session_key="codex-worker"
    _bootstrap_agent_name="codex"
    _bootstrap_terminal_label="VSCode T3 (codex worker)"
    ;;
  *)
    echo "Unknown role: ${_bootstrap_role}" >&2
    echo "Expected: supervisor | worker-claude | worker-codex" >&2
    return 1 2>/dev/null || exit 1
    ;;
esac

export VOLPRED_ACTOR="${_bootstrap_agent_name}"
export VOLPRED_SESSION_KEY="${_bootstrap_session_key}"
export VOLPRED_ROLE="${_bootstrap_role}"
export VOLPRED_TERMINAL_LABEL="${_bootstrap_terminal_label}"

echo "→ VOLPRED_ACTOR=${VOLPRED_ACTOR}"
echo "→ VOLPRED_SESSION_KEY=${VOLPRED_SESSION_KEY}"
echo "→ VOLPRED_ROLE=${VOLPRED_ROLE}"
echo "→ session-bootstrap --session-key ${_bootstrap_session_key}"

uv run volpred ops session-bootstrap \
  --session-key "${_bootstrap_session_key}" \
  --terminal-label "${_bootstrap_terminal_label}"

echo
echo "─── ${_bootstrap_session_key} ready ───"
echo
case "${_bootstrap_role}" in
  supervisor)
    cat <<'USAGE'
T1 (Supervisor) 常用指令：
  uv run volpred ops control-plane-summary
  uv run volpred ops tasks --status blocked      # approval backlog
  uv run volpred ops pending-curations           # 需要 curate 的 succeeded tasks
  uv run volpred ops agents                      # 看 T2/T3 是否上線
  uv run volpred ops scheduler-preview
  uv run volpred ops curate <task_id> --actor claude-supervisor \
      --promoted knowledge.json,research_program.md --notes "..."

職責：curate worker receipts、處理 approval、派 paper 決策任務、寫 paper .tex
禁止：對此 session 跑 heartbeat --agent claude 或 --session-key claude-worker
      （會覆蓋 T2 worker 心跳）
USAGE
    ;;
  worker-claude)
    cat <<'USAGE'
T2 (Claude Worker) 工作循環：
  uv run volpred ops next-task --session-key claude-worker --emit-brief
  # …執行任務…
  uv run volpred ops complete <task_id> --session-key claude-worker \
      --summary "..." --signals-json '{"summary_text":"...","knowledge_candidates":[...]}'
  # 失敗用 fail，長任務中用 heartbeat --session-key claude-worker

專責 task family：research / content / member / 論文寫作
禁止直接寫：knowledge.json / experiment_experiences.json / research_program.md
            agent-specs/skills/ / config/runtime_schedules.json / feed.json
USAGE
    ;;
  worker-codex)
    cat <<'USAGE'
T3 (Codex Worker) 工作循環：
  uv run volpred ops next-task --session-key codex-worker --emit-brief
  # …執行任務…
  uv run volpred ops complete <task_id> --session-key codex-worker \
      --summary "..." --signals-json '{"summary_text":"...","frontend_impact":{...}}'

專責 task family：code / review / ops / strategy
recalc/sync 類任務完成時，signal 帶 frontend_impact.requires_sync=true
禁止寫共享狀態（見 AGENTS.md:160-164）
USAGE
    ;;
esac

unset _bootstrap_role _bootstrap_session_key _bootstrap_agent_name _bootstrap_terminal_label
