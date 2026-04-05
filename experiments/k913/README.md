# K913: Variance Risk Premium (VRP) as Return Predictor

## Motivation
- VIX sufficiency confirmed 26 times for vol prediction, but VIX does NOT predict return direction (K697: r=0.04)
- VRP = Implied Variance - Realized Variance captures the "fear premium" investors pay
- Bollerslev, Tauchen & Zhou (2009, RFS): VRP significantly predicts equity returns
- Bekaert & Hoerova (2014, JFE): VRP predictive power varies across horizons
- K833: VRP 78-83% positive (fear premium persistent) -- but can it be exploited?

## Method
1. Compute VRP = (VIX/100)^2 * 252 - RV_22d * 252 (both annualized)
2. Descriptive statistics and distribution analysis
3. Predictive regressions at daily/weekly/monthly horizons with Newey-West HAC SE
4. OOS prediction (IS: 2006-2018, OOS: 2019-2026) with expanding window
5. VRP trading strategy (smooth weight based on VRP percentile)
6. VRP interaction with existing VT strategies

## Key Results

### VRP Characteristics
- VRP positive **85.7%** of time (fear premium is persistent)
- Mean VRP = 0.0081 (annualized), highly right-skewed (skew = -7.17)
- VRP-VIX correlation = **-0.24** (negatively correlated -- high VIX tends to mean negative VRP spikes)
- ACF(1) = 0.93 -- very persistent

### Predictive Regressions (Full Sample, Newey-West HAC SE)
| Horizon | beta | t-stat | R^2 | Harvey |t|>3? |
|---------|------|--------|-----|--------|
| Daily | 0.0137 | 1.10 | 0.0026 | NO |
| Weekly | 0.0146 | 0.37 | 0.0007 | NO |
| Monthly | 0.0250 | 0.23 | 0.0005 | NO |

**None pass Harvey (2016) |t|>3.0 threshold.**

### OOS Prediction (2019-2026)
| Horizon | OOS R^2 | Dir. Accuracy |
|---------|---------|---------------|
| Daily | -0.031 | 54.2% |
| Weekly | -0.082 | 59.0% |
| Monthly | -0.099 | 67.2% |

**All OOS R^2 are NEGATIVE** -- VRP model does worse than the historical mean.

### VRP Quintile Analysis (Lagged)
| Quintile | Ann. Return | Sharpe |
|----------|-------------|--------|
| Q1 (Low VRP) | 5.4% | 0.22 |
| Q2 | 11.3% | 0.89 |
| Q3 | 2.5% | 0.19 |
| Q4 | 3.3% | 0.20 |
| Q5 (High VRP) | 26.4% | 0.99 |

Q5-Q1 spread = 20.9% ann., but t = 1.12 (FAILS Harvey threshold).

### Strategy Performance
| Strategy | Sharpe | Ann. Return | MDD |
|----------|--------|-------------|-----|
| VRP Strategy | 0.555 | 6.1% | -37.4% |
| Buy & Hold SPY | 0.490 | 9.6% | -59.6% |

VRP strategy has better Sharpe and much better MDD, but the return difference is NOT statistically significant (t = -1.53, p = 0.125).

### VRP + 12/VIX Interaction
Combined VRP+12/VIX (Sharpe 0.39) does WORSE than plain 12/VIX (0.59) -- adding VRP hurts.

## Conclusion
**VRP does NOT significantly predict SPY returns** at any horizon, contrary to Bollerslev et al. (2009). This is consistent with K697 (VIX does not predict direction). The fear premium exists (85.7% positive VRP) but cannot be reliably timed. VRP as a strategy signal improves MDD but not returns. **This is a NULL RESULT** that reinforces the finding that market direction is unpredictable using volatility-based signals.

## Key Rules Applied
- signal.shift(1) for all strategy tests (no lookahead)
- np.random.seed(42) for reproducibility
- Newey-West HAC standard errors for all regressions
- Harvey (2016) |t| > 3.0 threshold for significance claims
- OOS R^2 (Campbell & Thompson 2008) for prediction evaluation

## Limitations
- RV proxy: 22-day rolling sum of r^2 (close-to-close), not 5-min RV
- Single asset (SPY) -- VRP might predict other markets differently
- Linear model only -- VRP might have nonlinear predictive power
- 2019-2026 OOS includes COVID, which is unusual

## References
- Bollerslev, Tauchen & Zhou (2009): Expected Stock Returns and Variance Risk Premia, RFS 22(11):4463-4492
- Bekaert & Hoerova (2014): The VIX, the Variance Premium and Stock Market Volatility, JFE 111(2):120-136
- Campbell & Thompson (2008): Predicting Excess Stock Returns Out of Sample, RFS 21(4):1509-1531
- Harvey (2016): ... and the Cross-Section of Expected Returns, RFS 29(1):5-68

## Data
- SPY daily prices: yfinance
- VIX daily close: yfinance (^VIX)
- Period: 2006-01-03 to 2026-03-30 (5,091 observations)
- Realized Variance: 22-day rolling sum of squared daily returns (annualized)
