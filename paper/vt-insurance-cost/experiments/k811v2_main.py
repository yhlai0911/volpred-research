#!/usr/bin/env python3
"""
K811v2: Convexity-Adjusted Insurance Premium -- VoV-Conditional VT (Bug-Fixed)
==============================================================================
[提出: Gemini #2 (original K811), 執行: Claude (K811v2 fix)]

Fixes 2 HIGH severity bugs found by Codex review of K811:

BUG 1 (HIGH): VVIX Pre-2012 Data Reliability
  K811 used VVIX from 2006, but VVIX had poor liquidity before 2012-01-03.
  FIX: Restrict entire backtest to 2012-01-01 ~ 2024-12-31 (VVIX reliable era only).
  No proxy/fallback filling -- only real VVIX data used.

BUG 2 (HIGH): Cost Calculation Mislabel
  K811 computed "insurance cost" as BH_return - VT_return, but this conflates:
    (a) Opportunity cost: return difference due to lower equity exposure
    (b) Direct cost: transaction costs from weight changes
  These were reported as a single "cost" number, mislabeling ~40% of the values.
  FIX: Decompose into opportunity_cost and direct_cost, report both separately.
  Total insurance cost = opportunity_cost + direct_cost.

References:
  - K811: Original VoV-conditional VT (2006-2026, VVIX proxy issues)
  - K41: VT = constant ~4%/yr insurance at all horizons
  - K229: VT Insurance Pricing -- 3.05%/yr expected cost
  - K687: No VT strategy beats BH 50/50 on Sharpe after correct lag
  - K688: VT wins under CRRA utility gamma >= 5
  - Huang & Shaliastovich (2015) "Volatility-of-Volatility Risk"
  - Harvey, Liu, Zhu (2016) t>3.0 threshold

Data: SPY, GLD, ^VIX, ^VVIX from yfinance
Period: 2012-01-01 ~ 2024-12-31 (VVIX reliable era only)
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
print("K811v2: Convexity-Adjusted Insurance Premium -- VoV-Conditional VT (Bug-Fixed)")
print("[提出: Gemini #2 (K811), 執行: Claude (K811v2 fix)]")
print("=" * 80)
print("\nBUG FIXES:")
print("  1. VVIX data restricted to 2012+ (reliable era only)")
print("  2. Insurance cost decomposed: opportunity cost vs direct cost")
print()
print("PART A: Data Download & Descriptive Statistics")
print("-" * 60)

import yfinance as yf

import argparse
_parser = argparse.ArgumentParser()
_parser.add_argument("--threshold", type=float, default=1.0)
_parser.add_argument("--output-suffix", type=str, default="")
_args = _parser.parse_args()
VOV_THRESHOLD = _args.threshold
OUTPUT_SUFFIX = _args.output_suffix


# Download data -- start from 2011 for enough warm-up (expanding z-score needs 60 days)
tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX", "VVIX": "^VVIX"}
raw = {}

for name, ticker in tickers.items():
    df = yf.download(ticker, start="2011-01-01", end="2025-01-01",
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df[["Close"]].rename(columns={"Close": name.lower()})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Merge all four -- inner join to keep only dates with ALL data
data = raw["SPY"].join(raw["GLD"], how="inner") \
                 .join(raw["VIX"], how="inner") \
                 .join(raw["VVIX"], how="inner")  # BUG 1 FIX: inner join, require real VVIX
data = data.dropna()

# BUG 1 FIX: Only use data from 2012-01-01 onwards (VVIX reliable era)
BACKTEST_START = "2012-01-01"
BACKTEST_END = "2024-12-31"

# Verify VVIX data quality: check for excessive NaN or zero in early period
pre_2012_vvix = raw["VVIX"].loc[:"2011-12-31"]
post_2012_vvix = raw["VVIX"].loc["2012-01-01":]
print(f"\n  VVIX data quality check:")
print(f"    Pre-2012 VVIX rows:  {len(pre_2012_vvix)} (EXCLUDED -- unreliable liquidity)")
print(f"    Post-2012 VVIX rows: {len(post_2012_vvix)} (USED)")
if len(post_2012_vvix) > 0:
    vvix_na = post_2012_vvix["vvix"].isna().sum()
    vvix_zero = (post_2012_vvix["vvix"] == 0).sum()
    print(f"    Post-2012 NaN: {vvix_na}, Zeros: {vvix_zero}")

# Compute returns
data["spy_ret"] = np.log(data["spy"] / data["spy"].shift(1))
data["gld_ret"] = np.log(data["gld"] / data["gld"].shift(1))

# VoV: use VVIX directly (no proxy/fallback needed since inner join)
data["vov"] = data["vvix"]

# VIX direction: 5-day change
data["vix_chg_5d"] = data["vix"] - data["vix"].shift(5)
data["vix_rising"] = (data["vix_chg_5d"] > 0).astype(int)

# Drop NaN rows
data = data.dropna(subset=["spy_ret", "gld_ret", "vov", "vix_rising"])

# Trim to reliable VVIX backtest period
data = data.loc[BACKTEST_START:BACKTEST_END]

n = len(data)
n_years = n / 252
print(f"\n  Backtest: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Trading days: {n}, Years: {n_years:.1f}")
print(f"  VoV source: VVIX (real data only, no proxy)")

# Descriptive statistics
print(f"\n  Descriptive Statistics:")
print(f"  {'':20s} {'Mean':>10} {'Std':>10} {'Skew':>8} {'Kurt':>8} {'Min':>10} {'Max':>10}")
print(f"  {'-'*70}")
for col, label in [("vix", "VIX"), ("vov", "VVIX"),
                   ("spy_ret", "SPY daily ret"), ("gld_ret", "GLD daily ret")]:
    s = data[col]
    print(f"  {label:20s} {s.mean():>10.4f} {s.std():>10.4f} {s.skew():>8.2f} "
          f"{s.kurtosis():>8.2f} {s.min():>10.4f} {s.max():>10.4f}")

RESULTS["data"] = {
    "backtest_start": str(data.index[0].date()),
    "backtest_end": str(data.index[-1].date()),
    "n_days": int(n),
    "n_years": round(n_years, 2),
    "vov_source": "VVIX (real data only, no proxy filling)",
    "vvix_reliable_era": "2012-01-01 onwards",
    "bug1_fix": "Excluded all pre-2012 VVIX data; inner join requires real VVIX",
}


# ============================================================
# PART B: VoV Regime Classification
# ============================================================
print("\n" + "=" * 80)
print("PART B: VoV Regime Classification")
print("-" * 60)

# Expanding z-score for VoV (no lookahead)
vov_expanding_mean = data["vov"].expanding(min_periods=60).mean()
vov_expanding_std = data["vov"].expanding(min_periods=60).std()
data["vov_zscore"] = (data["vov"] - vov_expanding_mean) / vov_expanding_std

# *** CRITICAL: shift all signals by 1 day to avoid lookahead ***
data["vov_zscore_lag"] = data["vov_zscore"].shift(1)
data["vix_rising_lag"] = data["vix_rising"].shift(1)
data["vov_lag"] = data["vov"].shift(1)
data["vix_lag"] = data["vix"].shift(1)

# VoV regime classification (using lagged signals)
def classify_vov_regime(row):
    """Classify VoV regime using lagged indicators."""
    vov_z = row["vov_zscore_lag"]
    vix_rising = row["vix_rising_lag"]

    if pd.isna(vov_z) or pd.isna(vix_rising):
        return "Unknown"

    high_vov = vov_z > VOV_THRESHOLD  # VoV threshold from CLI

    if high_vov and vix_rising:
        return "HighVoV_Rising"    # Storm approaching -- insure!
    elif high_vov and not vix_rising:
        return "HighVoV_Falling"   # VoV-decay, insurance over-priced
    elif not high_vov and vix_rising:
        return "LowVoV_Rising"     # Minor uptick, low concern
    else:
        return "LowVoV_Falling"    # Calm, insurance just drags


data["vov_regime"] = data.apply(classify_vov_regime, axis=1)

# Regime distribution
regime_counts = data["vov_regime"].value_counts()
print(f"\n  VoV Regime Distribution:")
print(f"  {'Regime':<20} {'Count':>8} {'Pct':>8}")
print(f"  {'-'*40}")
for regime, count in regime_counts.items():
    print(f"  {regime:<20} {count:>8} {count/n*100:>7.1f}%")

RESULTS["vov_regimes"] = {
    regime: {"count": int(count), "pct": round(count / n * 100, 2)}
    for regime, count in regime_counts.items()
}


# ============================================================
# PART C: Strategy Construction
# ============================================================
print("\n" + "=" * 80)
print("PART C: Strategy Construction")
print("-" * 60)


def compute_metrics(daily_rets, label="", years=None):
    """Compute standard performance metrics."""
    rets = np.array(daily_rets, dtype=np.float64)
    yr = years if years is not None else n_years
    cum = np.exp(np.nancumsum(rets))
    total_ret = cum[-1] / cum[0] if cum[0] > 0 else 1.0
    cagr = total_ret ** (1 / yr) - 1
    ann_vol = np.nanstd(rets) * np.sqrt(252)
    excess = np.nanmean(rets) - RF_DAILY
    sharpe = excess / np.nanstd(rets) * np.sqrt(252) if np.nanstd(rets) > 0 else 0.0
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = np.nanmin(dd)
    calmar = cagr / abs(mdd) if mdd != 0 else 0.0

    # Sortino
    downside = rets[rets < 0]
    downside_vol = np.sqrt(np.mean(downside ** 2)) * np.sqrt(252) if len(downside) > 0 else 1e-10
    sortino = (np.nanmean(rets) * 252 - RF_ANNUAL) / downside_vol

    # CRRA utility gamma=5
    gamma = 5
    simple_rets = np.exp(rets) - 1
    wealth = np.cumprod(1 + simple_rets)
    crra = np.mean((np.maximum(wealth, 1e-10) ** (1 - gamma) - 1) / (1 - gamma))

    return {
        "label": label,
        "cagr": round(cagr * 100, 3),
        "ann_vol": round(ann_vol * 100, 3),
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "crra_gamma5": round(crra, 6),
        "cum_return": round((total_ret - 1) * 100, 2),
    }


def apply_tx_cost(weights, cost_bps=TX_COST_BPS):
    """Apply transaction cost proportional to weight changes.
    Returns per-day tx cost array (always positive)."""
    tx = np.zeros(len(weights))
    for i in range(1, len(weights)):
        delta_w = abs(weights[i] - weights[i - 1])
        tx[i] = delta_w * cost_bps / 10000.0
    return tx


spy_rets = data["spy_ret"].values
gld_rets = data["gld_ret"].values
vix_vals = data["vix_lag"].values  # already lagged
vov_z = data["vov_zscore_lag"].values
vix_rising = data["vix_rising_lag"].values
vov_regime = data["vov_regime"].values

# ---------- S0: BH SPY ----------
s0_weights = np.ones(n)  # always 100% invested
s0_rets = spy_rets.copy()
s0_tx = np.zeros(n)  # no trading

# ---------- S1: Always 12/VIX ----------
s1_weights = np.zeros(n)
for i in range(n):
    if not np.isnan(vix_vals[i]) and vix_vals[i] > 0:
        s1_weights[i] = min(12.0 / vix_vals[i], 1.0)
    else:
        s1_weights[i] = 1.0  # fallback

s1_tx = apply_tx_cost(s1_weights)
s1_rets = s1_weights * spy_rets - s1_tx

# ---------- S2: VoV-Conditional VT ----------
# High VoV + Rising VIX -> 12/VIX insurance; otherwise -> BH SPY (weight=1)
s2_weights = np.zeros(n)
for i in range(n):
    if vov_regime[i] == "HighVoV_Rising":
        if not np.isnan(vix_vals[i]) and vix_vals[i] > 0:
            s2_weights[i] = min(12.0 / vix_vals[i], 1.0)
        else:
            s2_weights[i] = 1.0
    else:
        s2_weights[i] = 1.0  # fully invested

s2_tx = apply_tx_cost(s2_weights)
s2_rets = s2_weights * spy_rets - s2_tx

# ---------- S3: Smooth VoV VT ----------
# insurance_intensity = clip(vov_zscore, 0, 1)
# weight = 1 - insurance_intensity * (1 - 12/VIX)
s3_weights = np.zeros(n)
for i in range(n):
    z = vov_z[i] if not np.isnan(vov_z[i]) else 0.0
    insurance_intensity = np.clip(z, 0.0, 1.0)

    if not np.isnan(vix_vals[i]) and vix_vals[i] > 0:
        vt_weight = min(12.0 / vix_vals[i], 1.0)
    else:
        vt_weight = 1.0

    # Blend: full equity (1.0) when z<=0, 12/VIX when z>=1
    s3_weights[i] = 1.0 - insurance_intensity * (1.0 - vt_weight)

s3_tx = apply_tx_cost(s3_weights)
s3_rets = s3_weights * spy_rets - s3_tx

# ---------- S4: 50/50 SPY/GLD ----------
s4_rets = 0.5 * spy_rets + 0.5 * gld_rets

print("  All strategies computed.")
print(f"  S0: BH SPY")
print(f"  S1: Always 12/VIX SPY")
print(f"  S2: VoV-Conditional VT (insure only on HighVoV+Rising)")
print(f"  S3: Smooth VoV VT (continuous adjustment)")
print(f"  S4: 50/50 SPY/GLD")


# ============================================================
# PART D: Full-Period Performance
# ============================================================
print("\n" + "=" * 80)
print("PART D: Full-Period Performance (2012-2024)")
print("-" * 60)

strategies = {
    "S0_BH_SPY": s0_rets,
    "S1_Always_12VIX": s1_rets,
    "S2_VoV_Conditional": s2_rets,
    "S3_Smooth_VoV": s3_rets,
    "S4_5050_SPY_GLD": s4_rets,
}

all_metrics = {}
print(f"\n  {'Strategy':<25} {'CAGR':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8} "
      f"{'Calmar':>8} {'Sortino':>8} {'CRRA-5':>10}")
print(f"  {'-'*95}")

for name, rets in strategies.items():
    m = compute_metrics(rets, name)
    all_metrics[name] = m
    print(f"  {name:<25} {m['cagr']:>7.2f}% {m['ann_vol']:>7.2f}% {m['sharpe']:>8.4f} "
          f"{m['mdd']:>7.2f}% {m['calmar']:>8.4f} {m['sortino']:>8.4f} {m['crra_gamma5']:>10.6f}")

RESULTS["full_period_metrics"] = all_metrics


# ============================================================
# PART E: OOS Performance (2023-2024)
# ============================================================
print("\n" + "=" * 80)
print("PART E: OOS Performance (2023-01-01 ~ 2024-12-31)")
print("-" * 60)

oos_mask = (data.index >= "2023-01-01") & (data.index <= "2024-12-31")
oos_n = oos_mask.sum()
oos_years = oos_n / 252

oos_strategies = {
    "S0_BH_SPY": s0_rets[oos_mask],
    "S1_Always_12VIX": s1_rets[oos_mask],
    "S2_VoV_Conditional": s2_rets[oos_mask],
    "S3_Smooth_VoV": s3_rets[oos_mask],
    "S4_5050_SPY_GLD": s4_rets[oos_mask],
}

oos_metrics = {}
print(f"\n  OOS: {oos_n} days ({oos_years:.2f} years)")
print(f"\n  {'Strategy':<25} {'CAGR':>8} {'Vol':>8} {'Sharpe':>8} {'MDD':>8} "
      f"{'Calmar':>8} {'CRRA-5':>10}")
print(f"  {'-'*80}")

for name, rets in oos_strategies.items():
    m = compute_metrics(rets, name + "_OOS", years=oos_years)
    oos_metrics[name] = m
    print(f"  {name:<25} {m['cagr']:>7.2f}% {m['ann_vol']:>7.2f}% {m['sharpe']:>8.4f} "
          f"{m['mdd']:>7.2f}% {m['calmar']:>8.4f} {m['crra_gamma5']:>10.6f}")

RESULTS["oos_metrics"] = oos_metrics


# ============================================================
# PART F: DM Tests
# ============================================================
print("\n" + "=" * 80)
print("PART F: Diebold-Mariano Tests (Harvey t>3.0)")
print("-" * 60)

try:
    from volpred.stats.model_evaluation import strategy_dm_test
    dm_available = True
except ImportError:
    dm_available = False
    print("  WARNING: volpred.stats not available, using manual DM test")

    def strategy_dm_test(r1, r2, h=1, loss_fn="negative_return"):
        """Simple DM test fallback."""
        if loss_fn == "negative_return":
            d = -r1 - (-r2)  # d = r2 - r1
        elif loss_fn == "downside":
            d = np.where(r1 < 0, r1 ** 2, 0) - np.where(r2 < 0, r2 ** 2, 0)
        else:
            d = -(r1 ** 2) + r2 ** 2

        n_d = len(d)
        d_bar = np.mean(d)
        gamma_0 = np.var(d, ddof=1)
        var_d = gamma_0
        for k in range(1, h + 1):
            gamma_k = np.cov(d[k:], d[:-k])[0, 1]
            var_d += 2 * (1 - k / (h + 1)) * gamma_k
        se = np.sqrt(var_d / n_d) if var_d > 0 else 1e-10
        t_stat = d_bar / se
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n_d - 1))
        return t_stat, p_val

dm_results = {}
pairs = [
    ("S2_VoV_Conditional", "S0_BH_SPY", "S2 vs S0 (BH SPY)"),
    ("S2_VoV_Conditional", "S1_Always_12VIX", "S2 vs S1 (Always VT)"),
    ("S3_Smooth_VoV", "S0_BH_SPY", "S3 vs S0 (BH SPY)"),
    ("S3_Smooth_VoV", "S1_Always_12VIX", "S3 vs S1 (Always VT)"),
    ("S3_Smooth_VoV", "S4_5050_SPY_GLD", "S3 vs S4 (50/50)"),
    ("S1_Always_12VIX", "S0_BH_SPY", "S1 vs S0 (BH SPY)"),
]

print(f"\n  {'Comparison':<30} {'t-stat':>8} {'p-value':>10} {'Significant':>12}")
print(f"  {'-'*65}")

for s_a, s_b, label in pairs:
    r_a = strategies[s_a]
    r_b = strategies[s_b]
    t_stat, p_val = strategy_dm_test(r_a, r_b, h=1, loss_fn="negative_return")
    sig = "|t|>3.0" if abs(t_stat) > 3.0 else "NO"
    dm_results[label] = {
        "t_stat": round(t_stat, 4),
        "p_value": round(p_val, 6),
        "significant": abs(t_stat) > 3.0,
        "better": s_a if t_stat < 0 else s_b,
    }
    print(f"  {label:<30} {t_stat:>8.4f} {p_val:>10.6f} {sig:>12}")

RESULTS["dm_tests"] = dm_results


# ============================================================
# PART G: Insurance Cost by VoV Regime (BUG 2 FIX: Decomposed)
# ============================================================
print("\n" + "=" * 80)
print("PART G: Insurance Cost by VoV Regime (BUG 2 FIX: Decomposed)")
print("-" * 60)

print("""
  BUG 2 FIX: Insurance cost is now decomposed into TWO components:
  (a) Opportunity cost = BH_return - strategy_return_before_TX
      (return given up due to lower equity exposure)
  (b) Direct cost = transaction costs from weight changes
      (turnover-driven friction)
  Total cost = opportunity_cost + direct_cost
""")

regime_insurance = {}
regimes_to_check = ["HighVoV_Rising", "HighVoV_Falling", "LowVoV_Rising", "LowVoV_Falling"]

# Pre-compute gross returns (before TX) for each strategy
s1_rets_gross = s1_weights * spy_rets  # no tx
s2_rets_gross = s2_weights * spy_rets
s3_rets_gross = s3_weights * spy_rets

print(f"  {'Regime':<20} {'Days':>6} {'%':>7} | {'BH Ann%':>9} "
      f"{'S1 Opp':>8} {'S1 TX':>7} {'S1 Total':>9} | "
      f"{'S3 Opp':>8} {'S3 TX':>7} {'S3 Total':>9}")
print(f"  {'-'*110}")

for regime in regimes_to_check:
    mask = data["vov_regime"].values == regime
    nd = mask.sum()
    if nd < 10:
        continue

    pct = nd / n * 100
    bh_ann = np.mean(spy_rets[mask]) * 252 * 100

    # S1 decomposed
    s1_gross_ann = np.mean(s1_rets_gross[mask]) * 252 * 100
    s1_tx_ann = np.mean(s1_tx[mask]) * 252 * 100
    s1_opp_cost = bh_ann - s1_gross_ann  # opportunity cost
    s1_direct_cost = s1_tx_ann            # direct cost (always positive)
    s1_total_cost = s1_opp_cost + s1_direct_cost

    # S2 decomposed
    s2_gross_ann = np.mean(s2_rets_gross[mask]) * 252 * 100
    s2_tx_ann = np.mean(s2_tx[mask]) * 252 * 100
    s2_opp_cost = bh_ann - s2_gross_ann
    s2_direct_cost = s2_tx_ann
    s2_total_cost = s2_opp_cost + s2_direct_cost

    # S3 decomposed
    s3_gross_ann = np.mean(s3_rets_gross[mask]) * 252 * 100
    s3_tx_ann = np.mean(s3_tx[mask]) * 252 * 100
    s3_opp_cost = bh_ann - s3_gross_ann
    s3_direct_cost = s3_tx_ann
    s3_total_cost = s3_opp_cost + s3_direct_cost

    regime_insurance[regime] = {
        "n_days": int(nd),
        "pct_time": round(pct, 2),
        "bh_ann_pct": round(bh_ann, 3),
        # S1
        "s1_opportunity_cost": round(s1_opp_cost, 3),
        "s1_direct_cost": round(s1_direct_cost, 3),
        "s1_total_insurance_cost": round(s1_total_cost, 3),
        # S2
        "s2_opportunity_cost": round(s2_opp_cost, 3),
        "s2_direct_cost": round(s2_direct_cost, 3),
        "s2_total_insurance_cost": round(s2_total_cost, 3),
        # S3
        "s3_opportunity_cost": round(s3_opp_cost, 3),
        "s3_direct_cost": round(s3_direct_cost, 3),
        "s3_total_insurance_cost": round(s3_total_cost, 3),
    }

    print(f"  {regime:<20} {nd:>6} {pct:>6.1f}% | {bh_ann:>+8.2f}% "
          f"{s1_opp_cost:>+7.2f}% {s1_direct_cost:>6.3f}% {s1_total_cost:>+8.2f}% | "
          f"{s3_opp_cost:>+7.2f}% {s3_direct_cost:>6.3f}% {s3_total_cost:>+8.2f}%")

# Probability-weighted expected annual insurance cost (decomposed)
print(f"\n  Probability-Weighted Expected Annual Insurance Cost (decomposed):")
print(f"  {'Strategy':<15} {'Opp Cost':>12} {'Direct Cost':>14} {'Total':>10}")
print(f"  {'-'*55}")

insurance_summary = {}
for strat_key, strat_label in [("s1", "S1 Always VT"), ("s2", "S2 VoV-Cond"), ("s3", "S3 Smooth")]:
    total_opp = 0.0
    total_direct = 0.0
    for regime, rd in regime_insurance.items():
        w = rd["pct_time"] / 100
        total_opp += w * rd[f"{strat_key}_opportunity_cost"]
        total_direct += w * rd[f"{strat_key}_direct_cost"]
    total = total_opp + total_direct
    insurance_summary[strat_label] = {
        "opportunity_cost_pct_yr": round(total_opp, 3),
        "direct_cost_pct_yr": round(total_direct, 3),
        "total_cost_pct_yr": round(total, 3),
    }
    print(f"  {strat_label:<15} {total_opp:>+11.3f}% {total_direct:>13.3f}% {total:>+9.3f}%")

RESULTS["insurance_by_regime"] = regime_insurance
RESULTS["insurance_cost_decomposed"] = insurance_summary
RESULTS["bug2_fix"] = "Insurance cost decomposed into opportunity_cost (return gap) + direct_cost (TX)"


# ============================================================
# PART H: VoV Predictive Power for Forward MDD
# ============================================================
print("\n" + "=" * 80)
print("PART H: VoV Predictive Power for Forward 30-Day MDD")
print("-" * 60)

# Forward 30-day max drawdown of SPY
fwd_mdd_30 = np.full(n, np.nan)
for i in range(n - 30):
    fwd_rets = spy_rets[i + 1: i + 31]
    cum = np.exp(np.cumsum(fwd_rets))
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    fwd_mdd_30[i] = np.min(dd) * 100  # negative %

data["fwd_mdd_30"] = fwd_mdd_30

# Correlation: VoV z-score (lagged) vs forward MDD
valid = data.dropna(subset=["vov_zscore_lag", "fwd_mdd_30"])
corr_pearson = valid["vov_zscore_lag"].corr(valid["fwd_mdd_30"])
corr_spearman, sp_pval = stats.spearmanr(valid["vov_zscore_lag"], valid["fwd_mdd_30"])

corr_vix_mdd = valid["vix_lag"].corr(valid["fwd_mdd_30"])
corr_vix_sp, vix_sp_pval = stats.spearmanr(valid["vix_lag"], valid["fwd_mdd_30"])

print(f"\n  VoV z-score -> Forward 30d MDD:")
print(f"    Pearson r:  {corr_pearson:.4f}")
print(f"    Spearman r: {corr_spearman:.4f} (p={sp_pval:.2e})")
print(f"\n  VIX level -> Forward 30d MDD:")
print(f"    Pearson r:  {corr_vix_mdd:.4f}")
print(f"    Spearman r: {corr_vix_sp:.4f} (p={vix_sp_pval:.2e})")

# Quintile analysis
data_sorted = valid.copy()
data_sorted["vov_quintile"] = pd.qcut(data_sorted["vov_zscore_lag"], 5,
                                       labels=False, duplicates="drop")

print(f"\n  VoV Quintile -> Forward 30d MDD (avg):")
print(f"  {'Quintile':>10} {'VoV z-score':>12} {'Fwd 30d MDD':>14} {'Std':>10}")
print(f"  {'-'*50}")

quintile_analysis = {}
for q in range(5):
    q_mask = data_sorted["vov_quintile"] == q
    q_data = data_sorted.loc[q_mask]
    avg_z = q_data["vov_zscore_lag"].mean()
    avg_mdd = q_data["fwd_mdd_30"].mean()
    std_mdd = q_data["fwd_mdd_30"].std()
    q_label = "low" if q == 0 else ("high" if q == 4 else "mid")
    quintile_analysis[f"Q{q + 1}"] = {
        "avg_vov_zscore": round(avg_z, 3),
        "avg_fwd_mdd_30": round(avg_mdd, 3),
        "std_fwd_mdd_30": round(std_mdd, 3),
    }
    print(f"  {'Q'+str(q+1)+' ('+q_label+')':>10} "
          f"{avg_z:>12.3f} {avg_mdd:>13.3f}% {std_mdd:>9.3f}%")

# Monotonicity test
q_mdds = [quintile_analysis[f"Q{q + 1}"]["avg_fwd_mdd_30"] for q in range(5)]
monotone = all(q_mdds[i] >= q_mdds[i + 1] for i in range(4))
print(f"\n  Monotonicity (higher VoV -> worse MDD): {'YES' if monotone else 'NO'}")

RESULTS["vov_predictive_power"] = {
    "vov_to_fwd_mdd_pearson": round(corr_pearson, 4),
    "vov_to_fwd_mdd_spearman": round(corr_spearman, 4),
    "vov_spearman_pval": float(f"{sp_pval:.2e}"),
    "vix_to_fwd_mdd_pearson": round(corr_vix_mdd, 4),
    "vix_to_fwd_mdd_spearman": round(corr_vix_sp, 4),
    "vix_spearman_pval": float(f"{vix_sp_pval:.2e}"),
    "quintile_analysis": quintile_analysis,
    "monotonicity": monotone,
}


# ============================================================
# PART I: Rolling Insurance Cost Analysis (decomposed)
# ============================================================
print("\n" + "=" * 80)
print("PART I: Rolling 2-Year Insurance Cost by Strategy (decomposed)")
print("-" * 60)

window_2yr = 252 * 2
rolling_costs = []

for end_idx in range(window_2yr, n):
    start_idx = end_idx - window_2yr
    bh_mean = np.mean(spy_rets[start_idx:end_idx]) * 252 * 100

    for strat_key, gross_rets, tx_arr in [
        ("s1", s1_rets_gross, s1_tx),
        ("s2", s2_rets_gross, s2_tx),
        ("s3", s3_rets_gross, s3_tx),
    ]:
        gross_mean = np.mean(gross_rets[start_idx:end_idx]) * 252 * 100
        tx_mean = np.mean(tx_arr[start_idx:end_idx]) * 252 * 100
        opp = bh_mean - gross_mean
        direct = tx_mean
        total = opp + direct

        if strat_key == "s1":
            row = {"date": data.index[end_idx].strftime("%Y-%m-%d")}
        row[f"{strat_key}_opp_cost"] = opp
        row[f"{strat_key}_direct_cost"] = direct
        row[f"{strat_key}_total_cost"] = total

    rolling_costs.append(row)

rdf = pd.DataFrame(rolling_costs)

print(f"\n  Rolling 2-year insurance cost statistics (decomposed):")
print(f"  {'Strategy':<15} {'Opp Mean':>10} {'TX Mean':>10} {'Total Mean':>12} "
      f"{'Total Std':>11} {'%Free':>8}")
print(f"  {'-'*70}")

rolling_cost_stats = {}
for sk, label in [("s1", "S1 Always VT"), ("s2", "S2 VoV-Cond"), ("s3", "S3 Smooth")]:
    opp_s = rdf[f"{sk}_opp_cost"]
    tx_s = rdf[f"{sk}_direct_cost"]
    total_s = rdf[f"{sk}_total_cost"]
    rolling_cost_stats[label] = {
        "opp_cost_mean": round(opp_s.mean(), 3),
        "direct_cost_mean": round(tx_s.mean(), 3),
        "total_mean": round(total_s.mean(), 3),
        "total_median": round(total_s.median(), 3),
        "total_std": round(total_s.std(), 3),
        "total_min": round(total_s.min(), 3),
        "total_max": round(total_s.max(), 3),
        "pct_free": round((total_s < 0).mean() * 100, 1),
    }
    print(f"  {label:<15} {opp_s.mean():>+9.2f}% {tx_s.mean():>9.3f}% "
          f"{total_s.mean():>+11.2f}% {total_s.std():>10.2f}% "
          f"{(total_s < 0).mean()*100:>7.1f}%")

RESULTS["rolling_2yr_insurance_cost"] = rolling_cost_stats


# ============================================================
# PART J: Cross-OOS Validation (4 non-overlapping 2-year periods)
# ============================================================
print("\n" + "=" * 80)
print("PART J: Cross-OOS Validation (4 periods, 2012-2024)")
print("-" * 60)

# BUG 1 FIX: adjusted periods -- no pre-2012 data
oos_periods = [
    ("2013-01-01", "2014-12-31"),
    ("2015-01-01", "2016-12-31"),
    ("2019-01-01", "2020-12-31"),
    ("2023-01-01", "2024-12-31"),
]

cross_oos = {}
print(f"\n  {'Period':<22} {'S0 Sharpe':>10} {'S1 Sharpe':>10} {'S2 Sharpe':>10} "
      f"{'S3 Sharpe':>10} {'S4 Sharpe':>10} {'S3 beats S0':>12}")
print(f"  {'-'*85}")

s2_wins_s0 = 0
s3_wins_s0 = 0

for period_start, period_end in oos_periods:
    p_mask = (data.index >= period_start) & (data.index <= period_end)
    p_n = p_mask.sum()
    if p_n < 100:
        continue

    p_years = p_n / 252
    p_metrics = {}
    for name, rets_arr in strategies.items():
        m = compute_metrics(rets_arr[p_mask], name, years=p_years)
        p_metrics[name] = m

    period_label = f"{period_start}~{period_end}"
    s2_better = p_metrics["S2_VoV_Conditional"]["sharpe"] > p_metrics["S0_BH_SPY"]["sharpe"]
    s3_better = p_metrics["S3_Smooth_VoV"]["sharpe"] > p_metrics["S0_BH_SPY"]["sharpe"]
    if s2_better:
        s2_wins_s0 += 1
    if s3_better:
        s3_wins_s0 += 1

    cross_oos[period_label] = {name: m["sharpe"] for name, m in p_metrics.items()}

    print(f"  {period_label:<22} {p_metrics['S0_BH_SPY']['sharpe']:>10.4f} "
          f"{p_metrics['S1_Always_12VIX']['sharpe']:>10.4f} "
          f"{p_metrics['S2_VoV_Conditional']['sharpe']:>10.4f} "
          f"{p_metrics['S3_Smooth_VoV']['sharpe']:>10.4f} "
          f"{p_metrics['S4_5050_SPY_GLD']['sharpe']:>10.4f} "
          f"{'YES' if s3_better else 'NO':>12}")

print(f"\n  S2 beats S0: {s2_wins_s0}/4 periods")
print(f"  S3 beats S0: {s3_wins_s0}/4 periods")

RESULTS["cross_oos"] = {
    "periods": cross_oos,
    "n_periods": 4,
    "s2_wins_s0": s2_wins_s0,
    "s3_wins_s0": s3_wins_s0,
    "note": "4 periods (not 5) since backtest starts 2012, not 2006",
}


# ============================================================
# PART K: Weight Distribution & Turnover
# ============================================================
print("\n" + "=" * 80)
print("PART K: Weight Distribution & Turnover")
print("-" * 60)

weight_stats = {}
for name, weights in [("S1_Always_12VIX", s1_weights),
                       ("S2_VoV_Conditional", s2_weights),
                       ("S3_Smooth_VoV", s3_weights)]:
    avg_w = np.mean(weights)
    std_w = np.std(weights)
    pct_full = (weights >= 0.99).mean() * 100
    pct_half = (weights <= 0.50).mean() * 100
    turnover = np.mean(np.abs(np.diff(weights))) * 252 * 100

    weight_stats[name] = {
        "avg_weight_pct": round(avg_w * 100, 2),
        "std_weight_pct": round(std_w * 100, 2),
        "pct_fully_invested": round(pct_full, 1),
        "pct_half_or_less": round(pct_half, 1),
        "annualized_turnover_pct": round(turnover, 2),
    }

    print(f"  {name}:")
    print(f"    Avg equity weight: {avg_w * 100:.1f}% (std={std_w * 100:.1f}%)")
    print(f"    Fully invested (>99%): {pct_full:.1f}% of days")
    print(f"    Half or less: {pct_half:.1f}% of days")
    print(f"    Ann. turnover: {turnover:.1f}%")

RESULTS["weight_stats"] = weight_stats


# ============================================================
# PART L: Comparison with K811 Original
# ============================================================
print("\n" + "=" * 80)
print("PART L: K811v2 vs K811 Original Comparison")
print("-" * 60)

# Load K811 original results for comparison
k811_path = PROJECT / "experiments" / "k811_insurance_premium_vov_results.json"
k811_comparison = {}

if k811_path.exists():
    with open(k811_path) as f:
        k811_orig = json.load(f)

    print(f"\n  K811 original: {k811_orig['data']['backtest_start']} to {k811_orig['data']['backtest_end']}")
    print(f"  K811v2 fixed:  {RESULTS['data']['backtest_start']} to {RESULTS['data']['backtest_end']}")
    print(f"  K811 original: {k811_orig['data']['n_days']} days, VoV source: {k811_orig['data']['vov_source']}")
    print(f"  K811v2 fixed:  {RESULTS['data']['n_days']} days, VoV source: {RESULTS['data']['vov_source']}")

    print(f"\n  Sharpe Comparison (full period):")
    print(f"  {'Strategy':<25} {'K811 Sharpe':>12} {'K811v2 Sharpe':>14} {'Delta':>8}")
    print(f"  {'-'*65}")

    for strat in ["S0_BH_SPY", "S1_Always_12VIX", "S2_VoV_Conditional", "S3_Smooth_VoV", "S4_5050_SPY_GLD"]:
        s_old = k811_orig.get("full_period_metrics", {}).get(strat, {}).get("sharpe", float("nan"))
        s_new = all_metrics[strat]["sharpe"]
        delta = s_new - s_old if not np.isnan(s_old) else float("nan")
        k811_comparison[strat] = {
            "k811_sharpe": s_old,
            "k811v2_sharpe": s_new,
            "delta": round(delta, 4) if not np.isnan(delta) else None,
        }
        print(f"  {strat:<25} {s_old:>12.4f} {s_new:>14.4f} {delta:>+7.4f}")

    # Compare insurance costs
    if "insurance_cost_summary" in k811_orig:
        print(f"\n  Insurance Cost Comparison (annual %):")
        print(f"  {'Strategy':<15} {'K811 Total':>12} {'K811v2 Opp':>12} {'K811v2 TX':>10} {'K811v2 Total':>14}")
        print(f"  {'-'*70}")
        old_costs = k811_orig["insurance_cost_summary"]
        for old_key, new_key in [("S1_always_vt", "S1 Always VT"),
                                  ("S2_vov_conditional", "S2 VoV-Cond"),
                                  ("S3_smooth_vov", "S3 Smooth")]:
            old_val = old_costs.get(old_key, float("nan"))
            new_data = insurance_summary.get(new_key, {})
            new_opp = new_data.get("opportunity_cost_pct_yr", float("nan"))
            new_tx = new_data.get("direct_cost_pct_yr", float("nan"))
            new_total = new_data.get("total_cost_pct_yr", float("nan"))
            print(f"  {new_key:<15} {old_val:>+11.3f}% {new_opp:>+11.3f}% "
                  f"{new_tx:>9.3f}% {new_total:>+13.3f}%")

    RESULTS["k811_comparison"] = k811_comparison
else:
    print("  K811 original results not found -- skipping comparison")


# ============================================================
# PART M: Key Findings & Conclusions
# ============================================================
print("\n" + "=" * 80)
print("KEY FINDINGS & CONCLUSIONS (K811v2 -- Bug-Fixed)")
print("=" * 80)

s0_sharpe = all_metrics["S0_BH_SPY"]["sharpe"]
s1_sharpe = all_metrics["S1_Always_12VIX"]["sharpe"]
s2_sharpe = all_metrics["S2_VoV_Conditional"]["sharpe"]
s3_sharpe = all_metrics["S3_Smooth_VoV"]["sharpe"]
s4_sharpe = all_metrics["S4_5050_SPY_GLD"]["sharpe"]

s0_mdd = all_metrics["S0_BH_SPY"]["mdd"]
s1_mdd = all_metrics["S1_Always_12VIX"]["mdd"]
s2_mdd = all_metrics["S2_VoV_Conditional"]["mdd"]
s3_mdd = all_metrics["S3_Smooth_VoV"]["mdd"]

s1_total = insurance_summary["S1 Always VT"]["total_cost_pct_yr"]
s2_total = insurance_summary["S2 VoV-Cond"]["total_cost_pct_yr"]
s3_total = insurance_summary["S3 Smooth"]["total_cost_pct_yr"]

s1_opp = insurance_summary["S1 Always VT"]["opportunity_cost_pct_yr"]
s1_tx = insurance_summary["S1 Always VT"]["direct_cost_pct_yr"]
s3_opp = insurance_summary["S3 Smooth"]["opportunity_cost_pct_yr"]
s3_tx_cost = insurance_summary["S3 Smooth"]["direct_cost_pct_yr"]

# Cost reduction vs always-VT
if abs(s1_total) > 0.001:
    s2_cost_reduction = (1 - s2_total / s1_total) * 100
    s3_cost_reduction = (1 - s3_total / s1_total) * 100
else:
    s2_cost_reduction = None
    s3_cost_reduction = None

print(f"""
  BUG FIXES APPLIED:
  1. VVIX data: 2012-2024 only (no pre-2012 unreliable data, no proxy)
  2. Insurance cost: decomposed into opportunity cost + direct (TX) cost

  PERFORMANCE (2012-2024):
  {'Strategy':<25} {'Sharpe':>8} {'MDD':>8} {'CAGR':>8}
  {'-'*55}
  {'S0 BH SPY':<25} {s0_sharpe:>8.4f} {s0_mdd:>7.2f}% {all_metrics['S0_BH_SPY']['cagr']:>7.2f}%
  {'S1 Always 12/VIX':<25} {s1_sharpe:>8.4f} {s1_mdd:>7.2f}% {all_metrics['S1_Always_12VIX']['cagr']:>7.2f}%
  {'S2 VoV-Conditional':<25} {s2_sharpe:>8.4f} {s2_mdd:>7.2f}% {all_metrics['S2_VoV_Conditional']['cagr']:>7.2f}%
  {'S3 Smooth VoV':<25} {s3_sharpe:>8.4f} {s3_mdd:>7.2f}% {all_metrics['S3_Smooth_VoV']['cagr']:>7.2f}%
  {'S4 50/50 SPY/GLD':<25} {s4_sharpe:>8.4f} {all_metrics['S4_5050_SPY_GLD']['mdd']:>7.2f}% {all_metrics['S4_5050_SPY_GLD']['cagr']:>7.2f}%

  INSURANCE COST DECOMPOSITION (BUG 2 FIX):
  {'Strategy':<15} {'Opportunity':>12} {'Direct (TX)':>14} {'Total':>10}
  {'-'*55}
  {'S1 Always VT':<15} {s1_opp:>+11.3f}% {s1_tx:>13.3f}% {s1_total:>+9.3f}%
  {'S2 VoV-Cond':<15} {insurance_summary['S2 VoV-Cond']['opportunity_cost_pct_yr']:>+11.3f}% {insurance_summary['S2 VoV-Cond']['direct_cost_pct_yr']:>13.3f}% {s2_total:>+9.3f}%
  {'S3 Smooth':<15} {s3_opp:>+11.3f}% {s3_tx_cost:>13.3f}% {s3_total:>+9.3f}%

  COST REDUCTION vs S1 (Always VT):
    S2: {f'{s2_cost_reduction:.1f}%' if s2_cost_reduction else 'N/A'} reduction
    S3: {f'{s3_cost_reduction:.1f}%' if s3_cost_reduction else 'N/A'} reduction

  VoV PREDICTIVE POWER:
    VoV z-score -> forward 30d MDD: Spearman r = {corr_spearman:.4f} (p={sp_pval:.2e})
    VIX level -> forward 30d MDD:   Spearman r = {corr_vix_sp:.4f} (p={vix_sp_pval:.2e})
    Monotonicity: {'YES' if monotone else 'NO'}

  CROSS-OOS STABILITY (4 periods, 2012-2024):
    S2 beats BH SPY: {s2_wins_s0}/4 periods
    S3 beats BH SPY: {s3_wins_s0}/4 periods

  KEY INSIGHT:
    After fixing VVIX data period and decomposing costs, the core
    conclusion is testable: VoV conditioning can reduce the opportunity
    cost of insurance (lower equity exposure) but adds direct cost from
    turnover. The net benefit depends on which component dominates.
""")


# ============================================================
# Save results
# ============================================================
RESULTS["experiment"] = "K811v2"
RESULTS["title"] = "Convexity-Adjusted Insurance Premium -- VoV-Conditional VT (Bug-Fixed)"
RESULTS["proposed_by"] = "Gemini #2 (original K811)"
RESULTS["executed_by"] = "Claude (K811v2 fix)"
RESULTS["data_source"] = "yfinance (SPY, GLD, ^VIX, ^VVIX daily)"
RESULTS["period"] = "2012-01-01 ~ 2024-12-31 (VVIX reliable era)"
RESULTS["bugs_fixed"] = [
    {
        "bug_id": 1,
        "severity": "HIGH",
        "description": "VVIX pre-2012 data unreliable (low liquidity)",
        "fix": "Restricted backtest to 2012-2024; inner join requires real VVIX; no proxy/fallback",
    },
    {
        "bug_id": 2,
        "severity": "HIGH",
        "description": "Insurance cost mislabel -- conflated opportunity cost and direct TX cost",
        "fix": "Decomposed into opportunity_cost (BH - strategy_gross) and direct_cost (TX)",
    },
]
RESULTS["methodology"] = {
    "vov_proxy": "VVIX (real data only, no proxy)",
    "vov_zscore": "Expanding window z-score (min 60 days)",
    "vov_regime_threshold": "z > 1.0 = High VoV",
    "vix_direction": "5-day VIX change",
    "lag": "All signals shifted by 1 day (signal.shift(1))",
    "tx_cost": "5 bps per unit weight change",
    "vt_target": "12/VIX",
    "cost_decomposition": "opportunity_cost = BH_ret - strategy_ret_before_TX; direct_cost = TX",
}
RESULTS["references"] = [
    "K811: Original VoV-conditional VT (had 2 HIGH bugs)",
    "K41: VT = ~4%/yr constant insurance",
    "K229: VT Insurance Pricing -- 3.05%/yr expected cost",
    "K687: No VT beats BH 50/50 on Sharpe after correct lag",
    "K688: VT wins under CRRA utility gamma >= 5",
    "Huang & Shaliastovich (2015) Vol-of-Vol Risk",
    "Harvey, Liu, Zhu (2016) t>3.0 threshold",
]
RESULTS["insurance_cost_summary"] = insurance_summary

output_path = Path(__file__).parent / f"k811v2_th{str(VOV_THRESHOLD).replace(".","_")}_results.json"
with open(output_path, "w") as f:
    json.dump(RESULTS, f, indent=2, default=str, ensure_ascii=False)

print(f"\nResults saved to: {output_path}")
print(f"\n{'='*80}")
print("K811v2 EXPERIMENT COMPLETE")
print(f"{'='*80}")
