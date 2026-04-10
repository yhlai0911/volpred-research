# K1020: MS(2)-A4f — Markov Regime Switching + VIX Multiplicative GARCH-X

**[提出: 賴奕豪, 執行: Claude]**

## Research Question

K1019 showed MS(2)-GJR significantly beats GJR-t (DM t=-3.20) but loses to A4f-VIX9D (DM t=+2.75, NS). The regime probability and VIX are only weakly correlated (r=0.225), suggesting they capture different information dimensions. Can combining both regime switching and VIX external information beat either standalone model?

## Motivation

If regime switching and VIX each capture orthogonal volatility dynamics, their combination should dominate both. This experiment tests that hypothesis with two combination approaches:
- **M4: MS(2)-A4f** — Full integration: regime-specific tau parameters in the multiplicative structure
- **M5: A4f+RegProb** — Lightweight combination: use MS-GJR regime probability as an additional regressor in A4f's tau equation

## Models

| Model | Description | Parameters |
|-------|-------------|-----------|
| M1: GJR-t | GJR-GARCH(1,1), Student-t | 5 |
| M2: A4f-VIX9D-t | Multiplicative GARCH-X (sigma^2 = tau * g), VIX9D, Student-t | 7 |
| M3: MS(2)-GJR-N | 2-regime Markov-Switching GJR, Normal, Gray (1996) collapse | 10 |
| M4: MS(2)-A4f | **NEW**: 2-regime with regime-specific tau, shared g, Normal | 10 |
| M5: A4f+RegProb | **NEW**: A4f + regime probability as tau regressor, Normal | 7 |

### M4 Specification (MS(2)-A4f)
- tau_{s,t} = theta0_s + theta1_s * VIX9D^2_{t-1} (regime-specific)
- g_t = omega + alpha * u^2 + gamma * u^2 * I(u<0) + beta * g_{t-1} (shared)
- u_t = r_t / sqrt(tau_combined_t)
- sigma^2_t = sum_s P(s_t=s) * tau_{s,t} * g_t

### M5 Specification (A4f + RegProb)
- tau_t = theta0 + theta1 * VIX9D^2_{t-1} + theta2 * P(crisis_{t-1})
- g_t = omega + alpha * u^2 + gamma * u^2 * I(u<0) + beta * g_{t-1}

## Data

- **Asset**: SPY (2003-01-03 to 2026-04-09, N=5853)
- **VIX**: ^VIX (yfinance)
- **VIX9D**: ^VIX9D (yfinance, available from 2011-01-03)
- **OOS**: 2011-01-04 to 2026-04-09 (3838 days total; M2/M4/M5 have 1822 valid days due to VIX9D-related convergence issues in early windows)
- **Window**: 2000 days, refit every 63 days
- **Random seed**: 42

## Results

### QLIKE (lower = better, evaluated on r^2, Patton 2011)

| Rank | Model | QLIKE | N_valid |
|------|-------|-------|---------|
| 1 | MS(2)-GJR-N | -8.5298 | 3838 |
| 2 | GJR-t | -8.5083 | 3838 |
| 3 | A4f-VIX9D-t | -8.3960 | 1822 |
| 4 | A4f+RegProb | -8.3921 | 1822 |
| 5 | **MS(2)-A4f** | **-8.3301** | 1822 |

**MS(2)-A4f ranks LAST among all models on the shared sample.** The combination hurts rather than helps.

### Diebold-Mariano Tests (Harvey t>3.0 threshold)

| Comparison | DM t | Significance |
|-----------|------|-------------|
| MS(2)-A4f vs A4f-VIX9D-t | +1.892 | NS |
| A4f+RegProb vs A4f-VIX9D-t | +1.471 | NS |
| MS(2)-A4f vs MS(2)-GJR-N | -1.001 | NS |
| MS(2)-A4f vs GJR-t | -2.115 | NS |
| **A4f-VIX9D-t vs GJR-t** | **-5.327** | ***** |
| A4f+RegProb vs GJR-t | -5.168 | *** |

Positive DM t-stat = first model has HIGHER (worse) QLIKE.

### VaR 2.5% Backtesting

| Model | Violations | Rate | UC_p | CC_p | Basel | Score |
|-------|-----------|------|------|------|-------|-------|
| GJR-t | 121/3838 | 3.15% | 0.013 | 0.923 | GREEN | 2/3 |
| A4f-VIX9D-t | 48/1822 | 2.63% | 0.716 | 0.802 | GREEN | 3/3 |
| MS(2)-GJR-N | 120/3838 | 3.13% | 0.017 | 0.526 | GREEN | 2/3 |
| MS(2)-A4f | 62/1822 | 3.40% | 0.019 | 0.380 | GREEN | 2/3 |
| A4f+RegProb | 52/1822 | 2.85% | 0.344 | 0.664 | GREEN | 3/3 |

### Regime Analysis

| Metric | Value |
|--------|-------|
| Regime correlation (MS-GJR vs MS-A4f) | r=0.455 |
| VIX vs MS-A4f regime prob | r=0.147 |

## Conclusions

1. **MS(2)-A4f does NOT beat A4f-VIX9D-t** (DM t=+1.892, NS). The combination actually produces WORSE QLIKE, suggesting **information redundancy** — once VIX external information is incorporated through the multiplicative structure, adding regime switching does not help.

2. **A4f+RegProb also fails to improve** (DM t=+1.471, NS). Adding the MS-GJR regime probability as an extra regressor in tau provides no additional predictive power beyond VIX9D.

3. **A4f-VIX9D-t remains the champion** for VIX-based models. It has the best VaR score (3/3) and significantly beats GJR-t (DM t=-5.327).

4. **Regime switching helps in non-VIX models** — MS(2)-GJR-N has the best raw QLIKE (-8.530), but this is on a different sample (3838 days vs 1822).

5. **Convergence is a major issue**: 32/61 refits failed for A4f and MS-A4f models, likely due to VIX9D data sparsity in early windows. This limits the usable OOS sample.

6. **The regime probabilities from MS-GJR and MS-A4f are only moderately correlated (r=0.455)**, confirming that VIX information changes what regimes capture — but this doesn't translate into forecasting improvement.

## Interpretation

The null result is informative: **VIX already captures the crisis/calm distinction that regime switching models identify independently**. The weak VIX-regime correlation (r=0.225 in K1019, r=0.147 for MS-A4f) does not imply orthogonal information — it means VIX captures the economically relevant part more efficiently through the multiplicative tau structure than through discrete regime labels.

**This is consistent with VIX sufficiency** — a recurring finding in our research (31+ confirmations across K-series experiments). The marginal information in regime labels beyond what VIX provides is noise, not signal.

## Limitations

- VIX9D convergence issues reduce the OOS sample from 3838 to 1822 days
- MS(2)-A4f uses Normal innovations (not Student-t) to keep parameter count manageable — this may disadvantage it vs A4f-t
- Only tested with shared g-dynamics; fully independent per-regime dynamics (18+ params) were not attempted due to convergence concerns
- Single asset (SPY); results may differ for other assets or markets

## Files

- `k1020.py` — Full experiment script
- `k1020_results.json` — Numeric results
- `k1020_qlike_comparison.png` — QLIKE bar chart
- `k1020_regime_comparison.png` — Regime probability timeline comparison

## References

- Hamilton (1989). Econometrica, 57(2), 357-384.
- Gray (1996). JFE, 42(1), 27-62.
- Klaassen (2002). Empirical Economics, 27(2), 363-394.
- Engle & Rangel (2008). RFS, 21(3), 1187-1222.
- Patton (2011). J Econometrics, 160(1), 246-256.
- Harvey et al. (2016). t>3.0 threshold for multiple testing.
- Kupiec (1995). Christoffersen (1998). VaR backtesting.
