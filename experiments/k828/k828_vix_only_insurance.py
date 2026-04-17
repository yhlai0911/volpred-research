#!/usr/bin/env python3
"""
K828: VIX-Only Insurance Premium Conditioning
==============================================================
[提出: Claude (derived from K811v2), 執行: Claude]

Research Question:
  K811v2 found VIX predicts MDD better than VVIX (r=-0.327 vs -0.148).
  If VIX itself is a stronger signal, can we build a simpler VIX-percentile-
  conditional VT strategy that outperforms the VVIX-based version?

Hypothesis:
  - VIX percentile directly indicates insurance value
  - High VIX percentile (>80%) = high fear = insurance most valuable → full VT
  - Low VIX percentile (<20%) = calm = insurance over-priced → minimal VT
  - Middle = linear interpolation
  - Simpler signal (VIX only) should be more robust than VVIX

Strategies:
  S0: BH SPY (baseline)
  S1: Always 12/VIX (always insured)
  S2: VIX-Percentile Conditional — piecewise regime
  S3: VIX-Smooth — scaling factor based on percentile
  S4: 50/50 SPY/GLD (comparison benchmark)

Constraints:
  - signal.shift(1) — all signals lagged by 1 day, no lookahead
  - TX cost 5 bps per unit weight change
  - Expanding window for VIX percentile (avoid lookahead)
  - Period: 2006-01-01 ~ 2024-12-31 (no VVIX needed, longer history available)

Error Log Rules:
  - DM test: use strategy_dm_test from volpred.stats.model_evaluation
  - signal.shift(1): all VIX percentile signals use t-1 value
  - Sharpe > 2x baseline = likely bug, stop and check
  - Expanding percentile (not rolling fixed window) to avoid lookahead

Evaluation:
  - Sharpe, CAGR, MDD, Calmar, CRRA utility gamma=5
  - DM test vs S0 and S1 (Harvey t>3.0)
  - Insurance cost decomposition by VIX regime
  - Cross-OOS: 5 non-overlapping 2-year periods
  - Comparison with K811v2 VVIX conditioning results

Data: SPY, GLD, ^VIX from yfinance (2006-2024)

References:
  - K811: VoV-Conditional VT — VVIX-based conditioning
  - K811v2: VIX > VVIX for MDD prediction (r=-0.327 vs -0.148)
  - K41: VT = constant ~4%/yr insurance at all horizons
  - K229: VT Insurance Pricing — 3.05%/yr expected cost
  - K687: No VT strategy beats BH 50/50 on Sharpe after correct lag
  - K688: VT wins under CRRA utility gamma >= 5
  - Harvey, Liu, Zhu (2016) t>3.0 threshold
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parent.parent
TX_COST_BPS = 5
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252
RESULTS = {}

# ============================================================
# PART A: Data Download & Descriptive Statistics
# ============================================================
print("=" * 80)
print("K828: VIX-Only Insurance Premium Conditioning")
print("[提出: Claude (K811v2 follow-up), 執行: Claude]")
print("=" * 80)
print("\nPART A: Data Download & Descriptive Statistics")
print("-" * 60)

import yfinance as yf

# Download data
tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2005-01-01", end="2025-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df["Close"].rename(name)
    print(f"  {name}: {len(df)} rows, {df.index[0].date()} ~ {df.index[-1].date()}")

# Merge and align
prices = pd.concat(raw.values(), axis=1).dropna()
prices.index = pd.to_datetime(prices.index)
# Filter to analysis period
prices = prices.loc["2006-01-01":"2024-12-31"]
print(f"\nMerged: {len(prices)} days, {prices.index[0].date()} ~ {prices.index[-1].date()}")

# Returns
ret_spy = prices["SPY"].pct_change()
ret_gld = prices["GLD"].pct_change()
vix = prices["VIX"]

# Drop first NaN row
valid_idx = ret_spy.dropna().index
ret_spy = ret_spy.loc[valid_idx]
ret_gld = ret_gld.loc[valid_idx]
vix = vix.loc[valid_idx]

n_days = len(ret_spy)
n_years = n_days / 252
print(f"Analysis: {n_days} trading days = {n_years:.2f} years")

# Descriptive stats
print(f"\nSPY return: mean={ret_spy.mean()*252*100:.2f}%/yr, vol={ret_spy.std()*np.sqrt(252)*100:.2f}%/yr")
print(f"VIX: mean={vix.mean():.2f}, std={vix.std():.2f}, min={vix.min():.2f}, max={vix.max():.2f}")

RESULTS["data"] = {
    "backtest_start": str(ret_spy.index[0].date()),
    "backtest_end": str(ret_spy.index[-1].date()),
    "n_days": n_days,
    "n_years": round(n_years, 2),
    "vix_mean": round(vix.mean(), 2),
    "vix_std": round(vix.std(), 2),
}


# ============================================================
# PART B: VIX Expanding Percentile Computation
# ============================================================
print("\n\nPART B: VIX Expanding Percentile")
print("-" * 60)

# Compute expanding percentile of VIX (avoid lookahead)
# For each day t, percentile = rank(VIX_t) / count of all VIX values up to day t
# We need VIX values from before 2006 for warm-up
vix_full = raw["VIX"].dropna()
vix_full.index = pd.to_datetime(vix_full.index)

# Compute expanding percentile
def expanding_percentile(series):
    """Compute expanding percentile rank for each observation.

    For day t, percentile = (number of values <= VIX_t in [0, t]) / (t + 1)
    This uses only past data, no lookahead.
    """
    result = pd.Series(index=series.index, dtype=float)
    values = []
    for i, (idx, val) in enumerate(series.items()):
        values.append(val)
        # Percentile rank: fraction of past values <= current value
        rank = sum(1 for v in values if v <= val) / len(values)
        result.iloc[i] = rank
    return result

# Compute on full VIX history for warm-up, then slice
print("Computing expanding percentile on full VIX history...")
vix_pctile_full = expanding_percentile(vix_full)
# Align to analysis period
vix_pctile = vix_pctile_full.loc[valid_idx].reindex(ret_spy.index)

# *** CRITICAL: shift(1) — use yesterday's percentile for today's weight ***
vix_pctile_lagged = vix_pctile.shift(1)

print(f"VIX percentile: mean={vix_pctile.mean():.3f}, std={vix_pctile.std():.3f}")
print(f"VIX percentile min={vix_pctile.min():.3f}, max={vix_pctile.max():.3f}")

# Descriptive: VIX percentile distribution
pctile_bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
pctile_counts = pd.cut(vix_pctile, bins=pctile_bins).value_counts().sort_index()
print("\nVIX percentile distribution:")
for interval, count in pctile_counts.items():
    print(f"  {interval}: {count} days ({count/len(vix_pctile)*100:.1f}%)")


# ============================================================
# PART C: Strategy Construction
# ============================================================
print("\n\nPART C: Strategy Construction")
print("-" * 60)

# --- S0: Buy & Hold SPY ---
w_s0 = pd.Series(1.0, index=ret_spy.index)

# --- S1: Always 12/VIX ---
# Weight = min(12/VIX, 1.0), lagged by 1 day
vix_lagged = vix.shift(1)
w_s1_raw = (12.0 / vix_lagged).clip(upper=1.0)
# *** CRITICAL: shift(1) already applied via vix_lagged ***
w_s1 = w_s1_raw

# --- S2: VIX-Percentile Conditional ---
# VIX percentile > 80%: full VT (12/VIX)
# VIX percentile < 20%: minimal VT (fixed 80% equity)
# 20%-80%: linear interpolation
def compute_s2_weight(vix_pctile_lag, vix_lag):
    """Piecewise VIX-percentile conditional weight."""
    full_vt_weight = (12.0 / vix_lag).clip(upper=1.0)
    minimal_weight = 0.80  # fixed 80% equity when calm

    weight = pd.Series(index=vix_pctile_lag.index, dtype=float)

    high_mask = vix_pctile_lag > 0.80
    low_mask = vix_pctile_lag < 0.20
    mid_mask = ~high_mask & ~low_mask

    # High fear: full VT weight
    weight[high_mask] = full_vt_weight[high_mask]
    # Low fear: minimal weight
    weight[low_mask] = minimal_weight
    # Middle: linear interpolation
    # At pctile=0.20, weight=minimal_weight; at pctile=0.80, weight=full_vt_weight
    # interp = minimal + (full - minimal) * (pctile - 0.20) / 0.60
    interp_factor = (vix_pctile_lag[mid_mask] - 0.20) / 0.60
    weight[mid_mask] = minimal_weight + (full_vt_weight[mid_mask] - minimal_weight) * interp_factor

    return weight.clip(lower=0.0, upper=1.0)

w_s2 = compute_s2_weight(vix_pctile_lagged, vix_lagged)

# --- S3: VIX-Smooth ---
# weight = (12/VIX) * scaling_factor
# scaling = 0.5 + 0.5 * VIX_percentile
# When VIX percentile is low (calm), scaling < 1 → less VT
# When VIX percentile is high (fear), scaling > 0.5 → more VT
def compute_s3_weight(vix_pctile_lag, vix_lag):
    """Smooth VIX-percentile scaling."""
    base_weight = (12.0 / vix_lag).clip(upper=1.0)
    scaling = 0.5 + 0.5 * vix_pctile_lag
    weight = base_weight * scaling
    return weight.clip(lower=0.0, upper=1.0)

w_s3 = compute_s3_weight(vix_pctile_lagged, vix_lagged)

# --- S4: 50/50 SPY/GLD ---
w_s4 = pd.Series(0.5, index=ret_spy.index)  # 50% SPY weight, rest in GLD

# Print weight stats
print("\nWeight statistics (equity allocation):")
for name, w in [("S1_Always_12VIX", w_s1), ("S2_VIX_Pctile_Cond", w_s2), ("S3_VIX_Smooth", w_s3)]:
    w_clean = w.dropna()
    print(f"  {name}: mean={w_clean.mean()*100:.1f}%, std={w_clean.std()*100:.1f}%, "
          f"min={w_clean.min()*100:.1f}%, max={w_clean.max()*100:.1f}%")


# ============================================================
# PART D: Returns with Transaction Costs
# ============================================================
print("\n\nPART D: Returns with TX Costs")
print("-" * 60)

def compute_strategy_returns(weights, ret_equity, ret_safe=None, tx_bps=TX_COST_BPS):
    """Compute strategy returns with TX cost deducted on weight changes.

    For strategies with only SPY: rest goes to cash (0 return).
    For S4 (50/50): rest goes to GLD.
    """
    w = weights.copy()
    # First day with valid weights: no TX cost
    valid_start = w.first_valid_index()
    if valid_start is None:
        return pd.Series(0.0, index=ret_equity.index)

    # Weight changes for TX cost
    w_change = w.diff().abs().fillna(0)
    tx_cost = w_change * tx_bps / 10000

    if ret_safe is not None:
        strat_ret = w * ret_equity + (1 - w) * ret_safe - tx_cost
    else:
        strat_ret = w * ret_equity - tx_cost

    return strat_ret

# S0: BH SPY (no TX, always 100%)
ret_s0 = ret_spy.copy()

# S1: Always 12/VIX
ret_s1 = compute_strategy_returns(w_s1, ret_spy, tx_bps=TX_COST_BPS)

# S2: VIX-Percentile Conditional
ret_s2 = compute_strategy_returns(w_s2, ret_spy, tx_bps=TX_COST_BPS)

# S3: VIX-Smooth
ret_s3 = compute_strategy_returns(w_s3, ret_spy, tx_bps=TX_COST_BPS)

# S4: 50/50 SPY/GLD
ret_s4 = w_s4 * ret_spy + (1 - w_s4) * ret_gld  # rebalanced daily, no TX for constant weight

# Drop initial NaN rows (from lag)
start_idx = 2  # first 2 rows may have NaN from lag + pct_change
all_rets = pd.DataFrame({
    "S0_BH_SPY": ret_s0,
    "S1_Always_12VIX": ret_s1,
    "S2_VIX_Pctile_Cond": ret_s2,
    "S3_VIX_Smooth": ret_s3,
    "S4_5050_SPY_GLD": ret_s4,
}).dropna()

print(f"Valid return days: {len(all_rets)}")


# ============================================================
# PART E: Performance Metrics
# ============================================================
print("\n\nPART E: Full Period Performance Metrics")
print("-" * 60)

def compute_metrics(returns, label="", rf_daily=RF_DAILY, gamma=5):
    """Compute comprehensive performance metrics."""
    r = returns.dropna()
    n = len(r)
    ann_ret = (1 + r).prod() ** (252/n) - 1
    ann_vol = r.std() * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum = (1 + r).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    mdd = drawdown.min() * 100

    calmar = ann_ret / abs(mdd/100) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    # CRRA utility
    crra = np.mean((1 + r) ** (1 - gamma) / (1 - gamma)) if gamma != 1 else np.mean(np.log(1 + r))

    cagr = ann_ret * 100
    cum_return = ((1 + r).prod() - 1) * 100

    result = {
        "label": label,
        "cagr": round(cagr, 3),
        "ann_vol": round(ann_vol * 100, 3),
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 2),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "crra_gamma5": round(crra, 6),
        "cum_return": round(cum_return, 2),
    }

    print(f"  {label}: CAGR={cagr:.2f}%, Vol={ann_vol*100:.1f}%, Sharpe={sharpe:.4f}, "
          f"MDD={mdd:.1f}%, CRRA(5)={crra:.6f}")

    return result

full_metrics = {}
for col in all_rets.columns:
    full_metrics[col] = compute_metrics(all_rets[col], label=col)

RESULTS["full_period_metrics"] = full_metrics

# Sanity check: no strategy should have Sharpe > 2x S0
s0_sharpe = full_metrics["S0_BH_SPY"]["sharpe"]
for key, m in full_metrics.items():
    if key != "S0_BH_SPY" and m["sharpe"] > 2 * s0_sharpe:
        print(f"\n⚠️ WARNING: {key} Sharpe ({m['sharpe']:.4f}) > 2x S0 ({s0_sharpe:.4f}) — POSSIBLE BUG!")


# ============================================================
# PART F: Weight Statistics
# ============================================================
print("\n\nPART F: Weight Statistics")
print("-" * 60)

weight_stats = {}
for name, w in [("S1_Always_12VIX", w_s1), ("S2_VIX_Pctile_Cond", w_s2), ("S3_VIX_Smooth", w_s3)]:
    w_clean = w.loc[all_rets.index].dropna()
    turnover = w_clean.diff().abs().sum() / (len(w_clean) / 252)
    ws = {
        "avg_weight": round(w_clean.mean() * 100, 2),
        "std_weight": round(w_clean.std() * 100, 2),
        "pct_fully_invested": round((w_clean >= 0.99).mean() * 100, 1),
        "pct_half_or_less": round((w_clean <= 0.50).mean() * 100, 1),
        "annualized_turnover_pct": round(turnover * 100, 2),
    }
    weight_stats[name] = ws
    print(f"  {name}: avg={ws['avg_weight']:.1f}%, pct_full={ws['pct_fully_invested']:.1f}%, "
          f"turnover={ws['annualized_turnover_pct']:.0f}%/yr")

RESULTS["weight_stats"] = weight_stats


# ============================================================
# PART G: VIX Regime Analysis
# ============================================================
print("\n\nPART G: VIX Percentile Regime Analysis")
print("-" * 60)

# Define VIX percentile regimes
vix_pctile_aligned = vix_pctile.reindex(all_rets.index)
regime = pd.Series(index=all_rets.index, dtype=str)
regime[vix_pctile_aligned <= 0.20] = "Low (<20th)"
regime[(vix_pctile_aligned > 0.20) & (vix_pctile_aligned <= 0.50)] = "Mid-Low (20-50th)"
regime[(vix_pctile_aligned > 0.50) & (vix_pctile_aligned <= 0.80)] = "Mid-High (50-80th)"
regime[vix_pctile_aligned > 0.80] = "High (>80th)"

regime_results = {}
for r_name in ["Low (<20th)", "Mid-Low (20-50th)", "Mid-High (50-80th)", "High (>80th)"]:
    mask = regime == r_name
    n = mask.sum()
    if n < 10:
        continue

    r_data = {
        "n_days": int(n),
        "pct_time": round(n / len(all_rets) * 100, 2),
    }

    for col in all_rets.columns:
        r_sub = all_rets[col][mask]
        ann = r_sub.mean() * 252 * 100
        r_data[f"{col}_ann_pct"] = round(ann, 3)

    # Insurance cost = BH return - strategy return
    for s_name in ["S1_Always_12VIX", "S2_VIX_Pctile_Cond", "S3_VIX_Smooth"]:
        cost = r_data["S0_BH_SPY_ann_pct"] - r_data[f"{s_name}_ann_pct"]
        r_data[f"{s_name}_insurance_cost"] = round(cost, 3)

    regime_results[r_name] = r_data
    print(f"\n  {r_name}: {n} days ({r_data['pct_time']:.1f}%)")
    print(f"    BH: {r_data['S0_BH_SPY_ann_pct']:.1f}%, S1: {r_data['S1_Always_12VIX_ann_pct']:.1f}%, "
          f"S2: {r_data['S2_VIX_Pctile_Cond_ann_pct']:.1f}%, S3: {r_data['S3_VIX_Smooth_ann_pct']:.1f}%")
    print(f"    Insurance cost: S1={r_data['S1_Always_12VIX_insurance_cost']:.1f}%, "
          f"S2={r_data['S2_VIX_Pctile_Cond_insurance_cost']:.1f}%, "
          f"S3={r_data['S3_VIX_Smooth_insurance_cost']:.1f}%")

RESULTS["vix_regime_analysis"] = regime_results


# ============================================================
# PART H: Insurance Cost Summary
# ============================================================
print("\n\nPART H: Insurance Cost Summary (Full Period)")
print("-" * 60)

s0_cagr = full_metrics["S0_BH_SPY"]["cagr"]
insurance_summary = {}
for s_name in ["S1_Always_12VIX", "S2_VIX_Pctile_Cond", "S3_VIX_Smooth"]:
    cost = s0_cagr - full_metrics[s_name]["cagr"]
    insurance_summary[s_name] = round(cost, 3)
    print(f"  {s_name}: {cost:.3f}%/yr")

# Cost reduction vs S1
s1_cost = insurance_summary["S1_Always_12VIX"]
for s_name in ["S2_VIX_Pctile_Cond", "S3_VIX_Smooth"]:
    s_cost = insurance_summary[s_name]
    reduction = (1 - s_cost / s1_cost) * 100 if s1_cost != 0 else 0
    insurance_summary[f"{s_name}_cost_reduction_vs_S1_pct"] = round(reduction, 1)
    print(f"  {s_name} cost reduction vs S1: {reduction:.1f}%")

RESULTS["insurance_cost_summary"] = insurance_summary


# ============================================================
# PART I: DM Tests
# ============================================================
print("\n\nPART I: Diebold-Mariano Tests")
print("-" * 60)

try:
    from volpred.stats.model_evaluation import strategy_dm_test
    print("  Using volpred.stats.model_evaluation.strategy_dm_test")

    dm_results = {}
    pairs = [
        ("S2 vs S0 (BH SPY)", "S2_VIX_Pctile_Cond", "S0_BH_SPY"),
        ("S2 vs S1 (Always VT)", "S2_VIX_Pctile_Cond", "S1_Always_12VIX"),
        ("S3 vs S0 (BH SPY)", "S3_VIX_Smooth", "S0_BH_SPY"),
        ("S3 vs S1 (Always VT)", "S3_VIX_Smooth", "S1_Always_12VIX"),
        ("S3 vs S4 (50/50)", "S3_VIX_Smooth", "S4_5050_SPY_GLD"),
        ("S2 vs S4 (50/50)", "S2_VIX_Pctile_Cond", "S4_5050_SPY_GLD"),
        ("S1 vs S0 (BH SPY)", "S1_Always_12VIX", "S0_BH_SPY"),
        ("S2 vs S3", "S2_VIX_Pctile_Cond", "S3_VIX_Smooth"),
    ]

    for label, s1_name, s2_name in pairs:
        r1 = all_rets[s1_name].values
        r2 = all_rets[s2_name].values
        t_stat, p_val = strategy_dm_test(r1, r2)
        # Positive t-stat means s1 is better (lower loss = higher return)
        better = s1_name if t_stat > 0 else s2_name
        sig = abs(t_stat) > 3.0  # Harvey threshold
        dm_results[label] = {
            "t_stat": round(t_stat, 4),
            "p_value": round(p_val, 6),
            "significant": sig,
            "better": better,
        }
        sig_str = "***" if sig else ""
        print(f"  {label}: t={t_stat:.4f}, p={p_val:.4f} → {better} {sig_str}")

    RESULTS["dm_tests"] = dm_results

except ImportError:
    print("  WARNING: strategy_dm_test not available, using manual implementation")
    # Fallback: manual DM test
    def manual_dm_test(r1, r2):
        d = r1 - r2  # loss differential (negative return)
        d = -d  # flip: positive means r1 > r2 (r1 better)
        n = len(d)
        d_mean = np.mean(d)
        d_var = np.var(d, ddof=1)
        if d_var == 0:
            return 0.0, 1.0
        t_stat = d_mean / np.sqrt(d_var / n)
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
        return t_stat, p_val

    dm_results = {}
    pairs = [
        ("S2 vs S0 (BH SPY)", "S2_VIX_Pctile_Cond", "S0_BH_SPY"),
        ("S2 vs S1 (Always VT)", "S2_VIX_Pctile_Cond", "S1_Always_12VIX"),
        ("S3 vs S0 (BH SPY)", "S3_VIX_Smooth", "S0_BH_SPY"),
        ("S3 vs S1 (Always VT)", "S3_VIX_Smooth", "S1_Always_12VIX"),
        ("S1 vs S0 (BH SPY)", "S1_Always_12VIX", "S0_BH_SPY"),
    ]

    for label, s1_name, s2_name in pairs:
        r1 = all_rets[s1_name].values
        r2 = all_rets[s2_name].values
        t_stat, p_val = manual_dm_test(r1, r2)
        better = s1_name if t_stat > 0 else s2_name
        sig = abs(t_stat) > 3.0
        dm_results[label] = {
            "t_stat": round(t_stat, 4),
            "p_value": round(p_val, 6),
            "significant": sig,
            "better": better,
        }
        print(f"  {label}: t={t_stat:.4f}, p={p_val:.4f} → {better}")

    RESULTS["dm_tests"] = dm_results


# ============================================================
# PART J: VIX Predictive Power for Forward MDD
# ============================================================
print("\n\nPART J: VIX Predictive Power for Forward MDD")
print("-" * 60)

# Forward 30-day MDD
fwd_mdd_30 = pd.Series(index=all_rets.index, dtype=float)
cum_spy = (1 + all_rets["S0_BH_SPY"]).cumprod()
for i in range(len(cum_spy) - 30):
    window = cum_spy.iloc[i:i+30]
    peak = window.cummax()
    dd = ((window - peak) / peak).min() * 100
    fwd_mdd_30.iloc[i] = dd

fwd_mdd_valid = fwd_mdd_30.dropna()
vix_aligned = vix.reindex(fwd_mdd_valid.index).dropna()
vix_pctile_aligned2 = vix_pctile.reindex(fwd_mdd_valid.index).dropna()

# Use common index
common_idx = vix_aligned.index.intersection(fwd_mdd_valid.index).intersection(vix_pctile_aligned2.index)
vix_a = vix_aligned.loc[common_idx]
pctile_a = vix_pctile_aligned2.loc[common_idx]
mdd_a = fwd_mdd_valid.loc[common_idx]

# Correlations
vix_pearson = np.corrcoef(vix_a.values, mdd_a.values)[0, 1]
vix_spearman, vix_sp_p = stats.spearmanr(vix_a.values, mdd_a.values)
pctile_pearson = np.corrcoef(pctile_a.values, mdd_a.values)[0, 1]
pctile_spearman, pctile_sp_p = stats.spearmanr(pctile_a.values, mdd_a.values)

print(f"  VIX level → fwd 30d MDD: Pearson={vix_pearson:.4f}, Spearman={vix_spearman:.4f} (p={vix_sp_p:.2e})")
print(f"  VIX percentile → fwd 30d MDD: Pearson={pctile_pearson:.4f}, Spearman={pctile_spearman:.4f} (p={pctile_sp_p:.2e})")

# Quintile analysis
quintiles = pd.qcut(pctile_a, 5, labels=["Q1(Low)", "Q2", "Q3", "Q4", "Q5(High)"])
quintile_data = {}
for q in ["Q1(Low)", "Q2", "Q3", "Q4", "Q5(High)"]:
    mask = quintiles == q
    quintile_data[q] = {
        "avg_vix_pctile": round(pctile_a[mask].mean(), 3),
        "avg_fwd_mdd_30": round(mdd_a[mask].mean(), 3),
        "std_fwd_mdd_30": round(mdd_a[mask].std(), 3),
    }
    print(f"  {q}: avg_pctile={quintile_data[q]['avg_vix_pctile']:.3f}, "
          f"avg_fwd_mdd={quintile_data[q]['avg_fwd_mdd_30']:.2f}%")

# Check monotonicity
avgs = [quintile_data[q]["avg_fwd_mdd_30"] for q in ["Q1(Low)", "Q2", "Q3", "Q4", "Q5(High)"]]
monotonic = all(avgs[i] >= avgs[i+1] for i in range(len(avgs)-1))
print(f"  Monotonicity (Q1 > Q5 MDD): {monotonic}")

RESULTS["vix_predictive_power"] = {
    "vix_to_fwd_mdd_pearson": round(vix_pearson, 4),
    "vix_to_fwd_mdd_spearman": round(vix_spearman, 4),
    "vix_spearman_pval": float(f"{vix_sp_p:.2e}"),
    "pctile_to_fwd_mdd_pearson": round(pctile_pearson, 4),
    "pctile_to_fwd_mdd_spearman": round(pctile_spearman, 4),
    "pctile_spearman_pval": float(f"{pctile_sp_p:.2e}"),
    "quintile_analysis": quintile_data,
    "monotonicity": monotonic,
}


# ============================================================
# PART K: Rolling Insurance Cost
# ============================================================
print("\n\nPART K: Rolling 2-Year Insurance Cost")
print("-" * 60)

rolling_window = 504  # ~2 years
rolling_costs = {}

for s_name in ["S1_Always_12VIX", "S2_VIX_Pctile_Cond", "S3_VIX_Smooth"]:
    cost_series = (all_rets["S0_BH_SPY"] - all_rets[s_name]).rolling(rolling_window).sum()
    cost_ann = cost_series / 2 * 100  # annualize 2yr window
    cost_ann = cost_ann.dropna()

    rc = {
        "mean": round(cost_ann.mean(), 3),
        "median": round(cost_ann.median(), 3),
        "std": round(cost_ann.std(), 3),
        "min": round(cost_ann.min(), 3),
        "max": round(cost_ann.max(), 3),
        "pct_free": round((cost_ann < 0).mean() * 100, 1),
    }
    rolling_costs[s_name] = rc
    print(f"  {s_name}: mean={rc['mean']:.2f}%, median={rc['median']:.2f}%, "
          f"pct_free={rc['pct_free']:.1f}%")

RESULTS["rolling_2yr_insurance_cost"] = rolling_costs


# ============================================================
# PART L: Cross-OOS Validation
# ============================================================
print("\n\nPART L: Cross-OOS Validation (5 non-overlapping 2-year periods)")
print("-" * 60)

oos_periods = [
    ("2007-01-01", "2008-12-31"),
    ("2011-01-01", "2012-12-31"),
    ("2015-01-01", "2016-12-31"),
    ("2019-01-01", "2020-12-31"),
    ("2023-01-01", "2024-12-31"),
]

cross_oos = {"periods": {}}
s2_wins = 0
s3_wins = 0

for start, end in oos_periods:
    mask = (all_rets.index >= start) & (all_rets.index <= end)
    sub = all_rets.loc[mask]

    if len(sub) < 100:
        print(f"  {start}~{end}: SKIP (only {len(sub)} days)")
        continue

    period_key = f"{start}~{end}"
    cross_oos["periods"][period_key] = {}

    print(f"\n  {period_key} ({len(sub)} days):")
    for col in all_rets.columns:
        r = sub[col]
        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0
        cross_oos["periods"][period_key][col] = round(sharpe, 4)
        print(f"    {col}: Sharpe={sharpe:.4f}")

    # Check if S2/S3 beat S0
    if cross_oos["periods"][period_key]["S2_VIX_Pctile_Cond"] > cross_oos["periods"][period_key]["S0_BH_SPY"]:
        s2_wins += 1
    if cross_oos["periods"][period_key]["S3_VIX_Smooth"] > cross_oos["periods"][period_key]["S0_BH_SPY"]:
        s3_wins += 1

cross_oos["s2_wins_s0"] = s2_wins
cross_oos["s3_wins_s0"] = s3_wins
cross_oos["total_periods"] = len(oos_periods)

print(f"\n  S2 beats S0 (BH SPY): {s2_wins}/{len(oos_periods)}")
print(f"  S3 beats S0 (BH SPY): {s3_wins}/{len(oos_periods)}")

# Also check vs S4 (50/50)
s2_wins_s4 = sum(1 for p in cross_oos["periods"].values()
                 if p.get("S2_VIX_Pctile_Cond", 0) > p.get("S4_5050_SPY_GLD", 0))
s3_wins_s4 = sum(1 for p in cross_oos["periods"].values()
                 if p.get("S3_VIX_Smooth", 0) > p.get("S4_5050_SPY_GLD", 0))
cross_oos["s2_wins_s4"] = s2_wins_s4
cross_oos["s3_wins_s4"] = s3_wins_s4
print(f"  S2 beats S4 (50/50): {s2_wins_s4}/{len(oos_periods)}")
print(f"  S3 beats S4 (50/50): {s3_wins_s4}/{len(oos_periods)}")

RESULTS["cross_oos"] = cross_oos


# ============================================================
# PART M: OOS Period Metrics (2023-2024)
# ============================================================
print("\n\nPART M: OOS Period Metrics (2023-01-01 ~ 2024-12-31)")
print("-" * 60)

oos_mask = (all_rets.index >= "2023-01-01") & (all_rets.index <= "2024-12-31")
oos_data = all_rets.loc[oos_mask]
oos_metrics = {}
for col in all_rets.columns:
    oos_metrics[col] = compute_metrics(oos_data[col], label=f"{col}_OOS")

RESULTS["oos_metrics"] = oos_metrics


# ============================================================
# PART N: Comparison with K811v2 (VVIX-based)
# ============================================================
print("\n\nPART N: Comparison with K811v2 (VVIX-based)")
print("-" * 60)

k811_metrics = {
    "S1_Always_12VIX": {"sharpe": 0.2526, "cagr": 4.412, "mdd": -31.71},
    "S2_VoV_Conditional": {"sharpe": 0.2462, "cagr": 6.071, "mdd": -59.92},
    "S3_Smooth_VoV": {"sharpe": 0.3099, "cagr": 6.035, "mdd": -43.61},
    "S0_BH_SPY": {"sharpe": 0.3188, "cagr": 8.432, "mdd": -56.47},
}
k811_insurance = {
    "S1": 3.757,
    "S2_VoV_Cond": 2.202,
    "S3_Smooth_VoV": 2.236,
}
k811_cross_oos_s2 = 1  # out of 4 (was 5 but only 4 had VVIX)
k811_cross_oos_s3 = 1

comparison = {
    "K811v2_VVIX": {
        "S2_sharpe": k811_metrics["S2_VoV_Conditional"]["sharpe"],
        "S3_sharpe": k811_metrics["S3_Smooth_VoV"]["sharpe"],
        "S2_insurance_cost": k811_insurance["S2_VoV_Cond"],
        "S3_insurance_cost": k811_insurance["S3_Smooth_VoV"],
        "S2_cross_oos_wins": k811_cross_oos_s2,
        "S3_cross_oos_wins": k811_cross_oos_s3,
    },
    "K828_VIX_Only": {
        "S2_sharpe": full_metrics["S2_VIX_Pctile_Cond"]["sharpe"],
        "S3_sharpe": full_metrics["S3_VIX_Smooth"]["sharpe"],
        "S2_insurance_cost": insurance_summary["S2_VIX_Pctile_Cond"],
        "S3_insurance_cost": insurance_summary["S3_VIX_Smooth"],
        "S2_cross_oos_wins": s2_wins,
        "S3_cross_oos_wins": s3_wins,
    },
}

print("\n  K811v2 (VVIX) vs K828 (VIX-only):")
print(f"  {'Metric':<30} {'K811v2 (VVIX)':<20} {'K828 (VIX-only)':<20} {'Better':<10}")
print(f"  {'-'*80}")

for metric_name, k811_key, k828_key, higher_is_better in [
    ("S2 Sharpe", "S2_sharpe", "S2_sharpe", True),
    ("S3 Sharpe", "S3_sharpe", "S3_sharpe", True),
    ("S2 Insurance Cost", "S2_insurance_cost", "S2_insurance_cost", False),
    ("S3 Insurance Cost", "S3_insurance_cost", "S3_insurance_cost", False),
    ("S2 Cross-OOS Wins", "S2_cross_oos_wins", "S2_cross_oos_wins", True),
    ("S3 Cross-OOS Wins", "S3_cross_oos_wins", "S3_cross_oos_wins", True),
]:
    v1 = comparison["K811v2_VVIX"][k811_key]
    v2 = comparison["K828_VIX_Only"][k828_key]
    if higher_is_better:
        winner = "K828" if v2 > v1 else "K811v2" if v1 > v2 else "TIE"
    else:
        winner = "K828" if v2 < v1 else "K811v2" if v1 < v2 else "TIE"
    print(f"  {metric_name:<30} {v1:<20} {v2:<20} {winner:<10}")

RESULTS["k811v2_comparison"] = comparison


# ============================================================
# PART O: Sensitivity Analysis (percentile thresholds)
# ============================================================
print("\n\nPART O: Sensitivity Analysis (threshold variants)")
print("-" * 60)

sensitivity = {}
threshold_sets = [
    (0.10, 0.90, "10-90"),
    (0.15, 0.85, "15-85"),
    (0.20, 0.80, "20-80 (base)"),
    (0.25, 0.75, "25-75"),
    (0.30, 0.70, "30-70"),
]

for low_th, high_th, name in threshold_sets:
    # Recompute S2 with different thresholds
    full_vt_weight = (12.0 / vix_lagged).clip(upper=1.0)
    minimal_weight = 0.80

    w_test = pd.Series(index=ret_spy.index, dtype=float)
    high_mask = vix_pctile_lagged > high_th
    low_mask = vix_pctile_lagged < low_th
    mid_mask = ~high_mask & ~low_mask

    w_test[high_mask] = full_vt_weight[high_mask]
    w_test[low_mask] = minimal_weight

    if mid_mask.any():
        span = high_th - low_th
        interp_factor = (vix_pctile_lagged[mid_mask] - low_th) / span
        w_test[mid_mask] = minimal_weight + (full_vt_weight[mid_mask] - minimal_weight) * interp_factor

    w_test = w_test.clip(lower=0.0, upper=1.0)

    ret_test = compute_strategy_returns(w_test, ret_spy, tx_bps=TX_COST_BPS)
    ret_test_valid = ret_test.reindex(all_rets.index).dropna()

    ann_ret = ret_test_valid.mean() * 252
    ann_vol = ret_test_valid.std() * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0
    cagr = ann_ret * 100

    cum = (1 + ret_test_valid).cumprod()
    mdd = ((cum - cum.cummax()) / cum.cummax()).min() * 100

    insurance_cost = full_metrics["S0_BH_SPY"]["cagr"] - cagr

    sensitivity[name] = {
        "low_threshold": low_th,
        "high_threshold": high_th,
        "sharpe": round(sharpe, 4),
        "cagr": round(cagr, 3),
        "mdd": round(mdd, 2),
        "insurance_cost": round(insurance_cost, 3),
    }
    print(f"  {name}: Sharpe={sharpe:.4f}, CAGR={cagr:.2f}%, MDD={mdd:.1f}%, InsuranceCost={insurance_cost:.2f}%")

RESULTS["sensitivity_analysis"] = sensitivity

# Check sensitivity: Sharpe variation < 30%?
base_sharpe = sensitivity["20-80 (base)"]["sharpe"]
sharpe_values = [s["sharpe"] for s in sensitivity.values()]
max_dev = max(abs(s - base_sharpe) / abs(base_sharpe) for s in sharpe_values) * 100 if base_sharpe != 0 else 0
print(f"\n  Max Sharpe deviation from base: {max_dev:.1f}%")
print(f"  Sensitivity passed (<30%): {max_dev < 30}")


# ============================================================
# PART P: Summary & Save Results
# ============================================================
print("\n\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

print(f"""
K828: VIX-Only Insurance Premium Conditioning
Period: {RESULTS['data']['backtest_start']} ~ {RESULTS['data']['backtest_end']} ({RESULTS['data']['n_years']} years)

Full-Period Metrics:
  S0 BH SPY:          Sharpe={full_metrics['S0_BH_SPY']['sharpe']:.4f}, CAGR={full_metrics['S0_BH_SPY']['cagr']:.2f}%, MDD={full_metrics['S0_BH_SPY']['mdd']:.1f}%
  S1 Always 12/VIX:   Sharpe={full_metrics['S1_Always_12VIX']['sharpe']:.4f}, CAGR={full_metrics['S1_Always_12VIX']['cagr']:.2f}%, MDD={full_metrics['S1_Always_12VIX']['mdd']:.1f}%
  S2 VIX-Pctile Cond: Sharpe={full_metrics['S2_VIX_Pctile_Cond']['sharpe']:.4f}, CAGR={full_metrics['S2_VIX_Pctile_Cond']['cagr']:.2f}%, MDD={full_metrics['S2_VIX_Pctile_Cond']['mdd']:.1f}%
  S3 VIX-Smooth:      Sharpe={full_metrics['S3_VIX_Smooth']['sharpe']:.4f}, CAGR={full_metrics['S3_VIX_Smooth']['cagr']:.2f}%, MDD={full_metrics['S3_VIX_Smooth']['mdd']:.1f}%
  S4 50/50 SPY/GLD:   Sharpe={full_metrics['S4_5050_SPY_GLD']['sharpe']:.4f}, CAGR={full_metrics['S4_5050_SPY_GLD']['cagr']:.2f}%, MDD={full_metrics['S4_5050_SPY_GLD']['mdd']:.1f}%

Insurance Cost (CAGR difference from BH):
  S1 Always: {insurance_summary['S1_Always_12VIX']:.2f}%/yr
  S2 VIX-Cond: {insurance_summary['S2_VIX_Pctile_Cond']:.2f}%/yr (reduction: {insurance_summary.get('S2_VIX_Pctile_Cond_cost_reduction_vs_S1_pct', 'N/A')}%)
  S3 VIX-Smooth: {insurance_summary['S3_VIX_Smooth']:.2f}%/yr (reduction: {insurance_summary.get('S3_VIX_Smooth_cost_reduction_vs_S1_pct', 'N/A')}%)

Cross-OOS (S wins BH SPY on Sharpe):
  S2: {s2_wins}/{len(oos_periods)}
  S3: {s3_wins}/{len(oos_periods)}

Conclusion:
  VIX-only conditioning {'improves' if full_metrics['S2_VIX_Pctile_Cond']['sharpe'] > full_metrics['S1_Always_12VIX']['sharpe'] else 'does not improve'}
  Sharpe over always-VT, and {'reduces' if insurance_summary['S2_VIX_Pctile_Cond'] < insurance_summary['S1_Always_12VIX'] else 'does not reduce'} insurance cost.
""")

# Add experiment metadata
RESULTS["experiment"] = "K828"
RESULTS["title"] = "VIX-Only Insurance Premium Conditioning"
RESULTS["proposed_by"] = "Claude (K811v2 follow-up)"
RESULTS["executed_by"] = "Claude"
RESULTS["data_source"] = "yfinance (SPY, GLD, ^VIX daily)"
RESULTS["methodology"] = {
    "vix_percentile": "Expanding window percentile (no lookahead)",
    "s2_high_threshold": 0.80,
    "s2_low_threshold": 0.20,
    "s2_minimal_weight": 0.80,
    "s3_scaling": "0.5 + 0.5 * VIX_percentile",
    "lag": "All signals shifted by 1 day (signal.shift(1))",
    "tx_cost": "5 bps per unit weight change",
    "vt_target": "12/VIX",
}
RESULTS["references"] = [
    "K811v2: VVIX conditioning — VIX r=-0.327 > VVIX r=-0.148 for MDD",
    "K41: VT = ~4%/yr constant insurance",
    "K229: VT Insurance Pricing — 3.05%/yr expected cost",
    "K687: No VT beats BH 50/50 on Sharpe after correct lag",
    "K688: VT wins under CRRA utility gamma >= 5",
    "Harvey, Liu, Zhu (2016) t>3.0 threshold",
]

# Save results
output_path = PROJECT / "experiments" / "k828_vix_only_insurance_results.json"
with open(output_path, "w") as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\nResults saved to: {output_path}")
print("K828 complete.")
