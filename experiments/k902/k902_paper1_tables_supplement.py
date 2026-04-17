#!/usr/bin/env python3
"""
K902: Paper 1 Descriptive Stats + Cross-Asset QLIKE (C4+C5 resolution)
=====================================================================
[提出: 用戶, 執行: Claude]

Purpose: Re-generate all numbers in Paper 1 Tables 1 and 3 from scratch,
producing a fully traceable results JSON that resolves reviewer comments
C4 (Table 1 descriptive stats untraceable) and C5 (Table 3 QLIKE 8/10 rows).

Task 1 — Table 1 Descriptive Statistics
  Assets: SPY, QQQ, GLD, TLT, EEM, BTC-USD, IWM, SLV, 0050.TW
  Metrics: mean daily return (%), std (%), skewness, kurtosis, min (%), max (%), N
  Plus: GJR gamma (full-sample MLE), gamma t-stat, % negative rolling gamma (w=504)

Task 2 — Table 3 Cross-Asset QLIKE
  Assets: SPY, QQQ, GLD, TLT, EEM, BTC-USD
  Models: GARCH(1,1) vs GJR-GARCH(1,1), expanding window, refit every 63 days
  OOS periods: 2023-01-01 to 2024-12-31 (primary), 2025-01-01 to 2026-03-31 (validation)
  DM test with Newey-West HAC

Data source: yfinance (2005-01-01 to 2026-04-05, or available range)
For 0050.TW: clean_tw50_data() applied

References:
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust
  - Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH
  - Diebold & Mariano (1995) — predictive accuracy test
  - Harvey, Leybourne, Newbold (1997) — DM finite-sample correction
  - Harvey et al. (2016) — t > 3.0 threshold
  - K804: cross-asset GJR + Skewed-t VaR
  - K802: GJR + SkewedT dual champion on SPY
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist

# Add project root for volpred.utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__),
                            'k902_paper1_tables_supplement_results.json')

# Paper 1 uses 2017-01-01 to 2025-12-31 window; download wider for safety
DOWNLOAD_START = '2005-01-01'
DOWNLOAD_END = '2026-04-05'

# Table 1 period matches paper
TABLE1_START = '2017-01-01'
TABLE1_END = '2025-12-31'

# Table 3 OOS periods
OOS_PRIMARY_START = '2023-01-01'
OOS_PRIMARY_END = '2024-12-31'
OOS_VALIDATION_START = '2025-01-01'
OOS_VALIDATION_END = '2026-03-31'

REFIT_EVERY = 63  # re-estimate every ~3 months
ROLLING_GAMMA_WINDOW = 504  # ~2 years for rolling gamma

ASSETS_TABLE1 = [
    {'ticker': 'SPY', 'name': 'SPY', 'is_tw': False},
    {'ticker': 'QQQ', 'name': 'QQQ', 'is_tw': False},
    {'ticker': 'EEM', 'name': 'EEM', 'is_tw': False},
    {'ticker': 'GLD', 'name': 'GLD', 'is_tw': False},
    {'ticker': 'TLT', 'name': 'TLT', 'is_tw': False},
    {'ticker': 'BTC-USD', 'name': 'BTC', 'is_tw': False},
    {'ticker': 'SLV', 'name': 'SLV', 'is_tw': False},
    {'ticker': 'IWM', 'name': 'IWM', 'is_tw': False},
    {'ticker': '0050.TW', 'name': '0050.TW', 'is_tw': True},
]

ASSETS_TABLE3 = ['SPY', 'QQQ', 'GLD', 'TLT', 'EEM', 'BTC-USD']


# ==============================================================
# A. Variance filters
# ==============================================================

def garch_filter(r, omega, alpha, beta):
    """GARCH(1,1): σ²_t = ω + α·r²_{t-1} + β·σ²_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    s2[0] = max(np.var(r), 1e-10)
    for t in range(1, T):
        s2[t] = omega + alpha * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): σ²_t = ω + (α + γ·I_{r<0})·r²_{t-1} + β·σ²_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    s2[0] = max(np.var(r), 1e-10)
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


# ==============================================================
# B. MLE fitting
# ==============================================================

def fit_garch(returns, n_starts=5):
    """Fit GARCH(1,1) via quasi-MLE (Normal). Returns params dict or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 200:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + beta >= 1.0:
            return 1e10
        s2 = garch_filter(r, omega, alpha, beta)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 200)
        a0 = np.clip(0.06 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.90 + 0.03 * np.random.randn(), 0.5, 0.98)
        if a0 + b0 >= 0.99:
            b0 = 0.98 - a0
        o0 = max(1e-8, rv * (1 - a0 - b0))
        try:
            res = minimize(negll, [o0, a0, b0],
                           method='L-BFGS-B',
                           bounds=[(1e-10, None), (0, 0.5), (0, 0.999)],
                           options={'maxiter': 2000})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return None
    omega, alpha, beta = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'persistence': float(alpha + beta)}


def fit_gjr(returns, n_starts=5):
    """Fit GJR-GARCH(1,1) via quasi-MLE (Normal). Returns params dict or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 200:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 100)
        a0 = np.clip(0.05 + 0.03 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.97)
        g0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.95 - a0 - 0.5 * g0
        o0 = max(1e-8, rv * (1 - a0 - b0 - 0.5 * g0))
        try:
            res = minimize(negll, [o0, a0, b0, g0],
                           method='L-BFGS-B',
                           bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                           options={'maxiter': 2000})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * gamma)}


def fit_gjr_unconstrained(returns, n_starts=5):
    """Fit GJR-GARCH(1,1) allowing NEGATIVE gamma (for rolling analysis).

    Standard GJR constrains gamma >= 0, but for rolling analysis we want to
    detect assets where leverage effect is reversed (e.g., GLD, TLT).
    The filter handles negative gamma by the indicator mechanism:
    σ²_t = ω + (α + γ·I_{r<0})·r²_{t-1} + β·σ²_{t-1}
    With gamma < 0, negative shocks ADD LESS to volatility than positive shocks.

    Stationarity: α + β + 0.5*gamma < 1 (gamma can be negative, so this is easier to satisfy).
    Positivity: need α + gamma >= 0 when gamma < 0, so alpha absorbs the leverage term.
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 200:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        # Positivity: alpha + gamma*I >= 0 for both I=0 and I=1
        # I=0: alpha >= 0 (already enforced)
        # I=1: alpha + gamma >= 0
        if alpha + gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * max(gamma, 0) >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        # Check for negative variances (shouldn't happen with positivity constraint)
        if np.any(s2 <= 0):
            return 1e10
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 400)
        a0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.97)
        # Start gamma from both positive and negative initial values
        if seed % 2 == 0:
            g0 = np.clip(0.08 + 0.04 * np.random.randn(), -0.2, 0.3)
        else:
            g0 = np.clip(-0.05 + 0.04 * np.random.randn(), -0.2, 0.3)
        # Ensure alpha + gamma >= 0
        if a0 + g0 < 0:
            g0 = -a0 + 0.01
        if a0 + b0 + 0.5 * max(g0, 0) >= 0.99:
            b0 = 0.95 - a0 - 0.5 * max(g0, 0)
        o0 = max(1e-8, rv * max(0.01, 1 - a0 - b0 - 0.5 * max(g0, 0)))
        try:
            res = minimize(negll, [o0, a0, b0, g0],
                           method='L-BFGS-B',
                           bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (-0.5, 0.5)],
                           options={'maxiter': 2000})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * max(gamma, 0))}


def fit_gjr_with_hessian(returns, n_starts=5):
    """Fit GJR (unconstrained gamma) and compute approximate gamma t-stat."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 200:
        return None
    rv = np.var(r)

    def negll(params):
        omega, alpha, beta, gamma = params
        if omega <= 0 or alpha < 0 or beta < 0:
            return 1e10
        if alpha + gamma < 0:
            return 1e10
        if alpha + beta + 0.5 * max(gamma, 0) >= 1.0:
            return 1e10
        s2 = gjr_filter(r, omega, alpha, beta, gamma)
        if np.any(s2 <= 0):
            return 1e10
        ll = -0.5 * np.sum(np.log(s2[1:]) + r[1:] ** 2 / s2[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    for seed in range(n_starts):
        np.random.seed(seed + 300)
        a0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.97)
        if seed % 2 == 0:
            g0 = np.clip(0.08 + 0.04 * np.random.randn(), -0.2, 0.3)
        else:
            g0 = np.clip(-0.05 + 0.04 * np.random.randn(), -0.2, 0.3)
        if a0 + g0 < 0:
            g0 = -a0 + 0.01
        if a0 + b0 + 0.5 * max(g0, 0) >= 0.99:
            b0 = 0.95 - a0 - 0.5 * max(g0, 0)
        o0 = max(1e-8, rv * max(0.01, 1 - a0 - b0 - 0.5 * max(g0, 0)))
        try:
            res = minimize(negll, [o0, a0, b0, g0],
                           method='L-BFGS-B',
                           bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (-0.5, 0.5)],
                           options={'maxiter': 2000})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            continue
    if best is None:
        return None

    omega, alpha, beta, gamma = best.x

    # Approximate t-stat for gamma via numerical Hessian
    gamma_tstat = np.nan
    try:
        eps = 1e-5
        h = np.zeros(4)
        h[3] = eps
        f_plus = negll(best.x + h)
        f_minus = negll(best.x - h)
        f_center = best.fun
        d2 = (f_plus - 2 * f_center + f_minus) / (eps ** 2)
        if d2 > 0:
            se_gamma = 1.0 / np.sqrt(d2)
            gamma_tstat = gamma / se_gamma
    except Exception:
        pass

    return {
        'omega': float(omega), 'alpha': float(alpha),
        'beta': float(beta), 'gamma': float(gamma),
        'persistence': float(alpha + beta + 0.5 * max(gamma, 0)),
        'gamma_tstat': float(gamma_tstat) if np.isfinite(gamma_tstat) else None
    }


# ==============================================================
# C. OOS forecast + QLIKE
# ==============================================================

def oos_qlike_expanding(returns_full, dates_full, oos_start, oos_end,
                        refit_every=63, model='gjr'):
    """
    Expanding-window OOS QLIKE computation.
    Returns array of QLIKE_t = log(h_t) + r²_t / h_t for each OOS day,
    along with forecast variances and realized r².

    IMPORTANT: OOS forecasts use recursive h[t] = f(h[t-1], r²[t-1]),
    NOT stale variance. Re-estimation happens every refit_every days,
    but the variance filter runs daily with updated data.
    """
    r = np.ascontiguousarray(returns_full, dtype=np.float64)
    d = dates_full

    # Find OOS range
    oos_mask = (d >= pd.Timestamp(oos_start)) & (d <= pd.Timestamp(oos_end))
    oos_idx = np.where(oos_mask)[0]
    if len(oos_idx) == 0:
        return None

    forecasts = []
    realized = []
    qlike_vals = []
    oos_dates_out = []

    # Parameters (will be re-estimated periodically)
    params = None
    last_fit_idx = -refit_every  # force fit on first OOS day

    for i, idx in enumerate(oos_idx):
        if idx < 252:  # need at least 1 year of data
            continue

        # Re-estimate parameters periodically
        if i - last_fit_idx >= refit_every or params is None:
            train_r = r[:idx]
            if model == 'garch':
                params = fit_garch(train_r, n_starts=3)
            else:
                params = fit_gjr(train_r, n_starts=3)
            last_fit_idx = i
            if params is None:
                continue

        # Run filter on all data up to idx (inclusive) to get σ²[idx]
        # Then forecast σ²[idx+1] but we're forecasting for day idx
        # Actually: we forecast h_t for day t=idx using data up to t-1
        train_r = r[:idx]  # data up to but not including t

        if model == 'garch':
            s2 = garch_filter(train_r, params['omega'], params['alpha'], params['beta'])
            # One-step forecast: h_t = omega + alpha * r²_{t-1} + beta * s2_{t-1}
            h_t = (params['omega']
                   + params['alpha'] * train_r[-1] ** 2
                   + params['beta'] * s2[-1])
        else:
            s2 = gjr_filter(train_r, params['omega'], params['alpha'],
                            params['beta'], params['gamma'])
            ind = 1.0 if train_r[-1] < 0 else 0.0
            h_t = (params['omega']
                   + (params['alpha'] + params['gamma'] * ind) * train_r[-1] ** 2
                   + params['beta'] * s2[-1])

        h_t = max(h_t, 1e-12)
        r2_t = r[idx] ** 2

        # QLIKE_t = log(h_t) + r²_t / h_t
        q_t = np.log(h_t) + r2_t / h_t

        if np.isfinite(q_t):
            forecasts.append(float(h_t))
            realized.append(float(r2_t))
            qlike_vals.append(float(q_t))
            oos_dates_out.append(str(d[idx].date()))

    if len(qlike_vals) == 0:
        return None

    return {
        'qlike_mean': float(np.mean(qlike_vals)),
        'qlike_values': qlike_vals,
        'n_oos': len(qlike_vals),
        'dates': oos_dates_out,
        'forecasts': forecasts,
        'realized': realized,
    }


def dm_test_hac(loss1, loss2, h=1):
    """Diebold-Mariano test with Newey-West HAC.
    Negative t → model 1 is better.
    Harvey (2016): |t| > 3.0 for significance.
    """
    d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
    valid = np.isfinite(d)
    d = d[valid]
    n = len(d)
    if n < 10:
        return 0.0, 1.0

    d_mean = np.mean(d)
    max_lag = max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)  # Bartlett kernel
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * w * gamma_l

    var_d = max(var_d, 1e-20)
    se = np.sqrt(var_d / n)
    if se < 1e-12:
        return 0.0, 1.0

    t_stat = d_mean / se
    # Two-sided p-value using normal approximation
    p_val = 2 * (1 - norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


# ==============================================================
# D. Rolling gamma analysis
# ==============================================================

def rolling_gamma_analysis(returns, window=504):
    """Compute rolling GJR gamma estimates with given window.
    Uses UNCONSTRAINED gamma (can be negative) to detect reverse leverage.
    Returns dict with mean_gamma, std_gamma, pct_negative, hac_tstat.
    """
    r = np.ascontiguousarray(returns, dtype=np.float64)
    n = len(r)
    if n < window + 100:
        # Not enough data for meaningful rolling analysis
        # Fall back to full-sample
        params = fit_gjr_unconstrained(r, n_starts=3)
        if params is None:
            return {'mean_gamma': np.nan, 'std_gamma': np.nan,
                    'pct_negative': np.nan, 'n_windows': 0}
        return {'mean_gamma': params['gamma'],
                'std_gamma': 0.0,
                'pct_negative': 0.0 if params['gamma'] >= 0 else 100.0,
                'n_windows': 1}

    gammas = []
    step = max(21, window // 10)  # step ~quarterly for efficiency
    for start in range(0, n - window, step):
        end = start + window
        chunk = r[start:end]
        params = fit_gjr_unconstrained(chunk, n_starts=3)
        if params is not None:
            gammas.append(params['gamma'])

    if len(gammas) == 0:
        return {'mean_gamma': np.nan, 'std_gamma': np.nan,
                'pct_negative': np.nan, 'n_windows': 0}

    gammas = np.array(gammas)
    mean_g = float(np.mean(gammas))
    std_g = float(np.std(gammas))
    pct_neg = float(100 * np.mean(gammas < 0))

    # HAC t-stat for mean(gamma) != 0
    # Simple Newey-West with up to 5 lags
    n_g = len(gammas)
    d = gammas - mean_g
    gamma0 = np.mean(d ** 2)
    var_g = gamma0
    max_lag = min(5, n_g // 4)
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)
        gamma_l = np.mean(d[lag:] * d[:-lag])
        var_g += 2 * w * gamma_l
    var_g = max(var_g, 1e-20)
    se = np.sqrt(var_g / n_g)
    hac_t = mean_g / se if se > 1e-12 else 0.0

    return {
        'mean_gamma': mean_g,
        'std_gamma': std_g,
        'pct_negative': pct_neg,
        'hac_tstat': float(hac_t),
        'n_windows': int(n_g),
    }


# ==============================================================
# E. Data loading
# ==============================================================

def load_asset_data(ticker, is_tw=False):
    """Download data from yfinance and compute returns."""
    print(f"  Downloading {ticker}...")
    df = yf.download(ticker, start=DOWNLOAD_START, end=DOWNLOAD_END,
                     auto_adjust=True, progress=False)
    if df.empty:
        print(f"  WARNING: No data for {ticker}")
        return None, None

    # Handle MultiIndex columns from yfinance
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    prices = df['Close'].dropna()

    if is_tw:
        prices, returns = clean_tw50_data(prices)
        returns = returns.dropna()
    else:
        returns = prices.pct_change().dropna()

    # Remove any remaining extreme outliers (> 50% daily)
    extreme = returns.abs() > 0.50
    if extreme.any():
        print(f"  Removing {extreme.sum()} extreme returns for {ticker}")
        returns = returns[~extreme]

    print(f"  {ticker}: {len(returns)} returns, "
          f"{returns.index[0].date()} to {returns.index[-1].date()}")
    return prices, returns


# ==============================================================
# F. Main execution
# ==============================================================

def run_table1():
    """Task 1: Generate Table 1 descriptive statistics."""
    print("\n" + "=" * 70)
    print("TASK 1: Table 1 — Descriptive Statistics")
    print("=" * 70)

    results = {}

    for asset_info in ASSETS_TABLE1:
        ticker = asset_info['ticker']
        name = asset_info['name']
        is_tw = asset_info['is_tw']

        prices, returns = load_asset_data(ticker, is_tw)
        if returns is None:
            results[name] = {'error': 'No data'}
            continue

        # Filter to Table 1 period (2017-2025)
        mask = (returns.index >= TABLE1_START) & (returns.index <= TABLE1_END)
        r_period = returns[mask]

        if len(r_period) < 100:
            results[name] = {'error': f'Only {len(r_period)} obs in period'}
            continue

        # Basic descriptive stats
        r_arr = r_period.values
        mean_pct = float(np.mean(r_arr) * 100)
        std_pct = float(np.std(r_arr, ddof=1) * 100)
        skew = float(pd.Series(r_arr).skew())
        kurt = float(pd.Series(r_arr).kurtosis())  # excess kurtosis
        min_pct = float(np.min(r_arr) * 100)
        max_pct = float(np.max(r_arr) * 100)
        n_obs = len(r_arr)

        # Full-sample GJR fit for gamma
        gjr_params = fit_gjr_with_hessian(r_arr, n_starts=5)

        # Rolling gamma analysis
        rolling_info = rolling_gamma_analysis(r_arr, window=ROLLING_GAMMA_WINDOW)

        result = {
            'mean_pct': round(mean_pct, 3),
            'std_pct': round(std_pct, 2),
            'skewness': round(skew, 2),
            'kurtosis': round(kurt, 1),
            'min_pct': round(min_pct, 1),
            'max_pct': round(max_pct, 1),
            'n_obs': n_obs,
            'data_start': str(r_period.index[0].date()),
            'data_end': str(r_period.index[-1].date()),
        }

        if gjr_params is not None:
            result['gjr_gamma'] = round(gjr_params['gamma'], 4)
            result['gjr_gamma_tstat'] = (round(gjr_params['gamma_tstat'], 2)
                                         if gjr_params['gamma_tstat'] is not None
                                         else None)
            result['gjr_persistence'] = round(gjr_params['persistence'], 4)
            result['gjr_params'] = {
                'omega': gjr_params['omega'],
                'alpha': gjr_params['alpha'],
                'beta': gjr_params['beta'],
                'gamma': gjr_params['gamma'],
            }

        result['rolling_gamma'] = {
            'mean': round(rolling_info['mean_gamma'], 3)
                    if not np.isnan(rolling_info['mean_gamma']) else None,
            'std': round(rolling_info['std_gamma'], 3)
                   if not np.isnan(rolling_info.get('std_gamma', np.nan)) else None,
            'pct_negative': round(rolling_info['pct_negative'], 0)
                            if not np.isnan(rolling_info['pct_negative']) else None,
            'hac_tstat': round(rolling_info.get('hac_tstat', np.nan), 2)
                         if not np.isnan(rolling_info.get('hac_tstat', np.nan)) else None,
            'n_windows': rolling_info['n_windows'],
        }

        results[name] = result

        print(f"\n  {name}:")
        print(f"    Mean={mean_pct:.3f}%, Std={std_pct:.2f}%, "
              f"Skew={skew:.2f}, Kurt={kurt:.1f}")
        print(f"    Min={min_pct:.1f}%, Max={max_pct:.1f}%, N={n_obs}")
        if gjr_params:
            print(f"    GJR gamma={gjr_params['gamma']:.4f}, "
                  f"t={gjr_params.get('gamma_tstat', 'N/A')}")
        print(f"    Rolling gamma: mean={rolling_info['mean_gamma']:.3f}, "
              f"neg={rolling_info['pct_negative']:.0f}%")

    return results


def run_table3():
    """Task 2: Generate Table 3 cross-asset QLIKE."""
    print("\n" + "=" * 70)
    print("TASK 2: Table 3 — Cross-Asset QLIKE")
    print("=" * 70)

    results = {}

    for ticker in ASSETS_TABLE3:
        print(f"\n--- {ticker} ---")
        prices, returns = load_asset_data(ticker, is_tw=False)
        if returns is None:
            results[ticker] = {'error': 'No data'}
            continue

        r_arr = returns.values.astype(np.float64)
        dates_arr = returns.index

        asset_results = {}

        for oos_label, oos_start, oos_end in [
            ('2023-2024', OOS_PRIMARY_START, OOS_PRIMARY_END),
            ('2025', OOS_VALIDATION_START, OOS_VALIDATION_END),
        ]:
            print(f"  OOS: {oos_label}")

            # GARCH(1,1) OOS
            garch_oos = oos_qlike_expanding(
                r_arr, dates_arr, oos_start, oos_end,
                refit_every=REFIT_EVERY, model='garch')

            # GJR-GARCH(1,1) OOS
            gjr_oos = oos_qlike_expanding(
                r_arr, dates_arr, oos_start, oos_end,
                refit_every=REFIT_EVERY, model='gjr')

            if garch_oos is None or gjr_oos is None:
                print(f"    SKIP: insufficient data for {ticker} {oos_label}")
                asset_results[oos_label] = {'error': 'insufficient data'}
                continue

            garch_qlike = garch_oos['qlike_mean']
            gjr_qlike = gjr_oos['qlike_mean']

            # Delta: (GJR - GARCH) / |GARCH| * 100
            # Negative delta means GJR is better (lower QLIKE)
            delta_pct = (gjr_qlike - garch_qlike) / abs(garch_qlike) * 100

            # DM test: GARCH loss vs GJR loss
            # Negative t → GARCH loss > GJR loss → GJR is better
            dm_t, dm_p = dm_test_hac(
                np.array(garch_oos['qlike_values']),
                np.array(gjr_oos['qlike_values']),
                h=1
            )

            period_result = {
                'garch_qlike': round(garch_qlike, 3),
                'gjr_qlike': round(gjr_qlike, 3),
                'delta_pct': round(delta_pct, 2),
                'dm_tstat': round(dm_t, 3),
                'dm_pvalue': round(dm_p, 4),
                'dm_significant_5pct': dm_p < 0.05,
                'dm_harvey_pass': abs(dm_t) > 3.0,
                'n_oos_garch': garch_oos['n_oos'],
                'n_oos_gjr': gjr_oos['n_oos'],
            }

            asset_results[oos_label] = period_result

            sig = '*' if dm_p < 0.05 else ''
            harvey = ' [Harvey PASS]' if abs(dm_t) > 3.0 else ''
            print(f"    GARCH QLIKE: {garch_qlike:.3f}")
            print(f"    GJR   QLIKE: {gjr_qlike:.3f}")
            print(f"    Delta: {delta_pct:+.2f}%")
            print(f"    DM t={dm_t:.3f}, p={dm_p:.4f}{sig}{harvey}")
            print(f"    N(OOS): GARCH={garch_oos['n_oos']}, GJR={gjr_oos['n_oos']}")

        results[ticker] = asset_results

    return results


def main():
    t0 = time.time()
    print("K902: Paper 1 Descriptive Stats + Cross-Asset QLIKE")
    print(f"Started: {datetime.now(timezone.utc).isoformat()}")

    # Task 1: Table 1
    table1_results = run_table1()

    # Task 2: Table 3
    table3_results = run_table3()

    elapsed = time.time() - t0

    # Assemble final results
    final = {
        'experiment_id': 'K902',
        'title': 'Paper 1 Tables 1 & 3 Supplement (C4+C5 resolution)',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_seconds': round(elapsed, 1),
        'data_source': 'yfinance',
        'methodology': {
            'table1': {
                'period': f'{TABLE1_START} to {TABLE1_END}',
                'assets': [a['ticker'] for a in ASSETS_TABLE1],
                'stats': 'mean, std, skewness, excess kurtosis, min, max, N',
                'gjr_gamma': 'full-sample MLE + numerical Hessian t-stat',
                'rolling_gamma': f'window={ROLLING_GAMMA_WINDOW}, step=quarterly',
            },
            'table3': {
                'oos_primary': f'{OOS_PRIMARY_START} to {OOS_PRIMARY_END}',
                'oos_validation': f'{OOS_VALIDATION_START} to {OOS_VALIDATION_END}',
                'assets': ASSETS_TABLE3,
                'models': ['GARCH(1,1)', 'GJR-GARCH(1,1)'],
                'refit_every': REFIT_EVERY,
                'qlike_formula': 'QLIKE_t = log(h_t) + r²_t / h_t',
                'dm_test': 'Newey-West HAC, Harvey (2016) t>3.0 threshold',
            },
        },
        'references': [
            'Patton (2011) J. Econometrics 160 — QLIKE proxy-robust',
            'Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH',
            'Diebold & Mariano (1995) — predictive accuracy test',
            'Harvey et al. (2016) — t > 3.0 threshold',
        ],
        'table1_descriptive_stats': table1_results,
        'table3_cross_asset_qlike': table3_results,
    }

    # Print summary tables
    print("\n" + "=" * 70)
    print("SUMMARY: Table 1 — Descriptive Statistics")
    print("=" * 70)
    print(f"{'Asset':<10} {'Mean%':>7} {'Std%':>6} {'Skew':>6} {'Kurt':>6} "
          f"{'Min%':>7} {'Max%':>7} {'N':>5} {'γ':>7} {'γ t':>6} {'%neg':>5}")
    print("-" * 85)
    for asset_info in ASSETS_TABLE1:
        name = asset_info['name']
        r = table1_results.get(name, {})
        if 'error' in r:
            print(f"{name:<10} ERROR: {r['error']}")
            continue
        gamma = r.get('gjr_gamma', np.nan)
        gamma_t = r.get('gjr_gamma_tstat', np.nan)
        pct_neg = r.get('rolling_gamma', {}).get('pct_negative', np.nan)
        gamma_str = f"{gamma:+.3f}" if gamma is not None and not np.isnan(gamma) else "N/A"
        gamma_t_str = f"{gamma_t:+.2f}" if gamma_t is not None and not np.isnan(gamma_t) else "N/A"
        pct_neg_str = f"{pct_neg:.0f}%" if pct_neg is not None and not np.isnan(pct_neg) else "N/A"
        print(f"{name:<10} {r['mean_pct']:>7.3f} {r['std_pct']:>6.2f} "
              f"{r['skewness']:>6.2f} {r['kurtosis']:>6.1f} "
              f"{r['min_pct']:>7.1f} {r['max_pct']:>7.1f} {r['n_obs']:>5d} "
              f"{gamma_str:>7} {gamma_t_str:>6} {pct_neg_str:>5}")

    print("\n" + "=" * 70)
    print("SUMMARY: Table 3 — Cross-Asset QLIKE")
    print("=" * 70)
    print(f"{'Asset':<10} {'Period':<12} {'GARCH':>8} {'GJR':>8} "
          f"{'Δ%':>7} {'DM t':>7} {'DM p':>7} {'Sig':>4}")
    print("-" * 70)
    for ticker in ASSETS_TABLE3:
        asset_r = table3_results.get(ticker, {})
        for period in ['2023-2024', '2025']:
            pr = asset_r.get(period, {})
            if 'error' in pr:
                print(f"{ticker:<10} {period:<12} ERROR: {pr.get('error', 'N/A')}")
                continue
            sig = '*' if pr.get('dm_significant_5pct', False) else ''
            harvey = 'H' if pr.get('dm_harvey_pass', False) else ''
            print(f"{ticker:<10} {period:<12} {pr['garch_qlike']:>8.3f} "
                  f"{pr['gjr_qlike']:>8.3f} {pr['delta_pct']:>+7.2f} "
                  f"{pr['dm_tstat']:>7.3f} {pr['dm_pvalue']:>7.4f} {sig+harvey:>4}")

    # Save results
    with open(RESULTS_PATH, 'w') as f:
        json.dump(final, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_PATH}")
    print(f"Elapsed: {elapsed:.1f}s")

    return final


if __name__ == '__main__':
    main()
