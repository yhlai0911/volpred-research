# K1216 — K1213 multistart pattern applied to BR / IN / MX EM pooled MLE

**Status**: completed (worktree agent a76eb14b, 2026-04-17)
**Verdict**: `WIDESPREAD_FRAGILITY` — all 3 EM markets show the same
secondary-local-minimum pathology that K1213 exposed for AU.

---

## Motivation

K1213 (commit `c34d0546`) showed that the K1171 AU pooled
`theta_EAV = 3.16e-5` headline was stuck in a secondary local minimum:
a 100-random-start L-BFGS-B multistart + Nelder-Mead + differential-evolution
search found a best-LL basin-B `theta_rel = 1.476`, a 10× shift from the
K1171 `theta_rel = 0.150`. Both basins' max LL exceeded the K1171 canonical
LL by ≥71, so the K1171 fit was "neither basin's local max" — a pure
numerical artefact of the shared-MIDAS + stock-FE-GJR pooled spec plus
a narrow single-point default initialization.

If that same optimizer fragility also affects the other EM pooled fits:

- K1168 BR pool (canonical `theta_rel ≈ 1.89`, off-ladder)
- K1168 IN pool (canonical `theta_rel ≈ 1.17`, off-ladder)
- K1172 MX pool (canonical `theta_rel ≈ 1.20`, off-ladder)

then the Paper 2 Section 5 trajectory
K1165 (N=7, ρ=+0.75) → K1168 (N=10, +0.61) → K1172 (N=12, +0.44)
might be driven by the SAME numerical artefact, not by a real
cross-market institutional-ownership structure at EM level.

K1216 applies the K1213 multistart protocol verbatim to BR / IN / MX.

---

## Methodology (mirrors K1213 exactly)

For each of the 3 EM markets (N=10 stocks each, N=30 total):

1. **100 random initial points** (seed 42, start seeds `43..142`), sampled
   log-uniform on `theta0, theta_EAV ∈ [1e-6, 5e-4]` with random persistent
   `alpha/gamma/beta` within K1168/K1172 bounds.
2. **L-BFGS-B to convergence** reusing the EXACT `_pooled_wrap` from
   `k1168_per_stock_refit.py` (BR, IN) and `k1172_per_stock_refit.py` (MX).
   Same Numba `_pooled_negll`, same bounds, same penalty traps, no rewrite.
3. **K-means (K=2)** on converged `(theta_EAV, LL)` pairs → basin labels
   (0 = low-theta basin-A, 1 = high-theta basin-B).
4. **Best-LL across 100 starts** per market = global L-BFGS-B optimum.
5. **Sensitivity polish**: Nelder-Mead warm-start from L-BFGS-B best +
   differential-evolution (bounded, `seed = GLOBAL_SEED + 7`). The NM
   step is the honest global-search refinement; DE consistently hit the
   constraint-penalty wall and is excluded from the sensitivity metric
   but reported for transparency.
6. **Refined best-LL = max over {L-BFGS-B best, NM polish, valid DE}**.
7. **LR test** `LR = 2·(LL_refined − LL_canonical)` vs χ²(1)=3.84.
   Profile-LR half-threshold 1.92 used for "ROBUST" boundary.
8. **Standard errors**:
   - Hessian (numerical 2nd derivative on `theta_EAV` at refined point).
   - HAC-robust SE via stock-level score contributions (stocks
     independent, sandwich variance on `theta_EAV`).
9. **Spearman rebuild**: `rho(institutions_pct_mean, theta_rel)` with
   K1216-corrected BR/IN/MX (fragile markets get refined `theta_rel`),
   both N=12 (K1172 scope) and N=13 (+ K1213 AU).

Seeds, bounds, and lookahead guards are IDENTICAL to K1168/K1172 —
the only thing that differs is the 100-start search instead of one
default initialization.

---

## Per-market results

| Market | S | Conv | Canon θ_rel | L-BFGS-B best θ_rel | Refined θ_rel (NM) | Canon LL | Refined LL | LR stat | θ shift | Sens | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **BR** | 10 | 79/100 | 1.887 | 1.529 (basin-B) | **2.691** | 72213.52 | 72286.35 | **+145.66** | 42.7% | 76.0% | **FRAGILE** |
| **IN** | 10 | 80/100 | 1.170 | 2.783 (basin-B) | **3.077** | 81844.51 | 82049.89 | **+410.76** | 163.1% | 10.6% | **FRAGILE** |
| **MX** | 10 | 64/100 | 1.202 | 1.558 (basin-B) | **1.845** | 75932.06 | 76105.69 | **+347.27** | 53.5% | 18.5% | **FRAGILE** |

Basin structure (K-means on converged points):

| Market | Basin-A frac | Basin-A θ mean | Basin-A LL max | Basin-B frac | Basin-B θ mean | Basin-B LL max |
|---|---|---|---|---|---|---|
| BR | 23% | −4.73e-4 (trap/negative) | 69539 | 77% | +7.07e-4 | 72009 |
| IN | 61% | +6.80e-5 | 81831 | 39% | +6.45e-4 | 81947 |
| MX | 45% | +1.22e-4 | 75888 | 55% | +6.36e-4 | 75952 |

**Key observations**:
- **All 3 markets have LR >> χ²(1)=3.84** (LR = 145, 411, 347). By
  standard nested-LR inference the canonical K1168/K1172 fit is REJECTED
  at p < 1e-30 for every market.
- **Refined `theta_rel` shifts by 43–163%** from canonical. Not a
  precision issue — the canonical point is in a completely different
  basin than the NM-polished best-LL.
- **NM refinement consistently beats L-BFGS-B best** for all 3 markets,
  by +73, +103, +154 log-likelihood units. The L-BFGS-B 100-multistart
  search alone would have under-reported the true best-LL basin for BR/MX.
- DE always ended in the constraint penalty wall (`LL ≈ −1e13`) due to
  its stochastic population hitting `persistence ≥ 0.999` for some stocks.
  This is a failure mode of the bounded formulation, not an informative
  sensitivity signal; excluded from the sensitivity metric.
- **HAC SE remains highly significant** at the refined point:
  t-statistics 3.24 (BR), 6.58 (IN), 3.74 (MX). The effect is real —
  what shifts is its magnitude, not its sign.

**Per-market Hessian/HAC SE at refined best**:

| Market | θ_EAV refined | Hess SE | Hess t | HAC SE | HAC t |
|---|---|---|---|---|---|
| BR | 1.740e-3 | 9.56e-5 | 10.34 | 3.05e-4 | 3.24 |
| IN | 8.546e-4 | 6.61e-5 | 11.69 | 1.17e-4 | 6.58 |
| MX | 6.372e-4 | 4.87e-5 | 11.04 | 1.44e-4 | 3.74 |

(Hessian SE is computed at the L-BFGS-B best; it understates uncertainty
when the refined NM point differs. HAC SE is the preferred inference
quantity.)

---

## Cross-market Paper 2 §5 trajectory

Spearman `rho(institutions_pct_mean, theta_rel)`:

| Scenario | N | ρ | p | Harvey t |
|---|---|---|---|---|
| K1165 N=7 pre-EM | 7 | +0.750 | 0.052 | — |
| K1168 N=10 add BR/CH/IN | 10 | +0.612 | 0.060 | — |
| K1172 N=12 add MX/ID (baseline) | 12 | +0.441 | 0.152 | 1.55 |
| **K1216-corrected EM N=12** | 12 | **+0.364** | 0.245 | 1.23 |
| **K1216-corrected EM + K1213 AU N=13** | 13 | **+0.341** | 0.255 | 1.20 |

**Interpretation**: correcting all 3 EM pooled fits to their refined
best-LL `theta_rel` further ERODES the cross-market ρ
(+0.441 → +0.364, Harvey t 1.55 → 1.23). Adding K1213-corrected AU
(above-ladder `theta_rel ≈ 1.48`) drops ρ one more notch to +0.341
(t=1.20). Both are BELOW the +0.50 benchmark used as STRENGTHENED/
CONFIRMED threshold in K1165/K1168.

The intuition: the K1168/K1172 canonical EM fits were UNDERSTATING
the true EM `theta_rel`. Correcting them pushes EM markets further
ABOVE the developed-market ladder (TW 0.17, EU 0.14, JP 0.39, US 0.59),
weakening rather than strengthening the institutional-ownership proxy.

Institutions-pct ranking does NOT explain the EM off-ladder residual
even after fixing the optimizer bug. The N=12/13 Spearman trajectory
from K1165 N=7 ρ=+0.75 to K1216 ρ=+0.34 is a *magnitude* decay of 55%,
driven almost entirely by EM markets being larger `theta_rel` than the
institutional-ownership proxy predicts.

---

## Cross-market verdict: `WIDESPREAD_FRAGILITY`

**All 3 EM markets (BR, IN, MX) are FRAGILE** under the K1213 multistart
protocol. The K1168/K1172 canonical pooled fits appear broadly stuck in
secondary local minima under the shared-MIDAS + stock-FE-GJR spec.

**Paper 2 Section 5 implications**:

1. **Numerical-fragility disclosure is MANDATORY**. Every paper
   reporting K1168/K1172 pooled `theta_EAV` numbers must either
   (a) adopt K1216 refined best-LL, or (b) disclose that the
   canonical fit is a secondary local minimum with LR p << 1e-30.
2. **EM above-ladder residual GROWS, not shrinks**, after the correction.
   The K1165 → K1172 ρ decay trajectory is not explained by a single
   numerical artefact. The "EM off-ladder" pattern is larger than
   K1168/K1172 reported, so the institutional-ownership proxy is LESS
   predictive of cross-market `theta_rel` than Paper 2 §5 claimed.
3. **MAJOR trajectory revision required**: the N=12 → N=13 Harvey t is
   1.20 (p ≈ 0.25), not 1.55. The "institutional-ownership + analyst
   coverage two-level mechanism" as a cross-market EM explanation is
   more tenuous than K1168/K1172 headline. Paper 2 §5 should explicitly
   flag the EM `theta_rel` magnitudes as provisional pending a proper
   global-search re-estimation of all pooled fits (all 13 markets, not
   just AU/BR/IN/MX).
4. **Downstream impact on Paper 2 §5 narrative sketch**: do NOT
   describe the EM off-ladder as "mild above-ladder". The refined
   magnitudes are `theta_rel = 2.69 (BR), 3.08 (IN), 1.85 (MX),
   1.48 (AU from K1213)`, which are 4-10× the developed-market ladder,
   not "mildly above". This is either a real cross-market structural
   break OR evidence that the shared-MIDAS pooled spec is misspecified
   for high-volatility markets.

### Follow-ups recommended

- K1216b: apply 100-start search to the remaining K1168 pooled CH, and
  K1172 pooled ID fits (were neutral / on-ladder but should be checked).
- K1216c: apply 100-start search to the developed-market pools
  (TW/EU/JP/US/KR/CA/HK) to confirm the ladder base is stable.
- Investigate whether the basin structure correlates with
  `n_events × S` or with specific pathological stocks (eg KOFUBL.MX
  has only 1690 obs vs 3015 for others).

---

## Rigor / replication

- **Global seed**: 42 (reproducible).
- **Start seeds**: `43..142` shared across markets (so each market
  sees the same random-init distribution in the parameter-structure sense,
  though `sample_start` scales to each market's `mean_sigma2` and
  `vix2_mean`).
- **Bounds**: identical to K1168/K1172 / K1213 per brief requirement.
- **Lookahead guard**: inherited from the imported `_pooled_negll`
  (`VIX^2_{t-1}`, `EAV_{i,t-1}`). No new data pulled.
- **Penalty-trap guard**: reject fits with `res.fun > 1e11` or `-res.fun
  < 1000` (the K1213 heuristic; same numeric thresholds).
- **Data**: reused from `experiments/k1168/data/` (BR/IN) and
  `experiments/k1172/data/` (MX). No new fetches. VIX shared.
- **Worktree contract**: all outputs in `experiments/k1216/`; no
  modification of `storage/memory/` or `experiments/k1168/`, `k1171/`,
  `k1172/`, `k1213/`.

## Files

- `k1216.py` — main driver (imports k1168_per_stock_refit and
  k1172_per_stock_refit as-is).
- `k1216_results.json` — full per-market + cross-market results,
  Spearman rebuilds, Harvey t's, paper2 trajectory table.
- `k1216_per_market_summary.csv` — compact per-market verdict table.
- `k1216_multistart_results.csv` — all 300 (3 markets × 100 starts)
  per-start rows with convergence status and theta_EAV if converged.
- `k1216_BR_basin_hist.png` — BR basin histogram (100 starts).
- `k1216_IN_basin_hist.png` — IN basin histogram.
- `k1216_MX_basin_hist.png` — MX basin histogram.
- `k1216_trajectory.png` — per-market canonical vs K1216 `theta_rel`
  bars + Paper 2 §5 Spearman trajectory.
- `run.log` — stdout transcript.

## Cross-references

- K1213 (commit `c34d0546`) — AU multistart precedent.
- K1168 (commit in k1168/) — BR/IN/CH pooled canonical.
- K1172 (commit in k1172/) — MX/ID/ZA pooled canonical.
- K1171 — AU pre-K1213 pooled canonical.
- Paper 2 Section 5 — cross-market institutional-ownership mechanism;
  needs revision per this K1216 verdict.
