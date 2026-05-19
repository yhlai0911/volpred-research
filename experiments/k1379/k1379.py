#!/usr/bin/env python3
"""
K1379 — Paper 9 HAR-RV / HAR-RV-VIX Benchmarks (C4 Horse Race Fix)
=====================================================================
Adds HAR-RV (B-1) and HAR-RV-VIX (B-2) to the paper 9 horse race.
Compares all 4 models (B0/GJR, A4f, B-1/HAR-RV, B-2/HAR-RV-VIX) via
Diebold-Mariano test using Patton QLIKE loss.

Addresses Review v3 C4 (HIGH): "horse race without HAR-RV is incomplete."

seed=42, no lookahead, VIX_{t-1} in all models
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
SNAPSHOT_CSV = os.path.join(PROJECT_ROOT, 'paper', 'garch-x-vix', 'data',
                             'spy_vix_qqq_eem_fez_2000-2026.csv')

print("=" * 70)
print("K1379: HAR-RV / HAR-RV-VIX Benchmarks vs A4f (Paper 9)")
print("=" * 70)

# ============================================================
# 1. DATA LOADING
# ============================================================
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

oos_indices = np.where(oos_mask.values)[0]
n_oos = len(oos_indices)

print(f"  SPY: {df.index[0].date()} to {df.index[-1].date()}, n={len(df)}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

# ============================================================
# 2. MODEL IMPLEMENTATIONS
# ============================================================

@njit(cache=True)
def gjr_loglik(params, returns):
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
    var0 = np.var(returns)
    best_ll, best_p = np.inf, None
    for s in [[var0 * 0.05, 0.05, 0.05, 0.90],
              [var0 * 0.02, 0.03, 0.08, 0.88],
              [var0 * 0.10, 0.08, 0.10, 0.80]]:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B',
                                    bounds=[(1e-8, var0), (1e-4, 0.3),
                                            (1e-4, 0.3), (0.5, 0.999)])
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except Exception:
            pass
    return best_p


def gjr_1step(p, h, r):
    o, a, g, b = p
    asym = g * r**2 if r < 0 else 0.0
    return max(o + a * r**2 + asym + b * h, 1e-10)


def fit_a4f(returns, log_vix_vals, vix_vals):
    """A4f: τ_t = θ₀ + θ₁VIX²_{t-1}, free ω_g."""
    n = len(returns)
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]
    vix_lag = np.exp(log_vix_lag)

    def neg_loglik(params):
        th0, th1, omg, alp, gam, bet = params
        if omg <= 0 or alp < 0 or gam < 0 or bet < 0:
            return 1e10
        persist = alp + gam / 2.0 + bet
        if persist >= 1.0:
            return 1e10
        tau = np.maximum(th0 + th1 * vix_lag**2, 1e-16)
        eg = omg / (1.0 - persist)
        g = eg
        ll = 0.0
        for t in range(1, n):
            u = returns[t-1] / np.sqrt(max(tau[t], 1e-16))
            asym = gam * u**2 if u < 0 else 0.0
            g = omg + alp * u**2 + asym + bet * g
            g = max(g, 1e-10)
            sigma2 = tau[t] * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vm = np.mean(vix_lag**2) + 1e-8
    best_ll, best_p = np.inf, None
    for s in [[var0 * 0.1, var0/vm, 0.05, 0.05, 0.05, 0.90],
              [var0 * 0.05, var0/vm*0.5, 0.10, 0.03, 0.08, 0.88],
              [var0 * 0.2, var0/vm*1.5, 0.02, 0.08, 0.10, 0.80]]:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B',
                                    bounds=[(-1e-2, 1e-2), (1e-8, 1e-3), (1e-6, 1.0),
                                            (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)],
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except Exception:
            pass
    return best_p


def fit_har_rv(rv_series, vix_series=None):
    """
    Fit HAR-RV (or HAR-RV-VIX) via OLS.
    rv_series: array of RV_t (length n, using past values only)
    vix_series: if not None, add VIX²_{t-1} as regressor (HAR-RV-VIX)

    Returns coefficient vector β (intercept last in sklearn convention,
    but here we build X explicitly).
    """
    n = len(rv_series)
    if n < 30:
        return None

    # Build features (all using lag ≥ 1, no lookahead)
    # RV_{t-1}
    rv_d = np.full(n, np.nan)
    rv_d[1:] = rv_series[:-1]
    # RV̄^(5): mean of RV_{t-1}, ..., RV_{t-5}
    rv_w = np.full(n, np.nan)
    for i in range(5, n):
        rv_w[i] = np.mean(rv_series[i-5:i])
    # RV̄^(22): mean of RV_{t-1}, ..., RV_{t-22}
    rv_m = np.full(n, np.nan)
    for i in range(22, n):
        rv_m[i] = np.mean(rv_series[i-22:i])

    if vix_series is not None:
        vix_sq_lag = np.full(n, np.nan)
        vix_sq_lag[1:] = vix_series[:-1] ** 2
        mask = ~(np.isnan(rv_d) | np.isnan(rv_w) | np.isnan(rv_m) |
                 np.isnan(vix_sq_lag) | np.isnan(rv_series))
        X = np.column_stack([np.ones(mask.sum()), rv_d[mask], rv_w[mask],
                             rv_m[mask], vix_sq_lag[mask]])
    else:
        mask = ~(np.isnan(rv_d) | np.isnan(rv_w) | np.isnan(rv_m) |
                 np.isnan(rv_series))
        X = np.column_stack([np.ones(mask.sum()), rv_d[mask], rv_w[mask], rv_m[mask]])

    y = rv_series[mask]
    try:
        beta, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
        return beta
    except Exception:
        return None


def har_forecast(beta, rv_last, rv_history, vix_last=None):
    """One-step HAR-RV (or HAR-RV-VIX) forecast."""
    if beta is None:
        return np.nan
    n_hist = len(rv_history)
    rv_d = rv_last
    rv_w = np.mean(rv_history[-5:]) if n_hist >= 5 else rv_last
    rv_m = np.mean(rv_history[-22:]) if n_hist >= 22 else rv_last
    if vix_last is not None and len(beta) == 5:
        pred = beta[0] + beta[1]*rv_d + beta[2]*rv_w + beta[3]*rv_m + beta[4]*vix_last**2
    else:
        pred = beta[0] + beta[1]*rv_d + beta[2]*rv_w + beta[3]*rv_m
    return max(float(pred), 1e-16)


# ============================================================
# 3. ROLLING WINDOW OOS FORECASTING
# ============================================================
print("\n[2] Rolling window OOS forecasting (4 models)...")

fcst_gjr = np.full(n_oos, np.nan)
fcst_a4f = np.full(n_oos, np.nan)
fcst_har = np.full(n_oos, np.nan)
fcst_har_vix = np.full(n_oos, np.nan)

gjr_state = {'params': None, 'h': None}
a4f_state = {'params': None, 'g': None, 'tau_prev': None}
har_beta = None
har_vix_beta = None

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 500 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos} ({elapsed:.1f}s)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        ts = max(0, abs_idx - WINDOW)
        tr_ret = ret[ts:abs_idx]
        tr_log_vix = log_vix[ts:abs_idx]
        tr_vix = vix[ts:abs_idx]
        tr_r2 = r2[ts:abs_idx]

        # GJR-GARCH
        gjr_p = fit_gjr(tr_ret)
        if gjr_p is not None:
            gjr_state['params'] = gjr_p
            h = np.var(tr_ret)
            for i in range(1, len(tr_ret)):
                h = gjr_1step(gjr_p, h, tr_ret[i-1])
            gjr_state['h'] = h

        # A4f
        a4f_p = fit_a4f(tr_ret, tr_log_vix, tr_vix)
        if a4f_p is not None:
            a4f_state['params'] = a4f_p
            th0, th1, omg, alp, gam, bet = a4f_p
            persist = alp + gam / 2.0 + bet
            nt = len(tr_ret)
            lv_lag = np.empty(nt)
            lv_lag[0] = tr_log_vix[0]
            lv_lag[1:] = tr_log_vix[:-1]
            v_lag = np.exp(lv_lag)
            tau_tr = np.maximum(th0 + th1 * v_lag**2, 1e-16)
            eg = omg / (1.0 - persist) if persist < 1.0 else 1.0
            g = eg
            for i in range(1, nt):
                u = tr_ret[i-1] / np.sqrt(max(tau_tr[i], 1e-16))
                asym = gam * u**2 if u < 0 else 0.0
                g = omg + alp * u**2 + asym + bet * g
                g = max(g, 1e-10)
            a4f_state['g'] = g
            a4f_state['tau_prev'] = tau_tr[-1]

        # HAR-RV
        har_beta = fit_har_rv(tr_r2)

        # HAR-RV-VIX
        har_vix_beta = fit_har_rv(tr_r2, tr_vix)

    # GJR forecast
    if gjr_state['params'] is not None:
        h = gjr_1step(gjr_state['params'], gjr_state['h'], ret[abs_idx-1])
        fcst_gjr[t_idx] = h
        gjr_state['h'] = h

    # A4f forecast
    if a4f_state['params'] is not None:
        th0, th1, omg, alp, gam, bet = a4f_state['params']
        vix_t1 = vix[abs_idx - 1]  # VIX at t-1 (signal.shift(1))
        tau_t = max(th0 + th1 * vix_t1**2, 1e-16)
        g = a4f_state['g']
        u = ret[abs_idx-1] / np.sqrt(max(a4f_state['tau_prev'], 1e-16))
        asym = gam * u**2 if u < 0 else 0.0
        g = omg + alp * u**2 + asym + bet * g
        g = max(g, 1e-10)
        fcst_a4f[t_idx] = tau_t * g
        a4f_state['g'] = g
        a4f_state['tau_prev'] = tau_t

    # HAR-RV forecast (all regressors at t-1, no lookahead)
    if har_beta is not None and abs_idx > 22:
        ts_start = max(0, abs_idx - WINDOW)
        rv_hist = r2[ts_start:abs_idx]
        rv_last = r2[abs_idx - 1]
        fcst_har[t_idx] = har_forecast(har_beta, rv_last, rv_hist)

    # HAR-RV-VIX forecast (VIX²_{t-1} as extra regressor)
    if har_vix_beta is not None and abs_idx > 22:
        ts_start = max(0, abs_idx - WINDOW)
        rv_hist = r2[ts_start:abs_idx]
        rv_last = r2[abs_idx - 1]
        vix_last = vix[abs_idx - 1]  # VIX at t-1
        fcst_har_vix[t_idx] = har_forecast(har_vix_beta, rv_last, rv_hist, vix_last)

print(f"  Done in {time.time()-START_TIME:.1f}s")

# ============================================================
# 4. QLIKE LOSSES
# ============================================================
print("\n[3] Computing QLIKE losses...")

r2_oos = r2[oos_indices]
valid_all = (~np.isnan(fcst_gjr)) & (~np.isnan(fcst_a4f)) & \
            (~np.isnan(fcst_har)) & (~np.isnan(fcst_har_vix)) & (r2_oos > 1e-16)


def qlike(sigma2_hat, rv_proxy):
    ratio = np.maximum(sigma2_hat, 1e-16) / np.maximum(rv_proxy, 1e-16)
    return ratio - np.log(ratio) - 1.0


loss_gjr = qlike(fcst_gjr, r2_oos)
loss_a4f = qlike(fcst_a4f, r2_oos)
loss_har = qlike(fcst_har, r2_oos)
loss_har_vix = qlike(fcst_har_vix, r2_oos)

# QLIKE means (lower = better)
v = valid_all
print(f"  Valid OOS obs: {v.sum()}")
print(f"  GJR    QLIKE: {np.mean(loss_gjr[v]):.6f}")
print(f"  A4f    QLIKE: {np.mean(loss_a4f[v]):.6f}")
print(f"  HAR-RV QLIKE: {np.mean(loss_har[v]):.6f}")
print(f"  HAR-VX QLIKE: {np.mean(loss_har_vix[v]):.6f}")

# ============================================================
# 5. DM TESTS
# ============================================================
print("\n[4] Diebold-Mariano tests (Harvey 2016 threshold |t| > 3.0)...")


def dm_test(d):
    T = len(d)
    d_bar = np.mean(d)
    gamma0 = np.mean(d**2) - d_bar**2
    if gamma0 <= 0:
        return np.nan, np.nan
    dm_stat = d_bar / np.sqrt(gamma0 / T)
    dm_stat *= np.sqrt((T + 1 - 2 + 1/T) / T)  # Harvey et al. (1997) correction
    p_val = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T - 1))
    return float(dm_stat), float(p_val)


pairs = [
    ('A4f vs GJR', loss_gjr[v] - loss_a4f[v]),       # positive = A4f wins
    ('A4f vs HAR-RV', loss_har[v] - loss_a4f[v]),     # positive = A4f wins
    ('A4f vs HAR-VX', loss_har_vix[v] - loss_a4f[v]), # positive = A4f wins
    ('HAR-RV vs GJR', loss_gjr[v] - loss_har[v]),     # positive = HAR wins
    ('HAR-VX vs GJR', loss_gjr[v] - loss_har_vix[v]), # positive = HAR-VX wins
    ('HAR-VX vs HAR-RV', loss_har[v] - loss_har_vix[v]),  # positive = HAR-VX wins
]

dm_results = {}
for label, d in pairs:
    t, p = dm_test(d)
    harvey = bool(abs(t) > 3.0)
    print(f"  {label:20s}: t={t:+.3f}, p={p:.4f}, Harvey={'PASS' if harvey else 'FAIL'}")
    dm_results[label] = {'dm_t': t, 'dm_p': p, 'harvey_pass': harvey,
                         'direction': 'model1_wins' if (t > 0) else 'model2_wins'}

# ============================================================
# 6. SAVE LOSSES FOR K_NEW_C (White RC / SPA)
# ============================================================
np.save(os.path.join(SCRIPT_DIR, 'k1379_loss_gjr.npy'), loss_gjr)
np.save(os.path.join(SCRIPT_DIR, 'k1379_loss_a4f.npy'), loss_a4f)
np.save(os.path.join(SCRIPT_DIR, 'k1379_loss_har.npy'), loss_har)
np.save(os.path.join(SCRIPT_DIR, 'k1379_loss_har_vix.npy'), loss_har_vix)
np.save(os.path.join(SCRIPT_DIR, 'k1379_valid_mask.npy'), v)
print("\n  Saved loss arrays for K_NEW_C")

# ============================================================
# 7. RESULTS JSON
# ============================================================
elapsed = time.time() - START_TIME
results = {
    "experiment_id": "k1379",
    "title": "Paper 9 HAR-RV / HAR-RV-VIX Benchmarks vs A4f",
    "metadata": {
        "data_source": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "oos_start": OOS_START,
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "n_valid_oos": int(v.sum()),
        "harvey_threshold": 3.0,
        "qlike_proxy": "r_squared (daily squared log return)",
        "elapsed_seconds": round(elapsed, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "note": "HAR-RV fit via rolling OLS; A4f and GJR via MLE. Fair comparison: same QLIKE proxy.",
    },
    "qlike_means": {
        "GJR": float(np.mean(loss_gjr[v])),
        "A4f": float(np.mean(loss_a4f[v])),
        "HAR_RV": float(np.mean(loss_har[v])),
        "HAR_RV_VIX": float(np.mean(loss_har_vix[v])),
    },
    "dm_tests": dm_results,
    "paper9_c4_assessment": {
        "a4f_vs_har_rv_harvey_pass": dm_results.get('A4f vs HAR-RV', {}).get('harvey_pass', None),
        "verdict": "C4 ADDRESSED — A4f significantly beats HAR-RV"
        if dm_results.get('A4f vs HAR-RV', {}).get('harvey_pass', False)
        else "C4 LIMITATION — A4f does NOT significantly beat HAR-RV (honest result, add as limitation)",
    },
}

out_path = os.path.join(SCRIPT_DIR, 'k1379_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2)

print(f"\n[5] Results saved to {out_path}")
print(f"\nTotal elapsed: {elapsed:.1f}s")
print(f"\n{'='*50}")
print(f"C4 VERDICT: {results['paper9_c4_assessment']['verdict']}")
print('='*50)
