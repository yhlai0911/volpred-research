# K1257 — Bayesian Model Averaging (BMA) Volatility Forecast

- **Experiment ID**: `k1257`
- **Status**: **done**（executed 2026-04-20；runtime 343.8s, 3 assets, 6 models, 2020-2026 OOS）
- **Created At**: 2026-04-20T01:40:00+08:00
- **Executed At**: 2026-04-20T09:55:00+08:00
- **Proposer**: Claude (novelty-quota backlog from `research_program.md` 面向 A「Under-explored methodologies」)
- **Executor**: Claude agent

## 問題描述

K500+ pairwise DM tests 已大量累積，每次比較兩個模型（GARCH / GJR / EGARCH / TARCH / RealGARCH 等）。但**沒有單一模型 universally 最優**（K593 Cross-OOS 已 confirmed regime-dependent），pairwise 比較總有 edge-case inversion。

**Bayesian Model Averaging (BMA)** 提供另一個框架：不是「選一個最好」而是 **posterior-weighted combination**，權重動態隨 predictive likelihood 更新。

## 動機（Why this experiment）

1. **真正的 regime-adaptive**：K593 verdict 是「no universal winner, regime-dependent」—BMA 的 posterior 自動隨 regime 移動權重，不需 ex-ante 手動 regime 判斷
2. **避免 single-model risk**：當 GJR 在 crisis regime fail 時，BMA 自然降低其權重，不需人工切換
3. **對照現有 ensemble**：K482 已測過 MCS-weighted ensemble（equal weight 勝 MCS）— BMA 理論上更 principled（full posterior 而非只保留 survivors）
4. **Feed coverage = 0**（per `docs/topic_diversity_audit.md` 2026-04-19 novelty-quota 候選）

## 方法

### 候選模型集合

7 個 univariate variance specs (same as K1002 pipeline):
- GARCH(1,1) Normal
- GJR(1,1,1) Normal
- GJR(1,1,1) Student-t
- EGARCH(1,1) Normal
- HAR-RV (HAR of realized 5-min vol; if daily only, use |r|)
- A4f-VIX² (asset-matched IV for SPY)
- Realized GARCH (if 5-min data available)

### BMA 公式

每時點 $t$ 的 posterior weight 透過 predictive likelihood 更新：
$$w_{i,t+1} \propto w_{i,t} \cdot p(y_{t+1} | M_i, \mathcal{F}_t)$$

log-lik 用 normal / Student-t density evaluate。Rolling window 1250 天（~5 年）更新 posterior；refit 每 63 天 (quarter)。

### BMA forecast

$$\hat\sigma^2_{t+1}^{BMA} = \sum_i w_{i,t+1} \hat\sigma^2_{t+1}^{(i)}$$

### Benchmarks

- **GJR baseline** (最強 single-model): 應 BMA beat GJR QLIKE?
- **Equal weight**: 7 models 等權，K482 已知 beat MCS-weighted — BMA 應 beat equal weight?
- **Best-in-window** (oracle): rolling 1-year window 選 best model；unrealistic upper bound

## 預期結果

### H1 primary: BMA vs GJR baseline OOS

- **Null**: BMA QLIKE ≥ GJR QLIKE (BMA 不優於 single-best)
- **Alt**: BMA QLIKE < GJR QLIKE + Harvey |t| > 3 → PASS

### H2: BMA vs Equal weight

- **Null**: BMA weighting 對 QLIKE 無 marginal improvement vs equal weight
- **Alt**: BMA posterior weighting 顯著優於等權 (DM t > 3)

### H3: Regime-dependent weight 可解釋性

- 計算每個 regime（VIX <15 / 15-20 / 20-25 / >25）的 BMA weight 平均，看是否 vol-regime driven weight shift

## 資產與期間

- **資產**: SPY + GLD + 0050.TW（3-asset baseline）
- **期間**: 2010-01-04 ~ 2026-04-17（16 年）
- **IS**: 2010-2019 (~2520 天), **OOS**: 2020-2026 (~1620 天)

## 評估指標

- QLIKE（primary per research_program methodology）
- MSE 輔助
- Harvey (2016) |t| > 3.0 DM test
- 分 regime QLIKE（4 VIX buckets）

## Data sources

- `yfinance` SPY + GLD + 0050.TW + ^VIX daily (auto_adjust=False)
- 若有 5-min: `experiments/k526/data/`, `experiments/k886/data/`

## 實驗三件套

- [x] `README.md`（本檔）
- [x] `k1257_bma_volatility.py`
- [x] `k1257_results.json`
- [x] `k1257_weight_evolution.png`
- [x] `k1257_qlike_comparison.png`

## Results (executed 2026-04-20)

### Per-asset OOS QLIKE (2020-2026, n_oos≈1580)

| Asset | BMA | GJR-t (single best) | Equal-weight | DM BMA vs GJR-t | DM BMA vs Equal |
|-------|-----|---------------------|--------------|------------------|------------------|
| SPY | **-8.2274** | -8.1749 | -8.2044 | t=-3.40, p=0.0007, **Harvey PASS** | t=-1.36, p=0.17 |
| GLD | **-8.1812** | -8.0904 | -8.1371 | t=-3.38, p=0.0007, **Harvey PASS** | t=-2.69, p=0.007 |
| 0050.TW | -7.6790 | -7.6825 | **-7.6940** | t=+0.98, p=0.33 | t=+1.68, p=0.09 |

### Hypothesis verdicts

- **H1 (BMA beats GJR-t, Harvey |t|>3)**: **PARTIAL** — SPY + GLD PASS; 0050.TW FAIL (posterior concentrates on GJR-t so BMA≈GJR-t by construction)
- **H2 (BMA beats equal-weight, Harvey |t|>3)**: **FAIL** — no asset passes Harvey threshold; BMA only marginally beats equal on SPY/GLD (t≈-1.4 / -2.7), 0050.TW equal-weight actually wins point-estimate
- **H3 (regime-dependent weight shift)**: **FAIL** — posterior concentrates on 1 model per asset (A4f_IV2 for SPY/GLD, GJR-t for 0050.TW) and never reverses; weights are effectively regime-invariant

### Key findings (one-liner per hypothesis)

- H1: BMA PARTIAL — posterior correctly identifies IV-augmented A4f as superior for US/US-linked assets, but posterior concentration means BMA gain over GJR-t only when single best ≠ GJR-t.
- H2: BMA FAIL — no Harvey-significant gain over equal-weight; supports K482's "equal-weight ensemble puzzle" for SPY/GLD, and on 0050.TW equal-weight is numerically best.
- H3: Regime-adaptive weighting hypothesis rejected — cumulative likelihood update drives posterior to a single model within ~500 days and it never un-concentrates, so BMA ≠ regime-adaptive in this implementation.

### Interpretation

- Posterior concentration is a known feature of product-of-likelihood BMA updates: after ~n log-lik accumulations, the best model's weight → 1 exponentially. Forgetting factor / sliding-window posterior would be needed to preserve regime-adaptive behavior.
- A4f-IV² dominant on SPY/GLD confirms IV-augmented variance specs remain the workhorse — consistent with K1002 A4f-t being MCS-only-survivor.
- 0050.TW's VIX is actually SPY's VIX (no GVZ-equivalent for Taiwan); if a Taiwan-specific IV index (e.g. TAIEX VIX) were substituted, A4f might also dominate there.
- **Null result on H2/H3 is reported as-is per research-honesty principle**; H1 PARTIAL is the headline.

### Research-program linkage

- Confirms K482 "equal-weight beats MCS-weighted" generalizes to Bayesian posterior weighting: BMA does not dominate equal-weight on OOS QLIKE.
- Adds to K593 "no universal winner" — BMA's attempted regime-adaptive weighting fails because standard BMA cannot forget, so it cannot track regimes.

### Methodology notes

- 6 models (Realized-GARCH excluded — no 5-min data for these 3 assets)
- Rolling window W=1250, refit every 63 days, seed=42
- BMA posterior updated via `log w_{t+1} = log w_t + log p(y_t | M_i, F_{t-1})` with logsumexp normalization
- Harvey (2016) corrected DM t-stat, |t|>3 threshold
- Full raw results: `k1257_results.json`
- Charts: `k1257_weight_evolution.png` (posterior weight paths by asset), `k1257_qlike_comparison.png` (QLIKE bars + DM t-stat bars)

## 相關 K

- **K593** Cross-OOS regime-dependent（motivation）
- **K482** MCS-weighted ensemble（prior art）
- **K1002** 7-model pipeline（候選模型集同源）
- **K1074** Statistical edge ≠ Sharpe edge（注意結果要同時看 Sharpe 層級）

## Random seed

**42**

## 防錯檢查清單

- [ ] Lag discipline: signal shift(1), return at t
- [ ] Rolling vs expanding window 明訂（此文件: rolling 1250）
- [ ] Refit frequency 一致（63 天 quarter）
- [ ] 避免 lookahead: 第 t 期 posterior 只用到 t-1 及以前的 likelihood
- [ ] ADF unit root pre-check on returns
- [ ] Student-t df MLE 固定 or estimated 明訂

## Open questions

- Prior weight: uniform 1/7 or informed from K482 findings?
- BMA log-lik 的 numerical stability（log-sum-exp trick 必要）

## 等候 Codex 04-24 wake 執行 or 主線程手動跑

此 K-next spec 為 novelty-quota backlog 具體化 — feed-coverage 0 topic。寫 script + run 是下一步，預計 30-60 min runtime（7 model × 2520 IS fit + 63 天 refit）。
