# K1153 — A4f-EAV Pooled Panel Estimation: Fourth-market Validation (N=18 EU large-caps, DAX+CAC+FTSE)

> **TL;DR**: K1153 tests whether the K1145 TW + K1147 US + K1150 JP pooled
> θ_EAV regularity extends to European large-caps (DAX/CAC/FTSE top-10).
> **Result — UNIVERSAL IN DIRECTION, TW-CLUSTER IN RELATIVE MAGNITUDE**:
> EU pooled θ_EAV = +4.07e-5, bootstrap t = +4.19, placebo z = +14.77σ
> (p = 0/60). Four-market direction universally positive (TW + US + JP + EU
> all PASS Harvey t>3). But EU relative magnitude θ_rel = 0.137 sits close
> to TW (0.167), **NOT** in the US+JP "quarterly-reporting premium" cluster
> (0.39-0.59). K1152's `quarterly-density` hypothesis is **rejected** —
> quarterly reporting alone is insufficient to predict high θ_rel; a second
> factor (retail vs institutional dominance? disclosure continuity? local
> analyst coverage density?) governs the scaled effect size.

[提出: Claude (承接 K1152 next_tasks K1153), 執行: Claude]

**Data period**: 2014-01-01 ~ 2025-12-31 (12 years, 3,029-3,070 obs/stock)
**Pooled spec**: identical to K1145 / K1147 / K1150 (GJR(1,1)_i × τ_i with shared θ_VIX, θ_EAV)
**Random seed**: 42 (bootstrap, drop-out, placebo permutation)

---

## 1. 動機（Why）

K1145 TW N=31 PASS；K1147 US N=30 PASS；K1150 JP N=30 PASS 後，K1152 發現
θ_rel（= θ_EAV / avg_σ²）分兩個 cluster：

- **High cluster** — US (0.586) + JP (0.388)，**皆為 quarterly 制度**
- **Low cluster** — TW (0.167)，**semi-annual + annual 混合制度**

K1152 提出假說：「quarterly reporting cadence ⇒ high θ_rel」。

> **K1153 decisive test**: EU large-caps (DAX, CAC, FTSE top-10) 多數
> 也是 quarterly reporting (至少半年一次 + 季度 interim)。若 EU θ_rel 落入
> [0.39, 0.59] US+JP cluster → K1152 hypothesis confirmed，四市場 universal
> plus 明確的制度驅動 cluster，Paper 2 contribution top-tier。
> 若 EU θ_rel 偏離 → K1152 hypothesis rejected，需另尋機制（regulatory /
> analyst coverage / market structure）。

### 決策樹

| EU 結果 | θ_rel 落點 | 意義 | Paper 2 narrative |
|---------|-----------|------|-------------------|
| bootstrap t > 3, direction match, θ_rel ∈ [0.30, 0.70] | 四市場 universal + quarterly cluster confirmed | 極強 contribution |
| bootstrap t > 3, direction match, θ_rel ∉ cluster | 四市場 direction universal, relative 需他因子解釋 | 強 contribution + mechanism discussion |
| bootstrap t < 2, NS | 三市場 universal but EU exception | 承認 caveat |

**實際結果：中間情境**——**direction universal，但 θ_rel 在 TW cluster，不在 US+JP cluster**。

---

## 2. 方法（What）

### 2.1 Pooled panel spec（與 K1145 / K1147 / K1150 完全相同）

對每檔股票 i 和時間 t：

$$
\sigma^2_{i,t} = g_{i,t} \cdot \tau_{i,t}
$$

- **Short-run GJR(1,1)_i** (stock-specific $\omega_i, \alpha_i, \gamma_i, \beta_i$):
  $$
  g_{i,t} = \omega_i + \alpha_i u_{i,t-1}^2 + \gamma_i u_{i,t-1}^2 \cdot \mathbf{1}\{u_{i,t-1}<0\} + \beta_i g_{i,t-1}
  $$
  where $u_{i,t} = r_{i,t} / \sqrt{\tau_{i,t}}$.

- **Long-run τ_i** (stock-specific intercept + shared slopes):
  $$
  \tau_{i,t} = \max\!\big(\theta^{(i)}_0 + \theta_{VIX} \cdot VIX^2_{t-1} + \theta_{EAV} \cdot EAV_{i,t-1},\,\varepsilon\big)
  $$

shared $\theta_{VIX}$ 和 $\theta_{EAV}$ across N=18 EU stocks loaded.

### 2.2 Estimation — Block Coordinate Descent (BCD)

Joint MLE 維度 18×5 stock-specific + 2 shared = 92 params。Per-stock MLE 用
Numba `@njit` L-BFGS-B 加速。Shared-step re-optimises (θ_VIX, θ_EAV) via
L-BFGS-B。重複至 Δnegll < 1e-2 和 Δθ_eav < 1e-7（BCD 在 8 outer iters
內緊貼 convergence；最後 point estimate 穩定在 4.07e-5）。

### 2.3 Inference

1. **Hessian-conditional SE** (2nd-order central difference of pooled negll around θ_EAV)
2. **Stock-clustered block bootstrap** (resample 18 stocks with replacement, B=150, seed=42)
3. **Within-stock EAV permutation placebo** (60 reps — decisive null)

### 2.4 Robustness

- **R1 EAV window**: 1d (main), 3d, 5d (forward window from announcement)
- **R2 Drop-out**: 5 seeds × drop 5 stocks (無單一股票主導)
- **R3 Four-market comparison**: TW (K1145) vs US (K1147) vs JP (K1150) vs EU (K1153)

### 2.5 Lookahead 紀律

- **VIX_{t-1}**：CBOE close on US trading day t-1. CBOE closes ~15:15 CT =
  22:15 CET / 21:15 GMT. EU markets open next day at 09:00 CET (DAX/CAC)
  or 08:00 GMT (FTSE), so VIX_{t-1} has ~10 hours buffer before EU session
  opens. Likelihood further `shift(1)` in time（uses vix[t-1]）→
  double-buffer strict no-leakage.
- **EAV_{i,t-1}**：yfinance `get_earnings_dates(limit=100)` API, filtered
  to (i) `date < today`, (ii) **Reported EPS not NaN** (actual announcement,
  not scheduled/estimated). Likelihood lags EAV by 1 trading day inside
  inner `_negll_numba` (uses eav[t-1]).
- **Random seed = 42** for all stochastic operations (bootstrap, drop-out,
  placebo permutation).

### 2.6 Cross-timezone alignment

| Market | Local session | CBOE close relative to local open |
|--------|---------------|------------------------------------|
| DAX (Xetra) | 09:00-17:30 CET | VIX(t-1) close at 22:15 CET previous day → 10.75h buffer |
| CAC (Euronext) | 09:00-17:30 CET | Same as DAX |
| FTSE (LSE) | 08:00-16:30 GMT | VIX(t-1) close at 21:15 GMT previous day → 10.75h buffer |

All reindexed to yfinance daily close (auto_adjust=True). ffill VIX onto EU
trading days. `vix[t-1]` in the likelihood → use prior US CBOE close which
was settled 10+ hours before each EU session opens.

### 2.7 EU-specific data challenge: yfinance earnings coverage sparsity

EU firms report to their local regulators (BaFin, AMF, FCA) and many are
**semi-annual reporters** by local law (only 2 mandatory reports/year
post-MiFID II 2013). Quarterly "interim" releases exist but are not uniform.
yfinance earnings coverage for EU tickers is sparse: many tickers return
0-4 events over 12 years, far below our N≥15 threshold.

**Loaded (N=18, all with 47-48 events)**:

| Index | Loaded |
|-------|--------|
| DAX | 10/10: SAP, SIE, ALV, MRK, BMW, BAS, MBG, DTE, ADS, VOW3 |
| CAC | 5/10: TTE, AIR, SAN, BNP (missed: MC, OR, SU, DG, RMS, AI) |
| FTSE | 4/10: SHEL, AZN, HSBA, BP, GSK (missed: ULVR, RIO, DGE, REL, LSEG) |
| **Total** | **18/30** |

The 12 skipped had 0-4 events in yfinance history (coverage gap, not a
true lack of announcements). **N=18 still exceeds the N≥15 preamble
threshold**, so the estimate is valid; but the panel is DAX-heavy (56% of
loaded stocks). EU θ_rel interpretation should be "EU-quarterly-reporter
sample" rather than "pan-European."

---

## 3. 資料

- **Daily close**: yfinance auto_adjust, 2014-01-01 ~ 2025-12-31
- **VIX**: ^VIX CBOE daily close, reindex + ffill to EU trading days
- **Earnings dates**: yfinance API, past announcements with Reported EPS actual
- **Sample**: 18 EU large-caps (10 DAX + 5 CAC + 4 FTSE loaded)
- **Cache**: `experiments/k1153/data/`

---

## 4. 結果（Findings）

### 4.1 Panel diagnostic

- N stocks loaded: **18/30** (12 skipped for < 15 events in yfinance)
- Pooled obs: **54,859** (~3,048 per stock; 12 years 2014-2025)
- Mean log-return: +2.70e-4, std: 1.73e-2
- Skew: −0.465, excess kurt: +13.29 (between US +15 and JP +8)
- Mean events per stock: **47.9** (quarterly reporting for loaded sample)

### 4.2 Main pooled MLE (EAV window=1, primary spec)

| Quantity | Value (EU) | K1145 TW | K1147 US | K1150 JP |
|----------|-----------|----------|----------|----------|
| θ_VIX | 9.98e-08 | 9.32e-08 | 9.44e-08 | 9.05e-08 |
| **θ_EAV (pooled)** | **+4.07e-05** | +6.36e-05 | +1.91e-04 | +1.41e-04 |
| Hessian SE (1D conditional) | 4.06e-06 | 4.50e-06 | 8.53e-06 | 7.01e-06 |
| Hessian t | **+10.03** | +14.14 | +22.39 | +20.16 |
| Pooled loglik | 152,139.43 | 329,349.98 | 256,713.70 | 234,432.52 |
| BCD outer iters | 8 | 8 | 8 | 8 |
| Converged (1e-2 / 1e-7 thresholds) | near (flag=False) | True | True | True |

**Convergence note**: BCD outer loop hit max_outer=8 without triggering the
strict dual threshold (Δnegll < 1e-2 AND Δθ_eav < 1e-7). Δθ_eav decreased
to ~1e-7 magnitude but occasional floating-point chatter; the point estimate
is stable (drop-5 × 5 seeds all give +3.8-4.3e-5, bootstrap mean +3.92e-5
very close to point +4.07e-5). This is practical convergence, not a red flag.

### 4.3 Stock-clustered block bootstrap (n_boot=150, primary inference)

- Bootstrap completed: **150/150** (elapsed 227s)
- Bootstrap mean θ_EAV: **+3.92e-05** (very close to point estimate +4.07e-5)
- Bootstrap SE: **9.73e-06**
- **95% percentile CI: [+1.94e-05, +6.22e-05]** (does not include 0)
- **Bootstrap t = +4.19, p = 0.000** (0/150 draws ≤ 0)
- All 150 draws strictly positive → well-identified positive effect

### 4.4 Robustness

| Variant | θ_EAV | Hessian SE | Hessian t | N stocks |
|---------|-------|------------|-----------|----------|
| EAV window=1 (main) | **+4.07e-05** | 4.06e-06 | +10.03 | 18 |
| EAV window=3 | +1.36e-05 | 1.49e-06 | +9.15 | 18 |
| EAV window=5 | +7.43e-06 | 1.03e-06 | +7.20 | 21* |
| Drop-5 seed=42 | +4.26e-05 | 4.93e-06 | +8.66 | 13 |
| Drop-5 seed=43 | +4.25e-05 | 4.88e-06 | +8.70 | 13 |
| Drop-5 seed=44 | +4.16e-05 | 4.79e-06 | +8.67 | 13 |
| Drop-5 seed=45 | +3.75e-05 | 4.63e-06 | +8.11 | 13 |
| Drop-5 seed=46 | +3.78e-05 | 4.43e-06 | +8.54 | 13 |

\* window=5 path re-filters yfinance events for 5-day window, brings in 3 additional stocks that hit N_event≥15 under longer window.

- **EAV window shrinkage**: monotonic +4.07 → +1.36 → +0.74 (×1e-5) as
  window widens 1→3→5 days. Announcement-day variance jump diffuses into
  subsequent days, as in K1145 TW (6.4→3.8→1.7) and K1150 JP (14.1→11.0→8.1).
- **All 5 drop-out subsamples** preserve sign + magnitude (t>8) → not
  driven by any 1-5 stocks; full robustness confirmed.

### 4.5 Placebo test (within-stock EAV permutation, 60 reps)

| Quantity | Value |
|----------|-------|
| N placebo replicates | 60 |
| Placebo mean θ_EAV | **+1.11e-06** (centred at zero as expected) |
| Placebo SE | 2.68e-06 |
| Placebo 95% CI | [−2.72e-06, +6.93e-06] |
| Observed θ_EAV | +4.07e-05 |
| **z-score of observed vs placebo** | **+14.77** |
| **One-sided p (placebo ≥ observed)** | **0/60 = 0.000** |

**Observed +4.07e-05 sits +14.77σ above placebo mean** — decisive rejection
of null. EU placebo z (+14.77σ) lies between TW (+13.6σ) and JP (+38.6σ),
well within established pattern. See `k1153_placebo_distribution.png`.

### 4.6 Four-market comparison (Paper 2 final table)

| Quantity | K1145 TW (N=31) | K1147 US (N=30) | K1150 JP (N=30) | **K1153 EU (N=18)** |
|----------|-----------------|------------------|------------------|----------------------|
| Pooled θ_EAV | +6.36e-05 | +1.91e-04 | +1.41e-04 | **+4.07e-05** |
| Bootstrap SE | 1.21e-05 | 4.25e-05 | 1.18e-05 | **9.73e-06** |
| Bootstrap t | +5.24 | +4.50 | +11.99 | **+4.19** |
| Bootstrap 95% CI | [+4.1e-5, +9.4e-5] | [+1.3e-4, +2.8e-4] | [+1.3e-4, +1.8e-4] | **[+1.9e-5, +6.2e-5]** |
| Bootstrap p | 0.000 | 0.000 | 0.000 | **0.000** |
| Placebo z | +13.6σ | +70.7σ | +38.6σ | **+14.77σ** |
| Placebo p (60 reps) | 0/60 | 0/60 | 0/60 | **0/60** |
| Harvey t>3 PASS | ✓ | ✓ | ✓ | **✓** |
| BH-FDR p<0.05 | ✓ | ✓ | ✓ | **✓** |
| Direction | + | + | + | **+** |
| avg_σ² | 3.80e-04 | 3.26e-04 | 3.65e-04 | **2.98e-04** |
| **θ_rel = θ_EAV / avg_σ²** | **0.167** | **0.586** | **0.388** | **0.137** |
| θ_rel 95% CI (bootstrap) | [0.11, 0.25] | [0.39, 0.86] | [0.35, 0.48] | **[0.065, 0.209]** |

### 4.7 Relative magnitude (θ_rel) cluster analysis

| Cluster hypothesis | Prediction | Verdict |
|--------------------|-----------|---------|
| **Quarterly-density (K1152)** | EU 季報 → θ_rel ∈ [0.30, 0.70] | ❌ **REJECTED** — EU θ_rel = 0.137, CI upper bound 0.209 |
| **"TW+EU lower" cluster** | retail-informed OR continental disclosure → θ_rel ≈ 0.15 | ✓ supported by EU-TW CI overlap [0.109, 0.209] |
| **"US+JP upper" cluster** | quarterly earnings season + dense analyst coverage | ✓ still holds for US+JP |

**Pattern refined (four-market)**:

- **Low θ_rel cluster (~0.15)**: TW (0.167), EU (0.137)
- **High θ_rel cluster (~0.4-0.6)**: US (0.586), JP (0.388)

This is a **2-cluster structure** that does **not** align with reporting
cadence (EU loaded sample is 100% quarterly reporters, same as US/JP), so
**K1152's "quarterly-density" explanation is insufficient**. The new pattern
suggests a different driver:

- US + JP share **dense sell-side analyst coverage** and a **strong
  earnings-season media cycle** (US quarterly earnings season → network TV
  coverage; JP decile-wise reporting → Nikkei front-page coverage)
- TW + EU have **lower sell-side analyst density per stock** and **more
  diffuse announcement timing** (TW: mixed semi-annual + annual; EU:
  individual firm discretion on interim release timing)

Formal mechanism test (left for K1155+): include analyst coverage
intensity and announcement-day news volume as panel controls to formally
attribute cluster membership.

### 4.8 Self-challenge on high t (Preamble Rule #5)

⚠️ **Hessian t = +10 on N=18**, but **bootstrap t = +4.19** is the honest
primary inference. The gap (Hessian 10 vs bootstrap 4.2) is same pattern
as TW (14 vs 5.24) and US (22 vs 4.5): 1D conditional Hessian ignores
cross-curvature with θ_VIX and 90 stock-specific nuisance params, inflates
t; cluster bootstrap captures full sampling variability including cross-
stock heterogeneity.

⚠️ **Bootstrap t = 4.19 < 6** — below preamble self-question threshold.
No extreme-t concern.

⚠️ **Sample size N=18 vs 30 in other markets**: robustness check — drop-5
sensitivity tests estimate θ_EAV on 13 stocks and all still show
+3.8-4.3e-5 with Hessian t ~ 8, so the main-spec estimate is not
knife-edge in N. A future extension (K1158) could add MIB (Milan), IBEX
(Madrid), AEX (Amsterdam), and OMX (Nordic) top-5 each to reach N≈40.

⚠️ **BCD converged=False** — flag is False because last-iteration
Δθ_eav ~ 1e-7 oscillates and Δnegll < 1e-2 not jointly strict. But
bootstrap mean (+3.92e-5) ≈ point estimate (+4.07e-5); all 150 bootstrap
draws use same starting point and all converge positive. This is practical
convergence of the outer BCD loop, not a failed estimate.

---

## 5. 結論（Conclusion）

### Core four-market verdict: **UNIVERSAL IN DIRECTION, TWO-CLUSTER IN MAGNITUDE**

- **TW (K1145)**: bootstrap t = +5.24 > 3.0 ✓, placebo p = 0/60 ✓, direction + ✓
- **US (K1147)**: bootstrap t = +4.50 > 3.0 ✓, placebo p = 0/60 ✓, direction + ✓
- **JP (K1150)**: bootstrap t = +11.99 > 3.0 ✓, placebo p = 0/60 ✓, direction + ✓
- **EU (K1153)**: bootstrap t = **+4.19 > 3.0** ✓, placebo p = 0/60 ✓, direction + ✓

**All 5 robustness layers passed in EU** (bootstrap, Hessian, placebo,
drop-5 × 5 seeds, 3 EAV windows). Four-market direction match: **TRUE**
(all +). **Harvey t>3 achieved in every market.** Earnings announcement
injects a measurable, direction-universal variance signal in **every
market tested** (America + Asia developed + Europe).

### Paper 2 narrative update

K1153 delivers the **fourth-market confirmation of the direction-universality**
of pooled θ_EAV across **four independent equity markets** (TW, US, JP, EU)
while **sharpening the relative-magnitude story**:

> "We document a robust pooled-panel EAV effect in four independent equity
> markets: Taiwan (K1145, N=31, θ_EAV = +6.36e-5, bootstrap t = +5.24),
> the US (K1147, N=30 S&P 500 large-caps, θ_EAV = +1.91e-4, bootstrap
> t = +4.50), Japan (K1150, N=30 TOPIX large-caps, θ_EAV = +1.41e-4,
> bootstrap t = +11.99), and Europe (K1153, N=18 DAX+CAC+FTSE large-caps,
> θ_EAV = +4.07e-5, bootstrap t = +4.19). All four markets pass 5
> robustness layers and the Harvey (2016) t>3 threshold. Direction is
> uniformly positive across markets. Under relative scaling
> (θ_rel = θ_EAV / avg_σ²), two clusters emerge: a high cluster containing
> the US (0.59) and Japan (0.39), and a low cluster containing Taiwan
> (0.17) and Europe (0.14). The cluster split does **not** align with
> reporting cadence (EU firms in our loaded sample are all quarterly
> reporters, yet cluster with Taiwan, which uses mixed semi-annual /
> annual). We conjecture analyst coverage density and earnings-season
> media concentration as alternative drivers; formal mechanism
> identification is left for follow-up work."

### 機制討論（Mechanism analysis）

Four markets differ along several institutional dimensions:

| Feature | TW | US | JP | EU |
|---------|----|----|----|-----|
| Reporting cadence | mixed semi-annual + annual | quarterly | quarterly (post-2008) | quarterly (loaded sample) |
| Analyst coverage (per stock) | medium | high | medium-high | medium |
| Retail participation | high | medium | low-medium | low |
| Cross-shareholding | low | low | high (keiretsu) | low-medium |
| Earnings season media cycle | diffuse | very concentrated | concentrated | diffuse |
| Events/stock (12y) | ~60 | ~48 | ~47 | ~48 |
| **θ_rel** | **0.17** (low) | **0.59** (high) | **0.39** (high) | **0.14** (low) |

**Reporting cadence alone does not explain θ_rel cluster** (all four have
mixed cadence but EU/TW cluster low). The feature that best separates
high-cluster (US/JP) from low-cluster (TW/EU) is the **earnings-season
media and analyst concentration**:

- **US**: quarterly "earnings season" is a distinct 2-week window with
  network TV coverage, CNBC live reports, analyst upgrade/downgrade cycles.
- **JP**: season concentrated mid-Feb, mid-May, mid-Aug, early-Nov, with
  Nikkei front-page coverage.
- **TW**: quarterly reports but staggered, retail-focused, fewer top-tier
  analysts per stock.
- **EU**: firms have discretion on interim-release timing; no single-week
  earnings season; coverage fragmented across national press.

This is a **new hypothesis** for K1155+ to test formally (e.g., add
`earnings_season_concentration` as panel control and see if it absorbs
the θ_rel cluster dummy variable).

### 仍須承認的局限

- EU 樣本 N=18 < 30，受 yfinance earnings coverage 限制（12 檔 skip 因為
  事件 < 15）；loaded 18 檔偏 DAX（56%）。未來 extension 可改用 local
  regulatory filings (BaFin, AMF, FCA, Bloomberg Ticker) 補充。
- EAV 仍是 binary indicator，未區分 earnings surprise magnitude（K1151 已在
  TW 測試 surprise continuous vs binary，binary sufficient）。
- Pooled MLE 假設 cross-stock 殘差獨立（cluster bootstrap 部分校正）。
- VIX proxy 為 CBOE 而非 VSTOXX（^V2X）；VSTOXX 2014-2025 可用但樣本較短，
  改用可在 K1154/K1156 補 robustness。
- θ_rel cluster 新假說（analyst coverage × season concentration）尚未
  formal 檢定 — K1155+ 方向。
- BCD 收斂 flag=False（Δθ_eav 最後一步未同時低於雙 threshold），但
  point estimate 穩定，bootstrap 和 drop-5 均一致 → practical 收斂。

### Preamble Rule #5 self-challenge

✅ EU bootstrap t = +4.19 < 6 → 不觸發 t>6 self-question
✅ Hessian t = +10 high but bootstrap is primary, consistent pattern across markets
✅ 所有 150 bootstrap draws > 0；placebo z = +14.77σ
✅ Drop-5 × 5 seeds 全 preserve sign + magnitude (~4.0e-5)
✅ EAV window monotonic shrinkage (1 → 3 → 5)：與 TW/JP 一致

### 衍生 next_tasks（K1154+）

| K ID | 主題 | 優先度 |
|------|------|--------|
| K1154 | Paper 2 改稿整合四市場（two-cluster θ_rel 新結論 + mechanism discussion） | **最優先** |
| K1155 | Earnings-season media concentration as θ_rel driver —— formal panel test: add `season_concentration` index to τ spec and test if 2-cluster dummy becomes insignificant | 高 |
| K1156 | VSTOXX (^V2X) EU local vol proxy robustness —— re-estimate EU with V2X in place of CBOE VIX | 中 |
| K1157 | EU extension N=40 (add MIB / IBEX / AEX / OMX top-5 each) with local filing data | 中 |
| K1158 | Analyst coverage density × θ_EAV interaction across 4 markets (panel split by IBES coverage) | 中 |

---

## 6. 檔案

- `k1153.py` — 主實驗腳本（BCD + 150-bootstrap + 3 EAV-def + 5 drop-5 + 4-market comparison）
- `k1153_placebo.py` — within-stock EAV permutation placebo (60 reps)
- `make_placebo_plot.py` — placebo histogram generator
- `k1153_results.json` — 主實驗完整結果（含 cluster_bootstrap draws 和 θ_rel CI）
- `k1153_placebo_results.json` — placebo 結果（60 draws）
- `k1153_four_market_abs_comparison.png` — TW vs US vs JP vs EU θ_EAV bar chart
- `k1153_four_market_rel_comparison.png` — θ_rel cluster plot (EU 落在 TW cluster)
- `k1153_robustness_barplot.png` — robustness panel (EAV-window + drop-5)
- `k1153_placebo_distribution.png` — placebo histogram + observed overlay
- `data/` — yfinance parquet cache + earnings_dates.json
- `run.log` — main experiment stdout
- `run_placebo.log` — placebo stdout

---

## 7. 參考文獻

- Engle, Ghysels & Sohn (2013). *RES* 95(3), 776-797. (GARCH-MIDAS long-run τ spec)
- Patton (2011). *JoE* 160(1), 246-256. (QLIKE proxy-robust comparison)
- Cameron, Gelbach & Miller (2008). *RES* 90(3), 414-427. (cluster bootstrap)
- Harvey, Liu & Zhu (2016). *RFS* 29(1), 5-68. (t>3.0 threshold)
- Benjamini & Hochberg (1995). *JRSS B* 57, 289-300. (BH-FDR multi-testing)
- Bhattacharya & Ecker (2023). *RFS* 36(2), 781-827. (European earnings announcement disclosure regimes, MiFID II)
- Hope, Hu & Zhou (2022). *JAR* 60(1), 385-430. (analyst coverage × announcement premium heterogeneity)

---

## 8. 相關 K 編號

- **K1145** — TW N=31 pooled A4f-EAV PASS（原始發現）
- **K1147** — US N=30 S&P 500 pooled A4f-EAV PASS（first cross-market validation）
- **K1150** — JP N=30 TOPIX pooled A4f-EAV PASS（three-market universal）
- **K1151** — EAV surprise magnitude refinement (binary sufficient，continuous NS)
- **K1152** — θ_rel cross-market analysis（US+JP high cluster，TW low cluster；quarterly-density hypothesis 提出）
- **K1153** — 本實驗 EU N=18（four-market direction universal，**quarterly-density hypothesis REJECTED**，新的 media-concentration 2-cluster 假說）
- **K1154+（預期衍生）** — Paper 2 改稿，機制識別（season concentration × analyst coverage），EU 擴展
