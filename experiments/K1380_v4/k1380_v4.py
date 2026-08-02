#!/usr/bin/env python3
"""
K1380_v4 — Paper 9 17-Spec Horse-Race Loss Generation
=======================================================
3-STRIKE REFACTOR of K1380 (three failures with n_valid=0 from joint mask).

Root-cause fixes applied in v4:
  1. Per-model valid_i masks (was: joint mask → n_valid=0 when any MIDAS fails)
  2. Joint diagnostic restricted to specs with coverage >= 95%
  3. Non-NaN coverage diagnostics printed per spec (was: single aggregate print)
  4. MIDAS B-series lag matrix: proper column-by-column construction (no np.roll)
     np.roll wraps around → contaminates first rows; replaced with slicing.

Success criteria: n_valid_spa > 1500, ≥12/17 models with coverage ≥ 95%.
Output: k1380_v4_results.json + k1380_v4_losses_all.npy
"""

import json
import os
import time
import warnings

import numpy as np
import pandas as pd
from numba import njit

from volpred.models.garch.fixed_span_midas import (
    fit_fixed_span_garch_midas,
    fixed_span_log_vix_lags,
    forecast_fixed_span_garch_midas,
)
from volpred.research.optimization import bounded_multistart_minimize

warnings.filterwarnings('ignore')
np.random.seed(42)
START_TIME = time.time()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

if os.environ.get("K1380_PIPELINE_CHILD") != "1":
    raise SystemExit(
        "K1380_v4 has one canonical entrypoint: run_pipeline.py. "
        "Run that file so model fitting and inference receive one full-chain spec."
    )


def _atomic_write_json(path, payload):
    temporary = f"{path}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _atomic_save_npy(path, array):
    temporary = f"{path}.tmp"
    try:
        with open(temporary, "wb") as handle:
            np.save(handle, array)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

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
print("K1380_v4: 17-Spec Horse-Race Loss Generation (3-Strike Fix)")
print("=" * 70)

# ═══════════════════════════════════════════════════════════════════════════
# 1. DATA LOADING
# ═══════════════════════════════════════════════════════════════════════════
print("\n[1] Loading snapshot CSV...")
df_raw = pd.read_csv(SNAPSHOT_CSV, parse_dates=['date'], index_col='date')
df_raw.index = pd.to_datetime(df_raw.index)
df_raw = df_raw.sort_index()
duplicate_date_rows = int(df_raw.index.duplicated(keep='last').sum())
if duplicate_date_rows:
    print(f"  WARNING: dropped {duplicate_date_rows} duplicate date rows from snapshot (kept last)")
    df_raw = df_raw[~df_raw.index.duplicated(keep='last')]

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
    try:
        fit = bounded_multistart_minimize(
            neg_ll, starts=starts, bounds=bounds,
            options={'maxiter': 500},
        )
    except RuntimeError:
        return None
    return fit.params


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

    try:
        fit = bounded_multistart_minimize(
            neg_ll, starts=starts, bounds=bounds,
            options={'maxiter': 500},
        )
    except RuntimeError:
        return None, -np.inf
    return fit.params, -fit.objective


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
    vm_v2 = np.mean(vix_vals**2) + 1e-8
    vl_lag = np.empty(n); vl_lag[0]=log_vix_vals[0]; vl_lag[1:]=log_vix_vals[:-1]
    v_lag  = np.empty(n); v_lag[0] =vix_vals[0];     v_lag[1:] =vix_vals[:-1]
    log_r2 = np.log(np.maximum(returns**2, 1e-16))

    if tau_form == 'logexp':
        theta_init = np.linalg.lstsq(
            np.column_stack([np.ones(n), vl_lag]), log_r2, rcond=None
        )[0]
        tau_starts = [theta_init, (np.log(var0), 0.5), (-12.0, 1.5)]
        tau_bounds = [(-20.0, 0.0), (0.01, 5.0)]
    elif tau_form == 'vix2':
        tau_starts = [(var0*0.1, var0/vm_v2), (var0*0.05, var0/vm_v2*0.5)]
        tau_bounds = [(-1e-2, 1e-2), (1e-8, 1e-3)]
    else:  # vixi
        theta_init = np.linalg.lstsq(
            np.column_stack([np.ones(n), v_lag]), log_r2, rcond=None
        )[0]
        tau_starts = [theta_init, (-12.0, 0.05), (-10.0, 0.1)]
        tau_bounds = [(-20.0, 0.0), (0.001, 1.0)]

    def neg_outer(tau_p):
        th0, th1 = tau_p
        if tau_form == 'logexp':
            tau = compute_tau_logexp(th0, th1, vl_lag)
        elif tau_form == 'vix2':
            tau = compute_tau_vix2(th0, th1, v_lag)
        else:
            tau = compute_tau_vixi(th0, th1, v_lag)
        if not np.all(np.isfinite(tau)):
            return 1e10
        gjr_p, ll = fit_garch_x(returns, tau, omega_mode, denom)
        return -ll if gjr_p is not None and np.isfinite(ll) else 1e10

    try:
        outer = bounded_multistart_minimize(
            neg_outer,
            starts=tau_starts,
            bounds=tau_bounds,
            method='Nelder-Mead',
            options={'maxiter': 300, 'xatol': 1e-4, 'fatol': 1e-4},
        )
    except RuntimeError:
        return None, None
    th0, th1 = outer.params
    if tau_form == 'logexp':
        tau = compute_tau_logexp(th0, th1, vl_lag)
    elif tau_form == 'vix2':
        tau = compute_tau_vix2(th0, th1, v_lag)
    else:
        tau = compute_tau_vixi(th0, th1, v_lag)
    gjr_p, ll = fit_garch_x(returns, tau, omega_mode, denom)
    if gjr_p is None or not np.isfinite(ll):
        return None, None
    return tuple(outer.params), gjr_p


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
    _n, K = vix_lags_matrix.shape

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
    try:
        fit = bounded_multistart_minimize(
            neg_ll,
            starts=starts,
            bounds=bounds,
            options={'maxiter': 500},
        )
    except RuntimeError:
        return None
    return fit.params


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
fit_diagnostics = {
    s: [] for s in ('A5', 'B1', 'B2', 'B3', 'C1', 'C2', 'C3', 'B0')
}

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
        garch_x_fit_cache = {}

        # Pre-compute lagged arrays for training window
        tr_lv_lag = np.empty(ntr); tr_lv_lag[0]=tr_lv[0]; tr_lv_lag[1:]=tr_lv[:-1]
        tr_v_lag  = np.empty(ntr); tr_v_lag[0] =tr_v[0];  tr_v_lag[1:] =tr_v[:-1]

        # ── B0: GJR-GARCH ────────────────────────────────────────────────
        states['B0'] = {}
        gjr_p = fit_gjr(tr_ret)
        if gjr_p is not None:
            h_end = _gjr_filter(*gjr_p, tr_ret)[-1]
            states['B0'] = {'params': gjr_p, 'h': h_end}
            fit_diagnostics['B0'].append({
                'refit_date': str(df.index[abs_idx].date()),
                'n_training_daily': ntr,
                'params': [float(value) for value in gjr_p],
                'optimizer_contract': 'successful_finite_in_bounds',
            })
        else:
            fit_diagnostics['B0'].append({
                'refit_date': str(df.index[abs_idx].date()),
                'n_training_daily': ntr,
                'status': 'rejected',
                'reason': 'no successful finite in-bounds optimizer result',
            })

        # Helper: fit τ params then GJR params, store state
        def _fit_store(spec_name, tau_form, omega_mode='constrained', denom='tau_t'):
            # A rejected scheduled refit invalidates the prior state. Carrying the
            # previous window forward would silently turn fail-closed fitting back
            # into a stale-state fail-open path.
            states[spec_name] = {}
            fit_key = (tau_form, omega_mode, denom)
            if fit_key not in garch_x_fit_cache:
                garch_x_fit_cache[fit_key] = fit_tau_params(
                    tr_ret, tau_form, tr_lv, tr_v, omega_mode, denom
                )
            tau_p, gjr_ps = garch_x_fit_cache[fit_key]
            if tau_p is None or gjr_ps is None:
                if spec_name == 'A5':
                    fit_diagnostics['A5'].append({
                        'refit_date': str(df.index[abs_idx].date()),
                        'n_training_daily': ntr,
                        'status': 'rejected',
                        'reason': 'no successful finite in-bounds optimizer result',
                    })
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
            if spec_name == 'A5':
                fit_diagnostics['A5'].append({
                    'refit_date': str(df.index[abs_idx].date()),
                    'n_training_daily': ntr,
                    'tau_params': [float(value) for value in tau_p],
                    'short_run_params': [float(value) for value in gjr_ps],
                    'tau_min': float(np.min(tau)),
                    'tau_max': float(np.max(tau)),
                    'optimizer_contract': 'successful_finite_in_bounds',
                })

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
            states[bspec] = {}
            if ntr < K + 5:
                fit_diagnostics[bspec].append({
                    'refit_date': str(df.index[abs_idx].date()),
                    'n_training_daily': ntr,
                    'status': 'rejected',
                    'reason': f'insufficient history for K={K}',
                })
                continue
            # Build (ntr-K, K) lag matrix via slicing (FIX: np.roll wraps around,
            # contaminating first rows with tail data — use explicit slicing instead).
            # Row t of lv_mat = [tr_lv[t-1], tr_lv[t-2], ..., tr_lv[t-K]] for t=K..ntr-1
            # Column k (0-indexed lag k+1): tr_lv[K-1-k : ntr-1-k]
            if ntr <= K:
                continue
            lv_mat = np.column_stack([tr_lv[K-1-k:ntr-1-k] for k in range(K)])
            tr_ret_k = tr_ret[K:]  # align to rows K..ntr-1 (was K+1, off by one)
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
                fit_diagnostics[bspec].append({
                    'refit_date': str(df.index[abs_idx].date()),
                    'n_training_daily': ntr,
                    'params': [float(value) for value in midas_p],
                    'optimizer_contract': 'successful_finite_in_bounds',
                })
            else:
                fit_diagnostics[bspec].append({
                    'refit_date': str(df.index[abs_idx].date()),
                    'n_training_daily': ntr,
                    'status': 'rejected',
                    'reason': 'no successful finite in-bounds optimizer result',
                })

        # C-series: MIDAS fixed span (C1-C3) — monthly VIX averages
        for cspec, Km in [('C1', 6), ('C2', 12), ('C3', 24)]:
            states[cspec] = {}
            try:
                fixed_fit = fit_fixed_span_garch_midas(
                    returns=tr_ret,
                    return_dates=df.index[ts:abs_idx],
                    vix_history=vix[:abs_idx],
                    vix_history_dates=df.index[:abs_idx],
                    lag_months=Km,
                    min_observations=500,
                )
            except (RuntimeError, ValueError) as exc:
                fit_diagnostics[cspec].append({
                    'refit_date': str(df.index[abs_idx].date()),
                    'n_training_daily': ntr,
                    'status': 'rejected',
                    'reason': str(exc),
                })
                continue
            states[cspec] = {
                'params': fixed_fit.params,
                'g': fixed_fit.g_last,
                'tau_prev': fixed_fit.tau_last,
                'Km': Km,
            }
            fit_diagnostics[cspec].append({
                'refit_date': str(df.index[abs_idx].date()),
                'n_training_daily': ntr,
                'n_likelihood_daily': fixed_fit.n_observations,
                'params': [float(value) for value in fixed_fit.params],
                'optimizer_contract': 'successful_finite_in_bounds',
            })

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
        try:
            monthly_lv_now = fixed_span_log_vix_lags(
                history_vix=vix[:abs_idx],
                history_dates=df.index[:abs_idx],
                forecast_date=df.index[abs_idx],
                lag_months=Km,
            )
            forecast = forecast_fixed_span_garch_midas(
                params=st['params'],
                g_previous=st['g'],
                previous_return=r_prev,
                log_vix_lags=monthly_lv_now,
            )
        except ValueError:
            continue
        st['g'] = forecast.g
        st['tau_prev'] = forecast.tau
        losses[ci, t_idx] = forecast.variance


print(f"\n  Rolling forecasts complete ({time.time()-START_TIME:.0f}s)")

# ═══════════════════════════════════════════════════════════════════════════
# 5. QLIKE LOSSES
# ═══════════════════════════════════════════════════════════════════════════
print("\n[3] Computing QLIKE losses...")

r2_oos = r2[oos_indices]

def qlike(sigma2_hat, rv_proxy):
    """Patton (2011) proxy-robust QLIKE: r²/σ̂² - log(r²/σ̂²) - 1."""
    ratio = np.maximum(rv_proxy, 1e-16) / np.maximum(sigma2_hat, 1e-16)
    return ratio - np.log(ratio) - 1.0

qlike_matrix = np.full((17, n_oos), np.nan)
for i in range(17):
    valid = (~np.isnan(losses[i])) & (r2_oos > 1e-16)
    qlike_matrix[i, valid] = qlike(losses[i, valid], r2_oos[valid])

# FIX 1+3: Per-model valid masks + coverage diagnostics (was: joint valid_all → n_valid=0)
COV_THRESHOLD = 0.95
per_model_valid = {}
per_model_coverage = {}

print("\n  Per-model coverage diagnostics (FIX: per-model, not joint mask):")
for i, sn in enumerate(SPEC_LABELS):
    vi = ~np.isnan(qlike_matrix[i]) & (r2_oos > 1e-16)
    per_model_valid[sn] = vi
    cov = vi.sum() / n_oos
    per_model_coverage[sn] = cov
    eligible_mark = "✓" if cov >= COV_THRESHOLD else "✗"
    print(f"    {eligible_mark} {sn:4s}: n_valid={vi.sum():5d}, coverage={cov:.1%}, "
          f"NaN_count={int((~vi).sum())}")

# FIX 2: SPA test only for specs with coverage >= 95%
eligible_non_bm = [sn for sn in SPEC_LABELS
                   if sn != 'B0' and per_model_coverage[sn] >= COV_THRESHOLD]
b0_coverage = per_model_coverage['B0']
print(f"\n  B0 benchmark coverage: {b0_coverage:.1%}")
print(f"  Eligible specs (coverage >= {COV_THRESHOLD:.0%}): {eligible_non_bm}")
print(f"  Eligible count: {len(eligible_non_bm)} / 16 non-benchmark specs")

# Mean QLIKEs using each model's own valid mask
mean_qlikes = {sn: float(np.nanmean(qlike_matrix[SPEC_LABELS.index(sn),
                                                   per_model_valid[sn]]))
               for sn in SPEC_LABELS}
print("\n  Mean QLIKE per spec (own-mask nanmean, lower = better):")
sorted_specs = sorted(mean_qlikes.items(), key=lambda x: x[1])
for rank, (sn, ql) in enumerate(sorted_specs, 1):
    print(f"    {rank:2d}. {sn:4s}: {ql:.6f}")

# Save full loss matrix
_atomic_save_npy(os.path.join(SCRIPT_DIR, 'k1380_v4_losses_all.npy'), qlike_matrix)

# ═══════════════════════════════════════════════════════════════════════════
# 6. PRELIMINARY RAW-SCALE DIAGNOSTICS (NOT FORMAL SPA / RC)
# ═══════════════════════════════════════════════════════════════════════════
print(f"\n[4] Preliminary raw-scale diagnostics (B={BOOTSTRAP_B})...")

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

# FIX 2: Build SPA diff matrix using only eligible specs + intersection valid mask
# Intersection of B0 valid mask and all eligible-spec valid masks
if b0_coverage < COV_THRESHOLD:
    raise RuntimeError(
        f"B0 benchmark coverage {b0_coverage:.1%} < {COV_THRESHOLD:.0%}; "
        "cannot run SPA/RC test."
    )
if len(eligible_non_bm) < 2:
    raise RuntimeError(
        f"Only {len(eligible_non_bm)} eligible specs (coverage < {COV_THRESHOLD:.0%}); "
        "need ≥ 2 for SPA test."
    )

# Joint valid mask: intersection of B0 and all eligible spec valid masks
valid_spa = per_model_valid['B0'].copy()
for sn in eligible_non_bm:
    valid_spa &= per_model_valid[sn]
n_valid_spa = int(valid_spa.sum())
print(f"\n  n_valid for SPA test (intersection of B0 + {len(eligible_non_bm)} eligible): "
      f"{n_valid_spa}")
if n_valid_spa < 500:
    print(f"  WARNING: n_valid_spa={n_valid_spa} < 500; results unreliable.")

benchmark_ql = qlike_matrix[BENCHMARK_IDX, valid_spa]
n_elig = len(eligible_non_bm)
diff_matrix = np.empty((n_elig, n_valid_spa))
for i, sname in enumerate(eligible_non_bm):
    si = SPEC_LABELS.index(sname)
    diff_matrix[i] = benchmark_ql - qlike_matrix[si, valid_spa]  # positive = sname wins

# Observed test statistics
T = n_valid_spa
d_bar = diff_matrix.mean(axis=1)
d_std = diff_matrix.std(axis=1, ddof=1) + 1e-12
t_obs = np.sqrt(T) * d_bar / d_std

# This observation-SD statistic is retained only as a reproducibility diagnostic.
# The canonical correction script estimates a long-run bootstrap scale and performs
# the formal max-type inference.
legacy_joint_stat = float(np.max(np.maximum(t_obs, 0.0)))

bs_indices = stationary_bootstrap_indices(T, BOOTSTRAP_B, rng)
bootstrap_spa_stats = np.empty(BOOTSTRAP_B)
for b_idx, idx in enumerate(bs_indices):
    d_b = diff_matrix[:, idx]
    d_bar_b = d_b.mean(axis=1)
    d_std_b = d_b.std(axis=1, ddof=1) + 1e-12
    t_b = np.sqrt(T) * (d_bar_b - d_bar) / d_std_b
    bootstrap_spa_stats[b_idx] = float(np.max(np.maximum(t_b, 0.0)))

legacy_joint_empirical_p = float((bootstrap_spa_stats >= legacy_joint_stat).mean())

# White RC: focus on A4f vs GJR (only if A4f is eligible)
a4f_eligible = 'A4f' in eligible_non_bm
if a4f_eligible:
    a4f_elig_idx = eligible_non_bm.index('A4f')
    a4f_dm_stat = float(t_obs[a4f_elig_idx])
    bootstrap_rc_stats = np.empty(BOOTSTRAP_B)
    for b_idx, idx in enumerate(bs_indices):
        d_b_a4f = diff_matrix[a4f_elig_idx, idx]
        d_bar_b_a4f = d_b_a4f.mean()
        d_std_b_a4f = d_b_a4f.std(ddof=1) + 1e-12
        t_b_a4f = np.sqrt(T) * (d_bar_b_a4f - d_bar[a4f_elig_idx]) / d_std_b_a4f
        bootstrap_rc_stats[b_idx] = float(np.max([0.0, t_b_a4f]))
    a4f_dm_empirical_p = float((bootstrap_rc_stats >= a4f_dm_stat).mean())
else:
    a4f_dm_stat = float('nan')
    a4f_dm_empirical_p = float('nan')
    print("  WARNING: A4f not eligible; single-spec diagnostic skipped.")

print(f"\n  Raw-scale max diagnostic over {n_elig} specs: {legacy_joint_stat:.3f}")
print(f"  Empirical bootstrap tail fraction: {legacy_joint_empirical_p:.4f}")
if a4f_eligible:
    print(f"\n  A4f raw-scale t diagnostic vs GJR: {a4f_dm_stat:.3f}")
    print(f"  Single-spec empirical bootstrap tail fraction: {a4f_dm_empirical_p:.4f}")

print("\n  Individual t-stats for eligible specs:")
for i, sn in enumerate(eligible_non_bm):
    harvey = " Harvey PASS" if abs(t_obs[i]) > HARVEY_THRESHOLD and d_bar[i] > 0 else ""
    print(f"    {sn:4s}: t={t_obs[i]:6.3f}, d_bar={d_bar[i]:9.6f}{harvey}")

# Ineligible specs: report separately (own-mask statistics)
ineligible_non_bm = [sn for sn in SPEC_LABELS if sn != 'B0'
                     and per_model_coverage[sn] < COV_THRESHOLD]
if ineligible_non_bm:
    print(f"\n  Ineligible specs (coverage < {COV_THRESHOLD:.0%}, excluded from SPA):")
    for sn in ineligible_non_bm:
        print(f"    {sn:4s}: coverage={per_model_coverage[sn]:.1%} (excluded)")

superior_set = [eligible_non_bm[i] for i in range(n_elig)
                if d_bar[i] > 0 and t_obs[i] > 0]
print(f"\n  Superior set (nominally beat GJR among eligible): {superior_set}")

# ═══════════════════════════════════════════════════════════════════════════
# 7. RESULTS JSON
# ═══════════════════════════════════════════════════════════════════════════
elapsed = time.time() - START_TIME

results = {
    "experiment_id": "k1380_v4",
    "title": "Paper 9 17-Spec Horse-Race Loss Generation (v4 3-Strike Fix)",
    "metadata": {
        "data_source": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "oos_start": OOS_START,
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "bootstrap_B": BOOTSTRAP_B,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "harvey_threshold": HARVEY_THRESHOLD,
        "qlike_proxy": "r_squared (Patton 2011 proxy-robust)",
        "qlike_formula": "actual_r2 / forecast_variance - log(actual_r2 / forecast_variance) - 1",
        "duplicate_snapshot_rows_dropped": duplicate_date_rows,
        "coverage_threshold": COV_THRESHOLD,
        "n_eligible_specs": len(eligible_non_bm),
        "eligible_specs": eligible_non_bm,
        "ineligible_specs": ineligible_non_bm,
        "n_valid_spa": n_valid_spa,
        "lookahead_free": "signal.shift(1): vix[abs_idx-1] for t-1 VIX lag",
        "canonical_inference": "k1380_v4_rc_correction_results.json",
        "v4_fixes": [
            "per-model valid_i masks (no joint mask)",
            "SPA restricted to coverage>=95% specs",
            "per-model NaN coverage diagnostics",
            "MIDAS B-series lag matrix via slicing (no np.roll)",
            "A-series tau fits are bounded and reject failed/non-finite optimizer results",
            "C-series likelihood aligns every daily return to prior completed-month VIX lags",
            "C-series state is filtered through the training tail and excludes partial current-month VIX",
        ],
    },
    "fit_diagnostics": fit_diagnostics,
    "per_model_coverage": {sn: {"n_valid": int(per_model_valid[sn].sum()),
                                 "coverage": round(per_model_coverage[sn], 4),
                                 "eligible": bool(per_model_coverage[sn] >= COV_THRESHOLD)}
                           for sn in SPEC_LABELS},
    "mean_qlike_ranking": [
        {"rank": r+1, "spec": sn, "mean_qlike": float(ql)}
        for r, (sn, ql) in enumerate(sorted_specs)
    ],
    "legacy_raw_scale_joint_diagnostic": {
        "stat": legacy_joint_stat,
        "empirical_tail_fraction": legacy_joint_empirical_p,
        "n_specs_tested": n_elig,
        "formal_spa": False,
        "warning": "Uses raw observation SD, not long-run variance; diagnostic only.",
        "superior_set_nominal": superior_set,
    },
    "a4f_single_spec_bootstrap_dm": {
        "spec": "A4f",
        "eligible": a4f_eligible,
        "t_stat": a4f_dm_stat,
        "empirical_tail_fraction": a4f_dm_empirical_p,
        "snooping_adjusted": False,
        "warning": "Single-spec diagnostic; not a max-type Reality Check.",
    },
    "individual_dm_stats": {
        sn: {"t_stat": float(t_obs[i]), "d_bar": float(d_bar[i]),
             "harvey_pass": bool(d_bar[i] > 0 and t_obs[i] > HARVEY_THRESHOLD),
             "included_in_spa": True}
        for i, sn in enumerate(eligible_non_bm)
    },
    "c3_status": "PENDING_CANONICAL_CORRECTION_ARTIFACT",
}

out_path = os.path.join(SCRIPT_DIR, 'k1380_v4_results.json')
_atomic_write_json(out_path, results)
print(f"\n[5] Results saved to {out_path}")
print("    Loss matrix saved to k1380_v4_losses_all.npy")
print(f"\nTotal elapsed: {elapsed:.0f}s")

print(f"\n{'='*60}")
print("C3 STATUS: use k1380_v4_rc_correction_results.json for canonical inference")
print("="*60)
