# K1392: Leave-COVID-out DM Test — A4f vs GJR (OOS Truncated to Paper Period)

**Paper**: Paper 9 (garch-x-vix)  
**Issue addressed**: C1 CRITICAL — K1391 used extended OOS (to 2026-05-20, n=1866) vs paper's stated OOS (to 2026-04-07, n≈1825). K1392 truncates OOS to match paper's period.  
**Status**: Queued for compute

## Motivation

K1391 found GJR beating A4f (t=-2.03) when OOS extended to May 2026. But the paper's stated OOS is 2019-01-01 to 2026-04-07 (n=1825). The 41 extra trading days (April 8 – May 20, 2026) caused the reversal. K1392 re-runs with `OOS_END = '2026-04-07'` to match paper's stated period and produce a valid leave-COVID-out analysis for C1.

## Hypothesis

H0: A4f advantage (paper DM t ≈ 4.03, pinned-snapshot t = 4.148) is not purely COVID-driven — non-COVID subperiod should retain Harvey-significant outperformance (|t| > 3.0).

## Design

- Identical to K1391 except OOS truncated: `OOS_START='2019-01-01'`, `OOS_END='2026-04-07'`
- n_full_oos expected ≈ 1825 (matching paper's stated n)
- All else same: W=2000, refit every 63 days, A4f vs GJR, full QLIKE kernel, Harvey |t| > 3.0

## Expected Result

If paper's claim is robust:
- Full OOS DM t ≈ +4.0 (matches paper / K988 / K1391-truncated)
- Non-COVID DM t > 3.0 (Harvey-sig) → add Table + robustness discussion to paper

If non-COVID DM t < 3.0:
- Must downgrade main claims and reframe as "full OOS significant but not Harvey-robust"

## Signal Timing (No Lookahead)

Same as K1391 (Codex v2 PASS): VIX lag applied via `vix_lag[t] = vix_vals[t-1]`; OOS forecast uses `vix[oos_idx-1]` consistently with training.

## References

- K1391: same experiment with extended OOS (shows reversal due to Apr-May 2026 data)
- K988: original A4f vs GJR result (n=1825, t=+4.48 live data)
- `paper/garch-x-vix/errata_pending.md`: SF1-K1391 entry
