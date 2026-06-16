# K1515 PoC — Bond Illiquidity Prediction via Cross-Market Volatility Features

**Verdict**: `NULL` (XGBoost shows no statistically significant incremental
predictive power over OLS autoregressive baseline at daily frequency.)

## 1. Research Question

Can lagged **cross-market vol features** (SPY realized vol, VIX, SPY-VIX
correlation, credit-spread proxy) improve out-of-sample (OOS) prediction of
the **HYG daily illiquidity proxy** `(High-Low)/Close` versus an OLS
autoregressive baseline?

This direction is motivated by FAJ 2024 "Predicting Corporate Bond
Illiquidity via Machine Learning" — which finds equity-market vol carries
incremental signal for bond illiquidity at intra-quarter horizons.  K1515
tests a daily, single-name (HYG-only) PoC.

## 2. Differentiation vs Prior K

| K     | Direction                                                         |
|-------|-------------------------------------------------------------------|
| K1472 | HAR + **illiquidity proxy** predicting **equity vol** (reverse)   |
| K150  | Amihud as **GARCH-X exogenous** on equity vol                     |
| K265  | Liquidity proxy as GARCH-X on equity vol                          |
| K266  | Liquidity proxy as GARCH-X on equity vol (variant)                |
| K862  | Corwin-Schultz spread cross-correlation                           |
| **K1515 (this)** | **Predict bond illiquidity** using **stock-market vol**   |

The direction (stock-vol → bond-illiq) is unique among prior K.

## 3. Data

- Source: yfinance only (no synthetic fallback by design)
- Tickers: HYG, LQD, VCIT, SPY, ^VIX
- Period: 2014-01-01 → 2026-06-15
- After feature build / dropna: **3,107 daily rows**, 7 features + 1 target

## 4. Methodology

### 4.1 Target

`target_illiq_t = (HYG_High_t − HYG_Low_t) / HYG_Close_t`

A simple within-day range-based illiquidity proxy.  Bid-ask /
Corwin-Schultz alternatives are left to v2 sensitivity.

### 4.2 Features (all lagged, t-1 information set)

| Feature                | Construction                                              |
|------------------------|-----------------------------------------------------------|
| `hyg_illiq_lag1`       | `target_illiq_t.shift(1)`                                 |
| `hyg_illiq_ma5`        | `target_illiq_t.rolling(5).mean().shift(1)`               |
| `hyg_illiq_ma22`       | `target_illiq_t.rolling(22).mean().shift(1)`              |
| `spy_rv22`             | `std(log SPY_ret, 22d) * sqrt(252)` then `.shift(1)`      |
| `vix_lag1`             | `^VIX_close.shift(1)`                                     |
| `credit_spread_ma5`    | `(HYG_ret - LQD_ret).rolling(5).mean().shift(1)`          |
| `spy_vix_corr22`       | `SPY_ret.rolling(22).corr(VIX_change).shift(1)`           |

### 4.3 Lookahead Defenses

1. Every non-target column uses an explicit `.shift(1)` before being merged
   into the feature frame.  This is auditable via `grep '\.shift(1)'
   k1515.py` returning a match for every predictor.
2. All rolling statistics use **trailing** windows (pandas default).
3. Train/OOS split is **strictly temporal** — train ≤ 2022-12-31, OOS ≥
   2023-01-01 — never a random shuffle.
4. XGBoost gets `random_state=42` and no early-stopping on OOS data.

### 4.4 Models

- **OLS**: `sklearn.linear_model.LinearRegression` (intercept + 7 features)
- **XGBoost**: `n_estimators=300`, `max_depth=4`, `learning_rate=0.05`,
  `random_state=42`, no HPO (PoC scope, sensitivity left to v2)
- Identical feature set, identical lag treatment — baseline parity enforced.

### 4.5 Metrics

- OOS R² and RMSE for each model
- Diebold-Mariano test on squared-error loss difference
  (`d_t = e_OLS_t^2 − e_XGB_t^2`), large-sample normal approximation,
  two-sided p-value

## 5. Results

| Metric                  | OLS       | XGBoost   |
|-------------------------|-----------|-----------|
| OOS R²                  | 0.4315    | 0.4347    |
| OOS RMSE                | (see results.json) | (see results.json) |

- Δ R² (XGB − OLS) = **+0.0032** — economically trivial
- DM statistic: **0.049**, p-value: **0.961**  → cannot reject equal
  forecasting accuracy
- N train = 2,243; N OOS = 864

## 6. Interpretation

The OLS autoregressive baseline already captures ~43% of OOS variance — the
HYG illiquidity proxy is highly persistent at daily horizon, and 1-day +
5-day + 22-day MAs explain nearly everything that cross-market vol features
could plausibly add.  **Important framing caveat** (Codex review 2026-06-16): the DM test compares
XGBoost vs OLS *given the same 7-feature set* (AR + cross-market). It
therefore tests **model-class power** (gradient boosting vs linear), not
**feature-set power** (cross-market vs AR-only). The legitimate claim is
narrower: XGBoost does not extract significantly more signal than OLS from
the joint AR+XMKT feature set at daily frequency. Whether the XMKT subset
adds incremental power *over AR-only OLS* requires a separate AR-only
baseline run — flagged for v2.

With that caveat, on the joint feature set the result indicates **the linear
mapping already saturates whatever predictive content these 7 daily-lagged
features carry**; non-linear interactions XGB might exploit do not materialize
in OOS. The VIX feature importance (0.46) is an in-sample split-gain
statistic and does not translate into OOS forecast improvement.

This is consistent with two narratives:
- (a) Bond microstructure illiquidity is dominated by own-process inertia
  at daily horizon — equity-vol shocks transmit too slowly / are already
  priced in by t-1 close.
- (b) FAJ 2024's incremental-power result is documented at **monthly**
  horizon and uses a richer feature set (TRACE-based illiquidity, not
  range-based) — daily PoC with simplistic proxy is the wrong design to
  re-detect that effect.

## 7. Caveats / Limitations

1. **Single-name** (HYG only).  v2 should add LQD, VCIT, EMB, MUB as panel.
2. **Range-based proxy** is a crude illiquidity measure — Roll, Amihud, or
   Corwin-Schultz alternatives might surface effects that high-low misses.
3. **Daily frequency** is likely wrong horizon — monthly / weekly aggregated
   illiquidity vs lagged vol-regime indicators is more theoretically
   defensible.
4. **No HPO** for XGBoost — defaults may underfit.  Stricter test would
   tune via expanding-window CV on training period.
5. **No regime split** — averaging across 2020 COVID stress + 2023-26 calm
   may mask conditional incremental power that only appears in stress.
6. **DM test** uses iid normal approximation, no Newey-West HAC adjustment
   for h=1 forecast — acceptable for this large N but should be HLN-corrected
   for any v2.

## 8. References

1. Bao, J., Pan, J., & Wang, J. (2011). The illiquidity of corporate bonds.
   *Journal of Finance*, 66(3), 911–946.
2. Dick-Nielsen, J., Feldhütter, P., & Lando, D. (2012). Corporate bond
   liquidity before and after the onset of the subprime crisis. *Journal of
   Financial Economics*, 103(3), 471–492.
3. Bali, T. G., Subrahmanyam, A., & Wen, Q. (2024). Predicting Corporate
   Bond Illiquidity via Machine Learning. *Financial Analysts Journal*
   (motivating paper for K1515).
4. Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy.
   *Journal of Business & Economic Statistics*, 13(3), 253–263.
5. Corwin, S. A., & Schultz, P. (2012). A simple way to estimate bid-ask
   spreads from daily high and low prices. *Journal of Finance*, 67(2),
   719–760.

## 9. Reproducibility

```bash
uv run python experiments/k1515_bond_illiquidity_xmkt_vol/k1515.py
```

Outputs:
- `k1515_results.json` — full metrics
- `k1515_plots.png` — actual vs predicted + feature importance

Random seed = 42, pinned package versions noted in
`reproducibility` block of `k1515_results.json`.
