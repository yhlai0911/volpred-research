# K1035: EVT-VaR with A4f Residuals (Extreme Value Theory)

**[提出: 賴奕豪, 執行: Claude]**

## Problem / Motivation

K159 showed that EVT-GPD on GJR residuals achieved Kupiec 12/12 PASS but only Trinity 3/12. The poor Trinity performance was due to the Christoffersen (1998) conditional coverage test failing, suggesting residual clustering in VaR violations.

A4f-VIX is now established as the best volatility model for SPY/QQQ (K988, K1000). The hypothesis is: A4f's more accurate conditional variance (incorporating VIX as a multiplicative scaling factor) produces better-calibrated standardized residuals, which should be closer to i.i.d. This would improve both GPD fitting quality and violation independence, potentially boosting Trinity pass rate.

## Method

**Models compared (4 x 2 assets x 2 VaR levels = 16 test configurations):**

| Model | Variance | Tail Distribution |
|-------|----------|-------------------|
| GJR-t | GJR-GARCH(1,1) | Parametric Student-t(df=8) |
| GJR-EVT | GJR-GARCH(1,1) | GPD on standardized residuals |
| A4f-t | A4f-VIX multiplicative | Parametric Student-t(df=8) |
| A4f-EVT | A4f-VIX multiplicative | GPD on standardized residuals |

**EVT-GPD procedure (McNeil & Frey 2000):**
1. Estimate GARCH/A4f conditional variance h_t on rolling window
2. Compute standardized residuals: z_t = r_t / sqrt(h_t)
3. Fit GPD to exceedances above threshold (10th percentile of left tail)
4. VaR and ES from GPD quantiles, scaled by sqrt(h_t)

**Evaluation:**
- Kupiec (1995) unconditional coverage
- Christoffersen (1998) conditional coverage
- Basel traffic light
- Acerbi & Szekely (2014) ES backtest
- Trinity = all three VaR tests pass
- VaR levels: 2.5% and 1%

**Configuration:**
- Data: yfinance, 2005-01-01 to 2026-04-10
- OOS: 2019-01-01 onwards (~1827 days)
- Window: 2000, Refit: every 63 days
- Student-t df: 8 (fixed)
- GPD threshold: 10th percentile of left tail
- seed=42

## Results

### Trinity Pass Rates (out of 4 tests: 2 assets x 2 alpha levels)

| Model | Trinity PASS |
|-------|-------------|
| GJR-t | **0/4** |
| GJR-EVT | **4/4** |
| A4f-t | **4/4** |
| A4f-EVT | **4/4** |

### Key Finding: EVT dramatically improves GJR but A4f already saturated

**GJR-t fails all 4 Trinity tests** (both SPY and QQQ, both 2.5% and 1%). The failure is on Kupiec + Christoffersen: violation rates are too high (3.4-3.8% for 2.5% VaR, 1.6-1.9% for 1% VaR), and violations cluster.

**GJR-EVT passes all 4 Trinity tests** -- EVT completely fixes GJR's tail calibration problem. GPD captures the heavier-than-Student-t tails that df=8 underestimates.

**A4f-t already passes all 4 Trinity tests** -- A4f's multiplicative VIX scaling already produces well-calibrated VaR/ES without EVT.

**A4f-EVT also passes all 4** -- EVT does not hurt, but cannot improve what's already perfect. A4f-EVT shows marginally tighter violation rates (closer to expected):

| Model | SPY 2.5% VR | SPY 1% VR | QQQ 2.5% VR | QQQ 1% VR |
|-------|------------|-----------|-------------|-----------|
| A4f-t | 0.0268 | 0.0142 | 0.0312 | 0.0148 |
| A4f-EVT | 0.0224 | 0.0088 | 0.0235 | 0.0082 |
| Expected | 0.0250 | 0.0100 | 0.0250 | 0.0100 |

A4f-EVT violation rates are closer to the expected levels, but both pass all tests.

### GPD Shape Parameter (xi) Stability

- **GJR-EVT SPY**: xi = 0.103 +/- 0.042 (range: 0.025-0.189) -- positive xi = heavy tails
- **A4f-EVT SPY**: xi = 0.055 +/- 0.033 (range: -0.031-0.098) -- smaller xi, A4f already captures some tail risk
- **A4f residuals have less extreme tails** than GJR residuals, confirming A4f models fat tails better through the VIX component.

### QLIKE Comparison

| Asset | GJR QLIKE | A4f QLIKE | DM t-stat | Significant? |
|-------|-----------|-----------|-----------|-------------|
| SPY | 1.496 | 1.413 | -3.08 | Yes (>3.0) |
| QQQ | 1.500 | 1.411 | -2.49 | No (<3.0) |

A4f remains the better variance forecaster (lower QLIKE), significant for SPY.

## Conclusion

1. **EVT-GPD is a game-changer for GJR**: Trinity 0/4 -> 4/4. EVT fixes GJR's systematic underestimation of tail risk when using fixed df=8.

2. **EVT is unnecessary for A4f**: A4f-t already achieves 4/4 Trinity PASS. The VIX-based multiplicative scaling effectively captures the same tail information that EVT extracts from residuals.

3. **A4f reduces residual tail heaviness**: GPD xi parameter is smaller for A4f residuals (0.055 vs 0.103 for SPY), confirming A4f internalizes tail risk through the VIX channel.

4. **Practical implication**: For risk management, A4f-t(df=8) is sufficient -- adding EVT adds computational complexity without improving pass rates. However, for institutions using standard GJR-GARCH, EVT-GPD is strongly recommended.

5. **vs K159**: K159 found Trinity 3/12 for GJR-EVT. The improvement here (4/4) may be due to different threshold selection (10th percentile vs K159's method) or different OOS period. The key finding is that EVT helps GJR dramatically.

## Limitations

- Only 2 assets (SPY, QQQ) -- both US large-cap equity
- OOS period (2019-2026) includes COVID crash but is relatively short
- GPD threshold selection (10th percentile) not optimized
- Fixed df=8 may not be optimal for all periods
- Not tested on non-equity assets or emerging markets

## Files

- `k1035.py` -- Experiment script
- `k1035_results.json` -- Full results with all backtest statistics
- `k1035_violation_rates.png` -- Violation rate comparison chart
- `k1035_trinity_heatmap.png` -- Trinity pass/fail heatmap
- `k1035_gpd_xi_stability.png` -- GPD xi parameter stability over time

## References

- McNeil & Frey (2000). Estimation of tail-related risk measures for heteroscedastic financial time series: An EVT approach. J Empirical Finance.
- Kupiec (1995). Techniques for Verifying the Accuracy of Risk Measurement Models.
- Christoffersen (1998). Evaluating Interval Forecasts. International Economic Review.
- Acerbi & Szekely (2014). Back-testing Expected Shortfall.
- Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic Fundamentals.
