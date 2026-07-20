# K1257 — Bayesian Model Averaging (BMA) Volatility Forecast

- **Experiment ID**: `k1257`
- **Status**: **done**（executed 2026-04-20；runtime 369.6s per `k1257_results.json:runtime_seconds`, 3 assets, 6 models, 2020-2026 OOS）
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

**實作為 6 個** univariate variance specs（K1002 pipeline 的 daily-data 子集）:
- GARCH(1,1) Normal
- GJR(1,1,1) Normal
- GJR(1,1,1) Student-t
- EGARCH(1,1) Normal
- **HAR_ABS**（HAR on |r| proxy；無 5-min RV 資料，故非 HAR-RV）
- **A4f_IV2**（MF-GJR-X with asset-matched IV²：SPY `^VIX`²、GLD `^GVZ`²、0050.TW fallback `^VIX`²）

> Realized GARCH 原列入 spec，但這 3 檔資產無 5-min 資料，**未實作**（候選集 = 6，不是 7）。

### BMA 公式

每時點 $t$ 的 posterior weight 透過 predictive likelihood 更新：
$$w_{i,t+1} \propto w_{i,t} \cdot p(y_{t+1} | M_i, \mathcal{F}_t)$$

log-lik 用 normal / Student-t density evaluate。Rolling window 1250 天（~5 年）更新 posterior；refit 每 63 天 (quarter)。

### BMA forecast

$$\hat\sigma^2_{t+1}^{BMA} = \sum_i w_{i,t+1} \hat\sigma^2_{t+1}^{(i)}$$

### Benchmarks

- **GJR baseline** (最強 single-model): 應 BMA beat GJR QLIKE?
- **Equal weight**: 6 models 等權，K482 已知 beat MCS-weighted — BMA 應 beat equal weight?
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

- `yfinance` SPY + GLD + 0050.TW daily (auto_adjust=False)
- IV proxy（A4f_IV2 用）: SPY → `^VIX`、**GLD → `^GVZ`**、0050.TW → `^VIX`（fallback，無台股 IV index）
- `^VIX` 另作為 4-bucket regime 分類器，**所有資產共用**
- 若有 5-min: `experiments/k526/data/`, `experiments/k886/data/`

## 實驗三件套

- [x] `README.md`（本檔）
- [x] `k1257_bma_volatility.py`
- [x] `k1257_results.json`
- [x] `k1257_weight_evolution.png`
- [x] `k1257_qlike_comparison.png`

## Results (executed 2026-04-20)

### Per-asset OOS QLIKE (2020-2026, **common-sample**)

所有 headline QLIKE 皆在 BMA / Equal / GJR-t **共同有效日**（`n_common_sample`）上計算，與 Harvey t 出自同一樣本。

| Asset | n_common | BMA | GJR-t (single best) | Equal-weight | DM BMA vs GJR-t | DM BMA vs Equal |
|-------|----------|-----|---------------------|--------------|------------------|------------------|
| SPY | 1518 | **-8.1864** | -8.1358 | -8.1668 | t=-3.17, p=0.0015, **Harvey PASS** | t=-1.37, p=0.17 |
| GLD | 1581 | **-8.1812** | -8.0904 | -8.1371 | t=-3.38, p=0.0007, **Harvey PASS** | t=-2.69, p=0.007 |
| 0050.TW | 1524 | -7.6790 | -7.6825 | **-7.6940** | t=+0.98, p=0.33 | t=+1.68, p=0.09 |

SPY 的 GJR-t 有 63 個 invalid forecast days（1 次 non-converged refit × 63 天 refit block），故 `n_common=1518 < n_oos=1581`；GLD / 0050.TW 的 `n_common` 等於各自 `n_oos`。各序列自身樣本上的平均值另存於 JSON `qlike_own_sample`（SPY: BMA -8.2274 @ n=1581、Equal -8.2044 @ n=1581、GJR-t -8.1358 @ n=1518），**不可與 headline 混用比較**。

### Hypothesis verdicts

- **H1 (BMA beats GJR-t, Harvey |t|>3)**: **PARTIAL** — SPY + GLD PASS; 0050.TW FAIL (posterior concentrates on GJR-t so BMA≈GJR-t by construction)
- **H2 (BMA beats equal-weight, Harvey |t|>3)**: **FAIL** — no asset passes Harvey threshold; BMA only marginally beats equal on SPY/GLD (t≈-1.4 / -2.7), 0050.TW equal-weight actually wins point-estimate
- **H3 (regime-dependent weight shift)**: **FAIL** — posterior concentrates on 1 model per asset (A4f_IV2 for SPY/GLD, GJR-t for 0050.TW) and never reverses; weights are effectively regime-invariant

### Key findings (one-liner per hypothesis)

- H1: BMA PARTIAL — posterior correctly identifies IV-augmented A4f as superior for US/US-linked assets, but posterior concentration means BMA gain over GJR-t only when single best ≠ GJR-t.
- H2: BMA FAIL — no Harvey-significant gain over equal-weight; supports K482's "equal-weight ensemble puzzle" for SPY/GLD, and on 0050.TW equal-weight is numerically best.
- H3: Regime-adaptive weighting hypothesis rejected — cumulative likelihood update drives the posterior to a single model and it never un-concentrates, so BMA ≠ regime-adaptive in this implementation. （**「約 500 天」是 `k1257_weight_evolution.png` 的圖示描述（eyeballed from figure），不是量化指標**：本實驗未計算 effective number of models 或 concentration hitting-time，故此數字不可引用為 estimate。）

### Multiple comparisons — 為什麼 `|t|>3` 已經是 de-facto FWER 保護

本實驗的 headline 檢定數 **m = 3**（H1 的 BMA vs GJR-t，跨 SPY / GLD / 0050.TW；H2 的 BMA vs Equal 另為一組同樣 m=3 的檢定）。

| 量 | 值 |
|---|---|
| 檢定數 m | 3（每個 hypothesis family 各 3 個 asset-level DM 檢定） |
| 5% Bonferroni 校正門檻 | 0.05 / 3 = **0.0167** |
| 本實驗實際門檻 `\|t\|>3` 的 two-sided p（t-dist, df = n_common−1 ≈ 1517–1580） | **≈0.00274** |

`\|t\|>3` 對應的 p 遠嚴於 3-comparison 的 Bonferroni 門檻（0.00274 ≪ 0.0167），所以 SPY（t=−3.17, p=0.0015）與 GLD（t=−3.38, p=0.0007）的 H1 PASS 在 family-wise 校正後仍然成立，H2 的 FAIL 也不是門檻放寬造成的。採用固定 `|t|>3` 門檻即已提供 **de-facto FWER 保護**，無需另做 post-hoc 校正。（姊妹實驗 K1258 的 m=12，Bonferroni 門檻 0.00417，同樣寬於 0.00274。）

### Interpretation

- Posterior concentration is a known feature of product-of-likelihood BMA updates: after ~n log-lik accumulations, the best model's weight → 1 exponentially. Forgetting factor / sliding-window posterior would be needed to preserve regime-adaptive behavior.
- A4f-IV² dominant on SPY/GLD confirms IV-augmented variance specs remain the workhorse — consistent with K1002 A4f-t being MCS-only-survivor.
- 0050.TW's VIX is actually SPY's VIX (no GVZ-equivalent for Taiwan); if a Taiwan-specific IV index (e.g. TAIEX VIX) were substituted, A4f might also dominate there.
- **Null result on H2/H3 is reported as-is per research-honesty principle**; H1 PARTIAL is the headline.

### Limitations

1. **Posterior 吸收態（absorbing state）** — 本實作的 invalid-day 處理是**不可逆的**：模型在某日 forecast 無效（refit 未收斂等）時，其 log-weight 被設為 −inf 並排除於 posterior 之外，且**永遠無法回復**。JSON `posterior_semantics` 已明記此語意：`final_weights == 0.0` 代表「被 drop」，而 tiny-but-nonzero（如 SPY 的 GARCH_N ≈ 8.4e-31）代表「靠 likelihood 輸掉」。SPY 的 GJR-t 即因 26 次 refit 中 1 次未收斂而被 drop 63 天，終端權重恰為 0.0——這是機制性剔除，不是 posterior 對其預測能力的評價。
2. **Posterior 集中 ≠ regime adaptation** — 三檔資產的終端 posterior 都把 ~1.0 放在單一模型（SPY/GLD → A4f_IV2，0050.TW → GJR-t），且集中後不再反轉（「約 500 天」係從 `k1257_weight_evolution.png` **目測**得出的圖示描述，無 effective-number／hitting-time 指標支撐，不應當作量化估計引用）。因此 BMA 在實務上**就是那個模型的預測**，vs single-best 的差距是在說「posterior 挑對了哪個模型」，而非 combination 本身的增益。要保留 regime-adaptive 行為需 forgetting factor 或 sliding-window posterior（未實作）。
3. **樣本不對齊風險** — 因 SPY 的 GJR-t 缺 63 天，任何跨模型比較都必須在 common sample 上做。早期版本的 headline 混用了 own-sample BMA 與 common-sample GJR-t，已於本次 realign 修正。
4. **IV proxy 不對稱** — 0050.TW 沒有台股 IV index，A4f_IV2 用 `^VIX` 代打；regime 分類器也統一用 `^VIX`。0050.TW 的 A4f 劣勢（終端權重 5.4e-32）可能有相當部分來自 proxy 錯配，而非 IV-augmented spec 本身無效。
5. **無 5-min 資料** — HAR 只能用 |r| proxy（HAR_ABS），Realized GARCH 完全未納入；候選集因此偏向 daily-frequency specs。

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

- Prior weight: uniform 1/6 or informed from K482 findings?
- BMA log-lik 的 numerical stability（log-sum-exp trick 必要）

## 執行紀錄

本 K 源於 novelty-quota backlog（feed-coverage 0 topic）。**已於 2026-04-20 執行完畢**：實際候選集為 **6 個模型**（Realized GARCH 因無 5-min 資料未實作），rolling window 1250、refit 每 63 天、seed 42，實測 runtime **369.6s**（`k1257_results.json:runtime_seconds`）。

> 註：本段先前殘留「7 model × 2520」與「等候執行」的舊 spec 文字，與實際 6-model 執行結果衝突，已於 2026-07-20 移除。
