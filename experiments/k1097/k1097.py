"""
K1097: MS-GJR-t (Student-t innovations) + Full VaR-ES Trinity vs K1019 MS-GJR-N
================================================================================

Research Questions (differentiated from K1019):
  K1019 found MS-GJR-Normal beats GJR-t (DM t=-3.20) but fails VaR backtest
  (Kupiec p=0.005) due to Normal innovations ignoring fat tails.

  K1097 asks: Does Student-t innovations in each regime (MS-GJR-t) close the
  VaR gap AND the QLIKE gap vs A4f-VIX9D-t?

Models:
  M1: GJR-t (baseline, same as K1019)
  M2: MS(2)-GJR-N (Normal innovations, K1019 replication)
  M3: MS(2)-GJR-t (NEW — Student-t innovations, shared df across regimes)
  M4: A4f-VIX9D-t (K1019 reference model)

Evaluation:
  (1) QLIKE on r^2 (Patton 2011)
  (2) DM test (Harvey t>3.0): M3 vs M2 (does t-innov help QLIKE?),
      M3 vs M4 (does MS close A4f gap?)
  (3) **VaR+ES Trinity** at 1% AND 5% (both levels required):
      - Kupiec (1995) LR unconditional coverage test
      - Christoffersen (1998) CC independence test
      - Acerbi-Szekely (2014) Z-test for ES
      - Fissler-Ziegel (2016) FZ0 joint VaR-ES scoring
  (4) VaR computed with correct Student-t quantile (using df from fit)

Data: SPY 2005-2026 (yfinance), VIX, VIX9D. OOS 2013-2026, window=2000,
      refit every 63 days.

References:
  - Hamilton (1989): Econometrica 57(2). Markov-Switching.
  - Gray (1996): JFE 42(1). Regime-Switching GARCH.
  - Klaassen (2002): Empirical Economics 27(2). Improving GARCH with RS.
  - Haas, Mittnik & Paolella (2004): JFEC 2(4). MS-GARCH with t-innovations.
  - Patton (2011): JoE 160(1). QLIKE.
  - Kupiec (1995): J. Derivatives 3(2). VaR unconditional coverage.
  - Christoffersen (1998): IER 39(4). VaR conditional coverage.
  - Acerbi & Szekely (2014): Risk 27(11). ES backtest.
  - Fissler & Ziegel (2016): AoS 44(4). Joint VaR-ES elicitability.
  - Harvey (2016): t>3.0 threshold.

Extends K1019. Links to K988/K1075 (Paper 9 A4f-VIX family).

seed = 42
"""

import numpy as np
import pandas as pd
import json
import math
import warnings
import os
from datetime import datetime
from scipy.optimize import minimize
from scipy.stats import norm, chi2, t as student_t
from scipy.special import gammaln
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
    """Load SPY + VIX + VIX9D from yfinance."""
    print("\n=== K1097: MS-GJR-t (Student-t) vs MS-GJR-N + VaR-ES Trinity ===")
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

    df['vix_pct'] = df['vix'].rolling(252, min_periods=126).apply(
        lambda x: (x.values[-1] - x.min()) / (x.max() - x.min() + 1e-10), raw=False
    )
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
def t_nll_sum(returns, h, df):
    """Sum of negative Student-t log-pdf with scale factor to make Var=h[t].

    Note: for within-df optimization we can drop the df-dependent lgamma terms
    since they are constant in (omega, alpha, gamma, beta). But since df is
    also a parameter (and in M3 varies), we must include them.
    """
    T = len(returns)
    nll = 0.0
    # log normalizer for the standardised t-density (depends on df only)
    log_norm = (math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0)
                - 0.5 * np.log(np.pi * df))
    for t in range(T):
        scale2 = h[t] * (df - 2.0) / df
        if scale2 < 1e-20:
            scale2 = 1e-20
        z2 = returns[t] * returns[t] / scale2
        log_pdf = log_norm - 0.5 * np.log(scale2) - ((df + 1.0) / 2.0) * np.log(1.0 + z2 / df)
        nll -= log_pdf
    return nll


@njit
def gjr_nll_t(omega, alpha, gamma, beta, df, returns):
    h = gjr_h(omega, alpha, gamma, beta, returns)
    return t_nll_sum(returns, h, df)


# ============================================================
# 3. Model M1: GJR-t (baseline)
# ============================================================
def fit_gjr_t(returns):
    """Fit GJR-GARCH(1,1) with Student-t innovations."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    var0 = np.var(ret)

    def neg_ll(x):
        omega = np.exp(x[0])
        alpha = 0.3 / (1.0 + np.exp(-x[1]))
        gamma = 0.5 / (1.0 + np.exp(-x[2]))
        beta = 0.999 / (1.0 + np.exp(-x[3]))
        df = 2.1 + 30.0 / (1.0 + np.exp(-x[4]))  # (2.1, 32.1)
        pers = alpha + 0.5 * gamma + beta
        if pers >= 0.999:
            return 1e10
        try:
            nll = gjr_nll_t(omega, alpha, gamma, beta, df, ret)
        except Exception:
            return 1e10
        if not np.isfinite(nll):
            return 1e10
        return nll

    x0 = np.array([np.log(var0 * 0.05), 0.0, 0.0, 1.5, 0.5])
    best_val = 1e20
    best_x = None
    rng = np.random.RandomState(42)
    for i in range(8):
        if i == 0:
            x_try = x0.copy()
        else:
            x_try = x0 + rng.normal(0, 0.5, size=5)
        try:
            res = minimize(neg_ll, x_try, method='L-BFGS-B',
                           options={'maxiter': 500, 'ftol': 1e-9})
            if res.fun < best_val and res.fun < 1e9:
                best_val = res.fun
                best_x = res.x.copy()
        except Exception:
            pass
    if best_x is None:
        return None
    x = best_x
    omega = float(np.exp(x[0]))
    alpha = float(0.3 / (1.0 + np.exp(-x[1])))
    gamma = float(0.5 / (1.0 + np.exp(-x[2])))
    beta = float(0.999 / (1.0 + np.exp(-x[3])))
    df = float(2.1 + 30.0 / (1.0 + np.exp(-x[4])))
    h = gjr_h(omega, alpha, gamma, beta, ret)
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'df': df, 'h': h, 'nll': float(best_val)}


# ============================================================
# 4. Model M4: A4f-VIX9D-t
# ============================================================
@njit
def a4f_h(omega, alpha, gamma, beta, delta, returns, exog):
    T = len(returns)
    h = np.empty(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        r2 = returns[t-1] ** 2
        ind = 1.0 if returns[t-1] < 0 else 0.0
        ex = exog[t-1] if np.isfinite(exog[t-1]) else 0.0
        h[t] = omega + alpha*r2 + gamma*r2*ind + beta*h[t-1] + delta*ex
        if h[t] < 1e-16:
            h[t] = 1e-16
    return h


def fit_a4f_vix9d_t(returns, vix9d_scaled):
    """A4f-GJR-t: σ² = ω + α r² + γ r² I(r<0) + β σ²_{t-1} + δ (VIX9D/100)²"""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    exog = np.ascontiguousarray(vix9d_scaled, dtype=np.float64)
    var0 = np.var(ret)

    def neg_ll(x):
        omega = np.exp(x[0])
        alpha = 0.3 / (1.0 + np.exp(-x[1]))
        gamma = 0.5 / (1.0 + np.exp(-x[2]))
        beta = 0.999 / (1.0 + np.exp(-x[3]))
        delta = np.exp(x[4])
        df = 2.1 + 30.0 / (1.0 + np.exp(-x[5]))
        pers = alpha + 0.5 * gamma + beta
        if pers >= 0.999:
            return 1e10
        try:
            h = a4f_h(omega, alpha, gamma, beta, delta, ret, exog)
            nll = t_nll_sum(ret, h, df)
        except Exception:
            return 1e10
        if not np.isfinite(nll):
            return 1e10
        return nll

    x0 = np.array([np.log(var0 * 0.03), 0.0, 0.0, 1.5, np.log(1e-4), 0.5])
    best_val = 1e20
    best_x = None
    rng = np.random.RandomState(42)
    for i in range(8):
        x_try = x0 if i == 0 else x0 + rng.normal(0, 0.5, size=6)
        try:
            res = minimize(neg_ll, x_try, method='L-BFGS-B',
                           options={'maxiter': 500, 'ftol': 1e-9})
            if res.fun < best_val and res.fun < 1e9:
                best_val = res.fun
                best_x = res.x.copy()
        except Exception:
            pass
    if best_x is None:
        return None
    x = best_x
    omega = float(np.exp(x[0]))
    alpha = float(0.3 / (1.0 + np.exp(-x[1])))
    gamma = float(0.5 / (1.0 + np.exp(-x[2])))
    beta = float(0.999 / (1.0 + np.exp(-x[3])))
    delta = float(np.exp(x[4]))
    df = float(2.1 + 30.0 / (1.0 + np.exp(-x[5])))
    h = a4f_h(omega, alpha, gamma, beta, delta, ret, exog)
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'delta': delta, 'df': df, 'h': h, 'nll': float(best_val)}


# ============================================================
# 5. Model M2: MS(2)-GJR-Normal (K1019 replication)
# ============================================================
@njit
def ms_gjr_normal_filter(omega0, alpha0, gamma0, beta0,
                         omega1, alpha1, gamma1, beta1,
                         p00, p11, returns):
    T = len(returns)
    xi_filtered = np.empty(T)
    h0 = np.empty(T)
    h1 = np.empty(T)
    h_combined = np.empty(T)

    denom = (2.0 - p00 - p11)
    if abs(denom) < 1e-10:
        pi0 = 0.5
    else:
        pi0 = (1.0 - p11) / denom
    pi0 = max(min(pi0, 0.99), 0.01)

    var_all = np.var(returns)
    h0[0] = var_all * 0.5
    h1[0] = var_all * 2.0
    xi_filtered[0] = pi0
    h_combined[0] = pi0 * h0[0] + (1.0 - pi0) * h1[0]

    log_lik = 0.0
    for t in range(1, T):
        xi_pred_0 = p00 * xi_filtered[t-1] + (1.0 - p11) * (1.0 - xi_filtered[t-1])
        xi_pred_0 = max(min(xi_pred_0, 1.0 - 1e-8), 1e-8)
        xi_pred_1 = 1.0 - xi_pred_0

        r2_prev = returns[t-1] ** 2
        ind_prev = 1.0 if returns[t-1] < 0 else 0.0
        h_prev = h_combined[t-1]

        h0[t] = omega0 + alpha0*r2_prev + gamma0*r2_prev*ind_prev + beta0*h_prev
        h1[t] = omega1 + alpha1*r2_prev + gamma1*r2_prev*ind_prev + beta1*h_prev
        if h0[t] < 1e-16: h0[t] = 1e-16
        if h1[t] < 1e-16: h1[t] = 1e-16

        r_t = returns[t]
        f0 = (1.0 / np.sqrt(2.0 * np.pi * h0[t])) * np.exp(-0.5 * r_t**2 / h0[t])
        f1 = (1.0 / np.sqrt(2.0 * np.pi * h1[t])) * np.exp(-0.5 * r_t**2 / h1[t])
        f_total = xi_pred_0 * f0 + xi_pred_1 * f1
        if f_total < 1e-300:
            f_total = 1e-300

        log_lik += np.log(f_total)
        xi_filtered[t] = xi_pred_0 * f0 / f_total
        xi_filtered[t] = max(min(xi_filtered[t], 1.0 - 1e-8), 1e-8)
        h_combined[t] = xi_filtered[t] * h0[t] + (1.0 - xi_filtered[t]) * h1[t]

    return log_lik, xi_filtered, h0, h1, h_combined


# ============================================================
# 6. Model M3: MS(2)-GJR-t (NEW — shared df across regimes)
# ============================================================
@njit
def _t_density_scaled(r, h, df):
    """Student-t density with Var=h (scale factor applied)."""
    scale2 = h * (df - 2.0) / df
    if scale2 < 1e-20:
        scale2 = 1e-20
    z2 = r * r / scale2
    log_norm = (math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0)
                - 0.5 * np.log(np.pi * df) - 0.5 * np.log(scale2))
    log_pdf = log_norm - ((df + 1.0) / 2.0) * np.log(1.0 + z2 / df)
    return np.exp(log_pdf)


@njit
def ms_gjr_t_filter(omega0, alpha0, gamma0, beta0,
                    omega1, alpha1, gamma1, beta1,
                    p00, p11, df, returns):
    """
    2-regime MS-GJR with SHARED Student-t df across regimes.
    Gray (1996) variance collapse.
    Following Haas, Mittnik & Paolella (2004) MS-GARCH-t.
    Shared df is a common restriction to ensure identifiability and aid convergence.
    """
    T = len(returns)
    xi_filtered = np.empty(T)
    h0 = np.empty(T)
    h1 = np.empty(T)
    h_combined = np.empty(T)

    denom = (2.0 - p00 - p11)
    if abs(denom) < 1e-10:
        pi0 = 0.5
    else:
        pi0 = (1.0 - p11) / denom
    pi0 = max(min(pi0, 0.99), 0.01)

    var_all = np.var(returns)
    h0[0] = var_all * 0.5
    h1[0] = var_all * 2.0
    xi_filtered[0] = pi0
    h_combined[0] = pi0 * h0[0] + (1.0 - pi0) * h1[0]

    log_lik = 0.0
    for t in range(1, T):
        xi_pred_0 = p00 * xi_filtered[t-1] + (1.0 - p11) * (1.0 - xi_filtered[t-1])
        xi_pred_0 = max(min(xi_pred_0, 1.0 - 1e-8), 1e-8)
        xi_pred_1 = 1.0 - xi_pred_0

        r2_prev = returns[t-1] ** 2
        ind_prev = 1.0 if returns[t-1] < 0 else 0.0
        h_prev = h_combined[t-1]

        h0[t] = omega0 + alpha0*r2_prev + gamma0*r2_prev*ind_prev + beta0*h_prev
        h1[t] = omega1 + alpha1*r2_prev + gamma1*r2_prev*ind_prev + beta1*h_prev
        if h0[t] < 1e-16: h0[t] = 1e-16
        if h1[t] < 1e-16: h1[t] = 1e-16

        r_t = returns[t]
        f0 = _t_density_scaled(r_t, h0[t], df)
        f1 = _t_density_scaled(r_t, h1[t], df)
        f_total = xi_pred_0 * f0 + xi_pred_1 * f1
        if f_total < 1e-300:
            f_total = 1e-300

        log_lik += np.log(f_total)
        xi_filtered[t] = xi_pred_0 * f0 / f_total
        xi_filtered[t] = max(min(xi_filtered[t], 1.0 - 1e-8), 1e-8)
        h_combined[t] = xi_filtered[t] * h0[t] + (1.0 - xi_filtered[t]) * h1[t]

    return log_lik, xi_filtered, h0, h1, h_combined


def _extract_ms_params(x, regime_split=8):
    """Decode unconstrained params for 2-regime MS-GJR."""
    omega0 = np.exp(x[0])
    alpha0 = 0.4 / (1.0 + np.exp(-x[1]))
    gamma0 = 0.6 / (1.0 + np.exp(-x[2]))
    beta0 = 0.999 / (1.0 + np.exp(-x[3]))
    omega1 = np.exp(x[4])
    alpha1 = 0.4 / (1.0 + np.exp(-x[5]))
    gamma1 = 0.6 / (1.0 + np.exp(-x[6]))
    beta1 = 0.999 / (1.0 + np.exp(-x[7]))
    p00 = 0.98 / (1.0 + np.exp(-x[8])) + 0.01
    p11 = 0.98 / (1.0 + np.exp(-x[9])) + 0.01
    return omega0, alpha0, gamma0, beta0, omega1, alpha1, gamma1, beta1, p00, p11


def _inv_sig(y, upper=1.0):
    y_clipped = max(min(y, upper*0.999), upper*0.001)
    return np.log(y_clipped / (upper - y_clipped))


def fit_ms_gjr_normal(returns, n_starts=10):
    """Fit MS(2)-GJR-Normal (K1019 style). Gray (1996) collapse."""
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    var0 = np.var(ret)

    def neg_ll(x):
        (omega0, alpha0, gamma0, beta0, omega1, alpha1, gamma1, beta1,
         p00, p11) = _extract_ms_params(x)
        pers0 = alpha0 + 0.5*gamma0 + beta0
        pers1 = alpha1 + 0.5*gamma1 + beta1
        if pers0 >= 0.999 or pers1 >= 0.999:
            return 1e10
        try:
            ll, _, _, _, _ = ms_gjr_normal_filter(
                omega0, alpha0, gamma0, beta0,
                omega1, alpha1, gamma1, beta1, p00, p11, ret)
        except Exception:
            return 1e10
        if not np.isfinite(ll):
            return 1e10
        return -ll

    rng = np.random.RandomState(42)
    base_starts = [
        [np.log(var0*0.01), _inv_sig(0.02, 0.4), _inv_sig(0.05, 0.6), _inv_sig(0.90, 0.999),
         np.log(var0*0.10), _inv_sig(0.10, 0.4), _inv_sig(0.20, 0.6), _inv_sig(0.70, 0.999),
         _inv_sig(0.96, 0.98), _inv_sig(0.90, 0.98)],
        [np.log(var0*0.005), _inv_sig(0.01, 0.4), _inv_sig(0.03, 0.6), _inv_sig(0.93, 0.999),
         np.log(var0*0.05), _inv_sig(0.05, 0.4), _inv_sig(0.15, 0.6), _inv_sig(0.75, 0.999),
         _inv_sig(0.97, 0.98), _inv_sig(0.85, 0.98)],
        [np.log(var0*0.02), _inv_sig(0.03, 0.4), _inv_sig(0.08, 0.6), _inv_sig(0.85, 0.999),
         np.log(var0*0.20), _inv_sig(0.15, 0.4), _inv_sig(0.30, 0.6), _inv_sig(0.50, 0.999),
         _inv_sig(0.94, 0.98), _inv_sig(0.92, 0.98)],
    ]
    all_starts = list(base_starts)
    for _ in range(n_starts - len(base_starts)):
        base = base_starts[rng.randint(len(base_starts))]
        all_starts.append([b + rng.normal(0, 0.5) for b in base])

    best_val = 1e20
    best_x = None
    for x0 in all_starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B',
                           options={'maxiter': 2000, 'ftol': 1e-10})
            if res.fun < best_val and res.fun < 1e9:
                best_val = res.fun
                best_x = res.x.copy()
        except Exception:
            pass
    if best_x is None:
        return None
    (omega0, alpha0, gamma0, beta0, omega1, alpha1, gamma1, beta1,
     p00, p11) = _extract_ms_params(best_x)
    ll, xi_filtered, h0, h1, h_combined = ms_gjr_normal_filter(
        omega0, alpha0, gamma0, beta0,
        omega1, alpha1, gamma1, beta1, p00, p11, ret)

    # Ensure regime 0 is calm (lower uncond var)
    pers0 = alpha0 + 0.5*gamma0 + beta0
    pers1 = alpha1 + 0.5*gamma1 + beta1
    unc0 = omega0 / max(1.0 - pers0, 0.001)
    unc1 = omega1 / max(1.0 - pers1, 0.001)
    if unc1 < unc0:
        omega0, omega1 = omega1, omega0
        alpha0, alpha1 = alpha1, alpha0
        gamma0, gamma1 = gamma1, gamma0
        beta0, beta1 = beta1, beta0
        p00, p11 = p11, p00
        ll, xi_filtered, h0, h1, h_combined = ms_gjr_normal_filter(
            omega0, alpha0, gamma0, beta0,
            omega1, alpha1, gamma1, beta1, p00, p11, ret)

    mean_prob0 = float(np.mean(xi_filtered))
    degenerate = (mean_prob0 < 0.05 or mean_prob0 > 0.95)
    return {
        'regime0': {'omega': float(omega0), 'alpha': float(alpha0), 'gamma': float(gamma0),
                    'beta': float(beta0), 'persistence': float(alpha0 + 0.5*gamma0 + beta0)},
        'regime1': {'omega': float(omega1), 'alpha': float(alpha1), 'gamma': float(gamma1),
                    'beta': float(beta1), 'persistence': float(alpha1 + 0.5*gamma1 + beta1)},
        'p00': float(p00), 'p11': float(p11),
        'ergodic_prob0': float((1.0 - p11) / max(2.0 - p00 - p11, 1e-10)),
        'h_combined': h_combined, 'h0': h0, 'h1': h1,
        'xi_filtered': xi_filtered, 'nll': float(best_val),
        'degenerate': degenerate, 'mean_prob_regime0': mean_prob0,
        'omega0': omega0, 'alpha0': alpha0, 'gamma0': gamma0, 'beta0': beta0,
        'omega1': omega1, 'alpha1': alpha1, 'gamma1': gamma1, 'beta1': beta1,
        '_p00': p00, '_p11': p11,
    }


def fit_ms_gjr_t(returns, n_starts=10):
    """Fit MS(2)-GJR-t (Student-t innovations with SHARED df).

    Param layout: [omega0, alpha0, gamma0, beta0, omega1, alpha1, gamma1, beta1,
                   p00, p11, df]  (11 params, 1 more than Normal version)
    """
    ret = np.ascontiguousarray(returns, dtype=np.float64)
    var0 = np.var(ret)

    def neg_ll(x):
        (omega0, alpha0, gamma0, beta0, omega1, alpha1, gamma1, beta1,
         p00, p11) = _extract_ms_params(x[:10])
        df = 2.1 + 30.0 / (1.0 + np.exp(-x[10]))
        pers0 = alpha0 + 0.5*gamma0 + beta0
        pers1 = alpha1 + 0.5*gamma1 + beta1
        if pers0 >= 0.999 or pers1 >= 0.999:
            return 1e10
        try:
            ll, _, _, _, _ = ms_gjr_t_filter(
                omega0, alpha0, gamma0, beta0,
                omega1, alpha1, gamma1, beta1, p00, p11, df, ret)
        except Exception:
            return 1e10
        if not np.isfinite(ll):
            return 1e10
        return -ll

    rng = np.random.RandomState(42)
    base10 = [
        [np.log(var0*0.01), _inv_sig(0.02, 0.4), _inv_sig(0.05, 0.6), _inv_sig(0.90, 0.999),
         np.log(var0*0.10), _inv_sig(0.10, 0.4), _inv_sig(0.20, 0.6), _inv_sig(0.70, 0.999),
         _inv_sig(0.96, 0.98), _inv_sig(0.90, 0.98)],
        [np.log(var0*0.005), _inv_sig(0.01, 0.4), _inv_sig(0.03, 0.6), _inv_sig(0.93, 0.999),
         np.log(var0*0.05), _inv_sig(0.05, 0.4), _inv_sig(0.15, 0.6), _inv_sig(0.75, 0.999),
         _inv_sig(0.97, 0.98), _inv_sig(0.85, 0.98)],
        [np.log(var0*0.02), _inv_sig(0.03, 0.4), _inv_sig(0.08, 0.6), _inv_sig(0.85, 0.999),
         np.log(var0*0.20), _inv_sig(0.15, 0.4), _inv_sig(0.30, 0.6), _inv_sig(0.50, 0.999),
         _inv_sig(0.94, 0.98), _inv_sig(0.92, 0.98)],
    ]
    # df init: try df=7 (transform: x s.t. 2.1 + 30/(1+exp(-x)) = 7 → x = log((7-2.1)/(32.1-7)) )
    df_init = np.log((7.0 - 2.1) / (32.1 - 7.0))
    base_starts = [b + [df_init] for b in base10]
    all_starts = list(base_starts)
    for _ in range(n_starts - len(base_starts)):
        base = base_starts[rng.randint(len(base_starts))]
        all_starts.append([b + rng.normal(0, 0.5) for b in base])

    best_val = 1e20
    best_x = None
    for x0 in all_starts:
        try:
            res = minimize(neg_ll, x0, method='L-BFGS-B',
                           options={'maxiter': 2500, 'ftol': 1e-10})
            if res.fun < best_val and res.fun < 1e9:
                best_val = res.fun
                best_x = res.x.copy()
        except Exception:
            pass
    if best_x is None:
        return None
    x = best_x
    (omega0, alpha0, gamma0, beta0, omega1, alpha1, gamma1, beta1,
     p00, p11) = _extract_ms_params(x[:10])
    df = 2.1 + 30.0 / (1.0 + np.exp(-x[10]))

    ll, xi_filtered, h0, h1, h_combined = ms_gjr_t_filter(
        omega0, alpha0, gamma0, beta0,
        omega1, alpha1, gamma1, beta1, p00, p11, df, ret)

    # Ensure regime 0 is calm
    pers0 = alpha0 + 0.5*gamma0 + beta0
    pers1 = alpha1 + 0.5*gamma1 + beta1
    unc0 = omega0 / max(1.0 - pers0, 0.001)
    unc1 = omega1 / max(1.0 - pers1, 0.001)
    if unc1 < unc0:
        omega0, omega1 = omega1, omega0
        alpha0, alpha1 = alpha1, alpha0
        gamma0, gamma1 = gamma1, gamma0
        beta0, beta1 = beta1, beta0
        p00, p11 = p11, p00
        ll, xi_filtered, h0, h1, h_combined = ms_gjr_t_filter(
            omega0, alpha0, gamma0, beta0,
            omega1, alpha1, gamma1, beta1, p00, p11, df, ret)

    mean_prob0 = float(np.mean(xi_filtered))
    degenerate = (mean_prob0 < 0.05 or mean_prob0 > 0.95)
    return {
        'regime0': {'omega': float(omega0), 'alpha': float(alpha0), 'gamma': float(gamma0),
                    'beta': float(beta0), 'persistence': float(alpha0 + 0.5*gamma0 + beta0)},
        'regime1': {'omega': float(omega1), 'alpha': float(alpha1), 'gamma': float(gamma1),
                    'beta': float(beta1), 'persistence': float(alpha1 + 0.5*gamma1 + beta1)},
        'p00': float(p00), 'p11': float(p11), 'df': float(df),
        'ergodic_prob0': float((1.0 - p11) / max(2.0 - p00 - p11, 1e-10)),
        'h_combined': h_combined, 'h0': h0, 'h1': h1,
        'xi_filtered': xi_filtered, 'nll': float(best_val),
        'degenerate': degenerate, 'mean_prob_regime0': mean_prob0,
        'omega0': omega0, 'alpha0': alpha0, 'gamma0': gamma0, 'beta0': beta0,
        'omega1': omega1, 'alpha1': alpha1, 'gamma1': gamma1, 'beta1': beta1,
        '_p00': p00, '_p11': p11,
    }


# ============================================================
# 7. Evaluation: QLIKE, DM
# ============================================================
def qlike(actual_r2, predicted_h):
    mask = (predicted_h > 1e-20) & np.isfinite(actual_r2) & np.isfinite(predicted_h)
    a = np.maximum(actual_r2[mask], 1e-20)
    p = predicted_h[mask]
    return np.mean(a / p - np.log(a / p) - 1.0)


def qlike_losses(actual_r2, predicted_h):
    a = np.maximum(actual_r2, 1e-20)
    p = np.maximum(predicted_h, 1e-20)
    losses = a / p - np.log(a / p) - 1.0
    invalid = ~(np.isfinite(a) & np.isfinite(p) & (p > 1e-20))
    losses[invalid] = np.nan
    return losses


def dm_test(loss1, loss2):
    """DM test; negative t means model 1 better."""
    mask = np.isfinite(loss1) & np.isfinite(loss2)
    d = loss1[mask] - loss2[mask]
    n = len(d)
    if n < 50:
        return 0.0, 1.0
    mean_d = np.mean(d)
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
# 8. VaR-ES Trinity Backtests
# ============================================================
def _student_t_quantile_scaled(alpha, df, sigma2):
    """Quantile of Student-t with Var=sigma2 at level alpha.
    Returns x s.t. P(X < x) = alpha.
    Internal t has scale = sqrt(sigma2 * (df-2)/df)."""
    # t.ppf returns standardised t, we multiply by scale sqrt((df-2)/df) * sqrt(sigma2)
    # But since Var(X) = sigma2 and t has Var = df/(df-2), we want X = t * sqrt(sigma2 * (df-2)/df)
    scale = np.sqrt(sigma2 * (df - 2.0) / df)
    return student_t.ppf(alpha, df) * scale


def _student_t_es_scaled(alpha, df, sigma2):
    """Expected shortfall at level alpha for scaled Student-t with Var=sigma2.
    ES_alpha = E[X | X < VaR_alpha].
    Closed form for Student-t: ES = -scale * (df + t_ppf^2)/(df-1) * pdf(t_ppf) / alpha
    (McNeil, Frey, Embrechts 2015 eq. 8.16)"""
    scale = np.sqrt(sigma2 * (df - 2.0) / df)
    q = student_t.ppf(alpha, df)  # standardised quantile
    pdf_q = student_t.pdf(q, df)
    # ES of standardised t at level alpha (note: returns negative value for lower tail)
    es_std = -(df + q * q) / (df - 1.0) * pdf_q / alpha
    return es_std * scale


def _normal_es(alpha, sigma2):
    """ES for Normal with Var=sigma2: ES = -sigma * phi(z)/alpha where z = Phi^{-1}(alpha)."""
    sigma = np.sqrt(sigma2)
    z = norm.ppf(alpha)
    return -sigma * norm.pdf(z) / alpha


def kupiec_test(violations, alpha):
    """Kupiec (1995) LR unconditional coverage test."""
    n = len(violations)
    n_viol = int(np.sum(violations))
    if n == 0:
        return {'lr_stat': np.nan, 'p_value': np.nan, 'pass': False}
    vr = n_viol / n
    if n_viol == 0:
        lr_stat = -2.0 * (n * np.log(1 - alpha))
    elif n_viol == n:
        return {'lr_stat': np.inf, 'p_value': 0.0, 'pass': False, 'vr': vr, 'n_viol': n_viol, 'n': n}
    else:
        ll_u = n_viol * np.log(vr) + (n - n_viol) * np.log(1 - vr)
        ll_r = n_viol * np.log(alpha) + (n - n_viol) * np.log(1 - alpha)
        lr_stat = 2.0 * (ll_u - ll_r)
    p_val = float(1 - chi2.cdf(lr_stat, 1))
    return {'lr_stat': float(lr_stat), 'p_value': p_val, 'pass': p_val > 0.05,
            'vr': float(vr), 'n_viol': n_viol, 'n': int(n)}


def christoffersen_cc_test(violations, alpha):
    """Christoffersen (1998) CC test: joint unconditional + independence.

    Independence: transition prob P(I_t=1|I_{t-1}=0) = P(I_t=1|I_{t-1}=1).
    Combined CC = Kupiec + Independence = chi2(2).
    """
    n = len(violations)
    if n < 2:
        return {'lr_stat': np.nan, 'p_value': np.nan, 'pass': False}

    # Transition counts
    v = violations.astype(int)
    n00 = int(np.sum((v[:-1] == 0) & (v[1:] == 0)))
    n01 = int(np.sum((v[:-1] == 0) & (v[1:] == 1)))
    n10 = int(np.sum((v[:-1] == 1) & (v[1:] == 0)))
    n11 = int(np.sum((v[:-1] == 1) & (v[1:] == 1)))

    # Independence LR
    n0_ = n00 + n01
    n1_ = n10 + n11
    if n0_ == 0 or n1_ == 0:
        # Cannot compute pi_01 or pi_11 — degenerate
        lr_ind = 0.0
    else:
        pi_01 = n01 / n0_ if n0_ > 0 else 0.0
        pi_11 = n11 / n1_ if n1_ > 0 else 0.0
        pi = (n01 + n11) / (n0_ + n1_)

        # Guard log(0)
        def _safe_log(x):
            return np.log(max(x, 1e-300))

        ll_u = (n00 * _safe_log(1 - pi_01) + n01 * _safe_log(pi_01) +
                n10 * _safe_log(1 - pi_11) + n11 * _safe_log(pi_11))
        ll_r = ((n00 + n10) * _safe_log(1 - pi) + (n01 + n11) * _safe_log(pi))
        lr_ind = 2.0 * (ll_u - ll_r)
        if not np.isfinite(lr_ind):
            lr_ind = 0.0

    # Kupiec on full series
    n_viol = int(np.sum(v))
    if n_viol == 0 or n_viol == n:
        lr_uc = 0.0
    else:
        vr = n_viol / n
        ll_u = n_viol * np.log(vr) + (n - n_viol) * np.log(1 - vr)
        ll_r = n_viol * np.log(alpha) + (n - n_viol) * np.log(1 - alpha)
        lr_uc = 2.0 * (ll_u - ll_r)

    lr_cc = lr_uc + lr_ind
    p_val = float(1 - chi2.cdf(lr_cc, 2))
    return {'lr_stat': float(lr_cc), 'lr_uc': float(lr_uc), 'lr_ind': float(lr_ind),
            'p_value': p_val, 'pass': p_val > 0.05,
            'n00': n00, 'n01': n01, 'n10': n10, 'n11': n11}


def acerbi_szekely_z1(returns, var_series, es_series, violations, alpha):
    """Acerbi-Szekely (2014) Z1 statistic for ES backtest.

    Z1 = (1/N_viol) * sum_{t: violation} (r_t / ES_t) + 1

    Under H0 (model correct), E[Z1] = 0.
    If Z1 < 0 → model underestimates tail risk (ES too small in magnitude).
    If Z1 > 0 → model overestimates (conservative).

    Bootstrap p-value computed by resampling.
    """
    viol_mask = violations.astype(bool)
    n_viol = int(np.sum(viol_mask))
    if n_viol < 5:
        return {'z1': np.nan, 'p_value': np.nan, 'pass': False,
                'n_viol': n_viol, 'reason': 'too few violations'}

    r_viol = returns[viol_mask]
    es_viol = es_series[viol_mask]

    # ES is negative (lower tail); r_t / es_t should be ~1 under H0
    ratio = r_viol / es_viol  # Both negative → positive ratio near 1
    z1 = float(np.mean(ratio) - 1.0)

    # Bootstrap p-value (resample returns under H0 proxy: use full sample with same ES values)
    # Proper A&S test uses a Monte Carlo simulation from the model; here we use a simple
    # sign/bootstrap approximation
    rng = np.random.default_rng(42)
    n_boot = 2000
    boot_z1 = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n_viol, size=n_viol)
        boot_z1[b] = np.mean(r_viol[idx] / es_viol[idx]) - 1.0
    # Two-sided p-value
    p_val = float(np.mean(np.abs(boot_z1) >= abs(z1)))
    return {'z1': z1, 'p_value': p_val, 'pass': p_val > 0.05,
            'n_viol': n_viol, 'boot_mean_z1': float(np.mean(boot_z1)),
            'boot_std_z1': float(np.std(boot_z1))}


def fz0_loss(returns, var_series, es_series, alpha):
    """Fissler-Ziegel (2016) FZ0 scoring function for (VaR, ES).

    FZ0(r; v, e) = - 1/(alpha*e) * (v - r) * I(r < v) - v/e + log(-e) - 1

    v, e are negative (lower tail). Lower FZ0 = better joint calibration.
    Strictly consistent scoring rule.
    """
    mask = np.isfinite(var_series) & np.isfinite(es_series) & (es_series < 0)
    r = returns[mask]
    v = var_series[mask]
    e = es_series[mask]
    viol = (r < v).astype(float)
    term1 = -1.0 / (alpha * e) * (v - r) * viol  # Note: (v-r) > 0 when violation, e<0 → term1 > 0
    term2 = -v / e                                 # both negative → positive
    term3 = np.log(-e)
    fz = term1 + term2 + term3 - 1.0
    return float(np.mean(fz)), fz


def full_var_es_trinity(returns, h_forecast, alpha, innovation='t', df_series=None):
    """Full VaR-ES Trinity backtest at confidence level alpha.

    innovation: 't' (Student-t) or 'n' (Normal)
    df_series: array of df values (must be same length as h_forecast) for 't' case;
               if scalar, broadcast.
    """
    mask = np.isfinite(h_forecast) & np.isfinite(returns) & (h_forecast > 1e-20)
    r = returns[mask].astype(np.float64)
    h = h_forecast[mask].astype(np.float64)
    n_total = len(r)
    if n_total < 50:
        return {'n': n_total, 'pass': False, 'reason': 'too few obs'}

    var_series = np.empty(n_total)
    es_series = np.empty(n_total)

    if innovation == 't':
        if df_series is None:
            raise ValueError("df_series required for Student-t")
        if np.isscalar(df_series):
            df_arr = np.full(n_total, float(df_series))
        else:
            df_arr = np.asarray(df_series)[mask].astype(np.float64)
        for i in range(n_total):
            dfi = df_arr[i] if np.isfinite(df_arr[i]) and df_arr[i] > 2.1 else 7.0
            var_series[i] = _student_t_quantile_scaled(alpha, dfi, h[i])
            es_series[i] = _student_t_es_scaled(alpha, dfi, h[i])
    else:  # normal
        z = norm.ppf(alpha)
        var_series = z * np.sqrt(h)
        es_series = np.array([_normal_es(alpha, h_i) for h_i in h])

    violations = (r < var_series).astype(int)

    kupiec = kupiec_test(violations, alpha)
    cc = christoffersen_cc_test(violations, alpha)
    az = acerbi_szekely_z1(r, var_series, es_series, violations, alpha)
    fz_mean, _ = fz0_loss(r, var_series, es_series, alpha)

    # Basel Traffic Light (Green/Yellow/Red) at alpha=0.01 using 250-day window
    if alpha == 0.01:
        window = 250
        if n_total >= window:
            last_window = violations[-window:]
            n_last = int(np.sum(last_window))
            if n_last <= 4:
                basel = 'Green'
            elif n_last <= 9:
                basel = 'Yellow'
            else:
                basel = 'Red'
        else:
            basel = 'N/A (sample too short)'
    else:
        basel = 'N/A (not at 1%)'

    trinity_pass = (kupiec['pass'] and cc['pass'] and basel in ('Green', 'N/A (not at 1%)'))
    return {
        'alpha': alpha, 'innovation': innovation, 'n': n_total,
        'vr': float(np.mean(violations)), 'target_vr': alpha, 'n_viol': int(np.sum(violations)),
        'kupiec': kupiec, 'christoffersen_cc': cc,
        'acerbi_szekely_z1': az, 'fz0_loss': fz_mean, 'basel_traffic': basel,
        'trinity_pass_varonly': trinity_pass,
    }


# ============================================================
# 9. OOS Rolling Forecast
# ============================================================
def run_oos_forecast(df, oos_start='2013-01-01', window=2000, refit_every=63):
    oos_mask = df.index >= pd.Timestamp(oos_start)
    if not oos_mask.any():
        print(f"  ERROR: No data after {oos_start}")
        return None
    oos_start_idx = np.where(oos_mask)[0][0]
    if oos_start_idx < window:
        oos_start_idx = window
        print(f"  Adjusted OOS start to index {oos_start_idx} ({df.index[oos_start_idx].date()})")

    T = len(df)
    oos_len = T - oos_start_idx
    print(f"\n  OOS period: {df.index[oos_start_idx].date()} to {df.index[-1].date()}")
    print(f"  OOS length: {oos_len} days, Window: {window}, Refit: every {refit_every}")

    returns = df['ret'].values.astype(np.float64)
    r2 = df['r2'].values.astype(np.float64)
    vix9d_vals = df['vix9d'].values
    vix9d_scaled = np.where(np.isfinite(vix9d_vals), (vix9d_vals / 100.0) ** 2, 0.0).astype(np.float64)

    h_m1 = np.full(T, np.nan)
    h_m2 = np.full(T, np.nan)
    h_m3 = np.full(T, np.nan)
    h_m4 = np.full(T, np.nan)

    df_m1 = np.full(T, np.nan)  # df for M1 (GJR-t)
    df_m3 = np.full(T, np.nan)  # shared df for M3 (MS-GJR-t)
    df_m4 = np.full(T, np.nan)  # df for M4

    regime_prob_m2 = np.full(T, np.nan)
    regime_prob_m3 = np.full(T, np.nan)

    param_history_m3 = []

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
        if t - last_fit >= refit_every:
            train_start = max(t - window, 0)
            train_end = t
            train_ret = returns[train_start:train_end]
            train_vix9d = vix9d_scaled[train_start:train_end]

            if n_refits % 5 == 0:
                print(f"    Refit #{n_refits} at t={t} ({df.index[t].date()})...")

            # M1: GJR-t
            last_m1 = fit_gjr_t(train_ret)

            # M2: MS-GJR-N
            m2 = fit_ms_gjr_normal(train_ret, n_starts=8)
            if m2 is not None and not m2['degenerate']:
                last_m2 = m2
            else:
                n_m2_fails += 1

            # M3: MS-GJR-t (NEW)
            m3 = fit_ms_gjr_t(train_ret, n_starts=10)
            if m3 is not None and not m3['degenerate']:
                last_m3 = m3
                param_history_m3.append({
                    'date': str(df.index[t].date()),
                    'regime0': m3['regime0'].copy(),
                    'regime1': m3['regime1'].copy(),
                    'p00': m3['p00'], 'p11': m3['p11'], 'df': m3['df'],
                    'mean_prob0': m3['mean_prob_regime0']
                })
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

        # One-step-ahead forecasts
        # M1
        if last_m1 is not None:
            p = last_m1
            if t == oos_start_idx or not np.isfinite(h_m1[t-1]):
                h_prev = p['h'][-1]
            else:
                h_prev = h_m1[t-1]
            r_prev = returns[t-1]
            r2_prev = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_m1[t] = max(p['omega'] + p['alpha']*r2_prev + p['gamma']*r2_prev*ind + p['beta']*h_prev, 1e-16)
            df_m1[t] = p['df']

        # M2: MS-GJR-N
        if last_m2 is not None:
            m = last_m2
            if t == oos_start_idx or not np.isfinite(h_m2[t-1]):
                xi_prev = m['xi_filtered'][-1]
                h_prev = m['h_combined'][-1]
            else:
                xi_prev = regime_prob_m2[t-1]
                h_prev = h_m2[t-1]

            p00 = m['_p00']; p11 = m['_p11']
            xi_pred_0 = max(min(p00*xi_prev + (1.0-p11)*(1.0-xi_prev), 1.0-1e-8), 1e-8)
            xi_pred_1 = 1.0 - xi_pred_0

            r_prev = returns[t-1]
            r2_prev = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h0_t = max(m['omega0'] + m['alpha0']*r2_prev + m['gamma0']*r2_prev*ind + m['beta0']*h_prev, 1e-16)
            h1_t = max(m['omega1'] + m['alpha1']*r2_prev + m['gamma1']*r2_prev*ind + m['beta1']*h_prev, 1e-16)
            h_m2[t] = xi_pred_0*h0_t + xi_pred_1*h1_t

            # Update filtered prob using obs at t
            f0 = (1.0/np.sqrt(2*np.pi*h0_t)) * np.exp(-0.5*returns[t]**2/h0_t)
            f1 = (1.0/np.sqrt(2*np.pi*h1_t)) * np.exp(-0.5*returns[t]**2/h1_t)
            f_total = max(xi_pred_0*f0 + xi_pred_1*f1, 1e-300)
            regime_prob_m2[t] = np.clip(xi_pred_0*f0/f_total, 1e-8, 1-1e-8)

        # M3: MS-GJR-t (NEW)
        if last_m3 is not None:
            m = last_m3
            if t == oos_start_idx or not np.isfinite(h_m3[t-1]):
                xi_prev = m['xi_filtered'][-1]
                h_prev = m['h_combined'][-1]
            else:
                xi_prev = regime_prob_m3[t-1]
                h_prev = h_m3[t-1]

            p00 = m['_p00']; p11 = m['_p11']; df_t = m['df']
            xi_pred_0 = max(min(p00*xi_prev + (1.0-p11)*(1.0-xi_prev), 1.0-1e-8), 1e-8)
            xi_pred_1 = 1.0 - xi_pred_0

            r_prev = returns[t-1]
            r2_prev = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h0_t = max(m['omega0'] + m['alpha0']*r2_prev + m['gamma0']*r2_prev*ind + m['beta0']*h_prev, 1e-16)
            h1_t = max(m['omega1'] + m['alpha1']*r2_prev + m['gamma1']*r2_prev*ind + m['beta1']*h_prev, 1e-16)
            h_m3[t] = xi_pred_0*h0_t + xi_pred_1*h1_t
            df_m3[t] = df_t

            # Student-t densities for filtered prob update
            f0 = _t_density_scaled(returns[t], h0_t, df_t)
            f1 = _t_density_scaled(returns[t], h1_t, df_t)
            f_total = max(xi_pred_0*f0 + xi_pred_1*f1, 1e-300)
            regime_prob_m3[t] = np.clip(xi_pred_0*f0/f_total, 1e-8, 1-1e-8)

        # M4: A4f-VIX9D-t
        if last_m4 is not None:
            p = last_m4
            if t == oos_start_idx or not np.isfinite(h_m4[t-1]):
                h_prev = p['h'][-1]
            else:
                h_prev = h_m4[t-1]
            r_prev = returns[t-1]
            r2_prev = r_prev ** 2
            ind = 1.0 if r_prev < 0 else 0.0
            h_m4[t] = max(p['omega'] + p['alpha']*r2_prev + p['gamma']*r2_prev*ind
                          + p['beta']*h_prev + p['delta']*vix9d_scaled[t-1], 1e-16)
            df_m4[t] = p['df']

    print(f"\n  Completed: {n_refits} refits")
    print(f"  M2 MS-GJR-N failures: {n_m2_fails}/{n_refits}")
    print(f"  M3 MS-GJR-t failures: {n_m3_fails}/{n_refits}")
    print(f"  M4 A4f-VIX9D-t failures: {n_m4_fails}/{n_refits}")

    oos_sl = slice(oos_start_idx, T)
    for name, h in [('M1', h_m1), ('M2', h_m2), ('M3', h_m3), ('M4', h_m4)]:
        n_valid = int(np.sum(np.isfinite(h[oos_sl])))
        print(f"  {name} valid OOS forecasts: {n_valid}/{oos_len}")

    return {
        'h_m1': h_m1, 'h_m2': h_m2, 'h_m3': h_m3, 'h_m4': h_m4,
        'df_m1': df_m1, 'df_m3': df_m3, 'df_m4': df_m4,
        'regime_prob_m2': regime_prob_m2, 'regime_prob_m3': regime_prob_m3,
        'oos_start_idx': oos_start_idx,
        'param_history_m3': param_history_m3,
        'n_refits': n_refits,
        'n_m2_fails': n_m2_fails, 'n_m3_fails': n_m3_fails, 'n_m4_fails': n_m4_fails,
    }


# ============================================================
# 10. Charts
# ============================================================
def plot_qlike_comparison(qlike_dict, save_path):
    models = list(qlike_dict.keys())
    qlikes = [qlike_dict[m] for m in models]
    colors = ['#808080', '#4A90E2', '#2ECC71', '#E74C3C']
    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(models, qlikes, color=colors[:len(models)])
    for bar, q in zip(bars, qlikes):
        if q is not None and np.isfinite(q):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(),
                    f'{q:.4f}', ha='center', va='bottom', fontsize=10)
    best_idx = int(np.argmin([q if q is not None else np.inf for q in qlikes]))
    bars[best_idx].set_edgecolor('gold')
    bars[best_idx].set_linewidth(3)
    ax.set_ylabel('OOS QLIKE (lower = better)')
    ax.set_title('K1097: QLIKE Comparison — MS-GJR-t vs MS-GJR-N vs A4f-VIX9D-t')
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig(save_path, dpi=140, bbox_inches='tight')
    plt.close()


def plot_dm_comparison(dm_tests, save_path):
    names = list(dm_tests.keys())
    t_stats = [dm_tests[n]['t_stat'] for n in names]
    colors = ['#2ECC71' if abs(t) > 3.0 else '#95A5A6' for t in t_stats]
    fig, ax = plt.subplots(figsize=(11, 6))
    bars = ax.barh(names, t_stats, color=colors)
    ax.axvline(0, color='black', lw=0.8)
    ax.axvline(3.0, color='red', ls='--', alpha=0.6, label='Harvey |t|=3.0')
    ax.axvline(-3.0, color='red', ls='--', alpha=0.6)
    for bar, t in zip(bars, t_stats):
        ax.text(bar.get_width() + (0.1 if t >= 0 else -0.1),
                bar.get_y() + bar.get_height()/2,
                f'{t:+.2f}', va='center',
                ha='left' if t >= 0 else 'right', fontsize=10)
    ax.set_xlabel('DM t-statistic (negative means first model better)')
    ax.set_title('K1097: Diebold-Mariano Tests')
    ax.legend()
    ax.grid(axis='x', alpha=0.3)
    plt.tight_layout()
    plt.savefig(save_path, dpi=140, bbox_inches='tight')
    plt.close()


def plot_state_probabilities(df, forecasts, oos_start_idx, save_path):
    oos_sl = slice(oos_start_idx, len(df))
    dates = df.index[oos_sl]
    prob_m2 = forecasts['regime_prob_m2'][oos_sl]
    prob_m3 = forecasts['regime_prob_m3'][oos_sl]
    vix = df['vix'].values[oos_sl]

    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)

    axes[0].plot(dates, prob_m2, color='#4A90E2', lw=0.8)
    axes[0].fill_between(dates, 0, prob_m2, color='#4A90E2', alpha=0.25)
    axes[0].set_ylabel('P(Calm) — M2 (MS-GJR-N)')
    axes[0].set_title('K1097: Filtered Regime Probabilities (Calm state)')
    axes[0].set_ylim(-0.02, 1.02)
    axes[0].grid(alpha=0.3)

    axes[1].plot(dates, prob_m3, color='#2ECC71', lw=0.8)
    axes[1].fill_between(dates, 0, prob_m3, color='#2ECC71', alpha=0.25)
    axes[1].set_ylabel('P(Calm) — M3 (MS-GJR-t)')
    axes[1].set_ylim(-0.02, 1.02)
    axes[1].grid(alpha=0.3)

    axes[2].plot(dates, vix, color='#E74C3C', lw=0.8)
    axes[2].set_ylabel('VIX')
    axes[2].grid(alpha=0.3)
    axes[2].xaxis.set_major_locator(mdates.YearLocator())
    axes[2].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

    plt.xlabel('Date')
    plt.tight_layout()
    plt.savefig(save_path, dpi=140, bbox_inches='tight')
    plt.close()


def plot_parameters(param_history_m3, save_path):
    if not param_history_m3:
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.text(0.5, 0.5, 'No parameter history (all fits failed)',
                ha='center', va='center', fontsize=14)
        plt.savefig(save_path, dpi=140, bbox_inches='tight')
        plt.close()
        return

    dates = [pd.Timestamp(p['date']) for p in param_history_m3]
    r0_beta = [p['regime0']['beta'] for p in param_history_m3]
    r1_beta = [p['regime1']['beta'] for p in param_history_m3]
    r0_gamma = [p['regime0']['gamma'] for p in param_history_m3]
    r1_gamma = [p['regime1']['gamma'] for p in param_history_m3]
    r0_pers = [p['regime0']['persistence'] for p in param_history_m3]
    r1_pers = [p['regime1']['persistence'] for p in param_history_m3]
    df_vals = [p['df'] for p in param_history_m3]

    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    axes[0,0].plot(dates, r0_beta, 'o-', color='#4A90E2', label='Regime 0 (Calm)')
    axes[0,0].plot(dates, r1_beta, 's-', color='#E74C3C', label='Regime 1 (Crisis)')
    axes[0,0].set_ylabel('beta')
    axes[0,0].set_title('Beta (GARCH persistence)')
    axes[0,0].legend(); axes[0,0].grid(alpha=0.3)

    axes[0,1].plot(dates, r0_gamma, 'o-', color='#4A90E2', label='Regime 0')
    axes[0,1].plot(dates, r1_gamma, 's-', color='#E74C3C', label='Regime 1')
    axes[0,1].set_ylabel('gamma')
    axes[0,1].set_title('Gamma (leverage)')
    axes[0,1].legend(); axes[0,1].grid(alpha=0.3)

    axes[1,0].plot(dates, r0_pers, 'o-', color='#4A90E2', label='Regime 0')
    axes[1,0].plot(dates, r1_pers, 's-', color='#E74C3C', label='Regime 1')
    axes[1,0].set_ylabel('persistence (α+γ/2+β)')
    axes[1,0].set_title('Full persistence')
    axes[1,0].legend(); axes[1,0].grid(alpha=0.3)

    axes[1,1].plot(dates, df_vals, 'o-', color='#8E44AD')
    axes[1,1].set_ylabel('df (Student-t)')
    axes[1,1].set_title('Shared degrees of freedom (MS-GJR-t)')
    axes[1,1].grid(alpha=0.3)

    for ax in axes.flat:
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

    plt.suptitle('K1097: M3 (MS-GJR-t) Parameter Evolution', fontsize=14)
    plt.tight_layout()
    plt.savefig(save_path, dpi=140, bbox_inches='tight')
    plt.close()


def plot_var_es_trinity(var_es_results, save_path):
    """Plot VaR/ES Trinity pass/fail for each model at 1% and 5%."""
    models = []
    kupiec_passes = []
    cc_passes = []
    es_passes = []
    fz_values = []

    for model_name, result_pair in var_es_results.items():
        for alpha_label, res in result_pair.items():
            if not isinstance(res, dict) or 'kupiec' not in res:
                continue
            models.append(f'{model_name}@{alpha_label}')
            kupiec_passes.append(1 if res['kupiec'].get('pass', False) else 0)
            cc_passes.append(1 if res['christoffersen_cc'].get('pass', False) else 0)
            es_passes.append(1 if res['acerbi_szekely_z1'].get('pass', False) else 0)
            fz_values.append(res.get('fz0_loss', np.nan))

    fig, axes = plt.subplots(2, 1, figsize=(13, 9))

    # Panel 1: Pass/Fail bars
    n = len(models)
    x = np.arange(n)
    w = 0.25
    axes[0].bar(x - w, kupiec_passes, w, label='Kupiec', color='#4A90E2')
    axes[0].bar(x, cc_passes, w, label='Christoffersen CC', color='#2ECC71')
    axes[0].bar(x + w, es_passes, w, label='Acerbi-Szekely ES', color='#E74C3C')
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(models, rotation=40, ha='right')
    axes[0].set_ylabel('Pass (1) / Fail (0)')
    axes[0].set_title('K1097: VaR-ES Trinity Backtest Results')
    axes[0].legend(loc='upper right')
    axes[0].set_ylim(-0.05, 1.15)
    axes[0].grid(axis='y', alpha=0.3)

    # Panel 2: FZ0 loss (lower=better)
    axes[1].bar(x, fz_values, color='#8E44AD')
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(models, rotation=40, ha='right')
    axes[1].set_ylabel('FZ0 joint loss (lower = better)')
    axes[1].set_title('Fissler-Ziegel Joint VaR-ES Loss')
    axes[1].grid(axis='y', alpha=0.3)
    for i, v in enumerate(fz_values):
        if np.isfinite(v):
            axes[1].text(i, v, f'{v:.3f}', ha='center', va='bottom', fontsize=8)

    plt.tight_layout()
    plt.savefig(save_path, dpi=140, bbox_inches='tight')
    plt.close()


# ============================================================
# 11. Main
# ============================================================
def main():
    print("=" * 72)
    print("K1097: MS-GJR-t (Student-t) + Full VaR-ES Trinity")
    print("=" * 72)

    df = load_data()

    print("\n--- Descriptive Statistics ---")
    print(f"  Mean return: {df['ret'].mean()*100:.4f}%")
    print(f"  Std return:  {df['ret'].std()*100:.4f}%")
    print(f"  Skewness:    {df['ret'].skew():.4f}")
    print(f"  Kurtosis:    {df['ret'].kurtosis():.4f}")
    print(f"  Mean VIX:    {df['vix'].mean():.2f}")

    print("\n--- Running OOS Forecasting ---")
    forecasts = run_oos_forecast(df, oos_start='2013-01-01', window=2000, refit_every=63)
    if forecasts is None:
        print("ERROR: OOS forecasting failed")
        return

    oos_idx = forecasts['oos_start_idx']
    oos_sl = slice(oos_idx, len(df))
    r2_oos = df['r2'].values[oos_sl]
    ret_oos = df['ret'].values[oos_sl]

    print("\n--- QLIKE Evaluation (OOS on r^2, Patton 2011) ---")
    qlike_m1 = qlike(r2_oos, forecasts['h_m1'][oos_sl])
    qlike_m2 = qlike(r2_oos, forecasts['h_m2'][oos_sl])
    qlike_m3 = qlike(r2_oos, forecasts['h_m3'][oos_sl])
    qlike_m4 = qlike(r2_oos, forecasts['h_m4'][oos_sl])
    print(f"  M1 (GJR-t):         QLIKE = {qlike_m1:.6f}")
    print(f"  M2 (MS-GJR-N):      QLIKE = {qlike_m2:.6f}")
    print(f"  M3 (MS-GJR-t NEW):  QLIKE = {qlike_m3:.6f}")
    print(f"  M4 (A4f-VIX9D-t):   QLIKE = {qlike_m4:.6f}")

    print("\n--- Diebold-Mariano Tests (Harvey |t|>3.0) ---")
    loss_m1 = qlike_losses(r2_oos, forecasts['h_m1'][oos_sl])
    loss_m2 = qlike_losses(r2_oos, forecasts['h_m2'][oos_sl])
    loss_m3 = qlike_losses(r2_oos, forecasts['h_m3'][oos_sl])
    loss_m4 = qlike_losses(r2_oos, forecasts['h_m4'][oos_sl])

    dm_tests = {}
    for name, l1, l2 in [
        ('M2_vs_M1', loss_m2, loss_m1),
        ('M3_vs_M1', loss_m3, loss_m1),
        ('M3_vs_M2', loss_m3, loss_m2),   # Does Student-t add value vs Normal MS?
        ('M3_vs_M4', loss_m3, loss_m4),   # Does MS-GJR-t close A4f gap?
        ('M4_vs_M1', loss_m4, loss_m1),
    ]:
        t_stat, p_val = dm_test(l1, l2)
        sig = abs(t_stat) > 3.0
        if t_stat < -3.0:
            interp = f'{name.split("_vs_")[0]} better'
        elif t_stat > 3.0:
            interp = f'{name.split("_vs_")[1]} better'
        else:
            interp = 'NS at Harvey'
        dm_tests[name] = {
            't_stat': float(t_stat), 'p_value': float(p_val),
            'significant_harvey': bool(sig), 'interpretation': interp
        }
        mark = '***' if sig else 'NS'
        print(f"  {name}: DM t = {t_stat:+.4f}, p = {p_val:.4f}  [{mark}]  {interp}")

    # Full VaR-ES Trinity at 1% and 5%
    print("\n--- VaR-ES Trinity Backtest (Kupiec + Christoffersen + Acerbi-Szekely + FZ0) ---")
    var_es_results = {}

    m_specs = [
        ('M1_GJR_t', forecasts['h_m1'][oos_sl], 't', forecasts['df_m1'][oos_sl]),
        ('M2_MS_GJR_N', forecasts['h_m2'][oos_sl], 'n', None),
        ('M3_MS_GJR_t', forecasts['h_m3'][oos_sl], 't', forecasts['df_m3'][oos_sl]),
        ('M4_A4f_VIX9D_t', forecasts['h_m4'][oos_sl], 't', forecasts['df_m4'][oos_sl]),
    ]
    for model_name, h_oos, innov, df_oos in m_specs:
        var_es_results[model_name] = {}
        for alpha in [0.01, 0.05]:
            alpha_label = f'{int(alpha*100)}pct'
            res = full_var_es_trinity(ret_oos, h_oos, alpha,
                                      innovation=innov, df_series=df_oos)
            var_es_results[model_name][alpha_label] = res
            if 'kupiec' in res:
                kup = 'P' if res['kupiec']['pass'] else 'F'
                cc = 'P' if res['christoffersen_cc']['pass'] else 'F'
                az = 'P' if res['acerbi_szekely_z1']['pass'] else 'F'
                print(f"  {model_name} @ {alpha_label}: VR={res['vr']:.4f} (tgt {alpha:.2f}), "
                      f"Kupiec={kup}(p={res['kupiec']['p_value']:.3f}), "
                      f"CC={cc}(p={res['christoffersen_cc']['p_value']:.3f}), "
                      f"AS-ES={az}(p={res['acerbi_szekely_z1']['p_value']:.3f}), "
                      f"FZ0={res['fz0_loss']:.4f}, Basel={res['basel_traffic']}")

    # Regime analysis
    print("\n--- Regime Analysis ---")
    vix_oos = df['vix'].values[oos_sl]
    prob_m2 = forecasts['regime_prob_m2'][oos_sl]
    prob_m3 = forecasts['regime_prob_m3'][oos_sl]
    regime_analysis = {}
    for name, prob in [('M2', prob_m2), ('M3', prob_m3)]:
        mask = np.isfinite(prob) & np.isfinite(vix_oos)
        if int(np.sum(mask)) > 50:
            corr = float(np.corrcoef(prob[mask], vix_oos[mask])[0, 1])
            crisis_prop = float(np.mean(1.0 - prob[mask]))
        else:
            corr = np.nan
            crisis_prop = np.nan
        regime_analysis[f'corr_{name}_calm_vs_vix'] = corr
        regime_analysis[f'crisis_proportion_{name}'] = crisis_prop
        print(f"  {name}: P(calm) vs VIX corr = {corr:.4f}, Crisis proportion = {crisis_prop:.4f}")

    # Regime similarity M2 vs M3
    mask_both = np.isfinite(prob_m2) & np.isfinite(prob_m3)
    if int(np.sum(mask_both)) > 50:
        corr_m2m3 = float(np.corrcoef(prob_m2[mask_both], prob_m3[mask_both])[0, 1])
    else:
        corr_m2m3 = np.nan
    regime_analysis['corr_M2_vs_M3_regime_prob'] = corr_m2m3
    print(f"  M2 vs M3 regime prob corr: {corr_m2m3:.4f}")

    # Final parameter estimation for reporting
    print("\n--- Final Parameter Estimation (last 2000 obs) ---")
    last_ret = df['ret'].values[-2000:]
    final_m3 = fit_ms_gjr_t(last_ret, n_starts=12)
    final_params = {}
    if final_m3 is not None:
        r0, r1 = final_m3['regime0'], final_m3['regime1']
        print(f"\n  MS-GJR-t Regime 0 (Calm): omega={r0['omega']:.2e}, alpha={r0['alpha']:.4f}, "
              f"gamma={r0['gamma']:.4f}, beta={r0['beta']:.4f}, pers={r0['persistence']:.4f}")
        print(f"  MS-GJR-t Regime 1 (Crisis): omega={r1['omega']:.2e}, alpha={r1['alpha']:.4f}, "
              f"gamma={r1['gamma']:.4f}, beta={r1['beta']:.4f}, pers={r1['persistence']:.4f}")
        print(f"  p00={final_m3['p00']:.4f}, p11={final_m3['p11']:.4f}, "
              f"df(shared)={final_m3['df']:.2f}, "
              f"ergodic P(calm)={final_m3['ergodic_prob0']:.4f}")
        final_params['MS_GJR_t'] = {
            'regime0': final_m3['regime0'],
            'regime1': final_m3['regime1'],
            'p00': final_m3['p00'], 'p11': final_m3['p11'],
            'df': final_m3['df'],
            'ergodic_prob_calm': final_m3['ergodic_prob0'],
            'degenerate': final_m3['degenerate']
        }

    # Build results dict
    qlike_dict = {
        'M1_GJR_t': float(qlike_m1) if np.isfinite(qlike_m1) else None,
        'M2_MS_GJR_N': float(qlike_m2) if np.isfinite(qlike_m2) else None,
        'M3_MS_GJR_t': float(qlike_m3) if np.isfinite(qlike_m3) else None,
        'M4_A4f_VIX9D_t': float(qlike_m4) if np.isfinite(qlike_m4) else None,
    }

    # Conclusion
    valid_qlikes = [(v, k) for k, v in qlike_dict.items() if v is not None]
    if valid_qlikes:
        best = min(valid_qlikes, key=lambda x: x[0])
        conc_parts = [f"Best OOS QLIKE: {best[1]} ({best[0]:.6f})."]
    else:
        conc_parts = ["All models failed to produce valid forecasts."]

    dm_m3m2 = dm_tests.get('M3_vs_M2', {})
    t_m3m2 = dm_m3m2.get('t_stat', 0)
    if abs(t_m3m2) > 3.0:
        winner = 'MS-GJR-t' if t_m3m2 < 0 else 'MS-GJR-N'
        conc_parts.append(f"M3 vs M2: {winner} significantly better (DM t={t_m3m2:.2f}).")
    else:
        conc_parts.append(f"M3 vs M2: No significant QLIKE difference (DM t={t_m3m2:.2f}, NS). "
                         f"Student-t innovations do not significantly improve QLIKE over Normal.")

    dm_m3m4 = dm_tests.get('M3_vs_M4', {})
    t_m3m4 = dm_m3m4.get('t_stat', 0)
    if abs(t_m3m4) > 3.0:
        winner = 'MS-GJR-t' if t_m3m4 < 0 else 'A4f-VIX9D-t'
        conc_parts.append(f"M3 vs M4: {winner} significantly better (DM t={t_m3m4:.2f}).")
    else:
        conc_parts.append(f"M3 vs M4: No significant difference (DM t={t_m3m4:.2f}, NS).")

    # VaR comparison (at 1%)
    m3_var1 = var_es_results.get('M3_MS_GJR_t', {}).get('1pct', {})
    m2_var1 = var_es_results.get('M2_MS_GJR_N', {}).get('1pct', {})
    if 'kupiec' in m3_var1 and 'kupiec' in m2_var1:
        m3_pass = m3_var1['kupiec']['pass']
        m2_pass = m2_var1['kupiec']['pass']
        if m3_pass and not m2_pass:
            conc_parts.append(f"VaR 1%: MS-GJR-t PASSES Kupiec (p={m3_var1['kupiec']['p_value']:.3f}) "
                             f"while MS-GJR-N FAILS (p={m2_var1['kupiec']['p_value']:.3f}). "
                             f"Student-t innovations resolve K1019 VaR failure.")
        elif m3_pass and m2_pass:
            conc_parts.append("VaR 1%: both MS-GJR variants PASS Kupiec.")
        elif not m3_pass and not m2_pass:
            conc_parts.append("VaR 1%: both MS-GJR variants FAIL Kupiec — MS structure alone insufficient.")

    conclusion = ' '.join(conc_parts)
    print(f"\n--- Conclusion ---\n  {conclusion}")

    results = {
        'experiment_id': 'K1097',
        'title': 'MS-GJR-t (Student-t innovations) + Full VaR-ES Trinity',
        'timestamp': datetime.now().isoformat(),
        'proposer': 'Claude (K1019 extension — address VaR failure via Student-t)',
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
        'models': {
            'M1_GJR_t': 'GJR-GARCH(1,1) with Student-t innovations (baseline)',
            'M2_MS_GJR_N': 'MS(2)-GJR with Normal innovations (K1019 replication)',
            'M3_MS_GJR_t': 'MS(2)-GJR with shared Student-t df across regimes (NEW)',
            'M4_A4f_VIX9D_t': 'A4f-GJR-t with (VIX9D/100)^2 as exogenous additive term'
        },
        'differentiation_from_k1019': (
            'K1019 used Normal innovations in MS-GJR and failed VaR Kupiec (p=0.005). '
            'K1097 adds Student-t innovations (M3) and full VaR-ES Trinity evaluation '
            '(Kupiec + Christoffersen CC + Acerbi-Szekely ES + FZ0 at 1% and 5%). '
            'Tests whether Student-t in each regime addresses the tail-risk failure.'
        ),
        'descriptive_stats': {
            'mean_return_pct': float(df['ret'].mean() * 100),
            'std_return_pct': float(df['ret'].std() * 100),
            'skewness': float(df['ret'].skew()),
            'kurtosis': float(df['ret'].kurtosis()),
            'mean_vix': float(df['vix'].mean()),
        },
        'qlike': qlike_dict,
        'dm_tests': dm_tests,
        'var_es_trinity': var_es_results,
        'regime_analysis': regime_analysis,
        'final_parameters': final_params,
        'estimation_diagnostics': {
            'n_refits': forecasts['n_refits'],
            'n_m2_failures': forecasts['n_m2_fails'],
            'n_m3_failures': forecasts['n_m3_fails'],
            'n_m4_failures': forecasts['n_m4_fails'],
        },
        'param_evolution_m3_first20': forecasts['param_history_m3'][:20],
        'conclusion': conclusion,
        'references': [
            'Hamilton (1989): Econometrica 57(2)',
            'Gray (1996): JFE 42(1)',
            'Klaassen (2002): Empirical Economics 27(2)',
            'Haas, Mittnik & Paolella (2004): JFEC 2(4) — MS-GARCH-t',
            'Patton (2011): JoE 160(1) — QLIKE',
            'Kupiec (1995): J. Derivatives 3(2) — VaR unconditional coverage',
            'Christoffersen (1998): IER 39(4) — VaR conditional coverage',
            'Acerbi & Szekely (2014): Risk 27(11) — ES backtest',
            'Fissler & Ziegel (2016): AoS 44(4) — Joint VaR-ES elicitability',
            'McNeil, Frey & Embrechts (2015): QRM — Student-t ES closed form',
            'Harvey (2016): t>3.0 threshold',
        ],
        'related_experiments': ['K1019 (MS-GJR-N baseline)', 'K1020 (MS-A4f hybrid)',
                                'K988 (GJR-t baseline)', 'K1075 (A4f-VIX9D)'],
        'seed': 42,
    }

    # JSON serialize
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
    results_path = os.path.join(SCRIPT_DIR, 'k1097_results.json')
    with open(results_path, 'w') as f:
        json.dump(results_clean, f, indent=2, default=str)
    print(f"\n  Results saved: {results_path}")

    # Charts
    print("\n--- Generating Charts ---")
    plot_qlike_comparison(qlike_dict, os.path.join(SCRIPT_DIR, 'k1097_qlike_comparison.png'))
    plot_dm_comparison(dm_tests, os.path.join(SCRIPT_DIR, 'k1097_dm_comparison.png'))
    plot_state_probabilities(df, forecasts, oos_idx, os.path.join(SCRIPT_DIR, 'k1097_state_probabilities.png'))
    plot_parameters(forecasts['param_history_m3'], os.path.join(SCRIPT_DIR, 'k1097_parameters.png'))
    plot_var_es_trinity(var_es_results, os.path.join(SCRIPT_DIR, 'k1097_var_es_trinity.png'))

    # Theta1 evolution (df for M3, as per prompt request — use df as stability indicator)
    fig, ax = plt.subplots(figsize=(11, 5))
    if forecasts['param_history_m3']:
        dates = [pd.Timestamp(p['date']) for p in forecasts['param_history_m3']]
        dfs = [p['df'] for p in forecasts['param_history_m3']]
        ax.plot(dates, dfs, 'o-', color='#8E44AD')
        ax.axhline(np.mean(dfs), ls='--', color='gray', alpha=0.6, label=f'mean={np.mean(dfs):.2f}')
    else:
        ax.text(0.5, 0.5, 'No refit history', ha='center', va='center')
    ax.set_xlabel('Date')
    ax.set_ylabel('df (shared Student-t)')
    ax.set_title('K1097: MS-GJR-t shared df stability over refits')
    ax.grid(alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(os.path.join(SCRIPT_DIR, 'k1097_theta1_evolution.png'), dpi=140, bbox_inches='tight')
    plt.close()

    print("\n" + "=" * 72)
    print("K1097 COMPLETE")
    print("=" * 72)

    return results


if __name__ == '__main__':
    main()
