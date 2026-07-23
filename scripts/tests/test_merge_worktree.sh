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

# 2026-07-19: 跑腳本並保留 exit code（既有 helper 都用 `|| true` 吞掉 rc，
# 但 case 20 的成功判準就是「必須非 0 退出」）。
# 注意：呼叫端是 `output=$(run_merge_capture_rc ...)`，函式跑在 command-substitution
# 的 subshell 裡 → 任何 shell 變數賦值都回不到 parent。所以 rc 走檔案傳遞，
# 用 last_merge_rc 讀取。
run_merge_capture_rc() {
    local test_dir="$1"
    shift
    local rc=0
    (cd "$test_dir" && bash "$test_dir/scripts/merge_worktree.sh" "$@") \
        > "$TMP_BASE/last_run.out" 2>&1 || rc=$?
    printf '%s' "$rc" > "$TMP_BASE/last_run.rc"
    cat "$TMP_BASE/last_run.out"
}
last_merge_rc() { cat "$TMP_BASE/last_run.rc" 2>/dev/null || echo "NORC"; }

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
# Test Case 12 (2026-07-10; 2026-07-16 收斂): guard 真的該響時要響，且
#   agent 真的改了 feed.json → 必 ABORT（Case 11 不能把 guard 修成永遠不響）。
#   main WIP 必須原地保留；merge_worktree 不得再建立/套用任何 temp stash。
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

test_case_12_real_violation_aborts_without_stash() {
    echo "=== Case 12: agent 真改 feed.json → ABORT；main WIP 原地保留、不 stash ==="
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

    # main 有一堆未提交變更；新契約必須原地保留，不可 stash。
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

    # 12-2: 不得建立 temp stash。
    if git stash list | grep -q "merge_worktree: temp stash"; then
        fail "12-2: merge_worktree 建立了 temp stash（仍會觸碰其他 slot WIP）"
    else
        pass "12-2: 沒有建立 temp stash"
    fi

    # 12-3: 輸出也不可再提供任何 stash recovery 路徑。
    if echo "$output" | grep -q "stash@{0}\|stash pop\|temp stash"; then
        fail "12-3: 輸出仍含 stash recovery 路徑"
    else
        pass "12-3: 無 stash recovery 路徑"
    fi

    # 12-4: main 的未提交變更全程留在工作區。
    if [[ -f "$test_dir/dirty_12.txt" ]]; then
        pass "12-4: main 的未提交變更原地保留"
    else
        fail "12-4: dirty_12.txt 不見了（其他 slot 工作被吞）"
    fi

    # 12-5: class-level static gate；不是只期待某個 fixture 剛好沒走到 stash branch。
    if grep -Eq 'git[[:space:]]+stash[[:space:]]+(push|pop|apply)' "$MERGE_SCRIPT"; then
        fail "12-5: production merge script 仍含 runtime stash mutation"
    else
        pass "12-5: production merge script 無 runtime stash mutation"
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

# ============================================================
# Case 17/18 (2026-07-16): multi-slot dirty-main contract
#   - 同一路徑 WIP：fail-closed，原 bytes / worktree / branch 全保留，零 stash。
#   - 不相交 WIP：允許 integration，WIP 不進 commit 且仍留在 working tree。
# ============================================================
test_case_17_overlapping_dirty_main_aborts_without_stash() {
    echo "=== Case 17: main 同檔 WIP 與 agent 重疊 → ABORT、零 stash ==="
    local test_dir
    test_dir=$(setup_test_env "case17")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase17"
    local branch="worktree-agent-testcase17"

    mkdir -p experiments/k17overlap
    echo "print('base')" > experiments/k17overlap/k17overlap.py
    echo "# K17 overlap" > experiments/k17overlap/README.md
    echo "{}" > experiments/k17overlap/k17overlap_results.json
    git add experiments/k17overlap
    git commit -qm "seed shared experiment file"
    (cd "$wt" && git merge main --no-edit -q)

    echo "print('agent version')" > "$wt/experiments/k17overlap/k17overlap.py"
    (cd "$wt" && git add experiments/k17overlap && git commit -qm "agent edits shared file")
    certify_all_experiments "$wt"

    # 另一個 slot 在 main 同一路徑有未提交內容。
    echo "print('interactive WIP')" > experiments/k17overlap/k17overlap.py

    local output
    output=$(run_merge_in_test_dir "$test_dir")

    if echo "$output" | grep -q "WIP 與 agent 變更路徑重疊"; then
        pass "17-1: 同一路徑 dirty WIP 被 fail-closed 擋下"
    else
        fail "17-1: 沒有明確偵測同一路徑 overlap"
    fi
    if [[ "$(cat experiments/k17overlap/k17overlap.py)" == "print('interactive WIP')" ]]; then
        pass "17-2: main 上其他 slot 的 bytes 原封不動"
    else
        fail "17-2: main WIP 被 merge/stash 流程改寫"
    fi
    if [[ -d "$wt" ]] && ! git merge-base --is-ancestor "$branch" main 2>/dev/null; then
        pass "17-3: worktree/branch 保留且未假裝 merged"
    else
        fail "17-3: overlap abort 後 worktree 或 branch 狀態不安全"
    fi
    if git stash list | grep -q "merge_worktree: temp stash"; then
        fail "17-4: overlap 路徑仍建立 temp stash"
    else
        pass "17-4: overlap 路徑零 stash"
    fi
}

test_case_18_unrelated_dirty_main_merges_in_place() {
    echo "=== Case 18: main 不相交 WIP → 原地保留並完成 merge、零 stash ==="
    local test_dir
    test_dir=$(setup_test_env "case18")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase18"

    echo "base note" > operator_notes.txt
    git add operator_notes.txt
    git commit -qm "seed unrelated tracked file"
    (cd "$wt" && git merge main --no-edit -q)

    mkdir -p "$wt/experiments/k18clean"
    echo "print('agent experiment')" > "$wt/experiments/k18clean/k18clean.py"
    echo "# K18 clean" > "$wt/experiments/k18clean/README.md"
    echo "{}" > "$wt/experiments/k18clean/k18clean_results.json"
    certify_all_experiments "$wt"

    echo "operator WIP" > operator_notes.txt

    local output
    output=$(run_merge_in_test_dir "$test_dir")

    if git -C "$test_dir" cat-file -e "main:experiments/k18clean/k18clean.py" 2>/dev/null; then
        pass "18-1: 不相交 dirty main 仍完成 agent integration"
    else
        fail "18-1: 不相交 WIP 不必要地阻塞 merge"
    fi
    if [[ "$(cat operator_notes.txt)" == "operator WIP" ]] && \
       [[ "$(git show main:operator_notes.txt)" == "base note" ]]; then
        pass "18-2: WIP 留在 working tree，未混入 merge commit"
    else
        fail "18-2: 不相交 WIP 被覆寫或捲入 commit"
    fi
    if git stash list | grep -q "merge_worktree: temp stash"; then
        fail "18-3: 不相交路徑仍建立 temp stash"
    else
        pass "18-3: 不相交路徑零 stash"
    fi
    if echo "$output" | grep -q "原地保留，不 stash"; then
        pass "18-4: 輸出明確揭露保留 dirty WIP 的決策"
    else
        fail "18-4: 缺少 dirty-WIP 決策訊息"
    fi
}

test_case_19_foreign_staged_index_aborts_unchanged() {
    echo "=== Case 19: main foreign staged index → ABORT、index 原封不動 ==="
    local test_dir
    test_dir=$(setup_test_env "case19")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase19"
    mkdir -p "$wt/experiments/k19staged"
    echo "print('agent experiment')" > "$wt/experiments/k19staged/k19staged.py"
    echo "# K19 staged" > "$wt/experiments/k19staged/README.md"
    echo "{}" > "$wt/experiments/k19staged/k19staged_results.json"
    certify_all_experiments "$wt"

    echo "foreign staged bytes" > foreign_owner.txt
    git add foreign_owner.txt

    local output
    output=$(run_merge_in_test_dir "$test_dir")

    if echo "$output" | grep -q "main index 已有 staged 內容"; then
        pass "19-1: foreign staged index 被 fail-closed 擋下"
    else
        fail "19-1: staged preflight 沒有觸發"
    fi
    if git diff --cached --name-only | grep -qx "foreign_owner.txt" && \
       [[ "$(cat foreign_owner.txt)" == "foreign staged bytes" ]]; then
        pass "19-2: foreign index 與 working bytes 原封不動"
    else
        fail "19-2: merge 流程改寫/unstage 了 foreign owner 內容"
    fi
    if ! git -C "$test_dir" cat-file -e "main:experiments/k19staged/k19staged.py" 2>/dev/null && \
       [[ -d "$wt" ]]; then
        pass "19-3: agent branch 未假裝 merged，worktree 保留"
    else
        fail "19-3: staged abort 後 agent/worktree 狀態不安全"
    fi
    if git stash list | grep -q "merge_worktree: temp stash"; then
        fail "19-4: staged abort 路徑仍建立 temp stash"
    else
        pass "19-4: staged abort 路徑零 stash"
    fi
}


# ============================================================
# Test Case 20 (2026-07-19 SCOPE FIX): 成果只在 storage/、auto-commit 沒抓到
# → 必須 ABORT（非 0 exit），不得印「可安全移除」、不得移除 worktree
#
# 這是 2026-07-17 hourly-slot-2 合併 dispatch-slot-1 時發現的失效路徑：K1262-v4 PRIMARY
# 與 K1143-v2 兩層防線都只掃 worktree 的 experiments/，但 agent 成果早就不只放那裡。
# 成果全在 storage/event_articles/ + auto-commit 沒捕捉到 → rev-list=0 且 experiments/
# 是空的 → 舊版直接走「[OK] …experiments/ 也空，可安全移除」→ 未合併就砍 worktree。
# 那次沒出事只是因為 auto-commit 剛好正常且 branch 還在。
# ============================================================
test_case_20_storage_only_work_autocommit_failed() {
    echo "=== Case 20: 成果只在 storage/ + auto-commit 失效 → 必須 ABORT ==="
    local test_dir
    test_dir=$(setup_test_env "case20")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase20"

    # Agent 成果全部在 storage/ —— 完全不碰 experiments/（= 舊防線的盲區）
    mkdir -p "$wt/storage/event_articles"
    echo "# 事件文章：CPI 跳升" > "$wt/storage/event_articles/cpi_20260717.md"
    echo '{"kid": "evt1"}' > "$wt/storage/event_articles/cpi_20260717.json"

    # Mock「auto-commit 沒有捕捉到 agent 成果」：
    # 用 .git/info/exclude（位於 git-common-dir，linked worktree 共用）把成果路徑藏起來，
    # 於是 worktree 內 `git status --porcelain` 是乾淨的 → 腳本判定 has_uncommitted=false
    # → 根本不會觸發 auto-commit → rev-list=0。這正是 line 189 auto-commit 靜默沒生效
    # 時的實際狀態，也是 K1143-v2 註解自己列出的成因之一（「gitignore 吃掉檔案」）。
    echo "storage/event_articles/" >> "$test_dir/.git/info/exclude"

    # sanity：確認 mock 真的生效，否則這個測試測不到目標路徑
    if [[ -n "$(cd "$test_dir/$wt" && git status --porcelain)" ]]; then
        fail "20-0: mock 失效 — git status 仍看得到成果，測不到 rev-list=0 路徑"
        return
    fi

    local output rc
    output=$(run_merge_capture_rc "$test_dir")
    rc=$(last_merge_rc)

    if [[ "$rc" != "0" ]] && [[ "$rc" != "NORC" ]]; then
        pass "20-1: script 非 0 退出 (rc=$rc)"
    else
        fail "20-1: script exit 0 —— 未合併的成果被當成一次成功的整合"
    fi

    if echo "$output" | grep -q "ABORT"; then
        pass "20-2: 印出 ABORT"
    else
        fail "20-2: 沒有 ABORT"
        echo "$output" | tail -25
    fi

    if echo "$output" | grep -q "可安全移除"; then
        fail "20-3: 竟宣告「可安全移除」（storage-only 盲區重現）"
    else
        pass "20-3: 未宣告「可安全移除」"
    fi

    # 最關鍵：成果檔與 worktree 必須都還在
    if [[ -f "$test_dir/$wt/storage/event_articles/cpi_20260717.md" ]]; then
        pass "20-4: worktree 成果檔仍在（無 silent data loss）"
    else
        fail "20-4: 成果檔遺失 — worktree 未合併就被移除 (silent data loss!)"
    fi

    if git worktree list --porcelain | grep -q "agent-testcase20"; then
        pass "20-5: worktree 仍註冊（未被移除）"
    else
        fail "20-5: worktree 已被移除"
    fi

    # ABORT 訊息要指得出是哪個檔，否則人工復原無從下手
    if echo "$output" | grep -q "storage/event_articles/cpi_20260717.md"; then
        pass "20-6: ABORT 訊息列出具體檔案路徑"
    else
        fail "20-6: ABORT 訊息沒列出檔案路徑"
    fi
}

# ============================================================
# Test Case 21 (2026-07-19): --dry-run 不得自相矛盾
# 舊版 dry-run 不真的 commit → rev-list 必然 0 → 同時印「會自動提交」與
# 「可安全移除」，讓人誤判 worktree 是空的。
# ============================================================
test_case_21_dryrun_no_contradiction() {
    echo "=== Case 21: --dry-run 訊息不自相矛盾 ==="
    local test_dir
    test_dir=$(setup_test_env "case21")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase21"
    mkdir -p "$wt/storage/drafts"
    echo "draft body" > "$wt/storage/drafts/d1.md"

    local output
    output=$(run_merge_in_test_dir "$test_dir" --dry-run)

    if echo "$output" | grep -q "會自動提交" && echo "$output" | grep -q "可安全移除"; then
        fail "21-1: dry-run 自相矛盾（同時宣稱會自動提交 + 可安全移除）"
        echo "$output" | tail -25
    else
        pass "21-1: dry-run 無自相矛盾訊息"
    fi

    if echo "$output" | grep -q "會自動提交"; then
        pass "21-2: dry-run 有回報「會自動提交」"
    else
        fail "21-2: dry-run 沒回報未提交變更"
    fi

    if [[ -f "$test_dir/$wt/storage/drafts/d1.md" ]]; then
        pass "21-3: dry-run 未動 worktree 檔案"
    else
        fail "21-3: dry-run 竟動到 worktree 檔案"
    fi
}

# ============================================================
# Test Case 22 (K1262-v6): worktree tip 落後 main（0 自有 commit），main 期間刪掉/搬走檔案
# → 舊版 file-presence diff 把「main 自己刪掉的舊檔」當成 worktree 成果 → 觸發 fallback
#   → 用 `git log --all` 重建 commit list = **全 repo 其他分支**（其他 worktree 進行中的
#   工作 + 測試 fixture commit）→ 非 dry-run 會把別人未完成的工作 cherry-pick 進 main。
# → 修後：ancestor 判定使該訊號失效、fallback 永不用 --all，結論必須是「0 commits」，
#   且輸出**不得**出現任何其他分支的 commit。
# ============================================================
test_case_22_stale_worktree_no_foreign_commits() {
    echo "=== Case 22 (K1262-v6): 落後的 worktree 不得撈進其他分支的 commit ==="
    local test_dir
    test_dir=$(setup_test_env "case22")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase22"

    # main 前進：搬走一個檔 + 刪掉一個 runtime 檔（= 本次誤判的兩類噪音）
    mkdir -p scripts/_legacy storage/ops/event_ledger
    echo "x" > scripts/weekly_quota_estimate.py
    echo "{}" > storage/ops/event_ledger/abc123.json
    git add scripts storage && git commit -qm "add files that main will later move/drop"
    (cd "$wt" && git reset --hard main -q)   # worktree tip 與 main 同步後才落後
    git mv scripts/weekly_quota_estimate.py scripts/_legacy/weekly_quota_estimate.py
    git rm -q storage/ops/event_ledger/abc123.json
    git commit -qm "main: move to _legacy, drop runtime file"

    # 其他分支：模擬其他 worktree 進行中的工作 + 測試 fixture commit
    local i
    for i in 1 2; do
        git checkout -q -b "other/k$i" main
        echo "wip$i" > "experiments/other$i.txt"
        git add experiments && git commit -qm "other-branch wip $i (K17$i rev7)"
    done
    git checkout -q -b bad/fixture main
    echo f > f.txt && git add f.txt && git commit -qm "bad: new silent fallback"
    git checkout -q main

    local own
    own=$(git rev-list --count "main..worktree-agent-testcase22" 2>/dev/null || echo ERR)
    if [[ "$own" == "0" ]]; then
        echo "  [SETUP-OK] worktree branch 自有 commit = 0（tip 落後 main）"
    else
        echo "  [SETUP-WARN] 預期 0 自有 commit，實得 $own"
    fi

    local output
    output=$(run_merge_in_test_dir "$test_dir" --dry-run)

    # 1. 絕不可出現其他分支的 commit
    if echo "$output" | grep -qE "other-branch wip|bad: new silent fallback"; then
        fail "22-1: 撈進其他分支的 commit（K1262-v6 誤合風險重現）"
        echo "$output" | head -30
    else
        pass "22-1: 未撈進任何其他分支的 commit"
    fi

    # 2. 不可再宣稱從 --all 重建 commit list
    if echo "$output" | grep -q "從 git log --all 重建"; then
        fail "22-2: fallback 仍使用 git log --all（scope 未限縮）"
    else
        pass "22-2: fallback 未使用 git log --all"
    fi

    # 3. 不可宣告「會合併 N 個 commits」
    if echo "$output" | grep -qE "會合併 [1-9][0-9]* 個 commits"; then
        fail "22-3: 對 0 自有 commit 的 worktree 宣告要合併 commits"
    else
        pass "22-3: 未對 0 自有 commit 的 worktree 宣告合併"
    fi

    # 4. K1262 防線本體必須仍在：worktree 放真成果（untracked）時仍要被看見
    mkdir -p "$wt/experiments/k9999"
    echo "print('real result')" > "$wt/experiments/k9999/result.py"
    local output2
    output2=$(run_merge_in_test_dir "$test_dir" --dry-run)
    if echo "$output2" | grep -q "k9999/result.py"; then
        pass "22-4: 真成果仍被偵測到（K1262 防線未被弱化）"
    else
        fail "22-4: 真成果沒被偵測到 — K1262 silent-drop 的洞被打開了"
        echo "$output2" | head -30
    fi
}

# ============================================================
# Test Case 23 (2026-07-23): stale-base 同路徑雙邊修改不得交給 -X ours
#
# 真實事故 86e142305：merge result 相對 main parent 看似 +38/-7，但相對
# worktree parent 是 +0/-192；`git merge -X ours` 把 worktree 上已驗證的
# D6b reaper 靜默丟掉。既有 post-merge detector 只看 experiments/，因此
# scripts/compute_queue.py 完全不在保護範圍。
#
# 最小重現：branch 與 main 從同一 base 修改同一支程式的同一行。
# 正確行為是在 merge 前 fail-closed，保留 main bytes + worktree + branch，
# 要求先 rebase/人工整合；不能讓 -X ours 代替語意裁決。
# ============================================================
test_case_23_stale_overlap_aborts_before_merge() {
    echo "=== Case 23: stale-base 同路徑雙邊修改 → merge 前 ABORT ==="
    local test_dir
    test_dir=$(setup_test_env "case23")
    cd "$test_dir"

    local wt=".claude/worktrees/agent-testcase23"
    local branch="worktree-agent-testcase23"

    mkdir -p src
    printf '%s\n' "def verdict():" "    return 'base'" > src/live_worker.py
    git add src/live_worker.py && git commit -qm "seed shared live worker"
    (cd "$wt" && git merge main --no-edit -q)

    # Worktree 的有效實作。
    printf '%s\n' "def verdict():" "    return 'agent-live-reaper'" \
        > "$wt/src/live_worker.py"
    (cd "$wt" && git add src/live_worker.py && git commit -qm "agent: add live reaper")

    # Worktree 分出後 main 也改同一路徑；-X ours 會偏向這份 bytes。
    printf '%s\n' "def verdict():" "    return 'main-concurrent-change'" \
        > src/live_worker.py
    git add src/live_worker.py && git commit -qm "main: concurrent live worker change"

    local output rc
    output=$(run_merge_capture_rc "$test_dir")
    rc=$(last_merge_rc)

    if [[ "$rc" != "0" ]] && [[ "$rc" != "NORC" ]] && \
       echo "$output" | grep -q "STALE-BASE.*ABORT"; then
        pass "23-1: stale overlap 在 merge 前 fail-closed"
    else
        fail "23-1: stale overlap 未被擋下（rc=${rc}；-X ours 可靜默丟 worktree 活碼）"
        echo "$output" | tail -40
    fi

    if [[ "$(cat src/live_worker.py)" == *"main-concurrent-change"* ]] && \
       ! git -C "$test_dir" merge-base --is-ancestor "$branch" main 2>/dev/null; then
        pass "23-2: main bytes 未被改寫，branch 未假裝 merged"
    else
        fail "23-2: main 或 branch ancestry 已被 merge 污染"
    fi

    if [[ -d "$wt" ]] && \
       [[ "$(cat "$wt/src/live_worker.py")" == *"agent-live-reaper"* ]]; then
        pass "23-3: worktree 與 agent 活碼完整保留"
    else
        fail "23-3: worktree/agent 活碼被移除或改寫"
    fi

    if echo "$output" | grep -q "src/live_worker.py"; then
        pass "23-4: ABORT 證據列出重疊路徑"
    else
        fail "23-4: 訊息沒有列出需人工整合的路徑"
    fi
}

# Targeted feedback loop for the stale-base regression.  The full historical
# suite intentionally remains the default; this selector keeps Case 23 usable
# while unrelated baseline debt is being repaired under a separate task.
if [[ "${MERGE_TEST_ONLY:-}" == "23" ]]; then
    test_case_23_stale_overlap_aborts_before_merge
    echo "================================"
    echo "Assertions PASS: $PASS"
    echo "Assertions FAIL: $FAIL"
    echo "Test cases: $([[ $FAIL -eq 0 ]] && echo 'PASS 1/1' || echo 'FAIL — see assertion failures above')"
    echo "================================"
    [[ $FAIL -eq 0 ]]
    exit $?
fi


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
test_case_12_real_violation_aborts_without_stash
echo ""
test_case_13_unregistered_standalone_repo_dir
echo ""

test_case_14_uncertified_experiment_blocked
echo ""
test_case_15_fail_verdict_blocked
echo ""
test_case_16_stale_pass_verdict_blocked
echo ""
test_case_17_overlapping_dirty_main_aborts_without_stash
echo ""
test_case_18_unrelated_dirty_main_merges_in_place
echo ""
test_case_19_foreign_staged_index_aborts_unchanged
echo ""
test_case_20_storage_only_work_autocommit_failed
echo ""
test_case_21_dryrun_no_contradiction
echo ""
test_case_22_stale_worktree_no_foreign_commits
echo ""
test_case_23_stale_overlap_aborts_before_merge
echo ""

echo "================================"
echo "Assertions PASS: $PASS"
echo "Assertions FAIL: $FAIL"
# Test case-level summary（23 cases；17/18/19 pin multi-slot dirty-main/index contract；
# 20/21 pin the 2026-07-19 scope fix: 安全網掃全樹、dry-run 不自相矛盾；
# 22 pins K1262-v6: 落後的 worktree 不得靠 --all fallback 撈進其他分支的 commit；
# 23 pins stale-base 同路徑雙邊修改不得交給 -X ours 語意裁決）
TOTAL_CASES=23
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
