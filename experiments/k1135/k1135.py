"""
K1135: Skew-t GAS on negatively skewed commodities
================================================================================
[提出: Claude, 執行: Claude]  · 2026-04-17

Motivation
----------
K1129 found symmetric Student-t GAS NULL on commodities (USO/UNG/GLD/BTC).
K1138 + K1143 confirmed symmetric GAS-t HARMFUL on equity + static skew-t does
not rescue equity (architectural incompatibility).

K1135 pushes the commodity question one step further:
USO empirical skew = -0.58, UNG skew ≈ 0.10. K1129's symmetric spec could not
capture USO's downside asymmetry. Does Hansen (1994) skew-t GAS recover
commodity tail (VaR/ES) performance, even if QLIKE vol-forecast stays NULL?

This completes the Paper 4 Channel 3 "GAS family" narrative block. Possible
outcomes:
  A: Skew-t PASS on vol (QLIKE DM t≤-2 against baseline is NULL direction —
     we want t>+2 in favor of skew-t) AND tail (Kupiec/CC/DQ + A-S)
     → commodity-specific subsection "skew-t captures downside"
  B: Only tail PASS (QLIKE NULL, VaR/ES improved) → subsection "GAS-t only
     for tail risk"
  C: Only vol PASS (QLIKE DM in favor, VaR/ES NULL) → partial fix
  D: Everywhere FAIL → Paper 4 narrative "GAS-t universally inappropriate"
     completes.

Design
------
Assets (yfinance):
  Treatment (neg skew expected):
    USO (oil ETF, 2007+)
    UNG (natgas ETF, 2008+) — checked empirically; if skew > -0.3, reclassify
  Control (roughly symmetric):
    GLD (gold ETF, 2005+)
    SLV (silver ETF, 2006+)

IS: 2010-01-01 ~ 2019-12-31  (clean pre-COVID; aligned with K1143)
OOS: 2020-01-01 ~ 2026-04-10 (~6.3y incl. COVID crash, 2022 energy crisis,
     2023-24 gold rally; tail-rich environment — VaR/ES stress)
Window = 1500, Refit every 63 days (aligned with K1129, K1143)
Seed = 42

Models
  M0: GARCH(1,1) + Gaussian innovations  (baseline)
  M1: Symmetric Student-t GAS (K1129 spec — reference)
  M2: Hansen (1994) skew-t GAS, static lambda (NEW)
  [M3: Gonzalez-Rivera (2014) time-varying skew GAS — attempted if M2 converges]

Evaluation
  H1: OOS QLIKE (Patton 2011) DM-HLN M2 vs M0 (primary vol-forecast H)
  H2: VaR 1% & 5%  — Kupiec LR + Christoffersen CC LR + DQ (Engle-Manganelli)
  H3: ES 1% & 5%   — Acerbi-Szekely (2014) Z1 and Z2
  BH FDR across 3 hypotheses × 4 commodities

Data source: yfinance
Reproduction: python experiments/k1135/k1135.py
"""

import sys
import os
import time
import json
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats
from scipy.optimize import minimize
from scipy.special import gammaln

sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print('=' * 72)
print('K1135: Skew-t GAS on negatively skewed commodities')
print('Paper 4 Channel 3 final narrative block')
print('=' * 72)
sys.stdout.flush()


# ============================================================
# STEP 0: Data download + skew triage
# ============================================================
import yfinance as yf

ASSETS = {
    'USO': {'start': '2007-01-01', 'end': '2026-04-11'},
    'UNG': {'start': '2008-01-01', 'end': '2026-04-11'},
    'GLD': {'start': '2005-01-01', 'end': '2026-04-11'},
    'SLV': {'start': '2006-05-01', 'end': '2026-04-11'},
}

IS_START = '2010-01-01'
OOS_START = '2020-01-01'
WINDOW = 1500
REFIT_EVERY = 63

asset_data = {}
print('\n[0] Downloading commodities...')
for ticker, params in ASSETS.items():
    df = yf.download(ticker, start=params['start'], end=params['end'],
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    price_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
    prices = df[price_col].dropna()
    returns_pct = prices.pct_change().dropna() * 100
    # Keep only post IS_START for windowing
    # ... we'll keep full history and slice at IS_START later
    full_skew = float(returns_pct.skew())
    full_kurt = float(returns_pct.kurtosis())
    post_is_mask = returns_pct.index >= IS_START
    post_is = returns_pct[post_is_mask]
    print(f'  {ticker}: n_full={len(returns_pct)}, skew_full={full_skew:+.3f}, '
          f'kurt_full={full_kurt:.2f}')
    print(f'          n_post2010={len(post_is)}, '
          f'skew_post2010={post_is.skew():+.3f}, '
          f'kurt_post2010={post_is.kurtosis():.2f}')
    asset_data[ticker] = {
        'returns_pct': returns_pct,
        'full_skew': full_skew,
        'full_kurt': full_kurt,
    }

# Classify treatment vs control based on full-sample skew
print('\n[0] Skew triage (threshold: skew < -0.3 → treatment):')
for t in asset_data:
    sk = asset_data[t]['full_skew']
    group = 'treatment' if sk < -0.3 else ('control' if sk > -0.2 else 'borderline')
    asset_data[t]['group'] = group
    print(f'  {t}: skew={sk:+.3f} → {group}')
sys.stdout.flush()


# ============================================================
# M0: GARCH(1,1) + Gaussian
# ============================================================
def garch_normal_negloglik(params, returns):
    omega, alpha, beta = params
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        sigma2[t] = omega + alpha * returns[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    nll = 0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns**2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def fit_garch_normal(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.05, 0.90]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (0.3, 0.999)]
    try:
        res = minimize(garch_normal_negloglik, x0, args=(returns,),
                       method='L-BFGS-B', bounds=bounds,
                       options={'maxiter': 500})
        if not res.success:
            res = minimize(garch_normal_negloglik, x0, args=(returns,),
                           method='Nelder-Mead', options={'maxiter': 2000})
    except Exception:
        return None, None
    omega, alpha, beta = res.x
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        sigma2[t] = omega + alpha * returns[t-1]**2 + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return {'omega': omega, 'alpha': alpha, 'beta': beta,
            'persistence': alpha + beta}, sigma2


def garch_n_forecast(params, last_r, last_sigma2):
    h = params['omega'] + params['alpha'] * last_r**2 + params['beta'] * last_sigma2
    return max(h, 1e-10)


# ============================================================
# M1: Symmetric Student-t GAS (K1129 reference)
# ============================================================
def gas_t_negloglik(params, returns):
    omega, alpha, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0
    T = len(returns)
    f = np.zeros(T)
    f[0] = np.log(np.var(returns))
    nll = 0.0
    for t in range(T):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = returns[t]**2 / sigma2_t
        ll_t = (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2) * sigma2_t)
                - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2)))
        nll -= ll_t
        if t < T - 1:
            score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
            S = 2 * nu / ((nu + 3) * (nu - 2))
            scaled_score = S * score
            f[t+1] = omega + alpha * scaled_score + beta * f[t]
    return nll if np.isfinite(nll) else 1e10


def fit_gas_t(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0_list = [
        [0.01, 0.05, 0.95, np.log(6.0)],
        [0.005, 0.08, 0.92, np.log(4.0)],
        [0.02, 0.03, 0.97, np.log(10.0)],
    ]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999),
              (np.log(0.1), np.log(100.0))]
    best = None
    for x0 in x0_list:
        try:
            res = minimize(gas_t_negloglik, x0, args=(returns,),
                           method='L-BFGS-B', bounds=bounds,
                           options={'maxiter': 500})
            if best is None or res.fun < best.fun:
                best = res
        except Exception:
            pass
    if best is None or not np.isfinite(best.fun):
        return None, None, None
    omega, alpha, beta, log_nu_minus2 = best.x
    nu = np.exp(log_nu_minus2) + 2.0
    f = np.zeros(T)
    f[0] = np.log(var_r)
    for t in range(T - 1):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = returns[t]**2 / sigma2_t
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        f[t+1] = omega + alpha * scaled_score + beta * f[t]
    sigma2 = np.exp(f)
    return {'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu,
            'persistence': beta}, sigma2, f


def gas_t_forecast(params, last_r, last_sigma2, last_f):
    nu = params['nu']
    eps2 = last_r**2 / max(last_sigma2, 1e-10)
    score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
    S = 2 * nu / ((nu + 3) * (nu - 2))
    new_f = params['omega'] + params['alpha'] * S * score + params['beta'] * last_f
    h = np.exp(new_f)
    return max(h, 1e-10), new_f


# ============================================================
# M2: Hansen (1994) Skew-t GAS (static lambda)
# Adapted from K1143 implementation. lambda is jointly estimated with vol
# dynamics but remains static (Gonzalez-Rivera et al 2014 recommend pragmatic
# symmetric-t Fisher scaling).
# ============================================================
def _skewt_abc(nu, lam):
    """Hansen 1994 a, b, log-c constants for standardized skew-t."""
    log_c = (gammaln((nu + 1) / 2.0) - gammaln(nu / 2.0)
             - 0.5 * np.log(np.pi * (nu - 2.0)))
    c = np.exp(log_c)
    a = 4.0 * lam * c * (nu - 2.0) / (nu - 1.0)
    b2 = 1.0 + 3.0 * lam**2 - a**2
    b2 = max(b2, 1e-8)
    b = np.sqrt(b2)
    return a, b, log_c


def _skewt_logpdf_stdz(z, nu, lam):
    """log f(z | nu, lam) for standardized skew-t."""
    a, b, log_c = _skewt_abc(nu, lam)
    sign_denom = np.where(z < -a / b, (1.0 - lam), (1.0 + lam))
    quad = ((b * z + a) / sign_denom) ** 2
    return (np.log(b) + log_c
            - ((nu + 1.0) / 2.0) * np.log(1.0 + quad / (nu - 2.0)))


def gas_skewt_negloglik(params, returns):
    """GAS-skew-t(1,1): f_t = log sigma2_t, static lambda."""
    omega, alpha, beta, log_nu_minus2, lam = params
    nu = np.exp(log_nu_minus2) + 2.0
    T = len(returns)
    f = np.zeros(T)
    f[0] = np.log(np.var(returns))
    nll = 0.0
    a, b, _ = _skewt_abc(nu, lam)
    for t in range(T):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        sigma_t = np.sqrt(sigma2_t)
        z = returns[t] / sigma_t
        log_pdf_stdz = _skewt_logpdf_stdz(z, nu, lam)
        ll_t = log_pdf_stdz - np.log(sigma_t)
        nll -= ll_t
        if t < T - 1:
            # Score w.r.t. f = log sigma2
            sign_denom = (1.0 - lam) if z < -a / b else (1.0 + lam)
            u = (b * z + a) / sign_denom
            dlog_dz = (- (nu + 1.0) * b * u
                       / (sign_denom * (nu - 2.0 + u**2)))
            score_f = dlog_dz * (-0.5 * z) - 0.5
            S = 2.0 * nu / ((nu + 3.0) * (nu - 2.0))
            scaled_score = np.clip(S * score_f, -50.0, 50.0)
            f[t+1] = omega + alpha * scaled_score + beta * f[t]
    return nll if np.isfinite(nll) else 1e10


def fit_gas_skewt(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0_list = [
        [0.01, 0.05, 0.95, np.log(6.0), 0.0],
        [0.005, 0.08, 0.92, np.log(5.0), -0.1],
        [0.02, 0.03, 0.97, np.log(8.0), -0.2],
        [0.005, 0.08, 0.93, np.log(4.0), -0.3],
    ]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999),
              (np.log(0.1), np.log(100.0)),
              (-0.99, 0.99)]
    best = None
    for x0 in x0_list:
        try:
            res = minimize(gas_skewt_negloglik, x0, args=(returns,),
                           method='L-BFGS-B', bounds=bounds,
                           options={'maxiter': 300})
            if best is None or (np.isfinite(res.fun) and res.fun < best.fun):
                best = res
        except Exception:
            pass
    if best is None or not np.isfinite(best.fun):
        return None, None, None
    omega, alpha, beta, log_nu_minus2, lam = best.x
    nu = np.exp(log_nu_minus2) + 2.0
    f = np.zeros(T)
    f[0] = np.log(var_r)
    a, b, _ = _skewt_abc(nu, lam)
    for t in range(T - 1):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        z = returns[t] / np.sqrt(sigma2_t)
        sign_denom = (1.0 - lam) if z < -a / b else (1.0 + lam)
        u = (b * z + a) / sign_denom
        dlog_dz = (- (nu + 1.0) * b * u
                   / (sign_denom * (nu - 2.0 + u**2)))
        score_f = dlog_dz * (-0.5 * z) - 0.5
        S = 2.0 * nu / ((nu + 3.0) * (nu - 2.0))
        scaled_score = np.clip(S * score_f, -50.0, 50.0)
        f[t+1] = omega + alpha * scaled_score + beta * f[t]
    sigma2 = np.exp(f)
    return {'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu,
            'lam': lam, 'persistence': beta}, sigma2, f


def gas_skewt_forecast(params, last_r, last_sigma2, last_f):
    nu = params['nu']; lam = params['lam']
    a, b, _ = _skewt_abc(nu, lam)
    z = last_r / max(np.sqrt(last_sigma2), 1e-10)
    sign_denom = (1.0 - lam) if z < -a / b else (1.0 + lam)
    u = (b * z + a) / sign_denom
    dlog_dz = (- (nu + 1.0) * b * u
               / (sign_denom * (nu - 2.0 + u**2)))
    score_f = dlog_dz * (-0.5 * z) - 0.5
    S = 2.0 * nu / ((nu + 3.0) * (nu - 2.0))
    scaled_score = np.clip(S * score_f, -50.0, 50.0)
    new_f = (params['omega'] + params['alpha'] * scaled_score
             + params['beta'] * last_f)
    h = np.exp(new_f)
    return max(h, 1e-10), new_f


# ============================================================
# VaR / ES quantile helpers
# ============================================================
_TRAPEZ = getattr(np, 'trapezoid', None) or np.trapz


def _build_skewt_cdf(nu, lam, z_lo=-20.0, z_hi=20.0, n_pts=8000):
    """Build a stable skew-t CDF on a FIXED fine grid (Gemini fix for
    brentq chatter). Returns (grid_z, grid_cdf) suitable for np.interp."""
    zs = np.linspace(z_lo, z_hi, n_pts)
    log_pdf = _skewt_logpdf_stdz(zs, nu, lam)
    pdf = np.exp(log_pdf)
    # Cumulative trapezoidal integration
    # Trapezoid rule: each cell = 0.5*(f_i + f_{i+1})*dx
    dx = zs[1] - zs[0]
    cum = np.concatenate([[0.0], np.cumsum(0.5 * (pdf[:-1] + pdf[1:]) * dx)])
    # Normalize to make cum[-1] = 1 (in case tails were cut off)
    if cum[-1] > 0:
        cum = cum / cum[-1]
    return zs, cum


def skewt_quantile_from_grid(alpha_level, grid_z, grid_cdf):
    """Interpolate quantile from pre-built CDF grid."""
    if alpha_level <= grid_cdf[0]:
        return grid_z[0]
    if alpha_level >= grid_cdf[-1]:
        return grid_z[-1]
    # grid_cdf is monotonic; use interp (grid_cdf as x, grid_z as y)
    return float(np.interp(alpha_level, grid_cdf, grid_z))


def skewt_es_stdz_from_grid(alpha_level, nu, lam, var_z, grid_z=None):
    """E[Z | Z < var_z] using fixed-grid trapezoid integration.
    (Pre-builds short grid -20 → var_z with 3000 pts.)
    """
    if np.isnan(var_z):
        return np.nan
    zs = np.linspace(-20.0, var_z, 3000)
    log_pdf = _skewt_logpdf_stdz(zs, nu, lam)
    pdf = np.exp(log_pdf)
    numer = _TRAPEZ(zs * pdf, zs)
    denom = _TRAPEZ(pdf, zs)
    if denom < 1e-12:
        return np.nan
    return float(numer / denom)


# Cache (nu_rounded, lam_rounded) → (q_01, q_05, es_01, es_05)
# Since we only refit every REFIT_EVERY (63 days), the quantiles are
# constant within each window — but we still enter var_es_from_forecast
# for every OOS day. Cache speeds this up ~100×.
_SKEWT_CACHE = {}


def skewt_quantiles_cached(nu, lam, alpha_levels=(0.01, 0.05)):
    """Return (q_alpha, es_alpha) dict, cached by (rounded nu, rounded lam)."""
    key = (round(float(nu), 3), round(float(lam), 3))
    if key in _SKEWT_CACHE:
        return _SKEWT_CACHE[key]
    grid_z, grid_cdf = _build_skewt_cdf(nu, lam)
    out = {}
    for a in alpha_levels:
        q = skewt_quantile_from_grid(a, grid_z, grid_cdf)
        es = skewt_es_stdz_from_grid(a, nu, lam, q)
        out[a] = (q, es)
    _SKEWT_CACHE[key] = out
    return out


def normal_var_es(alpha_level):
    z = stats.norm.ppf(alpha_level)
    es = -stats.norm.pdf(z) / alpha_level
    return z, es


def student_t_var_es(alpha_level, nu):
    """Standardized (var=1) Student-t: z quantile and ES."""
    if nu <= 2:
        return np.nan, np.nan
    scale = np.sqrt((nu - 2) / nu)
    t_q = stats.t.ppf(alpha_level, df=nu)
    var_z = t_q * scale
    es_raw = -(stats.t.pdf(t_q, df=nu) / alpha_level * (nu + t_q**2) / (nu - 1))
    es_z = es_raw * scale
    return var_z, es_z


# ============================================================
# Evaluation: QLIKE + DM-HLN + BH
# ============================================================
def qlike_pointwise(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    out = np.full_like(actual, np.nan, dtype=float)
    valid = ((predicted > 0) & np.isfinite(predicted)
             & (actual > 0) & np.isfinite(actual))
    ratio = np.where(valid, actual / predicted, np.nan)
    out[valid] = ratio[valid] - np.log(ratio[valid]) - 1
    return out


def qlike(actual, predicted):
    return float(np.nanmean(qlike_pointwise(actual, predicted)))


def dm_hln_test(loss1, loss2, h=1):
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0, n
    d_mean = np.mean(d)
    max_lag = int(np.floor(n ** (1/3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0, n
    dm_stat = d_mean / np.sqrt(var_d)
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = hln * dm_stat
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value), int(n)


def benjamini_hochberg(pvals):
    pvals = np.asarray(pvals, dtype=float)
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    adj = ranked * n / (np.arange(n) + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.clip(adj, 0, 1)
    out = np.zeros(n)
    out[order] = adj
    return out.tolist()


# ============================================================
# VaR backtests: Kupiec + Christoffersen CC + Engle-Manganelli DQ
# ============================================================
def kupiec_test(violations, alpha_level, n):
    n_viol = int(np.sum(violations))
    if n_viol == 0 or n_viol == n:
        return 0.0, 1.0
    p_hat = n_viol / n
    lr = 2 * (n_viol * np.log(p_hat / alpha_level) +
              (n - n_viol) * np.log((1 - p_hat) / (1 - alpha_level)))
    return float(lr), float(1 - stats.chi2.cdf(lr, 1))


def christoffersen_cc_test(violations, alpha_level):
    """Christoffersen (1998) Conditional Coverage test (joint uc + ind).
    LR_cc = LR_uc + LR_ind ~ chi2(2) under H0 (correct coverage AND independence).

    LR_uc: unconditional coverage (Kupiec-equivalent) with null p = alpha_level.
    LR_ind: independence, null = p01 = p11 (no clustering).
    """
    n = len(violations)
    v = violations.astype(int)
    n_viol = int(v.sum())
    if n_viol == 0 or n_viol == n:
        return 0.0, 1.0
    # LR_uc (Kupiec under alternative that p = p_hat)
    p_hat = n_viol / n
    try:
        lr_uc = 2 * (n_viol * np.log(p_hat / alpha_level) +
                     (n - n_viol) * np.log((1 - p_hat) / (1 - alpha_level)))
    except Exception:
        lr_uc = 0.0

    # LR_ind (independence)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, n):
        if v[t-1] == 0 and v[t] == 0: n00 += 1
        elif v[t-1] == 0 and v[t] == 1: n01 += 1
        elif v[t-1] == 1 and v[t] == 0: n10 += 1
        else: n11 += 1
    p01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p_uncond = (n01 + n11) / (n - 1) if n > 1 else 0
    if p_uncond <= 0 or p_uncond >= 1:
        lr_ind = 0.0
    else:
        try:
            ll_ind = 0.0
            if n00 > 0 and 0 < p01 < 1: ll_ind += n00 * np.log(1 - p01)
            if n01 > 0 and 0 < p01 < 1: ll_ind += n01 * np.log(p01)
            if n10 > 0 and 0 < p11 < 1: ll_ind += n10 * np.log(1 - p11)
            if n11 > 0 and 0 < p11 < 1: ll_ind += n11 * np.log(p11)
            ll_0 = ((n00 + n10) * np.log(1 - p_uncond)
                    + (n01 + n11) * np.log(p_uncond))
            lr_ind = -2 * (ll_0 - ll_ind)
        except Exception:
            lr_ind = 0.0

    lr_cc = lr_uc + lr_ind
    try:
        p_cc = float(1 - stats.chi2.cdf(lr_cc, 2))
    except Exception:
        p_cc = 1.0
    return float(lr_cc), p_cc


def dq_test(violations, var_values, alpha_level, lags=4):
    """Engle-Manganelli (2004) Dynamic Quantile test.
    Regress H_t = I_t - alpha on constant + lagged H_t + VaR_t.
    Under H0: beta = 0 → LR ~ chi2(lags + 2).
    """
    n = len(violations)
    H = violations.astype(float) - alpha_level
    if n < lags + 10:
        return 0.0, 1.0
    # Build regressor matrix
    X_list = [np.ones(n - lags)]
    for L in range(1, lags + 1):
        X_list.append(H[lags - L:n - L])
    # Also include VaR_t (if time-varying; exclude constant collinearity)
    X_list.append(var_values[lags:])
    X = np.column_stack(X_list)
    y = H[lags:]
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        # DQ stat: beta'(X'X)beta / (alpha(1-alpha))
        XtX = X.T @ X
        try:
            XtX_inv = np.linalg.pinv(XtX)
        except Exception:
            return 0.0, 1.0
        dq_stat = float(beta @ XtX @ beta / (alpha_level * (1 - alpha_level)))
        df = X.shape[1]
        p = float(1 - stats.chi2.cdf(dq_stat, df))
        return dq_stat, p
    except Exception:
        return 0.0, 1.0


# ============================================================
# ES backtests: Acerbi-Szekely (2014) Z1 and Z2
# ============================================================
def acerbi_szekely_z1(returns, var_values, es_values):
    """Acerbi-Szekely (2014) Z1 test.
    Z1 = mean(r/ES | r < VaR) - 1  (our convention: ES, VaR, returns all same sign)
    Under H0 (correct ES): E[Z1] = 0.
    SE is estimated from the sample std of (r/ES) ratios across violations
    (Gemini review fix: was hardcoded 1/sqrt(n) assuming unit variance).
    """
    violations = returns < var_values
    n_viol = int(np.sum(violations))
    if n_viol < 3:
        return np.nan, 1.0, n_viol
    viol_idx = np.where(violations)[0]
    # ES is negative (tail); returns/ES should average to 1 under correct spec
    ratios = returns[viol_idx] / es_values[viol_idx]
    Z1 = float(np.mean(ratios) - 1)
    # Empirical SE of the mean estimator
    sample_std = float(np.std(ratios, ddof=1)) if n_viol > 1 else 1.0
    if sample_std < 1e-10:
        sample_std = 1.0
    se = sample_std / np.sqrt(n_viol)
    z_stat = Z1 / se if se > 0 else 0.0
    p_val = 2 * (1 - stats.norm.cdf(abs(z_stat)))
    return float(z_stat), float(p_val), n_viol


def acerbi_szekely_z2(returns, var_values, es_values, alpha_level):
    """Z2 test: Z2 = sum(r_t * I(r_t < VaR_t) / (N * alpha * ES_t)) + 1
    Under H0: E[Z2] = 0.
    """
    violations = returns < var_values
    n = len(returns)
    indicator = violations.astype(float)
    # r_t / ES_t * I / (n * alpha)
    numerator = np.sum(returns * indicator / es_values)
    Z2 = numerator / (n * alpha_level) - 1
    # Approximate normal: SE under H0 ≈ sqrt(variance of Z2 terms) / (n*alpha)
    # Use simple proxy: bootstrap SE
    if np.sum(violations) < 3:
        return np.nan, 1.0
    z_terms = returns * indicator / es_values
    se = np.std(z_terms, ddof=1) / (np.sqrt(n) * alpha_level)
    z_stat = Z2 / se if se > 0 else 0.0
    p_val = 2 * (1 - stats.norm.cdf(abs(z_stat)))
    return float(z_stat), float(p_val)


def var_es_from_forecast(model, params, sigma2_pred):
    """Given model identifier and sigma2 forecast, return (VaR_1%, VaR_5%, ES_1%, ES_5%)."""
    sigma = np.sqrt(sigma2_pred)
    if model == 'M0':
        q1, es1 = normal_var_es(0.01)
        q5, es5 = normal_var_es(0.05)
    elif model == 'M1':
        nu = params.get('nu', 8.0)
        q1, es1 = student_t_var_es(0.01, nu)
        q5, es5 = student_t_var_es(0.05, nu)
    elif model == 'M2':
        nu = params.get('nu', 8.0)
        lam = params.get('lam', 0.0)
        cache = skewt_quantiles_cached(nu, lam)
        q1, es1 = cache[0.01]
        q5, es5 = cache[0.05]
    else:
        raise ValueError(model)
    return (q1 * sigma, q5 * sigma, es1 * sigma, es5 * sigma)


# ============================================================
# OOS loop per asset
# ============================================================
model_keys = ['M0', 'M1', 'M2']
model_labels = {'M0': 'GARCH-N', 'M1': 'GAS-t (sym)', 'M2': 'GAS-skewt'}
all_results = {}

for ticker, d in asset_data.items():
    print(f'\n{"="*60}')
    print(f'  Processing: {ticker} ({d["group"]})')
    print(f'{"="*60}')
    sys.stdout.flush()

    returns_pct = d['returns_pct']
    # Restrict to IS_START onwards for windowing consistency
    mask_start = returns_pct.index >= IS_START
    returns_pct = returns_pct[mask_start]
    returns = returns_pct.values
    dates = returns_pct.index

    oos_mask = dates >= OOS_START
    if not any(oos_mask):
        print('  SKIP: No OOS data')
        continue
    oos_start_idx = int(np.where(oos_mask)[0][0])
    if oos_start_idx < WINDOW:
        print(f'  SKIP: Not enough IS data ({oos_start_idx} < {WINDOW})')
        continue
    n_oos = len(returns) - oos_start_idx
    print(f'  IS: {dates[0].strftime("%Y-%m-%d")} ~ '
          f'{dates[oos_start_idx-1].strftime("%Y-%m-%d")}')
    print(f'  OOS: {dates[oos_start_idx].strftime("%Y-%m-%d")} ~ '
          f'{dates[-1].strftime("%Y-%m-%d")} ({n_oos} obs)')

    # IS diagnostic — fit once on 2010-2019 returns before OOS
    is_returns = returns[:oos_start_idx]
    is_fit_m1 = fit_gas_t(is_returns)
    is_fit_m2 = fit_gas_skewt(is_returns)
    is_nu_m1 = is_fit_m1[0]['nu'] if is_fit_m1[0] else np.nan
    is_nu_m2 = is_fit_m2[0]['nu'] if is_fit_m2[0] else np.nan
    is_lam_m2 = is_fit_m2[0]['lam'] if is_fit_m2[0] else np.nan
    print(f'  IS diag: ν̂_M1={is_nu_m1:.2f}, ν̂_M2={is_nu_m2:.2f}, '
          f'λ̂_M2={is_lam_m2:+.3f}')
    sys.stdout.flush()

    forecasts = {m: np.full(n_oos, np.nan) for m in model_keys}
    var_1_pct = {m: np.full(n_oos, np.nan) for m in model_keys}
    var_5_pct = {m: np.full(n_oos, np.nan) for m in model_keys}
    es_1_pct = {m: np.full(n_oos, np.nan) for m in model_keys}
    es_5_pct = {m: np.full(n_oos, np.nan) for m in model_keys}
    params_cur = {m: None for m in model_keys}

    state_m0_sigma2 = None
    state_m1_sigma2 = state_m1_f = None
    state_m2_sigma2 = state_m2_f = None

    last_fit = -REFIT_EVERY
    t0 = time.time()

    for t_oos in range(n_oos):
        t_abs = oos_start_idx + t_oos

        if (t_oos - last_fit) >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_returns = returns[train_start:t_abs]
            if len(train_returns) < 500:
                continue

            # M0 GARCH-N
            p0, s2_0 = fit_garch_normal(train_returns)
            if p0 is not None:
                params_cur['M0'] = p0
                state_m0_sigma2 = float(s2_0[-1])

            # M1 symmetric GAS-t
            out_m1 = fit_gas_t(train_returns)
            if out_m1[0] is not None:
                p1, s2_1, f_1 = out_m1
                params_cur['M1'] = p1
                state_m1_sigma2 = float(s2_1[-1])
                state_m1_f = float(f_1[-1])

            # M2 Skew-t GAS
            out_m2 = fit_gas_skewt(train_returns)
            if out_m2[0] is not None:
                p2, s2_2, f_2 = out_m2
                params_cur['M2'] = p2
                state_m2_sigma2 = float(s2_2[-1])
                state_m2_f = float(f_2[-1])

            last_fit = t_oos
            if t_oos % (REFIT_EVERY * 3) == 0:
                elapsed = time.time() - t0
                pct = t_oos / n_oos * 100
                lam_s = (f"λ={params_cur['M2']['lam']:+.2f}"
                         if params_cur['M2'] else 'λ=NA')
                print(f'  [{ticker}] {pct:3.0f}% ({t_oos}/{n_oos}) '
                      f'{elapsed:5.1f}s  {lam_s}')
                sys.stdout.flush()

        last_r = returns[t_abs - 1]

        # M0 forecast
        if params_cur['M0'] is not None:
            h0 = garch_n_forecast(params_cur['M0'], last_r, state_m0_sigma2)
            forecasts['M0'][t_oos] = h0
            state_m0_sigma2 = h0
            v1, v5, e1, e5 = var_es_from_forecast('M0', params_cur['M0'], h0)
            var_1_pct['M0'][t_oos] = v1
            var_5_pct['M0'][t_oos] = v5
            es_1_pct['M0'][t_oos] = e1
            es_5_pct['M0'][t_oos] = e5

        # M1 forecast
        if params_cur['M1'] is not None:
            h1, new_f1 = gas_t_forecast(params_cur['M1'], last_r,
                                        state_m1_sigma2, state_m1_f)
            forecasts['M1'][t_oos] = h1
            state_m1_sigma2 = h1
            state_m1_f = new_f1
            v1, v5, e1, e5 = var_es_from_forecast('M1', params_cur['M1'], h1)
            var_1_pct['M1'][t_oos] = v1
            var_5_pct['M1'][t_oos] = v5
            es_1_pct['M1'][t_oos] = e1
            es_5_pct['M1'][t_oos] = e5

        # M2 forecast
        if params_cur['M2'] is not None:
            h2, new_f2 = gas_skewt_forecast(params_cur['M2'], last_r,
                                            state_m2_sigma2, state_m2_f)
            forecasts['M2'][t_oos] = h2
            state_m2_sigma2 = h2
            state_m2_f = new_f2
            v1, v5, e1, e5 = var_es_from_forecast('M2', params_cur['M2'], h2)
            var_1_pct['M2'][t_oos] = v1
            var_5_pct['M2'][t_oos] = v5
            es_1_pct['M2'][t_oos] = e1
            es_5_pct['M2'][t_oos] = e5

    elapsed = time.time() - t0
    print(f'  [{ticker}] done in {elapsed:.1f}s')
    sys.stdout.flush()

    # Evaluate --------------------------------------------------------
    actual_r2 = returns[oos_start_idx:]**2
    oos_returns = returns[oos_start_idx:]
    oos_dates = dates[oos_start_idx:]

    valid_mask = np.ones(n_oos, dtype=bool)
    for m in model_keys:
        valid_mask &= np.isfinite(forecasts[m])
        valid_mask &= np.isfinite(var_1_pct[m])
        valid_mask &= np.isfinite(var_5_pct[m])
    if np.sum(valid_mask) < 100:
        print(f'  SKIP: <100 valid forecasts')
        continue

    actual_r2_v = actual_r2[valid_mask]
    oos_returns_v = oos_returns[valid_mask]
    n_valid = len(actual_r2_v)
    print(f'  Valid OOS: {n_valid}')

    # --- H1: QLIKE & DM-HLN ---
    qlike_ind = {}
    for m in model_keys:
        fc = forecasts[m][valid_mask]
        ql = qlike_pointwise(actual_r2_v, fc)
        qlike_ind[m] = ql

    model_metrics = {}
    for m in model_keys:
        fc = forecasts[m][valid_mask]
        q = qlike(actual_r2_v, fc)
        rho, rho_p = stats.spearmanr(actual_r2_v, fc)
        model_metrics[m] = {
            'QLIKE': float(q),
            'Spearman_rho': float(rho),
            'Spearman_p': float(rho_p),
        }
        print(f'    {m} ({model_labels[m]}): QLIKE={q:.6f}, rho={rho:.3f}')

    # DM-HLN tests: M2 vs M0 (primary H1), M2 vs M1, M1 vs M0 (reference)
    dm_results = {}
    comps = [
        ('M1_vs_M0', 'M1', 'M0'),  # reference: replicates K1129 direction
        ('M2_vs_M0', 'M2', 'M0'),  # H1 primary
        ('M2_vs_M1', 'M2', 'M1'),  # M2 marginal over M1
    ]
    for name, new_m, base_m in comps:
        t_stat, p_val, n_used = dm_hln_test(qlike_ind[base_m], qlike_ind[new_m])
        q_base = model_metrics[base_m]['QLIKE']
        q_new = model_metrics[new_m]['QLIKE']
        rel_impr = (q_base - q_new) / q_base * 100
        dm_results[name] = {
            'DM_HLN_t': float(t_stat),
            'DM_HLN_p': float(p_val),
            'n_used': int(n_used),
            'QLIKE_rel_improvement_pct': float(rel_impr),
            'better': new_m if t_stat > 0 else base_m,
        }
        print(f'    DM-HLN {name}: t={t_stat:+.3f}, p={p_val:.3e}, '
              f'rel_impr={rel_impr:+.2f}%')

    # --- H2: VaR backtests ---
    print(f'\n  --- H2: VaR backtests ---')
    var_backtests = {'alpha_0.01': {}, 'alpha_0.05': {}}
    for alpha_level, var_arr in [(0.01, var_1_pct), (0.05, var_5_pct)]:
        for m in model_keys:
            var_v = var_arr[m][valid_mask]
            violations = oos_returns_v < var_v
            n_viol = int(np.sum(violations))
            viol_rate = float(np.mean(violations))
            kup_lr, kup_p = kupiec_test(violations, alpha_level, n_valid)
            cc_lr, cc_p = christoffersen_cc_test(violations, alpha_level)
            dq_stat, dq_p = dq_test(violations, var_v, alpha_level, lags=4)
            var_backtests[f'alpha_{alpha_level}'][m] = {
                'violation_rate': viol_rate,
                'n_violations': n_viol,
                'expected_violations': float(alpha_level * n_valid),
                'Kupiec_LR': float(kup_lr),
                'Kupiec_p': float(kup_p),
                'Christoffersen_CC_LR': float(cc_lr),
                'Christoffersen_CC_p': float(cc_p),
                'DQ_stat': float(dq_stat),
                'DQ_p': float(dq_p),
                'Trinity_PASS': bool(kup_p > 0.05 and cc_p > 0.05 and dq_p > 0.05),
            }
            print(f'    {m} @ {alpha_level*100:.0f}%: '
                  f'viol={viol_rate*100:.2f}% (exp {alpha_level*100:.0f}%), '
                  f'Kupiec_p={kup_p:.3f}, CC_p={cc_p:.3f}, DQ_p={dq_p:.3f}')

    # --- H3: ES backtests ---
    print(f'\n  --- H3: ES backtests (Acerbi-Szekely 2014) ---')
    es_backtests = {'alpha_0.01': {}, 'alpha_0.05': {}}
    for alpha_level, var_arr, es_arr in [
        (0.01, var_1_pct, es_1_pct),
        (0.05, var_5_pct, es_5_pct),
    ]:
        for m in model_keys:
            var_v = var_arr[m][valid_mask]
            es_v = es_arr[m][valid_mask]
            z1, p1, nv = acerbi_szekely_z1(oos_returns_v, var_v, es_v)
            z2, p2 = acerbi_szekely_z2(oos_returns_v, var_v, es_v, alpha_level)
            es_backtests[f'alpha_{alpha_level}'][m] = {
                'Z1': float(z1) if np.isfinite(z1) else None,
                'Z1_p': float(p1),
                'Z1_PASS': bool(np.isfinite(z1) and p1 > 0.05),
                'Z2': float(z2) if np.isfinite(z2) else None,
                'Z2_p': float(p2),
                'Z2_PASS': bool(np.isfinite(z2) and p2 > 0.05),
                'n_violations_used': nv,
            }
            z1s = f'{z1:+.3f}' if np.isfinite(z1) else 'NA'
            z2s = f'{z2:+.3f}' if np.isfinite(z2) else 'NA'
            print(f'    {m} @ {alpha_level*100:.0f}%: Z1={z1s} (p={p1:.3f}), '
                  f'Z2={z2s} (p={p2:.3f})')

    all_results[ticker] = {
        'n_oos': int(n_valid),
        'oos_start': str(oos_dates[0].strftime('%Y-%m-%d')),
        'oos_end': str(oos_dates[-1].strftime('%Y-%m-%d')),
        'group': d['group'],
        'full_skew': d['full_skew'],
        'full_kurt': d['full_kurt'],
        'is_diagnostic': {
            'nu_M1_sym': float(is_nu_m1) if np.isfinite(is_nu_m1) else None,
            'nu_M2_skewt': float(is_nu_m2) if np.isfinite(is_nu_m2) else None,
            'lam_M2_skewt': float(is_lam_m2) if np.isfinite(is_lam_m2) else None,
        },
        'model_metrics': model_metrics,
        'dm_tests': dm_results,
        'var_backtests': var_backtests,
        'es_backtests': es_backtests,
    }

sys.stdout.flush()


# ============================================================
# BH FDR adjustment across 3 hypotheses × 4 commodities
# ============================================================
print('\n' + '=' * 72)
print('BH FDR ADJUSTMENT — across {H1 QLIKE DM M2 vs M0} × 4 tickers')
print('=' * 72)

tickers = list(all_results.keys())
# H1 primary: M2 vs M0 QLIKE DM p-values
h1_pvals = []
for t in tickers:
    p = all_results[t]['dm_tests']['M2_vs_M0']['DM_HLN_p']
    h1_pvals.append(p)
h1_bh = benjamini_hochberg(h1_pvals) if len(h1_pvals) > 0 else []
for i, t in enumerate(tickers):
    all_results[t]['dm_tests']['M2_vs_M0']['BH_p'] = h1_bh[i]
    print(f'  {t}: DM_p={h1_pvals[i]:.4f}, BH_p={h1_bh[i]:.4f}')


# ============================================================
# CROSS-ASSET SUMMARY + Verdict
# ============================================================
print('\n' + '=' * 72)
print('CROSS-ASSET SUMMARY')
print('=' * 72)
print(f'\n{"Asset":<8} {"group":<11} {"skew":>7} {"kurt":>7} '
      f'{"ν̂_M1":>6} {"ν̂_M2":>6} {"λ̂_M2":>7}')
print('-' * 60)
for t in tickers:
    r = all_results[t]
    diag = r['is_diagnostic']
    nu1 = diag['nu_M1_sym']
    nu2 = diag['nu_M2_skewt']
    lam = diag['lam_M2_skewt']
    print(f'{t:<8} {r["group"]:<11} {r["full_skew"]:>+7.3f} {r["full_kurt"]:>7.2f} '
          f'{nu1:>6.2f} {nu2:>6.2f} {lam:>+7.3f}')

print(f'\n{"Asset":<8} {"M0 QL":>9} {"M1 QL":>9} {"M2 QL":>9} {"M2 vs M0 t":>12} {"BH_p":>7}')
print('-' * 60)
for t in tickers:
    r = all_results[t]
    mm = r['model_metrics']
    dm = r['dm_tests']['M2_vs_M0']
    print(f'{t:<8} {mm["M0"]["QLIKE"]:>9.4f} {mm["M1"]["QLIKE"]:>9.4f} '
          f'{mm["M2"]["QLIKE"]:>9.4f} {dm["DM_HLN_t"]:>+12.3f} {dm["BH_p"]:>7.3f}')

# Scenario determination
h1_pass_count = 0
for t in tickers:
    dm = all_results[t]['dm_tests']['M2_vs_M0']
    if dm['DM_HLN_t'] > 2 and dm['BH_p'] < 0.05:
        h1_pass_count += 1

h2_pass_count_1pct = 0
h2_pass_count_5pct = 0
for t in tickers:
    vb = all_results[t]['var_backtests']
    if vb['alpha_0.01']['M2']['Trinity_PASS']:
        h2_pass_count_1pct += 1
    if vb['alpha_0.05']['M2']['Trinity_PASS']:
        h2_pass_count_5pct += 1

h3_pass_count_1pct = 0
h3_pass_count_5pct = 0
for t in tickers:
    eb = all_results[t]['es_backtests']
    # Require BOTH Z1 and Z2 to pass
    if eb['alpha_0.01']['M2']['Z1_PASS'] and eb['alpha_0.01']['M2']['Z2_PASS']:
        h3_pass_count_1pct += 1
    if eb['alpha_0.05']['M2']['Z1_PASS'] and eb['alpha_0.05']['M2']['Z2_PASS']:
        h3_pass_count_5pct += 1

N = len(tickers)
print(f'\n--- Hypothesis Summary ---')
print(f'H1 (QLIKE DM M2>M0, t>+2 & BH_p<0.05): {h1_pass_count}/{N}')
print(f'H2 (VaR Trinity @1%): {h2_pass_count_1pct}/{N}')
print(f'H2 (VaR Trinity @5%): {h2_pass_count_5pct}/{N}')
print(f'H3 (ES Z1+Z2 @1%):    {h3_pass_count_1pct}/{N}')
print(f'H3 (ES Z1+Z2 @5%):    {h3_pass_count_5pct}/{N}')

# Scenario assignment
h1_PASS = h1_pass_count >= N / 2  # majority of assets
h2_PASS = (h2_pass_count_1pct + h2_pass_count_5pct) >= N  # at least 1 level each or combined coverage
h3_PASS = (h3_pass_count_1pct + h3_pass_count_5pct) >= N  # similar

# Simpler binary thresholds
h1_PASS = h1_pass_count >= 2
h2_PASS = max(h2_pass_count_1pct, h2_pass_count_5pct) >= 2
h3_PASS = max(h3_pass_count_1pct, h3_pass_count_5pct) >= 2

if h1_PASS and h2_PASS and h3_PASS:
    SCENARIO = 'A'
    scenario_desc = 'Skew-t PASS on vol AND tail'
elif not h1_PASS and h2_PASS and h3_PASS:
    SCENARIO = 'B'
    scenario_desc = 'Only VaR/ES improved, QLIKE NULL'
elif h1_PASS and not (h2_PASS and h3_PASS):
    SCENARIO = 'C'
    scenario_desc = 'Vol only, tail NULL'
else:
    SCENARIO = 'D'
    scenario_desc = 'Skew-t FAIL everywhere'

print(f'\n>>> VERDICT: Scenario {SCENARIO} — {scenario_desc}')
if SCENARIO == 'D':
    print('    Paper 4 Channel 3: "GAS-t universally inappropriate" narrative COMPLETE.')
elif SCENARIO == 'B':
    print('    Paper 4 Channel 3: add commodity subsection "GAS-skewt for tail risk only".')
elif SCENARIO == 'A':
    print('    Paper 4 Channel 3: add commodity subsection "GAS-skewt captures commodity downside".')
else:
    print('    Paper 4 Channel 3: narrative ambiguous — partial fix.')
sys.stdout.flush()


# ============================================================
# CHARTS
# ============================================================
colors = {'M0': '#2196F3', 'M1': '#4CAF50', 'M2': '#E91E63'}

# Chart 1: commodity skew + Gaussian reference
fig, axes = plt.subplots(1, len(tickers), figsize=(4*len(tickers), 4))
if len(tickers) == 1:
    axes = [axes]
for i, t in enumerate(tickers):
    rp = asset_data[t]['returns_pct']
    mask = rp.index >= IS_START
    data = rp[mask].values
    ax = axes[i]
    ax.hist(data, bins=80, density=True, alpha=0.6, color='#888', label='Empirical')
    xs = np.linspace(data.min(), data.max(), 300)
    ax.plot(xs, stats.norm.pdf(xs, data.mean(), data.std()), 'r-', lw=2, label='Gauss')
    ax.set_title(f'{t} (skew={stats.skew(data):+.2f}, '
                 f'kurt={stats.kurtosis(data):+.1f})')
    ax.set_xlim(-10, 10)
    ax.set_yscale('log')
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'commodity_skew_vs_gauss.png')
plt.savefig(chart1_path, dpi=150)
plt.close()
print(f'\n  Chart 1: {chart1_path}')

# Chart 2: VaR + ES backtest heatmap (p-values)
fig, axes = plt.subplots(2, 2, figsize=(14, 8))
for i, (alpha_level, var_arr, es_arr) in enumerate([
    (0.01, var_backtests.get('alpha_0.01', {}), es_backtests.get('alpha_0.01', {})),
    (0.05, var_backtests.get('alpha_0.05', {}), es_backtests.get('alpha_0.05', {})),
]):
    # VaR Trinity p-values matrix (Kupiec, CC, DQ) × 3 models × N tickers
    ax_var = axes[i, 0]
    mat_var = np.zeros((len(tickers), 3 * len(model_keys)))
    for ti, t in enumerate(tickers):
        vb = all_results[t]['var_backtests'][f'alpha_{alpha_level}']
        for mi, m in enumerate(model_keys):
            mat_var[ti, mi*3 + 0] = vb[m]['Kupiec_p']
            mat_var[ti, mi*3 + 1] = vb[m]['Christoffersen_CC_p']
            mat_var[ti, mi*3 + 2] = vb[m]['DQ_p']
    im = ax_var.imshow(mat_var, cmap='RdYlGn', vmin=0, vmax=0.2, aspect='auto')
    labels = []
    for m in model_keys:
        labels.extend([f'{m}-Kup', f'{m}-CC', f'{m}-DQ'])
    ax_var.set_xticks(range(len(labels)))
    ax_var.set_xticklabels(labels, rotation=45, fontsize=8)
    ax_var.set_yticks(range(len(tickers)))
    ax_var.set_yticklabels(tickers)
    for ti in range(len(tickers)):
        for mi in range(3 * len(model_keys)):
            ax_var.text(mi, ti, f'{mat_var[ti, mi]:.2f}',
                        ha='center', va='center', fontsize=7)
    ax_var.set_title(f'VaR Trinity p-values @ {alpha_level*100:.0f}%')
    plt.colorbar(im, ax=ax_var, fraction=0.046)

    # ES backtest p-values
    ax_es = axes[i, 1]
    mat_es = np.zeros((len(tickers), 2 * len(model_keys)))
    for ti, t in enumerate(tickers):
        eb = all_results[t]['es_backtests'][f'alpha_{alpha_level}']
        for mi, m in enumerate(model_keys):
            mat_es[ti, mi*2 + 0] = eb[m]['Z1_p']
            mat_es[ti, mi*2 + 1] = eb[m]['Z2_p']
    im2 = ax_es.imshow(mat_es, cmap='RdYlGn', vmin=0, vmax=0.2, aspect='auto')
    labels = []
    for m in model_keys:
        labels.extend([f'{m}-Z1', f'{m}-Z2'])
    ax_es.set_xticks(range(len(labels)))
    ax_es.set_xticklabels(labels, rotation=45, fontsize=8)
    ax_es.set_yticks(range(len(tickers)))
    ax_es.set_yticklabels(tickers)
    for ti in range(len(tickers)):
        for mi in range(2 * len(model_keys)):
            ax_es.text(mi, ti, f'{mat_es[ti, mi]:.2f}',
                       ha='center', va='center', fontsize=7)
    ax_es.set_title(f'ES Acerbi-Szekely p-values @ {alpha_level*100:.0f}%')
    plt.colorbar(im2, ax=ax_es, fraction=0.046)

plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'var_es_backtest.png')
plt.savefig(chart2_path, dpi=150)
plt.close()
print(f'  Chart 2: {chart2_path}')


# ============================================================
# SAVE RESULTS
# ============================================================
results_output = {
    'experiment_id': 'K1135',
    'title': 'Skew-t GAS on negatively skewed commodities',
    'description': ('Test whether Hansen (1994) skew-t GAS recovers VaR/ES '
                    'performance on commodities (USO/UNG treatment; GLD/SLV '
                    'controls) where K1129 symmetric-t was NULL. Completes Paper 4 '
                    'Channel 3 "GAS family" narrative block.'),
    'methodology': {
        'models': ['M0 GARCH-N', 'M1 symmetric Student-t GAS (K1129)',
                   'M2 Hansen skew-t GAS (static lambda)'],
        'assets': list(ASSETS.keys()),
        'is_start': IS_START,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'evaluation_target': 'r² for QLIKE (Patton 2011); (VaR, ES) evaluated directly on returns',
        'hypotheses': {
            'H1': 'QLIKE DM-HLN M2 vs M0 — skew-t improves vol forecast',
            'H2': 'VaR 1%&5% Kupiec + Christoffersen CC + Engle-Manganelli DQ',
            'H3': 'ES 1%&5% Acerbi-Szekely (2014) Z1 and Z2 joint PASS',
        },
        'multiple_testing': 'Benjamini-Hochberg FDR across 4 commodities for H1',
    },
    'data_source': 'yfinance',
    'seed': 42,
    'references': [
        'Creal, Koopman, Lucas (2013) JASA 108(501) — GAS framework',
        'Hansen (1994) IER 35(3):705-730 — skew-t density',
        'Gonzalez-Rivera et al (2014) IJF 30(3):529-550 — time-varying skew/kurt',
        'Patton (2011) J Econometrics 160 — QLIKE proxy-robust',
        'Harvey-Leybourne-Newbold (1997) IJF 13 — DM small-sample correction',
        'Kupiec (1995); Christoffersen (1998); Engle-Manganelli (2004) JBES 22',
        'Acerbi, Szekely (2014) Risk — ES backtest',
        'Benjamini-Hochberg (1995) JRSS B 57 — FDR control',
    ],
    'prior_experiments': {
        'K1129': 'commodity symmetric GAS-t → NULL on all 4 assets',
        'K1138': 'equity GAS-t → HARMFUL (SPY DM t=-3.27, QQQ t=-2.81)',
        'K1143': 'equity static skew-t → did not rescue harm; architectural incompat.',
    },
    'results': all_results,
    'verdict': {
        'scenario': SCENARIO,
        'description': scenario_desc,
        'H1_pass_count': h1_pass_count,
        'H2_pass_count_1pct': h2_pass_count_1pct,
        'H2_pass_count_5pct': h2_pass_count_5pct,
        'H3_pass_count_1pct': h3_pass_count_1pct,
        'H3_pass_count_5pct': h3_pass_count_5pct,
        'paper4_channel3_implication': {
            'A': 'Commodity-specific subsection: skew-t captures commodity downside',
            'B': 'Commodity-specific subsection: skew-t for tail risk only',
            'C': 'Narrative ambiguous — partial fix',
            'D': 'Paper 4 Channel 3 narrative "GAS-t universally inappropriate" complete',
        }[SCENARIO],
    },
    'charts': ['commodity_skew_vs_gauss.png', 'var_es_backtest.png'],
    'created_at': datetime.now(timezone.utc).isoformat(),
}

results_path = os.path.join(SCRIPT_DIR, 'k1135_results.json')
with open(results_path, 'w') as f:
    json.dump(results_output, f, indent=2, default=str)
print(f'\n  Results saved: {results_path}')
print('\nK1135 complete.')
