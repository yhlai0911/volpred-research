# K1623 第三臂（arm C）— round-3 送審前唯一的 compute gate

**Model**: opus / xhigh (per model_router)
**Task id**: `k1623_mc_third_arm_mean_structure_share`（VolPred task pool，已 claim）
**Worktree cwd**: `.claude/worktrees/dispatch-slot-2-c5cafe39-k1623`（branch `worktree-dispatch-slot-2-c5cafe39-k1623`）

## 開工前必讀

1. 完整任務規格：`storage/next_tasks.json` 裡 id=`k1623_mc_third_arm_mean_structure_share` 的 `description`
2. `experiments/k1623/README.md`（特別是 §6.4 目前那條 `DISCLOSED, NOT FIXED` 的 scope limit）
3. `experiments/k1623/k1623_rev2_mc.py` + `k1623_rev2_mc_results.json`

## 要解的 blocked item

`mean_structure_generated_regressor_share_unmeasured` — 現行兩臂**都**重估段均值，該成分在 A−B contrast 中相消，因此無法量化「估計段均值」相對「定位斷點」在 generated-regressor 不確定性中的佔比。

加**第三臂 C**（用已知植入的 level 向量做 demean，location + level 皆 oracle）後：
- **A−B** = 斷點定位 + 均值估計 的合計
- **B−C** = 均值估計 的單獨貢獻

## Frozen 數字（**不可改動**，供對照）

- Arm A−B：VIX −0.019962 / SPY −0.045159 / TW0050 −0.055620 / QQQ −0.041103 / N225 −0.045547 → range **[−0.0556, −0.0200]**
- 原 arm-A 總偏誤 range **[−0.0846, −0.0273]**
- `k1623_rev2_mc_results.json` 既有欄位經 flatten-diff 驗證為 **0 改 0 移、僅 50 新增** → 第三臂**必須同樣只新增欄位**，不得改動 frozen 欄位。

## 執行順序（**不可跳步**）

1. 擴充 `k1623_rev2_mc.py` 加 arm C（known-level demean）。**同 seed / 同 DGP / 同 replication 數，A/B/C 三臂共用同一組模擬路徑**（否則 B−C 不是乾淨對比）。
2. **寫完先給 Codex 審再跑**（實驗碼一律先審後跑）— `codex exec`，裁決存 `storage/ops/codex_reviews/k1623_armC_script_review.md`。
3. Codex 過了才走
   `uv run python scripts/compute_queue.py enqueue --script <path> --title "K1623 arm C MC" --result-artifact <new json> --output-path <exact file> --followup-brief '<收件要做的事>' --followup-task-type experiment --timeout 3600`。
   **heavy MC 禁塞本 job 內硬跑。**
4. 本 job 到「已 enqueue」為止即算完成；結果回來由後續 fire 在 PHASE A 收件，再更新 README §6.4 + `claim_corrections_rev3`。

## 替代路徑

若你判定第三臂不值得跑 → **明確接受為 permanent scope limit**，在 README 與 MC JSON 寫死理由（兩臂設計上相消、需第三臂），並在交付 JSON 留書面裁決。**不可默默跳過。**

## round-3 送審前的其他前置（本 job 一併處理）

README 尾端工具碎片已於 `0dd6aa987` 清除 → **會改 README 的 sha256 pin**。送審前必須重跑
`uv run python scripts/experiment_gates.py verdict-template` 重生 `review_verdict.json`
（目前 verdict=FAIL、fail-closed、29 個 sha256 pin，certify 正擋著 merge）。

## 硬性禁令

- ❌ 禁止 merge worktree（round 3 PASS 才可 merge）
- ❌ 禁止寫 `knowledge.json`（K1259）
- ❌ 禁止改動 frozen 欄位／force push／`--no-verify`／假數字

## 交付物（**必須存在**）

`experiments/k1623/k1623_arm_c_decision.json`：

```json
{
  "task_id": "k1623_mc_third_arm_mean_structure_share",
  "decision": "run_arm_c | permanent_scope_limit",
  "rationale": "...",
  "arm_c_script": {"path": "...", "shared_paths_with_ab": true, "seed": "...", "replications": 0},
  "codex_script_review": {"verdict": "...", "report": "storage/ops/codex_reviews/k1623_armC_script_review.md"},
  "compute_queue": {"enqueued": true, "job_id": "...", "result_artifact": "..."},
  "frozen_fields_untouched": {"verified_by": "flatten-diff", "changed": 0, "removed": 0},
  "verdict_template_regenerated": true,
  "commits": ["<sha>"]
}
```
