# K1354 — Monthly OPEX Gamma-Cliff Event Study

## Motivation

This experiment tests whether monthly option expiration creates a daily
realized-volatility pattern consistent with the practitioner "gamma cliff"
story: lower volatility in the three trading days before OPEX, followed by a
release after expiration.

The question is deliberately narrower than prior 0DTE work. K1354 studies
monthly expiration timing with daily SPY OHLC data, not intraday 0DTE volume
share or option-chain gamma exposure.

## Prior Evidence And Dedup Check

- `research_program.md` line 634 defines this as a new monthly OPEX daily-RV
  event study, orthogonal to the existing 0DTE intraday-share axis.
- Knowledge search found option-expiration/pinning context but no completed
  K experiment for monthly OPEX pre/post daily range-variance windows.
- Error-log constraints applied: explicit lookahead handling, no same-day
  signal trading claim, no overclaiming mechanism from proxy data, and code
  review before knowledge promotion.

Key literature / sources:

1. Ni, Pearson, and Poteshman (2005), *Journal of Financial Economics*,
   "Stock price clustering on option expiration dates".
2. Avellaneda and Lipkin (2003), *Quantitative Finance*, "A market-induced
   mechanism for stock pinning".
3. Feinstein and Goetzmann (1988), Federal Reserve Bank of Atlanta
   *Economic Review*, "The effect of the triple witching hour on stock market
   volatility".
4. Stoll and Whaley (1991), *Financial Analysts Journal*, "Expiration-day
   effects: what has changed?"

## Data

- Source: yfinance
- Ticker: SPY
- Requested period: 1993-01-29 to 2026-06-22
- Usable sample: 1993-02-01 to 2026-06-18
- Trading days after return/range filters: 8,403
- Monthly OPEX calendar events: 401
- Evaluable events after requiring +/-5 trading days and same-month controls:
  399
- Quad-witching events: 132
- Non-quad monthly OPEX events: 267

The script stores the yfinance adjusted OHLCV snapshot at
`data/SPY_ohlcv_auto_adjusted.csv`.

## Method

Monthly option expiration is proxied as the third Friday of each month. If the
third Friday is not an SPY trading day, the previous SPY trading day in the
same month is used. March, June, September, and December are tagged as
quad-witching months.

Primary realized-volatility proxy:

```text
Parkinson range variance = log(High / Low)^2 / (4 log 2)
```

Unit of inference is the event month. For each OPEX event:

- `pre3`: trading days -3, -2, -1
- `expiration`: trading day 0
- `post3`: trading days +1, +2, +3
- `post5`: trading days +1 through +5
- control: same-month trading days excluding offsets -5 through +5

Formal tests use paired event-level differences, not daily pooled rows:

- paired t-test
- Wilcoxon signed-rank test
- 5,000-rep paired bootstrap with seed 42
- quad vs non-quad Welch/bootstrap comparison

## Lookahead Policy

OPEX dates are known calendar information. The event study classification uses
calendar dates only, not realized returns. For any forecasting-style usage, the
script explicitly creates:

```python
df["opex_pre3_calendar_signal_lag1"] = pre_window.astype(int).shift(1)
```

No trading strategy return is computed from same-day signals.

## Success Criteria

Primary gamma-cliff confirmation requires both gates:

1. `pre3_minus_control < 0` with t-stat `< -3.0`, two-sided t-test p below
   Bonferroni alpha `0.0125`, bootstrap 95% CI entirely below zero, and
   one-sided bootstrap p below `0.0125`.
2. `post3_minus_pre3 > 0` with t-stat `> +3.0`, two-sided t-test p below
   Bonferroni alpha `0.0125`, bootstrap 95% CI entirely above zero, and
   one-sided bootstrap p below `0.0125`.

Quad-witching strength is secondary and cannot by itself make the experiment a
PASS.

## Results

Verdict: **NULL**.

Primary results:

| Test | Mean Difference | t-stat | Bootstrap 95% CI | One-sided p | Interpretation |
|---|---:|---:|---:|---:|---|
| pre3 - control | +0.00000209 | +0.31 | [-0.00001100, +0.00001587] | 0.5988 for suppression | No pre-OPEX suppression |
| post3 - pre3 | -0.00000392 | -0.51 | [-0.00001912, +0.00001074] | 0.6994 for release | No post-OPEX release |
| expiration - control | -0.00001513 | -2.22 | [-0.00002835, -0.00000175] | 0.0144 for lower expiration-day RV | Lower but misses stricter Bonferroni/Harvey gate |
| quad post3-pre3 minus non-quad | -0.00001870 | -1.23 | [-0.00004924, +0.00001004] | 0.8966 for stronger quad release | No stronger quad release |

Descriptive ratios versus same-month control:

- pre3: 1.159x
- expiration day: 0.944x
- post3: 1.203x

The lower expiration-day range variance is only unadjusted suggestive and does
not pass the stricter Harvey/Bonferroni gate. It also does not support the
requested "pre-72-hour suppression then post-expiration release" mechanism.

## Limitations

- SPY daily OHLC cannot observe dealer gamma exposure, open interest by strike,
  or intraday hedge rebalancing flow.
- The range-variance proxy captures daily high-low movement, not option-implied
  volatility.
- A true mechanism test would need historical option-chain open interest,
  dealer positioning assumptions, and intraday SPX/SPY data.
- NULL here means the free daily-OHLC specification does not support the
  gamma-cliff pattern; it does not falsify options-market gamma mechanics.

## Artifacts

- `K1354.py`
- `K1354_results.json`
- `data/K1354_event_panel.csv`
- `data/K1354_offset_panel.csv`
- `data/SPY_ohlcv_auto_adjusted.csv`
- `figures/K1354_opex_offset_profile.png`
- `figures/K1354_event_differences.png`
