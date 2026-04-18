"""
K462: STGARCH + GARCH-X Methods on Taiwan 0050.TW
===================================================
[提出: 用戶, 執行: Claude]

背景:
- 美股 SPY 上多次 GARCH-X / STGARCH null result（K431, K438, T5c 等）
- 用戶假說：台股受外部 regime shift 影響更大，美股無效的方法可能對台股有效
- 台股特性：amplification factor 4.6x, GJR gamma 0.088-0.146（較低）
- US lead-lag confirmed (T32/T33): SPY(t)→tw50(t+1) r=0.376
- VIX 對台股是真正外生信息（前一天 VIX，時區差異）

Models:
1. GJR-GARCH baseline (台股)
2. GARCH-X with lagged VIX² (δ·VIX²_{t-1}/252)
3. GARCH-X with lagged SPY return² (δ·r²_SPY,{t-1})
4. GARCH-X with both VIX² + SPY return²
5. STGARCH with VIX as transition variable
6. Simple SPY vol proxy: σ²_tw,t = a + b·σ²_SPY,{t-1}

Literature:
- González-Rivera (1998) STGARCH
- Han & Kristensen (2014) GARCH-X
- T32/T33 lead-lag analysis

Data: 0050.TW + SPY + ^VIX, 2008-01-01 ~ 2026-03-25 (yfinance)
OOS: 2023-01-01 ~ 2024-12-31
Window: 2000, refit every 21 days
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy import stats
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox
import yfinance as yf
import json, time, warnings

warnings.filterwarnings('ignore')

# ============================================================
# CORE FUNCTIONS
# ============================================================

def gjr_filter(params, returns):
    """GJR-GARCH(1,1) filter. params: [omega, alpha, gamma, beta]"""
    omega, alpha, gamma_p, beta = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        lev = float(returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + gamma_p * lev + beta * h[t-1]
        h[t] = max(h[t], 1e-8)
    return h

def gjr_negll(params, returns):
    omega, alpha, gamma_p, beta = params
    if omega < 1e-8 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    if alpha + gamma_p/2 + beta >= 1.0:
        return 1e10
    h = gjr_filter(params, returns)
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def gjr_x1_filter(params, returns, X1):
    """GJR-GARCH-X with 1 exogenous variable. params: [omega, alpha, gamma, beta, delta1]"""
    omega, alpha, gamma_p, beta, delta1 = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        lev = float(returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + gamma_p * lev + beta * h[t-1] + delta1 * X1[t-1]
        h[t] = max(h[t], 1e-8)
    return h

def gjr_x1_negll(params, returns, X1):
    omega, alpha, gamma_p, beta, delta1 = params
    if omega < 1e-8 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    if alpha + gamma_p/2 + beta >= 1.0:
        return 1e10
    h = gjr_x1_filter(params, returns, X1)
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def gjr_x2_filter(params, returns, X1, X2):
    """GJR-GARCH-X with 2 exogenous variables. params: [omega, alpha, gamma, beta, delta1, delta2]"""
    omega, alpha, gamma_p, beta, delta1, delta2 = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        lev = float(returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + gamma_p * lev + beta * h[t-1] + delta1 * X1[t-1] + delta2 * X2[t-1]
        h[t] = max(h[t], 1e-8)
    return h

def gjr_x2_negll(params, returns, X1, X2):
    omega, alpha, gamma_p, beta, delta1, delta2 = params
    if omega < 1e-8 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    if alpha + gamma_p/2 + beta >= 1.0:
        return 1e10
    h = gjr_x2_filter(params, returns, X1, X2)
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def stgarch_filter(params, returns, tv):
    """STGARCH filter. params: [mu, w1, a1, b1, w2, a2, b2, gam, c]"""
    mu, w1, a1, b1, w2, a2, b2, gam, c = params
    T = len(returns)
    eps = returns - mu
    h = np.empty(T)
    h[0] = max(np.var(eps[:min(100, T)]), 1e-6)
    for t in range(1, T):
        arg = gam * (tv[t-1] - c)
        if arg > 500: G = 1.0
        elif arg < -500: G = 0.0
        else: G = 1.0 / (1.0 + np.exp(-arg))
        ht = w1 + a1 * eps[t-1]**2 + b1 * h[t-1] + G * (w2 + a2 * eps[t-1]**2 + b2 * h[t-1])
        h[t] = ht if ht > 1e-8 else 1e-8
    return h, eps

def stgarch_negll(params, returns, tv):
    h, eps = stgarch_filter(params, returns, tv)
    ll = -0.5 * np.sum(np.log(h) + eps**2 / h)
    return -ll if np.isfinite(ll) else 1e10

# ============================================================
# FITTING FUNCTIONS
# ============================================================

def fit_gjr(returns, n_starts=3):
    var0 = np.var(returns)
    bounds = [(1e-8, var0*2), (1e-8, 0.5), (1e-8, 0.5), (1e-8, 0.999)]
    starts = [
        [var0*0.05, 0.05, 0.05, 0.90],
        [var0*0.02, 0.03, 0.08, 0.92],
        [var0*0.10, 0.08, 0.03, 0.85],
    ]
    best = None
    for x0 in starts[:n_starts]:
        try:
            r = minimize(gjr_negll, x0, args=(returns,), method='L-BFGS-B',
                         bounds=bounds, options={'maxiter': 500, 'ftol': 1e-12})
            if best is None or r.fun < best.fun:
                best = r
        except: pass
    if best is None or best.fun > 1e9:
        return None
    p = best.x
    return {
        'params': {'omega': p[0], 'alpha': p[1], 'gamma': p[2], 'beta': p[3]},
        'persistence': p[1] + p[2]/2 + p[3],
        'converged': best.success, 'nll': best.fun,
        'h': gjr_filter(p, returns), 'n_params': 4,
        'loglik': -best.fun,
        'aic': 2*best.fun + 2*4, 'bic': 2*best.fun + 4*np.log(len(returns))
    }

def fit_gjr_x1(returns, X1, n_starts=4):
    var0 = np.var(returns)
    bounds = [(1e-8, var0*2), (1e-8, 0.5), (1e-8, 0.5), (1e-8, 0.999), (-1.0, 1.0)]
    starts = [
        [var0*0.05, 0.05, 0.05, 0.88, 0.001],
        [var0*0.02, 0.03, 0.08, 0.90, 0.005],
        [var0*0.10, 0.08, 0.03, 0.85, 0.01],
        [var0*0.05, 0.05, 0.05, 0.88, -0.001],
    ]
    best = None
    for x0 in starts[:n_starts]:
        try:
            r = minimize(gjr_x1_negll, x0, args=(returns, X1), method='L-BFGS-B',
                         bounds=bounds, options={'maxiter': 500, 'ftol': 1e-12})
            if best is None or r.fun < best.fun:
                best = r
        except: pass
    if best is None or best.fun > 1e9:
        return None
    p = best.x
    return {
        'params': {'omega': p[0], 'alpha': p[1], 'gamma': p[2], 'beta': p[3], 'delta1': p[4]},
        'persistence': p[1] + p[2]/2 + p[3],
        'converged': best.success, 'nll': best.fun,
        'h': gjr_x1_filter(p, returns, X1), 'n_params': 5,
        'loglik': -best.fun,
        'aic': 2*best.fun + 2*5, 'bic': 2*best.fun + 5*np.log(len(returns))
    }

def fit_gjr_x2(returns, X1, X2, n_starts=4):
    var0 = np.var(returns)
    bounds = [(1e-8, var0*2), (1e-8, 0.5), (1e-8, 0.5), (1e-8, 0.999), (-1.0, 1.0), (-1.0, 1.0)]
    starts = [
        [var0*0.05, 0.05, 0.05, 0.85, 0.001, 0.005],
        [var0*0.02, 0.03, 0.08, 0.88, 0.005, 0.001],
        [var0*0.10, 0.08, 0.03, 0.82, 0.01, 0.01],
        [var0*0.05, 0.05, 0.05, 0.85, -0.001, 0.005],
    ]
    best = None
    for x0 in starts[:n_starts]:
        try:
            r = minimize(gjr_x2_negll, x0, args=(returns, X1, X2), method='L-BFGS-B',
                         bounds=bounds, options={'maxiter': 500, 'ftol': 1e-12})
            if best is None or r.fun < best.fun:
                best = r
        except: pass
    if best is None or best.fun > 1e9:
        return None
    p = best.x
    return {
        'params': {'omega': p[0], 'alpha': p[1], 'gamma': p[2], 'beta': p[3],
                   'delta1': p[4], 'delta2': p[5]},
        'persistence': p[1] + p[2]/2 + p[3],
        'converged': best.success, 'nll': best.fun,
        'h': gjr_x2_filter(p, returns, X1, X2), 'n_params': 6,
        'loglik': -best.fun,
        'aic': 2*best.fun + 2*6, 'bic': 2*best.fun + 6*np.log(len(returns))
    }

def fit_stgarch(returns, tv, tv_name='VIX', n_starts=5):
    """Fit STGARCH with multiple random starts."""
    T = len(returns)
    if tv_name == 'VIX':
        c_lo, c_hi = 10.0, 45.0
    else:
        c_lo, c_hi = 0.2, 4.0

    bounds = [(-1, 1), (1e-6, 5), (1e-6, 0.5), (0.01, 0.999),
              (-3, 3), (-0.3, 0.5), (-0.5, 0.5), (0.01, 200), (c_lo, c_hi)]

    best = None
    np.random.seed(42)
    for i in range(n_starts):
        x0 = [np.mean(returns) + np.random.randn()*0.01,
              np.random.uniform(0.005, 0.1), np.random.uniform(0.02, 0.15),
              np.random.uniform(0.7, 0.95), np.random.uniform(-0.05, 0.05),
              np.random.uniform(-0.05, 0.1), np.random.uniform(-0.1, 0.1),
              np.random.uniform(0.1, 50), np.random.uniform(c_lo, c_hi)]
        try:
            r = minimize(stgarch_negll, x0, args=(returns, tv),
                         method='L-BFGS-B', bounds=bounds,
                         options={'maxiter': 3000, 'ftol': 1e-10})
            if r.success and (best is None or r.fun < best.fun):
                best = r
        except: pass

    if best is None:
        return None
    p = best.x
    names = ['mu', 'omega1', 'alpha1', 'beta1', 'omega2', 'alpha2', 'beta2', 'gamma_st', 'c']
    d = {n: float(v) for n, v in zip(names, p)}
    d['persistence_low'] = d['alpha1'] + d['beta1']
    d['persistence_high'] = (d['alpha1']+d['alpha2']) + (d['beta1']+d['beta2'])
    d['loglik'] = float(-best.fun)
    d['aic'] = 2*9 + 2*best.fun
    d['bic'] = 9*np.log(T) + 2*best.fun
    d['converged'] = True
    d['T'] = T
    return d

# ============================================================
# NUMERICAL HESSIAN for standard errors
# ============================================================
def numerical_hessian(negll_func, params, *args, eps=1e-4):
    """Compute numerical Hessian of negative log-likelihood."""
    n = len(params)
    H = np.zeros((n, n))
    f0 = negll_func(params, *args)
    for i in range(n):
        for j in range(i, n):
            p_pp = params.copy(); p_pp[i] += eps; p_pp[j] += eps
            p_pm = params.copy(); p_pm[i] += eps; p_pm[j] -= eps
            p_mp = params.copy(); p_mp[i] -= eps; p_mp[j] += eps
            p_mm = params.copy(); p_mm[i] -= eps; p_mm[j] -= eps
            H[i,j] = (negll_func(p_pp,*args) - negll_func(p_pm,*args) - negll_func(p_mp,*args) + negll_func(p_mm,*args)) / (4*eps**2)
            H[j,i] = H[i,j]
    return H

def compute_se(negll_func, opt_params, *args):
    """Compute standard errors and t-stats from Hessian."""
    H = numerical_hessian(negll_func, np.array(opt_params), *args)
    try:
        cov = np.linalg.inv(H)
        se = np.sqrt(np.abs(np.diag(cov)))
        t_stats = np.array(opt_params) / se
        return se, t_stats
    except:
        return None, None

# ============================================================
# EVALUATION
# ============================================================
def qlike_loss(f, r):
    return np.log(f) + r / f

def compute_metrics(f, r, name=''):
    v = np.isfinite(f) & np.isfinite(r) & (f > 0)
    f, r = f[v], r[v]
    return {'name': name, 'qlike': float(np.mean(np.log(f) + r/f)),
            'mse': float(np.mean((f-r)**2)), 'mae': float(np.mean(np.abs(f-r))),
            'n_obs': int(v.sum()), 'mean_forecast': float(np.mean(f)),
            'mean_realized': float(np.mean(r))}

def dm_test(loss1, loss2):
    d = loss1 - loss2
    T = len(d)
    dm = np.mean(d) / np.sqrt(np.var(d, ddof=0) / T)
    p = 2 * (1 - stats.norm.cdf(abs(dm)))
    return float(dm), float(p)

# ============================================================
# ROLLING OOS FORECAST
# ============================================================
def rolling_oos_gjr(returns, dates, oos_start, oos_end, window=2000, refit_every=21):
    """Rolling OOS for GJR-GARCH baseline."""
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]
    forecasts, realized, fdates = [], [], []
    params = None; last_refit = -refit_every

    for count, idx in enumerate(oos_idx):
        if idx - last_refit >= refit_every or params is None:
            est_start = max(0, idx - window)
            fit = fit_gjr(returns[est_start:idx])
            if fit is not None:
                params = [fit['params']['omega'], fit['params']['alpha'],
                          fit['params']['gamma'], fit['params']['beta']]
                last_refit = idx
            elif params is None:
                continue

        # Filter on recent data
        lookback = min(200, idx)
        h = gjr_filter(params, returns[idx-lookback:idx])
        h_last = h[-1]
        eps_last = returns[idx-1]

        # 1-step forecast
        lev = float(eps_last < 0) * eps_last**2
        h_f = params[0] + params[1]*eps_last**2 + params[2]*lev + params[3]*h_last
        h_f = max(h_f, 1e-8)

        forecasts.append(h_f)
        realized.append(returns[idx]**2)
        fdates.append(dates[idx])

        if (count+1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)}")

    return np.array(forecasts), np.array(realized), fdates

def rolling_oos_gjr_x1(returns, X1, dates, oos_start, oos_end, window=2000, refit_every=21):
    """Rolling OOS for GJR-GARCH-X with 1 exogenous."""
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]
    forecasts, realized, fdates = [], [], []
    params = None; last_refit = -refit_every

    for count, idx in enumerate(oos_idx):
        if idx - last_refit >= refit_every or params is None:
            est_start = max(0, idx - window)
            fit = fit_gjr_x1(returns[est_start:idx], X1[est_start:idx])
            if fit is not None:
                params = [fit['params']['omega'], fit['params']['alpha'],
                          fit['params']['gamma'], fit['params']['beta'],
                          fit['params']['delta1']]
                last_refit = idx
            elif params is None:
                continue

        lookback = min(200, idx)
        h = gjr_x1_filter(params, returns[idx-lookback:idx], X1[idx-lookback:idx])
        h_last = h[-1]
        eps_last = returns[idx-1]

        lev = float(eps_last < 0) * eps_last**2
        h_f = params[0] + params[1]*eps_last**2 + params[2]*lev + params[3]*h_last + params[4]*X1[idx-1]
        h_f = max(h_f, 1e-8)

        forecasts.append(h_f)
        realized.append(returns[idx]**2)
        fdates.append(dates[idx])

        if (count+1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)}")

    return np.array(forecasts), np.array(realized), fdates

def rolling_oos_gjr_x2(returns, X1, X2, dates, oos_start, oos_end, window=2000, refit_every=21):
    """Rolling OOS for GJR-GARCH-X with 2 exogenous."""
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]
    forecasts, realized, fdates = [], [], []
    params = None; last_refit = -refit_every

    for count, idx in enumerate(oos_idx):
        if idx - last_refit >= refit_every or params is None:
            est_start = max(0, idx - window)
            fit = fit_gjr_x2(returns[est_start:idx], X1[est_start:idx], X2[est_start:idx])
            if fit is not None:
                params = [fit['params']['omega'], fit['params']['alpha'],
                          fit['params']['gamma'], fit['params']['beta'],
                          fit['params']['delta1'], fit['params']['delta2']]
                last_refit = idx
            elif params is None:
                continue

        lookback = min(200, idx)
        h = gjr_x2_filter(params, returns[idx-lookback:idx], X1[idx-lookback:idx], X2[idx-lookback:idx])
        h_last = h[-1]
        eps_last = returns[idx-1]

        lev = float(eps_last < 0) * eps_last**2
        h_f = params[0] + params[1]*eps_last**2 + params[2]*lev + params[3]*h_last + params[4]*X1[idx-1] + params[5]*X2[idx-1]
        h_f = max(h_f, 1e-8)

        forecasts.append(h_f)
        realized.append(returns[idx]**2)
        fdates.append(dates[idx])

        if (count+1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)}")

    return np.array(forecasts), np.array(realized), fdates

def rolling_oos_stgarch(returns, tv, dates, oos_start, oos_end, window=2000, refit_every=21, tv_name='VIX'):
    """Rolling OOS for STGARCH."""
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]
    forecasts, realized, fdates = [], [], []
    params = None; last_refit = -refit_every
    h_t = None; eps_t = None

    for count, idx in enumerate(oos_idx):
        if idx - last_refit >= refit_every or params is None:
            est_start = max(0, idx - window)
            d = fit_stgarch(returns[est_start:idx], tv[est_start:idx], tv_name=tv_name, n_starts=3)
            if d is not None:
                params = [d[k] for k in ['mu','omega1','alpha1','beta1','omega2','alpha2','beta2','gamma_st','c']]
                last_refit = idx
                lookback = min(200, idx)
                h_arr, eps_arr = stgarch_filter(params, returns[idx-lookback:idx], tv[idx-lookback:idx])
                h_t = h_arr[-1]; eps_t = eps_arr[-1]
            elif params is None:
                continue

        # 1-step forecast
        mu, w1, a1, b1, w2, a2, b2, gam, c = params
        s_prev = tv[idx-1]
        arg = gam * (s_prev - c)
        if arg > 500: G = 1.0
        elif arg < -500: G = 0.0
        else: G = 1.0 / (1.0 + np.exp(-arg))
        h_f = w1 + a1*eps_t**2 + b1*h_t + G*(w2 + a2*eps_t**2 + b2*h_t)
        h_f = max(h_f, 1e-8)

        forecasts.append(h_f)
        realized.append(returns[idx]**2)
        fdates.append(dates[idx])

        # Update state
        eps_t = returns[idx] - mu
        s_cur = tv[idx-1]
        arg2 = gam * (s_cur - c)
        if arg2 > 500: G2 = 1.0
        elif arg2 < -500: G2 = 0.0
        else: G2 = 1.0 / (1.0 + np.exp(-arg2))
        h_t = w1 + a1*eps_t**2 + b1*h_t + G2*(w2 + a2*eps_t**2 + b2*h_t)
        h_t = max(h_t, 1e-8)

        if (count+1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)}")

    return np.array(forecasts), np.array(realized), fdates

def rolling_oos_spy_proxy(tw_returns, spy_rv_lag, dates, oos_start, oos_end, window=2000, refit_every=21):
    """Rolling OOS for simple SPY vol proxy: h_tw = a + b * spy_rv_lag."""
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]
    forecasts, realized, fdates = [], [], []
    a_coef = None; b_coef = None; last_refit = -refit_every

    for count, idx in enumerate(oos_idx):
        if idx - last_refit >= refit_every or a_coef is None:
            est_start = max(0, idx - window)
            # OLS: tw_rv = a + b * spy_rv_lag
            y = tw_returns[est_start:idx]**2
            x = spy_rv_lag[est_start:idx]
            valid = np.isfinite(y) & np.isfinite(x)
            if valid.sum() > 100:
                y_v, x_v = y[valid], x[valid]
                X_mat = np.column_stack([np.ones(len(x_v)), x_v])
                try:
                    beta = np.linalg.lstsq(X_mat, y_v, rcond=None)[0]
                    a_coef, b_coef = beta[0], beta[1]
                    last_refit = idx
                except:
                    if a_coef is None: continue
            elif a_coef is None:
                continue

        h_f = a_coef + b_coef * spy_rv_lag[idx-1]
        h_f = max(h_f, 1e-8)

        forecasts.append(h_f)
        realized.append(tw_returns[idx]**2)
        fdates.append(dates[idx])

        if (count+1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)}")

    return np.array(forecasts), np.array(realized), fdates

# ============================================================
# MAIN
# ============================================================
print("=" * 70)
print("K462: STGARCH + GARCH-X Methods on Taiwan 0050.TW")
print("=" * 70)
t_start = time.time()

# --- Data Download ---
print("\n[0] Downloading data...")
tw50 = yf.download('0050.TW', start='2008-01-01', end='2026-03-25', progress=False)
spy = yf.download('SPY', start='2008-01-01', end='2026-03-25', progress=False)
vix = yf.download('^VIX', start='2008-01-01', end='2026-03-25', progress=False)

for df in [tw50, spy, vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# --- Returns ---
tw50['Return'] = tw50['Close'].pct_change() * 100
spy['Return'] = spy['Close'].pct_change() * 100
tw50 = tw50.dropna(subset=['Return'])
spy = spy.dropna(subset=['Return'])

# --- Data Quality: Handle stock split artifacts ---
# 0050.TW had a 4:1 split on 2014-01-02. yfinance adjusted close doesn't
# properly handle this, creating a spurious -75% return.
# Filter out returns > |20%| which are clearly corporate actions, not real returns.
n_before = len(tw50)
split_mask = tw50['Return'].abs() > 20.0
n_filtered = split_mask.sum()
if n_filtered > 0:
    split_dates = tw50.index[split_mask].strftime('%Y-%m-%d').tolist()
    print(f"  WARNING: Filtered {n_filtered} split artifact(s): {split_dates}")
    print(f"    Affected returns: {tw50.loc[split_mask, 'Return'].values}")
    tw50 = tw50[~split_mask]
    print(f"    {n_before} → {len(tw50)} observations")

# --- Timezone handling ---
for df in [tw50, spy, vix]:
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

# --- Align: Taiwan trading days, US data lag 1 ---
# SPY and VIX from previous US trading day
spy_ret_lag = spy['Return'].shift(1)  # SPY return, lagged 1 day
spy_ret_sq_lag = (spy_ret_lag ** 2)   # SPY return squared, lagged

vix_close = vix['Close']
vix_var_lag = (vix_close ** 2 / 252.0).shift(1)  # VIX² / 252, lagged

# SPY realized vol (rolling 21-day)
spy_rv_21 = (spy['Return'].rolling(21).std() ** 2).shift(1)  # lagged SPY variance

# Forward-fill US data to Taiwan trading days
tw_dates = tw50.index
spy_ret_sq_aligned = spy_ret_sq_lag.reindex(tw_dates, method='ffill')
vix_var_aligned = vix_var_lag.reindex(tw_dates, method='ffill')
spy_rv_aligned = spy_rv_21.reindex(tw_dates, method='ffill')

# Combine into single DataFrame
data = pd.DataFrame({
    'tw_return': tw50['Return'],
    'spy_ret_sq': spy_ret_sq_aligned,
    'vix_var': vix_var_aligned,
    'spy_rv': spy_rv_aligned
}, index=tw_dates).dropna()

print(f"  0050.TW: {len(tw50)} obs")
print(f"  SPY: {len(spy)} obs")
print(f"  VIX: {len(vix)} obs")
print(f"  Aligned data: {len(data)} obs ({data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')})")

# Arrays
tw_ret = data['tw_return'].values
spy_ret_sq = data['spy_ret_sq'].values
vix_var = data['vix_var'].values
spy_rv = data['spy_rv'].values
dates_arr = data.index

# ============================================================
# STEP 1: Descriptive Statistics & Diagnostics
# ============================================================
print("\n" + "=" * 70)
print("[1] DESCRIPTIVE STATISTICS & DIAGNOSTICS")
print("=" * 70)

desc = {}
for name, arr in [('tw_return(%)', tw_ret), ('spy_ret_sq', spy_ret_sq),
                   ('vix_var', vix_var), ('spy_rv', spy_rv)]:
    d = {
        'mean': float(np.mean(arr)), 'std': float(np.std(arr)),
        'skew': float(stats.skew(arr)), 'kurt': float(stats.kurtosis(arr)),
        'min': float(np.min(arr)), 'max': float(np.max(arr)),
        'N': len(arr)
    }
    desc[name] = d
    print(f"  {name}: mean={d['mean']:.4f}, std={d['std']:.4f}, skew={d['skew']:.2f}, kurt={d['kurt']:.1f}")

# ADF
print("\n  ADF Tests:")
adf_results = {}
for name, arr in [('tw_return', tw_ret), ('spy_ret_sq', spy_ret_sq), ('vix_var', vix_var)]:
    adf_s, adf_p = adfuller(arr, maxlag=20, autolag='AIC')[:2]
    adf_results[name] = {'statistic': float(adf_s), 'p_value': float(adf_p)}
    print(f"    {name}: ADF={adf_s:.3f}, p={adf_p:.6f} ({'stationary' if adf_p < 0.05 else 'NON-stationary'})")

# ARCH-LM
arch_s, arch_p = het_arch(tw_ret, nlags=10)[:2]
print(f"\n  ARCH-LM(10) on tw_return: stat={arch_s:.1f}, p={arch_p:.2e}")
arch_lm = {'lm_stat': float(arch_s), 'p_value': float(arch_p)}

# Ljung-Box
lb = acorr_ljungbox(tw_ret**2, lags=[10], return_df=True)
lb_stat = float(lb['lb_stat'].values[0])
lb_pval = float(lb['lb_pvalue'].values[0])
print(f"  Ljung-Box(10) on tw²: stat={lb_stat:.1f}, p={lb_pval:.2e}")

# Cross-correlation: SPY -> TW
corr_spy_tw = np.corrcoef(spy_ret_sq[1:], tw_ret[1:]**2)[0, 1]
print(f"\n  Corr(SPY r²_lag, TW r²): {corr_spy_tw:.4f}")
corr_vix_tw = np.corrcoef(vix_var[1:], tw_ret[1:]**2)[0, 1]
print(f"  Corr(VIX²/252_lag, TW r²): {corr_vix_tw:.4f}")

# ============================================================
# STEP 2: FULL-SAMPLE ESTIMATION (before OOS)
# ============================================================
print("\n" + "=" * 70)
print("[2] FULL-SAMPLE ESTIMATION (before OOS)")
print("=" * 70)

oos_start = '2023-01-01'
oos_end = '2024-12-31'
is_mask = dates_arr < oos_start

tw_is = tw_ret[is_mask]
spy_sq_is = spy_ret_sq[is_mask]
vix_var_is = vix_var[is_mask]
spy_rv_is = spy_rv[is_mask]

# Use last 2000 observations for IS estimation
n_is = min(2000, len(tw_is))
r_is = tw_is[-n_is:]
spy_sq_is_fit = spy_sq_is[-n_is:]
vix_var_is_fit = vix_var_is[-n_is:]

print(f"  IS period: last {n_is} obs before {oos_start}")

# Model 1: GJR baseline
print("\n  Fitting Model 1: GJR-GARCH(1,1) baseline...")
fit_base = fit_gjr(r_is)
if fit_base:
    print(f"    Converged={fit_base['converged']}, Persistence={fit_base['persistence']:.4f}")
    for k, v in fit_base['params'].items():
        print(f"    {k}={v:.6f}")

# Model 2: GARCH-X with VIX²
print("\n  Fitting Model 2: GARCH-X with VIX²_{t-1}/252...")
fit_vix = fit_gjr_x1(r_is, vix_var_is_fit)
if fit_vix:
    print(f"    Converged={fit_vix['converged']}, Persistence={fit_vix['persistence']:.4f}")
    for k, v in fit_vix['params'].items():
        print(f"    {k}={v:.6f}")

# Model 3: GARCH-X with SPY r²
print("\n  Fitting Model 3: GARCH-X with SPY r²_{t-1}...")
fit_spy = fit_gjr_x1(r_is, spy_sq_is_fit)
if fit_spy:
    print(f"    Converged={fit_spy['converged']}, Persistence={fit_spy['persistence']:.4f}")
    for k, v in fit_spy['params'].items():
        print(f"    {k}={v:.6f}")

# Model 4: GARCH-X with both
print("\n  Fitting Model 4: GARCH-X with VIX² + SPY r²...")
fit_both = fit_gjr_x2(r_is, vix_var_is_fit, spy_sq_is_fit)
if fit_both:
    print(f"    Converged={fit_both['converged']}, Persistence={fit_both['persistence']:.4f}")
    for k, v in fit_both['params'].items():
        print(f"    {k}={v:.6f}")

# Model 5: STGARCH with VIX transition
# Need VIX level for transition — use vix_close aligned to tw dates
vix_level_aligned = vix_close.reindex(tw_dates, method='ffill')
vix_level = vix_level_aligned.reindex(data.index).values
vix_level_is = vix_level[is_mask][-n_is:]

print("\n  Fitting Model 5: STGARCH with VIX transition...")
fit_st = fit_stgarch(r_is, vix_level_is, tv_name='VIX', n_starts=5)
if fit_st:
    print(f"    Converged={fit_st['converged']}")
    print(f"    gamma_st={fit_st['gamma_st']:.3f}, c={fit_st['c']:.3f}")
    print(f"    persistence_low={fit_st['persistence_low']:.4f}, persistence_high={fit_st['persistence_high']:.4f}")

# IS comparison table
print(f"\n  {'Model':<30} {'k':>3} {'LogLik':>10} {'AIC':>10} {'BIC':>10}")
print("  " + "-" * 66)
is_table = []
for name, fit in [("GJR baseline", fit_base), ("GARCH-X(VIX²)", fit_vix),
                  ("GARCH-X(SPY r²)", fit_spy), ("GARCH-X(VIX²+SPY r²)", fit_both)]:
    if fit:
        is_table.append((name, fit['n_params'], fit['loglik'], fit['aic'], fit['bic']))
if fit_st:
    is_table.append(("STGARCH(VIX)", 9, fit_st['loglik'], fit_st['aic'], fit_st['bic']))

for name, k, ll, aic, bic in sorted(is_table, key=lambda x: x[4]):
    print(f"  {name:<30} {k:>3} {ll:>10.1f} {aic:>10.1f} {bic:>10.1f}")

# --- Residual ARCH-LM for IS ---
print("\n  Residual ARCH-LM Tests:")
is_residual = {}
for name, fit in [("GJR baseline", fit_base), ("GARCH-X(VIX²)", fit_vix),
                  ("GARCH-X(SPY r²)", fit_spy), ("GARCH-X(VIX²+SPY r²)", fit_both)]:
    if fit:
        std_resid = r_is / np.sqrt(fit['h'])
        try:
            arch_test = het_arch(std_resid, nlags=10)
            remaining = "YES" if arch_test[1] < 0.05 else "NO"
            print(f"    {name}: stat={arch_test[0]:.2f}, p={arch_test[1]:.4f} (remaining ARCH: {remaining})")
            is_residual[name] = {'lm_stat': float(arch_test[0]), 'p_value': float(arch_test[1])}
        except:
            pass

if fit_st:
    p_st = [fit_st[k] for k in ['mu','omega1','alpha1','beta1','omega2','alpha2','beta2','gamma_st','c']]
    h_st, eps_st = stgarch_filter(p_st, r_is, vix_level_is)
    z_st = eps_st / np.sqrt(h_st)
    try:
        arch_test = het_arch(z_st, nlags=10)
        remaining = "YES" if arch_test[1] < 0.05 else "NO"
        print(f"    STGARCH(VIX): stat={arch_test[0]:.2f}, p={arch_test[1]:.4f} (remaining ARCH: {remaining})")
        is_residual['STGARCH(VIX)'] = {'lm_stat': float(arch_test[0]), 'p_value': float(arch_test[1])}
    except:
        pass

# --- Delta significance ---
print("\n  Delta Coefficient Significance:")
delta_significance = {}

if fit_vix:
    p_arr = np.array([fit_vix['params'][k] for k in ['omega','alpha','gamma','beta','delta1']])
    se, t_stat = compute_se(gjr_x1_negll, p_arr, r_is, vix_var_is_fit)
    if se is not None:
        delta1_se = se[4]; delta1_t = t_stat[4]
        delta1_p = 2 * (1 - stats.norm.cdf(abs(delta1_t)))
        print(f"    GARCH-X(VIX²): delta={fit_vix['params']['delta1']:.6f}, "
              f"SE={delta1_se:.6f}, t={delta1_t:.3f}, p={delta1_p:.4f}")
        delta_significance['GARCH-X(VIX²)'] = {
            'delta': float(fit_vix['params']['delta1']), 'se': float(delta1_se),
            't_stat': float(delta1_t), 'p_value': float(delta1_p)
        }

if fit_spy:
    p_arr = np.array([fit_spy['params'][k] for k in ['omega','alpha','gamma','beta','delta1']])
    se, t_stat = compute_se(gjr_x1_negll, p_arr, r_is, spy_sq_is_fit)
    if se is not None:
        delta1_se = se[4]; delta1_t = t_stat[4]
        delta1_p = 2 * (1 - stats.norm.cdf(abs(delta1_t)))
        print(f"    GARCH-X(SPY r²): delta={fit_spy['params']['delta1']:.6f}, "
              f"SE={delta1_se:.6f}, t={delta1_t:.3f}, p={delta1_p:.4f}")
        delta_significance['GARCH-X(SPY_r2)'] = {
            'delta': float(fit_spy['params']['delta1']), 'se': float(delta1_se),
            't_stat': float(delta1_t), 'p_value': float(delta1_p)
        }

if fit_both:
    p_arr = np.array([fit_both['params'][k] for k in ['omega','alpha','gamma','beta','delta1','delta2']])
    se, t_stat = compute_se(gjr_x2_negll, p_arr, r_is, vix_var_is_fit, spy_sq_is_fit)
    if se is not None:
        d1_se = se[4]; d1_t = t_stat[4]; d1_p = 2*(1-stats.norm.cdf(abs(d1_t)))
        d2_se = se[5]; d2_t = t_stat[5]; d2_p = 2*(1-stats.norm.cdf(abs(d2_t)))
        print(f"    GARCH-X(both): delta1(VIX²)={fit_both['params']['delta1']:.6f}, "
              f"t={d1_t:.3f}, p={d1_p:.4f}")
        print(f"                   delta2(SPY r²)={fit_both['params']['delta2']:.6f}, "
              f"t={d2_t:.3f}, p={d2_p:.4f}")
        delta_significance['GARCH-X(both)'] = {
            'delta1_VIX': float(fit_both['params']['delta1']), 'delta1_t': float(d1_t), 'delta1_p': float(d1_p),
            'delta2_SPY': float(fit_both['params']['delta2']), 'delta2_t': float(d2_t), 'delta2_p': float(d2_p)
        }

# ============================================================
# STEP 3: ROLLING OOS FORECASTING
# ============================================================
print("\n" + "=" * 70)
print("[3] ROLLING OOS FORECASTING (2023-01 to 2024-12, w=2000, refit=21d)")
print("=" * 70)

# Ensure we have VIX level array for full data
vix_level_full = vix_level

# Model 1: GJR baseline
print("\n  [1/6] GJR-GARCH(1,1) baseline...")
t0 = time.time()
f1, r1, d1 = rolling_oos_gjr(tw_ret, dates_arr, oos_start, oos_end)
print(f"    {time.time()-t0:.0f}s, n={len(f1)}")

# Model 2: GARCH-X with VIX²
print("\n  [2/6] GARCH-X with VIX²_{t-1}/252...")
t0 = time.time()
f2, r2, d2 = rolling_oos_gjr_x1(tw_ret, vix_var, dates_arr, oos_start, oos_end)
print(f"    {time.time()-t0:.0f}s, n={len(f2)}")

# Model 3: GARCH-X with SPY r²
print("\n  [3/6] GARCH-X with SPY r²_{t-1}...")
t0 = time.time()
f3, r3, d3 = rolling_oos_gjr_x1(tw_ret, spy_ret_sq, dates_arr, oos_start, oos_end)
print(f"    {time.time()-t0:.0f}s, n={len(f3)}")

# Model 4: GARCH-X with both
print("\n  [4/6] GARCH-X with VIX² + SPY r²...")
t0 = time.time()
f4, r4, d4 = rolling_oos_gjr_x2(tw_ret, vix_var, spy_ret_sq, dates_arr, oos_start, oos_end)
print(f"    {time.time()-t0:.0f}s, n={len(f4)}")

# Model 5: STGARCH with VIX transition
print("\n  [5/6] STGARCH with VIX transition...")
t0 = time.time()
f5, r5, d5 = rolling_oos_stgarch(tw_ret, vix_level_full, dates_arr, oos_start, oos_end, tv_name='VIX')
print(f"    {time.time()-t0:.0f}s, n={len(f5)}")

# Model 6: SPY vol proxy
print("\n  [6/6] SPY vol proxy...")
t0 = time.time()
f6, r6, d6 = rolling_oos_spy_proxy(tw_ret, spy_rv, dates_arr, oos_start, oos_end)
print(f"    {time.time()-t0:.0f}s, n={len(f6)}")

# ============================================================
# STEP 4: OOS COMPARISON
# ============================================================
print("\n" + "=" * 70)
print("[4] OOS PERFORMANCE COMPARISON")
print("=" * 70)

models = [
    ('GJR baseline', f1, r1),
    ('GARCH-X(VIX²)', f2, r2),
    ('GARCH-X(SPY r²)', f3, r3),
    ('GARCH-X(VIX²+SPY)', f4, r4),
    ('STGARCH(VIX)', f5, r5),
    ('SPY vol proxy', f6, r6),
]

all_metrics = []
print(f"\n  {'Model':<25} {'QLIKE':>10} {'MSE':>12} {'MAE':>10} {'N':>5}")
print("  " + "-" * 65)
for name, f, r in models:
    if len(f) > 0:
        m = compute_metrics(f, r, name)
        all_metrics.append(m)
        print(f"  {name:<25} {m['qlike']:>10.4f} {m['mse']:>12.4f} {m['mae']:>10.4f} {m['n_obs']:>5}")
    else:
        print(f"  {name:<25} {'FAILED':>10}")

# DM tests vs GJR baseline
print(f"\n  DM Tests vs GJR baseline:")
print(f"  {'Model':<25} {'DM t':>8} {'p-value':>10} {'QLIKE Δ%':>10} {'Result':>18}")
print("  " + "-" * 75)

dm_results = {}
for name, f, r in models:
    if 'GJR baseline' in name or len(f) == 0:
        continue
    n = min(len(f), len(f1))
    if n == 0: continue
    l_model = qlike_loss(f[:n], r[:n])
    l_base = qlike_loss(f1[:n], r1[:n])
    t_dm, p_dm = dm_test(l_model, l_base)
    qdiff = (np.mean(l_model) - np.mean(l_base)) / abs(np.mean(l_base)) * 100
    sig = "***" if p_dm < 0.01 else "**" if p_dm < 0.05 else "*" if p_dm < 0.10 else "NS"
    if t_dm < -1.96:
        result = f"BEATS GJR {sig}"
    elif t_dm > 1.96:
        result = f"GJR wins {sig}"
    else:
        result = f"No diff {sig}"
    dm_results[name] = {'dm_stat': t_dm, 'dm_pvalue': p_dm, 'qlike_diff_pct': qdiff, 'result': result}
    print(f"  {name:<25} {t_dm:>8.3f} {p_dm:>10.6f} {qdiff:>9.3f}% {result:>18}")

# ============================================================
# STEP 5: ROLLING CORRELATION STABILITY
# ============================================================
print("\n" + "=" * 70)
print("[5] ROLLING CORRELATION STABILITY (SPY→TW, VIX→TW)")
print("=" * 70)

# Rolling 252-day correlation of SPY return squared → next-day TW return squared
roll_window = 252
tw_r2 = tw_ret**2
roll_corr_spy = pd.Series(tw_r2).rolling(roll_window).corr(pd.Series(spy_ret_sq))
roll_corr_vix = pd.Series(tw_r2).rolling(roll_window).corr(pd.Series(vix_var))

rc_spy_valid = roll_corr_spy.dropna()
rc_vix_valid = roll_corr_vix.dropna()

print(f"  Rolling corr(SPY r², TW r²) 252d:")
print(f"    mean={rc_spy_valid.mean():.4f}, std={rc_spy_valid.std():.4f}")
print(f"    min={rc_spy_valid.min():.4f}, max={rc_spy_valid.max():.4f}")
print(f"  Rolling corr(VIX²/252, TW r²) 252d:")
print(f"    mean={rc_vix_valid.mean():.4f}, std={rc_vix_valid.std():.4f}")
print(f"    min={rc_vix_valid.min():.4f}, max={rc_vix_valid.max():.4f}")

roll_corr_stability = {
    'spy_tw': {
        'mean': float(rc_spy_valid.mean()), 'std': float(rc_spy_valid.std()),
        'min': float(rc_spy_valid.min()), 'max': float(rc_spy_valid.max())
    },
    'vix_tw': {
        'mean': float(rc_vix_valid.mean()), 'std': float(rc_vix_valid.std()),
        'min': float(rc_vix_valid.min()), 'max': float(rc_vix_valid.max())
    }
}

# ============================================================
# STEP 6: STGARCH TRANSITION ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("[6] STGARCH TRANSITION FUNCTION ANALYSIS")
print("=" * 70)

stgarch_analysis = {}
if fit_st:
    gam = fit_st['gamma_st']
    c = fit_st['c']
    G25 = c - np.log(3)/gam if gam > 0 else None
    G75 = c + np.log(3)/gam if gam > 0 else None
    width = (G75 - G25) if G25 and G75 else None

    speed = 'abrupt' if gam > 50 else ('smooth' if gam < 5 else 'moderate')
    print(f"  gamma={gam:.3f} ({speed}), c={c:.3f} (VIX threshold)")
    if width:
        print(f"  G=0.25 at VIX={G25:.1f}, G=0.75 at VIX={G75:.1f}, width={width:.1f}")

    p = fit_st
    print(f"  Low  regime (G→0, VIX<{c:.0f}): ω={p['omega1']:.4f} α={p['alpha1']:.4f} β={p['beta1']:.4f} pers={p['persistence_low']:.4f}")
    w_h = p['omega1']+p['omega2']
    a_h = p['alpha1']+p['alpha2']
    b_h = p['beta1']+p['beta2']
    p_h = a_h + b_h
    print(f"  High regime (G→1, VIX>{c:.0f}): ω={w_h:.4f} α={a_h:.4f} β={b_h:.4f} pers={p_h:.4f}")

    # Check for issues
    if p['persistence_low'] > 1.0:
        print(f"  WARNING: Low-regime persistence > 1 ({p['persistence_low']:.4f})")
    if p_h > 1.0:
        print(f"  WARNING: High-regime persistence > 1 ({p_h:.4f})")
    if gam > 100:
        print(f"  WARNING: Very large gamma → abrupt transition (≈ Markov switching)")

    stgarch_analysis = {
        'gamma': gam, 'c': c, 'speed': speed,
        'G25_VIX': float(G25) if G25 else None,
        'G75_VIX': float(G75) if G75 else None,
        'width': float(width) if width else None,
        'persistence_low': p['persistence_low'],
        'persistence_high': p_h,
        'omega1': p['omega1'], 'alpha1': p['alpha1'], 'beta1': p['beta1'],
        'omega_high': w_h, 'alpha_high': a_h, 'beta_high': b_h
    }

# ============================================================
# STEP 7: COINTEGRATION (SPY-TW vol)
# ============================================================
print("\n" + "=" * 70)
print("[7] SPY-TW VOLATILITY COINTEGRATION")
print("=" * 70)

from statsmodels.tsa.stattools import coint

tw_vol_21 = pd.Series(tw_ret).rolling(21).std().values
spy_vol_21 = np.sqrt(spy_rv)  # already 21d rolling std squared

# valid mask
valid = np.isfinite(tw_vol_21) & np.isfinite(spy_vol_21) & (tw_vol_21 > 0) & (spy_vol_21 > 0)
tw_v = tw_vol_21[valid]
spy_v = spy_vol_21[valid]

coint_stat, coint_p, coint_cv = coint(tw_v, spy_v)
print(f"  Engle-Granger cointegration test:")
print(f"    t-stat={coint_stat:.3f}, p={coint_p:.4f}")
print(f"    Critical values: 1%={coint_cv[0]:.3f}, 5%={coint_cv[1]:.3f}, 10%={coint_cv[2]:.3f}")
print(f"    Cointegrated: {'YES' if coint_p < 0.05 else 'NO'}")

coint_result = {
    't_stat': float(coint_stat), 'p_value': float(coint_p),
    'cv_1pct': float(coint_cv[0]), 'cv_5pct': float(coint_cv[1]),
    'cointegrated': bool(coint_p < 0.05)
}

# ============================================================
# STEP 8: CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("[8] CONCLUSION")
print("=" * 70)

t_total = time.time() - t_start

# Find best model
if len(all_metrics) > 0:
    best_model = min(all_metrics, key=lambda x: x['qlike'])
    gjr_m = [m for m in all_metrics if 'GJR baseline' in m['name']]
    gjr_qlike = gjr_m[0]['qlike'] if gjr_m else None

    # Any model significantly beats GJR?
    any_sig_win = any(v['dm_pvalue'] < 0.05 and v['dm_stat'] < 0 for v in dm_results.values())
    any_sig_lose = any(v['dm_pvalue'] < 0.05 and v['dm_stat'] > 0 for v in dm_results.values())

    # Best non-baseline
    non_base = [m for m in all_metrics if 'GJR baseline' not in m['name']]
    if non_base and gjr_qlike:
        best_alt = min(non_base, key=lambda x: x['qlike'])
        diff = (best_alt['qlike'] - gjr_qlike) / abs(gjr_qlike) * 100

        if any_sig_win:
            conclusion = (f"POSITIVE: {best_alt['name']} significantly beats GJR on Taiwan 0050.TW! "
                         f"QLIKE diff={diff:.3f}%. US-null methods work on Taiwan market.")
            verdict = "POSITIVE"
        elif best_alt['qlike'] < gjr_qlike:
            conclusion = (f"PARTIAL: {best_alt['name']} numerically better (QLIKE diff={diff:.3f}%) but not "
                         f"statistically significant. Suggestive but inconclusive.")
            verdict = "PARTIAL"
        else:
            conclusion = (f"NULL: No model beats GJR baseline on Taiwan. Best alt: {best_alt['name']} "
                         f"(diff={diff:.3f}%). GARCH ceiling extends to Taiwan market.")
            verdict = "NULL"
    else:
        conclusion = "Unable to compute comparison."
        verdict = "ERROR"
        diff = 0
else:
    conclusion = "No models successfully estimated."
    verdict = "ERROR"
    diff = 0
    best_model = None

print(f"\n  Verdict: {verdict}")
print(f"  {conclusion}")
print(f"  Runtime: {t_total:.0f}s")

# ============================================================
# SAVE RESULTS
# ============================================================

# Prepare IS results
is_results_save = {}
for name, fit in [("GJR_baseline", fit_base), ("GARCH-X(VIX²)", fit_vix),
                  ("GARCH-X(SPY_r2)", fit_spy), ("GARCH-X(VIX²+SPY)", fit_both)]:
    if fit:
        is_results_save[name] = {
            'params': {k: float(v) for k, v in fit['params'].items()},
            'persistence': float(fit['persistence']),
            'converged': bool(fit['converged']),
            'loglik': float(fit['loglik']),
            'aic': float(fit['aic']), 'bic': float(fit['bic']),
            'n_params': fit['n_params']
        }

if fit_st:
    is_results_save['STGARCH(VIX)'] = {
        k: (float(v) if isinstance(v, (float, np.floating, int, np.integer)) else v)
        for k, v in fit_st.items() if k not in ['T']
    }

results = {
    'experiment_id': 'K462',
    'title': 'STGARCH + GARCH-X Methods on Taiwan 0050.TW',
    'proposer': '用戶', 'executor': 'Claude',
    'asset': '0050.TW',
    'data_source': 'yfinance (0050.TW, SPY, ^VIX)',
    'data_period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'total_obs': len(data),
    'oos_period': f"{oos_start} to {oos_end}",
    'window': 2000, 'refit_every': 21,
    'runtime_seconds': round(t_total, 1),
    'hypothesis': '美股無效的 GARCH-X / STGARCH 方法可能對台股有效（外部 regime shift, VIX 外生信息, lead-lag r=0.376）',
    'descriptive': desc,
    'adf_tests': adf_results,
    'arch_lm': arch_lm,
    'cross_correlations': {
        'corr_spy_r2_tw_r2': float(corr_spy_tw),
        'corr_vix_var_tw_r2': float(corr_vix_tw)
    },
    'in_sample': is_results_save,
    'in_sample_residual_arch': is_residual,
    'delta_significance': delta_significance,
    'oos_metrics': all_metrics,
    'dm_tests': {k: {kk: (float(vv) if isinstance(vv, (float, np.floating)) else vv)
                     for kk, vv in v.items()} for k, v in dm_results.items()},
    'rolling_correlation_stability': roll_corr_stability,
    'stgarch_transition_analysis': stgarch_analysis,
    'cointegration_spy_tw_vol': coint_result,
    'verdict': verdict,
    'conclusion': conclusion,
    'comparison_with_spy_results': {
        'K431_SPY_STGARCH': 'GJR wins on SPY, STGARCH does NOT beat GJR',
        'K438_SPY_GARCHX': 'GARCH-X(VRP) borderline on SPY, delta unstable',
        'T5c_TW_GARCHX': 'GARCH-X(SPY overnight) WORSE +4.7% on TW, VIX-only +11.8%',
        'hypothesis': 'Taiwan amplification (4.6x) and true exogeneity of VIX may change result'
    }
}

out_path = 'experiments/k462_taiwan_methods_results.json'
with open(out_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)
print(f"\nSaved: {out_path}")
