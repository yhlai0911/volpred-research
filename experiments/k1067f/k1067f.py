#!/usr/bin/env python3
"""
K1067f: VIX-only ablation — reverse sanity check of K1067e.

[提出: Claude (follow-up to K1067e EAV-only ablation), 執行: Claude]

Motivation
----------
K1067e showed that dropping VIX from the full A4f-EAV spec keeps theta_EAV_i
stable (rho=+0.898, sign consistency 96.4%, panel log_analyst beta=+1.17e-3
t=+3.68). Verdict H3 borderline H1. EAV is an independent signal.

K1067f is the **reverse** ablation: keep VIX, drop EAV.
    tau_{i,t} = max(theta0_i + theta_VIX_i * VIX^2_{t-1}, eps)  (NO EAV)

Question: if we fit the noEAV spec per-stock, does theta_VIX_i remain
stable relative to theta_VIX_i_full (from K1166)?  Paper 2 claims the full
spec has two independent long-run channels (VIX = global climate,
EAV = firm-specific earnings). The reverse ablation tests the VIX channel.

Specification (per stock i)
---------------------------
    sigma2_{i,t} = g_{i,t} * tau_{i,t}
    g_{i,t} ~ GJR(1,1)_i        # stock-specific alpha, gamma, beta
                                  # omega_g = 1 - (alpha + gamma/2 + beta)  (EGS E[g]=1)
    tau_{i,t} = max(theta0_i + theta_VIX_i * VIX^2_{t-1}, eps)
                                  # NO EAV term

5 free params per stock: (theta0_i, alpha_i, gamma_i, beta_i, theta_VIX_i).

Hypotheses
----------
- H1 (VIX independent): theta_VIX_noEAV approximately equals theta_VIX_full
  (rho > +0.9, sign agreement > 90%, panel log_analyst same sign similar t).
- H2 (EAV was carrying VIX): theta_VIX_noEAV swings wildly or flips sign
  for many stocks, or the cross-sectional structure collapses.
- H3 (minor collinearity): rho in [0.5, 0.9], magnitudes shift ~10-20%.

Given K1067e verdict (EAV independent of VIX), we expect H1 / H3 borderline,
NOT H2 (VIX is a continuous strongly-autocorrelated regressor; EAV is a
sparse 0/1 flag — sparse flags rarely absorb much of a continuous regressor).

Lookahead discipline
--------------------
- VIX enters at lag t-1 (set inside numba likelihood).
- All random seeds = 42.

Reuse from K1067e / K1166
-------------------------
- Same 110 stocks (same filters, same window).
- Same cached parquet + VIX.
- Same analyst/mcap proxies.
- Load K1166's per-stock full-spec fits from data/k1166_per_stock_table.csv
  for direct theta_VIX_full comparison and LR test (nested: theta_EAV = 0
  under noEAV).

Analysis steps
--------------
1. Per-stock fit of the VIX-only spec.
2. Scatter theta_VIX_i_noEAV vs theta_VIX_i_full (K1166 cache).
3. Cross-stock Spearman / Pearson correlation of the two estimates.
4. Sign consistency %.
5. Per-stock LR stat: 2*(LL_full - LL_noEAV) ~ chi2(1).
6. Panel regression theta_VIX_i_noEAV ~ log(analyst) + log(mcap) + market FE
   (HC0 SE). Compare with K1067e panel (which worked on theta_EAV).
7. Cross-stock Spearman rho(log_analyst, theta_VIX_i_noEAV) pooled + per-market.

Verdict decision tree
---------------------
- H1: rho(noEAV, full) > +0.9 AND sign consistency > 90%.
- H2: rho(noEAV, full) < +0.5 OR >30% sign flips.
- H3: otherwise.

References
----------
- Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3), 776-797.
- K1166 (full spec), K1067e (EAV-only ablation).
- Harvey, Liu & Zhu (2016). RFS 29(1), 5-68.

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

EXPERIMENT_ID = 'K1067f'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
RESULTS_PATH = SCRIPT_DIR / 'k1067f_results.json'
CSV_PATH = SCRIPT_DIR / 'k1067f_per_stock_comparison.csv'
FIG_SCATTER_PATH = SCRIPT_DIR / 'k1067f_scatter_noEAV_vs_full.png'
FIG_SIGN_PATH = SCRIPT_DIR / 'k1067f_sign_consistency_hist.png'

MAIN_PROJECT_ROOT = Path('/Users/yhlai0911/Desktop/volpred-research')


def find_experiment_data_dir(rel: str) -> Path:
    """Find first existing experiments/kXXX/data path across worktree + main."""
    for base in (PROJECT_ROOT, MAIN_PROJECT_ROOT):
        p = base / rel
        if p.exists():
            return p
    return MAIN_PROJECT_ROOT / rel


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
    'TW': find_experiment_data_dir('experiments/k1145/data'),
    'US': find_experiment_data_dir('experiments/k1147/data'),
    'JP': find_experiment_data_dir('experiments/k1150/data'),
    'EU': find_experiment_data_dir('experiments/k1153/data'),
}

MARKET_DATA_START = {
    'TW': '2010-01-01',
    'US': '2014-01-01',
    'JP': '2014-01-01',
    'EU': '2014-01-01',
}
DATA_END = '2025-12-31'


def _find_first(path_rel: str) -> Path:
    for base in (PROJECT_ROOT, MAIN_PROJECT_ROOT):
        p = base / path_rel
        if p.exists():
            return p
    return MAIN_PROJECT_ROOT / path_rel


TW_EARNINGS_FILE = _find_first('財報公告日.txt')
ANALYST_PROXIES_PATH = SCRIPT_DIR / 'data' / 'analyst_media_proxies.json'
K1166_TABLE_PATH = SCRIPT_DIR / 'data' / 'k1166_per_stock_table.csv'


# ==========================================================================
# Data loading (matches K1067e / K1166 for fidelity)
# ==========================================================================
def _safe_name(market: str, ticker: str) -> str:
    if ticker.startswith('^'):
        return ticker.replace('^', 'IDX_')
    if market == 'TW':
        return ticker
    if market == 'US':
        return ticker.replace('-', '_')
    if market in ('JP', 'EU'):
        return ticker.replace('.', '_').replace('-', '_')
    return ticker


def load_tw_earnings(code: str, start: str, end: str) -> pd.DatetimeIndex:
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
    """Kept for filtering (n_events >= 15 sample rule) but eav not entered
    into noEAV likelihood."""
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
            find_experiment_data_dir('experiments/k1147/data') / 'earnings_dates.json',
            ticker)
    elif market == 'JP':
        ann_dates = load_earnings_from_json(
            find_experiment_data_dir('experiments/k1150/data') / 'earnings_dates.json',
            ticker)
    elif market == 'EU':
        ann_dates = load_earnings_from_json(
            find_experiment_data_dir('experiments/k1153/data') / 'earnings_dates.json',
            ticker)
    else:
        raise ValueError(f'Unknown market: {market}')
    eav_arr = build_eav_series(df.index, ann_dates, window=1)
    # Apply same sample filter as K1166/K1067e: n_obs >= 500 and n_events >= 15.
    if len(df) < 500 or eav_arr.sum() < 15:
        return None
    # Note: vix^2 is what the model uses (MIDAS/EGS convention).
    # We store vix^2 (scaled: VIX is in percentage points).
    vix_vals = df['vix'].values
    return {
        'market': market,
        'ticker': ticker,
        'r': df['r'].values,
        # VIX enters directly as VIX^2 later; keep raw levels here
        'vix': vix_vals,
        'vix_sq': vix_vals ** 2,
        # eav kept only for filtering — not passed into likelihood
        'eav': eav_arr,
        'n_obs': len(df),
        'n_events': int(eav_arr.sum()),
        'sigma2_sample': float(np.var(df['r'].values, ddof=1)),
    }


# ==========================================================================
# Per-stock likelihood (numba) — VIX ONLY, NO EAV
# ==========================================================================
@njit(cache=True, fastmath=True)
def _negll_stock_noEAV(theta0, alpha, gamma_p, beta_p,
                        theta_vix,
                        r, vix_sq):
    n = r.shape[0]
    persist = alpha + gamma_p / 2.0 + beta_p
    if alpha < 0.0 or gamma_p < 0.0 or beta_p < 0.0:
        return 1e12
    if persist >= 0.999:
        return 1e12
    omega_g = 1.0 - persist  # EGS E[g]=1
    if omega_g <= 1e-6:
        return 1e12
    tau = np.empty(n)
    for t in range(n):
        if t == 0:
            vs = vix_sq[0]
        else:
            vs = vix_sq[t - 1]
        raw = theta0 + theta_vix * vs
        tau[t] = raw if raw > 1e-16 else 1e-16
    g = 1.0
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


def negll_wrap_noEAV(params, r, vix_sq):
    theta0, alpha, gamma_p, beta_p, theta_vix = params
    return _negll_stock_noEAV(float(theta0), float(alpha),
                               float(gamma_p), float(beta_p),
                               float(theta_vix),
                               r, vix_sq)


def fit_one_stock(stock: dict, verbose: bool = False) -> dict:
    """Per-stock MLE fit — VIX ONLY spec, multi-start + Hessian SE.

    Parameterization (5 free params, E[g]=1 imposed via omega_g):
        params = (theta0, alpha, gamma, beta, theta_vix)
    """
    r = stock['r']
    vix_sq = stock['vix_sq']
    var_r = float(np.var(r, ddof=1))
    # VIX^2 is in (percent)^2 units; a typical scale is 10-1000. theta_vix
    # maps VIX^2 to tau scale (~1e-4 daily variance). So theta_vix scale
    # ~ var_r / 400 ~ 1e-6 to 1e-7. K1166 full has median theta_vix ~5e-7.
    var_vix_sq = float(np.mean(vix_sq))
    scale_vix = var_r / max(var_vix_sq, 1e-6)

    # Starts: include a wide range.
    starts = [
        [var_r * 0.5, 0.05, 0.05, 0.90, scale_vix * 0.5],
        [var_r * 0.3, 0.03, 0.08, 0.88, scale_vix * 1.0],
        [var_r * 0.8, 0.08, 0.10, 0.80, scale_vix * 0.1],
        [var_r * 0.1, 0.06, 0.06, 0.85, scale_vix * 2.0],
    ]
    bounds = [
        (1e-12, max(50.0 * var_r, 1e-4)),        # theta0
        (1e-4, 0.5),                              # alpha
        (0.0, 0.5),                               # gamma
        (0.3, 0.999),                             # beta
        (-100.0 * scale_vix, 100.0 * scale_vix),  # theta_vix
    ]

    best_ll = np.inf
    best_p = None
    for s in starts:
        try:
            s = [max(lo, min(hi, v)) for v, (lo, hi) in zip(s, bounds)]
            res = optimize.minimize(
                negll_wrap_noEAV, s, args=(r, vix_sq),
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
            'theta_vix_noEAV': None,
            'theta_vix_noEAV_se': None,
            'theta_vix_noEAV_t': None,
            'loglik_noEAV': None,
            'n_obs': stock['n_obs'],
            'n_events': stock['n_events'],
            'sigma2_sample': stock['sigma2_sample'],
        }

    theta0, alpha, gamma_p, beta_p, theta_vix = best_p
    loglik = -best_ll

    # Hessian SE for theta_vix — index 4 in noEAV param vector.
    eps = max(abs(theta_vix) * 1e-3, max(scale_vix * 1e-5, 1e-11))
    try:
        p_plus = best_p.copy(); p_plus[4] = theta_vix + eps
        p_minus = best_p.copy(); p_minus[4] = theta_vix - eps
        ll_p = negll_wrap_noEAV(p_plus, r, vix_sq)
        ll_m = negll_wrap_noEAV(p_minus, r, vix_sq)
        h22 = (ll_p - 2 * best_ll + ll_m) / (eps ** 2)
        if h22 > 0 and np.isfinite(h22):
            se = float(np.sqrt(1.0 / h22))
            t_val = float(theta_vix / se) if se > 0 else None
        else:
            se = None
            t_val = None
    except Exception:
        se = None
        t_val = None

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
        'theta_vix_noEAV': float(theta_vix),
        'theta_vix_noEAV_se': se,
        'theta_vix_noEAV_t': t_val,
        'loglik_noEAV': float(loglik),
        'n_obs': stock['n_obs'],
        'n_events': stock['n_events'],
        'sigma2_sample': stock['sigma2_sample'],
        'persistence': float(alpha + gamma_p / 2.0 + beta_p),
        'params_at_bound': at_bound,
    }


def _mp_worker(stock):
    t0 = time.time()
    res = fit_one_stock(stock, verbose=False)
    res['fit_time_sec'] = round(time.time() - t0, 2)
    return res


# ==========================================================================
# Analysis helpers
# ==========================================================================
def spearman_with_p(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 4:
        return None, None, int(mask.sum())
    rho, p = stats.spearmanr(x[mask], y[mask])
    return float(rho), float(p), int(mask.sum())


def pearson_with_p(x, y):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = np.isfinite(x) & np.isfinite(y)
    if mask.sum() < 4:
        return None, None, int(mask.sum())
    r, p = stats.pearsonr(x[mask], y[mask])
    return float(r), float(p), int(mask.sum())


def panel_ols_market_fe(df: pd.DataFrame, y_col: str):
    df = df.copy()
    df = df.dropna(subset=[y_col, 'analyst_count', 'market_cap'])
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
    y = df[y_col].values
    n, k = X.shape
    if n <= k:
        return None
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    resid = y - y_hat
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
# Plots
# ==========================================================================
def plot_scatter_noEAV_vs_full(df: pd.DataFrame, path: Path, spearman_rho: float):
    fig, ax = plt.subplots(1, 1, figsize=(8, 7))
    colors = {'TW': 'tab:blue', 'US': 'tab:red',
              'JP': 'tab:green', 'EU': 'tab:orange'}
    x = df['theta_vix'].astype(float)          # full (from K1166)
    y = df['theta_vix_noEAV'].astype(float)
    mask_all = np.isfinite(x) & np.isfinite(y)
    xmin = min(float(x[mask_all].min()), float(y[mask_all].min()))
    xmax = max(float(x[mask_all].max()), float(y[mask_all].max()))
    lim_hi = max(abs(xmin), abs(xmax)) * 1.1
    lim_lo = -0.1 * lim_hi if xmin >= 0 else -lim_hi
    ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi],
             color='grey', ls='--', lw=0.8, label='y=x')
    ax.axhline(0, color='grey', lw=0.4, ls=':')
    ax.axvline(0, color='grey', lw=0.4, ls=':')
    for m, sub in df.groupby('market'):
        xx = sub['theta_vix'].astype(float)
        yy = sub['theta_vix_noEAV'].astype(float)
        mask = np.isfinite(xx) & np.isfinite(yy)
        ax.scatter(xx[mask], yy[mask], color=colors.get(m, 'black'),
                   alpha=0.7, label=f'{m} (N={mask.sum()})', s=45,
                   edgecolor='white', lw=0.4)
    ax.set_xlabel(r'$\theta_{VIX,i}$ (full: with EAV) — K1166')
    ax.set_ylabel(r'$\theta_{VIX,i}$ (noEAV: VIX only) — K1067f')
    title = (f'K1067f: Per-stock $\\theta_{{VIX}}$ — VIX-only vs VIX+EAV spec\n'
             f'Spearman $\\rho$ = {spearman_rho:+.3f} (N = {mask_all.sum()})')
    ax.set_title(title)
    ax.set_xlim(lim_lo, lim_hi)
    ax.set_ylim(lim_lo, lim_hi)
    ax.legend(loc='best', fontsize=9)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


def plot_sign_consistency_hist(df: pd.DataFrame, path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    # Left: histogram of ratio theta_noEAV / theta_full
    ratio = df['theta_vix_noEAV'] / df['theta_vix']
    ratio = ratio.replace([np.inf, -np.inf], np.nan).dropna()
    axes[0].hist(ratio.clip(-5, 5), bins=30, color='steelblue',
                 edgecolor='white')
    axes[0].axvline(1.0, color='red', ls='--', lw=1.0,
                     label='ratio = 1 (identity)')
    axes[0].axvline(0.0, color='grey', ls=':', lw=0.8)
    axes[0].set_xlabel(
        r'$\theta_{VIX,i,noEAV} / \theta_{VIX,i,full}$ (clipped $\pm 5$)')
    axes[0].set_ylabel('count')
    axes[0].set_title(f'Ratio distribution (N={len(ratio)}, '
                       f'median={ratio.median():+.2f})')
    axes[0].legend()
    # Right: per-market sign-consistency bar
    markets = ['TW', 'EU', 'JP', 'US']
    sign_agree = []
    pos_noEAV = []
    pos_full = []
    n_per = []
    for m in markets:
        sub = df[df['market'] == m]
        both = sub.dropna(subset=['theta_vix', 'theta_vix_noEAV'])
        n_per.append(len(both))
        if len(both) == 0:
            sign_agree.append(0); pos_noEAV.append(0); pos_full.append(0)
            continue
        agree = (
            (np.sign(both['theta_vix']) == np.sign(both['theta_vix_noEAV'])).sum()
            / len(both)
        )
        sign_agree.append(agree)
        pos_noEAV.append((both['theta_vix_noEAV'] > 0).mean())
        pos_full.append((both['theta_vix'] > 0).mean())
    xs = np.arange(len(markets))
    w = 0.27
    axes[1].bar(xs - w, sign_agree, w, label='sign agreement')
    axes[1].bar(xs, pos_full, w, label='frac > 0 (full)')
    axes[1].bar(xs + w, pos_noEAV, w, label='frac > 0 (noEAV)')
    for i, m in enumerate(markets):
        axes[1].text(i, 1.02, f'N={n_per[i]}', ha='center', fontsize=9)
    axes[1].set_xticks(xs)
    axes[1].set_xticklabels(markets)
    axes[1].set_ylim(0, 1.15)
    axes[1].set_ylabel('proportion')
    axes[1].set_title('Sign consistency and positivity by market')
    axes[1].legend(loc='lower right', fontsize=9)
    axes[1].grid(True, alpha=0.25, axis='y')
    fig.suptitle(
        'K1067f: Sign consistency and ratio of VIX-only vs VIX+EAV spec',
        fontsize=12)
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    plt.close(fig)


# ==========================================================================
# Main
# ==========================================================================
def main():
    t0 = time.time()
    print(f'\n{"="*72}\n{EXPERIMENT_ID}: VIX-only ablation (no EAV in tau)\n{"="*72}\n')

    # ---- 1. Load stocks (identical time window as K1166/K1067e) ----
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

    # ---- 2. Per-stock MLE (VIX-only spec, multiprocessing) ----
    n_workers = min(8, os.cpu_count() or 4)
    print(f'[2/5] Per-stock VIX-only MLE fits '
          f'(n_workers={n_workers}) ...')
    t_fit = time.time()
    with Pool(n_workers) as pool:
        fit_results = pool.map(_mp_worker, all_stocks)
    print(f'  All {len(fit_results)} fits done in {time.time() - t_fit:.1f}s\n')

    df_fits = pd.DataFrame(fit_results)
    n_converged = int(df_fits['converged'].sum())
    print(f'  Converged: {n_converged}/{len(df_fits)}')
    bound_hits = df_fits['params_at_bound'].apply(
        lambda x: len(x) if isinstance(x, list) else 0).sum()
    print(
        '  Stocks with any param at bound: '
        f'{int((df_fits["params_at_bound"].apply(lambda x: len(x) if isinstance(x, list) else 0) > 0).sum())}/{len(df_fits)}'
    )

    # ---- 3. Merge with K1166 full fits + analyst proxies ----
    print('\n[3/5] Merge with K1166 full-spec per-stock table ...')
    df_full = pd.read_csv(K1166_TABLE_PATH)
    full_keep = ['market', 'ticker', 'theta_vix', 'theta_eav', 'theta_eav_se',
                 'theta_eav_t', 'loglik', 'analyst_count', 'market_cap',
                 'median_daily_turnover']
    df_full_sub = df_full[full_keep].rename(columns={
        'theta_vix': 'theta_vix',        # keep as "full" baseline
        'loglik': 'loglik_full',
        'theta_eav': 'theta_eav_full',
        'theta_eav_se': 'theta_eav_full_se',
        'theta_eav_t': 'theta_eav_full_t',
    })
    df_merged = df_fits.merge(df_full_sub, on=['market', 'ticker'], how='left')
    proxies = load_analyst_proxies()
    df_merged['analyst_count'] = df_merged['ticker'].map(
        lambda t: proxies.get(t, {}).get('analyst_count'))
    df_merged['market_cap'] = df_merged['ticker'].map(
        lambda t: proxies.get(t, {}).get('market_cap'))
    df_merged['median_daily_turnover'] = df_merged['ticker'].map(
        lambda t: proxies.get(t, {}).get('median_daily_turnover'))

    # LR statistic per stock (full nests noEAV; theta_eav=0 is the null).
    df_merged['LR_stat'] = 2.0 * (df_merged['loglik_full'] - df_merged['loglik_noEAV'])
    df_merged['LR_p'] = 1.0 - stats.chi2.cdf(df_merged['LR_stat'].clip(lower=0), df=1)

    keep_cols = ['market', 'ticker', 'converged', 'theta0', 'alpha',
                 'gamma', 'beta', 'persistence',
                 'theta_vix_noEAV', 'theta_vix_noEAV_se', 'theta_vix_noEAV_t',
                 'loglik_noEAV',
                 'theta_vix', 'theta_eav_full', 'theta_eav_full_se',
                 'theta_eav_full_t', 'loglik_full',
                 'LR_stat', 'LR_p',
                 'n_obs', 'n_events', 'sigma2_sample',
                 'analyst_count', 'market_cap', 'median_daily_turnover']
    df_merged[keep_cols].to_csv(CSV_PATH, index=False)
    print(f'  Saved: {CSV_PATH.relative_to(SCRIPT_DIR)}')

    # ---- 4. Cross-stock analysis ----
    print('\n[4/5] Cross-stock comparison noEAV vs full ...')
    pooled = df_merged[df_merged['converged'] & df_merged['theta_vix'].notna()].copy()
    sp_rho, sp_p, sp_n = spearman_with_p(pooled['theta_vix'], pooled['theta_vix_noEAV'])
    pe_r, pe_p, pe_n = pearson_with_p(pooled['theta_vix'], pooled['theta_vix_noEAV'])
    sign_agree_pooled = float(
        ((np.sign(pooled['theta_vix']) == np.sign(pooled['theta_vix_noEAV'])).sum())
        / len(pooled)
    ) if len(pooled) > 0 else None
    ratio = (pooled['theta_vix_noEAV'] / pooled['theta_vix']).replace(
        [np.inf, -np.inf], np.nan).dropna()
    ll_diff = pooled['loglik_full'] - pooled['loglik_noEAV']
    ll_diff_mean = float(ll_diff.mean())
    ll_diff_median = float(ll_diff.median())
    n_full_better = int((ll_diff > 0).sum())
    lr_reject_05 = float((pooled['LR_p'] < 0.05).mean())
    lr_reject_01 = float((pooled['LR_p'] < 0.01).mean())

    print(f'  Pooled (N={len(pooled)}): rho_Spearman(noEAV, full) = {sp_rho:+.3f} (p={sp_p:.3g})')
    print(f'  Pooled Pearson r = {pe_r:+.3f}')
    print(f'  Sign agreement = {sign_agree_pooled:.3f} '
          f'({int(sign_agree_pooled*len(pooled))}/{len(pooled)})')
    print(f'  Ratio noEAV/full: median={ratio.median():+.2f}, mean={ratio.mean():+.2f}, '
          f'IQR=[{ratio.quantile(0.25):+.2f}, {ratio.quantile(0.75):+.2f}]')
    print(f'  LR (full vs noEAV): mean diff LL = {ll_diff_mean:+.2f}, '
          f'median = {ll_diff_median:+.2f}, full wins in {n_full_better}/{len(pooled)}')
    print(f'  LR reject @0.05: {lr_reject_05:.2%}, @0.01: {lr_reject_01:.2%}')

    per_market = {}
    for m in ['TW', 'EU', 'JP', 'US']:
        sub = pooled[pooled['market'] == m]
        if len(sub) == 0:
            continue
        sp_rho_m, sp_p_m, _ = spearman_with_p(sub['theta_vix'], sub['theta_vix_noEAV'])
        pe_r_m, _, _ = pearson_with_p(sub['theta_vix'], sub['theta_vix_noEAV'])
        agree = float(((np.sign(sub['theta_vix']) == np.sign(sub['theta_vix_noEAV'])).sum())
                       / len(sub))
        t_noEAV = sub['theta_vix_noEAV_t'].dropna().values
        n_sig_2 = int(np.sum(np.abs(t_noEAV) > 2.0))
        n_sig_3 = int(np.sum(np.abs(t_noEAV) > 3.0))
        vals_n = sub['theta_vix_noEAV'].dropna().values
        vals_f = sub['theta_vix'].dropna().values
        per_market[m] = {
            'n': int(len(sub)),
            'spearman_noEAV_vs_full': {'rho': sp_rho_m, 'p': sp_p_m},
            'pearson_noEAV_vs_full': pe_r_m,
            'sign_agreement': agree,
            'noEAV_mean': float(np.mean(vals_n)) if len(vals_n) else None,
            'noEAV_median': float(np.median(vals_n)) if len(vals_n) else None,
            'noEAV_std': float(np.std(vals_n, ddof=1)) if len(vals_n) > 1 else None,
            'full_mean': float(np.mean(vals_f)) if len(vals_f) else None,
            'full_median': float(np.median(vals_f)) if len(vals_f) else None,
            'pct_sig_t2_noEAV': float(n_sig_2 / len(t_noEAV)) if len(t_noEAV) else None,
            'pct_sig_t3_noEAV': float(n_sig_3 / len(t_noEAV)) if len(t_noEAV) else None,
            'frac_pos_noEAV': float(np.mean(vals_n > 0)) if len(vals_n) else None,
            'frac_pos_full': float(np.mean(vals_f > 0)) if len(vals_f) else None,
            'LR_reject_0.05': float((sub['LR_p'] < 0.05).mean()),
        }
        print(f'    {m}: rho={sp_rho_m:+.3f}, sign_agree={agree:.2f}, '
              f'mean_noEAV={np.mean(vals_n):+.3e} vs full={np.mean(vals_f):+.3e}, '
              f'%|t|>2_noEAV={100*n_sig_2/max(len(t_noEAV),1):.0f}%')

    # Spearman(log_analyst, theta_vix_noEAV) — symmetric mechanism replay.
    print('\n  Mechanism replay (symmetry check): Spearman(log_analyst, theta_vix_noEAV):')
    spearman_mech = {}
    la = np.log(pooled['analyst_count'].astype(float) + 1.0)
    rho, p, n = spearman_with_p(la, pooled['theta_vix_noEAV'])
    spearman_mech['pooled'] = {'rho': rho, 'p': p, 'n': n}
    print(f'    pooled: rho={rho:+.3f} (p={p:.3f}, N={n})')
    for m in ['TW', 'US', 'JP', 'EU']:
        sub = pooled[pooled['market'] == m]
        if len(sub) < 4:
            continue
        la_m = np.log(sub['analyst_count'].astype(float) + 1.0)
        rho_m, p_m, n_m = spearman_with_p(la_m, sub['theta_vix_noEAV'])
        spearman_mech[m] = {'rho': rho_m, 'p': p_m, 'n': n_m}
        print(f'    {m}: rho={rho_m:+.3f} (p={p_m:.3f}, N={n_m})')

    # Panel regression: theta_vix_noEAV on analyst + market FE (HC0).
    print('\n  Panel: theta_vix_noEAV ~ log_analyst + log_mcap + market_FE (HC0):')
    panel_noEAV = panel_ols_market_fe(pooled, 'theta_vix_noEAV')
    if panel_noEAV is not None:
        for col, d in panel_noEAV['coefs'].items():
            print(f'    {col}: beta={d["beta"]:+.4e}, SE={d["se"]:.4e}, '
                  f't={d["t"]:+.3f}, p={d["p"]:.4f}')
        print(f'    R^2 = {panel_noEAV["r2"]:.3f}, n = {panel_noEAV["n"]}')

    # Also run panel with theta_vix_full for reference.
    print('\n  Panel reference: theta_vix (K1166 full) ~ log_analyst + log_mcap + market_FE (HC0):')
    panel_full_vix = panel_ols_market_fe(pooled, 'theta_vix')
    if panel_full_vix is not None:
        for col, d in panel_full_vix['coefs'].items():
            print(f'    {col}: beta={d["beta"]:+.4e}, SE={d["se"]:.4e}, '
                  f't={d["t"]:+.3f}, p={d["p"]:.4f}')
        print(f'    R^2 = {panel_full_vix["r2"]:.3f}, n = {panel_full_vix["n"]}')

    # ---- 5. Plots ----
    print('\n[5/5] Plots ...')
    plot_scatter_noEAV_vs_full(pooled, FIG_SCATTER_PATH, sp_rho)
    print(f'  {FIG_SCATTER_PATH.name}')
    plot_sign_consistency_hist(pooled, FIG_SIGN_PATH)
    print(f'  {FIG_SIGN_PATH.name}')

    # ---- Ablation verdict ----
    # Decision rule (symmetry with K1067e):
    # H1: rho > 0.9 AND sign consistency > 0.9
    # H2: rho < 0.5 OR sign flips > 30% OR panel sign change for analyst direction
    # H3: otherwise
    panel_la_noEAV = panel_noEAV['coefs'].get('log_analyst') if panel_noEAV else None
    panel_la_full = panel_full_vix['coefs'].get('log_analyst') if panel_full_vix else None

    h1 = (sp_rho is not None and sp_rho > 0.9
          and sign_agree_pooled is not None and sign_agree_pooled > 0.90)
    h2 = ((sp_rho is not None and sp_rho < 0.5)
          or (sign_agree_pooled is not None and sign_agree_pooled < 0.70)
          or (panel_la_noEAV is not None and panel_la_full is not None
              and panel_la_noEAV['beta'] * panel_la_full['beta'] < 0
              and abs(panel_la_full['t']) > 2.0))
    if h1:
        verdict = 'H1: VIX channel truly independent (rho>0.9, sign_agree>90%)'
        verdict_code = 'H1'
    elif h2:
        verdict = 'H2: EAV was carrying weight (large sign flips / low rho / panel sign change)'
        verdict_code = 'H2'
    else:
        verdict = 'H3: Partial collinearity (sign mostly preserved, magnitudes shift)'
        verdict_code = 'H3'

    print(f'\n  Ablation verdict: {verdict}')

    paper2_impact = {
        'H1': (
            'Paper 2 robustness COMPLETE. Both VIX and EAV channels are independent long-run regressors. '
            'The full A4f-EAV spec has no redundancy. Each channel survives removal of the other.'),
        'H2': (
            'Paper 2 VIX channel in question. Need to explain why removing a sparse 0/1 EAV flag '
            'materially shifts the continuous VIX loading.'),
        'H3': (
            'Paper 2 VIX channel MOSTLY STABLE. Partial collinearity; report joint loadings. '
            'Symmetric with K1067e EAV-only ablation.'),
    }[verdict_code]

    # ---- Build results JSON ----
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'VIX-only ablation vs A4f-EAV (full) per-stock spec (reverse sanity of K1067e)',
        'proposer': 'Claude (follow-up to K1067e EAV-only ablation)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_sources': [
            'experiments/k1145/data/ (TW parquet + VIX)',
            'experiments/k1147/data/ (US parquet + earnings_dates.json, earnings used only for n_events filter)',
            'experiments/k1150/data/ (JP parquet + earnings_dates.json)',
            'experiments/k1153/data/ (EU parquet + earnings_dates.json)',
            'experiments/k1166/k1166_per_stock_table.csv (full-spec theta_VIX baselines)',
            'experiments/k1164/data/analyst_media_proxies.json (analyst/mcap proxies)',
            '財報公告日.txt (TW earnings, big5, only for n_events filter)',
        ],
        'specification': {
            'full_reference': 'K1166 A4f-EAV: tau = theta0 + theta_VIX*VIX^2 + theta_EAV*EAV',
            'noEAV_tested_here': 'tau = theta0 + theta_VIX*VIX^2  (no EAV term)',
            'g_process': 'GJR(1,1) with Engle-Ghysels-Sohn E[g]=1 (omega_g = 1 - alpha - gamma/2 - beta)',
            'estimation': 'L-BFGS-B multi-start, Hessian SE from 2nd-order finite-diff',
            'lookahead': 'VIX^2 at lag t-1 (verified in numba likelihood)',
            'n_free_params_per_stock': 5,
        },
        'n_stocks_total': len(all_stocks),
        'n_converged_noEAV': n_converged,
        'pooled_cross_stock': {
            'spearman_noEAV_vs_full': {'rho': sp_rho, 'p': sp_p, 'n': sp_n},
            'pearson_noEAV_vs_full': {'r': pe_r, 'p': pe_p, 'n': pe_n},
            'sign_agreement': sign_agree_pooled,
            'ratio_noEAV_over_full': {
                'median': float(ratio.median()),
                'mean': float(ratio.mean()),
                'q25': float(ratio.quantile(0.25)),
                'q75': float(ratio.quantile(0.75)),
                'n': int(len(ratio)),
            },
            'loglik_diff_full_minus_noEAV': {
                'mean': ll_diff_mean,
                'median': ll_diff_median,
                'n_full_better': n_full_better,
                'n_total': int(len(pooled)),
                'LR_reject_0.05': lr_reject_05,
                'LR_reject_0.01': lr_reject_01,
            },
        },
        'per_market': per_market,
        'mechanism_spearman_log_analyst_vs_theta_vix_noEAV': spearman_mech,
        'panel_regression_noEAV': panel_noEAV,
        'panel_regression_full_vix_reference': panel_full_vix,
        'ablation_verdict': verdict,
        'ablation_verdict_code': verdict_code,
        'paper2_narrative_impact': paper2_impact,
        'hypotheses': {
            'H1': 'VIX channel truly independent (rho>0.9 AND sign agreement >90%)',
            'H2': 'EAV was carrying VIX weight (rho<0.5 OR sign_agree<70% OR panel sign flip)',
            'H3': 'Partial collinearity (neither H1 nor H2)',
        },
        'figures': {
            'scatter_noEAV_vs_full': str(FIG_SCATTER_PATH.name),
            'sign_consistency_hist': str(FIG_SIGN_PATH.name),
        },
        'limitations': [
            'Per-stock N_obs still 500-3000 daily observations each.',
            'Analyst count is yfinance snapshot (current, not historical average).',
            'SE from profile Hessian only (no block bootstrap).',
            'Compare within-stock: LR test assumes nesting holds; E[g]=1 normalization preserved.',
            'VIX column required for alignment (consistent with K1166/K1067e).',
        ],
        'execution_time_sec': round(time.time() - t0, 1),
    }

    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2)
    print(f'\n[DONE] Results: {RESULTS_PATH.name}')
    print(f'[DONE] Total time: {time.time() - t0:.1f}s')
    return out


if __name__ == '__main__':
    main()
