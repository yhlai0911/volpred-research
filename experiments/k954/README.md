# K954: DeFi Impermanent Loss and Volatility Prediction

## Problem
DeFi AMM (Uniswap-style) liquidity providers face Impermanent Loss (IL), which is entirely driven by price volatility. Can GARCH models predict IL and enable risk management for LPs?

## Motivation
- IL formula for 50/50 pool: `IL = 2*sqrt(p1/p0)/(1+p1/p0) - 1`
- For small moves: `IL ~ -sigma^2/8` (quadratic in volatility)
- If we can predict sigma^2, we can predict IL

## Data
- **Asset**: ETH-USD (yfinance), 2020-01-03 to 2026-04-05 (2,286 obs)
- **IS**: 1,599 obs (2020-01-03 to 2024-05-19)
- **OOS**: 686 obs (2024-05-20 to 2026-04-05)

## Method
1. Compute daily exact IL from price changes
2. GJR-GARCH(1,1,1)-t, GARCH(1,1)-t, EWMA(0.94), Naive baselines
3. Predicted IL = -sigma^2_predicted / 8
4. Evaluate: MSE/MAE/Corr of IL prediction, QLIKE on r^2, classification, selective LP

## Key Findings

### 1. IL is small but cumulative
- Daily mean IL: -0.023% (tiny per day)
- 30-day cumulative IL: -0.70% mean (significant for LPs)
- IL is **always** negative (cost), never benefit

### 2. IL approximation (-sigma^2/8) is excellent
- Correlation with exact IL: 0.9999
- Breaks down only for |return| > 10% (72 days in sample)

### 3. ETH has NO leverage effect (gamma < 0)
- GJR gamma = -0.032 (negative, opposite to equities)
- Confirms K916: crypto vol is symmetric or inverse-asymmetric
- Persistence = 1.0 (IGARCH), fat tails nu=3.80

### 4. IL prediction is weak (R^2 < 0)
- All models produce negative R^2 for daily IL prediction
- QLIKE on r^2 shows marginal GARCH advantage but differences are negligible
- Daily IL is too noisy to predict (it's a quadratic function of unpredictable returns)

### 5. Selective LP strategy fails
- With 0.5% threshold, predicted IL never exceeds it in OOS -> always in pool
- Even with lower thresholds, the Sharpe improvement is negligible
- **The fee revenue (0.03%/day) dominates IL cost (0.023%/day)**: fees > IL on average

## Conclusions
- **IL ~ -sigma^2/8 is an excellent approximation** for daily horizons
- **Predicting IL is equivalent to predicting r^2**, which is inherently noisy
- **GJR-GARCH cannot improve LP timing** because daily IL is small and fee income dominates
- **The real risk for LPs is tail events** (days with |return| > 10%): these are rare but IL is severe
- **Crypto has no leverage effect** (gamma < 0), making GJR less useful than for equities
- **For practical LP risk management, focusing on tail risk (VaR/ES of IL) may be more useful than mean prediction**

## Limitations
- Daily close from yfinance (UTC midnight) does not capture intraday vol
- Fee revenue simplified (constant), real fees depend on volume and range position
- No gas costs or smart contract risk
- Uniswap v3 concentrated liquidity not modeled (would amplify IL)
- VIX-crypto cross-market signal not tested (K916 showed it fails)

## Files
- `k954.py` - Main experiment script
- `k954_results.json` - Full numerical results
- `k954_il_analysis.png` - 6-panel analysis figure
