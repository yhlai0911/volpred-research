# Corsi (2009) HAR-RV

- **Citation**: Corsi, F. (2009). A simple approximate long-memory model of realized volatility. *Journal of Financial Econometrics* 7(2), 174–196.
- **Used in K1432 for**: Baseline B2 / B3 — daily, weekly (5-day), monthly (22-day) RV components as predictors of next-h RV. The canonical volatility baseline; any new stress/early-warning predictor must improve over HAR-RV to be claimed useful.
- **Implementation**: `experiments/k1432/k1432_tw_financial_stress.py` `make_predictors()` builds `har_d` (log of 1-day RV proxy), `har_w` (log of 5-day mean RV), `har_m` (log of 22-day mean RV).
- **Why it matters**: HAR-RV captures multi-horizon long-memory features. Any stress index that fails to beat HAR-RV is informationally redundant for vol forecasting.
