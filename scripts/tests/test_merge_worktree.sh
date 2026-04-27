#!/bin/bash
# test_merge_worktree.sh — 驗證 scripts/merge_worktree.sh 不會 silent 遺失 agent 工作
#
# 用法：
#   bash scripts/tests/test_merge_worktree.sh
#
# 測試場景：
#   Case A: agent 有 untracked experiments/<kXXX>/ 但沒 commit
#           → script 應 auto-commit 再 merge，不該 --force remove 遺失檔案
#   Case B: agent commit 了但 rev-list=0 (e.g. branch HEAD = main HEAD)
#           但工作目錄仍有 orphan experiments/ 檔
#           → script 應 abort，不該走 no-commits path 的 --force remove
#   Case C: agent 有 untracked files + auto-commit 成功 → merge path 正確
#   Case D: orphan branch cleanup 處理 `+` 標記 (checked-out 標記)
#   Case 5 (K1262-v4): 真實 commit 但 cwd-shift 後 rev-list 可能 false negative
#           → file-presence diff layer (PRIMARY) 必抓到 worktree-only experiments/ 檔
#   Case 6 (K1262-v4): merge 流程被截斷，main HEAD 無 K-experiment 檔但 worktree branch 有
#           → post-merge file-presence verification 必 ABORT 並列出 cherry-pick hint
#   Case 7 (K1262-v4): worktree locked (stale .git/worktrees/<name>/locked) 時 remove 失敗
#           → script 必印 unlock + remove + branch -D hint，**禁止** --force fallback
#
# 測試用獨立 git repo (不碰主 project state)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MERGE_SCRIPT="$PROJECT_ROOT/scripts/merge_worktree.sh"

TMP_BASE=$(mktemp -d "/tmp/merge_worktree_test.XXXXXX")
trap 'rm -rf "$TMP_BASE"' EXIT

PASS=0
FAIL=0

pass() { echo "  [PASS] $1"; PASS=$((PASS + 1)); }
fail() { echo "  [FAIL] $1"; FAIL=$((FAIL + 1)); }

# ============================================================
# Helper: 建立一個臨時 git repo 作為主目錄 + 一個 worktree
# 關鍵：把 merge_worktree.sh copy 到 test_dir/scripts/ 裡，
# 這樣 script 用 BASH_SOURCE 解析 MAIN_DIR 時會指到 test_dir 而不是主 project。
# ============================================================
setup_test_env() {
    local test_name="$1"
    local test_dir="$TMP_BASE/$test_name"
    mkdir -p "$test_dir/scripts"
    cp "$MERGE_SCRIPT" "$test_dir/scripts/merge_worktree.sh"
    chmod +x "$test_dir/scripts/merge_worktree.sh"

    cd "$test_dir"

    # 初始化 main repo
    git init -b main -q
    git config user.email "test@test"
    git config user.name "test"
    mkdir -p experiments .claude/worktrees
    echo "seed" > experiments/.gitkeep
    git add -A && git commit -qm "seed"

    # 建立 worktree
    git worktree add -b "worktree-agent-test${test_name}" \
        ".claude/worktrees/agent-test${test_name}" main -q 2>&1 | grep -v "^Preparing" || true

    echo "$test_dir"
}

# helper to run the script inside the test dir
run_merge_in_test_dir() {
    local test_dir="$1"
    shift
    (cd "$test_dir" && bash "$test_dir/scripts/merge_worktree.sh" "$@" 2>&1) || true
}

# ============================================================
# Test Case A: untracked experiments/ 無 commit → auto-commit + merge
# ============================================================
test_case_a() {
    echo "=== Case A: untracked experiments/ 無 commit ==="
    local test_dir
    test_dir=$(setup_test_env "caseA")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcaseA"
    # Agent 模擬：寫 experiments/ktest1/ 但沒 commit
    mkdir -p "$wt/experiments/ktest1"
    echo "print('test1')" > "$wt/experiments/ktest1/ktest1.py"
    echo "# K test1" > "$wt/experiments/ktest1/README.md"

    # Run merge script
    local output
    output=$(run_merge_in_test_dir "$test_dir")

    # 驗證：
    # 1. ktest1 應該出現在主目錄
    if [[ -f "$test_dir/experiments/ktest1/ktest1.py" ]]; then
        pass "A-1: ktest1.py 在主目錄（auto-commit + merge 成功）"
    else
        fail "A-1: ktest1.py 遺失 (silent data loss!)"
        echo "$output" | head -40
    fi

    # 2. worktree 應該已被移除 或 (若 abort) 還在
    # 若我們的 fix 運作正常，auto-commit 會成功，merge 會成功
    if ! git worktree list --porcelain | grep -q "$wt"; then
        pass "A-2: worktree 已清理"
    elif [[ -f "$test_dir/experiments/ktest1/ktest1.py" ]]; then
        pass "A-2: worktree 仍在但檔案安全 (acceptable state)"
    else
        fail "A-2: worktree 還在且檔案遺失"
    fi
}

# ============================================================
# Test Case B: rev-list=0 但 worktree 有 orphan experiments/
# → 必須 abort，不能 --force remove
# ============================================================
test_case_b() {
    echo "=== Case B: rev-list=0 + orphan experiments (reproducer for K1100g_d9 bug) ==="
    local test_dir
    test_dir=$(setup_test_env "caseB")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcaseB"

    # 模擬：worktree 裡有 experiments/ktest2/ 但 status 顯示為 untracked。
    # 我們 add 到 .gitignore 讓 git status 看不到它 → 模擬 auto-commit 未偵測
    echo "experiments/ktest2/" >> .gitignore
    git add .gitignore && git commit -qm "ignore ktest2"

    # 現在 pull 到 worktree
    (cd "$wt" && git pull --no-edit -q origin main 2>&1 || git merge main --no-edit -q 2>&1) || \
        (cd "$wt" && git reset --hard main -q)

    # Agent 寫 ktest2 (被 gitignore 覆蓋)
    mkdir -p "$wt/experiments/ktest2"
    echo "print('test2 - hidden by gitignore')" > "$wt/experiments/ktest2/ktest2.py"

    # 驗證模擬正確：status 應該看不到它
    local status_check
    status_check=$(cd "$wt" && git status --porcelain)
    if [[ -z "$status_check" ]]; then
        echo "  [SETUP-OK] git status 看不到 ktest2 (gitignored)，rev-list=0"
    else
        echo "  [SETUP-WARN] git status 仍看到 ktest2: $status_check"
    fi

    # Run merge script
    local output
    output=$(run_merge_in_test_dir "$test_dir")

    # 驗證：
    # 1. worktree 應該還在（script abort 了，不該 --force remove）
    if [[ -d "$wt" ]] && [[ -f "$wt/experiments/ktest2/ktest2.py" ]]; then
        pass "B-1: worktree 保留，ktest2.py 未遺失"
    else
        fail "B-1: worktree 被 --force remove，ktest2.py 可能遺失 (silent loss bug!)"
        echo "--- script output ---"
        echo "$output" | head -30
    fi

    # 2. script 應該有 ABORT 訊息
    if echo "$output" | grep -q "ABORT\|🛑"; then
        pass "B-2: script 正確 abort 並提示"
    else
        fail "B-2: script 沒 abort"
        echo "$output" | head -20
    fi
}

# ============================================================
# Test Case C: auto-commit 成功 → merge path
# ============================================================
test_case_c() {
    echo "=== Case C: auto-commit + merge 正常流程 ==="
    local test_dir
    test_dir=$(setup_test_env "caseC")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcaseC"
    mkdir -p "$wt/experiments/ktest3"
    echo "print('test3')" > "$wt/experiments/ktest3/ktest3.py"
    echo "{}" > "$wt/experiments/ktest3/ktest3_results.json"

    local output
    output=$(run_merge_in_test_dir "$test_dir")

    if [[ -f "$test_dir/experiments/ktest3/ktest3.py" ]] && \
       [[ -f "$test_dir/experiments/ktest3/ktest3_results.json" ]]; then
        pass "C-1: ktest3 所有檔案 merge 到主目錄"
    else
        fail "C-1: ktest3 檔案不完整"
        echo "$output" | head -30
    fi
}

# ============================================================
# Test Case D: orphan branch cleanup 不會產生 `+` 標記錯誤
# ============================================================
test_case_d() {
    echo "=== Case D: orphan branch cleanup 正確解析 branch 名稱 ==="
    local test_dir
    test_dir=$(setup_test_env "caseD")
    cd "$test_dir"

    # 建立多個 orphan branches
    git branch "worktree-agent-orphan1" main
    git branch "worktree-agent-orphan2" main

    # Dry-run
    local output
    output=$(run_merge_in_test_dir "$test_dir" --dry-run)

    # 驗證：不應出現 `+worktree-agent-*` (被 `+` 污染的名稱)
    if echo "$output" | grep -q "會刪除 orphan branch: +worktree"; then
        fail "D-1: orphan branch name 被 '+' 標記污染 (bug #1)"
        echo "$output" | grep "orphan branch" | head -5
    else
        pass "D-1: orphan branch 名稱乾淨（用 for-each-ref）"
    fi

    # 驗證：orphan1 和 orphan2 都要被列出
    if echo "$output" | grep -q "worktree-agent-orphan1" && \
       echo "$output" | grep -q "worktree-agent-orphan2"; then
        pass "D-2: 兩個 orphan branches 都被偵測"
    else
        fail "D-2: 漏了 orphan branch"
        echo "$output" | grep "orphan" | head -5
    fi
}

# ============================================================
# Test Case 5 (K1262-v4): file-presence diff layer 是 PRIMARY 防線
#   即使 rev-list 報 0，只要 worktree branch 有 main 沒有的 experiments/ 檔，
#   file-presence layer 必發現並驅動 merge path（不能 silent skip）
# ============================================================
test_case_5_rev_list_false_negative() {
    echo "=== Case 5 (K1262-v4): rev-list false negative + file-presence layer 必抓 ==="
    local test_dir
    test_dir=$(setup_test_env "case5")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase5"
    local branch="worktree-agent-testcase5"

    # Agent 在 worktree 裡 commit experiments/k1262sim/
    mkdir -p "$wt/experiments/k1262sim"
    cat > "$wt/experiments/k1262sim/k1262sim.py" <<'EOF'
# K1262 simulation: real implementation, real commit on worktree branch
print("k1262sim implementation")
EOF
    echo "# K1262sim README" > "$wt/experiments/k1262sim/README.md"
    (cd "$wt" && git add -A && git commit -qm "K1262sim deliverables")

    # 確認 commit 真的存在 worktree branch
    local commit_count
    commit_count=$(git rev-list --count "main..$branch" 2>/dev/null || echo "0")
    if [[ "$commit_count" -lt 1 ]]; then
        fail "5-setup: 預期 worktree branch 有 commit 但 rev-list 報 0（測試環境問題）"
        return
    fi

    # 確認 file-presence diff 在 main 端有用：worktree branch 含 main 沒有的 experiments/ 檔
    local diff_files
    diff_files=$(git diff-tree --diff-filter=A --name-only -r "main" "$branch" -- experiments/ 2>/dev/null || true)
    if ! echo "$diff_files" | grep -q "k1262sim"; then
        fail "5-setup: file-presence diff 沒看到 k1262sim 檔（測試環境問題）"
        echo "  diff_files=$diff_files"
        return
    fi

    # Run merge script
    local output
    output=$(run_merge_in_test_dir "$test_dir")

    # 5-1: k1262sim.py 必到 main HEAD
    if git -C "$test_dir" cat-file -e "main:experiments/k1262sim/k1262sim.py" 2>/dev/null; then
        pass "5-1: k1262sim.py 在 main HEAD（file-presence layer + merge 成功）"
    else
        fail "5-1: k1262sim.py 不在 main HEAD（K1262 silent drop pattern!）"
        echo "$output" | head -50
    fi

    # 5-2: 檔案也在 working tree
    if [[ -f "$test_dir/experiments/k1262sim/k1262sim.py" ]]; then
        pass "5-2: k1262sim.py 在主目錄 working tree"
    else
        fail "5-2: k1262sim.py 不在主目錄 working tree"
    fi

    # 5-3: script 不該誤判「rev-list=0 + experiments/ 也空」
    if echo "$output" | grep -q "沒有新的 commits.*可安全移除"; then
        fail "5-3: script 誤判 no-commits（K1262 false negative pattern）"
        echo "$output" | grep -B2 -A2 "沒有新的 commits"
    else
        pass "5-3: script 沒誤判 no-commits（rev-list false negative 防住）"
    fi
}

# ============================================================
# Test Case 6 (K1262-v4): post-merge file-presence verification 必 ABORT
#   simulate K1262 silent drop：merge 流程被截斷，main HEAD 沒拿到 K-experiment 檔
#   做法：patch test-dir 的 script 副本，在 git merge 那行 inject early return（模擬 bug）
#   K1262-v4 layer 必須抓到 worktree-branch 有檔但 main HEAD 沒有，列出 cherry-pick hint
# ============================================================
test_case_6_post_merge_verification() {
    echo "=== Case 6 (K1262-v4): post-merge file-presence verification 必 ABORT ==="
    local test_dir
    test_dir=$(setup_test_env "case6")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase6"
    local branch="worktree-agent-testcase6"

    # Agent commit
    mkdir -p "$wt/experiments/k1262v4"
    echo "print('k1262v4 lost')" > "$wt/experiments/k1262v4/k1262v4.py"
    echo "# K1262v4" > "$wt/experiments/k1262v4/README.md"
    (cd "$wt" && git add -A && git commit -qm "K1262v4 deliverables (will be lost)")

    # Patch script 副本：把 `git merge "$branch" -X ours` 那行替換成 echo + true
    # 這模擬 merge 流程「聲稱成功」但 main HEAD 實際沒拿到 commits 的 K1262 silent drop bug
    local script_copy="$test_dir/scripts/merge_worktree.sh"
    # 用 awk 替換：找到 `if git merge "$branch" -X ours` 開頭的 if，把 git merge 換成 :（true command）
    # 注意保留結構讓 merge_ok=true（模擬 script 認為 merge 成功）
    python3 - "$script_copy" <<'PYEOF'
import sys, re
p = sys.argv[1]
src = open(p).read()
# 把 git merge "$branch" -X ours 那行替換成 true（模擬 bug：merge 流程聲稱成功但實際沒寫 main）
new_src = re.sub(
    r'if git merge "\$branch" -X ours --no-edit -m "[^"]*"[^{]*?2>&1; then',
    'if : ; then  # PATCHED FOR TEST: simulate K1262 silent drop',
    src,
    count=1,
    flags=re.DOTALL
)
if new_src == src:
    # fallback simpler pattern
    new_src = re.sub(
        r'(if )git merge "\$branch" -X ours',
        r'\1: ; #git merge "$branch" -X ours',
        src,
        count=1,
    )
open(p, 'w').write(new_src)
PYEOF

    # Run merge script (the patched one)
    local output
    output=$(run_merge_in_test_dir "$test_dir")

    # 6-1: K1262-v4 必須印 [CRITICAL] detection 訊息
    if echo "$output" | grep -q "K1262-v4 detection"; then
        pass "6-1: K1262-v4 post-merge layer 偵測到 silent drop"
    else
        fail "6-1: K1262-v4 post-merge layer 沒抓到 silent drop（false negative!）"
        echo "--- output (last 60 lines) ---"
        echo "$output" | tail -60
    fi

    # 6-2: 必印 cherry-pick hint
    if echo "$output" | grep -q "cherry-pick"; then
        pass "6-2: script 提示 cherry-pick 救援命令"
    else
        fail "6-2: 沒列出 cherry-pick hint"
    fi

    # 6-3: worktree NOT removed（K1262-v4 必保留 worktree 待人工處理）
    if [[ -d "$wt" ]]; then
        pass "6-3: worktree 保留（K1262-v4 不允許 silent loss）"
    else
        fail "6-3: worktree 被移除！K-experiment 檔可能 silent loss"
    fi
}

# ============================================================
# Test Case 7 (K1262-v4): locked worktree → 必印 unlock + remove + branch -D hint
#   不可用 --force fallback (CLAUDE.md L168 禁止)
# ============================================================
test_case_7_locked_worktree_hint() {
    echo "=== Case 7 (K1262-v4): locked worktree hint message ==="
    local test_dir
    test_dir=$(setup_test_env "case7")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase7"
    local branch="worktree-agent-testcase7"

    # Agent commit normally
    mkdir -p "$wt/experiments/k1262lock"
    echo "print('k1262lock')" > "$wt/experiments/k1262lock/k1262lock.py"
    (cd "$wt" && git add -A && git commit -qm "K1262lock deliverables")

    # Lock the worktree (creates .git/worktrees/<wt>/locked)
    git worktree lock "$wt" --reason "test: simulate stale claude-agent lock (pid 99999)" 2>/dev/null || true

    # Run merge script
    local output
    output=$(run_merge_in_test_dir "$test_dir")

    # 7-1: merge 應該 OK（commits 進 main），但 remove 應失敗
    if git -C "$test_dir" cat-file -e "main:experiments/k1262lock/k1262lock.py" 2>/dev/null; then
        pass "7-1: K-experiment 檔在 main HEAD（merge 成功）"
    else
        fail "7-1: K-experiment 檔不在 main HEAD"
    fi

    # 7-2: worktree remove 應 fail（loud）
    if echo "$output" | grep -qE "worktree remove 失敗|locked"; then
        pass "7-2: script 偵測到 locked worktree 並印警告"
    else
        fail "7-2: script 沒偵測 lock 或沒印警告"
        echo "$output" | tail -30
    fi

    # 7-3: 必印 unlock hint（git worktree unlock）
    if echo "$output" | grep -q "worktree unlock"; then
        pass "7-3: script 提示 git worktree unlock"
    else
        fail "7-3: 沒提示 unlock 命令"
    fi

    # 7-4: 必 NOT 用 --force fallback
    # 檢查 output 不該含 "嘗試 --force" / "git worktree remove --force"
    if echo "$output" | grep -qE "嘗試 --force|worktree remove --force"; then
        fail "7-4: script 用了 --force fallback（違反 CLAUDE.md L168）"
        echo "$output" | grep -i "force"
    else
        pass "7-4: script 沒走 --force fallback（符合 CLAUDE.md L168）"
    fi

    # cleanup: unlock worktree so trap rm -rf works clean
    git worktree unlock "$wt" 2>/dev/null || true
}

# ============================================================
# Run tests
# ============================================================
echo "### merge_worktree.sh 測試 (K1143-v2 + K1262-v4) ###"
echo ""

test_case_a
echo ""
test_case_b
echo ""
test_case_c
echo ""
test_case_d
echo ""
test_case_5_rev_list_false_negative
echo ""
test_case_6_post_merge_verification
echo ""
test_case_7_locked_worktree_hint
echo ""

echo "================================"
echo "Assertions PASS: $PASS"
echo "Assertions FAIL: $FAIL"
# Test case-level summary（7 cases = A/B/C/D + 5/6/7）
TOTAL_CASES=7
if [[ $FAIL -eq 0 ]]; then
    echo "Test cases: PASS $TOTAL_CASES/$TOTAL_CASES"
else
    echo "Test cases: FAIL — see assertion failures above"
fi
echo "================================"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
