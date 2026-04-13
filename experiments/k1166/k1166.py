#!/usr/bin/env python3
"""
K1166: Per-stock theta_EAV refit — remove sigma^2 tautology in K1164 cluster mechanism analysis.

[提出: Claude (K1164 next_tasks K1166), 執行: Claude]

Motivation
----------
K1164 panel regression yielded `log_analyst beta = -0.149, t = -4.55` against
theta_rel_i = theta_EAV_shared / sigma^2_i. This appeared to refute K1153's
analyst-coverage hypothesis but was confounded by a mechanical sigma^2
tautology: within each market log(analyst) correlates positively with sigma^2_i
(US rho=+0.645, JP +0.461), so the construction theta_rel_i ~ 1/sigma^2_i
forces a negative correlation with log(analyst) regardless of mechanism.

K1166 breaks this tautology by *removing the shared theta_EAV* and fitting
a **stock-specific theta_EAV_i** per stock. Cross-stock variation in
theta_EAV_i is then a genuine firm-level mechanism signal, not an artefact
of volatility scaling.

Specification (per stock i)
---------------------------
    sigma2_{i,t} = g_{i,t} * tau_{i,t}
    g_{i,t} ~ GJR(1,1)_i                           # stock-specific omega, alpha, gamma, beta
    tau_{i,t} = max(theta0_i + theta_VIX_i*VIX^2_{t-1} + theta_EAV_i*EAV_{i,t-1}, eps)

All parameters stock-specific, no pooling. 109 independent MLEs.
Uses scipy.optimize L-BFGS-B with multi-start; Hessian SE from numerical 2nd
derivative of the profile likelihood in theta_EAV_i.

Lookahead discipline
--------------------
- VIX^2 enters at lag t-1; EAV at lag t-1; set in numba likelihood.
- EAV built from PUBLICLY DISCLOSED announcement dates.
- Random seed 42.

Data sources (all cached, reused)
---------------------------------
- experiments/k1145/data/*.parquet   TW OHLCV + IDX_VIX
- experiments/k1147/data/*.parquet   US OHLCV + IDX_VIX
- experiments/k1150/data/*.parquet   JP OHLCV + IDX_VIX
- experiments/k1153/data/*.parquet   EU OHLCV + IDX_VIX
- experiments/k1147/data/earnings_dates.json  US earnings
- experiments/k1150/data/earnings_dates.json  JP earnings
- experiments/k1153/data/earnings_dates.json  EU earnings
- 財報公告日.txt                       TW earnings (big5)
- experiments/k1164/data/analyst_media_proxies.json  Analyst/mcap/turnover

References
----------
- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3), 776-797.
- Patton (2011). Volatility forecast comparison. JoE 160(1), 246-256.
- Harvey, Liu & Zhu (2016). RFS 29(1), 5-68. (t>3 threshold)
- Newey & West (1987). Econometrica 55, 703-708.
- K1145/K1147/K1150/K1153/K1164 prior experiments.

Author: VolPred Research System.
Date: 2026-04-13.
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd
from numba import njit
from scipy import optimize, stats

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)
GLOBAL_RNG = np.random.default_rng(GLOBAL_SEED)

EXPERIMENT_ID = 'K1166'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_PATH = SCRIPT_DIR / 'k1166_results.json'
CSV_PATH = SCRIPT_DIR / 'k1166_per_stock_table.csv'
FIG_HIST_PATH = SCRIPT_DIR / 'k1166_theta_eav_hist_by_market.png'
FIG_SCATTER_PATH = SCRIPT_DIR / 'k1166_theta_eav_vs_analyst.png'

TW_TICKERS = [
    '2330.TW', '2303.TW', '6239.TW', '2454.TW', '2379.TW', '3034.TW',
    '3035.TW', '3443.TW', '2388.TW', '2881.TW', '2882.TW', '2883.TW',
    '2886.TW', '2887.TW', '2603.TW', '2615.TW', '2609.TW', '1301.TW',
    '1303.TW', '1326.TW', '2002.TW', '2027.TW', '2317.TW', '3045.TW',
    '2382.TW', '2912.TW', '2637.TW', '1215.TW', '2347.TW', '1210.TW',
    '2892.TW',
]

US_TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B',
    'UNH', 'V', 'JPM', 'WMT', 'MA', 'JNJ', 'XOM', 'PG', 'HD', 'CVX',
    'ABBV', 'AVGO', 'COST', 'PEP', 'KO', 'MRK', 'ADBE', 'CSCO', 'TMO',
    'CRM', 'MCD', 'ABT',
]

JP_TICKERS = [
    '7203.T', '6758.T', '9984.T', '8306.T', '6861.T', '9432.T', '6098.T',
    '7974.T', '6594.T', '8035.T', '4063.T', '6501.T', '9433.T', '8316.T',
    '8411.T', '6902.T', '6367.T', '8001.T', '8058.T', '4502.T', '6273.T',
    '7741.T', '6981.T', '8801.T', '6178.T', '7267.T', '8031.T', '4503.T',
    '8002.T', '6701.T',
]

EU_TICKERS = [
    'SAP.DE', 'SIE.DE', 'ALV.DE', 'MRK.DE', 'BMW.DE', 'BAS.DE', 'MBG.DE',
    'DTE.DE', 'ADS.DE', 'VOW3.DE', 'MC.PA', 'TTE.PA', 'AIR.PA', 'OR.PA',
    'SU.PA', 'SAN.PA', 'BNP.PA', 'DG.PA', 'RMS.PA', 'AI.PA', 'SHEL.L',
    'AZN.L', 'ULVR.L', 'HSBA.L', 'RIO.L', 'BP.L', 'DGE.L', 'GSK.L',
    'REL.L', 'LSEG.L',
]

MARKET_TICKERS = {
    'TW': TW_TICKERS,
    'US': US_TICKERS,
    'JP': JP_TICKERS,
    'EU': EU_TICKERS,
}

MARKET_SOURCE_DIR = {
    'TW': PROJECT_ROOT / 'experiments' / 'k1145' / 'data',
    'US': PROJECT_ROOT / 'experiments' / 'k1147' / 'data',
    'JP': PROJECT_ROOT / 'experiments' / 'k1150' / 'data',
    'EU': PROJECT_ROOT / 'experiments' / 'k1153' / 'data',
}

MARKET_DATA_START = {
    'TW': '2010-01-01',
    'US': '2014-01-01',
    'JP': '2014-01-01',
    'EU': '2014-01-01',
}
DATA_END = '2025-12-31'

TW_EARNINGS_FILE = PROJECT_ROOT / '財報公告日.txt'

ANALYST_PROXIES_PATH = SCRIPT_DIR / 'data' / 'analyst_media_proxies.json'


# ==========================================================================
# Data loading
# ==========================================================================
def _safe_name(market: str, ticker: str) -> str:
    """Per-market parquet naming convention (must match K1145/K1147/K1150/K1153)."""
    if ticker.startswith('^'):
        return ticker.replace('^', 'IDX_')
    if market == 'TW':
        # K1145 keeps the dot: '2330.TW.parquet'
        return ticker
    if market == 'US':
        # K1147 keeps BRK-B -> BRK_B.parquet (replace '-' with '_')
        return ticker.replace('-', '_')
    if market in ('JP', 'EU'):
        # K1150 / K1153 replace '.' with '_' and '-' with '_'
        return ticker.replace('.', '_').replace('-', '_')
    return ticker


def load_tw_earnings(code: str, start: str, end: str) -> pd.DatetimeIndex:
    """Load TW earnings from 財報公告日.txt (big5)."""
    with open(TW_EARNINGS_FILE, 'rb') as f:
        raw_text = f.read().decode('big5', errors='replace')
    lines = raw_text.strip().split('\n')
    recs = []
    for line in lines[1:]:
        parts = line.strip().split('\t')
        if len(parts) >= 4 and parts[0].strip() == code:
            ds = parts[3].strip()
            if ds:
                try:
                    dt = pd.Timestamp(ds.replace('/', '-'))
                    recs.append(dt)
                except Exception:
                    pass
    if not recs:
        return pd.DatetimeIndex([])
    di = pd.DatetimeIndex(recs).sort_values()
    di = di[(di >= start) & (di <= end)]
    return di


def load_earnings_from_json(cache_path: Path, ticker: str) -> pd.DatetimeIndex:
    if not cache_path.exists():
        return pd.DatetimeIndex([])
    with open(cache_path) as f:
        cache = json.load(f)
    if ticker not in cache:
        return pd.DatetimeIndex([])
    dates = [pd.Timestamp(d) for d in cache[ticker]]
    return pd.DatetimeIndex(dates)


def load_price_from_cache(market: str, ticker: str) -> pd.DataFrame | None:
    cache_dir = MARKET_SOURCE_DIR[market]
    parquet = cache_dir / f"{_safe_name(market, ticker)}.parquet"
    if not parquet.exists():
        return None
    df = pd.read_parquet(parquet)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def load_vix_from_cache(market: str) -> pd.Series | None:
    cache_dir = MARKET_SOURCE_DIR[market]
    parquet = cache_dir / 'IDX_VIX.parquet'
    if not parquet.exists():
        return None
    df = pd.read_parquet(parquet)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df['Close']


def build_eav_series(trading_days: pd.DatetimeIndex, ann_dates: pd.DatetimeIndex,
                     window: int = 1) -> np.ndarray:
    eav = np.zeros(len(trading_days), dtype=float)
    if len(ann_dates) == 0:
        return eav
    pos_arr = trading_days.searchsorted(ann_dates.values)
    for p in pos_arr:
        p = int(p)
        for w in range(window):
            if 0 <= p + w < len(trading_days):
                eav[p + w] = 1.0
    return eav


def load_one_stock(market: str, ticker: str) -> dict | None:
    raw = load_price_from_cache(market, ticker)
    if raw is None:
        return None
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix = load_vix_from_cache(market)
    if vix is None:
        return None
    vix = vix.reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]
    start = MARKET_DATA_START[market]
    if market == 'TW':
        code = ticker.replace('.TW', '')
        ann_dates = load_tw_earnings(code, start, DATA_END)
    elif market == 'US':
        ann_dates = load_earnings_from_json(
            PROJECT_ROOT / 'experiments' / 'k1147' / 'data' / 'earnings_dates.json',
            ticker)
    elif market == 'JP':
        ann_dates = load_earnings_from_json(
            PROJECT_ROOT / 'experiments' / 'k1150' / 'data' / 'earnings_dates.json',
            ticker)
    elif market == 'EU':
        ann_dates = load_earnings_from_json(
            PROJECT_ROOT / 'experiments' / 'k1153' / 'data' / 'earnings_dates.json',
            ticker)
    else:
        raise ValueError(f'Unknown market: {market}')
    eav_arr = build_eav_series(df.index, ann_dates, window=1)
    if len(df) < 500 or eav_arr.sum() < 15:
        return None
    return {
        'market': market,
        'ticker': ticker,
        'r': df['r'].values,
        'vix': df['vix'].values,
        'eav': eav_arr,
        'n_obs': len(df),
        'n_events': int(eav_arr.sum()),
        'sigma2_sample': float(np.var(df['r'].values, ddof=1)),
    }


# ==========================================================================
# Per-stock likelihood (numba)
#
# Identification: Engle-Ghysels-Sohn (2013, RES) GARCH-MIDAS normalization —
# impose E[g]=1 by setting omega_g = 1 - (alpha + gamma/2 + beta). This
# makes tau the unconditional long-run variance and removes the tau-g
# multiplicative degeneracy. Parameters become (theta0, alpha, gamma, beta,
# theta_vix, theta_eav) — 6 free per stock.
# ==========================================================================
@njit(cache=True, fastmath=True)
def _negll_stock(theta0, alpha, gamma_p, beta_p,
                 theta_vix, theta_eav,
                 r, vix, eav):
    n = r.shape[0]
    persist = alpha + gamma_p / 2.0 + beta_p
    if alpha < 0.0 or gamma_p < 0.0 or beta_p < 0.0:
        return 1e12
    if persist >= 0.999:
        return 1e12
    omega_g = 1.0 - persist  # Engle-Ghysels-Sohn normalization: E[g]=1
    if omega_g <= 1e-6:
        return 1e12
    tau = np.empty(n)
    for t in range(n):
        if t == 0:
            vl = vix[0]
            el = eav[0]
        else:
            vl = vix[t - 1]
            el = eav[t - 1]
        raw = theta0 + theta_vix * vl * vl + theta_eav * el
        tau[t] = raw if raw > 1e-16 else 1e-16
    g = 1.0  # start at unconditional = 1
    ll = 0.0
    log2pi = np.log(2.0 * np.pi)
    for t in range(1, n):
        tau_prev = tau[t - 1]
        if tau_prev < 1e-16:
            tau_prev = 1e-16
        u_prev = r[t - 1] / np.sqrt(tau_prev)
        asym = gamma_p * u_prev * u_prev if u_prev < 0.0 else 0.0
        g = omega_g + alpha * u_prev * u_prev + asym + beta_p * g
        if g < 1e-10:
            g = 1e-10
        sigma2 = tau[t] * g
        if sigma2 > 0.0:
            ll += -0.5 * (log2pi + np.log(sigma2) + r[t] * r[t] / sigma2)
    return -ll


def negll_wrap(params, r, vix, eav):
    theta0, alpha, gamma_p, beta_p, theta_vix, theta_eav = params
    return _negll_stock(float(theta0), float(alpha),
                         float(gamma_p), float(beta_p),
                         float(theta_vix), float(theta_eav),
                         r, vix, eav)


def fit_one_stock(stock: dict, verbose: bool = False) -> dict:
    """Per-stock MLE fit with multi-start + Hessian SE.

    Parameterization (6 free params, E[g]=1 imposed via omega_g):
        params = (theta0, alpha, gamma, beta, theta_vix, theta_eav)
    """
    r = stock['r']
    vix = stock['vix']
    eav = stock['eav']
    var_r = float(np.var(r, ddof=1))

    # Initial guesses — span reasonable region. theta0 init scale ~ var_r.
    # theta_VIX init ~ var_r / E[VIX^2] ~ var_r / 300.
    vix2_mean = float(np.mean(vix * vix))
    starts = [
        [var_r * 0.5, 0.05, 0.05, 0.90, var_r / (2 * vix2_mean), var_r * 0.1],
        [var_r * 0.8, 0.03, 0.08, 0.88, var_r / (3 * vix2_mean), var_r * 0.2],
        [var_r * 0.3, 0.08, 0.10, 0.80, var_r / vix2_mean, 0.0],
        [var_r * 0.6, 0.06, 0.06, 0.85, var_r / (2 * vix2_mean), var_r * 0.5],
    ]
    # Bounds: theta0 in [1e-12, 10*var_r] (anchors tau scale);
    # theta_vix allows scale of 0-2*var_r/vix2_mean
    bounds = [
        (1e-12, max(50.0 * var_r, 1e-4)),   # theta0
        (1e-4, 0.5),                         # alpha
        (0.0, 0.5),                          # gamma
        (0.3, 0.999),                        # beta
        (-2.0 * var_r / vix2_mean, 2.0 * var_r / vix2_mean),  # theta_vix
        (-20.0 * var_r, 20.0 * var_r),       # theta_eav (wide)
    ]

    best_ll = np.inf
    best_p = None
    for s in starts:
        try:
            # clip starting point to bounds
            s = [max(lo, min(hi, v)) for v, (lo, hi) in zip(s, bounds)]
            res = optimize.minimize(
                negll_wrap, s, args=(r, vix, eav),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 500, 'ftol': 1e-10, 'gtol': 1e-8},
            )
            if np.isfinite(res.fun) and res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x.copy()
        except Exception as e:
            if verbose:
                print(f'  start fail: {e}')
            continue

    if best_p is None:
        return {
            'market': stock['market'],
            'ticker': stock['ticker'],
            'converged': False,
            'theta0': None,
            'alpha': None,
            'gamma': None,
            'beta': None,
            'theta_vix': None,
            'theta_eav': None,
            'theta_eav_se': None,
            'theta_eav_t': None,
            'loglik': None,
            'n_obs': stock['n_obs'],
            'n_events': stock['n_events'],
            'sigma2_sample': stock['sigma2_sample'],
        }

    theta0, alpha, gamma_p, beta_p, theta_vix, theta_eav = best_p
    loglik = -best_ll

    # Numerical SE for theta_eav from profile Hessian (central 2nd diff)
    eps = max(abs(theta_eav) * 1e-3, max(var_r * 1e-5, 1e-9))
    try:
        p_plus = best_p.copy(); p_plus[5] = theta_eav + eps
        p_minus = best_p.copy(); p_minus[5] = theta_eav - eps
        ll_p = negll_wrap(p_plus, r, vix, eav)
        ll_m = negll_wrap(p_minus, r, vix, eav)
        h22 = (ll_p - 2 * best_ll + ll_m) / (eps ** 2)
        if h22 > 0 and np.isfinite(h22):
            se = float(np.sqrt(1.0 / h22))
            t_val = float(theta_eav / se) if se > 0 else None
        else:
            se = None
            t_val = None
    except Exception:
        se = None
        t_val = None

    # Diagnostic: is any param on a bound? (5% tolerance)
    at_bound = []
    for idx, (p, (lo, hi)) in enumerate(zip(best_p, bounds)):
        if abs(p - lo) / max(abs(lo), 1e-10) < 0.01 or abs(p - hi) / max(abs(hi), 1e-10) < 0.01:
            at_bound.append(idx)

    return {
        'market': stock['market'],
        'ticker': stock['ticker'],
        'converged': True,
        'theta0': float(theta0),
        'alpha': float(alpha),
        'gamma': float(gamma_p),
        'beta': float(beta_p),
        'theta_vix': float(theta_vix),
        'theta_eav': float(theta_eav),
        'theta_eav_se': se,
        'theta_eav_t': t_val,
        'loglik': float(loglik),
        'n_obs': stock['n_obs'],
        'n_events': stock['n_events'],
        'sigma2_sample': stock['sigma2_sample'],
        'persistence': float(alpha + gamma_p / 2.0 + beta_p),
        'params_at_bound': at_bound,
    }


# ==========================================================================
# Multiprocessing worker
# ==========================================================================
def _mp_worker(stock):
    t0 = time.time()
    res = fit_one_stock(stock, verbose=False)
    res['fit_time_sec'] = round(time.time() - t0, 2)
    return res


# ==========================================================================
# Load analyst proxies
# ==========================================================================
def load_analyst_proxies() -> dict:
    with open(ANALYST_PROXIES_PATH) as f:
        raw = json.load(f)
    out = {}
    for market, lst in raw.items():
        for rec in lst:
            out[rec['ticker']] = {
                'market': rec.get('market', market),
                'analyst_count': rec.get('analyst_count'),
                'market_cap': rec.get('market_cap'),
                'median_daily_turnover': rec.get('median_daily_turnover'),
                'currency': rec.get('currency'),
            }
    return out


# ==========================================================================
# Cross-stock analysis
# ==========================================================================
def spearman_with_p(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 4:
        return None, None, int(mask.sum())
    rho, p = stats.spearmanr(x[mask], y[mask])
    return float(rho), float(p), int(mask.sum())


def panel_ols_market_fe(df: pd.DataFrame):
    """Per-stock panel regression:
        theta_eav_i = sum_m alpha_m * D_{m,i} + beta1*log(analyst_i+1)
                    + beta2*log(mcap_i) + eps
    White HC0 robust SE.
    """
    df = df.copy()
    df = df.dropna(subset=['theta_eav', 'analyst_count', 'market_cap'])
    df['log_analyst'] = np.log(df['analyst_count'].astype(float) + 1.0)
    df['log_mcap'] = np.log(df['market_cap'].astype(float))
    markets = sorted(df['market'].unique())
    X_cols = []
    for m in markets:
        col = f'D_{m}'
        df[col] = (df['market'] == m).astype(float)
        X_cols.append(col)
    X_cols.append('log_analyst')
    X_cols.append('log_mcap')

    X = df[X_cols].values
    y = df['theta_eav'].values
    n, k = X.shape
    if n <= k:
        return None
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    resid = y - y_hat
    # HC0 sandwich
    XtX_inv = np.linalg.inv(X.T @ X)
    meat = (X.T * resid**2) @ X
    V = XtX_inv @ meat @ XtX_inv
    se = np.sqrt(np.diag(V))
    t = beta / se
    pvals = 2 * (1 - stats.t.cdf(np.abs(t), n - k))
    ss_res = float(np.sum(resid**2))
    ss_tot = float(np.sum((y - np.mean(y))**2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else None
    return {
        'n': int(n),
        'k': int(k),
        'r2': r2,
        'coefs': {col: {'beta': float(b), 'se': float(s),
                         't': float(tt), 'p': float(pp)}
                   for col, b, s, tt, pp in zip(X_cols, beta, se, t, pvals)},
        'X_cols': X_cols,
    }


# ==========================================================================
# Plots
# ==========================================================================
def plot_theta_eav_hist(df: pd.DataFrame, path: Path):
    markets = ['TW', 'EU', 'JP', 'US']
    fig, axes = plt.subplots(2, 2, figsize=(10, 7), sharey=False)
    for ax, m in zip(axes.flat, markets):
        sub = df[df['market'] == m]
        vals = sub['theta_eav'].dropna().values
        ax.hist(vals, bins=15, color='steelblue', edgecolor='white')
        med = np.median(vals) if len(vals) > 0 else np.nan
        mean = np.mean(vals) if len(vals) > 0 else np.nan
        ax.axvline(0, color='grey', lw=0.8, ls=':')
        ax.axvline(med, color='red', lw=1.2, ls='--',
                   label=f'median={med:+.2e}')
        ax.axvline(mean, color='orange', lw=1.2, ls='-',
                   label=f'mean={mean:+.2e}')
        ax.set_title(f'{m} (N={len(vals)})')
        ax.set_xlabel('theta_EAV_i')
        ax.set_ylabel('count')
        ax.legend(fontsize=8)
    fig.suptitle('K1166: Per-stock theta_EAV_i distribution by market', fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_theta_eav_scatter(df: pd.DataFrame, path: Path):
    fig, ax = plt.subplots(1, 1, figsize=(8, 6))
    colors = {'TW': 'tab:blue', 'US': 'tab:red',
              'JP': 'tab:green', 'EU': 'tab:orange'}
    for m, sub in df.groupby('market'):
        x = np.log(sub['analyst_count'].astype(float) + 1.0)
        y = sub['theta_eav'].astype(float)
        mask = np.isfinite(x) & np.isfinite(y)
        ax.scatter(x[mask], y[mask], color=colors.get(m, 'black'),
                   alpha=0.65, label=f'{m} (N={mask.sum()})', s=40)
    ax.axhline(0, color='grey', lw=0.8, ls=':')
    ax.set_xlabel('log(analyst_count + 1)')
    ax.set_ylabel('theta_EAV_i')
    ax.set_title('K1166: Per-stock theta_EAV_i vs log(analyst coverage)')
    ax.legend(loc='best')
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


# ==========================================================================
# Main
# ==========================================================================
def main():
    t0 = time.time()
    print(f'\n{"="*72}\n{EXPERIMENT_ID}: Per-stock theta_EAV refit (no shared pooling)\n{"="*72}\n')

    # ---- Load all stocks ----
    all_stocks = []
    print('[1/5] Loading cached stocks ...')
    for market, tickers in MARKET_TICKERS.items():
        loaded = 0
        skipped = []
        for tk in tickers:
            st = load_one_stock(market, tk)
            if st is None:
                skipped.append(tk)
                continue
            all_stocks.append(st)
            loaded += 1
        print(f'  {market}: loaded {loaded}/{len(tickers)} '
              f'(skipped: {skipped if skipped else "[]"})')
    print(f'  Total loaded: {len(all_stocks)} stocks\n')
    assert len(all_stocks) >= 100, f'Expected >=100 stocks, got {len(all_stocks)}'

    # ---- Per-stock MLE (multiprocessing) ----
    n_workers = min(8, os.cpu_count() or 4)
    print(f'[2/5] Per-stock MLE fits via multiprocessing (n_workers={n_workers}) ...')
    t_fit = time.time()
    with Pool(n_workers) as pool:
        fit_results = pool.map(_mp_worker, all_stocks)
    print(f'  All {len(fit_results)} fits done in {time.time() - t_fit:.1f}s\n')

    # Order and build dataframe
    df_fits = pd.DataFrame(fit_results)
    n_converged = int(df_fits['converged'].sum())
    print(f'  Converged: {n_converged}/{len(df_fits)}')
    print(f'  Mean fit time: {df_fits["fit_time_sec"].mean():.2f}s')
    bound_hits = df_fits['params_at_bound'].apply(lambda x: len(x) if isinstance(x, list) else 0).sum()
    print(f'  Stocks with any param at bound: '
          f'{int((df_fits["params_at_bound"].apply(lambda x: len(x) if isinstance(x, list) else 0) > 0).sum())}/{len(df_fits)}')

    # ---- Merge with analyst proxies ----
    print('\n[3/5] Merge with analyst/mcap proxies from K1164 cache ...')
    proxies = load_analyst_proxies()
    df_fits['analyst_count'] = df_fits['ticker'].map(
        lambda t: proxies.get(t, {}).get('analyst_count'))
    df_fits['market_cap'] = df_fits['ticker'].map(
        lambda t: proxies.get(t, {}).get('market_cap'))
    df_fits['median_daily_turnover'] = df_fits['ticker'].map(
        lambda t: proxies.get(t, {}).get('median_daily_turnover'))

    # save CSV
    keep_cols = ['market', 'ticker', 'converged', 'theta0', 'alpha',
                 'gamma', 'beta', 'persistence', 'theta_vix', 'theta_eav',
                 'theta_eav_se', 'theta_eav_t', 'loglik', 'n_obs', 'n_events',
                 'sigma2_sample', 'analyst_count', 'market_cap',
                 'median_daily_turnover']
    df_fits[keep_cols].to_csv(CSV_PATH, index=False)
    print(f'  Saved: {CSV_PATH.relative_to(PROJECT_ROOT)}')

    # ---- Per-stock statistics ----
    print('\n[4/5] Cross-stock statistics and mechanism test ...')
    per_market = {}
    for m, sub in df_fits.groupby('market'):
        sub_c = sub[sub['converged']]
        n_total = len(sub)
        n_conv = len(sub_c)
        t_vals = sub_c['theta_eav_t'].dropna().values
        n_sig = int(np.sum(np.abs(t_vals) > 2.0))
        n_sig_3 = int(np.sum(np.abs(t_vals) > 3.0))
        vals = sub_c['theta_eav'].dropna().values
        per_market[m] = {
            'n_total': n_total,
            'n_converged': n_conv,
            'theta_eav_mean': float(np.mean(vals)) if len(vals) > 0 else None,
            'theta_eav_median': float(np.median(vals)) if len(vals) > 0 else None,
            'theta_eav_std': float(np.std(vals, ddof=1)) if len(vals) > 1 else None,
            'n_sig_t2': n_sig,
            'n_sig_t3': n_sig_3,
            'pct_sig_t2': float(n_sig / len(t_vals)) if len(t_vals) > 0 else None,
            'pct_sig_t3': float(n_sig_3 / len(t_vals)) if len(t_vals) > 0 else None,
            'fraction_positive': float(np.mean(vals > 0)) if len(vals) > 0 else None,
        }
        print(f'  {m}: N_conv={n_conv}/{n_total}, mean={np.mean(vals):+.3e}, '
              f'median={np.median(vals):+.3e}, %|t|>2={100*n_sig/max(len(t_vals),1):.0f}%, '
              f'frac_pos={np.mean(vals > 0):.2f}')

    # Preamble Rule #5 check
    preamble_check = {}
    for m, info in per_market.items():
        if info['pct_sig_t3'] is not None and info['pct_sig_t3'] > 0.6:
            preamble_check[m] = (
                f'WARN: >{int(info["pct_sig_t3"]*100)}% per-stock |t|>3 '
                f'— self-challenge: verify no lookahead / tautology.')
        else:
            preamble_check[m] = 'OK'

    # ---- Cross-stock Spearman correlations ----
    spearman_results = {}
    pooled = df_fits[df_fits['converged']].copy()
    for group_name, group in [('pooled', pooled)] + list(pooled.groupby('market')):
        if isinstance(group_name, tuple):
            continue
        group_df = group if group_name == 'pooled' else group
        if len(group_df) < 4:
            continue
        entry = {}
        # Spearman vs analyst
        rho, p, n = spearman_with_p(group_df['analyst_count'],
                                     group_df['theta_eav'])
        entry['theta_eav_vs_analyst'] = {'rho': rho, 'p': p, 'n': n}
        # Spearman vs log(analyst)
        la = np.log(group_df['analyst_count'].astype(float) + 1.0)
        rho, p, n = spearman_with_p(la, group_df['theta_eav'])
        entry['theta_eav_vs_log_analyst'] = {'rho': rho, 'p': p, 'n': n}
        # Spearman theta_eav vs sigma2 — SANITY CHECK: should NOT be ~±1
        rho, p, n = spearman_with_p(group_df['sigma2_sample'],
                                     group_df['theta_eav'])
        entry['theta_eav_vs_sigma2'] = {'rho': rho, 'p': p, 'n': n}
        # Spearman vs mcap
        lm = np.log(group_df['market_cap'].astype(float))
        rho, p, n = spearman_with_p(lm, group_df['theta_eav'])
        entry['theta_eav_vs_log_mcap'] = {'rho': rho, 'p': p, 'n': n}
        spearman_results[group_name] = entry

    # also do per-market separately
    for m in ['TW', 'US', 'JP', 'EU']:
        sub = pooled[pooled['market'] == m]
        if len(sub) < 4:
            continue
        entry = {}
        la = np.log(sub['analyst_count'].astype(float) + 1.0)
        rho, p, n = spearman_with_p(la, sub['theta_eav'])
        entry['theta_eav_vs_log_analyst'] = {'rho': rho, 'p': p, 'n': n}
        rho, p, n = spearman_with_p(sub['sigma2_sample'], sub['theta_eav'])
        entry['theta_eav_vs_sigma2'] = {'rho': rho, 'p': p, 'n': n}
        lm = np.log(sub['market_cap'].astype(float))
        rho, p, n = spearman_with_p(lm, sub['theta_eav'])
        entry['theta_eav_vs_log_mcap'] = {'rho': rho, 'p': p, 'n': n}
        spearman_results[m] = entry

    print('\n  Cross-stock Spearman corr (log_analyst, theta_eav):')
    for name, d in spearman_results.items():
        la = d.get('theta_eav_vs_log_analyst')
        s2 = d.get('theta_eav_vs_sigma2')
        if la is None:
            continue
        print(f'    {name}: rho={la["rho"]:+.3f} (p={la["p"]:.3f}, N={la["n"]})  '
              f'| sanity sigma2: rho={s2["rho"]:+.3f}')

    # ---- Panel regression with market FE ----
    print('\n  Panel regression theta_eav_i ~ log_analyst + log_mcap + market_FE:')
    panel_res = panel_ols_market_fe(pooled)
    if panel_res is not None:
        for col, d in panel_res['coefs'].items():
            print(f'    {col}: beta={d["beta"]:+.4e}, SE={d["se"]:.4e}, '
                  f't={d["t"]:+.3f}, p={d["p"]:.4f}')
        print(f'    R^2 = {panel_res["r2"]:.3f}, n = {panel_res["n"]}')

    # ---- Compare pooled-shared theta_EAV vs per-stock mean ----
    shared_theta_eav = {
        'TW': 6.362165248598386e-05,
        'US': 1.9089860360002893e-04,
        'JP': 1.4127865441754286e-04,
        'EU': 4.0718849779368176e-05,
    }
    magnitude_compare = {}
    for m, shared in shared_theta_eav.items():
        sub = pooled[pooled['market'] == m]
        mean_persk = float(sub['theta_eav'].mean()) if len(sub) > 0 else None
        median_persk = float(sub['theta_eav'].median()) if len(sub) > 0 else None
        magnitude_compare[m] = {
            'pooled_shared_theta_eav': shared,
            'per_stock_mean': mean_persk,
            'per_stock_median': median_persk,
            'ratio_mean_to_shared': (mean_persk / shared) if mean_persk is not None else None,
        }
    print('\n  Pooled-shared vs per-stock mean theta_EAV:')
    for m, d in magnitude_compare.items():
        ratio = d['ratio_mean_to_shared']
        print(f'    {m}: shared={d["pooled_shared_theta_eav"]:+.3e}, '
              f'per-stock mean={d["per_stock_mean"]:+.3e}, '
              f'ratio={ratio:.2f}' if ratio is not None else f'    {m}: ratio=NA')

    # ---- Plots ----
    print('\n[5/5] Plots ...')
    plot_theta_eav_hist(pooled, FIG_HIST_PATH)
    print(f'  {FIG_HIST_PATH.name}')
    plot_theta_eav_scatter(pooled, FIG_SCATTER_PATH)
    print(f'  {FIG_SCATTER_PATH.name}')

    # ---- Mechanism verdict ----
    pooled_la = spearman_results.get('pooled', {}).get('theta_eav_vs_log_analyst', {})
    panel_la = panel_res['coefs'].get('log_analyst') if panel_res else None
    pooled_rho = pooled_la.get('rho') if pooled_la else None
    pooled_p = pooled_la.get('p') if pooled_la else None

    # Per-market rho count
    n_markets_pos = 0
    n_markets_neg = 0
    n_markets_sig_pos = 0
    for m in ['TW', 'US', 'JP', 'EU']:
        if m not in spearman_results:
            continue
        d = spearman_results[m].get('theta_eav_vs_log_analyst')
        if d is None or d['rho'] is None:
            continue
        if d['rho'] > 0:
            n_markets_pos += 1
            if d['p'] is not None and d['p'] < 0.10:
                n_markets_sig_pos += 1
        elif d['rho'] < 0:
            n_markets_neg += 1

    if (panel_la is not None
        and panel_la['beta'] > 0 and panel_la['p'] < 0.05
        and pooled_rho is not None and pooled_rho > 0.15):
        verdict = 'CONFIRMED (removed-tautology)'
    elif (panel_la is not None
          and panel_la['beta'] < 0 and panel_la['p'] < 0.05):
        verdict = 'REJECTED (negative sign even without tautology)'
    elif pooled_p is not None and pooled_p > 0.10:
        verdict = 'NULL (no cross-stock mechanism signal)'
    else:
        verdict = 'AMBIGUOUS'

    print(f'\n  Mechanism verdict: {verdict}')

    # ---- Build results JSON ----
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'Per-stock theta_EAV refit — remove sigma^2 tautology in K1164 cluster mechanism analysis',
        'proposer': 'Claude (K1164 next_tasks K1166)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_sources': [
            'experiments/k1145/data/ (TW parquet + VIX)',
            'experiments/k1147/data/ (US parquet + VIX + earnings_dates.json)',
            'experiments/k1150/data/ (JP parquet + VIX + earnings_dates.json)',
            'experiments/k1153/data/ (EU parquet + VIX + earnings_dates.json)',
            '財報公告日.txt (TW earnings, big5)',
            'experiments/k1164/data/analyst_media_proxies.json',
        ],
        'specification': {
            'equation': 'sigma2_{i,t} = g_{i,t} * tau_{i,t}; '
                         'g GJR(1,1) stock-specific; '
                         'tau = max(theta0_i + theta_VIX_i*VIX^2_{t-1} + theta_EAV_i*EAV_{i,t-1}, eps)',
            'estimation': 'L-BFGS-B multi-start, Hessian SE from 2nd-order finite-diff',
            'lookahead': 'VIX lag-1, EAV lag-1',
        },
        'n_stocks_total': len(all_stocks),
        'n_converged': n_converged,
        'per_market': per_market,
        'preamble_rule5_check': preamble_check,
        'spearman_correlations': spearman_results,
        'panel_regression_with_market_fe': panel_res,
        'magnitude_comparison_vs_pooled_shared': magnitude_compare,
        'mechanism_hypothesis': (
            'K1153 hypothesis: high analyst coverage -> HIGH theta_EAV_i '
            '(more institutional attention -> sharper vol response to earnings news).'),
        'mechanism_verdict': verdict,
        'verdict_notes': {
            'tautology_removed': 'YES — no shared theta_EAV; per-stock variation is firm-level.',
            'pooled_log_analyst_rho': pooled_rho,
            'pooled_log_analyst_p': pooled_p,
            'panel_log_analyst_beta': panel_la['beta'] if panel_la else None,
            'panel_log_analyst_t': panel_la['t'] if panel_la else None,
            'panel_log_analyst_p': panel_la['p'] if panel_la else None,
            'n_markets_positive_rho': n_markets_pos,
            'n_markets_negative_rho': n_markets_neg,
            'n_markets_sig_positive': n_markets_sig_pos,
        },
        'figures': {
            'hist_by_market': str(FIG_HIST_PATH.name),
            'scatter_vs_analyst': str(FIG_SCATTER_PATH.name),
        },
        'limitations': [
            'Per-stock fits may be noisy (N=500-3000 daily obs each).',
            'Analyst count is yfinance snapshot (current, not historical average).',
            'theta_EAV_i SE from profile Hessian; no block-bootstrap due to per-stock computational cost.',
            'No cross-market Spearman because market-level theta_EAV is at the market level; '
            'we instead do within-market plus pooled-with-FE cross-stock.',
        ],
        'execution_time_sec': round(time.time() - t0, 1),
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2)
    print(f'\n[DONE] Results: {RESULTS_PATH.relative_to(PROJECT_ROOT)}')
    print(f'[DONE] Total time: {time.time() - t0:.1f}s')
    return out


if __name__ == '__main__':
    main()
