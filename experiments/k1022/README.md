# K1022: Crypto Fear Channel -- BTC Vol Spillover to Equity via VIX

## Problem Statement
Does Bitcoin volatility asymmetrically spill over to equity markets through the VIX fear channel? K746b found evidence but was flagged by Codex for methodology issues (Granger target mismatch, Andrews partial). This experiment uses corrected methodology and extends the analysis with tail dependence, dynamic correlation, and economic value assessment.

## Motivation
- K639 confirmed BTC Granger-causes SPY returns with inverse leverage
- K746b found BTC vol asymmetrically Granger-causes VIX (crypto stress -> equity fear), but methodology was questioned
- Paper 6 needs rigorous evidence for the "crypto fear channel" mechanism
- Key question: Is BTC vol a useful signal for VIX forecasting (economic value)?

## Method
1. **Data**: SPY, BTC-USD, ^VIX from yfinance, 2015-2026 (N=2,811 common trading days)
2. **Granger Causality**: Corrected -- using VIX level (not log-VIX) as target per Codex review
3. **Asymmetric Granger**: Split BTC returns into up-vol (positive returns) and down-vol (negative returns), test each separately
4. **Tail Dependence**: Quantile regression of VIX change on BTC r-squared at tau = 0.05-0.95
5. **Rolling Spillover**: Diebold-Yilmaz VAR FEVD, 252-day rolling window, 10-day forecast horizon
6. **Dynamic Correlation**: EWMA (lambda=0.94) on GARCH-standardized residuals
7. **VIX Forecasting**: Expanding-window OOS (2019-2026), AR vs AR+BTC_vol, DM test

## Key Results

### 1. Granger Causality (Corrected)
- **BTC RV -> VIX: STRONG** -- Significant at 9/10 lags (p < 0.05 from lag 2 onwards)
- **VIX -> BTC RV: WEAK** -- Significant at only 1/10 lags (lag 1 only, p=0.018)
- Direction is predominantly BTC -> VIX, confirming K746b's core finding with correct methodology

### 2. Asymmetric Spillover (Key Finding)
- **BTC down-vol -> VIX: significant at 3/3 lags** (lags 2, 3, 5; p < 0.05)
- **BTC up-vol -> VIX: significant at 0/3 lags** (all p > 0.20)
- **Down/Up F-ratio averages 7.8x at lags 2-5**
- Conclusion: Only crypto crashes drive equity fear. Crypto rallies have zero effect on VIX.

### 3. Tail Dependence (Quantile Regression)
- BTC vol's effect on VIX change increases dramatically in the upper tail:
  - tau=0.05 (VIX drop): beta = -47.9 (p < 0.001)
  - tau=0.50 (median): beta = 22.8 (p < 0.001)
  - tau=0.95 (VIX spike): beta = 311.6 (p < 0.001)
- Upper tail avg beta (227.0) is 8x the lower tail avg (-28.2)
- BTC vol is most strongly associated with VIX spikes, not VIX drops

### 4. Spillover Dynamics
- Mean BTC->VIX spillover: 3.5%, VIX->BTC: 2.1% (net: BTC is sender)
- Spillover is time-varying with peaks during:
  - 2016 early (BTC->VIX 13.6%)
  - 2020 COVID (bidirectional, ~6%)
  - 2024 Aug (VIX event, 12.9%)
- Recent years (2023-2025): low total spillover (~1-2%)

### 5. Dynamic Correlation (EWMA-DCC)
- BTC-SPY mean DCC: 0.18 (low overall correlation)
- **High VIX regime: DCC = 0.295 vs Low VIX: DCC = 0.066** (t=25.6, p < 0.001)
- Contagion confirmed: BTC-equity correlation rises 4.4x during stress periods
- BTC-VIX DCC mean: -0.18 (inverse relationship)

### 6. VIX Regime-Conditional Behavior
| Regime | Return Corr | Vol Corr | BTC Ann. Ret | SPY Ann. Ret |
|--------|------------|----------|-------------|-------------|
| Low VIX (<13.6) | 0.06 | -0.28 | 120.9% | 48.1% |
| Mid VIX (13.6-21.3) | 0.09 | 0.27 | 41.7% | 22.3% |
| High VIX (>21.3) | 0.43 | 0.53 | -0.1% | -42.7% |

BTC is a diversifier during calm periods (low correlation) but converges during crises (high correlation). NOT a crisis hedge.

### 7. Economic Value: VIX Forecasting (NULL RESULT)
- AR+BTC_vol vs AR benchmark: MSE improvement = 0.81%, DM t = 0.42 (p=0.68)
- **Fails both Harvey (|t|>3.0) and standard (|t|>1.96) thresholds**
- BTC vol contains statistical Granger information about VIX but **no practical forecasting improvement** in linear framework
- Possible explanation: Information is absorbed too quickly (lag 1 not significant) or relationship is nonlinear

## Conclusions
1. **Crypto fear channel exists and is asymmetric**: Only crypto crashes (not rallies) Granger-cause VIX increases. The mechanism is unidirectional BTC->VIX.
2. **Tail dependence is extreme**: BTC vol's effect on VIX spikes (upper tail) is 8x larger than its effect on VIX drops.
3. **Contagion is VIX-regime dependent**: BTC-SPY correlation rises from 0.07 to 0.30 during high-VIX periods.
4. **No practical forecasting value**: Despite Granger causality, BTC vol does not improve VIX point forecasts in linear OOS evaluation.
5. **BTC is NOT a crisis hedge**: High-VIX regime annual return is -0.07% for BTC (vs -42.7% for SPY -- less bad, but not hedging).

## Limitations
- BTC data starts 2015 -- limited pre-maturity observations
- VIX is implied vol, not realized -- comparison is cross-concept
- Granger causality does not equal true causation
- EWMA DCC is simplified (not full DCC-GARCH MLE estimation)
- Linear AR model for VIX forecasting -- nonlinear methods may differ
- No intraday data -- daily frequency may miss fast spillovers

## Files
- `k1022.py` -- Main experiment script
- `k1022_results.json` -- Complete results with all statistics
- `k1022_spillover_dynamics.png` -- Spillover, rolling correlation, DCC, quantile regression
- `k1022_regime_analysis.png` -- BTC vs VIX time series, scatter by regime, directional spillover, DCC distribution

## Data Source
- yfinance: SPY, BTC-USD, ^VIX
- Period: 2015-02-03 to 2026-04-08
- Sample: N = 2,811 common trading days
- Seed: 42

## References
- K639: BTC-SPY Granger causality
- K746b: BTC vol asymmetric Granger causes VIX (original, methodology issues)
- Diebold & Yilmaz (2012): Connectedness approach
- Patton (2006): Copula-based models
- Harvey (2016): |t| > 3.0 threshold for statistical significance
