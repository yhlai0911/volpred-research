# K1262 Part C: Threshold Matrix (scaling × window) under Softer Detector

**Date**: 2026-04-27 19:53:04
**Detector**: Softer (kurt-weak) — Sharpe drop > 50% AND kurt > 1 AND vol amp > 50%

Cell format: `TF: <crit> / MR: <crit>`. `null` = no threshold detected at any adoption ≥10%.

## Critical Adoption Matrix

| Scaling \ Window | 10 | 22 | 60 |
|---:|:---:|:---:|:---:|
| 1 | TF: 70% / MR: 70% | TF: 70% / MR: 70% | TF: 70% / MR: 70% |
| 3 | TF: 30% / MR: 50% | TF: 30% / MR: 50% | TF: 30% / MR: 50% |
| 5 | TF: 30% / MR: 50% | TF: 20% / MR: 50% | TF: 20% / MR: 50% |
| 10 | TF: 20% / MR: 50% | TF: 20% / MR: 50% | TF: 20% / MR: 50% |

## Same matrix under STRICT detector (Phase 1)

| Scaling \ Window | 10 | 22 | 60 |
|---:|:---:|:---:|:---:|
| 1 | TF: 70% / MR: 70% | TF: 70% / MR: 70% | TF: 70% / MR: 70% |
| 3 | TF: 50% / MR: 50% | TF: 50% / MR: 50% | TF: 30% / MR: 50% |
| 5 | TF: 50% / MR: 50% | TF: 30% / MR: 50% | TF: 30% / MR: 50% |
| 10 | TF: 70% / MR: null | TF: 20% / MR: 50% | TF: 20% / MR: 50% |

## Same matrix under P5-STYLE (Sharpe-only) detector

| Scaling \ Window | 10 | 22 | 60 |
|---:|:---:|:---:|:---:|
| 1 | TF: 20% / MR: 20% | TF: 20% / MR: 20% | TF: 20% / MR: 20% |
| 3 | TF: 20% / MR: 20% | TF: 20% / MR: 20% | TF: 20% / MR: 20% |
| 5 | TF: 20% / MR: 20% | TF: 20% / MR: 20% | TF: 20% / MR: 20% |
| 10 | TF: 20% / MR: 20% | TF: 20% / MR: 20% | TF: 20% / MR: 20% |

## Cross-link

- Phase 2 raw: `experiments/k1262/k1262_results.json`
- Softer detector table: `experiments/k1262/k1262_softer_detector_table.md`
- Phase 2 verdict: `experiments/k1262/k1262_verdict.md`
