# K969: Bespoke RV — Optimal Daily Volatility Proxy Weighting

## Motivation
Patton & Zhang (JoE 2026, "Bespoke Realized Volatility") showed that ML-optimized weights on 5-min return squares across intraday time slots significantly improve realized volatility as a forecast target. Since we only have 56 days of 5-min data, we adapt the core concept to daily-frequency: can optimally weighted OHLCV-based volatility proxies outperform individual proxies or equal-weight combinations?

## Method

### Daily Volatility Proxies (from OHLCV)
1. **r²** — close-to-close squared return
2. **Parkinson** — range-based: (log(H/L))² / (4·log2)
3. **Garman-Klass** — range + close-open
4. **Rogers-Satchell** — drift-adjusted
5. **Yang-Zhang** — overnight + intraday composite

### Models Compared
1. **AR(1) on each proxy** — 5 individual models
2. **Equal-weight** — average of all 5 proxies, then AR(1)
3. **Bespoke OLS** — OLS regression: σ²_{t+1} = α + Σ wᵢ·proxyᵢ,ₜ
4. **Bespoke Ridge** — Same with L2 regularization (α=1.0)
5. **HAR-Bespoke** — HAR structure (daily/weekly/monthly) on equal-weight vol

### Data
- SPY OHLCV from yfinance, 2006-01-04 to 2026-04-06 (5094 obs)
- IS: 2006-2018 (3270 obs), OOS: 2019-2026 (1824 obs)

### Evaluation
- QLIKE (Patton 2011), MSE, Mincer-Zarnowitz regression, DM test

## Key Results

| Model | QLIKE | MSE(×1e-6) | MZ R² |
|-------|-------|-----------|-------|
| AR1_r² | 1.765 | 0.327 | 0.145 |
| AR1_parkinson | 1.608 | 0.309 | 0.262 |
| AR1_gk | 1.580 | 0.305 | 0.286 |
| AR1_rs | 1.603 | 0.305 | 0.283 |
| AR1_yz | 1.562 | 0.309 | 0.207 |
| Equal_Weight | 1.545 | 0.284 | 0.270 |
| Bespoke_OLS | 14009 | 0.315 | 0.172 |
| Bespoke_Ridge | 1.973 | 0.376 | 0.002 |
| **HAR_Bespoke** | **1.448** | **0.279** | **0.260** |

## Conclusions

1. **HAR-Bespoke wins decisively** — Best by both QLIKE (1.448) and MSE. Significantly better than all individual proxies (DM p < 0.001). The HAR structure (daily/weekly/monthly averaging) is the key driver, not complex weighting.

2. **Bespoke OLS fails catastrophically** — QLIKE = 14009 due to severe multicollinearity among range-based proxies (Parkinson/GK/RS correlation > 0.89). OLS weights are extreme and unstable (GK weight swings from -6.9 to +21.7 in rolling estimation). This is a textbook case of multicollinearity causing OOS failure.

3. **Ridge helps but not enough** — Regularization prevents the worst OLS behavior but the shrinkage is too aggressive (alpha=1.0), producing near-zero weights that can't capture proxy differences.

4. **Range-based proxies > close-to-close** — Among individual AR(1) models, Garman-Klass (QLIKE=1.580) beats close-to-close r² (1.765). Range-based estimators use more price information (H, L, O, C vs just C).

5. **Equal-weight is surprisingly strong** — Simple equal-weight average (QLIKE=1.545) beats every individual proxy AR(1). Diversification across estimators works, similar to Patton & Zhang's finding that combining information helps.

6. **Yang-Zhang best individual** — Despite being the most complex single proxy, AR1_yz (QLIKE=1.562) is the best individual predictor, likely because it combines overnight and intraday information.

## Limitations
- Daily-frequency adaptation cannot capture the intraday timing effects central to Patton & Zhang's original paper
- Target is close-to-close r², which is a noisy proxy for true volatility
- OLS multicollinearity is a known issue with correlated regressors — could be addressed with PCA or elastic net
- Only tested on SPY; cross-asset robustness untested

## References
- Patton & Zhang (2026), "Bespoke Realized Volatility", Journal of Econometrics
- Patton (2011), "Volatility forecast comparison using imperfect volatility proxies", JoE
- Garman & Klass (1980), "On the estimation of security price volatilities from historical data"
- Yang & Zhang (2000), "Drift independent volatility estimation"

## Files
- `k969_bespoke_rv.py` — Main experiment script
- `k969_bespoke_rv_results.json` — Full results
- `k969_weight_analysis.png` — OLS/Ridge weights + rolling stability
- `k969_forecast_comparison.png` — OOS performance comparison
