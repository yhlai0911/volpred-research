"""
K1028: DCC-A4f Multivariate Extension for Portfolio Risk

Extends the A4f multiplicative GARCH-X framework (τ×g with τ=VIX²)
to bivariate DCC for portfolio variance forecasting.

Two-step DCC (Engle 2002):
  Step 1: Fit univariate A4f (or GJR) to each asset → standardised residuals
  Step 2: Fit scalar DCC(1,1) to the pair of standardised residuals

Evaluation:
  - Portfolio QLIKE on r² (50/50 SPY/QQQ)
  - DM test: DCC-A4f vs DCC-GJR
  - Dynamic correlation plot

References:
  - Engle, R. (2002). Dynamic Conditional Correlation. JBES 20(3).
  - Patton, A. (2011). Volatility forecast comparison using imperfect proxies. JoE 160(1).
  - A4f: multiplicative τ×g framework from Paper 9

Data: yfinance SPY, QQQ, ^VIX, 2005-2026
OOS: 2019-2026, window=2000, refit/63d
seed=42
"""

import numpy as np
import json
import time
import warnings
from datetime import datetime
from numba import njit
import math

warnings.filterwarnings("ignore")
np.random.seed(42)

# ============================================================
# 1. Data
# ============================================================
def load_data():
    import yfinance as yf
    tickers = ["SPY", "QQQ", "^VIX"]
    raw = yf.download(tickers, start="2004-01-01", end="2026-12-31",
                       auto_adjust=True, progress=False)
    close = raw["Close"][["SPY", "QQQ"]].dropna()
    vix = raw["Close"]["^VIX"].reindex(close.index).ffill().bfill()

    ret_spy = np.log(close["SPY"] / close["SPY"].shift(1))
    ret_qqq = np.log(close["QQQ"] / close["QQQ"].shift(1))
    import pandas as pd
    df = pd.DataFrame({
        "ret_spy": ret_spy,
        "ret_qqq": ret_qqq,
        "vix": vix,
        "vix2": (vix / 100.0) ** 2 / 252.0,     # annualised VIX → daily variance scale
        "r2_spy": ret_spy ** 2,
        "r2_qqq": ret_qqq ** 2,
    }).dropna()
    return df

# ============================================================
# 2. Numba kernels
# ============================================================
@njit
def gjr_recursion(omega, alpha, gamma, beta, returns):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns[:min(100, T)])
    if h[0] < 1e-16:
        h[0] = 1e-6
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0.0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h

@njit
def gjr_nll(omega, alpha, gamma, beta, returns):
    h = gjr_recursion(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll

@njit
def a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    T = len(returns)
    tau = np.empty(T)
    g = np.empty(T)
    h = np.empty(T)
    tau[0] = theta0 + theta1 * vix2[0]
    if tau[0] < 1e-16:
        tau[0] = 1e-16
    g[0] = 1.0
    h[0] = tau[0] * g[0]
    for t in range(1, T):
        tau[t] = theta0 + theta1 * vix2[t-1]     # τ uses lagged VIX²
        if tau[t] < 1e-16:
            tau[t] = 1e-16
        u_prev = returns[t-1] / np.sqrt(tau[t])
        u2 = u_prev ** 2
        ind = 1.0 if returns[t-1] < 0.0 else 0.0
        g[t] = omega + alpha * u2 + gamma * u2 * ind + beta * g[t-1]
        if g[t] < 1e-16:
            g[t] = 1e-16
        h[t] = tau[t] * g[t]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h, tau, g

@njit
def a4f_nll(theta0, theta1, omega, alpha, gamma, beta, returns, vix2):
    h, _, _ = a4f_recursion(theta0, theta1, omega, alpha, gamma, beta, returns, vix2)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll

@njit
def dcc_qbar_and_filter(eps1, eps2, a, b):
    """
    Scalar DCC(1,1) filter.
    Q_t = (1-a-b)*Qbar + a * eps_{t-1}eps_{t-1}' + b * Q_{t-1}
    rho_t = Q12_t / sqrt(Q11_t * Q22_t)
    """
    T = len(eps1)
    # Qbar = unconditional correlation matrix of standardised residuals
    mean1 = 0.0
    mean2 = 0.0
    for t in range(T):
        mean1 += eps1[t]
        mean2 += eps2[t]
    mean1 /= T
    mean2 /= T
    qbar11 = 0.0
    qbar22 = 0.0
    qbar12 = 0.0
    for t in range(T):
        e1 = eps1[t] - mean1
        e2 = eps2[t] - mean2
        qbar11 += e1 * e1
        qbar22 += e2 * e2
        qbar12 += e1 * e2
    qbar11 /= T
    qbar22 /= T
    qbar12 /= T

    q11 = np.empty(T)
    q22 = np.empty(T)
    q12 = np.empty(T)
    rho = np.empty(T)

    q11[0] = qbar11
    q22[0] = qbar22
    q12[0] = qbar12
    denom = np.sqrt(q11[0] * q22[0])
    rho[0] = q12[0] / denom if denom > 1e-20 else 0.0

    c = 1.0 - a - b
    for t in range(1, T):
        q11[t] = c * qbar11 + a * eps1[t-1] * eps1[t-1] + b * q11[t-1]
        q22[t] = c * qbar22 + a * eps2[t-1] * eps2[t-1] + b * q22[t-1]
        q12[t] = c * qbar12 + a * eps1[t-1] * eps2[t-1] + b * q12[t-1]
        denom = np.sqrt(q11[t] * q22[t])
        if denom > 1e-20:
            rho[t] = q12[t] / denom
            # clamp
            if rho[t] > 0.9999:
                rho[t] = 0.9999
            elif rho[t] < -0.9999:
                rho[t] = -0.9999
        else:
            rho[t] = 0.0
    return rho, qbar12

@njit
def dcc_loglik(eps1, eps2, a, b):
    """
    DCC log-likelihood (second stage only).
    L_DCC = -0.5 * sum[ log(1-rho²) + (eps1² + eps2² - 2*rho*eps1*eps2)/(1-rho²) - eps1² - eps2² ]
    """
    rho, _ = dcc_qbar_and_filter(eps1, eps2, a, b)
    T = len(eps1)
    ll = 0.0
    for t in range(T):
        r = rho[t]
        r2 = r * r
        if r2 > 0.9998:
            r2 = 0.9998
        det = 1.0 - r2
        e1 = eps1[t]
        e2 = eps2[t]
        # bivariate normal (conditional on marginals):
        # additional loglik = -0.5 * [log(1-rho²) + (rho²*(e1²+e2²) - 2*rho*e1*e2)/(1-rho²)]
        ll += -0.5 * (np.log(det) + (r2 * (e1*e1 + e2*e2) - 2.0*r*e1*e2) / det)
    return ll

# ============================================================
# 3. Model fitting wrappers
# ============================================================
from scipy.optimize import minimize

def fit_gjr(returns):
    bounds = [(1e-8, 0.01), (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[1] + 0.5*p[2] + p[3] >= 1.0:
            return 1e10
        try:
            v = gjr_nll(p[0], p[1], p[2], p[3], returns)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for omega_init in [1e-6, 5e-6, 1e-5]:
        for alpha_init in [0.03, 0.06]:
            x0 = [omega_init, alpha_init, 0.08, 0.88]
            try:
                res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                               options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        x0 = [5e-6, 0.04, 0.08, 0.88]
        best_res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds)
    h = gjr_recursion(*best_res.x, returns)
    return {'params': best_res.x, 'h': h, 'converged': best_res.success}

def fit_a4f(returns, vix2):
    bounds = [(-0.01, 0.01), (0.01, 5.0), (1e-6, 1.0),
              (1e-6, 0.5), (1e-6, 0.5), (0.5, 0.999)]
    def obj(p):
        if p[3] + 0.5*p[4] + p[5] >= 1.0:
            return 1e10
        try:
            v = a4f_nll(p[0], p[1], p[2], p[3], p[4], p[5], returns, vix2)
            return v if np.isfinite(v) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for theta1_init in [0.3, 0.8, 2.0]:
        for omega_init in [0.02, 0.08]:
            x0 = [1e-5, theta1_init, omega_init, 0.04, 0.06, 0.90]
            try:
                res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                               options={'maxiter': 300})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        x0 = [1e-5, 0.5, 0.05, 0.04, 0.06, 0.90]
        best_res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds)
    h, tau, g = a4f_recursion(*best_res.x, returns, vix2)
    return {'params': best_res.x, 'h': h, 'tau': tau, 'g': g,
            'converged': best_res.success}

def fit_dcc(eps1, eps2):
    """Fit scalar DCC(1,1) by maximising 2nd-stage loglik."""
    bounds = [(1e-6, 0.3), (0.5, 0.999)]
    def obj(p):
        a, b = p
        if a + b >= 0.999:
            return 1e10
        try:
            ll = dcc_loglik(eps1, eps2, a, b)
            return -ll if np.isfinite(ll) else 1e10
        except:
            return 1e10
    best_res, best_nll = None, 1e10
    for a_init in [0.01, 0.05, 0.1]:
        for b_init in [0.85, 0.92, 0.95]:
            if a_init + b_init >= 0.999:
                continue
            x0 = [a_init, b_init]
            try:
                res = minimize(obj, x0, method='L-BFGS-B', bounds=bounds,
                               options={'maxiter': 200})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_res = res
            except:
                continue
    if best_res is None:
        best_res = minimize(obj, [0.05, 0.90], method='L-BFGS-B', bounds=bounds)
    rho, qbar12 = dcc_qbar_and_filter(eps1, eps2, best_res.x[0], best_res.x[1])
    return {'a': float(best_res.x[0]), 'b': float(best_res.x[1]),
            'rho': rho, 'qbar12': float(qbar12), 'converged': best_res.success}

# ============================================================
# 4. OOS DCC Forecasting (rolling)
# ============================================================
def oos_dcc_forecast(df, model_type, oos_start_date, window=2000, refit_every=63):
    """
    OOS portfolio variance forecast using DCC.

    Steps at each refit:
      1. Fit univariate model to each asset on training window
      2. Compute standardised residuals
      3. Fit DCC on standardised residuals
    Then produce one-step-ahead h1, h2, rho → portfolio variance.

    Returns:
      portfolio_var_forecast: array of shape (T,)  [NaN before OOS]
      rho_forecast: array of shape (T,)
      h1_forecast, h2_forecast: individual variance forecasts
    """
    import pandas as pd
    oos_idx = np.where(df.index >= oos_start_date)[0][0]
    T = len(df)
    ret_spy = df['ret_spy'].values
    ret_qqq = df['ret_qqq'].values
    vix2 = df['vix2'].values

    pvar = np.full(T, np.nan)
    rho_out = np.full(T, np.nan)
    h1_out = np.full(T, np.nan)
    h2_out = np.full(T, np.nan)

    last_fit_idx = -refit_every
    # state variables for recursive forecasting between refits
    gjr1_p = gjr2_p = a4f1_p = a4f2_p = None
    dcc_a = dcc_b = 0.0
    h1_prev = h2_prev = np.nan
    g1_prev = g2_prev = np.nan
    q11_prev = q22_prev = q12_prev = 0.0
    qbar11 = qbar22 = qbar12 = 0.0
    use_a4f = (model_type == 'a4f')

    for t in range(oos_idx, T):
        if t - last_fit_idx >= refit_every or last_fit_idx < 0:
            # --- Refit ---
            s = max(0, t - window)
            tr1 = ret_spy[s:t]
            tr2 = ret_qqq[s:t]
            tv = vix2[s:t]

            if use_a4f:
                fit1 = fit_a4f(tr1, tv)
                fit2 = fit_a4f(tr2, tv)
                eps1 = tr1 / np.sqrt(fit1['h'])
                eps2 = tr2 / np.sqrt(fit2['h'])
                a4f1_p = fit1['params']
                a4f2_p = fit2['params']
                g1_prev = fit1['g'][-1]
                g2_prev = fit2['g'][-1]
            else:
                fit1 = fit_gjr(tr1)
                fit2 = fit_gjr(tr2)
                eps1 = tr1 / np.sqrt(fit1['h'])
                eps2 = tr2 / np.sqrt(fit2['h'])
                gjr1_p = fit1['params']
                gjr2_p = fit2['params']
                h1_prev = fit1['h'][-1]
                h2_prev = fit2['h'][-1]

            dcc_fit = fit_dcc(eps1, eps2)
            dcc_a = dcc_fit['a']
            dcc_b = dcc_fit['b']
            # Compute Qbar from full training sample eps
            n = len(eps1)
            m1 = np.mean(eps1)
            m2 = np.mean(eps2)
            e1c = eps1 - m1
            e2c = eps2 - m2
            qbar11 = np.mean(e1c**2)
            qbar22 = np.mean(e2c**2)
            qbar12 = np.mean(e1c * e2c)
            # Initialise Q at end of training
            q11_prev = qbar11
            q22_prev = qbar22
            q12_prev = qbar12
            # Run DCC filter over training sample to get Q_{T-1}
            c = 1.0 - dcc_a - dcc_b
            qt11, qt22, qt12 = qbar11, qbar22, qbar12
            for k in range(1, n):
                qt11 = c * qbar11 + dcc_a * eps1[k-1]**2 + dcc_b * qt11
                qt22 = c * qbar22 + dcc_a * eps2[k-1]**2 + dcc_b * qt22
                qt12 = c * qbar12 + dcc_a * eps1[k-1]*eps2[k-1] + dcc_b * qt12
            q11_prev = qt11
            q22_prev = qt22
            q12_prev = qt12

            last_fit_idx = t

        # --- One-step-ahead forecast ---
        # Univariate h_{t|t-1}
        if use_a4f:
            p1 = a4f1_p
            tau1 = max(p1[0] + p1[1] * vix2[t-1], 1e-16)
            u1_prev = ret_spy[t-1] / np.sqrt(tau1)
            ind1 = 1.0 if ret_spy[t-1] < 0 else 0.0
            g1 = p1[2] + p1[3]*u1_prev**2 + p1[4]*u1_prev**2*ind1 + p1[5]*g1_prev
            g1 = max(g1, 1e-16)
            h1 = tau1 * g1
            g1_prev = g1

            p2 = a4f2_p
            tau2 = max(p2[0] + p2[1] * vix2[t-1], 1e-16)
            u2_prev = ret_qqq[t-1] / np.sqrt(tau2)
            ind2 = 1.0 if ret_qqq[t-1] < 0 else 0.0
            g2 = p2[2] + p2[3]*u2_prev**2 + p2[4]*u2_prev**2*ind2 + p2[5]*g2_prev
            g2 = max(g2, 1e-16)
            h2 = tau2 * g2
            g2_prev = g2
        else:
            p1 = gjr1_p
            r2_1 = ret_spy[t-1]**2
            ind1 = 1.0 if ret_spy[t-1] < 0 else 0.0
            h1 = p1[0] + p1[1]*r2_1 + p1[2]*r2_1*ind1 + p1[3]*h1_prev
            h1 = max(h1, 1e-16)
            h1_prev = h1

            p2 = gjr2_p
            r2_2 = ret_qqq[t-1]**2
            ind2 = 1.0 if ret_qqq[t-1] < 0 else 0.0
            h2 = p2[0] + p2[1]*r2_2 + p2[2]*r2_2*ind2 + p2[3]*h2_prev
            h2 = max(h2, 1e-16)
            h2_prev = h2

        # Standardised residuals for DCC update
        e1 = ret_spy[t-1] / np.sqrt(max(h1_out[t-1] if t > oos_idx and np.isfinite(h1_out[t-1]) else h1, 1e-16))
        e2 = ret_qqq[t-1] / np.sqrt(max(h2_out[t-1] if t > oos_idx and np.isfinite(h2_out[t-1]) else h2, 1e-16))

        # DCC Q update
        c = 1.0 - dcc_a - dcc_b
        q11 = c * qbar11 + dcc_a * e1**2 + dcc_b * q11_prev
        q22 = c * qbar22 + dcc_a * e2**2 + dcc_b * q22_prev
        q12 = c * qbar12 + dcc_a * e1*e2 + dcc_b * q12_prev
        q11_prev = q11
        q22_prev = q22
        q12_prev = q12

        denom = np.sqrt(q11 * q22)
        rho_t = q12 / denom if denom > 1e-20 else 0.0
        rho_t = max(min(rho_t, 0.9999), -0.9999)

        # Portfolio variance: w'Hw for 50/50
        # H = [[h1, rho*sqrt(h1*h2)], [rho*sqrt(h1*h2), h2]]
        # w = [0.5, 0.5]
        # pvar = 0.25*h1 + 0.25*h2 + 0.5*rho*sqrt(h1*h2)
        cov12 = rho_t * np.sqrt(h1 * h2)
        pv = 0.25 * h1 + 0.25 * h2 + 0.5 * cov12
        pv = max(pv, 1e-16)

        pvar[t] = pv
        rho_out[t] = rho_t
        h1_out[t] = h1
        h2_out[t] = h2

    return pvar, rho_out, h1_out, h2_out

# ============================================================
# 5. Constant-correlation benchmark
# ============================================================
def oos_ccc_forecast(df, model_type, oos_start_date, window=2000, refit_every=63):
    """
    CCC (constant conditional correlation) variant:
    Same univariate models, but rho = sample correlation of standardised residuals.
    """
    oos_idx = np.where(df.index >= oos_start_date)[0][0]
    T = len(df)
    ret_spy = df['ret_spy'].values
    ret_qqq = df['ret_qqq'].values
    vix2 = df['vix2'].values

    pvar = np.full(T, np.nan)
    rho_out = np.full(T, np.nan)

    last_fit_idx = -refit_every
    gjr1_p = gjr2_p = a4f1_p = a4f2_p = None
    h1_prev = h2_prev = np.nan
    g1_prev = g2_prev = np.nan
    rho_const = 0.0
    use_a4f = (model_type == 'a4f')

    for t in range(oos_idx, T):
        if t - last_fit_idx >= refit_every or last_fit_idx < 0:
            s = max(0, t - window)
            tr1 = ret_spy[s:t]
            tr2 = ret_qqq[s:t]
            tv = vix2[s:t]

            if use_a4f:
                fit1 = fit_a4f(tr1, tv)
                fit2 = fit_a4f(tr2, tv)
                eps1 = tr1 / np.sqrt(fit1['h'])
                eps2 = tr2 / np.sqrt(fit2['h'])
                a4f1_p = fit1['params']
                a4f2_p = fit2['params']
                g1_prev = fit1['g'][-1]
                g2_prev = fit2['g'][-1]
            else:
                fit1 = fit_gjr(tr1)
                fit2 = fit_gjr(tr2)
                eps1 = tr1 / np.sqrt(fit1['h'])
                eps2 = tr2 / np.sqrt(fit2['h'])
                gjr1_p = fit1['params']
                gjr2_p = fit2['params']
                h1_prev = fit1['h'][-1]
                h2_prev = fit2['h'][-1]

            rho_const = float(np.corrcoef(eps1, eps2)[0, 1])
            last_fit_idx = t

        # Univariate forecast (same logic as DCC)
        if use_a4f:
            p1 = a4f1_p
            tau1 = max(p1[0] + p1[1]*vix2[t-1], 1e-16)
            u1_prev = ret_spy[t-1] / np.sqrt(tau1)
            ind1 = 1.0 if ret_spy[t-1] < 0 else 0.0
            g1 = p1[2] + p1[3]*u1_prev**2 + p1[4]*u1_prev**2*ind1 + p1[5]*g1_prev
            g1 = max(g1, 1e-16)
            h1 = tau1 * g1
            g1_prev = g1

            p2 = a4f2_p
            tau2 = max(p2[0] + p2[1]*vix2[t-1], 1e-16)
            u2_prev = ret_qqq[t-1] / np.sqrt(tau2)
            ind2 = 1.0 if ret_qqq[t-1] < 0 else 0.0
            g2 = p2[2] + p2[3]*u2_prev**2 + p2[4]*u2_prev**2*ind2 + p2[5]*g2_prev
            g2 = max(g2, 1e-16)
            h2 = tau2 * g2
            g2_prev = g2
        else:
            p1 = gjr1_p
            r2_1 = ret_spy[t-1]**2
            ind1 = 1.0 if ret_spy[t-1] < 0 else 0.0
            h1 = p1[0] + p1[1]*r2_1 + p1[2]*r2_1*ind1 + p1[3]*h1_prev
            h1 = max(h1, 1e-16)
            h1_prev = h1

            p2 = gjr2_p
            r2_2 = ret_qqq[t-1]**2
            ind2 = 1.0 if ret_qqq[t-1] < 0 else 0.0
            h2 = p2[0] + p2[1]*r2_2 + p2[2]*r2_2*ind2 + p2[3]*h2_prev
            h2 = max(h2, 1e-16)
            h2_prev = h2

        cov12 = rho_const * np.sqrt(h1 * h2)
        pv = 0.25*h1 + 0.25*h2 + 0.5*cov12
        pv = max(pv, 1e-16)
        pvar[t] = pv
        rho_out[t] = rho_const

    return pvar, rho_out

# ============================================================
# 6. Evaluation
# ============================================================
def qlike(actual, forecast):
    """QLIKE loss: mean(actual/forecast + log(forecast))."""
    mask = np.isfinite(actual) & np.isfinite(forecast) & (forecast > 0) & (actual >= 0)
    a = actual[mask]
    f = forecast[mask]
    return float(np.mean(a / f + np.log(f)))

def dm_test(loss1, loss2):
    """Diebold-Mariano test: is loss1 significantly different from loss2?"""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {'t_stat': 0.0, 'p_value': 1.0, 'n': n}
    d_bar = np.mean(d)
    # HAC variance (Newey-West with ~n^(1/3) lags)
    max_lag = max(1, int(n ** (1.0/3.0)))
    gamma0 = np.mean((d - d_bar)**2)
    gamma_sum = 0.0
    for k in range(1, max_lag+1):
        w = 1.0 - k / (max_lag + 1.0)
        gk = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2.0 * w * gk
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return {'t_stat': 0.0, 'p_value': 1.0, 'n': n}
    t_stat = d_bar / np.sqrt(var_d)
    from scipy import stats
    p_value = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n-1))
    return {'t_stat': float(t_stat), 'p_value': float(p_value), 'n': int(n)}

def qlike_losses(actual, forecast):
    """Element-wise QLIKE losses."""
    mask = np.isfinite(actual) & np.isfinite(forecast) & (forecast > 0) & (actual >= 0)
    out = np.full(len(actual), np.nan)
    a = actual[mask]
    f = forecast[mask]
    out[mask] = a / f + np.log(f)
    return out

# ============================================================
# 7. Main
# ============================================================
def main():
    t0 = time.time()
    print("K1028: DCC-A4f Multivariate Extension")
    print("=" * 60)

    # --- Load data ---
    print("Loading data...")
    df = load_data()
    print(f"  Samples: {len(df)}, from {df.index[0].date()} to {df.index[-1].date()}")

    oos_start = "2019-01-02"
    oos_idx = np.where(df.index >= oos_start)[0][0]
    print(f"  OOS start: {oos_start} (index {oos_idx}), OOS days: {len(df) - oos_idx}")

    # Portfolio actual r²
    port_ret = 0.5 * df['ret_spy'].values + 0.5 * df['ret_qqq'].values
    port_r2 = port_ret ** 2

    # Descriptive stats
    print(f"\n  SPY: mean={df['ret_spy'].mean()*252:.4f}, std={df['ret_spy'].std()*np.sqrt(252):.4f}")
    print(f"  QQQ: mean={df['ret_qqq'].mean()*252:.4f}, std={df['ret_qqq'].std()*np.sqrt(252):.4f}")
    print(f"  Correlation: {df['ret_spy'].corr(df['ret_qqq']):.4f}")

    # --- Run OOS forecasts ---
    print("\n--- DCC-GJR ---")
    pvar_dcc_gjr, rho_dcc_gjr, _, _ = oos_dcc_forecast(df, 'gjr', oos_start, window=2000, refit_every=63)
    print(f"  Done. OOS forecasts: {np.sum(np.isfinite(pvar_dcc_gjr[oos_idx:]))}")

    print("--- DCC-A4f ---")
    pvar_dcc_a4f, rho_dcc_a4f, _, _ = oos_dcc_forecast(df, 'a4f', oos_start, window=2000, refit_every=63)
    print(f"  Done. OOS forecasts: {np.sum(np.isfinite(pvar_dcc_a4f[oos_idx:]))}")

    print("--- CCC-GJR ---")
    pvar_ccc_gjr, rho_ccc_gjr = oos_ccc_forecast(df, 'gjr', oos_start, window=2000, refit_every=63)
    print(f"  Done. OOS forecasts: {np.sum(np.isfinite(pvar_ccc_gjr[oos_idx:]))}")

    print("--- CCC-A4f ---")
    pvar_ccc_a4f, rho_ccc_a4f = oos_ccc_forecast(df, 'a4f', oos_start, window=2000, refit_every=63)
    print(f"  Done. OOS forecasts: {np.sum(np.isfinite(pvar_ccc_a4f[oos_idx:]))}")

    # --- QLIKE ---
    print("\n=== Portfolio QLIKE (lower is better) ===")
    oos_r2 = port_r2[oos_idx:]
    ql_dcc_gjr = qlike(oos_r2, pvar_dcc_gjr[oos_idx:])
    ql_dcc_a4f = qlike(oos_r2, pvar_dcc_a4f[oos_idx:])
    ql_ccc_gjr = qlike(oos_r2, pvar_ccc_gjr[oos_idx:])
    ql_ccc_a4f = qlike(oos_r2, pvar_ccc_a4f[oos_idx:])
    print(f"  DCC-GJR:  {ql_dcc_gjr:.6f}")
    print(f"  DCC-A4f:  {ql_dcc_a4f:.6f}")
    print(f"  CCC-GJR:  {ql_ccc_gjr:.6f}")
    print(f"  CCC-A4f:  {ql_ccc_a4f:.6f}")

    # --- DM tests ---
    print("\n=== Diebold-Mariano Tests ===")
    loss_dcc_gjr = qlike_losses(port_r2, pvar_dcc_gjr)
    loss_dcc_a4f = qlike_losses(port_r2, pvar_dcc_a4f)
    loss_ccc_gjr = qlike_losses(port_r2, pvar_ccc_gjr)
    loss_ccc_a4f = qlike_losses(port_r2, pvar_ccc_a4f)

    # Use only OOS
    lo_dcc_gjr = loss_dcc_gjr[oos_idx:]
    lo_dcc_a4f = loss_dcc_a4f[oos_idx:]
    lo_ccc_gjr = loss_ccc_gjr[oos_idx:]
    lo_ccc_a4f = loss_ccc_a4f[oos_idx:]

    dm1 = dm_test(lo_dcc_gjr, lo_dcc_a4f)
    print(f"  DCC-GJR vs DCC-A4f: t={dm1['t_stat']:.4f}, p={dm1['p_value']:.4f}")
    print(f"    → {'A4f better' if dm1['t_stat'] > 0 else 'GJR better'}")

    dm2 = dm_test(lo_ccc_gjr, lo_ccc_a4f)
    print(f"  CCC-GJR vs CCC-A4f: t={dm2['t_stat']:.4f}, p={dm2['p_value']:.4f}")

    dm3 = dm_test(lo_dcc_a4f, lo_ccc_a4f)
    print(f"  DCC-A4f vs CCC-A4f: t={dm3['t_stat']:.4f}, p={dm3['p_value']:.4f}")
    print(f"    → {'CCC better (DCC unnecessary)' if dm3['t_stat'] > 0 else 'DCC adds value'}")

    dm4 = dm_test(lo_dcc_gjr, lo_ccc_gjr)
    print(f"  DCC-GJR vs CCC-GJR: t={dm4['t_stat']:.4f}, p={dm4['p_value']:.4f}")

    # --- Correlation stats ---
    rho_dcc_a4f_oos = rho_dcc_a4f[oos_idx:]
    rho_dcc_gjr_oos = rho_dcc_gjr[oos_idx:]
    mask_a = np.isfinite(rho_dcc_a4f_oos)
    mask_g = np.isfinite(rho_dcc_gjr_oos)
    print(f"\n=== Dynamic Correlation Stats (OOS) ===")
    print(f"  DCC-A4f rho: mean={np.mean(rho_dcc_a4f_oos[mask_a]):.4f}, "
          f"std={np.std(rho_dcc_a4f_oos[mask_a]):.4f}, "
          f"min={np.min(rho_dcc_a4f_oos[mask_a]):.4f}, "
          f"max={np.max(rho_dcc_a4f_oos[mask_a]):.4f}")
    print(f"  DCC-GJR rho: mean={np.mean(rho_dcc_gjr_oos[mask_g]):.4f}, "
          f"std={np.std(rho_dcc_gjr_oos[mask_g]):.4f}, "
          f"min={np.min(rho_dcc_gjr_oos[mask_g]):.4f}, "
          f"max={np.max(rho_dcc_gjr_oos[mask_g]):.4f}")

    # --- VaR evaluation (portfolio, 5% level) ---
    print("\n=== Portfolio VaR Backtest (5%) ===")
    from scipy import stats
    z_05 = stats.norm.ppf(0.05)
    port_ret_oos = port_ret[oos_idx:]
    n_oos = len(port_ret_oos)

    for name, pv in [("DCC-GJR", pvar_dcc_gjr), ("DCC-A4f", pvar_dcc_a4f),
                      ("CCC-GJR", pvar_ccc_gjr), ("CCC-A4f", pvar_ccc_a4f)]:
        sigma_oos = np.sqrt(pv[oos_idx:])
        var5 = z_05 * sigma_oos   # negative
        violations = np.sum(port_ret_oos < var5)
        vrate = violations / n_oos
        # Kupiec LR
        p0 = 0.05
        if 0 < violations < n_oos:
            lr = 2.0 * (violations * np.log(vrate/p0) + (n_oos-violations)*np.log((1-vrate)/(1-p0)))
            pval = 1.0 - stats.chi2.cdf(lr, 1)
        else:
            lr = np.nan
            pval = np.nan
        print(f"  {name}: violations={violations}/{n_oos} ({vrate:.4f}), "
              f"Kupiec LR={lr:.2f}, p={pval:.4f}")

    # --- Plot ---
    print("\nGenerating correlation plot...")
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    dates = df.index[oos_idx:]
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True)

    # Panel 1: Dynamic correlation
    ax1 = axes[0]
    ax1.plot(dates, rho_dcc_a4f[oos_idx:], label='DCC-A4f', color='#2196F3', alpha=0.8, linewidth=0.8)
    ax1.plot(dates, rho_dcc_gjr[oos_idx:], label='DCC-GJR', color='#FF5722', alpha=0.7, linewidth=0.8)
    ax1.axhline(y=np.mean(rho_dcc_a4f_oos[mask_a]), color='#2196F3', linestyle='--', alpha=0.4, linewidth=0.6)
    ax1.axhline(y=np.mean(rho_dcc_gjr_oos[mask_g]), color='#FF5722', linestyle='--', alpha=0.4, linewidth=0.6)
    ax1.set_ylabel('Dynamic Correlation (ρ)')
    ax1.set_title('K1028: DCC-A4f vs DCC-GJR — SPY/QQQ Dynamic Correlation (OOS 2019-2026)')
    ax1.legend(loc='lower right')
    ax1.grid(True, alpha=0.3)

    # Panel 2: Portfolio variance forecast vs actual
    ax2 = axes[1]
    ax2.plot(dates, port_r2[oos_idx:], label='Actual r²', color='gray', alpha=0.3, linewidth=0.5)
    ax2.plot(dates, pvar_dcc_a4f[oos_idx:], label='DCC-A4f forecast', color='#2196F3', alpha=0.8, linewidth=0.8)
    ax2.plot(dates, pvar_dcc_gjr[oos_idx:], label='DCC-GJR forecast', color='#FF5722', alpha=0.7, linewidth=0.8)
    ax2.set_ylabel('Portfolio Variance')
    ax2.set_xlabel('Date')
    ax2.set_title('Portfolio Variance Forecast (50/50 SPY/QQQ)')
    ax2.legend(loc='upper right')
    ax2.grid(True, alpha=0.3)
    ax2.set_yscale('log')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax2.xaxis.set_major_locator(mdates.YearLocator())

    plt.tight_layout()
    plt.savefig('experiments/k1028/k1028_dcc_correlation.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved: k1028_dcc_correlation.png")

    # --- Fit one full-sample DCC to report parameters ---
    print("\n--- Full-sample DCC parameter estimates ---")
    full_ret1 = df['ret_spy'].values
    full_ret2 = df['ret_qqq'].values
    full_vix2 = df['vix2'].values
    fit1_full = fit_a4f(full_ret1, full_vix2)
    fit2_full = fit_a4f(full_ret2, full_vix2)
    eps1_full = full_ret1 / np.sqrt(fit1_full['h'])
    eps2_full = full_ret2 / np.sqrt(fit2_full['h'])
    dcc_full = fit_dcc(eps1_full, eps2_full)
    print(f"  A4f-SPY params: theta0={fit1_full['params'][0]:.6f}, theta1={fit1_full['params'][1]:.4f}, "
          f"omega={fit1_full['params'][2]:.4f}, alpha={fit1_full['params'][3]:.4f}, "
          f"gamma={fit1_full['params'][4]:.4f}, beta={fit1_full['params'][5]:.4f}")
    print(f"  A4f-QQQ params: theta0={fit2_full['params'][0]:.6f}, theta1={fit2_full['params'][1]:.4f}, "
          f"omega={fit2_full['params'][2]:.4f}, alpha={fit2_full['params'][3]:.4f}, "
          f"gamma={fit2_full['params'][4]:.4f}, beta={fit2_full['params'][5]:.4f}")
    print(f"  DCC: a={dcc_full['a']:.6f}, b={dcc_full['b']:.6f}, "
          f"persistence={dcc_full['a']+dcc_full['b']:.6f}")

    fit1g_full = fit_gjr(full_ret1)
    fit2g_full = fit_gjr(full_ret2)
    eps1g_full = full_ret1 / np.sqrt(fit1g_full['h'])
    eps2g_full = full_ret2 / np.sqrt(fit2g_full['h'])
    dcc_gjr_full = fit_dcc(eps1g_full, eps2g_full)
    print(f"  GJR-SPY params: omega={fit1g_full['params'][0]:.6f}, alpha={fit1g_full['params'][1]:.4f}, "
          f"gamma={fit1g_full['params'][2]:.4f}, beta={fit1g_full['params'][3]:.4f}")
    print(f"  GJR-QQQ params: omega={fit2g_full['params'][0]:.6f}, alpha={fit2g_full['params'][1]:.4f}, "
          f"gamma={fit2g_full['params'][2]:.4f}, beta={fit2g_full['params'][3]:.4f}")
    print(f"  DCC(GJR): a={dcc_gjr_full['a']:.6f}, b={dcc_gjr_full['b']:.6f}, "
          f"persistence={dcc_gjr_full['a']+dcc_gjr_full['b']:.6f}")

    elapsed = time.time() - t0

    # --- Results JSON ---
    results = {
        "experiment_id": "K1028",
        "title": "DCC-A4f Multivariate Extension for Portfolio Risk",
        "data_source": "yfinance",
        "assets": ["SPY", "QQQ"],
        "exogenous": "^VIX",
        "portfolio": "50/50 SPY/QQQ",
        "oos_start": oos_start,
        "oos_days": int(len(df) - oos_idx),
        "window": 2000,
        "refit_every": 63,
        "seed": 42,
        "descriptive_stats": {
            "spy_annual_mean": float(df['ret_spy'].mean() * 252),
            "spy_annual_std": float(df['ret_spy'].std() * np.sqrt(252)),
            "qqq_annual_mean": float(df['ret_qqq'].mean() * 252),
            "qqq_annual_std": float(df['ret_qqq'].std() * np.sqrt(252)),
            "unconditional_corr": float(df['ret_spy'].corr(df['ret_qqq'])),
            "n_obs": len(df),
            "date_range": f"{df.index[0].date()} to {df.index[-1].date()}"
        },
        "portfolio_qlike": {
            "DCC_GJR": ql_dcc_gjr,
            "DCC_A4f": ql_dcc_a4f,
            "CCC_GJR": ql_ccc_gjr,
            "CCC_A4f": ql_ccc_a4f,
            "best": min([(ql_dcc_gjr, "DCC-GJR"), (ql_dcc_a4f, "DCC-A4f"),
                         (ql_ccc_gjr, "CCC-GJR"), (ql_ccc_a4f, "CCC-A4f")],
                        key=lambda x: x[0])[1]
        },
        "dm_tests": {
            "DCC_GJR_vs_DCC_A4f": {
                "t_stat": dm1['t_stat'], "p_value": dm1['p_value'],
                "interpretation": "positive t → A4f better" if dm1['t_stat'] > 0 else "negative t → GJR better"
            },
            "CCC_GJR_vs_CCC_A4f": {
                "t_stat": dm2['t_stat'], "p_value": dm2['p_value']
            },
            "DCC_A4f_vs_CCC_A4f": {
                "t_stat": dm3['t_stat'], "p_value": dm3['p_value'],
                "interpretation": "positive t → CCC better (DCC unnecessary)" if dm3['t_stat'] > 0 else "negative t → DCC adds value"
            },
            "DCC_GJR_vs_CCC_GJR": {
                "t_stat": dm4['t_stat'], "p_value": dm4['p_value']
            }
        },
        "dcc_params_full_sample": {
            "A4f": {
                "a": dcc_full['a'], "b": dcc_full['b'],
                "persistence": dcc_full['a'] + dcc_full['b'],
                "converged": dcc_full['converged'],
                "qbar12": dcc_full['qbar12']
            },
            "GJR": {
                "a": dcc_gjr_full['a'], "b": dcc_gjr_full['b'],
                "persistence": dcc_gjr_full['a'] + dcc_gjr_full['b'],
                "converged": dcc_gjr_full['converged'],
                "qbar12": dcc_gjr_full['qbar12']
            }
        },
        "univariate_params_full_sample": {
            "A4f_SPY": {f"p{i}": float(v) for i, v in enumerate(fit1_full['params'])},
            "A4f_QQQ": {f"p{i}": float(v) for i, v in enumerate(fit2_full['params'])},
            "GJR_SPY": {f"p{i}": float(v) for i, v in enumerate(fit1g_full['params'])},
            "GJR_QQQ": {f"p{i}": float(v) for i, v in enumerate(fit2g_full['params'])}
        },
        "correlation_stats_oos": {
            "DCC_A4f": {
                "mean": float(np.mean(rho_dcc_a4f_oos[mask_a])),
                "std": float(np.std(rho_dcc_a4f_oos[mask_a])),
                "min": float(np.min(rho_dcc_a4f_oos[mask_a])),
                "max": float(np.max(rho_dcc_a4f_oos[mask_a]))
            },
            "DCC_GJR": {
                "mean": float(np.mean(rho_dcc_gjr_oos[mask_g])),
                "std": float(np.std(rho_dcc_gjr_oos[mask_g])),
                "min": float(np.min(rho_dcc_gjr_oos[mask_g])),
                "max": float(np.max(rho_dcc_gjr_oos[mask_g]))
            }
        },
        "var_backtest_5pct": {},
        "references": [
            "Engle, R. (2002). Dynamic Conditional Correlation. JBES 20(3), 339-350.",
            "Patton, A. (2011). Volatility forecast comparison using imperfect proxies. JoE 160(1), 246-256.",
            "A4f multiplicative framework from Paper 9 (Lai, 2026)"
        ],
        "elapsed_seconds": round(elapsed, 1),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

    # VaR results
    for name, pv in [("DCC_GJR", pvar_dcc_gjr), ("DCC_A4f", pvar_dcc_a4f),
                      ("CCC_GJR", pvar_ccc_gjr), ("CCC_A4f", pvar_ccc_a4f)]:
        sigma_oos = np.sqrt(pv[oos_idx:])
        var5 = z_05 * sigma_oos
        violations = int(np.sum(port_ret_oos < var5))
        vrate = violations / n_oos
        if 0 < violations < n_oos:
            lr = 2.0 * (violations * np.log(vrate/0.05) + (n_oos-violations)*np.log((1-vrate)/(1-0.05)))
            pval = float(1.0 - stats.chi2.cdf(lr, 1))
        else:
            lr = float('nan')
            pval = float('nan')
        results["var_backtest_5pct"][name] = {
            "violations": violations,
            "total": n_oos,
            "violation_rate": round(vrate, 4),
            "kupiec_lr": round(lr, 4) if np.isfinite(lr) else None,
            "kupiec_p": round(pval, 4) if np.isfinite(pval) else None,
            "pass": pval > 0.05 if np.isfinite(pval) else False
        }

    # Summary
    best_model = results["portfolio_qlike"]["best"]
    a4f_improves = ql_dcc_a4f < ql_dcc_gjr
    dcc_needed = dm3['t_stat'] < 0  # negative means DCC better than CCC
    results["summary"] = {
        "a4f_improves_over_gjr_in_dcc": a4f_improves,
        "qlike_improvement_pct": round((ql_dcc_gjr - ql_dcc_a4f) / abs(ql_dcc_gjr) * 100, 2) if ql_dcc_gjr != 0 else 0,
        "dm_t_a4f_vs_gjr": dm1['t_stat'],
        "dm_p_a4f_vs_gjr": dm1['p_value'],
        "dcc_adds_value_over_ccc": dcc_needed,
        "dm_t_dcc_vs_ccc_a4f": dm3['t_stat'],
        "best_model": best_model,
        "conclusion": (
            f"DCC-A4f {'improves' if a4f_improves else 'does not improve'} over DCC-GJR "
            f"(QLIKE: {ql_dcc_a4f:.6f} vs {ql_dcc_gjr:.6f}, "
            f"DM t={dm1['t_stat']:.3f}, p={dm1['p_value']:.3f}). "
            f"DCC {'adds value' if dcc_needed else 'does NOT add value'} over CCC "
            f"for A4f marginals (DM t={dm3['t_stat']:.3f}, p={dm3['p_value']:.3f})."
        )
    }

    with open('experiments/k1028/k1028_results.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to experiments/k1028/k1028_results.json")
    print(f"Elapsed: {elapsed:.1f}s")
    print(f"\n{'='*60}")
    print(f"CONCLUSION: {results['summary']['conclusion']}")

if __name__ == "__main__":
    main()
