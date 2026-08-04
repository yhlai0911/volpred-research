#!/bin/bash
# merge_worktree.sh — 安全地將 agent worktree 的變更合併回主分支
#
# 用法：
#   bash scripts/merge_worktree.sh                    # 合併所有 agent worktrees
#   bash scripts/merge_worktree.sh agent-abc123       # 只合併指定的 worktree
#   bash scripts/merge_worktree.sh --dry-run          # 只檢查，不實際操作
#
# 流程：
#   1. 確認 agent worktree 有 commits（沒有則先自動 commit）
#   2. Cherry-pick agent commits 到 main
#   3. 確認成功後才移除 worktree
#
# 絕對不會 --force remove 有未合併變更的 worktree

set -euo pipefail

# 防護：若 cwd 已失效（前次 worktree 被 force-rm 後 cwd 殘留），切回 HOME
pwd >/dev/null 2>&1 || cd "$HOME"

SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"

# ── K1618 (2026-07-04) STRIKE-2 FIX：robust MAIN_DIR 解析（cwd-agnostic）─────
# 根因：若 caller 的 shell cwd 停在被合併的 worktree 內（Bash 工具 cwd 跨呼叫持久），
# 舊版用 BASH_SOURCE-相對路徑解析 MAIN_DIR → 指到 **worktree root** 而非主 repo。
# 於是 main_branch = worktree 自己的分支 → `main_branch..branch` 拿自己比自己 = 0 commits
# false-negative → 5 層防禦全被繞過（FS-defense 也因 MAIN_DIR==wt_path 失效）→ 走
# destructive「可安全移除」→ 未 merge 就砍 worktree（K1618 靠 branch 存活才救回）。
# 正解：`git rev-parse --git-common-dir` 從任何 cwd（含 linked worktree 內）都回傳
# **主 repo 的 .git**；其 parent 即真 main root。主 repo 的 .git 是「目錄」，
# linked worktree 的 .git 是「檔案」→ 用 `-d "$root/.git"` 可靠區分、拒絕誤指 worktree。
# K1618 review Finding 1 (2026-07-04)：anchor 到 **腳本實體所在目錄**，不用裸 cwd。
# 否則從別的 git repo 用絕對路徑呼叫本腳本時，`git rev-parse --git-common-dir` 會依 cwd
# 解析成那個 repo（fail-open，可能對錯 repo 跑 destructive remove）。腳本屬於特定 repo，
# 故用 `git -C "$script_dir"`：K1618 相對路徑情境下 script_dir 在 worktree/scripts，但
# worktree 屬本 repo → git-common-dir 照樣回主 repo 的 .git；絕對路徑呼叫更是直接命中本 repo。
resolve_main_dir() {
    local script_dir common_dir root
    script_dir="$(cd "$(dirname "$SCRIPT_PATH")" 2>/dev/null && pwd)" || script_dir=""
    if [[ -z "$script_dir" ]]; then
        return 1  # 無法定位腳本目錄（BASH_SOURCE 空 + cwd 失效）→ fail-closed
    fi
    if common_dir=$(git -C "$script_dir" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) \
        && [[ -n "$common_dir" ]] && [[ -d "$common_dir" ]]; then
        root="$(cd "$(dirname "$common_dir")" 2>/dev/null && pwd)" || root=""
        if [[ -n "$root" ]] && [[ -d "$root/.git" ]]; then
            printf '%s' "$root"
            return 0
        fi
    fi
    # Fallback：script_dir 的 parent，但**只在** .git 是真目錄（非 worktree）時才信任
    root="$(cd "$script_dir/.." 2>/dev/null && pwd)" || root=""
    if [[ -n "$root" ]] && [[ -d "$root/.git" ]]; then
        printf '%s' "$root"
        return 0
    fi
    return 1
}

MAIN_DIR="$(resolve_main_dir)" || {
    echo "[FATAL] 無法可靠解析主 repo 根目錄（cwd 可能停在已失效或 linked worktree 內）。"
    echo "        請先 cd 到主 repo 根目錄（非 worktree）再重跑。"
    exit 1
}
# 立刻 cd 到真 main root：確保後續所有動作（尤其 git worktree remove）永不從
# 待移除的 worktree 內執行（cwd 失效會連鎖污染 git 指令 → K1618 root cause）。
cd "$MAIN_DIR" || { echo "[FATAL] 無法 cd 至 MAIN_DIR=$MAIN_DIR"; exit 1; }

# Sanity：所有 non-dry main mutation 都只准 canonical symbolic main。
_mdir_head="$(git -C "$MAIN_DIR" rev-parse --abbrev-ref HEAD 2>/dev/null || echo UNKNOWN)"
if [[ "$_mdir_head" != "main" ]]; then
    echo "[FATAL] MAIN_DIR=$MAIN_DIR 的 HEAD=$_mdir_head，不是 canonical main —"
    echo "        拒絕在 side/detached HEAD 執行 shared-checkout transaction。"
    exit 1
fi

# K1618 (2026-07-04): 破壞性移除前確認 shell cwd 不在待移除 worktree 內（defense-in-depth）。
ensure_cwd_outside_worktree() {
    local wt="$1"
    local cur="$PWD"
    if [[ "$wt" == "$MAIN_DIR" ]]; then
        echo "  [ABORT] 拒絕移除 MAIN_DIR 本身（$wt）"
        return 1
    fi
    if [[ "$cur" == "$wt" || "$cur" == "$wt"/* ]]; then
        echo "  [FIX] 當前 cwd 在待移除 worktree 內（$cur）→ 先 cd 回 $MAIN_DIR"
        cd "$MAIN_DIR" || { echo "  [ABORT] 無法 cd 回 MAIN_DIR，拒絕移除以防 cwd 失效"; return 1; }
    fi
    return 0
}

# ── 2026-07-19 SCOPE FIX：安全網從「只看 experiments/」擴到全樹 ─────────────
# 舊版 K1262-v4 PRIMARY（file-presence diff）與 K1143-v2（pre-remove 掃描）兩層防線
# 都硬編 `experiments/`。但 agent 成果早就不只放那裡（storage/event_articles/、
# storage/drafts/、docs/ 都有）。於是這條失效路徑一直開著：成果全在 storage/ →
# auto-commit 沒抓到（被 ignore 規則蓋掉、或根本沒觸發）→ rev-list=0 且 experiments/
# 是空的 → 直接走「可安全移除」→ 未合併就砍 worktree。
# 防線宣稱擋 silent data loss，實際覆蓋卻比宣稱窄；這裡把兩層都改成掃全樹。
#
# 取捨：為什麼**不**拿 `.gitignore` 當邊界
#   K1143-v2 自己的註解就把「gitignore 吃掉檔案」列為必須 ABORT 的成因之一——被 ignore
#   規則蓋到的 agent 產出，正是最容易靜默消失、最需要這條防線的那一種。若把邊界委派給
#   git 的 ignore 判斷（--exclude-standard / check-ignore），防線就會對它最該擋的情況失明。
#   代價是全樹掃描會看到機器產生的噪音。因此改用下面這份**結構性噪音 denylist**：只列
#   「機器產生、不帶 agent 語意」的路徑（快取 / venv / build 產物 / log），其餘一律視為
#   可能的成果。寧可偶爾多一次 fail-closed 的 ABORT，也不要少一次 silent 砍檔。
#
# ── K1262-v6 (2026-07-21)：辨識「main 自己刪掉／搬走的舊檔」，避免落後的 worktree 誤報 ──
# 判準刻意開得極窄：**同一路徑**在 main 的歷史裡曾存在**位元組完全相同**的版本。
# 滿足這條的檔案不可能是 agent 的新成果（新成果不會與 main 舊版本 byte-identical），
# 但足以吃掉 stale worktree（tip 落後 main）必然產生的那類噪音：被搬進 scripts/_legacy/ 的
# 腳本、被輪替刪掉的 runtime JSON、被移除的 local 設定 —— 這些正是本次誤判的三個檔。
# 為什麼不用路徑 denylist：denylist 只能擋「這次剛好誤報的這幾個檔」，且一旦寫寬
# （例如整個 storage/ 或所有 gitignored 檔）就會重新打開 K1262 silent-drop 的洞。
# 內容比對是內容層判準，不需要預測未來的成果路徑。
# 擋：把 main 自己刪掉的舊檔當成 worktree 未合併成果 → 假 ABORT／假 merge 觸發。
is_stale_main_deleted_file() {
    local wf="$1" rel="$2" blob c
    blob=$(git -C "$MAIN_DIR" hash-object -- "$wf" 2>/dev/null) || return 1
    [[ -z "$blob" ]] && return 1
    while IFS= read -r c; do
        [[ -z "$c" ]] && continue
        if [[ "$(git -C "$MAIN_DIR" rev-parse -q --verify "$c:$rel" 2>/dev/null)" == "$blob" ]]; then
            return 0
        fi
    done < <(git -C "$MAIN_DIR" log --format=%H -n 200 -- "$rel" 2>/dev/null)
    return 1
}

# 輸出：worktree 內存在、但 MAIN_DIR 對應路徑不存在的檔案（相對路徑，一行一個）。
worktree_only_paths() {
    local wt_path="$1"
    find "$wt_path" \
        \( -name '.git' -o -name '__pycache__' -o -name '.venv' -o -name 'venv' \
           -o -name 'node_modules' -o -name '.next' -o -name '.pytest_cache' \
           -o -name '.mypy_cache' -o -name '.ruff_cache' -o -name '.eggs' \
           -o -name 'dist' -o -name 'build' -o -name '*.egg-info' \
           -o -name '.claude' -o -path "$wt_path/storage/logs" \) -prune -o \
        -type f -not -name '*.pyc' -not -name '*.pyo' -not -name '.DS_Store' -print0 2>/dev/null \
    | while IFS= read -r -d '' wf; do
        local rel="${wf#$wt_path/}"
        [[ -z "$rel" ]] && continue
        if [[ ! -e "$MAIN_DIR/$rel" ]]; then
            # K1262-v6：main 歷史裡有同路徑、同內容的版本 → 是 main 刪掉/搬走的舊檔，非成果
            if is_stale_main_deleted_file "$wf" "$rel"; then
                continue
            fi
            printf '%s\n' "$rel"
        fi
    done
}
# ──────────────────────────────────────────────────────────────────────────

DRY_RUN=false
TARGET=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) TARGET="$(basename "$arg")" ;;  # 只取 basename，確保匹配一致
    esac
done

# Every non-dry integration is one Git transaction: worktree auto-commit,
# main-checkout ownership/stash, cherry-pick/merge, verification, and stash
# restoration must not be interleaved with another writer.  The Python owner
# derives its sentinel from git-common-dir, so this also serialises linked
# worktrees.  Descendants inherit a validated lease token and do not recurse.
if ! $DRY_RUN; then
    if ! /usr/bin/python3 "$MAIN_DIR/scripts/git_writer_lock.py" \
        validate-inherited --repo "$MAIN_DIR" --actor "merge-worktree-child" \
        >/dev/null 2>&1; then
        exec /usr/bin/python3 "$MAIN_DIR/scripts/git_writer_lock.py" run \
            --repo "$MAIN_DIR" \
            --actor "merge-worktree:${TARGET:-all}" \
            --timeout 300 \
            -- /bin/bash "$SCRIPT_PATH" "$@"
    fi
fi

echo "=== Worktree Merge Tool ==="
echo ""

# 獲取所有 agent worktrees
get_agent_worktrees() {
    git worktree list --porcelain | while IFS= read -r line; do
        if [[ "$line" == worktree* ]] && [[ "$line" == *".claude/worktrees/"* ]]; then
            echo "${line#worktree }"
        fi
    done
}

merge_one_worktree() {
    local wt_path="$1"
    local wt_name=$(basename "$wt_path")

    # 如果指定了 target，只處理匹配的（雙向包含匹配）
    if [[ -n "$TARGET" ]] && [[ "$wt_name" != *"$TARGET"* ]] && [[ "$TARGET" != *"$wt_name"* ]]; then
        return 0
    fi

    echo "--- Processing: $wt_name ---"

    # 獲取分支名稱
    local branch
    branch=$(git worktree list --porcelain | grep -A2 "^worktree $wt_path$" | grep "^branch" | sed 's|^branch refs/heads/||' || true)

    if [[ -z "$branch" ]]; then
        echo "  [WARN] 無法確定分支名稱，跳過"
        return 0
    fi

    echo "  Branch: $branch"

    # 檢查 worktree 是否有未提交的變更
    # K1143-v2 (2026-04-19): status 失敗必須 ABORT 不能 silent skip，
    # 否則 has_uncommitted=false + rev-list=0 會進入 line 123 "no commits" path
    # 觸發 remove --force，靜默吃掉工作目錄 (K903/K904/K1032/K1114/K1100g_d9)
    local has_uncommitted=false
    if [[ ! -d "$wt_path" ]]; then
        echo "  [ABORT] worktree 目錄不存在: $wt_path"
        return 1
    fi

    local status
    local status_rc=0
    status=$(cd "$wt_path" && git status --porcelain 2>&1) || status_rc=$?
    if [[ $status_rc -ne 0 ]]; then
        echo "  [ABORT] git status 在 worktree 內失敗 (rc=$status_rc)；拒絕繼續以防 silent data loss"
        echo "         output: $status"
        return 1
    fi
    if [[ -n "$status" ]]; then
        has_uncommitted=true
        echo "  [!] 有未提交的變更："
        echo "$status" | head -10 | sed 's/^/      /'
        local total=$(echo "$status" | wc -l | tr -d ' ')
        if [[ $total -gt 10 ]]; then
            echo "      ... 共 $total 個檔案"
        fi
    fi

    # 如果有未提交變更，自動 commit
    # K1143-v2: commit 後要驗證真的產生了新 commit（branch HEAD 前進），否則 abort
    if $has_uncommitted; then
        echo "  [ACTION] 自動提交未保存的變更..."
        if ! $DRY_RUN; then
            local head_before_commit head_after_commit
            head_before_commit=$(cd "$wt_path" && git rev-parse HEAD 2>/dev/null || echo "NONE")
            (cd "$wt_path" && git add -A && git commit -m "Auto-commit: save agent work before worktree merge

Files saved from worktree $wt_name to prevent data loss.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>") || {
                echo "  [ERROR] 自動提交失敗（git add -A 或 git commit 出錯）"
                return 1
            }
            head_after_commit=$(cd "$wt_path" && git rev-parse HEAD 2>/dev/null || echo "NONE")
            if [[ "$head_before_commit" == "$head_after_commit" ]]; then
                echo "  [ABORT] auto-commit 聲稱成功但 HEAD 未前進 ($head_before_commit)；可能 detached 或其他異常"
                return 1
            fi
            echo "  [OK] auto-commit: $head_before_commit → $head_after_commit"
        else
            echo "  [DRY-RUN] 會自動提交"
        fi
    fi

    # 找出 worktree 分支上的新 commits（相對於 main）
    # K1262-v4 (2026-04-27): 所有 ref 比較**強制** `git -C "$MAIN_DIR"` —
    # 過去用 cwd-relative `git log` / `git rev-list` 在某些 path 下會把
    # working-tree HEAD 解錯，產生 rev-list=0 false negative。
    # 詳：docs/error_log.md 2026-04-27 K1262 entry。
    local main_branch
    main_branch=$(git -C "$MAIN_DIR" rev-parse --abbrev-ref HEAD)

    # K1618 (2026-07-04): 若 main_branch == worktree branch，代表 MAIN_DIR 解析異常把
    # worktree 自己的分支當成主分支 → `main_branch..branch` 自比自 = 0-commit false-negative
    # （K1618 STRIKE-2 的直接症狀）。targeted guard：即便前段解析回歸也擋住自我比較。
    if [[ "$main_branch" == "$branch" ]]; then
        echo "  [ABORT] main_branch($main_branch) == worktree branch — 解析異常，"
        echo "         拒絕繼續以防自我比較 0-commit false-negative（K1618 STRIKE-2）"
        return 1
    fi

    # K1618 (2026-07-04) no-silent-fallback：git log 失敗必 fail-loud ABORT，不可把
    # 「git 錯誤回空」silently 當成「0 commits」（rc=0 空輸出=合法無 commit；rc≠0=git 錯誤）。
    local new_commits new_commits_rc=0
    new_commits=$(git -C "$MAIN_DIR" log --oneline "$main_branch..$branch" 2>&1) || new_commits_rc=$?
    if [[ $new_commits_rc -ne 0 ]]; then
        echo "  [ABORT] git log $main_branch..$branch 失敗 (rc=$new_commits_rc)；拒絕繼續以防 silent data loss"
        echo "         output: $new_commits"
        return 1
    fi

    # 雙重驗證：rev-list --count 防止 git log 靜默失敗（K1032/K1114/E067 教訓）
    local commit_count_verify
    commit_count_verify=$(git -C "$MAIN_DIR" rev-list --count "$main_branch..$branch" 2>/dev/null || echo "ERROR")

    if [[ "$commit_count_verify" == "ERROR" ]]; then
        echo "  [ABORT] git rev-list 失敗，無法確認 commit 狀態。手動處理。"
        return 1
    fi

    # 2026-07-23 stale-base overlap guard (86e142305 / D6b reaper incident).
    #
    # `git merge -X ours` only chooses our side for conflicting hunks; it does
    # not prove that the agent's semantic change survived.  In 86e142305 both
    # main and the worktree changed scripts/compute_queue.py after their common
    # base.  The merge looked small relative to main (+38/-7), but relative to
    # the worktree parent it was +0/-192: the verified D6b reaper disappeared.
    # The old post-merge detector only inspected experiments/, so code under
    # scripts/ had no protection.
    #
    # A worktree being behind main is normal in a busy repo.  The dangerous
    # state is narrower and deterministic: main advanced *and* both sides
    # touched the same path.  Disjoint stale worktrees remain mergeable (Case
    # 11: cron updates feed.json while an agent only adds its experiment).
    # Overlap requires an explicit rebase/manual integration before this
    # script may merge; `-X ours` must never make that semantic decision.
    local stale_merge_base=""
    local main_ahead_count=0
    local main_since_base_paths=""
    local branch_since_base_paths=""
    local stale_overlap_paths=""
    local branch_pure_deletion_paths=""

    if ! stale_merge_base=$(git -C "$MAIN_DIR" merge-base "$main_branch" "$branch" 2>/dev/null) \
        || [[ -z "$stale_merge_base" ]]; then
        echo "  [STALE-BASE ABORT] 無法解析 $main_branch 與 $branch 的 merge-base；拒絕盲目合併"
        return 1
    fi
    if ! main_ahead_count=$(git -C "$MAIN_DIR" rev-list --count "$stale_merge_base..$main_branch" 2>/dev/null); then
        echo "  [STALE-BASE ABORT] 無法計算 main 相對 worktree base 的前進量"
        return 1
    fi

    if [[ "$commit_count_verify" -gt 0 ]]; then
        branch_pure_deletion_paths=$(
            git -C "$MAIN_DIR" diff --numstat "$stale_merge_base" "$branch" 2>/dev/null \
                | awk -F '\t' '$1 == "0" && $2 ~ /^[0-9]+$/ && $2 > 0 {print $3}' \
                | sort -u || true
        )
        if [[ -n "$branch_pure_deletion_paths" ]]; then
            echo "  [PURE-DELETION WARN] worktree 相對 merge-base 有只刪不增的路徑："
            printf '%s\n' "$branch_pure_deletion_paths" | sed -n '1,20{s/^/      /;p;}'
            echo "  [PURE-DELETION WARN] 若非明確刪除任務，rebase 前先核對是否把活碼覆成舊版。"
        fi
    fi

    if [[ "$main_ahead_count" -gt 0 ]] && [[ "$commit_count_verify" -gt 0 ]]; then
        if ! main_since_base_paths=$(git -C "$MAIN_DIR" diff --name-only \
            "$stale_merge_base" "$main_branch"); then
            echo "  [STALE-BASE ABORT] 無法列出 main 自 merge-base 後的變更路徑"
            return 1
        fi
        if ! branch_since_base_paths=$(git -C "$MAIN_DIR" diff --name-only \
            "$stale_merge_base" "$branch"); then
            echo "  [STALE-BASE ABORT] 無法列出 worktree 自 merge-base 後的變更路徑"
            return 1
        fi
        stale_overlap_paths=$(comm -12 \
            <(printf '%s\n' "$main_since_base_paths" | sed '/^$/d' | sort -u) \
            <(printf '%s\n' "$branch_since_base_paths" | sed '/^$/d' | sort -u))

        if [[ -n "$stale_overlap_paths" ]]; then
            echo "  [STALE-BASE ABORT] worktree base 落後 main $main_ahead_count commits，且雙方修改同一路徑："
            printf '%s\n' "$stale_overlap_paths" | sed -n '1,20{s/^/      /;p;}'
            echo "  [WHY] 禁止交給 -X ours 靜默裁決；86e142305 曾因此相對 worktree parent 產生 +0/-192。"
            echo "  [HINT] 在 worktree 明確整合 main、解衝突並重跑驗證後再合併："
            echo "         git -C \"$wt_path\" rebase \"$main_branch\""
            echo "         # 解衝突、重跑該任務測試並 commit，再執行："
            echo "         bash scripts/merge_worktree.sh $wt_name"
            return 1
        fi
        echo "  [STALE-BASE SAFE] worktree base 落後 main $main_ahead_count commits，但變更路徑不相交，允許繼續。"
    fi

    # K1262-v4 (2026-04-27): **PRIMARY 防線** — file-presence diff 不依賴 rev-list count。
    # 即使 rev-list 報 0（false negative，K1032/K1114/K1262 same root cause），
    # 只要 worktree branch tip 含 main 沒有的檔，就強制走 merge path。
    # 這條 layer 在 K1262 silent drop bug 第三次重現後新增。
    # 2026-07-19 scope fix：拿掉 `-- experiments/` pathspec，改比對**全樹**。
    # 這是 commit-to-commit 的 tree diff，只看已提交的 tracked 檔，沒有 untracked 噪音問題，
    # 所以全樹是純粹的擴大覆蓋——不必再追著每個新的成果路徑（storage/、docs/…）補 pathspec。
    #
    # K1262-v6 (2026-07-21): diff-tree 訊號在 branch 是 main 祖先時**方向相反**，先擋掉。
    # `diff-tree A "$main_branch" "$branch"` 問的是「從 main 走到 branch 會新增哪些檔」。
    # 當 branch 完全落後（tip 已被 main 包含、0 自有 commit）時，這個集合等於
    # **main 後來刪掉／搬走的舊檔**（例：搬進 scripts/_legacy/、輪替掉的 runtime JSON、
    # 被移除的 .claude/settings.local.json），不是 branch 的成果。舊版拿它當
    # 「rev-list false negative」的證據 → 觸發 commit 來源 fallback → 誤判。
    # 擋：把 0 自有 commit 的 worktree 誤判成有未合併成果、進而誤合他人工作。
    # 為什麼安全（不弱化 K1262）：ancestor 成立 = branch tip 的整棵 tree 都已在 main 的
    # 歷史裡，定義上不存在「只在 branch 有的已提交成果」。真正的 K1262 silent-drop 情境
    # （有 commit 但 rev-list 誤報 0、或成果是 untracked/gitignored）都**不**滿足 ancestor：
    # 前者 branch tip 不是 main 祖先，後者走下面 K1262-v5 的 filesystem 防線，兩條都不受影響。
    local branch_is_ancestor=false
    if git -C "$MAIN_DIR" merge-base --is-ancestor "$branch" "$main_branch" 2>/dev/null; then
        branch_is_ancestor=true
    fi

    # K1262-v6: fallback 觸發但無法在 branch 範圍內解釋時的 fail-closed 旗標（見下方 gate）
    local fallback_unresolved=false

    local file_presence_unique=""
    if $branch_is_ancestor; then
        echo "  [K1262-v6] $branch 是 $main_branch 的祖先（tree 已完全含於 main 歷史）→"
        echo "             略過 commit-to-commit file-presence 訊號（該方向只會列出 main 自己刪掉的舊檔）。"
        echo "             下面的 K1262-v5 filesystem 防線與 pre-remove 全樹掃描**照常**執行。"
    else
        file_presence_unique=$(git -C "$MAIN_DIR" diff-tree --diff-filter=A --name-only -r "$main_branch" "$branch" 2>/dev/null | grep -v '^$' || true)
    fi
    # 過濾出真正只在 worktree branch 有的（main HEAD 不存在）
    local worktree_only_files=""
    if [[ -n "$file_presence_unique" ]]; then
        while IFS= read -r f; do
            [[ -z "$f" ]] && continue
            if ! git -C "$MAIN_DIR" cat-file -e "$main_branch:$f" 2>/dev/null; then
                worktree_only_files="$worktree_only_files$f"$'\n'
            fi
        done <<< "$file_presence_unique"
    fi

    # K1262-v5 (2026-04-27) EXTRA-DEFENSE: 若 git diff-tree 回空但 worktree 有實際檔案 not in
    # MAIN_DIR，純文件系統 fallback。處理 git plumbing 全 silent fail 的 K1262-actual case
    # (rev-list=0, log=empty, diff-tree=empty, 但檔案實在 worktree 裡)。
    # 2026-07-19 scope fix：從 `find "$wt_path/experiments"` 改成 worktree_only_paths()
    # 全樹掃描（見檔案上方該函式的取捨註解）。舊版只要成果不在 experiments/ 就完全看不到。
    if [[ -z "$worktree_only_files" ]] && [[ -d "$wt_path" ]]; then
        local fs_only_files=""
        fs_only_files=$(worktree_only_paths "$wt_path")
        if [[ -n "$fs_only_files" ]]; then
            echo "  [🚨 K1262-v5 FS-DEFENSE] git plumbing 全空但 filesystem 顯示 worktree 有 main 沒有的檔案"
            worktree_only_files="$fs_only_files"
        fi
    fi

    if [[ -z "$new_commits" ]] && [[ "$commit_count_verify" -eq 0 ]] && [[ -n "$worktree_only_files" ]]; then
        echo "  [🚨 K1262-v4 PRIMARY] rev-list 報 0 commits 但 file-presence diff 顯示 worktree 含 main 沒有的檔案："
        echo "$worktree_only_files" | head -10 | sed 's/^/      /'
        echo "  [🚨 K1262-v4] 強制走 merge path（不信 rev-list false negative）"
        # K1262-v6 (2026-07-21): 重建 commit list 的來源**限縮在這一個 branch**，永不用 `--all`。
        # 舊版 `git log --all "^$main_branch" "$branch"` 把「全 repo 所有分支」當成
        # 「這個 branch」的替身：其他 worktree 進行中的分支、測試 fixture commit 全會被撈進來
        # cherry-pick 進 main。偵測層的方向沒錯，錯的是 fallback 的 **scope**。
        # 擋：把別人未完成的工作與測試 fixture commit 誤合進 main（難回溯，比漏合更貴）。
        # 兩個 branch-scoped 來源：
        #   1) merge-base..branch —— 不受 main 前進影響，仍只看這條 branch 自己的 commit
        #   2) branch 自己的 reflog —— 救「ref 被覆寫/rev-list 誤報 0 但 commit 還在」的
        #      K1032/K1114 式 false negative（只取 main 尚未包含者），天然限定在本 branch
        local merge_base="" rebuilt=""
        merge_base=$(git -C "$MAIN_DIR" merge-base "$main_branch" "$branch" 2>/dev/null || true)
        if [[ -n "$merge_base" ]]; then
            rebuilt=$(git -C "$MAIN_DIR" log --oneline "$merge_base..$branch" 2>/dev/null | head -50 || true)
        fi
        if [[ -z "$rebuilt" ]]; then
            rebuilt=$(git -C "$MAIN_DIR" reflog show "$branch" --format='%H' 2>/dev/null \
                | while IFS= read -r sha; do
                    [[ -z "$sha" ]] && continue
                    if ! git -C "$MAIN_DIR" merge-base --is-ancestor "$sha" "$main_branch" 2>/dev/null; then
                        git -C "$MAIN_DIR" log --oneline -1 "$sha" 2>/dev/null || true
                    fi
                  done | awk '!seen[$0]++' | head -50 || true)
            [[ -n "$rebuilt" ]] && echo "  [K1262-v6] merge-base..$branch 為空，改用 $branch 自己的 reflog（仍限本 branch）"
        fi
        if [[ -z "$rebuilt" ]]; then
            # K1262-v6 fail-closed：branch 歷史裡找不到對應 commit 時**不再自動擴大範圍**。
            # 兩種錯誤方向不對稱：漏合 branch 還在、可救回；誤合污染 main、難回溯。
            # 所以這裡標記待人工確認，讓流程走到下面的 pre-remove 掃描 / v6 fail-closed gate，
            # 絕不因為「找不到就換更大的來源」而自動放行。
            fallback_unresolved=true
            echo "  [K1262-v6] branch-scoped 來源（merge-base / reflog）皆無 commit → 不擴大範圍，改要求人工確認"
        else
            new_commits="$rebuilt"
            commit_count_verify=$(printf '%s\n' "$new_commits" | grep -c '^' || echo 0)
            echo "  [K1262-v6] 從 branch-scoped 來源重建 commit list: $commit_count_verify commits"
        fi
    fi

    if [[ -z "$new_commits" ]] && [[ "$commit_count_verify" -eq 0 ]]; then
        # K1143-v2 (2026-04-19): rev-list=0 不代表工作目錄也空。
        # Auto-commit 失敗、detached HEAD、gitignore 吃掉檔案 → rev-list=0 但
        # wt_path 底下仍有 experiments/<kXXX> 是**主目錄沒有的**。舊版在這裡執行
        # `git worktree remove --force` 直接刪除整個目錄，是 K903/K904/K1032/K1114/K1100g_d9
        # silent loss 的真正 smoking gun。
        #
        # 2026-07-19 DRY-RUN 自相矛盾修正：
        # dry-run 不真的 auto-commit，所以 rev-list 必然還是 0。舊版於是同時印出
        # 「[DRY-RUN] 會自動提交」與「[OK] …可安全移除」兩句互相打臉的結論，讓人以為
        # worktree 是空的、可以放心砍。正解是**先模擬 auto-commit 之後的狀態再下結論**：
        # 既然實跑時那些未提交變更會先變成 commit，dry-run 就不該宣告「無變更可移除」。
        if $DRY_RUN && $has_uncommitted; then
            echo "  [DRY-RUN] rev-list=0 只是因為 dry-run 沒有真的 auto-commit。"
            echo "  [DRY-RUN] 實跑時上面列出的未提交變更會先被 commit → $main_branch..$branch 會有新 commits 要合併。"
            # 措辭刻意避開「可安全移除」這串字：那是 no-op 路徑的結論標記，
            # 出現在 dry-run 輸出裡就是誤導（也會讓守這條的測試失去意義）。
            echo "  [DRY-RUN] 結論：這個 worktree **有**待合併的成果，不是空的；實跑會走合併流程而非移除。"
            echo ""
            return 0
        fi

        # 防禦：pre-remove 掃 worktree 全樹，凡是主目錄沒有的檔就 abort。
        # 2026-07-19 scope fix：舊版只 for-loop `$wt_path/experiments/*/`，成果放在
        # storage/event_articles/、storage/drafts/、docs/ 時完全掃不到 → 直接走「可安全移除」。
        # 改用 worktree_only_paths()（全樹，結構性噪音 denylist；取捨見該函式註解）。
        # 附帶效果：舊版對「主目錄已有同名資料夾」還要另跑 diff -rq 比 worktree-only 檔，
        # 現在逐檔比對天然涵蓋這件事，那段特例邏輯（含它自己的 trailing-slash bug）可以退場。
        local orphan_paths=""
        orphan_paths=$(worktree_only_paths "$wt_path")
        if [[ -n "$orphan_paths" ]]; then
            local orphan_n
            orphan_n=$(printf '%s\n' "$orphan_paths" | grep -c '^' || echo 0)
            echo "  [🛑 ABORT] rev-list=0 但 worktree 有主目錄沒有的檔案（auto-commit 漏掉或被 ignore 規則蓋掉）：共 $orphan_n 個"
            printf '%s\n' "$orphan_paths" | head -20 | sed 's/^/      /'
            if [[ "$orphan_n" -gt 20 ]]; then
                echo "      ... 還有 $((orphan_n - 20)) 個"
            fi
            echo "  [🛑 ABORT] 拒絕 remove 以防 silent data loss"
            echo "  [HINT] 手動處理建議："
            echo "         1. cd $wt_path && git status --ignored && ls -la"
            echo "         2. 確認上列檔案是否為成果；是的話手動 copy 到主目錄對應路徑"
            echo "         3. 主目錄 git add + commit 後再跑 bash scripts/merge_worktree.sh $wt_name"
            echo "         4. 若確認全是可丟棄的產物，先在 worktree 內刪掉再重跑本腳本"
            return 1
        fi

        # K1262-v6 (2026-07-21) FAIL-CLOSED GATE：file-presence/FS 防線曾示警，但 branch 自己的
        # 歷史裡找不到對應 commit，且上面的全樹掃描也沒留下 orphan 檔 —— 狀態自相矛盾。
        # 舊版此時會自動把來源換成 `--all` 放行；新版停下來要人看一眼，絕不自動擴大範圍。
        # 擋：在證據不一致時仍走「可安全移除」或誤合他人 commit。
        if $fallback_unresolved; then
            echo "  [🛑 K1262-v6 ABORT] 偵測層示警（worktree 有 main 沒有的檔）但 $branch 的歷史"
            echo "         （merge-base..$branch 與其 reflog）找不到任何對應 commit —— 證據不一致。"
            echo "  [🛑 K1262-v6] 拒絕自動判定（既不移除、也不擴大 commit 來源），請人工確認："
            echo "         1. cd $wt_path && git status --ignored && git log --oneline -10"
            echo "         2. 確認成果後手動 copy 到主目錄對應路徑並 commit，再重跑本腳本"
            echo "         3. 若確認全是可丟棄的產物，先在 worktree 內刪掉再重跑本腳本"
            return 1
        fi

        echo "  [OK] 沒有新的 commits（雙重確認 rev-list=0）+ 全樹無 worktree-only 檔案，可安全移除"
        if ! $DRY_RUN; then
            # K1618 (2026-07-04): 移除前確認 cwd 不在待移除 worktree 內
            if ! ensure_cwd_outside_worktree "$wt_path"; then
                echo "  [ABORT] cwd guard 失敗，保留 worktree 待手動處理"
                return 1
            fi
            # K1143-v2: 禁用 --force fallback (CLAUDE.md L168 禁止)。若 remove 失敗就 abort。
            if ! git worktree remove "$wt_path" 2>&1; then
                echo "  [ABORT] git worktree remove 失敗（拒絕 --force fallback，CLAUDE.md L168 禁止）"
                echo "  [HINT] 手動檢查: ls $wt_path; git worktree list"
                echo "         若確認無遺失，再手動: git worktree remove --force $wt_path"
                return 1
            fi
            # 用 -d (lowercase) 不 -D：refuse 未合併 commit, 防止 silent data loss
            git branch -d "$branch" 2>&1 || {
                echo "  [WARN] branch -d 拒絕（branch 有未合併 commits），保留 branch 等待人工檢查"
            }
            echo "  [DONE] 已移除 worktree"
        else
            echo "  [DRY-RUN] 會移除 worktree"
        fi
        return 0
    fi

    if [[ -z "$new_commits" ]] && [[ "$commit_count_verify" -gt 0 ]]; then
        echo "  [ABORT] git log 報 0 commits 但 rev-list 報 $commit_count_verify commits。可能 K1032/K1114-style detection bug。"
        echo "         請手動執行：git log --oneline $main_branch..$branch"
        return 1
    fi

    echo "  [INFO] 發現新 commits："
    echo "$new_commits" | sed 's/^/      /'

    # --- Review-certification gate (2026-07-14) ---------------------------------
    # K1709 was FAILed by Codex and merged anyway — nothing here ever read the
    # verdict — and the nested-DM ratchet then reddened every push for three
    # dispatch hours. The merge path is where an uncertified experiment becomes
    # everyone's problem, so this is where the verdict has to be read.
    #
    # Three-dot: `main...branch` is "what the agent changed" (merge-base vs branch
    # tip). Two-dot would drag in main's own churn and block on experiments this
    # branch never touched — the L390 lesson, same trap.
    local gate_script="$MAIN_DIR/scripts/experiment_gates.py"
    local touched_experiments
    touched_experiments=$(git -C "$MAIN_DIR" diff --name-only "$main_branch...$branch" -- experiments/ 2>/dev/null \
        | awk -F/ 'NF>=2 && $1=="experiments" {print $2}' | sort -u || true)

    if [[ -n "$touched_experiments" ]]; then
        local uncertified=""
        while IFS= read -r kid; do
            [[ -n "$kid" ]] || continue
            local exp_dir="$wt_path/experiments/$kid"
            # Deleted in the branch → nothing to certify.
            [[ -d "$exp_dir" ]] || continue
            echo "  [CERT] 檢查 $kid 的審查裁決..."
            # python3 (stdlib-only), not `uv run`: this gate blocks merges, so it must
            # not inherit uv's project-resolution failure modes (no pyproject in a
            # scratch repo, uv absent from a cron PATH). A gate that cannot run is a
            # gate that abstains.
            if [[ ! -f "$gate_script" ]]; then
                echo "  [🛑 ABORT] 找不到 $gate_script — 不在沒有 gate 的情況下盲目合併實驗"
                return 1
            fi
            if ! python3 "$gate_script" certify --path "$exp_dir"; then
                uncertified="$uncertified $kid"
            fi
        done <<< "$touched_experiments"

        if [[ -n "$uncertified" ]]; then
            echo "  [🛑 ABORT] 未通過審查認證的實驗，拒絕合併：$uncertified"
            echo "  [WHY] K1709 就是被 Codex 判 FAIL 卻仍 merge 進 main，害 CI 連紅 4 次。"
            echo "        merge 的前提是「有一份 PASS 裁決，且它審的就是現在這份 bytes」。"
            echo "  [HINT] 路徑："
            echo "         1. 讓 Codex 審**凍結後**的實驗，寫 experiments/<kid>/review_verdict.json"
            echo "         2. 裁決要 pin 住 claim surface（*.py / README.md / *_results.json）的 sha256"
            echo "         3. 若審完又改了 code → 重審，不要手改裁決檔"
            echo "         4. 再跑 bash scripts/merge_worktree.sh $wt_name"
            return 1
        fi

        # --- Artifact-completeness gate (2026-07-19) ----------------------------
        # 認證 gate 問「這份實驗被審過了嗎」，這道問「它把該留的東西留下了嗎」：
        # knowledge.json 條目 + reproduce_spec.json。2026-07-19 CI 連三班紅
        # （k1732 → k1719）就是實驗進了 main、artifact 沒進，然後一筆一筆事後補。
        # 同一支腳本也跑在 .github/workflows/experiment-artifacts.yml；規則只有一份。
        local artifacts_gate="$MAIN_DIR/scripts/check_experiment_artifacts.py"
        if [[ ! -f "$artifacts_gate" ]]; then
            echo "  [🛑 ABORT] 找不到 $artifacts_gate — 不在沒有 gate 的情況下盲目合併實驗"
            return 1
        fi
        local artifact_args=()
        while IFS= read -r kid; do
            [[ -n "$kid" ]] || continue
            [[ -d "$wt_path/experiments/$kid" ]] || continue
            artifact_args+=(--path "$wt_path/experiments/$kid")
        done <<< "$touched_experiments"
        if [[ ${#artifact_args[@]} -gt 0 ]]; then
            echo "  [ARTIFACT] 檢查實驗 artifact 完整性..."
            # 同 certify gate：stdlib-only 的 python3，不用 uv —— 起不來的 gate 等於棄權。
            # --knowledge-ref HEAD（2026-08-04 k1735 教訓）：CI 驗的是 committed 狀態，
            # merge gate 若讀 working tree，未 commit 的 knowledge 條目會讓 merge 過、push 紅。
            # 兩個 gate 必須看同一份狀態。
            if ! python3 "$artifacts_gate" check --knowledge-ref HEAD "${artifact_args[@]}"; then
                echo "  [🛑 ABORT] 實驗缺 artifact，拒絕合併（上方已列出可直接執行的補救指令）"
                echo "  [WHY] 實驗進 main、knowledge/reproduce_spec 沒進 → 下一班 CI 紅，"
                echo "        而且要靠考古才知道當初跑了什麼。趁作者還在現場補最便宜。"
                return 1
            fi
        fi
    fi

    # Merge 到 main
    local commit_count
    commit_count=$(echo "$new_commits" | wc -l | tr -d ' ')

    if ! $DRY_RUN; then
        echo "  [ACTION] 合併到 $main_branch..."

        # 記錄 main 的原始位置（用於合併後驗證）
        local main_branch_orig
        main_branch_orig=$(git rev-parse HEAD)

        # 檢查 agent 是否修改了共享 JSON（違反規則的早期警告）
        # K1262-v4 (2026-04-27): git diff 用 -C "$MAIN_DIR" 強制 ref 解析在主 repo
        # 2026-05-18 K-worktree-stash-pop fix: 加 runtime/operational state 檔
        # （worktree 不該帶這些；它們是 main 上 cron/runtime 寫的 live state）
        #
        # 2026-07-10: 必須 three-dot。`main..branch`（two-dot）比的是 main tip 對 branch
        # tip —— 「兩邊差在哪」，其中包含 branch 分出去之後 main 自己改的檔。feed.json 幾乎
        # 每小時被 main 上的 cron 改一次，於是任何 base 稍舊的 worktree 都被判成「agent 動了
        # 共享 JSON」而 ABORT：這條 guard 想擋的是 agent，實際擋的是時間。`main...branch`
        # （three-dot）比的是 merge-base 對 branch tip —— 正好是「agent 改了什麼」。
        # 同檔 L443 的 experiments/ 掃描早就避開這個坑（見該處註解「會列所有差異，包含 agent
        # 從未動過但 main 領先的檔」），這裡漏掉，於是安全網變成路障。
        local shared_json_modified=false
        local shared_files=""
        for shared_f in \
            "storage/reports/feed.json" \
            "storage/memory/knowledge.json" \
            "storage/memory/thinking_journal.json" \
            "storage/memory/experiment_experiences.json" \
            "storage/.release_settings.json" \
            "storage/paper_trading.json" \
            "storage/session_state.json" \
            "storage/market_status.json" \
            "storage/ops/cron_last_run.json"; do
            if git -C "$MAIN_DIR" diff --name-only "$main_branch...$branch" -- "$shared_f" 2>/dev/null | grep -q .; then
                shared_json_modified=true
                shared_files="$shared_files $shared_f"
            fi
        done

        if $shared_json_modified; then
            echo "  [🛑 ABORT] Agent 修改了共享 JSON（違反 worktree 規則）:"
            echo "     $shared_files"
            echo "  [🛑 ABORT] -X ours 會靜默覆蓋 agent 變更；改 abort 讓你手動處理"
            echo "  [HINT] 手動路徑："
            echo "         1. 檢視 git diff $main_branch...$branch -- $shared_files"
            echo "         2. 決定把 agent 的有價值變更手動 apply 到 main（或直接 drop）"
            echo "         3. 再跑 bash scripts/merge_worktree.sh $wt_name 續做合併"
            return 1
        fi

        # Multi-slot main checkout 不屬於本次 merge transaction；其中的 WIP 可能來自
        # 另一個 slot 或互動 session。絕不 stash / reset / checkout 它。先拒絕任何
        # foreign staged state（否則 merge/fallback commit 可能把別人的 index 一起提交），
        # 再只對「agent 會碰到的同一路徑」fail-closed。互不相交的 unstaged/untracked
        # WIP 交給 Git 原生保留，讓 unrelated slot 不必為每次 integration 全面停機。
        local main_staged_paths main_unstaged_paths main_untracked_paths
        local main_dirty_paths branch_touched_paths dirty_overlap
        if ! main_staged_paths=$(git -C "$MAIN_DIR" diff --cached --name-only); then
            echo "  [ABORT] 無法讀取 main staged paths；拒絕在未知 index 狀態下合併"
            return 1
        fi
        if [[ -n "$main_staged_paths" ]]; then
            echo "  [ABORT] main index 已有 staged 內容；拒絕把其他 writer 的 index 捲入 merge commit："
            printf '%s\n' "$main_staged_paths" | sed -n '1,20{s/^/      /;p;}'
            echo "  [HINT] 等 staged 內容由原 owner commit/unstage 後再重跑；本工具不 stash、不 reset。"
            return 1
        fi
        if ! main_unstaged_paths=$(git -C "$MAIN_DIR" diff --name-only); then
            echo "  [ABORT] 無法讀取 main unstaged paths；拒絕合併"
            return 1
        fi
        if ! main_untracked_paths=$(git -C "$MAIN_DIR" ls-files --others --exclude-standard); then
            echo "  [ABORT] 無法讀取 main untracked paths；拒絕合併"
            return 1
        fi
        if ! branch_touched_paths=$(git -C "$MAIN_DIR" diff --name-only "$main_branch...$branch"); then
            echo "  [ABORT] 無法計算 agent touched paths；拒絕合併"
            return 1
        fi
        main_dirty_paths=$(printf '%s\n%s\n' "$main_unstaged_paths" "$main_untracked_paths" \
            | sed '/^$/d' | sort -u)
        dirty_overlap=$(comm -12 \
            <(printf '%s\n' "$main_dirty_paths" | sed '/^$/d' | sort -u) \
            <(printf '%s\n' "$branch_touched_paths" | sed '/^$/d' | sort -u))
        if [[ -n "$dirty_overlap" ]]; then
            echo "  [ABORT] main 未提交 WIP 與 agent 變更路徑重疊；拒絕觸碰其他 slot 的工作："
            printf '%s\n' "$dirty_overlap" | sed -n '1,20{s/^/      /;p;}'
            echo "  [HINT] 等原 owner 收尾，或由主線程人工整合；本工具不 stash、不覆寫。"
            return 1
        fi
        if [[ -n "$main_dirty_paths" ]]; then
            echo "  [PREP] main 有不相交的未提交 WIP；原地保留，不 stash："
            printf '%s\n' "$main_dirty_paths" | sed -n '1,20{s/^/      /;p;}'
        fi

        # 用 -X ours 自動解決衝突：新檔案照常加入，衝突部分保留 main 版本
        # Agent 不應修改共享狀態（knowledge.json、feed.json 等）
        local merge_ok=false
        if git merge "$branch" -X ours --no-edit -m "Merge agent worktree $wt_name ($commit_count commits)

Merged from worktree branch $branch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>" 2>&1; then
            merge_ok=true
            echo "  [OK] 合併成功"
        else
            echo "  [ERROR] 合併失敗（即使 -X ours 也無法解決）"
            git merge --abort 2>/dev/null || true

            # 最後手段：只複製 agent **新增**（--diff-filter=A）的 experiments/ 檔案
            # 不用 diff --name-only（會列所有差異，包含 agent 從未動過但 main 領先的檔，
            # 會導致 worktree 舊版覆蓋 main 新版 — 2026-04-18 agent-a7aac49d 教訓）
            echo "  [FALLBACK] 只複製 agent 新增的 experiments/ 檔案..."
            # K1262-v4: 強制 git -C "$MAIN_DIR"，不再 cd 進 wt_path（過去 cwd-shift 是 silent drop 根因）
            local exp_files
            exp_files=$(git -C "$MAIN_DIR" log --diff-filter=A --name-only --pretty=format: "$main_branch..$branch" -- experiments/ 2>/dev/null | grep -v '^$' | sort -u || true)
            if [[ -n "$exp_files" ]]; then
                local copy_count=0
                echo "$exp_files" | while IFS= read -r f; do
                    if [[ -f "$wt_path/$f" ]] && [[ ! -f "$MAIN_DIR/$f" ]]; then
                        mkdir -p "$MAIN_DIR/$(dirname "$f")"
                        cp "$wt_path/$f" "$MAIN_DIR/$f"
                        echo "      Copied NEW: $f"
                        copy_count=$((copy_count + 1))
                    elif [[ -f "$wt_path/$f" ]] && [[ -f "$MAIN_DIR/$f" ]]; then
                        echo "      SKIP (main 已有同名檔，不覆蓋): $f"
                    fi
                done
                # 只 add 新複製的檔，不是整個 experiments/（避免把主目錄 untracked 也一併 commit）
                if [[ -n "$exp_files" ]]; then
                    echo "$exp_files" | xargs -I{} git add "{}" 2>/dev/null || true
                fi
                git commit -m "Copy new experiments from worktree $wt_name (fallback, new files only)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>" 2>/dev/null && merge_ok=true
                if $merge_ok; then
                    echo "  [OK] fallback 複製成功（只複製新增檔案）"
                else
                    echo "  [WARN] fallback commit 失敗（可能沒有新檔要 commit）"
                fi
            else
                echo "  [INFO] agent 沒有新增檔案，nothing to fallback"
            fi
        fi

        # 合併後驗證：確認 agent 的 experiments/ 檔案全部到位
        # K1262-v4 (2026-04-27): 所有 git log/diff 強制 git -C "$MAIN_DIR"
        if $merge_ok; then
            echo "  [VERIFY] 檢查 experiments/ 檔案完整性..."
            local missing_files=0
            local agent_exp_files
            agent_exp_files=$(git -C "$MAIN_DIR" log --diff-filter=A --name-only --pretty=format: "$main_branch_orig..$branch" -- "experiments/" 2>/dev/null | grep -v '^$' || true)
            if [[ -n "$agent_exp_files" ]]; then
                while IFS= read -r exp_file; do
                    if [[ ! -f "$MAIN_DIR/$exp_file" ]]; then
                        echo "  [⚠️ MISSING] Agent 新增的檔案未出現在 main: $exp_file"
                        missing_files=$((missing_files + 1))
                    fi
                done <<< "$agent_exp_files"
                if [[ $missing_files -eq 0 ]]; then
                    echo "  [✓] 所有 experiments/ 新增檔案已正確合併"
                else
                    echo "  [⚠️ WARNING] $missing_files 個檔案遺漏！請手動檢查"
                fi
            fi

            # K1262-v4 (2026-04-27): POST-MERGE FILE-PRESENCE VERIFICATION (defensive layer)
            # 不只看 working tree 是否有檔（上面那段），還必須驗證 main:HEAD（git tree object）
            # 真的含 K-experiment 檔。working tree 有 ≠ commit 進 main HEAD（可能 untracked、
            # 可能在 stash、可能 -X ours drop 而 working tree 留 worktree 版本）。
            # 用 cat-file -e 確認檔案在 main:HEAD git object tree 裡。
            local k1262v4_missing_in_main=0
            local k1262v4_missing_files=""
            if [[ -n "$agent_exp_files" ]]; then
                while IFS= read -r exp_file; do
                    [[ -z "$exp_file" ]] && continue
                    # 確認檔案在 worktree branch 上存在
                    if git -C "$MAIN_DIR" cat-file -e "$branch:$exp_file" 2>/dev/null; then
                        # 確認 main HEAD 上也存在
                        if ! git -C "$MAIN_DIR" cat-file -e "HEAD:$exp_file" 2>/dev/null; then
                            k1262v4_missing_in_main=$((k1262v4_missing_in_main + 1))
                            k1262v4_missing_files="$k1262v4_missing_files  $exp_file"$'\n'
                        fi
                    fi
                done <<< "$agent_exp_files"
            fi
            if [[ $k1262v4_missing_in_main -gt 0 ]]; then
                echo ""
                echo "  🚨 ============================================="
                echo "  🚨 [CRITICAL] K1262-v4 detection: $k1262v4_missing_in_main 個 K-experiment 檔在 worktree-branch 但 NOT 在 main HEAD."
                echo "  🚨 Silent drop pattern detected. 缺檔："
                printf "%b" "$k1262v4_missing_files"
                echo "  🚨 必須手動 cherry-pick 救回："
                local last_branch_commit
                last_branch_commit=$(git -C "$MAIN_DIR" rev-parse "$branch" 2>/dev/null || echo "<branch-tip>")
                echo "  🚨   git -C \"$MAIN_DIR\" cherry-pick $last_branch_commit"
                echo "  🚨 Worktree NOT removed; 先 investigate 才能 retry."
                echo "  🚨 ============================================="
                echo ""
                # 標記 merge 沒真正成功，跳過 worktree 移除
                merge_ok=false
            fi

            # K1261-v3 (2026-04-27): 檢查 -X ours 是否靜默 drop 了 agent 對既有檔的修改
            # K1032 教訓 framing 限於 shared JSON, 但同 root cause 對 experiments/ 內 fork 檔同樣坑：
            # 主線程已 commit skeleton, agent 修改同檔 → -X ours 取 main = agent 版本 silent drop。
            local agent_modified_files
            agent_modified_files=$(git -C "$MAIN_DIR" log --diff-filter=M --name-only --pretty=format: "$main_branch_orig..$branch" -- "experiments/" 2>/dev/null | grep -v '^$' | sort -u || true)
            if [[ -n "$agent_modified_files" ]]; then
                local ours_dropped=0
                local dropped_files=""
                while IFS= read -r mod_file; do
                    [[ -z "$mod_file" ]] && continue
                    # 比較 main HEAD（merge 後）vs main_branch_orig（merge 前）：
                    # - 若同 = -X ours 取 main = agent 修改靜默 drop
                    # - 若異 = merge 取了 worktree 版本（或合併版本）= OK
                    if git -C "$MAIN_DIR" diff --quiet "$main_branch_orig" HEAD -- "$mod_file" 2>/dev/null; then
                        # main HEAD 對此檔內容與 merge 前相同 → -X ours 取了 main → worktree 變更被 drop
                        echo "  [🛑 -X ours DROPPED] $mod_file"
                        echo "      Agent 修改了此檔但 main 版本被保留（worktree branch 對此檔的變更靜默丟失）"
                        ours_dropped=$((ours_dropped + 1))
                        dropped_files="$dropped_files $mod_file"
                    fi
                done <<< "$agent_modified_files"
                if [[ $ours_dropped -gt 0 ]]; then
                    echo ""
                    echo "  🚨 ============================================="
                    echo "  🚨 K1032/K1261 PATTERN: -X ours 靜默 drop $ours_dropped 個 modified file"
                    # K1618 review Finding 2 (2026-07-04): 舊版只印警告仍 merge_ok=true → 之後
                    # 移除 worktree + branch -D force-delete → agent 修改真的遺失（reflog 兜底脆弱）。
                    # 改「永遠修流程不修資料」：自動從 worktree branch 還原這些檔並 commit；
                    # 任一還原失敗 → merge_ok=false 保留 worktree + branch 待人工，不 destructive 移除。
                    echo "  🔧 [AUTO-RESTORE] 自動從 $branch 還原被 drop 的 modified 檔..."
                    local ours_restore_failed=0
                    for df in $dropped_files; do
                        if git -C "$MAIN_DIR" checkout "$branch" -- "$df" 2>/dev/null; then
                            echo "  🔧   [✓] 還原 $df"
                        else
                            echo "  🔧   [✗] 還原失敗 $df"
                            ours_restore_failed=$((ours_restore_failed + 1))
                        fi
                    done
                    if [[ $ours_restore_failed -eq 0 ]]; then
                        # K1618 review CONDITIONAL_PASS 精修：add/commit 真失敗必 fail-closed
                        # 保留 worktree+branch（唯一 durable source），只有「無 diff 可提交」
                        # （還原內容與 HEAD 相同）才算合法 skip。
                        if ! git -C "$MAIN_DIR" add $dropped_files 2>/dev/null; then
                            echo "  🛑 git add 還原檔失敗 → 保留 worktree+branch 待人工（不移除）"
                            merge_ok=false
                        elif git -C "$MAIN_DIR" diff --cached --quiet -- $dropped_files 2>/dev/null; then
                            echo "  🔧 [OK] 還原檔與 main HEAD 內容相同，無需 commit（無資料遺失）"
                        elif git -C "$MAIN_DIR" commit -m "fix: restore agent modifications dropped by -X ours ($wt_name)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>" 2>/dev/null; then
                            echo "  🔧 [OK] 已自動還原並 commit $ours_dropped 個 agent 修改（無資料遺失）"
                        else
                            echo "  🛑 restore commit 失敗但有 staged 變更 → 保留 worktree+branch 待人工（不移除）"
                            merge_ok=false
                        fi
                    else
                        echo "  🛑 $ours_restore_failed 個檔還原失敗 → 保留 worktree + branch 待人工處理（不移除）"
                        merge_ok=false
                    fi
                    echo "  🚨 ============================================="
                    echo ""
                else
                    echo "  [✓] 所有 experiments/ modified files 都採 worktree 版本（無 silent drop）"
                fi
            fi
        fi

        # 清理 worktree
        if $merge_ok; then
            # 最終驗證：至少一個 experiments/K* 檔案存在
            local exp_dirs_on_main
            exp_dirs_on_main=$(ls -d experiments/K*/ 2>/dev/null | wc -l | tr -d ' ')
            echo "  [VERIFY] main 上 experiments/ 目錄數: $exp_dirs_on_main"

            # K1262-v4 (2026-04-27): loud remove，**禁止** --force fallback (CLAUDE.md L168)。
            # 失敗時印明確 hint：unlock + remove + branch -D；保留 worktree 待人工處理。
            local remove_ok=false
            local remove_err
            # K1618 (2026-07-04): 移除前確認 cwd 不在待移除 worktree 內（此路徑 merge 已成功、
            # 檔案已進 main，即使 guard 擋下保留 worktree 也是安全狀態）
            if ! ensure_cwd_outside_worktree "$wt_path"; then
                echo "  [SKIP] cwd guard 失敗，保留 worktree（merge 已完成、檔案已在 main）: $wt_path"
                return 0
            fi
            remove_err=$(git -C "$MAIN_DIR" worktree remove "$wt_path" 2>&1) && remove_ok=true || true
            if $remove_ok; then
                git -C "$MAIN_DIR" branch -D "$branch" 2>&1 || echo "  [WARN] branch $branch 刪除失敗（可能已被 remove 連帶處理）"
                echo "  [DONE] 已移除 worktree 和 branch"
            else
                # 解析 stale pid（typical: "lock file ... is locked by ... pid NNN"）
                local locked_pid
                locked_pid=$(echo "$remove_err" | grep -oE 'pid [0-9]+' | head -1 | awk '{print $2}' || true)
                echo "  [WARN] git worktree remove 失敗（拒絕 --force fallback，CLAUDE.md L168 禁止）"
                echo "  [WARN] err: $remove_err"
                echo ""
                echo "  [HINT] Worktree locked by stale process${locked_pid:+ (pid $locked_pid)}. Recovery:"
                echo "         git -C \"$MAIN_DIR\" worktree unlock $wt_path"
                echo "         git -C \"$MAIN_DIR\" worktree remove $wt_path"
                echo "         git -C \"$MAIN_DIR\" branch -D $branch"
                echo "  [HINT] 若 commits 已 merge 進 main 而 worktree 殘留檔不可信任，"
                echo "         確認 git -C \"$MAIN_DIR\" log --oneline -5 含 agent commits 後再清。"
            fi
        else
            echo "  [SKIP] 合併失敗，保留 worktree 待手動處理: $wt_path"
            echo "  [HINT] 手動修復: git cherry-pick <commit-hash>"
        fi
    else
        echo "  [DRY-RUN] 會合併 $commit_count 個 commits 到 $main_branch"
    fi

    echo ""
}

# K1684 (2026-07-12) STRIKE 3 of the K1032 class — "worktree work silently not merged".
#
# Every defence layer below this point assumes the directory under .claude/worktrees/ is a
# REGISTERED git worktree of this repo. A directory holding its OWN .git (a standalone clone --
# which is what `run_agent_job.py --cwd` had produced) is invisible to `git worktree list`, so
# get_agent_worktrees() never yields it, merge_one_worktree() never sees it, and the script
# reports "=== 完成 ===" having silently skipped an entire experiment. K1684 sat orphaned across
# three agent runs for exactly this reason: its objects live in a different object store, so even
# `git branch --contains` says the commits do not exist.
#
# Fail LOUD instead. The recovery is path-scoped extraction (never a cross-repo merge).
detect_unregistered_worktree_dirs() {
    local wt_root="$MAIN_DIR/.claude/worktrees"
    [[ -d "$wt_root" ]] || return 0

    local found=0 d name
    for d in "$wt_root"/*/; do
        [[ -d "$d" ]] || continue
        name=$(basename "$d")
        # registered? then the normal machinery owns it
        if git -C "$MAIN_DIR" worktree list --porcelain | grep -q "^worktree ${d%/}$"; then
            continue
        fi
        # not registered, but is it a git repo at all? (a stray non-git dir is not our problem)
        git -C "${d%/}" rev-parse --git-dir >/dev/null 2>&1 || continue

        found=1
        UNREGISTERED_FOUND=1
        local br
        br=$(git -C "${d%/}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')
        echo ""
        echo "  [ABORT] $name 在 .claude/worktrees/ 底下，但**不是**本 repo 註冊的 worktree。"
        echo "          它有自己的 .git（獨立 object store）→ 它的 commits 不在 main 的 object DB 裡，"
        echo "          merge / rev-list / branch --contains 全部看不到它。這是 silent orphan。"
        echo "          branch: $br"
        echo "          復原（path-scoped 抽取，不要跨 repo merge）："
        echo "            git -C \"$MAIN_DIR\" fetch .claude/worktrees/$name $br"
        echo "            git -C \"$MAIN_DIR\" checkout FETCH_HEAD -- experiments/"
        echo "            # 逐檔驗證內容後再 commit；確認無誤才刪目錄"
    done
    return $found
}

UNREGISTERED_FOUND=0
# 2026-07-19: 單一 worktree ABORT 不終止其他 worktree 的處理（K1143-v2 的設計），
# 但**必須**讓 caller（hourly fire / supervisor）看得見 —— 否則「未合併就保留待人工」
# 會被 exit 0 + 「=== 完成 ===」掩蓋成一次成功的整合。同 K1684 的理由。
ABORT_FOUND=0

# 主流程
# 用 compatible 方式讀 array（macOS bash 3.x 無 mapfile）
wt_array=()
while IFS= read -r line; do
    [[ -n "$line" ]] && wt_array+=("$line")
done < <(get_agent_worktrees)

detect_unregistered_worktree_dirs || true

if [[ ${#wt_array[@]} -eq 0 ]]; then
    echo "沒有找到 agent worktrees"
else
    echo "找到以下 agent worktrees:"
    for wt in "${wt_array[@]}"; do
        [[ -n "$wt" ]] && echo "  $(basename "$wt")"
    done
    echo ""

    # 用 for loop（非 pipe-while），避免子 shell 吞錯誤
    # K1143-v2 (2026-04-19): 單個 worktree abort (return 1) 不該終止整個 script；
    # 加 `|| true` 讓 main loop 繼續處理其他 worktree + orphan cleanup。
    for wt in "${wt_array[@]}"; do
        if [[ -n "$wt" ]]; then
            merge_one_worktree "$wt" || {
                ABORT_FOUND=1
                echo "  [SKIP] 這個 worktree abort，繼續處理其他"
            }
        fi
    done
fi

echo ""
echo "=== 完成 ==="
echo ""

# 清理 orphan worktree branches（worktree 已移除但 branch 殘留）
# K1143-v2 (2026-04-19): 用 git for-each-ref 而不是 `git branch | tr -d ' '`，
# 後者不會去掉 "currently checked out" 標記 `+` → 產出 `+worktree-agent-xxx`
# 錯誤名稱，後續 rev-list / branch -d 都會 silent 失敗。
echo "--- 清理 orphan worktree branches ---"
orphan_count=0
for branch in $(git for-each-ref --format='%(refname:short)' 'refs/heads/worktree-agent-*' 2>/dev/null); do
    # 檢查該 branch 是否還有 worktree 關聯
    if ! git worktree list --porcelain | grep -q "branch refs/heads/$branch"; then
        # 額外保護：檢查 branch 是否有未合併到 main 的 commits（防止 silent data loss）
        unmerged=$(git rev-list --count "main..$branch" 2>/dev/null || echo 0)
        if [[ "$unmerged" -gt 0 ]]; then
            echo "  [SKIP] $branch 有 $unmerged 個未合併 commits，不刪除（請手動 cherry-pick 或 git checkout）"
            continue
        fi
        if ! $DRY_RUN; then
            # -d (lowercase) 而不是 -D，refuse 未合併 commit 是最後一道防線
            git branch -d "$branch" 2>/dev/null && echo "  [CLEAN] 刪除 orphan branch: $branch" || \
                echo "  [SKIP] $branch branch -d 拒絕，保留供人工檢查"
        else
            echo "  [DRY-RUN] 會刪除 orphan branch: $branch"
        fi
        orphan_count=$((orphan_count + 1))
    fi
done
if [[ $orphan_count -eq 0 ]]; then
    echo "  無 orphan branches"
fi

# 顯示剩餘的 worktrees
echo ""
remaining=()
while IFS= read -r line; do
    [[ -n "$line" ]] && remaining+=("$line")
done < <(get_agent_worktrees)
if [[ ${#remaining[@]} -gt 0 ]] && [[ -n "${remaining[0]}" ]]; then
    echo "剩餘 worktrees："
    for wt in "${remaining[@]}"; do
        [[ -n "$wt" ]] && echo "  $(basename "$wt")"
    done
else
    echo "所有 agent worktrees 已清理完成"
fi

# K1684: 有未註冊的 worktree 目錄 → 非零退出，讓 caller（hourly fire / supervisor）看得見。
# 「完成」的訊息不可以掩蓋一個沒被合併的實驗。
if [[ "$UNREGISTERED_FOUND" -eq 1 ]]; then
    echo ""
    echo "=== 有未註冊的 worktree 目錄未處理（見上方 [ABORT]）— exit 1 ==="
    exit 1
fi

if [[ "$ABORT_FOUND" -eq 1 ]]; then
    echo ""
    echo "=== 有 worktree 因安全檢查 ABORT 而未合併（見上方 [ABORT]）— exit 1 ==="
    exit 1
fi
