"""
K973: Time-Varying Hurst Exponent for Volatility Forecasting

Background:
- Rough Volatility literature (Gatheral et al. 2018): log-volatility H ~ 0.1
- K34 tested rough vol at daily freq -> NULL (H ~0.01 too noisy)
- arXiv:2509.05820 (2025): Time-Varying Hurst EWMA
- Core idea: changes in H_t contain predictive information

Methods:
1. Rolling R/S Hurst exponent (window=60)
2. Variogram-based Hurst on log|returns|
3. EWMA smoothing of Hurst
4. Augmented models: GJR + H, HAR-type with H

References:
- Gatheral, Jaisson, Rosenbaum (2018) "Volatility is Rough", QF
- Corsi (2009) "A Simple Approximate Long-Memory Model", JFE
- Patton (2011) "Volatility Forecast Comparison Using Imperfect Proxies", JoE

Data: SPY daily from yfinance, 2006-01-01 to 2026-04-07
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from arch import arch_model
from scipy import stats
import json
import warnings
import os

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K973: Time-Varying Hurst Exponent for Vol Forecasting")
print("=" * 60)

spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)

spy['return'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy = spy.dropna(subset=['return'])
spy['r_squared'] = spy['return'] ** 2  # target for GARCH eval
spy['abs_return'] = np.abs(spy['return'])
spy['log_abs_return'] = np.log(spy['abs_return'].replace(0, np.nan))

print(f"Data: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(spy)}")
print(f"Mean return: {spy['return'].mean():.6f}")
print(f"Std return:  {spy['return'].std():.6f}")

# ============================================================
# 2. HURST EXPONENT ESTIMATION
# ============================================================

def hurst_rs(series, window=60):
    """Rolling R/S Hurst exponent estimation."""
    n = len(series)
    hurst = np.full(n, np.nan)
    for t in range(window, n):
        segment = series[t - window:t]
        mean_val = np.mean(segment)
        cumdev = np.cumsum(segment - mean_val)
        R = np.max(cumdev) - np.min(cumdev)
        S = np.std(segment, ddof=1)
        if S > 0 and R > 0:
            RS = R / S
            hurst[t] = np.log(RS) / np.log(window)
        else:
            hurst[t] = np.nan
    return hurst


def hurst_variogram(log_vol_series, window=120, lags=None):
    """Rolling variogram-based Hurst exponent on log-volatility."""
    if lags is None:
        lags = [1, 2, 5, 10, 20]
    n = len(log_vol_series)
    hurst = np.full(n, np.nan)
    lags_arr = np.array(lags)
    log_lags = np.log(lags_arr)

    for t in range(window, n):
        segment = log_vol_series[t - window:t]
        if np.any(np.isnan(segment)):
            continue
        variances = []
        valid = True
        for lag in lags:
            if lag >= len(segment):
                valid = False
                break
            diff = segment[lag:] - segment[:-lag]
            v = np.var(diff)
            if v <= 0:
                valid = False
                break
            variances.append(v)
        if not valid or len(variances) != len(lags):
            continue
        log_var = np.log(np.array(variances))
        slope, _ = np.polyfit(log_lags, log_var, 1)
        hurst[t] = slope / 2.0
    return hurst


print("\nEstimating Hurst exponents...")

# R/S on absolute returns
returns_arr = spy['return'].values
h_rs = hurst_rs(returns_arr, window=60)
spy['H_rs'] = h_rs

# R/S on log|returns|
log_abs_arr = spy['log_abs_return'].values.copy()
# Fill NaN in log_abs with forward fill for estimation
mask = np.isnan(log_abs_arr)
if mask.any():
    for i in range(1, len(log_abs_arr)):
        if np.isnan(log_abs_arr[i]):
            log_abs_arr[i] = log_abs_arr[i-1] if not np.isnan(log_abs_arr[i-1]) else 0.0

h_vario = hurst_variogram(log_abs_arr, window=120)
spy['H_vario'] = h_vario

# EWMA smoothing
spy['H_rs_ewma'] = pd.Series(h_rs, index=spy.index).ewm(halflife=22).mean()
spy['H_vario_ewma'] = pd.Series(h_vario, index=spy.index).ewm(halflife=22).mean()

# Descriptive stats
for col in ['H_rs', 'H_vario', 'H_rs_ewma', 'H_vario_ewma']:
    valid = spy[col].dropna()
    print(f"\n{col}:")
    print(f"  N valid: {len(valid)}")
    print(f"  Mean: {valid.mean():.4f}")
    print(f"  Std:  {valid.std():.4f}")
    print(f"  Min:  {valid.min():.4f}")
    print(f"  Max:  {valid.max():.4f}")
    print(f"  Median: {valid.median():.4f}")

# ============================================================
# 3. H vs VOL REGIME ANALYSIS
# ============================================================
print("\n" + "=" * 60)
print("H vs Volatility Regime Analysis")
print("=" * 60)

# Rolling 22-day realized vol
spy['rv_22'] = spy['return'].rolling(22).std() * np.sqrt(252)

# Classify vol regimes
spy['vol_regime'] = pd.cut(
    spy['rv_22'],
    bins=[0, 0.10, 0.15, 0.25, 1.0],
    labels=['Low (<10%)', 'Normal (10-15%)', 'High (15-25%)', 'Crisis (>25%)']
)

# H by regime
for col in ['H_rs_ewma', 'H_vario_ewma']:
    print(f"\n{col} by vol regime:")
    regime_stats = spy.groupby('vol_regime', observed=True)[col].agg(['mean', 'std', 'count'])
    print(regime_stats.to_string())

# Correlation of H with future vol
spy['rv_22_fwd'] = spy['rv_22'].shift(-22)
for col in ['H_rs_ewma', 'H_vario_ewma']:
    valid = spy[[col, 'rv_22_fwd']].dropna()
    corr = valid[col].corr(valid['rv_22_fwd'])
    print(f"\nCorr({col}, RV_22_forward): {corr:.4f}")

# ============================================================
# 4. BASELINE GJR-GARCH(1,1) OOS FORECAST
# ============================================================
print("\n" + "=" * 60)
print("OOS Forecasting")
print("=" * 60)

# IS: 2006-2018, OOS: 2019-2026
is_end = '2018-12-31'
oos_start = '2019-01-02'

is_mask = spy.index <= is_end
oos_mask = spy.index >= oos_start

returns_full = spy['return'] * 100  # scale for GARCH
r_sq_full = spy['r_squared']

oos_idx = spy.index[oos_mask]
n_oos = len(oos_idx)
n_is = is_mask.sum()

print(f"IS: {spy.index[is_mask][0].strftime('%Y-%m-%d')} to {spy.index[is_mask][-1].strftime('%Y-%m-%d')} (n={n_is})")
print(f"OOS: {oos_idx[0].strftime('%Y-%m-%d')} to {oos_idx[-1].strftime('%Y-%m-%d')} (n={n_oos})")

# Expanding window GJR-GARCH forecasts
print("\nEstimating GJR-GARCH baseline (expanding window, refit every 22 days)...")
gjr_forecasts = pd.Series(index=oos_idx, dtype=float)

refit_interval = 22
last_fit = None

for i, date in enumerate(oos_idx):
    loc = spy.index.get_loc(date)
    train_returns = returns_full.iloc[:loc]

    if last_fit is None or i % refit_interval == 0:
        try:
            am = arch_model(train_returns, vol='GARCH', p=1, o=1, q=1, dist='t')
            res = am.fit(disp='off', options={'maxiter': 300})
            last_fit = res
        except Exception:
            pass

    if last_fit is not None:
        try:
            fcast = last_fit.forecast(horizon=1, reindex=False)
            var_fcast = fcast.variance.values[-1, 0]
            gjr_forecasts.iloc[i] = var_fcast / 10000  # convert back from %^2
        except Exception:
            gjr_forecasts.iloc[i] = np.nan

    if (i + 1) % 250 == 0:
        print(f"  GJR progress: {i+1}/{n_oos}")

print(f"  GJR forecasts: {gjr_forecasts.notna().sum()} valid")

# ============================================================
# 5. AUGMENTED MODELS
# ============================================================
print("\nEstimating augmented models...")

# Prepare lagged H features (shift(1) to avoid lookahead)
spy['H_rs_ewma_lag1'] = spy['H_rs_ewma'].shift(1)
spy['H_vario_ewma_lag1'] = spy['H_vario_ewma'].shift(1)
spy['H_rs_lag1'] = spy['H_rs'].shift(1)

# Model A: HAR-type with H
# RV_t = a + b1*RV_{t-1} + b2*RV_{t-5} + b3*RV_{t-22} + b4*H_{t-1} + e
# where RV = r^2 (daily proxy)

# Compute lagged RV features
spy['r2_lag1'] = spy['r_squared'].shift(1)
spy['r2_lag5'] = spy['r_squared'].rolling(5).mean().shift(1)
spy['r2_lag22'] = spy['r_squared'].rolling(22).mean().shift(1)

# HAR baseline (no H)
def run_har_oos(df, oos_mask, feature_cols, target='r_squared', refit_every=22):
    """Run HAR-type OOS regression with expanding window."""
    oos_idx = df.index[oos_mask]
    forecasts = pd.Series(index=oos_idx, dtype=float)

    for i, date in enumerate(oos_idx):
        loc = df.index.get_loc(date)
        train = df.iloc[:loc].dropna(subset=feature_cols + [target])

        if len(train) < 100:
            continue

        if i % refit_every == 0 or i == 0:
            X_train = train[feature_cols].values
            y_train = train[target].values

            # OLS with intercept
            X_train_c = np.column_stack([np.ones(len(X_train)), X_train])
            try:
                beta = np.linalg.lstsq(X_train_c, y_train, rcond=None)[0]
            except Exception:
                continue

        # Forecast
        x_test = df.loc[date, feature_cols].values.astype(float)
        if np.any(np.isnan(x_test)):
            continue
        x_test_c = np.concatenate([[1.0], x_test])
        forecasts.iloc[i] = max(x_test_c @ beta, 1e-10)  # floor at small positive

    return forecasts

har_features_base = ['r2_lag1', 'r2_lag5', 'r2_lag22']
har_features_h_rs = ['r2_lag1', 'r2_lag5', 'r2_lag22', 'H_rs_ewma_lag1']
har_features_h_vario = ['r2_lag1', 'r2_lag5', 'r2_lag22', 'H_vario_ewma_lag1']
har_features_h_both = ['r2_lag1', 'r2_lag5', 'r2_lag22', 'H_rs_ewma_lag1', 'H_vario_ewma_lag1']
har_features_h_raw = ['r2_lag1', 'r2_lag5', 'r2_lag22', 'H_rs_lag1']

print("  HAR baseline...")
har_base_fcast = run_har_oos(spy, oos_mask, har_features_base)

print("  HAR + H_rs_ewma...")
har_hrs_fcast = run_har_oos(spy, oos_mask, har_features_h_rs)

print("  HAR + H_vario_ewma...")
har_hvario_fcast = run_har_oos(spy, oos_mask, har_features_h_vario)

print("  HAR + H_rs + H_vario...")
har_both_fcast = run_har_oos(spy, oos_mask, har_features_h_both)

print("  HAR + H_rs (raw)...")
har_hraw_fcast = run_har_oos(spy, oos_mask, har_features_h_raw)

# ============================================================
# 6. EVALUATION
# ============================================================
print("\n" + "=" * 60)
print("OOS Evaluation (QLIKE)")
print("=" * 60)

def qlike(actual, forecast):
    """QLIKE loss: mean(actual/forecast - log(actual/forecast) - 1)"""
    valid = ~(np.isnan(actual) | np.isnan(forecast) | (forecast <= 0) | (actual <= 0))
    a = actual[valid]
    f = forecast[valid]
    return np.mean(a / f - np.log(a / f) - 1), valid.sum()

def mse(actual, forecast):
    valid = ~(np.isnan(actual) | np.isnan(forecast))
    a = actual[valid]
    f = forecast[valid]
    return np.mean((a - f) ** 2), valid.sum()

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (two-sided)."""
    d = e1 - e2
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    d_var = np.var(d, ddof=1)

    # HAC variance (Newey-West with h-1 lags)
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        d_var += 2 * (1 - k / h) * gamma_k

    if d_var <= 0:
        return np.nan, np.nan

    dm_stat = d_mean / np.sqrt(d_var / n)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return dm_stat, p_value

actual_oos = spy.loc[oos_idx, 'r_squared'].values

models = {
    'GJR-GARCH(1,1)': gjr_forecasts.values,
    'HAR': har_base_fcast.values,
    'HAR + H_rs_ewma': har_hrs_fcast.values,
    'HAR + H_vario_ewma': har_hvario_fcast.values,
    'HAR + H_rs + H_vario': har_both_fcast.values,
    'HAR + H_rs_raw': har_hraw_fcast.values,
}

results = {}
for name, fcast in models.items():
    ql, n_valid = qlike(actual_oos, fcast)
    ms, _ = mse(actual_oos, fcast)
    results[name] = {'qlike': ql, 'mse': ms, 'n_valid': n_valid}
    print(f"  {name:25s}  QLIKE={ql:.6f}  MSE={ms:.2e}  N={n_valid}")

# DM tests: HAR augmented vs HAR base
print("\nDiebold-Mariano Tests (vs HAR baseline):")
print("  (negative DM = augmented model better)")

har_base_losses = actual_oos / har_base_fcast.values - np.log(actual_oos / har_base_fcast.values) - 1

dm_results = {}
for name, fcast in models.items():
    if name == 'HAR':
        continue
    aug_losses = actual_oos / fcast - np.log(actual_oos / fcast) - 1

    # Filter valid
    valid = ~(np.isnan(har_base_losses) | np.isnan(aug_losses))
    if valid.sum() < 50:
        continue

    dm_stat, p_val = dm_test(har_base_losses[valid], aug_losses[valid], h=1)
    dm_results[name] = {'dm_stat': dm_stat, 'p_value': p_val}
    sig = "***" if p_val < 0.01 else ("**" if p_val < 0.05 else ("*" if p_val < 0.10 else ""))
    print(f"  {name:25s}  DM={dm_stat:+.4f}  p={p_val:.4f} {sig}")

# MZ regression: actual = a + b * forecast
print("\nMincer-Zarnowitz Regression (actual = a + b*forecast):")
for name, fcast in models.items():
    valid = ~(np.isnan(actual_oos) | np.isnan(fcast))
    if valid.sum() < 50:
        continue
    a = actual_oos[valid]
    f = fcast[valid]
    slope, intercept, r_value, p_value, std_err = stats.linregress(f, a)
    print(f"  {name:25s}  a={intercept:.6f}  b={slope:.4f}  R2={r_value**2:.4f}")

# ============================================================
# 7. IN-SAMPLE COEFFICIENT ANALYSIS
# ============================================================
print("\n" + "=" * 60)
print("In-Sample HAR+H Coefficient Analysis")
print("=" * 60)

is_data = spy[is_mask].dropna(subset=har_features_h_rs + ['r_squared'])
X = is_data[har_features_h_rs].values
y = is_data['r_squared'].values
X_c = np.column_stack([np.ones(len(X)), X])

beta, residuals, rank, sv = np.linalg.lstsq(X_c, y, rcond=None)
y_hat = X_c @ beta
resid = y - y_hat
n_obs = len(y)
k = len(beta)
sigma2 = np.sum(resid ** 2) / (n_obs - k)
cov_beta = sigma2 * np.linalg.inv(X_c.T @ X_c)
se_beta = np.sqrt(np.diag(cov_beta))
t_stats = beta / se_beta

feature_names = ['const', 'r2_lag1', 'r2_lag5', 'r2_lag22', 'H_rs_ewma_lag1']
print(f"\nHAR + H_rs_ewma (IS, n={n_obs}):")
print(f"{'Feature':20s} {'Coef':>12s} {'SE':>12s} {'t-stat':>10s}")
for fn, b, se, t in zip(feature_names, beta, se_beta, t_stats):
    sig = "***" if abs(t) > 3.0 else ("**" if abs(t) > 2.0 else ("*" if abs(t) > 1.65 else ""))
    print(f"  {fn:18s} {b:12.6f} {se:12.6f} {t:10.4f} {sig}")

r2_is = 1 - np.sum(resid ** 2) / np.sum((y - np.mean(y)) ** 2)
print(f"  R2 = {r2_is:.6f}")

# Also test variogram H
is_data2 = spy[is_mask].dropna(subset=har_features_h_vario + ['r_squared'])
X2 = is_data2[har_features_h_vario].values
y2 = is_data2['r_squared'].values
X2_c = np.column_stack([np.ones(len(X2)), X2])

beta2, _, _, _ = np.linalg.lstsq(X2_c, y2, rcond=None)
y_hat2 = X2_c @ beta2
resid2 = y2 - y_hat2
sigma2_2 = np.sum(resid2 ** 2) / (len(y2) - len(beta2))
cov_beta2 = sigma2_2 * np.linalg.inv(X2_c.T @ X2_c)
se_beta2 = np.sqrt(np.diag(cov_beta2))
t_stats2 = beta2 / se_beta2

feature_names2 = ['const', 'r2_lag1', 'r2_lag5', 'r2_lag22', 'H_vario_ewma_lag1']
print(f"\nHAR + H_vario_ewma (IS, n={len(y2)}):")
print(f"{'Feature':20s} {'Coef':>12s} {'SE':>12s} {'t-stat':>10s}")
for fn, b, se, t in zip(feature_names2, beta2, se_beta2, t_stats2):
    sig = "***" if abs(t) > 3.0 else ("**" if abs(t) > 2.0 else ("*" if abs(t) > 1.65 else ""))
    print(f"  {fn:18s} {b:12.6f} {se:12.6f} {t:10.4f} {sig}")

# ============================================================
# 8. PLOTS
# ============================================================
print("\nGenerating plots...")

# Plot 1: H time series
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

ax = axes[0]
ax.plot(spy.index.to_numpy(), spy['H_rs_ewma'].to_numpy(), color='steelblue', alpha=0.8, linewidth=0.8, label='H (R/S, EWMA)')
ax.axhline(0.5, color='red', linestyle='--', alpha=0.5, label='H=0.5 (random walk)')
ax.set_ylabel('Hurst Exponent')
ax.set_title('K973: Time-Varying Hurst Exponent (R/S method)')
ax.legend(loc='upper right')
ax.grid(True, alpha=0.3)

ax = axes[1]
valid_vario = spy['H_vario_ewma'].dropna()
ax.plot(valid_vario.index.to_numpy(), valid_vario.to_numpy(), color='darkorange', alpha=0.8, linewidth=0.8, label='H (Variogram, EWMA)')
ax.axhline(0.5, color='red', linestyle='--', alpha=0.5, label='H=0.5')
ax.set_ylabel('Hurst Exponent')
ax.set_title('Time-Varying Hurst Exponent (Variogram method)')
ax.legend(loc='upper right')
ax.grid(True, alpha=0.3)

ax = axes[2]
ax.plot(spy.index.to_numpy(), (spy['rv_22'] * 100).to_numpy(), color='gray', alpha=0.6, linewidth=0.8, label='Annualized Vol (%)')
ax.set_ylabel('Volatility (%)')
ax.set_title('22-day Realized Volatility')
ax.legend(loc='upper right')
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k973_hurst_timeseries.png'), dpi=150, bbox_inches='tight')
plt.close()

# Plot 2: Forecast comparison (cumulative QLIKE)
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

# Cumulative QLIKE
ax = axes[0]
for name, fcast in models.items():
    valid = ~(np.isnan(actual_oos) | np.isnan(fcast) | (fcast <= 0) | (actual_oos <= 0))
    losses = np.where(valid, actual_oos / fcast - np.log(actual_oos / fcast) - 1, np.nan)
    cum_loss = pd.Series(losses, index=oos_idx).expanding().mean()
    ax.plot(oos_idx.to_numpy(), cum_loss.to_numpy(), label=name, linewidth=1.0, alpha=0.8)

ax.set_ylabel('Cumulative Mean QLIKE')
ax.set_title('K973: OOS Cumulative QLIKE (lower = better)')
ax.legend(loc='upper right', fontsize=8)
ax.grid(True, alpha=0.3)

# H distribution by regime
ax = axes[1]
regime_data = {}
for regime in ['Low (<10%)', 'Normal (10-15%)', 'High (15-25%)', 'Crisis (>25%)']:
    mask = spy['vol_regime'] == regime
    vals = spy.loc[mask, 'H_rs_ewma'].dropna().values
    if len(vals) > 0:
        regime_data[regime] = vals

bp = ax.boxplot(regime_data.values(), labels=regime_data.keys(), patch_artist=True)
colors = ['#2ecc71', '#3498db', '#e67e22', '#e74c3c']
for patch, color in zip(bp['boxes'], colors):
    patch.set_facecolor(color)
    patch.set_alpha(0.6)
ax.axhline(0.5, color='red', linestyle='--', alpha=0.5, label='H=0.5')
ax.set_ylabel('Hurst Exponent (R/S EWMA)')
ax.set_title('Hurst Exponent by Volatility Regime')
ax.legend()
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k973_forecast_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()

print("Plots saved.")

# ============================================================
# 9. SAVE RESULTS
# ============================================================
print("\nSaving results...")

# Prepare serializable results
results_json = {
    'experiment_id': 'K973',
    'title': 'Time-Varying Hurst Exponent for Volatility Forecasting',
    'data_source': 'yfinance (SPY)',
    'data_period': f"{spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}",
    'total_observations': int(len(spy)),
    'is_period': f"start to {is_end}",
    'oos_period': f"{oos_start} to end",
    'n_is': int(n_is),
    'n_oos': int(n_oos),
    'seed': 42,
    'hurst_descriptive': {},
    'hurst_by_regime': {},
    'oos_qlike': {},
    'oos_mse': {},
    'dm_tests_vs_har': {},
    'is_coefficients': {},
    'conclusion': '',
    'references': [
        'Gatheral, Jaisson, Rosenbaum (2018) "Volatility is Rough", Quantitative Finance',
        'Corsi (2009) "A Simple Approximate Long-Memory Model of Realized Volatility", JFE',
        'Patton (2011) "Volatility Forecast Comparison Using Imperfect Proxies", JoE',
        'arXiv:2509.05820 (2025) Time-Varying Hurst EWMA',
        'Harvey, Liu, Zhu (2016) ...and the cross-section of expected returns, RFS'
    ]
}

# Hurst descriptive stats
for col in ['H_rs', 'H_vario', 'H_rs_ewma', 'H_vario_ewma']:
    valid = spy[col].dropna()
    results_json['hurst_descriptive'][col] = {
        'n': int(len(valid)),
        'mean': round(float(valid.mean()), 4),
        'std': round(float(valid.std()), 4),
        'min': round(float(valid.min()), 4),
        'max': round(float(valid.max()), 4),
        'median': round(float(valid.median()), 4),
        'below_05_pct': round(float((valid < 0.5).mean() * 100), 1)
    }

# H by regime
for regime in ['Low (<10%)', 'Normal (10-15%)', 'High (15-25%)', 'Crisis (>25%)']:
    mask = spy['vol_regime'] == regime
    vals = spy.loc[mask, 'H_rs_ewma'].dropna()
    if len(vals) > 0:
        results_json['hurst_by_regime'][regime] = {
            'n': int(len(vals)),
            'mean': round(float(vals.mean()), 4),
            'std': round(float(vals.std()), 4)
        }

# OOS results
for name in models:
    results_json['oos_qlike'][name] = round(float(results[name]['qlike']), 6)
    results_json['oos_mse'][name] = float(results[name]['mse'])
    results_json['oos_qlike'][name + '_n'] = int(results[name]['n_valid'])

for name, dm in dm_results.items():
    results_json['dm_tests_vs_har'][name] = {
        'dm_stat': round(float(dm['dm_stat']), 4) if not np.isnan(dm['dm_stat']) else None,
        'p_value': round(float(dm['p_value']), 4) if not np.isnan(dm['p_value']) else None,
    }

# IS coefficients
results_json['is_coefficients']['HAR_H_rs_ewma'] = {
    'features': feature_names,
    'coefs': [round(float(b), 6) for b in beta],
    'se': [round(float(s), 6) for s in se_beta],
    't_stats': [round(float(t), 4) for t in t_stats],
    'R2': round(float(r2_is), 6),
    'n': int(n_obs)
}

# Determine conclusion
best_model = min(results, key=lambda k: results[k]['qlike'])
h_improves = any(
    results[m]['qlike'] < results['HAR']['qlike']
    for m in ['HAR + H_rs_ewma', 'HAR + H_vario_ewma', 'HAR + H_rs + H_vario']
)

h_rs_mean = spy['H_rs_ewma'].dropna().mean()
h_vario_mean = spy['H_vario_ewma'].dropna().mean()

conclusion_parts = []
conclusion_parts.append(f"Mean H (R/S EWMA) = {h_rs_mean:.3f}, H (Variogram EWMA) = {h_vario_mean:.3f}.")

if h_rs_mean < 0.5:
    conclusion_parts.append(f"H < 0.5 confirms rough volatility characteristics in SPY daily returns.")
else:
    conclusion_parts.append(f"H >= 0.5, rough vol characteristics not clearly evident at daily frequency.")

if h_improves:
    best_h_model = min(
        ['HAR + H_rs_ewma', 'HAR + H_vario_ewma', 'HAR + H_rs + H_vario'],
        key=lambda k: results[k]['qlike']
    )
    qlike_improvement = (results['HAR']['qlike'] - results[best_h_model]['qlike']) / results['HAR']['qlike'] * 100
    conclusion_parts.append(
        f"Adding H to HAR improves QLIKE by {qlike_improvement:.2f}% "
        f"(best: {best_h_model}, QLIKE={results[best_h_model]['qlike']:.6f} vs HAR {results['HAR']['qlike']:.6f})."
    )
    # Check DM significance
    if best_h_model in dm_results and dm_results[best_h_model]['p_value'] is not None:
        if dm_results[best_h_model]['p_value'] < 0.05:
            conclusion_parts.append(f"DM test significant at 5% (p={dm_results[best_h_model]['p_value']:.4f}).")
        else:
            conclusion_parts.append(f"But DM test not significant (p={dm_results[best_h_model]['p_value']:.4f}). Improvement may be noise.")
else:
    conclusion_parts.append("Adding H to HAR does NOT improve QLIKE. Hurst exponent has no incremental predictive value for daily vol.")

conclusion_parts.append(f"Best overall model: {best_model} (QLIKE={results[best_model]['qlike']:.6f}).")
conclusion_parts.append("Comparison with K34: confirms that daily-frequency Hurst is challenging for vol prediction.")

results_json['conclusion'] = ' '.join(conclusion_parts)

with open(os.path.join(SCRIPT_DIR, 'k973_hurst_vol_results.json'), 'w') as f:
    json.dump(results_json, f, indent=2, default=str)

print("\n" + "=" * 60)
print("CONCLUSION")
print("=" * 60)
print(results_json['conclusion'])
print("\nDone.")
