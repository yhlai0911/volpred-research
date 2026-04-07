# K975: VIX Term Structure Slope — Predictive Power and Strategy Analysis

## Research Question
Does the VIX/VIX3M term structure slope provide incremental predictive power for SPY returns and realized volatility beyond VIX level alone? Can a slope-based variable timing strategy outperform 12/VIX?

## Motivation
The VIX term structure (VIX vs VIX3M) reflects market expectations about volatility persistence. Backwardation (VIX > VIX3M, slope > 1) signals acute stress; contango (slope < 1) is the normal state. Literature suggests backwardation predicts vol mean reversion, which could inform trading strategies.

## Data
- **Source**: yfinance (^VIX, ^VIX3M, SPY)
- **Period**: 2010-01-05 to 2026-04-06 (4,087 observations)
- **IS/OOS split**: IS = 2010-2018, OOS = 2019-2026

## Method
1. **Descriptive**: Slope distribution, backwardation frequency, autocorrelation
2. **Predictive regressions**: Slope → forward returns/vol (1d/5d/22d), with VIX as benchmark, IS/OOS R², DM tests
3. **Strategy backtests**: Slope-based VT, 12/VIX, Slope-adjusted 12/VIX, Buy & Hold. All with signal.shift(1) lag
4. **Conditional analysis**: Returns by slope regime, backwardation event study
5. **Mean reversion test**: VIX change after strong backwardation episodes

## Key Results

### Descriptive Statistics
- Mean slope = 0.895, indicating typical contango
- Backwardation (slope > 1.0): only 7.8% of days
- High persistence: ACF(1) = 0.91, ACF(22) = 0.29
- Positive skew (1.18) with fat tails (kurtosis 3.18)

### Predictive Power
| Target | Slope Only R² (OOS) | VIX Only R² (OOS) | Slope+VIX R² (OOS) | Incremental R² | DM p-value |
|--------|--------------------|--------------------|---------------------|----------------|------------|
| Fwd 1d Return | 0.0010 | 0.0028 | 0.0026 | -0.0002 | 0.818 |
| Fwd 5d Return | -0.0024 | 0.0054 | 0.0049 | -0.0006 | 0.391 |
| Fwd 22d Return | 0.0169 | 0.0638 | 0.0628 | -0.0010 | 0.012 |
| **Fwd 5d RVol** | 0.3039 | 0.4786 | **0.5005** | **+0.0219** | **0.0002** |
| **Fwd 22d RVol** | 0.1867 | 0.3106 | **0.3250** | **+0.0145** | **0.0000** |

**Key finding**: Slope provides **statistically significant incremental predictive power for realized volatility** (5d and 22d), but **not for returns**. The DM test is highly significant for vol prediction (p < 0.001).

### Strategy Performance

| Strategy | Sharpe (Full) | Sharpe (OOS) | MDD | Ann. Return |
|----------|--------------|--------------|-----|-------------|
| Buy & Hold | 0.785 | 0.819 | -33.7% | 13.5% |
| 12/VIX | 0.882 | 0.990 | -14.4% | 8.2% |
| **Slope VT** | **0.908** | **1.055** | -27.4% | 14.2% |
| **Slope x 12/VIX** | **0.909** | **1.042** | -14.9% | 8.4% |

- Slope VT has highest OOS Sharpe (1.055) but higher MDD (-27.4%)
- Slope x 12/VIX achieves comparable Sharpe to Slope VT with much lower MDD (-14.9%)
- Both slope strategies marginally outperform pure 12/VIX

### Mean Reversion
After **strong backwardation** (slope > 1.1, n=69 events):
- 5-day VIX change: mean -7.4%, 74% decline (t=-2.10, p=0.040)
- 22-day VIX change: mean -18.2%, 80% decline (t=-3.43, **p=0.001**)
- Confirms statistically significant VIX mean reversion after backwardation

### Event Analysis
- **COVID 2020**: Slope hit 1.34 (extreme backwardation), 51.8% of days in backwardation
- **2022 Bear**: Mild slope elevation (mean 0.93), only 7.2% backwardation
- **Aug 2024 VIX spike**: Brief backwardation (9.1%), slope reached 1.14

## Conclusions
1. **Slope is a significant vol predictor**: Adds 1.5-2.2% incremental OOS R² over VIX alone for realized vol forecasting. This is economically meaningful for vol-targeting strategies.
2. **Slope is NOT a return predictor**: No incremental value for return forecasting beyond VIX level.
3. **Slope VT marginally outperforms 12/VIX**: Sharpe improvement is modest (~0.03 full sample, ~0.07 OOS), and comes with higher MDD. The combination (Slope x 12/VIX) provides a better risk-adjusted package.
4. **Backwardation = vol mean reversion**: Highly significant (p=0.001). After strong backwardation, VIX declines 80% of the time within 22 days.

## Limitations
- Slope strategy has discrete weight buckets (sensitivity to thresholds not tested)
- VIX3M data from yfinance may have gaps
- No transaction costs modeled
- Strategy improvement over 12/VIX is modest — may not survive realistic frictions

## Files
- `k975_vix_slope.py` — Main analysis script
- `k975_vix_slope_results.json` — Full numerical results
- `k975_slope_distribution.png` — Slope distribution and time series
- `k975_conditional_returns.png` — Conditional returns by regime
- `k975_strategy_comparison.png` — Strategy cumulative returns comparison
