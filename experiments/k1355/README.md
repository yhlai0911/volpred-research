# K1355: ML Daily Liquidity Proxy and the Volatility Channel

## Motivation

This experiment tests a narrow version of the Dai-Shi-Zhang liquidity idea with
free daily data: can a machine-learning estimate of daily market liquidity add
out-of-sample information for next-day volatility forecasts?

The research-program prompt mentions CPQS. True CPQS is the closing percent
quoted spread and requires closing bid and ask quotes. Yahoo/yfinance daily
OHLCV does not contain bid/ask quotes. Therefore this experiment does not claim
to estimate true CPQS. It builds a CPQS-like low-frequency percent-cost proxy
from daily range and Corwin-Schultz spread ingredients, then labels the result
as a proxy throughout.

## Prior Checks

Related internal findings searched before implementation:

- K150: Amihud fragility GARCH-X was null; daily Amihud is partly endogenous to
  volatility because it contains absolute returns.
- K154: daily OFI proxies showed some in-sample partial correlations, but did
  not deliver robust OOS forecasting gains.
- K1515: bond ETF illiquidity ML had model-class caveats and did not show a
  significant joint feature-set gain.

External anchors:

- Dai, Shi, and Zhang, "Estimating Market Liquidity from Daily Data: Marrying
  Microstructure Models and Machine Learning", Journal of Financial Markets
  forthcoming/2026.
- Chung and Zhang (2014), closing percent quoted spread.
- Corwin and Schultz (2012), high-low spread estimator.
- Goyenko, Holden, and Trzcinka (2009), plus Fong, Holden, and Trzcinka (2017),
  low-frequency liquidity proxy validation.

## Data

- Source: yfinance daily OHLCV, `auto_adjust=False`.
- Tickers: SPY, QQQ, IWM, EEM, HYG, LQD, TLT, GLD, and VIX.
- Requested sample: 2010-01-01 to run date.
- OOS split: 2020-01-01 onward.
- Raw download is saved to `data/yfinance_raw_ohlcv.csv`.
- Derived panel is saved to `data/derived_panel.csv`.

## Method

1. Build a low-frequency percent-cost proxy:
   - daily high-low range divided by close;
   - Corwin-Schultz two-day high-low spread estimate;
   - geometric average of those positive daily ingredients.
2. Fit pre-2020 pooled models to estimate the proxy from lagged daily features:
   - Ridge baseline;
   - Gradient Boosting primary ML model;
   - one-hidden-layer MLP diagnostic.
3. Convert the model-estimated spread into a cross-asset system liquidity
   factor using pre-2020 asset-level means and standard deviations.
4. Predict next-day range variance with a HAR-style baseline:
   - lagged 1d, 5d, and 22d range variance;
   - lagged VIX daily variance.
5. Add the lagged system liquidity factor and compare OOS QLIKE loss with the
   baseline using the project helper `dm_test`. The primary pooled DM first
   averages loss differences by date across assets, then runs HAC DM on that
   date series, so same-day cross-asset dependence is not treated as eight
   independent observations.

## Lookahead Policy

All predictors in the volatility-channel test use information available no
later than `t-1`. The code contains explicit shifted signal columns:

```python
factor_df[f"{name}_signal"] = factor_df[name].shift(1)
```

The OOS volatility models train only on observations before 2020-01-01 and are
evaluated on 2020 onward.

## Success Criteria

The statistical gate passes only if:

- pooled QLIKE improves after adding the Gradient-Boosting liquidity factor;
- at least 5 of 8 assets improve;
- pooled DM statistic is below -3.0, the project Harvey-strength gate.

Even if this statistical gate passes, the strongest honest verdict is capped at
`CONDITIONAL_PASS_PROXY`, because the experiment lacks true bid/ask or
high-frequency labels. A null result would not refute the Dai-Shi-Zhang result
for the same reason.

## Results

Generated on 2026-06-21 with yfinance history through 2026-06-19.

- Liquidity-proxy estimation: Gradient Boosting OOS R2 = 0.562 on the
  CPQS-like target; Ridge OOS R2 = 0.538; MLP OOS R2 = 0.540.
- Primary volatility-channel test: adding the lagged GB system-liquidity factor
  improves pooled OOS QLIKE by 10.31%.
- The date-clustered pooled DM statistic is -2.24 (p = 0.025), which is not
  Harvey-strength under the project gate of t < -3.0.
- 7 of 8 assets improve on QLIKE, but only 2 of 8 pass per-asset Harvey.
- Final verdict: `MIXED_WEAK`. Directionally interesting proxy evidence, not a
  publishable strong liquidity claim.
