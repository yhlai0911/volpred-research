#!/usr/bin/env python3
"""
K976: MF2-GARCH + VIX Slope Integration
========================================
Tests whether adding VIX term structure slope (VIX/VIX3M) to the MF2-GARCH
long-run component improves volatility forecasting beyond VIX alone.

Background:
- K970: MF2-VIX improved GJR QLIKE by 9.55% (DM t=2.94)
- K975: VIX Slope added +2.2% incremental R² for 5d RV (DM p=0.0002)

Models tested:
1. GJR-GARCH (baseline)
2. MF2-VIX: tau = (VIX/sqrt(252))²
3. MF2-VIX-Slope: tau = (VIX/sqrt(252))² × slope_adj
4. MF2-VIX+Slope (2-factor): tau = α×VIX² + β×VIX²×slope + γ
5. MF2-VIX+EMA: tau = w1×VIX² + w2×EMA²

Data: SPY, VIX, VIX3M from yfinance (2010-2026)
IS: 2010-2018, OOS: 2019-2026

References:
- Engle & Rangel (2008) Spline-GARCH
- Patton (2011) QLIKE loss function
- K970/K975 prior experiments
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import os
from datetime import datetime
from arch import arch_model
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data Download & Preparation
# ============================================================
print("=" * 60)
print("K976: MF2-GARCH + VIX Slope Integration")
print("=" * 60)

print("\n[1/7] Downloading data...")
spy = yf.download('SPY', start='2010-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2010-01-01', end='2026-04-07', progress=False)
vix3m = yf.download('^VIX3M', start='2010-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns from yfinance
for df_name, df in [('spy', spy), ('vix', vix), ('vix3m', vix3m)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Flatten index
spy.index = spy.index.tz_localize(None) if spy.index.tz else spy.index
vix.index = vix.index.tz_localize(None) if vix.index.tz else vix.index
vix3m.index = vix3m.index.tz_localize(None) if vix3m.index.tz else vix3m.index

# Compute returns
spy['Return'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy = spy.dropna(subset=['Return'])

# Align all data
common_idx = spy.index.intersection(vix.index).intersection(vix3m.index)
spy = spy.loc[common_idx]
vix_close = vix.loc[common_idx, 'Close'].copy()
vix3m_close = vix3m.loc[common_idx, 'Close'].copy()

# Ensure Series are clean
vix_close = vix_close.squeeze() if hasattr(vix_close, 'squeeze') else vix_close
vix3m_close = vix3m_close.squeeze() if hasattr(vix3m_close, 'squeeze') else vix3m_close
returns = spy['Return'].squeeze() if hasattr(spy['Return'], 'squeeze') else spy['Return']

print(f"  SPY: {len(spy)} observations ({spy.index[0].date()} to {spy.index[-1].date()})")
print(f"  VIX: {len(vix_close)} observations")
print(f"  VIX3M: {len(vix3m_close)} observations")
print(f"  Common: {len(common_idx)} observations")

# ============================================================
# 2. Construct Long-Run Components (tau)
# ============================================================
print("\n[2/7] Constructing long-run components...")

# All tau values use shift(1) to avoid lookahead
# tau = daily variance scale from VIX

# 2a. MF2-VIX: tau = (VIX / sqrt(252))²
tau_vix = ((vix_close / np.sqrt(252)) ** 2).shift(1)

# 2b. VIX Slope = VIX / VIX3M
slope_ratio = (vix_close / vix3m_close).shift(1)

# 2c. MF2-VIX-Slope: tau = (VIX/sqrt(252))² × slope_adj
# Calibrate k on IS period
IS_END = '2018-12-31'
OOS_START = '2019-01-02'

is_mask = returns.index <= IS_END
oos_mask = returns.index >= OOS_START

# Target: r² (squared return)
r_sq = returns ** 2

# Calibrate slope adjustment on IS
# slope_adj = 1 + max(0, ratio - 1) * k  (amplify in backwardation)
# Try k values and pick best QLIKE on IS
best_k = 0
best_qlike_k = np.inf

for k_try in np.arange(0.0, 5.1, 0.25):
    slope_adj_try = 1.0 + np.maximum(0, slope_ratio - 1.0) * k_try
    tau_try = tau_vix * slope_adj_try
    tau_try = tau_try.dropna()

    # QLIKE on IS
    common = r_sq.index.intersection(tau_try.index)
    common_is = [d for d in common if d <= pd.Timestamp(IS_END)]

    if len(common_is) < 100:
        continue

    r2_is = r_sq.loc[common_is].values
    tau_is = tau_try.loc[common_is].values

    # QLIKE = mean(r²/σ² + ln(σ²))
    valid = tau_is > 0
    if valid.sum() < 100:
        continue

    qlike = np.mean(r2_is[valid] / tau_is[valid] + np.log(tau_is[valid]))

    if qlike < best_qlike_k:
        best_qlike_k = qlike
        best_k = k_try

print(f"  Calibrated slope adjustment k = {best_k:.2f}")

slope_adj = 1.0 + np.maximum(0, slope_ratio - 1.0) * best_k
tau_vix_slope = tau_vix * slope_adj

# 2d. MF2-VIX+Slope (2-factor): OLS on IS
# tau = α × VIX² + β × VIX² × slope + γ
# where slope = VIX/VIX3M - 1 (centered at 0)
slope_centered = (slope_ratio - 1.0)
vix_sq = ((vix_close / np.sqrt(252)) ** 2).shift(1)

# Build IS data for OLS
is_dates = [d for d in r_sq.index if d <= pd.Timestamp(IS_END) and d in vix_sq.index and d in slope_centered.index]
is_dates = [d for d in is_dates if not np.isnan(vix_sq.loc[d]) and not np.isnan(slope_centered.loc[d])]

X_ols = np.column_stack([
    vix_sq.loc[is_dates].values,
    vix_sq.loc[is_dates].values * slope_centered.loc[is_dates].values,
    np.ones(len(is_dates))
])
y_ols = r_sq.loc[is_dates].values

# OLS with constraints: tau must be positive
from numpy.linalg import lstsq
coeffs, _, _, _ = lstsq(X_ols, y_ols, rcond=None)
alpha_ols, beta_ols, gamma_ols = coeffs
print(f"  2-factor OLS: α={alpha_ols:.6f}, β={beta_ols:.6f}, γ={gamma_ols:.8f}")

# Construct tau for full sample
tau_2factor = alpha_ols * vix_sq + beta_ols * vix_sq * slope_centered + gamma_ols
# Ensure positivity
tau_2factor = tau_2factor.clip(lower=1e-10)

# 2e. MF2-VIX+EMA: tau = w1×VIX² + w2×EMA²
# EMA of squared returns with span=60
ema_sq = r_sq.ewm(span=60).mean().shift(1)

# Calibrate weights on IS
best_w1 = 1.0
best_qlike_ema = np.inf

for w1_try in np.arange(0.0, 1.05, 0.05):
    w2_try = 1.0 - w1_try
    tau_try = w1_try * vix_sq + w2_try * ema_sq
    tau_try = tau_try.dropna()

    common_is = [d for d in tau_try.index if d <= pd.Timestamp(IS_END) and d in r_sq.index]
    if len(common_is) < 100:
        continue

    r2_is = r_sq.loc[common_is].values
    tau_is = tau_try.loc[common_is].values

    valid = tau_is > 0
    if valid.sum() < 100:
        continue

    qlike = np.mean(r2_is[valid] / tau_is[valid] + np.log(tau_is[valid]))

    if qlike < best_qlike_ema:
        best_qlike_ema = qlike
        best_w1 = w1_try

w2_best = 1.0 - best_w1
print(f"  VIX+EMA weights: w1(VIX)={best_w1:.2f}, w2(EMA)={w2_best:.2f}")

tau_vix_ema = best_w1 * vix_sq + w2_best * ema_sq

# ============================================================
# 3. GJR-GARCH Estimation (Baseline)
# ============================================================
print("\n[3/7] Estimating GJR-GARCH baseline...")

# Scale returns for arch package (percentage returns)
ret_pct = returns * 100

# IS estimation
ret_is = ret_pct[is_mask]
gjr_model = arch_model(ret_is, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
gjr_res = gjr_model.fit(disp='off')

omega = gjr_res.params['omega']
alpha1 = gjr_res.params['alpha[1]']
gamma1 = gjr_res.params['gamma[1]']
beta1 = gjr_res.params['beta[1]']

print(f"  GJR params: ω={omega:.6f}, α={alpha1:.4f}, γ={gamma1:.4f}, β={beta1:.4f}")
print(f"  Persistence: {alpha1 + gamma1/2 + beta1:.4f}")

# ============================================================
# 4. OOS Recursive Forecasting
# ============================================================
print("\n[4/7] OOS recursive forecasting...")

oos_dates = [d for d in returns.index if d >= pd.Timestamp(OOS_START)]
print(f"  OOS period: {oos_dates[0].date()} to {oos_dates[-1].date()} ({len(oos_dates)} days)")

# Pre-compute all tau series for OOS
tau_dict = {
    'GJR': None,  # will be computed recursively
    'MF2-VIX': tau_vix,
    'MF2-VIX-Slope': tau_vix_slope,
    'MF2-2Factor': tau_2factor,
    'MF2-VIX+EMA': tau_vix_ema
}

# GJR recursive OOS forecasting
# h_t = omega + alpha * r²_{t-1} + gamma * r²_{t-1} * I(r<0) + beta * h_{t-1}
# In percentage return space

# Initialize with IS conditional variance
gjr_oos_var = np.zeros(len(oos_dates))
h_prev = gjr_res.conditional_volatility.iloc[-1] ** 2  # last IS variance

all_ret_pct = ret_pct.reindex(returns.index)

for i, d in enumerate(oos_dates):
    # Forecast for today using yesterday's info
    idx_pos = returns.index.get_loc(d)
    r_prev = all_ret_pct.iloc[idx_pos - 1]
    indicator = 1.0 if r_prev < 0 else 0.0

    h_t = omega + alpha1 * r_prev**2 + gamma1 * r_prev**2 * indicator + beta1 * h_prev
    gjr_oos_var[i] = h_t
    h_prev = h_t

# Convert GJR variance from pct² to decimal²
gjr_oos_var_decimal = gjr_oos_var / 10000.0

# MF2 models: GJR on standardized returns (r/sqrt(tau)), then multiply back
# For MF2, we re-estimate GJR on r_t / sqrt(tau_t) in IS, then forecast

mf2_oos_results = {}

for model_name, tau_series in tau_dict.items():
    if model_name == 'GJR':
        continue

    # Get tau for IS period
    tau_is_vals = tau_series.reindex(returns.index[is_mask]).dropna()

    if len(tau_is_vals) < 500:
        print(f"  Skipping {model_name}: insufficient IS data ({len(tau_is_vals)})")
        continue

    # Standardized returns in IS: r_t / sqrt(tau_t)
    common_is_dates = tau_is_vals.index.intersection(returns.index[is_mask])
    r_std_is = returns.loc[common_is_dates] / np.sqrt(tau_is_vals.loc[common_is_dates])
    r_std_is_pct = r_std_is * 100

    # Fit GJR on standardized returns
    try:
        gjr_mf2 = arch_model(r_std_is_pct, vol='GARCH', p=1, o=1, q=1, mean='Zero', dist='normal')
        gjr_mf2_res = gjr_mf2.fit(disp='off')

        om = gjr_mf2_res.params['omega']
        a1 = gjr_mf2_res.params['alpha[1]']
        g1 = gjr_mf2_res.params['gamma[1]']
        b1 = gjr_mf2_res.params['beta[1]']

        persistence = a1 + g1/2 + b1
        print(f"  {model_name} GJR: ω={om:.6f}, α={a1:.4f}, γ={g1:.4f}, β={b1:.4f}, persist={persistence:.4f}")

    except Exception as e:
        print(f"  {model_name} estimation failed: {e}")
        continue

    # OOS recursive: h_t on standardized returns, then σ² = tau_t × g_t
    oos_var = np.zeros(len(oos_dates))
    h_prev_mf2 = gjr_mf2_res.conditional_volatility.iloc[-1] ** 2

    for i, d in enumerate(oos_dates):
        idx_pos = returns.index.get_loc(d)
        d_prev = returns.index[idx_pos - 1]

        # Get tau for previous day (already shifted in construction)
        tau_d = tau_series.get(d, np.nan)
        tau_d_prev = tau_series.get(d_prev, np.nan)

        if np.isnan(tau_d) or np.isnan(tau_d_prev) or tau_d_prev <= 0:
            # Fallback to GJR
            oos_var[i] = gjr_oos_var_decimal[i]
            continue

        # Standardized previous return
        r_prev_raw = returns.iloc[idx_pos - 1]
        r_std_prev = (r_prev_raw / np.sqrt(tau_d_prev)) * 100  # pct

        indicator = 1.0 if r_std_prev < 0 else 0.0
        g_t = om + a1 * r_std_prev**2 + g1 * r_std_prev**2 * indicator + b1 * h_prev_mf2

        # Total variance = tau_t × g_t (in pct²), convert to decimal²
        oos_var[i] = tau_d * (g_t / 10000.0) + tau_d  # tau is already variance scale
        # Actually: sigma² = tau × g (where g is the short-run in decimal² terms)
        # More precisely: sigma² = tau × (g/10000) since g is in pct²
        oos_var[i] = tau_d * g_t / 10000.0

        h_prev_mf2 = g_t

    mf2_oos_results[model_name] = oos_var

# ============================================================
# 5. Evaluation
# ============================================================
print("\n[5/7] Evaluating models...")

# Target: r²
target = r_sq.reindex(pd.DatetimeIndex(oos_dates)).values

# Collect all forecasts
forecasts = {'GJR': gjr_oos_var_decimal}
forecasts.update(mf2_oos_results)

results = {}

for model_name, fc in forecasts.items():
    # Filter valid entries
    valid = ~np.isnan(fc) & (fc > 0) & ~np.isnan(target)
    t = target[valid]
    f = fc[valid]

    n = len(t)

    # QLIKE = mean(r²/σ² + ln(σ²))
    qlike = np.mean(t / f + np.log(f))

    # MSE
    mse = np.mean((t - f) ** 2)

    # MZ regression: r² = a + b × σ²
    slope_mz, intercept_mz, r_value, p_value, _ = stats.linregress(f, t)

    results[model_name] = {
        'n_obs': int(n),
        'QLIKE': float(qlike),
        'MSE': float(mse),
        'MZ_intercept': float(intercept_mz),
        'MZ_slope': float(slope_mz),
        'MZ_R2': float(r_value ** 2),
        'MZ_p_slope': float(p_value)
    }

    print(f"\n  {model_name}:")
    print(f"    QLIKE = {qlike:.6f}")
    print(f"    MSE = {mse:.12f}")
    print(f"    MZ: a={intercept_mz:.6f}, b={slope_mz:.4f}, R²={r_value**2:.4f}")

# DM tests
print("\n  Diebold-Mariano Tests:")
dm_results = {}

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive ability."""
    d = e1 - e2
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    n = len(d)
    var_d = np.var(d, ddof=1)

    # Add autocovariance terms for h>1
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        var_d += 2 * gamma_k / n

    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0

    t_stat = d_mean / se
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)

# QLIKE loss differences
for model_name in forecasts:
    if model_name == 'GJR':
        continue

    fc_model = forecasts[model_name]
    fc_gjr = forecasts['GJR']

    valid = ~np.isnan(fc_model) & (fc_model > 0) & ~np.isnan(fc_gjr) & (fc_gjr > 0) & ~np.isnan(target)

    t_v = target[valid]
    f_m = fc_model[valid]
    f_g = fc_gjr[valid]

    # QLIKE losses
    loss_model = t_v / f_m + np.log(f_m)
    loss_gjr = t_v / f_g + np.log(f_g)

    t_stat, p_val = dm_test(loss_gjr, loss_model)

    dm_results[f'{model_name} vs GJR'] = {
        't_stat': t_stat,
        'p_value': p_val,
        'model_better': t_stat > 0
    }

    print(f"    {model_name} vs GJR: t={t_stat:.3f}, p={p_val:.4f} {'***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.1 else ''}")

# Also compare MF2 variants vs MF2-VIX
if 'MF2-VIX' in forecasts:
    for model_name in ['MF2-VIX-Slope', 'MF2-2Factor', 'MF2-VIX+EMA']:
        if model_name not in forecasts:
            continue

        fc_model = forecasts[model_name]
        fc_base = forecasts['MF2-VIX']

        valid = ~np.isnan(fc_model) & (fc_model > 0) & ~np.isnan(fc_base) & (fc_base > 0) & ~np.isnan(target)

        t_v = target[valid]
        f_m = fc_model[valid]
        f_b = fc_base[valid]

        loss_model = t_v / f_m + np.log(f_m)
        loss_base = t_v / f_b + np.log(f_b)

        t_stat, p_val = dm_test(loss_base, loss_model)

        dm_results[f'{model_name} vs MF2-VIX'] = {
            't_stat': t_stat,
            'p_value': p_val,
            'model_better': t_stat > 0
        }

        print(f"    {model_name} vs MF2-VIX: t={t_stat:.3f}, p={p_val:.4f} {'***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.1 else ''}")

# ============================================================
# 6. VaR Backtesting
# ============================================================
print("\n[6/7] VaR backtesting...")

var_results = {}
oos_returns = returns.reindex(pd.DatetimeIndex(oos_dates)).values

for model_name, fc in forecasts.items():
    valid = ~np.isnan(fc) & (fc > 0) & ~np.isnan(oos_returns)
    r_v = oos_returns[valid]
    f_v = fc[valid]

    sigma = np.sqrt(f_v)

    model_var = {}
    for alpha_var in [0.01, 0.05]:
        z = stats.norm.ppf(alpha_var)
        var_threshold = z * sigma  # negative value

        violations = r_v < var_threshold
        viol_rate = np.mean(violations)
        n_viol = np.sum(violations)
        n_total = len(r_v)

        # Kupiec LR test
        if n_viol == 0 or n_viol == n_total:
            lr_stat = 0
            lr_pval = 1.0
        else:
            lr_stat = -2 * (n_total * np.log(1 - alpha_var) + 0 -
                           (n_viol * np.log(n_viol / n_total) + (n_total - n_viol) * np.log(1 - n_viol / n_total)))
            # Correct Kupiec
            p_hat = n_viol / n_total
            if p_hat > 0 and p_hat < 1:
                lr_stat = 2 * (n_viol * np.log(p_hat / alpha_var) +
                              (n_total - n_viol) * np.log((1 - p_hat) / (1 - alpha_var)))
            else:
                lr_stat = 0
            lr_pval = 1 - stats.chi2.cdf(abs(lr_stat), 1)

        model_var[f'VaR_{int(alpha_var*100)}pct'] = {
            'expected_rate': float(alpha_var),
            'actual_rate': float(viol_rate),
            'n_violations': int(n_viol),
            'n_total': int(n_total),
            'kupiec_stat': float(lr_stat),
            'kupiec_pval': float(lr_pval)
        }

    var_results[model_name] = model_var
    print(f"  {model_name}: VaR1%={model_var['VaR_1pct']['actual_rate']:.4f} "
          f"(exp=0.01), VaR5%={model_var['VaR_5pct']['actual_rate']:.4f} (exp=0.05)")

# ============================================================
# 7. Plots & Output
# ============================================================
print("\n[7/7] Generating plots and saving results...")

# Plot 1: Tau comparison
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)

plot_start = pd.Timestamp('2019-01-01')
plot_idx = [d for d in oos_dates if d >= plot_start]

for ax, (name, tau_s) in zip(axes, [
    ('MF2-VIX', tau_vix),
    ('MF2-VIX-Slope', tau_vix_slope),
    ('MF2-2Factor', tau_2factor)
]):
    tau_plot = tau_s.reindex(plot_idx).dropna()
    ax.plot(tau_plot.index.to_numpy(), tau_plot.values * 10000, linewidth=0.7, label=name)
    ax.set_ylabel('τ (×10⁴)')
    ax.set_title(name)
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.3)

axes[-1].set_xlabel('Date')
fig.suptitle('K976: Long-Run Component (τ) Comparison — OOS Period', fontsize=14)
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k976_tau_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()

# Plot 2: OOS forecast comparison
fig, axes = plt.subplots(2, 1, figsize=(14, 8))

# Top: forecasts vs realized
oos_dt = np.array(oos_dates)
ax = axes[0]
ax.plot(oos_dt, target * 10000, color='gray', alpha=0.3, linewidth=0.5, label='Realized r²')
for model_name, fc in forecasts.items():
    ax.plot(oos_dt, fc * 10000, linewidth=0.8, alpha=0.8, label=model_name)
ax.set_ylabel('Variance (×10⁴)')
ax.set_title('OOS Variance Forecasts vs Realized')
ax.legend(loc='upper right', fontsize=8)
ax.set_ylim(0, np.percentile(target * 10000, 99) * 2)
ax.grid(True, alpha=0.3)

# Bottom: cumulative QLIKE difference (model - GJR)
ax = axes[1]
gjr_loss = target / forecasts['GJR'] + np.log(forecasts['GJR'])

for model_name in ['MF2-VIX', 'MF2-VIX-Slope', 'MF2-2Factor', 'MF2-VIX+EMA']:
    if model_name not in forecasts:
        continue
    fc = forecasts[model_name]
    valid = ~np.isnan(fc) & (fc > 0) & ~np.isnan(gjr_loss)

    model_loss = np.full_like(target, np.nan)
    model_loss[valid] = target[valid] / fc[valid] + np.log(fc[valid])

    cum_diff = np.nancumsum(gjr_loss - model_loss)
    ax.plot(oos_dt, cum_diff, linewidth=1.0, label=f'{model_name} gain over GJR')

ax.axhline(y=0, color='black', linestyle='--', alpha=0.5)
ax.set_ylabel('Cumulative QLIKE Gain')
ax.set_xlabel('Date')
ax.set_title('Cumulative QLIKE Improvement over GJR')
ax.legend(loc='upper left', fontsize=8)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k976_oos_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()

# Plot 3: VIX Slope distribution and relationship
fig, axes = plt.subplots(1, 2, figsize=(12, 5))

slope_oos = slope_ratio.reindex(pd.DatetimeIndex(oos_dates)).dropna()
axes[0].hist(slope_oos.values, bins=50, edgecolor='black', alpha=0.7)
axes[0].axvline(x=1.0, color='red', linestyle='--', label='Contango/Backwardation boundary')
axes[0].set_xlabel('VIX / VIX3M')
axes[0].set_ylabel('Frequency')
axes[0].set_title('VIX Term Structure Slope Distribution (OOS)')
axes[0].legend()

# Slope vs next-day realized vol
slope_vals = slope_ratio.reindex(pd.DatetimeIndex(oos_dates)).values
axes[1].scatter(slope_vals, np.sqrt(target) * np.sqrt(252) * 100,
                alpha=0.1, s=5, color='steelblue')
axes[1].set_xlabel('VIX / VIX3M (lagged)')
axes[1].set_ylabel('Realized Vol (annualized %)')
axes[1].set_title('VIX Slope vs Realized Volatility')
axes[1].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k976_slope_analysis.png'), dpi=150, bbox_inches='tight')
plt.close()

# ============================================================
# Save Results JSON
# ============================================================
output = {
    'experiment_id': 'K976',
    'title': 'MF2-GARCH + VIX Slope Integration',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX, ^VIX3M)',
    'sample_period': f"{spy.index[0].date()} to {spy.index[-1].date()}",
    'n_observations': int(len(common_idx)),
    'is_period': f"start to {IS_END}",
    'oos_period': f"{OOS_START} to {spy.index[-1].date()}",
    'oos_n': len(oos_dates),
    'seed': 42,
    'calibrated_parameters': {
        'slope_adjustment_k': float(best_k),
        'ols_2factor': {
            'alpha': float(alpha_ols),
            'beta': float(beta_ols),
            'gamma': float(gamma_ols)
        },
        'vix_ema_weights': {
            'w1_vix': float(best_w1),
            'w2_ema': float(w2_best)
        }
    },
    'gjr_parameters': {
        'omega': float(omega),
        'alpha': float(alpha1),
        'gamma': float(gamma1),
        'beta': float(beta1),
        'persistence': float(alpha1 + gamma1/2 + beta1)
    },
    'evaluation': results,
    'dm_tests': dm_results,
    'var_backtesting': var_results,
    'conclusions': {},
    'references': [
        'Engle & Rangel (2008) Spline-GARCH',
        'Patton (2011) QLIKE loss function',
        'K970: MF2-VIX baseline',
        'K975: VIX Slope analysis'
    ]
}

# Determine best model
best_model = min(results, key=lambda x: results[x]['QLIKE'])
gjr_qlike = results['GJR']['QLIKE']
best_qlike = results[best_model]['QLIKE']
improvement = (gjr_qlike - best_qlike) / gjr_qlike * 100

# Check if slope adds value over VIX alone
if 'MF2-VIX' in results:
    vix_qlike = results['MF2-VIX']['QLIKE']
    slope_models = ['MF2-VIX-Slope', 'MF2-2Factor']
    slope_improvement = {}
    for sm in slope_models:
        if sm in results:
            slope_improvement[sm] = (vix_qlike - results[sm]['QLIKE']) / vix_qlike * 100

output['conclusions'] = {
    'best_model': best_model,
    'best_qlike': float(best_qlike),
    'improvement_over_gjr_pct': float(improvement),
    'slope_adds_value': any(
        dm_results.get(f'{m} vs MF2-VIX', {}).get('model_better', False) and
        dm_results.get(f'{m} vs MF2-VIX', {}).get('p_value', 1) < 0.1
        for m in ['MF2-VIX-Slope', 'MF2-2Factor']
    ),
    'vix_ema_diversification': 'MF2-VIX+EMA' in results and results.get('MF2-VIX+EMA', {}).get('QLIKE', np.inf) < results.get('MF2-VIX', {}).get('QLIKE', 0),
    'ranking': sorted(results.keys(), key=lambda x: results[x]['QLIKE'])
}

with open(os.path.join(OUT_DIR, 'k976_mf2_slope_results.json'), 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n{'='*60}")
print(f"RESULTS SUMMARY")
print(f"{'='*60}")
print(f"\nBest model: {best_model} (QLIKE={best_qlike:.6f})")
print(f"Improvement over GJR: {improvement:.2f}%")
print(f"Ranking: {output['conclusions']['ranking']}")
print(f"Slope adds value over VIX alone: {output['conclusions']['slope_adds_value']}")
print(f"VIX+EMA provides diversification: {output['conclusions']['vix_ema_diversification']}")
print(f"\nResults saved to {OUT_DIR}")
print("Done!")
