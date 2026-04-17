"""
Rate-Hike Regime VT Experiment: Does excluding/reducing exposure during rate hikes improve 12/VIX?
==================================================================================================

Hypothesis (S2 monetary anti-signal):
  During rate-hike periods, high VIX/GARCH Z-score predicts NEGATIVE returns (t=-5.0).
  → VT should be MORE conservative during rate hikes.

Strategy variants:
  A. Baseline: 12/VIX always (weight = min(12/VIX, 1.0))
  B. Conservative in hikes: 8/VIX during rate-hike months, 12/VIX otherwise
  C. Cash in hikes: 0% equity during rate-hike months, 12/VIX otherwise
  D. VIX-adjusted: 12/VIX but multiply weight by 0.5 during hikes
  E. Buy-and-hold SPY (benchmark)

Data:
  - SPY, ^VIX, Fed Funds Rate proxy (^IRX 3-month T-bill or FRED)
  - Known FOMC rate hike dates as backup

Monthly rebalance, LAGGED weights, 0.05% TX cost.
Full period: 2010-2025, OOS: 2016-2025.
Harvey t>3 required for significance.

[提出: User (S2 finding), 執行: Claude]
"""

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# Project root
PROJECT_ROOT = Path("/Users/yhlai0911/Desktop/volpred-research")
sys.path.insert(0, str(PROJECT_ROOT / "src"))

# ============================================================
# CONFIG
# ============================================================
START_DATA = "2008-01-01"  # extra lookback
END_DATA = "2026-12-31"
OOS_START = "2016-01-01"
OOS_END = "2025-12-31"
FULL_START = "2010-01-01"
TX_COST = 0.0005  # 0.05% one-way
RF_ANNUAL = 0.02  # conservative risk-free rate
RF_DAILY = RF_ANNUAL / 252

# Known Fed rate hike periods (month starts when FFR was raised)
# Source: Federal Reserve historical data
# 2015-12 to 2018-12: gradual hiking (9 hikes)
# 2022-03 to 2023-07: aggressive hiking (11 hikes)
RATE_HIKE_MONTHS = [
    # 2015-2018 hiking cycle
    "2015-12", "2016-12", "2017-03", "2017-06", "2017-12",
    "2018-03", "2018-06", "2018-09", "2018-12",
    # 2022-2023 hiking cycle
    "2022-03", "2022-05", "2022-06", "2022-07", "2022-09",
    "2022-11", "2022-12", "2023-02", "2023-03", "2023-05", "2023-07",
]

print("=" * 80)
print("RATE-HIKE REGIME VT EXPERIMENT")
print("Does monetary policy awareness improve 12/VIX?")
print("=" * 80)

# ============================================================
# 1. Download Data
# ============================================================
print("\n[1/5] Downloading SPY, VIX, and Fed Funds Rate proxy data...")

spy_raw = yf.download("SPY", start=START_DATA, end=END_DATA, progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start=START_DATA, end=END_DATA, progress=False, auto_adjust=False)

# Also download ^IRX (3-month T-bill rate) as proxy for rate changes
irx_raw = yf.download("^IRX", start=START_DATA, end=END_DATA, progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, vix_raw, irx_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Also download SHY for cash returns
shy_raw = yf.download("SHY", start=START_DATA, end=END_DATA, progress=False, auto_adjust=False)
if isinstance(shy_raw.columns, pd.MultiIndex):
    shy_raw.columns = shy_raw.columns.get_level_values(0)

print(f"  SPY: {len(spy_raw)} days ({spy_raw.index[0].date()} to {spy_raw.index[-1].date()})")
print(f"  VIX: {len(vix_raw)} days")
print(f"  IRX: {len(irx_raw)} days")
print(f"  SHY: {len(shy_raw)} days")

# ============================================================
# 2. Process Data
# ============================================================
print("\n[2/5] Processing data and identifying rate-hike regimes...")

# SPY daily returns
spy = pd.DataFrame(index=spy_raw.index)
spy["close"] = spy_raw["Close"]
spy["ret"] = spy["close"].pct_change()
spy = spy.dropna()

# VIX close
vix = pd.DataFrame(index=vix_raw.index)
vix["close"] = vix_raw["Close"]

# SHY daily returns (cash proxy)
shy = pd.DataFrame(index=shy_raw.index)
shy["close"] = shy_raw["Close"]
shy["ret"] = shy["close"].pct_change()
shy = shy.dropna()

# IRX: 3-month T-bill rate
irx = pd.DataFrame(index=irx_raw.index)
irx["rate"] = irx_raw["Close"]
irx = irx.dropna()

# Identify rate-hike regime from IRX changes
# Method 1: Use known FOMC hike dates
hike_month_set = set(RATE_HIKE_MONTHS)

# Method 2: Also detect from IRX data (rate rising)
# Monthly IRX rate
irx_monthly = irx["rate"].resample("ME").last().dropna()
irx_change = irx_monthly.diff()
# A month is "hiking" if IRX rose by > 0.05% (5 basis points)
irx_hike_months = irx_change[irx_change > 0.05].index

print(f"  Known FOMC hike months: {len(RATE_HIKE_MONTHS)}")
print(f"  IRX-detected rising months: {len(irx_hike_months)}")

# Combine both methods for robustness
# Also define "rate-hike regime" more broadly: the entire period when rates are rising
# We'll use a "regime" flag: 1 if in the past 3 months there was a rate hike
def get_hike_regime(date, lookback_months=3):
    """Check if a date falls within a rate-hike regime (hike in past N months)."""
    ym = date.strftime("%Y-%m")
    if ym in hike_month_set:
        return True
    # Check if any of the previous lookback_months had a hike
    for i in range(1, lookback_months + 1):
        check_date = date - pd.DateOffset(months=i)
        check_ym = check_date.strftime("%Y-%m")
        if check_ym in hike_month_set:
            return True
    return False

# Also define "active hiking period" = from first hike to 3 months after last hike in a cycle
HIKING_PERIODS = [
    ("2015-12-01", "2019-03-31"),  # 2015-2018 cycle + 3 month buffer
    ("2022-03-01", "2023-10-31"),  # 2022-2023 cycle + 3 month buffer
]

def in_hiking_period(date):
    """Check if date falls within a broader hiking period."""
    for start, end in HIKING_PERIODS:
        if pd.Timestamp(start) <= date <= pd.Timestamp(end):
            return True
    return False

# Align all data
common_idx = spy.index.intersection(vix.index).intersection(shy.index)
spy = spy.loc[common_idx]
vix = vix.loc[common_idx]
shy = shy.loc[common_idx]

# Add regime flags
spy["month"] = spy.index.to_period("M")
spy["is_hike_month"] = [date.strftime("%Y-%m") in hike_month_set for date in spy.index]
spy["is_hike_regime"] = [get_hike_regime(date, lookback_months=2) for date in spy.index]
spy["in_hiking_period"] = [in_hiking_period(date) for date in spy.index]
spy["vix"] = vix["close"]
spy["shy_ret"] = shy["ret"]

# Filter to study period
spy = spy.loc[FULL_START:]
print(f"  Study period: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} days)")

n_hike_days = spy["is_hike_month"].sum()
n_period_days = spy["in_hiking_period"].sum()
print(f"  Days with active hike month: {n_hike_days} ({n_hike_days/len(spy)*100:.1f}%)")
print(f"  Days in hiking period: {n_period_days} ({n_period_days/len(spy)*100:.1f}%)")

# ============================================================
# 3. Run Strategy Variants
# ============================================================
print("\n[3/5] Running strategy variants...")

def run_strategy(spy_df, strategy_name, weight_func, rebalance="monthly"):
    """
    Run a VT strategy with monthly rebalance and lagged weights.

    weight_func(vix_level, is_hike_month, in_hiking_period) -> equity weight
    """
    df = spy_df.copy()

    # Monthly rebalance: compute weight at month-end, apply NEXT month
    months = df["month"].unique()

    # Compute monthly weights (lagged)
    month_weights = {}
    for m in months:
        mask = df["month"] == m
        month_data = df.loc[mask]
        if len(month_data) == 0:
            continue
        # Use last day of month's VIX for next month's weight
        vix_last = month_data["vix"].iloc[-1]
        hike = month_data["is_hike_month"].iloc[-1]
        period = month_data["in_hiking_period"].iloc[-1]
        w = weight_func(vix_last, hike, period)
        month_weights[m] = w

    # Apply lagged weights (this month's weight = last month's computed weight)
    sorted_months = sorted(month_weights.keys())
    lagged_weights = {}
    for i, m in enumerate(sorted_months):
        if i == 0:
            lagged_weights[m] = 1.0  # default first month
        else:
            lagged_weights[m] = month_weights[sorted_months[i-1]]

    # Daily returns
    daily_rets = []
    daily_weights = []
    daily_dates = []
    prev_w = None

    for idx, row in df.iterrows():
        m = row["month"]
        w = lagged_weights.get(m, 1.0)

        # Transaction cost on weight change
        tx = 0.0
        if prev_w is not None and abs(w - prev_w) > 0.01:
            tx = TX_COST * abs(w - prev_w)
        prev_w = w

        # Portfolio return: w * SPY + (1-w) * SHY - tx
        spy_r = row["ret"]
        shy_r = row["shy_ret"] if not np.isnan(row["shy_ret"]) else 0.0
        port_ret = w * spy_r + (1 - w) * shy_r - tx

        daily_rets.append(port_ret)
        daily_weights.append(w)
        daily_dates.append(idx)

    result = pd.DataFrame({
        "date": daily_dates,
        "ret": daily_rets,
        "weight": daily_weights,
    }).set_index("date")

    return result

# Strategy A: Baseline 12/VIX
def weight_baseline(vix, hike, period):
    return min(12.0 / max(vix, 1.0), 1.0)

# Strategy B: Conservative in hikes (8/VIX during hike months)
def weight_conservative_hike(vix, hike, period):
    if hike:
        return min(8.0 / max(vix, 1.0), 1.0)
    return min(12.0 / max(vix, 1.0), 1.0)

# Strategy C: Cash during hike months
def weight_cash_hike(vix, hike, period):
    if hike:
        return 0.0
    return min(12.0 / max(vix, 1.0), 1.0)

# Strategy D: 50% weight during hiking period
def weight_half_period(vix, hike, period):
    w = min(12.0 / max(vix, 1.0), 1.0)
    if period:
        w *= 0.5
    return w

# Strategy E: Buy and hold
def weight_buyhold(vix, hike, period):
    return 1.0

# Strategy F: Conservative during hiking PERIOD (not just month)
def weight_conservative_period(vix, hike, period):
    if period:
        return min(8.0 / max(vix, 1.0), 1.0)
    return min(12.0 / max(vix, 1.0), 1.0)

# Strategy G: Cash during hiking PERIOD
def weight_cash_period(vix, hike, period):
    if period:
        return 0.0
    return min(12.0 / max(vix, 1.0), 1.0)

strategies = {
    "A: 12/VIX baseline": weight_baseline,
    "B: 8/VIX in hike months": weight_conservative_hike,
    "C: Cash in hike months": weight_cash_hike,
    "D: 50% in hiking period": weight_half_period,
    "E: Buy-and-hold SPY": weight_buyhold,
    "F: 8/VIX in hiking period": weight_conservative_period,
    "G: Cash in hiking period": weight_cash_period,
}

results = {}
for name, wfunc in strategies.items():
    r = run_strategy(spy, name, wfunc)
    results[name] = r
    avg_w = r["weight"].mean()
    print(f"  {name}: avg weight = {avg_w:.3f}")

# ============================================================
# 4. Compute Metrics
# ============================================================
print("\n[4/5] Computing performance metrics...")

def compute_metrics(df_ret, name, rf_daily=RF_DAILY):
    """Compute Sharpe, MDD, cumulative return, etc."""
    rets = df_ret["ret"].values
    n = len(rets)

    # Annualized return
    cum_ret = np.prod(1 + rets) - 1
    ann_ret = (1 + cum_ret) ** (252 / n) - 1

    # Annualized vol
    ann_vol = np.std(rets) * np.sqrt(252)

    # Sharpe ratio
    excess = rets - rf_daily
    sharpe = np.mean(excess) / np.std(excess) * np.sqrt(252) if np.std(excess) > 0 else 0

    # Harvey t-stat: t = Sharpe * sqrt(N/252)
    n_years = n / 252
    t_stat = sharpe * np.sqrt(n_years)

    # Maximum drawdown
    cumulative = np.cumprod(1 + rets)
    running_max = np.maximum.accumulate(cumulative)
    drawdown = cumulative / running_max - 1
    mdd = np.min(drawdown)

    # Calmar ratio
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    return {
        "name": name,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "t_stat": t_stat,
        "mdd": mdd,
        "calmar": calmar,
        "cum_ret": cum_ret,
        "n_days": n,
        "avg_weight": df_ret["weight"].mean(),
    }

# Full period metrics
print("\n" + "=" * 100)
print(f"{'FULL PERIOD':^100s}")
print(f"{'(' + FULL_START + ' to ' + str(spy.index[-1].date()) + ')':^100s}")
print("=" * 100)
header = f"{'Strategy':<30s} {'AnnRet':>8s} {'AnnVol':>8s} {'Sharpe':>8s} {'t-stat':>8s} {'MDD':>8s} {'Calmar':>8s} {'AvgW':>8s}"
print(header)
print("-" * 100)

full_metrics = {}
for name, df_ret in results.items():
    m = compute_metrics(df_ret, name)
    full_metrics[name] = m
    print(f"{name:<30s} {m['ann_ret']:>8.2%} {m['ann_vol']:>8.2%} {m['sharpe']:>8.3f} {m['t_stat']:>8.2f} {m['mdd']:>8.2%} {m['calmar']:>8.3f} {m['avg_weight']:>8.3f}")

# OOS period metrics
spy_oos = spy.loc[OOS_START:]
results_oos = {}
for name, wfunc in strategies.items():
    r = run_strategy(spy_oos, name, wfunc)
    results_oos[name] = r

print("\n" + "=" * 100)
print(f"{'OOS PERIOD':^100s}")
print(f"{'(' + OOS_START + ' to ' + str(spy_oos.index[-1].date()) + ')':^100s}")
print("=" * 100)
print(header)
print("-" * 100)

oos_metrics = {}
for name, df_ret in results_oos.items():
    m = compute_metrics(df_ret, name)
    oos_metrics[name] = m
    print(f"{name:<30s} {m['ann_ret']:>8.2%} {m['ann_vol']:>8.2%} {m['sharpe']:>8.3f} {m['t_stat']:>8.2f} {m['mdd']:>8.2%} {m['calmar']:>8.3f} {m['avg_weight']:>8.3f}")

# ============================================================
# 5. Statistical Tests
# ============================================================
print("\n" + "=" * 100)
print(f"{'STATISTICAL TESTS':^100s}")
print("=" * 100)

# DM-like test: compare each strategy vs baseline
baseline_oos = results_oos["A: 12/VIX baseline"]["ret"].values

print("\nDiebold-Mariano style test (daily return difference vs baseline):")
print(f"{'Strategy':<30s} {'MeanDiff':>10s} {'t-stat':>8s} {'p-value':>8s} {'Sig?':>6s}")
print("-" * 70)

for name, df_ret in results_oos.items():
    if name == "A: 12/VIX baseline":
        continue
    alt_rets = df_ret["ret"].values
    # Align lengths
    min_len = min(len(baseline_oos), len(alt_rets))
    diff = alt_rets[:min_len] - baseline_oos[:min_len]
    t, p = stats.ttest_1samp(diff, 0)
    mean_diff = np.mean(diff)
    sig = "YES" if abs(t) > 3.0 else ("~" if abs(t) > 2.0 else "no")
    print(f"{name:<30s} {mean_diff:>10.6f} {t:>8.3f} {p:>8.4f} {sig:>6s}")

# Sharpe difference test (Lo 2002)
print("\nSharpe ratio difference test (vs baseline, Lo 2002 adjustment):")
print(f"{'Strategy':<30s} {'dSharpe':>10s} {'SE':>8s} {'z-stat':>8s} {'p-value':>8s}")
print("-" * 70)

baseline_sharpe = oos_metrics["A: 12/VIX baseline"]["sharpe"]
n_oos = oos_metrics["A: 12/VIX baseline"]["n_days"]

for name, m in oos_metrics.items():
    if name == "A: 12/VIX baseline":
        continue
    d_sharpe = m["sharpe"] - baseline_sharpe
    # Approximate SE of Sharpe difference ~ sqrt(2/T) per Lo (2002)
    se = np.sqrt(2 / (n_oos / 252))
    z = d_sharpe / se if se > 0 else 0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    print(f"{name:<30s} {d_sharpe:>10.4f} {se:>8.4f} {z:>8.3f} {p:>8.4f}")

# ============================================================
# 6. Sub-period analysis: performance DURING vs OUTSIDE hiking
# ============================================================
print("\n" + "=" * 100)
print(f"{'SUB-PERIOD ANALYSIS: DURING vs OUTSIDE HIKING PERIODS':^100s}")
print("=" * 100)

baseline_full = results["A: 12/VIX baseline"]
baseline_full_aligned = baseline_full.copy()
baseline_full_aligned["in_hiking"] = spy.loc[baseline_full.index, "in_hiking_period"]

# During hiking periods
hiking_mask = baseline_full_aligned["in_hiking"] == True
non_hiking_mask = baseline_full_aligned["in_hiking"] == False

print(f"\nBaseline 12/VIX performance split:")
if hiking_mask.sum() > 0:
    hiking_rets = baseline_full_aligned.loc[hiking_mask, "ret"]
    ann_ret_hike = (np.prod(1 + hiking_rets.values) ** (252 / len(hiking_rets)) - 1)
    ann_vol_hike = hiking_rets.std() * np.sqrt(252)
    sharpe_hike = (hiking_rets.mean() - RF_DAILY) / hiking_rets.std() * np.sqrt(252) if hiking_rets.std() > 0 else 0
    cum_hike = np.cumprod(1 + hiking_rets.values)
    mdd_hike = np.min(cum_hike / np.maximum.accumulate(cum_hike) - 1)
    print(f"  DURING hiking: AnnRet={ann_ret_hike:.2%}, Vol={ann_vol_hike:.2%}, Sharpe={sharpe_hike:.3f}, MDD={mdd_hike:.2%} ({len(hiking_rets)} days)")

if non_hiking_mask.sum() > 0:
    non_hiking_rets = baseline_full_aligned.loc[non_hiking_mask, "ret"]
    ann_ret_nh = (np.prod(1 + non_hiking_rets.values) ** (252 / len(non_hiking_rets)) - 1)
    ann_vol_nh = non_hiking_rets.std() * np.sqrt(252)
    sharpe_nh = (non_hiking_rets.mean() - RF_DAILY) / non_hiking_rets.std() * np.sqrt(252) if non_hiking_rets.std() > 0 else 0
    cum_nh = np.cumprod(1 + non_hiking_rets.values)
    mdd_nh = np.min(cum_nh / np.maximum.accumulate(cum_nh) - 1)
    print(f"  OUTSIDE hiking: AnnRet={ann_ret_nh:.2%}, Vol={ann_vol_nh:.2%}, Sharpe={sharpe_nh:.3f}, MDD={mdd_nh:.2%} ({len(non_hiking_rets)} days)")

# ============================================================
# 7. Robustness: vary the "conservative" parameter
# ============================================================
print("\n" + "=" * 100)
print(f"{'ROBUSTNESS: VARY CONSERVATIVE PARAMETER':^100s}")
print("=" * 100)
print(f"{'Param':>8s} {'Rule':>20s} {'AnnRet':>8s} {'Sharpe':>8s} {'MDD':>8s} {'t-stat':>8s}")
print("-" * 60)

for mult in [0.0, 0.3, 0.5, 0.7, 1.0]:
    def wfunc(vix, hike, period, m=mult):
        w = min(12.0 / max(vix, 1.0), 1.0)
        if period:
            w *= m
        return w
    r = run_strategy(spy_oos, f"mult={mult}", wfunc)
    met = compute_metrics(r, f"mult={mult}")
    label = "Cash" if mult == 0 else (f"{mult:.0%} weight" if mult < 1 else "Baseline")
    print(f"{mult:>8.1f} {label:>20s} {met['ann_ret']:>8.2%} {met['sharpe']:>8.3f} {met['mdd']:>8.2%} {met['t_stat']:>8.2f}")

# Also vary the VIX divisor during hikes
print(f"\n{'Divisor':>8s} {'Rule':>20s} {'AnnRet':>8s} {'Sharpe':>8s} {'MDD':>8s} {'t-stat':>8s}")
print("-" * 60)
for div in [6, 8, 10, 12]:
    def wfunc(vix, hike, period, d=div):
        if period:
            return min(float(d) / max(vix, 1.0), 1.0)
        return min(12.0 / max(vix, 1.0), 1.0)
    r = run_strategy(spy_oos, f"div={div}", wfunc)
    met = compute_metrics(r, f"div={div}")
    print(f"{div:>8d} {f'{div}/VIX in hikes':>20s} {met['ann_ret']:>8.2%} {met['sharpe']:>8.3f} {met['mdd']:>8.2%} {met['t_stat']:>8.2f}")

# ============================================================
# 8. Year-by-year breakdown
# ============================================================
print("\n" + "=" * 100)
print(f"{'YEAR-BY-YEAR COMPARISON (OOS)':^100s}")
print("=" * 100)

strategies_to_compare = ["A: 12/VIX baseline", "D: 50% in hiking period", "F: 8/VIX in hiking period"]

print(f"{'Year':>6s}", end="")
for s in strategies_to_compare:
    short = s.split(":")[0]
    print(f" {'Ret_'+short:>10s} {'Sha_'+short:>10s}", end="")
print(f" {'Hike?':>8s}")
print("-" * 80)

for year in range(2016, 2026):
    print(f"{year:>6d}", end="")
    yr_str = str(year)

    # Check if any hiking in this year
    any_hike = any(h.startswith(yr_str) for h in RATE_HIKE_MONTHS)

    for sname in strategies_to_compare:
        df_r = results_oos[sname]
        yr_mask = df_r.index.year == year
        if yr_mask.sum() > 0:
            yr_rets = df_r.loc[yr_mask, "ret"]
            yr_cum = np.prod(1 + yr_rets.values) - 1
            yr_vol = yr_rets.std() * np.sqrt(252)
            yr_sha = ((yr_rets.mean() - RF_DAILY) / yr_rets.std() * np.sqrt(252)) if yr_rets.std() > 0 else 0
            print(f" {yr_cum:>10.2%} {yr_sha:>10.3f}", end="")
        else:
            print(f" {'N/A':>10s} {'N/A':>10s}", end="")

    print(f" {'YES' if any_hike else 'no':>8s}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 100)
print(f"{'SUMMARY & CONCLUSION':^100s}")
print("=" * 100)

best_oos = max(oos_metrics.items(), key=lambda x: x[1]["sharpe"])
print(f"\nBest OOS Sharpe: {best_oos[0]} ({best_oos[1]['sharpe']:.3f})")
print(f"Baseline OOS Sharpe: {oos_metrics['A: 12/VIX baseline']['sharpe']:.3f}")

improvement = best_oos[1]["sharpe"] - oos_metrics["A: 12/VIX baseline"]["sharpe"]
print(f"Improvement: {improvement:+.4f}")

if abs(best_oos[1]["t_stat"]) > 3.0:
    print(f"Harvey significance: YES (t={best_oos[1]['t_stat']:.2f} > 3)")
else:
    print(f"Harvey significance: NO (t={best_oos[1]['t_stat']:.2f} < 3)")

# Check if any improvement is statistically significant
print("\nKey findings:")
for name, m in oos_metrics.items():
    if name == "A: 12/VIX baseline" or name == "E: Buy-and-hold SPY":
        continue
    d = m["sharpe"] - baseline_sharpe
    if d > 0:
        print(f"  + {name}: Sharpe {m['sharpe']:.3f} (+{d:.4f} vs baseline)")
    else:
        print(f"  - {name}: Sharpe {m['sharpe']:.3f} ({d:.4f} vs baseline)")

# MDD comparison
print(f"\nMDD comparison (OOS):")
for name, m in oos_metrics.items():
    print(f"  {name:<30s}: MDD = {m['mdd']:.2%}")

print("\n" + "=" * 100)
print("EXPERIMENT COMPLETE")
print("=" * 100)
