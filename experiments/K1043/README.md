# K1043: FHS-A4f VaR -- Filtered Historical Simulation vs CF-Rolling

## Motivation
- K1036 showed CF-Rolling achieves 6/6 Trinity PASS (best VaR method)
- K905 showed FHS beat CAViaR/QuantHAR, but never compared to CF-Rolling or A4f
- FHS (Barone-Adesi & Giannopoulos 1999) is an industry-standard VaR method
- Question: Can FHS match CF-Rolling? Does A4f improve FHS?

## Method
- **Design**: 2x4 factorial (2 models x 4 VaR methods)
  - Models: GJR-GARCH(1,1), A4f (multiplicative GARCH-X with VIX)
  - VaR Methods: Normal, Student-t(df=8), CF-Rolling(252d), FHS(252d)
- **FHS Implementation**:
  1. Fit GARCH to get conditional sigma_t
  2. Compute standardized residuals z_t = r_t / sigma_t
  3. From 252-day rolling window of z_t, take empirical quantile
  4. VaR = sigma_forecast * quantile(z, alpha)
  5. ES = sigma_forecast * mean(z[z <= quantile])
- **Assets**: SPY, QQQ, GLD
- **Data**: 2005-01-01 to 2026-04-10 (yfinance), OOS from 2019-01-01
- **Config**: window=2000, refit_every=63, alpha=2.5% and 1%, seed=42
- **Evaluation**: Kupiec, Christoffersen CC, Basel traffic light, Trinity, ES backtest (Acerbi-Szekely), DM test

## Key Results

### 2x4 Interaction Table (Trinity PASS rate)

| Model x Method | Normal | Student-t | CF-Rolling | FHS |
|----------------|--------|-----------|------------|-----|
| **GJR**        | 0/6 (0%) | 1/6 (17%) | **6/6 (100%)** | **6/6 (100%)** |
| **A4f**        | 2/6 (33%) | 5/6 (83%) | **6/6 (100%)** | **6/6 (100%)** |

### Model Effect (averaging over methods)
- GJR: 13/24 = 54.2%
- A4f: 19/24 = 79.2% (+25 pp)

### Method Effect (averaging over models)
- Normal: 2/12 = 16.7%
- Student-t: 6/12 = 50.0%
- CF-Rolling: **12/12 = 100.0%**
- FHS: **12/12 = 100.0%**

### ES Backtest
- **ALL 48/48 tests PASS** (100%) across all model x method combinations
- ES is not a binding constraint in this dataset

### DM Test: FHS vs CF-Rolling
- **All 12 DM tests show NO significant difference** (all |t| < 1.96)
- The two non-parametric methods are statistically indistinguishable
- Largest |t| = 1.654 (QQQ, GJR, 1%), still NS

## Conclusions

1. **FHS matches CF-Rolling: both achieve 12/12 (100%) Trinity PASS** -- confirming that non-parametric tail modeling is the key to robust VaR, regardless of the specific non-parametric approach.

2. **A4f does NOT improve FHS beyond what FHS already provides** -- both GJR+FHS and A4f+FHS achieve 6/6 Trinity PASS. The improvement from A4f is visible for parametric methods (Normal: 0/6 -> 2/6, Student-t: 1/6 -> 5/6) but not for non-parametric methods (both already 6/6).

3. **FHS and CF-Rolling are statistically indistinguishable** -- DM tests show no significant difference in quantile loss across any asset/alpha/model combination.

4. **The hierarchy is clear**: Non-parametric tail (FHS/CF-Rolling) >> Parametric fat-tailed (Student-t) >> Normal. The model (A4f vs GJR) is secondary to the VaR quantile method.

5. **Practical implication**: Either FHS or CF-Rolling can be used as the VaR method. FHS is slightly simpler (no moment computation needed), while CF-Rolling provides analytical transparency via skewness/kurtosis. Both are equally valid.

## Files
- `k1043.py` -- Main experiment script
- `k1043_results.json` -- Full results
- `k1043_trinity_heatmap.png` -- 2x4 Trinity PASS rate heatmap
- `k1043_violation_rates.png` -- Violation rates bar chart
- `k1043_fhs_vs_cf.png` -- FHS vs CF-Rolling comparison

## References
- Barone-Adesi & Giannopoulos (1999). J Futures Markets 19(5):583-602.
- Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320.
- Kupiec (1995). J Derivatives 3:73-84.
- Christoffersen (1998). Int Econ Rev 39(4):841-862.
- Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk.
- K1036: A4f + CF-Rolling 6/6 Trinity PASS
- K905: FHS beat CAViaR/QuantHAR
