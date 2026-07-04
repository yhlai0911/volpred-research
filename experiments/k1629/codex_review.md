# Codex Review - K1629

Verdict: **PASS_WITH_LIMITATION**

Scope reviewed: `experiments/k1629/k1629.py`, generated `k1629_results.json`, and figures.

## Findings

1. **PASS - Data source and reproducibility**
   - The script reads only local files under `data/intraday/SPY_5min_YYYY-MM-DD.csv`; it does not call live yfinance or mutate input data.
   - Results record raw files, raw days, kept days, excluded days, date range, bar count, seed, and bootstrap reps.

2. **PASS - Intraday alignment and segmentation**
   - UTC timestamps are converted to `America/New_York` before assigning segments.
   - Segment assignment uses bar start time with half-open intervals: open `09:30 <= t < 10:30`, midday `10:30 <= t < 15:00`, close `15:00 <= t < 16:00`.
   - Complete-day filter removes incomplete local snapshots before inference. Segment-count filter then requires 12 open bars, 12 close bars, and at least 50 midday bars.

3. **PASS - Return and RV calculation**
   - Each 5-minute interval return is `log(Close/Open)` for the same OHLC bar.
   - Main metric is per-bar RV intensity normalized by full-day per-bar RV, so the long midday segment is not mechanically favored by duration.
   - No cross-day return is used in segment RV; overnight gaps are intentionally outside this intraday-only question.

4. **PASS - Lookahead / trading-signal risk**
   - The experiment is descriptive, not a predictive strategy. There is no signal multiplied by future returns and no same-day trading rule.
   - Tail thresholds are full-sample descriptive cutoffs used to characterize the realized distribution, not ex-ante trading signals.

5. **PASS - Statistical tests**
   - Daily paired intensity differences are tested with Newey-West HAC lag 5 on day-level differences.
   - Bootstrap uses fixed `seed=42` and resamples whole days, not individual bars.
   - Tail proportions include Wilson CIs and day-cluster bootstrap CIs. Pooled chi-square tests are clearly secondary; the cluster bootstrap guards against overstating independent 5-minute evidence.

6. **PASS - Boundary conditions**
   - The script handles missing/invalid files, invalid schema, incomplete days, zero RV days, and small n paths.
   - JSON output avoids NaN/Inf via `_safe_float` in all reported statistics.

7. **LIMITATION - Short local sample**
   - The result covers 114 complete SPY days from 2026-01-14 to 2026-07-02. This is sufficient for a reader-facing myth check but not a paper-grade long-history claim.
   - The article/knowledge entry must keep the conclusion limited to "SPY 2026 local 5-minute snapshot".

## Required Fixes

None.

## Gate Decision

K1629 can be recorded in knowledge and used for a general-audience draft, provided the sample limitation remains explicit.
