"""
K1138: Equity compendium (SPY/QQQ/IWM) robust vol models
================================================================================
[提出: Claude (user direction), 執行: Claude]

Motivation:
K1136 established that non-score-driven robust extensions (GARCH-MIDAS-X,
HAR-RV-X) fail to beat GJR-GARCH baseline on commodity daily vol prediction
(USO/GLD/UNG/BTC-USD, 0/4 PASS on both fair tests). Combined with K1129/K1134
GAS-t NULL on same commodities, Paper 4 argues "universal robust-method NULL".

K1138 extends this to equity ETFs (SPY/QQQ/IWM) to test asset-class
heterogeneity:

  - If equity NULL → Paper 4 "universal-null" spans 5 asset classes
    (equity + commodity + bond + currency + crypto partially already covered).
  - If equity PASSES → robust models are asset-class heterogeneous.
    Important new Paper 4 subsection.

Design (mirrors K1136 for cross-asset symmetry):
  - Assets: SPY (2000-2026), QQQ (2000-2026), IWM (2001-2026)
  - Models:
    * M1 GJR-GARCH Normal (baseline)
    * M3 GARCH-MIDAS-X (VIX² prior-month mean drives τ_t, GJR on devolatilized)
    * M4 HAR-RV-X (Corsi 2009 log-Parkinson + log(VIX²_{t-1}))
    * M5 HAR-RV (control: no VIX regressor)
    * M6 GAS-t (Creal-Koopman-Lucas 2013) — brief requires this 3rd robust model
  - Window=1500, Refit=63, OOS 2021-01-04 → 2026-04-10 (same as K1136)
  - Fair tests (Patton 2011):
    * Fair Test #1: M3 vs M1 on r² (close²-native comparison; MIDAS VIX driver)
    * Fair Test #2: M4 vs M5 on Parkinson (within-family VIX marginal)
    * Fair Test #3: M6 vs M1 on r² (close²-native; score-driven robust)
  - Seed: 42

Notes on 5-min RV:
  Brief says "if 5-min unavailable use range-based Parkinson/GK". Since TAIFEX
  5-min data doesn't apply to US ETFs, we use Parkinson variance (same as K1136
  for direct cross-asset comparison). SPY/QQQ/IWM intraday tick data is not
  locally available — Parkinson is the best feasible proxy.

Leakage safeguards (K1121/K1136 lessons):
  - VIX_{t-1} is safe (CBOE realtime; no publication delay)
  - MIDAS τ_t uses mean of VIX² over STRICTLY prior calendar month (no
    same-month contamination)
  - HAR regressors shifted by 1 explicitly in code

Hypotheses:
  H1 (primary): At least one robust model beats M1 on ≥2/3 equity assets
                under fair-test framework.
  H2 NULL: Equity joins commodity in universal-null → Paper 4 strengthened.
  H3 EQUITY PASSES: asset-class heterogeneity → new Paper 4 subsection.

Reproduction: python experiments/k1138/k1138.py
"""
import sys
import os
import time
import warnings
import json
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

print("=" * 72)
print("K1138: Equity compendium (SPY/QQQ/IWM) robust models")
print("Paper 4 universal-null asset-class extension")
print("=" * 72)
sys.stdout.flush()


# ============================================================
# STEP 0: DATA
# ============================================================
import yfinance as yf

# SPY/QQQ start 2000; IWM starts 2000-05 (inception); use 2001-01 for clean sample
ASSETS = {
    'SPY': {'start': '2000-01-01', 'end': '2026-04-11'},
    'QQQ': {'start': '2000-01-01', 'end': '2026-04-11'},
    'IWM': {'start': '2001-01-01', 'end': '2026-04-11'},
}

OOS_START = '2021-01-01'
SUB_PERIOD_SPLIT = '2024-01-01'
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
    print(f"\n[0] Downloading {ticker}...")
    sys.stdout.flush()
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
    # Parkinson variance in pct² (matches K1136)
    log_hl = np.log(ohlc['High'] / ohlc['Low'])
    park_pct2 = (log_hl ** 2 / (4 * np.log(2)) * 10000.0)

    vix_aligned = vix_close.reindex(returns_pct.index)
    vix_aligned = vix_aligned.ffill()
    first_ok = vix_aligned.first_valid_index()
    mask = returns_pct.index >= first_ok
    returns_pct = returns_pct[mask]
    ohlc = ohlc.loc[returns_pct.index]
    park_pct2 = park_pct2.loc[returns_pct.index]
    vix_aligned = vix_aligned.loc[returns_pct.index]

    print(f"  Observations: {len(returns_pct)}")
    print(f"  Date range: {returns_pct.index[0].strftime('%Y-%m-%d')} ~ "
          f"{returns_pct.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Mean r: {returns_pct.mean():.4f}%, Std r: {returns_pct.std():.4f}%")
    print(f"  Mean Park: {park_pct2.mean():.4f} (pct²)")
    print(f"  Mean VIX: {vix_aligned.mean():.2f}")

    asset_data[ticker] = {
        'returns_pct': returns_pct,
        'ohlc': ohlc,
        'parkinson': park_pct2,
        'vix': vix_aligned,
    }

sys.stdout.flush()


# ============================================================
# M1 GJR-GARCH Normal (BASELINE — same as K1136)
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
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + gamma/2 + beta}, sigma2


def gjr_n_forecast(params, last_r, last_sigma2):
    ind = 1.0 if last_r < 0 else 0.0
    h = (params['omega'] + params['alpha'] * last_r**2
         + params['gamma'] * last_r**2 * ind + params['beta'] * last_sigma2)
    return max(h, 1e-10)


# ============================================================
# M6 GAS-t (Creal-Koopman-Lucas 2013) — same spec as K1129
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
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999),
              (np.log(0.1), np.log(100.0))]
    try:
        res = minimize(gas_t_negloglik, x0, args=(returns,),
                       method='L-BFGS-B', bounds=bounds,
                       options={'maxiter': 500})
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
    return ({'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu,
             'persistence': beta}, sigma2, f)


def gas_t_forecast(params, last_r, last_sigma2, last_f):
    nu = params['nu']
    eps2 = last_r**2 / max(last_sigma2, 1e-10)
    score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
    S = 2 * nu / ((nu + 3) * (nu - 2))
    scaled_score = S * score
    new_f = params['omega'] + params['alpha'] * scaled_score + params['beta'] * last_f
    h = np.exp(new_f)
    return max(h, 1e-10), new_f


# ============================================================
# M3 GARCH-MIDAS-X (same as K1136)
# ============================================================
def build_vix_monthly_lag1(daily_vix):
    """For each daily date d, return mean(VIX²) over calendar month strictly
    before d's month. Leakage-safe (same as K1136)."""
    vix2 = daily_vix ** 2
    monthly = vix2.resample('ME').mean()
    daily_out = pd.Series(index=daily_vix.index, dtype=float)
    for d in daily_vix.index:
        first_of_month = d.replace(day=1)
        eligible = monthly.index[monthly.index < first_of_month]
        if len(eligible) == 0:
            daily_out.loc[d] = np.nan
        else:
            daily_out.loc[d] = monthly.loc[eligible[-1]]
    return daily_out


def garch_midas_x_negloglik(params, returns, vix2_monthly):
    m_, theta, alpha, gamma_, beta = params
    T = len(returns)
    tau = np.exp(m_ + theta * vix2_monthly)
    tau = np.clip(tau, 1e-8, 1e8)
    eps = returns / np.sqrt(tau)
    g = np.zeros(T)
    g[0] = max(1.0, np.var(eps))
    nll = 0.0
    for t in range(T):
        sigma2_t = tau[t] * g[t]
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        nll += 0.5 * (np.log(2 * np.pi * sigma2_t) + returns[t]**2 / sigma2_t)
        if t < T - 1:
            ind = 1.0 if returns[t] < 0 else 0.0
            omega_g = max(1 - alpha - gamma_/2 - beta, 1e-6)
            g[t+1] = (omega_g + alpha * eps[t]**2
                      + gamma_ * eps[t]**2 * ind + beta * g[t])
            if g[t+1] < 1e-8:
                g[t+1] = 1e-8
    return nll if np.isfinite(nll) else 1e10


def fit_garch_midas_x(returns, vix2_monthly):
    T = len(returns)
    var_r = np.var(returns)
    log_var = np.log(var_r)
    x0_list = [
        [log_var, 0.001, 0.03, 0.05, 0.88],
        [log_var, 0.005, 0.05, 0.05, 0.85],
        [log_var - 1.0, 0.0, 0.03, 0.05, 0.88],
    ]
    bounds = [
        (log_var - 5, log_var + 5),
        (-1.0, 1.0),
        (1e-8, 0.3),
        (-0.1, 0.3),
        (0.3, 0.97),
    ]
    best = None
    for x0 in x0_list:
        try:
            res = minimize(garch_midas_x_negloglik, x0,
                           args=(returns, vix2_monthly), method='L-BFGS-B',
                           bounds=bounds, options={'maxiter': 300})
            if best is None or (res.fun < best.fun):
                best = res
        except Exception:
            continue
    if best is None or not np.isfinite(best.fun):
        return None, None, None
    m_, theta, alpha, gamma_, beta = best.x
    tau = np.exp(m_ + theta * vix2_monthly)
    tau = np.clip(tau, 1e-8, 1e8)
    eps = returns / np.sqrt(tau)
    g = np.zeros(T)
    g[0] = max(1.0, np.var(eps))
    for t in range(T - 1):
        ind = 1.0 if returns[t] < 0 else 0.0
        omega_g = max(1 - alpha - gamma_/2 - beta, 1e-6)
        g[t+1] = (omega_g + alpha * eps[t]**2
                  + gamma_ * eps[t]**2 * ind + beta * g[t])
        if g[t+1] < 1e-8:
            g[t+1] = 1e-8
    params = {'m': m_, 'theta': theta, 'alpha': alpha, 'gamma': gamma_,
              'beta': beta}
    return params, tau, g


def midas_x_forecast(params, last_r, last_eps, last_g, next_vix2_monthly):
    m_ = params['m']; theta = params['theta']
    alpha = params['alpha']; gamma_ = params['gamma']; beta = params['beta']
    tau_new = np.exp(m_ + theta * next_vix2_monthly)
    tau_new = float(np.clip(tau_new, 1e-8, 1e8))
    ind = 1.0 if last_r < 0 else 0.0
    omega_g = max(1 - alpha - gamma_/2 - beta, 1e-6)
    g_new = omega_g + alpha * last_eps**2 + gamma_ * last_eps**2 * ind + beta * last_g
    g_new = max(g_new, 1e-8)
    return max(tau_new * g_new, 1e-10), g_new, tau_new


# ============================================================
# M4 HAR-RV-X, M5 HAR-RV (same as K1136)
# ============================================================
def fit_har_rv_x(rv_series, vix_series, include_vix=True):
    log_rv = np.log(rv_series.clip(lower=1e-10))
    daily = log_rv.shift(1)
    weekly = log_rv.shift(1).rolling(window=5).mean()
    monthly = log_rv.shift(1).rolling(window=22).mean()
    cols = {'const': 1.0, 'daily': daily, 'weekly': weekly, 'monthly': monthly}
    if include_vix:
        log_vix2 = np.log((vix_series ** 2).clip(lower=1e-10))
        cols['vix_lag'] = log_vix2.shift(1)
    X = pd.DataFrame(cols).dropna()
    y = log_rv.loc[X.index]
    X_mat = X.values
    try:
        beta_hat, *_ = np.linalg.lstsq(X_mat, y.values, rcond=None)
    except Exception:
        return None
    resid = y.values - X_mat @ beta_hat
    sigma_resid = np.std(resid, ddof=X_mat.shape[1])
    return {
        'beta': beta_hat.tolist(),
        'col_order': list(X.columns),
        'sigma_resid': float(sigma_resid),
        'include_vix': include_vix,
    }


def har_rv_x_forecast(params, rv_history, vix_history_level):
    beta = np.array(params['beta'])
    log_rv = np.log(rv_history.clip(lower=1e-10))
    if len(log_rv) < 22:
        return None
    daily = log_rv.iloc[-1]
    weekly = log_rv.iloc[-5:].mean()
    monthly = log_rv.iloc[-22:].mean()
    x_vec = [1.0, daily, weekly, monthly]
    if params.get('include_vix', True):
        vix2 = vix_history_level.iloc[-1] ** 2
        x_vec.append(np.log(max(vix2, 1e-10)))
    x = np.array(x_vec)
    log_rv_hat = float(x @ beta)
    sigma_resid = params['sigma_resid']
    rv_hat = np.exp(log_rv_hat + 0.5 * sigma_resid**2)
    return max(rv_hat, 1e-10)


# ============================================================
# EVALUATION — QLIKE + DM-HLN (same as K1136)
# ============================================================
def qlike_pointwise(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    out = np.full_like(actual, np.nan, dtype=float)
    valid = (predicted > 0) & np.isfinite(predicted) & (actual > 0) & np.isfinite(actual)
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
    """Return BH-adjusted p-values (FDR control). pvals is a list/array."""
    pvals = np.asarray(pvals, dtype=float)
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    adj = ranked * n / (np.arange(n) + 1)
    # ensure monotone: work from highest rank downward
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.clip(adj, 0, 1)
    out = np.zeros(n)
    out[order] = adj
    return out.tolist()


# ============================================================
# OOS FORECASTING LOOP
# ============================================================
all_results = {}
model_keys = ['M1_GJR_N', 'M3_GARCH_MIDAS_X', 'M4_HAR_RV_X', 'M5_HAR_RV',
              'M6_GAS_t']
targets = ['parkinson', 'r2_close']

for ticker, d in asset_data.items():
    print(f"\n{'='*60}")
    print(f"  Processing: {ticker}")
    print(f"{'='*60}")
    sys.stdout.flush()

    returns_pct = d['returns_pct']
    returns = returns_pct.values
    dates = returns_pct.index
    park = d['parkinson']
    vix = d['vix']

    vix_m_lag1 = build_vix_monthly_lag1(vix)
    valid_vix_m = vix_m_lag1.first_valid_index()
    mask = dates >= valid_vix_m
    returns_pct = returns_pct[mask]
    returns = returns_pct.values
    dates = returns_pct.index
    park = park.loc[dates]
    vix = vix.loc[dates]
    vix_m_lag1 = vix_m_lag1.loc[dates].values

    oos_mask = dates >= OOS_START
    oos_start_idx = int(np.where(oos_mask)[0][0])
    n_oos = len(returns) - oos_start_idx
    print(f"  OOS: {dates[oos_start_idx].strftime('%Y-%m-%d')} ~ "
          f"{dates[-1].strftime('%Y-%m-%d')} ({n_oos} obs)")

    forecasts = {m: np.full(n_oos, np.nan) for m in model_keys}
    params_cur = {m: None for m in model_keys}
    state_m1_sigma2 = None
    state_m3_g = None
    state_m3_eps = None
    state_m6_sigma2 = None
    state_m6_f = None
    last_fit = -REFIT_EVERY
    t0 = time.time()

    for t_oos in range(n_oos):
        t_abs = oos_start_idx + t_oos

        if (t_oos - last_fit) >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_returns = returns[train_start:t_abs]
            train_vix_m = vix_m_lag1[train_start:t_abs]
            train_park = park.iloc[train_start:t_abs]
            train_vix = vix.iloc[train_start:t_abs]
            if len(train_returns) < 500:
                continue

            # M1 GJR-N
            p_m1, s2_m1 = fit_gjr_normal(train_returns)
            if p_m1 is not None:
                params_cur['M1_GJR_N'] = p_m1
                state_m1_sigma2 = float(s2_m1[-1])

            # M3 GARCH-MIDAS-X
            p_m3, tau_m3, g_m3 = fit_garch_midas_x(train_returns, train_vix_m)
            if p_m3 is not None:
                params_cur['M3_GARCH_MIDAS_X'] = p_m3
                state_m3_g = float(g_m3[-1])
                state_m3_eps = float(train_returns[-1] / np.sqrt(max(tau_m3[-1], 1e-10)))

            # M4 HAR-RV-X
            p_m4 = fit_har_rv_x(train_park, train_vix, include_vix=True)
            if p_m4 is not None:
                params_cur['M4_HAR_RV_X'] = p_m4

            # M5 HAR-RV (no VIX)
            p_m5 = fit_har_rv_x(train_park, train_vix, include_vix=False)
            if p_m5 is not None:
                params_cur['M5_HAR_RV'] = p_m5

            # M6 GAS-t
            out_m6 = fit_gas_t(train_returns)
            if out_m6 is not None and out_m6[0] is not None:
                p_m6, s2_m6, f_m6 = out_m6
                params_cur['M6_GAS_t'] = p_m6
                state_m6_sigma2 = float(s2_m6[-1])
                state_m6_f = float(f_m6[-1])

            last_fit = t_oos
            if t_oos % (REFIT_EVERY * 4) == 0:
                elapsed = time.time() - t0
                pct = t_oos / n_oos * 100
                print(f"  [{ticker}] {pct:.0f}% ({t_oos}/{n_oos}) {elapsed:.1f}s")
                sys.stdout.flush()

        last_r = returns[t_abs - 1]
        # M1 recurrence
        if params_cur['M1_GJR_N'] is not None and state_m1_sigma2 is not None:
            h = gjr_n_forecast(params_cur['M1_GJR_N'], last_r, state_m1_sigma2)
            forecasts['M1_GJR_N'][t_oos] = h
            state_m1_sigma2 = h

        # M3 MIDAS-X
        if (params_cur['M3_GARCH_MIDAS_X'] is not None
                and state_m3_g is not None and state_m3_eps is not None):
            next_vix_m = vix_m_lag1[t_abs]
            if np.isfinite(next_vix_m):
                h3, g_new, tau_new = midas_x_forecast(
                    params_cur['M3_GARCH_MIDAS_X'],
                    last_r, state_m3_eps, state_m3_g, next_vix_m)
                forecasts['M3_GARCH_MIDAS_X'][t_oos] = h3
                state_m3_g = g_new
                state_m3_eps = returns[t_abs] / np.sqrt(max(tau_new, 1e-10))

        # M4 HAR-RV-X
        if params_cur['M4_HAR_RV_X'] is not None:
            rv_hist = park.iloc[:t_abs]
            vix_hist = vix.iloc[:t_abs]
            h4 = har_rv_x_forecast(params_cur['M4_HAR_RV_X'], rv_hist, vix_hist)
            if h4 is not None:
                forecasts['M4_HAR_RV_X'][t_oos] = h4

        # M5 HAR-RV
        if params_cur['M5_HAR_RV'] is not None:
            rv_hist = park.iloc[:t_abs]
            vix_hist = vix.iloc[:t_abs]
            h5 = har_rv_x_forecast(params_cur['M5_HAR_RV'], rv_hist, vix_hist)
            if h5 is not None:
                forecasts['M5_HAR_RV'][t_oos] = h5

        # M6 GAS-t (recurrence: f_t = f(r_{t-1}, f_{t-1}))
        if (params_cur['M6_GAS_t'] is not None
                and state_m6_sigma2 is not None and state_m6_f is not None):
            h6, new_f = gas_t_forecast(params_cur['M6_GAS_t'],
                                       last_r, state_m6_sigma2, state_m6_f)
            forecasts['M6_GAS_t'][t_oos] = h6
            state_m6_sigma2 = h6
            state_m6_f = new_f

    elapsed = time.time() - t0
    print(f"  [{ticker}] done in {elapsed:.1f}s")
    sys.stdout.flush()

    oos_dates = dates[oos_start_idx:]
    valid_mask = np.ones(n_oos, dtype=bool)
    for m in model_keys:
        valid_mask &= np.isfinite(forecasts[m])
    if np.sum(valid_mask) < 100:
        print(f"  SKIP: <100 valid forecasts across all models")
        continue
    oos_dates_v = oos_dates[valid_mask]
    n_valid = len(oos_dates_v)
    print(f"  Valid OOS: {n_valid}")

    oos_targets = {
        'r2_close': (returns[oos_start_idx:] ** 2)[valid_mask],
        'parkinson': park.reindex(oos_dates).values[valid_mask],
    }

    ticker_results = {
        'n_oos': int(n_valid),
        'oos_start': str(oos_dates_v[0].strftime('%Y-%m-%d')),
        'oos_end': str(oos_dates_v[-1].strftime('%Y-%m-%d')),
        'kurtosis_excess': float(returns_pct.kurtosis()),
        'skewness': float(returns_pct.skew()),
        'std_pct': float(returns_pct.std()),
        'per_target': {},
    }

    for tgt in targets:
        actual = oos_targets[tgt]
        print(f"\n  --- Target: {tgt} ---")
        tgt_res = {'model_metrics': {}, 'dm_tests': {}, 'sub_period_qlike': None}
        qlike_ind = {}
        for m in model_keys:
            fc = forecasts[m][valid_mask]
            q = qlike(actual, fc)
            valid_both = np.isfinite(actual) & np.isfinite(fc) & (actual > 0) & (fc > 0)
            if valid_both.sum() > 10:
                rho, rho_p = stats.spearmanr(actual[valid_both], fc[valid_both])
            else:
                rho, rho_p = np.nan, 1.0
            tgt_res['model_metrics'][m] = {
                'QLIKE': float(q) if np.isfinite(q) else None,
                'Spearman_rho': float(rho) if np.isfinite(rho) else None,
                'Spearman_p': float(rho_p) if np.isfinite(rho_p) else None,
                'n_finite': int(valid_both.sum()),
            }
            qlike_ind[m] = qlike_pointwise(actual, fc)
            print(f"    {m}: QLIKE={q:.6f}, rho={rho:.3f}")

        q_m1 = tgt_res['model_metrics']['M1_GJR_N']['QLIKE']
        for m in ['M3_GARCH_MIDAS_X', 'M4_HAR_RV_X', 'M5_HAR_RV', 'M6_GAS_t']:
            t_stat, p_val, n_used = dm_hln_test(qlike_ind['M1_GJR_N'], qlike_ind[m])
            q_m = tgt_res['model_metrics'][m]['QLIKE']
            rel = ((q_m1 - q_m) / q_m1 * 100) if (q_m1 and q_m) else np.nan
            tgt_res['dm_tests'][f'{m}_vs_M1'] = {
                'DM_HLN_t': t_stat, 'DM_HLN_p': p_val, 'n_used': n_used,
                'QLIKE_rel_improvement_pct': float(rel) if np.isfinite(rel) else None,
                'gate_DM': bool(abs(t_stat) > 2.0),
                'gate_QLIKE_5pct': bool(np.isfinite(rel) and rel > 5.0),
                'significant_Harvey': bool(abs(t_stat) > 3.0),
                'better': m if t_stat > 0 else 'M1_GJR_N',
            }
            print(f"    DM-HLN {m} vs M1: t={t_stat:.3f}, p={p_val:.3e}, "
                  f"rel={rel:+.2f}%")

        # Fair test: M4 vs M5 (VIX marginal within HAR family)
        t_s, p_s, n_s = dm_hln_test(qlike_ind['M5_HAR_RV'],
                                    qlike_ind['M4_HAR_RV_X'])
        q_m5 = tgt_res['model_metrics']['M5_HAR_RV']['QLIKE']
        q_m4 = tgt_res['model_metrics']['M4_HAR_RV_X']['QLIKE']
        rel45 = ((q_m5 - q_m4) / q_m5 * 100) if (q_m5 and q_m4) else np.nan
        tgt_res['dm_tests']['M4_HAR_RV_X_vs_M5_HAR_RV'] = {
            'DM_HLN_t': t_s, 'DM_HLN_p': p_s, 'n_used': n_s,
            'QLIKE_rel_improvement_pct': float(rel45) if np.isfinite(rel45) else None,
            'gate_DM': bool(abs(t_s) > 2.0),
            'significant_Harvey': bool(abs(t_s) > 3.0),
            'better': 'M4_HAR_RV_X' if t_s > 0 else 'M5_HAR_RV',
            'description': 'VIX marginal value within HAR-RV family',
        }
        print(f"    DM-HLN M4 vs M5 (VIX marginal): t={t_s:.3f}, "
              f"rel={rel45:+.2f}%")

        # Sub-period stability
        sub_idx = np.where(oos_dates_v >= SUB_PERIOD_SPLIT)[0]
        if len(sub_idx) > 50 and len(sub_idx) < n_valid - 50:
            split = int(sub_idx[0])
            sub_a = slice(0, split); sub_b = slice(split, n_valid)
            sub_qlike = {}
            for m in model_keys:
                fc = forecasts[m][valid_mask]
                sub_qlike[m] = {
                    'early': float(qlike(actual[sub_a], fc[sub_a])),
                    'late': float(qlike(actual[sub_b], fc[sub_b])),
                    'n_early': int(split), 'n_late': int(n_valid - split),
                }
            tgt_res['sub_period_qlike'] = sub_qlike
            for m in ['M3_GARCH_MIDAS_X', 'M4_HAR_RV_X', 'M5_HAR_RV',
                      'M6_GAS_t']:
                beat_e = sub_qlike[m]['early'] < sub_qlike['M1_GJR_N']['early']
                beat_l = sub_qlike[m]['late'] < sub_qlike['M1_GJR_N']['late']
                tgt_res['dm_tests'][f'{m}_vs_M1']['gate_subperiod_stable'] = bool(
                    beat_e and beat_l)
                tgt_res['dm_tests'][f'{m}_vs_M1']['sub_early_beats'] = bool(beat_e)
                tgt_res['dm_tests'][f'{m}_vs_M1']['sub_late_beats'] = bool(beat_l)

        for key in ['M3_GARCH_MIDAS_X_vs_M1', 'M4_HAR_RV_X_vs_M1',
                    'M5_HAR_RV_vs_M1', 'M6_GAS_t_vs_M1']:
            gates = tgt_res['dm_tests'].get(key, {})
            gates['triple_gate_PASS'] = bool(
                gates.get('gate_DM', False)
                and gates.get('gate_QLIKE_5pct', False)
                and gates.get('gate_subperiod_stable', False)
            )

        ticker_results['per_target'][tgt] = tgt_res

    all_results[ticker] = ticker_results

sys.stdout.flush()


# ============================================================
# 9-CELL UNIVERSAL-NULL ANALYSIS
# (3 assets × 3 robust models: HAR-RV-X / GARCH-MIDAS-X / GAS-t)
# Brief requires exactly these 3 robust models for asset × model matrix.
# ============================================================
print("\n" + "=" * 72)
print("9-CELL UNIVERSAL-NULL ANALYSIS (3 assets × 3 robust models)")
print("Fair-test view: each model on its native target vs M1 baseline.")
print("  HAR-RV-X: fair test = M4 vs M5 on Parkinson (VIX marginal, same-target)")
print("  GARCH-MIDAS-X: fair test = M3 vs M1 on r² (close²-native)")
print("  GAS-t: fair test = M6 vs M1 on r² (close²-native)")
print("=" * 72)

equity_tickers = list(all_results.keys())
robust_labels = ['HAR-RV-X', 'GARCH-MIDAS-X', 'GAS-t']

# Collect 9 cells: (ticker, model) → dm_t, p, rel%
cell_results = {}
all_pvals = []
all_keys = []
for tk in equity_tickers:
    for lbl in robust_labels:
        if lbl == 'HAR-RV-X':
            dm = all_results[tk]['per_target']['parkinson']['dm_tests'].get(
                'M4_HAR_RV_X_vs_M5_HAR_RV', {})
            target = 'parkinson'
        elif lbl == 'GARCH-MIDAS-X':
            dm = all_results[tk]['per_target']['r2_close']['dm_tests'].get(
                'M3_GARCH_MIDAS_X_vs_M1', {})
            target = 'r2_close'
        else:  # GAS-t
            dm = all_results[tk]['per_target']['r2_close']['dm_tests'].get(
                'M6_GAS_t_vs_M1', {})
            target = 'r2_close'
        cell_results[(tk, lbl)] = {
            'DM_HLN_t': dm.get('DM_HLN_t', 0.0),
            'DM_HLN_p': dm.get('DM_HLN_p', 1.0),
            'rel_pct': dm.get('QLIKE_rel_improvement_pct', 0) or 0,
            'target': target,
        }
        all_pvals.append(dm.get('DM_HLN_p', 1.0))
        all_keys.append((tk, lbl))

# BH correction across 9 cells
bh_adj = benjamini_hochberg(all_pvals)
for i, k in enumerate(all_keys):
    cell_results[k]['DM_HLN_p_BH'] = float(bh_adj[i])

# PASS criterion: DM t ≤ -2 (robust model has LOWER QLIKE, "better" from M1's
# perspective means t > 0 for M1-better; we want robust to be better so t > 0
# from dm_hln_test(qlike_ind['M1_GJR_N'], qlike_ind[m]) → d = q_M1 - q_robust
# positive d means robust wins → positive t means robust wins.
# For M4 vs M5 it's dm_hln_test(M5, M4) → positive d = M4 wins)
# So robust WINS when t > 0 (not ≤ -2); we adopted convention "t > 2 means PASS"
# The brief says "DM t ≤ -2 AND BH adj p < 0.05" but that assumes the sign
# convention where robust loss appears first. We flip: robust PASS = t > +2
# AND BH adj p < 0.05.

print(f"\n{'Asset':<8}", end='')
for lbl in robust_labels:
    print(f" {lbl:>22}", end='')
print()
print("-" * (8 + 23 * len(robust_labels)))
pass_count = 0
for tk in equity_tickers:
    print(f"{tk:<8}", end='')
    for lbl in robust_labels:
        c = cell_results[(tk, lbl)]
        is_pass = (c['DM_HLN_t'] > 2.0) and (c['DM_HLN_p_BH'] < 0.05)
        if is_pass:
            pass_count += 1
        flag = ' PASS' if is_pass else ''
        print(f" t={c['DM_HLN_t']:+6.2f} p_BH={c['DM_HLN_p_BH']:.3f}{flag}", end='')
    print()
print(f"\n  PASS cells / 9: {pass_count}")

# Per-asset NULL check (cross-model): for each ticker, any cell with BOTH
# DM_HLN_t > 2.0 AND DM_HLN_p_BH < 0.05 → PASS. Must satisfy both criteria
# to be consistent with the 9-cell PASS logic at line 828.
print("\nPer-asset NULL (cross-model):")
asset_null = {}
for tk in equity_tickers:
    asset_cells = [cell_results[(tk, lbl)] for lbl in robust_labels]
    asset_pass = any(c['DM_HLN_t'] > 2.0 and c['DM_HLN_p_BH'] < 0.05 for c in asset_cells)
    asset_null[tk] = 'PASS' if asset_pass else 'NULL'
    max_t = max(c['DM_HLN_t'] for c in asset_cells)
    print(f"  {tk}: max DM_t={max_t:+.2f} → {asset_null[tk]}")

# Per-model NULL check (cross-asset): same dual-criterion as 9-cell PASS logic.
print("\nPer-model NULL (cross-asset):")
model_null = {}
for lbl in robust_labels:
    model_cells = [cell_results[(tk, lbl)] for tk in equity_tickers]
    model_pass = any(c['DM_HLN_t'] > 2.0 and c['DM_HLN_p_BH'] < 0.05 for c in model_cells)
    model_null[lbl] = 'PASS' if model_pass else 'NULL'
    max_t = max(c['DM_HLN_t'] for c in model_cells)
    print(f"  {lbl}: max DM_t={max_t:+.2f} → {model_null[lbl]}")

# Harvey joint threshold: |t|>3 AND BH p<0.05 for robust claim
harvey_cells = sum(1 for k in all_keys
                   if cell_results[k]['DM_HLN_t'] > 3.0
                   and cell_results[k]['DM_HLN_p_BH'] < 0.05)
print(f"\nHarvey joint threshold (t>3 & BH p<0.05): {harvey_cells}/9 cells")

# Final verdict
if pass_count >= 4:
    verdict = 'EQUITY_PASSES'
elif pass_count == 0 and harvey_cells == 0:
    verdict = 'UNIVERSAL_NULL_CONFIRMED'
else:
    verdict = 'MIXED'
print(f"\n*** VERDICT: {verdict} ***")


# ============================================================
# K1136 commodity vs K1138 equity max DM-t comparison
# ============================================================
print("\n" + "=" * 72)
print("K1136 commodity vs K1138 equity max DM-t comparison")
print("=" * 72)

# Load K1136 results
k1136_path = os.path.join(os.path.dirname(SCRIPT_DIR), 'k1136',
                          'k1136_results.json')
k1136_compare = None
if os.path.exists(k1136_path):
    with open(k1136_path) as f:
        k1136_data = json.load(f)
    k1136_compare = {}
    for tk, tk_res in k1136_data['per_asset_results'].items():
        dm_m3 = tk_res['per_target']['r2_close']['dm_tests'].get(
            'M3_GARCH_MIDAS_X_vs_M1', {}).get('DM_HLN_t', 0)
        dm_m4m5 = tk_res['per_target']['parkinson']['dm_tests'].get(
            'M4_HAR_RV_X_vs_M5_HAR_RV', {}).get('DM_HLN_t', 0)
        k1136_compare[tk] = {'MIDAS_r2': dm_m3, 'HAR_VIX_park': dm_m4m5,
                             'max': max(dm_m3, dm_m4m5)}
    print("K1136 commodity (max DM-t across fair tests):")
    for tk, v in k1136_compare.items():
        print(f"  {tk}: MIDAS-r² t={v['MIDAS_r2']:+.2f}, "
              f"HAR-VIX-park t={v['HAR_VIX_park']:+.2f} → max {v['max']:+.2f}")

print("\nK1138 equity (max DM-t across 3 robust models):")
for tk in equity_tickers:
    max_t = max(cell_results[(tk, lbl)]['DM_HLN_t'] for lbl in robust_labels)
    best = max(robust_labels,
               key=lambda l: cell_results[(tk, l)]['DM_HLN_t'])
    print(f"  {tk}: max t={max_t:+.2f} (best model: {best})")


# ============================================================
# CHARTS
# ============================================================
# Chart 1: DM heatmap (3 asset × 3 robust model)
fig, ax = plt.subplots(figsize=(9, 5))
heat = np.zeros((len(equity_tickers), len(robust_labels)))
for i, tk in enumerate(equity_tickers):
    for j, lbl in enumerate(robust_labels):
        heat[i, j] = cell_results[(tk, lbl)]['DM_HLN_t']
im = ax.imshow(heat, cmap='RdYlGn', vmin=-3, vmax=3, aspect='auto')
ax.set_xticks(range(len(robust_labels)))
ax.set_xticklabels(robust_labels, fontsize=10)
ax.set_yticks(range(len(equity_tickers)))
ax.set_yticklabels(equity_tickers, fontsize=10)
for i in range(len(equity_tickers)):
    for j in range(len(robust_labels)):
        c = cell_results[(equity_tickers[i], robust_labels[j])]
        txt = f"t={heat[i,j]:+.2f}\np_BH={c['DM_HLN_p_BH']:.2f}"
        ax.text(j, i, txt, ha='center', va='center', fontsize=9)
plt.colorbar(im, ax=ax, label='DM-HLN t (robust vs M1 baseline)')
ax.set_title('K1138: Equity 9-cell DM-HLN heatmap\n'
             '(positive t = robust model beats M1 baseline)')
plt.tight_layout()
chart1 = os.path.join(SCRIPT_DIR, 'dm_heatmap_equity.png')
plt.savefig(chart1, dpi=150)
plt.close()

# Chart 2: K1136 (commodity) vs K1138 (equity) fair-test comparison
fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
if k1136_compare is not None:
    ax = axes[0]
    commodity_tickers = list(k1136_compare.keys())
    x = np.arange(len(commodity_tickers))
    ax.bar(x - 0.2, [k1136_compare[t]['MIDAS_r2'] for t in commodity_tickers],
           0.4, label='MIDAS-X vs M1 (r²)', color='#9C27B0', alpha=0.85)
    ax.bar(x + 0.2, [k1136_compare[t]['HAR_VIX_park'] for t in commodity_tickers],
           0.4, label='HAR-VIX vs HAR (Parkinson)', color='#FF9800', alpha=0.85)
    ax.axhline(2.0, ls='--', color='gray', alpha=0.6, label='|t|=2')
    ax.axhline(3.0, ls=':', color='red', alpha=0.6, label='|t|=3 Harvey')
    ax.axhline(-2.0, ls='--', color='gray', alpha=0.6)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(commodity_tickers)
    ax.set_ylabel('DM-HLN t')
    ax.set_title('K1136: Commodity fair tests')
    ax.legend(fontsize=8)
    ax.grid(axis='y', alpha=0.3)

ax = axes[1]
x = np.arange(len(equity_tickers))
width = 0.25
for j, lbl in enumerate(robust_labels):
    ts = [cell_results[(tk, lbl)]['DM_HLN_t'] for tk in equity_tickers]
    color = {'HAR-RV-X': '#FF9800', 'GARCH-MIDAS-X': '#9C27B0',
             'GAS-t': '#2196F3'}[lbl]
    ax.bar(x + (j - 1) * width, ts, width, label=lbl, color=color, alpha=0.85)
ax.axhline(2.0, ls='--', color='gray', alpha=0.6, label='|t|=2')
ax.axhline(3.0, ls=':', color='red', alpha=0.6, label='|t|=3 Harvey')
ax.axhline(-2.0, ls='--', color='gray', alpha=0.6)
ax.axhline(0, color='black', lw=0.5)
ax.set_xticks(x)
ax.set_xticklabels(equity_tickers)
ax.set_title('K1138: Equity fair tests (robust vs M1 / within-family)')
ax.legend(fontsize=8)
ax.grid(axis='y', alpha=0.3)

fig.suptitle('K1136 commodity vs K1138 equity: fair-test DM-HLN t comparison',
             fontsize=11)
plt.tight_layout()
chart2 = os.path.join(SCRIPT_DIR, 'equity_vs_commodity_fair_tests.png')
plt.savefig(chart2, dpi=150)
plt.close()

print(f"\nCharts saved: {chart1}, {chart2}")


# ============================================================
# SAVE JSON
# ============================================================
# Paper 4 implication
if verdict == 'UNIVERSAL_NULL_CONFIRMED':
    paper4_implication = (
        'Equity joins commodity in the 5-asset-class universal-null narrative. '
        'Paper 4 can claim that robust volatility model extensions (score-driven '
        'GAS-t + non-score-driven GARCH-MIDAS and HAR-X) fail to beat GJR-GARCH '
        'baseline across BOTH equity (SPY/QQQ/IWM) and commodity (USO/GLD/UNG/'
        'BTC-USD) ETFs. This is strong evidence for universal robust-method null '
        'across asset classes.')
elif verdict == 'EQUITY_PASSES':
    paper4_implication = (
        'Robust models PASS on equity but NULL on commodity → asset-class '
        'heterogeneity. Paper 4 needs a new subsection on why VIX-augmented '
        'methods succeed for equity ETFs (where VIX is their own implied vol) '
        'but fail for commodity. This is a positive finding, not a universal '
        'null.')
else:
    paper4_implication = (
        'Mixed results: some (asset, model) combos PASS, others NULL. Paper 4 '
        'should report the specific passing combos explicitly rather than '
        'claiming universal null.')

out = {
    'experiment_id': 'K1138',
    'title': 'Equity compendium (SPY/QQQ/IWM) robust models — Paper 4 asset-class extension',
    'description': (
        'Extend K1136 commodity compendium to equity ETFs (SPY/QQQ/IWM) with '
        '3 robust volatility models (HAR-RV-X, GARCH-MIDAS-X, GAS-t) to test '
        'whether Paper 4 universal-null claim is asset-class invariant.'),
    'methodology': {
        'assets': list(ASSETS.keys()),
        'baseline': 'M1 GJR-GARCH Normal',
        'robust_models': {
            'M3_GARCH_MIDAS_X': 'τ_t = exp(m + θ × VIX²_monthly_lag1); g_t GJR. r²-native.',
            'M4_HAR_RV_X': 'Corsi 2009 HAR on log-Parkinson + log(VIX²_{t-1}). Parkinson-native.',
            'M5_HAR_RV': 'Control: plain Corsi HAR-RV (no VIX). Parkinson-native.',
            'M6_GAS_t': 'Creal-Koopman-Lucas 2013 GAS-t with Fisher-scaled score. r²-native.',
        },
        'targets': targets,
        'window': WINDOW, 'refit_every': REFIT_EVERY,
        'oos_period': f'{OOS_START} to 2026-04-10',
        'seed': 42,
        'rv_proxy_note': ('5-min RV not available for SPY/QQQ/IWM in local cache. '
                          'Using Parkinson range-based variance (same as K1136) '
                          'as RV proxy. This is consistent with K1136 cross-asset '
                          'comparison.'),
        'fair_tests_9_cell': {
            'HAR-RV-X': 'M4 vs M5 on Parkinson (within-family VIX marginal)',
            'GARCH-MIDAS-X': 'M3 vs M1 on r² (close²-native)',
            'GAS-t': 'M6 vs M1 on r² (close²-native)',
        },
        'bh_correction': 'Benjamini-Hochberg FDR across 9 cells',
    },
    'hypotheses': {
        'H1_primary': '≥1 robust model beats M1 on ≥2/3 equity assets via fair test',
        'H2_universal_null': 'All 9 cells NULL → Paper 4 universal-null spans equity+commodity',
        'H3_equity_heterogeneity': '≥4/9 PASS → asset-class heterogeneity subsection',
    },
    'per_asset_results': all_results,
    'nine_cell_analysis': {
        'cell_results': {
            f'{tk}_{lbl}': cell_results[(tk, lbl)]
            for tk in equity_tickers for lbl in robust_labels
        },
        'pass_count_out_of_9': pass_count,
        'harvey_joint_threshold_cells': harvey_cells,
        'asset_null_map': asset_null,
        'model_null_map': model_null,
        'verdict': verdict,
    },
    'k1136_comparison': k1136_compare,
    'summary': {
        'verdict': verdict,
        'paper4_implication': paper4_implication,
        'max_dm_t_equity': {
            tk: max(cell_results[(tk, lbl)]['DM_HLN_t'] for lbl in robust_labels)
            for tk in equity_tickers
        },
        'best_equity_model_combo': max(
            all_keys, key=lambda k: cell_results[k]['DM_HLN_t']),
    },
    'data_source': 'yfinance (SPY/QQQ/IWM OHLC + ^VIX)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Engle, Ghysels, Sohn (2013) Review of Economics and Statistics 95(3):776-797.',
        'Corsi (2009) J Financial Econometrics 7(2):174-196.',
        'Creal, Koopman, Lucas (2013) J Applied Econometrics 28(5):777-795.',
        'Patton (2011) J Econometrics 160:246-256.',
        'Harvey, Leybourne, Newbold (1997) Int J Forecasting 13:281-291.',
        'Harvey (2016) Review of Financial Studies 29:5-68 (|t|>3 threshold).',
        'Benjamini, Hochberg (1995) J Royal Statistical Society B 57(1):289-300.',
    ],
}
json_path = os.path.join(SCRIPT_DIR, 'k1138_results.json')
with open(json_path, 'w') as f:
    json.dump(out, f, indent=2, default=str)

print(f"\nResults saved: {json_path}")
print(f"\nFINAL VERDICT: {verdict}")
print(f"Paper 4 implication: {paper4_implication}")
print("\nK1138 complete.")
