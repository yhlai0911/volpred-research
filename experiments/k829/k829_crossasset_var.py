#!/usr/bin/env python3
"""
K829: Cross-Asset VaR Validation
=================================
[提出: 用戶, 執行: Claude]

Validates K825/K824v2 HistSim + Student-t VaR methodology on 4 non-SPY assets:
  QQQ (high-beta equity), GLD (low-vol commodity), BTC-USD (crypto), 0050.TW (Taiwan equity)

Method: GJR-GARCH(1,1) expanding window, refit every 63 days
VaR methods:
  1. Normal VaR (baseline)
  2. Student-t VaR (per-refit df, scale=sqrt((df-2)/df)) — K824v2 Bug 1 fix
  3. HistSim VaR (empirical quantile of standardized residuals)

OOS: 2023-01-01 ~ 2024-12-31
VaR levels: 1%, 5%
Evaluation: Kupiec (1995) + Christoffersen (1998) + Basel traffic light (standard 250-day) + Trinity

Error Log rules applied:
  - 0050.TW: must use clean_tw50_data from volpred.utils
  - Student-t: scale=sqrt((df-2)/df), per-refit df
  - Basel: standard 250-day window (Green 0-4, Yellow 5-9, Red ≥10)
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])

References:
  - K824v2: SPY confirmed HistSim(4/502, Basel Green, Trinity PASS), Student-t(6/502)
  - K804: Cross-asset equity/commodity 3/4 PASS, BTC exception (right-skew)
  - Kupiec (1995), Christoffersen (1998), Basel Committee (1996, 2019)
  - Harvey et al. (2016) — t>3.0 threshold

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
from scipy.stats import norm, t as t_dist, chi2

warnings.filterwarnings('ignore')

# Add project root for volpred.utils
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k829_crossasset_var_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]

ASSETS = {
    'QQQ': {'name': 'Invesco QQQ (Nasdaq-100)', 'start': '2006-01-01'},
    'GLD': {'name': 'SPDR Gold Trust', 'start': '2006-01-01'},
    'BTC-USD': {'name': 'Bitcoin', 'start': '2015-01-01'},
    '0050.TW': {'name': 'Taiwan 50 ETF', 'start': '2006-01-01'},
}


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
    """MLE for Student-t df from unit-variance standardized residuals.
    Uses scale = sqrt((df-2)/df) so fitted distribution has unit variance."""
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
# E. VaR Backtest: Kupiec + Christoffersen + Basel
# ==============================================================

def basel_traffic_light_250(violations_array, n_lookback=250, alpha_var=0.01):
    """Standard Basel II/III traffic light.

    For 1% VaR (standard): Green: 0-4, Yellow: 5-9, Red: >=10 in 250 days.
    For 5% VaR: scale thresholds proportionally (expected=12.5 vs 2.5).
      green_max = floor(4 * alpha/0.01), yellow_max = floor(9 * alpha/0.01)

    Basel Committee (1996, 2019) designed for 1% VaR. We apply proportional
    scaling for other alphas following Christoffersen & Pelletier (2004) approach.
    For shorter windows, additionally scale by N/250.
    """
    v = np.asarray(violations_array, dtype=int)
    n = len(v)
    window = min(n, n_lookback)
    v_window = v[-window:]
    n_viol = int(v_window.sum())

    # Scale thresholds for alpha level
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
        'n_violations': n1,
        'n_total': n,
        'kupiec': {'stat': round(kup_stat, 4), 'p_value': round(kup_p, 4),
                   'pass': bool(kup_p > 0.05)},
        'christoffersen': {'stat': round(cc_stat, 4), 'p_value': round(cc_p, 4),
                           'pass': bool(cc_p > 0.05)},
        'basel_traffic_light': traffic,
        'basel_violations_in_window': n_viol_window,
        'basel_window_size': window_size,
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and traffic == 'green'),
    }


# ==============================================================
# F. Per-asset VaR computation (expanding window OOS)
# ==============================================================

def run_asset_var(ticker, asset_info, verbose=True):
    """Run the full expanding-window VaR experiment for one asset."""
    t_start = time.time()
    name = asset_info['name']
    data_start = asset_info['start']

    if verbose:
        print(f"\n{'='*60}")
        print(f"  Asset: {ticker} ({name})")
        print(f"{'='*60}")

    # 1. Download data
    print(f"  [1] Downloading {ticker}...")
    df = yf.download(ticker, start=data_start, end='2026-01-01', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=['Close'])

    prices = df['Close']
    returns = prices.pct_change().dropna()

    # 0050.TW special handling
    if ticker == '0050.TW':
        print(f"  [*] Applying clean_tw50_data for 0050.TW...")
        prices, returns = clean_tw50_data(prices, returns)
        returns = returns.dropna()

    # Filter extreme returns for all assets (>50% daily = data error)
    extreme = returns.abs() > 0.50
    if extreme.any():
        n_extreme = extreme.sum()
        print(f"  [!] Removed {n_extreme} extreme return(s) (|r| > 50%)")
        returns = returns[~extreme]

    print(f"  Total returns: {len(returns)} ({returns.index[0].date()} ~ {returns.index[-1].date()})")

    # 2. Identify OOS period
    oos_mask = (returns.index >= OOS_START) & (returns.index <= OOS_END)
    oos_returns = returns[oos_mask]
    n_oos = len(oos_returns)
    if n_oos < 50:
        print(f"  [SKIP] Only {n_oos} OOS observations")
        return None

    print(f"  OOS: {n_oos} days ({oos_returns.index[0].date()} ~ {oos_returns.index[-1].date()})")

    # 3. Descriptive stats
    r_oos = oos_returns.values
    from scipy.stats import skew, kurtosis
    stats = {
        'mean': float(np.mean(r_oos)),
        'std': float(np.std(r_oos)),
        'skewness': float(skew(r_oos)),
        'kurtosis': float(kurtosis(r_oos, fisher=True)),
        'min': float(np.min(r_oos)),
        'max': float(np.max(r_oos)),
    }
    print(f"  OOS stats: mean={stats['mean']:.6f}, std={stats['std']:.4f}, "
          f"skew={stats['skewness']:.3f}, kurt={stats['kurtosis']:.2f}")

    # 4. Expanding window with refit
    all_returns = returns.values
    all_dates = returns.index
    oos_start_idx = np.searchsorted(all_dates, pd.Timestamp(OOS_START))
    oos_end_idx = np.searchsorted(all_dates, pd.Timestamp(OOS_END), side='right')

    # Storage for VaR forecasts
    var_forecasts = {alpha: {'normal': [], 'student_t': [], 'histsim': []}
                     for alpha in ALPHA_LEVELS}

    current_params = None
    current_z = None
    current_df = None
    last_refit = -999
    n_refits = 0

    print(f"  [2] Running expanding window OOS forecast...")
    for i in range(oos_start_idx, oos_end_idx):
        day_idx = i - oos_start_idx

        # Refit?
        if day_idx - last_refit >= REFIT_EVERY or current_params is None:
            train_r = all_returns[:i]  # data up to (but not including) day i
            params = fit_gjr(train_r)
            if params is not None:
                current_params = params
                current_z = compute_standardized_residuals(train_r, params)
                current_df = estimate_t_df(current_z)
                n_refits += 1
                last_refit = day_idx

        if current_params is None:
            # Can't forecast yet
            for alpha in ALPHA_LEVELS:
                for m in ['normal', 'student_t', 'histsim']:
                    var_forecasts[alpha][m].append(np.nan)
            continue

        # One-step forecast: σ²_{t+1|t}
        train_r = all_returns[:i]
        sigma2_f = gjr_one_step_forecast(train_r, current_params)
        sigma_f = np.sqrt(sigma2_f)

        # Compute VaR for each alpha and method
        for alpha in ALPHA_LEVELS:
            # M1: Normal VaR
            z_normal = norm.ppf(alpha)
            var_normal = sigma_f * z_normal
            var_forecasts[alpha]['normal'].append(float(var_normal))

            # M2: Student-t VaR (with proper scale)
            scale = np.sqrt((current_df - 2.0) / current_df) if current_df > 2 else 1.0
            z_t = t_dist.ppf(alpha, df=current_df, loc=0.0, scale=scale)
            var_student = sigma_f * z_t
            var_forecasts[alpha]['student_t'].append(float(var_student))

            # M3: HistSim VaR (empirical quantile of standardized residuals)
            z_hist = np.percentile(current_z, alpha * 100)
            var_histsim = sigma_f * z_hist
            var_forecasts[alpha]['histsim'].append(float(var_histsim))

    print(f"  Refits: {n_refits}, OOS forecasts: {len(var_forecasts[0.01]['normal'])}")

    # 5. Backtest each method at each alpha
    results = {
        'ticker': ticker,
        'name': name,
        'n_oos': n_oos,
        'n_refits': n_refits,
        'oos_stats': stats,
        'var_results': {},
    }

    oos_r = oos_returns.values
    method_names = {'normal': 'Normal', 'student_t': 'Student-t', 'histsim': 'HistSim'}

    for alpha in ALPHA_LEVELS:
        alpha_key = f"{alpha:.0%}"
        results['var_results'][alpha_key] = {}

        for method_key, method_name in method_names.items():
            var_arr = np.array(var_forecasts[alpha][method_key])
            # Align: only use non-nan
            valid = np.isfinite(var_arr)
            if valid.sum() < 50:
                results['var_results'][alpha_key][method_name] = {'error': 'insufficient valid forecasts'}
                continue

            bt = var_backtest(oos_r[valid], var_arr[valid], alpha_var=alpha)
            results['var_results'][alpha_key][method_name] = bt

            status = "PASS" if bt['trinity_pass'] else "FAIL"
            print(f"  {alpha_key} {method_name:10s}: {bt['n_violations']}/{bt['n_total']} "
                  f"({bt['violation_rate']:.4f}), Basel={bt['basel_traffic_light']}, "
                  f"Kupiec p={bt['kupiec']['p_value']:.3f}, "
                  f"Christ p={bt['christoffersen']['p_value']:.3f}, "
                  f"Trinity={status}")

    elapsed = time.time() - t_start
    results['elapsed_sec'] = round(elapsed, 1)
    print(f"  Elapsed: {elapsed:.1f}s")

    return results


# ==============================================================
# MAIN
# ==============================================================

def main():
    t0 = time.time()
    print("=" * 70)
    print("K829: Cross-Asset VaR Validation")
    print("  Assets: QQQ, GLD, BTC-USD, 0050.TW")
    print("  Methods: Normal, Student-t (scale-corrected), HistSim")
    print("  OOS: 2023-01-01 ~ 2024-12-31")
    print("  Refit: every 63 trading days")
    print("=" * 70)

    all_results = {}
    for ticker, info in ASSETS.items():
        result = run_asset_var(ticker, info)
        if result is not None:
            all_results[ticker] = result

    # ==============================================================
    # Summary: Trinity results across all assets
    # ==============================================================
    print("\n" + "=" * 70)
    print("SUMMARY: Trinity Pass/Fail across assets")
    print("=" * 70)

    summary_table = {}
    for ticker, res in all_results.items():
        summary_table[ticker] = {}
        for alpha_key in res['var_results']:
            summary_table[ticker][alpha_key] = {}
            for method_name, bt in res['var_results'][alpha_key].items():
                if 'error' in bt:
                    summary_table[ticker][alpha_key][method_name] = 'ERROR'
                else:
                    summary_table[ticker][alpha_key][method_name] = (
                        'PASS' if bt['trinity_pass'] else 'FAIL'
                    )

    # Print summary
    for alpha_key in ['1%', '5%']:
        print(f"\n  === {alpha_key} VaR ===")
        print(f"  {'Asset':<12} {'Normal':<10} {'Student-t':<10} {'HistSim':<10}")
        print(f"  {'-'*42}")
        for ticker in all_results:
            if alpha_key in summary_table[ticker]:
                row = summary_table[ticker][alpha_key]
                print(f"  {ticker:<12} {row.get('Normal','N/A'):<10} "
                      f"{row.get('Student-t','N/A'):<10} "
                      f"{row.get('HistSim','N/A'):<10}")

    # Count PASS rates
    pass_counts = {'Normal': 0, 'Student-t': 0, 'HistSim': 0}
    total_tests = {'Normal': 0, 'Student-t': 0, 'HistSim': 0}
    for ticker in all_results:
        for alpha_key in all_results[ticker]['var_results']:
            for method_name in ['Normal', 'Student-t', 'HistSim']:
                if method_name in summary_table[ticker].get(alpha_key, {}):
                    val = summary_table[ticker][alpha_key][method_name]
                    total_tests[method_name] += 1
                    if val == 'PASS':
                        pass_counts[method_name] += 1

    print(f"\n  === Overall Pass Rates ===")
    for method in ['Normal', 'Student-t', 'HistSim']:
        total = total_tests[method]
        passed = pass_counts[method]
        rate = passed / total if total > 0 else 0
        print(f"  {method:<12}: {passed}/{total} ({rate:.0%})")

    elapsed_total = time.time() - t0
    print(f"\n  Total elapsed: {elapsed_total:.1f}s")

    # ==============================================================
    # Save results
    # ==============================================================
    output = {
        'experiment_id': 'K829',
        'title': 'K829: Cross-Asset VaR Validation (QQQ, GLD, BTC-USD, 0050.TW)',
        'method': 'GJR-GARCH(1,1) expanding window + Normal/Student-t/HistSim VaR',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'data_source': 'yfinance',
        'error_log_rules': [
            '0050.TW: clean_tw50_data applied',
            'Student-t: scale=sqrt((df-2)/df) per-refit',
            'Basel: standard 250-day window',
            'GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])',
        ],
        'references': [
            'K824v2: SPY HistSim(4/502, Trinity PASS), Student-t(6/502)',
            'K804: Cross-asset 3/4 PASS, BTC exception',
            'Kupiec (1995), Christoffersen (1998)',
            'Basel Committee (1996, 2019)',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_total_sec': round(elapsed_total, 1),
        'assets': all_results,
        'summary_trinity': summary_table,
        'pass_rates': {
            method: f"{pass_counts[method]}/{total_tests[method]}"
            for method in ['Normal', 'Student-t', 'HistSim']
        },
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n  Results saved to: {RESULTS_PATH}")
    print("=" * 70)


if __name__ == '__main__':
    main()
