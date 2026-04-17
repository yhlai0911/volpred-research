#!/usr/bin/env python3
"""
K1148_d2: US EAV binary-vs-continuous OOS panel DM (cross-market validation)
============================================================================
[提出: Claude (Paper 2 §5 universal-magnitude cross-market validation), 執行: Claude]

Motivation:
  K1148_d1 (just completed) reported TW binary EAV OOS panel DM
  t=-1.46, p=0.076 — Scenario B Marginal FAIL. Combined with K1148
  continuous TW FAIL (t=-1.16, p=0.12), Paper 2 §5 universal-magnitude
  claim has no OOS leg in the TW market.

  This experiment asks: does the US market behave the same way?

  Pre-registered four scenarios (joint binary + continuous US OOS DM):
    A. US binary PASS (t ≤ -2 AND p < 0.05), continuous any
       → TW is OOS-noise exception; US+TW pooled validates §5 universal
    B. US binary FAIL AND US continuous FAIL
       → Cross-market FAIL; §5 universal claim withdrawn entirely
    C. US binary PASS AND US continuous FAIL
       → "Event is signal, magnitude is noise" in US; TW market-specific
         heterogeneity; §5 becomes a cross-market heterogeneity paper
    D. US binary DM > 0 (reverse sign)
       → Severe overfitting warning; §5 possibly deleted

Spec (strictly aligned to K1147 US baseline + K1148 / K1148_d1):
  - 30-stock US S&P 500 large-cap panel (K1147 pre-registered tickers)
  - Price cache: reuse K1147 parquet cache (2014-2025)
  - Earnings dates + surprisePercent: yfinance Ticker.get_earnings_dates(limit=80)
    (K1148 verified as more reliable than earnings_history)
  - IS: pre-2020 (2014-01-01 ~ 2019-12-31), OOS: 2020-01-01 ~ 2025-12-31
    (note: US sample starts 2014, not 2010 as TW)
  - Binary EAV_i,t = 1 if t = earnings day_i, else 0 (K1148_d1 spec)
  - Continuous EAV_i,t = |surprisePercent_i|/100 × 1{t = earnings day_i}
    (K1148 absolute-value continuous spec)
  - Both lag-1 inside _negll_numba via eav[t-1], vix[t-1]
  - Lookahead discipline: VIX_{t-1} (US CBOE settled prior day),
    EAV_{i,t-1} trading-day lag; strict IS/OOS calendar split

Pooled MLE:
  σ²_{i,t} = g_{i,t} · τ_{i,t}
  g_{i,t} = GJR(1,1)_i (per-stock ω, α, γ, β)
  τ_{i,t} = max(θ₀_i + θ_VIX · VIX²_{t-1} + θ_EAV · EAV_{i,t-1}, ε)
  shared (θ_VIX, θ_EAV) across stocks; BCD + Numba-JIT inner

OOS panel DM (verbatim K1148_d1 Codex-corrected spec):
  - Per-stock DM-HLN on QLIKE(r²) within each stock
  - Stock-bootstrap 10,000 reps → panel DM mean t + 95% CI + 1-sided p
  - Joint PASS: t ≤ -2 AND p_one < 0.05

Random seed: 42

Author: VolPred Research System
Date: 2026-04-17
"""
import os
import sys
import json
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats
from numba import njit

import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

warnings.filterwarnings('ignore')

# -------------------------- config --------------------------
GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)
GLOBAL_RNG = np.random.default_rng(GLOBAL_SEED)

START_TIME = time.time()
EXPERIMENT_ID = 'K1148_d2'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
# Reuse K1147 price cache (same tickers, 2014-2025 window)
K1147_CACHE_DIR = PROJECT_ROOT / 'experiments' / 'k1147' / 'data'
DATA_CACHE_DIR = SCRIPT_DIR / 'data'
DATA_CACHE_DIR.mkdir(exist_ok=True, parents=True)
SURPRISE_CACHE = DATA_CACHE_DIR / 'earnings_dates_surprise_us.json'
RESULTS_PATH = SCRIPT_DIR / 'k1148_d2_results.json'

DATA_START = '2014-01-01'
DATA_END = '2025-12-31'
OOS_START = '2020-01-01'   # same OOS calendar date as K1148 / K1148_d1

BCD_MAX_OUTER = 8
BCD_TIME_BUDGET = 600
N_STOCK_BOOTSTRAP = 10000
OOS_DM_THRESHOLD = -2.0    # Harvey (2016) one-sided

# K1147 US pre-registered N=30 large-caps
US_TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B',
    'UNH', 'V', 'JPM', 'WMT', 'MA', 'JNJ', 'XOM', 'PG', 'HD', 'CVX',
    'ABBV', 'AVGO', 'COST', 'PEP', 'KO', 'MRK', 'ADBE', 'CSCO', 'TMO',
    'CRM', 'MCD', 'ABT',
]


# ======================================================================
# Earnings loader (surprise% via get_earnings_dates — K1148 verified)
# ======================================================================
def fetch_earnings_surprises(tickers, use_cache=True):
    """Return dict: ticker -> DataFrame(index=announcement_date,
    columns=['surprise_pct']). Uses yfinance get_earnings_dates.

    Uses yfinance.Ticker.get_earnings_dates(limit=80) which returns up to
    80 quarterly earnings rows with columns including 'Surprise(%)'.
    K1148 verified this is more reliable than earnings_history."""
    if use_cache and SURPRISE_CACHE.exists():
        with open(SURPRISE_CACHE) as f:
            cached = json.load(f)
        out = {}
        for tk, rows in cached.items():
            if not rows:
                out[tk] = pd.DataFrame(columns=['surprise_pct'])
                continue
            df = pd.DataFrame(rows)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date').sort_index()
            out[tk] = df
        print(f'  [surprise cache] loaded {len(out)} tickers from '
              f'{SURPRISE_CACHE.name}')
        return out

    out = {}
    cache_dump = {}
    for tk in tickers:
        try:
            ed = yf.Ticker(tk).get_earnings_dates(limit=80)
            if ed is None or len(ed) == 0:
                print(f'  [surprise] {tk}: empty')
                out[tk] = pd.DataFrame(columns=['surprise_pct'])
                cache_dump[tk] = []
                continue
            ed = ed.sort_index()
            # Strip tz + time; keep date only
            idx = pd.to_datetime([i.date() for i in ed.index])
            # Column may be 'Surprise(%)'
            if 'Surprise(%)' not in ed.columns:
                print(f'  [surprise] {tk}: no Surprise(%) col, cols={list(ed.columns)}')
                out[tk] = pd.DataFrame(columns=['surprise_pct'])
                cache_dump[tk] = []
                continue
            sp = ed['Surprise(%)'].astype(float).values
            df = pd.DataFrame({'surprise_pct': sp}, index=idx)
            df = df.dropna()
            df = df[(df.index >= DATA_START) & (df.index <= DATA_END)]
            # Filter: past announcements only
            today = pd.Timestamp.now().normalize()
            df = df[df.index < today]
            out[tk] = df
            cache_dump[tk] = [
                {'date': d.strftime('%Y-%m-%d'), 'surprise_pct': float(v)}
                for d, v in df['surprise_pct'].items()
            ]
            print(f'  [surprise] {tk}: n={len(df)}, '
                  f'range=[{df.index.min().date() if len(df)>0 else "NA"}, '
                  f'{df.index.max().date() if len(df)>0 else "NA"}]')
            time.sleep(1.0)  # rate-limit
        except Exception as e:
            print(f'  [surprise] {tk}: ERROR {e}')
            out[tk] = pd.DataFrame(columns=['surprise_pct'])
            cache_dump[tk] = []
    with open(SURPRISE_CACHE, 'w') as f:
        json.dump(cache_dump, f, indent=2)
    print(f'  [surprise cache] saved to {SURPRISE_CACHE.name}')
    return out


def winsorize_surprises(surprise_dict, q_lo=0.05, q_hi=0.95):
    """Robust quantile winsor on pooled surprise distribution."""
    pooled = np.concatenate(
        [df['surprise_pct'].values for df in surprise_dict.values()
         if len(df) > 0]
    )
    if len(pooled) == 0:
        return surprise_dict, {}
    lo = float(np.percentile(pooled, q_lo * 100))
    hi = float(np.percentile(pooled, q_hi * 100))
    n_capped = 0
    total = 0
    out = {}
    for tk, df in surprise_dict.items():
        if len(df) == 0:
            out[tk] = df
            continue
        df2 = df.copy()
        before = df2['surprise_pct'].values.copy()
        df2['surprise_pct'] = df2['surprise_pct'].clip(lower=lo, upper=hi)
        n_capped += int((before != df2['surprise_pct'].values).sum())
        total += len(df2)
        out[tk] = df2
    info = {
        'q_lo': q_lo, 'q_hi': q_hi,
        'winsor_lo': lo, 'winsor_hi': hi,
        'n_capped': n_capped, 'n_total': total,
        'pct_capped': n_capped / total if total > 0 else 0.0,
        'pooled_min_raw': float(pooled.min()),
        'pooled_max_raw': float(pooled.max()),
        'pooled_mean_raw': float(pooled.mean()),
        'pooled_std_raw': float(pooled.std(ddof=1)),
    }
    return out, info


# ======================================================================
# Price loading (reuse K1147 cache)
# ======================================================================
def load_cached_price(ticker):
    """Load from K1147 cache. K1147 used safe_name = ticker.replace('^','IDX_').replace('-','_')
    for parquet filenames."""
    safe_name = ticker.replace('^', 'IDX_').replace('-', '_')
    path = K1147_CACHE_DIR / f"{safe_name}.parquet"
    if not path.exists():
        return None
    return pd.read_parquet(path)


def build_binary_eav(trading_days, ann_dates):
    """K1148_d1-style binary indicator: 1 on announcement day, 0 else."""
    eav = np.zeros(len(trading_days), dtype=float)
    if len(ann_dates) == 0:
        return eav
    pos_arr = trading_days.searchsorted(ann_dates.values)
    for p in pos_arr:
        p = int(p)
        if 0 <= p < len(trading_days):
            eav[p] = 1.0
    return eav


def build_continuous_eav(trading_days, surprise_df):
    """K1148-style continuous indicator: |surprise_pct|/100 on announcement
    day, 0 else."""
    eav = np.zeros(len(trading_days), dtype=float)
    if len(surprise_df) == 0:
        return eav
    pos_arr = trading_days.searchsorted(surprise_df.index.values)
    for p, sp in zip(pos_arr, surprise_df['surprise_pct'].values):
        p = int(p)
        if 0 <= p < len(trading_days):
            v = float(sp) / 100.0
            eav[p] = abs(v)
    return eav


def load_one_stock_both_specs(ticker, surprise_df):
    """Load one US stock with both binary and continuous EAV.
    Returns dict with r/vix/eav_bin/eav_cont arrays and date index."""
    raw = load_cached_price(ticker)
    if raw is None:
        return None
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix_raw = load_cached_price('^VIX')
    if vix_raw is None:
        return None
    vix = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]
    if len(surprise_df) == 0:
        return None
    ann_dates = pd.DatetimeIndex(surprise_df.index)
    eav_bin = build_binary_eav(df.index, ann_dates)
    eav_cont = build_continuous_eav(df.index, surprise_df)
    n_events = int((eav_bin != 0).sum())
    if len(df) < 500 or n_events < 15:
        return None
    return {
        'ticker': ticker,
        'r': df['r'].values,
        'vix': df['vix'].values,
        'eav_bin': eav_bin,
        'eav_cont': eav_cont,
        'index': df.index,
        'n_obs': len(df),
        'n_events': n_events,
    }


# ======================================================================
# Likelihood and forecasting (identical to K1148 / K1148_d1)
# ======================================================================
@njit(cache=True, fastmath=True)
def _negll_numba(theta0, omega_g, alpha, gamma_p, beta_p,
                  r, vix, eav, theta_vix, theta_eav):
    n = r.shape[0]
    persist = alpha + gamma_p / 2.0 + beta_p
    if omega_g <= 0.0 or alpha < 0.0 or gamma_p < 0.0 or beta_p < 0.0:
        return 1e10
    if persist >= 0.999:
        return 1e10
    tau = np.empty(n)
    tau[0] = theta0 if theta0 > 1e-16 else 1e-16
    for t in range(1, n):
        vl = vix[t - 1]
        el = eav[t - 1]
        raw = theta0 + theta_vix * vl * vl + theta_eav * el
        tau[t] = raw if raw > 1e-16 else 1e-16
    eg = omega_g / (1.0 - persist)
    g = eg
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


@njit(cache=True, fastmath=True)
def _forecast_sigma2_numba(theta0, omega_g, alpha, gamma_p, beta_p,
                            r, vix, eav, theta_vix, theta_eav):
    n = r.shape[0]
    sigma2 = np.empty(n)
    persist = alpha + gamma_p / 2.0 + beta_p
    eg = omega_g / (1.0 - persist) if persist < 0.999 else 1.0
    g = eg
    tau = np.empty(n)
    tau[0] = theta0 if theta0 > 1e-16 else 1e-16
    for t in range(1, n):
        vl = vix[t - 1]
        el = eav[t - 1]
        raw = theta0 + theta_vix * vl * vl + theta_eav * el
        tau[t] = raw if raw > 1e-16 else 1e-16
    sigma2[0] = tau[0] * g
    for t in range(1, n):
        tau_prev = tau[t - 1]
        if tau_prev < 1e-16:
            tau_prev = 1e-16
        u_prev = r[t - 1] / np.sqrt(tau_prev)
        asym = gamma_p * u_prev * u_prev if u_prev < 0.0 else 0.0
        g = omega_g + alpha * u_prev * u_prev + asym + beta_p * g
        if g < 1e-10:
            g = 1e-10
        sigma2[t] = tau[t] * g
    return sigma2


def per_stock_neg_loglik(sp, r, vix, eav, theta_vix, theta_eav):
    t0, og, a, gp, bp = sp
    return _negll_numba(float(t0), float(og), float(a), float(gp), float(bp),
                         r, vix, eav, float(theta_vix), float(theta_eav))


def fit_one_stock_given_shared(r, vix, eav, theta_vix, theta_eav, init=None):
    var0 = np.var(r)
    if init is None:
        starts = [
            [var0 * 0.10, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.20, 0.02, 0.08, 0.10, 0.80],
        ]
    else:
        starts = [init, [var0 * 0.10, 0.05, 0.05, 0.05, 0.90]]
    bounds = [(1e-8, 1e-2), (1e-6, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll = np.inf
    best_p = None
    for s in starts:
        try:
            res = optimize.minimize(
                per_stock_neg_loglik, s, args=(r, vix, eav, theta_vix, theta_eav),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 400, 'ftol': 1e-9},
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p, best_ll


def pooled_loglik_given_shared(stocks_is, eav_key, params_list,
                                theta_vix, theta_eav):
    """Compute pooled -loglik across stocks for given shared (theta_vix,
    theta_eav) and per-stock params_list. stocks_is is list of dicts with
    'r', 'vix', and the chosen EAV key."""
    total = 0.0
    for st, p in zip(stocks_is, params_list):
        total += per_stock_neg_loglik(p, st['r'], st['vix'], st[eav_key],
                                       theta_vix, theta_eav)
    return total


def fit_pooled_panel(stocks_is, eav_key, max_outer=8, init_vix=1e-7,
                     init_eav=5e-5, verbose=True, time_budget=None,
                     bounds_shared=None):
    """BCD pooled MLE. `eav_key` picks which EAV series
    ('eav_bin' or 'eav_cont') to use."""
    t_start = time.time()
    theta_vix = float(init_vix)
    theta_eav = float(init_eav)
    params_list = [None] * len(stocks_is)
    prev_negll = np.inf
    history = []
    converged = False
    if bounds_shared is None:
        bounds_shared = [(1e-9, 1e-3), (-1e-2, 1e-2)]

    for outer in range(max_outer):
        if time_budget is not None and time.time() - t_start > time_budget:
            if verbose:
                print(f'    [BCD] outer {outer}: time budget reached')
            break
        total_negll = 0.0
        for i, st in enumerate(stocks_is):
            pi = params_list[i]
            p, ll = fit_one_stock_given_shared(
                st['r'], st['vix'], st[eav_key], theta_vix, theta_eav, init=pi)
            if p is None:
                if params_list[i] is None:
                    raise RuntimeError(f'Stock {st["ticker"]} initial fit failed')
                continue
            params_list[i] = p
            total_negll += ll

        def obj(shared):
            return pooled_loglik_given_shared(
                stocks_is, eav_key, params_list, shared[0], shared[1])

        res = optimize.minimize(
            obj, [theta_vix, theta_eav],
            method='L-BFGS-B', bounds=bounds_shared,
            options={'maxiter': 200, 'ftol': 1e-10},
        )
        nv, ne = res.x
        d_ll = prev_negll - res.fun
        if verbose:
            print(f'    [BCD outer {outer}] θ_VIX={nv:.3e}, '
                  f'θ_EAV={ne:+.4e}, pooled_negll={res.fun:.2f}, '
                  f'Δll={d_ll:+.4f}, Δθ_eav={abs(ne-theta_eav):.2e}')
        history.append({
            'outer_iter': outer,
            'theta_vix': float(nv), 'theta_eav': float(ne),
            'pooled_negll': float(res.fun),
        })
        theta_vix, theta_eav = float(nv), float(ne)
        if outer >= 1 and d_ll < 1e-2 and abs(ne - history[-2]['theta_eav']) < 1e-7:
            converged = True
            if verbose:
                print('    [BCD] converged')
            break
        prev_negll = res.fun

    # Final inner pass
    final_negll = 0.0
    final_params = []
    for i, st in enumerate(stocks_is):
        p, ll = fit_one_stock_given_shared(
            st['r'], st['vix'], st[eav_key], theta_vix, theta_eav,
            init=params_list[i])
        if p is None:
            p = params_list[i]
            ll = per_stock_neg_loglik(p, st['r'], st['vix'], st[eav_key],
                                       theta_vix, theta_eav)
        final_params.append(p)
        final_negll += ll
    return {
        'theta_vix': theta_vix, 'theta_eav': theta_eav,
        'per_stock_params': [p.tolist() for p in final_params],
        'pooled_loglik': float(-final_negll),
        'pooled_negll': float(final_negll),
        'n_outer_iters': len(history),
        'converged': converged,
        'history': history,
    }


def hessian_se_theta_eav(stocks_is, eav_key, params_list,
                          theta_vix, theta_eav, eps_scale=1e-3):
    ll0 = pooled_loglik_given_shared(stocks_is, eav_key, params_list,
                                      theta_vix, theta_eav)
    eps = max(abs(theta_eav) * eps_scale, eps_scale * 1e-4)
    ll_p = pooled_loglik_given_shared(stocks_is, eav_key, params_list,
                                       theta_vix, theta_eav + eps)
    ll_m = pooled_loglik_given_shared(stocks_is, eav_key, params_list,
                                       theta_vix, theta_eav - eps)
    h22 = (ll_p - 2 * ll0 + ll_m) / (eps ** 2)
    if h22 > 0 and np.isfinite(h22):
        return float(np.sqrt(1.0 / h22))
    return None


# ======================================================================
# Pure-GJR baseline (identical to K1148 / K1148_d1)
# ======================================================================
@njit(cache=True, fastmath=True)
def _negll_pure_gjr(omega, alpha, gamma_p, beta_p, r):
    n = r.shape[0]
    persist = alpha + gamma_p / 2.0 + beta_p
    if omega <= 0.0 or alpha < 0.0 or gamma_p < 0.0 or beta_p < 0.0:
        return 1e10
    if persist >= 0.999:
        return 1e10
    h = omega / (1.0 - persist)
    ll = 0.0
    log2pi = np.log(2.0 * np.pi)
    for t in range(1, n):
        u_prev = r[t - 1]
        asym = gamma_p * u_prev * u_prev if u_prev < 0.0 else 0.0
        h = omega + alpha * u_prev * u_prev + asym + beta_p * h
        if h < 1e-10:
            h = 1e-10
        ll += -0.5 * (log2pi + np.log(h) + r[t] * r[t] / h)
    return -ll


def _pure_gjr_obj(params, r):
    return _negll_pure_gjr(float(params[0]), float(params[1]),
                            float(params[2]), float(params[3]), r)


def fit_pure_gjr(r):
    var0 = np.var(r)
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.10, 0.08, 0.04, 0.85],
        [var0 * 0.15, 0.03, 0.08, 0.85],
    ]
    bounds = [(1e-10, 1.0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    best_ll = np.inf
    best_p = None
    for s in starts:
        try:
            res = optimize.minimize(_pure_gjr_obj, s, args=(r,),
                                     method='L-BFGS-B', bounds=bounds,
                                     options={'maxiter': 400, 'ftol': 1e-9})
            if res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p, best_ll


def qlike(sigma2, r2):
    sigma2 = np.maximum(sigma2, 1e-16)
    r2 = np.maximum(r2, 1e-16)
    return np.log(sigma2) + r2 / sigma2


def dm_hln_stat(L1, L2):
    """One-sided DM-HLN at h=1; returns (stat, p_one_m1_better)."""
    d = np.asarray(L1) - np.asarray(L2)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 30:
        return None, None
    dbar = d.mean()
    var_d = np.var(d, ddof=1) / T
    if var_d <= 0:
        return None, None
    stat = dbar / np.sqrt(var_d)
    p_one_m1_better = float(stats.t.cdf(stat, df=T - 1))
    return float(stat), p_one_m1_better


# ======================================================================
# Full pipeline for ONE EAV spec: IS fit + baseline GJR + OOS panel DM
# ======================================================================
def run_one_spec(spec_name, eav_key, stocks_loaded,
                 init_eav, bounds_shared=None):
    """Run full pipeline for one EAV spec. Returns dict with all stats."""
    print(f'\n{"=" * 72}')
    print(f'SPEC: {spec_name} (eav_key={eav_key})')
    print(f'{"=" * 72}')

    # IS / OOS split
    print('\n[split] IS/OOS by calendar date ...')
    oos_start_ts = pd.Timestamp(OOS_START)
    is_stocks = []
    oos_stocks = []
    for st in stocks_loaded:
        idx = st['index']
        mask_is = np.asarray(idx < oos_start_ts, dtype=bool)
        mask_oos = np.asarray(idx >= oos_start_ts, dtype=bool)
        if mask_is.sum() < 500:
            print(f'    {st["ticker"]}: IS too short ({int(mask_is.sum())})')
            continue
        if mask_oos.sum() < 250:
            print(f'    {st["ticker"]}: OOS too short ({int(mask_oos.sum())})')
            continue
        is_rec = {
            'ticker': st['ticker'],
            'r': st['r'][mask_is], 'vix': st['vix'][mask_is],
            'eav_bin': st['eav_bin'][mask_is],
            'eav_cont': st['eav_cont'][mask_is],
            'index': idx[mask_is],
            'n_obs': int(mask_is.sum()),
            'n_events': int((st['eav_bin'][mask_is] != 0).sum()),
        }
        oos_rec = {
            'ticker': st['ticker'],
            'r': st['r'][mask_oos], 'vix': st['vix'][mask_oos],
            'eav_bin': st['eav_bin'][mask_oos],
            'eav_cont': st['eav_cont'][mask_oos],
            'index': idx[mask_oos],
            'n_obs': int(mask_oos.sum()),
            'n_events': int((st['eav_bin'][mask_oos] != 0).sum()),
        }
        is_stocks.append(is_rec)
        oos_stocks.append(oos_rec)

    print(f'  IS stocks: {len(is_stocks)} / OOS stocks: {len(oos_stocks)}')
    print(f'  IS total obs: {sum(s["n_obs"] for s in is_stocks):,}')
    print(f'  OOS total obs: {sum(s["n_obs"] for s in oos_stocks):,}')
    print(f'  IS total events: {sum(s["n_events"] for s in is_stocks):,}')
    print(f'  OOS total events: {sum(s["n_events"] for s in oos_stocks):,}')

    # IS pooled fit
    print(f'\n[IS fit] Pooled BCD (EAV={eav_key}) ...')
    fit_is = fit_pooled_panel(is_stocks, eav_key, max_outer=BCD_MAX_OUTER,
                               init_vix=1e-7, init_eav=init_eav,
                               verbose=True, time_budget=BCD_TIME_BUDGET,
                               bounds_shared=bounds_shared)
    theta_eav_is = fit_is['theta_eav']
    theta_vix_is = fit_is['theta_vix']
    print(f'\n  → IS θ_VIX = {theta_vix_is:.4e}')
    print(f'  → IS θ_EAV = {theta_eav_is:+.4e}')
    print(f'  → IS pooled loglik = {fit_is["pooled_loglik"]:.2f}')

    se_is = hessian_se_theta_eav(
        is_stocks, eav_key,
        [np.array(p) for p in fit_is['per_stock_params']],
        theta_vix_is, theta_eav_is,
    )
    t_is = theta_eav_is / se_is if (se_is and se_is > 0) else np.nan
    print(f'  IS Hessian SE={se_is}, t={t_is:.3f}')

    # Baseline pure-GJR per stock
    print(f'\n[baseline] Fitting pure-GJR on IS for {len(is_stocks)} stocks ...')
    is_gjr_params = []
    for st in is_stocks:
        p, _ = fit_pure_gjr(st['r'])
        is_gjr_params.append(p)

    # OOS forecasts + per-stock DM
    print(f'\n[OOS] Per-stock DM-HLN + stock-bootstrap (N={N_STOCK_BOOTSTRAP}) ...')
    per_stock_dm = []
    L_spec_all = []
    L_gjr_all = []
    for i, oos in enumerate(oos_stocks):
        if i >= len(is_stocks):
            break
        p_spec = np.array(fit_is['per_stock_params'][i])
        sigma2_spec = _forecast_sigma2_numba(
            p_spec[0], p_spec[1], p_spec[2], p_spec[3], p_spec[4],
            oos['r'], oos['vix'], oos[eav_key],
            fit_is['theta_vix'], fit_is['theta_eav'],
        )
        pg = is_gjr_params[i]
        if pg is None:
            continue
        persist_g = pg[1] + pg[2] / 2.0 + pg[3]
        sigma2_gjr = np.empty(len(oos['r']))
        h = pg[0] / (1.0 - persist_g) if persist_g < 0.999 else 1.0
        sigma2_gjr[0] = h
        for t in range(1, len(oos['r'])):
            u_prev = oos['r'][t - 1]
            asym = pg[2] * u_prev * u_prev if u_prev < 0.0 else 0.0
            h = pg[0] + pg[1] * u_prev * u_prev + asym + pg[3] * h
            if h < 1e-10:
                h = 1e-10
            sigma2_gjr[t] = h
        r2 = oos['r'] ** 2
        # Skip t=0 (unconditional tau/g burn-in)
        L_spec = qlike(sigma2_spec[1:], r2[1:])
        L_gjr = qlike(sigma2_gjr[1:], r2[1:])
        s_i, p_i = dm_hln_stat(L_spec, L_gjr)
        per_stock_dm.append({
            'ticker': oos['ticker'],
            'dm_stat': s_i,
            'p_spec_better': p_i,
            'mean_qlike_spec': float(np.nanmean(L_spec)),
            'mean_qlike_gjr': float(np.nanmean(L_gjr)),
            'n': int(len(L_spec)),
            'n_events_oos': oos['n_events'],
            'spec_wins_by_qlike': bool(np.nanmean(L_spec) < np.nanmean(L_gjr)),
        })
        L_spec_all.append(L_spec)
        L_gjr_all.append(L_gjr)

    dm_stats_valid = np.array([d['dm_stat'] for d in per_stock_dm
                                if d['dm_stat'] is not None])
    n_valid = len(dm_stats_valid)
    print(f'  Per-stock DM stats: n_valid={n_valid}')

    if n_valid >= 5:
        panel_dm_mean = float(np.mean(dm_stats_valid))
        panel_dm_median = float(np.median(dm_stats_valid))
        rng_dm = np.random.default_rng(123)
        boot_means = np.array([
            np.mean(rng_dm.choice(dm_stats_valid, size=n_valid, replace=True))
            for _ in range(N_STOCK_BOOTSTRAP)
        ])
        panel_dm_se = float(np.std(boot_means, ddof=1))
        panel_dm_t = panel_dm_mean / panel_dm_se if panel_dm_se > 0 else None
        panel_dm_ci = [float(np.percentile(boot_means, 2.5)),
                       float(np.percentile(boot_means, 97.5))]
        panel_dm_p_one = (
            float(np.mean(boot_means >= 0))
            if panel_dm_mean < 0
            else float(np.mean(boot_means <= 0))
        )
        n_individual_pass = int(np.sum(dm_stats_valid <= -2.0))
        pct_individual_pass = n_individual_pass / n_valid
        print(f'  Panel DM mean={panel_dm_mean:.4f}, '
              f'median={panel_dm_median:.4f}, SE={panel_dm_se:.4f}')
        print(f'  Panel DM t={panel_dm_t:.4f}, '
              f'95% CI=[{panel_dm_ci[0]:.4f}, {panel_dm_ci[1]:.4f}], '
              f'one-sided p={panel_dm_p_one:.4f}')
        print(f'  Individual stocks with DM ≤ -2: '
              f'{n_individual_pass}/{n_valid} ({pct_individual_pass:.1%})')
    else:
        panel_dm_mean = panel_dm_median = panel_dm_se = panel_dm_t = None
        panel_dm_p_one = None
        panel_dm_ci = None
        n_individual_pass = 0
        pct_individual_pass = 0.0

    L_spec_pooled = np.concatenate(L_spec_all) if L_spec_all else np.array([])
    L_gjr_pooled = np.concatenate(L_gjr_all) if L_gjr_all else np.array([])
    print(f'  Pooled mean QLIKE {spec_name}={np.nanmean(L_spec_pooled):.6f}')
    print(f'  Pooled mean QLIKE GJR     ={np.nanmean(L_gjr_pooled):.6f}')

    # Harvey joint PASS check
    if panel_dm_t is None or panel_dm_p_one is None:
        joint_pass = False
        pass_reason = 'panel DM unavailable'
    else:
        joint_pass = bool(
            panel_dm_t <= OOS_DM_THRESHOLD and panel_dm_p_one < 0.05
        )
        pass_reason = (f't={panel_dm_t:.3f}, p={panel_dm_p_one:.4f} '
                        f'{"PASS" if joint_pass else "FAIL"} (joint threshold)')
    print(f'  JOINT PASS: {joint_pass}  [{pass_reason}]')

    return {
        'spec_name': spec_name,
        'eav_key': eav_key,
        'n_is_stocks': len(is_stocks),
        'n_oos_stocks': len(oos_stocks),
        'n_is_obs': int(sum(s['n_obs'] for s in is_stocks)),
        'n_oos_obs': int(sum(s['n_obs'] for s in oos_stocks)),
        'n_is_events': int(sum(s['n_events'] for s in is_stocks)),
        'n_oos_events': int(sum(s['n_events'] for s in oos_stocks)),
        'is_fit': {
            'theta_vix': theta_vix_is,
            'theta_eav': theta_eav_is,
            'theta_eav_se_hessian': se_is,
            'theta_eav_t_hessian': float(t_is) if np.isfinite(t_is) else None,
            'pooled_loglik': fit_is['pooled_loglik'],
            'n_outer_iters': fit_is['n_outer_iters'],
            'converged': fit_is['converged'],
            'per_stock_tickers': [s['ticker'] for s in is_stocks],
            'per_stock_params': fit_is['per_stock_params'],
        },
        'oos_dm': {
            'n_stocks_valid': n_valid,
            'per_stock_dm': per_stock_dm,
            'panel_dm_mean': panel_dm_mean,
            'panel_dm_median': panel_dm_median,
            'panel_dm_se_bootstrap': panel_dm_se,
            'panel_dm_t': panel_dm_t,
            'panel_dm_ci_95': panel_dm_ci,
            'panel_dm_one_sided_p_spec_better': panel_dm_p_one,
            'n_individual_pass_dm_le_neg2': n_individual_pass,
            'pct_individual_pass_dm_le_neg2': pct_individual_pass,
            'threshold_oos_dm_pass': OOS_DM_THRESHOLD,
            'mean_qlike_spec_pooled': float(np.nanmean(L_spec_pooled))
                if len(L_spec_pooled) > 0 else None,
            'mean_qlike_baseline_gjr_pooled': float(np.nanmean(L_gjr_pooled))
                if len(L_gjr_pooled) > 0 else None,
            'joint_pass_harvey': joint_pass,
        },
    }


# ======================================================================
# Main
# ======================================================================
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: US EAV binary-vs-continuous OOS panel DM '
           '(cross-market)')
    print(f'{"=" * 72}\n')
    print(f'Tickers tried ({len(US_TICKERS)}): {US_TICKERS}\n')

    # --- [1/4] Fetch earnings surprises (uses cache after first run) ---
    print('[1/4] Fetching US earnings surprises (yfinance '
          'get_earnings_dates) ...')
    sur_dict = fetch_earnings_surprises(US_TICKERS, use_cache=True)
    sur_dict, winsor_info = winsorize_surprises(sur_dict)
    if winsor_info:
        print(f'\n  Winsor: lo={winsor_info["winsor_lo"]:.2f}%, '
              f'hi={winsor_info["winsor_hi"]:.2f}%, '
              f'capped {winsor_info["n_capped"]}/{winsor_info["n_total"]} '
              f'({winsor_info["pct_capped"]:.1%})')
        print(f'  Raw range: [{winsor_info["pooled_min_raw"]:.1f}%, '
              f'{winsor_info["pooled_max_raw"]:.1f}%]\n')

    # --- [2/4] Load each stock with BOTH binary and continuous EAV ---
    print('[2/4] Loading stocks (binary + continuous EAV) ...')
    stocks_loaded = []
    skipped = []
    for tk in US_TICKERS:
        sdf = sur_dict.get(tk, pd.DataFrame())
        if len(sdf) == 0:
            skipped.append((tk, 'no surprise data'))
            print(f'    SKIP {tk}: no surprise data')
            continue
        st = load_one_stock_both_specs(tk, sdf)
        if st is None:
            skipped.append((tk, 'load_one_stock_both_specs returned None'))
            print(f'    SKIP {tk}: insufficient data (n_events<15 or n_obs<500)')
            continue
        stocks_loaded.append(st)
        print(f'    {tk}: n_obs={st["n_obs"]}, n_events={st["n_events"]}')
    print(f'\n  Loaded {len(stocks_loaded)}/{len(US_TICKERS)} stocks')
    if skipped:
        print(f'  Skipped: {skipped}')
    if len(stocks_loaded) < 15:
        print(f'ABORT: only {len(stocks_loaded)} stocks')
        sys.exit(1)

    # --- [3/4] Run BOTH specs: binary and continuous -----------------
    # Binary EAV: same bounds as K1148_d1 (binary is 0/1)
    us_binary = run_one_spec(
        'US_BINARY', 'eav_bin', stocks_loaded,
        init_eav=5e-5,
        bounds_shared=[(1e-9, 1e-3), (-1e-2, 1e-2)],
    )

    # Continuous EAV: wider bounds than K1148 because US surprise|/100 after
    # quantile-winsor is capped at ~0.35 (vs TW ~0.91), so θ_EAV needs to be
    # ~2-3x larger to match per-event impact. Using (-1e-3, 5e-3) to give
    # room for the optimizer to find the true interior MLE.
    us_continuous = run_one_spec(
        'US_CONTINUOUS', 'eav_cont', stocks_loaded,
        init_eav=1e-4,
        bounds_shared=[(1e-9, 1e-3), (-1e-3, 5e-3)],
    )

    # --- [4/4] Load TW results for cross-market comparison ----------
    print(f'\n{"=" * 72}')
    print('[4/4] Cross-market comparison (TW vs US)')
    print('=' * 72)
    try:
        with open(PROJECT_ROOT / 'experiments' / 'k1148_d1'
                   / 'k1148_d1_results.json') as f:
            tw_bin = json.load(f)
        tw_bin_theta = tw_bin['is_fit']['theta_eav']
        tw_bin_t = tw_bin['is_fit']['theta_eav_t_hessian']
        tw_bin_dm = tw_bin['oos_dm']['panel_dm_t']
        tw_bin_p = tw_bin['oos_dm']['panel_dm_one_sided_p_binary_better']
    except Exception as e:
        print(f'  Could not load K1148_d1: {e}')
        tw_bin_theta = tw_bin_t = tw_bin_dm = tw_bin_p = None

    try:
        with open(PROJECT_ROOT / 'experiments' / 'k1148'
                   / 'k1148_results.json') as f:
            tw_cont = json.load(f)
        tw_cont_theta = tw_cont['k1148_continuous']['theta']
        tw_cont_t = tw_cont['k1148_continuous']['t_hessian']
        tw_cont_dm = tw_cont['oos_dm_hln']['panel_dm_t']
        tw_cont_p = tw_cont['oos_dm_hln']['panel_dm_one_sided_p_cont_better']
    except Exception as e:
        print(f'  Could not load K1148: {e}')
        tw_cont_theta = tw_cont_t = tw_cont_dm = tw_cont_p = None

    us_bin_theta = us_binary['is_fit']['theta_eav']
    us_bin_t = us_binary['is_fit']['theta_eav_t_hessian']
    us_bin_dm = us_binary['oos_dm']['panel_dm_t']
    us_bin_p = us_binary['oos_dm']['panel_dm_one_sided_p_spec_better']
    us_bin_pass = us_binary['oos_dm']['joint_pass_harvey']

    us_cont_theta = us_continuous['is_fit']['theta_eav']
    us_cont_t = us_continuous['is_fit']['theta_eav_t_hessian']
    us_cont_dm = us_continuous['oos_dm']['panel_dm_t']
    us_cont_p = us_continuous['oos_dm']['panel_dm_one_sided_p_spec_better']
    us_cont_pass = us_continuous['oos_dm']['joint_pass_harvey']

    print('\n  Four-row comparison:')
    print(f'  {"Spec":22s} | {"IS theta":>12s} | {"IS t":>7s} | '
          f'{"OOS DM t":>8s} | {"OOS p_one":>9s} | {"Joint?":>7s}')
    print('  ' + '-' * 78)

    def fmt(v, fmt_spec):
        return format(v, fmt_spec) if v is not None else 'N/A'

    rows = [
        ('US binary',      us_bin_theta,  us_bin_t,  us_bin_dm,  us_bin_p,  us_bin_pass),
        ('US continuous',  us_cont_theta, us_cont_t, us_cont_dm, us_cont_p, us_cont_pass),
        ('TW binary (d1)', tw_bin_theta,  tw_bin_t,  tw_bin_dm,  tw_bin_p,  None),
        ('TW continuous',  tw_cont_theta, tw_cont_t, tw_cont_dm, tw_cont_p, None),
    ]
    for name, th, tt, dm, pp, jp in rows:
        print(f'  {name:22s} | {fmt(th, "+.3e"):>12s} | {fmt(tt, "+.2f"):>7s} | '
              f'{fmt(dm, "+.3f"):>8s} | {fmt(pp, ".4f"):>9s} | '
              f'{("PASS" if jp else "FAIL") if jp is not None else "N/A":>7s}')

    # --- Scenario verdict -------------------------------------------
    # A: US binary PASS (any US continuous) → TW is exception
    # B: US binary FAIL and US continuous FAIL → cross-market null
    # C: US binary PASS and US continuous FAIL → magnitude-noise narrative
    # D: US binary DM > 0 → overfitting
    if us_bin_dm is not None and us_bin_dm > 0:
        scenario = 'D'
        verdict = (
            f'Scenario D: Reverse FAIL. US binary OOS DM t={us_bin_dm:+.3f} > 0. '
            'Baseline beats binary EAV in US. Severe overfitting warning. '
            'Paper 2 §5 may need to be deleted entirely.'
        )
    elif us_bin_pass and us_cont_pass:
        scenario = 'A_BOTH'
        verdict = (
            f'Scenario A (both pass): US binary OOS DM t={us_bin_dm:.3f} p={us_bin_p:.4f}, '
            f'US continuous OOS DM t={us_cont_dm:.3f} p={us_cont_p:.4f}. '
            'US validates OOS; TW is OOS-noise exception. '
            'Paper 2 §5 universal claim can be retained with cross-market OOS pooling.'
        )
    elif us_bin_pass and not us_cont_pass:
        scenario = 'C'
        verdict = (
            f'Scenario C: US binary PASS (t={us_bin_dm:.3f}, p={us_bin_p:.4f}), '
            f'US continuous FAIL (t={us_cont_dm:.3f}, p={us_cont_p:.4f}). '
            '"Magnitude is noise, event is signal" works in US but NOT in TW. '
            'Paper 2 §5 becomes a cross-market heterogeneity paper (empirical contribution).'
        )
    elif us_bin_pass:
        scenario = 'A'
        verdict = (
            f'Scenario A: US binary PASS alone (t={us_bin_dm:.3f}, p={us_bin_p:.4f}). '
            'US binary EAV validates OOS. TW binary is OOS-noise exception. '
            'Paper 2 §5 universal-magnitude claim can be retained with US evidence.'
        )
    else:
        scenario = 'B'
        verdict = (
            f'Scenario B: Cross-market FAIL. '
            f'US binary t={us_bin_dm:.3f} p={us_bin_p:.4f} (FAIL joint), '
            f'US continuous t={us_cont_dm:.3f} p={us_cont_p:.4f} (FAIL joint). '
            'Combined with TW (both FAIL), Paper 2 §5 universal-magnitude '
            'claim must be withdrawn at OOS layer. §5 can only report IS '
            'pooled identification; OOS panel DM reject NOT achieved in '
            'either market or either spec.'
        )

    print(f'\n  SCENARIO: {scenario}')
    print(f'  VERDICT: {verdict}')

    # Paper 2 implication per scenario
    if scenario == 'A_BOTH':
        paper2_impl = (
            '§5 retained + strengthened ("universal-magnitude, cross-market '
            'OOS PASS"). Pivot: explain TW OOS null as market-microstructure '
            'noise (retail flow, shorter trading week, T+1 settlement).'
        )
    elif scenario == 'A':
        paper2_impl = (
            '§5 retained with US OOS leg. Narrative: "IS-identified panel '
            'effect validated OOS in US large-caps; TW OOS null reflects '
            'market-specific microstructure."'
        )
    elif scenario == 'C':
        paper2_impl = (
            '§5 pivots to cross-market heterogeneity subsection: "Event is '
            'signal in US, but TW shows additional heterogeneity that '
            'binary spec cannot capture. Magnitude (|surprise|) noise in '
            'both markets; event-day flag captures signal only in US."'
        )
    elif scenario == 'D':
        paper2_impl = (
            '§5 DELETED. Reverse sign in US suggests IS pooled θ_EAV is '
            'spurious; overfitting artifact. Paper 2 must restructure to '
            'avoid §5 as evidence.'
        )
    else:  # B
        paper2_impl = (
            '§5 universal-magnitude claim WITHDRAWN at OOS layer. Retain '
            'only IS pooled identification. Option 1: delete §5 OOS '
            'evidence; Option 2: retitle §5 to "IS-identified panel effect '
            'with OOS heterogeneity across markets"; Option 3: pivot to '
            'firm-characteristic heterogeneity analysis (K1148_d1 '
            'next_task list).'
        )

    # --- Plots -------------------------------------------------------
    print('\n[plots] Generating figures ...')

    # Plot 1: US binary vs US continuous (4 bars × 4 metrics)
    plot1_path = SCRIPT_DIR / 'binary_vs_continuous_us_oos.png'
    fig, axes = plt.subplots(1, 4, figsize=(16, 4.5))
    labels = ['US binary', 'US continuous']
    colors = ['steelblue', 'firebrick']

    # (a) IS θ_EAV Hessian t
    axes[0].bar(labels, [us_bin_t or 0, us_cont_t or 0],
                color=colors, edgecolor='black', alpha=0.8)
    axes[0].axhline(3.0, color='black', linestyle='--', label='Harvey t=3.0')
    axes[0].axhline(0, color='gray', linestyle=':')
    axes[0].set_ylabel('IS pooled θ_EAV t (Hessian)')
    axes[0].set_title('(a) IS θ_EAV identification')
    axes[0].legend()

    # (b) per-stock DM median per spec
    bin_med = us_binary['oos_dm'].get('panel_dm_median') or 0
    cont_med = us_continuous['oos_dm'].get('panel_dm_median') or 0
    axes[1].bar(labels, [bin_med, cont_med],
                color=colors, edgecolor='black', alpha=0.8)
    axes[1].axhline(0, color='gray', linestyle=':')
    axes[1].axhline(-2.0, color='black', linestyle='--', label='DM=-2')
    axes[1].set_ylabel('OOS per-stock DM median')
    axes[1].set_title('(b) OOS per-stock DM median')
    axes[1].legend()

    # (c) bootstrap panel DM t
    axes[2].bar(labels, [us_bin_dm or 0, us_cont_dm or 0],
                color=colors, edgecolor='black', alpha=0.8)
    axes[2].axhline(0, color='gray', linestyle=':')
    axes[2].axhline(-2.0, color='black', linestyle='--', label='Harvey t=-2')
    axes[2].set_ylabel('OOS bootstrap panel DM t')
    axes[2].set_title('(c) OOS bootstrap panel DM t')
    axes[2].legend()

    # (d) bootstrap one-sided p
    axes[3].bar(labels, [us_bin_p or 1.0, us_cont_p or 1.0],
                color=colors, edgecolor='black', alpha=0.8)
    axes[3].axhline(0.05, color='black', linestyle='--', label='α=0.05')
    axes[3].set_ylabel('OOS bootstrap one-sided p')
    axes[3].set_title('(d) OOS one-sided p (spec better)')
    axes[3].legend()

    plt.suptitle(f'K1148_d2: US Binary vs Continuous EAV — OOS panel DM '
                   f'(scenario={scenario})',
                   fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(plot1_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  → {plot1_path}')

    # Plot 2: TW vs US comparison (4 specs × 4 metrics)
    plot2_path = SCRIPT_DIR / 'tw_vs_us_comparison.png'
    fig, axes = plt.subplots(1, 4, figsize=(18, 5))
    all_labels = ['TW\nbinary', 'TW\ncontinuous', 'US\nbinary', 'US\ncontinuous']
    all_colors = ['steelblue', 'cornflowerblue', 'firebrick', 'indianred']

    # (a) IS θ_EAV (Hessian t)
    t_stats = [tw_bin_t or 0, tw_cont_t or 0, us_bin_t or 0, us_cont_t or 0]
    axes[0].bar(all_labels, t_stats,
                color=all_colors, edgecolor='black', alpha=0.85)
    axes[0].axhline(3.0, color='black', linestyle='--', label='Harvey t=3.0')
    axes[0].axhline(0, color='gray', linestyle=':')
    axes[0].set_ylabel('IS θ_EAV t (Hessian)')
    axes[0].set_title('(a) IS identification')
    axes[0].legend()

    # (b) OOS DM t
    dms = [tw_bin_dm or 0, tw_cont_dm or 0, us_bin_dm or 0, us_cont_dm or 0]
    axes[1].bar(all_labels, dms,
                color=all_colors, edgecolor='black', alpha=0.85)
    axes[1].axhline(-2.0, color='black', linestyle='--', label='Harvey t=-2')
    axes[1].axhline(0, color='gray', linestyle=':')
    axes[1].set_ylabel('OOS panel DM t (lower is better)')
    axes[1].set_title('(b) OOS panel DM t')
    axes[1].legend()

    # (c) OOS one-sided p
    ps = [tw_bin_p or 1.0, tw_cont_p or 1.0, us_bin_p or 1.0, us_cont_p or 1.0]
    axes[2].bar(all_labels, ps,
                color=all_colors, edgecolor='black', alpha=0.85)
    axes[2].axhline(0.05, color='black', linestyle='--', label='α=0.05')
    axes[2].set_ylabel('OOS one-sided p')
    axes[2].set_title('(c) OOS one-sided p')
    axes[2].legend()

    # (d) Harvey joint PASS flag (|t|>=2 AND p<0.05)
    def joint_flag(dm, pp):
        if dm is None or pp is None:
            return 0
        return 1 if (dm <= -2.0 and pp < 0.05) else 0
    flags = [
        joint_flag(tw_bin_dm, tw_bin_p),
        joint_flag(tw_cont_dm, tw_cont_p),
        joint_flag(us_bin_dm, us_bin_p),
        joint_flag(us_cont_dm, us_cont_p),
    ]
    axes[3].bar(all_labels, flags,
                color=['green' if f else 'gray' for f in flags],
                edgecolor='black', alpha=0.85)
    axes[3].set_ylim(-0.1, 1.3)
    axes[3].set_yticks([0, 1])
    axes[3].set_yticklabels(['FAIL', 'PASS'])
    axes[3].set_ylabel('Harvey joint PASS (t≤-2 AND p<0.05)')
    axes[3].set_title('(d) Joint PASS flag')

    plt.suptitle(f'K1148_d2: TW vs US — Binary/Continuous EAV OOS panel DM '
                   f'(scenario={scenario})', fontsize=12, y=1.02)
    plt.tight_layout()
    plt.savefig(plot2_path, dpi=120, bbox_inches='tight')
    plt.close()
    print(f'  → {plot2_path}')

    # --- Save results JSON ------------------------------------------
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'US EAV binary-vs-continuous OOS panel DM '
                 '(cross-market validation of Paper 2 §5)',
        'proposer': 'Claude (Paper 2 §5 cross-market OOS validation)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': 'yfinance daily close (K1147 cache 2014-2025) + '
                       'yfinance get_earnings_dates',
        'data_period': f'{DATA_START} ~ {DATA_END}',
        'is_period': f'{DATA_START} ~ 2019-12-31',
        'oos_period': f'{OOS_START} ~ {DATA_END}',
        'tickers_tried': US_TICKERS,
        'n_stocks_loaded': len(stocks_loaded),
        'n_stock_bootstrap_reps': N_STOCK_BOOTSTRAP,
        'winsorization': winsor_info,
        'us_binary': us_binary,
        'us_continuous': us_continuous,
        'comparison_tw_d1': {
            'tw_binary_theta': tw_bin_theta,
            'tw_binary_t_hessian': tw_bin_t,
            'tw_binary_panel_dm_t': tw_bin_dm,
            'tw_binary_panel_dm_p_one': tw_bin_p,
            'tw_continuous_theta': tw_cont_theta,
            'tw_continuous_t_hessian': tw_cont_t,
            'tw_continuous_panel_dm_t': tw_cont_dm,
            'tw_continuous_panel_dm_p_one': tw_cont_p,
        },
        'four_row_table': [
            {'spec': 'US binary',      'theta_IS': us_bin_theta,  't_hessian_IS': us_bin_t,  'panel_DM_t_OOS': us_bin_dm,  'panel_DM_p_OOS': us_bin_p,  'joint_pass': us_bin_pass},
            {'spec': 'US continuous',  'theta_IS': us_cont_theta, 't_hessian_IS': us_cont_t, 'panel_DM_t_OOS': us_cont_dm, 'panel_DM_p_OOS': us_cont_p, 'joint_pass': us_cont_pass},
            {'spec': 'TW binary (d1)', 'theta_IS': tw_bin_theta,  't_hessian_IS': tw_bin_t,  'panel_DM_t_OOS': tw_bin_dm,  'panel_DM_p_OOS': tw_bin_p,  'joint_pass': False},
            {'spec': 'TW continuous',  'theta_IS': tw_cont_theta, 't_hessian_IS': tw_cont_t, 'panel_DM_t_OOS': tw_cont_dm, 'panel_DM_p_OOS': tw_cont_p, 'joint_pass': False},
        ],
        'scenario': scenario,
        'verdict': verdict,
        'paper2_implication': paper2_impl,
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results → {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  CORE VERDICT: {verdict}\n')
    print(f'  Paper 2 §5 implication: {paper2_impl}\n')


if __name__ == '__main__':
    main()
