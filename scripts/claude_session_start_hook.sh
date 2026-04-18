#!/usr/bin/env bash
# claude_session_start_hook.sh — Claude Code SessionStart hook
#
# 偵測 VOLPRED_SESSION_KEY 環境變數。若有值（bootstrap_agent_session.sh 設的），
# 把對應角色的 prompt 檔內容輸出為 hookSpecificOutput.additionalContext，
# 讓 Claude 啟動時自動載入角色工作流，不用人工貼 prompt。
#
# 若 VOLPRED_SESSION_KEY 未設 → 輸出空內容，hook 不影響普通互動 session。

set -u

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROMPTS_DIR="${PROJECT_DIR}/scripts/agent_prompts"

if [[ -z "${VOLPRED_SESSION_KEY:-}" ]]; then
  exit 0
fi

prompt_file="${PROMPTS_DIR}/${VOLPRED_SESSION_KEY}.txt"
if [[ ! -f "${prompt_file}" ]]; then
  exit 0
fi

role_prompt="$(cat "${prompt_file}")"
header="=== MULTI-AGENT MODE: ${VOLPRED_SESSION_KEY} ==="
additional_context="${header}
VOLPRED_ROLE=${VOLPRED_ROLE:-}
VOLPRED_TERMINAL_LABEL=${VOLPRED_TERMINAL_LABEL:-}

${role_prompt}

=== END ROLE PROMPT — 立即依上述指示執行，不用等用戶 prompt ==="

# Emit as Claude Code hook JSON so additionalContext is injected into session.
python3 -c "
import json, sys
payload = {
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': sys.stdin.read()
    }
}
print(json.dumps(payload, ensure_ascii=False))
" <<EOF
${additional_context}
EOF
