# K1346 — Lottery-stock basket vol-of-vol and crisis amplification

**Verdict: NULL.** A yfinance-only lottery-stock proxy basket does not provide
corrected evidence that lottery-stock vol-of-vol is a robust market-tail early
warning signal.

## Motivation

The backlog question asked whether a stock basket with lottery-like features
low price, high idiosyncratic volatility, and high recent MAX return has
realized-volatility / volatility-of-volatility amplification in risk-off
regimes, and whether that basket leads broad-market tail volatility.

This differs from K1503. K1503 tested factor ETF MAX and found a strong
next-month volatility state signal. K1346 moves to individual stocks and asks
whether that risk is systemic enough to lead SPY / IWM tail volatility.

## Literature checked

- Bali, Cakici, and Whitelaw (2011), *Maxing out: Stocks as lotteries and the
  cross-section of expected returns*, Journal of Financial Economics. This is
  the canonical stock-level MAX / lottery-stock reference:
  <https://econpapers.repec.org/article/eeejfinec/v_3a99_3ay_3a2011_3ai_3a2_3ap_3a427-446.htm>
- Zhang, Kappou, and Urquhart (2026), *Conditional demand for lottery-type
  stocks: Information spillovers and asset prices comovement*. This motivates
  checking whether lottery-stock behavior changes around macro/risk-off
  information states:
  <https://centaur.reading.ac.uk/128903/13/1-s2.0-S1057521926000724-main.pdf>
- Wang and Zeng (2026), *Factor MAX and Predictable Factor Returns*. This
  motivates the recent Factor-MAX extension and distinguishes factor-level MAX
  from stock-level lottery events:
  <https://scholars.hkbu.edu.hk/en/publications/factor-max-and-predictable-factor-returns/>
- Lee (2023), *The role of idiosyncratic jumps in stock markets*. This
  motivates treating positive idiosyncratic jumps as related to future skewness
  and lottery-like payoffs:
  <https://www.scheller.gatech.edu/directory/research/finance/lee/pdf/idiosyncraticlee_2023_feb.pdf>

## Data

- Source: yfinance adjusted close, `auto_adjust=True`.
- Requested window: 2018-01-01 to 2026-06-17 exclusive.
- Final complete-month sample: 2018-05-31 to 2026-05-31.
- Monthly observations: 97.
- Risk-off months: 23.
- Requested current-name proxy universe: 75 tickers.
- Valid yfinance universe after history filter: 74 tickers.

The universe is a current liquid retail/speculative proxy basket. It is
survivorship-biased and does **not** replace CRSP. The experiment is a public
data pilot, not a production stock-level anomaly test.

## Lookahead policy

The code computes monthly features first, then creates lagged forecasting
features with:

```python
panel[f"{col}_lag1"] = panel.groupby("ticker")[col].shift(1)
```

So month `t` basket membership uses month `t-1` low-price, idiosyncratic-vol,
and MAX information. Market lead tests use `basket_vov_lag1` or
`basket_rv_ann_lag1` to explain month `t` SPY / IWM volatility outcomes.

## Method

For each stock-month:

- Low-price component: negative cross-sectional z-score of lagged log price.
- Idio-vol component: z-score of lagged 63-day CAPM residual volatility.
- MAX component: z-score of lagged 21-day maximum daily return.
- Lottery score: mean of the three z-scores.

Each month selects the top 20% of valid stocks, with at least 5 names. The
median selected basket has:

| Diagnostic | Value |
|---|---:|
| Selected names | 15 |
| Lagged price | 3.97 |
| Lagged idio vol, annualized | 106.4% |
| Lagged 21d MAX return | 18.0% |

Risk-off is descriptive: current month SPY log return <= -5% or average VIX >=
25. Predictive tests are separate lagged regressions.

## Results

### Risk-off amplification

The basket's own RV and VoV are higher in risk-off months, but not enough to
pass the project bar:

| Metric | Risk-off mean | Normal mean | Diff | t | Bootstrap P(diff>0) | Harvey |
|---|---:|---:|---:|---:|---:|---|
| Basket RV | 0.697 | 0.618 | +0.079 | 1.82 | 0.964 | No |
| Basket VoV | 0.217 | 0.184 | +0.034 | 1.26 | 0.904 | No |

More importantly, relative to broad equity benchmarks the amplification is
negative:

| Metric | Risk-off mean | Normal mean | Diff | t | Bootstrap P(diff>0) |
|---|---:|---:|---:|---:|---:|
| Basket minus IWM RV | 0.364 | 0.433 | -0.068 | -2.02 | 0.021 |
| Basket minus IWM VoV | 0.117 | 0.126 | -0.009 | -0.35 | 0.353 |
| Basket minus SPY RV | 0.417 | 0.495 | -0.078 | -2.16 | 0.013 |
| Basket minus SPY VoV | 0.125 | 0.144 | -0.019 | -0.72 | 0.232 |

Interpretation: the lottery basket is high-volatility in absolute terms, but
SPY/IWM volatility expands more in risk-off months. This does not support a
unique lottery-stock crisis amplification channel.

### Lead tests

All lead regressions fail. Lagged lottery basket VoV has the wrong sign for
SPY/IWM next-month RV and tail-excess outcomes:

| Lead test | Coef | HAC t | Bonferroni p | Pass |
|---|---:|---:|---:|---|
| `basket_vov_lag1 -> spy_rv_ann` | -0.105 | -1.12 | 1.000 | No |
| `basket_vov_lag1 -> iwm_rv_ann` | -0.084 | -0.93 | 1.000 | No |
| `basket_vov_lag1 -> spy tail excess` | -0.016 | -0.74 | 1.000 | No |
| `basket_vov_lag1 -> iwm tail excess` | -0.021 | -0.36 | 1.000 | No |
| `basket_rv_lag1 -> spy_rv_ann` | -0.035 | -0.59 | 1.000 | No |
| `basket_rv_lag1 -> iwm_rv_ann` | +0.009 | +0.22 | 1.000 | No |

## Conclusion

K1346 is a NULL result for the proposed early-warning use case.

The absolute basket risk is high and mildly higher in risk-off months, but this
is not a corrected, benchmark-relative amplification effect. The lead tests do
not support using lottery-stock basket VoV as a SPY/IWM tail-vol warning signal.

## Limitations

- Current-name universe creates survivorship and selection bias.
- Adjusted-close yfinance data misses delisted bankrupt lottery stocks.
- Monthly VoV is based on 5-day rolling close-to-close volatility, not intraday
  or option-implied VoV.
- Risk-off amplification is descriptive; causal spillover is not identified.
- No trading strategy or transaction-cost claim is made.

## Files

- `k1346.py` — full reproducible script.
- `k1346_results.json` — machine-readable results.
- `data/close_prices_yfinance.csv` — yfinance close cache.
- `data/monthly_stock_panel.csv` — stock-month feature/outcome panel.
- `data/monthly_lottery_basket.csv` — basket-month outcomes.
- `data/monthly_lottery_selections.csv` — selected tickers by month.
- `figures/k1346_riskoff_amplification.png`
- `figures/k1346_lead_tstats.png`
- `codex_review.md` — source-level review.

Reproduce:

```bash
uv run python experiments/k1346/k1346.py
```
