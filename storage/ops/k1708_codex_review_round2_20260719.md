# K1708 Codex primary-path re-review (round 2) — 2026-07-19

- **Reviewer**: `codex exec` (read-only, bounded 1500s, via `scripts/codex_exec_bounded.sh`)
- **Subject**: post-fix bytes at worktree `dispatch-slot-2-8dda242d-k1708`, commit `cd135b00e`
- **Prior round**: `storage/ops/k1708_codex_review_20260717.md` (VERDICT: FAIL, 3 BLOCKERs)
- **This round**: **VERDICT: FAIL** — worktree NOT merged, no knowledge.json write of a merged result.
- **Independent checks by main thread**: `pytest experiments/k1708/test_k1708.py -q` → 35 passed (115.7s); no `*.quick.*` artifacts remain; `experiments/k1708/` absent from `main` (confirms BLOCKER-3 premise).

---

1. **FAIL — gate 條件有綁定，但「整體 gate 是嚴格子集」不成立。**

   `assess_market()` 確實要求 exact flag、`t>=3`、Holm、QLIKE `<0`、MCS membership、兩個 regime 同號，缺一即失敗（`K1708.py:2174-2193`）。`t>=3` 本身也確實是 `t>1.645` 的嚴格子集。

   但新舊門檻套在不同比較上：新 gate 使用 own-restriction（`K1708.py:1513`），舊 gate 使用 HAR_FIXED（現為描述性，`K1708.py:1560-1561`）。因此可能有 `t_own>=3`、同時 `t_fixed<=1.645`；不能由臨界值子集推出整體 gate 不會把舊 NULL 轉正。README §8.2 的結論過度宣稱（`README.md:292-293`）。

   此外 verdict 只信任 payload 的 `exact_on_scored_object` 與 `holm.reject`，沒有核對 `control_series` 是否等於 registry，也沒有重算 Holm（`K1708.py:2176-2182`）。實測把 control 改成 `HAR_FIXED` 但保留 exact flag，仍得到 `CONDITIONAL_PASS`。

2. **PASS — Holm 實作正確且正常生產路徑有使用。**

   `holm_bonferroni()` 依 p-value 遞增排序，以 `α/(m-rank)` step-down，第一次失敗後全部停止拒絕（`K1708.py:1449-1462`）。`evaluate()` 對 exactly-nested family 的單尾 CW p-values計算並附回每列（`K1708.py:1524-1529`），`assess_market()` 要求 `holm.reject=True`（`K1708.py:2180`）。

3. **PASS — 生產路徑的 nesting 已實質修正。**

   Registry 為三個模型指定獨立 control（`K1708.py:1283-1302`）。`HAR_S_BM_AT_SIGMA_ETA_ZERO` 由原 HARSL hyperparameters 複製後將 `sig2_eta=0`，再直接呼叫 `forecast_harsl()`（`K1708.py:1893-1907`），不是 `forecast_ols_block()`。

   `cw_vs_benchmark_primary` 不存在於現行 executable code；HAR_FIXED 比較只寫入 `cw_vs_fixed_descriptive_not_nested`（`K1708.py:1550-1569`）。但第 1 項所述 metadata 驗證缺口仍允許人工「重新貼標」後進 verdict。

4. **PASS — regime 使用同一 nested pair。**

   每個 regime 的 `qlike_vs_own_restriction` 與 CW 都使用 registry control（`K1708.py:1664-1683`）；verdict 讀取同一欄位並要求至少兩個 regime 全為負（`K1708.py:2160-2189`）。

5. **FAIL — NULL 保持不變，但「結果檔未動」無法由 Git 證明。**

   `K1708_results.json` 內原 verdict 是 `NULL`，目前 `derive_verdict()` 仍回 NULL；agent claim 的 `A_verdict_label_after_fix` 也是 `NULL`。

   然而 `cd135b00e^` 完全沒有 `experiments/k1708/`；commit 將 `K1708_results.json` 以新增檔提交，diff 是 `1768 insertions`。因此 Git diff 觸及全部 stored numbers，沒有可比較的 pre-fix blob/hash。舊 code trace、mtime 和先前 review 敘述只能提供旁證，不能驗證「每個數字 untouched」。

6. **FAIL — 35/35 通過，但數個新測試不具 pre-fix 鑑別力。**

   唯讀模式實跑結果：`35 passed in 111.14s`。`test_codex_minimal_payload_does_not_return_supported` 確實會咬住原假陽性。

   但以下測試在 pre-fix logic 也會通過：

   - `test_stored_full_sample_verdict_is_still_null`：舊 verdict 本來就是 NULL，而且結果檔不存在時會 skip（`test_k1708.py:610-622`）。
   - `test_gate_holds_the_pre_registered_t_bar`：fixture 只提供新欄位，舊 derive 忽略後同樣返回 NULL（`test_k1708.py:535-541`）。
   - `test_inexact_nesting_flag_is_load_bearing`：同樣可因舊 logic 不讀新欄位而假通過（`test_k1708.py:544-548`）。
   - `test_regime_consistency_needs_both_regimes_scored`：亦只斷言 NULL，舊 logic 不讀 regime 即可通過（`test_k1708.py:581-585`）。

   Registry 測試也只驗證名稱與 boolean，沒有呼叫實際 forecast generator（`test_k1708.py:625-640`）。

7. **PASS — 沒有 quick artifact 殘留。**

   找不到 `K1708_results.quick.json`、quick PNG、quick CSV 或 `.tmp`。正式結果仍標示 `quick_mode=false`。

8. **PASS — README 已誠實撤回。**

   §8.1–8.2 明確承認 HAR_FIXED 不精確 nested，以及先前 `t>1.645`、無 multiple-testing correction 是缺陷（`README.md:228-294`）。§12 明確推翻先前「不改推論設計」的處置（`README.md:399-408`）。§15 亦揭露現行程式與 stored result code trace 不一致（`README.md:527-547`）。

BLOCKER-1: 新舊 gate 使用不同 comparator，故 `t>=3 ⊂ t>1.645` 無法證明整體 gate 不會把舊 NULL 轉正 :: experiments/k1708/K1708.py:1513,1560-1561  
BLOCKER-2: verdict 未核對 registry control 身分或重算 Holm，錯誤比較只要重新貼上 exact/reject 標籤仍可通過 :: experiments/k1708/K1708.py:2176-2182  
BLOCKER-3: commit 將完整 results 檔列為新增，沒有 pre-fix Git blob，因而無法驗證 stored numbers untouched :: experiments/k1708/K1708_results.json:1  
BLOCKER-4: 多個號稱 gate/nesting regression 的新測試在 pre-fix logic 也會返回 NULL 而通過 :: experiments/k1708/test_k1708.py:535-548  
VERDICT: FAIL
tokens used
140,183
1. **FAIL — gate 條件有綁定，但「整體 gate 是嚴格子集」不成立。**

   `assess_market()` 確實要求 exact flag、`t>=3`、Holm、QLIKE `<0`、MCS membership、兩個 regime 同號，缺一即失敗（`K1708.py:2174-2193`）。`t>=3` 本身也確實是 `t>1.645` 的嚴格子集。

   但新舊門檻套在不同比較上：新 gate 使用 own-restriction（`K1708.py:1513`），舊 gate 使用 HAR_FIXED（現為描述性，`K1708.py:1560-1561`）。因此可能有 `t_own>=3`、同時 `t_fixed<=1.645`；不能由臨界值子集推出整體 gate 不會把舊 NULL 轉正。README §8.2 的結論過度宣稱（`README.md:292-293`）。

   此外 verdict 只信任 payload 的 `exact_on_scored_object` 與 `holm.reject`，沒有核對 `control_series` 是否等於 registry，也沒有重算 Holm（`K1708.py:2176-2182`）。實測把 control 改成 `HAR_FIXED` 但保留 exact flag，仍得到 `CONDITIONAL_PASS`。

2. **PASS — Holm 實作正確且正常生產路徑有使用。**

   `holm_bonferroni()` 依 p-value 遞增排序，以 `α/(m-rank)` step-down，第一次失敗後全部停止拒絕（`K1708.py:1449-1462`）。`evaluate()` 對 exactly-nested family 的單尾 CW p-values計算並附回每列（`K1708.py:1524-1529`），`assess_market()` 要求 `holm.reject=True`（`K1708.py:2180`）。

3. **PASS — 生產路徑的 nesting 已實質修正。**

   Registry 為三個模型指定獨立 control（`K1708.py:1283-1302`）。`HAR_S_BM_AT_SIGMA_ETA_ZERO` 由原 HARSL hyperparameters 複製後將 `sig2_eta=0`，再直接呼叫 `forecast_harsl()`（`K1708.py:1893-1907`），不是 `forecast_ols_block()`。

   `cw_vs_benchmark_primary` 不存在於現行 executable code；HAR_FIXED 比較只寫入 `cw_vs_fixed_descriptive_not_nested`（`K1708.py:1550-1569`）。但第 1 項所述 metadata 驗證缺口仍允許人工「重新貼標」後進 verdict。

4. **PASS — regime 使用同一 nested pair。**

   每個 regime 的 `qlike_vs_own_restriction` 與 CW 都使用 registry control（`K1708.py:1664-1683`）；verdict 讀取同一欄位並要求至少兩個 regime 全為負（`K1708.py:2160-2189`）。

5. **FAIL — NULL 保持不變，但「結果檔未動」無法由 Git 證明。**

   `K1708_results.json` 內原 verdict 是 `NULL`，目前 `derive_verdict()` 仍回 NULL；agent claim 的 `A_verdict_label_after_fix` 也是 `NULL`。

   然而 `cd135b00e^` 完全沒有 `experiments/k1708/`；commit 將 `K1708_results.json` 以新增檔提交，diff 是 `1768 insertions`。因此 Git diff 觸及全部 stored numbers，沒有可比較的 pre-fix blob/hash。舊 code trace、mtime 和先前 review 敘述只能提供旁證，不能驗證「每個數字 untouched」。

6. **FAIL — 35/35 通過，但數個新測試不具 pre-fix 鑑別力。**

   唯讀模式實跑結果：`35 passed in 111.14s`。`test_codex_minimal_payload_does_not_return_supported` 確實會咬住原假陽性。

   但以下測試在 pre-fix logic 也會通過：

   - `test_stored_full_sample_verdict_is_still_null`：舊 verdict 本來就是 NULL，而且結果檔不存在時會 skip（`test_k1708.py:610-622`）。
   - `test_gate_holds_the_pre_registered_t_bar`：fixture 只提供新欄位，舊 derive 忽略後同樣返回 NULL（`test_k1708.py:535-541`）。
   - `test_inexact_nesting_flag_is_load_bearing`：同樣可因舊 logic 不讀新欄位而假通過（`test_k1708.py:544-548`）。
   - `test_regime_consistency_needs_both_regimes_scored`：亦只斷言 NULL，舊 logic 不讀 regime 即可通過（`test_k1708.py:581-585`）。

   Registry 測試也只驗證名稱與 boolean，沒有呼叫實際 forecast generator（`test_k1708.py:625-640`）。

7. **PASS — 沒有 quick artifact 殘留。**

   找不到 `K1708_results.quick.json`、quick PNG、quick CSV 或 `.tmp`。正式結果仍標示 `quick_mode=false`。

8. **PASS — README 已誠實撤回。**

   §8.1–8.2 明確承認 HAR_FIXED 不精確 nested，以及先前 `t>1.645`、無 multiple-testing correction 是缺陷（`README.md:228-294`）。§12 明確推翻先前「不改推論設計」的處置（`README.md:399-408`）。§15 亦揭露現行程式與 stored result code trace 不一致（`README.md:527-547`）。

BLOCKER-1: 新舊 gate 使用不同 comparator，故 `t>=3 ⊂ t>1.645` 無法證明整體 gate 不會把舊 NULL 轉正 :: experiments/k1708/K1708.py:1513,1560-1561  
BLOCKER-2: verdict 未核對 registry control 身分或重算 Holm，錯誤比較只要重新貼上 exact/reject 標籤仍可通過 :: experiments/k1708/K1708.py:2176-2182  
BLOCKER-3: commit 將完整 results 檔列為新增，沒有 pre-fix Git blob，因而無法驗證 stored numbers untouched :: experiments/k1708/K1708_results.json:1  
BLOCKER-4: 多個號稱 gate/nesting regression 的新測試在 pre-fix logic 也會返回 NULL 而通過 :: experiments/k1708/test_k1708.py:535-548  
VERDICT: FAIL
