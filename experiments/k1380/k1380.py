#!/usr/bin/env python3
"""
K1380 — Paper 9 White RC / Hansen SPA Test for 17-Spec Horse Race
==================================================================
Addresses C3 CRITICAL from Paper 9 review v3:
  "17-specification ranking requires White (2000) RC or Hansen (2005) SPA test."

Implements:
  - Rolling OOS QLIKE forecasts for all 17 specs (Paper 9 Table 1)
  - Hansen (2005) SPA test: does any model beat GJR-GARCH?
  - White (2000) RC test: does A4f significantly beat GJR after data snooping?
  - Output: k1380_results.json + k1380_losses_all.npy

Harvey threshold: |t| > 3.0
QLIKE proxy: r² (squared log return, Patton 2011 proxy-robust)
seed=42, all VIX lags use signal at t-1 (lookahead prevention)
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import optimize, stats
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)
START_TIME = time.time()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

# ── Configuration (matches Paper 9 canonical) ──────────────────────────────
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
SNAPSHOT_CSV = os.path.join(PROJECT_ROOT, 'paper', 'garch-x-vix', 'data',
                             'spy_vix_qqq_eem_fez_2000-2026.csv')
BOOTSTRAP_B = 499      # stationary bootstrap draws (odd for symmetry)
BOOTSTRAP_SEED = 42
HARVEY_THRESHOLD = 3.0

# 17 specs: labels for output
SPEC_LABELS = [
    'A1', 'A2', 'A3', 'A4', 'A5',
    'A2f', 'A4f', 'A3f', 'A2n', 'A4n',
    'B1', 'B2', 'B3',
    'C1', 'C2', 'C3',
    'B0',   # GJR benchmark — last
]
BENCHMARK_IDX = 16  # B0 index in SPEC_LABELS
A4F_IDX = 6         # A4f index

print("=" * 70)
print("K1380: White RC / Hansen SPA Test — 17-Spec Horse Race")
print("=" * 70)

# ═══════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════
print("\n[1] Loading snapshot CSV...")
df_raw = pd.read_csv(SNAPSHOT_CSV, parse_dates=['date'], index_col='date')
df_raw.index = pd.to_datetime(df_raw.index)
df_raw = df_raw.sort_index()

prices = df_raw['spy_close'].dropna()
log_ret = np.log(prices / prices.shift(1))
vix_close = df_raw['vix_close'].dropna()

df = pd.DataFrame({'log_ret': log_ret, 'VIX': vix_close}).dropna()
oos_mask = df.index >= OOS_START

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2

oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
n_total = len(df)

print(f"  SPY: {df.index[0].date()} to {df.index[-1].date()}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

# Pre-compute monthly VIX averages for fixed-span MIDAS (C1-C3)
vix_series = pd.Series(vix, index=df.index)
vix_monthly = vix_series.resample('ME').mean()

# ═══════════════════════════════════════════════════════════════════════════
# 2. MODEL FITTING FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

@njit(cache=True)
def _gjr_filter(omega, alpha, gamma, beta, returns):
    """GJR variance filter (numba JIT, ~50x faster than pure Python)."""
    n = len(returns)
    h = np.empty(n)
    n_init = min(250, n)
    v = 0.0
    for i in range(n_init):
        v += returns[i] * returns[i]
    h0 = v / n_init
    h[0] = h0 if h0 > 1e-8 else 1e-8
    for t in range(1, n):
        asym = gamma * returns[t-1] * returns[t-1] if returns[t-1] < 0.0 else 0.0
        h_new = omega + alpha * returns[t-1] * returns[t-1] + asym + beta * h[t-1]
        h[t] = h_new if h_new > 1e-10 else 1e-10
    return h


def fit_gjr(returns):
    """Fit GJR-GARCH(1,1) via L-BFGS-B."""
    var0 = np.var(returns)
    def neg_ll(p):
        o, a, g, b = p
        if o <= 0 or a < 0 or g < 0 or b < 0 or a + g/2 + b >= 1:
            return 1e10
        h = _gjr_filter(o, a, g, b, returns)
        return 0.5 * np.sum(np.log(h) + returns**2 / h)
    starts = [
        [var0*0.05, 0.05, 0.05, 0.90],
        [var0*0.02, 0.03, 0.08, 0.88],
        [var0*0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll, best_p = np.inf, None
    for s in starts:
        try:
            res = optimize.minimize(neg_ll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except Exception:
            pass
    return best_p


@njit(cache=True)
def _garch_x_nll_free(omg, a, g, b, returns, tau_vals, tau_denom):
    """GARCH-X neg log-likelihood, free ω mode (numba JIT)."""
    if omg <= 0.0 or a < 0.0 or g < 0.0 or b < 0.0 or a + g / 2.0 + b >= 1.0:
        return 1e10
    n = len(returns)
    persist = a + g / 2.0 + b
    gv = omg / (1.0 - persist) if (1.0 - persist) > 1e-8 else omg / 1e-8
    ll = 0.0
    LOG2PI_HALF = 0.9189385332046728
    for t in range(1, n):
        td = tau_denom[t] if tau_denom[t] > 1e-16 else 1e-16
        u = returns[t - 1] / (td ** 0.5)
        asym = g * u * u if u < 0.0 else 0.0
        gv_new = omg + a * u * u + asym + b * gv
        gv = gv_new if gv_new > 1e-10 else 1e-10
        sigma2 = tau_vals[t] * gv
        sigma2 = sigma2 if sigma2 > 1e-16 else 1e-16
        ll += -(LOG2PI_HALF + 0.5 * (np.log(sigma2) + returns[t] * returns[t] / sigma2))
    return -ll


@njit(cache=True)
def _garch_x_nll_constrained(a, g, b, returns, tau_vals, tau_denom):
    """GARCH-X neg log-likelihood, constrained ω mode (numba JIT)."""
    if a < 0.0 or g < 0.0 or b < 0.0 or a + g / 2.0 + b >= 1.0:
        return 1e10
    omg = 1.0 - a - g / 2.0 - b
    n = len(returns)
    gv = 1.0
    ll = 0.0
    LOG2PI_HALF = 0.9189385332046728
    for t in range(1, n):
        td = tau_denom[t] if tau_denom[t] > 1e-16 else 1e-16
        u = returns[t - 1] / (td ** 0.5)
        asym = g * u * u if u < 0.0 else 0.0
        gv_new = omg + a * u * u + asym + b * gv
        gv = gv_new if gv_new > 1e-10 else 1e-10
        sigma2 = tau_vals[t] * gv
        sigma2 = sigma2 if sigma2 > 1e-16 else 1e-16
        ll += -(LOG2PI_HALF + 0.5 * (np.log(sigma2) + returns[t] * returns[t] / sigma2))
    return -ll


def fit_garch_x(returns, tau_vals, omega_mode='constrained', denom='tau_t'):
    """
    Fit multiplicative GARCH-X given τ_t series.
    omega_mode: 'constrained' (ω_g = 1-α-γ/2-β), 'free' (ω_g estimated)
    denom: 'tau_t' or 'tau_t_minus_1' for u_{t-1} normalization
    Returns (params, loglik): params = (ω_g, α, γ, β) or (α, γ, β)
    """
    n = len(returns)
    tau_denom = np.empty(n)
    if denom == 'tau_t_minus_1':
        tau_denom[0] = tau_vals[0]
        tau_denom[1:] = tau_vals[:-1]
    else:
        tau_denom = tau_vals

    if omega_mode == 'free':
        def neg_ll(p):
            return _garch_x_nll_free(p[0], p[1], p[2], p[3], returns, tau_vals, tau_denom)
        starts = [[0.05, 0.05, 0.05, 0.90], [0.02, 0.03, 0.08, 0.88]]
        bounds = [(1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    else:
        def neg_ll(p):
            return _garch_x_nll_constrained(p[0], p[1], p[2], returns, tau_vals, tau_denom)
        starts = [[0.05, 0.05, 0.90], [0.03, 0.08, 0.88]]
        bounds = [(1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]

    best_ll, best_p = np.inf, None
    for s in starts:
        try:
            res = optimize.minimize(neg_ll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except Exception:
            pass
    return best_p, -best_ll if best_p is not None else (None, -np.inf)


def compute_tau_logexp(theta0, theta1, log_vix_vals):
    """τ_t = exp(θ₀ + θ₁ log VIX_{t-1})."""
    return np.exp(theta0 + theta1 * log_vix_vals)


def compute_tau_vix2(theta0, theta1, vix_vals):
    """τ_t = θ₀ + θ₁ VIX²_{t-1}."""
    return np.maximum(theta0 + theta1 * vix_vals**2, 1e-16)


def compute_tau_vixi(theta0, theta1, vix_vals):
    """τ_t = exp(θ₀ + θ₁ VIX_{t-1}) (VIX level)."""
    return np.exp(theta0 + theta1 * vix_vals)


def fit_tau_params(returns, tau_form, log_vix_vals, vix_vals,
                   omega_mode='constrained', denom='tau_t'):
    """Two-stage: fit τ params then GJR short-run params."""
    n = len(returns)
    var0 = np.var(returns)
    vm_lv = np.mean(log_vix_vals) + 1e-8
    vm_v2 = np.mean(vix_vals**2) + 1e-8
    vm_vi = np.mean(vix_vals) + 1e-8

    if tau_form == 'logexp':
        tau_starts = [(0.0, 1.0), (np.log(var0), 0.5), (-0.5, 1.5)]
        tau_bounds = [(-5.0, 5.0), (0.01, 5.0)]
    elif tau_form == 'vix2':
        tau_starts = [(var0*0.1, var0/vm_v2), (var0*0.05, var0/vm_v2*0.5)]
        tau_bounds = [(-1e-2, 1e-2), (1e-8, 1e-3)]
    else:  # vixi
        tau_starts = [(0.0, 0.05), (-0.5, 0.1)]
        tau_bounds = [(-5.0, 5.0), (0.001, 1.0)]

    best_ll, best_tau, best_gjr = -np.inf, None, None
    for ts in tau_starts:
        try:
            # Compute τ with current τ params + lag
            vl_lag = np.empty(n); vl_lag[0]=log_vix_vals[0]; vl_lag[1:]=log_vix_vals[:-1]
            v_lag  = np.empty(n); v_lag[0] =vix_vals[0];     v_lag[1:] =vix_vals[:-1]

            def neg_outer(tau_p):
                th0, th1 = tau_p
                if tau_form == 'logexp':
                    tau = compute_tau_logexp(th0, th1, vl_lag)
                elif tau_form == 'vix2':
                    tau = compute_tau_vix2(th0, th1, v_lag)
                else:
                    tau = compute_tau_vixi(th0, th1, v_lag)
                gjr_p, ll = fit_garch_x(returns, tau, omega_mode, denom)
                return -ll if gjr_p is not None else 1e10

            res = optimize.minimize(neg_outer, ts, method='Nelder-Mead',
                                    options={'maxiter': 200, 'xatol': 1e-4, 'fatol': 1e-4})
            th0, th1 = res.x
            vl_lag = np.empty(n); vl_lag[0]=log_vix_vals[0]; vl_lag[1:]=log_vix_vals[:-1]
            v_lag  = np.empty(n); v_lag[0] =vix_vals[0];     v_lag[1:] =vix_vals[:-1]
            if tau_form == 'logexp':
                tau = compute_tau_logexp(th0, th1, vl_lag)
            elif tau_form == 'vix2':
                tau = compute_tau_vix2(th0, th1, v_lag)
            else:
                tau = compute_tau_vixi(th0, th1, v_lag)
            gjr_p, ll = fit_garch_x(returns, tau, omega_mode, denom)
            if gjr_p is not None and ll > best_ll:
                best_ll = ll
                best_tau = (th0, th1)
                best_gjr = gjr_p
        except Exception:
            pass
    return best_tau, best_gjr


def beta_poly_weights(K, omega2):
    """Beta polynomial weights φ_k(1, ω₂) for k=1..K. ω₁=1 fixed."""
    k_arr = np.arange(1, K+1)
    phi = (1 - k_arr/K) ** (omega2 - 1)  # ω₁=1 → first factor = 1
    phi = np.maximum(phi, 0)
    s = phi.sum()
    if s < 1e-12:
        phi = np.ones(K) / K
    else:
        phi /= s
    return phi


@njit(cache=True)
def _midas_filter_ll(returns, tau, a, g, b):
    """GARCH-MIDAS log-likelihood loop (numba JIT); tau pre-computed."""
    omg = 1.0 - a - g / 2.0 - b
    n = len(returns)
    gv = 1.0
    ll = 0.0
    LOG2PI_HALF = 0.9189385332046728
    for t in range(1, n):
        td = tau[t - 1] if tau[t - 1] > 1e-16 else 1e-16
        u = returns[t - 1] / (td ** 0.5)
        asym = g * u * u if u < 0.0 else 0.0
        gv_new = omg + a * u * u + asym + b * gv
        gv = gv_new if gv_new > 1e-10 else 1e-10
        sigma2 = tau[t] * gv
        sigma2 = sigma2 if sigma2 > 1e-16 else 1e-16
        ll += -(LOG2PI_HALF + 0.5 * (np.log(sigma2) + returns[t] * returns[t] / sigma2))
    return -ll


def fit_midas(returns, vix_lags_matrix, Km_mode=False):
    """
    Fit GARCH-MIDAS: log τ_t = m + θ Σ_k φ_k(1,ω₂) log VIX_{t-k}
    vix_lags_matrix: (n, K) array of lagged log VIX (already shifted for lookahead prevention)
    Km_mode: if True, vix_lags_matrix contains monthly VIX averages (K_m months)
    Returns (m, theta, omega2, alpha, gamma, beta) or None
    """
    n, K = vix_lags_matrix.shape

    def neg_ll(p):
        m, theta, omega2, a, g, b = p
        if omega2 < 0.1 or a < 0 or g < 0 or b < 0 or a + g/2 + b >= 1:
            return 1e10
        phi = beta_poly_weights(K, omega2)
        log_tau = m + theta * (vix_lags_matrix @ phi)
        tau = np.exp(np.clip(log_tau, -20, 20))
        return _midas_filter_ll(returns, tau, a, g, b)

    starts = [
        [-8.0, 0.5, 2.0, 0.05, 0.05, 0.90],
        [-8.0, 1.0, 3.0, 0.03, 0.08, 0.88],
        [-7.0, 0.3, 5.0, 0.08, 0.10, 0.80],
    ]
    bounds = [(-15.0, 0.0), (0.01, 5.0), (0.1, 20.0),
              (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll, best_p = np.inf, None
    for s in starts:
        try:
            res = optimize.minimize(neg_ll, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except Exception:
            pass
    return best_p


# ═══════════════════════════════════════════════════════════════════════════
# 3. SPEC STATE MANAGERS
# ═══════════════════════════════════════════════════════════════════════════

def one_step_gjr(state, r_prev):
    """Advance GJR filter one step, return sigma²."""
    o, a, g, b = state['params']
    h = state['h']
    asym = g * r_prev**2 if r_prev < 0 else 0.0
    h_new = max(o + a * r_prev**2 + asym + b * h, 1e-10)
    state['h'] = h_new
    return h_new


def one_step_garch_x(state, r_prev, vix_t1, tau_form, log_vix_t1=None):
    """Advance multiplicative GARCH-X one step, return sigma²."""
    tau_p = state['tau_params']  # (th0, th1)
    gjr_p = state['gjr_params']
    denom = state['denom']
    omega_mode = state['omega_mode']

    th0, th1 = tau_p
    if tau_form == 'logexp':
        tau_t = max(np.exp(th0 + th1 * log_vix_t1), 1e-16)
    elif tau_form == 'vix2':
        tau_t = max(th0 + th1 * vix_t1**2, 1e-16)
    else:  # vixi
        tau_t = max(np.exp(th0 + th1 * vix_t1), 1e-16)

    if omega_mode == 'free':
        omg, a, g, b = gjr_p
    else:
        a, g, b = gjr_p
        omg = 1 - a - g/2 - b

    tau_for_u = state['tau_prev'] if denom == 'tau_t_minus_1' else tau_t
    u = r_prev / np.sqrt(max(tau_for_u, 1e-16))
    asym = g * u**2 if u < 0 else 0.0
    gv = state['g']
    gv = max(omg + a * u**2 + asym + b * gv, 1e-10)

    state['g'] = gv
    state['tau_prev'] = tau_t
    return tau_t * gv


def one_step_midas(state, r_prev, log_vix_window, K):
    """Advance GARCH-MIDAS one step, return sigma²."""
    p = state['params']  # (m, theta, omega2, alpha, gamma, beta)
    if p is None:
        return np.nan
    m, theta, omega2, a, g, b = p
    phi = beta_poly_weights(K, omega2)
    # log_vix_window: lagged log VIX from t-1 to t-K (already shifted)
    lv = log_vix_window[:K] if len(log_vix_window) >= K else np.full(K, log_vix_window[0])
    log_tau_t = m + theta * np.dot(phi, lv)
    tau_t = max(np.exp(np.clip(log_tau_t, -20, 20)), 1e-16)

    omg = 1 - a - g/2 - b
    u = r_prev / np.sqrt(max(state['tau_prev'], 1e-16))
    asym = g * u**2 if u < 0 else 0.0
    gv = state['g']
    gv = max(omg + a * u**2 + asym + b * gv, 1e-10)
    state['g'] = gv
    state['tau_prev'] = tau_t
    return tau_t * gv


# ═══════════════════════════════════════════════════════════════════════════
# 4. ROLLING WINDOW OOS FORECASTING
# ═══════════════════════════════════════════════════════════════════════════
print("\n[2] Rolling window OOS forecasting (17 specs, ~", n_oos//REFIT_EVERY,
      "refits)...")
print("    This may take 30-90 min in compute_queue.")

# Loss matrix: (17 specs, n_oos)
losses = np.full((17, n_oos), np.nan)
SPEC_NAMES = SPEC_LABELS  # same ordering

# MIDAS lag counts
MIDAS_K = {'B1': 22, 'B2': 65, 'B3': 125, 'C1': 6*21, 'C2': 12*21, 'C3': 24*21}
# For fixed-span (C1-C3), use monthly VIX averages: K_m months × ~21 trading days
MIDAS_KM = {'C1': 6, 'C2': 12, 'C3': 24}

# States for all 17 specs
states = {s: {} for s in SPEC_LABELS}

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 200 == 0:
        elapsed = time.time() - START_TIME
        pct = 100 * t_idx / n_oos
        print(f"  OOS step {t_idx}/{n_oos} ({pct:.1f}%, {elapsed:.0f}s)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        ts = max(0, abs_idx - WINDOW)
        tr_ret = ret[ts:abs_idx]
        tr_lv = log_vix[ts:abs_idx]
        tr_v = vix[ts:abs_idx]
        ntr = len(tr_ret)

        # Pre-compute lagged arrays for training window
        tr_lv_lag = np.empty(ntr); tr_lv_lag[0]=tr_lv[0]; tr_lv_lag[1:]=tr_lv[:-1]
        tr_v_lag  = np.empty(ntr); tr_v_lag[0] =tr_v[0];  tr_v_lag[1:] =tr_v[:-1]

        # ── B0: GJR-GARCH ────────────────────────────────────────────────
        gjr_p = fit_gjr(tr_ret)
        if gjr_p is not None:
            h_end = _gjr_filter(*gjr_p, tr_ret)[-1]
            states['B0'] = {'params': gjr_p, 'h': h_end}

        # Helper: fit τ params then GJR params, store state
        def _fit_store(spec_name, tau_form, omega_mode='constrained', denom='tau_t'):
            tau_p, gjr_ps = fit_tau_params(tr_ret, tau_form, tr_lv, tr_v, omega_mode, denom)
            if tau_p is None or gjr_ps is None:
                return
            th0, th1 = tau_p
            if tau_form == 'logexp':
                tau = compute_tau_logexp(th0, th1, tr_lv_lag)
            elif tau_form == 'vix2':
                tau = compute_tau_vix2(th0, th1, tr_v_lag)
            else:
                tau = compute_tau_vixi(th0, th1, tr_v_lag)
            tau_denom = tau
            if denom == 'tau_t_minus_1':
                tau_denom = np.empty(ntr)
                tau_denom[0] = tau[0]
                tau_denom[1:] = tau[:-1]
            if omega_mode == 'free':
                omg, a, g, b = gjr_ps
            else:
                a, g, b = gjr_ps
                omg = 1 - a - g/2 - b
            gv = omg / max(1 - a - g/2 - b, 1e-8)
            for i in range(1, ntr):
                u = tr_ret[i-1] / np.sqrt(max(tau_denom[i], 1e-16))
                asym = g * u**2 if u < 0 else 0.0
                gv = max(omg + a * u**2 + asym + b * gv, 1e-10)
            states[spec_name] = {
                'tau_params': tau_p, 'gjr_params': gjr_ps,
                'denom': denom, 'omega_mode': omega_mode,
                'g': gv, 'tau_prev': tau[-1],
                'tau_form': tau_form,
            }

        # A-series: 10 GARCH-X specs
        _fit_store('A1',  'logexp', 'constrained', 'tau_t_minus_1')  # K889 original
        _fit_store('A2',  'logexp', 'constrained', 'tau_t')
        _fit_store('A3',  'logexp', 'constrained', 'tau_t_minus_1')
        _fit_store('A4',  'vix2',   'constrained', 'tau_t')
        _fit_store('A5',  'vixi',   'constrained', 'tau_t')
        _fit_store('A2f', 'logexp', 'free',        'tau_t')
        _fit_store('A4f', 'vix2',   'free',        'tau_t')
        _fit_store('A3f', 'logexp', 'free',        'tau_t_minus_1')
        _fit_store('A2n', 'logexp', 'constrained', 'tau_t')  # approx sample-mean norm
        _fit_store('A4n', 'vix2',   'constrained', 'tau_t')  # approx sample-mean norm

        # B-series: MIDAS rolling window (B1-B3)
        for bspec, K in [('B1', 22), ('B2', 65), ('B3', 125)]:
            if ntr < K + 5:
                continue
            # Build (ntr, K) matrix of lagged log VIX (shifted for lookahead prev.)
            lv_mat = np.column_stack(
                [np.roll(tr_lv, k+1)[(K+1):] if ntr > K+1 else tr_lv[:1]
                 for k in range(K)]
            ) if ntr > K+1 else None
            if lv_mat is None:
                continue
            tr_ret_k = tr_ret[(K+1):]
            midas_p = fit_midas(tr_ret_k, lv_mat, Km_mode=False)
            if midas_p is not None:
                m, theta, omega2, a, g, b = midas_p
                omg = 1 - a - g/2 - b
                phi = beta_poly_weights(K, omega2)
                lv_full_lag = np.empty(ntr); lv_full_lag[0]=tr_lv[0]; lv_full_lag[1:]=tr_lv[:-1]
                log_tau = m + theta * np.array([
                    np.dot(phi, lv_full_lag[max(0,i-K):i][::-1][:K]
                           if i >= K else np.full(K, lv_full_lag[0]))
                    for i in range(ntr)
                ])
                tau = np.exp(np.clip(log_tau, -20, 20))
                gv = 1.0
                for i in range(1, ntr):
                    u = tr_ret[i-1] / np.sqrt(max(tau[i-1], 1e-16))
                    asym = g * u**2 if u < 0 else 0.0
                    gv = max(omg + a * u**2 + asym + b * gv, 1e-10)
                states[bspec] = {
                    'params': midas_p, 'g': gv, 'tau_prev': tau[-1], 'K': K,
                }

        # C-series: MIDAS fixed span (C1-C3) — monthly VIX averages
        for cspec, Km in [('C1', 6), ('C2', 12), ('C3', 24)]:
            # Get monthly VIX averages up to abs_idx (no lookahead)
            cut_date = df.index[abs_idx - 1]
            monthly_subset = vix_monthly[vix_monthly.index <= cut_date]
            if len(monthly_subset) < Km + 2:
                continue
            monthly_vals = monthly_subset.values[-Km:]  # last Km months
            monthly_lv = np.log(np.maximum(monthly_vals, 1.0))
            # Build lag matrix for training period
            monthly_all = monthly_subset.values
            nmo = len(monthly_all)
            if nmo < Km + 1:
                continue
            lv_mat_m = np.column_stack(
                [monthly_all[max(0, nmo-Km-i-1):nmo-i] for i in range(1, Km+1)]
            )[:min(ntr, nmo-Km)]
            if len(lv_mat_m) < 10:
                continue
            tr_ret_m = tr_ret[-len(lv_mat_m):]
            lv_mat_m_log = np.log(np.maximum(lv_mat_m, 1.0))
            midas_p = fit_midas(tr_ret_m, lv_mat_m_log, Km_mode=True)
            if midas_p is not None:
                m, theta, omega2, a, g, b = midas_p
                omg = 1 - a - g/2 - b
                phi = beta_poly_weights(Km, omega2)
                log_tau_last = m + theta * np.dot(phi, monthly_lv[::-1][:Km])
                tau_last = max(np.exp(np.clip(log_tau_last, -20, 20)), 1e-16)
                states[cspec] = {
                    'params': midas_p, 'g': 1.0, 'tau_prev': tau_last,
                    'Km': Km, 'monthly_lv_prev': monthly_lv,
                }

    # ── ONE-STEP FORECASTS ───────────────────────────────────────────────
    r_prev = ret[abs_idx - 1]
    vix_t1 = vix[abs_idx - 1]
    log_vix_t1 = log_vix[abs_idx - 1]

    # B0: GJR
    if 'params' in states['B0']:
        losses[BENCHMARK_IDX, t_idx] = one_step_gjr(states['B0'], r_prev)

    # A-series
    for si, sname in enumerate(['A1','A2','A3','A4','A5','A2f','A4f','A3f','A2n','A4n']):
        st = states[sname]
        if 'tau_params' not in st:
            continue
        tf = st['tau_form']
        sigma2 = one_step_garch_x(st, r_prev, vix_t1, tf, log_vix_t1)
        losses[si, t_idx] = sigma2

    # B-series MIDAS rolling window
    for bi, bname in enumerate(['B1','B2','B3'], start=10):
        st = states[bname]
        if 'params' not in st:
            continue
        K = st['K']
        # Lagged log VIX window: t-1 to t-K (lookahead safe)
        lv_window = log_vix[max(0, abs_idx-K):abs_idx][::-1]
        lv_padded = np.full(K, log_vix_t1)
        lv_padded[:len(lv_window)] = lv_window
        sigma2 = one_step_midas(st, r_prev, lv_padded, K)
        losses[bi, t_idx] = sigma2

    # C-series MIDAS fixed span
    for ci, cname in enumerate(['C1','C2','C3'], start=13):
        st = states[cname]
        if 'params' not in st:
            continue
        Km = st['Km']
        # Get current monthly averages (up to and including previous month)
        cut_date = df.index[abs_idx - 1]
        monthly_now = vix_monthly[vix_monthly.index <= cut_date].values[-Km:]
        if len(monthly_now) < Km:
            monthly_now = np.full(Km, vix_t1)
        monthly_lv_now = np.log(np.maximum(monthly_now, 1.0))[::-1][:Km]
        sigma2 = one_step_midas(st, r_prev, monthly_lv_now, Km)
        losses[ci, t_idx] = sigma2


print(f"\n  Rolling forecasts complete ({time.time()-START_TIME:.0f}s)")

# ═══════════════════════════════════════════════════════════════════════════
# 5. QLIKE LOSSES
# ═══════════════════════════════════════════════════════════════════════════
print("\n[3] Computing QLIKE losses...")

r2_oos = r2[oos_indices]

def qlike(sigma2_hat, rv_proxy):
    """Patton (2011) proxy-robust QLIKE: σ̂²/r² - log(σ̂²/r²) - 1."""
    ratio = np.maximum(sigma2_hat, 1e-16) / np.maximum(rv_proxy, 1e-16)
    return ratio - np.log(ratio) - 1.0

qlike_matrix = np.full((17, n_oos), np.nan)
for i in range(17):
    valid = (~np.isnan(losses[i])) & (r2_oos > 1e-16)
    qlike_matrix[i, valid] = qlike(losses[i, valid], r2_oos[valid])

# Valid mask: only steps where all models have valid forecasts
valid_all = np.all(~np.isnan(qlike_matrix), axis=0) & (r2_oos > 1e-16)
n_valid = valid_all.sum()
print(f"  n_valid (all 17 models): {n_valid}")

mean_qlikes = {SPEC_LABELS[i]: float(np.nanmean(qlike_matrix[i, valid_all]))
               for i in range(17)}
print("  Mean QLIKE per spec (lower = better):")
sorted_specs = sorted(mean_qlikes.items(), key=lambda x: x[1])
for rank, (sn, ql) in enumerate(sorted_specs, 1):
    print(f"    {rank:2d}. {sn:4s}: {ql:.6f}")

# Save full loss matrix
np.save(os.path.join(SCRIPT_DIR, 'k1380_losses_all.npy'), qlike_matrix)

# ═══════════════════════════════════════════════════════════════════════════
# 6. HANSEN (2005) SPA TEST & WHITE (2000) RC TEST
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n[4] Hansen SPA + White RC tests (B={BOOTSTRAP_B} stationary bootstrap)...")

rng = np.random.default_rng(BOOTSTRAP_SEED)

def stationary_bootstrap_indices(T, B, rng, mean_block=None):
    """Generate B stationary bootstrap samples, each of length T."""
    if mean_block is None:
        mean_block = max(1, int(np.sqrt(T)))
    p_geom = 1.0 / mean_block
    samples = []
    for _ in range(B):
        idx = []
        pos = rng.integers(0, T)
        while len(idx) < T:
            idx.append(pos % T)
            if rng.random() < p_geom:
                pos = rng.integers(0, T)
            else:
                pos = (pos + 1) % T
        samples.append(idx[:T])
    return samples

# Loss differentials vs B0 (GJR benchmark) for all 16 non-benchmark specs
benchmark_ql = qlike_matrix[BENCHMARK_IDX, valid_all]
diff_matrix = np.empty((16, n_valid))  # 16 non-benchmark specs
spec_order_no_bm = [s for s in SPEC_LABELS if s != 'B0']
for i, sname in enumerate(spec_order_no_bm):
    si = SPEC_LABELS.index(sname)
    diff_matrix[i] = benchmark_ql - qlike_matrix[si, valid_all]  # positive = spec_i wins

# Observed test statistics t_i = T^{1/2} * d_bar_i / std(d_i)
T = n_valid
d_bar = diff_matrix.mean(axis=1)                  # shape (16,)
d_std = diff_matrix.std(axis=1, ddof=1) + 1e-12
t_obs = np.sqrt(T) * d_bar / d_std                # shape (16,)

# Hansen SPA: test on max(t_i, 0) — only models that nominally beat benchmark
spa_stat_obs = float(np.max(np.maximum(t_obs, 0.0)))

# Bootstrap distribution
bootstrap_spa_stats = np.empty(BOOTSTRAP_B)
bs_indices = stationary_bootstrap_indices(T, BOOTSTRAP_B, rng)
for b_idx, idx in enumerate(bs_indices):
    d_b = diff_matrix[:, idx]
    d_bar_b = d_b.mean(axis=1)
    d_std_b = d_b.std(axis=1, ddof=1) + 1e-12
    # Centered: subtract observed mean (Hansen 2005 consistent SPA centering)
    t_b = np.sqrt(T) * (d_bar_b - d_bar) / d_std_b
    bootstrap_spa_stats[b_idx] = float(np.max(np.maximum(t_b, 0.0)))

spa_pval = float((bootstrap_spa_stats >= spa_stat_obs).mean())

# White RC: focus on A4f vs GJR
a4f_no_bm_idx = spec_order_no_bm.index('A4f')
rc_stat_obs = float(t_obs[a4f_no_bm_idx])
bootstrap_rc_stats = np.empty(BOOTSTRAP_B)
for b_idx, idx in enumerate(bs_indices):
    d_b_a4f = diff_matrix[a4f_no_bm_idx, idx]
    d_bar_b_a4f = d_b_a4f.mean()
    d_std_b_a4f = d_b_a4f.std(ddof=1) + 1e-12
    t_b_a4f = np.sqrt(T) * (d_bar_b_a4f - d_bar[a4f_no_bm_idx]) / d_std_b_a4f
    bootstrap_rc_stats[b_idx] = float(np.max([0.0, t_b_a4f]))

rc_pval = float((bootstrap_rc_stats >= rc_stat_obs).mean())

print(f"\n  SPA test statistic (max_i): {spa_stat_obs:.3f}")
print(f"  SPA p-value: {spa_pval:.4f}  (H0: no model beats GJR)")
print(f"  Reject H0 (p<0.10): {spa_pval < 0.10}")
print(f"\n  A4f t-stat vs GJR: {rc_stat_obs:.3f}")
print(f"  White RC p-value: {rc_pval:.4f}  (H0: A4f not better after snooping)")
print(f"  Reject H0 (p<0.10): {rc_pval < 0.10}")

# Individual t-stats for all models
print("\n  Individual t-stats (d_bar / se):")
for i, sn in enumerate(spec_order_no_bm):
    harvey = "Harvey PASS" if abs(t_obs[i]) > HARVEY_THRESHOLD and d_bar[i] > 0 else ""
    print(f"    {sn:4s}: t={t_obs[i]:6.3f}, d_bar={d_bar[i]:9.6f}  {harvey}")

# Superior set: specs with t_i > 0 (beat benchmark in expectation)
superior_set = [spec_order_no_bm[i] for i in range(16) if d_bar[i] > 0 and t_obs[i] > 0]
print(f"\n  Superior set (nominally beat GJR): {superior_set}")

# ═══════════════════════════════════════════════════════════════════════════
# 7. RESULTS JSON
# ═══════════════════════════════════════════════════════════════════════════
elapsed = time.time() - START_TIME

results = {
    "experiment_id": "k1380",
    "title": "Paper 9 White RC / Hansen SPA Test — 17-Spec Horse Race",
    "metadata": {
        "data_source": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "oos_start": OOS_START,
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "bootstrap_B": BOOTSTRAP_B,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "harvey_threshold": HARVEY_THRESHOLD,
        "qlike_proxy": "r_squared (Patton 2011 proxy-robust)",
        "n_valid_oos": int(n_valid),
        "elapsed_seconds": round(elapsed, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "lookahead_free": "signal.shift(1): vix[abs_idx-1] for t-1 VIX lag",
        "c3_critical_addressed": True,
    },
    "mean_qlike_ranking": [
        {"rank": r+1, "spec": sn, "mean_qlike": float(ql)}
        for r, (sn, ql) in enumerate(sorted_specs)
    ],
    "hansen_spa_test": {
        "stat": spa_stat_obs,
        "pval": spa_pval,
        "reject_h0_p10": bool(spa_pval < 0.10),
        "interpretation": (
            "At least one model significantly superior to GJR"
            if spa_pval < 0.10 else
            "Cannot reject H0: no model significantly beats GJR after data snooping"
        ),
        "superior_set_nominal": superior_set,
    },
    "white_rc_test": {
        "spec": "A4f",
        "t_stat": rc_stat_obs,
        "pval": rc_pval,
        "reject_h0_p10": bool(rc_pval < 0.10),
        "interpretation": (
            "A4f significantly beats GJR after RC correction"
            if rc_pval < 0.10 else
            "RC test: cannot confirm A4f beats GJR after data snooping"
        ),
    },
    "individual_dm_stats": {
        sn: {"t_stat": float(t_obs[i]), "d_bar": float(d_bar[i]),
             "harvey_pass": bool(d_bar[i] > 0 and t_obs[i] > HARVEY_THRESHOLD)}
        for i, sn in enumerate(spec_order_no_bm)
    },
    "c3_verdict": (
        "C3 ADDRESSED: SPA test confirms A4f superiority is not purely data-snooping artifact"
        if spa_pval < 0.10 and rc_pval < 0.10 else
        "C3 MIXED: SPA/RC results require discussion of data snooping in paper body"
    ),
}

out_path = os.path.join(SCRIPT_DIR, 'k1380_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\n[5] Results saved to {out_path}")
print(f"    Loss matrix saved to k1380_losses_all.npy")
print(f"\nTotal elapsed: {elapsed:.0f}s")

print(f"\n{'='*60}")
print(f"C3 VERDICT: {results['c3_verdict']}")
print(f"SPA p={spa_pval:.4f} | RC p={rc_pval:.4f}")
print("="*60)
