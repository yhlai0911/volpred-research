# K1362 — Public Option-Flow Crowd Proxy

## Motivation

This task comes from the 2026-06-21 journal-discovery backlog:

> Use free Cboe put/call ratios, aggregate option volume, and the Cboe
> index/equity split to test whether call-buying pressure predicts SPY excess
> return, VIX change, or short-vol strategy drawdown.

The motivating JFQA paper uses aggregate call order imbalance from open-buy /
open-sell option flow. K1362 deliberately tests a narrower public-data question:

**Can aggregate Cboe put/call volume ratios stand in for true ACIB-style call
order imbalance?**

## Literature Checked

- Cao, Li, Zhan, and Zhou (2026), *Betting Against the Crowd: Option Trading
  and Market Risk Premium*, JFQA forthcoming:
  <https://jfqa.org/2026/03/07/betting-against-the-crowd-option-trading-and-market-risk-premium/>
- Pan and Poteshman (2006), *The Information in Option Volume for Future Stock
  Prices*, Review of Financial Studies:
  <https://www.nber.org/papers/w10925>
- Johnson and So (2012), *The Option to Stock Volume Ratio and Future
  Returns*, Journal of Financial Economics:
  <https://ideas.repec.org/a/eee/jfinec/v106y2012i2p262-286.html>
- Hu (2014), *Does option trading convey stock price information?*, Journal of
  Financial Economics:
  <https://ideas.repec.org/a/eee/jfinec/v111y2014i3p625-645.html>
- Cboe U.S. Options market statistics and public put/call CSV archives:
  <https://www.cboe.com/markets/us/options/market-statistics/daily/>
- OCC market-data reports:
  <https://www.theocc.com/market-data/market-data-reports/volume-and-open-interest/daily-volume>

## Data

- Cboe public CSV archives:
  - `totalpcarchive.csv` + `totalpc.csv`
  - `equitypcarchive.csv` + `equitypc.csv`
  - `indexpcarchive.csv` + `indexpc.csv`
- yfinance adjusted close:
  - SPY, ^VIX, SVXY, VXX, ^IRX
- Effective test window: 2007-04-03 to 2019-10-04 after rolling z-scores.
- Panel observations: 3,275 daily rows; 3,150 rows after 252-day signal
  construction.

The free Cboe bulk CSVs used here stop on 2019-10-04. This is therefore a
pre-2020 public-proxy feasibility study, not a test of the post-2020 retail
options boom.

## Method

Signals:

1. `equity_call_share_z`: 252-day rolling z-score of equity call volume share.
2. `equity_call_demand_z`: 252-day rolling z-score of negative equity put/call
   ratio.
3. `call_crowd_gap_z`: 252-day rolling z-score of equity call share minus index
   call share.
4. `call_crowd_intensity_z`: equity call-share z plus half equity-volume z,
   re-standardized.
5. `equity_minus_index_pcr_z`: 252-day rolling z-score of equity P/C minus
   index P/C.

Targets:

- SPY excess log return over ^IRX.
- VIX close-to-close change.
- SVXY log return as an actual short-vol ETF proxy.
- Horizons: 1 trading day and 5 trading days.

Regressions are standardized OLS/HAC with lagged log VIX, lagged VIX change,
and lagged SPY return controls.

## Lookahead Policy

All predictive regressions use lagged signals:

```python
panel[f"{col}_lag1"] = panel[col].shift(1)
```

The target at date `t` is the return or VIX change beginning at `t`, while the
option-flow proxy is from `t-1`. The SVXY risk-off diagnostic uses a lagged
rolling threshold:

```python
rolling_threshold = signal_lag1.rolling(252).quantile(0.8).shift(1)
```

Random procedures use `SEED = 42`.

## Success Criteria

A strong public-proxy short-vol timing claim requires:

1. At least two expected-direction HAC cells with `|t| >= 3`.
2. At least one pass must involve SVXY / short-vol drawdown or return.

If only VIX-change diagnostics pass, the correct conclusion is weak diagnostic
evidence, not a tradable short-vol timing signal.

## Results

Verdict: `WEAK_DIAGNOSTIC_NULL_STRONG_TIMING`.

Only one expected-direction HAC regression clears the Harvey `|t| >= 3` bar:

| Test | Standardized coef | HAC t | Interpretation |
|---|---:|---:|---|
| `equity_call_demand_z_lag1 -> vix_change_5d` | +0.0849 | +3.03 | High public equity call-demand proxy is followed by a higher 5-day VIX change. |

Near misses are directionally similar but below the bar:

| Test | HAC t |
|---|---:|
| `equity_call_share_z -> vix_change_5d` | +2.95 |
| `call_crowd_intensity_z -> vix_change_5d` | +2.66 |

SPY excess return and SVXY return tests do not pass. The most negative SVXY
5-day t-stat is only -1.13.

### Top-Quintile Diagnostics

For `equity_call_demand_z`, the top-quintile public call-demand state has:

| Target | Top quintile mean | Other days mean | Diff | Welch t | Bootstrap 95% CI |
|---|---:|---:|---:|---:|---:|
| SPY excess 5d | +0.0009 | +0.0015 | -0.0006 | -0.61 | [-0.0027, +0.0014] |
| VIX change 5d | +0.4527 | -0.1029 | +0.5556 | +4.38 | [+0.2785, +0.8122] |
| SVXY return 5d | -0.0025 | +0.0032 | -0.0057 | -1.09 | [-0.0156, +0.0041] |

### Short-Vol Drawdown Diagnostics

The simple risk-off rule holds cash instead of SVXY when the lagged signal is
above its lagged rolling 252-day 80th percentile. This is diagnostic only.

| Signal | Gated Sharpe | Buy-hold Sharpe | Gated MDD | Buy-hold MDD | Tail-hit diff |
|---|---:|---:|---:|---:|---:|
| equity_call_share_z | 0.198 | 0.132 | -92.13% | -93.07% | -2.93 pp |
| equity_call_demand_z | 0.179 | 0.132 | -92.13% | -93.07% | -2.62 pp |
| call_crowd_gap_z | 0.035 | 0.132 | -92.66% | -93.07% | -2.31 pp |
| call_crowd_intensity_z | 0.019 | 0.132 | -92.13% | -93.07% | -2.31 pp |
| equity_minus_index_pcr_z | 0.594 | 0.132 | -73.21% | -93.07% | +1.41 pp |

`equity_minus_index_pcr_z` looks better as an SVXY gating diagnostic, but it
does not have the required HAC support in the predictive regressions; treat it
as a follow-up candidate, not a pass.

## Figures

- `figures/k1362_cboe_put_call_ratios.png`
- `figures/k1362_predictive_tstats.png`
- `figures/k1362_svxy_top_quintile.png`

## Limitations

- Public Cboe put/call archives are aggregate volume ratios, not customer
  open-buy minus open-sell order imbalance.
- The free bulk CSVs stop on 2019-10-04, so the most relevant 2020-2026 retail
  option crowding period is missing.
- Cboe archive notes say some post-2012 figures are preliminary reported
  volume rather than cleared OCC volume.
- SVXY is an ETF proxy; it is not a direct short-vol option strategy and its
  exposure changed after the 2018 XIV event.
- Aggregate equity/index split cannot identify retail vs institutional flow.

## Reproduce

```bash
uv run python experiments/k1362/K1362.py
```

Use `--refresh` to redownload Cboe and yfinance data.
