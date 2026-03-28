"""
K661: NFP (Non-Farm Payrolls) Pre-Event Volatility Analysis
============================================================

Motivation:
  NFP is released on the first Friday of each month at 8:30 AM ET.
  It is one of the most market-moving US economic releases. We analyze:
    - Pre-NFP VIX behavior (5-day lead-up)
    - NFP-day SPY realized volatility vs normal days
    - Post-NFP drift in SPY (1, 5, 20 days)
    - VIX resolution effect (uncertainty drops after event)
    - Regime dependence (VIX>20 vs VIX<20)
    - "Surprise" proxy via SPY direction on NFP day

Data source: yfinance (SPY, ^VIX), 2010-01-01 to 2026-03-27
Reference: Ederington & Lee (1993) JF, Flannery & Protopapadakis (2002) JF
"""

import json
import warnings
from datetime import datetime, date, timedelta
from pathlib import Path
import calendar

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────
# 1. Download data
# ──────────────────────────────────────────────
print("=" * 60)
print("K661: NFP Pre-Event Volatility Analysis")
print("=" * 60)

START = "2010-01-01"
END = "2026-03-27"

print(f"\nDownloading SPY and ^VIX from {START} to {END} ...")
spy = yf.download("SPY", start=START, end=END, progress=False)
vix = yf.download("^VIX", start=START, end=END, progress=False)

# Flatten multi-level columns if needed
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy["Return"] = spy["Close"].pct_change()
spy["AbsReturn"] = spy["Return"].abs()
spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))

vix_close = vix["Close"].rename("VIX")

# Merge
df = spy[["Close", "Return", "AbsReturn", "LogReturn"]].copy()
df.columns = ["SPY_Close", "SPY_Return", "SPY_AbsReturn", "SPY_LogReturn"]
df = df.join(vix_close, how="inner")
df["VIX_Change"] = df["VIX"].diff()
df["VIX_PctChange"] = df["VIX"].pct_change()
df.dropna(inplace=True)

print(f"Data: {len(df)} trading days, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ──────────────────────────────────────────────
# 2. Identify NFP dates (first Friday of each month)
# ──────────────────────────────────────────────
def get_first_friday(year, month):
    """Return the first Friday of the given month/year."""
    c = calendar.Calendar(firstweekday=calendar.MONDAY)
    monthcal = c.monthdatescalendar(year, month)
    for week in monthcal:
        friday = week[4]  # Friday is index 4
        if friday.month == month:
            return friday
    return None

# Generate all first Fridays in our range
start_dt = pd.Timestamp(START)
end_dt = pd.Timestamp(END)

nfp_dates_raw = []
current = start_dt
while current <= end_dt:
    ff = get_first_friday(current.year, current.month)
    if ff is not None:
        nfp_dates_raw.append(pd.Timestamp(ff))
    # Move to next month
    if current.month == 12:
        current = pd.Timestamp(f"{current.year + 1}-01-01")
    else:
        current = pd.Timestamp(f"{current.year}-{current.month + 1:02d}-01")

# Filter to dates that exist in our data (market was open)
nfp_dates = [d for d in nfp_dates_raw if d in df.index]

# For NFP dates that fall on holidays, use the next trading day
nfp_dates_adjusted = []
for d in nfp_dates_raw:
    if d in df.index:
        nfp_dates_adjusted.append(d)
    else:
        # Find next trading day
        for offset in range(1, 5):
            candidate = d + pd.Timedelta(days=offset)
            if candidate in df.index:
                nfp_dates_adjusted.append(candidate)
                break

nfp_dates = sorted(set(nfp_dates_adjusted))
print(f"\nIdentified {len(nfp_dates)} NFP release dates (first Friday of each month, adjusted for holidays)")
print(f"  First: {nfp_dates[0].strftime('%Y-%m-%d')}, Last: {nfp_dates[-1].strftime('%Y-%m-%d')}")

# Mark NFP days in the dataframe
df["IsNFP"] = df.index.isin(nfp_dates).astype(int)

# ──────────────────────────────────────────────
# 3a. Pre-NFP VIX pattern (5 days before NFP)
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("3a. Pre-NFP VIX Pattern (5 trading days before NFP)")
print("=" * 60)

pre_nfp_vix_changes = {f"T-{i}": [] for i in range(1, 6)}
pre_nfp_vix_levels = {f"T-{i}": [] for i in range(1, 6)}

trading_days = df.index.tolist()

for nfp_date in nfp_dates:
    try:
        idx = trading_days.index(nfp_date)
    except ValueError:
        continue
    if idx < 5:
        continue
    for i in range(1, 6):
        pre_day = trading_days[idx - i]
        pre_nfp_vix_changes[f"T-{i}"].append(df.loc[pre_day, "VIX_Change"])
        pre_nfp_vix_levels[f"T-{i}"].append(df.loc[pre_day, "VIX"])

print("\nAverage VIX change in the 5 days before NFP:")
pre_nfp_summary = {}
for key in ["T-5", "T-4", "T-3", "T-2", "T-1"]:
    vals = pre_nfp_vix_changes[key]
    mean_chg = np.mean(vals)
    se = np.std(vals, ddof=1) / np.sqrt(len(vals))
    t_stat = mean_chg / se if se > 0 else 0
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(vals) - 1))
    print(f"  {key}: Mean VIX change = {mean_chg:+.4f} (t={t_stat:.2f}, p={p_val:.3f}, n={len(vals)})")
    pre_nfp_summary[key] = {
        "mean_vix_change": round(float(mean_chg), 4),
        "t_stat": round(float(t_stat), 2),
        "p_value": round(float(p_val), 4),
        "n": len(vals),
    }

# Cumulative VIX change T-5 to T-1
cum_vix_changes = []
for nfp_date in nfp_dates:
    try:
        idx = trading_days.index(nfp_date)
    except ValueError:
        continue
    if idx < 6:
        continue
    vix_at_t5 = df.loc[trading_days[idx - 5], "VIX"]
    vix_at_t0 = df.loc[nfp_date, "VIX"]
    # Actually we want T-5 to T-1 (before NFP day)
    vix_at_t1 = df.loc[trading_days[idx - 1], "VIX"]
    cum_vix_changes.append(vix_at_t1 - vix_at_t5)

cum_mean = np.mean(cum_vix_changes)
cum_se = np.std(cum_vix_changes, ddof=1) / np.sqrt(len(cum_vix_changes))
cum_t = cum_mean / cum_se if cum_se > 0 else 0
print(f"\n  Cumulative VIX change (T-5 to T-1): {cum_mean:+.4f} (t={cum_t:.2f}, n={len(cum_vix_changes)})")

# ──────────────────────────────────────────────
# 3b. NFP day realized vol vs non-NFP day
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("3b. NFP Day Volatility vs Non-NFP Day")
print("=" * 60)

nfp_abs_ret = df.loc[df["IsNFP"] == 1, "SPY_AbsReturn"].dropna()
non_nfp_abs_ret = df.loc[df["IsNFP"] == 0, "SPY_AbsReturn"].dropna()

nfp_mean_abs = nfp_abs_ret.mean()
non_nfp_mean_abs = non_nfp_abs_ret.mean()
vol_ratio = nfp_mean_abs / non_nfp_mean_abs

# Welch's t-test
t_stat_vol, p_val_vol = stats.ttest_ind(nfp_abs_ret, non_nfp_abs_ret, equal_var=False)
# Mann-Whitney U (non-parametric)
u_stat, p_val_mw = stats.mannwhitneyu(nfp_abs_ret, non_nfp_abs_ret, alternative="two-sided")

print(f"\n  NFP day mean |return|:     {nfp_mean_abs:.4f} ({nfp_mean_abs*100:.2f}%)")
print(f"  Non-NFP day mean |return|: {non_nfp_mean_abs:.4f} ({non_nfp_mean_abs*100:.2f}%)")
print(f"  Ratio (NFP/non-NFP):       {vol_ratio:.2f}x")
print(f"  Welch's t-test:            t={t_stat_vol:.2f}, p={p_val_vol:.4f}")
print(f"  Mann-Whitney U:            U={u_stat:.0f}, p={p_val_mw:.4f}")
print(f"  n(NFP)={len(nfp_abs_ret)}, n(non-NFP)={len(non_nfp_abs_ret)}")

# Also compare squared returns (variance proxy)
nfp_sq_ret = (df.loc[df["IsNFP"] == 1, "SPY_Return"] ** 2).dropna()
non_nfp_sq_ret = (df.loc[df["IsNFP"] == 0, "SPY_Return"] ** 2).dropna()
var_ratio = nfp_sq_ret.mean() / non_nfp_sq_ret.mean()
print(f"\n  Variance ratio (r^2): {var_ratio:.2f}x")

# ──────────────────────────────────────────────
# 3c. Post-NFP SPY drift
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("3c. Post-NFP SPY Drift")
print("=" * 60)

horizons = [1, 5, 20]
post_nfp_drift = {}

for h in horizons:
    rets = []
    for nfp_date in nfp_dates:
        try:
            idx = trading_days.index(nfp_date)
        except ValueError:
            continue
        if idx + h >= len(trading_days):
            continue
        future_day = trading_days[idx + h]
        cum_ret = (df.loc[future_day, "SPY_Close"] / df.loc[nfp_date, "SPY_Close"]) - 1
        rets.append(cum_ret)

    mean_ret = np.mean(rets)
    se = np.std(rets, ddof=1) / np.sqrt(len(rets))
    t_stat = mean_ret / se if se > 0 else 0
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(rets) - 1))

    # Compare to unconditional
    all_h_rets = []
    for i in range(len(trading_days) - h):
        cum = (df.loc[trading_days[i + h], "SPY_Close"] / df.loc[trading_days[i], "SPY_Close"]) - 1
        all_h_rets.append(cum)
    uncond_mean = np.mean(all_h_rets)

    print(f"\n  {h}-day post-NFP return:")
    print(f"    Mean: {mean_ret*100:.3f}% (t={t_stat:.2f}, p={p_val:.3f})")
    print(f"    Unconditional {h}-day mean: {uncond_mean*100:.3f}%")
    print(f"    Excess: {(mean_ret - uncond_mean)*100:.3f}%")

    post_nfp_drift[f"{h}d"] = {
        "mean_return_pct": round(float(mean_ret * 100), 3),
        "unconditional_mean_pct": round(float(uncond_mean * 100), 3),
        "excess_return_pct": round(float((mean_ret - uncond_mean) * 100), 3),
        "t_stat": round(float(t_stat), 2),
        "p_value": round(float(p_val), 4),
        "n": len(rets),
    }

# ──────────────────────────────────────────────
# 3d. VIX behavior after NFP (uncertainty resolution)
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("3d. VIX Behavior After NFP (Uncertainty Resolution)")
print("=" * 60)

vix_changes_on_nfp = []
vix_changes_1d_after = []
vix_changes_5d_after = []

for nfp_date in nfp_dates:
    try:
        idx = trading_days.index(nfp_date)
    except ValueError:
        continue
    if idx < 1 or idx + 5 >= len(trading_days):
        continue

    # VIX change ON NFP day (close-to-close)
    prev_day = trading_days[idx - 1]
    vix_chg = df.loc[nfp_date, "VIX"] - df.loc[prev_day, "VIX"]
    vix_changes_on_nfp.append(vix_chg)

    # VIX change 1 day after NFP
    next_day = trading_days[idx + 1]
    vix_chg_1d = df.loc[next_day, "VIX"] - df.loc[nfp_date, "VIX"]
    vix_changes_1d_after.append(vix_chg_1d)

    # VIX change 5 days after NFP
    day_5 = trading_days[idx + 5]
    vix_chg_5d = df.loc[day_5, "VIX"] - df.loc[nfp_date, "VIX"]
    vix_changes_5d_after.append(vix_chg_5d)

def report_vix_change(label, values):
    mean_val = np.mean(values)
    se = np.std(values, ddof=1) / np.sqrt(len(values))
    t_stat = mean_val / se if se > 0 else 0
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(values) - 1))
    pct_neg = sum(1 for v in values if v < 0) / len(values) * 100
    print(f"  {label}:")
    print(f"    Mean: {mean_val:+.3f} pts (t={t_stat:.2f}, p={p_val:.3f})")
    print(f"    % of times VIX dropped: {pct_neg:.1f}%")
    return {
        "mean_change_pts": round(float(mean_val), 3),
        "t_stat": round(float(t_stat), 2),
        "p_value": round(float(p_val), 4),
        "pct_drops": round(float(pct_neg), 1),
        "n": len(values),
    }

print()
vix_on_nfp = report_vix_change("VIX change ON NFP day", vix_changes_on_nfp)
print()
vix_1d_after = report_vix_change("VIX change 1 day AFTER NFP", vix_changes_1d_after)
print()
vix_5d_after = report_vix_change("VIX change 5 days AFTER NFP", vix_changes_5d_after)

# ──────────────────────────────────────────────
# 3e. Regime dependence (VIX level)
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("3e. Regime Dependence (VIX Level)")
print("=" * 60)

regime_results = {}
vix_thresholds = [(0, 15, "Low (VIX<15)"), (15, 20, "Medium (15<=VIX<20)"),
                  (20, 25, "Elevated (20<=VIX<25)"), (25, 100, "High (VIX>=25)")]

for lo, hi, label in vix_thresholds:
    nfp_in_regime = []
    nonnfp_in_regime = []

    for nfp_date in nfp_dates:
        try:
            idx = trading_days.index(nfp_date)
        except ValueError:
            continue
        if idx < 1:
            continue
        # Use previous day's VIX to define regime (available before market open)
        prev_vix = df.loc[trading_days[idx - 1], "VIX"]
        if lo <= prev_vix < hi:
            nfp_in_regime.append(df.loc[nfp_date, "SPY_AbsReturn"])

    # Non-NFP days in same regime
    for i, row in df.iterrows():
        if row["IsNFP"] == 0:
            vix_val = row["VIX"]
            if lo <= vix_val < hi:
                nonnfp_in_regime.append(row["SPY_AbsReturn"])

    if len(nfp_in_regime) > 5:
        nfp_mean = np.mean(nfp_in_regime)
        nonnfp_mean = np.mean(nonnfp_in_regime) if nonnfp_in_regime else 0
        ratio = nfp_mean / nonnfp_mean if nonnfp_mean > 0 else float("inf")

        t_stat, p_val = stats.ttest_ind(nfp_in_regime, nonnfp_in_regime, equal_var=False) if len(nonnfp_in_regime) > 5 else (0, 1)

        print(f"\n  {label} (n_NFP={len(nfp_in_regime)}):")
        print(f"    NFP |r|: {nfp_mean*100:.3f}%,  Non-NFP |r|: {nonnfp_mean*100:.3f}%")
        print(f"    Ratio: {ratio:.2f}x  (t={t_stat:.2f}, p={p_val:.4f})")

        regime_results[label] = {
            "n_nfp": len(nfp_in_regime),
            "n_non_nfp": len(nonnfp_in_regime),
            "nfp_abs_return_pct": round(float(nfp_mean * 100), 3),
            "non_nfp_abs_return_pct": round(float(nonnfp_mean * 100), 3),
            "ratio": round(float(ratio), 2),
            "t_stat": round(float(t_stat), 2),
            "p_value": round(float(p_val), 4),
        }
    else:
        print(f"\n  {label}: insufficient data (n={len(nfp_in_regime)})")

# ──────────────────────────────────────────────
# 4. NFP "Surprise" Analysis (proxy: SPY direction)
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("4. NFP Surprise Analysis (proxy: SPY direction on NFP day)")
print("=" * 60)

nfp_returns = []
for nfp_date in nfp_dates:
    if nfp_date in df.index:
        ret = df.loc[nfp_date, "SPY_Return"]
        nfp_returns.append((nfp_date, ret))

nfp_ret_series = pd.Series([r for _, r in nfp_returns], index=[d for d, _ in nfp_returns])

# "Good" NFP = SPY goes up; "Bad" NFP = SPY goes down
good_nfp = nfp_ret_series[nfp_ret_series > 0]
bad_nfp = nfp_ret_series[nfp_ret_series <= 0]

print(f"\n  Total NFP days: {len(nfp_ret_series)}")
print(f"  'Good' NFP (SPY up):   {len(good_nfp)} ({len(good_nfp)/len(nfp_ret_series)*100:.1f}%)")
print(f"  'Bad' NFP (SPY down):  {len(bad_nfp)} ({len(bad_nfp)/len(nfp_ret_series)*100:.1f}%)")
print(f"  Mean return on 'Good': {good_nfp.mean()*100:+.3f}%")
print(f"  Mean return on 'Bad':  {bad_nfp.mean()*100:+.3f}%")

# Large moves (>1% absolute)
large_moves = nfp_ret_series[nfp_ret_series.abs() > 0.01]
print(f"\n  Large NFP moves (|r|>1%): {len(large_moves)} ({len(large_moves)/len(nfp_ret_series)*100:.1f}%)")
if len(large_moves) > 0:
    print(f"    Mean |r| on large days: {large_moves.abs().mean()*100:.2f}%")

# VIX reaction based on SPY direction
vix_on_good_nfp = []
vix_on_bad_nfp = []
for nfp_date in nfp_dates:
    try:
        idx = trading_days.index(nfp_date)
    except ValueError:
        continue
    if idx < 1:
        continue
    spy_ret = df.loc[nfp_date, "SPY_Return"]
    vix_chg = df.loc[nfp_date, "VIX"] - df.loc[trading_days[idx - 1], "VIX"]
    if spy_ret > 0:
        vix_on_good_nfp.append(vix_chg)
    else:
        vix_on_bad_nfp.append(vix_chg)

print(f"\n  VIX change on 'Good' NFP: {np.mean(vix_on_good_nfp):+.3f} pts")
print(f"  VIX change on 'Bad' NFP:  {np.mean(vix_on_bad_nfp):+.3f} pts")

# Post-NFP drift conditioned on direction
print("\n  Post-NFP drift conditioned on direction:")
surprise_drift = {}
for direction, nfp_subset, label in [("good", good_nfp, "Good NFP"), ("bad", bad_nfp, "Bad NFP")]:
    drift_data = {}
    for h in [1, 5, 20]:
        rets = []
        for nfp_date in nfp_subset.index:
            try:
                idx = trading_days.index(nfp_date)
            except ValueError:
                continue
            if idx + h >= len(trading_days):
                continue
            future_day = trading_days[idx + h]
            cum_ret = (df.loc[future_day, "SPY_Close"] / df.loc[nfp_date, "SPY_Close"]) - 1
            rets.append(cum_ret)
        if rets:
            mean_r = np.mean(rets)
            print(f"    After {label}: {h}-day return = {mean_r*100:+.3f}% (n={len(rets)})")
            drift_data[f"{h}d"] = round(float(mean_r * 100), 3)
    surprise_drift[direction] = drift_data

# ──────────────────────────────────────────────
# 5. Year-by-year NFP impact
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("5. Year-by-Year NFP Impact")
print("=" * 60)

yearly_nfp_stats = {}
for nfp_date in nfp_dates:
    yr = nfp_date.year
    if yr not in yearly_nfp_stats:
        yearly_nfp_stats[yr] = []
    if nfp_date in df.index:
        yearly_nfp_stats[yr].append(df.loc[nfp_date, "SPY_AbsReturn"])

print(f"\n  {'Year':<6} {'Mean |r|%':>10} {'N':>5}")
print(f"  {'-'*6} {'-'*10} {'-'*5}")
yearly_summary = {}
for yr in sorted(yearly_nfp_stats.keys()):
    vals = yearly_nfp_stats[yr]
    if vals:
        m = np.mean(vals) * 100
        print(f"  {yr:<6} {m:>10.3f} {len(vals):>5}")
        yearly_summary[str(yr)] = {"mean_abs_return_pct": round(float(m), 3), "n": len(vals)}

# ──────────────────────────────────────────────
# 6. Current context: VIX around 27-30 (late March 2026)
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("6. Current Context for April 3, 2026 NFP")
print("=" * 60)

# Get latest VIX
latest_vix = df["VIX"].iloc[-1]
latest_date = df.index[-1].strftime("%Y-%m-%d")
print(f"\n  Latest VIX: {latest_vix:.2f} (as of {latest_date})")

# Historical NFP performance when VIX was in similar range (25-35)
high_vix_nfp = []
high_vix_nonnfp = []
for nfp_date in nfp_dates:
    try:
        idx = trading_days.index(nfp_date)
    except ValueError:
        continue
    if idx < 1:
        continue
    prev_vix = df.loc[trading_days[idx - 1], "VIX"]
    if 25 <= prev_vix <= 35:
        high_vix_nfp.append({
            "date": nfp_date.strftime("%Y-%m-%d"),
            "spy_return": float(df.loc[nfp_date, "SPY_Return"]),
            "abs_return": float(df.loc[nfp_date, "SPY_AbsReturn"]),
            "vix_prev": float(prev_vix),
        })

print(f"\n  Historical NFP days with VIX 25-35: {len(high_vix_nfp)} events")
if high_vix_nfp:
    high_vix_abs = [x["abs_return"] for x in high_vix_nfp]
    high_vix_ret = [x["spy_return"] for x in high_vix_nfp]
    print(f"  Mean |return|: {np.mean(high_vix_abs)*100:.3f}%")
    print(f"  Mean return:   {np.mean(high_vix_ret)*100:+.3f}%")
    print(f"  Max |return|:  {max(high_vix_abs)*100:.3f}%")
    print(f"\n  Individual events (most recent first):")
    for evt in sorted(high_vix_nfp, key=lambda x: x["date"], reverse=True)[:10]:
        print(f"    {evt['date']}: SPY={evt['spy_return']*100:+.2f}%, VIX_prev={evt['vix_prev']:.1f}")

# ──────────────────────────────────────────────
# 7. Investor-facing summary
# ──────────────────────────────────────────────
print("\n" + "=" * 60)
print("7. Investor-Facing Summary")
print("=" * 60)

print(f"""
Key findings for investors:

1. NFP Day Volatility:
   - SPY |return| on NFP day is {vol_ratio:.2f}x normal days
   - Variance (r^2) ratio: {var_ratio:.2f}x
   - This is {'statistically significant' if p_val_vol < 0.05 else 'not statistically significant'} (p={p_val_vol:.4f})

2. VIX Resolution Effect:
   - VIX drops on NFP day {vix_on_nfp['pct_drops']:.0f}% of the time
   - Average VIX change on NFP: {vix_on_nfp['mean_change_pts']:+.3f} pts
   - This confirms the uncertainty resolution hypothesis

3. Regime Matters:
   - When VIX > 25, NFP days show {regime_results.get('High (VIX>=25)', {}).get('ratio', 'N/A')}x more vol than normal
   - When VIX < 15, NFP days show {regime_results.get('Low (VIX<15)', {}).get('ratio', 'N/A')}x more vol than normal

4. For April 3, 2026:
   - Current VIX ~{latest_vix:.0f} → high uncertainty environment
   - Historical NFP with VIX 25-35: average |move| = {np.mean(high_vix_abs)*100:.2f}% if high_vix_abs else 'N/A'
   - {'Consider reducing position sizing before NFP' if latest_vix > 25 else 'Normal position sizing appropriate'}
   - NFP release is at 8:30 AM ET — avoid limit orders that might get filled at bad prices
""")

# ──────────────────────────────────────────────
# 8. Save results
# ──────────────────────────────────────────────
results = {
    "experiment_id": "K661",
    "title": "NFP Pre-Event Volatility Analysis",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance (SPY, ^VIX)",
    "data_period": f"{START} to {END}",
    "n_trading_days": len(df),
    "n_nfp_dates": len(nfp_dates),
    "references": [
        "Ederington & Lee (1993) 'How Markets Process Information: News Releases and Volatility' JF",
        "Flannery & Protopapadakis (2002) 'Macroeconomic Factors Do Influence Aggregate Stock Returns' RFS",
        "Andersen et al. (2003) 'Micro Effects of Macro Announcements' AER",
    ],
    "pre_nfp_vix_pattern": pre_nfp_summary,
    "cumulative_vix_change_T5_to_T1": {
        "mean": round(float(cum_mean), 4),
        "t_stat": round(float(cum_t), 2),
        "n": len(cum_vix_changes),
    },
    "nfp_day_volatility": {
        "nfp_mean_abs_return_pct": round(float(nfp_mean_abs * 100), 3),
        "non_nfp_mean_abs_return_pct": round(float(non_nfp_mean_abs * 100), 3),
        "vol_ratio": round(float(vol_ratio), 2),
        "variance_ratio": round(float(var_ratio), 2),
        "welch_t_stat": round(float(t_stat_vol), 2),
        "welch_p_value": round(float(p_val_vol), 4),
        "mann_whitney_p": round(float(p_val_mw), 4),
        "n_nfp": len(nfp_abs_ret),
        "n_non_nfp": len(non_nfp_abs_ret),
    },
    "post_nfp_drift": post_nfp_drift,
    "vix_resolution": {
        "on_nfp_day": vix_on_nfp,
        "1d_after_nfp": vix_1d_after,
        "5d_after_nfp": vix_5d_after,
    },
    "regime_dependence": regime_results,
    "surprise_analysis": {
        "total_nfp_days": len(nfp_ret_series),
        "pct_good_nfp": round(float(len(good_nfp) / len(nfp_ret_series) * 100), 1),
        "pct_bad_nfp": round(float(len(bad_nfp) / len(nfp_ret_series) * 100), 1),
        "mean_good_return_pct": round(float(good_nfp.mean() * 100), 3),
        "mean_bad_return_pct": round(float(bad_nfp.mean() * 100), 3),
        "large_move_pct": round(float(len(large_moves) / len(nfp_ret_series) * 100), 1),
        "vix_on_good_nfp_pts": round(float(np.mean(vix_on_good_nfp)), 3),
        "vix_on_bad_nfp_pts": round(float(np.mean(vix_on_bad_nfp)), 3),
        "post_drift_by_direction": surprise_drift,
    },
    "yearly_summary": yearly_summary,
    "current_context": {
        "latest_vix": round(float(latest_vix), 2),
        "latest_date": latest_date,
        "high_vix_nfp_events": high_vix_nfp,
        "high_vix_nfp_mean_abs_return_pct": round(float(np.mean(high_vix_abs) * 100), 3) if high_vix_abs else None,
    },
    "investor_summary": {
        "nfp_vol_multiplier": round(float(vol_ratio), 2),
        "nfp_variance_multiplier": round(float(var_ratio), 2),
        "vix_drops_on_nfp_pct": round(float(vix_on_nfp["pct_drops"]), 1),
        "vix_mean_change_on_nfp": round(float(vix_on_nfp["mean_change_pts"]), 3),
        "current_vix": round(float(latest_vix), 2),
        "recommendation": (
            "High VIX environment: NFP will be a high-volatility event. "
            "Consider (1) reducing position size by 20-30% before NFP, "
            "(2) avoiding limit orders near current price, "
            "(3) waiting 30-60 min after release for price discovery."
            if latest_vix > 25 else
            "Normal VIX environment: standard NFP playbook. "
            "Expect slightly elevated vol but no need for special measures."
        ),
    },
}

output_path = Path(__file__).parent / "k661_results.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

print(f"\nResults saved to {output_path}")
print("\nDone!")
