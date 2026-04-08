# K916: MF-GJR on Bitcoin -- Does Multiplicative VIX Structure Work for Crypto?

## Research Question
MF-GJR(VIX) is the best forecasting model for SPY/QQQ (K889 Harvey PASS).
BTC has entirely different volatility characteristics (24/7 trading, no overnight gap,
positive skewness, huge regime differences). Does MF-GJR still work for BTC?
What is the VIX elasticity (theta_1) for BTC vs SPY?

## Motivation
- K889/K889v2: MF-GJR beats GJR by -6.6% QLIKE for SPY, but 0050.TW NS (-0.3%)
- K906: SPY overnight 50% vol -> MF-GJR's tau(VIX) implicitly captures this structure
- BTC 24/7 trading -> no overnight gap -> tau(VIX) role may differ
- K830: BTC VaR needs different distribution (positive skewness)
- K136: BTC has regime-dependent gamma
- K66: 5% BTC is the only statistically significant improvement to 50/50
- K855: BTC-ETF post-2024 correlation >0.3 in 76% of windows
- Academic value: MF-GJR cross-asset class universality test

## Data
- BTC-USD daily from yfinance (2015-01-01 to 2026-04-01)
- VIX from yfinance (^VIX)
- Only business days where VIX is available (BTC weekends dropped)

## Models
1. GARCH(1,1) -- symmetric baseline
2. GJR-GARCH(1,1) -- with gamma (BTC gamma may be positive or zero)
3. MF-GJR(VIX) -- sigma^2 = tau(VIX) * g_t (SPY champion)
4. MF-GARCH(VIX) -- sigma^2 = tau(VIX) * g_t (no asymmetry)
5. EWMA(0.94) -- simple baseline

## Evaluation
- QLIKE on r^2 (Patton 2011 proxy-robust)
- DM test vs GARCH baseline (Harvey |t| > 3.0)
- Spearman rank correlation
- MCS (Hansen-Lunde-Nason 2011)
- VaR 1% + 5% Trinity (Kupiec + Christoffersen + Basel)
- HistSim VaR (K908 confirmed best for fat-tailed assets)

## OOS Setup
- DATA_START = 2015-01-01
- OOS_START = 2021-01-01 (5yr IS, 5yr OOS covering BTC bull/bear/recovery/ETF)
- WINDOW = 1000 (BTC history is shorter than SPY)
- REFIT_EVERY = 63

## Key Comparisons
- theta_1 (VIX elasticity): SPY ~2.34 (K889) vs BTC = ?
- BTC gamma: positive (reverse leverage)? zero? negative (like equity)?
- Pre-ETF vs Post-ETF (2024-01): structural break in VIX sensitivity?

## References
- Engle, Ghysels & Sohn (2013) RES 95(3):776-797
- Engle & Rangel (2008) RFS 21(3):1187-1222
- Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
- Patton (2011) J Econometrics 160:246-256
- Harvey et al. (2016) JBES 34:92-104
- Hansen, Lunde & Nason (2011) Econometrica 79(2):453-497

## Author
VolPred Research System
Date: 2026-04-06
