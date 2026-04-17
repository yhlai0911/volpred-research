#!/usr/bin/env python3
"""
K633: Taiwan 0050 Strategy Optimization

Motivation:
  Most strategies focus on US assets (SPY/GLD). Taiwan investors want 0050.TW-
  specific strategies. We have Taiwan VT (8.63/VIX) and Hybrid Leverage but
  haven't systematically optimized parameters for 0050.

  Key challenge: Taiwan market uses PREVIOUS DAY's VIX (US closes after Taiwan
  opens), so all signals use VIX_{t-1}.

Design:
  Data: 0050.TW, SPY, VIX daily via yfinance (2010-01-01 to 2026-03-27)
  OOS evaluation: 2015-01-01 to 2026-03-27 (~11 years)
  Monthly rebalancing on 1st trading day

  Strategy variants:
    a. Simple VT: w = k/VIX_{t-1}, k ∈ {8, 10, 12, 14, 16}
    b. Piecewise VT: breakpoint-based linear ramp
    c. Taiwan-specific VT: w = k/(VIX_{t-1} × amplification)
       amplification ∈ {3.0, 4.0, 4.6, 5.0}
    d. 50/50 0050+GLD allocation
    e. Fear DCA with 0050 (step function from K632)
    f. Buy-and-hold 0050 (benchmark)

  Transaction costs (Taiwan ETF):
    - Commission: 0.1425% × 0.3 (3折) = 0.04275% per trade
    - ETF securities tax: 0.1% sell-side only
    - Round-trip: ~18.5bp
    - Reference: .claude/skills/autonomous-research/references/transaction-costs.md

  Evaluation: Sharpe, MDD, Calmar, Total return, Net Sharpe (after TX)
  Bootstrap significance vs buy-and-hold

References:
  - K530: 0050 vol ≈ 4.6× SPY VIX-implied (amplification factor)
  - K552: Fear DCA 3/3 OOS cross-validation
  - K569/K574: Piecewise VT Sharpe 1.875
  - K595: Adaptive Tier 3-regime switching
  - K632: Fear DCA parameter optimization
  - daily_update.py: taiwan_8.63vix uses 8.63/VIX = 12/(VIX×1.39)

Data source: yfinance (0050.TW, SPY, GLD, ^VIX), daily prices
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════

# Taiwan ETF transaction costs (from transaction-costs.md)
TW_COMMISSION_RATE = 0.001425        # 0.1425% official
TW_COMMISSION_DISCOUNT = 0.3         # 3折 typical online
TW_EFFECTIVE_COMMISSION = TW_COMMISSION_RATE * TW_COMMISSION_DISCOUNT  # 0.04275%
TW_ETF_TAX_RATE = 0.001             # 0.1% sell-side only (ETF, NOT 0.3%)
TW_ETF_ROUND_TRIP = TW_EFFECTIVE_COMMISSION * 2 + TW_ETF_TAX_RATE  # ~18.5bp

# US ETF costs (for GLD in 50/50 strategies)
US_ETF_ROUND_TRIP = 0.0002           # ~2bp (spread only, zero commission)

OOS_START = "2015-01-01"
OOS_END = "2026-03-27"
FULL_START = "2010-01-01"
DATA_START = "2009-01-01"  # extra buffer for VIX lag + warmup

# ═══════════════════════════════════════════════════════════
# 1. Data Download
# ═══════════════════════════════════════════════════════════
print("=" * 80)
print("K633: Taiwan 0050 Strategy Optimization")
print("=" * 80)

print("\n[1/8] Downloading data...")
tickers = {"0050.TW": "0050", "SPY": "SPY", "GLD": "GLD", "^VIX": "VIX"}
raw = {}
for ticker, label in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2026-03-28", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        close = df[("Close", ticker)].dropna()
    else:
        close = df["Close"].dropna()
    raw[label] = close
    print(f"  {label}: {close.index[0].strftime('%Y-%m-%d')} to "
          f"{close.index[-1].strftime('%Y-%m-%d')} ({len(close)} days)")

# Build unified daily DataFrame
# Use union of all indices, forward-fill 0050 on US holidays
all_dates = raw["0050"].index.union(raw["SPY"].index).union(raw["VIX"].index)
daily = pd.DataFrame(index=all_dates)
daily["tw50"] = raw["0050"].reindex(all_dates).ffill()
daily["spy"] = raw["SPY"].reindex(all_dates).ffill()
daily["gld"] = raw["GLD"].reindex(all_dates).ffill()
daily["vix"] = raw["VIX"].reindex(all_dates).ffill()
daily = daily.dropna()
daily.index = pd.to_datetime(daily.index)

# VIX_{t-1} for Taiwan strategies (timezone lag)
daily["vix_lag"] = daily["vix"].shift(1)
daily = daily.dropna()

# Daily returns
daily["tw50_ret"] = daily["tw50"].pct_change()
daily["spy_ret"] = daily["spy"].pct_change()
daily["gld_ret"] = daily["gld"].pct_change()
daily = daily.dropna()

print(f"\n  Unified daily data: {daily.index[0].strftime('%Y-%m-%d')} to "
      f"{daily.index[-1].strftime('%Y-%m-%d')} ({len(daily)} days)")

# ═══════════════════════════════════════════════════════════
# 2. Descriptive Statistics
# ═══════════════════════════════════════════════════════════
print("\n[2/8] Descriptive Statistics...")

for label, col in [("0050.TW", "tw50_ret"), ("SPY", "spy_ret"), ("GLD", "gld_ret")]:
    r = daily[col]
    ann_vol = r.std() * np.sqrt(252)
    print(f"  {label}: mean={r.mean()*100:.4f}%/day, std={r.std()*100:.4f}%, "
          f"ann_vol={ann_vol*100:.1f}%, skew={r.skew():.3f}, kurt={r.kurtosis():.3f}")

vix = daily["vix"]
print(f"\n  VIX: mean={vix.mean():.2f}, std={vix.std():.2f}, "
      f"min={vix.min():.1f}, max={vix.max():.1f}")

# VIX regime distribution
regimes = {
    "VIX < 15": (vix < 15).sum(),
    "15 ≤ VIX < 20": ((vix >= 15) & (vix < 20)).sum(),
    "20 ≤ VIX < 25": ((vix >= 20) & (vix < 25)).sum(),
    "25 ≤ VIX < 30": ((vix >= 25) & (vix < 30)).sum(),
    "VIX ≥ 30": (vix >= 30).sum(),
}
n_total = len(vix)
print("\n  VIX regime distribution:")
for rname, cnt in regimes.items():
    print(f"    {rname:20s}: {cnt:5d} days ({cnt/n_total*100:5.1f}%)")

# 0050 vs SPY amplification check
oos_mask = daily.index >= OOS_START
tw_vol = daily.loc[oos_mask, "tw50_ret"].std() * np.sqrt(252)
spy_vol = daily.loc[oos_mask, "spy_ret"].std() * np.sqrt(252)
vix_mean_oos = daily.loc[oos_mask, "vix"].mean()
amplification_actual = tw_vol / (vix_mean_oos / 100)
print(f"\n  OOS amplification check:")
print(f"    0050 ann vol = {tw_vol*100:.1f}%")
print(f"    SPY ann vol  = {spy_vol*100:.1f}%")
print(f"    Mean VIX     = {vix_mean_oos:.1f}")
print(f"    0050_vol / (VIX/100) = {amplification_actual:.2f}x")

# ═══════════════════════════════════════════════════════════
# 3. Monthly Rebalancing Schedule
# ═══════════════════════════════════════════════════════════
print("\n[3/8] Building monthly rebalancing schedule...")

daily["year_month"] = daily.index.to_period("M")
first_trading_days = daily.groupby("year_month").apply(lambda g: g.index[0])
rebal_dates = first_trading_days[
    (first_trading_days >= OOS_START) & (first_trading_days <= OOS_END)
].values
rebal_dates = pd.DatetimeIndex(rebal_dates)

print(f"  Rebalancing months: {len(rebal_dates)}")
print(f"  Period: {rebal_dates[0].strftime('%Y-%m')} to {rebal_dates[-1].strftime('%Y-%m')}")


# ═══════════════════════════════════════════════════════════
# 4. Strategy Simulation Engine
# ═══════════════════════════════════════════════════════════
print("\n[4/8] Simulating strategies...")


def simulate_monthly_vt(daily_df, rebal_dates, weight_func, name,
                        asset_col="tw50_ret", cost_per_trade=TW_ETF_ROUND_TRIP):
    """
    Simulate a monthly-rebalanced VT strategy.

    weight_func: callable(vix_lag) -> target weight in [0, 1]
    Returns dict with gross and net metrics.
    """
    oos_data = daily_df[daily_df.index >= rebal_dates[0]].copy()

    # Assign weight on each rebalancing date
    weights = {}
    for rd in rebal_dates:
        if rd in oos_data.index:
            vl = oos_data.loc[rd, "vix_lag"]
            w = weight_func(vl)
            weights[rd] = np.clip(w, 0.0, 1.0)

    # Daily portfolio returns
    current_weight = 0.0
    port_rets_gross = []
    port_rets_net = []
    prev_weight = 0.0
    trade_count = 0

    for date in oos_data.index:
        if date in weights:
            new_weight = weights[date]
            # Transaction cost on weight change
            turnover = abs(new_weight - prev_weight)
            tx_cost = turnover * cost_per_trade
            trade_count += 1 if turnover > 0.001 else 0
            current_weight = new_weight
            prev_weight = current_weight
        else:
            tx_cost = 0.0

        asset_ret = oos_data.loc[date, asset_col]
        gross_ret = current_weight * asset_ret + (1 - current_weight) * 0.0
        net_ret = gross_ret - tx_cost
        port_rets_gross.append((date, gross_ret))
        port_rets_net.append((date, net_ret))

    gross_df = pd.DataFrame(port_rets_gross, columns=["date", "ret"]).set_index("date")
    net_df = pd.DataFrame(port_rets_net, columns=["date", "ret"]).set_index("date")

    return {
        "name": name,
        **_calc_metrics(gross_df["ret"], "gross"),
        **_calc_metrics(net_df["ret"], "net"),
        "trades": trade_count,
        "avg_weight": np.mean(list(weights.values())),
    }


def simulate_two_asset_vt(daily_df, rebal_dates, weight_func, name,
                          asset1_col="tw50_ret", asset2_col="gld_ret",
                          split=(0.5, 0.5),
                          cost1=TW_ETF_ROUND_TRIP, cost2=US_ETF_ROUND_TRIP):
    """
    Two-asset monthly-rebalanced strategy (e.g. 50/50 0050+GLD).
    weight_func returns total risky weight, split between asset1 and asset2.
    """
    oos_data = daily_df[daily_df.index >= rebal_dates[0]].copy()

    weights = {}
    for rd in rebal_dates:
        if rd in oos_data.index:
            vl = oos_data.loc[rd, "vix_lag"]
            w = weight_func(vl)
            weights[rd] = np.clip(w, 0.0, 1.0)

    current_w1 = 0.0
    current_w2 = 0.0
    prev_w1 = 0.0
    prev_w2 = 0.0
    port_rets_gross = []
    port_rets_net = []

    for date in oos_data.index:
        if date in weights:
            total_w = weights[date]
            new_w1 = total_w * split[0]
            new_w2 = total_w * split[1]
            turnover1 = abs(new_w1 - prev_w1)
            turnover2 = abs(new_w2 - prev_w2)
            tx_cost = turnover1 * cost1 + turnover2 * cost2
            current_w1 = new_w1
            current_w2 = new_w2
            prev_w1 = current_w1
            prev_w2 = current_w2
        else:
            tx_cost = 0.0

        r1 = oos_data.loc[date, asset1_col]
        r2 = oos_data.loc[date, asset2_col]
        cash_w = 1 - current_w1 - current_w2
        gross_ret = current_w1 * r1 + current_w2 * r2 + cash_w * 0.0
        net_ret = gross_ret - tx_cost
        port_rets_gross.append((date, gross_ret))
        port_rets_net.append((date, net_ret))

    gross_df = pd.DataFrame(port_rets_gross, columns=["date", "ret"]).set_index("date")
    net_df = pd.DataFrame(port_rets_net, columns=["date", "ret"]).set_index("date")

    return {
        "name": name,
        **_calc_metrics(gross_df["ret"], "gross"),
        **_calc_metrics(net_df["ret"], "net"),
        "trades": len(weights),
        "avg_weight": np.mean(list(weights.values())),
    }


def simulate_dca_0050(daily_df, invest_dates, multiplier_func, name,
                      base_monthly=10000, cost_per_trade=TW_ETF_ROUND_TRIP):
    """
    DCA simulation for 0050 with VIX-based contribution multipliers.
    base_monthly in TWD (10,000 TWD ≈ ~310 USD).
    """
    prices = daily_df["tw50"]
    daily_rets = daily_df["tw50_ret"]
    start_date = invest_dates[0]
    oos_prices = prices[prices.index >= start_date]

    shares = 0.0
    total_invested = 0.0
    portfolio_values = []
    invest_idx = 0

    for date in oos_prices.index:
        price = oos_prices[date]

        if invest_idx < len(invest_dates) and date >= invest_dates[invest_idx]:
            vix_lag = daily_df.loc[date, "vix_lag"] if date in daily_df.index else 18.0
            mult = multiplier_func(vix_lag)
            contrib = base_monthly * mult
            # Deduct buy-side commission
            buy_cost = contrib * TW_EFFECTIVE_COMMISSION
            net_invest = contrib - buy_cost
            new_shares = net_invest / price
            shares += new_shares
            total_invested += contrib
            invest_idx += 1

        portfolio_values.append((date, shares * price, total_invested))

    if not portfolio_values:
        return None

    pv_df = pd.DataFrame(portfolio_values, columns=["date", "value", "invested"])
    pv_df.set_index("date", inplace=True)

    terminal = pv_df["value"].iloc[-1]
    total_inv = pv_df["invested"].iloc[-1]
    gain_pct = (terminal / total_inv - 1) * 100

    # MDD
    running_max = pv_df["value"].cummax()
    dd = (pv_df["value"] - running_max) / running_max
    mdd = dd.min()

    # Monthly returns for Sharpe
    pv_monthly = pv_df["value"].resample("ME").last().dropna()
    monthly_rets = pv_monthly.pct_change().dropna()
    sharpe = (monthly_rets.mean() / monthly_rets.std()) * np.sqrt(12) if monthly_rets.std() > 0 else 0

    return {
        "name": name,
        "terminal_wealth": round(float(terminal), 2),
        "total_invested": round(float(total_inv), 2),
        "gain_pct": round(float(gain_pct), 2),
        "mdd": round(float(mdd), 4),
        "sharpe": round(float(sharpe), 4),
        "n_months": invest_idx,
    }


def _calc_metrics(returns, prefix):
    """Calculate Sharpe, MDD, Calmar, total return from daily returns series."""
    if len(returns) == 0:
        return {}

    # Cumulative wealth
    cum = (1 + returns).cumprod()
    total_ret = float(cum.iloc[-1] - 1)
    n_years = len(returns) / 252

    # Annualized return
    cagr = float(cum.iloc[-1] ** (1 / n_years) - 1) if n_years > 0 else 0

    # Annualized vol
    ann_vol = float(returns.std() * np.sqrt(252))

    # Sharpe (assuming risk-free = 0 for simplicity, consistent with other experiments)
    sharpe = cagr / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    mdd = float(dd.min())

    # Calmar
    calmar = cagr / abs(mdd) if abs(mdd) > 0.001 else 0

    return {
        f"{prefix}_total_ret": round(total_ret * 100, 2),
        f"{prefix}_cagr": round(cagr * 100, 2),
        f"{prefix}_vol": round(ann_vol * 100, 2),
        f"{prefix}_sharpe": round(sharpe, 4),
        f"{prefix}_mdd": round(mdd * 100, 2),
        f"{prefix}_calmar": round(calmar, 4),
    }


# ─────────────────────────────────────────────────
# A. Simple VT: w = k / VIX_{t-1}
# ─────────────────────────────────────────────────
results = []

for k in [8, 10, 12, 14, 16]:
    res = simulate_monthly_vt(
        daily, rebal_dates,
        weight_func=lambda v, k=k: k / v,
        name=f"SimpleVT_k{k}"
    )
    results.append(res)
    print(f"  {res['name']:30s} | Gross Sharpe={res['gross_sharpe']:.3f} "
          f"Net Sharpe={res['net_sharpe']:.3f} MDD={res['net_mdd']:.1f}%")

# ─────────────────────────────────────────────────
# B. Piecewise VT variants
# ─────────────────────────────────────────────────
piecewise_configs = [
    # (name, full_below, zero_above) — linear between
    ("PW_12_20", 12, 20),   # current piecewise_conservative
    ("PW_12_25", 12, 25),
    ("PW_15_25", 15, 25),
    ("PW_15_30", 15, 30),
    ("PW_10_20", 10, 20),
    ("PW_10_25", 10, 25),
]

for name, full_below, zero_above in piecewise_configs:
    def make_pw_func(fb, za):
        def pw(v):
            if v < fb:
                return 1.0
            elif v > za:
                return 0.0
            else:
                return (za - v) / (za - fb)
        return pw

    res = simulate_monthly_vt(
        daily, rebal_dates,
        weight_func=make_pw_func(full_below, zero_above),
        name=f"Piecewise_{name}"
    )
    results.append(res)
    print(f"  {res['name']:30s} | Gross Sharpe={res['gross_sharpe']:.3f} "
          f"Net Sharpe={res['net_sharpe']:.3f} MDD={res['net_mdd']:.1f}%")

# ─────────────────────────────────────────────────
# C. Taiwan-specific VT: w = k_eff / VIX_{t-1}
# ─────────────────────────────────────────────────
# The existing strategy uses 8.63/VIX = 12/(VIX×1.39)
# where 1.39 = VIXTWN/VIX ratio. Test a range of effective k values.
# Lower k → more conservative (accounts for 0050's higher vol vs SPY).
for k_eff in [4, 6, 8, 8.63, 10, 12]:
    res = simulate_monthly_vt(
        daily, rebal_dates,
        weight_func=lambda v, k=k_eff: k / v,
        name=f"TW_k{k_eff:.2f}"
    )
    results.append(res)
    print(f"  {res['name']:30s} | Gross Sharpe={res['gross_sharpe']:.3f} "
          f"Net Sharpe={res['net_sharpe']:.3f} MDD={res['net_mdd']:.1f}%")

# ─────────────────────────────────────────────────
# D. 50/50 0050+GLD
# ─────────────────────────────────────────────────
for k in [8, 10, 12]:
    res = simulate_two_asset_vt(
        daily, rebal_dates,
        weight_func=lambda v, k=k: k / v,
        name=f"5050_0050GLD_k{k}",
        asset1_col="tw50_ret", asset2_col="gld_ret",
        split=(0.5, 0.5),
        cost1=TW_ETF_ROUND_TRIP, cost2=US_ETF_ROUND_TRIP
    )
    results.append(res)
    print(f"  {res['name']:30s} | Gross Sharpe={res['gross_sharpe']:.3f} "
          f"Net Sharpe={res['net_sharpe']:.3f} MDD={res['net_mdd']:.1f}%")

# Piecewise 50/50 0050+GLD
res = simulate_two_asset_vt(
    daily, rebal_dates,
    weight_func=make_pw_func(12, 20),
    name="5050_0050GLD_PW12_20",
    asset1_col="tw50_ret", asset2_col="gld_ret",
    split=(0.5, 0.5),
    cost1=TW_ETF_ROUND_TRIP, cost2=US_ETF_ROUND_TRIP
)
results.append(res)
print(f"  {res['name']:30s} | Gross Sharpe={res['gross_sharpe']:.3f} "
      f"Net Sharpe={res['net_sharpe']:.3f} MDD={res['net_mdd']:.1f}%")

# ─────────────────────────────────────────────────
# E. Fear DCA with 0050
# ─────────────────────────────────────────────────
print("\n  --- Fear DCA variants ---")

# Investment dates for DCA (first trading day each month, 0050 trading days only)
tw50_only = daily[daily["tw50"].notna()].copy()
tw50_only["year_month"] = tw50_only.index.to_period("M")
tw_first_days = tw50_only.groupby("year_month").apply(lambda g: g.index[0])
tw_invest_dates = tw_first_days[
    (tw_first_days >= OOS_START) & (tw_first_days <= OOS_END)
].values
tw_invest_dates = pd.DatetimeIndex(tw_invest_dates)

dca_results = []

# Plain DCA (benchmark)
plain_dca = simulate_dca_0050(
    daily, tw_invest_dates,
    multiplier_func=lambda v: 1.0,
    name="Plain_DCA_0050"
)
dca_results.append(plain_dca)
print(f"  {plain_dca['name']:30s} | Sharpe={plain_dca['sharpe']:.3f} "
      f"MDD={plain_dca['mdd']*100:.1f}% Gain={plain_dca['gain_pct']:.1f}%")

# Fear DCA: step function
def fear_step(v):
    if v > 30:
        return 2.0
    elif v > 25:
        return 1.5
    elif v < 15:
        return 0.5
    else:
        return 1.0

fear_dca = simulate_dca_0050(
    daily, tw_invest_dates,
    multiplier_func=fear_step,
    name="Fear_DCA_0050"
)
dca_results.append(fear_dca)
print(f"  {fear_dca['name']:30s} | Sharpe={fear_dca['sharpe']:.3f} "
      f"MDD={fear_dca['mdd']*100:.1f}% Gain={fear_dca['gain_pct']:.1f}%")

# Aggressive Fear DCA
def fear_aggressive(v):
    if v > 30:
        return 3.0
    elif v > 25:
        return 2.0
    elif v < 15:
        return 0.5
    else:
        return 1.0

fear_agg = simulate_dca_0050(
    daily, tw_invest_dates,
    multiplier_func=fear_aggressive,
    name="Fear_DCA_0050_Aggressive"
)
dca_results.append(fear_agg)
print(f"  {fear_agg['name']:30s} | Sharpe={fear_agg['sharpe']:.3f} "
      f"MDD={fear_agg['mdd']*100:.1f}% Gain={fear_agg['gain_pct']:.1f}%")

# Inverse VIX DCA: mult = 12/VIX (invest more when VIX is low = market calm)
inv_dca = simulate_dca_0050(
    daily, tw_invest_dates,
    multiplier_func=lambda v: 12.0 / v,
    name="InverseVIX_DCA_0050"
)
dca_results.append(inv_dca)
print(f"  {inv_dca['name']:30s} | Sharpe={inv_dca['sharpe']:.3f} "
      f"MDD={inv_dca['mdd']*100:.1f}% Gain={inv_dca['gain_pct']:.1f}%")

# ─────────────────────────────────────────────────
# F. Buy-and-hold 0050 (benchmark)
# ─────────────────────────────────────────────────
bh_res = simulate_monthly_vt(
    daily, rebal_dates,
    weight_func=lambda v: 1.0,
    name="BuyHold_0050",
    cost_per_trade=0.0  # no rebalancing cost for buy-and-hold
)
results.append(bh_res)
print(f"\n  {bh_res['name']:30s} | Gross Sharpe={bh_res['gross_sharpe']:.3f} "
      f"MDD={bh_res['net_mdd']:.1f}%")


# ═══════════════════════════════════════════════════════════
# 5. Ranking Table
# ═══════════════════════════════════════════════════════════
print("\n" + "=" * 80)
print("[5/8] Strategy Ranking (sorted by Net Sharpe)")
print("=" * 80)

# Sort by net Sharpe
ranked = sorted(results, key=lambda x: x.get("net_sharpe", 0), reverse=True)

print(f"\n{'Rank':>4} {'Strategy':30s} {'Gross SR':>9} {'Net SR':>9} "
      f"{'CAGR%':>7} {'MDD%':>7} {'Calmar':>7} {'AvgW':>6} {'Trades':>6}")
print("-" * 100)
for i, r in enumerate(ranked, 1):
    print(f"{i:4d} {r['name']:30s} {r['gross_sharpe']:9.3f} {r['net_sharpe']:9.3f} "
          f"{r.get('net_cagr', 0):7.2f} {r.get('net_mdd', 0):7.1f} "
          f"{r.get('net_calmar', 0):7.3f} {r.get('avg_weight', 0):6.2f} "
          f"{r.get('trades', 0):6d}")


# ═══════════════════════════════════════════════════════════
# 6. Bootstrap Significance vs Buy-and-Hold
# ═══════════════════════════════════════════════════════════
print("\n[6/8] Bootstrap significance test vs buy-and-hold...")

# Get daily returns for bootstrap
oos_daily = daily[daily.index >= rebal_dates[0]].copy()

# Buy-and-hold daily returns
bh_daily_rets = oos_daily["tw50_ret"].values

# Best strategy daily returns (reconstruct)
best_strat = ranked[0]
best_name = best_strat["name"]
print(f"  Testing best strategy: {best_name}")

# Reconstruct best strategy daily returns
def reconstruct_daily_returns(daily_df, rebal_dates, weight_func, asset_col="tw50_ret"):
    """Reconstruct daily return series for a strategy."""
    oos = daily_df[daily_df.index >= rebal_dates[0]].copy()
    weights = {}
    for rd in rebal_dates:
        if rd in oos.index:
            vl = oos.loc[rd, "vix_lag"]
            weights[rd] = np.clip(weight_func(vl), 0.0, 1.0)

    current_w = 0.0
    rets = []
    for date in oos.index:
        if date in weights:
            current_w = weights[date]
        r = oos.loc[date, asset_col]
        rets.append(current_w * r)
    return np.array(rets)


# Identify the weight function and type for the best strategy
def get_weight_func(name):
    """Returns (weight_func, is_two_asset, split_info)."""
    if name.startswith("SimpleVT_k"):
        k = int(name.split("k")[1])
        return lambda v, k=k: k / v, False, None
    elif name.startswith("TW_k"):
        k = float(name.split("k")[1])
        return lambda v, k=k: k / v, False, None
    elif name.startswith("Piecewise_PW_"):
        parts = name.replace("Piecewise_PW_", "").split("_")
        fb, za = int(parts[0]), int(parts[1])
        return make_pw_func(fb, za), False, None
    elif name == "BuyHold_0050":
        return lambda v: 1.0, False, None
    elif name.startswith("5050_0050GLD"):
        # Two-asset: extract k or piecewise
        if "_PW" in name:
            parts = name.split("PW")[1].split("_")
            fb, za = int(parts[0]), int(parts[1])
            return make_pw_func(fb, za), True, ("tw50_ret", "gld_ret", 0.5, 0.5)
        else:
            k = int(name.split("_k")[1])
            return (lambda v, k=k: k / v), True, ("tw50_ret", "gld_ret", 0.5, 0.5)
    else:
        return None, False, None


def reconstruct_two_asset_returns(daily_df, rebal_dates, weight_func,
                                   a1_col, a2_col, s1, s2):
    """Reconstruct daily return series for a two-asset strategy."""
    oos = daily_df[daily_df.index >= rebal_dates[0]].copy()
    weights = {}
    for rd in rebal_dates:
        if rd in oos.index:
            vl = oos.loc[rd, "vix_lag"]
            weights[rd] = np.clip(weight_func(vl), 0.0, 1.0)

    cw1, cw2 = 0.0, 0.0
    rets = []
    for date in oos.index:
        if date in weights:
            total_w = weights[date]
            cw1 = total_w * s1
            cw2 = total_w * s2
        r1 = oos.loc[date, a1_col]
        r2 = oos.loc[date, a2_col]
        rets.append(cw1 * r1 + cw2 * r2)
    return np.array(rets)


# Bootstrap test
n_boot = 10000
rng = np.random.default_rng(42)
boot_results = []

print("\n  Top-5 strategies vs Buy-and-Hold:")
print(f"  {'Strategy':30s} {'Excess bp/day':>14} {'p-value':>10} {'Sig':>5}")
print("  " + "-" * 65)

for r in ranked[:5]:
    wf, is_two, split_info = get_weight_func(r["name"])
    if wf is None:
        continue

    if is_two:
        strat_rets = reconstruct_two_asset_returns(
            daily, rebal_dates, wf,
            split_info[0], split_info[1], split_info[2], split_info[3]
        )
    else:
        strat_rets = reconstruct_daily_returns(daily, rebal_dates, wf)

    d = strat_rets - bh_daily_rets[:len(strat_rets)]
    bm = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, len(d), len(d))
        bm[b] = d[idx].mean()
    pv = (bm <= 0).mean()
    md = d.mean()
    sig = "***" if pv < 0.01 else ("**" if pv < 0.05 else ("*" if pv < 0.10 else ""))
    print(f"  {r['name']:30s} {md*10000:14.2f} {pv:10.4f} {sig:>5}")
    boot_results.append({"name": r["name"], "excess_bp": round(md*10000, 2),
                         "p_value": round(pv, 4)})

# Use top result for summary
best_wf, best_is_two, best_split = get_weight_func(best_name)
if best_wf is not None:
    if best_is_two:
        best_daily_rets = reconstruct_two_asset_returns(
            daily, rebal_dates, best_wf,
            best_split[0], best_split[1], best_split[2], best_split[3]
        )
    else:
        best_daily_rets = reconstruct_daily_returns(daily, rebal_dates, best_wf)

    diff = best_daily_rets - bh_daily_rets[:len(best_daily_rets)]
    boot_means = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, len(diff), len(diff))
        boot_means[b] = diff[idx].mean()

    p_value = (boot_means <= 0).mean()
    ci_lo = np.percentile(boot_means, 2.5)
    ci_hi = np.percentile(boot_means, 97.5)
    mean_diff = diff.mean()

    print(f"\n  Best strategy ({best_name}):")
    print(f"  Mean daily excess return: {mean_diff*10000:.2f} bp/day")
    print(f"  Bootstrap 95% CI: [{ci_lo*10000:.2f}, {ci_hi*10000:.2f}] bp/day")
    print(f"  p-value (one-sided, > BH): {p_value:.4f}")
    print(f"  Significant at 5%: {'Yes' if p_value < 0.05 else 'No'}")
else:
    mean_diff, p_value, ci_lo, ci_hi = 0, 1, 0, 0
    print(f"  Could not reconstruct {best_name}")


# ═══════════════════════════════════════════════════════════
# 7. Transaction Cost Impact Analysis
# ═══════════════════════════════════════════════════════════
print("\n[7/8] Transaction cost impact analysis...")

print(f"\n  Taiwan ETF round-trip cost: {TW_ETF_ROUND_TRIP*10000:.1f} bp")
print(f"  Monthly rebalancing: ~12 trades/year")
print(f"  Estimated annual TX drag: {TW_ETF_ROUND_TRIP * 12 * 100:.2f}% (upper bound, full turnover)")

print(f"\n  {'Strategy':30s} {'Gross CAGR':>11} {'Net CAGR':>11} {'TX Drag':>9}")
print("  " + "-" * 65)
for r in ranked[:10]:
    gross_cagr = r.get("gross_cagr", 0)
    net_cagr = r.get("net_cagr", 0)
    drag = gross_cagr - net_cagr
    print(f"  {r['name']:30s} {gross_cagr:10.2f}% {net_cagr:10.2f}% {drag:8.2f}%")


# ═══════════════════════════════════════════════════════════
# 8. Save Results
# ═══════════════════════════════════════════════════════════
print("\n[8/8] Saving results...")

# Best strategy selection
candidates = [r for r in ranked if r.get("net_sharpe", 0) > 0.5]
best_for_retail = None
for r in candidates:
    mdd = abs(r.get("net_mdd", -99))
    if mdd < 20:
        best_for_retail = r
        break

output = {
    "experiment_id": "K633",
    "title": "Taiwan 0050 Strategy Optimization",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance",
    "data_period": {
        "full": f"{daily.index[0].strftime('%Y-%m-%d')} to {daily.index[-1].strftime('%Y-%m-%d')}",
        "oos": f"{OOS_START} to {OOS_END}",
        "oos_years": round((pd.Timestamp(OOS_END) - pd.Timestamp(OOS_START)).days / 365.25, 1),
    },
    "transaction_costs": {
        "tw_etf_round_trip_bp": round(TW_ETF_ROUND_TRIP * 10000, 1),
        "tw_commission_effective": f"{TW_EFFECTIVE_COMMISSION*100:.4f}%",
        "tw_etf_tax": f"{TW_ETF_TAX_RATE*100:.1f}%",
        "us_etf_round_trip_bp": round(US_ETF_ROUND_TRIP * 10000, 1),
        "reference": ".claude/skills/autonomous-research/references/transaction-costs.md",
    },
    "descriptive_stats": {
        "tw50_ann_vol_oos": round(tw_vol * 100, 2),
        "spy_ann_vol_oos": round(spy_vol * 100, 2),
        "vix_mean_oos": round(vix_mean_oos, 2),
        "amplification_actual": round(amplification_actual, 2),
        "vix_regime_distribution": {k: f"{v/n_total*100:.1f}%" for k, v in regimes.items()},
    },
    "strategy_rankings": [
        {
            "rank": i + 1,
            "name": r["name"],
            "gross_sharpe": r.get("gross_sharpe"),
            "net_sharpe": r.get("net_sharpe"),
            "gross_cagr": r.get("gross_cagr"),
            "net_cagr": r.get("net_cagr"),
            "gross_mdd": r.get("gross_mdd"),
            "net_mdd": r.get("net_mdd"),
            "net_calmar": r.get("net_calmar"),
            "avg_weight": round(r.get("avg_weight", 0), 4),
            "trades": r.get("trades"),
        }
        for i, r in enumerate(ranked)
    ],
    "dca_results": [
        {
            "name": d["name"],
            "terminal_wealth": d["terminal_wealth"],
            "total_invested": d["total_invested"],
            "gain_pct": d["gain_pct"],
            "mdd": d["mdd"],
            "sharpe": d["sharpe"],
            "n_months": d["n_months"],
        }
        for d in dca_results if d is not None
    ],
    "bootstrap_vs_buyhold": {
        "best_strategy": best_name,
        "mean_excess_bp_per_day": round(mean_diff * 10000, 2),
        "p_value": round(p_value, 4),
        "ci_95_lo_bp": round(ci_lo * 10000, 2),
        "ci_95_hi_bp": round(ci_hi * 10000, 2),
        "top5_results": boot_results,
    },
    "best_for_retail": {
        "name": best_for_retail["name"] if best_for_retail else "None meets criteria",
        "criteria": "Net Sharpe > 0.5, MDD < -20%",
        "net_sharpe": best_for_retail.get("net_sharpe") if best_for_retail else None,
        "net_mdd": best_for_retail.get("net_mdd") if best_for_retail else None,
        "net_cagr": best_for_retail.get("net_cagr") if best_for_retail else None,
    },
    "key_findings": [],  # Populated after analysis
    "notes": [
        "All Taiwan strategies use VIX_{t-1} (timezone lag: US closes after Taiwan opens)",
        "ETF tax rate 0.1% (NOT 0.3% stock rate)",
        "Monthly rebalancing on 1st trading day",
        "OOS period ~11 years provides robust evaluation for monthly strategies",
        "0050 prices forward-filled on US holidays",
        "DCA simulation uses TWD 10,000/month base",
    ],
}

# Add key findings
findings = []
if best_for_retail:
    findings.append(
        f"Best retail strategy: {best_for_retail['name']} "
        f"(Net Sharpe={best_for_retail.get('net_sharpe')}, "
        f"MDD={best_for_retail.get('net_mdd'):.1f}%)"
    )

# Compare existing 8.63/VIX
existing = next((r for r in ranked if "8.63" in r["name"]), None)
if existing:
    findings.append(
        f"Existing taiwan_8.63vix: rank #{ranked.index(existing)+1}, "
        f"Net Sharpe={existing['net_sharpe']}"
    )

# TX cost impact
if len(ranked) > 0:
    top = ranked[0]
    drag = top.get("gross_cagr", 0) - top.get("net_cagr", 0)
    findings.append(
        f"TX cost drag on top strategy: {drag:.2f}% CAGR "
        f"({TW_ETF_ROUND_TRIP*10000:.1f}bp round-trip × monthly rebal)"
    )

# Piecewise vs simple comparison
pw_best = next((r for r in ranked if "Piecewise" in r["name"]), None)
simple_best = next((r for r in ranked if "SimpleVT" in r["name"]), None)
if pw_best and simple_best:
    findings.append(
        f"Piecewise best ({pw_best['name']}) vs Simple best ({simple_best['name']}): "
        f"Net Sharpe {pw_best['net_sharpe']:.3f} vs {simple_best['net_sharpe']:.3f}"
    )

# DCA comparison
if len(dca_results) >= 2 and dca_results[0] and dca_results[1]:
    plain = dca_results[0]
    fear = dca_results[1]
    findings.append(
        f"Fear DCA vs Plain DCA (0050): gain {fear['gain_pct']:.1f}% vs {plain['gain_pct']:.1f}% "
        f"(+{fear['gain_pct']-plain['gain_pct']:.1f}pp)"
    )

output["key_findings"] = findings

# Save
out_path = Path(__file__).parent / "k633_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"\n  Saved to {out_path}")

# Print summary
print("\n" + "=" * 80)
print("KEY FINDINGS")
print("=" * 80)
for i, finding in enumerate(findings, 1):
    print(f"  {i}. {finding}")

print("\n  DCA Results (0050.TW):")
print(f"  {'Strategy':30s} {'Gain%':>8} {'MDD':>8} {'Sharpe':>8} {'Invested':>12}")
print("  " + "-" * 70)
for d in dca_results:
    if d:
        print(f"  {d['name']:30s} {d['gain_pct']:7.1f}% {d['mdd']*100:7.1f}% "
              f"{d['sharpe']:8.3f} {d['total_invested']:12,.0f}")

print(f"\n{'='*80}")
print("K633 COMPLETE")
print(f"{'='*80}")
