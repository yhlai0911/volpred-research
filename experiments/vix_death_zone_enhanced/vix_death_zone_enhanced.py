"""
VIX 15-18 "Death Zone" Enhanced Hybrid VT Analysis
====================================================
The VIX 15-18 range historically produces ~-7.5%/yr returns.
Test if Hybrid VT can be improved by MORE aggressively reducing exposure
when VIX is in the 15-18 "death zone".

Strategy A: Standard Hybrid VT (VIX/GARCH > 1.3 switch)
Strategy B: Enhanced -- same as A but ALSO reduce weight by 30% when VIX is 15-18

Test on SPY 2018-2026 with GJR-GARCH w=2000.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
WINDOW = 2000
VIX_THRESHOLD = 1.3
TARGET_VOL_ANNUAL = 0.10
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 1.5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

# Death zone parameters
DEATH_ZONE_LOW = 15.0
DEATH_ZONE_HIGH = 18.0
DEATH_ZONE_REDUCTION = 0.30  # 30% weight reduction

# OOS period
OOS_START = "2018-01-02"
DATA_START = "2008-01-01"  # enough lookback for w=2000

print("=" * 75)
print("VIX 15-18 DEATH ZONE: ENHANCED HYBRID VT ANALYSIS")
print("=" * 75)
print(f"  Death zone: VIX {DEATH_ZONE_LOW}-{DEATH_ZONE_HIGH}")
print(f"  Reduction in death zone: {DEATH_ZONE_REDUCTION:.0%}")
print(f"  OOS period: {OOS_START} onwards")
print(f"  Model: GJR-GARCH(1,1,1) w={WINDOW}")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/5] Downloading SPY and VIX data...")

spy_raw = yf.download("SPY", start=DATA_START, end="2026-12-31", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start=DATA_START, end="2026-12-31", progress=False, auto_adjust=False)

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

# ==================================================================
# 2. Rolling GJR-GARCH Forecast (w=2000)
# ==================================================================
print(f"\n[2/5] Running rolling GJR-GARCH(1,1,1) with w={WINDOW}...")

returns_all = data["returns"].values
vix_all = data["vix_close"].values

garch_vol = np.full(len(data), np.nan)
n_total = len(data) - WINDOW
report_every = max(1, n_total // 20)

for i in range(n_total):
    idx = WINDOW + i
    window_returns = returns_all[idx - WINDOW:idx] * 100  # pct for arch

    try:
        model = arch_model(window_returns, vol="GARCH", p=1, o=1, q=1,
                          dist="t", mean="Zero", rescale=False)
        result = model.fit(disp="off", show_warning=False)
        fcast = result.forecast(horizon=1)
        var_pct = fcast.variance.iloc[-1, 0]
        garch_vol[idx] = np.sqrt(var_pct / 10000)  # convert back to decimal
    except Exception:
        garch_vol[idx] = np.std(returns_all[idx - WINDOW:idx])

    if (i + 1) % report_every == 0:
        pct = (i + 1) / n_total * 100
        print(f"    Progress: {pct:.0f}% ({i+1}/{n_total})")

print("  GARCH forecasts complete.")

# Add to dataframe
data["garch_vol"] = garch_vol
data["vix_daily"] = data["vix_close"] / 100 / np.sqrt(252)
data["ratio"] = data["vix_daily"] / data["garch_vol"]

# ==================================================================
# 3. Filter OOS Period
# ==================================================================
oos_mask = (data.index >= OOS_START) & data["garch_vol"].notna()
oos = data[oos_mask].copy()

print(f"\n[3/5] OOS period: {oos.index[0].date()} to {oos.index[-1].date()} ({len(oos)} days)")

# ==================================================================
# 4. First: Analyze VIX regimes in OOS period
# ==================================================================
print("\n[3.5/5] VIX Regime Analysis in OOS period:")
print("-" * 60)

vix_bins = [
    ("VIX < 12", oos["vix_close"] < 12),
    ("VIX 12-15", (oos["vix_close"] >= 12) & (oos["vix_close"] < 15)),
    ("VIX 15-18 (Death Zone)", (oos["vix_close"] >= 15) & (oos["vix_close"] < 18)),
    ("VIX 18-25", (oos["vix_close"] >= 18) & (oos["vix_close"] < 25)),
    ("VIX 25-35", (oos["vix_close"] >= 25) & (oos["vix_close"] < 35)),
    ("VIX > 35", oos["vix_close"] >= 35),
]

for label, mask in vix_bins:
    n_days = mask.sum()
    pct = n_days / len(oos) * 100
    if n_days > 5:
        avg_ret = oos.loc[mask, "returns"].mean() * 252 * 100  # annualized %
        vol = oos.loc[mask, "returns"].std() * np.sqrt(252) * 100
        sharpe_zone = (oos.loc[mask, "returns"].mean() - RF_DAILY) / oos.loc[mask, "returns"].std() * np.sqrt(252) if oos.loc[mask, "returns"].std() > 0 else 0
        print(f"  {label:30s}: {n_days:>4d} days ({pct:>5.1f}%), Ann.Ret={avg_ret:>+6.1f}%, Vol={vol:>5.1f}%, Sharpe={sharpe_zone:>+5.2f}")
    else:
        print(f"  {label:30s}: {n_days:>4d} days ({pct:>5.1f}%)")

# ==================================================================
# 5. Run Strategies
# ==================================================================
print(f"\n[4/5] Running strategy comparison...")

# --- Common: GARCH-based weight ---
w_garch = TARGET_VOL_DAILY / oos["garch_vol"]
w_garch = w_garch.clip(0, MAX_LEVERAGE)

# --- Common: VIX-based weight ---
w_vix = TARGET_VOL_DAILY / oos["vix_daily"]
w_vix = w_vix.clip(0, MAX_LEVERAGE)

# --- Strategy A: Standard Hybrid VT ---
# Switch to VIX when ratio > threshold
ratio = oos["ratio"]
w_hybrid_std = np.where(ratio > VIX_THRESHOLD, w_vix, w_garch)

# --- Strategy B: Enhanced with death zone reduction ---
# Same as A, but reduce by 30% when VIX is in 15-18
in_death_zone = (oos["vix_close"] >= DEATH_ZONE_LOW) & (oos["vix_close"] < DEATH_ZONE_HIGH)
w_hybrid_enhanced = w_hybrid_std.copy()
w_hybrid_enhanced[in_death_zone.values] *= (1 - DEATH_ZONE_REDUCTION)

# --- Strategy C: Buy & Hold (benchmark) ---
# weight = 1.0 always

# Also test different reduction levels for sensitivity
reduction_levels = [0.10, 0.20, 0.30, 0.40, 0.50]


def compute_strategy_metrics(weights, returns_arr, name, rf_daily=RF_DAILY):
    """Compute metrics for a given weight array."""
    port_returns = weights * returns_arr
    n = len(port_returns)
    total_years = n / 252

    cum_ret = np.exp(np.cumsum(port_returns))

    ann_ret = (cum_ret[-1] ** (1 / total_years)) - 1
    ann_vol = np.std(port_returns) * np.sqrt(252)
    sharpe = (np.mean(port_returns) - rf_daily) / np.std(port_returns) * np.sqrt(252) if np.std(port_returns) > 0 else 0

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = cum_ret / running_max - 1
    max_dd = np.min(drawdowns)

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else np.inf

    # Sortino
    downside = port_returns[port_returns < 0]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else 1e-6
    sortino = (ann_ret - RF_ANNUAL) / downside_vol

    # Monthly win rate
    monthly_rets = pd.Series(port_returns, index=oos.index).resample("ME").sum()
    win_rate = (monthly_rets > 0).mean()

    # Average weight
    avg_weight = np.mean(weights)

    # Turnover
    weight_changes = np.abs(np.diff(weights))
    ann_turnover = np.sum(weight_changes) / total_years

    # Yearly breakdown
    yearly = {}
    port_series = pd.Series(port_returns, index=oos.index)
    for yr in sorted(set(oos.index.year)):
        yr_rets = port_series[port_series.index.year == yr]
        if len(yr_rets) > 20:
            yr_sharpe = (yr_rets.mean() - rf_daily) / yr_rets.std() * np.sqrt(252) if yr_rets.std() > 0 else 0
            yr_ann_ret = (np.exp(yr_rets.sum()) - 1)
            yearly[yr] = {"sharpe": yr_sharpe, "return": yr_ann_ret}

    return {
        "strategy": name,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "sortino": sortino,
        "win_rate_monthly": win_rate,
        "avg_weight": avg_weight,
        "ann_turnover": ann_turnover,
        "total_growth": cum_ret[-1],
        "total_years": total_years,
        "cum_returns": cum_ret,
        "port_returns": port_returns,
        "yearly": yearly,
    }


# Run all strategies
returns_arr = oos["returns"].values

results = {}

# Strategy A: Standard Hybrid VT
print("  Running Strategy A: Standard Hybrid VT...")
results["A_Standard"] = compute_strategy_metrics(w_hybrid_std, returns_arr, "A: Standard Hybrid VT")

# Strategy B: Enhanced (30% reduction in death zone)
print("  Running Strategy B: Enhanced (-30% in VIX 15-18)...")
results["B_Enhanced"] = compute_strategy_metrics(w_hybrid_enhanced, returns_arr, "B: Enhanced (-30% VIX 15-18)")

# Buy & Hold benchmark
print("  Running Buy & Hold benchmark...")
bh_weights = np.ones(len(returns_arr))
results["BuyHold"] = compute_strategy_metrics(bh_weights, returns_arr, "Buy & Hold (SPY)")

# Sensitivity: Different reduction levels
print("  Running sensitivity analysis (different reduction levels)...")
sensitivity = {}
for red in reduction_levels:
    w_sens = w_hybrid_std.copy()
    w_sens[in_death_zone.values] *= (1 - red)
    name = f"DZ_red_{int(red*100)}pct"
    sensitivity[name] = compute_strategy_metrics(w_sens, returns_arr, f"Death Zone -{int(red*100)}%")

# Also test wider death zones
print("  Running death zone boundary sensitivity...")
zone_configs = [
    (13, 18, "VIX 13-18"),
    (14, 18, "VIX 14-18"),
    (15, 18, "VIX 15-18"),
    (15, 20, "VIX 15-20"),
    (15, 22, "VIX 15-22"),
    (13, 20, "VIX 13-20"),
]
zone_results = {}
for lo, hi, label in zone_configs:
    zone_mask = (oos["vix_close"] >= lo) & (oos["vix_close"] < hi)
    w_z = w_hybrid_std.copy()
    w_z[zone_mask.values] *= (1 - DEATH_ZONE_REDUCTION)
    zone_results[label] = compute_strategy_metrics(w_z, returns_arr, f"Enhanced ({label})")

# ==================================================================
# 6. Print Results
# ==================================================================
print(f"\n[5/5] Results Summary")
print("=" * 75)

# --- Main comparison ---
print(f"\n{'策略':<35} {'Sharpe':>8} {'年化報酬':>10} {'MaxDD':>10} {'Calmar':>8} {'Avg Wt':>8}")
print("-" * 85)

for key in ["A_Standard", "B_Enhanced", "BuyHold"]:
    r = results[key]
    print(f"{r['strategy']:<35} {r['sharpe']:>8.3f} {r['ann_return']:>9.2%} {r['max_dd']:>9.2%} {r['calmar']:>8.2f} {r['avg_weight']:>8.3f}")

# Delta
a = results["A_Standard"]
b = results["B_Enhanced"]
print("-" * 85)
print(f"{'Delta (B - A)':<35} {b['sharpe']-a['sharpe']:>+8.3f} {b['ann_return']-a['ann_return']:>+9.2%} "
      f"{b['max_dd']-a['max_dd']:>+9.2%} {b['calmar']-a['calmar']:>+8.2f} {b['avg_weight']-a['avg_weight']:>+8.3f}")

# --- Detailed metrics ---
print("\n\nDetailed Comparison:")
print("-" * 75)
for key in ["A_Standard", "B_Enhanced"]:
    r = results[key]
    print(f"\n  {r['strategy']}:")
    print(f"    Sharpe Ratio:     {r['sharpe']:.3f}")
    print(f"    Annual Return:    {r['ann_return']:.2%}")
    print(f"    Annual Vol:       {r['ann_vol']:.2%}")
    print(f"    Max Drawdown:     {r['max_dd']:.2%}")
    print(f"    Calmar Ratio:     {r['calmar']:.2f}")
    print(f"    Sortino Ratio:    {r['sortino']:.2f}")
    print(f"    Monthly Win%:     {r['win_rate_monthly']:.1%}")
    print(f"    Avg Weight:       {r['avg_weight']:.3f}")
    print(f"    Ann Turnover:     {r['ann_turnover']:.2f}")
    print(f"    Total Growth:     {r['total_growth']:.2f}x ($1M -> ${r['total_growth']*1_000_000:,.0f})")

# --- Death zone days analysis ---
dz_days = in_death_zone.sum()
dz_pct = dz_days / len(oos) * 100
print(f"\n\nDeath Zone Statistics:")
print(f"  Days in VIX 15-18: {dz_days} ({dz_pct:.1f}% of OOS)")
print(f"  Avg SPY return in death zone: {oos.loc[in_death_zone, 'returns'].mean()*252:.2%} annualized")
print(f"  Std A weight in death zone: {w_hybrid_std[in_death_zone.values].mean():.3f}")
print(f"  Enh B weight in death zone: {w_hybrid_enhanced[in_death_zone.values].mean():.3f}")

# --- Yearly breakdown ---
print("\n\nYearly Sharpe Comparison:")
print("-" * 65)
print(f"{'Year':<8} {'Standard':>12} {'Enhanced':>12} {'Delta':>10} {'VIX 15-18 Days':>16}")

years = sorted(set(oos.index.year))
for yr in years:
    yr_mask = oos.index.year == yr
    dz_yr = ((oos["vix_close"] >= DEATH_ZONE_LOW) & (oos["vix_close"] < DEATH_ZONE_HIGH) & yr_mask).sum()

    if yr in a["yearly"] and yr in b["yearly"]:
        a_s = a["yearly"][yr]["sharpe"]
        b_s = b["yearly"][yr]["sharpe"]
        delta = b_s - a_s
        print(f"{yr:<8} {a_s:>12.3f} {b_s:>12.3f} {delta:>+10.3f} {dz_yr:>16d}")

print(f"\n{'Avg':<8}", end="")
a_avg = np.mean([a["yearly"][yr]["sharpe"] for yr in years if yr in a["yearly"]])
b_avg = np.mean([b["yearly"][yr]["sharpe"] for yr in years if yr in b["yearly"]])
print(f" {a_avg:>12.3f} {b_avg:>12.3f} {b_avg-a_avg:>+10.3f}")

# --- Yearly Return Comparison ---
print("\n\nYearly Return Comparison:")
print("-" * 65)
print(f"{'Year':<8} {'Standard':>12} {'Enhanced':>12} {'Delta':>10}")
for yr in years:
    if yr in a["yearly"] and yr in b["yearly"]:
        a_r = a["yearly"][yr]["return"]
        b_r = b["yearly"][yr]["return"]
        print(f"{yr:<8} {a_r:>11.2%} {b_r:>11.2%} {b_r-a_r:>+10.2%}")

# --- Sensitivity: Reduction levels ---
print("\n\nSensitivity: Death Zone Reduction Level")
print("-" * 75)
print(f"{'Reduction':>10} {'Sharpe':>10} {'Ann Ret':>10} {'MaxDD':>10} {'Calmar':>10} {'dSharpe vs Std':>15}")

# First print standard (0% reduction)
print(f"{'0%':>10} {a['sharpe']:>10.3f} {a['ann_return']:>9.2%} {a['max_dd']:>9.2%} {a['calmar']:>10.2f} {'baseline':>15}")

for red in reduction_levels:
    name = f"DZ_red_{int(red*100)}pct"
    s = sensitivity[name]
    delta_s = s['sharpe'] - a['sharpe']
    print(f"{int(red*100)}%{'':<8} {s['sharpe']:>10.3f} {s['ann_return']:>9.2%} {s['max_dd']:>9.2%} {s['calmar']:>10.2f} {delta_s:>+15.3f}")

# --- Sensitivity: Zone boundaries ---
print("\n\nSensitivity: Death Zone Boundaries (30% reduction)")
print("-" * 75)
print(f"{'Zone':>12} {'Sharpe':>10} {'Ann Ret':>10} {'MaxDD':>10} {'Calmar':>10} {'Days':>8} {'dSharpe':>10}")

print(f"{'Standard':>12} {a['sharpe']:>10.3f} {a['ann_return']:>9.2%} {a['max_dd']:>9.2%} {a['calmar']:>10.2f} {'-':>8} {'baseline':>10}")

for lo, hi, label in zone_configs:
    z = zone_results[label]
    zone_mask = (oos["vix_close"] >= lo) & (oos["vix_close"] < hi)
    n_days = zone_mask.sum()
    delta_s = z['sharpe'] - a['sharpe']
    print(f"{label:>12} {z['sharpe']:>10.3f} {z['ann_return']:>9.2%} {z['max_dd']:>9.2%} {z['calmar']:>10.2f} {n_days:>8d} {delta_s:>+10.3f}")


# Find optimal configuration
all_configs = [(label, zone_results[label]) for _, _, label in zone_configs]
all_configs += [(f"Std-{int(r*100)}%", sensitivity[f"DZ_red_{int(r*100)}pct"]) for r in reduction_levels]
best_config = max(all_configs, key=lambda x: x[1]["sharpe"])
print(f"\n  ** Best configuration: {best_config[0]}, Sharpe={best_config[1]['sharpe']:.3f} **")


print("\n" + "=" * 75)
print("ANALYSIS COMPLETE")
print("=" * 75)

# ==================================================================
# 7. Save results & Record to MemorySystem / Publisher
# ==================================================================
print("\n[6/6] Recording to MemorySystem and Publisher...")

sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research/src")
from volpred.memory.system import MemorySystem
from volpred.publisher.publisher import Publisher

storage_dir = "/Users/yhlai0911/Desktop/volpred-research/storage"
mem = MemorySystem(storage_dir=storage_dir)
pub = Publisher(storage_dir=storage_dir)

# Save results JSON
output = {
    "experiment": "vix_death_zone_enhanced",
    "date": datetime.now().isoformat(),
    "config": {
        "window": WINDOW,
        "vix_threshold": VIX_THRESHOLD,
        "death_zone": [DEATH_ZONE_LOW, DEATH_ZONE_HIGH],
        "death_zone_reduction": DEATH_ZONE_REDUCTION,
        "oos_start": str(oos.index[0].date()),
        "oos_end": str(oos.index[-1].date()),
        "oos_days": len(oos),
    },
    "standard_hybrid_vt": {
        "sharpe": round(a["sharpe"], 3),
        "ann_return": round(a["ann_return"], 4),
        "max_dd": round(a["max_dd"], 4),
        "calmar": round(a["calmar"], 2),
        "sortino": round(a["sortino"], 2),
    },
    "enhanced_hybrid_vt": {
        "sharpe": round(b["sharpe"], 3),
        "ann_return": round(b["ann_return"], 4),
        "max_dd": round(b["max_dd"], 4),
        "calmar": round(b["calmar"], 2),
        "sortino": round(b["sortino"], 2),
    },
    "delta": {
        "sharpe": round(b["sharpe"] - a["sharpe"], 3),
        "ann_return": round(b["ann_return"] - a["ann_return"], 4),
        "max_dd": round(b["max_dd"] - a["max_dd"], 4),
    },
    "sensitivity_reduction": {
        f"{int(r*100)}%": {
            "sharpe": round(sensitivity[f"DZ_red_{int(r*100)}pct"]["sharpe"], 3),
            "ann_return": round(sensitivity[f"DZ_red_{int(r*100)}pct"]["ann_return"], 4),
            "max_dd": round(sensitivity[f"DZ_red_{int(r*100)}pct"]["max_dd"], 4),
        }
        for r in reduction_levels
    },
    "sensitivity_zones": {
        label: {
            "sharpe": round(zone_results[label]["sharpe"], 3),
            "ann_return": round(zone_results[label]["ann_return"], 4),
            "max_dd": round(zone_results[label]["max_dd"], 4),
        }
        for _, _, label in zone_configs
    },
    "best_config": {
        "name": best_config[0],
        "sharpe": round(best_config[1]["sharpe"], 3),
    },
    "death_zone_stats": {
        "days": int(dz_days),
        "pct_of_oos": round(dz_pct, 1),
        "spy_ann_return_in_zone": round(float(oos.loc[in_death_zone, "returns"].mean() * 252), 4),
    },
}

out_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/vix_death_zone_enhanced/vix_death_zone_enhanced_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"  Results JSON saved to {out_path}")

# MemorySystem
mem.add_knowledge(
    category="strategy_enhancement",
    content=(
        f"VIX 15-18 死亡區間增強策略測試 (2018-2026)：當 VIX 在 15-18 時減少 {DEATH_ZONE_REDUCTION:.0%} 曝險。"
        f"標準 Hybrid VT Sharpe {a['sharpe']:.3f}, MaxDD {a['max_dd']:.2%}；"
        f"增強版 Sharpe {b['sharpe']:.3f}, MaxDD {b['max_dd']:.2%}。"
        f"Sharpe 差距 {b['sharpe']-a['sharpe']:+.3f}。"
        f"死亡區間佔 OOS {dz_pct:.1f}% 的交易日。"
        f"最佳配置：{best_config[0]}，Sharpe {best_config[1]['sharpe']:.3f}。"
    ),
    evidence=["vix_death_zone_enhanced"],
    confidence=0.85,
)

mem.think(
    thought=(
        f"VIX 15-18 死亡區間增強分析完成。\n"
        f"核心問題：VIX 15-18 歷史報酬約 -7.5%/yr，是否應在此區間積極減倉？\n"
        f"結果：\n"
        f"  Standard Hybrid VT: Sharpe {a['sharpe']:.3f}, MaxDD {a['max_dd']:.2%}\n"
        f"  Enhanced (-30% in VIX 15-18): Sharpe {b['sharpe']:.3f}, MaxDD {b['max_dd']:.2%}\n"
        f"  Delta Sharpe: {b['sharpe']-a['sharpe']:+.3f}\n"
        f"死亡區間佔 {dz_pct:.1f}% 交易日。\n"
        f"敏感度分析：減倉幅度 10-50% 和不同邊界 (13-22) 都做了測試。\n"
        f"最佳配置: {best_config[0]}, Sharpe {best_config[1]['sharpe']:.3f}"
    ),
    context="vix_death_zone_enhanced_analysis"
)

# Yearly detail strings
yearly_detail_lines = []
for yr in years:
    if yr in a["yearly"] and yr in b["yearly"]:
        yearly_detail_lines.append(
            f"| {yr} | {a['yearly'][yr]['sharpe']:.3f} | {b['yearly'][yr]['sharpe']:.3f} | "
            f"{b['yearly'][yr]['sharpe']-a['yearly'][yr]['sharpe']:+.3f} | "
            f"{a['yearly'][yr]['return']:.2%} | {b['yearly'][yr]['return']:.2%} |"
        )
yearly_table = "\n".join(yearly_detail_lines)

# Sensitivity lines
sens_lines = []
for red in reduction_levels:
    name = f"DZ_red_{int(red*100)}pct"
    s = sensitivity[name]
    sens_lines.append(f"| {int(red*100)}% | {s['sharpe']:.3f} | {s['ann_return']:.2%} | {s['max_dd']:.2%} | {s['sharpe']-a['sharpe']:+.3f} |")
sens_table = "\n".join(sens_lines)

# Zone boundary lines
zone_lines = []
for lo, hi, label in zone_configs:
    z = zone_results[label]
    zone_mask_temp = (oos["vix_close"] >= lo) & (oos["vix_close"] < hi)
    n_d = zone_mask_temp.sum()
    zone_lines.append(f"| {label} | {z['sharpe']:.3f} | {z['ann_return']:.2%} | {z['max_dd']:.2%} | {n_d} | {z['sharpe']-a['sharpe']:+.3f} |")
zone_table = "\n".join(zone_lines)

md_report = f"""## VIX 15-18 死亡區間增強 Hybrid VT 分析

### 研究假說
VIX 15-18 歷史年化報酬約 -7.5%，為「死亡區間」。假設在此區間更積極減倉可改善策略表現。

### 測試設計
- **Strategy A (標準)**: Hybrid VT，VIX/GARCH > 1.3 切換
- **Strategy B (增強)**: 同 A，但 VIX 在 15-18 時額外減倉 {DEATH_ZONE_REDUCTION:.0%}
- 模型: GJR-GARCH(1,1,1) w={WINDOW}
- OOS: {output['config']['oos_start']} ~ {output['config']['oos_end']} ({output['config']['oos_days']} 天)

### 主要結果

| 策略 | Sharpe | 年化報酬 | MaxDD | Calmar | Sortino |
|------|--------|----------|-------|--------|---------|
| **標準 Hybrid VT** | **{a['sharpe']:.3f}** | **{a['ann_return']:.2%}** | **{a['max_dd']:.2%}** | **{a['calmar']:.2f}** | **{a['sortino']:.2f}** |
| **增強 (-30% VIX 15-18)** | **{b['sharpe']:.3f}** | **{b['ann_return']:.2%}** | **{b['max_dd']:.2%}** | **{b['calmar']:.2f}** | **{b['sortino']:.2f}** |
| Delta (B-A) | {b['sharpe']-a['sharpe']:+.3f} | {b['ann_return']-a['ann_return']:+.2%} | {b['max_dd']-a['max_dd']:+.2%} | {b['calmar']-a['calmar']:+.2f} | {b['sortino']-a['sortino']:+.2f} |
| Buy & Hold | {results['BuyHold']['sharpe']:.3f} | {results['BuyHold']['ann_return']:.2%} | {results['BuyHold']['max_dd']:.2%} | {results['BuyHold']['calmar']:.2f} | {results['BuyHold']['sortino']:.2f} |

### 死亡區間統計
- VIX 15-18 交易日: {dz_days} 天 (佔 OOS {dz_pct:.1f}%)
- 死亡區間內 SPY 年化報酬: {float(oos.loc[in_death_zone, 'returns'].mean()*252):.2%}
- 標準策略平均權重 (死亡區間): {w_hybrid_std[in_death_zone.values].mean():.3f}
- 增強策略平均權重 (死亡區間): {w_hybrid_enhanced[in_death_zone.values].mean():.3f}

### 逐年比較

| 年份 | 標準 Sharpe | 增強 Sharpe | Delta | 標準報酬 | 增強報酬 |
|------|-------------|-------------|-------|----------|----------|
{yearly_table}

### 敏感度分析：減倉幅度

| 減倉 | Sharpe | 年化報酬 | MaxDD | vs 標準 |
|------|--------|----------|-------|---------|
| 0% (標準) | {a['sharpe']:.3f} | {a['ann_return']:.2%} | {a['max_dd']:.2%} | baseline |
{sens_table}

### 敏感度分析：區間邊界 (均 -30%)

| 區間 | Sharpe | 年化報酬 | MaxDD | 天數 | vs 標準 |
|------|--------|----------|-------|------|---------|
{zone_table}

### 最佳配置
**{best_config[0]}**，Sharpe = {best_config[1]['sharpe']:.3f}

### 結論
死亡區間增強策略的效果取決於減倉幅度和區間邊界的選擇。
分析結果顯示 Sharpe 差距為 {b['sharpe']-a['sharpe']:+.3f}。
"""

pub.publish_milestone(
    title="VIX 15-18 死亡區間增強 Hybrid VT 分析完成",
    description=md_report,
    phase="strategy_enhancement",
    details={
        "standard": output["standard_hybrid_vt"],
        "enhanced": output["enhanced_hybrid_vt"],
        "delta": output["delta"],
        "best_config": output["best_config"],
        "death_zone_stats": output["death_zone_stats"],
    }
)

print("  Knowledge and milestone published.")
print("\nDone!")
