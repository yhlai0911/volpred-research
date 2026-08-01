# K1743 — TSM ADR vs 2330.TW price discovery

## Motivation

TSMC trades in Taipei as 2330.TW and in New York as the TSM ADR (five Taiwan
shares per ADR).  Their non-overlapping trading hours make the pair a useful
laboratory for asking where price and volatility discovery occurs.  The
2024–2026 ADR-premium narrative is treated as motivation, not as a result to
be assumed.

## Method

The script downloads unadjusted daily OHLC for `TSM`, `2330.TW`, and `TWD=X`
from Yahoo Finance.  It constructs the log ADR premium
`log(TSM * TWD-per-USD / (5 * 2330.TW))`, reports annual premium summaries,
and evaluates both chronological directions:

- Taipei close on calendar day t → New York close on t (Taipei is already
  closed before New York opens).
- New York close on t → the next **common-date** Taipei observation.  This
  signal is explicitly implemented with `signal.shift(1)` on the common-date
  panel. Around exchange-specific holidays the target may span more than one
  local Taiwan session, so this is not a literal next-session design.

For each direction, a fixed 2010–2020 training sample estimates a baseline
absolute-return model (own lagged absolute return) and an augmented model
(cross-market return plus lagged premium change).  The untouched 2021 onward
sample is scored using MSE and proxy-robust QLIKE on squared returns.  Because
the models are nested, Clark–West supplies the predictive-content inference.
This is a daily-close
lead–lag design, not an information-share estimator and not an intraday
causal claim.

## Lookahead policy

All fitted coefficients are frozen before the OOS period.  Own-market and
premium predictors are lagged.  The US-to-Taiwan path contains the literal
`signal.shift(1)` required by the experiment gate.  Same-calendar Taipei data
may predict New York only because the exchange closes earlier; the results
record this timing assumption.  No revised macroeconomic series are used.

## Data-quality policy

The downloaded `TWD=X` series contained two impossible isolated observations:
1.8015 TWD/USD on 2011-10-25 and 3.67 on 2014-12-31, versus an otherwise roughly
28--33 series. They created mechanical ADR-premium prints near -94% and -88%.
The runtime now records and drops FX observations outside the deliberately broad
10--100 TWD/USD validity band without imputation. If more than 1% of the common
panel violates that band, the run fails closed instead of silently cleaning a
materially corrupted feed.

## Success criteria

The directional price-discovery claim is supported only if the augmented
model improves OOS QLIKE and MSE and its one-sided Clark–West p-value is below
5%.
Anything weaker is recorded as null/mixed.  Premium claims must be based on
the downloaded observations and include annual coverage counts.  `seed=42`
is fixed even though the current estimator is deterministic.

## Reproduction

```bash
uv run python experiments/K1743/K1743.py
```

The byte-traceable output is `K1743_results.json` in this directory.

## Result

The rerun uses 3,912 common-date observations from 2010-01-04 through
2026-07-31 after dropping the two recorded FX glitches. The untouched 2021+
OOS window has 1,305 observations in each direction.

Neither direction meets the predeclared success rule. Taipei-to-New-York makes
both OOS losses worse (MSE -0.0156% improvement; QLIKE -0.1243%) and has
one-sided Clark--West p=0.4093. New-York-to-Taipei slightly improves MSE by
0.0657% but worsens QLIKE by 0.2380%, with Clark--West p=0.1799. The experiment
therefore reports `NULL`: this daily common-date design does not establish
incremental directional volatility-prediction content.

The descriptive premium remains elevated in the recent sample after the FX
repair (annual mean 16.21% in 2024, 22.46% in 2025, and 16.43% through
2026-07-31), but that is a descriptive observation, not evidence about causal
price discovery.
