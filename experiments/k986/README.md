# K986: Adaptive Multi-Factor HAR — Dynamic Factor Selection

## Problem & Motivation
Standard HAR-RV uses 3 fixed components (1d, 5d, 22d squared returns). Prior experiments (K969, K987) showed that additional vol proxies (especially VIX²) improve forecasting. This experiment tests whether **dynamic factor selection** via regularization (LASSO/Ridge/ElasticNet) outperforms fixed-factor HAR models for daily volatility prediction.

Inspired by Cinquetti et al. (FoFI 2026) who use 287 high-frequency factors with adaptive selection, but implemented with 10 daily-frequency vol proxies.

## Method
- **10 candidate factors** (all shift(1) to avoid lookahead):
  1. r² (1d), r² (5d), r² (22d) — standard HAR
  2. |r| (absolute return)
  3. Parkinson range-based vol
  4. Garman-Klass vol
  5. VIX/sqrt(252) (implied vol, daily)
  6. VIX² (quadratic, per K987)
  7. Leverage term (asymmetric)
  8. r² (66d, quarterly)

- **7 models compared**:
  - HAR-3: Standard HAR (OLS, 3 factors)
  - HAR-10: All 10 factors (OLS)
  - HAR-LASSO: LassoCV automatic selection
  - HAR-Ridge: Ridge regression (manual CV)
  - HAR-ElasticNet: ElasticNetCV (L1+L2)
  - Rolling-LASSO: Refit every 252 days, window=3000
  - GJR-GARCH: Parametric baseline

- **Data**: SPY + VIX (yfinance), 2006-04-10 to 2026-04-06
- **IS**: 2006-2018 (3204 days), **OOS**: 2019-2026 (1824 days)
- **Evaluation**: QLIKE, MSE, OOS R², MZ regression, DM test
- **Seed**: 42

## Key Results

### OOS Performance (ranked by MSE)

| Model | MSE | OOS R² | QLIKE | MZ R² | DM vs HAR-3 |
|-------|-----|--------|-------|-------|-------------|
| GJR-GARCH | 2.01e-07 | **0.4653** | **-8.527** | 0.4707 | -7.24*** |
| HAR-Ridge | 2.80e-07 | 0.2574 | -7.453 | 0.2711 | +3.62*** |
| HAR-LASSO | 2.82e-07 | 0.2505 | +2.302 | 0.2519 | +4.77*** |
| HAR-ElasticNet | 2.82e-07 | 0.2505 | +2.301 | 0.2519 | +4.77*** |
| HAR-10 (OLS) | 2.83e-07 | 0.2492 | +2.447 | 0.2509 | +4.83*** |
| Rolling-LASSO | 2.87e-07 | 0.2392 | -2.670 | 0.2398 | +3.70*** |
| HAR-3 | 3.05e-07 | 0.1895 | -8.194 | 0.1925 | baseline |

### Factor Selection (Rolling LASSO, 8 refits)
| Factor | Selection Freq | Interpretation |
|--------|---------------|----------------|
| r²(1d) | 8/8 (100%) | Core — always selected |
| r²(5d) | 8/8 (100%) | Core — always selected |
| |r|(1d) | 8/8 (100%) | Core — complementary to r² |
| GK | 8/8 (100%) | Core — range-based info valuable |
| VIX² | 8/8 (100%) | Core — confirms K987 finding |
| Leverage | 8/8 (100%) | Core — asymmetry matters |
| r²(66d) | 8/8 (100%) | Core — quarterly component |
| VIX/√252 | 7/8 (87.5%) | Near-core |
| r²(22d) | 6/8 (75.0%) | Sometimes redundant with r²(66d) |
| Parkinson | 5/8 (62.5%) | Partially redundant with GK |

## Conclusions

1. **GJR-GARCH dominates all HAR variants by QLIKE** (DM = -7.24, p < 0.001). This is consistent with the principle that GARCH uses r² as its natural target and exploits conditional heteroskedasticity structure that linear HAR cannot capture.

2. **Multi-factor HAR improves OOS R² over HAR-3** (0.19 → 0.25-0.26 by MSE), but **worsens QLIKE** due to occasional negative predictions. Ridge is best among HAR variants (OOS R² = 0.2574) because its strong shrinkage prevents negative predictions.

3. **LASSO selects ALL 10 factors** — no sparsity in the static case. This means all vol proxies contribute, but with varying importance. In the rolling case, Parkinson and r²(22d) are occasionally dropped.

4. **VIX² is consistently selected** (100% across all 8 rolling LASSO refits), confirming K987's finding that the quadratic VIX term has genuine predictive power.

5. **Rolling LASSO does NOT outperform static LASSO** — adaptive refitting adds noise and slightly worsens OOS R² (0.2392 vs 0.2505). The factor structure is stable enough that static estimation suffices.

6. **Key limitation**: HAR with daily r² proxy has a ceiling (~0.25 OOS R²) because r² is a very noisy proxy for true volatility. GJR-GARCH's advantage (0.47 OOS R²) comes from its parametric structure, not from better factors.

## Files
- `k986_adaptive_har.py` — Main experiment script
- `k986_adaptive_har_results.json` — Full results
- `k986_factor_selection.png` — Rolling LASSO factor selection heatmap
- `k986_oos_comparison.png` — OOS comparison plots

## References
- Corsi (2009) — HAR-RV model
- Cinquetti et al. (FoFI 2026) — Multi-factor HAR with 287 HF factors
- Patton (2011) — QLIKE loss function
- Harvey (2016) — t>3.0 threshold
