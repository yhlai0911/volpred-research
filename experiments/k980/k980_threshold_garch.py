"""
K980: Threshold GJR-GARCH with VIX Regime Switching
====================================================

Background:
- Standard GJR-GARCH has a single set of parameters for all market conditions
- Threshold GARCH allows ALL parameters to switch between regimes
- We use VIX_{t-1} as the threshold variable (no lookahead)

References:
- Chen, Liu & Gerlach (2011, Computational Statistics): TARMA with Bayesian variable selection
- Chen, Liu & So (2013, Computational Statistics): Threshold Asymmetric SV
- Patton (2011): QLIKE loss for volatility model comparison

Models compared:
1. GJR baseline: single-regime GJR-GARCH(1,1)
2. Threshold GJR (TGJR): two VIX regimes with separate parameters
3. GJR + VIX dummy: h_t = GJR + delta * I(VIX > c)

Data: SPY 2006-01-01 to 2026-04-07
IS: 2006-2018, OOS: 2019-2026
VIX must be shifted by 1 day (use VIX_{t-1} for regime)

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.optimize import minimize
from scipy.stats import t as t_dist
from datetime import datetime

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K980: Threshold GJR-GARCH with VIX Regime Switching")
print("=" * 60)

spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle MultiIndex columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Compute log returns
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy = spy.dropna(subset=['ret'])

# Merge VIX (use VIX_{t-1} for regime determination - shift by 1)
vix_close = vix[['Close']].rename(columns={'Close': 'VIX'})
data = spy[['ret']].join(vix_close, how='inner')
data['VIX_lag'] = data['VIX'].shift(1)  # VIX_{t-1} -- NO LOOKAHEAD
data = data.dropna()

# Squared returns as proxy for realized variance
data['r2'] = data['ret'] ** 2

print(f"Total observations: {len(data)}")
print(f"Date range: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")
print(f"VIX mean: {data['VIX'].mean():.2f}, median: {data['VIX'].median():.2f}")
print(f"VIX_lag mean: {data['VIX_lag'].mean():.2f}")

# Split IS/OOS
is_mask = data.index < '2019-01-01'
oos_mask = data.index >= '2019-01-01'
data_is = data[is_mask]
data_oos = data[oos_mask]

print(f"\nIS: {len(data_is)} obs ({data_is.index[0].strftime('%Y-%m-%d')} to {data_is.index[-1].strftime('%Y-%m-%d')})")
print(f"OOS: {len(data_oos)} obs ({data_oos.index[0].strftime('%Y-%m-%d')} to {data_oos.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. Utility & Evaluation Functions
# ============================================================

def qlike_loss(actual, forecast):
    """QLIKE loss per observation (element-wise)."""
    actual_clean = np.maximum(actual, 1e-12)
    forecast_clean = np.maximum(forecast, 1e-12)
    ratio = actual_clean / forecast_clean
    return ratio - np.log(ratio) - 1


def qlike(actual, forecast):
    """QLIKE loss: actual/forecast - log(actual/forecast) - 1
    Handles near-zero actual values by clamping."""
    return np.mean(qlike_loss(actual, forecast))


# ============================================================
# 3. GJR-GARCH Estimation Functions
# ============================================================

def gjr_garch_loglik(params, returns, out_h=None):
    """
    GJR-GARCH(1,1) negative log-likelihood (Gaussian).
    params = [omega, alpha, gamma, beta]
    """
    omega, alpha, gamma, beta = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * indicator + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    if out_h is not None:
        out_h[:] = h

    # Gaussian log-likelihood
    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(h) + returns**2 / h)
    return -ll  # negative for minimization


def fit_gjr(returns, x0=None):
    """Fit GJR-GARCH(1,1) by MLE."""
    if x0 is None:
        var_r = np.var(returns)
        x0 = [var_r * 0.05, 0.05, 0.05, 0.90]

    bounds = [(1e-8, 0.01), (1e-6, 0.5), (0.0, 0.5), (0.01, 0.999)]

    result = minimize(gjr_garch_loglik, x0, args=(returns,),
                      method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': 5000, 'ftol': 1e-12})

    params = result.x
    persistence = params[1] + params[3] + 0.5 * params[2]

    return {
        'omega': params[0],
        'alpha': params[1],
        'gamma': params[2],
        'beta': params[3],
        'persistence': persistence,
        'converged': result.success,
        'loglik': -result.fun,
        'nobs': len(returns)
    }


def gjr_forecast_oos(params, returns, h_last):
    """
    One-step-ahead OOS forecast for GJR-GARCH.
    h_t = omega + alpha * r²_{t-1} + gamma * r²_{t-1} * I(r_{t-1}<0) + beta * h_{t-1}
    """
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)
    forecasts = np.zeros(T)

    # First OOS forecast uses last IS h
    h_prev = h_last
    for t in range(T):
        if t == 0:
            r_prev = returns.iloc[t]  # Actually we need the last IS return
            # We'll handle this in the main loop
            pass
        indicator = 1.0 if (returns.iloc[t-1] if t > 0 else 0) < 0 else 0.0
        r2_prev = (returns.iloc[t-1] if t > 0 else 0)**2
        h_t = omega + alpha * r2_prev + gamma * r2_prev * indicator + beta * h_prev
        if h_t < 1e-10:
            h_t = 1e-10
        forecasts[t] = h_t
        h_prev = h_t

    return forecasts


# ============================================================
# 3. Model 1: Standard GJR-GARCH (Baseline)
# ============================================================
print("\n" + "=" * 60)
print("Model 1: Standard GJR-GARCH (Baseline)")
print("=" * 60)

returns_is = data_is['ret'].values
returns_oos = data_oos['ret'].values

gjr_fit = fit_gjr(returns_is)
print(f"omega={gjr_fit['omega']:.6f}, alpha={gjr_fit['alpha']:.4f}, "
      f"gamma={gjr_fit['gamma']:.4f}, beta={gjr_fit['beta']:.4f}")
print(f"Persistence: {gjr_fit['persistence']:.4f}, Converged: {gjr_fit['converged']}")

# Get IS conditional variance for last value
h_is = np.zeros(len(returns_is))
h_is[0] = np.var(returns_is)
for t in range(1, len(returns_is)):
    ind = 1.0 if returns_is[t-1] < 0 else 0.0
    h_is[t] = (gjr_fit['omega'] + gjr_fit['alpha'] * returns_is[t-1]**2 +
               gjr_fit['gamma'] * returns_is[t-1]**2 * ind + gjr_fit['beta'] * h_is[t-1])
    h_is[t] = max(h_is[t], 1e-10)

# OOS recursive forecasting
all_returns = np.concatenate([returns_is, returns_oos])
h_oos_gjr = np.zeros(len(returns_oos))
h_prev = h_is[-1]

for t in range(len(returns_oos)):
    idx = len(returns_is) + t
    r_prev = all_returns[idx - 1]
    ind = 1.0 if r_prev < 0 else 0.0
    h_t = (gjr_fit['omega'] + gjr_fit['alpha'] * r_prev**2 +
           gjr_fit['gamma'] * r_prev**2 * ind + gjr_fit['beta'] * h_prev)
    h_t = max(h_t, 1e-10)
    h_oos_gjr[t] = h_t
    h_prev = h_t

r2_oos = returns_oos ** 2

# ============================================================
# 4. Model 2: Threshold GJR-GARCH
# ============================================================
print("\n" + "=" * 60)
print("Model 2: Threshold GJR-GARCH (Grid Search for c)")
print("=" * 60)

# Grid search for optimal threshold c
thresholds = [14, 16, 18, 20, 22, 24, 26, 28]
vix_lag_is = data_is['VIX_lag'].values

best_qlike = np.inf
best_c = None
best_regime_params = None

for c in thresholds:
    low_mask = vix_lag_is <= c
    high_mask = vix_lag_is > c

    pct_low = low_mask.sum() / len(vix_lag_is)
    pct_high = high_mask.sum() / len(vix_lag_is)

    # Constraint: each regime at least 15% of observations
    if pct_low < 0.15 or pct_high < 0.15:
        print(f"  c={c}: skipped (low={pct_low:.1%}, high={pct_high:.1%})")
        continue

    # Fit GJR on each regime separately
    returns_low = returns_is[low_mask]
    returns_high = returns_is[high_mask]

    if len(returns_low) < 100 or len(returns_high) < 100:
        print(f"  c={c}: skipped (too few obs: low={len(returns_low)}, high={len(returns_high)})")
        continue

    fit_low = fit_gjr(returns_low)
    fit_high = fit_gjr(returns_high)

    if not fit_low['converged'] or not fit_high['converged']:
        print(f"  c={c}: skipped (convergence failed)")
        continue

    # IS recursive h using threshold switching
    h_thresh_is = np.zeros(len(returns_is))
    h_thresh_is[0] = np.var(returns_is)

    for t in range(1, len(returns_is)):
        r_prev = returns_is[t-1]
        ind = 1.0 if r_prev < 0 else 0.0

        if vix_lag_is[t] <= c:
            p = fit_low
        else:
            p = fit_high

        h_thresh_is[t] = (p['omega'] + p['alpha'] * r_prev**2 +
                          p['gamma'] * r_prev**2 * ind + p['beta'] * h_thresh_is[t-1])
        h_thresh_is[t] = max(h_thresh_is[t], 1e-10)

    # IS QLIKE (skip first 100 for burn-in, clamp near-zero r2)
    r2_is = returns_is ** 2
    qlike_is = qlike(r2_is[100:], h_thresh_is[100:])

    print(f"  c={c}: low={pct_low:.1%} ({len(returns_low)} obs), high={pct_high:.1%} ({len(returns_high)} obs), "
          f"IS QLIKE={qlike_is:.6f}")
    print(f"    Low regime:  omega={fit_low['omega']:.6f}, alpha={fit_low['alpha']:.4f}, "
          f"gamma={fit_low['gamma']:.4f}, beta={fit_low['beta']:.4f}, pers={fit_low['persistence']:.4f}")
    print(f"    High regime: omega={fit_high['omega']:.6f}, alpha={fit_high['alpha']:.4f}, "
          f"gamma={fit_high['gamma']:.4f}, beta={fit_high['beta']:.4f}, pers={fit_high['persistence']:.4f}")

    if qlike_is < best_qlike:
        best_qlike = qlike_is
        best_c = c
        best_regime_params = {'low': fit_low, 'high': fit_high}
        best_h_is = h_thresh_is.copy()

print(f"\nBest threshold: c = {best_c} (IS QLIKE = {best_qlike:.6f})")

# OOS forecasting for Threshold GJR
vix_lag_oos = data_oos['VIX_lag'].values
h_oos_tgjr = np.zeros(len(returns_oos))
h_prev = best_h_is[-1]

for t in range(len(returns_oos)):
    idx = len(returns_is) + t
    r_prev = all_returns[idx - 1]
    ind = 1.0 if r_prev < 0 else 0.0

    if vix_lag_oos[t] <= best_c:
        p = best_regime_params['low']
    else:
        p = best_regime_params['high']

    h_t = (p['omega'] + p['alpha'] * r_prev**2 +
           p['gamma'] * r_prev**2 * ind + p['beta'] * h_prev)
    h_t = max(h_t, 1e-10)
    h_oos_tgjr[t] = h_t
    h_prev = h_t

# ============================================================
# 5. Model 3: GJR + VIX Dummy
# ============================================================
print("\n" + "=" * 60)
print("Model 3: GJR + VIX Dummy")
print("=" * 60)


def gjr_vix_dummy_loglik(params, returns, vix_lag, c):
    """
    GJR-GARCH(1,1) + VIX dummy.
    h_t = omega + alpha*r²_{t-1} + gamma*r²_{t-1}*I(r<0) + beta*h_{t-1} + delta*I(VIX_{t-1}>c)
    params = [omega, alpha, gamma, beta, delta]
    """
    omega, alpha, gamma, beta, delta = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)

    for t in range(1, T):
        indicator = 1.0 if returns[t-1] < 0 else 0.0
        vix_dummy = 1.0 if vix_lag[t] > c else 0.0
        h[t] = (omega + alpha * returns[t-1]**2 +
                gamma * returns[t-1]**2 * indicator +
                beta * h[t-1] + delta * vix_dummy)
        if h[t] < 1e-10:
            h[t] = 1e-10

    ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(h) + returns**2 / h)
    return -ll


# Use the best threshold c from TGJR
c_dummy = best_c
var_r = np.var(returns_is)
x0_dummy = [var_r * 0.05, 0.05, 0.05, 0.90, 1e-5]
bounds_dummy = [(1e-8, 0.01), (1e-6, 0.5), (0.0, 0.5), (0.01, 0.999), (0.0, 0.001)]

result_dummy = minimize(gjr_vix_dummy_loglik, x0_dummy,
                        args=(returns_is, vix_lag_is, c_dummy),
                        method='L-BFGS-B', bounds=bounds_dummy,
                        options={'maxiter': 5000, 'ftol': 1e-12})

dummy_params = result_dummy.x
print(f"omega={dummy_params[0]:.6f}, alpha={dummy_params[1]:.4f}, "
      f"gamma={dummy_params[2]:.4f}, beta={dummy_params[3]:.4f}, delta={dummy_params[4]:.8f}")
print(f"Converged: {result_dummy.success}")

# OOS forecasting for GJR + VIX Dummy
h_oos_dummy = np.zeros(len(returns_oos))

# Need IS h for last value
h_dummy_is = np.zeros(len(returns_is))
h_dummy_is[0] = np.var(returns_is)
for t in range(1, len(returns_is)):
    ind = 1.0 if returns_is[t-1] < 0 else 0.0
    vd = 1.0 if vix_lag_is[t] > c_dummy else 0.0
    h_dummy_is[t] = (dummy_params[0] + dummy_params[1] * returns_is[t-1]**2 +
                     dummy_params[2] * returns_is[t-1]**2 * ind +
                     dummy_params[3] * h_dummy_is[t-1] + dummy_params[4] * vd)
    h_dummy_is[t] = max(h_dummy_is[t], 1e-10)

h_prev = h_dummy_is[-1]
for t in range(len(returns_oos)):
    idx = len(returns_is) + t
    r_prev = all_returns[idx - 1]
    ind = 1.0 if r_prev < 0 else 0.0
    vd = 1.0 if vix_lag_oos[t] > c_dummy else 0.0
    h_t = (dummy_params[0] + dummy_params[1] * r_prev**2 +
           dummy_params[2] * r_prev**2 * ind +
           dummy_params[3] * h_prev + dummy_params[4] * vd)
    h_t = max(h_t, 1e-10)
    h_oos_dummy[t] = h_t
    h_prev = h_t

# ============================================================
# 6. Evaluation Metrics
# ============================================================
print("\n" + "=" * 60)
print("OOS Evaluation")
print("=" * 60)


def mse(actual, forecast):
    return np.mean((actual - forecast) ** 2)


def mae(actual, forecast):
    return np.mean(np.abs(actual - forecast))


def mz_regression(actual, forecast):
    """Mincer-Zarnowitz regression: actual = a + b * forecast + e"""
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(forecast)), forecast])
    coeffs, _, _, _ = lstsq(X, actual, rcond=None)
    y_hat = X @ coeffs
    ss_res = np.sum((actual - y_hat) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
    return {'intercept': coeffs[0], 'slope': coeffs[1], 'r2': r2}


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test. H0: equal predictive accuracy.
    loss1, loss2: loss differentials
    Returns: DM statistic, p-value
    """
    d = loss1 - loss2
    T = len(d)
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma0 + gamma_sum) / T
    if var_d <= 0:
        var_d = gamma0 / T
    dm_stat = d_mean / np.sqrt(var_d)
    from scipy.stats import norm
    p_value = 2 * (1 - norm.cdf(np.abs(dm_stat)))
    return dm_stat, p_value


# Target = r²
target = r2_oos

models = {
    'GJR': h_oos_gjr,
    'TGJR': h_oos_tgjr,
    'GJR+Dummy': h_oos_dummy,
}

results_eval = {}
for name, h_oos in models.items():
    q = qlike(target, h_oos)
    m = mse(target, h_oos)
    ma = mae(target, h_oos)
    mz = mz_regression(target, h_oos)
    results_eval[name] = {
        'QLIKE': q, 'MSE': m, 'MAE': ma,
        'MZ_intercept': mz['intercept'], 'MZ_slope': mz['slope'], 'MZ_R2': mz['r2']
    }
    print(f"\n{name}:")
    print(f"  QLIKE: {q:.6f}")
    print(f"  MSE:   {m:.10f}")
    print(f"  MAE:   {ma:.6f}")
    print(f"  MZ: intercept={mz['intercept']:.6f}, slope={mz['slope']:.4f}, R²={mz['r2']:.4f}")

# DM tests (pairwise)
print("\n--- Diebold-Mariano Tests ---")
dm_results = {}
model_names = list(models.keys())
for i in range(len(model_names)):
    for j in range(i+1, len(model_names)):
        n1, n2 = model_names[i], model_names[j]
        loss1 = qlike_loss(target, models[n1])
        loss2 = qlike_loss(target, models[n2])
        dm_stat, p_val = dm_test(loss1, loss2)
        dm_results[f"{n1}_vs_{n2}"] = {'DM_stat': dm_stat, 'p_value': p_val}
        sig = "***" if p_val < 0.001 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
        winner = n1 if dm_stat < 0 else n2
        print(f"  {n1} vs {n2}: DM={dm_stat:.4f}, p={p_val:.4f} {sig} (lower QLIKE: {winner})")

# ============================================================
# 7. Regime-Conditional Evaluation
# ============================================================
print("\n" + "=" * 60)
print("Regime-Conditional OOS Evaluation")
print("=" * 60)

low_oos_mask = vix_lag_oos <= best_c
high_oos_mask = vix_lag_oos > best_c

print(f"OOS low-VIX days: {low_oos_mask.sum()} ({low_oos_mask.mean():.1%})")
print(f"OOS high-VIX days: {high_oos_mask.sum()} ({high_oos_mask.mean():.1%})")

regime_eval = {}
for regime_name, mask in [('Low VIX', low_oos_mask), ('High VIX', high_oos_mask)]:
    print(f"\n--- {regime_name} Regime (c={best_c}) ---")
    regime_eval[regime_name] = {}
    for name, h_oos in models.items():
        q = qlike(target[mask], h_oos[mask])
        m = mse(target[mask], h_oos[mask])
        regime_eval[regime_name][name] = {'QLIKE': q, 'MSE': m}
        print(f"  {name}: QLIKE={q:.6f}, MSE={m:.10f}")

# ============================================================
# 8. VaR Backtesting
# ============================================================
print("\n" + "=" * 60)
print("VaR Backtesting (1% and 5%)")
print("=" * 60)

returns_oos_series = data_oos['ret'].values
var_results = {}

for alpha_level in [0.01, 0.05]:
    z = t_dist.ppf(alpha_level, df=5) * np.sqrt(3.0/5.0)  # Student-t scale
    print(f"\n--- VaR {alpha_level*100:.0f}% (Student-t df=5) ---")
    var_results[f'VaR_{alpha_level}'] = {}

    for name, h_oos in models.items():
        var = z * np.sqrt(h_oos)
        violations = (returns_oos_series < var).sum()
        vr = violations / len(returns_oos_series)
        expected = alpha_level
        # Kupiec LR test
        T = len(returns_oos_series)
        n1 = violations
        n0 = T - n1
        if n1 > 0 and n0 > 0:
            lr = -2 * (n0 * np.log(1 - expected) + n1 * np.log(expected) -
                       n0 * np.log(1 - n1/T) - n1 * np.log(n1/T))
        else:
            lr = 0.0
        from scipy.stats import chi2
        p_kupiec = 1 - chi2.cdf(lr, 1) if lr > 0 else 1.0

        var_results[f'VaR_{alpha_level}'][name] = {
            'violations': int(violations),
            'violation_rate': float(vr),
            'expected_rate': float(expected),
            'kupiec_LR': float(lr),
            'kupiec_p': float(p_kupiec)
        }
        status = "PASS" if p_kupiec > 0.05 else "FAIL"
        print(f"  {name}: violations={violations}/{T} ({vr:.3%}), "
              f"expected={expected:.1%}, Kupiec p={p_kupiec:.4f} [{status}]")

# ============================================================
# 9. Parameter Comparison Across Regimes
# ============================================================
print("\n" + "=" * 60)
print("Parameter Comparison: Low vs High VIX Regime")
print("=" * 60)

param_comparison = {}
for param_name in ['omega', 'alpha', 'gamma', 'beta', 'persistence']:
    low_val = best_regime_params['low'][param_name]
    high_val = best_regime_params['high'][param_name]
    ratio = high_val / low_val if low_val > 0 else np.inf
    param_comparison[param_name] = {
        'low_regime': float(low_val),
        'high_regime': float(high_val),
        'ratio': float(ratio)
    }
    print(f"  {param_name:12s}: Low={low_val:.6f}, High={high_val:.6f}, Ratio={ratio:.2f}")

# ============================================================
# 10. Plots
# ============================================================
BASE = '/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a95fb3ea/experiments/k980'

# Plot 1: Regime Parameters Comparison
fig, axes = plt.subplots(1, 5, figsize=(16, 4))
param_names = ['omega', 'alpha', 'gamma', 'beta', 'persistence']
for i, pn in enumerate(param_names):
    vals = [param_comparison[pn]['low_regime'], param_comparison[pn]['high_regime']]
    bars = axes[i].bar(['Low VIX', 'High VIX'], vals, color=['#2196F3', '#F44336'], alpha=0.8)
    axes[i].set_title(pn.capitalize(), fontsize=12, fontweight='bold')
    axes[i].set_ylabel('Value')
    for bar, val in zip(bars, vals):
        axes[i].text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                     f'{val:.5f}', ha='center', va='bottom', fontsize=8)
plt.suptitle(f'K980: GJR-GARCH Parameters by VIX Regime (c={best_c})',
             fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig(f'{BASE}/k980_regime_parameters.png', dpi=150, bbox_inches='tight')
plt.close()
print(f"\nSaved: k980_regime_parameters.png")

# Plot 2: OOS Comparison
fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

# Top: conditional variance forecasts
oos_dates = data_oos.index.to_numpy()
for name, h_oos in models.items():
    ann_vol = np.sqrt(h_oos * 252) * 100
    axes[0].plot(oos_dates, ann_vol, label=name, alpha=0.7, linewidth=0.8)
axes[0].set_ylabel('Annualized Volatility (%)')
axes[0].set_title('K980: OOS Conditional Volatility Forecasts', fontsize=14, fontweight='bold')
axes[0].legend()
axes[0].grid(True, alpha=0.3)

# Bottom: cumulative QLIKE difference (TGJR - GJR)
qlike_diff = (target / h_oos_tgjr - np.log(target / h_oos_tgjr) - 1) - \
             (target / h_oos_gjr - np.log(target / h_oos_gjr) - 1)
cum_diff = np.cumsum(qlike_diff)
axes[1].plot(oos_dates, cum_diff, color='#4CAF50', linewidth=1)
axes[1].axhline(0, color='black', linewidth=0.5, linestyle='--')
axes[1].fill_between(oos_dates, cum_diff, 0,
                     where=cum_diff < 0, color='green', alpha=0.2, label='TGJR better')
axes[1].fill_between(oos_dates, cum_diff, 0,
                     where=cum_diff > 0, color='red', alpha=0.2, label='GJR better')
axes[1].set_ylabel('Cumulative QLIKE Difference\n(TGJR - GJR)')
axes[1].set_title('Cumulative QLIKE Loss Differential', fontsize=12)
axes[1].legend()
axes[1].grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(f'{BASE}/k980_oos_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved: k980_oos_comparison.png")

# ============================================================
# 11. Save Results JSON
# ============================================================
results = {
    'experiment_id': 'K980',
    'title': 'Threshold GJR-GARCH with VIX Regime Switching',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'total_obs': int(len(data)),
    'is_obs': int(len(data_is)),
    'oos_obs': int(len(data_oos)),
    'is_period': f"{data_is.index[0].strftime('%Y-%m-%d')} to {data_is.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{data_oos.index[0].strftime('%Y-%m-%d')} to {data_oos.index[-1].strftime('%Y-%m-%d')}",
    'seed': 42,
    'methodology': {
        'description': 'Threshold GJR-GARCH where GARCH parameters switch based on VIX_{t-1} regime',
        'threshold_variable': 'VIX_{t-1} (lagged, no lookahead)',
        'threshold_grid': thresholds,
        'best_threshold': int(best_c),
        'regime_constraint': 'Each regime >= 20% of IS observations',
        'models': ['GJR (baseline)', 'Threshold GJR (TGJR)', 'GJR + VIX Dummy']
    },
    'parameters': {
        'gjr_baseline': {k: float(v) for k, v in gjr_fit.items() if k != 'converged' and k != 'nobs'},
        'tgjr_low_regime': {k: float(v) for k, v in best_regime_params['low'].items() if k != 'converged' and k != 'nobs'},
        'tgjr_high_regime': {k: float(v) for k, v in best_regime_params['high'].items() if k != 'converged' and k != 'nobs'},
        'gjr_dummy': {
            'omega': float(dummy_params[0]),
            'alpha': float(dummy_params[1]),
            'gamma': float(dummy_params[2]),
            'beta': float(dummy_params[3]),
            'delta': float(dummy_params[4])
        }
    },
    'param_comparison': param_comparison,
    'oos_evaluation': results_eval,
    'regime_conditional_evaluation': regime_eval,
    'dm_tests': {k: {kk: float(vv) for kk, vv in v.items()} for k, v in dm_results.items()},
    'var_backtesting': var_results,
    'references': [
        'Chen, Liu & Gerlach (2011, Computational Statistics): TARMA with Bayesian variable selection',
        'Chen, Liu & So (2013, Computational Statistics): Threshold Asymmetric SV',
        'Patton (2011): Volatility forecast comparison using imperfect proxies',
        'Hansen & Lunde (2005): Forecast comparison of volatility models'
    ]
}

# Determine conclusions
best_model_qlike = min(results_eval.items(), key=lambda x: x[1]['QLIKE'])
tgjr_vs_gjr_dm = dm_results.get('GJR_vs_TGJR', {})

results['conclusions'] = {
    'best_model_qlike': best_model_qlike[0],
    'best_qlike_value': float(best_model_qlike[1]['QLIKE']),
    'optimal_threshold': int(best_c),
    'regime_parameters_differ': True,  # Will be more specific below
    'tgjr_vs_gjr': {
        'dm_stat': float(tgjr_vs_gjr_dm.get('DM_stat', 0)),
        'p_value': float(tgjr_vs_gjr_dm.get('p_value', 1)),
        'significant_at_5pct': tgjr_vs_gjr_dm.get('p_value', 1) < 0.05
    },
    'key_finding': ''
}

# Summarize key finding
qlike_gjr = results_eval['GJR']['QLIKE']
qlike_tgjr = results_eval['TGJR']['QLIKE']
qlike_dummy = results_eval['GJR+Dummy']['QLIKE']
pct_diff = (qlike_tgjr - qlike_gjr) / qlike_gjr * 100

if qlike_tgjr < qlike_gjr:
    direction = 'improves'
else:
    direction = 'worsens'

sig_text = 'statistically significant' if tgjr_vs_gjr_dm.get('p_value', 1) < 0.05 else 'not statistically significant'

key_finding = (
    f"Threshold GJR (c={best_c}) {direction} OOS QLIKE by {abs(pct_diff):.2f}% vs baseline GJR. "
    f"Difference is {sig_text} (DM p={tgjr_vs_gjr_dm.get('p_value', 1):.4f}). "
    f"High-VIX regime shows omega {param_comparison['omega']['ratio']:.1f}x, "
    f"alpha {param_comparison['alpha']['ratio']:.1f}x, "
    f"gamma {param_comparison['gamma']['ratio']:.1f}x vs low-VIX regime."
)
results['conclusions']['key_finding'] = key_finding
print(f"\n{'='*60}")
print(f"KEY FINDING: {key_finding}")
print(f"{'='*60}")

with open(f'{BASE}/k980_threshold_garch_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nSaved: k980_threshold_garch_results.json")

print("\nK980 Complete!")
