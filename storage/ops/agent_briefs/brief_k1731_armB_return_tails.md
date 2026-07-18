# K1731 — GEVReg-MIDAS-SSVS arm B：報酬尾部分位數預測（老闆指派 assign_c55b0d66）

**Model**: opus / xhigh (per model_router, task_type=experiment)

## 來源與定位

老闆 Telegram msg 946/947（2026-07-18）：「既然模型都要樣本內估計與樣本外預測了，除了波動預測，報酬也可以做，然後看結果如何再看要寫什麼」。

Arm A（K1730，波動率區間預測）框架已完成並通過驗證，程式碼在
`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-558d7893-k1730/experiments/k1730/`
（`k1730_data.py` / `k1730_models.py` / `k1730_scoring.py` / `k1730_gevreg_midas_ssvs.py`）。

**Arm A 的實際結論是 NULL（甚至負向）**，你必須先讀懂再開工，否則會重蹈覆轍：
- OOS 2008-01-07 → 2026-07-13，967 個週度 block，19 次年度 refit。
- mean pinball：GEVReg-MIDAS-SSVS **0.11419** vs GEV-HAR 0.11224 vs HAR-QR 0.11201 → **加總經反而更差**。
- DM vs GEV-HAR t=2.13（p=0.033，favours benchmark）；Harvey 修正後 `harvey_significant=false`。
- Permutation test 是關鍵證據：把總經張量跨週打亂後 pinball **0.11208 < 0.11419（真資料）**，
  即「打亂的總經比真總經還好」→ 總經在 OOS 沒有增量訊息，SSVS 的高 PIP（VIX 0.82 / CPI 0.61）
  是樣本內選擇的產物，不是可外推的預測力。

**因此 arm B 的先驗是「大概率也是 null」**。這不是失敗，是有效結論 —— 報酬可預測性弱是既有共識。
你的任務是做出**能站得住腳的 null**（或站得住腳的 non-null），不是想辦法弄出漂亮數字。
任何「調到有顯著為止」的行為都是造假。

## 範圍

沿用 arm A 的 GEV-MIDAS-SSVS 引擎，換被解釋變數：**不做報酬點預測**（R² 天生近 0，直接做等於預設 null），
改做**報酬分配的尾部分位數 / 下檔風險區間預測**。

- 目標：週頻 SPY 報酬的左尾（以週內最大跌幅 block minima 取負號 → block maxima，可直接沿用 GEV）
  或週報酬的低分位數。兩種擇一，在報告裡說明選擇理由與對應的經濟問題。
- Predictors：與 arm A 相同的 point-in-time 月頻總經（ALFRED first-release：CPI / NFP / IP / UNRATE）
  + 市場變數（VIX / TERM），MIDAS beta 權重壓成週頻。**必須沿用 arm A 的 vintage 對齊邏輯**（`k1730_data.py`），
  不得改用參考月對齊。
- Baselines：歷史分位數（Empirical）、GARCH-t VaR、quantile HAR（HAR-QR）、無總經的 GEV-HAR。
- 評分：VaR backtest（Kupiec UC + Christoffersen IND/CC + DQ test）、pinball loss、ES（expected shortfall）。
- 經濟意義口徑：避險 / 部位規模（HE / VaR / Utility），**不比 Sharpe**（見 memory `feedback_hedging_vs_trading`）。
- 樣本內估計 vs rolling OOS 嚴格分離、明確 lag、固定 seed=42。
- **必做 permutation test**（同 arm A）：打亂總經後重估，若 shuffled 不比 real 差 → 明確寫「總經無增量訊息」。

## 從 arm A 驗證報告繼承的技術債（開工前必讀）

主線程已對 arm A 做完獨立驗證，以下是**你會原樣繼承的問題**，必須先處理再往前推：

1. **SSVS sampler 沒收斂 — 這是 arm A 最嚴重的缺陷。** quick 設定下 19 次 refit 有 **11 次 R-hat > 1.1**，
   最差 R-hat=3.21、ESS_min=3.0（n_kept=1200）、兩鏈 PIP 差距達 0.94。
   **在這個狀態下報告的 PIP 沒有統計意義**，而 code 沒有任何 gate 阻止未收斂的 refit 進入預測。
   → arm B **必須加 convergence gate**：R-hat > 1.1 或 ESS < 100 的 refit 要標記，且不得用其 PIP 下任何敘述。
   → 建議先修 `k1730_models.py:641-659` 的 block-2 proposal 調適（macro 係數逐一更新、adapt 只在 burn-in），
     再移植。把未收斂的 sampler 跑更多 draws 只是把問題跑久一點。
2. **quick vs production 已實測**：`selected_omega` 與 `xi` 完全不受 MCMC 長度影響（deterministic MLE），
   但 PIP 平均絕對差 0.096、最大 0.36，**72 個 cell 中有 11 個跨過 0.5 納入門檻**。
   → 任何 PIP 敘述都必須用 production 設定產出，不得用 quick 結果下結論。
3. **多重比較未處理**：arm A 主表 4 個 DM + 子樣本 16 個 = 20 次檢定全是 raw p-value，
   唯一守門是 ad-hoc 的 `|t| > 3.0`。arm B 要用 Holm 或 Romano-Wolf（或 MCS），並明講方法。
4. **CRPS 缺項**：arm A 只有 13 個 tau 的 mean pinball（CRPS 的離散近似），沒有真 CRPS。arm B 請補上。
5. **reproducibility 缺口**：arm A 的 results.json 早於現行 code（缺 `pit` 欄位與 fig4），
   用現行 code 重跑不會得到同結構。arm B **交件前必須確認 results.json 是現行 code 的產物**。
6. **likelihood 要換，不要照搬 GEV**：GEV 對 arm A 的 block maxima 是正確分布；報酬尾部分位數不是 block maximum，
   直接套 GEV 是誤用。請用 POT/GPD（threshold exceedance）或 skew-t，並說明選擇理由。
   若改用「週內最大跌幅取負號」的 block minima 口徑，GEV 才適用 — 兩條路擇一，講清楚。
7. **可直接重用的資產**（arm A 留下最有價值的部分）：`k1730_data.py` 的 ALFRED PIT 層
   （`fetch_first_release` / `build_monthly_macro` / `build_midas_lag_tensor` / `assert_no_lookahead`）
   整段照用即可，只要餵含 `origin` / `block_start` / `block_end` 三欄的 weeks frame。
   `beta_weights` / `midas_aggregate` 完全泛型。
   但 `ssvs_gev` 的 `log_post` 硬呼叫 `gev_reg_nll`、`ssvs_predictive_quantiles` 硬呼叫 `gev_cdf`，
   要重用必須把 nll / cdf 改成注入的 callable；`_unpack` 的參數佈局 `[beta, phi0, phi1, xi]` 也硬編在三處。

## 硬性要求

1. **Lookahead 檢查要機械化**，沿用 arm A 的三道 check（macro_released_before_origin /
   origin_before_block_start / blocks_non_overlapping），並把 violations 計數寫進 results.json。
2. **多重比較**：對多個 baseline 做 DM 時報告 Harvey 小樣本修正與族錯誤率處理，不要只挑最好看的 p 值。
3. **MCMC 診斷**：多鏈 R-hat / ESS 要有數字；不要只給 PIP。
4. **結果 JSON 落在** `experiments/k1731/k1731_gevreg_midas_ssvs_returns_results.json`，
   含 config、data_sources、lookahead_checks、sample、refits、oos（by_model / dm_tests / subperiods）、
   permutation_test、figures、runtime_seconds。欄位結構比照 arm A 以便交叉比對。
5. **production 設定要真的跑完**（arm A 的教訓：agent 在 job 結束前才啟動全量跑，結果被截斷、
   交出去的是 quick-mode 產物）。**先跑 quick 驗流程，確認無誤後把全量跑放在時間預算的前段**，
   不要留到最後。若時間不足，寧可縮小 OOS 起點也要交出完整、標示清楚的結果。
6. **禁止**假數字、禁止把 in-sample 當 OOS、禁止在沒有 permutation/baseline 對照下宣稱總經有預測力。
7. 圖：至少 (a) rolling VaR 違反率、(b) SSVS PIP 熱圖、(c) 預測尾部 vs 實現報酬。

## 交付

- `experiments/k1731/` 完整程式碼 + results JSON + 圖。
- 一份 `experiments/k1731/README.md`：3 段內講完「問了什麼 / 做了什麼 / 結論是什麼（含 null 就寫 null）」，
  並明確對照 arm A 的結論。
- **不要自己寫 knowledge.json**（K1259 規則），由主線程收件時寫。
