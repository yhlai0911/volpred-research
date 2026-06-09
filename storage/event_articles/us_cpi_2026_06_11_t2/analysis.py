"""
US CPI 2026-06-11 T-2 Preview: Recent CPI reaction trend + current VIX/VIX9D positioning
Evidence package for VolPred T-2 event article (differentiated from T-7).

T-2 focus:
  (a) Recent 4 CPI reactions (2026-02 → 2026-05) — variance compression trend
  (b) Current VIX / VIX9D term-structure (latest ~10 trading days)
  (c) Pre-event positioning signals: IV already priced or not
"""

import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import yfinance as yf
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

OUT_DIR = "/Users/yhlai0911/Desktop/volpred-research/storage/event_articles/us_cpi_2026_06_11_t2"

# ─── 1. Data Download (extend to 2026-06-08, latest fully-closed trading day) ──

print("Downloading VIX, VIX9D, SPY data...")
start = "2025-05-01"
end = "2026-06-09"  # exclusive upper bound; last closed day = 2026-06-08

vix = yf.download("^VIX", start=start, end=end, auto_adjust=True, progress=False)
vix9d = yf.download("^VIX9D", start=start, end=end, auto_adjust=True, progress=False)
spy = yf.download("SPY", start=start, end=end, auto_adjust=True, progress=False)

vix_close = vix['Close'].squeeze()
vix9d_close = vix9d['Close'].squeeze()
spy_close = spy['Close'].squeeze()

print(f"VIX: {len(vix_close)} trading days, {vix_close.index[0].date()} to {vix_close.index[-1].date()}")
print(f"VIX9D: {len(vix9d_close)} trading days")
print(f"SPY: {len(spy_close)} trading days")

# ─── 2. CPI Release Dates (13 months baseline, same as T-7) ─────────────────

cpi_dates = pd.to_datetime([
    "2025-05-13",
    "2025-06-11",
    "2025-07-15",
    "2025-08-12",
    "2025-09-11",
    "2025-10-15",
    "2025-11-13",
    "2025-12-10",
    "2026-01-14",
    "2026-02-12",  # Recent 4 starts here
    "2026-03-12",
    "2026-04-10",
    "2026-05-13",
])

# Recent-4 subset (T-2 angle)
recent4 = cpi_dates[-4:]

# ─── 3. Find closest trading day ────────────────────────────────────────────

def find_closest_trading_day(target_date, index):
    if target_date in index:
        return target_date
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

recent4_td = []
for d in recent4:
    td = find_closest_trading_day(d, vix_close.index)
    if td is not None:
        recent4_td.append(td)

print(f"\nFull baseline N={len(cpi_trading_days)}; recent-4 N={len(recent4_td)}")

# ─── 4. CPI Day VIX % Change ────────────────────────────────────────────────

def vix_pct(td):
    pos = vix_close.index.get_loc(td)
    if pos == 0:
        return None
    prev = vix_close.iloc[pos - 1]
    curr = vix_close.iloc[pos]
    return float((curr - prev) / prev * 100), float(prev), float(curr)

vix_changes_all = []
for td in cpi_trading_days:
    r = vix_pct(td)
    if r is not None:
        pct, prev, curr = r
        vix_changes_all.append({'date': td, 'pct': pct, 'prev': prev, 'curr': curr})

vix_changes_arr_all = np.array([x['pct'] for x in vix_changes_all])

# Recent 4 subset
vix_changes_recent4 = [x for x in vix_changes_all if x['date'] in recent4_td]
recent4_arr = np.array([x['pct'] for x in vix_changes_recent4])

# Earlier 9 subset
earlier9 = [x for x in vix_changes_all if x['date'] not in recent4_td]
earlier9_arr = np.array([x['pct'] for x in earlier9])

print("\n=== Recent 4 CPI Day VIX % Change (T-2 focus) ===")
for x in vix_changes_recent4:
    print(f"  {x['date'].date()}  VIX {x['prev']:.2f} -> {x['curr']:.2f}  ({x['pct']:+.2f}%)")
print(f"Recent-4 mean:   {recent4_arr.mean():+.2f}%")
print(f"Recent-4 std:    {recent4_arr.std():.2f}%")
print(f"Earlier-9 mean:  {earlier9_arr.mean():+.2f}%")
print(f"Earlier-9 std:   {earlier9_arr.std():.2f}%")
print(f"Full-13 std:     {vix_changes_arr_all.std():.2f}%")

# Variance compression F-test (one-sided: earlier > recent)
F_stat = earlier9_arr.var(ddof=1) / recent4_arr.var(ddof=1)
df1 = len(earlier9_arr) - 1
df2 = len(recent4_arr) - 1
F_pval = 1 - stats.f.cdf(F_stat, df1, df2)
print(f"F-test (var_earlier9 / var_recent4): F={F_stat:.3f}, df=({df1},{df2}), one-sided p={F_pval:.4f}")

# ─── 5. Current VIX / VIX9D term structure (latest 10 trading days) ─────────

common_idx = vix_close.index.intersection(vix9d_close.index)
vix_a = vix_close.loc[common_idx]
vix9d_a = vix9d_close.loc[common_idx]
ratio = vix9d_a / vix_a  # >1 => short-dated higher (front-end stressed)

latest10_idx = common_idx[-10:]
latest5_idx = common_idx[-5:]

print("\n=== Latest 10 trading days VIX & VIX9D ===")
for d in latest10_idx:
    print(f"  {d.date()}  VIX={vix_a.loc[d]:.2f}  VIX9D={vix9d_a.loc[d]:.2f}  ratio={ratio.loc[d]:.3f}")

latest5_ratio = ratio.loc[latest5_idx].mean()
latest10_ratio = ratio.loc[latest10_idx].mean()

# Baseline ratio (non-CPI days, full sample)
non_cpi_mask = ~ratio.index.isin(cpi_trading_days)
baseline_ratio = ratio.loc[non_cpi_mask]

print(f"\nLatest-5 mean VIX9D/VIX:  {latest5_ratio:.4f}")
print(f"Latest-10 mean VIX9D/VIX: {latest10_ratio:.4f}")
print(f"Baseline (non-CPI all) mean: {baseline_ratio.mean():.4f}, std={baseline_ratio.std():.4f}")
print(f"Latest-5 z-score vs baseline: {(latest5_ratio - baseline_ratio.mean()) / baseline_ratio.std():.2f}")

# ─── 6. Pre-CPI VIX run-up profile (T-5 to T-1) ─────────────────────────────

print("\n=== Pre-CPI VIX run-up (T-5 to T-1, mean % vs CPI day) ===")
preevent_changes = {-5: [], -4: [], -3: [], -2: [], -1: []}
for td in cpi_trading_days:
    pos = vix_close.index.get_loc(td)
    base = vix_close.iloc[pos]
    for offset in range(-5, 0):
        ip = pos + offset
        if ip >= 0:
            preevent_changes[offset].append(float((vix_close.iloc[ip] - base) / base * 100))

for offset in sorted(preevent_changes.keys()):
    arr = np.array(preevent_changes[offset])
    print(f"  T{offset:+d}: mean diff vs CPI-day VIX = {arr.mean():+.2f}%, n={len(arr)}")

# ─── 7. Build T-2 specific summary table (recent 4) ────────────────────────

table_rows = []
for x in vix_changes_recent4:
    td = x['date']
    ratio_val = float(ratio.loc[td]) if td in ratio.index else None
    pos = vix_close.index.get_loc(td)
    if pos + 5 < len(vix_close):
        post5 = (vix_close.iloc[pos + 5] - vix_close.iloc[pos]) / vix_close.iloc[pos] * 100
    else:
        post5 = None
    table_rows.append({
        'CPI 發布日': td.strftime('%Y-%m-%d'),
        'VIX（T-1）': round(x['prev'], 2),
        'VIX（當日）': round(x['curr'], 2),
        'VIX 當日漲跌': f"{x['pct']:+.1f}%",
        'VIX9D/VIX 比值': f"{ratio_val:.3f}" if ratio_val else 'N/A',
        'VIX T+5 變化': f"{post5:+.1f}%" if post5 is not None else 'N/A',
    })

df_table = pd.DataFrame(table_rows)
print("\nT-2 Summary Table (recent 4 CPI):")
print(df_table.to_string(index=False))

# Current state (for article context, not historical)
current_vix = float(vix_close.iloc[-1])
current_vix9d = float(vix9d_close.iloc[-1])
current_ratio = current_vix9d / current_vix
current_date = vix_close.index[-1].strftime('%Y-%m-%d')
print(f"\nCurrent state ({current_date}):  VIX={current_vix:.2f}  VIX9D={current_vix9d:.2f}  ratio={current_ratio:.3f}")

# ─── 8. Figure 1: Recent 4 vs Earlier 9 dispersion ──────────────────────────

fig1, ax = plt.subplots(figsize=(9, 5))

x_recent = np.arange(len(recent4_arr)) + len(earlier9_arr) + 1
x_earlier = np.arange(len(earlier9_arr))

ax.scatter(x_earlier, earlier9_arr,
           color='#90a4ae', alpha=0.85, s=80, edgecolor='white',
           label=f'前 9 次（2025-05 ~ 2026-01），σ={earlier9_arr.std():.2f}%')
ax.scatter(x_recent, recent4_arr,
           color='#d32f2f', alpha=0.9, s=110, edgecolor='white',
           label=f'近 4 次（2026-02 ~ 2026-05），σ={recent4_arr.std():.2f}%')

ax.axhline(0, color='black', linewidth=0.8, linestyle='--', alpha=0.5)

# variance band
e_mean = earlier9_arr.mean()
e_std = earlier9_arr.std()
ax.axhspan(e_mean - e_std, e_mean + e_std, alpha=0.06, color='#90a4ae')

r_mean = recent4_arr.mean()
r_std = recent4_arr.std()
ax.axhspan(r_mean - r_std, r_mean + r_std, alpha=0.06, color='#d32f2f')

# annotate recent 4
recent_labels = [x['date'].strftime('%Y-%m-%d') for x in vix_changes_recent4]
for xi, yi, lbl in zip(x_recent, recent4_arr, recent_labels):
    ax.annotate(f"{lbl}\n{yi:+.1f}%", (xi, yi),
                textcoords="offset points", xytext=(0, 12),
                ha='center', fontsize=8.5, color='#b71c1c')

all_labels = [x['date'].strftime('%y-%m') for x in earlier9] + [''] + [x['date'].strftime('%y-%m') for x in vix_changes_recent4]
all_x = list(x_earlier) + [len(earlier9_arr)] + list(x_recent)
ax.set_xticks(all_x)
ax.set_xticklabels(all_labels, rotation=45, ha='right', fontsize=8)

ax.set_xlabel('CPI 發布月份', fontsize=11)
ax.set_ylabel('VIX 當日漲跌幅（%）', fontsize=11)
ax.set_title('US CPI 反應的方差壓縮：近 4 次 vs 前 9 次\n（樣本期 2025-05 ~ 2026-05，當日 VIX 收盤 vs T-1）',
             fontsize=12.5, fontweight='bold')
ax.legend(fontsize=9, loc='upper left')
ax.yaxis.grid(True, alpha=0.3)
ax.set_axisbelow(True)

fig1.text(0.99, 0.01, '資料來源：yfinance / CBOE ^VIX；VolPred 自製分析',
          ha='right', va='bottom', fontsize=7, color='grey')
plt.tight_layout()
fig1.savefig(f'{OUT_DIR}/fig1_recent4_vs_earlier9.png', dpi=150, bbox_inches='tight')
plt.close()
print("\nFig 1 saved.")

# ─── 9. Figure 2: Current VIX / VIX9D term structure (last 30 days) ────────

fig2, ax2 = plt.subplots(figsize=(9, 5))
last30 = common_idx[-30:]

ax2.plot(last30, vix_a.loc[last30], 'o-', color='#1565c0', linewidth=1.8, markersize=4, label='VIX')
ax2.plot(last30, vix9d_a.loc[last30], 's--', color='#d32f2f', linewidth=1.6, markersize=4, label='VIX9D')

ax2.axvspan(latest5_idx[0], latest5_idx[-1], alpha=0.12, color='#ffa000', label='近 5 交易日')

ax2.annotate(f"{current_date}\nVIX={current_vix:.2f}\nVIX9D={current_vix9d:.2f}\nratio={current_ratio:.3f}",
             (last30[-1], current_vix),
             textcoords="offset points", xytext=(10, -25),
             fontsize=9, color='#0d47a1',
             bbox=dict(boxstyle="round,pad=0.4", facecolor='#e3f2fd', edgecolor='#1565c0', alpha=0.9))

ax2.set_xlabel('日期', fontsize=11)
ax2.set_ylabel('指數水準', fontsize=11)
ax2.set_title(f'CPI 發布前的 VIX / VIX9D 結構（{last30[0].date()} ~ {last30[-1].date()}）\n比值 <1 表示短端隱含波動低於 30 天，前端定價較鬆',
              fontsize=12.5, fontweight='bold')
ax2.legend(fontsize=9, loc='upper left')
ax2.yaxis.grid(True, alpha=0.3)
ax2.set_axisbelow(True)
plt.xticks(rotation=45, ha='right', fontsize=8)

fig2.text(0.99, 0.01, '資料來源：yfinance / CBOE ^VIX ^VIX9D；VolPred 自製分析',
          ha='right', va='bottom', fontsize=7, color='grey')
plt.tight_layout()
fig2.savefig(f'{OUT_DIR}/fig2_current_vix_term.png', dpi=150, bbox_inches='tight')
plt.close()
print("Fig 2 saved.")

# ─── 10. Save evidence JSON ─────────────────────────────────────────────────

evidence = {
    "event": "US CPI 2026-06-11",
    "article_slot": "T-2",
    "data_period": f"{start} to {vix_close.index[-1].date()}",
    "latest_closed_trading_day": current_date,
    "cpi_dates_full_n": len(cpi_trading_days),
    "cpi_dates_recent4_n": len(recent4_td),
    "primary_numbers": {
        "recent4_vix_day_pct": {
            "values": [{"date": x['date'].strftime('%Y-%m-%d'), "pct": round(x['pct'], 3),
                        "vix_prev": round(x['prev'], 2), "vix_curr": round(x['curr'], 2)}
                       for x in vix_changes_recent4],
            "mean": round(float(recent4_arr.mean()), 3),
            "std": round(float(recent4_arr.std()), 3),
            "min": round(float(recent4_arr.min()), 3),
            "max": round(float(recent4_arr.max()), 3),
        },
        "earlier9_vix_day_pct": {
            "mean": round(float(earlier9_arr.mean()), 3),
            "std": round(float(earlier9_arr.std()), 3),
            "min": round(float(earlier9_arr.min()), 3),
            "max": round(float(earlier9_arr.max()), 3),
            "n": len(earlier9_arr),
        },
        "variance_compression_ftest": {
            "F_stat": round(float(F_stat), 3),
            "df_earlier": df1,
            "df_recent": df2,
            "one_sided_pval": round(float(F_pval), 4),
            "interpretation": "p<0.05 表示近 4 次方差顯著低於前 9 次"
        },
        "current_term_structure": {
            "as_of_date": current_date,
            "vix": round(current_vix, 2),
            "vix9d": round(current_vix9d, 2),
            "ratio_vix9d_vix": round(current_ratio, 4),
            "latest5_ratio_mean": round(float(latest5_ratio), 4),
            "latest10_ratio_mean": round(float(latest10_ratio), 4),
            "baseline_ratio_mean": round(float(baseline_ratio.mean()), 4),
            "baseline_ratio_std": round(float(baseline_ratio.std()), 4),
            "z_score_latest5_vs_baseline": round(float((latest5_ratio - baseline_ratio.mean()) / baseline_ratio.std()), 2),
        },
        "pre_cpi_runup": {
            f"T{offset:+d}": {
                "mean_pct_vs_cpi_day": round(float(np.mean(preevent_changes[offset])), 3),
                "n": len(preevent_changes[offset])
            }
            for offset in sorted(preevent_changes.keys())
        }
    },
    "table_rows_recent4": table_rows,
    "latest_10_days": [
        {"date": d.strftime('%Y-%m-%d'),
         "vix": round(float(vix_a.loc[d]), 2),
         "vix9d": round(float(vix9d_a.loc[d]), 2),
         "ratio": round(float(ratio.loc[d]), 4)}
        for d in latest10_idx
    ]
}

with open(f'{OUT_DIR}/evidence.json', 'w') as f:
    json.dump(evidence, f, ensure_ascii=False, indent=2, default=str)

print("\nEvidence saved to evidence.json")
print("\n=== KEY NUMBERS ===")
print(json.dumps({
    "recent4_std": evidence['primary_numbers']['recent4_vix_day_pct']['std'],
    "earlier9_std": evidence['primary_numbers']['earlier9_vix_day_pct']['std'],
    "F_p": evidence['primary_numbers']['variance_compression_ftest']['one_sided_pval'],
    "latest5_ratio": evidence['primary_numbers']['current_term_structure']['latest5_ratio_mean'],
    "z_score": evidence['primary_numbers']['current_term_structure']['z_score_latest5_vs_baseline'],
    "current_vix": evidence['primary_numbers']['current_term_structure']['vix'],
    "current_vix9d": evidence['primary_numbers']['current_term_structure']['vix9d'],
}, ensure_ascii=False, indent=2))
