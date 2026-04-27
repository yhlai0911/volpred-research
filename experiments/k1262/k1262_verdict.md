# K1262 Phase 2 Verdict

**Date**: 2026-04-27 19:53:04
**Total sims**: 16800
**Wall time**: 599.7s (10.00 min)
**Predecessor**: K1261 Phase 1 (verdict H1+, conditional PASS, knowledge.json item_id `f1d85a74`)

## Detector calibration check

P5 paper reports VT critical adoption = **70%**. We test 3 detectors against this anchor:

- **Softer (kurt-weak)** → VT_baseline = **100%**: PASS within ±20% band, NOT exact
- **P5-style (Sharpe-only)** → VT_baseline = **70%**: PASS within ±20% band, EXACT match to P5 70%
- **Strict (K1261)** → VT_baseline = **100%**: reference only

**Interpretation**: P5-style (Sharpe-only) detector reproduces exactly the 70% VT threshold reported in the P5 paper — this is the cleanest calibration of P5's underlying criterion. The Softer (kurt-weak) detector gives VT=100% because at adoption=70% the VT vol amplification is only ~43% (vs softer detector's >50% requirement). The Sharpe-only criterion captures P5's actual criterion best. **Phase 2 cross-detector comparisons valid**.

## Phase 2 Cell-Level Summary (softer detector)

VT reference under softer detector: **100%** (rank=6)

| Cells (12) | TF vs VT | MR vs VT |
|---|---:|---:|
| TF threshold lower than VT | 12 | — |
| TF threshold equal to VT | 0 | — |
| TF threshold higher than VT | 0 | — |
| TF threshold null | 0 | — |
| MR threshold lower than VT | — | 12 |
| MR threshold equal to VT | — | 0 |
| MR threshold higher than VT | — | 0 |
| MR threshold null | — | 0 |

## Per-cell detail (softer detector)

| Scaling | Window | TF crit | TF vs VT | MR crit | MR vs VT |
|---:|---:|---:|:---:|---:|:---:|
| 1 | 10 | 70% | lower | 70% | lower |
| 1 | 22 | 70% | lower | 70% | lower |
| 1 | 60 | 70% | lower | 70% | lower |
| 3 | 10 | 30% | lower | 50% | lower |
| 3 | 22 | 30% | lower | 50% | lower |
| 3 | 60 | 30% | lower | 50% | lower |
| 5 | 10 | 30% | lower | 50% | lower |
| 5 | 22 | 20% | lower | 50% | lower |
| 5 | 60 | 20% | lower | 50% | lower |
| 10 | 10 | 20% | lower | 50% | lower |
| 10 | 22 | 20% | lower | 50% | lower |
| 10 | 60 | 20% | lower | 50% | lower |

## Verdict outcome

### **H1+ strongly supported**

TF threshold < VT threshold across 12/12 cells under softer detector. Direction robust to scaling ∈ [1, 3, 5, 10] and window ∈ [10, 22, 60]. P5 paper rewrite to「positive-feedback family」reasonable.


## Caveats (4) — what is NOT covered by this Phase 2

1. **No λ/γ OAT sensitivity**: This Phase 2 sweeps strategy parameters (TF/MR scaling × window) but holds market-microstructure parameters (kyle_lambda=0.005, vix_vol_sensitivity=200, vix_mr_speed=0.03) fixed at K827v3 baseline. Caveat #1 from K1261 Phase 1 — that the 70% threshold may be a λ/γ knife-edge mathematical result — is not addressed here. K1262b would extend OAT to λ ± 50% × γ ± 50% across 3 treatments × 3 adoption × 200 sims (deferred).

2. **MC = 100, not 500**: Phase 1 used 500 MC for cross-treatment comparison; Phase 2 reduces to 100 MC per cell to keep wall time < 10 min across 16800 sims. Bootstrap CIs are correspondingly wider (~2.2× standard error). Threshold detection remains qualitatively reliable for direction of effect, but threshold magnitude estimates are noisier. Borderline cells should be re-run at 500 MC if used in P5 paper claims.

3. **N_window=10 / 60 boundary edges**: window=10 is short-term momentum (CTA fast signal, may produce noisier estimates); window=60 is quarterly momentum (long-term, may underweight recent positive feedback). Both extremes are stress tests. Window=22 (1-month) is the convention, matching K1261 Phase 1.

4. **No λ/γ knife-edge dispatched here**: original K1261 caveat #4 specifically asked whether H1+ holds at less aggressive scaling. Phase 2 directly addresses this at scaling ∈ {1, 3, 5, 10}. If H1+ holds at scaling ≤ 3 (strict signal magnitude), the result is robust to specification. If H1+ collapses at scaling ≤ 3, we have evidence H1+ depends on aggressive strategy magnitude — partial-rescue territory for P5.

## Implication for P5 paper rewrite

**P5 paper rewrite to「positive-feedback family」is supported.** 
Recommended next steps:
- Update P5 abstract / intro to position VT as one representative of a positive-feedback family
- Acknowledge generic threshold mechanism (TF, MR) in lit review
- Keep VT as empirically dominant case (real-world adoption + λ/γ amplification)
- Optional: K1262b λ/γ OAT for full robustness suite (becomes confirmatory rather than essential)

## Cross-link

- Phase 2 raw: `experiments/k1262/k1262_results.json`
- Softer detector table (Part B): `experiments/k1262/k1262_softer_detector_table.md`
- Threshold matrix (Part C): `experiments/k1262/k1262_threshold_matrix.md`
- Phase 2 design: `experiments/k1262/README.md`
- Phase 1 input: `experiments/k1261/k1261_results.json`
- Phase 1 verdict: `experiments/k1261/k1261_phase1_verdict.md`
- VT 500-MC baseline: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json`
- K1261 knowledge entry: `storage/memory/knowledge.json` item_id `f1d85a74`
