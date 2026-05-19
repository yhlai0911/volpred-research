#!/usr/bin/env python3
"""
K1378 — Paper 9 Leave-COVID-out DM Test (SF1 Robustness Fix)
=============================================================
Compute DM test (A4f vs GJR-GARCH) for:
  (a) Full OOS: 2019-01-01 onwards
  (b) Non-COVID OOS: excluding 2020-03-01 to 2021-06-30

Addresses SERIOUS FLAW SF1 from review v3:
  "No leave-COVID-out analysis. 7-period robustness claim has no table."

Harvey threshold: |t| > 3.0
QLIKE proxy: r² (squared log return)
seed=42, signal.shift(1) for VIX lag
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

# Configuration — matches Paper 9 canonical
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
COVID_START = '2020-03-01'
COVID_END = '2021-06-30'
SNAPSHOT_CSV = os.path.join(PROJECT_ROOT, 'paper', 'garch-x-vix', 'data',
                             'spy_vix_qqq_eem_fez_2000-2026.csv')

print("=" * 70)
print("K1378: Leave-COVID-out DM Test (A4f vs GJR-GARCH)")
print("=" * 70)

# ============================================================
# 1. DATA LOADING — snapshot CSV only, no live yfinance
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
covid_mask = (df.index >= COVID_START) & (df.index <= COVID_END)
no_covid_oos_mask = oos_mask & ~covid_mask

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2

dates = df.index.to_numpy()
oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
no_covid_oos_pos = no_covid_oos_mask[oos_mask]  # bool mask within OOS

print(f"  SPY: {df.index[0].date()} to {df.index[-1].date()}, n={len(df)}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")
print(f"  COVID period: {COVID_START} to {COVID_END}")
print(f"  Non-COVID OOS: {no_covid_oos_pos.sum()} days")

# ============================================================
# 2. MODEL IMPLEMENTATIONS (copied from compute_mcs_dm.py)
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
    starts = [
        [var0 * 0.1, var0 / vm, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vm * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vm * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [(-1e-2, 1e-2), (1e-8, 1e-3), (1e-6, 1.0),
              (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll, best_p = np.inf, None
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll, best_p = res.fun, res.x
        except Exception:
            pass
    return best_p


def compute_tau_a4f(params, vix_lag):
    th0, th1 = params[0], params[1]
    return np.maximum(th0 + th1 * vix_lag**2, 1e-16)


# ============================================================
# 3. ROLLING WINDOW OOS FORECASTING
# ============================================================
print("\n[2] Rolling window OOS forecasting (A4f + GJR)...")

fcst_gjr = np.full(n_oos, np.nan)
fcst_a4f = np.full(n_oos, np.nan)

gjr_state = {'params': None, 'h': None}
a4f_state = {'params': None, 'g': None, 'tau_prev': None}

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
            tau_tr = compute_tau_a4f(a4f_p, v_lag)
            eg = omg / (1.0 - persist) if persist < 1.0 else 1.0
            g = eg
            for i in range(1, nt):
                u = tr_ret[i-1] / np.sqrt(max(tau_tr[i], 1e-16))
                asym = gam * u**2 if u < 0 else 0.0
                g = omg + alp * u**2 + asym + bet * g
                g = max(g, 1e-10)
            a4f_state['g'] = g
            a4f_state['tau_prev'] = tau_tr[-1]

    # GJR one-step forecast
    if gjr_state['params'] is not None:
        h = gjr_1step(gjr_state['params'], gjr_state['h'], ret[abs_idx-1])
        fcst_gjr[t_idx] = h
        gjr_state['h'] = h

    # A4f one-step forecast
    if a4f_state['params'] is not None:
        th0, th1, omg, alp, gam, bet = a4f_state['params']
        # VIX at t-1 (signal.shift(1)) — abs_idx is current t, use vix[abs_idx-1]
        vix_t1 = vix[abs_idx - 1]
        tau_t = max(th0 + th1 * vix_t1**2, 1e-16)
        g = a4f_state['g']
        u = ret[abs_idx-1] / np.sqrt(max(a4f_state['tau_prev'], 1e-16))
        asym = gam * u**2 if u < 0 else 0.0
        g = omg + alp * u**2 + asym + bet * g
        g = max(g, 1e-10)
        sigma2 = tau_t * g
        fcst_a4f[t_idx] = sigma2
        a4f_state['g'] = g
        a4f_state['tau_prev'] = tau_t

print(f"  Done in {time.time()-START_TIME:.1f}s")

# ============================================================
# 4. QLIKE LOSSES
# ============================================================
# QLIKE(σ̂², r²) = σ̂²/r² - log(σ̂²/r²) - 1  [Patton 2011, proxy-robust]
print("\n[3] Computing QLIKE losses...")

r2_oos = r2[oos_indices]
valid = (~np.isnan(fcst_gjr)) & (~np.isnan(fcst_a4f)) & (r2_oos > 1e-16)

def qlike(sigma2_hat, rv_proxy):
    ratio = np.maximum(sigma2_hat, 1e-16) / np.maximum(rv_proxy, 1e-16)
    return ratio - np.log(ratio) - 1.0

loss_gjr = qlike(fcst_gjr, r2_oos)
loss_a4f = qlike(fcst_a4f, r2_oos)

# Mean QLIKE (note: we use r²/n as QLIKE proxy for h, so QLIKE = -loglik analog)
# Standard QLIKE: mean(σ̂²/r² - log(σ̂²/r²) - 1) — lower is better
# Paper uses negative log-likelihood proxy: h/r² - log(h) - log(r²) ...
# Using the Patton-robust QLIKE for consistency
loss_diff = loss_gjr - loss_a4f  # positive = A4f wins

# ============================================================
# 5. DM TEST
# ============================================================
print("\n[4] Diebold-Mariano tests...")

def dm_test(d, h=1, small_sample_correction=True):
    """Harvey-Leybourne-Newbold (1997) DM test."""
    T = len(d)
    d_bar = np.mean(d)
    # Newey-West HAC variance (Bartlett kernel, bandwidth = h-1)
    gamma0 = np.mean(d**2) - d_bar**2
    nw_var = gamma0
    for j in range(1, h):
        gamma_j = np.mean(d[j:] * d[:-j]) - d_bar**2
        nw_var += 2 * (1 - j / h) * gamma_j
    if nw_var <= 0:
        return np.nan, np.nan
    dm_stat = d_bar / np.sqrt(nw_var / T)
    if small_sample_correction and T > 1:
        # Harvey et al. (1997) small-sample correction
        k = 1  # forecast horizon
        dm_stat *= np.sqrt((T + 1 - 2*k + k*(k-1)/T) / T)
    p_val = 2 * (1 - stats.t.cdf(abs(dm_stat), df=T-1))
    return float(dm_stat), float(p_val)


# (a) Full OOS
valid_full = valid.copy()
d_full = loss_diff[valid_full]
dm_t_full, dm_p_full = dm_test(d_full)
mean_qlike_gjr_full = float(np.mean(loss_gjr[valid_full]))
mean_qlike_a4f_full = float(np.mean(loss_a4f[valid_full]))

# (b) Non-COVID OOS
valid_no_covid = valid & no_covid_oos_pos
d_no_covid = loss_diff[valid_no_covid]
dm_t_no_covid, dm_p_no_covid = dm_test(d_no_covid)
mean_qlike_gjr_nc = float(np.mean(loss_gjr[valid_no_covid]))
mean_qlike_a4f_nc = float(np.mean(loss_a4f[valid_no_covid]))

# (c) COVID-only OOS
covid_only = valid & ~no_covid_oos_pos & oos_mask.values[oos_mask.values]
covid_only_oos = valid & ~no_covid_oos_pos
d_covid = loss_diff[covid_only_oos]
dm_t_covid, dm_p_covid = dm_test(d_covid)

print(f"\n--- Full OOS (n={valid_full.sum()}) ---")
print(f"  GJR QLIKE: {mean_qlike_gjr_full:.6f}")
print(f"  A4f QLIKE: {mean_qlike_a4f_full:.6f}")
print(f"  DM t-stat: {dm_t_full:.3f}")
print(f"  Harvey pass (|t|>3): {abs(dm_t_full)>3.0}")

print(f"\n--- Non-COVID OOS (n={valid_no_covid.sum()}) ---")
print(f"  GJR QLIKE: {mean_qlike_gjr_nc:.6f}")
print(f"  A4f QLIKE: {mean_qlike_a4f_nc:.6f}")
print(f"  DM t-stat: {dm_t_no_covid:.3f}")
print(f"  Harvey pass (|t|>3): {abs(dm_t_no_covid)>3.0}")

print(f"\n--- COVID-only OOS (n={covid_only_oos.sum()}) ---")
print(f"  DM t-stat: {dm_t_covid:.3f}")
print(f"  Harvey pass (|t|>3): {abs(dm_t_covid)>3.0}")

# ============================================================
# 6. SAVE LOSSES (for future White RC / SPA test K_NEW_C)
# ============================================================
np.save(os.path.join(SCRIPT_DIR, 'k1378_losses_gjr.npy'), loss_gjr)
np.save(os.path.join(SCRIPT_DIR, 'k1378_losses_a4f.npy'), loss_a4f)
np.save(os.path.join(SCRIPT_DIR, 'k1378_valid_mask.npy'), valid)
np.save(os.path.join(SCRIPT_DIR, 'k1378_no_covid_mask.npy'), no_covid_oos_pos)
print("\n  Saved loss arrays for K_NEW_C (White RC / SPA)")

# ============================================================
# 7. RESULTS JSON
# ============================================================
elapsed = time.time() - START_TIME
results = {
    "experiment_id": "k1378",
    "title": "Paper 9 Leave-COVID-out DM Test (SF1 Robustness Fix)",
    "metadata": {
        "data_source": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        "oos_start": OOS_START,
        "covid_exclusion": f"{COVID_START} to {COVID_END}",
        "window": WINDOW,
        "refit_every": REFIT_EVERY,
        "harvey_threshold": 3.0,
        "qlike_proxy": "r_squared (squared log return)",
        "elapsed_seconds": round(elapsed, 1),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    },
    "full_oos": {
        "n": int(valid_full.sum()),
        "gjr_qlike_mean": mean_qlike_gjr_full,
        "a4f_qlike_mean": mean_qlike_a4f_full,
        "dm_t_stat": dm_t_full,
        "dm_p_value": dm_p_full,
        "harvey_pass": bool(abs(dm_t_full) > 3.0),
    },
    "no_covid_oos": {
        "n": int(valid_no_covid.sum()),
        "gjr_qlike_mean": mean_qlike_gjr_nc,
        "a4f_qlike_mean": mean_qlike_a4f_nc,
        "dm_t_stat": dm_t_no_covid,
        "dm_p_value": dm_p_no_covid,
        "harvey_pass": bool(abs(dm_t_no_covid) > 3.0),
        "sf1_verdict": "REFUTED" if abs(dm_t_no_covid) > 3.0 else "CONFIRMED",
    },
    "covid_only_oos": {
        "n": int(covid_only_oos.sum()),
        "dm_t_stat": dm_t_covid,
        "dm_p_value": dm_p_covid,
        "harvey_pass": bool(abs(dm_t_covid) > 3.0),
    },
}

out_path = os.path.join(SCRIPT_DIR, 'k1378_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"\n[5] Results saved to {out_path}")
print(f"\nTotal elapsed: {elapsed:.1f}s")

# Final verdict
sf1 = results['no_covid_oos']['sf1_verdict']
print(f"\n{'='*50}")
print(f"SF1 VERDICT: {sf1}")
if sf1 == 'REFUTED':
    t = dm_t_no_covid
    print(f"  A4f DM t={t:.3f} outside COVID → Harvey PASS → SF1 refuted")
    print("  Paper body: add Table X showing non-COVID DM stat.")
else:
    t = dm_t_no_covid
    print(f"  A4f DM t={t:.3f} outside COVID → Harvey FAIL → SF1 confirmed")
    print("  Paper needs major revision: COVID-driven result.")
print('='*50)
