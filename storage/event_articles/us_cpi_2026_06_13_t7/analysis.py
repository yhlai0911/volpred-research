"""
US CPI 2026-06-13 T-7 Preview: VIX event study analysis
Evidence package for VolPred event article
"""

import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import yfinance as yf
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

# ─── 1. Data Download ───────────────────────────────────────────────────────

print("Downloading VIX, VIX9D, SPY data...")
start = "2025-05-01"
end = "2026-05-26"

vix = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
vix9d = yf.download("^VIX9D", start=start, end=end, auto_adjust=True, progress=False)
spy = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)

vix_close = vix['Close'].squeeze()
vix9d_close = vix9d['Close'].squeeze()
spy_close = spy['Close'].squeeze()

print(f"VIX: {len(vix_close)} trading days, {vix_close.index[0].date()} to {vix_close.index[-1].date()}")
print(f"VIX9D: {len(vix9d_close)} trading days")
print(f"SPY: {len(spy_close)} trading days")

# ─── 2. CPI Release Dates (last 13 months: 2025-05 to 2026-05) ──────────────

# BLS actual release dates (confirmed from BLS calendar)
cpi_dates = pd.to_datetime([
    "2025-05-13",  # April 2025 CPI
    "2025-06-11",  # May 2025 CPI
    "2025-07-15",  # June 2025 CPI
    "2025-08-12",  # July 2025 CPI
    "2025-09-11",  # August 2025 CPI
    "2025-10-15",  # September 2025 CPI
    "2025-11-13",  # October 2025 CPI
    "2025-12-10",  # November 2025 CPI
    "2026-01-14",  # December 2025 CPI
    "2026-02-12",  # January 2026 CPI
    "2026-03-12",  # February 2026 CPI
    "2026-04-10",  # March 2026 CPI
    "2026-05-13",  # April 2026 CPI
])

print(f"\nCPI release dates in sample: {len(cpi_dates)}")
for d in cpi_dates:
    in_range = d in vix_close.index
    print(f"  {d.date()}: {'in VIX data' if in_range else 'MISSING (use closest)'}")

# ─── 3. Find closest trading day for each CPI release ─────────────────────

def find_closest_trading_day(target_date, index):
    """Find the closest trading day in index to target_date."""
    if target_date in index:
        return target_date
    # Search forward/backward up to 5 days
    for delta in range(1, 6):
        fwd = target_date + pd.Timedelta(days=delta)
        bwd = target_date - pd.Timedelta(days=delta)
        if fwd in index:
            return fwd
        if bwd in index:
            return bwd
    return None

cpi_trading_days = []
for d in cpi_dates:
    td = find_closest_trading_day(d, vix_close.index)
    if td is not None:
        cpi_trading_days.append(td)
        print(f"  CPI {d.date()} → trading day {td.date()}")

print(f"\nMatched {len(cpi_trading_days)} CPI days to trading days")

# ─── 4. Primary Evidence Numbers ────────────────────────────────────────────

# 4.1: CPI release day VIX % change
print("\n=== 4.1 CPI Day VIX % Change ===")
vix_pct_changes = []
for td in cpi_trading_days:
    pos = vix_close.index.get_loc(td)
    if pos > 0:
        prev = vix_close.iloc[pos - 1]
        curr = vix_close.iloc[pos]
        pct = (curr - prev) / prev * 100
        vix_pct_changes.append({
            'date': td,
            'vix_prev': float(prev),
            'vix_cpi_day': float(curr),
            'vix_pct_change': float(pct)
        })

vix_changes_arr = np.array([x['vix_pct_change'] for x in vix_pct_changes])
print(f"N CPI days with prev: {len(vix_changes_arr)}")
print(f"Mean VIX % change on CPI day: {vix_changes_arr.mean():.2f}%")
print(f"Median: {np.median(vix_changes_arr):.2f}%")
print(f"Std: {vix_changes_arr.std():.2f}%")
print(f"5th pct: {np.percentile(vix_changes_arr, 5):.2f}%")
print(f"95th pct: {np.percentile(vix_changes_arr, 95):.2f}%")
print(f"Min: {vix_changes_arr.min():.2f}%")
print(f"Max: {vix_changes_arr.max():.2f}%")

# 4.2: VIX/VIX9D ratio on CPI days vs non-event baseline
print("\n=== 4.2 VIX9D/VIX Ratio on CPI Days vs Baseline ===")
# Align VIX and VIX9D
common_idx = vix_close.index.intersection(vix9d_close.index)
vix_aligned = vix_close.loc[common_idx]
vix9d_aligned = vix9d_close.loc[common_idx]
ratio = vix9d_aligned / vix_aligned  # VIX9D/VIX ratio

# CPI day ratio
cpi_ratio_vals = []
for td in cpi_trading_days:
    if td in ratio.index:
        cpi_ratio_vals.append(float(ratio.loc[td]))

# Baseline: non-CPI days
non_cpi_mask = ~ratio.index.isin(cpi_trading_days)
baseline_ratio = ratio.loc[non_cpi_mask]

cpi_ratio_arr = np.array(cpi_ratio_vals)
baseline_ratio_arr = baseline_ratio.values

print(f"CPI day VIX9D/VIX ratio: mean={cpi_ratio_arr.mean():.4f}, std={cpi_ratio_arr.std():.4f}")
print(f"Non-CPI baseline ratio: mean={baseline_ratio_arr.mean():.4f}, std={baseline_ratio_arr.std():.4f}")
print(f"Ratio difference (CPI - baseline): {cpi_ratio_arr.mean() - baseline_ratio_arr.mean():.4f}")

# t-test CPI day ratio vs baseline
tstat, pval = stats.ttest_ind(cpi_ratio_arr, baseline_ratio_arr)
print(f"t-test: t={tstat:.3f}, p={pval:.4f}")

# 4.3: VIX revert/persist after CPI (5 trading days)
print("\n=== 4.3 VIX Post-CPI 5-Day Behavior ===")
post_cpi_changes = {1: [], 2: [], 3: [], 4: [], 5: []}
post_cpi_vix9d_ratio = {-2: [], -1: [], 0: [], 1: [], 2: [], 3: [], 4: [], 5: []}

for td in cpi_trading_days:
    if td not in vix_close.index:
        continue
    pos = vix_close.index.get_loc(td)
    cpi_vix = vix_close.iloc[pos]

    for lag in range(1, 6):
        if pos + lag < len(vix_close):
            future_vix = vix_close.iloc[pos + lag]
            pct = (future_vix - cpi_vix) / cpi_vix * 100
            post_cpi_changes[lag].append(float(pct))

    # Ratio event window: -2 to +5
    for offset in range(-2, 6):
        idx_pos = pos + offset
        if 0 <= idx_pos < len(ratio.index):
            day = vix_close.index[pos + offset] if 0 <= pos + offset < len(vix_close) else None
            if day is not None and day in ratio.index:
                post_cpi_vix9d_ratio[offset].append(float(ratio.loc[day]))

print("CPI day VIX % change from release:")
for lag in range(1, 6):
    arr = np.array(post_cpi_changes[lag])
    if len(arr) > 0:
        print(f"  T+{lag}: mean={arr.mean():.2f}%, median={np.median(arr):.2f}%, n={len(arr)}")

print("\nVIX9D/VIX ratio event window (relative to CPI day):")
for offset in sorted(post_cpi_vix9d_ratio.keys()):
    arr = np.array(post_cpi_vix9d_ratio[offset])
    if len(arr) > 0:
        print(f"  T{offset:+d}: mean={arr.mean():.4f}, n={len(arr)}")

# ─── 5. Build Summary Table ─────────────────────────────────────────────────

table_rows = []
for row in vix_pct_changes:
    td = row['date']
    ratio_val = float(ratio.loc[td]) if td in ratio.index else None
    # post-5d change
    pos = vix_close.index.get_loc(td)
    if pos + 5 < len(vix_close):
        post5 = (vix_close.iloc[pos + 5] - vix_close.iloc[pos]) / vix_close.iloc[pos] * 100
    else:
        post5 = None

    table_rows.append({
        'CPI 發布日': td.strftime('%Y-%m-%d'),
        'VIX（T-1）': round(row['vix_prev'], 2),
        'VIX（當日）': round(row['vix_cpi_day'], 2),
        'VIX 當日漲跌': f"{row['vix_pct_change']:+.1f}%",
        'VIX9D/VIX 比值': f"{ratio_val:.3f}" if ratio_val else 'N/A',
        'VIX T+5 變化': f"{post5:+.1f}%" if post5 is not None else 'N/A',
    })

df_table = pd.DataFrame(table_rows)
print("\nSummary Table:")
print(df_table.to_string(index=False))

# ─── 6. Figure 1: CPI Day VIX % Change Distribution ────────────────────────

fig1, ax = plt.subplots(figsize=(9, 5))
colors = ['#d32f2f' if x > 0 else '#1565c0' for x in vix_changes_arr]
bars = ax.bar(range(len(vix_changes_arr)), vix_changes_arr, color=colors, alpha=0.8, edgecolor='white')
ax.axhline(0, color='black', linewidth=0.8, linestyle='--', alpha=0.5)
ax.axhline(vix_changes_arr.mean(), color='#ff6f00', linewidth=2, linestyle='-',
           label=f'平均值 {vix_changes_arr.mean():+.1f}%')
ax.axhline(np.median(vix_changes_arr), color='#7b1fa2', linewidth=2, linestyle='--',
           label=f'中位數 {np.median(vix_changes_arr):+.1f}%')

# Fill between 5th-95th percentile range indicator
p5, p95 = np.percentile(vix_changes_arr, 5), np.percentile(vix_changes_arr, 95)
ax.axhspan(p5, p95, alpha=0.07, color='grey', label=f'5th–95th 區間 ({p5:.1f}% ~ {p95:.1f}%)')

# x-axis labels
labels = [pd.Timestamp(r['date']).strftime('%y-%m') for r in vix_pct_changes]
ax.set_xticks(range(len(vix_changes_arr)))
ax.set_xticklabels(labels, rotation=45, ha='right', fontsize=9)

ax.set_xlabel('CPI 發布月份', fontsize=11)
ax.set_ylabel('VIX 當日漲跌幅（%）', fontsize=11)
ax.set_title('近 13 個月 US CPI 發布日 VIX 漲跌幅\n（2025-05 至 2026-05，共 13 次）', fontsize=13, fontweight='bold')
ax.legend(fontsize=9, loc='upper left')
ax.yaxis.grid(True, alpha=0.3)
ax.set_axisbelow(True)

# Annotate each bar with value
for i, v in enumerate(vix_changes_arr):
    ax.text(i, v + (0.3 if v >= 0 else -0.5), f'{v:+.1f}', ha='center', va='bottom' if v >= 0 else 'top',
            fontsize=7.5, color='#333')

fig1.text(0.99, 0.01, '資料來源：yfinance / CBOE ^VIX；VolPred K490 研究框架',
          ha='right', va='bottom', fontsize=7, color='grey')
plt.tight_layout()
fig1.savefig('/Users/yhlai0911/Desktop/volpred-research/storage/event_articles/us_cpi_2026_06_13_t7/fig1_cpi_day_vix_dist.png',
             dpi=150, bbox_inches='tight')
plt.close()
print("\nFig 1 saved: fig1_cpi_day_vix_dist.png")

# ─── 7. Figure 2: VIX9D/VIX Ratio Event Window ──────────────────────────────

fig2, ax2 = plt.subplots(figsize=(9, 5))
offsets = sorted([k for k in post_cpi_vix9d_ratio.keys() if len(post_cpi_vix9d_ratio[k]) >= 3])
means = [np.mean(post_cpi_vix9d_ratio[o]) for o in offsets]
stds = [np.std(post_cpi_vix9d_ratio[o]) / np.sqrt(len(post_cpi_vix9d_ratio[o])) for o in offsets]  # SE

ax2.plot(offsets, means, 'o-', color='#1565c0', linewidth=2.2, markersize=7, label='CPI 事件窗口平均')
ax2.fill_between(offsets,
                 np.array(means) - np.array(stds),
                 np.array(means) + np.array(stds),
                 alpha=0.2, color='#1565c0', label='±1 SE 信賴帶')

# Baseline horizontal line
ax2.axhline(baseline_ratio_arr.mean(), color='#ff6f00', linewidth=1.8, linestyle='--',
            label=f'非 CPI 日基準 {baseline_ratio_arr.mean():.3f}')

ax2.axvline(0, color='red', linewidth=1.2, linestyle=':', alpha=0.8)
ax2.text(0.1, ax2.get_ylim()[0] + 0.001, 'CPI 發布日', color='red', fontsize=9, rotation=90, va='bottom')

ax2.set_xlabel('CPI 發布日相對交易日（0=發布日）', fontsize=11)
ax2.set_ylabel('VIX9D / VIX 比值', fontsize=11)
ax2.set_title('CPI 事件窗口 VIX9D/VIX 比值路徑\n（2025-05 至 2026-05，13 次平均）', fontsize=13, fontweight='bold')
ax2.legend(fontsize=9)
ax2.yaxis.grid(True, alpha=0.3)
ax2.xaxis.set_major_locator(plt.MultipleLocator(1))
ax2.set_axisbelow(True)

fig2.text(0.99, 0.01, '資料來源：yfinance / CBOE ^VIX ^VIX9D；VolPred K490 研究框架',
          ha='right', va='bottom', fontsize=7, color='grey')
plt.tight_layout()
fig2.savefig('/Users/yhlai0911/Desktop/volpred-research/storage/event_articles/us_cpi_2026_06_13_t7/fig2_vix_term_event_window.png',
             dpi=150, bbox_inches='tight')
plt.close()
print("Fig 2 saved: fig2_vix_term_event_window.png")

# ─── 8. Save evidence JSON ──────────────────────────────────────────────────

evidence = {
    "event": "US CPI 2026-06-13",
    "article_slot": "T-7",
    "data_period": f"{start} to {end}",
    "cpi_dates_n": len(cpi_trading_days),
    "primary_numbers": {
        "cpi_day_vix_pct_change": {
            "mean": round(float(vix_changes_arr.mean()), 3),
            "median": round(float(np.median(vix_changes_arr)), 3),
            "std": round(float(vix_changes_arr.std()), 3),
            "p5": round(float(np.percentile(vix_changes_arr, 5)), 3),
            "p95": round(float(np.percentile(vix_changes_arr, 95)), 3),
            "min": round(float(vix_changes_arr.min()), 3),
            "max": round(float(vix_changes_arr.max()), 3),
            "n": len(vix_changes_arr)
        },
        "vix9d_vix_ratio": {
            "cpi_day_mean": round(float(cpi_ratio_arr.mean()), 4),
            "cpi_day_std": round(float(cpi_ratio_arr.std()), 4),
            "baseline_mean": round(float(baseline_ratio_arr.mean()), 4),
            "baseline_std": round(float(baseline_ratio_arr.std()), 4),
            "difference": round(float(cpi_ratio_arr.mean() - baseline_ratio_arr.mean()), 4),
            "ttest_stat": round(float(tstat), 3),
            "ttest_pval": round(float(pval), 4)
        },
        "post_cpi_5day_vix": {
            f"T+{lag}": {
                "mean": round(float(np.mean(post_cpi_changes[lag])), 3),
                "median": round(float(np.median(post_cpi_changes[lag])), 3),
                "n": len(post_cpi_changes[lag])
            }
            for lag in range(1, 6) if post_cpi_changes[lag]
        }
    },
    "table_rows": table_rows,
    "ratio_event_window": {
        str(k): {
            "mean": round(float(np.mean(v)), 4),
            "n": len(v)
        }
        for k, v in post_cpi_vix9d_ratio.items() if v
    }
}

with open('/Users/yhlai0911/Desktop/volpred-research/storage/event_articles/us_cpi_2026_06_13_t7/evidence.json', 'w') as f:
    json.dump(evidence, f, ensure_ascii=False, indent=2, default=str)

print("\nEvidence saved to evidence.json")
print("\n=== SUMMARY OF PRIMARY NUMBERS ===")
print(json.dumps(evidence['primary_numbers'], ensure_ascii=False, indent=2))
