#!/bin/bash
# UserPromptSubmit hook — every interactive turn, check email_reply backlog.
# If pending email_reply > 0, inject reminder into prompt context so Claude
# main thread can't keep doing feature work while user replies sit.
#
# Per user 2026-05-25 directive: 「為什麼互動 session 沒先 claim email」.
# Hooked via .claude/settings.json UserPromptSubmit.

cd /Users/yhlai0911/Desktop/volpred-research || exit 0

# Silently exit if pool file missing (do not block prompt)
[ -f storage/next_tasks.json ] || exit 0

COUNT=$(jq '[.[] | select(.task_type=="email_reply" and (.status=="pending" or .status=="pending_main_thread"))] | length' storage/next_tasks.json 2>/dev/null)

if [ -z "$COUNT" ] || [ "$COUNT" -eq 0 ]; then
  # Nothing pending — quiet
  exit 0
fi

# Inject reminder. stdout becomes part of prompt context.
echo ""
echo "⚠️  EMAIL_REPLY BACKLOG: $COUNT pending"
echo ""
jq -r '[.[] | select(.task_type=="email_reply" and (.status=="pending" or .status=="pending_main_thread"))] | .[] | "  - \(.id) — \(.email_subject // "(no subj)" | .[0:80]) (P\(.priority // "?"))"' storage/next_tasks.json 2>/dev/null | head -5

echo ""
echo "硬規則（per AGENTS.md / publishing rules）: email_reply 是 PHASE 0 最高優先 — 處理完才做 feature work。"
echo "Claim: uv run python scripts/task_pool_claim.py claim --id <id> --owner interactive-claude"
echo ""
