#!/usr/bin/env python3
"""
K885: EVT-VaR — Extreme Value Theory for Tail Risk
=====================================================
[提出: 用戶, 執行: Claude]

Background:
  K824v2/K825/K829 established GJR + Historical Simulation as the VaR champion
  and Student-t as second best. But we have NEVER tested Extreme Value Theory
  (EVT), which is the theoretical gold standard for tail modeling.

Methods (6 total):
  M1: GJR + Normal VaR (baseline, often fails)
  M2: GJR + Student-t VaR (strong baseline, scale=sqrt((df-2)/df))
  M3: GJR + Historical Simulation (current champion from K824v2/K829)
  M4: GJR + Skewed-t (Hansen 1994, captures asymmetry)
  M5: EVT-PoT (Peaks-over-Threshold, pure GPD on raw returns)
  M6: GJR + EVT-PoT (McNeil & Frey 2000 two-step: GARCH filter + GPD on residuals)

Data:
  - Assets: SPY, QQQ, GLD, EEM, 0050.TW (5 assets)
  - Source: yfinance
  - OOS: 2019-01-01 to 2024-12-31
  - Expanding window, refit every 63 trading days

Evaluation:
  - VaR: Kupiec (1995) + Christoffersen (1998) + Basel traffic light + Trinity
  - ES: Acerbi-Szekely (2014) Z2 test (bootstrap p-value)
  - Joint: Fissler-Ziegel (2016) joint scoring
  - Capital efficiency: average VaR width (tighter = more efficient)

Error Log rules applied:
  - 0050.TW: must use clean_tw50_data from volpred.utils
  - Student-t: scale=sqrt((df-2)/df) per-refit df
  - Basel: standard 250-day window
  - GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])
  - EVT threshold: 10th percentile of losses (standard choice per McNeil & Frey 2000)

References:
  - McNeil, A.J. & Frey, R. (2000). Estimation of tail-related risk measures for
    heteroscedastic financial time series. J Empirical Finance, 7(3-4), 271-300.
  - Embrechts, P., Klüppelberg, C. & Mikosch, T. (1997). Modelling extremal events.
  - Acerbi, C. & Szekely, B. (2014). Back-testing expected shortfall. Risk.
  - Fissler, T. & Ziegel, J.F. (2016). Higher order elicitability. Ann Statistics.
  - Hansen, B.E. (1994). Autoregressive conditional density estimation. Int Econ Rev.
  - K824v2: SPY HistSim Trinity PASS, Student-t second best
  - K829: Cross-asset validation (QQQ, GLD, BTC-USD, 0050.TW)

Author: VolPred Research System
Date: 2026-04-05
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf
from numba import njit
from scipy.optimize import minimize
from scipy.stats import norm, t as t_dist, chi2, skew, kurtosis, genpareto
from scipy.special import gammaln

warnings.filterwarnings('ignore')

# Add project root for volpred.utils
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k885_evt_var_results.json')
OOS_START = '2019-01-01'
OOS_END = '2024-12-31'
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
HISTSIM_WINDOW = 500
EVT_THRESHOLD_QUANTILE = 0.10  # 10th percentile of losses for PoT threshold

ASSETS = {
    'SPY': {'name': 'S&P 500 ETF', 'start': '2000-01-01'},
    'QQQ': {'name': 'Invesco QQQ (Nasdaq-100)', 'start': '2000-01-01'},
    'GLD': {'name': 'SPDR Gold Trust', 'start': '2004-11-18'},
    'EEM': {'name': 'iShares MSCI Emerging Markets', 'start': '2004-01-01'},
    '0050.TW': {'name': 'Taiwan 50 ETF', 'start': '2003-06-30'},
}

np.random.seed(42)


# ==============================================================
# A. Numba-accelerated GJR-GARCH variance filter
# ==============================================================

@njit(cache=True)
def gjr_filter(r, omega, alpha, beta, gamma):
    """GJR-GARCH(1,1): sigma2_t = omega + (alpha + gamma*I_{r<0})*r2_{t-1} + beta*sigma2_{t-1}"""
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
    """sigma2_{t+1} given data up to t."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    ind = 1.0 if r[-1] < 0 else 0.0
    f = (params['omega']
         + (params['alpha'] + params['gamma'] * ind) * r[-1] ** 2
         + params['beta'] * s2[-1])
    return max(f, 1e-12)


def compute_standardized_residuals(returns, params):
    """z_t = r_t / sigma_t for in-sample data."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    s2 = gjr_filter(r, params['omega'], params['alpha'],
                    params['beta'], params['gamma'])
    sigma = np.sqrt(np.maximum(s2, 1e-16))
    z = r / sigma
    return z[1:]  # skip first (variance initialized from sample)


# ==============================================================
# D. Student-t df estimation (with correct scale)
# ==============================================================

def estimate_t_df(std_residuals, df_min=2.1, df_max=30.0):
    """MLE for Student-t df. Uses scale=sqrt((df-2)/df) so unit variance."""
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
# E. Skewed-t distribution (Hansen 1994)
# ==============================================================

def skewed_t_logpdf(z, eta, lam):
    """Log-pdf of Hansen (1994) skewed-t distribution.

    eta > 2 = degrees of freedom
    -1 < lam < 1 = skewness parameter

    Returns log-pdf values for standardized residuals z.
    """
    # Constants
    c = np.exp(gammaln((eta + 1) / 2) - gammaln(eta / 2)) / np.sqrt(np.pi * (eta - 2))
    a = 4 * lam * c * ((eta - 2) / (eta - 1))
    b = np.sqrt(1 + 3 * lam**2 - a**2)

    # Density
    y = b * z + a
    logf = np.where(
        y < 0,
        np.log(b) + np.log(c) - ((eta + 1) / 2) * np.log(1 + (y / (1 - lam))**2 / (eta - 2)),
        np.log(b) + np.log(c) - ((eta + 1) / 2) * np.log(1 + (y / (1 + lam))**2 / (eta - 2))
    )
    return logf


def estimate_skewed_t(std_residuals, eta_min=2.1, eta_max=30.0):
    """MLE for Hansen (1994) skewed-t parameters (eta, lambda)."""
    z = np.asarray(std_residuals, dtype=np.float64)
    z = z[np.isfinite(z)]
    if len(z) < 50:
        return 5.0, 0.0

    def neg_loglik(params):
        log_eta, lam = params
        eta = np.exp(log_eta)
        if eta < eta_min or eta > eta_max or abs(lam) >= 0.99:
            return 1e10
        ll = np.sum(skewed_t_logpdf(z, eta, lam))
        return -ll if np.isfinite(ll) else 1e10

    best_nll = 1e10
    best_params = (5.0, 0.0)
    for eta_init in [4.0, 7.0, 12.0]:
        for lam_init in [-0.1, 0.0, 0.1]:
            try:
                res = minimize(neg_loglik, x0=[np.log(eta_init), lam_init],
                               method='L-BFGS-B',
                               bounds=[(np.log(eta_min), np.log(eta_max)), (-0.95, 0.95)],
                               options={'maxiter': 1000})
                if res.fun < best_nll:
                    best_nll = res.fun
                    best_params = (float(np.exp(res.x[0])), float(res.x[1]))
            except Exception:
                continue

    return best_params


def skewed_t_quantile(alpha, eta, lam, n_grid=100000):
    """Numerical quantile of Hansen (1994) skewed-t via grid search.

    For alpha=0.01 or 0.05, this is efficient enough.
    """
    # Generate grid of z values
    z_grid = np.linspace(-8, 8, n_grid)
    logpdf = skewed_t_logpdf(z_grid, eta, lam)
    pdf = np.exp(logpdf)
    # Numerical CDF via trapezoidal
    dz = z_grid[1] - z_grid[0]
    cdf = np.cumsum(pdf) * dz
    cdf /= cdf[-1]  # normalize
    # Find quantile
    idx = np.searchsorted(cdf, alpha)
    idx = min(max(idx, 0), len(z_grid) - 1)
    return float(z_grid[idx])


# ==============================================================
# F. EVT: Peaks-over-Threshold with GPD
# ==============================================================

def fit_gpd_pot(losses, threshold_quantile=0.10):
    """Fit GPD to exceedances over threshold via MLE.

    losses: array of positive values (e.g., -returns for left tail)
    threshold_quantile: quantile of losses to use as threshold

    Returns: (xi, sigma_u, u, n_exceedances, N_total) or None if fails
    """
    losses = np.asarray(losses, dtype=np.float64)
    losses = losses[np.isfinite(losses)]

    if len(losses) < 50:
        return None

    # Threshold: quantile of losses
    u = float(np.quantile(losses, 1 - threshold_quantile))

    # Exceedances
    exceedances = losses[losses > u] - u
    n_exc = len(exceedances)

    if n_exc < 15:
        return None

    # Fit GPD via scipy MLE
    try:
        # genpareto.fit returns (c, loc, scale) where c = shape (xi)
        # Fix loc=0 since exceedances are already shifted
        xi, _, sigma_u = genpareto.fit(exceedances, floc=0)

        # Sanity checks
        if sigma_u <= 0 or xi < -0.5 or xi > 2.0:
            return None

        return {
            'xi': float(xi),
            'sigma_u': float(sigma_u),
            'u': float(u),
            'n_exceedances': int(n_exc),
            'N_total': int(len(losses)),
        }
    except Exception:
        return None


def evt_var(gpd_params, alpha):
    """EVT VaR using GPD tail model.

    VaR_alpha = u + (sigma_u / xi) * [(N/N_u * (1-alpha))^(-xi) - 1]

    For alpha < threshold proportion, this extrapolates into the tail.
    """
    if gpd_params is None:
        return np.nan

    xi = gpd_params['xi']
    sigma_u = gpd_params['sigma_u']
    u = gpd_params['u']
    n_exc = gpd_params['n_exceedances']
    N = gpd_params['N_total']

    # Tail fraction
    Fu = n_exc / N

    if abs(xi) < 1e-8:
        # xi ≈ 0: exponential tail
        var = u + sigma_u * np.log(Fu / alpha)
    else:
        var = u + (sigma_u / xi) * ((Fu / alpha)**xi - 1)

    return float(var)


def evt_es(gpd_params, alpha):
    """EVT Expected Shortfall.

    ES_alpha = VaR_alpha / (1 - xi) + (sigma_u - xi * u) / (1 - xi)
    Valid for xi < 1.
    """
    if gpd_params is None:
        return np.nan

    xi = gpd_params['xi']
    sigma_u = gpd_params['sigma_u']
    u = gpd_params['u']

    var = evt_var(gpd_params, alpha)
    if not np.isfinite(var):
        return np.nan

    if xi >= 1.0:
        return np.nan  # ES undefined for xi >= 1

    es = var / (1 - xi) + (sigma_u - xi * u) / (1 - xi)
    return float(es)


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

    traffic, n_viol_window, window_size = basel_traffic_light_250(
        violations, alpha_var=alpha_var)

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
# H. ES Backtest: Acerbi-Szekely (2014) Z2 Test
# ==============================================================

def acerbi_szekely_z2(returns, var_series, es_series, alpha_var=0.01, n_bootstrap=1000):
    """Acerbi & Szekely (2014) Z2 statistic for ES backtesting.

    Z2 = (1/T) * sum_{t: r_t < VaR_t} (r_t / ES_t) / alpha + 1
    Under H0 (correct ES), E[Z2] = 0.

    Bootstrap p-value: fraction of bootstrap Z2 <= observed Z2.
    """
    r = np.asarray(returns, dtype=np.float64)
    var_arr = np.asarray(var_series, dtype=np.float64)
    es_arr = np.asarray(es_series, dtype=np.float64)

    T = len(r)
    if T < 50:
        return {'z2_stat': np.nan, 'p_value': np.nan}

    violations = r < var_arr
    n_viol = int(violations.sum())

    if n_viol == 0:
        return {'z2_stat': 0.0, 'p_value': 1.0, 'n_violations': 0}

    # Z2 statistic
    # es_arr is negative (loss), r is negative when violated
    z2 = (1.0 / T) * np.sum(r[violations] / es_arr[violations]) / alpha_var + 1.0

    # Bootstrap p-value
    rng = np.random.RandomState(42)
    z2_boot = np.zeros(n_bootstrap)
    for b in range(n_bootstrap):
        idx = rng.choice(T, size=T, replace=True)
        r_b = r[idx]
        var_b = var_arr[idx]
        es_b = es_arr[idx]
        viol_b = r_b < var_b
        n_viol_b = int(viol_b.sum())
        if n_viol_b == 0:
            z2_boot[b] = 0.0
        else:
            z2_boot[b] = (1.0 / T) * np.sum(r_b[viol_b] / es_b[viol_b]) / alpha_var + 1.0

    # p-value: proportion of bootstrap z2 <= observed z2
    # Under H0, Z2 should be around 0; large negative = ES is too optimistic
    p_value = float(np.mean(z2_boot <= z2))

    return {
        'z2_stat': round(float(z2), 4),
        'p_value': round(p_value, 4),
        'n_violations': n_viol,
        'pass': bool(p_value > 0.05),
    }


# ==============================================================
# I. Fissler-Ziegel (2016) Joint VaR-ES Score
# ==============================================================

def fissler_ziegel_score(returns, var_series, es_series, alpha_var=0.01):
    """Fissler-Ziegel (2016) joint VaR-ES scoring function.

    S(VaR, ES, r) = (1/alpha)*I(r<VaR)*(VaR - r) - VaR + ES + (1/ES)*(-1/(2*alpha))*(I(r<VaR)*(r-VaR)^2) - (ES/2)

    Simplified: we use the consistent scoring function S1 from Fissler & Ziegel (2016).
    Lower score = better.
    """
    r = np.asarray(returns, dtype=np.float64)
    var_arr = np.asarray(var_series, dtype=np.float64)
    es_arr = np.asarray(es_series, dtype=np.float64)

    T = len(r)
    if T < 50:
        return np.nan

    violations = (r < var_arr).astype(float)

    # FZ loss function (homogeneous of degree 0)
    # S_t = -1/alpha * I(r_t < VaR_t) * (r_t - VaR_t) + VaR_t - ES_t
    #        + ES_t * log(-ES_t) - 1/alpha * I(r_t < VaR_t) * (r_t - VaR_t) / ES_t
    # We use a simplified version that is still strictly consistent:

    score = np.zeros(T)
    for t in range(T):
        v = var_arr[t]
        e = es_arr[t]
        if e >= 0 or not np.isfinite(e):
            score[t] = np.nan
            continue

        indicator = 1.0 if r[t] < v else 0.0
        # FZ score (consistent for (VaR, ES) pair)
        score[t] = (
            -(1.0 / alpha_var) * indicator * (r[t] - v) / e
            - v / e
            + np.log(-e)
            - 1.0
        )

    valid = np.isfinite(score)
    if valid.sum() < 50:
        return np.nan

    return float(np.mean(score[valid]))


# ==============================================================
# J. ES computation for each method
# ==============================================================

def normal_es(sigma, alpha):
    """ES under Normal assumption."""
    z_alpha = norm.ppf(alpha)
    es = -sigma * norm.pdf(z_alpha) / alpha
    return float(es)


def student_t_es(sigma, df, alpha):
    """ES under Student-t assumption with proper scale correction."""
    if df <= 2:
        return np.nan
    scale = np.sqrt((df - 2.0) / df)
    z_alpha = t_dist.ppf(alpha, df=df, loc=0, scale=scale)
    # ES = -sigma * [t_pdf(z_alpha; df) / alpha] * [(df + z_alpha^2/scale^2) / (df - 1)] * scale
    # Simplified: ES = sigma * E[-z | z < z_alpha] where z ~ scaled t
    # For standardized t: ES = -sigma * t_pdf(t_inv_alpha) * (df + t_inv_alpha^2) / ((df-1)*alpha)
    t_quantile = t_dist.ppf(alpha, df=df)
    es_standardized = -t_dist.pdf(t_quantile, df=df) * (df + t_quantile**2) / ((df - 1) * alpha)
    # Scale correction
    es = sigma * scale * es_standardized
    return float(es)


def histsim_es(sigma, std_residuals, alpha):
    """ES from empirical distribution of standardized residuals."""
    z = np.asarray(std_residuals, dtype=np.float64)
    z_sorted = np.sort(z)
    n = len(z_sorted)
    n_tail = max(int(np.floor(alpha * n)), 1)
    es_z = float(np.mean(z_sorted[:n_tail]))
    return float(sigma * es_z)


def skewed_t_es(sigma, eta, lam, alpha, n_grid=100000):
    """ES from Hansen (1994) skewed-t via numerical integration."""
    z_grid = np.linspace(-8, 8, n_grid)
    logpdf = skewed_t_logpdf(z_grid, eta, lam)
    pdf = np.exp(logpdf)
    dz = z_grid[1] - z_grid[0]
    cdf = np.cumsum(pdf) * dz
    cdf_norm = cdf / cdf[-1]

    # Find VaR quantile
    idx_var = np.searchsorted(cdf_norm, alpha)
    idx_var = min(max(idx_var, 1), len(z_grid) - 1)

    # ES = E[z | z < VaR_z] (integrate z*f(z) for z < var_z)
    tail_pdf = pdf[:idx_var]
    tail_z = z_grid[:idx_var]
    if len(tail_pdf) < 2:
        return np.nan

    es_z = float(np.sum(tail_z * tail_pdf) * dz / (np.sum(tail_pdf) * dz))
    return float(sigma * es_z)


# ==============================================================
# K. Per-asset VaR computation (expanding window OOS)
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
    df = yf.download(ticker, start=data_start, end='2025-01-01', progress=False)
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

    # Filter extreme returns (>50% daily = data error)
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

    # Methods: normal, student_t, histsim, skewed_t, evt_pot, garch_evt
    METHOD_KEYS = ['normal', 'student_t', 'histsim', 'skewed_t', 'evt_pot', 'garch_evt']

    # Storage for VaR and ES forecasts
    var_forecasts = {alpha: {m: [] for m in METHOD_KEYS} for alpha in ALPHA_LEVELS}
    es_forecasts = {alpha: {m: [] for m in METHOD_KEYS} for alpha in ALPHA_LEVELS}

    current_params = None
    current_z = None
    current_df_t = None
    current_skew_params = None
    current_gpd_raw = None  # For pure EVT-PoT
    current_gpd_resid = None  # For GARCH+EVT
    last_refit = -999
    n_refits = 0

    print(f"  [2] Running expanding window OOS forecast...")
    for i in range(oos_start_idx, oos_end_idx):
        day_idx = i - oos_start_idx

        # Refit?
        if day_idx - last_refit >= REFIT_EVERY or current_params is None:
            train_r = all_returns[:i]  # data up to (but not including) day i

            # Fit GJR-GARCH
            params = fit_gjr(train_r)
            if params is not None:
                current_params = params
                current_z = compute_standardized_residuals(train_r, params)
                current_df_t = estimate_t_df(current_z)
                current_skew_params = estimate_skewed_t(current_z)

                # EVT on standardized residuals (GARCH+EVT: McNeil & Frey 2000)
                # Use negative residuals as losses
                z_losses = -current_z  # positive = loss
                current_gpd_resid = fit_gpd_pot(z_losses,
                                                 threshold_quantile=EVT_THRESHOLD_QUANTILE)

                n_refits += 1
                last_refit = day_idx

            # Pure EVT-PoT on raw returns (no GARCH filter)
            # Use negative returns as losses
            raw_losses = -train_r  # positive = loss
            current_gpd_raw = fit_gpd_pot(raw_losses,
                                           threshold_quantile=EVT_THRESHOLD_QUANTILE)

        if current_params is None:
            for alpha in ALPHA_LEVELS:
                for m in METHOD_KEYS:
                    var_forecasts[alpha][m].append(np.nan)
                    es_forecasts[alpha][m].append(np.nan)
            continue

        # One-step forecast: sigma2_{t+1|t}
        train_r = all_returns[:i]
        sigma2_f = gjr_one_step_forecast(train_r, current_params)
        sigma_f = np.sqrt(sigma2_f)

        for alpha in ALPHA_LEVELS:
            # M1: Normal VaR & ES
            z_normal = norm.ppf(alpha)
            var_normal = sigma_f * z_normal
            es_normal = normal_es(sigma_f, alpha)
            var_forecasts[alpha]['normal'].append(float(var_normal))
            es_forecasts[alpha]['normal'].append(float(es_normal))

            # M2: Student-t VaR & ES
            scale_t = np.sqrt((current_df_t - 2.0) / current_df_t) if current_df_t > 2 else 1.0
            z_t = t_dist.ppf(alpha, df=current_df_t, loc=0.0, scale=scale_t)
            var_student = sigma_f * z_t
            es_student = student_t_es(sigma_f, current_df_t, alpha)
            var_forecasts[alpha]['student_t'].append(float(var_student))
            es_forecasts[alpha]['student_t'].append(float(es_student))

            # M3: HistSim VaR & ES
            z_hist = np.percentile(current_z, alpha * 100)
            var_histsim = sigma_f * z_hist
            es_hist = histsim_es(sigma_f, current_z, alpha)
            var_forecasts[alpha]['histsim'].append(float(var_histsim))
            es_forecasts[alpha]['histsim'].append(float(es_hist))

            # M4: Skewed-t VaR & ES
            eta, lam = current_skew_params
            z_skt = skewed_t_quantile(alpha, eta, lam)
            var_skt = sigma_f * z_skt
            es_skt = skewed_t_es(sigma_f, eta, lam, alpha)
            var_forecasts[alpha]['skewed_t'].append(float(var_skt))
            es_forecasts[alpha]['skewed_t'].append(float(es_skt))

            # M5: Pure EVT-PoT (on raw returns, no GARCH)
            if current_gpd_raw is not None:
                evt_var_raw = evt_var(current_gpd_raw, alpha)
                evt_es_raw = evt_es(current_gpd_raw, alpha)
                # EVT models losses (positive), convert back to returns (negative)
                var_forecasts[alpha]['evt_pot'].append(float(-evt_var_raw))
                es_forecasts[alpha]['evt_pot'].append(float(-evt_es_raw))
            else:
                var_forecasts[alpha]['evt_pot'].append(np.nan)
                es_forecasts[alpha]['evt_pot'].append(np.nan)

            # M6: GARCH + EVT (McNeil & Frey 2000)
            if current_gpd_resid is not None:
                evt_var_z = evt_var(current_gpd_resid, alpha)
                evt_es_z = evt_es(current_gpd_resid, alpha)
                if np.isfinite(evt_var_z):
                    # VaR = sigma_t * VaR(z) where VaR(z) from GPD of standardized residuals
                    # evt_var_z is a positive loss quantile, convert to negative return
                    var_forecasts[alpha]['garch_evt'].append(float(-sigma_f * evt_var_z))
                    if np.isfinite(evt_es_z):
                        es_forecasts[alpha]['garch_evt'].append(float(-sigma_f * evt_es_z))
                    else:
                        es_forecasts[alpha]['garch_evt'].append(np.nan)
                else:
                    var_forecasts[alpha]['garch_evt'].append(np.nan)
                    es_forecasts[alpha]['garch_evt'].append(np.nan)
            else:
                var_forecasts[alpha]['garch_evt'].append(np.nan)
                es_forecasts[alpha]['garch_evt'].append(np.nan)

    print(f"  Refits: {n_refits}, OOS forecasts: {len(var_forecasts[0.01]['normal'])}")

    # 5. Backtest each method at each alpha
    results = {
        'ticker': ticker,
        'name': name,
        'n_oos': n_oos,
        'n_refits': n_refits,
        'oos_stats': stats,
        'var_results': {},
        'es_results': {},
        'fz_scores': {},
    }

    oos_r = oos_returns.values
    method_display = {
        'normal': 'Normal',
        'student_t': 'Student-t',
        'histsim': 'HistSim',
        'skewed_t': 'Skewed-t',
        'evt_pot': 'EVT-PoT',
        'garch_evt': 'GARCH+EVT',
    }

    for alpha in ALPHA_LEVELS:
        alpha_key = f"{alpha:.0%}"
        results['var_results'][alpha_key] = {}
        results['es_results'][alpha_key] = {}
        results['fz_scores'][alpha_key] = {}

        for method_key, method_name in method_display.items():
            var_arr = np.array(var_forecasts[alpha][method_key])
            es_arr = np.array(es_forecasts[alpha][method_key])

            # Only use non-nan positions
            valid = np.isfinite(var_arr) & np.isfinite(es_arr)
            if valid.sum() < 50:
                results['var_results'][alpha_key][method_name] = {'error': 'insufficient valid forecasts'}
                results['es_results'][alpha_key][method_name] = {'error': 'insufficient valid forecasts'}
                results['fz_scores'][alpha_key][method_name] = np.nan
                continue

            # VaR backtest
            bt = var_backtest(oos_r[valid], var_arr[valid], alpha_var=alpha)
            bt['avg_var_width'] = round(float(np.mean(np.abs(var_arr[valid]))), 6)
            results['var_results'][alpha_key][method_name] = bt

            # ES backtest (Acerbi-Szekely Z2)
            es_bt = acerbi_szekely_z2(oos_r[valid], var_arr[valid], es_arr[valid],
                                       alpha_var=alpha, n_bootstrap=1000)
            results['es_results'][alpha_key][method_name] = es_bt

            # Fissler-Ziegel joint score
            fz = fissler_ziegel_score(oos_r[valid], var_arr[valid], es_arr[valid],
                                       alpha_var=alpha)
            results['fz_scores'][alpha_key][method_name] = round(fz, 6) if np.isfinite(fz) else None

            status = "PASS" if bt['trinity_pass'] else "FAIL"
            es_status = "PASS" if es_bt.get('pass', False) else "FAIL"
            print(f"  {alpha_key} {method_name:12s}: {bt['n_violations']}/{bt['n_total']} "
                  f"({bt['violation_rate']:.4f}), Basel={bt['basel_traffic_light']}, "
                  f"Trinity={status}, ES={es_status}, "
                  f"FZ={fz:.4f}" if np.isfinite(fz) else
                  f"  {alpha_key} {method_name:12s}: {bt['n_violations']}/{bt['n_total']} "
                  f"({bt['violation_rate']:.4f}), Basel={bt['basel_traffic_light']}, "
                  f"Trinity={status}, ES={es_status}, FZ=N/A")

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
    print("K885: EVT-VaR — Extreme Value Theory for Tail Risk")
    print("  Assets: SPY, QQQ, GLD, EEM, 0050.TW")
    print("  Methods: Normal, Student-t, HistSim, Skewed-t, EVT-PoT, GARCH+EVT")
    print(f"  OOS: {OOS_START} ~ {OOS_END}")
    print(f"  Refit: every {REFIT_EVERY} trading days")
    print(f"  EVT threshold: {EVT_THRESHOLD_QUANTILE:.0%} quantile")
    print("=" * 70)

    all_results = {}
    for ticker, info in ASSETS.items():
        result = run_asset_var(ticker, info)
        if result is not None:
            all_results[ticker] = result

    # ==============================================================
    # Summary Tables
    # ==============================================================
    print("\n" + "=" * 70)
    print("SUMMARY: Trinity Pass/Fail + ES Pass/Fail")
    print("=" * 70)

    method_names = ['Normal', 'Student-t', 'HistSim', 'Skewed-t', 'EVT-PoT', 'GARCH+EVT']

    for alpha_key in ['1%', '5%']:
        print(f"\n  === {alpha_key} VaR Trinity ===")
        header = f"  {'Asset':<12}"
        for m in method_names:
            header += f" {m:<12}"
        print(header)
        print(f"  {'-'*len(header)}")

        for ticker in all_results:
            row = f"  {ticker:<12}"
            for m in method_names:
                bt = all_results[ticker]['var_results'].get(alpha_key, {}).get(m, {})
                if 'error' in bt:
                    row += f" {'ERROR':<12}"
                elif bt.get('trinity_pass', False):
                    row += f" {'PASS':<12}"
                else:
                    vr = bt.get('violation_rate', 0)
                    row += f" {'FAIL':>4} {vr:.3f}  "
            print(row)

    # ES results
    for alpha_key in ['1%', '5%']:
        print(f"\n  === {alpha_key} ES Acerbi-Szekely ===")
        header = f"  {'Asset':<12}"
        for m in method_names:
            header += f" {m:<12}"
        print(header)
        print(f"  {'-'*len(header)}")

        for ticker in all_results:
            row = f"  {ticker:<12}"
            for m in method_names:
                es_bt = all_results[ticker]['es_results'].get(alpha_key, {}).get(m, {})
                if 'error' in es_bt:
                    row += f" {'ERROR':<12}"
                elif es_bt.get('pass', False):
                    z2 = es_bt.get('z2_stat', 0)
                    row += f" {'PASS':>4} {z2:+.2f}  "
                else:
                    z2 = es_bt.get('z2_stat', 0)
                    row += f" {'FAIL':>4} {z2:+.2f}  "
            print(row)

    # FZ scores
    for alpha_key in ['1%', '5%']:
        print(f"\n  === {alpha_key} Fissler-Ziegel Joint Score (lower=better) ===")
        header = f"  {'Asset':<12}"
        for m in method_names:
            header += f" {m:<12}"
        print(header)
        print(f"  {'-'*len(header)}")

        for ticker in all_results:
            row = f"  {ticker:<12}"
            for m in method_names:
                fz = all_results[ticker]['fz_scores'].get(alpha_key, {}).get(m)
                if fz is not None:
                    row += f" {fz:<12.4f}"
                else:
                    row += f" {'N/A':<12}"
            print(row)

    # Capital efficiency (average VaR width)
    for alpha_key in ['1%', '5%']:
        print(f"\n  === {alpha_key} Capital Efficiency (Avg VaR Width, lower=tighter) ===")
        header = f"  {'Asset':<12}"
        for m in method_names:
            header += f" {m:<12}"
        print(header)
        print(f"  {'-'*len(header)}")

        for ticker in all_results:
            row = f"  {ticker:<12}"
            for m in method_names:
                bt = all_results[ticker]['var_results'].get(alpha_key, {}).get(m, {})
                w = bt.get('avg_var_width')
                if w is not None:
                    row += f" {w:<12.4f}"
                else:
                    row += f" {'N/A':<12}"
            print(row)

    # Overall pass rates
    print(f"\n  === Overall VaR Trinity Pass Rates ===")
    for m in method_names:
        total = 0
        passed = 0
        for ticker in all_results:
            for alpha_key in ['1%', '5%']:
                bt = all_results[ticker]['var_results'].get(alpha_key, {}).get(m, {})
                if 'error' not in bt:
                    total += 1
                    if bt.get('trinity_pass', False):
                        passed += 1
        rate = passed / total if total > 0 else 0
        print(f"  {m:<12}: {passed}/{total} ({rate:.0%})")

    print(f"\n  === Overall ES Acerbi-Szekely Pass Rates ===")
    for m in method_names:
        total = 0
        passed = 0
        for ticker in all_results:
            for alpha_key in ['1%', '5%']:
                es_bt = all_results[ticker]['es_results'].get(alpha_key, {}).get(m, {})
                if 'error' not in es_bt:
                    total += 1
                    if es_bt.get('pass', False):
                        passed += 1
        rate = passed / total if total > 0 else 0
        print(f"  {m:<12}: {passed}/{total} ({rate:.0%})")

    # Best FZ scores across assets
    print(f"\n  === Average FZ Score Across Assets ===")
    for alpha_key in ['1%', '5%']:
        print(f"  {alpha_key}:")
        for m in method_names:
            scores = []
            for ticker in all_results:
                fz = all_results[ticker]['fz_scores'].get(alpha_key, {}).get(m)
                if fz is not None:
                    scores.append(fz)
            if scores:
                print(f"    {m:<12}: {np.mean(scores):.4f} (n={len(scores)})")
            else:
                print(f"    {m:<12}: N/A")

    elapsed_total = time.time() - t0
    print(f"\n  Total elapsed: {elapsed_total:.1f}s")

    # ==============================================================
    # Build cross-asset summary
    # ==============================================================
    cross_asset_summary = {}
    for m in method_names:
        cross_asset_summary[m] = {
            'trinity_pass_1pct': 0,
            'trinity_pass_5pct': 0,
            'trinity_total_1pct': 0,
            'trinity_total_5pct': 0,
            'es_pass_1pct': 0,
            'es_pass_5pct': 0,
            'es_total_1pct': 0,
            'es_total_5pct': 0,
            'avg_fz_1pct': [],
            'avg_fz_5pct': [],
            'avg_var_width_1pct': [],
            'avg_var_width_5pct': [],
        }
        for ticker in all_results:
            for alpha_key, level in [('1%', '1pct'), ('5%', '5pct')]:
                bt = all_results[ticker]['var_results'].get(alpha_key, {}).get(m, {})
                if 'error' not in bt:
                    cross_asset_summary[m][f'trinity_total_{level}'] += 1
                    if bt.get('trinity_pass', False):
                        cross_asset_summary[m][f'trinity_pass_{level}'] += 1
                    w = bt.get('avg_var_width')
                    if w is not None:
                        cross_asset_summary[m][f'avg_var_width_{level}'].append(w)

                es_bt = all_results[ticker]['es_results'].get(alpha_key, {}).get(m, {})
                if 'error' not in es_bt:
                    cross_asset_summary[m][f'es_total_{level}'] += 1
                    if es_bt.get('pass', False):
                        cross_asset_summary[m][f'es_pass_{level}'] += 1

                fz = all_results[ticker]['fz_scores'].get(alpha_key, {}).get(m)
                if fz is not None:
                    cross_asset_summary[m][f'avg_fz_{level}'].append(fz)

    # Convert lists to means
    for m in cross_asset_summary:
        for key in list(cross_asset_summary[m].keys()):
            if isinstance(cross_asset_summary[m][key], list):
                vals = cross_asset_summary[m][key]
                cross_asset_summary[m][key] = round(float(np.mean(vals)), 6) if vals else None

    # ==============================================================
    # Save results
    # ==============================================================
    output = {
        'experiment_id': 'K885',
        'title': 'K885: EVT-VaR — Extreme Value Theory for Tail Risk',
        'type': 'empirical_analysis',
        'method': 'GJR-GARCH(1,1) expanding window + 6 VaR/ES methods including EVT-PoT',
        'oos_period': f'{OOS_START} to {OOS_END}',
        'refit_every': REFIT_EVERY,
        'alpha_levels': ALPHA_LEVELS,
        'evt_threshold_quantile': EVT_THRESHOLD_QUANTILE,
        'histsim_window': HISTSIM_WINDOW,
        'data_source': 'yfinance',
        'assets_tested': list(ASSETS.keys()),
        'methods': method_names,
        'error_log_rules': [
            '0050.TW: clean_tw50_data applied',
            'Student-t: scale=sqrt((df-2)/df) per-refit',
            'Basel: standard 250-day window',
            'GARCH OOS: recursive h[t]=f(h[t-1], r²[t-1])',
            'EVT threshold: 10th percentile of losses (McNeil & Frey 2000)',
        ],
        'references': [
            'McNeil & Frey (2000): Two-step GARCH+EVT, J Empirical Finance',
            'Embrechts, Klüppelberg & Mikosch (1997): EVT for finance',
            'Acerbi & Szekely (2014): ES backtesting, Risk',
            'Fissler & Ziegel (2016): Joint VaR-ES scoring, Ann Statistics',
            'Hansen (1994): Skewed-t, Int Econ Rev',
            'K824v2: SPY HistSim Trinity PASS, Student-t second best',
            'K829: Cross-asset validation',
        ],
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'elapsed_total_sec': round(elapsed_total, 1),
        'cross_asset_summary': cross_asset_summary,
        'assets': all_results,
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Results saved to: {RESULTS_PATH}")


if __name__ == '__main__':
    main()
