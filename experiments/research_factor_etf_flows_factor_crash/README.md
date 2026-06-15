# Factor ETF Flow-Pressure Crowding and Factor-Crash Risk

## Motivation

Smart-beta and factor ETFs make factor exposure easy to buy, but that also raises a crowding question: do surges into factor ETFs precede factor reversals or volatility spikes?

This experiment tests a yfinance-only proxy on four large factor ETFs:

- `MTUM`: momentum
- `QUAL`: quality
- `USMV`: minimum volatility
- `VLUE`: value

Important limitation: yfinance does not provide complete historical AUM or shares outstanding for this ETF set. Only `QUAL` returned sparse shares data in a quick API check; `MTUM`, `USMV`, and `VLUE` did not. Therefore this experiment does **not** claim to measure true ETF flows.

## Literature / Source Motivation

- "Smart beta, smarter flows" (Journal of Empirical Finance, 2025): smart-beta ETF trading can affect investor sensitivity to factor alphas. URL: https://ideas.repec.org/a/eee/empfin/v81y2025ics0927539825000027.html
- "Competition for Attention in the ETF Space" (Review of Financial Studies): ETF product demand and specialized ETF underperformance are linked to attention/product design. URL: https://academic.oup.com/rfs/advance-article/doi/10.1093/rfs/hhac048/6655702
- "The Smart Beta Mirage" (2025): discusses smart-beta ETF listing/performance patterns and potential crowding/diminishing-return explanations. URL: https://ira.lib.polyu.edu.hk/bitstream/10397/102732/1/Huang_Smart_Beta_Mirage.pdf
- iShares ETF and ETP Market Trends Q1 2026: recent ETF flow context. URL: https://www.ishares.com/us/insights/inside-the-market/2026-etf-market-trends-and-flows

## Data

- Source: yfinance daily adjusted close and volume.
- Sample request: 2013-01-01 to 2026-06-15; actual last date 2026-06-12.
- Factor ETFs: `MTUM`, `QUAL`, `USMV`, `VLUE`.
- Controls: `SPY`, `^VIX`.
- OOS start: 2020-01-02.

## Proxy Construction

For each factor ETF:

```text
signed dollar volume = sign(ETF excess return vs SPY) * Close * Volume
pressure_30 = 30d sum(signed dollar volume) / 252d average dollar volume
```

Each ETF's pressure series is rolling z-scored, then the four z-scores are averaged and z-scored again to form the factor ETF crowding proxy.

This is a **flow-pressure proxy**, not AUM flow. It mixes investor demand, liquidity demand, and price impact.

## Method

Primary tests:

- Outcome 1, reversal: does high crowding predict lower future equal-weight factor ETF excess return vs SPY?
- Outcome 2, vol spike: does high crowding predict higher future realized variance of the equal-weight factor ETF basket?
- Horizons: 5, 21, 63 trading days.

Controls:

- lagged 21d factor excess return
- lagged 21d and 63d factor basket RV
- lagged 21d and 63d SPY RV
- lagged VIX level and 5d VIX change

Lookahead controls:

- `crowding_z_l1 = crowding_z.shift(1)`
- all controls also enter as `.shift(1)`
- forward targets start at row `t`, so row `t` uses information through `t-1`

Statistical discipline:

- 2 outcomes x 3 horizons = 6 primary tests.
- Bonferroni alpha = 0.00833.
- OLS with Newey-West HAC, maxlags `horizon + 5`.
- Event-study bootstrap uses seed 42 and 1000 reps.

## Results

Verdict: `NULL`.

Primary OOS regression tests:

| Outcome | Horizon | n | Coef | HAC t | p-value | Direction supportive | Bonferroni pass |
|---|---:|---:|---:|---:|---:|---|---|
| reversal | 5 | 1607 | +0.000005 | +0.02 | 0.986 | no | no |
| reversal | 21 | 1607 | -0.000677 | -0.71 | 0.477 | yes | no |
| reversal | 63 | 1607 | -0.001545 | -0.69 | 0.493 | yes | no |
| vol spike | 5 | 1607 | -0.003753 | -1.28 | 0.200 | no | no |
| vol spike | 21 | 1607 | -0.006837 | -1.53 | 0.126 | no | no |
| vol spike | 63 | 1607 | -0.005235 | -1.14 | 0.253 | no | no |

Event-study diagnostic:

- 19 top-decile crowding events after 21d cooldown.
- Future factor excess returns are not significantly lower after events.
- Future factor-basket variance is not significantly higher after events; point estimates are negative at all horizons.

## Interpretation

The signed dollar-volume proxy does not support the hypothesis that factor ETF crowding peaks predict factor crashes. The only direction-supportive cells are 21d/63d reversal, but their HAC p-values are about 0.48/0.49. The vol-spike hypothesis points the wrong way in all three horizons.

Conclusion strength is limited by the proxy. This is best recorded as: with free yfinance data, a volume-based factor ETF pressure proxy does not produce a robust crowding crash signal. A true AUM/share-creation dataset would be required before making stronger claims about ETF flows.

## Caveats

- Not true ETF flow or AUM data.
- Signed dollar volume can reflect market-maker inventory, liquidity demand, and price impact.
- Four ETFs only; no sector/factor mutual fund flow data.
- Regression study, not a tradable strategy backtest.
- Factor ETF histories begin in the 2010s, limiting pre-2020 training context.

## Artifacts

- `research_factor_etf_flows_factor_crash.py`
- `research_factor_etf_flows_factor_crash_results.json`
- `fig_primary_hac_tests.png`
- `fig_crowding_proxy_events.png`
