# K1391: Leave-COVID-out DM Test — A4f vs GJR

**Paper**: Paper 9 (garch-x-vix)  
**Issue addressed**: C1 CRITICAL — v3 review: OOS period 2019-2026 contains COVID-19 crash (VIX peak 82.69); without subperiod analysis, VIX-based model advantage could be crisis-driven  
**Status**: Queued for compute

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

## References

- K988: Multiplicative GARCH-X spec comparison (A4f baseline result)  
- Diebold & Mariano (2002); Harvey et al. (2016)  
- `paper/garch-x-vix/consolidated_issues_v3.md` C1 CRITICAL
