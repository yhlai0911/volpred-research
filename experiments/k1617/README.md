# K1617: Time-Varying Factor Loading (TVL) Factor-Augmented HAR vs Static-Loading HAR

**Verdict: NULL** (for the primary hypothesis) — a *time-varying* factor loading does
**not** significantly improve HAR-RV forecasts over either a plain HAR or a *static*
factor-augmented HAR. The TVL-rescue hypothesis is rejected. A modest, economically
negligible **secondary** finding: the *static* common factor does significantly (but
tiny, ~0.7% pooled QLIKE) beat HAR in this HAR/range-RV setting — a framework-dependent
nuance relative to K928's GJR/daily-r² null.

---

## Research question & motivation

K928 (Factor-Augmented GJR-GARCH, PCA common volatility factor across
SPY/QQQ/IWM/GLD/TLT, daily r²) concluded that a **static** common-volatility factor
adds no incremental predictive value and is redundant with VIX. This experiment asks a
narrower, targeted question:

> Is K928's null a consequence of the loading being constrained to be **static**? If the
> factor loading is allowed to be **time-varying** (γ_t), does the common factor recover
> incremental predictive power inside a **HAR-RV** framework?

The honest prior (from K928) was that the result would likely remain null. It does — for
the time-varying loading. The value of the experiment is a clean three-model OOS contrast
with correct testing and an honest verdict, not "winning."

### Differentiation vs K928
| | K928 | K1617 |
|---|---|---|
| Framework | Factor-Augmented **GJR-GARCH** | **HAR-RV** (Corsi 2009) |
| Target | daily **r²** (close-to-close, chi-sq noisy) | **Garman-Klass range-based RV proxy** (log-RV) |
| Loading | **static** only | **static vs time-varying (γ_t)** direct contrast |
| Factor | rolling-PCA PC1 (250d) | rolling-PCA PC1 (250d) — same construction |
| Panel | SPY/QQQ/IWM/GLD/TLT 2006–2026 | SPY/QQQ/IWM/GLD/TLT 2012–2026 (same panel) |

---

## Data

- **Source**: yfinance daily OHLC (`auto_adjust=False`, **raw OHLC** — required for the
  range estimator; splits do not occur intraday so within-day OHLC is internally
  consistent). Cached to `data_ohlc.csv` for reproducibility.
- **Panel**: SPY, QQQ, IWM, GLD, TLT (same 5-asset US ETF panel as K928).
- **Period**: 2012-01-01 → 2026-06-30. Inner-join on common trading days →
  **3,642 common trading days** (2012-01-03 … 2026-06-29).
- **OOS**: expanding window, refit **daily**, OOS start **2017-01-01** →
  **2,384 OOS forecasts per asset** (11,920 asset-days). OOS spans 2018-Q4 vol, the
  2020 COVID crash, and the 2022 bear market (≥1 bear market, per project rule).

### ⚠️ Realized-variance measure — HONEST LABELLING
RV here is a **range-based realized-variance PROXY**, **not** an intraday 5-minute RV. We
do not have long high-frequency data (the only intraday file, `SPY_daily_rv.csv`, is ~5.5
months and unusable for a 14-year HAR OOS). Instead we compute the **Garman-Klass (1980)**
daily variance estimator from OHLC:

```
RV_GK_t = 0.5 · (ln(H/L))²  −  (2·ln2 − 1) · (ln(C/O))²
```

This is an **intraday open-to-close** variance proxy (GK ≥ 0 always). It is consistent
across all five assets and all three models, so the comparison is apples-to-apples within
the HAR family. It is **not** claimed to be intraday RV. References: Parkinson (1980);
Garman & Klass (1980); Alizadeh, Brandt & Diebold (2002).

---

## Method

Three models share an **identical HAR-RV core** (expanding OLS on log-RV, refit daily),
differing **only** in the factor contribution — a clean nested ladder that isolates the
loading:

1. **HAR** (Corsi 2009):
   `logRV_t = c + b_d·logRV_{t-1} + b_w·mean(logRV, t-5..t-1) + b_m·mean(logRV, t-22..t-1)`
2. **FA-HAR static**: `HAR core + γ · F_{t-1}`, where γ = **expanding** (full-history)
   through-origin slope of the HAR residual on the lagged factor.
3. **FA-HAR TVL**: `HAR core + γ_t · F_{t-1}`, where γ_t = **rolling-250d** slope of the
   HAR residual on the lagged factor.

Because static and TVL add the factor to the **same** HAR core using the **same**
estimator, the **only** difference between them is static (constant, full-history) vs
time-varying (rolling-250d) **loading** — exactly the object of interest.

- **Factor F**: rolling-250d PCA first principal component of the standardized cross-asset
  log-RV panel, sign-fixed (SPY loading positive), **OOS-extracted** (loadings and
  standardization use only data through the projection date). `F_{t-1}` predicts `logRV_t`.
  Same construction philosophy as K928.
- **Loading definition**: through-origin slope `Σ(resid·F)/Σ(F²)`. For the expanding
  window the HAR residuals are mean-zero by OLS construction, so this equals the OLS slope;
  for the rolling window it is a projection (near-identical since F is ~zero-mean).

### Anti-lookahead (highest-priority risk)
- `logRV_t` uses only info dated ≤ t-1: HAR lags via `shift(1)` + rolling, factor via
  `factor.shift(1)` → `F_{t-1}`.
- Rolling-PCA loadings/standardization use only data through the projection date.
- Expanding training rows for origin `i` are `slice(0, i)` (rows ≤ i-1); H=1 satisfies
  `target_end < forecast_origin` (last training label at date[i-1] < forecast date[i]).
- γ / γ_t regressions use only HAR residuals and factors dated ≤ i-1; rolling slice
  indices verified aligned.

### Evaluation
- **QLIKE** on the variance scale (canonical `actual/pred − log(actual/pred) − 1`, via
  `volpred.stats.model_evaluation.qlike` / `qlike_pointwise`). log-RV forecasts are mapped
  to variance with a **common log-normal (Jensen) correction** `exp(pred_logRV + 0.5·s²)`
  using the shared expanding HAR-core residual variance `s²`. The correction is identical
  across the three models on each date but does **not** algebraically cancel in the QLIKE
  differential; we therefore also report a **no-Jensen sensitivity** (`predicted_var =
  exp(pred_logRV)`) — the DM verdict is **invariant** to this choice.
- **log-RV MSE** (Jensen-free anchor).
- **DM test** with **Harvey-Leybourne-Newbold (1997)** small-sample correction, Student-t
  reference, threshold **|t| > 3.0** (Harvey 2016). **PRIMARY** inference aggregates the
  cross-asset loss differential **by date** first, then runs HLN on the date series
  (K1355: do **not** treat asset-days as iid). **Per-asset** DM also reported.
  **Stacked asset-day** DM is **diagnostic only** (overstates significance).

Reproducible: `uv run python experiments/k1617/k1617.py`. Seeded (`np.random.seed(42)`).

---

## Results

### OOS QLIKE (variance scale, lower = better) and log-RV MSE

**Pooled (all 11,920 asset-days):**

| Model | Pooled QLIKE | Pooled log-RV MSE |
|---|---|---|
| HAR | 0.32952 | 0.59810 |
| FA-static | 0.32716 | 0.59552 |
| FA-TVL | **0.32600** | **0.59452** |

**Per-asset QLIKE:**

| Asset | HAR | FA-static | FA-TVL |
|---|---|---|---|
| SPY | 0.3835 | **0.3827** | 0.3834 |
| QQQ | 0.3343 | **0.3332** | 0.3342 |
| IWM | 0.2709 | 0.2680 | **0.2688** |
| GLD | 0.3732 | 0.3719 | **0.3699** |
| TLT | 0.2858 | 0.2799 | **0.2737** |

The absolute differences are tiny (≤0.7% relative pooled). FA-TVL has the lowest *point*
QLIKE on GLD/TLT (bonds/gold), FA-static on SPY/QQQ/IWM — but see DM tests: none of these
differences is significant at |t|>3.0 except static-vs-HAR pooled.

### DM tests — HLN small-sample corrected, threshold |t| > 3.0

**PRIMARY (pooled cross-asset loss differential by date, n=2,384 dates):**

| Pair | HLN t | Harvey pass (|t|>3.0)? | Reading |
|---|---|---|---|
| TVL vs HAR | −1.59 | **No** | TVL not sig. better than HAR |
| TVL vs static | −0.72 | **No** | TVL **not** better than static |
| static vs HAR | **−3.19** | **Yes** | static factor sig. beats HAR (tiny) |

**Per-asset HLN t** (negative = first model better): TVL-vs-HAR / TVL-vs-static / static-vs-HAR

| Asset | TVL vs HAR | TVL vs static | static vs HAR |
|---|---|---|---|
| SPY | −0.01 | +0.38 | −1.22 |
| QQQ | −0.06 | +0.62 | −1.68 |
| IWM | −1.01 | +0.52 | −2.92 |
| GLD | −0.92 | −0.66 | −1.76 |
| TLT | −2.28 | −1.73 | **−3.09** |

The static factor's help is concentrated in **TLT** (t=−3.09) and **IWM** (t=−2.92); the
pooled-by-date significance is driven by these. TVL beats static on **no** asset at
|t|>3.0, and is actually slightly *worse* than static on SPY/QQQ (positive t).

**DIAGNOSTIC ONLY — stacked asset-day** (overstates significance; do not cite): TVL-vs-HAR
t=−2.37, TVL-vs-static t=−1.03, static-vs-HAR t=−4.88. The gap between stacked (−4.88) and
pooled-by-date (−3.19) for static-vs-HAR confirms the K1355 concern — stacked asset-days
overstate significance because same-date cross-asset losses share market shocks.

### Jensen-correction sensitivity (robustness)

The variance-scale Jensen correction does not cancel in the DM differential, so we re-ran
without it (`predicted_var = exp(pred_logRV)`):

| Pair | Primary (with Jensen) | No-Jensen |
|---|---|---|
| TVL vs HAR | −1.59 | −2.87 |
| TVL vs static | −0.72 | −2.56 |
| static vs HAR | −3.19 | −3.02 |

**Verdict is invariant**: the TVL hypothesis remains NULL under both (TVL vs HAR and vs
static stay below |t|>3.0), and static-vs-HAR stays significant. The Jensen choice moves
the TVL t-stats but does not change any pass/fail conclusion.

---

## Verdict

**NULL (primary hypothesis: time-varying loading does not rescue incremental power).**

- Time-varying loading does **not** significantly beat HAR (pooled-by-date HLN t=−1.59)
  nor static-FA (t=−0.72). The rolling loading adds **no** incremental value over a static
  loading — its noisier estimation, if anything, weakens the signal (TVL vs HAR t=−1.59 <
  static vs HAR t=−3.19).
- **Secondary** (framework-dependent nuance vs K928): the **static** factor augmentation
  does modestly but significantly beat HAR (pooled-by-date HLN t=−3.19, ~0.7% pooled
  QLIKE), concentrated in TLT/IWM. This is economically negligible and requires no
  time-varying loading. K928's GJR/daily-r² null does not carry over one-for-one to the
  HAR/GK-RV setting, but the common factor's value remains near-negligible.

This is consistent with the broader project finding that common cross-asset volatility
factors add little beyond own-asset persistence for individual-asset forecasting.

### Codex review
`codex exec` (gpt-5.5, xhigh) source review → **CONDITIONAL_PASS**. Lookahead (PCA/β_t/train
alignment), QLIKE direction, DM HLN correctness, seed, and GK-proxy labelling all PASS.
Three items flagged and **resolved**: (1) a false docstring claim that the Jensen
correction "cancels in every DM differential" — corrected, and a no-Jensen sensitivity run
was added that empirically confirms verdict invariance; (2) the verdict note wrongly
implied the static factor was also null — rewritten to be precise/conditional; (3) missing
README — this file. Reviewer source: **Codex CONDITIONAL_PASS (flagged items fixed)**.

---

## Limitations

1. **Range-based RV proxy, not intraday RV.** GK measures open-to-close range variance,
   not 5-min-sampled RV; it misses overnight variance and intraday microstructure. A
   genuine high-frequency RV panel could change magnitudes (K928 found smoothed 22-day RV
   gave much stronger common-factor structure than noisy daily r²).
2. **5-asset US-ETF panel** — external validity to other markets/asset classes untested.
3. **Rolling-window β bandwidth sensitivity** — γ_t uses a fixed 250-day window; the
   result could differ under Kalman/state-space filtering or other bandwidths (a Kalman
   robustness pass is a natural extension). Primary uses rolling-window as the more robust,
   transparent estimator.
4. **Two-step (residual-augmentation) design** isolates the loading cleanly but differs
   slightly from a joint FA-HAR OLS (Frisch-Waugh: the two-step slope loads on the raw
   factor, not the HAR-orthogonalized factor). A joint-rolling FA-HAR would also vary the
   HAR coefficients, confounding the loading question — hence the residual-augmentation
   choice.
5. **Through-origin loading** (no per-window intercept) for γ_t; near-identical to the OLS
   slope since F is ~zero-mean, but not identical for the rolling window.

---

## References
- Corsi (2009) *J. Financial Econometrics* 7 — HAR-RV
- Garman & Klass (1980) *J. Business* 53 — range-based variance estimator
- Parkinson (1980) *J. Business* 53 — high-low range estimator
- Alizadeh, Brandt & Diebold (2002) *J. Finance* 57 — range-based volatility
- Patton (2011) *J. Econometrics* 160 — proxy-robust QLIKE
- Harvey, Leybourne & Newbold (1997) *Int. J. Forecasting* 13 — small-sample DM correction
- Harvey et al. (2016) — |t|>3.0 multiple-testing threshold
- K928 (this project) — static common-vol factor null / VIX sufficiency
- K1355 (this project) — cross-asset loss differentials aggregated by date, not iid

## Files
- `k1617.py` — full reproducible, seeded experiment
- `k1617_results.json` — all metrics, DM t-stats, Jensen sensitivity, verdict, provenance
- `data_ohlc.csv` — cached raw OHLC (data provenance)
- `fig_rv_factor.png` — GK realized-vol proxy (SPY) + common PCA factor over time
- `fig_qlike_comparison.png` — pooled and per-asset OOS QLIKE, three models
- `fig_tvl_beta.png` — time-varying γ_t path vs static γ (SPY)
