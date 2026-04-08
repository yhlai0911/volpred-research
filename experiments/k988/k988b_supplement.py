#!/usr/bin/env python3
"""
K988b: Supplementary Specifications for Multiplicative GARCH-X / GARCH-MIDAS(VIX)
==================================================================================
[提出: 賴奕豪, 執行: Claude]

Supplements K988 with missing specifications identified in discussion:
  A3f: tau_{t-1} denominator + free omega (cross-comparison completeness)
  A2n: log-exp tau + sample-mean normalization (方案B: rescale u so E(u²)=1)
  A4n: VIX² tau + sample-mean normalization
  C1: GARCH-MIDAS fixed-span K=6 months (original paper spec, tau constant within month)
  C2: GARCH-MIDAS fixed-span K=12 months
  C3: GARCH-MIDAS fixed-span K=24 months

Also validates VRP interpretation by computing correlation between g and independent VRP.

References: same as K988.
"""

import os, sys, json, time, warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K988b"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k988b_results.json')

DATA_START = '2005-01-01'
DATA_END = '2026-04-08'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

print("=" * 70)
print(f"{EXPERIMENT_ID}: Supplementary Specifications")
print("=" * 70)

# ============================================================
# DATA
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
df['month'] = df.index.to_period('M')

oos_mask = np.array(df.index >= OOS_START)
ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2
n_total = len(df)

oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
print(f"  SPY: n={n_total}, n_oos={n_oos}")


# ============================================================
# GJR BENCHMARK (reuse from K988)
# ============================================================
from numba import njit

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
        if h[t] < 1e-10: h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2*np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll

def fit_gjr(returns):
    var0 = np.var(returns)
    best_ll, best_p = np.inf, None
    for s in [[var0*0.05,0.05,0.05,0.90],[var0*0.02,0.03,0.08,0.88],[var0*0.10,0.08,0.10,0.80]]:
        try:
            r = optimize.minimize(gjr_loglik, s, args=(returns,), method='L-BFGS-B',
                                  bounds=[(1e-8,var0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)])
            if r.fun < best_ll: best_ll, best_p = r.fun, r.x
        except: pass
    return best_p

def gjr_1step(p, h, r):
    o,a,g,b = p
    asym = g*r**2 if r < 0 else 0.0
    return max(o + a*r**2 + asym + b*h, 1e-10)


# ============================================================
# MULTIPLICATIVE GARCH-X (with sample-mean normalization option)
# ============================================================
def fit_mfgjr_x(returns, log_vix_v, vix_v, tau_func='log_exp', denom_mode='tau_t',
                free_omega=False, sample_norm=False):
    """
    Fit multiplicative GJR-X.
    sample_norm: if True, normalize u by sqrt(mean(r²/tau)) so E(u²)≈1,
                 then use constrained omega = 1-a-g/2-b (方案B).
    """
    n = len(returns)
    log_vix_lag = np.empty(n); log_vix_lag[0] = log_vix_v[0]; log_vix_lag[1:] = log_vix_v[:-1]
    vix_lag = np.exp(log_vix_lag)

    r2_pos = np.maximum(returns**2, 1e-16)
    log_r2 = np.log(r2_pos)

    if tau_func == 'log_exp':
        X = np.column_stack([np.ones(n), log_vix_lag])
    elif tau_func == 'vix_squared':
        X = np.column_stack([np.ones(n), vix_lag**2])
    theta_init = np.linalg.lstsq(X, log_r2, rcond=None)[0]

    def neg_loglik(params):
        if free_omega:
            if tau_func == 'vix_squared':
                th0, th1, omg, alp, gam, bet = params
                tau = np.maximum(th0 + th1 * vix_lag**2, 1e-16)
            else:
                th0, th1, omg, alp, gam, bet = params
                tau = np.maximum(np.exp(th0 + th1 * log_vix_lag), 1e-16)
        else:
            if tau_func == 'vix_squared':
                th0, th1, alp, gam, bet = params
                tau = np.maximum(th0 + th1 * vix_lag**2, 1e-16)
            else:
                th0, th1, alp, gam, bet = params
                tau = np.maximum(np.exp(th0 + th1 * log_vix_lag), 1e-16)
            omg = None  # computed below

        if alp < 0 or gam < 0 or bet < 0: return 1e10
        persist = alp + gam/2.0 + bet
        if persist >= 1.0: return 1e10

        if free_omega:
            omega_g = omg
            if omega_g <= 0: return 1e10
        else:
            omega_g = 1.0 - persist
            if omega_g <= 0: return 1e10

        # Sample-mean normalization factor
        # Codex K999 fix: match pairing with recursion u_{t-1} = r_{t-1}/sqrt(tau_t)
        if sample_norm:
            if denom_mode == 'tau_t':
                mean_r2_over_tau = np.mean(returns[:-1]**2 / tau[1:])
            else:
                mean_r2_over_tau = np.mean(returns[:-1]**2 / tau[:-1])
            norm_factor = np.sqrt(max(mean_r2_over_tau, 1e-16))
        else:
            norm_factor = 1.0

        eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
        g = np.empty(n)
        g[0] = eg if free_omega else 1.0
        ll = 0.0

        for t in range(1, n):
            if denom_mode == 'tau_t':
                u_prev = (returns[t-1] / np.sqrt(tau[t])) / norm_factor
            else:
                u_prev = (returns[t-1] / np.sqrt(tau[t-1])) / norm_factor
            asym = gam * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alp * u_prev**2 + asym + bet * g[t-1]
            if g[t] < 1e-10: g[t] = 1e-10

        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sample_norm:
                sigma2 *= mean_r2_over_tau  # rescale back
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    best_ll, best_p = np.inf, None

    if free_omega:
        if tau_func == 'vix_squared':
            v0 = np.var(returns); vm = np.mean(vix_lag**2)+1e-8
            starts = [[v0*0.1,v0/vm,0.05,0.05,0.05,0.90],[v0*0.05,v0/vm*0.5,0.10,0.03,0.08,0.88]]
            bounds = [(-1e-2,1e-2),(1e-8,1e-3),(1e-6,1.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]
        else:
            starts = [[theta_init[0],theta_init[1],0.05,0.05,0.05,0.90],
                       [theta_init[0],theta_init[1],0.10,0.03,0.08,0.88]]
            bounds = [(-20,0),(0.1,5.0),(1e-6,1.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]
    else:
        if tau_func == 'vix_squared':
            v0 = np.var(returns); vm = np.mean(vix_lag**2)+1e-8
            starts = [[v0*0.1,v0/vm,0.05,0.05,0.90],[v0*0.05,v0/vm*0.5,0.03,0.08,0.88]]
            bounds = [(-1e-2,1e-2),(1e-8,1e-3),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]
        else:
            starts = [[theta_init[0],theta_init[1],0.05,0.05,0.90],
                       [theta_init[0],theta_init[1],0.03,0.08,0.88]]
            bounds = [(-20,0),(0.1,5.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999)]

    for s in starts:
        try:
            r = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter':500})
            if r.fun < best_ll: best_ll, best_p = r.fun, r.x
        except: pass
    return best_p


def compute_tau(params, log_vix_lag, vix_lag, tau_func):
    th0, th1 = params[0], params[1]
    if tau_func == 'log_exp':
        return np.maximum(np.exp(th0 + th1 * log_vix_lag), 1e-16)
    elif tau_func == 'vix_squared':
        return np.maximum(th0 + th1 * vix_lag**2, 1e-16)


# ============================================================
# GARCH-MIDAS FIXED-SPAN (monthly tau, constant within month)
# ============================================================
def beta_weights(K, w1, w2):
    k_v = np.arange(1, K+1, dtype=np.float64) / K
    raw = k_v**(w1-1) * (1-k_v)**(w2-1)
    s = raw.sum()
    return raw / s if s > 1e-16 else np.ones(K)/K


def fit_garch_midas_fixed_span(returns, vix_vals, month_labels, K_months):
    """
    GARCH-MIDAS with fixed-span: tau_t is constant within each month.
    tau_t = exp(m + theta * sum_{k=1}^{K} phi_k * mean_log_VIX_{month t-k})

    This is the original Engle, Ghysels, Sohn (2013) specification.
    g_{i,t} denominator = tau_t (Eq.4 in the paper).
    """
    # Compute monthly average log-VIX
    df_temp = pd.DataFrame({'log_vix': np.log(np.maximum(vix_vals, 1.0)),
                            'month': month_labels})
    monthly_vix = df_temp.groupby('month')['log_vix'].mean()
    unique_months = monthly_vix.index.tolist()
    month_to_idx = {m: i for i, m in enumerate(unique_months)}

    n = len(returns)
    # Map each day to its month index
    day_month_idx = np.array([month_to_idx[m] for m in month_labels])

    # Need K months of history
    valid_start_month = K_months
    if valid_start_month >= len(unique_months):
        return None, 0

    # Find first valid day
    valid_start_day = 0
    for i in range(n):
        if day_month_idx[i] >= valid_start_month:
            valid_start_day = i
            break

    n_valid = n - valid_start_day
    if n_valid < 500:
        return None, valid_start_day

    monthly_vix_arr = monthly_vix.values  # array of monthly avg log-VIX

    def neg_loglik(params):
        m_p, theta_p, alpha, gamma_p, beta_g, w1, w2 = params
        if w1 < 1.0 or w2 < 1.0: return 1e10
        if alpha < 0 or gamma_p < 0 or beta_g < 0: return 1e10
        omega_g = 1.0 - alpha - gamma_p/2.0 - beta_g
        if omega_g <= 0 or alpha + gamma_p/2.0 + beta_g >= 1.0: return 1e10

        weights = beta_weights(K_months, w1, w2)

        # Pre-compute tau for each month
        n_months = len(unique_months)
        tau_monthly = np.empty(n_months)
        for mi in range(n_months):
            if mi < K_months:
                tau_monthly[mi] = np.exp(m_p)  # not enough history, use intercept
            else:
                midas_sum = sum(weights[k] * monthly_vix_arr[mi-1-k] for k in range(K_months))
                tau_monthly[mi] = max(np.exp(m_p + theta_p * midas_sum), 1e-16)

        g = 1.0
        ll = 0.0

        for i in range(valid_start_day, n):
            mi = day_month_idx[i]
            tau_t = tau_monthly[mi]

            if i > valid_start_day:
                # g update: denominator = tau_t (current month's tau, per Eq.4)
                u_prev = returns[i-1] / np.sqrt(tau_t)
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha * u_prev**2 + asym + beta_g * g
                g = max(g, 1e-10)

            sigma2 = tau_t * g
            if sigma2 > 0:
                ll += -0.5 * (np.log(2*np.pi) + np.log(sigma2) + returns[i]**2 / sigma2)

        return -ll

    best_ll, best_p = np.inf, None
    starts = [
        [-10.0, 1.0, 0.05, 0.05, 0.90, 1.5, 2.0],
        [-8.0, 0.5, 0.03, 0.08, 0.88, 1.0, 5.0],
        [-12.0, 1.5, 0.08, 0.10, 0.80, 2.0, 3.0],
    ]
    bounds = [(-20,0),(0.01,5.0),(1e-4,0.3),(1e-4,0.3),(0.5,0.999),(1.0,20.0),(1.0,20.0)]

    for s in starts:
        try:
            r = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter':500})
            if r.fun < best_ll: best_ll, best_p = r.fun, r.x
        except: pass
    return best_p, valid_start_day


# ============================================================
# OOS FORECASTING
# ============================================================
print("\n[2] Out-of-sample forecasting...")

model_names = [
    'B0_GJR',
    'A3f_tau_t1_free_omega',
    'A2n_logexp_samplenorm',
    'A4n_vix2_samplenorm',
    'C1_MIDAS_FS_K6',
    'C2_MIDAS_FS_K12',
    'C3_MIDAS_FS_K24',
]

# Model configs: (tau_func, denom_mode, free_omega, sample_norm)
mfx_configs = {
    'A3f_tau_t1_free_omega': ('log_exp', 'tau_t_minus_1', True, False),
    'A2n_logexp_samplenorm': ('log_exp', 'tau_t', False, True),
    'A4n_vix2_samplenorm': ('vix_squared', 'tau_t', False, True),
}

midas_fs_configs = {
    'C1_MIDAS_FS_K6': 6,
    'C2_MIDAS_FS_K12': 12,
    'C3_MIDAS_FS_K24': 24,
}

forecasts = {name: np.full(n_oos, np.nan) for name in model_names}
states = {name: {'h': None, 'g': None, 'tau_prev': None, 'params': None, 'norm_factor': 1.0}
          for name in model_names}

month_labels = df['month'].values
refit_count = 0

print(f"  OOS: {n_oos} obs, refit every {REFIT_EVERY} days")

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        print(f"  Step {t_idx}/{n_oos} ({time.time()-START_TIME:.0f}s)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        ts = max(0, abs_idx - WINDOW)
        tr_ret = ret[ts:abs_idx]
        tr_log_vix = log_vix[ts:abs_idx]
        tr_vix = vix[ts:abs_idx]
        tr_months = month_labels[ts:abs_idx]

        # B0: GJR
        gjr_p = fit_gjr(tr_ret)
        if gjr_p is not None:
            states['B0_GJR']['params'] = gjr_p
            h = np.var(tr_ret)
            for i in range(1, len(tr_ret)):
                h = gjr_1step(gjr_p, h, tr_ret[i-1])
            states['B0_GJR']['h'] = h

        # MF-X models
        for name, (tf, dm, fo, sn) in mfx_configs.items():
            p = fit_mfgjr_x(tr_ret, tr_log_vix, tr_vix, tau_func=tf, denom_mode=dm,
                            free_omega=fo, sample_norm=sn)
            if p is not None:
                states[name]['params'] = p
                th0, th1 = p[0], p[1]
                if fo:
                    omg, alp, gam, bet = p[2], p[3], p[4], p[5]
                else:
                    alp, gam, bet = p[2], p[3], p[4]
                    omg = 1.0 - alp - gam/2.0 - bet

                nt = len(tr_ret)
                lv_lag = np.empty(nt); lv_lag[0] = tr_log_vix[0]; lv_lag[1:] = tr_log_vix[:-1]
                v_lag = np.exp(lv_lag)
                tau_tr = compute_tau(p, lv_lag, v_lag, tf)

                # Compute normalization factor (Codex K999 fix: match r_{t-1}/tau_t pairing)
                nf = 1.0
                if sn:
                    if dm == 'tau_t':
                        mean_r2_tau = np.mean(tr_ret[:-1]**2 / tau_tr[1:])
                    else:
                        mean_r2_tau = np.mean(tr_ret[:-1]**2 / tau_tr[:-1])
                    nf = np.sqrt(max(mean_r2_tau, 1e-16))
                states[name]['norm_factor'] = nf

                persist = alp + gam/2.0 + bet
                eg = omg / (1.0 - persist) if persist < 1.0 else 1.0
                g = eg if fo else 1.0
                for i in range(1, nt):
                    if dm == 'tau_t':
                        u = (tr_ret[i-1] / np.sqrt(max(tau_tr[i], 1e-16))) / nf
                    else:
                        u = (tr_ret[i-1] / np.sqrt(max(tau_tr[i-1], 1e-16))) / nf
                    asym = gam * u**2 if u < 0 else 0.0
                    g = omg + alp * u**2 + asym + bet * g
                    g = max(g, 1e-10)
                states[name]['g'] = g
                states[name]['tau_prev'] = tau_tr[-1]

        # GARCH-MIDAS fixed-span
        for name, K_m in midas_fs_configs.items():
            p, vs = fit_garch_midas_fixed_span(tr_ret, tr_vix, tr_months, K_m)
            if p is not None:
                states[name]['params'] = p
                # Initialize g from training tail
                m_p, theta_p = p[0], p[1]
                alp, gam, bet = p[2], p[3], p[4]
                w1, w2 = p[5], p[6]
                omg = 1.0 - alp - gam/2.0 - bet
                weights = beta_weights(K_m, w1, w2)

                # Compute monthly avg VIX for training
                df_tr = pd.DataFrame({'lv': np.log(np.maximum(tr_vix, 1.0)), 'mo': tr_months})
                mo_avg = df_tr.groupby('mo')['lv'].mean()
                mo_arr = mo_avg.values
                mo_list = mo_avg.index.tolist()
                mo_map = {m: i for i, m in enumerate(mo_list)}

                g = 1.0
                for i in range(vs, len(tr_ret)):
                    mi = mo_map.get(tr_months[i], 0)
                    if mi >= K_m:
                        ms = sum(weights[k] * mo_arr[mi-1-k] for k in range(K_m) if mi-1-k >= 0)
                        tau_i = max(np.exp(m_p + theta_p * ms), 1e-16)
                    else:
                        tau_i = max(np.exp(m_p), 1e-16)
                    if i > vs:
                        u = tr_ret[i-1] / np.sqrt(tau_i)
                        asym = gam * u**2 if u < 0 else 0.0
                        g = omg + alp * u**2 + asym + bet * g
                        g = max(g, 1e-10)
                states[name]['g'] = g
                states[name]['tau_prev'] = tau_i if 'tau_i' in dir() else np.exp(m_p)

    # --- Forecasts ---

    # B0: GJR
    p = states['B0_GJR']['params']
    if p is not None:
        h = states['B0_GJR']['h']
        h = gjr_1step(p, h, ret[abs_idx-1])
        forecasts['B0_GJR'][t_idx] = h
        states['B0_GJR']['h'] = h

    # MF-X models
    for name, (tf, dm, fo, sn) in mfx_configs.items():
        p = states[name]['params']
        if p is None: continue

        th0, th1 = p[0], p[1]
        if fo:
            omg, alp, gam, bet = p[2], p[3], p[4], p[5]
        else:
            alp, gam, bet = p[2], p[3], p[4]
            omg = 1.0 - alp - gam/2.0 - bet

        lv_l = log_vix[abs_idx-1]
        v_l = vix[abs_idx-1]
        tau_t = compute_tau(p, lv_l, v_l, tf)
        if isinstance(tau_t, np.ndarray): tau_t = float(tau_t.flat[0])

        r_prev = ret[abs_idx-1]
        g_prev = states[name]['g']
        tau_prev = states[name]['tau_prev']
        nf = states[name]['norm_factor']

        if dm == 'tau_t':
            u = (r_prev / np.sqrt(max(tau_t, 1e-16))) / nf
        else:
            u = (r_prev / np.sqrt(max(tau_prev, 1e-16))) / nf

        asym = gam * u**2 if u < 0 else 0.0
        g_new = omg + alp * u**2 + asym + bet * g_prev
        g_new = max(g_new, 1e-10)

        fc = tau_t * g_new
        if sn:
            fc *= nf**2  # rescale back to original variance space
        forecasts[name][t_idx] = fc
        states[name]['g'] = g_new
        states[name]['tau_prev'] = tau_t

    # GARCH-MIDAS fixed-span
    for name, K_m in midas_fs_configs.items():
        p = states[name]['params']
        if p is None: continue

        m_p, theta_p = p[0], p[1]
        alp, gam, bet = p[2], p[3], p[4]
        w1, w2 = p[5], p[6]
        omg = 1.0 - alp - gam/2.0 - bet
        weights = beta_weights(K_m, w1, w2)

        # Compute tau for current month using monthly avg VIX history
        current_month = month_labels[abs_idx]
        # Get monthly average VIX up to previous month
        hist_mask = df.index[:abs_idx]
        df_hist = pd.DataFrame({'lv': np.log(np.maximum(vix[:abs_idx], 1.0)),
                                'mo': month_labels[:abs_idx]})
        mo_avg = df_hist.groupby('mo')['lv'].mean()
        mo_list = mo_avg.index.tolist()

        # Find current month index
        if current_month in mo_list:
            mi = mo_list.index(current_month)
        else:
            mi = len(mo_list)

        if mi >= K_m:
            ms = sum(weights[k] * mo_avg.iloc[mi-1-k] for k in range(K_m) if mi-1-k >= 0)
            tau_t = max(np.exp(m_p + theta_p * ms), 1e-16)
        else:
            tau_t = max(np.exp(m_p), 1e-16)

        r_prev = ret[abs_idx-1]
        g_prev = states[name]['g']

        u = r_prev / np.sqrt(tau_t)
        asym = gam * u**2 if u < 0 else 0.0
        g_new = omg + alp * u**2 + asym + bet * g_prev
        g_new = max(g_new, 1e-10)

        forecasts[name][t_idx] = tau_t * g_new
        states[name]['g'] = g_new
        states[name]['tau_prev'] = tau_t


# ============================================================
# EVALUATION
# ============================================================
print(f"\n[3] Evaluation ({time.time()-START_TIME:.0f}s)...")

oos_r2 = r2[oos_indices]
results = {'models': {}, 'dm_tests': {}}

print(f"\n  {'Model':<30} {'QLIKE':>8} {'Spearman':>10} {'Valid':>6}")
print(f"  {'-'*30} {'-'*8} {'-'*10} {'-'*6}")

for name in model_names:
    fc = forecasts[name]
    valid = ~np.isnan(fc) & (fc > 0)
    nv = valid.sum()
    if nv < 100:
        print(f"  {name:<30} {'N/A':>8} {'N/A':>10} {nv:>6}")
        results['models'][name] = {'status': 'insufficient', 'n_valid': int(nv)}
        continue

    ql = float(np.mean(np.log(fc[valid]) + oos_r2[valid] / fc[valid]))
    rho, _ = stats.spearmanr(fc[valid], oos_r2[valid])
    print(f"  {name:<30} {ql:>8.4f} {rho:>10.4f} {nv:>6}")
    results['models'][name] = {'qlike': ql, 'spearman': float(rho), 'n_valid': int(nv)}

# DM tests vs GJR
gjr_fc = forecasts['B0_GJR']
gjr_v = ~np.isnan(gjr_fc) & (gjr_fc > 0)

print(f"\n  DM Tests vs GJR:")
for name in model_names:
    if name == 'B0_GJR': continue
    fc = forecasts[name]
    bv = gjr_v & ~np.isnan(fc) & (fc > 0)
    nb = bv.sum()
    if nb < 100: continue

    loss_g = np.log(gjr_fc[bv]) + oos_r2[bv] / gjr_fc[bv]
    loss_m = np.log(fc[bv]) + oos_r2[bv] / fc[bv]
    d = loss_g - loss_m
    dm = np.mean(d)
    T = len(d)
    ml = int(T**(1/3))
    hv = np.var(d, ddof=0)
    for j in range(1, ml+1):
        w = 1 - j/(ml+1)
        gj = np.mean((d[j:]-dm)*(d[:-j]-dm))
        hv += 2*w*gj
    t_stat = dm / np.sqrt(max(hv/T, 1e-20))
    sig = "YES" if abs(t_stat) > 3.0 else "No"
    print(f"  {name:<30} DM t={t_stat:+.3f} {sig}")
    results['dm_tests'][f'{name}_vs_GJR'] = {
        'dm_t': float(t_stat), 'significant': abs(t_stat) > 3.0}


# ============================================================
# VRP VALIDATION
# ============================================================
print(f"\n[4] VRP validation...")

# Compute g series for A4f (best model from K988) and correlate with independent VRP
# VRP = VIX²_{t-1}/252 - r²_t (simplified daily VRP proxy)
# Codex K999 fix: use VIX_{t-1} (lagged) not same-day VIX_t
vix_lag_oos = vix[oos_indices - 1]  # VIX_{t-1} for each OOS day
vix_var = (vix_lag_oos ** 2) / 252  # annualized VIX²_{t-1} → daily
oos_ret_sq = r2[oos_indices]

# Simple VRP proxy: implied - realized (positive = seller premium)
vrp_proxy = vix_var - oos_ret_sq

# For the best MF-X model (A4_vix_squared from K988, need to reconstruct g)
# We can approximate: g ≈ forecast / tau
# where tau = theta0 + theta1 * VIX²_{t-1}
# But we don't have K988's A4f here. Instead, use A4n or A3f g values.
# Actually let's compute g from any available model.

for name in ['A4n_vix2_samplenorm', 'A2n_logexp_samplenorm', 'A3f_tau_t1_free_omega']:
    fc = forecasts[name]
    valid = ~np.isnan(fc) & (fc > 0)
    if valid.sum() < 100: continue

    # g ≈ sigma² / tau. For VIX² models: tau ≈ proportional to VIX²
    # So g ≈ forecast / (c * VIX²_{t-1})
    # Rank correlation between g and VRP doesn't need exact scaling
    g_proxy = fc[valid] / np.maximum(vix_var[valid], 1e-16)
    vrp_v = vrp_proxy[valid]

    rho_gv, p_gv = stats.spearmanr(g_proxy, vrp_v)
    print(f"  {name}: Spearman(g_proxy, VRP) = {rho_gv:.4f} (p={p_gv:.4f})")
    results[f'vrp_corr_{name}'] = {'spearman': float(rho_gv), 'p': float(p_gv)}

# Also: direct r²/VIX² ratio vs VRP
ratio = oos_ret_sq / np.maximum(vix_var, 1e-16)
rho_rv, p_rv = stats.spearmanr(ratio, vrp_proxy)
print(f"  r²/VIX² vs VRP: Spearman = {rho_rv:.4f} (p={p_rv:.4f})")
results['vrp_corr_raw_ratio'] = {'spearman': float(rho_rv), 'p': float(p_rv)}


# ============================================================
# SAVE
# ============================================================
results['metadata'] = {
    'experiment_id': EXPERIMENT_ID,
    'elapsed': time.time() - START_TIME,
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'n_oos': n_oos, 'n_refits': refit_count,
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Saved to {RESULTS_PATH}")
print(f"  Total: {time.time()-START_TIME:.0f}s")
print(f"{'='*70}")
print(f"K988b COMPLETE")
print(f"{'='*70}")
