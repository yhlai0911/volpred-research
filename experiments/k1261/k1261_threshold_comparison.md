# K1261 Phase 1 Cross-Treatment Threshold Comparison

**Date**: 2026-04-27 18:43:19
**Treatments**: VT_baseline (K827v3 stored), TF, MR, NoiseControl
**Adoption levels**: [0.0, 0.1, 0.2, 0.3, 0.5, 0.7, 1.0]
**MC sims (Phase 1 full)**: 500 per cell
**Total Phase 1 sims**: 10500
**Wall time (full pipeline)**: 132.3s (2.21 min)

## Pre-flight Sanity

| Treatment | Verdict | Wall (s) | NaN | Clamps | Reasons |
|---|---|---:|---:|---:|---|
| TF | PASS | 8.5 | 0 | 14458 | all checks OK |
| MR | PASS | 8.5 | 0 | 16532 | all checks OK |
| NoiseControl | PASS | 8.8 | 0 | 0 | all checks OK |

## Sharpe Ratio (mean across MC)

| Adoption | VT (K827v3) | TF | MR | NoiseControl |
|---:|---:|---:|---:|---:|
| 0% | null | null | null | null |
| 10% | 0.4675 | -0.8328 | -1.7714 | 0.5104 |
| 20% | 0.4956 | -3.1342 | -60.1559 | 0.5118 |
| 30% | 0.4664 | -3.2313 | 0.0000 | 0.4868 |
| 50% | 0.3357 | -0.7892 | -4.2151 | 0.4977 |
| 70% | 0.0844 | -2.7935 | -3.9388 | 0.5041 |
| 100% | -0.2670 | -2.6227 | -3.6876 | 0.4986 |

## Kurtosis (mean across MC)

| Adoption | VT (K827v3) | TF | MR | NoiseControl |
|---:|---:|---:|---:|---:|
| 0% | -0.0027 | -0.0027 | -0.0027 | -0.0027 |
| 10% | -0.0128 | -0.0007 | -0.0057 | -0.0054 |
| 20% | 0.0028 | 11.2530 | -1.9322 | -0.0048 |
| 30% | -0.0037 | 12.8241 | NaN | 0.0024 |
| 50% | 0.0563 | 1412.2719 | 42.7639 | -0.0035 |
| 70% | 1.4121 | 69.8972 | 17.0072 | -0.0044 |
| 100% | 61.3526 | 31.3935 | 17.9149 | 0.0011 |

## Annual Volatility (mean across MC)

| Adoption | VT (K827v3) | TF | MR | NoiseControl |
|---:|---:|---:|---:|---:|
| 0% | 0.1601 | 0.1601 | 0.1601 | 0.1601 |
| 10% | 0.1601 | 0.1808 | 0.1824 | 0.1599 |
| 20% | 0.1614 | 0.8518 | 5.8537 | 0.1596 |
| 30% | 0.1661 | 2.0433 | NaN | 0.1600 |
| 50% | 0.1902 | 241.9481 | 46.6244 | 0.1600 |
| 70% | 0.2285 | 8.6233 | 15.5201 | 0.1599 |
| 100% | 0.3508 | 16.4169 | 31.2052 | 0.1598 |

## VIX Spike % (>30, mean across MC)

| Adoption | VT (K827v3) | TF | MR | NoiseControl |
|---:|---:|---:|---:|---:|
| 0% | 0.0007 | 0.0007 | 0.0007 | 0.0007 |
| 10% | 0.0002 | 0.3355 | 1.9093 | 0.0018 |
| 20% | 0.0022 | 98.4987 | 98.8100 | 0.0008 |
| 30% | 0.0047 | 98.9531 | 98.9969 | 0.0012 |
| 50% | 0.3411 | 99.0447 | 99.0456 | 0.0019 |
| 70% | 16.1581 | 99.0595 | 99.0601 | 0.0002 |
| 100% | 90.0245 | 99.0722 | 99.0726 | 0.0017 |

## Threshold Detection (per treatment)

Critical adoption = first level (≥10%) where ALL three hold:
- (a) Sharpe drop > 50% from treatment-specific 10% baseline
- (b) Kurtosis > 10
- (c) Vol amplification > 50% from treatment-specific 10% baseline

| Treatment | Critical Adoption | Note |
|---|---|---|
| VT (K827v3 stored) | 100% | |
| TF | 20% | |
| MR | 50% | |
| NoiseControl | null (no threshold) | |
