"""
K426: Efficient GARCH-Informed Neural Network (GINN) for Volatility Forecasting

Background:
- K419 attempted GINN but timed out (exit 144) due to inefficient code
- This re-implements with high-efficiency algorithms
- GINN concept (arXiv 2410.00288): GARCH as feature extractor → ML corrector

Efficiency optimizations:
1. Pre-compute ALL GARCH features once (not per-window)
2. Refit GARCH every 21 days (not daily) — ~24 refits vs 504
3. Use MLP (sklearn MLPRegressor) instead of LSTM — no sequential overhead
4. Vectorized feature engineering with pandas rolling
5. Target runtime: < 3 minutes

CRITICAL: All features are STRICTLY LAGGED (t-1 and earlier).
We predict RV_t = r_t^2 using only information available at end of day t-1.
No contemporaneous features allowed — this prevents the data leakage that would
make Ridge achieve r=1.0 (trivially copying ret_sq as the prediction).

Prior knowledge:
- K419: GINN failed (exit 144, timeout/OOM)
- QLIKE ceiling confirmed 13+ times: GJR-GARCH optimal at daily freq
- P23/P33/R10/T5c: GARCH-MIDAS, MS-GARCH, CARR, CAViaR all OOS NS vs GJR
- Only 5-min RV (Realized GARCH pilot -18%) potentially breaks ceiling

Experiment Design:
- Asset: SPY, Data: 2005-01-01 ~ 2026-03-25
- OOS: 2023-01-01 ~ 2024-12-31 (>=504 days)
- Models: GJR-GARCH baseline vs GINN-MLP vs GINN-Ridge
- Proxy: RV = return^2 (daily standard)
- Metrics: QLIKE, MSE, MAE + DM test
- ALL features use lag >= 1 (no look-ahead bias)

Data: yfinance SPY daily
Output: experiments/k426_efficient_ginn_results.json
"""

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from sklearn.neural_network import MLPRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from scipy import stats
import json
import time
import warnings
from datetime import datetime, timezone

warnings.filterwarnings('ignore')

print("=" * 75)
print("K426: Efficient GARCH-Informed Neural Network (GINN)")
print("  [ALL features strictly lagged — no contemporaneous data]")
print("=" * 75)

t_start = time.time()

# ============================================================
# STEP 1: Data Download & Diagnostics
# ============================================================
print("\n--- Step 1: Data Download & Diagnostics ---")

spy = yf.download('SPY', start='2005-01-01', end='2026-03-25', progress=False)
close = spy['Close'].squeeze().dropna()
returns = 100 * close.pct_change().dropna()
rv = returns ** 2  # realized variance proxy: r_t^2

print(f"Data period: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(returns)}")
print(f"\nDescriptive statistics (returns %):")
print(f"  Mean:     {returns.mean():.4f}")
print(f"  Std:      {returns.std():.4f}")
print(f"  Skewness: {returns.skew():.4f}")
print(f"  Kurtosis: {returns.kurtosis():.4f}")
print(f"  Min:      {returns.min():.4f}")
print(f"  Max:      {returns.max():.4f}")

# ADF test
from statsmodels.tsa.stattools import adfuller
adf_stat, adf_p, _, _, _, _ = adfuller(returns.values, maxlag=20)
print(f"\nADF test: stat={adf_stat:.4f}, p={adf_p:.6f} -> {'Stationary' if adf_p < 0.05 else 'Non-stationary'}")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_lm_stat, arch_lm_p, _, _ = het_arch(returns.values, nlags=10)
print(f"ARCH LM test (10 lags): stat={arch_lm_stat:.4f}, p={arch_lm_p:.6f} -> {'ARCH effects' if arch_lm_p < 0.05 else 'No ARCH'}")

# Ljung-Box on squared returns
from statsmodels.stats.diagnostic import acorr_ljungbox
lb = acorr_ljungbox(returns.values**2, lags=[10], return_df=True)
lb_stat = lb['lb_stat'].values[0]
lb_p = lb['lb_pvalue'].values[0]
print(f"Ljung-Box on r^2(10): stat={lb_stat:.4f}, p={lb_p:.6f} -> {'Autocorrelated' if lb_p < 0.05 else 'No autocorrelation'}")

# ============================================================
# STEP 2: Define OOS period and feature engineering
# ALL FEATURES ARE LAGGED (available at t-1 to predict t)
# ============================================================
print("\n--- Step 2: OOS Setup & Feature Engineering (STRICTLY LAGGED) ---")

oos_start = '2023-01-01'
oos_end = '2024-12-31'

oos_mask = (returns.index >= oos_start) & (returns.index <= oos_end)
oos_indices = returns.index[oos_mask]
n_oos = len(oos_indices)
print(f"OOS period: {oos_start} to {oos_end}")
print(f"OOS observations: {n_oos}")

# Pre-compute ALL features (vectorized, ALL LAGGED by at least 1 day)
print("\nBuilding feature matrix (vectorized, all features lagged)...")
t_feat = time.time()

features = pd.DataFrame(index=returns.index)

# === Lagged return features (information from t-1 and earlier) ===
features['ret_lag1'] = returns.shift(1)
features['ret_lag2'] = returns.shift(2)
features['ret_lag3'] = returns.shift(3)
features['ret_lag5'] = returns.shift(5)

# Lagged squared returns (past realized variance)
features['rv_lag1'] = (returns ** 2).shift(1)
features['rv_lag2'] = (returns ** 2).shift(2)
features['rv_lag3'] = (returns ** 2).shift(3)

# Lagged absolute returns
features['abs_ret_lag1'] = returns.abs().shift(1)
features['abs_ret_lag2'] = returns.abs().shift(2)

# === Rolling volatility features (all use shift(1) to ensure lag) ===
# These are computed on data up to t-1
for w in [5, 10, 21, 63]:
    features[f'rstd_{w}d_lag1'] = returns.rolling(w).std().shift(1)

# Rolling mean absolute return (proxy for vol)
for w in [5, 21]:
    features[f'rmean_abs_{w}d_lag1'] = returns.abs().rolling(w).mean().shift(1)

# === Asymmetry features (leverage effect, lagged) ===
neg_ret = (returns < 0).astype(float) * returns.abs()
features['neg_ret_lag1'] = neg_ret.shift(1)
features['neg_ret_lag2'] = neg_ret.shift(2)
features['leverage_5d_lag1'] = neg_ret.rolling(5).mean().shift(1)
features['leverage_21d_lag1'] = neg_ret.rolling(21).mean().shift(1)

# === Volatility-of-volatility (lagged) ===
features['vol_of_vol_21d_lag1'] = returns.rolling(5).std().rolling(21).std().shift(1)

# === Return momentum (lagged sums) ===
features['ret_5d_lag1'] = returns.rolling(5).sum().shift(1)
features['ret_21d_lag1'] = returns.rolling(21).sum().shift(1)

# === Range-based vol proxy (lagged) ===
if 'High' in spy.columns and 'Low' in spy.columns:
    high = spy['High'].squeeze()
    low = spy['Low'].squeeze()
    parkinson_vol = (np.log(high / low) ** 2 / (4 * np.log(2)))
    features['parkinson_lag1'] = parkinson_vol.reindex(returns.index).shift(1)

# === Volume features (lagged) ===
if 'Volume' in spy.columns:
    vol = spy['Volume'].squeeze().reindex(returns.index)
    features['volume_change_lag1'] = vol.pct_change().shift(1)
    features['volume_21d_ratio_lag1'] = (vol / vol.rolling(21).mean()).shift(1)

print(f"  Raw feature matrix shape: {features.shape}")
print(f"  Features: {list(features.columns)}")
print(f"  Feature engineering time: {time.time() - t_feat:.2f}s")

# Drop NaN rows (from rolling windows + lags)
features_clean = features.dropna()
rv_aligned = rv.loc[features_clean.index]
returns_aligned = returns.loc[features_clean.index]

print(f"  After dropna: {len(features_clean)} observations")
print(f"\n  LEAKAGE CHECK: All features use shift(1) or greater.")
print(f"  No contemporaneous ret, ret_sq, abs_ret, or garch_ratio in features.")

# ============================================================
# STEP 3: GARCH Rolling Forecast (refit every 21 days)
# ============================================================
print("\n--- Step 3: GARCH Rolling Forecast (refit every 21 days) ---")

t_garch = time.time()
train_window = 2000
refit_every = 21

# OOS dates within our cleaned feature set
oos_feat_mask = (features_clean.index >= oos_start) & (features_clean.index <= oos_end)
oos_dates = features_clean.index[oos_feat_mask]
n_oos_actual = len(oos_dates)
print(f"OOS dates in feature matrix: {n_oos_actual}")

# Position mapping for fast slicing
all_dates = features_clean.index
date_to_pos = {d: i for i, d in enumerate(all_dates)}

# Storage for GARCH forecasts (OOS)
garch_var_oos = pd.Series(index=oos_dates, dtype=float)

# First: fit on training window before OOS to get initial params and cond var
first_oos_pos = date_to_pos[oos_dates[0]]
train_start_pos = max(0, first_oos_pos - train_window)

# Full in-sample fit for training conditional variance
train_returns = returns_aligned.iloc[train_start_pos:first_oos_pos]
am_full = arch_model(train_returns, vol='GARCH', p=1, o=1, q=1, dist='t')
res_full = am_full.fit(disp='off', show_warning=False)
cond_var_train = res_full.conditional_volatility ** 2

print(f"  GJR-GARCH params (initial fit on {len(train_returns)} obs):")
print(f"    omega={res_full.params.get('omega', 'N/A'):.6f}")
print(f"    alpha={res_full.params.get('alpha[1]', 'N/A'):.6f}")
print(f"    gamma={res_full.params.get('gamma[1]', 'N/A'):.6f}")
print(f"    beta ={res_full.params.get('beta[1]', 'N/A'):.6f}")
persistence = (res_full.params.get('alpha[1]', 0) +
               res_full.params.get('gamma[1]', 0) / 2 +
               res_full.params.get('beta[1]', 0))
print(f"    persistence={persistence:.6f} {'(< 1 OK)' if persistence < 1 else '(>= 1 WARNING)'}")

# Convergence check
if not res_full.convergence_flag == 0:
    print(f"  WARNING: GARCH convergence flag = {res_full.convergence_flag}")

# Standardized residual diagnostics
std_resid_garch = res_full.std_resid
lb_std = acorr_ljungbox(std_resid_garch**2, lags=[10], return_df=True)
lb_std_p = lb_std['lb_pvalue'].values[0]
print(f"  Std residual^2 LB(10): p={lb_std_p:.4f} -> {'Remaining ARCH' if lb_std_p < 0.05 else 'No remaining ARCH (good)'}")

# OOS rolling forecasts with refit every 21 days
n_refits = 0
current_omega = res_full.params.get('omega', 0.01)
current_alpha = res_full.params.get('alpha[1]', 0.05)
current_gamma = res_full.params.get('gamma[1]', 0.05)
current_beta = res_full.params.get('beta[1]', 0.90)

print(f"\n  Running OOS forecasts ({n_oos_actual} days, refit every {refit_every} days)...")

for i, date in enumerate(oos_dates):
    pos = date_to_pos[date]

    if i % refit_every == 0:
        # Refit GARCH on trailing window
        t_start_idx = max(0, pos - train_window)
        train_ret = returns_aligned.iloc[t_start_idx:pos]

        try:
            am = arch_model(train_ret, vol='GARCH', p=1, o=1, q=1, dist='t')
            res = am.fit(disp='off', show_warning=False)

            current_omega = res.params.get('omega', 0.01)
            current_alpha = res.params.get('alpha[1]', 0.05)
            current_gamma = res.params.get('gamma[1]', 0.05)
            current_beta = res.params.get('beta[1]', 0.90)

            # 1-step forecast from fitted model
            fcast = res.forecast(horizon=1)
            garch_var_oos.iloc[i] = fcast.variance.values[-1, 0]
            n_refits += 1
        except Exception as e:
            garch_var_oos.iloc[i] = train_ret.var()
    else:
        # Use GJR-GARCH recursion: h_t = omega + alpha*r^2_{t-1} + gamma*I(r<0)*r^2_{t-1} + beta*h_{t-1}
        prev_ret = returns_aligned.iloc[pos - 1]
        prev_var = garch_var_oos.iloc[i - 1] if i > 0 else returns_aligned.iloc[pos-train_window:pos].var()

        indicator = 1.0 if prev_ret < 0 else 0.0
        h_t = (current_omega +
               current_alpha * prev_ret**2 +
               current_gamma * indicator * prev_ret**2 +
               current_beta * prev_var)
        garch_var_oos.iloc[i] = max(h_t, 0.001)

    if (i + 1) % 100 == 0:
        print(f"    {i+1}/{n_oos_actual} done...")

print(f"  GARCH forecasting done: {n_refits} refits, {time.time() - t_garch:.2f}s")

# ============================================================
# STEP 4: Build ML training set with GARCH as feature
# ============================================================
print("\n--- Step 4: Building ML Training & Test Sets ---")
t_ml = time.time()

# For training: need GARCH conditional variance as a feature (lagged)
# Use the in-sample conditional variance from the full fit
train_dates = features_clean.index[train_start_pos:first_oos_pos]

# Build GARCH variance feature for training period (lagged by 1 day)
garch_var_train = pd.Series(index=train_dates, dtype=float)
for d in train_dates:
    if d in cond_var_train.index:
        garch_var_train[d] = cond_var_train[d]
    else:
        garch_var_train[d] = np.nan

# GARCH feature: lagged by 1 (h_{t|t-1} is already a forecast for t, made at t-1)
# But conditional variance from arch is h_t estimated using info up to t-1, so it IS a legitimate feature
# However, to be safe, we shift by 1 as well
features_with_garch = features_clean.copy()
garch_combined = pd.concat([garch_var_train, garch_var_oos])
features_with_garch['garch_h_lag1'] = garch_combined.shift(1)  # LAGGED

# Log GARCH variance (often more stable for ML)
features_with_garch['log_garch_h_lag1'] = np.log(features_with_garch['garch_h_lag1'].clip(lower=0.001))

# Ratio: past RV / GARCH prediction (measures GARCH error, lagged)
features_with_garch['rv_garch_ratio_lag1'] = (
    features_with_garch['rv_lag1'] / features_with_garch['garch_h_lag1'].clip(lower=0.001)
)

# All feature columns (everything except what we're predicting)
feat_cols = [c for c in features_with_garch.columns]
print(f"  Total features: {len(feat_cols)}")
print(f"  Feature list: {feat_cols}")

# Build train/test split
train_data = features_with_garch.loc[train_dates].dropna()
test_data = features_with_garch.loc[oos_dates].dropna()

X_train = train_data[feat_cols].values
y_train = rv_aligned.loc[train_data.index].values

X_test = test_data[feat_cols].values
y_test = rv_aligned.loc[test_data.index].values

print(f"\n  Training set: {X_train.shape[0]} x {X_train.shape[1]} features")
print(f"  Test set:     {X_test.shape[0]} x {X_test.shape[1]} features")

# Sanity check: correlation between features and target
print(f"\n  LEAKAGE SANITY CHECK (feature-target correlations):")
for j, col in enumerate(feat_cols):
    corr_val = np.corrcoef(X_train[:, j], y_train)[0, 1]
    if abs(corr_val) > 0.8:
        print(f"    WARNING: {col} has |corr|={abs(corr_val):.3f} with target!")
    elif abs(corr_val) > 0.5:
        print(f"    NOTE: {col} corr={corr_val:.3f}")

max_corr = max(abs(np.corrcoef(X_train[:, j], y_train)[0, 1]) for j in range(X_train.shape[1]))
print(f"  Max |feature-target corr|: {max_corr:.3f}")
if max_corr > 0.9:
    print("  *** POTENTIAL LEAKAGE DETECTED — review features ***")
elif max_corr < 0.5:
    print("  No leakage detected (all correlations < 0.5)")
else:
    print("  Moderate correlations — expected for lagged vol features")

# Scale features
scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train)
X_test_scaled = scaler.transform(X_test)

# ============================================================
# STEP 5: Train Models
# ============================================================
print("\n--- Step 5: Training Models ---")

# Model 1: GINN-MLP (2 hidden layers)
print("  Training GINN-MLP (64-32, relu, adam)...")
t_mlp = time.time()
mlp = MLPRegressor(
    hidden_layer_sizes=(64, 32),
    activation='relu',
    solver='adam',
    max_iter=500,
    early_stopping=True,
    validation_fraction=0.15,
    n_iter_no_change=20,
    random_state=42,
    learning_rate_init=0.001,
    batch_size=128,
)
mlp.fit(X_train_scaled, y_train)
mlp_pred = mlp.predict(X_test_scaled)
mlp_pred = np.maximum(mlp_pred, 0.001)  # floor to prevent negative/zero
mlp_time = time.time() - t_mlp
print(f"    Training time: {mlp_time:.2f}s, iterations: {mlp.n_iter_}")

# Model 2: GINN-Ridge (linear baseline with GARCH features)
print("  Training GINN-Ridge (alpha=1.0)...")
t_ridge = time.time()
ridge = Ridge(alpha=1.0)
ridge.fit(X_train_scaled, y_train)
ridge_pred = ridge.predict(X_test_scaled)
ridge_pred = np.maximum(ridge_pred, 0.001)
ridge_time = time.time() - t_ridge
print(f"    Training time: {ridge_time:.4f}s")

# Model 3: GJR-GARCH baseline (already computed)
garch_pred = garch_var_oos.loc[test_data.index].values
print(f"  GJR-GARCH baseline: {len(garch_pred)} predictions")

print(f"\n  ML setup + training time: {time.time() - t_ml:.2f}s")

# ============================================================
# STEP 6: Evaluation
# ============================================================
print("\n--- Step 6: Evaluation ---")

y_true = y_test

def qlike(actual, forecast):
    """QLIKE loss: mean(rv/forecast + log(forecast))"""
    ratio = actual / forecast
    return np.mean(ratio + np.log(forecast))

def mse_fn(actual, forecast):
    return np.mean((actual - forecast) ** 2)

def mae_fn(actual, forecast):
    return np.mean(np.abs(actual - forecast))

models = {
    'GJR-GARCH': garch_pred,
    'GINN-MLP': mlp_pred,
    'GINN-Ridge': ridge_pred,
}

results = {}
print(f"\n{'Model':<15} {'QLIKE':>10} {'MSE':>12} {'MAE':>10}")
print("-" * 50)

for name, pred in models.items():
    q = qlike(y_true, pred)
    m = mse_fn(y_true, pred)
    a = mae_fn(y_true, pred)
    results[name] = {'QLIKE': float(q), 'MSE': float(m), 'MAE': float(a)}
    print(f"{name:<15} {q:>10.4f} {m:>12.4f} {a:>10.4f}")

# Relative improvements
print(f"\n--- Relative to GJR-GARCH baseline ---")
base_q = results['GJR-GARCH']['QLIKE']
base_m = results['GJR-GARCH']['MSE']
base_a = results['GJR-GARCH']['MAE']

for name in ['GINN-MLP', 'GINN-Ridge']:
    dq = (results[name]['QLIKE'] - base_q) / abs(base_q) * 100
    dm = (results[name]['MSE'] - base_m) / base_m * 100
    da = (results[name]['MAE'] - base_a) / base_a * 100
    print(f"  {name}: QLIKE {dq:+.2f}%, MSE {dm:+.2f}%, MAE {da:+.2f}%")
    results[name]['QLIKE_pct_change'] = round(dq, 4)
    results[name]['MSE_pct_change'] = round(dm, 4)
    results[name]['MAE_pct_change'] = round(da, 4)

# ============================================================
# STEP 7: Diebold-Mariano Tests
# ============================================================
print("\n--- Step 7: Diebold-Mariano Tests ---")

def dm_test(actual, forecast1, forecast2, loss='qlike'):
    """
    Diebold-Mariano test: H0: equal predictive accuracy
    Positive stat means forecast1 worse (forecast2 better).
    """
    if loss == 'qlike':
        d1 = actual / forecast1 + np.log(forecast1)
        d2 = actual / forecast2 + np.log(forecast2)
    elif loss == 'mse':
        d1 = (actual - forecast1) ** 2
        d2 = (actual - forecast2) ** 2

    d = d1 - d2  # positive = model1 worse

    n = len(d)
    d_mean = d.mean()

    # HAC variance (Bartlett kernel)
    bandwidth = int(np.ceil(n ** (1/3)))
    gamma_0 = np.var(d, ddof=1)
    hac_var = gamma_0
    for h in range(1, bandwidth + 1):
        gamma_h = np.cov(d[h:], d[:-h])[0, 1]
        weight = 1 - h / (bandwidth + 1)
        hac_var += 2 * weight * gamma_h

    se = np.sqrt(max(hac_var, 1e-10) / n)
    dm_stat = d_mean / se
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n-1))

    return float(dm_stat), float(p_value)

print(f"\n{'Comparison':<30} {'DM-stat':>10} {'p-value':>10} {'Winner':>15}")
print("-" * 70)

dm_results = {}
for name in ['GINN-MLP', 'GINN-Ridge']:
    for loss_type in ['qlike', 'mse']:
        dm_stat, dm_p = dm_test(y_true, garch_pred, models[name], loss=loss_type)
        winner = name if dm_stat > 0 else 'GJR-GARCH'
        sig = '***' if dm_p < 0.01 else '**' if dm_p < 0.05 else '*' if dm_p < 0.10 else 'NS'
        print(f"  GJR vs {name} ({loss_type.upper():<5})  {dm_stat:>10.4f} {dm_p:>10.4f}   {winner} {sig}")

        if name not in dm_results:
            dm_results[name] = {}
        dm_results[name][loss_type.upper()] = {
            'DM_stat': round(dm_stat, 4),
            'p_value': round(dm_p, 4),
            'significant': dm_p < 0.05
        }

# ============================================================
# STEP 8: Residual Diagnostics
# ============================================================
print("\n--- Step 8: Residual Diagnostics ---")

for name, pred in models.items():
    resid = y_true - pred
    std_resid = resid / max(resid.std(), 1e-10)

    lb_res = acorr_ljungbox(std_resid, lags=[10], return_df=True)
    lb_p_res = lb_res['lb_pvalue'].values[0]

    lb_sq = acorr_ljungbox(std_resid**2, lags=[10], return_df=True)
    lb_sq_p = lb_sq['lb_pvalue'].values[0]

    print(f"  {name}: Resid LB(10) p={lb_p_res:.4f}, Resid^2 LB(10) p={lb_sq_p:.4f}")

# ============================================================
# STEP 9: Feature Importance (Permutation-based)
# ============================================================
print("\n--- Step 9: Feature Importance (Permutation, MLP) ---")

from sklearn.inspection import permutation_importance

perm_result = permutation_importance(
    mlp, X_test_scaled, y_test,
    n_repeats=10, random_state=42,
    scoring='neg_mean_squared_error'
)

importances = perm_result.importances_mean
sorted_idx = np.argsort(importances)[::-1]

print(f"\n  Top 10 features (permutation importance):")
for rank, idx in enumerate(sorted_idx[:10]):
    print(f"    {rank+1}. {feat_cols[idx]:<25} importance={importances[idx]:.4f}")

# ============================================================
# STEP 10: Prediction Correlation Analysis
# ============================================================
print("\n--- Step 10: Prediction Correlation Analysis ---")

for name, pred in models.items():
    corr = np.corrcoef(y_true, pred)[0, 1]
    rank_corr = stats.spearmanr(y_true, pred).statistic
    print(f"  {name}: Pearson r={corr:.4f}, Spearman rho={rank_corr:.4f}")

# Correlation between models
print(f"\n  Inter-model correlations:")
print(f"    GJR vs MLP:   r={np.corrcoef(garch_pred, mlp_pred)[0,1]:.4f}")
print(f"    GJR vs Ridge: r={np.corrcoef(garch_pred, ridge_pred)[0,1]:.4f}")
print(f"    MLP vs Ridge: r={np.corrcoef(mlp_pred, ridge_pred)[0,1]:.4f}")

# ============================================================
# STEP 11: Mincer-Zarnowitz Regression
# ============================================================
print("\n--- Step 11: Mincer-Zarnowitz Regression ---")

from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

for name, pred in models.items():
    X_mz = add_constant(pred)
    mz_res = OLS(y_true, X_mz).fit(cov_type='HC1')
    a, b = mz_res.params
    r2 = mz_res.rsquared
    # F-test for a=0, b=1
    f_stat = mz_res.f_test('x1=1, const=0').statistic
    f_p = mz_res.f_test('x1=1, const=0').pvalue
    print(f"  {name}: a={a:.4f}, b={b:.4f}, R2={r2:.4f}, F(a=0,b=1) p={float(f_p):.4f}")

# ============================================================
# FINAL SUMMARY
# ============================================================
total_time = time.time() - t_start

print("\n" + "=" * 75)
print("FINAL SUMMARY")
print("=" * 75)

# Determine conclusion
best_ml_name = 'GINN-MLP' if results['GINN-MLP']['QLIKE'] < results['GINN-Ridge']['QLIKE'] else 'GINN-Ridge'
best_ml_pct = results[best_ml_name].get('QLIKE_pct_change', 0)
best_ml_dm_p = dm_results[best_ml_name]['QLIKE']['p_value']
best_ml_sig = dm_results[best_ml_name]['QLIKE']['significant']

if best_ml_sig and best_ml_pct < -5:
    conclusion = f"ML IMPROVEMENT: {best_ml_name} significantly improves QLIKE by {abs(best_ml_pct):.1f}% (DM p={best_ml_dm_p:.4f})"
    verdict = "QLIKE ceiling broken by GINN"
elif best_ml_sig and best_ml_pct < 0:
    conclusion = f"MARGINAL ML IMPROVEMENT: {best_ml_name} improves QLIKE by {abs(best_ml_pct):.1f}% (DM p={best_ml_dm_p:.4f})"
    verdict = "Minor improvement, ceiling largely intact"
elif not best_ml_sig and best_ml_pct < 0:
    conclusion = f"NO SIGNIFICANT IMPROVEMENT: {best_ml_name} QLIKE {best_ml_pct:+.1f}% (DM p={best_ml_dm_p:.4f})"
    verdict = "QLIKE ceiling confirmed (14th time)"
elif best_ml_pct > 0:
    conclusion = f"ML WORSE: {best_ml_name} QLIKE {best_ml_pct:+.1f}% worse than GJR-GARCH (DM p={best_ml_dm_p:.4f})"
    verdict = "QLIKE ceiling confirmed (14th time) — ML overfits or adds noise"
else:
    conclusion = "Inconclusive"
    verdict = "Need further analysis"

print(f"\n  Conclusion: {conclusion}")
print(f"  Verdict: {verdict}")
print(f"\n  Total runtime: {total_time:.1f}s ({total_time/60:.1f} min)")
print(f"  GARCH refits: {n_refits}")
print(f"  K419 failed (exit 144 timeout). K426 completed in {total_time:.1f}s.")
print(f"  Key: refit every {refit_every} days + MLP (not LSTM) + vectorized features")

# ============================================================
# Save Results
# ============================================================
print("\n--- Saving results ---")

output = {
    "experiment_id": "K426",
    "title": "Efficient GARCH-Informed Neural Network (GINN) for Volatility Forecasting",
    "date": datetime.now(timezone.utc).isoformat(),
    "asset": "SPY",
    "data_source": "yfinance",
    "data_period": f"{returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}",
    "total_observations": int(len(returns)),
    "oos_period": f"{oos_start} to {oos_end}",
    "oos_observations": int(len(y_test)),
    "train_window": train_window,
    "refit_every": refit_every,
    "n_refits": n_refits,
    "feature_engineering": {
        "total_features": len(feat_cols),
        "feature_list": feat_cols,
        "all_lagged": True,
        "min_lag": 1,
        "leakage_check": f"Max |feature-target corr| = {max_corr:.3f}",
        "note": "ALL features strictly lagged by >= 1 day. No contemporaneous ret_sq/abs_ret/garch_ratio."
    },
    "diagnostics": {
        "ADF": {"stat": round(adf_stat, 4), "p": round(adf_p, 6), "stationary": bool(adf_p < 0.05)},
        "ARCH_LM": {"stat": round(arch_lm_stat, 4), "p": round(arch_lm_p, 6), "arch_effects": bool(arch_lm_p < 0.05)},
        "Ljung_Box_r2": {"stat": round(lb_stat, 4), "p": round(lb_p, 6), "autocorrelated": bool(lb_p < 0.05)},
        "GARCH_std_resid_sq_LB10_p": round(float(lb_std_p), 4)
    },
    "garch_params": {
        "omega": round(float(res_full.params.get('omega', 0)), 6),
        "alpha": round(float(res_full.params.get('alpha[1]', 0)), 6),
        "gamma": round(float(res_full.params.get('gamma[1]', 0)), 6),
        "beta": round(float(res_full.params.get('beta[1]', 0)), 6),
        "persistence": round(float(persistence), 6),
        "convergence": int(res_full.convergence_flag) if hasattr(res_full, 'convergence_flag') else None
    },
    "models": {
        "GJR-GARCH": {
            "QLIKE": round(results['GJR-GARCH']['QLIKE'], 4),
            "MSE": round(results['GJR-GARCH']['MSE'], 4),
            "MAE": round(results['GJR-GARCH']['MAE'], 4),
        },
        "GINN-MLP": {
            "architecture": "(64, 32) relu, adam, early_stopping",
            "QLIKE": round(results['GINN-MLP']['QLIKE'], 4),
            "MSE": round(results['GINN-MLP']['MSE'], 4),
            "MAE": round(results['GINN-MLP']['MAE'], 4),
            "QLIKE_pct_change": results['GINN-MLP'].get('QLIKE_pct_change'),
            "MSE_pct_change": results['GINN-MLP'].get('MSE_pct_change'),
            "MAE_pct_change": results['GINN-MLP'].get('MAE_pct_change'),
            "training_time_s": round(mlp_time, 2),
            "n_iterations": int(mlp.n_iter_),
            "DM_test_QLIKE": dm_results['GINN-MLP']['QLIKE'],
            "DM_test_MSE": dm_results['GINN-MLP']['MSE'],
        },
        "GINN-Ridge": {
            "architecture": "Ridge(alpha=1.0)",
            "QLIKE": round(results['GINN-Ridge']['QLIKE'], 4),
            "MSE": round(results['GINN-Ridge']['MSE'], 4),
            "MAE": round(results['GINN-Ridge']['MAE'], 4),
            "QLIKE_pct_change": results['GINN-Ridge'].get('QLIKE_pct_change'),
            "MSE_pct_change": results['GINN-Ridge'].get('MSE_pct_change'),
            "MAE_pct_change": results['GINN-Ridge'].get('MAE_pct_change'),
            "training_time_s": round(ridge_time, 4),
            "DM_test_QLIKE": dm_results['GINN-Ridge']['QLIKE'],
            "DM_test_MSE": dm_results['GINN-Ridge']['MSE'],
        }
    },
    "top_features_mlp": [
        {"rank": rank+1, "feature": feat_cols[idx], "importance": round(float(importances[idx]), 4)}
        for rank, idx in enumerate(sorted_idx[:10])
    ],
    "prediction_correlations": {
        name: {
            "pearson_r": round(float(np.corrcoef(y_true, pred)[0, 1]), 4),
            "spearman_rho": round(float(stats.spearmanr(y_true, pred).statistic), 4)
        }
        for name, pred in models.items()
    },
    "conclusion": conclusion,
    "verdict": verdict,
    "total_runtime_s": round(total_time, 1),
    "k419_comparison": (
        "K419 failed (exit 144 timeout) due to inefficient per-day GARCH refit + LSTM training. "
        f"K426 completed in {total_time:.1f}s with: (1) refit every {refit_every} days ({n_refits} refits vs ~504), "
        "(2) MLP instead of LSTM, (3) vectorized feature engineering, (4) strictly lagged features (no leakage)."
    ),
    "limitations": [
        "RV proxy = return^2 (noisy, no intraday data)",
        "MLP may not capture temporal dependencies (but daily vol has weak temporal structure beyond GARCH)",
        f"Refit every {refit_every} days means params may be stale during fast regime changes",
        "Single asset (SPY) — results may differ for other assets",
        "OOS period 2023-2024 is relatively calm — extreme events may show different results",
        "Only tested MLP and Ridge — deeper architectures (CNN, Transformer) not tested"
    ]
}

with open('experiments/k426_efficient_ginn_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to experiments/k426_efficient_ginn_results.json")
print(f"  Script: experiments/k426_efficient_ginn.py")
print("  DONE.")
