# K1100e: N=13 Cross-Asset λ_L Threshold Test

**Status: COMPLETE — H1 CONFIRMED**
**Date: 2026-04-17**
**Parent: K1100c (MIXED), K1100b (5 pairs NULL)**

## Motivation

K1100c found Scenario C (MIXED): SPY-TLT Joe DM=+10.36, SPY-GLD Joe=+7.66, but equity-equity all NULL. The λ_L threshold hypothesis emerged: the Joe copula's upper-tail advantage only materializes when lower-tail dependence is low (cross-asset pairs), not when it is high (equity-equity crash co-movement).

K1100e formally tests H1 with N=13 pairs across 5 asset classes, providing adequate statistical power for Spearman correlation test.

## Hypothesis

**H1**: Spearman(λ_L, DM_Joe-vs-DCC) < 0 with N=13 pairs, p < 0.05 (one-sided)

Low λ_L → asymmetric tail structure → Joe captures divergence → positive DM
High λ_L → symmetric crash co-movement → Joe no advantage → DM ≤ 0

## Data

- Source: yfinance daily
- Period: 2005-01-04 to 2026-04-10 (5350 days)
- OOS: 2013-06-01 to 2026-04-10 (~3200 days per pair)
- Marginal: A4f-VIX GARCH (GLD/SLV use GVZ)
- Window: 1250 days, refit every 63 days
- MC paths: 5000/day, seed=42

## 13 Pairs

| Pair | Asset Class | λ_L | DM_Joe | Harvey |
|------|-------------|-----|--------|--------|
| SPY-QQQ | equity-equity | 0.589 | +1.654 | no |
| SPY-IWM | equity-equity | 0.401 | -2.125 | no |
| SPY-XLF | equity-equity | 0.465 | -1.023 | no |
| SPY-TLT | equity-bond | 0.009 | +10.292 | YES*** |
| SPY-IEF | equity-bond | 0.019 | +7.613 | YES*** |
| SPY-TIP | equity-bond | 0.014 | +5.592 | YES*** |
| SPY-GLD | equity-commodity | 0.038 | +7.692 | YES*** |
| SPY-SLV | equity-commodity | 0.023 | +3.516 | YES*** |
| SPY-USO | equity-commodity | 0.047 | +3.518 | YES*** |
| SPY-UUP | equity-fx | 0.012 | +7.092 | YES*** |
| SPY-FXE | equity-fx | 0.039 | +6.984 | YES*** |
| SPY-LQD | equity-credit | 0.020 | +4.584 | YES*** |
| SPY-HYG | equity-credit | 0.174 | -0.020 | no |

## Formal Spearman Test

**Spearman(λ_L, DM_Joe)**: ρ = -0.791, p-two-sided = 0.001, p-one-sided(H1) = **0.001**

**H1 CONFIRMED** at p < 0.001 (one-sided).

**Spearman(λ_L, DM_SkewT)**: ρ = -0.841, p-one-sided = **0.000**

## Harvey |t|>3.0 Pass Count

| Asset Class | Pass/Total |
|-------------|-----------|
| equity-equity | 0/3 |
| equity-bond | 3/3 |
| equity-commodity | 3/3 |
| equity-fx | 2/2 |
| equity-credit | 1/2 |
| **Total** | **9/13** |

Note: SPY-HYG (high-yield, λ_L=0.174) is the exception in equity-credit — HYG has higher equity co-movement than investment-grade LQD, consistent with theory.

## Models

- M1: DCC-A4f-ASYM (baseline)
- M5: Copula-Joe-A4f-ASYM (main test)
- M4: Copula-SkewT-A4f-ASYM (secondary, also confirms H1)

## Outputs

- `k1100e_results.json` — full results for all 13 pairs
- `dm_vs_lambdaL_N13.png` — scatter plot: DM vs λ_L by asset class
- `k1100e_dm_heatmap.png` — DM heatmap 13 pairs × 2 models
- `run.log` — execution log

## Scenario: CONFIRMED

The λ_L threshold hypothesis is formally confirmed:
- Spearman ρ = -0.791, p = 0.001 (one-sided)
- Clear separation: equity-bond/commodity/FX (low λ_L) all PASS; equity-equity (high λ_L) all NULL
- 9/13 pairs Harvey |t|>3.0

## Paper 3 Implication

**SUPPORT: Publish asset-class-specific copula claim**

The K1100c coincidence is NOT random. K1100e with N=13 provides definitive evidence:
- Asset class determines λ_L which determines copula advantage
- Joe copula is not universally better than DCC — it is specifically better for cross-asset pairs with low lower-tail dependence
- This is the mechanism: stocks fly together in crashes (high λ_L), but diverge from bonds/commodities/FX (low λ_L)
- Joe's upper-tail focus correctly models this divergence structure

### Anti-lookahead verification
- Marginals: A4f uses x_{t-1} to forecast h_t (τ=θ₀+θ₁·x²_{t-1})
- Copula params from training window ending at t-1
- No same-day signal used

## Runtime

Total: ~4800 seconds (~80 minutes for 13 pairs × 3 models × ~3200 OOS days)

## References

- Joe (1997). Multivariate Models and Dependence Concepts. Chapman&Hall.
- Hansen (1994). Autoregressive Conditional Density Estimation. IER 35(3).
- Harvey (1997). Testing the Equality of Prediction Mean Squared Errors. IJFE 2(4).
- Patton (2006). Modelling asymmetric exchange rate dependence. IER 47(2).
- K1100c (2026-04-17): 5 pairs MIXED, Joe sig for cross-class pairs.
- K1100b (2026-04-13): 5 pairs all NULL (symmetric copulas).
