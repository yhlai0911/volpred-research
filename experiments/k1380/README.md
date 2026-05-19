# K1380 — Paper 9 White RC / Hansen SPA Test for 17-Spec Horse Race

## Motivation

Paper 9 (garch-x-vix) review v3 identified C3 (CRITICAL):
> "17-specification ranking requires multiple testing correction. White (2000) Reality Check or
> Hansen (2005) Superior Predictive Ability test is needed for the horse-race claims."

The paper ranks 17 multiplicative volatility models (A1-A4n GARCH-X, B1-B3 MIDAS-RW,
C1-C3 MIDAS-FS, B0 GJR benchmark) by QLIKE. Without multiple testing correction, the
ranking of A4f as "best" is subject to data snooping bias. K1380 applies:
- **Hansen (2005) SPA test**: Is there any model in the set that significantly beats all others?
- **White (2000) RC test**: Is the best model (A4f) significantly better than the benchmark (GJR)?

## Method

### Data
- `paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv` (pinned snapshot)
- SPY daily log returns + VIX daily close
- OOS period: 2019-01-01 onward (consistent with Paper 9 main results)
- Rolling window: W=2000, refit_every=63

### 17 Specifications (Paper 9 Table 1)
**GARCH-X A-series (10 specs):**
- A1: log-exp τ_t, inconsistent τ estimation (K889 original)
- A2: log-exp τ_t, consistent τ_t, constrained ω_g
- A3: log-exp τ_t, consistent τ_{t-1}, constrained ω_g
- A4: VIX² τ_t, constrained ω_g
- A5: exp(VIX) τ_t, constrained ω_g
- A2f: log-exp τ_t, free ω_g
- A4f: VIX² τ_t, free ω_g (best by QLIKE in full paper)
- A3f: log-exp τ_{t-1}, free ω_g
- A2n: log-exp τ_t, sample-mean normalization
- A4n: VIX² τ_t, sample-mean normalization

**GARCH-MIDAS (6 specs):**
- B1: Rolling-window Beta poly K=22 daily VIX lags
- B2: Rolling-window Beta poly K=65 daily VIX lags
- B3: Rolling-window Beta poly K=125 daily VIX lags
- C1: Fixed-span Beta poly Km=6 monthly VIX averages
- C2: Fixed-span Beta poly Km=12 monthly VIX averages
- C3: Fixed-span Beta poly Km=24 monthly VIX averages

**Benchmark (1 spec):**
- B0: GJR-GARCH(1,1)

### Lookahead Prevention
- All VIX regressors use signal at t-1: `vix[abs_idx - 1]` for one-step-ahead forecast
- MIDAS: log VIX lags from t-1 to t-K
- No returns data leakage: estimation uses only returns up to t-1

### Tests
1. **White RC (2000)**: H0: E[d_i] = E[L_A4f - L_GJR] ≤ 0 for all i≠A4f. Stationary bootstrap, B=999.
2. **Hansen SPA (2005)**: H0: no model in the set is significantly better than the benchmark. Uses consistent estimator for variance.

### Success Criteria
- Primary: SPA p-value for A4f < 0.10 → A4f survives data snooping test
- Secondary: Report which models survive in the superior set
- Paper body: Add "Multiple Testing" subsection with SPA results as Table

## Seed & Reproducibility
- seed=42 for bootstrap
- signal.shift(1) for all VIX lags (explicit lookahead prevention)

## Files
- `k1380.py`: main script
- `k1380_results.json`: results with SPA test statistics + p-values
- `k1380_losses_all.npy`: (17, n_oos) QLIKE loss matrix for future use
