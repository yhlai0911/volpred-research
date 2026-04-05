#!/usr/bin/env python3
"""
K893: Regime-Weighted Conformal VaR (RWC)
=========================================
[提出: 用戶, 執行: Claude]

Concept: Weight conformal prediction residuals by VIX-regime similarity.
In high-vol regimes, give more weight to past high-vol residuals.
This should produce tighter prediction intervals than equal-weighted
conformal (HistSim) while maintaining coverage.

Prior work:
  K768/K800: Conformal VaR wrapper — C1 Naive FAIL, C2 Proxy-Robust PASS
             but too wide, C3 Exchangeable FAIL
  K824v2: HistSim & Student-t remain best VaR methods

Regime definition (VIX-based, no lookahead — uses VIX_{t-1}):
  Low:    VIX < 15
  Medium: 15 <= VIX < 25
  High:   VIX >= 25

Model: GJR-GARCH(1,1) + various VaR quantile methods
  1. Normal VaR
  2. Student-t VaR (scale correction sqrt((df-2)/df))
  3. HistSim (equal-weighted rolling 500 days) = RWC λ=0
  4. RWC λ=0.05
  5. RWC λ=0.1
  6. RWC λ=0.2

Assets: SPY, QQQ, 0050.TW (3 assets)
Data: yfinance, 2005-2026
OOS: 2019-01-01 to latest (≥6 years, includes COVID + 2022 bear + 2025)
For 0050.TW: clean_tw50_data mandatory

Evaluation:
  - VaR 1% + 5% Trinity (Kupiec + Christoffersen + Basel)
  - ES Acerbi-Szekely Z-test
  - Capital efficiency (average VaR width)
  - Coverage by regime

Error log rules:
  - DM test: use volpred.stats.model_evaluation.strategy_dm_test
  - Student-t: scale term sqrt((df-2)/df) included
  - 0050.TW: clean_tw50_data mandatory
  - Basel: standard 250-day lookback
  - signal.shift(1): VIX regime uses VIX_{t-1} (no lookahead)

References:
  - arXiv:2602.03903 (2026) — Regime-structured conformal prediction
  - Vovk et al. (2005) — Algorithmic Learning in a Random World (conformal)
  - Kupiec (1995) — Unconditional VaR coverage
  - Christoffersen (1998) — Conditional VaR independence
  - Basel Committee (1996, 2019) — Traffic light backtesting
  - Acerbi & Szekely (2014) — ES backtesting
  - Hansen & Lunde (2005) — volatility model evaluation
  - Harvey et al. (2016) — multiple testing threshold |t|>3.0
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

RESULTS_PATH = os.path.join(os.path.dirname(__file__),
                            'k893_regime_conformal_var_results.json')
OOS_START = '2019-01-01'
REFIT_EVERY = 63  # quarterly refit
ASSETS = ['SPY', 'QQQ', '0050.TW']
LAMBDA_VALUES = [0.0, 0.05, 0.1, 0.2]
HISTSIM_WINDOW = 500  # rolling window for residuals


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
# C. One-step forecast and standardized residuals
# ==============================================================

def gjr_one_step_forecast(returns, params):
    """GJR one-step forecast: σ²_{t+1} given data up to t."""
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
# D. Student-t df estimation (FIXED: with scale correction)
# ==============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """Estimate Student-t df from unit-variance standardized residuals via MLE.
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

    best_nll, best_df = 1e10, 5.0
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
# E. Regime-Weighted Conformal VaR (core innovation)
# ==============================================================

def weighted_quantile(values, weights, quantile):
    """Compute weighted quantile using sorted values and cumulative weights.

    For quantile q, finds value v such that
        sum(w_i for v_i <= v) / sum(w_i) >= q
    This is the standard definition for weighted quantiles.
    """
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)

    mask = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    values = values[mask]
    weights = weights[mask]

    if len(values) == 0:
        return np.nan

    # Sort by values
    sorter = np.argsort(values)
    values = values[sorter]
    weights = weights[sorter]

    # Cumulative weights normalized to [0, 1]
    cum_weights = np.cumsum(weights)
    cum_weights /= cum_weights[-1]

    # Find first index where cumulative weight >= quantile
    idx = np.searchsorted(cum_weights, quantile)
    idx = min(idx, len(values) - 1)
    return values[idx]


def compute_rwc_var(sigma_t, z_residuals, vix_history, vix_t,
                    alpha, lam, max_residuals=HISTSIM_WINDOW):
    """Compute Regime-Weighted Conformal VaR.

    Args:
        sigma_t: GARCH forecast σ for time t
        z_residuals: standardized residuals z_1, ..., z_{T-1}
        vix_history: VIX values corresponding to residuals
        vix_t: VIX at time t-1 (no lookahead)
        alpha: VaR level (e.g. 0.01 for 1%)
        lam: regime similarity parameter (0 = equal weight = HistSim)
        max_residuals: maximum number of past residuals to use

    Returns:
        VaR (negative number, loss at alpha level)
    """
    # Use most recent residuals
    n = min(len(z_residuals), max_residuals)
    z = z_residuals[-n:]
    vix_hist = vix_history[-n:]

    if len(z) < 30:
        # Fallback to Normal VaR
        return sigma_t * norm.ppf(alpha)

    # Compute regime similarity weights
    if lam <= 0:
        # Equal weights = HistSim
        weights = np.ones(len(z))
    else:
        # Exponential kernel: w_t = exp(-λ * |VIX_t - VIX_T|)
        vix_diff = np.abs(vix_hist - vix_t)
        weights = np.exp(-lam * vix_diff)

    # Weighted quantile of standardized residuals
    z_quantile = weighted_quantile(z, weights, alpha)

    return sigma_t * z_quantile


# ==============================================================
# F. VaR Backtesting Functions
# ==============================================================

def kupiec_test(violations, n_obs, alpha):
    """Kupiec (1995) unconditional coverage test.
    H0: violation rate = alpha. Returns (LR_stat, p_value)."""
    n_viol = int(np.sum(violations))
    if n_viol == 0:
        return 0.0, 1.0
    if n_viol == n_obs:
        return 999.0, 0.0
    pi_hat = n_viol / n_obs
    lr = 2 * (n_viol * np.log(pi_hat / alpha)
              + (n_obs - n_viol) * np.log((1 - pi_hat) / (1 - alpha)))
    p = 1 - chi2.cdf(abs(lr), 1)
    return float(lr), float(p)


def christoffersen_test(violations):
    """Christoffersen (1998) conditional coverage (independence) test.
    H0: violations are independent. Returns (LR_cc, p_value)."""
    v = np.asarray(violations, dtype=int)
    n = len(v)
    if n < 3:
        return 0.0, 1.0

    # Transition counts
    n00, n01, n10, n11 = 0, 0, 0, 0
    for i in range(1, n):
        if v[i - 1] == 0 and v[i] == 0:
            n00 += 1
        elif v[i - 1] == 0 and v[i] == 1:
            n01 += 1
        elif v[i - 1] == 1 and v[i] == 0:
            n10 += 1
        else:
            n11 += 1

    # Under independence
    n_viol = int(np.sum(v))
    if n_viol == 0 or n_viol == n:
        return 0.0, 1.0
    pi_hat = n_viol / n

    # Transition probabilities
    p01 = n01 / max(n00 + n01, 1)
    p11 = n11 / max(n10 + n11, 1)

    # Log-likelihoods
    eps = 1e-16
    # Unrestricted
    ll1 = 0.0
    if n00 > 0:
        ll1 += n00 * np.log(max(1 - p01, eps))
    if n01 > 0:
        ll1 += n01 * np.log(max(p01, eps))
    if n10 > 0:
        ll1 += n10 * np.log(max(1 - p11, eps))
    if n11 > 0:
        ll1 += n11 * np.log(max(p11, eps))

    # Restricted (independence)
    ll0 = 0.0
    if n00 + n10 > 0:
        ll0 += (n00 + n10) * np.log(max(1 - pi_hat, eps))
    if n01 + n11 > 0:
        ll0 += (n01 + n11) * np.log(max(pi_hat, eps))

    lr_ind = 2 * (ll1 - ll0)
    p = 1 - chi2.cdf(abs(lr_ind), 1)
    return float(lr_ind), float(p)


def basel_traffic_light(violations, n_obs):
    """Basel II/III traffic light: 250-day lookback.
    Green: 0-4 violations, Yellow: 5-9, Red: >=10.
    For OOS < 250 days, scale thresholds proportionally."""
    n_viol = int(np.sum(violations))
    if n_obs >= 250:
        # Use last 250 days
        recent = violations[-250:]
        n_recent = int(np.sum(recent))
    else:
        n_recent = n_viol

    # Scale thresholds for shorter windows
    scale = min(n_obs, 250) / 250.0
    green_max = int(np.floor(4 * scale))
    yellow_max = int(np.floor(9 * scale))

    if n_recent <= green_max:
        return 'GREEN'
    elif n_recent <= yellow_max:
        return 'YELLOW'
    else:
        return 'RED'


def trinity_test(violations, n_obs, alpha):
    """Trinity test: Kupiec + Christoffersen + Basel, all must pass."""
    _, p_kup = kupiec_test(violations, n_obs, alpha)
    _, p_cc = christoffersen_test(violations)
    btl = basel_traffic_light(violations, n_obs)

    kupiec_pass = p_kup > 0.05
    cc_pass = p_cc > 0.05
    basel_pass = btl == 'GREEN'

    return {
        'kupiec_p': round(float(p_kup), 4),
        'kupiec_pass': kupiec_pass,
        'cc_p': round(float(p_cc), 4),
        'cc_pass': cc_pass,
        'basel': btl,
        'basel_pass': basel_pass,
        'trinity_pass': kupiec_pass and cc_pass and basel_pass
    }


def acerbi_szekely_es_test(returns, var_forecasts, es_forecasts, violations):
    """Acerbi & Szekely (2014) ES backtest.
    Z = (1/n_viol) * sum( r_t * I(r_t < VaR_t) ) / ES - 1
    Under H0 (correct ES): E[Z] = 0.
    Test: Z / SE(Z), approximate normal."""
    r = np.asarray(returns)
    var_f = np.asarray(var_forecasts)
    es_f = np.asarray(es_forecasts)

    hit = r < var_f
    n_hit = np.sum(hit)

    if n_hit < 2:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True, 'n_violations': int(n_hit)}

    # ES ratio: average loss given violation / average ES forecast at violation
    avg_loss = np.mean(r[hit])
    avg_es = np.mean(es_f[hit])

    if abs(avg_es) < 1e-12:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True, 'n_violations': int(n_hit)}

    # Ratio test
    es_ratio = avg_loss / avg_es
    # Under H0: ratio ~ 1. Z-test approximation
    se = np.std(r[hit] / es_f[hit]) / np.sqrt(n_hit)
    if se < 1e-12:
        return {'z_stat': 0.0, 'p_value': 1.0, 'pass': True, 'n_violations': int(n_hit)}

    z_stat = (es_ratio - 1.0) / se
    p_value = 2 * (1 - norm.cdf(abs(z_stat)))

    return {
        'z_stat': round(float(z_stat), 4),
        'p_value': round(float(p_value), 4),
        'pass': p_value > 0.05,
        'es_ratio': round(float(es_ratio), 4),
        'n_violations': int(n_hit)
    }


# ==============================================================
# G. Data Loading
# ==============================================================

def load_data(ticker, start='2005-01-01'):
    """Load price data from yfinance and compute log returns."""
    print(f"  Downloading {ticker}...")
    data = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    if data.empty:
        raise ValueError(f"No data for {ticker}")

    # Handle MultiIndex columns
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    prices = data['Close'].dropna()

    # Clean 0050.TW data
    if '0050' in ticker:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
        from volpred.utils import clean_tw50_data
        prices, _ = clean_tw50_data(prices)
        print(f"  0050.TW cleaned: {len(prices)} observations")

    returns = np.log(prices / prices.shift(1)).dropna()

    # Load VIX for regime classification
    print(f"  Downloading ^VIX...")
    vix_data = yf.download('^VIX', start=start, progress=False, auto_adjust=True)
    if isinstance(vix_data.columns, pd.MultiIndex):
        vix_data.columns = vix_data.columns.get_level_values(0)
    vix = vix_data['Close'].dropna()

    # Align dates
    common = returns.index.intersection(vix.index)
    returns = returns.loc[common]
    vix = vix.loc[common]
    prices = prices.loc[common]

    print(f"  {ticker}: {len(returns)} observations, "
          f"{returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")

    return returns, vix, prices


# ==============================================================
# H. Classify VIX regime
# ==============================================================

def classify_regime(vix_value):
    """Classify VIX into Low/Medium/High regime."""
    if vix_value < 15:
        return 'Low'
    elif vix_value < 25:
        return 'Medium'
    else:
        return 'High'


# ==============================================================
# I. Main OOS VaR Forecasting Loop
# ==============================================================

def run_oos_var(returns, vix, oos_start=OOS_START):
    """Run expanding-window OOS VaR forecasting with multiple methods.

    For each day t in OOS:
      1. Fit/refit GJR on data up to t-1
      2. Compute σ_t (one-step forecast)
      3. Compute standardized residuals z_1,...,z_{t-1}
      4. Compute VaR at 1% and 5% using each method
      5. Record violation (r_t < VaR_t)

    NO LOOKAHEAD: VIX regime uses VIX_{t-1} (shifted by 1).
    """
    r_vals = returns.values
    vix_vals = vix.values
    dates = returns.index

    oos_mask = dates >= oos_start
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) < 252:
        print(f"  WARNING: OOS < 252 days ({len(oos_indices)}), skipping")
        return None

    print(f"  OOS: {dates[oos_indices[0]].strftime('%Y-%m-%d')} to "
          f"{dates[oos_indices[-1]].strftime('%Y-%m-%d')} ({len(oos_indices)} days)")

    # Methods
    methods = ['Normal', 'Student-t', 'HistSim']
    for lam in LAMBDA_VALUES:
        if lam > 0:
            methods.append(f'RWC_lam{lam}')

    alphas = [0.01, 0.05]

    # Storage
    results = {m: {f'var_{a}': [] for a in alphas} for m in methods}
    for m in methods:
        for a in alphas:
            results[m][f'es_{a}'] = []
    actual_returns = []
    oos_dates = []
    oos_vix = []
    oos_regimes = []
    sigma_forecasts = []

    # GJR state
    current_params = None
    last_fit_idx = -999

    t_start = time.time()
    n_oos = len(oos_indices)

    for step, t in enumerate(oos_indices):
        # --- Refit GJR if needed ---
        if t - last_fit_idx >= REFIT_EVERY or current_params is None:
            train_r = r_vals[:t]
            params = fit_gjr(train_r)
            if params is not None:
                current_params = params
                last_fit_idx = t
            elif current_params is None:
                continue

        # --- One-step σ forecast ---
        sigma2_t = gjr_one_step_forecast(r_vals[:t], current_params)
        sigma_t = np.sqrt(sigma2_t)
        sigma_forecasts.append(sigma_t)

        # --- Standardized residuals up to t-1 ---
        z_all = compute_standardized_residuals(r_vals[:t], current_params)

        # --- VIX at t-1 (no lookahead!) ---
        vix_t_prev = vix_vals[t - 1]  # VIX_{t-1}
        regime_t = classify_regime(vix_t_prev)

        actual_returns.append(r_vals[t])
        oos_dates.append(str(dates[t].date()))
        oos_vix.append(float(vix_t_prev))
        oos_regimes.append(regime_t)

        # --- VIX history for residuals ---
        # z_all has length len(r_vals[:t]) - 1 = t - 1
        # VIX aligned: vix_vals[1:t] (skip first for same reason as residuals)
        vix_for_residuals = vix_vals[1:t]
        if len(vix_for_residuals) > len(z_all):
            vix_for_residuals = vix_for_residuals[-len(z_all):]
        elif len(vix_for_residuals) < len(z_all):
            z_all = z_all[-len(vix_for_residuals):]

        for alpha in alphas:
            # --- Method 1: Normal VaR ---
            var_normal = sigma_t * norm.ppf(alpha)
            es_normal = sigma_t * (-norm.pdf(norm.ppf(alpha)) / alpha)
            results['Normal'][f'var_{alpha}'].append(float(var_normal))
            results['Normal'][f'es_{alpha}'].append(float(-abs(es_normal)))

            # --- Method 2: Student-t VaR ---
            # Estimate df from residuals (use cached if recent enough)
            if step % REFIT_EVERY == 0 or step == 0:
                _cached_df = estimate_t_df(z_all)
            scale = np.sqrt((_cached_df - 2) / _cached_df) if _cached_df > 2.1 else 1.0
            var_t = sigma_t * t_dist.ppf(alpha, df=_cached_df) * scale
            # ES for Student-t: E[X | X < VaR] using integration
            # For Student-t(df), ES_alpha = -sigma * scale * f(t_inv(alpha;df);df) * (df + t_inv(alpha;df)^2) / ((df-1) * alpha)
            t_q = t_dist.ppf(alpha, df=_cached_df)
            es_t_val = (-sigma_t * scale * t_dist.pdf(t_q, df=_cached_df)
                        * (_cached_df + t_q**2) / ((_cached_df - 1) * alpha))
            results['Student-t'][f'var_{alpha}'].append(float(var_t))
            results['Student-t'][f'es_{alpha}'].append(float(es_t_val))

            # --- Method 3: HistSim (equal-weighted = RWC λ=0) ---
            var_hs = compute_rwc_var(sigma_t, z_all, vix_for_residuals,
                                     vix_t_prev, alpha, lam=0.0)
            # ES for HistSim: average of residuals below quantile
            n_resid = min(len(z_all), HISTSIM_WINDOW)
            z_recent = z_all[-n_resid:]
            z_sorted = np.sort(z_recent)
            n_below = max(1, int(np.floor(alpha * len(z_sorted))))
            es_hs = sigma_t * np.mean(z_sorted[:n_below])
            results['HistSim'][f'var_{alpha}'].append(float(var_hs))
            results['HistSim'][f'es_{alpha}'].append(float(es_hs))

            # --- Methods 4-6: RWC with different λ ---
            for lam in LAMBDA_VALUES:
                if lam <= 0:
                    continue
                method_name = f'RWC_lam{lam}'
                var_rwc = compute_rwc_var(sigma_t, z_all, vix_for_residuals,
                                          vix_t_prev, alpha, lam=lam)
                # ES for RWC: weighted average of residuals below weighted quantile
                n_r = min(len(z_all), HISTSIM_WINDOW)
                z_r = z_all[-n_r:]
                vix_r = vix_for_residuals[-n_r:]
                w_r = np.exp(-lam * np.abs(vix_r - vix_t_prev))
                # ES: weighted mean of z below the VaR quantile
                z_q = var_rwc / sigma_t  # standardized VaR
                below_mask = z_r <= z_q
                if np.any(below_mask):
                    es_rwc = sigma_t * np.average(z_r[below_mask],
                                                   weights=w_r[below_mask])
                else:
                    es_rwc = var_rwc * 1.2  # fallback
                results[method_name][f'var_{alpha}'].append(float(var_rwc))
                results[method_name][f'es_{alpha}'].append(float(es_rwc))

        # Progress
        if (step + 1) % 200 == 0:
            elapsed = time.time() - t_start
            rate = (step + 1) / elapsed
            eta = (n_oos - step - 1) / rate
            print(f"  [{step+1}/{n_oos}] {rate:.1f} days/sec, ETA {eta:.0f}s")

    elapsed = time.time() - t_start
    print(f"  Completed in {elapsed:.1f}s ({len(actual_returns)} OOS days)")

    return {
        'methods': methods,
        'alphas': alphas,
        'results': results,
        'actual_returns': actual_returns,
        'oos_dates': oos_dates,
        'oos_vix': oos_vix,
        'oos_regimes': oos_regimes,
        'sigma_forecasts': [float(s) for s in sigma_forecasts],
        'n_oos': len(actual_returns),
    }


# ==============================================================
# J. Evaluate results
# ==============================================================

def evaluate_results(oos_data):
    """Evaluate all VaR methods with Trinity + ES tests."""
    if oos_data is None:
        return None

    methods = oos_data['methods']
    alphas = oos_data['alphas']
    r = np.array(oos_data['actual_returns'])
    regimes = oos_data['oos_regimes']
    n_oos = oos_data['n_oos']

    evaluation = {}

    for method in methods:
        evaluation[method] = {}
        for alpha in alphas:
            var_f = np.array(oos_data['results'][method][f'var_{alpha}'])
            es_f = np.array(oos_data['results'][method][f'es_{alpha}'])

            # Violations
            violations = (r < var_f).astype(int)
            n_viol = int(np.sum(violations))
            viol_rate = n_viol / n_oos

            # Trinity test
            trinity = trinity_test(violations, n_oos, alpha)

            # ES test
            es_test = acerbi_szekely_es_test(r, var_f, es_f, violations)

            # Capital efficiency: average VaR width (more negative = wider)
            avg_var = float(np.mean(var_f))
            avg_var_pct = float(np.mean(var_f) * 100)  # in %

            # Coverage by regime
            regime_coverage = {}
            for reg in ['Low', 'Medium', 'High']:
                reg_mask = np.array([rg == reg for rg in regimes])
                if np.sum(reg_mask) > 0:
                    reg_viol = np.sum(violations[reg_mask])
                    reg_n = np.sum(reg_mask)
                    regime_coverage[reg] = {
                        'n_days': int(reg_n),
                        'n_violations': int(reg_viol),
                        'violation_rate': round(float(reg_viol / reg_n), 4),
                        'target': alpha
                    }

            evaluation[method][f'alpha_{alpha}'] = {
                'n_violations': n_viol,
                'violation_rate': round(viol_rate, 4),
                'target_rate': alpha,
                'trinity': trinity,
                'es_test': es_test,
                'avg_var_pct': round(avg_var_pct, 4),
                'regime_coverage': regime_coverage
            }

    return evaluation


# ==============================================================
# K. Main
# ==============================================================

def main():
    print("=" * 70)
    print("K893: Regime-Weighted Conformal VaR (RWC)")
    print("=" * 70)
    print(f"OOS start: {OOS_START}")
    print(f"Lambda values: {LAMBDA_VALUES}")
    print(f"HistSim window: {HISTSIM_WINDOW}")
    print(f"Refit every: {REFIT_EVERY} days")
    print(f"Assets: {ASSETS}")
    print()

    all_results = {
        'experiment_id': 'K893',
        'title': 'Regime-Weighted Conformal VaR (RWC)',
        'description': ('VIX-regime-weighted conformal prediction for VaR. '
                        'Weight past standardized residuals by similarity to '
                        'current VIX regime, producing tighter intervals than '
                        'equal-weighted HistSim while maintaining coverage.'),
        'data_source': 'yfinance',
        'oos_start': OOS_START,
        'lambda_values': LAMBDA_VALUES,
        'histsim_window': HISTSIM_WINDOW,
        'refit_every': REFIT_EVERY,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'assets': {}
    }

    for ticker in ASSETS:
        print(f"\n{'='*60}")
        print(f"Asset: {ticker}")
        print(f"{'='*60}")

        try:
            returns, vix, prices = load_data(ticker)
        except Exception as e:
            print(f"  ERROR loading {ticker}: {e}")
            all_results['assets'][ticker] = {'error': str(e)}
            continue

        # Descriptive statistics
        print(f"  Mean return: {returns.mean()*100:.4f}%")
        print(f"  Std: {returns.std()*100:.4f}%")
        print(f"  Skewness: {returns.skew():.4f}")
        print(f"  Kurtosis: {returns.kurtosis():.4f}")
        print(f"  VIX mean: {vix.mean():.2f}, VIX range: {vix.min():.2f}-{vix.max():.2f}")

        # Run OOS
        oos_data = run_oos_var(returns, vix)
        if oos_data is None:
            all_results['assets'][ticker] = {'error': 'OOS too short'}
            continue

        # Evaluate
        evaluation = evaluate_results(oos_data)

        # Print summary
        print(f"\n  === VaR Backtest Results for {ticker} ===")
        for alpha in [0.01, 0.05]:
            print(f"\n  --- VaR {alpha*100:.0f}% ---")
            print(f"  {'Method':<20} {'Violations':>10} {'Rate':>8} {'Kupiec':>8} "
                  f"{'CC':>8} {'Basel':>8} {'Trinity':>8} {'AvgVaR%':>10}")
            print(f"  {'-'*82}")
            for method in oos_data['methods']:
                ev = evaluation[method][f'alpha_{alpha}']
                tri = ev['trinity']
                print(f"  {method:<20} {ev['n_violations']:>10} "
                      f"{ev['violation_rate']*100:>7.2f}% "
                      f"{'PASS' if tri['kupiec_pass'] else 'FAIL':>8} "
                      f"{'PASS' if tri['cc_pass'] else 'FAIL':>8} "
                      f"{tri['basel']:>8} "
                      f"{'PASS' if tri['trinity_pass'] else 'FAIL':>8} "
                      f"{ev['avg_var_pct']:>10.4f}")

        # Regime breakdown
        print(f"\n  === Coverage by Regime ({ticker}) ===")
        for alpha in [0.01, 0.05]:
            print(f"\n  VaR {alpha*100:.0f}%:")
            for method in oos_data['methods']:
                ev = evaluation[method][f'alpha_{alpha}']
                regime_cov = ev['regime_coverage']
                parts = []
                for reg in ['Low', 'Medium', 'High']:
                    if reg in regime_cov:
                        rc = regime_cov[reg]
                        parts.append(f"{reg}: {rc['violation_rate']*100:.2f}% "
                                     f"({rc['n_violations']}/{rc['n_days']})")
                print(f"  {method:<20} | {' | '.join(parts)}")

        # ES test results
        print(f"\n  === ES Backtest ({ticker}) ===")
        for alpha in [0.01, 0.05]:
            print(f"\n  ES {alpha*100:.0f}%:")
            print(f"  {'Method':<20} {'Z-stat':>10} {'p-value':>10} {'Pass':>6}")
            for method in oos_data['methods']:
                ev = evaluation[method][f'alpha_{alpha}']
                es = ev['es_test']
                print(f"  {method:<20} {es['z_stat']:>10.4f} "
                      f"{es['p_value']:>10.4f} "
                      f"{'PASS' if es['pass'] else 'FAIL':>6}")

        # Store results
        asset_result = {
            'n_obs': int(len(returns)),
            'data_period': f"{returns.index[0].strftime('%Y-%m-%d')} to "
                           f"{returns.index[-1].strftime('%Y-%m-%d')}",
            'descriptive': {
                'mean_return': round(float(returns.mean()), 6),
                'std': round(float(returns.std()), 6),
                'skewness': round(float(returns.skew()), 4),
                'kurtosis': round(float(returns.kurtosis()), 4),
                'vix_mean': round(float(vix.mean()), 2),
                'vix_min': round(float(vix.min()), 2),
                'vix_max': round(float(vix.max()), 2),
            },
            'n_oos': oos_data['n_oos'],
            'oos_period': f"{oos_data['oos_dates'][0]} to {oos_data['oos_dates'][-1]}",
            'regime_distribution': {
                'Low': sum(1 for r in oos_data['oos_regimes'] if r == 'Low'),
                'Medium': sum(1 for r in oos_data['oos_regimes'] if r == 'Medium'),
                'High': sum(1 for r in oos_data['oos_regimes'] if r == 'High'),
            },
            'evaluation': evaluation
        }

        all_results['assets'][ticker] = asset_result

    # ============================================================
    # Cross-asset summary
    # ============================================================
    print("\n" + "=" * 70)
    print("CROSS-ASSET SUMMARY")
    print("=" * 70)

    # Count Trinity passes per method
    trinity_summary = {}
    for method in all_results['assets'].get('SPY', {}).get('evaluation', {}).keys():
        trinity_summary[method] = {}

    for alpha in [0.01, 0.05]:
        print(f"\n  VaR {alpha*100:.0f}% Trinity PASS count (out of {len(ASSETS)} assets):")
        for method in ['Normal', 'Student-t', 'HistSim'] + [f'RWC_lam{l}' for l in LAMBDA_VALUES if l > 0]:
            passes = 0
            total = 0
            for ticker in ASSETS:
                asset_data = all_results['assets'].get(ticker, {})
                if 'evaluation' in asset_data:
                    ev = asset_data['evaluation'].get(method, {}).get(f'alpha_{alpha}', {})
                    tri = ev.get('trinity', {})
                    if tri.get('trinity_pass', False):
                        passes += 1
                    total += 1
            print(f"  {method:<20}: {passes}/{total}")

    # Capital efficiency comparison
    print(f"\n  Capital Efficiency (avg VaR% at 1% level):")
    for method in ['Normal', 'Student-t', 'HistSim'] + [f'RWC_lam{l}' for l in LAMBDA_VALUES if l > 0]:
        vals = []
        for ticker in ASSETS:
            asset_data = all_results['assets'].get(ticker, {})
            if 'evaluation' in asset_data:
                ev = asset_data['evaluation'].get(method, {}).get('alpha_0.01', {})
                if 'avg_var_pct' in ev:
                    vals.append(ev['avg_var_pct'])
        if vals:
            print(f"  {method:<20}: {np.mean(vals):.4f}% (avg across assets)")

    # Key findings
    print("\n  === KEY FINDINGS ===")
    # Check if any RWC beats HistSim
    for ticker in ASSETS:
        asset_data = all_results['assets'].get(ticker, {})
        if 'evaluation' not in asset_data:
            continue
        for alpha in [0.01, 0.05]:
            hs_ev = asset_data['evaluation'].get('HistSim', {}).get(f'alpha_{alpha}', {})
            hs_trinity = hs_ev.get('trinity', {}).get('trinity_pass', False)
            hs_avg_var = hs_ev.get('avg_var_pct', 0)

            for lam in LAMBDA_VALUES:
                if lam <= 0:
                    continue
                method = f'RWC_lam{lam}'
                rwc_ev = asset_data['evaluation'].get(method, {}).get(f'alpha_{alpha}', {})
                rwc_trinity = rwc_ev.get('trinity', {}).get('trinity_pass', False)
                rwc_avg_var = rwc_ev.get('avg_var_pct', 0)

                # Tighter = less negative = closer to 0
                if rwc_trinity and abs(rwc_avg_var) < abs(hs_avg_var):
                    improvement = (1 - abs(rwc_avg_var) / abs(hs_avg_var)) * 100
                    print(f"  {ticker} VaR{alpha*100:.0f}%: {method} tighter than HistSim "
                          f"by {improvement:.1f}% while maintaining Trinity PASS")

    # Save results
    with open(RESULTS_PATH, 'w') as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to: {RESULTS_PATH}")

    return all_results


if __name__ == '__main__':
    main()
