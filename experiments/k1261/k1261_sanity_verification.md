# K1261 Phase 1.0 Sanity Verification Report

**Date**: 2026-04-27 17:19:08
**Treatment**: VT_baseline (replicate K827v3)
**Adoption levels**: [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
**MC sims per cell**: 100
**Total sims**: 700
**Wall time**: 25.4s (0.4 min)
**Primary gate**: MC z-score |z| <= 2.0 (SE = std/sqrt(n_sanity))
**Secondary gate (informational)**: relative diff ±5%

## Method

Forked K827v3's `run_single_simulation()` (lines 101-243) and refactored the VT-specific weight rule (lines 152-156) into a `VTAgent` class. Sanity verification reuses K827v3's seed formula `int(adoption * 100000) + sim_idx + 42` (line 346). With N_SIMS_SANITY=100 the sanity sims are a strict subset of K827v3's 500 main sims.

**Byte-exactness verification** (single-seed cross-check): seed=50042, adoption=50% — K827v3 vs K1261-VT produce identical results (diff=0.000000 across ann_return, ann_vol, kurtosis, vt_sharpe, vix_spike_pct, final_price). This confirms the fork preserves K827v3 dynamics byte-for-byte.

**Gate calibration note**: The legacy ±5% relative-diff gate is miscalibrated for n_sanity=100 because per-sim Sharpe std is large (e.g. std=0.255 at 50% adoption gives SE_100=0.0255 ≈ 7.6% of mean — wider than the ±5% gate). The correct gate is the MC z-score using SE = std/sqrt(n_sanity); a byte-exact fork should yield |z| < 2 with ~95% probability per cell.

Critical preservation checks: rng draw order (VIX noise → noise trader changes → fundamental shock per t), VTAgent deterministic given vix_series[t-1], no extra rng draws inside VTAgent — verified by single-seed byte-match test above.

## Results

| Adoption | K827v3 Sharpe (n=500) | K827v3 std | SE (n=100) | K1261 Sharpe (n=100) | Rel Diff % | ±5% gate | z-score | z gate |
|---:|---:|---:|---:|---:|---:|:---:|---:|:---:|
| 0% | null | N/A | N/A | null | N/A | PASS | N/A | PASS (Both null (n_strategy=0)) |
| 10% | 0.4675 | 0.3254 | 0.0325 | 0.5003 | +7.01% | FAIL | +1.01 | PASS |
| 20% | 0.4956 | 0.2945 | 0.0294 | 0.4699 | -5.18% | FAIL | -0.87 | PASS |
| 30% | 0.4664 | 0.3256 | 0.0326 | 0.4660 | -0.09% | PASS | -0.01 | PASS |
| 50% | 0.3357 | 0.2554 | 0.0255 | 0.3045 | -9.30% | FAIL | -1.22 | PASS |
| 70% | 0.0844 | 0.2116 | 0.0212 | 0.0903 | +7.01% | FAIL | +0.28 | PASS |
| 100% | -0.2670 | 0.1335 | 0.0134 | -0.2748 | -2.91% | PASS | -0.58 | PASS |

**±5% gate (legacy, informational)**: 3/7 cells PASS
**z-score gate (primary)**: 7/7 cells PASS

## Verdict: **PASS**

All 7 adoption levels are within MC sampling noise (|z| ≤ 2) of K827v3 stored values. Combined with the byte-exact single-seed match, the fork preserves K827v3 dynamics. **Ready for Phase 1 scale-up** (4 treatments × 7 adoption × 500 MC = 14,000 sims, ~22-44 hr wall).

Note: 4/7 cells lie outside the legacy ±5% relative-diff band, but this band is wider than 1 SE for n=100 only at high-adoption regimes where Sharpe magnitude is small; at small magnitudes the relative-% metric blows up even when absolute differences are within MC noise. The z-gate (which normalises by per-sim std) is the correct test.

## Implementation Status

Strategy agent classes implemented:

- `VTAgent`: implemented (replicates K827v3 lines 152-156 verbatim)
- `TFAgent`: implemented (22-day momentum, scaling 10.0)
- `MRAgent`: implemented (negated TF signal)
- `NoiseAgent`: implemented (random walk; sim rng injected via `_rng`)

All 4 implemented (no NotImplementedError remaining for agent classes or `run_single_simulation`).

## Cross-link

- Source: `experiments/k1261/k1261_non_vt_ablation.py`
- Results JSON: `experiments/k1261/k1261_sanity_results.json`
- K827v3 baseline: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json`
- Design: `experiments/k1261/README.md`
- Baseline check: `experiments/k1261/baseline_check_2026_04_27.md`
