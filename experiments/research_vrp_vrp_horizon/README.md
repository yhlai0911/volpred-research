# Downside/Upside VRP Proxy and Cross-Horizon SPY Predictability

## Motivation

The backlog question was whether a downside variance-risk-premium component is
larger than the upside component and whether its predictive power for SPY
returns or realized variance is concentrated at medium horizons.

This experiment is deliberately conservative. Free yfinance data provide SPY
returns and total VIX implied variance, but they do not provide true
option-implied downside and upside variance. The test therefore builds a
reduced-form proxy: total VIX variance is split into downside and upside legs
using lagged trailing realized semivariance shares. This can screen the idea,
but it cannot replace an option-chain or model-free variance-swap
decomposition.

## Literature

- Bollerslev, Tauchen, and Zhou (2009), "Expected Stock Returns and Variance
  Risk Premia": https://academic.oup.com/rfs/article-abstract/22/11/4463/1565787
- Bekaert and Hoerova (2014), "The VIX, the Variance Premium and Stock Market
  Volatility": https://ideas.repec.org/p/nbr/nberwo/18995.html
- "Downside Variance Risk Premium", Federal Reserve FEDS working paper:
  https://www.federalreserve.gov/econresdata/feds/2015/files/2015020pap.pdf
- "Variance and Skewness Risk Premium and Expected Equity Returns":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=6712647

## Related Internal Context

This test extends, but does not overturn, existing VolPred VRP results:

- K913 found total VRP positive but not a reliable SPY return-timing signal.
- K1452 found the free-data segment VRP sign-split story fragile and
  proxy-dependent.
- K1476 found no robust post-2018 VRP decline story and reinforced that VRP
  proxies require careful horizon alignment.

## Data

- Source: yfinance adjusted close.
- Tickers: SPY and ^VIX.
- Download window: 2004-01-01 to 2026-06-15.
- Analysis sample: 2010-01-04 onward after 252-day share warmup.
- Rows with valid downside/upside VRP proxy: 4,136.
- Cached inputs: `data/close.csv` and `data/panel.csv`.

## Method

Daily SPY log returns are split into realized downside and upside squared
returns:

- downside realized variance: `min(ret, 0)^2`
- upside realized variance: `max(ret, 0)^2`

Total implied variance proxy:

`iv_total = (VIX / 100)^2`

The free-data down/up split is:

`iv_down_proxy = iv_total_lag1 * trailing_252d_downside_semivariance_share_lag1`

`iv_up_proxy = iv_total_lag1 * trailing_252d_upside_semivariance_share_lag1`

Realized legs use trailing 22-trading-day annualized semivariance. All signal
inputs are shifted by one trading day before any forward target:

- `iv_total_lag1`
- `rv_total_22_lag1`
- `rv_down_22_lag1`
- `rv_up_22_lag1`
- `down_share_252_lag1`
- `ret_21_lag1`

VRP proxy definitions:

- `vrp_total_lag1 = iv_total_lag1 - rv_total_22_lag1`
- `vrp_down_lag1 = iv_down_proxy_lag1 - rv_down_22_lag1`
- `vrp_up_lag1 = iv_up_proxy_lag1 - rv_up_22_lag1`

Targets are forward SPY cumulative log return and log forward annualized
realized variance at 21, 63, and 126 trading days. Predictive regressions use
Newey-West HAC standard errors with maxlags equal to the overlapping target
horizon. Controls are lagged log 22-day realized variance and lagged 21-day SPY
return. Mean tests use HAC(22). Mean uncertainty also uses a 1,000-rep
21-day moving-block bootstrap with seed 42.

The pre-specified gate is:

- sign support: downside VRP mean t > 3, downside-minus-upside spread t > 3,
  and the bootstrap spread 95% CI lower bound > 0;
- return support: downside VRP return-prediction t > 3 at 63 or 126 days and
  larger than the 21-day t-stat;
- RV support: downside VRP realized-variance-prediction t > 3 at 63 or 126
  days and larger than the 21-day t-stat;
- SUPPORT requires all three legs; PARTIAL requires at least one leg.

## Results

Mean VRP proxy tests:

| Component | Mean vol points squared | HAC t | HAC p |
|---|---:|---:|---:|
| Total VRP | 91.84 | 4.07 | 0.000046 |
| Downside VRP | 49.44 | 4.00 | 0.000065 |
| Upside VRP | 42.40 | 3.68 | 0.000237 |
| Downside minus upside | 7.04 | 0.88 | 0.380 |

The total VRP proxy is positive, and both down and up components are positive.
However, the downside-minus-upside spread is not statistically reliable. The
bootstrap 95% CI for the spread is [-8.81, 23.18] vol points squared.

Predictive regression t-stats:

| Target | Horizon | Downside VRP t | Upside VRP t | Total VRP t |
|---|---:|---:|---:|---:|
| Return | 21d | 1.56 | -2.46 | -0.82 |
| Return | 63d | 2.26 | -2.93 | -0.92 |
| Return | 126d | 1.90 | -2.04 | -0.85 |
| Log RV | 21d | 1.46 | 0.56 | 2.12 |
| Log RV | 63d | -0.53 | 1.28 | 1.60 |
| Log RV | 126d | -1.27 | 1.41 | 1.17 |

The 63-day return regression is directionally consistent with the medium-horizon
story, but the downside t-stat is only 2.26 and does not meet the pre-specified
t > 3 gate. The realized-variance target fails more clearly: downside VRP is
not positive at 63 or 126 days.

## Verdict

NULL.

The free-data downside/upside VRP proxy does not pass the sign plus
medium-horizon prediction gate. The only defensible statement is narrow:
aggregate VRP and both semivariance-allocated components are positive on
average, but the downside component is not reliably larger than the upside
component and does not robustly predict medium-horizon SPY returns or realized
variance under this proxy.

## Research Honesty Notes

- This is not a true option-implied downside/upside variance decomposition.
- VIX is a roughly 30-calendar-day total implied variance proxy, so 63-day and
  126-day regressions are reduced-form horizon tests.
- All predictors are explicitly lagged by one trading day.
- The result should not be used as an article claim that downside VRP dominates
  unless a later option-chain decomposition confirms it.
