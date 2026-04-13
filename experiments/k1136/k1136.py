"""
K1136: Non-score-driven robust vol models on commodity compendium
================================================================================
[提出: Claude (user direction), 執行: Claude]

Motivation:
K1129 + K1134 established GAS family (score-driven Creal-Koopman-Lucas 2013)
is NULL across 8 assets × 4 proxies = 32 DM comparisons (0 triple-gate PASS).
But this only rules out *score-driven* robustification. Literature offers
non-score-driven extensions:
  - GARCH-MIDAS (Engle-Ghysels-Sohn 2013, Rev Econ Stat)
  - HAR-RV-X (Corsi 2009 + exogenous VIX regressor)

K1136 distinguishes two possibilities for Paper 4 framing:
  - Hypothesis A (score-driven failure specific): non-score-driven methods
    (exog-driven long-run trend + HAR + VIX info) PASS → GAS specifically
    fails because score downweights extreme info.
  - Hypothesis B (universal robust-model failure): non-score also fails →
    no daily-frequency exog can add information beyond GJR's own volatility
    process on these 4 commodities.

Design:
  - 4 assets: USO / GLD / UNG / BTC-USD (K1129/K1134 compendium)
  - Baselines (from K1134): M1 GJR-GARCH Normal (r² close, model-native)
                            Reference GAS-t NULL established.
  - Additions:
    * M3 GARCH-MIDAS-X (τ_t driven by prior-month mean of VIX²)
    * M4 HAR-RV-X (Corsi 2009, on log Parkinson RV, +VIX_{t-1} exog)
  - Primary target: Parkinson range-based variance (K1134 found most
    informative proxy; matches HAR-RV's native scale).
  - Secondary: r² close (K1129 baseline for cross-method comparison).
  - Window=1500 (commodity sample constraint from BTC), Refit=63.
  - OOS 2021-2026 (includes COVID + Ukraine + FTX + LUNA, same as K1134).
  - Triple gate: DM |t|>2 (Harvey-Leybourne-Newbold 1997 small-sample),
                 QLIKE rel-improvement > 5%, sub-period stable.
  - Seed: 42.

Key timing safeguards (responding to FRED-delay error_log lesson):
  - VIX is CBOE realtime so VIX_{t-1} is safe for daily models.
  - GARCH-MIDAS monthly τ_t uses MEAN of VIX² in the prior calendar month
    (lag-1 on month index) → no current-month leakage.
  - HAR-RV-X uses Parkinson_{t-1}, VIX_{t-1} → no same-day leakage.
  - All regressors shifted explicitly in code.

Hypotheses:
  H1 (primary): M3 or M4 beat M1 on ≥2/4 assets (triple gate)
                under Parkinson proxy.
  H2: If non-score wins → GAS failure is specific to score-driven
       downweighting (supports E065 interpretation).
  H3: If non-score also NULL → robust-model failure is universal on
       commodity daily vol.

Output: 4 assets × 2 new models × 2 proxies DM table + Paper-4 naming
        recommendation.

Reproduction: python experiments/k1136/k1136.py
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
print("K1136: GARCH-MIDAS-X + HAR-RV-X on Commodities (USO/GLD/UNG/BTC-USD)")
print("VIX as exogenous long-run driver")
print("=" * 72)
sys.stdout.flush()


# ============================================================
# STEP 0: DATA
# ============================================================
import yfinance as yf

ASSETS = {
    'USO':      {'start': '2007-01-01', 'end': '2026-04-11'},
    'GLD':      {'start': '2005-01-01', 'end': '2026-04-11'},
    'UNG':      {'start': '2008-01-01', 'end': '2026-04-11'},
    'BTC-USD':  {'start': '2015-01-01', 'end': '2026-04-11'},
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
    # Parkinson variance in pct² (matches K1134)
    log_hl = np.log(ohlc['High'] / ohlc['Low'])
    park_pct2 = (log_hl ** 2 / (4 * np.log(2)) * 10000.0)

    # VIX aligned to asset dates (inner merge; BTC trades weekends → lose Sat/Sun where VIX missing)
    vix_aligned = vix_close.reindex(returns_pct.index)
    # For weekends/holidays with missing VIX, forward-fill (most recent VIX known)
    vix_aligned = vix_aligned.ffill()
    # Drop leading NaN (before VIX starts)
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
# M1 GJR-GARCH Normal (BASELINE — same as K1134)
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
# M3 GARCH-MIDAS-X (Engle-Ghysels-Sohn 2013, simplified)
# ============================================================
# σ²_t = τ_t × g_t
# Short-run g_t follows GJR-GARCH on devolatilized returns ε_t = r_t / √τ_t:
#   g_t = (1-α-γ/2-β) + α·(ε_{t-1})² + γ·(ε_{t-1})²·I(r_{t-1}<0) + β·g_{t-1}
# Long-run τ_t = exp(m + θ × VIX²_monthly_lag1)
# VIX²_monthly_lag1 = mean of VIX² over prior calendar month (no leakage)
#
# This is a simplified MIDAS: instead of Beta weights over K monthly lags,
# we use lag-1 month mean (single-lag MIDAS). This reduces parameter count
# (avoid w_1, w_2 weight parameters) while preserving the "low-freq exog driver"
# structure. Analogous to Engle-Ghysels-Sohn Table 3's "RV fixed window".

def build_vix_monthly_lag1(daily_vix):
    """For each daily date d, return mean(VIX²) over the calendar month strictly
    before d's month (i.e., prior complete calendar month).

    Leakage-safe: for day d in month M, we only use dates in months M-1, M-2, ...
    The returned value for d is the mean VIX² over month M-1 only.

    Implementation: resample to month-end labels, then for each d pick the
    latest month-end label that is strictly < first-of-month(d). This way
    same-month data never enters.
    """
    vix2 = daily_vix ** 2
    monthly = vix2.resample('ME').mean()  # month-end labels
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
    """Simplified GARCH-MIDAS-X negative log-likelihood.
    params = [m, theta, alpha, gamma, beta]
    τ_t = exp(m + theta × vix2_monthly_{lag1}[t])
    g_t GJR-GARCH on ε = r / √τ"""
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
            # g update: intercept (1-α-γ/2-β) so E[g]=1 in long run
            omega_g = max(1 - alpha - gamma_/2 - beta, 1e-6)
            g[t+1] = (omega_g + alpha * eps[t]**2
                      + gamma_ * eps[t]**2 * ind + beta * g[t])
            if g[t+1] < 1e-8:
                g[t+1] = 1e-8
    return nll if np.isfinite(nll) else 1e10


def fit_garch_midas_x(returns, vix2_monthly):
    """Fit simplified GARCH-MIDAS-X. Return params + final τ,g."""
    T = len(returns)
    var_r = np.var(returns)
    # Initial guesses: m = log(var_r), theta small
    log_var = np.log(var_r)
    x0_list = [
        [log_var, 0.001, 0.03, 0.05, 0.88],
        [log_var, 0.005, 0.05, 0.05, 0.85],
        [log_var - 1.0, 0.0, 0.03, 0.05, 0.88],
    ]
    bounds = [
        (log_var - 5, log_var + 5),
        (-1.0, 1.0),      # theta
        (1e-8, 0.3),      # alpha
        (-0.1, 0.3),      # gamma (allow mild inverse)
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
    """One-step forecast of σ² = τ_{t+1} × g_{t+1}."""
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
# M4 HAR-RV-X (Corsi 2009 on log-RV + VIX_{t-1})
# ============================================================
# log(RV_t) = β0 + β_d log(RV_{t-1}) + β_w log(meanRV_{t-5:t-1})
#           + β_m log(meanRV_{t-22:t-1}) + β_x log(VIX²_{t-1}) + ε
# RV = Parkinson variance (pct² units).
# All regressors strictly shifted by 1 — no same-day leakage.

def fit_har_rv_x(rv_series, vix_series, include_vix=True):
    """Fit HAR(-RV)(-X) via OLS on log-RV.
    rv_series: pd.Series of RV (pct²).  vix_series: pd.Series of VIX level.
    include_vix=False → plain HAR-RV (Corsi 2009) without exogenous.
    """
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
    """Forecast next-day RV from trailing RV series and VIX (level).
    rv_history: pd.Series ending at day t-1 (last value = RV_{t-1}).
    Returns σ² prediction for day t. If params['include_vix']=False, VIX
    regressor is omitted."""
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
# EVALUATION — QLIKE + DM-HLN (same as K1134)
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


# ============================================================
# OOS FORECASTING LOOP
# ============================================================
all_results = {}
model_keys = ['M1_GJR_N', 'M3_GARCH_MIDAS_X', 'M4_HAR_RV_X', 'M5_HAR_RV']
# M5 is plain HAR-RV (no VIX) — control for isolating VIX's incremental contribution.
# Without M5, M4's win on Parkinson could be "HAR fits Parkinson target" mechanical
# rather than "VIX adds info". M5 vs M4 tests the VIX contribution on RV-native task.
targets = ['parkinson', 'r2_close']  # primary + secondary

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

    # Build VIX monthly_lag1 (for MIDAS-X). Leakage-safe: for day t, uses
    # mean VIX² over prior calendar month.
    vix_m_lag1 = build_vix_monthly_lag1(vix)
    # Drop any dates without valid vix_m_lag1 (e.g. very early in sample)
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
    # State carriers
    state_m1_sigma2 = None
    state_m3_g = None
    state_m3_eps = None
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

            # M4 HAR-RV-X (with VIX)
            p_m4 = fit_har_rv_x(train_park, train_vix, include_vix=True)
            if p_m4 is not None:
                params_cur['M4_HAR_RV_X'] = p_m4

            # M5 HAR-RV (no VIX) — control for VIX's marginal value
            p_m5 = fit_har_rv_x(train_park, train_vix, include_vix=False)
            if p_m5 is not None:
                params_cur['M5_HAR_RV'] = p_m5

            last_fit = t_oos
            if t_oos % (REFIT_EVERY * 4) == 0:
                elapsed = time.time() - t0
                pct = t_oos / n_oos * 100
                print(f"  [{ticker}] {pct:.0f}% ({t_oos}/{n_oos}) {elapsed:.1f}s")
                sys.stdout.flush()

        last_r = returns[t_abs - 1]
        # M1 recurrence using forecasted σ² (standard OOS GARCH)
        if params_cur['M1_GJR_N'] is not None and state_m1_sigma2 is not None:
            h = gjr_n_forecast(params_cur['M1_GJR_N'], last_r, state_m1_sigma2)
            forecasts['M1_GJR_N'][t_oos] = h
            state_m1_sigma2 = h

        # M3 MIDAS-X forecast
        if (params_cur['M3_GARCH_MIDAS_X'] is not None
                and state_m3_g is not None and state_m3_eps is not None):
            # Forecast σ²_t = τ_t × g_t where g_t = f(eps_{t-1}, g_{t-1}, ind_{r_{t-1}})
            # state_m3_g = g_{t-1}, state_m3_eps = eps_{t-1}, last_r = r_{t-1}
            # next_vix_m = VIX²_monthly_lag1[t_abs] → τ_t
            next_vix_m = vix_m_lag1[t_abs]
            if np.isfinite(next_vix_m):
                h3, g_new, tau_new = midas_x_forecast(
                    params_cur['M3_GARCH_MIDAS_X'],
                    last_r, state_m3_eps, state_m3_g, next_vix_m)
                forecasts['M3_GARCH_MIDAS_X'][t_oos] = h3
                # Update states for NEXT iter: need g_t and eps_t
                # g_new = g_t (just computed)
                # eps_t = r_t / sqrt(τ_t) where r_t = returns[t_abs], τ_t = tau_new
                state_m3_g = g_new
                state_m3_eps = returns[t_abs] / np.sqrt(max(tau_new, 1e-10))

        # M4 HAR-RV-X forecast — use trailing park up to t_abs-1 and vix up to t_abs-1
        if params_cur['M4_HAR_RV_X'] is not None:
            rv_hist = park.iloc[:t_abs]  # strictly t-1 and before
            vix_hist = vix.iloc[:t_abs]
            h4 = har_rv_x_forecast(params_cur['M4_HAR_RV_X'], rv_hist, vix_hist)
            if h4 is not None:
                forecasts['M4_HAR_RV_X'][t_oos] = h4

        # M5 HAR-RV (no VIX) forecast
        if params_cur['M5_HAR_RV'] is not None:
            rv_hist = park.iloc[:t_abs]
            h5 = har_rv_x_forecast(params_cur['M5_HAR_RV'], rv_hist, vix_hist)
            if h5 is not None:
                forecasts['M5_HAR_RV'][t_oos] = h5

    elapsed = time.time() - t0
    print(f"  [{ticker}] done in {elapsed:.1f}s")
    sys.stdout.flush()

    # Valid mask
    oos_dates = dates[oos_start_idx:]
    valid_mask = np.ones(n_oos, dtype=bool)
    for m in model_keys:
        valid_mask &= np.isfinite(forecasts[m])
    if np.sum(valid_mask) < 100:
        print(f"  SKIP: <100 valid forecasts for all three models")
        continue
    oos_dates_v = oos_dates[valid_mask]
    n_valid = len(oos_dates_v)
    print(f"  Valid OOS: {n_valid}")

    # Targets
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

        # DM tests: (a) all additions vs M1 baseline (cross-family — caveat re:
        # model-target matching), and (b) M4 vs M5 (VIX marginal value on RV-native
        # task — fair within-family test).
        q_m1 = tgt_res['model_metrics']['M1_GJR_N']['QLIKE']
        for m in ['M3_GARCH_MIDAS_X', 'M4_HAR_RV_X', 'M5_HAR_RV']:
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

        # M4 vs M5 — isolates VIX marginal contribution within HAR-RV family
        # (same target, same fit target, only +/- VIX regressor)
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
            'description': 'Isolates VIX marginal value (HAR-RV-X minus HAR-RV)',
        }
        print(f"    DM-HLN M4 vs M5 (VIX marginal): t={t_s:.3f}, "
              f"rel={rel45:+.2f}%")

        # Cross-family M4 vs M3 (proxy-dependent — keep for completeness)
        t_s, p_s, n_s = dm_hln_test(qlike_ind['M3_GARCH_MIDAS_X'],
                                    qlike_ind['M4_HAR_RV_X'])
        q_m3 = tgt_res['model_metrics']['M3_GARCH_MIDAS_X']['QLIKE']
        rel43 = ((q_m3 - q_m4) / q_m3 * 100) if (q_m3 and q_m4) else np.nan
        tgt_res['dm_tests']['M4_HAR_RV_X_vs_M3_GARCH_MIDAS_X'] = {
            'DM_HLN_t': t_s, 'DM_HLN_p': p_s, 'n_used': n_s,
            'QLIKE_rel_improvement_pct': float(rel43) if np.isfinite(rel43) else None,
            'gate_DM': bool(abs(t_s) > 2.0),
            'better': 'M4_HAR_RV_X' if t_s > 0 else 'M3_GARCH_MIDAS_X',
            'caveat': 'Cross-family: HAR on RV-native target vs GARCH on r²-native model',
        }

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
            for m in ['M3_GARCH_MIDAS_X', 'M4_HAR_RV_X', 'M5_HAR_RV']:
                beat_e = sub_qlike[m]['early'] < sub_qlike['M1_GJR_N']['early']
                beat_l = sub_qlike[m]['late'] < sub_qlike['M1_GJR_N']['late']
                tgt_res['dm_tests'][f'{m}_vs_M1']['gate_subperiod_stable'] = bool(
                    beat_e and beat_l)
                tgt_res['dm_tests'][f'{m}_vs_M1']['sub_early_beats'] = bool(beat_e)
                tgt_res['dm_tests'][f'{m}_vs_M1']['sub_late_beats'] = bool(beat_l)

        for key in ['M3_GARCH_MIDAS_X_vs_M1', 'M4_HAR_RV_X_vs_M1',
                    'M5_HAR_RV_vs_M1']:
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
# CROSS-ASSET SUMMARY — FAIR COMPARISONS ONLY
# ============================================================
# Model-target matching (preamble Rule #1):
#   M1 GJR-N → close² native  → fair on r² target
#   M3 GARCH-MIDAS-X → close² native (GJR short-run on devolatilized returns)
#                      → fair on r² target
#   M4 HAR-RV-X → Parkinson native → tautologically better on Parkinson target
#   M5 HAR-RV → Parkinson native → tautologically better on Parkinson target
#
# FAIR TESTS:
#   1. r² target: M3 vs M1 (close²-native vs close²-native + VIX-MIDAS)
#      → Tests whether VIX long-run driver helps GARCH.
#   2. Parkinson target: M4 vs M5 (HAR+VIX vs HAR no-VIX) within HAR family
#      → Tests whether VIX marginal regressor helps HAR (not cross-family).
#
# UNFAIR/MECHANICAL tests shown for transparency:
#   - M4 vs M1 on Parkinson: HAR wins mechanically (native target)
#   - M1 vs M4 on r²: GJR wins mechanically (native target)
# ============================================================

print("\n" + "=" * 72)
print("FAIR TEST #1: M3 GARCH-MIDAS-X vs M1 GJR-N on r² target")
print("  (both are close²-native; tests VIX long-run driver value)")
print("=" * 72)
print(f"\n{'Asset':<10} {'M1 QL':>10} {'M3 QL':>10} {'DM t':>8} "
      f"{'Rel %':>8} {'Triple':>8}")
print("-" * 60)
h1_m3 = 0
for t in all_results:
    r2 = all_results[t]['per_target']['r2_close']
    m1_q = r2['model_metrics']['M1_GJR_N']['QLIKE']
    m3_q = r2['model_metrics']['M3_GARCH_MIDAS_X']['QLIKE']
    dm = r2['dm_tests'].get('M3_GARCH_MIDAS_X_vs_M1', {})
    t_stat = dm.get('DM_HLN_t', 0)
    rel = dm.get('QLIKE_rel_improvement_pct', 0) or 0
    triple = 'PASS' if dm.get('triple_gate_PASS') else 'FAIL'
    if dm.get('triple_gate_PASS'): h1_m3 += 1
    print(f"{t:<10} {m1_q:>10.4f} {m3_q:>10.4f} {t_stat:>8.2f} "
          f"{rel:>7.1f}% {triple:>8}")
print(f"\nFair test #1 verdict: {h1_m3}/{len(all_results)} "
      f"{'PASS' if h1_m3 >= 2 else 'FAIL'}")

print("\n" + "=" * 72)
print("FAIR TEST #2: M4 HAR-RV-X vs M5 HAR-RV on Parkinson target")
print("  (both Parkinson-native; isolates VIX's marginal value)")
print("=" * 72)
print(f"\n{'Asset':<10} {'M5 QL':>10} {'M4 QL':>10} {'DM t':>8} "
      f"{'Rel %':>8}")
print("-" * 52)
h1_vix_in_har = 0
for t in all_results:
    pk = all_results[t]['per_target']['parkinson']
    m5_q = pk['model_metrics']['M5_HAR_RV']['QLIKE']
    m4_q = pk['model_metrics']['M4_HAR_RV_X']['QLIKE']
    dm = pk['dm_tests'].get('M4_HAR_RV_X_vs_M5_HAR_RV', {})
    t_stat = dm.get('DM_HLN_t', 0)
    rel = dm.get('QLIKE_rel_improvement_pct', 0) or 0
    sig = abs(t_stat) > 2.0 and rel > 0
    if abs(t_stat) > 2.0 and rel > 0:
        h1_vix_in_har += 1
    print(f"{t:<10} {m5_q:>10.4f} {m4_q:>10.4f} {t_stat:>8.2f} "
          f"{rel:>7.1f}%  {'VIX+' if sig else ''}")
print(f"\nFair test #2 verdict: VIX adds value to HAR on {h1_vix_in_har}/"
      f"{len(all_results)} assets (|t|>2 and Rel>0)")

print("\n" + "=" * 72)
print("TRANSPARENCY: Mechanical comparisons (not fair, shown for record)")
print("=" * 72)
print("\n[M4 vs M1 on Parkinson — HAR wins mechanically since HAR fits Parkinson]")
print(f"{'Asset':<10} {'M1 QL':>10} {'M4 QL':>10} {'DM t':>8} {'Rel %':>8}")
for t in all_results:
    pk = all_results[t]['per_target']['parkinson']
    m1_q = pk['model_metrics']['M1_GJR_N']['QLIKE']
    m4_q = pk['model_metrics']['M4_HAR_RV_X']['QLIKE']
    dm = pk['dm_tests'].get('M4_HAR_RV_X_vs_M1', {})
    print(f"{t:<10} {m1_q:>10.4f} {m4_q:>10.4f} "
          f"{dm.get('DM_HLN_t',0):>8.2f} "
          f"{dm.get('QLIKE_rel_improvement_pct',0) or 0:>7.1f}%")
print("  → These wins are mechanical (target = fit target), not informative.")

# H1 overall
h1_any = h1_m3  # Only fair tests count
print(f"\nH1 primary (non-score-driven beats M1 on ≥2/4 via FAIR tests):")
print(f"  M3 GARCH-MIDAS-X vs M1 on r² target: {h1_m3}/{len(all_results)}")
print(f"  M4 adds VIX to HAR: {h1_vix_in_har}/{len(all_results)} (supplementary)")
print(f"  Overall: {h1_any}/{len(all_results)} "
      f"{'PASS' if h1_any >= 2 else 'FAIL'}")


# ============================================================
# CHARTS
# ============================================================
colors = {'M1_GJR_N': '#2196F3', 'M3_GARCH_MIDAS_X': '#9C27B0',
          'M4_HAR_RV_X': '#FF9800', 'M5_HAR_RV': '#795548'}

# Chart 1: QLIKE by proxy × asset × model (4 models now)
fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
target_labels = {'r2_close': 'r² (close²) — GARCH-native',
                 'parkinson': 'Parkinson — HAR-native'}
for j, proxy in enumerate(['r2_close', 'parkinson']):
    ax = axes[j]
    x = np.arange(len(all_results))
    width = 0.20
    for i, m in enumerate(model_keys):
        qs = [all_results[t]['per_target'][proxy]['model_metrics'][m]['QLIKE']
              or np.nan for t in all_results]
        ax.bar(x + i * width, qs, width, label=m, color=colors[m], alpha=0.85)
    ax.set_xticks(x + width * 1.5)
    ax.set_xticklabels(list(all_results.keys()), rotation=20, fontsize=9)
    ax.set_title(target_labels[proxy], fontsize=11)
    ax.grid(axis='y', alpha=0.3)
    if j == 0:
        ax.set_ylabel('QLIKE (lower=better)')
        ax.legend(fontsize=8)
fig.suptitle('K1136: Non-score-driven robust models — model-target matched view\n(OOS 2021-2026)', fontsize=11)
plt.tight_layout()
chart1 = os.path.join(SCRIPT_DIR, 'k1136_qlike.png')
plt.savefig(chart1, dpi=150)
plt.close()

# Chart 2: DM-HLN t heatmap — FAIR vs UNFAIR comparisons
fig, axes = plt.subplots(1, 2, figsize=(14, 5))
tkrs = list(all_results.keys())

# Left: FAIR tests
fair_cols = [
    ('r2_close', 'M3_GARCH_MIDAS_X_vs_M1', 'M3 vs M1\n(r² fair)'),
    ('parkinson', 'M4_HAR_RV_X_vs_M5_HAR_RV', 'M4 vs M5\n(VIX marginal)'),
]
ts_fair = np.zeros((len(tkrs), len(fair_cols)))
for i, tk in enumerate(tkrs):
    for j, (pr, mc, _) in enumerate(fair_cols):
        ts_fair[i, j] = all_results[tk]['per_target'][pr]['dm_tests'].get(
            mc, {}).get('DM_HLN_t', 0.0)
ax = axes[0]
im = ax.imshow(ts_fair, cmap='RdYlGn', vmin=-3, vmax=3, aspect='auto')
ax.set_xticks(range(len(fair_cols)))
ax.set_xticklabels([c[2] for c in fair_cols], fontsize=9)
ax.set_yticks(range(len(tkrs)))
ax.set_yticklabels(tkrs, fontsize=9)
for i in range(len(tkrs)):
    for j in range(len(fair_cols)):
        ax.text(j, i, f"{ts_fair[i,j]:.2f}", ha='center', va='center', fontsize=9)
plt.colorbar(im, ax=ax, label='DM-HLN t')
ax.set_title('FAIR tests (model-target matched)')

# Right: Unfair/mechanical for transparency
unfair_cols = [
    ('parkinson', 'M4_HAR_RV_X_vs_M1', 'M4 vs M1\n(Parkinson)\n[HAR-native, unfair]'),
    ('r2_close', 'M4_HAR_RV_X_vs_M1', 'M4 vs M1\n(r²)\n[GARCH-native, unfair]'),
]
ts_unfair = np.zeros((len(tkrs), len(unfair_cols)))
for i, tk in enumerate(tkrs):
    for j, (pr, mc, _) in enumerate(unfair_cols):
        ts_unfair[i, j] = all_results[tk]['per_target'][pr]['dm_tests'].get(
            mc, {}).get('DM_HLN_t', 0.0)
ax = axes[1]
im = ax.imshow(ts_unfair, cmap='RdYlGn', vmin=-13, vmax=13, aspect='auto')
ax.set_xticks(range(len(unfair_cols)))
ax.set_xticklabels([c[2] for c in unfair_cols], fontsize=8)
ax.set_yticks(range(len(tkrs)))
ax.set_yticklabels(tkrs, fontsize=9)
for i in range(len(tkrs)):
    for j in range(len(unfair_cols)):
        ax.text(j, i, f"{ts_unfair[i,j]:.2f}", ha='center', va='center', fontsize=9)
plt.colorbar(im, ax=ax, label='DM-HLN t')
ax.set_title('UNFAIR (mechanical) — shown for transparency')

fig.suptitle('K1136: Fair vs mechanical comparisons under Patton 2011 proxy rules',
             fontsize=11)
plt.tight_layout()
chart2 = os.path.join(SCRIPT_DIR, 'k1136_dm_heatmap.png')
plt.savefig(chart2, dpi=150)
plt.close()

# Chart 3: VIX marginal value within HAR family (M4 vs M5)
#   Only fair within-family comparison; isolates VIX-regressor contribution.
fig, ax = plt.subplots(figsize=(9, 5))
tkrs = list(all_results.keys())
x = np.arange(len(tkrs))
width = 0.35
m4_t = [all_results[tk]['per_target']['parkinson']['dm_tests'].get(
        'M4_HAR_RV_X_vs_M5_HAR_RV', {}).get('DM_HLN_t', 0) for tk in tkrs]
m3_t = [all_results[tk]['per_target']['r2_close']['dm_tests'].get(
        'M3_GARCH_MIDAS_X_vs_M1', {}).get('DM_HLN_t', 0) for tk in tkrs]
ax.bar(x - width/2, m3_t, width,
       label='M3 GARCH-MIDAS-X vs M1 on r² (fair)', color='#9C27B0', alpha=0.85)
ax.bar(x + width/2, m4_t, width,
       label='M4 vs M5 on Parkinson (VIX marginal in HAR)', color='#FF9800', alpha=0.85)
ax.axhline(2.0, ls='--', color='gray', alpha=0.6, label='|t|=2')
ax.axhline(-2.0, ls='--', color='gray', alpha=0.6)
ax.axhline(3.0, ls=':', color='red', alpha=0.6, label='|t|=3 Harvey')
ax.axhline(-3.0, ls=':', color='red', alpha=0.6)
ax.axhline(0, color='black', lw=0.5)
ax.set_xticks(x)
ax.set_xticklabels(tkrs)
ax.set_ylabel('DM-HLN t (positive = VIX-augmented wins)')
ax.set_title('K1136 fair tests: Does VIX add value?\nFair1 = MIDAS exog driver | Fair2 = marginal VIX regressor in HAR')
ax.legend(fontsize=8, loc='best')
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart3 = os.path.join(SCRIPT_DIR, 'k1136_fair_tests.png')
plt.savefig(chart3, dpi=150)
plt.close()

print(f"\nCharts saved: {chart1}, {chart2}, {chart3}")


# ============================================================
# SAVE JSON
# ============================================================
paper4_naming = ''
# Interpretation rules (honest):
#  - Fair test #1 (M3 vs M1 on r²): tests if VIX as long-run exog helps
#    close²-native GARCH prediction.
#  - Fair test #2 (M4 vs M5 on Parkinson): tests if VIX adds marginal
#    value to HAR-RV family (within-family, same target).
#  - M4 vs M1 on Parkinson is MECHANICAL (HAR-native target), not informative.
if h1_m3 >= 2 and h1_vix_in_har >= 2:
    paper4_naming = (
        'Non-score-driven robust methods DO succeed (both MIDAS exog and HAR-VIX). '
        'Paper 4 naming: "Score-driven downweighting fails on commodity vol; '
        'exogenous VIX driver succeeds" — GAS specifically fails due to '
        'downweight of extreme information; VIX-level info adds signal.')
elif h1_m3 >= 2 or h1_vix_in_har >= 2:
    paper4_naming = (
        'Partial non-score success. Paper 4 naming: "Robust-model failure is '
        'method-dependent — score-driven (GAS) fails; one of {MIDAS exog, '
        'HAR-VIX} succeeds". Specifics in JSON.')
else:
    paper4_naming = (
        'Universal robust-model failure under fair tests: paper4_name='
        '"robust-model NULL across score-driven AND non-score-driven methods". '
        'Covers GAS (K1129/K1134) + GARCH-MIDAS-X + HAR-RV-X (K1136).')

out = {
    'experiment_id': 'K1136',
    'title': 'Non-score-driven robust vol models on commodity compendium',
    'description': (
        'Test whether non-score-driven robust extensions (GARCH-MIDAS-X with VIX '
        'long-run driver; HAR-RV-X with VIX regressor) beat GJR-GARCH baseline '
        'where GAS-t family (K1129 + K1134) was NULL. Distinguishes "score-driven '
        'specific failure" from "universal robust-model failure" for Paper 4 naming.'
    ),
    'methodology': {
        'assets': list(ASSETS.keys()),
        'baseline': 'M1 GJR-GARCH Normal',
        'additions': {
            'M3_GARCH_MIDAS_X': 'τ_t = exp(m + θ × VIX²_monthly_lag1); g_t GJR(1,1). Close²-native.',
            'M4_HAR_RV_X': 'Corsi 2009 HAR on log-Parkinson + log(VIX²_{t-1}). Parkinson-native.',
            'M5_HAR_RV': 'Control: plain Corsi 2009 HAR-RV (no VIX). Parkinson-native.',
        },
        'targets': targets,
        'window': WINDOW, 'refit_every': REFIT_EVERY,
        'oos_period': f'{OOS_START} to 2026-04-10',
        'seed': 42,
        'lag_safety': 'VIX_{t-1} for HAR; prior-month VIX² mean for MIDAS-X (no leakage)',
        'fair_tests': {
            'Fair_1': 'M3 vs M1 on r² target (close²-native comparison; tests MIDAS VIX long-run driver)',
            'Fair_2': 'M4 vs M5 on Parkinson (Parkinson-native within-family; isolates VIX marginal value)',
        },
        'unfair_tests_documented': {
            'M4_vs_M1_on_Parkinson': 'Model-target mismatch — HAR wins mechanically',
            'M3_vs_M1_on_Parkinson': 'Model-target mismatch — GARCH-family loses mechanically',
        },
    },
    'hypotheses': {
        'H1_primary': 'Non-score-driven methods beat M1 on ≥2/4 via FAIR tests',
        'H2': 'If H1 PASS → GAS failure specific to score-driven',
        'H3': 'If H1 FAIL → universal robust-model failure',
    },
    'per_asset_results': all_results,
    'summary': {
        'fair_test_1_m3_midas_pass_count': h1_m3,
        'fair_test_2_vix_in_har_sig_count': h1_vix_in_har,
        'h1_overall_verdict': 'PASS' if h1_any >= 2 else 'FAIL',
        'paper4_naming_recommendation': paper4_naming,
        'warning': ('M4 HAR-RV-X wins on Parkinson are MECHANICAL (HAR is '
                    'fit on Parkinson target, so trivially better than '
                    'GJR-GARCH on Parkinson). Only Fair Test #1 (M3 vs M1 '
                    'on r²) and Fair Test #2 (M4 vs M5 on Parkinson) count.'),
    },
    'data_source': 'yfinance (OHLC for assets; ^VIX for exogenous)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Engle, Ghysels, Sohn (2013) Stock market volatility and macroeconomic fundamentals. Review of Economics and Statistics 95(3):776-797.',
        'Corsi (2009) A simple approximate long-memory model of realized volatility. Journal of Financial Econometrics 7(2):174-196.',
        'Patton (2011) J Econometrics 160:246-256.',
        'Harvey-Leybourne-Newbold (1997) IJF 13:281-291.',
        'Harvey (2016) |t|>3 multiple-testing threshold. RFS 29:5-68.',
    ],
}
json_path = os.path.join(SCRIPT_DIR, 'k1136_results.json')
with open(json_path, 'w') as f:
    json.dump(out, f, indent=2, default=str)

print(f"\nResults saved: {json_path}")
print(f"\nFINAL: {out['summary']['h1_overall_verdict']} — {out['summary']['paper4_naming_recommendation']}")
print("\nK1136 complete.")
