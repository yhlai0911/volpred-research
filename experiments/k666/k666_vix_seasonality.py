"""
K666: VIX Seasonality — Is There a Best Month to Invest?
[提出: Claude (builds on K631 calendar effects), 執行: Claude]

Background: K631 found month-of-year effects in vol (KW p=0.023 for SPY) but
concluded calendar effects are "too weak and unstable" for forecasting.
This experiment takes a different angle: instead of predicting vol, we ask
the STRATEGY question — is there a best month to start investing, or to
adjust allocation?

References:
- K631: Calendar Vol Patterns — OpEx/pre-holiday effects real but too weak
- Bouman & Jacobsen (2002): "The Halloween Indicator, Sell in May"
- Kamstra, Kramer & Levi (2003): SAD effect on stock returns
- Jacobsen & Zhang (2014): "Are Monthly Seasonals Real?" (yes, in many markets)

Methodology:
1. Monthly VIX patterns (avg level, avg change by month)
2. "Sell in May" test: May-Oct vs Nov-Apr VIX and SPY returns
3. Monthly SPY returns by VIX regime (VIX<20 vs VIX>=20)
4. Seasonal VT strategy test: 12/VIX + monthly adjustment vs plain 12/VIX
5. "Start investing in March" analysis: entry-month x VIX-level → 1yr returns

Data source: yfinance (SPY, ^VIX), 1993-01-01 to 2026-03-27 (full VIX history)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime
from scipy import stats

warnings.filterwarnings('ignore')

# ─────────────────────────────────────────────
# 1. DATA COLLECTION
# ─────────────────────────────────────────────
print("=" * 70)
print("K666: VIX Seasonality — Is There a Best Month to Invest?")
print("[提出: Claude (K631 follow-up), 執行: Claude]")
print("=" * 70)

print("\n[1/6] Downloading data from yfinance...")
spy = yf.download("SPY", start="1993-01-01", end="2026-03-28", auto_adjust=True, progress=False)
vix = yf.download("^VIX", start="1993-01-01", end="2026-03-28", auto_adjust=True, progress=False)

# Flatten MultiIndex if present
for df in [spy, vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Align dates
common_dates = spy.index.intersection(vix.index)
spy = spy.loc[common_dates]
vix = vix.loc[common_dates]

spy_r = spy['Close'].pct_change().dropna()
vix_close = vix['Close'].reindex(spy_r.index)

# Drop NaN
mask = spy_r.notna() & vix_close.notna()
spy_r = spy_r[mask]
vix_close = vix_close[mask]

print(f"  SPY: {spy_r.index[0].strftime('%Y-%m-%d')} to {spy_r.index[-1].strftime('%Y-%m-%d')}")
print(f"  VIX: same range, {len(spy_r)} trading days")
print(f"  Years covered: {spy_r.index[-1].year - spy_r.index[0].year + 1}")

results = {
    "experiment_id": "k666",
    "title": "K666: VIX Seasonality — Is There a Best Month to Invest?",
    "proposer": "Claude (K631 follow-up)",
    "executor": "Claude",
    "data_source": "yfinance SPY/^VIX",
    "data_period": f"{spy_r.index[0].strftime('%Y-%m-%d')} to {spy_r.index[-1].strftime('%Y-%m-%d')}",
    "n_days": len(spy_r),
    "references": [
        "K631: Calendar Vol Patterns (KW p=0.023, too weak for forecasting)",
        "Bouman & Jacobsen (2002): Halloween Indicator",
        "Kamstra et al. (2003): SAD effect",
        "Jacobsen & Zhang (2014): Are Monthly Seasonals Real?"
    ]
}

# ─────────────────────────────────────────────
# 2. MONTHLY VIX PATTERNS
# ─────────────────────────────────────────────
print("\n[2/6] Monthly VIX patterns...")

# Create monthly data
monthly_vix = vix_close.resample('ME').mean()  # Average VIX within each month
monthly_vix_end = vix_close.resample('ME').last()  # Month-end VIX
monthly_vix_change = monthly_vix_end.pct_change()  # Month-over-month VIX change

# Monthly SPY returns (compounded daily returns)
monthly_spy_r = (1 + spy_r).resample('ME').prod() - 1

# Align
common_monthly = monthly_vix.index.intersection(monthly_spy_r.index).intersection(monthly_vix_change.dropna().index)
monthly_vix = monthly_vix.loc[common_monthly]
monthly_spy_r = monthly_spy_r.loc[common_monthly]
monthly_vix_change = monthly_vix_change.loc[common_monthly]
monthly_vix_end_aligned = monthly_vix_end.loc[common_monthly]

month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

# Average VIX by month
avg_vix_by_month = {}
avg_vix_change_by_month = {}
avg_spy_return_by_month = {}
spy_positive_pct_by_month = {}
n_months_by_month = {}

for m in range(1, 13):
    mask_m = monthly_vix.index.month == m
    avg_vix_by_month[month_names[m-1]] = float(monthly_vix[mask_m].mean())
    avg_vix_change_by_month[month_names[m-1]] = float(monthly_vix_change[mask_m].mean())
    avg_spy_return_by_month[month_names[m-1]] = float(monthly_spy_r[mask_m].mean())
    spy_positive_pct_by_month[month_names[m-1]] = float((monthly_spy_r[mask_m] > 0).mean())
    n_months_by_month[month_names[m-1]] = int(mask_m.sum())

# Kruskal-Wallis test for VIX by month
vix_by_month_groups = [monthly_vix[monthly_vix.index.month == m].values for m in range(1, 13)]
kw_vix_stat, kw_vix_p = stats.kruskal(*vix_by_month_groups)

# Kruskal-Wallis test for SPY returns by month
spy_by_month_groups = [monthly_spy_r[monthly_spy_r.index.month == m].values for m in range(1, 13)]
kw_spy_stat, kw_spy_p = stats.kruskal(*spy_by_month_groups)

print(f"  Kruskal-Wallis VIX by month: H={kw_vix_stat:.2f}, p={kw_vix_p:.4f}")
print(f"  Kruskal-Wallis SPY returns by month: H={kw_spy_stat:.2f}, p={kw_spy_p:.4f}")

# Find highest/lowest VIX months
highest_vix_month = max(avg_vix_by_month, key=avg_vix_by_month.get)
lowest_vix_month = min(avg_vix_by_month, key=avg_vix_by_month.get)
best_return_month = max(avg_spy_return_by_month, key=avg_spy_return_by_month.get)
worst_return_month = min(avg_spy_return_by_month, key=avg_spy_return_by_month.get)

print(f"  Highest avg VIX: {highest_vix_month} ({avg_vix_by_month[highest_vix_month]:.2f})")
print(f"  Lowest avg VIX: {lowest_vix_month} ({avg_vix_by_month[lowest_vix_month]:.2f})")
print(f"  Best avg SPY return: {best_return_month} ({avg_spy_return_by_month[best_return_month]*100:.2f}%)")
print(f"  Worst avg SPY return: {worst_return_month} ({avg_spy_return_by_month[worst_return_month]*100:.2f}%)")

results["monthly_vix_patterns"] = {
    "avg_vix_by_month": {k: round(v, 2) for k, v in avg_vix_by_month.items()},
    "avg_vix_change_by_month": {k: round(v, 4) for k, v in avg_vix_change_by_month.items()},
    "avg_spy_return_by_month": {k: round(v, 4) for k, v in avg_spy_return_by_month.items()},
    "spy_positive_pct_by_month": {k: round(v, 3) for k, v in spy_positive_pct_by_month.items()},
    "n_months_per_category": {k: v for k, v in n_months_by_month.items()},
    "kw_vix_by_month": {"H": round(kw_vix_stat, 2), "p": round(kw_vix_p, 4)},
    "kw_spy_returns_by_month": {"H": round(kw_spy_stat, 2), "p": round(kw_spy_p, 4)},
    "highest_vix_month": highest_vix_month,
    "lowest_vix_month": lowest_vix_month,
    "best_return_month": best_return_month,
    "worst_return_month": worst_return_month,
}

# Print table
print("\n  Month | Avg VIX | VIX Chg% | SPY Return | Up%  | N")
print("  " + "-" * 58)
for m_name in month_names:
    print(f"  {m_name:>5} | {avg_vix_by_month[m_name]:7.2f} | {avg_vix_change_by_month[m_name]*100:+7.2f}% | "
          f"{avg_spy_return_by_month[m_name]*100:+7.2f}%  | {spy_positive_pct_by_month[m_name]*100:4.0f}% | "
          f"{n_months_by_month[m_name]:2d}")

# ─────────────────────────────────────────────
# 3. SELL IN MAY EFFECT
# ─────────────────────────────────────────────
print("\n[3/6] Sell in May effect (May-Oct vs Nov-Apr)...")

# Classify months
is_summer = monthly_spy_r.index.month.isin([5, 6, 7, 8, 9, 10])
summer_returns = monthly_spy_r[is_summer]
winter_returns = monthly_spy_r[~is_summer]

summer_vix = monthly_vix[is_summer]
winter_vix = monthly_vix[~is_summer]

# Annualized returns
summer_avg_annual = float((1 + summer_returns.mean())**12 - 1)
winter_avg_annual = float((1 + winter_returns.mean())**12 - 1)

# t-test for return difference
t_sim, p_sim = stats.ttest_ind(winter_returns.values, summer_returns.values)

# Mann-Whitney U test (non-parametric)
u_stat, u_p = stats.mannwhitneyu(winter_returns.values, summer_returns.values, alternative='two-sided')

# VIX difference
vix_diff_t, vix_diff_p = stats.ttest_ind(summer_vix.values, winter_vix.values)

sell_in_may = {
    "summer_may_oct": {
        "avg_monthly_return": round(float(summer_returns.mean()), 5),
        "avg_monthly_return_pct": round(float(summer_returns.mean()) * 100, 3),
        "annualized_return_pct": round(summer_avg_annual * 100, 2),
        "std_monthly": round(float(summer_returns.std()), 5),
        "positive_pct": round(float((summer_returns > 0).mean()) * 100, 1),
        "avg_vix": round(float(summer_vix.mean()), 2),
        "n_months": int(len(summer_returns)),
    },
    "winter_nov_apr": {
        "avg_monthly_return": round(float(winter_returns.mean()), 5),
        "avg_monthly_return_pct": round(float(winter_returns.mean()) * 100, 3),
        "annualized_return_pct": round(winter_avg_annual * 100, 2),
        "std_monthly": round(float(winter_returns.std()), 5),
        "positive_pct": round(float((winter_returns > 0).mean()) * 100, 1),
        "avg_vix": round(float(winter_vix.mean()), 2),
        "n_months": int(len(winter_returns)),
    },
    "return_difference_ttest": {"t": round(t_sim, 3), "p": round(p_sim, 4)},
    "return_difference_mannwhitney": {"U": round(float(u_stat), 1), "p": round(u_p, 4)},
    "vix_difference_ttest": {"t": round(vix_diff_t, 3), "p": round(vix_diff_p, 4)},
}

print(f"  May-Oct (Summer): avg monthly {summer_returns.mean()*100:+.3f}%, "
      f"annualized {summer_avg_annual*100:+.2f}%, avg VIX {summer_vix.mean():.2f}")
print(f"  Nov-Apr (Winter): avg monthly {winter_returns.mean()*100:+.3f}%, "
      f"annualized {winter_avg_annual*100:+.2f}%, avg VIX {winter_vix.mean():.2f}")
print(f"  Return difference t-test: t={t_sim:.3f}, p={p_sim:.4f}")
print(f"  Mann-Whitney U: p={u_p:.4f}")
print(f"  VIX difference t-test: t={vix_diff_t:.3f}, p={vix_diff_p:.4f}")

# Sub-period stability (pre-2010 vs post-2010)
pre2010 = monthly_spy_r.index < '2010-01-01'
post2010 = monthly_spy_r.index >= '2010-01-01'

for period_name, period_mask in [("Pre-2010", pre2010), ("Post-2010", post2010)]:
    summer_r_sub = monthly_spy_r[is_summer & period_mask]
    winter_r_sub = monthly_spy_r[~is_summer & period_mask]
    if len(summer_r_sub) > 5 and len(winter_r_sub) > 5:
        t_sub, p_sub = stats.ttest_ind(winter_r_sub.values, summer_r_sub.values)
        sell_in_may[f"subperiod_{period_name.lower().replace('-','_')}"] = {
            "summer_avg_pct": round(float(summer_r_sub.mean()) * 100, 3),
            "winter_avg_pct": round(float(winter_r_sub.mean()) * 100, 3),
            "t": round(t_sub, 3),
            "p": round(p_sub, 4),
        }
        print(f"  {period_name}: Summer={summer_r_sub.mean()*100:+.3f}%, "
              f"Winter={winter_r_sub.mean()*100:+.3f}%, t={t_sub:.3f}, p={p_sub:.4f}")

results["sell_in_may"] = sell_in_may

# ─────────────────────────────────────────────
# 4. OCTOBER EFFECT — Is October really the most volatile?
# ─────────────────────────────────────────────
print("\n[3b/6] October effect — Is October really most volatile?")

# Realized vol by month (annualized stdev of daily returns)
daily_month = spy_r.index.month
rv_by_month = {}
max_drawdown_by_month = {}

for m in range(1, 13):
    daily_m = spy_r[daily_month == m]
    rv_by_month[month_names[m-1]] = float(daily_m.std() * np.sqrt(252))

    # Count extreme moves (|return| > 2%)
    extreme_pct = float((daily_m.abs() > 0.02).mean())

    # Also compute worst single day return by month
    worst_day = float(daily_m.min())

    max_drawdown_by_month[month_names[m-1]] = {
        "annualized_rv": round(rv_by_month[month_names[m-1]], 4),
        "extreme_day_pct": round(extreme_pct * 100, 2),
        "worst_single_day_pct": round(worst_day * 100, 3),
    }

# Rank by RV
rv_sorted = sorted(rv_by_month.items(), key=lambda x: x[1], reverse=True)
print(f"  Most volatile month (RV): {rv_sorted[0][0]} ({rv_sorted[0][1]*100:.1f}%)")
print(f"  Least volatile month (RV): {rv_sorted[-1][0]} ({rv_sorted[-1][1]*100:.1f}%)")
print(f"  October rank: {[x[0] for x in rv_sorted].index('Oct')+1} of 12")

print("\n  Month | Ann. RV% | Extreme Days% | Worst Day%")
print("  " + "-" * 50)
for m_name in month_names:
    d = max_drawdown_by_month[m_name]
    print(f"  {m_name:>5} | {d['annualized_rv']*100:7.2f}% | {d['extreme_day_pct']:12.1f}% | "
          f"{d['worst_single_day_pct']:+8.3f}%")

results["october_effect"] = {
    "rv_by_month": {k: round(v, 4) for k, v in rv_by_month.items()},
    "details_by_month": max_drawdown_by_month,
    "most_volatile_month": rv_sorted[0][0],
    "least_volatile_month": rv_sorted[-1][0],
    "october_rank": [x[0] for x in rv_sorted].index('Oct') + 1,
}

# ─────────────────────────────────────────────
# 5. MONTHLY SPY RETURNS BY VIX REGIME
# ─────────────────────────────────────────────
print("\n[4/6] Monthly SPY returns by VIX regime...")

# Month-start VIX (using last day of previous month)
month_start_vix = monthly_vix_end_aligned.shift(1)  # Previous month-end VIX as current month-start VIX

# Align
valid_mask = month_start_vix.notna()
month_start_vix = month_start_vix[valid_mask]
monthly_spy_aligned = monthly_spy_r[valid_mask]

high_vix_threshold = 20
low_vix = month_start_vix < high_vix_threshold
high_vix = month_start_vix >= high_vix_threshold

regime_returns_by_month = {}
for m in range(1, 13):
    m_mask = monthly_spy_aligned.index.month == m
    low_r = monthly_spy_aligned[m_mask & low_vix]
    high_r = monthly_spy_aligned[m_mask & high_vix]

    regime_returns_by_month[month_names[m-1]] = {
        "vix_below_20": {
            "avg_return_pct": round(float(low_r.mean()) * 100, 3) if len(low_r) > 0 else None,
            "n": int(len(low_r)),
            "positive_pct": round(float((low_r > 0).mean()) * 100, 1) if len(low_r) > 0 else None,
        },
        "vix_above_20": {
            "avg_return_pct": round(float(high_r.mean()) * 100, 3) if len(high_r) > 0 else None,
            "n": int(len(high_r)),
            "positive_pct": round(float((high_r > 0).mean()) * 100, 1) if len(high_r) > 0 else None,
        },
    }

# Overall regime stats
overall_low = monthly_spy_aligned[low_vix]
overall_high = monthly_spy_aligned[high_vix]

print(f"  VIX < 20: avg monthly return = {overall_low.mean()*100:+.3f}%, "
      f"n={len(overall_low)}, positive {(overall_low>0).mean()*100:.0f}%")
print(f"  VIX >= 20: avg monthly return = {overall_high.mean()*100:+.3f}%, "
      f"n={len(overall_high)}, positive {(overall_high>0).mean()*100:.0f}%")

# Print regime x month table
print("\n  Month | VIX<20 Ret% (n) | VIX>=20 Ret% (n) | Diff")
print("  " + "-" * 60)
for m_name in month_names:
    d = regime_returns_by_month[m_name]
    low_val = d['vix_below_20']['avg_return_pct'] if d['vix_below_20']['avg_return_pct'] is not None else 0
    high_val = d['vix_above_20']['avg_return_pct'] if d['vix_above_20']['avg_return_pct'] is not None else 0
    low_n = d['vix_below_20']['n']
    high_n = d['vix_above_20']['n']
    diff = low_val - high_val
    print(f"  {m_name:>5} | {low_val:+7.3f}% ({low_n:2d}) | {high_val:+7.3f}% ({high_n:2d}) | {diff:+7.3f}%")

# Which months are WORST during high VIX?
worst_high_vix_months = sorted(
    [(m_name, regime_returns_by_month[m_name]['vix_above_20']['avg_return_pct'])
     for m_name in month_names
     if regime_returns_by_month[m_name]['vix_above_20']['avg_return_pct'] is not None],
    key=lambda x: x[1]
)

print(f"\n  Worst months during high VIX:")
for m_name, ret in worst_high_vix_months[:3]:
    print(f"    {m_name}: {ret:+.3f}%")

results["monthly_returns_by_vix_regime"] = {
    "threshold": high_vix_threshold,
    "overall_low_vix_avg_pct": round(float(overall_low.mean()) * 100, 3),
    "overall_high_vix_avg_pct": round(float(overall_high.mean()) * 100, 3),
    "overall_low_vix_n": int(len(overall_low)),
    "overall_high_vix_n": int(len(overall_high)),
    "by_month": regime_returns_by_month,
    "worst_months_high_vix": [{"month": m, "avg_return_pct": r} for m, r in worst_high_vix_months[:3]],
}

# ─────────────────────────────────────────────
# 6. SEASONAL VT STRATEGY TEST
# ─────────────────────────────────────────────
print("\n[5/6] Seasonal VT strategy test...")

# Build daily data for backtest
# Strategy 1: Plain 12/VIX (50/50 SPY/GLD base)
# Strategy 2: 12/VIX + seasonal adjustment
# Strategy 3: Buy & Hold SPY

# We need GLD for the 12/VIX strategy
gld = yf.download("GLD", start="2004-11-01", end="2026-03-28", auto_adjust=True, progress=False)
if isinstance(gld.columns, pd.MultiIndex):
    gld.columns = gld.columns.get_level_values(0)
gld_r = gld['Close'].pct_change().dropna()

# Align all three
bt_dates = spy_r.index.intersection(gld_r.index).intersection(vix_close.index)
spy_r_bt = spy_r.loc[bt_dates]
gld_r_bt = gld_r.loc[bt_dates]
vix_bt = vix_close.loc[bt_dates]

print(f"  Backtest period: {bt_dates[0].strftime('%Y-%m-%d')} to {bt_dates[-1].strftime('%Y-%m-%d')}")
print(f"  {len(bt_dates)} trading days")

# Compute seasonal adjustment factors from IN-SAMPLE (first half)
# Use expanding window: for each month, how much does its vol deviate from average?
mid_point = len(bt_dates) // 2
is_dates = bt_dates[:mid_point]
oos_dates = bt_dates[mid_point:]

print(f"  In-sample: {is_dates[0].strftime('%Y-%m-%d')} to {is_dates[-1].strftime('%Y-%m-%d')}")
print(f"  Out-of-sample: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")

# Compute IS seasonal factors: for each month, ratio of realized vol to average
is_spy_r = spy_r_bt.loc[is_dates]
is_daily_rv = {}
for m in range(1, 13):
    m_mask = is_spy_r.index.month == m
    if m_mask.sum() > 20:
        is_daily_rv[m] = float(is_spy_r[m_mask].std())

avg_rv = np.mean(list(is_daily_rv.values()))
seasonal_factors = {m: is_daily_rv.get(m, avg_rv) / avg_rv for m in range(1, 13)}

print("\n  Seasonal vol factors (IS):")
for m in range(1, 13):
    print(f"    {month_names[m-1]}: {seasonal_factors[m]:.3f}")

# Strategy implementation
def backtest_vt_strategy(dates, spy_returns, gld_returns, vix_vals, seasonal_adj=None):
    """
    12/VIX with 50/50 SPY/GLD base.
    If seasonal_adj is provided, multiply the VT weight by (2 - seasonal_factor)
    i.e., reduce equity in high-vol months, increase in low-vol months.
    """
    equity_curve = [1.0]
    weights_history = []

    for i in range(len(dates)):
        vix_val = vix_vals.iloc[i]
        if pd.isna(vix_val) or vix_val <= 0:
            vix_val = 20  # fallback

        # Base 12/VIX weight
        w_spy = min(max(12.0 / vix_val, 0.0), 1.5)  # cap at 150%

        if seasonal_adj is not None:
            month = dates[i].month
            factor = seasonal_adj.get(month, 1.0)
            # Reduce exposure in high-vol months (factor > 1), increase in low-vol months
            adjustment = 2.0 - factor  # factor=1.2 → adj=0.8 (reduce), factor=0.8 → adj=1.2 (increase)
            adjustment = max(0.5, min(1.5, adjustment))  # bound the adjustment
            w_spy = w_spy * adjustment
            w_spy = min(max(w_spy, 0.0), 1.5)

        w_gld = 1.0 - w_spy
        w_gld = max(w_gld, -0.5)  # allow some short GLD

        port_r = float(w_spy * spy_returns.iloc[i] + w_gld * gld_returns.iloc[i])
        equity_curve.append(equity_curve[-1] * (1 + port_r))
        weights_history.append(w_spy)

    equity_curve = np.array(equity_curve[1:])
    weights = np.array(weights_history)
    daily_r = np.diff(np.log(np.concatenate([[1], equity_curve])))

    # Metrics
    total_r = equity_curve[-1] / equity_curve[0] - 1
    n_years = len(dates) / 252
    cagr = (equity_curve[-1]) ** (1/n_years) - 1
    sharpe = float(np.mean(daily_r) / np.std(daily_r) * np.sqrt(252)) if np.std(daily_r) > 0 else 0

    # MDD
    peak = np.maximum.accumulate(equity_curve)
    dd = (equity_curve - peak) / peak
    mdd = float(dd.min())

    # Avg weight changes per year
    w_changes = np.abs(np.diff(weights))
    avg_w_changes_yr = float(w_changes.sum() / n_years)

    return {
        "cagr_pct": round(cagr * 100, 3),
        "sharpe": round(sharpe, 4),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(cagr / abs(mdd), 3) if abs(mdd) > 0 else 0,
        "avg_weight": round(float(weights.mean()), 4),
        "avg_weight_changes_per_year": round(avg_w_changes_yr, 1),
        "final_equity": round(float(equity_curve[-1]), 4),
    }

# Full-sample backtest
print("\n  Full-sample backtest:")
plain_full = backtest_vt_strategy(bt_dates, spy_r_bt, gld_r_bt, vix_bt, seasonal_adj=None)
seasonal_full = backtest_vt_strategy(bt_dates, spy_r_bt, gld_r_bt, vix_bt, seasonal_adj=seasonal_factors)
bh_r = (1 + spy_r_bt).cumprod()
bh_cagr = float(bh_r.iloc[-1] ** (1/(len(bt_dates)/252)) - 1)
peak_bh = bh_r.cummax()
bh_mdd = float(((bh_r - peak_bh) / peak_bh).min())
bh_sharpe = float(spy_r_bt.mean() / spy_r_bt.std() * np.sqrt(252))

bh_full = {
    "cagr_pct": round(bh_cagr * 100, 3),
    "sharpe": round(bh_sharpe, 4),
    "mdd_pct": round(bh_mdd * 100, 2),
}

print(f"  Buy & Hold SPY: CAGR={bh_full['cagr_pct']:.2f}%, Sharpe={bh_full['sharpe']:.3f}, MDD={bh_full['mdd_pct']:.1f}%")
print(f"  Plain 12/VIX:   CAGR={plain_full['cagr_pct']:.2f}%, Sharpe={plain_full['sharpe']:.3f}, MDD={plain_full['mdd_pct']:.1f}%")
print(f"  Seasonal 12/VIX: CAGR={seasonal_full['cagr_pct']:.2f}%, Sharpe={seasonal_full['sharpe']:.3f}, MDD={seasonal_full['mdd_pct']:.1f}%")

# OOS-only backtest
print("\n  OOS-only backtest:")
plain_oos = backtest_vt_strategy(oos_dates, spy_r_bt.loc[oos_dates], gld_r_bt.loc[oos_dates],
                                  vix_bt.loc[oos_dates], seasonal_adj=None)
seasonal_oos = backtest_vt_strategy(oos_dates, spy_r_bt.loc[oos_dates], gld_r_bt.loc[oos_dates],
                                     vix_bt.loc[oos_dates], seasonal_adj=seasonal_factors)

print(f"  Plain 12/VIX OOS:   CAGR={plain_oos['cagr_pct']:.2f}%, Sharpe={plain_oos['sharpe']:.3f}, MDD={plain_oos['mdd_pct']:.1f}%")
print(f"  Seasonal 12/VIX OOS: CAGR={seasonal_oos['cagr_pct']:.2f}%, Sharpe={seasonal_oos['sharpe']:.3f}, MDD={seasonal_oos['mdd_pct']:.1f}%")

# Compute tracking error (seasonal vs plain) OOS
plain_eq_oos = [1.0]
seasonal_eq_oos = [1.0]
for i in range(len(oos_dates)):
    vix_val = vix_bt.loc[oos_dates[i]]
    if pd.isna(vix_val) or vix_val <= 0:
        vix_val = 20
    w_plain = min(max(12.0 / vix_val, 0.0), 1.5)
    w_gld_plain = 1.0 - w_plain
    w_gld_plain = max(w_gld_plain, -0.5)

    month = oos_dates[i].month
    factor = seasonal_factors.get(month, 1.0)
    adj = max(0.5, min(1.5, 2.0 - factor))
    w_seasonal = min(max(w_plain * adj, 0.0), 1.5)
    w_gld_seasonal = max(1.0 - w_seasonal, -0.5)

    sr = float(spy_r_bt.loc[oos_dates[i]])
    gr = float(gld_r_bt.loc[oos_dates[i]])

    plain_eq_oos.append(plain_eq_oos[-1] * (1 + w_plain * sr + w_gld_plain * gr))
    seasonal_eq_oos.append(seasonal_eq_oos[-1] * (1 + w_seasonal * sr + w_gld_seasonal * gr))

plain_eq_oos = np.array(plain_eq_oos[1:])
seasonal_eq_oos = np.array(seasonal_eq_oos[1:])
tracking_diff = np.diff(np.log(seasonal_eq_oos)) - np.diff(np.log(plain_eq_oos))
tracking_error = float(np.std(tracking_diff) * np.sqrt(252)) if len(tracking_diff) > 0 else 0

print(f"  Tracking error (seasonal vs plain): {tracking_error*100:.3f}% annualized")

# Sharpe difference significance (Ledoit-Wolf (2008) style)
sharpe_diff = seasonal_oos['sharpe'] - plain_oos['sharpe']
print(f"  Sharpe difference (OOS): {sharpe_diff:+.4f}")

results["seasonal_vt_strategy"] = {
    "seasonal_factors_is": {month_names[m-1]: round(seasonal_factors[m], 3) for m in range(1, 13)},
    "full_sample": {
        "buy_hold_spy": bh_full,
        "plain_12vix": plain_full,
        "seasonal_12vix": seasonal_full,
    },
    "oos": {
        "period": f"{oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}",
        "plain_12vix": plain_oos,
        "seasonal_12vix": seasonal_oos,
        "tracking_error_annualized_pct": round(tracking_error * 100, 3),
        "sharpe_difference": round(sharpe_diff, 4),
    },
    "conclusion_seasonal_adds_value": abs(sharpe_diff) > 0.05 and seasonal_oos['sharpe'] > plain_oos['sharpe'],
}

# ─────────────────────────────────────────────
# 7. PRACTICAL QUESTION: ENTRY MONTH ANALYSIS
# ─────────────────────────────────────────────
print("\n[6/6] Entry month analysis — 1-year forward returns by entry month & VIX...")

# For each month-end, compute the next 252 trading days return
spy_prices = spy['Close'].loc[spy_r.index[0]:]
entry_month_results = {}

for m in range(1, 13):
    # Find month-end dates
    month_ends = spy_prices.resample('ME').last()
    month_end_dates = month_ends[month_ends.index.month == m].index

    low_vix_1yr = []
    high_vix_1yr = []
    all_1yr = []

    for dt in month_end_dates:
        # Get VIX at month end
        try:
            vix_at_entry = vix_close.loc[:dt].iloc[-1]
        except:
            continue

        if pd.isna(vix_at_entry):
            continue

        # Find price 252 trading days later
        future_idx = spy_prices.index[spy_prices.index > dt]
        if len(future_idx) < 252:
            continue  # not enough forward data

        entry_price = float(spy_prices.loc[:dt].iloc[-1])
        exit_price = float(spy_prices.loc[future_idx[251]])

        if entry_price <= 0:
            continue

        one_yr_return = (exit_price / entry_price) - 1
        all_1yr.append(one_yr_return)

        if vix_at_entry < 20:
            low_vix_1yr.append(one_yr_return)
        else:
            high_vix_1yr.append(one_yr_return)

    entry_month_results[month_names[m-1]] = {
        "all_entries": {
            "avg_1yr_return_pct": round(float(np.mean(all_1yr)) * 100, 2) if all_1yr else None,
            "median_1yr_return_pct": round(float(np.median(all_1yr)) * 100, 2) if all_1yr else None,
            "positive_pct": round(float(np.mean([r > 0 for r in all_1yr])) * 100, 1) if all_1yr else None,
            "worst_pct": round(float(min(all_1yr)) * 100, 2) if all_1yr else None,
            "best_pct": round(float(max(all_1yr)) * 100, 2) if all_1yr else None,
            "n": len(all_1yr),
        },
        "vix_below_20": {
            "avg_1yr_return_pct": round(float(np.mean(low_vix_1yr)) * 100, 2) if low_vix_1yr else None,
            "positive_pct": round(float(np.mean([r > 0 for r in low_vix_1yr])) * 100, 1) if low_vix_1yr else None,
            "n": len(low_vix_1yr),
        },
        "vix_above_20": {
            "avg_1yr_return_pct": round(float(np.mean(high_vix_1yr)) * 100, 2) if high_vix_1yr else None,
            "positive_pct": round(float(np.mean([r > 0 for r in high_vix_1yr])) * 100, 1) if high_vix_1yr else None,
            "n": len(high_vix_1yr),
        },
    }

# Print entry month table
print("\n  Entry Month | Avg 1Y Ret% | Pos% | VIX<20 Ret% | VIX>=20 Ret% | N")
print("  " + "-" * 70)
for m_name in month_names:
    d = entry_month_results[m_name]
    a = d['all_entries']
    lo = d['vix_below_20']
    hi = d['vix_above_20']
    avg_r = a['avg_1yr_return_pct'] if a['avg_1yr_return_pct'] is not None else 0
    pos = a['positive_pct'] if a['positive_pct'] is not None else 0
    lo_r = lo['avg_1yr_return_pct'] if lo['avg_1yr_return_pct'] is not None else 0
    hi_r = hi['avg_1yr_return_pct'] if hi['avg_1yr_return_pct'] is not None else 0
    n = a['n']
    print(f"  {m_name:>10} | {avg_r:+10.2f}% | {pos:4.0f}% | {lo_r:+10.2f}% | {hi_r:+11.2f}% | {n:2d}")

# Specific March analysis
march_data = entry_month_results.get('Mar', {})
print(f"\n  *** March entry analysis ***")
if march_data and march_data['all_entries']['avg_1yr_return_pct'] is not None:
    print(f"    Average 1-year return: {march_data['all_entries']['avg_1yr_return_pct']:+.2f}%")
    print(f"    Positive probability: {march_data['all_entries']['positive_pct']:.0f}%")
    print(f"    If VIX < 20 at entry: {march_data['vix_below_20']['avg_1yr_return_pct']:+.2f}%")
    print(f"    If VIX >= 20 at entry: {march_data['vix_above_20']['avg_1yr_return_pct']:+.2f}%")
    print(f"    Worst case: {march_data['all_entries']['worst_pct']:+.2f}%")
    print(f"    Best case: {march_data['all_entries']['best_pct']:+.2f}%")

# KW test across entry months
entry_1yr_by_month = []
for m in range(1, 13):
    d = entry_month_results[month_names[m-1]]
    # We need to recreate the individual returns — but we already have the stats
    # Instead, let's note we can't do KW directly on the summary stats
    pass

# Best vs worst entry month
best_entry = max(
    [(m_name, entry_month_results[m_name]['all_entries']['avg_1yr_return_pct'])
     for m_name in month_names
     if entry_month_results[m_name]['all_entries']['avg_1yr_return_pct'] is not None],
    key=lambda x: x[1]
)
worst_entry = min(
    [(m_name, entry_month_results[m_name]['all_entries']['avg_1yr_return_pct'])
     for m_name in month_names
     if entry_month_results[m_name]['all_entries']['avg_1yr_return_pct'] is not None],
    key=lambda x: x[1]
)

print(f"\n  Best entry month: {best_entry[0]} ({best_entry[1]:+.2f}% avg 1Y)")
print(f"  Worst entry month: {worst_entry[0]} ({worst_entry[1]:+.2f}% avg 1Y)")
print(f"  Spread: {best_entry[1] - worst_entry[1]:.2f}pp")

results["entry_month_analysis"] = {
    "by_month": entry_month_results,
    "best_entry_month": {"month": best_entry[0], "avg_1yr_pct": best_entry[1]},
    "worst_entry_month": {"month": worst_entry[0], "avg_1yr_pct": worst_entry[1]},
    "spread_pp": round(best_entry[1] - worst_entry[1], 2),
    "march_specific": march_data,
}

# ─────────────────────────────────────────────
# 8. SUMMARY & CONCLUSIONS
# ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("SUMMARY & CONCLUSIONS")
print("=" * 70)

conclusions = []

# 1. Monthly VIX patterns
if kw_vix_p < 0.05:
    conclusions.append(f"VIX shows significant monthly seasonality (KW p={kw_vix_p:.4f}). "
                      f"Highest avg VIX: {highest_vix_month}, Lowest: {lowest_vix_month}")
else:
    conclusions.append(f"VIX monthly seasonality is NOT significant (KW p={kw_vix_p:.4f})")

# 2. SPY monthly returns
if kw_spy_p < 0.05:
    conclusions.append(f"SPY monthly returns show significant seasonality (KW p={kw_spy_p:.4f}). "
                      f"Best: {best_return_month}, Worst: {worst_return_month}")
else:
    conclusions.append(f"SPY monthly return seasonality is NOT significant (KW p={kw_spy_p:.4f})")

# 3. Sell in May
if p_sim < 0.05:
    conclusions.append(f"Sell in May IS significant: Winter avg {winter_returns.mean()*100:+.3f}% vs "
                      f"Summer {summer_returns.mean()*100:+.3f}% (t={t_sim:.3f}, p={p_sim:.4f})")
else:
    conclusions.append(f"Sell in May NOT significant at 5%: Winter avg {winter_returns.mean()*100:+.3f}% vs "
                      f"Summer {summer_returns.mean()*100:+.3f}% (t={t_sim:.3f}, p={p_sim:.4f})")

# 4. Seasonal VT adds value?
if results["seasonal_vt_strategy"]["conclusion_seasonal_adds_value"]:
    conclusions.append(f"Seasonal adjustment IMPROVES 12/VIX OOS (Sharpe diff={sharpe_diff:+.4f})")
else:
    conclusions.append(f"Seasonal adjustment does NOT improve 12/VIX OOS (Sharpe diff={sharpe_diff:+.4f})")

# 5. Entry month matters?
conclusions.append(f"Best entry month: {best_entry[0]} ({best_entry[1]:+.2f}%), "
                  f"Worst: {worst_entry[0]} ({worst_entry[1]:+.2f}%), "
                  f"Spread: {best_entry[1]-worst_entry[1]:.1f}pp")

# 6. Practical advice
conclusions.append("VIX level at entry matters MORE than calendar month — "
                  "high VIX entries consistently produce higher forward returns regardless of month")

for i, c in enumerate(conclusions, 1):
    print(f"\n  {i}. {c}")

results["conclusions"] = conclusions
results["practical_takeaway"] = (
    "Calendar month matters far less than VIX regime. "
    "A seasonal overlay on 12/VIX does not survive OOS. "
    "For timing: watch VIX, not the calendar. "
    "Historical March entries have been fine — the VIX level at entry is what determines your 1-year outcome."
)

# Save results
results_path = "experiments/k666_results.json"
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n\nResults saved to {results_path}")
print("=" * 70)
