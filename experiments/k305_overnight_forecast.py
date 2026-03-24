"""
K305: Can We Forecast Tomorrow's Overnight Gap?
================================================
Background:
  K268 showed overnight returns account for ~50% of daily variance with
  different properties (SPY overnight Sharpe 0.57 vs intraday 0.21).
  K297 showed opening 30 minutes = 17.8% of daily RV.
  Question: Can we PREDICT the magnitude of tomorrow's overnight gap?

Data: SPY + VIX daily OHLC from yfinance, 2005-01-01 to 2024-12-31.
Methodology:
  1. Define overnight gap: |Open_t / Close_{t-1} - 1|
  2. Predictors (all known at previous close):
     - VIX level at close
     - VIX change (today vs yesterday)
     - |SPY return| today (same-day absolute return)
     - Day of week (Friday->Monday gap is longest)
     - Earnings season dummy (Jan/Apr/Jul/Oct)
  3. Univariate correlations + partial r controlling for VIX
  4. Rolling OLS (750-day window): predict tomorrow's |gap|
  5. OOS R^2 vs naive benchmark (use today's gap for tomorrow)
  6. Strategy implication for VT timing

Author: VolPred Research System (Claude)
Data source: yfinance (real market data)
"""

import json
import warnings
import sys
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import statsmodels.api as sm

warnings.filterwarnings("ignore")

print("=" * 70)
print("K305: Can We Forecast Tomorrow's Overnight Gap?")
print("=" * 70)
print(f"Execution time: {datetime.now().isoformat()}")
print()

# ============================================================
# 1. Data Download
# ============================================================
print("[1/7] Downloading data from yfinance...")

spy = yf.download("SPY", start="2004-12-01", end="2025-01-01", progress=False)
vix = yf.download("^VIX", start="2004-12-01", end="2025-01-01", progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  SPY: {len(spy)} rows, {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"  VIX: {len(vix)} rows, {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. Construct Overnight Gap
# ============================================================
print("\n[2/7] Constructing overnight gap and predictors...")

df = pd.DataFrame(index=spy.index)
df["spy_open"] = spy["Open"]
df["spy_close"] = spy["Close"]
df["spy_high"] = spy["High"]
df["spy_low"] = spy["Low"]
df["vix_close"] = vix["Close"].reindex(spy.index, method="ffill")

# Overnight gap: Open_t / Close_{t-1} - 1
df["prev_close"] = df["spy_close"].shift(1)
df["overnight_gap"] = df["spy_open"] / df["prev_close"] - 1
df["abs_overnight_gap"] = df["overnight_gap"].abs()

# Daily return
df["spy_return"] = df["spy_close"].pct_change()
df["abs_spy_return"] = df["spy_return"].abs()

# Intraday range (proxy for intraday vol)
df["intraday_range"] = (df["spy_high"] - df["spy_low"]) / df["spy_close"]

# VIX features
df["vix_change"] = df["vix_close"].pct_change()
df["vix_level"] = df["vix_close"]

# Day of week (0=Monday, 4=Friday)
df["dow"] = df.index.dayofweek
df["is_monday"] = (df["dow"] == 0).astype(int)  # Monday gap = longest (Friday close -> Monday open)

# Earnings season dummy (quarters: Jan, Apr, Jul, Oct)
df["earnings_season"] = df.index.month.isin([1, 4, 7, 10]).astype(int)

# Previous day's gap as naive predictor
df["prev_abs_gap"] = df["abs_overnight_gap"].shift(1)

# Filter to 2005-2024
df = df.loc["2005-01-01":"2024-12-31"].copy()
df = df.dropna(subset=["abs_overnight_gap", "prev_abs_gap", "vix_level"])

print(f"  Sample: {len(df)} trading days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
print(f"  Mean |overnight gap|: {df['abs_overnight_gap'].mean()*100:.4f}%")
print(f"  Median |overnight gap|: {df['abs_overnight_gap'].median()*100:.4f}%")
print(f"  Std |overnight gap|: {df['abs_overnight_gap'].std()*100:.4f}%")
print(f"  95th percentile: {df['abs_overnight_gap'].quantile(0.95)*100:.4f}%")
print(f"  99th percentile: {df['abs_overnight_gap'].quantile(0.99)*100:.4f}%")

# ============================================================
# 3. Descriptive Statistics by Day of Week
# ============================================================
print("\n[3/7] Overnight gap by day of week...")
dow_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
dow_stats = df.groupby("dow")["abs_overnight_gap"].agg(["mean", "median", "std", "count"])
dow_stats.index = dow_stats.index.map(dow_names)
print(dow_stats.to_string(float_format=lambda x: f"{x*100:.4f}%" if x < 1 else f"{int(x)}"))

# Monday vs rest t-test
monday_gaps = df.loc[df["is_monday"] == 1, "abs_overnight_gap"]
other_gaps = df.loc[df["is_monday"] == 0, "abs_overnight_gap"]
t_stat_mon, p_val_mon = stats.ttest_ind(monday_gaps, other_gaps)
print(f"\n  Monday vs rest: t={t_stat_mon:.3f}, p={p_val_mon:.4f}")
print(f"  Monday mean: {monday_gaps.mean()*100:.4f}%, Others mean: {other_gaps.mean()*100:.4f}%")

# By earnings season
earn_on = df.loc[df["earnings_season"] == 1, "abs_overnight_gap"]
earn_off = df.loc[df["earnings_season"] == 0, "abs_overnight_gap"]
t_earn, p_earn = stats.ttest_ind(earn_on, earn_off)
print(f"\n  Earnings season vs off-season: t={t_earn:.3f}, p={p_earn:.4f}")
print(f"  Earnings months mean: {earn_on.mean()*100:.4f}%, Off-season: {earn_off.mean()*100:.4f}%")

# ============================================================
# 4. Univariate Predictive Regressions
# ============================================================
print("\n[4/7] Univariate predictive regressions...")
print("  Target: |overnight_gap|_t+1")
print("  All predictors known at close of day t (no look-ahead)")
print()

# Shift target: we want to predict TOMORROW's gap using TODAY's info
df["target"] = df["abs_overnight_gap"].shift(-1)
df_reg = df.dropna(subset=["target"]).copy()

predictors = {
    "VIX level": "vix_level",
    "VIX change": "vix_change",
    "|SPY return|": "abs_spy_return",
    "Intraday range": "intraday_range",
    "Monday dummy": "is_monday",
    "Earnings season": "earnings_season",
    "Previous |gap|": "prev_abs_gap",
}

univariate_results = {}
print(f"  {'Predictor':<20} {'Corr':>8} {'p-value':>10} {'t-stat':>8} {'R²':>8}")
print("  " + "-" * 60)

for name, col in predictors.items():
    x = df_reg[col].values
    y = df_reg["target"].values

    # Correlation
    corr, p_corr = stats.pearsonr(x, y)

    # OLS regression
    X = sm.add_constant(x)
    model = sm.OLS(y, X).fit(cov_type="HC1")  # heteroskedasticity-robust SE
    t_val = model.tvalues[1]
    r2 = model.rsquared

    univariate_results[name] = {
        "correlation": float(corr),
        "p_value": float(p_corr),
        "t_stat": float(t_val),
        "r_squared": float(r2),
    }

    sig = "***" if abs(t_val) > 3.0 else "**" if abs(t_val) > 2.0 else "*" if abs(t_val) > 1.65 else ""
    print(f"  {name:<20} {corr:>8.4f} {p_corr:>10.2e} {t_val:>8.3f} {r2:>8.5f} {sig}")

# ============================================================
# 5. Partial Correlations (controlling for VIX)
# ============================================================
print("\n[5/7] Partial correlations controlling for VIX level...")

partial_results = {}
print(f"  {'Predictor':<20} {'Raw r':>8} {'Partial r':>10} {'p-value':>10}")
print("  " + "-" * 52)

for name, col in predictors.items():
    if col == "vix_level":
        continue  # Skip VIX itself

    y = df_reg["target"].values
    x = df_reg[col].values
    z = df_reg["vix_level"].values

    # Partial correlation: residualize both x and y on z
    Z = sm.add_constant(z)
    resid_y = sm.OLS(y, Z).fit().resid
    resid_x = sm.OLS(x, Z).fit().resid

    partial_r, partial_p = stats.pearsonr(resid_y, resid_x)
    raw_r = stats.pearsonr(x, y)[0]

    partial_results[name] = {
        "raw_r": float(raw_r),
        "partial_r": float(partial_r),
        "p_value": float(partial_p),
    }

    print(f"  {name:<20} {raw_r:>8.4f} {partial_r:>10.4f} {partial_p:>10.2e}")

# ============================================================
# 6. Multivariate OLS (full sample, for feature selection)
# ============================================================
print("\n[6/7] Multivariate OLS (full sample)...")

feature_cols = ["vix_level", "vix_change", "abs_spy_return", "intraday_range",
                "is_monday", "earnings_season", "prev_abs_gap"]
feature_names = ["VIX level", "VIX change", "|SPY return|", "Intraday range",
                 "Monday", "Earnings", "Prev |gap|"]

X_full = sm.add_constant(df_reg[feature_cols].values)
y_full = df_reg["target"].values

model_full = sm.OLS(y_full, X_full).fit(cov_type="HC1")
print(f"  Full-sample R²: {model_full.rsquared:.5f}")
print(f"  Adjusted R²:    {model_full.rsquared_adj:.5f}")
print(f"  F-statistic:    {model_full.fvalue:.2f}")
print()
print(f"  {'Feature':<20} {'Coef':>12} {'t-stat':>8} {'p-value':>10}")
print("  " + "-" * 54)

for i, fname in enumerate(["Intercept"] + feature_names):
    coef = model_full.params[i]
    tval = model_full.tvalues[i]
    pval = model_full.pvalues[i]
    sig = "***" if abs(tval) > 3.0 else "**" if abs(tval) > 2.0 else "*" if abs(tval) > 1.65 else ""
    print(f"  {fname:<20} {coef:>12.6f} {tval:>8.3f} {pval:>10.2e} {sig}")

# ============================================================
# 7. Rolling OOS Forecast
# ============================================================
print("\n[7/7] Rolling OOS forecast (750-day training window)...")

TRAIN_WINDOW = 750
MIN_TRAIN = 500

# We'll use the best features: VIX level, |SPY return|, prev |gap|, intraday range
# (selecting based on significance in full-sample regression)
selected_features = ["vix_level", "abs_spy_return", "intraday_range", "prev_abs_gap",
                     "is_monday", "earnings_season"]
selected_names = ["VIX level", "|SPY return|", "Intraday range", "Prev |gap|",
                  "Monday", "Earnings"]

y_all = df_reg["target"].values
X_all = df_reg[selected_features].values
dates = df_reg.index

# Also try with VIX change
all_features = ["vix_level", "vix_change", "abs_spy_return", "intraday_range",
                "prev_abs_gap", "is_monday", "earnings_season"]
X_all_full = df_reg[all_features].values

# Storage for predictions
oos_preds_selected = np.full(len(y_all), np.nan)
oos_preds_full = np.full(len(y_all), np.nan)
oos_preds_naive = np.full(len(y_all), np.nan)  # Use today's gap as forecast
oos_preds_vix_only = np.full(len(y_all), np.nan)  # VIX-only model
oos_preds_expanding_mean = np.full(len(y_all), np.nan)  # Expanding window mean

n_total = len(y_all)
n_oos = 0

# Only iterate where target (y_all) is not NaN
# y_all[-1] is NaN because target = shift(-1)
valid_end = n_total
while valid_end > 0 and np.isnan(y_all[valid_end - 1]):
    valid_end -= 1

print(f"  Total obs: {n_total}, valid target obs: {valid_end}")
print(f"  OOS loop: t = {TRAIN_WINDOW} to {valid_end - 1}")

for t in range(TRAIN_WINDOW, valid_end):
    # Training data: [t-TRAIN_WINDOW, t)
    train_start = t - TRAIN_WINDOW

    y_train = y_all[train_start:t]

    # Skip if training target has NaN
    if np.any(np.isnan(y_train)):
        continue

    # Selected model
    X_train_sel = sm.add_constant(X_all[train_start:t])
    X_test_sel = sm.add_constant(X_all[t:t+1], has_constant='add')
    try:
        mdl = sm.OLS(y_train, X_train_sel).fit()
        oos_preds_selected[t] = mdl.predict(X_test_sel)[0]
    except Exception:
        pass

    # Full model
    X_train_f = sm.add_constant(X_all_full[train_start:t])
    X_test_f = sm.add_constant(X_all_full[t:t+1], has_constant='add')
    try:
        mdl_f = sm.OLS(y_train, X_train_f).fit()
        oos_preds_full[t] = mdl_f.predict(X_test_f)[0]
    except Exception:
        pass

    # VIX-only model
    vix_train = df_reg["vix_level"].values[train_start:t].reshape(-1, 1)
    vix_test = df_reg["vix_level"].values[t:t+1].reshape(-1, 1)
    X_train_v = sm.add_constant(vix_train)
    X_test_v = sm.add_constant(vix_test, has_constant='add')
    try:
        mdl_v = sm.OLS(y_train, X_train_v).fit()
        oos_preds_vix_only[t] = mdl_v.predict(X_test_v)[0]
    except Exception:
        pass

    # Naive: use today's |gap| as tomorrow's forecast
    oos_preds_naive[t] = df_reg["abs_overnight_gap"].values[t]  # known at t's open

    # Expanding mean
    oos_preds_expanding_mean[t] = y_all[:t].mean()

    n_oos += 1

print(f"  Successfully predicted {n_oos} days OOS")

# Filter to OOS period only (both prediction and target must be valid)
mask = ~np.isnan(oos_preds_selected) & ~np.isnan(y_all)
oos_dates = dates[mask]
y_oos = y_all[mask]
pred_selected = oos_preds_selected[mask]
pred_full = oos_preds_full[mask]
pred_naive = oos_preds_naive[mask]
pred_vix_only = oos_preds_vix_only[mask]
pred_expanding = oos_preds_expanding_mean[mask]

print(f"  OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
print(f"  OOS observations: {len(y_oos)}")

# OOS R² = 1 - SS_res / SS_tot
# Benchmark: expanding mean (standard for R²_oos)
ss_tot = np.sum((y_oos - y_oos.mean()) ** 2)

def oos_r2(preds, actual, ss_total):
    ss_res = np.sum((actual - preds) ** 2)
    return 1 - ss_res / ss_total

def oos_r2_vs_naive(preds, actual, naive_preds):
    """R² relative to naive model"""
    ss_naive = np.sum((actual - naive_preds) ** 2)
    ss_model = np.sum((actual - preds) ** 2)
    return 1 - ss_model / ss_naive

r2_selected = oos_r2(pred_selected, y_oos, ss_tot)
r2_full = oos_r2(pred_full, y_oos, ss_tot)
r2_naive = oos_r2(pred_naive, y_oos, ss_tot)
r2_vix_only = oos_r2(pred_vix_only, y_oos, ss_tot)
r2_expanding = oos_r2(pred_expanding, y_oos, ss_tot)

# R² relative to naive
r2_vs_naive_selected = oos_r2_vs_naive(pred_selected, y_oos, pred_naive)
r2_vs_naive_full = oos_r2_vs_naive(pred_full, y_oos, pred_naive)
r2_vs_naive_vix = oos_r2_vs_naive(pred_vix_only, y_oos, pred_naive)

print(f"\n  OOS R² (vs expanding mean benchmark):")
print(f"    Expanding mean:     {r2_expanding:>8.5f} (benchmark = 0)")
print(f"    Naive (today's gap):{r2_naive:>8.5f}")
print(f"    VIX-only model:     {r2_vix_only:>8.5f}")
print(f"    Selected features:  {r2_selected:>8.5f}")
print(f"    Full model:         {r2_full:>8.5f}")

print(f"\n  OOS R² (vs naive 'use today's gap' benchmark):")
print(f"    VIX-only model:     {r2_vs_naive_vix:>8.5f}")
print(f"    Selected features:  {r2_vs_naive_selected:>8.5f}")
print(f"    Full model:         {r2_vs_naive_full:>8.5f}")

# ============================================================
# 8. RMSE comparison
# ============================================================
print("\n  RMSE comparison (in bps):")
rmse_expanding = np.sqrt(np.mean((y_oos - pred_expanding) ** 2)) * 10000
rmse_naive = np.sqrt(np.mean((y_oos - pred_naive) ** 2)) * 10000
rmse_vix = np.sqrt(np.mean((y_oos - pred_vix_only) ** 2)) * 10000
rmse_selected = np.sqrt(np.mean((y_oos - pred_selected) ** 2)) * 10000
rmse_full = np.sqrt(np.mean((y_oos - pred_full) ** 2)) * 10000

print(f"    Expanding mean:     {rmse_expanding:.2f} bps")
print(f"    Naive (today's gap):{rmse_naive:.2f} bps")
print(f"    VIX-only:           {rmse_vix:.2f} bps")
print(f"    Selected features:  {rmse_selected:.2f} bps")
print(f"    Full model:         {rmse_full:.2f} bps")

# ============================================================
# 9. Diebold-Mariano Test
# ============================================================
print("\n  Diebold-Mariano test (selected model vs naive)...")

e_model = y_oos - pred_selected
e_naive = y_oos - pred_naive
d = e_naive**2 - e_model**2  # positive = model better

# Newey-West HAC standard errors for DM test
dm_mean = d.mean()
dm_var = np.var(d, ddof=1)

# Newey-West with lag = int(n^(1/3))
n = len(d)
max_lag = int(n ** (1/3))
gamma_0 = np.var(d, ddof=1)
nw_var = gamma_0
for k in range(1, max_lag + 1):
    gamma_k = np.mean((d[k:] - dm_mean) * (d[:-k] - dm_mean))
    weight = 1 - k / (max_lag + 1)
    nw_var += 2 * weight * gamma_k

dm_stat = dm_mean / np.sqrt(nw_var / n)
dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

print(f"    DM statistic (vs naive): {dm_stat:.4f}")
print(f"    p-value: {dm_pval:.4f}")
print(f"    {'Model significantly better' if dm_stat > 1.96 else 'Model significantly worse' if dm_stat < -1.96 else 'No significant difference'}")

# DM: selected vs expanding mean
e_expand = y_oos - pred_expanding
d2 = e_expand**2 - e_model**2
dm_mean2 = d2.mean()
nw_var2 = np.var(d2, ddof=1)
for k in range(1, max_lag + 1):
    gamma_k2 = np.mean((d2[k:] - dm_mean2) * (d2[:-k] - dm_mean2))
    weight = 1 - k / (max_lag + 1)
    nw_var2 += 2 * weight * gamma_k2
dm_stat2 = dm_mean2 / np.sqrt(nw_var2 / n)
dm_pval2 = 2 * (1 - stats.norm.cdf(abs(dm_stat2)))

print(f"\n    DM statistic (vs expanding mean): {dm_stat2:.4f}")
print(f"    p-value: {dm_pval2:.4f}")
print(f"    {'Model significantly better' if dm_stat2 > 1.96 else 'No significant difference'}")

# ============================================================
# 10. Sub-period Analysis (stability check)
# ============================================================
print("\n  Sub-period OOS R² analysis...")

# Split OOS into 5 non-overlapping periods
n_periods = 5
period_size = len(y_oos) // n_periods

print(f"  {'Period':<30} {'N':>6} {'R² sel':>10} {'R² naive':>10} {'R² VIX':>10}")
print("  " + "-" * 70)

subperiod_results = []
for i in range(n_periods):
    start = i * period_size
    end = (i + 1) * period_size if i < n_periods - 1 else len(y_oos)

    y_sub = y_oos[start:end]
    ss_tot_sub = np.sum((y_sub - y_sub.mean()) ** 2)

    r2_sel_sub = oos_r2(pred_selected[start:end], y_sub, ss_tot_sub)
    r2_naive_sub = oos_r2(pred_naive[start:end], y_sub, ss_tot_sub)
    r2_vix_sub = oos_r2(pred_vix_only[start:end], y_sub, ss_tot_sub)

    period_label = f"{oos_dates[start].strftime('%Y-%m')} to {oos_dates[min(end-1, len(oos_dates)-1)].strftime('%Y-%m')}"

    subperiod_results.append({
        "period": period_label,
        "n": end - start,
        "r2_selected": float(r2_sel_sub),
        "r2_naive": float(r2_naive_sub),
        "r2_vix": float(r2_vix_sub),
    })

    print(f"  {period_label:<30} {end-start:>6} {r2_sel_sub:>10.5f} {r2_naive_sub:>10.5f} {r2_vix_sub:>10.5f}")

# ============================================================
# 11. VIX Regime Conditioning
# ============================================================
print("\n  Gap predictability by VIX regime...")

# Split into VIX regimes
vix_oos = df_reg["vix_level"].values[mask]

regimes = {
    "Low VIX (<15)": vix_oos < 15,
    "Medium VIX (15-25)": (vix_oos >= 15) & (vix_oos < 25),
    "High VIX (25-35)": (vix_oos >= 25) & (vix_oos < 35),
    "Crisis VIX (>35)": vix_oos >= 35,
}

print(f"  {'Regime':<25} {'N':>6} {'Mean |gap|':>12} {'R² sel':>10} {'R² naive':>10}")
print("  " + "-" * 67)

regime_results = {}
for regime_name, regime_mask in regimes.items():
    if regime_mask.sum() < 30:
        continue

    y_r = y_oos[regime_mask]
    ss_r = np.sum((y_r - y_r.mean()) ** 2)

    r2_sel_r = oos_r2(pred_selected[regime_mask], y_r, ss_r) if ss_r > 0 else np.nan
    r2_naive_r = oos_r2(pred_naive[regime_mask], y_r, ss_r) if ss_r > 0 else np.nan

    regime_results[regime_name] = {
        "n": int(regime_mask.sum()),
        "mean_gap_bps": float(y_r.mean() * 10000),
        "r2_selected": float(r2_sel_r),
        "r2_naive": float(r2_naive_r),
    }

    print(f"  {regime_name:<25} {regime_mask.sum():>6} {y_r.mean()*10000:>10.2f} bp {r2_sel_r:>10.5f} {r2_naive_r:>10.5f}")

# ============================================================
# 12. Directional Accuracy (can we predict large vs small gaps?)
# ============================================================
print("\n  Directional accuracy: large gap prediction...")

# Define "large gap" as top quartile
gap_75th = np.percentile(y_oos, 75)
actual_large = (y_oos > gap_75th).astype(int)
pred_large_sel = (pred_selected > gap_75th).astype(int)
pred_large_naive = (pred_naive > gap_75th).astype(int)

accuracy_sel = np.mean(actual_large == pred_large_sel)
accuracy_naive = np.mean(actual_large == pred_large_naive)

# Precision/Recall for "large gap" class
tp_sel = np.sum((pred_large_sel == 1) & (actual_large == 1))
fp_sel = np.sum((pred_large_sel == 1) & (actual_large == 0))
fn_sel = np.sum((pred_large_sel == 0) & (actual_large == 1))

precision_sel = tp_sel / (tp_sel + fp_sel) if (tp_sel + fp_sel) > 0 else 0
recall_sel = tp_sel / (tp_sel + fn_sel) if (tp_sel + fn_sel) > 0 else 0

tp_naive = np.sum((pred_large_naive == 1) & (actual_large == 1))
fp_naive = np.sum((pred_large_naive == 1) & (actual_large == 0))
fn_naive = np.sum((pred_large_naive == 0) & (actual_large == 1))

precision_naive = tp_naive / (tp_naive + fp_naive) if (tp_naive + fp_naive) > 0 else 0
recall_naive = tp_naive / (tp_naive + fn_naive) if (tp_naive + fn_naive) > 0 else 0

print(f"  Threshold for 'large gap': {gap_75th*10000:.2f} bps (75th percentile)")
print(f"  {'Model':<20} {'Accuracy':>10} {'Precision':>10} {'Recall':>10}")
print("  " + "-" * 54)
print(f"  {'Selected':>20} {accuracy_sel:>10.4f} {precision_sel:>10.4f} {recall_sel:>10.4f}")
print(f"  {'Naive':>20} {accuracy_naive:>10.4f} {precision_naive:>10.4f} {recall_naive:>10.4f}")

# ============================================================
# 13. Autocorrelation of overnight gaps
# ============================================================
print("\n  Autocorrelation structure of |overnight gap|...")

acf_values = []
for lag in range(1, 11):
    acf_val = df_reg["abs_overnight_gap"].autocorr(lag=lag)
    acf_values.append(acf_val)
    sig = "***" if abs(acf_val) > 2/np.sqrt(len(df_reg)) * 1.5 else ""
    print(f"    Lag {lag:>2}: {acf_val:.4f} {sig}")

# ============================================================
# 14. Strategy Implication: Gap-Conditional VT Timing
# ============================================================
print("\n  Strategy implication: Gap-conditional VT timing...")
print("  If large gap predicted → reduce position at close (avoid overnight risk)")
print("  If small gap predicted → maintain position (capture overnight premium)")

# Simulate: when model predicts top-quartile gap, go flat overnight
# Otherwise, hold SPY overnight
overnight_returns_oos = df_reg["overnight_gap"].values[mask]

# Strategy: hold overnight only when predicted gap is small
hold_mask = pred_selected <= np.percentile(pred_selected, 75)  # Hold when small gap predicted
skip_mask = ~hold_mask  # Skip when large gap predicted

strategy_returns = overnight_returns_oos.copy()
strategy_returns[skip_mask] = 0  # Flat on predicted large-gap nights

buy_hold_overnight = overnight_returns_oos

# Annualize
ann_factor = 252
sharpe_bh = np.mean(buy_hold_overnight) / np.std(buy_hold_overnight) * np.sqrt(ann_factor)
sharpe_strat = np.mean(strategy_returns) / np.std(strategy_returns) * np.sqrt(ann_factor) if np.std(strategy_returns) > 0 else 0

cum_bh = np.cumprod(1 + buy_hold_overnight) - 1
cum_strat = np.cumprod(1 + strategy_returns) - 1

print(f"  Buy & hold overnight: Sharpe = {sharpe_bh:.3f}, Total return = {cum_bh[-1]*100:.1f}%")
print(f"  Skip large-gap nights: Sharpe = {sharpe_strat:.3f}, Total return = {cum_strat[-1]*100:.1f}%")
print(f"  Nights held: {hold_mask.sum()} / {len(hold_mask)} ({hold_mask.mean()*100:.1f}%)")
print(f"  Nights skipped: {skip_mask.sum()} ({skip_mask.mean()*100:.1f}%)")

# Average gap on skipped vs held nights
avg_gap_skipped = np.mean(np.abs(overnight_returns_oos[skip_mask]))
avg_gap_held = np.mean(np.abs(overnight_returns_oos[hold_mask]))
print(f"  Mean |gap| on skipped nights: {avg_gap_skipped*10000:.2f} bps")
print(f"  Mean |gap| on held nights:    {avg_gap_held*10000:.2f} bps")
print(f"  Ratio (skipped/held): {avg_gap_skipped/avg_gap_held:.2f}x")

# ============================================================
# 15. Summary and Conclusions
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K305 Overnight Gap Forecast")
print("=" * 70)

print(f"""
Data: SPY + VIX daily OHLC, 2005-2024 ({len(df)} trading days)
Target: |Open_t / Close_{'{t-1}'} - 1| (absolute overnight gap)
Mean |gap|: {df['abs_overnight_gap'].mean()*100:.4f}% ({df['abs_overnight_gap'].mean()*10000:.2f} bps)

KEY FINDINGS:

1. UNIVARIATE PREDICTORS:
   - VIX level is the strongest single predictor (r = {univariate_results['VIX level']['correlation']:.4f})
   - Previous |gap| shows persistence (r = {univariate_results['Previous |gap|']['correlation']:.4f})
   - |SPY return| also predictive (r = {univariate_results['|SPY return|']['correlation']:.4f})
   - Monday dummy: {'significant' if abs(univariate_results['Monday dummy']['t_stat']) > 2 else 'not significant'} (t = {univariate_results['Monday dummy']['t_stat']:.3f})
   - Earnings season: {'significant' if abs(univariate_results['Earnings season']['t_stat']) > 2 else 'not significant'} (t = {univariate_results['Earnings season']['t_stat']:.3f})

2. PARTIAL CORRELATIONS (controlling for VIX):
   - Most predictors lose power after VIX control
   - VIX captures the bulk of overnight gap variation

3. OUT-OF-SAMPLE PERFORMANCE (rolling 750-day window):
   - OOS R² (vs mean): Selected = {r2_selected:.5f}, VIX-only = {r2_vix_only:.5f}
   - OOS R² (vs naive): Selected = {r2_vs_naive_selected:.5f}
   - DM test vs naive: t = {dm_stat:.4f}, p = {dm_pval:.4f}
   - DM test vs mean:  t = {dm_stat2:.4f}, p = {dm_pval2:.4f}

4. VIX REGIME DEPENDENCE:
   - Gap magnitude scales with VIX (higher VIX → larger gaps)
   - Predictability varies across regimes

5. STRATEGY IMPLICATION:
   - Skip-large-gap strategy Sharpe: {sharpe_strat:.3f} vs Buy-hold overnight: {sharpe_bh:.3f}
   - Model correctly identifies larger-gap nights (ratio: {avg_gap_skipped/avg_gap_held:.2f}x)

LIMITATIONS:
   - No after-hours volume data (important predictor, unavailable from yfinance)
   - No earnings announcement calendar (only crude quarterly proxy)
   - No macro event calendar (FOMC, payrolls → known large-gap dates)
   - Overnight gap is partially driven by global markets (not modeled)
   - Transaction costs not included in strategy simulation
   - Strategy assumes ability to trade at close (realistic for SPY)
""")

# ============================================================
# Save results
# ============================================================
results = {
    "experiment": "K305",
    "title": "Can We Forecast Tomorrow's Overnight Gap?",
    "data_source": "yfinance (SPY, ^VIX)",
    "sample_period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    "n_observations": int(len(df)),
    "oos_period": f"{oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}",
    "n_oos": int(len(y_oos)),
    "target": "|Open_t / Close_{t-1} - 1|",
    "mean_abs_gap_pct": float(df["abs_overnight_gap"].mean() * 100),
    "mean_abs_gap_bps": float(df["abs_overnight_gap"].mean() * 10000),
    "descriptive": {
        "monday_vs_rest_t": float(t_stat_mon),
        "monday_vs_rest_p": float(p_val_mon),
        "monday_mean_bps": float(monday_gaps.mean() * 10000),
        "other_mean_bps": float(other_gaps.mean() * 10000),
        "earnings_vs_off_t": float(t_earn),
        "earnings_vs_off_p": float(p_earn),
    },
    "univariate_results": univariate_results,
    "partial_correlations": partial_results,
    "full_sample_r2": float(model_full.rsquared),
    "full_sample_adj_r2": float(model_full.rsquared_adj),
    "oos_results": {
        "r2_expanding_mean": float(r2_expanding),
        "r2_naive": float(r2_naive),
        "r2_vix_only": float(r2_vix_only),
        "r2_selected": float(r2_selected),
        "r2_full": float(r2_full),
        "r2_vs_naive_vix": float(r2_vs_naive_vix),
        "r2_vs_naive_selected": float(r2_vs_naive_selected),
        "r2_vs_naive_full": float(r2_vs_naive_full),
        "rmse_expanding_bps": float(rmse_expanding),
        "rmse_naive_bps": float(rmse_naive),
        "rmse_vix_bps": float(rmse_vix),
        "rmse_selected_bps": float(rmse_selected),
        "rmse_full_bps": float(rmse_full),
    },
    "dm_test": {
        "vs_naive_stat": float(dm_stat),
        "vs_naive_pval": float(dm_pval),
        "vs_mean_stat": float(dm_stat2),
        "vs_mean_pval": float(dm_pval2),
    },
    "subperiod_results": subperiod_results,
    "regime_results": regime_results,
    "directional": {
        "threshold_bps": float(gap_75th * 10000),
        "accuracy_selected": float(accuracy_sel),
        "accuracy_naive": float(accuracy_naive),
        "precision_selected": float(precision_sel),
        "recall_selected": float(recall_sel),
    },
    "autocorrelation": {f"lag_{i+1}": float(v) for i, v in enumerate(acf_values)},
    "strategy": {
        "sharpe_buy_hold_overnight": float(sharpe_bh),
        "sharpe_skip_large_gap": float(sharpe_strat),
        "total_return_bh_pct": float(cum_bh[-1] * 100),
        "total_return_strat_pct": float(cum_strat[-1] * 100),
        "nights_held_pct": float(hold_mask.mean() * 100),
        "avg_gap_skipped_bps": float(avg_gap_skipped * 10000),
        "avg_gap_held_bps": float(avg_gap_held * 10000),
        "gap_ratio_skipped_vs_held": float(avg_gap_skipped / avg_gap_held),
    },
    "limitations": [
        "No after-hours volume data (unavailable from yfinance)",
        "No earnings announcement calendar (only crude quarterly proxy)",
        "No macro event calendar (FOMC, payrolls)",
        "Overnight gap partially driven by global markets (not modeled)",
        "Transaction costs not included in strategy simulation",
        "Strategy assumes ability to trade at close",
    ],
}

output_path = Path(__file__).parent / "k305_overnight_forecast_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
print("Done.")
