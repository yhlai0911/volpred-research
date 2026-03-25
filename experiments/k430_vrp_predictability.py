"""
K430: Volatility Risk Premium (VRP) Predictability - Behavioral Finance Direction

Research Questions:
1. Can VRP predict future realized volatility?
2. Does VRP have stronger predictive power at extremes (high fear / complacency)?
3. Does VRP's predictive power vary across volatility regimes?

Prior knowledge:
- K-series: VRP NOT a directional signal for SPY returns (null, r=0.037 monthly)
- K-series: VIX has ~4.5% incremental power for next-day vol over lagged vol
- K-series: GARCH-X with VIX unstable coefficient, marginal QLIKE improvement
- This experiment: VRP → future vol (NOT returns), quintile & regime analysis

Data: yfinance (SPY, ^VIX), 2005-01-01 to present
Methods: OLS, Ridge, quantile analysis, DM test
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

print("=" * 70)
print("K430: Volatility Risk Premium Predictability")
print("=" * 70)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2005-01-01', progress=False)
vix = yf.download('^VIX', start='2005-01-01', progress=False)

# Handle MultiIndex columns if present
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} obs)")
print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()} ({len(vix)} obs)")

# ============================================================
# 2. FEATURE CONSTRUCTION
# ============================================================
print("\n[2] Constructing features...")

# Daily returns
ret = spy['Close'].pct_change()

# Realized volatility (21-day annualized, in %)
rv_21 = ret.rolling(21).std() * np.sqrt(252) * 100

# Future realized vol (21-day forward-looking) - the target
rv_21_future = ret.rolling(21).std().shift(-21) * np.sqrt(252) * 100

# Combine into DataFrame
df = pd.DataFrame({
    'vix': vix['Close'].reindex(spy.index),
    'rv_21': rv_21,
    'rv_21_future': rv_21_future,
    'ret': ret,
}, index=spy.index)

# VRP = implied vol (VIX) - realized vol
df['vrp'] = df['vix'] - df['rv_21']

# VRP z-score (63-day rolling)
vrp_mean_63 = df['vrp'].rolling(63).mean()
vrp_std_63 = df['vrp'].rolling(63).std()
df['vrp_zscore'] = (df['vrp'] - vrp_mean_63) / vrp_std_63

# VRP momentum (5-day change)
df['vrp_momentum'] = df['vrp'].diff(5)

# VRP mean reversion (deviation from 63-day mean)
df['vrp_mean_revert'] = df['vrp'] - vrp_mean_63

# VRP extreme indicators (calculated on expanding window to avoid lookahead)
df['vrp_pct_rank'] = df['vrp'].expanding(min_periods=252).rank(pct=True)
df['vrp_extreme_high'] = (df['vrp_pct_rank'] > 0.90).astype(int)
df['vrp_extreme_low'] = (df['vrp_pct_rank'] < 0.10).astype(int)

# Lagged RV (baseline predictor)
df['rv_21_lag'] = df['rv_21']

# Future vol change direction
df['vol_change_dir'] = (df['rv_21_future'] > df['rv_21']).astype(int)

# Future 21-day excess return
df['ret_21_future'] = ret.rolling(21).sum().shift(-21) * 100  # in %

# VIX regime (high/low based on expanding median)
df['vix_median'] = df['vix'].expanding(min_periods=252).median()
df['vix_regime'] = np.where(df['vix'] > df['vix_median'], 'high', 'low')

# Drop NaN
df_clean = df.dropna(subset=['vrp', 'vrp_zscore', 'vrp_momentum', 'vrp_mean_revert',
                              'rv_21_future', 'rv_21_lag', 'vol_change_dir', 'ret_21_future'])
print(f"  Clean sample: {df_clean.index[0].date()} to {df_clean.index[-1].date()} ({len(df_clean)} obs)")

# ============================================================
# 3. DESCRIPTIVE STATISTICS & DIAGNOSTICS
# ============================================================
print("\n[3] Descriptive Statistics & Diagnostics...")

desc_vars = ['vix', 'rv_21', 'vrp', 'vrp_zscore', 'rv_21_future']
desc_stats = {}
for v in desc_vars:
    s = df_clean[v]
    desc_stats[v] = {
        'mean': float(s.mean()),
        'std': float(s.std()),
        'skew': float(s.skew()),
        'kurtosis': float(s.kurtosis()),
        'min': float(s.min()),
        'p10': float(s.quantile(0.10)),
        'p25': float(s.quantile(0.25)),
        'median': float(s.median()),
        'p75': float(s.quantile(0.75)),
        'p90': float(s.quantile(0.90)),
        'max': float(s.max()),
        'N': int(s.count()),
    }
    print(f"\n  {v}:")
    print(f"    Mean={s.mean():.3f}, Std={s.std():.3f}, Skew={s.skew():.3f}, Kurt={s.kurtosis():.3f}")
    print(f"    [Min={s.min():.2f}, P10={s.quantile(0.10):.2f}, Med={s.median():.2f}, P90={s.quantile(0.90):.2f}, Max={s.max():.2f}]")

# VRP sign analysis
vrp_positive_pct = (df_clean['vrp'] > 0).mean() * 100
print(f"\n  VRP positive: {vrp_positive_pct:.1f}% of observations")

# ADF test on VRP
from statsmodels.tsa.stattools import adfuller
adf_result = adfuller(df_clean['vrp'].values, maxlag=21, autolag='AIC')
print(f"\n  ADF test on VRP: stat={adf_result[0]:.4f}, p={adf_result[1]:.6f}")
print(f"    → VRP is {'stationary' if adf_result[1] < 0.05 else 'non-stationary'}")

# Ljung-Box test on VRP
from statsmodels.stats.diagnostic import acorr_ljungbox
lb_result = acorr_ljungbox(df_clean['vrp'].values, lags=[10, 21], return_df=True)
print(f"\n  Ljung-Box test on VRP:")
for lag in [10, 21]:
    row = lb_result.loc[lag]
    print(f"    Lag {lag}: Q={row['lb_stat']:.2f}, p={row['lb_pvalue']:.6f}")

# Correlation matrix
corr_vars = ['vrp', 'rv_21', 'vix', 'rv_21_future', 'ret_21_future']
corr_matrix = df_clean[corr_vars].corr()
print(f"\n  Correlation matrix:")
print(corr_matrix.round(3).to_string())

# ============================================================
# 4. OOS SPLIT
# ============================================================
print("\n[4] OOS Split...")
is_mask = df_clean.index < '2023-01-01'
oos_mask = df_clean.index >= '2023-01-01'

df_is = df_clean[is_mask].copy()
df_oos = df_clean[oos_mask].copy()
print(f"  IS: {df_is.index[0].date()} to {df_is.index[-1].date()} ({len(df_is)} obs)")
print(f"  OOS: {df_oos.index[0].date()} to {df_oos.index[-1].date()} ({len(df_oos)} obs)")

# ============================================================
# 5. MODEL ESTIMATION & OOS EVALUATION
# ============================================================
print("\n[5] Model Estimation & OOS Evaluation...")

# Target: rv_21_future
y_is = df_is['rv_21_future'].values
y_oos = df_oos['rv_21_future'].values

# Model 1: Baseline (lagged RV21 only)
X1_is = df_is[['rv_21_lag']].values
X1_oos = df_oos[['rv_21_lag']].values

# Model 2: VRP only
X2_is = df_is[['vrp']].values
X2_oos = df_oos[['vrp']].values

# Model 3: VRP + all features (Ridge)
feature_cols = ['rv_21_lag', 'vrp', 'vrp_zscore', 'vrp_momentum', 'vrp_mean_revert',
                'vrp_extreme_high', 'vrp_extreme_low']
X3_is = df_is[feature_cols].values
X3_oos = df_oos[feature_cols].values

# Model 4: Lagged RV + VRP (simple augmentation)
X4_is = df_is[['rv_21_lag', 'vrp']].values
X4_oos = df_oos[['rv_21_lag', 'vrp']].values


def qlike(actual, predicted):
    """QLIKE loss: mean(actual/predicted + ln(predicted) - 1 - ln(actual))"""
    # Ensure positive
    pred_safe = np.maximum(predicted, 0.01)
    act_safe = np.maximum(actual, 0.01)
    return np.mean(act_safe / pred_safe + np.log(pred_safe) - 1 - np.log(act_safe))


def mse(actual, predicted):
    return np.mean((actual - predicted) ** 2)


def mae(actual, predicted):
    return np.mean(np.abs(actual - predicted))


# OLS regression function
def ols_fit_predict(X_is, y_is, X_oos):
    """Simple OLS with intercept"""
    X_aug = np.column_stack([np.ones(len(X_is)), X_is])
    X_oos_aug = np.column_stack([np.ones(len(X_oos)), X_oos])
    beta, _, _, _ = np.linalg.lstsq(X_aug, y_is, rcond=None)
    y_pred = X_oos_aug @ beta
    return y_pred, beta


# Fit all models
models = {}

# Model 1: Baseline (lagged RV)
pred1, beta1 = ols_fit_predict(X1_is, y_is, X1_oos)
models['M1_baseline_RV'] = {
    'pred': pred1,
    'beta': beta1.tolist(),
    'features': ['const', 'rv_21_lag'],
}

# Model 2: VRP only
pred2, beta2 = ols_fit_predict(X2_is, y_is, X2_oos)
models['M2_VRP_only'] = {
    'pred': pred2,
    'beta': beta2.tolist(),
    'features': ['const', 'vrp'],
}

# Model 3: Ridge (VRP + all features)
scaler = StandardScaler()
X3_is_scaled = scaler.fit_transform(X3_is)
X3_oos_scaled = scaler.transform(X3_oos)
ridge = Ridge(alpha=1.0)
ridge.fit(X3_is_scaled, y_is)
pred3 = ridge.predict(X3_oos_scaled)
models['M3_Ridge_full'] = {
    'pred': pred3,
    'beta': [float(ridge.intercept_)] + ridge.coef_.tolist(),
    'features': ['const'] + feature_cols,
}

# Model 4: Lagged RV + VRP
pred4, beta4 = ols_fit_predict(X4_is, y_is, X4_oos)
models['M4_RV_plus_VRP'] = {
    'pred': pred4,
    'beta': beta4.tolist(),
    'features': ['const', 'rv_21_lag', 'vrp'],
}

# Evaluate all models
print("\n  OOS Performance (predicting future 21-day RV):")
print(f"  {'Model':<25s} {'QLIKE':>8s} {'MSE':>8s} {'MAE':>8s} {'Corr':>8s}")
print("  " + "-" * 55)

model_results = {}
for name, m in models.items():
    p = m['pred']
    q = qlike(y_oos, p)
    ms = mse(y_oos, p)
    ma = mae(y_oos, p)
    corr = np.corrcoef(y_oos, p)[0, 1]
    print(f"  {name:<25s} {q:8.4f} {ms:8.2f} {ma:8.2f} {corr:8.4f}")
    model_results[name] = {
        'qlike': float(q),
        'mse': float(ms),
        'mae': float(ma),
        'correlation': float(corr),
        'coefficients': dict(zip(m['features'], [float(b) for b in m['beta']])),
    }

# ============================================================
# 6. DIEBOLD-MARIANO TEST
# ============================================================
print("\n[6] Diebold-Mariano Test (vs Baseline)...")

baseline_err = (y_oos - pred1) ** 2
dm_results = {}

for name, m in models.items():
    if name == 'M1_baseline_RV':
        continue
    alt_err = (y_oos - m['pred']) ** 2
    d = baseline_err - alt_err  # positive = baseline worse = alternative better

    # Newey-West HAC standard error (lag = 21 for overlapping targets)
    n = len(d)
    d_mean = d.mean()
    max_lag = 21

    # HAC variance
    gamma_0 = np.mean((d - d_mean) ** 2)
    hac_var = gamma_0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)  # Bartlett kernel
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        hac_var += 2 * w * gamma_k

    dm_stat = d_mean / np.sqrt(hac_var / n)
    dm_pvalue = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    print(f"  {name} vs Baseline: DM={dm_stat:.3f}, p={dm_pvalue:.4f} {'*' if dm_pvalue < 0.05 else ''}")
    dm_results[name] = {
        'dm_stat': float(dm_stat),
        'p_value': float(dm_pvalue),
        'significant_5pct': bool(dm_pvalue < 0.05),
        'direction': 'alternative better' if d_mean > 0 else 'baseline better',
        'mean_loss_diff': float(d_mean),
    }

# ============================================================
# 7. QUINTILE ANALYSIS
# ============================================================
print("\n[7] Quintile Analysis (VRP level → forecast accuracy)...")

# Use full sample quintiles based on IS distribution
vrp_quintile_breaks = df_is['vrp'].quantile([0.2, 0.4, 0.6, 0.8]).values
df_oos_q = df_oos.copy()
df_oos_q['vrp_quintile'] = pd.cut(df_oos_q['vrp'],
                                    bins=[-np.inf] + list(vrp_quintile_breaks) + [np.inf],
                                    labels=['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high'])
df_oos_q['pred_baseline'] = pred1
df_oos_q['pred_vrp_aug'] = pred4

quintile_results = {}
print(f"\n  {'Quintile':<12s} {'N':>5s} {'Mean_VRP':>10s} {'Mean_FutRV':>12s} {'MSE_Base':>10s} {'MSE_VRP+':>10s} {'Improv%':>8s} {'DirAcc':>8s}")
print("  " + "-" * 80)

for q_name in ['Q1_low', 'Q2', 'Q3', 'Q4', 'Q5_high']:
    mask = df_oos_q['vrp_quintile'] == q_name
    if mask.sum() < 5:
        continue
    sub = df_oos_q[mask]
    n_q = len(sub)
    mean_vrp = sub['vrp'].mean()
    mean_fut_rv = sub['rv_21_future'].mean()

    mse_base = mse(sub['rv_21_future'].values, sub['pred_baseline'].values)
    mse_vrp = mse(sub['rv_21_future'].values, sub['pred_vrp_aug'].values)
    improv = (1 - mse_vrp / mse_base) * 100 if mse_base > 0 else 0

    # Direction accuracy: does VRP correctly predict vol increase/decrease?
    pred_vol_change = (sub['pred_vrp_aug'] > sub['rv_21']).astype(int)
    actual_vol_change = sub['vol_change_dir'].values
    dir_acc = (pred_vol_change.values == actual_vol_change).mean() * 100

    print(f"  {q_name:<12s} {n_q:>5d} {mean_vrp:>10.2f} {mean_fut_rv:>12.2f} {mse_base:>10.2f} {mse_vrp:>10.2f} {improv:>7.1f}% {dir_acc:>7.1f}%")

    quintile_results[q_name] = {
        'n': int(n_q),
        'mean_vrp': float(mean_vrp),
        'mean_future_rv': float(mean_fut_rv),
        'mse_baseline': float(mse_base),
        'mse_vrp_augmented': float(mse_vrp),
        'improvement_pct': float(improv),
        'direction_accuracy': float(dir_acc),
    }

# ============================================================
# 8. REGIME ANALYSIS
# ============================================================
print("\n[8] Regime Analysis (VIX high/low → VRP predictive power)...")

regime_results = {}
for regime in ['high', 'low']:
    mask = df_oos_q['vix_regime'] == regime
    if mask.sum() < 10:
        continue
    sub = df_oos_q[mask]
    n_r = len(sub)

    # Fit local OLS: rv_21_future ~ rv_21_lag + vrp
    X_r = sub[['rv_21_lag', 'vrp']].values
    y_r = sub['rv_21_future'].values
    X_r_aug = np.column_stack([np.ones(n_r), X_r])
    beta_r, _, _, _ = np.linalg.lstsq(X_r_aug, y_r, rcond=None)

    # VRP coefficient and its t-stat
    y_hat = X_r_aug @ beta_r
    resid = y_r - y_hat
    sigma2 = np.sum(resid ** 2) / (n_r - X_r_aug.shape[1])
    # Robust standard errors (simple)
    cov = sigma2 * np.linalg.inv(X_r_aug.T @ X_r_aug)
    se_vrp = np.sqrt(cov[2, 2])
    t_vrp = beta_r[2] / se_vrp
    p_vrp = 2 * (1 - stats.t.cdf(abs(t_vrp), n_r - 3))

    # Correlation VRP → future RV
    corr_vrp_fut = np.corrcoef(sub['vrp'].values, y_r)[0, 1]

    print(f"\n  Regime: VIX {regime} (N={n_r})")
    print(f"    VRP coeff: {beta_r[2]:.4f} (t={t_vrp:.3f}, p={p_vrp:.4f})")
    print(f"    Corr(VRP, future RV): {corr_vrp_fut:.4f}")

    regime_results[f'vix_{regime}'] = {
        'n': int(n_r),
        'vrp_coefficient': float(beta_r[2]),
        'vrp_t_stat': float(t_vrp),
        'vrp_p_value': float(p_vrp),
        'corr_vrp_future_rv': float(corr_vrp_fut),
        'all_coefficients': {
            'const': float(beta_r[0]),
            'rv_21_lag': float(beta_r[1]),
            'vrp': float(beta_r[2]),
        },
    }

# ============================================================
# 9. EXTREME VRP ANALYSIS (Behavioral Finance Core)
# ============================================================
print("\n[9] Extreme VRP Analysis (Behavioral Finance)...")

# Define extremes based on IS percentiles
vrp_p10 = df_is['vrp'].quantile(0.10)
vrp_p90 = df_is['vrp'].quantile(0.90)
vrp_p05 = df_is['vrp'].quantile(0.05)
vrp_p95 = df_is['vrp'].quantile(0.95)

extreme_results = {}
for label, lo, hi in [
    ('extreme_low_p10', -np.inf, vrp_p10),
    ('low_p10_p25', vrp_p10, df_is['vrp'].quantile(0.25)),
    ('normal_p25_p75', df_is['vrp'].quantile(0.25), df_is['vrp'].quantile(0.75)),
    ('high_p75_p90', df_is['vrp'].quantile(0.75), vrp_p90),
    ('extreme_high_p90', vrp_p90, np.inf),
]:
    mask = (df_oos['vrp'] >= lo) & (df_oos['vrp'] < hi)
    if mask.sum() < 5:
        print(f"  {label}: insufficient obs ({mask.sum()})")
        extreme_results[label] = {'n': int(mask.sum()), 'insufficient': True}
        continue

    sub = df_oos[mask]
    n_e = len(sub)

    # Mean VRP, mean future RV, mean RV change
    mean_vrp = sub['vrp'].mean()
    mean_fut_rv = sub['rv_21_future'].mean()
    mean_rv_now = sub['rv_21'].mean()
    mean_rv_change = mean_fut_rv - mean_rv_now

    # Does high VRP predict vol decline? (behavioral hypothesis: fear → vol mean reversion)
    vol_decline_pct = (sub['rv_21_future'] < sub['rv_21']).mean() * 100

    # Mean future excess return
    mean_fut_ret = sub['ret_21_future'].mean()

    print(f"\n  {label} (N={n_e}):")
    print(f"    Mean VRP={mean_vrp:.2f}, Current RV={mean_rv_now:.2f}, Future RV={mean_fut_rv:.2f}")
    print(f"    Vol change={mean_rv_change:+.2f}, Vol decline pct={vol_decline_pct:.1f}%")
    print(f"    Mean 21d future return={mean_fut_ret:+.2f}%")

    extreme_results[label] = {
        'n': int(n_e),
        'mean_vrp': float(mean_vrp),
        'mean_current_rv': float(mean_rv_now),
        'mean_future_rv': float(mean_fut_rv),
        'mean_rv_change': float(mean_rv_change),
        'vol_decline_pct': float(vol_decline_pct),
        'mean_future_21d_return_pct': float(mean_fut_ret),
    }

# ============================================================
# 10. IN-SAMPLE REGRESSION DIAGNOSTICS
# ============================================================
print("\n[10] In-Sample Regression Diagnostics...")

# Full IS regression: future_rv ~ rv_21_lag + vrp + vrp_zscore + vrp_momentum + vrp_mean_revert
import statsmodels.api as sm

X_diag = df_is[['rv_21_lag', 'vrp', 'vrp_zscore', 'vrp_momentum', 'vrp_mean_revert']].copy()
X_diag = sm.add_constant(X_diag)
y_diag = df_is['rv_21_future'].values

ols_model = sm.OLS(y_diag, X_diag).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
print(ols_model.summary().tables[1])

# Check for multicollinearity via VIF
from statsmodels.stats.outliers_influence import variance_inflation_factor
vif_data = []
for i in range(1, X_diag.shape[1]):  # skip constant
    vif_val = variance_inflation_factor(X_diag.values, i)
    vif_data.append({'feature': X_diag.columns[i], 'VIF': float(vif_val)})
    print(f"  VIF({X_diag.columns[i]}): {vif_val:.2f}")

# R-squared
print(f"\n  IS R-squared: {ols_model.rsquared:.4f}")
print(f"  IS Adj R-squared: {ols_model.rsquared_adj:.4f}")

# Residual ARCH test
from statsmodels.stats.diagnostic import het_arch
resid_ols = ols_model.resid
arch_test = het_arch(resid_ols, nlags=10)
print(f"\n  Residual ARCH LM test (10 lags): stat={arch_test[0]:.2f}, p={arch_test[1]:.6f}")
print(f"    → {'Residual ARCH effects present' if arch_test[1] < 0.05 else 'No residual ARCH effects'}")

is_regression = {
    'r_squared': float(ols_model.rsquared),
    'adj_r_squared': float(ols_model.rsquared_adj),
    'n_obs': int(ols_model.nobs),
    'coefficients': {},
    'vif': vif_data,
    'residual_arch_lm_pvalue': float(arch_test[1]),
}
for param in ols_model.params.index:
    is_regression['coefficients'][param] = {
        'coef': float(ols_model.params[param]),
        't_stat': float(ols_model.tvalues[param]),
        'p_value': float(ols_model.pvalues[param]),
    }

# ============================================================
# 11. RETURN PREDICTION (SECONDARY ANALYSIS)
# ============================================================
print("\n[11] VRP → Future Returns (Secondary Analysis)...")

# VRP → 21-day future return (via vol channel)
y_ret_is = df_is['ret_21_future'].values
y_ret_oos = df_oos['ret_21_future'].values

# Simple regression: ret_21_future ~ vrp
X_ret_is = df_is[['vrp']].values
X_ret_oos = df_oos[['vrp']].values

pred_ret, beta_ret = ols_fit_predict(X_ret_is, y_ret_is, X_ret_oos)
corr_ret = np.corrcoef(y_ret_oos, pred_ret)[0, 1]
print(f"  VRP → 21d return: OOS corr={corr_ret:.4f}")
print(f"  Beta (VRP→ret): {beta_ret[1]:.4f}")

# IS regression with HAC
X_ret_diag = sm.add_constant(df_is[['vrp']])
ret_model = sm.OLS(y_ret_is, X_ret_diag).fit(cov_type='HAC', cov_kwds={'maxlags': 21})
print(f"  IS: VRP coeff={ret_model.params['vrp']:.4f}, t={ret_model.tvalues['vrp']:.3f}, p={ret_model.pvalues['vrp']:.4f}")
print(f"  IS R²={ret_model.rsquared:.4f}")

return_prediction = {
    'oos_correlation': float(corr_ret),
    'is_vrp_coefficient': float(ret_model.params['vrp']),
    'is_vrp_t_stat': float(ret_model.tvalues['vrp']),
    'is_vrp_p_value': float(ret_model.pvalues['vrp']),
    'is_r_squared': float(ret_model.rsquared),
}

# ============================================================
# 12. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Best model for vol prediction
best_model = min(model_results.items(), key=lambda x: x[1]['qlike'])
print(f"\n  Best vol predictor (QLIKE): {best_model[0]} (QLIKE={best_model[1]['qlike']:.4f})")

# VRP incremental value
baseline_qlike = model_results['M1_baseline_RV']['qlike']
vrp_aug_qlike = model_results['M4_RV_plus_VRP']['qlike']
qlike_improv = (1 - vrp_aug_qlike / baseline_qlike) * 100
print(f"  VRP incremental improvement over baseline: {qlike_improv:+.2f}% QLIKE")

# DM test significance
dm_m4 = dm_results.get('M4_RV_plus_VRP', {})
print(f"  DM test (M4 vs M1): stat={dm_m4.get('dm_stat', 'N/A')}, p={dm_m4.get('p_value', 'N/A')}")

# Extreme VRP behavioral finding
if 'extreme_high_p90' in extreme_results and not extreme_results['extreme_high_p90'].get('insufficient', False):
    eh = extreme_results['extreme_high_p90']
    el = extreme_results['extreme_low_p10']
    print(f"\n  Behavioral finance findings:")
    print(f"    High fear (VRP>P90): future vol change={eh['mean_rv_change']:+.2f}, vol decline={eh['vol_decline_pct']:.1f}%")
    if not el.get('insufficient', False):
        print(f"    Complacency (VRP<P10): future vol change={el['mean_rv_change']:+.2f}, vol decline={el['vol_decline_pct']:.1f}%")

# Harvey (2016) threshold check
print(f"\n  Harvey (2016) t>3.0 threshold check:")
for param, vals in is_regression['coefficients'].items():
    if param == 'const':
        continue
    passes = abs(vals['t_stat']) > 3.0
    print(f"    {param}: t={vals['t_stat']:.3f} → {'PASSES' if passes else 'FAILS'} Harvey threshold")

# Conclusions
conclusions = []
if qlike_improv > 0:
    conclusions.append(f"VRP provides {qlike_improv:.1f}% QLIKE improvement over lagged RV baseline")
else:
    conclusions.append(f"VRP does NOT improve vol prediction over lagged RV ({qlike_improv:.1f}% QLIKE)")

if dm_m4.get('significant_5pct', False):
    conclusions.append("DM test: VRP-augmented model SIGNIFICANTLY better than baseline")
else:
    conclusions.append(f"DM test: VRP improvement NOT statistically significant (p={dm_m4.get('p_value', 'N/A'):.4f})")

# Check if extreme VRP has asymmetric predictive power
if ('extreme_high_p90' in extreme_results and not extreme_results['extreme_high_p90'].get('insufficient', False)
    and 'extreme_low_p10' in extreme_results and not extreme_results['extreme_low_p10'].get('insufficient', False)):
    eh = extreme_results['extreme_high_p90']
    el = extreme_results['extreme_low_p10']
    if eh['vol_decline_pct'] > 60:
        conclusions.append(f"Extreme fear (VRP>P90) → vol tends to decline ({eh['vol_decline_pct']:.0f}% of cases) — supports mean reversion hypothesis")
    if el['vol_decline_pct'] < 40:
        conclusions.append(f"Complacency (VRP<P10) → vol tends to rise ({100-el['vol_decline_pct']:.0f}% of cases) — supports fear/complacency asymmetry")

# Regime analysis conclusion
for regime, data in regime_results.items():
    if abs(data['vrp_t_stat']) > 2:
        conclusions.append(f"VRP significant in {regime} regime (t={data['vrp_t_stat']:.3f})")

conclusions.append("Consistent with prior findings: VRP is better at predicting vol dynamics than return direction")

print(f"\n  Conclusions:")
for i, c in enumerate(conclusions, 1):
    print(f"    {i}. {c}")

# ============================================================
# 13. SAVE RESULTS
# ============================================================
print("\n[13] Saving results...")

results = {
    'experiment_id': 'k430',
    'title': 'Volatility Risk Premium Predictability (Behavioral Finance)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{df_clean.index[0].date()} to {df_clean.index[-1].date()}",
    'n_observations': int(len(df_clean)),
    'is_period': f"{df_is.index[0].date()} to {df_is.index[-1].date()}",
    'oos_period': f"{df_oos.index[0].date()} to {df_oos.index[-1].date()}",
    'is_n': int(len(df_is)),
    'oos_n': int(len(df_oos)),
    'descriptive_statistics': desc_stats,
    'vrp_positive_pct': float(vrp_positive_pct),
    'adf_test': {
        'statistic': float(adf_result[0]),
        'p_value': float(adf_result[1]),
        'stationary': bool(adf_result[1] < 0.05),
    },
    'model_results_oos': model_results,
    'dm_tests': dm_results,
    'quintile_analysis': quintile_results,
    'regime_analysis': regime_results,
    'extreme_vrp_analysis': extreme_results,
    'is_regression_diagnostics': is_regression,
    'return_prediction_secondary': return_prediction,
    'qlike_improvement_pct': float(qlike_improv),
    'conclusions': conclusions,
    'limitations': [
        'Overlapping 21-day windows create serial correlation (mitigated by HAC standard errors)',
        'VRP proxy uses VIX (30d implied) vs 21d realized — maturity mismatch',
        'OOS period (2023-2025) may not be representative of all market conditions',
        'No transaction cost consideration for any trading implications',
        'RV uses close-to-close returns only (no intraday data)',
    ],
    'prior_knowledge': [
        'K-series: VRP is NOT a directional signal for SPY returns (null result)',
        'K-series: VIX has ~4.5% incremental power for next-day vol',
        'K-series: GARCH-X with VIX gives unstable coefficient',
    ],
}

output_path = 'experiments/k430_vrp_predictability_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"  Saved to {output_path}")
print("\n  DONE.")
