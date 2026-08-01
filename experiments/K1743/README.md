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
- New York close on t → the next available Taipei close.  This signal is
  explicitly implemented with `signal.shift(1)` on the common-date panel.

For each direction, a fixed 2010–2020 training sample estimates a baseline
absolute-return model (own lagged absolute return) and an augmented model
(cross-market return plus lagged premium change).  The untouched 2021 onward
sample is scored using MSE and proxy-robust QLIKE on squared returns.  Because
the models are nested, Clark–West supplies the primary predictive-content
inference; the canonical repository DM statistic is diagnostic-only.  This is a daily-close
lead–lag design, not an information-share estimator and not an intraday
causal claim.

## Lookahead policy

All fitted coefficients are frozen before the OOS period.  Own-market and
premium predictors are lagged.  The US-to-Taiwan path contains the literal
`signal.shift(1)` required by the experiment gate.  Same-calendar Taipei data
may predict New York only because the exchange closes earlier; the results
record this timing assumption.  No revised macroeconomic series are used.

## Success criteria

The directional price-discovery claim is supported only if the augmented
model improves OOS QLIKE and MSE and its one-sided Clark–West p-value is below
5%.  The diagnostic DM statistic never feeds the verdict.
Anything weaker is recorded as null/mixed.  Premium claims must be based on
the downloaded observations and include annual coverage counts.  `seed=42`
is fixed even though the current estimator is deterministic.

## Reproduction

```bash
uv run python experiments/K1743/K1743.py
```

The byte-traceable output is `K1743_results.json` in this directory.
