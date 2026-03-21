"""
VIX-Zone Enhanced HVT: Cross-Period Validation (Rule 16)
=========================================================
The VIX-Zone Enhanced HVT showed +0.090 Sharpe improvement.
Per Rule 16, we must validate on 3 different periods.

Test periods:
  1. 2014-2018 (pre-COVID)
  2. 2019-2022 (COVID + rate hike)
  3. 2023-2026 (recovery + Iran)

Strategies:
  A. Standard HVT: GJR w=2000, VIX/GARCH > 1.3 switch, target 10%
  B. VIX-Zone Enhanced: same + VIX<14 boost 30%, VIX 14-18 reduce 20%

Criterion: Enhancement must win ALL 3 periods, or it's likely overfitted.
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

# VIX-Zone Enhancement parameters
VIX_LOW_THRESHOLD = 14.0    # VIX < 14: boost 30%
VIX_MID_LOW = 14.0          # VIX 14-18: reduce 20%
VIX_MID_HIGH = 18.0
BOOST_FACTOR = 0.30          # +30% weight when VIX < 14
REDUCE_FACTOR = 0.20         # -20% weight when VIX 14-18

# Test periods
PERIODS = [
    ("2014-2018 (pre-COVID)", "2014-01-02", "2018-12-31"),
    ("2019-2022 (COVID + rate hike)", "2019-01-02", "2022-12-31"),
    ("2023-2026 (recovery + Iran)", "2023-01-02", "2026-12-31"),
]

# Need enough lookback for w=2000
DATA_START = "2005-01-01"

print("=" * 80)
print("VIX-ZONE ENHANCED HVT: CROSS-PERIOD VALIDATION (Rule 16)")
print("=" * 80)
print(f"  Standard HVT: GJR w={WINDOW}, VIX/GARCH > {VIX_THRESHOLD} switch, target {TARGET_VOL_ANNUAL:.0%}")
print(f"  VIX-Zone Enhanced: + VIX<{VIX_LOW_THRESHOLD} boost {BOOST_FACTOR:.0%}, VIX {VIX_MID_LOW}-{VIX_MID_HIGH} reduce {REDUCE_FACTOR:.0%}")
print(f"  Test periods: {len(PERIODS)}")
for name, start, end in PERIODS:
    print(f"    {name}: {start} ~ {end}")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/4] Downloading SPY and VIX data...")

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
# 2. Rolling GJR-GARCH Forecast (full dataset)
# ==================================================================
print(f"\n[2/4] Running rolling GJR-GARCH(1,1,1) with w={WINDOW}...")

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
# 3. Strategy functions
# ==================================================================
def compute_strategy_metrics(weights, returns_arr, dates, name, rf_daily=RF_DAILY):
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
    monthly_rets = pd.Series(port_returns, index=dates).resample("ME").sum()
    win_rate = (monthly_rets > 0).mean()

    # Average weight
    avg_weight = np.mean(weights)

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
        "total_growth": cum_ret[-1],
        "total_years": total_years,
        "n_days": n,
    }


def run_period(period_name, start_date, end_date):
    """Run both strategies on a specific period."""
    # Filter to OOS period with valid GARCH
    oos_mask = (data.index >= start_date) & (data.index <= end_date) & data["garch_vol"].notna()
    oos = data[oos_mask].copy()

    if len(oos) < 50:
        print(f"  WARNING: Only {len(oos)} days for {period_name}, skipping")
        return None

    returns_arr = oos["returns"].values
    vix_vals = oos["vix_close"].values
    ratio_vals = oos["ratio"].values
    garch_vol_vals = oos["garch_vol"].values
    vix_daily_vals = oos["vix_daily"].values

    # --- GARCH-based weight ---
    w_garch = TARGET_VOL_DAILY / garch_vol_vals
    w_garch = np.clip(w_garch, 0, MAX_LEVERAGE)

    # --- VIX-based weight ---
    w_vix = TARGET_VOL_DAILY / vix_daily_vals
    w_vix = np.clip(w_vix, 0, MAX_LEVERAGE)

    # --- Strategy A: Standard HVT ---
    w_standard = np.where(ratio_vals > VIX_THRESHOLD, w_vix, w_garch)

    # --- Strategy B: VIX-Zone Enhanced ---
    w_enhanced = w_standard.copy()
    # VIX < 14: boost weight by 30%
    low_vix_mask = vix_vals < VIX_LOW_THRESHOLD
    w_enhanced[low_vix_mask] *= (1 + BOOST_FACTOR)
    # VIX 14-18: reduce weight by 20%
    mid_vix_mask = (vix_vals >= VIX_MID_LOW) & (vix_vals < VIX_MID_HIGH)
    w_enhanced[mid_vix_mask] *= (1 - REDUCE_FACTOR)
    # Cap at max leverage
    w_enhanced = np.clip(w_enhanced, 0, MAX_LEVERAGE)

    # --- Buy & Hold ---
    w_bh = np.ones(len(returns_arr))

    # Compute metrics
    res_standard = compute_strategy_metrics(w_standard, returns_arr, oos.index, "Standard HVT")
    res_enhanced = compute_strategy_metrics(w_enhanced, returns_arr, oos.index, "VIX-Zone Enhanced")
    res_bh = compute_strategy_metrics(w_bh, returns_arr, oos.index, "Buy & Hold")

    # VIX zone statistics
    n_low = low_vix_mask.sum()
    n_mid = mid_vix_mask.sum()
    n_high = (vix_vals >= VIX_MID_HIGH).sum()

    return {
        "period_name": period_name,
        "start": str(oos.index[0].date()),
        "end": str(oos.index[-1].date()),
        "n_days": len(oos),
        "standard": res_standard,
        "enhanced": res_enhanced,
        "buy_hold": res_bh,
        "delta_sharpe": res_enhanced["sharpe"] - res_standard["sharpe"],
        "enhanced_wins": res_enhanced["sharpe"] > res_standard["sharpe"],
        "vix_zones": {
            f"VIX<{VIX_LOW_THRESHOLD}": int(n_low),
            f"VIX {VIX_MID_LOW}-{VIX_MID_HIGH}": int(n_mid),
            f"VIX>={VIX_MID_HIGH}": int(n_high),
            f"pct_low": round(n_low / len(oos) * 100, 1),
            f"pct_mid": round(n_mid / len(oos) * 100, 1),
            f"pct_high": round(n_high / len(oos) * 100, 1),
        },
        "avg_vix": round(float(vix_vals.mean()), 1),
    }


# ==================================================================
# 4. Run all periods
# ==================================================================
print(f"\n[3/4] Running cross-period validation...")

all_results = []
for period_name, start, end in PERIODS:
    print(f"\n  --- {period_name} ---")
    result = run_period(period_name, start, end)
    if result is not None:
        all_results.append(result)
        print(f"    Days: {result['n_days']}, Avg VIX: {result['avg_vix']}")
        print(f"    Standard HVT:     Sharpe {result['standard']['sharpe']:.3f}, Ret {result['standard']['ann_return']:.2%}, MaxDD {result['standard']['max_dd']:.2%}")
        print(f"    VIX-Zone Enhanced: Sharpe {result['enhanced']['sharpe']:.3f}, Ret {result['enhanced']['ann_return']:.2%}, MaxDD {result['enhanced']['max_dd']:.2%}")
        print(f"    Buy & Hold:       Sharpe {result['buy_hold']['sharpe']:.3f}, Ret {result['buy_hold']['ann_return']:.2%}, MaxDD {result['buy_hold']['max_dd']:.2%}")
        print(f"    Delta Sharpe: {result['delta_sharpe']:+.3f} {'*** ENHANCED WINS ***' if result['enhanced_wins'] else '--- STANDARD WINS ---'}")
        print(f"    VIX Zones: <{VIX_LOW_THRESHOLD}: {result['vix_zones'][f'pct_low']:.1f}%, {VIX_MID_LOW}-{VIX_MID_HIGH}: {result['vix_zones'][f'pct_mid']:.1f}%, >={VIX_MID_HIGH}: {result['vix_zones'][f'pct_high']:.1f}%")

# ==================================================================
# 5. Summary and Verdict
# ==================================================================
print("\n" + "=" * 80)
print("[4/4] CROSS-PERIOD VALIDATION SUMMARY")
print("=" * 80)

print(f"\n{'Period':<35} {'Standard':>10} {'Enhanced':>10} {'Delta':>10} {'Winner':>15}")
print("-" * 85)

n_wins = 0
for r in all_results:
    winner = "Enhanced" if r["enhanced_wins"] else "Standard"
    if r["enhanced_wins"]:
        n_wins += 1
    print(f"{r['period_name']:<35} {r['standard']['sharpe']:>10.3f} {r['enhanced']['sharpe']:>10.3f} {r['delta_sharpe']:>+10.3f} {winner:>15}")

avg_delta = np.mean([r["delta_sharpe"] for r in all_results])
print("-" * 85)
print(f"{'Average Delta':<35} {'':>10} {'':>10} {avg_delta:>+10.3f}")

print(f"\n  Enhanced wins: {n_wins}/{len(all_results)} periods")

if n_wins == len(all_results):
    verdict = "PASS - VIX-Zone Enhancement is GENUINE improvement (wins ALL periods)"
    is_overfitted = False
else:
    verdict = f"FAIL - VIX-Zone Enhancement is LIKELY OVERFITTED (wins only {n_wins}/{len(all_results)} periods)"
    is_overfitted = True

print(f"\n  *** VERDICT: {verdict} ***")

# Detailed metrics table
print("\n\nDetailed Metrics by Period:")
print("-" * 100)
print(f"{'Period':<35} {'Strat':<12} {'Sharpe':>8} {'Ret':>10} {'Vol':>8} {'MaxDD':>10} {'Calmar':>8} {'Sortino':>8}")
print("-" * 100)
for r in all_results:
    for strat_key, label in [("standard", "Standard"), ("enhanced", "Enhanced"), ("buy_hold", "B&H")]:
        s = r[strat_key]
        pname = r["period_name"] if label == "Standard" else ""
        print(f"{pname:<35} {label:<12} {s['sharpe']:>8.3f} {s['ann_return']:>9.2%} {s['ann_vol']:>7.2%} {s['max_dd']:>9.2%} {s['calmar']:>8.2f} {s['sortino']:>8.2f}")
    print()

# VIX Zone distribution
print("\nVIX Zone Distribution by Period:")
print("-" * 80)
print(f"{'Period':<35} {'VIX<14':>10} {'VIX 14-18':>12} {'VIX>=18':>10} {'Avg VIX':>10}")
print("-" * 80)
for r in all_results:
    print(f"{r['period_name']:<35} {r['vix_zones']['pct_low']:.1f}%{'':<5} {r['vix_zones']['pct_mid']:.1f}%{'':<7} {r['vix_zones']['pct_high']:.1f}%{'':<5} {r['avg_vix']:.1f}")

# ==================================================================
# 6. Save Results & Record to MemorySystem + Publisher
# ==================================================================
print("\n[5/5] Recording to MemorySystem and Publisher...")

sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research/src")
from volpred.memory.system import MemorySystem
from volpred.publisher.publisher import Publisher

storage_dir = "/Users/yhlai0911/Desktop/volpred-research/storage"
mem = MemorySystem(storage_dir=storage_dir)
pub = Publisher(storage_dir=storage_dir)

# Save results JSON
output = {
    "experiment": "vix_zone_cross_period_validation",
    "rule": "Rule 16 cross-period validation",
    "date": datetime.now().isoformat(),
    "config": {
        "window": WINDOW,
        "vix_threshold": VIX_THRESHOLD,
        "target_vol": TARGET_VOL_ANNUAL,
        "vix_low_threshold": VIX_LOW_THRESHOLD,
        "vix_mid_range": [VIX_MID_LOW, VIX_MID_HIGH],
        "boost_factor": BOOST_FACTOR,
        "reduce_factor": REDUCE_FACTOR,
    },
    "periods": [],
    "verdict": verdict,
    "is_overfitted": is_overfitted,
    "n_wins": n_wins,
    "n_periods": len(all_results),
    "avg_delta_sharpe": round(avg_delta, 4),
}

for r in all_results:
    period_data = {
        "name": r["period_name"],
        "start": r["start"],
        "end": r["end"],
        "n_days": r["n_days"],
        "avg_vix": r["avg_vix"],
        "standard_sharpe": round(r["standard"]["sharpe"], 3),
        "enhanced_sharpe": round(r["enhanced"]["sharpe"], 3),
        "bh_sharpe": round(r["buy_hold"]["sharpe"], 3),
        "delta_sharpe": round(r["delta_sharpe"], 3),
        "enhanced_wins": r["enhanced_wins"],
        "standard_ann_return": round(r["standard"]["ann_return"], 4),
        "enhanced_ann_return": round(r["enhanced"]["ann_return"], 4),
        "standard_max_dd": round(r["standard"]["max_dd"], 4),
        "enhanced_max_dd": round(r["enhanced"]["max_dd"], 4),
        "vix_zones": r["vix_zones"],
    }
    output["periods"].append(period_data)

out_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/vix_zone_cross_period_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"  Results JSON saved to {out_path}")

# Build period summary table for reports
period_lines = []
for p in output["periods"]:
    winner = "Enhanced" if p["enhanced_wins"] else "Standard"
    period_lines.append(
        f"| {p['name']} | {p['standard_sharpe']:.3f} | {p['enhanced_sharpe']:.3f} | "
        f"{p['delta_sharpe']:+.3f} | {winner} | {p['avg_vix']} |"
    )
period_table = "\n".join(period_lines)

# Detailed lines
detail_lines = []
for r in all_results:
    for strat_key, label in [("standard", "Standard"), ("enhanced", "Enhanced")]:
        s = r[strat_key]
        detail_lines.append(
            f"| {r['period_name']} | {label} | {s['sharpe']:.3f} | {s['ann_return']:.2%} | "
            f"{s['ann_vol']:.2%} | {s['max_dd']:.2%} | {s['calmar']:.2f} | {s['sortino']:.2f} |"
        )
detail_table = "\n".join(detail_lines)

# VIX zone lines
zone_lines = []
for r in all_results:
    zone_lines.append(
        f"| {r['period_name']} | {r['vix_zones']['pct_low']:.1f}% | "
        f"{r['vix_zones']['pct_mid']:.1f}% | {r['vix_zones']['pct_high']:.1f}% | {r['avg_vix']} |"
    )
zone_table = "\n".join(zone_lines)

# MemorySystem: knowledge
mem.add_knowledge(
    category="cross_period_validation",
    content=(
        f"Rule 16 跨期驗證：VIX-Zone Enhanced HVT。"
        f"3 個時期測試：{'; '.join(p['name'] + ' delta ' + format(p['delta_sharpe'], '+.3f') for p in output['periods'])}。"
        f"Enhanced 勝出 {n_wins}/{len(all_results)} 個時期。"
        f"平均 delta Sharpe: {avg_delta:+.3f}。"
        f"判定：{'通過 — 真實改善' if not is_overfitted else '未通過 — 可能過擬合'}。"
    ),
    evidence=["vix_zone_cross_period_validation", "Rule_16"],
    confidence=0.90 if not is_overfitted else 0.75,
)

# MemorySystem: thinking
mem.think(
    thought=(
        f"Rule 16 跨期驗證完成。VIX-Zone Enhanced HVT 在 3 個不同時期（2014-2018, 2019-2022, 2023-2026）進行測試。\n"
        f"結果：Enhanced 勝出 {n_wins}/{len(all_results)} 期，平均 delta Sharpe {avg_delta:+.3f}。\n"
        + "\n".join(f"  {p['name']}: Standard {p['standard_sharpe']:.3f}, Enhanced {p['enhanced_sharpe']:.3f}, delta {p['delta_sharpe']:+.3f}" for p in output["periods"])
        + f"\n判定：{'通過 — VIX-Zone Enhancement 是真實改善' if not is_overfitted else '未通過 — VIX-Zone Enhancement 可能是過擬合'}。"
        + f"\n{'如果沒有在所有時期勝出，boost/reduce 的參數可能只在特定 VIX 環境下有效。' if is_overfitted else '在不同 VIX 環境下皆有效，機制穩健。'}"
    ),
    context="Rule 16 cross-period validation"
)

# Publisher: milestone
md_report = f"""## VIX-Zone Enhanced HVT：Rule 16 跨期驗證

### 驗證目的
VIX-Zone Enhanced HVT 在原始測試中顯示 +0.090 Sharpe 改善。
依 Rule 16，需在 3 個不同時期驗證，若無法全部勝出則判定為過擬合。

### 策略規格
- **Standard HVT**: GJR-GARCH w={WINDOW}, VIX/GARCH > {VIX_THRESHOLD} 切換, 目標波動率 {TARGET_VOL_ANNUAL:.0%}
- **VIX-Zone Enhanced**: 同上 + VIX < {VIX_LOW_THRESHOLD} 加碼 {BOOST_FACTOR:.0%}, VIX {VIX_MID_LOW}-{VIX_MID_HIGH} 減碼 {REDUCE_FACTOR:.0%}

### 跨期比較

| 時期 | Standard Sharpe | Enhanced Sharpe | Delta | Winner | Avg VIX |
|------|----------------|-----------------|-------|--------|---------|
{period_table}

**平均 Delta Sharpe: {avg_delta:+.3f}**
**Enhanced 勝出: {n_wins}/{len(all_results)} 時期**

### 詳細指標

| 時期 | 策略 | Sharpe | 年化報酬 | 年化波動 | MaxDD | Calmar | Sortino |
|------|------|--------|----------|----------|-------|--------|---------|
{detail_table}

### VIX 區間分佈

| 時期 | VIX<14 | VIX 14-18 | VIX>=18 | Avg VIX |
|------|--------|-----------|---------|---------|
{zone_table}

### 判定

**{'PASS: VIX-Zone Enhancement 是真實改善' if not is_overfitted else 'FAIL: VIX-Zone Enhancement 可能是過擬合'}**

{'Enhancement 在所有 3 個不同市場環境中均提升 Sharpe，機制穩健。' if not is_overfitted else f'Enhancement 僅在 {n_wins}/{len(all_results)} 個時期勝出，建議不採用此增強。'}
"""

pub.publish_milestone(
    title=f"Rule 16 跨期驗證：VIX-Zone Enhanced HVT {'PASS' if not is_overfitted else 'FAIL'}",
    description=md_report,
    phase="cross_period_validation",
    details={
        "verdict": verdict,
        "is_overfitted": is_overfitted,
        "n_wins": n_wins,
        "n_periods": len(all_results),
        "avg_delta_sharpe": round(avg_delta, 4),
        "periods": output["periods"],
    }
)

print("  Knowledge, thinking, and milestone published.")
print(f"\n{'=' * 80}")
print(f"VERDICT: {verdict}")
print(f"{'=' * 80}")
print("\nDone!")
