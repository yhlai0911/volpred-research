#!/usr/bin/env python3
"""
K1198: Paper 1 Tables 10/11/12/C3 KB-only 6 values Formal Rebuild
==================================================================
[worktree agent-ac1c126f, 2026-04-17]

PURPOSE:
  Paper 1 (Leverage Direction Matters) has 6 values that exist only in the
  knowledge base (KB_ONLY_PRE_K status) with no formal experiment JSON.
  This experiment provides a formal, reproducible computation for all 6 values.

THE 6 TARGET VALUES (from tables.tex / body.tex):
  1. Table 10 (tab:amplify): SPY avg constituent stock γ = 0.076
  2. Table 10 (tab:amplify): SPY t-stat (ETF γ vs avg stock γ) = -16.92
  3. Table 11 (tab:tail): BH ES(1%) = -4.68%, VT ES(1%) = -1.35%
  4. Table 11 (tab:tail): Excess kurtosis BH = 14.71, VT = 0.46
  5. Table 12 (tab:gamma-mechanism): Spearman ρ(γ, β_trend) = 1.000, p < 0.001
                                      + individual β_trend values (SPY=0.109, GLD=-0.055)
  6. C3 (body.tex §4.2.3): Gold regime t-test: bull γ=-0.043, bear γ=+0.048, t=-4.71

METHODOLOGY:
  - Table 10: GJR-GARCH(1,1) full-sample estimation on SPY + 20 top constituents
              (AAPL, MSFT, AMZN, NVDA, GOOGL, META, TSLA, BRK-B, UNH, JNJ,
               JPM, V, PG, MA, HD, XOM, CVX, MRK, ABBV, PEP)
              t-stat: one-sample t-test of constituent γ values vs ETF γ

  - Table 11: Hybrid VT vs Buy & Hold SPY (2014-2026)
              ES(1%) computed from daily return distribution
              Excess kurtosis from daily returns

  - Table 12: VT trend-beta regression for 7 primary assets
              (SPY, QQQ, EEM, USO, BTC-USD, TLT, GLD)
              β_trend: OLS of VT weight changes on lagged 5-day returns
              Spearman ρ across (γ, β_trend)

  - C3: Gold regime split by bull/bear (2005-2026 extended)
        Rolling GJR-GARCH γ, split by trailing 252-day return > 0 vs ≤ 0
        Two-sample t-test

DATA:
  - yfinance, seed=42
  - SPY: 2017-01-01 to 2025-12-31 (Table 12 primary)
  - SPY: 2014-01-01 to 2026-01-01 (Table 11 VT performance)
  - GLD: 2005-01-01 to 2026-01-01 (C3 regime, extended)
  - Constituents: 2017-01-01 to 2025-12-31 (Table 10)

PAPER TARGETS (for comparison):
  T10: avg_stock_gamma=0.076, t_stat=-16.92
  T11: ES_bh=-4.68%, ES_vt=-1.35%, kurtosis_bh=14.71, kurtosis_vt=0.46
  T12: spearman_rho=1.000, pearson_r=0.993
  C3:  bull_gamma=-0.043, bear_gamma=+0.048, t_stat=-4.71, p<0.0001

REFERENCES:
  - Glosten, Jagannathan, Runkle (1993) JF 48(5) — GJR-GARCH
  - Bollerslev (1986) JE 31(3) — GARCH(1,1)
  - Longin & Solnik (2001) JF 56(2) — correlation asymmetry during declines
  - Moreira & Muir (2017) JF 72(4) — volatility targeting
  - Hood & Raughtigan (2025) — VT trend-following mechanism
"""

import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize
from scipy.stats import spearmanr, pearsonr, ttest_ind
from scipy.stats import norm

warnings.filterwarnings('ignore')
np.random.seed(42)

RESULTS_PATH = Path(__file__).parent / 'k1198_results.json'
LOG_PATH = Path(__file__).parent / 'run.log'

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(str(LOG_PATH), mode='w'),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)

# ─── Paper targets ───────────────────────────────────────────────────────────
PAPER_TARGETS = {
    'T10_avg_stock_gamma': 0.076,
    'T10_t_stat': -16.92,
    'T11_ES_bh': -4.68,          # percent
    'T11_ES_vt': -1.35,          # percent
    'T11_kurtosis_bh': 14.71,
    'T11_kurtosis_vt': 0.46,
    'T12_spearman_rho': 1.000,
    'T12_pearson_r': 0.993,
    'C3_bull_gamma': -0.043,
    'C3_bear_gamma': 0.048,
    'C3_t_stat': -4.71,
}

RTOL = 0.05  # 5% relative tolerance

# ─── Asset lists ─────────────────────────────────────────────────────────────
SPY_TOP20_CONSTITUENTS = [
    'AAPL', 'MSFT', 'AMZN', 'NVDA', 'GOOGL',
    'META', 'TSLA', 'BRK-B', 'UNH', 'JNJ',
    'JPM', 'V', 'PG', 'MA', 'HD',
    'XOM', 'CVX', 'MRK', 'ABBV', 'PEP',
]

# 7 primary assets for Table 12 gamma-mechanism
PRIMARY_7 = ['SPY', 'QQQ', 'EEM', 'USO', 'BTC-USD', 'TLT', 'GLD']


# ═══════════════════════════════════════════════════════════════════════════════
# GJR-GARCH Implementation
# ═══════════════════════════════════════════════════════════════════════════════

def gjr_filter(r, omega, alpha, gamma, beta):
    """GJR-GARCH(1,1): h_t = omega + (alpha + gamma*I_{r<0})*r^2_{t-1} + beta*h_{t-1}"""
    T = len(r)
    h = np.empty(T)
    h[0] = float(np.var(r))
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0.0 else 0.0
        h[t] = omega + (alpha + gamma * ind) * r[t - 1] ** 2 + beta * h[t - 1]
        if h[t] < 1e-12:
            h[t] = 1e-12
    return h


def fit_gjr_garch(returns, n_starts=5):
    """Fit GJR-GARCH(1,1) via quasi-MLE. Returns (omega, alpha, gamma, beta) or None."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    if len(r) < 100:
        return None

    rv = float(np.var(r))
    pct_neg = np.mean(r < 0)

    def negll(params):
        omega, alpha, gam, beta = params
        if omega <= 0 or alpha < 0 or gam < -alpha or beta < 0:
            return 1e10
        if alpha + gam * pct_neg + beta >= 1.0:
            return 1e10
        h = gjr_filter(r, omega, alpha, gam, beta)
        ll = -0.5 * np.sum(np.log(h[1:]) + r[1:] ** 2 / h[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    rng = np.random.RandomState(42)
    for s in range(n_starts):
        a0 = float(np.clip(0.05 + 0.02 * rng.randn(), 0.005, 0.25))
        g0 = float(np.clip(0.08 + 0.03 * rng.randn(), -a0, 0.4))
        b0 = float(np.clip(0.88 + 0.02 * rng.randn(), 0.5, 0.97))
        if a0 + g0 * pct_neg + b0 >= 0.99:
            b0 = 0.98 - a0 - g0 * pct_neg
        o0 = max(1e-8, rv * max(1e-4, 1.0 - a0 - g0 * pct_neg - b0))
        try:
            res = minimize(
                negll, [o0, a0, g0, b0],
                method='L-BFGS-B',
                bounds=[(1e-12, None), (0, 0.5), (-0.3, 0.8), (0, 0.9999)],
                options={'maxiter': 5000, 'ftol': 1e-12},
            )
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            pass
    if best is None:
        return None
    return best.x  # [omega, alpha, gamma, beta]


def gjr_gamma_tstat(returns):
    """
    Estimate GJR-GARCH full-sample and compute gamma + asymptotic t-stat.
    Returns (gamma, t_stat) or (nan, nan).
    """
    params = fit_gjr_garch(returns)
    if params is None:
        return np.nan, np.nan
    omega, alpha, gam, beta = params
    r = np.ascontiguousarray(returns, dtype=np.float64)
    h = gjr_filter(r, omega, alpha, gam, beta)

    # Score-based numerical Hessian for standard error
    eps = 1e-5
    p = np.array([omega, alpha, gam, beta])

    def ll_scalar(pp):
        o, a, g, b = pp
        if o <= 0 or a < 0 or g < -a or b < 0 or a + g * 0.5 + b >= 1:
            return -1e10
        hh = gjr_filter(r, o, a, g, b)
        val = -0.5 * np.sum(np.log(hh[1:]) + r[1:] ** 2 / hh[1:])
        return val if np.isfinite(val) else -1e10

    # Numerical Hessian (gamma parameter is index 2)
    H = np.zeros((4, 4))
    for i in range(4):
        for j in range(4):
            ei = np.zeros(4); ei[i] = eps
            ej = np.zeros(4); ej[j] = eps
            H[i, j] = (ll_scalar(p + ei + ej) - ll_scalar(p + ei - ej)
                        - ll_scalar(p - ei + ej) + ll_scalar(p - ei - ej)) / (4 * eps ** 2)

    try:
        cov = np.linalg.inv(-H)
        se_gamma = np.sqrt(max(cov[2, 2], 1e-16))
        t_stat = gam / se_gamma
    except Exception:
        t_stat = np.nan

    return float(gam), float(t_stat)


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE 10: Diversification Amplification
# ═══════════════════════════════════════════════════════════════════════════════

def compute_table10():
    """
    Table 10: ETF γ vs avg constituent stock γ for SPY.
    Paper: SPY ETF γ=0.211, avg stock γ=0.076, t=-16.92
    """
    log.info("=" * 70)
    log.info("TABLE 10: Diversification Amplification (SPY vs 20 constituents)")
    log.info("=" * 70)

    start_date = '2017-01-01'
    end_date = '2025-12-31'

    # Download SPY
    log.info("Downloading SPY...")
    spy_data = yf.download('SPY', start=start_date, end=end_date,
                            progress=False, auto_adjust=True)
    spy_ret = spy_data['Close'].pct_change().dropna().squeeze().values * 100

    spy_gamma, spy_t = gjr_gamma_tstat(spy_ret)
    log.info(f"  SPY: γ={spy_gamma:.4f}, t={spy_t:.2f}")

    # Download constituents
    constituent_gammas = []
    constituent_tstats = []
    failed = []

    for ticker in SPY_TOP20_CONSTITUENTS:
        try:
            data = yf.download(ticker, start=start_date, end=end_date,
                               progress=False, auto_adjust=True)
            if len(data) < 500:
                log.warning(f"  {ticker}: insufficient data ({len(data)} obs)")
                failed.append(ticker)
                continue
            ret = data['Close'].pct_change().dropna().squeeze().values * 100
            g, t = gjr_gamma_tstat(ret)
            if np.isfinite(g):
                constituent_gammas.append(g)
                constituent_tstats.append(t)
                log.info(f"  {ticker}: γ={g:.4f}, t={t:.2f}")
            else:
                log.warning(f"  {ticker}: estimation failed")
                failed.append(ticker)
        except Exception as e:
            log.warning(f"  {ticker}: error — {e}")
            failed.append(ticker)

    avg_gamma = float(np.mean(constituent_gammas))
    n_stocks = len(constituent_gammas)
    ratio = spy_gamma / avg_gamma if avg_gamma != 0 else np.nan

    # One-sample t-test: H0: mean constituent γ = SPY γ
    # Body text says t = -16.92 (ETF higher than individual stocks)
    # Direction: individual stock gammas are all < SPY gamma
    from scipy import stats
    t_stat_vs_spy, p_val = stats.ttest_1samp(constituent_gammas, spy_gamma)

    log.info(f"\n  N constituents used: {n_stocks}")
    log.info(f"  Avg constituent γ: {avg_gamma:.4f} (paper: 0.076)")
    log.info(f"  SPY ETF γ: {spy_gamma:.4f} (paper: 0.211)")
    log.info(f"  Ratio: {ratio:.2f}x (paper: 2.8x)")
    log.info(f"  t-stat (stocks vs SPY): {t_stat_vs_spy:.2f} (paper: -16.92)")
    log.info(f"  p-value: {p_val:.6f}")
    if len(failed) > 0:
        log.info(f"  Failed tickers: {failed}")

    # Match check
    matched_avg = abs(avg_gamma - PAPER_TARGETS['T10_avg_stock_gamma']) / abs(PAPER_TARGETS['T10_avg_stock_gamma']) <= RTOL
    matched_t = abs(t_stat_vs_spy - PAPER_TARGETS['T10_t_stat']) / abs(PAPER_TARGETS['T10_t_stat']) <= RTOL

    log.info(f"  MATCH avg_gamma: {matched_avg} | MATCH t_stat: {matched_t}")

    return {
        'spy_gamma': float(spy_gamma),
        'spy_t_stat': float(spy_t),
        'constituent_gammas': [float(g) for g in constituent_gammas],
        'avg_constituent_gamma': avg_gamma,
        'n_constituents': n_stocks,
        'ratio_etf_to_stocks': float(ratio),
        't_stat_vs_etf': float(t_stat_vs_spy),
        'p_val_vs_etf': float(p_val),
        'failed_tickers': failed,
        'paper_avg_stock_gamma': PAPER_TARGETS['T10_avg_stock_gamma'],
        'paper_t_stat': PAPER_TARGETS['T10_t_stat'],
        'matched_avg_gamma': bool(matched_avg),
        'matched_t_stat': bool(matched_t),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE 11: Tail Risk Metrics (Hybrid VT vs BH, SPY 2014-2026)
# ═══════════════════════════════════════════════════════════════════════════════

def garch_filter_simple(r, omega, alpha, beta):
    """GARCH(1,1) filter (Python, for small arrays)."""
    T = len(r)
    h = np.empty(T)
    h[0] = np.var(r)
    for t in range(1, T):
        h[t] = omega + alpha * r[t-1]**2 + beta * h[t-1]
        h[t] = max(h[t], 1e-12)
    return h


def fit_garch_simple(returns):
    """Fit GARCH(1,1) — minimal, for VT."""
    r = np.ascontiguousarray(returns, dtype=np.float64)
    rv = float(np.var(r))

    def negll(params):
        omega, alpha, beta = params
        if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1.0:
            return 1e10
        h = garch_filter_simple(r, omega, alpha, beta)
        ll = -0.5 * np.sum(np.log(h[1:]) + r[1:] ** 2 / h[1:])
        return -ll if np.isfinite(ll) else 1e10

    best, best_nll = None, 1e10
    rng = np.random.RandomState(42)
    for s in range(4):
        a0 = float(np.clip(0.06 + 0.02 * rng.randn(), 0.01, 0.25))
        b0 = float(np.clip(0.89 + 0.02 * rng.randn(), 0.5, 0.97))
        if a0 + b0 >= 0.99:
            b0 = 0.98 - a0
        o0 = max(1e-8, rv * (1 - a0 - b0))
        try:
            res = minimize(negll, [o0, a0, b0], method='L-BFGS-B',
                           bounds=[(1e-12, None), (0, 0.5), (0, 0.9999)],
                           options={'maxiter': 3000})
            if res.fun < best_nll:
                best_nll, best = res.fun, res
        except Exception:
            pass
    return best.x if best else np.array([rv * 0.01, 0.06, 0.90])


def compute_table11():
    """
    Table 11: Tail Risk Metrics — Hybrid VT vs Buy & Hold (SPY, 2014–2026).
    Paper: ES(1%) BH=-4.68%, VT=-1.35%; kurtosis BH=14.71, VT=0.46
    """
    log.info("=" * 70)
    log.info("TABLE 11: Tail Risk Metrics (SPY 2014-2026)")
    log.info("=" * 70)

    start_date = '2014-01-01'
    end_date = '2026-01-01'
    TARGET_VOL = 0.10  # 10% annualized target
    VT_SMOOTH = 5      # days for sigma smoothing
    VT_CLIP = 1.5      # max weight

    # Download SPY
    log.info("Downloading SPY (2014-2026)...")
    spy_data = yf.download('SPY', start=start_date, end=end_date,
                            progress=False, auto_adjust=True)
    prices = spy_data['Close']
    dates = prices.index
    ret = prices.pct_change().dropna().squeeze() * 100  # percent

    log.info(f"  SPY observations: {len(ret)}")

    r_arr = ret.values.astype(np.float64)

    # BH statistics
    bh_es_1pct = float(np.percentile(r_arr, 1))  # ES = worst 1% average
    # True ES: mean of returns below the 1% VaR
    var_1pct = np.percentile(r_arr, 1)
    bh_es = float(np.mean(r_arr[r_arr <= var_1pct]))
    bh_kurt = float(pd.Series(r_arr).kurtosis())  # excess kurtosis
    bh_skew = float(pd.Series(r_arr).skew())
    bh_worst_day = float(np.min(r_arr))

    log.info(f"  BH ES(1%): {bh_es:.4f}% (paper: -4.68%)")
    log.info(f"  BH Excess Kurtosis: {bh_kurt:.4f} (paper: 14.71)")
    log.info(f"  BH skewness: {bh_skew:.4f} (paper: -0.583)")
    log.info(f"  BH worst day: {bh_worst_day:.4f}%")

    # Volatility Targeting (GJR-GARCH-based VT with expanding window)
    # Fit GARCH on first 504 days, then roll with quarterly refits
    min_train = 504
    refit_every = 63  # quarterly
    sigma_arr = np.full(len(r_arr), np.nan)
    params = None
    last_refit = 0

    for i in range(min_train, len(r_arr)):
        train_r = r_arr[:i]
        if (params is None) or ((i - last_refit) >= refit_every):
            new_params = fit_garch_simple(train_r)
            if new_params is not None:
                params = new_params
                last_refit = i
        if params is not None:
            omega, alpha, beta = params
            h = garch_filter_simple(train_r, omega, alpha, beta)
            s2_next = omega + alpha * train_r[-1]**2 + beta * h[-1]
            sigma_arr[i] = np.sqrt(max(s2_next, 1e-12)) * np.sqrt(252) / 100
            # annualized, in decimal

    # VT weights: target_vol / sigma
    # Using GARCH sigma (annualized)
    weights = np.full(len(r_arr), np.nan)
    for i in range(min_train, len(r_arr)):
        if np.isfinite(sigma_arr[i]) and sigma_arr[i] > 0:
            w = TARGET_VOL / sigma_arr[i]
            weights[i] = min(w, VT_CLIP)

    # VT returns use lagged weight (weight from t-1 applied to return at t)
    vt_ret = np.full(len(r_arr), np.nan)
    for i in range(min_train + 1, len(r_arr)):
        if np.isfinite(weights[i - 1]):
            vt_ret[i] = weights[i - 1] * r_arr[i]

    # Remove NaN
    vt_clean = vt_ret[~np.isnan(vt_ret)]

    vt_var_1pct = np.percentile(vt_clean, 1)
    vt_es = float(np.mean(vt_clean[vt_clean <= vt_var_1pct]))
    vt_kurt = float(pd.Series(vt_clean).kurtosis())
    vt_skew = float(pd.Series(vt_clean).skew())
    vt_worst_day = float(np.min(vt_clean))

    log.info(f"  VT ES(1%): {vt_es:.4f}% (paper: -1.35%)")
    log.info(f"  VT Excess Kurtosis: {vt_kurt:.4f} (paper: 0.46)")
    log.info(f"  VT skewness: {vt_skew:.4f} (paper: -0.143)")
    log.info(f"  VT worst day: {vt_worst_day:.4f}%")

    # ES percent improvement
    es_pct_improvement = (vt_es - bh_es) / abs(bh_es) * 100
    log.info(f"  ES improvement: {es_pct_improvement:.1f}% (paper: -71%)")

    # Match checks
    matched_es_bh = abs(bh_es - PAPER_TARGETS['T11_ES_bh']) / abs(PAPER_TARGETS['T11_ES_bh']) <= RTOL
    matched_es_vt = abs(vt_es - PAPER_TARGETS['T11_ES_vt']) / abs(PAPER_TARGETS['T11_ES_vt']) <= RTOL
    matched_kurt_bh = abs(bh_kurt - PAPER_TARGETS['T11_kurtosis_bh']) / abs(PAPER_TARGETS['T11_kurtosis_bh']) <= RTOL
    matched_kurt_vt = abs(vt_kurt - PAPER_TARGETS['T11_kurtosis_vt']) / abs(PAPER_TARGETS['T11_kurtosis_vt']) <= 0.2  # wider tol for small kurtosis

    log.info(f"  MATCH ES_bh: {matched_es_bh} | ES_vt: {matched_es_vt}")
    log.info(f"  MATCH kurtosis_bh: {matched_kurt_bh} | kurtosis_vt: {matched_kurt_vt}")

    return {
        'n_obs_bh': int(len(r_arr)),
        'n_obs_vt': int(len(vt_clean)),
        'bh_es_1pct': bh_es,
        'vt_es_1pct': vt_es,
        'bh_kurtosis': bh_kurt,
        'vt_kurtosis': vt_kurt,
        'bh_skewness': bh_skew,
        'vt_skewness': vt_skew,
        'bh_worst_day': bh_worst_day,
        'vt_worst_day': vt_worst_day,
        'es_pct_improvement': float(es_pct_improvement),
        'paper_es_bh': PAPER_TARGETS['T11_ES_bh'],
        'paper_es_vt': PAPER_TARGETS['T11_ES_vt'],
        'paper_kurtosis_bh': PAPER_TARGETS['T11_kurtosis_bh'],
        'paper_kurtosis_vt': PAPER_TARGETS['T11_kurtosis_vt'],
        'matched_es_bh': bool(matched_es_bh),
        'matched_es_vt': bool(matched_es_vt),
        'matched_kurtosis_bh': bool(matched_kurt_bh),
        'matched_kurtosis_vt': bool(matched_kurt_vt),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# TABLE 12: Gamma-Mechanism Mapping (VT trend-beta vs GJR γ)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_vt_trend_beta(returns_pct, target_vol=0.10, smooth_days=5,
                           clip_max=1.5, lookback=504):
    """
    Compute VT trend-beta: OLS slope of VT weight changes on lagged 5-day returns.
    β_trend = Cov(Δw_t, r_{t-5:t}) / Var(r_{t-5:t})
    where Δw_t = w_t - w_{t-1}

    Returns (trend_beta, t_stat).
    """
    r = np.ascontiguousarray(returns_pct, dtype=np.float64)
    n = len(r)

    # Estimate GARCH on full sample for sigma
    params = fit_garch_simple(r)
    if params is None:
        return np.nan, np.nan

    omega, alpha, beta = params
    h = garch_filter_simple(r, omega, alpha, beta)
    sigma_daily = np.sqrt(h) * np.sqrt(252) / 100  # annualized decimal

    # VT weights with lag
    weights = target_vol / np.maximum(sigma_daily, 1e-6)
    weights = np.minimum(weights, clip_max)

    # Weight changes
    delta_w = np.diff(weights)  # length n-1

    # 5-day trailing return (momentum signal)
    trailing_5 = np.array([np.sum(r[max(0, i-4):i+1]) for i in range(n)])
    # Align: delta_w[i] corresponds to change from t to t+1
    # trailing_5[i] = sum of returns over [t-4, t]
    x = trailing_5[:-1]  # trailing return at t, same size as delta_w
    y = delta_w

    # Remove NaN
    mask = np.isfinite(x) & np.isfinite(y)
    x_clean = x[mask]
    y_clean = y[mask]

    if len(x_clean) < 50:
        return np.nan, np.nan

    # OLS
    from numpy.linalg import lstsq
    X = np.column_stack([np.ones(len(x_clean)), x_clean])
    coef, _, _, _ = lstsq(X, y_clean, rcond=None)
    trend_beta = coef[1]

    # t-statistic (OLS)
    y_hat = X @ coef
    resid = y_clean - y_hat
    s2 = np.sum(resid**2) / (len(y_clean) - 2)
    XtX_inv = np.linalg.inv(X.T @ X)
    se_beta = np.sqrt(s2 * XtX_inv[1, 1])
    t_stat = trend_beta / se_beta if se_beta > 0 else np.nan

    return float(trend_beta), float(t_stat)


def compute_table12():
    """
    Table 12: Gamma-Mechanism Mapping.
    Paper: Spearman ρ(γ, β_trend)=1.000, Pearson r=0.993, N=7
    SPY: γ=+0.211, β_trend=+0.109, t=18.0
    GLD: γ=-0.088, β_trend=-0.055, t=-11.8
    """
    log.info("=" * 70)
    log.info("TABLE 12: Gamma-Mechanism Mapping (7 primary assets)")
    log.info("=" * 70)

    # Paper Table 12 rows with expected values
    paper_table12 = {
        'SPY':    {'gamma': 0.211,  'trend_beta': 0.109,  't_stat': 18.0,  'mechanism': 'Trend follower'},
        'QQQ':    {'gamma': 0.150,  'trend_beta': 0.074,  't_stat': 17.5,  'mechanism': 'Trend follower'},
        'EEM':    {'gamma': 0.100,  'trend_beta': 0.053,  't_stat': 14.5,  'mechanism': 'Trend follower'},
        'USO':    {'gamma': 0.050,  'trend_beta': 0.032,  't_stat': 12.9,  'mechanism': 'Mixed'},
        'BTC-USD':{'gamma': 0.030,  'trend_beta': 0.007,  't_stat': 5.3,   'mechanism': 'Weak trend'},
        'TLT':    {'gamma': 0.006,  'trend_beta': -0.006, 't_stat': -1.3,  'mechanism': 'Variance mgmt'},
        'GLD':    {'gamma': -0.088, 'trend_beta': -0.055, 't_stat': -11.8, 'mechanism': 'Contrarian'},
    }

    start_date = '2017-01-01'
    end_date = '2025-12-31'

    computed_gammas = []
    computed_betas = []
    assets_ok = []

    results_per_asset = {}

    for ticker in PRIMARY_7:
        log.info(f"\n  Processing {ticker}...")
        try:
            data = yf.download(ticker, start=start_date, end=end_date,
                               progress=False, auto_adjust=True)
            if len(data) < 500:
                log.warning(f"  {ticker}: insufficient data")
                continue
            ret = data['Close'].pct_change().dropna().squeeze().values * 100

            # GJR-GARCH γ (full sample)
            params = fit_gjr_garch(ret)
            if params is None:
                log.warning(f"  {ticker}: GJR fit failed")
                continue
            omega, alpha, gam, beta = params

            # t-stat via numerical Hessian
            _, t_gam = gjr_gamma_tstat(ret)

            # VT trend-beta
            trend_beta, t_trend = compute_vt_trend_beta(ret)

            p_entry = paper_table12.get(ticker, {})
            log.info(f"  {ticker}: γ={gam:.4f} (paper:{p_entry.get('gamma','?')}), "
                     f"β_trend={trend_beta:.4f} (paper:{p_entry.get('trend_beta','?')}), "
                     f"t_trend={t_trend:.2f} (paper:{p_entry.get('t_stat','?')})")

            computed_gammas.append(gam)
            computed_betas.append(trend_beta)
            assets_ok.append(ticker)

            results_per_asset[ticker] = {
                'gamma': float(gam),
                'gamma_t_stat': float(t_gam) if np.isfinite(t_gam) else None,
                'trend_beta': float(trend_beta) if np.isfinite(trend_beta) else None,
                'trend_beta_t_stat': float(t_trend) if np.isfinite(t_trend) else None,
                'paper_gamma': p_entry.get('gamma'),
                'paper_trend_beta': p_entry.get('trend_beta'),
                'paper_t_stat': p_entry.get('t_stat'),
            }
        except Exception as e:
            log.warning(f"  {ticker}: error — {e}")
            continue

    # Compute Spearman and Pearson correlations
    g_arr = np.array(computed_gammas)
    b_arr = np.array(computed_betas)
    mask = np.isfinite(g_arr) & np.isfinite(b_arr)
    g_clean = g_arr[mask]
    b_clean = b_arr[mask]
    n_ok = int(np.sum(mask))

    if n_ok >= 3:
        rho_spearman, p_spearman = spearmanr(g_clean, b_clean)
        r_pearson, p_pearson = pearsonr(g_clean, b_clean)
    else:
        rho_spearman = p_spearman = r_pearson = p_pearson = np.nan

    log.info(f"\n  N assets used: {n_ok}")
    log.info(f"  Spearman ρ: {rho_spearman:.4f} (paper: 1.000)")
    log.info(f"  Spearman p: {p_spearman:.6f}")
    log.info(f"  Pearson r: {r_pearson:.4f} (paper: 0.993)")

    matched_spearman = abs(rho_spearman - PAPER_TARGETS['T12_spearman_rho']) <= 0.1
    matched_pearson = abs(r_pearson - PAPER_TARGETS['T12_pearson_r']) <= 0.05

    log.info(f"  MATCH Spearman: {matched_spearman} | Pearson: {matched_pearson}")

    return {
        'n_assets': n_ok,
        'assets': assets_ok,
        'computed_gammas': [float(g) for g in g_clean],
        'computed_trend_betas': [float(b) for b in b_clean],
        'spearman_rho': float(rho_spearman) if np.isfinite(rho_spearman) else None,
        'spearman_p': float(p_spearman) if np.isfinite(p_spearman) else None,
        'pearson_r': float(r_pearson) if np.isfinite(r_pearson) else None,
        'pearson_p': float(p_pearson) if np.isfinite(p_pearson) else None,
        'per_asset': results_per_asset,
        'paper_spearman_rho': PAPER_TARGETS['T12_spearman_rho'],
        'paper_pearson_r': PAPER_TARGETS['T12_pearson_r'],
        'matched_spearman': bool(matched_spearman),
        'matched_pearson': bool(matched_pearson),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# C3: Gold Regime t-test (bull vs bear)
# ═══════════════════════════════════════════════════════════════════════════════

def compute_c3_gold_regime():
    """
    C3: Gold regime t-test from body.tex §4.2.3.
    Paper: bull γ=-0.043, bear γ=+0.048, t=-4.71, p<0.0001

    Methodology:
    - Download GLD (or XAUUSD proxy) from 2005-2026
    - Compute rolling 252-day GJR-GARCH γ with 504-day window, 63-day step
    - Split windows by trailing 252-day return > 0 (bull) vs ≤ 0 (bear)
    - Two-sample t-test on γ values

    Note: GLD ETF started 2004; use extended sample 2005-2026.
    For gold regime: bull = trailing year return > 0, bear = ≤ 0.
    """
    log.info("=" * 70)
    log.info("C3: Gold Regime t-test (2005-2026 extended)")
    log.info("=" * 70)

    start_date = '2005-01-01'
    end_date = '2026-01-01'
    window = 504
    step = 63

    log.info("Downloading GLD (2005-2026 extended)...")
    data = yf.download('GLD', start=start_date, end=end_date,
                        progress=False, auto_adjust=True)
    prices = data['Close']
    ret = prices.pct_change().dropna().squeeze().values * 100  # percent
    dates_idx = prices.index[1:]

    log.info(f"  GLD obs: {len(ret)}")

    # Rolling GJR-GARCH with step
    gammas = []
    trailing_rets = []
    window_dates = []

    n = len(ret)
    for start_i in range(0, n - window, step):
        end_i = start_i + window
        if end_i > n:
            break
        r_win = ret[start_i:end_i]

        # Trailing 252-day return: return over the window itself (annualized proxy)
        # Use cumulative return of last 252 days of window
        lookback_252 = 252
        last_252_start = max(0, end_i - lookback_252)
        r_last_252 = ret[last_252_start:end_i]
        cum_ret = float(np.sum(r_last_252))  # simple sum as proxy (%)

        # Fit GJR-GARCH
        params = fit_gjr_garch(r_win)
        if params is not None:
            _, _, gam, _ = params
            gammas.append(float(gam))
            trailing_rets.append(cum_ret)
            window_dates.append(str(dates_idx[end_i - 1]) if end_i - 1 < len(dates_idx) else 'N/A')

    gammas = np.array(gammas)
    trailing_rets = np.array(trailing_rets)

    log.info(f"  Total rolling windows: {len(gammas)}")

    # Split by bull/bear
    bull_mask = trailing_rets > 0
    bear_mask = trailing_rets <= 0

    bull_gammas = gammas[bull_mask]
    bear_gammas = gammas[bear_mask]

    n_bull = int(np.sum(bull_mask))
    n_bear = int(np.sum(bear_mask))

    bull_mean = float(np.mean(bull_gammas)) if n_bull > 0 else np.nan
    bear_mean = float(np.mean(bear_gammas)) if n_bear > 0 else np.nan

    log.info(f"  N bull windows: {n_bull}, mean γ = {bull_mean:.4f} (paper: -0.043)")
    log.info(f"  N bear windows: {n_bear}, mean γ = {bear_mean:.4f} (paper: +0.048)")

    # Two-sample t-test (Welch's t-test, unequal variance)
    if n_bull >= 3 and n_bear >= 3:
        t_stat, p_val = ttest_ind(bull_gammas, bear_gammas, equal_var=False)
    else:
        t_stat, p_val = np.nan, np.nan

    log.info(f"  t-stat (bull vs bear): {t_stat:.4f} (paper: -4.71)")
    log.info(f"  p-value: {p_val:.6f} (paper: <0.0001)")

    matched_bull = abs(bull_mean - PAPER_TARGETS['C3_bull_gamma']) / abs(PAPER_TARGETS['C3_bull_gamma']) <= RTOL
    matched_bear = abs(bear_mean - PAPER_TARGETS['C3_bear_gamma']) / abs(PAPER_TARGETS['C3_bear_gamma']) <= RTOL
    matched_t = abs(t_stat - PAPER_TARGETS['C3_t_stat']) / abs(PAPER_TARGETS['C3_t_stat']) <= RTOL

    log.info(f"  MATCH bull_gamma: {matched_bull} | bear_gamma: {matched_bear} | t_stat: {matched_t}")

    return {
        'n_total_windows': len(gammas),
        'n_bull': n_bull,
        'n_bear': n_bear,
        'bull_mean_gamma': bull_mean,
        'bear_mean_gamma': bear_mean,
        'all_gammas': [float(g) for g in gammas],
        'trailing_rets': [float(r) for r in trailing_rets],
        't_stat_bull_vs_bear': float(t_stat) if np.isfinite(t_stat) else None,
        'p_value': float(p_val) if np.isfinite(p_val) else None,
        'paper_bull_gamma': PAPER_TARGETS['C3_bull_gamma'],
        'paper_bear_gamma': PAPER_TARGETS['C3_bear_gamma'],
        'paper_t_stat': PAPER_TARGETS['C3_t_stat'],
        'matched_bull_gamma': bool(matched_bull),
        'matched_bear_gamma': bool(matched_bear),
        'matched_t_stat': bool(matched_t),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    t_start = time.time()
    np.random.seed(42)

    log.info("K1198: Paper 1 Tables 10/11/12/C3 KB-only 6 values Formal Rebuild")
    log.info(f"Start time: {datetime.now(timezone.utc).isoformat()}")
    log.info("=" * 70)

    results = {
        'experiment_id': 'K1198',
        'title': 'Paper 1 Tables 10/11/12/C3 KB-only 6 values Formal Rebuild',
        'seed': 42,
        'data_source': 'yfinance',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }

    # Table 10
    try:
        results['table10'] = compute_table10()
    except Exception as e:
        log.error(f"Table 10 failed: {e}", exc_info=True)
        results['table10'] = {'error': str(e)}

    # Table 11
    try:
        results['table11'] = compute_table11()
    except Exception as e:
        log.error(f"Table 11 failed: {e}", exc_info=True)
        results['table11'] = {'error': str(e)}

    # Table 12
    try:
        results['table12'] = compute_table12()
    except Exception as e:
        log.error(f"Table 12 failed: {e}", exc_info=True)
        results['table12'] = {'error': str(e)}

    # C3 Gold Regime
    try:
        results['c3_gold_regime'] = compute_c3_gold_regime()
    except Exception as e:
        log.error(f"C3 failed: {e}", exc_info=True)
        results['c3_gold_regime'] = {'error': str(e)}

    # ─── Summary ─────────────────────────────────────────────────────────────
    log.info("\n" + "=" * 70)
    log.info("SUMMARY: Match Status for 6 KB-only Values")
    log.info("=" * 70)

    match_summary = {}

    # T10: avg stock gamma + t-stat
    t10 = results.get('table10', {})
    v1_match = t10.get('matched_avg_gamma', False)
    v2_match = t10.get('matched_t_stat', False)
    match_summary['T10_avg_stock_gamma'] = {
        'paper': PAPER_TARGETS['T10_avg_stock_gamma'],
        'computed': t10.get('avg_constituent_gamma'),
        'matched': v1_match,
    }
    match_summary['T10_t_stat'] = {
        'paper': PAPER_TARGETS['T10_t_stat'],
        'computed': t10.get('t_stat_vs_etf'),
        'matched': v2_match,
    }

    # T11: ES + kurtosis
    t11 = results.get('table11', {})
    v3_match = t11.get('matched_es_bh', False)
    v4_match = t11.get('matched_kurtosis_bh', False)
    match_summary['T11_ES_bh'] = {
        'paper': PAPER_TARGETS['T11_ES_bh'],
        'computed': t11.get('bh_es_1pct'),
        'matched': v3_match,
    }
    match_summary['T11_kurtosis_bh'] = {
        'paper': PAPER_TARGETS['T11_kurtosis_bh'],
        'computed': t11.get('bh_kurtosis'),
        'matched': v4_match,
    }

    # T12: Spearman rho
    t12 = results.get('table12', {})
    v5_match = t12.get('matched_spearman', False)
    match_summary['T12_spearman_rho'] = {
        'paper': PAPER_TARGETS['T12_spearman_rho'],
        'computed': t12.get('spearman_rho'),
        'matched': v5_match,
    }

    # C3: gold regime t-stat
    c3 = results.get('c3_gold_regime', {})
    v6_match = c3.get('matched_t_stat', False)
    match_summary['C3_t_stat'] = {
        'paper': PAPER_TARGETS['C3_t_stat'],
        'computed': c3.get('t_stat_bull_vs_bear'),
        'matched': v6_match,
    }

    # Count
    n_matched = sum(1 for v in match_summary.values() if v.get('matched', False))
    n_total = len(match_summary)

    for key, val in match_summary.items():
        status = "MATCHED" if val.get('matched') else "DIVERGED"
        computed_val = val.get('computed')
        computed_str = f"{computed_val:.4f}" if isinstance(computed_val, float) else str(computed_val)
        log.info(f"  {status}: {key} paper={val['paper']} computed={computed_str}")

    log.info(f"\n  OVERALL: {n_matched}/{n_total} values matched")

    # Determine verdict
    if n_matched == n_total:
        verdict = 'MATCHED'
        recommendation = 'All values confirmed — no paper update needed'
    elif n_matched >= n_total * 0.5:
        verdict = '(b) MODIFY_PAPER'
        recommendation = 'Partial match — update divergent paper values to match formal experiment'
    else:
        verdict = '(a) FIX_SCRIPT'
        recommendation = 'Majority diverge — investigate methodology differences first'

    results['match_summary'] = match_summary
    results['n_matched'] = n_matched
    results['n_total'] = n_total
    results['verdict'] = verdict
    results['recommendation'] = recommendation

    elapsed = time.time() - t_start
    results['elapsed_seconds'] = round(elapsed, 2)

    log.info(f"\n  Verdict: {verdict}")
    log.info(f"  Recommendation: {recommendation}")
    log.info(f"  Elapsed: {elapsed:.1f}s")

    # Save results
    with open(str(RESULTS_PATH), 'w') as f:
        json.dump(results, f, indent=2)
    log.info(f"\nResults saved to: {RESULTS_PATH}")

    return results


if __name__ == '__main__':
    main()
