#!/usr/bin/env python3
"""
K811: Convexity-Adjusted Insurance Premium — VoV-Conditional VT
================================================================
[提出: Gemini #2, 執行: Claude]

Research Question:
  VT's core issue is carry cost (~4%/yr, K41/K229). Can Vol-of-Vol (VoV)
  clustering tell us when insurance is over-priced, enabling strategic
  under-hedging that reduces carry while preserving crisis protection?

Hypothesis:
  - High VoV + Rising VIX = storm approaching, insurance most valuable
  - High VoV + Falling VIX = VoV-decay, insurance over-priced
  - Low VoV + Any VIX = calm markets, insurance just drags returns

Strategies:
  S0: BH SPY (baseline)
  S1: Always 12/VIX (always insured)
  S2: VoV-Conditional — buy insurance only when High VoV + Rising VIX
  S3: Smooth VoV — insurance_weight = clip(VoV_zscore, 0, 1) * (12/VIX)
  S4: 50/50 SPY/GLD (comparison benchmark)

Constraints:
  - signal.shift(1) — all signals lagged, no lookahead
  - TX cost 5 bps per unit weight change
  - Expanding window for VoV z-score computation
  - VVIX as primary VoV proxy; fallback: VIX 20d rolling std

Evaluation:
  - Sharpe, CAGR, MDD, Calmar, CRRA utility gamma=5
  - DM test vs S0 and S1 (Harvey t>3.0)
  - Insurance cost in different VoV regimes
  - VoV predictive power for forward 30-day MDD

Data: SPY, GLD, ^VIX, ^VVIX from yfinance (2006-2026)
OOS: 2023-01-01 ~ 2024-12-31

References:
  - K41: VT = constant ~4%/yr insurance at all horizons
  - K229: VT Insurance Pricing — 3.05%/yr expected cost
  - K687: No VT strategy beats BH 50/50 on Sharpe after correct lag
  - K688: VT wins under CRRA utility gamma >= 5
  - Harvey, Liu, Zhu (2016) t>3.0 threshold
  - Huang & Shaliastovich (2015) "Volatility-of-Volatility Risk"
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
print("K811: Convexity-Adjusted Insurance Premium — VoV-Conditional VT")
print("[提出: Gemini #2, 執行: Claude]")
print("=" * 80)
print("\nPART A: Data Download & Descriptive Statistics")
print("-" * 60)

import yfinance as yf

# Download data
tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX", "VVIX": "^VVIX"}
raw = {}

for name, ticker in tickers.items():
    df = yf.download(ticker, start="2004-01-01", end="2026-06-01",
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df[["Close"]].rename(columns={"Close": name.lower()})
    print(f"  {name}: {len(df)} days ({df.index[0].date()} to {df.index[-1].date()})")

# Merge SPY, GLD, VIX first (longer history)
data = raw["SPY"].join(raw["GLD"], how="inner") \
                 .join(raw["VIX"], how="inner")
data = data.dropna()

# Check VVIX availability
vvix_available = len(raw["VVIX"]) > 100
if vvix_available:
    data = data.join(raw["VVIX"], how="left")
    # VVIX starts ~2007, fill NaN with VIX rolling std proxy
    vvix_missing = data["vvix"].isna().sum()
    print(f"\n  VVIX: {len(raw['VVIX'])} days, {vvix_missing} missing after merge")
else:
    print("\n  VVIX not available — using VIX rolling std as proxy")

# Compute returns
data["spy_ret"] = np.log(data["spy"] / data["spy"].shift(1))
data["gld_ret"] = np.log(data["gld"] / data["gld"].shift(1))

# VoV proxy: prefer VVIX, fallback to VIX 20d rolling std
data["vix_rolling_std"] = data["vix"].rolling(20).std()

if vvix_available and "vvix" in data.columns:
    # Use VVIX where available, else VIX rolling std scaled to VVIX-like range
    # Scale factor: median(VVIX) / median(vix_rolling_std) in overlap period
    overlap = data.dropna(subset=["vvix", "vix_rolling_std"])
    if len(overlap) > 100:
        scale = overlap["vvix"].median() / overlap["vix_rolling_std"].median()
    else:
        scale = 10.0  # rough default
    data["vov"] = data["vvix"].fillna(data["vix_rolling_std"] * scale)
    vov_source = "VVIX (# scaled VIX rolling std)"
else:
    data["vov"] = data["vix_rolling_std"] * 10.0  # scale to VVIX-like magnitude
    vov_source = "VIX 20d rolling std (scaled)"

# VIX direction: 5-day change
data["vix_chg_5d"] = data["vix"] - data["vix"].shift(5)
data["vix_rising"] = (data["vix_chg_5d"] > 0).astype(int)

# Drop NaN rows
data = data.dropna(subset=["spy_ret", "gld_ret", "vov", "vix_rising"])

# Trim to backtest period (start from 2006 for enough VoV history)
BACKTEST_START = "2006-01-03"
BACKTEST_END = "2026-03-31"
data = data.loc[BACKTEST_START:BACKTEST_END]

n = len(data)
n_years = n / 252
print(f"\n  Backtest: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Trading days: {n}, Years: {n_years:.1f}")
print(f"  VoV source: {vov_source}")

# Descriptive statistics
print(f"\n  Descriptive Statistics:")
print(f"  {'':20s} {'Mean':>10} {'Std':>10} {'Skew':>8} {'Kurt':>8} {'Min':>10} {'Max':>10}")
print(f"  {'-'*70}")
for col, label in [("vix", "VIX"), ("vov", "VoV (VVIX/proxy)"),
                   ("spy_ret", "SPY daily ret"), ("gld_ret", "GLD daily ret")]:
    s = data[col]
    print(f"  {label:20s} {s.mean():>10.4f} {s.std():>10.4f} {s.skew():>8.2f} "
          f"{s.kurtosis():>8.2f} {s.min():>10.4f} {s.max():>10.4f}")

RESULTS["data"] = {
    "backtest_start": str(data.index[0].date()),
    "backtest_end": str(data.index[-1].date()),
    "n_days": int(n),
    "n_years": round(n_years, 2),
    "vov_source": vov_source,
    "vvix_available": vvix_available,
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

    high_vov = vov_z > 1.0  # VoV above 1 sigma

    if high_vov and vix_rising:
        return "HighVoV_Rising"    # Storm approaching — insure!
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


def compute_metrics(daily_rets, label=""):
    """Compute standard performance metrics."""
    rets = np.array(daily_rets, dtype=np.float64)
    cum = np.exp(np.nancumsum(rets))
    total_ret = cum[-1] / cum[0] if cum[0] > 0 else 1.0
    cagr = total_ret ** (1 / n_years) - 1
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
    # Use simple returns for CRRA
    simple_rets = np.exp(rets) - 1
    wealth = np.cumprod(1 + simple_rets)
    if gamma == 1:
        crra = np.mean(np.log(np.maximum(wealth, 1e-10)))
    else:
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
    """Apply transaction cost proportional to weight changes."""
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
s0_rets = spy_rets.copy()

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
# High VoV + Rising VIX → 12/VIX insurance; otherwise → BH SPY (weight=1)
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
# When vov_z <= 0: weight = 1 (no insurance)
# When vov_z >= 1: weight = 12/VIX (full insurance)
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
print("PART D: Full-Period Performance")
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
# PART E: OOS Performance (2023-2025)
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

# Need separate n_years for OOS metrics
_saved_n_years = n_years
n_years = oos_years
for name, rets in oos_strategies.items():
    m = compute_metrics(rets, name + "_OOS")
    oos_metrics[name] = m
    print(f"  {name:<25} {m['cagr']:>7.2f}% {m['ann_vol']:>7.2f}% {m['sharpe']:>8.4f} "
          f"{m['mdd']:>7.2f}% {m['calmar']:>8.4f} {m['crra_gamma5']:>10.6f}")
n_years = _saved_n_years

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
        # HAC variance (Newey-West, bandwidth h)
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
    # Negative t → strategy A is better (lower loss = higher return)

RESULTS["dm_tests"] = dm_results


# ============================================================
# PART G: Insurance Cost by VoV Regime
# ============================================================
print("\n" + "=" * 80)
print("PART G: Insurance Cost by VoV Regime")
print("-" * 60)

print(f"\n  Insurance cost = CAGR(BH SPY) - CAGR(strategy) within each regime")
print(f"  Positive = strategy costs you return relative to BH\n")

regime_insurance = {}
regimes_to_check = ["HighVoV_Rising", "HighVoV_Falling", "LowVoV_Rising", "LowVoV_Falling"]

print(f"  {'Regime':<20} {'Days':>6} {'%':>7} {'BH Ann%':>9} {'S1 Ann%':>9} "
      f"{'S2 Ann%':>9} {'S3 Ann%':>9} {'S1 Cost':>9} {'S2 Cost':>9} {'S3 Cost':>9}")
print(f"  {'-'*100}")

for regime in regimes_to_check:
    mask = data["vov_regime"].values == regime
    nd = mask.sum()
    if nd < 10:
        continue

    pct = nd / n * 100
    bh_ann = np.mean(spy_rets[mask]) * 252 * 100
    s1_ann = np.mean(s1_rets[mask]) * 252 * 100
    s2_ann = np.mean(s2_rets[mask]) * 252 * 100
    s3_ann = np.mean(s3_rets[mask]) * 252 * 100

    s1_cost = bh_ann - s1_ann
    s2_cost = bh_ann - s2_ann
    s3_cost = bh_ann - s3_ann

    regime_insurance[regime] = {
        "n_days": int(nd),
        "pct_time": round(pct, 2),
        "bh_ann_pct": round(bh_ann, 3),
        "s1_ann_pct": round(s1_ann, 3),
        "s2_ann_pct": round(s2_ann, 3),
        "s3_ann_pct": round(s3_ann, 3),
        "s1_insurance_cost": round(s1_cost, 3),
        "s2_insurance_cost": round(s2_cost, 3),
        "s3_insurance_cost": round(s3_cost, 3),
    }

    print(f"  {regime:<20} {nd:>6} {pct:>6.1f}% {bh_ann:>+8.2f}% {s1_ann:>+8.2f}% "
          f"{s2_ann:>+8.2f}% {s3_ann:>+8.2f}% {s1_cost:>+8.2f}% {s2_cost:>+8.2f}% {s3_cost:>+8.2f}%")

# Expected annual cost weighted by regime probability
print(f"\n  Probability-Weighted Expected Annual Insurance Cost:")
for strat_key in ["s1_insurance_cost", "s2_insurance_cost", "s3_insurance_cost"]:
    total = 0.0
    for regime, rd in regime_insurance.items():
        total += (rd["pct_time"] / 100) * rd[strat_key]
    strat_label = strat_key.replace("_insurance_cost", "").upper()
    print(f"    {strat_label}: {total:+.3f}%/yr")

RESULTS["insurance_by_regime"] = regime_insurance


# ============================================================
# PART H: VoV Predictive Power for Forward MDD
# ============================================================
print("\n" + "=" * 80)
print("PART H: VoV Predictive Power for Forward 30-Day MDD")
print("-" * 60)

# For each day, compute forward 30-day max drawdown of SPY
fwd_mdd_30 = np.full(n, np.nan)
for i in range(n - 30):
    fwd_rets = spy_rets[i + 1: i + 31]
    cum = np.exp(np.cumsum(fwd_rets))
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    fwd_mdd_30[i] = np.min(dd) * 100  # negative %

data["fwd_mdd_30"] = fwd_mdd_30

# Correlation between VoV z-score (lagged) and forward MDD
valid = data.dropna(subset=["vov_zscore_lag", "fwd_mdd_30"])
corr_pearson = valid["vov_zscore_lag"].corr(valid["fwd_mdd_30"])
corr_spearman, sp_pval = stats.spearmanr(valid["vov_zscore_lag"], valid["fwd_mdd_30"])

# Also check VIX prediction of forward MDD
corr_vix_mdd = valid["vix_lag"].corr(valid["fwd_mdd_30"])
corr_vix_sp, vix_sp_pval = stats.spearmanr(valid["vix_lag"], valid["fwd_mdd_30"])

print(f"\n  VoV z-score → Forward 30d MDD:")
print(f"    Pearson r:  {corr_pearson:.4f}")
print(f"    Spearman r: {corr_spearman:.4f} (p={sp_pval:.2e})")
print(f"\n  VIX level → Forward 30d MDD:")
print(f"    Pearson r:  {corr_vix_mdd:.4f}")
print(f"    Spearman r: {corr_vix_sp:.4f} (p={vix_sp_pval:.2e})")

# Quintile analysis: sort by VoV z-score, check forward MDD
data_sorted = valid.copy()
data_sorted["vov_quintile"] = pd.qcut(data_sorted["vov_zscore_lag"], 5, labels=False, duplicates="drop")

print(f"\n  VoV Quintile → Forward 30d MDD (avg):")
print(f"  {'Quintile':>10} {'VoV z-score':>12} {'Fwd 30d MDD':>14} {'Fwd 30d MDD Std':>16}")
print(f"  {'-'*55}")

quintile_analysis = {}
for q in range(5):
    q_mask = data_sorted["vov_quintile"] == q
    q_data = data_sorted.loc[q_mask]
    avg_z = q_data["vov_zscore_lag"].mean()
    avg_mdd = q_data["fwd_mdd_30"].mean()
    std_mdd = q_data["fwd_mdd_30"].std()
    quintile_analysis[f"Q{q + 1}"] = {
        "avg_vov_zscore": round(avg_z, 3),
        "avg_fwd_mdd_30": round(avg_mdd, 3),
        "std_fwd_mdd_30": round(std_mdd, 3),
    }
    print(f"  {f'Q{q+1} ({"low" if q == 0 else "high" if q == 4 else "mid"})':>10} "
          f"{avg_z:>12.3f} {avg_mdd:>13.3f}% {std_mdd:>15.3f}%")

# Monotonicity test (does higher VoV → worse MDD?)
q_mdds = [quintile_analysis[f"Q{q + 1}"]["avg_fwd_mdd_30"] for q in range(5)]
monotone = all(q_mdds[i] >= q_mdds[i + 1] for i in range(4))  # MDD is negative, so "worse" = more negative
print(f"\n  Monotonicity (higher VoV → worse MDD): {'YES' if monotone else 'NO'}")

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
# PART I: Rolling Insurance Cost Analysis
# ============================================================
print("\n" + "=" * 80)
print("PART I: Rolling 2-Year Insurance Cost by Strategy")
print("-" * 60)

window_2yr = 252 * 2
rolling_costs = []

for end_idx in range(window_2yr, n):
    start_idx = end_idx - window_2yr
    bh_mean = np.mean(spy_rets[start_idx:end_idx]) * 252 * 100
    s1_mean = np.mean(s1_rets[start_idx:end_idx]) * 252 * 100
    s2_mean = np.mean(s2_rets[start_idx:end_idx]) * 252 * 100
    s3_mean = np.mean(s3_rets[start_idx:end_idx]) * 252 * 100

    rolling_costs.append({
        "date": data.index[end_idx].strftime("%Y-%m-%d"),
        "s1_cost": bh_mean - s1_mean,
        "s2_cost": bh_mean - s2_mean,
        "s3_cost": bh_mean - s3_mean,
    })

rdf = pd.DataFrame(rolling_costs)

print(f"\n  Rolling 2-year insurance cost statistics:")
print(f"  {'Strategy':<15} {'Mean':>9} {'Median':>9} {'Std':>9} {'Min':>9} {'Max':>9} {'%Free':>8}")
print(f"  {'-'*65}")

rolling_cost_stats = {}
for col, label in [("s1_cost", "S1 Always VT"), ("s2_cost", "S2 VoV-Cond"), ("s3_cost", "S3 Smooth")]:
    s = rdf[col]
    rolling_cost_stats[label] = {
        "mean": round(s.mean(), 3),
        "median": round(s.median(), 3),
        "std": round(s.std(), 3),
        "min": round(s.min(), 3),
        "max": round(s.max(), 3),
        "pct_free": round((s < 0).mean() * 100, 1),
    }
    print(f"  {label:<15} {s.mean():>+8.2f}% {s.median():>+8.2f}% {s.std():>8.2f}% "
          f"{s.min():>+8.2f}% {s.max():>+8.2f}% {(s < 0).mean()*100:>7.1f}%")

RESULTS["rolling_2yr_insurance_cost"] = rolling_cost_stats


# ============================================================
# PART J: Cross-OOS Validation (5 non-overlapping 2-year periods)
# ============================================================
print("\n" + "=" * 80)
print("PART J: Cross-OOS Validation (5 periods)")
print("-" * 60)

oos_periods = [
    ("2007-01-01", "2008-12-31"),
    ("2011-01-01", "2012-12-31"),
    ("2015-01-01", "2016-12-31"),
    ("2019-01-01", "2020-12-31"),
    ("2023-01-01", "2024-12-31"),
]

cross_oos = {}
print(f"\n  {'Period':<22} {'S0 Sharpe':>10} {'S1 Sharpe':>10} {'S2 Sharpe':>10} "
      f"{'S3 Sharpe':>10} {'S4 Sharpe':>10} {'S2 beats S0':>12}")
print(f"  {'-'*85}")

s2_wins_s0 = 0
s3_wins_s0 = 0

for period_start, period_end in oos_periods:
    p_mask = (data.index >= period_start) & (data.index <= period_end)
    p_n = p_mask.sum()
    if p_n < 100:
        continue

    _saved = n_years
    n_years = p_n / 252

    p_metrics = {}
    for name, rets_arr in strategies.items():
        m = compute_metrics(rets_arr[p_mask], name)
        p_metrics[name] = m

    n_years = _saved

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
          f"{'YES' if s2_better else 'NO':>12}")

print(f"\n  S2 beats S0: {s2_wins_s0}/5 periods")
print(f"  S3 beats S0: {s3_wins_s0}/5 periods")

RESULTS["cross_oos"] = {
    "periods": cross_oos,
    "s2_wins_s0": s2_wins_s0,
    "s3_wins_s0": s3_wins_s0,
}


# ============================================================
# PART K: Insurance Value Assessment Tool
# ============================================================
print("\n" + "=" * 80)
print("PART K: Insurance Value Assessment (Practical Tool)")
print("-" * 60)

# Current regime assessment (last available data point)
last_row = data.iloc[-1]
last_vov_z = last_row.get("vov_zscore_lag", np.nan)
last_vix = last_row.get("vix_lag", np.nan)
last_regime = last_row.get("vov_regime", "Unknown")
last_date = data.index[-1].strftime("%Y-%m-%d")

print(f"\n  Latest data point: {last_date}")
print(f"  VIX (lagged):    {last_vix:.2f}" if not np.isnan(last_vix) else "  VIX: N/A")
print(f"  VoV z-score:     {last_vov_z:.3f}" if not np.isnan(last_vov_z) else "  VoV z-score: N/A")
print(f"  VoV Regime:      {last_regime}")

# Assessment logic
if last_regime == "HighVoV_Rising":
    assessment = "INSURE — storm approaching, insurance most valuable"
    recommendation = "Use full 12/VIX weight (VT protection ON)"
elif last_regime == "HighVoV_Falling":
    assessment = "REDUCE — VoV-decay, insurance likely over-priced"
    recommendation = "Consider partial or no VT (save carry cost)"
elif last_regime == "LowVoV_Rising":
    assessment = "MONITOR — minor uptick, low urgency"
    recommendation = "Light VT or no VT (cost > benefit in low VoV)"
else:
    assessment = "SKIP — calm markets, insurance just drags returns"
    recommendation = "Stay fully invested, no VT needed"

print(f"  Assessment:      {assessment}")
print(f"  Recommendation:  {recommendation}")

# Historical accuracy: what happened after each regime?
print(f"\n  Historical Forward 30d MDD by regime:")
for regime in regimes_to_check:
    r_mask = (data["vov_regime"] == regime) & data["fwd_mdd_30"].notna()
    if r_mask.sum() < 10:
        continue
    avg_mdd = data.loc[r_mask, "fwd_mdd_30"].mean()
    worst_mdd = data.loc[r_mask, "fwd_mdd_30"].min()
    pct_bad = (data.loc[r_mask, "fwd_mdd_30"] < -5).mean() * 100
    print(f"    {regime:<20}: avg MDD = {avg_mdd:>+7.2f}%, worst = {worst_mdd:>+7.2f}%, "
          f"P(MDD < -5%) = {pct_bad:.1f}%")

RESULTS["current_assessment"] = {
    "date": last_date,
    "vix": round(float(last_vix), 2) if not np.isnan(last_vix) else None,
    "vov_zscore": round(float(last_vov_z), 3) if not np.isnan(last_vov_z) else None,
    "regime": last_regime,
    "assessment": assessment,
    "recommendation": recommendation,
}


# ============================================================
# PART L: Weight Distribution Statistics
# ============================================================
print("\n" + "=" * 80)
print("PART L: Weight Distribution & Turnover")
print("-" * 60)

weight_stats = {}
for name, weights in [("S1_Always_12VIX", s1_weights),
                       ("S2_VoV_Conditional", s2_weights),
                       ("S3_Smooth_VoV", s3_weights)]:
    avg_w = np.mean(weights)
    std_w = np.std(weights)
    pct_full = (weights >= 0.99).mean() * 100
    pct_half = (weights <= 0.50).mean() * 100
    turnover = np.mean(np.abs(np.diff(weights))) * 252 * 100  # annualized turnover in pct

    weight_stats[name] = {
        "avg_weight": round(avg_w * 100, 2),
        "std_weight": round(std_w * 100, 2),
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
# PART M: Key Findings & Conclusions
# ============================================================
print("\n" + "=" * 80)
print("KEY FINDINGS & CONCLUSIONS")
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

s2_cost_reduction = None
s3_cost_reduction = None

# Cost reduction vs always-VT
s1_total_cost = sum((rd["pct_time"] / 100) * rd["s1_insurance_cost"]
                     for rd in regime_insurance.values())
s2_total_cost = sum((rd["pct_time"] / 100) * rd["s2_insurance_cost"]
                     for rd in regime_insurance.values())
s3_total_cost = sum((rd["pct_time"] / 100) * rd["s3_insurance_cost"]
                     for rd in regime_insurance.values())

if abs(s1_total_cost) > 0.001:
    s2_cost_reduction = (1 - s2_total_cost / s1_total_cost) * 100
    s3_cost_reduction = (1 - s3_total_cost / s1_total_cost) * 100

print(f"""
  1. VoV-CONDITIONAL VT (S2) vs ALWAYS VT (S1):
     - S2 Sharpe: {s2_sharpe:.4f} vs S1: {s1_sharpe:.4f}
     - S2 MDD: {s2_mdd:.2f}% vs S1: {s1_mdd:.2f}%
     - S2 insurance cost: {s2_total_cost:+.3f}%/yr vs S1: {s1_total_cost:+.3f}%/yr
     - Cost reduction: {f'{s2_cost_reduction:.1f}%' if s2_cost_reduction else 'N/A'}

  2. SMOOTH VoV (S3) vs ALWAYS VT (S1):
     - S3 Sharpe: {s3_sharpe:.4f} vs S1: {s1_sharpe:.4f}
     - S3 MDD: {s3_mdd:.2f}% vs S1: {s1_mdd:.2f}%
     - S3 insurance cost: {s3_total_cost:+.3f}%/yr vs S1: {s1_total_cost:+.3f}%/yr
     - Cost reduction: {f'{s3_cost_reduction:.1f}%' if s3_cost_reduction else 'N/A'}

  3. VoV PREDICTIVE POWER:
     - VoV z-score → forward 30d MDD: Spearman r = {corr_spearman:.4f} (p={sp_pval:.2e})
     - VIX level → forward 30d MDD:   Spearman r = {corr_vix_sp:.4f} (p={vix_sp_pval:.2e})
     - Monotonicity (higher VoV → worse MDD): {'YES' if monotone else 'NO'}

  4. CROSS-OOS STABILITY:
     - S2 beats BH SPY: {s2_wins_s0}/5 periods
     - S3 beats BH SPY: {s3_wins_s0}/5 periods

  5. INSURANCE VALUE ASSESSMENT:
     - Current regime: {last_regime}
     - Assessment: {assessment}

  6. CORE INSIGHT:
     VoV-conditional VT aims to maintain crisis protection while
     reducing carry cost in low-volatility-of-volatility regimes.
     The key test: does reduced cost come at acceptable MDD cost?
""")


# ============================================================
# Save results
# ============================================================
RESULTS["experiment"] = "K811"
RESULTS["title"] = "Convexity-Adjusted Insurance Premium — VoV-Conditional VT"
RESULTS["proposed_by"] = "Gemini #2"
RESULTS["executed_by"] = "Claude"
RESULTS["data_source"] = "yfinance (SPY, GLD, ^VIX, ^VVIX daily)"
RESULTS["methodology"] = {
    "vov_proxy": vov_source,
    "vov_zscore": "Expanding window z-score (min 60 days)",
    "vov_regime_threshold": "z > 1.0 = High VoV",
    "vix_direction": "5-day VIX change",
    "lag": "All signals shifted by 1 day",
    "tx_cost": "5 bps per unit weight change",
    "vt_target": "12/VIX",
}
RESULTS["references"] = [
    "K41: VT = ~4%/yr constant insurance",
    "K229: VT Insurance Pricing — 3.05%/yr expected cost",
    "K687: No VT beats BH 50/50 on Sharpe after correct lag",
    "K688: VT wins under CRRA utility gamma >= 5",
    "Huang & Shaliastovich (2015) Vol-of-Vol Risk",
    "Harvey, Liu, Zhu (2016) t>3.0 threshold",
]
RESULTS["insurance_cost_summary"] = {
    "S1_always_vt": round(s1_total_cost, 3),
    "S2_vov_conditional": round(s2_total_cost, 3),
    "S3_smooth_vov": round(s3_total_cost, 3),
    "S2_cost_reduction_pct": round(s2_cost_reduction, 1) if s2_cost_reduction else None,
    "S3_cost_reduction_pct": round(s3_cost_reduction, 1) if s3_cost_reduction else None,
}

output_path = PROJECT / "experiments" / "k811_insurance_premium_vov_results.json"
with open(output_path, "w") as f:
    json.dump(RESULTS, f, indent=2, default=str, ensure_ascii=False)

print(f"\nResults saved to: {output_path}")
print(f"\n{'='*80}")
print("K811 EXPERIMENT COMPLETE")
print(f"{'='*80}")
