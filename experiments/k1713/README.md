# K1713 — verified duplicate closure for the daily-OHLC HARQ test

## Disposition

`DUPLICATE_CLOSURE_PASS` if the executable audit remains green.

The queued K1713 brief is already fully implemented by `experiments/k1661/`.
K1661 tests whether a noisy daily-OHLC proxy for realized quarticity makes HARQ
measurement-error weighting ineffective or harmful relative to HAR. It uses
SPY, 0050.TW, and TWII as the documented TX proxy; Garman-Klass daily variance;
range-based quarticity; rolling-window HAR/HARQ forecasts; QLIKE; and DM-HLN.

Creating another empirical K from the same source snapshots, design, and null
result would falsely suggest an independent replication. K1713 therefore
closes the stale queue item with a byte-traceable replay audit and creates no
new knowledge claim.

## Motivation and prior knowledge

The queue description says that HARQ had not yet been implemented in the
repository. That premise became stale when K1661 was completed on 2026-07-08.
The pre-run search found:

- K1582: true 5-minute realized quarticity; HARQ directionally improves TX
  QLIKE but misses the project significance gate.
- K1661: the exact contrarian daily-OHLC experiment requested by K1713;
  canonical verdict `NULL`, with consistent but insignificant HARQ degradation.
- Knowledge already contains the K1661 finding, so K1713 must not append a
  second entry.

## External anchors

- Corsi (2009), *A Simple Approximate Long-Memory Model of Realized
  Volatility*, supplies the HAR baseline.
- Bollerslev, Patton, and Quaedvlieg (2016), *Exploiting the Errors*, supplies
  the HARQ measurement-error interaction.
- Garman and Klass (1980), *On the Estimation of Security Price Volatilities
  from Historical Data*, supplies the OHLC range estimator.
- Patton (2011), *Volatility Forecast Comparison Using Imperfect Volatility
  Proxies*, motivates actual-over-predicted QLIKE.
- Harvey, Leybourne, and Newbold (1997) supplies the small-sample DM
  correction used by K1661.

## Audit method

`K1713.py` performs three layers of verification:

1. Contract checks confirm that K1661 contains the requested markets, GK and
   range-quarticity functions, HAR/HARQ models, 1,000-day rolling window,
   actual-over-predicted QLIKE, and DM-HLN with horizon one.
2. An independent target-date ledger rebuilds every feature using explicit
   `signal.shift(1)` and must be byte-equal to K1661's design matrix.
3. Every model for every asset is replayed from K1661's committed OHLC
   snapshots. QLIKE, MSE, sample counts, insanity-filter counts, and HARQ-vs-HAR
   DM-HLN statistics must match the committed result within declared numeric
   tolerances.

The output records SHA-256 hashes of the source script, stored result, review,
and each OHLC input snapshot.

## Lookahead policy

At target date `t`, daily, weekly, monthly, and quarticity features are all
lagged with `signal.shift(1)`. K1661's rolling training slice ends at `t-1`, so
every training target date is strictly earlier than the forecast origin. The
DM inference horizon is `h=1`, matching the one-day forecast target. Seed 42 is
fixed even though the replayed OLS path is deterministic.

## Success criteria

Closure passes only if all contract checks are true, all three independently
rebuilt design matrices are byte-equal, and every replayed metric matches the
stored K1661 result. Any mismatch produces `AUDIT_FAIL` and a non-zero exit.

Passing this gate means only that K1713 is a verified duplicate. It does not
upgrade K1661's empirical `NULL`, does not convert directional evidence into
statistical evidence, and must not be counted as another replication.

## Reproduction

```bash
uv run python experiments/k1713/K1713.py
uv run python scripts/experiment_gates.py run --path experiments/k1713
```

Expected files:

- `README.md`
- `K1713.py`
- `K1713_results.json`
- `review_primary_20260716.md`
- `review_verdict.json`
