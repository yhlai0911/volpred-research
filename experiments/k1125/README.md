# K1125 — OFI x Lee-Mykland Jump Detection on TAIFEX TX

**Status**: FAIL (triple threshold) but meaningful partial result
**Date**: 2026-04-13
**Author**: Claude (worktree agent-k1125)
**Data**: TAIFEX TX futures 5-min bars 2017-2021 (via K1124 cached 73,203 bars)

## Problem & Motivation

K1124 established a surprising stylized fact on TAIFEX: **|OFI| high -> next 5-min diffusive RV LOWER** (mean-reversion, opposite to US-market intuition). That finding used total 5-min RV as target.

This experiment asks a different question: **do high-|OFI| bars predict JUMPS** (discrete tail events) even if they fail to predict diffusive vol? Jumps and continuous diffusion have different economic mechanisms — large |OFI| may reflect informed traders filling orders, making a price jump in the next bar more likely.

Lee & Mykland (2008) provide a nonparametric jump test on tick-level 5-min bars:
```
L_t = |r_t| / sigma_hat_t
```
where sigma_hat_t is a rolling bipower variation (BV) estimate. Under the null (no jump), L_t converges to a known distribution and bar-level tests with a Gumbel-adjusted threshold identify jumps at level alpha.

## Data & Method

- **Source**: Cached 5-min bars from K1124 (TAIFEX TX day session 08:45-13:44:59)
- **Bars**: 73,203 across 1,223 trading days, 2017-01-03 to 2021-12-30
- **Active contract selection**: inherited from K1124 (T-1 rolling volume, no selection lookahead)

### Lee-Mykland Jump Detection
- Window K = 16 returns (strictly past)
- BV formula: `BV_t = (1/(K-1)) * (1/mu1^2) * sum_{j=t-K+1}^{t-1} |r_{j-1}||r_j|`, where mu1 = sqrt(2/pi)
- This covers K-1 pair products from returns r_{t-K},...,r_{t-1} (K past returns, strictly before r_t).
- Threshold: Gumbel-adjusted multi-test at alpha = 0.01:
  `C_n + S_n * beta_n` where `C_n = sqrt(2 log n) - 0.5 (log log n + log 4pi) / sqrt(2 log n)`, `S_n = 1/sqrt(2 log n)`, `beta_n = -log(-log(1-alpha))`.
  For n=53,635 valid obs -> threshold = **5.126**
- Jump rate detected: **0.21%** (114 jumps in OOS — consistent with Lee-Mykland 2008 reports of ~0.5% on S&P 5-min)

### Models (strict lag-1, no same-bar leak)
All features are at bar t; target is `jump_{t+1}` (next bar's jump indicator):

| Model | Features |
|---|---|
| **M0** | constant (base rate) |
| **M1** | `jump_curr` (lagged jump indicator) — baseline |
| **M2** | M1 + `|OFI|_t` — H1 magnitude |
| **M3** | M2 + `OFI_t` (signed) — H2 asymmetry |
| **M4** | M3 + `vix_lag1_z`, `|OFI|_t * vix_lag1_z` — H3 regime |

- VIX: previous US trading day's ^VIX close (lag-1; TAIFEX day session opens 08:45 local, after US close)
- VIX z-score: standardized using **IS-only** mean/std (2017-2019) to avoid OOS leakage
- IS: 2017-2019 (31,498 bars); OOS: 2020-2021 (20,914 bars)
- Logistic regression, L2 regularized (C=1.0), seed 42

## Results (after Codex fix)

### OOS Comparison

| Model | AUC IS | AUC OOS | Brier OOS | LL OOS |
|---|---|---|---|---|
| M0 constant | 0.5000 | 0.5000 | 0.001576 | -0.01198 |
| **M1 lag jump** | 0.5111 | **0.5144** | 0.001575 | -0.01190 |
| M2 + \|OFI\| | 0.5645 | 0.5213 | 0.001574 | -0.01181 |
| **M3 + signed OFI** | **0.5920** | **0.5545** | 0.001574 | -0.01173 |
| M4 + VIX regime | 0.5880 | 0.4919 | 0.001576 | -0.01200 |

### DM Tests on Log-Likelihood (Newey-West HAC, positive t = latter model better)

| Comparison | t | mean delta LL |
|---|---|---|
| M2 vs M1 | +1.98 | +9.2e-05 |
| **M3 vs M2** | **+2.55** | +7.9e-05 |
| **M3 vs M1** | **+2.82** | +1.71e-04 |
| M4 vs M3 | **-6.09** | -2.74e-04 |

### |OFI| Distribution by Jump Status

- Jump bars (N=114): **|OFI|_mean = 0.1728**
- No-jump bars (N=52,298): |OFI|_mean = 0.1410
- Welch t = **+2.15**, p = 0.034
- KS stat = 0.154, p < 1e-3

### Sub-Period OOS Stability

| Year | Base rate | AUC M1 | AUC M2 | AUC M3 |
|---|---|---|---|---|
| **2020** (crisis) | 0.124% | 0.499 | **0.571** | **0.580** |
| **2021** (calm) | 0.192% | 0.524 | 0.493 | 0.547 |

- **2020 COVID crisis**: clear improvement from |OFI| (both M2 and M3 beat M1)
- **2021 calm period**: M2 ceases to help (AUC 0.49 < 0.52 baseline); M3 still marginally better
- **Conclusion**: OFI -> jump predictability is regime-dependent

### M3 Coefficients (standardized features)

| Feature | Coef | Interpretation |
|---|---|---|
| `jump_curr` | +0.116 | Jump clustering: t jump -> t+1 jump slightly more likely |
| `\|OFI\|_t` | **+0.200** | **High \|OFI\| -> higher jump probability** (opposite to K1124 diffusive-vol finding) |
| `OFI_t` signed | **-0.187** | **Sell-side OFI pressure -> higher jump probability**; buy-side pressure slightly lowers it |
| intercept | -6.03 | Base log-odds (~0.2% rate) |

The signed OFI coefficient is the key finding: **negative OFI (sell pressure) predicts jumps more than positive OFI** — a Taiwan-specific asymmetry.

## Triple-Threshold Verdict

| Criterion | Value | Threshold | Pass? |
|---|---|---|---|
| AUC improvement (M2 vs M1) | +0.007 | > 0.02 | **FAIL** |
| Brier improvement (M2 vs M1) | +0.04% | > 5% | **FAIL** |
| Sub-period AUC stability | 2020 OK, 2021 M2 FAILS | both > baseline | **FAIL** |

=== **TRIPLE: FAIL** ===

M3 shows stronger signal (AUC impr +0.04) but still below 0.02 threshold considering multiple specifications tested. Statistical significance exists (DM t=+2.82) without economic significance — the Patton (2011) & Hansen SPA warning pattern.

## Codex Audit (HIGH severity, ran pre-record)

Codex `codex exec -s read-only` identified **2 HIGH issues** in first run:

1. **Bipower variation off-by-one** (critical):
   Original `pairs[t-K+1:t-1]` covered returns `r_{t-K+1},...,r_{t-1}` (only K-1 returns, K-2 products),
   not the claimed `r_{t-K},...,r_{t-1}` (K returns, K-1 products).
   **Fix**: `pairs[t-K:t-1]` + divisor `(K-1)*mu1^2`. Verified: each day's first finite L_stat at bar=16, last bar excluded from valid sample.

2. **VIX z-score OOS leakage**:
   Original `vix_z = (vix - mean_full_sample) / std_full_sample` used 2020-2021 distribution info for feature engineering.
   **Fix**: compute mean/std on IS rows (2017-2019) only.

Both fixes applied and full experiment re-run. M3 DM t-stat changed from +2.43 to +2.82 after fix (now stronger, validating the finding direction).

## Key Findings

1. **|OFI| IS positively associated with jumps** (jump bars |OFI|_mean = 0.173 vs no-jump 0.141, Welch t=+2.15, p=0.034). This is **opposite to K1124**'s diffusive-vol finding where |OFI| high -> vol LOWER.

2. **Signed OFI asymmetry matters**: the M3 coefficient -0.187 on signed OFI plus +0.200 on |OFI| implies:
   - Big sell pressure: strong positive jump signal
   - Big buy pressure: much weaker jump signal
   - This contrasts with Cont et al. (2014) on US equities where order imbalance typically has symmetric impact

3. **Regime dependence**: Effect concentrated in 2020 (COVID crisis). 2021 calm period shows little OFI -> jump predictability. M3 still positive in both sub-periods but economically weak in 2021.

4. **VIX regime interaction fails** (M4 AUC OOS = 0.49, DM vs M3 t = -6.09). Lagged daily VIX does not modulate the OFI -> jump relationship at 5-min horizon.

5. **Mechanism hypothesis**: Large sell-side |OFI| on TAIFEX may reflect institutional unwinds that cross thin liquidity layers, triggering next-bar jumps. The effect is muted during calm periods when order books are deeper.

## Limitations

- Single market (TAIFEX TX day session); no bid/ask data (pure tick rule).
- Jump definition binary at alpha=0.01 — robustness to alpha not tested.
- IS (3 years) / OOS (2 years) split relatively small. Expanding window re-estimation not done.
- COVID crisis disproportionately drives 2020 results; extreme regime may not generalize.
- Base rate 0.21% makes AUC sensitive to small sample swings.
- Settled contract rollover effect on OFI not explicitly tested here (K1124 found settlement days had lower RV despite higher |OFI|).

## Verdict

**Not a publishable standalone finding** under triple threshold. But it **rules in** a partial truth:
- |OFI| positively (not negatively) predicts the discrete jump component
- Signed OFI provides incremental info (M3 > M2)
- Effect concentrated in crisis periods

**Why K1124 and K1125 point opposite directions**: they measure different things. K1124's target (5-min RV) pools diffusive + jump variation; the diffusive part mean-reverts after |OFI| bursts (order pressure releases), while the rare jump component is (slightly) more likely. The diffusive component dominates the pooled measure, yielding K1124's negative sign on |OFI| -> RV.

This is consistent with **Cont-Tankov (2004) jump-diffusion decomposition**: different channels, different predictability patterns.

## Derived Directions (3)

1. **K1126 — OFI x jump on US ES/SPY 5-min** (cross-market replication).
   Does K1125's sell-side asymmetry replicate on US equities? Lee-Mykland + OFI from ES futures tick data. If asymmetry is Taiwan-specific, it's a microstructure-level institutional-flow signature.

2. **K1127 — Separate diffusion vs jump components on TAIFEX**.
   Decompose 5-min RV into continuous (BV) + jump component. Run K1124-style |OFI| -> BV and |OFI| -> jump-RV separately. Does the sign of OFI -> diffusive vol stay negative while OFI -> jump-variance stays positive? This would cleanly test the Cont-Tankov mechanism hypothesis.

3. **K1128 — Regime-dependent OFI prediction (VIX tertiles)**.
   Split days into VIX tertiles (not interactions). Re-run M3 on each. Expect strong effect in high-VIX tertile, weak in low-VIX. If confirmed, would motivate a crisis-detection trading rule (paper trades when OFI spikes during high-VIX).

## Files

- `k1125.py` — Main experiment (post-Codex-fix version)
- `k1125_pilot.py` — Pilot on 3 months for pipeline sanity
- `k1125_results.json` — Full numeric results
- `k1125_results.png` — 4-panel figure (L distribution, |OFI| by jump, AUC, Brier)
- `k1125_preds.npz` — OOS predictions for all models (for re-analysis)
- `_cache_bars_*.parquet` — Reused K1124 bar cache

## References

- Lee, S.S., Mykland, P.A. (2008). "Jumps in Financial Markets: A New Nonparametric Test and Jump Dynamics." *Review of Financial Studies* 21(6), 2535-2563.
- Cont, R., Kukanov, A., Stoikov, S. (2014). "The Price Impact of Order Book Events." *Journal of Financial Econometrics* 12(1), 47-88.
- Cont, R., Tankov, P. (2004). *Financial Modelling with Jump Processes*. CRC Press.
- Patton, A. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies." *Journal of Econometrics* 160(1), 246-256.
- Harvey, D., Leybourne, S., Newbold, P. (1997). "Testing the Equality of Prediction Mean Squared Errors." *International Journal of Forecasting* 13(2), 281-291.
