# Conditional Expected Drawdown Risk Target vs Realized-Vol Target

## Motivation

This experiment tests whether a practitioner-friendly drawdown-risk target can
improve a simple equity risk-targeting rule. The candidate signal is
Conditional Expected Drawdown (CED): the tail mean of fixed-horizon drawdowns
estimated from recent OHLC paths. The benchmark is the standard realized-vol
target.

The task is related to, but distinct from:

- K1494: CDaR scaling on SPY/TLT/GLD/DBC failed to beat realized-vol targeting.
- K1334: downside-CVaR targeting also failed to produce reliable left-tail
  improvement.

Here the basket is equity-only, using equal-weight SPY/QQQ/IWM returns, and
the drawdown signal is computed from daily adjusted OHLC data at 20-day and
60-day horizons.

## Literature

- Chekhlov, Uryasev, Zabarankin (2005), "Drawdown Measure in Portfolio
  Optimization".
- Chekhlov, Uryasev, Zabarankin (2003), "Portfolio Optimization with Drawdown
  Constraints".
- PyPortfolioOpt EfficientCDaR documentation.
- scikit-portfolio Efficient Conditional Drawdown at Risk documentation.

These sources motivate drawdown-aware risk measures, but the experiment treats
out-of-sample performance as an empirical question rather than assuming CED is
an upgrade.

## Data

- Source: yfinance adjusted OHLC with `auto_adjust=True`.
- Tickers: SPY, QQQ, IWM.
- Analysis period after all warmups: 2006-01-03 to 2026-06-12.
- Out-of-sample period: 2018-01-02 to 2026-06-12.
- OOS sample size: 2,123 trading days.
- Cached inputs: `data/open.csv`, `data/high.csv`, `data/low.csv`,
  `data/close.csv`.

## Method

The base portfolio is the equal-weight daily close return of SPY, QQQ, and IWM.
The baseline exposure is:

`TARGET_VOL / 63d annualized realized volatility`, clipped to `[0, 1.5]`, then
shifted by one trading day.

The CED exposure is:

`target_ced / trailing 252d fixed-horizon CED`, clipped to `[0, 1.5]`, then
shifted by one trading day.

Two CED horizons are tested: 20 trading days and 60 trading days. The CED target
is calibrated in-sample to match the realized-vol baseline's mean exposure over
2005-01-03 to 2017-12-29. Transaction costs are 5 bps one-way on absolute
exposure changes. Formal comparison uses a paired moving-block bootstrap on OOS
daily returns with 1,000 replications, 21-day blocks, and seed 42.

The success gate was pre-specified in code: a CED variant must improve the MDD
bootstrap interval, improve the Calmar bootstrap interval, avoid materially
worse Sharpe, and avoid higher left-tail frequency.

## Results

OOS metrics:

| Strategy | CAGR | Sharpe | MDD | Calmar | Left-tail days <= -2% | Mean exposure | Annual turnover |
|---|---:|---:|---:|---:|---:|---:|---:|
| Buy-hold | 15.13% | 0.767 | -34.25% | 0.442 | 113 | 1.000 | 0.000 |
| Vol target | 7.70% | 0.626 | -20.56% | 0.375 | 39 | 0.724 | 2.432 |
| CED20 target | 7.88% | 0.609 | -24.43% | 0.323 | 45 | 0.684 | 0.650 |
| CED60 target | 6.30% | 0.513 | -25.21% | 0.250 | 45 | 0.654 | 0.682 |

Paired moving-block bootstrap versus the vol target:

- CED20 Sharpe diff mean: -0.0146, 95% CI [-0.2233, 0.2070].
- CED20 MDD diff mean: -2.50 percentage points, 95% CI [-10.06, 5.25].
- CED20 Calmar diff mean: -0.0163, 95% CI [-0.2196, 0.2287].
- CED20 left-tail frequency diff mean: +0.0030, 95% CI [-0.0043, 0.0104].
- CED60 Sharpe diff mean: -0.1070, 95% CI [-0.3269, 0.1335].
- CED60 MDD diff mean: -3.62 percentage points, 95% CI [-12.87, 4.76].
- CED60 Calmar diff mean: -0.0808, 95% CI [-0.3160, 0.1535].
- CED60 left-tail frequency diff mean: +0.0028, 95% CI [-0.0042, 0.0104].

CED turnover is much lower than vol-target turnover, but this did not translate
into better drawdown, Calmar, Sharpe, or left-tail performance.

## Verdict

NULL.

Fixed-horizon CED targeting does not pass the pre-specified gate versus 63-day
realized-vol targeting on the SPY/QQQ/IWM basket. The evidence is directionally
consistent with the earlier K1494/K1334 lesson: backward-looking drawdown or
tail-risk scalers can reduce turnover, but they should not be claimed to
anticipate fast crashes unless OOS evidence supports that claim.

## Research Honesty Notes

- All strategy exposures are explicitly lagged by one trading day before being
  applied to returns.
- The bootstrap seed is fixed.
- The CED OHLC path uses adjusted daily Low versus previous adjusted Close, but
  it approximates the basket's intraday low as the average constituent low
  return rather than reconstructing a true intraday portfolio path.
- This experiment is a robustness check, not a strategy launch gate.
