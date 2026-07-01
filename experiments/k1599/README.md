# K1599 - Daily Co-Jump Proxy and HAR-CJ-Style Forecast Test

## Verdict

`SUPPORTED_DAILY_PROXY`

Lagged daily co-jump proxy features improve one-day-ahead squared-return QLIKE forecasts across a 12-ETF panel. `HAR_CJ_proxy` is the best mean-QLIKE model for all 12 assets, records 18 strict Harvey/Holm wins, and records zero strict losses. The result is positive but deliberately scoped: this is a daily proxy diagnostic, not a high-frequency BNS/Lee-Mykland HAR-CJ replication.

## Motivation

The backlog asks whether systemic co-jumps and HAR-CJ jump decomposition can become a stronger VolPred jump axis. Earlier project work, especially K1303, showed that loose HAR-CJ implementations can overclaim. K1599 therefore tests a narrower question:

Do lagged cross-ETF daily co-jump counts, detected with a BNS-style rolling bipower scale, improve daily volatility forecasts beyond HAR and own-jump HAR baselines?

## Literature Checked

- Bollerslev, Law, and Tauchen (2017), "Risk, jumps, and diversification." https://ideas.repec.org/a/eee/jfinec/v126y2017i3p563-591.html
- Barndorff-Nielsen and Shephard (2004), "Power and bipower variation with stochastic volatility and jumps." https://academic.oup.com/jfec/article-abstract/2/1/1/960705
- Andersen, Bollerslev, and Diebold (2007), "Roughing It Up: Including Jump Components in the Measurement, Modeling, and Forecasting of Return Volatility." https://ideas.repec.org/a/tpr/restat/v89y2007i4p701-720.html
- Lee and Mykland (2008), "Jumps in Financial Markets: A New Nonparametric Test and Jump Dynamics." https://academic.oup.com/rfs/article-abstract/21/6/2535/1574138
- Lee, Lee, and Kim (2022), sector ETF co-jumps and volatility forecasting motivation. https://www.mdpi.com/1911-8074/15/8/334

## Data

- Source: `experiments/k1552/data/prices.parquet`
- Assets: `SPY`, `QQQ`, `IWM`, `XLB`, `XLE`, `XLF`, `XLI`, `XLK`, `XLP`, `XLU`, `XLV`, `XLY`
- Return sample: 2005-01-01 onward
- OOS start: 2016-01-01
- Target: next-day close-to-close squared log return
- Loss: QLIKE on `actual_r2` and model forecast

## Jump and Co-Jump Proxy

The repository does not currently contain synchronized cross-ETF 5-minute bars, so K1599 uses a daily BNS-style scale:

`|r_t| / sqrt((pi/2) * rolling_mean(|r_{t-1}| * |r_{t-2}|)) > 2.5`

This flags large daily jumps against a lagged bipower-style volatility scale. Same-day co-jump count is the number of ETFs flagged on date `t`; all jump and co-jump features are shifted at least one day before the forecast target.

Jump rates are about 2.6% to 3.6% by ETF. There are 236 days with at least 3 ETF jumps and 118 days with at least 6 ETF jumps.

## Models

- `HAR_daily`: log-r2 HAR with 1-day, 5-day, and 22-day lagged components
- `HAR_J_proxy`: `HAR_daily` plus own lagged jump, down-jump, 5-day jump rate, and jump-ratio features
- `HAR_CJ_proxy`: `HAR_J_proxy` plus lagged cross-ETF co-jump and down-co-jump features

All models are annual-refit expanding-window log-OLS forecasts.

## Results

Mean asset-level QLIKE, lower is better:

| Model | Mean QLIKE |
|---|---:|
| HAR_CJ_proxy | 2.2489 |
| HAR_J_proxy | 2.2638 |
| HAR_daily | 2.2915 |

Strict HAR-CJ wins:

- 12/12 wins versus `HAR_daily`
- 6/12 wins versus `HAR_J_proxy`
- 0 strict losses

Co-jump stress diagnostic:

| Next-day market metric | High co-jump mean | Low co-jump mean | Difference | Welch t | p-value |
|---|---:|---:|---:|---:|---:|
| mean r2 | 0.000473 | 0.000184 | 0.000289 | 3.07 | 0.00239 |
| mean abs return | 0.013586 | 0.009061 | 0.004525 | 4.60 | 0.00000668 |

High co-jump days are followed by higher next-day market volatility, and the lagged co-jump features translate into OOS QLIKE gains in this daily panel.

## Interpretation

Safe claim:

> Daily cross-ETF co-jump proxy counts are a useful stress-state feature and improve next-day squared-return volatility forecasts in this 12-ETF OOS test.

Unsafe claim:

> This proves a high-frequency HAR-CJ / Lee-Mykland co-jump model is ready for paper use.

That would overstate the evidence. K1599 is positive, but it is not synchronized intraday co-jump identification. A paper-grade result needs 5-minute cross-asset RV/BPV, formal jump tests, threshold sensitivity, and a proper continuous-vs-jump decomposition.

## K1303 Guardrail

K1303 failed because HAR-CJ was overclaimed after weak jump identification and evaluation choices. K1599 avoids that failure mode by:

- labeling the method as a daily proxy;
- using a bipower-style lagged scale rather than raw truncation alone;
- evaluating with QLIKE and paired DM/Holm tests;
- keeping the conclusion below high-frequency replication strength.

## Artifacts

- `k1599.py`
- `k1599_results.json`
- `k1599_oos_forecasts.csv.gz`
- `k1599_cojump_har_proxy.png`
- `codex_review.md`
- `knowledge_handoff.md`
