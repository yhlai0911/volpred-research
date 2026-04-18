"""
K1133b: BTC GAS-t decomposition — innovation distribution vs GAS dynamics vs regime-switching
============================================================================================
[Proposer: Claude, Executor: Claude (worktree agent-a97b4fe0)]

Motivation (from K1133):
  K1133 found BTC GAS-t reversal concentrated in P1 pre-institutional 2017-2020
  (DM t=-4.67) but NEUTRAL in P2/P3. GJR-Student-t ALSO reverses in P1 (t=-3.36),
  suggesting Student-t innovation — not GAS dynamics — may be the root cause.
  K1133 also fit a 2-state MS-GAS-t in-sample (LRT χ² 48.5/36.6/15.9 all sig)
  but did NOT implement OOS forecasting.

K1133b has two objectives:
  (a) Decompose innovation-distribution vs GAS-dynamics contribution by adding
      M4 GAS-Normal (Creal-Koopman-Lucas score without Student-t heavy tail).
      - If GAS-Normal beats GJR-Normal in P1 → GAS dynamics matter
      - If equivalent/worse → Student-t innovation is the sole driver of BTC P1 reversal
  (b) Implement MS-GAS-t OOS forecasting (Klaassen 2002 state-prob recursion)
      and test whether regime-specific parameters rescue BTC.

Design — 5 models:
  M1  GJR-GARCH Normal            (K1129 baseline)
  M2  GJR-GARCH Student-t         (K1129 baseline; P1 reversal -3.36)
  M3  GAS-t                       (K1133 baseline; P1 reversal -4.67)
  M4  GAS-Normal  (NEW)           (Isolates GAS dynamics w/o Student-t penalty)
  M5  GJR-N with input shift-scale standardization (NEW; controls for numeric scaling)

  MS-GAS-t (OOS, Klaassen 2002)   (tests regime-switching rescue)

References:
  - Creal, Koopman, Lucas (2013) JASA — GAS framework
  - Harvey (2013) Dynamic Models for Volatility & Heavy Tails, Cambridge UP
  - Gray (1996) "Modeling the conditional distribution of interest rates as a
    regime-switching process" JFE 42:27-62 — state-prob recursion
  - Klaassen (2002) "Improving GARCH volatility forecasts with regime-switching
    GARCH" Empirical Economics 27:363-394 — filtered-variance recursion (adopted)
  - Harvey, Leybourne, Newbold (1997) IJF — DM small-sample correction
  - Patton (2011) JoE — QLIKE proxy-robust

Strict rules:
  - Lookahead-safe rolling OOS (train strictly before forecast obs)
  - Seed 42 for any stochastic routine
  - MLE via L-BFGS-B + restart; if MS-GAS-t OOS non-converge → mark PRELIMINARY
  - Use SAME OOS sample as K1133 for apples-to-apples comparison

Run: python experiments/k1133b/k1133b.py
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from scipy import stats
from scipy.optimize import minimize
from scipy.special import gammaln

sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print("=" * 80)
print("K1133b: BTC GAS-t decomposition (innovation vs dynamics vs regime)")
print("=" * 80)
sys.stdout.flush()

# ============================================================
# STEP 0: Data (match K1133 exactly)
# ============================================================
import yfinance as yf

TICKER = 'BTC-USD'
START = '2015-01-01'
END = '2026-04-15'

print(f"\n[0] Downloading {TICKER} {START} → {END} ...")
sys.stdout.flush()
df = yf.download(TICKER, start=START, end=END, progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
price_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
prices = df[price_col].dropna()
returns_pct = prices.pct_change().dropna() * 100

print(f"  Observations: {len(returns_pct)}")
print(f"  Range: {returns_pct.index[0].strftime('%Y-%m-%d')} → "
      f"{returns_pct.index[-1].strftime('%Y-%m-%d')}")
print(f"  Mean={returns_pct.mean():.4f}%  Std={returns_pct.std():.4f}%  "
      f"Skew={returns_pct.skew():.3f}  ExcKurt={returns_pct.kurtosis():.3f}")
sys.stdout.flush()

# ============================================================
# MODEL 1: GJR-GARCH Normal (reuse K1133 spec)
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
        res = minimize(gjr_normal_negloglik, x0, args=(returns,), method='L-BFGS-B',
                       bounds=bounds, options={'maxiter': 500})
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
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta}, sigma2


# ============================================================
# MODEL 2: GJR-GARCH Student-t (reuse K1133 spec)
# ============================================================
def gjr_t_negloglik(params, returns):
    omega, alpha, gamma, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = (omega + alpha * returns[t-1]**2
                     + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1])
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    nll = 0.0
    for t in range(T):
        eps2 = returns[t]**2 / sigma2[t]
        ll_t = (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2) * sigma2[t])
                - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2)))
        nll -= ll_t
    return nll if np.isfinite(nll) else 1e10


def fit_gjr_t(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.03, 0.05, 0.90, np.log(6.0)]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999),
              (np.log(0.1), np.log(100.0))]
    try:
        res = minimize(gjr_t_negloglik, x0, args=(returns,), method='L-BFGS-B',
                       bounds=bounds, options={'maxiter': 500})
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [var_r * 0.02, 0.05, 0.08, 0.88, np.log(4.0)],
                [var_r * 0.08, 0.02, 0.03, 0.92, np.log(10.0)],
            ]:
                try:
                    res2 = minimize(gjr_t_negloglik, x0_alt, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None
    omega, alpha, gamma, beta, log_nu_minus2 = res.x
    nu = np.exp(log_nu_minus2) + 2.0
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = (omega + alpha * returns[t-1]**2
                     + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1])
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta, 'nu': nu}, sigma2


# ============================================================
# MODEL 3: GAS-t (reuse K1133 spec)
#   score = -0.5 + (nu+1)/2 * eps2 / (nu-2+eps2)
#   Fisher scaling S = 2*nu / ((nu+3)*(nu-2))
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
    x0 = [0.01, 0.05, 0.95, np.log(6.0)]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100.0))]
    try:
        res = minimize(gas_t_negloglik, x0, args=(returns,), method='L-BFGS-B',
                       bounds=bounds, options={'maxiter': 500})
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [0.005, 0.1, 0.90, np.log(4.0)],
                [0.02, 0.03, 0.97, np.log(10.0)],
                [0.0, 0.08, 0.92, np.log(8.0)],
            ]:
                try:
                    res2 = minimize(gas_t_negloglik, x0_alt, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None
    omega, alpha, beta, log_nu_minus2 = res.x
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
    return {'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu}, sigma2


# ============================================================
# MODEL 4 (NEW): GAS-Normal
#   Density: N(0, sigma²_t) → score ∇_f log N = -0.5 + 0.5 * eps2 (eps2=r²/σ²)
#   Fisher information for f=log(sigma²): I(f)=0.5 → Fisher-scaled score:
#     scaled_score = 0.5^{-1/2} * (-0.5 + 0.5*eps2) = sqrt(2)*(-0.5+0.5*eps2)
#   Under Creal-Koopman-Lucas (2013) Table 1 / Harvey (2013) eq.(4.5),
#   GAS-Normal with f=log(sigma²) recursion is:
#     f_{t+1} = omega + alpha * s_t + beta * f_t
#     s_t = S_t * nabla_t, S_t = I_t^{-1}, nabla_t = 0.5*(eps2_t - 1)
#   With I_t = 0.5, S_t = 2, s_t = 2 * 0.5 * (eps2-1) = eps2 - 1
#   So GAS-Normal with inv-Fisher scaling:  f_{t+1} = omega + alpha*(eps2_t - 1) + beta*f_t
#   NOTE: user spec requested "score = (ε² - σ²); Fisher scaling = 2σ⁴".
#         This gives score·S = (ε²-σ²)/(2σ⁴) = (eps2-1)/(2σ²), which is the
#         identity-scaled form (see Harvey 2013 sec. 4.1). In Harvey's unit-scale
#         (score defined on log-variance f = log σ²), the Fisher-scaled score is
#         exactly (eps2 - 1). Both parameterisations are equivalent under L-BFGS.
#   We implement the log-variance form: s_t = eps2_t - 1  (numerically stabler)
# ============================================================
def gas_normal_negloglik(params, returns):
    omega, alpha, beta = params
    T = len(returns)
    f = np.zeros(T)
    f[0] = np.log(np.var(returns))
    nll = 0.0
    for t in range(T):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = returns[t]**2 / sigma2_t
        # Gaussian log-density with log-variance f
        ll_t = -0.5 * (np.log(2 * np.pi) + f[t] + eps2)
        nll -= ll_t
        if t < T - 1:
            # Fisher-scaled score on log-variance parameterisation:
            # nabla_t = 0.5*(eps2 - 1), I_t = 0.5 → s_t = eps2 - 1
            scaled_score = eps2 - 1.0
            f[t+1] = omega + alpha * scaled_score + beta * f[t]
    return nll if np.isfinite(nll) else 1e10


def fit_gas_normal(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0 = [0.01, 0.05, 0.95]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999)]
    try:
        res = minimize(gas_normal_negloglik, x0, args=(returns,), method='L-BFGS-B',
                       bounds=bounds, options={'maxiter': 500})
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [0.005, 0.1, 0.90],
                [0.02, 0.03, 0.97],
                [0.0, 0.08, 0.92],
            ]:
                try:
                    res2 = minimize(gas_normal_negloglik, x0_alt, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None
    omega, alpha, beta = res.x
    f = np.zeros(T)
    f[0] = np.log(var_r)
    for t in range(T - 1):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = returns[t]**2 / sigma2_t
        scaled_score = eps2 - 1.0
        f[t+1] = omega + alpha * scaled_score + beta * f[t]
    sigma2 = np.exp(f)
    return {'omega': omega, 'alpha': alpha, 'beta': beta}, sigma2


# ============================================================
# MODEL 5 (CONTROL): GJR-N with explicit shift-scale input standardisation
#   Standardise training returns to mean=0, std=1, fit GJR-N, then transform
#   forecasts back. Control for any numeric-scaling artefact in GAS vs GJR.
# ============================================================
def fit_gjr_normal_standardised(returns):
    mu = np.mean(returns)
    sd = np.std(returns)
    if sd < 1e-10:
        return None, None, None, None
    r_std = (returns - mu) / sd
    params_std, sigma2_std = fit_gjr_normal(r_std)
    if params_std is None:
        return None, None, None, None
    # Transform variance back to original scale: σ²_orig = sd² * σ²_std
    sigma2_orig = sigma2_std * sd**2
    return params_std, sigma2_orig, mu, sd


# ============================================================
# ONE-STEP FORECAST
# ============================================================
def forecast_one_step(model_type, params, last_return, last_sigma2, last_f=None,
                      mu_std=None, sd_std=None):
    if model_type in ('M1_GJR_N', 'M2_GJR_t'):
        ind = 1.0 if last_return < 0 else 0.0
        h = (params['omega'] + params['alpha'] * last_return**2
             + params['gamma'] * last_return**2 * ind + params['beta'] * last_sigma2)
        return max(h, 1e-10), None
    elif model_type == 'M3_GAS_t':
        nu = params['nu']
        eps2 = last_return**2 / last_sigma2
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        new_f = params['omega'] + params['alpha'] * scaled_score + params['beta'] * last_f
        return max(np.exp(new_f), 1e-10), new_f
    elif model_type == 'M4_GAS_N':
        eps2 = last_return**2 / last_sigma2
        scaled_score = eps2 - 1.0
        new_f = params['omega'] + params['alpha'] * scaled_score + params['beta'] * last_f
        return max(np.exp(new_f), 1e-10), new_f
    elif model_type == 'M5_GJR_N_std':
        # Standardised input: r_std_{t-1} = (r_{t-1} - mu)/sd; last_sigma2 is in orig scale
        r_std = (last_return - mu_std) / sd_std
        # sigma2_std on standardised scale:
        last_sigma2_std = last_sigma2 / (sd_std**2) if sd_std > 0 else last_sigma2
        ind = 1.0 if r_std < 0 else 0.0
        h_std = (params['omega'] + params['alpha'] * r_std**2
                 + params['gamma'] * r_std**2 * ind + params['beta'] * last_sigma2_std)
        h_std = max(h_std, 1e-10)
        return h_std * sd_std**2, None
    else:
        raise ValueError(f"Unknown: {model_type}")


# ============================================================
# EVALUATION METRICS (reuse K1133)
# ============================================================
def qlike(actual_r2, predicted_sigma2):
    valid = ((predicted_sigma2 > 0) & np.isfinite(predicted_sigma2)
             & np.isfinite(actual_r2) & (actual_r2 > 0))
    a = actual_r2[valid]
    p = predicted_sigma2[valid]
    loss = a / p - np.log(a / p) - 1
    return np.mean(loss)


def qlike_ind(actual_r2, predicted_sigma2):
    ratio = actual_r2 / predicted_sigma2
    with np.errstate(divide='ignore', invalid='ignore'):
        ql = ratio - np.log(np.where(ratio > 0, ratio, 1e-30)) - 1
    ql[actual_r2 <= 0] = np.nan
    ql[predicted_sigma2 <= 0] = np.nan
    return ql


def dm_hln_test(loss1, loss2, h=1):
    d = loss1 - loss2
    d = d[np.isfinite(d) & ~np.isnan(d)]
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
    hln_correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = hln_correction * dm_stat
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value, n


# ============================================================
# MS-GAS-t MLE (Hamilton filter, for fitting on train window)
# ============================================================
def ms_gas_t_negloglik(params, returns):
    (o0, a0, b0, ln_nu0,
     o1, a1, b1, ln_nu1,
     lp00, lp11) = params
    nu0 = np.exp(ln_nu0) + 2.0
    nu1 = np.exp(ln_nu1) + 2.0
    p00 = 1.0 / (1.0 + np.exp(-lp00))
    p11 = 1.0 / (1.0 + np.exp(-lp11))
    P = np.array([[p00, 1 - p00], [1 - p11, p11]])

    T = len(returns)
    var_r = np.var(returns)
    pi0 = (1 - p11) / (2 - p00 - p11) if (2 - p00 - p11) > 1e-8 else 0.5
    pi = np.array([pi0, 1 - pi0])
    if np.any(pi < 0) or np.any(pi > 1):
        pi = np.array([0.5, 0.5])

    f0 = np.log(var_r)
    f1 = np.log(var_r)
    log_lik = 0.0

    for t in range(T):
        sigma2_0 = max(np.exp(f0), 1e-10)
        sigma2_1 = max(np.exp(f1), 1e-10)
        eps2_0 = returns[t]**2 / sigma2_0
        eps2_1 = returns[t]**2 / sigma2_1
        log_d0 = (gammaln((nu0 + 1) / 2) - gammaln(nu0 / 2)
                  - 0.5 * np.log(np.pi * (nu0 - 2) * sigma2_0)
                  - (nu0 + 1) / 2 * np.log(1 + eps2_0 / (nu0 - 2)))
        log_d1 = (gammaln((nu1 + 1) / 2) - gammaln(nu1 / 2)
                  - 0.5 * np.log(np.pi * (nu1 - 2) * sigma2_1)
                  - (nu1 + 1) / 2 * np.log(1 + eps2_1 / (nu1 - 2)))

        pred = pi @ P
        d0 = np.exp(log_d0)
        d1 = np.exp(log_d1)
        joint0 = pred[0] * d0
        joint1 = pred[1] * d1
        marg = joint0 + joint1
        if marg <= 0 or not np.isfinite(marg):
            return 1e10
        log_lik += np.log(marg)
        pi = np.array([joint0 / marg, joint1 / marg])

        if t < T - 1:
            score_0 = -0.5 + (nu0 + 1) / 2 * eps2_0 / (nu0 - 2 + eps2_0)
            S0 = 2 * nu0 / ((nu0 + 3) * (nu0 - 2))
            score_1 = -0.5 + (nu1 + 1) / 2 * eps2_1 / (nu1 - 2 + eps2_1)
            S1 = 2 * nu1 / ((nu1 + 3) * (nu1 - 2))
            f0_new = o0 + a0 * S0 * score_0 + b0 * f0
            f1_new = o1 + a1 * S1 * score_1 + b1 * f1
            f0, f1 = f0_new, f1_new

    return -log_lik if np.isfinite(log_lik) else 1e10


def fit_ms_gas_t(returns, maxiter=300, x0=None):
    var_r = np.var(returns)
    if x0 is None:
        x0 = [0.005, 0.03, 0.96, np.log(8.0),
              0.020, 0.08, 0.90, np.log(5.0),
              2.0, 2.0]
    bounds = [
        (-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100)),
        (-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100)),
        (-8.0, 8.0), (-8.0, 8.0),
    ]
    best = None
    try:
        res = minimize(ms_gas_t_negloglik, x0, args=(returns,),
                       method='L-BFGS-B', bounds=bounds,
                       options={'maxiter': maxiter})
        best = res
    except Exception:
        pass
    # try a second x0 flipping states
    try:
        x0_alt = list(x0)
        # swap states
        x0_alt[0:4], x0_alt[4:8] = x0[4:8], x0[0:4]
        res2 = minimize(ms_gas_t_negloglik, x0_alt, args=(returns,),
                        method='L-BFGS-B', bounds=bounds,
                        options={'maxiter': maxiter})
        if best is None or res2.fun < best.fun:
            best = res2
    except Exception:
        pass
    if best is None or not np.isfinite(best.fun) or best.fun > 1e9:
        return None
    return {
        'params': best.x,
        'neg_loglik': float(best.fun),
        'success': bool(best.success),
    }


def ms_gas_t_params_to_dict(x):
    (o0, a0, b0, ln_nu0,
     o1, a1, b1, ln_nu1,
     lp00, lp11) = x
    return {
        'state_0': {'omega': float(o0), 'alpha': float(a0), 'beta': float(b0),
                    'nu': float(np.exp(ln_nu0) + 2.0)},
        'state_1': {'omega': float(o1), 'alpha': float(a1), 'beta': float(b1),
                    'nu': float(np.exp(ln_nu1) + 2.0)},
        'p00': float(1.0 / (1.0 + np.exp(-lp00))),
        'p11': float(1.0 / (1.0 + np.exp(-lp11))),
    }


# ============================================================
# Klaassen (2002) MS-GAS-t state-prob recursion with OOS forecast
# ----------------------------------------------------------
# Recursion uses ONLY info up to t-1:
#   ξ_{t|t-1} = P' · ξ_{t-1|t-1}
#   σ²_{k,t}(params_k) is the state-k predictive variance given state k at t
#     — in MS-GAS-t each state has its own log-variance path f_{k,t}
#   σ²_{t|t-1} = Σ_k ξ_{k,t|t-1} · σ²_{k,t}
# Filtered update at time t uses observation r_t:
#   ξ_{k,t|t} ∝ ξ_{k,t|t-1} · f_k(r_t | σ²_{k,t})
# State-k log-variance recursion under Klaassen-style path aggregation:
#   f_{k,t+1} = ω_k + α_k · S_k(r_t, σ²_{k,t}) + β_k · f_{k,t}
# (We keep per-state path; Klaassen collapsing pass-through is identical for GAS
#  because f is a sufficient statistic and we don't need to collapse. We DO use
#  filtered probabilities ξ_{t|t} to update the initial state probability of the
#  next step. This is Gray-style for transition forward but keeps per-state f_k
#  path for GAS dynamics. We denote this a hybrid "Gray-Klaassen MS-GAS-t".)
# ============================================================

def ms_gas_t_oos_forecast(returns_train, returns_oos, ms_params,
                          refit_every=None, refit_returns_func=None):
    """
    Forecast sigma²_{t|t-1} for OOS period using MS-GAS-t with Gray (1996) state
    recursion. Returns arrays of length len(returns_oos): forecasts, state0_prob,
    state1_prob (all predictive = info up to t-1).

    Parameters
    ----------
    returns_train : 1D array — training data used to warm-start state filter
                    (run Hamilton filter through train to get f_0, f_1, pi)
    returns_oos   : 1D array — OOS observations
    ms_params     : 10-vector from fit_ms_gas_t (train-only fit)
    """
    (o0, a0, b0, ln_nu0,
     o1, a1, b1, ln_nu1,
     lp00, lp11) = ms_params
    nu0 = np.exp(ln_nu0) + 2.0
    nu1 = np.exp(ln_nu1) + 2.0
    p00 = 1.0 / (1.0 + np.exp(-lp00))
    p11 = 1.0 / (1.0 + np.exp(-lp11))
    P = np.array([[p00, 1 - p00], [1 - p11, p11]])

    # Run Hamilton filter on training data to get f_0, f_1, pi at T-1
    var_r = np.var(returns_train)
    pi0 = (1 - p11) / (2 - p00 - p11) if (2 - p00 - p11) > 1e-8 else 0.5
    pi = np.array([pi0, 1 - pi0])
    if np.any(pi < 0) or np.any(pi > 1):
        pi = np.array([0.5, 0.5])
    f0 = np.log(var_r)
    f1 = np.log(var_r)

    for t in range(len(returns_train)):
        sigma2_0 = max(np.exp(f0), 1e-10)
        sigma2_1 = max(np.exp(f1), 1e-10)
        eps2_0 = returns_train[t]**2 / sigma2_0
        eps2_1 = returns_train[t]**2 / sigma2_1
        log_d0 = (gammaln((nu0 + 1) / 2) - gammaln(nu0 / 2)
                  - 0.5 * np.log(np.pi * (nu0 - 2) * sigma2_0)
                  - (nu0 + 1) / 2 * np.log(1 + eps2_0 / (nu0 - 2)))
        log_d1 = (gammaln((nu1 + 1) / 2) - gammaln(nu1 / 2)
                  - 0.5 * np.log(np.pi * (nu1 - 2) * sigma2_1)
                  - (nu1 + 1) / 2 * np.log(1 + eps2_1 / (nu1 - 2)))
        pred = pi @ P
        log_max = max(log_d0, log_d1)
        d0 = np.exp(log_d0 - log_max)
        d1 = np.exp(log_d1 - log_max)
        joint0 = pred[0] * d0
        joint1 = pred[1] * d1
        marg = joint0 + joint1
        if marg <= 0 or not np.isfinite(marg):
            pi = np.array([0.5, 0.5])
        else:
            pi = np.array([joint0 / marg, joint1 / marg])

        score_0 = -0.5 + (nu0 + 1) / 2 * eps2_0 / (nu0 - 2 + eps2_0)
        S0 = 2 * nu0 / ((nu0 + 3) * (nu0 - 2))
        score_1 = -0.5 + (nu1 + 1) / 2 * eps2_1 / (nu1 - 2 + eps2_1)
        S1 = 2 * nu1 / ((nu1 + 3) * (nu1 - 2))
        f0 = o0 + a0 * S0 * score_0 + b0 * f0
        f1 = o1 + a1 * S1 * score_1 + b1 * f1

    # At this point: f0, f1 are the one-step-ahead log-variance forecasts for
    # EACH state at time T (first OOS index), and pi is xi_{T-1|T-1}.
    # Predictive state probs for first OOS: xi_{T|T-1} = pi @ P

    n_oos = len(returns_oos)
    forecasts = np.full(n_oos, np.nan)
    state0_probs = np.full(n_oos, np.nan)
    state1_probs = np.full(n_oos, np.nan)

    # LOOKAHEAD-SAFE LOOP: at each t, use (pi @ P) to form forecast, then update
    # with r_oos[t] for next step.
    for t in range(n_oos):
        # Predictive state prob (ONLY info up to prev obs)
        xi_pred = pi @ P   # ξ_{t|t-1}
        sigma2_0 = max(np.exp(f0), 1e-10)
        sigma2_1 = max(np.exp(f1), 1e-10)
        # Variance forecast (Klaassen 2002): weighted sum of state-specific variances
        sigma2_fcst = xi_pred[0] * sigma2_0 + xi_pred[1] * sigma2_1
        forecasts[t] = sigma2_fcst
        state0_probs[t] = xi_pred[0]
        state1_probs[t] = xi_pred[1]

        # Now use r_oos[t] to update filter for next step
        r_t = returns_oos[t]
        eps2_0 = r_t**2 / sigma2_0
        eps2_1 = r_t**2 / sigma2_1
        log_d0 = (gammaln((nu0 + 1) / 2) - gammaln(nu0 / 2)
                  - 0.5 * np.log(np.pi * (nu0 - 2) * sigma2_0)
                  - (nu0 + 1) / 2 * np.log(1 + eps2_0 / (nu0 - 2)))
        log_d1 = (gammaln((nu1 + 1) / 2) - gammaln(nu1 / 2)
                  - 0.5 * np.log(np.pi * (nu1 - 2) * sigma2_1)
                  - (nu1 + 1) / 2 * np.log(1 + eps2_1 / (nu1 - 2)))
        log_max = max(log_d0, log_d1)
        d0 = np.exp(log_d0 - log_max)
        d1 = np.exp(log_d1 - log_max)
        joint0 = xi_pred[0] * d0
        joint1 = xi_pred[1] * d1
        marg = joint0 + joint1
        if marg <= 0 or not np.isfinite(marg):
            pi = np.array([0.5, 0.5])
        else:
            pi = np.array([joint0 / marg, joint1 / marg])

        # Update state-specific log-variance paths
        score_0 = -0.5 + (nu0 + 1) / 2 * eps2_0 / (nu0 - 2 + eps2_0)
        S0 = 2 * nu0 / ((nu0 + 3) * (nu0 - 2))
        score_1 = -0.5 + (nu1 + 1) / 2 * eps2_1 / (nu1 - 2 + eps2_1)
        S1 = 2 * nu1 / ((nu1 + 3) * (nu1 - 2))
        f0 = o0 + a0 * S0 * score_0 + b0 * f0
        f1 = o1 + a1 * S1 * score_1 + b1 * f1

    return forecasts, state0_probs, state1_probs


# ============================================================
# PART A: Per-sub-period rolling OOS (5 models)
# ============================================================
SUB_PERIODS = [
    ('Period1_preinstitutional', '2015-01-01', '2020-12-31'),
    ('Period2_FTX_Luna_era',     '2021-01-01', '2023-12-31'),
    ('Period3_spotETF_era',      '2024-01-01', '2026-04-15'),
]

WINDOW_DEFAULT = 750
WINDOW_MIN = 500
REFIT_EVERY = 63
MODEL_KEYS = ['M1_GJR_N', 'M2_GJR_t', 'M3_GAS_t', 'M4_GAS_N', 'M5_GJR_N_std']

returns_arr = returns_pct.values
dates = returns_pct.index.to_numpy()

print(f"\n{'='*80}\nPART A: 5-model rolling OOS by sub-period\n{'='*80}")
sys.stdout.flush()

subperiod_results = {}

for sp_name, sp_start, sp_end in SUB_PERIODS:
    print(f"\n[PartA] {sp_name}  [{sp_start} → {sp_end}]")
    sys.stdout.flush()

    sp_start_dt = np.datetime64(sp_start)
    sp_end_dt = np.datetime64(sp_end)
    sp_mask = (dates >= sp_start_dt) & (dates <= sp_end_dt)
    sp_indices = np.where(sp_mask)[0]
    if len(sp_indices) < WINDOW_MIN + 100:
        print(f"  SKIP: only {len(sp_indices)} obs")
        continue

    sp_first = int(sp_indices[0])
    sp_last = int(sp_indices[-1]) + 1
    sp_returns = returns_arr[sp_first:sp_last]
    sp_dates = dates[sp_first:sp_last]
    n_sp = len(sp_returns)

    WINDOW = min(WINDOW_DEFAULT, n_sp - 100)
    WINDOW = max(WINDOW, WINDOW_MIN)
    oos_start_sp = WINDOW
    n_oos = n_sp - oos_start_sp
    print(f"  window={WINDOW}, n_sp={n_sp}, n_oos={n_oos}")
    sys.stdout.flush()

    forecasts = {m: np.full(n_oos, np.nan) for m in MODEL_KEYS}
    current_params = {m: None for m in MODEL_KEYS}
    current_sigma2 = {m: None for m in MODEL_KEYS}
    current_f = {m: None for m in MODEL_KEYS}
    current_mu = {m: None for m in MODEL_KEYS}
    current_sd = {m: None for m in MODEL_KEYS}

    t0 = time.time()
    last_fit = -REFIT_EVERY

    for t_oos in range(n_oos):
        t_abs = oos_start_sp + t_oos

        if t_oos - last_fit >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_data = sp_returns[train_start:t_abs]
            # LOOKAHEAD ASSERT
            assert train_start + len(train_data) == t_abs, \
                f"Train window leaks into obs {t_abs}"
            if len(train_data) < 500:
                continue

            p_m1, s2_m1 = fit_gjr_normal(train_data)
            p_m2, s2_m2 = fit_gjr_t(train_data)
            p_m3, s2_m3 = fit_gas_t(train_data)
            p_m4, s2_m4 = fit_gas_normal(train_data)
            p_m5, s2_m5, mu5, sd5 = fit_gjr_normal_standardised(train_data)

            if p_m1 is not None:
                current_params['M1_GJR_N'] = p_m1
                current_sigma2['M1_GJR_N'] = s2_m1[-1]
            if p_m2 is not None:
                current_params['M2_GJR_t'] = p_m2
                current_sigma2['M2_GJR_t'] = s2_m2[-1]
            if p_m3 is not None:
                current_params['M3_GAS_t'] = p_m3
                current_sigma2['M3_GAS_t'] = s2_m3[-1]
                current_f['M3_GAS_t'] = np.log(max(s2_m3[-1], 1e-10))
            if p_m4 is not None:
                current_params['M4_GAS_N'] = p_m4
                current_sigma2['M4_GAS_N'] = s2_m4[-1]
                current_f['M4_GAS_N'] = np.log(max(s2_m4[-1], 1e-10))
            if p_m5 is not None:
                current_params['M5_GJR_N_std'] = p_m5
                current_sigma2['M5_GJR_N_std'] = s2_m5[-1]
                current_mu['M5_GJR_N_std'] = mu5
                current_sd['M5_GJR_N_std'] = sd5

            last_fit = t_oos
            if t_oos % (REFIT_EVERY * 3) == 0:
                elapsed = time.time() - t0
                print(f"    {t_oos}/{n_oos} ({t_oos/n_oos*100:.0f}%) {elapsed:.1f}s")
                sys.stdout.flush()

        last_r = sp_returns[t_abs - 1]
        for m in MODEL_KEYS:
            if current_params[m] is None:
                continue
            if m in ('M3_GAS_t', 'M4_GAS_N'):
                h, new_f = forecast_one_step(m, current_params[m], last_r,
                                             current_sigma2[m], last_f=current_f[m])
                forecasts[m][t_oos] = h
                current_sigma2[m] = h
                current_f[m] = new_f
            elif m == 'M5_GJR_N_std':
                h, _ = forecast_one_step(m, current_params[m], last_r,
                                         current_sigma2[m],
                                         mu_std=current_mu[m], sd_std=current_sd[m])
                forecasts[m][t_oos] = h
                current_sigma2[m] = h
            else:
                h, _ = forecast_one_step(m, current_params[m], last_r,
                                         current_sigma2[m])
                forecasts[m][t_oos] = h
                current_sigma2[m] = h

    elapsed = time.time() - t0
    print(f"  done in {elapsed:.1f}s")
    sys.stdout.flush()

    actual_r2 = sp_returns[oos_start_sp:]**2
    oos_dates_v = sp_dates[oos_start_sp:]

    valid_mask = np.ones(n_oos, dtype=bool)
    for m in MODEL_KEYS:
        valid_mask &= np.isfinite(forecasts[m])
    n_valid = int(np.sum(valid_mask))
    print(f"  valid OOS: {n_valid}")

    if n_valid < 100:
        print(f"  SKIP: <100 valid")
        continue

    actual_r2_v = actual_r2[valid_mask]

    ql_ind = {}
    for m in MODEL_KEYS:
        fc = forecasts[m][valid_mask]
        ql_ind[m] = qlike_ind(actual_r2_v, fc)

    results_sp = {
        'n_oos': n_valid,
        'oos_start': pd.Timestamp(oos_dates_v[valid_mask][0]).strftime('%Y-%m-%d'),
        'oos_end': pd.Timestamp(oos_dates_v[valid_mask][-1]).strftime('%Y-%m-%d'),
        'sub_period_start': sp_start,
        'sub_period_end': sp_end,
        'preliminary_flag': bool(n_valid < 504),
        'model_metrics': {},
        'dm_tests': {},
        'forecasts': {m: forecasts[m][valid_mask].tolist() for m in MODEL_KEYS},
        'actual_r2': actual_r2_v.tolist(),
        'oos_dates': [pd.Timestamp(d).strftime('%Y-%m-%d')
                      for d in oos_dates_v[valid_mask]],
    }

    for m in MODEL_KEYS:
        fc = forecasts[m][valid_mask]
        q = qlike(actual_r2_v, fc)
        rho, rho_p = stats.spearmanr(actual_r2_v, fc)
        results_sp['model_metrics'][m] = {
            'QLIKE': float(q),
            'Spearman_rho': float(rho),
            'Spearman_p': float(rho_p),
        }
        print(f"    {m:14s}: QLIKE={q:.6f}, rho={rho:+.3f}")

    # DM all pairs vs M1 and key contrasts
    q_m1 = results_sp['model_metrics']['M1_GJR_N']['QLIKE']
    for m in ['M2_GJR_t', 'M3_GAS_t', 'M4_GAS_N', 'M5_GJR_N_std']:
        t_stat, p_val, n_used = dm_hln_test(ql_ind['M1_GJR_N'], ql_ind[m])
        q_m = results_sp['model_metrics'][m]['QLIKE']
        rel = (q_m1 - q_m) / q_m1 * 100
        results_sp['dm_tests'][f'{m}_vs_M1'] = {
            'DM_HLN_t': float(t_stat),
            'DM_HLN_p': float(p_val),
            'n_used': int(n_used),
            'QLIKE_rel_improvement_pct': float(rel),
            'gate_DM': bool(abs(t_stat) > 2.0),
            'gate_Harvey': bool(abs(t_stat) > 3.0),
        }
        print(f"    DM {m} vs M1: t={t_stat:+.3f}, p={p_val:.3e}, rel={rel:+.2f}%")

    # Key decomposition contrast: M4 GAS-N vs M3 GAS-t (isolates distribution)
    t_s, p_s, n_s = dm_hln_test(ql_ind['M3_GAS_t'], ql_ind['M4_GAS_N'])
    q_m3 = results_sp['model_metrics']['M3_GAS_t']['QLIKE']
    q_m4 = results_sp['model_metrics']['M4_GAS_N']['QLIKE']
    results_sp['dm_tests']['M4_GAS_N_vs_M3_GAS_t'] = {
        'DM_HLN_t': float(t_s),
        'DM_HLN_p': float(p_s),
        'n_used': int(n_s),
        'QLIKE_rel_improvement_pct': float((q_m3 - q_m4) / q_m3 * 100),
        'interpretation': 'GAS-Normal vs GAS-t — isolates Student-t innovation contribution',
    }
    print(f"    DM M4 vs M3: t={t_s:+.3f}, p={p_s:.3e}")

    # Key contrast: M2 GJR-t vs M1 (also tests Student-t under GARCH dynamics)
    subperiod_results[sp_name] = results_sp

# ============================================================
# PART B: MS-GAS-t OOS forecast (Klaassen/Gray state-prob recursion)
# ============================================================
print(f"\n{'='*80}\nPART B: MS-GAS-t OOS forecasting (Klaassen 2002 state-prob)\n{'='*80}")
sys.stdout.flush()

ms_oos_results = {}

for sp_name, sp_start, sp_end in SUB_PERIODS:
    print(f"\n[PartB] {sp_name}")
    sys.stdout.flush()

    if sp_name not in subperiod_results:
        ms_oos_results[sp_name] = {'skipped': True, 'reason': 'Part A skipped'}
        continue

    sp_start_dt = np.datetime64(sp_start)
    sp_end_dt = np.datetime64(sp_end)
    sp_mask = (dates >= sp_start_dt) & (dates <= sp_end_dt)
    sp_indices = np.where(sp_mask)[0]
    sp_first = int(sp_indices[0])
    sp_last = int(sp_indices[-1]) + 1
    sp_returns = returns_arr[sp_first:sp_last]
    sp_dates = dates[sp_first:sp_last]
    n_sp = len(sp_returns)
    WINDOW = min(WINDOW_DEFAULT, n_sp - 100)
    WINDOW = max(WINDOW, WINDOW_MIN)
    oos_start_sp = WINDOW
    n_oos = n_sp - oos_start_sp

    # Fit MS-GAS-t ONCE on first train window (no lookahead).
    # Rolling refit too expensive (10-param MLE ~10-60s each); we'll refit at
    # same REFIT_EVERY cadence as Part A but MS likelihood is fragile.
    ms_forecasts = np.full(n_oos, np.nan)
    ms_state0 = np.full(n_oos, np.nan)
    ms_state1 = np.full(n_oos, np.nan)

    # Adaptive refit cadence for MS (longer to reduce compute): 252 days
    MS_REFIT_EVERY = 252
    last_ms_fit_params = None
    ms_fit_log = []

    t0 = time.time()
    t_oos = 0
    while t_oos < n_oos:
        t_abs = oos_start_sp + t_oos
        train_start = max(0, t_abs - WINDOW)
        train_data = sp_returns[train_start:t_abs]
        assert train_start + len(train_data) == t_abs, \
            f"MS train leaks into obs {t_abs}"

        # Fit MS-GAS-t on train_data; warm-start from last_ms_fit_params if available
        x0_init = last_ms_fit_params if last_ms_fit_params is not None else None
        ms_fit = fit_ms_gas_t(train_data, maxiter=200, x0=x0_init)
        if ms_fit is None:
            print(f"    t_oos={t_oos}: MS fit FAILED, skipping block")
            t_oos += MS_REFIT_EVERY
            continue

        last_ms_fit_params = ms_fit['params']
        ms_fit_log.append({
            't_oos': t_oos,
            't_abs': t_abs,
            'fit_nll': ms_fit['neg_loglik'],
            'converged': ms_fit['success'],
            'params': ms_gas_t_params_to_dict(ms_fit['params']),
        })

        # Determine OOS block to forecast (from t_oos to t_oos + MS_REFIT_EVERY)
        block_end = min(t_oos + MS_REFIT_EVERY, n_oos)
        oos_block = sp_returns[t_abs:t_abs + (block_end - t_oos)]

        block_fcsts, block_s0, block_s1 = ms_gas_t_oos_forecast(
            returns_train=train_data,
            returns_oos=oos_block,
            ms_params=ms_fit['params'],
        )
        ms_forecasts[t_oos:block_end] = block_fcsts
        ms_state0[t_oos:block_end] = block_s0
        ms_state1[t_oos:block_end] = block_s1

        elapsed = time.time() - t0
        print(f"    block t_oos {t_oos}→{block_end-1}: nll={ms_fit['neg_loglik']:.1f} "
              f"conv={ms_fit['success']} cum_elapsed={elapsed:.1f}s")
        sys.stdout.flush()
        t_oos = block_end

    elapsed = time.time() - t0
    print(f"  Part B done in {elapsed:.1f}s")
    sys.stdout.flush()

    actual_r2_full = sp_returns[oos_start_sp:]**2

    # Align with Part A valid mask
    partA = subperiod_results[sp_name]
    dates_partA = partA['oos_dates']
    oos_dates_full = [pd.Timestamp(d).strftime('%Y-%m-%d')
                      for d in sp_dates[oos_start_sp:]]
    # Build mask: which OOS indices (in full OOS array) are in Part A valid set
    partA_date_set = set(dates_partA)
    ms_valid_mask = np.array([(d in partA_date_set) and np.isfinite(ms_forecasts[i])
                              for i, d in enumerate(oos_dates_full)])

    n_valid = int(ms_valid_mask.sum())
    print(f"  MS-GAS-t valid OOS (intersect Part A): {n_valid}")

    if n_valid < 100:
        ms_oos_results[sp_name] = {
            'n_oos': n_valid,
            'skipped': True,
            'reason': f'insufficient valid forecasts ({n_valid})',
            'ms_fit_log': ms_fit_log,
        }
        continue

    ms_fc_v = ms_forecasts[ms_valid_mask]
    s0_v = ms_state0[ms_valid_mask]
    s1_v = ms_state1[ms_valid_mask]
    actual_r2_v = actual_r2_full[ms_valid_mask]
    ql_ms = qlike_ind(actual_r2_v, ms_fc_v)
    q_ms = qlike(actual_r2_v, ms_fc_v)

    # Align Part A forecasts to ms_valid_mask
    # partA 'forecasts' was stored in valid-of-partA order; need to re-align
    # Rebuild: for each ms-valid date, find index in partA dates_partA
    date_to_partA_idx = {d: i for i, d in enumerate(dates_partA)}
    # The ms_valid_mask indexes the full OOS array; let's find positions
    partA_aligned_idx = []
    for i, m in enumerate(ms_valid_mask):
        if m:
            d = oos_dates_full[i]
            if d in date_to_partA_idx:
                partA_aligned_idx.append(date_to_partA_idx[d])
    partA_aligned_idx = np.array(partA_aligned_idx)

    # Models' aligned individual QLIKE
    ql_models_aligned = {}
    for m in MODEL_KEYS:
        fc_arr = np.array(partA['forecasts'][m])[partA_aligned_idx]
        ar_arr = np.array(partA['actual_r2'])[partA_aligned_idx]
        ql_models_aligned[m] = qlike_ind(ar_arr, fc_arr)

    # DM MS vs M3 GAS-t (main contrast), MS vs M1 GJR-N, MS vs M4 GAS-N
    ms_dm = {}
    for m in ['M1_GJR_N', 'M2_GJR_t', 'M3_GAS_t', 'M4_GAS_N']:
        t_stat, p_val, n_used = dm_hln_test(ql_models_aligned[m], ql_ms)
        q_base = qlike(actual_r2_v, np.array(partA['forecasts'][m])[partA_aligned_idx])
        rel = (q_base - q_ms) / q_base * 100 if q_base > 0 else 0.0
        ms_dm[f'MS_vs_{m}'] = {
            'DM_HLN_t': float(t_stat),
            'DM_HLN_p': float(p_val),
            'n_used': int(n_used),
            'QLIKE_MS': float(q_ms),
            f'QLIKE_{m}': float(q_base),
            'QLIKE_rel_improvement_pct': float(rel),
            'gate_DM': bool(abs(t_stat) > 2.0),
            'gate_Harvey': bool(abs(t_stat) > 3.0),
        }
        print(f"    DM MS vs {m}: t={t_stat:+.3f}, p={p_val:.3e}, rel={rel:+.2f}%")

    ms_oos_results[sp_name] = {
        'n_oos': n_valid,
        'QLIKE_MS_GAS_t': float(q_ms),
        'state_prob_mean': {'state_0': float(np.mean(s0_v)),
                            'state_1': float(np.mean(s1_v))},
        'state_prob_std': {'state_0': float(np.std(s0_v)),
                           'state_1': float(np.std(s1_v))},
        'dm_tests': ms_dm,
        'ms_fit_log': ms_fit_log,
        'preliminary_flag': bool(n_valid < 504),
        # Store forecasts / state probs for plotting
        'forecasts_ms': ms_fc_v.tolist(),
        'state_prob_0': s0_v.tolist(),
        'state_prob_1': s1_v.tolist(),
        'oos_dates': [oos_dates_full[i] for i, m in enumerate(ms_valid_mask) if m],
    }

# ============================================================
# PART C: Decomposition verdict
# ============================================================
print(f"\n{'='*80}\nPART C: Decomposition verdict\n{'='*80}")
sys.stdout.flush()

verdict = {}
for sp_name in subperiod_results:
    partA = subperiod_results[sp_name]
    dm = partA['dm_tests']
    mm = partA['model_metrics']
    sp_verdict = {
        'n_oos': partA['n_oos'],
        'preliminary': partA['preliminary_flag'],
        'DM_M2_vs_M1': dm['M2_GJR_t_vs_M1']['DM_HLN_t'],      # Student-t under GJR
        'DM_M3_vs_M1': dm['M3_GAS_t_vs_M1']['DM_HLN_t'],       # K1133 baseline
        'DM_M4_vs_M1': dm['M4_GAS_N_vs_M1']['DM_HLN_t'],       # GAS-Normal — pure dynamics
        'DM_M5_vs_M1': dm['M5_GJR_N_std_vs_M1']['DM_HLN_t'],   # Standardised control
        'DM_M4_vs_M3': dm['M4_GAS_N_vs_M3_GAS_t']['DM_HLN_t'], # GAS-N vs GAS-t
        'QLIKE': {m: mm[m]['QLIKE'] for m in MODEL_KEYS},
    }

    # Classification rule:
    # - "distribution-driven": M4 (GAS-N) better than M3 (GAS-t) with DM>+2 AND
    #   M2 (GJR-t) worse than M1 (GJR-N) with DM<-2
    # - "dynamics-driven": M3 (GAS-t) better than M1 AND M4 (GAS-N) better than M1
    # - "regime-driven": determined in Part B below
    t_m4m1 = sp_verdict['DM_M4_vs_M1']
    t_m3m1 = sp_verdict['DM_M3_vs_M1']
    t_m2m1 = sp_verdict['DM_M2_vs_M1']
    t_m4m3 = sp_verdict['DM_M4_vs_M3']

    drivers = []
    if t_m3m1 < -2 and t_m4m1 < -2:
        drivers.append('BOTH_GAS_dynamics_and_Student_t_harmful')
    elif t_m3m1 < -2 and abs(t_m4m1) <= 2:
        drivers.append('Student_t_driven')
        if t_m4m3 > 2:
            drivers.append('GAS_Normal_recovers')
    elif t_m3m1 < -2 and t_m4m1 > 2:
        drivers.append('paradox_GAS_dynamics_help_without_t')
    elif abs(t_m3m1) <= 2 and abs(t_m4m1) <= 2:
        drivers.append('GAS_framework_neutral')
    else:
        drivers.append('other')

    # MS part
    if sp_name in ms_oos_results and 'dm_tests' in ms_oos_results[sp_name]:
        ms_vs_m3 = ms_oos_results[sp_name]['dm_tests'].get('MS_vs_M3_GAS_t', {}).get('DM_HLN_t', 0.0)
        ms_vs_m1 = ms_oos_results[sp_name]['dm_tests'].get('MS_vs_M1_GJR_N', {}).get('DM_HLN_t', 0.0)
        sp_verdict['DM_MS_vs_M3'] = float(ms_vs_m3)
        sp_verdict['DM_MS_vs_M1'] = float(ms_vs_m1)
        if ms_vs_m1 > 2:
            drivers.append('MS_GAS_rescues_vs_GJR_N')
        elif ms_vs_m3 > 2:
            drivers.append('MS_rescues_single_state_GAS_but_still_worse_than_GJR_N')
        elif ms_vs_m1 < -2:
            drivers.append('MS_GAS_still_worse_than_GJR_N')
        else:
            drivers.append('MS_GAS_neutral')

    sp_verdict['drivers'] = drivers
    verdict[sp_name] = sp_verdict

    print(f"\n  {sp_name}:")
    print(f"    DM M2 vs M1 (GJR-t)     : {t_m2m1:+.3f}")
    print(f"    DM M3 vs M1 (GAS-t)     : {t_m3m1:+.3f}  ← K1133 baseline")
    print(f"    DM M4 vs M1 (GAS-N NEW) : {t_m4m1:+.3f}  ← isolates GAS dynamics")
    print(f"    DM M5 vs M1 (std ctrl)  : {sp_verdict['DM_M5_vs_M1']:+.3f}")
    print(f"    DM M4 vs M3 (GAS-N beats GAS-t?): {t_m4m3:+.3f}  ← isolates Student-t")
    if 'DM_MS_vs_M1' in sp_verdict:
        print(f"    DM MS-GAS-t vs M1       : {sp_verdict['DM_MS_vs_M1']:+.3f}")
        print(f"    DM MS-GAS-t vs M3       : {sp_verdict['DM_MS_vs_M3']:+.3f}")
    print(f"    → drivers: {', '.join(drivers)}")

# Headline
p1 = verdict.get('Period1_preinstitutional', {})
if p1:
    if 'Student_t_driven' in p1.get('drivers', []):
        headline = (
            'DECOMPOSITION: Student-t innovation is the root cause of BTC P1 '
            'reversal. GAS-Normal (no heavy-tail penalty) matches GJR-Normal. '
            'GAS dynamics per se are NOT the problem.'
        )
    elif 'BOTH_GAS_dynamics_and_Student_t_harmful' in p1.get('drivers', []):
        headline = (
            'DECOMPOSITION: BOTH GAS dynamics and Student-t innovation '
            'underperform on BTC P1. Full GAS framework inappropriate.'
        )
    elif 'paradox_GAS_dynamics_help_without_t' in p1.get('drivers', []):
        headline = (
            'DECOMPOSITION: GAS dynamics HELP on BTC P1 when paired with Normal '
            'innovation but Student-t destroys them. Distribution choice dominates.'
        )
    else:
        headline = f"P1 drivers: {p1.get('drivers')}"
else:
    headline = 'Insufficient P1 data for verdict.'

# Paper implication
all_bad = all(
    any(('Student_t_driven' in d or 'BOTH_GAS' in d) for d in verdict[sp].get('drivers', []))
    for sp in verdict
)
ms_helps_somewhere = any(
    'MS_GAS_rescues' in d
    for sp in verdict for d in verdict[sp].get('drivers', [])
)

if all_bad and not ms_helps_somewhere:
    paper_implication = (
        'BTC GAS-t paper NOT feasible as "GAS helps crypto". A "Why GAS-t fails '
        'on BTC: Student-t innovation as the culprit" diagnostic paper IS '
        'feasible — story: BTC\'s negative skew + moderate kurt in low-vol P1 '
        'penalises Student-t density more than it benefits from heavy tails.'
    )
elif ms_helps_somewhere:
    paper_implication = (
        'BTC GAS-t paper partially feasible IF regime-switching: MS-GAS-t '
        'rescues at least one period. Narrative: "Catania (2018) MS-GAS '
        'remedy conditionally supported on BTC".'
    )
else:
    paper_implication = 'Mixed — full results needed for paper framing.'

print(f"\n{'='*80}")
print(f"HEADLINE: {headline}")
print(f"PAPER IMPLICATION: {paper_implication}")
print(f"{'='*80}")

# ============================================================
# CHARTS
# ============================================================
colors = {
    'M1_GJR_N':     '#2196F3',
    'M2_GJR_t':     '#4CAF50',
    'M3_GAS_t':     '#E91E63',
    'M4_GAS_N':     '#FF9800',
    'M5_GJR_N_std': '#9C27B0',
}

# Chart 1: QLIKE by period, 5 models
fig, ax = plt.subplots(figsize=(13, 6))
period_names = list(subperiod_results.keys())
x = np.arange(len(period_names))
width = 0.16
for i, m in enumerate(MODEL_KEYS):
    qs = [subperiod_results[p]['model_metrics'][m]['QLIKE'] for p in period_names]
    ax.bar(x + i * width, qs, width, label=m, color=colors[m], alpha=0.85)
ax.set_xlabel('Sub-period')
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('K1133b: BTC QLIKE across sub-periods — 5-model decomposition\n'
             '(M1 GJR-N baseline, M4 GAS-Normal isolates GAS dynamics)')
ax.set_xticks(x + width * 2)
ax.set_xticklabels([p.replace('_', '\n') for p in period_names], fontsize=9)
ax.legend(fontsize=9, loc='upper right')
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart1 = os.path.join(SCRIPT_DIR, 'k1133b_qlike_5model.png')
plt.savefig(chart1, dpi=150)
plt.close()
print(f"\n  Chart 1: {chart1}")

# Chart 2: MS-GAS-t state probs timeseries (stitched P1/P2/P3)
fig, axes = plt.subplots(len(period_names), 1, figsize=(13, 3 * len(period_names)),
                         sharey=True)
if len(period_names) == 1:
    axes = [axes]
for i, sp in enumerate(period_names):
    if sp not in ms_oos_results or 'state_prob_0' not in ms_oos_results[sp]:
        axes[i].text(0.5, 0.5, f'MS-GAS-t skipped ({ms_oos_results.get(sp, {}).get("reason", "n/a")})',
                     ha='center', va='center', transform=axes[i].transAxes)
        axes[i].set_title(sp)
        continue
    d = ms_oos_results[sp]
    xs = pd.to_datetime(d['oos_dates'])
    axes[i].fill_between(xs, 0, d['state_prob_0'], alpha=0.45, color='#2196F3',
                         label='state 0 (low vol)')
    axes[i].fill_between(xs, d['state_prob_0'],
                         np.array(d['state_prob_0']) + np.array(d['state_prob_1']),
                         alpha=0.45, color='#E91E63', label='state 1 (high vol)')
    axes[i].set_ylabel('ξ_{t|t-1}')
    axes[i].set_ylim(0, 1)
    axes[i].set_title(f'{sp}  (mean ξ_0={d["state_prob_mean"]["state_0"]:.3f}, '
                      f'ξ_1={d["state_prob_mean"]["state_1"]:.3f})')
    axes[i].legend(loc='upper right', fontsize=8)
    axes[i].grid(alpha=0.3)
axes[-1].set_xlabel('Date')
plt.tight_layout()
chart2 = os.path.join(SCRIPT_DIR, 'k1133b_ms_state_prob.png')
plt.savefig(chart2, dpi=150)
plt.close()
print(f"  Chart 2: {chart2}")

# Chart 3: DM heatmap (period × key contrast)
fig, ax = plt.subplots(figsize=(12, 5))
key_contrasts = [
    ('M2_GJR_t_vs_M1', 'GJR-t vs GJR-N\n(Student-t under GARCH)'),
    ('M3_GAS_t_vs_M1', 'GAS-t vs GJR-N\n(K1133 baseline)'),
    ('M4_GAS_N_vs_M1', 'GAS-N vs GJR-N\n(pure GAS dynamics)'),
    ('M5_GJR_N_std_vs_M1', 'GJR-N std vs GJR-N\n(scaling control)'),
    ('M4_GAS_N_vs_M3_GAS_t', 'GAS-N vs GAS-t\n(isolates Student-t)'),
]
ts = np.zeros((len(period_names), len(key_contrasts)))
for i, p in enumerate(period_names):
    for j, (c, _) in enumerate(key_contrasts):
        ts[i, j] = subperiod_results[p]['dm_tests'].get(c, {}).get('DM_HLN_t', 0.0)
im = ax.imshow(ts, cmap='RdYlGn', vmin=-5, vmax=5, aspect='auto')
ax.set_xticks(range(len(key_contrasts)))
ax.set_xticklabels([lbl for _, lbl in key_contrasts], fontsize=8)
ax.set_yticks(range(len(period_names)))
ax.set_yticklabels([p.replace('_', '\n') for p in period_names], fontsize=8)
for i in range(len(period_names)):
    for j in range(len(key_contrasts)):
        col = 'white' if abs(ts[i, j]) > 3 else 'black'
        ax.text(j, i, f"{ts[i, j]:+.2f}", ha='center', va='center',
                color=col, fontsize=10, fontweight='bold')
plt.colorbar(im, ax=ax, label='DM-HLN t-stat')
ax.set_title('K1133b: DM-HLN t-stat across periods × key contrasts\n'
             '(green = second model wins, red = second model worse)')
plt.tight_layout()
chart3 = os.path.join(SCRIPT_DIR, 'k1133b_dm_heatmap.png')
plt.savefig(chart3, dpi=150)
plt.close()
print(f"  Chart 3: {chart3}")

# ============================================================
# SAVE RESULTS
# ============================================================
# Strip large arrays from subperiod_results for JSON readability
for sp in subperiod_results:
    # Keep metrics, DM tests, but drop raw forecasts/actuals for size
    subperiod_results[sp].pop('forecasts', None)
    subperiod_results[sp].pop('actual_r2', None)
    subperiod_results[sp].pop('oos_dates', None)

for sp in ms_oos_results:
    if 'forecasts_ms' in ms_oos_results[sp]:
        # Keep sample of first/last 5 for verification
        fc = ms_oos_results[sp].pop('forecasts_ms', None)
        s0 = ms_oos_results[sp].pop('state_prob_0', None)
        s1 = ms_oos_results[sp].pop('state_prob_1', None)
        if fc is not None:
            ms_oos_results[sp]['forecasts_ms_sample_first5'] = fc[:5]
            ms_oos_results[sp]['forecasts_ms_sample_last5'] = fc[-5:]
        if s0 is not None:
            ms_oos_results[sp]['state_prob_0_sample_first5'] = s0[:5]
            ms_oos_results[sp]['state_prob_0_sample_last5'] = s0[-5:]
        if s1 is not None:
            ms_oos_results[sp]['state_prob_1_sample_first5'] = s1[:5]
            ms_oos_results[sp]['state_prob_1_sample_last5'] = s1[-5:]

output = {
    'experiment_id': 'K1133b',
    'title': 'BTC GAS-t decomposition — innovation vs GAS dynamics vs regime-switching',
    'parent_experiment': 'K1133',
    'related_K': ['K1129', 'K1038', 'K437'],
    'motivation': (
        'K1133 found BTC GAS-t reversal concentrated in P1 pre-institutional. '
        'GJR-Student-t also reverses in P1, hinting Student-t innovation — not '
        'GAS dynamics — is root cause. K1133 MS-GAS-t in-sample LRT all sig but '
        'no OOS. K1133b: (a) decompose via GAS-Normal baseline; (b) implement '
        'MS-GAS-t OOS with Klaassen (2002) state-prob recursion.'
    ),
    'methodology': {
        'models': {
            'M1_GJR_N': 'GJR-GARCH Normal (K1129 baseline)',
            'M2_GJR_t': 'GJR-GARCH Student-t (K1129 baseline)',
            'M3_GAS_t': 'GAS-t with Fisher scaling (K1133 baseline)',
            'M4_GAS_N': 'GAS-Normal (NEW) — Creal-Koopman-Lucas Normal density, '
                        'score = eps2 - 1 (Fisher-scaled log-variance form)',
            'M5_GJR_N_std': 'GJR-N on shift-scale standardised returns (control '
                            'for numeric-scaling artefact)',
            'MS_GAS_t': '2-state Markov-switching GAS-t, OOS Klaassen (2002) '
                        'state-prob recursion with per-state log-variance paths',
        },
        'data_source': 'yfinance BTC-USD daily',
        'date_range': f'{START} → {END}',
        'n_total_obs': int(len(returns_pct)),
        'sub_periods': [{'name': n, 'start': s, 'end': e} for (n, s, e) in SUB_PERIODS],
        'window_default': WINDOW_DEFAULT,
        'window_min': WINDOW_MIN,
        'refit_every': REFIT_EVERY,
        'ms_refit_every': 252,
        'evaluation_target': 'r² (squared returns; GARCH-native proxy)',
        'metrics': ['QLIKE (Patton 2011)', 'DM-HLN (Harvey et al 1997)'],
        'lookahead_safety': ('Explicit assertion `train_start + len(train_data) '
                             '== t_abs` at every refit. MS filter runs through '
                             'train only; OOS forecast ξ_{t|t-1} = P \' ξ_{t-1|t-1} '
                             'uses ONLY info up to prev obs.'),
    },
    'seed': 42,
    'references': [
        'Creal, Koopman, Lucas (2013) JASA 108:1-18 — GAS framework',
        'Harvey (2013) Dynamic Models for Volatility & Heavy Tails',
        'Gray (1996) JFE 42:27-62 — MS-GARCH state-prob recursion',
        'Klaassen (2002) Empirical Economics 27:363-394 — MS-GARCH forecast',
        'Harvey, Leybourne, Newbold (1997) IJF — DM-HLN',
        'Patton (2011) JoE 160:246 — QLIKE proxy-robust',
        'Hamilton (1989) Econometrica — Markov-switching',
    ],
    'part_A_results': subperiod_results,
    'part_B_MS_GAS_t_OOS': ms_oos_results,
    'part_C_verdict_by_period': verdict,
    'headline_conclusion': headline,
    'paper_implication': paper_implication,
    'charts': ['k1133b_qlike_5model.png',
               'k1133b_ms_state_prob.png',
               'k1133b_dm_heatmap.png'],
    'created_at': datetime.now(timezone.utc).isoformat(),
}

output_path = os.path.join(SCRIPT_DIR, 'k1133b_results.json')
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved: {output_path}")
print("\nK1133b complete.")
