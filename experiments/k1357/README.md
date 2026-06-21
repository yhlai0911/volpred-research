# K1357: RLMM Spread-Asymmetry Fingerprint

## Motivation

The backlog asks whether reinforcement-learning market makers leave a
low-frequency footprint: after otherwise symmetric market-making cost shocks,
does liquidity deteriorate more on negative market days than positive market
days, and does that deterioration forecast near-term realized variance?

This experiment is deliberately a free-data proxy test. It cannot observe
actual bid/ask quotes, order-book depth, market-maker inventory, or algorithmic
market-maker behavior.

## Prior Internal Checks

- K1355 found a directionally useful but sub-Harvey daily liquidity proxy for
  volatility forecasting. K1357 is narrower: it tests an asymmetric spread
  response around cost shocks, not a generic liquidity factor.
- K1498 already used Corwin-Schultz and other daily liquidity proxies for
  option-liquidity crash-risk diagnostics. K1357 reuses the low-frequency
  spread-estimator logic but changes the mechanism and target.
- `docs/error_log.md` records the K1355 pooled-DM mistake: multi-asset
  asset-days must not be treated as independent. K1357 therefore date-clusters
  pooled forecast loss differences.

## External Anchors

- Colliard, Foucault, and Lovo, "Algorithmic Pricing and Liquidity in
  Securities Markets", *Review of Financial Studies* advance article, 2026.
  The paper studies Q-learning algorithmic market makers and finds that higher
  profit volatility can produce less competitive market outcomes.
- Corwin and Schultz (2012), *Journal of Finance*, "A Simple Way to Estimate
  Bid-Ask Spreads from Daily High and Low Prices".
- Classic market-making theory links bid-ask spreads to inventory risk,
  adverse selection, and price-risk costs. This experiment only asks whether a
  daily proxy carries a detectable footprint.

## Data

- yfinance daily OHLCV, `auto_adjust=False`.
- Assets: `SPY`, `QQQ`, `IWM`, `AAPL`, `MSFT`, `NVDA`, `AMZN`, `GOOGL`,
  `META`, `TSLA`.
- Market shock controls: `^VIX` and SPY adjusted-close returns.
- Sample starts 2012-01-01; OOS forecast evaluation starts 2020-01-01.

## Proxy Design

Spread proxy:

- Corwin-Schultz daily high-low effective-spread estimator.
- Transformed as `log1p(100 * spread)` before z-scoring and response tests.

Cost shock:

- `0.5 * abs(VIX return z) + 0.5 * positive asset dollar-volume z >= 1.0`.
- The sign split is SPY close-to-close return on the shock day.

Event test:

- Shock day `t` is known at close `t`.
- Response is the next trading day's spread-proxy change:
  `spread_log[t+1] - spread_log[t]`.
- Primary statistic is the date-level mean response after negative-market
  shocks minus positive-market shocks, with fixed-seed bootstrap CI.

Forecast test:

- Target at row `t` is close-to-close realized variance over `t+1..t+5`.
- Baseline: HAR realized-variance features + lagged VIX z + lagged volume z.
- Challenger: baseline + lagged spread z + lagged negative-cost-spread
  interaction.
- Per-asset OOS expanding OLS with annual refits.
- Pooled DM first averages same-date cross-asset QLIKE loss differentials, then
  runs HAC DM with `h=5`.

## Lookahead Policy

The forecasting panel explicitly uses `.shift(1)`:

```python
frame["log_rv_1_lag1"] = np.log(rv).shift(1)
frame["log_rv_5_lag1"] = np.log(rv.rolling(5).mean()).shift(1)
frame["log_rv_22_lag1"] = np.log(rv.rolling(22).mean()).shift(1)
frame["vix_z_lag1"] = frame["vix_z"].shift(1)
frame["volume_z_lag1"] = frame["volume_z"].shift(1)
frame["spread_z_lag1"] = frame["spread_z"].shift(1)
frame["asym_spread_cost_lag1"] = frame["asym_spread_cost"].shift(1)
```

Rolling z-scores use past rolling moments via `x.shift(1)` before computing
the mean and standard deviation.

## Success Criteria

`CONDITIONAL_PASS_PROXY` requires both:

- event asymmetry bootstrap CI lower bound above zero; and
- OOS forecast pooled DM `t < -3.0`, with at least 7 of 10 assets improving on
  QLIKE.

`EVENT_ONLY_WEAK` is used if only the event asymmetry gate passes. `MIXED_WEAK`
is used for directionally favorable forecast evidence below Harvey strength.
Otherwise the result is `NULL`.

## Results

Verdict: `EVENT_ONLY_WEAK`.

Event response:

- Date-level negative-market minus positive-market cost-shock spread response:
  `+0.0457` in next-day `log1p(100 * CS spread)` units.
- Fixed-seed bootstrap 95% CI: `[+0.0006, +0.0896]`.
- Event sample: 908 negative-market shock dates and 1,062 positive-market
  shock dates after date-level aggregation.

Forecast test:

- Pooled `HAR_VIX_VOL_SPREAD_ASYM` vs `HAR_VIX_VOL` QLIKE loss differential:
  `+0.000631`, DM `t=+0.626`, `p=0.531`.
- Positive QLIKE improvement assets: 3 of 10.
- Best single asset was `IWM` at `+0.44%`; `QQQ` was worst at `-0.65%`.

Interpretation: the daily spread proxy has an event-study asymmetry consistent
with one-sided liquidity deterioration after negative cost shocks, but that
footprint does not translate into robust next-week RV forecast improvement.
The result is therefore not promotable as a strong K finding.

## Claim Ceiling

Even a positive result would be only a daily OHLCV proxy finding. It would not
identify reinforcement-learning market makers, true bid/ask quotes, quote
depth, inventory constraints, or intraday market-making conduct.

## Files

- `K1357.py`
- `K1357_results.json`
- `K1357_spread_asymmetry.png`
- `codex_review.md`
- `data/`
