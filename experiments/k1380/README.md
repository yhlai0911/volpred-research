# K1380 — Paper 9 White RC / Hansen SPA Test for 17-Spec Horse Race

## STATUS: 2026-07-16 run DISCARDED (loss function was reversed) — re-run queued 2026-07-17

The 2026-07-16 run reported that **no VIX-augmented spec beats GJR after multiple-testing
correction** (SPA $p=1.000$, White RC on A4f $t=-0.272$, GJR lowest mean QLIKE 623.7). That
conclusion was an artifact and **must not be cited or written into Paper 9**.

**Root cause.** `k1380.py`'s `qlike()` computed the ratio as $\hat\sigma^2/r^2$ instead of
$r^2/\hat\sigma^2$. Patton's (2011) proxy-robust QLIKE is
$r^2/\hat\sigma^2 - \log(r^2/\hat\sigma^2) - 1$, which is rank-equivalent to the canonical
$\log\hat\sigma^2 + r^2/\hat\sigma^2$ used in `paper/garch-x-vix/reproduce.py:927`. The reversed
form is a different loss and is **not robust**: under $r^2 = \sigma^2\chi^2_1$, $E[1/r^2]$
diverges, so its expectation is minimized by shrinking $\hat\sigma^2 \to 0$. It mechanically
rewards under-forecasting.

Verified numerically (2026-07-17, 400k draws, forecasts $= c \cdot \sigma^2_{\text{true}}$):

| $c$ | robust $r^2/\hat\sigma^2$ | reversed $\hat\sigma^2/r^2$ |
|---|---|---|
| 1.00 (truth) | **1.271** (min) | 559,680 |
| 0.50 | 1.578 | 279,840 |
| 0.10 | 7.968 | 55,968 |
| 0.02 | 46.356 | 11,195 |

The robust loss is minimized at the truth; the reversed loss falls monotonically as forecasts
shrink. GJR — which never receives VIX spikes and therefore forecasts lowest — wins by
construction. Three corroborating symptoms, all consistent with this and with nothing else:

1. **Scale.** Mean QLIKE $\approx 620$–$740$, versus $\approx 1.4$ for the same proxy, same OOS
   window, same $n=1{,}852$ in the paper's own K1379 run (`main.tex`, HAR-benchmark subsection).
   Loss max was $4.1\times10^8$ — the mean is dominated by near-zero-$r^2$ days.
2. **Lost power.** A4f vs.\ GJR gave $t=-0.272$ here but $t=-4.37$ ($p=1.3\times10^{-5}$) in
   K1379 on the identical sample. Noise from tiny-$r^2$ days swamped the signal, so SPA/RC
   failing to reject is a power artifact, not evidence of no effect.
3. **Bogus exclusions.** A5/C2/C3 were dropped as "numerically divergent" on mean QLIKE
   255,122 / 9,349 / 3,904. Those are the specs with the *highest* forecasts — exactly what the
   reversed loss punishes hardest. Their convergence must be re-assessed, not assumed.

**Artifacts from that run are archived, not deleted** (`*_INVALID_20260716.*`).
`k1380_losses_all_INVALID_20260716.npy` caches the *wrong* loss and cannot be repaired
arithmetically ($x - \log x - 1$ is not injective), so `k1380_spa_from_cache_INVALID_20260716.py`
is dead — the OOS forecasts have to be re-fitted. `k1380.py:647` is fixed and the re-run is in
the compute queue; the Paper 9 "Multiple Testing" subsection waits on its output.

Both possible outcomes are publishable: the multiple-testing correction either upholds the
paper's A4f-over-GJR claim or overturns it. What is not acceptable is deciding it with a loss
that rewards forecasting zero.

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
