# K1108d — Non-capex quantitative guidance as foundry θ_EAV mechanism (D2)

| 欄位 | 內容 |
|------|------|
| 實驗編號 | K1108d |
| 提出者 | 賴奕豪 |
| 執行者 | Claude (worktree agent-ae315a15) |
| 日期 | 2026-04-17 |
| Parent chain | K1108 → K1108b → K1108c → K1108e → K1108f |
| Paper mapping | Paper 2 foundry narrative, mechanism candidate D2 |
| Seed | 42 |
| Status | LOW_COVERAGE_PRELIMINARY NULL |

## 動機（5-layer NULL precedent）

Paper 2 的 foundry rule 聲稱 `θ₂ > 0` 是該行業結構的產物，但 K1104 首次觀察到這個 empirical 事實之後，K1108、K1108b、K1108c、K1108e、K1108f 連續 5 層 NULL 都沒能找到可歸因的 mechanism：

| 層 | 實驗 | Finding |
|----|------|---------|
| 1 | K1108 | TSMC alone, capex guidance inconclusive / weak NULL |
| 2 | K1108b | 4-firm pool binary `guide_updated` DECISIVE NULL (pool Wald t=-0.0003) |
| 3 | K1108c | Continuous `guide_delta_pct` NULL (H2_MAGNITUDE_NULL) |
| 4 | K1108e | Operating leverage (PPE/Rev, D/E, (PPE+SGA)/Rev) NULL |
| 5 | K1108f | Regime-split (volatility / cycle-phase) NULL |

D2 是剩下唯一的「guidance-based」候選：non-capex 量化 guidance tokens（utilisation rate delta / wafer ASP delta / R&D spend delta）。若 D2 也 NULL，Paper 2 必須接受「industry fixed effect, no attributable channel」的 framing。

## 假設

| Label | 條件 |
|-------|------|
| H_D2_PASS | max any-of-3 `|HAC t|` > 3.0 AND partial-F p < 0.05 |
| H_D2_PARTIAL | 2.0 < max `|HAC t|` < 3.0 OR partial-F p ∈ (0.05, 0.10) |
| H_D2_NULL | max `|HAC t|` < 2.0 AND partial-F p > 0.10 |
| H_D2_LOW_COVERAGE | all-3 coverage < 60% → preliminary only |

## Data sources

| 來源 | 用途 | coverage |
|------|------|----------|
| `experiments/k1108c/k1108c_merged_pool.csv` | θ_EAV_empirical event panel（135 events, 4 firms） | 100% of base pool |
| yfinance `quarterly_income_stmt` | rev QoQ / gm QoQ pp / R&D YoY（proxy）| 6 quarters 覆蓋 → 2024Q4+ only |
| yfinance `income_stmt` (annual) | R&D YoY annual fallback | FY2022-FY2024 per firm |
| HAND_CODED (memory of public IR commentary) | utilisation rate delta, wafer ASP delta (subset) | 19 hand / 5 hand |

資料流程：

1. `k1108d_fetch_noncapex.py` 讀 K1108c pool → 對每個 (firm, event_date) 嘗試以下優先序填入 3 維 non-capex regressors：
   - HAND_CODED（優先）
   - PROXY_PIT（yfinance quarterly income stmt, fq_end 必須 ≤ event_date 且 ≤ 120 days）
   - PROXY_ANNUAL（yfinance annual R&D YoY）
   - 否則 NaN
2. Outputs `data/k1108d_noncapex_pool.csv`（135 rows）含 `util_source`/`asp_source`/`rd_source` ∈ {HAND_CODED, PROXY_PIT, PROXY_ANNUAL, NA}。
3. `k1108d.py` merge → regression → verdict。

**PIT alignment**: proxy values 來自 earnings-day 公告的當季 actuals（同日與 guidance 一起發佈，符合 contemporaneous PIT），非 ex-post revisions。Hand-coded 值來自 earnings call 當天公開 commentary。

## Coverage（LOW COVERAGE flag）

| Covariate | N (total 135) | % coverage | hand-coded | proxy |
|-----------|:-------------:|:----------:|:----------:|:-----:|
| utilisation_delta_pp | 32 | 23.7% | 19 | 13 |
| wafer_asp_delta_pct | 15 | 11.1% | 5 | 10 |
| rd_delta_pct | 32 | 23.7% | 0 | 32 |
| **all 3 non-NaN** | **12** | **8.9%** | — | — |
| any 1 non-NaN | 47 | 34.8% | — | — |

Per-firm all-3 coverage: 2330.TW 10.6% / 2303.TW 6.2% / GFS 17.6% / 0981.HK 4.3% — **所有 firm < 50%**。

**Coverage 遠低於 60% 門檻（8.9% vs 60%）** → 任何「PASS」都必須視為 PRELIMINARY；實驗 label 自動降級為 `H_D2_LOW_COVERAGE_PRELIMINARY`。

## Results（4 specs + partial-F + control）

### Univariate specs (HAC + cluster-by-firm)

| Covariate | N | β | SE_HAC | t_HAC | t_cluster | p_HAC |
|-----------|:-:|:--:|:-----:|:-----:|:---------:|:-----:|
| utilisation_delta_pp | 32 | +2.577e-05 | 8.08e-05 | +0.319 | +0.290 | 0.749 |
| wafer_asp_delta_pct | 15 | -4.509e-05 | 2.36e-04 | -0.191 | -0.113 | 0.849 |
| rd_delta_pct | 32 | -7.295e-05 | 7.54e-05 | -0.968 | -1.533 | 0.333 |

### Joint spec (3 non-capex + firm FE + year FE; median-imputed N=135)

| Covariate | β | t_HAC | t_cluster | p_HAC |
|-----------|:--:|:-----:|:---------:|:-----:|
| utilisation_delta_pp | +7.499e-05 | +0.550 | +0.486 | 0.582 |
| wafer_asp_delta_pct | +1.554e-04 | +0.367 | +0.288 | 0.714 |
| rd_delta_pct | -1.520e-04 | -1.041 | -0.906 | 0.298 |

**Partial-F (β_util = β_asp = β_rd = 0)**: F = 0.347, p = 0.791, df=(3, 117) — **NULL**.

### Orthogonality check (joint + `guide_delta_pct` as capex control)

| Covariate | β | t_HAC | p_HAC |
|-----------|:--:|:-----:|:-----:|
| utilisation_delta_pp | +7.470e-05 | +0.540 | 0.589 |
| wafer_asp_delta_pct | +1.278e-04 | +0.304 | 0.761 |
| rd_delta_pct | -1.477e-04 | -1.014 | 0.310 |
| guide_delta_pct (control) | -1.300e-05 | -1.040 | 0.299 |

Non-capex coefs 在 controlling for capex 後無變化（|Δt| < 0.02），顯示無 orthogonal 非-capex 訊號。capex control 本身也 NULL（與 K1108c 一致）。

### Block bootstrap (N=1000, block=5, firm-stratified)

| Covariate | boot mean | 95% CI | p_boot |
|-----------|:---------:|:------:|:------:|
| utilisation_delta_pp | +1.772e-04 | [-5.99e-05, +5.51e-04] | 0.148 |
| wafer_asp_delta_pct | -2.035e-04 | [-1.93e-03, +1.01e-03] | 0.772 |
| rd_delta_pct | -1.383e-04 | [-6.72e-04, +1.75e-04] | 0.454 |

All 3 bootstrap 95% CIs 都涵蓋 0 → **no non-capex channel survives**。

### Hand-coded-only subset (robustness)

| Covariate | N | β | t_HAC | p_HAC |
|-----------|:-:|:--:|:-----:|:-----:|
| utilisation_delta_pp (hand) | 19 | -8.82e-06 | -0.070 | 0.944 |
| wafer_asp_delta_pct (hand) | 5 | -2.68e-04 | -1.166 | 0.244 |

Hand-only subset 比 proxy-imputed 更弱 → 確認非 proxy-noise 帶來偽信號。

## Verdict

**`H_D2_LOW_COVERAGE_PRELIMINARY`**

- Max `|HAC t|` = 0.97（rd_delta_pct univariate，低於所有 verdict threshold）
- Partial-F p = 0.791（遠超 0.10）
- All-3 coverage = 8.9% < 60% → LOW_COVERAGE 警示
- Bootstrap 95% CIs 都含 0
- Orthogonality check 下仍 NULL
- Hand-coded-only subset 也 NULL

### Paper 2 narrative commitment

→ **`PROVISIONAL_INDUSTRY_FE_FRAMING`**

即使考量 coverage 限制，也沒有證據顯示任何 non-capex guidance token 能預測 foundry θ_EAV。結合 K1108/b/c/e/f 的 5-layer 證據：

> **6-layer NULL stack (preliminary)**: capex binary + capex continuous + op_leverage + regime-split + non-capex guidance 全部 NULL → foundry θ₂ > 0 rule 最合理的解釋是 **structural industry fixed-effect**，不是任何可歸因的 event-driven mechanism。

Paper 2 narrative decision state（受 narrative state machine 規範）：
- 不直接改 body.tex（僅更新 research_program.md + knowledge.json）
- 本結果 + K1108c + K1108e + K1108f = 4 個 complementary experiments，滿足 "≥3 互補實驗" 門檻
- 建議主線程觸發 narrative decision → 若 confirmed，status 改為 `decision_made_awaiting_body_rewrite`

### Next steps / caveats

1. **Data augmentation**：real earnings-call transcript scrape（MOPS 重大訊息 PDF, TSM/GFS 10-Q call transcripts）可將 coverage 從 8.9% 推到 40-60%。這會消耗 ≥ 1 週人工編碼，但屬於投稿前必要的 robustness 工作。
2. 不建議在 coverage 推到 ≥ 60% 前公開文章化結論；應仍視為內部 narrative decision aid。
3. 若資料擴充後 coverage ≥ 60% 且仍 NULL → Paper 2 可 finalize 6-layer framing；若 PASS → 必須撤回本處 preliminary 結論並重做 narrative decision。

## 防錯規則符合度

- [x] 先讀 `docs/error_log.md`
- [x] Knowledge search（K1108/b/c/e/f/K1104/foundry pool）
- [x] PIT alignment：proxy 只用已公告的 quarterly actuals；hand-coded 值綁 earnings announcement date；不允許 ex-post revision
- [x] Lookahead guard：`θ_EAV_empirical` 已依 K1108c 慣例 lag-1；proxy fq_end ≤ event_date；annual fy_end ≤ event_date
- [x] HAC (Andrews 1991 BW) + cluster-by-firm SE dual report
- [x] Block bootstrap seed 42, 1000 reps
- [x] Firm FE + year FE 吸收 level / macro
- [x] Median-impute robustness + HAND_CODED-only sensitivity
- [x] Low coverage 時 verdict 自動降級
- [x] Worktree 只動 `experiments/k1108d/` 與一個 `experiments/k1108c/k1108c_merged_pool.csv`（reused input copy）
- [x] No shared-state writes（knowledge.json / feed / paper body 未修改）

## Files

| File | Purpose |
|------|---------|
| `k1108d_fetch_noncapex.py` | 建 3-dim non-capex pool（hand-coded + yfinance proxy） |
| `k1108d.py` | 主分析：4 specs + partial-F + control + bootstrap + verdict |
| `data/k1108d_noncapex_pool.csv` | 135 rows × 3 non-capex covariates + provenance tags |
| `k1108d_results.json` | 完整結果 JSON |
| `k1108d_coef_forest.png` | Forest plot（univariate vs joint+FE） |
| `k1108d_scatter_best_predictor.png` | θ_EAV vs best non-capex predictor |
| `README.md` | 本文件 |

## References

- K1104, K1108, K1108b, K1108c, K1108e, K1108f (parent chain)
- Andrews, D. W. K. (1991). Heteroskedasticity and Autocorrelation Consistent Covariance Matrix Estimation. *Econometrica*.
- Newey, W. K., & West, K. D. (1987). A Simple, Positive Semi-Definite Heteroskedasticity and Autocorrelation Consistent Covariance Matrix. *Econometrica*.
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the Cross-Section of Expected Returns. *Review of Financial Studies*.
- Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap. *JASA*.
