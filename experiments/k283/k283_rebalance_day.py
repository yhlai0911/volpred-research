"""
K283: Does the Day of Month Matter for Rebalancing?
====================================================
Background: K281 confirmed monthly rebalancing is optimal.
But does it matter WHICH day? First trading day? Last? Mid-month?
Options expiration Friday?

Strategy: 50/50 SPY/GLD with 12/VIX monthly rebalance
Data: SPY, GLD, VIX daily from yfinance, 2005-2024
Methodology:
  1. Test all 22 possible start days within a month
  2. Named days: 1st, last, 15th, 3rd Friday
  3. Metrics: Sharpe, MDD, net Sharpe (5bps)
  4. Dispersion: range and std of Sharpe across all 22 start days
  5. 5-period cross-OOS validation
  6. Key question: is there a "best day" or is it noise?

[Proposed: User, Executed: Claude]
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import json

# ══════════════════════════════════════════════════════════════════════
# 1. Download Data
# ══════════════════════════════════════════════════════════════════════
print("=" * 78)
print("K283: Does the Day of Month Matter for Rebalancing?")
print("Strategy: 50/50 SPY/GLD + 12/VIX monthly rebalance")
print("=" * 78)

print("\n[1/6] Downloading SPY, GLD, ^VIX data (2004-2025)...")

tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
raw = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2004-01-01", end="2025-12-31",
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df[["Close"]].rename(columns={"Close": name})

data = raw["SPY"].join(raw["GLD"], how="inner").join(raw["VIX"], how="inner").dropna()
data["spy_ret"] = np.log(data["SPY"] / data["SPY"].shift(1))
data["gld_ret"] = np.log(data["GLD"] / data["GLD"].shift(1))
data = data.dropna()

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  GLD starts: {raw['GLD'].dropna().index[0].date()}")

# ══════════════════════════════════════════════════════════════════════
# 2. VT Weight Computation (12/VIX)
# ══════════════════════════════════════════════════════════════════════
print("\n[2/6] Computing 12/VIX weights...")

data["vt_weight"] = (12.0 / data["VIX"]).clip(0, 1.5)
data["equal_ret"] = 0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]

# Pre-compute month info (vectorized)
data["ym"] = data.index.to_period("M")
data["rank_in_month"] = data.groupby("ym").cumcount()  # 0-indexed
data["weekday"] = data.index.weekday

# Max rank per month (for "last day" and capping)
max_ranks = data.groupby("ym")["rank_in_month"].transform("max")
data["max_rank"] = max_ranks

print(f"  Mean VT weight: {data['vt_weight'].mean():.3f}")
print(f"  VT weight range: [{data['vt_weight'].min():.3f}, {data['vt_weight'].max():.3f}]")

RF_DAILY = 0.04 / 252
TX_COST_BPS = 5


# ══════════════════════════════════════════════════════════════════════
# 3. Vectorized rebalance day identification + portfolio simulation
# ══════════════════════════════════════════════════════════════════════

def make_rebal_mask_nth(df, n):
    """Boolean mask: True on n-th trading day of each month (0-indexed).
    If month has fewer days, use last available."""
    target = np.minimum(n, df["max_rank"].values)
    return df["rank_in_month"].values == target


def make_rebal_mask_last(df):
    """Boolean mask: True on last trading day of each month."""
    return df["rank_in_month"].values == df["max_rank"].values


def make_rebal_mask_nearest_15th(df):
    """Boolean mask: True on trading day nearest to 15th."""
    mask = np.zeros(len(df), dtype=bool)
    for ym, group in df.groupby("ym"):
        target = pd.Timestamp(year=ym.start_time.year,
                              month=ym.start_time.month, day=15)
        diffs = (group.index - target).to_series().abs()
        best_idx = diffs.values.argmin()
        iloc_pos = df.index.get_loc(group.index[best_idx])
        mask[iloc_pos] = True
    return mask


def make_rebal_mask_3rd_friday(df):
    """Boolean mask: True on 3rd Friday of each month."""
    mask = np.zeros(len(df), dtype=bool)
    fridays = df[df["weekday"] == 4]
    for ym, group in fridays.groupby(fridays.index.to_period("M")):
        if len(group) >= 3:
            iloc_pos = df.index.get_loc(group.index[2])
        elif len(group) > 0:
            iloc_pos = df.index.get_loc(group.index[-1])
        else:
            continue
        mask[iloc_pos] = True
    return mask


def simulate_rebalance(vt_weights, equal_returns, rebal_mask):
    """Vectorized-ish portfolio simulation with monthly rebalance.
    Uses numpy for speed. Returns (port_returns, weights, n_trades)."""
    n = len(vt_weights)
    weights = np.empty(n)
    port_returns = np.empty(n)

    current_w = vt_weights[0]
    n_trades = 0

    for t in range(n):
        if rebal_mask[t]:
            new_w = vt_weights[t]
            if abs(new_w - current_w) > 0.001:
                n_trades += 1
            current_w = new_w
        weights[t] = current_w
        port_returns[t] = current_w * equal_returns[t]

    return port_returns, weights, n_trades


def compute_metrics(port_returns, weights, n_trades, name=""):
    """Compute full performance metrics from simulated returns."""
    n = len(port_returns)
    total_years = n / 252

    cum_ret = np.exp(np.cumsum(port_returns))
    ann_ret = (cum_ret[-1] ** (1 / total_years)) - 1
    ann_vol = np.std(port_returns) * np.sqrt(252)
    sharpe = (np.mean(port_returns) - RF_DAILY) / np.std(port_returns) * np.sqrt(252)

    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = cum_ret / running_max - 1
    max_dd = np.min(drawdowns)

    weight_changes = np.abs(np.diff(weights))
    ann_turnover = np.sum(weight_changes) / total_years
    total_tx_cost = np.sum(weight_changes) * TX_COST_BPS / 10000
    tx_drag_annual = total_tx_cost / total_years
    net_ann_ret = ann_ret - tx_drag_annual
    net_sharpe = (net_ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

    calmar = ann_ret / abs(max_dd) if max_dd != 0 else np.inf

    down_rets = port_returns[port_returns < 0]
    downside_vol = np.std(down_rets) * np.sqrt(252) if len(down_rets) > 0 else 1e-6
    sortino = (ann_ret - 0.04) / downside_vol

    # Monthly win rate (approximate: group by ~21 day chunks)
    # Use pandas for accuracy
    idx = pd.RangeIndex(n)
    monthly_groups = idx // 21
    monthly_sums = pd.Series(port_returns).groupby(monthly_groups).sum()
    win_rate = (monthly_sums > 0).mean()

    return {
        "name": name,
        "sharpe": sharpe,
        "net_sharpe": net_sharpe,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "max_dd": max_dd,
        "calmar": calmar,
        "sortino": sortino,
        "n_trades": n_trades,
        "trades_per_year": n_trades / total_years,
        "ann_turnover": ann_turnover,
        "tx_drag_annual": tx_drag_annual,
        "win_rate_monthly": win_rate,
        "total_growth": cum_ret[-1],
        "total_years": total_years,
        "avg_weight": np.mean(weights),
    }


def quick_sharpe(vt_weights, equal_returns, rebal_mask):
    """Compute only Sharpe ratio (fast path for dispersion analysis)."""
    n = len(vt_weights)
    port_returns = np.empty(n)
    current_w = vt_weights[0]

    for t in range(n):
        if rebal_mask[t]:
            current_w = vt_weights[t]
        port_returns[t] = current_w * equal_returns[t]

    return (np.mean(port_returns) - RF_DAILY) / np.std(port_returns) * np.sqrt(252)


# ══════════════════════════════════════════════════════════════════════
# 4. Full Sample Analysis: All 22 Start Days
# ══════════════════════════════════════════════════════════════════════
print("\n[3/6] Testing all 22 possible monthly start days (full sample)...")

vt_w = data["vt_weight"].values
eq_ret = data["equal_ret"].values

# Pre-compute all 22 rebalance masks
rebal_masks = {}
for offset in range(22):
    rebal_masks[offset] = make_rebal_mask_nth(data, offset)

all_results = {}
for offset in range(22):
    pr, wts, nt = simulate_rebalance(vt_w, eq_ret, rebal_masks[offset])
    all_results[offset] = compute_metrics(pr, wts, nt, name=f"Day_{offset+1}")
    if (offset + 1) % 5 == 0:
        print(f"    Offset {offset+1}/22 done (Sharpe={all_results[offset]['sharpe']:.4f})")

# Named days
named_masks = {
    "1st_trading_day": make_rebal_mask_nth(data, 0),
    "last_trading_day": make_rebal_mask_last(data),
    "15th_nearest": make_rebal_mask_nearest_15th(data),
    "3rd_friday": make_rebal_mask_3rd_friday(data),
}
named_labels = {
    "1st_trading_day": "1st Trading Day",
    "last_trading_day": "Last Trading Day",
    "15th_nearest": "~15th (Nearest)",
    "3rd_friday": "3rd Friday (OpEx)",
}

named_results = {}
for key, mask in named_masks.items():
    pr, wts, nt = simulate_rebalance(vt_w, eq_ret, mask)
    named_results[key] = compute_metrics(pr, wts, nt, name=named_labels[key])

print("  All 22 offsets + 4 named days computed.")

# ══════════════════════════════════════════════════════════════════════
# 5. Dispersion Analysis
# ══════════════════════════════════════════════════════════════════════
print("\n[4/6] Dispersion analysis across all 22 start days...")

sharpes = np.array([all_results[k]["sharpe"] for k in range(22)])
net_sharpes = np.array([all_results[k]["net_sharpe"] for k in range(22)])
mdds = np.array([all_results[k]["max_dd"] for k in range(22)])
ann_rets = np.array([all_results[k]["ann_return"] for k in range(22)])

n_years_full = all_results[0]["total_years"]
sharpe_se = 1.0 / np.sqrt(n_years_full)
observed_range = sharpes.max() - sharpes.min()
observed_std = sharpes.std()

print(f"\n  Sharpe Ratio across 22 start days:")
print(f"    Mean:   {sharpes.mean():.4f}")
print(f"    Std:    {sharpes.std():.4f}")
print(f"    Min:    {sharpes.min():.4f} (Day {np.argmin(sharpes)+1})")
print(f"    Max:    {sharpes.max():.4f} (Day {np.argmax(sharpes)+1})")
print(f"    Range:  {observed_range:.4f}")
print(f"    CV:     {sharpes.std()/sharpes.mean()*100:.1f}%")

print(f"\n  Net Sharpe (5bps) across 22 start days:")
print(f"    Mean:   {net_sharpes.mean():.4f}")
print(f"    Std:    {net_sharpes.std():.4f}")
print(f"    Range:  {net_sharpes.max() - net_sharpes.min():.4f}")

print(f"\n  MDD across 22 start days:")
print(f"    Mean:   {mdds.mean():.2%}")
print(f"    Std:    {mdds.std():.2%}")
print(f"    Best:   {mdds.max():.2%} (Day {np.argmax(mdds)+1})")
print(f"    Worst:  {mdds.min():.2%} (Day {np.argmin(mdds)+1})")
print(f"    Range:  {(mdds.max() - mdds.min()):.2%}")

print(f"\n  Sharpe SE ({n_years_full:.0f}-year sample): {sharpe_se:.4f}")
print(f"  Range / SE = {observed_range / sharpe_se:.2f}")
print(f"  => Range {'< 1 SE: noise' if observed_range < sharpe_se else '< 2 SE: likely noise' if observed_range < 2*sharpe_se else '>= 2 SE: possibly meaningful'}")

# ══════════════════════════════════════════════════════════════════════
# 6. Named Days Comparison Table
# ══════════════════════════════════════════════════════════════════════
print("\n[5/6] Named days comparison...")
print("\n" + "=" * 90)
print(f"{'Day':>22} {'Sharpe':>8} {'Net Sh':>8} {'Ann Ret':>9} {'MDD':>9} "
      f"{'Calmar':>8} {'Trades/Y':>9} {'Win%':>7}")
print("-" * 90)

named_keys = ["1st_trading_day", "last_trading_day", "15th_nearest", "3rd_friday"]
for key in named_keys:
    r = named_results[key]
    print(f"{r['name']:>22} {r['sharpe']:>8.4f} {r['net_sharpe']:>8.4f} "
          f"{r['ann_return']:>8.2%} {r['max_dd']:>8.2%} "
          f"{r['calmar']:>8.2f} {r['trades_per_year']:>9.1f} "
          f"{r['win_rate_monthly']:>6.1%}")

print("-" * 90)
print(f"{'22-day Mean':>22} {sharpes.mean():>8.4f} {net_sharpes.mean():>8.4f} "
      f"{ann_rets.mean():>8.2%} {mdds.mean():>8.2%}")
print(f"{'22-day Std':>22} {sharpes.std():>8.4f} {net_sharpes.std():>8.4f} "
      f"{ann_rets.std():>8.2%} {mdds.std():>8.2%}")
print(f"{'22-day Range':>22} {observed_range:>8.4f} "
      f"{net_sharpes.max()-net_sharpes.min():>8.4f} "
      f"{'':>9} {(mdds.max()-mdds.min()):>8.2%}")

# ══════════════════════════════════════════════════════════════════════
# 7. All 22 Days Detail
# ══════════════════════════════════════════════════════════════════════
print("\n\nAll 22 Start Days (sorted by Sharpe):")
print("-" * 85)
print(f"{'Day':>6} {'Sharpe':>8} {'Net Sh':>8} {'Ann Ret':>9} {'MDD':>9} "
      f"{'Calmar':>8} {'Sortino':>8} {'Growth':>8}")
print("-" * 85)

sorted_offsets = sorted(range(22), key=lambda k: all_results[k]["sharpe"], reverse=True)
for offset in sorted_offsets:
    r = all_results[offset]
    print(f"{'Day '+str(offset+1):>6} {r['sharpe']:>8.4f} {r['net_sharpe']:>8.4f} "
          f"{r['ann_return']:>8.2%} {r['max_dd']:>8.2%} "
          f"{r['calmar']:>8.2f} {r['sortino']:>8.2f} {r['total_growth']:>7.2f}x")

# ══════════════════════════════════════════════════════════════════════
# 8. 5-Period Cross-OOS Validation
# ══════════════════════════════════════════════════════════════════════
print("\n\n[6/6] 5-Period Cross-OOS Validation...")

oos_periods = [
    ("2005-01-01", "2008-12-31", "2005-2008 (GFC)"),
    ("2009-01-01", "2012-12-31", "2009-2012 (Recovery)"),
    ("2013-01-01", "2016-12-31", "2013-2016 (Low Vol)"),
    ("2017-01-01", "2020-12-31", "2017-2020 (COVID)"),
    ("2021-01-01", "2024-12-31", "2021-2024 (Post-COVID)"),
]

oos_results = {}

for start, end, period_name in oos_periods:
    mask = (data.index >= start) & (data.index <= end)
    pdata = data[mask].copy()
    if len(pdata) < 252:
        print(f"  Skipping {period_name}: only {len(pdata)} days")
        continue

    p_vt_w = pdata["vt_weight"].values
    p_eq_ret = pdata["equal_ret"].values

    oos_results[period_name] = {"offsets": {}, "named": {}}

    # All 22 offsets
    for offset in range(22):
        rmask = make_rebal_mask_nth(pdata, offset)
        sh = quick_sharpe(p_vt_w, p_eq_ret, rmask)
        oos_results[period_name]["offsets"][offset] = sh

    # Named days
    for key, mask_fn in [
        ("1st_trading_day", lambda d: make_rebal_mask_nth(d, 0)),
        ("last_trading_day", make_rebal_mask_last),
        ("15th_nearest", make_rebal_mask_nearest_15th),
        ("3rd_friday", make_rebal_mask_3rd_friday),
    ]:
        rmask = mask_fn(pdata)
        pr, wts, nt = simulate_rebalance(p_vt_w, p_eq_ret, rmask)
        oos_results[period_name]["named"][key] = compute_metrics(
            pr, wts, nt, name=key)

    sh_vals = list(oos_results[period_name]["offsets"].values())
    print(f"  {period_name}: {len(pdata)} days, "
          f"Sharpe range={max(sh_vals)-min(sh_vals):.4f}")

# Print cross-OOS summary
print("\n\nCross-OOS: Sharpe Range & Std Across 22 Start Days")
print("=" * 85)
print(f"{'Period':>25} {'Mean Sh':>8} {'Std Sh':>8} {'Range':>8} "
      f"{'Best Day':>9} {'Worst Day':>10} {'Range/SE':>9}")
print("-" * 85)

oos_dispersion_summary = []
best_days_per_period = []
for period_name in [p[2] for p in oos_periods]:
    if period_name not in oos_results:
        continue
    offsets = oos_results[period_name]["offsets"]
    sh_arr = np.array([offsets[k] for k in range(22)])
    n_yrs = len(data[(data.index >= [p for p in oos_periods if p[2]==period_name][0][0]) &
                      (data.index <= [p for p in oos_periods if p[2]==period_name][0][1])]) / 252
    se = 1.0 / np.sqrt(n_yrs)
    rng = sh_arr.max() - sh_arr.min()

    best_day = int(np.argmax(sh_arr) + 1)
    worst_day = int(np.argmin(sh_arr) + 1)
    best_days_per_period.append(best_day)

    print(f"{period_name:>25} {sh_arr.mean():>8.4f} {sh_arr.std():>8.4f} "
          f"{rng:>8.4f} {best_day:>9} {worst_day:>10} {rng/se:>9.2f}")

    oos_dispersion_summary.append({
        "period": period_name,
        "mean_sharpe": round(float(sh_arr.mean()), 4),
        "std_sharpe": round(float(sh_arr.std()), 4),
        "range_sharpe": round(float(rng), 4),
        "best_day": best_day,
        "worst_day": worst_day,
        "range_over_se": round(float(rng / se), 3),
    })

# Cross-OOS: Named days comparison
print("\n\nCross-OOS: Named Days Sharpe")
print("=" * 85)
header = f"{'Period':>25}"
named_labels_short = ["1st Day", "Last Day", "~15th", "3rd Fri"]
for label in named_labels_short:
    header += f" {label:>10}"
header += f" {'Range':>8}"
print(header)
print("-" * 85)

named_cross_oos = []
for period_name in [p[2] for p in oos_periods]:
    if period_name not in oos_results:
        continue
    named = oos_results[period_name]["named"]
    row = f"{period_name:>25}"
    vals = []
    for key in named_keys:
        if key in named and named[key] is not None:
            sh = named[key]["sharpe"]
            row += f" {sh:>10.4f}"
            vals.append(sh)
        else:
            row += f" {'N/A':>10}"
    if len(vals) >= 2:
        row += f" {max(vals)-min(vals):>8.4f}"
    print(row)
    named_cross_oos.append({
        "period": period_name,
        "sharpes": {k: round(named[k]["sharpe"], 4) for k in named_keys
                    if k in named and named[k] is not None}
    })

# Persistence check
print("\n\nPersistence Check: Does the best day repeat across OOS periods?")
print("-" * 78)
for i, period_name in enumerate([p[2] for p in oos_periods]):
    if period_name not in oos_results:
        continue
    offsets = oos_results[period_name]["offsets"]
    best_off = max(offsets, key=offsets.get)
    print(f"  {period_name}: Best = Day {best_off+1} "
          f"(Sharpe {offsets[best_off]:.4f})")

from collections import Counter
day_counts = Counter(best_days_per_period)
print(f"\n  Best day frequency: {dict(day_counts)}")
max_appearances = max(day_counts.values()) if day_counts else 0
most_common_day = day_counts.most_common(1)[0][0] if day_counts else 0
print(f"  Most frequent best day: Day {most_common_day} "
      f"({max_appearances}/{len(best_days_per_period)} periods)")

if max_appearances <= 2:
    persistence_msg = "NO persistent 'best day' — consistent with noise"
elif max_appearances <= 3:
    persistence_msg = "WEAK persistence — likely noise with 5 periods"
else:
    persistence_msg = "SOME persistence — but verify statistical significance"
print(f"  => {persistence_msg}")

# ══════════════════════════════════════════════════════════════════════
# 9. F-test / Kruskal-Wallis: Formal test of day-effect
# ══════════════════════════════════════════════════════════════════════
print("\n\nFormal Test: Day-of-Month Effect on Monthly Returns")
print("-" * 78)

# For each of the 22 offsets, collect monthly returns
# Then test: are the means significantly different?
from scipy import stats

monthly_returns_by_offset = {}
for offset in range(22):
    mask = rebal_masks[offset]
    pr, _, _ = simulate_rebalance(vt_w, eq_ret, mask)
    # Resample to monthly
    monthly = pd.Series(pr, index=data.index).resample("ME").sum()
    monthly_returns_by_offset[offset] = monthly.values

# Kruskal-Wallis test (non-parametric ANOVA)
groups = [monthly_returns_by_offset[k] for k in range(22)]
# Ensure equal-ish lengths (some months may differ by 1)
min_len = min(len(g) for g in groups)
groups_trimmed = [g[:min_len] for g in groups]

kw_stat, kw_p = stats.kruskal(*groups_trimmed)
print(f"  Kruskal-Wallis H-statistic: {kw_stat:.4f}")
print(f"  p-value: {kw_p:.4f}")
print(f"  => {'SIGNIFICANT (p<0.05)' if kw_p < 0.05 else 'NOT significant (p>0.05): no day-of-month effect'}")

# Also test pairwise: best vs worst offset
best_off = int(np.argmax(sharpes))
worst_off = int(np.argmin(sharpes))
t_stat, t_p = stats.ttest_ind(
    monthly_returns_by_offset[best_off],
    monthly_returns_by_offset[worst_off]
)
print(f"\n  Pairwise t-test (Day {best_off+1} vs Day {worst_off+1}):")
print(f"    t-statistic: {t_stat:.4f}")
print(f"    p-value: {t_p:.4f}")
print(f"    => {'SIGNIFICANT' if t_p < 0.05 else 'NOT significant: best and worst day indistinguishable'}")

# ══════════════════════════════════════════════════════════════════════
# 10. Summary & Practical Recommendation
# ══════════════════════════════════════════════════════════════════════
print("\n\n" + "=" * 78)
print("SUMMARY: K283 — Does Day of Month Matter for Rebalancing?")
print("=" * 78)

day_matters = kw_p < 0.05 and max_appearances >= 3

if observed_range < sharpe_se:
    disp_label = "range < 1 SE (noise)"
elif observed_range < 2 * sharpe_se:
    disp_label = "range < 2 SE (likely noise)"
else:
    disp_label = "range >= 2 SE (possibly meaningful)"

print(f"""
Strategy: 50/50 SPY/GLD + 12/VIX, monthly rebalance
Data: {data.index[0].date()} to {data.index[-1].date()} ({len(data)} days, {n_years_full:.1f} years)
TX cost: {TX_COST_BPS} bps one-way

FULL SAMPLE DISPERSION (22 possible start days):
  Sharpe: mean={sharpes.mean():.4f}, std={sharpes.std():.4f}, range={observed_range:.4f}
  Net Sharpe (5bps): mean={net_sharpes.mean():.4f}, std={net_sharpes.std():.4f}
  MDD: mean={mdds.mean():.2%}, range={(mdds.max()-mdds.min()):.2%}
  Sharpe SE: {sharpe_se:.4f}
  Range/SE: {observed_range/sharpe_se:.3f}
  Dispersion assessment: {disp_label}

NAMED DAYS (full sample):
  1st Trading Day: Sharpe {named_results['1st_trading_day']['sharpe']:.4f}, Net {named_results['1st_trading_day']['net_sharpe']:.4f}, MDD {named_results['1st_trading_day']['max_dd']:.2%}
  Last Trading Day: Sharpe {named_results['last_trading_day']['sharpe']:.4f}, Net {named_results['last_trading_day']['net_sharpe']:.4f}, MDD {named_results['last_trading_day']['max_dd']:.2%}
  ~15th (Mid-month): Sharpe {named_results['15th_nearest']['sharpe']:.4f}, Net {named_results['15th_nearest']['net_sharpe']:.4f}, MDD {named_results['15th_nearest']['max_dd']:.2%}
  3rd Friday (OpEx): Sharpe {named_results['3rd_friday']['sharpe']:.4f}, Net {named_results['3rd_friday']['net_sharpe']:.4f}, MDD {named_results['3rd_friday']['max_dd']:.2%}

STATISTICAL TESTS:
  Kruskal-Wallis: H={kw_stat:.4f}, p={kw_p:.4f} ({'significant' if kw_p < 0.05 else 'not significant'})
  Best vs Worst: t={t_stat:.4f}, p={t_p:.4f} ({'significant' if t_p < 0.05 else 'not significant'})

CROSS-OOS PERSISTENCE:
  Best day per period: {best_days_per_period}
  Frequency: {dict(day_counts)}
  {persistence_msg}

CONCLUSION:
  Day-of-month choice {'MATTERS' if day_matters else 'DOES NOT MATTER'} for rebalancing.
  {'The effect is statistically significant.' if day_matters else 'Dispersion is within sampling noise.'}
  PRACTICAL ADVICE: Rebalance on your most convenient day — payday, month-end,
  or any regular schedule. There is no evidence of a systematic "best day."
""")

# ══════════════════════════════════════════════════════════════════════
# 11. Save Results
# ══════════════════════════════════════════════════════════════════════
output = {
    "experiment": "K283",
    "title": "Does the Day of Month Matter for Rebalancing?",
    "strategy": "50/50 SPY/GLD + 12/VIX monthly rebalance",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_days": int(len(data)),
    "n_years": round(float(n_years_full), 1),
    "tx_cost_bps": TX_COST_BPS,
    "full_sample": {
        "sharpe_mean": round(float(sharpes.mean()), 4),
        "sharpe_std": round(float(sharpes.std()), 4),
        "sharpe_range": round(float(observed_range), 4),
        "sharpe_min": round(float(sharpes.min()), 4),
        "sharpe_max": round(float(sharpes.max()), 4),
        "sharpe_se": round(float(sharpe_se), 4),
        "range_over_se": round(float(observed_range / sharpe_se), 3),
        "net_sharpe_mean": round(float(net_sharpes.mean()), 4),
        "net_sharpe_std": round(float(net_sharpes.std()), 4),
        "mdd_mean": round(float(mdds.mean()), 4),
        "mdd_range": round(float(mdds.max() - mdds.min()), 4),
        "all_22_days": {
            f"day_{k+1}": {
                "sharpe": round(float(all_results[k]["sharpe"]), 4),
                "net_sharpe": round(float(all_results[k]["net_sharpe"]), 4),
                "ann_return": round(float(all_results[k]["ann_return"]), 4),
                "max_dd": round(float(all_results[k]["max_dd"]), 4),
            } for k in range(22)
        },
    },
    "named_days": {
        key: {
            "sharpe": round(float(named_results[key]["sharpe"]), 4),
            "net_sharpe": round(float(named_results[key]["net_sharpe"]), 4),
            "ann_return": round(float(named_results[key]["ann_return"]), 4),
            "max_dd": round(float(named_results[key]["max_dd"]), 4),
            "calmar": round(float(named_results[key]["calmar"]), 2),
            "sortino": round(float(named_results[key]["sortino"]), 2),
        } for key in named_keys
    },
    "statistical_tests": {
        "kruskal_wallis": {
            "H_statistic": round(float(kw_stat), 4),
            "p_value": round(float(kw_p), 4),
            "significant": bool(kw_p < 0.05),
        },
        "best_vs_worst_ttest": {
            "best_day": int(best_off + 1),
            "worst_day": int(worst_off + 1),
            "t_statistic": round(float(t_stat), 4),
            "p_value": round(float(t_p), 4),
            "significant": bool(t_p < 0.05),
        },
    },
    "cross_oos": {
        "periods": oos_dispersion_summary,
        "named_comparison": named_cross_oos,
        "best_day_per_period": best_days_per_period,
        "best_day_persistent": bool(max_appearances >= 3),
    },
    "conclusion": {
        "day_matters": bool(day_matters),
        "dispersion_assessment": disp_label,
        "recommendation": "Rebalance on most convenient day (payday, month-end, etc.)",
        "best_day_persistent": bool(max_appearances >= 3),
    },
}

out_path = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a4c16424/experiments/k283_rebalance_day_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"Results saved to {out_path}")

print("\n" + "=" * 78)
print("K283 complete.")
print("=" * 78)
