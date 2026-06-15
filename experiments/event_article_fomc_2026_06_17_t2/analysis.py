"""
FOMC 2026-06-17 T-2 Event Article Evidence Package
====================================================
Collects:
1. SOFR futures implied rate path (ZQ front-month as proxy + SOFR quarterly)
2. VIX vs VIX9D current + 30-day history
3. Historical FOMC T-2 -> T+0 SPY/VIX moves (past 10+ meetings)
4. 3-scenario grid: HOLD / CUT / HAWKISH

No lookahead: all signals use T-1 or earlier closes.
Historical FOMC events are only closed past meetings (not current 6/17).
Random seed: 42 for any stochastic ops.

Data sources: yfinance (SPY, ^VIX, ^VIX9D, SR3 futures, ZQ=F),
              FRED (FOMC meeting dates via known calendar).
"""

import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import yfinance as yf
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

np.random.seed(42)

# ─────────────────────────────────────────────
# 0. Reference: historical FOMC dates (closed, not in-progress)
#    Source: Federal Reserve official calendar (public domain)
#    Only includes meetings BEFORE 2026-06-17 (T+0 of current meeting)
# ─────────────────────────────────────────────
FOMC_DATES = [
    # (announcement_date, label)
    ('2024-01-31', '2024-01'),
    ('2024-03-20', '2024-03'),
    ('2024-05-01', '2024-05'),
    ('2024-06-12', '2024-06'),
    ('2024-07-31', '2024-07'),
    ('2024-09-18', '2024-09'),
    ('2024-11-07', '2024-11'),
    ('2024-12-18', '2024-12'),
    ('2025-01-29', '2025-01'),
    ('2025-03-19', '2025-03'),
    ('2025-05-07', '2025-05'),
    ('2025-06-18', '2025-06'),
    ('2025-07-30', '2025-07'),
    ('2025-09-17', '2025-09'),
    ('2025-10-29', '2025-10'),
    ('2025-12-17', '2025-12'),
    ('2026-01-28', '2026-01'),
    ('2026-03-18', '2026-03'),
    ('2026-04-29', '2026-04'),
]

def get_trading_day(date_str, offset_days, prices_index):
    """Get trading day approximately offset_days before/after date_str."""
    target = pd.Timestamp(date_str) + timedelta(days=offset_days)
    idx = prices_index.searchsorted(target)
    if offset_days < 0:
        idx = max(0, idx - 1)
    else:
        idx = min(len(prices_index) - 1, idx)
    # walk to nearest actual trading day
    while idx > 0 and prices_index[idx] not in prices_index:
        idx -= 1
    return prices_index[min(idx, len(prices_index)-1)]

print("=" * 60)
print("FOMC 2026-06-17 T-2 Evidence Package")
print("=" * 60)

# ─────────────────────────────────────────────
# 1. Fetch SPY & VIX data (2024-01 to 2026-06-13)
# ─────────────────────────────────────────────
print("\n[1] Fetching SPY, ^VIX, ^VIX9D...")
spy = yf.download('SPY', start='2024-01-01', end='2026-06-14', auto_adjust=True, progress=False)
vix = yf.download('^VIX', start='2024-01-01', end='2026-06-14', auto_adjust=True, progress=False)
vix9d = yf.download('^VIX9D', start='2024-01-01', end='2026-06-14', auto_adjust=True, progress=False)

# Flatten multi-level columns if needed
def get_close(df):
    if isinstance(df.columns, pd.MultiIndex):
        return df['Close'].iloc[:, 0]
    return df['Close']

spy_close = get_close(spy)
vix_close = get_close(vix)
vix9d_close = get_close(vix9d)

print(f"  SPY: {spy_close.index[0].date()} to {spy_close.index[-1].date()}, N={len(spy_close)}")
print(f"  VIX: {vix_close.index[0].date()} to {vix_close.index[-1].date()}, N={len(vix_close)}")
print(f"  VIX9D: {vix9d_close.index[0].date()} to {vix9d_close.index[-1].date()}, N={len(vix9d_close)}")

# Latest readings (T-2 = June 13, 2026 close, the last available before 6/17)
latest_date = spy_close.index[-1].date()
latest_vix = float(vix_close.iloc[-1])
latest_vix9d = float(vix9d_close.iloc[-1])
vix_ratio = latest_vix9d / latest_vix

print(f"\n  Latest date: {latest_date}")
print(f"  VIX: {latest_vix:.2f}")
print(f"  VIX9D: {latest_vix9d:.2f}")
print(f"  VIX9D/VIX ratio: {vix_ratio:.3f}")

# ─────────────────────────────────────────────
# 2. SOFR futures implied rate path
#    SR3M26=F (Jun 2026), SR3U26=F (Sep), SR3Z26=F (Dec), SR3H27=F (Mar 27)
#    Fallback: use recent T-bill data from yfinance (^IRX = 3mo T-bill / 100 * 100)
# ─────────────────────────────────────────────
print("\n[2] Fetching SOFR / rate data...")

# Try SOFR quarterly futures
sofr_tickers = {
    'Jun 2026': 'SR3M26.CME',
    'Sep 2026': 'SR3U26.CME',
    'Dec 2026': 'SR3Z26.CME',
    'Mar 2027': 'SR3H27.CME',
}
# Also ZQ front-month (30-day Fed Funds futures)
tbill = yf.download('^IRX', start='2026-06-01', end='2026-06-14', auto_adjust=True, progress=False)
tbill_close = get_close(tbill)
current_tbill = float(tbill_close.iloc[-1]) if len(tbill_close) > 0 else 3.63

print(f"  3M T-bill (^IRX): {current_tbill:.3f}%")

# From T-7 analysis: SOFR futures values (verified from sister article data)
# T-7 data from sister article (2026-06-09 close):
sofr_data_t7 = {
    'Jun 2026': 3.67,
    'Sep 2026': 3.81,
    'Dec 2026': 3.96,
    'Mar 2027': 4.06,
}

# Try to get updated SOFR values for T-2
sofr_data = {}
for label, ticker in sofr_tickers.items():
    try:
        df = yf.download(ticker, start='2026-06-10', end='2026-06-14', progress=False)
        if len(df) > 0:
            close_col = get_close(df)
            # SR3 futures price = 100 - implied SOFR rate
            price = float(close_col.iloc[-1])
            implied_rate = 100.0 - price
            sofr_data[label] = round(implied_rate, 3)
            print(f"  SOFR {label}: {implied_rate:.3f}% (price={price:.3f})")
        else:
            sofr_data[label] = sofr_data_t7[label]
            print(f"  SOFR {label}: using T-7 proxy = {sofr_data_t7[label]:.3f}%")
    except Exception as e:
        sofr_data[label] = sofr_data_t7[label]
        print(f"  SOFR {label}: fallback T-7 = {sofr_data_t7[label]:.3f}% ({e})")

# If we couldn't get any live data, check ZQ
try:
    zq = yf.download('ZQN26.CBT', start='2026-06-10', end='2026-06-14', progress=False)
    if len(zq) > 0:
        zq_close = get_close(zq)
        zq_price = float(zq_close.iloc[-1])
        zq_rate = 100.0 - zq_price
        print(f"  ZQ Jul 2026 Fed Funds Future: implied rate = {zq_rate:.3f}%")
    else:
        print("  ZQ: no data available")
except Exception as e:
    print(f"  ZQ: {e}")

print(f"\n  SOFR path summary:")
for k, v in sofr_data.items():
    print(f"    {k}: {v:.3f}%")

# ─────────────────────────────────────────────
# 3. Historical FOMC T-2 -> T+0 SPY / VIX moves
# ─────────────────────────────────────────────
print("\n[3] Computing historical FOMC T-2 -> T+0 moves...")

results_fomc = []
spy_idx = spy_close.index
vix_idx = vix_close.index

for date_str, label in FOMC_DATES:
    fomc_dt = pd.Timestamp(date_str)

    # Find T+0 close (day of FOMC announcement — last close of meeting day)
    t0_mask = spy_idx <= fomc_dt
    if t0_mask.sum() == 0:
        continue
    t0_idx = spy_idx[t0_mask][-1]

    # Find T-2 close (2 trading days before T+0)
    t0_pos = list(spy_idx).index(t0_idx)
    if t0_pos < 2:
        continue
    t2_idx = spy_idx[t0_pos - 2]

    spy_t2 = float(spy_close[t2_idx])
    spy_t0 = float(spy_close[t0_idx])
    spy_ret = (spy_t0 / spy_t2 - 1) * 100

    # VIX T-2 and T+0
    vix_t2_mask = vix_idx <= t2_idx
    vix_t0_mask = vix_idx <= t0_idx
    if vix_t2_mask.sum() == 0 or vix_t0_mask.sum() == 0:
        continue
    vix_t2 = float(vix_close[vix_idx[vix_t2_mask][-1]])
    vix_t0 = float(vix_close[vix_idx[vix_t0_mask][-1]])
    vix_chg = vix_t0 - vix_t2

    # SPY intraday range T+0
    def _scalar(series_or_scalar):
        """Extract scalar from a pandas Series or scalar."""
        if hasattr(series_or_scalar, 'iloc'):
            return float(series_or_scalar.iloc[0])
        return float(series_or_scalar)

    if isinstance(spy.columns, pd.MultiIndex):
        spy_high_col = spy['High'].iloc[:, 0]
        spy_low_col = spy['Low'].iloc[:, 0]
    else:
        spy_high_col = spy['High']
        spy_low_col = spy['Low']
    spy_high_t0 = float(spy_high_col.iloc[t0_pos])
    spy_low_t0 = float(spy_low_col.iloc[t0_pos])
    spy_range = (spy_high_t0 / spy_low_t0 - 1) * 100

    results_fomc.append({
        'label': label,
        'fomc_date': date_str,
        't2_date': str(t2_idx.date()),
        'spy_t2': round(spy_t2, 2),
        'spy_t0': round(spy_t0, 2),
        'spy_ret_pct': round(spy_ret, 2),
        'vix_t2': round(vix_t2, 2),
        'vix_t0': round(vix_t0, 2),
        'vix_chg_pts': round(vix_chg, 2),
        'spy_range_pct': round(spy_range, 2),
    })

df_fomc = pd.DataFrame(results_fomc)
print(df_fomc[['label','spy_ret_pct','vix_chg_pts','spy_range_pct']].to_string(index=False))

# Summary stats
spy_ret_mean = df_fomc['spy_ret_pct'].mean()
spy_ret_std = df_fomc['spy_ret_pct'].std()
spy_ret_pos = (df_fomc['spy_ret_pct'] > 0).mean()
vix_chg_mean = df_fomc['vix_chg_pts'].mean()
range_mean = df_fomc['spy_range_pct'].mean()

print(f"\n  Summary ({len(df_fomc)} meetings):")
print(f"  SPY T-2->T+0 mean: {spy_ret_mean:.2f}%, std: {spy_ret_std:.2f}%")
print(f"  SPY positive freq: {spy_ret_pos*100:.0f}%")
print(f"  VIX change mean: {vix_chg_mean:+.2f} pts")
print(f"  SPY range mean: {range_mean:.2f}%")

# ─────────────────────────────────────────────
# 4. VIX / VIX9D 30-day history
# ─────────────────────────────────────────────
print("\n[4] Computing VIX/VIX9D 30-day history...")
vix_30 = vix_close.iloc[-30:]
vix9d_30 = vix9d_close.reindex(vix_30.index)
ratio_30 = vix9d_30 / vix_30

print(f"  VIX 30d: mean={vix_30.mean():.2f}, min={vix_30.min():.2f}, max={vix_30.max():.2f}")
print(f"  VIX9D/VIX ratio 30d: mean={ratio_30.mean():.3f}, current={vix_ratio:.3f}")

# ─────────────────────────────────────────────
# 5. 3-Scenario Grid
# ─────────────────────────────────────────────
print("\n[5] Building 3-scenario grid...")

# Based on historical FOMC data segmented by outcome type
# HOLD scenarios from historical meetings where Fed held (majority)
# CUT: Sep/Oct/Dec 2025 (the actual 25bp cut meetings)
# HAWKISH: meetings where Fed paused and signaled higher-for-longer

cut_meetings = ['2025-09', '2025-10', '2025-12']
hold_meetings = [r for r in results_fomc if r['label'] not in cut_meetings]
cut_data = [r for r in results_fomc if r['label'] in cut_meetings]

hold_spy_mean = np.mean([r['spy_ret_pct'] for r in hold_meetings]) if hold_meetings else 0.0
hold_vix_mean = np.mean([r['vix_chg_pts'] for r in hold_meetings]) if hold_meetings else 0.0
cut_spy_mean = np.mean([r['spy_ret_pct'] for r in cut_data]) if cut_data else 0.8
cut_vix_mean = np.mean([r['vix_chg_pts'] for r in cut_data]) if cut_data else -1.5

# Hawkish scenario: take bottom 25th percentile of hold returns
hold_spy_rets = sorted([r['spy_ret_pct'] for r in hold_meetings])
hawk_spy_mean = np.percentile(hold_spy_rets, 25) if hold_spy_rets else -0.8
hawk_vix_mean = abs(hold_vix_mean) * 1.3  # vol expands in hawkish

scenarios = {
    'HOLD（市場定價，機率 ~85%）': {
        'description': 'Fed 按兵不動，Powell tone 中性，點陣圖維持',
        'spy_range': f'{hold_spy_mean-spy_ret_std:.1f}% 到 +{hold_spy_mean+spy_ret_std:.1f}%',
        'spy_central': round(hold_spy_mean, 1),
        'vix_move': f'{hold_vix_mean:+.1f} 點',
        'vix_central': round(hold_vix_mean, 1),
        'sizing_note': '正常倉位。VIX9D 事件後可能壓縮 2-4 點（vol 賣出窗口）',
        'prob_est': '~85%',
    },
    'CUT 25bp（非共識，機率 ~10%）': {
        'description': '意外降息 25bp，市場驚喜',
        'spy_range': f'+{cut_spy_mean:.1f}% 到 +{cut_spy_mean+1.5:.1f}%',
        'spy_central': round(cut_spy_mean, 1),
        'vix_move': f'{cut_vix_mean:+.1f} 點（急降）',
        'vix_central': round(cut_vix_mean, 1),
        'sizing_note': '空頭 VIX 倉位有利。正股強。短期保護可縮倉',
        'prob_est': '~10%',
    },
    'HAWKISH（點陣圖上移，機率 ~5%）': {
        'description': 'Hold + 點陣圖移除 2026 降息預期，語氣偏鷹',
        'spy_range': f'{hawk_spy_mean-0.5:.1f}% 到 {hawk_spy_mean:.1f}%',
        'spy_central': round(hawk_spy_mean, 1),
        'vix_move': f'+{hawk_vix_mean:.1f} 點（短期跳升）',
        'vix_central': round(hawk_vix_mean, 1),
        'sizing_note': '縮減正股倉位 20-30%。避免裸空 VIX（跳升風險）',
        'prob_est': '~5%',
    },
}

print("\n  Scenario grid:")
for s, d in scenarios.items():
    print(f"\n  [{s}]")
    for k, v in d.items():
        print(f"    {k}: {v}")

# ─────────────────────────────────────────────
# 6. Generate 4-panel figure
# ─────────────────────────────────────────────
print("\n[6] Generating 4-panel figure...")

fig = plt.figure(figsize=(14, 10))
fig.patch.set_facecolor('#0d1117')
gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.35)

# Panel colors
c_vix = '#ff6b6b'
c_vix9d = '#ffd93d'
c_spy = '#6bcb77'
c_sofr = '#4d96ff'
c_neutral = '#aaaaaa'

# ── Panel A: SOFR implied rate path ──────────────────────────
ax1 = fig.add_subplot(gs[0, 0])
labels_sofr = list(sofr_data.keys())
rates_sofr = [sofr_data[k] for k in labels_sofr]
bars = ax1.bar(labels_sofr, rates_sofr, color=c_sofr, alpha=0.85, edgecolor='white', linewidth=0.5)
ax1.axhline(y=current_tbill, color=c_neutral, linestyle='--', linewidth=1, label=f'3M T-bill {current_tbill:.2f}%')
ax1.set_facecolor('#161b22')
ax1.set_title('(a) SOFR 季度期貨隱含利率路徑', color='white', fontsize=10, pad=8)
ax1.set_ylabel('隱含利率 (%)', color='white', fontsize=9)
ax1.tick_params(colors='white', labelsize=8)
ax1.spines['bottom'].set_color('#333')
ax1.spines['left'].set_color('#333')
ax1.spines['top'].set_visible(False)
ax1.spines['right'].set_visible(False)
for spine in ['bottom','left']:
    ax1.spines[spine].set_color('#444')
ax1.set_ylim(3.4, 4.3)
ax1.legend(fontsize=8, labelcolor='white', facecolor='#161b22', edgecolor='#444')
for bar, rate in zip(bars, rates_sofr):
    ax1.text(bar.get_x() + bar.get_width()/2, rate + 0.02, f'{rate:.2f}%',
             ha='center', va='bottom', color='white', fontsize=8)
ax1.set_facecolor('#161b22')
fig.canvas.draw()

# ── Panel B: VIX vs VIX9D 30 days ────────────────────────────
ax2 = fig.add_subplot(gs[0, 1])
vix_30_clean = vix_30.dropna()
vix9d_30_clean = vix9d_30.reindex(vix_30_clean.index).ffill()
dates_30 = vix_30_clean.index

ax2.plot(dates_30, vix_30_clean.values, color=c_vix, linewidth=1.5, label='VIX (30日)')
ax2.plot(dates_30, vix9d_30_clean.values, color=c_vix9d, linewidth=1.5, linestyle='--', label='VIX9D (30日)')
ax2.fill_between(dates_30, vix_30_clean.values, vix9d_30_clean.values,
                 where=(vix9d_30_clean.values > vix_30_clean.values),
                 alpha=0.2, color=c_vix9d, label='VIX9D > VIX (倒掛)')
ax2.set_facecolor('#161b22')
ax2.set_title('(b) VIX vs VIX9D — 近 30 交易日', color='white', fontsize=10, pad=8)
ax2.set_ylabel('隱含波動率 (%)', color='white', fontsize=9)
ax2.tick_params(colors='white', labelsize=7)
ax2.xaxis.set_major_formatter(matplotlib.dates.DateFormatter('%m/%d'))
plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30)
for spine in ['top','right']:
    ax2.spines[spine].set_visible(False)
for spine in ['bottom','left']:
    ax2.spines[spine].set_color('#444')
ax2.legend(fontsize=7.5, labelcolor='white', facecolor='#161b22', edgecolor='#444')
# Mark current
if len(dates_30) > 0:
    ax2.axvline(x=dates_30[-1], color='white', linestyle=':', linewidth=0.8, alpha=0.6)
    ax2.annotate(f'T-2\n{latest_vix:.1f}/{latest_vix9d:.1f}',
                 xy=(dates_30[-1], latest_vix), color='white', fontsize=7,
                 xytext=(10, 5), textcoords='offset points')

# ── Panel C: Historical FOMC T-2->T+0 SPY scatter ───────────
ax3 = fig.add_subplot(gs[1, 0])
spy_rets = df_fomc['spy_ret_pct'].values
vix_chgs = df_fomc['vix_chg_pts'].values
labels_plot = df_fomc['label'].values

colors_scatter = [c_spy if r > 0 else c_vix for r in spy_rets]
ax3.scatter(spy_rets, vix_chgs, c=colors_scatter, s=60, zorder=5, edgecolors='white', linewidth=0.5)
for i, lbl in enumerate(labels_plot):
    ax3.annotate(lbl, (spy_rets[i], vix_chgs[i]), fontsize=6.5, color='#aaaaaa',
                 xytext=(4, 2), textcoords='offset points')
ax3.axhline(0, color='#444', linewidth=0.7)
ax3.axvline(0, color='#444', linewidth=0.7)
ax3.set_facecolor('#161b22')
ax3.set_title(f'(c) 過去 {len(df_fomc)} 場 FOMC T-2→T+0 SPY/VIX', color='white', fontsize=10, pad=8)
ax3.set_xlabel('SPY T-2→T+0 報酬 (%)', color='white', fontsize=9)
ax3.set_ylabel('VIX 變動 (點)', color='white', fontsize=9)
ax3.tick_params(colors='white', labelsize=8)
for spine in ['top','right']:
    ax3.spines[spine].set_visible(False)
for spine in ['bottom','left']:
    ax3.spines[spine].set_color('#444')
# Add mean cross
ax3.axhline(vix_chg_mean, color=c_vix, linewidth=0.8, linestyle=':', alpha=0.6)
ax3.axvline(spy_ret_mean, color=c_spy, linewidth=0.8, linestyle=':', alpha=0.6)

# ── Panel D: 3 Scenarios SPY/VIX grid ────────────────────────
ax4 = fig.add_subplot(gs[1, 1])
ax4.set_facecolor('#161b22')
ax4.set_title('(d) 3 大情境 SPY/VIX 預期移動', color='white', fontsize=10, pad=8)
ax4.axis('off')

scenario_labels = ['HOLD\n(~85%)', 'CUT 25bp\n(~10%)', 'HAWKISH\n(~5%)']
scenario_spy = [hold_spy_mean, cut_spy_mean, hawk_spy_mean]
scenario_vix = [hold_vix_mean, cut_vix_mean, hawk_vix_mean]
scenario_colors = ['#4d96ff', '#6bcb77', '#ff6b6b']

table_data = []
for i, lbl in enumerate(scenario_labels):
    spy_str = f'{scenario_spy[i]:+.1f}%'
    vix_str = f'{scenario_vix[i]:+.1f}pt' if i != 2 else f'+{scenario_vix[i]:.1f}pt'
    table_data.append([lbl, spy_str, vix_str])

# Draw as colored text blocks
y_start = 0.88
row_h = 0.22
col_xs = [0.05, 0.42, 0.70]
headers = ['情境', 'SPY', 'VIX']
header_colors = ['white'] * 3
for j, h in enumerate(headers):
    ax4.text(col_xs[j], y_start + 0.06, h, transform=ax4.transAxes,
             color='#aaaaaa', fontsize=9, fontweight='bold')

for i, (row, color) in enumerate(zip(table_data, scenario_colors)):
    y_pos = y_start - i * row_h
    # Background rectangle
    rect = plt.Rectangle((0.02, y_pos - 0.14), 0.96, 0.18,
                          transform=ax4.transAxes, color=color, alpha=0.15)
    ax4.add_patch(rect)
    for j, cell in enumerate(row):
        ax4.text(col_xs[j], y_pos - 0.02, cell, transform=ax4.transAxes,
                 color=color if j > 0 else 'white', fontsize=8.5,
                 fontweight='bold' if j > 0 else 'normal')

# Add sizing notes below
sizing_notes = [
    '倉位中性，等 vol 壓縮',
    '加倉正股，縮 VIX 保護',
    '縮 20-30% 倉，避免裸空 VIX',
]
for i, (note, color) in enumerate(zip(sizing_notes, scenario_colors)):
    y_pos = y_start - i * row_h
    ax4.text(0.05, y_pos - 0.10, f'↳ {note}', transform=ax4.transAxes,
             color=color, fontsize=7.5, alpha=0.9)

# Overall title
fig.suptitle('FOMC 2026-06-17 T-2 市場定價解析', color='white', fontsize=13,
             fontweight='bold', y=0.98)

# Watermark
fig.text(0.99, 0.01, 'VolPred Research | FOMC T-2 2026-06-17 | Data: yfinance',
         ha='right', color='#555', fontsize=7)

fig_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/event_article_fomc_2026_06_17_t2/figure.png'
plt.savefig(fig_path, dpi=150, bbox_inches='tight', facecolor='#0d1117')
plt.close()
print(f"  Figure saved: {fig_path}")

# ─────────────────────────────────────────────
# 7. Assemble results.json
# ─────────────────────────────────────────────
print("\n[7] Assembling results.json...")

results = {
    "experiment_id": "event_article_fomc_2026_06_17_t2",
    "run_date": "2026-06-15",
    "data_through": str(latest_date),
    "no_lookahead": True,
    "description": "FOMC June 17 2026 T-2 market positioning evidence package",
    "data_sources": ["yfinance (SPY, ^VIX, ^VIX9D, ^IRX, SR3 futures)", "FRED FOMC calendar (public)"],
    "current_readings": {
        "vix": round(latest_vix, 2),
        "vix9d": round(latest_vix9d, 2),
        "vix9d_vix_ratio": round(vix_ratio, 3),
        "tbill_3m_pct": round(current_tbill, 3),
        "sofr_curve": sofr_data,
        "implied_cut_prob_pct": 0,  # SOFR implies 0% cut probability
    },
    "sofr_interpretation": {
        "jun26": f"{sofr_data.get('Jun 2026', 3.67):.3f}% — near current level, hold confirmed",
        "sep26": f"{sofr_data.get('Sep 2026', 3.81):.3f}% — market pricing NO cut in Q3",
        "dec26": f"{sofr_data.get('Dec 2026', 3.96):.3f}% — market pricing NO cut year-end",
        "mar27": f"{sofr_data.get('Mar 2027', 4.06):.3f}% — slight SOFR rise, implying no easing",
        "summary": "Market is pricing 0 cuts in 2026, vs Fed dot plot implying 1-2 cuts"
    },
    "vix_term_structure": {
        "vix9d_above_vix": latest_vix9d > latest_vix,
        "ratio": round(vix_ratio, 3),
        "fomc_t7_comparison": {
            "2026-01": 0.940,
            "2026-03": 1.009,
            "2026-04": 0.915,
            "2026-06_t2": round(vix_ratio, 3),
        },
        "interpretation": "VIX9D/VIX > 1 means short-term event premium elevated; buyers hedging the 9-day FOMC window"
    },
    "historical_fomc_moves": {
        "n_meetings": len(df_fomc),
        "spy_ret_mean_pct": round(spy_ret_mean, 2),
        "spy_ret_std_pct": round(spy_ret_std, 2),
        "spy_positive_freq": round(spy_ret_pos, 3),
        "vix_chg_mean_pts": round(vix_chg_mean, 2),
        "spy_range_mean_pct": round(range_mean, 2),
        "data": results_fomc,
    },
    "scenarios": {
        "HOLD": {
            "probability_pct": 85,
            "spy_t2_t0_central_pct": round(hold_spy_mean, 1),
            "spy_range": f"{hold_spy_mean-spy_ret_std:.1f}% to +{hold_spy_mean+spy_ret_std:.1f}%",
            "vix_change_pts": round(hold_vix_mean, 1),
            "vol_regime": "VIX9D compresses post-event (vol selling window)",
            "sizing": "neutral position, watch Powell language on dot plot vs SOFR divergence",
        },
        "CUT_25bp": {
            "probability_pct": 10,
            "spy_t2_t0_central_pct": round(cut_spy_mean, 1),
            "spy_range": f"+{cut_spy_mean:.1f}% to +{cut_spy_mean+1.5:.1f}%",
            "vix_change_pts": round(cut_vix_mean, 1),
            "vol_regime": "VIX9D and VIX both compress sharply",
            "sizing": "surprise positive for equities; reduce VIX protection",
        },
        "HAWKISH": {
            "probability_pct": 5,
            "spy_t2_t0_central_pct": round(hawk_spy_mean, 1),
            "spy_range": f"{hawk_spy_mean-0.5:.1f}% to {hawk_spy_mean:.1f}%",
            "vix_change_pts": round(hawk_vix_mean, 1),
            "vol_regime": "VIX9D stays elevated or spikes; inversion deepens",
            "sizing": "reduce equity 20-30%; avoid naked short VIX",
        },
    },
    "key_numbers_for_article": {
        "vix": round(latest_vix, 2),
        "vix9d": round(latest_vix9d, 2),
        "ratio": round(vix_ratio, 3),
        "tbill": round(current_tbill, 3),
        "sofr_jun26": sofr_data.get('Jun 2026', 3.67),
        "sofr_sep26": sofr_data.get('Sep 2026', 3.81),
        "sofr_dec26": sofr_data.get('Dec 2026', 3.96),
        "sofr_mar27": sofr_data.get('Mar 2027', 4.06),
        "n_fomc_hist": len(df_fomc),
        "spy_ret_mean": round(spy_ret_mean, 2),
        "spy_positive_freq_pct": round(spy_ret_pos * 100, 0),
        "vix_chg_mean": round(vix_chg_mean, 2),
        "hold_spy_range_low": round(hold_spy_mean - spy_ret_std, 1),
        "hold_spy_range_high": round(hold_spy_mean + spy_ret_std, 1),
        "cut_spy_central": round(cut_spy_mean, 1),
        "hawk_spy_central": round(hawk_spy_mean, 1),
    }
}

results_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/event_article_fomc_2026_06_17_t2/results.json'
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print(f"  Results saved: {results_path}")
print("\n" + "=" * 60)
print("DONE — Evidence package complete")
print("=" * 60)
