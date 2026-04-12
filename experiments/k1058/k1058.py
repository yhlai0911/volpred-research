#!/usr/bin/env python3
"""
K1058: A4f Cross-Market Validation on 0050.TW with US VIX
==========================================================
[提出: 賴奕豪, 執行: Claude]

Motivation:
  A4f (multiplicative GARCH-X with VIX²) is the core model of Paper 9.
  K988 showed DM t=4.48 vs GJR on SPY, K1056 confirmed 5/5 sub-period robustness.
  This experiment tests A4f on Taiwan market (0050.TW) using US VIX as the
  external regressor, providing cross-market validation for Paper 9.

  Key questions:
  1. Does A4f with US VIX² improve 0050.TW volatility prediction?
  2. Does DM test pass Harvey |t|>3.0?
  3. How does θ₁ compare to SPY? (amplified? attenuated?)
  4. VaR/ES Trinity test PASS rate?

  Taiwan market specifics:
  - 0050.TW has TSMC ~50% weight, different trading hours
  - Taiwan amplification factor 4.6x (K176)
  - VIX-to-TW lag exists (TW uses prior-day VIX)
  - Trading days differ (Taiwan vs US holidays) → forward-fill VIX

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797.
  - Conrad & Loch (2015). Anticipating Long-Term Stock Market Volatility. JBES.
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold.
  - K988: A4f DM t=4.48 vs GJR on SPY (baseline comparison)
  - K994: Cross-asset QQQ/GLD significant, 0050.TW not tested
  - K997: Local fear index (VIXTWN) not superior to US VIX for TW

Data: 0050.TW 2005-2026, ^VIX from yfinance. OOS: 2019-01-01 to latest.
Evaluation: QLIKE on r² (Patton 2011), DM test, Spearman rank, VaR/ES Trinity.
Random seed: 42

Author: VolPred Research System
Date: 2026-04-12
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
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1058"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, spearman_corr
from volpred.utils import clean_tw50_data

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1058_results.json')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-12'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63  # quarterly refit

print("=" * 70)
print(f"{EXPERIMENT_ID}: A4f Cross-Market Validation on 0050.TW with US VIX")
print("  Cross-market robustness test for Paper 9")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

# Load 0050.TW
raw_tw = yf.download('0050.TW', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw_tw.columns, pd.MultiIndex):
    raw_tw.columns = raw_tw.columns.get_level_values(0)
prices_tw = raw_tw['Close'].copy()

# ⚠️ MANDATORY: Clean 0050.TW split artifacts
prices_tw, _ = clean_tw50_data(prices_tw)

log_ret_tw = np.log(prices_tw / prices_tw.shift(1))

# Load VIX
vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

# Align: 0050.TW and VIX have different trading days
# Forward-fill VIX to 0050.TW trading days
vix_ffill = vix_close.reindex(prices_tw.index, method='ffill')

df = pd.DataFrame({
    'price': prices_tw,
    'log_ret': log_ret_tw,
    'VIX': vix_ffill
})
df = df.dropna()

# Check for anomalous returns (split artifacts)
max_abs_ret = df['log_ret'].abs().max()
if max_abs_ret > 0.3:
    print(f"  ⚠️ WARNING: Max |return| = {max_abs_ret:.4f}, checking for split artifacts...")
    bad_dates = df[df['log_ret'].abs() > 0.3].index
    for d in bad_dates:
        print(f"    Suspicious return on {d.strftime('%Y-%m-%d')}: {df.loc[d, 'log_ret']:.4f}")
    # Remove extreme outliers (>30% daily return = very likely split artifact)
    df = df[df['log_ret'].abs() <= 0.3]
    print(f"  After cleaning: {len(df)} observations")

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  0050.TW: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2

# ============================================================
# SECTION 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
oos_ret = ret[oos_mask]
print(f"  Full sample mean return (ann): {np.mean(ret)*252:.4f}")
print(f"  Full sample std (ann): {np.std(ret)*np.sqrt(252):.4f}")
print(f"  OOS mean return (ann): {np.mean(oos_ret)*252:.4f}")
print(f"  OOS std (ann): {np.std(oos_ret)*np.sqrt(252):.4f}")
print(f"  OOS skewness: {stats.skew(oos_ret):.3f}")
print(f"  OOS kurtosis: {stats.kurtosis(oos_ret):.3f}")
print(f"  VIX mean: {np.mean(vix):.2f}")
print(f"  VIX autocorr(1): {np.corrcoef(vix[1:], vix[:-1])[0,1]:.4f}")

# ADF test on returns
from statsmodels.tsa.stattools import adfuller
adf_ret = adfuller(ret, maxlag=10, autolag='AIC')
print(f"  ADF on returns: stat={adf_ret[0]:.4f}, p={adf_ret[1]:.6f}")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_lm = het_arch(ret, nlags=5)
print(f"  ARCH LM(5): stat={arch_lm[0]:.2f}, p={arch_lm[1]:.6f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


# --- GJR-GARCH(1,1) Benchmark ---
@njit(cache=True)
def gjr_loglik(params, returns):
    """Standard GJR-GARCH(1,1) log-likelihood."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    """Fit GJR-GARCH(1,1)."""
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f: Multiplicative GARCH-X with VIX² and free omega ---
def fit_a4f(returns, vix_vals):
    """
    Fit A4f: τ_t = max(θ₀ + θ₁ × VIX²_{t-1}, ε)
    g_t = ω_g + α × u²_{t-1} + γ × u²_{t-1} × I(u<0) + β × g_{t-1}
    σ²_t = τ_t × g_t

    where u_t = r_t / sqrt(τ_t), denominator uses τ_t (current, predetermined per Engle et al. 2013)
    free omega: ω_g is a free parameter (not constrained to 1-α-γ/2-β)

    Parameters: [θ₀, θ₁, ω_g, α, γ, β]
    """
    n = len(returns)

    # Lagged VIX for tau (no lookahead)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params

        # Compute tau
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

        if omega_g <= 0:
            return 1e10
        if alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        if alpha + gamma_p / 2.0 + beta >= 0.999:
            return 1e10

        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 1.0:
            return 1e10
        eg = omega_g / (1.0 - persist)

        g = np.empty(n)
        g[0] = eg
        ll = 0.0

        for t in range(1, n):
            # Denominator = tau_t (current, predetermined)
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)

        return -ll

    best_ll = np.inf
    best_params = None

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag**2) + 1e-8

    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
        [var0 * 0.01, var0 / vix2_mean * 2.0, 0.08, 0.04, 0.06, 0.85],
    ]

    bounds = [
        (-1e-2, 1e-2),     # θ₀
        (1e-8, 1e-3),       # θ₁
        (1e-6, 1.0),        # ω_g
        (1e-4, 0.3),        # α
        (1e-4, 0.3),        # γ
        (0.5, 0.999),       # β
    ]

    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params


def compute_tau_a4f(theta0, theta1, vix_lag_val):
    """Compute tau for A4f: τ = max(θ₀ + θ₁ × VIX², ε)"""
    if np.isscalar(vix_lag_val):
        return max(theta0 + theta1 * vix_lag_val**2, 1e-16)
    return np.maximum(theta0 + theta1 * vix_lag_val**2, 1e-16)


# ============================================================
# SECTION 4: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[4] Out-of-sample forecasting...")

oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)
print(f"  OOS observations: {n_oos_actual}")

model_names = ['GJR', 'A4f']
forecasts = {name: np.full(n_oos_actual, np.nan) for name in model_names}

# Parameter tracking
theta1_history = []  # Track θ₁ over refits
gjr_param_history = []
a4f_param_history = []

# State variables
states = {
    'GJR': {'params': None, 'h': None},
    'A4f': {'params': None, 'g': None, 'tau_prev': None},
}

refit_count = 0
print(f"  Refit every {REFIT_EVERY} days")

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # GJR
        gjr_params = fit_gjr(train_ret)
        if gjr_params is not None:
            states['GJR']['params'] = gjr_params
            gjr_param_history.append({
                'refit': refit_count,
                'date': str(df.index[abs_idx].date()),
                'omega': float(gjr_params[0]),
                'alpha': float(gjr_params[1]),
                'gamma': float(gjr_params[2]),
                'beta': float(gjr_params[3]),
                'persistence': float(gjr_params[1] + gjr_params[2]/2 + gjr_params[3]),
            })
            # Initialize h from training
            h = np.var(train_ret)
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            states['GJR']['h'] = h

        # A4f
        a4f_params = fit_a4f(train_ret, train_vix)
        if a4f_params is not None:
            states['A4f']['params'] = a4f_params
            theta0, theta1_val = a4f_params[0], a4f_params[1]
            omega_g, alpha_p, gamma_p, beta_p = a4f_params[2], a4f_params[3], a4f_params[4], a4f_params[5]

            a4f_param_history.append({
                'refit': refit_count,
                'date': str(df.index[abs_idx].date()),
                'theta0': float(theta0),
                'theta1': float(theta1_val),
                'omega_g': float(omega_g),
                'alpha': float(alpha_p),
                'gamma': float(gamma_p),
                'beta': float(beta_p),
                'persistence': float(alpha_p + gamma_p/2 + beta_p),
            })
            theta1_history.append(float(theta1_val))

            # Initialize g from training
            n_train = len(train_ret)
            vix_lag_tr = np.empty(n_train)
            vix_lag_tr[0] = train_vix[0]
            vix_lag_tr[1:] = train_vix[:-1]

            tau_train = compute_tau_a4f(theta0, theta1_val, vix_lag_tr)

            persist = alpha_p + gamma_p / 2.0 + beta_p
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g = eg
            for i in range(1, n_train):
                # Denominator = tau_t (current, predetermined)
                u_prev = train_ret[i-1] / np.sqrt(max(tau_train[i], 1e-16))
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)

            states['A4f']['g'] = g
            states['A4f']['tau_prev'] = tau_train[-1]

    # --- Generate forecasts for day abs_idx ---

    # GJR
    p = states['GJR']['params']
    if p is not None:
        h_prev = states['GJR']['h']
        r_prev = ret[abs_idx - 1]
        h_new = gjr_forecast_1step(p, h_prev, r_prev)
        forecasts['GJR'][t_idx] = h_new
        states['GJR']['h'] = h_new

    # A4f
    p = states['A4f']['params']
    if p is not None:
        theta0, theta1_val = p[0], p[1]
        omega_g, alpha_p, gamma_p, beta_p = p[2], p[3], p[4], p[5]

        # tau_t uses VIX_{t-1} — predetermined (no lookahead)
        v_lag = vix[abs_idx - 1]
        tau_t = compute_tau_a4f(theta0, theta1_val, v_lag)

        # Update g using r_{t-1}
        r_prev = ret[abs_idx - 1]
        g_prev = states['A4f']['g']

        # Denominator = tau_t (current, predetermined)
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        forecasts['A4f'][t_idx] = tau_t * g_new
        states['A4f']['g'] = g_new
        states['A4f']['tau_prev'] = tau_t

elapsed = time.time() - START_TIME
print(f"  Forecasting complete: {refit_count} refits in {elapsed:.0f}s")

# ============================================================
# SECTION 5: EVALUATION
# ============================================================
print("\n[5] Evaluation...")

oos_r2 = r2[oos_mask]
oos_dates = df.index[oos_mask]

results = {
    'experiment_id': EXPERIMENT_ID,
    'asset': '0050.TW',
    'external_regressor': 'US_VIX',
    'data_source': 'yfinance',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': n_total,
    'n_oos': n_oos_actual,
    'oos_start': OOS_START,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'models': {},
    'dm_tests': {},
    'var_tests': {},
    'regime_analysis': {},
    'theta1_comparison': {},
    'diagnostics': {
        'full_sample_mean_return_ann': float(np.mean(ret) * 252),
        'full_sample_std_ann': float(np.std(ret) * np.sqrt(252)),
        'oos_mean_return_ann': float(np.mean(oos_ret) * 252),
        'oos_std_ann': float(np.std(oos_ret) * np.sqrt(252)),
        'oos_skewness': float(stats.skew(oos_ret)),
        'oos_kurtosis': float(stats.kurtosis(oos_ret)),
        'vix_mean': float(np.mean(vix)),
        'adf_stat': float(adf_ret[0]),
        'adf_p': float(adf_ret[1]),
        'arch_lm_stat': float(arch_lm[0]),
        'arch_lm_p': float(arch_lm[1]),
    },
}

# --- Model-level metrics ---
for name in model_names:
    fc = forecasts[name]
    valid = np.isfinite(fc) & np.isfinite(oos_r2)
    n_valid = valid.sum()

    if n_valid < 100:
        print(f"  {name}: too few valid forecasts ({n_valid})")
        continue

    fc_v = fc[valid]
    r2_v = oos_r2[valid]

    # QLIKE
    qlike_val = float(qlike(r2_v, fc_v))

    # Spearman
    rho, rho_p = spearman_corr(r2_v, fc_v)

    # MSE
    mse_val = float(np.mean((r2_v - fc_v)**2))

    print(f"  {name}: QLIKE={qlike_val:.6f}, Spearman={rho:.4f}, MSE={mse_val:.2e}, n_valid={n_valid}")

    results['models'][name] = {
        'qlike': qlike_val,
        'mse': mse_val,
        'spearman_rho': float(rho),
        'spearman_p': float(rho_p),
        'n_valid': int(n_valid),
        'mean_forecast': float(np.mean(fc_v)),
        'std_forecast': float(np.std(fc_v)),
    }

# --- DM Test ---
print("\n  DM Tests:")
from volpred.stats.model_evaluation import qlike_pointwise

gjr_fc = forecasts['GJR']
a4f_fc = forecasts['A4f']
valid = np.isfinite(gjr_fc) & np.isfinite(a4f_fc) & np.isfinite(oos_r2)

if valid.sum() > 100:
    loss_gjr = qlike_pointwise(oos_r2[valid], gjr_fc[valid])
    loss_a4f = qlike_pointwise(oos_r2[valid], a4f_fc[valid])

    dm_t, dm_p = dm_test(loss_a4f, loss_gjr)

    # Negative t → A4f is better (lower QLIKE loss)
    direction = "A4f_better" if dm_t < 0 else "GJR_better"
    significant = abs(dm_t) > 3.0

    print(f"  A4f vs GJR: DM t={dm_t:.4f}, p={dm_p:.6f}, |t|>3.0: {significant}, direction: {direction}")

    # QLIKE improvement percentage
    mean_gjr_loss = float(np.mean(loss_gjr))
    mean_a4f_loss = float(np.mean(loss_a4f))
    improvement_pct = (mean_gjr_loss - mean_a4f_loss) / mean_gjr_loss * 100 if mean_gjr_loss != 0 else 0

    results['dm_tests']['A4f_vs_GJR'] = {
        'dm_t': float(dm_t),
        'dm_p': float(dm_p),
        'significant_harvey': significant,
        'direction': direction,
        'n_compared': int(valid.sum()),
        'mean_qlike_loss_gjr': mean_gjr_loss,
        'mean_qlike_loss_a4f': mean_a4f_loss,
        'qlike_improvement_pct': float(improvement_pct),
    }

# ============================================================
# SECTION 6: VaR/ES EVALUATION (Trinity Test)
# ============================================================
print("\n[6] VaR/ES Evaluation (Trinity Test)...")

def kupiec_test(violations, n_obs, alpha):
    """Kupiec (1995) unconditional coverage test."""
    n_viol = np.sum(violations)
    p_hat = n_viol / n_obs if n_obs > 0 else 0
    if p_hat == 0 or p_hat == 1:
        return 0.0, 1.0  # degenerate
    lr = -2 * (n_obs * np.log(1 - alpha) + n_viol * np.log(alpha)
               - (n_obs - n_viol) * np.log(1 - p_hat) - n_viol * np.log(p_hat))
    lr = max(lr, 0)
    p_val = 1 - stats.chi2.cdf(lr, 1)
    return float(lr), float(p_val)


def christoffersen_test(violations):
    """Christoffersen (1998) conditional coverage (independence) test."""
    n = len(violations)
    viol = violations.astype(int)

    # Count transitions
    n00, n01, n10, n11 = 0, 0, 0, 0
    for i in range(1, n):
        if viol[i-1] == 0 and viol[i] == 0: n00 += 1
        elif viol[i-1] == 0 and viol[i] == 1: n01 += 1
        elif viol[i-1] == 1 and viol[i] == 0: n10 += 1
        elif viol[i-1] == 1 and viol[i] == 1: n11 += 1

    # Independence test
    n0 = n00 + n01
    n1 = n10 + n11

    if n0 == 0 or n1 == 0:
        return 0.0, 1.0

    pi01 = n01 / n0 if n0 > 0 else 0
    pi11 = n11 / n1 if n1 > 0 else 0
    pi = (n01 + n11) / (n0 + n1)

    if pi == 0 or pi == 1 or pi01 == 0 or pi01 == 1:
        return 0.0, 1.0
    if pi11 == 0 or pi11 == 1:
        return 0.0, 1.0

    ll_0 = n00 * np.log(1 - pi) + n01 * np.log(pi) + n10 * np.log(1 - pi) + n11 * np.log(pi)
    ll_1 = n00 * np.log(1 - pi01) + n01 * np.log(pi01)
    if pi11 > 0 and pi11 < 1:
        ll_1 += n10 * np.log(1 - pi11) + n11 * np.log(pi11)

    lr_ind = -2 * (ll_0 - ll_1)
    lr_ind = max(lr_ind, 0)
    p_val = 1 - stats.chi2.cdf(lr_ind, 1)
    return float(lr_ind), float(p_val)


def basel_traffic_light(n_violations, n_obs, alpha):
    """Basel traffic light test (250-day convention)."""
    # Scale to 250-day equivalent
    scale = 250 / n_obs if n_obs > 0 else 1
    n_viol_scaled = n_violations * scale

    expected = alpha * 250

    if n_viol_scaled <= expected * 1.5:
        return "Green"
    elif n_viol_scaled <= expected * 2.5:
        return "Yellow"
    else:
        return "Red"


def acerbi_szekely_es_test(returns, var_forecast, es_forecast, alpha):
    """Acerbi & Szekely (2014) ES backtest Z-test."""
    violations = returns < -np.sqrt(var_forecast) * stats.norm.ppf(1 - alpha)

    if violations.sum() == 0:
        return 0.0, 1.0

    # Test statistic
    exceedances = returns[violations]
    expected_es = -np.sqrt(es_forecast[violations]) if len(es_forecast[violations]) > 0 else 0

    # Simplified version: compare average loss given violation to ES
    avg_loss = np.mean(-exceedances)
    avg_es = np.mean(np.sqrt(var_forecast[violations])) * stats.norm.pdf(stats.norm.ppf(alpha)) / alpha

    if avg_es == 0:
        return 0.0, 1.0

    z = (avg_loss - avg_es) / (np.std(-exceedances) / np.sqrt(violations.sum()))
    p_val = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(z), float(p_val)


# VaR/ES for each model at 1% and 5%
alphas = [0.01, 0.05]

for name in model_names:
    fc = forecasts[name]
    valid = np.isfinite(fc)
    if valid.sum() < 100:
        continue

    fc_v = fc[valid]
    ret_v = ret[oos_mask][valid]
    n_v = len(ret_v)

    results['var_tests'][name] = {}

    for alpha in alphas:
        z_alpha = stats.norm.ppf(alpha)

        # VaR = sigma * z_alpha (negative = loss threshold)
        var_threshold = np.sqrt(fc_v) * z_alpha  # negative

        # ES = sigma * phi(z) / alpha (expected shortfall)
        es_multiplier = -stats.norm.pdf(z_alpha) / alpha
        es_threshold = np.sqrt(fc_v) * es_multiplier  # positive (loss magnitude)

        # Violations: return < VaR
        violations = ret_v < var_threshold
        n_viol = int(violations.sum())
        viol_rate = n_viol / n_v
        expected_rate = alpha

        # Kupiec
        kup_stat, kup_p = kupiec_test(violations, n_v, alpha)

        # Christoffersen
        cc_stat, cc_p = christoffersen_test(violations)

        # Basel
        basel = basel_traffic_light(n_viol, n_v, alpha)

        # Trinity: all three pass
        trinity_pass = (kup_p > 0.05) and (cc_p > 0.05) and (basel == "Green")

        # ES test (simplified)
        if n_viol > 5:
            es_z, es_p = acerbi_szekely_es_test(ret_v, fc_v, fc_v, alpha)
        else:
            es_z, es_p = 0.0, 1.0

        label = f"alpha_{int(alpha*100)}pct"
        results['var_tests'][name][label] = {
            'alpha': alpha,
            'n_obs': n_v,
            'n_violations': n_viol,
            'violation_rate': float(viol_rate),
            'expected_rate': expected_rate,
            'kupiec_stat': kup_stat,
            'kupiec_p': float(kup_p),
            'kupiec_pass': kup_p > 0.05,
            'christoffersen_stat': cc_stat,
            'christoffersen_p': float(cc_p),
            'christoffersen_pass': cc_p > 0.05,
            'basel_traffic_light': basel,
            'trinity_pass': trinity_pass,
            'es_z': es_z,
            'es_p': float(es_p),
            'es_pass': es_p > 0.05,
        }

        print(f"  {name} VaR({int(alpha*100)}%): violations={n_viol}/{n_v} ({viol_rate:.3f}), "
              f"Kupiec p={kup_p:.4f}, CC p={cc_p:.4f}, Basel={basel}, "
              f"Trinity={'PASS' if trinity_pass else 'FAIL'}, ES p={es_p:.4f}")

# ============================================================
# SECTION 7: VIX REGIME CONDITIONAL ANALYSIS
# ============================================================
print("\n[7] VIX Regime Conditional Analysis...")

vix_oos = vix[oos_mask]
regimes = {
    'low (<15)': vix_oos < 15,
    'normal (15-25)': (vix_oos >= 15) & (vix_oos < 25),
    'elevated (25-35)': (vix_oos >= 25) & (vix_oos < 35),
    'high (>35)': vix_oos >= 35,
}

for regime_name, mask in regimes.items():
    n_regime = mask.sum()
    if n_regime < 30:
        print(f"  {regime_name}: n={n_regime} (too few, skipping)")
        results['regime_analysis'][regime_name] = {'n': int(n_regime), 'skipped': True}
        continue

    valid = mask & np.isfinite(gjr_fc) & np.isfinite(a4f_fc)
    if valid.sum() < 30:
        results['regime_analysis'][regime_name] = {'n': int(n_regime), 'skipped': True}
        continue

    r2_regime = oos_r2[valid]
    gjr_regime = gjr_fc[valid]
    a4f_regime = a4f_fc[valid]

    qlike_gjr_r = float(qlike(r2_regime, gjr_regime))
    qlike_a4f_r = float(qlike(r2_regime, a4f_regime))

    improvement = (qlike_gjr_r - qlike_a4f_r) / abs(qlike_gjr_r) * 100 if qlike_gjr_r != 0 else 0

    # DM test per regime
    loss_gjr_r = qlike_pointwise(r2_regime, gjr_regime)
    loss_a4f_r = qlike_pointwise(r2_regime, a4f_regime)
    dm_t_r, dm_p_r = dm_test(loss_a4f_r, loss_gjr_r)

    print(f"  {regime_name}: n={valid.sum()}, QLIKE GJR={qlike_gjr_r:.4f}, A4f={qlike_a4f_r:.4f}, "
          f"improvement={improvement:.2f}%, DM t={dm_t_r:.3f}")

    results['regime_analysis'][regime_name] = {
        'n': int(valid.sum()),
        'qlike_gjr': qlike_gjr_r,
        'qlike_a4f': qlike_a4f_r,
        'qlike_improvement_pct': float(improvement),
        'dm_t': float(dm_t_r),
        'dm_p': float(dm_p_r),
        'direction': "A4f_better" if dm_t_r < 0 else "GJR_better",
    }

# ============================================================
# SECTION 8: θ₁ COMPARISON (SPY vs 0050.TW)
# ============================================================
print("\n[8] θ₁ Comparison (SPY vs 0050.TW)...")

theta1_tw_mean = float(np.mean(theta1_history)) if theta1_history else 0
theta1_tw_std = float(np.std(theta1_history)) if len(theta1_history) > 1 else 0
theta1_tw_median = float(np.median(theta1_history)) if theta1_history else 0

# K988 SPY reference: A4f θ₁ mean across refits (from K988 results)
# We'll report TW values and let comparison be done externally
results['theta1_comparison'] = {
    'tw_theta1_mean': theta1_tw_mean,
    'tw_theta1_std': theta1_tw_std,
    'tw_theta1_median': theta1_tw_median,
    'tw_theta1_min': float(min(theta1_history)) if theta1_history else 0,
    'tw_theta1_max': float(max(theta1_history)) if theta1_history else 0,
    'n_refits': len(theta1_history),
    'spy_dm_t_reference': 4.48,  # K988 reference
}

print(f"  0050.TW θ₁: mean={theta1_tw_mean:.8f}, median={theta1_tw_median:.8f}")
print(f"  0050.TW θ₁: std={theta1_tw_std:.8f}, range=[{min(theta1_history) if theta1_history else 0:.8f}, {max(theta1_history) if theta1_history else 0:.8f}]")

# Parameter histories
results['parameter_history'] = {
    'gjr': gjr_param_history[-5:] if gjr_param_history else [],  # last 5 refits
    'a4f': a4f_param_history[-5:] if a4f_param_history else [],
}

# ============================================================
# SECTION 9: SAVE RESULTS
# ============================================================
print("\n[9] Saving results...")

results['metadata'] = {
    'script': 'k1058.py',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(time.time() - START_TIME, 1),
    'random_seed': 42,
    'references': [
        'Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3):776-797',
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256',
        'Harvey et al. (2016). t > 3.0 threshold',
        'K988: A4f DM t=4.48 vs GJR on SPY',
        'K1056: A4f 5/5 sub-period robust on SPY',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to {RESULTS_PATH}")

# ============================================================
# SECTION 10: GENERATE CHARTS
# ============================================================
print("\n[10] Generating charts...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- Chart 1: DM Comparison ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Left: QLIKE comparison
models_for_plot = list(results['models'].keys())
qlike_vals = [results['models'][m]['qlike'] for m in models_for_plot]
colors = ['#e74c3c' if m == 'A4f' else '#3498db' for m in models_for_plot]
bars = axes[0].barh(models_for_plot, qlike_vals, color=colors, edgecolor='white', height=0.5)
axes[0].set_xlabel('QLIKE (lower = better)')
axes[0].set_title(f'QLIKE on r² — 0050.TW OOS ({OOS_START}+)')
for bar, val in zip(bars, qlike_vals):
    axes[0].text(bar.get_width() + 0.001, bar.get_y() + bar.get_height()/2,
                f'{val:.4f}', va='center', fontsize=10)

# Right: DM test result
if 'A4f_vs_GJR' in results['dm_tests']:
    dm_info = results['dm_tests']['A4f_vs_GJR']
    dm_val = dm_info['dm_t']
    color = '#27ae60' if abs(dm_val) > 3.0 else '#e67e22'
    axes[1].barh(['A4f vs GJR'], [dm_val], color=color, height=0.3)
    axes[1].axvline(x=-3.0, color='red', linestyle='--', alpha=0.7, label='Harvey threshold (|t|=3.0)')
    axes[1].axvline(x=3.0, color='red', linestyle='--', alpha=0.7)
    axes[1].axvline(x=0, color='gray', linestyle='-', alpha=0.3)
    axes[1].set_xlabel('DM t-statistic')
    axes[1].set_title(f'DM Test: A4f vs GJR (t={dm_val:.2f})')
    axes[1].legend(loc='lower right')
    # Add SPY reference
    axes[1].axvline(x=-4.48, color='purple', linestyle=':', alpha=0.5, label='SPY ref (t=-4.48)')
    axes[1].legend(loc='lower right')

plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1058_dm_comparison.png')
plt.savefig(chart1_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 1 saved: {chart1_path}")

# --- Chart 2: VaR Trinity Test Heatmap ---
fig, ax = plt.subplots(figsize=(10, 5))

var_data = []
var_labels_row = []
var_labels_col = ['Kupiec\n(1%)', 'CC\n(1%)', 'Basel\n(1%)', 'ES\n(1%)',
                  'Kupiec\n(5%)', 'CC\n(5%)', 'Basel\n(5%)', 'ES\n(5%)']

for name in model_names:
    if name not in results['var_tests']:
        continue
    row = []
    for alpha_label in ['alpha_1pct', 'alpha_5pct']:
        if alpha_label in results['var_tests'][name]:
            t = results['var_tests'][name][alpha_label]
            row.append(1 if t['kupiec_pass'] else 0)
            row.append(1 if t['christoffersen_pass'] else 0)
            row.append(1 if t['basel_traffic_light'] == 'Green' else 0)
            row.append(1 if t['es_pass'] else 0)
        else:
            row.extend([0, 0, 0, 0])
    var_data.append(row)
    var_labels_row.append(name)

if var_data:
    var_arr = np.array(var_data)
    cmap = plt.cm.RdYlGn
    im = ax.imshow(var_arr, cmap=cmap, aspect='auto', vmin=0, vmax=1)
    ax.set_xticks(range(len(var_labels_col)))
    ax.set_xticklabels(var_labels_col, fontsize=9)
    ax.set_yticks(range(len(var_labels_row)))
    ax.set_yticklabels(var_labels_row)
    for i in range(len(var_labels_row)):
        for j in range(len(var_labels_col)):
            text = "PASS" if var_arr[i, j] == 1 else "FAIL"
            color = 'white' if var_arr[i, j] == 0 else 'black'
            ax.text(j, i, text, ha='center', va='center', fontsize=9, fontweight='bold', color=color)
    ax.set_title(f'VaR/ES Trinity Test — 0050.TW (OOS {OOS_START}+)')
    plt.colorbar(im, ax=ax, label='PASS (1) / FAIL (0)')

plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'k1058_var_trinity.png')
plt.savefig(chart2_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 2 saved: {chart2_path}")

# --- Chart 3: θ₁ History ---
fig, axes = plt.subplots(1, 2, figsize=(14, 5))

# Left: θ₁ time series
if a4f_param_history:
    dates_p = [p['date'] for p in a4f_param_history]
    theta1_vals = [p['theta1'] for p in a4f_param_history]
    axes[0].plot(range(len(theta1_vals)), theta1_vals, 'o-', color='#e74c3c', markersize=4)
    axes[0].set_xlabel('Refit #')
    axes[0].set_ylabel('θ₁')
    axes[0].set_title('θ₁ Evolution (0050.TW A4f)')
    axes[0].axhline(y=theta1_tw_mean, color='gray', linestyle='--', alpha=0.5, label=f'Mean={theta1_tw_mean:.2e}')
    axes[0].legend()
    axes[0].grid(True, alpha=0.3)

# Right: θ₁ distribution histogram
if theta1_history:
    axes[1].hist(theta1_history, bins=min(20, len(theta1_history)), color='#e74c3c', edgecolor='white', alpha=0.7)
    axes[1].axvline(x=theta1_tw_mean, color='red', linestyle='--', label=f'0050.TW mean={theta1_tw_mean:.2e}')
    axes[1].set_xlabel('θ₁')
    axes[1].set_ylabel('Count')
    axes[1].set_title('θ₁ Distribution: 0050.TW')
    axes[1].legend()

plt.tight_layout()
chart3_path = os.path.join(SCRIPT_DIR, 'k1058_theta1_comparison.png')
plt.savefig(chart3_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 3 saved: {chart3_path}")

# --- Chart 4: Forecast Comparison Time Series ---
fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

# Top: Actual r² and forecasts
oos_dates_arr = oos_dates.to_numpy()

valid_both = np.isfinite(gjr_fc) & np.isfinite(a4f_fc)
axes[0].scatter(oos_dates_arr[valid_both], oos_r2[valid_both], s=1, alpha=0.3, color='gray', label='r²')
axes[0].plot(oos_dates_arr[valid_both], gjr_fc[valid_both], alpha=0.7, linewidth=0.8, color='#3498db', label='GJR')
axes[0].plot(oos_dates_arr[valid_both], a4f_fc[valid_both], alpha=0.7, linewidth=0.8, color='#e74c3c', label='A4f')
axes[0].set_ylabel('Variance')
axes[0].set_title(f'Volatility Forecasts — 0050.TW OOS ({OOS_START}+)')
axes[0].legend(loc='upper right')
axes[0].set_yscale('log')

# Bottom: Cumulative QLIKE difference
if valid_both.sum() > 0:
    loss_gjr_all = qlike_pointwise(oos_r2[valid_both], gjr_fc[valid_both])
    loss_a4f_all = qlike_pointwise(oos_r2[valid_both], a4f_fc[valid_both])
    cum_diff = np.cumsum(loss_gjr_all - loss_a4f_all)
    axes[1].plot(oos_dates_arr[valid_both], cum_diff, color='#27ae60', linewidth=1.0)
    axes[1].axhline(y=0, color='gray', linestyle='--', alpha=0.3)
    axes[1].fill_between(oos_dates_arr[valid_both], 0, cum_diff,
                         where=cum_diff > 0, alpha=0.2, color='green')
    axes[1].fill_between(oos_dates_arr[valid_both], 0, cum_diff,
                         where=cum_diff < 0, alpha=0.2, color='red')
    axes[1].set_ylabel('Cumulative QLIKE Advantage\n(A4f over GJR)')
    axes[1].set_title('A4f Cumulative Advantage (positive = A4f better)')

for ax in axes:
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

plt.tight_layout()
chart4_path = os.path.join(SCRIPT_DIR, 'k1058_forecast_timeseries.png')
plt.savefig(chart4_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart 4 saved: {chart4_path}")

# ============================================================
# SECTION 11: SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

if 'A4f_vs_GJR' in results['dm_tests']:
    dm_info = results['dm_tests']['A4f_vs_GJR']
    print(f"\n  A4f vs GJR on 0050.TW:")
    print(f"    DM t-stat: {dm_info['dm_t']:.4f}")
    print(f"    Harvey |t|>3.0: {dm_info['significant_harvey']}")
    print(f"    QLIKE improvement: {dm_info['qlike_improvement_pct']:.2f}%")
    print(f"    Direction: {dm_info['direction']}")
    print(f"    SPY reference DM t: -4.48 (K988)")

if 'GJR' in results['models'] and 'A4f' in results['models']:
    print(f"\n  Spearman correlation:")
    print(f"    GJR: {results['models']['GJR']['spearman_rho']:.4f}")
    print(f"    A4f: {results['models']['A4f']['spearman_rho']:.4f}")

print(f"\n  θ₁ (0050.TW): {theta1_tw_mean:.8f}")
print(f"  Runtime: {time.time() - START_TIME:.1f}s")
print("=" * 70)
print("DONE")
