#!/usr/bin/env python3
"""
K1147: A4f-EAV pooled panel estimation across N=30 US S&P 500 large-caps
========================================================================
[提出: Claude (承接 K1145 next_tasks), 執行: Claude]

Cross-market validation of K1145 universal-magnitude θ_EAV finding.

Context:
  K1145 found pooled θ_EAV = +6.36e-5 (cluster bootstrap t=+5.24,
  within-stock placebo p=0/60) in N=31 TW stocks.

  Open question (K1145 next_tasks K1147): Is this a **global volatility
  regularity** (also present in US large-caps) or **TW-specific**?

  Decision tree:
    - US pooled t > 3, BH PASS → universal global regularity,
      Paper 2 contribution boost
    - US pooled t < 2, NS       → TW-specific, Paper 2 adds caveat
    - 2 < t < 3                 → ambiguous (N=50 extension)

Pooled spec (identical to K1145):
    σ²_{i,t} = g_{i,t} · τ_{i,t}
    g_{i,t} = GJR(1,1)_i  (stock-specific ω_i, α_i, γ_i, β_i)
    τ_{i,t} = max(θ₀_i + θ_VIX · VIX²_{t-1} + θ_EAV · EAV_{i,t-1}, ε)

Methodology:
  - BCD (block coordinate descent) pooled MLE
  - Cluster bootstrap (stock-level resample, n=150)
  - 3 EAV-window robustness (1d / 3d / 5d)
  - Drop-5 × 5 seeds robustness
  - Placebo (within-stock EAV permutation, 60 reps)
  - Cross-market comparison with K1145 TW result

Lookahead discipline:
  - VIX_{t-1}: CBOE close of prior US trading day (already settled)
  - EAV_{i,t-1}: announcement dates from yfinance earnings_dates API
    filtered to dates strictly before today (i.e., already announced);
    in likelihood we further lag by 1 trading day
  - Same-market alignment (US stock vs US VIX) — no cross-tz leakage
  - Random seed=42

Data:
  - yfinance daily close 2014-2025 (auto_adjust)
  - ^VIX cache
  - yfinance get_earnings_dates(limit=100) per ticker
  - 30 pre-registered S&P 500 large-caps by well-known market cap

Author: VolPred Research System.
Date: 2026-04-13.
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

GLOBAL_SEED = 42
np.random.seed(GLOBAL_SEED)
GLOBAL_RNG = np.random.default_rng(GLOBAL_SEED)

START_TIME = time.time()
EXPERIMENT_ID = 'K1147'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_CACHE_DIR = SCRIPT_DIR / 'data'
DATA_CACHE_DIR.mkdir(exist_ok=True, parents=True)
EARNINGS_CACHE = DATA_CACHE_DIR / 'earnings_dates.json'
RESULTS_PATH = SCRIPT_DIR / 'k1147_results.json'

DATA_START = '2014-01-01'
DATA_END = '2025-12-31'

# Pre-registered N=30 US S&P 500 large-caps (well-known, stable, high liquidity)
TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B',
    'UNH', 'V', 'JPM', 'WMT', 'MA', 'JNJ', 'XOM', 'PG', 'HD', 'CVX',
    'ABBV', 'AVGO', 'COST', 'PEP', 'KO', 'MRK', 'ADBE', 'CSCO', 'TMO',
    'CRM', 'MCD', 'ABT',
]


# ==========================================================================
# Data loading
# ==========================================================================
def load_earnings_yfinance(ticker, force_refresh=False):
    """Load earnings announcement dates for a US ticker via yfinance API.

    Uses get_earnings_dates(limit=100) which returns ~25 years of history.
    Filters to dates strictly BEFORE today (i.e., already announced).
    Returns sorted DatetimeIndex (tz-naive, date-only).

    Cache: stores per-ticker list of ISO dates in earnings_dates.json to
    avoid repeated API calls.
    """
    cache = {}
    if EARNINGS_CACHE.exists() and not force_refresh:
        with open(EARNINGS_CACHE) as f:
            cache = json.load(f)
    if ticker in cache:
        dates = [pd.Timestamp(d) for d in cache[ticker]]
        return pd.DatetimeIndex(dates)

    # Fetch via API
    try:
        tk = yf.Ticker(ticker)
        df = tk.get_earnings_dates(limit=100)
        if df is None or len(df) == 0:
            return pd.DatetimeIndex([])
        # Filter: past announcements only (strictly before today, no
        # future estimated dates)
        today = pd.Timestamp.now(tz=df.index.tz if df.index.tz else None)
        past = df[df.index < today]
        # Strip tz + time; keep date only
        date_list = sorted(set(past.index.tz_localize(None).normalize().tolist()))
        # Clip to data window
        date_list = [d for d in date_list
                     if pd.Timestamp(DATA_START) <= d <= pd.Timestamp(DATA_END)]
        cache[ticker] = [d.isoformat() for d in date_list]
        with open(EARNINGS_CACHE, 'w') as f:
            json.dump(cache, f, indent=2)
        # Rate-limit between calls
        time.sleep(1.0)
        return pd.DatetimeIndex(date_list)
    except Exception as e:
        print(f'    [earnings API fail] {ticker}: {e}')
        return pd.DatetimeIndex([])


def cached_download(ticker):
    """Download + cache daily OHLCV. Converts tickers to yfinance format
    (preserves BRK-B -> BRK-B)."""
    safe_name = ticker.replace('^', 'IDX_').replace('-', '_')
    cache_path = DATA_CACHE_DIR / f"{safe_name}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)
    print(f'    [download] {ticker} ...')
    raw = yf.download(ticker, start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=True)
    if raw is None or len(raw) == 0:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    try:
        raw.to_parquet(cache_path)
    except Exception:
        pass
    return raw


def build_eav_series(trading_days, ann_dates, window):
    """EAV flag: forward-from-announcement window.
       EAV[t]=1 iff t in {ann_i, ann_i+1, ..., ann_i+window-1}.
    Lookahead-safety: EAV lagged 1 day inside likelihood.
    """
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


def load_one_stock(ticker, eav_window=1):
    raw = cached_download(ticker)
    if raw is None:
        return None
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix_raw = cached_download('^VIX')
    if vix_raw is None:
        return None
    vix = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]
    ann_dates = load_earnings_yfinance(ticker)
    eav_arr = build_eav_series(df.index, ann_dates, eav_window)
    if len(df) < 500 or eav_arr.sum() < 15:
        return None
    return {
        'ticker': ticker,
        'r': df['r'].values,
        'vix': df['vix'].values,
        'eav': eav_arr,
        'index': df.index,
        'n_obs': len(df),
        'n_events': int(eav_arr.sum()),
    }


# ==========================================================================
# Per-stock A4f-EAV inner (shared θ_VIX, θ_EAV held fixed) — same as K1145
# ==========================================================================
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
    for t in range(n):
        if t == 0:
            vl = vix[0]
            el = eav[0]
        else:
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


def per_stock_neg_loglik(stock_params, r, vix, eav, theta_vix, theta_eav):
    theta0, omega_g, alpha, gamma_p, beta_p = stock_params
    return _negll_numba(float(theta0), float(omega_g), float(alpha),
                         float(gamma_p), float(beta_p),
                         r, vix, eav, float(theta_vix), float(theta_eav))


def fit_one_stock_given_shared(stock, theta_vix, theta_eav, init=None):
    r = stock['r']
    vix = stock['vix']
    eav = stock['eav']
    var0 = np.var(r)
    if init is None:
        starts = [
            [var0 * 0.10, 0.05, 0.05, 0.05, 0.90],
            [var0 * 0.05, 0.10, 0.03, 0.08, 0.88],
            [var0 * 0.20, 0.02, 0.08, 0.10, 0.80],
        ]
    else:
        starts = [init,
                  [var0 * 0.10, 0.05, 0.05, 0.05, 0.90]]
    bounds = [
        (1e-8, 1e-2),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    best_ll = np.inf
    best_p = None
    for s in starts:
        try:
            res = optimize.minimize(
                per_stock_neg_loglik, s, args=(r, vix, eav,
                                                theta_vix, theta_eav),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 400, 'ftol': 1e-9},
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p, best_ll


# ==========================================================================
# BCD
# ==========================================================================
def pooled_loglik_given_shared(stocks, stock_params_list, theta_vix, theta_eav):
    total = 0.0
    for st, p in zip(stocks, stock_params_list):
        total += per_stock_neg_loglik(p, st['r'], st['vix'], st['eav'],
                                       theta_vix, theta_eav)
    return total


def shared_objective(shared, stocks, stock_params_list):
    theta_vix, theta_eav = shared
    return pooled_loglik_given_shared(stocks, stock_params_list,
                                       theta_vix, theta_eav)


def fit_pooled_panel(stocks, max_outer=10, init_vix=1e-7, init_eav=5e-5,
                     verbose=True, time_budget=None):
    t_start = time.time()
    theta_vix = float(init_vix)
    theta_eav = float(init_eav)
    stock_params_list = [None] * len(stocks)
    prev_total_ll = np.inf
    history = []
    converged = False

    for outer in range(max_outer):
        if time_budget is not None and time.time() - t_start > time_budget:
            if verbose:
                print(f'    [BCD] outer {outer}: time budget reached')
            break
        total_negll = 0.0
        for i, st in enumerate(stocks):
            p_init = stock_params_list[i] if stock_params_list[i] is not None else None
            p, ll = fit_one_stock_given_shared(st, theta_vix, theta_eav, init=p_init)
            if p is None:
                if stock_params_list[i] is None:
                    raise RuntimeError(f'Stock {st["ticker"]} initial fit failed')
                continue
            stock_params_list[i] = p
            total_negll += ll
        bounds_shared = [(1e-9, 1e-3), (-1e-2, 1e-2)]
        res = optimize.minimize(
            shared_objective, [theta_vix, theta_eav],
            args=(stocks, stock_params_list),
            method='L-BFGS-B', bounds=bounds_shared,
            options={'maxiter': 200, 'ftol': 1e-10},
        )
        new_vix, new_eav = res.x
        new_negll = res.fun
        d_vix = abs(new_vix - theta_vix)
        d_eav = abs(new_eav - theta_eav)
        d_ll = prev_total_ll - new_negll
        if verbose:
            print(f'    [BCD outer {outer}] θ_VIX={new_vix:.3e}, '
                  f'θ_EAV={new_eav:+.4e}, pooled_negll={new_negll:.2f}, '
                  f'Δll={d_ll:+.4f}, Δθ_eav={d_eav:.2e}')
        history.append({
            'outer_iter': outer,
            'theta_vix': float(new_vix),
            'theta_eav': float(new_eav),
            'pooled_negll': float(new_negll),
        })
        theta_vix, theta_eav = float(new_vix), float(new_eav)
        if outer >= 1 and d_ll < 1e-2 and d_eav < 1e-7:
            converged = True
            if verbose:
                print('    [BCD] converged')
            break
        prev_total_ll = new_negll

    final_total_negll = 0.0
    final_params_list = []
    for i, st in enumerate(stocks):
        p, ll = fit_one_stock_given_shared(st, theta_vix, theta_eav,
                                            init=stock_params_list[i])
        if p is None:
            p = stock_params_list[i]
            ll = per_stock_neg_loglik(p, st['r'], st['vix'], st['eav'],
                                       theta_vix, theta_eav)
        final_params_list.append(p)
        final_total_negll += ll
    return {
        'theta_vix': theta_vix,
        'theta_eav': theta_eav,
        'per_stock_params': [p.tolist() for p in final_params_list],
        'pooled_loglik': float(-final_total_negll),
        'pooled_negll': float(final_total_negll),
        'n_outer_iters': len(history),
        'converged': converged,
        'history': history,
    }


def hessian_se_theta_eav(stocks, stock_params_list, theta_vix, theta_eav,
                          eps_scale=1e-3):
    ll0 = pooled_loglik_given_shared(stocks, stock_params_list,
                                      theta_vix, theta_eav)
    eps = max(abs(theta_eav) * eps_scale, eps_scale * 1e-4)
    ll_p = pooled_loglik_given_shared(stocks, stock_params_list,
                                       theta_vix, theta_eav + eps)
    ll_m = pooled_loglik_given_shared(stocks, stock_params_list,
                                       theta_vix, theta_eav - eps)
    h22 = (ll_p - 2 * ll0 + ll_m) / (eps ** 2)
    if h22 > 0 and np.isfinite(h22):
        return float(np.sqrt(1.0 / h22))
    return None


def cluster_bootstrap_theta_eav(stocks, n_boot=150, seed=42,
                                  init_vix=1e-7, init_eav=5e-5,
                                  inner_max_outer=2,
                                  per_boot_time_budget=45):
    rng = np.random.default_rng(seed)
    N = len(stocks)
    draws = []
    for b in range(n_boot):
        idx = rng.integers(0, N, size=N)
        boot = [stocks[i] for i in idx]
        try:
            fit = fit_pooled_panel(boot, max_outer=inner_max_outer,
                                    init_vix=init_vix, init_eav=init_eav,
                                    verbose=False,
                                    time_budget=per_boot_time_budget)
            draws.append(fit['theta_eav'])
        except Exception as e:
            print(f'    [boot {b}] fail: {e}')
            continue
    return np.array(draws)


def bh_adjust(pvals):
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adj_sorted = ranked * n / (np.arange(1, n + 1))
    for i in range(n - 2, -1, -1):
        adj_sorted[i] = min(adj_sorted[i], adj_sorted[i + 1])
    adj = np.empty(n)
    adj[order] = np.minimum(adj_sorted, 1.0)
    return adj


# ==========================================================================
# Main
# ==========================================================================
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: A4f-EAV pooled panel estimation (N=30 US large-caps)')
    print(f'{"=" * 72}\n')
    print(f'Tickers ({len(TICKERS)}): {TICKERS}\n')

    # Load
    print('[1/6] Loading stocks (EAV window=1) ...')
    stocks_w1 = []
    for tk in TICKERS:
        st = load_one_stock(tk, eav_window=1)
        if st is None:
            print(f'    SKIP {tk}: insufficient data')
            continue
        stocks_w1.append(st)
        print(f'    {tk}: n_obs={st["n_obs"]}, n_events={st["n_events"]}')
    print(f'  Loaded {len(stocks_w1)}/{len(TICKERS)} stocks\n')
    if len(stocks_w1) < 15:
        print('  ABORT: < 15 stocks loaded')
        sys.exit(1)
    N_actual = len(stocks_w1)

    # Diagnostic
    print('[2/6] Pre-fit panel diagnostic ...')
    all_r = np.concatenate([s['r'] for s in stocks_w1])
    print(f'  Pooled obs: {len(all_r):,}')
    print(f'  Mean r={np.mean(all_r):+.4e}, std={np.std(all_r):.4e}')
    print(f'  Skew={stats.skew(all_r):+.3f}, kurt={stats.kurtosis(all_r):+.3f}')
    print(f'  Mean events per stock: {np.mean([s["n_events"] for s in stocks_w1]):.1f}')
    print()

    # Main pooled BCD
    print('[3/6] Pooled BCD fit (EAV window=1, primary) ...')
    fit_w1 = fit_pooled_panel(stocks_w1, max_outer=8, verbose=True,
                               time_budget=600)
    theta_eav_main = fit_w1['theta_eav']
    theta_vix_main = fit_w1['theta_vix']
    print(f'\n  → θ_VIX = {theta_vix_main:.4e}')
    print(f'  → θ_EAV = {theta_eav_main:+.4e}')
    print(f'  → pooled loglik = {fit_w1["pooled_loglik"]:.2f}')
    print(f'  → converged = {fit_w1["converged"]}')

    # Hessian
    print('\n  Hessian SE for θ_EAV ...')
    se_hessian = hessian_se_theta_eav(
        stocks_w1, [np.array(p) for p in fit_w1['per_stock_params']],
        theta_vix_main, theta_eav_main,
    )
    t_hessian = (theta_eav_main / se_hessian) if (se_hessian and se_hessian > 0) else np.nan
    print(f'  Hessian SE={se_hessian}, t={t_hessian}')

    # Bootstrap
    print('\n[4/6] Stock-clustered block bootstrap (gold-standard) ...')
    n_boot = 150
    boot_t0 = time.time()
    boot_draws = cluster_bootstrap_theta_eav(
        stocks_w1, n_boot=n_boot, seed=GLOBAL_SEED,
        init_vix=theta_vix_main, init_eav=theta_eav_main,
        inner_max_outer=2, per_boot_time_budget=45,
    )
    print(f'  bootstrap draws: {len(boot_draws)}/{n_boot} '
          f'(elapsed={time.time() - boot_t0:.1f}s)')
    if len(boot_draws) >= 30:
        boot_se = float(np.std(boot_draws, ddof=1))
        boot_mean = float(np.mean(boot_draws))
        boot_ci_lo = float(np.percentile(boot_draws, 2.5))
        boot_ci_hi = float(np.percentile(boot_draws, 97.5))
        boot_t = theta_eav_main / boot_se if boot_se > 0 else np.nan
        boot_p = 2 * min(
            np.mean(boot_draws <= 0),
            np.mean(boot_draws >= 0),
        )
        boot_p = float(boot_p)
    else:
        boot_se = boot_mean = boot_ci_lo = boot_ci_hi = boot_t = boot_p = None
    print(f'  bootstrap mean={boot_mean}, SE={boot_se}')
    print(f'  bootstrap 95% CI = [{boot_ci_lo}, {boot_ci_hi}]')
    print(f'  bootstrap t={boot_t}, p={boot_p}')

    # Robustness R1: EAV windows
    print('\n[5/6] Robustness — alternate EAV definitions ...')
    rob_eav_results = {}
    for window in (3, 5):
        print(f'\n  R1 EAV window={window}:')
        stocks_w = []
        for tk in TICKERS:
            st = load_one_stock(tk, eav_window=window)
            if st is None:
                continue
            stocks_w.append(st)
        if len(stocks_w) < 15:
            print(f'    SKIP — only {len(stocks_w)} stocks')
            continue
        fit_w = fit_pooled_panel(stocks_w, max_outer=6, verbose=False,
                                  init_vix=theta_vix_main,
                                  init_eav=theta_eav_main,
                                  time_budget=300)
        se_w = hessian_se_theta_eav(
            stocks_w, [np.array(p) for p in fit_w['per_stock_params']],
            fit_w['theta_vix'], fit_w['theta_eav'],
        )
        t_w = (fit_w['theta_eav'] / se_w) if (se_w and se_w > 0) else np.nan
        rob_eav_results[f'window_{window}'] = {
            'theta_vix': fit_w['theta_vix'],
            'theta_eav': fit_w['theta_eav'],
            'theta_eav_se_hessian': se_w,
            'theta_eav_t_hessian': float(t_w) if np.isfinite(t_w) else None,
            'pooled_loglik': fit_w['pooled_loglik'],
            'n_stocks': len(stocks_w),
            'converged': fit_w['converged'],
        }
        print(f'    θ_EAV={fit_w["theta_eav"]:+.4e}, SE={se_w}, t={t_w}')

    # Robustness R2: drop-out
    print('\n  R2 Drop-out 5 random stocks x 5 seeds:')
    dropout_results = []
    for sd in (42, 43, 44, 45, 46):
        rng = np.random.default_rng(sd)
        drop_idx = set(rng.choice(len(stocks_w1), size=5, replace=False).tolist())
        sub = [s for i, s in enumerate(stocks_w1) if i not in drop_idx]
        dropped = [stocks_w1[i]['ticker'] for i in drop_idx]
        try:
            fit_sub = fit_pooled_panel(
                sub, max_outer=5, verbose=False,
                init_vix=theta_vix_main, init_eav=theta_eav_main,
                time_budget=240,
            )
            se_sub = hessian_se_theta_eav(
                sub, [np.array(p) for p in fit_sub['per_stock_params']],
                fit_sub['theta_vix'], fit_sub['theta_eav'],
            )
            t_sub = (fit_sub['theta_eav'] / se_sub) if (se_sub and se_sub > 0) else np.nan
            dropout_results.append({
                'seed': sd,
                'dropped_tickers': dropped,
                'theta_eav': fit_sub['theta_eav'],
                'theta_eav_se': se_sub,
                'theta_eav_t': float(t_sub) if np.isfinite(t_sub) else None,
                'n_stocks': len(sub),
            })
            print(f'    seed={sd}, dropped={dropped}, θ_EAV={fit_sub["theta_eav"]:+.3e}, t={t_sub}')
        except Exception as e:
            print(f'    seed={sd}: FAIL {e}')

    # BH-FDR
    print('\n  BH-FDR multi-test correction:')
    p_hessian = float(2 * (1 - stats.norm.cdf(abs(t_hessian)))) if np.isfinite(t_hessian) else 1.0
    p_boot = boot_p if boot_p is not None else 1.0
    pvec = [p_hessian, p_boot]
    pnames = ['pooled_hessian', 'pooled_bootstrap']
    bh_adj = bh_adjust(pvec)
    bh_table = [{'name': n, 'raw_p': float(p), 'bh_adj_p': float(bp)}
                for n, p, bp in zip(pnames, pvec, bh_adj)]
    for row in bh_table:
        print(f'    {row["name"]}: raw_p={row["raw_p"]:.4f}, BH_adj_p={row["bh_adj_p"]:.4f}')

    # Cross-market comparison with K1145 TW
    TW_POOLED_THETA_EAV = 6.3622e-5
    TW_BOOT_SE = 1.21e-5
    TW_BOOT_T = 5.24
    print('\n  Cross-market comparison (K1147 US vs K1145 TW):')
    print(f'    K1145 TW pooled θ_EAV = {TW_POOLED_THETA_EAV:+.3e} (boot t={TW_BOOT_T:.2f})')
    print(f'    K1147 US pooled θ_EAV = {theta_eav_main:+.3e} (boot t={boot_t})')
    direction_match = bool(np.sign(theta_eav_main) == np.sign(TW_POOLED_THETA_EAV))
    # Informal magnitude ratio
    magnitude_ratio = float(theta_eav_main / TW_POOLED_THETA_EAV) if TW_POOLED_THETA_EAV != 0 else None
    print(f'    Direction match: {direction_match}')
    print(f'    Magnitude ratio US/TW: {magnitude_ratio}')

    # Verdict
    primary_pass = (
        np.isfinite(t_hessian) and abs(t_hessian) > 3.0 and
        bh_table[0]['bh_adj_p'] < 0.05
    )
    boot_pass = (
        boot_p is not None and bh_table[1]['bh_adj_p'] < 0.05 and
        boot_t is not None and abs(boot_t) > 3.0
    )
    # Cross-market verdict
    if boot_pass and direction_match:
        cross_verdict = 'UNIVERSAL — US pooled θ_EAV PASS and direction matches K1145 TW → global regularity'
    elif boot_t is not None and abs(boot_t) < 2.0:
        cross_verdict = 'TW-SPECIFIC — US pooled θ_EAV NS → TW-specific, Paper 2 needs cross-market caveat'
    elif boot_t is not None and 2.0 <= abs(boot_t) <= 3.0:
        cross_verdict = 'AMBIGUOUS — US pooled t in (2,3), needs N=50 extension or Codex second opinion'
    else:
        cross_verdict = 'INCONCLUSIVE — check bootstrap draws'
    print(f'\n  CROSS-MARKET VERDICT: {cross_verdict}')

    # Plots
    print('\n[6/6] Plots ...')
    plot1_path = SCRIPT_DIR / 'k1147_tw_vs_us_comparison.png'
    fig, ax = plt.subplots(1, 1, figsize=(8, 4.5))
    markets = ['K1145 TW\n(N=31)', 'K1147 US\n(N=' + str(N_actual) + ')']
    thetas = [TW_POOLED_THETA_EAV, theta_eav_main]
    ses = [TW_BOOT_SE, boot_se if boot_se else 0]
    xpos = np.arange(len(markets))
    colors = ['steelblue', 'darkred']
    ax.bar(xpos, thetas, yerr=[1.96 * s for s in ses],
           color=colors, edgecolor='black', alpha=0.75, capsize=6)
    ax.axhline(0, color='gray', linestyle=':')
    ax.set_xticks(xpos)
    ax.set_xticklabels(markets)
    ax.set_ylabel(r'Pooled $\theta_{EAV}$')
    ax.set_title(r'K1147 Cross-market: TW vs US pooled $\theta_{EAV}$ (error bars 95% CI)')
    for i, (v, s) in enumerate(zip(thetas, ses)):
        ax.text(i, v + 1.96 * s + max(thetas) * 0.05,
                f'{v:+.2e}\n(boot t={TW_BOOT_T if i == 0 else boot_t})',
                ha='center', fontsize=9)
    plt.tight_layout()
    plt.savefig(plot1_path, dpi=120)
    plt.close()
    print(f'  -> {plot1_path}')

    # Plot 2: robustness barplot
    plot2_path = SCRIPT_DIR / 'k1147_robustness_barplot.png'
    fig, ax = plt.subplots(1, 1, figsize=(10, 4.5))
    labels = ['main(w=1)']
    vals = [theta_eav_main]
    ses_r = [se_hessian if se_hessian else 0]
    for w in (3, 5):
        k = f'window_{w}'
        if k in rob_eav_results:
            labels.append(f'EAV w={w}')
            vals.append(rob_eav_results[k]['theta_eav'])
            ses_r.append(rob_eav_results[k]['theta_eav_se_hessian'] or 0)
    for d in dropout_results:
        labels.append(f'drop_s{d["seed"]}')
        vals.append(d['theta_eav'])
        ses_r.append(d['theta_eav_se'] or 0)
    xpos = np.arange(len(labels))
    ax.bar(xpos, vals, yerr=[1.96 * s for s in ses_r],
           color=['red'] + ['orange'] * 2 + ['steelblue'] * len(dropout_results),
           edgecolor='black', alpha=0.75, capsize=4)
    ax.axhline(0, color='gray', linestyle=':')
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9)
    ax.set_ylabel(r'Pooled $\theta_{EAV}$ (US)')
    ax.set_title(r'K1147 Robustness: US pooled $\theta_{EAV}$ across EAV defs and drop-outs')
    plt.tight_layout()
    plt.savefig(plot2_path, dpi=120)
    plt.close()
    print(f'  -> {plot2_path}')

    # Save
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'A4f-EAV pooled panel estimation across N=30 US S&P 500 large-caps (cross-market validation of K1145)',
        'proposer': 'Claude (承接 K1145 next_tasks K1147)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': 'yfinance daily close 2014-2025; yfinance get_earnings_dates API',
        'data_period': f'{DATA_START} ~ {DATA_END}',
        'tickers': TICKERS,
        'n_stocks_loaded': N_actual,
        'pooled_obs': int(sum(s['n_obs'] for s in stocks_w1)),
        'panel_diagnostic': {
            'pooled_n': int(len(all_r)),
            'mean_r': float(np.mean(all_r)),
            'std_r': float(np.std(all_r)),
            'skew': float(stats.skew(all_r)),
            'kurt_excess': float(stats.kurtosis(all_r)),
            'mean_events_per_stock': float(np.mean([s['n_events'] for s in stocks_w1])),
        },
        'main_fit_eav_window_1': {
            'theta_vix': theta_vix_main,
            'theta_eav': theta_eav_main,
            'theta_eav_se_hessian': se_hessian,
            'theta_eav_t_hessian': float(t_hessian) if np.isfinite(t_hessian) else None,
            'theta_eav_p_hessian': float(p_hessian),
            'pooled_loglik': fit_w1['pooled_loglik'],
            'n_outer_iters': fit_w1['n_outer_iters'],
            'converged': fit_w1['converged'],
            'history': fit_w1['history'],
            'per_stock_params': fit_w1['per_stock_params'],
            'per_stock_tickers': [s['ticker'] for s in stocks_w1],
        },
        'cluster_bootstrap': {
            'n_boot_target': n_boot,
            'n_boot_completed': int(len(boot_draws)),
            'mean': boot_mean,
            'se': boot_se,
            'ci_95': [boot_ci_lo, boot_ci_hi] if boot_se is not None else None,
            't_stat': float(boot_t) if (boot_t is not None and np.isfinite(boot_t)) else None,
            'p_value': boot_p,
            'draws': boot_draws.tolist(),
        },
        'robustness_eav_window': rob_eav_results,
        'robustness_dropout': dropout_results,
        'bh_fdr_table': bh_table,
        'cross_market': {
            'k1145_tw_theta_eav': TW_POOLED_THETA_EAV,
            'k1145_tw_boot_se': TW_BOOT_SE,
            'k1145_tw_boot_t': TW_BOOT_T,
            'k1147_us_theta_eav': theta_eav_main,
            'k1147_us_boot_se': boot_se,
            'k1147_us_boot_t': float(boot_t) if (boot_t is not None and np.isfinite(boot_t)) else None,
            'direction_match': direction_match,
            'magnitude_ratio_us_over_tw': magnitude_ratio,
            'cross_market_verdict': cross_verdict,
        },
        'verdict': {
            'primary_t_pass_h0_zero': bool(primary_pass),
            'boot_pass': bool(boot_pass),
            'core_verdict_text': cross_verdict,
        },
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results -> {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  CORE CROSS-MARKET VERDICT: {cross_verdict}\n')


if __name__ == '__main__':
    main()
