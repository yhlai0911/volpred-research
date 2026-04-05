# K911: Quantile Connectedness & Tail Contagion (QDVC)

## Motivation
- K907: mean TCI ~50%, orthogonal to VIX (r=0.001)
- K910: mean TCI has no directional predictive power (r=0.005)
- K908: MF-GJR + HistSim solves VaR, but doesn't use network structure
- **Hypothesis**: mean TCI is null because we looked at the wrong dimension. Tail connectedness (tau=0.05 TCI) may spike during extremes, independently of VIX

## Method
1. Quantile VAR: replace OLS with quantile regression at tau = {0.05, 0.50, 0.95}
2. For each tau, compute Generalized FEVD -> tau-specific connectedness table
3. Rolling 250-day windows (step=5 for efficiency) across 4 assets: SPY, QQQ, GLD, 0050.TW
4. Compare Tail TCI (tau=0.05) vs Mean TCI (tau=0.50) vs Upper TCI (tau=0.95)
5. Correlate with VIX, test tail risk prediction via logistic regression

## Efficiency Notes
- 4 assets (not 9) to keep quantile regression tractable
- Rolling step=5 (every 5 days, not every day)
- VAR lag p=2
- Estimated runtime: 5-10 minutes

## Data
- yfinance daily OHLC, 2006-01-01 to 2026-04-01
- Assets: SPY, QQQ, GLD, 0050.TW
- Vol proxy: Garman-Klass
- 0050.TW cleaned via clean_tw50_data

## References
- Ando, Greenwood-Nimmo, Shin (2022): Quantile Connectedness
- Diebold & Yilmaz (2012, 2014): Standard Connectedness
- Koenker & Bassett (1978): Quantile Regression

## Output
- k911_quantile_connectedness.py
- k911_quantile_connectedness_results.json
- k911_rolling_quantile_tci.png
- k911_tail_vs_mean_tci.png
- k911_crisis_comparison.png
