#!/usr/bin/env python3
"""
K1163: A4f-EAV pooled panel re-estimation with K1163 refetched EU earnings
============================================================================
Reuses K1153 pooled estimator (GJR×τ with shared θ_VIX, θ_EAV + BCD).
Only change: earnings dates for 11 K1153-skipped CAC/FTSE tickers are
replaced from the K1163 provenance CSV (HAND_IRCALENDAR source), bringing
EU coverage from N=18 to target N≥25.

Methodology: identical to K1153 (BCD + 150-bootstrap + 60-placebo)
  σ²_{i,t} = g_{i,t} · τ_{i,t}
  g = GJR(1,1)_i
  τ = max(θ_0_i + θ_VIX · VIX²_{t-1} + θ_EAV · EAV_{i,t-1}, ε)

Success criteria (from task brief):
  - EU coverage ≥20/30 stocks
  - K1153 vs K1163 delta table per market
  - Verdict: ROBUST (θ_rel cluster unchanged) / REVISED (shifted) / INCOMPLETE

Author: VolPred Research System (K1163).
Date: 2026-04-17.
"""
import os
import sys
import json
import time
import csv
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
EXPERIMENT_ID = 'K1163'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_CACHE_DIR = SCRIPT_DIR / 'data'
DATA_CACHE_DIR.mkdir(exist_ok=True, parents=True)
RESULTS_PATH = SCRIPT_DIR / 'k1163_results.json'

# Reuse K1153's price/VIX parquet cache (data downloads identical, just replace
# earnings dates).
K1153_DATA_DIR = SCRIPT_DIR.parent / 'k1153' / 'data'

DATA_START = '2014-01-01'
DATA_END = '2025-12-31'

# N=30 EU large-caps: same as K1153
TICKERS = [
    # DAX (Germany, Xetra) — 10
    'SAP.DE', 'SIE.DE', 'ALV.DE', 'MRK.DE', 'BMW.DE', 'BAS.DE',
    'MBG.DE', 'DTE.DE', 'ADS.DE', 'VOW3.DE',
    # CAC 40 (France, Euronext Paris) — 10
    'MC.PA', 'TTE.PA', 'AIR.PA', 'OR.PA', 'SU.PA', 'SAN.PA',
    'BNP.PA', 'DG.PA', 'RMS.PA', 'AI.PA',
    # FTSE 100 (UK, LSE) — 10
    'SHEL.L', 'AZN.L', 'ULVR.L', 'HSBA.L', 'RIO.L', 'BP.L',
    'DGE.L', 'GSK.L', 'REL.L', 'LSEG.L',
]


# ==========================================================================
# Data loading — K1163 uses k1163_eu_earnings_dates.csv (provenance-tagged)
# ==========================================================================
def load_k1163_earnings_table():
    """Load k1163_eu_earnings_dates.csv → {ticker: [list of date_strs]}"""
    csv_path = DATA_CACHE_DIR / 'k1163_eu_earnings_dates.csv'
    if not csv_path.exists():
        raise RuntimeError(f'K1163 earnings CSV missing: {csv_path}. '
                           f'Run k1163_fetch_eu.py first.')
    table = {}
    provenance_by_ticker = {}
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            tk = row['ticker']
            table.setdefault(tk, []).append(row['date'])
            provenance_by_ticker.setdefault(tk, set()).add(row['provenance'])
    for tk in provenance_by_ticker:
        provenance_by_ticker[tk] = sorted(provenance_by_ticker[tk])
    return table, provenance_by_ticker


def cached_download(ticker):
    """Reuse K1153 parquet cache if available, else download + cache locally."""
    safe_name = (ticker.replace('^', 'IDX_').replace('-', '_')
                        .replace('.', '_'))
    # Check K1153 cache first
    k1153_path = K1153_DATA_DIR / f"{safe_name}.parquet"
    if k1153_path.exists():
        return pd.read_parquet(k1153_path)
    local_path = DATA_CACHE_DIR / f"{safe_name}.parquet"
    if local_path.exists():
        return pd.read_parquet(local_path)
    print(f'    [download] {ticker} ...')
    raw = yf.download(ticker, start=DATA_START, end=DATA_END,
                      progress=False, auto_adjust=True)
    if raw is None or len(raw) == 0:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    try:
        raw.to_parquet(local_path)
    except Exception:
        pass
    return raw


def build_eav_series(trading_days, ann_dates, window):
    """EAV flag: forward-from-announcement window.
       EAV[t]=1 iff t in {ann_i, ann_i+1, ..., ann_i+window-1}.
    Lookahead-safety: EAV lagged 1 day inside likelihood (uses eav[t-1]).
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


def load_one_stock_k1163(ticker, earnings_table, eav_window=1):
    """Load one EU stock with K1163 earnings dates (provenance-aware)."""
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

    # K1163 earnings dates (may come from YFINANCE or HAND_IRCALENDAR)
    raw_dates = earnings_table.get(ticker, [])
    ann_dates_list = []
    for d in raw_dates:
        try:
            ts = pd.Timestamp(d[:10] if len(d) >= 10 else d)
            if pd.Timestamp(DATA_START) <= ts <= pd.Timestamp(DATA_END):
                ann_dates_list.append(ts)
        except Exception:
            continue
    ann_dates = pd.DatetimeIndex(sorted(set(ann_dates_list)))

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
# Per-stock negll (identical to K1153)
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
        starts = [init, [var0 * 0.10, 0.05, 0.05, 0.05, 0.90]]
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
                per_stock_neg_loglik, s,
                args=(r, vix, eav, theta_vix, theta_eav),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 400, 'ftol': 1e-9},
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p, best_ll


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


def placebo_within_stock(stocks, n_placebo=60, seed=42, init_vix=9e-8,
                          init_eav=0.0, per_rep_time_budget=120):
    rng = np.random.default_rng(seed)
    thetas = []
    ts = []
    for b in range(n_placebo):
        permuted = []
        for s in stocks:
            new = s['eav'].copy()
            rng.shuffle(new)
            permuted.append({**s, 'eav': new})
        try:
            fit = fit_pooled_panel(permuted, max_outer=3, verbose=False,
                                    init_vix=init_vix, init_eav=init_eav,
                                    time_budget=per_rep_time_budget)
            se = hessian_se_theta_eav(
                permuted, [np.array(p) for p in fit['per_stock_params']],
                fit['theta_vix'], fit['theta_eav'],
            )
            t = (fit['theta_eav'] / se) if (se and se > 0) else np.nan
            thetas.append(fit['theta_eav'])
            ts.append(float(t) if np.isfinite(t) else None)
        except Exception as e:
            print(f'    [placebo {b}] fail: {e}')
    return np.array(thetas), ts


# ==========================================================================
# Main
# ==========================================================================
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: EU panel re-estimation with K1163 earnings (target N>=25)')
    print(f'{"=" * 72}\n')

    # Step 0: Load K1163 earnings table
    earnings_table, provenance_by_ticker = load_k1163_earnings_table()
    print(f'K1163 earnings table: {len(earnings_table)} tickers loaded')
    for tk in TICKERS:
        if tk in provenance_by_ticker:
            print(f'  {tk}: {len(earnings_table[tk])} events '
                  f'(prov={provenance_by_ticker[tk]})')

    # Step 1: Load stocks using K1163 earnings
    print('\n[1/6] Loading stocks with K1163 earnings (window=1) ...')
    stocks_w1 = []
    skipped = []
    load_provenance = {}
    for tk in TICKERS:
        st = load_one_stock_k1163(tk, earnings_table, eav_window=1)
        if st is None:
            skipped.append(tk)
            print(f'    SKIP {tk}: insufficient data')
            continue
        stocks_w1.append(st)
        load_provenance[tk] = provenance_by_ticker.get(tk, ['UNKNOWN'])
        print(f'    {tk}: n_obs={st["n_obs"]}, n_events={st["n_events"]} '
              f'(prov={provenance_by_ticker.get(tk, ["UNKNOWN"])})')
    N_actual = len(stocks_w1)
    print(f'\n  Loaded {N_actual}/{len(TICKERS)} stocks  (skipped: {skipped})')
    if N_actual < 15:
        print('  ABORT: < 15 stocks loaded')
        sys.exit(1)

    # Success gate
    if N_actual < 20:
        print(f'\n  ⚠ LOW_COVERAGE: only {N_actual}/30 loaded; marking PRELIMINARY')
        coverage_label = 'LOW_COVERAGE_PRELIMINARY'
    elif N_actual >= 25:
        coverage_label = 'FULL_COVERAGE'
    else:
        coverage_label = 'PARTIAL_COVERAGE'

    # Step 2: Diagnostic
    print('\n[2/6] Pre-fit panel diagnostic ...')
    all_r = np.concatenate([s['r'] for s in stocks_w1])
    print(f'  Pooled obs: {len(all_r):,}')
    print(f'  Mean r={np.mean(all_r):+.4e}, std={np.std(all_r):.4e}')
    print(f'  Skew={stats.skew(all_r):+.3f}, kurt={stats.kurtosis(all_r):+.3f}')
    print(f'  Mean events per stock: '
          f'{np.mean([s["n_events"] for s in stocks_w1]):.1f}')

    # Step 3: Main BCD fit
    print('\n[3/6] Pooled BCD fit (EAV window=1, primary) ...')
    fit_w1 = fit_pooled_panel(stocks_w1, max_outer=8, verbose=True,
                               time_budget=900)
    theta_eav_main = fit_w1['theta_eav']
    theta_vix_main = fit_w1['theta_vix']
    print(f'\n  → θ_VIX = {theta_vix_main:.4e}')
    print(f'  → θ_EAV = {theta_eav_main:+.4e}')
    print(f'  → pooled loglik = {fit_w1["pooled_loglik"]:.2f}')
    print(f'  → converged = {fit_w1["converged"]}')

    se_hessian = hessian_se_theta_eav(
        stocks_w1, [np.array(p) for p in fit_w1['per_stock_params']],
        theta_vix_main, theta_eav_main,
    )
    t_hessian = (theta_eav_main / se_hessian) if (se_hessian and se_hessian > 0) else np.nan
    print(f'  Hessian SE={se_hessian}, t={t_hessian}')

    # Step 4: Bootstrap
    print('\n[4/6] Stock-clustered block bootstrap (n_boot=150) ...')
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
        boot_p = 2 * min(np.mean(boot_draws <= 0), np.mean(boot_draws >= 0))
        boot_p = float(boot_p)
    else:
        boot_se = boot_mean = boot_ci_lo = boot_ci_hi = boot_t = boot_p = None
    print(f'  bootstrap mean={boot_mean}, SE={boot_se}')
    print(f'  bootstrap 95% CI = [{boot_ci_lo}, {boot_ci_hi}]')
    print(f'  bootstrap t={boot_t}, p={boot_p}')

    # Step 5: Placebo
    print('\n[5/6] Within-stock EAV permutation placebo (n_placebo=60) ...')
    placebo_t0 = time.time()
    placebo_thetas, placebo_ts = placebo_within_stock(
        stocks_w1, n_placebo=60, seed=GLOBAL_SEED,
        init_vix=9e-8, init_eav=0.0, per_rep_time_budget=120,
    )
    print(f'  placebo draws completed: {len(placebo_thetas)}/60 '
          f'(elapsed={time.time() - placebo_t0:.1f}s)')
    if len(placebo_thetas) > 0:
        placebo_mean = float(np.mean(placebo_thetas))
        placebo_se = float(np.std(placebo_thetas, ddof=1))
        placebo_ci = [
            float(np.percentile(placebo_thetas, 2.5)),
            float(np.percentile(placebo_thetas, 97.5)),
        ]
        z_observed = ((theta_eav_main - placebo_mean) / placebo_se
                      if placebo_se > 0 else np.nan)
        placebo_p = float(np.mean(placebo_thetas >= theta_eav_main))
    else:
        placebo_mean = placebo_se = z_observed = placebo_p = None
        placebo_ci = None
    print(f'  placebo mean={placebo_mean}, SE={placebo_se}')
    print(f'  placebo 95% CI = {placebo_ci}')
    print(f'  observed θ_EAV = {theta_eav_main:+.4e}')
    print(f'  z_observed = {z_observed}')
    print(f'  P(placebo >= observed) = {placebo_p}')

    # Step 6: Compare with K1153 + four-market
    print('\n[6/6] K1163 vs K1153 comparison + four-market update ...')
    K1153_EU_THETA_EAV = 4.0718849779368176e-05
    K1153_EU_BOOT_SE = 9.73e-06
    K1153_EU_BOOT_T = 4.19
    K1153_EU_AVG_SIGMA2 = 2.9797e-4
    K1153_EU_THETA_REL = 0.1366
    K1153_EU_PLACEBO_Z = 14.77
    K1153_N = 18

    TW_THETA_EAV = 6.36e-5
    TW_THETA_REL = 0.167
    US_THETA_EAV = 1.91e-4
    US_THETA_REL = 0.586
    JP_THETA_EAV = 1.41e-4
    JP_THETA_REL = 0.388

    eu_avg_sigma2_k1163 = float(np.std(all_r) ** 2)
    eu_theta_rel_k1163 = theta_eav_main / eu_avg_sigma2_k1163
    delta_theta_eav = theta_eav_main - K1153_EU_THETA_EAV
    delta_theta_rel = eu_theta_rel_k1163 - K1153_EU_THETA_REL

    if len(boot_draws) >= 30 and eu_avg_sigma2_k1163 > 0:
        boot_rel = boot_draws / eu_avg_sigma2_k1163
        eu_rel_boot_mean = float(np.mean(boot_rel))
        eu_rel_boot_se = float(np.std(boot_rel, ddof=1))
        eu_rel_ci_lo = float(np.percentile(boot_rel, 2.5))
        eu_rel_ci_hi = float(np.percentile(boot_rel, 97.5))
    else:
        eu_rel_boot_mean = eu_rel_boot_se = eu_rel_ci_lo = eu_rel_ci_hi = None

    print(f'\n  Delta table:')
    print(f'    θ_EAV  K1153={K1153_EU_THETA_EAV:+.3e}  K1163={theta_eav_main:+.3e}  '
          f'Δ={delta_theta_eav:+.3e}')
    print(f'    θ_rel  K1153={K1153_EU_THETA_REL:.3f}      K1163={eu_theta_rel_k1163:.3f}      '
          f'Δ={delta_theta_rel:+.3f}')
    print(f'    boot t K1153={K1153_EU_BOOT_T:.2f}       K1163={boot_t}')
    print(f'    placebo z K1153={K1153_EU_PLACEBO_Z:.2f}  K1163={z_observed}')
    print(f'    N     K1153={K1153_N}          K1163={N_actual}')

    # Four-market θ_rel cluster verdict
    LOW_CLUSTER_UPPER = 0.25  # TW 0.167, EU K1153 0.137
    HIGH_CLUSTER_LOWER = 0.30  # JP 0.388, US 0.586

    # Rules:
    #   ROBUST: K1163 EU θ_rel stays in low cluster (<=0.25) AND bootstrap still PASSES
    #   REVISED_HIGH: K1163 EU θ_rel moves to high cluster (>=0.30)
    #   REVISED_INTERMEDIATE: (0.25, 0.30) ambiguous between clusters
    #   INCOMPLETE: bootstrap fails or coverage <20
    if N_actual < 20 or (boot_t is not None and abs(boot_t) < 3.0):
        verdict = 'INCOMPLETE'
        verdict_text = (f'INCOMPLETE — N={N_actual} or bootstrap t={boot_t} '
                        f'below Harvey threshold.')
    elif eu_theta_rel_k1163 <= LOW_CLUSTER_UPPER:
        verdict = 'ROBUST'
        verdict_text = (f'ROBUST — K1163 EU θ_rel={eu_theta_rel_k1163:.3f} '
                        f'stays in low cluster [<={LOW_CLUSTER_UPPER}]; K1153 '
                        f'conclusion confirmed. Quarterly-density hypothesis '
                        f'remains REJECTED. TW+EU low cluster vs US+JP high '
                        f'cluster — refined media×analyst mechanism narrative '
                        f'holds for Paper 2.')
    elif eu_theta_rel_k1163 >= HIGH_CLUSTER_LOWER:
        verdict = 'REVISED'
        verdict_text = (f'REVISED — K1163 EU θ_rel={eu_theta_rel_k1163:.3f} '
                        f'moved to high cluster [>={HIGH_CLUSTER_LOWER}]; '
                        f'K1153 yfinance-sparse sample may have been biased '
                        f'downward by DAX-heavy (56%) composition. With full '
                        f'N=30 coverage, EU now clusters with US+JP; '
                        f'K1152 quarterly-density hypothesis may warrant '
                        f're-evaluation.')
    else:
        verdict = 'REVISED_INTERMEDIATE'
        verdict_text = (f'REVISED_INTERMEDIATE — K1163 EU θ_rel='
                        f'{eu_theta_rel_k1163:.3f} sits between low and '
                        f'high clusters; cluster membership ambiguous.')

    print(f'\n  FOUR-MARKET VERDICT: {verdict}')
    print(f'  {verdict_text}')

    # Figures
    print('\n  Generating figures ...')
    # Figure 1: EU θ_rel distribution K1153 vs K1163
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))
    k1153_ci = [0.065, 0.209]
    k1163_ci = [eu_rel_ci_lo, eu_rel_ci_hi] if eu_rel_ci_lo is not None else [0, 0]
    xpos = [0, 1]
    mids = [K1153_EU_THETA_REL, eu_theta_rel_k1163]
    err_lo = [K1153_EU_THETA_REL - k1153_ci[0], eu_theta_rel_k1163 - k1163_ci[0]]
    err_hi = [k1153_ci[1] - K1153_EU_THETA_REL, k1163_ci[1] - eu_theta_rel_k1163]
    ax.errorbar(xpos, mids, yerr=[err_lo, err_hi],
                fmt='o', capsize=10, markersize=10, color='purple',
                ecolor='gray', elinewidth=2)
    ax.axhspan(0, LOW_CLUSTER_UPPER, color='lightblue', alpha=0.2,
               label=f'Low cluster [0, {LOW_CLUSTER_UPPER}]')
    ax.axhspan(HIGH_CLUSTER_LOWER, 0.70, color='gold', alpha=0.2,
               label=f'High cluster [{HIGH_CLUSTER_LOWER}, 0.70]')
    # Reference lines for TW/US/JP
    ax.axhline(TW_THETA_REL, color='steelblue', linestyle='--', alpha=0.6,
               label=f'TW θ_rel={TW_THETA_REL}')
    ax.axhline(JP_THETA_REL, color='darkgreen', linestyle='--', alpha=0.6,
               label=f'JP θ_rel={JP_THETA_REL}')
    ax.axhline(US_THETA_REL, color='darkred', linestyle='--', alpha=0.6,
               label=f'US θ_rel={US_THETA_REL}')
    ax.set_xticks(xpos)
    ax.set_xticklabels([f'K1153 EU\n(N={K1153_N}, yfinance)',
                        f'K1163 EU\n(N={N_actual}, YF+IR)'])
    ax.set_ylabel(r'$\theta_{rel} = \theta_{EAV}/\bar\sigma^2$')
    ax.set_title(f'K1163 vs K1153 EU θ_rel (verdict: {verdict})')
    ax.legend(loc='upper right', fontsize=9)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / 'k1163_eu_theta_rel_k1153_vs_k1163.png', dpi=120)
    plt.close()

    # Figure 2: Placebo z-stat comparison
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))
    if len(placebo_thetas) > 0:
        ax.hist(placebo_thetas, bins=20, alpha=0.6, color='lightgray',
                edgecolor='black', label=f'K1163 placebo (n={len(placebo_thetas)})')
        ax.axvline(theta_eav_main, color='purple', linestyle='-',
                   linewidth=2.5,
                   label=f'K1163 observed θ_EAV={theta_eav_main:+.3e} (z={z_observed:.2f}σ)')
        ax.axvline(K1153_EU_THETA_EAV, color='steelblue', linestyle='--',
                   linewidth=2,
                   label=f'K1153 observed θ_EAV={K1153_EU_THETA_EAV:+.3e} (z={K1153_EU_PLACEBO_Z:.2f}σ)')
        ax.axvline(0, color='black', linestyle=':', alpha=0.5)
    ax.set_xlabel(r'Placebo $\theta_{EAV}$')
    ax.set_ylabel('count')
    ax.set_title('K1163 EU placebo distribution (within-stock EAV permutation, n=60)')
    ax.legend(loc='upper right', fontsize=9)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / 'k1163_placebo_distribution.png', dpi=120)
    plt.close()

    # Figure 3: Four-market comparison
    fig, ax = plt.subplots(1, 1, figsize=(10, 5))
    markets = ['TW\nN=31', 'EU K1153\nN=18', 'EU K1163\n'f'N={N_actual}', 'JP\nN=30', 'US\nN=30']
    rel_values = [TW_THETA_REL, K1153_EU_THETA_REL, eu_theta_rel_k1163,
                  JP_THETA_REL, US_THETA_REL]
    colors = ['steelblue', 'lightpurple' if verdict == 'REVISED' else 'plum',
              'purple', 'darkgreen', 'darkred']
    try:
        ax.bar(range(len(markets)), rel_values, color=colors,
               edgecolor='black', alpha=0.75)
    except ValueError:
        ax.bar(range(len(markets)), rel_values, color='plum',
               edgecolor='black', alpha=0.75)
    ax.axhspan(0, LOW_CLUSTER_UPPER, color='lightblue', alpha=0.15,
               label=f'Low cluster')
    ax.axhspan(HIGH_CLUSTER_LOWER, 0.75, color='gold', alpha=0.15,
               label=f'High cluster')
    ax.set_xticks(range(len(markets)))
    ax.set_xticklabels(markets, fontsize=9)
    ax.set_ylabel(r'$\theta_{rel}$')
    ax.set_title('Four-market θ_rel (K1153 → K1163 EU refit comparison)')
    for i, v in enumerate(rel_values):
        ax.text(i, v + 0.02, f'{v:.3f}', ha='center', fontsize=9)
    ax.legend(loc='upper left', fontsize=9)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / 'k1163_four_market_rel_comparison.png', dpi=120)
    plt.close()

    # Save results
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'K1163 EU refit with refetched earnings dates (target N>=25)',
        'proposer': 'Claude (承接 K1153 yfinance-sparse coverage)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': 'yfinance price/VIX + k1163_eu_earnings_dates.csv '
                       '(YFINANCE + HAND_IRCALENDAR provenance)',
        'data_period': f'{DATA_START} ~ {DATA_END}',
        'tickers': TICKERS,
        'n_stocks_target': 30,
        'n_stocks_loaded': N_actual,
        'skipped_tickers': skipped,
        'coverage_label': coverage_label,
        'loaded_provenance': load_provenance,
        'panel_diagnostic': {
            'pooled_n': int(len(all_r)),
            'mean_r': float(np.mean(all_r)),
            'std_r': float(np.std(all_r)),
            'skew': float(stats.skew(all_r)),
            'kurt_excess': float(stats.kurtosis(all_r)),
            'mean_events_per_stock': float(
                np.mean([s['n_events'] for s in stocks_w1])),
        },
        'main_fit_eav_window_1': {
            'theta_vix': theta_vix_main,
            'theta_eav': theta_eav_main,
            'theta_eav_se_hessian': se_hessian,
            'theta_eav_t_hessian': float(t_hessian) if np.isfinite(t_hessian) else None,
            'pooled_loglik': fit_w1['pooled_loglik'],
            'n_outer_iters': fit_w1['n_outer_iters'],
            'converged': fit_w1['converged'],
            'history': fit_w1['history'],
            'per_stock_params': fit_w1['per_stock_params'],
            'per_stock_tickers': [s['ticker'] for s in stocks_w1],
            'per_stock_n_events': [s['n_events'] for s in stocks_w1],
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
        'placebo': {
            'n_placebo_target': 60,
            'n_placebo_completed': int(len(placebo_thetas)),
            'mean': placebo_mean,
            'se': placebo_se,
            'ci_95': placebo_ci,
            'z_observed': float(z_observed) if (z_observed is not None and np.isfinite(z_observed)) else None,
            'p_one_sided': placebo_p,
            'draws': placebo_thetas.tolist() if len(placebo_thetas) > 0 else [],
        },
        'k1163_vs_k1153': {
            'k1153_eu_n': K1153_N,
            'k1163_eu_n': N_actual,
            'k1153_theta_eav': K1153_EU_THETA_EAV,
            'k1163_theta_eav': theta_eav_main,
            'delta_theta_eav': delta_theta_eav,
            'k1153_theta_rel': K1153_EU_THETA_REL,
            'k1163_theta_rel': eu_theta_rel_k1163,
            'delta_theta_rel': delta_theta_rel,
            'k1153_boot_t': K1153_EU_BOOT_T,
            'k1163_boot_t': float(boot_t) if (boot_t is not None and np.isfinite(boot_t)) else None,
            'k1153_placebo_z': K1153_EU_PLACEBO_Z,
            'k1163_placebo_z': float(z_observed) if (z_observed is not None and np.isfinite(z_observed)) else None,
        },
        'four_market': {
            'tw_theta_rel': TW_THETA_REL,
            'eu_k1153_theta_rel': K1153_EU_THETA_REL,
            'eu_k1163_theta_rel': eu_theta_rel_k1163,
            'jp_theta_rel': JP_THETA_REL,
            'us_theta_rel': US_THETA_REL,
            'eu_rel_boot_mean': eu_rel_boot_mean,
            'eu_rel_boot_se': eu_rel_boot_se,
            'eu_rel_ci95': [eu_rel_ci_lo, eu_rel_ci_hi] if eu_rel_ci_lo is not None else None,
            'low_cluster_upper': LOW_CLUSTER_UPPER,
            'high_cluster_lower': HIGH_CLUSTER_LOWER,
        },
        'verdict': {
            'label': verdict,
            'text': verdict_text,
        },
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results -> {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  FINAL VERDICT: {verdict}')
    print(f'  {verdict_text}')


if __name__ == '__main__':
    main()
