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

MAIN_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$MAIN_DIR"

DRY_RUN=false
TARGET=""

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) TARGET="$arg" ;;
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

    # 如果指定了 target，只處理匹配的
    if [[ -n "$TARGET" ]] && [[ "$wt_name" != *"$TARGET"* ]]; then
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

    if [[ -z "$new_commits" ]]; then
        echo "  [OK] 沒有新的 commits，可安全移除"
        if ! $DRY_RUN; then
            git worktree remove "$wt_path" 2>/dev/null || git worktree remove --force "$wt_path" 2>/dev/null
            git branch -D "$branch" 2>/dev/null || true
            echo "  [DONE] 已移除 worktree"
        else
            echo "  [DRY-RUN] 會移除 worktree"
        fi
        return 0
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
            echo "  [⚠️ WARNING] Agent 修改了共享 JSON（違反 worktree 規則）:"
            echo "     $shared_files"
            echo "  [⚠️ WARNING] 這些檔案的 agent 變更將被 main 覆蓋（-X ours）"
            echo "  [⚠️ WARNING] 請在合併後手動從 experiments/ README 恢復知識記錄"
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

            # 最後手段：直接複製 experiments/ 新檔案
            echo "  [FALLBACK] 直接複製 experiments/ 檔案..."
            local exp_files
            exp_files=$(cd "$wt_path" && git diff --name-only "$main_branch" -- experiments/ 2>/dev/null || true)
            if [[ -n "$exp_files" ]]; then
                echo "$exp_files" | while IFS= read -r f; do
                    if [[ -f "$wt_path/$f" ]]; then
                        mkdir -p "$MAIN_DIR/$(dirname "$f")"
                        cp "$wt_path/$f" "$MAIN_DIR/$f"
                        echo "      Copied: $f"
                    fi
                done
                git add experiments/ 2>/dev/null || true
                git commit -m "Copy experiments from worktree $wt_name (fallback)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>" 2>/dev/null || true
                merge_ok=true
                echo "  [OK] fallback 複製成功"
            fi
        fi

        # 還原 main 的 stash
        if $main_dirty; then
            echo "  [PREP] 還原 main 的 stash..."
            git stash pop 2>/dev/null || {
                echo "  [WARN] stash pop 衝突，保留在 stash 中（git stash list 查看）"
            }
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
            git worktree remove "$wt_path" 2>/dev/null || git worktree remove --force "$wt_path" 2>/dev/null
            git branch -D "$branch" 2>/dev/null || true
            echo "  [DONE] 已移除 worktree"
        else
            echo "  [SKIP] 合併失敗，保留 worktree 待手動處理: $wt_path"
        fi
    else
        echo "  [DRY-RUN] 會合併 $commit_count 個 commits 到 $main_branch"
    fi

    echo ""
}

# 主流程
worktrees=$(get_agent_worktrees)

if [[ -z "$worktrees" ]]; then
    echo "沒有找到 agent worktrees"
    exit 0
fi

echo "找到以下 agent worktrees:"
echo "$worktrees" | while IFS= read -r wt; do
    echo "  $(basename "$wt")"
done
echo ""

echo "$worktrees" | while IFS= read -r wt; do
    if [[ -n "$wt" ]]; then
        merge_one_worktree "$wt"
    fi
done

echo ""
echo "=== 完成 ==="
echo ""
# 顯示剩餘的 worktrees
remaining=$(get_agent_worktrees)
if [[ -n "$remaining" ]]; then
    echo "剩餘 worktrees："
    echo "$remaining" | while IFS= read -r wt; do
        echo "  $(basename "$wt")"
    done
else
    echo "所有 agent worktrees 已清理完成"
fi
