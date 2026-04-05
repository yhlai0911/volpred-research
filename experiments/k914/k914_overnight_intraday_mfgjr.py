#!/usr/bin/env python3
"""
K914: Overnight-Intraday Decomposed MF-GJR
============================================
[提出: Claude autonomous research, 執行: Claude]

Motivation:
  K906 found SPY overnight volatility ~50% of total. Standard MF-GJR uses
  close-to-close returns, mixing overnight and intraday sources. This experiment
  tests whether decomposing the long-run component into overnight/intraday
  improves forecasts.

Models:
  A: Standard MF-GJR (baseline, same as K889v2)
     sigma^2 = tau_t * g_t, tau_t = exp(theta0 + theta1 * logVIX_{t-1})
  B: MF-GJR + Overnight Regressor
     tau_t = exp(theta0 + theta1 * logVIX_{t-1} + theta2 * r^2_overnight,t-1)
  C: Separate Overnight/Intraday MF-GJR
     sigma^2_total = sigma^2_overnight + sigma^2_intraday (independence assumed)
  D: MF-GJR + Overnight Ratio
     tau_t = exp(theta0 + theta1 * logVIX_{t-1} + theta2 * overnight_ratio_{t-1})

Data:
  - Asset: SPY (OHLC data required)
  - Period: 2005-01-01 to 2026-04-01
  - OOS: 2019-01-01 to latest
  - VIX from yfinance (^VIX)

Evaluation:
  - QLIKE on r^2 (Patton 2011 proxy-robust)
  - DM tests with Harvey (2016) |t| > 3.0
  - Spearman rank correlation
  - VaR 1% + 5% Trinity (Kupiec + Christoffersen + Basel)

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104
  - Hansen & Lunde (2005) J Econometrics 127(1-2):255-285

Author: VolPred Research System
Date: 2026-04-06
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.stats import norm, chi2

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K914"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k914_overnight_intraday_mfgjr_results.json')

# Data parameters (same as K889v2 for comparability)
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]

print("=" * 70)
print(f"{EXPERIMENT_ID}: Overnight-Intraday Decomposed MF-GJR")
print("  Testing whether overnight/intraday decomposition improves MF-GJR")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING WITH OHLC
# ============================================================
print("\n[1] Loading SPY OHLC + VIX data...")
import yfinance as yf

# Download SPY with OHLC
spy_raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)

# Download VIX
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

# Build DataFrame with OHLC
df = pd.DataFrame({
    'open': spy_raw['Open'],
    'high': spy_raw['High'],
    'low': spy_raw['Low'],
    'close': spy_raw['Close'],
    'VIX': vix_raw['Close'].reindex(spy_raw.index).ffill(),
})
df = df.dropna()

# Return decomposition
df['r_total'] = np.log(df['close'] / df['close'].shift(1))
df['r_overnight'] = np.log(df['open'] / df['close'].shift(1))
df['r_intraday'] = np.log(df['close'] / df['open'])

# Drop first row (NaN from shift)
df = df.dropna()

# Verify decomposition: r_total should approximately equal r_overnight + r_intraday
decomp_check = df['r_total'] - (df['r_overnight'] + df['r_intraday'])
print(f"  Decomposition check: max |r_total - (r_overnight + r_intraday)| = {decomp_check.abs().max():.2e}")
print(f"  Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={len(df)}")

# ============================================================
# SECTION 2: DECOMPOSITION ANALYSIS
# ============================================================
print("\n[2] Overnight vs Intraday Decomposition Analysis...")

r_total = df['r_total'].values
r_overnight = df['r_overnight'].values
r_intraday = df['r_intraday'].values
vix_vals = df['VIX'].values
log_vix = np.log(vix_vals)

# Basic statistics
decomp_stats = {}
for name, r in [('Total', r_total), ('Overnight', r_overnight), ('Intraday', r_intraday)]:
    decomp_stats[name] = {
        'mean': float(np.mean(r)),
        'std': float(np.std(r)),
        'var': float(np.var(r)),
        'skewness': float(stats.skew(r)),
        'kurtosis': float(stats.kurtosis(r)),
        'n': len(r),
    }
    print(f"  {name:10s}: Mean={np.mean(r):.6f} Std={np.std(r):.4f} "
          f"Var={np.var(r):.6f} Skew={stats.skew(r):.3f} Kurt={stats.kurtosis(r):.2f}")

# Variance ratios
total_var = np.var(r_total)
overnight_var = np.var(r_overnight)
intraday_var = np.var(r_intraday)
covar_on_intra = np.cov(r_overnight, r_intraday)[0, 1]
overnight_var_pct = overnight_var / total_var * 100
intraday_var_pct = intraday_var / total_var * 100
covar_pct = 2 * covar_on_intra / total_var * 100

print(f"\n  Variance decomposition:")
print(f"    Overnight var pct:  {overnight_var_pct:.1f}%")
print(f"    Intraday var pct:   {intraday_var_pct:.1f}%")
print(f"    2*Cov(ON,ID) pct:  {covar_pct:.1f}%")
print(f"    Sum check:          {overnight_var_pct + intraday_var_pct + covar_pct:.1f}%")

# Correlation between overnight and intraday
corr_on_id = np.corrcoef(r_overnight, r_intraday)[0, 1]
print(f"  Corr(overnight, intraday): {corr_on_id:.4f}")

# Correlation with VIX (lagged)
vix_lag = np.roll(log_vix, 1)
vix_lag[0] = log_vix[0]
r2_total = r_total ** 2
r2_overnight = r_overnight ** 2
r2_intraday = r_intraday ** 2

corr_vix_total = np.corrcoef(vix_lag, r2_total)[0, 1]
corr_vix_overnight = np.corrcoef(vix_lag, r2_overnight)[0, 1]
corr_vix_intraday = np.corrcoef(vix_lag, r2_intraday)[0, 1]

print(f"\n  Correlation of log(VIX_{{t-1}}) with r^2_t:")
print(f"    Total r^2:      {corr_vix_total:.4f}")
print(f"    Overnight r^2:  {corr_vix_overnight:.4f}")
print(f"    Intraday r^2:   {corr_vix_intraday:.4f}")

# Autocorrelation of r^2 components
def autocorr(x, lag=1):
    """Compute autocorrelation at given lag."""
    n = len(x)
    if n <= lag:
        return np.nan
    return np.corrcoef(x[:-lag], x[lag:])[0, 1]

print(f"\n  Autocorrelation of r^2:")
for name, r2 in [('Total', r2_total), ('Overnight', r2_overnight), ('Intraday', r2_intraday)]:
    ac1 = autocorr(r2, 1)
    ac5 = autocorr(r2, 5)
    ac22 = autocorr(r2, 22)
    print(f"    {name:10s}: AC(1)={ac1:.4f} AC(5)={ac5:.4f} AC(22)={ac22:.4f}")

# Granger causality (simple F-test with 5 lags)
print(f"\n  Granger causality (F-test, 5 lags):")
from numpy.linalg import lstsq as np_lstsq

def granger_test(y, x, max_lag=5):
    """Simple Granger causality test using F-test."""
    n = len(y) - max_lag
    if n < 50:
        return np.nan, np.nan

    # Restricted model: y_t on y_{t-1}...y_{t-lag}
    Y = y[max_lag:]
    X_r = np.column_stack([np.ones(n)] + [y[max_lag-i-1:len(y)-i-1] for i in range(max_lag)])
    b_r = np_lstsq(X_r, Y, rcond=None)[0]
    ssr_r = np.sum((Y - X_r @ b_r) ** 2)

    # Unrestricted: add x_{t-1}...x_{t-lag}
    X_u = np.column_stack([X_r] + [x[max_lag-i-1:len(x)-i-1] for i in range(max_lag)])
    b_u = np_lstsq(X_u, Y, rcond=None)[0]
    ssr_u = np.sum((Y - X_u @ b_u) ** 2)

    # F-test
    k_r = X_r.shape[1]
    k_u = X_u.shape[1]
    f_stat = ((ssr_r - ssr_u) / (k_u - k_r)) / (ssr_u / (n - k_u))
    p_val = 1 - stats.f.cdf(f_stat, k_u - k_r, n - k_u)
    return f_stat, p_val

f_on_to_id, p_on_to_id = granger_test(r2_intraday, r2_overnight)
f_id_to_on, p_id_to_on = granger_test(r2_overnight, r2_intraday)
print(f"    Overnight -> Intraday: F={f_on_to_id:.3f}, p={p_on_to_id:.4f}")
print(f"    Intraday -> Overnight: F={f_id_to_on:.3f}, p={p_id_to_on:.4f}")

# Overnight ratio time series
overnight_ratio = r2_overnight / (r2_overnight + r2_intraday + 1e-20)
print(f"\n  Overnight ratio (r^2_ON / (r^2_ON + r^2_ID)):")
print(f"    Mean: {np.mean(overnight_ratio):.4f}")
print(f"    Std:  {np.std(overnight_ratio):.4f}")
print(f"    AC(1): {autocorr(overnight_ratio, 1):.4f}")


# ============================================================
# SECTION 3: GENERATE DECOMPOSITION PLOT
# ============================================================
print("\n[3] Generating decomposition plots...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K914: SPY Overnight vs Intraday Volatility Decomposition', fontsize=14)

# Panel 1: Rolling 63-day variance ratio
roll_var_on = pd.Series(r2_overnight, index=df.index).rolling(63).mean()
roll_var_id = pd.Series(r2_intraday, index=df.index).rolling(63).mean()
roll_ratio = roll_var_on / (roll_var_on + roll_var_id)

ax = axes[0, 0]
ax.plot(df.index, roll_ratio, linewidth=0.8, color='tab:blue')
ax.axhline(0.5, color='red', linestyle='--', alpha=0.5)
ax.set_title('Overnight Variance Share (63-day rolling)')
ax.set_ylabel('Overnight / (Overnight + Intraday)')
ax.set_ylim(0, 1)

# Panel 2: VIX vs overnight/intraday r^2 scatter
ax = axes[0, 1]
ax.scatter(vix_lag[::10], r2_overnight[::10], alpha=0.3, s=5, label='Overnight r²', color='tab:orange')
ax.scatter(vix_lag[::10], r2_intraday[::10], alpha=0.3, s=5, label='Intraday r²', color='tab:green')
ax.set_xlabel('log(VIX_{t-1})')
ax.set_ylabel('r²_t')
ax.set_title('VIX vs Component r²')
ax.legend()
ax.set_ylim(0, np.percentile(r2_total, 99))

# Panel 3: Autocorrelation comparison
lags = range(1, 31)
ac_total = [autocorr(r2_total, l) for l in lags]
ac_overnight = [autocorr(r2_overnight, l) for l in lags]
ac_intraday = [autocorr(r2_intraday, l) for l in lags]

ax = axes[1, 0]
ax.bar(np.array(list(lags)) - 0.25, ac_total, width=0.25, label='Total', alpha=0.8)
ax.bar(np.array(list(lags)), ac_overnight, width=0.25, label='Overnight', alpha=0.8)
ax.bar(np.array(list(lags)) + 0.25, ac_intraday, width=0.25, label='Intraday', alpha=0.8)
ax.set_xlabel('Lag')
ax.set_ylabel('Autocorrelation of r²')
ax.set_title('Autocorrelation Structure')
ax.legend()

# Panel 4: Distribution of overnight ratio
ax = axes[1, 1]
ax.hist(overnight_ratio, bins=50, density=True, alpha=0.7, color='tab:purple')
ax.axvline(np.mean(overnight_ratio), color='red', linestyle='--', label=f'Mean={np.mean(overnight_ratio):.3f}')
ax.set_xlabel('Overnight Ratio')
ax.set_ylabel('Density')
ax.set_title('Distribution of Overnight Ratio')
ax.legend()

plt.tight_layout()
decomp_plot_path = os.path.join(SCRIPT_DIR, 'k914_decomposition.png')
plt.savefig(decomp_plot_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {decomp_plot_path}")


# ============================================================
# SECTION 4: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[4] Model implementations...")


def fit_gjr_garch(returns):
    """Fit GJR-GARCH(1,1) via MLE with multi-start."""
    from numba import njit

    @njit(cache=True)
    def gjr_loglik(params, rets):
        omega, alpha, gamma, beta = params
        n = len(rets)
        h = np.empty(n)
        h[0] = np.var(rets)
        ll = 0.0
        for t in range(1, n):
            asym = gamma * rets[t-1]**2 if rets[t-1] < 0 else 0.0
            h[t] = omega + alpha * rets[t-1]**2 + asym + beta * h[t-1]
            if h[t] < 1e-10:
                h[t] = 1e-10
        for t in range(n):
            if h[t] > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + rets[t]**2 / h[t])
        return -ll

    best_ll = np.inf
    best_params = None
    starts = [
        [1e-6, 0.05, 0.05, 0.90],
        [1e-6, 0.08, 0.10, 0.85],
        [1e-5, 0.03, 0.03, 0.93],
        [5e-6, 0.06, 0.08, 0.88],
    ]
    bounds = [(1e-8, 1e-3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                lambda p: gjr_loglik(p, returns), x0,
                method='L-BFGS-B', bounds=bounds, options={'maxiter': 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params, -best_ll


def gjr_garch_forecast_oos(params, r_prev, h_prev):
    """One-step GJR-GARCH forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    h_next = omega + alpha * r_prev**2 + asym + beta * h_prev
    return max(h_next, 1e-10)


def fit_mf_garch_extended(returns, log_vix, extra_regressors=None, model_type='gjr'):
    """Fit MF-GJR with optional extra regressors in the long-run component.

    Long-run: tau_t = exp(theta_0 + theta_1*logVIX_{t-1} + theta_2*X1_{t-1} + ...)
    Short-run: g_t = GJR on standardized returns u_t = r_t/sqrt(tau_t)

    Parameters:
    -----------
    returns : array
        Return series
    log_vix : array
        Log VIX values (NOT lagged - lagging is done internally)
    extra_regressors : list of arrays or None
        Additional regressors for the long-run component (NOT lagged - lagging done internally)
    model_type : str
        'garch' or 'gjr'

    Returns:
    --------
    params, loglik
    """
    n = len(returns)
    assert len(log_vix) == n

    n_extra = 0
    if extra_regressors is not None:
        n_extra = len(extra_regressors)
        for xr in extra_regressors:
            assert len(xr) == n

    # Lag VIX and extra regressors
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

    extra_lag = []
    if extra_regressors is not None:
        for xr in extra_regressors:
            xr_lag = np.roll(xr, 1)
            xr_lag[0] = xr[0]
            extra_lag.append(xr_lag)

    # Initial theta via OLS
    r2 = returns ** 2
    r2_positive = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_positive)
    X_ols = np.column_stack([np.ones(n), log_vix_lag] + extra_lag)
    theta_init = np.linalg.lstsq(X_ols, log_r2, rcond=None)[0]

    def neg_loglik(params):
        if model_type == 'gjr':
            # params: [theta_0, theta_1, ...theta_extra, alpha, gamma, beta]
            n_theta = 2 + n_extra
            thetas = params[:n_theta]
            alpha = params[n_theta]
            gamma = params[n_theta + 1]
            beta = params[n_theta + 2]
        else:
            n_theta = 2 + n_extra
            thetas = params[:n_theta]
            alpha = params[n_theta]
            beta = params[n_theta + 1]
            gamma = 0.0

        # Long-run component
        log_tau = thetas[0] + thetas[1] * log_vix_lag
        for i in range(n_extra):
            log_tau += thetas[2 + i] * extra_lag[i]
        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)

        # Standardized returns
        u = returns / np.sqrt(tau)

        # Short-run component
        omega_g = 1.0 - alpha - gamma / 2.0 - beta
        if omega_g <= 0 or alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10

        g = np.empty(n)
        g[0] = 1.0
        for t in range(1, n):
            asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
            g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        sigma2 = tau * g
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)

        if not np.isfinite(ll):
            return 1e10
        return -ll

    best_ll = np.inf
    best_params = None

    if model_type == 'gjr':
        # Params: [theta0, theta1, ...extra_thetas, alpha, gamma, beta]
        base_starts = [
            list(theta_init) + [0.05, 0.05, 0.90],
            [t * 0.8 for t in theta_init] + [0.08, 0.10, 0.85],
            [-8.0, 0.5] + [0.0] * n_extra + [0.05, 0.05, 0.90],
            [-7.0, 0.8] + [0.0] * n_extra + [0.03, 0.03, 0.93],
        ]
        bounds = ([(-20, 0), (-1, 3)] +
                  [(-5, 5)] * n_extra +
                  [(1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)])
    else:
        base_starts = [
            list(theta_init) + [0.05, 0.90],
            [t * 0.8 for t in theta_init] + [0.08, 0.85],
            [-8.0, 0.5] + [0.0] * n_extra + [0.05, 0.90],
            [-7.0, 0.8] + [0.0] * n_extra + [0.03, 0.93],
        ]
        bounds = ([(-20, 0), (-1, 3)] +
                  [(-5, 5)] * n_extra +
                  [(1e-4, 0.3), (0.5, 0.999)])

    for x0 in base_starts:
        try:
            res = optimize.minimize(
                neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 1000}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        return None, None

    return best_params, -best_ll


def forecast_mf_garch_extended(params, returns, log_vix, extra_regressors=None, model_type='gjr'):
    """Generate in-sample sigma^2, g, tau from MF-GARCH/GJR with extra regressors."""
    n = len(returns)
    n_extra = 0
    if extra_regressors is not None:
        n_extra = len(extra_regressors)

    if model_type == 'gjr':
        n_theta = 2 + n_extra
        thetas = params[:n_theta]
        alpha = params[n_theta]
        gamma = params[n_theta + 1]
        beta = params[n_theta + 2]
    else:
        n_theta = 2 + n_extra
        thetas = params[:n_theta]
        alpha = params[n_theta]
        beta = params[n_theta + 1]
        gamma = 0.0

    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    # Long-run component
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]
    log_tau = thetas[0] + thetas[1] * log_vix_lag
    if extra_regressors is not None:
        for i, xr in enumerate(extra_regressors):
            xr_lag = np.roll(xr, 1)
            xr_lag[0] = xr[0]
            log_tau += thetas[2 + i] * xr_lag
    tau = np.exp(log_tau)
    tau = np.maximum(tau, 1e-16)

    # Standardized returns and short-run
    u = returns / np.sqrt(tau)
    g = np.empty(n)
    g[0] = 1.0
    for t in range(1, n):
        asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
        g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    sigma2 = tau * g
    return sigma2, g, tau


# ============================================================
# SECTION 5: ROLLING OOS EVALUATION
# ============================================================
print("\n[5] Rolling OOS evaluation (SPY only)...")

ret = df['r_total'].values
r_on = df['r_overnight'].values
r_id = df['r_intraday'].values
log_vix_raw = np.log(df['VIX'].values)
r2 = ret ** 2
r2_on = r_on ** 2
r2_id = r_id ** 2
dates = df.index

# Overnight ratio
overnight_ratio_ts = r2_on / (r2_on + r2_id + 1e-20)

# Find OOS start index
oos_mask = dates >= OOS_START
oos_start_idx = np.argmax(oos_mask)
if oos_start_idx < WINDOW:
    oos_start_idx = WINDOW
print(f"  OOS starts at index {oos_start_idx}, date={dates[oos_start_idx]}")

n_oos = len(ret) - oos_start_idx
print(f"  OOS days: {n_oos}")

# Storage for forecasts
models = ['Model_A_MF-GJR', 'Model_B_+Overnight', 'Model_C_Separate', 'Model_D_+Ratio']
forecasts = {m: np.full(n_oos, np.nan) for m in models}
oos_returns = ret[oos_start_idx:]
oos_r2 = r2[oos_start_idx:]
oos_dates = dates[oos_start_idx:]

# State variables for each model
state = {m: {} for m in models}

n_refits = 0

for t in range(n_oos):
    idx = oos_start_idx + t
    need_refit = (t == 0) or (t % REFIT_EVERY == 0)

    # Training window
    train_start = max(0, idx - WINDOW)
    train_ret = ret[train_start:idx]
    train_vix = log_vix_raw[train_start:idx]
    train_r2_on = r2_on[train_start:idx]
    train_r_on = r_on[train_start:idx]
    train_r_id = r_id[train_start:idx]
    train_on_ratio = overnight_ratio_ts[train_start:idx]

    if need_refit:
        n_refits += 1
        if t % (REFIT_EVERY * 5) == 0:
            print(f"    Refit #{n_refits} at t={t}, date={dates[idx]}")

        # === Model A: Standard MF-GJR (baseline) ===
        params_a, ll_a = fit_mf_garch_extended(train_ret, train_vix, model_type='gjr')
        if params_a is not None:
            state['Model_A_MF-GJR']['params'] = params_a
            _, g_arr, tau_arr = forecast_mf_garch_extended(params_a, train_ret, train_vix, model_type='gjr')
            # Advance g one step (Bug Fix #3 from K889v2)
            theta0, theta1, alpha_a, gamma_a, beta_a = params_a
            last_tau = tau_arr[-1]
            u_last = train_ret[-1] / np.sqrt(last_tau)
            omega_g = 1.0 - alpha_a - gamma_a / 2.0 - beta_a
            asym = gamma_a * u_last**2 if u_last < 0 else 0.0
            state['Model_A_MF-GJR']['g'] = max(omega_g + alpha_a * u_last**2 + asym + beta_a * g_arr[-1], 1e-10)

        # === Model B: MF-GJR + Overnight Regressor ===
        params_b, ll_b = fit_mf_garch_extended(
            train_ret, train_vix,
            extra_regressors=[train_r2_on],
            model_type='gjr'
        )
        if params_b is not None:
            state['Model_B_+Overnight']['params'] = params_b
            _, g_arr, tau_arr = forecast_mf_garch_extended(
                params_b, train_ret, train_vix,
                extra_regressors=[train_r2_on],
                model_type='gjr'
            )
            # Advance g
            # params_b: [theta0, theta1, theta2, alpha, gamma, beta]
            n_theta_b = 3  # theta0, theta1, theta2
            alpha_b = params_b[n_theta_b]
            gamma_b = params_b[n_theta_b + 1]
            beta_b = params_b[n_theta_b + 2]
            last_tau = tau_arr[-1]
            u_last = train_ret[-1] / np.sqrt(last_tau)
            omega_g = 1.0 - alpha_b - gamma_b / 2.0 - beta_b
            asym = gamma_b * u_last**2 if u_last < 0 else 0.0
            state['Model_B_+Overnight']['g'] = max(omega_g + alpha_b * u_last**2 + asym + beta_b * g_arr[-1], 1e-10)

        # === Model C: Separate Overnight + Intraday MF-GJR ===
        # Fit separate model on overnight returns
        params_c_on, ll_c_on = fit_mf_garch_extended(train_r_on, train_vix, model_type='gjr')
        if params_c_on is not None:
            state['Model_C_Separate']['params_on'] = params_c_on
            _, g_arr_on, tau_arr_on = forecast_mf_garch_extended(params_c_on, train_r_on, train_vix, model_type='gjr')
            theta0c, theta1c, alpha_c, gamma_c, beta_c = params_c_on
            last_tau = tau_arr_on[-1]
            u_last = train_r_on[-1] / np.sqrt(last_tau)
            omega_g = 1.0 - alpha_c - gamma_c / 2.0 - beta_c
            asym = gamma_c * u_last**2 if u_last < 0 else 0.0
            state['Model_C_Separate']['g_on'] = max(omega_g + alpha_c * u_last**2 + asym + beta_c * g_arr_on[-1], 1e-10)

        # Fit separate model on intraday returns
        params_c_id, ll_c_id = fit_mf_garch_extended(train_r_id, train_vix, model_type='gjr')
        if params_c_id is not None:
            state['Model_C_Separate']['params_id'] = params_c_id
            _, g_arr_id, tau_arr_id = forecast_mf_garch_extended(params_c_id, train_r_id, train_vix, model_type='gjr')
            theta0c, theta1c, alpha_c, gamma_c, beta_c = params_c_id
            last_tau = tau_arr_id[-1]
            u_last = train_r_id[-1] / np.sqrt(last_tau)
            omega_g = 1.0 - alpha_c - gamma_c / 2.0 - beta_c
            asym = gamma_c * u_last**2 if u_last < 0 else 0.0
            state['Model_C_Separate']['g_id'] = max(omega_g + alpha_c * u_last**2 + asym + beta_c * g_arr_id[-1], 1e-10)

        # === Model D: MF-GJR + Overnight Ratio ===
        params_d, ll_d = fit_mf_garch_extended(
            train_ret, train_vix,
            extra_regressors=[train_on_ratio],
            model_type='gjr'
        )
        if params_d is not None:
            state['Model_D_+Ratio']['params'] = params_d
            _, g_arr, tau_arr = forecast_mf_garch_extended(
                params_d, train_ret, train_vix,
                extra_regressors=[train_on_ratio],
                model_type='gjr'
            )
            n_theta_d = 3
            alpha_d = params_d[n_theta_d]
            gamma_d = params_d[n_theta_d + 1]
            beta_d = params_d[n_theta_d + 2]
            last_tau = tau_arr[-1]
            u_last = train_ret[-1] / np.sqrt(last_tau)
            omega_g = 1.0 - alpha_d - gamma_d / 2.0 - beta_d
            asym = gamma_d * u_last**2 if u_last < 0 else 0.0
            state['Model_D_+Ratio']['g'] = max(omega_g + alpha_d * u_last**2 + asym + beta_d * g_arr[-1], 1e-10)

    # === Generate one-step-ahead forecasts ===

    # Model A: Standard MF-GJR
    if 'params' in state['Model_A_MF-GJR']:
        p = state['Model_A_MF-GJR']['params']
        theta0, theta1, alpha_a, gamma_a, beta_a = p

        # tau from VIX_{t-1}
        log_tau_t = theta0 + theta1 * log_vix_raw[idx - 1]
        tau_t = max(np.exp(log_tau_t), 1e-16)

        if need_refit:
            g_t = state['Model_A_MF-GJR']['g']
        else:
            u_prev = ret[idx - 1] / np.sqrt(state['Model_A_MF-GJR'].get('tau_prev', tau_t))
            omega_g = 1.0 - alpha_a - gamma_a / 2.0 - beta_a
            asym = gamma_a * u_prev**2 if u_prev < 0 else 0.0
            g_t = max(omega_g + alpha_a * u_prev**2 + asym + beta_a * state['Model_A_MF-GJR']['g'], 1e-10)

        state['Model_A_MF-GJR']['tau_prev'] = tau_t
        state['Model_A_MF-GJR']['g'] = g_t
        forecasts['Model_A_MF-GJR'][t] = tau_t * g_t

    # Model B: MF-GJR + Overnight Regressor
    if 'params' in state['Model_B_+Overnight']:
        p = state['Model_B_+Overnight']['params']
        theta0, theta1, theta2 = p[0], p[1], p[2]
        alpha_b, gamma_b, beta_b = p[3], p[4], p[5]

        # tau from VIX_{t-1} + r^2_overnight,{t-1}
        log_tau_t = theta0 + theta1 * log_vix_raw[idx - 1] + theta2 * r2_on[idx - 1]
        tau_t = max(np.exp(log_tau_t), 1e-16)

        if need_refit:
            g_t = state['Model_B_+Overnight']['g']
        else:
            u_prev = ret[idx - 1] / np.sqrt(state['Model_B_+Overnight'].get('tau_prev', tau_t))
            omega_g = 1.0 - alpha_b - gamma_b / 2.0 - beta_b
            asym = gamma_b * u_prev**2 if u_prev < 0 else 0.0
            g_t = max(omega_g + alpha_b * u_prev**2 + asym + beta_b * state['Model_B_+Overnight']['g'], 1e-10)

        state['Model_B_+Overnight']['tau_prev'] = tau_t
        state['Model_B_+Overnight']['g'] = g_t
        forecasts['Model_B_+Overnight'][t] = tau_t * g_t

    # Model C: Separate Overnight + Intraday
    if 'params_on' in state['Model_C_Separate'] and 'params_id' in state['Model_C_Separate']:
        # Overnight model
        p_on = state['Model_C_Separate']['params_on']
        theta0_on, theta1_on, alpha_on, gamma_on, beta_on = p_on

        log_tau_on = theta0_on + theta1_on * log_vix_raw[idx - 1]
        tau_on = max(np.exp(log_tau_on), 1e-16)

        if need_refit:
            g_on = state['Model_C_Separate']['g_on']
        else:
            u_prev_on = r_on[idx - 1] / np.sqrt(state['Model_C_Separate'].get('tau_prev_on', tau_on))
            omega_g = 1.0 - alpha_on - gamma_on / 2.0 - beta_on
            asym = gamma_on * u_prev_on**2 if u_prev_on < 0 else 0.0
            g_on = max(omega_g + alpha_on * u_prev_on**2 + asym + beta_on * state['Model_C_Separate']['g_on'], 1e-10)

        state['Model_C_Separate']['tau_prev_on'] = tau_on
        state['Model_C_Separate']['g_on'] = g_on
        sigma2_on = tau_on * g_on

        # Intraday model
        p_id = state['Model_C_Separate']['params_id']
        theta0_id, theta1_id, alpha_id, gamma_id, beta_id = p_id

        log_tau_id = theta0_id + theta1_id * log_vix_raw[idx - 1]
        tau_id = max(np.exp(log_tau_id), 1e-16)

        if need_refit:
            g_id = state['Model_C_Separate']['g_id']
        else:
            u_prev_id = r_id[idx - 1] / np.sqrt(state['Model_C_Separate'].get('tau_prev_id', tau_id))
            omega_g = 1.0 - alpha_id - gamma_id / 2.0 - beta_id
            asym = gamma_id * u_prev_id**2 if u_prev_id < 0 else 0.0
            g_id = max(omega_g + alpha_id * u_prev_id**2 + asym + beta_id * state['Model_C_Separate']['g_id'], 1e-10)

        state['Model_C_Separate']['tau_prev_id'] = tau_id
        state['Model_C_Separate']['g_id'] = g_id
        sigma2_id = tau_id * g_id

        # Total variance: sum (independence assumption)
        forecasts['Model_C_Separate'][t] = sigma2_on + sigma2_id

    # Model D: MF-GJR + Overnight Ratio
    if 'params' in state['Model_D_+Ratio']:
        p = state['Model_D_+Ratio']['params']
        theta0, theta1, theta2 = p[0], p[1], p[2]
        alpha_d, gamma_d, beta_d = p[3], p[4], p[5]

        # tau from VIX_{t-1} + overnight_ratio_{t-1}
        log_tau_t = theta0 + theta1 * log_vix_raw[idx - 1] + theta2 * overnight_ratio_ts[idx - 1]
        tau_t = max(np.exp(log_tau_t), 1e-16)

        if need_refit:
            g_t = state['Model_D_+Ratio']['g']
        else:
            u_prev = ret[idx - 1] / np.sqrt(state['Model_D_+Ratio'].get('tau_prev', tau_t))
            omega_g = 1.0 - alpha_d - gamma_d / 2.0 - beta_d
            asym = gamma_d * u_prev**2 if u_prev < 0 else 0.0
            g_t = max(omega_g + alpha_d * u_prev**2 + asym + beta_d * state['Model_D_+Ratio']['g'], 1e-10)

        state['Model_D_+Ratio']['tau_prev'] = tau_t
        state['Model_D_+Ratio']['g'] = g_t
        forecasts['Model_D_+Ratio'][t] = tau_t * g_t

print(f"  Refits: {n_refits}")


# ============================================================
# SECTION 6: EVALUATION
# ============================================================
print("\n[6] Evaluation...")

# 6a: QLIKE on r^2
qlike_results = {}
for m in models:
    f = forecasts[m]
    valid = np.isfinite(f) & (f > 0)
    if valid.sum() > 100:
        qlike_results[m] = qlike(oos_r2[valid], f[valid])
    else:
        qlike_results[m] = np.nan

# Normalize to Model A baseline
baseline_qlike = qlike_results['Model_A_MF-GJR']
qlike_pct = {}
for m in models:
    if np.isfinite(qlike_results[m]) and np.isfinite(baseline_qlike) and baseline_qlike > 0:
        qlike_pct[m] = ((qlike_results[m] - baseline_qlike) / baseline_qlike) * 100
    else:
        qlike_pct[m] = np.nan

print(f"\n  QLIKE on r^2 (Patton 2011) — lower is better:")
for m in models:
    pct = qlike_pct.get(m, np.nan)
    print(f"    {m:25s}: {qlike_results[m]:.6f} ({pct:+.3f}% vs Model A)")

# 6b: Spearman rank correlation
spearman_results = {}
for m in models:
    f = forecasts[m]
    valid = np.isfinite(f) & (f > 0)
    if valid.sum() > 100:
        rho, p = spearman_corr(oos_r2[valid], f[valid])
        spearman_results[m] = {'rho': rho, 'p': p}
    else:
        spearman_results[m] = {'rho': np.nan, 'p': np.nan}

print(f"\n  Spearman rank correlation:")
for m in models:
    r = spearman_results[m]
    print(f"    {m:25s}: rho={r['rho']:.4f} (p={r['p']:.2e})")

# 6c: DM tests vs Model A
baseline_loss = qlike_pointwise(oos_r2, forecasts['Model_A_MF-GJR'])
dm_results = {}
for m in models:
    if m == 'Model_A_MF-GJR':
        dm_results[m] = {'t': 0.0, 'p': 1.0}
        continue
    f = forecasts[m]
    valid = np.isfinite(f) & (f > 0) & np.isfinite(baseline_loss)
    if valid.sum() > 100:
        m_loss = qlike_pointwise(oos_r2[valid], f[valid])
        t_stat, p_val = dm_test(m_loss, baseline_loss[valid])
        dm_results[m] = {'t': float(t_stat), 'p': float(p_val)}
    else:
        dm_results[m] = {'t': np.nan, 'p': np.nan}

print(f"\n  DM tests vs Model A (negative t = model is better than A):")
for m in models:
    r = dm_results[m]
    sig = "***HARVEY" if abs(r['t']) > 3.0 else ("*" if abs(r['t']) > 1.96 else "NS")
    print(f"    {m:25s}: t={r['t']:+.3f} (p={r['p']:.4f}) {sig}")

# 6d: VaR Trinity test
var_results = {}
for alpha in ALPHA_LEVELS:
    var_results[alpha] = {}
    z = norm.ppf(alpha)

    for m in models:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() < 100:
            var_results[alpha][m] = {'violations': np.nan, 'rate': np.nan,
                                     'kupiec_p': np.nan, 'cc_p': np.nan,
                                     'basel': 'N/A', 'trinity': False}
            continue

        sigma = np.sqrt(f[valid])
        var_threshold = z * sigma
        actual_ret = oos_returns[valid]

        violations = actual_ret < var_threshold
        n_viol = int(np.sum(violations))
        n_total = int(len(actual_ret))
        viol_rate = n_viol / n_total

        # Kupiec test
        p_hat = viol_rate
        if 0 < p_hat < 1:
            kupiec_lr = 2 * (n_viol * np.log(p_hat / alpha) +
                             (n_total - n_viol) * np.log((1 - p_hat) / (1 - alpha)))
            kupiec_p = 1 - chi2.cdf(kupiec_lr, 1) if kupiec_lr > 0 else 1.0
        else:
            kupiec_p = 0.0 if p_hat == 0 and alpha > 0 else 1.0

        # Christoffersen CC
        n00 = n01 = n10 = n11 = 0
        for i in range(1, n_total):
            if not violations[i-1]:
                if not violations[i]:
                    n00 += 1
                else:
                    n01 += 1
            else:
                if not violations[i]:
                    n10 += 1
                else:
                    n11 += 1

        if (n00 + n01) > 0 and (n10 + n11) > 0:
            p01 = n01 / (n00 + n01)
            p11 = n11 / (n10 + n11)
            p_pool = (n01 + n11) / n_total

            if 0 < p_pool < 1 and 0 < p01 < 1 and 0 < p11 < 1:
                lr_ind = 2 * (
                    n00 * np.log(1 - p01) + n01 * np.log(p01) +
                    n10 * np.log(1 - p11) + n11 * np.log(p11) -
                    (n00 + n10) * np.log(1 - p_pool) -
                    (n01 + n11) * np.log(p_pool)
                )
                cc_p = 1 - chi2.cdf(max(0, lr_ind + max(0, kupiec_lr if kupiec_lr > 0 else 0)), 2)
            else:
                cc_p = 1.0
        else:
            cc_p = 1.0

        # Basel traffic light
        if alpha == 0.01:
            if n_viol <= 4:
                basel = "GREEN"
            elif n_viol <= 9:
                basel = "YELLOW"
            else:
                basel = "RED"
        else:
            expected = int(n_total * 0.05)
            if n_viol <= expected + 4:
                basel = "GREEN"
            elif n_viol <= expected + 9:
                basel = "YELLOW"
            else:
                basel = "RED"

        trinity_pass = (kupiec_p > 0.05) and (cc_p > 0.05) and (basel == "GREEN")

        var_results[alpha][m] = {
            'violations': n_viol,
            'total': n_total,
            'rate': round(viol_rate, 4),
            'expected_rate': alpha,
            'kupiec_p': round(kupiec_p, 4),
            'cc_p': round(cc_p, 4),
            'basel': basel,
            'trinity': trinity_pass,
        }

for alpha in ALPHA_LEVELS:
    print(f"\n  VaR {int(alpha*100)}% Trinity:")
    for m in models:
        r = var_results[alpha][m]
        print(f"    {m:25s}: {r['violations']}/{r.get('total','?')} "
              f"({r['rate']:.3f}) Kupiec p={r['kupiec_p']:.3f} "
              f"CC p={r['cc_p']:.3f} Basel={r['basel']} "
              f"Trinity={'PASS' if r['trinity'] else 'FAIL'}")


# ============================================================
# SECTION 7: PARAMETER ANALYSIS
# ============================================================
print("\n[7] Parameter analysis...")

param_report = {}

# Model A
if 'params' in state['Model_A_MF-GJR']:
    p = state['Model_A_MF-GJR']['params']
    param_report['Model_A'] = {
        'theta_0': float(p[0]), 'theta_1': float(p[1]),
        'alpha': float(p[2]), 'gamma': float(p[3]), 'beta': float(p[4]),
        'persistence_g': float(p[2] + p[3]/2 + p[4]),
    }
    print(f"  Model A (MF-GJR): theta0={p[0]:.4f} theta1={p[1]:.4f} "
          f"alpha={p[2]:.4f} gamma={p[3]:.4f} beta={p[4]:.4f}")

# Model B
if 'params' in state['Model_B_+Overnight']:
    p = state['Model_B_+Overnight']['params']
    param_report['Model_B'] = {
        'theta_0': float(p[0]), 'theta_1': float(p[1]), 'theta_2_overnight': float(p[2]),
        'alpha': float(p[3]), 'gamma': float(p[4]), 'beta': float(p[5]),
        'persistence_g': float(p[3] + p[4]/2 + p[5]),
    }
    print(f"  Model B (+Overnight): theta0={p[0]:.4f} theta1={p[1]:.4f} "
          f"theta2_ON={p[2]:.4f} alpha={p[3]:.4f} gamma={p[4]:.4f} beta={p[5]:.4f}")

# Model C
if 'params_on' in state['Model_C_Separate']:
    p_on = state['Model_C_Separate']['params_on']
    param_report['Model_C_overnight'] = {
        'theta_0': float(p_on[0]), 'theta_1': float(p_on[1]),
        'alpha': float(p_on[2]), 'gamma': float(p_on[3]), 'beta': float(p_on[4]),
        'persistence_g': float(p_on[2] + p_on[3]/2 + p_on[4]),
    }
    print(f"  Model C (ON): theta0={p_on[0]:.4f} theta1={p_on[1]:.4f} "
          f"alpha={p_on[2]:.4f} gamma={p_on[3]:.4f} beta={p_on[4]:.4f}")
if 'params_id' in state['Model_C_Separate']:
    p_id = state['Model_C_Separate']['params_id']
    param_report['Model_C_intraday'] = {
        'theta_0': float(p_id[0]), 'theta_1': float(p_id[1]),
        'alpha': float(p_id[2]), 'gamma': float(p_id[3]), 'beta': float(p_id[4]),
        'persistence_g': float(p_id[2] + p_id[3]/2 + p_id[4]),
    }
    print(f"  Model C (ID): theta0={p_id[0]:.4f} theta1={p_id[1]:.4f} "
          f"alpha={p_id[2]:.4f} gamma={p_id[3]:.4f} beta={p_id[4]:.4f}")

# Model D
if 'params' in state['Model_D_+Ratio']:
    p = state['Model_D_+Ratio']['params']
    param_report['Model_D'] = {
        'theta_0': float(p[0]), 'theta_1': float(p[1]), 'theta_2_ratio': float(p[2]),
        'alpha': float(p[3]), 'gamma': float(p[4]), 'beta': float(p[5]),
        'persistence_g': float(p[3] + p[4]/2 + p[5]),
    }
    print(f"  Model D (+Ratio): theta0={p[0]:.4f} theta1={p[1]:.4f} "
          f"theta2_ratio={p[2]:.4f} alpha={p[3]:.4f} gamma={p[4]:.4f} beta={p[5]:.4f}")


# ============================================================
# SECTION 8: MODEL COMPARISON PLOT
# ============================================================
print("\n[8] Generating model comparison plot...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K914: Overnight-Intraday Decomposed MF-GJR — Model Comparison', fontsize=14)

# Panel 1: QLIKE bar chart
ax = axes[0, 0]
model_names = [m.replace('Model_', '').replace('_', '\n') for m in models]
qlike_vals = [qlike_results[m] for m in models]
colors = ['tab:blue', 'tab:orange', 'tab:green', 'tab:red']
bars = ax.bar(model_names, qlike_vals, color=colors, alpha=0.8)
ax.set_ylabel('QLIKE')
ax.set_title('QLIKE on r² (lower is better)')
# Mark best
best_idx = np.argmin(qlike_vals)
bars[best_idx].set_edgecolor('black')
bars[best_idx].set_linewidth(2)

# Panel 2: DM t-statistics
ax = axes[0, 1]
dm_t_vals = [dm_results[m]['t'] for m in models]
bars = ax.bar(model_names, dm_t_vals, color=colors, alpha=0.8)
ax.axhline(-3.0, color='red', linestyle='--', alpha=0.5, label='Harvey |t|=3.0')
ax.axhline(3.0, color='red', linestyle='--', alpha=0.5)
ax.axhline(0, color='black', linewidth=0.5)
ax.set_ylabel('DM t-statistic vs Model A')
ax.set_title('DM Test (negative = better than A)')
ax.legend()

# Panel 3: Spearman correlation
ax = axes[1, 0]
rho_vals = [spearman_results[m]['rho'] for m in models]
bars = ax.bar(model_names, rho_vals, color=colors, alpha=0.8)
ax.set_ylabel('Spearman rho')
ax.set_title('Spearman Rank Correlation with r²')

# Panel 4: VaR 1% violation rates
ax = axes[1, 1]
viol_rates = [var_results[0.01][m]['rate'] if not np.isnan(var_results[0.01][m].get('rate', np.nan)) else 0 for m in models]
bars = ax.bar(model_names, viol_rates, color=colors, alpha=0.8)
ax.axhline(0.01, color='red', linestyle='--', label='Expected 1%')
ax.set_ylabel('VaR 1% Violation Rate')
ax.set_title('VaR 1% Backtesting')
ax.legend()

plt.tight_layout()
comparison_plot_path = os.path.join(SCRIPT_DIR, 'k914_model_comparison.png')
plt.savefig(comparison_plot_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {comparison_plot_path}")


# ============================================================
# SECTION 9: CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)

# Find best model
best_model = min(models, key=lambda m: qlike_results[m] if np.isfinite(qlike_results[m]) else float('inf'))
print(f"\n  Best model by QLIKE: {best_model} ({qlike_results[best_model]:.6f})")

# Check significance
any_significant = False
significant_list = []
for m in models:
    if m == 'Model_A_MF-GJR':
        continue
    dm = dm_results[m]
    if abs(dm['t']) > 3.0 and dm['t'] < 0:
        any_significant = True
        significant_list.append(f"{m} (DM t={dm['t']:.3f})")
        print(f"  SIGNIFICANT: {m} beats Model A (DM t={dm['t']:.3f})")

if not any_significant:
    print("  No decomposed model significantly beats standard MF-GJR (Harvey |t|>3.0)")
    print("  => NULL RESULT: Overnight-intraday decomposition does NOT improve MF-GJR")
    print("  => VIX elasticity in standard MF-GJR already implicitly captures this structure")

# Key findings summary
print(f"\n  Key findings:")
print(f"    Overnight variance share: {overnight_var_pct:.1f}%")
print(f"    Corr(VIX, r^2_overnight): {corr_vix_overnight:.4f}")
print(f"    Corr(VIX, r^2_intraday): {corr_vix_intraday:.4f}")
print(f"    Corr(overnight, intraday): {corr_on_id:.4f}")
print(f"    QLIKE improvement best model: {qlike_pct[best_model]:+.3f}% vs Model A")
if significant_list:
    print(f"    Significant improvements: {', '.join(significant_list)}")


# ============================================================
# SECTION 10: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME
print(f"\n  Runtime: {elapsed:.1f}s")

# Build key findings text
key_findings_parts = []
key_findings_parts.append(
    f"SPY overnight variance share = {overnight_var_pct:.1f}% of total "
    f"(intraday {intraday_var_pct:.1f}%, 2*cov {covar_pct:.1f}%). "
)
key_findings_parts.append(
    f"VIX correlates with overnight r² ({corr_vix_overnight:.3f}) "
    f"{'more' if abs(corr_vix_overnight) > abs(corr_vix_intraday) else 'less'} "
    f"than intraday r² ({corr_vix_intraday:.3f}). "
)
if any_significant:
    key_findings_parts.append(
        f"Decomposed model(s) significantly beat standard MF-GJR: "
        f"{', '.join(significant_list)}. "
    )
else:
    key_findings_parts.append(
        "No decomposed model significantly beats standard MF-GJR "
        "(Harvey |t| > 3.0 threshold). NULL RESULT: overnight-intraday "
        "decomposition does NOT improve MF-GJR forecasts. "
        "The VIX elasticity in tau already implicitly captures "
        "overnight/intraday volatility structure. "
    )
key_findings_parts.append(
    f"Best model QLIKE improvement: {qlike_pct[best_model]:+.3f}% vs Model A. "
)

key_findings = ''.join(key_findings_parts)

final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Overnight-Intraday Decomposed MF-GJR (K914)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'methodology': {
        'models': {
            'Model_A': 'MF-GJR baseline: tau = exp(theta0 + theta1*logVIX_{t-1})',
            'Model_B': 'MF-GJR + overnight: tau = exp(theta0 + theta1*logVIX_{t-1} + theta2*r^2_overnight,{t-1})',
            'Model_C': 'Separate MF-GJR on overnight + intraday returns, sigma^2 = sigma^2_ON + sigma^2_ID',
            'Model_D': 'MF-GJR + ratio: tau = exp(theta0 + theta1*logVIX_{t-1} + theta2*overnight_ratio_{t-1})',
        },
        'estimation': f'Rolling window (w={WINDOW}), refit every {REFIT_EVERY} days, MLE with multi-start',
        'evaluation': 'QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), Spearman, VaR Trinity',
    },
    'data': {
        'source': 'yfinance',
        'asset': 'SPY',
        'period': f'{DATA_START} to {DATA_END}',
        'oos_start': OOS_START,
        'oos_end': str(oos_dates[-1].date()),
        'n_oos': int(n_oos),
        'n_refits': n_refits,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
    },
    'decomposition_analysis': {
        'overnight_var_pct': round(overnight_var_pct, 2),
        'intraday_var_pct': round(intraday_var_pct, 2),
        'covariance_pct': round(covar_pct, 2),
        'corr_overnight_intraday': round(corr_on_id, 4),
        'corr_vix_r2_total': round(corr_vix_total, 4),
        'corr_vix_r2_overnight': round(corr_vix_overnight, 4),
        'corr_vix_r2_intraday': round(corr_vix_intraday, 4),
        'granger_overnight_to_intraday': {'F': round(f_on_to_id, 3), 'p': round(p_on_to_id, 4)},
        'granger_intraday_to_overnight': {'F': round(f_id_to_on, 3), 'p': round(p_id_to_on, 4)},
        'overnight_ratio_mean': round(float(np.mean(overnight_ratio)), 4),
        'overnight_ratio_std': round(float(np.std(overnight_ratio)), 4),
        'descriptive_stats': {k: {kk: round(vv, 6) if isinstance(vv, float) else vv
                                   for kk, vv in v.items()}
                              for k, v in decomp_stats.items()},
    },
    'results': {
        'qlike': {m: round(v, 6) if np.isfinite(v) else None for m, v in qlike_results.items()},
        'qlike_pct_vs_model_a': {m: round(v, 3) if np.isfinite(v) else None for m, v in qlike_pct.items()},
        'spearman': {m: {'rho': round(v['rho'], 4) if np.isfinite(v['rho']) else None,
                         'p': round(v['p'], 6) if np.isfinite(v['p']) else None}
                     for m, v in spearman_results.items()},
        'dm_vs_model_a': {m: {'t': round(v['t'], 3) if np.isfinite(v['t']) else None,
                               'p': round(v['p'], 4) if np.isfinite(v['p']) else None,
                               'significant_harvey': abs(v['t']) > 3.0 if np.isfinite(v['t']) else False}
                          for m, v in dm_results.items()},
        'var': {str(a): {m: v for m, v in var_results[a].items()} for a in ALPHA_LEVELS},
    },
    'parameters': param_report,
    'conclusion': {
        'any_significant_vs_model_a': any_significant,
        'significant_models': significant_list,
        'best_model': best_model,
        'null_result': not any_significant,
        'interpretation': key_findings,
    },
    'references': [
        'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey et al. (2016) JBES 34:92-104',
        'Hansen & Lunde (2005) J Econometrics 127(1-2):255-285',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)
print(f"\n  Results saved to: {RESULTS_PATH}")

print(f"\n{'='*70}")
print(f"K914 COMPLETE — Runtime: {elapsed:.1f}s")
print(f"{'='*70}")
