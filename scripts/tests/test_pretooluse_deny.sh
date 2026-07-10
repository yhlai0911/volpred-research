#!/bin/bash
# Regression: .claude/hooks/pretooluse-bash-optimizer.sh deny 清單
# （2026-07-10 topology-audit-pretooluse-deny：CLAUDE.md『絕對禁止』prose → 機械攔截）
#
# Exit-code 紀律（.claude/rules/hooks-exit-code.md）：不依賴 pipeline $?，
# 逐案 parse hook 自己的 JSON 輸出（.hookSpecificOutput.permissionDecision）決定 pass/fail，
# 最後以顯式 FAIL 計數決定整體退出碼。
set -uo pipefail

HOOK="/Users/yhlai0911/volpred-research/.claude/hooks/pretooluse-bash-optimizer.sh"
PASS=0
FAIL=0

run() {  # $1=command string → hook stdout
  printf '{"tool_input":{"command":%s}}' "$(printf '%s' "$1" | jq -Rs .)" | bash "$HOOK"
}

decision() {  # $1=command → permissionDecision 或 "none"
  run "$1" | jq -r '.hookSpecificOutput.permissionDecision // "none"'
}

assert_deny() {  # $1=label $2=command
  local dec; dec="$(decision "$2")"
  if [[ "$dec" == "deny" ]]; then PASS=$((PASS + 1)); echo "PASS deny : $1";
  else FAIL=$((FAIL + 1)); echo "FAIL deny (got $dec): $1"; fi
}

assert_allow() {  # $1=label $2=command
  local dec; dec="$(decision "$2")"
  if [[ "$dec" != "deny" ]]; then PASS=$((PASS + 1)); echo "PASS allow: $1";
  else FAIL=$((FAIL + 1)); echo "FAIL allow (got deny): $1"; fi
}

# ── 應 deny（第一批既往事故項）──
assert_deny "worktree remove --force"      "git worktree remove --force .claude/worktrees/foo"
assert_deny "worktree remove -f"           "git worktree remove -f .claude/worktrees/foo"
assert_deny "npx zeabur deploy"            "npx zeabur deploy"
assert_deny "zeabur deploy direct"         "zeabur deploy --project abc"
assert_deny "cat feed.json"                "cat storage/reports/feed.json"
assert_deny "cat knowledge.json"           "cat storage/memory/knowledge.json"
assert_deny "less feed.json"               "less storage/reports/feed.json"
assert_deny "cat feed.json piped to jq"    "cat storage/reports/feed.json | jq '.items'"
assert_deny "cat after pipe"               "echo x | cat storage/memory/knowledge.json"
assert_deny "zeabur deploy after &&"       "cd frontend-v2-fix && npx zeabur deploy"
assert_deny "worktree remove after ;"      "cd /tmp ; git worktree remove --force foo"
assert_deny "force flag after path"        "git worktree remove foo --force"
# 2026-07-10：git parse-options 收長選項不歧義縮寫與 short flag 聚合，實測 -ff/--for/--forc
# 全被 git 接受而舊 regex 全放行。-ff 正是文件建議用來移除 locked worktree 的寫法。
assert_deny "aggregated -ff"               "git worktree remove -ff foo"
assert_deny "abbrev --for"                 "git worktree remove --for foo"
assert_deny "abbrev --forc"                "git worktree remove --forc foo"
assert_deny "short cluster -vf"            "git worktree remove -vf foo"
assert_deny "aggregated -ff after path"    "git worktree remove foo -ff"

# ── false-positive 防護：命令引數 / commit message / echo 裡「提到」危險字串不可誤擋 ──
assert_allow "commit msg mentions zeabur"  "git commit -m 'ban zeabur deploy direct call'"
assert_allow "commit msg mentions worktree" "git commit -m 'no more git worktree remove --force'"
assert_allow "echo mentions cat feed.json" "echo 'do not cat storage/reports/feed.json'"
assert_allow "grep for zeabur deploy str"  "grep 'zeabur deploy' docs/notes.md"

# ── 應 allow（sanctioned 用法 / 非事故項，不可誤擋）──
assert_allow "jq feed.json"                "jq '.items[0]' storage/reports/feed.json"
assert_allow "grep feed.json"              "grep NVDA storage/reports/feed.json"
assert_allow "head knowledge.json"         "head -c 500 storage/memory/knowledge.json"
assert_allow "deploy-zeabur-safe.sh"       "bash frontend-v2-fix/scripts/deploy-zeabur-safe.sh"
assert_allow "worktree remove (no force)"  "git worktree remove .claude/worktrees/foo"
# 2026-07-10 18:20：清理死 worktree 時被誤擋 — -f 屬於前一段的 rm，不屬於 worktree remove
assert_allow "rm -f then worktree remove"  "rm -f /tmp/junk && git worktree remove .claude/worktrees/foo"
assert_allow "rm -f on next line"          $'rm -f /tmp/junk\ngit worktree remove .claude/worktrees/foo'
assert_allow "worktree remove then rm -f"  "git worktree remove .claude/worktrees/foo && rm -f /tmp/junk"
# 過度攔截防護：路徑內含 -f 子字串（無前導空白）不是 flag
assert_allow "path contains -f substring"  "git worktree remove .claude/worktrees/wt-fix"
assert_allow "path named frontend-fix"     "git worktree remove .claude/worktrees/frontend-fix"
assert_allow "plain echo"                  "echo hello"
assert_allow "pytest advisory rewrite"     "uv run pytest tests/"
assert_allow "cat unrelated file"          "cat storage/reports/mile_abc123.json"

echo "---"
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
