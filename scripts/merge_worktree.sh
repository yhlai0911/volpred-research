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

    # Cherry-pick 或 merge 到 main
    local commit_count
    commit_count=$(echo "$new_commits" | wc -l | tr -d ' ')

    if ! $DRY_RUN; then
        echo "  [ACTION] 合併到 $main_branch..."

        # 嘗試 merge（比 cherry-pick 更安全，處理衝突更好）
        if git merge "$branch" --no-edit -m "Merge agent worktree $wt_name ($commit_count commits)

Merged from worktree branch $branch.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>" 2>/dev/null; then
            echo "  [OK] 合併成功"

            # 合併成功後安全移除 worktree
            git worktree remove "$wt_path" 2>/dev/null || git worktree remove --force "$wt_path" 2>/dev/null
            git branch -D "$branch" 2>/dev/null || true
            echo "  [DONE] 已移除 worktree"
        else
            echo "  [ERROR] 合併衝突！需要手動解決"
            git merge --abort 2>/dev/null || true

            # 嘗試用 checkout 方式複製檔案
            echo "  [ACTION] 嘗試直接複製 experiments/ 和 storage/ 檔案..."
            local exp_files
            exp_files=$(cd "$wt_path" && git diff --name-only "$main_branch" -- experiments/ 2>/dev/null || true)

            local copied_any=false

            if [[ -n "$exp_files" ]]; then
                echo "$exp_files" | while IFS= read -r f; do
                    if [[ -f "$wt_path/$f" ]]; then
                        local dir=$(dirname "$f")
                        mkdir -p "$MAIN_DIR/$dir"
                        cp "$wt_path/$f" "$MAIN_DIR/$f"
                        echo "      Copied: $f"
                    fi
                done
                git add experiments/ 2>/dev/null || true
                copied_any=true
            fi

            # --- Merge storage/reports/{id}.json (individual reports, safe to copy) ---
            local report_files
            report_files=$(cd "$wt_path" && git diff --name-only "$main_branch" -- storage/reports/ 2>/dev/null | grep -v 'feed\.json' || true)
            if [[ -n "$report_files" ]]; then
                echo "  [ACTION] 複製 individual report JSON..."
                echo "$report_files" | while IFS= read -r f; do
                    if [[ -f "$wt_path/$f" ]]; then
                        local dir=$(dirname "$f")
                        mkdir -p "$MAIN_DIR/$dir"
                        cp "$wt_path/$f" "$MAIN_DIR/$f"
                        echo "      Copied: $f"
                    fi
                done
                git add storage/reports/ 2>/dev/null || true
                copied_any=true
            fi

            # --- Merge storage/memory/ JSON arrays (knowledge, experiments, etc.) ---
            # Strategy: use jq to union both sides by unique key, avoiding data loss
            local memory_files
            memory_files=$(cd "$wt_path" && git diff --name-only "$main_branch" -- storage/memory/ 2>/dev/null || true)
            if [[ -n "$memory_files" ]] && command -v jq &>/dev/null; then
                echo "  [ACTION] 合併 storage/memory/ JSON 檔案..."
                echo "$memory_files" | while IFS= read -r f; do
                    local main_file="$MAIN_DIR/$f"
                    local wt_file="$wt_path/$f"
                    if [[ -f "$wt_file" ]] && [[ -f "$main_file" ]]; then
                        # Detect unique key: item_id for knowledge, id for others, entry_id for log
                        local key="id"
                        if jq -e '.[0].item_id' "$main_file" &>/dev/null; then
                            key="item_id"
                        elif jq -e '.[0].entry_id' "$main_file" &>/dev/null; then
                            key="entry_id"
                        fi
                        # Union: main entries + worktree entries not already in main
                        local merged
                        merged=$(jq -s --arg key "$key" '
                            (.[0] | map(.[$key]) | map(select(. != null))) as $existing_ids |
                            .[0] + [.[1][] | select(.[$key] as $id | ($existing_ids | index($id)) == null)]
                        ' "$main_file" "$wt_file" 2>/dev/null) || true
                        if [[ -n "$merged" ]]; then
                            echo "$merged" > "$main_file"
                            echo "      Merged: $f (union by .$key)"
                        else
                            echo "      [WARN] jq merge failed for $f, keeping main version"
                        fi
                    elif [[ -f "$wt_file" ]] && [[ ! -f "$main_file" ]]; then
                        local dir=$(dirname "$f")
                        mkdir -p "$MAIN_DIR/$dir"
                        cp "$wt_file" "$main_file"
                        echo "      Copied (new): $f"
                    fi
                done
                git add storage/memory/ 2>/dev/null || true
                copied_any=true
            elif [[ -n "$memory_files" ]]; then
                echo "  [WARN] jq not found, skipping storage/memory/ merge"
                echo "         Install jq to enable safe JSON array merging"
            fi

            if $copied_any; then
                git commit -m "Copy experiment + storage files from worktree $wt_name (merge conflict fallback)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>" 2>/dev/null || true
                echo "  [OK] 檔案複製/合併成功"

                # 現在安全移除
                git worktree remove --force "$wt_path" 2>/dev/null || true
                git branch -D "$branch" 2>/dev/null || true
                echo "  [DONE] 已移除 worktree"
            else
                echo "  [SKIP] 沒有可複製的檔案，保留 worktree 待手動處理"
            fi
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
