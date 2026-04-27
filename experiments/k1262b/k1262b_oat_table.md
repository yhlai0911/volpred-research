# K1262b OAT Threshold Table — P5-style detector

**Date**: 2026-04-27 20:52:12
**Detector**: P5-style (Sharpe sign flip OR Sharpe drop > 70% from 10% baseline)
**MC sims per cell**: 200
**Adoption levels tested**: [0.1, 0.3, 0.7, 1.0]
**TF/MR fixed**: scaling=10, window=22

## OAT cell definitions

| Cell label | kyle_lambda (λ) | vix_vol_sensitivity (γ) |
|---|---:|---:|
| `cell1_baseline` | 0.005 | 200.0 |
| `cell2_lambda_low` | 0.0025 | 200.0 |
| `cell3_lambda_high` | 0.0075 | 200.0 |
| `cell4_gamma_low` | 0.005 | 100.0 |
| `cell5_gamma_high` | 0.005 | 300.0 |

## Critical adoption threshold per (cell, treatment)

| OAT cell | VT_baseline | TF | MR | NoiseControl |
|---|:---:|:---:|:---:|:---:|
| `cell1_baseline` | 70% | 30% | 70% | null |
| `cell2_lambda_low` | 100% | 30% | 30% | null |
| `cell3_lambda_high` | 70% | 30% | null | null |
| `cell4_gamma_low` | 70% | 30% | 70% | null |
| `cell5_gamma_high` | 70% | 30% | 70% | null |

## Calibration check (success criterion 4)

- **Cell 1 baseline (λ=0.005, γ=200) VT_baseline threshold under P5-style detector**: **70%**
- **K1262 reference**: 70% (P5 paper anchor reproduced from K827v3 500-MC)
- **Status**: EXACT MATCH to K1262 calibration → P5-style detector reproduces VT=70% at MC=200 baseline.

## VT_baseline mean Sharpe per (cell, adoption)

| OAT cell | 10% | 30% | 70% | 100% |
|---|---:|---:|---:|---:|
| `cell1_baseline` | 0.510 | 0.475 | 0.084 | -0.274 |
| `cell2_lambda_low` | 0.499 | 0.499 | 0.349 | 0.068 |
| `cell3_lambda_high` | 0.507 | 0.460 | -0.108 | -0.396 |
| `cell4_gamma_low` | 0.499 | 0.474 | 0.146 | -0.210 |
| `cell5_gamma_high` | 0.508 | 0.471 | 0.046 | -0.285 |