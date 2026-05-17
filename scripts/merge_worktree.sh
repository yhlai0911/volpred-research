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

# 用 BASH_SOURCE 而非 $0，並 fallback 到絕對路徑 git rev-parse --show-toplevel
SCRIPT_PATH="${BASH_SOURCE[0]:-$0}"
if [[ -f "$SCRIPT_PATH" ]]; then
    MAIN_DIR="$(cd "$(dirname "$SCRIPT_PATH")/.." && pwd)"
else
    MAIN_DIR="$(git rev-parse --show-toplevel 2>/dev/null || echo "$PWD")"
fi
cd "$MAIN_DIR" || { echo "[FATAL] 無法 cd 至 MAIN_DIR=$MAIN_DIR"; exit 1; }

DRY_RUN=false
TARGET=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) TARGET="$(basename "$arg")" ;;  # 只取 basename，確保匹配一致
    esac
done

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

    local new_commits
    new_commits=$(git -C "$MAIN_DIR" log --oneline "$main_branch..$branch" 2>/dev/null || true)

    # 雙重驗證：rev-list --count 防止 git log 靜默失敗（K1032/K1114/E067 教訓）
    local commit_count_verify
    commit_count_verify=$(git -C "$MAIN_DIR" rev-list --count "$main_branch..$branch" 2>/dev/null || echo "ERROR")

    if [[ "$commit_count_verify" == "ERROR" ]]; then
        echo "  [ABORT] git rev-list 失敗，無法確認 commit 狀態。手動處理。"
        return 1
    fi

    # K1262-v4 (2026-04-27): **PRIMARY 防線** — file-presence diff 不依賴 rev-list count。
    # 即使 rev-list 報 0（false negative，K1032/K1114/K1262 same root cause），
    # 只要 worktree branch tip 含 main 沒有的 experiments/<kXXX>/ 檔，就強制走 merge path。
    # 這條 layer 在 K1262 silent drop bug 第三次重現後新增。
    local file_presence_unique=""
    file_presence_unique=$(git -C "$MAIN_DIR" diff-tree --diff-filter=A --name-only -r "$main_branch" "$branch" -- experiments/ 2>/dev/null | grep -v '^$' || true)
    # 過濾出真正只在 worktree branch 有的（main HEAD 不存在）
    local worktree_only_exp_files=""
    if [[ -n "$file_presence_unique" ]]; then
        while IFS= read -r f; do
            [[ -z "$f" ]] && continue
            if ! git -C "$MAIN_DIR" cat-file -e "$main_branch:$f" 2>/dev/null; then
                worktree_only_exp_files="$worktree_only_exp_files$f"$'\n'
            fi
        done <<< "$file_presence_unique"
    fi

    # K1262-v5 (2026-04-27) EXTRA-DEFENSE: 若 git diff-tree 回空但 worktree 有實際檔案 not in
    # MAIN_DIR，純文件系統 fallback。處理 git plumbing 全 silent fail 的 K1262-actual case
    # (rev-list=0, log=empty, diff-tree=empty, 但檔案實在 worktree 裡)。
    if [[ -z "$worktree_only_exp_files" ]] && [[ -d "$wt_path/experiments" ]]; then
        local fs_only_files=""
        while IFS= read -r -d '' wf; do
            local rel="${wf#$wt_path/}"
            if [[ ! -e "$MAIN_DIR/$rel" ]]; then
                fs_only_files="${fs_only_files}${rel}"$'\n'
            fi
        done < <(find "$wt_path/experiments" -type f -not -path '*/__pycache__/*' -print0 2>/dev/null)
        if [[ -n "$fs_only_files" ]]; then
            echo "  [🚨 K1262-v5 FS-DEFENSE] git plumbing 全空但 filesystem 顯示 worktree experiments/ 有 main 沒有的檔案"
            worktree_only_exp_files="$fs_only_files"
        fi
    fi

    if [[ -z "$new_commits" ]] && [[ "$commit_count_verify" -eq 0 ]] && [[ -n "$worktree_only_exp_files" ]]; then
        echo "  [🚨 K1262-v4 PRIMARY] rev-list 報 0 commits 但 file-presence diff 顯示 worktree branch 含 main 沒有的 experiments/ 檔："
        echo "$worktree_only_exp_files" | head -10 | sed 's/^/      /'
        echo "  [🚨 K1262-v4] 強制走 merge path（不信 rev-list false negative）"
        # 重建 new_commits 與 commit_count_verify 從另一條路徑（git log --all 跨 worktree）
        new_commits=$(git -C "$MAIN_DIR" log --oneline --all "^$main_branch" "$branch" 2>/dev/null | head -50 || true)
        if [[ -z "$new_commits" ]]; then
            # 仍找不到 — 可能 branch ref 對不上但檔案在 working tree（gitignored）
            # 沿用既有 K1143-v2 abort path：file-presence layer fall through 到下面 if
            :
        else
            commit_count_verify=$(echo "$new_commits" | grep -c '^' || echo 0)
            echo "  [K1262-v4] 從 git log --all 重建 commit list: $commit_count_verify commits"
        fi
    fi

    if [[ -z "$new_commits" ]] && [[ "$commit_count_verify" -eq 0 ]]; then
        # K1143-v2 (2026-04-19): rev-list=0 不代表工作目錄也空。
        # Auto-commit 失敗、detached HEAD、gitignore 吃掉檔案 → rev-list=0 但
        # wt_path 底下仍有 experiments/<kXXX> 是**主目錄沒有的**。舊版在這裡執行
        # `git worktree remove --force` 直接刪除整個目錄，是 K903/K904/K1032/K1114/K1100g_d9
        # silent loss 的真正 smoking gun。
        #
        # 防禦：pre-remove 掃 worktree 下 experiments/<kXXX>/，凡是主目錄沒有的就 abort。
        # 有相同 kXXX 的 common dir 也需要用 diff 檢查是否 worktree 版更新（不比 __pycache__）。
        local orphan_exp_dirs=""
        local updated_exp_dirs=""
        if [[ -d "$wt_path/experiments" ]]; then
            for exp_dir in "$wt_path/experiments/"*/; do
                [[ -d "$exp_dir" ]] || continue
                local exp_name
                exp_name=$(basename "$exp_dir")
                # K1262-v5 (2026-04-27): glob 給的 $exp_dir 帶 trailing slash，但 diff -rq 輸出
                # `Only in /path:` 不帶 trailing slash → grep `^Only in $exp_dir` (with /) NEVER matches
                # → wt_only 永遠空 → updated_exp_dirs 永遠空 → silent drop. 修：strip trailing /.
                local exp_dir_no_slash="${exp_dir%/}"
                if [[ ! -d "$MAIN_DIR/experiments/$exp_name" ]]; then
                    orphan_exp_dirs="$orphan_exp_dirs  $exp_name\n"
                else
                    # 共存資料夾：比對有無 worktree-only 的關鍵檔
                    local wt_only
                    wt_only=$(diff -rq "$MAIN_DIR/experiments/$exp_name" "$exp_dir_no_slash" 2>/dev/null \
                        | grep "^Only in $exp_dir_no_slash" \
                        | grep -v '__pycache__' \
                        | head -5 || true)
                    if [[ -n "$wt_only" ]]; then
                        updated_exp_dirs="$updated_exp_dirs  $exp_name (worktree-only files):\n$wt_only\n"
                    fi
                fi
            done
        fi
        if [[ -n "$orphan_exp_dirs" ]] || [[ -n "$updated_exp_dirs" ]]; then
            echo "  [🛑 ABORT] rev-list=0 但 worktree experiments/ 有主目錄沒有的內容（auto-commit 漏掉或 gitignored）："
            if [[ -n "$orphan_exp_dirs" ]]; then
                echo "    主目錄不存在的實驗資料夾："
                printf "%b" "$orphan_exp_dirs"
            fi
            if [[ -n "$updated_exp_dirs" ]]; then
                echo "    主目錄有但 worktree 多出檔案的資料夾："
                printf "%b" "$updated_exp_dirs"
            fi
            echo "  [🛑 ABORT] 拒絕 remove 以防 silent data loss"
            echo "  [HINT] 手動處理建議："
            echo "         1. cd $wt_path && git status && ls -la experiments/"
            echo "         2. 把漏掉的檔手動 copy 到主目錄：cp -r $wt_path/experiments/<kXXX> $MAIN_DIR/experiments/"
            echo "         3. 主目錄 git add + commit 後再跑 bash scripts/merge_worktree.sh $wt_name"
            return 1
        fi

        echo "  [OK] 沒有新的 commits（雙重確認 rev-list=0）+ experiments/ 也空，可安全移除"
        if ! $DRY_RUN; then
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

    # Merge 到 main
    local commit_count
    commit_count=$(echo "$new_commits" | wc -l | tr -d ' ')

    if ! $DRY_RUN; then
        echo "  [ACTION] 合併到 $main_branch..."

        # 記錄 main 的原始位置（用於合併後驗證）
        local main_branch_orig
        main_branch_orig=$(git rev-parse HEAD)

        # 確保 main 沒有未提交的變更（否則 merge 會被拒絕）
        local main_dirty=false
        local main_status
        main_status=$(git status --porcelain 2>/dev/null || true)
        if [[ -n "$main_status" ]]; then
            main_dirty=true
            echo "  [PREP] main 有未提交變更，先 stash..."
            git stash push -m "merge_worktree: temp stash before merging $wt_name" 2>/dev/null || true
        fi

        # 檢查 agent 是否修改了共享 JSON（違反規則的早期警告）
        # K1262-v4 (2026-04-27): git diff 用 -C "$MAIN_DIR" 強制 ref 解析在主 repo
        # 2026-05-18 K-worktree-stash-pop fix: 加 runtime/operational state 檔
        # （worktree 不該帶這些；它們是 main 上 cron/runtime 寫的 live state）
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
            if git -C "$MAIN_DIR" diff --name-only "$main_branch..$branch" -- "$shared_f" 2>/dev/null | grep -q .; then
                shared_json_modified=true
                shared_files="$shared_files $shared_f"
            fi
        done

        if $shared_json_modified; then
            echo "  [🛑 ABORT] Agent 修改了共享 JSON（違反 worktree 規則）:"
            echo "     $shared_files"
            echo "  [🛑 ABORT] -X ours 會靜默覆蓋 agent 變更；改 abort 讓你手動處理"
            echo "  [HINT] 手動路徑："
            echo "         1. 檢視 git diff $main_branch..$branch -- $shared_files"
            echo "         2. 決定把 agent 的有價值變更手動 apply 到 main（或直接 drop）"
            echo "         3. 再跑 bash scripts/merge_worktree.sh $wt_name 續做合併"
            # 還原 stash 才退出（避免 silent stash）
            if $main_dirty; then
                echo "  [RESTORE] 還原剛才的 stash..."
                git stash pop 2>&1 | head -5 || echo "  [⚠️] stash pop 失敗，手動 git stash list + git stash apply stash@{0}"
            fi
            return 1
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

        # 還原 main 的 stash
        if $main_dirty; then
            echo "  [PREP] 還原 main 的 stash..."
            if ! git stash pop 2>&1 | tee /tmp/merge_worktree_stash_pop.log; then
                echo ""
                echo "  ⚠️  STASH POP 衝突 — 自動 surgical restore runtime 檔（2026-05-18 K-worktree-stash-pop fix）"
                # 自動救回 runtime/operational state 檔案（worktree merge 不應該覆蓋這些）
                # 這些檔案的 worktree 版本是 stale（從 checkout 時凍結），main 版本才是 live
                local runtime_files=(
                    "storage/.release_settings.json"
                    "storage/logs/cron/release_pool.log"
                    "storage/logs/cron/check_alerts.log"
                    "storage/logs/cron/collect_us.log"
                    "storage/logs/cron/collect_tw.log"
                    "storage/logs/cron/daily_update.log"
                    "storage/logs/cron/continue_task_stub.log"
                    "storage/market_status.json"
                    "storage/session_state.json"
                    "storage/ops/cron_last_run.json"
                    "storage/ops/pending_sessions.json"
                )
                local restored=0
                for rf in "${runtime_files[@]}"; do
                    # 只還原 stash@{0} 內確實有的 runtime 檔（避免 noisy error）
                    if git stash show stash@{0} --name-only 2>/dev/null | grep -qx "$rf"; then
                        if git checkout stash@{0} -- "$rf" 2>/dev/null; then
                            echo "    [✓ RESTORED] $rf"
                            restored=$((restored + 1))
                        fi
                    fi
                done
                echo "  [OK] 自動還原 $restored 個 runtime 檔"
                echo ""
                echo "  🚨 ============================================="
                echo "  🚨 但 stash@{0} 內可能還有其他主線程未提交變更需手動處理"
                echo "  🚨 不要關掉這個 session 以免遺忘。"
                echo "  🚨 救回方法："
                echo "  🚨   git stash show stash@{0} --name-only   # 看有哪些檔"
                echo "  🚨   git checkout stash@{0} -- <path>       # 救特定檔"
                echo "  🚨   git stash apply stash@{0}              # 全部 apply"
                echo "  🚨 ============================================="
                echo ""
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
                    echo "  🚨 不阻擋 merge（merge 已完成）但強烈建議手動恢復："
                    for df in $dropped_files; do
                        echo "  🚨   git checkout $branch -- $df"
                    done
                    echo "  🚨   git add$dropped_files"
                    echo "  🚨   git commit -m \"fix: restore agent modifications dropped by -X ours\""
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

# 主流程
# 用 compatible 方式讀 array（macOS bash 3.x 無 mapfile）
wt_array=()
while IFS= read -r line; do
    [[ -n "$line" ]] && wt_array+=("$line")
done < <(get_agent_worktrees)

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
            merge_one_worktree "$wt" || echo "  [SKIP] 這個 worktree abort，繼續處理其他"
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
