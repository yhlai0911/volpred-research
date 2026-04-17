"""
K1143: GAS-t equity HARM mechanism diagnostic
================================================================================
[提出: Claude, 執行: Claude]  · 2026-04-17

Motivation
----------
K1138 discovered GAS-t is NOT just NULL on equity — it's *actively harmful*:
  SPY:  DM-HLN t = -3.27 (p_BH = 0.003)
  QQQ:  DM-HLN t = -2.81 (p_BH = 0.011)
  IWM:  DM-HLN t = -0.49 (NS)
vs K1129 commodities (USO/GLD/UNG/BTC) which are only NULL (max |t|=1.17).

Why does symmetric Student-t GAS hurt equity while only being NULL on commodity?
This diagnostic decomposes the failure mode through four hypotheses:

  M1  (K1138 baseline):  Symmetric Student-t GAS (Fisher-scaled score)
  M2  Skew-t GAS         (Hansen 1994 skew-t) — test asymmetry hypothesis
  M3  Score-clip GAS     (Winsorize scaled score at ±3σ_IS) — test overshoot
  M4  Persistence-cap    (force β ≤ 0.97) — test near-unit-root pathology
  M5  Regime-switch      (VIX tertile from IS: HAR-RV in low, GAS-t in high)

Mechanism evidence collected for each asset:
  * ν̂ distribution (IS): equity vs commodity — does equity have higher ν (more
    Gaussian-like) so GAS-t's heavy-tail downweight is mis-specified?
  * Score magnitude histogram (IS): does equity score concentrate near symmetry
    while commodity has positive-tail mass?
  * Estimated skewness fit (M2 Skew-t): does λ̂ significantly differ from 0?
  * Forecast-error bias: calm-day overprediction check.

Scenarios
  A: Skew-t PASS     → "GAS-t symmetric assumption mis-specified on equity"
  B: Clip PASS       → "Score update overshoots on equity vol clusters"
  C: Persistence-cap → "β near unity causes error compounding on equity"
  D: Regime-switch   → "GAS-t ceiling on calm equity — HAR better in low-vol"
  E: Nothing PASSES  → "Architectural incompatibility — equity vol not score-representable"

Design
------
Assets: SPY, QQQ (from K1138 harm cells — IWM skipped since t=-0.49 is NS)
IS training: 2010-01-01 ~ 2019-12-31, OOS evaluation: 2020-01-01 ~ 2026-04-10
Window: 1500, refit every 63 days (aligned with K1138)
Seed: 42
DM-HLN + BH across M2..M5 vs GARCH baseline + vs M1 symmetric GAS.

Data source: yfinance
Reproduction: python experiments/k1143/k1143.py
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
print('K1143: GAS-t equity HARM mechanism diagnostic')
print('Paper 4 channel-specific narrative rationale')
print('=' * 72)
sys.stdout.flush()


# ============================================================
# STEP 0: Data download
# ============================================================
import yfinance as yf

ASSETS = {
    'SPY': {'start': '2000-01-01', 'end': '2026-04-11'},
    'QQQ': {'start': '2000-01-01', 'end': '2026-04-11'},
}
OOS_START = '2021-01-04'   # exactly match K1138 (2021-01-04 ~ 2026-04-10)
IS_START = '2010-01-01'    # enough runway for WINDOW=1500 rolling IS
WINDOW = 1500
REFIT_EVERY = 63

print('\n[0] Downloading VIX...')
vix_raw = yf.download('^VIX', start='2000-01-01', end='2026-04-11',
                      progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].dropna()
print(f'  VIX: {vix_close.index[0].strftime("%Y-%m-%d")} ~ '
      f'{vix_close.index[-1].strftime("%Y-%m-%d")}, n={len(vix_close)}')
sys.stdout.flush()

asset_data = {}
for ticker, params in ASSETS.items():
    print(f'\n[0] Downloading {ticker}...')
    df = yf.download(ticker, start=params['start'], end=params['end'],
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    needed = ['Open', 'High', 'Low', 'Close']
    ohlc = df[needed].dropna()
    valid = (ohlc['High'] >= ohlc[['Open', 'Close']].max(axis=1)) & \
            (ohlc['Low'] <= ohlc[['Open', 'Close']].min(axis=1)) & \
            (ohlc['Low'] > 0) & (ohlc['High'] > ohlc['Low'])
    ohlc = ohlc[valid]
    returns_pct = ohlc['Close'].pct_change().dropna() * 100
    ohlc = ohlc.loc[returns_pct.index]
    log_hl = np.log(ohlc['High'] / ohlc['Low'])
    park_pct2 = (log_hl ** 2 / (4 * np.log(2)) * 10000.0)

    vix_aligned = vix_close.reindex(returns_pct.index).ffill()
    first_ok = vix_aligned.first_valid_index()
    mask = returns_pct.index >= first_ok
    returns_pct = returns_pct[mask]
    ohlc = ohlc.loc[returns_pct.index]
    park_pct2 = park_pct2.loc[returns_pct.index]
    vix_aligned = vix_aligned.loc[returns_pct.index]
    print(f'  Observations: {len(returns_pct)}')
    print(f'  Date range: {returns_pct.index[0].strftime("%Y-%m-%d")} ~ '
          f'{returns_pct.index[-1].strftime("%Y-%m-%d")}')
    print(f'  Mean r: {returns_pct.mean():.4f}%, Std r: {returns_pct.std():.4f}%')
    print(f'  Mean Park: {park_pct2.mean():.4f} (pct²)')

    # Descriptive statistics pre-2020 vs post-2020
    pre_mask = returns_pct.index < OOS_START
    post_mask = returns_pct.index >= OOS_START
    desc = {
        'pre2020': {
            'n': int(pre_mask.sum()),
            'mean': float(returns_pct[pre_mask].mean()),
            'std': float(returns_pct[pre_mask].std()),
            'skewness': float(returns_pct[pre_mask].skew()),
            'excess_kurtosis': float(returns_pct[pre_mask].kurtosis()),
        },
        'post2020': {
            'n': int(post_mask.sum()),
            'mean': float(returns_pct[post_mask].mean()),
            'std': float(returns_pct[post_mask].std()),
            'skewness': float(returns_pct[post_mask].skew()),
            'excess_kurtosis': float(returns_pct[post_mask].kurtosis()),
        },
    }
    print(f'  Pre-2020: skew={desc["pre2020"]["skewness"]:.3f}, '
          f'kurt={desc["pre2020"]["excess_kurtosis"]:.2f}')
    print(f'  Post-2020: skew={desc["post2020"]["skewness"]:.3f}, '
          f'kurt={desc["post2020"]["excess_kurtosis"]:.2f}')

    asset_data[ticker] = {
        'returns_pct': returns_pct,
        'parkinson': park_pct2,
        'vix': vix_aligned,
        'descriptive': desc,
    }

sys.stdout.flush()


# ============================================================
# Baseline: GARCH(1,1) — same "GARCH baseline" as K1138 uses GJR-N(1,1).
# We also use GJR-N(1,1) to match K1138 exactly.
# ============================================================
def gjr_normal_negloglik(params, returns):
    omega, alpha, gamma, beta = params
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = (omega + alpha * returns[t-1]**2
                     + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1])
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    nll = 0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns**2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def fit_gjr_normal(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.03, 0.05, 0.90]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999)]
    try:
        res = minimize(gjr_normal_negloglik, x0, args=(returns,),
                       method='L-BFGS-B', bounds=bounds,
                       options={'maxiter': 500})
        if not res.success:
            res = minimize(gjr_normal_negloglik, x0, args=(returns,),
                           method='Nelder-Mead', options={'maxiter': 2000})
    except Exception:
        return None, None
    omega, alpha, gamma, beta = res.x
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = (omega + alpha * returns[t-1]**2
                     + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1])
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return ({'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
             'persistence': alpha + gamma/2 + beta}, sigma2)


def gjr_n_forecast(params, last_r, last_sigma2):
    ind = 1.0 if last_r < 0 else 0.0
    h = (params['omega'] + params['alpha'] * last_r**2
         + params['gamma'] * last_r**2 * ind + params['beta'] * last_sigma2)
    return max(h, 1e-10)


# ============================================================
# M1 GAS-t (symmetric Student-t, K1138 spec) — reference for self-comparison
# ============================================================
def gas_t_negloglik(params, returns, beta_cap=None, score_clip=None):
    """
    GAS-t(1,1) with optional persistence cap and score clip.
    f_t = log(sigma2_t); f_{t+1} = omega + alpha * s_t + beta * f_t
    s_t = Fisher-scaled score.
    beta_cap: if set, beta is clipped to ≤ beta_cap (for M4).
    score_clip: if set, scaled_score is winsorized to [-score_clip, +score_clip].
    """
    omega, alpha, beta, log_nu_minus2 = params
    if beta_cap is not None:
        beta = min(beta, beta_cap)
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
            if score_clip is not None:
                scaled_score = np.clip(scaled_score, -score_clip, score_clip)
            f[t+1] = omega + alpha * scaled_score + beta * f[t]
    return nll if np.isfinite(nll) else 1e10


def fit_gas_t(returns, beta_cap=None, score_clip=None, label=''):
    """beta_cap: None or 0.97 (for M4). score_clip: None or float (for M3)."""
    T = len(returns)
    var_r = np.var(returns)
    x0 = [0.01, 0.05, 0.95, np.log(6.0)]
    b_lo, b_hi = 0.3, (beta_cap if beta_cap is not None else 0.999)
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (b_lo, b_hi),
              (np.log(0.1), np.log(100.0))]
    try:
        res = minimize(gas_t_negloglik, x0,
                       args=(returns, beta_cap, score_clip),
                       method='L-BFGS-B', bounds=bounds,
                       options={'maxiter': 500})
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [0.005, 0.1, 0.90, np.log(4.0)],
                [0.02, 0.03, min(0.97, b_hi), np.log(10.0)],
                [0.0, 0.08, 0.92, np.log(8.0)],
            ]:
                try:
                    res2 = minimize(gas_t_negloglik, x0_alt,
                                    args=(returns, beta_cap, score_clip),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None, None
    omega, alpha, beta, log_nu_minus2 = res.x
    nu = np.exp(log_nu_minus2) + 2.0
    f = np.zeros(T)
    scores = np.zeros(T)
    f[0] = np.log(var_r)
    for t in range(T - 1):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = returns[t]**2 / sigma2_t
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        if score_clip is not None:
            scaled_score = np.clip(scaled_score, -score_clip, score_clip)
        scores[t] = scaled_score
        f[t+1] = omega + alpha * scaled_score + beta * f[t]
    sigma2 = np.exp(f)
    return ({'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu,
             'persistence': beta,
             'beta_cap': beta_cap, 'score_clip': score_clip},
            sigma2, f, scores)


def gas_t_forecast(params, last_r, last_sigma2, last_f):
    nu = params['nu']
    eps2 = last_r**2 / max(last_sigma2, 1e-10)
    score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
    S = 2 * nu / ((nu + 3) * (nu - 2))
    scaled_score = S * score
    if params.get('score_clip') is not None:
        scaled_score = np.clip(scaled_score,
                               -params['score_clip'], params['score_clip'])
    new_f = (params['omega'] + params['alpha'] * scaled_score
             + params['beta'] * last_f)
    h = np.exp(new_f)
    return max(h, 1e-10), new_f


# ============================================================
# M2 GAS with Hansen (1994) Skew-t innovations
# ============================================================
# Hansen skew-t density:
#   f(z | eta, lambda) = b * c * [1 + (1/(eta-2)) * ((b*z+a)/(1-lambda sign))^2]^{-(eta+1)/2}
# where:
#   a = 4*lambda*c*(eta-2)/(eta-1)
#   b^2 = 1 + 3*lambda^2 - a^2
#   c = Gamma((eta+1)/2) / (sqrt(pi*(eta-2)) * Gamma(eta/2))
#   sign = +1 if z >= -a/b else -1
# Here z = r / sigma (standardized innovation).

def _skewt_abc(nu, lam):
    """Hansen 1994 a, b, log-c constants for standardized skew-t (var=1)."""
    log_c = (gammaln((nu + 1) / 2.0) - gammaln(nu / 2.0)
             - 0.5 * np.log(np.pi * (nu - 2.0)))
    c = np.exp(log_c)
    a = 4.0 * lam * c * (nu - 2.0) / (nu - 1.0)
    b2 = 1.0 + 3.0 * lam**2 - a**2
    b2 = max(b2, 1e-8)
    b = np.sqrt(b2)
    return a, b, log_c


def _skewt_logpdf_stdz(z, nu, lam):
    a, b, log_c = _skewt_abc(nu, lam)
    # threshold: z < -a/b (use left branch with (1-lam)) else right branch (1+lam)
    sign_denom = np.where(z < -a / b, (1.0 - lam), (1.0 + lam))
    quad = ((b * z + a) / sign_denom) ** 2
    # log density of standardized z:
    log_pdf_stdz = (np.log(b) + log_c
                    - ((nu + 1.0) / 2.0) * np.log(1.0 + quad / (nu - 2.0)))
    return log_pdf_stdz


def _skewt_score_lambda(z, nu, lam):
    """Analytic partial derivative of log f(z | nu, lam) wrt lam (for M2 GAS).
    We only use numerical derivative via finite differences for robustness:
    lambda update uses dlogf/dlambda.
    Here we return analytic df/dlam approximated by central difference."""
    h_fd = 1e-4
    return (_skewt_logpdf_stdz(z, nu, lam + h_fd)
            - _skewt_logpdf_stdz(z, nu, lam - h_fd)) / (2.0 * h_fd)


def gas_skewt_negloglik(params, returns):
    """
    GAS-t with Hansen skew-t. f_t = log sigma2_t, same as M1.
    lam is time-invariant (standard Hansen AR-skew-t uses static lambda; we
    follow that — only sigma2 is score-driven, not lambda itself).
    """
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
        # log pdf of r = log f(z) - log sigma
        ll_t = log_pdf_stdz - np.log(sigma_t)
        nll -= ll_t
        if t < T - 1:
            # Score w.r.t. f = log sigma2: s_f = d log f(r|sigma2) / df
            # log f(r | sigma2) = log f_stdz(z) - 0.5*f
            # d/df log f_stdz(z) = dlog_fstdz/dz * dz/df = dlog_fstdz/dz * (-0.5 z)
            # z = r * exp(-0.5 f) → dz/df = -0.5 z
            # dlog_fstdz/dz via analytic (Hansen):
            #   derivative wrt z: = -(nu+1)/2 * 2*(b*z+a)*b / ((1-lam sign)^2 * (nu-2 + ((b*z+a)/(1-lam sign))^2))
            sign_denom = (1.0 - lam) if z < -a / b else (1.0 + lam)
            u = (b * z + a) / sign_denom
            dlog_dz = (- (nu + 1.0) * b * u
                       / (sign_denom * (nu - 2.0 + u**2)))
            score_f = dlog_dz * (-0.5 * z) - 0.5  # -0.5 from d/df(-0.5f)
            # Fisher information I(f) for GAS scaling
            # For symmetric Student-t I(f) = 0.5*(nu+1)/(nu+3). For skew-t we use
            # the same denominator as M1 (Fisher of symmetric t) as pragmatic
            # scaling — Gonzalez-Rivera et al 2014 show this is acceptable.
            S = 2.0 * nu / ((nu + 3.0) * (nu - 2.0))
            scaled_score = S * score_f
            # clip to avoid runaway in malformed iterations
            scaled_score = np.clip(scaled_score, -50.0, 50.0)
            f[t+1] = omega + alpha * scaled_score + beta * f[t]
    return nll if np.isfinite(nll) else 1e10


def fit_gas_skewt(returns):
    """Fit M2: Skew-t GAS. Static lambda estimated jointly with vol dynamics."""
    T = len(returns)
    var_r = np.var(returns)
    # initial values
    x0_list = [
        [0.01, 0.05, 0.95, np.log(6.0), 0.0],
        [0.005, 0.08, 0.92, np.log(5.0), -0.1],
        [0.02, 0.03, 0.97, np.log(8.0), -0.2],
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
            if best is None or res.fun < best.fun:
                best = res
        except Exception:
            pass
    if best is None or not np.isfinite(best.fun):
        return None, None, None, None
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
    return ({'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu,
             'lam': lam, 'persistence': beta}, sigma2, f, None)


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
# HAR-RV (simple, no VIX) for M5 regime switch
# ============================================================
def fit_har_rv(rv_series):
    log_rv = np.log(rv_series.clip(lower=1e-10))
    daily = log_rv.shift(1)
    weekly = log_rv.shift(1).rolling(window=5).mean()
    monthly = log_rv.shift(1).rolling(window=22).mean()
    X = pd.DataFrame({'const': 1.0, 'daily': daily, 'weekly': weekly,
                      'monthly': monthly}).dropna()
    y = log_rv.loc[X.index]
    X_mat = X.values
    try:
        beta_hat, *_ = np.linalg.lstsq(X_mat, y.values, rcond=None)
    except Exception:
        return None
    resid = y.values - X_mat @ beta_hat
    sigma_resid = np.std(resid, ddof=X_mat.shape[1])
    return {'beta': beta_hat.tolist(), 'sigma_resid': float(sigma_resid)}


def har_rv_forecast(params, rv_history):
    beta = np.array(params['beta'])
    log_rv = np.log(rv_history.clip(lower=1e-10))
    if len(log_rv) < 22:
        return None
    daily = log_rv.iloc[-1]
    weekly = log_rv.iloc[-5:].mean()
    monthly = log_rv.iloc[-22:].mean()
    x = np.array([1.0, daily, weekly, monthly])
    log_rv_hat = float(x @ beta)
    sigma_resid = params['sigma_resid']
    rv_hat = np.exp(log_rv_hat + 0.5 * sigma_resid**2)
    return max(rv_hat, 1e-10)


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
# OOS LOOP per asset
# ============================================================
model_keys = ['BASE_GJR_N', 'M1_GAS_t_sym', 'M2_GAS_skewt', 'M3_GAS_t_clip',
              'M4_GAS_t_betacap', 'M5_regime_HAR_GAS']
# IS score diagnostic showed q99≈0.63, so ±3 clip never bites.
# Set to q95 ≈ 0.30 (tighter) so clip actually engages on right tail outliers.
SCORE_CLIP_VAL = 0.30  # ±0.30 on scaled score (tight; engages score-skew right tail)
BETA_CAP = 0.90        # tighter cap to force genuine persistence reduction

all_results = {}

for ticker, d in asset_data.items():
    print(f'\n{"="*60}')
    print(f'  Processing: {ticker}')
    print(f'{"="*60}')
    sys.stdout.flush()

    returns_pct = d['returns_pct']
    returns = returns_pct.values
    dates = returns_pct.index
    park = d['parkinson']
    vix = d['vix']

    # Restrict to IS_START onwards so windows are aligned
    mask_start = dates >= IS_START
    returns_pct = returns_pct[mask_start]
    returns = returns_pct.values
    dates = returns_pct.index
    park = park.loc[dates]
    vix = vix.loc[dates]

    oos_mask = dates >= OOS_START
    oos_start_idx = int(np.where(oos_mask)[0][0])
    n_oos = len(returns) - oos_start_idx
    print(f'  OOS: {dates[oos_start_idx].strftime("%Y-%m-%d")} ~ '
          f'{dates[-1].strftime("%Y-%m-%d")} ({n_oos} obs)')

    # Train IS summary (for ν̂ / score histogram diagnostic — full IS fit once)
    is_returns = returns[:oos_start_idx]
    is_vix = vix.iloc[:oos_start_idx].values
    p_m1_is, s2_m1_is, f_m1_is, scores_m1_is = fit_gas_t(is_returns)
    p_m2_is, s2_m2_is, f_m2_is, _ = fit_gas_skewt(is_returns)
    is_nu_m1 = p_m1_is['nu'] if p_m1_is else np.nan
    is_nu_m2 = p_m2_is['nu'] if p_m2_is else np.nan
    is_lam_m2 = p_m2_is['lam'] if p_m2_is else np.nan
    is_scores_m1 = scores_m1_is[:-1] if scores_m1_is is not None else np.array([])
    # VIX tertiles from IS
    is_vix_valid = is_vix[~np.isnan(is_vix)]
    vix_t1 = float(np.quantile(is_vix_valid, 1/3))
    vix_t2 = float(np.quantile(is_vix_valid, 2/3))
    print(f'  IS (2010-2019): ν̂_M1={is_nu_m1:.2f}, ν̂_M2={is_nu_m2:.2f}, '
          f'λ̂_M2={is_lam_m2:+.3f}')
    print(f'  IS VIX tertiles: T1={vix_t1:.2f}, T2={vix_t2:.2f}')
    sys.stdout.flush()

    forecasts = {m: np.full(n_oos, np.nan) for m in model_keys}
    params_cur = {m: None for m in model_keys}

    state_base_sigma2 = None
    state_m1_sigma2 = state_m1_f = None
    state_m2_sigma2 = state_m2_f = None
    state_m3_sigma2 = state_m3_f = None
    state_m4_sigma2 = state_m4_f = None
    # M5 regime switch: use BASE or HAR depending on which regime VIX_{t-1} is in
    # Low VIX (< T1 of IS) → HAR-RV; mid/high → GAS-t (M1)
    last_fit = -REFIT_EVERY
    t0 = time.time()

    for t_oos in range(n_oos):
        t_abs = oos_start_idx + t_oos

        if (t_oos - last_fit) >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_returns = returns[train_start:t_abs]
            train_park = park.iloc[train_start:t_abs]
            if len(train_returns) < 500:
                continue

            # BASE GJR-N
            p_b, s2_b = fit_gjr_normal(train_returns)
            if p_b is not None:
                params_cur['BASE_GJR_N'] = p_b
                state_base_sigma2 = float(s2_b[-1])

            # M1 symmetric GAS-t
            out_m1 = fit_gas_t(train_returns)
            if out_m1[0] is not None:
                p_m1, s2_m1, f_m1, _ = out_m1
                params_cur['M1_GAS_t_sym'] = p_m1
                state_m1_sigma2 = float(s2_m1[-1])
                state_m1_f = float(f_m1[-1])

            # M2 Skew-t GAS
            out_m2 = fit_gas_skewt(train_returns)
            if out_m2[0] is not None:
                p_m2, s2_m2, f_m2, _ = out_m2
                params_cur['M2_GAS_skewt'] = p_m2
                state_m2_sigma2 = float(s2_m2[-1])
                state_m2_f = float(f_m2[-1])

            # M3 Score-clip GAS
            out_m3 = fit_gas_t(train_returns, score_clip=SCORE_CLIP_VAL)
            if out_m3[0] is not None:
                p_m3, s2_m3, f_m3, _ = out_m3
                params_cur['M3_GAS_t_clip'] = p_m3
                state_m3_sigma2 = float(s2_m3[-1])
                state_m3_f = float(f_m3[-1])

            # M4 Persistence-cap GAS
            out_m4 = fit_gas_t(train_returns, beta_cap=BETA_CAP)
            if out_m4[0] is not None:
                p_m4, s2_m4, f_m4, _ = out_m4
                params_cur['M4_GAS_t_betacap'] = p_m4
                state_m4_sigma2 = float(s2_m4[-1])
                state_m4_f = float(f_m4[-1])

            # M5 regime: fit HAR-RV on train_park
            p_har = fit_har_rv(train_park)
            if p_har is not None:
                params_cur['M5_regime_HAR_GAS'] = {
                    'har': p_har,
                    'gas': p_m1 if out_m1[0] is not None else None,
                    'vix_t1': vix_t1,
                }

            last_fit = t_oos
            if t_oos % (REFIT_EVERY * 4) == 0:
                elapsed = time.time() - t0
                pct = t_oos / n_oos * 100
                print(f'  [{ticker}] {pct:.0f}% ({t_oos}/{n_oos}) '
                      f'{elapsed:.1f}s')
                sys.stdout.flush()

        last_r = returns[t_abs - 1]

        # BASE
        if params_cur['BASE_GJR_N'] is not None and state_base_sigma2 is not None:
            h = gjr_n_forecast(params_cur['BASE_GJR_N'], last_r, state_base_sigma2)
            forecasts['BASE_GJR_N'][t_oos] = h
            state_base_sigma2 = h

        # M1
        if (params_cur['M1_GAS_t_sym'] is not None
                and state_m1_sigma2 is not None and state_m1_f is not None):
            h, new_f = gas_t_forecast(params_cur['M1_GAS_t_sym'],
                                      last_r, state_m1_sigma2, state_m1_f)
            forecasts['M1_GAS_t_sym'][t_oos] = h
            state_m1_sigma2 = h; state_m1_f = new_f

        # M2
        if (params_cur['M2_GAS_skewt'] is not None
                and state_m2_sigma2 is not None and state_m2_f is not None):
            h, new_f = gas_skewt_forecast(params_cur['M2_GAS_skewt'],
                                          last_r, state_m2_sigma2, state_m2_f)
            forecasts['M2_GAS_skewt'][t_oos] = h
            state_m2_sigma2 = h; state_m2_f = new_f

        # M3
        if (params_cur['M3_GAS_t_clip'] is not None
                and state_m3_sigma2 is not None and state_m3_f is not None):
            h, new_f = gas_t_forecast(params_cur['M3_GAS_t_clip'],
                                      last_r, state_m3_sigma2, state_m3_f)
            forecasts['M3_GAS_t_clip'][t_oos] = h
            state_m3_sigma2 = h; state_m3_f = new_f

        # M4
        if (params_cur['M4_GAS_t_betacap'] is not None
                and state_m4_sigma2 is not None and state_m4_f is not None):
            h, new_f = gas_t_forecast(params_cur['M4_GAS_t_betacap'],
                                      last_r, state_m4_sigma2, state_m4_f)
            forecasts['M4_GAS_t_betacap'][t_oos] = h
            state_m4_sigma2 = h; state_m4_f = new_f

        # M5 regime switch (low VIX → HAR, else → GAS-t M1)
        m5p = params_cur['M5_regime_HAR_GAS']
        if m5p is not None:
            vix_last = float(vix.iloc[t_abs - 1])
            if np.isnan(vix_last):
                pass
            elif vix_last < m5p['vix_t1']:
                # HAR-RV
                if m5p['har'] is not None:
                    rv_hist = park.iloc[:t_abs]
                    h5 = har_rv_forecast(m5p['har'], rv_hist)
                    if h5 is not None:
                        forecasts['M5_regime_HAR_GAS'][t_oos] = h5
            else:
                # Use M1 GAS-t forecast (already written at [t_oos] above)
                m1_val = forecasts['M1_GAS_t_sym'][t_oos]
                if np.isfinite(m1_val):
                    forecasts['M5_regime_HAR_GAS'][t_oos] = float(m1_val)

    elapsed = time.time() - t0
    print(f'  [{ticker}] OOS done in {elapsed:.1f}s')
    sys.stdout.flush()

    # Collect valid forecasts: for DM we compare pairs, but need at least
    # BASE + each M defined. For M5, if VIX is low most of time, we still use it.
    oos_dates = dates[oos_start_idx:]
    # evaluate on r² target (GARCH/GAS native); same as K1138 "r²" view
    r2 = (returns[oos_start_idx:] ** 2)

    asset_res = {
        'n_oos': int(n_oos),
        'oos_start': str(oos_dates[0].strftime('%Y-%m-%d')),
        'oos_end': str(oos_dates[-1].strftime('%Y-%m-%d')),
        'descriptive': d['descriptive'],
        'IS_summary': {
            'nu_hat_M1_symmetric': float(is_nu_m1) if np.isfinite(is_nu_m1) else None,
            'nu_hat_M2_skewt': float(is_nu_m2) if np.isfinite(is_nu_m2) else None,
            'lam_hat_M2_skewt': float(is_lam_m2) if np.isfinite(is_lam_m2) else None,
            'vix_tertile_T1': vix_t1,
            'vix_tertile_T2': vix_t2,
            'score_m1_mean': float(np.mean(is_scores_m1)) if is_scores_m1.size else None,
            'score_m1_std': float(np.std(is_scores_m1)) if is_scores_m1.size else None,
            'score_m1_skew': float(stats.skew(is_scores_m1)) if is_scores_m1.size else None,
            'score_m1_kurt_excess': float(stats.kurtosis(is_scores_m1)) if is_scores_m1.size else None,
            'score_m1_q01': float(np.quantile(is_scores_m1, 0.01)) if is_scores_m1.size else None,
            'score_m1_q99': float(np.quantile(is_scores_m1, 0.99)) if is_scores_m1.size else None,
        },
    }

    # Model-level QLIKE and DM tests
    model_metrics = {}
    qlike_ind = {}
    for m in model_keys:
        fc = forecasts[m]
        valid = np.isfinite(fc) & (r2 > 0)
        q = qlike(r2[valid], fc[valid]) if valid.sum() > 10 else np.nan
        model_metrics[m] = {
            'QLIKE': float(q) if np.isfinite(q) else None,
            'n_valid': int(valid.sum()),
        }
        qlike_ind[m] = qlike_pointwise(r2, fc)
        print(f'    {m}: QLIKE={q:.6f}, n_valid={valid.sum()}')

    # DM tests: each M vs BASE_GJR_N and each M vs M1_GAS_t_sym
    dm_vs_base = {}
    dm_vs_m1 = {}
    pvals_list = []
    keys_list = []
    for m in ['M1_GAS_t_sym', 'M2_GAS_skewt', 'M3_GAS_t_clip',
              'M4_GAS_t_betacap', 'M5_regime_HAR_GAS']:
        # d = loss_BASE - loss_M so positive t means M beats BASE
        t_b, p_b, n_b = dm_hln_test(qlike_ind['BASE_GJR_N'], qlike_ind[m])
        q_base = model_metrics['BASE_GJR_N']['QLIKE']
        q_m = model_metrics[m]['QLIKE']
        rel_b = ((q_base - q_m) / q_base * 100) if (q_base and q_m) else np.nan
        dm_vs_base[m] = {
            'DM_HLN_t': t_b, 'DM_HLN_p': p_b, 'n_used': n_b,
            'rel_improvement_pct': float(rel_b) if np.isfinite(rel_b) else None,
            'PASS_gate': bool(t_b > 2.0),
            'Harvey': bool(t_b > 3.0),
        }
        pvals_list.append(p_b); keys_list.append(('vs_BASE', m))
        print(f'    DM vs BASE {m}: t={t_b:+.3f}, p={p_b:.3e}, rel={rel_b:+.2f}%')

        # vs M1 symmetric
        if m != 'M1_GAS_t_sym':
            t_1, p_1, n_1 = dm_hln_test(qlike_ind['M1_GAS_t_sym'], qlike_ind[m])
            q_m1_val = model_metrics['M1_GAS_t_sym']['QLIKE']
            rel_1 = ((q_m1_val - q_m) / q_m1_val * 100) if (q_m1_val and q_m) else np.nan
            dm_vs_m1[m] = {
                'DM_HLN_t': t_1, 'DM_HLN_p': p_1, 'n_used': n_1,
                'rel_improvement_pct': float(rel_1) if np.isfinite(rel_1) else None,
                'PASS_gate': bool(t_1 > 2.0),
                'Harvey': bool(t_1 > 3.0),
            }
            pvals_list.append(p_1); keys_list.append(('vs_M1', m))
            print(f'    DM vs M1 sym {m}: t={t_1:+.3f}, p={p_1:.3e}, rel={rel_1:+.2f}%')

    # BH correction across all tests for this asset
    bh_adj = benjamini_hochberg(pvals_list)
    for (kind, m), p_adj in zip(keys_list, bh_adj):
        if kind == 'vs_BASE':
            dm_vs_base[m]['DM_HLN_p_BH'] = float(p_adj)
            dm_vs_base[m]['PASS_BH'] = bool(dm_vs_base[m]['DM_HLN_t'] > 2.0 and p_adj < 0.05)
            dm_vs_base[m]['Harvey_BH'] = bool(dm_vs_base[m]['DM_HLN_t'] > 3.0 and p_adj < 0.05)
        else:
            dm_vs_m1[m]['DM_HLN_p_BH'] = float(p_adj)
            dm_vs_m1[m]['PASS_BH'] = bool(dm_vs_m1[m]['DM_HLN_t'] > 2.0 and p_adj < 0.05)

    asset_res['model_metrics'] = model_metrics
    asset_res['dm_vs_BASE_GJR_N'] = dm_vs_base
    asset_res['dm_vs_M1_GAS_t_sym'] = dm_vs_m1
    asset_res['forecasts_valid_mask_count'] = {
        m: int(np.isfinite(forecasts[m]).sum()) for m in model_keys
    }
    asset_res['r2_oos_mean'] = float(np.mean(r2))

    all_results[ticker] = asset_res

sys.stdout.flush()


# ============================================================
# Scenario classification
# ============================================================
print('\n' + '=' * 72)
print('SCENARIO CLASSIFICATION')
print('=' * 72)

def pass_on_both(key):
    """Returns True if model `key` beats BASE_GJR_N on both SPY & QQQ (DM t>+2
    AND BH p<0.05)."""
    return all(
        all_results[tk]['dm_vs_BASE_GJR_N'][key]['PASS_BH']
        for tk in all_results
    )

def not_harm_both(key):
    """Returns True if model `key` does not HARM vs BASE (i.e. DM t > -2 on both)."""
    return all(
        all_results[tk]['dm_vs_BASE_GJR_N'][key]['DM_HLN_t'] > -2.0
        for tk in all_results
    )

skewt_pass = pass_on_both('M2_GAS_skewt')
clip_pass = pass_on_both('M3_GAS_t_clip')
betacap_pass = pass_on_both('M4_GAS_t_betacap')
regime_pass = pass_on_both('M5_regime_HAR_GAS')

skewt_not_harm = not_harm_both('M2_GAS_skewt')
clip_not_harm = not_harm_both('M3_GAS_t_clip')
betacap_not_harm = not_harm_both('M4_GAS_t_betacap')
regime_not_harm = not_harm_both('M5_regime_HAR_GAS')

# Softer criterion: does at least one variant *repair* (DM_t > -2, i.e. no
# longer significantly worse than BASE)
scenario = None
if skewt_pass:
    scenario = 'A: Skew-t PASS — asymmetry is the fix'
elif clip_pass:
    scenario = 'B: Score-clip PASS — overshoot is the fix'
elif regime_pass:
    scenario = 'C: Regime-switch PASS — GAS-t ceiling in calm'
elif betacap_pass:
    scenario = 'F: Persistence-cap PASS — near-unit-root pathology'
elif skewt_not_harm and not clip_not_harm:
    scenario = 'A*: Skew-t REPAIRS (no longer harmful)'
elif clip_not_harm and not skewt_not_harm:
    scenario = 'B*: Score-clip REPAIRS'
elif regime_not_harm and not (skewt_not_harm or clip_not_harm):
    scenario = 'C*: Regime-switch REPAIRS'
elif not any([skewt_not_harm, clip_not_harm, betacap_not_harm, regime_not_harm]):
    scenario = 'D: All variants still HARM — architectural incompatibility'
else:
    scenario = 'MIXED: Multiple partial repairs'

print(f'\nSkew-t        PASS_BH (both assets): {skewt_pass}, no-harm: {skewt_not_harm}')
print(f'Score-clip    PASS_BH (both assets): {clip_pass}, no-harm: {clip_not_harm}')
print(f'Persist-cap   PASS_BH (both assets): {betacap_pass}, no-harm: {betacap_not_harm}')
print(f'Regime-switch PASS_BH (both assets): {regime_pass}, no-harm: {regime_not_harm}')
print(f'\n*** SCENARIO: {scenario} ***')

# ============================================================
# CHARTS
# ============================================================
# Chart 1: forecast error by regime (SPY + QQQ, M1 vs BASE)
fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
for idx, tk in enumerate(all_results.keys()):
    ax = axes[idx]
    res = all_results[tk]
    m_keys_plot = ['BASE_GJR_N', 'M1_GAS_t_sym', 'M2_GAS_skewt',
                   'M3_GAS_t_clip', 'M4_GAS_t_betacap', 'M5_regime_HAR_GAS']
    qs = [res['model_metrics'][m]['QLIKE'] for m in m_keys_plot]
    colors_plot = ['#757575', '#E91E63', '#4CAF50', '#FF9800',
                   '#9C27B0', '#2196F3']
    ax.bar(range(len(m_keys_plot)), qs, color=colors_plot, alpha=0.85)
    ax.set_xticks(range(len(m_keys_plot)))
    ax.set_xticklabels([m.replace('_', '\n') for m in m_keys_plot],
                       fontsize=8, rotation=0)
    ax.set_title(f'{tk} OOS QLIKE')
    ax.set_ylabel('QLIKE (lower=better)')
    ax.grid(axis='y', alpha=0.3)
    ax.axhline(res['model_metrics']['BASE_GJR_N']['QLIKE'],
               ls='--', color='gray', alpha=0.5, label='BASE')
plt.suptitle('K1143: GAS-t variants vs GJR baseline — OOS QLIKE',
             fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'gas_forecast_error_by_regime.png'),
            dpi=150)
plt.close()

# Chart 2: score magnitude histogram (IS scores from M1 symmetric GAS)
fig, axes = plt.subplots(1, 2, figsize=(13, 5))
for idx, tk in enumerate(all_results.keys()):
    ax = axes[idx]
    # Re-fit M1 on IS only to extract scores
    is_returns_tk = asset_data[tk]['returns_pct'][asset_data[tk]['returns_pct'].index >= IS_START]
    is_returns_tk = is_returns_tk[is_returns_tk.index < OOS_START]
    out = fit_gas_t(is_returns_tk.values)
    if out[0] is None:
        continue
    _, _, _, scores = out
    scores = scores[:-1]  # exclude trailing zero
    # Clip for display to see core distribution
    ax.hist(scores, bins=80, color='#2196F3', alpha=0.75,
            range=(-2, 8))
    ax.set_title(f'{tk} IS (2010-2019) scaled score distribution')
    ax.set_xlabel('Scaled score s_t (M1 symmetric GAS-t)')
    ax.set_ylabel('Frequency')
    ax.grid(alpha=0.3)
    # annotate quantiles
    q01 = np.quantile(scores, 0.01)
    q99 = np.quantile(scores, 0.99)
    ax.axvline(q01, ls='--', color='red', alpha=0.6,
               label=f'1%: {q01:.2f}')
    ax.axvline(q99, ls='--', color='red', alpha=0.6,
               label=f'99%: {q99:.2f}')
    ax.legend(fontsize=8)
plt.suptitle('K1143: IS score distribution — diagnostic for score clipping',
             fontsize=11)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'score_update_magnitude_distribution.png'),
            dpi=150)
plt.close()

print(f'\nCharts saved: gas_forecast_error_by_regime.png, '
      f'score_update_magnitude_distribution.png')


# ============================================================
# Save results JSON
# ============================================================
out = {
    'experiment_id': 'K1143',
    'title': ('GAS-t equity HARM mechanism diagnostic: which variant repairs '
              'K1138 SPY/QQQ negative t?'),
    'description': (
        'K1138 found GAS-t actively harmful on SPY (t=-3.27) and QQQ (t=-2.81). '
        'K1143 decomposes four candidate mechanisms: asymmetry (Hansen skew-t), '
        'score overshoot (winsorize at ±3), persistence near unity (β≤0.97), '
        'and GAS-t low-vol ceiling (regime switch HAR vs GAS). OOS 2020-2026 '
        'vs K1138 baseline GJR-N and vs M1 symmetric GAS-t reference.'),
    'methodology': {
        'assets': list(ASSETS.keys()),
        'IS_period': f'{IS_START} ~ 2019-12-31',
        'OOS_period': f'{OOS_START} ~ 2026-04-10',
        'window': WINDOW, 'refit_every': REFIT_EVERY,
        'score_clip_threshold': SCORE_CLIP_VAL,
        'beta_cap': BETA_CAP,
        'models': {
            'BASE_GJR_N': 'GJR-GARCH(1,1) Normal, K1138 baseline',
            'M1_GAS_t_sym': 'K1138 symmetric Student-t GAS (reference)',
            'M2_GAS_skewt': 'Hansen (1994) skew-t GAS, static λ',
            'M3_GAS_t_clip': f'Symmetric GAS-t with scaled score winsorized at ±{SCORE_CLIP_VAL}',
            'M4_GAS_t_betacap': f'Symmetric GAS-t with β ≤ {BETA_CAP}',
            'M5_regime_HAR_GAS': ('Regime switch on VIX IS tertile 1: '
                                  'HAR-RV in low-VIX, GAS-t otherwise'),
        },
        'evaluation': 'QLIKE on r² (GARCH/GAS native, Patton 2011)',
        'statistical_test': 'DM-HLN (Harvey-Leybourne-Newbold 1997) + BH FDR',
        'pass_threshold': 'DM t>+2 AND BH p<0.05',
        'seed': 42,
    },
    'per_asset_results': all_results,
    'scenario_analysis': {
        'skewt_PASS_both': skewt_pass,
        'skewt_no_harm_both': skewt_not_harm,
        'clip_PASS_both': clip_pass,
        'clip_no_harm_both': clip_not_harm,
        'betacap_PASS_both': betacap_pass,
        'betacap_no_harm_both': betacap_not_harm,
        'regime_PASS_both': regime_pass,
        'regime_no_harm_both': regime_not_harm,
        'scenario': scenario,
    },
    'paper4_implication': (
        'Paper 4 channel-specific narrative: whichever variant repairs (or '
        'fails to repair) the equity-harm signature tells a mechanism story. '
        f'Current scenario: {scenario}.'),
    'data_source': 'yfinance',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Creal, Koopman, Lucas (2013) JASA 108(501):1-18',
        'Hansen (1994) International Economic Review 35:705-730 (skew-t)',
        'Gonzalez-Rivera, Maldonado, Perez (2014) International Journal of Forecasting 30(3):529-550',
        'Harvey (2013) Cambridge UP — Dynamic Models for Volatility and Heavy Tails',
        'Patton (2011) J Econometrics 160:246-256',
        'Harvey-Leybourne-Newbold (1997) IJF 13:281-291',
        'Benjamini-Hochberg (1995) JRSS B 57:289-300',
    ],
}
with open(os.path.join(SCRIPT_DIR, 'k1143_results.json'), 'w') as f:
    json.dump(out, f, indent=2, default=str)
print(f'\nResults saved: k1143_results.json')
print(f'\nFINAL SCENARIO: {scenario}')
print('\nK1143 complete.')
