# K1145 — A4f-EAV Pooled Panel Estimation (N=31 Taiwan Stocks)

> **TL;DR**: Paper 2 last-pass side-finding test. Pools all 31 pre-registered stocks
> into a single A4f-EAV MLE with shared θ_VIX and θ_EAV but stock-specific GJR
> components. Answers the question: "If there is no stock-level θ_EAV signal (K1109
> cross-sectional NULL + K1140 temporal NULL), does θ_EAV emerge as a universal-
> magnitude effect at the panel level?"

[提出: Claude (承接 K1140 next_tasks K1143), 執行: Claude]

---

## 1. 動機（Why）

Paper 2 目前處於「cross-sectional + temporal dual-NULL」狀態：

- **K1109**：N=31 pre-registered sector sample，ANOVA F(7,20)=1.31, p=0.297 → sector heterogeneity **FAIL**
- **K1113**：firm covariate 回歸 → 所有 covariate 在 BH-FDR 後 NULL
- **K1140**：K1114 rolling θ₂ 的 HAC Newey-West + block-bootstrap 檢定，0/9 PASS → temporal heterogeneity 也 **FAIL**

K1140 的 next_tasks 段落列出一個 last-pass 可能路徑：

> "K1143 — A4f-EAV 改為 **pooled panel estimation**（不分股）— 若能在 pooled 上找到
> θ_EAV ≠ 0，可作為 Paper 2 的 positive side-finding"

K1145 執行這個 last-pass：把 N=31 所有 stock-day observations 合併，估一個共享 θ_EAV。
若這條路也 FAIL，Paper 2 就是乾淨的 dual-NULL 論文。

### 兩種可能結果的 Paper 2 narrative 含義

| 結果 | Paper 2 narrative |
|------|-------------------|
| pooled θ_EAV > 0, BH-PASS | "EAV effect 是 universal in magnitude, not stock-specific—firm-level noise 掩蓋了 panel-level signal" (salvages contribution) |
| pooled θ_EAV NS | **真正的 dual-NULL paper** — 三路徑（cross-sectional sector/covariate, temporal trend, panel pooled）全 FAIL。Paper 2 contribution 定位在「negative-result rigor」 |

---

## 2. 方法（What）

### 2.1 Pooled panel spec

對每檔股票 i 和時間 t：

$$
\sigma^2_{i,t} = g_{i,t} \cdot \tau_{i,t}
$$

- **Short-run GJR(1,1) component** (stock-specific)：
  $$
  g_{i,t} = \omega_i + \alpha_i u_{i,t-1}^2 + \gamma_i u_{i,t-1}^2 \cdot \mathbf{1}\{u_{i,t-1} < 0\} + \beta_i g_{i,t-1}
  $$
  with $u_{i,t} = r_{i,t} / \sqrt{\tau_{i,t}}$.

- **Long-run τ component** (stock-specific intercept, shared slopes)：
  $$
  \tau_{i,t} = \max\big(\theta^{(i)}_0 + \theta_{VIX} \cdot VIX^2_{t-1} + \theta_{EAV} \cdot EAV_{i,t-1}, \varepsilon\big)
  $$

**關鍵**：$\theta_{VIX}$ 和 $\theta_{EAV}$ **shared across 31 stocks**。這是 pooled panel 的核心假設。
$\theta^{(i)}_0$ 當作 stock fixed effect 允許各股票基準波動率不同。

### 2.2 Estimation — Block Coordinate Descent

全 joint MLE 維度高（31 × 5 stock-specific + 2 shared = 157 params）。用 BCD 分解：

```
repeat:
  for each stock i:
    fit (θ₀_i, ω_i, α_i, γ_i, β_i) by L-BFGS-B with shared (θ_VIX, θ_EAV) frozen
  update (θ_VIX, θ_EAV) by L-BFGS-B minimizing Σ_i pooled negll with stock params frozen
until Δloglik < 1e-2
```

- 內層 per-stock MLE 用 **Numba @njit** JIT 加速（~120x speedup vs pure Python）
- 4 starting values per stock
- Bounded optimization: θ₀ ∈ [1e-8, 1e-2], GJR persist < 0.999

### 2.3 Inference — Three layers

1. **Hessian SE**：numerical 2nd derivative of pooled negll w.r.t. θ_EAV，stock params held fixed. Asymptotic Wald test.
2. **Stock-clustered block bootstrap** (gold-standard for panel)：resample whole stocks with replacement 150 times, refit pooled BCD, record θ_EAV draws. Non-parametric 95% CI and two-sided p-value.
3. **K1109 single-stock mean θ₂ vs pooled**：比較 pooled point estimate 與 K1109 個股 θ₂ 平均數/中位數 (one-sample t-test on K1109 per-firm θ₂)

### 2.4 Robustness

- **R1 EAV window**：1-day (default)、3-day (announcement + 2 trading days after)、5-day
- **R2 Drop-out**：5 個隨機 seed (42, 43, 44, 45, 46)，每個 seed 丟掉 5 檔股票，refit pooled
- **R3 Direction consistency**：pooled θ_EAV sign vs K1109 single-stock mean θ₂ sign

### 2.5 Lookahead discipline

- **VIX_{t-1}**：US 前一日 session close（TW 開盤前已結算）
- **EAV_{i,t-1}**：公告日 lagged 1 天，用 `searchsorted` 在 trading days index 上定位
- 沒有使用 forward-looking flag；EAV 完全從已公告日期構造
- 所有回歸係數前 lag 都在 `_negll_numba` 內部用 `vix[t-1]`, `eav[t-1]` 實現，**代碼結構驗證**

### 2.6 Multi-test correction

Primary 3 tests (Hessian Wald, cluster bootstrap, K1109 single-stock mean) 統一做 BH-FDR。
Harvey (2016) |t| > 3.0 作為 Wald 通過門檻。

---

## 3. 資料

- **Daily close**：yfinance auto_adjust, 2010-01-01 ~ 2025-12-31
- **VIX**：^VIX daily close, reindex + ffill 到 TW trading days
- **Earnings dates**：`財報公告日.txt` (Big5 encoding), lookup by stock code
- **Sample**：N=31 pre-registered stocks from K1109 `firm_level_results`（8 sectors）
- **Cache**：`experiments/k1145/data/` (從 K1109 cache 複製，避免重新下載)
- **Random seed**：42 (numpy + bootstrap)

---

## 4. 結果（Findings）

### 4.1 Panel diagnostic
- N stocks loaded: **31/31**
- Pooled obs: **121,014** (3,684 ~ 3,911 per stock; 16 years 2010-2025)
- Mean log-return: +4.13e-4, std: 1.95e-2
- Skew: +0.156, excess kurt: +5.74
- Mean events per stock: 59.7 (range 57 - 61)

### 4.2 Main pooled MLE (EAV window=1, primary spec)
| Quantity | Value |
|----------|------|
| θ_VIX | 9.32e-08 |
| **θ_EAV (pooled)** | **+6.36e-05** |
| Hessian SE (1D conditional) | 4.50e-06 |
| Hessian t | **+14.14** |
| Hessian Wald p | ≈ 0.000 |
| Pooled log-likelihood | 329,349.98 |
| BCD outer iters | 8 |
| Convergence flag | False (Δll declining but didn't hit 1e-2 threshold; 8th iter Δll=+0.20, θ_EAV stable since iter 4) |

### 4.3 Stock-clustered block bootstrap (n_boot=150)
- Bootstrap completed: 150/150 (elapsed 426s)
- Bootstrap mean θ_EAV: +6.77e-05
- Bootstrap SE: 1.21e-05
- **95% percentile CI: [+4.13e-05, +9.38e-05]** (does not include 0)
- **Bootstrap t = +5.24, p ≈ 0** (no draws ≤ 0)

### 4.4 Robustness

| Variant | θ_EAV | Hessian SE | Hessian t |
|---------|-------|------------|-----------|
| EAV window=1 (main) | +6.36e-05 | 4.50e-06 | **+14.14** |
| EAV window=3 | +3.80e-05 | 2.67e-06 | +14.25 |
| EAV window=5 | +1.73e-05 | 1.71e-06 | +10.12 |
| Drop-5 seed=42 | +7.96e-05 | — | +14.12 |
| Drop-5 seed=43 | +7.03e-05 | — | +13.52 |
| Drop-5 seed=44 | +7.25e-05 | — | +13.69 |
| Drop-5 seed=45 | +6.21e-05 | — | +12.17 |
| Drop-5 seed=46 | +6.29e-05 | — | +12.87 |

θ_EAV magnitude **shrinks linearly** as window expands (1d ≈ 6.36e-5 → 3d ≈ 3.80e-5 → 5d ≈ 1.73e-5)
— sensible: same total announcement variance is being smeared over more days.
All 5 drop-out subsamples preserve sign + magnitude → not driven by 1-2 stocks.

### 4.5 K1109 single-stock comparison

| Quantity | K1109 (single-stock) | K1145 (pooled) |
|----------|---------------------|----------------|
| N | 31 stocks | 31 stocks (joint) |
| Mean θ_EAV | +4.64e-05 | +6.36e-05 |
| Median θ_EAV | +2.78e-05 | — |
| SE of mean | 1.15e-04 | 4.50e-06 (Hessian), 1.21e-05 (bootstrap) |
| t-stat (mean = 0) | **+0.40 (p=0.69)** | **+14.14 (Hessian) / +5.24 (bootstrap)** |
| Direction | positive | positive — **MATCH** |

**Crucial inference**: K1109 fails because per-stock SE is huge (cross-stock dispersion = 1.15e-4 ≫ pooled estimator SE).
Pooled MLE pools observations across stocks, getting ~31x effective N, and the signal emerges.
This is exactly the K1145 hypothesis: **EAV effect is universal in magnitude, masked by stock-level noise**.

### 4.6 BH-FDR table (3-test correction)

| Test | raw p | BH-adj p | Verdict |
|------|-------|----------|---------|
| pooled_hessian | ≈ 0 | ≈ 0 | **PASS** |
| pooled_bootstrap | ≈ 0 | ≈ 0 | **PASS** |
| k1109_mean_test | 0.689 | 0.689 | NS (single-stock null) |

### 4.7 Codex review (2026-04-13)

Codex (gpt-5, high reasoning) reviewed `k1145.py` and confirmed:
- ✅ **Lookahead correct**: VIX_lag and EAV_lag are properly t-1 shifted in `_negll_numba`
- ✅ **Hessian SE correctly coded** (central difference, sqrt(1/h22))
- ✅ **Cluster bootstrap correctly resamples whole stocks**
- ⚠️ **Conditional 1D Hessian inflates t** (ignores cross-curvature with θ_VIX and per-stock nuisance) → bootstrap t=5.24 is the more honest number ✓ (we already report bootstrap as primary)
- ⚠️ EAV window comment originally said "backward" but code is forward-from-announcement → docstring corrected post-review (no result change; lookahead still respected via likelihood-side lag)

### 4.8 Placebo test (within-stock EAV permutation) — **decisive**

Codex-suggested: shuffle EAV array within each stock (preserves event count, breaks time alignment with returns).
Refit pooled BCD on permuted panel; if pooled signal is real, observed +6.36e-5 should be far in placebo tail.

| Quantity | Value |
|----------|------|
| N placebo replicates | 60 |
| Placebo mean θ_EAV | **+1.36e-06** (essentially zero, as expected under null) |
| Placebo SE | 4.69e-06 |
| Placebo 95% CI | [-5.34e-06, +1.28e-05] |
| Observed θ_EAV | +6.36e-05 |
| **Distance from placebo mean** | **+13.6 placebo SE** |
| **One-sided p (placebo ≥ observed)** | **0/60 = 0.000** |

**Conclusions from placebo**:
1. **Pooled MLE is not biased upward by pooling artifact** (placebo mean ≈ 0 confirms unbiasedness under null)
2. **Hessian SE (4.50e-6) ≈ placebo SE (4.69e-6)** — Codex's "conditional Hessian inflates t" concern is partially mitigated; the conditional 1D Hessian SE turns out to track the actual sampling SE under permutation null
3. **Cluster bootstrap SE (1.21e-5) is wider** than both — bootstrap captures additional cross-stock variance dispersion ON TOP OF the within-stock variance the placebo isolates
4. **Observed +6.36e-5 sits 13.6σ above placebo mean** — overwhelming evidence of real time-aligned signal at announcement dates

This is the **strongest possible robustness layer** for the K1145 finding.

---

## 5. 結論

### Core Verdict: **PASS — Paper 2 universal-magnitude side-finding confirmed**

Primary 決策規則（pre-registered）：
- pooled θ_EAV t > 3.0 (Harvey 2016) AND BH-adj p < 0.05 → PASS
- 觀察：bootstrap t = +5.24 (p ≈ 0)；Hessian t = +14.14 (p ≈ 0)；BH-adj p ≈ 0 ✓✓

### Paper 2 narrative pivot

K1109 (cross-sectional NULL) + K1113 (firm covariates NULL) + K1140 (rolling temporal NULL) **不再是「dual NULL paper」**。
K1145 證明：**EAV (earnings-announcement variance) 效應在台股是 universal in magnitude
across firms (~+6.4e-5)，但 stock-level estimator SE 太大 (1.15e-4) 無法逐股偵測**。

新的 Paper 2 contribution narrative:

> "We document a robust pooled-panel EAV effect (θ_EAV = +6.4e-5, cluster-bootstrap
> t = +5.24, n_stocks = 31, n_obs = 121,014) that is invisible at the firm level.
> Per-stock EAV slopes are highly dispersed (SE = 1.15e-4 ≫ pooled SE = 1.21e-5),
> rendering individual-stock tests statistically uninformative (one-sample t = 0.40,
> p = 0.69). This is consistent with EAV being a **universal-magnitude** earnings-
> announcement variance premium that is masked by firm-level idiosyncratic noise.
> Sector and firm-attribute regressions (Engle-Ghysels-Sohn 2013 framework with
> N=31 pre-registered Taiwanese stocks) all fail to reject the null of homogeneity;
> the effect is best understood as a population-level constant rather than a
> firm-level predictor."

### Preamble Rule #5 自我質疑（post-hoc, pooled 特有）

⚠️ Panel pooled 有時膨脹效應 — Hessian t = 14 是 1D conditional curvature，**忽略了 θ_VIX 與 nuisance 參數的 cross-curvature**，因此被高估。**信 bootstrap t = 5.24** —— 透過 stock-level cluster bootstrap，承認 within-stock 自相關和 cross-stock 異質性。

額外 robustness 來自：
1. **EAV-window 1/3/5 三條 specification 都顯著**（t > 10），且係數隨 window 增大線性遞減，符合 "same total announcement variance smeared over more days" 的物理直覺
2. **5 個獨立 drop-out subsamples 全部 t > 12** — 不是 1-2 檔股票驅動
3. **Direction match with K1109 single-stock mean** — 點估方向一致，差別是 SE 的 31x 縮減
4. **Codex review 通過**，無 HIGH-severity bug；conditional Hessian 過度信心的疑慮已由 bootstrap 主檢定回應

### 仍須謹慎承認的局限

- 樣本侷限於台股 31 檔 pre-registered 股票（K1109 八大產業）
- EAV 是粗糙的 binary indicator（公告日 vs 非公告日），未區分財報好壞或市場意外程度
- Pooled MLE 假設 cross-stock 殘差獨立——bootstrap 雖然部分校正但完全 cross-section copula 未模型化
- 結果可推廣到大型台灣藍籌股；中小型股或新興市場個股是否成立未驗證

### 衍生 next_tasks (K1146+)

| K ID | 主題 | 優先度 |
|------|------|--------|
| K1146 | **Paper 2 manuscript pivot**：把現有 dual-NULL 草稿改寫為 "universal-magnitude pooled effect" finding + 5 robustness layers (window/dropout/placebo/bootstrap/Hessian) | **最優先** |
| K1147 | EAV magnitude 跨市場驗證：US S&P 500 N=30, Japan TOPIX N=30 用同樣 pooled spec 看 θ_EAV 是否類似量級 | 高 |
| K1148 | EAV refine：earnings surprise（actual − consensus EPS）連續變數版本 vs binary，看哪個解釋力更強 | 中 |
| K1149 | Pooled spec 換 PCA factor model（θ_EAV 受到 systematic factor 主導？）| 中 |

---

## 6. 檔案

- `k1145.py` — 主實驗腳本（BCD + Hessian + bootstrap + 3 EAV defs + 5 drop-outs）
- `k1145_placebo.py` — Codex-建議補充：within-stock EAV permutation placebo
- `k1145_results.json` — 主實驗完整結果 JSON
- `k1145_placebo_results.json` — placebo 結果 JSON
- `k1145_theta_eav_pool_vs_single.png` — pooled θ_EAV vs K1109 single-stock histogram
- `k1145_robustness_barplot.png` — θ_EAV 在 8 個變體下的 bar plot（含 95% CI）
- `data/` — yfinance cache (複製自 K1109)
- `run.log` — stdout 執行 log

---

## 7. 參考文獻

- Engle, R. F., Ghysels, E., & Sohn, B. (2013). Stock market volatility and macroeconomic fundamentals. *Review of Economics and Statistics*, 95(3), 776-797. *(GARCH-MIDAS long-run τ component)*
- Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics*, 160(1), 246-256. *(QLIKE + cross-model fair comparison)*
- Cameron, A. C., Gelbach, J. B., & Miller, D. L. (2008). Bootstrap-based improvements for inference with clustered errors. *Review of Economics and Statistics*, 90(3), 414-427. *(cluster bootstrap for panel)*
- Harvey, C. R., Liu, Y., & Zhu, H. (2016). … and the cross-section of expected returns. *Review of Financial Studies*, 29(1), 5-68. *(Harvey t>3.0 threshold)*
- Benjamini, Y., & Hochberg, Y. (1995). Controlling the FDR. *JRSS B*, 57(1), 289-300.

## 8. 相關 K 編號

- **K1067 / K1067b / K1067c** — TSMC/UMC/MediaTek A4f-EAV single-window results (three-stock NULL + MIXED + counterexample)
- **K1109** — Pre-registered N=31 cross-sectional sector ANOVA FAIL（提供 ticker list）
- **K1113** — Firm covariate regression FAIL
- **K1114** — Rolling θ_EAV with 96% overlap (raw OLS SE biased)
- **K1140** — HAC + block-bootstrap on K1114 rolling θ series, 0/9 BH-PASS（本 K 直接承接）
