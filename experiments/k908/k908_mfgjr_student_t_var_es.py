#!/usr/bin/env python3
"""
K908: MF-GJR + Student-t Distribution — VaR/ES Complete Evaluation
===================================================================
[提出: Claude, 執行: Claude]

Background:
  K889/K889v2: MF-GJR improves QLIKE by -6.6% vs GJR, but 1% VaR ALL FAIL
  (Normal distribution underestimates tail risk).
  K802: GJR + Student-t fixed VaR Trinity PASS.
  K825: Historical Simulation competitive for VaR.

This experiment combines the best volatility model (MF-GJR) with the best
distribution (Student-t, HistSim) to achieve complete risk management:

  5 Models × 2 VaR levels × 3 assets:
    1. GJR + Normal
    2. GJR + Student-t
    3. MF-GJR + Normal
    4. MF-GJR + Student-t   ← expected winner
    5. MF-GJR + HistSim

  Full ES evaluation:
    - Acerbi & Szekely (2014) Z-test
    - Fissler & Ziegel (2016) joint VaR-ES scoring

Error log rules:
  - Student-t: MUST use scale sqrt((df-2)/df) for unit variance (K824 lesson)
  - Basel traffic light: standard thresholds (250d: Green<5, Yellow 5-9, Red>=10)
  - GARCH OOS: recursive h[t]=f(h[t-1], r^2[t-1])
  - DM test: use volpred.stats.model_evaluation.dm_test

Data:
  - Assets: SPY, QQQ, 0050.TW
  - Period: 2005-01-01 to 2026-04-01
  - OOS: 2019-01-01 to latest
  - VIX from yfinance (^VIX)
  - 0050.TW: clean_tw50_data (mandatory)

References:
  - Engle, Ghysels & Sohn (2013) RES 95(3):776-797
  - Patton (2011) J Econometrics 160:246-256
  - Harvey et al. (2016) JBES 34:92-104
  - McNeil & Frey (2000) J Empirical Finance 7:271-300
  - Acerbi & Szekely (2014) Risk Magazine
  - Fissler & Ziegel (2016) JASA 111:1048-1059
  - Kupiec (1995) J Derivatives 3(2):73-84
  - Christoffersen (1998) Int Economic Review 39(4):841-862

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
from scipy.stats import norm, t as t_dist, chi2
from numba import njit

warnings.filterwarnings('ignore')

START_TIME = time.time()
EXPERIMENT_ID = "K908"

# ============================================================
# Configuration
# ============================================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.utils import clean_tw50_data
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k908_mfgjr_student_t_var_es_results.json')

# Data parameters (same as K889v2 for comparability)
DATA_START = '2005-01-01'
DATA_END = '2026-04-01'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63
ALPHA_LEVELS = [0.01, 0.05]
ASSETS = ['SPY', 'QQQ', '0050.TW']

# VaR model names
VAR_MODELS = [
    'GJR+Normal',
    'GJR+Student-t',
    'MF-GJR+Normal',
    'MF-GJR+Student-t',
    'MF-GJR+HistSim',
]

print("=" * 70)
print(f"{EXPERIMENT_ID}: MF-GJR + Student-t Distribution — VaR/ES Complete Evaluation")
print("  Goal: Fix MF-GJR 1% VaR FAIL via Student-t / HistSim distribution")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING (from K889v2)
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf


def load_asset_data(ticker, vix_data):
    """Load asset data with VIX alignment (from K889v2, no double-lag)."""
    print(f"  Loading {ticker}...")
    raw = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    prices = raw['Close'].copy()
    log_ret = np.log(prices / prices.shift(1))

    if '0050' in ticker:
        prices, log_ret = clean_tw50_data(prices, log_ret)

    df = pd.DataFrame({'price': prices, 'log_ret': log_ret})
    df = df.dropna(subset=['log_ret'])
    df = df.join(vix_data, how='left')
    df['VIX'] = df['VIX'].ffill()
    df = df.dropna()

    return df


# Download VIX
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_data = vix_raw[['Close']].rename(columns={'Close': 'VIX'})

asset_data = {}
for ticker in ASSETS:
    asset_data[ticker] = load_asset_data(ticker, vix_data)
    d = asset_data[ticker]
    print(f"    {ticker}: {d.index[0].strftime('%Y-%m-%d')} to "
          f"{d.index[-1].strftime('%Y-%m-%d')}, n={len(d)}")

# ============================================================
# SECTION 2: DIAGNOSTICS
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


# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS (from K889v2, unchanged)
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
    """Fit MF-GARCH or MF-GJR (from K889v2, unchanged)."""
    n = len(returns)
    assert len(log_vix) == n

    r2 = returns ** 2
    r2_positive = np.maximum(r2, 1e-16)
    log_r2 = np.log(r2_positive)
    log_vix_lag = np.roll(log_vix, 1)
    log_vix_lag[0] = log_vix[0]

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


def forecast_mf_garch(params, returns, log_vix, model_type='garch'):
    """Generate in-sample sigma^2 from MF-GARCH/MF-GJR model."""
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


# ============================================================
# SECTION 4: STUDENT-t DISTRIBUTION FITTING
# ============================================================
print("\n[4] Student-t distribution fitting module...")


def fit_student_t(standardized_residuals):
    """Fit Student-t to standardized residuals using MLE.

    Returns (df, scale) where scale = sqrt((df-2)/df) for unit-variance t.

    IMPORTANT (K824 lesson): For VaR calculation, we need the quantile
    of a unit-variance Student-t. The standard Student-t with df degrees
    of freedom has variance = df/(df-2). To get unit variance:
      z ~ t(df) / sqrt(df/(df-2))
    Equivalently, VaR_alpha = sigma * t_ppf(alpha, df) * sqrt((df-2)/df)
    """
    z = standardized_residuals
    # Remove extreme outliers for stable fitting
    z_clean = z[np.isfinite(z) & (np.abs(z) < 10)]

    if len(z_clean) < 100:
        return 5.0, np.sqrt(3.0 / 5.0)  # fallback

    # MLE fit: fix loc=0, estimate df and scale jointly
    try:
        df_hat, loc_hat, scale_hat = t_dist.fit(z_clean, floc=0)
        # Ensure df > 2 (variance exists)
        df_hat = max(df_hat, 2.1)
        # The correct scale for unit-variance Student-t
        # If the original t(df) has variance = df/(df-2),
        # then z / sqrt(df/(df-2)) has variance 1
        # Correction factor: sqrt((df-2)/df)
        scale_correction = np.sqrt((df_hat - 2) / df_hat)
    except Exception:
        df_hat = 5.0
        scale_correction = np.sqrt(3.0 / 5.0)

    return float(df_hat), float(scale_correction)


def student_t_var(sigma, alpha, df):
    """Compute Student-t VaR.

    VaR_alpha = -sigma * t_ppf(alpha, df) * sqrt((df-2)/df)

    The sqrt((df-2)/df) correction ensures unit-variance t quantiles
    (K824 lesson: without this, VaR is overestimated).
    """
    q = t_dist.ppf(alpha, df=df)  # negative for left tail
    scale_correction = np.sqrt((df - 2) / df)
    return -sigma * q * scale_correction  # positive VaR


def student_t_es(sigma, alpha, df):
    """Compute Student-t ES (Expected Shortfall).

    ES_alpha = sigma * [t_pdf(t_ppf(alpha,df), df) / alpha] *
               [(df + t_ppf(alpha,df)^2) / (df - 1)] * sqrt((df-2)/df)

    Reference: McNeil & Frey (2000), Equation (14).
    """
    q = t_dist.ppf(alpha, df=df)  # negative
    pdf_at_q = t_dist.pdf(q, df=df)
    scale_correction = np.sqrt((df - 2) / df)
    es = sigma * (pdf_at_q / alpha) * ((df + q**2) / (df - 1)) * scale_correction
    return es  # positive ES


def normal_var(sigma, alpha):
    """Compute Normal VaR."""
    return -sigma * norm.ppf(alpha)  # positive VaR


def normal_es(sigma, alpha):
    """Compute Normal ES.

    ES_alpha = sigma * phi(z_alpha) / alpha
    """
    z = norm.ppf(alpha)
    return sigma * norm.pdf(z) / alpha  # positive ES


def histsim_var_es(standardized_residuals, sigma, alpha):
    """Compute Historical Simulation VaR and ES.

    VaR: quantile(z_IS, alpha) * sigma
    ES: mean of z_IS beyond quantile * sigma
    """
    z = standardized_residuals[np.isfinite(standardized_residuals)]
    if len(z) < 50:
        # Fallback to normal
        return normal_var(sigma, alpha), normal_es(sigma, alpha)

    q = np.quantile(z, alpha)  # negative
    var_hs = -q * sigma  # positive

    # ES: mean of residuals below the quantile
    tail = z[z <= q]
    if len(tail) > 0:
        es_hs = -np.mean(tail) * sigma  # positive
    else:
        es_hs = var_hs * 1.2  # fallback

    return var_hs, es_hs


# ============================================================
# SECTION 5: VaR/ES BACKTESTING FUNCTIONS
# ============================================================
print("\n[5] VaR/ES backtesting functions...")


def kupiec_test(violations, n_total, alpha):
    """Kupiec (1995) unconditional coverage LR test."""
    n_viol = int(np.sum(violations))
    p_hat = n_viol / n_total if n_total > 0 else 0

    if 0 < p_hat < 1:
        lr = 2 * (n_viol * np.log(p_hat / alpha) +
                  (n_total - n_viol) * np.log((1 - p_hat) / (1 - alpha)))
        p_value = 1 - chi2.cdf(max(0, lr), 1)
    elif p_hat == 0:
        p_value = 0.0 if alpha > 0 else 1.0
    else:
        p_value = 0.0

    return n_viol, p_hat, float(p_value)


def christoffersen_test(violations, n_total, kupiec_lr=None):
    """Christoffersen (1998) conditional coverage test."""
    n00 = n01 = n10 = n11 = 0
    for i in range(1, n_total):
        if not violations[i-1]:
            if not violations[i]:
                n00 += 1
            else:
                n01 += 1
        else:
            if not violations[i]:
                n10 += 1
            else:
                n11 += 1

    if (n00 + n01) > 0 and (n10 + n11) > 0:
        p01 = n01 / (n00 + n01)
        p11 = n11 / (n10 + n11)
        p_pool = (n01 + n11) / n_total if n_total > 0 else 0

        if 0 < p_pool < 1 and 0 < p01 < 1 and 0 < p11 < 1:
            lr_ind = 2 * (
                n00 * np.log(1 - p01) + n01 * np.log(p01) +
                n10 * np.log(1 - p11) + n11 * np.log(p11) -
                (n00 + n10) * np.log(1 - p_pool) -
                (n01 + n11) * np.log(p_pool)
            )
            # CC = Kupiec LR + Independence LR
            # Compute Kupiec LR from violations
            n_viol = int(np.sum(violations))
            p_hat = n_viol / n_total
            alpha_est = p_hat  # for CC we use estimated rate
            if kupiec_lr is not None and kupiec_lr > 0:
                cc_lr = lr_ind + kupiec_lr
            else:
                cc_lr = lr_ind
            cc_p = 1 - chi2.cdf(max(0, cc_lr), 2)
        else:
            cc_p = 1.0
    else:
        cc_p = 1.0

    return float(cc_p)


def basel_traffic_light(n_viol, n_total, alpha):
    """Basel traffic light classification.

    For 1% VaR over 250 days: Green<=4, Yellow 5-9, Red>=10
    For other periods, scale proportionally.
    """
    if alpha == 0.01:
        # Standard Basel for 1% VaR
        # Scale by actual window size vs 250
        scale = n_total / 250.0
        green_max = int(4 * scale)
        yellow_max = int(9 * scale)
        if n_viol <= green_max:
            return "GREEN"
        elif n_viol <= yellow_max:
            return "YELLOW"
        else:
            return "RED"
    else:
        # For 5% VaR, scale thresholds
        expected = int(n_total * alpha)
        # Green: within expected +-4 (Basel tolerance)
        scaled_tol = int(4 * (n_total / 250.0))
        if n_viol <= expected + scaled_tol:
            return "GREEN"
        elif n_viol <= expected + int(9 * (n_total / 250.0)):
            return "YELLOW"
        else:
            return "RED"


def acerbi_szekely_test(returns, var_series, es_series, alpha):
    """Acerbi & Szekely (2014) ES backtest (Z-test).

    H0: ES model is correctly specified.
    Z = (1/n_viol) * sum_{t: r_t < -VaR_t} (r_t / -ES_t) + 1
    Under H0, Z ~ 0. Rejection: Z < -1.96 (one-sided).

    Returns Z-statistic and p-value.
    """
    violations = returns < -var_series
    n_viol = int(np.sum(violations))

    if n_viol == 0:
        return 0.0, 1.0  # No violations, can't test ES

    # Sum of (r_t / -ES_t) for violation days
    # Note: returns are negative on violation days, ES is positive
    exceedances = returns[violations]
    es_viol = es_series[violations]

    # Z = (1/N) * sum(r_t / -ES_t) + 1
    # = 1 - (1/N) * sum(-r_t / ES_t)
    # When ES is correctly specified, E[-r_t / ES_t | r_t < -VaR_t] = 1
    ratio = -exceedances / es_viol
    z_stat = float(1.0 - np.mean(ratio))

    # Approximate p-value using bootstrap or normal approximation
    # Standard error from the sample
    if n_viol > 1:
        se = float(np.std(ratio) / np.sqrt(n_viol))
        if se > 0:
            t_stat = z_stat / se
            p_value = float(norm.cdf(t_stat))  # one-sided: reject if Z << 0
        else:
            p_value = 0.5
    else:
        p_value = 0.5

    return float(z_stat), float(p_value)


def fissler_ziegel_score(returns, var_series, es_series, alpha):
    """Fissler & Ziegel (2016) joint VaR-ES scoring function.

    S(VaR, ES, r) = (1/ES) * I(r < -VaR) * (r + VaR) + VaR/ES + log(-ES) - 1

    This is a strictly consistent scoring function for the pair (VaR, ES).
    Lower total score = better model.

    Modified formulation (positive VaR and ES inputs):
    S = (1/ES) * I(r < -VaR) * (-r - VaR) + VaR/ES + log(ES) - 1
    """
    n = len(returns)
    violations = returns < -var_series

    scores = np.zeros(n)
    for i in range(n):
        v = var_series[i]  # positive
        e = es_series[i]   # positive
        r = returns[i]

        if e <= 0:
            e = 1e-10

        if violations[i]:
            exceedance = (-r - v)  # positive
            scores[i] = exceedance / e + v / e + np.log(e) - 1
        else:
            scores[i] = v / e + np.log(e) - 1

    return float(np.mean(scores))


def var_trinity_test(violations_bool, n_total, alpha):
    """Full Trinity test: Kupiec + CC + Basel."""
    n_viol = int(np.sum(violations_bool))
    p_hat = n_viol / n_total

    # Kupiec
    if 0 < p_hat < 1:
        kupiec_lr = 2 * (n_viol * np.log(p_hat / alpha) +
                         (n_total - n_viol) * np.log((1 - p_hat) / (1 - alpha)))
        kupiec_p = 1 - chi2.cdf(max(0, kupiec_lr), 1)
    elif p_hat == 0:
        kupiec_p = 0.0 if alpha > 0 else 1.0
        kupiec_lr = 0
    else:
        kupiec_p = 0.0
        kupiec_lr = 0

    # CC
    cc_p = christoffersen_test(violations_bool, n_total, kupiec_lr if kupiec_lr > 0 else None)

    # Basel
    basel = basel_traffic_light(n_viol, n_total, alpha)

    # Trinity: all three must pass
    trinity = bool((kupiec_p > 0.05) and (cc_p > 0.05) and (basel == "GREEN"))

    return {
        'violations': n_viol,
        'total': n_total,
        'rate': round(float(p_hat), 4),
        'expected_rate': alpha,
        'kupiec_p': round(float(kupiec_p), 4),
        'cc_p': round(float(cc_p), 4),
        'basel': basel,
        'trinity': trinity,
    }


# ============================================================
# SECTION 6: ROLLING OOS EVALUATION
# ============================================================
print("\n[6] Rolling OOS evaluation...")


def run_oos_for_asset(ticker, df):
    """Run GJR + MF-GJR models OOS, then evaluate 5 VaR/ES variants."""
    print(f"\n  === {ticker} ===")

    ret = df['log_ret'].values
    log_vix_raw = np.log(df['VIX'].values)
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

    # Storage for sigma forecasts (only GJR and MF-GJR needed)
    sigma2_gjr = np.full(n_oos, np.nan)
    sigma2_mfgjr = np.full(n_oos, np.nan)
    oos_returns = ret[oos_start_idx:]
    oos_r2 = r2[oos_start_idx:]
    oos_dates = dates[oos_start_idx:]

    # Storage for Student-t df estimates per refit window
    gjr_df_estimates = []
    mfgjr_df_estimates = []

    # Storage for standardized residuals (for HistSim)
    gjr_std_resid_all = []     # accumulated from all training windows
    mfgjr_std_resid_all = []

    # Current Student-t parameters
    current_gjr_df = 5.0
    current_mfgjr_df = 5.0

    # HistSim residuals stored per refit: list of (t_index, residuals)
    mfgjr_hist_resid_per_refit = []

    # ---- Rolling estimation ----
    last_gjr_params = None
    last_gjr_h = None
    last_mfgjr_params = None
    last_mfgjr_g = None
    tau_prev_mfgjr = None

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
                # Reconstruct in-sample h for standardized residuals
                h_arr = np.empty(len(train_ret))
                h_arr[0] = np.var(train_ret)
                for tt in range(1, len(train_ret)):
                    omega, alpha, gamma_g, beta = gjr_params
                    asym = gamma_g * train_ret[tt-1]**2 if train_ret[tt-1] < 0 else 0.0
                    h_arr[tt] = omega + alpha * train_ret[tt-1]**2 + asym + beta * h_arr[tt-1]
                    h_arr[tt] = max(h_arr[tt], 1e-10)

                # BUG FIX #3: Advance h one step
                last_gjr_h = gjr_garch_forecast_oos(
                    gjr_params, train_ret[-1], h_arr[-1])

                # Compute standardized residuals for Student-t fitting
                gjr_std_resid = train_ret[1:] / np.sqrt(h_arr[1:])
                gjr_df, _ = fit_student_t(gjr_std_resid)
                current_gjr_df = gjr_df
                gjr_df_estimates.append({
                    'refit': n_refits,
                    'date': str(dates[idx].date()),
                    'df': round(gjr_df, 2)
                })

            # === Fit MF-GJR ===
            mfgjr_params, mfgjr_ll = fit_mf_garch(train_ret, train_vix, model_type='gjr')
            if mfgjr_params is not None:
                last_mfgjr_params = mfgjr_params
                _, g_arr, tau_arr = forecast_mf_garch(mfgjr_params, train_ret, train_vix, 'gjr')

                # BUG FIX #3: Advance g one step
                theta0, theta1, alpha_mf, gamma_mf, beta_mf = mfgjr_params
                last_tau = tau_arr[-1]
                u_last = train_ret[-1] / np.sqrt(last_tau)
                omega_g = 1.0 - alpha_mf - gamma_mf / 2.0 - beta_mf
                asym = gamma_mf * u_last**2 if u_last < 0 else 0.0
                last_mfgjr_g = omega_g + alpha_mf * u_last**2 + asym + beta_mf * g_arr[-1]
                last_mfgjr_g = max(last_mfgjr_g, 1e-10)

                # Compute standardized residuals
                sigma2_is = tau_arr * g_arr
                mfgjr_std_resid = train_ret[1:] / np.sqrt(sigma2_is[1:])
                mfgjr_df, _ = fit_student_t(mfgjr_std_resid)
                current_mfgjr_df = mfgjr_df
                mfgjr_df_estimates.append({
                    'refit': n_refits,
                    'date': str(dates[idx].date()),
                    'df': round(mfgjr_df, 2)
                })

                # Store standardized residuals for HistSim
                hist_resid_clean = mfgjr_std_resid[np.isfinite(mfgjr_std_resid)]
                mfgjr_hist_resid_per_refit.append((t, hist_resid_clean.copy()))

        # === Generate one-step-ahead sigma^2 forecasts ===

        # GJR-GARCH
        if last_gjr_params is not None and last_gjr_h is not None:
            if not need_refit and t > 0:
                last_gjr_h = gjr_garch_forecast_oos(
                    last_gjr_params, ret[idx-1], last_gjr_h)
            sigma2_gjr[t] = last_gjr_h

        # MF-GJR
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
            sigma2_mfgjr[t] = tau_t * g_t

    print(f"    Refits: {n_refits}")

    # ============================================================
    # SECTION 7: COMPUTE VaR AND ES FOR ALL 5 MODELS
    # ============================================================
    print(f"    Computing VaR/ES for 5 model-distribution combinations...")

    # Build arrays of df estimates that change at each refit
    # (residuals were stored in mfgjr_hist_resid_per_refit during OOS loop)
    gjr_df_arr = np.full(n_oos, 5.0)
    mfgjr_df_arr = np.full(n_oos, 5.0)

    # Assign per-period df from refit estimates
    refit_idx = 0
    current_gjr_df_val = 5.0
    current_mfgjr_df_val = 5.0
    for t in range(n_oos):
        need_refit = (t == 0) or (t % REFIT_EVERY == 0)
        if need_refit and refit_idx < len(gjr_df_estimates):
            current_gjr_df_val = gjr_df_estimates[refit_idx]['df']
            refit_idx_mf = min(refit_idx, len(mfgjr_df_estimates) - 1)
            current_mfgjr_df_val = mfgjr_df_estimates[refit_idx_mf]['df'] if mfgjr_df_estimates else 5.0
            refit_idx += 1
        gjr_df_arr[t] = current_gjr_df_val
        mfgjr_df_arr[t] = current_mfgjr_df_val

    # For HistSim: use stored residuals from each refit window
    # mfgjr_hist_resid_per_refit is a list of (refit_t_index, residuals) from the main OOS loop
    hist_var_cache = {alpha: np.full(n_oos, np.nan) for alpha in ALPHA_LEVELS}
    hist_es_cache = {alpha: np.full(n_oos, np.nan) for alpha in ALPHA_LEVELS}

    current_hist_resid_idx = 0
    current_hist_resid = None
    for t in range(n_oos):
        # Check if we need to update the HistSim residuals at this refit point
        if (current_hist_resid_idx < len(mfgjr_hist_resid_per_refit) and
                t >= mfgjr_hist_resid_per_refit[current_hist_resid_idx][0]):
            current_hist_resid = mfgjr_hist_resid_per_refit[current_hist_resid_idx][1]
            current_hist_resid_idx += 1
            # Advance past any additional refits that happen at the same t
            while (current_hist_resid_idx < len(mfgjr_hist_resid_per_refit) and
                   mfgjr_hist_resid_per_refit[current_hist_resid_idx][0] <= t):
                current_hist_resid = mfgjr_hist_resid_per_refit[current_hist_resid_idx][1]
                current_hist_resid_idx += 1

        sigma_mfgjr = np.sqrt(sigma2_mfgjr[t]) if np.isfinite(sigma2_mfgjr[t]) and sigma2_mfgjr[t] > 0 else np.nan
        if current_hist_resid is not None and len(current_hist_resid) > 50 and np.isfinite(sigma_mfgjr):
            for alpha in ALPHA_LEVELS:
                q = np.quantile(current_hist_resid, alpha)
                hist_var_cache[alpha][t] = -q * sigma_mfgjr
                tail = current_hist_resid[current_hist_resid <= q]
                if len(tail) > 0:
                    hist_es_cache[alpha][t] = -np.mean(tail) * sigma_mfgjr
                else:
                    hist_es_cache[alpha][t] = hist_var_cache[alpha][t] * 1.2

    print(f"    Student-t df (GJR, final): {gjr_df_arr[-1]:.2f}")
    print(f"    Student-t df (MF-GJR, final): {mfgjr_df_arr[-1]:.2f}")

    # ============================================================
    # SECTION 8: VaR/ES EVALUATION FOR ALL 5 MODELS
    # ============================================================
    print(f"    Evaluating VaR/ES...")

    var_results = {}
    es_results = {}

    for alpha in ALPHA_LEVELS:
        var_results[alpha] = {}
        es_results[alpha] = {}

        for vm in VAR_MODELS:
            # Compute VaR and ES arrays
            var_arr = np.full(n_oos, np.nan)
            es_arr = np.full(n_oos, np.nan)

            for t in range(n_oos):
                if vm == 'GJR+Normal':
                    s2 = sigma2_gjr[t]
                    if np.isfinite(s2) and s2 > 0:
                        sigma = np.sqrt(s2)
                        var_arr[t] = normal_var(sigma, alpha)
                        es_arr[t] = normal_es(sigma, alpha)

                elif vm == 'GJR+Student-t':
                    s2 = sigma2_gjr[t]
                    if np.isfinite(s2) and s2 > 0:
                        sigma = np.sqrt(s2)
                        df = gjr_df_arr[t]
                        var_arr[t] = student_t_var(sigma, alpha, df)
                        es_arr[t] = student_t_es(sigma, alpha, df)

                elif vm == 'MF-GJR+Normal':
                    s2 = sigma2_mfgjr[t]
                    if np.isfinite(s2) and s2 > 0:
                        sigma = np.sqrt(s2)
                        var_arr[t] = normal_var(sigma, alpha)
                        es_arr[t] = normal_es(sigma, alpha)

                elif vm == 'MF-GJR+Student-t':
                    s2 = sigma2_mfgjr[t]
                    if np.isfinite(s2) and s2 > 0:
                        sigma = np.sqrt(s2)
                        df = mfgjr_df_arr[t]
                        var_arr[t] = student_t_var(sigma, alpha, df)
                        es_arr[t] = student_t_es(sigma, alpha, df)

                elif vm == 'MF-GJR+HistSim':
                    var_arr[t] = hist_var_cache[alpha][t]
                    es_arr[t] = hist_es_cache[alpha][t]

            # Evaluate VaR
            valid = np.isfinite(var_arr) & np.isfinite(oos_returns)
            if valid.sum() < 100:
                var_results[alpha][vm] = {
                    'violations': None, 'rate': None,
                    'kupiec_p': None, 'cc_p': None,
                    'basel': 'N/A', 'trinity': False
                }
                es_results[alpha][vm] = {
                    'acerbi_szekely_z': None, 'acerbi_szekely_p': None,
                    'fissler_ziegel_score': None
                }
                continue

            violations_bool = oos_returns[valid] < -var_arr[valid]
            n_valid = int(valid.sum())

            trinity_result = var_trinity_test(violations_bool, n_valid, alpha)
            var_results[alpha][vm] = trinity_result

            # Evaluate ES
            as_z, as_p = acerbi_szekely_test(
                oos_returns[valid], var_arr[valid], es_arr[valid], alpha
            )
            fz_score = fissler_ziegel_score(
                oos_returns[valid], var_arr[valid], es_arr[valid], alpha
            )

            es_results[alpha][vm] = {
                'acerbi_szekely_z': round(as_z, 4),
                'acerbi_szekely_p': round(as_p, 4),
                'fissler_ziegel_score': round(fz_score, 6),
            }

    # ============================================================
    # Print results
    # ============================================================
    for alpha in ALPHA_LEVELS:
        print(f"\n    VaR {int(alpha*100)}% Trinity:")
        for vm in VAR_MODELS:
            r = var_results[alpha][vm]
            if r['violations'] is not None:
                print(f"      {vm:25s}: {r['violations']}/{r['total']} "
                      f"({r['rate']:.4f}) Kupiec p={r['kupiec_p']:.3f} "
                      f"CC p={r['cc_p']:.3f} Basel={r['basel']} "
                      f"Trinity={'PASS' if r['trinity'] else 'FAIL'}")
            else:
                print(f"      {vm:25s}: N/A")

        print(f"\n    ES {int(alpha*100)}% Backtesting:")
        for vm in VAR_MODELS:
            r = es_results[alpha][vm]
            if r['acerbi_szekely_z'] is not None:
                print(f"      {vm:25s}: AS_Z={r['acerbi_szekely_z']:+.4f} "
                      f"AS_p={r['acerbi_szekely_p']:.4f} "
                      f"FZ={r['fissler_ziegel_score']:.6f}")
            else:
                print(f"      {vm:25s}: N/A")

    # ============================================================
    # SECTION 9: QLIKE COMPARISON (GJR vs MF-GJR)
    # ============================================================
    print(f"\n    QLIKE comparison (GJR vs MF-GJR):")
    qlike_results = {}
    for m_name, sigma2_arr in [('GJR', sigma2_gjr), ('MF-GJR', sigma2_mfgjr)]:
        valid = np.isfinite(sigma2_arr) & (sigma2_arr > 0)
        if valid.sum() > 100:
            qlike_results[m_name] = qlike(oos_r2[valid], sigma2_arr[valid])
        else:
            qlike_results[m_name] = np.nan

    gjr_qlike = qlike_results.get('GJR', np.nan)
    for m_name in ['GJR', 'MF-GJR']:
        q = qlike_results.get(m_name, np.nan)
        pct = ((q - gjr_qlike) / gjr_qlike * 100) if np.isfinite(q) and np.isfinite(gjr_qlike) and gjr_qlike > 0 else np.nan
        print(f"      {m_name}: {q:.6f} ({pct:+.3f}% vs GJR)")

    # DM test
    gjr_loss = qlike_pointwise(oos_r2, sigma2_gjr)
    mfgjr_loss = qlike_pointwise(oos_r2, sigma2_mfgjr)
    valid_dm = np.isfinite(gjr_loss) & np.isfinite(mfgjr_loss)
    if valid_dm.sum() > 100:
        dm_t, dm_p = dm_test(mfgjr_loss[valid_dm], gjr_loss[valid_dm])
        dm_result = {'t': round(float(dm_t), 3), 'p': round(float(dm_p), 4),
                     'significant_harvey': abs(float(dm_t)) > 3.0}
    else:
        dm_result = {'t': None, 'p': None, 'significant_harvey': False}
    print(f"      DM test (MF-GJR vs GJR): t={dm_result['t']}, p={dm_result['p']} "
          f"{'Harvey PASS' if dm_result['significant_harvey'] else 'Harvey FAIL'}")

    # ============================================================
    # Collect results
    # ============================================================

    # Student-t df summary
    gjr_df_summary = {
        'mean_df': round(float(np.mean([x['df'] for x in gjr_df_estimates])), 2) if gjr_df_estimates else None,
        'min_df': round(float(np.min([x['df'] for x in gjr_df_estimates])), 2) if gjr_df_estimates else None,
        'max_df': round(float(np.max([x['df'] for x in gjr_df_estimates])), 2) if gjr_df_estimates else None,
        'final_df': gjr_df_estimates[-1]['df'] if gjr_df_estimates else None,
        'all_estimates': gjr_df_estimates,
    }
    mfgjr_df_summary = {
        'mean_df': round(float(np.mean([x['df'] for x in mfgjr_df_estimates])), 2) if mfgjr_df_estimates else None,
        'min_df': round(float(np.min([x['df'] for x in mfgjr_df_estimates])), 2) if mfgjr_df_estimates else None,
        'max_df': round(float(np.max([x['df'] for x in mfgjr_df_estimates])), 2) if mfgjr_df_estimates else None,
        'final_df': mfgjr_df_estimates[-1]['df'] if mfgjr_df_estimates else None,
        'all_estimates': mfgjr_df_estimates,
    }

    # Best model ranking
    best_var_model = {}
    best_es_model = {}
    for alpha in ALPHA_LEVELS:
        alpha_str = str(alpha)
        # Best VaR: Trinity PASS + lowest violation rate
        trinity_pass_models = [vm for vm in VAR_MODELS
                              if var_results[alpha][vm].get('trinity', False)]
        if trinity_pass_models:
            best_var_model[alpha_str] = min(
                trinity_pass_models,
                key=lambda vm: abs(var_results[alpha][vm]['rate'] - alpha)
            )
        else:
            # No Trinity PASS — pick lowest violation rate
            valid_models = [vm for vm in VAR_MODELS
                           if var_results[alpha][vm].get('rate') is not None]
            if valid_models:
                best_var_model[alpha_str] = min(
                    valid_models,
                    key=lambda vm: abs(var_results[alpha][vm]['rate'] - alpha)
                )
            else:
                best_var_model[alpha_str] = 'N/A'

        # Best ES: lowest Fissler-Ziegel score (among Trinity PASS models)
        es_candidates = trinity_pass_models if trinity_pass_models else VAR_MODELS
        valid_es = [vm for vm in es_candidates
                   if es_results[alpha][vm].get('fissler_ziegel_score') is not None]
        if valid_es:
            best_es_model[alpha_str] = min(
                valid_es,
                key=lambda vm: es_results[alpha][vm]['fissler_ziegel_score']
            )
        else:
            best_es_model[alpha_str] = 'N/A'

    # Core question answer
    mfgjr_st_1pct_trinity = bool(var_results[0.01].get('MF-GJR+Student-t', {}).get('trinity', False))
    mfgjr_st_5pct_trinity = bool(var_results[0.05].get('MF-GJR+Student-t', {}).get('trinity', False))

    return {
        'ticker': ticker,
        'n_oos': int(n_oos),
        'oos_start': str(oos_dates[0].date()),
        'oos_end': str(oos_dates[-1].date()),
        'n_refits': n_refits,
        'qlike': {m: round(v, 6) if np.isfinite(v) else None for m, v in qlike_results.items()},
        'qlike_pct_vs_gjr': {
            m: round(((v - gjr_qlike) / gjr_qlike * 100), 3)
            if np.isfinite(v) and np.isfinite(gjr_qlike) and gjr_qlike > 0 else None
            for m, v in qlike_results.items()
        },
        'dm_mfgjr_vs_gjr': dm_result,
        'student_t_df': {
            'GJR': gjr_df_summary,
            'MF-GJR': mfgjr_df_summary,
        },
        'var': {
            str(a): {vm: var_results[a][vm] for vm in VAR_MODELS}
            for a in ALPHA_LEVELS
        },
        'es': {
            str(a): {vm: es_results[a][vm] for vm in VAR_MODELS}
            for a in ALPHA_LEVELS
        },
        'best_var_model': best_var_model,
        'best_es_model': best_es_model,
        'core_question': {
            'mfgjr_student_t_1pct_trinity': mfgjr_st_1pct_trinity,
            'mfgjr_student_t_5pct_trinity': mfgjr_st_5pct_trinity,
            'complete_solution': bool(mfgjr_st_1pct_trinity and mfgjr_st_5pct_trinity),
        },
    }


# ============================================================
# SECTION 10: RUN ALL ASSETS
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
# SECTION 11: CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("CROSS-ASSET SUMMARY")
print("=" * 70)

for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        print(f"\n{ticker}: ERROR - {all_results[ticker]['error']}")
        continue
    r = all_results[ticker]
    print(f"\n{ticker} (OOS: {r['oos_start']} to {r['oos_end']}, n={r['n_oos']})")

    # QLIKE
    print(f"  QLIKE: GJR={r['qlike'].get('GJR', 'N/A')}, "
          f"MF-GJR={r['qlike'].get('MF-GJR', 'N/A')} "
          f"({r['qlike_pct_vs_gjr'].get('MF-GJR', 'N/A')}% vs GJR)")
    dm = r.get('dm_mfgjr_vs_gjr', {})
    print(f"  DM test: t={dm.get('t', 'N/A')}, "
          f"{'Harvey PASS' if dm.get('significant_harvey') else 'Harvey FAIL'}")

    # Student-t df
    gjr_df = r.get('student_t_df', {}).get('GJR', {})
    mfgjr_df = r.get('student_t_df', {}).get('MF-GJR', {})
    print(f"  Student-t df: GJR={gjr_df.get('mean_df', 'N/A')} (range: "
          f"{gjr_df.get('min_df', 'N/A')}-{gjr_df.get('max_df', 'N/A')}), "
          f"MF-GJR={mfgjr_df.get('mean_df', 'N/A')} (range: "
          f"{mfgjr_df.get('min_df', 'N/A')}-{mfgjr_df.get('max_df', 'N/A')})")

    # VaR 1% Trinity
    print(f"  VaR 1% Trinity:")
    for vm in VAR_MODELS:
        v = r['var'].get('0.01', {}).get(vm, {})
        if v.get('violations') is not None:
            print(f"    {vm:25s}: {v['violations']}/{v['total']} "
                  f"({v['rate']:.4f}) Basel={v['basel']} "
                  f"Trinity={'PASS' if v['trinity'] else 'FAIL'}")
        else:
            print(f"    {vm:25s}: N/A")

    # VaR 5% Trinity
    print(f"  VaR 5% Trinity:")
    for vm in VAR_MODELS:
        v = r['var'].get('0.05', {}).get(vm, {})
        if v.get('violations') is not None:
            print(f"    {vm:25s}: {v['violations']}/{v['total']} "
                  f"({v['rate']:.4f}) Basel={v['basel']} "
                  f"Trinity={'PASS' if v['trinity'] else 'FAIL'}")
        else:
            print(f"    {vm:25s}: N/A")

    # ES summary
    print(f"  ES Fissler-Ziegel scores (lower = better):")
    for alpha in ALPHA_LEVELS:
        alpha_str = str(alpha)
        print(f"    {int(alpha*100)}% VaR:")
        for vm in VAR_MODELS:
            e = r['es'].get(alpha_str, {}).get(vm, {})
            fz = e.get('fissler_ziegel_score')
            as_p = e.get('acerbi_szekely_p')
            if fz is not None:
                print(f"      {vm:25s}: FZ={fz:.6f} AS_p={as_p:.4f}")

    # Core question
    cq = r.get('core_question', {})
    print(f"  CORE: MF-GJR+Student-t 1% Trinity={'PASS' if cq.get('mfgjr_student_t_1pct_trinity') else 'FAIL'}, "
          f"5% Trinity={'PASS' if cq.get('mfgjr_student_t_5pct_trinity') else 'FAIL'}, "
          f"Complete={'YES' if cq.get('complete_solution') else 'NO'}")


# ============================================================
# SECTION 12: OVERALL CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("OVERALL CONCLUSION")
print("=" * 70)

# Check across all assets
all_complete = True
any_improvement = False
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        all_complete = False
        continue
    cq = all_results[ticker].get('core_question', {})
    if cq.get('complete_solution'):
        any_improvement = True
        print(f"  {ticker}: MF-GJR+Student-t is COMPLETE SOLUTION (QLIKE + VaR + ES)")
    else:
        all_complete = False
        # Check which parts pass
        if cq.get('mfgjr_student_t_1pct_trinity'):
            print(f"  {ticker}: MF-GJR+Student-t 1% Trinity PASS (5% incomplete)")
        elif cq.get('mfgjr_student_t_5pct_trinity'):
            print(f"  {ticker}: MF-GJR+Student-t 5% Trinity PASS (1% incomplete)")
        else:
            print(f"  {ticker}: MF-GJR+Student-t FAIL both VaR levels")

# Check HistSim as alternative
print("\n  HistSim performance:")
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    r = all_results[ticker]
    for alpha in ALPHA_LEVELS:
        hs = r['var'].get(str(alpha), {}).get('MF-GJR+HistSim', {})
        if hs.get('violations') is not None:
            print(f"    {ticker} {int(alpha*100)}%: "
                  f"{hs['violations']}/{hs['total']} ({hs['rate']:.4f}) "
                  f"Trinity={'PASS' if hs['trinity'] else 'FAIL'}")

# Best overall model
print("\n  Best VaR model per asset per level:")
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    r = all_results[ticker]
    for alpha_str, bm in r.get('best_var_model', {}).items():
        print(f"    {ticker} {alpha_str}: {bm}")

print(f"\n  Best ES model per asset per level:")
for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    r = all_results[ticker]
    for alpha_str, bm in r.get('best_es_model', {}).items():
        print(f"    {ticker} {alpha_str}: {bm}")


# ============================================================
# SECTION 13: SAVE RESULTS
# ============================================================
elapsed = time.time() - START_TIME

# Overall conclusion
conclusion = {
    'student_t_fixes_1pct_var': {},
    'histsim_fixes_1pct_var': {},
    'complete_solution_found': {},
    'best_overall_var_model': {},
    'best_overall_es_model': {},
}

for ticker in ASSETS:
    if 'error' in all_results[ticker]:
        continue
    r = all_results[ticker]
    cq = r.get('core_question', {})

    # Does Student-t fix the 1% VaR problem?
    mfgjr_normal_1pct = bool(r['var'].get('0.01', {}).get('MF-GJR+Normal', {}).get('trinity', False))
    mfgjr_st_1pct = bool(r['var'].get('0.01', {}).get('MF-GJR+Student-t', {}).get('trinity', False))
    conclusion['student_t_fixes_1pct_var'][ticker] = bool((not mfgjr_normal_1pct) and mfgjr_st_1pct)

    # Does HistSim fix it?
    mfgjr_hs_1pct = bool(r['var'].get('0.01', {}).get('MF-GJR+HistSim', {}).get('trinity', False))
    conclusion['histsim_fixes_1pct_var'][ticker] = bool((not mfgjr_normal_1pct) and mfgjr_hs_1pct)

    conclusion['complete_solution_found'][ticker] = bool(cq.get('complete_solution', False))
    conclusion['best_overall_var_model'][ticker] = r.get('best_var_model', {})
    conclusion['best_overall_es_model'][ticker] = r.get('best_es_model', {})


final_results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'MF-GJR + Student-t Distribution — VaR/ES Complete Evaluation',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'runtime_seconds': round(elapsed, 1),
    'methodology': {
        'volatility_models': ['GJR-GARCH(1,1)', 'MF-GJR (Engle-Ghysels-Sohn 2013)'],
        'distributions': ['Normal', 'Student-t (MLE, per-refit)', 'Historical Simulation'],
        'var_models': VAR_MODELS,
        'mf_long_run': 'tau_t = exp(theta_0 + theta_1 * log(VIX_{t-1}))',
        'mf_short_run_gjr': 'g_t = (1-a-g/2-b) + a*u^2_{t-1} + g*u^2_{t-1}*I(u<0) + b*g_{t-1}',
        'student_t_var': 'VaR = sigma * |t_ppf(alpha, df)| * sqrt((df-2)/df)',
        'student_t_es': 'ES = sigma * [pdf/alpha] * [(df+q^2)/(df-1)] * sqrt((df-2)/df)',
        'estimation': 'Rolling window (w=2000), refit every 63 days, MLE with multi-start',
        'var_evaluation': 'Kupiec (1995) + Christoffersen (1998) + Basel traffic light = Trinity',
        'es_evaluation': 'Acerbi & Szekely (2014) Z-test + Fissler & Ziegel (2016) joint scoring',
    },
    'data': {
        'source': 'yfinance',
        'assets': ASSETS,
        'period': f'{DATA_START} to {DATA_END}',
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
    },
    'results': all_results,
    'conclusion': conclusion,
    'references': [
        'Engle, Ghysels & Sohn (2013) RES 95(3):776-797',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey et al. (2016) JBES 34:92-104',
        'McNeil & Frey (2000) J Empirical Finance 7:271-300',
        'Acerbi & Szekely (2014) Risk Magazine',
        'Fissler & Ziegel (2016) JASA 111:1048-1059',
        'Kupiec (1995) J Derivatives 3(2):73-84',
        'Christoffersen (1998) Int Economic Review 39(4):841-862',
        'Hansen, Lunde & Nason (2011) Econometrica 79(2):453-497',
    ],
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\nResults saved to: {RESULTS_PATH}")
print(f"Runtime: {elapsed:.1f}s")
print("=" * 70)
