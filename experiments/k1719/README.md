# K1719 — ASIA-5 conservative daily volatility spillover ladder

## Motivation

K1719 asks whether volatility information travels from the United States to
Japan, then Taiwan, and finally Southeast Asia.  The classic literature finds
international return/volatility transmission, but daily Yahoo bars cannot
identify a clean within-day Tokyo → Taipei → Southeast-Asia causal sequence:
Taiwan closes before Tokyo, while Southeast-Asian sessions overlap Taiwan.
Accordingly, this experiment tests the narrower and defensible question:
**does the previous local trading day's upstream information improve a target
market's next daily variance forecast beyond its own history?**

This extends the earlier SPY → Taiwan direction to six Asian targets while
retaining a strict, auditable information set.  It does not claim an intraday
mechanism.

## Prior literature

1. Engle, Ito, and Lin (1990), “Meteor Showers or Heat Waves?”,
   *Econometrica* 58, 525–542, DOI: 10.2307/2938189.  Session-level FX
   volatility transmission motivates the information-flow interpretation.
2. Hamao, Masulis, and Ng (1990), “Correlations in Price Changes and
   Volatility across International Stock Markets”, *Review of Financial
   Studies* 3, 281–307, DOI: 10.1093/rfs/3.2.281.
3. Lin, Engle, and Ito (1994), “Do Bulls and Bears Move Across Borders?”,
   *Review of Financial Studies* 7, 507–538, DOI: 10.1093/rfs/7.3.507.
4. Diebold and Yilmaz (2009), “Measuring Financial Asset Return and
   Volatility Spillovers”, *Economic Journal* 119, 158–171,
   DOI: 10.1111/j.1468-0297.2008.02208.x.  We do not implement its FEVD
   connectedness statistic here because K1719's primary question is nested
   OOS predictive content and because the original paper has a normalization
   erratum.

## Data and reproducibility

- Source: Yahoo Finance via `yfinance` 1.2.0.
- Fixed download request: 2005-01-01 through 2025-12-31 (end-exclusive).
- Instruments: SPY, ^VIX, ^N225, ^TWII, ^STI, ^JKSE, ^KLSE, ^SET.BK.
- Adjusted daily OHLC prices (`auto_adjust=True`); this experiment uses Close.
- `k1719_source_snapshot.csv` is a frozen, sorted wide close-price snapshot.
  Its SHA-256 is recorded in `k1719_results.json`.
- Random seed: 42.  The estimation itself is deterministic.

Daily squared log return is a noisy proxy for close-to-close variance.  It is
appropriate for comparing the same model class on the same target, but it is
not intraday realized variance.

## Method

For every target, the baseline rolling model predicts log variance from its
own lag-1 variance and trailing 5/22-session variance averages.  The ladder
model adds lagged upstream information:

- Japan: SPY variance and VIX level.
- Taiwan: SPY, VIX, and Japan variance.
- Singapore, Indonesia, Malaysia, Thailand: SPY, VIX, Japan, and Taiwan.

All predictor series are created with an explicit `signal.shift(1)` before the
cross-market inner join.  Each forecast origin uses at most the previous 756
common observations and is fit only on rows strictly before the forecast row.
Forecasts are clipped to the training sample's 1st–99th percentile variance
range to prevent exponentiation from producing numerical outliers.

Primary economic loss is Patton-direction QLIKE (`actual / predicted`) on the
same squared-return proxy.  Because the ladder nests the baseline, raw DM is
not valid primary inference: it is reported only as a diagnostic.  Formal
incremental-predictability inference uses the repository's canonical
Clark–West nested test on the fitted log-variance target.  We also report
Spearman correlation and MSE.  Harvey-strength evidence requires `|t| > 3`;
ordinary p-values are descriptive only.

## Lookahead policy

- `signal = signal.shift(1)` is literal in `k1719.py`.
- The common-date join happens only after every signal has been lagged within
  its own market series.
- At forecast row `i`, the rolling fit ends at `i-1`; the target at `i` is
  never in the training window.
- We deliberately do not use same-date Japan returns for Taiwan or same-date
  Taiwan returns for Southeast Asia, even where close times might suggest a
  partial information advantage.  Daily bars cannot separate overlapping
  session components.

## Pre-registered success criteria

The ladder is considered supported only if:

1. QLIKE improves for at least 4 of 6 targets; and
2. at least 2 target-level Clark–West comparisons pass `|t| > 3`; and
3. the date-aggregated Southeast-Asia panel Clark–West statistic also passes
   `|t| > 3`.

Otherwise the result is MIXED or NULL and must be reported as such.  A positive
in-sample coefficient or an unadjusted p-value is not sufficient.

## Run

```bash
uv run python experiments/k1719/k1719.py
uv run python scripts/experiment_gates.py run --path experiments/k1719
```

Outputs are written atomically.  The claim surface is the README, script,
result JSON, source snapshot, and chart; `review_verdict.json` is generated
only after the frozen files receive Codex review.
