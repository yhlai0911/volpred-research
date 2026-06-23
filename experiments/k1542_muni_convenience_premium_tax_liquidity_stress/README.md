# K1542 - Municipal convenience-premium compression and cross-asset volatility

## Motivation

This experiment tests whether a free-data proxy for municipal-bond convenience
premium compression can work as a next-week volatility prior. The proposed
channel is tax/liquidity stress: when tax-exempt muni ETFs cheapen relative to
taxable bond and credit beta baselines, the same pressure may precede muni ETF
RV, credit ETF RV, or a stock-bond correlation regime shift.

## Differentiation

This is not a bond-level test of municipal convenience premia. It is a daily ETF
proxy experiment. The purpose is narrower: check whether a cheap/free signal
constructed from MUB/TFI/HYD/TAXF, taxable bond ETFs, ETF volume, and FRED
state/local fiscal stress has predictive content strong enough to justify a
deeper bond-level study.

Related internal priors:

- K1515 flagged that MUB could be added to bond ETF illiquidity/vol work, but
  did not test municipal tax-liquidity stress.
- K1538/K1539 tested credit ETF risk/vol signals, not tax-exempt muni richness.

## Literature Precheck

- Fleckenstein and Longstaff, "Do Municipal Bond Investors Pay a Convenience
  Premium to Avoid Taxes?", Review of Financial Studies, 2025. This motivates
  tax-related convenience premia in municipal bond prices.
  <https://academic.oup.com/rfs/advance-article/doi/10.1093/rfs/hhaf100/8328065>
- Anbil, Carlson, and Styczynski, "How the New Fed Municipal Bond Facility
  Capped Muni-Treasury Yield Spreads in the COVID-19 Recession", Dallas Fed
  working paper. This motivates muni-Treasury stress and facility intervention.
  <https://www.dallasfed.org/-/media/documents/research/papers/2021/wp2101.pdf>
- Federal Reserve Bank of New York Liberty Street Economics, "Municipal Debt
  Markets and the COVID-19 Pandemic". This motivates liquidity/redemption stress
  as a muni market state variable.
  <https://libertystreeteconomics.newyorkfed.org/2020/06/municipal-debt-markets-and-the-covid-19-pandemic/>
- FRED `W070RC1Q027SBEA`, state and local government current tax receipts, used
  as a lagged fiscal-stress proxy.
  <https://fred.stlouisfed.org/series/W070RC1Q027SBEA>

## Data

- Price and volume: yfinance adjusted daily OHLCV, requested 2007-01-01 to
  2026-06-24.
- Muni ETFs: `MUB`, `TFI`, `HYD`, `TAXF`.
- Taxable / cross-asset controls: `IEF`, `AGG`, `LQD`, `HYG`, `SPY`, `^VIX`.
- FRED: `W070RC1Q027SBEA`, `NA000328Q`, `STLFSI4`, `NFCI`.

All requested ETFs had enough history:

| ETF | First close | Last close | Rows |
|---|---:|---:|---:|
| MUB | 2007-09-10 | 2026-06-23 | 4,726 |
| TFI | 2007-09-13 | 2026-06-23 | 4,723 |
| HYD | 2009-02-05 | 2026-06-23 | 4,371 |
| TAXF | 2018-09-12 | 2026-06-23 | 1,954 |

## Method

The stress proxy has five lagged components:

1. Rolling 252-day beta residual cheapening of each muni ETF versus
   `IEF`, `AGG`, `LQD`, `HYG`, and `SPY`.
2. Rolling 21-day muni ETF drawdown stress.
3. Muni ETF volume spike z-score.
4. Lagged state/local tax-receipt YoY deterioration from FRED.
5. Lagged `STLFSI4` financial stress.

The final signal is:

`tax_liquidity_stress_lag = mean(component z-scores).`

Lookahead guard:

- ETF cheapening, drawdown, and volume components are explicitly `.shift(1)`.
- Quarterly tax receipts and weekly stress indicators are shifted by one release
  stamp before daily forward fill.
- Forward targets are 5-trading-day RV/drawdown or 21-trading-day SPY-IEF
  realized correlation.

Formal tests:

- In-sample OLS with Newey-West HAC standard errors, max lag 5.
- Bonferroni and BH correction across 14 tested targets.
- Expanding-window OOS forecast, refit every 21 trading days.
- OOS loss comparison uses canonical `dm_test` on squared forecast errors.

Gate:

- In-sample gate: HAC t >= 3 and Bonferroni p < 0.05.
- OOS gate: MSE improvement > 0 and DM t <= -3.
- A publishable prior requires both in-sample and OOS support.

## Results

Verdict: **WEAK_DIAGNOSTIC_ONLY**.

The proxy has clear in-sample association with next-week muni RV, but OOS tests
do not clear the Harvey-strength DM gate. Therefore the result is diagnostic,
not a production prior.

### In-Sample Passes

| Target | Family | HAC t | 1-sigma effect | Bonferroni p | Gate |
|---|---|---:|---:|---:|---|
| MUB_fwd_rv5 | muni_rv5 | 4.25 | +1.49 vol pp | 0.00030 | PASS |
| TFI_fwd_rv5 | muni_rv5 | 4.12 | +1.37 vol pp | 0.00053 | PASS |
| HYG_fwd_rv5 | cross_asset_rv5 | 3.00 | +0.97 vol pp | 0.03750 | PASS |

Near misses:

- LQD_fwd_rv5: t = 2.94, Bonferroni p = 0.046, but t < 3 so FAIL.
- MUB_fwd_drawdown5: t = 2.94, Bonferroni p = 0.047, but t < 3 so FAIL.
- HYD/TAXF RV and drawdown are directionally positive but below the gate.

### OOS

No target passes OOS.

Best OOS improvements:

| Target | MSE improvement | DM t | Gate |
|---|---:|---:|---|
| MUB_fwd_rv5 | +10.84% | -1.39 | FAIL |
| TFI_fwd_rv5 | +9.36% | -1.40 | FAIL |
| HYD_fwd_rv5 | +7.72% | -0.89 | FAIL |
| LQD_fwd_rv5 | +3.98% | -1.07 | FAIL |

The improvements are economically interesting but not statistically strong
enough under the project gate.

## Interpretation

There is a plausible diagnostic pattern: when muni ETFs cheapen versus their
taxable beta basket, with drawdown/volume/fiscal stress aligned, next-week MUB
and TFI RV tend to be higher. The signal also weakly spills into HYG RV.

But the result does not survive the full production standard because the OOS DM
statistics are far below `|t| >= 3`. The correct conclusion is:

**Muni tax-liquidity stress is a promising diagnostic for a deeper bond-level or
fund-flow study, but not yet a robust cross-asset volatility prior.**

## Outputs

- `k1542_muni_convenience_premium_tax_liquidity_stress.py`
- `k1542_muni_convenience_premium_tax_liquidity_stress_results.json`
- `k1542_muni_convenience_premium_tax_liquidity_stress_daily_panel.csv`
- `figures/k1542_stress_components.png`
- `figures/k1542_regression_tstats.png`
- `figures/k1542_oos_mse_improvement.png`
- `figures/k1542_stress_quintiles.png`

## Limitations

- ETF volume is not underlying muni bond volume.
- ETF residual cheapening is not a direct bond-level convenience premium.
- Quarterly tax receipts are low-frequency and lagged; they cannot explain daily
  variation by themselves.
- TAXF history is much shorter than MUB/TFI/HYD.
- A stronger follow-up should use municipal fund flows, MSRB/EMMA or TRACE-like
  muni trade data if available, and bond-level tax-adjusted spread measures.
