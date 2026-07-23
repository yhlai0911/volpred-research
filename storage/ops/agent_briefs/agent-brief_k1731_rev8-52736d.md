# K1731 arm B rev8 — bounded claim-layer remediation

**Model**: opus / xhigh (per model_router)
**Task id**: `assign_24ebe308`（VolPred task pool，已由 hourly dispatch claim）
**Worktree cwd**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`（已是你的 cwd，branch `wt/dispatch-slot-1-bd00f90a-k1731`）

## 開工前必讀

1. 完整任務規格：`storage/next_tasks.json` 裡 id=`assign_24ebe308` 的 `description` 欄（用 python json 讀，不要整檔 cat）
2. Codex 裁決全文：`storage/ops/codex_reviews/k1731_armB_rev7_verdict.md`
3. `experiments/k1731/README.md`

## 範圍（**只修 claim layer，不重跑估計**）

三個 blocker，逐條做完並留證據：

- **B1 — DM interpretation 依 nested / non-nested 分流**：`k1731_gevreg_midas_ssvs_returns.py` 的 DM 解讀必須分流；GEV-HAR 那兩列只能標 `diagnostic-only`，**不得**附 coverage 或 bound。
- **B2 — 三份 results JSON 從 canonical source / finalizer 重生**：禁手改。重生後 numeric leaves 必須**零漂移**（用 flatten-diff 對照舊檔，把 diff 結果寫進交付 JSON）。
- **B3 — README opening 與 Honest conclusions 改寫**：不得再用 in-sample PIP 支撐 OOS does-not-improve null；改述為 *weak in-sample selection* + *uncorrected directional OOS diagnostic*。

## 驗收 gate（全過才算完成）

- 108-test nested-DM ratchet
- 69-check verification
- 3834-leaf regression（0 out-of-allowlist）
- 重建 freeze

## 硬性禁令

- ❌ 禁止 merge worktree（`assign_67f56b79` 維持 blocked，round 8 PASS 才解除）
- ❌ 禁止寫 `knowledge.json`（K1259：agent 不得自寫）
- ❌ 禁止 force push / `--no-verify` / 假數字
- ✅ commit 留在本 worktree branch 即可

## 交付物（**必須存在，否則 job 判失敗**）

`experiments/k1731/k1731_armB_rev8_remediation.json`，至少含：

```json
{
  "task_id": "assign_24ebe308",
  "blockers": {"B1a": {...}, "B1b": {...}, "B5": {...}},
  "results_json_regen": {"method": "canonical finalizer", "numeric_leaf_drift": 0, "flatten_diff": "..."},
  "gates": {"nested_dm_ratchet": "PASS/FAIL 108/108", "verification": "69/69", "regression": "3834 leaves / N out-of-allowlist"},
  "freeze_rebuilt": true,
  "codex_round8": {"submitted": true, "verdict": "...", "report_path": "..."},
  "commits": ["<sha>"],
  "honest_limitations": ["..."]
}
```

每一格都要是**你實際跑出來**的數字。任一 gate FAIL 就照實寫 FAIL 並說明，**不准粉飾**。

## 送審

修完跑 Codex round 8（`codex exec`，額度無限制），裁決存 `storage/ops/codex_reviews/k1731_armB_rev8_verdict.md`，並把 verdict 摘要寫進上面的交付 JSON。
