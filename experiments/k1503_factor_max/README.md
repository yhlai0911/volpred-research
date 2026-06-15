# K1503 — Factor-MAX and next-month factor ETF returns / volatility

**Final verdict: MIXED.** Prior-month factor-MAX does **not** support the
next-month underperformance hypothesis, but it strongly predicts higher
next-month realized volatility in this small factor ETF universe.

## Research question

The backlog question was:

> Factor-MAX: use monthly MAX from factor ETFs (`MTUM`, `QUAL`, `VLUE`,
> `USMV`, `SIZE`) to test whether high factor-MAX predicts lower next-month
> factor returns or higher volatility.

This experiment is a yfinance-only pilot. It tests ETF-level factor-MAX, not
the original stock-level MAX anomaly.

## Literature checked before implementation

- Wang and Zeng (2026 working paper), *Factor MAX and Predictable Factor
  Returns*: motivates testing whether extreme factor returns forecast future
  factor returns.
- Bali, Cakici, and Whitelaw (2011), *Maxing out: Stocks as lotteries and the
  cross-section of expected returns*, Journal of Financial Economics: defines
  the stock-level MAX effect.
- Bali, Brown, Murray, and Tang (2017), *A lottery-demand-based explanation of
  the beta anomaly*, Journal of Financial and Quantitative Analysis: connects
  lottery demand / MAX-style measures to broader asset-pricing anomalies.

## Relation to prior K findings

- `K89`: factor tilts did not improve the 50/50 VT framework.
- `K566`: factor timing plus VT was null; factor ETF correlations with SPY
  were high.
- `K876`: MTUM crash risk is partly distinct from SPY crashes, but VIX overlays
  did not pass.
- `K1446`: USMV is lower-risk than MTUM / QUAL / VLUE / SPY on descriptive
  risk metrics.

K1503 is different: it asks whether prior-month factor ETF MAX predicts
next-month cross-sectional factor ETF returns or volatility.

## Data

- Source: yfinance adjusted close via `yf.download(auto_adjust=True)`.
- Factor ETFs: `MTUM`, `QUAL`, `VLUE`, `USMV`, `SIZE`.
- Benchmark: `SPY`.
- Price span downloaded: earliest `SPY` 2010-01-04; factor ETFs begin
  2011-10-20 to 2013-07-18 depending on ticker; last price 2026-06-15.
- Analysis sample uses complete monthly outcomes only: 2013-06-30 to
  2026-05-31.
- Final panel: 777 ETF-month rows, 156 months, 5 factor ETFs.

## Timing and lookahead controls

The experiment uses prior-month signals only:

```python
panel[f"{col}_lag1"] = panel.groupby("ticker")[col].shift(1)
```

So month `t-1` daily returns form MAX, and month `t` return / volatility are
the outcomes. The partial 2026-06 month is excluded by the
`last_complete_month_end_rule = 2026-05-31`.

## Method

Main signal:

- `max_daily_return_lag1`: maximum daily simple return during the prior
  calendar month.

Main outcomes:

- `monthly_excess_vs_spy`: current-month factor ETF log return minus current
  month SPY log return.
- `monthly_rv_ann`: current-month realized volatility from daily log returns,
  annualized.

Tests:

- Monthly sort: low prior-MAX ETF(s) minus high prior-MAX ETF(s) next-month
  excess return.
- Monthly sort: high prior-MAX ETF(s) minus low prior-MAX ETF(s) next-month
  realized volatility.
- Monthly Fama-MacBeth cross-sectional beta of outcome on prior-MAX z-score.
- Pooled OLS with ticker and month fixed effects, clustered by month.

Threshold: internal Harvey-style `|t| > 3` for the 8 main tests. Sort spread
confidence intervals use 5,000 bootstrap resamples with seed 42.

## Results

### Return hypothesis: NULL

Expected sign: high MAX should underperform, so low-MAX minus high-MAX should
be positive.

| Test | Estimate | t-stat | Harvey pass |
|---|---:|---:|---|
| Low1 minus High1 excess return, annualized | -3.06% | -1.01 | No |
| Low2 minus High2 excess return, annualized | -0.75% | -0.31 | No |
| Fama-MacBeth beta on MAX z-score | +0.00059 | +0.63 | No |
| Pooled FE coefficient on MAX z-score | -0.00012 | -0.11 | No |

There is no support for a factor ETF underperformance anomaly. The sort
spreads are directionally opposite or near zero, and none pass the Harvey
threshold.

### Volatility hypothesis: PASS

Expected sign: high MAX should predict higher next-month realized volatility.

| Test | Estimate | t-stat | Harvey pass |
|---|---:|---:|---|
| High1 minus Low1 next-month RV | +5.21 pp | +8.70 | Yes |
| High2 minus Low2 next-month RV | +3.72 pp | +9.94 | Yes |
| Fama-MacBeth beta on MAX z-score | +1.83 pp | +9.47 | Yes |
| Pooled FE coefficient on MAX z-score | +1.09 pp | +7.67 | Yes |

This is a strong volatility-persistence result: factor ETFs with a large
prior-month lottery-like daily jump tend to remain higher-volatility in the
next month.

## Interpretation

K1503 should not be cited as evidence that ETF-level Factor-MAX predicts lower
future factor returns. It does not.

The usable finding is narrower: prior-month MAX is a strong cross-sectional
state variable for next-month realized volatility among these factor ETFs.
That is consistent with volatility clustering and with K1446's factor ETF risk
diagnostics, but it is not the same claim as the original stock-level MAX
return anomaly.

## Limitations

- Only five liquid factor ETFs are used.
- ETF-level MAX may mix underlying factor lottery demand with ETF trading
  microstructure.
- The sample begins after the newest ETF has enough observations, so it cannot
  test pre-2013 factor cycles.
- No options, stock-level holdings, or borrow-fee data are used.

## Files

- `k1503.py` — reproducible experiment script.
- `k1503_results.json` — all machine-readable results.
- `data/prices_yfinance.csv` — cached yfinance adjusted close.
- `data/monthly_factor_max_panel.csv` — monthly ETF panel.
- `data/monthly_sort_spreads.csv` — high/low MAX monthly spreads.
- `figures/k1503_factor_max_by_ticker.png`
- `figures/k1503_sort_spread_distributions.png`
- `figures/k1503_rolling_sort_spreads.png`
- `codex_review.md` — source-level review.

Reproduce:

```bash
uv run python experiments/k1503_factor_max/k1503.py
```
