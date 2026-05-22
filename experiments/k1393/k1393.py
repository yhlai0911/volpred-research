#!/usr/bin/env python3
"""
K1393: Leave-COVID-out DM Test — A4f vs GJR (K988 spec faithful replication)
=============================================================================
Motivation:
  K1392 failed to verify K988's full-OOS DM t≈+4.0 due to three implementation
  bugs vs K988:
    (1) theta0 bounds: K1392 [0, var0*2] vs K988 [-1e-2, 1e-2]
    (2) theta1 bounds: K1392 [1e-10, 1.0] vs K988 [1e-8, 1e-3]
    (3) g initialization: K1392 h_g[0]=1.0 vs K988 g[0]=omega/(1-persist)
  K1393 uses K988's EXACT fit_mfgjr_x function (vix_squared, tau_t, free_omega=True)
  and state-based rolling forecast, then adds COVID subperiod masks.

Design:
  - A4f spec: tau_t = max(theta0 + theta1*VIX^2_{t-1}, eps), g follows GJR(1,1)
    with free omega, denom_mode='tau_t' (Engle et al. 2013)
  - Rolling OOS: W=2000, refit every 63 days (matches K988 protocol)
  - OOS: 2019-01-01 to 2026-04-07 (n≈1825, paper period)
  - COVID window: 2020-02-01 to 2020-06-30 (excluded in non-COVID analysis)
  - DM test: Newey-West HAC, Harvey et al. (2016) |t|>3.0 threshold

Verification gate:
  full_oos DM t should be ≈ +4.0 to +4.5 (K988 A4f_vix2_free_omega vs B0_GJR),
  confirming OOS match. If not, K1393 itself has a replication bug.

References:
  K988: original A4f vs GJR (full spec comparison, n=1825, DM t≈+4.48)
  K1391: first COVID test (wrong OOS end); K1392: second attempt (wrong bounds)
  paper/garch-x-vix C1 CRITICAL issue (COVID subperiod analysis)

Author: VolPred Research System
Date: 2026-05-22
Seed: 42
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import optimize

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1393"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1393_results.json')
DATA_PATH = os.path.join(PROJECT_ROOT, 'paper', 'garch-x-vix', 'data',
                          'spy_vix_qqq_eem_fez_2000-2026.csv')

# Configuration (mirrors K988 protocol + K1392 COVID masks)
OOS_START = '2019-01-01'
OOS_END = '2026-04-07'   # paper's stated OOS end
WINDOW = 2000
REFIT_EVERY = 63         # quarterly
COVID_START = '2020-02-01'
COVID_END = '2020-06-30'

print("=" * 70)
print(f"{EXPERIMENT_ID}: Leave-COVID-out DM Test — A4f vs GJR (K988 spec)")
print("  Paper 9 garch-x-vix C1 CRITICAL — K1392 bug-fix replication")
print("=" * 70)

# ============================================================
# DATA LOADING
# ============================================================
print("\n[1] Loading data...")
df_raw = pd.read_csv(DATA_PATH, parse_dates=['date'], index_col='date')
df_raw = df_raw.sort_index()

spy_prices = df_raw['spy_adj_close'].dropna()
vix_close = df_raw['vix_close'].dropna()
common_idx = spy_prices.index.intersection(vix_close.index)
spy_prices = spy_prices.loc[common_idx]
vix_close = vix_close.loc[common_idx]

log_ret = np.log(spy_prices / spy_prices.shift(1))
df = pd.DataFrame({'log_ret': log_ret, 'VIX': vix_close}).dropna()

oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} to {OOS_END}, n_oos={n_oos}")
print(f"  VIX OOS range: {df.loc[oos_mask, 'VIX'].min():.1f}–{df.loc[oos_mask, 'VIX'].max():.1f}")

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))

# ============================================================
# MODEL IMPLEMENTATIONS — EXACT K988 SPEC
# ============================================================
print("\n[2] Model definitions (K988-faithful)...")


# --- GJR-GARCH (same as K988) ---

def gjr_loglik(params, returns):
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = float(np.var(returns[:min(250, n)]))
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0.0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2.0 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    var0 = float(np.var(returns))
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-10, var0 * 0.5), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params if best_params is not None else np.array([var0 * 0.05, 0.05, 0.05, 0.90])


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f: tau = theta0 + theta1*VIX^2, free omega, denom_mode='tau_t' ---
# Exact replication of K988's fit_mfgjr_x(tau_func='vix_squared', denom_mode='tau_t', free_omega=True)

def fit_a4f_k988(returns, vix_vals):
    """
    K988-faithful A4f fit: vix_squared, tau_t denom, free_omega=True.
    Bounds and initialization exactly matching K988 fit_mfgjr_x.
    Uses L-BFGS-B optimizer (same as K988).
    """
    n = len(returns)
    var0 = float(np.var(returns))

    # Lagged VIX (same as K988: vix_lag = exp(log_vix_lag) for vix_squared)
    log_vix_vals = np.log(np.maximum(vix_vals, 1.0))
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]
    vix_lag = np.exp(log_vix_lag)   # actual VIX values, lagged by 1

    vix2_mean = float(np.mean(vix_lag**2)) + 1e-8

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
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
        # Initialize g at unconditional mean (K988 free_omega=True logic)
        g = np.empty(n)
        g[0] = eg
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(max(tau[t], 1e-16))   # denom_mode='tau_t'
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2.0 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    # K988 exact bounds for vix_squared, free_omega=True
    bounds = [
        (-1e-2, 1e-2),   # theta0  ← KEY: K1392 used (0, var0*2)
        (1e-8, 1e-3),    # theta1  ← KEY: K1392 used (1e-10, 1.0)
        (1e-6, 1.0),     # omega_g
        (1e-4, 0.3),     # alpha
        (1e-4, 0.3),     # gamma
        (0.5, 0.999),    # beta
    ]

    # K988 starting values
    starts = [
        [var0 * 0.1,  var0 / vix2_mean,       0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2,  var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]

    best_ll = np.inf
    best_params = None
    for s in starts:
        # Clip to bounds before passing
        s_clipped = [np.clip(s[i], bounds[i][0], bounds[i][1]) for i in range(6)]
        try:
            res = optimize.minimize(neg_loglik, s_clipped, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params


def a4f_get_g_state(params, returns, vix_vals):
    """
    Compute the final g state from training data (for state-based rolling).
    Matches K988's initialization and update logic.
    """
    n = len(returns)
    theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = params

    log_vix_vals = np.log(np.maximum(vix_vals, 1.0))
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]
    vix_lag = np.exp(log_vix_lag)
    tau_train = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

    persist = alpha_p + gamma_p / 2.0 + beta_p
    eg = omega_g / max(1.0 - persist, 1e-10)
    g = eg  # initialize at unconditional mean (K988 free_omega=True)
    tau_last = tau_train[-1]

    for i in range(1, n):
        u_prev = returns[i-1] / np.sqrt(max(tau_train[i], 1e-16))
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
        g = max(g, 1e-10)

    return g, tau_last


# ============================================================
# ROLLING OOS FORECASTING (state-based, matching K988)
# ============================================================
print("\n[3] Rolling OOS forecasting (state-based, K988 protocol)...")
print(f"  W={WINDOW}, refit every {REFIT_EVERY}, OOS={OOS_START} to {OOS_END}")

oos_indices = np.where(oos_mask)[0]
n_oos_total = len(oos_indices)
oos_dates = df.index[oos_indices]
print(f"  OOS observations: {n_oos_total}")

gjr_losses = np.full(n_oos_total, np.nan)
a4f_losses = np.full(n_oos_total, np.nan)

# State variables
gjr_state = {'params': None, 'h': None}
a4f_state = {'params': None, 'g': None, 'tau_prev': None}

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 300 == 0:
        elapsed = time.time() - START_TIME
        print(f"  Step {t_idx}/{n_oos_total} ({elapsed:.1f}s)")

    if abs_idx < WINDOW:
        continue

    # Refit at start and every REFIT_EVERY steps
    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0) or gjr_state['params'] is None

    if need_refit:
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # GJR refit
        gjr_p = fit_gjr(train_ret)
        if gjr_p is not None:
            gjr_state['params'] = gjr_p
            # Initialize h from end of training
            h = float(np.var(train_ret))
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_p, h, train_ret[i-1])
            gjr_state['h'] = h

        # A4f refit (K988-faithful)
        a4f_p = fit_a4f_k988(train_ret, train_vix)
        if a4f_p is not None:
            a4f_state['params'] = a4f_p
            g_last, tau_last = a4f_get_g_state(a4f_p, train_ret, train_vix)
            a4f_state['g'] = g_last
            a4f_state['tau_prev'] = tau_last

    # --- GJR forecast ---
    p_gjr = gjr_state['params']
    if p_gjr is not None and gjr_state['h'] is not None:
        r_prev = ret[abs_idx - 1]
        h_new = gjr_forecast_1step(p_gjr, gjr_state['h'], r_prev)
        gjr_losses[t_idx] = float(np.log(h_new) + ret[abs_idx]**2 / h_new)
        gjr_state['h'] = h_new

    # --- A4f forecast ---
    p_a4f = a4f_state['params']
    if p_a4f is not None and a4f_state['g'] is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = p_a4f
        # tau_t uses VIX_{t-1} (lagged, predetermined)
        vix_lag_t = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * vix_lag_t**2, 1e-16)

        r_prev = ret[abs_idx - 1]
        g_prev = a4f_state['g']
        # denom_mode='tau_t': u_{t-1} = r_{t-1} / sqrt(tau_t)
        u_prev = r_prev / np.sqrt(max(tau_t, 1e-16))
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = max(omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev, 1e-10)

        sigma2_forecast = tau_t * g_new
        a4f_losses[t_idx] = float(np.log(sigma2_forecast) + ret[abs_idx]**2 / sigma2_forecast)
        a4f_state['g'] = g_new
        a4f_state['tau_prev'] = tau_t

print(f"  Valid GJR losses: {np.sum(~np.isnan(gjr_losses))}")
print(f"  Valid A4f losses: {np.sum(~np.isnan(a4f_losses))}")

# Quick sanity: mean QLIKE levels
mask_valid = ~np.isnan(gjr_losses) & ~np.isnan(a4f_losses)
print(f"  Mean QLIKE GJR: {np.mean(gjr_losses[mask_valid]):.6f} (K988 ref: -8.277)")
print(f"  Mean QLIKE A4f: {np.mean(a4f_losses[mask_valid]):.6f} (K988 ref: -8.361)")

# ============================================================
# COVID SUBPERIOD MASKS
# ============================================================
print("\n[4] Subperiod masks...")

covid_start_dt = pd.Timestamp(COVID_START)
covid_end_dt = pd.Timestamp(COVID_END)

mask_full = mask_valid
mask_covid = (oos_dates >= covid_start_dt) & (oos_dates <= covid_end_dt) & mask_full
mask_non_covid = ~mask_covid & mask_full
mask_pre_covid = (oos_dates < covid_start_dt) & mask_full
mask_post_covid = (oos_dates > covid_end_dt) & mask_full

n_full = mask_full.sum()
n_covid = mask_covid.sum()
n_non_covid = mask_non_covid.sum()
n_pre = mask_pre_covid.sum()
n_post = mask_post_covid.sum()
print(f"  Full OOS: {n_full} | COVID: {n_covid} | Non-COVID: {n_non_covid} | Pre: {n_pre} | Post: {n_post}")

# ============================================================
# DM TESTS (Newey-West HAC, Harvey et al. 2016)
# ============================================================
print("\n[5] DM tests...")


def dm_test_hac(loss1, loss2):
    """
    DM test: d_t = loss1_t - loss2_t.
    Positive t → model 2 better (lower loss2).
    """
    d = loss1 - loss2
    n = len(d)
    if n < 10:
        return {'t_stat': np.nan, 'p_value': np.nan, 'mean_diff': float(np.mean(d)), 'n': n}
    d_mean = float(np.mean(d))
    q = max(1, int(n ** (1/3)))
    # Newey-West variance
    gamma0 = float(np.mean((d - d_mean)**2))
    nw_sum = gamma0
    for lag in range(1, q + 1):
        gamma_l = float(np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean)))
        nw_sum += 2.0 * (1 - lag / (q + 1)) * gamma_l
    nw_var = nw_sum / n
    if nw_var <= 0:
        return {'t_stat': np.nan, 'p_value': np.nan, 'mean_diff': d_mean, 'n': n}
    t_stat = d_mean / np.sqrt(nw_var)
    from scipy.stats import t as t_dist
    p_val = float(2.0 * t_dist.sf(abs(t_stat), df=n-1))
    harvey_sig = (abs(t_stat) > 3.0)
    return {
        't_stat': float(t_stat),
        'p_value': p_val,
        'mean_diff': d_mean,
        'n': int(n),
        'harvey_significant': harvey_sig,
        'mean_qlike_gjr': float(np.mean(loss1[mask_full if len(loss1) == n_full else np.ones(n, dtype=bool)])),
        'mean_qlike_a4f': float(np.mean(loss2[mask_full if len(loss2) == n_full else np.ones(n, dtype=bool)])),
    }


def run_dm(mask, label):
    l1 = gjr_losses[mask]
    l2 = a4f_losses[mask]
    res = dm_test_hac(l1, l2)
    # Fix mean_qlike fields to use mask-specific data
    res['mean_qlike_gjr'] = float(np.mean(gjr_losses[mask]))
    res['mean_qlike_a4f'] = float(np.mean(a4f_losses[mask]))
    sig_str = "HARVEY-SIG" if res.get('harvey_significant') else "not sig"
    print(f"  {label}: t={res['t_stat']:.4f}, p={res['p_value']:.4f}, n={res['n']} [{sig_str}]")
    print(f"    QLIKE GJR={res['mean_qlike_gjr']:.6f}, A4f={res['mean_qlike_a4f']:.6f}")
    return res


dm_full     = run_dm(mask_full,      "Full OOS")
dm_non_covid = run_dm(mask_non_covid, "Non-COVID")
dm_pre      = run_dm(mask_pre_covid, "Pre-COVID")
dm_covid    = run_dm(mask_covid,     "COVID window")
dm_post     = run_dm(mask_post_covid, "Post-COVID")

# ============================================================
# INTERPRETATION
# ============================================================
print("\n[6] Interpretation (vs K988 and C1 gate)...")
full_t = dm_full['t_stat']
nc_t = dm_non_covid['t_stat']
print(f"  Full OOS DM t = {full_t:.4f} (K988 ref: +4.48; should match if spec correct)")
print(f"  Non-COVID DM t = {nc_t:.4f} (C1 gate: |t|>3.0 Harvey-sig)")
if not np.isnan(full_t):
    if full_t > 3.0:
        print("  VERIFICATION: full_oos t>3 — consistent with K988, A4f dominates GJR ✓")
    elif full_t > 0:
        print("  PARTIAL: full_oos t>0 but <3.0 — A4f still better but not Harvey-sig overall")
    else:
        print("  WARNING: full_oos t<0 — GJR beats A4f; possible replication bug")
if not np.isnan(nc_t):
    if abs(nc_t) > 3.0 and nc_t > 0:
        print(f"  C1 PASS: non-COVID t={nc_t:.4f}>3.0 — A4f advantage not COVID-driven → robustness table OK")
    elif nc_t > 0:
        print(f"  C1 WEAK: non-COVID t={nc_t:.4f}>0 but <3.0 — advantage persists but not Harvey-robust")
    else:
        print(f"  C1 FAIL: non-COVID t={nc_t:.4f}<0 — investigate COVID inflation hypothesis")

# ============================================================
# SAVE RESULTS
# ============================================================
elapsed_total = time.time() - START_TIME
results = {
    "experiment_id": EXPERIMENT_ID,
    "run_at": datetime.now(timezone.utc).isoformat(),
    "elapsed_seconds": round(elapsed_total, 1),
    "configuration": {
        "oos_start": OOS_START,
        "oos_end": OOS_END,
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "covid_start": COVID_START,
        "covid_end": COVID_END,
        "data_source": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "seed": 42,
        "a4f_spec": "vix_squared, tau_t denom, free_omega=True, L-BFGS-B",
        "theta0_bounds": "[-1e-2, 1e-2] (K988-faithful)",
        "theta1_bounds": "[1e-8, 1e-3] (K988-faithful)",
        "g_init": "omega/(1-persist) unconditional mean (K988-faithful)",
        "note": "K1393 = K1392 bug-fix: correct bounds, g init, optimizer to match K988"
    },
    "sample_sizes": {
        "n_full_oos": int(n_full),
        "n_covid": int(n_covid),
        "n_non_covid": int(n_non_covid),
        "n_pre_covid": int(n_pre),
        "n_post_covid": int(n_post)
    },
    "dm_tests": {
        "full_oos": dm_full,
        "non_covid": dm_non_covid,
        "pre_covid": dm_pre,
        "covid_window": dm_covid,
        "post_covid": dm_post
    },
    "k988_reference": {
        "A4f_qlike": -8.360769450776205,
        "B0_GJR_qlike": -8.277222480688362,
        "dm_t": 4.482553559343101,
        "n": 1825
    },
    "metadata": {
        "paper": "garch-x-vix",
        "issue_addressed": "C1 CRITICAL — COVID subperiod analysis (K1392 bug-fix)",
        "review_round": "v3",
        "predecessor_experiments": ["K988", "K1391", "K1392"],
        "k1392_bugs_fixed": [
            "theta0 bounds: [0, var0*2] → [-1e-2, 1e-2]",
            "theta1 bounds: [1e-10, 1.0] → [1e-8, 1e-3]",
            "g_init: 1.0 → omega/(1-persist)",
            "optimizer: SLSQP → L-BFGS-B",
            "rolling: recompute-each-step → state-based recursive"
        ]
    }
}

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, cls=NpEncoder)

print(f"\n[7] Results saved to {RESULTS_PATH}")
print(f"    Elapsed: {elapsed_total:.1f}s")
print(f"    Full OOS DM t = {full_t:.4f} | Non-COVID DM t = {nc_t:.4f}")
print("\nDONE.")
