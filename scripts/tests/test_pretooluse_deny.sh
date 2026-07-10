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
# 2026-07-10 class sweep：舊 pattern 只認 `zeabur` / `npx zeabur`，以下 7 種全放行。
assert_deny "npx pinned version"           "npx zeabur@latest deploy"
assert_deny "npx --yes"                    "npx --yes zeabur deploy"
assert_deny "npx -y"                       "npx -y zeabur deploy"
assert_deny "bunx"                         "bunx zeabur deploy"
assert_deny "pnpm dlx"                     "pnpm dlx zeabur deploy"
assert_deny "yarn dlx"                     "yarn dlx zeabur deploy"
assert_deny "node_modules bin path"        "./node_modules/.bin/zeabur deploy"
assert_deny "cat feed.json"                "cat storage/reports/feed.json"
assert_deny "cat knowledge.json"           "cat storage/memory/knowledge.json"
assert_deny "less feed.json"               "less storage/reports/feed.json"
assert_deny "cat feed.json piped to jq"    "cat storage/reports/feed.json | jq '.items'"
assert_deny "cat after pipe"               "echo x | cat storage/memory/knowledge.json"
# 2026-07-10 class sweep：cat 的等價整檔 dumper，舊 pattern 只認 cat/less/more。
assert_deny "bat feed.json"                "bat storage/reports/feed.json"
assert_deny "nl knowledge.json"            "nl storage/memory/knowledge.json"
assert_deny "view feed.json"               "view storage/reports/feed.json"
assert_deny "tac knowledge.json"           "tac storage/memory/knowledge.json"
assert_deny "od feed.json"                 "od storage/reports/feed.json"
assert_deny "strings knowledge.json"       "strings storage/memory/knowledge.json"
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
# 2026-07-10：`git -C <dir>` / `--git-dir=` 前綴繞過 worktree deny（規則假設 git 後直接接
# worktree）。我修 PHASE-Z 時親手觸發 `git -C <repo> worktree remove <path> --force`，
# 只被 git 自己的「contains modified files」擋下。amend 規則早已處理 `-C`，worktree 漏了。
assert_deny "worktree -C prefix + force"   "git -C /repo worktree remove foo --force"
assert_deny "worktree -C prefix + path+force" "git -C /repo worktree remove /tmp/x --force"
assert_deny "worktree --git-dir prefix -f" "git --git-dir=/r/.git worktree remove foo -f"
assert_deny "worktree -C + -ff after &&"   "cd /tmp && git -C /r worktree remove x -ff"
# false-positive 防護：-C 前綴但無 force 仍須放行
assert_allow "worktree -C prefix no force" "git -C /repo worktree remove .claude/worktrees/foo"
assert_allow "worktree -C prefix prune"    "git -C /repo worktree prune"

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
# class sweep 的反向防護：擴大 pattern 後不可誤擋非 deploy 的 zeabur 子命令與非 dumper
assert_allow "zeabur list (not deploy)"    "npx zeabur list"
assert_allow "zeabur@latest list"          "npx zeabur@latest list"
assert_allow "batch cmd starting with bat" "batch_render storage/reports/feed.json"
assert_allow "cat unrelated report"        "bat storage/reports/mile_abc123.json"
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

# ── git commit --amend on 共用 main checkout（2026-07-10 hourly-23 事故）──
# 這條 deny 依賴「目標 repo 的 toplevel/branch」，不能靠真實 repo 當下狀態（會隨分支漂移）。
# 起一個一次性 repo 當 ROOT，worktree 當「agent 自己的 checkout」，兩者對照。
AMEND_TMP="$(mktemp -d)"
trap 'rm -rf "$AMEND_TMP"' EXIT
git init -q -b main "$AMEND_TMP/shared" 2>/dev/null
git -C "$AMEND_TMP/shared" -c user.email=t@t -c user.name=t commit -q --allow-empty -m base
git -C "$AMEND_TMP/shared" worktree add -q -b agent-branch "$AMEND_TMP/wt" 2>/dev/null
SHARED="$AMEND_TMP/shared"
WT="$AMEND_TMP/wt"

run_cwd() {  # $1=cwd $2=command → hook stdout（ROOT 指向一次性 shared repo）
  printf '{"cwd":%s,"tool_input":{"command":%s}}' \
    "$(printf '%s' "$1" | jq -Rs .)" "$(printf '%s' "$2" | jq -Rs .)" \
    | VOLPRED_HOOK_ROOT="$SHARED" bash "$HOOK"
}
decision_cwd() { run_cwd "$1" "$2" | jq -r '.hookSpecificOutput.permissionDecision // "none"'; }

assert_deny_cwd() {  # $1=label $2=cwd $3=command
  local dec; dec="$(decision_cwd "$2" "$3")"
  if [[ "$dec" == "deny" ]]; then PASS=$((PASS + 1)); echo "PASS deny : $1";
  else FAIL=$((FAIL + 1)); echo "FAIL deny (got $dec): $1"; fi
}
assert_allow_cwd() {  # $1=label $2=cwd $3=command
  local dec; dec="$(decision_cwd "$2" "$3")"
  if [[ "$dec" != "deny" ]]; then PASS=$((PASS + 1)); echo "PASS allow: $1";
  else FAIL=$((FAIL + 1)); echo "FAIL allow (got deny): $1"; fi
}

assert_deny_cwd  "amend on shared main"        "$SHARED" "git commit --amend -m x"
assert_deny_cwd  "amend abbrev --amen"         "$SHARED" "git commit --amen -m x"
assert_deny_cwd  "amend abbrev --am"           "$SHARED" "git commit --am -m x"
assert_deny_cwd  "amend after &&"              "$SHARED" "git add -A && git commit --amend --no-edit"
# 從 worktree 用 `git -C <main>` 打回共用 checkout —— cwd 看起來安全，目標不安全
assert_deny_cwd  "git -C shared from worktree" "$WT"     "git -C $SHARED commit --amend --no-edit"

# agent 在自己的 worktree 分支上 amend：單一 owner，無覆蓋他人之虞
assert_allow_cwd "amend in own worktree"       "$WT"     "git commit --amend --no-edit"
# 主 checkout 但不在 main 分支
git -C "$SHARED" checkout -q -b side
assert_allow_cwd "amend on shared side-branch" "$SHARED" "git commit --amend --no-edit"
git -C "$SHARED" checkout -q main
# false positive 防護：引號內提到 --amend、以及 `git commit -C <commit>`（沿用 message，非 amend）
assert_allow_cwd "commit msg mentions amend"   "$SHARED" "git commit -m 'ban --amend on shared main'"
assert_allow_cwd "commit -C reuse message"     "$SHARED" "git commit -C HEAD~1"
assert_allow_cwd "plain commit on shared main" "$SHARED" "git commit -m normal"

echo "---"
echo "PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
