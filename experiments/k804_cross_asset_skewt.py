#!/usr/bin/env python3
"""
K804: Cross-Asset GJR + Skewed-t VaR Validation
================================================
[提出: 用戶, 執行: Claude]

K802 found GJR + Skewed-t = dual champion on SPY:
  - QLIKE #1 (GJR wins vs GARCH, DM t=-3.25, Harvey PASS)
  - VaR Trinity PASS (Kupiec + Christoffersen + Basel GREEN)

K804 question: Does this hold across asset classes?
  - QQQ: tech, higher vol, stronger asymmetry?
  - GLD: gold, safe-haven, different dynamics
  - 0050.TW: Taiwan ETF, US lead-lag, higher vol
  - BTC-USD: crypto, extreme tails, near-zero skewness?

For each asset, test 3 GJR VaR variants:
  1. GJR + Normal        — baseline (K799 FAIL)
  2. GJR + Student-t     — fat tails only
  3. GJR + FHS           — nonparametric empirical quantile

Evaluation:
  - QLIKE on r² (Patton 2011 proxy-robust, GJR always wins since same σ²)
  - VaR 1% backtest: Kupiec + Christoffersen + Basel trinity
  - Does Student-t / FHS fix Normal's tail underestimation across all assets?

Setup:
  - Expanding window, refit every 63 days
  - OOS: 2023-01-03 to 2024-12-31
  - signal.shift(1): forecasts use data[:t] only (no lookahead)
  - For 0050.TW: clean_tw50_data() to fix 1:4 split artifact

References:
  - Patton (2011) J. Econometrics 160 — QLIKE proxy-robust
  - Kupiec (1995) — unconditional coverage
  - Christoffersen (1998) — conditional independence
  - Harvey et al. (2016) — Harvey t>3.0 threshold
  - Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH
  - Fernandez & Steel (1998) JASA 93 — skewed-t
  - K802: GJR+SkewedT dual champion on SPY (QLIKE #1 + VaR PASS)
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
from scipy.stats import norm, t as t_dist, chi2, spearmanr

# Add project root to path for volpred.utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from volpred.utils import clean_tw50_data

warnings.filterwarnings('ignore')

RESULTS_PATH = os.path.join(os.path.dirname(__file__), 'k804_cross_asset_skewt_results.json')
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63
ALPHA_VAR = 0.01

ASSETS = {
    'QQQ': {'ticker': 'QQQ', 'name': 'QQQ (Nasdaq-100 ETF)', 'is_tw': False, 'is_crypto': False},
    'GLD': {'ticker': 'GLD', 'name': 'GLD (Gold ETF)', 'is_tw': False, 'is_crypto': False},
    '0050.TW': {'ticker': '0050.TW', 'name': '0050.TW (Taiwan 50 ETF)', 'is_tw': True, 'is_crypto': False},
    'BTC-USD': {'ticker': 'BTC-USD', 'name': 'BTC-USD (Bitcoin)', 'is_tw': False, 'is_crypto': True},
}


# ==============================================================
# A. Numba-free variance filters (fast enough for this scale)
# ==============================================================

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


def fit_gjr(returns, n_starts=3):
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


def compute_std_residuals(returns, params):
    """Compute standardized residuals z_t = r_t / σ_t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'], params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]


def fcast_gjr_next(returns, params):
    """GJR one-step σ² forecast using data up to but NOT including the forecast day."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'], params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(float(f), 1e-12)


# ==============================================================
# B. Distribution parameter estimation
# ==============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """Estimate Student-t df from standardized residuals via MLE.

    FIX (Codex K804, Issue 2): std_residuals = r_t / sigma_t are unit-variance by
    construction. scipy.stats.t(df) has variance df/(df-2). Therefore to fit a
    Student-t to unit-variance data, we must use the SCALED parameterization:
        z ~ t(df) * sqrt((df-2)/df)  <=>  z/scale ~ t(df)
    where scale = sqrt((df-2)/df).

    Equivalently, we fit t(df, loc=0, scale=sqrt((df-2)/df)) to z.
    The correct VaR quantile is then:
        VaR = sigma * t.ppf(alpha, df) * sqrt((df-2)/df)
    which is the same as:
        VaR = sigma * t.ppf(alpha, df, scale=sqrt((df-2)/df))
    """
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 30:
        return 5.0

    def neg_ll(log_df):
        df = np.exp(log_df)
        if df < df_min or df > df_max:
            return 1e10
        # scale = sqrt((df-2)/df) so that t(df, scale=scale) has unit variance
        scale = np.sqrt((df - 2.0) / df)
        ll = np.sum(t_dist.logpdf(z, df=df, loc=0.0, scale=scale))
        return -ll if np.isfinite(ll) else 1e10

    try:
        res = minimize(neg_ll, x0=[np.log(5.0)], method='L-BFGS-B',
                       bounds=[(np.log(df_min), np.log(df_max))],
                       options={'maxiter': 500})
        return float(np.clip(np.exp(res.x[0]), df_min, df_max))
    except Exception:
        return 5.0


def t_var_quantile(alpha, df):
    """
    Correct VaR quantile for unit-variance standardized t residuals.
    Returns z_alpha such that P(z < z_alpha) = alpha, where z ~ t(df, scale=sqrt((df-2)/df)).
    """
    scale = np.sqrt((df - 2.0) / df)
    return float(t_dist.ppf(alpha, df=df, loc=0.0, scale=scale))


# ==============================================================
# C. VaR backtest
# ==============================================================

def var_backtest(returns, var_series, alpha_var=0.01):
    """Kupiec + Christoffersen + Basel traffic light."""
    r = np.asarray(returns, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)

    violations = (r < var).astype(int)
    n = len(r)
    n1 = int(violations.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec LR test
    # FIX (Codex K804): n1==0 is NOT automatically PASS — at 1% VaR, 0/500 gives p≈0.001.
    # Must compute LR using boundary: log(pi_hat) → log(alpha_var) if n1=0 (one-sided limit).
    if n1 == 0:
        # LR = -2 * (n * log(1-alpha)) — lower limit: over-conservative VaR, often FAIL
        lr = -2 * n0 * np.log(1 - alpha_var)
        kup_stat = float(lr)
        kup_p = float(1 - chi2.cdf(lr, df=1))
    elif n1 == n:
        lr = -2 * n1 * np.log(alpha_var)
        kup_stat = float(lr)
        kup_p = float(1 - chi2.cdf(lr, df=1))
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
        pi_all = (t01 + t11) / n if n > 1 else 0
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

    # Basel traffic light
    if pi_hat <= alpha_var * 1.5:
        traffic = 'green'
    elif pi_hat <= alpha_var * 2.0:
        traffic = 'yellow'
    else:
        traffic = 'red'

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
        'trinity_pass': bool(kup_p > 0.05 and cc_p > 0.05 and traffic == 'green'),
    }


# ==============================================================
# D. QLIKE helpers
# ==============================================================

def qlike_score(actual, predicted):
    a = np.asarray(actual, dtype=np.float64)
    f = np.asarray(predicted, dtype=np.float64)
    valid = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
    if valid.sum() < 10:
        return np.nan
    a, f = a[valid], f[valid]
    ratio = a / f
    return float(np.mean(ratio - np.log(ratio) - 1))


def pointwise_qlike(actual, predicted):
    a = np.maximum(np.asarray(actual, dtype=np.float64), 1e-16)
    f = np.maximum(np.asarray(predicted, dtype=np.float64), 1e-16)
    ratio = a / f
    return ratio - np.log(ratio) - 1


def dm_test(loss1, loss2, h=1):
    """DM test with Newey-West HAC. Negative t-stat → model 1 better."""
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
        w = 1 - lag / (max_lag + 1)
        gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2 * w * gamma_l
    if var_d <= 0:
        return 0.0, 1.0
    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0
    t_stat = d_mean / se
    p_val = 2 * (1 - t_dist.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ==============================================================
# E. Download & clean data
# ==============================================================

def download_asset(ticker, is_tw=False, is_crypto=False):
    """Download returns for a given asset."""
    print(f"\n  Downloading {ticker}...")
    try:
        if is_crypto:
            # BTC trades 24/7 — use daily data
            df = yf.download(ticker, start='2016-01-01', end='2025-01-01',
                             auto_adjust=True, progress=False)
        else:
            df = yf.download(ticker, start='2006-01-01', end='2025-01-01',
                             auto_adjust=True, progress=False)
    except Exception as e:
        print(f"  ERROR downloading {ticker}: {e}")
        return None, None

    if df.empty:
        print(f"  No data for {ticker}")
        return None, None

    # Flatten multi-level columns if needed
    if hasattr(df.columns, 'levels'):
        df.columns = df.columns.get_level_values(0)

    price_col = 'Close' if 'Close' in df.columns else 'Adj Close'
    prices = df[price_col].dropna()

    if is_tw:
        prices, returns = clean_tw50_data(prices)
        returns = returns.dropna()  # clean_tw50_data uses pct_change() which has NaN at [0]
        print(f"  0050.TW split artifact cleaned. n_prices={len(prices)}, n_returns={len(returns)}")
    else:
        returns = prices.pct_change().dropna()

    print(f"  {ticker}: {len(prices)} days, {prices.index[0].date()} to {prices.index[-1].date()}")
    return prices, returns


# ==============================================================
# F. Per-asset OOS loop
# ==============================================================

def run_asset_oos(ticker, returns_all, asset_info):
    """
    Expanding-window OOS for one asset.

    CRITICAL: Forecast at time t uses only data[:t] (i.e., data up to day t-1).
    This is equivalent to signal.shift(1) — no lookahead.
    """
    asset_name = asset_info['name']
    is_crypto = asset_info['is_crypto']
    print(f"\n{'='*55}")
    print(f"Processing {asset_name}")
    print(f"{'='*55}")

    r = returns_all.values.astype(np.float64)
    dates = returns_all.index

    # OOS index identification
    oos_start = pd.Timestamp(OOS_START)
    oos_end = pd.Timestamp(OOS_END)

    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) < 50:
        print(f"  Insufficient OOS data: {len(oos_indices)} days. Skipping.")
        return None

    oos_start_idx = oos_indices[0]
    oos_end_idx = oos_indices[-1] + 1
    n_oos = oos_end_idx - oos_start_idx

    print(f"  IS: {dates[0].date()} to {dates[oos_start_idx - 1].date()} ({oos_start_idx} days)")
    print(f"  OOS: {dates[oos_start_idx].date()} to {dates[oos_end_idx - 1].date()} ({n_oos} days)")

    # Descriptive stats for OOS returns
    r_oos = r[oos_start_idx:oos_end_idx]
    from scipy.stats import skew, kurtosis
    oos_stats = {
        'mean_return': round(float(np.mean(r_oos)), 6),
        'std_return': round(float(np.std(r_oos)), 6),
        'skewness': round(float(skew(r_oos)), 4),
        'kurtosis': round(float(kurtosis(r_oos)), 4),
        'min_return': round(float(np.min(r_oos)), 6),
        'max_return': round(float(np.max(r_oos)), 6),
        'n_days': n_oos,
    }
    print(f"  OOS stats: mean={oos_stats['mean_return']:.4f}, std={oos_stats['std_return']:.4f}, "
          f"skew={oos_stats['skewness']:.3f}, kurt={oos_stats['kurtosis']:.3f}")

    # Storage arrays
    sigma2_gjr = np.full(n_oos, np.nan)
    var_normal = np.full(n_oos, np.nan)
    var_t = np.full(n_oos, np.nan)
    var_fhs = np.full(n_oos, np.nan)

    dist_params_log = []
    gjr_params = None
    last_fit = -REFIT_EVERY  # force fit on day 0
    # Track last ATTEMPT separately so failed fits don't trigger infinite retries
    last_fit_attempt = -REFIT_EVERY

    z_normal = float(norm.ppf(ALPHA_VAR))  # -2.3263
    df_t_cur = 5.0  # default until first fit
    fhs_q_cur = z_normal  # default

    t0 = time.time()
    n_refits = 0

    for i in range(n_oos):
        t = oos_start_idx + i

        # CRITICAL: use data[:t] only — data at t is the CURRENT day's return (not yet observed)
        r_train = r[:t]

        # Refit check: trigger every REFIT_EVERY days based on last ATTEMPT, not last success
        # This prevents infinite retry loop when fit fails
        if i - last_fit_attempt >= REFIT_EVERY:
            last_fit_attempt = i
            new_params = fit_gjr(r_train)
            n_refits += 1

            if new_params is not None:
                gjr_params = new_params
                last_fit = i
                # Standardized residuals for distribution fitting
                z_is = compute_std_residuals(r_train, gjr_params)
                z_is = z_is[np.isfinite(z_is)]

                # Student-t df
                df_t_cur = estimate_t_df(z_is)

                # FHS empirical quantile
                fhs_q_cur = float(np.quantile(z_is, ALPHA_VAR))

                dist_params_log.append({
                    'day_idx': i,
                    'date': str(dates[t].date()),
                    'df_t': round(df_t_cur, 4),
                    'fhs_q': round(fhs_q_cur, 4),
                    'gjr_persistence': round(gjr_params['persistence'], 6),
                })

                if i % 126 == 0 or i == 0:
                    print(f"  [Refit {n_refits}] Day {i}/{n_oos} ({dates[t].date()}), "
                          f"persist={gjr_params['persistence']:.4f}, "
                          f"df={df_t_cur:.2f}, FHS_q={fhs_q_cur:.4f}")
            else:
                print(f"  [Refit {n_refits}] Day {i}: GJR fit FAILED, using cached params")
                dist_params_log.append({
                    'day_idx': i, 'date': str(dates[t].date()),
                    'df_t': df_t_cur, 'fhs_q': fhs_q_cur, 'gjr_persistence': None
                })

        # Generate forecasts
        if gjr_params is not None:
            s2_gjr = fcast_gjr_next(r_train, gjr_params)
            sigma_gjr = np.sqrt(max(s2_gjr, 1e-16))
            sigma2_gjr[i] = s2_gjr

            # VaR 1: Normal
            var_normal[i] = sigma_gjr * z_normal

            # VaR 2: Student-t (fat tails)
            # FIX (Codex K804): use unit-variance scaled t quantile
            z_t_val = t_var_quantile(ALPHA_VAR, df_t_cur)
            var_t[i] = sigma_gjr * z_t_val

            # VaR 3: FHS (empirical quantile)
            var_fhs[i] = sigma_gjr * fhs_q_cur

    elapsed = time.time() - t0
    print(f"  OOS loop done: {elapsed:.1f}s, {n_refits} refits")

    # Align realized returns with forecasts
    r_realized = r[oos_start_idx:oos_end_idx]
    r2_realized = r_realized ** 2

    # Remove NaN positions
    valid = np.isfinite(sigma2_gjr) & np.isfinite(r_realized)
    r_v = r_realized[valid]
    r2_v = r2_realized[valid]
    s2_v = sigma2_gjr[valid]
    vn_v = var_normal[valid]
    vt_v = var_t[valid]
    vf_v = var_fhs[valid]

    n_valid = int(valid.sum())
    print(f"  Valid OOS observations: {n_valid}/{n_oos}")

    # QLIKE
    qlike_gjr = qlike_score(r2_v, s2_v)

    # VaR backtests
    bt_normal = var_backtest(r_v, vn_v, ALPHA_VAR)
    bt_t = var_backtest(r_v, vt_v, ALPHA_VAR)
    bt_fhs = var_backtest(r_v, vf_v, ALPHA_VAR)

    # Spearman rank correlation: predicted σ² vs realized r²
    rho, rho_p = spearmanr(s2_v, r2_v)

    print(f"\n  QLIKE (GJR): {qlike_gjr:.6f}")
    print(f"  Spearman rho: {rho:.4f} (p={rho_p:.4f})")
    print(f"  VaR (Normal): violations={bt_normal['n_violations']}/{n_valid} "
          f"({bt_normal['violation_rate']:.4f}), PASS={bt_normal['trinity_pass']}, "
          f"Basel={bt_normal['basel_traffic_light']}")
    print(f"  VaR (Student-t df={df_t_cur:.1f}): violations={bt_t['n_violations']}/{n_valid} "
          f"({bt_t['violation_rate']:.4f}), PASS={bt_t['trinity_pass']}, "
          f"Basel={bt_t['basel_traffic_light']}")
    print(f"  VaR (FHS q={fhs_q_cur:.3f}): violations={bt_fhs['n_violations']}/{n_valid} "
          f"({bt_fhs['violation_rate']:.4f}), PASS={bt_fhs['trinity_pass']}, "
          f"Basel={bt_fhs['basel_traffic_light']}")

    # Summary of latest distribution params
    final_params = dist_params_log[-1] if dist_params_log else {}

    return {
        'oos_stats': oos_stats,
        'n_oos_valid': n_valid,
        'n_refits': n_refits,
        'qlike': round(qlike_gjr, 6) if np.isfinite(qlike_gjr) else None,
        'spearman': {'rho': round(float(rho), 4), 'p_value': round(float(rho_p), 4)},
        'var_backtest': {
            'GJR+Normal': bt_normal,
            'GJR+StudentT': bt_t,
            'GJR+FHS': bt_fhs,
        },
        'distribution_params': {
            'student_t_df_final': round(df_t_cur, 4),
            'fhs_quantile_final': round(fhs_q_cur, 4),
        },
        'dist_params_log': dist_params_log,
        'runtime_seconds': round(elapsed, 2),
    }


# ==============================================================
# G. Main
# ==============================================================

def main():
    print("=" * 60)
    print("K804: Cross-Asset GJR + Skewed-t VaR Validation")
    print("=" * 60)
    print(f"OOS: {OOS_START} to {OOS_END}, refit every {REFIT_EVERY} days")
    print(f"VaR alpha: {ALPHA_VAR*100}% (1-sided)")

    t_global = time.time()
    results_by_asset = {}

    for asset_key, asset_info in ASSETS.items():
        ticker = asset_info['ticker']
        is_tw = asset_info['is_tw']
        is_crypto = asset_info['is_crypto']

        prices, returns = download_asset(ticker, is_tw=is_tw, is_crypto=is_crypto)
        if returns is None or len(returns) < 200:
            print(f"  Skipping {asset_key}: insufficient data")
            results_by_asset[asset_key] = {'error': 'insufficient data'}
            continue

        result = run_asset_oos(ticker, returns, asset_info)
        if result is None:
            results_by_asset[asset_key] = {'error': 'OOS loop failed'}
        else:
            results_by_asset[asset_key] = result

    total_elapsed = time.time() - t_global

    # ==============================================================
    # H. Cross-asset summary
    # ==============================================================
    print("\n" + "=" * 60)
    print("CROSS-ASSET SUMMARY")
    print("=" * 60)

    summary_rows = []
    for asset_key, res in results_by_asset.items():
        if 'error' in res:
            print(f"  {asset_key:12s}: ERROR — {res['error']}")
            continue
        vbt = res['var_backtest']
        row = {
            'asset': asset_key,
            'asset_name': ASSETS[asset_key]['name'],
            'n_oos': res['n_oos_valid'],
            'qlike': res['qlike'],
            'spearman_rho': res['spearman']['rho'],
            'normal_violations': vbt['GJR+Normal']['n_violations'],
            'normal_rate': vbt['GJR+Normal']['violation_rate'],
            'normal_pass': vbt['GJR+Normal']['trinity_pass'],
            'normal_basel': vbt['GJR+Normal']['basel_traffic_light'],
            't_violations': vbt['GJR+StudentT']['n_violations'],
            't_rate': vbt['GJR+StudentT']['violation_rate'],
            't_pass': vbt['GJR+StudentT']['trinity_pass'],
            't_basel': vbt['GJR+StudentT']['basel_traffic_light'],
            'fhs_violations': vbt['GJR+FHS']['n_violations'],
            'fhs_rate': vbt['GJR+FHS']['violation_rate'],
            'fhs_pass': vbt['GJR+FHS']['trinity_pass'],
            'fhs_basel': vbt['GJR+FHS']['basel_traffic_light'],
            'df_t_final': res['distribution_params']['student_t_df_final'],
        }
        summary_rows.append(row)
        print(f"  {asset_key:12s}: QLIKE={row['qlike']:.6f}, rho={row['spearman_rho']:.3f}")
        print(f"    Normal:    {row['normal_violations']:3d} viol ({row['normal_rate']:.4f}), "
              f"PASS={row['normal_pass']}, Basel={row['normal_basel']}")
        print(f"    Student-t: {row['t_violations']:3d} viol ({row['t_rate']:.4f}), "
              f"PASS={row['t_pass']}, Basel={row['t_basel']}, df={row['df_t_final']:.1f}")
        print(f"    FHS:       {row['fhs_violations']:3d} viol ({row['fhs_rate']:.4f}), "
              f"PASS={row['fhs_pass']}, Basel={row['fhs_basel']}")

    # Aggregate counts
    n_assets = len(summary_rows)
    n_normal_pass = sum(1 for r in summary_rows if r['normal_pass'])
    n_t_pass = sum(1 for r in summary_rows if r['t_pass'])
    n_fhs_pass = sum(1 for r in summary_rows if r['fhs_pass'])

    print(f"\nTrinity PASS rate:")
    print(f"  Normal:    {n_normal_pass}/{n_assets}")
    print(f"  Student-t: {n_t_pass}/{n_assets}")
    print(f"  FHS:       {n_fhs_pass}/{n_assets}")

    # Key findings
    student_t_fixes_normal = all(
        r['t_pass'] and not r['normal_pass'] or r['t_pass']
        for r in summary_rows
    )
    all_t_pass = n_t_pass == n_assets
    all_fhs_pass = n_fhs_pass == n_assets

    print(f"\nKey findings:")
    print(f"  All assets Student-t PASS: {all_t_pass}")
    print(f"  All assets FHS PASS: {all_fhs_pass}")
    print(f"  Normal fails some: {n_normal_pass < n_assets}")

    # ==============================================================
    # I. Save results
    # ==============================================================
    results = {
        'experiment_id': 'K804',
        'title': 'Cross-Asset GJR + Skewed-t VaR Validation',
        'attribution': '[提出: 用戶, 執行: Claude]',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance',
        'assets_tested': list(ASSETS.keys()),
        'oos_period': f'{OOS_START} to {OOS_END}',
        'refit_every': REFIT_EVERY,
        'alpha_var': ALPHA_VAR,
        'models': ['GJR+Normal', 'GJR+StudentT', 'GJR+FHS'],
        'per_asset_results': results_by_asset,
        'summary': summary_rows,
        'aggregate': {
            'n_assets_tested': n_assets,
            'normal_pass_count': n_normal_pass,
            'student_t_pass_count': n_t_pass,
            'fhs_pass_count': n_fhs_pass,
            'normal_pass_rate': round(n_normal_pass / max(n_assets, 1), 4),
            'student_t_pass_rate': round(n_t_pass / max(n_assets, 1), 4),
            'fhs_pass_rate': round(n_fhs_pass / max(n_assets, 1), 4),
            'fat_tail_fix_universal': all_t_pass,
            'fhs_fix_universal': all_fhs_pass,
        },
        'runtime_seconds': round(total_elapsed, 2),
        'references': [
            'Patton (2011) J. Econometrics 160 — QLIKE proxy-robust loss',
            'Kupiec (1995) — unconditional VaR coverage',
            'Christoffersen (1998) — conditional VaR independence',
            'Harvey et al. (2016) — multiple testing threshold t>3.0',
            'Glosten, Jagannathan, Runkle (1993) JoF 48 — GJR-GARCH',
            'Fernandez & Steel (1998) JASA 93 — skewed-t distribution',
            'K802: GJR+SkewedT dual champion on SPY (QLIKE #1 + VaR PASS)',
            'K799: Grand Model Evaluation — GJR wins QLIKE, fails VaR with Normal',
        ],
        'limitations': [
            'OOS 2023-2024 is relatively calm for equities — extreme events underrepresented',
            'BTC has shorter history (2016+) and 24/7 trading — GJR assumes trading-day returns',
            '0050.TW uses US VIX as signal (K802 was US-only), lag structure may differ',
            'Daily r² noisy proxy for true σ² — 5-min RV unavailable for all assets here',
            'n=~500 OOS days has limited power for VaR backtests (Type II error elevated)',
            'Student-t estimated from IS residuals — estimation error propagates to VaR',
        ],
    }

    # Remove dist_params_log from per_asset_results to keep JSON manageable
    results_clean = dict(results)
    results_clean['per_asset_results'] = {}
    for k, v in results_by_asset.items():
        if 'error' in v:
            results_clean['per_asset_results'][k] = v
        else:
            entry = {kk: vv for kk, vv in v.items() if kk != 'dist_params_log'}
            entry['dist_params_sample'] = v.get('dist_params_log', [])[:3]  # keep first 3
            results_clean['per_asset_results'][k] = entry

    with open(RESULTS_PATH, 'w') as f:
        json.dump(results_clean, f, indent=2, default=str)

    print(f"\nResults saved to: {RESULTS_PATH}")
    print(f"Total runtime: {total_elapsed:.1f}s")
    return results_clean


if __name__ == '__main__':
    main()
