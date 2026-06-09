# Patton (2011) QLIKE Loss

- **Citation**: Patton, A. J. (2011). Volatility forecast comparison using imperfect volatility proxies. *Journal of Econometrics* 160(1), 246–256.
- **Used in K1432 for**: OOS loss function — QLIKE = log(σ̂²) + σ²/σ̂². Robust to noisy proxy volatility (MSE is not). All DM tests reported in QLIKE plus MSE for sanity.
- **Implementation**: `qlike_loss()` in the script.
- **Why it matters**: MSE on log RV penalizes both directions symmetrically, but QLIKE specifically penalizes under-prediction more harshly — the relevant asymmetry for risk-management early-warning use cases.
