#!/usr/bin/env python3
"""K598: Adaptive Tier with Debounce — Fix the 77% False Exit Problem
=======================================================================

Motivation:
    K597 found Adaptive Tier has 27.3 regime switches/year, 77% are false exits
    (<=5 days), costing ~1.67%/yr. This experiment tests debounce filters to
    reduce false switches while maintaining crisis protection.

Design:
    Base: Adaptive Tier (K595) — VIX<15 leverage, 15-20 standard, >20 exit
    Debounce variants:
      a. 3-day confirmation: only switch if VIX stays in new regime 3 consecutive days
      b. 5-day confirmation: same but 5 days
      c. MA smoothed: use 5-day MA of VIX for regime boundaries
      d. Hysteresis: different thresholds for entry vs exit (enter exit at VIX>22, re-enter at VIX<18)
      e. Weekly regime: only check regime on Fridays (reduce noise)

    Evaluation:
      - Regime switches/year, false exit rate
      - Sharpe, MDD, CAGR, Calmar, Sortino
      - Crisis protection (GFC, COVID, 2022)
      - Cross-OOS: 3 periods
      - Harvey t>3.0 vs original Adaptive Tier AND vs B&H

References:
    - K595: Adaptive Tier original (Sharpe 1.455, MDD -8.7%, CAGR 14.73%)
    - K597: Stress test revealing 77% false exits, 27.3 switches/year
    - Moreira & Muir (2017, JoF): Volatility-managed portfolios
    - Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing
    - Harvey (2016, JoF): t>3 threshold

Data source: yfinance (SPY, GLD, ^VIX, ^IRX)
Period: 2005-2026 (~21 years)
Author: [Proposed: User, Executed: Claude]
"""
from __future__ import annotations

import json
import sys
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
RF_ANNUAL = 0.02
ANNUALIZE = np.sqrt(252)
N_BOOTSTRAP = 5000
BORROWING_SPREAD = 0.005  # 50bps above risk-free
FALLBACK_RF = 0.04
np.random.seed(42)

# Piecewise parameters (from K568 IS optimization)
C1 = 12.0  # start ramp-down
C2 = 20.0  # full exit

# VIX-Conditional Leverage parameters (from K548/K551)
VIX_LEV_LOW = 15.0   # below this: 1.5x
VIX_LEV_HIGH = 25.0  # above this: 1.0x
LEV_MAX = 1.5
LEV_MIN = 1.0

# Cross-OOS periods — 3 non-overlapping ~7 year periods
OOS_PERIODS = [
    ("P1_2005_2012", "2005-06-01", "2012-05-31"),
    ("P2_2012_2019", "2012-06-01", "2019-05-31"),
    ("P3_2019_2026", "2019-06-01", "2026-03-28"),
]

# Crisis periods
CRISIS_PERIODS = {
    "GFC": ("2007-10-01", "2009-06-30"),
    "COVID": ("2020-01-15", "2020-06-30"),
    "Bear_2022": ("2022-01-01", "2022-12-31"),
}


# ============================================================
#  Weight Functions (building blocks)
# ============================================================
def w_piecewise(vix: np.ndarray) -> np.ndarray:
    """Piecewise linear: w=1 if VIX<C1, ramp to 0 at C2, w=0 if VIX>C2."""
    return np.clip(
        np.where(vix < C1, 1.0,
                 np.where(vix > C2, 0.0,
                          (C2 - vix) / (C2 - C1))),
        0.0, 1.0
    )


def w_12vix(vix: np.ndarray) -> np.ndarray:
    """Standard 12/VIX weight."""
    return np.clip(12.0 / vix, 0.0, 1.0)


def lev_vix_conditional(vix: np.ndarray) -> np.ndarray:
    """VIX-Conditional Leverage: 1.5x if VIX<15, 1.0x if VIX>25, linear between."""
    return np.clip(
        LEV_MAX - (LEV_MAX - LEV_MIN) * (vix - VIX_LEV_LOW) / (VIX_LEV_HIGH - VIX_LEV_LOW),
        LEV_MIN, LEV_MAX
    )


# ============================================================
#  Regime Classification
# ============================================================
def classify_regime(vix_val: float) -> int:
    """Classify VIX into regime: 0=leverage (VIX<15), 1=standard (15-20), 2=exit (>20)."""
    if vix_val < 15:
        return 0
    elif vix_val <= 20:
        return 1
    else:
        return 2


# ============================================================
#  Adaptive Tier Strategies (Original + Debounce Variants)
# ============================================================
def adaptive_tier_original(vix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Original Adaptive Tier — no debounce."""
    std = w_12vix(vix)
    pw = w_piecewise(vix)
    lev = lev_vix_conditional(vix)

    weight = np.where(vix < 15, std,
                      np.where(vix <= 20, std, pw))
    leverage = np.where(vix < 15, lev, np.ones_like(vix))
    return weight, leverage


def adaptive_tier_nday_confirm(vix: np.ndarray, n_days: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """N-day confirmation debounce: only switch regime if VIX stays in new regime
    for n_days consecutive days."""
    std = w_12vix(vix)
    pw = w_piecewise(vix)
    lev = lev_vix_conditional(vix)

    n = len(vix)
    # Classify raw regime per day
    raw_regime = np.array([classify_regime(v) for v in vix])

    # Apply N-day confirmation
    confirmed_regime = np.zeros(n, dtype=int)
    confirmed_regime[0] = raw_regime[0]
    pending_regime = raw_regime[0]
    pending_count = 0

    for i in range(1, n):
        if raw_regime[i] == confirmed_regime[i - 1]:
            # Staying in current regime — reset pending
            confirmed_regime[i] = confirmed_regime[i - 1]
            pending_regime = confirmed_regime[i]
            pending_count = 0
        elif raw_regime[i] == pending_regime and pending_regime != confirmed_regime[i - 1]:
            # Continuing in pending new regime
            pending_count += 1
            if pending_count >= n_days:
                confirmed_regime[i] = pending_regime
            else:
                confirmed_regime[i] = confirmed_regime[i - 1]
        else:
            # New different regime — start fresh pending
            pending_regime = raw_regime[i]
            pending_count = 1
            if n_days <= 1:
                confirmed_regime[i] = pending_regime
            else:
                confirmed_regime[i] = confirmed_regime[i - 1]

    # Compute weights based on confirmed regime
    weight = np.where(confirmed_regime == 0, std,
                      np.where(confirmed_regime == 1, std, pw))
    leverage = np.where(confirmed_regime == 0, lev, np.ones_like(vix))
    return weight, leverage


def adaptive_tier_ma_smoothed(vix: np.ndarray, window: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """MA smoothed: use moving average of VIX for regime boundaries."""
    # Compute MA
    vix_ma = pd.Series(vix).rolling(window=window, min_periods=1).mean().values

    std = w_12vix(vix)  # Weights still based on raw VIX (for accuracy)
    pw = w_piecewise(vix)
    lev = lev_vix_conditional(vix)

    # But regime classification uses smoothed VIX
    weight = np.where(vix_ma < 15, std,
                      np.where(vix_ma <= 20, std, pw))
    leverage = np.where(vix_ma < 15, lev, np.ones_like(vix))
    return weight, leverage


def adaptive_tier_hysteresis(vix: np.ndarray,
                              exit_threshold: float = 22.0,
                              reenter_threshold: float = 18.0,
                              leverage_exit: float = 17.0,
                              leverage_enter: float = 13.0) -> tuple[np.ndarray, np.ndarray]:
    """Hysteresis: different thresholds for entering vs exiting a regime.

    - Enter exit mode at VIX > exit_threshold (22), re-enter at VIX < reenter_threshold (18)
    - Enter leverage mode at VIX < leverage_enter (13), exit leverage at VIX > leverage_exit (17)
    """
    std = w_12vix(vix)
    pw = w_piecewise(vix)
    lev = lev_vix_conditional(vix)

    n = len(vix)
    regime = np.ones(n, dtype=int)  # Start in standard (1)

    for i in range(1, n):
        prev = regime[i - 1]

        if prev == 2:  # Currently in exit mode
            if vix[i] < reenter_threshold:
                # Check if should go to leverage or standard
                if vix[i] < leverage_enter:
                    regime[i] = 0  # leverage
                else:
                    regime[i] = 1  # standard
            else:
                regime[i] = 2  # stay in exit

        elif prev == 0:  # Currently in leverage mode
            if vix[i] > exit_threshold:
                regime[i] = 2  # jump to exit
            elif vix[i] > leverage_exit:
                regime[i] = 1  # move to standard
            else:
                regime[i] = 0  # stay in leverage

        else:  # prev == 1, standard mode
            if vix[i] > exit_threshold:
                regime[i] = 2  # move to exit
            elif vix[i] < leverage_enter:
                regime[i] = 0  # move to leverage
            else:
                regime[i] = 1  # stay in standard

    weight = np.where(regime == 0, std,
                      np.where(regime == 1, std, pw))
    leverage = np.where(regime == 0, lev, np.ones_like(vix))
    return weight, leverage


def adaptive_tier_weekly(vix: np.ndarray, dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray]:
    """Weekly regime: only update regime on Fridays (day_of_week=4)."""
    std = w_12vix(vix)
    pw = w_piecewise(vix)
    lev = lev_vix_conditional(vix)

    n = len(vix)
    regime = np.zeros(n, dtype=int)
    regime[0] = classify_regime(vix[0])

    for i in range(1, n):
        if dates[i].weekday() == 4:  # Friday
            regime[i] = classify_regime(vix[i])
        else:
            regime[i] = regime[i - 1]

    weight = np.where(regime == 0, std,
                      np.where(regime == 1, std, pw))
    leverage = np.where(regime == 0, lev, np.ones_like(vix))
    return weight, leverage


# ============================================================
#  Data Loading
# ============================================================
def load_data() -> pd.DataFrame:
    """Load SPY, GLD, VIX, IRX from yfinance."""
    print("=" * 70)
    print("K598: Adaptive Tier with Debounce — Fix False Exit Problem")
    print("=" * 70)
    print("\nDownloading data from yfinance...")

    tickers = ["SPY", "GLD", "^VIX"]
    data = yf.download(tickers, start="2004-11-01", end="2026-03-28",
                       auto_adjust=True, progress=False)

    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data

    df = pd.DataFrame({
        "SPY": close["SPY"],
        "GLD": close["GLD"],
        "VIX": close["^VIX"],
    }).dropna()

    # Risk-free rate
    try:
        irx = yf.download("^IRX", start="2004-11-01", end="2026-03-28",
                           auto_adjust=True, progress=False)
        if isinstance(irx.columns, pd.MultiIndex):
            irx.columns = irx.columns.get_level_values(0)
        df["rf_annual"] = irx["Close"].reindex(df.index).ffill() / 100
        df["rf_daily"] = df["rf_annual"] / 252
        print(f"  Risk-free rate from ^IRX: mean={df['rf_annual'].mean()*100:.2f}%")
    except Exception:
        df["rf_annual"] = FALLBACK_RF
        df["rf_daily"] = FALLBACK_RF / 252
        print(f"  Using fallback RF: {FALLBACK_RF*100:.1f}%")

    df["r_SPY"] = df["SPY"].pct_change()
    df["r_GLD"] = df["GLD"].pct_change()
    df["r_port"] = 0.5 * df["r_SPY"] + 0.5 * df["r_GLD"]  # 50/50 portfolio
    df = df.dropna()

    print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")

    # Descriptive statistics
    print(f"\n  VIX: mean={df['VIX'].mean():.1f}, std={df['VIX'].std():.1f}, "
          f"min={df['VIX'].min():.1f}, max={df['VIX'].max():.1f}")
    print(f"  VIX < 15: {(df['VIX'] < 15).mean()*100:.1f}% of days")
    print(f"  VIX 15-20: {((df['VIX'] >= 15) & (df['VIX'] <= 20)).mean()*100:.1f}% of days")
    print(f"  VIX > 20: {(df['VIX'] > 20).mean()*100:.1f}% of days")

    return df


# ============================================================
#  Performance Metrics
# ============================================================
def compute_strategy_returns(r_port: np.ndarray, weights: np.ndarray,
                              leverage: np.ndarray, rf_daily: np.ndarray,
                              tx_cost: float = 0.001) -> np.ndarray:
    """Compute daily strategy returns with leverage and borrowing costs."""
    effective = weights * leverage

    # Transaction cost on effective exposure changes
    eff_chg = np.abs(np.diff(effective, prepend=effective[0]))
    cost = eff_chg * tx_cost

    # Gross return = exposure * portfolio return + (1 - exposure) * rf
    gross = effective * r_port + (1.0 - effective) * rf_daily

    # Borrowing cost (only when leverage > 1)
    borrow = np.maximum(leverage - 1.0, 0.0) * weights * (rf_daily + BORROWING_SPREAD / 252)

    return gross - borrow - cost


def compute_metrics(daily_returns: np.ndarray, rf_daily: np.ndarray = None,
                    weights: np.ndarray = None, leverage: np.ndarray = None) -> dict:
    """Compute comprehensive performance metrics."""
    r = daily_returns
    n = len(r)
    if n < 126:  # minimum half year
        return None

    ann_ret = np.mean(r) * 252
    ann_vol = np.std(r, ddof=1) * ANNUALIZE

    if rf_daily is not None:
        excess = r - rf_daily
    else:
        excess = r - RF_ANNUAL / 252
    sharpe = np.mean(excess) / np.std(excess, ddof=1) * ANNUALIZE if np.std(excess) > 1e-10 else 0

    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1
    mdd = np.min(dd)

    years = n / 252
    cagr = cum[-1] ** (1 / years) - 1 if cum[-1] > 0 else -1

    calmar = cagr / abs(mdd) if abs(mdd) > 1e-10 else 0

    downside = excess[excess < 0]
    down_vol = np.std(downside, ddof=1) * ANNUALIZE if len(downside) > 10 else 1e-8
    sortino = (ann_ret - RF_ANNUAL) / down_vol

    turnover = 0.0
    if weights is not None:
        effective = weights * leverage if leverage is not None else weights
        turnover = float(np.mean(np.abs(np.diff(effective))) * 252)

    terminal = cum[-1] * 1_000_000

    # Avg/max exposure
    effective_exp = weights * leverage if leverage is not None else weights
    avg_exp = float(np.mean(effective_exp))
    max_exp = float(np.max(effective_exp))
    pct_leveraged = float(np.mean(effective_exp > 1.0)) * 100

    return {
        "ann_return": round(float(ann_ret) * 100, 2),
        "ann_vol": round(float(ann_vol) * 100, 2),
        "sharpe": round(float(sharpe), 3),
        "mdd": round(float(mdd) * 100, 2),
        "cagr": round(float(cagr) * 100, 2),
        "calmar": round(float(calmar), 3),
        "sortino": round(float(sortino), 3),
        "n_days": int(n),
        "terminal_1M": round(float(terminal), 0),
        "turnover": round(float(turnover), 1),
        "avg_exposure": round(avg_exp, 3),
        "max_exposure": round(max_exp, 3),
        "pct_leveraged": round(pct_leveraged, 1),
    }


# ============================================================
#  Regime Switching Analysis
# ============================================================
def analyze_regime_switches(regime_array: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    """Analyze regime switching behavior: count switches, false exits, durations."""
    n = len(regime_array)
    years = n / 252

    # Count switches
    switches = np.sum(regime_array[1:] != regime_array[:-1])
    switches_per_year = switches / years

    # Analyze each regime stint
    stints = []
    current_regime = regime_array[0]
    stint_start = 0
    for i in range(1, n):
        if regime_array[i] != current_regime:
            stints.append({
                "regime": int(current_regime),
                "start_idx": stint_start,
                "end_idx": i - 1,
                "duration": i - stint_start,
                "start_date": str(dates[stint_start].date()),
                "end_date": str(dates[i - 1].date()),
            })
            current_regime = regime_array[i]
            stint_start = i
    # Last stint
    stints.append({
        "regime": int(current_regime),
        "start_idx": stint_start,
        "end_idx": n - 1,
        "duration": n - stint_start,
        "start_date": str(dates[stint_start].date()),
        "end_date": str(dates[n - 1].date()),
    })

    # False exits: exit regime (2) stints <= 5 days
    exit_stints = [s for s in stints if s["regime"] == 2]
    false_exits = [s for s in exit_stints if s["duration"] <= 5]
    false_exit_rate = len(false_exits) / len(exit_stints) * 100 if exit_stints else 0

    # Regime distribution
    regime_counts = {
        "leverage_pct": float(np.mean(regime_array == 0)) * 100,
        "standard_pct": float(np.mean(regime_array == 1)) * 100,
        "exit_pct": float(np.mean(regime_array == 2)) * 100,
    }

    # Average stint durations by regime
    avg_duration = {}
    for r in [0, 1, 2]:
        r_stints = [s["duration"] for s in stints if s["regime"] == r]
        if r_stints:
            avg_duration[f"regime_{r}_avg_days"] = round(np.mean(r_stints), 1)
            avg_duration[f"regime_{r}_median_days"] = round(np.median(r_stints), 1)
            avg_duration[f"regime_{r}_count"] = len(r_stints)

    return {
        "total_switches": int(switches),
        "switches_per_year": round(switches_per_year, 1),
        "total_exit_stints": len(exit_stints),
        "false_exits_le5d": len(false_exits),
        "false_exit_rate_pct": round(false_exit_rate, 1),
        "regime_distribution": regime_counts,
        "stint_durations": avg_duration,
    }


def get_regime_array(vix: np.ndarray, strategy_fn, dates: pd.DatetimeIndex = None) -> np.ndarray:
    """Get the regime array for a given strategy (for switch analysis)."""
    n = len(vix)

    if strategy_fn == "original":
        return np.array([classify_regime(v) for v in vix])

    elif strategy_fn == "confirm_3d":
        raw = np.array([classify_regime(v) for v in vix])
        confirmed = np.zeros(n, dtype=int)
        confirmed[0] = raw[0]
        pending = raw[0]
        count = 0
        for i in range(1, n):
            if raw[i] == confirmed[i - 1]:
                confirmed[i] = confirmed[i - 1]
                pending = confirmed[i]
                count = 0
            elif raw[i] == pending and pending != confirmed[i - 1]:
                count += 1
                if count >= 3:
                    confirmed[i] = pending
                else:
                    confirmed[i] = confirmed[i - 1]
            else:
                pending = raw[i]
                count = 1
                confirmed[i] = confirmed[i - 1]
        return confirmed

    elif strategy_fn == "confirm_5d":
        raw = np.array([classify_regime(v) for v in vix])
        confirmed = np.zeros(n, dtype=int)
        confirmed[0] = raw[0]
        pending = raw[0]
        count = 0
        for i in range(1, n):
            if raw[i] == confirmed[i - 1]:
                confirmed[i] = confirmed[i - 1]
                pending = confirmed[i]
                count = 0
            elif raw[i] == pending and pending != confirmed[i - 1]:
                count += 1
                if count >= 5:
                    confirmed[i] = pending
                else:
                    confirmed[i] = confirmed[i - 1]
            else:
                pending = raw[i]
                count = 1
                confirmed[i] = confirmed[i - 1]
        return confirmed

    elif strategy_fn == "ma_smoothed":
        vix_ma = pd.Series(vix).rolling(window=5, min_periods=1).mean().values
        return np.array([classify_regime(v) for v in vix_ma])

    elif strategy_fn == "hysteresis":
        regime = np.ones(n, dtype=int)
        for i in range(1, n):
            prev = regime[i - 1]
            if prev == 2:
                if vix[i] < 18:
                    regime[i] = 0 if vix[i] < 13 else 1
                else:
                    regime[i] = 2
            elif prev == 0:
                if vix[i] > 22:
                    regime[i] = 2
                elif vix[i] > 17:
                    regime[i] = 1
                else:
                    regime[i] = 0
            else:
                if vix[i] > 22:
                    regime[i] = 2
                elif vix[i] < 13:
                    regime[i] = 0
                else:
                    regime[i] = 1
        return regime

    elif strategy_fn == "weekly":
        regime = np.zeros(n, dtype=int)
        regime[0] = classify_regime(vix[0])
        for i in range(1, n):
            if dates[i].weekday() == 4:
                regime[i] = classify_regime(vix[i])
            else:
                regime[i] = regime[i - 1]
        return regime

    return np.array([classify_regime(v) for v in vix])


# ============================================================
#  Statistical Tests
# ============================================================
def dm_test(r1: np.ndarray, r2: np.ndarray) -> tuple[float, float]:
    """Diebold-Mariano test. Positive t means r1 is better."""
    d = r1 - r2
    n = len(d)
    d_mean = np.mean(d)
    bw = int(n ** (1/3))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, bw + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / (bw + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


def jkm_sharpe_test(r1: np.ndarray, r2: np.ndarray) -> tuple[float, float]:
    """Jobson-Korkie-Memmel test for Sharpe ratio difference."""
    mu1, mu2 = np.mean(r1), np.mean(r2)
    s1, s2 = np.std(r1, ddof=1), np.std(r2, ddof=1)
    n = len(r1)
    if s1 < 1e-10 or s2 < 1e-10:
        return 0.0, 1.0
    sr1, sr2 = mu1 / s1, mu2 / s2
    rho = np.corrcoef(r1, r2)[0, 1]
    theta = (1 / n) * (2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2 * sr1 * sr2 * rho))
    if theta <= 0:
        return 0.0, 1.0
    z = (sr1 - sr2) / np.sqrt(theta)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(z), float(p)


def bootstrap_sharpe_diff(r1: np.ndarray, r2: np.ndarray, n_boot: int = N_BOOTSTRAP) -> dict:
    """Bootstrap confidence interval for Sharpe ratio difference."""
    n = len(r1)
    sr_diffs = []
    for _ in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        b1, b2 = r1[idx], r2[idx]
        s1 = np.mean(b1) / np.std(b1, ddof=1) * ANNUALIZE if np.std(b1) > 1e-10 else 0
        s2 = np.mean(b2) / np.std(b2, ddof=1) * ANNUALIZE if np.std(b2) > 1e-10 else 0
        sr_diffs.append(s1 - s2)
    sr_diffs = np.array(sr_diffs)
    return {
        "mean_diff": round(float(np.mean(sr_diffs)), 3),
        "ci_2_5": round(float(np.percentile(sr_diffs, 2.5)), 3),
        "ci_97_5": round(float(np.percentile(sr_diffs, 97.5)), 3),
        "pct_positive": round(float(np.mean(sr_diffs > 0)) * 100, 1),
    }


# ============================================================
#  Crisis Period Analysis
# ============================================================
def analyze_crisis(r_strategy: np.ndarray, r_bh: np.ndarray, dates: pd.DatetimeIndex,
                   crisis_start: str, crisis_end: str) -> dict:
    """Analyze strategy performance during a crisis period."""
    mask = (dates >= crisis_start) & (dates <= crisis_end)
    if mask.sum() < 5:
        return None

    r_s = r_strategy[mask]
    r_b = r_bh[mask]

    cum_s = np.cumprod(1 + r_s)
    cum_b = np.cumprod(1 + r_b)

    peak_s = np.maximum.accumulate(cum_s)
    peak_b = np.maximum.accumulate(cum_b)

    return {
        "n_days": int(mask.sum()),
        "strategy_return": round(float(cum_s[-1] - 1) * 100, 2),
        "bh_return": round(float(cum_b[-1] - 1) * 100, 2),
        "strategy_mdd": round(float(np.min(cum_s / peak_s - 1)) * 100, 2),
        "bh_mdd": round(float(np.min(cum_b / peak_b - 1)) * 100, 2),
        "protection": round(float((cum_s[-1] - 1) - (cum_b[-1] - 1)) * 100, 2),
    }


# ============================================================
#  Estimate False Exit Cost
# ============================================================
def estimate_false_exit_cost(vix: np.ndarray, r_port: np.ndarray,
                              regime_array: np.ndarray) -> dict:
    """Estimate the cost of false exits: missed returns during short exit stints."""
    n = len(vix)
    total_missed = 0.0
    n_false = 0
    missed_returns = []

    # Find exit stints <= 5 days
    i = 0
    while i < n:
        if regime_array[i] == 2:  # exit regime
            start = i
            while i < n and regime_array[i] == 2:
                i += 1
            duration = i - start
            if duration <= 5:
                # This is a false exit — calculate missed return
                stint_ret = np.sum(r_port[start:i])
                total_missed += stint_ret
                missed_returns.append(stint_ret)
                n_false += 1
        else:
            i += 1

    years = n / 252
    annual_cost = -total_missed / years if total_missed < 0 else total_missed / years

    return {
        "n_false_exits": n_false,
        "total_missed_return_pct": round(float(total_missed) * 100, 2),
        "annual_missed_return_pct": round(float(total_missed / years) * 100, 2),
        "avg_missed_per_false_exit_pct": round(float(np.mean(missed_returns)) * 100, 3) if missed_returns else 0,
        "false_exits_positive_pct": round(float(np.mean([r > 0 for r in missed_returns])) * 100, 1) if missed_returns else 0,
    }


# ============================================================
#  Main Experiment
# ============================================================
def main():
    df = load_data()

    vix = df["VIX"].values
    r_port = df["r_port"].values
    rf_daily = df["rf_daily"].values
    dates = df.index

    # Define all strategies
    print("\n" + "=" * 70)
    print("Computing strategy weights...")
    print("=" * 70)

    strategies = {}

    # Buy & Hold baseline
    w_bh = np.ones(len(vix))
    l_bh = np.ones(len(vix))
    strategies["BuyHold"] = (w_bh, l_bh)

    # Original Adaptive Tier
    w_orig, l_orig = adaptive_tier_original(vix)
    strategies["AT_Original"] = (w_orig, l_orig)

    # Debounce variants
    w_3d, l_3d = adaptive_tier_nday_confirm(vix, n_days=3)
    strategies["AT_Confirm3D"] = (w_3d, l_3d)

    w_5d, l_5d = adaptive_tier_nday_confirm(vix, n_days=5)
    strategies["AT_Confirm5D"] = (w_5d, l_5d)

    w_ma, l_ma = adaptive_tier_ma_smoothed(vix, window=5)
    strategies["AT_MA5"] = (w_ma, l_ma)

    w_hyst, l_hyst = adaptive_tier_hysteresis(vix)
    strategies["AT_Hysteresis"] = (w_hyst, l_hyst)

    w_wk, l_wk = adaptive_tier_weekly(vix, dates)
    strategies["AT_Weekly"] = (w_wk, l_wk)

    # Compute returns
    print("\nComputing strategy returns (10bp TX cost)...")
    returns = {}
    for name, (w, l) in strategies.items():
        returns[name] = compute_strategy_returns(r_port, w, l, rf_daily, tx_cost=0.001)

    # ============================================================
    #  Full Sample Metrics
    # ============================================================
    print("\n" + "=" * 70)
    print("FULL SAMPLE PERFORMANCE")
    print("=" * 70)

    full_metrics = {}
    for name, (w, l) in strategies.items():
        m = compute_metrics(returns[name], rf_daily, w, l)
        full_metrics[name] = m
        if m:
            print(f"  {name:20s}: Sharpe={m['sharpe']:.3f}  CAGR={m['cagr']:.2f}%  "
                  f"MDD={m['mdd']:.2f}%  Sortino={m['sortino']:.3f}  "
                  f"Turnover={m['turnover']:.1f}  AvgExp={m['avg_exposure']:.3f}")

    # ============================================================
    #  Regime Switching Analysis
    # ============================================================
    print("\n" + "=" * 70)
    print("REGIME SWITCHING ANALYSIS")
    print("=" * 70)

    regime_keys = {
        "AT_Original": "original",
        "AT_Confirm3D": "confirm_3d",
        "AT_Confirm5D": "confirm_5d",
        "AT_MA5": "ma_smoothed",
        "AT_Hysteresis": "hysteresis",
        "AT_Weekly": "weekly",
    }

    switch_analysis = {}
    for name, fn_key in regime_keys.items():
        regime = get_regime_array(vix, fn_key, dates)
        sa = analyze_regime_switches(regime, dates)
        switch_analysis[name] = sa
        print(f"\n  {name}:")
        print(f"    Switches/yr: {sa['switches_per_year']:.1f}  "
              f"False exits: {sa['false_exits_le5d']}/{sa['total_exit_stints']} "
              f"({sa['false_exit_rate_pct']:.1f}%)")
        dist = sa['regime_distribution']
        print(f"    Regime dist: leverage={dist['leverage_pct']:.1f}%  "
              f"standard={dist['standard_pct']:.1f}%  exit={dist['exit_pct']:.1f}%")

    # ============================================================
    #  False Exit Cost Analysis
    # ============================================================
    print("\n" + "=" * 70)
    print("FALSE EXIT COST ANALYSIS")
    print("=" * 70)

    false_exit_costs = {}
    for name, fn_key in regime_keys.items():
        regime = get_regime_array(vix, fn_key, dates)
        fec = estimate_false_exit_cost(vix, r_port, regime)
        false_exit_costs[name] = fec
        print(f"  {name}: {fec['n_false_exits']} false exits, "
              f"annual missed return={fec['annual_missed_return_pct']:.2f}%/yr, "
              f"positive missed={fec['false_exits_positive_pct']:.1f}%")

    # ============================================================
    #  Crisis Protection
    # ============================================================
    print("\n" + "=" * 70)
    print("CRISIS PROTECTION")
    print("=" * 70)

    crisis_results = {}
    for crisis_name, (c_start, c_end) in CRISIS_PERIODS.items():
        crisis_results[crisis_name] = {}
        print(f"\n  --- {crisis_name} ({c_start} to {c_end}) ---")
        for name in strategies:
            cr = analyze_crisis(returns[name], returns["BuyHold"], dates, c_start, c_end)
            if cr:
                crisis_results[crisis_name][name] = cr
                if name != "BuyHold":
                    print(f"    {name:20s}: return={cr['strategy_return']:+.2f}%  "
                          f"MDD={cr['strategy_mdd']:.2f}%  "
                          f"protection={cr['protection']:+.2f}%")

    # ============================================================
    #  Statistical Tests vs Original AT and vs B&H
    # ============================================================
    print("\n" + "=" * 70)
    print("STATISTICAL TESTS")
    print("=" * 70)

    stat_tests = {}
    debounce_names = ["AT_Confirm3D", "AT_Confirm5D", "AT_MA5", "AT_Hysteresis", "AT_Weekly"]

    for name in debounce_names:
        stat_tests[name] = {}

        # vs Original AT
        dm_t, dm_p = dm_test(returns[name], returns["AT_Original"])
        jkm_z, jkm_p = jkm_sharpe_test(returns[name], returns["AT_Original"])
        boot = bootstrap_sharpe_diff(returns[name], returns["AT_Original"])
        harvey_pass = abs(jkm_z) > 3.0
        stat_tests[name]["vs_AT_Original"] = {
            "dm_t": round(dm_t, 3),
            "dm_p": round(dm_p, 4),
            "jkm_z": round(jkm_z, 3),
            "jkm_p": round(jkm_p, 4),
            "harvey_pass": harvey_pass,
            "bootstrap": boot,
        }
        print(f"\n  {name} vs AT_Original:")
        print(f"    DM t={dm_t:.3f} (p={dm_p:.4f})  JKM z={jkm_z:.3f} (p={jkm_p:.4f})  "
              f"Harvey={'PASS' if harvey_pass else 'FAIL'}")
        print(f"    Bootstrap Sharpe diff: {boot['mean_diff']:+.3f} "
              f"[{boot['ci_2_5']:.3f}, {boot['ci_97_5']:.3f}], "
              f"{boot['pct_positive']:.1f}% positive")

        # vs B&H
        dm_t2, dm_p2 = dm_test(returns[name], returns["BuyHold"])
        jkm_z2, jkm_p2 = jkm_sharpe_test(returns[name], returns["BuyHold"])
        boot2 = bootstrap_sharpe_diff(returns[name], returns["BuyHold"])
        harvey_pass2 = abs(jkm_z2) > 3.0
        stat_tests[name]["vs_BuyHold"] = {
            "dm_t": round(dm_t2, 3),
            "dm_p": round(dm_p2, 4),
            "jkm_z": round(jkm_z2, 3),
            "jkm_p": round(jkm_p2, 4),
            "harvey_pass": harvey_pass2,
            "bootstrap": boot2,
        }
        print(f"  {name} vs BuyHold:")
        print(f"    DM t={dm_t2:.3f} (p={dm_p2:.4f})  JKM z={jkm_z2:.3f} (p={jkm_p2:.4f})  "
              f"Harvey={'PASS' if harvey_pass2 else 'FAIL'}")

    # Also test Original AT vs B&H for reference
    dm_orig_bh_t, dm_orig_bh_p = dm_test(returns["AT_Original"], returns["BuyHold"])
    jkm_orig_bh_z, jkm_orig_bh_p = jkm_sharpe_test(returns["AT_Original"], returns["BuyHold"])
    stat_tests["AT_Original"] = {
        "vs_BuyHold": {
            "dm_t": round(dm_orig_bh_t, 3),
            "dm_p": round(dm_orig_bh_p, 4),
            "jkm_z": round(jkm_orig_bh_z, 3),
            "jkm_p": round(jkm_orig_bh_p, 4),
            "harvey_pass": abs(jkm_orig_bh_z) > 3.0,
        }
    }
    print(f"\n  AT_Original vs BuyHold:")
    print(f"    JKM z={jkm_orig_bh_z:.3f} (p={jkm_orig_bh_p:.4f})  "
          f"Harvey={'PASS' if abs(jkm_orig_bh_z) > 3.0 else 'FAIL'}")

    # ============================================================
    #  Cross-OOS Validation (3 periods)
    # ============================================================
    print("\n" + "=" * 70)
    print("CROSS-OOS VALIDATION (3 periods)")
    print("=" * 70)

    oos_results = {}
    for period_name, start, end in OOS_PERIODS:
        mask = (dates >= start) & (dates <= end)
        if mask.sum() < 252:
            continue

        oos_results[period_name] = {}
        print(f"\n  --- {period_name} (N={mask.sum()}) ---")

        for name in strategies:
            r_sub = returns[name][mask]
            rf_sub = rf_daily[mask]
            w_sub = strategies[name][0][mask] if strategies[name][0] is not None else None
            l_sub = strategies[name][1][mask] if strategies[name][1] is not None else None
            m = compute_metrics(r_sub, rf_sub, w_sub, l_sub)
            if m:
                oos_results[period_name][name] = m
                if name not in ["BuyHold"]:
                    print(f"    {name:20s}: Sharpe={m['sharpe']:.3f}  CAGR={m['cagr']:.2f}%  MDD={m['mdd']:.2f}%")

    # Check OOS consistency
    print("\n  OOS CONSISTENCY (Sharpe > BuyHold in each period):")
    oos_consistency = {}
    for name in debounce_names + ["AT_Original"]:
        passes = 0
        total = 0
        for period_name, _, _ in OOS_PERIODS:
            if period_name in oos_results and name in oos_results[period_name] and "BuyHold" in oos_results[period_name]:
                total += 1
                if oos_results[period_name][name]["sharpe"] > oos_results[period_name]["BuyHold"]["sharpe"]:
                    passes += 1
        oos_consistency[name] = f"{passes}/{total}"
        print(f"    {name:20s}: {passes}/{total} periods Sharpe > B&H")

    # ============================================================
    #  Summary: Best Debounce Method
    # ============================================================
    print("\n" + "=" * 70)
    print("SUMMARY: DEBOUNCE COMPARISON")
    print("=" * 70)

    print(f"\n  {'Strategy':<20s} {'Sharpe':>7s} {'CAGR':>7s} {'MDD':>7s} "
          f"{'Sw/yr':>6s} {'FalseExit':>10s} {'AnnCost':>8s} {'OOS':>5s}")
    print("  " + "-" * 75)

    for name in ["AT_Original"] + debounce_names:
        m = full_metrics[name]
        sa = switch_analysis[name]
        fec = false_exit_costs[name]
        oos = oos_consistency.get(name, "?/?")
        print(f"  {name:<20s} {m['sharpe']:>7.3f} {m['cagr']:>6.2f}% {m['mdd']:>6.2f}% "
              f"{sa['switches_per_year']:>6.1f} {sa['false_exit_rate_pct']:>9.1f}% "
              f"{fec['annual_missed_return_pct']:>7.2f}% {oos:>5s}")

    # ============================================================
    #  Find Best Variant
    # ============================================================
    all_names = ["AT_Original"] + debounce_names

    # Score: weighted combination of Sharpe improvement, false exit reduction, crisis protection
    best_name = None
    best_score = -999

    for name in debounce_names:
        m = full_metrics[name]
        m_orig = full_metrics["AT_Original"]
        sa = switch_analysis[name]
        sa_orig = switch_analysis["AT_Original"]
        fec = false_exit_costs[name]
        fec_orig = false_exit_costs["AT_Original"]

        # Score components:
        sharpe_delta = m["sharpe"] - m_orig["sharpe"]
        false_exit_reduction = (sa_orig["false_exit_rate_pct"] - sa["false_exit_rate_pct"]) / max(sa_orig["false_exit_rate_pct"], 1)
        cost_reduction = (fec_orig["annual_missed_return_pct"] - fec["annual_missed_return_pct"]) / max(abs(fec_orig["annual_missed_return_pct"]), 0.01)

        # Check crisis protection maintained (GFC MDD should not be much worse)
        gfc_orig = crisis_results.get("GFC", {}).get("AT_Original", {}).get("strategy_mdd", -100)
        gfc_new = crisis_results.get("GFC", {}).get(name, {}).get("strategy_mdd", -100)
        crisis_ok = gfc_new >= gfc_orig - 5  # Allow up to 5% worse MDD in GFC

        score = sharpe_delta * 10 + false_exit_reduction * 2 + cost_reduction * 2
        if not crisis_ok:
            score -= 10  # Heavy penalty for losing crisis protection

        if score > best_score:
            best_score = score
            best_name = name

    print(f"\n  BEST DEBOUNCE VARIANT: {best_name} (score={best_score:.3f})")
    best_m = full_metrics[best_name]
    orig_m = full_metrics["AT_Original"]
    print(f"  Sharpe: {orig_m['sharpe']:.3f} → {best_m['sharpe']:.3f} ({best_m['sharpe'] - orig_m['sharpe']:+.3f})")
    print(f"  CAGR:   {orig_m['cagr']:.2f}% → {best_m['cagr']:.2f}% ({best_m['cagr'] - orig_m['cagr']:+.2f}%)")
    print(f"  MDD:    {orig_m['mdd']:.2f}% → {best_m['mdd']:.2f}% ({best_m['mdd'] - orig_m['mdd']:+.2f}%)")

    best_sa = switch_analysis[best_name]
    orig_sa = switch_analysis["AT_Original"]
    print(f"  Switches/yr: {orig_sa['switches_per_year']:.1f} → {best_sa['switches_per_year']:.1f}")
    print(f"  False exits:  {orig_sa['false_exit_rate_pct']:.1f}% → {best_sa['false_exit_rate_pct']:.1f}%")

    best_fec = false_exit_costs[best_name]
    orig_fec = false_exit_costs["AT_Original"]
    print(f"  Annual cost:  {orig_fec['annual_missed_return_pct']:.2f}% → {best_fec['annual_missed_return_pct']:.2f}%")

    # ============================================================
    #  Recommendation
    # ============================================================
    sharpe_improved = best_m["sharpe"] > orig_m["sharpe"]
    false_exits_reduced = best_sa["false_exit_rate_pct"] < orig_sa["false_exit_rate_pct"] - 10
    cost_reduced = abs(best_fec["annual_missed_return_pct"]) < abs(orig_fec["annual_missed_return_pct"]) * 0.7

    recommendation = "UPGRADE" if (sharpe_improved and false_exits_reduced) else "KEEP_ORIGINAL"
    print(f"\n  RECOMMENDATION: {recommendation}")
    if recommendation == "UPGRADE":
        print(f"  → Replace AT_Original with {best_name} in production")
    else:
        print(f"  → Keep original Adaptive Tier. Debounce trade-off not favorable enough.")

    # ============================================================
    #  Save Results
    # ============================================================
    results = {
        "experiment_id": "K598",
        "title": "Adaptive Tier with Debounce — Fix False Exit Problem",
        "description": f"Tested 5 debounce variants to reduce 77% false exit rate. "
                       f"Best variant: {best_name}. Recommendation: {recommendation}.",
        "data_source": "yfinance (SPY, GLD, ^VIX, ^IRX)",
        "data_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        "n_trading_days": len(df),
        "references": [
            "K595: Adaptive Tier original (Sharpe 1.455, MDD -8.7%, CAGR 14.73%)",
            "K597: Stress test — 27.3 switches/yr, 77% false exits, 1.67%/yr cost",
            "Moreira & Muir (2017, JoF): Volatility-managed portfolios",
            "Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing",
            "Harvey (2016, JoF): t>3 threshold",
        ],
        "full_sample_metrics": full_metrics,
        "regime_switch_analysis": switch_analysis,
        "false_exit_costs": false_exit_costs,
        "crisis_protection": crisis_results,
        "statistical_tests": stat_tests,
        "cross_oos": oos_results,
        "oos_consistency": oos_consistency,
        "best_variant": best_name,
        "recommendation": recommendation,
        "best_variant_improvement": {
            "sharpe_delta": round(best_m["sharpe"] - orig_m["sharpe"], 3),
            "cagr_delta": round(best_m["cagr"] - orig_m["cagr"], 2),
            "mdd_delta": round(best_m["mdd"] - orig_m["mdd"], 2),
            "switches_reduction": round(orig_sa["switches_per_year"] - best_sa["switches_per_year"], 1),
            "false_exit_reduction": round(orig_sa["false_exit_rate_pct"] - best_sa["false_exit_rate_pct"], 1),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(__file__).parent / "k598_adaptive_debounce_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    main()
