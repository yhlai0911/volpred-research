"""
K204: GLD Momentum-Based VT — Can We Exploit K203's Finding?
=============================================================
[提出: 用戶, 執行: Claude]

Background:
  K203 found GLD 12-1 month momentum has partial r=0.39 with future GLD vol,
  passing Harvey threshold (t=6.5). Can we use this to build a GLD-specific VT
  that beats the standard 12/VIX approach?

Methodology:
  1. GLD momentum features:
     - MOM_12_1: trailing 12-month return excluding last month
     - MOM_6_1: trailing 6-month return excluding last month
     - |MOM|: absolute momentum (distance from zero)
  2. VT strategies for 50/50 SPY/GLD portfolio:
     - Base: 12/VIX monthly rebalancing
     - MOM overlay: when GLD |MOM_12_1| > 80th pctl, reduce GLD alloc by 30%
     - MOM regime: high GLD momentum -> lower vol target for GLD component
     - Combined: 12/VIX for SPY + MOM-adjusted for GLD
  3. 5-period cross-OOS validation (MANDATORY)
  4. Harvey t>3.0 for strategy claims

Data: GLD, SPY, VIX daily from yfinance. OOS: 5 periods (2015-2024, 2yr each).
TX cost: 0.1% per trade.
"""

import json
import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from pathlib import Path
from datetime import datetime

# =====================================================================
# CONFIG
# =====================================================================
TARGET_VOL_ANNUAL = 0.12  # 12% annual vol target
MAX_LEVERAGE = 1.5
TX_COST = 0.001  # 0.1% per trade
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

DATA_START = "2004-01-01"
# 5-period cross-OOS: each ~2 years
OOS_PERIODS = [
    ("2015-01-01", "2016-12-31"),
    ("2017-01-01", "2018-12-31"),
    ("2019-01-01", "2020-12-31"),
    ("2021-01-01", "2022-12-31"),
    ("2023-01-01", "2024-12-31"),
]

# Momentum parameters
MOM_LOOKBACK_12 = 252  # ~12 months
MOM_LOOKBACK_6 = 126   # ~6 months
MOM_SKIP = 21          # skip last month (momentum crash avoidance)
MOM_PERCENTILE = 80    # threshold for "extreme" momentum
GLD_REDUCTION = 0.30   # reduce GLD allocation by 30% when momentum extreme
LOW_VOL_TARGET_MULT = 0.70  # use 70% of normal vol target in high-mom regime

REBAL_FREQ = 21  # monthly rebalancing (trading days)

print("=" * 78)
print("K204: GLD MOMENTUM-BASED VT — CAN WE EXPLOIT K203'S FINDING?")
print("=" * 78)

# =====================================================================
# 1. DOWNLOAD DATA
# =====================================================================
print("\n[1/6] Downloading SPY, GLD, ^VIX data...")

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end="2025-12-31",
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df[["Close"]].rename(columns={"Close": name})

# Merge on common dates
merged = raw["SPY"]
for name in ["GLD", "VIX"]:
    merged = merged.join(raw[name], how="inner")
merged = merged.dropna()

# Log returns
for asset in ["SPY", "GLD"]:
    merged[f"{asset}_ret"] = np.log(merged[asset] / merged[asset].shift(1))
merged = merged.dropna()

# VIX daily vol
merged["VIX_daily"] = merged["VIX"] / 100 / np.sqrt(252)

print(f"  Data range: {merged.index[0].date()} to {merged.index[-1].date()}")
print(f"  Total trading days: {len(merged)}")
print(f"  GLD first date: {raw['GLD'].dropna().index[0].date()}")

# =====================================================================
# 2. COMPUTE GLD MOMENTUM FEATURES
# =====================================================================
print("\n[2/6] Computing GLD momentum features...")

# Cumulative log return for rolling windows
gld_log_price = np.log(merged["GLD"])

# MOM_12_1: return from t-252 to t-21 (12 months excluding last month)
merged["GLD_MOM_12_1"] = gld_log_price.shift(MOM_SKIP) - gld_log_price.shift(MOM_LOOKBACK_12)
# MOM_6_1: return from t-126 to t-21
merged["GLD_MOM_6_1"] = gld_log_price.shift(MOM_SKIP) - gld_log_price.shift(MOM_LOOKBACK_6)
# Absolute momentum
merged["GLD_ABS_MOM_12_1"] = merged["GLD_MOM_12_1"].abs()
merged["GLD_ABS_MOM_6_1"] = merged["GLD_MOM_6_1"].abs()

# Expanding percentile rank of |MOM| (avoid look-ahead)
merged["GLD_ABS_MOM_12_1_pctrank"] = merged["GLD_ABS_MOM_12_1"].expanding(min_periods=252).rank(pct=True) * 100

# Also compute realized vol for GLD (21-day)
merged["GLD_RV21"] = merged["GLD_ret"].rolling(21).std() * np.sqrt(252)

# Drop rows without momentum
mom_valid = merged.dropna(subset=["GLD_MOM_12_1", "GLD_ABS_MOM_12_1_pctrank"])
print(f"  Momentum features available from: {mom_valid.index[0].date()}")
print(f"  Rows with valid momentum: {len(mom_valid)}")

# Quick diagnostic: correlation of |MOM| with future realized vol
future_rv = merged["GLD_RV21"].shift(-21)  # 21 days ahead
valid_corr = merged.dropna(subset=["GLD_ABS_MOM_12_1"]).copy()
valid_corr["future_rv"] = future_rv
valid_corr = valid_corr.dropna(subset=["future_rv"])
r, p = stats.pearsonr(valid_corr["GLD_ABS_MOM_12_1"], valid_corr["future_rv"])
print(f"  |MOM_12_1| vs future 21d RV: r={r:.3f}, p={p:.4f}")

# =====================================================================
# 3. DEFINE VT STRATEGIES
# =====================================================================
print("\n[3/6] Defining VT strategies...")


def compute_vix_weight(vix_val, target_vol=TARGET_VOL_ANNUAL):
    """Standard 12/VIX weight, capped at MAX_LEVERAGE."""
    vix_ann = vix_val / 100 if vix_val > 1 else vix_val  # handle both formats
    if vix_ann <= 0:
        return 1.0
    w = target_vol / vix_ann
    return min(w, MAX_LEVERAGE)


def run_strategy(data, oos_start, oos_end, strategy_name="base"):
    """
    Run a VT strategy on 50/50 SPY/GLD portfolio.

    Strategies:
    - "base": standard 12/VIX monthly rebal for both SPY and GLD
    - "mom_overlay": reduce GLD when |MOM_12_1| > 80th pctl
    - "mom_regime": lower GLD vol target when high momentum
    - "combined": 12/VIX for SPY + MOM-adjusted for GLD
    - "buyhold": static 50/50 buy-and-hold (no VT)
    """
    # Filter to OOS period
    mask = (data.index >= oos_start) & (data.index <= oos_end)
    oos = data.loc[mask].copy()

    if len(oos) < 100:
        return None

    # Pre-OOS lookback for expanding percentile (use all data up to OOS start)
    pre_oos = data.loc[data.index < oos_start].copy()

    port_returns = []
    port_weights_spy = []
    port_weights_gld = []
    rebal_dates = []

    # Track last rebalance for monthly frequency
    last_rebal_idx = -REBAL_FREQ  # force rebal on first day
    current_w_spy = 0.5
    current_w_gld = 0.5
    prev_w_spy = 0.5
    prev_w_gld = 0.5

    for i, (date, row) in enumerate(oos.iterrows()):
        # Monthly rebalancing check
        if i - last_rebal_idx >= REBAL_FREQ:
            last_rebal_idx = i

            vix_val = row["VIX"]
            vix_weight = compute_vix_weight(vix_val)

            if strategy_name == "base":
                # Standard 12/VIX for both, 50/50 split
                current_w_spy = 0.5 * vix_weight
                current_w_gld = 0.5 * vix_weight

            elif strategy_name == "mom_overlay":
                # Base 12/VIX, but reduce GLD when |MOM| is extreme
                abs_mom_pctrank = row.get("GLD_ABS_MOM_12_1_pctrank", 50)
                if pd.notna(abs_mom_pctrank) and abs_mom_pctrank > MOM_PERCENTILE:
                    # High momentum -> reduce GLD, keep SPY same
                    current_w_spy = 0.5 * vix_weight
                    current_w_gld = 0.5 * vix_weight * (1 - GLD_REDUCTION)
                else:
                    current_w_spy = 0.5 * vix_weight
                    current_w_gld = 0.5 * vix_weight

            elif strategy_name == "mom_regime":
                # Lower vol target for GLD when momentum is high
                abs_mom_pctrank = row.get("GLD_ABS_MOM_12_1_pctrank", 50)
                if pd.notna(abs_mom_pctrank) and abs_mom_pctrank > MOM_PERCENTILE:
                    # Use reduced vol target for GLD component
                    gld_target = TARGET_VOL_ANNUAL * LOW_VOL_TARGET_MULT
                    gld_vix_weight = compute_vix_weight(vix_val, target_vol=gld_target)
                    current_w_spy = 0.5 * vix_weight
                    current_w_gld = 0.5 * gld_vix_weight
                else:
                    current_w_spy = 0.5 * vix_weight
                    current_w_gld = 0.5 * vix_weight

            elif strategy_name == "combined":
                # SPY: standard 12/VIX
                # GLD: 12/VIX base + MOM overlay + MOM regime blend
                abs_mom_pctrank = row.get("GLD_ABS_MOM_12_1_pctrank", 50)
                current_w_spy = 0.5 * vix_weight

                if pd.notna(abs_mom_pctrank) and abs_mom_pctrank > MOM_PERCENTILE:
                    # Blend: reduce allocation AND lower vol target
                    gld_target = TARGET_VOL_ANNUAL * LOW_VOL_TARGET_MULT
                    gld_vix_weight = compute_vix_weight(vix_val, target_vol=gld_target)
                    current_w_gld = 0.5 * gld_vix_weight * (1 - GLD_REDUCTION)
                else:
                    current_w_gld = 0.5 * vix_weight

            elif strategy_name == "buyhold":
                current_w_spy = 0.5
                current_w_gld = 0.5

            # Cap leverage
            current_w_spy = min(current_w_spy, MAX_LEVERAGE * 0.5)
            current_w_gld = min(current_w_gld, MAX_LEVERAGE * 0.5)

        # Compute portfolio return
        spy_ret = row["SPY_ret"]
        gld_ret = row["GLD_ret"]
        port_ret = current_w_spy * spy_ret + current_w_gld * gld_ret

        # Transaction costs on rebalance
        if i == last_rebal_idx:
            turnover = abs(current_w_spy - prev_w_spy) + abs(current_w_gld - prev_w_gld)
            tx_cost = turnover * TX_COST
            port_ret -= tx_cost
            rebal_dates.append(date)

        port_returns.append(port_ret)
        port_weights_spy.append(current_w_spy)
        port_weights_gld.append(current_w_gld)
        prev_w_spy = current_w_spy
        prev_w_gld = current_w_gld

    # Rest is in cash earning risk-free
    cash_weight = 1.0 - np.array(port_weights_spy) - np.array(port_weights_gld)
    cash_weight = np.maximum(cash_weight, 0)
    port_returns = np.array(port_returns) + cash_weight * RF_DAILY

    return {
        "returns": port_returns,
        "dates": oos.index.tolist(),
        "weights_spy": port_weights_spy,
        "weights_gld": port_weights_gld,
        "n_rebals": len(rebal_dates),
    }


def compute_metrics(returns, label=""):
    """Compute strategy performance metrics."""
    if returns is None or len(returns) < 50:
        return None

    ann_ret = np.mean(returns) * 252
    ann_vol = np.std(returns, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = np.cumsum(returns)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum - running_max
    mdd = np.min(drawdown)

    # Calmar
    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Sortino
    downside = returns[returns < 0]
    down_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - RF_ANNUAL) / down_vol if down_vol > 0 else 0

    # Turnover (approximate via weight changes)
    n_years = len(returns) / 252

    return {
        "label": label,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "n_days": len(returns),
        "n_years": n_years,
    }


# =====================================================================
# 4. RUN 5-PERIOD CROSS-OOS VALIDATION
# =====================================================================
print("\n[4/6] Running 5-period cross-OOS validation...")

strategies = ["base", "mom_overlay", "mom_regime", "combined", "buyhold"]
all_results = {s: [] for s in strategies}
all_sharpes = {s: [] for s in strategies}
all_mdds = {s: [] for s in strategies}

for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
    print(f"\n  --- OOS Period {period_idx+1}: {oos_start} to {oos_end} ---")

    for strat in strategies:
        result = run_strategy(merged, oos_start, oos_end, strategy_name=strat)
        if result is None:
            print(f"    {strat:15s}: SKIPPED (insufficient data)")
            continue

        metrics = compute_metrics(result["returns"], label=f"{strat}_P{period_idx+1}")
        if metrics is None:
            print(f"    {strat:15s}: SKIPPED (too few returns)")
            continue

        all_results[strat].append(metrics)
        all_sharpes[strat].append(metrics["sharpe"])
        all_mdds[strat].append(metrics["mdd"])

        print(f"    {strat:15s}: Sharpe={metrics['sharpe']:+.3f}  "
              f"MDD={metrics['mdd']:+.1%}  Ann.Ret={metrics['ann_ret']:+.1%}  "
              f"Calmar={metrics['calmar']:.3f}  N={metrics['n_days']}")

# =====================================================================
# 5. STATISTICAL TESTS
# =====================================================================
print("\n" + "=" * 78)
print("[5/6] STATISTICAL ANALYSIS")
print("=" * 78)

# 5a. Cross-OOS summary
print("\n--- Cross-OOS Summary (5 periods) ---")
print(f"{'Strategy':15s} | {'Mean Sharpe':>12s} | {'Std Sharpe':>10s} | {'t-stat':>8s} | "
      f"{'Mean MDD':>10s} | {'Win vs Base':>12s}")
print("-" * 85)

base_sharpes = all_sharpes.get("base", [])

for strat in strategies:
    sharpes = all_sharpes[strat]
    mdds = all_mdds[strat]

    if len(sharpes) < 2:
        print(f"  {strat:15s}: insufficient data")
        continue

    mean_s = np.mean(sharpes)
    std_s = np.std(sharpes, ddof=1)
    se_s = std_s / np.sqrt(len(sharpes))
    t_stat = mean_s / se_s if se_s > 0 else 0
    mean_mdd = np.mean(mdds)

    # Win rate vs base
    if strat != "base" and len(base_sharpes) == len(sharpes):
        wins = sum(1 for s, b in zip(sharpes, base_sharpes) if s > b)
        win_str = f"{wins}/{len(sharpes)}"
    else:
        win_str = "—"

    print(f"  {strat:15s} | {mean_s:+12.3f} | {std_s:10.3f} | {t_stat:+8.2f} | "
          f"{mean_mdd:+10.1%} | {win_str:>12s}")

# 5b. Paired t-test: each momentum strategy vs base
print("\n--- Paired t-tests vs Base (Sharpe difference) ---")
for strat in ["mom_overlay", "mom_regime", "combined"]:
    if len(all_sharpes[strat]) != len(base_sharpes) or len(base_sharpes) < 3:
        print(f"  {strat}: cannot test (insufficient periods)")
        continue

    diffs = [s - b for s, b in zip(all_sharpes[strat], base_sharpes)]
    mean_diff = np.mean(diffs)
    std_diff = np.std(diffs, ddof=1)
    se_diff = std_diff / np.sqrt(len(diffs))
    t_paired = mean_diff / se_diff if se_diff > 0 else 0
    p_paired = 2 * (1 - stats.t.cdf(abs(t_paired), df=len(diffs) - 1))

    print(f"  {strat:15s}: ΔSharpe={mean_diff:+.4f}, t={t_paired:+.3f}, p={p_paired:.4f}"
          f"  {'*** SIGNIFICANT' if p_paired < 0.05 else '(n.s.)'}")

# 5c. Paired t-test on MDD
print("\n--- Paired t-tests vs Base (MDD difference) ---")
for strat in ["mom_overlay", "mom_regime", "combined"]:
    if len(all_mdds[strat]) != len(all_mdds["base"]) or len(all_mdds["base"]) < 3:
        print(f"  {strat}: cannot test (insufficient periods)")
        continue

    diffs = [s - b for s, b in zip(all_mdds[strat], all_mdds["base"])]
    mean_diff = np.mean(diffs)
    std_diff = np.std(diffs, ddof=1)
    se_diff = std_diff / np.sqrt(len(diffs))
    t_paired = mean_diff / se_diff if se_diff > 0 else 0
    # One-sided: is MDD less negative (better)?
    # MDD is negative, so improvement = positive diff
    p_paired = 1 - stats.t.cdf(t_paired, df=len(diffs) - 1)

    print(f"  {strat:15s}: ΔMDD={mean_diff:+.4f}, t={t_paired:+.3f}, p={p_paired:.4f}"
          f"  {'*** SIGNIFICANT' if p_paired < 0.05 else '(n.s.)'}")

# 5d. Harvey threshold check
print("\n--- Harvey (2016) Multiple Testing Threshold ---")
print("  Required t > 3.0 for new strategy claims")
for strat in ["mom_overlay", "mom_regime", "combined"]:
    if len(all_sharpes[strat]) < 2:
        continue
    sharpes = all_sharpes[strat]
    mean_s = np.mean(sharpes)
    std_s = np.std(sharpes, ddof=1)
    t_stat = mean_s / (std_s / np.sqrt(len(sharpes))) if std_s > 0 else 0
    passes = "PASS" if abs(t_stat) > 3.0 else "FAIL"
    print(f"  {strat:15s}: t={t_stat:+.2f}  [{passes}]")

# 5e. Full sample analysis
print("\n--- Full Sample Analysis (all OOS combined) ---")
for strat in strategies:
    all_rets = []
    for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
        result = run_strategy(merged, oos_start, oos_end, strategy_name=strat)
        if result is not None:
            all_rets.extend(result["returns"].tolist())

    if len(all_rets) > 100:
        all_rets = np.array(all_rets)
        m = compute_metrics(all_rets, label=f"{strat}_FULL")
        if m:
            print(f"  {strat:15s}: Sharpe={m['sharpe']:+.3f}  MDD={m['mdd']:+.1%}  "
                  f"Ann.Ret={m['ann_ret']:+.1%}  Sortino={m['sortino']:+.3f}  "
                  f"Calmar={m['calmar']:.3f}  N={m['n_days']}")

# =====================================================================
# 6. DETAILED DIAGNOSTICS
# =====================================================================
print("\n" + "=" * 78)
print("[6/6] DETAILED DIAGNOSTICS")
print("=" * 78)

# 6a. Weight analysis for momentum strategies
print("\n--- Weight Analysis: How often does momentum overlay trigger? ---")
for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
    mask = (merged.index >= oos_start) & (merged.index <= oos_end)
    oos = merged.loc[mask]
    if len(oos) == 0:
        continue

    pctrank = oos["GLD_ABS_MOM_12_1_pctrank"]
    n_valid = pctrank.notna().sum()
    n_triggered = (pctrank > MOM_PERCENTILE).sum()
    pct_triggered = n_triggered / n_valid * 100 if n_valid > 0 else 0

    # Average |MOM| when triggered vs not
    triggered = oos.loc[pctrank > MOM_PERCENTILE, "GLD_ABS_MOM_12_1"]
    not_triggered = oos.loc[pctrank <= MOM_PERCENTILE, "GLD_ABS_MOM_12_1"]

    print(f"  P{period_idx+1} ({oos_start[:4]}-{oos_end[:4]}): "
          f"triggered {n_triggered}/{n_valid} ({pct_triggered:.1f}%), "
          f"|MOM| triggered={triggered.mean():.4f} vs normal={not_triggered.mean():.4f}")

# 6b. Correlation between momentum and subsequent GLD return
print("\n--- Momentum vs Subsequent GLD Returns (21-day forward) ---")
future_gld_ret = merged["GLD_ret"].rolling(21).sum().shift(-21)
valid = merged.dropna(subset=["GLD_ABS_MOM_12_1"]).copy()
valid["future_gld_ret_21d"] = future_gld_ret
valid = valid.dropna(subset=["future_gld_ret_21d"])

r_mom_ret, p_mom_ret = stats.pearsonr(valid["GLD_ABS_MOM_12_1"], valid["future_gld_ret_21d"])
r_mom_ret6, p_mom_ret6 = stats.pearsonr(valid["GLD_ABS_MOM_6_1"], valid["future_gld_ret_21d"])

print(f"  |MOM_12_1| vs 21d fwd GLD return: r={r_mom_ret:.3f}, p={p_mom_ret:.4f}")
print(f"  |MOM_6_1|  vs 21d fwd GLD return: r={r_mom_ret6:.3f}, p={p_mom_ret6:.4f}")

# Signed momentum vs return (is there continuation or reversal?)
r_signed, p_signed = stats.pearsonr(valid["GLD_MOM_12_1"], valid["future_gld_ret_21d"])
print(f"  MOM_12_1 (signed) vs 21d fwd ret: r={r_signed:.3f}, p={p_signed:.4f}")
print(f"  => {'Continuation (momentum)' if r_signed > 0 else 'Reversal (mean-reversion)'}")

# 6c. Alternative thresholds sensitivity
print("\n--- Sensitivity Analysis: Percentile Threshold ---")
for pct in [60, 70, 80, 90, 95]:
    test_sharpes = []
    for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
        # Run overlay with different threshold
        mask = (merged.index >= oos_start) & (merged.index <= oos_end)
        oos = merged.loc[mask].copy()
        if len(oos) < 100:
            continue

        port_returns = []
        last_rebal_idx = -REBAL_FREQ
        current_w_spy = 0.5
        current_w_gld = 0.5
        prev_w_spy = 0.5
        prev_w_gld = 0.5

        for i, (date, row) in enumerate(oos.iterrows()):
            if i - last_rebal_idx >= REBAL_FREQ:
                last_rebal_idx = i
                vix_val = row["VIX"]
                vix_weight = compute_vix_weight(vix_val)
                abs_mom_pctrank = row.get("GLD_ABS_MOM_12_1_pctrank", 50)

                if pd.notna(abs_mom_pctrank) and abs_mom_pctrank > pct:
                    current_w_spy = 0.5 * vix_weight
                    current_w_gld = 0.5 * vix_weight * (1 - GLD_REDUCTION)
                else:
                    current_w_spy = 0.5 * vix_weight
                    current_w_gld = 0.5 * vix_weight

                current_w_spy = min(current_w_spy, MAX_LEVERAGE * 0.5)
                current_w_gld = min(current_w_gld, MAX_LEVERAGE * 0.5)

            spy_ret = row["SPY_ret"]
            gld_ret = row["GLD_ret"]
            port_ret = current_w_spy * spy_ret + current_w_gld * gld_ret

            if i == last_rebal_idx:
                turnover = abs(current_w_spy - prev_w_spy) + abs(current_w_gld - prev_w_gld)
                port_ret -= turnover * TX_COST

            cash_w = max(0, 1.0 - current_w_spy - current_w_gld)
            port_ret += cash_w * RF_DAILY

            port_returns.append(port_ret)
            prev_w_spy = current_w_spy
            prev_w_gld = current_w_gld

        m = compute_metrics(np.array(port_returns))
        if m:
            test_sharpes.append(m["sharpe"])

    if test_sharpes:
        mean_s = np.mean(test_sharpes)
        base_mean = np.mean(base_sharpes) if base_sharpes else 0
        diff = mean_s - base_mean
        print(f"  Pctl={pct:3d}: Mean Sharpe={mean_s:+.3f}  (Δ vs base: {diff:+.4f})")

# 6d. Alternative: MOM_6_1 instead of MOM_12_1
print("\n--- Alternative: 6-month momentum (MOM_6_1) overlay ---")
# Compute 6-month expanding percentile rank
merged["GLD_ABS_MOM_6_1_pctrank"] = merged["GLD_ABS_MOM_6_1"].expanding(min_periods=126).rank(pct=True) * 100

mom6_sharpes = []
for period_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
    mask = (merged.index >= oos_start) & (merged.index <= oos_end)
    oos = merged.loc[mask].copy()
    if len(oos) < 100:
        continue

    port_returns = []
    last_rebal_idx = -REBAL_FREQ
    current_w_spy = 0.5
    current_w_gld = 0.5
    prev_w_spy = 0.5
    prev_w_gld = 0.5

    for i, (date, row) in enumerate(oos.iterrows()):
        if i - last_rebal_idx >= REBAL_FREQ:
            last_rebal_idx = i
            vix_val = row["VIX"]
            vix_weight = compute_vix_weight(vix_val)
            abs_mom_pctrank = row.get("GLD_ABS_MOM_6_1_pctrank", 50)

            if pd.notna(abs_mom_pctrank) and abs_mom_pctrank > MOM_PERCENTILE:
                current_w_spy = 0.5 * vix_weight
                current_w_gld = 0.5 * vix_weight * (1 - GLD_REDUCTION)
            else:
                current_w_spy = 0.5 * vix_weight
                current_w_gld = 0.5 * vix_weight

            current_w_spy = min(current_w_spy, MAX_LEVERAGE * 0.5)
            current_w_gld = min(current_w_gld, MAX_LEVERAGE * 0.5)

        spy_ret = row["SPY_ret"]
        gld_ret = row["GLD_ret"]
        port_ret = current_w_spy * spy_ret + current_w_gld * gld_ret

        if i == last_rebal_idx:
            turnover = abs(current_w_spy - prev_w_spy) + abs(current_w_gld - prev_w_gld)
            port_ret -= turnover * TX_COST

        cash_w = max(0, 1.0 - current_w_spy - current_w_gld)
        port_ret += cash_w * RF_DAILY

        port_returns.append(port_ret)
        prev_w_spy = current_w_spy
        prev_w_gld = current_w_gld

    m = compute_metrics(np.array(port_returns))
    if m:
        mom6_sharpes.append(m["sharpe"])
        print(f"  P{period_idx+1}: Sharpe={m['sharpe']:+.3f}  MDD={m['mdd']:+.1%}")

if mom6_sharpes:
    print(f"  Mean Sharpe (MOM_6_1): {np.mean(mom6_sharpes):+.3f}  "
          f"(base: {np.mean(base_sharpes):+.3f})")

# =====================================================================
# 7. SAVE RESULTS
# =====================================================================
print("\n" + "=" * 78)
print("SAVING RESULTS")
print("=" * 78)

results_dict = {
    "experiment": "K204",
    "title": "GLD Momentum-Based VT",
    "question": "Can K203 GLD momentum finding improve 50/50 SPY/GLD VT?",
    "date": datetime.now().isoformat(),
    "methodology": {
        "portfolio": "50/50 SPY/GLD",
        "base_vt": "12/VIX monthly rebalancing",
        "target_vol": TARGET_VOL_ANNUAL,
        "tx_cost": TX_COST,
        "rebal_freq": "monthly (21 trading days)",
        "mom_lookback_12": MOM_LOOKBACK_12,
        "mom_lookback_6": MOM_LOOKBACK_6,
        "mom_skip": MOM_SKIP,
        "mom_percentile": MOM_PERCENTILE,
        "gld_reduction": GLD_REDUCTION,
        "low_vol_mult": LOW_VOL_TARGET_MULT,
    },
    "oos_periods": OOS_PERIODS,
    "cross_oos_results": {},
    "diagnostics": {},
}

# Store per-strategy per-period results
for strat in strategies:
    strat_data = {
        "sharpes": all_sharpes[strat],
        "mdds": all_mdds[strat],
        "mean_sharpe": float(np.mean(all_sharpes[strat])) if all_sharpes[strat] else None,
        "mean_mdd": float(np.mean(all_mdds[strat])) if all_mdds[strat] else None,
        "periods": [r for r in all_results[strat]],
    }
    results_dict["cross_oos_results"][strat] = strat_data

# Paired tests
paired_tests = {}
for strat in ["mom_overlay", "mom_regime", "combined"]:
    if len(all_sharpes[strat]) == len(base_sharpes) and len(base_sharpes) >= 3:
        diffs = [s - b for s, b in zip(all_sharpes[strat], base_sharpes)]
        mean_diff = float(np.mean(diffs))
        std_diff = float(np.std(diffs, ddof=1))
        se_diff = std_diff / np.sqrt(len(diffs))
        t_p = mean_diff / se_diff if se_diff > 0 else 0
        p_p = float(2 * (1 - stats.t.cdf(abs(t_p), df=len(diffs) - 1)))
        paired_tests[strat] = {
            "delta_sharpe": mean_diff,
            "t_stat": float(t_p),
            "p_value": p_p,
            "significant": p_p < 0.05,
        }
results_dict["paired_tests_sharpe"] = paired_tests

# MDD paired tests
mdd_tests = {}
for strat in ["mom_overlay", "mom_regime", "combined"]:
    if len(all_mdds[strat]) == len(all_mdds["base"]) and len(all_mdds["base"]) >= 3:
        diffs = [s - b for s, b in zip(all_mdds[strat], all_mdds["base"])]
        mean_diff = float(np.mean(diffs))
        std_diff = float(np.std(diffs, ddof=1))
        se_diff = std_diff / np.sqrt(len(diffs))
        t_p = mean_diff / se_diff if se_diff > 0 else 0
        p_p = float(1 - stats.t.cdf(t_p, df=len(diffs) - 1))
        mdd_tests[strat] = {
            "delta_mdd": mean_diff,
            "t_stat": float(t_p),
            "p_value": p_p,
            "significant": p_p < 0.05,
        }
results_dict["paired_tests_mdd"] = mdd_tests

# Diagnostics
results_dict["diagnostics"]["mom_rv_correlation"] = {
    "abs_mom_12_1_vs_future_rv21": {"r": float(r), "p": float(p)},
    "abs_mom_12_1_vs_future_ret21": {"r": float(r_mom_ret), "p": float(p_mom_ret)},
    "mom_12_1_signed_vs_future_ret21": {"r": float(r_signed), "p": float(p_signed)},
}

# Conclusion
all_strat_diffs = []
for strat in ["mom_overlay", "mom_regime", "combined"]:
    if strat in paired_tests:
        all_strat_diffs.append(paired_tests[strat]["delta_sharpe"])

any_significant = any(
    paired_tests.get(s, {}).get("significant", False)
    for s in ["mom_overlay", "mom_regime", "combined"]
)
any_harvey = False
for strat in ["mom_overlay", "mom_regime", "combined"]:
    sharpes = all_sharpes[strat]
    if len(sharpes) >= 2:
        mean_s = np.mean(sharpes)
        std_s = np.std(sharpes, ddof=1)
        t_stat = mean_s / (std_s / np.sqrt(len(sharpes))) if std_s > 0 else 0
        if abs(t_stat) > 3.0:
            any_harvey = True

results_dict["conclusion"] = {
    "any_significant_improvement": any_significant,
    "passes_harvey": any_harvey,
    "verdict": (
        "POSITIVE: GLD momentum overlay significantly improves VT"
        if any_significant and any_harvey
        else "NULL: GLD momentum does NOT significantly improve 12/VIX VT"
    ),
    "interpretation": (
        "Despite K203's finding that GLD |MOM_12_1| correlates with future vol (r=0.39), "
        "translating this predictive relationship into a superior VT strategy fails. "
        "This is consistent with VIX sufficiency: VIX already captures the vol information "
        "that momentum provides, making momentum-based overlays redundant for monthly VT."
    ) if not (any_significant and any_harvey) else (
        "GLD momentum overlay provides statistically significant improvement over base 12/VIX."
    ),
}

# Save
RESULTS_PATH = Path(__file__).resolve().parent / "k204_gld_momentum_vt_results.json"
with open(RESULTS_PATH, "w") as f:
    json.dump(results_dict, f, indent=2, default=str)
print(f"\n  Results saved to: {RESULTS_PATH}")

# =====================================================================
# FINAL SUMMARY
# =====================================================================
print("\n" + "=" * 78)
print("K204 FINAL SUMMARY")
print("=" * 78)

print(f"\n  Research Question: Can GLD momentum improve 50/50 SPY/GLD VT?")
print(f"  K203 Finding: |MOM_12_1| partial r=0.39 with future GLD vol (t=6.5)")
print(f"  OOS Validation: {len(OOS_PERIODS)} periods (2015-2024, 2yr each)")
print(f"  TX Cost: {TX_COST*100:.1f}% per trade")
print(f"\n  Verdict: {results_dict['conclusion']['verdict']}")
print(f"  Harvey t>3.0: {'PASS' if any_harvey else 'FAIL'}")
print(f"  Paired t-test: {'SIGNIFICANT' if any_significant else 'NOT SIGNIFICANT'}")

if all_strat_diffs:
    best_diff = max(all_strat_diffs)
    print(f"  Best ΔSharpe vs base: {best_diff:+.4f}")

print(f"\n  Interpretation: {results_dict['conclusion']['interpretation']}")
print("\n" + "=" * 78)
