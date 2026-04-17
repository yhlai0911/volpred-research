<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

---
name: agent-result-verification
description: >
  Agent（worktree 或 background）返回實驗結果後的驗證 checklist。
  防止 agent 回報不準確的數字（K1016 教訓：agent 聲稱 QLIKE 改善 +13.7%
  但 JSON 顯示惡化）。Trigger: 每次 agent 返回實驗結果後自動執行。
  Do not use for research design, article writing, or generic platform ops.
user-invocable: false
---

# Agent Result Verification Checklist

## Scope Boundary

Use this skill only after agent 回報統計或比較結果時，用來：

- 以 results JSON 為準驗證數字
- 檢查號誌方向與合理性
- 阻止錯誤數字流入 knowledge / 文章

Do **not** use this skill for：

- 研究設計與模型選擇 → `autonomous-research`
- worktree merge / reflog 恢復 → `worktree-merge-verification`

## 觸發時機
每次 agent 返回包含統計數字的實驗結果後，**在記錄 knowledge 之前**必須執行。

## Checklist（按順序）

### 1. 讀取 results JSON（不信 agent summary）
```python
import json
with open(f'experiments/K{ID}/k{id}_results.json') as f:
    r = json.load(f)
```

### 2. 核對關鍵數字
逐一比對以下數字是否與 agent summary 一致：

| 指標 | Agent 說 | JSON 實際值 | 一致？ |
|------|---------|------------|--------|
| QLIKE (model A) | | | |
| QLIKE (model B) | | | |
| DM t-stat | | | |
| QLIKE improvement % | | | |
| VaR pass/fail | | | |

**如果任何數字不一致 → 以 JSON 為準，不用 agent 的數字。**

### 3. 合理性檢查
- [ ] Sharpe > 2x baseline? → 90% 有 bug，暫停
- [ ] DM t-stat 的正負號是否合理？（負 = 新模型更好）
- [ ] QLIKE improvement 方向是否與 DM 一致？
- [ ] VaR violation rate 是否在合理範圍？（2.5% target → 1-4% 正常）
- [ ] 模型有收斂嗎？（convergence flag, persistence < 1）

### 4. 數字不一致的常見原因

| 現象 | 常見原因 |
|------|---------|
| Agent 說改善但 JSON 顯示惡化 | Agent 混淆了 model A 和 model B 的數字 |
| DM t-stat 正負號反了 | Agent 弄反了比較方向（A vs B 還是 B vs A）|
| QLIKE % 不匹配 | Agent 用了不同的 baseline（round-off 或 wrong model）|
| 兩個模型結果完全相同 | 代碼 bug：兩個模型共享了同一組參數或 fear input |

### 5. 通過驗證後才可以
- 記錄 knowledge（數字從 JSON 抄，不從 agent summary 抄）
- 撰寫文章
- 更新 research_program.md

## 歷史事件

| 日期 | 實驗 | 問題 | 影響 |
|------|------|------|------|
| 2026-04-10 | K1016 | Agent 聲稱 QLIKE +13.7% (DM=+5.46)，JSON 顯示惡化 (1.616→1.831) | Knowledge 記錄錯誤數字，需要修正 |
| 2026-04-10 | K1016 | M4/M5 結果完全相同 | 代碼 bug：兩個模型共用 input |
| 2026-03-29 | 8/93 實驗 | 10% 的實驗被推翻 | 全部因跳過「Codex 先審代碼」|
