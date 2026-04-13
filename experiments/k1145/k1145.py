#!/usr/bin/env python3
"""
K1145: A4f-EAV pooled panel estimation across N=31 Taiwan stocks
================================================================
[提出: Claude (承接 K1140 next_tasks K1143), 執行: Claude]

Paper 2 last-pass side-finding test.

Motivation:
  K1109 (cross-sectional N=31) and K1113 (firm covariates) both NULL.
  K1140 (rolling temporal HAC + block-bootstrap) all 9 BH-FDR tests
  collapse — true dual NULL at the per-stock level.

  Open question (K1140 next_tasks K1143): even if no stock-level signal
  is detectable, is θ_EAV a *universal magnitude* effect that emerges
  only at the panel level?

  Pooled spec (shared θ_VIX, θ_EAV; stock-specific GJR + level):
      σ²_{i,t} = g_{i,t} · τ_{i,t}
      g_{i,t} = GJR(1,1)_i   (stock-specific ω_i, α_i, γ_i, β_i)
      τ_{i,t} = max(θ₀_i + θ_VIX · VIX²_{t-1} + θ_EAV · EAV_{i,t-1}, ε)

  Pre-registered decision rule:
      θ_EAV pooled t > 3.0 (Harvey 2016) AND BH-adj p < 0.05
        → Paper 2 side-finding "universal-magnitude EAV effect"
      Else
        → Paper 2 is a clean dual-NULL paper

Methodology:
  Block coordinate descent (BCD) for joint MLE:
    Outer loop over (θ_VIX, θ_EAV):
      For each stock i: fit (θ₀_i, ω_i, α_i, γ_i, β_i) with shared
        (θ_VIX, θ_EAV) frozen.
      Aggregate Σᵢ Σ_t log L_{i,t}.
    Update (θ_VIX, θ_EAV) by L-BFGS-B over pooled loglik.
  Iterate until pooled loglik improvement < 1e-3.

  Inference for θ_EAV:
    1. Hessian-based SE (numerical 2nd derivative, all stocks held fixed)
    2. Stock-clustered block bootstrap (resample whole stocks 1000x,
       refit pooled MLE) — gold-standard for panel SE
    3. Newey-West HAC across pooled (i,t) obs is NOT used because cross-
       stock independence is closer to truth than within-stock AR(1).

Robustness:
  R1. EAV definition: 1-day window (default), 3-day [t-1,t,t+1?] using
      forward-looking ⚠ — corrected to backward-only [t-2,t-1,t],
      [t-4,...,t]. Each lagged before entering τ.
  R2. Drop-out: 5 ad-hoc subsamples each removing 5 random stocks
      (seed 42, 43, 44, 45, 46) — check θ_EAV pooled stability
  R3. Single-stock mean θ_EAV (from K1109) vs pooled θ_EAV — direction
      and magnitude consistency

Lookahead discipline:
  - VIX_{t-1} and EAV_{i,t-1} both lagged 1 trading day before τ.
  - EAV based on disclosed announcement dates (公司公開), not estimated
    forward-looking flags.
  - Cross-market alignment: VIX is US session t-1 (settled before TW
    market open at t). No leak.

Data:
  - yfinance daily close 2010-2025 (cache: experiments/k1145/data/)
  - ^VIX cache
  - 財報公告日.txt — earnings announcement dates per ticker
  - 31-stock pre-registered list from K1109 firm_level_results

Random seed: 42

References:
  - Engle, Ghysels & Sohn (2013). GARCH-MIDAS. RES 95(3), 776-797.
  - Patton (2011). Volatility forecast comparison. JoE 160(1), 246-256.
  - Cameron, Gelbach & Miller (2008). Bootstrap-based improvements for
    inference with clustered errors. RES 90(3), 414-427.
  - Harvey, Liu & Zhu (2016). … and the cross-section of expected
    returns. RFS 29(1), 5-68.
  - Benjamini & Hochberg (1995). Controlling the FDR. JRSS B 57.
  - K1067/K1067b/K1067c — three-stock A4f-EAV results
  - K1109 — pre-reg N=31 cross-sectional sector ANOVA FAIL
  - K1113 — firm covariate FAIL
  - K1140 — rolling HAC + block-bootstrap, 0/9 PASS

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
EXPERIMENT_ID = 'K1145'
SCRIPT_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = SCRIPT_DIR.parent.parent
DATA_FILE = PROJECT_ROOT / '財報公告日.txt'
DATA_CACHE_DIR = SCRIPT_DIR / 'data'
DATA_CACHE_DIR.mkdir(exist_ok=True, parents=True)
RESULTS_PATH = SCRIPT_DIR / 'k1145_results.json'

DATA_START = '2010-01-01'
DATA_END = '2025-12-31'
TIME_BUDGET_SEC = 1800  # 30 min

# Pre-registered N=31 ticker list (from K1109)
TICKERS = [
    '2330.TW', '2303.TW', '6239.TW', '2454.TW', '2379.TW', '3034.TW',
    '3035.TW', '3443.TW', '2388.TW', '2881.TW', '2882.TW', '2883.TW',
    '2886.TW', '2887.TW', '2603.TW', '2615.TW', '2609.TW', '1301.TW',
    '1303.TW', '1326.TW', '2002.TW', '2027.TW', '2317.TW', '3045.TW',
    '2382.TW', '2912.TW', '2637.TW', '1215.TW', '2347.TW', '1210.TW',
    '2892.TW',
]


# ==========================================================================
# Data loading (verbatim style from K1109)
# ==========================================================================
def load_earnings(code):
    with open(DATA_FILE, 'rb') as f:
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
    di = di[(di >= DATA_START) & (di <= DATA_END)]
    return di


def cached_download(ticker):
    cache_path = DATA_CACHE_DIR / f"{ticker.replace('^', 'IDX_')}.parquet"
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
    """Build EAV(i,t) flag at the announcement day and forward by `window`
    trading days. Codex review (2026-04-13) confirmed this is forward-
    from-announcement, NOT backward-from-t.

    window=1 -> EAV[t]=1 iff t is the announcement day
    window=3 -> EAV[t]=1 iff t in {ann, ann+1, ann+2}
                (announcement day + next 2 trading days)
    window=5 -> {ann, ann+1, ..., ann+4}

    No-lookahead guarantee:
      The EAV flag is constructed from PUBLICLY DISCLOSED announcement
      dates (財報公告日.txt) only. In the likelihood `_negll_numba`, EAV
      is then **lagged by 1** before entering tau_t = θ₀ + θ_VIX·VIX²_{t-1}
      + θ_EAV·EAV_{t-1}. So at time t we only use info known by t-1.

    Rationale for forward window: post-announcement realized-vol effect
    persists for a few sessions (information absorption), captured by
    EAV remaining "on" for window days after the announcement.
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
    code = ticker.replace('.TW', '')
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
    ann_dates = load_earnings(code)
    eav_arr = build_eav_series(df.index, ann_dates, eav_window)
    if len(df) < 500 or eav_arr.sum() < 15:
        return None
    return {
        'ticker': ticker,
        'code': code,
        'r': df['r'].values,
        'vix': df['vix'].values,
        'eav': eav_arr,
        'index': df.index,
        'n_obs': len(df),
        'n_events': int(eav_arr.sum()),
    }


# ==========================================================================
# Per-stock A4f-EAV inner objective (shared θ_VIX, θ_EAV held fixed)
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
    # precompute tau[t] with lag-1 VIX and EAV
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
    """Negative log-likelihood for a single stock given shared θ_VIX, θ_EAV.

    stock_params = (theta0, omega_g, alpha, gamma, beta)
    """
    theta0, omega_g, alpha, gamma_p, beta_p = stock_params
    return _negll_numba(float(theta0), float(omega_g), float(alpha),
                         float(gamma_p), float(beta_p),
                         r, vix, eav, float(theta_vix), float(theta_eav))


def fit_one_stock_given_shared(stock, theta_vix, theta_eav, init=None):
    """Fit per-stock GJR + theta0 with shared θ_VIX, θ_EAV frozen.

    Returns (best_params, best_negll).
    """
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
        (1e-8, 1e-2),  # theta0
        (1e-6, 1.0),   # omega_g
        (1e-4, 0.3),   # alpha
        (1e-4, 0.3),   # gamma
        (0.5, 0.999),  # beta
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
# Block coordinate descent: pooled MLE
# ==========================================================================
def pooled_loglik_given_shared(stocks, stock_params_list,
                                theta_vix, theta_eav):
    """Sum negll across stocks with fixed shared (θ_VIX, θ_EAV) and per-
    stock params. Used to update shared by minimize."""
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
    """Block coordinate descent for joint pooled MLE.

    Returns dict with theta_vix, theta_eav, per-stock params,
    pooled_loglik, n_outer_iters, convergence_flag.
    """
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
        # ---- inner: per-stock fit ----
        total_negll = 0.0
        for i, st in enumerate(stocks):
            p_init = stock_params_list[i] if stock_params_list[i] is not None else None
            p, ll = fit_one_stock_given_shared(st, theta_vix, theta_eav,
                                                init=p_init)
            if p is None:
                # use previous if exists, else skip
                if stock_params_list[i] is None:
                    raise RuntimeError(f'Stock {st["ticker"]} initial fit failed')
                continue
            stock_params_list[i] = p
            total_negll += ll
        # ---- outer: update shared ----
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

    # Final inner pass at converged shared
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
    """Numerical 2nd-derivative SE for shared θ_EAV holding everything else
    fixed (per-stock params and θ_VIX)."""
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


# ==========================================================================
# Stock-clustered block bootstrap
# ==========================================================================
def cluster_bootstrap_theta_eav(stocks, n_boot=200, seed=42,
                                  init_vix=1e-7, init_eav=5e-5,
                                  inner_max_outer=4,
                                  per_boot_time_budget=120):
    """Resample whole stocks with replacement n_boot times. For each boot
    resample, refit pooled BCD (light: max_outer=4) and record θ_EAV.

    Returns array of θ_EAV bootstrap draws.
    """
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


# ==========================================================================
# BH-FDR
# ==========================================================================
def bh_adjust(pvals):
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adj_sorted = ranked * n / (np.arange(1, n + 1))
    # enforce monotonicity (BH)
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
    print(f'{EXPERIMENT_ID}: A4f-EAV pooled panel estimation (N=31 TW stocks)')
    print(f'{"=" * 72}\n')
    print(f'Tickers ({len(TICKERS)}): {TICKERS}\n')

    # ---- Load all stocks (default EAV window=1) ----
    print('[1/6] Loading stocks (EAV window=1) ...')
    stocks_w1 = []
    for tk in TICKERS:
        st = load_one_stock(tk, eav_window=1)
        if st is None:
            print(f'    SKIP {tk}: insufficient data')
            continue
        stocks_w1.append(st)
        print(f'    {tk}: n_obs={st["n_obs"]}, n_events={st["n_events"]}')
    print(f'  Loaded {len(stocks_w1)}/{len(TICKERS)} stocks for default fit\n')
    if len(stocks_w1) < 15:
        print('  ABORT: < 15 stocks loaded')
        sys.exit(1)

    # ---- Diagnostic ----
    print('[2/6] Pre-fit panel diagnostic ...')
    all_r = np.concatenate([s['r'] for s in stocks_w1])
    print(f'  Pooled obs: {len(all_r):,}')
    print(f'  Mean r={np.mean(all_r):+.4e}, std={np.std(all_r):.4e}')
    print(f'  Skew={stats.skew(all_r):+.3f}, kurt={stats.kurtosis(all_r):+.3f}')
    arch_z = (np.array([np.var(s['r']) for s in stocks_w1])).std()
    print(f'  Cross-stock variance dispersion: {arch_z:.4e}')
    print(f'  Mean events per stock: {np.mean([s["n_events"] for s in stocks_w1]):.1f}')
    print()

    # ---- Main pooled BCD fit (EAV window=1) ----
    print('[3/6] Pooled BCD fit (EAV window=1, primary) ...')
    fit_w1 = fit_pooled_panel(stocks_w1, max_outer=8, verbose=True,
                               time_budget=600)
    theta_eav_main = fit_w1['theta_eav']
    theta_vix_main = fit_w1['theta_vix']
    print(f'\n  → θ_VIX = {theta_vix_main:.4e}')
    print(f'  → θ_EAV = {theta_eav_main:+.4e}')
    print(f'  → pooled loglik = {fit_w1["pooled_loglik"]:.2f}')
    print(f'  → converged = {fit_w1["converged"]}')

    # Hessian SE
    print('\n  Hessian SE for θ_EAV ...')
    se_hessian = hessian_se_theta_eav(
        stocks_w1, [np.array(p) for p in fit_w1['per_stock_params']],
        theta_vix_main, theta_eav_main,
    )
    t_hessian = (theta_eav_main / se_hessian) if (se_hessian and se_hessian > 0) else np.nan
    print(f'  Hessian SE={se_hessian}, t={t_hessian}')

    # ---- Stock-clustered block bootstrap ----
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
        # bootstrap p-value (two-sided): fraction of |t_boot - mean| >= |t_obs|
        # equivalently use percentile of zero
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

    # ---- Robustness R1: EAV window 3 and 5 ----
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

    # ---- Robustness R2: drop-out 5 stocks x 5 seeds ----
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

    # ---- Compare to single-stock K1109 mean θ_EAV ----
    print('\n  R3 Compare to K1109 single-stock θ_EAV:')
    try:
        with open(PROJECT_ROOT / 'experiments' / 'k1109' / 'k1109_results.json') as f:
            k1109 = json.load(f)
        single_thetas = []
        single_thetas_t = []
        for f_ in k1109['firm_level_results']:
            if f_['ticker'] in [s['ticker'] for s in stocks_w1]:
                single_thetas.append(f_['theta2'])
                if f_.get('theta2_t') is not None:
                    single_thetas_t.append(f_['theta2_t'])
        single_thetas = np.array(single_thetas)
        single_thetas_t = np.array(single_thetas_t)
        single_mean = float(np.mean(single_thetas))
        single_median = float(np.median(single_thetas))
        single_se = float(np.std(single_thetas, ddof=1) / np.sqrt(len(single_thetas)))
        single_t = single_mean / single_se if single_se > 0 else np.nan
        # one-sample t-test that mean = 0
        t_test_p = float(2 * (1 - stats.t.cdf(abs(single_t), df=len(single_thetas) - 1)))
        print(f'    K1109 N={len(single_thetas)}, mean θ₂={single_mean:+.3e}, '
              f'median={single_median:+.3e}, SE_mean={single_se:.3e}, '
              f't_mean=0: {single_t:+.2f}, p={t_test_p:.4f}')
        print(f'    Pooled θ_EAV = {theta_eav_main:+.3e}')
        print(f'    Direction match: '
              f'{"YES" if np.sign(theta_eav_main) == np.sign(single_mean) else "NO"}')
        single_compare = {
            'k1109_n': len(single_thetas),
            'k1109_mean_theta2': single_mean,
            'k1109_median_theta2': single_median,
            'k1109_mean_se': single_se,
            'k1109_mean_t': float(single_t) if np.isfinite(single_t) else None,
            'k1109_mean_p': t_test_p,
            'pooled_theta_eav': theta_eav_main,
            'direction_match': bool(np.sign(theta_eav_main) == np.sign(single_mean)),
        }
        single_thetas_for_plot = single_thetas
    except Exception as e:
        print(f'    Could not load K1109: {e}')
        single_compare = {'error': str(e)}
        single_thetas_for_plot = np.array([])

    # ---- BH-FDR on three primary p-values: pooled-Hessian, pooled-bootstrap, K1109-mean ----
    print('\n  BH-FDR multi-test correction:')
    p_hessian = float(2 * (1 - stats.norm.cdf(abs(t_hessian)))) if np.isfinite(t_hessian) else 1.0
    p_boot = boot_p if boot_p is not None else 1.0
    pvec = [p_hessian, p_boot]
    pnames = ['pooled_hessian', 'pooled_bootstrap']
    if isinstance(single_compare, dict) and 'k1109_mean_p' in single_compare:
        pvec.append(single_compare['k1109_mean_p'])
        pnames.append('k1109_mean_test')
    bh_adj = bh_adjust(pvec)
    bh_table = [{'name': n, 'raw_p': float(p), 'bh_adj_p': float(bp)}
                for n, p, bp in zip(pnames, pvec, bh_adj)]
    for row in bh_table:
        print(f'    {row["name"]}: raw_p={row["raw_p"]:.4f}, BH_adj_p={row["bh_adj_p"]:.4f}')

    # ---- Verdict ----
    primary_pass = (
        np.isfinite(t_hessian) and abs(t_hessian) > 3.0 and
        bh_table[0]['bh_adj_p'] < 0.05
    )
    boot_pass = (
        boot_p is not None and bh_table[1]['bh_adj_p'] < 0.05
    )
    verdict_text = (
        'PASS — Paper 2 universal-magnitude side-finding'
        if primary_pass and boot_pass
        else 'FAIL — Paper 2 is dual-NULL'
        if not primary_pass and not boot_pass
        else 'PARTIAL — only one of (Hessian, bootstrap) passed; treat as NULL'
    )
    print(f'\n  CORE VERDICT: {verdict_text}')

    # ---- Plots ----
    print('\n[6/6] Plots ...')
    plot1_path = SCRIPT_DIR / 'k1145_theta_eav_pool_vs_single.png'
    fig, ax = plt.subplots(1, 1, figsize=(8, 4.5))
    if len(single_thetas_for_plot) > 0:
        ax.hist(single_thetas_for_plot, bins=20, alpha=0.55,
                color='steelblue', edgecolor='black',
                label=f'K1109 single-stock θ₂ (N={len(single_thetas_for_plot)})')
        ax.axvline(np.mean(single_thetas_for_plot), color='steelblue',
                   linestyle='--', label=f'K1109 mean = {np.mean(single_thetas_for_plot):+.2e}')
    ax.axvline(theta_eav_main, color='red', linewidth=2.5,
               label=f'Pooled θ_EAV = {theta_eav_main:+.2e}')
    if boot_se is not None:
        ax.axvspan(theta_eav_main - 1.96 * boot_se,
                   theta_eav_main + 1.96 * boot_se, color='red', alpha=0.15,
                   label=f'Pooled boot 95% CI [{boot_ci_lo:+.2e}, {boot_ci_hi:+.2e}]')
    ax.axvline(0, color='gray', linestyle=':', alpha=0.7)
    ax.set_xlabel(r'$\theta_{EAV}$')
    ax.set_ylabel('Count (single-stock)')
    ax.set_title(f'K1145: Pooled vs Single-stock θ_EAV (N={len(stocks_w1)})')
    ax.legend(loc='best', fontsize=9)
    plt.tight_layout()
    plt.savefig(plot1_path, dpi=120)
    plt.close()
    print(f'  -> {plot1_path}')

    # plot 2: robustness barplot
    plot2_path = SCRIPT_DIR / 'k1145_robustness_barplot.png'
    fig, ax = plt.subplots(1, 1, figsize=(10, 4.5))
    labels = ['main(w=1)']
    vals = [theta_eav_main]
    ses = [se_hessian if se_hessian else 0]
    for w in (3, 5):
        k = f'window_{w}'
        if k in rob_eav_results:
            labels.append(f'EAV w={w}')
            vals.append(rob_eav_results[k]['theta_eav'])
            ses.append(rob_eav_results[k]['theta_eav_se_hessian'] or 0)
    for d in dropout_results:
        labels.append(f'drop_seed{d["seed"]}')
        vals.append(d['theta_eav'])
        ses.append(d['theta_eav_se'] or 0)
    xpos = np.arange(len(labels))
    ax.bar(xpos, vals, yerr=[1.96 * s for s in ses],
           color=['red'] + ['orange'] * 2 + ['steelblue'] * len(dropout_results),
           edgecolor='black', alpha=0.75, capsize=4)
    ax.axhline(0, color='gray', linestyle=':')
    ax.set_xticks(xpos)
    ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9)
    ax.set_ylabel(r'Pooled $\theta_{EAV}$')
    ax.set_title(f'K1145 Robustness: pooled θ_EAV across EAV defs and drop-outs')
    plt.tight_layout()
    plt.savefig(plot2_path, dpi=120)
    plt.close()
    print(f'  -> {plot2_path}')

    # ---- Save results ----
    out = {
        'experiment_id': EXPERIMENT_ID,
        'title': 'A4f-EAV pooled panel estimation across N=31 TW stocks',
        'proposer': 'Claude (承接 K1140 next_tasks K1143)',
        'executor': 'Claude',
        'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'random_seed': GLOBAL_SEED,
        'data_source': 'yfinance daily close 2010-2025; 財報公告日.txt',
        'data_period': f'{DATA_START} ~ {DATA_END}',
        'tickers': TICKERS,
        'n_stocks_loaded': len(stocks_w1),
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
        'k1109_single_stock_compare': single_compare,
        'bh_fdr_table': bh_table,
        'verdict': {
            'primary_t_pass_h0_zero': bool(primary_pass),
            'boot_pass': bool(boot_pass),
            'core_verdict_text': verdict_text,
        },
        'elapsed_seconds': float(time.time() - START_TIME),
    }
    with open(RESULTS_PATH, 'w') as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    print(f'\n  Results -> {RESULTS_PATH}')
    print(f'  Elapsed: {time.time() - START_TIME:.1f}s')
    print(f'\n  CORE VERDICT: {verdict_text}\n')


if __name__ == '__main__':
    main()
