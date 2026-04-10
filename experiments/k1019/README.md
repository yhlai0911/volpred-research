# K1019: VIX Regime Transition Prediction

## Problem
K752 found VIX-return R² varies 0.24-0.64 across eras (CV=0.33), suggesting distinct volatility regimes. Can we predict when VIX transitions from low to high volatility regime, and use such predictions to improve VT strategy performance?

## Motivation
If regime transitions are predictable, VT strategies could reduce equity weight *before* entering high-vol periods, reducing drawdowns. This connects to the broader question of whether VIX regime information adds value beyond the smooth 12/VIX weight function.

## Related Work
- **K752**: 5 eras VIX R² from 0.24 (pre-GFC) to 0.64 (COVID recovery)
- **K162**: VIX Regime -> Return Prediction (initial results)
- **K278**: VIX Regime Transition (initial results)
- **K133**: VIX info decay router - no true decay regime

## Method

### Data
- SPY, VIX, VIX3M from yfinance (2007-07-17 to 2026-04-08)
- Total: 4,712 observations; IS: 2,886; OOS: 1,826 (from 2019-01-01)
- seed=42

### Regime Definition
Three thresholds tested: VIX > 20, VIX > 25, VIX > 30

### Features (14 total)
VIX change rates (daily, 5d, 20d), VIX above MA20, term structure (VIX/VIX3M), realized vol (5d, 20d, ratio), return momentum (5d, 20d), VIX percentile rank, VIX acceleration, VIX level.

### Models
1. **Logistic Regression**: Full IS fit, OOS predict
2. **Rolling Logistic**: 756-day window, refit every 63 days (adaptive)
3. **Threshold Model**: ΔlogVIX speed threshold (optimized on IS)
4. **Naive Persistence** (baseline): Tomorrow's regime = today's regime

### Lag Convention
- Target: `regime.shift(-1)` (predict tomorrow's regime from today's features)
- Economic strategies: `prediction.shift(1)` (use yesterday's prediction for today's weight)
- Both baseline and strategy use same lag convention

## Results

### Classification Performance (OOS, VIX > 20)

| Model | Accuracy | F1 | Precision | Recall |
|-------|----------|-----|-----------|--------|
| Logistic Regression | 0.9102 | 0.8896 | 0.8573 | 0.9245 |
| Rolling Logistic | 0.8812 | 0.8527 | 0.8285 | 0.8783 |
| Threshold Model | 0.9200 | 0.8990 | 0.8892 | 0.9091 |
| **Naive Persistence** | **0.9272** | **0.9071** | **0.9064** | **0.9077** |

**Key finding: No model beats naive persistence.** VIX regimes are so persistent that "tomorrow = today" is extremely accurate.

### Regime Persistence

| Threshold | Mean High-Vol Episode | Median | Max | Episodes |
|-----------|----------------------|--------|-----|----------|
| VIX > 20 | 12.1 days | 2.0 days | 331 days | 143 |
| VIX > 25 | 8.6 days | 2.0 days | 212 days | 102 |
| VIX > 30 | 8.5 days | 2.0 days | 170 days | 53 |

Daily transition probability: 6.1% for VIX > 20 (~15 transitions/year).

### Transition Detection (VIX > 20)

| Lead Time | Rolling Logistic | Logistic Regression |
|-----------|-----------------|---------------------|
| 1 day | 33.3% | 21.2% |
| 2 days | 39.4% | 40.9% |
| 3 days | 37.9% | 31.8% |
| 5 days | 43.9% | 39.4% |

Models detect only ~33-44% of transitions with 1-5 day lead -- insufficient for reliable early warning.

### Economic Value (OOS 2019-2026)

| Strategy | Sharpe | Ann. Return | MDD |
|----------|--------|-------------|-----|
| **12/VIX baseline** | **0.9177** | **0.0870** | **-0.1483** |
| Buy & Hold | 0.7752 | 0.1523 | -0.3372 |
| LR Binary (VIX>20) | 0.8580 | 0.0723 | -0.1341 |
| LR Prob-wt (VIX>20) | 0.8824 | 0.0587 | -0.0919 |
| Rolling Log Binary (VIX>20) | 0.8549 | 0.0710 | -0.1312 |
| Rolling Log Prob-wt (VIX>20) | 0.9083 | 0.0596 | -0.1006 |
| LR Binary (VIX>30) | 0.9549 | 0.0904 | -0.1396 |

- Best Sharpe improvement: +0.0372 (LR Binary VIX>30) -- marginal
- Prob-weighted strategies improve MDD (-0.09 to -0.10 vs -0.15) but at cost of lower returns
- No strategy achieves Sharpe > 2x baseline (no bug suspicion)

## Conclusion

**Null result (important).** VIX regime prediction does not meaningfully improve upon the 12/VIX baseline:

1. **Regime persistence dominates**: VIX regimes are so sticky (mean 12 days for VIX>20) that naive persistence achieves F1=0.91. Sophisticated models cannot beat this.
2. **Transition detection is poor**: Only 33-44% of regime transitions are detected even with 5-day lead -- too unreliable for strategy use.
3. **12/VIX already adapts smoothly**: The continuous weight function `min(12/VIX, 1)` naturally reduces exposure as VIX rises toward/past 20, effectively capturing regime information without discrete switching.
4. **Binary switching hurts**: Abrupt weight changes (1.0 -> 0.3) add unnecessary whipsaw cost vs smooth adjustment.

**Implication for VT design**: Smooth-weight strategies (12/VIX, Risk Parity) are more robust than regime-switching approaches. This reinforces K133's finding that there is no true VIX decay regime worth trading, and supports the existing system's reliance on smooth weight functions.

## Limitations
- OOS period (2019-2026) includes unusual events (COVID, 2022 rate hikes, 2025 tariff shock)
- VIX>20 threshold is arbitrary; results may differ with data-driven threshold selection
- Only tested logistic-family models; deep learning or ensemble methods might perform differently
- Single asset (SPY); cross-market applicability untested

## Files
- `k1019.py` -- Experiment script
- `k1019_results.json` -- Full results
- `k1019_regime_prediction.png` -- 4-panel visualization
