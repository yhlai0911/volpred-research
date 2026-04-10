# K1019: Markov-Switching GJR-GARCH (MS-GJR) Volatility Forecasting

## Research Questions
1. Do two regimes (calm/crisis) in GJR parameters show economically meaningful differences?
2. Can MS-GJR improve OOS QLIKE over the GJR-t baseline?
3. How does MS-GJR compare to A4f-VIX9D-t (K1004 best model)?
4. Is the MS-GJR regime probability highly correlated with VIX level?

## Motivation
- K813 (Smooth Transition GARCH) showed IS significance (LR=252) but OOS DM=-0.11 NS with 11 parameters
- MS-GJR is a cleaner approach: discrete regime switching via Hamilton (1989) filter, 10 parameters
- If regime probability aligns with VIX, it would confirm that VIX-augmented models (like A4f-VIX9D) capture the same information more efficiently

## Method
- **Models**: M1 (GJR-t baseline), M2 (MS(2)-GJR-Normal), M3 (MS(2)-GJR + VIX-driven transitions), M4 (A4f-VIX9D-t)
- **MS-GJR structure**: Gray (1996) / Klaassen (2002) variance collapse to avoid path dependence
- **Data**: SPY 2003-2026 (yfinance), OOS: 2013-2026, window=2000, refit every 63 days
- **Evaluation**: QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), VaR 2.5% backtest

## Key Results

### QLIKE (OOS, lower = better)
| Model | QLIKE | DM vs M1 | DM vs M4 |
|-------|-------|----------|----------|
| M1: GJR-t (baseline) | 1.6474 | -- | t=+3.53*** |
| M2: MS(2)-GJR | 1.6149 | t=-3.20*** | t=+2.75 NS |
| M3: MS(2)-GJR+VIX | 1.6247 | t=-2.37 NS | t=+2.49 NS |
| M4: A4f-VIX9D-t | 1.5808 | t=-3.53*** | -- |

### VaR 2.5% Backtest
| Model | Violation Rate | Kupiec p | Status |
|-------|---------------|----------|--------|
| M1: GJR-t | 2.97% | 0.093 | PASS |
| M2: MS-GJR | 3.30% | 0.005 | FAIL |
| M3: MS-GJR-VIX | 3.69% | 0.000 | FAIL |
| M4: A4f-VIX9D-t | 2.82% | 0.250 | PASS |

### Regime Parameters (last estimation window)
- **Regime 0 (Calm, 73% of time)**: alpha=0.00, gamma=0.60, beta=0.65, persistence=0.95
  - High leverage effect, moderate GARCH persistence
- **Regime 1 (Crisis, 27%)**: alpha=0.00, gamma=0.00, beta=0.83, persistence=0.83
  - Pure GARCH persistence, no leverage effect
- Transition: P(stay calm)=0.96, P(stay crisis)=0.90

### Regime-VIX Correlation
- M2 P(calm) vs VIX: r = 0.225 (weak)
- M3 P(calm) vs VIX: r = -0.294 (weak-moderate)

## Conclusions

1. **MS-GJR significantly beats GJR-t** (DM t=-3.20, passes Harvey threshold). The regime structure captures meaningful volatility dynamics.

2. **A4f-VIX9D-t remains the best model** (QLIKE 1.581 vs MS-GJR 1.615). MS-GJR does not significantly beat A4f-VIX9D-t (DM t=+2.75, NS at Harvey threshold).

3. **Regime probability is only weakly correlated with VIX** (r=0.225). This means MS-GJR and VIX-augmented models capture partially different information -- the regime variable is NOT simply a discretized VIX.

4. **MS-GJR fails VaR backtest** (VR=3.30%, Kupiec p=0.005). Normal distribution in each regime is insufficient for tail risk. This is consistent with K799-K804 findings that Student-t is essential for VaR/ES.

5. **VIX-driven transitions (M3) do not help** over constant transitions (M2). QLIKE is worse (1.625 vs 1.615) and VaR violation rate is higher (3.69% vs 3.30%).

6. **Interesting regime characterization**: Calm regime has high leverage (gamma=0.60) but moderate persistence; crisis regime has high persistence (beta=0.83) but no leverage effect. This aligns with the stylized fact that leverage effects matter more in normal markets, while crisis periods are dominated by volatility persistence.

## Limitations
- Normal innovations in MS-GJR (not Student-t) -- explains poor VaR performance
- Gray (1996) collapse approximation may lose information vs full path-dependent model
- VIX9D availability limits M4 comparison to post-2011 data
- 10 parameters (MS-GJR) vs 5 (GJR-t) -- risk of overfitting despite QLIKE improvement

## References
- Hamilton (1989), Econometrica 57(2): Markov-Switching time series
- Gray (1996), JFE 42(1): Regime-Switching GARCH
- Klaassen (2002), Empirical Economics 27(2): Improving GARCH with RS
- Haas, Mittnik & Paolella (2004), JFEC 2(4): MS-GARCH models
- Patton (2011), JoE 160(1): QLIKE loss
- Harvey (2016): t>3.0 threshold

## Files
- `k1019.py` -- experiment script
- `k1019_results.json` -- complete results
- `k1019_qlike_comparison.png` -- QLIKE bar chart
- `k1019_regime_timeline.png` -- regime probability vs VIX timeline
- `k1019_regime_params.png` -- regime parameter evolution
