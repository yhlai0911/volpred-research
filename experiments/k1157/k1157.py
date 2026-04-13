#!/usr/bin/env python3
"""
K1157: Continuous earnings surprise vs Binary EAV (JP TOPIX N=30)
==================================================================
[提出: Claude (承接 K1151 next_tasks K1157), 執行: Claude]

Research question
-----------------
K1151 showed on US S&P 500 N=30 that the continuous-surprise spec is
non-significant (bootstrap t = +1.11, p = 0.41) while the binary-EAV
spec is overwhelmingly preferred (ΔAIC = -5479 with equal k = 152).
Verdict: BINARY SUFFICIENT for US.

K1157 question: is "binary sufficient" universal across markets, or is
it US-specific? We replicate the same continuous-vs-binary head-to-head
on the K1150 JP TOPIX top-30 large-cap panel (~88k pooled obs,
~47 events/stock, 2014-2025). Decision tree:

| JP continuous bootstrap | Binary AIC vs Continuous | Verdict |
|------------------------|--------------------------|---------|
| t < 2 + binary AIC <<  | binary <<                | UNIVERSAL (binary sufficient cross-market) |
| t > 3                   | indifferent              | MARKET-SPECIFIC (JP responds to surprise size) |
| t > 3                   | continuous wins         | JP surprise-size matters |
| ambiguous               | ambiguous                | INCONCLUSIVE |

Methodology mirrors K1151 exactly:
  - Same pool spec: σ²_{i,t} = g_{i,t}·τ_{i,t}, GJR(1,1) per stock + shared
    θ_VIX (CBOE VIX² lagged), shared θ_x where x is binary EAV or surp_z.
  - Continuous surp_z = (clipped(|Surprise(%)|, p99) - mean) / std,
    nonzero on announcement day(s) only.
  - BCD (block coordinate descent) pooled MLE, max 8 outer iters.
  - Hessian SE on shared θ_x.
  - Stock-clustered block bootstrap (n=150, seed=42).
  - Drop-5 × 3 seeds robustness.
  - Plus K1157_placebo.py: within-stock surp_z permutation, 60 reps.

Lookahead discipline (mirrors K1150):
  - VIX_{t-1}: CBOE VIX close on US calendar day t-1 is settled at
    ~21:00 UTC = ~06:00 JST, so it is fully observed before TSE opens
    on JST day t. Likelihood uses vix[t-1] (additional shift in time)
    as double safety.
  - surp_z_{t-1}: built from yfinance earnings_dates with Reported EPS
    not NaN (announced-only); likelihood lags by 1 trading day.
  - Random seed = 42 for everything.

Author: VolPred Research System.
Date: 2026-04-13.
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone
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

START_TIME = time.time()
EXPERIMENT_ID = 'K1157'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = SCRIPT_DIR / 'data'
EARNINGS_DATES_CACHE = DATA_DIR / 'earnings_dates.json'
EARNINGS_SURPRISE_CACHE = DATA_DIR / 'earnings_surprises.json'
RESULTS_PATH = SCRIPT_DIR / 'k1157_results.json'

DATA_START = '2014-01-01'
DATA_END = '2025-12-31'

# Same 30 TOPIX large-caps as K1150
TICKERS = [
    '7203.T', '6758.T', '9984.T', '8306.T', '6861.T', '9432.T',
    '6098.T', '7974.T', '6594.T', '8035.T', '4063.T', '6501.T',
    '9433.T', '8316.T', '8411.T', '6902.T', '6367.T', '8001.T',
    '8058.T', '4502.T', '6273.T', '7741.T', '6981.T', '8801.T',
    '6178.T', '7267.T', '8031.T', '4503.T', '8002.T', '6701.T',
]

SURP_WINSOR_PCT = 99.0


# ==========================================================================
# Data loading
# ==========================================================================
def _safe_name(ticker):
    return ticker.replace('^', 'IDX_').replace('-', '_').replace('.', '_')


def load_cached_prices(ticker):
    cache_path = DATA_DIR / f"{_safe_name(ticker)}.parquet"
    if not cache_path.exists():
        return None
    return pd.read_parquet(cache_path)


def load_earnings_dates_only(ticker):
    """Return DatetimeIndex of past announcement dates (from K1150 cache)."""
    with open(EARNINGS_DATES_CACHE) as f:
        cache = json.load(f)
    if ticker not in cache:
        return pd.DatetimeIndex([])
    dates = [pd.Timestamp(d) for d in cache[ticker]]
    return pd.DatetimeIndex(dates)


def load_earnings_surprises(ticker):
    """Return dict: date (pd.Timestamp normalised) -> abs_surprise_pct."""
    with open(EARNINGS_SURPRISE_CACHE) as f:
        cache = json.load(f)
    if ticker not in cache:
        return {}
    out = {}
    for rec in cache[ticker]:
        out[pd.Timestamp(rec['date']).normalize()] = abs(float(rec['surprise_pct']))
    return out


def build_eav_binary(trading_days, ann_dates, window):
    """Binary EAV: 1 on announcement day and forward (window-1) trading days."""
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


def build_surp_raw(trading_days, ann_dates, surp_map, window):
    """Raw |surprise|%: nonzero on announcement day(s) only."""
    arr = np.zeros(len(trading_days), dtype=float)
    if len(ann_dates) == 0:
        return arr
    pos_arr = trading_days.searchsorted(ann_dates.values)
    for ann_dt, p in zip(ann_dates.values, pos_arr):
        p = int(p)
        ann_ts = pd.Timestamp(ann_dt).normalize()
        surp = float(surp_map.get(ann_ts, 0.0))
        if surp == 0.0:
            continue
        for w in range(window):
            if 0 <= p + w < len(trading_days):
                arr[p + w] = max(arr[p + w], surp)
    return arr


def load_one_stock(ticker, window=1):
    raw = load_cached_prices(ticker)
    if raw is None:
        return None
    prices = raw['Close'].copy().dropna()
    log_ret = np.log(prices / prices.shift(1))
    vix_raw = load_cached_prices('^VIX')
    if vix_raw is None:
        return None
    vix = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]
    ann_dates = load_earnings_dates_only(ticker)
    surp_map = load_earnings_surprises(ticker)
    eav_b = build_eav_binary(df.index, ann_dates, window)
    surp_raw = build_surp_raw(df.index, ann_dates, surp_map, window)
    if len(df) < 500 or eav_b.sum() < 15:
        return None
    n_events_binary = int(eav_b.sum())
    n_events_surp = int((surp_raw > 0).sum())
    return {
        'ticker': ticker,
        'r': df['r'].values,
        'vix': df['vix'].values,
        'eav_b': eav_b,
        'surp_raw': surp_raw,
        'index': df.index,
        'n_obs': len(df),
        'n_events_binary': n_events_binary,
        'n_events_surp': n_events_surp,
    }


def standardize_continuous(stocks, winsor_pct=SURP_WINSOR_PCT):
    """Winsorize + z-score |surprise| across the full pool."""
    all_surp = np.concatenate([s['surp_raw'] for s in stocks])
    nonzero = all_surp[all_surp > 0]
    if len(nonzero) == 0:
        raise RuntimeError('No non-zero surprise values found')
    p99 = float(np.percentile(nonzero, winsor_pct))
    nonzero_clip = np.clip(nonzero, 0, p99)
    mu = float(np.mean(nonzero_clip))
    sd = float(np.std(nonzero_clip, ddof=1))
    if sd < 1e-6:
        sd = 1e-6
    new_stocks = []
    for s in stocks:
        clipped = np.clip(s['surp_raw'], 0, p99)
        z = np.where(clipped > 0, (clipped - mu) / sd, 0.0)
        new_stocks.append({**s, 'surp_z': z})
    return new_stocks, {
        'p99_threshold_pct': p99,
        'mean_nonzero_clipped': mu,
        'std_nonzero_clipped': sd,
        'n_nonzero_total': int(len(nonzero)),
        'n_clipped_at_p99': int((nonzero > p99).sum()),
        'raw_max_pct': float(nonzero.max()),
        'raw_mean_pct': float(nonzero.mean()),
    }


# ==========================================================================
# Estimator (shared between binary / continuous — third arg is "x" signal)
# ==========================================================================
@njit(cache=True, fastmath=True)
def _negll_numba(theta0, omega_g, alpha, gamma_p, beta_p,
                  r, vix, x, theta_vix, theta_x):
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
            xl = x[0]
        else:
            vl = vix[t - 1]
            xl = x[t - 1]
        raw = theta0 + theta_vix * vl * vl + theta_x * xl
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


def per_stock_negll(stock_params, r, vix, x, theta_vix, theta_x):
    theta0, omega_g, alpha, gamma_p, beta_p = stock_params
    return _negll_numba(
        float(theta0), float(omega_g), float(alpha),
        float(gamma_p), float(beta_p),
        r, vix, x, float(theta_vix), float(theta_x),
    )


def fit_one_stock(stock_x_field, stock, theta_vix, theta_x, init=None):
    r = stock['r']
    vix = stock['vix']
    x = stock[stock_x_field]
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
                per_stock_negll, s,
                args=(r, vix, x, theta_vix, theta_x),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 400, 'ftol': 1e-9},
            )
            if res.fun < best_ll:
                best_ll = res.fun
                best_p = res.x
        except Exception:
            continue
    return best_p, best_ll


def pooled_negll(stocks, stock_x_field, per_stock_params,
                  theta_vix, theta_x):
    total = 0.0
    for st, p in zip(stocks, per_stock_params):
        total += per_stock_negll(
            p, st['r'], st['vix'], st[stock_x_field],
            theta_vix, theta_x,
        )
    return total


def shared_objective(shared, stocks, stock_x_field, per_stock_params):
    theta_vix, theta_x = shared
    return pooled_negll(stocks, stock_x_field, per_stock_params,
                         theta_vix, theta_x)


def fit_pooled_panel(stocks, stock_x_field, max_outer=8,
                     init_vix=1e-7, init_x=5e-5, verbose=True,
                     time_budget=None, bounds_x=(-1.0, 1.0)):
    t_start = time.time()
    theta_vix = float(init_vix)
    theta_x = float(init_x)
    stock_params_list = [None] * len(stocks)
    prev_total_ll = np.inf
    history = []
    converged = False
    bounds_shared = [(1e-9, 1e-3), bounds_x]

    for outer in range(max_outer):
        if time_budget is not None and time.time() - t_start > time_budget:
            if verbose:
                print(f'    [BCD] outer {outer}: time budget hit')
            break
        total_negll = 0.0
        for i, st in enumerate(stocks):
            p_init = stock_params_list[i]
            p, ll = fit_one_stock(stock_x_field, st, theta_vix, theta_x,
                                   init=p_init)
            if p is None:
                if stock_params_list[i] is None:
                    raise RuntimeError(f'stock {st["ticker"]} initial fit failed')
                continue
            stock_params_list[i] = p
            total_negll += ll
        res = optimize.minimize(
            shared_objective, [theta_vix, theta_x],
            args=(stocks, stock_x_field, stock_params_list),
            method='L-BFGS-B', bounds=bounds_shared,
            options={'maxiter': 200, 'ftol': 1e-10},
        )
        new_vix, new_x = res.x
        new_negll = res.fun
        d_x = abs(new_x - theta_x)
        d_ll = prev_total_ll - new_negll
        if verbose:
            print(f'    [BCD outer {outer}] θ_VIX={new_vix:.3e}, '
                  f'θ_x={new_x:+.4e}, negll={new_negll:.2f}, Δll={d_ll:+.4f}')
        history.append({
            'outer_iter': outer,
            'theta_vix': float(new_vix),
            'theta_x': float(new_x),
            'pooled_negll': float(new_negll),
        })
        theta_vix, theta_x = float(new_vix), float(new_x)
        if outer >= 1 and d_ll < 1e-2 and d_x < 1e-7:
            converged = True
            if verbose:
                print('    [BCD] converged')
            break
        prev_total_ll = new_negll

    final_negll = 0.0
    final_params = []
    for i, st in enumerate(stocks):
        p, ll = fit_one_stock(stock_x_field, st, theta_vix, theta_x,
                               init=stock_params_list[i])
        if p is None:
            p = stock_params_list[i]
            ll = per_stock_negll(p, st['r'], st['vix'], st[stock_x_field],
                                  theta_vix, theta_x)
        final_params.append(p)
        final_negll += ll
    return {
        'theta_vix': theta_vix,
        'theta_x': theta_x,
        'per_stock_params': [p.tolist() for p in final_params],
        'pooled_loglik': float(-final_negll),
        'pooled_negll': float(final_negll),
        'n_outer_iters': len(history),
        'converged': converged,
        'history': history,
    }


def hessian_se_theta_x(stocks, stock_x_field, per_stock_params,
                       theta_vix, theta_x, eps_scale=1e-3):
    ll0 = pooled_negll(stocks, stock_x_field, per_stock_params,
                        theta_vix, theta_x)
    eps = max(abs(theta_x) * eps_scale, eps_scale * 1e-4)
    ll_p = pooled_negll(stocks, stock_x_field, per_stock_params,
                         theta_vix, theta_x + eps)
    ll_m = pooled_negll(stocks, stock_x_field, per_stock_params,
                         theta_vix, theta_x - eps)
    h22 = (ll_p - 2 * ll0 + ll_m) / (eps ** 2)
    if h22 > 0 and np.isfinite(h22):
        return float(np.sqrt(1.0 / h22))
    return None


def cluster_bootstrap(stocks, stock_x_field, n_boot=150, seed=42,
                      init_vix=1e-7, init_x=5e-5, inner_max_outer=2,
                      per_boot_time_budget=45,
                      bounds_x=(-1.0, 1.0)):
    rng = np.random.default_rng(seed)
    N = len(stocks)
    draws = []
    t0 = time.time()
    for b in range(n_boot):
        idx = rng.integers(0, N, size=N)
        boot = [stocks[i] for i in idx]
        try:
            fit = fit_pooled_panel(
                boot, stock_x_field, max_outer=inner_max_outer,
                init_vix=init_vix, init_x=init_x, verbose=False,
                time_budget=per_boot_time_budget, bounds_x=bounds_x,
            )
            draws.append(fit['theta_x'])
        except Exception as e:
            print(f'    [boot {b}] fail: {e}')
            continue
        if (b + 1) % 25 == 0:
            print(f'    [boot {b+1}/{n_boot}] elapsed={time.time()-t0:.0f}s')
    return np.array(draws)


def aic_bic(negll, k, n):
    ll = -negll
    aic = 2 * k - 2 * ll
    bic = k * np.log(n) - 2 * ll
    return float(aic), float(bic)


# ==========================================================================
# Main
# ==========================================================================
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: Continuous surprise vs Binary EAV (JP TOPIX N=30)')
    print(f'{"=" * 72}\n')

    print('[1/5] Loading stocks (EAV window=1) ...')
    stocks = []
    for tk in TICKERS:
        st = load_one_stock(tk, window=1)
        if st is None:
            print(f'    SKIP {tk}: insufficient data')
            continue
        stocks.append(st)
        print(f'    {tk}: n_obs={st["n_obs"]}, n_events_binary={st["n_events_binary"]}, '
              f'n_events_surp_matched={st["n_events_surp"]}')
    N_actual = len(stocks)
    print(f'  Loaded {N_actual}/{len(TICKERS)} stocks\n')
    if N_actual < 15:
        print('  ABORT: < 15 stocks (per K1157 design min)')
        sys.exit(1)

    print('[2/5] Standardizing continuous surprise (winsor p99 + z-score) ...')
    stocks, surp_summary = standardize_continuous(stocks)
    print(f"  raw  mean={surp_summary['raw_mean_pct']:.2f}% max={surp_summary['raw_max_pct']:.2f}%")
    print(f"  p99  threshold = {surp_summary['p99_threshold_pct']:.2f}%")
    print(f"  n_nonzero events total = {surp_summary['n_nonzero_total']}")
    print(f"  n_clipped at p99 = {surp_summary['n_clipped_at_p99']}")
    print(f"  mean_clipped = {surp_summary['mean_nonzero_clipped']:.2f}%, "
          f"std_clipped = {surp_summary['std_nonzero_clipped']:.2f}%\n")

    # 3. Binary baseline (replicate K1150)
    print('[3/5] Binary EAV baseline (replicate K1150 on local cache) ...')
    fit_b = fit_pooled_panel(
        stocks, 'eav_b',
        max_outer=8, init_vix=9e-8, init_x=5e-5,
        verbose=True, time_budget=600,
        bounds_x=(-1e-2, 1e-2),
    )
    theta_b = fit_b['theta_x']
    se_b = hessian_se_theta_x(
        stocks, 'eav_b',
        [np.array(p) for p in fit_b['per_stock_params']],
        fit_b['theta_vix'], theta_b,
    )
    t_b_hess = theta_b / se_b if (se_b and se_b > 0) else np.nan
    print(f'\n  Binary:  θ_EAV={theta_b:+.4e}, SE={se_b:.4e}, t_hess={t_b_hess:+.2f}')
    print(f'           pooled_loglik={fit_b["pooled_loglik"]:.2f}')

    # 4. Continuous surprise fit
    print('\n[4/5] Continuous surprise (z-scored |surprise|) ...')
    fit_c = fit_pooled_panel(
        stocks, 'surp_z',
        max_outer=8, init_vix=fit_b['theta_vix'], init_x=1e-5,
        verbose=True, time_budget=600,
        bounds_x=(-1e-2, 1e-2),
    )
    theta_c = fit_c['theta_x']
    se_c = hessian_se_theta_x(
        stocks, 'surp_z',
        [np.array(p) for p in fit_c['per_stock_params']],
        fit_c['theta_vix'], theta_c,
    )
    t_c_hess = theta_c / se_c if (se_c and se_c > 0) else np.nan
    print(f'\n  Continuous:  θ_SURP={theta_c:+.4e}, SE={se_c:.4e}, t_hess={t_c_hess:+.2f}')
    print(f'               pooled_loglik={fit_c["pooled_loglik"]:.2f}')

    # 5. AIC / BIC
    k_total = N_actual * 5 + 2
    n_total = int(sum(s['n_obs'] for s in stocks))
    aic_b, bic_b = aic_bic(fit_b['pooled_negll'], k_total, n_total)
    aic_c, bic_c = aic_bic(fit_c['pooled_negll'], k_total, n_total)
    print('\n  Information criteria (lower is better):')
    print(f'    Binary      : AIC={aic_b:.2f}, BIC={bic_b:.2f}')
    print(f'    Continuous  : AIC={aic_c:.2f}, BIC={bic_c:.2f}')
    print(f'    ΔAIC (bin-cont) = {aic_b - aic_c:+.2f} (>0 favours continuous)')
    print(f'    ΔBIC (bin-cont) = {bic_b - bic_c:+.2f}')

    # 5.1 Bootstrap
    print('\n[5/5a] Cluster bootstrap for BINARY (n=150) ...')
    boot_b = cluster_bootstrap(
        stocks, 'eav_b', n_boot=150, seed=GLOBAL_SEED,
        init_vix=fit_b['theta_vix'], init_x=theta_b,
        inner_max_outer=2, per_boot_time_budget=45,
        bounds_x=(-1e-2, 1e-2),
    )
    print(f'  Binary boot draws: {len(boot_b)}/150')

    print('\n[5/5b] Cluster bootstrap for CONTINUOUS (n=150) ...')
    boot_c = cluster_bootstrap(
        stocks, 'surp_z', n_boot=150, seed=GLOBAL_SEED,
        init_vix=fit_c['theta_vix'], init_x=theta_c,
        inner_max_outer=2, per_boot_time_budget=45,
        bounds_x=(-1e-2, 1e-2),
    )
    print(f'  Continuous boot draws: {len(boot_c)}/150')

    def boot_stats(draws, theta_main):
        if len(draws) < 30:
            return dict.fromkeys(
                ['mean', 'se', 'ci_lo', 'ci_hi', 't', 'p'], None)
        mean = float(np.mean(draws))
        se = float(np.std(draws, ddof=1))
        lo = float(np.percentile(draws, 2.5))
        hi = float(np.percentile(draws, 97.5))
        t = theta_main / se if se > 0 else np.nan
        p_two = 2 * min(np.mean(draws <= 0), np.mean(draws >= 0))
        return {
            'mean': mean, 'se': se, 'ci_lo': lo, 'ci_hi': hi,
            't': float(t) if np.isfinite(t) else None,
            'p': float(p_two),
        }

    bs_b = boot_stats(boot_b, theta_b)
    bs_c = boot_stats(boot_c, theta_c)
    print('\n  Bootstrap results:')
    print(f'    Binary      : mean={bs_b["mean"]}, SE={bs_b["se"]}, t={bs_b["t"]}, p={bs_b["p"]}')
    print(f'    Continuous  : mean={bs_c["mean"]}, SE={bs_c["se"]}, t={bs_c["t"]}, p={bs_c["p"]}')

    # 6. Drop-5 robustness (continuous)
    print('\n[6] Drop-5 robustness (continuous, 3 seeds) ...')
    dropout = []
    for sd in (42, 43, 44):
        rng = np.random.default_rng(sd)
        drop_idx = set(rng.choice(N_actual, size=5, replace=False).tolist())
        sub = [s for i, s in enumerate(stocks) if i not in drop_idx]
        dropped = [stocks[i]['ticker'] for i in drop_idx]
        try:
            fit_sub = fit_pooled_panel(
                sub, 'surp_z', max_outer=5, verbose=False,
                init_vix=fit_c['theta_vix'], init_x=theta_c,
                time_budget=240, bounds_x=(-1e-2, 1e-2),
            )
            se_sub = hessian_se_theta_x(
                sub, 'surp_z',
                [np.array(p) for p in fit_sub['per_stock_params']],
                fit_sub['theta_vix'], fit_sub['theta_x'],
            )
            t_sub = fit_sub['theta_x'] / se_sub if (se_sub and se_sub > 0) else None
            dropout.append({
                'seed': sd, 'dropped_tickers': dropped,
                'theta_surp': fit_sub['theta_x'],
                'se_hess': se_sub,
                't_hess': float(t_sub) if t_sub is not None else None,
                'n_stocks': len(sub),
            })
            print(f'    seed={sd}, dropped={dropped}, θ_SURP={fit_sub["theta_x"]:+.3e}, '
                  f't={t_sub}')
        except Exception as e:
            print(f'    seed={sd}: FAIL {e}')

    # 7. Verdict
    print('\n[7] Verdict')
    t_b_boot = bs_b.get('t') or 0
    t_c_boot = bs_c.get('t') or 0
    if t_c_boot is None:
        t_c_boot = 0
    if t_b_boot is None:
        t_b_boot = 0
    delta_aic = aic_b - aic_c

    if t_c_boot > 3 and delta_aic > 2:
        mechanism = 'SURPRISE-MAGNITUDE CONFIRMED (continuous bootstrap t>3 AND ΔAIC favours continuous)'
        universality = 'JP MARKET-SPECIFIC: surprise size matters in JP, contrasts US K1151 binary-sufficient'
    elif t_c_boot > 3 and abs(delta_aic) < 2:
        mechanism = 'BOTH SIGNIFICANT BUT AIC INDIFFERENT'
        universality = 'JP weakly market-specific'
    elif t_c_boot < 2 and t_b_boot > 3:
        mechanism = 'BINARY SUFFICIENT (continuous NS, binary captures announcement-day clustering regardless of surprise size)'
        universality = 'UNIVERSAL: binary-sufficient confirmed cross-market (JP matches US K1151)'
    elif t_c_boot > 3 and t_b_boot > 3 and delta_aic < -2:
        mechanism = 'BINARY STRICTLY BETTER (both significant but AIC favours binary)'
        universality = 'UNIVERSAL: binary spec preferred cross-market'
    else:
        mechanism = 'AMBIGUOUS'
        universality = 'INCONCLUSIVE — manual review needed'

    if 'SURPRISE-MAGNITUDE CONFIRMED' in mechanism:
        narrative = 'JP differs from US — Paper 2 must report market-specific narrative.'
    elif 'BINARY SUFFICIENT' in mechanism or 'BINARY STRICTLY BETTER' in mechanism:
        narrative = 'Universal binary-sufficient: Paper 2 keeps binary as main spec across all three markets.'
    else:
        narrative = 'Inconclusive; report both specs as complementary.'

    print(f'\n  Mechanism: {mechanism}')
    print(f'  Universality: {universality}')
    print(f'  Paper 2 narrative: {narrative}')

    if t_c_hess is not None and abs(t_c_hess) > 8:
        print(f'\n  ⚠️  continuous Hessian t={t_c_hess:+.2f} > 8 — Hessian inflation expected for')
        print('      pooled panels with 150+ nuisance params; trust bootstrap t (preamble Rule #5).')

    # 8. Plots
    print('\n[8] Plots ...')
    plot1 = SCRIPT_DIR / 'k1157_tstat_barplot.png'
    fig, ax = plt.subplots(1, 1, figsize=(8, 4.8))
    labels = ['Binary\nHessian', 'Binary\nBootstrap',
              'Continuous\nHessian', 'Continuous\nBootstrap']
    tvals = [
        t_b_hess if np.isfinite(t_b_hess) else 0,
        bs_b['t'] if bs_b['t'] is not None else 0,
        t_c_hess if np.isfinite(t_c_hess) else 0,
        bs_c['t'] if bs_c['t'] is not None else 0,
    ]
    colors = ['#1f77b4', '#1f77b4', '#d62728', '#d62728']
    ax.bar(np.arange(4), tvals, color=colors, alpha=0.75, edgecolor='black')
    ax.axhline(3, linestyle='--', color='gray', label='Harvey |t|>3')
    ax.axhline(-3, linestyle='--', color='gray')
    ax.axhline(0, linestyle='-', color='black', lw=0.5)
    ax.set_xticks(np.arange(4))
    ax.set_xticklabels(labels)
    ax.set_ylabel('t-statistic')
    ax.set_title(f'K1157 — Binary vs Continuous surprise t-stat (JP TOPIX N={N_actual})')
    for i, v in enumerate(tvals):
        ax.text(i, v + (0.5 if v > 0 else -0.8), f'{v:+.2f}',
                ha='center', fontsize=10, fontweight='bold')
    ax.legend(loc='best')
    plt.tight_layout()
    plt.savefig(plot1, dpi=120)
    plt.close()
    print(f'  -> {plot1}')

    # Plot 2: US vs JP continuous-vs-binary t-stat side-by-side comparison
    plot2 = SCRIPT_DIR / 'k1157_us_vs_jp_comparison.png'
    fig, ax = plt.subplots(1, 1, figsize=(9, 5))
    # K1151 US results (load if available, fall back to documented values)
    us_path = Path('/Users/yhlai0911/Desktop/volpred-research/experiments/k1151/k1151_results.json')
    if us_path.exists():
        with open(us_path) as f:
            us_res = json.load(f)
        us_b_t = us_res['binary_baseline']['bootstrap']['t']
        us_c_t = us_res['continuous_surprise']['bootstrap']['t']
    else:
        us_b_t = 4.49
        us_c_t = 1.11
    jp_b_t = bs_b['t'] if bs_b['t'] is not None else 0
    jp_c_t = bs_c['t'] if bs_c['t'] is not None else 0
    width = 0.35
    xs = np.arange(2)
    ax.bar(xs - width/2, [us_b_t, us_c_t], width, label='US K1151',
           color='#1f77b4', alpha=0.8, edgecolor='black')
    ax.bar(xs + width/2, [jp_b_t, jp_c_t], width, label='JP K1157',
           color='#d62728', alpha=0.8, edgecolor='black')
    ax.axhline(3, linestyle='--', color='gray', label='Harvey |t|>3')
    ax.axhline(0, linestyle='-', color='black', lw=0.5)
    ax.set_xticks(xs)
    ax.set_xticklabels(['Binary EAV\n(bootstrap)', 'Continuous surprise\n(bootstrap)'])
    ax.set_ylabel('Bootstrap t-statistic')
    ax.set_title('US vs JP — Binary vs Continuous EAV t-stat (cross-market universality)')
    for i, (us_v, jp_v) in enumerate(zip([us_b_t, us_c_t], [jp_b_t, jp_c_t])):
        ax.text(i - width/2, us_v + 0.3, f'{us_v:+.2f}', ha='center', fontsize=9)
        ax.text(i + width/2, jp_v + 0.3, f'{jp_v:+.2f}', ha='center', fontsize=9)
    ax.legend(loc='best')
    plt.tight_layout()
    plt.savefig(plot2, dpi=120)
    plt.close()
    print(f'  -> {plot2}')

    # 9. Save results
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'Continuous earnings surprise vs binary EAV — JP TOPIX N=30 (universality test of K1151)',
        'proposer': 'Claude (承接 K1151 next_tasks K1157)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': 'yfinance daily close 2014-2025; yfinance get_earnings_dates(limit=100) Surprise(%)',
        'data_period': f'{DATA_START} ~ {DATA_END}',
        'tickers': TICKERS,
        'n_stocks_loaded': N_actual,
        'pooled_n_obs': n_total,
        'n_params_total_per_spec': k_total,
        'surp_summary': surp_summary,
        'binary_baseline': {
            'theta_eav': theta_b,
            'se_hessian': se_b,
            't_hessian': float(t_b_hess) if np.isfinite(t_b_hess) else None,
            'pooled_loglik': fit_b['pooled_loglik'],
            'pooled_negll': fit_b['pooled_negll'],
            'aic': aic_b,
            'bic': bic_b,
            'converged': fit_b['converged'],
            'n_outer_iters': fit_b['n_outer_iters'],
            'bootstrap': {
                'n_boot_target': 150,
                'n_boot_completed': int(len(boot_b)),
                **bs_b,
                'draws': boot_b.tolist(),
            },
        },
        'continuous_surprise': {
            'theta_surp': theta_c,
            'se_hessian': se_c,
            't_hessian': float(t_c_hess) if np.isfinite(t_c_hess) else None,
            'pooled_loglik': fit_c['pooled_loglik'],
            'pooled_negll': fit_c['pooled_negll'],
            'aic': aic_c,
            'bic': bic_c,
            'converged': fit_c['converged'],
            'n_outer_iters': fit_c['n_outer_iters'],
            'bootstrap': {
                'n_boot_target': 150,
                'n_boot_completed': int(len(boot_c)),
                **bs_c,
                'draws': boot_c.tolist(),
            },
        },
        'comparison': {
            'delta_aic_binary_minus_continuous': aic_b - aic_c,
            'delta_bic_binary_minus_continuous': bic_b - bic_c,
            'positive_delta_favours': 'continuous',
        },
        'robustness_dropout_continuous': dropout,
        'mechanism_verdict': mechanism,
        'universality_verdict': universality,
        'paper2_narrative_recommendation': narrative,
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results -> {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  FINAL MECHANISM VERDICT: {mechanism}')
    print(f'  UNIVERSALITY VERDICT:    {universality}')


if __name__ == '__main__':
    main()
