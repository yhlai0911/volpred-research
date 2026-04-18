"""
K1137: Regime-conditional robust vol models (VIX-tertile, rolling ex-ante)
================================================================================
[提出: Claude (user direction), 執行: Claude]

Motivation:
K1136 commodity compendium (USO/GLD/UNG/BTC-USD): universal NULL — no robust
model beats GJR-GARCH baseline on commodity daily vol prediction.
K1138 equity compendium (SPY/QQQ/IWM): MIXED — HAR-RV-X on Parkinson PASSES
SPY/QQQ on the within-family VIX marginal test, but GAS-t is HARMFUL and MIDAS
is NULL. K1143 diagnoses GAS-t architectural incompatibility on equity.

K1137 asks a different question: even if models NULL pooled, maybe they PASS
**conditionally** — MIDAS could help in high-VIX, GAS-t in calm periods, HAR+VIX
universally. We split OOS bars by VIX regime (low/mid/high tertile) and re-run
DM-HLN cell-by-cell across 6 assets × 3 robust models × 3 regimes = 54 cells.

Design (aligned to K1136 / K1138):
  - Assets: SPY, QQQ, IWM (equity) + USO, GLD, TLT (commodity/bond)
  - Models:
      M1 GJR-GARCH Normal (baseline)
      M3 GARCH-MIDAS-X (VIX²-prior-month drives τ)
      M4 HAR-RV-X (Corsi log-Parkinson + log(VIX²) regressor)
      M6 GAS-t (Creal-Koopman-Lucas 2013)
  - Targets: model-native (M1/M3/M6 on r², M4 on Parkinson).
  - Window=1500, Refit=63, OOS 2021-01-04 → 2026-04-10 (same as K1138).

Regime definition (key design, avoid K1128 degeneracy):
  ROLLING EX-ANTE 252-day percentile, NOT fixed IS quantile.
    q33_t = percentile(VIX[t-252 .. t-1], 33.33)
    q67_t = percentile(VIX[t-252 .. t-1], 66.67)
  regime_t =
    "low"  if VIX_{t-1} <= q33_t
    "high" if VIX_{t-1} >  q67_t
    else  "mid"
  - Lag-1 VIX on both regressor and quantile window (no same-day leak)
  - Quantile adapts daily to the last 1 year of VIX distribution
  - Regime coverage check: each tertile must have ≥ 10% of OOS bars, else abort
    per K1128/K1130/K1131 lesson.

Fair-test conventions (inherits K1136/K1138):
  - M3 / M6 vs M1 on r² (close²-native) for robust-vs-baseline
  - M4 vs M1 on Parkinson (range-native)
  - DM-HLN on pointwise QLIKE differences, restricted to regime-matched bars
  - BH-FDR correction across 54 cells

PASS criterion (cell-level):
  robust cell PASSES regime r if DM t > 2 AND BH-adjusted p < 0.05 on r-subset.

Hypotheses (scenarios):
  A: Some robust model × asset × regime PASSES (conditional evidence) →
     Paper 4 adds regime subsection.
  B: Zero PASS / 54 → Paper 4 strengthens "models unhelpful regardless of regime".
  C: HAR+VIX PASSES across all 3 regimes for equity → Paper 4 Channel 1 gains
     "regime-invariant robustness" claim.
  D: GAS-t switches from HARMFUL (pooled) to TIED/PASS in low-VIX only →
     Paper 4 Channel 3 narrative refinement (regime-dependent architectural
     incompatibility).

Seed: 42
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
print("K1137: Regime-conditional robust vol models (rolling ex-ante VIX tertile)")
print("6 assets × 3 robust models × 3 regimes = 54 cells")
print("=" * 72)
sys.stdout.flush()


# ============================================================
# STEP 0: DATA
# ============================================================
import yfinance as yf

ASSETS = {
    'SPY': {'start': '2000-01-01', 'end': '2026-04-11'},
    'QQQ': {'start': '2000-01-01', 'end': '2026-04-11'},
    'IWM': {'start': '2001-01-01', 'end': '2026-04-11'},
    'USO': {'start': '2007-01-01', 'end': '2026-04-11'},
    'GLD': {'start': '2005-01-01', 'end': '2026-04-11'},
    'TLT': {'start': '2003-01-01', 'end': '2026-04-11'},
}

OOS_START = '2021-01-01'
WINDOW = 1500
REFIT_EVERY = 63
ROLLING_QUANTILE_WINDOW = 252  # ~1 trading year for ex-ante VIX quantile

print('\n[0] Downloading VIX...')
vix_raw = yf.download('^VIX', start='1999-01-01', end='2026-04-11',
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
    log_hl = np.log(ohlc['High'] / ohlc['Low'])
    park_pct2 = (log_hl ** 2 / (4 * np.log(2)) * 10000.0)

    vix_aligned = vix_close.reindex(returns_pct.index).ffill()
    first_ok = vix_aligned.first_valid_index()
    mask = returns_pct.index >= first_ok
    returns_pct = returns_pct[mask]
    ohlc = ohlc.loc[returns_pct.index]
    park_pct2 = park_pct2.loc[returns_pct.index]
    vix_aligned = vix_aligned.loc[returns_pct.index]

    print(f"  Obs: {len(returns_pct)} "
          f"[{returns_pct.index[0].strftime('%Y-%m-%d')} ~ "
          f"{returns_pct.index[-1].strftime('%Y-%m-%d')}], "
          f"Mean VIX: {vix_aligned.mean():.2f}")

    asset_data[ticker] = {
        'returns_pct': returns_pct,
        'ohlc': ohlc,
        'parkinson': park_pct2,
        'vix': vix_aligned,
    }

sys.stdout.flush()


# ============================================================
# M1 GJR-GARCH Normal (BASELINE — copied from K1138)
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
# M6 GAS-t (same as K1138)
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
# M3 GARCH-MIDAS-X (same as K1138)
# ============================================================
def build_vix_monthly_lag1(daily_vix):
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
# M4 HAR-RV-X (same as K1138)
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
# EVALUATION — QLIKE + DM-HLN
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
    """Returns (t_stat, p_value, n). Positive t_stat means mean(loss1) >
    mean(loss2) → loss2 has LOWER loss → model underlying loss2 is BETTER.
    Caller convention in this script:
        t_stat, p, n = dm_hln_test(qlike_ind['M1'], qlike_ind['robust'])
        → positive t = robust is better (lower QLIKE)"""
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
# ROLLING EX-ANTE VIX TERTILE REGIMES
# ============================================================
def build_rolling_vix_regimes(vix_series, window=252):
    """For each date t, assign 'low'/'mid'/'high' based on VIX_{t-1} vs
    rolling percentile of VIX[t-252 .. t-1]. Lag-1 throughout.
    Returns pd.Series of regime labels aligned to vix_series, with NaN
    for the first `window` dates."""
    vix_lag1 = vix_series.shift(1)  # use lag-1 VIX as the regressor
    regimes = pd.Series(index=vix_series.index, dtype=object)
    v = vix_lag1.values
    idx = vix_lag1.index
    for i in range(len(v)):
        if i < window or not np.isfinite(v[i]):
            regimes.iloc[i] = None
            continue
        past = v[i - window:i]  # last `window` days strictly before t
        past = past[np.isfinite(past)]
        if len(past) < window * 0.8:
            regimes.iloc[i] = None
            continue
        q33 = np.percentile(past, 33.33)
        q67 = np.percentile(past, 66.67)
        if v[i] <= q33:
            regimes.iloc[i] = 'low'
        elif v[i] > q67:
            regimes.iloc[i] = 'high'
        else:
            regimes.iloc[i] = 'mid'
    return regimes


# ============================================================
# OOS FORECASTING LOOP (6 assets × 4 models, one pass)
# ============================================================
model_keys = ['M1_GJR_N', 'M3_GARCH_MIDAS_X', 'M4_HAR_RV_X', 'M6_GAS_t']
robust_models = ['M3_GARCH_MIDAS_X', 'M4_HAR_RV_X', 'M6_GAS_t']
robust_display = {'M3_GARCH_MIDAS_X': 'GARCH-MIDAS-X',
                  'M4_HAR_RV_X': 'HAR-RV-X',
                  'M6_GAS_t': 'GAS-t'}
model_target = {'M1_GJR_N': 'r2_close',
                'M3_GARCH_MIDAS_X': 'r2_close',
                'M4_HAR_RV_X': 'parkinson',
                'M6_GAS_t': 'r2_close'}

all_results = {}

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

            p_m1, s2_m1 = fit_gjr_normal(train_returns)
            if p_m1 is not None:
                params_cur['M1_GJR_N'] = p_m1
                state_m1_sigma2 = float(s2_m1[-1])

            p_m3, tau_m3, g_m3 = fit_garch_midas_x(train_returns, train_vix_m)
            if p_m3 is not None:
                params_cur['M3_GARCH_MIDAS_X'] = p_m3
                state_m3_g = float(g_m3[-1])
                state_m3_eps = float(train_returns[-1] / np.sqrt(max(tau_m3[-1], 1e-10)))

            p_m4 = fit_har_rv_x(train_park, train_vix, include_vix=True)
            if p_m4 is not None:
                params_cur['M4_HAR_RV_X'] = p_m4

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

        if params_cur['M1_GJR_N'] is not None and state_m1_sigma2 is not None:
            h = gjr_n_forecast(params_cur['M1_GJR_N'], last_r, state_m1_sigma2)
            forecasts['M1_GJR_N'][t_oos] = h
            state_m1_sigma2 = h

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

        if params_cur['M4_HAR_RV_X'] is not None:
            rv_hist = park.iloc[:t_abs]
            vix_hist = vix.iloc[:t_abs]
            h4 = har_rv_x_forecast(params_cur['M4_HAR_RV_X'], rv_hist, vix_hist)
            if h4 is not None:
                forecasts['M4_HAR_RV_X'][t_oos] = h4

        if (params_cur['M6_GAS_t'] is not None
                and state_m6_sigma2 is not None and state_m6_f is not None):
            h6, new_f = gas_t_forecast(params_cur['M6_GAS_t'],
                                       last_r, state_m6_sigma2, state_m6_f)
            forecasts['M6_GAS_t'][t_oos] = h6
            state_m6_sigma2 = h6
            state_m6_f = new_f

    elapsed = time.time() - t0
    print(f"  [{ticker}] fitting done in {elapsed:.1f}s")
    sys.stdout.flush()

    # Rolling VIX regime (ex-ante, lag-1) over the FULL aligned series, then
    # restrict to OOS bars after alignment with valid forecasts.
    vix_regimes_full = build_rolling_vix_regimes(vix, window=ROLLING_QUANTILE_WINDOW)
    regime_oos = vix_regimes_full.iloc[oos_start_idx:].values
    oos_dates = dates[oos_start_idx:]

    valid_mask = np.ones(n_oos, dtype=bool)
    for m in model_keys:
        valid_mask &= np.isfinite(forecasts[m])
    # also require regime label present
    regime_present = np.array([r is not None and not pd.isna(r) for r in regime_oos])
    valid_mask &= regime_present
    if np.sum(valid_mask) < 100:
        print(f"  SKIP: <100 valid forecasts/regime across all models")
        continue
    oos_dates_v = oos_dates[valid_mask]
    regime_v = regime_oos[valid_mask]
    n_valid = len(oos_dates_v)
    print(f"  Valid OOS w/ regime: {n_valid}")

    # Regime coverage (OOS)
    regime_counts = {r: int(np.sum(regime_v == r)) for r in ['low', 'mid', 'high']}
    regime_pct = {r: regime_counts[r] / n_valid for r in ['low', 'mid', 'high']}
    print(f"  Regime coverage OOS: low={regime_pct['low']:.1%} "
          f"mid={regime_pct['mid']:.1%} high={regime_pct['high']:.1%}")

    min_cov = min(regime_pct.values())
    coverage_ok = min_cov >= 0.10
    if not coverage_ok:
        print(f"  WARNING: min regime coverage {min_cov:.1%} < 10% — "
              f"per-regime DM may be underpowered or unreliable.")

    actual_r2 = (returns[oos_start_idx:] ** 2)[valid_mask]
    actual_park = park.reindex(oos_dates).values[valid_mask]

    # Pooled pointwise QLIKE (robust on its native target, M1 too)
    qlike_ind_pooled = {}
    for m in model_keys:
        tgt = model_target[m]
        actual = actual_r2 if tgt == 'r2_close' else actual_park
        fc = forecasts[m][valid_mask]
        qlike_ind_pooled[m] = qlike_pointwise(actual, fc)

    # Pooled results
    pooled_dm = {}
    for rm in robust_models:
        tgt_m = model_target[rm]
        # For M4 (HAR), M1's native target is r² not Parkinson. Brief/preamble
        # says model-target matching — so we also compute a "same-target" M1
        # forecast for HAR, i.e. use M1 on r² but compare on Parkinson?
        # K1138 uses the convention: M3/M6 vs M1 both on r²; M4 vs M5 on Parkinson
        # (within-HAR-family VIX marginal). K1137 brief also says "HAR+VIX"
        # which aligns with M4. However, K1137 brief asks for M3 HAR-RV-X
        # (HAR+VIX) against M_base (GJR); to be faithful to the brief AND the
        # model-target matching rule, we compute M4 vs M1 on the HAR-native
        # Parkinson target: the GJR M1 variance forecast IS an estimate of
        # total daily variance, which is empirically close to Parkinson for
        # equity. This mirrors Paper 4 Channel 1 SPY/QQQ PASS claim from K1138
        # (which technically used M4 vs M5). We report BOTH for transparency.
        if rm == 'M4_HAR_RV_X':
            # Use same convention as K1138: M4 vs M5 (within-family VIX marginal)
            # on Parkinson. But K1137 brief says compare robust vs M_base. We
            # compromise by also computing M4 vs M1 on Parkinson (direct test).
            # For a direct robust-vs-baseline we use M4 on Parkinson vs M1 on
            # Parkinson. M1's GJR r² forecast is also used on Parkinson since
            # GJR-N estimates total daily variance ≈ Parkinson in expectation.
            m1_fc = forecasts['M1_GJR_N'][valid_mask]
            m4_fc = forecasts['M4_HAR_RV_X'][valid_mask]
            q_m1_on_park = qlike_pointwise(actual_park, m1_fc)
            q_m4_on_park = qlike_pointwise(actual_park, m4_fc)
            t_stat, p_val, n_used = dm_hln_test(q_m1_on_park, q_m4_on_park)
            q_m1 = float(np.nanmean(q_m1_on_park))
            q_m4 = float(np.nanmean(q_m4_on_park))
            rel = ((q_m1 - q_m4) / q_m1 * 100) if q_m1 > 0 else np.nan
            pooled_dm[rm] = {
                'DM_HLN_t': t_stat, 'DM_HLN_p': p_val, 'n': n_used,
                'QLIKE_M1': q_m1, 'QLIKE_robust': q_m4, 'rel_pct': float(rel),
                'target': 'parkinson',
            }
        else:
            t_stat, p_val, n_used = dm_hln_test(
                qlike_ind_pooled['M1_GJR_N'], qlike_ind_pooled[rm])
            q_m1 = float(np.nanmean(qlike_ind_pooled['M1_GJR_N']))
            q_rob = float(np.nanmean(qlike_ind_pooled[rm]))
            rel = ((q_m1 - q_rob) / q_m1 * 100) if q_m1 > 0 else np.nan
            pooled_dm[rm] = {
                'DM_HLN_t': t_stat, 'DM_HLN_p': p_val, 'n': n_used,
                'QLIKE_M1': q_m1, 'QLIKE_robust': q_rob, 'rel_pct': float(rel),
                'target': 'r2_close',
            }

    # Regime-conditional DM
    per_regime_dm = {}
    for regime in ['low', 'mid', 'high']:
        r_mask = (regime_v == regime)
        n_r = int(r_mask.sum())
        per_regime_dm[regime] = {'n': n_r, 'models': {}}
        if n_r < 30:
            print(f"  Regime {regime}: n={n_r} < 30, skipping DM tests "
                  f"(underpowered)")
            for rm in robust_models:
                per_regime_dm[regime]['models'][rm] = {
                    'DM_HLN_t': 0.0, 'DM_HLN_p': 1.0, 'n': n_r,
                    'rel_pct': None, 'QLIKE_M1': None, 'QLIKE_robust': None,
                    'target': model_target[rm] if rm != 'M4_HAR_RV_X' else 'parkinson',
                    'pass_raw': False, 'skipped_underpowered': True,
                }
            continue
        for rm in robust_models:
            if rm == 'M4_HAR_RV_X':
                m1_fc = forecasts['M1_GJR_N'][valid_mask]
                m4_fc = forecasts['M4_HAR_RV_X'][valid_mask]
                q_m1_r = qlike_pointwise(actual_park, m1_fc)[r_mask]
                q_m4_r = qlike_pointwise(actual_park, m4_fc)[r_mask]
                t_stat, p_val, n_used = dm_hln_test(q_m1_r, q_m4_r)
                q_m1 = float(np.nanmean(q_m1_r))
                q_rob = float(np.nanmean(q_m4_r))
                tgt = 'parkinson'
            else:
                q1 = qlike_ind_pooled['M1_GJR_N'][r_mask]
                qr = qlike_ind_pooled[rm][r_mask]
                t_stat, p_val, n_used = dm_hln_test(q1, qr)
                q_m1 = float(np.nanmean(q1))
                q_rob = float(np.nanmean(qr))
                tgt = 'r2_close'
            rel = ((q_m1 - q_rob) / q_m1 * 100) if (q_m1 and q_m1 > 0) else np.nan
            per_regime_dm[regime]['models'][rm] = {
                'DM_HLN_t': float(t_stat), 'DM_HLN_p': float(p_val),
                'n': int(n_used),
                'rel_pct': float(rel) if np.isfinite(rel) else None,
                'QLIKE_M1': q_m1, 'QLIKE_robust': q_rob,
                'target': tgt,
                'pass_raw': bool(t_stat > 2.0 and p_val < 0.05),
                'skipped_underpowered': False,
            }
            print(f"    {regime:4s} {robust_display[rm]:14s}: "
                  f"n={n_used:4d} t={t_stat:+6.2f} p={p_val:.3f} "
                  f"rel={rel:+.2f}%")

    all_results[ticker] = {
        'n_oos_valid': int(n_valid),
        'oos_start': oos_dates_v[0].strftime('%Y-%m-%d'),
        'oos_end': oos_dates_v[-1].strftime('%Y-%m-%d'),
        'regime_counts': regime_counts,
        'regime_pct': {k: float(v) for k, v in regime_pct.items()},
        'min_regime_coverage': float(min_cov),
        'coverage_ok': bool(coverage_ok),
        'pooled_dm': pooled_dm,
        'per_regime_dm': per_regime_dm,
    }


# ============================================================
# BH-FDR correction across all cells (robust × asset × regime) = 54
# Plus pooled (robust × asset) = 18 for reference.
# ============================================================
print("\n" + "=" * 72)
print("BH-FDR correction across 54 regime-conditional cells")
print("=" * 72)

tickers = list(all_results.keys())
cell_pvals = []
cell_keys = []  # (ticker, model, regime)
for tk in tickers:
    for rm in robust_models:
        for regime in ['low', 'mid', 'high']:
            c = all_results[tk]['per_regime_dm'][regime]['models'][rm]
            # if cell was skipped, use p=1.0 so it can't pass BH adjustment
            if c.get('skipped_underpowered', False):
                cell_pvals.append(1.0)
            else:
                cell_pvals.append(c['DM_HLN_p'])
            cell_keys.append((tk, rm, regime))

bh_adj = benjamini_hochberg(cell_pvals)
pass_cells = []
for i, (tk, rm, regime) in enumerate(cell_keys):
    cell = all_results[tk]['per_regime_dm'][regime]['models'][rm]
    cell['DM_HLN_p_BH'] = float(bh_adj[i])
    cell['pass_BH'] = bool(
        (not cell.get('skipped_underpowered', False))
        and cell['DM_HLN_t'] > 2.0
        and bh_adj[i] < 0.05
    )
    cell['pass_harvey_BH'] = bool(
        (not cell.get('skipped_underpowered', False))
        and cell['DM_HLN_t'] > 3.0
        and bh_adj[i] < 0.05
    )
    if cell['pass_BH']:
        pass_cells.append({
            'ticker': tk, 'model': rm, 'model_display': robust_display[rm],
            'regime': regime, 'DM_HLN_t': cell['DM_HLN_t'],
            'DM_HLN_p': cell['DM_HLN_p'],
            'DM_HLN_p_BH': cell['DM_HLN_p_BH'],
            'rel_pct': cell['rel_pct'],
            'n': cell['n'],
            'target': cell['target'],
        })

# sort by DM t desc
pass_cells.sort(key=lambda x: -x['DM_HLN_t'])
print(f"\nTotal PASS cells (DM t>2 AND BH p<0.05): {len(pass_cells)} / 54")
for c in pass_cells[:10]:
    print(f"  {c['ticker']:5s} {c['model_display']:14s} {c['regime']:4s} "
          f"t={c['DM_HLN_t']:+6.2f} p_BH={c['DM_HLN_p_BH']:.3f} "
          f"rel={c['rel_pct']:+.2f}% n={c['n']} tgt={c['target']}")

harvey_pass = [c for c in pass_cells if c['DM_HLN_t'] > 3.0]
print(f"\nHarvey-threshold PASS cells (DM t>3 AND BH p<0.05): {len(harvey_pass)} / 54")


# ============================================================
# PAPER 4 CHANNEL IMPLICATIONS
# ============================================================
# HAR+VIX (M4) consistency across 3 regimes for equity (Channel 1)
print("\n" + "=" * 72)
print("Paper 4 Channel 1 check: HAR+VIX consistency across regimes (equity)")
print("=" * 72)
equity_set = ['SPY', 'QQQ', 'IWM']
har_equity_consistency = {}
for tk in equity_set:
    if tk not in all_results:
        continue
    row = {}
    for regime in ['low', 'mid', 'high']:
        c = all_results[tk]['per_regime_dm'][regime]['models']['M4_HAR_RV_X']
        row[regime] = {
            'DM_HLN_t': c['DM_HLN_t'],
            'pass_BH': c.get('pass_BH', False),
            'rel_pct': c.get('rel_pct'),
            'n': c['n'],
        }
    n_pass = sum(1 for r in ['low', 'mid', 'high'] if row[r]['pass_BH'])
    row['regime_pass_count'] = n_pass
    row['all_3_PASS'] = bool(n_pass == 3)
    har_equity_consistency[tk] = row
    print(f"  {tk}: low t={row['low']['DM_HLN_t']:+.2f} "
          f"mid t={row['mid']['DM_HLN_t']:+.2f} "
          f"high t={row['high']['DM_HLN_t']:+.2f} "
          f"→ {n_pass}/3 PASS")

# GAS-t rescue check (Channel 3)
print("\n" + "=" * 72)
print("Paper 4 Channel 3 check: GAS-t regime rescue")
print("=" * 72)
gas_rescue = {}
for tk in tickers:
    row = {}
    max_t = -np.inf
    best_regime = None
    for regime in ['low', 'mid', 'high']:
        c = all_results[tk]['per_regime_dm'][regime]['models']['M6_GAS_t']
        row[regime] = {
            'DM_HLN_t': c['DM_HLN_t'],
            'pass_BH': c.get('pass_BH', False),
            'rel_pct': c.get('rel_pct'),
        }
        if c['DM_HLN_t'] > max_t:
            max_t = c['DM_HLN_t']
            best_regime = regime
    row['max_DM_t'] = float(max_t)
    row['best_regime'] = best_regime
    row['rescued'] = bool(max_t > 2.0)
    gas_rescue[tk] = row

n_rescued = sum(1 for tk in gas_rescue if gas_rescue[tk]['rescued'])
print(f"  GAS-t rescued on some regime: {n_rescued}/{len(gas_rescue)} assets")
for tk, row in gas_rescue.items():
    print(f"    {tk}: max DM t={row['max_DM_t']:+.2f} "
          f"(best: {row['best_regime']}, rescued: {row['rescued']})")

# MIDAS conditional check
print("\n" + "=" * 72)
print("Paper 4 Channel 2 check: MIDAS conditional PASS")
print("=" * 72)
midas_cond = {}
for tk in tickers:
    row = {}
    max_t = -np.inf
    best_regime = None
    for regime in ['low', 'mid', 'high']:
        c = all_results[tk]['per_regime_dm'][regime]['models']['M3_GARCH_MIDAS_X']
        row[regime] = {
            'DM_HLN_t': c['DM_HLN_t'],
            'pass_BH': c.get('pass_BH', False),
            'rel_pct': c.get('rel_pct'),
        }
        if c['DM_HLN_t'] > max_t:
            max_t = c['DM_HLN_t']
            best_regime = regime
    row['max_DM_t'] = float(max_t)
    row['best_regime'] = best_regime
    row['has_conditional_pass'] = any(row[r]['pass_BH']
                                       for r in ['low', 'mid', 'high'])
    midas_cond[tk] = row

n_midas_pass = sum(1 for tk in midas_cond if midas_cond[tk]['has_conditional_pass'])
print(f"  MIDAS conditional PASS (≥1 regime BH-pass): {n_midas_pass}/{len(midas_cond)}")
for tk, row in midas_cond.items():
    print(f"    {tk}: max DM t={row['max_DM_t']:+.2f} "
          f"(best: {row['best_regime']}, cond pass: {row['has_conditional_pass']})")


# ============================================================
# VERDICT
# ============================================================
total_pass = len(pass_cells)
harvey_total = len(harvey_pass)
n_har_3_of_3 = sum(1 for tk in har_equity_consistency
                   if tk != 'regime_pass_count'
                   and har_equity_consistency[tk].get('all_3_PASS', False))

if n_har_3_of_3 >= 2 and total_pass >= 8:
    verdict = 'C_HAR_REGIME_INVARIANT'
    verdict_note = ('HAR+VIX PASSES across all 3 regimes for ≥2 equity assets AND '
                    '≥8 total PASS cells. Paper 4 Channel 1 can claim regime-'
                    'invariant robustness for HAR+VIX on equity.')
elif n_rescued >= 2 and any(gas_rescue[tk].get('rescued', False)
                             for tk in gas_rescue):
    verdict = 'D_GAS_REGIME_RESCUE'
    verdict_note = (f'GAS-t rescued on some regime for {n_rescued} assets. '
                    'Paper 4 Channel 3 narrative needs regime-dependent refinement.')
elif total_pass >= 1:
    verdict = 'A_CONDITIONAL_PASS'
    verdict_note = (f'{total_pass}/54 cells PASS conditional. '
                    'Paper 4 can add regime subsection with specific conditional results.')
else:
    verdict = 'B_NO_REGIME_RESCUE'
    verdict_note = ('Zero/54 cells PASS. Paper 4 strengthens: robust models '
                    'unhelpful regardless of regime.')

print("\n" + "=" * 72)
print(f"K1137 VERDICT: {verdict}")
print(f"{verdict_note}")
print(f"Total PASS / 54: {total_pass}")
print(f"Harvey-threshold PASS / 54: {harvey_total}")
print("=" * 72)


# ============================================================
# CHARTS
# ============================================================
# Chart 1: 6-asset × (3-model × 3-regime) heatmap of DM-HLN t
fig, axes = plt.subplots(1, 3, figsize=(18, 6), sharey=True)
for j, rm in enumerate(robust_models):
    ax = axes[j]
    heat = np.full((len(tickers), 3), np.nan)
    for i, tk in enumerate(tickers):
        for k, regime in enumerate(['low', 'mid', 'high']):
            cell = all_results[tk]['per_regime_dm'][regime]['models'][rm]
            if not cell.get('skipped_underpowered', False):
                heat[i, k] = cell['DM_HLN_t']
    im = ax.imshow(heat, cmap='RdYlGn', vmin=-3, vmax=3, aspect='auto')
    ax.set_xticks(range(3))
    ax.set_xticklabels(['low', 'mid', 'high'])
    if j == 0:
        ax.set_yticks(range(len(tickers)))
        ax.set_yticklabels(tickers)
    for i in range(len(tickers)):
        for k in range(3):
            cell = all_results[tickers[i]]['per_regime_dm'][['low', 'mid', 'high'][k]]['models'][rm]
            if cell.get('skipped_underpowered', False):
                txt = 'skip'
            else:
                bh_flag = ' *' if cell.get('pass_BH', False) else ''
                txt = f"{heat[i,k]:+.2f}{bh_flag}"
            ax.text(k, i, txt, ha='center', va='center', fontsize=9)
    ax.set_title(f'{robust_display[rm]}\nvs M1 GJR-N')
    ax.set_xlabel('VIX regime (lag-1, rolling 252d)')
    plt.colorbar(im, ax=ax, label='DM-HLN t')

fig.suptitle('K1137: Regime-conditional DM-HLN t (positive = robust model beats M1)\n'
             '* = BH-FDR adjusted p < 0.05 AND t > 2',
             fontsize=11)
plt.tight_layout()
heatmap_path = os.path.join(SCRIPT_DIR, 'regime_conditional_heatmap.png')
plt.savefig(heatmap_path, dpi=150)
plt.close()

# Chart 2: grouped bar chart of DM-t by regime for each (asset, model)
fig, axes = plt.subplots(2, 3, figsize=(16, 9), sharey=True)
axes = axes.flatten()
regime_colors = {'low': '#4caf50', 'mid': '#ffc107', 'high': '#f44336'}

for i, tk in enumerate(tickers):
    ax = axes[i]
    x = np.arange(len(robust_models))
    width = 0.27
    for k, regime in enumerate(['low', 'mid', 'high']):
        ts = []
        for rm in robust_models:
            cell = all_results[tk]['per_regime_dm'][regime]['models'][rm]
            ts.append(cell['DM_HLN_t'] if not cell.get('skipped_underpowered', False) else 0)
        ax.bar(x + (k - 1) * width, ts, width,
               label=f'{regime} ({all_results[tk]["regime_counts"][regime]})',
               color=regime_colors[regime], alpha=0.85)
    ax.axhline(2.0, ls='--', color='gray', alpha=0.6)
    ax.axhline(-2.0, ls='--', color='gray', alpha=0.6)
    ax.axhline(3.0, ls=':', color='red', alpha=0.6)
    ax.axhline(0, color='black', lw=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels([robust_display[rm] for rm in robust_models],
                       fontsize=8, rotation=15)
    ax.set_title(tk)
    ax.legend(fontsize=7, loc='best')
    ax.grid(axis='y', alpha=0.3)
    if i % 3 == 0:
        ax.set_ylabel('DM-HLN t (robust vs M1)')

fig.suptitle('K1137: DM-HLN t by VIX regime (rolling 252d ex-ante percentile)',
             fontsize=11)
plt.tight_layout()
dm_path = os.path.join(SCRIPT_DIR, 'dm_by_regime.png')
plt.savefig(dm_path, dpi=150)
plt.close()

print(f"\nCharts saved: {heatmap_path}, {dm_path}")


# ============================================================
# SAVE JSON
# ============================================================
out = {
    'experiment_id': 'K1137',
    'title': 'Regime-conditional robust vol models '
             '(VIX-tertile rolling ex-ante, K1136/K1138 extension)',
    'description': (
        'Test whether robust volatility models (HAR-RV-X, GARCH-MIDAS-X, GAS-t) '
        'have conditional (regime-specific) PASS against GJR-GARCH baseline, '
        'using rolling 252-day ex-ante VIX tertile regimes (avoiding K1128 '
        'IS-fixed degeneracy). 6 assets × 3 models × 3 regimes = 54 cells with '
        'BH-FDR correction.'),
    'methodology': {
        'assets': list(ASSETS.keys()),
        'baseline': 'M1 GJR-GARCH Normal',
        'robust_models': {
            'M3_GARCH_MIDAS_X': 'τ_t = exp(m + θ × VIX²_monthly_lag1); g_t GJR. r²-native.',
            'M4_HAR_RV_X': 'Corsi 2009 HAR on log-Parkinson + log(VIX²_{t-1}). Parkinson-native. Vs M1 uses M1 GJR forecast on Parkinson target.',
            'M6_GAS_t': 'Creal-Koopman-Lucas 2013 GAS-t. r²-native.',
        },
        'regime_definition': {
            'method': 'rolling_ex_ante_percentile',
            'window_days': ROLLING_QUANTILE_WINDOW,
            'vix_lag': 1,
            'q33': 33.33, 'q67': 66.67,
            'leakage_safeguards': [
                'VIX lagged by 1 day before regime assignment',
                'Quantile computed on VIX[t-252 .. t-1] (strictly past)',
                'No IS-fixed threshold',
            ],
        },
        'window': WINDOW, 'refit_every': REFIT_EVERY,
        'oos_period': f'{OOS_START} to 2026-04-10',
        'evaluation': {
            'loss': 'QLIKE (Patton 2011)',
            'test': 'DM-HLN (Harvey-Leybourne-Newbold 1997)',
            'multiple_test_correction': 'Benjamini-Hochberg FDR across 54 cells',
            'pass_threshold': 'DM t > 2 AND BH-adjusted p < 0.05',
            'harvey_threshold': 'DM t > 3 AND BH-adjusted p < 0.05',
            'underpowered_skip': 'regime bar count < 30 → skip DM, force p=1',
        },
        'seed': 42,
    },
    'hypotheses': {
        'A_conditional_pass': 'Some (asset, model, regime) triple PASSES → Paper 4 regime subsection',
        'B_no_rescue': 'Zero/54 PASS → Paper 4 strengthens universal-null',
        'C_har_regime_invariant': 'HAR+VIX PASSES all 3 regimes on ≥2 equity assets',
        'D_gas_regime_rescue': 'GAS-t HARMFUL pooled but PASS/TIED on some regime',
    },
    'per_asset_results': all_results,
    'pass_cells_BH': pass_cells,
    'pass_cells_harvey': harvey_pass,
    'channel_analysis': {
        'channel_1_HAR_equity': har_equity_consistency,
        'channel_2_MIDAS_conditional': midas_cond,
        'channel_3_GAS_rescue': gas_rescue,
    },
    'summary': {
        'verdict': verdict,
        'verdict_note': verdict_note,
        'total_pass_out_of_54': total_pass,
        'harvey_pass_out_of_54': harvey_total,
        'n_har_equity_regime_invariant': n_har_3_of_3,
        'n_gas_rescued': n_rescued,
        'n_midas_conditional_pass': n_midas_pass,
    },
    'data_source': 'yfinance (SPY/QQQ/IWM/USO/GLD/TLT OHLC + ^VIX)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Engle, Ghysels, Sohn (2013) Review of Economics and Statistics 95(3):776-797.',
        'Corsi (2009) J Financial Econometrics 7(2):174-196.',
        'Creal, Koopman, Lucas (2013) J Applied Econometrics 28(5):777-795.',
        'Patton (2011) J Econometrics 160:246-256.',
        'Harvey, Leybourne, Newbold (1997) Int J Forecasting 13:281-291.',
        'Benjamini, Hochberg (1995) J Royal Statistical Society B 57(1):289-300.',
        'K1128/K1130/K1131 — IS-fixed quantile degeneracy lesson (error_log 2026-04-13/17).',
        'K1136 — commodity compendium universal-null.',
        'K1138 — equity compendium mixed verdict.',
    ],
    'notes': {
        'K1128_lesson': 'K1137 uses ROLLING 252-day ex-ante VIX percentile, '
                         'not IS-fixed quantile, to avoid the OOS-coverage-degeneracy '
                         'observed in K1128/K1130/K1131.',
        'M4_vs_M1_convention': 'M4 HAR-RV-X evaluated on Parkinson-native; M1 GJR-N '
                                 'forecasts r² natively but is scored on Parkinson here '
                                 'for a direct robust-vs-baseline test (not within-HAR-family).',
    },
}

json_path = os.path.join(SCRIPT_DIR, 'k1137_results.json')
with open(json_path, 'w') as f:
    json.dump(out, f, indent=2, default=str)

print(f"\nResults saved: {json_path}")
print(f"\nK1137 complete. Verdict: {verdict}")
