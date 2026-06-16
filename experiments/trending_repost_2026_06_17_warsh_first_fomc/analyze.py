"""
analyze.py — 跨資產 Vol 分析：FOMC 2026-06-17 Warsh 首秀前後
數據來源：yfinance（VIX, VIX9D, MOVE, 殖利率）

This script is descriptive analysis only — NO trading signals, NO lookahead.
All analysis is backward-looking on historical price data.
"""
import json
import os
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # headless
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FIGS_DIR = os.path.join(SCRIPT_DIR, 'figs')
os.makedirs(FIGS_DIR, exist_ok=True)

# ── 讀取原始數據 ──────────────────────────────────────────────
df = pd.read_csv(os.path.join(SCRIPT_DIR, 'raw_data.csv'), index_col=0, parse_dates=True)
df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
df = df.sort_index()

print(f"Data loaded: {df.shape}, from {df.index[0].date()} to {df.index[-1].date()}")
print(df.tail(5))

# ── 關鍵數值 ──────────────────────────────────────────────────
# 最新值（2026-06-16 收盤）
latest_date = df.index[-1].date()
vix_latest   = df['vix'].dropna().iloc[-1]
vix9d_latest = df['vix9d'].dropna().iloc[-1]
move_latest  = df['move'].dropna().iloc[-1]
tnx_latest   = df['us10y_yield'].dropna().iloc[-1]    # 10Y yield (x10 = %)
irx_latest   = df['us3m_yield'].dropna().iloc[-1]     # 3M yield
fvx_latest   = df['us5y_yield'].dropna().iloc[-1]     # 5Y yield

# yfinance 殖利率已是百分比值（e.g. 4.43 = 4.43%）
us10y = tnx_latest  # %
us3m  = irx_latest  # %
us5y  = fvx_latest  # %
spread_10y3m = us10y - us3m   # yield curve spread

print(f"\n=== Latest Values ({latest_date}) ===")
print(f"VIX:    {vix_latest:.2f}")
print(f"VIX9D:  {vix9d_latest:.2f}")
print(f"MOVE:   {move_latest:.2f}")
print(f"US 10Y: {us10y:.2f}%")
print(f"US 3M:  {us3m:.2f}%")
print(f"US 5Y:  {us5y:.2f}%")
print(f"10Y-3M spread: {spread_10y3m:.2f}%")

# VIX9D/VIX ratio
vix9d_vix_ratio = vix9d_latest / vix_latest
print(f"VIX9D/VIX ratio: {vix9d_vix_ratio:.3f}")

# ── 30日滾動統計 ──────────────────────────────────────────────
vix_30d   = df['vix'].dropna().iloc[-30:]
move_30d  = df['move'].dropna().iloc[-30:]

vix_mean_30d  = vix_30d.mean()
vix_std_30d   = vix_30d.std()
move_mean_30d = move_30d.mean()
move_std_30d  = move_30d.std()

# MOVE/VIX ratio 30日
# Align on common dates
common_idx = df[['vix','move']].dropna()
move_vix_ratio_30d = (common_idx['move'] / common_idx['vix']).iloc[-30:]
move_vix_ratio_latest = move_vix_ratio_30d.iloc[-1]
move_vix_ratio_mean   = move_vix_ratio_30d.mean()
move_vix_ratio_std    = move_vix_ratio_30d.std()
move_vix_z = (move_vix_ratio_latest - move_vix_ratio_mean) / move_vix_ratio_std if move_vix_ratio_std > 0 else 0.0

print(f"\n=== 30-Day Rolling Stats ===")
print(f"VIX mean:          {vix_mean_30d:.2f}")
print(f"VIX std:           {vix_std_30d:.2f}")
print(f"MOVE mean:         {move_mean_30d:.2f}")
print(f"MOVE/VIX ratio:    {move_vix_ratio_latest:.3f} (30d mean={move_vix_ratio_mean:.3f}, z={move_vix_z:.2f})")

# ── 90日 MOVE/VIX percentile ──────────────────────────────────
move_vix_ratio_90d = (common_idx['move'] / common_idx['vix']).iloc[-90:]
percentile_90d = float((move_vix_ratio_90d < move_vix_ratio_latest).sum()) / len(move_vix_ratio_90d) * 100
print(f"MOVE/VIX 90d percentile: {percentile_90d:.0f}th")

# ── 近期 CPI 數據（硬編碼 FRED 公開數值）────────────────────
# FRED CPIAUCSL：2026-05 YoY 估算使用最新公開值
# 根據任務說明：5月 CPI 4.2%（YoY）— 若實際數字確認後調整
# 注意：這是任務 brief 給定的場景參數，非 yfinance 實時抓取
# FOMC 2026-06-17 是依據這個 CPI 讀數開會
cpi_may2026_yoy = 4.2   # % YoY (per task brief scenario)
fed_funds_upper  = 4.50  # % (FOMC 維持 4.25-4.50)

# ── FIGURE 1：VIX / MOVE / VIX9D 跨資產 Vol 走勢 ─────────────
fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
fig.patch.set_facecolor('#0f1117')
for ax in axes:
    ax.set_facecolor('#0f1117')
    ax.tick_params(colors='#c8ccd4', labelsize=9)
    ax.spines['bottom'].set_color('#3a3f4b')
    ax.spines['left'].set_color('#3a3f4b')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

# VIX
ax1 = axes[0]
vix_s = df['vix'].dropna()
ax1.plot(vix_s.index, vix_s.values, color='#58a6ff', lw=1.5, label='VIX')
ax1.axhline(vix_latest, color='#ff6b6b', lw=0.8, ls='--', alpha=0.7)
ax1.axhline(vix_mean_30d, color='#ffd700', lw=0.8, ls=':', alpha=0.7, label=f'30d avg={vix_mean_30d:.1f}')
ax1.set_ylabel('VIX', color='#c8ccd4', fontsize=9)
ax1.text(0.99, 0.88, f'現值 {vix_latest:.2f}', transform=ax1.transAxes,
         color='#ff6b6b', fontsize=10, ha='right', fontweight='bold')
ax1.legend(loc='upper left', fontsize=8, framealpha=0.3,
           labelcolor='#c8ccd4', facecolor='#1c1f26')
ax1.set_title('跨資產波動率：VIX · MOVE · VIX9D\n(2026-02 至 2026-06-16)',
              color='#e6edf3', fontsize=11, pad=8)

# MOVE
ax2 = axes[1]
move_s = df['move'].dropna()
ax2.plot(move_s.index, move_s.values, color='#f97583', lw=1.5, label='MOVE')
ax2.axhline(move_latest, color='#ffa07a', lw=0.8, ls='--', alpha=0.7)
ax2.axhline(move_mean_30d, color='#ffd700', lw=0.8, ls=':', alpha=0.7, label=f'30d avg={move_mean_30d:.1f}')
ax2.set_ylabel('MOVE', color='#c8ccd4', fontsize=9)
ax2.text(0.99, 0.88, f'現值 {move_latest:.2f}', transform=ax2.transAxes,
         color='#ffa07a', fontsize=10, ha='right', fontweight='bold')
ax2.legend(loc='upper left', fontsize=8, framealpha=0.3,
           labelcolor='#c8ccd4', facecolor='#1c1f26')

# VIX9D
ax3 = axes[2]
vix9d_s = df['vix9d'].dropna()
ax3.plot(vix9d_s.index, vix9d_s.values, color='#85e89d', lw=1.5, label='VIX9D')
vix9d_mean_30d = vix9d_s.iloc[-30:].mean()
ax3.axhline(vix9d_latest, color='#66ff99', lw=0.8, ls='--', alpha=0.7)
ax3.axhline(vix9d_mean_30d, color='#ffd700', lw=0.8, ls=':', alpha=0.7, label=f'30d avg={vix9d_mean_30d:.1f}')
ax3.set_ylabel('VIX9D', color='#c8ccd4', fontsize=9)
ax3.text(0.99, 0.88, f'現值 {vix9d_latest:.2f}\nVIX9D/VIX={vix9d_vix_ratio:.3f}',
         transform=ax3.transAxes, color='#85e89d', fontsize=9.5, ha='right', fontweight='bold')
ax3.legend(loc='upper left', fontsize=8, framealpha=0.3,
           labelcolor='#c8ccd4', facecolor='#1c1f26')
ax3.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
ax3.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
plt.xticks(rotation=30, color='#c8ccd4')

# FOMC day marker
fomc_date = pd.Timestamp('2026-06-17')
for ax in axes:
    ax.axvline(fomc_date, color='#ffd700', lw=1.2, ls='-', alpha=0.5, label='FOMC 2026-06-17')

plt.tight_layout(rect=[0, 0, 1, 1])
fig_path1 = os.path.join(FIGS_DIR, 'cross_asset_vol.png')
fig.savefig(fig_path1, dpi=150, bbox_inches='tight', facecolor='#0f1117')
plt.close(fig)
print(f"✓ Fig 1 saved: {fig_path1}")

# ── FIGURE 2：MOVE/VIX Ratio + 殖利率曲線 ─────────────────────
fig2, (ax4, ax5) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
fig2.patch.set_facecolor('#0f1117')
for ax in [ax4, ax5]:
    ax.set_facecolor('#0f1117')
    ax.tick_params(colors='#c8ccd4', labelsize=9)
    ax.spines['bottom'].set_color('#3a3f4b')
    ax.spines['left'].set_color('#3a3f4b')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)

# MOVE/VIX ratio
ratio_s = (common_idx['move'] / common_idx['vix'])
ratio_mean_90 = ratio_s.iloc[-90:].mean()
ratio_std_90  = ratio_s.iloc[-90:].std()
z_band_upper  = ratio_mean_90 + ratio_std_90
z_band_lower  = ratio_mean_90 - ratio_std_90

ax4.plot(ratio_s.index, ratio_s.values, color='#f0c040', lw=1.5, label='MOVE/VIX ratio')
ax4.axhline(ratio_mean_90, color='#888888', lw=0.8, ls='--', alpha=0.7, label=f'90d avg={ratio_mean_90:.2f}')
ax4.fill_between(ratio_s.iloc[-90:].index,
                 z_band_lower, z_band_upper,
                 color='#f0c040', alpha=0.08, label='±1σ band (90d)')
ax4.axvline(fomc_date, color='#ff6b6b', lw=1.2, ls='-', alpha=0.5)
ax4.set_ylabel('MOVE/VIX', color='#c8ccd4', fontsize=9)
ax4.text(0.99, 0.88, f'現值 {move_vix_ratio_latest:.2f}\n90d z = {move_vix_z:.2f}',
         transform=ax4.transAxes, color='#f0c040', fontsize=10, ha='right', fontweight='bold')
ax4.legend(loc='upper left', fontsize=8, framealpha=0.3,
           labelcolor='#c8ccd4', facecolor='#1c1f26')
ax4.set_title('MOVE/VIX 比值與殖利率曲線斜率\n(衡量債市 vs 股市波動率分歧)',
              color='#e6edf3', fontsize=11, pad=8)

# 殖利率曲線
tnx_s = df['us10y_yield'].dropna()
irx_s = df['us3m_yield'].dropna()
# align
idx_common = tnx_s.index.intersection(irx_s.index)
spread_s = tnx_s[idx_common] - irx_s[idx_common]

ax5.plot(tnx_s.index, tnx_s.values, color='#58a6ff', lw=1.5, label='US 10Y Yield (%)')
ax5.plot(irx_s.index, irx_s.values, color='#85e89d', lw=1.2, ls='--', label='US 3M Yield (%)')
ax5_twin = ax5.twinx()
ax5_twin.set_facecolor('#0f1117')
ax5_twin.tick_params(colors='#c8ccd4', labelsize=8)
ax5_twin.spines['right'].set_color('#3a3f4b')
ax5_twin.spines['top'].set_visible(False)
ax5_twin.plot(spread_s.index, spread_s.values, color='#ffa07a', lw=1.0, alpha=0.7,
              label='10Y-3M spread')
ax5_twin.axhline(0, color='#666666', lw=0.8, ls=':')
ax5_twin.set_ylabel('10Y-3M spread (%)', color='#ffa07a', fontsize=8)
ax5.axvline(fomc_date, color='#ff6b6b', lw=1.2, ls='-', alpha=0.5)
ax5.set_ylabel('Yield (%)', color='#c8ccd4', fontsize=9)
ax5.text(0.99, 0.88, f'10Y={us10y:.2f}%  3M={us3m:.2f}%\nspread={spread_10y3m:+.2f}%',
         transform=ax5.transAxes, color='#58a6ff', fontsize=9, ha='right', fontweight='bold')
lines1, labels1 = ax5.get_legend_handles_labels()
lines2, labels2 = ax5_twin.get_legend_handles_labels()
ax5.legend(lines1 + lines2, labels1 + labels2, loc='upper left', fontsize=8,
           framealpha=0.3, labelcolor='#c8ccd4', facecolor='#1c1f26')
ax5.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
ax5.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
plt.xticks(rotation=30, color='#c8ccd4')

plt.tight_layout()
fig_path2 = os.path.join(FIGS_DIR, 'move_vix_ratio_yields.png')
fig2.savefig(fig_path2, dpi=150, bbox_inches='tight', facecolor='#0f1117')
plt.close(fig2)
print(f"✓ Fig 2 saved: {fig_path2}")

# ── 輸出 results.json ─────────────────────────────────────────
results = {
    "experiment_id": "trending_repost_2026_06_17_warsh_first_fomc",
    "task_type": "trending_repost",
    "as_of_date": str(latest_date),
    "fomc_date": "2026-06-17",
    "scenario": {
        "cpi_may2026_yoy_pct": cpi_may2026_yoy,
        "fed_funds_upper_pct": fed_funds_upper,
        "note": "CPI 4.2% per task brief scenario; Fed Funds upper 4.50% (hold scenario)"
    },
    "vol_metrics": {
        "vix": round(vix_latest, 2),
        "vix9d": round(vix9d_latest, 2),
        "vix9d_vix_ratio": round(vix9d_vix_ratio, 4),
        "vix9d_inverted": bool(vix9d_latest > vix_latest),  # True = short-term fear > medium-term
        "move": round(move_latest, 2),
        "vix_30d_mean": round(vix_mean_30d, 2),
        "vix_30d_std":  round(vix_std_30d, 2),
        "move_30d_mean": round(move_mean_30d, 2),
        "move_30d_std": round(move_std_30d, 2),
    },
    "cross_asset_ratio": {
        "move_vix_ratio_latest": round(move_vix_ratio_latest, 4),
        "move_vix_ratio_30d_mean": round(move_vix_ratio_mean, 4),
        "move_vix_ratio_30d_std": round(move_vix_ratio_std, 4),
        "move_vix_30d_z": round(move_vix_z, 3),
        "move_vix_90d_mean": round(ratio_mean_90, 4),
        "move_vix_90d_std": round(ratio_std_90, 4),
        "move_vix_90d_percentile": round(percentile_90d, 1),
    },
    "rates": {
        "us_10y_yield_pct": round(us10y, 2),
        "us_3m_yield_pct": round(us3m, 2),
        "us_5y_yield_pct": round(us5y, 2),
        "yield_curve_10y3m_spread_pct": round(spread_10y3m, 2),
        "yield_curve_status": "normal" if float(spread_10y3m) > 0 else "inverted",
    },
    "figures": [
        "figs/cross_asset_vol.png",
        "figs/move_vix_ratio_yields.png"
    ],
    "data_sources": [
        "yfinance: ^VIX, ^VIX9D, ^MOVE, ^TNX, ^IRX, ^FVX",
        "Task brief: CPI May 2026 YoY = 4.2% (scenario parameter)"
    ]
}

results_path = os.path.join(SCRIPT_DIR, 'results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2)
print(f"✓ Results saved to {results_path}")

# Print summary table
print("\n" + "=" * 60)
print("EVIDENCE SUMMARY TABLE")
print("=" * 60)
print(f"{'指標':<25} {'值':>12} {'備註'}")
print("-" * 60)
print(f"{'VIX (股市隱含vol)':<25} {vix_latest:>12.2f}")
print(f"{'VIX9D (9日隱含vol)':<25} {vix9d_latest:>12.2f}")
print(f"{'VIX9D/VIX 比值':<25} {vix9d_vix_ratio:>12.4f} {'< 1 = 短端低於中端'}")
print(f"{'MOVE (債市隱含vol)':<25} {move_latest:>12.2f}")
print(f"{'MOVE/VIX 比值':<25} {move_vix_ratio_latest:>12.4f}")
print(f"{'MOVE/VIX 90d z-score':<25} {move_vix_z:>12.3f}")
print(f"{'MOVE/VIX 90d pctile':<25} {percentile_90d:>11.0f}%")
print(f"{'US 10Y 殖利率':<25} {us10y:>11.2f}%")
print(f"{'US 3M 殖利率':<25} {us3m:>11.2f}%")
print(f"{'10Y-3M 利差':<25} {spread_10y3m:>11.2f}%")
print(f"{'5月 CPI YoY (情境)':<25} {cpi_may2026_yoy:>11.1f}%")
print(f"{'Fed Funds upper (情境)':<25} {fed_funds_upper:>11.2f}%")
print("=" * 60)
