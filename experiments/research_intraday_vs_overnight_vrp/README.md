# Intraday vs Overnight Pseudo-VRP Decomposition

## Motivation

Recent variance-risk-premium work decomposes option-implied variance risk
premia into trading-period and nontrading-period components. The backlog
question was whether a free-data version can show that overnight variance
premium dominates across assets and predicts next-day realized volatility.

This experiment is deliberately conservative. Daily yfinance OHLC data do not
contain option chains or model-free implied variance. Therefore, the experiment
uses rolling one-step GARCH(1,1) variance forecasts as an ex-ante
physical-measure proxy and calls the object `pseudo-VRP`, not true option VRP.

## Literature

- Papagelis and Dotsis (2025), "The Variance Risk Premium Over Trading and
  Nontrading Periods": https://onlinelibrary.wiley.com/doi/full/10.1002/fut.22589
- Carr and Wu (2009), "Variance Risk Premia": https://doi.org/10.1093/rfs/hhn038
- Bollerslev, Tauchen, and Zhou (2009), "Expected Stock Returns and Variance
  Risk Premia": https://www.federalreserve.gov/pubs/feds/2007/200711/
- Corsi (2009), "A Simple Approximate Long-Memory Model of Realized Volatility":
  https://doi.org/10.1093/jjfinec/nbp001

## Related Internal Context

Prior VolPred memory already warns that VIX/GARCH VRP-like spreads are not
reliable directional equity timing signals, that same-day VIX timing creates
lookahead bias, and that overnight/intraday decomposition must not mix
incompatible targets. This experiment narrows the question to variance
decomposition and next-day realized-variance prediction.

## Data

- Source: yfinance adjusted OHLC with `auto_adjust=True`.
- Assets: SPY, QQQ, IWM, EFA.
- Download window: 2003-01-01 to 2026-06-15.
- Analysis starts after warmup on 2007-01-03.
- OOS period: 2018-01-02 to 2026-06-12.
- OOS sample size after GARCH warmup: 2,123 days per asset.
- Cached inputs: `data/open.csv`, `data/high.csv`, `data/low.csv`,
  `data/close.csv`.

## Method

Returns are decomposed as:

- overnight: `log(Open_t / Close_{t-1})`
- intraday: `log(Close_t / Open_t)`
- close-to-close: `log(Close_t / Close_{t-1})`

Realized session variance is `overnight_return^2 + intraday_return^2`.
Close-to-close variance differs by the covariance residual
`2 * overnight_return * intraday_return`.

For the ex-ante proxy, the script fits rolling zero-mean GARCH(1,1) models on
close-to-close returns:

- trailing window: 1,000 observations
- refit frequency: 21 trading days
- forecast timing: the variance forecast for day `t` uses returns through `t-1`

The total GARCH variance is allocated into overnight and intraday expected
components using the trailing 252-day overnight share, shifted by one day. The
pseudo-premium is:

`expected_component_variance - realized_component_variance`

Predictive regressions test whether yesterday's pseudo-premia predict today's
log session variance:

`log(session_var_t) ~ overnight_pseudo_vrp_{t-1} + intraday_pseudo_vrp_{t-1} + log(session_var_{t-1}) + log(garch_var_{t-1})`

Standard errors are Newey-West HAC with 5 lags. Share and premium uncertainty
uses a 1,000-rep moving-block bootstrap with 21-day blocks and seed 42.

The pre-specified support gate requires both:

- overnight realized variance share bootstrap CI lower bound > 0.5 in at least
  3 of 4 assets;
- lagged overnight pseudo-VRP HAC t-stat > 3 in at least 3 of 4 assets.

## Results

OOS realized session-variance shares:

| Asset | Overnight share | Intraday share | Overnight share 95% CI | Mean overnight var (%^2) | Mean intraday var (%^2) |
|---|---:|---:|---:|---:|---:|
| SPY | 0.426 | 0.574 | [0.333, 0.524] | 0.617 | 0.832 |
| QQQ | 0.379 | 0.621 | [0.318, 0.451] | 0.849 | 1.394 |
| IWM | 0.397 | 0.603 | [0.332, 0.461] | 0.943 | 1.433 |
| EFA | 0.646 | 0.354 | [0.566, 0.715] | 0.866 | 0.474 |

Only EFA has robust overnight majority. For the US ETFs, intraday variance is
larger over 2018-2026.

Predictive regressions:

| Asset | Overnight pseudo-VRP coef | Overnight HAC t | Intraday pseudo-VRP coef | Intraday HAC t | R2 |
|---|---:|---:|---:|---:|---:|
| SPY | -0.0218 | -0.653 | -0.0917 | -3.091 | 0.213 |
| QQQ | -0.0738 | -2.286 | -0.0310 | -0.882 | 0.170 |
| IWM | -0.0170 | -0.523 | -0.1077 | -3.934 | 0.157 |
| EFA | -0.0391 | -1.280 | -0.0789 | -2.647 | 0.153 |

No asset has lagged overnight pseudo-VRP with positive HAC t > 3. Some intraday
pseudo-VRP coefficients are significantly negative, which is not the tested
overnight-dominance mechanism and should not be promoted as a positive result.

## Verdict

NULL.

The yfinance-only pseudo-VRP proxy does not support a broad cross-asset claim
that overnight variance premium dominates and predicts next-day realized
variance. The only robust overnight-majority asset is EFA. For SPY, QQQ, and
IWM, intraday variance is larger over the OOS window. The lagged overnight
pseudo-VRP predictor fails the pre-specified Harvey-style t-stat gate in all
four assets.

## Research Honesty Notes

- This is not a replication of the model-free option-implied VRP literature.
- The object measured here is a GARCH forecast-error proxy, not investable
  option carry.
- Predictive features are explicitly shifted by one trading day.
- The result is useful as a free-data diagnostic and a warning against
  overclaiming option-VRP conclusions from OHLC-only data.
