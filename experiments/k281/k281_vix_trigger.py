"""
K281: VIX Trigger Rebalancing — The Practical Middle Ground
============================================================
Background: K279 showed daily VT dominates but requires daily attention.
VIX Trigger (rebalance only when VIX crosses boundaries) got Sharpe 0.388
with only 40 trades/yr. Can we optimize the trigger thresholds?

Data: SPY, GLD, VIX daily from yfinance. 2005-2024.

Methodology:
1. VIX Trigger variants:
   a. Standard: boundaries at 15, 20, 25, 30
   b. Wide: boundaries at 12, 20, 30
   c. Narrow: boundaries at 12, 15, 18, 22, 27, 35
   d. Asymmetric: up-triggers at 20, 25, 30; down-trigger only at 15
   e. Hysteresis: trigger UP at 22, trigger DOWN at 18
2. For each variant: Sharpe, MDD, trades/yr, net Sharpe at 5bps
3. Behavioral rating: how many times per year must investor check VIX?
4. 5-period cross-OOS
5. The IDEAL trigger: balance daily's performance and monthly's simplicity

[提出: 用戶, 執行: Claude]
"""

import sys
import json
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime

# ==================================================================
# 1. Download data
# ==================================================================
print("=" * 72)
print("K281: VIX Trigger Rebalancing — The Practical Middle Ground")
print("=" * 72)
print(f"\nStarted: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

print("\n[1/6] Downloading SPY, GLD, VIX data (2004-2025)...")

spy_raw = yf.download("SPY", start="2004-01-01", end="2025-12-31", progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="2004-01-01", end="2025-12-31", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2004-01-01", end="2025-12-31", progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(gld, how="inner").join(vix, how="inner").dropna()
data["spy_ret"] = np.log(data["spy_close"] / data["spy_close"].shift(1))
data["gld_ret"] = np.log(data["gld_close"] / data["gld_close"].shift(1))
data = data.dropna()

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")

# ==================================================================
# 2. Define VIX-to-weight mapping (12/VIX style)
# ==================================================================
# Weight = target_vol / implied_vol = 12 / VIX (capped at 1.0)
# This is our standard 12/VIX rule for the 50/50 SPY/GLD portfolio.

TARGET_ANNUALIZED = 0.12  # 12% target vol
RF_DAILY = 0.04 / 252     # ~4% risk-free
TX_COST_BPS = 5            # 5 bps per trade (one-way)

def vix_to_weight(vix_level):
    """Convert VIX level to portfolio weight using 12/VIX rule, capped [0, 1]."""
    w = TARGET_ANNUALIZED / (vix_level / 100)
    return np.clip(w, 0.0, 1.0)

# ==================================================================
# 3. Define trigger schemes
# ==================================================================

def get_vix_zone_standard(vix):
    """Standard: boundaries at 15, 20, 25, 30"""
    if vix < 15:
        return 0
    elif vix < 20:
        return 1
    elif vix < 25:
        return 2
    elif vix < 30:
        return 3
    else:
        return 4

def get_vix_zone_wide(vix):
    """Wide: boundaries at 12, 20, 30 (fewer triggers)"""
    if vix < 12:
        return 0
    elif vix < 20:
        return 1
    elif vix < 30:
        return 2
    else:
        return 3

def get_vix_zone_narrow(vix):
    """Narrow: boundaries at 12, 15, 18, 22, 27, 35 (more triggers)"""
    if vix < 12:
        return 0
    elif vix < 15:
        return 1
    elif vix < 18:
        return 2
    elif vix < 22:
        return 3
    elif vix < 27:
        return 4
    elif vix < 35:
        return 5
    else:
        return 6

def get_vix_zone_asymmetric(vix, prev_zone, prev_vix):
    """
    Asymmetric: up-triggers at 20, 25, 30 (reduce on spike),
    down-trigger only at 15 (restore when calm).
    Between 15-20 on the way down, do NOT trigger — stay in current allocation.
    """
    # Up triggers (VIX rising → reduce exposure)
    up_boundaries = [20, 25, 30]
    # Down trigger (VIX falling → restore)
    down_boundary = 15

    # Determine zone based on direction
    if vix >= 30:
        return 3  # max defensive
    elif vix >= 25:
        return 2
    elif vix >= 20:
        return 1
    elif vix < down_boundary:
        return 0  # full exposure only when VIX < 15
    else:
        # Between 15-20 on the way down: keep previous zone
        return prev_zone

def get_vix_zone_hysteresis(vix, prev_zone):
    """
    Hysteresis: trigger UP (go defensive) at 22, trigger DOWN (go aggressive) at 18.
    Avoids whipsaw around 20. Binary: zone 0 (aggressive) or zone 1 (defensive).
    Extended with a second level at 28/24.
    """
    if prev_zone == 0:
        # Currently aggressive
        if vix >= 28:
            return 2  # very defensive
        elif vix >= 22:
            return 1  # defensive
        else:
            return 0  # stay aggressive
    elif prev_zone == 1:
        # Currently defensive
        if vix >= 28:
            return 2  # very defensive
        elif vix < 18:
            return 0  # go aggressive
        else:
            return 1  # stay defensive
    else:
        # Currently very defensive (zone 2)
        if vix < 18:
            return 0  # go aggressive
        elif vix < 24:
            return 1  # go defensive
        else:
            return 2  # stay very defensive


# Zone midpoint VIX for weight calculation
ZONE_MIDPOINTS = {
    "standard": {0: 12, 1: 17.5, 2: 22.5, 3: 27.5, 4: 35},
    "wide":     {0: 10, 1: 16, 2: 25, 3: 35},
    "narrow":   {0: 10, 1: 13.5, 2: 16.5, 3: 20, 4: 24.5, 5: 31, 6: 40},
    "asymmetric": {0: 12, 1: 22.5, 2: 27.5, 3: 35},
    "hysteresis": {0: 15, 1: 22, 2: 32},
}


def run_trigger_strategy(data_df, scheme_name, zone_func_type):
    """
    Run a VIX trigger strategy.

    Returns dict with performance metrics + daily series.
    """
    n = len(data_df)
    vix_vals = data_df["vix_close"].values
    spy_rets = data_df["spy_ret"].values
    gld_rets = data_df["gld_ret"].values

    midpoints = ZONE_MIDPOINTS[scheme_name]

    # Track zones and weights
    zones = np.zeros(n, dtype=int)
    weights = np.zeros(n)
    trade_days = np.zeros(n, dtype=bool)

    # Initialize
    if zone_func_type == "standard":
        zones[0] = get_vix_zone_standard(vix_vals[0])
    elif zone_func_type == "wide":
        zones[0] = get_vix_zone_wide(vix_vals[0])
    elif zone_func_type == "narrow":
        zones[0] = get_vix_zone_narrow(vix_vals[0])
    elif zone_func_type == "asymmetric":
        zones[0] = 0  # start aggressive
    elif zone_func_type == "hysteresis":
        zones[0] = 0  # start aggressive

    weights[0] = vix_to_weight(midpoints[zones[0]])
    trade_days[0] = True  # initial position

    for i in range(1, n):
        v = vix_vals[i]

        if zone_func_type == "standard":
            new_zone = get_vix_zone_standard(v)
        elif zone_func_type == "wide":
            new_zone = get_vix_zone_wide(v)
        elif zone_func_type == "narrow":
            new_zone = get_vix_zone_narrow(v)
        elif zone_func_type == "asymmetric":
            new_zone = get_vix_zone_asymmetric(v, zones[i-1], vix_vals[i-1])
        elif zone_func_type == "hysteresis":
            new_zone = get_vix_zone_hysteresis(v, zones[i-1])

        zones[i] = new_zone

        if new_zone != zones[i-1]:
            # Zone changed — rebalance
            weights[i] = vix_to_weight(midpoints[new_zone])
            trade_days[i] = True
        else:
            # No change — hold
            weights[i] = weights[i-1]

    # Portfolio return: 50/50 SPY/GLD, scaled by weight
    # Weight applied with 1-day lag (signal today → position tomorrow)
    lagged_w = np.roll(weights, 1)
    lagged_w[0] = 0  # no position on day 1

    port_ret = lagged_w * (0.5 * spy_rets + 0.5 * gld_rets)

    # Transaction costs
    weight_changes = np.abs(np.diff(lagged_w))
    tc_daily = np.zeros(n)
    tc_daily[1:] = weight_changes * TX_COST_BPS / 10000

    port_ret_net = port_ret - tc_daily

    return {
        "weights": weights,
        "lagged_weights": lagged_w,
        "port_ret": port_ret,
        "port_ret_net": port_ret_net,
        "zones": zones,
        "trade_days": trade_days,
        "n_trades": int(np.sum(trade_days)),
    }


def compute_metrics(port_ret, port_ret_net, n_trades, n_days):
    """Compute Sharpe, MDD, Calmar, trades/yr, net Sharpe."""
    years = n_days / 252

    # Gross
    ann_ret = np.mean(port_ret) * 252
    ann_vol = np.std(port_ret, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = np.cumsum(port_ret)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum - running_max
    mdd = np.min(drawdown)

    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Sortino
    downside = port_ret[port_ret < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 10 else ann_vol
    sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

    # Net
    ann_ret_net = np.mean(port_ret_net) * 252
    ann_vol_net = np.std(port_ret_net, ddof=1) * np.sqrt(252)
    sharpe_net = (ann_ret_net - 0.04) / ann_vol_net if ann_vol_net > 0 else 0

    trades_per_yr = n_trades / years if years > 0 else 0

    # TX cost drag
    tx_drag = (ann_ret - ann_ret_net) * 100  # in bps * 100 → percentage points

    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "sharpe_net": sharpe_net,
        "trades_per_yr": trades_per_yr,
        "tx_drag_pct": tx_drag,
    }


# ==================================================================
# 4. Benchmark strategies
# ==================================================================

def run_daily_vt(data_df):
    """Daily 12/VIX rebalancing (optimal but high maintenance)."""
    n = len(data_df)
    vix_vals = data_df["vix_close"].values
    spy_rets = data_df["spy_ret"].values
    gld_rets = data_df["gld_ret"].values

    weights = np.array([vix_to_weight(v) for v in vix_vals])

    lagged_w = np.roll(weights, 1)
    lagged_w[0] = 0

    port_ret = lagged_w * (0.5 * spy_rets + 0.5 * gld_rets)

    weight_changes = np.abs(np.diff(lagged_w))
    tc_daily = np.zeros(n)
    tc_daily[1:] = weight_changes * TX_COST_BPS / 10000

    port_ret_net = port_ret - tc_daily

    n_trades = np.sum(np.abs(np.diff(weights)) > 0.001)

    return port_ret, port_ret_net, int(n_trades)


def run_monthly_vt(data_df):
    """Monthly 12/VIX rebalancing (first trading day of month)."""
    n = len(data_df)
    vix_vals = data_df["vix_close"].values
    spy_rets = data_df["spy_ret"].values
    gld_rets = data_df["gld_ret"].values

    month_key = data_df.index.to_period("M")
    first_days = data_df.groupby(month_key).head(1).index
    is_rebal = data_df.index.isin(first_days)

    weights = np.zeros(n)
    weights[0] = vix_to_weight(vix_vals[0])

    for i in range(1, n):
        if is_rebal[i]:
            weights[i] = vix_to_weight(vix_vals[i])
        else:
            weights[i] = weights[i-1]

    lagged_w = np.roll(weights, 1)
    lagged_w[0] = 0

    port_ret = lagged_w * (0.5 * spy_rets + 0.5 * gld_rets)

    weight_changes = np.abs(np.diff(lagged_w))
    tc_daily = np.zeros(n)
    tc_daily[1:] = weight_changes * TX_COST_BPS / 10000

    port_ret_net = port_ret - tc_daily

    n_trades = np.sum(is_rebal)

    return port_ret, port_ret_net, int(n_trades)


def run_buy_and_hold(data_df):
    """Buy & Hold 50/50 SPY/GLD."""
    spy_rets = data_df["spy_ret"].values
    gld_rets = data_df["gld_ret"].values
    port_ret = 0.5 * spy_rets + 0.5 * gld_rets
    return port_ret, port_ret.copy(), 1  # 1 initial trade


# ==================================================================
# 5. Run all strategies on full OOS
# ==================================================================
# OOS: 2005-01-01 to end (GLD starts Nov 2004)
oos_start = "2005-01-01"
oos = data.loc[oos_start:].copy()
print(f"\n[2/6] OOS period: {oos.index[0].date()} to {oos.index[-1].date()} ({len(oos)} days)")

print("\n[3/6] Running all strategies on full OOS period...")

# Trigger strategies
trigger_schemes = {
    "Standard (15/20/25/30)": ("standard", "standard"),
    "Wide (12/20/30)": ("wide", "wide"),
    "Narrow (12/15/18/22/27/35)": ("narrow", "narrow"),
    "Asymmetric (up:20/25/30, down:15)": ("asymmetric", "asymmetric"),
    "Hysteresis (up:22/28, down:18/24)": ("hysteresis", "hysteresis"),
}

all_results = {}

for name, (scheme, ztype) in trigger_schemes.items():
    res = run_trigger_strategy(oos, scheme, ztype)
    metrics = compute_metrics(res["port_ret"], res["port_ret_net"], res["n_trades"], len(oos))
    all_results[name] = {**metrics, "type": "trigger"}
    print(f"  {name}: Sharpe={metrics['sharpe']:.3f}, Net={metrics['sharpe_net']:.3f}, "
          f"MDD={metrics['mdd']:.1%}, Trades/yr={metrics['trades_per_yr']:.1f}")

# Benchmarks
print("\n  --- Benchmarks ---")

# Daily VT
ret_d, ret_d_net, n_d = run_daily_vt(oos)
m_daily = compute_metrics(ret_d, ret_d_net, n_d, len(oos))
all_results["Daily VT (12/VIX)"] = {**m_daily, "type": "benchmark"}
print(f"  Daily VT: Sharpe={m_daily['sharpe']:.3f}, Net={m_daily['sharpe_net']:.3f}, "
      f"MDD={m_daily['mdd']:.1%}, Trades/yr={m_daily['trades_per_yr']:.1f}")

# Monthly VT
ret_m, ret_m_net, n_m = run_monthly_vt(oos)
m_monthly = compute_metrics(ret_m, ret_m_net, n_m, len(oos))
all_results["Monthly VT (12/VIX)"] = {**m_monthly, "type": "benchmark"}
print(f"  Monthly VT: Sharpe={m_monthly['sharpe']:.3f}, Net={m_monthly['sharpe_net']:.3f}, "
      f"MDD={m_monthly['mdd']:.1%}, Trades/yr={m_monthly['trades_per_yr']:.1f}")

# Buy & Hold
ret_bh, ret_bh_net, n_bh = run_buy_and_hold(oos)
m_bh = compute_metrics(ret_bh, ret_bh_net, n_bh, len(oos))
all_results["Buy & Hold 50/50"] = {**m_bh, "type": "benchmark"}
print(f"  Buy & Hold: Sharpe={m_bh['sharpe']:.3f}, MDD={m_bh['mdd']:.1%}")


# ==================================================================
# 6. Behavioral rating
# ==================================================================
print("\n[4/6] Behavioral analysis...")

# For each trigger strategy, compute how often investor needs to check
behavioral = {}
for name, (scheme, ztype) in trigger_schemes.items():
    res = run_trigger_strategy(oos, scheme, ztype)
    years = len(oos) / 252
    trades_yr = res["n_trades"] / years

    # "Check frequency" = how often must you look at VIX to not miss a trigger?
    # Approximate: if there are N zone changes per year, you need to check
    # at least 2x as often to catch them promptly.
    # But practically: VIX moves slowly most of the time.
    # A simple heuristic: check daily if >50 trades/yr, weekly if 20-50, bi-weekly if <20

    if trades_yr > 50:
        check_freq = "Daily"
        difficulty = 5
    elif trades_yr > 30:
        check_freq = "2-3x/week"
        difficulty = 4
    elif trades_yr > 15:
        check_freq = "Weekly"
        difficulty = 3
    elif trades_yr > 8:
        check_freq = "Bi-weekly"
        difficulty = 2
    else:
        check_freq = "Monthly"
        difficulty = 1

    behavioral[name] = {
        "trades_per_yr": trades_yr,
        "check_frequency": check_freq,
        "difficulty_rating": difficulty,
    }

print("\n  Behavioral Ratings:")
print(f"  {'Strategy':<42} {'Trades/yr':>10} {'Check Freq':>14} {'Difficulty':>11}")
print("  " + "-" * 79)
for name, b in behavioral.items():
    print(f"  {name:<42} {b['trades_per_yr']:>10.1f} {b['check_frequency']:>14} "
          f"{b['difficulty_rating']:>7}/5")
# Benchmarks
print(f"  {'Daily VT (benchmark)':<42} {m_daily['trades_per_yr']:>10.1f} {'Daily':>14} {'5':>7}/5")
print(f"  {'Monthly VT (benchmark)':<42} {m_monthly['trades_per_yr']:>10.1f} {'Monthly':>14} {'1':>7}/5")


# ==================================================================
# 7. Cross-OOS validation (5 periods)
# ==================================================================
print("\n[5/6] Cross-OOS validation (5 periods)...")

# Define 5 OOS periods
oos_periods = [
    ("2005-01-01", "2008-12-31", "2005-2008 (GFC build-up & crisis)"),
    ("2009-01-01", "2012-12-31", "2009-2012 (Recovery + Euro crisis)"),
    ("2013-01-01", "2016-12-31", "2013-2016 (Low vol era)"),
    ("2017-01-01", "2020-12-31", "2017-2020 (COVID)"),
    ("2021-01-01", "2024-12-31", "2021-2024 (Post-COVID + rate hikes)"),
]

cross_oos_results = {}

for period_start, period_end, period_name in oos_periods:
    period_data = data.loc[period_start:period_end].copy()
    if len(period_data) < 100:
        print(f"  Skipping {period_name}: insufficient data ({len(period_data)} days)")
        continue

    print(f"\n  Period: {period_name} ({len(period_data)} days)")

    period_results = {}

    # Trigger strategies
    for name, (scheme, ztype) in trigger_schemes.items():
        res = run_trigger_strategy(period_data, scheme, ztype)
        metrics = compute_metrics(res["port_ret"], res["port_ret_net"], res["n_trades"], len(period_data))
        period_results[name] = metrics

    # Benchmarks
    ret_d, ret_d_net, n_d = run_daily_vt(period_data)
    period_results["Daily VT (12/VIX)"] = compute_metrics(ret_d, ret_d_net, n_d, len(period_data))

    ret_m, ret_m_net, n_m = run_monthly_vt(period_data)
    period_results["Monthly VT (12/VIX)"] = compute_metrics(ret_m, ret_m_net, n_m, len(period_data))

    ret_bh, ret_bh_net, n_bh = run_buy_and_hold(period_data)
    period_results["Buy & Hold 50/50"] = compute_metrics(ret_bh, ret_bh_net, n_bh, len(period_data))

    cross_oos_results[period_name] = period_results

    # Print summary for this period
    print(f"  {'Strategy':<42} {'Sharpe':>7} {'Net':>7} {'MDD':>8} {'Tr/yr':>7}")
    print("  " + "-" * 73)
    for sname, sm in period_results.items():
        print(f"  {sname:<42} {sm['sharpe']:>7.3f} {sm['sharpe_net']:>7.3f} "
              f"{sm['mdd']:>7.1%} {sm['trades_per_yr']:>7.1f}")


# ==================================================================
# 8. Aggregate cross-OOS: mean and consistency
# ==================================================================
print("\n" + "=" * 72)
print("CROSS-OOS SUMMARY")
print("=" * 72)

all_strategy_names = list(trigger_schemes.keys()) + ["Daily VT (12/VIX)", "Monthly VT (12/VIX)", "Buy & Hold 50/50"]

print(f"\n{'Strategy':<42} {'Mean Sh':>8} {'Std Sh':>8} {'Mean Net':>9} "
      f"{'Mean MDD':>9} {'Win/5':>6}")
print("-" * 82)

summary_table = {}

for sname in all_strategy_names:
    sharpes = []
    nets = []
    mdds = []
    for pname, pres in cross_oos_results.items():
        if sname in pres:
            sharpes.append(pres[sname]["sharpe"])
            nets.append(pres[sname]["sharpe_net"])
            mdds.append(pres[sname]["mdd"])

    if len(sharpes) == 0:
        continue

    mean_sh = np.mean(sharpes)
    std_sh = np.std(sharpes, ddof=1) if len(sharpes) > 1 else 0
    mean_net = np.mean(nets)
    mean_mdd = np.mean(mdds)

    # Win count: how many periods Sharpe > 0?
    wins = sum(1 for s in sharpes if s > 0)

    summary_table[sname] = {
        "mean_sharpe": mean_sh,
        "std_sharpe": std_sh,
        "mean_net_sharpe": mean_net,
        "mean_mdd": mean_mdd,
        "wins": wins,
        "n_periods": len(sharpes),
        "sharpes_by_period": sharpes,
        "nets_by_period": nets,
    }

    print(f"{sname:<42} {mean_sh:>8.3f} {std_sh:>8.3f} {mean_net:>9.3f} "
          f"{mean_mdd:>8.1%} {wins:>3}/{len(sharpes)}")


# ==================================================================
# 9. Efficiency frontier: Sharpe per unit of difficulty
# ==================================================================
print("\n" + "=" * 72)
print("EFFICIENCY FRONTIER: Sharpe per Unit of Effort")
print("=" * 72)

difficulty_map = {
    "Standard (15/20/25/30)": 3,
    "Wide (12/20/30)": 2,
    "Narrow (12/15/18/22/27/35)": 4,
    "Asymmetric (up:20/25/30, down:15)": 3,
    "Hysteresis (up:22/28, down:18/24)": 2,
    "Daily VT (12/VIX)": 5,
    "Monthly VT (12/VIX)": 1,
    "Buy & Hold 50/50": 0,
}

print(f"\n{'Strategy':<42} {'Net Sharpe':>10} {'Difficulty':>10} {'Efficiency':>10}")
print("-" * 74)

efficiency = {}
for sname in all_strategy_names:
    if sname not in summary_table or sname not in difficulty_map:
        continue
    net_sh = summary_table[sname]["mean_net_sharpe"]
    diff = difficulty_map[sname]
    # Efficiency = net Sharpe / (1 + difficulty)
    # Adding 1 to avoid division by zero for B&H
    eff = net_sh / (1 + diff) if diff >= 0 else 0
    efficiency[sname] = eff
    print(f"{sname:<42} {net_sh:>10.3f} {diff:>7}/5 {eff:>10.3f}")

best_eff = max(efficiency, key=efficiency.get) if efficiency else "N/A"
print(f"\n  >>> Best efficiency (Sharpe per effort): {best_eff}")


# ==================================================================
# 10. Head-to-head: each trigger vs daily, monthly, B&H
# ==================================================================
print("\n" + "=" * 72)
print("HEAD-TO-HEAD: Trigger vs Benchmarks (per-period wins)")
print("=" * 72)

for tname in trigger_schemes:
    if tname not in summary_table:
        continue
    trigger_sharpes = []
    daily_sharpes = []
    monthly_sharpes = []
    bh_sharpes = []

    for pname, pres in cross_oos_results.items():
        if tname in pres and "Daily VT (12/VIX)" in pres:
            trigger_sharpes.append(pres[tname]["sharpe_net"])
            daily_sharpes.append(pres["Daily VT (12/VIX)"]["sharpe_net"])
            monthly_sharpes.append(pres["Monthly VT (12/VIX)"]["sharpe_net"])
            bh_sharpes.append(pres["Buy & Hold 50/50"]["sharpe_net"])

    n_p = len(trigger_sharpes)
    vs_daily = sum(1 for t, d in zip(trigger_sharpes, daily_sharpes) if t > d)
    vs_monthly = sum(1 for t, m in zip(trigger_sharpes, monthly_sharpes) if t > m)
    vs_bh = sum(1 for t, b in zip(trigger_sharpes, bh_sharpes) if t > b)

    print(f"\n  {tname}:")
    print(f"    vs Daily:   {vs_daily}/{n_p} wins")
    print(f"    vs Monthly: {vs_monthly}/{n_p} wins")
    print(f"    vs B&H:     {vs_bh}/{n_p} wins")


# ==================================================================
# 11. The IDEAL trigger recommendation
# ==================================================================
print("\n" + "=" * 72)
print("THE IDEAL TRIGGER: Recommendation")
print("=" * 72)

# Rank strategies by a composite score:
# Score = 0.4 * normalized_net_sharpe + 0.3 * normalized_mdd + 0.3 * (1 - normalized_difficulty)
# where normalized = (x - min) / (max - min)

# Exclude B&H from ranking (it's the null case)
ranked_names = [s for s in all_strategy_names if s != "Buy & Hold 50/50" and s in summary_table]

net_sharpes = [summary_table[s]["mean_net_sharpe"] for s in ranked_names]
mdds = [summary_table[s]["mean_mdd"] for s in ranked_names]  # more negative = worse
diffs = [difficulty_map[s] for s in ranked_names]

# Normalize
def normalize(vals, higher_is_better=True):
    vmin, vmax = min(vals), max(vals)
    if vmax == vmin:
        return [0.5] * len(vals)
    if higher_is_better:
        return [(v - vmin) / (vmax - vmin) for v in vals]
    else:
        return [(vmax - v) / (vmax - vmin) for v in vals]

norm_sharpe = normalize(net_sharpes, higher_is_better=True)
norm_mdd = normalize(mdds, higher_is_better=True)  # less negative = better, so higher is better
norm_diff = normalize(diffs, higher_is_better=False)  # lower difficulty = better

composite_scores = {}
for i, name in enumerate(ranked_names):
    score = 0.4 * norm_sharpe[i] + 0.3 * norm_mdd[i] + 0.3 * norm_diff[i]
    composite_scores[name] = score

# Sort by score
sorted_strategies = sorted(composite_scores.items(), key=lambda x: x[1], reverse=True)

print(f"\nComposite Score = 0.4×Sharpe + 0.3×MDD + 0.3×Simplicity")
print(f"\n{'Rank':<5} {'Strategy':<42} {'Score':>7} {'Net Sh':>8} {'MDD':>8} {'Diff':>6}")
print("-" * 78)
for rank, (sname, score) in enumerate(sorted_strategies, 1):
    print(f"{rank:<5} {sname:<42} {score:>7.3f} {summary_table[sname]['mean_net_sharpe']:>8.3f} "
          f"{summary_table[sname]['mean_mdd']:>7.1%} {difficulty_map[sname]:>4}/5")

winner = sorted_strategies[0][0]
print(f"\n  >>> RECOMMENDED STRATEGY: {winner}")
print(f"      Net Sharpe: {summary_table[winner]['mean_net_sharpe']:.3f}")
print(f"      Mean MDD: {summary_table[winner]['mean_mdd']:.1%}")
print(f"      Difficulty: {difficulty_map[winner]}/5")
print(f"      Behavioral: Check VIX {behavioral.get(winner, {}).get('check_frequency', 'N/A')}")


# ==================================================================
# 12. Statistical significance (bootstrap Sharpe difference)
# ==================================================================
print("\n" + "=" * 72)
print("STATISTICAL TESTS: Bootstrap Sharpe Differences")
print("=" * 72)

# For each trigger strategy, bootstrap test vs monthly VT (the practical alternative)
# and vs daily VT (the theoretical optimum)
N_BOOT = 10000
np.random.seed(42)

# Full OOS returns for bootstrapping
trigger_full_results = {}
for name, (scheme, ztype) in trigger_schemes.items():
    res = run_trigger_strategy(oos, scheme, ztype)
    trigger_full_results[name] = res["port_ret_net"]

ret_d_full, ret_d_net_full, _ = run_daily_vt(oos)
ret_m_full, ret_m_net_full, _ = run_monthly_vt(oos)

print(f"\n  Bootstrap: {N_BOOT} replications, block length = 21 days")

def block_bootstrap_sharpe_diff(ret_a, ret_b, n_boot=10000, block_len=21):
    """Block bootstrap for Sharpe ratio difference."""
    n = len(ret_a)
    n_blocks = n // block_len + 1

    sharpe_diffs = np.zeros(n_boot)

    for b in range(n_boot):
        # Sample block start indices
        starts = np.random.randint(0, n - block_len, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_len) for s in starts])[:n]

        boot_a = ret_a[indices]
        boot_b = ret_b[indices]

        sha = np.mean(boot_a) / np.std(boot_a, ddof=1) * np.sqrt(252) if np.std(boot_a) > 0 else 0
        shb = np.mean(boot_b) / np.std(boot_b, ddof=1) * np.sqrt(252) if np.std(boot_b) > 0 else 0

        sharpe_diffs[b] = sha - shb

    p_value = np.mean(sharpe_diffs < 0)  # P(trigger < benchmark)
    return np.mean(sharpe_diffs), np.std(sharpe_diffs), p_value

print(f"\n  {'Trigger Strategy':<42} {'vs Monthly':>12} {'p-val':>8} {'vs Daily':>12} {'p-val':>8}")
print("  " + "-" * 84)

for tname in trigger_schemes:
    if tname not in trigger_full_results:
        continue
    t_ret = trigger_full_results[tname]

    # vs Monthly
    diff_m, std_m, p_m = block_bootstrap_sharpe_diff(t_ret, ret_m_net_full, N_BOOT)
    # vs Daily
    diff_d, std_d, p_d = block_bootstrap_sharpe_diff(t_ret, ret_d_net_full, N_BOOT)

    sig_m = "*" if p_m < 0.05 or p_m > 0.95 else ""
    sig_d = "*" if p_d < 0.05 or p_d > 0.95 else ""

    print(f"  {tname:<42} {diff_m:>+10.3f}{sig_m:>2} {p_m:>7.3f} "
          f"{diff_d:>+10.3f}{sig_d:>2} {p_d:>7.3f}")

print("\n  * = significant at 5% level (trigger is sig. better/worse)")
print("  p-value: P(trigger < benchmark). p<0.05 = trigger significantly worse.")


# ==================================================================
# 13. Save results
# ==================================================================
print("\n[6/6] Saving results...")

output = {
    "experiment": "K281",
    "title": "VIX Trigger Rebalancing — The Practical Middle Ground",
    "data": {
        "assets": ["SPY", "GLD"],
        "source": "yfinance",
        "oos_range": f"{oos.index[0].date()} to {oos.index[-1].date()}",
        "n_days": len(oos),
    },
    "full_oos_results": {},
    "cross_oos_summary": {},
    "behavioral": {},
    "efficiency": {},
    "composite_ranking": [],
    "recommendation": winner,
    "timestamp": datetime.now().isoformat(),
}

for sname, metrics in all_results.items():
    output["full_oos_results"][sname] = {k: float(v) if isinstance(v, (np.floating, float)) else v
                                          for k, v in metrics.items()}

for sname in all_strategy_names:
    if sname in summary_table:
        st = summary_table[sname]
        output["cross_oos_summary"][sname] = {
            "mean_sharpe": float(st["mean_sharpe"]),
            "std_sharpe": float(st["std_sharpe"]),
            "mean_net_sharpe": float(st["mean_net_sharpe"]),
            "mean_mdd": float(st["mean_mdd"]),
            "wins": st["wins"],
            "n_periods": st["n_periods"],
        }

for sname, b in behavioral.items():
    output["behavioral"][sname] = b

for sname, eff in efficiency.items():
    output["efficiency"][sname] = float(eff)

for rank, (sname, score) in enumerate(sorted_strategies, 1):
    output["composite_ranking"].append({
        "rank": rank,
        "strategy": sname,
        "score": float(score),
        "mean_net_sharpe": float(summary_table[sname]["mean_net_sharpe"]),
        "mean_mdd": float(summary_table[sname]["mean_mdd"]),
        "difficulty": difficulty_map[sname],
    })

results_path = "experiments/k281_vix_trigger_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Results saved to {results_path}")


# ==================================================================
# FINAL SUMMARY
# ==================================================================
print("\n" + "=" * 72)
print("K281 FINAL SUMMARY")
print("=" * 72)

print(f"""
EXPERIMENT: VIX Trigger Rebalancing Optimization
DATA: SPY + GLD 50/50, 12/VIX rule, {oos.index[0].date()} to {oos.index[-1].date()}
TX COST: {TX_COST_BPS} bps per trade

TRIGGER VARIANTS TESTED:
  a. Standard (15/20/25/30) — classic 4-zone
  b. Wide (12/20/30) — minimalist 3-zone
  c. Narrow (12/15/18/22/27/35) — granular 6-zone
  d. Asymmetric (up:20/25/30, down:15) — fast defense, slow recovery
  e. Hysteresis (up:22/28, down:18/24) — whipsaw protection

FULL OOS RESULTS:
""")

# Final table
print(f"{'Strategy':<42} {'Sharpe':>7} {'Net Sh':>7} {'MDD':>8} {'Tr/yr':>7} {'Diff':>5}")
print("-" * 78)
for sname in all_strategy_names:
    if sname in all_results:
        m = all_results[sname]
        d = difficulty_map.get(sname, "?")
        print(f"{sname:<42} {m['sharpe']:>7.3f} {m['sharpe_net']:>7.3f} "
              f"{m['mdd']:>7.1%} {m['trades_per_yr']:>7.1f} {d:>4}/5")

print(f"""
CROSS-OOS CONSISTENCY:
  {winner}: {summary_table[winner]['wins']}/{summary_table[winner]['n_periods']} periods positive Sharpe
  Mean Net Sharpe: {summary_table[winner]['mean_net_sharpe']:.3f}
  Mean MDD: {summary_table[winner]['mean_mdd']:.1%}

RECOMMENDATION: {winner}
  This strategy captures most of the VT benefit with minimal trading.
  Check VIX: {behavioral.get(winner, {}).get('check_frequency', 'varies')}
""")

print(f"\nFinished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
