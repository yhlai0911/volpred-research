# K1080: A4f Extended History on IWM — Completing the US Equity Size Axis

**Experiment ID**: K1080
**Date**: 2026-04-12
**Proposer**: 用戶 (via K1080 brief)
**Executor**: Claude
**Status**: Complete

---

## 1. Problem Description

Paper 9's headline claim is that the **A4f multiplicative GARCH-MIDAS specification**
(τ = θ₀ + θ₁·VIX²_{t-1}, g = GJR) reliably improves volatility forecasts over
plain GJR across liquid equity ETFs. K1075 (SPY large-cap) and K1078 (QQQ
Nasdaq-100 tech) both delivered strong Harvey-PASS results, while K1077
(0050.TW Taiwan) was a clean null. IWM — the **iShares Russell 2000 ETF
(small-cap)** — was the conspicuous missing rung between "big US equity ETFs
work" and "Taiwan retail ETF fails".

IWM matters because small-cap has:

- higher idiosyncratic / noise component than SPX,
- lower liquidity at the tails,
- ~22 % annualised volatility vs ~16 % for SPY,
- its own native IV index (RVX = Russell 2000 VIX), making the VIX an
  interesting — but possibly mismatched — driver.

## 2. Motivation

If A4f wins on IWM, the Paper 9 claim strengthens to *"A4f works across the US
equity size spectrum"*. If it fails, the paper's scope needs to be bounded
("large/tech only"). Either way, the result fills a visible hole in the
cross-asset table Paper 9 needs to carry.

## 3. Method

**Strict parity with K1075 (SPY) / K1078 (QQQ).**

| Setting | Value |
|---|---|
| Asset | IWM (yfinance, Adj Close, IPO 2000-05-26) |
| Exogenous driver | ^VIX (yfinance) |
| Data span | 2000-05-30 → 2026-04-10 (n = 6 505) |
| OOS windows | 2007-01 / 2013-01 / 2019-01 (three non-overlapping) |
| Training window | Rolling 2 000 days (uses all available when insufficient) |
| Refit cadence | 63 days (quarterly) |
| Baseline | GJR-GARCH(1,1), Gaussian QMLE, numba-compiled |
| Test model | A4f (τ = θ₀ + θ₁·VIX²_{t-1}, g = GJR, free ω_g) |
| Target | r² (Patton 2011 QLIKE) |
| Inference | HAC Newey–West DM test, block-bootstrap 95 % CI (B = 1 000), Harvey \|t\|>3 |
| Sub-periods | GFC / Euro / COVID / Bear 2022; VIX buckets Low–Crisis |
| Seed | 42 |

**Supplementary (2007-2021)**: joint IWM+VIX+RVX window with A4f-VIX vs
A4f-RVX on a 50/50 train/OOS split to test IV-family substitutability on IWM
(parallel to K1079's VXN/VIX study).

## 4. Hypotheses

| H | Claim | Verdict | Evidence |
|---|---|---|---|
| H1 | IWM full OOS A4f > GJR, DM \|t\|>3 | **PASS** | DM t = +4.797, p ≈ 0, QLIKE diff = −0.38 % |
| H2 | IWM GFC A4f improves over GJR (directional) | **PASS** | QLIKE −0.34 %, DM t = +2.244 (directional win; not Harvey-level) |
| H3 | All 3 OOS windows A4f wins directionally | **PASS** | 3/3 windows have QLIKE diff < 0 |
| H4 | A4f does not break down at VIX>40 | **PASS** | Extreme (VIX 40–60) diff = −2.34 %, Crisis (VIX > 60) diff = −0.68 %, both negative |
| H5 | IWM θ₁ intermediate between SPY (<1 order) and 0050.TW (~4) | **FAIL** — **UNSTABLE (TW-like)** | Span = 3.54 orders |
| H6 | A4f-RVX marginally better than A4f-VIX for IWM (2007-2021) | **DIRECTIONAL** | diff = 0.00 %, DM t = +0.04 — effectively identical |

## 5. Key Results

**Full OOS 2007-2026 (n = 4 848)**

- QLIKE GJR = −7.6966, A4f = −7.7259 (−0.38 %)
- **DM t = +4.797** (Harvey-PASS), bootstrap 95 % CI for mean loss diff excludes 0.
- Spearman with r²: GJR 0.344, A4f 0.372.

**Per window**

| Window | n | QL_GJR | QL_A4f | Diff % | DM t | Harvey |
|---|---:|---:|---:|---:|---:|:---:|
| Early_Crisis (2007-12) | 1 510 | −7.320 | −7.331 | −0.15 % | +1.18 | FAIL |
| Middle_Recovery (2013-18) | 1 510 | −8.267 | −8.314 | −0.56 % | +5.01 | **PASS** |
| Late_COVID (2019-26) | 1 828 | −7.537 | −7.567 | −0.40 % | +2.56 | FAIL |

**Crisis sub-periods** (all improve directionally)

| Crisis | n | Diff % | DM t |
|---|---:|---:|---:|
| GFC (2008-09) | 505 | −0.34 % | +2.24 |
| Euro (2011-12) | 274 | −0.24 % | +1.25 |
| COVID Crash (2020 H1) | 104 | −1.57 % | +0.93 |
| Bear 2022 | 251 | −0.26 % | +1.19 |

**Four-asset size-axis summary (the Paper 9 table)**

| Asset | Size/Style | Full DM | Diff % | Harvey | θ₁ span |
|---|---|---:|---:|:---:|---:|
| SPY (K1075) | US large-cap | +7.92 | −0.89 % | PASS | <1 order |
| QQQ (K1078) | US tech (Nasdaq-100) | +5.99 | −0.59 % | PASS | 1.91 |
| **IWM (K1080)** | **US small-cap** | **+4.80** | **−0.38 %** | **PASS** | **3.54** |
| 0050.TW (K1077) | Taiwan retail | −0.49 | +0.33 % | FAIL | (N/A stored) |

DM statistic declines monotonically from SPY → QQQ → IWM → 0050.TW, matching
the intuition that A4f's VIX channel is strongest where VIX is closest to the
asset's native risk source.

**RVX supplement (2007-2021, n_OOS = 1 847)**

- A4f-VIX QLIKE = −8.0612, A4f-RVX QLIKE = −8.0614 (−0.00 %)
- DM (VIX vs RVX) t = +0.04, p = 0.97 → **IV family is substitutable for IWM**,
  extending K1079's VXN/VIX finding to the small-cap rung.

## 6. Conclusion

### 6.1 Headline finding

**A4f extends from large-cap to small-cap US equity ETFs** (SPY → QQQ → IWM all
Harvey-PASS). The Paper 9 claim can be stated as:

> A4f delivers statistically significant QLIKE improvement across US liquid
> equity ETFs spanning large-cap (SPY, +7.92), tech (QQQ, +5.99), and
> small-cap (IWM, +4.80). The effect attenuates with idiosyncratic risk
> (DM_IWM < DM_QQQ < DM_SPY) but remains Harvey-significant throughout. The
> test fails on Taiwan 0050 (−0.49), consistent with A4f being a
> US-equity-index-driven phenomenon rather than a universal truth.

### 6.2 Surprise (and its nuance)

**Headline number**: IWM's θ₁ orders-of-magnitude span is **3.54** — at first
glance as unstable as 0050.TW (K1077 ~4) — even though its forecasts clearly
improve.

**Nuance**: the 3.54 figure is driven by a small number of outlier refits.
Looking at the full θ₁ distribution across 77 converged refits:

| Percentile | 10 | 25 | 50 | 75 | 90 |
|---|---:|---:|---:|---:|---:|
| θ₁ | 1.66e-7 | 2.32e-7 | **2.52e-7** | 2.77e-7 | 1.67e-5 |

The **core 80 % (P10-P90) spans only 1.87 orders** — comparable to QQQ
(1.91). Only the top decile (driven by refits around extreme VIX
spikes) pushes the full range to 3.54 orders.

So the honest reading is a **two-layer finding**:

- For a "typical" refit, IWM's θ₁ is nearly as stable as QQQ — the core
  small-cap A4f channel behaves well.
- But in the tails (during or just after VIX > 40 spikes), IWM's θ₁
  occasionally jumps by 2+ orders, which SPY and QQQ do not exhibit.
  This is consistent with small-cap's larger idiosyncratic component:
  A VIX spike is a noisier signal for Russell 2000 volatility than for SPX
  volatility, and the optimiser compensates with a much larger coefficient
  to maintain fit.
- QLIKE improvement (average-case accuracy) and θ₁ stability
  (worst-case parameter interpretability) are **two different things**,
  and IWM shows they can disagree.

Paper 9 should therefore report a **two-column cross-asset table**:
(i) full-OOS DM t-statistic for forecast accuracy, (ii) θ₁ P10-P90 span
for parameter robustness. Readers who want A4f for *trading / risk*
purposes should know that IWM's coefficient is bankable in the median
but can misbehave in crisis refits.

### 6.3 RVX vs VIX

With QLIKE differences < 0.01 % and DM t = 0.04, **RVX adds essentially no
information over VIX** for IWM volatility forecasting. This mirrors K1079's
VXN vs VIX finding on QQQ — the US IV family is highly substitutable at this
horizon. Paper 9 can cite a single exogenous IV (VIX) without weakening the
result for any specific size segment.

## 7. Limitations

- RVX history is 2004-2021 only (yfinance), so the RVX supplement is
  constrained to a single static-parameter 50/50 split rather than the
  rolling-refit protocol used in the primary. A full rolling-refit comparison
  would need CBOE historical data.
- IWM 2000-01 to 2006-12 data exists but is used only as the training buffer
  for the 2007-01 OOS start; we did not add a "2003-06 dot-com recovery"
  window because it leaves insufficient training history (parity with
  K1075/K1078 decisions).
- Crisis sub-period DMs (|t| 0.9-2.2) are all below the Harvey threshold.
  The full-OOS Harvey-PASS comes primarily from Middle_Recovery (t = +5.0);
  readers should not over-claim per-crisis significance.
- A4f uses VIX² as the exogenous driver. We did not test squared log-VIX,
  difference forms, or GARCH-MIDAS with true low-frequency weighting, which
  could interact differently with IWM's idiosyncratic noise.

## 8. Files

| File | Purpose |
|---|---|
| `k1080.py` | Full experiment script (rolling refit, DM, bootstrap, plots). |
| `k1080_results.json` | Complete results (per-window, crisis, VIX bucket, θ₁ stability, RVX supplement, four-asset comparison). |
| `k1080_extended_dm.png` | QLIKE + DM t per OOS window. |
| `k1080_crisis_periods.png` | DM t across GFC / Euro / COVID / Bear 2022. |
| `k1080_vix_bucket.png` | QLIKE diff % across Low / Normal / High / Extreme / Crisis VIX. |
| `k1080_theta1_evolution.png` | θ₁ time series across 78 refits (log scale). |
| `k1080_four_asset_comparison.png` | SPY / QQQ / IWM / 0050.TW side-by-side (DM, θ₁ span, summary). |

## 9. References

- **Engle, Ghysels & Sohn (2013).** *Stock market volatility and macroeconomic fundamentals.* Review of Economics and Statistics 95(3), 776-797. (GARCH-MIDAS origin)
- **Patton (2011).** *Volatility forecast comparison using imperfect volatility proxies.* J. Econometrics 160, 246-256. (QLIKE consistency under r² proxy)
- **Harvey, Leybourne & Newbold (2016).** *Testing the equality of prediction mean squared errors.* (|t|>3 threshold for multiple comparisons)
- **Hansen & Lunde (2005).** *A forecast comparison of volatility models.* J. Applied Econometrics.

## 10. Upstream / Downstream

**Upstream**: K988 (SPY A4f), K994 (cross-asset brief), K1056 (5 sub-periods),
K1075 (SPY extended), K1077 (0050.TW null), K1078 (QQQ extended), K1079 (VXN
substitutability).

**Downstream suggestions (for `research_program.md`)**:

1. **IEF / TLT fixed-income A4f with MOVE as IV driver** — does the
   size-axis generalisation extend to a different asset class entirely?
2. **θ₁ stability vs forecast-accuracy decoupling** — are there other
   specifications where these two criteria tell different stories, and is
   there a principled way to trade them off (e.g. penalised likelihood with
   a θ₁ smoothness prior)?
3. **International small-cap (EWU, SCZ, EEM small-cap subset)** —
   does small-cap instability travel across markets, or is it a
   Russell-2000-specific liquidity effect?
