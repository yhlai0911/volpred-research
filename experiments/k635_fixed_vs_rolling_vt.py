#!/usr/bin/env python3
"""
K635: Fixed vs Rolling GARCH Parameters — Impact on VT Strategy Performance
=============================================================================
[提出: 用戶, 執行: Claude]

Motivation:
  K634 made a surprising finding: fixed GARCH parameters (estimated once from a
  large pre-OOS sample) produce BETTER QLIKE than rolling re-estimation (every
  21 days) for SPY. This directly challenges our rolling re-estimation methodology.

  The critical question is: does this QLIKE improvement translate to better
  ECONOMIC OUTCOMES (Sharpe, MDD, etc.) for the VT strategy? If not, this would
  be yet another confirmation of the "prediction ≠ application" principle
  (already confirmed 6 times in prior experiments).

Prior Knowledge:
  - K634: Fixed params → lower QLIKE than rolling (SPY: 1.464 vs 1.492)
  - K35/K36: GJR-GARCH baseline for SPY
  - K174/K175: Crisis parameter stability
  - K435: Hillebrand persistence inflation
  - K459/K474/K476: "Prediction ≠ application" confirmed multiple times

References:
  - Hillebrand (2005) "Neglecting parameter changes in GARCH models" JoE
  - Lamoureux & Lastrapes (1990) "Persistence in variance" JBES
  - Hansen & Lunde (2005) "A forecast comparison of volatility models" JoAE
  - Fleming, Kirby & Ostdiek (2001) "The economic value of volatility timing" JoFE

Data: SPY, GLD from yfinance (2006-01-01 to 2026-03-27)
OOS period: 2023-01-01 to 2024-12-31
"""

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

START_TIME = time.time()
EXPERIMENT_ID = "K635"
MAIN_REPO = "/Users/yhlai0911/Desktop/volpred-research"

# ============================================================================
# Configuration
# ============================================================================
DATA_START = "2005-01-01"
DATA_END = "2026-03-28"
ANALYSIS_START = "2006-01-01"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
ROLLING_WINDOW = 2000
REFIT_STEP = 21  # monthly re-estimation
TARGET_VOL = 0.10  # 10% annual target
MAX_WEIGHT = 1.5  # 150% cap
MIN_WEIGHT = 0.0  # no shorting
EWMA_LAMBDA = 0.94
TX_COST_BP = 2  # 2bp round-trip
RANDOM_SEED = 42

np.random.seed(RANDOM_SEED)


def P(msg):
    """Print with flush for real-time output."""
    print(msg, flush=True)


# ============================================================================
# Data Download
# ============================================================================
def download_data(ticker: str) -> pd.DataFrame:
    P(f"  Downloading {ticker}...")
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()
    df["return"] = np.log(df["Close"] / df["Close"].shift(1))
    df = df.dropna()
    df["rv"] = df["return"] ** 2  # daily realized variance proxy
    return df


def download_vix() -> pd.Series:
    P("  Downloading VIX...")
    vix = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    return vix["Close"].dropna()


# ============================================================================
# GJR-GARCH(1,1) Estimation (arch library)
# ============================================================================
try:
    from arch import arch_model
    HAS_ARCH = True
    P("  Using arch library for GARCH estimation")
except ImportError:
    HAS_ARCH = False
    P("  WARNING: arch library not found")
    sys.exit(1)


def fit_gjr_garch(returns):
    """Fit GJR-GARCH(1,1). Returns dict with omega, alpha, gamma, beta, persistence."""
    r = np.asarray(returns, dtype=np.float64) * 100  # percentage scale

    try:
        am = arch_model(r, vol='Garch', p=1, o=1, q=1, dist='normal', mean='Zero')
        res = am.fit(disp='off', options={'maxiter': 200})
        if res.convergence_flag != 0:
            return None
        omega = res.params['omega'] / 10000  # back to decimal
        alpha = res.params['alpha[1]']
        gamma = res.params['gamma[1]']
        beta = res.params['beta[1]']
        persistence = alpha + beta + gamma / 2.0
        return {
            "omega": float(omega),
            "alpha": float(alpha),
            "gamma": float(gamma),
            "beta": float(beta),
            "persistence": float(persistence),
            "converged": True,
            "loglik": float(res.loglikelihood),
        }
    except Exception:
        return None


# ============================================================================
# Sigma Forecast Methods
# ============================================================================
def gjr_sigma2_step(r_prev, sigma2_prev, params):
    """One-step GJR-GARCH variance update."""
    ind = 1.0 if r_prev < 0 else 0.0
    sigma2 = (params['omega'] +
              params['alpha'] * r_prev ** 2 +
              params['gamma'] * ind * r_prev ** 2 +
              params['beta'] * sigma2_prev)
    return max(sigma2, 1e-12)


def generate_rolling_sigma(returns, oos_start_idx, refit_step=21, rolling_window=2000):
    """Generate sigma forecasts using rolling re-estimated GJR-GARCH parameters."""
    T = len(returns)
    sigma2 = np.full(T, np.nan)

    # Pre-estimate all parameter sets needed
    param_records = []
    t = rolling_window
    while t <= T:
        window_rets = returns[t - rolling_window: t]
        result = fit_gjr_garch(window_rets)
        if result is not None and result["converged"]:
            param_records.append({"date_idx": t - 1, **result})
        t += refit_step

    if len(param_records) == 0:
        return sigma2, param_records

    sorted_records = sorted(param_records, key=lambda x: x['date_idx'])
    param_indices = [r['date_idx'] for r in sorted_records]

    # Initialize sigma2 chain
    prev_sigma2 = np.var(returns[:rolling_window])

    for t in range(rolling_window, T):
        idx = np.searchsorted(param_indices, t, side='right') - 1
        if idx < 0:
            continue
        p = sorted_records[idx]
        sigma2_t = gjr_sigma2_step(returns[t - 1], prev_sigma2, p)
        sigma2[t] = sigma2_t
        prev_sigma2 = sigma2_t

    return sigma2, param_records


def generate_fixed_sigma(returns, fixed_params, start_idx):
    """Generate sigma forecasts using fixed (pre-estimated) parameters."""
    T = len(returns)
    sigma2 = np.full(T, np.nan)
    prev_sigma2 = np.var(returns[:start_idx])

    for t in range(start_idx, T):
        sigma2_t = gjr_sigma2_step(returns[t - 1], prev_sigma2, fixed_params)
        sigma2[t] = sigma2_t
        prev_sigma2 = sigma2_t

    return sigma2


def generate_ewma_sigma(returns, lam=0.94):
    """Generate sigma forecasts using EWMA."""
    T = len(returns)
    sigma2 = np.full(T, np.nan)
    sigma2[0] = np.var(returns[:60]) if len(returns) > 60 else returns[0] ** 2
    for t in range(1, T):
        sigma2[t] = lam * sigma2[t - 1] + (1 - lam) * returns[t - 1] ** 2
    return sigma2


# ============================================================================
# VT Strategy
# ============================================================================
def run_vt_strategy(returns, sigma2_daily, oos_mask, target_vol=0.10,
                    max_w=1.5, min_w=0.0, tx_cost_bp=2):
    """
    Run Volatility Targeting strategy.

    w_t = target_vol / (sigma_annual_t)
    sigma_annual_t = sqrt(252 * sigma2_daily_t)

    Returns dict with strategy performance metrics.
    """
    T = len(returns)
    sigma_annual = np.sqrt(252 * sigma2_daily)

    # Compute weights
    weights = np.full(T, np.nan)
    for t in range(T):
        if np.isfinite(sigma_annual[t]) and sigma_annual[t] > 1e-8:
            w = target_vol / sigma_annual[t]
            w = np.clip(w, min_w, max_w)
            weights[t] = w
        else:
            weights[t] = np.nan

    # Strategy returns in OOS
    oos_idx = np.where(oos_mask)[0]
    if len(oos_idx) == 0:
        return None

    # Use simple returns for strategy P&L
    simple_returns = np.exp(returns) - 1  # convert log to simple

    strat_returns = np.full(T, np.nan)
    weight_changes = np.full(T, np.nan)

    for i, t in enumerate(oos_idx):
        if np.isfinite(weights[t]) and np.isfinite(simple_returns[t]):
            strat_returns[t] = weights[t] * simple_returns[t]
            if i > 0 and np.isfinite(weights[oos_idx[i - 1]]):
                weight_changes[t] = abs(weights[t] - weights[oos_idx[i - 1]])

    # Apply transaction costs
    tx_cost_decimal = tx_cost_bp / 10000
    strat_returns_net = np.copy(strat_returns)
    for t in oos_idx:
        if np.isfinite(weight_changes[t]):
            strat_returns_net[t] -= weight_changes[t] * tx_cost_decimal

    # Performance metrics
    oos_strat = strat_returns[oos_idx]
    oos_strat_net = strat_returns_net[oos_idx]
    oos_weights = weights[oos_idx]
    oos_wchanges = weight_changes[oos_idx]

    valid_mask = np.isfinite(oos_strat)
    oos_strat = oos_strat[valid_mask]
    oos_strat_net = oos_strat_net[valid_mask]
    oos_weights_valid = oos_weights[valid_mask]
    oos_wchanges_valid = oos_wchanges[valid_mask]

    if len(oos_strat) < 10:
        return None

    # Sharpe
    ann_ret = np.mean(oos_strat) * 252
    ann_vol = np.std(oos_strat) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 1e-8 else 0.0

    ann_ret_net = np.mean(oos_strat_net) * 252
    ann_vol_net = np.std(oos_strat_net) * np.sqrt(252)
    sharpe_net = ann_ret_net / ann_vol_net if ann_vol_net > 1e-8 else 0.0

    # Total return
    cumret = np.cumprod(1 + oos_strat) - 1
    total_return = float(cumret[-1])

    cumret_net = np.cumprod(1 + oos_strat_net) - 1
    total_return_net = float(cumret_net[-1])

    # Max drawdown
    cum_wealth = np.cumprod(1 + oos_strat)
    peak = np.maximum.accumulate(cum_wealth)
    drawdowns = (cum_wealth - peak) / peak
    max_dd = float(np.min(drawdowns))

    cum_wealth_net = np.cumprod(1 + oos_strat_net)
    peak_net = np.maximum.accumulate(cum_wealth_net)
    drawdowns_net = (cum_wealth_net - peak_net) / peak_net
    max_dd_net = float(np.min(drawdowns_net))

    # Calmar
    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-8 else 0.0
    calmar_net = ann_ret_net / abs(max_dd_net) if abs(max_dd_net) > 1e-8 else 0.0

    # Sortino
    downside = oos_strat[oos_strat < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 1e-8 else 0.0

    # Weight stats
    valid_wc = oos_wchanges_valid[np.isfinite(oos_wchanges_valid)]
    n_sig_changes = int(np.sum(valid_wc > 0.05))  # >5pp changes
    weight_stability = float(np.std(valid_wc)) if len(valid_wc) > 0 else np.nan
    avg_weight = float(np.nanmean(oos_weights_valid))
    weight_std = float(np.nanstd(oos_weights_valid))

    # QLIKE in OOS
    oos_rv = (returns[oos_idx] ** 2)[valid_mask]
    oos_sigma2 = sigma2_daily[oos_idx][valid_mask]
    qlike_mask = (oos_rv > 0) & (oos_sigma2 > 0) & np.isfinite(oos_rv) & np.isfinite(oos_sigma2)
    if qlike_mask.sum() > 0:
        qlike_val = float(np.mean(oos_rv[qlike_mask] / oos_sigma2[qlike_mask] -
                                   np.log(oos_rv[qlike_mask] / oos_sigma2[qlike_mask]) - 1))
    else:
        qlike_val = np.nan

    return {
        "n_obs_oos": int(len(oos_strat)),
        "annualized_return": float(ann_ret),
        "annualized_vol": float(ann_vol),
        "sharpe_ratio": float(sharpe),
        "net_sharpe_ratio": float(sharpe_net),
        "total_return": total_return,
        "total_return_net": total_return_net,
        "max_drawdown": max_dd,
        "max_drawdown_net": max_dd_net,
        "calmar_ratio": float(calmar),
        "calmar_ratio_net": float(calmar_net),
        "sortino_ratio": float(sortino),
        "avg_weight": avg_weight,
        "weight_std": weight_std,
        "n_significant_weight_changes": n_sig_changes,
        "weight_change_std": weight_stability,
        "qlike_oos": qlike_val,
        "cumulative_returns": cum_wealth.tolist(),
    }


def run_12vix_strategy(returns_simple, vix_daily, oos_mask, max_w=1.5, min_w=0.0):
    """Run 12/VIX strategy as benchmark."""
    T = len(returns_simple)
    weights = np.full(T, np.nan)

    for t in range(T):
        if np.isfinite(vix_daily[t]) and vix_daily[t] > 1e-8:
            w = 12.0 / vix_daily[t]
            w = np.clip(w, min_w, max_w)
            weights[t] = w

    oos_idx = np.where(oos_mask)[0]
    if len(oos_idx) == 0:
        return None

    strat_returns = np.full(T, np.nan)
    weight_changes = np.full(T, np.nan)

    for i, t in enumerate(oos_idx):
        if np.isfinite(weights[t]) and np.isfinite(returns_simple[t]):
            strat_returns[t] = weights[t] * returns_simple[t]
            if i > 0 and np.isfinite(weights[oos_idx[i - 1]]):
                weight_changes[t] = abs(weights[t] - weights[oos_idx[i - 1]])

    # TX cost
    tx_cost_decimal = TX_COST_BP / 10000
    strat_returns_net = np.copy(strat_returns)
    for t in oos_idx:
        if np.isfinite(weight_changes[t]):
            strat_returns_net[t] -= weight_changes[t] * tx_cost_decimal

    oos_strat = strat_returns[oos_idx]
    oos_strat_net = strat_returns_net[oos_idx]
    oos_weights = weights[oos_idx]
    oos_wchanges = weight_changes[oos_idx]

    valid_mask = np.isfinite(oos_strat)
    oos_strat = oos_strat[valid_mask]
    oos_strat_net = oos_strat_net[valid_mask]
    oos_weights_valid = oos_weights[valid_mask]
    oos_wchanges_valid = oos_wchanges[valid_mask]

    if len(oos_strat) < 10:
        return None

    ann_ret = np.mean(oos_strat) * 252
    ann_vol = np.std(oos_strat) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 1e-8 else 0.0
    ann_ret_net = np.mean(oos_strat_net) * 252
    ann_vol_net = np.std(oos_strat_net) * np.sqrt(252)
    sharpe_net = ann_ret_net / ann_vol_net if ann_vol_net > 1e-8 else 0.0

    cumret = np.cumprod(1 + oos_strat)
    total_return = float(cumret[-1] - 1)
    cum_wealth = cumret
    peak = np.maximum.accumulate(cum_wealth)
    drawdowns = (cum_wealth - peak) / peak
    max_dd = float(np.min(drawdowns))
    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-8 else 0.0

    cumret_net = np.cumprod(1 + oos_strat_net)
    total_return_net = float(cumret_net[-1] - 1)
    cum_wealth_net = cumret_net
    peak_net = np.maximum.accumulate(cum_wealth_net)
    drawdowns_net = (cum_wealth_net - peak_net) / peak_net
    max_dd_net = float(np.min(drawdowns_net))
    calmar_net = ann_ret_net / abs(max_dd_net) if abs(max_dd_net) > 1e-8 else 0.0

    downside = oos_strat[oos_strat < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 1e-8 else 0.0

    valid_wc = oos_wchanges_valid[np.isfinite(oos_wchanges_valid)]
    n_sig_changes = int(np.sum(valid_wc > 0.05))
    weight_stability = float(np.std(valid_wc)) if len(valid_wc) > 0 else np.nan

    return {
        "n_obs_oos": int(len(oos_strat)),
        "annualized_return": float(ann_ret),
        "annualized_vol": float(ann_vol),
        "sharpe_ratio": float(sharpe),
        "net_sharpe_ratio": float(sharpe_net),
        "total_return": total_return,
        "total_return_net": total_return_net,
        "max_drawdown": max_dd,
        "max_drawdown_net": max_dd_net,
        "calmar_ratio": float(calmar),
        "calmar_ratio_net": float(calmar_net),
        "sortino_ratio": float(sortino),
        "avg_weight": float(np.nanmean(oos_weights_valid)),
        "weight_std": float(np.nanstd(oos_weights_valid)),
        "n_significant_weight_changes": n_sig_changes,
        "weight_change_std": weight_stability,
        "qlike_oos": None,  # no sigma2 for 12/VIX
        "cumulative_returns": cum_wealth.tolist(),
    }


# ============================================================================
# 50/50 SPY/GLD Portfolio VT
# ============================================================================
def run_portfolio_vt(spy_returns, gld_returns, sigma2_spy, sigma2_gld,
                     oos_mask, target_vol=0.10, max_w=1.5, min_w=0.0, tx_cost_bp=2):
    """
    Run 50/50 SPY/GLD VT.
    Portfolio sigma = sqrt(0.5^2 * spy_sigma2 + 0.5^2 * gld_sigma2 + 2*0.5*0.5*cov_sg)
    For simplicity, use rolling 60-day correlation for cov estimation.
    """
    T = len(spy_returns)

    # Rolling correlation (60-day)
    corr_window = 60
    rolling_corr = np.full(T, 0.0)
    for t in range(corr_window, T):
        c = np.corrcoef(spy_returns[t - corr_window:t], gld_returns[t - corr_window:t])[0, 1]
        rolling_corr[t] = c if np.isfinite(c) else 0.0

    # Portfolio variance
    port_sigma2 = np.full(T, np.nan)
    for t in range(T):
        if np.isfinite(sigma2_spy[t]) and np.isfinite(sigma2_gld[t]):
            s_spy = np.sqrt(sigma2_spy[t])
            s_gld = np.sqrt(sigma2_gld[t])
            port_var = (0.5 ** 2 * sigma2_spy[t] +
                        0.5 ** 2 * sigma2_gld[t] +
                        2 * 0.5 * 0.5 * rolling_corr[t] * s_spy * s_gld)
            port_sigma2[t] = max(port_var, 1e-12)

    port_sigma_annual = np.sqrt(252 * port_sigma2)

    # VT weights
    weights = np.full(T, np.nan)
    for t in range(T):
        if np.isfinite(port_sigma_annual[t]) and port_sigma_annual[t] > 1e-8:
            w = target_vol / port_sigma_annual[t]
            w = np.clip(w, min_w, max_w)
            weights[t] = w

    # Portfolio simple returns (50/50)
    spy_simple = np.exp(spy_returns) - 1
    gld_simple = np.exp(gld_returns) - 1
    port_returns = 0.5 * spy_simple + 0.5 * gld_simple

    oos_idx = np.where(oos_mask)[0]
    if len(oos_idx) == 0:
        return None

    strat_returns = np.full(T, np.nan)
    weight_changes = np.full(T, np.nan)

    for i, t in enumerate(oos_idx):
        if np.isfinite(weights[t]) and np.isfinite(port_returns[t]):
            strat_returns[t] = weights[t] * port_returns[t]
            if i > 0 and np.isfinite(weights[oos_idx[i - 1]]):
                weight_changes[t] = abs(weights[t] - weights[oos_idx[i - 1]])

    tx_cost_decimal = tx_cost_bp / 10000
    strat_returns_net = np.copy(strat_returns)
    for t in oos_idx:
        if np.isfinite(weight_changes[t]):
            strat_returns_net[t] -= weight_changes[t] * tx_cost_decimal

    oos_strat = strat_returns[oos_idx]
    oos_strat_net = strat_returns_net[oos_idx]
    oos_weights = weights[oos_idx]
    oos_wchanges = weight_changes[oos_idx]

    valid_mask = np.isfinite(oos_strat)
    oos_strat = oos_strat[valid_mask]
    oos_strat_net = oos_strat_net[valid_mask]
    oos_weights_valid = oos_weights[valid_mask]
    oos_wchanges_valid = oos_wchanges[valid_mask]

    if len(oos_strat) < 10:
        return None

    ann_ret = np.mean(oos_strat) * 252
    ann_vol = np.std(oos_strat) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 1e-8 else 0.0
    ann_ret_net = np.mean(oos_strat_net) * 252
    ann_vol_net = np.std(oos_strat_net) * np.sqrt(252)
    sharpe_net = ann_ret_net / ann_vol_net if ann_vol_net > 1e-8 else 0.0

    cum_wealth = np.cumprod(1 + oos_strat)
    total_return = float(cum_wealth[-1] - 1)
    peak = np.maximum.accumulate(cum_wealth)
    drawdowns = (cum_wealth - peak) / peak
    max_dd = float(np.min(drawdowns))
    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-8 else 0.0

    cum_wealth_net = np.cumprod(1 + oos_strat_net)
    total_return_net = float(cum_wealth_net[-1] - 1)
    peak_net = np.maximum.accumulate(cum_wealth_net)
    drawdowns_net = (cum_wealth_net - peak_net) / peak_net
    max_dd_net = float(np.min(drawdowns_net))
    calmar_net = ann_ret_net / abs(max_dd_net) if abs(max_dd_net) > 1e-8 else 0.0

    downside = oos_strat[oos_strat < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 1e-8 else 0.0

    valid_wc = oos_wchanges_valid[np.isfinite(oos_wchanges_valid)]
    n_sig_changes = int(np.sum(valid_wc > 0.05))
    weight_stability = float(np.std(valid_wc)) if len(valid_wc) > 0 else np.nan

    return {
        "n_obs_oos": int(len(oos_strat)),
        "annualized_return": float(ann_ret),
        "annualized_vol": float(ann_vol),
        "sharpe_ratio": float(sharpe),
        "net_sharpe_ratio": float(sharpe_net),
        "total_return": total_return,
        "total_return_net": total_return_net,
        "max_drawdown": max_dd,
        "max_drawdown_net": max_dd_net,
        "calmar_ratio": float(calmar),
        "calmar_ratio_net": float(calmar_net),
        "sortino_ratio": float(sortino),
        "avg_weight": float(np.nanmean(oos_weights_valid)),
        "weight_std": float(np.nanstd(oos_weights_valid)),
        "n_significant_weight_changes": n_sig_changes,
        "weight_change_std": weight_stability,
        "cumulative_returns": cum_wealth.tolist(),
    }


# ============================================================================
# Buy & Hold Benchmark
# ============================================================================
def buy_and_hold(returns_log, oos_mask):
    """Simple buy & hold benchmark."""
    simple = np.exp(returns_log) - 1
    oos_idx = np.where(oos_mask)[0]
    oos_ret = simple[oos_idx]
    valid = oos_ret[np.isfinite(oos_ret)]
    if len(valid) < 10:
        return None

    ann_ret = np.mean(valid) * 252
    ann_vol = np.std(valid) * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 1e-8 else 0.0

    cum_wealth = np.cumprod(1 + valid)
    total_return = float(cum_wealth[-1] - 1)
    peak = np.maximum.accumulate(cum_wealth)
    drawdowns = (cum_wealth - peak) / peak
    max_dd = float(np.min(drawdowns))
    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-8 else 0.0

    return {
        "n_obs_oos": int(len(valid)),
        "annualized_return": float(ann_ret),
        "annualized_vol": float(ann_vol),
        "sharpe_ratio": float(sharpe),
        "total_return": total_return,
        "max_drawdown": max_dd,
        "calmar_ratio": float(calmar),
    }


# ============================================================================
# Diebold-Mariano Test
# ============================================================================
def dm_test(e1, e2, h=1):
    """Diebold-Mariano test. H0: equal predictive ability."""
    d = e1 - e2
    n = len(d)
    d_bar = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    var_d = gamma_0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        var_d += 2 * (1 - k / h) * gamma_k
    se = np.sqrt(var_d / n)
    if se < 1e-12:
        return 0.0, 1.0
    dm_stat = d_bar / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)


# ============================================================================
# Main Experiment
# ============================================================================
def main():
    P(f"\n{'='*70}")
    P(f"  K635: Fixed vs Rolling GARCH Parameters — VT Strategy Performance")
    P(f"{'='*70}")

    # ── Download data ──
    P("\n  [1] Downloading data...")
    spy_data = download_data("SPY")
    gld_data = download_data("GLD")
    vix_series = download_vix()

    # Align to common dates
    common_idx = spy_data.index.intersection(gld_data.index)
    common_idx = common_idx[common_idx >= ANALYSIS_START]
    common_idx = common_idx[common_idx <= OOS_END]

    spy_data = spy_data.loc[common_idx]
    gld_data = gld_data.loc[common_idx]

    spy_returns = spy_data["return"].values
    gld_returns = gld_data["return"].values
    dates = common_idx

    # OOS mask
    oos_mask = np.array([(d >= pd.Timestamp(OOS_START)) & (d <= pd.Timestamp(OOS_END)) for d in dates])
    oos_start_idx = np.where(oos_mask)[0][0] if oos_mask.any() else None

    P(f"  Total observations: {len(spy_returns)}")
    P(f"  Period: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")
    P(f"  OOS observations: {oos_mask.sum()}")
    P(f"  OOS period: {OOS_START} to {OOS_END}")

    # Descriptive stats
    desc = {
        "SPY": {
            "n_obs": int(len(spy_returns)),
            "mean_return": float(np.mean(spy_returns)),
            "std_return": float(np.std(spy_returns)),
            "skewness": float(stats.skew(spy_returns)),
            "kurtosis": float(stats.kurtosis(spy_returns)),
        },
        "GLD": {
            "n_obs": int(len(gld_returns)),
            "mean_return": float(np.mean(gld_returns)),
            "std_return": float(np.std(gld_returns)),
            "skewness": float(stats.skew(gld_returns)),
            "kurtosis": float(stats.kurtosis(gld_returns)),
        },
    }

    # ── [2] Estimate fixed parameters (pre-OOS sample: 2006-2022) ──
    P("\n  [2] Estimating FIXED GJR-GARCH parameters (pre-OOS: 2006-2022)...")
    pre_oos_returns_spy = spy_returns[:oos_start_idx]
    pre_oos_returns_gld = gld_returns[:oos_start_idx]

    P(f"    SPY pre-OOS sample: {len(pre_oos_returns_spy)} obs")
    fixed_params_spy = fit_gjr_garch(pre_oos_returns_spy)
    if fixed_params_spy:
        P(f"    SPY fixed params: omega={fixed_params_spy['omega']:.8f}, "
          f"alpha={fixed_params_spy['alpha']:.4f}, gamma={fixed_params_spy['gamma']:.4f}, "
          f"beta={fixed_params_spy['beta']:.4f}, persistence={fixed_params_spy['persistence']:.4f}")
    else:
        P("    WARNING: SPY fixed estimation FAILED")

    P(f"    GLD pre-OOS sample: {len(pre_oos_returns_gld)} obs")
    fixed_params_gld = fit_gjr_garch(pre_oos_returns_gld)
    if fixed_params_gld:
        P(f"    GLD fixed params: omega={fixed_params_gld['omega']:.8f}, "
          f"alpha={fixed_params_gld['alpha']:.4f}, gamma={fixed_params_gld['gamma']:.4f}, "
          f"beta={fixed_params_gld['beta']:.4f}, persistence={fixed_params_gld['persistence']:.4f}")
    else:
        P("    WARNING: GLD fixed estimation FAILED")

    # ── [3] Generate all sigma forecasts ──
    P("\n  [3] Generating sigma forecasts for all methods...")

    # 3a. Rolling GJR-GARCH
    P("    Rolling GJR-GARCH (SPY)...")
    sigma2_rolling_spy, spy_param_records = generate_rolling_sigma(
        spy_returns, oos_start_idx, refit_step=REFIT_STEP, rolling_window=ROLLING_WINDOW
    )
    P(f"    Rolling SPY: {len(spy_param_records)} parameter sets estimated")

    P("    Rolling GJR-GARCH (GLD)...")
    sigma2_rolling_gld, gld_param_records = generate_rolling_sigma(
        gld_returns, oos_start_idx, refit_step=REFIT_STEP, rolling_window=ROLLING_WINDOW
    )
    P(f"    Rolling GLD: {len(gld_param_records)} parameter sets estimated")

    # 3b. Fixed GJR-GARCH
    P("    Fixed GJR-GARCH (SPY)...")
    sigma2_fixed_spy = generate_fixed_sigma(spy_returns, fixed_params_spy, ROLLING_WINDOW)

    P("    Fixed GJR-GARCH (GLD)...")
    sigma2_fixed_gld = generate_fixed_sigma(gld_returns, fixed_params_gld, ROLLING_WINDOW)

    # 3c. EWMA
    P("    EWMA (SPY)...")
    sigma2_ewma_spy = generate_ewma_sigma(spy_returns, lam=EWMA_LAMBDA)
    P("    EWMA (GLD)...")
    sigma2_ewma_gld = generate_ewma_sigma(gld_returns, lam=EWMA_LAMBDA)

    # 3d. VIX-implied (for 12/VIX strategy)
    vix_aligned = vix_series.reindex(dates, method="ffill").values

    # ── [4] Run VT strategies (SPY only) ──
    P("\n  [4] Running VT strategies (SPY only)...")

    spy_simple = np.exp(spy_returns) - 1

    results_spy = {}

    P("    4a. Rolling VT (SPY)...")
    results_spy["rolling_vt"] = run_vt_strategy(
        spy_returns, sigma2_rolling_spy, oos_mask, TARGET_VOL, MAX_WEIGHT, MIN_WEIGHT, TX_COST_BP
    )

    P("    4b. Fixed VT (SPY)...")
    results_spy["fixed_vt"] = run_vt_strategy(
        spy_returns, sigma2_fixed_spy, oos_mask, TARGET_VOL, MAX_WEIGHT, MIN_WEIGHT, TX_COST_BP
    )

    P("    4c. EWMA VT (SPY)...")
    results_spy["ewma_vt"] = run_vt_strategy(
        spy_returns, sigma2_ewma_spy, oos_mask, TARGET_VOL, MAX_WEIGHT, MIN_WEIGHT, TX_COST_BP
    )

    P("    4d. 12/VIX (SPY)...")
    results_spy["12vix"] = run_12vix_strategy(
        spy_simple, vix_aligned, oos_mask, MAX_WEIGHT, MIN_WEIGHT
    )

    P("    4e. Buy & Hold (SPY)...")
    results_spy["buy_hold"] = buy_and_hold(spy_returns, oos_mask)

    # Print SPY summary
    P(f"\n  {'='*60}")
    P(f"  SPY VT Strategy Comparison (OOS: {OOS_START} to {OOS_END})")
    P(f"  {'='*60}")
    P(f"  {'Strategy':<18} {'Sharpe':>8} {'NetSh':>8} {'Return':>8} {'MaxDD':>8} {'Calmar':>8} {'Sortino':>8} {'#Chg':>6} {'QLIKE':>8}")
    P(f"  {'-'*88}")
    for name, r in results_spy.items():
        if r is None:
            P(f"  {name:<18} FAILED")
            continue
        sharpe = r.get('sharpe_ratio', 0)
        net_sh = r.get('net_sharpe_ratio', sharpe)
        ret = r.get('total_return', 0)
        mdd = r.get('max_drawdown', 0)
        calmar = r.get('calmar_ratio', 0)
        sortino = r.get('sortino_ratio', 0)
        nchg = r.get('n_significant_weight_changes', '-')
        ql = r.get('qlike_oos', None)
        ql_str = f"{ql:.4f}" if ql is not None else "N/A"
        P(f"  {name:<18} {sharpe:>8.3f} {net_sh:>8.3f} {ret:>7.1%} {mdd:>7.1%} {calmar:>8.3f} {sortino:>8.3f} {str(nchg):>6} {ql_str:>8}")

    # ── [5] Run 50/50 SPY/GLD VT strategies ──
    P(f"\n  [5] Running 50/50 SPY/GLD VT strategies...")

    results_portfolio = {}

    P("    5a. Rolling VT (50/50)...")
    results_portfolio["rolling_vt_5050"] = run_portfolio_vt(
        spy_returns, gld_returns, sigma2_rolling_spy, sigma2_rolling_gld,
        oos_mask, TARGET_VOL, MAX_WEIGHT, MIN_WEIGHT, TX_COST_BP
    )

    P("    5b. Fixed VT (50/50)...")
    results_portfolio["fixed_vt_5050"] = run_portfolio_vt(
        spy_returns, gld_returns, sigma2_fixed_spy, sigma2_fixed_gld,
        oos_mask, TARGET_VOL, MAX_WEIGHT, MIN_WEIGHT, TX_COST_BP
    )

    P("    5c. EWMA VT (50/50)...")
    results_portfolio["ewma_vt_5050"] = run_portfolio_vt(
        spy_returns, gld_returns, sigma2_ewma_spy, sigma2_ewma_gld,
        oos_mask, TARGET_VOL, MAX_WEIGHT, MIN_WEIGHT, TX_COST_BP
    )

    P("    5d. Buy & Hold 50/50...")
    port_simple = 0.5 * spy_simple + 0.5 * (np.exp(gld_returns) - 1)
    port_log = np.log(1 + port_simple)
    results_portfolio["buy_hold_5050"] = buy_and_hold(port_log, oos_mask)

    # Print portfolio summary
    P(f"\n  {'='*60}")
    P(f"  50/50 SPY/GLD VT Strategy Comparison (OOS: {OOS_START} to {OOS_END})")
    P(f"  {'='*60}")
    P(f"  {'Strategy':<22} {'Sharpe':>8} {'NetSh':>8} {'Return':>8} {'MaxDD':>8} {'Calmar':>8} {'Sortino':>8}")
    P(f"  {'-'*76}")
    for name, r in results_portfolio.items():
        if r is None:
            P(f"  {name:<22} FAILED")
            continue
        sharpe = r.get('sharpe_ratio', 0)
        net_sh = r.get('net_sharpe_ratio', sharpe)
        ret = r.get('total_return', 0)
        mdd = r.get('max_drawdown', 0)
        calmar = r.get('calmar_ratio', 0)
        sortino = r.get('sortino_ratio', 0)
        P(f"  {name:<22} {sharpe:>8.3f} {net_sh:>8.3f} {ret:>7.1%} {mdd:>7.1%} {calmar:>8.3f} {sortino:>8.3f}")

    # ── [6] DM tests ──
    P(f"\n  [6] Diebold-Mariano Tests (strategy return loss = -squared return)...")

    dm_results = {}

    # Compare rolling vs fixed (strategy returns)
    if results_spy["rolling_vt"] and results_spy["fixed_vt"]:
        oos_idx = np.where(oos_mask)[0]
        # Use squared return differences as loss
        roll_cumret = np.array(results_spy["rolling_vt"]["cumulative_returns"])
        fix_cumret = np.array(results_spy["fixed_vt"]["cumulative_returns"])

        # DM test on QLIKE (forecast quality)
        oos_rv = spy_returns[oos_idx] ** 2
        oos_sigma2_roll = sigma2_rolling_spy[oos_idx]
        oos_sigma2_fix = sigma2_fixed_spy[oos_idx]
        valid = (np.isfinite(oos_rv) & np.isfinite(oos_sigma2_roll) &
                 np.isfinite(oos_sigma2_fix) & (oos_rv > 0) &
                 (oos_sigma2_roll > 0) & (oos_sigma2_fix > 0))
        if valid.sum() > 20:
            rv_v = oos_rv[valid]
            s2_roll = oos_sigma2_roll[valid]
            s2_fix = oos_sigma2_fix[valid]
            ql_roll = rv_v / s2_roll - np.log(rv_v / s2_roll) - 1
            ql_fix = rv_v / s2_fix - np.log(rv_v / s2_fix) - 1
            dm_stat, dm_pval = dm_test(ql_roll, ql_fix, h=1)
            dm_results["qlike_rolling_vs_fixed"] = {
                "dm_statistic": dm_stat,
                "p_value": dm_pval,
                "interpretation": "positive = rolling worse (higher QLIKE)" if dm_stat > 0 else "negative = fixed worse",
            }
            P(f"    QLIKE DM (Rolling vs Fixed): stat={dm_stat:.3f}, p={dm_pval:.4f}")
            if dm_stat > 0:
                P(f"    → Rolling has HIGHER QLIKE (worse prediction) — fixed is better forecaster")
            else:
                P(f"    → Rolling has LOWER QLIKE (better prediction)")

        # DM test on strategy squared returns (economic loss)
        roll_rets = np.array(results_spy["rolling_vt"]["cumulative_returns"])
        fix_rets = np.array(results_spy["fixed_vt"]["cumulative_returns"])
        # Compute daily returns from cumulative
        n_min = min(len(roll_rets), len(fix_rets))
        roll_daily = np.diff(roll_rets[:n_min]) / roll_rets[:n_min - 1]
        fix_daily = np.diff(fix_rets[:n_min]) / fix_rets[:n_min - 1]
        if len(roll_daily) > 20:
            # Negative squared return as loss (lower = worse)
            roll_loss = -(roll_daily ** 2)
            fix_loss = -(fix_daily ** 2)
            dm_stat2, dm_pval2 = dm_test(roll_loss, fix_loss, h=1)
            dm_results["econ_rolling_vs_fixed"] = {
                "dm_statistic": float(dm_stat2),
                "p_value": float(dm_pval2),
                "interpretation": "Tests if strategy return variance differs significantly",
            }
            P(f"    Economic DM (Rolling vs Fixed): stat={dm_stat2:.3f}, p={dm_pval2:.4f}")

    # ── [7] QLIKE comparison ──
    P(f"\n  [7] QLIKE Comparison (forecast quality in OOS)...")

    qlike_results = {}
    oos_idx = np.where(oos_mask)[0]
    oos_rv = spy_returns[oos_idx] ** 2

    for name, sigma2 in [("rolling", sigma2_rolling_spy), ("fixed", sigma2_fixed_spy),
                          ("ewma", sigma2_ewma_spy)]:
        oos_s2 = sigma2[oos_idx]
        valid = (np.isfinite(oos_rv) & np.isfinite(oos_s2) & (oos_rv > 0) & (oos_s2 > 0))
        if valid.sum() > 0:
            rv_v = oos_rv[valid]
            s2_v = oos_s2[valid]
            ql = float(np.mean(rv_v / s2_v - np.log(rv_v / s2_v) - 1))
            qlike_results[name] = ql
            P(f"    {name:>10}: QLIKE = {ql:.6f}")

    # ── [8] Weight evolution comparison ──
    P(f"\n  [8] Weight evolution analysis...")

    weight_analysis = {}
    for name, sigma2 in [("rolling", sigma2_rolling_spy), ("fixed", sigma2_fixed_spy),
                          ("ewma", sigma2_ewma_spy)]:
        oos_s2 = sigma2[oos_idx]
        sigma_ann = np.sqrt(252 * oos_s2)
        weights = np.clip(TARGET_VOL / sigma_ann, MIN_WEIGHT, MAX_WEIGHT)
        valid = np.isfinite(weights)
        if valid.sum() > 0:
            w_valid = weights[valid]
            weight_analysis[name] = {
                "mean_weight": float(np.mean(w_valid)),
                "std_weight": float(np.std(w_valid)),
                "min_weight": float(np.min(w_valid)),
                "max_weight": float(np.max(w_valid)),
                "pct_at_cap": float(np.mean(w_valid >= MAX_WEIGHT - 0.01) * 100),
                "avg_daily_change": float(np.mean(np.abs(np.diff(w_valid)))),
            }
            P(f"    {name:>10}: mean={np.mean(w_valid):.3f}, std={np.std(w_valid):.3f}, "
              f"at_cap={np.mean(w_valid >= MAX_WEIGHT - 0.01) * 100:.1f}%")

    # ── [9] Plot ──
    P(f"\n  [9] Generating plots...")

    fig, axes = plt.subplots(2, 2, figsize=(16, 10))
    fig.suptitle(f"K635: Fixed vs Rolling GARCH — VT Strategy (OOS: {OOS_START} to {OOS_END})",
                 fontsize=14, fontweight='bold')

    oos_dates = dates[oos_mask]

    # Plot 1: SPY cumulative returns
    ax = axes[0, 0]
    for name, label, color in [("rolling_vt", "Rolling VT", "blue"),
                                ("fixed_vt", "Fixed VT", "red"),
                                ("ewma_vt", "EWMA VT", "green"),
                                ("12vix", "12/VIX", "orange")]:
        r = results_spy.get(name)
        if r and "cumulative_returns" in r:
            cr = np.array(r["cumulative_returns"])
            ax.plot(oos_dates[:len(cr)], cr, label=label, color=color, linewidth=1.5)

    bh = results_spy.get("buy_hold")
    if bh:
        bh_simple = np.exp(spy_returns[oos_mask]) - 1
        bh_cum = np.cumprod(1 + bh_simple)
        ax.plot(oos_dates[:len(bh_cum)], bh_cum, label="Buy&Hold", color="gray",
                linewidth=1, linestyle="--")

    ax.set_title("SPY: Cumulative Wealth")
    ax.legend(fontsize=8)
    ax.set_ylabel("Wealth ($1 initial)")
    ax.grid(True, alpha=0.3)

    # Plot 2: SPY weights over time
    ax = axes[0, 1]
    for name, sigma2, color in [("Rolling", sigma2_rolling_spy, "blue"),
                                 ("Fixed", sigma2_fixed_spy, "red"),
                                 ("EWMA", sigma2_ewma_spy, "green")]:
        oos_s2 = sigma2[oos_mask]
        sigma_ann = np.sqrt(252 * oos_s2)
        weights = np.clip(TARGET_VOL / sigma_ann, MIN_WEIGHT, MAX_WEIGHT)
        ax.plot(oos_dates, weights, label=name, color=color, alpha=0.7, linewidth=1)

    ax.set_title("SPY: VT Weights (10% target)")
    ax.legend(fontsize=8)
    ax.set_ylabel("Weight")
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5)
    ax.axhline(y=MAX_WEIGHT, color='gray', linestyle=':', alpha=0.3, label=f'Cap ({MAX_WEIGHT})')
    ax.grid(True, alpha=0.3)

    # Plot 3: Performance bar chart
    ax = axes[1, 0]
    strat_names = []
    sharpes = []
    net_sharpes = []
    for name in ["rolling_vt", "fixed_vt", "ewma_vt", "12vix", "buy_hold"]:
        r = results_spy.get(name)
        if r:
            strat_names.append(name.replace("_", "\n"))
            sharpes.append(r.get('sharpe_ratio', 0))
            net_sharpes.append(r.get('net_sharpe_ratio', r.get('sharpe_ratio', 0)))

    x = np.arange(len(strat_names))
    width = 0.35
    ax.bar(x - width / 2, sharpes, width, label='Sharpe', color='steelblue')
    ax.bar(x + width / 2, net_sharpes, width, label='Net Sharpe', color='coral')
    ax.set_xticks(x)
    ax.set_xticklabels(strat_names, fontsize=8)
    ax.set_title("SPY: Sharpe Ratios")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3, axis='y')

    # Plot 4: Portfolio 50/50 cumulative returns
    ax = axes[1, 1]
    for name, label, color in [("rolling_vt_5050", "Rolling VT", "blue"),
                                ("fixed_vt_5050", "Fixed VT", "red"),
                                ("ewma_vt_5050", "EWMA VT", "green")]:
        r = results_portfolio.get(name)
        if r and "cumulative_returns" in r:
            cr = np.array(r["cumulative_returns"])
            ax.plot(oos_dates[:len(cr)], cr, label=label, color=color, linewidth=1.5)

    bh5050 = results_portfolio.get("buy_hold_5050")
    if bh5050:
        bh_port = 0.5 * (np.exp(spy_returns[oos_mask]) - 1) + 0.5 * (np.exp(gld_returns[oos_mask]) - 1)
        bh_cum = np.cumprod(1 + bh_port)
        ax.plot(oos_dates[:len(bh_cum)], bh_cum, label="B&H 50/50", color="gray",
                linewidth=1, linestyle="--")

    ax.set_title("50/50 SPY/GLD: Cumulative Wealth")
    ax.legend(fontsize=8)
    ax.set_ylabel("Wealth ($1 initial)")
    ax.grid(True, alpha=0.3)

    plt.tight_layout()
    plot_path = Path(MAIN_REPO) / "experiments" / "k635_fixed_vs_rolling_vt.png"
    plt.savefig(plot_path, dpi=150, bbox_inches='tight')
    plt.close()
    P(f"    Plot saved: {plot_path}")

    # ── [10] Key Analysis ──
    P(f"\n  {'='*60}")
    P(f"  KEY ANALYSIS: Does QLIKE improvement → strategy improvement?")
    P(f"  {'='*60}")

    if results_spy["rolling_vt"] and results_spy["fixed_vt"]:
        roll_sh = results_spy["rolling_vt"]["sharpe_ratio"]
        fix_sh = results_spy["fixed_vt"]["sharpe_ratio"]
        roll_ql = qlike_results.get("rolling", np.nan)
        fix_ql = qlike_results.get("fixed", np.nan)

        qlike_winner = "fixed" if fix_ql < roll_ql else "rolling"
        sharpe_winner = "fixed" if fix_sh > roll_sh else "rolling"

        P(f"    QLIKE winner: {qlike_winner} (rolling={roll_ql:.6f}, fixed={fix_ql:.6f})")
        P(f"    Sharpe winner: {sharpe_winner} (rolling={roll_sh:.3f}, fixed={fix_sh:.3f})")

        if qlike_winner != sharpe_winner:
            P(f"\n    *** PREDICTION ≠ APPLICATION CONFIRMED (7th time!) ***")
            P(f"    Better QLIKE (forecast) does NOT translate to better Sharpe (economics)")
            conclusion = "prediction_ne_application_confirmed"
        else:
            P(f"\n    Prediction and application ALIGNED — {qlike_winner} wins both")
            conclusion = "prediction_application_aligned"
    else:
        conclusion = "comparison_failed"

    # ── Assemble results ──
    elapsed = time.time() - START_TIME

    # Remove cumulative_returns from JSON (too large)
    for d in [results_spy, results_portfolio]:
        for k, v in d.items():
            if v and "cumulative_returns" in v:
                del v["cumulative_returns"]

    output = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Fixed vs Rolling GARCH Parameters — Impact on VT Strategy Performance",
        "description": (
            "Tests whether the QLIKE improvement from fixed (pre-OOS) GARCH parameters "
            "(found in K634) translates to better VT strategy economic outcomes. "
            "Compares Rolling VT, Fixed VT, EWMA VT, 12/VIX, and Buy&Hold."
        ),
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "data_source": "yfinance",
            "analysis_start": ANALYSIS_START,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "rolling_window": ROLLING_WINDOW,
            "refit_step": REFIT_STEP,
            "target_vol": TARGET_VOL,
            "max_weight": MAX_WEIGHT,
            "min_weight": MIN_WEIGHT,
            "ewma_lambda": EWMA_LAMBDA,
            "tx_cost_bp": TX_COST_BP,
        },
        "references": [
            "K634: Fixed params QLIKE < rolling QLIKE for SPY",
            "Hillebrand (2005) 'Neglecting parameter changes in GARCH models' JoE",
            "Fleming, Kirby & Ostdiek (2001) 'Economic value of volatility timing' JoFE",
            "Hansen & Lunde (2005) 'A forecast comparison of volatility models' JoAE",
        ],
        "prior_knowledge": [
            "K634 (fixed params better QLIKE)",
            "K35/K36 (GJR baseline)",
            "K459/K474/K476 (prediction ≠ application)",
        ],
        "descriptive_stats": desc,
        "fixed_params": {
            "SPY": fixed_params_spy,
            "GLD": fixed_params_gld,
        },
        "spy_strategies": results_spy,
        "portfolio_5050_strategies": results_portfolio,
        "qlike_comparison": qlike_results,
        "weight_analysis": weight_analysis,
        "dm_tests": dm_results,
        "conclusion": conclusion,
        "key_finding": (
            f"QLIKE winner: {qlike_winner if 'qlike_winner' in dir() else 'N/A'}, "
            f"Sharpe winner: {sharpe_winner if 'sharpe_winner' in dir() else 'N/A'}. "
            f"Conclusion: {conclusion}"
        ),
        "runtime_seconds": round(elapsed, 1),
        "plot_file": "experiments/k635_fixed_vs_rolling_vt.png",
    }

    # Save results
    results_path = Path(MAIN_REPO) / "experiments" / "k635_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    P(f"\n  Results saved: {results_path}")
    P(f"  Runtime: {elapsed:.1f}s")

    return output


if __name__ == "__main__":
    results = main()
