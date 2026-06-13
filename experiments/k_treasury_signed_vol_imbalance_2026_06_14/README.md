# K_treasury_signed_vol_imbalance_2026_06_14 — Treasury daily signed-volume imbalance pilot

**Status**: CONDITIONAL_PASS (1/6 marginal at uncorrected α=0.05, fails Bonferroni)
**Date**: 2026-06-14
**Author**: Claude (experiment subagent, opus high)
**Data**: yfinance daily TLT / IEF / ZN=F / SPY, 2015-01-02 ~ 2026-06-12 (2,763–2,877 daily obs)

## Problem & Motivation

Treasury market participants are dominated by central banks, dealers, and large
asset managers; their daily flow imbalance is a candidate macro-information
proxy. We test whether **daily signed-volume imbalance** on three Treasury
proxies (TLT 20+yr ETF, IEF 7-10yr ETF, ZN=F 10yr futures) predicts:

- **H1 (self-predict)**: next-day RV of the same instrument
- **H2 (spillover)**: next-day RV of SPY (US equity benchmark)

The mechanism would be: large directional Treasury flow today reflects a macro
news / risk-off impulse → vol propagates one day forward. If true, the signal
is exploitable for daily vol-targeting strategies and cross-asset RV models.

## Differentiation from prior knowledge

| K | Setup | This work's distinct angle |
|---|-------|---|
| **K1124** | TAIFEX TX intraday 5-min OFI with Lee-Ready pure-tick rule; H1 = magnitude effect on intraday RV | We use **daily** aggregation on **US Treasury** (not TW equity), no tick rule needed, and test **cross-day, cross-asset** spillover |
| **K1127** | TAIFEX TX × ES intraday 1h OFI cross-market lead-lag | We use **daily volume sign** (not OFI / tick rule) on **Treasury → equity** channel, not within-Asia or US-overnight |

Key conceptual narrowing: at daily horizon with no intraday tick data, we can
only compute `sign(return_t) × volume_t / volume_t = sign(return_t)`, so the
"imbalance" here collapses to a sign indicator. We retain the normalised
form for definitional fidelity and document this as a known limitation
(see §Limitations).

## Method

### Data
- yfinance daily OHLCV
- Period: 2015-01-01 → 2026-06-13 (hard `CAP_DATE` to prevent lookahead on today's incomplete bar)
- Tickers: TLT, IEF, ZN=F, SPY
- Rows after clean (drop NaN, drop 0-volume): TLT 2,878; IEF 2,878; ZN=F 2,870; SPY 2,878
- yfinance failure raises (no silent fallback)

### Features (per ticker)
```
ret_t            = log(close_t / close_{t-1})
signed_vol_imb_t = sign(ret_t) * volume_t / volume_t   ∈ [-1, +1]
                   (0-return ties: carry forward last nonzero sign)
RV_t             = ret_t^2
```

### Models (Newey-West HAC OLS, L=5)

H1, for X ∈ {TLT, IEF, ZN=F}:
```
log(RV_{t+1}^X) = a + b · signed_vol_imb_t^X + c · log(RV_t^X) + ε_t
```

H2, for X ∈ {TLT, IEF, ZN=F}:
```
log(RV_{t+1}^SPY) = a + b · signed_vol_imb_t^X + c · log(RV_t^SPY) + ε_t
```

### Lookahead safeguards
- `signed_vol_imb_t` and `log(RV_t)` are time-t (strictly past relative to target)
- target `log(RV_{t+1})` uses `.shift(-1)` on RV → drops the last row
- `CAP_DATE = 2026-06-13` blocks any partial 2026-06-14 bar

### Significance
- HAC (Newey-West, lags=5) two-sided |t| > 2.0
- Block bootstrap (block_len=20, B=5,000, seed=42), p < 0.05
- Bonferroni across 6 tests: α = 0.05/6 ≈ **0.00833**

### Seeds
`numpy.random.seed(42)`, `np.random.default_rng(42)` for bootstrap.

## Results

### H1 — Self-predict (3 tests)

| Asset | n | β | HAC SE | HAC t | HAC p | Boot p | Bonf 0.00833? |
|---|---|---|---|---|---|---|---|
| TLT   | 2,848 | **-0.0965** | 0.0393 | **-2.45** | 0.014 | **0.012** | ✘ (marginal) |
| IEF   | 2,831 | -0.0508 | 0.0372 | -1.36 | 0.173 | 0.190 | ✘ |
| ZN=F  | 2,763 |  0.0255 | 0.0370 |  0.69 | 0.492 | 0.499 | ✘ |

### H2 — Spillover Treasury → SPY (3 tests)

| Treasury | n | β | HAC SE | HAC t | HAC p | Boot p | Bonf 0.00833? |
|---|---|---|---|---|---|---|---|
| TLT  | 2,864 | -0.00000 | 0.0414 | -0.00 | 1.000 | 1.000 | ✘ |
| IEF  | 2,864 |  0.0442  | 0.0453 |  0.98 | 0.329 | 0.316 | ✘ |
| ZN=F | 2,854 |  0.0530  | 0.0450 |  1.18 | 0.238 | 0.229 | ✘ |

### Interpretation

Only **TLT self-predict** (H1) shows a marginal effect: a negative sign-of-return
indicator on day t predicts higher log-RV on day t+1, consistent with a
**daily-frequency leverage effect** on long-duration Treasuries (down days
followed by higher next-day vol). After Bonferroni correction for 6 tests,
this fails the gate (p=0.012 > 0.00833). IEF and ZN=F show the same sign
but smaller magnitude and are NS individually. The H2 spillover channel
(Treasury → SPY) is uniformly **null**, with TLT spillover beta numerically
zero.

The TLT marginal effect overlaps with the well-known **asymmetric volatility
/ leverage effect** literature (Black 1976; Christie 1982; Engle-Ng 1993),
which a standard GJR-GARCH would already capture as a `1{r<0}·r²` term.
This experiment did not condition on log(RV_t) lag structure beyond a single
lag, nor compare to a GJR-GARCH baseline — so the marginal result on TLT
should be read as "daily sign of return predicts log-RV after controlling
for log-RV persistence" rather than "novel signed-volume imbalance signal."

## Verdict

**CONDITIONAL_PASS** — 1 marginal test (TLT H1, uncorrected p=0.012) fails
Bonferroni 0.00833 and overlaps known leverage-effect; H2 spillover is fully
null. Cannot claim "Treasury daily signed-volume imbalance predicts next-day
RV" as a novel signal at the daily horizon under standard multiple-testing
discipline.

## Limitations & next steps

1. **Signal collapses to sign(return) at daily horizon**: because
   `signed_volume / total_volume = sign(return)` with no intraday tick data,
   the "imbalance" is binary-valued (modulo 0-return ties). Magnitude
   information is lost. To revive the original mechanism, intraday data is
   required (cf. K1124's Lee-Ready tick rule on TAIFEX or trade-side data
   on TRACE for Treasuries).
2. **TLT marginal effect ≈ leverage effect**: a clean test would compare
   incremental forecast power vs GJR-GARCH or HAR-RV with leverage term.
3. **Alternative RV proxy**: replace `ret^2` with Garman-Klass `(0.5·(log H/L)^2 - (2·log2−1)·(log C/O)^2)` for lower-noise RV.
4. **TRACE Treasury data**: dealer-vs-customer signed-volume in cash Treasuries
   would carry information beyond price-sign and is the proper version of
   this hypothesis at the macro level.

## Files

- `k_treasury_signed_vol_imbalance_2026_06_14.py` — reproducible script (seed=42)
- `results.json` — full statistics + bootstrap CI + configuration
- `fig_h1_self_predict.png` — 3-panel H1 scatter
- `fig_h2_spillover.png` — 3-panel H2 scatter

## Reproducibility

```
uv run python experiments/k_treasury_signed_vol_imbalance_2026_06_14/k_treasury_signed_vol_imbalance_2026_06_14.py
```

Runtime ~12s on M-series Mac (yfinance fetch dominates).
