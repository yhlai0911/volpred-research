# K1331: Realized Dispersion / Correlation Proxy Without Options Data

- **K id**: K1331
- **Status**: completed
- **Verdict**: **MIXED**
- **Created**: 2026-06-14

## Research Question

Can a no-options realized proxy for dispersion / correlation risk premium, built from
`SPY` realized variance versus large-cap constituent average realized variance, show
mean reversion or useful regime-timing power?

This is intentionally narrower than a true option-implied DSPX / correlation-risk-premium
test. It only uses yfinance adjusted close data.

## Differentiation

- `K809/K771` tested sector dispersion timing and found no robust return edge.
- `K982` tested sector dispersion and average correlation for SPY volatility prediction.
- `K1331` instead builds a constituent-level realized proxy:
  - `dispersion_var = mean(component 21d realized variance) - SPY 21d realized variance`
  - `realized_corr_proxy = SPY 21d realized variance / mean(component 21d realized variance)`

## Data

- Source: yfinance adjusted close
- Period: 2014-01-31 to 2026-05-14
- Observations: 3,090
- Index: `SPY`
- VIX control: `^VIX`
- Constituents used: 20 current large-cap names
  (`AAPL`, `MSFT`, `NVDA`, `AMZN`, `META`, `GOOGL`, `BRK-B`, `JPM`, `XOM`,
  `UNH`, `JNJ`, `PG`, `HD`, `MA`, `V`, `BAC`, `WMT`, `KO`, `PEP`, `COST`)

## Method

### Realized proxy

- 21-day annualized realized variance from daily log returns.
- Constituent average variance is an equal-weight basket over available names.
- The proxy is **not** option-implied and is **not** a tradable dispersion premium.

### Forecast target

- Future target is next 21 trading days of `SPY` realized variance, covering returns
  from `t+1` to `t+21`.
- Forecast features use information available through close `t`.
- OOS forecast period starts 2022-01-01.
- Expanding-window log-variance regressions are refit daily.
- Forecast comparison uses QLIKE and repo-standard HAC DM with `h=21`.

### Timing strategies

Simple SPY de-risking rules are tested only as regime-timing diagnostics:

- `S1`: reduce SPY exposure to 50% when `dispersion_z > 1`
- `S2`: reduce SPY exposure to 50% when `corr_proxy_z < -1`
- `S3`: reduce exposure when either condition triggers

All strategy signals explicitly use `signal.shift(1)`, so signal from day `t-1`
is applied to return day `t`. Trading cost is 2 bps per unit exposure change.

## Results

### Mean reversion

Realized dispersion and realized-correlation proxy both strongly mean-revert:

| Test | Slope | HAC t | p-value | R2 |
|---|---:|---:|---:|---:|
| 21d change in dispersion z on current dispersion z | -0.853 | -11.31 | 1.19e-29 | 0.428 |
| 21d change in corr-proxy z on current corr-proxy z | -0.830 | -12.70 | 5.81e-37 | 0.414 |

Top-versus-bottom dispersion quintile check:

- Low dispersion forward change: `+1.052`
- High dispersion forward change: `-1.799`
- High minus low: `-2.851`

### Forecasting

No dispersion/correlation model clears the Harvey `|t| > 3` OOS forecast gate versus
the current `SPY` realized-variance baseline.

| Model | OOS QLIKE | DM t vs M0 | Harvey pass |
|---|---:|---:|---|
| M0 current SPY RV | 0.3316 | 0.00 | baseline |
| M1 current RV + dispersion | 0.3281 | -0.24 | no |
| M2 current RV + corr proxy | 0.3328 | +0.12 | no |
| M3 current RV + dispersion + corr | 0.3304 | -0.08 | no |
| M4 VIX + current RV | 0.2732 | -2.74 | no |
| M5 VIX + current RV + dispersion + corr | 0.2735 | -2.35 | no |

Important: the best forecast model is `VIX + current RV`, not a dispersion model, and
even it misses the Harvey threshold.

### Regime timing

Timing value appears only as downside-risk reduction from lower exposure, not as a
statistically robust return edge.

| Strategy | Sharpe | MDD | 1% daily quantile | Downside DM t vs BH |
|---|---:|---:|---:|---:|
| Buy-hold SPY | 0.756 | -24.50% | -2.99% | baseline |
| S1 de-risk high dispersion | 0.779 | -24.20% | -2.80% | -3.41 |
| S2 de-risk low corr proxy | 0.799 | -24.50% | -2.96% | -3.78 |
| S3 de-risk either | 0.775 | -24.20% | -2.75% | -4.45 |

Negative-return DM tests do **not** pass; only downside-loss tests pass.

## Verdict

**MIXED**.

1. Realized dispersion / correlation proxy is highly mean-reverting.
2. It does **not** deliver Harvey-level OOS QLIKE forecast improvement over current
   `SPY` realized variance.
3. Simple de-risking rules improve downside loss, but this is mostly an exposure-reduction
   result and should not be described as a return alpha.

## Limitations

- Fixed current large-cap basket creates survivorship bias.
- Equal-weight constituent variance is an approximation, not an S&P 500 historical
  constituent calculation.
- This test cannot infer the option-implied correlation risk premium; it only tests a
  realized-data proxy.
- 21-day realized targets overlap; formal forecast inference therefore uses HAC with
  `h=21`, and descriptive p-values should not be overread.

## Files

- `K1331.py` — full experiment script
- `K1331_results.json` — structured results
- `data/prices.csv` — yfinance close snapshot
- `data/features.csv` — realized dispersion / correlation proxy features
- `data/oos_forecasts.csv` — expanding OOS forecast table
- `data/strategy_returns.csv` — timing strategy return table
- `figures/k1331_dispersion_timeseries.png`
- `figures/k1331_oos_qlike.png`

## References

- Cboe S&P 500 Dispersion Index (DSPX): <https://www.cboe.com/us/indices/dispersion/>
- Driessen, Maenhout, Vilkov, *Option-Implied Correlations and the Price of Correlation Risk*: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2166829>
- *Dispersion Trading and Correlation Risk Premium*: <https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID1889147_code850132.pdf?abstractid=1889147&mirid=1>
