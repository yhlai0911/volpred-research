# K1618 — Realized Semicovariance (P/N/M) as a Cross-Asset Correlation-Regime Early-Warning Signal

**Verdict: `NULL_WITH_WEAK_SECONDARY`** — the pre-registered core hypothesis is
**not supported**; one weak, non-robust secondary signal survives.

- ⏱ Run date: 2026-07-04 (Taiwan time)
- Data: yfinance daily adjusted closes, 10 cross-asset ETFs, **2005-01-03 → 2026-06-30**
- Sample: 5,406 trading days → **257 non-overlapping 21-day windows**; **196 OOS windows** (~monthly, post 60-window burn-in)
- Reproduce: `uv run python K1618.py` (seed = 42, prices cached to `prices_cache.csv`)

---

## 1. Motivation & Differentiation

Bollerslev, Li, Patton & Quaedvlieg (2020, *Econometrica*) decompose realized
covariance into signed components using the sign of the underlying returns:

- **P** (concordant positive): both assets up together — `Σ r_i⁺ r_j⁺`
- **N** (concordant negative): both assets down together (downside co-movement) — `Σ r_i⁻ r_j⁻`
- **M** (discordant/mixed): one up, one down — `Σ (r_i⁺ r_j⁻ + r_i⁻ r_j⁺)`, with `M ≤ 0`

so that `RCov = P + N + M`. Their follow-up work on **realized semibetas**
(Bollerslev, Patton & Quaedvlieg 2022, *JFE*) shows the **negative (downside)
component carries the strongest risk premium**, and the asymmetric-correlation
literature (Longin & Solnik 2001, *JoF*; Engle 2002 DCC, *JBES*) documents that
cross-asset correlations rise precisely in down markets.

**Pre-registered core hypothesis (H1):** across a cross-asset ETF panel, the
**N component (negative-concordant semicovariance) is an *earlier / better*
predictor of a future correlation-regime break (or cross-asset volatility spike)
than total realized covariance `RCov` or total realized variance `RV`.** If true,
downside co-movement would be an actionable correlation-regime early-warning
signal for risk management.

**Differentiation vs prior VolPred work:** K1355 studied cross-asset HAR-RV
forecasting (loss pooling), K446/K1121 studied macro/alt-data early warning.
No prior K decomposes realized covariance into BPQ signed components or tests the
N-component-as-correlation-regime-signal hypothesis. This is the first
semicovariance experiment in the program.

---

## 2. Literature (≥3)

1. **Bollerslev, Li, Patton & Quaedvlieg (2020)**, "Realized Semicovariances",
   *Econometrica* 88(4), 1515–1551. — Defines the P/N/M signed decomposition;
   N (down-down) carries distinct predictive content for future covariance.
   *(The task brief cited this as "JoE"; the correct venue is Econometrica —
   corrected here per research-honesty.)*
2. **Bollerslev, Patton & Quaedvlieg (2022)**, "Realized semibetas:
   Disentangling 'good' and 'bad' downside risks", *Journal of Financial
   Economics* 144(1), 227–246. — Downside/negative semibeta is the priced risk;
   validates daily-frequency realized-semibeta construction.
3. **Longin & Solnik (2001)**, "Extreme Correlation of International Equity
   Markets", *Journal of Finance* 56(2), 649–676. — Correlations rise in bear
   markets (downside), not symmetric bull/bear — the economic basis for H1.
4. **Engle (2002)**, "Dynamic Conditional Correlation", *JBES* 20(3), 339–350. —
   Time-varying / regime-switching correlation; the object we try to forecast.
5. Methodology: **Patton (2011)** proxy-robust QLIKE; **Diebold & Mariano
   (1995)** + **Harvey, Leybourne & Newbold (1997)** small-sample DM correction.

---

## 3. Data & Construction

**Panel (10 ETFs, stock/bond/commodity/region — designed to produce correlation
regime switches):** SPY, QQQ, IWM, EFA, EEM, TLT, GLD, XLF, XLK, XLE. All 10 have
complete data over 2005-01-03 → 2026-06-30 (no gaps), covering the **2008 GFC,
2020 COVID, and 2022 bear** regimes (OOS spans multiple bear markets).

**Frequency — daily, not high-frequency (fidelity caveat, see §7).** Log returns
are aggregated within **non-overlapping 21-trading-day (~monthly) windows** to form
monthly realized semicovariances — the daily-frequency realized-semibeta
convention of BPQ (2022). For each window and each of the C(10,2)=45 asset pairs
we compute P_ij, N_ij, M_ij, RCov_ij, then take the panel average across pairs.
Total RV = mean over assets of `Σ r_i²`. The realized cross-asset correlation
target is the mean of the 45 off-diagonal Pearson correlations within the window.

**Identity check:** `max |RCov_ij − (P_ij+N_ij+M_ij)| = 2.8e-17` across all
45×257 = 11,565 pair-windows → identity holds to machine precision. ✓

---

## 4. Method (formal tests)

1. **Descriptive:** lead-lag correlations of each component (window `w`) vs future
   (window `w+1`) correlation and RV.
2. **In-sample HAC predictive regressions** (Newey-West, auto-bandwidth) of future
   correlation / RV on each component, plus incremental-N-over-persistence and
   N/P/M decomposition regressions.
3. **OOS expanding-window forecasts + Diebold-Mariano (HLN-corrected):**
   univariate OLS forecast of target `w+1` from predictor `w`, for predictors
   **N vs RCov vs RV vs naive persistence**. Loss = **MSE** for the correlation
   target (can be negative), **QLIKE** (`actual/pred − log(actual/pred) − 1`, via
   `volpred.stats.model_evaluation.qlike_pointwise`) for the RV target.
   DM with HLN small-sample factor + Student-t reference; moving-block bootstrap
   (seed 42, 2000 reps) 95% CI on the mean loss differential.
4. **Regime-break classification:** binary spike label = target `w+1` exceeds the
   **training-only** 80th percentile; OOS discrimination via rank-based AUC for
   N / RCov / RV, with a 1000-rep bootstrap CI on AUC(N) − AUC(RCov).
5. **K1355-compliant cross-pair robustness:** per-pair OOS forecast of future
   pair-RCov (N vs RCov), loss differentials **date-aggregated across the 45 pairs
   per window before** the DM; the stacked pair-window DM is reported *only* as a
   diagnostic.

## 4b. 防錯規則遵守聲明 (anti-error compliance)

- **Lookahead (highest risk):** predictor from window `w`, target from
  strictly-later non-overlapping window `w+1`. OOS training rows use
  `{(X_k, Y_{k+1}) : k+1 ≤ w}` — every training target window ends strictly before
  the forecast origin (end of window `w`), i.e. `target_end < forecast_origin`
  (equivalently the row-`j` label window `j+H < i`). Verified: zero clipped/
  negative RV forecasts; truth series identical across predictors.
- **K1355 cross-asset pooling:** PRIMARY inference is on a **panel-aggregate
  series (one value per window)** → no asset-day stacking by construction. The
  cross-pair variant **date-aggregates** the loss differential before DM; stacked
  pair-window DM is diagnostic only (and is likewise null here).
- **K783c QLIKE direction:** canonical `actual/predicted − log(actual/predicted) − 1`
  via the shared `qlike_pointwise`; no hand-written inverse QLIKE.
- **K1216b symmetric spec:** N / RCov / RV predictors use the *identical*
  univariate-OLS functional form (OLS forecast is invariant to affine rescaling of
  a single regressor, so no standardisation asymmetry).
- **Harvey (2016) multiple-testing bar** `|t| > 3.0` reported alongside standard
  `p < 0.05`; **HLN (1997)** small-sample factor applied on the HAC DM.
- **Seeds fixed** (seed = 42) for every bootstrap / resample.
- **Horizon discipline:** single H=1 (next window); DM HAC horizon = H.

---

## 5. Results

### Identity & structure
- Identity `RCov = P+N+M` holds to 2.8e-17. Panel means: **N=0.00145 > P=0.00132**,
  M=−0.00055 → downside co-movement dominates upside (BPQ asymmetry confirmed
  *structurally*). Realized cross-asset correlation ranges [0.113, 0.738]
  (median 0.427) with clear crisis spikes.

### CORE hypothesis (future CORRELATION regime) — NOT SUPPORTED
| Test | N | RCov | RV |
|---|---|---|---|
| Lead-1 corr vs future correlation | 0.136 | **0.156** | 0.141 |
| OOS AUC (correlation spike, 28/196) | **0.546 (worst)** | 0.572 | 0.581 |
| OOS MSE (future correlation) | 0.01186 | **0.01180** | 0.01182 |

- OOS DM **N vs RCov** (correlation target): HLN t = **+1.52**, p = 0.131,
  better = **RCov** (not N; insignificant).
- OOS DM **N vs RV**: HLN t = +0.84, p = 0.404, better = RV.
- In-sample incremental N over correlation-persistence: t = 1.78, **p = 0.074**
  (not significant at 5%).
- AUC(N) − AUC(RCov) = −0.025, bootstrap 95% CI [−0.089, +0.035] (includes 0).

**N is the *weakest* of the three predictors for correlation-regime spikes.**

### SECONDARY (future cross-asset RV) — weak, non-robust
- OOS DM **N vs RCov** (RV target, QLIKE): HLN t = **−2.53, p = 0.012**, better = N;
  bootstrap CI on mean loss diff [−0.040, −0.006] **excludes 0**. → N beats the
  *total* RCov for forecasting next-month volatility, consistent with the BPQ
  "downside component carries the vol signal" thesis.
- **But** N does **not** beat simple total RV: DM t = +0.87, p = 0.384 (RV wins);
  and it clears **no** Harvey `|t| > 3` bar. OOS AUC (RV spike): N = 0.783 vs
  RCov = 0.768 vs **RV = 0.803** — RV still best.

### Cross-pair robustness (K1355) — null
- Date-aggregated N vs RCov (future pair-RCov): HLN t = **−0.21, p = 0.835** (null).
- Stacked pair-window diagnostic: t = −0.81 (also null; would have *over*stated SE
  if abused as primary — the K1355 discipline changes nothing here because there is
  no edge to inflate).

Figures: `fig_a_components_timeseries.png` (P/N/M + correlation with GFC/COVID/2022
shading), `fig_b_predictive_power.png` (OOS AUC + forecast-loss bars),
`fig_c_event_windows.png` (normalized N vs correlation around the three crises).

---

## 6. Verdict

**`NULL_WITH_WEAK_SECONDARY`.** The pre-registered claim — that negative-concordant
semicovariance is a *superior* early-warning signal for cross-asset correlation
regimes — is **rejected**: at daily frequency the N component is, if anything, the
*weakest* of N/RCov/RV on the correlation-spike target, and never beats total RCov
or total RV significantly there. The only positive is a **secondary, non-robust**
finding: N modestly beats the *total* RCov (but not total RV, and below the Harvey
bar) for forecasting next-month cross-asset volatility — an echo of BPQ's downside
result, not a correlation-regime signal. Reported honestly as a null; no
overclaim.

---

## 7. Limitations (honest)

- **Daily vs high-frequency fidelity gap (most important).** BPQ (2020) realized
  semicovariances are defined on *intraday* returns; N/P/M are theoretically
  identified as spot-covariance objects only in the high-frequency limit. Here we
  use **daily** returns within monthly windows (the BPQ-2022 daily semibeta
  convention). With only 21 daily observations per window the components are noisy
  estimates of the intraday objects, and the sign decomposition captures far less
  of the fine co-jump / diffusive structure that HF data reveal. A genuine
  intraday (e.g. 5-min) implementation could plausibly recover a signal this daily
  proxy cannot — this experiment does **not** rule out the HF version of H1.
- **Correlation itself is highly persistent**, so any component beating a naive
  mean is unremarkable; the honest benchmark is total RV (persistence), which N
  fails to beat. R² of the correlation regressions is tiny (~0.02).
- **N is scale-confounded with volatility**: high N reflects both high correlation
  *and* high volatility, so its modest RV-forecast edge over RCov is more a
  volatility statement than a correlation statement.
- **Non-overlapping monthly windows** give ~196 OOS points; a rolling-window design
  would add observations but require h=21 HAC and reintroduce overlap dependence.
- **Threshold/quantile spike definition** (top-quintile) is one of several
  reasonable regime-break operationalisations; results may differ for
  break-detection (e.g. CUSUM/HMM) targets.
