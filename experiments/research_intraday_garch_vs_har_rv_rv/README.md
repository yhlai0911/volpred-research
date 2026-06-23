# research_intraday_garch_vs_har_rv_rv

## Motivation

The research backlog asked whether a multiplicative intraday component model
can improve realized-variance forecasting stability relative to plain HAR-RV.
This is close to the HAR-RV / realized-GARCH track in `research_program.md`, but
it focuses on the information in the intraday volatility shape itself.

## Prior Knowledge

- `research_program.md` records HAR-RV as a strong baseline, while warning that
  target choice matters: HAR-RV should be judged on realized variance, not mixed
  with close-to-close GARCH targets.
- `storage/memory/knowledge.json` has related entries: K1349 is a 0050.TW
  5-minute HAR-RV pilot with insufficient OOS data; K1533 finds that realized
  measures help but neural/complex structures often fail to beat classical
  baselines once leakage is removed.
- Relevant error-log rules: no lookahead, no mechanical target-mismatch claims,
  and no paper-grade claim when OOS < 252 days.

## Literature

- Corsi (2009), Journal of Financial Econometrics: HAR-RV baseline with daily,
  weekly, and monthly realized-volatility components.
- Andersen and Bollerslev (1997), Journal of Empirical Finance: intraday
  periodicity and volatility persistence.
- Engle and Sokalska (2012), Journal of Financial Econometrics: multiplicative
  component GARCH decomposing volatility into daily, diurnal, and stochastic
  intraday components.

## Data

- Source: local yfinance 5-minute SPY snapshots in
  `data/intraday/SPY_5min_YYYY-MM-DD.csv`.
- Asset: SPY.
- Actual sample is determined by the local cache and recorded in
  `research_intraday_garch_vs_har_rv_rv_results.json`.
- The script does not call live yfinance, so reruns are pinned to local files.

## Method

1. Read every local SPY 5-minute CSV and compute daily 5-minute realized
   variance as the sum of squared intraday log returns.
2. Build a plain log-HAR baseline:
   `log(RV[t+1]) ~ logRV[t] + mean(logRV[t-4:t]) + mean(logRV[t-21:t])`.
3. Build an augmented proxy for multiplicative intraday structure by adding
   day-t intraday-shape features:
   `open_close_share`, `first_half_share`, `seasonal_concentration`,
   and `max_slot_share`.
4. Use expanding OOS OLS forecasts and evaluate next-day RV using Patton QLIKE
   plus the project DM helper with `h=1`.

## Lookahead Guard

All predictors are observed at day `t` after the close. The target is
`RV[t+1]`, implemented as `target_rv_next = rv.shift(-1)`.

This is not a trading strategy. There is no same-day signal multiplied by
same-day return.

## Expected Interpretation

Because the local 5-minute cache is short, this experiment is expected to be a
pilot. A directional QLIKE improvement is not sufficient for a publishable
claim unless OOS reaches at least 252 forecasts and the DM statistic clears the
project Harvey threshold of `|t| > 3`.

## Result

Verdict: `PILOT_ONLY_INSUFFICIENT_OOS`.

- Data: SPY local yfinance 5-minute snapshots, 2026-01-14 to 2026-06-22.
- Usable daily RV rows: 107.
- OOS forecasts: 43.
- HAR QLIKE: 0.4560.
- HAR + intraday-shape QLIKE: 0.6956.
- Relative change: -52.5% versus HAR, meaning the augmented proxy is worse.
- DM t-stat for seasonal minus HAR losses: 0.822, p=0.416.

Interpretation: in this short local 2026 pilot, intraday-shape features do not
improve next-day SPY realized-variance forecasts beyond plain HAR. This is a
null/pilot result, not evidence against a full multiplicative component GARCH
model in a longer clean high-frequency panel.

## Reproduce

```bash
uv run python experiments/research_intraday_garch_vs_har_rv_rv/research_intraday_garch_vs_har_rv_rv.py
```
