# K1336: EM FX Carry x FX-Vol Regime Double-Gate

## Motivation

The task asks whether an emerging-market FX carry strategy can be improved by a
two-condition gate: hold carry only when the interest-rate differential is high
and realized FX volatility is low. This is motivated by the carry literature:
carry earns risk premia in normal periods but can suffer unwind crashes when FX
volatility and funding stress rise.

This experiment is a free-data diagnostic. It uses USD/EM spot rates from
yfinance and FRED/OECD short-rate proxies. It is not a professional FX forward
carry book and should not be read as executable EM FX carry pricing.

## Literature

- Menkhoff, Sarno, Schmeling, and Schrimpf (2012), "Carry Trades and Global
  Foreign Exchange Volatility":
  https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2012.01728.x
- Lustig, Roussanov, and Verdelhan (2011), "Common Risk Factors in Currency
  Markets": https://academic.oup.com/rfs/article-abstract/24/11/3731/1589752
- Brunnermeier, Nagel, and Pedersen (2008), "Carry Trades and Currency
  Crashes": https://www.nber.org/papers/w14473
- FRED/OECD short-rate proxies: https://fred.stlouisfed.org/

## Related Internal Context

Prior VolPred memory is mixed. K18 found that global VIX timing helped an
AUD/JPY carry proxy. K416 found that carry crashes amplified SPY volatility, but
own carry volatility was not a clean positive timing signal after VIX control.
K1336 therefore tests a narrower rule: own currency carry plus own FX realized
volatility as an admission filter.

## Data

- FX source: yfinance adjusted close.
- FX tickers: `BRL=X`, `MXN=X`, `ZAR=X`, `IDR=X`.
- Rate source: FRED/OECD short-rate proxies.
- US funding proxy: `TB3MS`.
- EM rate proxies:
  - BRL: `IRSTCB01BRM156N`, monthly, available through 2023-12.
  - MXN: `IR3TIB01MXM156N`, monthly, available through 2026-04.
  - ZAR: `IR3TIB01ZAM156N`, monthly, available through 2026-04.
  - IDR: `IR3TIB01IDQ156N`, quarterly, available through 2026-Q1.
- Download window: 2004-01-01 to 2026-06-15.
- OOS evaluation window: 2012-01-03 onward.
- OOS observations: 3,763 trading days.
- Cached data: `data/fx_close.csv`, `data/fred_*.csv`, `data/panel.csv`.

## Data Cleaning

yfinance EM FX spot contains obvious decimal-place glitches. The script removes
daily spot log returns with absolute value above 15% before computing strategy
returns and realized volatility. Removed observations:

| Currency | Removed spot-return outliers |
|---|---:|
| BRL | 0 |
| MXN | 0 |
| ZAR | 5 |
| IDR | 14 |

This filter is necessary. Without it, an IDR quote error around 2012-02-07
dominates the whole backtest.

## Method

Spot is quoted as local currency per USD. A US investor long EM currency and
funded in USD is approximated as:

`daily_return = rate_diff_lag1 / 252 - dlog(USDLC)`

The pure carry baseline allocates 1/4 notional to each currency when lagged
EM-USD short-rate differential is positive.

The double-gate allocates 1/4 notional only when all three conditions hold:

- lagged rate differential is positive;
- lagged rate differential is above its rolling 756-day 60th percentile;
- lagged 60-day realized FX volatility is below its rolling 756-day median.

Lookahead controls:

- FRED monthly observations are delayed by 45 calendar days before daily use.
- FRED quarterly observations are delayed by 90 calendar days before daily use.
- Stale rates are masked after 120 days for monthly series and 210 days for
  quarterly series.
- Carry, realized volatility, and rolling thresholds use explicit `.shift(1)`.
- Strategy return at date `t` uses only signals available before date `t`.

Transaction cost is 5 bps per one-way notional change.

Formal tests:

- HAC(21) mean test of `gate_return - pure_return`.
- 1,000-rep 21-day moving-block bootstrap of Sharpe difference, seed 42.

Success gate:

- SUPPORT requires Sharpe improvement >= 0.15, HAC t-stat > 3 for mean return
  difference, MDD improvement >= 20%, and bootstrap Sharpe-diff 95% CI lower
  bound > 0.
- PARTIAL requires positive Sharpe improvement, positive MDD improvement, and
  bootstrap `p_gt_0 >= 0.80`.

## Results

Portfolio metrics:

| Strategy | Ann return | Ann vol | Sharpe | MDD | Avg exposure | Active share |
|---|---:|---:|---:|---:|---:|---:|
| Pure carry | 0.18% | 8.40% | 0.022 | -33.53% | 88.15% | 100.00% |
| Carry x low-FX-vol gate | 0.37% | 2.24% | 0.166 | -9.28% | 13.21% | 41.64% |

Formal comparison:

- Sharpe difference: +0.144, below the pre-specified +0.15 threshold.
- MDD improvement: +24.25 percentage points, or +72.3% relative improvement.
- HAC mean return difference: -0.14% annualized, t=-0.065, p=0.948.
- Bootstrap Sharpe difference: mean +0.135, 95% CI [-0.429, +0.689],
  `p_gt_0=0.67`.

Per-currency Sharpe:

| Currency | Pure Sharpe | Gate Sharpe |
|---|---:|---:|
| BRL | -0.030 | 0.406 |
| MXN | 0.293 | 0.215 |
| ZAR | -0.107 | -0.385 |
| IDR | -0.022 | -0.130 |

The gate reduces drawdown mainly by reducing exposure. Average gross exposure
falls from 88.15% to 13.21%. That risk reduction is real, but it is not enough
to prove superior timing or a tradable alpha edge.

## Verdict

NULL.

The double gate is useful as a conservative admission filter, but it does not
beat the pure carry baseline under the pre-specified statistical gate. The most
honest interpretation is that own FX volatility can reduce crash exposure by
sitting in cash, while the return improvement is statistically indistinguishable
from zero.

## Research Honesty Notes

- The experiment uses a spot-plus-rate-differential proxy, not forwards.
- Rate series are delayed before use to reduce FRED/OECD publication lookahead.
- Brazil's rate series ends in 2023, and stale-rate masking limits later BRL
  contribution.
- yfinance EM FX spot has data glitches; the outlier filter is documented and
  counted in results.
- The result should not be marketed as "EM carry timing works"; it is a NULL
  result with a drawdown-control caveat.
