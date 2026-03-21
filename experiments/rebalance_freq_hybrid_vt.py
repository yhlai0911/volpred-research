"""
Hybrid VT Rebalancing Frequency Analysis
=========================================
Compare Daily / Weekly (Friday) / Monthly (1st trading day) rebalancing
for Hybrid VT strategy using GJR-GARCH with w=2000.

Switch to VIX-based weight when VIX/GARCH ratio > 1.3
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from datetime import datetime

# ------------------------------------------------------------------
# 1. Download data
# ------------------------------------------------------------------
print("=" * 70)
print("Hybrid VT Rebalancing Frequency Analysis")
print("=" * 70)
print("\n[1/4] Downloading SPY and VIX data (2006-2026)...")

spy_raw = yf.download("SPY", start="2006-01-01", end="2026-12-31", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2006-01-01", end="2026-12-31", progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(vix, how="inner").dropna()
data["returns"] = np.log(data["spy_close"] / data["spy_close"].shift(1))
data = data.dropna()

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")

# ------------------------------------------------------------------
# 2. Rolling GJR-GARCH forecast (w=2000)
# ------------------------------------------------------------------
print("\n[2/4] Running rolling GJR-GARCH(1,1,1) with w=2000...")

WINDOW = 2000
THRESHOLD = 1.3
RF_DAILY = 0.04 / 252  # risk-free rate (approx 4% annual)

# OOS starts after first WINDOW days
oos_start_idx = WINDOW
oos_dates = data.index[oos_start_idx:]
returns_all = data["returns"].values
vix_all = data["vix_close"].values

print(f"  OOS start: {oos_dates[0].date()}")
print(f"  OOS end:   {oos_dates[-1].date()}")
print(f"  OOS days:  {len(oos_dates)}")

# Pre-compute all GARCH forecasts
garch_vol = np.full(len(data), np.nan)
n_total = len(oos_dates)
report_every = max(1, n_total // 20)

for i in range(n_total):
    idx = oos_start_idx + i
    window_returns = returns_all[idx - WINDOW:idx] * 100  # pct for arch

    try:
        model = arch_model(window_returns, vol="GARCH", p=1, o=1, q=1,
                          dist="t", mean="Zero", rescale=False)
        result = model.fit(disp="off", show_warning=False)
        fcast = result.forecast(horizon=1)
        var_pct = fcast.variance.iloc[-1, 0]
        garch_vol[idx] = np.sqrt(var_pct / 10000)  # convert back to decimal
    except Exception:
        # Fallback: use expanding window std
        garch_vol[idx] = np.std(returns_all[idx - WINDOW:idx])

    if (i + 1) % report_every == 0:
        pct = (i + 1) / n_total * 100
        print(f"    Progress: {pct:.0f}% ({i+1}/{n_total})")

print("  GARCH forecasts complete.")

# Add GARCH vol to dataframe
data["garch_vol"] = garch_vol
data["vix_daily"] = data["vix_close"] / 100 / np.sqrt(252)  # VIX to daily vol
data["ratio"] = data["vix_daily"] / data["garch_vol"]

# ------------------------------------------------------------------
# 3. VT weight computation
# ------------------------------------------------------------------
print("\n[3/4] Computing strategy signals and portfolio returns...")

# Target volatility: 10% annualized -> daily
TARGET_VOL_ANNUAL = 0.10
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)

# GARCH-based weight
data["w_garch"] = TARGET_VOL_DAILY / data["garch_vol"]
data["w_garch"] = data["w_garch"].clip(0, 1.5)  # max leverage 1.5x

# VIX-based weight
data["w_vix"] = TARGET_VOL_DAILY / data["vix_daily"]
data["w_vix"] = data["w_vix"].clip(0, 1.5)

# Hybrid weight: use VIX when ratio > threshold
data["w_hybrid"] = np.where(data["ratio"] > THRESHOLD, data["w_vix"], data["w_garch"])

# Focus on OOS period only
oos = data.iloc[oos_start_idx:].copy()
print(f"  OOS period: {oos.index[0].date()} to {oos.index[-1].date()} ({len(oos)} days)")

# ------------------------------------------------------------------
# Identify rebalancing days
# ------------------------------------------------------------------
# Daily: every day
oos["rebal_daily"] = True

# Weekly: every Friday (weekday == 4)
oos["rebal_weekly"] = oos.index.weekday == 4

# Monthly: first trading day of each month
oos["month_key"] = oos.index.to_period("M")
first_days = oos.groupby("month_key").head(1).index
oos["rebal_monthly"] = oos.index.isin(first_days)


def run_strategy(oos_df, rebal_col, strategy_name):
    """Run Hybrid VT with given rebalancing schedule."""
    n = len(oos_df)
    weights = np.zeros(n)
    port_returns = np.zeros(n)
    n_trades = 0

    current_w = oos_df["w_hybrid"].iloc[0]
    weights[0] = current_w
    port_returns[0] = current_w * oos_df["returns"].iloc[0]

    for t in range(1, n):
        if oos_df[rebal_col].iloc[t]:
            new_w = oos_df["w_hybrid"].iloc[t]
            if abs(new_w - current_w) > 0.001:
                n_trades += 1
            current_w = new_w
        weights[t] = current_w
        port_returns[t] = current_w * oos_df["returns"].iloc[t]

    # Compute metrics
    cum_ret = np.exp(np.cumsum(port_returns))
    total_years = n / 252

    ann_ret = (cum_ret[-1] ** (1 / total_years)) - 1
    ann_vol = np.std(port_returns) * np.sqrt(252)
    sharpe = (np.mean(port_returns) - RF_DAILY) / np.std(port_returns) * np.sqrt(252)

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = cum_ret / running_max - 1
    max_dd = np.min(drawdowns)

    # Annual turnover: sum of abs weight changes / years
    weight_changes = np.abs(np.diff(weights))
    ann_turnover = np.sum(weight_changes) / total_years * 100  # as percentage

    # Win rate (monthly)
    monthly_rets = pd.Series(port_returns, index=oos_df.index).resample("ME").sum()
    win_rate = (monthly_rets > 0).mean()

    # Calmar ratio
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else np.inf

    # Sortino ratio
    downside = port_returns[port_returns < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else 1e-6
    sortino = (ann_ret - 0.04) / downside_vol

    # Average weight
    avg_weight = np.mean(weights)

    # Number of days in VIX mode
    vix_mode_pct = (oos_df["ratio"] > THRESHOLD).mean() * 100

    return {
        "strategy": strategy_name,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "sortino": sortino,
        "ann_turnover": ann_turnover,
        "n_trades": n_trades,
        "trades_per_year": n_trades / total_years,
        "win_rate_monthly": win_rate,
        "avg_weight": avg_weight,
        "total_growth": cum_ret[-1],
        "total_years": total_years,
        "cum_returns": cum_ret,
        "port_returns": port_returns,
        "weights": weights,
    }


# Run all three strategies
results = {}
for rebal_col, name in [
    ("rebal_daily", "Daily Hybrid VT"),
    ("rebal_weekly", "Weekly Hybrid VT (Fri)"),
    ("rebal_monthly", "Monthly Hybrid VT"),
]:
    print(f"  Running {name}...")
    results[name] = run_strategy(oos, rebal_col, name)

# Also run Buy & Hold for reference
bh_returns = oos["returns"].values
bh_cum = np.exp(np.cumsum(bh_returns))
bh_years = len(oos) / 252
bh_ann_ret = (bh_cum[-1] ** (1 / bh_years)) - 1
bh_ann_vol = np.std(bh_returns) * np.sqrt(252)
bh_sharpe = (np.mean(bh_returns) - RF_DAILY) / np.std(bh_returns) * np.sqrt(252)
bh_running_max = np.maximum.accumulate(bh_cum)
bh_dd = bh_cum / bh_running_max - 1
bh_max_dd = np.min(bh_dd)

results["Buy & Hold (SPY)"] = {
    "strategy": "Buy & Hold (SPY)",
    "ann_return": bh_ann_ret,
    "ann_vol": bh_ann_vol,
    "sharpe": bh_sharpe,
    "max_dd": bh_max_dd,
    "calmar": bh_ann_ret / abs(bh_max_dd) if bh_max_dd != 0 else np.inf,
    "sortino": 0,
    "ann_turnover": 0,
    "n_trades": 0,
    "trades_per_year": 0,
    "win_rate_monthly": 0,
    "avg_weight": 1.0,
    "total_growth": bh_cum[-1],
    "total_years": bh_years,
}

# ------------------------------------------------------------------
# 4. Print results
# ------------------------------------------------------------------
print("\n[4/4] Results Summary")
print("=" * 70)

# Main comparison table
header = f"{'策略':<25} {'Sharpe':>8} {'年化報酬':>10} {'MaxDD':>10} {'年換手率':>10} {'年交易次數':>10}"
print(header)
print("-" * 73)

for name in ["Daily Hybrid VT", "Weekly Hybrid VT (Fri)", "Monthly Hybrid VT", "Buy & Hold (SPY)"]:
    r = results[name]
    print(f"{r['strategy']:<25} {r['sharpe']:>8.3f} {r['ann_return']:>9.1%} {r['max_dd']:>9.1%} {r['ann_turnover']:>9.0f}% {r.get('trades_per_year', 0):>10.0f}")

print()
print("Detailed Metrics:")
print("-" * 73)
for name in ["Daily Hybrid VT", "Weekly Hybrid VT (Fri)", "Monthly Hybrid VT"]:
    r = results[name]
    print(f"\n  {r['strategy']}:")
    print(f"    Sharpe:        {r['sharpe']:.3f}")
    print(f"    Ann. Return:   {r['ann_return']:.2%}")
    print(f"    Ann. Vol:      {r['ann_vol']:.2%}")
    print(f"    Max DD:        {r['max_dd']:.2%}")
    print(f"    Calmar:        {r['calmar']:.2f}")
    print(f"    Sortino:       {r['sortino']:.2f}")
    print(f"    Ann. Turnover: {r['ann_turnover']:.0f}%")
    print(f"    Trades/Year:   {r['trades_per_year']:.0f}")
    print(f"    Avg Weight:    {r['avg_weight']:.3f}")
    print(f"    Total Growth:  {r['total_growth']:.2f}x ($1M -> ${r['total_growth']*1_000_000:,.0f})")
    print(f"    Monthly Win%:  {r.get('win_rate_monthly', 0):.1%}")

# Yearly breakdown
print("\n\nYearly Sharpe Comparison:")
print("-" * 73)
yearly_header = f"{'年份':<8}"
for name in ["Daily Hybrid VT", "Weekly Hybrid VT (Fri)", "Monthly Hybrid VT"]:
    short = name.split("(")[0].strip() if "(" in name else name.replace(" Hybrid VT", "")
    yearly_header += f" {short:>14}"
print(yearly_header)

for name_key in ["Daily Hybrid VT", "Weekly Hybrid VT (Fri)", "Monthly Hybrid VT"]:
    r = results[name_key]
    r["_port_series"] = pd.Series(r["port_returns"], index=oos.index)

years = sorted(set(oos.index.year))
for yr in years:
    row = f"{yr:<8}"
    for name in ["Daily Hybrid VT", "Weekly Hybrid VT (Fri)", "Monthly Hybrid VT"]:
        r = results[name]
        yr_rets = r["_port_series"][r["_port_series"].index.year == yr]
        if len(yr_rets) > 20:
            yr_sharpe = (yr_rets.mean() - RF_DAILY) / yr_rets.std() * np.sqrt(252)
            row += f" {yr_sharpe:>14.2f}"
        else:
            row += f" {'N/A':>14}"
    print(row)

# Cost analysis
print("\n\nTransaction Cost Impact (10bps per trade):")
print("-" * 73)
COST_BPS = 10
for name in ["Daily Hybrid VT", "Weekly Hybrid VT (Fri)", "Monthly Hybrid VT"]:
    r = results[name]
    cost_drag = r["ann_turnover"] / 100 * COST_BPS / 10000  # turnover * cost per unit
    adj_return = r["ann_return"] - cost_drag
    adj_sharpe = (adj_return - 0.04) / r["ann_vol"]
    print(f"  {name:<25}: Cost drag {cost_drag:.2%}/yr, Adj Sharpe {adj_sharpe:.3f} (raw {r['sharpe']:.3f})")

print("\n" + "=" * 70)
print("Analysis complete.")
print("=" * 70)

# ------------------------------------------------------------------
# 5. Save summary dict for MemorySystem
# ------------------------------------------------------------------
summary = {
    "oos_start": str(oos.index[0].date()),
    "oos_end": str(oos.index[-1].date()),
    "oos_days": len(oos),
    "window": WINDOW,
    "threshold": THRESHOLD,
    "strategies": {}
}
for name in ["Daily Hybrid VT", "Weekly Hybrid VT (Fri)", "Monthly Hybrid VT"]:
    r = results[name]
    summary["strategies"][name] = {
        "sharpe": round(r["sharpe"], 3),
        "ann_return": round(r["ann_return"], 4),
        "ann_vol": round(r["ann_vol"], 4),
        "max_dd": round(r["max_dd"], 4),
        "calmar": round(r["calmar"], 2),
        "sortino": round(r["sortino"], 2),
        "ann_turnover_pct": round(r["ann_turnover"], 0),
        "trades_per_year": round(r["trades_per_year"], 0),
        "total_growth": round(r["total_growth"], 2),
        "avg_weight": round(r["avg_weight"], 3),
    }

import json
out_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/rebalance_freq_results.json"
with open(out_path, "w") as f:
    json.dump(summary, f, indent=2)
print(f"\nResults saved to {out_path}")
