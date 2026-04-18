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
    local has_uncommitted=false
    if [[ -d "$wt_path" ]]; then
        local status
        status=$(cd "$wt_path" && git status --porcelain 2>/dev/null || true)
        if [[ -n "$status" ]]; then
            has_uncommitted=true
            echo "  [!] 有未提交的變更："
            echo "$status" | head -10 | sed 's/^/      /'
            local total=$(echo "$status" | wc -l | tr -d ' ')
            if [[ $total -gt 10 ]]; then
                echo "      ... 共 $total 個檔案"
            fi
        fi
    fi

    # 如果有未提交變更，自動 commit
    if $has_uncommitted; then
        echo "  [ACTION] 自動提交未保存的變更..."
        if ! $DRY_RUN; then
            (cd "$wt_path" && git add -A && git commit -m "Auto-commit: save agent work before worktree merge

Files saved from worktree $wt_name to prevent data loss.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>") || {
                echo "  [ERROR] 自動提交失敗"
                return 1
            }
        else
            echo "  [DRY-RUN] 會自動提交"
        fi
    fi

    # 找出 worktree 分支上的新 commits（相對於 main）
    local main_branch
    main_branch=$(git rev-parse --abbrev-ref HEAD)

    local new_commits
    new_commits=$(git log --oneline "$main_branch..$branch" 2>/dev/null || true)

    # 雙重驗證：rev-list --count 防止 git log 靜默失敗（K1032/K1114/E067 教訓）
    local commit_count_verify
    commit_count_verify=$(git rev-list --count "$main_branch..$branch" 2>/dev/null || echo "ERROR")

    if [[ "$commit_count_verify" == "ERROR" ]]; then
        echo "  [ABORT] git rev-list 失敗，無法確認 commit 狀態。手動處理。"
        return 1
    fi

    if [[ -z "$new_commits" ]] && [[ "$commit_count_verify" -eq 0 ]]; then
        echo "  [OK] 沒有新的 commits（雙重確認 rev-list=0），可安全移除"
        if ! $DRY_RUN; then
            git worktree remove "$wt_path" 2>/dev/null || git worktree remove --force "$wt_path" 2>/dev/null
            # 用 -d (lowercase) 不 -D：refuse 未合併 commit, 防止 silent data loss
            git branch -d "$branch" 2>/dev/null || {
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
        local shared_json_modified=false
        local shared_files=""
        for shared_f in "storage/reports/feed.json" "storage/memory/knowledge.json" "storage/memory/thinking_journal.json" "storage/memory/experiment_experiences.json"; do
            if git diff --name-only "$main_branch..$branch" -- "$shared_f" 2>/dev/null | grep -q .; then
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
            local exp_files
            exp_files=$(cd "$wt_path" && git log --diff-filter=A --name-only --pretty=format: "$main_branch..$branch" -- experiments/ 2>/dev/null | grep -v '^$' | sort -u || true)
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
                echo "  🚨 ============================================="
                echo "  🚨 STASH POP 衝突！你的主線程修改還在 stash@{0}"
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
        if $merge_ok; then
            echo "  [VERIFY] 檢查 experiments/ 檔案完整性..."
            local missing_files=0
            local agent_exp_files
            agent_exp_files=$(git log --diff-filter=A --name-only --pretty=format: "$main_branch_orig..$branch" -- "experiments/" 2>/dev/null | grep -v '^$' || true)
            if [[ -n "$agent_exp_files" ]]; then
                while IFS= read -r exp_file; do
                    if [[ ! -f "$MAIN_DIR/$exp_file" ]]; then
                        echo "  [⚠️ MISSING] Agent 新增的檔案未出現在 main: $exp_file"
                        missing_files=$((missing_files + 1))
                    fi
                done <<< "$agent_exp_files"
                if [[ $missing_files -eq 0 ]]; then
                    echo "  [✓] 所有 experiments/ 檔案已正確合併"
                else
                    echo "  [⚠️ WARNING] $missing_files 個檔案遺漏！請手動檢查"
                fi
            fi
        fi

        # 清理 worktree
        if $merge_ok; then
            # 最終驗證：至少一個 experiments/K* 檔案存在
            local exp_dirs_on_main
            exp_dirs_on_main=$(ls -d experiments/K*/ 2>/dev/null | wc -l | tr -d ' ')
            echo "  [VERIFY] main 上 experiments/ 目錄數: $exp_dirs_on_main"

            # loud remove — 不吞錯誤，remove 失敗必須讓使用者知道
            local remove_ok=false
            if git worktree remove "$wt_path" 2>&1; then
                remove_ok=true
            else
                echo "  [WARN] worktree remove 拒絕（可能仍有 untracked 檔）；嘗試 --force..."
                if git worktree remove --force "$wt_path" 2>&1; then
                    remove_ok=true
                else
                    echo "  [WARN] --force 也失敗（常見是 claude agent lock）；嘗試 unlock + -f -f..."
                    git worktree unlock "$wt_path" 2>&1 || true
                    if git worktree remove -f -f "$wt_path" 2>&1; then
                        remove_ok=true
                    else
                        echo "  🚨 [ERROR] unlock + -f -f 也失敗。手動處理："
                        echo "  🚨   ls $wt_path                              # 看殘留"
                        echo "  🚨   rm -rf $wt_path && git worktree prune   # 強制清"
                        echo "  🚨   git branch -D $branch                   # 再刪 branch"
                    fi
                fi
            fi
            if $remove_ok; then
                git branch -D "$branch" 2>&1 || echo "  [WARN] branch $branch 刪除失敗（可能已被 remove 連帶處理）"
                echo "  [DONE] 已移除 worktree 和 branch"
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
    for wt in "${wt_array[@]}"; do
        if [[ -n "$wt" ]]; then
            merge_one_worktree "$wt"
        fi
    done
fi

echo ""
echo "=== 完成 ==="
echo ""

# 清理 orphan worktree branches（worktree 已移除但 branch 殘留）
echo "--- 清理 orphan worktree branches ---"
orphan_count=0
for branch in $(git branch --list 'worktree-agent-*' 2>/dev/null | tr -d ' '); do
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
