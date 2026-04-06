"""
K938: Yang-Zhang CARR Cross-Asset Validation
Validate K935 finding (YZ CARR beats Parkinson ~8% on SPY) across 4 asset types.

Assets:
  1. SPY  - S&P 500 ETF (baseline, reproduce K935)
  2. GLD  - Gold ETF (24h trading, small overnight gap)
  3. QQQ  - Nasdaq 100 ETF (tech-heavy, high vol)
  4. 0050.TW - Taiwan Top 50 ETF (large US-driven gap)

Hypotheses:
  H1: Gap ratio (Var(overnight)/Var(total)) predicts YZ improvement magnitude
  H2: 0050.TW shows largest YZ improvement (US gap influence)
  H3: GLD shows smallest YZ improvement (near 24h trading)

Models (per asset):
  - GARCH(1,1)
  - GJR(1,1,1) via arch package
  - CARR_Parkinson(1,1) (custom MLE)
  - CARR_YZ(1,1) (Yang-Zhang range, custom MLE)

Evaluation:
  - QLIKE on r^2 (Patton 2011 proxy-robust)
  - Spearman rank correlation
  - DM test (Harvey |t| > 3.0)
  - Gap ratio analysis

References:
  Parkinson (1980) JoB
  Yang & Zhang (2000) JoB
  Chou (2005) JFE "Forecasting Financial Volatilities with Extreme Values"
  Patton (2011) J. Econometrics 160

Data source: yfinance (OHLC daily)
OOS: 2016-01-01 ~ 2025-12-31
Window: 2000 (500 for 0050.TW if data insufficient)
Refit: every 21 trading days

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import json
import warnings
import os
import sys
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from scipy.optimize import minimize
from scipy import stats

np.random.seed(42)
warnings.filterwarnings('ignore')

# Add project root for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, PROJECT_ROOT)

from volpred.stats.model_evaluation import qlike, qlike_pointwise, dm_test

import yfinance as yf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. HELPER FUNCTIONS
# ============================================================

def compute_range_estimators(df):
    """Compute Parkinson and Yang-Zhang range estimators from OHLC data.
    Returns DataFrame with added columns."""
    df = df.copy()

    # Log prices
    df['log_H'] = np.log(df['High'])
    df['log_L'] = np.log(df['Low'])
    df['log_O'] = np.log(df['Open'])
    df['log_C'] = np.log(df['Close'])

    # Returns
    df['log_return'] = df['log_C'] - df['log_C'].shift(1)
    df['r2'] = df['log_return'] ** 2

    # Overnight return: log(Open_t / Close_{t-1})
    df['overnight_return'] = df['log_O'] - df['log_C'].shift(1)

    # --- Parkinson (1980) ---
    # sigma^2_P = (log(H/L))^2 / (4*ln2)
    df['range_parkinson'] = (df['log_H'] - df['log_L'])**2 / (4 * np.log(2))

    # --- Rogers-Satchell (1991) ---
    # sigma^2_RS = (H-C)(H-O) + (L-C)(L-O)
    df['range_rs'] = ((df['log_H'] - df['log_C']) * (df['log_H'] - df['log_O'])
                     + (df['log_L'] - df['log_C']) * (df['log_L'] - df['log_O']))

    # --- Yang-Zhang (2000) ---
    # Full formula: sigma^2_YZ = overnight^2 + k * open_var + (1-k) * RS
    df['overnight_sq'] = df['overnight_return']**2
    k_yz = 0.34 / (1.34 + 2.0)  # asymptotic k
    df['open_var'] = ((df['log_H'] - df['log_O'])**2 + (df['log_L'] - df['log_O'])**2)
    df['range_yz'] = df['overnight_sq'] + k_yz * df['open_var'] + (1 - k_yz) * df['range_rs']

    return df


def carr_fit(ranges, max_iter=500):
    """Fit CARR(1,1) with Exponential innovation.
    Range_t = lambda_t * epsilon_t, epsilon_t ~ Exp(1)
    lambda_t = omega + alpha * Range_{t-1} + beta * lambda_{t-1}
    Log-likelihood: sum(-log(lambda_t) - Range_t / lambda_t)
    """
    T = len(ranges)
    mean_r = np.mean(ranges)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        lam = np.zeros(T)
        lam[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r
        for t in range(1, T):
            lam[t] = omega + alpha * ranges[t - 1] + beta * lam[t - 1]
            if lam[t] <= 1e-10:
                lam[t] = 1e-10
        ll = -np.log(lam) - ranges / lam
        return -np.sum(ll[10:])

    omega0 = mean_r * 0.05
    x0 = [omega0, 0.10, 0.85]
    bounds = [(1e-8, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, b0 in [(0.05, 0.90), (0.15, 0.80), (0.08, 0.88), (0.20, 0.70)]:
            x0_alt = [mean_r * 0.05, a0, b0]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success,
            'loglik': -result.fun}


def carr_forecast_oos(params, ranges):
    """One-step-ahead CARR forecast (recursive). Returns T forecasts."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(ranges)
    lam = np.zeros(T + 1)
    lam[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        lam[t + 1] = omega + alpha * ranges[t] + beta * lam[t]
        if lam[t + 1] <= 1e-10:
            lam[t + 1] = 1e-10
    return lam[1:]  # forecast for t=1,...,T (uses info up to t-1)


def garch_fit(returns, max_iter=500):
    """Fit GARCH(1,1) via MLE with Normal innovations."""
    T = len(returns)
    r = returns.copy()
    mean_r2 = np.mean(r ** 2)

    def neg_loglik(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.9999:
            return 1e10
        h = np.zeros(T)
        h[0] = omega / (1 - alpha - beta) if (alpha + beta) < 1 else mean_r2
        for t in range(1, T):
            h[t] = omega + alpha * r[t - 1] ** 2 + beta * h[t - 1]
            if h[t] <= 1e-10:
                h[t] = 1e-10
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    omega0 = mean_r2 * 0.05
    x0 = [omega0, 0.08, 0.88]
    bounds = [(1e-10, None), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, b0 in [(0.05, 0.92), (0.12, 0.85), (0.03, 0.95)]:
            x0_alt = [mean_r2 * 0.05, a0, b0]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    omega, alpha, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta, 'converged': result.success,
            'loglik': -result.fun}


def garch_forecast_oos(params, returns):
    """One-step-ahead GARCH forecast (recursive)."""
    omega, alpha, beta = params['omega'], params['alpha'], params['beta']
    T = len(returns)
    h = np.zeros(T + 1)
    h[0] = omega / max(1 - alpha - beta, 0.01)
    for t in range(T):
        h[t + 1] = omega + alpha * returns[t] ** 2 + beta * h[t]
        if h[t + 1] <= 1e-10:
            h[t + 1] = 1e-10
    return h[1:]


def gjr_fit(returns, max_iter=500):
    """Fit GJR-GARCH(1,1,1) via MLE with Normal innovations."""
    T = len(returns)
    r = returns.copy()
    mean_r2 = np.mean(r ** 2)

    def neg_loglik(params):
        omega, alpha, gamma, beta = params
        if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
            return 1e10
        if (alpha + 0.5 * gamma + beta) >= 0.9999:
            return 1e10
        h = np.zeros(T)
        h[0] = omega / (1 - alpha - 0.5 * gamma - beta) if (alpha + 0.5 * gamma + beta) < 1 else mean_r2
        for t in range(1, T):
            h[t] = omega + alpha * r[t-1]**2 + gamma * r[t-1]**2 * (r[t-1] < 0) + beta * h[t-1]
            if h[t] <= 1e-10:
                h[t] = 1e-10
        ll = -0.5 * (np.log(2 * np.pi) + np.log(h) + r ** 2 / h)
        return -np.sum(ll[10:])

    omega0 = mean_r2 * 0.05
    x0 = [omega0, 0.03, 0.10, 0.88]
    bounds = [(1e-10, None), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.9999)]
    result = minimize(neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                      options={'maxiter': max_iter, 'ftol': 1e-12})

    if not result.success:
        for a0, g0, b0 in [(0.02, 0.15, 0.85), (0.05, 0.08, 0.88), (0.01, 0.20, 0.80)]:
            x0_alt = [mean_r2 * 0.05, a0, g0, b0]
            result_alt = minimize(neg_loglik, x0_alt, method='L-BFGS-B', bounds=bounds,
                                  options={'maxiter': max_iter, 'ftol': 1e-12})
            if result_alt.success and result_alt.fun < result.fun:
                result = result_alt

    omega, alpha, gamma, beta = result.x
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + 0.5 * gamma + beta, 'converged': result.success,
            'loglik': -result.fun}


def gjr_forecast_oos(params, returns):
    """One-step-ahead GJR forecast (recursive)."""
    omega, alpha, gamma, beta = params['omega'], params['alpha'], params['gamma'], params['beta']
    T = len(returns)
    h = np.zeros(T + 1)
    h[0] = omega / max(1 - alpha - 0.5 * gamma - beta, 0.01)
    for t in range(T):
        h[t + 1] = omega + alpha * returns[t]**2 + gamma * returns[t]**2 * (returns[t] < 0) + beta * h[t]
        if h[t + 1] <= 1e-10:
            h[t + 1] = 1e-10
    return h[1:]


def run_oos_for_asset(df, oos_start, window, refit_every=21):
    """Run OOS forecasting for all 4 models on one asset.

    Returns dict with forecast arrays aligned to OOS period.
    """
    oos_mask = df.index >= oos_start
    oos_idx = df.index[oos_mask]
    n_oos = oos_mask.sum()

    if n_oos < 100:
        print(f"  WARNING: Only {n_oos} OOS observations, need >= 100")
        return None

    returns = df['log_return'].values
    r2 = df['r2'].values
    range_p = df['range_parkinson'].values
    range_yz = df['range_yz'].values

    # Find the index of oos_start
    oos_start_idx = np.where(oos_mask)[0][0]

    # Ensure enough training data
    actual_window = min(window, oos_start_idx)
    if actual_window < 250:
        print(f"  WARNING: Training window only {actual_window} days, need >= 250")
        return None

    print(f"  OOS period: {oos_idx[0].strftime('%Y-%m-%d')} ~ {oos_idx[-1].strftime('%Y-%m-%d')} ({n_oos} days)")
    print(f"  Training window: {actual_window} days")

    # Allocate forecast arrays
    fc_garch = np.zeros(n_oos)
    fc_gjr = np.zeros(n_oos)
    fc_carr_p = np.zeros(n_oos)
    fc_carr_yz = np.zeros(n_oos)

    # Rolling OOS with periodic refit
    last_refit = -refit_every  # Force refit at start
    params_garch = None
    params_gjr = None
    params_carr_p = None
    params_carr_yz = None

    for i in range(n_oos):
        t = oos_start_idx + i  # Global index

        # Refit if needed
        if i - last_refit >= refit_every or params_garch is None:
            train_start = max(0, t - actual_window)
            train_returns = returns[train_start:t]
            train_range_p = range_p[train_start:t]
            train_range_yz = range_yz[train_start:t]

            params_garch = garch_fit(train_returns)
            params_gjr = gjr_fit(train_returns)
            params_carr_p = carr_fit(train_range_p)
            params_carr_yz = carr_fit(train_range_yz)
            last_refit = i

        # One-step-ahead forecast using recursive formula
        if i == 0 or (i - last_refit == 0 and i > 0):
            # After refit: generate full forecast series from train data
            fc_series_garch = garch_forecast_oos(params_garch, returns[max(0, t - actual_window):t])
            fc_series_gjr = gjr_forecast_oos(params_gjr, returns[max(0, t - actual_window):t])
            fc_series_carr_p = carr_forecast_oos(params_carr_p, range_p[max(0, t - actual_window):t])
            fc_series_carr_yz = carr_forecast_oos(params_carr_yz, range_yz[max(0, t - actual_window):t])
            # The last element of each series is the forecast for day t
            fc_garch[i] = fc_series_garch[-1]
            fc_gjr[i] = fc_series_gjr[-1]
            fc_carr_p[i] = fc_series_carr_p[-1]
            fc_carr_yz[i] = fc_series_carr_yz[-1]
        else:
            # Between refits: recursive one-step update
            # GARCH: h[t+1] = omega + alpha * r[t]^2 + beta * h[t]
            fc_garch[i] = (params_garch['omega'] +
                          params_garch['alpha'] * returns[t-1]**2 +
                          params_garch['beta'] * fc_garch[i-1])
            fc_gjr[i] = (params_gjr['omega'] +
                        params_gjr['alpha'] * returns[t-1]**2 +
                        params_gjr['gamma'] * returns[t-1]**2 * (returns[t-1] < 0) +
                        params_gjr['beta'] * fc_gjr[i-1])
            fc_carr_p[i] = (params_carr_p['omega'] +
                           params_carr_p['alpha'] * range_p[t-1] +
                           params_carr_p['beta'] * fc_carr_p[i-1])
            fc_carr_yz[i] = (params_carr_yz['omega'] +
                            params_carr_yz['alpha'] * range_yz[t-1] +
                            params_carr_yz['beta'] * fc_carr_yz[i-1])

        # Floor
        fc_garch[i] = max(fc_garch[i], 1e-10)
        fc_gjr[i] = max(fc_gjr[i], 1e-10)
        fc_carr_p[i] = max(fc_carr_p[i], 1e-10)
        fc_carr_yz[i] = max(fc_carr_yz[i], 1e-10)

    actual_r2 = r2[oos_start_idx:oos_start_idx + n_oos]

    return {
        'actual_r2': actual_r2,
        'fc_garch': fc_garch,
        'fc_gjr': fc_gjr,
        'fc_carr_p': fc_carr_p,
        'fc_carr_yz': fc_carr_yz,
        'oos_dates': oos_idx,
        'n_oos': n_oos,
        'params_garch': params_garch,
        'params_gjr': params_gjr,
        'params_carr_p': params_carr_p,
        'params_carr_yz': params_carr_yz,
    }


def evaluate_forecasts(results):
    """Compute QLIKE, Spearman correlation, and DM tests."""
    actual = results['actual_r2']
    models = {
        'GARCH': results['fc_garch'],
        'GJR': results['fc_gjr'],
        'CARR_Parkinson': results['fc_carr_p'],
        'CARR_YZ': results['fc_carr_yz'],
    }

    evals = {}
    for name, fc in models.items():
        q = qlike(actual, fc)
        rho, p_rho = stats.spearmanr(actual, fc)
        evals[name] = {
            'qlike': float(q),
            'spearman_rho': float(rho),
            'spearman_p': float(p_rho),
        }

    # DM tests (all pairs against CARR_YZ)
    loss_yz = qlike_pointwise(actual, results['fc_carr_yz'])
    dm_results = {}
    for name, fc in models.items():
        if name == 'CARR_YZ':
            continue
        loss_other = qlike_pointwise(actual, fc)
        t_stat, p_val = dm_test(loss_other, loss_yz, h=1)
        dm_results[f'CARR_YZ_vs_{name}'] = {
            'dm_t': float(t_stat),
            'dm_p': float(p_val),
            'yz_better': bool(t_stat > 0),  # positive t means loss_other > loss_yz
            'significant_harvey': bool(abs(t_stat) > 3.0),
        }

    # Also DM: CARR_YZ vs CARR_Parkinson specifically
    # (already included above, but let's also do GARCH vs GJR for completeness)
    loss_garch = qlike_pointwise(actual, results['fc_garch'])
    loss_gjr = qlike_pointwise(actual, results['fc_gjr'])
    t_gg, p_gg = dm_test(loss_garch, loss_gjr, h=1)
    dm_results['GJR_vs_GARCH'] = {
        'dm_t': float(t_gg),
        'dm_p': float(p_gg),
        'gjr_better': bool(t_gg > 0),
        'significant_harvey': bool(abs(t_gg) > 3.0),
    }

    return evals, dm_results


def compute_gap_ratio(df):
    """Compute gap ratio = Var(overnight_return) / Var(total_return)."""
    overnight = df['overnight_return'].dropna()
    total = df['log_return'].dropna()
    gap_ratio = overnight.var() / total.var()
    return {
        'gap_ratio': float(gap_ratio),
        'var_overnight': float(overnight.var()),
        'var_total': float(total.var()),
        'mean_abs_overnight': float(overnight.abs().mean()),
        'mean_abs_total': float(total.abs().mean()),
    }


# ============================================================
# 2. MAIN EXPERIMENT
# ============================================================

print("=" * 60)
print("K938: Yang-Zhang CARR Cross-Asset Validation")
print("=" * 60)

# Asset definitions
ASSETS = {
    'SPY': {'ticker': 'SPY', 'name': 'S&P 500 ETF', 'start': '2004-01-01', 'window': 2000},
    'GLD': {'ticker': 'GLD', 'name': 'Gold ETF', 'start': '2004-11-18', 'window': 2000},
    'QQQ': {'ticker': 'QQQ', 'name': 'Nasdaq 100 ETF', 'start': '2004-01-01', 'window': 2000},
    '0050.TW': {'ticker': '0050.TW', 'name': 'Taiwan Top 50 ETF', 'start': '2006-01-01', 'window': 500},
}

OOS_START = '2016-01-01'
REFIT_EVERY = 21

all_results = {}

for asset_key, asset_info in ASSETS.items():
    print(f"\n{'='*60}")
    print(f"Processing: {asset_key} ({asset_info['name']})")
    print(f"{'='*60}")

    # Download data
    print(f"\n  Downloading {asset_info['ticker']}...")
    data = yf.download(asset_info['ticker'], start=asset_info['start'], end='2026-01-01', progress=False)

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    # 0050.TW: fix split issue
    if asset_key == '0050.TW':
        print("  Applying 0050.TW split fix (clean_tw50_data)...")
        from volpred.utils import clean_tw50_data
        # clean_tw50_data expects a price Series, but we need OHLC
        # Detect split: if 2013 prices >> 2014 prices, apply /4 to pre-2014
        split_date = pd.Timestamp('2014-01-02')
        if split_date in data.index:
            pre_split = data.loc[data.index < split_date]
            post_split = data.loc[data.index >= split_date]
            if len(pre_split) > 0 and len(post_split) > 0:
                ratio = pre_split['Close'].iloc[-1] / post_split['Close'].iloc[0]
                if ratio > 2.0:  # split detected
                    print(f"    Split detected (ratio={ratio:.2f}), dividing pre-2014 prices by 4")
                    for col in ['Open', 'High', 'Low', 'Close']:
                        data.loc[data.index < split_date, col] = data.loc[data.index < split_date, col] / 4.0
                else:
                    print(f"    No split artifact detected (ratio={ratio:.2f})")
        else:
            # Try using clean_tw50_data on Close
            clean_prices, _ = clean_tw50_data(data['Close'])
            adj_ratio = data['Close'] / clean_prices
            adj_ratio = adj_ratio.dropna()
            if adj_ratio.nunique() > 1:
                # Apply the same ratio to OHLC
                for col in ['Open', 'High', 'Low', 'Close']:
                    data[col] = data[col] / adj_ratio.reindex(data.index).ffill().bfill()
                print("    Applied clean_tw50_data adjustment to OHLC")

    # Compute range estimators
    data = compute_range_estimators(data)

    # Floor negative values
    FLOOR = 1e-10
    for col in ['range_parkinson', 'range_rs', 'range_yz']:
        data[col] = np.maximum(data[col], FLOOR)

    # Drop NaN
    data = data.dropna(subset=['range_parkinson', 'range_yz', 'log_return', 'r2', 'overnight_return'])

    print(f"  Total observations: {len(data)}")
    print(f"  Date range: {data.index[0].strftime('%Y-%m-%d')} ~ {data.index[-1].strftime('%Y-%m-%d')}")

    # Descriptive statistics
    print(f"\n  Descriptive Stats:")
    for name, col in [('Parkinson', 'range_parkinson'), ('YZ', 'range_yz'), ('r2', 'r2')]:
        vals = data[col]
        print(f"    {name:12s}: mean={vals.mean():.6f}, std={vals.std():.6f}")

    # Gap ratio
    gap_info = compute_gap_ratio(data)
    print(f"\n  Gap Analysis:")
    print(f"    Gap ratio = {gap_info['gap_ratio']:.4f} (Var(overnight)/Var(total))")
    print(f"    Mean |overnight| = {gap_info['mean_abs_overnight']:.6f}")
    print(f"    Mean |total|     = {gap_info['mean_abs_total']:.6f}")

    # Determine OOS start for this asset
    oos_start_ts = pd.Timestamp(OOS_START)
    if data.index[0] > oos_start_ts:
        # Need enough training data
        min_train = asset_info['window']
        if len(data) < min_train + 100:
            print(f"  SKIP: Not enough data ({len(data)} < {min_train + 100})")
            continue
        oos_start_ts = data.index[min_train]
        print(f"  Adjusted OOS start: {oos_start_ts.strftime('%Y-%m-%d')}")

    # Run OOS
    print(f"\n  Running OOS forecasting (window={asset_info['window']}, refit={REFIT_EVERY})...")
    oos_results = run_oos_for_asset(data, oos_start_ts, asset_info['window'], REFIT_EVERY)

    if oos_results is None:
        print(f"  SKIP: OOS failed")
        continue

    # Evaluate
    print(f"\n  Evaluating forecasts...")
    evals, dm_results = evaluate_forecasts(oos_results)

    # Print results
    print(f"\n  === Results for {asset_key} ===")
    print(f"  {'Model':<18s} {'QLIKE':>10s} {'Spearman':>10s}")
    print(f"  {'-'*40}")
    for model_name, ev in sorted(evals.items(), key=lambda x: x[1]['qlike']):
        print(f"  {model_name:<18s} {ev['qlike']:>10.6f} {ev['spearman_rho']:>10.4f}")

    print(f"\n  DM Tests (vs CARR_YZ):")
    for pair, dm in dm_results.items():
        sig_mark = "***" if dm.get('significant_harvey', False) else ""
        print(f"    {pair:<25s}: t={dm['dm_t']:>7.3f}, p={dm['dm_p']:.4f} {sig_mark}")

    # QLIKE improvement
    q_p = evals['CARR_Parkinson']['qlike']
    q_yz = evals['CARR_YZ']['qlike']
    improvement_pct = (q_p - q_yz) / q_p * 100
    print(f"\n  YZ improvement over Parkinson: {improvement_pct:+.2f}% QLIKE reduction")

    # Store results
    all_results[asset_key] = {
        'asset_info': {k: v for k, v in asset_info.items() if k != 'ticker'},
        'n_total': len(data),
        'n_oos': oos_results['n_oos'],
        'oos_start': str(oos_start_ts.strftime('%Y-%m-%d')),
        'gap_analysis': gap_info,
        'evaluations': evals,
        'dm_tests': dm_results,
        'yz_improvement_pct': float(improvement_pct),
        'model_params': {
            'GARCH': {k: float(v) if isinstance(v, (float, np.floating)) else v
                      for k, v in oos_results['params_garch'].items()},
            'GJR': {k: float(v) if isinstance(v, (float, np.floating)) else v
                    for k, v in oos_results['params_gjr'].items()},
            'CARR_Parkinson': {k: float(v) if isinstance(v, (float, np.floating)) else v
                               for k, v in oos_results['params_carr_p'].items()},
            'CARR_YZ': {k: float(v) if isinstance(v, (float, np.floating)) else v
                        for k, v in oos_results['params_carr_yz'].items()},
        },
    }


# ============================================================
# 3. CROSS-ASSET ANALYSIS
# ============================================================
print("\n" + "=" * 60)
print("CROSS-ASSET ANALYSIS")
print("=" * 60)

if len(all_results) >= 2:
    # Gap ratio vs YZ improvement
    gap_ratios = []
    yz_improvements = []
    asset_labels = []

    for asset_key, res in all_results.items():
        gap_ratios.append(res['gap_analysis']['gap_ratio'])
        yz_improvements.append(res['yz_improvement_pct'])
        asset_labels.append(asset_key)

    # Spearman correlation between gap ratio and YZ improvement
    if len(gap_ratios) >= 3:
        rho_gap, p_gap = stats.spearmanr(gap_ratios, yz_improvements)
    else:
        rho_gap = np.corrcoef(gap_ratios, yz_improvements)[0, 1]
        p_gap = np.nan  # Not enough for significance test

    print(f"\n  Gap Ratio vs YZ Improvement:")
    print(f"  {'Asset':<12s} {'Gap Ratio':>10s} {'YZ Improvement':>15s}")
    print(f"  {'-'*40}")
    for i, asset in enumerate(asset_labels):
        print(f"  {asset:<12s} {gap_ratios[i]:>10.4f} {yz_improvements[i]:>14.2f}%")
    print(f"\n  Correlation (gap ratio vs YZ improvement): r={rho_gap:.4f}")
    if not np.isnan(p_gap):
        print(f"  p-value: {p_gap:.4f}")

    cross_asset_analysis = {
        'gap_vs_improvement_corr': float(rho_gap),
        'gap_vs_improvement_p': float(p_gap) if not np.isnan(p_gap) else None,
        'assets': asset_labels,
        'gap_ratios': [float(x) for x in gap_ratios],
        'yz_improvements': [float(x) for x in yz_improvements],
    }
else:
    cross_asset_analysis = {'error': f'Only {len(all_results)} assets completed, need >= 2'}


# ============================================================
# 4. SUMMARY TABLE
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY TABLE")
print("=" * 60)

print(f"\n  {'Asset':<10s} {'Gap Ratio':>10s} | {'GARCH':>8s} {'GJR':>8s} {'CARR_P':>8s} {'CARR_YZ':>8s} | {'YZ vs P':>8s} {'DM t':>8s}")
print(f"  {'-'*85}")
for asset_key, res in all_results.items():
    ev = res['evaluations']
    dm_yz_p = res['dm_tests'].get('CARR_YZ_vs_CARR_Parkinson', {})
    dm_t = dm_yz_p.get('dm_t', np.nan)
    print(f"  {asset_key:<10s} {res['gap_analysis']['gap_ratio']:>10.4f} | "
          f"{ev['GARCH']['qlike']:>8.4f} {ev['GJR']['qlike']:>8.4f} "
          f"{ev['CARR_Parkinson']['qlike']:>8.4f} {ev['CARR_YZ']['qlike']:>8.4f} | "
          f"{res['yz_improvement_pct']:>7.2f}% {dm_t:>8.3f}")

print(f"\n  Spearman Rank Correlation (on r^2):")
print(f"  {'Asset':<10s} {'GARCH':>8s} {'GJR':>8s} {'CARR_P':>8s} {'CARR_YZ':>8s}")
print(f"  {'-'*50}")
for asset_key, res in all_results.items():
    ev = res['evaluations']
    print(f"  {asset_key:<10s} {ev['GARCH']['spearman_rho']:>8.4f} {ev['GJR']['spearman_rho']:>8.4f} "
          f"{ev['CARR_Parkinson']['spearman_rho']:>8.4f} {ev['CARR_YZ']['spearman_rho']:>8.4f}")


# ============================================================
# 5. VISUALIZATION
# ============================================================
print("\n[Generating plots...]")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K938: Yang-Zhang CARR Cross-Asset Validation\n(QLIKE on r², lower = better)',
             fontsize=14, fontweight='bold')

# Panel 1: QLIKE comparison bar chart
ax = axes[0, 0]
assets_plot = list(all_results.keys())
n_assets = len(assets_plot)
models_plot = ['GARCH', 'GJR', 'CARR_Parkinson', 'CARR_YZ']
colors = ['#2196F3', '#4CAF50', '#FF9800', '#E91E63']
x = np.arange(n_assets)
width = 0.2
for j, model in enumerate(models_plot):
    vals = [all_results[a]['evaluations'][model]['qlike'] for a in assets_plot]
    ax.bar(x + j * width - 1.5 * width, vals, width, label=model, color=colors[j], alpha=0.85)
ax.set_xticks(x)
ax.set_xticklabels(assets_plot, fontsize=11)
ax.set_ylabel('QLIKE (lower = better)', fontsize=11)
ax.set_title('QLIKE on r² by Asset', fontsize=12)
ax.legend(fontsize=9, loc='upper right')
ax.grid(axis='y', alpha=0.3)

# Panel 2: Spearman correlation comparison
ax = axes[0, 1]
for j, model in enumerate(models_plot):
    vals = [all_results[a]['evaluations'][model]['spearman_rho'] for a in assets_plot]
    ax.bar(x + j * width - 1.5 * width, vals, width, label=model, color=colors[j], alpha=0.85)
ax.set_xticks(x)
ax.set_xticklabels(assets_plot, fontsize=11)
ax.set_ylabel('Spearman rho', fontsize=11)
ax.set_title('Spearman Rank Correlation on r²', fontsize=12)
ax.legend(fontsize=9, loc='lower right')
ax.grid(axis='y', alpha=0.3)

# Panel 3: Gap ratio vs YZ improvement scatter
ax = axes[1, 0]
gap_r = [all_results[a]['gap_analysis']['gap_ratio'] for a in assets_plot]
yz_imp = [all_results[a]['yz_improvement_pct'] for a in assets_plot]
ax.scatter(gap_r, yz_imp, s=120, c='#E91E63', zorder=5, edgecolors='black')
for i, a in enumerate(assets_plot):
    ax.annotate(a, (gap_r[i], yz_imp[i]), textcoords="offset points",
                xytext=(10, 5), fontsize=11, fontweight='bold')
# Fit line if >= 2 points
if len(gap_r) >= 2:
    z = np.polyfit(gap_r, yz_imp, 1)
    p_line = np.poly1d(z)
    x_line = np.linspace(min(gap_r) * 0.9, max(gap_r) * 1.1, 50)
    ax.plot(x_line, p_line(x_line), '--', color='gray', alpha=0.7)
ax.set_xlabel('Gap Ratio (Var(overnight)/Var(total))', fontsize=11)
ax.set_ylabel('YZ Improvement over Parkinson (%)', fontsize=11)
ax.set_title('Gap Ratio vs YZ CARR Improvement', fontsize=12)
ax.grid(alpha=0.3)

# Panel 4: DM test t-statistics
ax = axes[1, 1]
dm_pairs = ['CARR_YZ_vs_GARCH', 'CARR_YZ_vs_GJR', 'CARR_YZ_vs_CARR_Parkinson']
dm_labels = ['vs GARCH', 'vs GJR', 'vs CARR_P']
dm_colors_pos = '#4CAF50'
dm_colors_neg = '#f44336'
bar_width = 0.15
for j, (pair, label) in enumerate(zip(dm_pairs, dm_labels)):
    t_vals = []
    for a in assets_plot:
        dm = all_results[a]['dm_tests'].get(pair, {})
        t_vals.append(dm.get('dm_t', 0))
    bar_colors = [dm_colors_pos if t > 0 else dm_colors_neg for t in t_vals]
    ax.bar(x + j * bar_width - bar_width, t_vals, bar_width, label=label,
           color=bar_colors, alpha=0.85, edgecolor='black', linewidth=0.5)
ax.axhline(y=3.0, color='red', linestyle='--', alpha=0.7, label='Harvey |t|>3.0')
ax.axhline(y=-3.0, color='red', linestyle='--', alpha=0.7)
ax.axhline(y=0, color='black', linewidth=0.5)
ax.set_xticks(x)
ax.set_xticklabels(assets_plot, fontsize=11)
ax.set_ylabel('DM t-statistic', fontsize=11)
ax.set_title('DM Test: CARR_YZ vs Others\n(positive = YZ better)', fontsize=12)
ax.legend(fontsize=9, loc='best')
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
chart_path = os.path.join(SCRIPT_DIR, 'k938_cross_asset.png')
plt.savefig(chart_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved: {chart_path}")


# ============================================================
# 6. SAVE RESULTS
# ============================================================
print("\n[Saving results...]")

results_out = {
    'experiment_id': 'K938',
    'title': 'Yang-Zhang CARR Cross-Asset Validation',
    'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'data_source': 'yfinance',
    'oos_start': OOS_START,
    'refit_every': REFIT_EVERY,
    'references': [
        'Parkinson (1980) JoB',
        'Yang & Zhang (2000) JoB',
        'Chou (2005) JFE',
        'Patton (2011) J. Econometrics 160',
    ],
    'assets': all_results,
    'cross_asset_analysis': cross_asset_analysis,
    'conclusions': {
        'h1_gap_predicts_yz_improvement': None,  # Will be set below
        'h2_0050tw_largest_improvement': None,
        'h3_gld_smallest_improvement': None,
    },
}

# Set conclusions based on results
if len(all_results) >= 2:
    # H1: Gap ratio predicts YZ improvement
    results_out['conclusions']['h1_gap_predicts_yz_improvement'] = {
        'supported': float(cross_asset_analysis.get('gap_vs_improvement_corr', 0)) > 0.3,
        'correlation': cross_asset_analysis.get('gap_vs_improvement_corr'),
        'interpretation': ('Positive correlation between gap ratio and YZ improvement'
                          if float(cross_asset_analysis.get('gap_vs_improvement_corr', 0)) > 0
                          else 'No clear relationship')
    }

    # H2: 0050.TW largest improvement
    if '0050.TW' in all_results:
        tw_imp = all_results['0050.TW']['yz_improvement_pct']
        max_imp = max(r['yz_improvement_pct'] for r in all_results.values())
        results_out['conclusions']['h2_0050tw_largest_improvement'] = {
            'supported': tw_imp >= max_imp * 0.95,  # Within 5% of max
            'tw_improvement': tw_imp,
            'max_improvement': max_imp,
            'max_asset': [k for k, v in all_results.items() if v['yz_improvement_pct'] == max_imp][0],
        }

    # H3: GLD smallest improvement
    if 'GLD' in all_results:
        gld_imp = all_results['GLD']['yz_improvement_pct']
        min_imp = min(r['yz_improvement_pct'] for r in all_results.values())
        results_out['conclusions']['h3_gld_smallest_improvement'] = {
            'supported': gld_imp <= min_imp * 1.05,  # Within 5% of min
            'gld_improvement': gld_imp,
            'min_improvement': min_imp,
            'min_asset': [k for k, v in all_results.items() if v['yz_improvement_pct'] == min_imp][0],
        }

results_path = os.path.join(SCRIPT_DIR, 'k938_results.json')
with open(results_path, 'w') as f:
    json.dump(results_out, f, indent=2, default=str)
print(f"  Saved: {results_path}")


# ============================================================
# 7. FINAL SUMMARY
# ============================================================
print("\n" + "=" * 60)
print("K938 FINAL SUMMARY")
print("=" * 60)

for asset_key, res in all_results.items():
    q_p = res['evaluations']['CARR_Parkinson']['qlike']
    q_yz = res['evaluations']['CARR_YZ']['qlike']
    q_garch = res['evaluations']['GARCH']['qlike']
    q_gjr = res['evaluations']['GJR']['qlike']
    dm_yz_p = res['dm_tests'].get('CARR_YZ_vs_CARR_Parkinson', {})
    dm_yz_garch = res['dm_tests'].get('CARR_YZ_vs_GARCH', {})

    print(f"\n  {asset_key} (gap ratio = {res['gap_analysis']['gap_ratio']:.4f}):")
    print(f"    Best model (QLIKE): {min(res['evaluations'].items(), key=lambda x: x[1]['qlike'])[0]}")
    print(f"    YZ vs Parkinson: {res['yz_improvement_pct']:+.2f}% QLIKE, DM t={dm_yz_p.get('dm_t', np.nan):.3f}")
    print(f"    YZ vs GARCH:     DM t={dm_yz_garch.get('dm_t', np.nan):.3f}")

print(f"\n  Cross-asset correlation (gap ratio vs YZ improvement): "
      f"r={cross_asset_analysis.get('gap_vs_improvement_corr', 'N/A')}")

print("\n  DONE.")
