# K1539 - Corporate-bond news sentiment and RV-only risk targets

## Motivation

This experiment tests the backlog hypothesis that news sentiment may have an
economically small effect on corporate-bond ETF returns, but could still carry
incremental information for risk targets such as next-week realized volatility,
downside semivariance, or a HYG-minus-LQD spread-proxy drawdown.

## Differentiation

This is not a rerun of K1538. K1538 built a bond-fund run-pressure proxy from
ETF volume, price pressure, illiquidity, and cash-migration variables. K1539
uses a text-based sentiment proxy and asks whether the signal is more visible in
risk targets than in return targets.

Related internal priors:

- K1463: free attention/sentiment vol proxy, broad market.
- K1528: free sentiment-beta cross-section, return premium null.
- K1538: bond-fund run-pressure proxy for credit ETF volatility, weak directional
  but gate-failing.

## Literature Precheck

- Shapiro, Sudhof, and Wilson, "Measuring News Sentiment", FRB San Francisco
  Working Paper 2017-01.
- Buckman, Shapiro, Sudhof, and Wilson, "News Sentiment in the Time of COVID-19",
  FRBSF Economic Letter 2020-08.
- Bao and Pan, "Excess Volatility of Corporate Bonds", working paper.
- "Dispersion in News Sentiment and Corporate Bond Returns", SSRN working paper,
  motivates corporate-bond-specific text signals.

## Data

- FRBSF Daily News Sentiment Index, downloaded from the FRBSF Excel file.
  Effective sentiment span: 1980-01-01 to 2026-06-21.
- yfinance adjusted daily OHLCV, requested 2007-01-01 to 2026-06-24.
- ETFs / controls: `HYG`, `LQD`, `BKLN`, `VCIT`, `VCSH`, `SPY`, `^VIX`.
- Effective merged panel: 2007-07-05 to 2026-06-23, 4,899 daily rows.
- GDELT corporate-credit keyword tone was attempted as a last-3-month diagnostic,
  but the public DOC API returned HTTP 429 during this run. The formal results
  therefore use FRBSF news sentiment only.

## Method

Primary signal:

`sentiment_stress_lag = (-rolling_zscore(FRBSF sentiment)).shift(1)`

Higher values mean more negative news sentiment. The `.shift(1)` is explicit:
targets dated `t` use only information through `t-1`.

Targets:

- forward 5-trading-day log return,
- forward 5-trading-day annualized realized volatility,
- forward 5-trading-day annualized downside semivolatility,
- forward 5-trading-day HYG-minus-LQD spread-proxy drawdown.

Controls:

- own lagged RV21,
- own lagged 5-day return,
- SPY lagged RV21,
- lagged log VIX.

Tests:

- OLS with Newey-West HAC standard errors, max lag 5.
- Multiple-testing control with Bonferroni and BH q-values across 16 tests.
- Expanding-window OOS forecasts, refit every 21 trading days, comparing
  controls-only baseline versus baseline plus sentiment stress.
- OOS loss comparison uses `volpred.stats.model_evaluation.dm_test` on MSE loss.
- Gate: Harvey-style `|t| >= 3`; OOS gate requires MSE improvement and DM
  `t <= -3`.

## Results

Verdict: **NULL_NEWS_SENTIMENT_RISK_TARGET**.

Return effect is economically small. The largest return effect is `HYG`:

- beta = -0.000773 per sentiment-stress unit,
- 1-sigma effect = -0.000986 5-day log return, about -9.9 bps,
- HAC t = -1.94,
- Bonferroni p = 0.843,
- gate = FAIL.

The strongest risk-target regression is `LQD` downside semivolatility:

- beta = +0.00226 annualized downside semivol,
- 1-sigma effect = +0.00288 annualized downside semivol,
- HAC t = +2.43,
- Bonferroni p = 0.243,
- gate = FAIL.

OOS forecasting is worse for every tested target. The least-bad risk OOS cell is
`VCSH` downside semivolatility:

- baseline MSE = 0.0003219,
- augmented MSE = 0.0003224,
- MSE improvement = -0.17%,
- DM t = +1.55,
- gate = FAIL.

## Interpretation

This free-data proxy does not support the risk-only hypothesis. Negative news
sentiment is directionally associated with slightly weaker `HYG` / `LQD` returns
and somewhat higher `LQD` downside semivolatility, but none of the effects
survive Harvey-strength or multiple-testing gates. Adding sentiment also worsens
OOS MSE across all return and risk targets.

The correct conclusion is a null result: FRBSF broad news sentiment is not a
robust corporate-bond ETF risk-target predictor in this design. A stronger
retest would need a reliable long-history corporate-credit-specific news feed or
bond-level TRACE / spread data, not only broad economic news sentiment.

## Outputs

- `k1539_corporate_bond_news_sentiment_rv_only.py`
- `k1539_corporate_bond_news_sentiment_rv_only_results.json`
- `k1539_corporate_bond_news_sentiment_rv_only_daily_panel.csv`
- `figures/k1539_sentiment_stress.png`
- `figures/k1539_risk_target_hac_tstats.png`
- `figures/k1539_oos_mse_improvement.png`

## Limitations

- FRBSF sentiment is broad economic news sentiment, not corporate-credit-only
  sentiment.
- GDELT corporate-credit tone was rate-limited in this run.
- ETF adjusted-close data are not TRACE bond-level returns or credit spreads.
- The HYG-minus-LQD drawdown is a spread proxy, not an observed option-adjusted
  spread.
- Results are predictive associations, not causal news effects.
