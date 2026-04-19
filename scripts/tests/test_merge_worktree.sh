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
# Run tests
# ============================================================
echo "### merge_worktree.sh 測試 (K1143-v2) ###"
echo ""

test_case_a
echo ""
test_case_b
echo ""
test_case_c
echo ""
test_case_d
echo ""

echo "================================"
echo "PASS: $PASS"
echo "FAIL: $FAIL"
echo "================================"

if [[ $FAIL -gt 0 ]]; then
    exit 1
fi
exit 0
