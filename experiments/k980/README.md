# K980: Threshold GJR-GARCH with VIX Regime Switching

## Motivation
Standard GJR-GARCH uses a single set of parameters for all market conditions. If volatility dynamics differ between low-VIX and high-VIX regimes, a threshold model that switches all GARCH parameters based on VIX level could improve forecasts.

## Method
- **Threshold GJR-GARCH (TGJR)**: Two separate GJR-GARCH(1,1) models estimated on IS data split by VIX_{t-1} regime. OOS forecasts use VIX_{t-1} to select the active regime's parameters.
- **GJR + VIX Dummy**: Standard GJR with an additive dummy term delta * I(VIX_{t-1} > c)
- **Baseline**: Standard GJR-GARCH(1,1)
- Grid search over c in {14, 16, 18, 20, 22, 24}, selecting the c that minimizes IS QLIKE
- VIX is always lagged by 1 day (no lookahead)

## Data
- SPY + VIX from yfinance, 2006-01-05 to 2026-04-06 (5093 obs)
- IS: 2006-2018 (3269 obs), OOS: 2019-2026 (1824 obs)
- Target: r^2 (squared daily log returns)

## Key Findings

### Parameters differ significantly across regimes
With optimal threshold c=14:
| Parameter | Low VIX | High VIX | Ratio |
|-----------|---------|----------|-------|
| omega | 0.000017 | 0.000003 | 0.21 |
| alpha | 0.016 | 0.050 | 3.04 |
| gamma | 0.198 | 0.050 | 0.25 |
| beta | 0.302 | 0.899 | 2.97 |
| persistence | 0.418 | 0.974 | 2.33 |

Low-VIX regime has much lower persistence and higher leverage effect (gamma), while high-VIX regime has very high persistence -- volatility is more "sticky" during stressed periods.

### OOS: No improvement over baseline GJR
| Model | QLIKE | MSE | MZ R^2 |
|-------|-------|-----|--------|
| GJR | 1.4989 | 2.75e-7 | 0.272 |
| TGJR (c=14) | 1.5032 | 2.88e-7 | 0.239 |
| GJR+Dummy | 1.5048 | 2.87e-7 | 0.249 |

DM test: GJR vs TGJR p=0.748 (not significant). Neither TGJR nor the VIX dummy improves over baseline.

### Regime-conditional evaluation
- Low VIX (VIX < 14): TGJR wins (QLIKE 1.573 vs 1.645)
- High VIX (VIX >= 14): GJR wins (QLIKE 1.472 vs 1.490)

TGJR helps in calm markets but hurts in stressed markets, and since 85% of OOS days have VIX >= 14, the net effect is negative.

## Conclusion
**Null result.** While GARCH parameters clearly differ between VIX regimes (confirming regime-dependent dynamics), the two-regime threshold approach does not improve OOS forecasting. The problem is likely:
1. Separate regime estimation loses temporal continuity in h_t
2. The optimal IS threshold (c=14) may not be optimal OOS
3. Standard GJR already captures regime dynamics implicitly through its ARCH/leverage terms

This confirms that VIX information is better incorporated through multiplicative/long-component approaches (like MF-GARCH from K970) rather than discrete regime switching.

## References
- Chen, Liu & Gerlach (2011, Computational Statistics): TARMA with Bayesian variable selection
- Chen, Liu & So (2013, Computational Statistics): Threshold Asymmetric SV
- Patton (2011): Volatility forecast comparison using imperfect proxies

## Files
- `k980_threshold_garch.py` -- Main experiment script
- `k980_threshold_garch_results.json` -- Full results
- `k980_regime_parameters.png` -- Parameter comparison across regimes
- `k980_oos_comparison.png` -- OOS forecast comparison
