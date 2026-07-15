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
#   Case 8 (K1618 STRIKE-2): caller 的 shell cwd **停在待合併 worktree 內**（Bash cwd 持久污染），
#           worktree branch 有未合併 commits。舊版 BASH_SOURCE-相對 MAIN_DIR 解析 → 指到
#           worktree root → main_branch=worktree 分支 → 自比自 0-commit false-negative →
#           走「可安全移除」未 merge 就砍 worktree（K1618 靠 branch 存活救回）。
#           → 修後 script 必用 git-common-dir 解析真 main root，正確 merge、無 silent loss。
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

# 2026-07-14: 合併現在要求「一份 PASS 裁決，且它審的就是現在這份 bytes」
# (scripts/experiment_gates.py certify)。這裡模擬一個守規矩的 agent：實驗凍結後
# 由審查者寫下 review_verdict.json。沒有它，實驗就進不了 main —— 那正是 K1709
# 的教訓，也是下面 case 14/15 專門守住的行為。
certify_all_experiments() {
    # 無參數（或該 case 沒有 $wt 變數）→ 掃所有 agent worktree
    local wt="${1:-}"
    if [[ -z "$wt" ]]; then
        local w
        for w in .claude/worktrees/*/; do
            [[ -d "$w" ]] && certify_all_experiments "${w%/}"
        done
        return 0
    fi
    [[ -d "$wt/experiments" ]] || return 0
    local exp_dir
    for exp_dir in "$wt/experiments"/*/; do
        [[ -d "$exp_dir" ]] || continue
        python3 - "$exp_dir" <<'PYCERT'
import hashlib, json, sys
from pathlib import Path
exp = Path(sys.argv[1])
surface = [
    p for p in sorted(exp.rglob("*"))
    if p.is_file() and "__pycache__" not in p.parts and p.name != "review_verdict.json"
    and (p.suffix == ".py" or p.name == "README.md" or p.name.endswith("_results.json"))
]
(exp / "review_verdict.json").write_text(json.dumps({
    "kid": exp.name,
    "verdict": "PASS",
    "reviewer": "test-fixture",
    "reviewed_at": "2026-07-14T00:00:00+08:00",
    "reviewed_sha256": {
        str(p.relative_to(exp)): hashlib.sha256(p.read_bytes()).hexdigest() for p in surface
    },
}, indent=2), encoding="utf-8")
PYCERT
    done
}

# ============================================================
# Helper: 建立一個臨時 git repo 作為主目錄 + 一個 worktree
# 關鍵：把 merge_worktree.sh copy 到 test_dir/scripts/ 裡，
# 這樣 script 用 BASH_SOURCE 解析 MAIN_DIR 時會指到 test_dir 而不是主 project。
# ============================================================
setup_test_env() {
    local test_name="$1"
    local test_dir="$TMP_BASE/$test_name"
    mkdir -p "$test_dir/scripts" "$test_dir/storage/ops"
    cp "$MERGE_SCRIPT" "$test_dir/scripts/merge_worktree.sh"
    cp "$PROJECT_ROOT/scripts/git_writer_lock.py" "$test_dir/scripts/git_writer_lock.py"
    mkdir -p "$test_dir/src/volpred/ops"
    cp "$PROJECT_ROOT/src/volpred/ops/git_writer_lock.py" \
        "$test_dir/src/volpred/ops/git_writer_lock.py"
    chmod +x "$test_dir/scripts/merge_worktree.sh"
    # merge 路徑會呼叫 trusted certify gate；gate 或其 stdlib dependency
    # 不存在時 merge_worktree.sh 會 fail-closed。certify 目前 arm MDD owner；
    # 其餘 auditor 保留給 run-path fixture。
    local real_scripts
    real_scripts="$(cd "$(dirname "$MERGE_SCRIPT")" && pwd)"
    cp "$real_scripts/experiment_gates.py" "$test_dir/scripts/"
    cp "$real_scripts/experiment_claim_surface.py" "$test_dir/scripts/"
    cp "$real_scripts/audit_nested_dm_misuse.py" "$test_dir/scripts/"
    cp "$real_scripts/audit_dm_hac_lag.py" "$test_dir/scripts/"
    cp "$real_scripts/audit_mdd_scale_artifact.py" "$test_dir/scripts/"
    cp "$real_scripts/audit_fevd_ordering.py" "$test_dir/scripts/"
    cp "$PROJECT_ROOT/storage/ops/mdd_scale_artifact_baseline.json" \
        "$test_dir/storage/ops/"

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

# K1618: run the script with cwd stuck INSIDE the given worktree (reproduces the
# persistent-cwd pollution that corrupted MAIN_DIR resolution). $2 = worktree relpath.
# 關鍵：用 **相對路徑** `scripts/merge_worktree.sh` 呼叫（=真實 K1618 觸發條件）。
# cwd 在 worktree 內時，相對路徑指到 worktree 自己的腳本副本，且 BASH_SOURCE 是相對路徑
# → 舊版據此把 MAIN_DIR 解析成 worktree root（絕對路徑呼叫不會重現此 bug）。
run_merge_from_inside_worktree() {
    local test_dir="$1"
    local wt_rel="$2"
    shift 2
    (cd "$test_dir/$wt_rel" && bash scripts/merge_worktree.sh "$@" 2>&1) || true
}

# K1618 review Finding 1: run the script from an arbitrary cwd via ABSOLUTE path.
# $1 = the cwd to run from, $2 = the test_dir whose script to invoke.
run_merge_from_cwd() {
    local run_cwd="$1"
    local test_dir="$2"
    shift 2
    (cd "$run_cwd" && bash "$test_dir/scripts/merge_worktree.sh" "$@" 2>&1) || true
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
    certify_all_experiments "${wt:-}"
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
    certify_all_experiments "${wt:-}"
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
    certify_all_experiments "${wt:-}"
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
    certify_all_experiments "${wt:-}"
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
    certify_all_experiments "${wt:-}"
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
    certify_all_experiments "${wt:-}"
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
    certify_all_experiments "${wt:-}"
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
# Test Case 8 (K1618 STRIKE-2): caller cwd 停在待合併 worktree 內
#   worktree branch 有未合併 commits。舊版 MAIN_DIR 誤解析成 worktree root →
#   main_branch=worktree 分支 → 自比自 0-commit → 走「可安全移除」未 merge 就砍。
#   修後必用 git-common-dir 解析真 main root，正確 merge、K-experiment 檔進 main、無 loss。
# ============================================================
test_case_8_cwd_inside_worktree() {
    echo "=== Case 8 (K1618 STRIKE-2): cwd 停在 worktree 內 → 不可 silent drop ==="
    local test_dir
    test_dir=$(setup_test_env "case8")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase8"
    local branch="worktree-agent-testcase8"

    # Agent 在 worktree 裡 commit experiments/k1618sim/（真實未合併 commit）
    mkdir -p "$wt/experiments/k1618sim"
    echo "print('k1618sim implementation')" > "$wt/experiments/k1618sim/k1618sim.py"
    echo "# K1618sim README" > "$wt/experiments/k1618sim/README.md"
    echo '{"verdict":"real"}' > "$wt/experiments/k1618sim/k1618sim_results.json"
    (cd "$wt" && git add -A && git commit -qm "K1618sim deliverables")

    # 確認 setup：worktree branch 有未合併 commit
    local commit_count
    commit_count=$(git rev-list --count "main..$branch" 2>/dev/null || echo "0")
    if [[ "$commit_count" -lt 1 ]]; then
        fail "8-setup: 預期 worktree branch 有未合併 commit 但 rev-list 報 0（測試環境問題）"
        return
    fi

    # 關鍵：從 worktree **內部** 執行 merge script（K1618 精確觸發條件）
    local output
    certify_all_experiments "${wt:-}"
    output=$(run_merge_from_inside_worktree "$test_dir" "$wt" agent-testcase8)

    # 8-1: k1618sim.py 必進 main HEAD（不可 silent drop）
    if git -C "$test_dir" cat-file -e "main:experiments/k1618sim/k1618sim.py" 2>/dev/null; then
        pass "8-1: k1618sim.py 在 main HEAD（cwd 在 worktree 內仍正確 merge）"
    else
        fail "8-1: k1618sim.py 不在 main HEAD（K1618 silent drop 重現！）"
        echo "$output" | tail -50
    fi

    # 8-2: 三件套齊全在 main HEAD
    if git -C "$test_dir" cat-file -e "main:experiments/k1618sim/README.md" 2>/dev/null \
       && git -C "$test_dir" cat-file -e "main:experiments/k1618sim/k1618sim_results.json" 2>/dev/null; then
        pass "8-2: README + results.json 也在 main HEAD"
    else
        fail "8-2: 部分檔案遺失"
    fi

    # 8-3: script 絕不可誤判「沒有新的 commits...可安全移除」（K1618 false-negative pattern）
    if echo "$output" | grep -q "沒有新的 commits.*可安全移除"; then
        fail "8-3: script 誤判 no-commits（K1618 self-compare false negative 重現！）"
        echo "$output" | grep -B2 -A2 "可安全移除"
    else
        pass "8-3: script 沒誤判 no-commits（MAIN_DIR robust 解析防住自比自）"
    fi

    # 8-4: MAIN_DIR 不可被誤解析成 worktree（不可出現 FATAL worktree-branch HEAD）
    if echo "$output" | grep -qE "MAIN_DIR.*worktree 分支|main_branch.*== worktree branch"; then
        fail "8-4: MAIN_DIR/main_branch 仍被解析成 worktree（fix 未生效或 guard 誤觸）"
        echo "$output" | grep -E "FATAL|ABORT" | head -10
    else
        pass "8-4: MAIN_DIR 正確解析成主 repo（未觸發 worktree-branch guard）"
    fi
}

# ============================================================
# Test Case 9 (K1618 review Finding 2): -X ours drop 了 agent 對既有檔的修改
#   → 舊版只警告仍移除 worktree+branch -D → agent 修改遺失。
#   修後必 AUTO-RESTORE agent 版本並 commit，main HEAD 保留 agent 修改。
# ============================================================
test_case_9_ours_dropped_auto_restore() {
    echo "=== Case 9 (Finding 2): -X ours drop modified 檔 → 自動還原不遺失 ==="
    local test_dir
    test_dir=$(setup_test_env "case9")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase9"
    local branch="worktree-agent-testcase9"

    # seed 加一個既有檔 experiments/km9/km9.py（main + worktree 都會有）
    mkdir -p experiments/km9
    echo "v0" > experiments/km9/km9.py
    git add -A && git commit -qm "seed km9.py v0"
    # 讓 worktree 追上這個 commit
    (cd "$wt" && git merge main --no-edit -q 2>&1 || git reset --hard main -q)

    # agent 在 worktree 改 km9.py
    echo "agent v1" > "$wt/experiments/km9/km9.py"
    (cd "$wt" && git add -A && git commit -qm "agent modifies km9.py")

    # main ALSO 改 km9.py（製造衝突 → -X ours 取 main → drop agent 版本）
    echo "main v1" > experiments/km9/km9.py
    git add -A && git commit -qm "main modifies km9.py"

    local output
    certify_all_experiments "${wt:-}"
    output=$(run_merge_in_test_dir "$test_dir")

    # 9-1: main HEAD 的 km9.py 必是 agent 版本（auto-restore 生效）
    local final_content
    final_content=$(git -C "$test_dir" show "main:experiments/km9/km9.py" 2>/dev/null || echo "MISSING")
    if [[ "$final_content" == "agent v1" ]]; then
        pass "9-1: main HEAD km9.py = agent 版本（-X ours drop 已自動還原，無資料遺失）"
    else
        fail "9-1: km9.py = '$final_content'（agent 修改遺失！Finding 2 重現）"
        echo "$output" | grep -E "DROPPED|RESTORE|還原" | head -10
    fi

    # 9-2: script 必印 AUTO-RESTORE 訊息
    if echo "$output" | grep -q "AUTO-RESTORE"; then
        pass "9-2: script 執行 auto-restore（非只警告）"
    else
        fail "9-2: script 沒 auto-restore"
    fi
}

# ============================================================
# Test Case 10 (K1618 review Finding 1): cwd 在**無關 git repo** + 絕對路徑呼叫
#   → MAIN_DIR 必 anchor 到腳本所屬 repo（本 repo），不可被 cwd repo 綁架。
# ============================================================
test_case_10_cross_repo_cwd_anchor() {
    echo "=== Case 10 (Finding 1): cwd 在無關 repo → MAIN_DIR anchor 腳本 repo ==="
    local test_dir
    test_dir=$(setup_test_env "case10")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase10"
    local branch="worktree-agent-testcase10"
    mkdir -p "$wt/experiments/kx10"
    echo "print('kx10')" > "$wt/experiments/kx10/kx10.py"
    (cd "$wt" && git add -A && git commit -qm "kx10 deliverables")

    # 建無關 repo B
    local repo_b="$TMP_BASE/unrelated_repo_b"
    mkdir -p "$repo_b"
    (cd "$repo_b" && git init -b main -q && git config user.email t@t && git config user.name t \
        && echo x > x.txt && git add -A && git commit -qm "b")

    # 從 repo B 的 cwd，絕對路徑呼叫 test_dir 的 script
    local output
    certify_all_experiments "${wt:-}"
    output=$(run_merge_from_cwd "$repo_b" "$test_dir" agent-testcase10)

    # 10-1: kx10 必 merge 進 test_dir（腳本 repo），不是 repo B
    if git -C "$test_dir" cat-file -e "main:experiments/kx10/kx10.py" 2>/dev/null; then
        pass "10-1: kx10 merge 進腳本所屬 repo（MAIN_DIR anchor 正確）"
    else
        fail "10-1: kx10 沒進腳本 repo（MAIN_DIR 被 cwd repo 綁架，Finding 1 重現）"
        echo "$output" | tail -30
    fi

    # 10-2: repo B 未被污染（仍只 1 commit、無 kx10）
    local b_commits
    b_commits=$(git -C "$repo_b" rev-list --count HEAD 2>/dev/null || echo "?")
    if [[ "$b_commits" == "1" ]] && ! git -C "$repo_b" cat-file -e "HEAD:experiments/kx10/kx10.py" 2>/dev/null; then
        pass "10-2: 無關 repo B 未被污染"
    else
        fail "10-2: 無關 repo B 被動到（commits=$b_commits）"
    fi
}

# ============================================================
# Test Case 11 (2026-07-10): shared-JSON guard 必須只看 agent 改了什麼
#   main 在 branch 分出去之後自己改了 feed.json（cron 每小時都在做這件事）。
#   舊版用 two-dot `main..branch` → 把 main 自己的改動記到 agent 頭上 → 誤 ABORT。
#   任何 base 稍舊的 worktree 都中，安全網變路障，逼人手動硬 merge。
# ============================================================
test_case_11_stale_base_no_false_abort() {
    echo "=== Case 11: main 自己動了 feed.json → 不可誤判成 agent 修改 ==="
    local test_dir
    test_dir=$(setup_test_env "case11")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase11"

    # agent 只碰自己的 experiments/（完全合規）
    mkdir -p "$wt/experiments/k9911"
    echo "print('k9911')" > "$wt/experiments/k9911/k9911.py"
    (cd "$wt" && git add -A && git commit -qm "k9911: agent 只動 experiments/")

    # main 在 branch 分出去「之後」改共享 JSON —— 這是 cron 的日常，不是違規
    mkdir -p storage/reports
    echo '{"articles": ["cron 每小時寫這支"]}' > storage/reports/feed.json
    git add -A && git commit -qm "main: cron 更新 feed.json"

    local output
    certify_all_experiments "${wt:-}"
    output=$(run_merge_in_test_dir "$test_dir")

    # 11-1: 不可 ABORT
    if echo "$output" | grep -q "Agent 修改了共享 JSON"; then
        fail "11-1: 誤判 ABORT（two-dot 回歸；main 自己的 feed.json 改動被算到 agent 頭上）"
        echo "$output" | grep -E "ABORT|共享 JSON" | head -5
    else
        pass "11-1: main 自己改 feed.json 不觸發 shared-JSON ABORT"
    fi

    # 11-2: 合併真的發生 —— agent 的檔案要進 main 的 git tree（不只 working tree）
    if git -C "$test_dir" cat-file -e "main:experiments/k9911/k9911.py" 2>/dev/null; then
        pass "11-2: k9911.py 已在 main HEAD 的 git tree"
    else
        fail "11-2: k9911.py 不在 main HEAD（合併被誤 abort 擋掉）"
    fi

    # 11-3: main 自己的 feed.json 不可被 agent 版本蓋掉
    local feed
    feed=$(git -C "$test_dir" show "main:storage/reports/feed.json" 2>/dev/null || echo MISSING)
    if [[ "$feed" == *"cron 每小時寫這支"* ]]; then
        pass "11-3: main 的 feed.json 內容保留"
    else
        fail "11-3: feed.json = '$feed'（main 的 live state 被覆蓋）"
    fi
}

# ============================================================
# Test Case 12 (2026-07-10): guard 真的該響時要響，且 stash 還原不可假警報
#   agent 真的改了 feed.json → 必 ABORT（Case 11 不能把 guard 修成永遠不響）。
#   且 main 有未提交變更時：stash pop 成功就不准印「stash pop 失敗」。
#   舊版 `git stash pop | head -5 || echo 失敗` 在 pipefail 下被 SIGPIPE 打成 rc=141，
#   pop 成功也印失敗，還叫人 `git stash apply stash@{0}` —— 那已是別人的舊 stash。
# ============================================================
test_case_13_unregistered_standalone_repo_dir() {
    # K1684 (2026-07-12), STRIKE 3 of the K1032 class. A directory under .claude/worktrees/ that
    # carries its OWN .git is invisible to `git worktree list` — so every existing defence layer
    # (rev-list, diff-tree, post-merge cat-file) is never even reached, and the script used to
    # print "=== 完成 ===" while an entire experiment sat unmerged in a foreign object store.
    echo "=== Case 13: .claude/worktrees/ 底下的獨立 repo（非註冊 worktree）→ 必須 fail loud ==="
    local test_dir
    test_dir=$(setup_test_env "case13")
    cd "$test_dir"

    # 一個「看起來像 worktree、其實是獨立 repo」的目錄
    local rogue=".claude/worktrees/k9999-rogue"
    mkdir -p "$rogue/experiments/k9999"
    (
        cd "$rogue"
        git init -q -b agent/k9999-rogue-r2
        git config user.email t@t; git config user.name t
        echo '{"GATE_VERDICT": "H2_UNSUPPORTED"}' > experiments/k9999/k9999_results.json
        git add -A && git commit -qm "k9999: 只存在於這個獨立 repo 的實驗結果"
    ) >/dev/null 2>&1

    local output
    certify_all_experiments "${wt:-}"
    output=$(run_merge_in_test_dir "$test_dir")

    # 13-1: 必須被偵測到並 fail loud（舊版是完全靜默）
    if echo "$output" | grep -q "\[ABORT\] k9999-rogue"; then
        pass "13-1: 未註冊的獨立 repo 目錄被偵測並 ABORT"
    else
        fail "13-1: 獨立 repo 目錄被靜默跳過（K1032 class silent orphan 復發）"
    fi

    # 13-2: 要給得出可執行的 path-scoped 復原指令，不是叫人跨 repo merge
    if echo "$output" | grep -q "fetch .claude/worktrees/k9999-rogue agent/k9999-rogue-r2"; then
        pass "13-2: 印出 path-scoped 復原指令（fetch + checkout）"
    else
        fail "13-2: 沒印出可執行的復原指令"
    fi

    # 13-3: 不可以在漏掉它的情況下宣告一切完成
    if echo "$output" | grep -q "有未註冊的 worktree 目錄未處理"; then
        pass "13-3: 收尾訊息沒有掩蓋未處理的目錄"
    else
        fail "13-3: script 照常宣告完成，掩蓋了未合併的實驗"
    fi

    # 13-4: 這個目錄的 commit 確實不在 main 的 object store（本 case 的前提要成立）
    if git -C "$test_dir" log --all --oneline 2>/dev/null | grep -q "k9999"; then
        fail "13-4: 前提不成立 — rogue commit 竟在 main object store（測試沒測到該測的東西）"
    else
        pass "13-4: rogue commit 確實不在 main object store（前提成立）"
    fi
}

test_case_12_real_violation_aborts_and_stash_restores() {
    echo "=== Case 12: agent 真改 feed.json → ABORT；且 stash 還原不假警報 ==="
    local test_dir
    test_dir=$(setup_test_env "case12")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase12"

    mkdir -p storage/reports
    echo '{"articles": []}' > storage/reports/feed.json
    git add -A && git commit -qm "seed feed.json"
    (cd "$wt" && git merge main --no-edit -q 2>&1 || git reset --hard main -q)

    # agent 違規改共享 JSON
    echo '{"articles": ["agent 不該碰這支"]}' > "$wt/storage/reports/feed.json"
    (cd "$wt" && git add -A && git commit -qm "agent 違規改 feed.json")

    # main 有一堆未提交變更 → 觸發 stash；夠多行才能讓舊版的 head -5 提早關管線
    # 只 stage dirty_*.txt：`git add -A` 會把測試用的 worktree 當 embedded repo 加進 index
    local i
    for i in $(seq 1 12); do echo "dirty $i" > "dirty_$i.txt"; done
    git add dirty_*.txt

    local output
    certify_all_experiments "${wt:-}"
    output=$(run_merge_in_test_dir "$test_dir")

    # 12-1: guard 該響
    if echo "$output" | grep -q "Agent 修改了共享 JSON"; then
        pass "12-1: agent 真改 feed.json → ABORT（guard 沒被 Case 11 修壞）"
    else
        fail "12-1: agent 改了 feed.json 卻沒 ABORT（guard 失效）"
    fi

    # 12-2: pop 成功就不准印失敗
    if echo "$output" | grep -q "stash pop 失敗"; then
        fail "12-2: 假警報「stash pop 失敗」（pipefail + head -5 的 SIGPIPE 回歸）"
    else
        pass "12-2: stash pop 成功，無假警報"
    fi

    # 12-3: 絕不可教人跑 stash@{0}（pop 已成功，那是別人的 stash）
    if echo "$output" | grep -q "stash apply stash@{0}"; then
        fail "12-3: 提示 stash@{0} —— 照做會把陳年 stash 蓋回 main"
    else
        pass "12-3: 未提示危險的 stash@{0}"
    fi

    # 12-4: main 的未提交變更必須真的回到工作區（不可 silent stash）
    if [[ -f "$test_dir/dirty_12.txt" ]]; then
        pass "12-4: main 的未提交變更已還原"
    else
        fail "12-4: dirty_12.txt 不見了（stash 沒還原，工作被吞）"
    fi
}

# ============================================================
# Run tests
# ============================================================
echo "### merge_worktree.sh 測試 (K1143-v2 + K1262-v4 + K1618 + 2026-07-10 guard) ###"
echo ""


# ============================================================================
# Case 14/15/16 (2026-07-14): 審查認證 gate — K1709 的三個入口全部關上
# K1709 被 Codex 判 FAIL 卻仍 merge 進 main → nested-DM ratchet 讓連續三班
# dispatch 的 push 全紅。merge 路徑從來沒讀過裁決。
# ============================================================================
test_case_14_uncertified_experiment_blocked() {
    echo "=== Case 14: 實驗沒有審查裁決 → 拒絕合併 ==="
    local test_dir
    test_dir=$(setup_test_env "case14")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase14"

    mkdir -p "$wt/experiments/k14un"
    echo "print('never reviewed')" > "$wt/experiments/k14un/k14un.py"
    echo "# K14" > "$wt/experiments/k14un/README.md"

    # 注意：故意不呼叫 certify_all_experiments
    local output
    output=$(run_merge_in_test_dir "$test_dir") || true

    if ! git -C "$test_dir" cat-file -e "main:experiments/k14un/k14un.py" 2>/dev/null; then
        pass "14-1: 未認證的實驗沒有進 main"
    else
        fail "14-1: 未認證的實驗竟然合併了（K1709 重現）"
    fi

    if echo "$output" | grep -q "未通過審查認證"; then
        pass "14-2: 明確說出為什麼擋"
    else
        fail "14-2: 沒說明擋的原因"
    fi

    if [[ -f "$test_dir/$wt/experiments/k14un/k14un.py" ]]; then
        pass "14-3: worktree 保留，工作沒被丟掉"
    else
        fail "14-3: 擋下來卻把 agent 的工作弄丟了"
    fi
}

test_case_15_fail_verdict_blocked() {
    echo "=== Case 15 (K1709 verbatim): 裁決是 FAIL → 拒絕合併 ==="
    local test_dir
    test_dir=$(setup_test_env "case15")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase15"

    mkdir -p "$wt/experiments/k15fail"
    echo "print('reviewer said no')" > "$wt/experiments/k15fail/k15fail.py"
    certify_all_experiments "$wt"
    # 審查者判 FAIL
    python3 - "$test_dir/$wt/experiments/k15fail/review_verdict.json" <<'PYF'
import json, sys
from pathlib import Path
p = Path(sys.argv[1]); c = json.loads(p.read_text()); c["verdict"] = "FAIL"
p.write_text(json.dumps(c, indent=2))
PYF

    local output
    output=$(run_merge_in_test_dir "$test_dir") || true

    if ! git -C "$test_dir" cat-file -e "main:experiments/k15fail/k15fail.py" 2>/dev/null; then
        pass "15-1: FAIL 的實驗沒有進 main"
    else
        fail "15-1: FAIL 的實驗被合併了 — 這正是 K1709 讓 CI 連紅 4 次的原因"
    fi

    if echo "$output" | grep -q "未通過審查認證"; then
        pass "15-2: merge 路徑真的讀了裁決"
    else
        fail "15-2: merge 路徑沒讀裁決"
    fi
}

test_case_16_stale_pass_verdict_blocked() {
    echo "=== Case 16: PASS 之後又改了 code → 裁決過期，一樣擋 ==="
    local test_dir
    test_dir=$(setup_test_env "case16")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase16"

    mkdir -p "$wt/experiments/k16stale"
    echo "print('v1 — the bytes the reviewer saw')" > "$wt/experiments/k16stale/k16stale.py"
    certify_all_experiments "$wt"   # PASS，pin 住 v1 的 sha256

    # 審查之後 agent 又改了 code（2026-07-14 K1709 rev1 真實發生的事）
    echo "print('v2 — fixed after the review, never re-reviewed')" \
        > "$wt/experiments/k16stale/k16stale.py"

    local output
    output=$(run_merge_in_test_dir "$test_dir") || true

    if ! git -C "$test_dir" cat-file -e "main:experiments/k16stale/k16stale.py" 2>/dev/null; then
        pass "16-1: 審完又改過的 code 沒有靠舊 PASS 混進 main"
    else
        fail "16-1: 陳舊的 PASS 裁決放行了沒人審過的 bytes"
    fi

    if echo "$output" | grep -q "未通過審查認證"; then
        pass "16-2: 認證與 bytes 綁定，不只與檔名綁定"
    else
        fail "16-2: gate 沒抓到 sha 漂移"
    fi
}


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
test_case_8_cwd_inside_worktree
echo ""
test_case_9_ours_dropped_auto_restore
echo ""
test_case_10_cross_repo_cwd_anchor
echo ""
test_case_11_stale_base_no_false_abort
echo ""
test_case_12_real_violation_aborts_and_stash_restores
echo ""
test_case_13_unregistered_standalone_repo_dir
echo ""

test_case_14_uncertified_experiment_blocked
echo ""
test_case_15_fail_verdict_blocked
echo ""
test_case_16_stale_pass_verdict_blocked
echo ""

echo "================================"
echo "Assertions PASS: $PASS"
echo "Assertions FAIL: $FAIL"
# Test case-level summary（16 cases = A/B/C/D + 5/6/7 + 8/9/10 + 11/12 + 13 + 14/15/16 認證 gate）
TOTAL_CASES=16
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
