#!/usr/bin/env python3
"""K540: HAR-VIX Ensemble VT Strategy
=============================================

Research question: Can we COMBINE HAR's prediction power with VIX's
forward-looking nature in a smarter way than simple 50/50 averaging?

Motivation (from K530 & K533):
  - K530: HAR-ABS is the best predictor (DM=-15.45 vs GJR-GARCH)
  - K533: HAR-ABS is the WORST VT strategy (Sharpe 1.123 vs 12/VIX 1.748)
  - K533: HAR-VIX narrows the gap (only -0.059 Sharpe vs 12/VIX)
  - K533: Weight correlation HAR-ABS vs 12/VIX = 0.506 — different info!

Key insight: HAR and VIX capture different information (backward vs forward).
Their DISAGREEMENT may be a useful signal.

Strategies tested:
  1. 12/VIX VT (benchmark)
  2. Disagreement Filter: agree → VIX; disagree → conservative (min weight)
  3. HAR Reality Check: base=12/VIX, but reduce when HAR sees high vol that
     VIX ignores (HAR_vol/VIX_vol > threshold → scale down)
  4. Regime-Conditional: low VIX → pure VIX; high VIX → blend; medium → VIX
  5. Dynamic Blend: α·VIX + (1-α)·HAR, α optimized per VIX regime (IS)
  6. Disagreement Momentum: track recent agree/disagree streak; longer
     disagreement → more conservative weighting

Cross-OOS: 5 periods (Harvey t>3.0 for significance)
Data: SPY + GLD + VIX from yfinance, 2005-present

References:
  - Corsi (2009, JFE): HAR-RV model
  - Moreira & Muir (2017, JoF): Volatility-managed portfolios
  - K530: HAR-ABS DM=-15.45 vs GJR-GARCH
  - K533: prediction ≠ application (HAR best predictor, worst VT)
  - K440/K470/K488/K503/K504/K524: 12/VIX irreducible kernel

Data source: yfinance (SPY, GLD, ^VIX)
Author: [Proposed: User, Executed: Claude]

Usage:
    uv run python experiments/k540_har_ensemble_vt.py
"""
from __future__ import annotations

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

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ============================================================
#  Constants & Configuration
# ============================================================
TARGET_VOL = 0.12  # 12% annualized target volatility
TX_COST = 0.001    # 0.1% one-way transaction cost
HAR_WINDOW = 500   # HAR estimation window (rolling OLS)
ANNUALIZE = np.sqrt(252)

# 5 cross-OOS periods for robust evaluation
OOS_PERIODS = {
    "OOS1_2015_2016": ("2015-01-01", "2016-12-31"),
    "OOS2_2017_2018": ("2017-01-01", "2018-12-31"),
    "OOS3_2019_2020": ("2019-01-01", "2020-12-31"),
    "OOS4_2021_2022": ("2021-01-01", "2022-12-31"),
    "OOS5_2023_2024": ("2023-01-01", "2024-12-31"),
}

# ============================================================
#  Utility Functions
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def sharpe_ratio(returns: np.ndarray) -> float:
    """Annualized Sharpe ratio."""
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * ANNUALIZE)


def max_drawdown(returns: np.ndarray) -> float:
    """Maximum drawdown from cumulative returns."""
    cum = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return float(np.min(dd))


def cagr(returns: np.ndarray) -> float:
    """Compound annual growth rate."""
    n_years = len(returns) / 252
    if n_years <= 0:
        return 0.0
    total = np.prod(1 + returns)
    if total <= 0:
        return -1.0
    return float(total ** (1 / n_years) - 1)


def calmar_ratio(returns: np.ndarray) -> float:
    """Calmar ratio = CAGR / |MDD|."""
    mdd = max_drawdown(returns)
    c = cagr(returns)
    if abs(mdd) < 1e-10:
        return 0.0
    return float(c / abs(mdd))


def sortino_ratio(returns: np.ndarray) -> float:
    """Annualized Sortino ratio."""
    downside = returns[returns < 0]
    if len(downside) < 2:
        return 0.0
    downside_std = np.std(downside)
    if downside_std == 0:
        return 0.0
    return float(np.mean(returns) / downside_std * ANNUALIZE)


def turnover(weights: np.ndarray) -> float:
    """Average daily turnover = mean(|delta w|)."""
    dw = np.diff(weights)
    return float(np.mean(np.abs(dw)))


def net_sharpe_after_tx(returns: np.ndarray, weights: np.ndarray,
                        tx_cost: float) -> float:
    """Sharpe after deducting transaction costs."""
    dw = np.abs(np.diff(weights))
    tx_drag = dw * tx_cost
    net_ret = returns[1:] - tx_drag
    return sharpe_ratio(net_ret)


def dm_test_returns(returns1: np.ndarray, returns2: np.ndarray) -> tuple:
    """DM-style test on return differences.
    H0: E[r1 - r2] = 0.  Positive t → model1 better.
    """
    d = returns1 - returns2
    T = len(d)
    if T < 10:
        return (0.0, 1.0)
    d_bar = np.mean(d)
    # Newey-West with lag=int(T^(1/3)) for robustness
    lag = max(1, int(T ** (1/3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for j in range(1, lag + 1):
        gamma_j = np.mean((d[j:] - d_bar) * (d[:-j] - d_bar))
        gamma_sum += 2 * (1 - j / (lag + 1)) * gamma_j
    nw_var = gamma0 + gamma_sum
    if nw_var <= 0:
        nw_var = gamma0
    se = np.sqrt(nw_var / T)
    if se == 0:
        return (0.0, 1.0)
    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=T - 1))
    return (float(t_stat), float(p_val))


# ============================================================
#  HAR Feature Construction (from K530/K533)
# ============================================================

def build_har_features(log_returns: np.ndarray,
                       vix_daily: np.ndarray = None) -> dict:
    """Build HAR features: RV1, RV5, RV22 (absolute return proxies)."""
    abs_r = np.abs(log_returns)
    rv1 = abs_r.copy()
    rv5 = pd.Series(abs_r).rolling(5).mean().values
    rv22 = pd.Series(abs_r).rolling(22).mean().values

    result = {"rv1": rv1, "rv5": rv5, "rv22": rv22}

    if vix_daily is not None:
        result["vix_daily"] = vix_daily / 100.0 / ANNUALIZE

    return result


def ols_fit(X: np.ndarray, y: np.ndarray):
    """OLS with intercept. Returns [intercept, beta1, beta2, ...]."""
    n = len(y)
    X_aug = np.column_stack([np.ones(n), X])
    try:
        beta = np.linalg.lstsq(X_aug, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        beta = np.zeros(X_aug.shape[1])
    return beta


def ols_predict(X_new: np.ndarray, beta: np.ndarray) -> float:
    """Predict with OLS coefficients."""
    x_aug = np.concatenate([[1.0], X_new])
    return max(float(np.dot(x_aug, beta)), 1e-10)


# ============================================================
#  Weight Computation Functions
# ============================================================

def compute_vix_weights(vix_close: np.ndarray) -> np.ndarray:
    """Standard 12/VIX position sizing (forward-looking benchmark)."""
    weights = np.minimum(1.0, 12.0 / vix_close)
    return np.clip(weights, 0.0, 1.0)


def compute_har_abs_weights(log_returns: np.ndarray,
                            window: int = 500) -> np.ndarray:
    """HAR-ABS VT: rolling OLS on |r| with RV1, RV5, RV22."""
    n = len(log_returns)
    features = build_har_features(log_returns)
    rv1, rv5, rv22 = features["rv1"], features["rv5"], features["rv22"]

    weights = np.full(n, 1.0)

    for t in range(window, n):
        start = t - window
        train_X, train_y = [], []
        for i in range(start, t):
            if np.isnan(rv5[i]) or np.isnan(rv22[i]):
                continue
            if i + 1 >= n:
                continue
            train_X.append([rv1[i], rv5[i], rv22[i]])
            train_y.append(np.abs(log_returns[i + 1]))

        if len(train_X) < 50:
            continue

        beta = ols_fit(np.array(train_X), np.array(train_y))
        x_new = np.array([rv1[t], rv5[t], rv22[t]])
        if np.any(np.isnan(x_new)):
            continue
        pred_abs = ols_predict(x_new, beta)
        sigma_daily = pred_abs * np.sqrt(np.pi / 2)
        sigma_annual = sigma_daily * ANNUALIZE

        if sigma_annual > 0.01:
            weights[t] = min(1.0, TARGET_VOL / sigma_annual)

    return np.clip(weights, 0.0, 1.0)


def compute_har_abs_forecast(log_returns: np.ndarray,
                              window: int = 500) -> np.ndarray:
    """Return HAR-ABS annualized vol forecast (not weights).

    Needed for ensemble strategies that compare HAR vs VIX forecasts.
    """
    n = len(log_returns)
    features = build_har_features(log_returns)
    rv1, rv5, rv22 = features["rv1"], features["rv5"], features["rv22"]

    forecasts = np.full(n, np.nan)

    for t in range(window, n):
        start = t - window
        train_X, train_y = [], []
        for i in range(start, t):
            if np.isnan(rv5[i]) or np.isnan(rv22[i]):
                continue
            if i + 1 >= n:
                continue
            train_X.append([rv1[i], rv5[i], rv22[i]])
            train_y.append(np.abs(log_returns[i + 1]))

        if len(train_X) < 50:
            continue

        beta = ols_fit(np.array(train_X), np.array(train_y))
        x_new = np.array([rv1[t], rv5[t], rv22[t]])
        if np.any(np.isnan(x_new)):
            continue
        pred_abs = ols_predict(x_new, beta)
        sigma_daily = pred_abs * np.sqrt(np.pi / 2)
        sigma_annual = sigma_daily * ANNUALIZE
        forecasts[t] = sigma_annual

    return forecasts


# ============================================================
#  Ensemble Strategy Definitions
# ============================================================

def strategy_disagreement_filter(w_vix: np.ndarray, w_har: np.ndarray,
                                  threshold: float = 0.15) -> np.ndarray:
    """Strategy 1: Disagreement Filter.

    When HAR and VIX AGREE (weight diff < threshold): use VIX weight.
    When they DISAGREE: use the more conservative (lower) weight.
    Hypothesis: disagreement = uncertainty = be cautious.
    """
    n = len(w_vix)
    weights = np.copy(w_vix)
    for t in range(n):
        diff = abs(w_vix[t] - w_har[t])
        if diff > threshold:
            # Disagreement: be conservative
            weights[t] = min(w_vix[t], w_har[t])
    return np.clip(weights, 0.0, 1.0)


def strategy_har_reality_check(w_vix: np.ndarray,
                                har_vol_forecast: np.ndarray,
                                vix_close: np.ndarray,
                                ratio_threshold: float = 1.5) -> np.ndarray:
    """Strategy 2: HAR as VIX Reality Check.

    Base: 12/VIX weights.
    When HAR predicts vol >> VIX implied (HAR_vol/VIX_implied > threshold):
      reduce weight proportionally → VIX is complacent, HAR sees risk.
    When HAR < VIX: keep VIX weight (VIX already cautious).
    """
    n = len(w_vix)
    weights = np.copy(w_vix)
    vix_vol = vix_close / 100.0  # VIX is already annualized %

    for t in range(n):
        if np.isnan(har_vol_forecast[t]) or vix_vol[t] < 0.01:
            continue
        ratio = har_vol_forecast[t] / vix_vol[t]
        if ratio > ratio_threshold:
            # HAR sees more risk than VIX implies — reduce position
            # Scale down proportionally: if ratio=2.0 & threshold=1.5,
            # reduction = 1 - (2.0-1.5)/2.0 = 0.75 (keep 75%)
            scale = max(0.3, 1.0 - (ratio - ratio_threshold) / ratio)
            weights[t] = w_vix[t] * scale

    return np.clip(weights, 0.0, 1.0)


def strategy_regime_conditional(w_vix: np.ndarray, w_har: np.ndarray,
                                 vix_close: np.ndarray,
                                 low_vix: float = 15.0,
                                 high_vix: float = 25.0,
                                 blend_alpha: float = 0.5) -> np.ndarray:
    """Strategy 3: Regime-Conditional Blend.

    Low VIX (<15):   pure 12/VIX (VIX is best in calm markets)
    High VIX (>25):  blend α·VIX + (1-α)·HAR (HAR captures dynamics better)
    Medium VIX:      pure 12/VIX
    """
    n = len(w_vix)
    weights = np.copy(w_vix)

    for t in range(n):
        if vix_close[t] > high_vix:
            weights[t] = blend_alpha * w_vix[t] + (1 - blend_alpha) * w_har[t]

    return np.clip(weights, 0.0, 1.0)


def strategy_dynamic_blend(w_vix: np.ndarray, w_har: np.ndarray,
                            vix_close: np.ndarray,
                            alpha_low: float = 0.9,
                            alpha_mid: float = 0.8,
                            alpha_high: float = 0.5) -> np.ndarray:
    """Strategy 4: Dynamic Blend with regime-dependent α.

    w = α_regime · VIX_weight + (1-α_regime) · HAR_weight

    Low VIX (<15):   α=0.9 (mostly VIX — VIX dominates in calm)
    Medium VIX:      α=0.8
    High VIX (>25):  α=0.5 (equal blend — HAR adds value in stress)
    """
    n = len(w_vix)
    weights = np.zeros(n)

    for t in range(n):
        if vix_close[t] < 15:
            alpha = alpha_low
        elif vix_close[t] > 25:
            alpha = alpha_high
        else:
            alpha = alpha_mid
        weights[t] = alpha * w_vix[t] + (1 - alpha) * w_har[t]

    return np.clip(weights, 0.0, 1.0)


def strategy_disagreement_momentum(w_vix: np.ndarray, w_har: np.ndarray,
                                     lookback: int = 10,
                                     disagree_threshold: float = 0.15,
                                     max_reduction: float = 0.3) -> np.ndarray:
    """Strategy 5: Disagreement Momentum.

    Track how often HAR and VIX have disagreed in recent days.
    Higher disagreement frequency → more conservative.

    disagreement_score = fraction of last `lookback` days where
                          |w_vix - w_har| > threshold

    Adjustment: w = w_vix * (1 - max_reduction * disagreement_score)
    """
    n = len(w_vix)
    weights = np.copy(w_vix)

    for t in range(lookback, n):
        diffs = np.abs(w_vix[t-lookback:t] - w_har[t-lookback:t])
        disagree_score = np.mean(diffs > disagree_threshold)
        reduction = max_reduction * disagree_score
        weights[t] = w_vix[t] * (1.0 - reduction)

    return np.clip(weights, 0.0, 1.0)


# ============================================================
#  Backtester
# ============================================================

def backtest_strategy(spy_returns: np.ndarray, gld_returns: np.ndarray,
                      weights: np.ndarray, name: str,
                      spy_allocation: float = 0.5) -> dict:
    """Backtest a VT strategy on 50/50 SPY+GLD portfolio."""
    gld_alloc = 1.0 - spy_allocation
    risky_return = spy_allocation * spy_returns + gld_alloc * gld_returns
    strat_return = weights * risky_return + (1 - weights) * 0.0  # cash=0

    sr = sharpe_ratio(strat_return)
    mdd = max_drawdown(strat_return)
    cal = calmar_ratio(strat_return)
    sort = sortino_ratio(strat_return)
    to = turnover(weights)
    net_sr = net_sharpe_after_tx(strat_return, weights, TX_COST)
    c = cagr(strat_return)
    ann_vol = float(np.std(strat_return) * ANNUALIZE)
    avg_weight = float(np.mean(weights))

    return {
        "name": name,
        "sharpe": round(sr, 4),
        "net_sharpe": round(net_sr, 4),
        "cagr": round(c, 4),
        "ann_vol": round(ann_vol, 4),
        "mdd": round(mdd, 4),
        "calmar": round(cal, 4),
        "sortino": round(sort, 4),
        "turnover": round(to, 6),
        "avg_weight": round(avg_weight, 4),
        "n_obs": len(strat_return),
        "returns": strat_return,
        "weights": weights,
    }


# ============================================================
#  Bootstrap Confidence Interval for Sharpe Difference
# ============================================================

def bootstrap_sharpe_diff(ret1: np.ndarray, ret2: np.ndarray,
                           n_boot: int = 10000,
                           ci: float = 0.95) -> dict:
    """Bootstrap CI for Sharpe(ret1) - Sharpe(ret2)."""
    T = len(ret1)
    diffs = np.zeros(n_boot)
    rng = np.random.default_rng(42)

    for b in range(n_boot):
        idx = rng.choice(T, size=T, replace=True)
        s1 = sharpe_ratio(ret1[idx])
        s2 = sharpe_ratio(ret2[idx])
        diffs[b] = s1 - s2

    alpha = (1 - ci) / 2
    lo = np.percentile(diffs, 100 * alpha)
    hi = np.percentile(diffs, 100 * (1 - alpha))
    mean_diff = np.mean(diffs)
    p_positive = np.mean(diffs > 0)

    return {
        "mean_diff": round(float(mean_diff), 4),
        "ci_lo": round(float(lo), 4),
        "ci_hi": round(float(hi), 4),
        "p_positive": round(float(p_positive), 4),
    }


# ============================================================
#  Main Experiment
# ============================================================

def main():
    t_start = time.time()

    print_section("K540: HAR-VIX Ensemble VT Strategy")
    print("  Q: Can HAR complement VIX rather than replace it?")
    print("  Core idea: HAR/VIX disagreement = uncertainty signal")
    print("  Benchmark: 12/VIX (irreducible kernel, confirmed 7x)")

    # --------------------------------------------------------
    # 1. DATA COLLECTION
    # --------------------------------------------------------
    print_section("1. Data Collection", "-")

    spy = yf.download("SPY", start="2005-01-01", progress=False)
    gld = yf.download("GLD", start="2005-01-01", progress=False)
    vix = yf.download("^VIX", start="2005-01-01", progress=False)

    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    # Align
    common_idx = spy.index.intersection(gld.index).intersection(vix.index)
    spy = spy.loc[common_idx]
    gld = gld.loc[common_idx]
    vix = vix.loc[common_idx]

    print(f"  SPY: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} obs)")
    print(f"  GLD: {gld.index[0].date()} to {gld.index[-1].date()} ({len(gld)} obs)")
    print(f"  VIX: {vix.index[0].date()} to {vix.index[-1].date()} ({len(vix)} obs)")

    # Returns
    spy_ret = np.log(spy["Close"] / spy["Close"].shift(1)).values.flatten()
    gld_ret = np.log(gld["Close"] / gld["Close"].shift(1)).values.flatten()
    vix_close = vix["Close"].values.flatten()
    dates = spy.index

    spy_ret[0] = 0.0
    gld_ret[0] = 0.0

    n = len(spy_ret)
    print(f"  Total observations: {n}")

    # --------------------------------------------------------
    # 2. DESCRIPTIVE STATISTICS
    # --------------------------------------------------------
    print_section("2. Descriptive Statistics", "-")

    for name, ret in [("SPY", spy_ret), ("GLD", gld_ret)]:
        valid = ret[~np.isnan(ret)]
        print(f"  {name}: mean={np.mean(valid):.6f}, std={np.std(valid):.6f}, "
              f"skew={stats.skew(valid):.4f}, kurt={stats.kurtosis(valid):.4f}")

    print(f"  VIX: mean={np.nanmean(vix_close):.2f}, "
          f"median={np.nanmedian(vix_close):.2f}, "
          f"min={np.nanmin(vix_close):.2f}, max={np.nanmax(vix_close):.2f}")

    # VIX regime distribution
    low_pct = np.mean(vix_close < 15) * 100
    mid_pct = np.mean((vix_close >= 15) & (vix_close <= 25)) * 100
    high_pct = np.mean(vix_close > 25) * 100
    print(f"  VIX regimes: Low(<15)={low_pct:.1f}%, "
          f"Mid(15-25)={mid_pct:.1f}%, High(>25)={high_pct:.1f}%")

    # --------------------------------------------------------
    # 3. COMPUTE BASE WEIGHTS + HAR FORECASTS
    # --------------------------------------------------------
    print_section("3. Computing Base Weights & HAR Forecasts", "-")

    print("  Computing 12/VIX weights...")
    w_vix = compute_vix_weights(vix_close)

    print("  Computing HAR-ABS weights (rolling OLS, window=500)...")
    w_har = compute_har_abs_weights(spy_ret, window=HAR_WINDOW)

    print("  Computing HAR-ABS vol forecasts (for reality check strategy)...")
    har_forecast = compute_har_abs_forecast(spy_ret, window=HAR_WINDOW)

    # Weight correlation analysis
    valid_mask = ~np.isnan(har_forecast) & (har_forecast > 0)
    corr_weights = np.corrcoef(w_vix[valid_mask], w_har[valid_mask])[0, 1]
    print(f"  Weight correlation (VIX vs HAR): {corr_weights:.4f}")

    # Disagreement analysis
    diffs = np.abs(w_vix[valid_mask] - w_har[valid_mask])
    print(f"  Weight disagreement stats:")
    print(f"    Mean |diff|: {np.mean(diffs):.4f}")
    print(f"    Median |diff|: {np.median(diffs):.4f}")
    print(f"    Max |diff|: {np.max(diffs):.4f}")
    print(f"    Pct diff > 0.10: {np.mean(diffs > 0.10)*100:.1f}%")
    print(f"    Pct diff > 0.15: {np.mean(diffs > 0.15)*100:.1f}%")
    print(f"    Pct diff > 0.20: {np.mean(diffs > 0.20)*100:.1f}%")

    # HAR vs VIX vol comparison
    vix_vol_implied = vix_close[valid_mask] / 100.0
    har_vol_valid = har_forecast[valid_mask]
    ratio_har_vix = har_vol_valid / vix_vol_implied
    print(f"\n  HAR/VIX vol ratio stats:")
    print(f"    Mean: {np.mean(ratio_har_vix):.4f}")
    print(f"    Median: {np.median(ratio_har_vix):.4f}")
    print(f"    Pct ratio > 1.5: {np.mean(ratio_har_vix > 1.5)*100:.1f}%")
    print(f"    Pct ratio > 2.0: {np.mean(ratio_har_vix > 2.0)*100:.1f}%")

    # --------------------------------------------------------
    # 4. COMPUTE ENSEMBLE STRATEGY WEIGHTS
    # --------------------------------------------------------
    print_section("4. Computing Ensemble Strategy Weights", "-")

    strategies_config = {
        "12/VIX": {"weights": w_vix, "description": "Benchmark"},
        "DisagreeFilter": {
            "weights": strategy_disagreement_filter(w_vix, w_har, threshold=0.15),
            "description": "Disagree→conservative",
        },
        "HARReality": {
            "weights": strategy_har_reality_check(
                w_vix, har_forecast, vix_close, ratio_threshold=1.5),
            "description": "HAR checks VIX complacency",
        },
        "RegimeCond": {
            "weights": strategy_regime_conditional(
                w_vix, w_har, vix_close,
                low_vix=15.0, high_vix=25.0, blend_alpha=0.5),
            "description": "VIX regime blend",
        },
        "DynBlend": {
            "weights": strategy_dynamic_blend(
                w_vix, w_har, vix_close,
                alpha_low=0.9, alpha_mid=0.8, alpha_high=0.5),
            "description": "Dynamic α blend",
        },
        "DisagreeMom": {
            "weights": strategy_disagreement_momentum(
                w_vix, w_har, lookback=10,
                disagree_threshold=0.15, max_reduction=0.3),
            "description": "Disagreement momentum",
        },
    }

    # Report weight stats for each strategy
    for sname, sconfig in strategies_config.items():
        w = sconfig["weights"]
        valid_w = w[~np.isnan(w)]
        print(f"  {sname:16s}: mean={np.mean(valid_w):.4f}, "
              f"std={np.std(valid_w):.4f}, "
              f"turnover={turnover(w):.6f}")

    # --------------------------------------------------------
    # 5. CROSS-OOS EVALUATION (5 periods)
    # --------------------------------------------------------
    print_section("5. Cross-OOS Evaluation (5 periods)", "-")

    all_results = {}
    summary_sharpe = {sname: [] for sname in strategies_config}
    summary_net_sharpe = {sname: [] for sname in strategies_config}
    summary_mdd = {sname: [] for sname in strategies_config}

    for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
        print(f"\n  --- {period_name}: {oos_start} to {oos_end} ---")

        mask = (dates >= oos_start) & (dates <= oos_end)
        if mask.sum() == 0:
            print(f"    SKIP: no data in this period")
            continue

        oos_idx = np.where(mask)[0]
        oos_spy = spy_ret[oos_idx]
        oos_gld = gld_ret[oos_idx]

        # B&H benchmark
        bh = backtest_strategy(oos_spy, oos_gld, np.ones(len(oos_idx)),
                               "B&H 50/50", spy_allocation=0.5)

        # All strategies
        period_strats = [bh]
        for sname, sconfig in strategies_config.items():
            result = backtest_strategy(
                oos_spy, oos_gld, sconfig["weights"][oos_idx],
                sname, spy_allocation=0.5)
            period_strats.append(result)
            summary_sharpe[sname].append(result["sharpe"])
            summary_net_sharpe[sname].append(result["net_sharpe"])
            summary_mdd[sname].append(result["mdd"])

        # Print table
        print(f"\n  {'Strategy':16s} {'Sharpe':>8s} {'NetSR':>8s} {'CAGR':>8s} "
              f"{'MDD':>8s} {'Calmar':>8s} {'TO':>10s} {'AvgW':>6s}")
        print(f"  {'-'*78}")
        for s in period_strats:
            print(f"  {s['name']:16s} {s['sharpe']:8.4f} {s['net_sharpe']:8.4f} "
                  f"{s['cagr']:8.4f} {s['mdd']:8.4f} {s['calmar']:8.4f} "
                  f"{s['turnover']:10.6f} {s['avg_weight']:6.4f}")

        # DM tests: each ensemble vs 12/VIX
        print(f"\n  DM tests vs 12/VIX (Newey-West SE):")
        vix_strat = [s for s in period_strats if s["name"] == "12/VIX"][0]
        for s in period_strats:
            if s["name"] in ("B&H 50/50", "12/VIX"):
                continue
            t_stat, p_val = dm_test_returns(s["returns"], vix_strat["returns"])
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else \
                  "*" if p_val < 0.1 else "NS"
            print(f"    {s['name']:16s}: t={t_stat:+.4f}, p={p_val:.4f} [{sig}]")

        # Store results
        period_results = {}
        for s in period_strats:
            period_results[s["name"]] = {
                k: v for k, v in s.items() if k not in ("returns", "weights")
            }

        # Add DM tests
        dm_tests = {}
        for s in period_strats:
            if s["name"] in ("B&H 50/50", "12/VIX"):
                continue
            t_stat, p_val = dm_test_returns(s["returns"], vix_strat["returns"])
            dm_tests[f"{s['name']}_vs_VIX"] = {
                "t_stat": round(t_stat, 4),
                "p_value": round(p_val, 4),
                "significant_at_5pct": p_val < 0.05,
            }
        period_results["dm_tests"] = dm_tests
        all_results[period_name] = period_results

    # --------------------------------------------------------
    # 6. CROSS-OOS SUMMARY
    # --------------------------------------------------------
    print_section("6. Cross-OOS Summary (Mean across 5 periods)", "-")

    print(f"\n  {'Strategy':16s} {'Mean SR':>8s} {'Std SR':>8s} "
          f"{'Mean NetSR':>10s} {'Mean MDD':>9s} {'Win vs VIX':>11s}")
    print(f"  {'-'*68}")

    vix_sharpes = summary_sharpe["12/VIX"]
    for sname in strategies_config:
        sharpes = summary_sharpe[sname]
        net_sharpes = summary_net_sharpe[sname]
        mdds = summary_mdd[sname]
        wins = sum(1 for s, v in zip(sharpes, vix_sharpes) if s > v)
        print(f"  {sname:16s} {np.mean(sharpes):8.4f} {np.std(sharpes):8.4f} "
              f"{np.mean(net_sharpes):10.4f} {np.mean(mdds):9.4f} "
              f"{wins}/{len(sharpes)}")

    # Harvey t-test: mean Sharpe difference across periods
    print(f"\n  Harvey (2016) significance (paired t-test across 5 periods):")
    for sname in strategies_config:
        if sname == "12/VIX":
            continue
        sharpe_diffs = [s - v for s, v in zip(summary_sharpe[sname], vix_sharpes)]
        mean_diff = np.mean(sharpe_diffs)
        if len(sharpe_diffs) > 1:
            se = np.std(sharpe_diffs, ddof=1) / np.sqrt(len(sharpe_diffs))
            if se > 0:
                t_stat = mean_diff / se
                p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(sharpe_diffs)-1))
            else:
                t_stat, p_val = 0.0, 1.0
        else:
            t_stat, p_val = 0.0, 1.0
        sig = "PASS" if abs(t_stat) > 3.0 else "FAIL"
        print(f"    {sname:16s}: mean_diff={mean_diff:+.4f}, "
              f"t={t_stat:+.4f}, p={p_val:.4f} [{sig}]")

    # --------------------------------------------------------
    # 7. SENSITIVITY ANALYSIS
    # --------------------------------------------------------
    print_section("7. Sensitivity Analysis", "-")

    # 7a. Disagreement Filter threshold sensitivity
    print("\n  7a. Disagreement Filter — threshold sensitivity:")
    print(f"    {'Threshold':>10s} {'Mean SR':>8s} {'Mean NetSR':>10s}")
    disagree_sensitivity = {}
    for thresh in [0.05, 0.10, 0.15, 0.20, 0.25, 0.30]:
        w_test = strategy_disagreement_filter(w_vix, w_har, threshold=thresh)
        sharpes_test = []
        for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
            mask = (dates >= oos_start) & (dates <= oos_end)
            if mask.sum() == 0:
                continue
            oos_idx = np.where(mask)[0]
            res = backtest_strategy(spy_ret[oos_idx], gld_ret[oos_idx],
                                    w_test[oos_idx], f"DF_{thresh}",
                                    spy_allocation=0.5)
            sharpes_test.append(res["sharpe"])
        mean_sr = np.mean(sharpes_test)
        print(f"    {thresh:10.2f} {mean_sr:8.4f}")
        disagree_sensitivity[str(thresh)] = round(mean_sr, 4)

    # 7b. HAR Reality Check — ratio threshold sensitivity
    print("\n  7b. HAR Reality Check — ratio threshold sensitivity:")
    print(f"    {'Ratio Thr':>10s} {'Mean SR':>8s}")
    reality_sensitivity = {}
    for ratio_thr in [1.0, 1.2, 1.5, 1.8, 2.0, 2.5]:
        w_test = strategy_har_reality_check(
            w_vix, har_forecast, vix_close, ratio_threshold=ratio_thr)
        sharpes_test = []
        for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
            mask = (dates >= oos_start) & (dates <= oos_end)
            if mask.sum() == 0:
                continue
            oos_idx = np.where(mask)[0]
            res = backtest_strategy(spy_ret[oos_idx], gld_ret[oos_idx],
                                    w_test[oos_idx], f"RC_{ratio_thr}",
                                    spy_allocation=0.5)
            sharpes_test.append(res["sharpe"])
        mean_sr = np.mean(sharpes_test)
        print(f"    {ratio_thr:10.2f} {mean_sr:8.4f}")
        reality_sensitivity[str(ratio_thr)] = round(mean_sr, 4)

    # 7c. Dynamic Blend — α_high sensitivity
    print("\n  7c. Dynamic Blend — α_high (VIX>25 blend) sensitivity:")
    print(f"    {'alpha_high':>10s} {'Mean SR':>8s}")
    dynblend_sensitivity = {}
    for a_high in [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
        w_test = strategy_dynamic_blend(w_vix, w_har, vix_close,
                                         alpha_low=0.9, alpha_mid=0.8,
                                         alpha_high=a_high)
        sharpes_test = []
        for period_name, (oos_start, oos_end) in OOS_PERIODS.items():
            mask = (dates >= oos_start) & (dates <= oos_end)
            if mask.sum() == 0:
                continue
            oos_idx = np.where(mask)[0]
            res = backtest_strategy(spy_ret[oos_idx], gld_ret[oos_idx],
                                    w_test[oos_idx], f"DB_{a_high}",
                                    spy_allocation=0.5)
            sharpes_test.append(res["sharpe"])
        mean_sr = np.mean(sharpes_test)
        print(f"    {a_high:10.2f} {mean_sr:8.4f}")
        dynblend_sensitivity[str(a_high)] = round(mean_sr, 4)

    # --------------------------------------------------------
    # 8. BOOTSTRAP CONFIDENCE INTERVALS (full sample 2015-2024)
    # --------------------------------------------------------
    print_section("8. Bootstrap CIs (full sample 2015-2024, 10k reps)", "-")

    full_mask = (dates >= "2015-01-01") & (dates <= "2024-12-31")
    full_idx = np.where(full_mask)[0]
    full_spy = spy_ret[full_idx]
    full_gld = gld_ret[full_idx]

    # Get VIX full-sample returns
    vix_full = backtest_strategy(full_spy, full_gld, w_vix[full_idx],
                                  "12/VIX", spy_allocation=0.5)

    bootstrap_results = {}
    for sname, sconfig in strategies_config.items():
        if sname == "12/VIX":
            continue
        s_full = backtest_strategy(full_spy, full_gld,
                                    sconfig["weights"][full_idx],
                                    sname, spy_allocation=0.5)
        boot = bootstrap_sharpe_diff(s_full["returns"], vix_full["returns"])
        bootstrap_results[sname] = boot
        print(f"  {sname:16s} vs 12/VIX: diff={boot['mean_diff']:+.4f} "
              f"[{boot['ci_lo']:+.4f}, {boot['ci_hi']:+.4f}] "
              f"P(>0)={boot['p_positive']:.3f}")

    # --------------------------------------------------------
    # 9. REGIME-SPECIFIC ANALYSIS
    # --------------------------------------------------------
    print_section("9. Regime-Specific Performance (full sample)", "-")

    regimes = {
        "Low VIX (<15)": vix_close[full_idx] < 15,
        "Mid VIX (15-25)": (vix_close[full_idx] >= 15) & (vix_close[full_idx] <= 25),
        "High VIX (>25)": vix_close[full_idx] > 25,
    }

    regime_results = {}
    for regime_name, regime_mask in regimes.items():
        if regime_mask.sum() < 30:
            print(f"  {regime_name}: too few obs ({regime_mask.sum()})")
            continue

        print(f"\n  --- {regime_name} (n={regime_mask.sum()}) ---")
        print(f"  {'Strategy':16s} {'Sharpe':>8s} {'MDD':>8s} {'AvgW':>6s}")
        print(f"  {'-'*40}")

        regime_data = {}
        for sname, sconfig in strategies_config.items():
            r_spy = full_spy[regime_mask]
            r_gld = full_gld[regime_mask]
            r_w = sconfig["weights"][full_idx][regime_mask]
            r_res = backtest_strategy(r_spy, r_gld, r_w, sname,
                                       spy_allocation=0.5)
            print(f"  {sname:16s} {r_res['sharpe']:8.4f} "
                  f"{r_res['mdd']:8.4f} {r_res['avg_weight']:6.4f}")
            regime_data[sname] = {
                "sharpe": r_res["sharpe"],
                "mdd": r_res["mdd"],
                "avg_weight": r_res["avg_weight"],
            }
        regime_results[regime_name] = regime_data

    # --------------------------------------------------------
    # 10. CONCLUSIONS
    # --------------------------------------------------------
    print_section("10. Conclusions", "-")

    # Find best ensemble strategy
    mean_sharpes = {sname: np.mean(summary_sharpe[sname])
                    for sname in strategies_config}
    best_name = max(mean_sharpes, key=mean_sharpes.get)
    best_sr = mean_sharpes[best_name]
    vix_sr = mean_sharpes["12/VIX"]
    delta = best_sr - vix_sr

    print(f"\n  Best ensemble: {best_name} (mean Sharpe={best_sr:.4f})")
    print(f"  Benchmark:     12/VIX (mean Sharpe={vix_sr:.4f})")
    print(f"  Delta:         {delta:+.4f}")

    # Check Harvey t>3.0
    sharpe_diffs = [s - v for s, v in zip(
        summary_sharpe[best_name], vix_sharpes)]
    if len(sharpe_diffs) > 1:
        se = np.std(sharpe_diffs, ddof=1) / np.sqrt(len(sharpe_diffs))
        if se > 0:
            t_stat = np.mean(sharpe_diffs) / se
        else:
            t_stat = 0.0
    else:
        t_stat = 0.0

    if abs(t_stat) > 3.0:
        print(f"  Harvey t={t_stat:.4f} > 3.0: SIGNIFICANT")
    elif delta > 0:
        print(f"  Harvey t={t_stat:.4f} < 3.0: improvement exists but NOT significant")
    else:
        print(f"  Harvey t={t_stat:.4f}: no improvement over 12/VIX")

    # Final verdict
    any_beats_vix = any(mean_sharpes[s] > vix_sr for s in strategies_config
                        if s != "12/VIX")
    if any_beats_vix and abs(t_stat) > 3.0:
        verdict = "POSITIVE: ensemble significantly beats 12/VIX"
    elif any_beats_vix:
        verdict = "MARGINAL: ensemble improves but not significantly"
    else:
        verdict = "NULL: 12/VIX remains irreducible — 8th confirmation"

    print(f"\n  VERDICT: {verdict}")

    # --------------------------------------------------------
    # 11. SAVE RESULTS
    # --------------------------------------------------------
    elapsed = time.time() - t_start

    results = {
        "experiment_id": "K540",
        "title": "HAR-VIX Ensemble VT Strategy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(elapsed, 1),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "data_period": f"{spy.index[0].date()} to {spy.index[-1].date()}",
        "n_observations": n,
        "methodology": {
            "har_window": HAR_WINDOW,
            "target_vol": TARGET_VOL,
            "tx_cost": TX_COST,
            "oos_periods": OOS_PERIODS,
            "strategies": {
                sname: sconfig["description"]
                for sname, sconfig in strategies_config.items()
            },
        },
        "cross_oos_results": all_results,
        "cross_oos_summary": {
            sname: {
                "mean_sharpe": round(np.mean(summary_sharpe[sname]), 4),
                "std_sharpe": round(np.std(summary_sharpe[sname]), 4),
                "mean_net_sharpe": round(np.mean(summary_net_sharpe[sname]), 4),
                "mean_mdd": round(np.mean(summary_mdd[sname]), 4),
                "per_period_sharpe": [round(s, 4) for s in summary_sharpe[sname]],
            }
            for sname in strategies_config
        },
        "sensitivity_analysis": {
            "disagreement_threshold": disagree_sensitivity,
            "reality_check_ratio": reality_sensitivity,
            "dynamic_blend_alpha_high": dynblend_sensitivity,
        },
        "bootstrap_ci": bootstrap_results,
        "regime_analysis": regime_results,
        "weight_analysis": {
            "weight_correlation_vix_har": round(corr_weights, 4),
            "disagreement_stats": {
                "mean_abs_diff": round(float(np.mean(diffs)), 4),
                "median_abs_diff": round(float(np.median(diffs)), 4),
                "pct_diff_gt_015": round(float(np.mean(diffs > 0.15) * 100), 1),
            },
            "har_vix_vol_ratio": {
                "mean": round(float(np.mean(ratio_har_vix)), 4),
                "median": round(float(np.median(ratio_har_vix)), 4),
                "pct_gt_1.5": round(float(np.mean(ratio_har_vix > 1.5) * 100), 1),
            },
        },
        "conclusion": {
            "best_ensemble": best_name,
            "best_mean_sharpe": round(best_sr, 4),
            "vix_mean_sharpe": round(vix_sr, 4),
            "delta": round(delta, 4),
            "harvey_t": round(t_stat, 4),
            "harvey_significant": abs(t_stat) > 3.0,
            "verdict": verdict,
        },
        "references": [
            "Corsi (2009, JFE): HAR-RV model",
            "Moreira & Muir (2017, JoF): Volatility-managed portfolios",
            "K530: HAR-ABS DM=-15.45 vs GJR-GARCH",
            "K533: prediction ≠ application (HAR best predictor, worst VT)",
            "K440/K470/K488/K503/K504/K524: 12/VIX irreducible kernel",
        ],
    }

    results_path = project_root / "experiments" / "k540_har_ensemble_vt_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")
    print(f"  Runtime: {elapsed:.1f} seconds")


if __name__ == "__main__":
    main()
