# K1341 Codex Code Review

**Reviewer**: Codex CLI (gpt-5.4 via `codex exec`)
**Review date**: 2026-06-15

## v1 review — VERDICT: FAIL

Codex flagged 4 issues:

1. **Baseline exclusion was approximate** (`K1341.py:164`). Used a calendar-day
   buffer (`event_date ± 10 cal days`) instead of the actual trading-day
   positional window `[pos-5, pos+5]`. Holiday weeks could mis-exclude.
2. **`align_event_to_index` silently snapped forward** (`K1341.py:128`) with no
   max-gap check; a non-trading-day Friday could leak into Monday with no audit
   trail.
3. **Bootstrap p-value** could return zero — should use `(count + 1) / (B + 1)`.
4. **t+1 z-score divisor** used cross-event std of baseline means, not
   per-event baseline std. This does not support the "reverted vs persistent"
   interpretation.

## v2 review — VERDICT: PASS

All 4 issues fixed and verified by Codex:

- (a) `align_event_to_index(..., max_gap_days=3)` forward-snaps holiday Fridays
  and rejects longer gaps.
- (b) Baseline exclusion now uses positional trading-day window from
  `df.index[excl_lo:excl_hi]` via `same_month_baseline_values`.
- (c) t+1 z-score uses per-event `same_month_baseline_std`.
- (d) Bootstrap p-value uses `(count + 1) / (B + 1)`.

Codex also ran `py_compile` and synthetic helper checks on the four fixes; all
passed. No new bugs introduced.

**Final reviewer source**: Codex CLI (primary path).
**Final verdict**: PASS.

## Caveat noted (not blocking)

- Russell sample is small (n=12). Block bootstrap p-values around 0.02-0.18
  should be interpreted with multiple-testing concerns (15 tests across
  ticker × measure × event-set). A Bonferroni-style correction would shift
  IWB r2_cc / IWB parkinson / QQQ r2_cc out of significance.

## Key empirical findings (results.json)

- **Russell reconstitution day (n=12)**: IWM r2_cc event mean 2.85e-4 vs
  baseline 1.75e-4 (1.6x); IWM t+1 z=+2.20 — **t+1 does NOT mean-revert** for
  IWM. Wilcoxon p high (0.81) because of mixed-sign individual events; bootstrap
  p on IWB / QQQ around 0.02-0.03 but mark as exploratory after MT correction.
- **S&P quarterly rebalance (n=49)**: All p-values non-significant across SPY
  and QQQ; t+1 z-scores small (|z|<0.7). No evidence of dislocation effect at
  the S&P-quarterly event horizon.

## Interpretation

The original hypothesis (dislocation then mean reversion) is **not supported**.
- Russell day on IWM shows persistence not reversion (z>+2 at t+1).
- S&P quarterly shows nothing detectable.

This qualifies as a **CONDITIONAL_PASS with NULL/REVERSED finding** for the
research narrative — the experimental method is sound (PASS by Codex v2) but
the empirical answer to the motivating question is "no clean dislocate-revert
pattern at daily frequency for these ETF proxies."
