# K1262 Part B: Softer Detector Recompute of K1261 Raw Results

**Date**: 2026-04-27 19:53:04
**Source**: `/Users/yhlai0911/Desktop/volpred-research/experiments/k1261/k1261_results.json` (K1261 Phase 1 raw aggregates) + `/Users/yhlai0911/Desktop/volpred-research/paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json` (K827v3 VT 500-MC baseline).

## Detector definitions

1. **Strict (K1261 Phase 1)**: Sharpe drop > 50% from 10% baseline AND kurt > 10 AND vol amp > 50%.
2. **Softer (kurt-weak)**: Sharpe drop > 50% AND kurt > 1 AND vol amp > 50%. Loosens the kurtosis criterion to match P5 paper's softer threshold criterion.
3. **P5-style (Sharpe-only)**: Sharpe sign flip OR Sharpe drop > 70% from 10% baseline. Pure strategy-performance criterion (no kurt or vol amp required).

## Critical Adoption Table

| Treatment | Strict (K1261) | Softer (kurt-weak) | P5-style (Sharpe-only) |
|---|:---:|:---:|:---:|
| VT_baseline | 100% | 100% | 70% |
| TF | 20% | 20% | 20% |
| MR | 50% | 50% | 20% |
| NoiseControl | null | null | null |

## Calibration check

P5 paper reports VT critical adoption = 70%. The softer (kurt-weak) detector applied to VT_baseline is the calibration target. Acceptable range: ±20% adoption (i.e. 50% / 70% / 80% / 100%).

- **Softer (kurt-weak) → VT_baseline**: 100% 
  (calibration check: see verdict.md for pass/fail interpretation)
- **P5-style → VT_baseline**: 70%

## Cross-link

- K1261 raw input: `experiments/k1261/k1261_results.json`
- K827v3 VT 500-MC baseline: `paper/vt-crowding-abm/experiments/k827v3_abm_fixed_liquidity_results.json`
- Phase 2 sweep raw: `experiments/k1262/k1262_results.json`
- Phase 2 grid output: `experiments/k1262/k1262_threshold_matrix.md`
- Phase 2 verdict: `experiments/k1262/k1262_verdict.md`
