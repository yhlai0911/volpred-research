"""
K1019: Markov-Switching GJR-GARCH (MS-GJR) Volatility Forecasting
===================================================================
Data: SPY 2005-2026 (yfinance), VIX (^VIX), VIX9D (^VIX9D)
OOS: 2013-2026 (VIX9D available from ~2011), window=2000, refit every 63 days
Models:
  M1: GJR-t (baseline)
  M2: MS(2)-GJR-N (2-regime Markov-Switching GJR, Hamilton filter)
  M3: MS(2)-GJR + VIX indicator (VIX percentile assists regime identification)
  M4: A4f-VIX9D-t (comparison, K1004 best model)

Evaluation: QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0),
            VaR 2.5%: regime-weighted VaR
Charts: (1) QLIKE bar chart (2) Regime probability timeline vs VIX
        (3) Two-regime parameter comparison

References:
- Hamilton (1989): Econometrica, 57(2), 357-384. Markov-Switching.
- Gray (1996): JFE, 42(1), 27-62. Regime-Switching GARCH.
- Klaassen (2002): Empirical Economics, 27(2), 363-394. Improving GARCH with RS.
- Haas, Mittnik & Paolella (2004): JFEC, 2(4), 493-530. MS-GARCH.
- Patton (2011): JoE, 160(1), 246-256. QLIKE loss.
- Harvey (2016): t>3.0 threshold.
- Engle & Rangel (2008): Spline-GARCH.

seed = 42
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
from datetime import datetime
from scipy.optimize import minimize
from scipy.stats import norm, chi2
from numba import njit
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data Loading
# ============================================================
def load_data():
    """Load SPY + VIX + VIX9D data from 2004."""
    print("\n=== K1019: Markov-Switching GJR-GARCH ===")
    print("Loading SPY + VIX + VIX9D...")

    spy = yf.download('SPY', start='2003-01-01', end='2026-12-31', progress=False)
    vix = yf.download('^VIX', start='2003-01-01', end='2026-12-31', progress=False)
    vix9d = yf.download('^VIX9D', start='2003-01-01', end='2026-12-31', progress=False)

    for d in [spy, vix, vix9d]:
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['close'] = spy['Close']
    df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
    df['vix9d'] = vix9d['Close'].reindex(spy.index, method='ffill')
    df['ret'] = np.log(df['close'] / df['close'].shift(1))
    df = df.dropna(subset=['ret', 'close', 'vix'])
    df['ret'] = df['ret'].clip(-0.20, 0.20)
    df['r2'] = df['ret'] ** 2

    # VIX percentile (rolling 252-day)
    df['vix_pct'] = df['vix'].rolling(252, min_periods=126).apply(
        lambda x: (x.values[-1] - x.min()) / (x.max() - x.min() + 1e-10), raw=False
    )
    # Forward fill vix_pct for the initial period
    df['vix_pct'] = df['vix_pct'].fillna(0.5)

    print(f"  SPY data: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")
    vix9d_valid = df['vix9d'].notna().sum()
    print(f"  VIX9D valid obs: {vix9d_valid}")

    return df


# ============================================================
# 2. Numba-accelerated GARCH core
# ============================================================
@njit
def gjr_h(omega, alpha, gamma, beta, returns):
    """GJR-GARCH variance recursion."""
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


@njit
def t_logpdf_sum(returns, h, df):
    """Sum of Student-t log-pdf with correct scale factor sqrt((df-2)/df)."""
    T = len(returns)
    scale_factor = (df - 2.0) / df
    ll = 0.0
    for t in range(T):
        sigma2 = h[t] * scale_factor
        if sigma2 < 1e-16:
            sigma2 = 1e-16
        z2 = returns[t] ** 2 / sigma2
        # Log-pdf (up to constant that depends only on df, cancels in optimization)
        ll += 0.5 * np.log(sigma2) + ((df + 1.0) / 2.0) * np.log(1.0 + z2 / (df - 2.0))
    return ll


@njit
def gjr_nll_normal(omega, alpha, gamma, beta, returns):
    """GJR-GARCH Normal NLL."""
    h = gjr_h(omega, alpha, gamma, beta, returns)
    T = len(returns)
    ll = 0.0
    for t in range(T):
        ll += np.log(h[t]) + returns[t]**2 / h[t]
    return 0.5 * ll


@njit
def gjr_nll_t(omega, alpha, gamma, beta, df, returns):
    """GJR-GARCH Student-t NLL."""
    h = gjr_h(omega, alpha, gamma, beta, returns)
    return t_logpdf_sum(returns, h, df)


# ============================================================
# 3. Model M1: GJR-t (baseline)
# ============================================================
def fit_gjr_t(returns):
    """Fit GJR-GARCH(1,1) with Student-t innovations."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    var0 = np.var(ret)

    def neg_ll(params):
        omega, alpha, gamma, beta, df = params
        if omega < 1e-10 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if alpha + 0.5 * gamma + beta >= 1.0:
            return 1e10
        if df <= 2.01 or df > 100:
            return 1e10
        return gjr_nll_t(omega, alpha, gamma, beta, df, ret)

    best_res = None
    best_val = 1e20
    starts = [
        [var0 * 0.05, 0.05, 0.10, 0.85, 8.0],
        [var0 * 0.02, 0.03, 0.08, 0.88, 6.0],
        [var0 * 0.10, 0.08, 0.15, 0.75, 10.0],
        [var0 * 0.01, 0.02, 0.05, 0.92, 5.0],
    ]
    bounds = [(1e-10, 0.01), (1e-6, 0.5), (1e-6, 0.5), (0.3, 0.999), (2.1, 100)]

    for x0 in starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 500, 'ftol': 1e-12})
            if res.fun < best_val:
                best_val = res.fun
                best_res = res
        except:
            pass

    if best_res is None or best_val > 1e9:
        return None

    p = best_res.x
    h = gjr_h(p[0], p[1], p[2], p[3], ret)
    persistence = p[1] + 0.5 * p[2] + p[3]

    return {
        'omega': p[0], 'alpha': p[1], 'gamma': p[2], 'beta': p[3], 'df': p[4],
        'h': h, 'persistence': persistence, 'converged': best_res.success,
        'nll': best_val
    }


# ============================================================
# 4. Model M4: A4f-VIX9D-t (Augmented GJR with VIX9D)
# ============================================================
@njit
def a4f_h(omega, alpha, gamma, beta, delta, returns, exog):
    """A4f GARCH: h_t = omega + alpha*r2 + gamma*r2*I + beta*h_{t-1} + delta*exog_{t-1}."""
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * r2 + gamma * r2 * ind + beta * h[t-1] + delta * exog[t-1]
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


def fit_a4f_vix9d_t(returns, vix9d_scaled):
    """Fit A4f-VIX9D-t model."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    exog = np.ascontiguousarray(vix9d_scaled, dtype=np.float64)
    var0 = np.var(ret)

    def neg_ll(params):
        omega, alpha, gamma, beta, delta, df = params
        if omega < 1e-10 or alpha < 0 or gamma < 0 or beta < 0 or delta < 0:
            return 1e10
        if alpha + 0.5 * gamma + beta >= 0.999:
            return 1e10
        if df <= 2.01 or df > 100:
            return 1e10
        h = a4f_h(omega, alpha, gamma, beta, delta, ret, exog)
        return t_logpdf_sum(ret, h, df)

    best_res = None
    best_val = 1e20
    starts = [
        [var0*0.01, 0.02, 0.05, 0.80, 0.01, 8.0],
        [var0*0.005, 0.01, 0.03, 0.85, 0.02, 6.0],
        [var0*0.02, 0.03, 0.08, 0.75, 0.005, 10.0],
    ]
    bounds = [(1e-10, 0.01), (1e-6, 0.3), (1e-6, 0.3), (0.3, 0.998),
              (1e-8, 0.1), (2.1, 100)]

    for x0 in starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B', bounds=bounds,
                          options={'maxiter': 500, 'ftol': 1e-12})
            if res.fun < best_val:
                best_val = res.fun
                best_res = res
        except:
            pass

    if best_res is None or best_val > 1e9:
        return None

    p = best_res.x
    h = a4f_h(p[0], p[1], p[2], p[3], p[4], ret, exog)

    return {
        'omega': p[0], 'alpha': p[1], 'gamma': p[2], 'beta': p[3],
        'delta': p[4], 'df': p[5], 'h': h,
        'persistence': p[1] + 0.5 * p[2] + p[3],
        'converged': best_res.success, 'nll': best_val
    }


# ============================================================
# 5. Model M2: MS(2)-GJR-N (Markov-Switching GJR, Normal)
# ============================================================
# Gray (1996) / Klaassen (2002) approach:
# Collapse conditional variance at each step to avoid path dependence.
# Parameters: [omega0,alpha0,gamma0,beta0, omega1,alpha1,gamma1,beta1, p00,p11]

@njit
def ms_gjr_filter(omega0, alpha0, gamma0, beta0,
                  omega1, alpha1, gamma1, beta1,
                  p00, p11, returns):
    """
    Hamilton filter for 2-regime GJR-GARCH(1,1) with Normal innovations.
    Gray (1996) variance collapse.

    Returns: (log_likelihood, filtered_probs_regime0, h0, h1, h_combined)
    """
    T = len(returns)

    xi_filtered = np.empty(T)  # P(s_t = 0 | info_t)
    h0 = np.empty(T)
    h1 = np.empty(T)
    h_combined = np.empty(T)

    # Ergodic probabilities for initialization
    denom = (2.0 - p00 - p11)
    if abs(denom) < 1e-10:
        pi0 = 0.5
    else:
        pi0 = (1.0 - p11) / denom
    pi0 = max(min(pi0, 0.99), 0.01)

    var_all = np.var(returns)
    h0[0] = var_all * 0.5   # Calm
    h1[0] = var_all * 2.0   # Crisis

    xi_filtered[0] = pi0
    h_combined[0] = pi0 * h0[0] + (1.0 - pi0) * h1[0]

    log_lik = 0.0

    for t in range(1, T):
        # Prediction: P(s_t | info_{t-1})
        xi_pred_0 = p00 * xi_filtered[t-1] + (1.0 - p11) * (1.0 - xi_filtered[t-1])
        xi_pred_1 = 1.0 - xi_pred_0

        # Clamp
        xi_pred_0 = max(min(xi_pred_0, 1.0 - 1e-8), 1e-8)
        xi_pred_1 = 1.0 - xi_pred_0

        # Variance recursion (Gray collapse: each regime uses h_combined from t-1)
        r2_prev = returns[t-1] ** 2
        ind_prev = 1.0 if returns[t-1] < 0 else 0.0
        h_prev = h_combined[t-1]

        h0[t] = omega0 + alpha0 * r2_prev + gamma0 * r2_prev * ind_prev + beta0 * h_prev
        h1[t] = omega1 + alpha1 * r2_prev + gamma1 * r2_prev * ind_prev + beta1 * h_prev

        if h0[t] < 1e-16:
            h0[t] = 1e-16
        if h1[t] < 1e-16:
            h1[t] = 1e-16

        # Normal density in each regime
        r_t = returns[t]
        f0 = (1.0 / np.sqrt(2.0 * np.pi * h0[t])) * np.exp(-0.5 * r_t**2 / h0[t])
        f1 = (1.0 / np.sqrt(2.0 * np.pi * h1[t])) * np.exp(-0.5 * r_t**2 / h1[t])

        f_total = xi_pred_0 * f0 + xi_pred_1 * f1

        if f_total < 1e-300:
            f_total = 1e-300

        log_lik += np.log(f_total)

        # Update: P(s_t = 0 | info_t)
        xi_filtered[t] = xi_pred_0 * f0 / f_total
        xi_filtered[t] = max(min(xi_filtered[t], 1.0 - 1e-8), 1e-8)

        # Gray collapse
        h_combined[t] = xi_filtered[t] * h0[t] + (1.0 - xi_filtered[t]) * h1[t]

    return log_lik, xi_filtered, h0, h1, h_combined


def fit_ms_gjr(returns, n_starts=10):
    """Fit MS(2)-GJR-GARCH(1,1) with Normal innovations.

    Uses unconstrained parameterization:
    - omega: exp(x) > 0
    - alpha, gamma: sigmoid(x) * upper_bound
    - beta: sigmoid(x) * upper_bound
    - p00, p11: sigmoid(x) in (0,1)
    """
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    var0 = np.var(ret)

    def neg_ll(x):
        # Regime 0 (calm)
        omega0 = np.exp(x[0])
        alpha0 = 0.4 / (1.0 + np.exp(-x[1]))     # (0, 0.4)
        gamma0 = 0.6 / (1.0 + np.exp(-x[2]))     # (0, 0.6)
        beta0  = 0.999 / (1.0 + np.exp(-x[3]))   # (0, 0.999)

        # Regime 1 (crisis)
        omega1 = np.exp(x[4])
        alpha1 = 0.4 / (1.0 + np.exp(-x[5]))
        gamma1 = 0.6 / (1.0 + np.exp(-x[6]))
        beta1  = 0.999 / (1.0 + np.exp(-x[7]))

        # Transition probabilities
        p00 = 0.98 / (1.0 + np.exp(-x[8])) + 0.01  # (0.01, 0.99)
        p11 = 0.98 / (1.0 + np.exp(-x[9])) + 0.01

        # Stationarity check
        pers0 = alpha0 + 0.5 * gamma0 + beta0
        pers1 = alpha1 + 0.5 * gamma1 + beta1
        if pers0 >= 0.999 or pers1 >= 0.999:
            return 1e10

        ll, _, _, _, _ = ms_gjr_filter(
            omega0, alpha0, gamma0, beta0,
            omega1, alpha1, gamma1, beta1,
            p00, p11, ret
        )

        if np.isnan(ll) or np.isinf(ll):
            return 1e10
        return -ll

    rng = np.random.RandomState(42)
    best_val = 1e20
    best_x = None

    # Initial values in the unconstrained space
    # inv_sigmoid(y/upper) = log(y/(upper-y))
    def inv_sig(y, upper=1.0):
        y_clipped = max(min(y, upper*0.999), upper*0.001)
        return np.log(y_clipped / (upper - y_clipped))

    base_starts = [
        # Calm regime: low omega, low alpha+gamma, high beta
        # Crisis regime: high omega, high alpha+gamma, lower beta
        [np.log(var0*0.01), inv_sig(0.02, 0.4), inv_sig(0.05, 0.6), inv_sig(0.90, 0.999),
         np.log(var0*0.10), inv_sig(0.10, 0.4), inv_sig(0.20, 0.6), inv_sig(0.70, 0.999),
         inv_sig(0.96, 0.98), inv_sig(0.90, 0.98)],
        [np.log(var0*0.005), inv_sig(0.01, 0.4), inv_sig(0.03, 0.6), inv_sig(0.93, 0.999),
         np.log(var0*0.05), inv_sig(0.05, 0.4), inv_sig(0.15, 0.6), inv_sig(0.75, 0.999),
         inv_sig(0.97, 0.98), inv_sig(0.85, 0.98)],
        [np.log(var0*0.02), inv_sig(0.03, 0.4), inv_sig(0.08, 0.6), inv_sig(0.85, 0.999),
         np.log(var0*0.20), inv_sig(0.15, 0.4), inv_sig(0.30, 0.6), inv_sig(0.50, 0.999),
         inv_sig(0.94, 0.98), inv_sig(0.92, 0.98)],
        [np.log(var0*0.03), inv_sig(0.04, 0.4), inv_sig(0.10, 0.6), inv_sig(0.82, 0.999),
         np.log(var0*0.08), inv_sig(0.08, 0.4), inv_sig(0.25, 0.6), inv_sig(0.60, 0.999),
         inv_sig(0.95, 0.98), inv_sig(0.88, 0.98)],
    ]

    all_starts = list(base_starts)
    for _ in range(n_starts - len(base_starts)):
        base = base_starts[rng.randint(len(base_starts))]
        perturbed = [b + rng.normal(0, 0.5) for b in base]
        all_starts.append(perturbed)

    for x0 in all_starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B',
                          options={'maxiter': 2000, 'ftol': 1e-10})
            if res.fun < best_val and res.fun < 1e9:
                best_val = res.fun
                best_x = res.x.copy()
        except:
            pass

    if best_x is None:
        return None

    # Extract final parameters
    x = best_x
    omega0 = np.exp(x[0])
    alpha0 = 0.4 / (1.0 + np.exp(-x[1]))
    gamma0 = 0.6 / (1.0 + np.exp(-x[2]))
    beta0  = 0.999 / (1.0 + np.exp(-x[3]))
    omega1 = np.exp(x[4])
    alpha1 = 0.4 / (1.0 + np.exp(-x[5]))
    gamma1 = 0.6 / (1.0 + np.exp(-x[6]))
    beta1  = 0.999 / (1.0 + np.exp(-x[7]))
    p00 = 0.98 / (1.0 + np.exp(-x[8])) + 0.01
    p11 = 0.98 / (1.0 + np.exp(-x[9])) + 0.01

    ll, xi_filtered, h0, h1, h_combined = ms_gjr_filter(
        omega0, alpha0, gamma0, beta0,
        omega1, alpha1, gamma1, beta1,
        p00, p11, ret
    )

    # Ensure regime 0 is the calm regime
    pers0 = alpha0 + 0.5 * gamma0 + beta0
    pers1 = alpha1 + 0.5 * gamma1 + beta1
    unc0 = omega0 / max(1.0 - pers0, 0.001)
    unc1 = omega1 / max(1.0 - pers1, 0.001)

    if unc1 < unc0:
        # Swap regimes
        omega0, omega1 = omega1, omega0
        alpha0, alpha1 = alpha1, alpha0
        gamma0, gamma1 = gamma1, gamma0
        beta0, beta1 = beta1, beta0
        p00, p11 = p11, p00
        ll, xi_filtered, h0, h1, h_combined = ms_gjr_filter(
            omega0, alpha0, gamma0, beta0,
            omega1, alpha1, gamma1, beta1,
            p00, p11, ret
        )

    mean_prob0 = np.mean(xi_filtered)
    degenerate = (mean_prob0 < 0.05 or mean_prob0 > 0.95)

    return {
        'regime0': {'omega': float(omega0), 'alpha': float(alpha0), 'gamma': float(gamma0),
                   'beta': float(beta0), 'persistence': float(alpha0 + 0.5*gamma0 + beta0)},
        'regime1': {'omega': float(omega1), 'alpha': float(alpha1), 'gamma': float(gamma1),
                   'beta': float(beta1), 'persistence': float(alpha1 + 0.5*gamma1 + beta1)},
        'p00': float(p00), 'p11': float(p11),
        'ergodic_prob0': float((1.0 - p11) / (2.0 - p00 - p11 + 1e-10)),
        'h_combined': h_combined,
        'h0': h0, 'h1': h1,
        'xi_filtered': xi_filtered,
        'nll': float(best_val),
        'degenerate': degenerate,
        'mean_prob_regime0': float(mean_prob0),
        'omega0': omega0, 'alpha0': alpha0, 'gamma0': gamma0, 'beta0': beta0,
        'omega1': omega1, 'alpha1': alpha1, 'gamma1': gamma1, 'beta1': beta1,
        '_p00': p00, '_p11': p11,
    }


# ============================================================
# 6. Model M3: MS(2)-GJR + VIX indicator
# ============================================================
@njit
def ms_gjr_vix_filter(omega0, alpha0, gamma0, beta0,
                      omega1, alpha1, gamma1, beta1,
                      c00, d00, c11, d11,
                      returns, vix_pct):
    """Hamilton filter with VIX-driven time-varying transition probabilities.

    P(s_t=0|s_{t-1}=0) = logistic(c00 + d00 * vix_pct_{t-1})
    P(s_t=1|s_{t-1}=1) = logistic(c11 + d11 * vix_pct_{t-1})
    """
    T = len(returns)
    xi_filtered = np.empty(T)
    h0 = np.empty(T)
    h1 = np.empty(T)
    h_combined = np.empty(T)

    var_all = np.var(returns)
    h0[0] = var_all * 0.5
    h1[0] = var_all * 2.0
    xi_filtered[0] = 0.5
    h_combined[0] = 0.5 * h0[0] + 0.5 * h1[0]

    log_lik = 0.0

    for t in range(1, T):
        vp = vix_pct[t-1]
        logit_p00 = c00 + d00 * vp
        logit_p11 = c11 + d11 * vp

        # Clip
        if logit_p00 > 10.0: logit_p00 = 10.0
        if logit_p00 < -10.0: logit_p00 = -10.0
        if logit_p11 > 10.0: logit_p11 = 10.0
        if logit_p11 < -10.0: logit_p11 = -10.0

        p00_t = 1.0 / (1.0 + np.exp(-logit_p00))
        p11_t = 1.0 / (1.0 + np.exp(-logit_p11))

        xi_pred_0 = p00_t * xi_filtered[t-1] + (1.0 - p11_t) * (1.0 - xi_filtered[t-1])
        xi_pred_0 = max(min(xi_pred_0, 1.0 - 1e-8), 1e-8)
        xi_pred_1 = 1.0 - xi_pred_0

        r2_prev = returns[t-1] ** 2
        ind_prev = 1.0 if returns[t-1] < 0 else 0.0
        h_prev = h_combined[t-1]

        h0[t] = omega0 + alpha0 * r2_prev + gamma0 * r2_prev * ind_prev + beta0 * h_prev
        h1[t] = omega1 + alpha1 * r2_prev + gamma1 * r2_prev * ind_prev + beta1 * h_prev
        if h0[t] < 1e-16: h0[t] = 1e-16
        if h1[t] < 1e-16: h1[t] = 1e-16

        r_t = returns[t]
        f0 = (1.0 / np.sqrt(2.0 * np.pi * h0[t])) * np.exp(-0.5 * r_t**2 / h0[t])
        f1 = (1.0 / np.sqrt(2.0 * np.pi * h1[t])) * np.exp(-0.5 * r_t**2 / h1[t])

        f_total = xi_pred_0 * f0 + xi_pred_1 * f1
        if f_total < 1e-300: f_total = 1e-300

        log_lik += np.log(f_total)

        xi_filtered[t] = xi_pred_0 * f0 / f_total
        xi_filtered[t] = max(min(xi_filtered[t], 1.0 - 1e-8), 1e-8)

        h_combined[t] = xi_filtered[t] * h0[t] + (1.0 - xi_filtered[t]) * h1[t]

    return log_lik, xi_filtered, h0, h1, h_combined


def fit_ms_gjr_vix(returns, vix_pct, n_starts=10):
    """Fit MS(2)-GJR with VIX-driven transition probabilities."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    vpct = np.ascontiguousarray(vix_pct, dtype=np.float64)
    var0 = np.var(ret)

    def inv_sig(y, upper=1.0):
        y_clipped = max(min(y, upper*0.999), upper*0.001)
        return np.log(y_clipped / (upper - y_clipped))

    def neg_ll(x):
        omega0 = np.exp(x[0])
        alpha0 = 0.4 / (1.0 + np.exp(-x[1]))
        gamma0 = 0.6 / (1.0 + np.exp(-x[2]))
        beta0  = 0.999 / (1.0 + np.exp(-x[3]))
        omega1 = np.exp(x[4])
        alpha1 = 0.4 / (1.0 + np.exp(-x[5]))
        gamma1 = 0.6 / (1.0 + np.exp(-x[6]))
        beta1  = 0.999 / (1.0 + np.exp(-x[7]))
        c00 = x[8]
        d00 = x[9]
        c11 = x[10]
        d11 = x[11]

        if alpha0 + 0.5*gamma0 + beta0 >= 0.999:
            return 1e10
        if alpha1 + 0.5*gamma1 + beta1 >= 0.999:
            return 1e10

        ll, _, _, _, _ = ms_gjr_vix_filter(
            omega0, alpha0, gamma0, beta0,
            omega1, alpha1, gamma1, beta1,
            c00, d00, c11, d11,
            ret, vpct
        )
        if np.isnan(ll) or np.isinf(ll):
            return 1e10
        return -ll

    rng = np.random.RandomState(42)
    best_val = 1e20
    best_x = None

    base_starts = [
        [np.log(var0*0.01), inv_sig(0.02, 0.4), inv_sig(0.05, 0.6), inv_sig(0.90, 0.999),
         np.log(var0*0.10), inv_sig(0.10, 0.4), inv_sig(0.20, 0.6), inv_sig(0.70, 0.999),
         3.0, -1.0, 2.0, 1.0],
        [np.log(var0*0.005), inv_sig(0.01, 0.4), inv_sig(0.03, 0.6), inv_sig(0.93, 0.999),
         np.log(var0*0.05), inv_sig(0.05, 0.4), inv_sig(0.15, 0.6), inv_sig(0.75, 0.999),
         2.5, -2.0, 1.5, 2.0],
        [np.log(var0*0.02), inv_sig(0.03, 0.4), inv_sig(0.08, 0.6), inv_sig(0.85, 0.999),
         np.log(var0*0.20), inv_sig(0.15, 0.4), inv_sig(0.30, 0.6), inv_sig(0.50, 0.999),
         2.0, -0.5, 2.5, 0.5],
    ]

    all_starts = list(base_starts)
    for _ in range(n_starts - len(base_starts)):
        base = base_starts[rng.randint(len(base_starts))]
        perturbed = [b + rng.normal(0, 0.5) for b in base]
        all_starts.append(perturbed)

    for x0 in all_starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B',
                          options={'maxiter': 2000, 'ftol': 1e-10})
            if res.fun < best_val and res.fun < 1e9:
                best_val = res.fun
                best_x = res.x.copy()
        except:
            pass

    if best_x is None:
        return None

    x = best_x
    omega0 = np.exp(x[0])
    alpha0 = 0.4 / (1.0 + np.exp(-x[1]))
    gamma0 = 0.6 / (1.0 + np.exp(-x[2]))
    beta0  = 0.999 / (1.0 + np.exp(-x[3]))
    omega1 = np.exp(x[4])
    alpha1 = 0.4 / (1.0 + np.exp(-x[5]))
    gamma1 = 0.6 / (1.0 + np.exp(-x[6]))
    beta1  = 0.999 / (1.0 + np.exp(-x[7]))
    c00, d00, c11, d11 = x[8], x[9], x[10], x[11]

    ll, xi_filtered, h0, h1, h_combined = ms_gjr_vix_filter(
        omega0, alpha0, gamma0, beta0,
        omega1, alpha1, gamma1, beta1,
        c00, d00, c11, d11,
        ret, vpct
    )

    # Ensure regime 0 is calm
    unc0 = omega0 / max(1.0 - alpha0 - 0.5*gamma0 - beta0, 0.001)
    unc1 = omega1 / max(1.0 - alpha1 - 0.5*gamma1 - beta1, 0.001)

    if unc1 < unc0:
        omega0, omega1 = omega1, omega0
        alpha0, alpha1 = alpha1, alpha0
        gamma0, gamma1 = gamma1, gamma0
        beta0, beta1 = beta1, beta0
        c00, c11 = c11, c00
        d00, d11 = d11, d00
        ll, xi_filtered, h0, h1, h_combined = ms_gjr_vix_filter(
            omega0, alpha0, gamma0, beta0,
            omega1, alpha1, gamma1, beta1,
            c00, d00, c11, d11,
            ret, vpct
        )

    mean_prob0 = np.mean(xi_filtered)

    return {
        'regime0': {'omega': float(omega0), 'alpha': float(alpha0), 'gamma': float(gamma0),
                   'beta': float(beta0), 'persistence': float(alpha0 + 0.5*gamma0 + beta0)},
        'regime1': {'omega': float(omega1), 'alpha': float(alpha1), 'gamma': float(gamma1),
                   'beta': float(beta1), 'persistence': float(alpha1 + 0.5*gamma1 + beta1)},
        'c00': float(c00), 'd00': float(d00), 'c11': float(c11), 'd11': float(d11),
        'h_combined': h_combined, 'h0': h0, 'h1': h1,
        'xi_filtered': xi_filtered,
        'nll': float(best_val),
        'degenerate': (mean_prob0 < 0.05 or mean_prob0 > 0.95),
        'mean_prob_regime0': float(mean_prob0),
        'omega0': omega0, 'alpha0': alpha0, 'gamma0': gamma0, 'beta0': beta0,
        'omega1': omega1, 'alpha1': alpha1, 'gamma1': gamma1, 'beta1': beta1,
        '_c00': c00, '_d00': d00, '_c11': c11, '_d11': d11,
    }


# ============================================================
# 7. QLIKE loss and DM test
# ============================================================
def qlike(actual_r2, predicted_h):
    """QLIKE loss (Patton 2011). Lower is better.
    Add floor to r2 to avoid log(0)."""
    mask = (predicted_h > 1e-20) & np.isfinite(actual_r2) & np.isfinite(predicted_h)
    a = actual_r2[mask].copy()
    p = predicted_h[mask].copy()
    # Floor r2 to avoid log(0) -- days with exactly zero return
    a = np.maximum(a, 1e-20)
    return np.mean(a / p - np.log(a / p) - 1.0)


def qlike_losses(actual_r2, predicted_h):
    """Per-observation QLIKE losses for DM test."""
    a = np.maximum(actual_r2, 1e-20)
    p = np.maximum(predicted_h, 1e-20)
    losses = a / p - np.log(a / p) - 1.0
    # Mark invalid
    invalid = ~(np.isfinite(a) & np.isfinite(p) & (p > 1e-20))
    losses[invalid] = np.nan
    return losses


def dm_test(loss1, loss2):
    """Diebold-Mariano test. Negative t means model 1 is better."""
    mask = np.isfinite(loss1) & np.isfinite(loss2)
    d = loss1[mask] - loss2[mask]
    n = len(d)
    if n < 50:
        return 0.0, 1.0

    mean_d = np.mean(d)

    # Newey-West HAC variance
    max_lag = int(n ** (1.0/3.0))
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, max_lag + 1):
        w = 1.0 - k / (max_lag + 1.0)
        gamma_k = np.mean((d[k:] - mean_d) * (d[:-k] - mean_d))
        hac_var += 2.0 * w * gamma_k

    if hac_var <= 0:
        hac_var = gamma0

    se = np.sqrt(hac_var / n)
    if se < 1e-15:
        return 0.0, 1.0

    t_stat = mean_d / se
    p_val = 2.0 * (1.0 - norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


# ============================================================
# 8. OOS Rolling Forecasting
# ============================================================
def run_oos_forecast(df, oos_start='2013-01-01', window=2000, refit_every=63):
    """Run OOS forecasting for all 4 models."""

    oos_mask = df.index >= pd.Timestamp(oos_start)
    if not oos_mask.any():
        print(f"  ERROR: No data after {oos_start}")
        return None

    oos_start_idx = np.where(oos_mask)[0][0]

    # Ensure enough history
    if oos_start_idx < window:
        oos_start_idx = window
        print(f"  Adjusted OOS start to index {oos_start_idx} ({df.index[oos_start_idx].date()}) "
              f"due to window requirement")

    T = len(df)
    oos_len = T - oos_start_idx
    print(f"\n  OOS period: {df.index[oos_start_idx].date()} to {df.index[-1].date()}")
    print(f"  OOS length: {oos_len} days, Window: {window}, Refit: every {refit_every} days")

    returns = df['ret'].values
    r2 = df['r2'].values
    vix_pct = df['vix_pct'].values
    vix9d_vals = df['vix9d'].values
    vix9d_scaled = np.where(np.isfinite(vix9d_vals), (vix9d_vals / 100.0) ** 2, 0.0)

    # Storage
    h_m1 = np.full(T, np.nan)
    h_m2 = np.full(T, np.nan)
    h_m3 = np.full(T, np.nan)
    h_m4 = np.full(T, np.nan)

    regime_prob_m2 = np.full(T, np.nan)
    regime_prob_m3 = np.full(T, np.nan)

    param_history_m2 = []

    last_fit = -refit_every
    last_m1 = None
    last_m2 = None
    last_m3 = None
    last_m4 = None

    n_refits = 0
    n_m2_fails = 0
    n_m3_fails = 0
    n_m4_fails = 0

    for t in range(oos_start_idx, T):
        # Refit check
        if t - last_fit >= refit_every:
            train_start = t - window
            if train_start < 0:
                train_start = 0
            train_end = t

            train_ret = returns[train_start:train_end]
            train_vpct = vix_pct[train_start:train_end]
            train_vix9d = vix9d_scaled[train_start:train_end]

            if n_refits % 5 == 0:
                print(f"    Refit #{n_refits} at t={t} ({df.index[t].date()})...")

            # M1: GJR-t
            last_m1 = fit_gjr_t(train_ret)

            # M2: MS-GJR
            m2 = fit_ms_gjr(train_ret, n_starts=10)
            if m2 is not None:
                if m2['degenerate']:
                    n_m2_fails += 1
                else:
                    last_m2 = m2
                    param_history_m2.append({
                        'date': str(df.index[t].date()),
                        'regime0': m2['regime0'].copy(),
                        'regime1': m2['regime1'].copy(),
                        'p00': m2['p00'], 'p11': m2['p11'],
                        'mean_prob0': m2['mean_prob_regime0']
                    })
            else:
                n_m2_fails += 1

            # M3: MS-GJR-VIX
            m3 = fit_ms_gjr_vix(train_ret, train_vpct, n_starts=10)
            if m3 is not None:
                if m3['degenerate']:
                    n_m3_fails += 1
                else:
                    last_m3 = m3
            else:
                n_m3_fails += 1

            # M4: A4f-VIX9D-t
            has_vix9d = np.any(train_vix9d > 0)
            if has_vix9d:
                m4 = fit_a4f_vix9d_t(train_ret, train_vix9d)
                if m4 is not None:
                    last_m4 = m4
                else:
                    n_m4_fails += 1
            else:
                n_m4_fails += 1

            last_fit = t
            n_refits += 1

        # === One-step-ahead forecasts ===

        # M1: GJR-t
        if last_m1 is not None:
            p = last_m1
            if t == oos_start_idx or np.isnan(h_m1[t-1]):
                h_prev = p['h'][-1]
            else:
                h_prev = h_m1[t-1]

            r_prev = returns[t-1]
            r2_prev = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_m1[t] = p['omega'] + p['alpha']*r2_prev + p['gamma']*r2_prev*ind + p['beta']*h_prev
            h_m1[t] = max(h_m1[t], 1e-16)

        # M2: MS-GJR
        if last_m2 is not None:
            m = last_m2
            if t == oos_start_idx or np.isnan(h_m2[t-1]):
                xi_prev = m['xi_filtered'][-1]
                h_prev = m['h_combined'][-1]
            else:
                xi_prev = regime_prob_m2[t-1]
                h_prev = h_m2[t-1]

            p00 = m['_p00']
            p11 = m['_p11']

            xi_pred_0 = p00 * xi_prev + (1.0 - p11) * (1.0 - xi_prev)
            xi_pred_0 = max(min(xi_pred_0, 1.0-1e-8), 1e-8)
            xi_pred_1 = 1.0 - xi_pred_0

            r_prev = returns[t-1]
            r2_prev = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0

            h0_t = m['omega0'] + m['alpha0']*r2_prev + m['gamma0']*r2_prev*ind + m['beta0']*h_prev
            h1_t = m['omega1'] + m['alpha1']*r2_prev + m['gamma1']*r2_prev*ind + m['beta1']*h_prev
            h0_t = max(h0_t, 1e-16)
            h1_t = max(h1_t, 1e-16)

            h_m2[t] = xi_pred_0 * h0_t + xi_pred_1 * h1_t

            # Update filtered prob (using observation at t for next step)
            f0 = (1.0/np.sqrt(2*np.pi*h0_t)) * np.exp(-0.5*returns[t]**2/h0_t)
            f1 = (1.0/np.sqrt(2*np.pi*h1_t)) * np.exp(-0.5*returns[t]**2/h1_t)
            f_total = xi_pred_0*f0 + xi_pred_1*f1
            if f_total < 1e-300:
                f_total = 1e-300
            regime_prob_m2[t] = np.clip(xi_pred_0*f0/f_total, 1e-8, 1-1e-8)

        # M3: MS-GJR-VIX
        if last_m3 is not None:
            m = last_m3
            if t == oos_start_idx or np.isnan(h_m3[t-1]):
                xi_prev = m['xi_filtered'][-1]
                h_prev = m['h_combined'][-1]
            else:
                xi_prev = regime_prob_m3[t-1]
                h_prev = h_m3[t-1]

            vp = vix_pct[t-1]
            logit_p00 = np.clip(m['_c00'] + m['_d00']*vp, -10, 10)
            logit_p11 = np.clip(m['_c11'] + m['_d11']*vp, -10, 10)
            p00_t = 1.0/(1.0+np.exp(-logit_p00))
            p11_t = 1.0/(1.0+np.exp(-logit_p11))

            xi_pred_0 = p00_t * xi_prev + (1.0 - p11_t) * (1.0 - xi_prev)
            xi_pred_0 = max(min(xi_pred_0, 1.0-1e-8), 1e-8)
            xi_pred_1 = 1.0 - xi_pred_0

            r_prev = returns[t-1]
            r2_prev = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0

            h0_t = m['omega0'] + m['alpha0']*r2_prev + m['gamma0']*r2_prev*ind + m['beta0']*h_prev
            h1_t = m['omega1'] + m['alpha1']*r2_prev + m['gamma1']*r2_prev*ind + m['beta1']*h_prev
            h0_t = max(h0_t, 1e-16)
            h1_t = max(h1_t, 1e-16)

            h_m3[t] = xi_pred_0 * h0_t + xi_pred_1 * h1_t

            f0 = (1.0/np.sqrt(2*np.pi*h0_t)) * np.exp(-0.5*returns[t]**2/h0_t)
            f1 = (1.0/np.sqrt(2*np.pi*h1_t)) * np.exp(-0.5*returns[t]**2/h1_t)
            f_total = xi_pred_0*f0 + xi_pred_1*f1
            if f_total < 1e-300:
                f_total = 1e-300
            regime_prob_m3[t] = np.clip(xi_pred_0*f0/f_total, 1e-8, 1-1e-8)

        # M4: A4f-VIX9D-t
        if last_m4 is not None:
            p = last_m4
            if t == oos_start_idx or np.isnan(h_m4[t-1]):
                h_prev = p['h'][-1]
            else:
                h_prev = h_m4[t-1]

            r_prev = returns[t-1]
            r2_prev = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_m4[t] = (p['omega'] + p['alpha']*r2_prev + p['gamma']*r2_prev*ind +
                       p['beta']*h_prev + p['delta']*vix9d_scaled[t-1])
            h_m4[t] = max(h_m4[t], 1e-16)

    print(f"\n  Completed: {n_refits} refits")
    print(f"  M2 MS-GJR fit failures: {n_m2_fails}/{n_refits}")
    print(f"  M3 MS-GJR-VIX fit failures: {n_m3_fails}/{n_refits}")
    print(f"  M4 A4f-VIX9D failures: {n_m4_fails}/{n_refits}")

    # Count valid OOS observations per model
    oos_sl = slice(oos_start_idx, T)
    for name, h in [('M1', h_m1), ('M2', h_m2), ('M3', h_m3), ('M4', h_m4)]:
        n_valid = np.sum(np.isfinite(h[oos_sl]))
        print(f"  {name} valid OOS forecasts: {n_valid}/{oos_len}")

    return {
        'h_m1': h_m1, 'h_m2': h_m2, 'h_m3': h_m3, 'h_m4': h_m4,
        'regime_prob_m2': regime_prob_m2, 'regime_prob_m3': regime_prob_m3,
        'oos_start_idx': oos_start_idx,
        'param_history_m2': param_history_m2,
        'n_refits': n_refits,
        'n_m2_fails': n_m2_fails, 'n_m3_fails': n_m3_fails, 'n_m4_fails': n_m4_fails
    }


# ============================================================
# 9. VaR evaluation
# ============================================================
def var_backtest(returns, h_forecast, alpha=0.025):
    """VaR backtest with Kupiec (1995) unconditional coverage test."""
    mask = np.isfinite(h_forecast) & np.isfinite(returns) & (h_forecast > 0)
    ret = returns[mask]
    h = h_forecast[mask]
    n_total = len(ret)

    if n_total < 50:
        return {'alpha': alpha, 'violation_rate': np.nan, 'n_violations': 0,
                'n_total': n_total, 'kupiec_pval': np.nan, 'pass': False}

    z_alpha = norm.ppf(alpha)
    var_threshold = z_alpha * np.sqrt(h)

    violations = ret < var_threshold
    vr = float(np.mean(violations))
    n_viol = int(np.sum(violations))

    # Kupiec (1995) LR test: 2 * (LL_unrestricted - LL_restricted)
    if n_viol == 0:
        # No violations: model may be too conservative
        lr_stat = 2 * n_total * np.log((1 - alpha) / 1.0)  # approximate
        lr_pval = 1 - chi2.cdf(abs(lr_stat), 1) if abs(lr_stat) > 0 else 1.0
    elif n_viol == n_total:
        lr_pval = 0.0
    else:
        lr_stat = 2 * (n_viol * np.log(vr / alpha) +
                       (n_total - n_viol) * np.log((1 - vr) / (1 - alpha)))
        lr_pval = float(1 - chi2.cdf(lr_stat, 1))

    return {
        'alpha': alpha,
        'violation_rate': vr,
        'n_violations': n_viol,
        'n_total': n_total,
        'kupiec_pval': lr_pval,
        'pass': lr_pval > 0.05
    }


# ============================================================
# 10. Charts
# ============================================================
def plot_qlike_comparison(qlike_dict, save_path):
    """Bar chart comparing QLIKE across models."""
    models = list(qlike_dict.keys())
    qlikes = [qlike_dict[m] for m in models]

    # Pretty names
    pretty = {
        'M1_GJR_t': 'M1: GJR-t\n(baseline)',
        'M2_MS_GJR': 'M2: MS-GJR',
        'M3_MS_GJR_VIX': 'M3: MS-GJR\n+VIX',
        'M4_A4f_VIX9D_t': 'M4: A4f\nVIX9D-t'
    }
    labels = [pretty.get(m, m) for m in models]

    colors = ['#2196F3', '#FF9800', '#4CAF50', '#E91E63']

    fig, ax = plt.subplots(figsize=(10, 6))

    valid_qlikes = [q if q is not None and np.isfinite(q) else 0 for q in qlikes]
    bars = ax.bar(labels, valid_qlikes, color=colors, alpha=0.85, edgecolor='white', linewidth=1.5)

    for bar, val, orig in zip(bars, valid_qlikes, qlikes):
        if orig is not None and np.isfinite(orig):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
                   f'{orig:.4f}', ha='center', va='bottom', fontsize=12, fontweight='bold')
        else:
            ax.text(bar.get_x() + bar.get_width()/2, 0.01,
                   'N/A', ha='center', va='bottom', fontsize=12, color='red')

    # Highlight best
    valid = [(q, i) for i, q in enumerate(qlikes) if q is not None and np.isfinite(q)]
    if valid:
        best_idx = min(valid, key=lambda x: x[0])[1]
        bars[best_idx].set_edgecolor('#FFD700')
        bars[best_idx].set_linewidth(3)

    ax.set_ylabel('QLIKE Loss (lower = better)', fontsize=13)
    ax.set_title('K1019: OOS QLIKE — Markov-Switching GJR-GARCH', fontsize=14, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    ax.set_axisbelow(True)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved: {save_path}")


def plot_regime_timeline(df, forecasts, oos_start_idx, save_path):
    """Regime probability timeline overlaid with VIX."""
    oos_sl = slice(oos_start_idx, len(df))
    dates = df.index[oos_sl]
    vix = df['vix'].values[oos_sl]
    prob_crisis_m2 = 1.0 - forecasts['regime_prob_m2'][oos_sl]

    fig, ax1 = plt.subplots(figsize=(14, 6))

    ax1.plot(dates, vix, color='#2196F3', alpha=0.7, linewidth=1, label='VIX')
    ax1.set_ylabel('VIX Level', color='#2196F3', fontsize=12)
    ax1.tick_params(axis='y', labelcolor='#2196F3')
    vix_max = np.nanmax(vix) if np.any(np.isfinite(vix)) else 80
    ax1.set_ylim(0, vix_max * 1.15)

    ax2 = ax1.twinx()
    mask = np.isfinite(prob_crisis_m2)
    if np.sum(mask) > 0:
        ax2.fill_between(dates[mask], 0, prob_crisis_m2[mask],
                         color='#FF5722', alpha=0.3, label='P(Crisis)')
        ax2.plot(dates[mask], prob_crisis_m2[mask],
                 color='#FF5722', alpha=0.6, linewidth=0.5)
    ax2.set_ylabel('P(Crisis Regime)', color='#FF5722', fontsize=12)
    ax2.tick_params(axis='y', labelcolor='#FF5722')
    ax2.set_ylim(0, 1.05)

    events = [('2020-03-16', 'COVID'), ('2022-06-13', 'Rate Hikes')]
    for date_str, label in events:
        try:
            evt_date = pd.Timestamp(date_str)
            if dates[0] <= evt_date <= dates[-1]:
                ax1.axvline(x=evt_date, color='gray', linestyle='--', alpha=0.5)
                ax1.text(evt_date, ax1.get_ylim()[1]*0.92, label,
                        rotation=90, va='top', ha='right', fontsize=9, color='gray')
        except:
            pass

    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
    ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    fig.autofmt_xdate()

    ax1.set_title('K1019: MS-GJR Crisis Regime Probability vs VIX', fontsize=14, fontweight='bold')
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved: {save_path}")


def plot_regime_params(param_history, save_path):
    """Compare parameters across regimes over time."""
    if not param_history:
        print("  No param history to plot, skipping")
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    dates = [pd.Timestamp(p['date']) for p in param_history]

    param_names = [
        ('alpha', 'Alpha (ARCH effect)'),
        ('gamma', 'Gamma (Leverage effect)'),
        ('beta', 'Beta (GARCH persistence)'),
        ('persistence', 'Total Persistence')
    ]

    for idx, (pname, title) in enumerate(param_names):
        ax = axes[idx // 2][idx % 2]
        r0_vals = [p['regime0'][pname] for p in param_history]
        r1_vals = [p['regime1'][pname] for p in param_history]

        ax.plot(dates, r0_vals, 'b-o', markersize=4, label='Regime 0 (Calm)', alpha=0.8)
        ax.plot(dates, r1_vals, 'r-s', markersize=4, label='Regime 1 (Crisis)', alpha=0.8)

        ax.set_title(title, fontsize=11, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)
        if len(dates) > 1:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
            ax.xaxis.set_major_locator(mdates.MonthLocator(interval=12))

    fig.suptitle('K1019: MS-GJR Regime Parameter Evolution', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"  Chart saved: {save_path}")


# ============================================================
# 11. Main
# ============================================================
def main():
    print("=" * 70)
    print("K1019: Markov-Switching GJR-GARCH Volatility Forecasting")
    print("=" * 70)

    df = load_data()

    # Descriptive stats
    print("\n--- Descriptive Statistics ---")
    print(f"  Mean return: {df['ret'].mean()*100:.4f}%")
    print(f"  Std return:  {df['ret'].std()*100:.4f}%")
    print(f"  Skewness:    {df['ret'].skew():.4f}")
    print(f"  Kurtosis:    {df['ret'].kurtosis():.4f}")
    print(f"  Mean VIX:    {df['vix'].mean():.2f}")

    # OOS forecast
    print("\n--- Running OOS Forecasting ---")
    forecasts = run_oos_forecast(df, oos_start='2013-01-01', window=2000, refit_every=63)

    if forecasts is None:
        print("ERROR: OOS forecasting failed")
        return

    oos_idx = forecasts['oos_start_idx']
    oos_sl = slice(oos_idx, len(df))
    r2_oos = df['r2'].values[oos_sl]
    ret_oos = df['ret'].values[oos_sl]

    # QLIKE
    print("\n--- QLIKE Evaluation (OOS on r^2, Patton 2011) ---")

    qlike_m1 = qlike(r2_oos, forecasts['h_m1'][oos_sl])
    qlike_m2 = qlike(r2_oos, forecasts['h_m2'][oos_sl])
    qlike_m3 = qlike(r2_oos, forecasts['h_m3'][oos_sl])
    qlike_m4 = qlike(r2_oos, forecasts['h_m4'][oos_sl])

    print(f"  M1 (GJR-t):       QLIKE = {qlike_m1:.6f}")
    print(f"  M2 (MS-GJR):      QLIKE = {qlike_m2:.6f}")
    print(f"  M3 (MS-GJR-VIX):  QLIKE = {qlike_m3:.6f}")
    print(f"  M4 (A4f-VIX9D-t): QLIKE = {qlike_m4:.6f}")

    # DM tests
    print("\n--- Diebold-Mariano Tests (Harvey threshold |t|>3.0) ---")

    loss_m1 = qlike_losses(r2_oos, forecasts['h_m1'][oos_sl])
    loss_m2 = qlike_losses(r2_oos, forecasts['h_m2'][oos_sl])
    loss_m3 = qlike_losses(r2_oos, forecasts['h_m3'][oos_sl])
    loss_m4 = qlike_losses(r2_oos, forecasts['h_m4'][oos_sl])

    dm_tests = {}
    for name, l1, l2 in [
        ('M2_vs_M1', loss_m2, loss_m1),
        ('M3_vs_M1', loss_m3, loss_m1),
        ('M2_vs_M4', loss_m2, loss_m4),
        ('M3_vs_M4', loss_m3, loss_m4),
        ('M4_vs_M1', loss_m4, loss_m1),
    ]:
        t_stat, p_val = dm_test(l1, l2)
        sig = abs(t_stat) > 3.0
        if t_stat < -3.0:
            interp = f'{name.split("_vs_")[0]} better'
        elif t_stat > 3.0:
            interp = f'{name.split("_vs_")[1]} better'
        else:
            interp = 'NS'

        dm_tests[name] = {
            't_stat': t_stat, 'p_value': p_val,
            'significant_harvey': sig, 'interpretation': interp
        }
        mark = '***' if sig else 'NS'
        print(f"  {name}: DM t = {t_stat:+.4f}, p = {p_val:.4f}  [{mark}]")

    # VaR 2.5%
    print("\n--- VaR 2.5% Backtest ---")
    var_results = {}
    for name, h_oos in [('M1_GJR_t', forecasts['h_m1'][oos_sl]),
                         ('M2_MS_GJR', forecasts['h_m2'][oos_sl]),
                         ('M3_MS_GJR_VIX', forecasts['h_m3'][oos_sl]),
                         ('M4_A4f_VIX9D_t', forecasts['h_m4'][oos_sl])]:
        vr = var_backtest(ret_oos, h_oos, alpha=0.025)
        var_results[name] = vr
        status = 'PASS' if vr['pass'] else 'FAIL'
        print(f"  {name}: VR={vr['violation_rate']:.4f} (target=0.025), "
              f"n_viol={vr['n_violations']}/{vr['n_total']}, "
              f"Kupiec p={vr['kupiec_pval']:.4f} [{status}]")

    # Regime analysis
    print("\n--- Regime Analysis ---")
    vix_oos = df['vix'].values[oos_sl]
    prob_m2 = forecasts['regime_prob_m2'][oos_sl]
    prob_m3 = forecasts['regime_prob_m3'][oos_sl]

    regime_analysis = {}
    for name, prob in [('M2', prob_m2), ('M3', prob_m3)]:
        mask = np.isfinite(prob) & np.isfinite(vix_oos)
        if np.sum(mask) > 50:
            corr = float(np.corrcoef(prob[mask], vix_oos[mask])[0, 1])
            crisis_prop = float(np.mean(1.0 - prob[mask]))
        else:
            corr = np.nan
            crisis_prop = np.nan
        regime_analysis[f'corr_{name}_calm_vs_vix'] = corr
        regime_analysis[f'crisis_proportion_{name}'] = crisis_prop
        print(f"  {name}: P(calm) vs VIX corr = {corr:.4f}, Crisis proportion = {crisis_prop:.4f}")

    # Final parameter estimation for reporting
    print("\n--- Final Parameter Estimation (last 2000 obs) ---")
    last_ret = df['ret'].values[-2000:]
    last_vpct = df['vix_pct'].values[-2000:]

    final_ms = fit_ms_gjr(last_ret, n_starts=12)
    final_ms_vix = fit_ms_gjr_vix(last_ret, last_vpct, n_starts=12)

    final_params = {}
    if final_ms is not None:
        r0, r1 = final_ms['regime0'], final_ms['regime1']
        print(f"\n  MS-GJR Regime 0 (Calm): omega={r0['omega']:.2e}, alpha={r0['alpha']:.4f}, "
              f"gamma={r0['gamma']:.4f}, beta={r0['beta']:.4f}, pers={r0['persistence']:.4f}")
        print(f"  MS-GJR Regime 1 (Crisis): omega={r1['omega']:.2e}, alpha={r1['alpha']:.4f}, "
              f"gamma={r1['gamma']:.4f}, beta={r1['beta']:.4f}, pers={r1['persistence']:.4f}")
        print(f"  p00={final_ms['p00']:.4f}, p11={final_ms['p11']:.4f}, "
              f"ergodic_P(calm)={final_ms['ergodic_prob0']:.4f}")
        print(f"  Degenerate: {final_ms['degenerate']}")
        final_params['MS_GJR'] = {
            'regime0': final_ms['regime0'],
            'regime1': final_ms['regime1'],
            'p00': final_ms['p00'], 'p11': final_ms['p11'],
            'ergodic_prob_calm': final_ms['ergodic_prob0']
        }
    else:
        print("  MS-GJR: fit failed")
        final_params['MS_GJR'] = None

    if final_ms_vix is not None:
        print(f"\n  MS-GJR-VIX: c00={final_ms_vix['c00']:.4f}, d00={final_ms_vix['d00']:.4f}, "
              f"c11={final_ms_vix['c11']:.4f}, d11={final_ms_vix['d11']:.4f}")
        print(f"  Degenerate: {final_ms_vix['degenerate']}")
        final_params['MS_GJR_VIX'] = {
            'regime0': final_ms_vix['regime0'],
            'regime1': final_ms_vix['regime1'],
            'c00': final_ms_vix['c00'], 'd00': final_ms_vix['d00'],
            'c11': final_ms_vix['c11'], 'd11': final_ms_vix['d11']
        }
    else:
        print("  MS-GJR-VIX: fit failed")
        final_params['MS_GJR_VIX'] = None

    # ============================================================
    # Build results dict
    # ============================================================
    qlike_dict = {
        'M1_GJR_t': float(qlike_m1) if np.isfinite(qlike_m1) else None,
        'M2_MS_GJR': float(qlike_m2) if np.isfinite(qlike_m2) else None,
        'M3_MS_GJR_VIX': float(qlike_m3) if np.isfinite(qlike_m3) else None,
        'M4_A4f_VIX9D_t': float(qlike_m4) if np.isfinite(qlike_m4) else None,
    }

    # Conclusion
    valid_qlikes = [(v, k) for k, v in qlike_dict.items() if v is not None]
    if valid_qlikes:
        best = min(valid_qlikes, key=lambda x: x[0])
        conc_parts = [f"Best OOS QLIKE: {best[1]} ({best[0]:.6f})."]
    else:
        conc_parts = ["All models failed to produce valid forecasts."]

    dm_m2m1 = dm_tests.get('M2_vs_M1', {})
    t_m2m1 = dm_m2m1.get('t_stat', 0)
    if abs(t_m2m1) > 3.0:
        winner = 'MS-GJR' if t_m2m1 < 0 else 'GJR-t'
        conc_parts.append(f"M2 vs M1: {winner} significantly better (DM t={t_m2m1:.2f}).")
    else:
        conc_parts.append(f"M2 vs M1: No significant difference (DM t={t_m2m1:.2f}, NS at Harvey threshold).")

    dm_m2m4 = dm_tests.get('M2_vs_M4', {})
    t_m2m4 = dm_m2m4.get('t_stat', 0)
    if abs(t_m2m4) > 3.0:
        winner = 'MS-GJR' if t_m2m4 < 0 else 'A4f-VIX9D-t'
        conc_parts.append(f"M2 vs M4: {winner} significantly better (DM t={t_m2m4:.2f}).")
    else:
        conc_parts.append(f"M2 vs M4: No significant difference (DM t={t_m2m4:.2f}, NS).")

    corr_m2 = regime_analysis.get('corr_M2_calm_vs_vix', np.nan)
    if np.isfinite(corr_m2):
        strength = 'strongly' if abs(corr_m2) > 0.5 else ('moderately' if abs(corr_m2) > 0.3 else 'weakly')
        conc_parts.append(
            f"MS-GJR regime probability is {strength} correlated with VIX (r={corr_m2:.3f}), "
            f"{'confirming' if abs(corr_m2) > 0.5 else 'suggesting limited'} overlap with VIX-based approaches."
        )

    conclusion = ' '.join(conc_parts)
    print(f"\n--- Conclusion ---\n  {conclusion}")

    results = {
        'experiment_id': 'K1019',
        'title': 'Markov-Switching GJR-GARCH (MS-GJR) Volatility Forecasting',
        'timestamp': datetime.now().isoformat(),
        'data': {
            'asset': 'SPY',
            'source': 'yfinance',
            'period': f"{df.index[0].date()} to {df.index[-1].date()}",
            'n_total': int(len(df)),
            'oos_start': str(df.index[oos_idx].date()),
            'oos_end': str(df.index[-1].date()),
            'oos_length': int(len(df) - oos_idx),
            'window': 2000, 'refit_every': 63,
        },
        'descriptive_stats': {
            'mean_return_pct': float(df['ret'].mean() * 100),
            'std_return_pct': float(df['ret'].std() * 100),
            'skewness': float(df['ret'].skew()),
            'kurtosis': float(df['ret'].kurtosis()),
            'mean_vix': float(df['vix'].mean()),
        },
        'qlike': qlike_dict,
        'dm_tests': dm_tests,
        'var_backtest_2_5pct': var_results,
        'regime_analysis': regime_analysis,
        'final_parameters': final_params,
        'estimation_diagnostics': {
            'n_refits': forecasts['n_refits'],
            'n_m2_failures': forecasts['n_m2_fails'],
            'n_m3_failures': forecasts['n_m3_fails'],
            'n_m4_failures': forecasts['n_m4_fails'],
        },
        'param_evolution': forecasts['param_history_m2'][:20],  # Limit for JSON size
        'conclusion': conclusion,
        'references': [
            'Hamilton (1989) - Econometrica 57(2): Markov-Switching time series',
            'Gray (1996) - JFE 42(1): Regime-Switching GARCH',
            'Klaassen (2002) - Empirical Economics 27(2): Improving GARCH with RS',
            'Haas, Mittnik & Paolella (2004) - JFEC 2(4): MS-GARCH models',
            'Patton (2011) - JoE 160(1): QLIKE loss function',
            'Harvey (2016): t>3.0 threshold',
        ]
    }

    # JSON serialize helper
    def clean_for_json(obj):
        if isinstance(obj, dict):
            return {k: clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [clean_for_json(v) for v in obj]
        elif isinstance(obj, (np.integer,)):
            return int(obj)
        elif isinstance(obj, (np.floating,)):
            v = float(obj)
            return v if np.isfinite(v) else None
        elif isinstance(obj, np.ndarray):
            return [clean_for_json(x) for x in obj]
        elif isinstance(obj, (np.bool_,)):
            return bool(obj)
        elif isinstance(obj, float):
            return obj if np.isfinite(obj) else None
        return obj

    results_clean = clean_for_json(results)
    results_path = os.path.join(SCRIPT_DIR, 'k1019_results.json')
    with open(results_path, 'w') as f:
        json.dump(results_clean, f, indent=2, default=str)
    print(f"\n  Results saved: {results_path}")

    # Charts
    print("\n--- Generating Charts ---")
    plot_qlike_comparison(qlike_dict, os.path.join(SCRIPT_DIR, 'k1019_qlike_comparison.png'))
    plot_regime_timeline(df, forecasts, oos_idx, os.path.join(SCRIPT_DIR, 'k1019_regime_timeline.png'))
    plot_regime_params(forecasts['param_history_m2'], os.path.join(SCRIPT_DIR, 'k1019_regime_params.png'))

    print("\n" + "=" * 70)
    print("K1019 COMPLETE")
    print("=" * 70)

    return results


if __name__ == '__main__':
    main()
