#!/usr/bin/env python3
"""
K760: Alternative Risk Premia Rotation — Can Multi-Factor Vol Strategies Beat 12/VIX?

[提出: Codex (7th suggestion), 執行: Claude]

Hypothesis: Harvesting multiple vol risk premia (variance carry, skew premium,
equity risk premium, safe haven) and rotating among them based on VIX regime
can produce better risk-adjusted returns than simple 12/VIX.

Design:
  Part A: 4 Alt Risk Premia Sleeves
    1. Variance Carry: earn when VIX > realized vol (short vol carry)
    2. Skew Premium: earn VIX term structure contango (VIX3M > VIX)
    3. Equity Risk Premium: SPY via 12/VIX weight
    4. Safe Haven Premium: GLD allocation

  Part B: 3 Regimes (VIX-based)
    - Low Vol (VIX < 15): overweight variance carry + equity
    - Normal (15 <= VIX <= 25): equal weight
    - High Vol (VIX > 25): overweight safe haven, cut carry

  Part C: Backtest monthly rebalancing, cross-OOS

Data: SPY, GLD, ^VIX, ^VIX3M from yfinance, 2008-2026
References:
  - Ilmanen (2011), Expected Returns — variance risk premium
  - Carr & Wu (2009), Variance Risk Premiums, RFS
  - Egloff, Leippold & Wu (2010), Variance Risk Dynamics
  - K175: Cross-asset rotation Sharpe 0.812 < Fixed (0.997)
  - K43: VIX3M/VVIX overlay NULL
  - T13: VIX term structure vol predictor but no VT gain
"""

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

# ─────────────────────────────────────────────
# 1. Data Download
# ─────────────────────────────────────────────
print("=" * 70)
print("K760: Alternative Risk Premia Rotation")
print("=" * 70)

tickers = {
    "SPY": "SPY",
    "GLD": "GLD",
    "VIX": "^VIX",
    "VIX3M": "^VIX3M",
}

data = {}
for name, ticker in tickers.items():
    print(f"Downloading {name} ({ticker})...")
    df = yf.download(ticker, start="2007-01-01", end="2026-04-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df["Close"].squeeze()

# Combine
prices = pd.DataFrame(data)
prices = prices.dropna()
print(f"\nData range: {prices.index[0].date()} to {prices.index[-1].date()}")
print(f"Total days: {len(prices)}")

# Simple returns
ret_spy = prices["SPY"].pct_change()
ret_gld = prices["GLD"].pct_change()

# 22-day realized vol (annualized)
rv_22d = ret_spy.rolling(22).std() * np.sqrt(252) * 100  # in % like VIX

# ─────────────────────────────────────────────
# 2. Define Alt Risk Premia Signals
# ─────────────────────────────────────────────
print("\n--- Defining Risk Premia Signals ---")

# Signal 1: Variance Carry = (VIX - RV) / VIX
# Positive when VIX > RV (typical "variance risk premium" state)
variance_carry = (prices["VIX"] - rv_22d) / prices["VIX"]
variance_carry = variance_carry.clip(0, 1)

# Signal 2: Skew/Term Structure Premium = max(0, 1 - VIX/VIX3M)
# Positive in contango (VIX3M > VIX = normal), zero in backwardation
term_structure_signal = 1 - prices["VIX"] / prices["VIX3M"]
term_structure_signal = term_structure_signal.clip(0, 1)

# Signal 3: Equity Risk Premium weight = 12 / VIX
equity_signal = 12.0 / prices["VIX"]
equity_signal = equity_signal.clip(0, 1)

# Signal 4: Safe Haven = 1 - equity_signal
safe_haven_signal = 1.0 - equity_signal

# Print signal stats
print(f"\nVariance Carry signal: mean={variance_carry.mean():.3f}, std={variance_carry.std():.3f}")
print(f"Term Structure signal: mean={term_structure_signal.mean():.3f}, std={term_structure_signal.std():.3f}")
print(f"Equity signal (12/VIX): mean={equity_signal.mean():.3f}, std={equity_signal.std():.3f}")
print(f"Safe Haven signal: mean={safe_haven_signal.mean():.3f}, std={safe_haven_signal.std():.3f}")

# ─────────────────────────────────────────────
# 3. Regime Definition
# ─────────────────────────────────────────────
print("\n--- Regime Analysis ---")

vix = prices["VIX"]
regime = pd.Series("Normal", index=vix.index)
regime[vix < 15] = "Low"
regime[vix > 25] = "High"

for r in ["Low", "Normal", "High"]:
    pct = (regime == r).mean() * 100
    avg_vix = vix[regime == r].mean()
    print(f"  {r}: {pct:.1f}% of time, avg VIX={avg_vix:.1f}")

# ─────────────────────────────────────────────
# 4. Portfolio Construction: Regime-Based Rotation
# ─────────────────────────────────────────────
print("\n--- Building Rotation Portfolios ---")

# CRITICAL: signal.shift(1) — all signals use yesterday's data
variance_carry_lag = variance_carry.shift(1)
term_structure_lag = term_structure_signal.shift(1)
equity_signal_lag = equity_signal.shift(1)
safe_haven_lag = safe_haven_signal.shift(1)
regime_lag = regime.shift(1)

# ── Strategy 1: Equal-Weight Multi-Premia (no regime rotation) ──
# Each sleeve contributes to SPY vs GLD allocation:
#   - Variance carry → SPY (earn carry by being in equity)
#   - Term structure → SPY (contango = stable, ok to hold equity)
#   - Equity signal → SPY (direct 12/VIX)
#   - Safe haven → GLD
# Equal weight: SPY_w = mean(variance_carry, term_structure, equity) / normalization
def build_equal_weight_portfolio():
    """Equal-weight multi-premia: average of 3 pro-equity signals → SPY weight"""
    spy_w = (variance_carry_lag + term_structure_lag + equity_signal_lag) / 3.0
    spy_w = spy_w.clip(0, 1)
    gld_w = 1.0 - spy_w
    return spy_w, gld_w

# ── Strategy 2: Regime-Rotated Multi-Premia ──
def build_regime_rotated_portfolio():
    """
    Regime-dependent sleeve weights:
      Low Vol (VIX<15):  variance_carry×0.4 + term_structure×0.2 + equity×0.4 → aggressive
      Normal (15-25):    variance_carry×0.3 + term_structure×0.2 + equity×0.3 + safe×0.2
      High Vol (>25):    variance_carry×0.0 + term_structure×0.1 + equity×0.2 + safe×0.7
    """
    spy_w = pd.Series(np.nan, index=prices.index)

    low = regime_lag == "Low"
    normal = regime_lag == "Normal"
    high = regime_lag == "High"

    # Low vol: overweight equity + carry
    spy_w[low] = (
        0.4 * variance_carry_lag[low]
        + 0.2 * term_structure_lag[low]
        + 0.4 * equity_signal_lag[low]
    )

    # Normal: balanced
    spy_w[normal] = (
        0.3 * variance_carry_lag[normal]
        + 0.2 * term_structure_lag[normal]
        + 0.3 * equity_signal_lag[normal]
    )
    # The remaining 0.2 goes to safe haven = GLD

    # High vol: defensive
    spy_w[high] = (
        0.0 * variance_carry_lag[high]
        + 0.1 * term_structure_lag[high]
        + 0.2 * equity_signal_lag[high]
    )
    # 0.7 goes to safe haven

    spy_w = spy_w.clip(0, 1)
    gld_w = 1.0 - spy_w
    return spy_w, gld_w

# ── Strategy 3: Carry-Weighted (variance carry dominates) ──
def build_carry_weighted_portfolio():
    """Variance carry as primary signal, others as secondary"""
    spy_w = (
        0.5 * variance_carry_lag
        + 0.2 * term_structure_lag
        + 0.3 * equity_signal_lag
    )
    spy_w = spy_w.clip(0, 1)
    gld_w = 1.0 - spy_w
    return spy_w, gld_w

# ── Baselines ──
def build_12vix_portfolio():
    """Standard 12/VIX baseline"""
    spy_w = equity_signal_lag.clip(0, 1)
    gld_w = 1.0 - spy_w
    return spy_w, gld_w

def build_5050_portfolio():
    """Static 50/50 baseline"""
    spy_w = pd.Series(0.5, index=prices.index)
    gld_w = pd.Series(0.5, index=prices.index)
    return spy_w, gld_w

def build_spy_bh_portfolio():
    """SPY buy-and-hold"""
    spy_w = pd.Series(1.0, index=prices.index)
    gld_w = pd.Series(0.0, index=prices.index)
    return spy_w, gld_w

# ─────────────────────────────────────────────
# 5. Monthly Rebalancing + TX Cost
# ─────────────────────────────────────────────
TX_COST = 0.0005  # 5 bps per leg

def compute_returns_monthly_rebal(spy_w, gld_w, start_date=None, end_date=None):
    """
    Monthly rebalancing with TX cost.
    Weights change only on first trading day of each month.
    """
    df = pd.DataFrame({
        "spy_w": spy_w,
        "gld_w": gld_w,
        "ret_spy": ret_spy,
        "ret_gld": ret_gld,
    }).dropna()

    if start_date:
        df = df[df.index >= start_date]
    if end_date:
        df = df[df.index <= end_date]

    if len(df) < 22:
        return None

    # Monthly rebalancing: only update weights on month start
    monthly_mask = df.index.to_series().dt.to_period("M") != df.index.to_series().dt.to_period("M").shift(1)

    active_spy_w = pd.Series(np.nan, index=df.index)
    active_gld_w = pd.Series(np.nan, index=df.index)

    prev_spy = 0.5  # initial weight
    for i, idx in enumerate(df.index):
        if monthly_mask.iloc[i]:
            # Rebalance day: update to new signal weight
            new_spy = df["spy_w"].iloc[i]
            new_gld = df["gld_w"].iloc[i]
            if np.isnan(new_spy):
                new_spy = prev_spy
                new_gld = 1 - prev_spy
            active_spy_w.iloc[i] = new_spy
            active_gld_w.iloc[i] = new_gld
            prev_spy = new_spy
        else:
            # Drift: keep previous weights (no rebalance)
            active_spy_w.iloc[i] = prev_spy
            active_gld_w.iloc[i] = 1 - prev_spy

    # Portfolio return
    port_ret = active_spy_w * df["ret_spy"] + active_gld_w * df["ret_gld"]

    # TX cost on weight changes
    dw_spy = active_spy_w.diff().abs()
    dw_gld = active_gld_w.diff().abs()
    tx = (dw_spy + dw_gld) * TX_COST
    tx.iloc[0] = 0

    port_ret_net = port_ret - tx

    return port_ret_net


def compute_returns_daily_rebal(spy_w, gld_w, start_date=None, end_date=None):
    """Daily rebalancing with TX cost (for comparison)."""
    df = pd.DataFrame({
        "spy_w": spy_w,
        "gld_w": gld_w,
        "ret_spy": ret_spy,
        "ret_gld": ret_gld,
    }).dropna()

    if start_date:
        df = df[df.index >= start_date]
    if end_date:
        df = df[df.index <= end_date]

    if len(df) < 22:
        return None

    port_ret = df["spy_w"] * df["ret_spy"] + df["gld_w"] * df["ret_gld"]

    dw_spy = df["spy_w"].diff().abs()
    dw_gld = df["gld_w"].diff().abs()
    tx = (dw_spy + dw_gld) * TX_COST
    tx.iloc[0] = 0

    port_ret_net = port_ret - tx
    return port_ret_net


# ─────────────────────────────────────────────
# 6. Performance Metrics
# ─────────────────────────────────────────────
def calc_metrics(returns, name=""):
    """Calculate standard performance metrics."""
    if returns is None or len(returns) < 22:
        return None
    r = returns.dropna()
    cum = (1 + r).cumprod()
    total_ret = cum.iloc[-1] - 1
    n_years = len(r) / 252
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    vol = r.std() * np.sqrt(252)
    sharpe = cagr / vol if vol > 0 else 0

    # Max drawdown
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252)
    sortino = cagr / downside if downside > 0 else 0

    return {
        "name": name,
        "cagr": float(round(cagr * 100, 2)),
        "vol": float(round(vol * 100, 2)),
        "sharpe": float(round(sharpe, 3)),
        "mdd": float(round(mdd * 100, 2)),
        "calmar": float(round(calmar, 3)),
        "sortino": float(round(sortino, 3)),
        "n_days": len(r),
        "n_years": round(n_years, 1),
    }


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test comparing two return series (higher is better)."""
    # Compare squared losses from zero (i.e., compare variances)
    d = e1 ** 2 - e2 ** 2  # positive if e2 is better (lower variance)
    d = d.dropna()
    if len(d) < 30:
        return np.nan, np.nan
    d_mean = d.mean()
    # Newey-West HAC standard error
    n = len(d)
    gamma_0 = d.var()
    gamma_sum = 0
    for k in range(1, h + 1):
        gamma_k = np.cov(d.iloc[k:].values, d.iloc[:-k].values)[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    dm_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)


# ─────────────────────────────────────────────
# 7. Full Sample Backtest
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART A: Full Sample Backtest (Monthly Rebalancing)")
print("=" * 70)

strategies = {
    "Equal-Weight Multi-Premia": build_equal_weight_portfolio,
    "Regime-Rotated Multi-Premia": build_regime_rotated_portfolio,
    "Carry-Weighted Multi-Premia": build_carry_weighted_portfolio,
    "12/VIX (Baseline)": build_12vix_portfolio,
    "50/50 SPY/GLD (Baseline)": build_5050_portfolio,
    "SPY Buy-Hold": build_spy_bh_portfolio,
}

full_results = {}
full_returns = {}

for name, builder in strategies.items():
    spy_w, gld_w = builder()
    ret = compute_returns_monthly_rebal(spy_w, gld_w, start_date="2008-01-01")
    metrics = calc_metrics(ret, name)
    if metrics:
        full_results[name] = metrics
        full_returns[name] = ret
        print(f"\n{name}:")
        print(f"  CAGR={metrics['cagr']:.2f}%  Vol={metrics['vol']:.2f}%  "
              f"Sharpe={metrics['sharpe']:.3f}  MDD={metrics['mdd']:.2f}%  "
              f"Calmar={metrics['calmar']:.3f}  Sortino={metrics['sortino']:.3f}")

# ─────────────────────────────────────────────
# 8. DM Tests vs 12/VIX
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART B: Diebold-Mariano Tests vs 12/VIX")
print("=" * 70)

baseline_ret = full_returns.get("12/VIX (Baseline)")
dm_results = {}

if baseline_ret is not None:
    for name, ret in full_returns.items():
        if "Baseline" in name or "Buy-Hold" in name:
            continue
        # Align
        common = baseline_ret.index.intersection(ret.index)
        r1 = ret.loc[common]
        r2 = baseline_ret.loc[common]

        # DM test on return differences (strategy vs baseline)
        diff = r1 - r2
        n = len(diff)
        if n < 30:
            continue
        t_stat = diff.mean() / (diff.std() / np.sqrt(n))
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

        dm_results[name] = {"t_stat": round(float(t_stat), 3), "p_value": round(float(p_val), 4)}
        sig = "★" if p_val < 0.05 else "NS"
        print(f"  {name} vs 12/VIX: t={t_stat:.3f}, p={p_val:.4f} {sig}")

# ─────────────────────────────────────────────
# 9. Daily vs Monthly Rebalancing Comparison
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART C: Daily vs Monthly Rebalancing")
print("=" * 70)

for name, builder in [
    ("Equal-Weight Multi-Premia", build_equal_weight_portfolio),
    ("Regime-Rotated Multi-Premia", build_regime_rotated_portfolio),
    ("12/VIX (Baseline)", build_12vix_portfolio),
]:
    spy_w, gld_w = builder()
    ret_m = compute_returns_monthly_rebal(spy_w, gld_w, start_date="2008-01-01")
    ret_d = compute_returns_daily_rebal(spy_w, gld_w, start_date="2008-01-01")
    m_m = calc_metrics(ret_m, f"{name} (Monthly)")
    m_d = calc_metrics(ret_d, f"{name} (Daily)")
    if m_m and m_d:
        print(f"\n{name}:")
        print(f"  Monthly: Sharpe={m_m['sharpe']:.3f}  MDD={m_m['mdd']:.2f}%")
        print(f"  Daily:   Sharpe={m_d['sharpe']:.3f}  MDD={m_d['mdd']:.2f}%")

# ─────────────────────────────────────────────
# 10. Regime-Conditional Performance
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART D: Regime-Conditional Performance")
print("=" * 70)

regime_perf = {}
for r_name in ["Low", "High", "Normal"]:
    mask = regime_lag == r_name
    regime_perf[r_name] = {}
    print(f"\n  Regime: {r_name} (VIX {'<15' if r_name == 'Low' else '>25' if r_name == 'High' else '15-25'})")

    for s_name in ["Equal-Weight Multi-Premia", "Regime-Rotated Multi-Premia", "12/VIX (Baseline)", "50/50 SPY/GLD (Baseline)"]:
        if s_name in full_returns:
            r = full_returns[s_name]
            regime_r = r[r.index.isin(mask[mask].index)]
            if len(regime_r) > 22:
                ann_ret = regime_r.mean() * 252 * 100
                ann_vol = regime_r.std() * np.sqrt(252) * 100
                sr = ann_ret / ann_vol if ann_vol > 0 else 0
                regime_perf[r_name][s_name] = {
                    "ann_ret": round(float(ann_ret), 2),
                    "ann_vol": round(float(ann_vol), 2),
                    "sharpe": round(float(sr / 100), 3),
                }
                print(f"    {s_name}: ret={ann_ret:.2f}%/yr  vol={ann_vol:.2f}%  Sharpe={sr/100:.3f}")

# ─────────────────────────────────────────────
# 11. Cross-OOS Validation (5 periods)
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART E: Cross-OOS Validation (5 non-overlapping 2-year periods)")
print("=" * 70)

oos_periods = [
    ("2010-01-01", "2011-12-31"),
    ("2012-01-01", "2013-12-31"),
    ("2014-01-01", "2015-12-31"),
    ("2016-01-01", "2017-12-31"),
    ("2020-01-01", "2021-12-31"),
]

cross_oos = {}
for name, builder in [
    ("Equal-Weight Multi-Premia", build_equal_weight_portfolio),
    ("Regime-Rotated Multi-Premia", build_regime_rotated_portfolio),
    ("Carry-Weighted Multi-Premia", build_carry_weighted_portfolio),
]:
    spy_w, gld_w = builder()
    wins = 0
    cross_oos[name] = []

    for start, end in oos_periods:
        ret_s = compute_returns_monthly_rebal(spy_w, gld_w, start_date=start, end_date=end)

        # Baseline: 50/50
        spy_w_b, gld_w_b = build_5050_portfolio()
        ret_b = compute_returns_monthly_rebal(spy_w_b, gld_w_b, start_date=start, end_date=end)

        m_s = calc_metrics(ret_s, name)
        m_b = calc_metrics(ret_b, "50/50")

        if m_s and m_b:
            win = m_s["sharpe"] > m_b["sharpe"]
            if win:
                wins += 1
            cross_oos[name].append({
                "period": f"{start[:4]}-{end[:4]}",
                "strategy_sharpe": m_s["sharpe"],
                "baseline_sharpe": m_b["sharpe"],
                "win": win,
            })

    print(f"\n{name}: {wins}/5 periods beat 50/50")
    for p in cross_oos[name]:
        marker = "✓" if p["win"] else "✗"
        print(f"  {p['period']}: Strategy={p['strategy_sharpe']:.3f} vs 50/50={p['baseline_sharpe']:.3f} {marker}")

# ─────────────────────────────────────────────
# 12. COMMON_START Period (2023-01-04 ~ today)
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART F: COMMON_START Period (2023-01-04 ~ today)")
print("=" * 70)

common_results = {}
for name, builder in strategies.items():
    spy_w, gld_w = builder()
    ret = compute_returns_monthly_rebal(spy_w, gld_w, start_date="2023-01-04")
    m = calc_metrics(ret, name)
    if m:
        common_results[name] = m
        print(f"\n{name}:")
        print(f"  CAGR={m['cagr']:.2f}%  Vol={m['vol']:.2f}%  Sharpe={m['sharpe']:.3f}  MDD={m['mdd']:.2f}%")

# ─────────────────────────────────────────────
# 13. Sensitivity Analysis (±20% parameter variation)
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART G: Sensitivity Analysis (±20% VIX thresholds)")
print("=" * 70)

sensitivity = {}
for vix_low, vix_high, label in [(12, 20, "-20%"), (15, 25, "Base"), (18, 30, "+20%")]:
    # Rebuild regime with different thresholds
    regime_sens = pd.Series("Normal", index=vix.index)
    regime_sens[vix < vix_low] = "Low"
    regime_sens[vix > vix_high] = "High"
    regime_sens_lag = regime_sens.shift(1)

    # Rebuild regime-rotated with these thresholds
    spy_w_s = pd.Series(np.nan, index=prices.index)
    low_s = regime_sens_lag == "Low"
    normal_s = regime_sens_lag == "Normal"
    high_s = regime_sens_lag == "High"

    spy_w_s[low_s] = (
        0.4 * variance_carry_lag[low_s]
        + 0.2 * term_structure_lag[low_s]
        + 0.4 * equity_signal_lag[low_s]
    )
    spy_w_s[normal_s] = (
        0.3 * variance_carry_lag[normal_s]
        + 0.2 * term_structure_lag[normal_s]
        + 0.3 * equity_signal_lag[normal_s]
    )
    spy_w_s[high_s] = (
        0.0 * variance_carry_lag[high_s]
        + 0.1 * term_structure_lag[high_s]
        + 0.2 * equity_signal_lag[high_s]
    )
    spy_w_s = spy_w_s.clip(0, 1)
    gld_w_s = 1.0 - spy_w_s

    ret_s = compute_returns_monthly_rebal(spy_w_s, gld_w_s, start_date="2008-01-01")
    m_s = calc_metrics(ret_s, f"Regime-Rotated ({label})")
    if m_s:
        sensitivity[label] = m_s
        print(f"  Thresholds ({vix_low}/{vix_high}): Sharpe={m_s['sharpe']:.3f}  MDD={m_s['mdd']:.2f}%")

# Check if Sharpe drops > 30%
base_sharpe = sensitivity.get("Base", {}).get("sharpe", 0)
for label in ["-20%", "+20%"]:
    if label in sensitivity and base_sharpe > 0:
        change = (sensitivity[label]["sharpe"] - base_sharpe) / base_sharpe * 100
        print(f"  {label} Sharpe change: {change:.1f}% {'PASS (<30%)' if abs(change) < 30 else 'FAIL (>30%)'}")

# ─────────────────────────────────────────────
# 14. Weight Distribution Analysis
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART H: Average Weight Distribution by Regime")
print("=" * 70)

weight_analysis = {}
for name, builder in [
    ("Equal-Weight", build_equal_weight_portfolio),
    ("Regime-Rotated", build_regime_rotated_portfolio),
    ("12/VIX", build_12vix_portfolio),
]:
    spy_w, gld_w = builder()
    spy_w_clean = spy_w.dropna()

    weight_analysis[name] = {
        "overall_spy_mean": round(float(spy_w_clean.mean()), 3),
        "overall_spy_std": round(float(spy_w_clean.std()), 3),
    }
    print(f"\n{name}: avg SPY weight = {spy_w_clean.mean():.3f} ± {spy_w_clean.std():.3f}")

    for r_name in ["Low", "Normal", "High"]:
        mask = regime == r_name
        r_w = spy_w_clean[spy_w_clean.index.isin(mask[mask].index)]
        if len(r_w) > 0:
            weight_analysis[name][f"{r_name}_spy_mean"] = round(float(r_w.mean()), 3)
            print(f"  {r_name}: avg SPY weight = {r_w.mean():.3f}")

# ─────────────────────────────────────────────
# 15. Variance Carry Premium Analysis
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("PART I: Variance Carry Premium Analysis")
print("=" * 70)

# When is VIX > RV (positive variance carry)?
vrp = prices["VIX"] - rv_22d
vrp_positive = (vrp > 0).mean() * 100
vrp_mean = vrp.dropna().mean()
vrp_std = vrp.dropna().std()

print(f"VIX > Realized Vol: {vrp_positive:.1f}% of days")
print(f"Variance Risk Premium (VIX - RV22d): mean={vrp_mean:.2f}%, std={vrp_std:.2f}%")

# Returns conditional on VRP sign
vrp_lag = vrp.shift(1)
spy_ret_vrp_pos = ret_spy[vrp_lag > 0].dropna()
spy_ret_vrp_neg = ret_spy[vrp_lag <= 0].dropna()

if len(spy_ret_vrp_pos) > 22 and len(spy_ret_vrp_neg) > 22:
    pos_ann = spy_ret_vrp_pos.mean() * 252 * 100
    neg_ann = spy_ret_vrp_neg.mean() * 252 * 100
    print(f"\nSPY return when VRP > 0 (yesterday): {pos_ann:.2f}%/yr ({len(spy_ret_vrp_pos)} days)")
    print(f"SPY return when VRP <= 0 (yesterday): {neg_ann:.2f}%/yr ({len(spy_ret_vrp_neg)} days)")

    # t-test
    t_vrp, p_vrp = stats.ttest_ind(spy_ret_vrp_pos, spy_ret_vrp_neg)
    print(f"  Difference t-test: t={t_vrp:.3f}, p={p_vrp:.4f}")

# ─────────────────────────────────────────────
# 16. Save Results
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("SAVING RESULTS")
print("=" * 70)

results = {
    "experiment_id": "K760",
    "title": "Alternative Risk Premia Rotation — Can Multi-Factor Vol Strategies Beat 12/VIX?",
    "proposer": "Codex (7th suggestion)",
    "executor": "Claude",
    "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    "data_source": "yfinance (SPY, GLD, ^VIX, ^VIX3M)",
    "data_period": f"{prices.index[0].date()} to {prices.index[-1].date()}",
    "n_days": len(prices),
    "methodology": {
        "signals": [
            "Variance Carry: (VIX - RV22d) / VIX, clipped [0,1]",
            "Term Structure: max(0, 1 - VIX/VIX3M)",
            "Equity (12/VIX): 12/VIX, clipped [0,1]",
            "Safe Haven: 1 - equity_signal",
        ],
        "regimes": {
            "Low": "VIX < 15",
            "Normal": "15 <= VIX <= 25",
            "High": "VIX > 25",
        },
        "rebalancing": "Monthly (first trading day)",
        "tx_cost": "5 bps per leg on weight changes",
        "lag": "signal.shift(1) — all signals use t-1 data",
    },
    "references": [
        "Ilmanen (2011) Expected Returns",
        "Carr & Wu (2009) Variance Risk Premiums, RFS",
        "K175: Cross-asset rotation < Fixed allocation",
        "K43: VIX3M overlay NULL",
        "T13: Term structure vol predictor but no VT gain",
    ],
    "full_sample_results": full_results,
    "dm_tests_vs_12vix": dm_results,
    "cross_oos_5_periods": cross_oos,
    "common_start_results": common_results,
    "sensitivity_analysis": sensitivity,
    "weight_analysis": weight_analysis,
    "variance_carry_analysis": {
        "vrp_positive_pct": round(float(vrp_positive), 1),
        "vrp_mean": round(float(vrp_mean), 2),
        "vrp_std": round(float(vrp_std), 2),
    },
    "regime_conditional_performance": regime_perf,
    "conclusions": [],  # filled below
}

# ── Derive conclusions ──
conclusions = []

# Compare best multi-premia vs 12/VIX
best_mp = max(
    [(n, m["sharpe"]) for n, m in full_results.items() if "Multi-Premia" in n],
    key=lambda x: x[1],
    default=("N/A", 0),
)
baseline_sharpe_full = full_results.get("12/VIX (Baseline)", {}).get("sharpe", 0)
baseline_5050_sharpe = full_results.get("50/50 SPY/GLD (Baseline)", {}).get("sharpe", 0)

conclusions.append(
    f"Best multi-premia strategy: {best_mp[0]} (Sharpe {best_mp[1]:.3f}) "
    f"vs 12/VIX ({baseline_sharpe_full:.3f}) vs 50/50 ({baseline_5050_sharpe:.3f})"
)

# DM significance
any_significant = any(v["p_value"] < 0.05 for v in dm_results.values())
conclusions.append(
    f"DM tests: {'At least one significant' if any_significant else 'No strategy significantly beats 12/VIX'}"
)

# Cross-OOS
for name, periods in cross_oos.items():
    wins = sum(1 for p in periods if p["win"])
    conclusions.append(f"Cross-OOS {name}: {wins}/5 beat 50/50")

# Variance carry
conclusions.append(
    f"Variance Risk Premium positive {vrp_positive:.0f}% of days "
    f"(mean VIX-RV = {vrp_mean:.1f}%)"
)

results["conclusions"] = conclusions

# Save
out_path = Path("experiments/k760_alt_risk_premia_results.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {out_path}")

# Print conclusions
print("\n" + "=" * 70)
print("CONCLUSIONS")
print("=" * 70)
for c in conclusions:
    print(f"  • {c}")

print("\n[K760 Complete]")
