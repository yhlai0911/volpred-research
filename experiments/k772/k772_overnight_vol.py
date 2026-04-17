#!/usr/bin/env python3
"""
K772: Overnight Volatility Component — Hansen & Lunde (2005) Decomposition
==========================================================================
[提出: 用戶, 執行: Claude]

SPY has OHLC data, enabling decomposition of close-to-close returns into:
  r_total = r_overnight + r_intraday
  r_overnight = log(Open_t / Close_{t-1})
  r_intraday  = log(Close_t / Open_t)

Hansen & Lunde (2005) showed ~20% of daily variance is overnight for US
equities. Our prior experiments (T44, Phase I) found 43% for SPY 2020-2026.
This experiment does the FULL decomposition + HAR-OC model + unified
comparison.

Part A: Verify return decomposition & compute variance shares
Part B: Time-varying overnight fraction (rolling 252-day)
Part C: HAR-OC model (HAR + overnight component)
Part D: Unified model comparison (all predict same target: σ²_cc)
         - GJR-GARCH, EWMA, HAR-RV², HAR-OC, AMEM (converted)

References:
  - Hansen, P.R. & Lunde, A. (2005) "A forecast comparison of volatility
    models: Does anything beat a GARCH(1,1)?" J.Applied Econometrics 20, 873-889
  - Corsi, F. (2009) "A Simple Approximate Long-Memory Model of Realized
    Volatility" J.Financial Econometrics 7, 174-196
  - Patton, A.J. (2011) "Volatility forecast comparison using imperfect
    volatility proxies" J.Econometrics 160, 246-256
  - Engle, R.F. & Gallo, G.M. (2006) "A multiple indicators model for
    volatility using intra-daily data" J.Econometrics 131, 3-27

Data: SPY OHLC from yfinance, 2007-01-03 to 2026-03-30
Metrics: QLIKE (primary), MSE, Diebold-Mariano test, Harvey t>3.0
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import norm
from datetime import datetime, timezone
from numba import njit
import warnings
import os
import sys
import time

warnings.filterwarnings('ignore')

RESULTS_PATH = 'experiments/k772_overnight_vol_results.json'

# ============================================================
# Data Loading & Return Decomposition
# ============================================================

def load_spy_ohlc():
    """Load SPY OHLC data from yfinance."""
    print("Loading SPY OHLC data from yfinance...")
    spy = yf.download('SPY', start='2006-06-01', end='2026-04-01', auto_adjust=True, progress=False)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.droplevel(1)
    spy = spy[['Open', 'High', 'Low', 'Close']].dropna()
    print(f"  SPY raw: {len(spy)} rows, {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
    return spy


def decompose_returns(df):
    """
    Decompose close-to-close returns into overnight + intraday.
    r_total_t     = log(Close_t / Close_{t-1})
    r_overnight_t = log(Open_t  / Close_{t-1})
    r_intraday_t  = log(Close_t / Open_t)

    Verify: r_total = r_overnight + r_intraday (to machine precision)
    """
    close = df['Close'].values
    opn = df['Open'].values

    # Total return
    r_total = np.log(close[1:] / close[:-1])
    # Overnight return: from previous close to today's open
    r_overnight = np.log(opn[1:] / close[:-1])
    # Intraday return: from today's open to today's close
    r_intraday = np.log(close[1:] / opn[1:])

    # Verify decomposition
    decomp_error = np.max(np.abs(r_total - (r_overnight + r_intraday)))
    assert decomp_error < 1e-12, f"Decomposition error: {decomp_error}"

    dates = df.index[1:]
    result = pd.DataFrame({
        'r_total': r_total,
        'r_overnight': r_overnight,
        'r_intraday': r_intraday,
        'r2_total': r_total**2,
        'r2_overnight': r_overnight**2,
        'r2_intraday': r_intraday**2,
    }, index=dates)

    return result


# ============================================================
# Part A: Variance Decomposition Statistics
# ============================================================

def variance_decomposition(ret_df, start_date='2007-01-03'):
    """
    σ²_total = σ²_overnight + σ²_intraday + 2×cov(overnight, intraday)
    What fraction is overnight?
    """
    df = ret_df.loc[start_date:]
    n = len(df)

    r_on = df['r_overnight'].values
    r_id = df['r_intraday'].values
    r_tot = df['r_total'].values

    var_total = np.var(r_tot, ddof=1)
    var_overnight = np.var(r_on, ddof=1)
    var_intraday = np.var(r_id, ddof=1)
    cov_on_id = np.cov(r_on, r_id)[0, 1]
    corr_on_id = np.corrcoef(r_on, r_id)[0, 1]

    # Verify: var_total ≈ var_overnight + var_intraday + 2*cov
    var_sum = var_overnight + var_intraday + 2 * cov_on_id
    var_check_error = abs(var_total - var_sum) / var_total

    # Shares
    overnight_share = var_overnight / var_total
    intraday_share = var_intraday / var_total
    covariance_share = 2 * cov_on_id / var_total

    print("\n" + "="*60)
    print("Part A: Variance Decomposition (Full Sample)")
    print("="*60)
    print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  N obs: {n}")
    print(f"  σ²_total     = {var_total:.8f}  (annualized σ = {np.sqrt(var_total*252)*100:.1f}%)")
    print(f"  σ²_overnight = {var_overnight:.8f}  ({overnight_share*100:.1f}% of total)")
    print(f"  σ²_intraday  = {var_intraday:.8f}  ({intraday_share*100:.1f}% of total)")
    print(f"  2×cov        = {2*cov_on_id:.8f}  ({covariance_share*100:.1f}% of total)")
    print(f"  Decomp check: {var_check_error*100:.6f}% error")
    print(f"  Corr(overnight, intraday) = {corr_on_id:.4f}")
    print(f"  Hansen & Lunde (2005) benchmark: ~20% overnight")
    print(f"  Our finding: {overnight_share*100:.1f}% overnight")

    # Descriptive statistics for each component
    stats = {}
    for name, arr in [('total', r_tot), ('overnight', r_on), ('intraday', r_id)]:
        stats[name] = {
            'mean': float(np.mean(arr)),
            'std': float(np.std(arr, ddof=1)),
            'skew': float(pd.Series(arr).skew()),
            'kurtosis': float(pd.Series(arr).kurtosis()),
            'min': float(np.min(arr)),
            'max': float(np.max(arr)),
            'mean_abs': float(np.mean(np.abs(arr))),
        }

    return {
        'n': n,
        'date_range': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        'var_total': float(var_total),
        'var_overnight': float(var_overnight),
        'var_intraday': float(var_intraday),
        'cov_overnight_intraday': float(cov_on_id),
        'corr_overnight_intraday': float(corr_on_id),
        'overnight_share': float(overnight_share),
        'intraday_share': float(intraday_share),
        'covariance_share': float(covariance_share),
        'decomp_check_error': float(var_check_error),
        'annualized_vol_total': float(np.sqrt(var_total * 252)),
        'annualized_vol_overnight': float(np.sqrt(var_overnight * 252)),
        'annualized_vol_intraday': float(np.sqrt(var_intraday * 252)),
        'descriptive_stats': stats,
    }


# ============================================================
# Part B: Time-varying Overnight Fraction
# ============================================================

def rolling_overnight_fraction(ret_df, window=252, start_date='2007-01-03'):
    """
    Compute rolling overnight variance fraction over time.
    Is it stable or regime-dependent?
    """
    df = ret_df.loc[start_date:]
    n = len(df)

    r_on = df['r_overnight'].values
    r_id = df['r_intraday'].values
    r_tot = df['r_total'].values
    dates = df.index

    on_frac = np.full(n, np.nan)
    for t in range(window, n):
        v_tot = np.var(r_tot[t-window:t], ddof=1)
        v_on = np.var(r_on[t-window:t], ddof=1)
        if v_tot > 0:
            on_frac[t] = v_on / v_tot

    valid = ~np.isnan(on_frac)
    fracs = on_frac[valid]

    # Regime analysis: separate by VIX or total vol level
    # Use rolling vol as proxy for regime
    rolling_vol = pd.Series(r_tot).rolling(window).std().values

    # Define regimes by vol quartiles
    vol_valid = rolling_vol[valid]
    frac_valid = fracs
    q25, q75 = np.percentile(vol_valid, [25, 75])

    low_vol_mask = vol_valid <= q25
    mid_vol_mask = (vol_valid > q25) & (vol_valid <= q75)
    high_vol_mask = vol_valid > q75

    regime_stats = {
        'low_vol': {
            'mean_overnight_share': float(np.mean(frac_valid[low_vol_mask])),
            'std_overnight_share': float(np.std(frac_valid[low_vol_mask])),
            'n': int(low_vol_mask.sum()),
        },
        'mid_vol': {
            'mean_overnight_share': float(np.mean(frac_valid[mid_vol_mask])),
            'std_overnight_share': float(np.std(frac_valid[mid_vol_mask])),
            'n': int(mid_vol_mask.sum()),
        },
        'high_vol': {
            'mean_overnight_share': float(np.mean(frac_valid[high_vol_mask])),
            'std_overnight_share': float(np.std(frac_valid[high_vol_mask])),
            'n': int(high_vol_mask.sum()),
        },
    }

    # Year-by-year breakdown
    yearly = {}
    for yr in range(2008, 2027):
        mask = [d.year == yr for d in dates]
        mask = np.array(mask) & valid
        if mask.sum() > 0:
            yearly[str(yr)] = float(np.mean(on_frac[mask]))

    print("\n" + "="*60)
    print("Part B: Time-varying Overnight Fraction")
    print("="*60)
    print(f"  Rolling window: {window} days")
    print(f"  Mean overnight fraction: {np.mean(fracs):.3f}")
    print(f"  Std overnight fraction:  {np.std(fracs):.3f}")
    print(f"  Min: {np.min(fracs):.3f}, Max: {np.max(fracs):.3f}")
    print(f"\n  By regime:")
    for regime, stats in regime_stats.items():
        print(f"    {regime}: overnight = {stats['mean_overnight_share']:.3f} ± {stats['std_overnight_share']:.3f} (n={stats['n']})")
    print(f"\n  By year:")
    for yr, frac in yearly.items():
        print(f"    {yr}: {frac:.3f}")

    return {
        'window': window,
        'mean_overnight_fraction': float(np.mean(fracs)),
        'std_overnight_fraction': float(np.std(fracs)),
        'min_overnight_fraction': float(np.min(fracs)),
        'max_overnight_fraction': float(np.max(fracs)),
        'regime_stats': regime_stats,
        'yearly': yearly,
    }


# ============================================================
# Model Implementations
# ============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1) variance filter. Returns σ² array."""
    T = len(r)
    sigma2 = np.zeros(T)
    var_r = 0.0
    for i in range(T):
        var_r += r[i]**2
    var_r /= T
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if r[t-1] < 0 else 0.0
        sigma2[t] = omega + (alpha + gamma * ind) * r[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-12:
            sigma2[t] = 1e-12
    return sigma2


@njit(cache=True)
def amem_filter(x, r, omega, alpha, beta, gamma_lev):
    """
    AMEM(1,1) with leverage:
        μ_t = ω + (α + γ × I_{r<0}) × x_{t-1} + β × μ_{t-1}
    x: |r_t|, r: raw returns
    """
    T = len(x)
    mu = np.zeros(T)
    mu[0] = x[0] if x[0] > 0 else 0.01
    for t in range(1, T):
        indicator = 1.0 if r[t-1] < 0 else 0.0
        mu[t] = omega + (alpha + gamma_lev * indicator) * x[t-1] + beta * mu[t-1]
        if mu[t] < 1e-10:
            mu[t] = 1e-10
    return mu


def amem_negloglik(params, x, r):
    """Gamma MLE for AMEM."""
    omega, alpha, beta, gamma_lev, k = params
    if omega <= 0 or alpha < 0 or beta < 0 or gamma_lev < 0 or k <= 0:
        return 1e10
    if alpha + beta + 0.5 * gamma_lev >= 1.0:
        return 1e10
    mu = amem_filter(x, r, omega, alpha, beta, gamma_lev)
    x_trim = x[1:]
    mu_trim = mu[1:]
    valid = (mu_trim > 1e-10) & (x_trim > 0)
    if valid.sum() < 10:
        return 1e10
    x_v = x_trim[valid]
    mu_v = mu_trim[valid]
    ll = (k * np.log(k / mu_v) + (k - 1) * np.log(x_v)
          - k * x_v / mu_v - gammaln(k))
    total_ll = np.sum(ll)
    if not np.isfinite(total_ll):
        return 1e10
    return -total_ll


def fit_amem(x, r, max_attempts=3):
    """Fit AMEM via Gamma MLE with multiple restarts."""
    x = np.ascontiguousarray(x, dtype=np.float64)
    r = np.ascontiguousarray(r, dtype=np.float64)
    x_mean = np.mean(x[x > 0]) if np.any(x > 0) else 0.01
    best_result = None
    best_nll = 1e10

    for attempt in range(max_attempts):
        np.random.seed(42 + attempt)
        omega0 = x_mean * 0.05 * (1 + 0.2 * np.random.randn())
        alpha0 = 0.05 + 0.03 * np.random.randn()
        beta0 = 0.85 + 0.05 * np.random.randn()
        gamma0 = 0.1 + 0.05 * np.random.randn()
        k0 = 2.0 + np.random.rand()
        alpha0 = max(0.01, min(alpha0, 0.4))
        beta0 = max(0.3, min(beta0, 0.95))
        gamma0 = max(0.01, min(gamma0, 0.4))
        if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
            beta0 = 0.97 - alpha0 - 0.5 * gamma0
        p0 = [max(1e-6, omega0), alpha0, beta0, max(0.01, gamma0), max(0.5, k0)]
        bounds = [(1e-8, None), (0, 0.9), (0, 0.99), (0, 0.9), (0.1, 100)]
        result = minimize(amem_negloglik, p0, args=(x, r),
                         method='L-BFGS-B', bounds=bounds,
                         options={'maxiter': 5000, 'ftol': 1e-10})
        if result.fun < best_nll:
            best_nll = result.fun
            best_result = result

    if best_result is None:
        return None
    res = best_result
    return {
        'params': {
            'omega': res.x[0], 'alpha': res.x[1], 'beta': res.x[2],
            'gamma': res.x[3], 'k': res.x[4],
            'persistence': res.x[1] + res.x[2] + 0.5 * res.x[3]
        },
        'converged': res.success,
        'nll': res.fun,
    }


def fit_gjr_garch(returns):
    """GJR-GARCH(1,1) via quasi-MLE. Forecast: σ²."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    T = len(r)
    if T < 50:
        return None

    def gjr_negll(params, r):
        omega, alpha, beta, gamma_lev = params
        if omega <= 0 or alpha < 0 or beta < 0 or gamma_lev < 0:
            return 1e10
        if alpha + beta + 0.5 * gamma_lev >= 1.0:
            return 1e10
        sigma2 = gjr_filter(r, omega, alpha, beta, gamma_lev)
        ll = -0.5 * np.sum(np.log(sigma2[1:]) + r[1:]**2 / sigma2[1:])
        return -ll if np.isfinite(ll) else 1e10

    rv = np.var(r)
    best = None
    best_nll = 1e10
    for seed in range(3):
        np.random.seed(seed + 100)
        omega0 = rv * 0.05 * (1 + 0.2 * np.random.randn())
        alpha0 = 0.05 + 0.03 * np.random.randn()
        beta0 = 0.90 + 0.03 * np.random.randn()
        gamma0 = 0.08 + 0.04 * np.random.randn()
        alpha0 = max(0.01, min(alpha0, 0.3))
        beta0 = max(0.5, min(beta0, 0.98))
        gamma0 = max(0.01, min(gamma0, 0.3))
        if alpha0 + beta0 + 0.5 * gamma0 >= 0.99:
            beta0 = 0.98 - alpha0 - 0.5 * gamma0
        p0 = [max(1e-8, omega0), alpha0, beta0, gamma0]
        bounds = [(1e-10, None), (0, 0.5), (0, 0.999), (0, 0.5)]
        res = minimize(gjr_negll, p0, args=(r,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 5000, 'ftol': 1e-10})
        if res.fun < best_nll:
            best_nll = res.fun
            best = res

    if best is None:
        return None
    return {
        'params': {
            'omega': best.x[0], 'alpha': best.x[1],
            'beta': best.x[2], 'gamma': best.x[3],
            'persistence': best.x[1] + best.x[2] + 0.5 * best.x[3]
        },
        'converged': best.success,
        'nll': best.fun,
    }


# ============================================================
# HAR-RV² (predicts variance, not |r|)
# ============================================================

def fit_har_rv2(r2_series):
    """
    HAR-RV² regression (daily r² as proxy for daily RV):
    r²_{t+1} = β₀ + β₁ × r²_t + β₂ × MA5_t(r²) + β₃ × MA22_t(r²)
    """
    x = r2_series.copy()
    n = len(x)
    if n < 30:
        return None
    ma5 = pd.Series(x).rolling(5).mean().values
    ma22 = pd.Series(x).rolling(22).mean().values
    valid_start = 22
    if n <= valid_start + 30:
        return None
    idx = np.arange(valid_start, n - 1)  # predict t+1
    Y = x[idx + 1]
    X = np.column_stack([
        np.ones(len(idx)),
        x[idx],
        ma5[idx],
        ma22[idx]
    ])
    valid_rows = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if valid_rows.sum() < 30:
        return None
    Y = Y[valid_rows]
    X = X[valid_rows]
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return None
    return beta


def har_rv2_forecast(r2_recent, beta):
    """One-step-ahead HAR-RV² forecast."""
    n = len(r2_recent)
    if n < 22:
        return None
    lag1 = r2_recent[-1]
    ma5 = np.mean(r2_recent[-5:])
    ma22 = np.mean(r2_recent[-22:])
    pred = beta[0] + beta[1] * lag1 + beta[2] * ma5 + beta[3] * ma22
    return max(pred, 1e-12)


# ============================================================
# Part C: HAR-OC (HAR + Overnight Component)
# ============================================================

def fit_har_oc(r2_total, r2_overnight, r2_intraday):
    """
    HAR-OC:
    r²_cc_{t+1} = β₀ + β₁ × r²_intraday_t + β₂ × MA5_t(r²_cc)
                 + β₃ × MA22_t(r²_cc) + β₄ × r²_overnight_t

    Separates overnight from intraday in the daily component.
    """
    n = len(r2_total)
    if n < 30:
        return None
    ma5 = pd.Series(r2_total).rolling(5).mean().values
    ma22 = pd.Series(r2_total).rolling(22).mean().values
    valid_start = 22
    if n <= valid_start + 30:
        return None
    idx = np.arange(valid_start, n - 1)
    Y = r2_total[idx + 1]
    X = np.column_stack([
        np.ones(len(idx)),
        r2_intraday[idx],      # β₁: intraday component
        ma5[idx],              # β₂: weekly average (close-to-close)
        ma22[idx],             # β₃: monthly average (close-to-close)
        r2_overnight[idx],     # β₄: overnight component
    ])
    valid_rows = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if valid_rows.sum() < 30:
        return None
    Y = Y[valid_rows]
    X = X[valid_rows]
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return None
    return beta


def har_oc_forecast(r2_total_recent, r2_overnight_recent, r2_intraday_recent, beta):
    """One-step-ahead HAR-OC forecast (predicts σ²_cc)."""
    n = len(r2_total_recent)
    if n < 22:
        return None
    r2_id = r2_intraday_recent[-1]
    r2_on = r2_overnight_recent[-1]
    ma5 = np.mean(r2_total_recent[-5:])
    ma22 = np.mean(r2_total_recent[-22:])
    pred = beta[0] + beta[1] * r2_id + beta[2] * ma5 + beta[3] * ma22 + beta[4] * r2_on
    return max(pred, 1e-12)


# ============================================================
# HAR-OC-Ext: HAR-OC with weekly/monthly overnight averages
# ============================================================

def fit_har_oc_ext(r2_total, r2_overnight, r2_intraday):
    """
    HAR-OC-Extended:
    r²_cc_{t+1} = β₀ + β₁ × r²_intraday_t + β₂ × MA5_t(r²_intraday)
                 + β₃ × MA22_t(r²_cc) + β₄ × r²_overnight_t
                 + β₅ × MA5_t(r²_overnight)
    """
    n = len(r2_total)
    if n < 30:
        return None
    ma5_total = pd.Series(r2_total).rolling(5).mean().values
    ma22_total = pd.Series(r2_total).rolling(22).mean().values
    ma5_on = pd.Series(r2_overnight).rolling(5).mean().values
    ma5_id = pd.Series(r2_intraday).rolling(5).mean().values
    valid_start = 22
    if n <= valid_start + 30:
        return None
    idx = np.arange(valid_start, n - 1)
    Y = r2_total[idx + 1]
    X = np.column_stack([
        np.ones(len(idx)),
        r2_intraday[idx],
        ma5_id[idx],
        ma22_total[idx],
        r2_overnight[idx],
        ma5_on[idx],
    ])
    valid_rows = ~(np.isnan(X).any(axis=1) | np.isnan(Y))
    if valid_rows.sum() < 30:
        return None
    Y = Y[valid_rows]
    X = X[valid_rows]
    try:
        beta = np.linalg.lstsq(X, Y, rcond=None)[0]
    except Exception:
        return None
    return beta


def har_oc_ext_forecast(r2_total_recent, r2_overnight_recent, r2_intraday_recent, beta):
    """One-step-ahead HAR-OC-Ext forecast."""
    n = len(r2_total_recent)
    if n < 22:
        return None
    r2_id = r2_intraday_recent[-1]
    r2_on = r2_overnight_recent[-1]
    ma5_id = np.mean(r2_intraday_recent[-5:])
    ma5_on = np.mean(r2_overnight_recent[-5:])
    ma22_total = np.mean(r2_total_recent[-22:])
    pred = (beta[0] + beta[1] * r2_id + beta[2] * ma5_id
            + beta[3] * ma22_total + beta[4] * r2_on + beta[5] * ma5_on)
    return max(pred, 1e-12)


# ============================================================
# EWMA baseline
# ============================================================

def ewma_forecast(returns, lam=0.94):
    """EWMA variance forecast (RiskMetrics). Forecast: σ²."""
    r = returns
    n = len(r)
    sigma2 = np.zeros(n)
    sigma2[0] = np.var(r[:min(22, n)])
    for t in range(1, n):
        sigma2[t] = lam * sigma2[t-1] + (1 - lam) * r[t-1]**2
    return sigma2


# ============================================================
# Evaluation Metrics
# ============================================================

def qlike(actual_r2, forecast_sigma2):
    """QLIKE loss: L = r²/σ² - log(r²/σ²) - 1. Lower is better."""
    valid = (forecast_sigma2 > 1e-15) & (actual_r2 > 0) & np.isfinite(actual_r2) & np.isfinite(forecast_sigma2)
    r2 = actual_r2[valid]
    s2 = forecast_sigma2[valid]
    losses = r2 / s2 - np.log(r2 / s2) - 1.0
    return float(np.mean(losses)), losses


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. Negative stat means model 1 is better."""
    d = loss1 - loss2
    n = len(d)
    if n < 10:
        return 0, 1.0
    dbar = np.mean(d)
    # Newey-West variance with h-1 lags
    gamma0 = np.var(d, ddof=1)
    autocovar = 0
    for k in range(1, h):
        if k < n:
            autocovar += np.sum(d[k:] * d[:-k]) / n
    var_dbar = (gamma0 + 2 * autocovar) / n
    if var_dbar <= 0:
        var_dbar = gamma0 / n
    dm_stat = dbar / np.sqrt(var_dbar)
    # Harvey small-sample correction
    harvey_stat = dm_stat * np.sqrt((n + 1 - 2*h + h*(h-1)/n) / n)
    p_val = 2 * (1 - norm.cdf(abs(harvey_stat)))
    return float(harvey_stat), float(p_val)


# ============================================================
# Part C + D: Expanding Window Forecasting
# ============================================================

PI_OVER_2 = np.pi / 2.0

def run_expanding_window(ret_df, min_window=1000, refit_every=63, start_date='2007-01-03'):
    """
    Expanding window forecast comparison.
    All models predict the SAME target: r²_{t+1} (close-to-close squared return)

    Models:
    1. GJR-GARCH(1,1): forecasts σ² directly
    2. EWMA(0.94): forecasts σ² directly
    3. HAR-RV²: OLS on r²_d, MA5(r²), MA22(r²)
    4. HAR-OC: HAR + overnight squared return
    5. HAR-OC-Ext: HAR-OC + weekly overnight average + weekly intraday
    6. AMEM: forecasts E[|r|], convert via E[|r|]² × π/2
    """
    df = ret_df.loc[start_date:]
    r_total = df['r_total'].values
    r2_total = df['r2_total'].values
    r_overnight = df['r_overnight'].values
    r2_overnight = df['r2_overnight'].values
    r_intraday = df['r_intraday'].values
    r2_intraday = df['r2_intraday'].values
    abs_r = np.abs(r_total)
    n = len(df)

    print(f"\n" + "="*60)
    print(f"Parts C+D: Expanding Window Forecasting")
    print(f"="*60)
    print(f"  Total obs: {n}, min window: {min_window}")
    print(f"  Refit every: {refit_every} obs")
    print(f"  OOS start: ~obs {min_window}")

    # Storage
    n_oos = n - min_window - 1
    if n_oos < 100:
        print("  ERROR: Not enough OOS observations!")
        return None

    forecasts = {
        'gjr': np.full(n_oos, np.nan),
        'ewma': np.full(n_oos, np.nan),
        'har_rv2': np.full(n_oos, np.nan),
        'har_oc': np.full(n_oos, np.nan),
        'har_oc_ext': np.full(n_oos, np.nan),
        'amem': np.full(n_oos, np.nan),
    }
    actual = np.full(n_oos, np.nan)

    # Cached model params
    gjr_params = None
    har_rv2_beta = None
    har_oc_beta = None
    har_oc_ext_beta = None
    amem_params = None
    last_refit = -refit_every  # force refit at start

    t0 = time.time()
    n_refits = 0

    for i in range(n_oos):
        t = min_window + i  # current time index

        # Actual: r²_{t+1}
        actual[i] = r2_total[t + 1]

        # Refit models periodically
        if i - last_refit >= refit_every:
            # GJR-GARCH
            gjr_result = fit_gjr_garch(r_total[:t+1])
            if gjr_result and gjr_result['converged']:
                gjr_params = gjr_result['params']

            # HAR-RV²
            har_rv2_beta = fit_har_rv2(r2_total[:t+1])

            # HAR-OC
            har_oc_beta = fit_har_oc(r2_total[:t+1], r2_overnight[:t+1], r2_intraday[:t+1])

            # HAR-OC-Ext
            har_oc_ext_beta = fit_har_oc_ext(r2_total[:t+1], r2_overnight[:t+1], r2_intraday[:t+1])

            # AMEM
            amem_result = fit_amem(abs_r[:t+1], r_total[:t+1], max_attempts=2)
            if amem_result and amem_result['converged']:
                amem_params = amem_result['params']

            last_refit = i
            n_refits += 1
            if n_refits % 10 == 0:
                elapsed = time.time() - t0
                print(f"  Refit #{n_refits} at obs {t}/{n}, elapsed {elapsed:.1f}s")

        # === Generate forecasts for t+1 ===

        # 1. GJR-GARCH: one-step-ahead σ²
        if gjr_params is not None:
            s2 = gjr_filter(r_total[:t+1], gjr_params['omega'], gjr_params['alpha'],
                           gjr_params['beta'], gjr_params['gamma'])
            # forecast for t+1
            ind = 1.0 if r_total[t] < 0 else 0.0
            sigma2_next = (gjr_params['omega'] +
                          (gjr_params['alpha'] + gjr_params['gamma'] * ind) * r_total[t]**2 +
                          gjr_params['beta'] * s2[-1])
            forecasts['gjr'][i] = max(sigma2_next, 1e-12)

        # 2. EWMA
        s2_ewma = ewma_forecast(r_total[:t+1])
        # EWMA forecast for t+1
        sigma2_ewma_next = 0.94 * s2_ewma[-1] + 0.06 * r_total[t]**2
        forecasts['ewma'][i] = max(sigma2_ewma_next, 1e-12)

        # 3. HAR-RV²
        if har_rv2_beta is not None and t >= 22:
            pred = har_rv2_forecast(r2_total[:t+1], har_rv2_beta)
            if pred is not None:
                forecasts['har_rv2'][i] = pred

        # 4. HAR-OC
        if har_oc_beta is not None and t >= 22:
            pred = har_oc_forecast(r2_total[:t+1], r2_overnight[:t+1], r2_intraday[:t+1], har_oc_beta)
            if pred is not None:
                forecasts['har_oc'][i] = pred

        # 5. HAR-OC-Ext
        if har_oc_ext_beta is not None and t >= 22:
            pred = har_oc_ext_forecast(r2_total[:t+1], r2_overnight[:t+1], r2_intraday[:t+1], har_oc_ext_beta)
            if pred is not None:
                forecasts['har_oc_ext'][i] = pred

        # 6. AMEM: convert E[|r|] → σ² via squaring × π/2
        if amem_params is not None:
            mu = amem_filter(abs_r[:t+1], r_total[:t+1], amem_params['omega'],
                            amem_params['alpha'], amem_params['beta'], amem_params['gamma'])
            # One-step-ahead: μ_{t+1}
            ind = 1.0 if r_total[t] < 0 else 0.0
            mu_next = (amem_params['omega'] +
                      (amem_params['alpha'] + amem_params['gamma'] * ind) * abs_r[t] +
                      amem_params['beta'] * mu[-1])
            # Convert: E[|r|]² × π/2 = σ² (under Normality)
            sigma2_amem = mu_next**2 * PI_OVER_2
            forecasts['amem'][i] = max(sigma2_amem, 1e-12)

    elapsed = time.time() - t0
    print(f"  Completed in {elapsed:.1f}s ({n_refits} refits)")

    return actual, forecasts, df.index[min_window+1:].tolist()


def evaluate_forecasts(actual, forecasts):
    """Compute QLIKE, MSE, and all pairwise DM tests."""
    results = {}
    losses = {}

    # Compute QLIKE for each model
    print("\n" + "="*60)
    print("Part D: Unified Model Comparison (target = r²_cc)")
    print("="*60)

    for name, fcast in forecasts.items():
        valid = np.isfinite(fcast) & np.isfinite(actual) & (actual > 0) & (fcast > 1e-15)
        n_valid = valid.sum()
        if n_valid < 100:
            print(f"  {name}: SKIP (only {n_valid} valid forecasts)")
            continue
        q, ql = qlike(actual[valid], fcast[valid])
        mse = float(np.mean((actual[valid] - fcast[valid])**2))
        results[name] = {
            'qlike': q,
            'mse': mse,
            'n_valid': int(n_valid),
        }
        losses[name] = ql  # store individual losses for DM test
        print(f"  {name:15s}: QLIKE = {q:.6f}  MSE = {mse:.2e}  (n={n_valid})")

    # Ranking
    ranking = sorted(results.keys(), key=lambda x: results[x]['qlike'])
    print(f"\n  QLIKE Ranking: {' > '.join(ranking)} (lower is better)")
    print(f"  Best: {ranking[0]} ({results[ranking[0]]['qlike']:.6f})")

    # Pairwise DM tests
    model_names = list(results.keys())
    dm_results = {}
    print(f"\n  Diebold-Mariano Tests (Harvey-corrected):")
    print(f"  {'Comparison':35s} {'DM-stat':>10s} {'p-value':>10s} {'|t|>3':>8s} {'Better':>10s}")
    print(f"  {'-'*75}")

    for i in range(len(model_names)):
        for j in range(i+1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            # Align losses on common valid indices
            v1 = np.isfinite(forecasts[m1]) & np.isfinite(actual) & (actual > 0) & (forecasts[m1] > 1e-15)
            v2 = np.isfinite(forecasts[m2]) & np.isfinite(actual) & (actual > 0) & (forecasts[m2] > 1e-15)
            common = v1 & v2
            if common.sum() < 100:
                continue
            _, ql1 = qlike(actual[common], forecasts[m1][common])
            _, ql2 = qlike(actual[common], forecasts[m2][common])
            stat, pval = dm_test(ql1, ql2, h=1)
            better = m1 if stat < 0 else m2
            harvey_pass = abs(stat) > 3.0
            key = f"{m1}_vs_{m2}"
            dm_results[key] = {
                'dm_stat': stat,
                'p_value': pval,
                'harvey_pass': harvey_pass,
                'better': better,
                'n_common': int(common.sum()),
            }
            marker = "***" if harvey_pass else ("**" if pval < 0.01 else ("*" if pval < 0.05 else ""))
            print(f"  {m1} vs {m2:20s} {stat:10.3f} {pval:10.6f} {'YES' if harvey_pass else 'no':>8s} {better:>10s} {marker}")

    return {
        'metrics': results,
        'ranking': ranking,
        'dm_tests': dm_results,
    }


# ============================================================
# Part C-extra: HAR-OC Beta Analysis
# ============================================================

def har_oc_beta_analysis(ret_df, start_date='2007-01-03'):
    """
    Full-sample HAR-OC regression to examine overnight coefficient significance.
    Uses statsmodels for proper t-stats.
    """
    df = ret_df.loc[start_date:]
    r2_total = df['r2_total'].values
    r2_overnight = df['r2_overnight'].values
    r2_intraday = df['r2_intraday'].values
    n = len(df)

    ma5 = pd.Series(r2_total).rolling(5).mean().values
    ma22 = pd.Series(r2_total).rolling(22).mean().values

    valid_start = 22
    idx = np.arange(valid_start, n - 1)
    Y = r2_total[idx + 1]

    # HAR-RV² (baseline)
    X_har = np.column_stack([
        np.ones(len(idx)),
        r2_total[idx],
        ma5[idx],
        ma22[idx]
    ])

    # HAR-OC
    X_oc = np.column_stack([
        np.ones(len(idx)),
        r2_intraday[idx],
        ma5[idx],
        ma22[idx],
        r2_overnight[idx],
    ])

    valid_har = ~(np.isnan(X_har).any(axis=1) | np.isnan(Y))
    valid_oc = ~(np.isnan(X_oc).any(axis=1) | np.isnan(Y))

    # OLS with HAC standard errors (manual Newey-West)
    def ols_with_hac(X, Y, valid_mask, max_lag=10):
        X_v = X[valid_mask]
        Y_v = Y[valid_mask]
        n_v = len(Y_v)
        beta = np.linalg.lstsq(X_v, Y_v, rcond=None)[0]
        resid = Y_v - X_v @ beta
        # R²
        ss_res = np.sum(resid**2)
        ss_tot = np.sum((Y_v - np.mean(Y_v))**2)
        r2 = 1 - ss_res / ss_tot
        adj_r2 = 1 - (1 - r2) * (n_v - 1) / (n_v - X_v.shape[1] - 1)
        # Newey-West HAC
        k = X_v.shape[1]
        S = np.zeros((k, k))
        for l in range(max_lag + 1):
            if l == 0:
                Gl = X_v.T @ np.diag(resid**2) @ X_v
            else:
                w = 1 - l / (max_lag + 1)
                Gl = np.zeros((k, k))
                for t in range(l, n_v):
                    Gl += resid[t] * resid[t-l] * np.outer(X_v[t], X_v[t-l])
                Gl = w * (Gl + Gl.T)
            S += Gl
        S /= n_v
        XtX_inv = np.linalg.inv(X_v.T @ X_v / n_v)
        V = XtX_inv @ S @ XtX_inv / n_v
        se = np.sqrt(np.diag(V))
        t_stats = beta / se
        return {
            'beta': beta.tolist(),
            'se': se.tolist(),
            't_stats': t_stats.tolist(),
            'r2': float(r2),
            'adj_r2': float(adj_r2),
            'n': int(n_v),
        }

    print("\n" + "="*60)
    print("Part C: HAR-OC Regression Analysis")
    print("="*60)

    har_result = ols_with_hac(X_har, Y, valid_har)
    oc_result = ols_with_hac(X_oc, Y, valid_oc)

    print(f"\n  HAR-RV² (baseline):")
    print(f"    r²_{'{'}t+1{'}'} = β₀ + β₁ × r²_t + β₂ × MA5(r²) + β₃ × MA22(r²)")
    labels_har = ['const', 'r²_daily', 'MA5(r²)', 'MA22(r²)']
    for lbl, b, se, t in zip(labels_har, har_result['beta'], har_result['se'], har_result['t_stats']):
        sig = '***' if abs(t) > 3.0 else ('**' if abs(t) > 2.0 else ('*' if abs(t) > 1.65 else ''))
        print(f"    {lbl:15s}: β={b:10.6f}, SE={se:10.6f}, t={t:7.2f} {sig}")
    print(f"    R² = {har_result['r2']:.4f}, Adj.R² = {har_result['adj_r2']:.4f}, n = {har_result['n']}")

    print(f"\n  HAR-OC (with overnight):")
    print(f"    r²_{'{'}t+1{'}'} = β₀ + β₁ × r²_intraday_t + β₂ × MA5(r²) + β₃ × MA22(r²) + β₄ × r²_overnight_t")
    labels_oc = ['const', 'r²_intraday', 'MA5(r²)', 'MA22(r²)', 'r²_overnight']
    for lbl, b, se, t in zip(labels_oc, oc_result['beta'], oc_result['se'], oc_result['t_stats']):
        sig = '***' if abs(t) > 3.0 else ('**' if abs(t) > 2.0 else ('*' if abs(t) > 1.65 else ''))
        print(f"    {lbl:15s}: β={b:10.6f}, SE={se:10.6f}, t={t:7.2f} {sig}")
    print(f"    R² = {oc_result['r2']:.4f}, Adj.R² = {oc_result['adj_r2']:.4f}, n = {oc_result['n']}")

    r2_improvement = oc_result['adj_r2'] - har_result['adj_r2']
    print(f"\n  R² improvement from overnight: {r2_improvement:.4f} ({r2_improvement/har_result['adj_r2']*100:.2f}%)")
    overnight_t = oc_result['t_stats'][4]
    print(f"  Overnight t-stat: {overnight_t:.2f} (Harvey threshold: |t|>3.0)")

    return {
        'har_rv2': har_result,
        'har_oc': oc_result,
        'r2_improvement': float(r2_improvement),
        'overnight_t_stat': float(overnight_t),
        'overnight_significant_harvey': abs(overnight_t) > 3.0,
    }


# ============================================================
# Main
# ============================================================

def main():
    print("K772: Overnight Volatility Component — Hansen & Lunde (2005)")
    print("=" * 70)
    t_start = time.time()

    # Load data
    spy = load_spy_ohlc()

    # Decompose returns
    ret_df = decompose_returns(spy)
    start_date = '2007-01-03'
    ret_df = ret_df.loc[start_date:]
    print(f"  Analysis period: {ret_df.index[0].strftime('%Y-%m-%d')} to {ret_df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  N: {len(ret_df)}")

    # Part A: Variance decomposition
    part_a = variance_decomposition(ret_df, start_date)

    # Part B: Time-varying overnight fraction
    part_b = rolling_overnight_fraction(ret_df, window=252, start_date=start_date)

    # Part C: HAR-OC beta analysis (full-sample regression)
    part_c = har_oc_beta_analysis(ret_df, start_date)

    # Part D: Expanding window forecast comparison
    actual, forecasts, oos_dates = run_expanding_window(ret_df, min_window=1000,
                                                         refit_every=63, start_date=start_date)

    part_d = evaluate_forecasts(actual, forecasts)

    # Add OOS date range
    oos_start = oos_dates[0].strftime('%Y-%m-%d') if oos_dates else 'N/A'
    oos_end = oos_dates[-1].strftime('%Y-%m-%d') if oos_dates else 'N/A'
    part_d['oos_range'] = f"{oos_start} to {oos_end}"
    part_d['n_oos'] = len(oos_dates)

    # Summary
    total_time = time.time() - t_start
    print(f"\n" + "="*70)
    print(f"SUMMARY — K772 Overnight Volatility Component")
    print(f"="*70)
    print(f"  Total runtime: {total_time:.1f}s")
    print(f"  OOS period: {oos_start} to {oos_end} (n={len(oos_dates)})")
    print(f"\n  Key Findings:")
    print(f"    1. Overnight variance share: {part_a['overnight_share']*100:.1f}% (Hansen & Lunde: ~20%)")
    print(f"    2. Corr(overnight, intraday): {part_a['corr_overnight_intraday']:.4f}")
    print(f"    3. Overnight t-stat in HAR-OC: {part_c['overnight_t_stat']:.2f} (Harvey: {'PASS' if part_c['overnight_significant_harvey'] else 'FAIL'})")
    print(f"    4. R² improvement: {part_c['r2_improvement']:.4f}")
    print(f"    5. QLIKE ranking: {' > '.join(part_d['ranking'])}")

    # Key question: Does HAR-OC beat HAR-RV²?
    har_oc_key = None
    for key, val in part_d['dm_tests'].items():
        if 'har_rv2' in key and 'har_oc' in key and 'ext' not in key:
            har_oc_key = key
            break
    if har_oc_key:
        dm = part_d['dm_tests'][har_oc_key]
        print(f"\n  HAR-OC vs HAR-RV²: DM={dm['dm_stat']:.3f}, p={dm['p_value']:.6f}, "
              f"Harvey: {'PASS' if dm['harvey_pass'] else 'FAIL'}, better: {dm['better']}")

    # Does anything beat GJR?
    for key, val in part_d['dm_tests'].items():
        if 'gjr' in key:
            print(f"  {key}: DM={val['dm_stat']:.3f}, p={val['p_value']:.6f}, better: {val['better']}")

    # Save results
    results = {
        'experiment_id': 'K772',
        'title': 'Overnight Volatility Component — Hansen & Lunde (2005) Decomposition',
        'proposer': '用戶',
        'executor': 'Claude',
        'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
        'data_source': 'yfinance (SPY OHLC)',
        'methodology': 'Return decomposition (overnight + intraday), expanding window '
                       '(min 1000 obs, refit every 63), QLIKE, DM test with Harvey correction.',
        'references': [
            'Hansen & Lunde (2005) J.Applied Econometrics 20, 873-889',
            'Corsi (2009) J.Financial Econometrics 7, 174-196',
            'Patton (2011) J.Econometrics 160, 246-256',
            'Engle & Gallo (2006) J.Econometrics 131, 3-27',
        ],
        'part_a_variance_decomposition': part_a,
        'part_b_time_varying': part_b,
        'part_c_har_oc_regression': part_c,
        'part_d_model_comparison': part_d,
        'runtime_seconds': float(total_time),
    }

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {RESULTS_PATH}")


if __name__ == '__main__':
    main()
