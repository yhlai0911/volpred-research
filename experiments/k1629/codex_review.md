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

---

## Post-Publish Article Review (K1018 24h rule) — 2026-07-06

**Article**: `mile_467226e7` — 「開盤第一小時真的最危險嗎？」(published 2026-07-05 06:00 UTC; reviewed within 24h window)

**Method**: Full article-vs-source number audit (main thread) + focused Codex overclaim/lookahead pass (session 019f33e8).

**Number audit**: 20+ published figures all match `k1629_results.json` exactly —
period 2026-01-14~07-02, 117→114 days, 8889 bars; open 2.13x / 32.8% share / 92-of-114 days;
tail thresholds 17.03bp / -12.98bp; segment tail rates 12.5/11.5, 3.77/3.97, 3.07/3.22. No discrepancy.

**Codex verdict**: PASS_WITH_NOTE. No lookahead (descriptive slice, no signal×future return), no DM/Harvey
or predictive overclaim. Soft note: limit-order-at-open advice slightly exceeds descriptive evidence.

**Disposition**: PASS. No correction needed — article already hedges the execution advice with
「通常…更合理」and explicitly states 「本文是描述性日內風險切片，不是交易策略回測」. Codex's note is
covered by existing framing; no research-honesty violation.
