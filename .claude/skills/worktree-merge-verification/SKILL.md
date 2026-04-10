---
name: worktree-merge-verification
description: >
  Worktree agent 完成後的合併與驗證流程。防止 agent 工作成果遺失（K1032 教訓：
  merge_worktree.sh 判斷「no commits」但 reflog 有 commit，導致實驗檔案遺失）。
  Trigger: 每次 worktree agent 完成返回後自動執行。
user-invocable: false
---

# Worktree Merge Verification

## 觸發時機
每次 worktree agent（`isolation: "worktree"`）完成返回後，**必須執行此流程**。

## 流程（按順序，不可跳步）

### Step 1: 嘗試 merge_worktree.sh
```bash
bash scripts/merge_worktree.sh <agent-name>
```

### Step 2: 驗證檔案是否到位
```bash
ls experiments/K{ID}/ 2>/dev/null || echo "FILES MISSING"
```
如果檔案不存在 → 進入 Step 3 恢復流程。

### Step 3: 恢復遺失的 commit
merge_worktree.sh 有已知的邊緣情況：worktree 有 commit 但腳本判斷「no new commits」後直接刪除 worktree。

**恢復步驟**：
```bash
# 1. 檢查分支是否還在
git branch -a | grep <agent-name>

# 2. 搜尋 reflog
git reflog --all | grep "K{ID}\|<agent-name>" | head -5

# 3. Cherry-pick 遺失的 commit
git cherry-pick <commit-hash> --no-edit

# 4. 清理分支
git branch -D worktree-<agent-name> 2>/dev/null
```

### Step 4: 驗證 results JSON 核心數字
**K1016 教訓：agent 回報的數字可能與 JSON 不一致。**
```python
import json
with open(f'experiments/K{ID}/k{id}_results.json') as f:
    r = json.load(f)
# 逐一核對 agent summary 中的關鍵數字（DM t-stat, QLIKE, VaR pass/fail）
```

### Step 5: 記錄 knowledge（主線程負責）
- Worktree agent 禁止寫 knowledge.json
- 主線程根據驗證後的 JSON 數字撰寫 knowledge entry
- 數字必須來自 JSON，不可複製 agent summary

## 已知陷阱

| 日期 | 問題 | 原因 | 解法 |
|------|------|------|------|
| 2026-04-10 K1032 | merge 說 "no new commits" 但有 commit | merge_worktree.sh 的 `git log main..branch` 比較基準不正確（worktree 可能 fast-forward 到 main） | 用 reflog 找回 commit，cherry-pick |
| 2026-04 多次 | merge conflict fallback 導致 knowledge.json 90x 膨脹 | jq 去重 bug（item_id vs id 格式不一致） | 已修復：改用 Python content-hash 去重 |
| K923/K924/K932 | `git worktree remove --force` 遺失未 commit 的檔案 | Agent 沒有在結束前 commit | Preamble 強制要求 agent 結尾 commit |
