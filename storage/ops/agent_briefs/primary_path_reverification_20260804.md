# 三份實驗 primary-path 複驗（2026-08-04）

## K1746 — Codex primary path, VERDICT PASS, AGREES_WITH_FALLBACK yes
逐項 1-6 全 PASS，附 file:line 證據。新增兩個 residual risk（fallback 未提出）：
- 調整後 dict 插入順序由 p-sorted 變成呼叫者順序；現有 consumer 順序不敏感，但未來不可把 .items() 當 Holm rank
- canonical helper 是 import 依賴，不含在 K1746 的 entrypoint hash / declared inputs 內；本次未變更，但 transitive research-code identity 未被 pin

## K1747 — Codex 額度用盡（Aug 8 恢復）；改以 Codex 用的銳化 brief 交 agy 針對性複審
VERDICT FAIL，AGREES_WITH_FALLBACK yes，且解決了原本懸而未決的問題：
- B1 成立，並定位到機制：decide_verdict() 用 |0.287-0.05| < |0.301-0.05| - 0.01 的相對 1 個百分點門檻，
  完全不檢查替代程序本身是否 size-calibrated。於是 28.7%（名目 5.7 倍）被判成「更接近名目」。
- B2 成立，且三選一有答案：**README 因果敘述是錯的**，不是程式標反。a3_status 標籤數學上正確
  （log-space LS 最小化 se_log、Gamma deviance 最小化 QLIKE）；資料顯示 QLIKE 無論 A3 成立與否都貼名目
  （0.047-0.050），se_log 無論 A3 成立與否都失真（0.086-0.094）。A3 根本不是驅動因子。
- 新增：tables/ 也未追蹤（我原先只標了 figures/）
- 新增：experiment_gates.py 的 kid 正則只匹配小寫 k → 88 個大寫 K 實驗靜默跳過 registry 檢查（已獨立確認並開單）

## K1735 — 未執行 primary-path。Codex 額度用盡，且 agy 已審過同一份 bytes，重跑同一 reviewer 不產生新資訊。
仍欠 Codex 複驗（Aug 8 後）。

## 我的錯誤
K1747 第一次 Codex 執行可能已產出裁決，被我用 grep -A40 '^VERDICT:' 管線截掉且未存檔而丟失，
白燒約 10 萬 token 額度。之後改為先落檔再解析。

## Codex K1746 原文
```
(brief 見 scratchpad)
```
## agy K1747 針對性複審原文
```
VERDICT: FAIL
AGREES_WITH_FALLBACK: yes
B1_HOLDS: yes -- Under D2 (`D2_R250_p20`), `dm_expanding_pi1` rejects at 30.1% and `ep_split_pi025` rejects at 28.7% (Wilson CI [0.2598, 0.3158]), which is ~5.7x nominal 0.05. This reading of the data is exact. Calling 28.7% "closer to nominal" (due to `decide_verdict()` thresholding `|0.287 - 0.05| < |0.301 - 0.05| - 0.01`) does not satisfy the substantive requirement of a supported learner-aware fix. D2 tests nested models (HAR inside LASSO under $H_0^{pop}$), where parameter estimation noise introduces a downward shift in loss differentials (Clark & West 2007). Neither expanding DM nor EP-split is size-calibrated for nested models; EP-split remains severely mis-sized at 28.7%, making the POSITIVE gate verdict invalid.
B2_HOLDS: yes -- In `K1747_results.json` under design `D4_a3_alignment` (scheme `dm_expanding_pi1`):
  - `D4_ls_log`, `se_log`: rate 0.086, `excludes_nominal`=True, `a3_status`=`holds_exactly`
  - `D4_ls_log`, `qlike`: rate 0.050, `excludes_nominal`=False, `a3_status`=`violated`
  - `D4_gamma_level`, `se_log`: rate 0.094, `excludes_nominal`=True, `a3_status`=`violated`
  - `D4_gamma_level`, `qlike`: rate 0.047, `excludes_nominal`=False, `a3_status`=`holds_exactly`
Which explanation is right: **The README causal story is wrong.** The `a3_status` labels in `K1747.py` (`A3_STATUS` dict) are mathematically correct (log-space least squares minimizes `se_log`; Gamma deviance minimizes QLIKE). However, the README narrative (§6.2 / lines 202–211) asserts that violating A3 under QLIKE drives spurious DM rejections. The D4 simulation evidence directly contradicts this story: QLIKE sits on nominal (~0.047–0.050) regardless of whether A3 holds or is violated, whereas `se_log` is distorted (~0.086–0.094) regardless of A3 status.
OTHER_BLOCKING_DEFECTS:
- Untracked claim surface artifacts: `figures/mc_size_by_cell.png`, `figures/size_vs_a4_rate.png`, and `tables/` are untracked (`??`) in the worktree git status.
RESIDUAL_RISKS:
- Gate logic vulnerability: `decide_verdict()` relies on a raw 1 percentage point delta check without verifying whether the alternative procedure is actually size-calibrated (CI covering nominal 0.05) or whether the underlying comparison is nested.
- Upper-case K registration mismatch: `experiment_gates.py` regex `k(\d+)` only matches lower-case `k1747`, bypassing automatic reservation checks for `K1747`.
```
