"""
K306: VIX Speed as Binary Risk Trigger — Proper OOS Strategy Test
==================================================================
[提出: 用戶, 執行: Claude]

Background:
  K300 found VIX speed z-score survives rolling validation but with tiny QLIKE
  improvement (+0.01%). However, as a BINARY risk trigger (threshold=1.0), it
  showed -40% MDD improvement. This experiment does proper 5-period cross-OOS
  validation of the STRATEGY (not just the forecast).

Design:
  Signal: VIX 20d z-score > threshold → reduce equity to 50%
  Base portfolio: 50/50 SPY/GLD (monthly rebalance)
  Immediate override when signal triggers (daily check)
  Thresholds tested: 0.5, 1.0, 1.5, 2.0

Benchmarks:
  1. 50/50 B&H (no timing, monthly rebalance)
  2. 50/50 + VT 12/VIX (current best strategy — Volatility Targeting)
  3. 50/50 + VIX speed trigger (this experiment)
  4. 50/50 + VT + VIX speed overlay (VT + trigger together)

5-Period Cross-OOS (2005-2024, ~4-year periods):
  P1: 2005-2008 (GFC ramp-up)
  P2: 2009-2012 (recovery)
  P3: 2013-2016 (low-vol era)
  P4: 2017-2020 (COVID)
  P5: 2021-2024 (rate hikes)

Metrics: Sharpe, MDD, Calmar, trades/yr, net Sharpe at 5bps

Data: SPY, GLD, ^VIX daily from yfinance. 2003-2024.
"""

import sys
import os
import warnings
import json
import time
import traceback
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2003-01-01"
DATA_END = "2024-12-31"
VIX_MA_WINDOW = 20          # VIX z-score lookback
TARGET_VOL_ANNUAL = 0.10    # VT target: 10% annualized
MAX_LEVERAGE = 1.5           # VT max leverage
TX_COST_BPS = 5              # Transaction cost per trade (one-way)
RF_ANNUAL = 0.02             # Risk-free rate
RF_DAILY = RF_ANNUAL / 252
GARCH_WINDOW = 252           # For VT: EWMA-like vol estimation window (simpler for strategy)

# Thresholds to test
THRESHOLDS = [0.5, 1.0, 1.5, 2.0]

# Equity reduction when signal fires
RISK_OFF_EQUITY_WEIGHT = 0.25  # Reduce SPY from 50% to 25% when triggered
NORMAL_EQUITY_WEIGHT = 0.50    # Normal: 50% SPY

# 5-period cross-validation
OOS_PERIODS = [
    ("2005-01-03", "2008-12-31", "P1_GFC"),
    ("2009-01-02", "2012-12-31", "P2_Recovery"),
    ("2013-01-02", "2016-12-31", "P3_LowVol"),
    ("2017-01-03", "2020-12-31", "P4_COVID"),
    ("2021-01-04", "2024-12-31", "P5_RateHikes"),
]

print("=" * 80)
print("K306: VIX SPEED AS BINARY RISK TRIGGER — 5-PERIOD CROSS-OOS")
print("    [提出: 用戶, 執行: Claude]")
print("=" * 80)
print(f"  Thresholds: {THRESHOLDS}")
print(f"  Risk-off equity weight: {RISK_OFF_EQUITY_WEIGHT}")
print(f"  TX cost: {TX_COST_BPS} bps one-way")
print(f"  VT target vol: {TARGET_VOL_ANNUAL*100:.0f}%")
print()


# ==================================================================
# DATA LOADING
# ==================================================================
print("[1/5] Loading data from yfinance...")
t0 = time.time()

tickers = ["SPY", "GLD", "^VIX"]
raw = {}
for t in tickers:
    d = yf.download(t, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    raw[t] = d[["Close"]].rename(columns={"Close": t.replace("^", "")})

df = raw["SPY"].join(raw["GLD"], how="inner").join(raw["^VIX"], how="inner").dropna()

# Log returns
df["SPY_ret"] = np.log(df["SPY"] / df["SPY"].shift(1))
df["GLD_ret"] = np.log(df["GLD"] / df["GLD"].shift(1))
df = df.dropna()

# VIX speed z-score: (VIX - MA20) / std20
df["VIX_MA"] = df["VIX"].rolling(window=VIX_MA_WINDOW, min_periods=VIX_MA_WINDOW).mean()
df["VIX_STD"] = df["VIX"].rolling(window=VIX_MA_WINDOW, min_periods=VIX_MA_WINDOW).std()
df["VIX_speed"] = (df["VIX"] - df["VIX_MA"]) / df["VIX_STD"].clip(lower=0.01)

# Rolling realized vol for VT (EWMA proxy using 60d window)
df["SPY_rv60"] = df["SPY_ret"].rolling(60).std() * np.sqrt(252)
df["GLD_rv60"] = df["GLD_ret"].rolling(60).std() * np.sqrt(252)

df = df.dropna()

print(f"  Data range: {df.index[0].date()} to {df.index[-1].date()}")
print(f"  Total observations: {len(df)}")
print(f"  VIX speed stats: mean={df['VIX_speed'].mean():.3f}, std={df['VIX_speed'].std():.3f}")
print(f"  Time: {time.time()-t0:.1f}s")
print()


# ==================================================================
# STRATEGY SIMULATION ENGINE
# ==================================================================

def compute_metrics(daily_returns, name="Strategy"):
    """Compute strategy metrics from daily log returns."""
    if len(daily_returns) < 30:
        return {"name": name, "error": "insufficient data"}

    dr = np.array(daily_returns)

    # Annualized return
    cum_ret = np.exp(np.sum(dr)) - 1
    n_years = len(dr) / 252
    ann_ret = (1 + cum_ret) ** (1 / max(n_years, 0.01)) - 1

    # Annualized vol
    ann_vol = np.std(dr) * np.sqrt(252)

    # Sharpe
    sharpe = (ann_ret - RF_ANNUAL) / max(ann_vol, 1e-8)

    # Max drawdown
    cum = np.cumsum(dr)
    running_max = np.maximum.accumulate(cum)
    drawdowns = cum - running_max
    mdd = float(np.min(drawdowns))
    mdd_pct = np.exp(mdd) - 1  # Convert log DD to pct

    # Calmar
    calmar = ann_ret / max(abs(mdd_pct), 1e-8)

    # Sortino
    downside = dr[dr < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 5 else ann_vol
    sortino = (ann_ret - RF_ANNUAL) / max(downside_vol, 1e-8)

    return {
        "name": name,
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd_pct": float(mdd_pct),
        "calmar": float(calmar),
        "sortino": float(sortino),
        "cum_ret": float(cum_ret),
        "n_days": len(dr),
        "n_years": float(n_years),
    }


def simulate_portfolio(df_period, strategy_type, threshold=1.0):
    """
    Simulate a portfolio over the given period.

    strategy_type:
      'bh'         → 50/50 buy-and-hold, monthly rebalance
      'trigger'    → 50/50 + VIX speed trigger (reduce equity when signal fires)
      'vt'         → 50/50 + Volatility Targeting (scale by realized vol)
      'vt_trigger' → 50/50 + VT + VIX speed overlay

    Returns: dict with daily returns, metrics, and trade count.
    """
    n = len(df_period)
    dates = df_period.index
    spy_ret = df_period["SPY_ret"].values
    gld_ret = df_period["GLD_ret"].values
    vix_speed = df_period["VIX_speed"].values
    spy_vol = df_period["SPY_rv60"].values
    gld_vol = df_period["GLD_rv60"].values

    daily_returns = []
    w_spy_prev = NORMAL_EQUITY_WEIGHT
    w_gld_prev = 1.0 - NORMAL_EQUITY_WEIGHT
    n_trades = 0
    signal_days = 0

    for i in range(n):
        # ============================================================
        # CRITICAL: Use LAGGED signal (yesterday's VIX speed) to avoid
        # same-day timing bias. VIX close[t] is simultaneous with SPY
        # close[t], so using vix_speed[t] to decide weight for return[t]
        # would be look-ahead bias.
        # For VT, use lagged vol estimate (yesterday's 60d vol) which is
        # also known at close of day t-1.
        # ============================================================
        lagged_vix_speed = vix_speed[i - 1] if i > 0 else 0.0
        lagged_spy_vol = spy_vol[i - 1] if i > 0 else spy_vol[i]
        lagged_gld_vol = gld_vol[i - 1] if i > 0 else gld_vol[i]

        # Determine target weights
        if strategy_type == "bh":
            w_spy_target = NORMAL_EQUITY_WEIGHT
            w_gld_target = 1.0 - NORMAL_EQUITY_WEIGHT

        elif strategy_type == "trigger":
            # Binary trigger: if LAGGED VIX speed z-score > threshold, reduce equity
            if lagged_vix_speed > threshold:
                w_spy_target = RISK_OFF_EQUITY_WEIGHT
                w_gld_target = 1.0 - RISK_OFF_EQUITY_WEIGHT
                signal_days += 1
            else:
                w_spy_target = NORMAL_EQUITY_WEIGHT
                w_gld_target = 1.0 - NORMAL_EQUITY_WEIGHT

        elif strategy_type == "vt":
            # Volatility Targeting: scale each asset using LAGGED vol
            spy_scale = TARGET_VOL_ANNUAL / max(lagged_spy_vol, 0.01)
            gld_scale = TARGET_VOL_ANNUAL / max(lagged_gld_vol, 0.01)
            spy_scale = np.clip(spy_scale, 0.1, MAX_LEVERAGE)
            gld_scale = np.clip(gld_scale, 0.1, MAX_LEVERAGE)

            w_spy_target = NORMAL_EQUITY_WEIGHT * spy_scale
            w_gld_target = (1.0 - NORMAL_EQUITY_WEIGHT) * gld_scale

            # Normalize so total weight <= 1 (no leverage in aggregate for fair comparison)
            total = w_spy_target + w_gld_target
            if total > 1.0:
                w_spy_target /= total
                w_gld_target /= total

        elif strategy_type == "vt_trigger":
            # VT + binary trigger overlay (all signals LAGGED)
            spy_scale = TARGET_VOL_ANNUAL / max(lagged_spy_vol, 0.01)
            gld_scale = TARGET_VOL_ANNUAL / max(lagged_gld_vol, 0.01)
            spy_scale = np.clip(spy_scale, 0.1, MAX_LEVERAGE)
            gld_scale = np.clip(gld_scale, 0.1, MAX_LEVERAGE)

            w_spy_target = NORMAL_EQUITY_WEIGHT * spy_scale
            w_gld_target = (1.0 - NORMAL_EQUITY_WEIGHT) * gld_scale

            # Normalize
            total = w_spy_target + w_gld_target
            if total > 1.0:
                w_spy_target /= total
                w_gld_target /= total

            # Overlay: if LAGGED VIX speed trigger fires, cut equity further
            if lagged_vix_speed > threshold:
                saved_spy = w_spy_target
                w_spy_target *= 0.5  # Halve equity exposure
                # Redistribute to GLD (cash equivalent in this context)
                w_gld_target = min(1.0, w_gld_target + (saved_spy - w_spy_target))
                signal_days += 1
        else:
            raise ValueError(f"Unknown strategy: {strategy_type}")

        # Monthly rebalance OR immediate trigger/VT override
        is_month_start = (i == 0) or (dates[i].month != dates[i-1].month)
        weight_changed = (abs(w_spy_target - w_spy_prev) > 0.01 or
                          abs(w_gld_target - w_gld_prev) > 0.01)

        # For trigger/vt/vt_trigger: rebalance whenever signal changes
        # For bh: only rebalance monthly
        should_rebalance = is_month_start or (
            weight_changed and strategy_type in ("trigger", "vt", "vt_trigger")
        )

        if should_rebalance:
            # Transaction cost: proportional to weight change
            turnover = abs(w_spy_target - w_spy_prev) + abs(w_gld_target - w_gld_prev)
            tx_cost = turnover * TX_COST_BPS / 10000
            n_trades += 1
        else:
            tx_cost = 0
            w_spy_target = w_spy_prev
            w_gld_target = w_gld_prev

        # Daily portfolio return
        port_ret = w_spy_target * spy_ret[i] + w_gld_target * gld_ret[i] - tx_cost
        daily_returns.append(port_ret)

        # Drift weights (approximate — weights change due to returns)
        # For next day, estimate drifted weights
        spy_growth = np.exp(spy_ret[i])
        gld_growth = np.exp(gld_ret[i])
        total_val = w_spy_target * spy_growth + w_gld_target * gld_growth
        if total_val > 0:
            w_spy_prev = w_spy_target * spy_growth / total_val
            w_gld_prev = w_gld_target * gld_growth / total_val
        else:
            w_spy_prev = w_spy_target
            w_gld_prev = w_gld_target

    metrics = compute_metrics(daily_returns,
                              f"{strategy_type}{'_t'+str(threshold) if 'trigger' in strategy_type else ''}")
    metrics["n_trades"] = n_trades
    metrics["trades_per_year"] = n_trades / max(metrics.get("n_years", 1), 0.01)
    metrics["signal_days"] = signal_days
    metrics["signal_pct"] = signal_days / max(n, 1) * 100

    # Net Sharpe (after TX)
    metrics["net_sharpe"] = metrics["sharpe"]  # TX already deducted in daily returns

    return {
        "daily_returns": daily_returns,
        "metrics": metrics,
    }


# ==================================================================
# RUN 5-PERIOD CROSS-OOS VALIDATION
# ==================================================================
print("[2/5] Running 5-period cross-OOS validation...")
print("=" * 80)

all_results = {}

for period_start, period_end, period_name in OOS_PERIODS:
    print(f"\n{'='*60}")
    print(f"  Period: {period_name} ({period_start} to {period_end})")
    print(f"{'='*60}")

    mask = (df.index >= period_start) & (df.index <= period_end)
    df_p = df[mask].copy()

    if len(df_p) < 100:
        print(f"  WARNING: Only {len(df_p)} observations, skipping.")
        continue

    print(f"  Observations: {len(df_p)}")
    print(f"  VIX range: {df_p['VIX'].min():.1f} - {df_p['VIX'].max():.1f}")

    period_results = {}

    # 1. Benchmark: 50/50 B&H
    res_bh = simulate_portfolio(df_p, "bh")
    period_results["bh"] = res_bh["metrics"]
    print(f"\n  50/50 B&H:    Sharpe={res_bh['metrics']['sharpe']:+.3f}  "
          f"MDD={res_bh['metrics']['mdd_pct']*100:+.1f}%  "
          f"AnnRet={res_bh['metrics']['ann_ret']*100:+.1f}%  "
          f"Trades/yr={res_bh['metrics']['trades_per_year']:.0f}")

    # 2. VT only (no trigger)
    res_vt = simulate_portfolio(df_p, "vt")
    period_results["vt"] = res_vt["metrics"]
    print(f"  50/50 + VT:   Sharpe={res_vt['metrics']['sharpe']:+.3f}  "
          f"MDD={res_vt['metrics']['mdd_pct']*100:+.1f}%  "
          f"AnnRet={res_vt['metrics']['ann_ret']*100:+.1f}%  "
          f"Trades/yr={res_vt['metrics']['trades_per_year']:.0f}")

    # 3. Trigger at each threshold
    for thresh in THRESHOLDS:
        res_trig = simulate_portfolio(df_p, "trigger", threshold=thresh)
        key = f"trigger_{thresh}"
        period_results[key] = res_trig["metrics"]
        print(f"  Trigger t={thresh}: Sharpe={res_trig['metrics']['sharpe']:+.3f}  "
              f"MDD={res_trig['metrics']['mdd_pct']*100:+.1f}%  "
              f"AnnRet={res_trig['metrics']['ann_ret']*100:+.1f}%  "
              f"Signal={res_trig['metrics']['signal_pct']:.1f}%  "
              f"Trades/yr={res_trig['metrics']['trades_per_year']:.0f}")

    # 4. VT + trigger overlay at each threshold
    for thresh in THRESHOLDS:
        res_vt_trig = simulate_portfolio(df_p, "vt_trigger", threshold=thresh)
        key = f"vt_trigger_{thresh}"
        period_results[key] = res_vt_trig["metrics"]
        print(f"  VT+Trig t={thresh}: Sharpe={res_vt_trig['metrics']['sharpe']:+.3f}  "
              f"MDD={res_vt_trig['metrics']['mdd_pct']*100:+.1f}%  "
              f"AnnRet={res_vt_trig['metrics']['ann_ret']*100:+.1f}%  "
              f"Signal={res_vt_trig['metrics']['signal_pct']:.1f}%  "
              f"Trades/yr={res_vt_trig['metrics']['trades_per_year']:.0f}")

    all_results[period_name] = period_results


# ==================================================================
# POOLED FULL-SAMPLE ANALYSIS
# ==================================================================
print("\n\n[3/5] Full-sample pooled analysis (2005-2024)...")
print("=" * 80)

mask_full = (df.index >= "2005-01-03") & (df.index <= "2024-12-31")
df_full = df[mask_full].copy()
print(f"  Full OOS: {df_full.index[0].date()} to {df_full.index[-1].date()} ({len(df_full)} days)")

full_results = {}

# B&H
res_bh_full = simulate_portfolio(df_full, "bh")
full_results["bh"] = res_bh_full

# VT
res_vt_full = simulate_portfolio(df_full, "vt")
full_results["vt"] = res_vt_full

# Triggers
for thresh in THRESHOLDS:
    res = simulate_portfolio(df_full, "trigger", threshold=thresh)
    full_results[f"trigger_{thresh}"] = res

# VT + triggers
for thresh in THRESHOLDS:
    res = simulate_portfolio(df_full, "vt_trigger", threshold=thresh)
    full_results[f"vt_trigger_{thresh}"] = res


# ==================================================================
# CROSS-PERIOD CONSISTENCY ANALYSIS
# ==================================================================
print("\n\n[4/5] Cross-Period Consistency Analysis")
print("=" * 80)

strategies_to_check = (
    ["bh", "vt"] +
    [f"trigger_{t}" for t in THRESHOLDS] +
    [f"vt_trigger_{t}" for t in THRESHOLDS]
)

# Build a comparison table
print("\n  Strategy Sharpe by Period:")
header = f"  {'Strategy':<20s}"
for _, _, pname in OOS_PERIODS:
    header += f"  {pname:>12s}"
header += f"  {'Pooled':>10s}  {'Wins':>6s}"
print(header)
print("  " + "-" * (len(header) - 2))

consistency_data = {}

for strat in strategies_to_check:
    line = f"  {strat:<20s}"
    sharpes = []
    for _, _, pname in OOS_PERIODS:
        if pname in all_results and strat in all_results[pname]:
            s = all_results[pname][strat]["sharpe"]
            sharpes.append(s)
            line += f"  {s:>+12.3f}"
        else:
            line += f"  {'N/A':>12s}"

    # Pooled
    if strat in full_results:
        pooled_sharpe = full_results[strat]["metrics"]["sharpe"]
        line += f"  {pooled_sharpe:>+10.3f}"
    else:
        pooled_sharpe = float("nan")
        line += f"  {'N/A':>10s}"

    # Count periods where this beats B&H
    bh_sharpes = []
    for _, _, pname in OOS_PERIODS:
        if pname in all_results and "bh" in all_results[pname]:
            bh_sharpes.append(all_results[pname]["bh"]["sharpe"])

    wins = sum(1 for s, b in zip(sharpes, bh_sharpes) if s > b)
    line += f"  {wins}/5"

    print(line)

    consistency_data[strat] = {
        "sharpes": sharpes,
        "pooled_sharpe": pooled_sharpe,
        "wins_vs_bh": wins,
    }


# MDD comparison
print("\n\n  Strategy MDD by Period:")
header = f"  {'Strategy':<20s}"
for _, _, pname in OOS_PERIODS:
    header += f"  {pname:>12s}"
header += f"  {'Pooled':>10s}  {'Wins':>6s}"
print(header)
print("  " + "-" * (len(header) - 2))

for strat in strategies_to_check:
    line = f"  {strat:<20s}"
    mdds = []
    for _, _, pname in OOS_PERIODS:
        if pname in all_results and strat in all_results[pname]:
            m = all_results[pname][strat]["mdd_pct"]
            mdds.append(m)
            line += f"  {m*100:>+11.1f}%"
        else:
            line += f"  {'N/A':>12s}"

    # Pooled
    if strat in full_results:
        pooled_mdd = full_results[strat]["metrics"]["mdd_pct"]
        line += f"  {pooled_mdd*100:>+9.1f}%"
    else:
        pooled_mdd = float("nan")
        line += f"  {'N/A':>10s}"

    # Count periods where MDD is better (less negative) than B&H
    bh_mdds = []
    for _, _, pname in OOS_PERIODS:
        if pname in all_results and "bh" in all_results[pname]:
            bh_mdds.append(all_results[pname]["bh"]["mdd_pct"])

    wins = sum(1 for m, b in zip(mdds, bh_mdds) if m > b)  # Less negative = better
    line += f"  {wins}/5"

    print(line)


# ==================================================================
# STATISTICAL TESTS: Is trigger/VT return distribution different?
# ==================================================================
print("\n\n[5/5] Statistical Significance Tests")
print("=" * 80)

print("\n  Paired t-test on daily returns (strategy - B&H) across full pooled period:")
print(f"  {'Strategy':<20s}  {'Mean diff':>12s}  {'t-stat':>10s}  {'p-value':>10s}  {'Significant':>12s}")
print("  " + "-" * 70)

bh_daily = full_results["bh"]["daily_returns"]

for strat in strategies_to_check:
    if strat == "bh" or strat not in full_results:
        continue

    strat_daily = full_results[strat]["daily_returns"]

    if len(strat_daily) != len(bh_daily):
        print(f"  {strat:<20s}  Length mismatch!")
        continue

    diff = np.array(strat_daily) - np.array(bh_daily)

    # Newey-West HAC t-test
    T = len(diff)
    d_bar = np.mean(diff)
    max_lag = max(1, int(np.floor(T ** (1/3))))
    gamma_0 = np.mean((diff - d_bar) ** 2)
    V = gamma_0
    for k in range(1, max_lag + 1):
        w_k = 1.0 - k / (max_lag + 1)
        gamma_k = np.mean((diff[k:] - d_bar) * (diff[:-k] - d_bar))
        V += 2 * w_k * gamma_k
    V = max(V, 1e-20)
    t_stat = d_bar / np.sqrt(V / T)
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))

    sig = "***" if abs(t_stat) > 3.0 else ("*" if p_val < 0.05 else "")

    print(f"  {strat:<20s}  {d_bar*10000:>+10.2f}bp  {t_stat:>+10.3f}  {p_val:>10.4f}  {sig:>12s}")


# ==================================================================
# KEY QUESTION: Is VIX speed trigger REDUNDANT with VT?
# ==================================================================
print("\n\n" + "=" * 80)
print("KEY ANALYSIS: VIX Speed Trigger vs. VT — Redundant or Complementary?")
print("=" * 80)

best_trigger_thresh = None
best_trigger_sharpe = -999

for thresh in THRESHOLDS:
    key = f"trigger_{thresh}"
    if key in full_results:
        s = full_results[key]["metrics"]["sharpe"]
        if s > best_trigger_sharpe:
            best_trigger_sharpe = s
            best_trigger_thresh = thresh

best_vt_trigger_thresh = None
best_vt_trigger_sharpe = -999

for thresh in THRESHOLDS:
    key = f"vt_trigger_{thresh}"
    if key in full_results:
        s = full_results[key]["metrics"]["sharpe"]
        if s > best_vt_trigger_sharpe:
            best_vt_trigger_sharpe = s
            best_vt_trigger_thresh = thresh

bh_m = full_results["bh"]["metrics"]
vt_m = full_results["vt"]["metrics"]
trig_m = full_results[f"trigger_{best_trigger_thresh}"]["metrics"]
vt_trig_m = full_results[f"vt_trigger_{best_vt_trigger_thresh}"]["metrics"]

print(f"\n  Best trigger threshold: {best_trigger_thresh}")
print(f"  Best VT+trigger threshold: {best_vt_trigger_thresh}")

print(f"\n  {'Metric':<20s}  {'50/50 BH':>12s}  {'VT Only':>12s}  {'Trigger':>12s}  {'VT+Trigger':>12s}")
print("  " + "-" * 72)

for metric, is_pct, is_already_pct in [
    ("ann_ret", True, False),
    ("ann_vol", True, False),
    ("sharpe", False, False),
    ("mdd_pct", True, False),
    ("calmar", False, False),
    ("sortino", False, False),
    ("trades_per_year", False, False),
    ("signal_pct", True, True),  # Already in % units
]:
    line = f"  {metric:<20s}"
    for m in [bh_m, vt_m, trig_m, vt_trig_m]:
        val = m.get(metric, 0)
        if is_pct and not is_already_pct:
            line += f"  {val*100:>+11.1f}%"
        elif is_already_pct:
            line += f"  {val:>+11.1f}%"
        else:
            line += f"  {val:>+12.3f}"
    print(line)


# Marginal contribution analysis
print("\n  Marginal Contribution Analysis:")
print(f"    VT alone adds to B&H Sharpe:        {vt_m['sharpe'] - bh_m['sharpe']:+.3f}")
print(f"    Trigger alone adds to B&H Sharpe:    {trig_m['sharpe'] - bh_m['sharpe']:+.3f}")
print(f"    VT+Trigger adds to B&H Sharpe:       {vt_trig_m['sharpe'] - bh_m['sharpe']:+.3f}")
print(f"    VT+Trigger adds to VT-only Sharpe:   {vt_trig_m['sharpe'] - vt_m['sharpe']:+.3f} (MARGINAL)")

print(f"\n    VT alone MDD improvement:            {(vt_m['mdd_pct'] - bh_m['mdd_pct'])*100:+.1f}pp")
print(f"    Trigger alone MDD improvement:       {(trig_m['mdd_pct'] - bh_m['mdd_pct'])*100:+.1f}pp")
print(f"    VT+Trigger MDD improvement:          {(vt_trig_m['mdd_pct'] - bh_m['mdd_pct'])*100:+.1f}pp")
print(f"    VT+Trigger adds to VT MDD:           {(vt_trig_m['mdd_pct'] - vt_m['mdd_pct'])*100:+.1f}pp (MARGINAL)")

# Redundancy test: correlation of daily return differences
vt_diff = np.array(full_results["vt"]["daily_returns"]) - np.array(bh_daily)
trig_diff = np.array(full_results[f"trigger_{best_trigger_thresh}"]["daily_returns"]) - np.array(bh_daily)
corr_signals = np.corrcoef(vt_diff, trig_diff)[0, 1]
print(f"\n    Correlation of return diffs (VT vs Trigger, relative to B&H): {corr_signals:+.3f}")
if abs(corr_signals) > 0.7:
    print("    → HIGH correlation → signals are LARGELY REDUNDANT")
elif abs(corr_signals) > 0.3:
    print("    → MODERATE correlation → signals are PARTIALLY OVERLAPPING")
else:
    print("    → LOW correlation → signals are COMPLEMENTARY (different information)")


# ==================================================================
# CROSS-OOS CONSISTENCY VERDICT
# ==================================================================
print("\n\n" + "=" * 80)
print("CROSS-OOS CONSISTENCY VERDICT")
print("=" * 80)

for strat in strategies_to_check:
    if strat == "bh":
        continue

    cd = consistency_data.get(strat, {})
    wins = cd.get("wins_vs_bh", 0)
    pooled = cd.get("pooled_sharpe", float("nan"))
    sharpes = cd.get("sharpes", [])

    # Count periods with positive Sharpe
    pos_periods = sum(1 for s in sharpes if s > 0)

    # Consistency: do all periods agree on sign of improvement vs B&H?
    bh_sharpes_list = []
    for _, _, pname in OOS_PERIODS:
        if pname in all_results and "bh" in all_results[pname]:
            bh_sharpes_list.append(all_results[pname]["bh"]["sharpe"])

    improvements = [s - b for s, b in zip(sharpes, bh_sharpes_list)]
    consistent_sign = all(x > 0 for x in improvements) or all(x < 0 for x in improvements)

    verdict = "PASS" if wins >= 3 and not np.isnan(pooled) else "FAIL"

    print(f"\n  {strat}:")
    print(f"    Wins vs B&H: {wins}/5")
    print(f"    Positive Sharpe periods: {pos_periods}/5")
    print(f"    Consistent sign: {'Yes' if consistent_sign else 'No'}")
    print(f"    Pooled Sharpe: {pooled:+.3f}")
    print(f"    Verdict: {verdict}")


# ==================================================================
# SAVE RESULTS
# ==================================================================
print("\n\n" + "=" * 80)
print("SAVING RESULTS")
print("=" * 80)

output = {
    "experiment": "K306",
    "title": "VIX Speed as Binary Risk Trigger — 5-Period Cross-OOS",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{df.index[0].date()} to {df.index[-1].date()}",
    "methodology": {
        "signal": "VIX 20d z-score > threshold → reduce equity to 25%",
        "base_portfolio": "50/50 SPY/GLD monthly rebalance",
        "vt_method": "60d realized vol → scale to 10% target, max leverage 1.5x",
        "tx_cost_bps": TX_COST_BPS,
        "thresholds_tested": THRESHOLDS,
    },
    "full_sample_metrics": {},
    "period_metrics": {},
    "consistency": {},
    "key_findings": {},
}

# Full sample
for strat in strategies_to_check:
    if strat in full_results:
        output["full_sample_metrics"][strat] = full_results[strat]["metrics"]

# Period metrics
for _, _, pname in OOS_PERIODS:
    if pname in all_results:
        output["period_metrics"][pname] = {}
        for strat in strategies_to_check:
            if strat in all_results[pname]:
                output["period_metrics"][pname][strat] = all_results[pname][strat]

# Consistency
for strat in strategies_to_check:
    output["consistency"][strat] = consistency_data.get(strat, {})

# Key findings
output["key_findings"] = {
    "best_trigger_threshold": best_trigger_thresh,
    "best_vt_trigger_threshold": best_vt_trigger_thresh,
    "vt_vs_bh_sharpe_improvement": float(vt_m["sharpe"] - bh_m["sharpe"]),
    "trigger_vs_bh_sharpe_improvement": float(trig_m["sharpe"] - bh_m["sharpe"]),
    "vt_trigger_vs_vt_sharpe_improvement": float(vt_trig_m["sharpe"] - vt_m["sharpe"]),
    "signal_correlation": float(corr_signals),
    "redundancy_assessment": (
        "largely_redundant" if abs(corr_signals) > 0.7 else
        "partially_overlapping" if abs(corr_signals) > 0.3 else
        "complementary"
    ),
}

# Clean NaN for JSON serialization
def clean_for_json(obj):
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_for_json(v) for v in obj]
    elif isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    elif isinstance(obj, (np.floating, np.integer)):
        v = float(obj)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    return obj

output_clean = clean_for_json(output)

results_path = os.path.join(os.path.dirname(__file__), "k306_vix_speed_trigger_results.json")
with open(results_path, "w") as f:
    json.dump(output_clean, f, indent=2, default=str)

print(f"  Results saved to: {results_path}")


# ==================================================================
# FINAL SUMMARY
# ==================================================================
print("\n\n" + "=" * 80)
print("K306 FINAL SUMMARY")
print("=" * 80)

print(f"""
  DATA: SPY + GLD + VIX from yfinance ({df.index[0].date()} to {df.index[-1].date()})

  FULL-SAMPLE METRICS (2005-2024):
    50/50 B&H:         Sharpe={bh_m['sharpe']:+.3f}  MDD={bh_m['mdd_pct']*100:+.1f}%  Ret={bh_m['ann_ret']*100:+.1f}%
    50/50 + VT:        Sharpe={vt_m['sharpe']:+.3f}  MDD={vt_m['mdd_pct']*100:+.1f}%  Ret={vt_m['ann_ret']*100:+.1f}%
    Trigger (t={best_trigger_thresh}):   Sharpe={trig_m['sharpe']:+.3f}  MDD={trig_m['mdd_pct']*100:+.1f}%  Ret={trig_m['ann_ret']*100:+.1f}%
    VT+Trigger (t={best_vt_trigger_thresh}): Sharpe={vt_trig_m['sharpe']:+.3f}  MDD={vt_trig_m['mdd_pct']*100:+.1f}%  Ret={vt_trig_m['ann_ret']*100:+.1f}%

  MARGINAL VALUE OF TRIGGER:
    Over B&H: Sharpe {trig_m['sharpe'] - bh_m['sharpe']:+.3f}, MDD {(trig_m['mdd_pct']-bh_m['mdd_pct'])*100:+.1f}pp
    Over VT:  Sharpe {vt_trig_m['sharpe'] - vt_m['sharpe']:+.3f}, MDD {(vt_trig_m['mdd_pct']-vt_m['mdd_pct'])*100:+.1f}pp
    Signal correlation with VT: {corr_signals:+.3f}

  CROSS-OOS CONSISTENCY:
    Trigger wins vs B&H: {consistency_data.get(f'trigger_{best_trigger_thresh}', {}).get('wins_vs_bh', '?')}/5
    VT+Trigger wins vs B&H: {consistency_data.get(f'vt_trigger_{best_vt_trigger_thresh}', {}).get('wins_vs_bh', '?')}/5
""")

print("K306 COMPLETE.")
