"""
K989: MF2-VIX + VIX² Convexity — Combining Two ★-Level Findings

Builds on:
  K970: MF2-VIX (sigma²=tau_VIX * g_GJR) improved GJR QLIKE by 9.55%, DM t=2.94
  K987: VIX² quadratic OOS R²=0.258 vs VIX linear 0.202, confirmed convexity
  K986: LASSO 100% selected VIX² as important factor

Hypothesis: Adding VIX² convexity to the MF2 tau may combine both advantages.

Models tested:
  1. GJR baseline (standard GJR-GARCH(1,1))
  2. MF2-VIX (K970 baseline): tau = (VIX_{t-1}/sqrt(252))²
  3. MF2-VIX² (quadratic): tau = alpha + beta1*VIX²_{t-1} + beta2*VIX⁴_{t-1}
  4. MF2-VIX-Poly: tau from polynomial regression r²=f(VIX, VIX²)
  5. MF2-VIX-Piecewise: tau = (VIX/sqrt(252))² * (1 + delta*max(VIX-20,0))
  6. GJR-X: GJR with exogenous VIX² in variance equation

Data: SPY 2006-2026, IS: 2006-2018, OOS: 2019-2026
Target: r² (close-to-close squared return)

References:
  - Conrad, C. & Engle, R. (2025). Two-component GARCH. J. Applied Econometrics.
  - Patton, A.J. (2011). Volatility forecast comparison. J. Econometrics, 160(1).
  - Harvey, C.R., Liu, Y., & Zhu, H. (2016). ...and cross-section. RFS.

Data source: yfinance (SPY, ^VIX), 2006-01-01 to 2026-04-07
"""

import numpy as np
import pandas as pd
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from scipy import stats as sp_stats
from numpy.linalg import lstsq

np.random.seed(42)
warnings.filterwarnings('ignore')

SCRIPT_DIR = 'experiments/k989'

# ============================================================
# 1. Data Download
# ============================================================
import yfinance as yf

print("Downloading SPY and VIX data...")
spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Log returns (%)
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1)) * 100
spy = spy.dropna(subset=['ret'])

# Align VIX with SPY dates
vix_close = vix['Close'].reindex(spy.index).ffill()

# Squared returns as proxy for realized variance
spy['r2'] = spy['ret'] ** 2

print(f"SPY: {len(spy)} obs, {spy.index[0].date()} to {spy.index[-1].date()}")
print(f"VIX aligned: {vix_close.notna().sum()} obs")

# ============================================================
# 2. Descriptive Statistics
# ============================================================
print("\n=== Descriptive Statistics ===")
print(f"  ret: mean={spy['ret'].mean():.4f}, std={spy['ret'].std():.4f}, "
      f"skew={spy['ret'].skew():.4f}, kurt={spy['ret'].kurtosis():.4f}")
print(f"  r2:  mean={spy['r2'].mean():.6f}, std={spy['r2'].std():.6f}")
print(f"  VIX: mean={vix_close.mean():.2f}, std={vix_close.std():.2f}")

# ============================================================
# 3. Long-run component construction (all shifted by 1)
# ============================================================

# --- 3a. MF2-VIX (K970 baseline) ---
spy['tau_vix'] = ((vix_close / np.sqrt(252)) ** 2).shift(1)

# --- 3b. MF2-VIX² (quadratic tau) ---
# tau = alpha + beta1 * VIX²_{t-1}/252 + beta2 * VIX⁴_{t-1}/252²
# Calibrate on IS data using OLS: r²_t ~ f(VIX²_{t-1}, VIX⁴_{t-1})
vix_shifted = vix_close.shift(1)  # Use t-1 VIX
spy['vix_lag'] = vix_shifted
spy['vix2_lag'] = vix_shifted ** 2
spy['vix4_lag'] = vix_shifted ** 4

# --- 3c. MF2-VIX-Poly (polynomial fit) ---
# tau from polynomial: r²_t = a + b1*VIX_{t-1} + b2*VIX²_{t-1}
# (calibrated below on IS)

# --- 3d. MF2-VIX-Piecewise ---
# tau = (VIX_{t-1}/sqrt(252))² * (1 + delta * max(VIX_{t-1} - 20, 0))
# delta calibrated on IS

# Floor and drop NaN
spy['tau_vix'] = spy['tau_vix'].clip(lower=1e-6)
spy = spy.dropna(subset=['tau_vix', 'vix_lag'])
print(f"\nAfter tau computation: {len(spy)} obs")

# ============================================================
# 4. IS/OOS Split (preliminary for calibration)
# ============================================================
IS_END = '2018-12-31'
OOS_START = '2019-01-02'

is_mask_pre = spy.index <= IS_END
y_is_cal = spy.loc[is_mask_pre, 'r2'].values

# ============================================================
# 5. Calibrate tau variants on IS, then compute for full sample
# ============================================================

# --- 5a. MF2-VIX² calibration ---
X_vix2_is = np.column_stack([
    np.ones(is_mask_pre.sum()),
    spy.loc[is_mask_pre, 'vix2_lag'].values / 252,
    spy.loc[is_mask_pre, 'vix4_lag'].values / (252**2)
])
coef_vix2, _, _, _ = lstsq(X_vix2_is, y_is_cal, rcond=None)
print(f"\nMF2-VIX² calibration: alpha={coef_vix2[0]:.8f}, beta1={coef_vix2[1]:.6f}, beta2={coef_vix2[2]:.10f}")

X_vix2_all = np.column_stack([
    np.ones(len(spy)),
    spy['vix2_lag'].values / 252,
    spy['vix4_lag'].values / (252**2)
])
spy['tau_vix2'] = np.maximum(X_vix2_all @ coef_vix2, 1e-6)

# --- 5b. MF2-VIX-Poly calibration ---
X_poly_is = np.column_stack([
    np.ones(is_mask_pre.sum()),
    spy.loc[is_mask_pre, 'vix_lag'].values / np.sqrt(252),
    spy.loc[is_mask_pre, 'vix2_lag'].values / 252
])
coef_poly, _, _, _ = lstsq(X_poly_is, y_is_cal, rcond=None)
print(f"MF2-VIX-Poly calibration: a={coef_poly[0]:.8f}, b1={coef_poly[1]:.6f}, b2={coef_poly[2]:.8f}")

X_poly_all = np.column_stack([
    np.ones(len(spy)),
    spy['vix_lag'].values / np.sqrt(252),
    spy['vix2_lag'].values / 252
])
spy['tau_poly'] = np.maximum(X_poly_all @ coef_poly, 1e-6)

# --- 5c. MF2-VIX-Piecewise calibration ---
tau_base_is = (spy.loc[is_mask_pre, 'vix_lag'].values / np.sqrt(252)) ** 2
kick_is = np.maximum(spy.loc[is_mask_pre, 'vix_lag'].values - 20, 0)

best_delta = 0.0
best_qlike = np.inf

for delta_cand in np.arange(0.001, 0.5, 0.001):
    tau_test = tau_base_is * (1.0 + delta_cand * kick_is)
    tau_test = np.maximum(tau_test, 1e-6)
    ql = np.mean(np.log(tau_test) + y_is_cal / tau_test)
    if ql < best_qlike:
        best_qlike = ql
        best_delta = delta_cand

print(f"MF2-VIX-Piecewise calibration: delta={best_delta:.4f}")

tau_base_all = (spy['vix_lag'].values / np.sqrt(252)) ** 2
kick_all = np.maximum(spy['vix_lag'].values - 20, 0)
spy['tau_piecewise'] = np.maximum(tau_base_all * (1.0 + best_delta * kick_all), 1e-6)

# ============================================================
# 5d. Final IS/OOS split (after all tau columns exist)
# ============================================================
is_mask = spy.index <= IS_END
oos_mask = spy.index >= OOS_START

spy_is = spy[is_mask].copy()
spy_oos = spy[oos_mask].copy()

print(f"\nIS: {len(spy_is)} obs ({spy_is.index[0].date()} to {spy_is.index[-1].date()})")
print(f"OOS: {len(spy_oos)} obs ({spy_oos.index[0].date()} to {spy_oos.index[-1].date()})")

# ============================================================
# 6. GJR-GARCH estimation helpers
# ============================================================
from arch import arch_model

def fit_gjr(returns, dist='t'):
    """Fit GJR-GARCH(1,1) with Student-t errors."""
    am = arch_model(returns, vol='GARCH', p=1, o=1, q=1, dist=dist, mean='Zero')
    res = am.fit(disp='off', show_warning=False)
    return res

def gjr_recursion(params, returns, initial_var):
    """Run GJR-GARCH(1,1) recursion with fixed parameters."""
    omega = params['omega']
    alpha = params['alpha[1]']
    gamma = params['gamma[1]']
    beta = params['beta[1]']

    n = len(returns)
    h = np.zeros(n)
    h[0] = initial_var

    r = returns.values if hasattr(returns, 'values') else returns

    for t in range(1, n):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        h[t] = omega + alpha * r[t-1]**2 + gamma * r[t-1]**2 * indicator + beta * h[t-1]
        h[t] = max(h[t], 1e-8)

    return h

# ============================================================
# 7. Model estimation and OOS forecasting
# ============================================================
results = {}

# --- 7a. Baseline GJR-GARCH ---
print("\n=== Model 1: Baseline GJR-GARCH ===")
res_gjr = fit_gjr(spy_is['ret'])
print(f"  Convergence: {res_gjr.convergence_flag == 0}")
params_gjr = res_gjr.params
persistence = params_gjr['alpha[1]'] + params_gjr['gamma[1]']/2 + params_gjr['beta[1]']
print(f"  omega={params_gjr['omega']:.6f}, alpha={params_gjr['alpha[1]']:.6f}, "
      f"gamma={params_gjr['gamma[1]']:.6f}, beta={params_gjr['beta[1]']:.6f}")
print(f"  Persistence: {persistence:.4f}")

# OOS recursion
last_is_h = res_gjr.conditional_volatility.iloc[-1] ** 2
last_is_r = spy_is['ret'].iloc[-1]
last_is_r2 = last_is_r ** 2
last_is_ind = 1.0 if last_is_r < 0 else 0.0
initial_var_gjr = (params_gjr['omega'] + params_gjr['alpha[1]'] * last_is_r2
                   + params_gjr['gamma[1]'] * last_is_r2 * last_is_ind
                   + params_gjr['beta[1]'] * last_is_h)

oos_h_gjr = gjr_recursion(params_gjr, spy_oos['ret'], initial_var_gjr)
results['GJR'] = {
    'forecast': oos_h_gjr,
    'params': {k: float(v) for k, v in params_gjr.items()},
    'persistence': float(persistence)
}

# --- 7b. MF2 variants ---
tau_variants = {
    'MF2-VIX': 'tau_vix',
    'MF2-VIX2': 'tau_vix2',
    'MF2-Poly': 'tau_poly',
    'MF2-Piecewise': 'tau_piecewise'
}

for name, tau_col in tau_variants.items():
    print(f"\n=== Model: {name} ===")

    # Standardize IS returns by long-run component
    tau_is = spy_is[tau_col].values
    r_tilde_is = spy_is['ret'].values / np.sqrt(tau_is)

    # Check for valid standardized returns
    valid = np.isfinite(r_tilde_is) & (np.abs(r_tilde_is) < 1000)
    if valid.sum() < len(r_tilde_is) * 0.9:
        print(f"  WARNING: {(~valid).sum()} invalid standardized returns, skipping")
        continue

    # Fit GJR on standardized returns
    r_tilde_series = pd.Series(r_tilde_is, index=spy_is.index)
    res_mf2 = fit_gjr(r_tilde_series)
    params_mf2 = res_mf2.params
    print(f"  Convergence: {res_mf2.convergence_flag == 0}")
    p_mf2 = params_mf2['alpha[1]'] + params_mf2['gamma[1]']/2 + params_mf2['beta[1]']
    print(f"  omega={params_mf2['omega']:.6f}, alpha={params_mf2['alpha[1]']:.6f}, "
          f"gamma={params_mf2['gamma[1]']:.6f}, beta={params_mf2['beta[1]']:.6f}")
    print(f"  Persistence (short-run): {p_mf2:.4f}")

    # OOS: standardize returns by tau, then run GJR recursion
    tau_oos = spy_oos[tau_col].values
    r_tilde_oos = spy_oos['ret'].values / np.sqrt(tau_oos)

    # Initial var for short-run
    last_is_g = res_mf2.conditional_volatility.iloc[-1] ** 2
    last_is_rtilde = r_tilde_is[-1]
    last_is_rtilde2 = last_is_rtilde ** 2
    last_is_ind_mf2 = 1.0 if last_is_rtilde < 0 else 0.0
    initial_var_mf2 = (params_mf2['omega'] + params_mf2['alpha[1]'] * last_is_rtilde2
                       + params_mf2['gamma[1]'] * last_is_rtilde2 * last_is_ind_mf2
                       + params_mf2['beta[1]'] * last_is_g)

    r_tilde_series_oos = pd.Series(r_tilde_oos, index=spy_oos.index)
    oos_g = gjr_recursion(params_mf2, r_tilde_series_oos, initial_var_mf2)

    # Final forecast: sigma² = tau * g
    oos_h_mf2 = tau_oos * oos_g

    results[name] = {
        'forecast': oos_h_mf2,
        'params': {k: float(v) for k, v in params_mf2.items()},
        'persistence_short': float(p_mf2),
        'tau_col': tau_col
    }

# --- 7c. GJR-X (GJR with exogenous VIX² in variance equation) ---
print("\n=== Model: GJR-X (exogenous VIX²) ===")
# Manual GJR-X: h_t = omega + alpha*r²_{t-1} + gamma*r²_{t-1}*I + beta*h_{t-1} + delta*VIX²_{t-1}/252
# Estimate via grid search on IS, minimizing negative log-likelihood

def gjr_x_loglik(params_vec, returns, vix2_lag, dist='t'):
    """Negative log-likelihood for GJR-X model."""
    omega, alpha, gamma_p, beta, delta, nu = params_vec

    # Constraints
    if omega < 0 or alpha < 0 or gamma_p < 0 or beta < 0 or delta < 0:
        return 1e10
    if alpha + gamma_p/2 + beta >= 1.0:
        return 1e10
    if nu <= 2.01:
        return 1e10

    n = len(returns)
    h = np.zeros(n)
    h[0] = np.var(returns[:100]) if len(returns) > 100 else np.var(returns)

    for t in range(1, n):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = (omega + alpha * returns[t-1]**2 + gamma_p * returns[t-1]**2 * ind
                + beta * h[t-1] + delta * vix2_lag[t-1])
        h[t] = max(h[t], 1e-8)

    # Student-t log-likelihood
    from scipy.special import gammaln
    ll = 0.0
    for t in range(n):
        z2 = returns[t]**2 / h[t]
        ll += (gammaln((nu+1)/2) - gammaln(nu/2) - 0.5*np.log(np.pi*(nu-2))
               - 0.5*np.log(h[t]) - (nu+1)/2 * np.log(1 + z2/(nu-2)))

    return -ll

from scipy.optimize import minimize

ret_is = spy_is['ret'].values
vix2_is = spy_is['vix2_lag'].values / 252  # Scale VIX² to daily

# Initial guess from baseline GJR
x0 = [
    float(params_gjr['omega']),
    float(params_gjr['alpha[1]']),
    float(params_gjr['gamma[1]']),
    float(params_gjr['beta[1]']),
    0.001,  # delta (exogenous VIX² effect)
    float(params_gjr.get('nu', 5.0))
]

# Bounds
bounds = [
    (1e-6, 10.0),     # omega
    (1e-6, 0.5),      # alpha
    (1e-6, 0.5),      # gamma
    (0.01, 0.999),    # beta
    (0.0, 1.0),       # delta
    (2.01, 100.0)     # nu
]

opt_result = minimize(gjr_x_loglik, x0, args=(ret_is, vix2_is, 't'),
                      method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': 5000, 'ftol': 1e-12})

if opt_result.success:
    om_x, al_x, ga_x, be_x, de_x, nu_x = opt_result.x
    print(f"  Convergence: True")
    print(f"  omega={om_x:.6f}, alpha={al_x:.6f}, gamma={ga_x:.6f}, "
          f"beta={be_x:.6f}, delta={de_x:.6f}, nu={nu_x:.2f}")
    print(f"  Persistence (excl. VIX): {al_x + ga_x/2 + be_x:.4f}")

    # OOS recursion for GJR-X
    vix2_oos = spy_oos['vix2_lag'].values / 252
    ret_oos_arr = spy_oos['ret'].values
    n_oos = len(ret_oos_arr)
    h_gjrx = np.zeros(n_oos)

    # Initial var: use last IS values
    last_ret = ret_is[-1]
    last_h_is = np.var(ret_is)  # rough estimate
    # Better: compute IS h recursion for last value
    h_is = np.zeros(len(ret_is))
    h_is[0] = np.var(ret_is[:100])
    for t in range(1, len(ret_is)):
        ind = 1.0 if ret_is[t-1] < 0 else 0.0
        h_is[t] = (om_x + al_x * ret_is[t-1]**2 + ga_x * ret_is[t-1]**2 * ind
                   + be_x * h_is[t-1] + de_x * vix2_is[t-1])
        h_is[t] = max(h_is[t], 1e-8)

    # First OOS step
    ind_last = 1.0 if ret_is[-1] < 0 else 0.0
    h_gjrx[0] = (om_x + al_x * ret_is[-1]**2 + ga_x * ret_is[-1]**2 * ind_last
                 + be_x * h_is[-1] + de_x * vix2_is[-1])
    h_gjrx[0] = max(h_gjrx[0], 1e-8)

    for t in range(1, n_oos):
        ind = 1.0 if ret_oos_arr[t-1] < 0 else 0.0
        h_gjrx[t] = (om_x + al_x * ret_oos_arr[t-1]**2 + ga_x * ret_oos_arr[t-1]**2 * ind
                     + be_x * h_gjrx[t-1] + de_x * vix2_oos[t-1])
        h_gjrx[t] = max(h_gjrx[t], 1e-8)

    results['GJR-X'] = {
        'forecast': h_gjrx,
        'params': {'omega': om_x, 'alpha': al_x, 'gamma': ga_x,
                   'beta': be_x, 'delta': de_x, 'nu': nu_x},
        'persistence': float(al_x + ga_x/2 + be_x)
    }
else:
    print(f"  Convergence: FAILED ({opt_result.message})")
    # Fallback: use baseline GJR
    results['GJR-X'] = results['GJR'].copy()
    results['GJR-X']['note'] = 'convergence_failed'

# ============================================================
# 8. Evaluation
# ============================================================
print("\n" + "="*60)
print("OOS EVALUATION")
print("="*60)

r2_oos = spy_oos['r2'].values
ret_oos = spy_oos['ret'].values

def qlike(actual, forecast):
    """QLIKE loss (Patton 2011, proxy-robust)."""
    h = np.maximum(forecast, 1e-8)
    return np.mean(np.log(h) + actual / h)

def mse(actual, forecast):
    return np.mean((actual - forecast) ** 2)

def oos_r2(actual, forecast):
    """OOS R² = 1 - MSE/Var(actual)"""
    return 1 - np.sum((actual - forecast)**2) / np.sum((actual - np.mean(actual))**2)

def mz_regression(actual, forecast):
    """Mincer-Zarnowitz regression."""
    X = np.column_stack([np.ones(len(forecast)), forecast])
    coefs, _, _, _ = lstsq(X, actual, rcond=None)
    y_hat = X @ coefs
    ss_res = np.sum((actual - y_hat) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    r2_score = 1 - ss_res / ss_tot
    return {'intercept': float(coefs[0]), 'slope': float(coefs[1]), 'R2': float(r2_score)}

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (two-sided, HAC variance)."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, max(h, 2)):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return {'t_stat': 0.0, 'p_value': 1.0}

    t_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - sp_stats.norm.cdf(abs(t_stat)))
    return {'t_stat': float(t_stat), 'p_value': float(p_value)}

# Compute losses
model_names = [m for m in ['GJR', 'MF2-VIX', 'MF2-VIX2', 'MF2-Poly', 'MF2-Piecewise', 'GJR-X']
               if m in results]
losses_qlike = {}
losses_mse = {}

print(f"\n{'Model':<16} {'QLIKE':>10} {'MSE':>14} {'OOS-R2':>8} {'MZ-R2':>8} {'MZ-slope':>10}")
print("-" * 70)

eval_results = {}
for name in model_names:
    h = results[name]['forecast']
    q = qlike(r2_oos, h)
    m = mse(r2_oos, h)
    r2_val = oos_r2(r2_oos, h)
    mz = mz_regression(r2_oos, h)

    losses_qlike[name] = np.log(np.maximum(h, 1e-8)) + r2_oos / np.maximum(h, 1e-8)
    losses_mse[name] = (r2_oos - h) ** 2

    print(f"{name:<16} {q:>10.4f} {m:>14.4e} {r2_val:>8.4f} {mz['R2']:>8.4f} {mz['slope']:>10.4f}")

    eval_results[name] = {
        'QLIKE': float(q),
        'MSE': float(m),
        'OOS_R2': float(r2_val),
        'MZ_R2': mz['R2'],
        'MZ_intercept': mz['intercept'],
        'MZ_slope': mz['slope']
    }

# DM tests
print(f"\n{'Pair':<30} {'DM-stat':>10} {'p-value':>10} {'|t|>3.0':>10}")
print("-" * 65)

dm_results = {}

# Key comparisons: each model vs GJR and vs MF2-VIX
comparison_pairs = []
for m in model_names:
    if m != 'GJR':
        comparison_pairs.append(('GJR', m))
    if m != 'MF2-VIX' and m != 'GJR':
        comparison_pairs.append(('MF2-VIX', m))

for m1, m2 in comparison_pairs:
    if m1 in losses_qlike and m2 in losses_qlike:
        dm = dm_test(losses_qlike[m1], losses_qlike[m2])
        pair = f"{m1} vs {m2}"
        sig = "YES" if abs(dm['t_stat']) > 3.0 else "no"
        print(f"{pair:<30} {dm['t_stat']:>10.3f} {dm['p_value']:>10.4f} {sig:>10}")
        dm_results[pair] = dm

# ============================================================
# 9. VaR + ES Backtesting
# ============================================================
print("\n" + "="*60)
print("VaR + ES BACKTESTING")
print("="*60)

def var_backtest(returns, forecast_var, alpha=0.05, dist='t', df=5):
    """VaR backtesting with Kupiec and Christoffersen tests."""
    sigma = np.sqrt(np.maximum(forecast_var, 1e-8))

    if dist == 't':
        scale = np.sqrt((df - 2) / df)
        z = sp_stats.t.ppf(alpha, df) * scale
    else:
        z = sp_stats.norm.ppf(alpha)

    var_level = z * sigma
    violations = returns < var_level
    n_viol = violations.sum()
    n_total = len(returns)
    viol_rate = n_viol / n_total

    # Kupiec
    p_hat = viol_rate
    if p_hat == 0 or p_hat == 1:
        kupiec_stat, kupiec_p = 0.0, 1.0
    else:
        lr = -2 * ((n_total - n_viol) * np.log((1 - alpha) / (1 - p_hat)) +
                    n_viol * np.log(alpha / p_hat))
        kupiec_stat = float(lr)
        kupiec_p = float(1 - sp_stats.chi2.cdf(abs(lr), 1))

    # Christoffersen
    v = violations.astype(int)
    n00 = np.sum((v[:-1] == 0) & (v[1:] == 0))
    n01 = np.sum((v[:-1] == 0) & (v[1:] == 1))
    n10 = np.sum((v[:-1] == 1) & (v[1:] == 0))
    n11 = np.sum((v[:-1] == 1) & (v[1:] == 1))

    if (n00 + n01) > 0 and (n10 + n11) > 0 and n01 > 0 and n10 > 0:
        pi01 = n01 / (n00 + n01)
        pi11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
        pi = (n01 + n11) / (n00 + n01 + n10 + n11)
        if pi11 > 0 and pi11 < 1 and pi01 > 0 and pi01 < 1:
            lr_ind = -2 * (
                (n00 + n10) * np.log(1 - pi) + (n01 + n11) * np.log(pi)
                - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
                - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
            )
            christ_stat = float(lr_ind)
            christ_p = float(1 - sp_stats.chi2.cdf(abs(lr_ind), 1))
        else:
            christ_stat, christ_p = 0.0, 1.0
    else:
        christ_stat, christ_p = 0.0, 1.0

    # ES backtest (McNeil & Frey 2000): average shortfall conditional on VaR violation
    if n_viol > 0:
        if dist == 't':
            es_z = -sp_stats.t.pdf(sp_stats.t.ppf(alpha, df), df) / alpha * ((df + sp_stats.t.ppf(alpha, df)**2) / (df - 1)) * scale
        else:
            es_z = -sp_stats.norm.pdf(sp_stats.norm.ppf(alpha)) / alpha
        es_level = es_z * sigma
        # Excess losses beyond ES
        excess = returns[violations] - es_level[violations]
        es_mean = float(np.mean(excess))
        es_std = float(np.std(excess, ddof=1)) if n_viol > 1 else 0.0
        es_t = es_mean / (es_std / np.sqrt(n_viol)) if es_std > 0 else 0.0
        es_p = 2 * (1 - sp_stats.norm.cdf(abs(es_t))) if es_std > 0 else 1.0
    else:
        es_mean, es_t, es_p = 0.0, 0.0, 1.0

    return {
        'alpha': alpha,
        'n_violations': int(n_viol),
        'n_total': int(n_total),
        'violation_rate': float(viol_rate),
        'expected_rate': float(alpha),
        'kupiec_stat': kupiec_stat,
        'kupiec_p': kupiec_p,
        'christoffersen_stat': christ_stat,
        'christoffersen_p': christ_p,
        'es_excess_mean': es_mean,
        'es_t_stat': float(es_t),
        'es_p_value': float(es_p)
    }

df_t = float(params_gjr.get('nu', 5.0))

var_results = {}
for alpha_level in [0.01, 0.05]:
    print(f"\nVaR {int(alpha_level*100)}%:")
    print(f"{'Model':<16} {'Violations':>11} {'Rate':>8} {'Expected':>9} {'Kupiec-p':>10} {'ES-t':>8}")
    print("-" * 66)

    for name in model_names:
        h = results[name]['forecast']
        vb = var_backtest(ret_oos, h, alpha=alpha_level, dist='t', df=df_t)
        key = f"{name}_VaR{int(alpha_level*100)}"
        var_results[key] = vb
        print(f"{name:<16} {vb['n_violations']:>5}/{vb['n_total']:<5} "
              f"{vb['violation_rate']:>8.4f} {vb['expected_rate']:>9.4f} "
              f"{vb['kupiec_p']:>10.4f} {vb['es_t_stat']:>8.3f}")

# ============================================================
# 10. Plots
# ============================================================

# --- 10a. Tau comparison ---
fig, axes = plt.subplots(2, 2, figsize=(14, 10))

tau_plot_data = [
    ('MF2-VIX (baseline)', 'tau_vix'),
    ('MF2-VIX² (quadratic)', 'tau_vix2'),
    ('MF2-Poly (polynomial)', 'tau_poly'),
    ('MF2-Piecewise', 'tau_piecewise')
]

for ax, (title, col) in zip(axes.flat, tau_plot_data):
    tau_vals = np.sqrt(spy[col].values) * np.sqrt(252)  # annualized vol
    ax.plot(spy.index.to_numpy(), tau_vals, color='steelblue', alpha=0.7, linewidth=0.6)
    ax.axvline(pd.Timestamp(IS_END), color='red', linestyle='--', alpha=0.5)
    ax.set_ylabel('Ann. Vol (%)')
    ax.set_title(f'tau: {title}')
    ax.grid(True, alpha=0.3)

plt.suptitle('K989: Long-run Component (tau) Variants', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig(f'{SCRIPT_DIR}/k989_tau_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print("\nSaved: k989_tau_comparison.png")

# --- 10b. OOS comparison ---
fig, axes = plt.subplots(3, 1, figsize=(14, 12))

# Top: forecasts vs realized
ax = axes[0]
dates_oos = spy_oos.index.to_numpy()
ax.plot(dates_oos, np.sqrt(r2_oos) * np.sqrt(252), color='gray', alpha=0.2,
        linewidth=0.4, label='|r| (ann.)')
colors = {'GJR': 'black', 'MF2-VIX': 'blue', 'MF2-VIX2': 'red',
          'MF2-Poly': 'green', 'MF2-Piecewise': 'orange', 'GJR-X': 'purple'}
for name in model_names:
    h = results[name]['forecast']
    ax.plot(dates_oos, np.sqrt(h) * np.sqrt(252), color=colors.get(name, 'gray'),
            alpha=0.7, linewidth=0.7, label=name)
ax.set_ylabel('Annualized Vol (%)')
ax.set_title('OOS Volatility Forecasts (2019-2026)')
ax.legend(loc='upper right', fontsize=7, ncol=2)
ax.grid(True, alpha=0.3)

# Middle: cumulative QLIKE difference vs GJR
ax = axes[1]
for name in model_names:
    if name == 'GJR':
        continue
    diff = losses_qlike['GJR'] - losses_qlike[name]
    cum_diff = np.cumsum(diff)
    ax.plot(dates_oos, cum_diff, color=colors.get(name, 'gray'),
            linewidth=1.0, label=f'{name}', alpha=0.8)
ax.axhline(0, color='black', linestyle='--', alpha=0.3)
ax.set_ylabel('Cumulative QLIKE gain over GJR')
ax.set_title('Cumulative QLIKE Advantage over GJR (positive = model better)')
ax.legend(loc='upper left', fontsize=7)
ax.grid(True, alpha=0.3)

# Bottom: cumulative QLIKE difference vs MF2-VIX
ax = axes[2]
for name in model_names:
    if name in ('GJR', 'MF2-VIX'):
        continue
    diff = losses_qlike['MF2-VIX'] - losses_qlike[name]
    cum_diff = np.cumsum(diff)
    ax.plot(dates_oos, cum_diff, color=colors.get(name, 'gray'),
            linewidth=1.0, label=f'{name}', alpha=0.8)
ax.axhline(0, color='black', linestyle='--', alpha=0.3)
ax.set_ylabel('Cumulative QLIKE gain over MF2-VIX')
ax.set_title('Cumulative QLIKE Advantage over MF2-VIX (positive = model better)')
ax.legend(loc='upper left', fontsize=7)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(f'{SCRIPT_DIR}/k989_oos_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print("Saved: k989_oos_comparison.png")

# ============================================================
# 11. Save Results
# ============================================================

best_model = min(eval_results, key=lambda x: eval_results[x]['QLIKE'])

# QLIKE improvements
gjr_qlike = eval_results['GJR']['QLIKE']
vix_qlike = eval_results.get('MF2-VIX', {}).get('QLIKE', gjr_qlike)

improvements_vs_gjr = {}
improvements_vs_mf2vix = {}
for m, e in eval_results.items():
    if m != 'GJR':
        improvements_vs_gjr[m] = float((gjr_qlike - e['QLIKE']) / abs(gjr_qlike) * 100)
    if m != 'MF2-VIX' and 'MF2-VIX' in eval_results:
        improvements_vs_mf2vix[m] = float((vix_qlike - e['QLIKE']) / abs(vix_qlike) * 100)

output = {
    'experiment_id': 'K989',
    'title': 'MF2-VIX + VIX² Convexity Synthesis',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'method': 'MF2-GARCH with VIX² convexity-enhanced tau variants',
    'builds_on': ['K970 (MF2-VIX)', 'K987 (VIX² nonlinearity)', 'K986 (LASSO VIX² selection)'],
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{spy.index[0].date()} to {spy.index[-1].date()}",
    'sample_sizes': {
        'total': int(len(spy)),
        'IS': int(len(spy_is)),
        'OOS': int(len(spy_oos))
    },
    'IS_period': f"{spy_is.index[0].date()} to {spy_is.index[-1].date()}",
    'OOS_period': f"{spy_oos.index[0].date()} to {spy_oos.index[-1].date()}",
    'tau_calibration': {
        'MF2-VIX': 'tau = (VIX_{t-1}/sqrt(252))^2, no calibration needed',
        'MF2-VIX2': {
            'formula': 'tau = alpha + beta1*VIX^2/252 + beta2*VIX^4/252^2',
            'alpha': float(coef_vix2[0]),
            'beta1': float(coef_vix2[1]),
            'beta2': float(coef_vix2[2])
        },
        'MF2-Poly': {
            'formula': 'tau = a + b1*VIX/sqrt(252) + b2*VIX^2/252',
            'a': float(coef_poly[0]),
            'b1': float(coef_poly[1]),
            'b2': float(coef_poly[2])
        },
        'MF2-Piecewise': {
            'formula': 'tau = (VIX/sqrt(252))^2 * (1 + delta*max(VIX-20,0))',
            'delta': float(best_delta)
        }
    },
    'models': {},
    'evaluation': eval_results,
    'dm_tests': dm_results,
    'var_backtesting': var_results,
    'improvements_vs_gjr_pct': improvements_vs_gjr,
    'improvements_vs_mf2vix_pct': improvements_vs_mf2vix,
    'best_model': best_model,
    'conclusion': '',
    'references': [
        'Conrad, C. & Engle, R. (2025). Two-component GARCH. J. Applied Econometrics.',
        'Patton, A.J. (2011). Volatility forecast comparison. J. Econometrics, 160(1), 246-256.',
        'Harvey, C.R., Liu, Y., & Zhu, H. (2016). ...and cross-section. RFS.',
        'McNeil, A.J. & Frey, R. (2000). Estimation of tail-related risk measures. J. Empirical Finance.'
    ],
    'seed': 42,
    'timestamp': datetime.now().isoformat()
}

# Model details
for name in model_names:
    info = {'params': results[name].get('params', {})}
    if 'persistence' in results[name]:
        info['persistence'] = results[name]['persistence']
    if 'persistence_short' in results[name]:
        info['persistence_short'] = results[name]['persistence_short']
    if 'note' in results[name]:
        info['note'] = results[name]['note']
    output['models'][name] = info

# Conclusion
conclusion_parts = [
    f"Best model by QLIKE: {best_model} ({eval_results[best_model]['QLIKE']:.4f})",
    f"GJR baseline QLIKE: {gjr_qlike:.4f}",
]
for m, imp in sorted(improvements_vs_gjr.items(), key=lambda x: -x[1]):
    direction = "improvement" if imp > 0 else "worse"
    conclusion_parts.append(f"{m}: {abs(imp):.2f}% {direction} over GJR")

if improvements_vs_mf2vix:
    conclusion_parts.append("--- vs MF2-VIX ---")
    for m, imp in sorted(improvements_vs_mf2vix.items(), key=lambda x: -x[1]):
        if m not in ('GJR',):
            direction = "improvement" if imp > 0 else "worse"
            conclusion_parts.append(f"{m}: {abs(imp):.2f}% {direction} over MF2-VIX")

# DM significance
sig_pairs = [p for p, v in dm_results.items() if abs(v['t_stat']) > 3.0]
if sig_pairs:
    conclusion_parts.append(f"DM significant (|t|>3.0): {', '.join(sig_pairs)}")
else:
    conclusion_parts.append("No pairs pass Harvey (2016) |t|>3.0 threshold")

output['conclusion'] = '; '.join(conclusion_parts)

with open(f'{SCRIPT_DIR}/k989_mf2_vix2_results.json', 'w') as f:
    json.dump(output, f, indent=2, default=str)

print("\n" + "="*60)
print("CONCLUSION")
print("="*60)
for part in conclusion_parts:
    print(f"  {part}")

print(f"\nResults saved to {SCRIPT_DIR}/k989_mf2_vix2_results.json")
print("Done.")
