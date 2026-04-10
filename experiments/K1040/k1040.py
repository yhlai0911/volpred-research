#!/usr/bin/env python3
"""
K1040: VRP Return Predictability via A4f g_t
=============================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  K1023 found g_t (from A4f decomposition) correlates with VRP (Spearman rho~0.80).
  Bollerslev, Tauchen & Zhou (2009, RFS) showed VRP predicts equity returns (R^2~5-8% monthly).
  K998 showed g_t cannot predict FUTURE VRP, but can it predict FUTURE RETURNS?
  K818 used SSVS for return prediction -> SPY OOS R^2 = -1.47% (NULL).

  This experiment tests whether g_t (A4f's VRP proxy) can predict SPY excess returns
  at daily (h=1), weekly (h=5), and monthly (h=22) horizons using OOS predictive regressions.

Design:
  Predictive regressions: r_{t->t+h} = a + b1*g_t + b2*VRP_t + b3*VIX_t + epsilon_{t+h}
  Six models:
    1. Historical mean (benchmark)
    2. VRP-only
    3. g_t-only
    4. VIX-only
    5. g_t + VRP
    6. Kitchen sink (g_t + VRP + VIX)

  g_t construction: A4f model with tau_t = theta0 + theta1 * VIX_{t-1}^2
  VRP construction: VIX_t^2/252 - RV_22d (rolling 22-day realized variance)

  OOS: expanding window, train on [0:T], predict T+1...T+h.
  Window: 2000, refit_every: 63.
  h > 1: overlapping returns + Newey-West HAC (lag h-1).

  OPTIMIZATION: A4f recursion runs once per refit window over the entire training
  set to produce g_t for all training days + current OOS day. Between refits,
  the recursion extends incrementally.

Evaluation:
  - OOS R^2 = 1 - MSE(model)/MSE(hist_mean). > 0 = predictive power.
  - Diebold-Mariano test on squared errors vs hist mean.
  - Direction accuracy = P(sign(y_hat) = sign(y)). > 50% = direction forecast.
  - Clark-West (2007) adjusted MSPE for nested models.
  - Long-short economic value based on g_t signal.

Data: SPY 2005-01-01 to 2026-04-10, VIX from yfinance.
OOS: 2019-01-01 onwards.
Seed: 42.

References:
  - Bollerslev, Tauchen & Zhou (2009). Expected Stock Returns and VRP. RFS 22(11).
  - Campbell & Thompson (2008). Predicting Excess Stock Returns OOS. RFS 21(4).
  - Clark & West (2007). Approximately Normal Tests for Nested Models. JoE 138(1).
  - Newey & West (1987). Simple, Positive Semi-definite HAC Estimator. Econometrica.
  - K1023: g_t vs VRP Spearman rho ~ 0.80
  - K998: g_t cannot predict future VRP
  - K818: SSVS return prediction NULL

Author: VolPred Research System
Date: 2026-04-11
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.special import gammaln
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1040"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1040_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-10'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
DF_FIXED = 8
HORIZONS = [1, 5, 22]
RV_WINDOW = 22

print("=" * 70)
print(f"{EXPERIMENT_ID}: VRP Return Predictability via A4f g_t")
print(f"  Horizons: {HORIZONS} | OOS from {OOS_START}")
print(f"  Window: {WINDOW}, refit_every: {REFIT_EVERY}")
print("=" * 70)


# ============================================================
# SECTION 1: A4f MODEL FUNCTIONS
# ============================================================

def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, fear2):
    """A4f multiplicative GARCH-X recursion (vectorized loop)."""
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)

    tau[0] = max(theta0 + theta1 * fear2[0], 1e-16)
    g[0] = 1.0
    h[0] = tau[0]

    for t in range(1, T):
        tau[t] = max(theta0 + theta1 * fear2[t-1], 1e-16)
        u2 = (returns[t-1] / np.sqrt(tau[t])) ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        g[t] = max(omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1], 1e-16)
        h[t] = max(tau[t] * g[t], 1e-16)

    return h, tau, g


def student_t_const(df):
    return float(gammaln((df + 1) / 2) - gammaln(df / 2) - 0.5 * np.log(np.pi * (df - 2)))


T_CONST_8 = student_t_const(DF_FIXED)


def a4f_nll_t(params, returns, fear2, df, t_const):
    theta0, theta1, omega, alpha_p, gamma_p, beta_p = params
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha_p, gamma_p, beta_p, returns, fear2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += t_const - 0.5 * np.log(h[t]) - (df + 1) / 2 * np.log(1 + returns[t]**2 / (h[t] * (df - 2)))
    return -ll


def fit_a4f_t(returns, vix_vals, df=DF_FIXED):
    """Fit A4f model. vix_vals = VIX values (not squared yet)."""
    var0 = np.var(returns)
    fear2 = vix_vals ** 2
    fear2_mean = np.mean(fear2) + 1e-8
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.1, var0 / fear2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / fear2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / fear2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / fear2_mean * 2.0, 0.08, 0.04, 0.04, 0.92],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3),
              (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    for s in starts:
        try:
            res = optimize.minimize(
                a4f_nll_t, s, args=(returns, fear2, float(df), T_CONST_8),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 300, 'ftol': 1e-9}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


# ============================================================
# SECTION 2: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close})
df = df.dropna()

n_total = len(df)
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

# ============================================================
# SECTION 3: CONSTRUCT PREDICTORS
# ============================================================
print("\n[2] Constructing predictors...")

df['r2'] = df['log_ret'] ** 2
df['RV_22d'] = df['r2'].rolling(RV_WINDOW).sum()
df['IV_monthly'] = (df['VIX'] / 100) ** 2 * (22 / 252)
df['VRP'] = df['IV_monthly'] - df['RV_22d']
df['VIX_level'] = df['VIX'] / 100

for h_val in HORIZONS:
    df[f'fwd_ret_{h_val}d'] = df['log_ret'].rolling(h_val).sum().shift(-h_val)

df_clean = df.dropna(subset=['RV_22d', 'VRP'] + [f'fwd_ret_{h_val}d' for h_val in HORIZONS]).copy()
print(f"  Clean sample: {df_clean.index[0].strftime('%Y-%m-%d')} to {df_clean.index[-1].strftime('%Y-%m-%d')}, n={len(df_clean)}")
print(f"  Mean VRP: {df_clean['VRP'].mean():.6e}")

# ============================================================
# SECTION 4: PRE-COMPUTE g_t FOR ALL OBSERVATIONS
# ============================================================
print("\n[3] Pre-computing g_t with rolling A4f estimation...")

all_ret = df_clean['log_ret'].values
all_vix = df_clean['VIX'].values
all_vrp = df_clean['VRP'].values
all_vix_level = df_clean['VIX_level'].values
all_dates = df_clean.index.values
n_clean = len(df_clean)

oos_mask = df_clean.index >= OOS_START
oos_start_idx = np.where(oos_mask)[0][0]
n_oos = oos_mask.sum()
print(f"  OOS start: {df_clean.index[oos_start_idx].strftime('%Y-%m-%d')}, n_oos={n_oos}")

# Pre-compute g_t for all OOS observations using rolling A4f fits
# Strategy: fit A4f at refit points, run recursion over full window to get g_t
g_t_all = np.full(n_clean, np.nan)
last_fit_idx = -REFIT_EVERY
last_params = None
n_refits = 0

# We need g_t for the entire training period too (for in-sample regressions)
# Fit starting from the earliest possible point
min_train = max(500, oos_start_idx - WINDOW)

for t in range(min_train, n_clean):
    need_refit = (t - last_fit_idx >= REFIT_EVERY) or (last_params is None)

    if need_refit:
        train_start = max(0, t - WINDOW)
        train_end = t + 1  # include current day
        train_ret = all_ret[train_start:train_end]
        train_vix = all_vix[train_start:train_end]

        params = fit_a4f_t(train_ret, train_vix)
        if params is not None:
            last_params = params
            last_fit_idx = t
            n_refits += 1

            # Run recursion over the full window
            fear2 = train_vix ** 2
            _, _, g_series = a4f_recursion(*params, train_ret, fear2)
            # Store g_t values for all days in this window
            for j in range(len(g_series)):
                idx = train_start + j
                g_t_all[idx] = g_series[j]

            if n_refits % 10 == 0:
                print(f"    Refit #{n_refits} at t={t} ({df_clean.index[t].strftime('%Y-%m-%d')}), "
                      f"g_t={g_series[-1]:.4f}")
    elif last_params is not None:
        # Between refits: extend g_t by one step using last g value
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = last_params
        tau_t = max(theta0 + theta1 * all_vix[t-1]**2, 1e-16)
        u_prev = all_ret[t-1] / np.sqrt(tau_t)
        u2 = u_prev ** 2
        ind = 1.0 if all_ret[t-1] < 0 else 0.0
        g_prev = g_t_all[t-1] if np.isfinite(g_t_all[t-1]) else 1.0
        g_t_all[t] = max(omega_g + alpha_p * u2 + gamma_p * u2 * ind + beta_p * g_prev, 1e-16)

print(f"  Total refits: {n_refits}")
print(f"  g_t coverage: {np.sum(np.isfinite(g_t_all))}/{n_clean}")

elapsed_step3 = time.time() - START_TIME
print(f"  Step 3 time: {elapsed_step3:.1f}s")


# ============================================================
# SECTION 5: NEWEY-WEST AND OLS HELPERS
# ============================================================

def newey_west_se(residuals, X, lag):
    """Newey-West HAC standard errors."""
    n, k = X.shape
    e = residuals.reshape(-1, 1)
    Xe = X * e
    S = Xe.T @ Xe / n
    for j in range(1, lag + 1):
        w = 1 - j / (lag + 1)
        Gamma_j = Xe[j:].T @ Xe[:-j] / n
        S = S + w * (Gamma_j + Gamma_j.T)
    XtX_inv = np.linalg.inv(X.T @ X / n)
    V = XtX_inv @ S @ XtX_inv / n
    return np.sqrt(np.diag(V))


# ============================================================
# SECTION 6: OOS PREDICTIVE REGRESSIONS (BATCH APPROACH)
# ============================================================
print("\n[4] Running OOS predictive regressions...")

results_by_horizon = {}

for h in HORIZONS:
    print(f"\n  --- Horizon h={h} ---")
    fwd_key = f'fwd_ret_{h}d'
    all_fwd = df_clean[fwd_key].values

    # Arrays for OOS predictions
    preds = {
        'hist_mean': np.full(n_oos, np.nan),
        'vrp_only': np.full(n_oos, np.nan),
        'gt_only': np.full(n_oos, np.nan),
        'vix_only': np.full(n_oos, np.nan),
        'gt_vrp': np.full(n_oos, np.nan),
        'kitchen_sink': np.full(n_oos, np.nan),
    }
    fwd_oos = np.full(n_oos, np.nan)

    for i in range(n_oos):
        t = oos_start_idx + i

        # Current day's predictors (no lookahead: g_t, VRP_t, VIX_t are known at t)
        gt_now = g_t_all[t]
        vrp_now = all_vrp[t]
        vix_now = all_vix_level[t]
        fwd_now = all_fwd[t]

        if not (np.isfinite(gt_now) and np.isfinite(vrp_now) and np.isfinite(vix_now) and np.isfinite(fwd_now)):
            continue

        fwd_oos[i] = fwd_now

        # Training data: expanding window [train_start, t-1]
        # Use g_t values we pre-computed
        train_start = max(0, t - WINDOW)
        train_end = t  # exclusive: up to t-1

        # Get valid training points
        train_g = g_t_all[train_start:train_end]
        train_fwd = all_fwd[train_start:train_end]
        train_vrp = all_vrp[train_start:train_end]
        train_vix = all_vix_level[train_start:train_end]

        valid = (np.isfinite(train_g) & np.isfinite(train_fwd) &
                 np.isfinite(train_vrp) & np.isfinite(train_vix))
        n_valid_train = valid.sum()

        if n_valid_train < 200:
            continue

        tg = train_g[valid]
        tf = train_fwd[valid]
        tv = train_vrp[valid]
        tvx = train_vix[valid]
        n_tr = len(tf)
        ones = np.ones(n_tr)

        # Model 1: Historical mean
        preds['hist_mean'][i] = np.mean(tf)

        # Model 2: VRP-only
        X = np.column_stack([ones, tv])
        beta = np.linalg.lstsq(X, tf, rcond=None)[0]
        preds['vrp_only'][i] = beta[0] + beta[1] * vrp_now

        # Model 3: g_t-only
        X = np.column_stack([ones, tg])
        beta = np.linalg.lstsq(X, tf, rcond=None)[0]
        preds['gt_only'][i] = beta[0] + beta[1] * gt_now

        # Model 4: VIX-only
        X = np.column_stack([ones, tvx])
        beta = np.linalg.lstsq(X, tf, rcond=None)[0]
        preds['vix_only'][i] = beta[0] + beta[1] * vix_now

        # Model 5: g_t + VRP
        X = np.column_stack([ones, tg, tv])
        beta = np.linalg.lstsq(X, tf, rcond=None)[0]
        preds['gt_vrp'][i] = beta[0] + beta[1] * gt_now + beta[2] * vrp_now

        # Model 6: Kitchen sink
        X = np.column_stack([ones, tg, tv, tvx])
        beta = np.linalg.lstsq(X, tf, rcond=None)[0]
        preds['kitchen_sink'][i] = beta[0] + beta[1] * gt_now + beta[2] * vrp_now + beta[3] * vix_now

    # --- Evaluate ---
    valid_oos = np.isfinite(fwd_oos)
    for k in preds:
        valid_oos &= np.isfinite(preds[k])
    n_valid = valid_oos.sum()
    print(f"    Valid OOS predictions: {n_valid}")

    if n_valid < 50:
        print(f"    WARNING: Too few valid OOS points for h={h}")
        results_by_horizon[h] = {'error': 'insufficient_data', 'n_valid': int(n_valid)}
        continue

    actual = fwd_oos[valid_oos]
    benchmark_mse = np.mean((actual - preds['hist_mean'][valid_oos]) ** 2)

    model_results = {}
    for model_name in preds:
        pred_vals = preds[model_name][valid_oos]
        errors = actual - pred_vals
        se = errors ** 2
        mse = np.mean(se)

        oos_r2 = 1 - mse / benchmark_mse if model_name != 'hist_mean' else 0.0
        correct_dir = np.mean(np.sign(pred_vals) == np.sign(actual))

        # DM test vs hist_mean
        dm_stat = dm_pval = cw_stat = cw_pval = None
        if model_name != 'hist_mean':
            bench_se = (actual - preds['hist_mean'][valid_oos]) ** 2
            d = bench_se - se
            d_mean = np.mean(d)
            lag_nw = max(h - 1, 1)
            d_dm = d - d_mean
            var_d = np.var(d_dm)
            for j in range(1, lag_nw + 1):
                w = 1 - j / (lag_nw + 1)
                var_d += 2 * w * np.mean(d_dm[j:] * d_dm[:-j])
            dm_se = np.sqrt(max(var_d, 1e-20) / n_valid)
            if dm_se > 0:
                dm_stat = float(d_mean / dm_se)
                dm_pval = float(2 * (1 - stats.norm.cdf(abs(dm_stat))))

            # Clark-West
            e_bench = actual - preds['hist_mean'][valid_oos]
            e_model = errors
            cw_d = e_bench**2 - e_model**2 + (preds['hist_mean'][valid_oos] - pred_vals)**2
            cw_mean = np.mean(cw_d)
            cw_dm = cw_d - cw_mean
            cw_var = np.var(cw_dm)
            for j in range(1, lag_nw + 1):
                w = 1 - j / (lag_nw + 1)
                cw_var += 2 * w * np.mean(cw_dm[j:] * cw_dm[:-j])
            cw_se = np.sqrt(max(cw_var, 1e-20) / n_valid)
            if cw_se > 0:
                cw_stat = float(cw_mean / cw_se)
                cw_pval = float(1 - stats.norm.cdf(cw_stat))

        model_results[model_name] = {
            'mse': float(mse),
            'oos_r2': float(oos_r2),
            'direction_accuracy': float(correct_dir),
            'dm_stat': dm_stat,
            'dm_pval': dm_pval,
            'cw_stat': cw_stat,
            'cw_pval': cw_pval,
        }

        line = f"    {model_name:15s}: OOS R2={oos_r2:+.4f}, Dir={correct_dir:.3f}"
        if dm_stat is not None:
            line += f", DM={dm_stat:+.2f}(p={dm_pval:.3f}), CW={cw_stat:+.2f}(p={cw_pval:.3f})"
        print(line)

    # --- In-sample regression (full pre-OOS period) ---
    print(f"\n    In-sample full regression:")
    is_g = g_t_all[:oos_start_idx]
    is_fwd = all_fwd[:oos_start_idx]
    is_vrp = all_vrp[:oos_start_idx]
    is_vix = all_vix_level[:oos_start_idx]
    all_fwd_h = df_clean[fwd_key].values[:oos_start_idx]

    is_valid = np.isfinite(is_g) & np.isfinite(all_fwd_h) & np.isfinite(is_vrp) & np.isfinite(is_vix)
    if is_valid.sum() > 100:
        g_v = is_g[is_valid]
        f_v = all_fwd_h[is_valid]
        v_v = is_vrp[is_valid]
        vx_v = is_vix[is_valid]
        n_is = len(f_v)

        X_is = np.column_stack([np.ones(n_is), g_v, v_v, vx_v])
        beta_is = np.linalg.lstsq(X_is, f_v, rcond=None)[0]
        resid_is = f_v - X_is @ beta_is
        is_r2 = 1 - np.var(resid_is) / np.var(f_v)
        lag_nw = max(h - 1, 1)
        se_hac = newey_west_se(resid_is, X_is, lag_nw)

        print(f"      IS R2: {is_r2:.4f}, n={n_is}")
        names = ['const', 'g_t', 'VRP', 'VIX']
        for j, nm in enumerate(names):
            t_s = beta_is[j] / se_hac[j] if se_hac[j] > 0 else 0
            print(f"        {nm:6s}: {beta_is[j]:+.6f} (t={t_s:+.2f})")

        model_results['in_sample'] = {
            'r2': float(is_r2),
            'n': int(n_is),
            'coefficients': {nm: float(beta_is[j]) for j, nm in enumerate(names)},
            'hac_t_stats': {nm: float(beta_is[j] / se_hac[j]) if se_hac[j] > 0 else 0
                            for j, nm in enumerate(names)},
        }

    # --- Long-short economic value ---
    g_oos = g_t_all[oos_start_idx:oos_start_idx + n_oos]
    fwd_h_oos = df_clean[fwd_key].values[oos_start_idx:oos_start_idx + n_oos]
    valid_ls = np.isfinite(g_oos) & np.isfinite(fwd_h_oos)

    if valid_ls.sum() > 50:
        g_ls = g_oos[valid_ls]
        f_ls = fwd_h_oos[valid_ls]
        ls_ret = np.zeros(len(g_ls))

        for i_e in range(50, len(g_ls)):
            med_g = np.median(g_ls[:i_e])
            # g_t < median -> VRP positive -> long equity (risk overpriced)
            # This is the signal: use g_t[i_e-1] to decide position for return at i_e
            # (lag by 1 to avoid lookahead)
            if i_e > 0 and g_ls[i_e - 1] < med_g:
                ls_ret[i_e] = f_ls[i_e]
            elif i_e > 0:
                ls_ret[i_e] = -f_ls[i_e]

        ls_valid = ls_ret[50:]
        if len(ls_valid) > 0 and np.std(ls_valid) > 0:
            ann = 252 / h
            ls_sharpe = np.mean(ls_valid) / np.std(ls_valid) * np.sqrt(ann)
            bh_sharpe = np.mean(f_ls[50:]) / np.std(f_ls[50:]) * np.sqrt(ann) if np.std(f_ls[50:]) > 0 else 0

            print(f"\n    Long-short (g_t signal, lagged):")
            print(f"      LS Sharpe: {ls_sharpe:.3f}, BH Sharpe: {bh_sharpe:.3f}")

            model_results['long_short'] = {
                'ls_sharpe': float(ls_sharpe),
                'bh_sharpe': float(bh_sharpe),
                'ls_mean_ann': float(np.mean(ls_valid) * ann),
                'n_trades': int(len(ls_valid)),
            }

    # g_t descriptive stats
    valid_g_oos = g_oos[np.isfinite(g_oos)]
    model_results['g_t_stats'] = {
        'mean': float(np.mean(valid_g_oos)),
        'std': float(np.std(valid_g_oos)),
        'median': float(np.median(valid_g_oos)),
        'min': float(np.min(valid_g_oos)),
        'max': float(np.max(valid_g_oos)),
        'pct_below_1': float(np.mean(valid_g_oos < 1)),
    }
    print(f"    g_t OOS: mean={np.mean(valid_g_oos):.4f}, median={np.median(valid_g_oos):.4f}, "
          f"%<1={np.mean(valid_g_oos < 1)*100:.1f}%")

    results_by_horizon[h] = {
        'n_valid': int(n_valid),
        'n_refits': int(n_refits),
        'models': model_results,
    }


# ============================================================
# SECTION 7: SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

summary_table = []
for h in HORIZONS:
    if 'error' in results_by_horizon.get(h, {}):
        continue
    hr = results_by_horizon[h]
    print(f"\n  h={h}d (n={hr['n_valid']}):")
    for mn in ['hist_mean', 'vrp_only', 'gt_only', 'vix_only', 'gt_vrp', 'kitchen_sink']:
        if mn not in hr['models']:
            continue
        m = hr['models'][mn]
        r2 = m['oos_r2']
        da = m['direction_accuracy']
        line = f"    {mn:15s}: R2={r2:+.4f}, Dir={da:.3f}"
        if m.get('cw_pval') is not None:
            if m['cw_pval'] < 0.01:
                line += " ***"
            elif m['cw_pval'] < 0.05:
                line += " **"
            elif m['cw_pval'] < 0.10:
                line += " *"
        print(line)
        summary_table.append({
            'horizon': h, 'model': mn,
            'oos_r2': r2, 'direction_accuracy': da,
            'dm_stat': m.get('dm_stat'), 'cw_stat': m.get('cw_stat'),
            'cw_pval': m.get('cw_pval'),
        })


# ============================================================
# SECTION 8: VISUALIZATION
# ============================================================
print("\n[5] Generating charts...")

fig, axes = plt.subplots(2, 3, figsize=(18, 10))
fig.suptitle(f'{EXPERIMENT_ID}: OOS Return Predictability -- A4f g_t vs VRP vs VIX',
             fontsize=14, fontweight='bold')

for col, h in enumerate(HORIZONS):
    # Row 1: OOS R^2
    ax = axes[0, col]
    if 'error' in results_by_horizon.get(h, {}):
        ax.text(0.5, 0.5, f'h={h}: No Data', ha='center', va='center', transform=ax.transAxes)
        continue
    hr = results_by_horizon[h]
    mnames = ['vrp_only', 'gt_only', 'vix_only', 'gt_vrp', 'kitchen_sink']
    dnames = ['VRP', 'g_t', 'VIX', 'g_t+VRP', 'All']
    r2_vals = [hr['models'].get(mn, {}).get('oos_r2', 0) for mn in mnames]
    colors = ['#4CAF50' if v >= 0 else '#F44336' for v in r2_vals]
    bars = ax.bar(dnames, r2_vals, color=colors, edgecolor='black', linewidth=0.5)
    ax.axhline(0, color='black', linewidth=0.5)
    ax.set_title(f'h={h}d OOS R^2', fontsize=12)
    ax.set_ylabel('OOS R^2')
    for bar, val in zip(bars, r2_vals):
        y = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2, y,
                f'{val:.4f}', ha='center', va='bottom' if val >= 0 else 'top', fontsize=8)

    # Row 2: Direction accuracy
    ax = axes[1, col]
    mnames2 = ['hist_mean', 'vrp_only', 'gt_only', 'vix_only', 'gt_vrp', 'kitchen_sink']
    dnames2 = ['Mean', 'VRP', 'g_t', 'VIX', 'g+V', 'All']
    da_vals = [hr['models'].get(mn, {}).get('direction_accuracy', 0.5) for mn in mnames2]
    colors_da = ['#4CAF50' if v > 0.5 else '#F44336' for v in da_vals]
    bars = ax.bar(dnames2, da_vals, color=colors_da, edgecolor='black', linewidth=0.5)
    ax.axhline(0.5, color='red', linewidth=1, linestyle='--', label='50%')
    ax.set_title(f'h={h}d Direction Accuracy', fontsize=12)
    ax.set_ylabel('Accuracy')
    ax.set_ylim(0.40, 0.65)
    ax.legend(fontsize=7)
    for bar, val in zip(bars, da_vals):
        ax.text(bar.get_x() + bar.get_width()/2, val + 0.003,
                f'{val:.3f}', ha='center', va='bottom', fontsize=7)

plt.tight_layout()
chart_path = os.path.join(SCRIPT_DIR, 'k1040_oos_r2_direction.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart_path}")


# ============================================================
# SECTION 9: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME

final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'VRP Return Predictability via A4f g_t',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'config': {
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'horizons': HORIZONS,
        'rv_window': RV_WINDOW,
        'df_fixed': DF_FIXED,
        'seed': 42,
        'asset': 'SPY',
        'data_source': 'yfinance',
    },
    'n_total': int(n_total),
    'results_by_horizon': {},
    'summary_table': summary_table,
    'references': [
        'Bollerslev, Tauchen & Zhou (2009). Expected Stock Returns and VRP. RFS 22(11).',
        'Campbell & Thompson (2008). Predicting Excess Stock Returns OOS. RFS 21(4).',
        'Clark & West (2007). Approximately Normal Tests for Nested Models. JoE 138(1).',
        'K1023: g_t vs VRP Spearman rho ~ 0.80',
        'K998: g_t cannot predict future VRP',
        'K818: SSVS return prediction NULL (OOS R2=-1.47%)',
    ],
    'conclusion': '',
}

# Copy results with proper serialization
for h_key, h_data in results_by_horizon.items():
    final_results['results_by_horizon'][str(h_key)] = h_data

# Auto-generate conclusion
has_positive_r2 = any(
    results_by_horizon.get(h, {}).get('models', {}).get(mn, {}).get('oos_r2', -1) > 0
    for h in HORIZONS
    for mn in ['vrp_only', 'gt_only', 'vix_only', 'gt_vrp', 'kitchen_sink']
)

has_sig_cw = any(
    (results_by_horizon.get(h, {}).get('models', {}).get(mn, {}).get('cw_pval') or 1) < 0.05
    for h in HORIZONS
    for mn in ['vrp_only', 'gt_only', 'vix_only', 'gt_vrp', 'kitchen_sink']
)

if has_positive_r2 and has_sig_cw:
    final_results['conclusion'] = (
        'POSITIVE: Some models show positive OOS R^2 with significant Clark-West test. '
        'g_t from A4f has return predictive power, consistent with Bollerslev et al. (2009).'
    )
elif has_positive_r2:
    final_results['conclusion'] = (
        'WEAK POSITIVE: Some models show positive OOS R^2 but not statistically significant '
        'by Clark-West test. Marginal evidence of return predictability.'
    )
else:
    final_results['conclusion'] = (
        'NULL: No model achieves positive OOS R^2 for SPY returns. '
        'g_t from A4f does not predict future returns, consistent with EMH. '
        'This extends K818 (SSVS null) and K998 (no g_t -> VRP prediction).'
    )

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\n[6] Results saved: {RESULTS_PATH}")
print(f"    Runtime: {elapsed:.1f}s")
print(f"    Conclusion: {final_results['conclusion']}")
print("=" * 70)
print(f"{EXPERIMENT_ID} COMPLETE")
print("=" * 70)
