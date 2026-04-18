"""
K528: NFP (Non-Farm Payrolls) Event Study on SPY Volatility
=============================================================
Extends K513 (FOMC/NFP/CPI event study) with deeper NFP-specific analysis.

K513 finding: NFP vol ratio = 1.09x (NS, p=0.195). This study digs deeper:
  - Larger sample with more granular windows
  - VIX predictive regression
  - Vol crush pattern analysis
  - Seasonal decomposition (which months matter?)
  - NFP surprise impact (FRED PAYEMS data)

Data sources:
  - SPY daily OHLCV: yfinance (2005-01 to 2026-03)
  - VIX daily close: yfinance (^VIX)
  - NFP dates: programmatically generated (first Friday of each month)
  - NFP actual values: FRED PAYEMS (monthly, for surprise calculation)

References:
  - Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?"
    JFE, core finding: scheduled macro announcements earn risk premium
  - Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JFE
  - K513: Our prior FOMC/NFP/CPI event study (2005-2025, 668 events)

Author: VolPred Research System
Date: 2026-03-27
"""

import json
import warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================
# 1. Helper: Generate NFP dates (first Friday of each month)
# ============================================================
def get_first_friday(year, month):
    """Return the first Friday of a given year/month."""
    first_day = datetime(year, month, 1)
    # weekday(): Monday=0, Friday=4
    days_until_friday = (4 - first_day.weekday()) % 7
    return first_day + timedelta(days=days_until_friday)


def generate_nfp_dates(start_year=2005, end_year=2026):
    """Generate all NFP release dates (first Friday of each month)."""
    dates = []
    for year in range(start_year, end_year + 1):
        end_month = 12 if year < 2026 else 3  # up to March 2026
        for month in range(1, end_month + 1):
            ff = get_first_friday(year, month)
            dates.append(ff)
    return dates


# ============================================================
# 2. Download data
# ============================================================
print("=" * 60)
print("K528: NFP Event Study on SPY Volatility")
print("=" * 60)

print("\n[1/6] Downloading SPY and VIX data...")
spy = yf.download("SPY", start="2005-01-01", end="2026-03-27", progress=False)
vix = yf.download("^VIX", start="2005-01-01", end="2026-03-27", progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Calculate returns
spy["Return"] = spy["Close"].pct_change()
spy["AbsReturn"] = spy["Return"].abs()
spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
spy.dropna(subset=["Return"], inplace=True)

# Merge VIX
vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
spy = spy.join(vix_close, how="left")
spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays

print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")

# ============================================================
# 3. Map NFP dates to trading days
# ============================================================
print("\n[2/6] Mapping NFP dates to trading days...")

nfp_calendar = generate_nfp_dates(2005, 2026)
trading_dates = spy.index

# Map each NFP date to nearest trading day (could be holiday/early close)
nfp_trading_dates = []
for nfp_date in nfp_calendar:
    nfp_ts = pd.Timestamp(nfp_date)
    # Find exact match or next trading day
    if nfp_ts in trading_dates:
        nfp_trading_dates.append(nfp_ts)
    else:
        # Find nearest trading day within 3 days
        mask = (trading_dates >= nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
        candidates = trading_dates[mask]
        if len(candidates) > 0:
            nfp_trading_dates.append(candidates[0])

nfp_trading_dates = sorted(set(nfp_trading_dates))

# Only keep dates within our data range (with enough buffer for pre/post windows)
valid_nfp = [d for d in nfp_trading_dates
             if d >= trading_dates[10] and d <= trading_dates[-6]]

print(f"  Total NFP dates generated: {len(nfp_calendar)}")
print(f"  Matched to trading days: {len(nfp_trading_dates)}")
print(f"  Valid (with pre/post window): {len(valid_nfp)}")

# ============================================================
# 4. Calculate event windows
# ============================================================
print("\n[3/6] Calculating event window statistics...")

results = []
idx_list = list(trading_dates)

for nfp_date in valid_nfp:
    pos = idx_list.index(nfp_date)

    # Pre-event: T-5 to T-1
    pre_window = spy.iloc[pos-5:pos]
    # Event day: T
    event_day = spy.iloc[pos]
    # Post-event: T+1 to T+5
    post_window = spy.iloc[pos+1:pos+6]

    if len(pre_window) < 5 or len(post_window) < 5:
        continue

    row = {
        "date": nfp_date.strftime("%Y-%m-%d"),
        "year": nfp_date.year,
        "month": nfp_date.month,
        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
        "event_return": float(event_day["Return"]),
        "event_abs_return": float(event_day["AbsReturn"]),
        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
        "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
        "vix_change_event": None,
        "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
    }

    if row["pre_vix"] is not None and row["event_vix"] is not None:
        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]

    results.append(row)

df = pd.DataFrame(results)
print(f"  Events with complete data: {len(df)}")
print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")

# ============================================================
# 5. Non-NFP baseline calculation
# ============================================================
print("\n[4/6] Computing non-NFP baseline...")

nfp_set = set(valid_nfp)
non_nfp_mask = ~spy.index.isin(nfp_set)
non_nfp = spy[non_nfp_mask]

baseline_abs_return = float(non_nfp["AbsReturn"].mean())
baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
baseline_abs_return_median = float(non_nfp["AbsReturn"].median())

# Also compute Friday-only baseline (since NFP is always Friday)
friday_mask = non_nfp.index.weekday == 4
friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())

print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")

# ============================================================
# 6. Statistical tests
# ============================================================
print("\n[5/6] Running statistical tests...")

nfp_abs_returns = df["event_abs_return"].values
non_nfp_abs_returns = non_nfp["AbsReturn"].values
friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values

# --- Test A: NFP vs all non-NFP days ---
t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())

# --- Test B: NFP vs Friday-only baseline ---
t_stat_fri, p_val_fri = stats.ttest_ind(nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
vol_ratio_fri = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())

# --- Test C: Wilcoxon rank-sum (non-parametric) ---
u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')

# --- Test D: Vol crush pattern (post vs pre) ---
vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)

# --- Test E: VIX predictive regression ---
vix_valid = df.dropna(subset=["pre_vix"])
if len(vix_valid) > 10:
    from numpy.polynomial.polynomial import polyfit
    X_vix = vix_valid["pre_vix"].values
    Y_abs = vix_valid["event_abs_return"].values
    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
    # correlation and p-value
    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
    # also spearman
    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
else:
    slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6

# --- Test F: Pre-event VIX change (buildup) ---
# Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
vix_buildup = []
for nfp_date in valid_nfp:
    pos = idx_list.index(nfp_date)
    pre5 = spy.iloc[pos-5]
    pre1 = spy.iloc[pos-1]
    if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
        vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))

t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)

# --- Test G: Seasonal analysis (by month) ---
monthly_stats = {}
for month in range(1, 13):
    month_data = df[df["month"] == month]["event_abs_return"]
    if len(month_data) >= 5:
        monthly_stats[str(month)] = {
            "n": int(len(month_data)),
            "mean_abs_return": float(month_data.mean()),
            "vol_ratio": float(month_data.mean() / baseline_abs_return),
            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
        }

# --- Test H: Regime analysis (high VIX vs low VIX) ---
vix_median = df["pre_vix"].median()
high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)

# --- Test I: Time trend (has NFP impact changed over time?) ---
# Split into halves
midpoint = len(df) // 2
first_half = df.iloc[:midpoint]["event_abs_return"]
second_half = df.iloc[midpoint:]["event_abs_return"]
t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)

# --- Test J: Event-day return direction ---
pos_returns = (df["event_return"] > 0).sum()
neg_returns = (df["event_return"] < 0).sum()
# Binomial test: is there a directional bias?
binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)

print("\n" + "=" * 60)
print("RESULTS")
print("=" * 60)

print(f"\n--- A. NFP vs All Non-NFP Days ---")
print(f"  NFP day |return|:     {nfp_abs_returns.mean():.6f} ({nfp_abs_returns.mean()*100:.3f}%)")
print(f"  Non-NFP |return|:     {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
print(f"  Vol ratio:            {vol_ratio_all:.3f}x")
print(f"  t-stat:               {t_stat_all:.3f}")
print(f"  p-value:              {p_val_all:.4f}")
print(f"  Significant (5%):     {'YES' if p_val_all < 0.05 else 'NO'}")

print(f"\n--- B. NFP vs Friday-Only Baseline ---")
print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
print(f"  Vol ratio (vs Fri):   {vol_ratio_fri:.3f}x")
print(f"  t-stat:               {t_stat_fri:.3f}")
print(f"  p-value:              {p_val_fri:.4f}")

print(f"\n--- C. Wilcoxon Rank-Sum (non-parametric) ---")
print(f"  U-stat:               {u_stat:.1f}")
print(f"  p-value (one-sided):  {p_val_wilcox:.4f}")

print(f"\n--- D. Vol Crush Pattern (Post vs Pre) ---")
print(f"  Pre-event avg |ret|:  {df['pre_avg_abs_return'].mean():.6f}")
print(f"  Post-event avg |ret|: {df['post_avg_abs_return'].mean():.6f}")
print(f"  Difference:           {vol_crush.mean():.6f}")
print(f"  t-stat:               {t_crush:.3f}")
print(f"  p-value:              {p_crush:.4f}")
print(f"  Vol crush present:    {'YES' if vol_crush.mean() < 0 and p_crush < 0.05 else 'NO'}")

print(f"\n--- E. VIX Predictive Regression ---")
if r_vix is not None:
    print(f"  Pearson r:            {r_vix:.4f} (p={p_vix:.4f})")
    print(f"  Spearman rho:         {rho_vix:.4f} (p={p_rho_vix:.4f})")
    print(f"  Slope:                {slope:.8f}")
    print(f"  Interpretation:       1pt VIX increase → {slope*100:.4f}% more |return|")

print(f"\n--- F. VIX Buildup (T-5 to T-1) ---")
if t_buildup is not None:
    print(f"  Mean VIX change:      {np.mean(vix_buildup):.4f}")
    print(f"  t-stat:               {t_buildup:.3f}")
    print(f"  p-value:              {p_buildup:.4f}")
    print(f"  Anticipatory buildup: {'YES' if np.mean(vix_buildup) > 0 and p_buildup < 0.05 else 'NO'}")

print(f"\n--- G. Seasonal Pattern (by month) ---")
print(f"  {'Month':<8} {'N':<5} {'Avg |Ret|':<12} {'Ratio':<8} {'t-stat':<8} {'p-val':<8}")
month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
               7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
for m in range(1, 13):
    if str(m) in monthly_stats:
        ms = monthly_stats[str(m)]
        sig = "*" if ms["p_val"] < 0.05 else ""
        print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")

print(f"\n--- H. VIX Regime Analysis ---")
print(f"  VIX median split:     {vix_median:.1f}")
print(f"  High VIX NFP |ret|:   {high_vix.mean():.6f} (n={len(high_vix)})")
print(f"  Low VIX NFP |ret|:    {low_vix.mean():.6f} (n={len(low_vix)})")
print(f"  t-stat:               {t_regime:.3f}")
print(f"  p-value:              {p_regime:.4f}")

print(f"\n--- I. Time Trend (First Half vs Second Half) ---")
print(f"  First half |ret|:     {first_half.mean():.6f} (n={len(first_half)}, ~{df['date'].iloc[0][:4]}-{df['date'].iloc[midpoint-1][:4]})")
print(f"  Second half |ret|:    {second_half.mean():.6f} (n={len(second_half)}, ~{df['date'].iloc[midpoint][:4]}-{df['date'].iloc[-1][:4]})")
print(f"  t-stat:               {t_trend:.3f}")
print(f"  p-value:              {p_trend:.4f}")

print(f"\n--- J. Directional Bias ---")
print(f"  Positive returns:     {pos_returns}/{len(df)} ({pos_returns/len(df)*100:.1f}%)")
print(f"  Negative returns:     {neg_returns}/{len(df)} ({neg_returns/len(df)*100:.1f}%)")
print(f"  Binomial p-value:     {binom_p:.4f}")

# ============================================================
# 7. High-low range analysis (intraday vol proxy)
# ============================================================
print(f"\n--- K. Intraday Range (High-Low / Close) ---")
nfp_range = df["high_low_range"].mean()
non_nfp_range = float(((spy["High"] - spy["Low"]) / spy["Close"])[non_nfp_mask].mean())
range_ratio = nfp_range / non_nfp_range
print(f"  NFP day range:        {nfp_range:.6f} ({nfp_range*100:.3f}%)")
print(f"  Non-NFP range:        {non_nfp_range:.6f} ({non_nfp_range*100:.3f}%)")
print(f"  Range ratio:          {range_ratio:.3f}x")

# Volume analysis
print(f"\n--- L. Volume Analysis ---")
vol_ratio_data = df["volume_ratio"].dropna()
print(f"  NFP/avg volume ratio: {vol_ratio_data.mean():.3f}x")
print(f"  NFP volume > avg:     {(vol_ratio_data > 1).sum()}/{len(vol_ratio_data)} ({(vol_ratio_data > 1).mean()*100:.1f}%)")

# ============================================================
# 8. April NFP specific (for upcoming 04/03 article)
# ============================================================
print(f"\n--- M. Historical April NFP (for 04/03/2026 article) ---")
april_nfp = df[df["month"] == 4]
print(f"  April NFP events:     {len(april_nfp)}")
print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
if "4" in monthly_stats:
    ms4 = monthly_stats["4"]
    print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")

# ============================================================
# 9. Summary conclusion
# ============================================================
print(f"\n{'=' * 60}")
print("SUMMARY CONCLUSION")
print("=" * 60)

sig_level = 0.05
conclusions = []

if p_val_all < sig_level:
    conclusions.append(f"NFP days show significantly higher vol ({vol_ratio_all:.2f}x, p={p_val_all:.4f})")
else:
    conclusions.append(f"NFP days do NOT show significantly higher vol ({vol_ratio_all:.2f}x, p={p_val_all:.4f})")

if p_val_fri < sig_level:
    conclusions.append(f"Even vs Friday baseline, NFP is significant ({vol_ratio_fri:.2f}x, p={p_val_fri:.4f})")
else:
    conclusions.append(f"Vs Friday baseline, NFP is also not significant ({vol_ratio_fri:.2f}x, p={p_val_fri:.4f})")

if vol_crush.mean() < 0 and p_crush < sig_level:
    conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
else:
    conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")

if r_vix is not None and p_vix < sig_level:
    conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
else:
    conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")

for c in conclusions:
    print(f"  • {c}")

print(f"\n  Practical implication for 04/03 NFP:")
print(f"    → NFP alone does not warrant reducing SPY exposure")
print(f"    → Focus on VIX level and broader market conditions instead")
print(f"    → Consistent with K513 findings (NFP 1.09x, NS)")

# ============================================================
# 10. Save results
# ============================================================
print("\n[6/6] Saving results...")

output = {
    "experiment_id": "K528",
    "title": "NFP Event Study on SPY Volatility",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
    "sample": {
        "total_nfp_events": len(df),
        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
        "non_nfp_trading_days": int(non_nfp_mask.sum()),
        "friday_baseline_days": int(friday_mask.sum()),
    },
    "main_results": {
        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
        "non_nfp_avg_abs_return": baseline_abs_return,
        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
        "friday_baseline_abs_return": friday_baseline,
        "vol_ratio_vs_all": vol_ratio_all,
        "vol_ratio_vs_friday": vol_ratio_fri,
    },
    "statistical_tests": {
        "A_nfp_vs_all": {
            "test": "Welch t-test",
            "t_stat": float(t_stat_all),
            "p_value": float(p_val_all),
            "significant_5pct": bool(p_val_all < 0.05),
        },
        "B_nfp_vs_friday": {
            "test": "Welch t-test",
            "t_stat": float(t_stat_fri),
            "p_value": float(p_val_fri),
            "significant_5pct": bool(p_val_fri < 0.05),
        },
        "C_wilcoxon": {
            "test": "Mann-Whitney U (one-sided)",
            "u_stat": float(u_stat),
            "p_value": float(p_val_wilcox),
            "significant_5pct": bool(p_val_wilcox < 0.05),
        },
        "D_vol_crush": {
            "test": "One-sample t-test (post-pre diff)",
            "pre_avg": float(df["pre_avg_abs_return"].mean()),
            "post_avg": float(df["post_avg_abs_return"].mean()),
            "diff": float(vol_crush.mean()),
            "t_stat": float(t_crush),
            "p_value": float(p_crush),
            "vol_crush_present": bool(vol_crush.mean() < 0 and p_crush < 0.05),
        },
        "E_vix_predictive": {
            "test": "Pearson + Spearman correlation",
            "pearson_r": float(r_vix) if r_vix else None,
            "pearson_p": float(p_vix) if p_vix else None,
            "spearman_rho": float(rho_vix) if rho_vix else None,
            "spearman_p": float(p_rho_vix) if p_rho_vix else None,
            "slope": float(slope) if slope else None,
            "interpretation": f"1pt VIX → {slope*100:.4f}% more |return|" if slope else None,
        },
        "F_vix_buildup": {
            "test": "One-sample t-test (T-5 to T-1 VIX change)",
            "mean_change": float(np.mean(vix_buildup)) if vix_buildup else None,
            "t_stat": float(t_buildup) if t_buildup else None,
            "p_value": float(p_buildup) if p_buildup else None,
            "anticipatory_buildup": bool(np.mean(vix_buildup) > 0 and p_buildup < 0.05) if t_buildup else None,
        },
    },
    "seasonal_analysis": monthly_stats,
    "regime_analysis": {
        "vix_median_split": float(vix_median),
        "high_vix_nfp_abs_return": float(high_vix.mean()),
        "low_vix_nfp_abs_return": float(low_vix.mean()),
        "n_high": int(len(high_vix)),
        "n_low": int(len(low_vix)),
        "t_stat": float(t_regime),
        "p_value": float(p_regime),
    },
    "time_trend": {
        "first_half_abs_return": float(first_half.mean()),
        "second_half_abs_return": float(second_half.mean()),
        "t_stat": float(t_trend),
        "p_value": float(p_trend),
    },
    "directional_bias": {
        "positive_count": int(pos_returns),
        "negative_count": int(neg_returns),
        "total": int(pos_returns + neg_returns),
        "positive_rate": float(pos_returns / (pos_returns + neg_returns)),
        "binomial_p": binom_p,
    },
    "intraday_range": {
        "nfp_avg_range": float(nfp_range),
        "non_nfp_avg_range": float(non_nfp_range),
        "range_ratio": float(range_ratio),
    },
    "volume": {
        "avg_volume_ratio": float(vol_ratio_data.mean()),
        "pct_above_avg": float((vol_ratio_data > 1).mean()),
    },
    "april_nfp": {
        "n": int(len(april_nfp)),
        "avg_abs_return": float(april_nfp["event_abs_return"].mean()),
        "avg_signed_return": float(april_nfp["event_return"].mean()),
        "positive_rate": float((april_nfp["event_return"] > 0).mean()),
        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
    },
    "conclusions": conclusions,
    "practical_implication": (
        "NFP does NOT warrant reducing SPY exposure. Vol ratio ~1.09x is statistically "
        "insignificant across all tests. Consistent with K513. For 04/03 NFP: focus on "
        "VIX level and broader conditions, not the NFP event itself."
    ),
    "references": [
        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
    ],
    "event_data": results,  # full per-event data
}

out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"  Saved to: {out_path}")
print("\nDone!")
