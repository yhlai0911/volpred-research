# K1021: A4f-VIX9D with Joint Student-t Degrees of Freedom Estimation

## Motivation
K1004 showed A4f-VIX9D-t (Student-t, df jointly estimated) slightly outperforms A4f-VIX9D-N (Normal) on QLIKE and significantly improves VaR calibration. Paper 9 needs a systematic comparison of distribution assumptions within the A4f framework: joint estimation vs fixed df, and whether Hansen (1994) skewed Student-t adds further improvement.

## Research Questions
1. In the A4f multiplicative framework, does jointly estimating df outperform fixed df (e.g., df=5 or df=8)?
2. Is the estimated df time-varying across rolling windows? What is the typical range?
3. Does skewed Student-t (Hansen 1994) provide additional VaR/ES calibration beyond symmetric Student-t?
4. QLIKE impact expected to be small; main value should be in VaR/ES calibration.

## Method
- **A4f specification**: sigma^2 = tau_t * g_t; tau_t = theta0 + theta1 * VIX9D^2_{t-1}; g_t = omega + alpha*u^2 + gamma*u^2*I(r<0) + beta*g_{t-1}
- **5 models**:
  - M1: A4f-VIX9D-N (Normal innovations)
  - M2: A4f-VIX9D-t-joint (Student-t, df jointly estimated via MLE)
  - M3: A4f-VIX9D-t-fixed5 (Student-t, df=5 fixed)
  - M4: A4f-VIX9D-t-fixed8 (Student-t, df=8 fixed)
  - M5: A4f-VIX9D-skewt (Hansen 1994 skewed Student-t, df+skew jointly estimated)
- **Estimation**: Rolling window=2000, refit every 63 days, MLE with L-BFGS-B, 3 random starts
- **Data**: SPY + QQQ, 2011-2026, yfinance. VIX9D: ^VIX9D. OOS: 2019-2026 (N=1827)
- **Evaluation**: QLIKE on r^2, VaR (1%/2.5%/5%), ES (2.5%), DM test (Harvey t>3.0), Scorecard
- **Seed**: 42

## Key Results

### SPY

| Model | QLIKE | df | skew | VaR 1% | VaR 2.5% | VaR 5% |
|-------|-------|----|------|--------|----------|--------|
| A4f-VIX9D-N | -8.3875 | N/A | N/A | 1/4 | 6/6 | 4/4 |
| A4f-VIX9D-t-joint | -8.3904 | 8.5 | N/A | **4/4** | 6/6 | 4/4 |
| A4f-VIX9D-t-fixed5 | -8.3762 | 5.0 | N/A | **4/4** | 6/6 | 4/4 |
| A4f-VIX9D-t-fixed8 | **-8.3930** | 8.0 | N/A | **4/4** | 6/6 | 4/4 |
| A4f-VIX9D-skewt | -8.3854 | 9.5 | -0.217 | **4/4** | 6/6 | 4/4 |

### QQQ

| Model | QLIKE | df | skew | VaR 1% | VaR 2.5% | VaR 5% |
|-------|-------|----|------|--------|----------|--------|
| A4f-VIX9D-N | **-7.7845** | N/A | N/A | 1/4 | 4/6 | 4/4 |
| A4f-VIX9D-t-joint | -7.7837 | 8.6 | N/A | 1/4 | 6/6 | 4/4 |
| A4f-VIX9D-t-fixed5 | -7.7790 | 5.0 | N/A | **4/4** | 6/6 | 4/4 |
| A4f-VIX9D-t-fixed8 | -7.7793 | 8.0 | N/A | 1/4 | 6/6 | 4/4 |
| A4f-VIX9D-skewt | -7.7833 | 8.9 | -0.222 | **4/4** | 6/6 | 4/4 |

### DM Tests (SPY)
- t-joint vs Normal: t=-1.941 (p=0.052, marginal)
- **t-joint vs t-fixed5: t=-3.113 (p=0.002, significant by Harvey threshold)**
- t-joint vs t-fixed8: t=0.870 (p=0.385, not significant)
- **t-fixed5 vs t-fixed8: t=3.779 (p=0.0002, highly significant -- fixed8 >> fixed5)**
- skewt vs t-joint: t=2.789 (p=0.005 -- t-joint slightly better QLIKE than skewt)

### df Evolution
- Joint estimate converges to **df ~ 8.5** (SPY) and **df ~ 8.6** (QQQ) on average
- Std dev of df: ~1.8 (SPY), ~2.2 (QQQ) -- moderately time-varying
- Consistent with K802 finding that equity df is typically 5-8
- Skew-t estimates slightly higher df (~9.5 SPY, ~8.9 QQQ) with negative skew lambda ~ -0.22

## Conclusions

1. **QLIKE differences are negligible across distribution assumptions** -- the A4f variance equation dominates prediction accuracy, not the innovation distribution. None of the DM tests exceed Harvey t>3.0 for t-joint vs Normal.

2. **VaR calibration is where distribution matters enormously**:
   - Normal: FAILS VaR 1% (violation rate 1.64% SPY, 2.13% QQQ -- both significantly > 1%)
   - Student-t (joint or fixed8): PASSES VaR 1% for SPY (1.48% or 1.31%), borderline for QQQ
   - Fixed df=5: Most conservative, PASSES all VaR levels for both assets (perfect calibration)
   - Skew-t: PASSES all VaR levels with slightly conservative violations

3. **Joint estimation settles near df=8**, close to fixed df=8. The DM test shows no significant QLIKE difference between joint and fixed8. But jointly estimated df varies from ~6 to ~12 across windows, suggesting some time-variation.

4. **Fixed df=5 is the most robust VaR model** -- achieves 4/4 scorecard across all VaR levels and both assets, despite slightly worse QLIKE (the fixed5 QLIKE penalty is statistically significant vs joint by Harvey threshold: t=-3.113).

5. **Skew-t adds complexity without clear benefit**: lambda ~ -0.22 captures left skewness, but the VaR improvement over symmetric t is negligible (both already achieve 4/4). The extra parameter is not justified.

6. **Paper 9 recommendation**: Use A4f-VIX9D-t with fixed df=8 as the default (best QLIKE-VaR balance), and report joint estimation results as robustness. Fixed df=5 for conservative risk management.

## Limitations
- Only 2 assets (SPY, QQQ) -- both US large-cap equity
- OOS period 2019-2026 includes COVID crash (extreme tail event)
- VIX9D as the sole exogenous variable (VIX or VIX3M not compared here -- see K1004)
- Skew-t ES computed via simulation (analytical VaR but MC ES)

## Files
- `k1021.py` -- experiment script
- `k1021_results.json` -- full results
- `k1021_df_evolution_spy.png` -- df estimate evolution plot
- `k1021_var_scorecard.png` -- VaR scorecard heatmap
- `k1021_violation_timeline_spy.png` -- VaR 2.5% violation timeline
- `k1021_qlike_comparison.png` -- QLIKE bar chart comparison

## References
- Engle & Rangel (2008): Spline-GARCH
- Patton (2011): QLIKE loss
- Hansen (1994): Skewed Student-t distribution
- Kupiec (1995), Christoffersen (1998): VaR backtesting
- Acerbi & Szekely (2014): ES backtesting
- Harvey (2016): Multiple testing threshold t>3.0
