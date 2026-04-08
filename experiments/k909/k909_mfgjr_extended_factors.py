#!/usr/bin/env python3
"""
K909: MF-GJR with Extended Long-Run Factors
============================================
[提出: Claude, 執行: Claude]

K889v2 confirmed MF-GJR(VIX) beats GJR by -6.6% QLIKE for SPY. This experiment
tests whether a SECOND long-run factor can further improve the model:

  tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}) + theta_2 * X_{t-1})

Candidate factors:
  1. VIX Term Structure Slope = log(VIX3M / VIX)   — direction info
  2. Corwin-Schultz Bid-Ask Spread (from OHLC)      — liquidity / microstructure
  3. Parkinson Range = log(H/L)                      — intraday range

Key question: Does any factor provide Harvey PASS (|t|>3.0) incremental
improvement BEYOND VIX?

Background:
  - K889v2: MF-GJR(VIX) beats GJR by -6.6% QLIKE (SPY), DM t=-2.569
  - K862: Corwin-Schultz spread is the ONLY factor that broke VIX sufficiency
    (beyond VIX t=3.01 Harvey PASS)
  - K894: Multiplicative structure > additive (MF-GJR > GJR-X(VIX))

Error log rules applied:
  - DM test: use volpred.stats.model_evaluation.dm_test (not custom)
  - 0050.TW: must use clean_tw50_data
  - GARCH OOS: recursive h[t] = f(h[t-1], r^2[t-1])
  - VIX3M missing values: ffill
  - Sharpe > 2x baseline = almost certainly a bug

Data:
  - Assets: SPY, QQQ, 0050.TW
  - Period: 2005-01-01 to 2026-04-01
  - OOS: 2019-01-01 to latest
  - VIX, VIX3M from yfinance
  - 0050.TW: clean_tw50_data (mandatory)

Evaluation (Patton 2011 fair comparison):
  - QLIKE on r^2 (proxy-robust, unified target)
  - DM test vs MF-GJR(VIX) baseline (Harvey |t| > 3.0)
  - DM test vs GJR (for context)
  - MCS (Hansen-Lunde-Nason 2011)
  - Spearman rank correlation
  - IS vs OOS improvement comparison (overfitting check)

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Engle & Rangel (2008) RFS 21(3):1187-1222
  - Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104
  - Hansen, Lunde & Nason (2011) Econometrica 79(2):453-497
  - Corwin & Schultz (2012) J Finance 67(2):719-760
  - Parkinson (1980) J Business 53(1):61-65

Author: VolPred Research System
Date: 2026-04-06
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize
from scipy.stats import norm, chi2
from numba import njit

warnings.filterwarnings('ignore')

START_TIME = time.time()
EXPERIMENT_ID = "K909"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr
from volpred.stats.mcs import model_confidence_set

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k909_mfgjr_extended_factors_results.json')

# Data parameters (same as K889v2 for comparability)
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
ASSETS = ['SPY', 'QQQ', '0050.TW']

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR with Extended Long-Run Factors")
print("  Testing: VIX Term Structure Slope, Corwin-Schultz Spread, Parkinson Range")
print("=" * 70)

# ============================================================
# SECTION 1: HELPER FUNCTIONS — Factor Computation
# ============================================================

def corwin_schultz_spread(high, low):
    """Estimate bid-ask spread from OHLC data (Corwin & Schultz, 2012).

    S = 2(e^alpha - 1) / (1 + e^alpha)
    where alpha is derived from 1-day and 2-day high-low ratios.

    Returns spread array aligned with original index (first value is NaN).
    """
    high = np.asarray(high, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)

    # beta = sum of squared log(H/L) for consecutive days
    log_hl = np.log(high / low)
    beta = log_hl[:-1]**2 + log_hl[1:]**2

    # gamma = squared log of 2-day high-low ratio
    high_2d = np.maximum(high[:-1], high[1:])
    low_2d = np.minimum(low[:-1], low[1:])
    gamma = np.log(high_2d / low_2d)**2

    # alpha
    k = 3 - 2 * np.sqrt(2)
    alpha_num = np.sqrt(2 * beta) - np.sqrt(beta)
    alpha = (alpha_num / k) - np.sqrt(np.maximum(gamma / k, 0))

    # Spread = 2(e^alpha - 1) / (1 + e^alpha)
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))
    spread = np.maximum(spread, 0)  # spread >= 0

    # Align with original index (first value is NaN)
    return np.concatenate([[np.nan], spread])


def parkinson_range(high, low):
    """Parkinson (1980) range estimator: log(H/L).

    This is a simple measure of intraday price range.
    """
    return np.log(np.asarray(high, dtype=np.float64) /
                  np.asarray(low, dtype=np.float64))


# ============================================================
# SECTION 2: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf


def load_asset_data(ticker, vix_data, vix3m_data):
    """Load asset data with VIX, VIX3M, and computed factors."""
    print(f"  Loading {ticker}...")
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].copy()
    high = raw['High'].copy()
    low = raw['Low'].copy()
    log_ret = np.log(prices / prices.shift(1))

    # For 0050.TW: clean split artifacts
    if '0050' in ticker:
        prices, log_ret = clean_tw50_data(prices, log_ret)

    df = pd.DataFrame({
        'price': prices,
        'high': high,
        'low': low,
        'log_ret': log_ret
    })
    df = df.dropna(subset=['log_ret'])

    # Join VIX (no pre-shift — model handles lag internally)
    df = df.join(vix_data, how='left')
    df['VIX'] = df['VIX'].ffill()

    # Join VIX3M
    df = df.join(vix3m_data, how='left')
    df['VIX3M'] = df['VIX3M'].ffill()

    # Compute factors
    # Factor 1: VIX Term Structure Slope = log(VIX3M / VIX)
    # Positive = contango (calm), Negative = backwardation (panic)
    df['vix_slope'] = np.log(df['VIX3M'] / df['VIX'])

    # Factor 2: Corwin-Schultz Spread
    df['cs_spread'] = corwin_schultz_spread(df['high'].values, df['low'].values)

    # Factor 3: Parkinson Range = log(H/L)
    df['park_range'] = parkinson_range(df['high'].values, df['low'].values)

    # Drop rows with any NaN in critical columns
    df = df.dropna(subset=['VIX', 'VIX3M', 'cs_spread', 'park_range'])

    return df


# Download VIX and VIX3M
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_data = vix_raw[['Close']].rename(columns={'Close': 'VIX'})

vix3m_raw = yf.download("^VIX3M", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix3m_raw.columns, pd.MultiIndex):
    vix3m_raw.columns = vix3m_raw.columns.get_level_values(0)
vix3m_data = vix3m_raw[['Close']].rename(columns={'Close': 'VIX3M'})

print(f"  VIX data: {vix_data.index[0].strftime('%Y-%m-%d')} to {vix_data.index[-1].strftime('%Y-%m-%d')}")
print(f"  VIX3M data: {vix3m_data.index[0].strftime('%Y-%m-%d')} to {vix3m_data.index[-1].strftime('%Y-%m-%d')}")

asset_data = {}
for ticker in ASSETS:
    asset_data[ticker] = load_asset_data(ticker, vix_data, vix3m_data)
    d = asset_data[ticker]
    print(f"    {ticker}: {d.index[0].strftime('%Y-%m-%d')} to "
          f"{d.index[-1].strftime('%Y-%m-%d')}, n={len(d)}")
    # Factor diagnostics
    print(f"      VIX slope: mean={d['vix_slope'].mean():.4f}, std={d['vix_slope'].std():.4f}")
    print(f"      CS spread: mean={d['cs_spread'].mean():.6f}, std={d['cs_spread'].std():.6f}")
    print(f"      Park range: mean={d['park_range'].mean():.4f}, std={d['park_range'].std():.4f}")

# ============================================================
# SECTION 3: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")
for ticker in ASSETS:
    ret = asset_data[ticker]['log_ret'].values
    desc = {
        'mean': float(np.mean(ret)),
        'std': float(np.std(ret)),
        'skewness': float(stats.skew(ret)),
        'kurtosis': float(stats.kurtosis(ret)),
        'n': int(len(ret))
    }
    jb_stat, jb_p = stats.jarque_bera(ret)
    # ARCH LM test (10 lags)
    ret2 = ret ** 2
    n_lm = len(ret2) - 10
    X_lm = np.column_stack([np.ones(n_lm)] + [ret2[i:i+n_lm] for i in range(10)])
    y_lm = ret2[10:]
    b_lm = np.linalg.lstsq(X_lm, y_lm, rcond=None)[0]
    r2_lm = 1 - np.var(y_lm - X_lm @ b_lm) / np.var(y_lm)
    arch_lm = n_lm * r2_lm

    print(f"  {ticker}: Mean={desc['mean']:.6f} Std={desc['std']:.4f} "
          f"Skew={desc['skewness']:.3f} Kurt={desc['kurtosis']:.2f} "
          f"JB={jb_stat:.0f}(p={jb_p:.1e}) ARCH_LM={arch_lm:.1f}")

# Factor correlation with VIX
print("\n  Factor correlations with log(VIX):")
for ticker in ASSETS:
    d = asset_data[ticker]
    log_vix = np.log(d['VIX'].values)
    for fname, fcol in [('VIX Slope', 'vix_slope'),
                         ('CS Spread', 'cs_spread'),
                         ('Park Range', 'park_range')]:
        fvals = d[fcol].values
        valid = np.isfinite(fvals) & np.isfinite(log_vix)
        corr = np.corrcoef(log_vix[valid], fvals[valid])[0, 1]
        print(f"    {ticker} log(VIX) vs {fname}: r={corr:.4f}")


# ============================================================
# SECTION 4: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


@njit(cache=True)
def gjr_garch_loglik(params, returns):
    """GJR-GARCH(1,1) log-likelihood. Returns negative LL for minimization."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns)
    ll = 0.0

    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10

    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])

    return -ll


@njit(cache=True)
def gjr_garch_forecast_oos(params, returns, h_prev):
    """One-step GJR-GARCH forecast given previous h and return."""
    omega, alpha, gamma, beta = params
    r_prev = returns
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    h_next = omega + alpha * r_prev**2 + asym + beta * h_prev
    return max(h_next, 1e-10)


def fit_gjr_garch(returns):
    """Fit GJR-GARCH(1,1) via MLE with multi-start."""
    best_ll = np.inf
    best_params = None

    starts = [
        [1e-6, 0.05, 0.05, 0.90],
        [1e-6, 0.08, 0.10, 0.85],
        [1e-5, 0.03, 0.03, 0.93],
        [5e-6, 0.06, 0.08, 0.88],
    ]

    bounds = [(1e-8, 1e-3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                lambda p: gjr_garch_loglik(p, returns),
                x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 500}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params, -best_ll


def fit_mf_garch(returns, log_vix, model_type='garch'):
    """Fit single-factor MF-GARCH or MF-GJR (VIX only).

    Long-run: tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))
    Short-run: g_t = GARCH(1,1) or GJR-GARCH(1,1) on u_t = r_t/sqrt(tau_t)
    Total: sigma^2_t = tau_t * g_t
    """
    n = len(returns)
    assert len(log_vix) == n

    r2 = returns ** 2
    r2_positive = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_positive)
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

    # OLS for initial theta
    X_ols = np.column_stack([np.ones(n), log_vix_lag])
    theta_init = np.linalg.lstsq(X_ols, log_r2, rcond=None)[0]

    def neg_loglik(params):
        if model_type == 'gjr':
            theta0, theta1, alpha, gamma, beta = params
        else:
            theta0, theta1, alpha, beta = params
            gamma = 0.0

        log_tau = theta0 + theta1 * log_vix_lag
        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)
        u = returns / np.sqrt(tau)

        omega_g = 1.0 - alpha - gamma / 2.0 - beta
        if omega_g <= 0 or alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10

        g = np.empty(n)
        g[0] = 1.0

        for t in range(1, n):
            asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
            g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        sigma2 = tau * g
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)

        if not np.isfinite(ll):
            return 1e10
        return -ll

    best_ll = np.inf
    best_params = None

    if model_type == 'gjr':
        starts = [
            [theta_init[0], theta_init[1], 0.05, 0.05, 0.90],
            [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.10, 0.85],
            [-8.0, 0.5, 0.05, 0.05, 0.90],
            [-7.0, 0.8, 0.03, 0.03, 0.93],
        ]
        bounds = [(-20, 0), (-1, 3), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]
    else:
        starts = [
            [theta_init[0], theta_init[1], 0.05, 0.90],
            [theta_init[0] * 0.8, theta_init[1] * 0.8, 0.08, 0.85],
            [-8.0, 0.5, 0.05, 0.90],
            [-7.0, 0.8, 0.03, 0.93],
        ]
        bounds = [(-20, 0), (-1, 3), (1e-4, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 1000}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        return None, None
    return best_params, -best_ll


def fit_mf_garch_extended(returns, log_vix, extra_factor, model_type='gjr'):
    """Fit two-factor MF-GJR: tau_t = exp(theta_0 + theta_1*logVIX_{t-1} + theta_2*X_{t-1}).

    Parameters:
        returns: array of log returns
        log_vix: array of log(VIX)
        extra_factor: array of the second factor (raw values, will be lagged)
        model_type: 'garch' or 'gjr'

    Returns:
        params, log_likelihood
        For gjr: params = [theta_0, theta_1, theta_2, alpha, gamma, beta]
        For garch: params = [theta_0, theta_1, theta_2, alpha, beta]
    """
    n = len(returns)
    assert len(log_vix) == n
    assert len(extra_factor) == n

    r2 = returns ** 2
    r2_positive = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_positive)

    # Lag both factors
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

    factor_lag = np.roll(extra_factor, 1)
    factor_lag[0] = extra_factor[0]

    # OLS for initial thetas
    X_ols = np.column_stack([np.ones(n), log_vix_lag, factor_lag])
    theta_init = np.linalg.lstsq(X_ols, log_r2, rcond=None)[0]

    def neg_loglik(params):
        if model_type == 'gjr':
            theta0, theta1, theta2, alpha, gamma, beta = params
        else:
            theta0, theta1, theta2, alpha, beta = params
            gamma = 0.0

        # Long-run component with two factors
        log_tau = theta0 + theta1 * log_vix_lag + theta2 * factor_lag
        tau = np.exp(log_tau)
        tau = np.maximum(tau, 1e-16)

        u = returns / np.sqrt(tau)

        omega_g = 1.0 - alpha - gamma / 2.0 - beta
        if omega_g <= 0 or alpha + gamma / 2.0 + beta >= 1.0:
            return 1e10

        g = np.empty(n)
        g[0] = 1.0

        for t in range(1, n):
            asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
            g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        sigma2 = tau * g
        ll = -0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns**2 / sigma2)

        if not np.isfinite(ll):
            return 1e10
        return -ll

    best_ll = np.inf
    best_params = None

    if model_type == 'gjr':
        # [theta_0, theta_1, theta_2, alpha, gamma, beta]
        starts = [
            [theta_init[0], theta_init[1], theta_init[2], 0.05, 0.05, 0.90],
            [theta_init[0] * 0.8, theta_init[1] * 0.8, theta_init[2] * 0.5, 0.08, 0.10, 0.85],
            [-8.0, 0.5, 0.0, 0.05, 0.05, 0.90],
            [-7.0, 0.8, 0.0, 0.03, 0.03, 0.93],
            [theta_init[0], theta_init[1], 0.0, 0.06, 0.08, 0.88],
            [-8.0, 0.5, theta_init[2], 0.05, 0.05, 0.90],
        ]
        bounds = [(-20, 0), (-1, 3), (-5, 5), (1e-4, 0.3), (0.0, 0.3), (0.5, 0.999)]
    else:
        starts = [
            [theta_init[0], theta_init[1], theta_init[2], 0.05, 0.90],
            [theta_init[0] * 0.8, theta_init[1] * 0.8, theta_init[2] * 0.5, 0.08, 0.85],
            [-8.0, 0.5, 0.0, 0.05, 0.90],
            [-7.0, 0.8, 0.0, 0.03, 0.93],
        ]
        bounds = [(-20, 0), (-1, 3), (-5, 5), (1e-4, 0.3), (0.5, 0.999)]

    for x0 in starts:
        try:
            res = optimize.minimize(
                neg_loglik, x0, method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 1000}
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    if best_params is None:
        return None, None
    return best_params, -best_ll


def forecast_mf_garch(params, returns, log_vix, model_type='garch'):
    """Generate in-sample sigma^2 from single-factor MF model."""
    n = len(returns)

    if model_type == 'gjr':
        theta0, theta1, alpha, gamma, beta = params
    else:
        theta0, theta1, alpha, beta = params
        gamma = 0.0

    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]
    log_tau = theta0 + theta1 * log_vix_lag
    tau = np.exp(log_tau)
    tau = np.maximum(tau, 1e-16)
    u = returns / np.sqrt(tau)

    g = np.empty(n)
    g[0] = 1.0
    for t in range(1, n):
        asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
        g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    sigma2 = tau * g
    return sigma2, g, tau


def forecast_mf_garch_extended(params, returns, log_vix, extra_factor, model_type='gjr'):
    """Generate in-sample sigma^2 from two-factor MF model."""
    n = len(returns)

    if model_type == 'gjr':
        theta0, theta1, theta2, alpha, gamma, beta = params
    else:
        theta0, theta1, theta2, alpha, beta = params
        gamma = 0.0

    omega_g = 1.0 - alpha - gamma / 2.0 - beta

    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]
    factor_lag = np.roll(extra_factor, 1)
    factor_lag[0] = extra_factor[0]

    log_tau = theta0 + theta1 * log_vix_lag + theta2 * factor_lag
    tau = np.exp(log_tau)
    tau = np.maximum(tau, 1e-16)
    u = returns / np.sqrt(tau)

    g = np.empty(n)
    g[0] = 1.0
    for t in range(1, n):
        asym = gamma * u[t-1]**2 if u[t-1] < 0 else 0.0
        g[t] = omega_g + alpha * u[t-1]**2 + asym + beta * g[t-1]
        if g[t] < 1e-10:
            g[t] = 1e-10

    sigma2 = tau * g
    return sigma2, g, tau


# ============================================================
# SECTION 5: ROLLING OOS EVALUATION
# ============================================================
print("\n[4] Rolling OOS evaluation...")


def run_oos_for_asset(ticker, df):
    """Run all models OOS for a single asset, including extended factor models."""
    print(f"\n  === {ticker} ===")

    ret = df['log_ret'].values
    log_vix_raw = np.log(df['VIX'].values)
    vix_slope_raw = df['vix_slope'].values
    cs_spread_raw = df['cs_spread'].values
    park_range_raw = df['park_range'].values
    # Use log of park_range as the factor (log(H/L) is already log scale)
    log_park_range_raw = np.log(np.maximum(park_range_raw, 1e-10))
    r2 = ret ** 2
    dates = df.index

    # Find OOS start index
    oos_mask = dates >= OOS_START
    oos_start_idx = np.argmax(oos_mask)
    if oos_start_idx < WINDOW:
        oos_start_idx = WINDOW
    print(f"    OOS starts at index {oos_start_idx}, date={dates[oos_start_idx]}")

    n_oos = len(ret) - oos_start_idx
    print(f"    OOS days: {n_oos}")

    # Model names
    # Baseline models: GJR, MF-GJR(VIX)
    # Extended models: MF-GJR(VIX+Slope), MF-GJR(VIX+Spread), MF-GJR(VIX+Range)
    models = ['GJR', 'MF-GJR(VIX)',
              'MF-GJR(VIX+Slope)', 'MF-GJR(VIX+Spread)', 'MF-GJR(VIX+Range)']

    # Factor definitions: (name, raw_array)
    extended_factors = {
        'MF-GJR(VIX+Slope)': ('vix_slope', vix_slope_raw),
        'MF-GJR(VIX+Spread)': ('cs_spread', cs_spread_raw),
        'MF-GJR(VIX+Range)': ('log_park_range', log_park_range_raw),
    }

    forecasts = {m: np.full(n_oos, np.nan) for m in models}
    oos_returns = ret[oos_start_idx:]
    oos_r2 = r2[oos_start_idx:]
    oos_dates = dates[oos_start_idx:]

    # Track IS log-likelihoods for overfitting check
    is_logliks = {m: [] for m in models}

    # State variables for GJR
    last_gjr_params = None
    last_gjr_h = None

    # State variables for MF-GJR(VIX)
    last_mfgjr_params = None
    last_mfgjr_g = None
    tau_prev_mfgjr = None

    # State variables for extended models
    last_ext_params = {m: None for m in extended_factors}
    last_ext_g = {m: None for m in extended_factors}
    tau_prev_ext = {m: None for m in extended_factors}

    n_refits = 0
    for t in range(n_oos):
        idx = oos_start_idx + t
        need_refit = (t == 0) or (t % REFIT_EVERY == 0)

        # Training window
        train_start = max(0, idx - WINDOW)
        train_ret = ret[train_start:idx]
        train_vix = log_vix_raw[train_start:idx]

        if need_refit:
            n_refits += 1

            # === Fit GJR-GARCH ===
            gjr_params, gjr_ll = fit_gjr_garch(train_ret)
            if gjr_params is not None:
                last_gjr_params = gjr_params
                is_logliks['GJR'].append(gjr_ll)
                h_arr = np.empty(len(train_ret))
                h_arr[0] = np.var(train_ret)
                for tt in range(1, len(train_ret)):
                    omega, alpha, gamma_g, beta = gjr_params
                    asym = gamma_g * train_ret[tt-1]**2 if train_ret[tt-1] < 0 else 0.0
                    h_arr[tt] = omega + alpha * train_ret[tt-1]**2 + asym + beta * h_arr[tt-1]
                    h_arr[tt] = max(h_arr[tt], 1e-10)
                # BUG FIX #3: Advance h one step
                last_gjr_h = gjr_garch_forecast_oos(gjr_params, train_ret[-1], h_arr[-1])

            # === Fit MF-GJR(VIX) ===
            mfgjr_params, mfgjr_ll = fit_mf_garch(train_ret, train_vix, model_type='gjr')
            if mfgjr_params is not None:
                last_mfgjr_params = mfgjr_params
                is_logliks['MF-GJR(VIX)'].append(mfgjr_ll)
                _, g_arr, tau_arr = forecast_mf_garch(mfgjr_params, train_ret, train_vix, 'gjr')
                # BUG FIX #3: Advance g one step
                theta0, theta1, alpha_mf, gamma_mf, beta_mf = mfgjr_params
                last_tau = tau_arr[-1]
                u_last = train_ret[-1] / np.sqrt(last_tau)
                omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
                asym = gamma_mf * u_last**2 if u_last < 0 else 0.0
                last_mfgjr_g = omega_g + alpha_mf * u_last**2 + asym + beta_mf * g_arr[-1]
                last_mfgjr_g = max(last_mfgjr_g, 1e-10)

            # === Fit extended models ===
            for m_name, (f_name, f_raw) in extended_factors.items():
                train_factor = f_raw[train_start:idx]
                ext_params, ext_ll = fit_mf_garch_extended(
                    train_ret, train_vix, train_factor, model_type='gjr')
                if ext_params is not None:
                    last_ext_params[m_name] = ext_params
                    is_logliks[m_name].append(ext_ll)
                    _, g_arr, tau_arr = forecast_mf_garch_extended(
                        ext_params, train_ret, train_vix, train_factor, 'gjr')
                    # BUG FIX #3: Advance g one step
                    theta0, theta1, theta2, alpha_mf, gamma_mf, beta_mf = ext_params
                    last_tau = tau_arr[-1]
                    u_last = train_ret[-1] / np.sqrt(last_tau)
                    omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
                    asym = gamma_mf * u_last**2 if u_last < 0 else 0.0
                    last_ext_g[m_name] = omega_g + alpha_mf * u_last**2 + asym + beta_mf * g_arr[-1]
                    last_ext_g[m_name] = max(last_ext_g[m_name], 1e-10)

            if n_refits % 5 == 0 or n_refits == 1:
                print(f"    Refit #{n_refits} at t={t}, date={dates[idx].strftime('%Y-%m-%d')}")

        # === Generate one-step-ahead forecasts ===

        # GJR-GARCH
        if last_gjr_params is not None and last_gjr_h is not None:
            if not need_refit and t > 0:
                last_gjr_h = gjr_garch_forecast_oos(last_gjr_params, ret[idx-1], last_gjr_h)
            forecasts['GJR'][t] = last_gjr_h

        # MF-GJR(VIX)
        if last_mfgjr_params is not None:
            theta0, theta1, alpha_mf, gamma_mf, beta_mf = last_mfgjr_params
            log_tau_t = theta0 + theta1 * log_vix_raw[idx-1]
            tau_t = np.exp(log_tau_t)
            tau_t = max(tau_t, 1e-16)

            if need_refit:
                g_t = last_mfgjr_g
            else:
                u_prev = ret[idx-1] / np.sqrt(tau_prev_mfgjr)
                omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
                asym = gamma_mf * u_prev**2 if u_prev < 0 else 0.0
                g_t = omega_g + alpha_mf * u_prev**2 + asym + beta_mf * last_mfgjr_g
                g_t = max(g_t, 1e-10)

            tau_prev_mfgjr = tau_t
            last_mfgjr_g = g_t
            forecasts['MF-GJR(VIX)'][t] = tau_t * g_t

        # Extended models
        for m_name, (f_name, f_raw) in extended_factors.items():
            if last_ext_params[m_name] is not None:
                theta0, theta1, theta2, alpha_mf, gamma_mf, beta_mf = last_ext_params[m_name]
                # Long-run from yesterday's VIX AND yesterday's extra factor
                log_tau_t = theta0 + theta1 * log_vix_raw[idx-1] + theta2 * f_raw[idx-1]
                tau_t = np.exp(log_tau_t)
                tau_t = max(tau_t, 1e-16)

                if need_refit:
                    g_t = last_ext_g[m_name]
                else:
                    u_prev = ret[idx-1] / np.sqrt(tau_prev_ext[m_name])
                    omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
                    asym = gamma_mf * u_prev**2 if u_prev < 0 else 0.0
                    g_t = omega_g + alpha_mf * u_prev**2 + asym + beta_mf * last_ext_g[m_name]
                    g_t = max(g_t, 1e-10)

                tau_prev_ext[m_name] = tau_t
                last_ext_g[m_name] = g_t
                forecasts[m_name][t] = tau_t * g_t

    print(f"    Refits: {n_refits}")

    # ============================================================
    # SECTION 6: EVALUATION
    # ============================================================

    # 6a: QLIKE on r^2 (Patton 2011)
    qlike_results = {}
    for m in models:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() > 100:
            qlike_results[m] = qlike(oos_r2[valid], f[valid])
        else:
            qlike_results[m] = np.nan

    # Normalize to GJR baseline
    gjr_qlike = qlike_results['GJR']
    qlike_pct_vs_gjr = {}
    for m in models:
        if np.isfinite(qlike_results[m]) and np.isfinite(gjr_qlike) and gjr_qlike > 0:
            qlike_pct_vs_gjr[m] = ((qlike_results[m] - gjr_qlike) / gjr_qlike) * 100
        else:
            qlike_pct_vs_gjr[m] = np.nan

    # Also compute % vs MF-GJR(VIX) baseline
    mfgjr_qlike = qlike_results['MF-GJR(VIX)']
    qlike_pct_vs_mfgjr = {}
    for m in models:
        if np.isfinite(qlike_results[m]) and np.isfinite(mfgjr_qlike) and mfgjr_qlike > 0:
            qlike_pct_vs_mfgjr[m] = ((qlike_results[m] - mfgjr_qlike) / mfgjr_qlike) * 100
        else:
            qlike_pct_vs_mfgjr[m] = np.nan

    print(f"\n    QLIKE on r^2 (Patton 2011):")
    for m in models:
        pct_gjr = qlike_pct_vs_gjr.get(m, np.nan)
        pct_mfgjr = qlike_pct_vs_mfgjr.get(m, np.nan)
        print(f"      {m:25s}: {qlike_results[m]:.6f} "
              f"({pct_gjr:+.3f}% vs GJR, {pct_mfgjr:+.3f}% vs MF-GJR(VIX))")

    # 6b: Spearman rank correlation
    spearman_results = {}
    for m in models:
        f = forecasts[m]
        valid = np.isfinite(f) & (f > 0)
        if valid.sum() > 100:
            rho, p = spearman_corr(oos_r2[valid], f[valid])
            spearman_results[m] = {'rho': rho, 'p': p}
        else:
            spearman_results[m] = {'rho': np.nan, 'p': np.nan}

    print(f"\n    Spearman rank correlation:")
    for m in models:
        r = spearman_results[m]
        print(f"      {m:25s}: rho={r['rho']:.4f} (p={r['p']:.2e})")

    # 6c: DM tests vs GJR AND vs MF-GJR(VIX)
    gjr_loss = qlike_pointwise(oos_r2, forecasts['GJR'])
    mfgjr_loss = qlike_pointwise(oos_r2, forecasts['MF-GJR(VIX)'])

    dm_vs_gjr = {}
    dm_vs_mfgjr = {}
    for m in models:
        if m == 'GJR':
            dm_vs_gjr[m] = {'t': 0.0, 'p': 1.0}
        else:
            f = forecasts[m]
            valid = np.isfinite(f) & (f > 0) & np.isfinite(gjr_loss)
            if valid.sum() > 100:
                m_loss = qlike_pointwise(oos_r2[valid], f[valid])
                t_stat, p_val = dm_test(m_loss, gjr_loss[valid])
                dm_vs_gjr[m] = {'t': float(t_stat), 'p': float(p_val)}
            else:
                dm_vs_gjr[m] = {'t': np.nan, 'p': np.nan}

        if m == 'MF-GJR(VIX)':
            dm_vs_mfgjr[m] = {'t': 0.0, 'p': 1.0}
        else:
            f = forecasts[m]
            valid = np.isfinite(f) & (f > 0) & np.isfinite(mfgjr_loss)
            if valid.sum() > 100:
                m_loss = qlike_pointwise(oos_r2[valid], f[valid])
                t_stat, p_val = dm_test(m_loss, mfgjr_loss[valid])
                dm_vs_mfgjr[m] = {'t': float(t_stat), 'p': float(p_val)}
            else:
                dm_vs_mfgjr[m] = {'t': np.nan, 'p': np.nan}

    print(f"\n    DM tests vs GJR (negative t = model better):")
    for m in models:
        r = dm_vs_gjr[m]
        sig = "***" if abs(r['t']) > 3.0 else ("*" if abs(r['t']) > 1.96 else "NS")
        print(f"      {m:25s}: t={r['t']:+.3f} (p={r['p']:.4f}) {sig}")

    print(f"\n    DM tests vs MF-GJR(VIX) (negative t = extended model better):")
    for m in models:
        r = dm_vs_mfgjr[m]
        sig = "HARVEY PASS" if abs(r['t']) > 3.0 else ("*" if abs(r['t']) > 1.96 else "NS")
        print(f"      {m:25s}: t={r['t']:+.3f} (p={r['p']:.4f}) {sig}")

    # 6d: MCS (Hansen-Lunde-Nason 2011)
    all_valid = np.ones(n_oos, dtype=bool)
    for m in models:
        f = forecasts[m]
        all_valid &= np.isfinite(f) & (f > 0)

    if all_valid.sum() > 100:
        aligned_losses = {m: qlike_pointwise(oos_r2[all_valid], forecasts[m][all_valid])
                          for m in models}
        mcs_result = model_confidence_set(aligned_losses, alpha=0.10, n_boot=5000, seed=42)
        mcs_survived = mcs_result['mcs_models']
        mcs_eliminated = [m for m, _ in mcs_result['eliminated']]
        mcs_p_values = mcs_result['p_values']
    else:
        mcs_survived = models
        mcs_eliminated = []
        mcs_p_values = {m: 1.0 for m in models}

    best_model = min(
        [m for m in models if np.isfinite(qlike_results.get(m, np.nan))],
        key=lambda m: qlike_results[m]
    )

    print(f"\n    MCS (Hansen-Lunde-Nason 2011, alpha=0.10, 5000 bootstrap):")
    print(f"      Best model: {best_model}")
    print(f"      Survived: {mcs_survived}")
    print(f"      Eliminated: {mcs_eliminated}")
    print(f"      P-values: {', '.join(f'{m}={mcs_p_values.get(m, 0):.3f}' for m in models)}")

    # 6e: VaR Trinity test (1% and 5%)
    var_results = {}
    for alpha in ALPHA_LEVELS:
        var_results[alpha] = {}
        z = norm.ppf(alpha)

        for m in models:
            f = forecasts[m]
            valid = np.isfinite(f) & (f > 0)
            if valid.sum() < 100:
                var_results[alpha][m] = {'violations': np.nan, 'rate': np.nan,
                                         'kupiec_p': np.nan, 'cc_p': np.nan,
                                         'basel': 'N/A', 'trinity': False}
                continue

            sigma = np.sqrt(f[valid])
            var_threshold = z * sigma
            actual_ret = oos_returns[valid]

            violations = actual_ret < var_threshold
            n_viol = int(np.sum(violations))
            n_total = int(len(actual_ret))
            viol_rate = n_viol / n_total

            # Kupiec (1995)
            p_hat = viol_rate
            if 0 < p_hat < 1:
                kupiec_lr = 2 * (n_viol * np.log(p_hat / alpha) +
                                 (n_total - n_viol) * np.log((1 - p_hat) / (1 - alpha)))
                kupiec_p = 1 - chi2.cdf(kupiec_lr, 1) if kupiec_lr > 0 else 1.0
            else:
                kupiec_p = 0.0 if p_hat == 0 and alpha > 0 else 1.0

            # Christoffersen (1998)
            n00 = n01 = n10 = n11 = 0
            for i in range(1, n_total):
                if not violations[i-1]:
                    if not violations[i]: n00 += 1
                    else: n01 += 1
                else:
                    if not violations[i]: n10 += 1
                    else: n11 += 1

            if (n00 + n01) > 0 and (n10 + n11) > 0:
                p01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
                p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
                p_pool = (n01 + n11) / n_total if n_total > 0 else 0

                if 0 < p_pool < 1 and 0 < p01 < 1 and 0 < p11 < 1:
                    lr_ind = 2 * (
                        n00 * np.log(1 - p01) + n01 * np.log(p01) +
                        n10 * np.log(1 - p11) + n11 * np.log(p11) -
                        (n00 + n10) * np.log(1 - p_pool) -
                        (n01 + n11) * np.log(p_pool)
                    )
                    cc_p = 1 - chi2.cdf(max(0, lr_ind + max(0, kupiec_lr if kupiec_lr > 0 else 0)), 2)
                else:
                    cc_p = 1.0
            else:
                cc_p = 1.0

            # Basel traffic light
            if alpha == 0.01:
                if n_viol <= 4: basel = "GREEN"
                elif n_viol <= 9: basel = "YELLOW"
                else: basel = "RED"
            else:
                expected = int(n_total * 0.05)
                if n_viol <= expected + 4: basel = "GREEN"
                elif n_viol <= expected + 9: basel = "YELLOW"
                else: basel = "RED"

            trinity_pass = (kupiec_p > 0.05) and (cc_p > 0.05) and (basel == "GREEN")
            var_results[alpha][m] = {
                'violations': n_viol,
                'total': n_total,
                'rate': round(viol_rate, 4),
                'expected_rate': alpha,
                'kupiec_p': round(kupiec_p, 4),
                'cc_p': round(cc_p, 4),
                'basel': basel,
                'trinity': trinity_pass
            }

    for alpha in ALPHA_LEVELS:
        print(f"\n    VaR {int(alpha*100)}% Trinity:")
        for m in models:
            r = var_results[alpha][m]
            print(f"      {m:25s}: {r['violations']}/{r.get('total','?')} "
                  f"({r['rate']:.3f}) Kupiec p={r['kupiec_p']:.3f} "
                  f"CC p={r['cc_p']:.3f} Basel={r['basel']} "
                  f"Trinity={'PASS' if r['trinity'] else 'FAIL'}")

    # 6f: IS vs OOS improvement (overfitting check)
    # Average IS log-likelihood per parameter
    is_oos_comparison = {}
    for m in models:
        if is_logliks[m]:
            avg_is_ll = float(np.mean(is_logliks[m]))
        else:
            avg_is_ll = np.nan
        is_oos_comparison[m] = {
            'avg_is_loglik': avg_is_ll,
            'oos_qlike': qlike_results.get(m, np.nan),
        }

    # 6g: Parameter estimates for extended models
    param_report = {}
    if last_gjr_params is not None:
        param_report['GJR'] = {
            'omega': float(last_gjr_params[0]),
            'alpha': float(last_gjr_params[1]),
            'gamma': float(last_gjr_params[2]),
            'beta': float(last_gjr_params[3]),
            'persistence': float(last_gjr_params[1] + last_gjr_params[2]/2 + last_gjr_params[3])
        }
    if last_mfgjr_params is not None:
        param_report['MF-GJR(VIX)'] = {
            'theta_0': float(last_mfgjr_params[0]),
            'theta_1': float(last_mfgjr_params[1]),
            'alpha': float(last_mfgjr_params[2]),
            'gamma': float(last_mfgjr_params[3]),
            'beta': float(last_mfgjr_params[4]),
            'persistence_g': float(last_mfgjr_params[2] + last_mfgjr_params[3]/2 + last_mfgjr_params[4])
        }
    for m_name in extended_factors:
        if last_ext_params[m_name] is not None:
            p = last_ext_params[m_name]
            param_report[m_name] = {
                'theta_0': float(p[0]),
                'theta_1_vix': float(p[1]),
                'theta_2_factor': float(p[2]),
                'alpha': float(p[3]),
                'gamma': float(p[4]),
                'beta': float(p[5]),
                'persistence_g': float(p[3] + p[4]/2 + p[5])
            }

    # theta_2 significance assessment (simple Wald-like check)
    theta2_summary = {}
    for m_name in extended_factors:
        if last_ext_params[m_name] is not None:
            theta2_val = float(last_ext_params[m_name][2])
            # Check if theta_2 is economically meaningful
            # (comparing to theta_1 magnitude)
            theta1_val = float(last_ext_params[m_name][1])
            theta2_summary[m_name] = {
                'theta_2': theta2_val,
                'theta_1': theta1_val,
                'ratio_theta2_theta1': abs(theta2_val) / max(abs(theta1_val), 1e-10),
                'sign': 'positive' if theta2_val > 0 else 'negative',
            }

    print(f"\n    theta_2 estimates (extended factor coefficient):")
    for m_name, ts in theta2_summary.items():
        print(f"      {m_name:25s}: theta_2={ts['theta_2']:+.4f} "
              f"(theta_1={ts['theta_1']:.4f}, ratio={ts['ratio_theta2_theta1']:.3f})")

    return {
        'ticker': ticker,
        'n_oos': int(n_oos),
        'oos_start': str(oos_dates[0].date()),
        'oos_end': str(oos_dates[-1].date()),
        'n_refits': n_refits,
        'qlike': {m: round(v, 6) if np.isfinite(v) else None for m, v in qlike_results.items()},
        'qlike_pct_vs_gjr': {m: round(v, 3) if np.isfinite(v) else None for m, v in qlike_pct_vs_gjr.items()},
        'qlike_pct_vs_mfgjr_vix': {m: round(v, 3) if np.isfinite(v) else None for m, v in qlike_pct_vs_mfgjr.items()},
        'spearman': {m: {'rho': round(v['rho'], 4) if np.isfinite(v['rho']) else None,
                         'p': round(v['p'], 6) if np.isfinite(v['p']) else None}
                     for m, v in spearman_results.items()},
        'dm_vs_gjr': {m: {'t': round(v['t'], 3) if np.isfinite(v['t']) else None,
                          'p': round(v['p'], 4) if np.isfinite(v['p']) else None,
                          'significant_harvey': abs(v['t']) > 3.0 if np.isfinite(v['t']) else False}
                      for m, v in dm_vs_gjr.items()},
        'dm_vs_mfgjr_vix': {m: {'t': round(v['t'], 3) if np.isfinite(v['t']) else None,
                                 'p': round(v['p'], 4) if np.isfinite(v['p']) else None,
                                 'significant_harvey': abs(v['t']) > 3.0 if np.isfinite(v['t']) else False}
                             for m, v in dm_vs_mfgjr.items()},
        'mcs': {
            'best_model': best_model,
            'survived': mcs_survived,
            'eliminated': mcs_eliminated,
            'p_values': {m: round(v, 4) for m, v in mcs_p_values.items()},
        },
        'var': {str(a): {m: v for m, v in var_results[a].items()} for a in ALPHA_LEVELS},
        'parameters': param_report,
        'theta2_summary': theta2_summary,
        'is_oos_comparison': {m: {k: round(v, 4) if isinstance(v, float) and np.isfinite(v) else v
                                   for k, v in comp.items()}
                              for m, comp in is_oos_comparison.items()},
    }


# ============================================================
# SECTION 7: RUN ALL ASSETS
# ============================================================
all_results = {}

for ticker in ASSETS:
    try:
        result = run_oos_for_asset(ticker, asset_data[ticker])
        all_results[ticker] = result
    except Exception as e:
        print(f"  ERROR for {ticker}: {e}")
        import traceback
        traceback.print_exc()
        all_results[ticker] = {'error': str(e)}


# ============================================================
# SECTION 8: CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

extended_models = ['MF-GJR(VIX+Slope)', 'MF-GJR(VIX+Spread)', 'MF-GJR(VIX+Range)']

for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        print(f"\n{ticker}: ERROR - {all_results[ticker]['error']}")
        continue
    r = all_results[ticker]
    print(f"\n{ticker} (OOS: {r['oos_start']} to {r['oos_end']}, n={r['n_oos']})")

    print(f"  QLIKE (% vs GJR): ", end="")
    for m in ['MF-GJR(VIX)'] + extended_models:
        pct = r['qlike_pct_vs_gjr'].get(m)
        print(f"  {m}={pct:+.3f}%" if pct is not None else f"  {m}=N/A", end="")
    print()

    print(f"  QLIKE (% vs MF-GJR(VIX)): ", end="")
    for m in extended_models:
        pct = r['qlike_pct_vs_mfgjr_vix'].get(m)
        print(f"  {m}={pct:+.3f}%" if pct is not None else f"  {m}=N/A", end="")
    print()

    print(f"  DM vs MF-GJR(VIX): ", end="")
    for m in extended_models:
        dm = r['dm_vs_mfgjr_vix'].get(m, {})
        t_val = dm.get('t')
        harvey = " HARVEY" if dm.get('significant_harvey') else ""
        print(f"  {m}={t_val:+.3f}{harvey}" if t_val is not None else f"  {m}=N/A", end="")
    print()

    print(f"  MCS survived: {r['mcs']['survived']}")


# ============================================================
# SECTION 9: KEY FINDINGS
# ============================================================
print("\n" + "=" * 70)
print("KEY FINDINGS: Does any factor beat MF-GJR(VIX)?")
print("=" * 70)

any_significant_vs_mfgjr = False
significant_list = []
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    for m in extended_models:
        dm = all_results[ticker]['dm_vs_mfgjr_vix'].get(m, {})
        if dm.get('significant_harvey', False) and dm.get('t', 0) < 0:
            any_significant_vs_mfgjr = True
            significant_list.append(f"{m} on {ticker} (DM t={dm['t']:.3f})")
            print(f"  SIGNIFICANT: {m} beats MF-GJR(VIX) on {ticker} (DM t={dm['t']:.3f})")

if not any_significant_vs_mfgjr:
    print("  No extended model significantly beats MF-GJR(VIX) (Harvey |t|>3.0)")
    print("  -> VIX remains the dominant long-run factor")

    # But check if any shows improvement at conventional levels
    print("\n  Improvement check (conventional p<0.05):")
    for ticker in ASSETS:
        if 'error' in all_results[ticker]:
            continue
        for m in extended_models:
            dm = all_results[ticker]['dm_vs_mfgjr_vix'].get(m, {})
            t_val = dm.get('t', 0)
            if t_val is not None and t_val < -1.96:
                pct = all_results[ticker]['qlike_pct_vs_mfgjr_vix'].get(m)
                print(f"    {m} on {ticker}: t={t_val:.3f}, QLIKE {pct:+.3f}% (conventional sig but not Harvey)")
else:
    print(f"\n  SIGNIFICANT improvements found: {', '.join(significant_list)}")

# Check theta_2 values across assets
print("\n  theta_2 values across assets:")
for m in extended_models:
    print(f"    {m}:")
    for ticker in ASSETS:
        if 'error' in all_results[ticker]:
            continue
        ts = all_results[ticker].get('theta2_summary', {}).get(m, {})
        if ts:
            print(f"      {ticker}: theta_2={ts['theta_2']:+.4f} ({ts['sign']}, "
                  f"ratio to theta_1={ts['ratio_theta2_theta1']:.3f})")


# ============================================================
# SECTION 10: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME

final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'MF-GJR with Extended Long-Run Factors',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'methodology': {
        'models': [
            'GJR-GARCH(1,1)',
            'MF-GJR(VIX) — baseline',
            'MF-GJR(VIX+Slope) — VIX term structure slope',
            'MF-GJR(VIX+Spread) — Corwin-Schultz bid-ask spread',
            'MF-GJR(VIX+Range) — Parkinson log range',
        ],
        'mf_long_run_baseline': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_long_run_extended': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}) + theta_2 * X_{t-1})',
        'factors': {
            'VIX Slope': 'log(VIX3M / VIX) — term structure slope (contango vs backwardation)',
            'CS Spread': 'Corwin-Schultz (2012) bid-ask spread from OHLC — liquidity/microstructure',
            'Park Range': 'log(Parkinson 1980 range) = log(log(H/L)) — intraday price range',
        },
        'estimation': 'Rolling window (w=2000), refit every 63 days, MLE with multi-start',
        'evaluation': 'QLIKE on r^2 (Patton 2011), DM test (Harvey t>3.0), Spearman, MCS (HLN 2011), VaR Trinity',
    },
    'data': {
        'source': 'yfinance',
        'assets': ASSETS,
        'period': f'{DATA_START} to {DATA_END}',
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'vix3m_note': 'VIX3M available from ~2007, ffilled for alignment',
    },
    'results': all_results,
    'key_findings': {
        'any_factor_beats_mfgjr_vix_harvey': any_significant_vs_mfgjr,
        'significant_improvements': significant_list,
        'conclusion': (
            'At least one extended factor provides Harvey PASS improvement beyond VIX'
            if any_significant_vs_mfgjr else
            'No extended factor provides Harvey PASS improvement beyond VIX. '
            'VIX sufficiency confirmed for the 26th+ time.'
        ),
    },
    'references': [
        'Engle, Ghysels & Sohn (2013) Stock Market Volatility and Macroeconomic Fundamentals, RES 95(3):776-797',
        'Engle & Rangel (2008) The Spline-GARCH Model, RFS 21(3):1187-1222',
        'Conrad & Engle (2025) Two-factor GARCH, J Applied Econometrics',
        'Patton (2011) Volatility forecast comparison using imperfect proxies, J Econometrics 160:246-256',
        'Harvey et al. (2016) Testing for multiple bubbles, JBES 34:92-104',
        'Hansen, Lunde & Nason (2011) The Model Confidence Set, Econometrica 79(2):453-497',
        'Corwin & Schultz (2012) A simple way to estimate bid-ask spreads, J Finance 67(2):719-760',
        'Parkinson (1980) The extreme value method for estimating the variance, J Business 53(1):61-65',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\nResults saved to: {RESULTS_PATH}")
print(f"Runtime: {elapsed:.1f}s ({elapsed/60:.1f}min)")
print(f"\n{'='*70}")
print(f"K909 COMPLETE")
print(f"{'='*70}")
