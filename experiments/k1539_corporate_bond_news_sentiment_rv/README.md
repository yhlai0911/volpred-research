# K1539 - Corporate-bond news proxy and credit ETF risk targets

## Motivation

This experiment tests whether a free corporate-credit news proxy has more
predictive content for risk targets than for bond ETF returns.  The task comes
from the research backlog line: "corporate-bond news sentiment 的 RV-only 再檢定:
報酬小不代表風險無訊號".

The experiment is a free-data diagnostic.  It does not replicate bond-level
TRACE returns or a licensed news-sentiment database.

## Differentiation

Prior internal results already cover adjacent channels:

- K1487: coarse GDELT novel-risk keyword intensity failed to improve RV
  forecasts and often worsened QLIKE.
- K1522: corporate-bond ETF factor-zoo proxy audit was null after conservative
  lag discipline.
- K1538: bond-fund run-pressure proxy showed weak directional credit ETF RV
  evidence but failed formal gates.

K1539 differs by focusing on corporate-credit news keywords and by explicitly
comparing return targets against next-week RV, downside semivariance, and
HYG-minus-LQD drawdown targets.

## Literature Precheck

- Journal of Fixed Income Winter 2026, "Corporate Bond Returns: Does News
  Sentiment Matter?"  Used only as motivation for the return-vs-risk framing.
- Tetlock (2007), "Giving Content to Investor Sentiment", Journal of Finance.
- Baker, Bloom, and Davis (2016), "Measuring Economic Policy Uncertainty", QJE.
- GDELT DOC 2.0 API documentation for free news timeline proxies.

## Data

- Market data: yfinance adjusted daily close, requested 2020-01-01 to
  2026-06-24.
- ETFs: `HYG`, `LQD`, `BKLN`, `VCIT`, `VCSH`, `SPY`, `^VIX`.
- News data: GDELT DOC 2.0 TimelineVol for corporate-credit keyword buckets:
  corporate bond, high yield / leveraged loan, credit spread, and
  default/downgrade.  TimelineTone is attempted and its availability is recorded
  in the results JSON.
- If fresh GDELT calls are rate-limited, the script falls back to the existing
  K1487 `private_credit` TimelineVol cache and labels the run as an adjacent
  proxy diagnostic rather than a full corporate-bond sentiment test.
- Live GDELT is opt-in via `K1539_USE_LIVE_GDELT=1`; default execution uses the
  existing cache because this hourly run hit GDELT HTTP 429 / SSL stalls.

## Method

The news proxy is:

- `news_volume_z`: rolling z-score of `log1p(GDELT TimelineVol)`, averaged
  across keyword buckets.
- `news_negative_tone_z`: rolling z-score of negative GDELT TimelineTone when
  the endpoint returns a valid series.
- `news_stress_z`: mean of volume and negative-tone z-scores when tone is
  available; otherwise volume intensity alone.

Lookahead guard: every predictive test uses
`signal_lag = news_stress_z.shift(1)`.  Targets begin on date `t`, so the news
signal uses only information through `t-1`.

Formal tests:

- HAC predictive regressions with controls for own lagged RV21, SPY lagged
  RV21, lagged log VIX, and lagged HYG-LQD credit underperformance.
- Return targets: next 5/21 trading-day cumulative returns, expected sign
  negative under stress.
- Risk targets: next 5/21 trading-day realized variance, downside
  semivariance, and HYG-underperforms-LQD drawdown, expected sign positive.
- Harvey-style `|t| >= 3` gate, plus Bonferroni and BH q-values.
- Expanding-window OOS MSE comparison for risk targets, with HAC DM test on
  augmented-minus-baseline squared-error loss.  The OOS warm-up is 504 trading
  days because the available cached GDELT proxy starts in 2023.

## Outputs

- `k1539_corporate_bond_news_sentiment_rv.py`
- `k1539_corporate_bond_news_sentiment_rv_results.json`
- `k1539_corporate_bond_news_sentiment_rv_daily_panel.csv`
- `figures/k1539_news_proxy_timeseries.png`
- `figures/k1539_hac_tstats.png`

## Limitations

- GDELT keyword buckets are coarse and not a validated bond-news classifier.
- TimelineVol measures attention/intensity, not true sentiment.
- A rate-limited run using only the K1487 private-credit cache is weaker than
  the intended full corporate-credit bucket panel.
- ETF volatility is not underlying TRACE corporate-bond volatility.
- Results are predictive associations, not causal evidence.
