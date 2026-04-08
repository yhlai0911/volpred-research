# K966: HAR-PD Path-Dependent RV Forecasting (5-min RV, Pilot)

## Motivation
K624 tested HAR-PD (Guyon & Lekeufack 2023, arXiv:2503.00851) using daily squared returns as the volatility proxy and found it performed 88% worse than standard HAR-RV. The hypothesis was that path-dependent features need high-frequency data to be effective. K960 established the 5-min RV baseline (HAR-RV R²=0.243, QLIKE=0.118). This experiment tests whether HAR-PD improves over HAR-RV when using 5-min realized variance as the target.

## Method
- **HAR-RV baseline**: RV_{t+1} = β₀ + β_d RV_t + β_w RV_t^(w) + β_m RV_t^(m)
- **HAR-PD extension**: adds two path-dependent features:
  - R1 (trend): exponentially weighted past returns (decay λ₁)
  - R2 (volatility memory): exponentially weighted past |returns| (decay λ₂)
- **Lambda selection**: grid search over λ ∈ {0.01, 0.05, 0.1, 0.2, 0.5, 0.8, 0.9, 0.95}, minimizing IS QLIKE
- **Data**: SPY 5-min intraday from yfinance, 2026-01-15 to 2026-04-06 (55 usable days)
- **Split**: IS=37 days, OOS=17 days (pilot study)

## Key Results

| Model | OOS QLIKE | OOS R² | 
|-------|-----------|--------|
| HAR-RV | 0.331 | -7.354 |
| HAR-PD (R1+R2) | 0.377 | -10.835 |
| HAR-PD (R1 only) | 0.346 | -8.617 |
| HAR-PD (R2 only) | 0.335 | -8.266 |

- **Best lambdas**: λ₁=0.01, λ₂=0.20
- **IS fit**: HAR-PD R²=0.841 vs HAR R²=0.575 (PD much better in-sample)
- **OOS**: HAR-PD 13.8% worse in QLIKE (overfitting)
- **DM test**: t=-1.37, p=0.19 (not significant, expected with N=17)
- **Bootstrap**: HAR-PD better in only 10.6% of 1000 reps, CI includes 0

## Conclusion
**NULL RESULT confirmed.** HAR-PD does not improve over HAR-RV even with 5-min data. The path-dependent features dramatically improve in-sample fit (R² 0.575→0.841) but degrade OOS performance, a classic overfitting pattern exacerbated by the tiny sample (N=55 total, 17 OOS).

This is consistent with K624 (daily r² version, PD 88% worse). The direction is the same across both data frequencies: path-dependent features as formulated here add noise rather than signal for SPY volatility forecasting.

**Caveats**: This is a pilot study with only 17 OOS days. With 200+ days of 5-min data, results could differ. The negative OOS R² for both models indicates the IS period and OOS period have very different dynamics.

## References
- Guyon, J. & Lekeufack, J. (2023). "Volatility is (Mostly) Path-Dependent." arXiv:2503.00851
- Corsi, F. (2009). "A Simple Approximate Long-Memory Model of Realized Volatility." JFE 7(2):174-196
- Patton, A. (2011). "Volatility Forecast Comparison Using Imperfect Volatility Proxies." JoE 160(1):246-256

## Files
- `k966_har_pd.py` — experiment script
- `k966_har_pd_results.json` — full results
- `k966_lambda_grid.png` — lambda grid search heatmap
- `k966_forecast_comparison.png` — HAR vs HAR-PD OOS forecasts
