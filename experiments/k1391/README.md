# K1391: Leave-COVID-out DM Test — A4f vs GJR

**Paper**: Paper 9 (garch-x-vix)  
**Issue addressed**: C1 CRITICAL — v3 review: OOS period 2019-2026 contains COVID-19 crash (VIX peak 82.69); without subperiod analysis, VIX-based model advantage could be crisis-driven  
**Status**: COMPLETED — CONDITIONAL PASS (Codex v2 reviewed; results valid but OOS ≠ paper's stated OOS)

## Hypothesis

H0: A4f advantage (K988 DM t ≈ +4.03) is not purely COVID-driven — non-COVID subperiod should retain Harvey-significant outperformance (|t| > 3.0).

If advantage collapses in non-COVID period: must re-frame paper claims.  
If advantage persists: adds robustness to paper narrative.

## Design

- Model pair: A4f (`tau_t = theta0 + theta1*VIX^2_{t-1}`, GJR g-component) vs GJR-GARCH(1,1)  
- Protocol mirrors K988: W=2000 rolling window, refit every 63 days, OOS from 2019-01-01  
- QLIKE loss function; Diebold-Mariano test with Newey-West HAC (`q = int(T^(1/3))`)  
- Harvey et al. (2016) threshold: |t| > 3.0 for significance

### Subperiods

| Name | Period |
|------|--------|
| full_oos | 2019-01-01 onward |
| non_covid | full_oos minus COVID window |
| pre_covid | 2019-01-01 to 2020-01-31 |
| covid_window | 2020-02-01 to 2020-06-30 |
| post_covid | 2020-07-01 onward |

## Signal Timing (No Lookahead)

- `tau_t = theta0 + theta1 * VIX^2_{t-1}`: VIX lag applied via `vix_lag[t] = vix_vals[t-1]` in both `a4f_loglik` and `a4f_variance_series`  
- OOS forecast: `vix_for_tau = vix[oos_idx - 1]` (VIX_{t-1}), consistent with training convention  
- GJR uses `r_{t-1}` and `h_{t-1}` for one-step-ahead (standard)

## Stationarity Constraints (Fair Comparison)

Both models enforce `alpha + gamma/2 + beta < 0.999` via SLSQP constraint.

## Codex Reviews

- **v1 (2026-05-22)**: FAIL — found (1) train/predict VIX timing inconsistency (contemporaneous vs lagged), (2) GJR missing stationarity constraint, (3) DM sign comment error
- **v2 (2026-05-22)**: PASS — all three fixes verified: vix_lag shift in both a4f functions, g_last extracted directly from h_g series, GJR SLSQP constraint added

## Data

`paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv` (local snapshot, no live fetch)

## Results (recomputed 2026-07-27T15:06 UTC after snapshot-dedup, n_oos=1900)

> **Snapshot-dedup guard (2026-07-27)**: the 2026-05-22 run (n_oos=1866) ran on a
> canonical snapshot that contained duplicate trading days, which leaked into the DM
> test. Root cause fixed in the loader (`sort_index()` then
> `df_raw[~df_raw.index.duplicated(keep="last")]`). Rerun on the clean+extended
> snapshot yields n_oos=1900. **Verdict does not flip** — GJR still wins full/non-COVID/
> post-COVID — but post-COVID now reaches Harvey significance (see notes). Old
> contaminated numbers preserved below under "prior contaminated run" for audit.

| Period | n | DM t | p-value | Harvey sig | Winner |
|--------|---|------|---------|------------|--------|
| Full OOS (2019-05-20) | 1900 | **−2.054** | 0.040 | ✗ | GJR |
| Non-COVID | 1796 | **−2.924** | 0.0035 | ✗ | GJR |
| Pre-COVID | 273 | −0.351 | 0.726 | ✗ | GJR (small) |
| COVID window | 104 | +1.465 | 0.146 | ✗ | A4f (not sig) |
| Post-COVID | 1523 | **−3.208** | 0.0014 | **✓** | GJR |

Notes:
- DM convention: positive t = A4f better (lower QLIKE loss), negative t = GJR better
- QLIKE kernel: log(σ²) + r²/σ², full kernel (not r² proxy)
- **Post-COVID now reaches Harvey significance** (|t|=3.21 > 3.0) on the clean snapshot;
  all other subperiods remain below the Harvey threshold.

### Prior contaminated run (2026-05-22, n_oos=1866 — superseded, kept for audit)

| Period | n | DM t | p-value | Winner |
|--------|---|------|---------|--------|
| Full OOS | 1866 | −2.030 | 0.042 | GJR |
| Non-COVID | 1762 | −2.554 | 0.011 | GJR |
| Post-COVID | 1489 | −2.460 | 0.014 | GJR |

## Critical Finding: OOS Period Mismatch

**K1391 OOS extends to 2026-05-20 (clean n=1900), paper's stated OOS ends 2026-04-07 (n=1825).**  
The extra trading days are sufficient to flip the result:

- Paper / pinned snapshot (n=1825): A4f DM t ≈ +4.148 (Harvey-sig) ← A4f wins
- K1391 (clean n=1900): DM t = −2.054 ← GJR wins

This reversal indicates **A4f advantage collapsed in April–May 2026 data**. Likely cause: VIX remained elevated (trade-war period) but SPY returns were lower-than-expected volatility, causing A4f's large τ_t (via VIX²) to over-predict variance → worse QLIKE.

### Implication for Paper 9 C1

K1391 does NOT directly address C1 (leave-COVID-out for the paper's OOS 2019–April 2026). Need:
- **K1392**: Truncate OOS to 2026-04-07 to match paper's stated period; then re-run subperiod analysis.
- K1391 results (extended OOS): separately useful as an out-of-sample monitoring finding (A4f advantage not stable post-April 2026).

## Codex Reviews

- **v1 (2026-05-22)**: FAIL — found (1) train/predict VIX timing inconsistency (contemporaneous vs lagged), (2) GJR missing stationarity constraint, (3) DM sign comment error
- **v2 (2026-05-22)**: PASS — all three fixes verified: vix_lag shift in both a4f functions, g_last extracted directly from h_g series, GJR SLSQP constraint added

## References

- K988: Multiplicative GARCH-X spec comparison (A4f baseline result, n=1825, t=+4.48)  
- errata_pending.md: pinned snapshot A4f DM t = 4.148 (n=1825)
- K1392 (pending): leave-COVID-out with truncated OOS to match paper's stated period
- Diebold & Mariano (2002); Harvey et al. (2016)
