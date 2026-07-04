# research_magnet_effect_2015_7_10_vol

## Verdict

`CONTINUATION_WEAKENED_DAILY_PROXY_NO_VOL_BREAK`

TWSE daily OHLC data show that stocks near the old 7% price-limit boundary had a
clear next-day volatility premium, but the 2015-06-01 widening from 7% to 10%
does not produce a Harvey-pass break in that next-day absolute-return premium.
The cleaner fixed old-7% boundary test instead finds a strong weakening of
side-adjusted next-day continuation after the old boundary stopped binding.

This is a daily proxy result. It does not prove an intraday magnet effect,
because true magnet behavior requires order-book or trade-level approach-speed
data before the limit is hit.

## Data

- Source: official TWSE `exchangeReport/MI_INDEX` daily CSV, `type=ALLBUT0999`.
- Period: 2014-01-02 to 2016-12-30.
- Change date: 2015-06-01, when the TWSE daily price fluctuation limit moved
  from 7% to 10%.
- Sample filter: 4-digit listed common stocks only; ETFs, warrants, preferred
  shares, and most special products are excluded.
- Fetched sample: 783 weekday candidates, 726 trading days, 57 no-data dates,
  0 fetch failures.
- Analysis sample: 615,567 valid stock-days after requiring previous close,
  next close, non-X comparison status, and a reasonable next-trading-day gap.

## Method

Two event definitions are used:

- Applicable-limit event: high/low touches the applicable daily limit within
  0.25 percentage points, or close is within 1 percentage point of the
  applicable daily limit. This means 7% before 2015-06-01 and 10% after.
- Fixed old-7% event: the same rule, but fixed at the old 7% boundary in both
  pre- and post-widening periods. This is the preferred natural-experiment
  comparison because post-widening observations that pass 7% are no longer
  necessarily at the binding exchange limit.

Targets are next-trading-day close-to-close absolute return and side-adjusted
continuation. The event signal is measured at day t and the return target is at
t+1, so the design avoids same-day lookahead.

Inference uses daily HAC regressions for event-minus-control daily averages and
date-clustered cross-sectional regressions. The reporting gate uses the local
Harvey-style `|t| > 3` standard.

## Results

| Test | Estimate | t-stat | Interpretation |
| --- | ---: | ---: | --- |
| Applicable-limit daily abs-return premium, post minus pre | +1.094 pp | 5.64 | Mechanically contaminated because post events are selected at +/-10% rather than +/-7%. |
| Fixed old-7% daily abs-return premium, post minus pre | +0.244 pp | 1.23 | No Harvey-pass widening break in next-day volatility premium. |
| Fixed old-7% cross-section event premium, pre period | +0.429 pp | 3.86 | Near-old-limit stocks have a next-day volatility premium before widening. |
| Fixed old-7% cross-section event-post interaction | +1.190 pp | 0.85 | No reliable widening break in the cross-sectional premium. |
| Fixed old-7% side-adjusted continuation, post minus pre | -0.859 pp | -4.20 | Strong daily-proxy evidence that continuation weakened after the old 7% boundary stopped binding. |

Event counts:

- Applicable-limit events: 18,759 valid stock-days.
- Fixed old-7% events: 28,672 valid stock-days.
- Mean applicable event rate: 3.59% pre-widening, 2.60% post-widening.

## Interpretation

The cleanest result is not "2015 increased next-day volatility after limit
events." That claim fails under the fixed old-7% robustness test. The supported
claim is narrower: before the widening, old-boundary pressure days had
next-day volatility and continuation behavior consistent with a binding-limit
constraint; after the old boundary stopped binding, side-adjusted continuation
fell sharply.

This is consistent with a relaxation of delayed continuation around the former
limit boundary, but it remains a daily OHLC proxy. It should not be written up
as definitive intraday magnet-effect evidence without trade-level data.

## Related Work

- TWSE trading mechanism page, including the 2015-06-01 10% limit change:
  https://www.twse.com.tw/en/products/system/trading.html
- Cho, Russell, Tiao, and Tsay (2003), "The magnet effect of price limits":
  https://ideas.repec.org/a/eee/empfin/v10y2003i1-2p133-168.html
- Hsieh, Kim, and Yang (2009), "The Magnet Effect of Price Limits: A Logit Approach":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1494185
- SSRN 3942000, "The Magnet Effect Under Relaxed Daily Price Limits":
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3942000

Internal related null/limited findings checked before execution:

- K790v2 and K790: Taiwan price-limit related evidence is sparse and sensitive.
- K508: Taiwan price-limit institutional angle did not previously yield a
  strong publishable signal.

## Artifacts

- `research_magnet_effect_2015_7_10_vol.py`: full reproducible script.
- `research_magnet_effect_2015_7_10_vol_results.json`: structured results.
- `data/daily_event_summary.csv`: applicable-limit daily summary.
- `data/event_rows.csv`: applicable-limit event rows.
- `data/old7_daily_event_summary.csv`: fixed old-7% daily summary.
- `data/old7_event_rows.csv`: fixed old-7% event rows.
- `magnet_effect_daily_proxy.png`: event-rate and next-day premium figure.

Reproduce:

```bash
uv run python experiments/research_magnet_effect_2015_7_10_vol/research_magnet_effect_2015_7_10_vol.py
```
