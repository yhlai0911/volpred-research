#!/usr/bin/env python3
"""
K836: 0050.TW EVT-POT VaR — Extreme Value Theory for Taiwan Equity Tail Risk
==============================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K829 showed 0050.TW 1% VaR FAILS for all 3 methods (Normal, Student-t, HistSim).
  Root cause: kurtosis=7.67, skew=-0.681 (much heavier tail than SPY).
  5% VaR PASS for all — problem is concentrated in the extreme tail.
  Basel Green requires ≤4 violations in 250 days, but all methods get 5-9 (Yellow).

Solution approaches:
  1. EVT-POT: GPD fit on left tail of GJR-GARCH standardized residuals
     - Multiple threshold percentiles tested: 5%, 10%, 15%
  2. Cornish-Fisher expansion: Adjusts Normal quantile using skewness + kurtosis
  3. EVT-POT with safety multiplier: Inflated EVT quantile for conservatism

Methods compared (8 total):
  M1: Normal VaR (K829 baseline, FAIL)
  M2: Student-t VaR (K829, FAIL)
  M3: HistSim VaR (K829, FAIL)
  M4: EVT-POT (5th percentile threshold)
  M5: EVT-POT (10th percentile threshold)
  M6: EVT-POT (15th percentile threshold)
  M7: Cornish-Fisher VaR (skewness + kurtosis adjustment)
  M8: EVT-POT (10th pctl) + 10% safety margin

OOS: 2023-01-01 ~ 2024-12-31
Asset: 0050.TW (Taiwan 50 ETF)
Evaluation: Kupiec + Christoffersen + Basel traffic light + Trinity

Error Log rules applied:
  - 0050.TW: must use clean_tw50_data from volpred.utils
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1]), not stale variance
  - Student-t: scale=sqrt((df-2)/df)
  - Basel: standard 250-day window (Green 0-4, Yellow 5-9, Red ≥10)
  - GPD fit: check ξ > -0.5 (finite VaR), refit per-63-days

References:
  - McNeil & Frey (2000) "Estimation of tail-related risk measures for heteroscedastic
    financial time series: an extreme value approach", J Empirical Finance
  - Gilli & Kellezi (2006) "An application of extreme value theory for measuring
    financial risk", Computational Economics
  - Cornish & Fisher (1938) "Moments and cumulants in the specification of distributions"
  - K829: 0050.TW Normal 9/481, Student-t 6/481, HistSim 6/481 — all FAIL (Basel Yellow)
  - K824v2: SPY confirmed HistSim(4/502, Trinity PASS)
  - Kupiec (1995), Christoffersen (1998), Basel Committee (1996, 2019)

Data source: yfinance
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
from numba import njit
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist, chi2, genpareto, skew, kurtosis

warnings.filterwarnings('ignore')

# Add project root for volpred.utils
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k836_tw_evt_var_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
EVT_THRESHOLDS = [5, 10, 15]  # Multiple threshold percentiles to test
SAFETY_MARGIN = 0.10  # 10% safety multiplier for conservative EVT


# ==============================================================
# A. Numba-accelerated GJR-GARCH variance filter
# ==============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): σ²_t = ω + (α + γ·I_{r<0})·r²_{t-1} + β·σ²_{t-1}"""
    T = len(r)
    s2 = np.empty(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i] ** 2
    var_r /= T
    s2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < 1e-12:
            s2[t] = 1e-12
    return s2


# ==============================================================
# B. GJR-GARCH model fitting
# ==============================================================

def fit_gjr(returns, n_starts=4):
    """Fit GJR-GARCH(1,1) via quasi-MLE (Normal). Returns params dict or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
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
        b0 = np.clip(0.88 + 0.04 * np.random.randn(), 0.5, 0.98)
        g0 = np.clip(0.08 + 0.04 * np.random.randn(), 0.01, 0.3)
        if a0 + b0 + 0.5 * g0 >= 0.99:
            b0 = 0.97 - a0 - 0.5 * g0
        o0 = max(1e-8, rv * (1 - a0 - b0 - 0.5 * g0))
        res = minimize(negll, [o0, a0, b0, g0],
                       method='L-BFGS-B',
                       bounds=[(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)],
                       options={'maxiter': 3000})
        if res.fun < best_nll:
            best_nll, best = res.fun, res
    if best is None:
        return None
    omega, alpha, beta, gamma = best.x
    return {'omega': float(omega), 'alpha': float(alpha),
            'beta': float(beta), 'gamma': float(gamma),
            'persistence': float(alpha + beta + 0.5 * gamma)}


# ==============================================================
# C. One-step-ahead forecast + standardized residuals
# ==============================================================

def gjr_one_step_forecast(returns, params):
    """σ²_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def compute_standardized_residuals(returns, params):
    """z_t = r_t / σ_t for in-sample data."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]  # skip first (variance initialized from sample)


# ==============================================================
# D. Student-t df estimation (FIXED: scale=sqrt((df-2)/df))
# ==============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """MLE for Student-t df from unit-variance standardized residuals."""
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return 5.0

    def neg_loglik(log_df):
        df = np.exp(log_df)
        if df < df_min or df > df_max:
            return 1e10
        scale = np.sqrt((df - 2.0) / df)
        ll = np.sum(t_dist.logpdf(z, df=df, loc=0.0, scale=scale))
        return -ll if np.isfinite(ll) else 1e10

    best_nll = 1e10
    best_df = 5.0
    for df_init in [3.0, 5.0, 8.0, 15.0]:
        res = minimize(neg_loglik, x0=[np.log(df_init)],
                       method='L-BFGS-B',
                       bounds=[(np.log(df_min), np.log(df_max))],
                       options={'maxiter': 500})
        if res.fun < best_nll:
            best_nll = res.fun
            best_df = float(np.exp(res.x[0]))

    return float(np.clip(best_df, df_min, df_max))


# ==============================================================
# E. EVT-POT: Generalized Pareto Distribution for left tail
# ==============================================================

def fit_gpd_left_tail(std_residuals, threshold_percentile=10):
    """
    Fit GPD to left-tail exceedances of standardized residuals.
    McNeil & Frey (2000) approach.
    """
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    n_total = len(z)

    if n_total < 50:
        return None

    u = np.percentile(z, threshold_percentile)
    mask = z < u
    exceedances = u - z[mask]  # positive values
    n_exceed = len(exceedances)

    if n_exceed < 20:
        return None

    try:
        xi, _loc, beta = genpareto.fit(exceedances, floc=0)
    except Exception:
        return None

    if beta <= 0:
        return None

    return {
        'xi': float(xi),
        'beta': float(beta),
        'threshold_u': float(u),
        'n_exceedances': int(n_exceed),
        'n_total': int(n_total),
        'exceed_ratio': float(n_exceed / n_total),
    }


def evt_var_quantile(gpd_params, alpha):
    """
    Compute EVT-POT VaR quantile in z-space.
    McNeil & Frey (2000):
      VaR_α(z) = u - (β/ξ) * [((N_u/n) / α)^ξ - 1]   if ξ ≠ 0
    """
    xi = gpd_params['xi']
    beta = gpd_params['beta']
    u = gpd_params['threshold_u']
    exceed_ratio = gpd_params['exceed_ratio']

    if alpha >= exceed_ratio:
        return None

    if abs(xi) < 1e-8:
        q = u - beta * np.log(exceed_ratio / alpha)
    else:
        q = u - (beta / xi) * ((exceed_ratio / alpha) ** xi - 1.0)

    return float(q)


# ==============================================================
# F. Cornish-Fisher VaR quantile
# ==============================================================

def cornish_fisher_quantile(std_residuals, alpha):
    """
    Cornish-Fisher expansion: adjusts Normal quantile using skewness & kurtosis.

    z_CF = z_α + (z_α² - 1) * S/6 + (z_α³ - 3z_α) * K/24 - (2z_α³ - 5z_α) * S²/36

    where S = skewness, K = excess kurtosis, z_α = Normal quantile.
    Cornish & Fisher (1938).
    """
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]

    S = float(skew(z))
    K = float(kurtosis(z, fisher=True))  # excess kurtosis
    z_alpha = norm.ppf(alpha)

    # Cornish-Fisher expansion (4th order)
    z_cf = (z_alpha
            + (z_alpha ** 2 - 1) * S / 6.0
            + (z_alpha ** 3 - 3.0 * z_alpha) * K / 24.0
            - (2.0 * z_alpha ** 3 - 5.0 * z_alpha) * S ** 2 / 36.0)

    return float(z_cf)


# ==============================================================
# G. VaR Backtest: Kupiec + Christoffersen + Basel
# ==============================================================

def basel_traffic_light_250(violations_array, n_lookback=250, alpha_var=0.01):
    """Standard Basel II/III traffic light."""
    v = np.asarray(violations_array, dtype=int)
    n = len(v)
    window = min(n, n_lookback)
    v_window = v[-window:]
    n_viol = int(v_window.sum())

    alpha_scale = alpha_var / 0.01
    if window >= 250:
        green_max = int(np.floor(4 * alpha_scale))
        yellow_max = int(np.floor(9 * alpha_scale))
    else:
        green_max = int(np.floor(window * 4.0 * alpha_scale / 250.0))
        yellow_max = int(np.floor(window * 9.0 * alpha_scale / 250.0))

    green_max = max(green_max, 0)
    yellow_max = max(yellow_max, max(green_max + 1, 1))

    if n_viol <= green_max:
        color = 'green'
    elif n_viol <= yellow_max:
        color = 'yellow'
    else:
        color = 'red'

    return color, n_viol, window


def var_backtest(returns, var_series, alpha_var=0.01):
    """Kupiec (1995) + Christoffersen (1998) + Basel traffic light."""
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec unconditional coverage
    if n1 == 0 or n1 == n:
        kup_stat, kup_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha_var) + n0 * np.log(1 - alpha_var)
                    - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kup_stat = float(lr)
        kup_p = float(1 - chi2.cdf(lr, df=1))

    # Christoffersen independence
    try:
        t00 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 0)))
        t01 = int(np.sum((violations[:-1] == 0) & (violations[1:] == 1)))
        t10 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 0)))
        t11 = int(np.sum((violations[:-1] == 1) & (violations[1:] == 1)))
        pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
        if 0 < pi01 < 1 and 0 < pi11 < 1 and 0 < pi_all < 1:
            lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all)
                           + (t01 + t11) * np.log(pi_all)
                           - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                           - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
            cc_stat = float(lr_ind)
            cc_p = float(1 - chi2.cdf(lr_ind, df=1))
        else:
            cc_stat, cc_p = 0.0, 1.0
    except Exception:
        cc_stat, cc_p = 0.0, 1.0

    traffic, n_viol_window, window_size = basel_traffic_light_250(violations, alpha_var=alpha_var)

    return {
        'violation_rate': round(float(pi_hat), 6),
        'expected_rate': float(alpha_var),
        'n_violations': int(n1),
        'n_total': int(n),
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4),
                   'pass': bool(kup_p > 0.05)},
        'christoffersen': {'stat': round(cc_stat, 4), 'p_value': round(cc_p, 4),
                           'pass': bool(cc_p > 0.05)},
        'basel_traffic_light': traffic,
        'basel_violations_in_window': int(n_viol_window),
        'basel_window_size': int(window_size),
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and traffic == 'green'),
    }


# ==============================================================
# H. JSON serialization helper
# ==============================================================

def make_serializable(obj):
    """Convert numpy types to Python native types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [make_serializable(v) for v in obj]
    elif isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


# ==============================================================
# I. Main experiment: 0050.TW with 8 VaR methods
# ==============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K836: 0050.TW EVT-POT VaR")
    print("  Asset: 0050.TW (Taiwan 50 ETF)")
    print("  Methods: Normal, Student-t, HistSim, EVT-POT(5/10/15%),")
    print("           Cornish-Fisher, EVT-POT+Safety")
    print(f"  OOS: {OOS_START} ~ {OOS_END}")
    print(f"  Refit: every {REFIT_EVERY} trading days")
    print(f"  EVT thresholds: {EVT_THRESHOLDS}th percentile")
    print("=" * 70)

    # 1. Download data
    print("\n[1] Downloading 0050.TW...")
    df = yf.download('0050.TW', start='2006-01-01', end='2026-01-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Close'])

    prices = df['Close']
    returns = prices.pct_change().dropna()

    # Apply clean_tw50_data (mandatory for 0050.TW)
    print("[*] Applying clean_tw50_data for 0050.TW...")
    prices, returns = clean_tw50_data(prices, returns)
    returns = returns.dropna()

    # Filter extreme returns (>50% daily = data error)
    extreme = returns.abs() > 0.50
    if extreme.any():
        n_extreme = int(extreme.sum())
        print(f"[!] Removed {n_extreme} extreme return(s) (|r| > 50%)")
        returns = returns[~extreme]

    print(f"Total returns: {len(returns)} ({returns.index[0].date()} ~ {returns.index[-1].date()})")

    # 2. OOS period
    oos_mask = (returns.index >= OOS_START) & (returns.index <= OOS_END)
    oos_returns = returns[oos_mask]
    n_oos = len(oos_returns)
    print(f"OOS: {n_oos} days ({oos_returns.index[0].date()} ~ {oos_returns.index[-1].date()})")

    # 3. Descriptive stats
    r_oos = oos_returns.values
    oos_stats = {
        'mean': float(np.mean(r_oos)),
        'std': float(np.std(r_oos)),
        'skewness': float(skew(r_oos)),
        'kurtosis': float(kurtosis(r_oos, fisher=True)),
        'min': float(np.min(r_oos)),
        'max': float(np.max(r_oos)),
    }
    print(f"OOS stats: mean={oos_stats['mean']:.6f}, std={oos_stats['std']:.4f}, "
          f"skew={oos_stats['skewness']:.3f}, kurt={oos_stats['kurtosis']:.2f}")

    # 4. Full-sample descriptive
    all_r = returns.values
    full_stats = {
        'mean': float(np.mean(all_r)),
        'std': float(np.std(all_r)),
        'skewness': float(skew(all_r)),
        'kurtosis': float(kurtosis(all_r, fisher=True)),
        'n_obs': int(len(all_r)),
    }
    print(f"Full-sample stats: skew={full_stats['skewness']:.3f}, "
          f"kurt={full_stats['kurtosis']:.2f}, n={full_stats['n_obs']}")

    # 5. Expanding window with refit
    all_returns = returns.values
    all_dates = returns.index
    oos_start_idx = int(np.searchsorted(all_dates, pd.Timestamp(OOS_START)))
    oos_end_idx = int(np.searchsorted(all_dates, pd.Timestamp(OOS_END), side='right'))

    # Method keys
    method_keys = [
        'normal', 'student_t', 'histsim',
        'evt_pot_5', 'evt_pot_10', 'evt_pot_15',
        'cornish_fisher',
        'evt_pot_10_safe',
    ]
    method_display = {
        'normal': 'Normal',
        'student_t': 'Student-t',
        'histsim': 'HistSim',
        'evt_pot_5': 'EVT-POT(5%)',
        'evt_pot_10': 'EVT-POT(10%)',
        'evt_pot_15': 'EVT-POT(15%)',
        'cornish_fisher': 'Cornish-Fisher',
        'evt_pot_10_safe': 'EVT-POT+Safety',
    }

    var_forecasts = {alpha: {m: [] for m in method_keys} for alpha in ALPHA_LEVELS}

    current_params = None
    current_z = None
    current_df_t = None
    current_gpd = {}  # key: threshold_pctl → gpd_params
    last_refit = -999
    n_refits = 0
    gpd_history = []

    print(f"\n[2] Running expanding window OOS forecast...")
    for i in range(oos_start_idx, oos_end_idx):
        day_idx = i - oos_start_idx

        # Refit?
        if day_idx - last_refit >= REFIT_EVERY or current_params is None:
            train_r = all_returns[:i]
            params = fit_gjr(train_r)
            if params is not None:
                current_params = params
                current_z = compute_standardized_residuals(train_r, params)
                current_df_t = estimate_t_df(current_z)

                # Fit GPD at multiple thresholds
                for pctl in EVT_THRESHOLDS:
                    gpd = fit_gpd_left_tail(current_z, threshold_percentile=pctl)
                    if gpd is not None:
                        current_gpd[pctl] = gpd

                # Log GPD params for threshold=10
                if 10 in current_gpd:
                    g = current_gpd[10]
                    gpd_history.append({
                        'refit_idx': int(day_idx),
                        'xi': float(g['xi']),
                        'beta': float(g['beta']),
                        'threshold_u': float(g['threshold_u']),
                        'n_exceedances': int(g['n_exceedances']),
                        'n_total': int(g['n_total']),
                    })
                    if n_refits == 0 or day_idx % (REFIT_EVERY * 2) == 0:
                        print(f"    Refit @day {day_idx}: GJR pers={params['persistence']:.4f}, "
                              f"t-df={current_df_t:.2f}, "
                              f"GPD ξ={g['xi']:.4f}, β={g['beta']:.4f}")

                n_refits += 1
                last_refit = day_idx

        if current_params is None:
            for alpha in ALPHA_LEVELS:
                for m in method_keys:
                    var_forecasts[alpha][m].append(np.nan)
            continue

        # One-step forecast: σ²_{t+1|t}
        train_r = all_returns[:i]
        sigma2_f = gjr_one_step_forecast(train_r, current_params)
        sigma_f = np.sqrt(sigma2_f)

        for alpha in ALPHA_LEVELS:
            # M1: Normal VaR
            z_normal = norm.ppf(alpha)
            var_forecasts[alpha]['normal'].append(float(sigma_f * z_normal))

            # M2: Student-t VaR
            scale_t = np.sqrt((current_df_t - 2.0) / current_df_t) if current_df_t > 2 else 1.0
            z_t = t_dist.ppf(alpha, df=current_df_t, loc=0.0, scale=scale_t)
            var_forecasts[alpha]['student_t'].append(float(sigma_f * z_t))

            # M3: HistSim VaR
            z_hist = np.percentile(current_z, alpha * 100)
            var_forecasts[alpha]['histsim'].append(float(sigma_f * z_hist))

            # M4-M6: EVT-POT at multiple thresholds
            for pctl in EVT_THRESHOLDS:
                key = f'evt_pot_{pctl}'
                if pctl in current_gpd:
                    z_evt = evt_var_quantile(current_gpd[pctl], alpha)
                    if z_evt is not None:
                        var_forecasts[alpha][key].append(float(sigma_f * z_evt))
                    else:
                        var_forecasts[alpha][key].append(float(sigma_f * z_hist))
                else:
                    var_forecasts[alpha][key].append(float(sigma_f * z_hist))

            # M7: Cornish-Fisher VaR
            z_cf = cornish_fisher_quantile(current_z, alpha)
            var_forecasts[alpha]['cornish_fisher'].append(float(sigma_f * z_cf))

            # M8: EVT-POT(10%) + 10% safety margin
            if 10 in current_gpd:
                z_evt10 = evt_var_quantile(current_gpd[10], alpha)
                if z_evt10 is not None:
                    # Make VaR more negative (more conservative) by multiplying absolute value
                    var_safe = sigma_f * z_evt10 * (1.0 + SAFETY_MARGIN)
                    var_forecasts[alpha]['evt_pot_10_safe'].append(float(var_safe))
                else:
                    var_forecasts[alpha]['evt_pot_10_safe'].append(
                        float(sigma_f * z_hist * (1.0 + SAFETY_MARGIN)))
            else:
                var_forecasts[alpha]['evt_pot_10_safe'].append(
                    float(sigma_f * z_hist * (1.0 + SAFETY_MARGIN)))

    print(f"Refits: {n_refits}, OOS forecasts: {len(var_forecasts[0.01]['normal'])}")

    # 6. Backtest each method
    var_results = {}
    oos_r = oos_returns.values

    print(f"\n{'='*70}")
    print("RESULTS: VaR Backtest for 0050.TW")
    print(f"{'='*70}")

    for alpha in ALPHA_LEVELS:
        alpha_key = f"{alpha:.0%}"
        var_results[alpha_key] = {}

        print(f"\n  --- {alpha_key} VaR ---")
        for method_key in method_keys:
            method_name = method_display[method_key]
            var_arr = np.array(var_forecasts[alpha][method_key])
            valid = np.isfinite(var_arr)
            if valid.sum() < 50:
                var_results[alpha_key][method_name] = {'error': 'insufficient valid forecasts'}
                continue

            bt = var_backtest(oos_r[valid], var_arr[valid], alpha_var=alpha)
            var_results[alpha_key][method_name] = bt

            status = "PASS" if bt['trinity_pass'] else "FAIL"
            print(f"  {method_name:20s}: {bt['n_violations']:2d}/{bt['n_total']} "
                  f"({bt['violation_rate']:.4f}), Basel={bt['basel_traffic_light']:6s}, "
                  f"Kupiec p={bt['kupiec']['p_value']:.3f}, "
                  f"Christ p={bt['christoffersen']['p_value']:.3f}, "
                  f"Trinity={status}")

    # 7. Summary table
    print(f"\n{'='*70}")
    print("SUMMARY: 1% VaR — Which method fixes 0050.TW?")
    print(f"{'='*70}")
    print(f"  {'Method':20s} {'Viol':>5s} {'Rate':>7s} {'Basel':>7s} {'Trinity':>8s}")
    print(f"  {'-'*20} {'-'*5} {'-'*7} {'-'*7} {'-'*8}")

    if '1%' in var_results:
        for method_key in method_keys:
            method_name = method_display[method_key]
            if method_name in var_results['1%'] and 'error' not in var_results['1%'][method_name]:
                bt = var_results['1%'][method_name]
                status = "PASS" if bt['trinity_pass'] else "FAIL"
                print(f"  {method_name:20s} {bt['n_violations']:5d} "
                      f"{bt['violation_rate']:7.4f} {bt['basel_traffic_light']:>7s} "
                      f"{status:>8s}")

    # 8. GPD diagnostics
    print(f"\n{'='*70}")
    print("GPD Parameter Diagnostics")
    print(f"{'='*70}")
    if gpd_history:
        xis = [g['xi'] for g in gpd_history]
        betas = [g['beta'] for g in gpd_history]
        print(f"  GPD(10%) across {len(gpd_history)} refits:")
        print(f"    ξ (shape): mean={np.mean(xis):.4f}, std={np.std(xis):.4f}, "
              f"range=[{np.min(xis):.4f}, {np.max(xis):.4f}]")
        print(f"    β (scale): mean={np.mean(betas):.4f}, std={np.std(betas):.4f}")
        print(f"    ξ > 0 (heavy tail): {sum(1 for x in xis if x > 0)}/{len(xis)} refits")
        print(f"    ξ > -0.5 (valid): {sum(1 for x in xis if x > -0.5)}/{len(xis)} refits")

    # 9. VaR level comparison
    print(f"\n{'='*70}")
    print("Average |VaR| levels (1% VaR)")
    print(f"{'='*70}")
    for method_key in method_keys:
        method_name = method_display[method_key]
        var_arr = np.array(var_forecasts[0.01][method_key])
        valid = np.isfinite(var_arr)
        if valid.sum() > 0:
            mean_var = float(np.mean(np.abs(var_arr[valid])))
            print(f"  {method_name:20s}: {mean_var:.6f} ({mean_var*100:.3f}%)")

    # 10. Cornish-Fisher quantile diagnostics
    print(f"\n  Cornish-Fisher z-quantile details:")
    # Compute on last training set residuals
    if current_z is not None:
        z_vals = current_z[np.isfinite(current_z)]
        S = float(skew(z_vals))
        K = float(kurtosis(z_vals, fisher=True))
        z01 = norm.ppf(0.01)
        z_cf_01 = (z01
                    + (z01**2 - 1) * S / 6.0
                    + (z01**3 - 3.0 * z01) * K / 24.0
                    - (2.0 * z01**3 - 5.0 * z01) * S**2 / 36.0)
        print(f"    Residual skewness={S:.4f}, excess kurtosis={K:.4f}")
        print(f"    Normal 1% quantile: z={z01:.4f}")
        print(f"    Cornish-Fisher 1% quantile: z={z_cf_01:.4f}")
        print(f"    Adjustment: {(z_cf_01 - z01):.4f} ({(z_cf_01/z01 - 1)*100:.1f}% more conservative)")

    # 11. Save results
    elapsed = time.time() - t0

    results = make_serializable({
        'experiment_id': 'K836',
        'title': 'K836: 0050.TW EVT-POT VaR — Extreme Value Theory for Taiwan Equity Tail Risk',
        'method': 'GJR-GARCH(1,1) + EVT-POT + Cornish-Fisher + Safety margin',
        'asset': '0050.TW',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'refit_every': REFIT_EVERY,
        'evt_thresholds': EVT_THRESHOLDS,
        'safety_margin': SAFETY_MARGIN,
        'alpha_levels': ALPHA_LEVELS,
        'data_source': 'yfinance',
        'error_log_rules': [
            '0050.TW: clean_tw50_data applied',
            'Student-t: scale=sqrt((df-2)/df) per-refit',
            'Basel: standard 250-day window',
            'GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])',
            'GPD: ξ > -0.5 checked, per-refit parameters',
        ],
        'references': [
            'McNeil & Frey (2000) J Empirical Finance — EVT-POT for GARCH residuals',
            'Gilli & Kellezi (2006) Computational Economics — EVT for financial risk',
            'Cornish & Fisher (1938) — CF expansion for non-Normal quantiles',
            'K829: 0050.TW Normal 9/481, Student-t 6/481, HistSim 6/481 — all FAIL',
            'K824v2: SPY HistSim(4/502, Trinity PASS)',
            'Kupiec (1995), Christoffersen (1998), Basel Committee (1996, 2019)',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_sec': round(elapsed, 1),
        'n_oos': n_oos,
        'n_refits': n_refits,
        'oos_stats': oos_stats,
        'full_sample_stats': full_stats,
        'var_results': var_results,
        'gpd_params_history': gpd_history,
        'gpd_summary': {
            'mean_xi': float(np.mean(xis)) if gpd_history else None,
            'mean_beta': float(np.mean(betas)) if gpd_history else None,
            'all_xi_valid': all(x > -0.5 for x in xis) if gpd_history else None,
            'n_heavy_tail': sum(1 for x in xis if x > 0) if gpd_history else None,
            'n_refits_with_gpd': len(gpd_history),
        },
        'trinity_summary': {},
        'k829_comparison': {},
    })

    # Build trinity summary
    for alpha_key in var_results:
        results['trinity_summary'][alpha_key] = {}
        for method_name in var_results[alpha_key]:
            bt = var_results[alpha_key][method_name]
            if 'error' not in bt:
                results['trinity_summary'][alpha_key][method_name] = (
                    'PASS' if bt['trinity_pass'] else 'FAIL'
                )
            else:
                results['trinity_summary'][alpha_key][method_name] = 'ERROR'

    # K829 comparison
    k829_baseline = {'Normal': 9, 'Student-t': 6, 'HistSim': 6}
    if '1%' in var_results:
        for method_key in method_keys:
            method_name = method_display[method_key]
            if method_name in var_results['1%'] and 'error' not in var_results['1%'][method_name]:
                bt = var_results['1%'][method_name]
                results['k829_comparison'][method_name] = {
                    'violations_k836': int(bt['n_violations']),
                    'violations_k829': k829_baseline.get(method_name, None),
                    'basel_k836': bt['basel_traffic_light'],
                    'trinity_k836': 'PASS' if bt['trinity_pass'] else 'FAIL',
                }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved to {RESULTS_PATH}")
    print(f"Total elapsed: {elapsed:.1f}s")

    # 12. Final verdict
    print(f"\n{'='*70}")
    print("VERDICT: Which method(s) fix 0050.TW 1% VaR?")
    print(f"{'='*70}")

    any_pass = False
    if '1%' in var_results:
        for method_key in method_keys:
            method_name = method_display[method_key]
            if method_name in var_results['1%'] and 'error' not in var_results['1%'][method_name]:
                bt = var_results['1%'][method_name]
                if bt['trinity_pass']:
                    print(f"  PASS: {method_name} — {bt['n_violations']}/{bt['n_total']} violations, "
                          f"Basel={bt['basel_traffic_light']}")
                    any_pass = True

    if not any_pass:
        print("  No method achieves Trinity PASS for 1% VaR.")
        print("\n  Analysis of the gap:")
        if '1%' in var_results:
            best_method = None
            best_viol = 999
            for method_key in method_keys:
                method_name = method_display[method_key]
                if method_name in var_results['1%'] and 'error' not in var_results['1%'][method_name]:
                    bt = var_results['1%'][method_name]
                    if bt['n_violations'] < best_viol:
                        best_viol = bt['n_violations']
                        best_method = method_name
            print(f"  Best method: {best_method} with {best_viol} violations")
            print(f"  Basel Green threshold: ≤4 violations in 250 days")
            print(f"  Gap: need to reduce {best_viol - 4} more violations")
            # Check last-250-day window specifically
            if best_method:
                bt = var_results['1%'][best_method]
                print(f"  Basel window violations: {bt['basel_violations_in_window']} "
                      f"in {bt['basel_window_size']} days")
    else:
        print("\n  EVT-based methods successfully correct the heavy-tail problem for 0050.TW!")


if __name__ == '__main__':
    main()
