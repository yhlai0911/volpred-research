# K1016: HAR + vix_gap Parsimonious Volatility Model

## Research Question

Can a parsimonious HAR(1,5,22) + vix_gap model significantly improve over the HAR baseline for volatility prediction? K1014 found that vix_gap (VIX implied - realized vol spread) was the only significant path feature (t=7.27) in the full HAR-PD model, but multicollinearity degraded overall prediction. This experiment tests whether isolating vix_gap alone in a simpler HAR specification yields out-of-sample improvement.

## Motivation

- **K1014**: HAR-PD found vix_gap is the only significant path feature (t=7.27), but the full model with all path features worsened predictions due to multicollinearity
- **K530**: HAR-ABS dominates GJR on |r| target (DM=-15.45)
- **K782**: HAR loses to GJR on r^2 target (proxy matters more than model)
- **K208**: Implied-Realized Vol Gap has prior research as a risk indicator

## Method

### Models (5)
| Model | Specification | Target |
|-------|--------------|--------|
| M1 | HAR(1,5,22) baseline | |r| -> convert to sigma^2 |
| M2 | HAR + vix_gap | |r| -> convert to sigma^2 |
| M3 | HAR + VIX_level | |r| -> convert to sigma^2 |
| M4 | A4f-VIX9D (GARCH-X) | sigma^2 (native) |
| M5 | GJR-t (pure GARCH) | sigma^2 (native) |

### Key Definitions
- **vix_gap** = VIX_t / (100 * sqrt(252)) - sqrt(RV_22_t), where RV_22 = mean(r^2) over past 22 days
- HAR |r| forecasts converted to sigma^2: sigma^2 = |r_hat|^2 * pi/2 (normality assumption)
- Unified comparison on QLIKE(r^2) per Patton (2011) proxy-robust framework

### Estimation
- HAR: OLS, rolling window=1000, refit every 63 days
- GARCH: MLE, window=2000, refit every 63 days
- Data: SPY, 2004-02-04 to 2026-04-08 (5,579 obs), yfinance
- Evaluation period: 2012-01-13 to 2026-04-08 (3,567 obs)
- Seed: 42

## Results

### QLIKE on r^2 (Patton 2011, lower = better)

| Model | QLIKE | Spearman(r^2) | Rank |
|-------|-------|---------------|------|
| M5: GJR-t | **1.537** | 0.386 | 1 |
| M4: A4f-VIX9D* | 1.537 | 0.386 | =1 |
| M1: HAR(1,5,22) | 1.616 | 0.323 | 3 |
| M3: HAR+VIX_level | 1.624 | 0.393 | 4 |
| M2: HAR+vix_gap | **1.831** | 0.384 | 5 (worst) |

*M4 fell back to pure GJR due to arch library GARCH-X limitation -- not a valid comparison.

### MSE on |r| (HAR native target, lower = better)

| Model | MSE(|r|) |
|-------|----------|
| M3: HAR+VIX_level | **4.550e-5** |
| M2: HAR+vix_gap | 4.617e-5 |
| M1: HAR(1,5,22) | 4.872e-5 |

### DM Tests (Harvey threshold |t| > 3.0)

| Comparison | Target | DM t-stat | p-value | Significant? |
|-----------|--------|-----------|---------|-------------|
| M2 vs M1 | QLIKE r^2 | +1.583 | 0.113 | NO (M2 worse) |
| M2 vs M1 | MSE |r| | -2.869 | 0.004 | Near (M2 better) |
| M2 vs M3 | QLIKE r^2 | +1.561 | 0.119 | NO |
| M3 vs M1 | QLIKE r^2 | +0.160 | 0.873 | NO |
| M1 vs M5 | QLIKE r^2 | +3.041 | 0.002 | **YES** (HAR worse) |
| M2 vs M5 | QLIKE r^2 | +2.077 | 0.038 | NO (Harvey) |

### In-Sample Coefficient Significance

**M2 (HAR + vix_gap):**
| Variable | Coef | SE | t-stat |
|----------|------|-----|--------|
| const | -0.00263 | 0.00027 | -9.72 |
| |r_1| | -0.095 | 0.0155 | -6.13 |
| avg|r_5| | 0.390 | 0.0337 | 11.56 |
| avg|r_22| | 0.825 | 0.0417 | 19.79 |
| **vix_gap** | **0.770** | **0.0418** | **18.43** |

vix_gap coefficient: 100% positive across all 73 rolling refits, mean=0.918, range [0.56, 1.27].

## Key Findings

1. **vix_gap fails on QLIKE r^2**: Despite massive in-sample significance (t=18.43), vix_gap actually *worsens* QLIKE on r^2 (1.831 vs 1.616 for baseline). This is a textbook in-sample vs OOS divergence.

2. **vix_gap helps on native |r| target**: On MSE(|r|), M2 significantly improves over M1 (DM t=-2.869, p=0.004), though this falls just short of Harvey's t>3.0 threshold.

3. **The |r| -> r^2 conversion amplifies errors**: The pi/2 conversion (sigma^2 = |r_hat|^2 * pi/2) squares the forecasting error, which particularly hurts models with higher implied vol predictions. vix_gap is predominantly positive (86.5% of days VIX overprices realized vol), so HAR+vix_gap systematically predicts higher |r| -> even higher sigma^2 -> worse QLIKE on r^2.

4. **GJR dominance on QLIKE r^2 reconfirmed**: M1 (HAR) is significantly worse than GJR at Harvey threshold (DM t=3.041). This directly reconfirms K782.

5. **VIX information improves ranking but not QLIKE**: Both M2 and M3 have better Spearman correlation with r^2 (0.384-0.393) than M1 (0.323), suggesting VIX information helps *rank* volatility but the magnitude calibration degrades QLIKE.

6. **VRP (vix_gap) is persistently positive**: 86.5% of days have positive vix_gap (VIX overprices realized vol), consistent with the variance risk premium literature (Bollerslev et al. 2009). The mean vix_gap is 0.00225 daily, roughly 3.6% annualized.

## Limitations

- M4 (A4f-VIX9D) was not properly estimated due to arch library limitations with exogenous regressors -- this comparison is invalid
- The |r| -> sigma^2 conversion assumes normality (pi/2 factor), which may bias results under fat tails
- Only SPY tested; cross-asset robustness not verified
- The stark IS vs OOS divergence for vix_gap may be partly due to the non-stationarity of the VRP over long samples

## Implications for Research Program

1. **vix_gap has genuine predictive content for |r| but not for sigma^2 via QLIKE**: Future HAR models could include vix_gap when the native target is |r|, but this does not translate to r^2 superiority
2. **GARCH remains king for r^2 prediction**: Even simple GJR-t outperforms augmented HAR models on QLIKE r^2
3. **The Spearman vs QLIKE divergence** (better ranking but worse QLIKE) suggests exploring rank-based loss functions or regime-dependent models where VIX info enters through regime classification rather than direct regression

## Data Source
- yfinance: SPY, ^VIX, ^VIX9D
- Period: 2004-02-04 to 2026-04-08

## References
- Corsi (2009): HAR-RV model, Journal of Financial Econometrics
- Patton (2011): Volatility Models and Their Use in Prediction, J. Financial Econometrics
- Bollerslev et al. (2009): Expected Stock Returns and Variance Risk Premia, RFS
- Harvey (2016): Multiple testing threshold
- K1014, K530, K782, K1004, K208
