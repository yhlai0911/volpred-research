# K989: MF2-VIX + VIX² Convexity Synthesis

## Motivation
This experiment combines two recent ★-level findings:
- **K970**: MF2-VIX (σ²=τ_VIX×g_GJR) improved GJR QLIKE by 9.55%, DM t=2.94
- **K987**: VIX² quadratic OOS R²=0.258 vs VIX linear 0.202, confirming convex VIX-vol relationship
- **K986**: LASSO 100% selected VIX² as important factor

**Hypothesis**: Adding VIX² convexity to the MF2 tau component may combine both advantages.

## Method

### Data
- SPY and VIX from yfinance, 2006-01-01 to 2026-04-07
- IS: 2006-2018 (3269 obs), OOS: 2019-2026 (1824 obs)
- Target: r² (daily squared return, in percentage-squared units)
- All tau components use shift(1) to avoid lookahead

### Models Tested

| Model | tau Formula | Calibration |
|-------|-----------|-------------|
| **GJR** (baseline) | Standard GJR-GARCH(1,1) | arch package |
| **MF2-VIX** (K970) | τ = (VIX_{t-1}/√252)² | No calibration |
| **MF2-VIX²** | τ = α + β₁·VIX²/252 + β₂·VIX⁴/252² | IS OLS on r² |
| **MF2-Poly** | τ = a + b₁·VIX/√252 + b₂·VIX²/252 | IS OLS on r² |
| **MF2-Piecewise** | τ = (VIX/√252)² × (1 + δ·max(VIX-20,0)) | IS grid search |
| **GJR-X** | h_t = ω + α·r²_{t-1} + γ·r²I + β·h_{t-1} + δ·VIX²/252 | MLE (L-BFGS-B) |

### Evaluation
- QLIKE, MSE, OOS R², MZ regression
- DM test (all models vs GJR and vs MF2-VIX)
- VaR backtesting (1%, 5%) with ES

## Key Results

### QLIKE Rankings (lower = better)
| Model | QLIKE | Improvement vs GJR | vs MF2-VIX |
|-------|-------|-------------------|------------|
| MF2-Piecewise | 0.8486 | 9.54% | +0.01% |
| MF2-VIX | 0.8487 | 9.52% | baseline |
| MF2-VIX² | 0.8549 | 8.86% | -0.73% |
| GJR-X | 0.8751 | 6.71% | -3.11% |
| MF2-Poly | 0.8923 | 4.87% | -5.14% |
| GJR | 0.9380 | baseline | — |

### DM Test Results
- **No VIX² variant significantly beats MF2-VIX** (all |t| < 3.0)
- MF2-VIX vs MF2-Poly: t = -3.783 (Poly significantly **worse**)
- MF2-VIX vs GJR-X: t = -4.449 (GJR-X significantly **worse**)
- MF2-Piecewise ≈ MF2-VIX (delta calibrated to near-zero: 0.001)

### VaR Performance
- MF2-VIX best at 1% VaR (21 violations, Kupiec p=0.526)
- GJR-X best OOS R² (0.303) and MZ slope (0.934) but worse QLIKE

## Conclusions

1. **VIX² convexity does NOT improve MF2-VIX in the QLIKE metric.** The simple (VIX/√252)² tau already captures the convexity through its squared transformation.

2. **Piecewise delta ≈ 0**: The grid search found optimal delta = 0.001, meaning no additional convexity kick above VIX=20 improves over the base MF2-VIX. The squared VIX already has inherent convexity.

3. **MF2-VIX² and MF2-Poly are worse**: Adding extra polynomial terms introduces noise without improving forecasts. OOS R² is negative for both (-0.82 and -0.99), indicating overfitting of the tau component.

4. **GJR-X has best OOS R² (0.303) and MZ slope (0.934)** but worse QLIKE (0.875 vs 0.849). This is consistent with the two-component decomposition being better at capturing the log-variance dynamics that QLIKE measures.

5. **MF2-VIX remains the best tau specification.** The K970 finding stands: the simple VIX-implied variance as tau is hard to beat. The VIX² nonlinearity found in K987 reflects the relationship between VIX levels and realized vol, but this is already captured by squaring VIX in the MF2 framework.

## Implications
- The VIX² convexity (K987) is a **descriptive finding** about the VIX-vol relationship, not a source of additional forecasting power beyond what MF2-VIX already uses
- Future improvements should focus on the short-run component (g_t) rather than trying to enhance tau
- GJR-X's higher MZ slope suggests that directly incorporating VIX² in the variance equation may be useful for point-forecast applications (where MSE matters more than QLIKE)

## Files
- `k989_mf2_vix2.py` — Main experiment script
- `k989_mf2_vix2_results.json` — Full results
- `k989_tau_comparison.png` — Long-run component comparison
- `k989_oos_comparison.png` — OOS forecast comparison

## References
- Conrad, C. & Engle, R. (2025). Two-component GARCH. J. Applied Econometrics.
- Patton, A.J. (2011). Volatility forecast comparison. J. Econometrics, 160(1).
- Harvey, C.R., Liu, Y., & Zhu, H. (2016). ...and cross-section. RFS.
