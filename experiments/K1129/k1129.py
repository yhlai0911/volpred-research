"""
K1129: GAS-t on Commodity Markets — Does Creal-Koopman-Lucas advantage reappear?
================================================================================
[提出: Claude, 執行: Claude]

Research Questions:
1. Does GAS-t outperform GJR-GARCH family on commodities (where K1038 showed NULL on equity/gold)?
2. Does the Student-t innovation alone (M2 = GJR-t) capture most of the gain?
3. High-volatility commodities (oil/gas) vs lower-vol (gold) — does gain scale with kurtosis?
4. Can a single-commodity GAS-t paper emerge?

Literature:
- Creal, Koopman, Lucas (2013) JASA 108(501):1-18 — GAS framework
- Harvey (2013) Dynamic Models for Volatility & Heavy Tails — Cambridge UP
- Hafner & Wang (2023) Energy Economics — GAS models for oil volatility
- Lucas & Zhang (2015) — GAS models for heavy-tailed asset returns
- Patton (2011) — QLIKE on r² for proxy-robust comparison
- Diebold-Mariano-Harvey-Leybourne-Newbold (1997) — DM-HLN small-sample correction

Prior:
- K437 (SPY, short OOS): GAS-t underperforms GARCH
- K1038 (SPY/QQQ/GLD/0050.TW, 7-year OOS): GAS-t NULL — all DM tests NS
  - GLD: QLIKE 1.508 (GJR) vs 1.510 (GAS-t), DM t=-0.26
- Gap: pure commodity markets (oil/gas/crypto) not yet tested

Hypotheses:
- H1 (primary): GAS-t beats GJR (M1) on at least 2/4 commodities at DM-HLN |t|>2
- H2: oil/gas (high kurt) gains more than gold (lower kurt)
- H3 (null): K1038 pattern repeats — GAS-t shows no edge
- H4: VaR violation rate GAS-t < GJR-Normal (Student-t innovations help tail)

Design:
- 4 assets: USO (oil ETF, ~2006+), GLD (gold ETF, ~2004+), UNG (natgas ETF, ~2007+), BTC-USD (crypto, ~2014+)
- 3 models: M1 GJR-GARCH Normal, M2 GJR-GARCH Student-t, M3 GAS-t
- OOS split: Train 2015-2020, Test 2021-2026 (with rolling WINDOW=1500 as BTC constraint)
- Refit every 63 days
- Three-gate publishable threshold (K1100g_d1 lesson):
    (a) DM-HLN |t| > 2 (two-sided p<0.05)
    (b) QLIKE relative improvement > 5%
    (c) Sub-period stability (sign consistency in 2 sub-periods)
- VaR/ES at 1% and 2.5% (Kupiec + CC + Basel + A-S ES)
- Seed: 42

Data source: yfinance
Reproduction: python experiments/K1129/k1129.py
"""

import sys
import os
import numpy as np
import pandas as pd
import json
import time
import warnings
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

print("=" * 72)
print("K1129: GAS-t on Commodity Markets (USO/GLD/UNG/BTC-USD)")
print("Creal, Koopman, Lucas (2013) JASA; replicates K1038 setup for commodities")
print("=" * 72)
sys.stdout.flush()

# ============================================================
# STEP 0: Data Download
# ============================================================
import yfinance as yf

# ETF inception dates (approximately):
# USO: 2006-04-10  | GLD: 2004-11-18  | UNG: 2007-04-18  | BTC-USD: 2014-09-17 (yfinance earliest)
ASSETS = {
    'USO': {'start': '2007-01-01', 'end': '2026-04-11'},
    'GLD': {'start': '2005-01-01', 'end': '2026-04-11'},
    'UNG': {'start': '2008-01-01', 'end': '2026-04-11'},
    'BTC-USD': {'start': '2015-01-01', 'end': '2026-04-11'},
}

OOS_START = '2021-01-01'
SUB_PERIOD_SPLIT = '2024-01-01'  # split OOS into two halves for stability gate
WINDOW = 1500  # enough for BTC; K1038 used 2000 but BTC has limited history
REFIT_EVERY = 63

asset_data = {}
for ticker, params in ASSETS.items():
    print(f"\n[0] Downloading {ticker}...")
    sys.stdout.flush()
    df = yf.download(ticker, start=params['start'], end=params['end'],
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    price_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
    prices = df[price_col].dropna()

    # BTC-USD trades weekends; keep as-is (daily returns include weekends)
    returns_pct = prices.pct_change().dropna() * 100  # percentage returns
    print(f"  Observations: {len(returns_pct)}")
    print(f"  Date range: {returns_pct.index[0].strftime('%Y-%m-%d')} ~ "
          f"{returns_pct.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Mean: {returns_pct.mean():.4f}%, Std: {returns_pct.std():.4f}%")
    print(f"  Skew: {returns_pct.skew():.3f}, Kurt (excess): {returns_pct.kurtosis():.3f}")

    asset_data[ticker] = returns_pct

sys.stdout.flush()


# ============================================================
# MODEL LIKELIHOODS AND FITTERS
# ============================================================

def gjr_normal_negloglik(params, returns):
    """GJR-GARCH(1,1) with Normal innovations."""
    omega, alpha, gamma, beta = params
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    nll = 0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns**2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def gjr_t_negloglik(params, returns):
    """GJR-GARCH(1,1) with Student-t innovations (standardized var=1)."""
    omega, alpha, gamma, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    # Student-t density with unit variance: scale sigma by sqrt((nu-2)/nu)
    # Using the "standardized t" parameterization as in Creal-Koopman-Lucas
    nll = 0.0
    for t in range(T):
        eps2 = returns[t]**2 / sigma2[t]
        ll_t = (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2) * sigma2[t])
                - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2)))
        nll -= ll_t
    return nll if np.isfinite(nll) else 1e10


def gas_t_negloglik(params, returns):
    """
    GAS-t(1,1), Creal-Koopman-Lucas (2013) Eq 5.
    f_t = log(sigma2_t); f_{t+1} = omega + alpha * s_t + beta * f_t
    s_t = I^{-1} * score (Fisher-scaled score).
    """
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


def fit_gjr_normal(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.03, 0.05, 0.90]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999)]
    try:
        res = minimize(gjr_normal_negloglik, x0, args=(returns,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 500})
        if not res.success:
            res = minimize(gjr_normal_negloglik, x0, args=(returns,), method='Nelder-Mead',
                          options={'maxiter': 2000})
    except Exception:
        return None, None
    omega, alpha, gamma, beta = res.x
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + gamma / 2 + beta}, sigma2


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
                    res2 = minimize(gjr_t_negloglik, x0_alt, args=(returns,), method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
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
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta, 'nu': nu,
            'persistence': alpha + gamma / 2 + beta}, sigma2


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
                    res2 = minimize(gas_t_negloglik, x0_alt, args=(returns,), method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
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
    return {'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu,
            'persistence': beta}, sigma2


def forecast_one_step(model_type, params, last_return, last_sigma2, last_f=None):
    if model_type == 'M1_GJR_N':
        ind = 1.0 if last_return < 0 else 0.0
        h = (params['omega'] + params['alpha'] * last_return**2
             + params['gamma'] * last_return**2 * ind + params['beta'] * last_sigma2)
    elif model_type == 'M2_GJR_t':
        ind = 1.0 if last_return < 0 else 0.0
        h = (params['omega'] + params['alpha'] * last_return**2
             + params['gamma'] * last_return**2 * ind + params['beta'] * last_sigma2)
    elif model_type == 'M3_GAS_t':
        nu = params['nu']
        eps2 = last_return**2 / last_sigma2
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        new_f = params['omega'] + params['alpha'] * scaled_score + params['beta'] * last_f
        h = np.exp(new_f)
    else:
        raise ValueError(f"Unknown: {model_type}")
    return max(h, 1e-10)


# ============================================================
# EVALUATION METRICS
# ============================================================

def qlike(actual_r2, predicted_sigma2):
    valid = ((predicted_sigma2 > 0) & np.isfinite(predicted_sigma2)
             & np.isfinite(actual_r2) & (actual_r2 > 0))
    a = actual_r2[valid]
    p = predicted_sigma2[valid]
    loss = a / p - np.log(a / p) - 1
    return np.mean(loss)


def dm_hln_test(loss1, loss2, h=1):
    """
    Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample correction.
    Returns (t_stat, p_value, n_used).
    """
    d = loss1 - loss2
    d = d[np.isfinite(d) & ~np.isnan(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0, n
    d_mean = np.mean(d)
    # HAC variance (Newey-West)
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
    # HLN small-sample correction
    hln_correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = hln_correction * dm_stat
    # t-distribution with n-1 df (HLN recommends)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value, n


def var_violations(returns, sigma2, alpha_level, dist='normal', nu=None):
    sigma = np.sqrt(sigma2)
    if dist == 'normal':
        z = stats.norm.ppf(alpha_level)
    elif dist == 't' and nu is not None and nu > 2:
        z = stats.t.ppf(alpha_level, df=nu) * np.sqrt((nu - 2) / nu)
    else:
        z = stats.norm.ppf(alpha_level)
    var_threshold = z * sigma
    return returns < var_threshold


def kupiec_test(violations, alpha_level, n):
    n_viol = int(np.sum(violations))
    if n_viol == 0 or n_viol == n:
        return 0.0, 1.0
    p_hat = n_viol / n
    lr = 2 * (n_viol * np.log(p_hat / alpha_level) +
              (n - n_viol) * np.log((1 - p_hat) / (1 - alpha_level)))
    return lr, 1 - stats.chi2.cdf(lr, 1)


def christoffersen_cc_test(violations):
    n = len(violations)
    v = violations.astype(int)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, n):
        if v[t-1] == 0 and v[t] == 0: n00 += 1
        elif v[t-1] == 0 and v[t] == 1: n01 += 1
        elif v[t-1] == 1 and v[t] == 0: n10 += 1
        else: n11 += 1
    if n01 + n11 == 0 or n00 + n10 == 0:
        return 0.0, 1.0
    p01 = n01 / (n00 + n01) if (n00 + n01) > 0 else 0
    p11 = n11 / (n10 + n11) if (n10 + n11) > 0 else 0
    p = (n01 + n11) / n
    if p <= 0 or p >= 1:
        return 0.0, 1.0
    try:
        ll_ind = 0.0
        if n00 > 0 and p01 > 0: ll_ind += n00 * np.log(1 - p01)
        if n01 > 0 and p01 > 0: ll_ind += n01 * np.log(p01)
        if n10 > 0 and p11 > 0: ll_ind += n10 * np.log(1 - p11)
        if n11 > 0 and p11 > 0: ll_ind += n11 * np.log(p11)
        ll_0 = (n00 + n10) * np.log(1 - p) + (n01 + n11) * np.log(p)
        lr = -2 * (ll_0 - ll_ind)
        return lr, 1 - stats.chi2.cdf(lr, 1)
    except Exception:
        return 0.0, 1.0


def acerbi_szekely_es_test(returns, sigma2, alpha_level, dist='normal', nu=None):
    sigma = np.sqrt(sigma2)
    n = len(returns)
    if dist == 'normal':
        z_var = stats.norm.ppf(alpha_level)
        es_scale = -stats.norm.pdf(z_var) / alpha_level
    elif dist == 't' and nu is not None and nu > 2:
        z_var = stats.t.ppf(alpha_level, df=nu) * np.sqrt((nu - 2) / nu)
        t_q = stats.t.ppf(alpha_level, df=nu)
        es_scale = -(stats.t.pdf(t_q, df=nu) / alpha_level
                     * (nu + t_q**2) / (nu - 1)) * np.sqrt((nu - 2) / nu)
    else:
        z_var = stats.norm.ppf(alpha_level)
        es_scale = -stats.norm.pdf(z_var) / alpha_level
    var_th = z_var * sigma
    es_th = es_scale * sigma
    violations = returns < var_th
    n_viol = int(np.sum(violations))
    if n_viol < 3:
        return 0.0, 1.0
    Z = np.sum(returns[violations] / es_th[violations]) / n_viol - 1
    se_approx = 1.0 / np.sqrt(n_viol)
    z_stat = Z / se_approx
    return z_stat, 2 * (1 - stats.norm.cdf(abs(z_stat)))


# ============================================================
# OOS FORECASTING LOOP
# ============================================================
all_results = {}
per_asset_qlike_individual = {}  # for cross-asset DM aggregation
model_keys = ['M1_GJR_N', 'M2_GJR_t', 'M3_GAS_t']

for ticker, returns_pct in asset_data.items():
    print(f"\n{'='*60}")
    print(f"  Processing: {ticker}")
    print(f"{'='*60}")
    sys.stdout.flush()

    returns = returns_pct.values
    dates = returns_pct.index

    oos_mask = dates >= OOS_START
    if not any(oos_mask):
        print(f"  SKIP: No OOS data")
        continue
    oos_start_idx = int(np.where(oos_mask)[0][0])
    if oos_start_idx < WINDOW:
        print(f"  SKIP: Not enough IS data ({oos_start_idx} < {WINDOW})")
        continue
    n_oos = len(returns) - oos_start_idx
    print(f"  OOS: {dates[oos_start_idx].strftime('%Y-%m-%d')} ~ "
          f"{dates[-1].strftime('%Y-%m-%d')} ({n_oos} obs)")

    forecasts = {m: np.full(n_oos, np.nan) for m in model_keys}
    current_params = {m: None for m in model_keys}
    current_sigma2 = {m: None for m in model_keys}
    current_f = {m: None for m in model_keys}

    t0 = time.time()
    last_fit = -REFIT_EVERY

    for t_oos in range(n_oos):
        t_abs = oos_start_idx + t_oos

        if t_oos - last_fit >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_data = returns[train_start:t_abs]
            if len(train_data) < 500:
                continue

            p_m1, s2_m1 = fit_gjr_normal(train_data)
            p_m2, s2_m2 = fit_gjr_t(train_data)
            p_m3, s2_m3 = fit_gas_t(train_data)

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

            last_fit = t_oos
            if t_oos % (REFIT_EVERY * 3) == 0:
                elapsed = time.time() - t0
                pct = t_oos / n_oos * 100
                print(f"  [{ticker}] {pct:.0f}% ({t_oos}/{n_oos}) {elapsed:.1f}s")
                sys.stdout.flush()

        last_r = returns[t_abs - 1]
        for m in model_keys:
            if current_params[m] is None:
                continue
            if m == 'M3_GAS_t':
                h = forecast_one_step(m, current_params[m], last_r,
                                      current_sigma2[m], last_f=current_f[m])
                forecasts[m][t_oos] = h
                current_sigma2[m] = h
                current_f[m] = np.log(max(h, 1e-10))
            else:
                h = forecast_one_step(m, current_params[m], last_r, current_sigma2[m])
                forecasts[m][t_oos] = h
                current_sigma2[m] = h

    elapsed = time.time() - t0
    print(f"  [{ticker}] done in {elapsed:.1f}s")
    sys.stdout.flush()

    # Evaluation ------------------------------------------------------
    actual_r2 = returns[oos_start_idx:]**2
    oos_returns = returns[oos_start_idx:]
    oos_dates = dates[oos_start_idx:]

    valid_mask = np.ones(n_oos, dtype=bool)
    for m in model_keys:
        valid_mask &= np.isfinite(forecasts[m])
    if np.sum(valid_mask) < 100:
        print(f"  SKIP: <100 valid forecasts")
        continue

    actual_r2_v = actual_r2[valid_mask]
    oos_returns_v = oos_returns[valid_mask]
    oos_dates_v = oos_dates[valid_mask]
    n_valid = len(actual_r2_v)
    print(f"  Valid OOS: {n_valid}")

    # Per-observation QLIKE for DM
    qlike_ind = {}
    for m in model_keys:
        fc = forecasts[m][valid_mask]
        ratio = actual_r2_v / fc
        with np.errstate(divide='ignore', invalid='ignore'):
            ql = ratio - np.log(np.where(ratio > 0, ratio, 1e-30)) - 1
        ql[actual_r2_v <= 0] = np.nan
        qlike_ind[m] = ql
    per_asset_qlike_individual[ticker] = qlike_ind

    # Aggregate metrics
    results_ticker = {}
    for m in model_keys:
        fc = forecasts[m][valid_mask]
        q = qlike(actual_r2_v, fc)
        rho, rho_p = stats.spearmanr(actual_r2_v, fc)
        results_ticker[m] = {
            'QLIKE': float(q),
            'Spearman_rho': float(rho),
            'Spearman_p': float(rho_p),
        }
        print(f"    {m}: QLIKE={q:.6f}, rho={rho:.3f}")

    # DM-HLN tests: primary comparisons vs M1 baseline
    dm_results = {}
    q_m1 = results_ticker['M1_GJR_N']['QLIKE']
    for m in ['M2_GJR_t', 'M3_GAS_t']:
        t_stat, p_val, n_used = dm_hln_test(qlike_ind['M1_GJR_N'], qlike_ind[m])
        q_m = results_ticker[m]['QLIKE']
        rel_impr = (q_m1 - q_m) / q_m1 * 100  # percent improvement
        dm_results[f'{m}_vs_M1'] = {
            'DM_HLN_t': float(t_stat),
            'DM_HLN_p': float(p_val),
            'n_used': int(n_used),
            'QLIKE_rel_improvement_pct': float(rel_impr),
            'gate_DM': bool(abs(t_stat) > 2.0),
            'gate_QLIKE_5pct': bool(rel_impr > 5.0),
            'significant_Harvey': bool(abs(t_stat) > 3.0),
            'better': m if t_stat > 0 else 'M1_GJR_N',
        }
        print(f"    DM-HLN {m} vs M1: t={t_stat:.3f}, p={p_val:.3e}, "
              f"rel_impr={rel_impr:+.2f}%")

    # DM M3 vs M2 (does GAS add over Student-t?)
    t_s, p_s, n_s = dm_hln_test(qlike_ind['M2_GJR_t'], qlike_ind['M3_GAS_t'])
    q_m2 = results_ticker['M2_GJR_t']['QLIKE']
    q_m3 = results_ticker['M3_GAS_t']['QLIKE']
    dm_results['M3_GAS_t_vs_M2_GJR_t'] = {
        'DM_HLN_t': float(t_s),
        'DM_HLN_p': float(p_s),
        'n_used': int(n_s),
        'QLIKE_rel_improvement_pct': float((q_m2 - q_m3) / q_m2 * 100),
        'gate_DM': bool(abs(t_s) > 2.0),
        'better': 'M3_GAS_t' if t_s > 0 else 'M2_GJR_t',
    }
    print(f"    DM-HLN M3 vs M2: t={t_s:.3f}, p={p_s:.3e}")

    # Sub-period stability: split OOS into two halves and check QLIKE sign consistency
    sub_idx = np.where(oos_dates_v >= SUB_PERIOD_SPLIT)[0]
    if len(sub_idx) > 50 and len(sub_idx) < n_valid - 50:
        split = int(sub_idx[0])
        sub_a = slice(0, split)
        sub_b = slice(split, n_valid)
        sub_qlike = {}
        for m in model_keys:
            fc = forecasts[m][valid_mask]
            sub_qlike[m] = {
                'early': float(qlike(actual_r2_v[sub_a], fc[sub_a])),
                'late': float(qlike(actual_r2_v[sub_b], fc[sub_b])),
                'n_early': int(split),
                'n_late': int(n_valid - split),
            }
        # sign consistency: does M3 beat M1 in both halves?
        for m in ['M2_GJR_t', 'M3_GAS_t']:
            beat_early = sub_qlike[m]['early'] < sub_qlike['M1_GJR_N']['early']
            beat_late = sub_qlike[m]['late'] < sub_qlike['M1_GJR_N']['late']
            dm_results[f'{m}_vs_M1']['gate_subperiod_stable'] = bool(beat_early and beat_late)
            dm_results[f'{m}_vs_M1']['sub_early_beats'] = bool(beat_early)
            dm_results[f'{m}_vs_M1']['sub_late_beats'] = bool(beat_late)
    else:
        sub_qlike = None

    # Triple gate aggregation
    for key in ['M2_GJR_t_vs_M1', 'M3_GAS_t_vs_M1']:
        gates = dm_results.get(key, {})
        gates['triple_gate_PASS'] = bool(
            gates.get('gate_DM', False)
            and gates.get('gate_QLIKE_5pct', False)
            and gates.get('gate_subperiod_stable', False)
        )

    # VaR/ES
    print(f"\n  --- VaR & ES Backtests ---")
    var_results = {}
    for alpha in [0.01, 0.025]:
        var_results[f'alpha_{alpha}'] = {}
        for m in model_keys:
            fc = forecasts[m][valid_mask]
            if m in ('M2_GJR_t', 'M3_GAS_t'):
                nu_val = (current_params[m]['nu']
                          if current_params[m] and 'nu' in current_params[m] else 8.0)
                dist = 't'
            else:
                nu_val = None
                dist = 'normal'
            viols = var_violations(oos_returns_v, fc, alpha, dist=dist, nu=nu_val)
            viol_rate = float(np.mean(viols))
            n_viols = int(np.sum(viols))
            kup_lr, kup_p = kupiec_test(viols, alpha, n_valid)
            cc_lr, cc_p = christoffersen_cc_test(viols)
            n_250 = min(n_valid, 250)
            viols_250 = int(np.sum(viols[-n_250:]))
            if alpha == 0.01:
                basel = 'Green' if viols_250 <= 4 else ('Yellow' if viols_250 <= 9 else 'Red')
            else:
                basel = 'Green' if viols_250 <= 10 else ('Yellow' if viols_250 <= 15 else 'Red')
            trinity = bool((kup_p > 0.05) and (cc_p > 0.05) and (basel == 'Green'))
            es_z, es_p = acerbi_szekely_es_test(oos_returns_v, fc, alpha,
                                                dist=dist, nu=nu_val)
            var_results[f'alpha_{alpha}'][m] = {
                'violation_rate': viol_rate,
                'n_violations': n_viols,
                'expected_violations': float(alpha * n_valid),
                'Kupiec_p': float(kup_p),
                'CC_p': float(cc_p),
                'Basel': basel,
                'Trinity_PASS': trinity,
                'ES_z': float(es_z),
                'ES_p': float(es_p),
                'ES_PASS': bool(es_p > 0.05),
                'distribution': dist,
                'nu': float(nu_val) if nu_val else None,
            }
            print(f"    {m} @ {alpha*100:.1f}%: viol={viol_rate*100:.2f}% "
                  f"(exp {alpha*100:.1f}%), Trinity={trinity}, ES_p={es_p:.3f}")

    all_results[ticker] = {
        'n_oos': int(n_valid),
        'oos_start': str(oos_dates_v[0].strftime('%Y-%m-%d')),
        'oos_end': str(oos_dates_v[-1].strftime('%Y-%m-%d')),
        'kurtosis_excess': float(returns_pct.kurtosis()),
        'skewness': float(returns_pct.skew()),
        'std_pct': float(returns_pct.std()),
        'model_metrics': results_ticker,
        'dm_tests': dm_results,
        'sub_period_qlike': sub_qlike,
        'var_es_backtests': var_results,
    }

    # Save forecasts for plotting (first asset only)
    if ticker == list(ASSETS.keys())[0]:
        first_forecasts = {m: forecasts[m][valid_mask] for m in model_keys}
        first_actual_r2 = actual_r2_v
        first_dates = oos_dates_v
        first_ticker_plot = ticker

sys.stdout.flush()

# ============================================================
# CROSS-ASSET SUMMARY
# ============================================================
print("\n" + "=" * 72)
print("CROSS-ASSET SUMMARY")
print("=" * 72)
print(f"\n{'Asset':<10} {'kurt':>8} {'M1 QL':>10} {'M2 QL':>10} {'M3 QL':>10} {'Best':>8}")
print("-" * 64)
for t in all_results:
    me = all_results[t]['model_metrics']
    kurt = all_results[t]['kurtosis_excess']
    best = min(model_keys, key=lambda m: me[m]['QLIKE'])
    print(f"{t:<10} {kurt:>8.2f} "
          f"{me['M1_GJR_N']['QLIKE']:>10.4f} "
          f"{me['M2_GJR_t']['QLIKE']:>10.4f} "
          f"{me['M3_GAS_t']['QLIKE']:>10.4f} {best:>8}")

print(f"\n{'Asset':<10} {'M2 vs M1':>22} {'M3 vs M1':>22} {'M3 vs M2':>20}")
print("-" * 80)
for t in all_results:
    dm = all_results[t]['dm_tests']
    m2v = dm.get('M2_GJR_t_vs_M1', {})
    m3v = dm.get('M3_GAS_t_vs_M1', {})
    m32 = dm.get('M3_GAS_t_vs_M2_GJR_t', {})
    def fmt(dd):
        if not dd: return 'n/a'
        marker = '***' if dd.get('significant_Harvey') else ('**' if dd.get('gate_DM') else ' ')
        gate = 'GATE' if dd.get('triple_gate_PASS') else ''
        return f"t={dd.get('DM_HLN_t',0):>5.2f}{marker}{gate:>5}"
    print(f"{t:<10} {fmt(m2v):>22} {fmt(m3v):>22} {fmt(m32):>20}")

# Triple gate summary
print("\n--- TRIPLE GATE (DM |t|>2 + QLIKE >5% + sub-period stable) ---")
h1_pass = 0
for t in all_results:
    dm = all_results[t]['dm_tests']
    m3_vs_m1 = dm.get('M3_GAS_t_vs_M1', {})
    if m3_vs_m1.get('triple_gate_PASS'):
        h1_pass += 1
        print(f"  {t}: M3 PASSES all 3 gates")
    else:
        print(f"  {t}: M3 FAILS "
              f"[DM={m3_vs_m1.get('gate_DM', False)}, "
              f"QL5={m3_vs_m1.get('gate_QLIKE_5pct', False)}, "
              f"sub={m3_vs_m1.get('gate_subperiod_stable', False)}]")
print(f"\nH1 (M3 beats M1 on >=2/4 commodities with triple gate): "
      f"{h1_pass}/{len(all_results)} — {'PASS' if h1_pass >= 2 else 'FAIL'}")

# H2 check: gain vs kurt
print("\n--- H2: QLIKE gain (M3 vs M1) correlated with kurtosis? ---")
kurts = []
gains = []
for t in all_results:
    kurts.append(all_results[t]['kurtosis_excess'])
    g = all_results[t]['dm_tests'].get('M3_GAS_t_vs_M1', {}).get('QLIKE_rel_improvement_pct', 0)
    gains.append(g)
    print(f"  {t}: kurt={kurts[-1]:.2f}, M3 gain over M1 = {g:+.2f}%")
if len(kurts) >= 3:
    try:
        rho_k, p_k = stats.spearmanr(kurts, gains)
        print(f"  Spearman(kurt, gain) = {rho_k:.3f} (p={p_k:.3f})")
    except Exception:
        pass

# H4: VaR violation (GAS-t<GJR-N at 1%)
print("\n--- H4: VaR violation rate M3 < M1 at 1%? ---")
h4_count = 0
for t in all_results:
    vr_m1 = all_results[t]['var_es_backtests']['alpha_0.01']['M1_GJR_N']['violation_rate']
    vr_m3 = all_results[t]['var_es_backtests']['alpha_0.01']['M3_GAS_t']['violation_rate']
    better = vr_m3 < vr_m1
    h4_count += int(better)
    print(f"  {t}: M1={vr_m1*100:.2f}%, M3={vr_m3*100:.2f}% — "
          f"M3 {'better' if better else 'worse/equal'}")
print(f"H4: {h4_count}/{len(all_results)} commodities show GAS-t has fewer VaR violations at 1%")

sys.stdout.flush()

# ============================================================
# CHARTS
# ============================================================
colors = {'M1_GJR_N': '#2196F3', 'M2_GJR_t': '#4CAF50', 'M3_GAS_t': '#E91E63'}

# Chart 1: QLIKE bar
fig, ax = plt.subplots(figsize=(10, 6))
x = np.arange(len(all_results))
width = 0.27
for i, m in enumerate(model_keys):
    qs = [all_results[t]['model_metrics'][m]['QLIKE'] for t in all_results]
    ax.bar(x + i * width, qs, width, label=m, color=colors[m], alpha=0.85)
ax.set_xlabel('Asset')
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('K1129: GAS-t vs GJR-Normal vs GJR-t on Commodity Markets\n(OOS 2021-2026, Patton 2011)')
ax.set_xticks(x + width)
ax.set_xticklabels(list(all_results.keys()))
ax.legend()
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1129_qlike_comparison.png')
plt.savefig(chart1_path, dpi=150)
plt.close()
print(f"\n  Chart 1: {chart1_path}")

# Chart 2: DM t-statistics heatmap-ish
fig, ax = plt.subplots(figsize=(10, 5))
comparisons = ['M2_GJR_t_vs_M1', 'M3_GAS_t_vs_M1', 'M3_GAS_t_vs_M2_GJR_t']
ts = np.zeros((len(all_results), len(comparisons)))
for i, t in enumerate(all_results):
    for j, c in enumerate(comparisons):
        ts[i, j] = all_results[t]['dm_tests'].get(c, {}).get('DM_HLN_t', 0.0)
im = ax.imshow(ts, cmap='RdYlGn', vmin=-3, vmax=3, aspect='auto')
ax.set_xticks(range(len(comparisons)))
ax.set_xticklabels(['M2 vs M1', 'M3 vs M1', 'M3 vs M2'])
ax.set_yticks(range(len(all_results)))
ax.set_yticklabels(list(all_results.keys()))
for i in range(len(all_results)):
    for j in range(len(comparisons)):
        ax.text(j, i, f"{ts[i,j]:.2f}", ha='center', va='center',
                color='black', fontsize=10)
plt.colorbar(im, ax=ax, label='DM-HLN t')
ax.set_title('K1129: DM-HLN t-statistics (positive = second model wins)')
plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'k1129_dm_heatmap.png')
plt.savefig(chart2_path, dpi=150)
plt.close()
print(f"  Chart 2: {chart2_path}")

# Chart 3: VaR violation rates
fig, ax = plt.subplots(figsize=(10, 6))
x = np.arange(len(all_results))
width = 0.27
for i, m in enumerate(model_keys):
    vr = [all_results[t]['var_es_backtests']['alpha_0.01'][m]['violation_rate'] * 100
          for t in all_results]
    ax.bar(x + i * width, vr, width, label=m, color=colors[m], alpha=0.85)
ax.axhline(1.0, color='black', linestyle='--', linewidth=1, label='Expected 1%')
ax.set_xlabel('Asset')
ax.set_ylabel('VaR 1% violation rate (%)')
ax.set_title('K1129: VaR Violation Rate at 1% — H4 (M3 Student-t should reduce tail violations)')
ax.set_xticks(x + width)
ax.set_xticklabels(list(all_results.keys()))
ax.legend()
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart3_path = os.path.join(SCRIPT_DIR, 'k1129_var_violations.png')
plt.savefig(chart3_path, dpi=150)
plt.close()
print(f"  Chart 3: {chart3_path}")

# ============================================================
# SAVE RESULTS
# ============================================================
results_output = {
    'experiment_id': 'K1129',
    'title': 'GAS-t on Commodity Markets — Does Creal-Koopman-Lucas advantage reappear?',
    'description': ('Test whether GAS-t (Creal et al 2013) outperforms GJR-GARCH '
                    'family on pure commodity markets (oil, gold, natgas, crypto). '
                    'Follow-up to K437 (SPY null) and K1038 (4-asset null incl. GLD).'),
    'methodology': {
        'models': ['M1 GJR-GARCH Normal', 'M2 GJR-GARCH Student-t', 'M3 GAS-t'],
        'assets': list(ASSETS.keys()),
        'oos_start': OOS_START,
        'sub_period_split': SUB_PERIOD_SPLIT,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'evaluation_target': 'r² (squared returns, GARCH-native proxy)',
        'metrics': ['QLIKE (Patton 2011)', 'DM-HLN test (Harvey-Leybourne-Newbold 1997)',
                    'Spearman rank correlation',
                    'VaR Kupiec/CC/Basel Trinity at 1% and 2.5%',
                    'Acerbi-Szekely (2014) ES backtest'],
        'triple_gate': {
            'gate_DM': 'DM-HLN |t| > 2',
            'gate_QLIKE_5pct': 'Relative QLIKE improvement > 5%',
            'gate_subperiod_stable': 'Sign consistency across 2 OOS sub-periods',
        },
        'dm_threshold_harvey': 'Harvey (2016) |t| > 3.0 (reported separately)',
    },
    'data_source': 'yfinance',
    'seed': 42,
    'references': [
        'Creal, Koopman, Lucas (2013) JASA 108(501):1-18',
        'Harvey (2013) Dynamic Models for Volatility & Heavy Tails, Cambridge UP',
        'Blasques, Koopman, Lucas (2015) Biometrika 102(2):325-343',
        'Patton (2011) Journal of Econometrics 160:246-256 — QLIKE proxy-robust',
        'Harvey-Leybourne-Newbold (1997) IJF 13:281-291 — DM small-sample correction',
        'Harvey (2016) — multiple-testing |t|>3.0 threshold',
        'Acerbi & Szekely (2014) Risk — ES backtest',
    ],
    'prior_experiments': {
        'K437': 'SPY only, 2023-2024 OOS: GAS-t underperforms GARCH family',
        'K1038': 'SPY/QQQ/GLD/0050.TW, 2019-2026 OOS: GAS-t NULL on all 4 assets',
    },
    'results': all_results,
    'charts': ['k1129_qlike_comparison.png', 'k1129_dm_heatmap.png',
               'k1129_var_violations.png'],
    'created_at': datetime.now(timezone.utc).isoformat(),
}

results_path = os.path.join(SCRIPT_DIR, 'k1129_results.json')
with open(results_path, 'w') as f:
    json.dump(results_output, f, indent=2, default=str)
print(f"\n  Results saved: {results_path}")
print("\nK1129 complete.")
