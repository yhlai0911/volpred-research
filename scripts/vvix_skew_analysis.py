"""
VVIX / SKEW / VIX Term Structure 分析
======================================
研究 VVIX、SKEW、VIX3M 對 VT 策略的增量預測能力。

基準策略：50/50 SPY/GLD with 12/VIX（Sharpe 0.83）
測試：VVIX tail-guard overlay、SKEW overlay、VIX term structure overlay

所有回測使用 LAGGED weights（signal_t → weight_{t+1}）
"""

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ────────────────────────────────────────────
# 1. 數據下載
# ────────────────────────────────────────────
print("=" * 70)
print("VVIX / SKEW / VIX Term Structure 分析")
print("=" * 70)

print("\n[1/6] 下載數據...")

tickers = {
    "SPY": "SPY",
    "GLD": "GLD",
    "VIX": "^VIX",
    "VVIX": "^VVIX",
    "SKEW": "^SKEW",
    "VIX3M": "^VIX3M",
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2006-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df["Close"].squeeze()
    print(f"  {name}: {len(data[name])} rows, {data[name].index[0].date()} ~ {data[name].index[-1].date()}")

# Build aligned DataFrame
df_all = pd.DataFrame(data)
df_all = df_all.dropna(subset=["SPY", "VIX"])  # Must have SPY and VIX

# Forward-fill VVIX/SKEW/VIX3M (they may have missing days)
for col in ["VVIX", "SKEW", "VIX3M", "GLD"]:
    if col in df_all.columns:
        df_all[col] = df_all[col].ffill()

# Calculate returns
df_all["SPY_ret"] = df_all["SPY"].pct_change()
df_all["GLD_ret"] = df_all["GLD"].pct_change()

# VIX term structure ratio
df_all["VIX_ratio"] = df_all["VIX"] / df_all["VIX3M"]

# Drop initial NaN
df_all = df_all.dropna(subset=["SPY_ret"])

print(f"\n  對齊後資料: {len(df_all)} rows")
print(f"  VVIX 非空: {df_all['VVIX'].notna().sum()} rows")
print(f"  SKEW 非空: {df_all['SKEW'].notna().sum()} rows")
print(f"  VIX3M 非空: {df_all['VIX3M'].notna().sum()} rows")

# ────────────────────────────────────────────
# 2. 統計特性分析
# ────────────────────────────────────────────
print("\n" + "=" * 70)
print("[2/6] 統計特性分析")
print("=" * 70)

# Subset where VVIX is available
df_vvix = df_all.dropna(subset=["VVIX"]).copy()
print(f"\nVVIX 可用期間: {df_vvix.index[0].date()} ~ {df_vvix.index[-1].date()} ({len(df_vvix)} days)")

# Basic statistics
stats_summary = {}
for col in ["VIX", "VVIX", "SKEW", "VIX3M", "VIX_ratio"]:
    s = df_vvix[col].dropna()
    stats_summary[col] = {
        "mean": round(float(s.mean()), 2),
        "median": round(float(s.median()), 2),
        "std": round(float(s.std()), 2),
        "min": round(float(s.min()), 2),
        "max": round(float(s.max()), 2),
        "skewness": round(float(s.skew()), 3),
        "kurtosis": round(float(s.kurtosis()), 3),
        "pct_25": round(float(s.quantile(0.25)), 2),
        "pct_75": round(float(s.quantile(0.75)), 2),
        "pct_90": round(float(s.quantile(0.90)), 2),
        "pct_95": round(float(s.quantile(0.95)), 2),
    }

print("\n--- 描述統計 ---")
print(f"{'指標':<12} {'VIX':>10} {'VVIX':>10} {'SKEW':>10} {'VIX3M':>10} {'VIX/VIX3M':>10}")
print("-" * 62)
for stat in ["mean", "median", "std", "min", "max", "pct_90", "pct_95", "skewness", "kurtosis"]:
    row = f"{stat:<12}"
    for col in ["VIX", "VVIX", "SKEW", "VIX3M", "VIX_ratio"]:
        row += f" {stats_summary[col][stat]:>9}"
    print(row)

# Correlation matrix
corr_cols = ["VIX", "VVIX", "SKEW", "VIX_ratio", "SPY_ret"]
corr_matrix = df_vvix[corr_cols].corr()
print("\n--- 相關係數矩陣 ---")
print(corr_matrix.round(3).to_string())

# ────────────────────────────────────────────
# 3. Lead-lag 分析：VVIX 是否領先 VIX？
# ────────────────────────────────────────────
print("\n" + "=" * 70)
print("[3/6] Lead-Lag 分析")
print("=" * 70)

# Cross-correlation: does VVIX change predict future VIX change?
df_vvix["VVIX_change"] = df_vvix["VVIX"].pct_change()
df_vvix["VIX_change"] = df_vvix["VIX"].pct_change()
df_vvix["VIX_change_1d"] = df_vvix["VIX_change"].shift(-1)  # Tomorrow's VIX change
df_vvix["VIX_change_5d"] = df_vvix["VIX"].pct_change(5).shift(-5)  # 5-day forward VIX change

lead_lag_results = {}
for lag_name, target in [("VIX_change_1d", "1日後 VIX 變化"),
                          ("VIX_change_5d", "5日後 VIX 變化")]:
    valid = df_vvix[["VVIX_change", lag_name]].dropna()
    r, p = stats.pearsonr(valid["VVIX_change"], valid[lag_name])
    lead_lag_results[target] = {"correlation": round(r, 4), "p_value": round(p, 4), "n": len(valid)}
    print(f"  VVIX 變化 → {target}: r={r:.4f}, p={p:.4f}, n={len(valid)}")

# VVIX level → future SPY returns
for horizon in [1, 5, 22]:
    df_vvix[f"SPY_fwd_{horizon}d"] = df_vvix["SPY_ret"].rolling(horizon).sum().shift(-horizon)
    valid = df_vvix[["VVIX", f"SPY_fwd_{horizon}d"]].dropna()
    r, p = stats.pearsonr(valid["VVIX"], valid[f"SPY_fwd_{horizon}d"])
    lead_lag_results[f"VVIX → SPY {horizon}d fwd return"] = {"correlation": round(r, 4), "p_value": round(p, 4), "n": len(valid)}
    print(f"  VVIX 水平 → SPY {horizon}日前瞻報酬: r={r:.4f}, p={p:.4f}")

# VVIX level → future VIX spike (>3 std move)
df_vvix["VIX_spike_5d"] = (df_vvix["VIX_change"].rolling(5).max().shift(-5) >
                            df_vvix["VIX_change"].rolling(252).std() * 2).astype(int)
valid = df_vvix[["VVIX", "VIX_spike_5d"]].dropna()
r, p = stats.pointbiserialr(valid["VIX_spike_5d"], valid["VVIX"])
print(f"  VVIX 水平 → 5日內 VIX spike (>2σ): r={r:.4f}, p={p:.4f}")
lead_lag_results["VVIX → 5d VIX spike"] = {"correlation": round(r, 4), "p_value": round(p, 4), "n": len(valid)}

# ────────────────────────────────────────────
# 4. VT 策略回測函數
# ────────────────────────────────────────────

def backtest_vt(df, weight_col, spy_ret_col="SPY_ret", gld_ret_col="GLD_ret",
                spy_pct=0.5, gld_pct=0.5, start_date=None, end_date=None,
                rebal="daily"):
    """
    回測 VT 策略。使用 LAGGED weights（weight_t → return_{t+1}）。

    Parameters:
        df: DataFrame with columns [weight_col, spy_ret_col, gld_ret_col]
        weight_col: column name for equity weight (0-1)
        spy_pct/gld_pct: allocation within equity portion
        rebal: "daily" or "monthly"
    Returns:
        dict with Sharpe, MDD, Calmar, etc.
    """
    sub = df.copy()
    if start_date:
        sub = sub[sub.index >= start_date]
    if end_date:
        sub = sub[sub.index <= end_date]

    sub = sub.dropna(subset=[weight_col, spy_ret_col])
    if gld_ret_col in sub.columns:
        sub = sub.dropna(subset=[gld_ret_col])

    # LAGGED weights: use yesterday's signal for today's position
    sub["w_lag"] = sub[weight_col].shift(1)
    sub = sub.dropna(subset=["w_lag"])

    if rebal == "monthly":
        # Use end-of-month weight, hold for entire next month
        monthly_w = sub["w_lag"].resample("ME").last()
        sub["w_monthly"] = np.nan
        for dt, w in monthly_w.items():
            mask = (sub.index > dt) & (sub.index <= dt + pd.DateOffset(months=1))
            sub.loc[mask, "w_monthly"] = w
        # Fill first month with first available weight
        sub["w_monthly"] = sub["w_monthly"].ffill().bfill()
        sub["w_lag"] = sub["w_monthly"]

    # Portfolio return
    if gld_ret_col in sub.columns and gld_pct > 0:
        sub["port_ret"] = sub["w_lag"] * (spy_pct * sub[spy_ret_col] + gld_pct * sub[gld_ret_col]) + \
                          (1 - sub["w_lag"]) * 0.0  # Cash = 0 return for simplicity
    else:
        sub["port_ret"] = sub["w_lag"] * sub[spy_ret_col]

    # Buy-and-hold for comparison (same spy/gld split)
    if gld_ret_col in sub.columns and gld_pct > 0:
        sub["bh_ret"] = spy_pct * sub[spy_ret_col] + gld_pct * sub[gld_ret_col]
    else:
        sub["bh_ret"] = sub[spy_ret_col]

    # Metrics
    n_years = len(sub) / 252
    ann_ret = float((1 + sub["port_ret"]).prod() ** (1 / n_years) - 1) if n_years > 0 else 0
    ann_vol = float(sub["port_ret"].std() * np.sqrt(252))
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + sub["port_ret"]).cumprod()
    dd = cum / cum.cummax() - 1
    mdd = float(dd.min())

    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Downside deviation → Sortino
    downside = sub["port_ret"][sub["port_ret"] < 0]
    sortino = ann_ret / (float(downside.std()) * np.sqrt(252)) if len(downside) > 0 else 0

    # Turnover (avg daily weight change)
    turnover = float(sub["w_lag"].diff().abs().mean()) * 252

    # B&H metrics
    bh_ann_ret = float((1 + sub["bh_ret"]).prod() ** (1 / n_years) - 1) if n_years > 0 else 0
    bh_ann_vol = float(sub["bh_ret"].std() * np.sqrt(252))
    bh_sharpe = bh_ann_ret / bh_ann_vol if bh_ann_vol > 0 else 0
    bh_cum = (1 + sub["bh_ret"]).cumprod()
    bh_dd = bh_cum / bh_cum.cummax() - 1
    bh_mdd = float(bh_dd.min())

    # Harvey t-stat for Sharpe difference
    n = len(sub)
    se_sharpe = np.sqrt((1 + 0.5 * sharpe**2) / n) * np.sqrt(252)
    se_bh = np.sqrt((1 + 0.5 * bh_sharpe**2) / n) * np.sqrt(252)
    # Approximation: SE of difference
    se_diff = np.sqrt(se_sharpe**2 + se_bh**2)  # Conservative (ignores correlation)
    t_diff = (sharpe - bh_sharpe) / se_diff if se_diff > 0 else 0

    return {
        "ann_return": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "turnover": round(turnover, 2),
        "n_days": len(sub),
        "n_years": round(n_years, 1),
        "period": f"{sub.index[0].date()} ~ {sub.index[-1].date()}",
        "bh_sharpe": round(bh_sharpe, 3),
        "bh_mdd": round(bh_mdd, 4),
        "sharpe_diff_t": round(t_diff, 3),
        "avg_weight": round(float(sub["w_lag"].mean()), 3),
    }


# ────────────────────────────────────────────
# 5. 策略回測
# ────────────────────────────────────────────
print("\n" + "=" * 70)
print("[4/6] VT 策略回測")
print("=" * 70)

# Prepare signals (all lagged inherently in backtest_vt)
df_bt = df_all.copy()

# A. Base: 12/VIX weight (capped at 1.0)
df_bt["w_12vix"] = (12.0 / df_bt["VIX"]).clip(0, 1)

# B. VVIX overlay strategies
for vvix_thresh in [100, 110, 120, 130]:
    # When VVIX > threshold, scale down position by factor
    for scale in [0.5, 0.7]:
        col = f"w_vvix_{vvix_thresh}_s{int(scale*100)}"
        df_bt[col] = df_bt["w_12vix"].copy()
        mask = df_bt["VVIX"] > vvix_thresh
        df_bt.loc[mask, col] = df_bt.loc[mask, "w_12vix"] * scale

# C. VVIX percentile overlay
df_bt["VVIX_pct"] = df_bt["VVIX"].rolling(252).rank(pct=True)
for pct_thresh in [0.80, 0.90]:
    col = f"w_vvix_pct{int(pct_thresh*100)}"
    df_bt[col] = df_bt["w_12vix"].copy()
    mask = df_bt["VVIX_pct"] > pct_thresh
    df_bt.loc[mask, col] = df_bt.loc[mask, "w_12vix"] * 0.5

# D. SKEW overlay
for skew_thresh in [130, 140, 150]:
    col = f"w_skew_{skew_thresh}"
    df_bt[col] = df_bt["w_12vix"].copy()
    mask = df_bt["SKEW"] > skew_thresh
    df_bt.loc[mask, col] = df_bt.loc[mask, "w_12vix"] * 0.7

# E. VIX term structure overlay
# Backwardation (VIX/VIX3M > 1) = stress → already in VIX level
# Contango (VIX/VIX3M < 0.85) = deep complacency → reduce exposure
for ratio_thresh in [0.85, 0.90]:
    col = f"w_vixratio_{int(ratio_thresh*100)}"
    df_bt[col] = df_bt["w_12vix"].copy()
    # In deep contango (complacent market), cap weight
    mask = df_bt["VIX_ratio"] < ratio_thresh
    df_bt.loc[mask, col] = df_bt.loc[mask, "w_12vix"] * 0.7

# F. Combined: VVIX + VIX term structure
df_bt["w_combined"] = df_bt["w_12vix"].copy()
mask_vvix = df_bt["VVIX"] > 120
mask_contango = df_bt["VIX_ratio"] < 0.85
# VVIX high → scale down
df_bt.loc[mask_vvix, "w_combined"] = df_bt.loc[mask_vvix, "w_12vix"] * 0.7
# Deep contango + VVIX high = very dangerous → scale more
df_bt.loc[mask_vvix & mask_contango, "w_combined"] = df_bt.loc[mask_vvix & mask_contango, "w_12vix"] * 0.5

# G. VVIX-adjusted VIX: use VVIX to adjust effective VIX level
# High VVIX means VIX might be understating risk → inflate VIX reading
df_bt["VIX_adj"] = df_bt["VIX"] * (1 + (df_bt["VVIX"] - 80) / 200).clip(0.8, 1.5)
df_bt["w_vix_adj"] = (12.0 / df_bt["VIX_adj"]).clip(0, 1)

# ────────────────────────────────────────────
# Run backtests
# ────────────────────────────────────────────
# Periods
periods = {
    "Full (VVIX available)": (df_bt["VVIX"].first_valid_index(), None),
    "Pre-COVID (2014-2019)": ("2014-01-01", "2019-12-31"),
    "COVID+ (2020-2022)": ("2020-01-01", "2022-12-31"),
    "OOS (2023-2026)": ("2023-01-01", None),
}

# Strategy columns
strategies = {
    "基準: 12/VIX": "w_12vix",
    "VVIX>100 ×0.5": "w_vvix_100_s50",
    "VVIX>100 ×0.7": "w_vvix_100_s70",
    "VVIX>110 ×0.5": "w_vvix_110_s50",
    "VVIX>110 ×0.7": "w_vvix_110_s70",
    "VVIX>120 ×0.5": "w_vvix_120_s50",
    "VVIX>120 ×0.7": "w_vvix_120_s70",
    "VVIX>130 ×0.5": "w_vvix_130_s50",
    "VVIX>130 ×0.7": "w_vvix_130_s70",
    "VVIX P90 ×0.5": "w_vvix_pct90",
    "VVIX P80 ×0.5": "w_vvix_pct80",
    "SKEW>130 ×0.7": "w_skew_130",
    "SKEW>140 ×0.7": "w_skew_140",
    "SKEW>150 ×0.7": "w_skew_150",
    "Contango<0.85 ×0.7": "w_vixratio_85",
    "Contango<0.90 ×0.7": "w_vixratio_90",
    "Combined VVIX+TS": "w_combined",
    "VVIX-adj VIX": "w_vix_adj",
}

all_results = {}

for period_name, (start, end) in periods.items():
    print(f"\n--- {period_name} ---")
    start_str = str(start) if start else None
    period_results = {}

    for strat_name, col in strategies.items():
        result = backtest_vt(df_bt, col, start_date=start_str, end_date=end)
        period_results[strat_name] = result

    all_results[period_name] = period_results

    # Print summary table
    print(f"{'策略':<22} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'Sortino':>8} {'AvgWt':>7} {'Δ Sharpe t':>10}")
    print("-" * 75)
    base_sharpe = period_results["基準: 12/VIX"]["sharpe"]
    for strat_name, r in period_results.items():
        delta = r["sharpe"] - base_sharpe
        delta_str = f"{delta:+.3f}" if strat_name != "基準: 12/VIX" else "---"
        print(f"{strat_name:<22} {r['sharpe']:>7.3f} {r['mdd']:>8.4f} {r['calmar']:>7.3f} "
              f"{r['sortino']:>8.3f} {r['avg_weight']:>7.3f} {delta_str:>10}")

# ────────────────────────────────────────────
# 6. 50/50 SPY/GLD 策略（推薦策略的 overlay）
# ────────────────────────────────────────────
print("\n" + "=" * 70)
print("[5/6] 50/50 SPY/GLD 策略 + Overlay")
print("=" * 70)

spygld_results = {}

for period_name, (start, end) in periods.items():
    print(f"\n--- {period_name} ---")
    start_str = str(start) if start else None
    period_results = {}

    key_strategies = {
        "基準: 12/VIX 50/50": "w_12vix",
        "VVIX>120 ×0.7": "w_vvix_120_s70",
        "VVIX>130 ×0.7": "w_vvix_130_s70",
        "VVIX P90 ×0.5": "w_vvix_pct90",
        "SKEW>140 ×0.7": "w_skew_140",
        "Contango<0.85 ×0.7": "w_vixratio_85",
        "Combined VVIX+TS": "w_combined",
        "VVIX-adj VIX": "w_vix_adj",
    }

    for strat_name, col in key_strategies.items():
        result = backtest_vt(df_bt, col, spy_pct=0.5, gld_pct=0.5,
                            start_date=start_str, end_date=end)
        period_results[strat_name] = result

    spygld_results[period_name] = period_results

    print(f"{'策略':<22} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'Sortino':>8} {'AvgWt':>7}")
    print("-" * 65)
    for strat_name, r in period_results.items():
        print(f"{strat_name:<22} {r['sharpe']:>7.3f} {r['mdd']:>8.4f} {r['calmar']:>7.3f} "
              f"{r['sortino']:>8.3f} {r['avg_weight']:>7.3f}")

# ────────────────────────────────────────────
# 7. 月度再平衡（推薦策略用月度）
# ────────────────────────────────────────────
print("\n" + "=" * 70)
print("[5b/6] 月度再平衡比較（50/50 SPY/GLD）")
print("=" * 70)

monthly_results = {}
for period_name, (start, end) in periods.items():
    start_str = str(start) if start else None
    period_results = {}

    for strat_name, col in [("基準: 12/VIX", "w_12vix"),
                             ("VVIX>120 ×0.7", "w_vvix_120_s70"),
                             ("Combined VVIX+TS", "w_combined"),
                             ("VVIX-adj VIX", "w_vix_adj")]:
        result = backtest_vt(df_bt, col, spy_pct=0.5, gld_pct=0.5,
                            start_date=start_str, end_date=end, rebal="monthly")
        period_results[strat_name] = result

    monthly_results[period_name] = period_results

    print(f"\n--- {period_name} (月度) ---")
    print(f"{'策略':<22} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'Sortino':>8} {'AvgWt':>7}")
    print("-" * 65)
    for strat_name, r in period_results.items():
        print(f"{strat_name:<22} {r['sharpe']:>7.3f} {r['mdd']:>8.4f} {r['calmar']:>7.3f} "
              f"{r['sortino']:>8.3f} {r['avg_weight']:>7.3f}")

# ────────────────────────────────────────────
# 8. 條件分析：VVIX 在極端事件時的表現
# ────────────────────────────────────────────
print("\n" + "=" * 70)
print("[6/6] 條件分析 + 結論")
print("=" * 70)

# Analyze VVIX behavior around major VIX spikes
df_vvix2 = df_bt.dropna(subset=["VVIX"]).copy()
df_vvix2["VIX_spike"] = df_vvix2["VIX"].pct_change(5) > 0.30  # 30% spike in 5 days

# What was VVIX doing before VIX spikes?
spike_dates = df_vvix2[df_vvix2["VIX_spike"]].index
if len(spike_dates) > 0:
    pre_spike_vvix = []
    for dt in spike_dates:
        idx = df_vvix2.index.get_loc(dt)
        if idx >= 5:
            pre_vvix = df_vvix2["VVIX"].iloc[idx-5:idx].mean()
            current_vvix = df_vvix2["VVIX"].iloc[idx]
            pre_spike_vvix.append({
                "date": str(dt.date()),
                "pre_5d_vvix": round(float(pre_vvix), 1),
                "at_spike_vvix": round(float(current_vvix), 1),
                "vix_at_spike": round(float(df_vvix2["VIX"].iloc[idx]), 1),
            })

    print(f"\nVIX 急漲事件 (5日漲>30%): {len(spike_dates)} 次")
    pre_vvix_vals = [x["pre_5d_vvix"] for x in pre_spike_vvix[:50]]
    print(f"  急漲前5日平均 VVIX: {np.mean(pre_vvix_vals):.1f}")
    print(f"  急漲前5日 VVIX 中位數: {np.median(pre_vvix_vals):.1f}")
    print(f"  正常時期 VVIX 平均: {df_vvix2['VVIX'].mean():.1f}")

    # Is pre-spike VVIX significantly different from normal?
    normal_vvix = df_vvix2[~df_vvix2["VIX_spike"]]["VVIX"].dropna()
    t_stat, p_val = stats.ttest_ind(pre_vvix_vals, normal_vvix.sample(min(1000, len(normal_vvix)), random_state=42))
    print(f"  t 檢定 (spike前 vs 正常): t={t_stat:.3f}, p={p_val:.4f}")

# ────────────────────────────────────────────
# CONCLUSION
# ────────────────────────────────────────────
print("\n" + "=" * 70)
print("結論")
print("=" * 70)

# Compare OOS results
oos_base = all_results.get("OOS (2023-2026)", {}).get("基準: 12/VIX", {})
oos_spygld_base = spygld_results.get("OOS (2023-2026)", {}).get("基準: 12/VIX 50/50", {})

print(f"""
=== VVIX / SKEW / VIX Term Structure 分析結論 ===

1. 統計特性:
   - VVIX 與 VIX 相關性高（通常 r > 0.5），但包含額外信息
   - VVIX 在 VIX spike 前是否有預警取決於 lead-lag 分析結果
   - SKEW 與 VIX 的相關性較低，捕獲不同風險維度

2. Lead-Lag 結果:
""")
for key, val in lead_lag_results.items():
    sig = "✓ 顯著" if val["p_value"] < 0.05 else "✗ 不顯著"
    print(f"   - {key}: r={val['correlation']}, p={val['p_value']} {sig}")

# Find best overlay in OOS
if "OOS (2023-2026)" in all_results:
    oos = all_results["OOS (2023-2026)"]
    base_s = oos["基準: 12/VIX"]["sharpe"]
    print(f"\n3. OOS (2023-2026) SPY-only 策略:")
    print(f"   基準 12/VIX Sharpe: {base_s}")
    for name, r in sorted(oos.items(), key=lambda x: x[1]["sharpe"], reverse=True):
        if name == "基準: 12/VIX":
            continue
        delta = r["sharpe"] - base_s
        sig = "有增量" if delta > 0.02 else "無增量"
        print(f"   {name}: Sharpe={r['sharpe']}, Δ={delta:+.3f} ({sig})")

if "OOS (2023-2026)" in spygld_results:
    oos50 = spygld_results["OOS (2023-2026)"]
    base50_s = oos50["基準: 12/VIX 50/50"]["sharpe"]
    print(f"\n4. OOS (2023-2026) 50/50 SPY/GLD 策略:")
    print(f"   基準 12/VIX 50/50 Sharpe: {base50_s}")
    for name, r in sorted(oos50.items(), key=lambda x: x[1]["sharpe"], reverse=True):
        if name == "基準: 12/VIX 50/50":
            continue
        delta = r["sharpe"] - base50_s
        print(f"   {name}: Sharpe={r['sharpe']}, Δ={delta:+.3f}")

# Check if any overlay beats base consistently across ALL periods
print("\n5. 跨期間一致性檢查 (Overlay > Base 的期間數 / 總期間數):")
for strat_name in strategies:
    if strat_name == "基準: 12/VIX":
        continue
    wins = 0
    total = 0
    for period_name in all_results:
        if strat_name in all_results[period_name] and "基準: 12/VIX" in all_results[period_name]:
            total += 1
            if all_results[period_name][strat_name]["sharpe"] > all_results[period_name]["基準: 12/VIX"]["sharpe"]:
                wins += 1
    if total > 0:
        print(f"   {strat_name}: {wins}/{total} ({wins/total*100:.0f}%)")

print("""
6. 核心結論:
   - 待上方數據確認：VVIX/SKEW/VIX Term Structure 是否能突破 12/VIX 的 sufficient statistic 地位
   - 若所有 overlay 在 OOS 都無法持續贏過基準，則確認 VIX sufficient statistic 假說更加穩健
   - 這將是 J3/J4/J8 系列（VIX 吸收所有替代信號）的又一確認
""")

# ────────────────────────────────────────────
# 9. 保存結果
# ────────────────────────────────────────────
output = {
    "experiment_id": "vvix_skew_analysis",
    "timestamp": datetime.now().isoformat(),
    "description": "VVIX / SKEW / VIX Term Structure 對 VT 策略的增量預測能力分析",
    "attribution": "[提出: Gemini (VVIX tail-guard overlay), 執行: Claude]",
    "data_summary": {
        "vvix_available_from": str(df_bt["VVIX"].first_valid_index().date()) if df_bt["VVIX"].first_valid_index() else None,
        "skew_available_from": str(df_bt["SKEW"].first_valid_index().date()) if df_bt["SKEW"].first_valid_index() else None,
        "vix3m_available_from": str(df_bt["VIX3M"].first_valid_index().date()) if df_bt["VIX3M"].first_valid_index() else None,
        "total_aligned_days": len(df_all),
    },
    "statistics": stats_summary,
    "correlations": {k: {k2: round(v2, 4) for k2, v2 in v.items()}
                     for k, v in corr_matrix.to_dict().items()},
    "lead_lag": lead_lag_results,
    "spy_only_results": all_results,
    "spygld_5050_results": spygld_results,
    "monthly_rebal_results": monthly_results,
    "conclusion": {
        "vvix_adds_value": None,  # Will be determined by results
        "skew_adds_value": None,
        "term_structure_adds_value": None,
        "vix_sufficient_statistic_confirmed": None,
    }
}

# Determine conclusions based on OOS results
if "OOS (2023-2026)" in all_results:
    oos = all_results["OOS (2023-2026)"]
    base_s = oos["基準: 12/VIX"]["sharpe"]

    # Check VVIX overlays
    vvix_overlays = [k for k in oos if "VVIX" in k or "vvix" in k.lower()]
    vvix_better = any(oos[k]["sharpe"] > base_s + 0.02 for k in vvix_overlays if k in oos)
    output["conclusion"]["vvix_adds_value"] = vvix_better

    # Check SKEW overlays
    skew_overlays = [k for k in oos if "SKEW" in k]
    skew_better = any(oos[k]["sharpe"] > base_s + 0.02 for k in skew_overlays if k in oos)
    output["conclusion"]["skew_adds_value"] = skew_better

    # Check term structure overlays
    ts_overlays = [k for k in oos if "Contango" in k or "Combined" in k]
    ts_better = any(oos[k]["sharpe"] > base_s + 0.02 for k in ts_overlays if k in oos)
    output["conclusion"]["term_structure_adds_value"] = ts_better

    # VIX sufficient statistic confirmed if nothing adds value
    output["conclusion"]["vix_sufficient_statistic_confirmed"] = not (vvix_better or skew_better or ts_better)

out_path = Path("/Users/yhlai0911/Dropbox/自我研究波動預測模型/storage/experiments/vvix_skew_analysis.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2, default=str)

print(f"\n結果已保存至: {out_path}")
print("Done.")
