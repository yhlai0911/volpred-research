# Labor-Force Growth / Immigration Public Proxy as Wage-Sensitive Sector RV Prior

## Motivation

The backlog question was whether labor-force growth and immigration-linked labor
supply shocks can be used as a prior for realized volatility in wage-sensitive
sectors such as homebuilders, retail, and industrials.

This experiment is deliberately conservative. Public monthly FRED/BLS series do
not measure true real-time immigration flows. The test therefore treats them as
reduced-form public proxies for labor supply, labor-market tightness, and wage
pressure, then asks whether those proxies lead next-month and next-3-month ETF
realized volatility.

## Literature / External Context

- FRBSF Economic Letter, "Immigration and Changes in Labor Force
  Demographics": https://www.frbsf.org/research-and-insights/publications/economic-letter/2025/11/immigration-and-changes-in-labor-force-demographics/
- FRBSF Economic Letter, "The Role of Immigration in U.S. Labor Market
  Tightness": https://www.frbsf.org/research-and-insights/publications/economic-letter/2023/10/role-of-immigration-in-us-labor-market-tightness/
- FRBSF Economic Letter, "Recent Spike in Immigration and Easing Labor
  Markets": https://www.frbsf.org/research-and-insights/publications/economic-letter/2024/05/recent-spike-in-immigration-and-easing-labor-markets/
- Boston Fed, "Quantifying the Recent Immigration Surge":
  https://www.bostonfed.org/publications/research-department-working-paper/2024/quantifying-the-recent-immigration-surge.aspx
- BLS Foreign-born workers release:
  https://www.bls.gov/news.release/forbrn.nr0.htm

## Data

- Macro source: FRED CSV endpoints.
- Macro series:
  - `CLF16OV`: civilian labor force level.
  - `PAYEMS`: total nonfarm payrolls.
  - `JTSJOL`: total nonfarm job openings.
  - `CES0500000003`: average hourly earnings, total private.
  - `LNU01073395`: foreign-born civilian labor force level.
- Market source: yfinance adjusted close, `auto_adjust=True`.
- Market tickers: `SPY`, `XHB`, `XRT`, `XLI`.
- Market sample after dropping partial June 2026: 2006-01-03 to 2026-05-29.
- Regression complete-case sample: 157 to 183 monthly observations depending on
  ETF, horizon, and signal. The strongest cell has 168 monthly observations
  from 2012-04-30 to 2026-03-31.

## Method

Targets are monthly ETF realized variances:

- `1m`: annualized sum of daily squared log returns within the target month.
- `3m`: annualized sum of daily squared log returns over the next three months.

Signals are monthly expanding z-scores with at least 60 prior months:

- `low_labor_force_growth_z`: negative 12-month civilian labor-force growth.
- `low_foreign_born_lf_growth_z`: negative 12-month foreign-born labor-force
  growth.
- `payroll_labor_supply_gap_z`: 12-month payroll change minus 12-month
  labor-force change.
- `labor_tightness_z`: JOLTS openings divided by civilian labor force.
- `wage_growth_z`: 12-month average-hourly-earnings growth.
- `labor_supply_stress_z`: equal-weight average of the five signals above.

Lookahead guard: all macro signals are shifted by one month in code:

```python
signal_panel = z[SIGNAL_COLUMNS].shift(1)
```

So market target month `t` uses macro signal month `t-1`. Controls are lagged
own ETF log RV, lagged own return, lagged SPY log RV, and lagged SPY return.

Each ETF x horizon x signal cell is estimated by OLS with Newey-West HAC
standard errors (`maxlags=max(1, horizon_months)`). The primary family has 36
tests, and p-values are Holm and Bonferroni adjusted. The pre-specified support
gate is:

`coef > 0`, `|t| >= 3.0`, and `Holm p < 0.05`.

## Results

Verdict: **CONDITIONAL_SUPPORT**.

Six cells pass the positive Harvey-Holm support gate:

| ETF | Horizon | Signal | Coef on log RV | HAC t | Holm p | N |
|---|---:|---|---:|---:|---:|---:|
| XRT | 1m | wage_growth_z | 0.196 | 3.25 | 0.0364 | 170 |
| XRT | 3m | wage_growth_z | 0.240 | 3.18 | 0.0463 | 168 |
| XLI | 1m | wage_growth_z | 0.154 | 4.43 | 0.000324 | 170 |
| XLI | 1m | labor_supply_stress_z | 0.389 | 4.06 | 0.00165 | 159 |
| XLI | 3m | wage_growth_z | 0.151 | 5.27 | 0.00000496 | 168 |
| XLI | 3m | labor_supply_stress_z | 0.366 | 3.33 | 0.0286 | 157 |

The strongest cell is lagged wage growth predicting XLI 3-month log RV
(`coef=0.151`, `t=5.27`, `Holm p=4.96e-06`). A 1,000-rep 6-month moving-block
bootstrap for that selected cell gives coefficient CI95 `[0.0968, 0.2287]` and
`P(coef>0)=1.00`.

Important negative result: the direct foreign-born labor-force proxy does **not**
survive the gate. Its strongest cell is XLI 1m (`t=2.16`, Holm p=0.739). The
evidence therefore supports a **wage/labor-market-stress RV prior**, not a clean
"immigration-flow alpha" claim.

## Robustness / Caveats

Supported cells were re-fit on pre-2020 and post-2020 subsamples. Direction is
mostly positive, but most subsamples do not independently clear `t>3`:

- XRT 3m wage growth remains strong pre-2020 (`t=3.31`) but is weaker post-2020
  (`t=1.99`).
- XLI wage-growth and composite-stress cells are stronger in the full sample
  than in either subsample, so the full-sample result likely reflects a shared
  labor-inflation / macro-volatility regime component.

This is not a tradable strategy. No portfolio rule, cost model, or OOS trading
test is claimed. The result is best used as a research prior: when public
wage-growth or broad labor-supply-stress proxies are elevated, XLI and XRT
forward RV deserves a higher prior, but true immigration-flow data would be
needed before making a stronger immigration-specific claim.

## Files

- `research_labor_force_growth_immigration_shock_wage_sensit.py`: reproducible
  experiment script.
- `research_labor_force_growth_immigration_shock_wage_sensit_results.json`:
  full data metadata, regression results, bootstrap, and sensitivity output.
- `fig_signal_tstats.png`: strongest positive HAC t-stat cells.
- `fig_labor_supply_stress_xhb.png`: lagged composite stress vs XHB next-month
  log RV.
