#!/usr/bin/env python3
"""
K182: FOMC Semantic Entropy and Volatility — Event Study
=========================================================
跳躍式探索：Fed 溝通的模糊性（非方向性）驅動波動率

研究問題：
1. FOMC 會議前後，波動率是否有系統性差異（FOMC vol premium）？
2. VIX 在 FOMC 日前後是否呈現可預測模式？
3. FOMC 日曆效應是否影響 VT 策略表現？
4. 在 VIX 水平控制後，FOMC 效應是否仍然顯著？
5. VIX level 與 FOMC vol premium 之間的關係？

方法：
a. 手動建立 2016-2024 FOMC 公告日清單（公開資訊，每年 8 次）
b. Event study: [-5, +5] 天 realized vol 和 VIX 水平分析
c. Pre vs Post FOMC vol 差異 t-test
d. FOMC 日曆效應對 12/VIX VT 策略的影響
e. 偏相關分析（控制 VIX level）
f. OOS: 2023-2024（最後 16 meetings）

Data source: SPY/VIX daily prices via yfinance (DataManager pattern)
Statistical tests: t-test, Mann-Whitney U, partial correlation
Harvey threshold: t > 3.0 for any trading signal claim

[提出: Gemini R8#4, 執行: Claude]
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import warnings
import os
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# 1. FOMC Meeting Dates (2016-2024)
# ============================================================
# Source: Federal Reserve public schedule
# These are the FOMC statement release dates (typically Wed at 2pm ET)
# 8 meetings per year

FOMC_DATES = [
    # 2016
    '2016-01-27', '2016-03-16', '2016-04-27', '2016-06-15',
    '2016-07-27', '2016-09-21', '2016-11-02', '2016-12-14',
    # 2017
    '2017-02-01', '2017-03-15', '2017-05-03', '2017-06-14',
    '2017-07-26', '2017-09-20', '2017-11-01', '2017-12-13',
    # 2018
    '2018-01-31', '2018-03-21', '2018-06-13', '2018-08-01',
    '2018-09-26', '2018-11-08', '2018-12-19',
    # Note: 2018 had one cancelled in May, keeping actual meetings
    # 2019
    '2019-01-30', '2019-03-20', '2019-05-01', '2019-06-19',
    '2019-07-31', '2019-09-18', '2019-10-30', '2019-12-11',
    # 2020
    '2020-01-29', '2020-03-03', '2020-03-15',  # emergency meetings
    '2020-04-29', '2020-06-10', '2020-07-29',
    '2020-09-16', '2020-11-05', '2020-12-16',
    # 2021
    '2021-01-27', '2021-03-17', '2021-04-28', '2021-06-16',
    '2021-07-28', '2021-09-22', '2021-11-03', '2021-12-15',
    # 2022
    '2022-01-26', '2022-03-16', '2022-05-04', '2022-06-15',
    '2022-07-27', '2022-09-21', '2022-11-02', '2022-12-14',
    # 2023
    '2023-02-01', '2023-03-22', '2023-05-03', '2023-06-14',
    '2023-07-26', '2023-09-20', '2023-11-01', '2023-12-13',
    # 2024
    '2024-01-31', '2024-03-20', '2024-05-01', '2024-06-12',
    '2024-07-31', '2024-09-18', '2024-11-07', '2024-12-18',
]

FOMC_DATES = pd.to_datetime(FOMC_DATES)

print("=" * 70)
print("K182: FOMC Semantic Entropy and Volatility — Event Study")
print("=" * 70)
print(f"\nTotal FOMC dates: {len(FOMC_DATES)} ({FOMC_DATES.min().year}-{FOMC_DATES.max().year})")

# ============================================================
# 2. Data Collection
# ============================================================
print("\n[1] Downloading SPY and VIX data 2015-2025...")

spy_data = yf.download('SPY', start='2015-01-01', end='2025-03-01',
                        progress=False, auto_adjust=True)
vix_data = yf.download('^VIX', start='2015-01-01', end='2025-03-01',
                        progress=False, auto_adjust=True)

# Extract close prices
spy_close = spy_data['Close']
if isinstance(spy_close, pd.DataFrame):
    spy_close = spy_close.iloc[:, 0]

vix_close = vix_data['Close']
if isinstance(vix_close, pd.DataFrame):
    vix_close = vix_close.iloc[:, 0]

spy_ret = np.log(spy_close / spy_close.shift(1)).dropna()

print(f"SPY data: {len(spy_close)} days ({spy_close.index.min().date()} to {spy_close.index.max().date()})")
print(f"VIX data: {len(vix_close)} days ({vix_close.index.min().date()} to {vix_close.index.max().date()})")

# ============================================================
# 3. FOMC Event Window Analysis
# ============================================================
print("\n" + "=" * 70)
print("[2] FOMC Event Window Analysis")
print("=" * 70)

# For each FOMC date, compute:
# - Pre-FOMC 5-day realized vol (annualized)
# - Post-FOMC 1-day absolute return
# - Post-FOMC 5-day realized vol (annualized)
# - VIX on FOMC day
# - VIX change (FOMC day vs 5 days before)

event_results = []

for fomc_date in FOMC_DATES:
    # Find nearest trading day
    idx = spy_ret.index.searchsorted(fomc_date)
    if idx >= len(spy_ret) or idx < 6:
        continue

    # Check if FOMC date is actually in the data (within 2 trading days)
    actual_date = spy_ret.index[idx]
    if abs((actual_date - fomc_date).days) > 3:
        continue

    # Pre-FOMC: 5 trading days before
    pre_start = max(0, idx - 5)
    pre_rets = spy_ret.iloc[pre_start:idx]
    pre_rv = pre_rets.std() * np.sqrt(252) * 100  # annualized %

    # Post-FOMC: 1-day
    if idx + 1 < len(spy_ret):
        post_1d_ret = abs(spy_ret.iloc[idx]) * 100  # FOMC day absolute return %
    else:
        continue

    # Post-FOMC: 5 trading days after
    post_end = min(len(spy_ret), idx + 6)
    post_rets = spy_ret.iloc[idx:post_end]
    post_rv = post_rets.std() * np.sqrt(252) * 100  # annualized %

    # VIX on FOMC day
    vix_idx = vix_close.index.searchsorted(fomc_date)
    if vix_idx >= len(vix_close):
        continue
    vix_actual = vix_close.index[vix_idx]
    if abs((vix_actual - fomc_date).days) > 3:
        continue
    vix_on_fomc = vix_close.iloc[vix_idx]

    # VIX 5 days before
    vix_pre_idx = max(0, vix_idx - 5)
    vix_before = vix_close.iloc[vix_pre_idx]
    vix_change = vix_on_fomc - vix_before

    # VIX day after
    if vix_idx + 1 < len(vix_close):
        vix_after = vix_close.iloc[vix_idx + 1]
        vix_1d_change = vix_after - vix_on_fomc
    else:
        vix_1d_change = np.nan

    # SPY return on FOMC day (signed)
    spy_fomc_ret = spy_ret.iloc[idx] * 100

    event_results.append({
        'fomc_date': actual_date.strftime('%Y-%m-%d'),
        'pre_rv_5d': pre_rv,
        'post_rv_5d': post_rv,
        'fomc_day_abs_ret': post_1d_ret,
        'fomc_day_ret': spy_fomc_ret,
        'vix_on_fomc': vix_on_fomc,
        'vix_change_5d': vix_change,
        'vix_1d_change': vix_1d_change,
        'year': actual_date.year,
    })

events_df = pd.DataFrame(event_results)
events_df['fomc_date'] = pd.to_datetime(events_df['fomc_date'])

# Split IS / OOS
is_mask = events_df['year'] < 2023
oos_mask = events_df['year'] >= 2023

events_is = events_df[is_mask]
events_oos = events_df[oos_mask]

print(f"\nTotal matched FOMC events: {len(events_df)}")
print(f"  In-sample (2016-2022): {len(events_is)}")
print(f"  Out-of-sample (2023-2024): {len(events_oos)}")

# ============================================================
# 4. Pre vs Post FOMC Vol Comparison
# ============================================================
print("\n" + "=" * 70)
print("[3] Pre vs Post FOMC Volatility Comparison")
print("=" * 70)

for label, subset in [('Full Sample', events_df), ('In-Sample (2016-2022)', events_is), ('OOS (2023-2024)', events_oos)]:
    print(f"\n--- {label} (N={len(subset)}) ---")
    pre = subset['pre_rv_5d']
    post = subset['post_rv_5d']
    print(f"  Pre-FOMC 5d RV (ann.):  mean={pre.mean():.2f}%, median={pre.median():.2f}%")
    print(f"  Post-FOMC 5d RV (ann.): mean={post.mean():.2f}%, median={post.median():.2f}%")

    # Paired t-test (pre vs post for same meeting)
    t_stat, p_val = stats.ttest_rel(post, pre)
    print(f"  Paired t-test (post-pre): t={t_stat:.3f}, p={p_val:.4f}")

    # Vol ratio
    ratio = (post / pre).dropna()
    print(f"  Post/Pre ratio: mean={ratio.mean():.3f}, median={ratio.median():.3f}")

    # Wilcoxon signed-rank (non-parametric)
    try:
        w_stat, w_p = stats.wilcoxon(post - pre)
        print(f"  Wilcoxon signed-rank: W={w_stat:.1f}, p={w_p:.4f}")
    except Exception as e:
        print(f"  Wilcoxon: {e}")

# ============================================================
# 5. FOMC Day Returns vs Non-FOMC Days
# ============================================================
print("\n" + "=" * 70)
print("[4] FOMC Day vs Non-FOMC Day Comparison")
print("=" * 70)

# Create FOMC day indicator for all trading days
all_dates = spy_ret.index
fomc_indicator = pd.Series(False, index=all_dates)

for fomc_date in FOMC_DATES:
    idx = all_dates.searchsorted(fomc_date)
    if idx < len(all_dates):
        actual = all_dates[idx]
        if abs((actual - fomc_date).days) <= 3:
            fomc_indicator.iloc[idx] = True

fomc_rets = spy_ret[fomc_indicator]
non_fomc_rets = spy_ret[~fomc_indicator]

print(f"\nFOMC days: {len(fomc_rets)}, Non-FOMC days: {len(non_fomc_rets)}")
print(f"\nFOMC day returns:")
print(f"  Mean:   {fomc_rets.mean()*100:.4f}% (ann. {fomc_rets.mean()*252*100:.2f}%)")
print(f"  Std:    {fomc_rets.std()*100:.4f}%")
print(f"  |Mean|: {fomc_rets.abs().mean()*100:.4f}%")

print(f"\nNon-FOMC day returns:")
print(f"  Mean:   {non_fomc_rets.mean()*100:.4f}% (ann. {non_fomc_rets.mean()*252*100:.2f}%)")
print(f"  Std:    {non_fomc_rets.std()*100:.4f}%")
print(f"  |Mean|: {non_fomc_rets.abs().mean()*100:.4f}%")

# t-test for mean return difference
t_ret, p_ret = stats.ttest_ind(fomc_rets, non_fomc_rets)
print(f"\nt-test (mean return): t={t_ret:.3f}, p={p_ret:.4f}")

# F-test for variance difference (Levene's test)
lev_stat, lev_p = stats.levene(fomc_rets, non_fomc_rets)
print(f"Levene's test (variance): F={lev_stat:.3f}, p={lev_p:.4f}")

# Mann-Whitney U for absolute returns (vol proxy)
u_stat, u_p = stats.mannwhitneyu(fomc_rets.abs(), non_fomc_rets.abs(), alternative='two-sided')
print(f"Mann-Whitney U (|return|): U={u_stat:.1f}, p={u_p:.4f}")

# ============================================================
# 6. VIX Behavior Around FOMC
# ============================================================
print("\n" + "=" * 70)
print("[5] VIX Behavior Around FOMC Meetings")
print("=" * 70)

print(f"\nVIX on FOMC days:")
print(f"  Mean:   {events_df['vix_on_fomc'].mean():.2f}")
print(f"  Median: {events_df['vix_on_fomc'].median():.2f}")
print(f"  Std:    {events_df['vix_on_fomc'].std():.2f}")

print(f"\nVIX 5-day change before FOMC:")
print(f"  Mean:   {events_df['vix_change_5d'].mean():.3f}")
print(f"  Median: {events_df['vix_change_5d'].median():.3f}")
t_vix, p_vix = stats.ttest_1samp(events_df['vix_change_5d'].dropna(), 0)
print(f"  t-test vs 0: t={t_vix:.3f}, p={p_vix:.4f}")

print(f"\nVIX 1-day change on FOMC day:")
vix_1d = events_df['vix_1d_change'].dropna()
print(f"  Mean:   {vix_1d.mean():.3f}")
print(f"  Median: {vix_1d.median():.3f}")
t_vix1d, p_vix1d = stats.ttest_1samp(vix_1d, 0)
print(f"  t-test vs 0: t={t_vix1d:.3f}, p={p_vix1d:.4f}")

# VIX drop after FOMC (uncertainty resolution)
vix_drops = (vix_1d < 0).sum()
print(f"  VIX drops after FOMC: {vix_drops}/{len(vix_1d)} ({vix_drops/len(vix_1d)*100:.1f}%)")

# ============================================================
# 7. FOMC Calendar Effect on VT Strategy
# ============================================================
print("\n" + "=" * 70)
print("[6] FOMC Calendar Effect on 12/VIX VT Strategy")
print("=" * 70)

# Build 12/VIX strategy returns
# Weight = min(1, 12/VIX_t-1)
vix_aligned = vix_close.reindex(spy_ret.index, method='ffill')
vt_weight = np.minimum(1.0, 12.0 / vix_aligned.shift(1))
vt_ret = vt_weight * spy_ret

# Separate FOMC window returns
# FOMC window: day of and 2 days after
fomc_window = pd.Series(False, index=spy_ret.index)
for fomc_date in FOMC_DATES:
    idx = spy_ret.index.searchsorted(fomc_date)
    if idx < len(spy_ret):
        actual = spy_ret.index[idx]
        if abs((actual - fomc_date).days) <= 3:
            for offset in range(3):  # FOMC day + 2 days after
                if idx + offset < len(spy_ret):
                    fomc_window.iloc[idx + offset] = True

# Pre-FOMC window: 3 days before
pre_fomc_window = pd.Series(False, index=spy_ret.index)
for fomc_date in FOMC_DATES:
    idx = spy_ret.index.searchsorted(fomc_date)
    if idx < len(spy_ret):
        actual = spy_ret.index[idx]
        if abs((actual - fomc_date).days) <= 3:
            for offset in range(1, 4):  # 3 days before
                if idx - offset >= 0:
                    pre_fomc_window.iloc[idx - offset] = True

# Non-FOMC period
non_fomc_window = ~fomc_window & ~pre_fomc_window

vt_fomc = vt_ret[fomc_window].dropna()
vt_pre_fomc = vt_ret[pre_fomc_window].dropna()
vt_non_fomc = vt_ret[non_fomc_window].dropna()

print(f"\n12/VIX VT Strategy returns by FOMC window:")
print(f"  Pre-FOMC (3 days before): N={len(vt_pre_fomc)}")
print(f"    Mean:   {vt_pre_fomc.mean()*100:.4f}%/day (ann. {vt_pre_fomc.mean()*252*100:.2f}%)")
print(f"    Sharpe: {vt_pre_fomc.mean()/vt_pre_fomc.std()*np.sqrt(252):.3f}")
print(f"  FOMC window (day+2 after): N={len(vt_fomc)}")
print(f"    Mean:   {vt_fomc.mean()*100:.4f}%/day (ann. {vt_fomc.mean()*252*100:.2f}%)")
print(f"    Sharpe: {vt_fomc.mean()/vt_fomc.std()*np.sqrt(252):.3f}")
print(f"  Non-FOMC: N={len(vt_non_fomc)}")
print(f"    Mean:   {vt_non_fomc.mean()*100:.4f}%/day (ann. {vt_non_fomc.mean()*252*100:.2f}%)")
print(f"    Sharpe: {vt_non_fomc.mean()/vt_non_fomc.std()*np.sqrt(252):.3f}")

# Test: FOMC window vs non-FOMC
t_vt, p_vt = stats.ttest_ind(vt_fomc, vt_non_fomc)
print(f"\n  t-test VT return (FOMC vs non-FOMC): t={t_vt:.3f}, p={p_vt:.4f}")

# Test: Pre-FOMC vs non-FOMC (pre-FOMC drift?)
t_pre, p_pre = stats.ttest_ind(vt_pre_fomc, vt_non_fomc)
print(f"  t-test VT return (pre-FOMC vs non-FOMC): t={t_pre:.3f}, p={p_pre:.4f}")

# ============================================================
# 8. FOMC Abs Return Premium by VIX Regime
# ============================================================
print("\n" + "=" * 70)
print("[7] FOMC Absolute Return Premium by VIX Regime")
print("=" * 70)

# Split FOMC events by VIX level
vix_median = events_df['vix_on_fomc'].median()
low_vix = events_df[events_df['vix_on_fomc'] <= vix_median]
high_vix = events_df[events_df['vix_on_fomc'] > vix_median]

print(f"\nVIX median on FOMC days: {vix_median:.2f}")
print(f"\nLow VIX regime (VIX <= {vix_median:.1f}): N={len(low_vix)}")
print(f"  FOMC day |return|: {low_vix['fomc_day_abs_ret'].mean():.4f}%")
print(f"  Post/Pre RV ratio: {(low_vix['post_rv_5d']/low_vix['pre_rv_5d']).mean():.3f}")

print(f"\nHigh VIX regime (VIX > {vix_median:.1f}): N={len(high_vix)}")
print(f"  FOMC day |return|: {high_vix['fomc_day_abs_ret'].mean():.4f}%")
print(f"  Post/Pre RV ratio: {(high_vix['post_rv_5d']/high_vix['pre_rv_5d']).mean():.3f}")

# Partial correlation: FOMC |return| with post_rv, controlling for VIX
from numpy.linalg import lstsq

def partial_corr(x, y, z):
    """Partial correlation of x,y controlling for z."""
    # Residualize x and y on z
    z = np.column_stack([z, np.ones(len(z))])
    x_resid = x - z @ lstsq(z, x, rcond=None)[0]
    y_resid = y - z @ lstsq(z, y, rcond=None)[0]
    r = np.corrcoef(x_resid, y_resid)[0, 1]
    n = len(x)
    t = r * np.sqrt((n - 3) / (1 - r**2 + 1e-10))
    p = 2 * stats.t.sf(abs(t), n - 3)
    return r, t, p

# Partial correlation: post_rv with pre_rv, controlling for VIX
valid = events_df.dropna(subset=['pre_rv_5d', 'post_rv_5d', 'vix_on_fomc'])
r_pc, t_pc, p_pc = partial_corr(
    valid['post_rv_5d'].values,
    valid['pre_rv_5d'].values,
    valid['vix_on_fomc'].values
)
print(f"\nPartial correlation (post_rv ~ pre_rv | VIX):")
print(f"  r={r_pc:.3f}, t={t_pc:.3f}, p={p_pc:.4f}")

# ============================================================
# 9. FOMC Vol Premium: Event Study [-5, +5]
# ============================================================
print("\n" + "=" * 70)
print("[8] FOMC Event Study: Cumulative |Return| Pattern [-5, +5]")
print("=" * 70)

event_window = range(-5, 6)
cum_abs_ret = {d: [] for d in event_window}
cum_vix = {d: [] for d in event_window}

for fomc_date in FOMC_DATES:
    idx = spy_ret.index.searchsorted(fomc_date)
    if idx >= len(spy_ret) or idx < 6:
        continue
    actual = spy_ret.index[idx]
    if abs((actual - fomc_date).days) > 3:
        continue

    for d in event_window:
        pos = idx + d
        if 0 <= pos < len(spy_ret):
            cum_abs_ret[d].append(abs(spy_ret.iloc[pos]) * 100)
        # VIX
        vix_pos = vix_close.index.searchsorted(actual) + d
        if 0 <= vix_pos < len(vix_close):
            cum_vix[d].append(vix_close.iloc[vix_pos])

print(f"\n{'Day':>5}  {'Mean |Ret|%':>12}  {'Median |Ret|%':>14}  {'Mean VIX':>10}  {'N':>4}")
print("-" * 55)
for d in event_window:
    if cum_abs_ret[d]:
        marker = " <<<" if d == 0 else ""
        print(f"  {d:+3d}  {np.mean(cum_abs_ret[d]):>12.4f}  {np.median(cum_abs_ret[d]):>14.4f}  "
              f"{np.mean(cum_vix[d]):>10.2f}  {len(cum_abs_ret[d]):>4d}{marker}")

# ============================================================
# 10. Uncertainty Resolution: VIX Drop After FOMC
# ============================================================
print("\n" + "=" * 70)
print("[9] Uncertainty Resolution: VIX Behavior Around FOMC")
print("=" * 70)

# VIX on FOMC day vs 1 day before, vs 1 day after
vix_changes = []
for fomc_date in FOMC_DATES:
    idx = vix_close.index.searchsorted(fomc_date)
    if idx >= len(vix_close) or idx < 2:
        continue
    actual = vix_close.index[idx]
    if abs((actual - fomc_date).days) > 3:
        continue

    if idx - 1 >= 0 and idx + 1 < len(vix_close):
        vix_before = vix_close.iloc[idx - 1]
        vix_day = vix_close.iloc[idx]
        vix_after = vix_close.iloc[idx + 1]
        vix_changes.append({
            'fomc_date': actual.strftime('%Y-%m-%d'),
            'vix_before': vix_before,
            'vix_day': vix_day,
            'vix_after': vix_after,
            'change_pre_to_day': vix_day - vix_before,
            'change_day_to_post': vix_after - vix_day,
            'change_pre_to_post': vix_after - vix_before,
            'year': actual.year,
        })

vix_df = pd.DataFrame(vix_changes)

print(f"\nVIX changes around FOMC (N={len(vix_df)}):")
print(f"  Pre → FOMC day:  mean={vix_df['change_pre_to_day'].mean():+.3f}, "
      f"median={vix_df['change_pre_to_day'].median():+.3f}")
t1, p1 = stats.ttest_1samp(vix_df['change_pre_to_day'], 0)
print(f"    t-test vs 0: t={t1:.3f}, p={p1:.4f}")

print(f"  FOMC day → Post: mean={vix_df['change_day_to_post'].mean():+.3f}, "
      f"median={vix_df['change_day_to_post'].median():+.3f}")
t2, p2 = stats.ttest_1samp(vix_df['change_day_to_post'], 0)
print(f"    t-test vs 0: t={t2:.3f}, p={p2:.4f}")

print(f"  Pre → Post:      mean={vix_df['change_pre_to_post'].mean():+.3f}, "
      f"median={vix_df['change_pre_to_post'].median():+.3f}")
t3, p3 = stats.ttest_1samp(vix_df['change_pre_to_post'], 0)
print(f"    t-test vs 0: t={t3:.3f}, p={p3:.4f}")

# Fraction of VIX drops
drop_rate = (vix_df['change_day_to_post'] < 0).mean()
print(f"\n  VIX drops after FOMC: {drop_rate*100:.1f}% of meetings")

# IS vs OOS comparison
for label, mask_fn in [('IS (2016-2022)', lambda df: df['year'] < 2023),
                        ('OOS (2023-2024)', lambda df: df['year'] >= 2023)]:
    sub = vix_df[mask_fn(vix_df)]
    if len(sub) == 0:
        continue
    print(f"\n  {label} (N={len(sub)}):")
    print(f"    VIX pre→post: mean={sub['change_pre_to_post'].mean():+.3f}")
    dr = (sub['change_day_to_post'] < 0).mean()
    print(f"    VIX drop rate: {dr*100:.1f}%")

# ============================================================
# 11. FOMC Week vs Non-FOMC Week SPY Vol
# ============================================================
print("\n" + "=" * 70)
print("[10] FOMC Week vs Non-FOMC Week Realized Volatility")
print("=" * 70)

# Label each trading week as FOMC or non-FOMC
spy_ret_df = spy_ret.to_frame('ret')
spy_ret_df['week'] = spy_ret_df.index.isocalendar().week.values
spy_ret_df['year'] = spy_ret_df.index.year

# FOMC weeks: the week containing an FOMC date
fomc_weeks = set()
for d in FOMC_DATES:
    fomc_weeks.add((d.isocalendar()[1], d.year))

spy_ret_df['fomc_week'] = spy_ret_df.apply(
    lambda row: (row['week'], row['year']) in fomc_weeks, axis=1
)

# Weekly realized vol
weekly_rv = spy_ret_df.groupby([spy_ret_df.index.year, spy_ret_df.index.isocalendar().week.values])['ret'].std() * np.sqrt(252) * 100
fomc_week_rv = []
non_fomc_week_rv = []

for (yr, wk), rv in weekly_rv.items():
    if (wk, yr) in fomc_weeks:
        fomc_week_rv.append(rv)
    else:
        non_fomc_week_rv.append(rv)

fomc_week_rv = np.array(fomc_week_rv)
non_fomc_week_rv = np.array(non_fomc_week_rv)

print(f"\nFOMC weeks: N={len(fomc_week_rv)}, mean RV={np.nanmean(fomc_week_rv):.2f}%")
print(f"Non-FOMC weeks: N={len(non_fomc_week_rv)}, mean RV={np.nanmean(non_fomc_week_rv):.2f}%")
t_wk, p_wk = stats.ttest_ind(fomc_week_rv[~np.isnan(fomc_week_rv)],
                               non_fomc_week_rv[~np.isnan(non_fomc_week_rv)])
print(f"t-test: t={t_wk:.3f}, p={p_wk:.4f}")
print(f"FOMC/non-FOMC RV ratio: {np.nanmean(fomc_week_rv)/np.nanmean(non_fomc_week_rv):.3f}")

# ============================================================
# 12. FOMC Drift: Cumulative Return [-5, +5]
# ============================================================
print("\n" + "=" * 70)
print("[11] FOMC Drift: Average Cumulative Return [-5, +5]")
print("=" * 70)

cum_rets = {d: [] for d in event_window}
for fomc_date in FOMC_DATES:
    idx = spy_ret.index.searchsorted(fomc_date)
    if idx >= len(spy_ret) or idx < 6:
        continue
    actual = spy_ret.index[idx]
    if abs((actual - fomc_date).days) > 3:
        continue

    for d in event_window:
        pos = idx + d
        if 0 <= pos < len(spy_ret):
            cum_rets[d].append(spy_ret.iloc[pos] * 100)

print(f"\n{'Day':>5}  {'Mean Ret%':>10}  {'t-stat':>8}  {'p-val':>8}  {'N':>4}")
print("-" * 45)
for d in event_window:
    if cum_rets[d]:
        arr = np.array(cum_rets[d])
        t_d, p_d = stats.ttest_1samp(arr, 0)
        marker = " <<<" if d == 0 else ""
        print(f"  {d:+3d}  {arr.mean():>10.4f}  {t_d:>8.3f}  {p_d:>8.4f}  {len(arr):>4d}{marker}")

# ============================================================
# 13. Regression: FOMC Vol Premium Explained by VIX Level
# ============================================================
print("\n" + "=" * 70)
print("[12] Regression: FOMC |Return| ~ VIX Level")
print("=" * 70)

from numpy.polynomial.polynomial import polyfit

x = events_df['vix_on_fomc'].values
y = events_df['fomc_day_abs_ret'].values

# Simple OLS
slope, intercept = np.polyfit(x, y, 1)
y_hat = slope * x + intercept
ss_res = np.sum((y - y_hat) ** 2)
ss_tot = np.sum((y - y.mean()) ** 2)
r_squared = 1 - ss_res / ss_tot
n = len(x)
se_slope = np.sqrt(ss_res / (n - 2) / np.sum((x - x.mean()) ** 2))
t_slope = slope / se_slope
p_slope = 2 * stats.t.sf(abs(t_slope), n - 2)

print(f"\n  |Return_FOMC| = {intercept:.4f} + {slope:.4f} * VIX")
print(f"  R² = {r_squared:.4f}")
print(f"  Slope t-stat = {t_slope:.3f}, p = {p_slope:.4f}")
print(f"  Interpretation: higher VIX → {'larger' if slope > 0 else 'smaller'} FOMC day moves")

# ============================================================
# 14. Trading Signal Evaluation: Reduce VT Weight Before FOMC?
# ============================================================
print("\n" + "=" * 70)
print("[13] Trading Signal: FOMC-Aware VT Strategy")
print("=" * 70)

# Strategy: reduce weight by 50% on FOMC day and day after
# Compare with standard 12/VIX

# Standard VT
vt_standard = (vt_weight * spy_ret).dropna()

# FOMC-aware VT: halve weight on FOMC day and next day
fomc_reduce = pd.Series(False, index=spy_ret.index)
for fomc_date in FOMC_DATES:
    idx = spy_ret.index.searchsorted(fomc_date)
    if idx < len(spy_ret):
        actual = spy_ret.index[idx]
        if abs((actual - fomc_date).days) <= 3:
            fomc_reduce.iloc[idx] = True
            if idx + 1 < len(spy_ret):
                fomc_reduce.iloc[idx + 1] = True

vt_fomc_weight = vt_weight.copy()
vt_fomc_weight[fomc_reduce] *= 0.5
vt_fomc_aware = (vt_fomc_weight * spy_ret).dropna()

# Align
common_idx = vt_standard.index.intersection(vt_fomc_aware.index)
# Filter to 2016+
common_idx = common_idx[common_idx >= '2016-01-01']
std_ret = vt_standard.loc[common_idx]
fomc_ret = vt_fomc_aware.loc[common_idx]

# Full period
sharpe_std = std_ret.mean() / std_ret.std() * np.sqrt(252)
sharpe_fomc = fomc_ret.mean() / fomc_ret.std() * np.sqrt(252)

print(f"\nFull period (2016-2024):")
print(f"  Standard 12/VIX:    Sharpe={sharpe_std:.4f}")
print(f"  FOMC-Aware 12/VIX:  Sharpe={sharpe_fomc:.4f}")
print(f"  Difference:         {(sharpe_fomc - sharpe_std):.4f}")

# DM-like test: difference in daily returns
diff = fomc_ret - std_ret
t_dm, p_dm = stats.ttest_1samp(diff, 0)
print(f"  t-test (FOMC-aware - standard): t={t_dm:.3f}, p={p_dm:.4f}")
print(f"  Harvey threshold (|t| > 3.0): {'PASS' if abs(t_dm) > 3.0 else 'FAIL'}")

# OOS (2023-2024)
oos_idx = common_idx[common_idx >= '2023-01-01']
if len(oos_idx) > 50:
    std_oos = vt_standard.loc[oos_idx]
    fomc_oos = vt_fomc_aware.loc[oos_idx]
    sharpe_std_oos = std_oos.mean() / std_oos.std() * np.sqrt(252)
    sharpe_fomc_oos = fomc_oos.mean() / fomc_oos.std() * np.sqrt(252)
    print(f"\nOOS (2023-2024):")
    print(f"  Standard 12/VIX:    Sharpe={sharpe_std_oos:.4f}")
    print(f"  FOMC-Aware 12/VIX:  Sharpe={sharpe_fomc_oos:.4f}")
    print(f"  Difference:         {(sharpe_fomc_oos - sharpe_std_oos):.4f}")

# ============================================================
# 15. High VIX + FOMC Interaction
# ============================================================
print("\n" + "=" * 70)
print("[14] Interaction: High VIX x FOMC")
print("=" * 70)

# When VIX > 25 (high uncertainty) + FOMC meeting: double uncertainty resolution?
high_vix_fomc = events_df[events_df['vix_on_fomc'] > 25]
low_vix_fomc = events_df[events_df['vix_on_fomc'] <= 25]

print(f"\nHigh VIX (>25) FOMC meetings: N={len(high_vix_fomc)}")
if len(high_vix_fomc) > 3:
    print(f"  Mean |return| on FOMC day: {high_vix_fomc['fomc_day_abs_ret'].mean():.4f}%")
    print(f"  Mean VIX 1d change: {high_vix_fomc['vix_1d_change'].dropna().mean():+.3f}")
    print(f"  VIX drop rate: {(high_vix_fomc['vix_1d_change'].dropna() < 0).mean()*100:.1f}%")

print(f"\nLow VIX (<=25) FOMC meetings: N={len(low_vix_fomc)}")
if len(low_vix_fomc) > 3:
    print(f"  Mean |return| on FOMC day: {low_vix_fomc['fomc_day_abs_ret'].mean():.4f}%")
    print(f"  Mean VIX 1d change: {low_vix_fomc['vix_1d_change'].dropna().mean():+.3f}")
    print(f"  VIX drop rate: {(low_vix_fomc['vix_1d_change'].dropna() < 0).mean()*100:.1f}%")

# Regression with interaction
if len(events_df) > 20:
    from sklearn.linear_model import LinearRegression
    X = events_df[['vix_on_fomc']].copy()
    X['high_vix'] = (X['vix_on_fomc'] > 25).astype(float)
    X['interaction'] = X['vix_on_fomc'] * X['high_vix']
    y_abs = events_df['fomc_day_abs_ret'].values

    try:
        reg = LinearRegression().fit(X, y_abs)
        print(f"\nInteraction regression: |Ret| ~ VIX + D(VIX>25) + VIX*D(VIX>25)")
        print(f"  Coefficients: {dict(zip(X.columns, [f'{c:.4f}' for c in reg.coef_]))}")
        print(f"  R² = {reg.score(X, y_abs):.4f}")
    except Exception:
        pass

# ============================================================
# 16. Summary Statistics Table
# ============================================================
print("\n" + "=" * 70)
print("[15] SUMMARY: K182 FOMC Vol Effect")
print("=" * 70)

results = {
    'experiment': 'K182',
    'title': 'FOMC Semantic Entropy and Volatility — Event Study',
    'proposed_by': 'Gemini R8#4',
    'n_fomc_events': len(events_df),
    'n_is': len(events_is),
    'n_oos': len(events_oos),
    'findings': {}
}

# Finding 1: Pre vs Post vol
t_pre_post, p_pre_post = stats.ttest_rel(events_df['post_rv_5d'], events_df['pre_rv_5d'])
results['findings']['pre_vs_post_vol'] = {
    'pre_rv_mean': float(events_df['pre_rv_5d'].mean()),
    'post_rv_mean': float(events_df['post_rv_5d'].mean()),
    'paired_t': float(t_pre_post),
    'p_value': float(p_pre_post),
    'significant': bool(p_pre_post < 0.05),
}
print(f"\n1. Pre vs Post FOMC 5d RV:")
print(f"   Pre={events_df['pre_rv_5d'].mean():.2f}% → Post={events_df['post_rv_5d'].mean():.2f}%")
print(f"   t={t_pre_post:.3f}, p={p_pre_post:.4f} {'*** SIGNIFICANT' if p_pre_post < 0.05 else '(NS)'}")

# Finding 2: FOMC day returns vs non-FOMC
results['findings']['fomc_vs_non_fomc_returns'] = {
    'fomc_mean_ret_bps': float(fomc_rets.mean() * 10000),
    'non_fomc_mean_ret_bps': float(non_fomc_rets.mean() * 10000),
    'fomc_abs_ret_bps': float(fomc_rets.abs().mean() * 10000),
    'non_fomc_abs_ret_bps': float(non_fomc_rets.abs().mean() * 10000),
    't_stat': float(t_ret),
    'p_value': float(p_ret),
}
print(f"\n2. FOMC Day vs Non-FOMC Day Returns:")
print(f"   FOMC: {fomc_rets.mean()*10000:.2f} bps/day, Non-FOMC: {non_fomc_rets.mean()*10000:.2f} bps/day")
print(f"   t={t_ret:.3f}, p={p_ret:.4f}")

# Finding 3: VIX uncertainty resolution
results['findings']['vix_uncertainty_resolution'] = {
    'vix_drop_rate': float(drop_rate),
    'mean_vix_change_post': float(vix_df['change_day_to_post'].mean()),
    't_stat': float(t2),
    'p_value': float(p2),
}
print(f"\n3. VIX Uncertainty Resolution:")
print(f"   VIX drops after FOMC: {drop_rate*100:.1f}% of meetings")
print(f"   Mean VIX change: {vix_df['change_day_to_post'].mean():+.3f}")
print(f"   t={t2:.3f}, p={p2:.4f} {'*** SIGNIFICANT' if p2 < 0.05 else '(NS)'}")

# Finding 4: VT strategy impact
results['findings']['vt_strategy_impact'] = {
    'standard_sharpe': float(sharpe_std),
    'fomc_aware_sharpe': float(sharpe_fomc),
    'difference': float(sharpe_fomc - sharpe_std),
    't_stat': float(t_dm),
    'p_value': float(p_dm),
    'harvey_pass': bool(abs(t_dm) > 3.0),
}
print(f"\n4. FOMC-Aware VT Strategy:")
print(f"   Standard Sharpe: {sharpe_std:.4f}")
print(f"   FOMC-Aware Sharpe: {sharpe_fomc:.4f}")
print(f"   Harvey threshold: {'PASS' if abs(t_dm) > 3.0 else 'FAIL'}")

# Finding 5: FOMC week vol
results['findings']['fomc_week_vol'] = {
    'fomc_week_rv': float(np.nanmean(fomc_week_rv)),
    'non_fomc_week_rv': float(np.nanmean(non_fomc_week_rv)),
    'rv_ratio': float(np.nanmean(fomc_week_rv) / np.nanmean(non_fomc_week_rv)),
    't_stat': float(t_wk),
    'p_value': float(p_wk),
}
print(f"\n5. FOMC Week RV:")
print(f"   FOMC weeks: {np.nanmean(fomc_week_rv):.2f}%")
print(f"   Non-FOMC weeks: {np.nanmean(non_fomc_week_rv):.2f}%")
print(f"   Ratio: {np.nanmean(fomc_week_rv)/np.nanmean(non_fomc_week_rv):.3f}")
print(f"   t={t_wk:.3f}, p={p_wk:.4f}")

# Finding 6: VIX regime interaction
results['findings']['vix_regime_interaction'] = {
    'high_vix_fomc_n': len(high_vix_fomc),
    'high_vix_abs_ret': float(high_vix_fomc['fomc_day_abs_ret'].mean()) if len(high_vix_fomc) > 0 else None,
    'low_vix_abs_ret': float(low_vix_fomc['fomc_day_abs_ret'].mean()) if len(low_vix_fomc) > 0 else None,
    'vix_slope_on_fomc_ret': float(slope),
    'vix_slope_t': float(t_slope),
    'vix_slope_r2': float(r_squared),
}
print(f"\n6. VIX x FOMC Interaction:")
print(f"   |Ret| ~ VIX: slope={slope:.4f}, t={t_slope:.3f}, R²={r_squared:.4f}")

# Overall verdict
print(f"\n{'='*70}")
print("VERDICT:")
fomc_has_vol_effect = p_pre_post < 0.05 or p_wk < 0.05
vix_resolves = drop_rate > 0.55
trading_signal = abs(t_dm) > 3.0

if fomc_has_vol_effect:
    print("  ✓ FOMC has a detectable effect on realized volatility")
else:
    print("  ✗ FOMC vol premium NOT statistically significant")

if vix_resolves:
    print(f"  ✓ VIX drops after {drop_rate*100:.0f}% of FOMC meetings (uncertainty resolution)")
else:
    print("  ✗ VIX uncertainty resolution is weak")

if trading_signal:
    print("  ✓ FOMC-aware VT generates significant alpha (Harvey-approved)")
else:
    print("  ✗ FOMC calendar overlay does NOT improve VT (FAIL Harvey)")
    print("    → VIX sufficient statistic confirmed: FOMC calendar adds nothing beyond VIX")

results['verdict'] = {
    'fomc_vol_effect': fomc_has_vol_effect,
    'vix_uncertainty_resolution': vix_resolves,
    'trading_signal': trading_signal,
    'conclusion': 'VIX already captures FOMC uncertainty; calendar overlay is redundant'
        if not trading_signal else 'FOMC calendar overlay adds value beyond VIX'
}

print(f"\n{'='*70}")

# Save results
results_path = os.path.join(BASE_DIR, 'experiments', 'k182_fomc_vol_effect_results.json')
# Convert any remaining numpy types
def convert(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj

import json

class NpEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return super().default(obj)

with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, cls=NpEncoder)
print(f"\nResults saved to {results_path}")
