#!/usr/bin/env python3
"""
K1162: Analyst-coverage-high sub-sample continuous EAV mechanism test
=======================================================================
[提出: Claude (承接 K1151 next_tasks K1162), 執行: Claude]

Research question
-----------------
K1151 (US N=30) + K1157 (JP N=30) both found that the continuous
earnings-surprise spec (z-scored |Surprise%| on announcement window)
is non-significant (US bootstrap t=+1.11, JP bootstrap t=+1.32), with
a massive ΔAIC favouring binary (US -5479, JP -2551). Verdict so far:
BINARY SUFFICIENT.

K1162 hypothesis: maybe the continuous signal is dominated by
noise-to-signal in low-analyst-coverage stocks (where yfinance
Surprise% is itself a noisy proxy). If we restrict to HIGH-coverage
stocks (≥ median analyst count), the continuous θ_SURP should be
cleaner and potentially significant. If even the HIGH subset remains
NS → "binary sufficient" is fundamental, not a noise artifact.

Decision tree
-------------
| HIGH continuous bootstrap t | LOW continuous bootstrap t | Verdict |
|----------------------------|---------------------------|--------|
| > 3 | < 2 | NOISE-MASKED — continuous works in clean subset |
| < 2 | < 2 | BINARY-FUNDAMENTAL — no noise-masking; binary sufficient is real |
| < 2 | > 3 | COUNTERINTUITIVE — re-check code/data |
| both > 3 | both > 3 | BOTH SIGNAL — continuous broadly works but pooled power was just low |
| ambiguous | ambiguous | INCONCLUSIVE |

Method (mirrors K1151)
----------------------
1. Pool: K1147/K1151 US N=30 large-caps, 2014-01-01~2025-12-31.
2. Analyst coverage: yfinance `numberOfAnalystOpinions` current snapshot
   (fetch_coverage.py).
3. Split at pool median (32.5 analysts): HIGH n=15 (tech/consumer
   megacaps, 33-64 analysts), LOW n=15 (defensives/financials + BRK-B,
   3-32 analysts).
4. For each subset, run the exact K1151 continuous spec pooled MLE:
     σ²_{i,t} = g_{i,t} · τ_{i,t}
     g_{i,t} = GJR(1,1)_i
     τ_{i,t} = max(θ₀_i + θ_VIX·VIX²_{t-1} + θ_SURP·surp_z_{i,t-1}, ε)
   where surp_z = (clipped(|surp%|, p99) - mean) / std across the
   **subset** pool (not global — each subset standardises within).
5. Hessian SE + cluster bootstrap n=150 (seed=42) on θ_SURP shared.
6. Also fit binary EAV on each subset for internal ΔAIC comparison.
7. Within-subset placebo n=60 (permute surp_z within stock).
8. Wald test for θ_HIGH = θ_LOW using bootstrap SEs.

Lookahead discipline
--------------------
- Analyst coverage is the CURRENT snapshot (not trailing 12M — yfinance
  free API doesn't provide it). Limitation acknowledged in README.
- All in-panel regressors (surp_z, VIX) are lagged t-1, same as K1151.
- Random seed = 42.

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
EXPERIMENT_ID = 'K1162'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = SCRIPT_DIR / 'data'
EARNINGS_DATES_CACHE = DATA_DIR / 'earnings_dates.json'
EARNINGS_SURPRISE_CACHE = DATA_DIR / 'earnings_surprises.json'
COVERAGE_PATH = DATA_DIR / 'coverage.json'
RESULTS_PATH = SCRIPT_DIR / 'k1162_results.json'

DATA_START = '2014-01-01'
DATA_END = '2025-12-31'

# Same 30 S&P 500 large-caps as K1147/K1151
TICKERS = [
    'AAPL', 'MSFT', 'NVDA', 'GOOGL', 'AMZN', 'META', 'TSLA', 'BRK-B',
    'UNH', 'V', 'JPM', 'WMT', 'MA', 'JNJ', 'XOM', 'PG', 'HD', 'CVX',
    'ABBV', 'AVGO', 'COST', 'PEP', 'KO', 'MRK', 'ADBE', 'CSCO', 'TMO',
    'CRM', 'MCD', 'ABT',
]

SURP_WINSOR_PCT = 99.0


# ==========================================================================
# Data loading (mirrors k1151, but DATA_DIR scoped to k1162)
# ==========================================================================
def load_cached_prices(ticker):
    safe_name = ticker.replace('^', 'IDX_').replace('-', '_')
    cache_path = DATA_DIR / f"{safe_name}.parquet"
    if not cache_path.exists():
        return None
    return pd.read_parquet(cache_path)


def load_earnings_dates_only(ticker):
    with open(EARNINGS_DATES_CACHE) as f:
        cache = json.load(f)
    if ticker not in cache:
        return pd.DatetimeIndex([])
    dates = [pd.Timestamp(d) for d in cache[ticker]]
    return pd.DatetimeIndex(dates)


def load_earnings_surprises(ticker):
    with open(EARNINGS_SURPRISE_CACHE) as f:
        cache = json.load(f)
    if ticker not in cache:
        return {}
    out = {}
    for rec in cache[ticker]:
        out[pd.Timestamp(rec['date']).normalize()] = abs(float(rec['surprise_pct']))
    return out


def build_eav_binary(trading_days, ann_dates, window):
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
    vix = vix_raw['Close'].reindex(prices.index, method='ffill')
    df = pd.DataFrame({'r': log_ret, 'vix': vix}).dropna()
    df = df[df['r'].abs() <= 0.30]
    ann_dates = load_earnings_dates_only(ticker)
    surp_map = load_earnings_surprises(ticker)
    eav_b = build_eav_binary(df.index, ann_dates, window)
    surp_raw = build_surp_raw(df.index, ann_dates, surp_map, window)
    if len(df) < 500 or eav_b.sum() < 15:
        return None
    return {
        'ticker': ticker,
        'r': df['r'].values,
        'vix': df['vix'].values,
        'eav_b': eav_b,
        'surp_raw': surp_raw,
        'index': df.index,
        'n_obs': len(df),
        'n_events_binary': int(eav_b.sum()),
        'n_events_surp': int((surp_raw > 0).sum()),
    }


def standardize_continuous(stocks, winsor_pct=SURP_WINSOR_PCT):
    """Winsor + z-score |surprise| across this stock pool (subset-local)."""
    all_surp = np.concatenate([s['surp_raw'] for s in stocks])
    nonzero = all_surp[all_surp > 0]
    if len(nonzero) == 0:
        raise RuntimeError('No non-zero surprise values')
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
    }


# ==========================================================================
# Estimator (identical to k1151)
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


# ==========================================================================
# Subset pipeline
# ==========================================================================
def run_subset(label, tickers_subset, init_vix=9e-8):
    print(f'\n{"=" * 72}\n[SUBSET {label}]  tickers={tickers_subset}')
    stocks = []
    for tk in tickers_subset:
        s = load_one_stock(tk, window=1)
        if s is None:
            print(f'  SKIP {tk} (insufficient data)')
            continue
        stocks.append(s)
    N_actual = len(stocks)
    print(f'  Loaded {N_actual}/{len(tickers_subset)} stocks')
    if N_actual < 10:
        raise RuntimeError(f'subset {label} too small: {N_actual}')

    stocks, surp_summary = standardize_continuous(stocks)
    print(f'  Subset p99 threshold = {surp_summary["p99_threshold_pct"]:.2f}%')
    print(f'  Subset n_nonzero events = {surp_summary["n_nonzero_total"]}')
    print(f'  Subset mean_clipped = {surp_summary["mean_nonzero_clipped"]:.2f}, '
          f'std_clipped = {surp_summary["std_nonzero_clipped"]:.2f}')

    # Binary baseline on this subset (internal reference)
    print(f'\n  [{label}] Binary EAV baseline ...')
    fit_b = fit_pooled_panel(
        stocks, 'eav_b',
        max_outer=8, init_vix=init_vix, init_x=5e-5,
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
    print(f'  [{label}] Binary θ_EAV = {theta_b:+.4e}, t_hess={t_b_hess:+.2f}')

    # Continuous on this subset
    print(f'\n  [{label}] Continuous surp_z ...')
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
    print(f'  [{label}] Continuous θ_SURP = {theta_c:+.4e}, t_hess={t_c_hess:+.2f}')

    # AIC
    k_total = N_actual * 5 + 2
    n_total = int(sum(s['n_obs'] for s in stocks))
    aic_b, bic_b = aic_bic(fit_b['pooled_negll'], k_total, n_total)
    aic_c, bic_c = aic_bic(fit_c['pooled_negll'], k_total, n_total)
    print(f'  [{label}] AIC binary={aic_b:.2f}, AIC cont={aic_c:.2f}, ΔAIC (bin-cont)={aic_b-aic_c:+.2f}')

    # Bootstrap on continuous (primary)
    print(f'\n  [{label}] Cluster bootstrap CONTINUOUS (n=150) ...')
    boot_c = cluster_bootstrap(
        stocks, 'surp_z', n_boot=150, seed=GLOBAL_SEED,
        init_vix=fit_c['theta_vix'], init_x=theta_c,
        inner_max_outer=2, per_boot_time_budget=45,
        bounds_x=(-1e-2, 1e-2),
    )
    bs_c = boot_stats(boot_c, theta_c)
    print(f'  [{label}] Continuous boot: draws={len(boot_c)}, '
          f'mean={bs_c["mean"]}, t={bs_c["t"]}, p={bs_c["p"]}')

    # Bootstrap binary for internal check
    print(f'\n  [{label}] Cluster bootstrap BINARY (n=150) ...')
    boot_b = cluster_bootstrap(
        stocks, 'eav_b', n_boot=150, seed=GLOBAL_SEED,
        init_vix=fit_b['theta_vix'], init_x=theta_b,
        inner_max_outer=2, per_boot_time_budget=45,
        bounds_x=(-1e-2, 1e-2),
    )
    bs_b = boot_stats(boot_b, theta_b)
    print(f'  [{label}] Binary boot: draws={len(boot_b)}, '
          f'mean={bs_b["mean"]}, t={bs_b["t"]}, p={bs_b["p"]}')

    return {
        'label': label,
        'tickers': tickers_subset,
        'n_stocks_loaded': N_actual,
        'pooled_n_obs': n_total,
        'k_total': k_total,
        'surp_summary': surp_summary,
        'binary': {
            'theta_eav': theta_b,
            'se_hessian': se_b,
            't_hessian': float(t_b_hess) if np.isfinite(t_b_hess) else None,
            'pooled_loglik': fit_b['pooled_loglik'],
            'pooled_negll': fit_b['pooled_negll'],
            'aic': aic_b, 'bic': bic_b,
            'converged': fit_b['converged'],
            'n_outer_iters': fit_b['n_outer_iters'],
            'bootstrap': {
                'n_boot_target': 150, 'n_boot_completed': int(len(boot_b)),
                **bs_b, 'draws': boot_b.tolist(),
            },
        },
        'continuous': {
            'theta_surp': theta_c,
            'se_hessian': se_c,
            't_hessian': float(t_c_hess) if np.isfinite(t_c_hess) else None,
            'pooled_loglik': fit_c['pooled_loglik'],
            'pooled_negll': fit_c['pooled_negll'],
            'aic': aic_c, 'bic': bic_c,
            'converged': fit_c['converged'],
            'n_outer_iters': fit_c['n_outer_iters'],
            'bootstrap': {
                'n_boot_target': 150, 'n_boot_completed': int(len(boot_c)),
                **bs_c, 'draws': boot_c.tolist(),
            },
        },
        'delta_aic_binary_minus_continuous': aic_b - aic_c,
        'delta_bic_binary_minus_continuous': bic_b - bic_c,
    }


def wald_test_theta_diff(res_high, res_low):
    """Wald H0: θ_HIGH = θ_LOW using bootstrap SEs (independent subsets)."""
    tH = res_high['continuous']['theta_surp']
    tL = res_low['continuous']['theta_surp']
    seH = res_high['continuous']['bootstrap']['se']
    seL = res_low['continuous']['bootstrap']['se']
    if seH is None or seL is None:
        return {'theta_diff': tH - tL, 'se_diff': None, 'wald_t': None, 'p': None}
    se_diff = float(np.sqrt(seH ** 2 + seL ** 2))
    wald_t = (tH - tL) / se_diff if se_diff > 0 else np.nan
    # two-sided p from normal approx
    p = 2 * (1 - stats.norm.cdf(abs(wald_t))) if np.isfinite(wald_t) else None
    return {
        'theta_high': tH, 'theta_low': tL,
        'theta_diff': tH - tL, 'se_diff': se_diff,
        'wald_t': float(wald_t) if np.isfinite(wald_t) else None,
        'p_two_sided': float(p) if p is not None else None,
    }


def decide_verdict(res_high, res_low):
    tH = res_high['continuous']['bootstrap']['t'] or 0.0
    tL = res_low['continuous']['bootstrap']['t'] or 0.0
    if tH > 3 and tL < 2:
        verdict = 'NOISE-MASKED — high-coverage continuous PASSES, low-coverage NS → noise in low-coverage stocks masks the surprise-magnitude effect'
    elif tH < 2 and tL < 2:
        verdict = 'BINARY-FUNDAMENTAL — both subsets NS, "binary sufficient" is not a noise artifact; announcement-day clustering is the true mechanism'
    elif tH < 2 and tL > 3:
        verdict = 'COUNTERINTUITIVE — low-coverage NS with high-coverage PASSING is the opposite of expectations; re-check data and code'
    elif tH > 3 and tL > 3:
        verdict = 'BOTH SIGNAL — continuous works in both subsets; pooled K1151 just had low power or dilution'
    else:
        verdict = 'AMBIGUOUS'
    return verdict


# ==========================================================================
# Main
# ==========================================================================
def main():
    print(f'\n{"=" * 72}')
    print(f'{EXPERIMENT_ID}: Analyst-coverage sub-sample continuous EAV (US N=30)')
    print(f'{"=" * 72}\n')

    # Load coverage
    with open(COVERAGE_PATH) as f:
        coverage = json.load(f)
    cov_map = {r['ticker']: r for r in coverage}
    analyst_counts = [(r['ticker'], r['numAnalysts']) for r in coverage
                      if r['numAnalysts'] is not None]
    analyst_counts.sort(key=lambda x: x[1])
    vals = [c[1] for c in analyst_counts]
    median_n = float(np.median(vals))
    print(f'Coverage snapshot: n={len(analyst_counts)}, '
          f'min={min(vals)}, median={median_n}, max={max(vals)}')

    # Split at median (ties go to LOW per <= rule; with 30 stocks and
    # median=32.5 the split is exactly 15/15)
    low_tickers = [t for t, n in analyst_counts if n <= median_n]
    high_tickers = [t for t, n in analyst_counts if n > median_n]
    if len(low_tickers) != len(high_tickers):
        print(f'  WARN: uneven split low={len(low_tickers)}, high={len(high_tickers)}')
    print(f'  LOW  (n={len(low_tickers)}):  {low_tickers}')
    print(f'  HIGH (n={len(high_tickers)}): {high_tickers}')

    # Run both subsets
    res_low = run_subset('LOW', low_tickers)
    res_high = run_subset('HIGH', high_tickers)

    # Wald test
    wald = wald_test_theta_diff(res_high, res_low)
    print(f'\n[WALD] θ_HIGH - θ_LOW = {wald["theta_diff"]:+.4e}, '
          f'SE_diff={wald["se_diff"]}, t={wald["wald_t"]}, p={wald["p_two_sided"]}')

    # Verdict
    verdict = decide_verdict(res_high, res_low)
    print(f'\n[VERDICT] {verdict}')

    # Paper 2 narrative recommendation
    if 'NOISE-MASKED' in verdict:
        narrative = ('Continuous surprise spec is viable for HIGH-coverage '
                     'stocks. Paper 2 should carve out a HIGH-coverage '
                     'robustness section; full pool binary remains main spec.')
    elif 'BINARY-FUNDAMENTAL' in verdict:
        narrative = ('Binary EAV as main spec is NOT a noise artifact — '
                     'even in the clean HIGH-coverage sub-sample continuous '
                     'surprise fails. K1162 strengthens the mechanism claim: '
                     'announcement-day information-processing friction, '
                     'not surprise magnitude.')
    elif 'BOTH SIGNAL' in verdict:
        narrative = ('Continuous surprise works in both subsets; re-examine '
                     'the K1151 pooled result for dilution/scaling issues.')
    else:
        narrative = 'See verdict; report both subsets side by side.'
    print(f'[PAPER 2 NARRATIVE] {narrative}')

    # Plots
    print('\n[PLOTS]')
    plot1 = SCRIPT_DIR / 'k1162_tstat_barplot.png'
    fig, ax = plt.subplots(1, 1, figsize=(8, 5))
    labels = ['LOW\nHessian', 'LOW\nBootstrap',
              'HIGH\nHessian', 'HIGH\nBootstrap']
    tvals = [
        res_low['continuous']['t_hessian'] or 0,
        res_low['continuous']['bootstrap']['t'] or 0,
        res_high['continuous']['t_hessian'] or 0,
        res_high['continuous']['bootstrap']['t'] or 0,
    ]
    colors = ['#8c564b', '#8c564b', '#2ca02c', '#2ca02c']
    ax.bar(np.arange(4), tvals, color=colors, alpha=0.75, edgecolor='black')
    ax.axhline(3, linestyle='--', color='gray', label='Harvey |t|>3')
    ax.axhline(-3, linestyle='--', color='gray')
    ax.axhline(0, linestyle='-', color='black', lw=0.5)
    ax.set_xticks(np.arange(4))
    ax.set_xticklabels(labels)
    ax.set_ylabel('t-statistic')
    ax.set_title(f'K1162 — Continuous θ_SURP t-stat (LOW vs HIGH analyst coverage, US)')
    for i, v in enumerate(tvals):
        ax.text(i, v + (0.5 if v > 0 else -0.8), f'{v:+.2f}',
                ha='center', fontsize=10, fontweight='bold')
    ax.legend(loc='best')
    plt.tight_layout()
    plt.savefig(plot1, dpi=120)
    plt.close()
    print(f'  -> {plot1}')

    # Coverage distribution plot
    plot2 = SCRIPT_DIR / 'k1162_coverage_dist.png'
    fig, ax = plt.subplots(1, 1, figsize=(9, 4.5))
    sorted_pairs = sorted(analyst_counts, key=lambda x: x[1])
    xs = np.arange(len(sorted_pairs))
    ys = [p[1] for p in sorted_pairs]
    colors2 = ['#8c564b' if n <= median_n else '#2ca02c' for _, n in sorted_pairs]
    ax.bar(xs, ys, color=colors2, alpha=0.8, edgecolor='black')
    ax.axhline(median_n, linestyle='--', color='red',
               label=f'median = {median_n:g}')
    ax.set_xticks(xs)
    ax.set_xticklabels([p[0] for p in sorted_pairs], rotation=60, fontsize=8)
    ax.set_ylabel('# of analyst opinions (yfinance snapshot)')
    ax.set_title('K1162 — US N=30 analyst coverage distribution (brown=LOW, green=HIGH)')
    ax.legend()
    plt.tight_layout()
    plt.savefig(plot2, dpi=120)
    plt.close()
    print(f'  -> {plot2}')

    # Save results
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'Analyst-coverage-high sub-sample continuous EAV mechanism test — US N=30 split into HIGH/LOW by yfinance numberOfAnalystOpinions',
        'proposer': 'Claude (承接 K1151 next_tasks K1162)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': (
            'yfinance daily close 2014-2025 + get_earnings_dates(limit=100) '
            'Surprise(%) cache from K1151; analyst coverage = '
            'yfinance.Ticker.info["numberOfAnalystOpinions"] current snapshot'
        ),
        'data_period': f'{DATA_START} ~ {DATA_END}',
        'coverage_proxy': 'yfinance numberOfAnalystOpinions (current snapshot)',
        'split_rule': f'pool median = {median_n}; LOW = coverage ≤ median, HIGH = coverage > median',
        'coverage_raw': coverage,
        'tickers_low': low_tickers,
        'tickers_high': high_tickers,
        'subset_LOW': res_low,
        'subset_HIGH': res_high,
        'wald_theta_high_minus_low': wald,
        'verdict': verdict,
        'paper2_narrative_recommendation': narrative,
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results -> {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  FINAL MECHANISM VERDICT: {verdict}')


if __name__ == '__main__':
    main()
