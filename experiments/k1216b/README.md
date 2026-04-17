# K1216b — Close the 5-EM multistart audit: CH + ID

**Status**: completed (worktree agent `agent-aa5753c4`, 2026-04-17)
**Verdict**: `ALL_5_EM_FRAGILE` — CH + ID join BR, IN, MX, AU as trapped
pooled MLE cases. The 5-EM pattern exposed by K1213/K1216 is universal.

---

## Motivation

K1213 found that K1171 AU pooled `theta_EAV` was not at any local maximum
under the shared-MIDAS + stock-FE-GJR pooled specification — it sat
between two basins, both of whose best-LL points exceeded the canonical
LL by ≥71 (LR statistic `>> χ²(1) = 3.84`). K1216 applied the same
100-multistart protocol to the three high-`theta_rel` EM pools
(BR 1.89, IN 1.17, MX 1.20) and returned a decisive
**`WIDESPREAD_FRAGILITY`**: LR statistics `+146 / +411 / +347` against
canonical, refined `theta_rel` 1.85–3.08.

Two EM markets in the K1168/K1172 panel remained untested:

- **CH (Shanghai SSE)**, from K1168, canonical `theta_rel = 0.304`, N=10 stocks
- **ID (IDX Composite)**, from K1172, canonical `theta_rel = 0.238`, N=10 stocks

Both have LOW canonical `theta_rel`. If they also prove fragile, the 5-EM
pattern is universal regardless of canonical theta magnitude. If they
are robust, optimizer fragility partitions on `theta_rel` level —
"off-ladder" pools trapped, "near-ladder" pools fine — which would be
an exculpatory finding for Paper 2 §5.

K1216b closes this gap.

---

## Methodology (mirrors K1213 / K1216 exactly)

For each of the 2 markets (N=10 stocks each, N=20 total):

1. **100 random initial points** (seed 42, start seeds `43..142`),
   sampled log-uniform on `theta0, theta_EAV ∈ [1e-6, 5e-4]` with random
   persistent `alpha/gamma/beta` within K1168/K1172 bounds.
2. **L-BFGS-B to convergence** reusing the EXACT `_pooled_wrap` from
   `k1168_per_stock_refit.py` (CH) and `k1172_per_stock_refit.py` (ID).
   Same Numba `_pooled_negll`, same bounds, same penalty trap rejection.
3. **K-means (K=2)** on converged `(theta_EAV, LL)` pairs → basin labels.
4. **Best-LL across 100 starts** per market = L-BFGS-B global estimate.
5. **Sensitivity polish**: Nelder-Mead warm-start from L-BFGS-B best +
   differential-evolution (bounded, `seed = GLOBAL_SEED + 7`). DE is
   penalty-wall excluded if `LL ≤ 1000`.
6. **Refined best-LL** = `max` over valid optimizers.
7. **LR test** `LR = 2·(LL_refined − LL_canonical)` vs `χ²(1)=3.84`.
   Half-threshold `1.92` used for the ROBUST cutoff (profile-LR).
8. **Standard errors**: numerical Hessian on `theta_EAV` + HAC-robust
   sandwich (stock-level score contributions, stocks independent).
9. **5-EM Spearman rebuild**: combine K1216 BR/IN/MX refined + K1216b
   CH/ID refined + K1213 AU refined into
   `ρ(institutions_pct_mean, theta_rel)` at N=12 and N=13.

The K1216 optimization helpers (`load_market_stocks`, `fit_pooled_lbfgs`,
`kmeans_basins`, `hessian_se_theta_eav`, `hac_se_theta_eav`,
`run_sensitivity`, `plot_basin_hist`) are imported by file path from
`experiments/k1216/k1216.py`. K1216b only monkey-patches
`MARKET_SPEC / CANONICAL / ROOT` to route them to CH + ID — **no
rewrite**, per brief.

Seeds, bounds, lookahead guards IDENTICAL to K1168 / K1172 / K1213 / K1216.

---

## Per-market results

| Market | S | Conv | Canon θ_rel | L-BFGS-B best θ_rel (basin) | Refined θ_rel (source) | Canon LL | Refined LL | LR stat | θ shift | Sens | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **CH** | 10 | 78/100 | 0.304 | 1.001 (B) | **1.469** (NM)       | 77922.50 | 78221.47 | **+597.94** | 383.5% | 46.8% | **FRAGILE** |
| **ID** | 10 | 64/100 | 0.238 | 0.709 (A) | **1.917** (NM)       | 76494.23 | 76676.91 | **+365.36** | 706.5% | 170.2% | **FRAGILE** |

Both LR statistics blow past `χ²(1) = 3.84` by two orders of magnitude.
`θ_EAV` shifts of 3.8× (CH) and 7.1× (ID) and refined `θ_rel ≈ 1.5–1.9`
mean the canonical estimates are not a local maximum of the pooled
likelihood — they are optimizer-trap artefacts.

### Basin structure (K-means on converged points)

| Market | Basin-A frac | Basin-A θ mean | Basin-A LL max | Basin-B frac | Basin-B θ mean | Basin-B LL max |
|---|---|---|---|---|---|---|
| **CH** | 0.55 | 2.24e-05 | 77817.35 | 0.45 | 3.61e-04 | 77991.78 |
| **ID** | 0.47 | 1.34e-04 | 76524.30 | 0.53 | 5.03e-04 | 76511.37 |

- CH shows the cleanest basin-B dominance: basin-B max-LL (77991.78)
  exceeds basin-A max-LL (77817.35) by 174 LL units. The canonical LL
  (77922.50) sits *between* the two basin maxima — not in either basin's
  peak. This is the exact K1213 pathology.
- ID has basin-A max-LL (76524.30) marginally above basin-B max-LL
  (76511.37), but both are surpassed by the NM polish (76676.91), which
  lands at `θ_EAV = 7.80e-4` — outside the log-uniform [1e-6, 5e-4]
  start range. Warm-started NM finds a HIGHER basin than L-BFGS-B
  random starts reach, confirming the optimizer fragility is not just
  between two basins but includes a third off-grid optimum.

### Sensitivity

- CH: NM polish beats L-BFGS-B best by 229.70 LL units (+46.8% θ shift).
  DE penalty-trapped (excluded).
- ID: NM polish beats L-BFGS-B best by 152.60 LL units (+170.2% θ shift).
  DE penalty-trapped (excluded).

### Standard errors

| Market | Hessian SE | Hessian t | HAC SE | HAC t |
|---|---|---|---|---|
| **CH** | 4.20e-05 | 8.40 | 1.17e-04 | 3.00 |
| **ID** | 3.33e-05 | 8.67 | 1.13e-04 | 2.54 |

HAC t-stats remain significant (≥2.5) at the refined `θ_EAV`, so the
*sign and significance* of the institutional-ownership effect survive —
only the *magnitude* flips 4-8× versus canonical.

---

## 5-EM combined trajectory (Spearman primary)

Cross-market Spearman `ρ(institutions_pct_mean, θ_rel)` under every
layer of correction, N=12 (K1172 scope) and N=13 (+ K1213 AU):

| Layer | Scope | ρ | p | Harvey t | N |
|---|---|---|---|---|---|
| K1172 baseline (canonical)                     | dev+EM canon | **+0.441** | 0.152 | +1.55 | 12 |
| K1213 AU only                                   | + AU refined | +0.418 | 0.156 | +1.52 | 13 |
| K1216 EM refined (BR/IN/MX)                     | 3 EM refined | +0.364 | 0.245 | +1.23 | 12 |
| K1216 EM + K1213 AU                             | 3 EM + AU refined | +0.341 | 0.255 | +1.20 | 13 |
| **K1216b 5-EM refined (BR/IN/MX/CH/ID)**        | **5 EM refined** | **−0.077** | **0.812** | **−0.24** | **12** |
| **K1216b 5-EM + K1213 AU N=13 (FINAL PRIMARY)** | **5 EM + AU refined** | **−0.071** | **0.817** | **−0.24** | **13** |

**The institutional-ownership primary rho collapses from +0.441 to
−0.071** after refining all 5 EM pooled fits — a 1.16-σ swing to the
wrong side of zero (Harvey t = −0.24). The decay is not monotone: most
of the loss happens specifically when CH + ID refined `θ_rel` ≈ 1.5–1.9
replace canonical 0.3 / 0.24, because CH/ID have LOW
`institutions_pct_mean` (0.157, 0.154) yet end up with HIGH `θ_rel`,
breaking the rank concordance that drove +0.44 at K1172 baseline.

### Refined 5-EM theta_rel vs canonical

| Market | Canon θ_rel | Refined θ_rel | Shift | Source |
|---|---|---|---|---|
| AU | 0.150 | 1.476 | 9.8× | K1213 basin-B best-LL |
| BR | 1.887 | 2.691 | 1.4× | K1216 refined (NM) |
| CH | 0.304 | 1.469 | 4.8× | K1216b refined (NM) |
| ID | 0.238 | 1.917 | 8.1× | K1216b refined (NM) |
| IN | 1.170 | 3.077 | 2.6× | K1216 refined (NM) |
| MX | 1.202 | 1.845 | 1.5× | K1216 refined (NM) |

All 5 EM markets refined upward to `θ_rel ∈ [1.5, 3.1]`. Canonical
low-`θ_rel` EM pools (AU/CH/ID) were even further trapped (4.8×–9.8×)
than the initially-off-ladder ones (BR/IN/MX at 1.4×–2.6×).

---

## Final verdict

### `ALL_5_EM_FRAGILE`

All 5 EM markets in the K1168/K1172/K1171 panel (BR, IN, MX, AU, CH, ID)
show the same optimizer pathology. The canonical pooled MLE is NOT a
local maximum of the likelihood under shared-MIDAS + stock-FE-GJR — it
is a numerical artefact of the single-point default initialization.

Two implications for Paper 2 §5:

1. **The EM above-ladder narrative based on K1168 / K1172 canonical
   θ_rel is a universal numerical artefact.** Once every EM pool is
   properly multistart-refined, the EM cluster is NOT a cleanly
   `θ_rel > 1` shelf: refined values span 1.47 (CH) to 3.08 (IN) with
   no stable ordering.
2. **The institutional-ownership primary Spearman is not significant**
   under a faithful global optimum. The N=13 primary ρ is −0.071
   (p=0.82, Harvey t=−0.24). K1172 / K1173 / K1211 claims that rely on
   ρ = +0.44 or the AU-outlier / EM-above-ladder pattern should be
   retracted or heavily qualified. The effect *sign* at per-market
   level survives (HAC t ≥ 2.5 everywhere), but the *cross-market*
   ordering relationship does not.

### Comparison to the CH_ID_EXCEPTIONS hypothesis

The brief flagged a possible "CH_ID_EXCEPTIONS" outcome where low-θ_rel
EM would resist the pathology. Actually observed:

| Market | Canon θ_rel | Refined θ_rel | Fragility |
|---|---|---|---|
| CH | 0.304 | 1.469 | FRAGILE +597.94 |
| ID | 0.238 | 1.917 | FRAGILE +365.36 |

Low `θ_rel` did NOT protect the pool — it made the fragility *worse*
(higher relative shift). The pattern is: under the shared-MIDAS + stock-
FE-GJR spec, every EM pool has a high-θ basin with strictly higher LL
than the "natural" default-init basin, and only aggressive multistart
search finds it.

---

## Outputs

| File | Purpose |
|---|---|
| `k1216b.py` | Runner |
| `k1216b_results.json` | Full per-market + 5-EM Spearman rebuild |
| `k1216b_per_market_summary.csv` | One row per market: canon vs refined |
| `k1216b_multistart_results.csv` | 200 rows (100 starts × 2 markets) |
| `k1216b_CH_basin_hist.png` | CH 100-start θ_EAV histogram, two basins marked |
| `k1216b_ID_basin_hist.png` | ID 100-start θ_EAV histogram, two basins marked |
| `k1216b_5em_trajectory.png` | Full K1165 → K1216b primary ρ evolution |
| `run.log` | Complete stdout from the multistart fits |

---

## Rigour checklist

- Seed: base `42`; 100 starts `43..142`; DE seed `GLOBAL_SEED + 7`; K-means seed `42`.
- Bounds: identical to K1168 (CH) and K1172 (ID); no silent widening.
- Lookahead: inherited — `_pooled_negll` shifts `VIX²_{t-1}` and `EAV_{i,t-1}`.
- No data refetch; same parquet files as K1168 / K1172.
- Penalty-trap guard: reject fits with `res.fun > 1e11` or `−res.fun ≤ 1000`.
- DE penalty-wall returns (`LL = −1e13`) excluded from the sensitivity delta
  metric but reported in the JSON for transparency.
- No rewrite of K1216 helpers — imported by file path via
  `importlib.util.spec_from_file_location`.
- Worktree-only outputs: `experiments/k1216b/` (no shared-state writes).

---

## References

- K1168 `experiments/k1168/k1168_pooled_by_market.json` (canonical CH)
- K1171 `experiments/k1171/k1171_results.json` (canonical AU, inst_pct_mean)
- K1172 `experiments/k1172/k1172_pooled_by_market.json` (canonical ID)
- K1172 `experiments/k1172/k1172_results.json` (N=12 baseline Spearman)
- K1213 `experiments/k1213/` (AU multistart, refined `θ_rel = 1.476`)
- K1216 `experiments/k1216/` (BR/IN/MX multistart, shared optimization helpers)
- knowledge.json `item_id = 5cf52ce6` (K1216 WIDESPREAD_FRAGILITY)
- knowledge.json `item_id = e4d376ad` (K1213 AU ABOVE_LADDER_OVERTURNED)
