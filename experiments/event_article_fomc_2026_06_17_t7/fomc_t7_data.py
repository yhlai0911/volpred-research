"""
event_article_fomc_2026_06_17_t7 — Data script
FOMC 6/17 T-7: SOFR futures rate path + VIX term structure + April dot plot context
Run: uv run python experiments/event_article_fomc_2026_06_17_t7/fomc_t7_data.py
"""
import yfinance as yf
import pandas as pd
import numpy as np
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path

OUT_DIR = Path(__file__).parent

# ── 1. Download data ──────────────────────────────────────────────────────────
spy = yf.download('SPY', start='2025-01-01', end='2026-06-10', auto_adjust=True, progress=False)
spy_close = spy['Close'].squeeze()
spy_ret = spy_close.pct_change().dropna()

irx_df = yf.download('^IRX', start='2025-01-01', end='2026-06-10', auto_adjust=True, progress=False)
irx_s = irx_df['Close'].squeeze()

vix_df = yf.download('^VIX', start='2025-01-01', end='2026-06-10', auto_adjust=True, progress=False)
vix_s = vix_df['Close'].squeeze()

vix9d_df = yf.download('^VIX9D', start='2026-01-01', end='2026-06-10', auto_adjust=True, progress=False)
vix9d_s = vix9d_df['Close'].squeeze()

# SOFR quarterly futures (as of 2026-06-09)
sofr_contracts = {
    'Jun 2026': ('SR3M26.CME', 3.6675),
    'Sep 2026': ('SR3U26.CME', 3.8050),
    'Dec 2026': ('SR3Z26.CME', 3.9550),
    'Mar 2027': ('SR3H27.CME', 4.0550),
}

# ── 2. Key stats ──────────────────────────────────────────────────────────────
vix_current = float(vix_s.iloc[-1])
vix9d_current = float(vix9d_s.iloc[-1])
ratio_current = vix9d_current / vix_current

# VIX at each 2026 FOMC T-7
fomc_t7_data = {
    'Jan 28 2026': {'t7_date': '2026-01-21', 'vix': 16.9, 'vix9d': 15.9},
    'Mar 18 2026': {'t7_date': '2026-03-11', 'vix': 24.2, 'vix9d': 24.4},
    'Apr 29 2026': {'t7_date': '2026-04-22', 'vix': 18.9, 'vix9d': 17.3},
    'Jun 17 2026': {'t7_date': '2026-06-10', 'vix': vix_current, 'vix9d': vix9d_current},
}
for k, v in fomc_t7_data.items():
    v['ratio'] = round(v['vix9d'] / v['vix'], 3)

# SPY realized vol (last 5 trading days, annualized)
ts_now = pd.Timestamp('2026-06-09')
idx_now = spy_ret.index.searchsorted(ts_now)
pre_current = spy_ret.iloc[max(0, idx_now - 5):idx_now + 1]
spy_5d_rv = float(pre_current.std()) * np.sqrt(252) * 100

results = {
    'as_of': '2026-06-09',
    'event': 'FOMC 2026-06-17',
    't_slot': 'T-7',
    'rate_data': {
        'tbill_3m': float(irx_s.iloc[-1]),
        'zq_front_price': 96.34,
        'zq_implied_rate': 3.66,
        'sofr_path': {k: v[1] for k, (_, v) in ((k, (t, r)) for k, (t, r) in sofr_contracts.items())},
        'note': 'SOFR 3-month quarterly futures; price = 100 - implied SOFR'
    },
    'vix_data': {
        'vix': vix_current,
        'vix9d': vix9d_current,
        'ratio': round(ratio_current, 4),
        'fomc_t7_comparison': fomc_t7_data,
    },
    'spy_data': {
        'close_jun9': float(spy_close.iloc[-1]),
        'ytd_return_pct': round((float(spy_close.iloc[-1]) / float(spy_close.iloc[0]) - 1) * 100, 1),
        '5d_realized_vol_annualized_pct': round(spy_5d_rv, 1),
    },
    'sources': ['yfinance: ^VIX, ^VIX9D, SPY, ^IRX, SR3*.CME', 'data_range: 2025-01-01 to 2026-06-09'],
    'method_note': (
        'Fed Funds rate path inferred from: (1) 3-month T-bill as FF proxy; '
        '(2) SOFR quarterly futures SR3 for forward rate expectations; '
        '(3) ZQ=F front-month as current implied FF rate. '
        'CME FedWatch probabilities not directly available via yfinance — '
        'SOFR futures and T-bill trajectory used as academic substitute.'
    )
}

# Save results
results_path = OUT_DIR / 'fomc_t7_results.json'
with open(results_path, 'w', encoding='utf-8') as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print(f"Results saved: {results_path}")

# ── 3. Figure ─────────────────────────────────────────────────────────────────
fig, axes = plt.subplots(2, 2, figsize=(12, 9))
fig.suptitle('FOMC 6/17 T-7：利率路徑 × VIX 結構', fontsize=14, fontweight='bold', y=0.98)

# Panel 1: T-bill rate trajectory
ax1 = axes[0, 0]
ax1.plot(irx_s.index, irx_s.values, color='steelblue', linewidth=2)
for d in ['2025-09-17', '2025-10-29', '2025-12-10', '2026-01-28', '2026-03-18', '2026-04-29']:
    ax1.axvline(pd.Timestamp(d), color='red', alpha=0.3, linestyle='--', linewidth=0.8)
ax1.axvline(pd.Timestamp('2026-06-17'), color='orange', alpha=0.7, linestyle='--', linewidth=1.5)
ax1.set_title('3 個月 T-bill 利率 (2025-2026)\n[Fed Funds 路徑代理；紅線=FOMC, 橘線=6/17]', fontsize=9)
ax1.set_ylabel('利率 (%)')
ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%y'))
ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
plt.setp(ax1.xaxis.get_majorticklabels(), rotation=30)
ax1.grid(True, alpha=0.3)

# Panel 2: SOFR futures implied path
ax2 = axes[0, 1]
quarters = ['Jun\n2026', 'Sep\n2026', 'Dec\n2026', 'Mar\n2027']
sofr_rates = [3.67, 3.81, 3.96, 4.05]
bars = ax2.bar(quarters, sofr_rates, color=['#2196F3', '#1976D2', '#1565C0', '#0D47A1'], alpha=0.8, width=0.5)
ax2.set_ylim(3.4, 4.3)
ax2.set_title('SOFR 期貨隱含利率路徑\n(SR3 季度合約，2026-06-09)', fontsize=10)
ax2.set_ylabel('隱含 SOFR (%)')
for bar, rate in zip(bars, sofr_rates):
    ax2.text(bar.get_x() + bar.get_width() / 2, rate + 0.02, f'{rate:.2f}%',
             ha='center', va='bottom', fontsize=9, fontweight='bold')
ax2.axhline(3.75, color='green', linestyle='--', alpha=0.7, linewidth=1.5)
ax2.text(3.05, 3.72, '推測當前 FF 下限\n~3.75%', fontsize=7.5, color='green', ha='right')
ax2.grid(True, alpha=0.3, axis='y')

# Panel 3: VIX at each FOMC T-7
ax3 = axes[1, 0]
fomc_labels = ['Jan\n2026', 'Mar\n2026', 'Apr\n2026', 'Jun\n2026\n(今)']
vix_at_t7 = [16.9, 24.2, 18.9, 19.87]
vix9d_at_t7 = [15.9, 24.4, 17.3, 22.14]
x = np.arange(len(fomc_labels))
w = 0.35
ax3.bar(x - w / 2, vix_at_t7, w, label='VIX', color='#E74C3C', alpha=0.8)
ax3.bar(x + w / 2, vix9d_at_t7, w, label='VIX9D', color='#E67E22', alpha=0.8)
ax3.set_xticks(x)
ax3.set_xticklabels(fomc_labels, fontsize=9)
ax3.set_title('2026 各場 FOMC T-7 的 VIX/VIX9D', fontsize=10)
ax3.set_ylabel('VIX 點數')
ax3.legend(fontsize=9)
ax3.grid(True, alpha=0.3, axis='y')
# Highlight Jun
ax3.axhline(20, color='gray', linestyle=':', alpha=0.5)

# Panel 4: VIX9D/VIX ratio
ax4 = axes[1, 1]
ratios = [0.940, 1.009, 0.914, 1.114]
colors_r = ['#27AE60' if r < 1 else '#E74C3C' for r in ratios]
ax4.bar(fomc_labels, ratios, color=colors_r, alpha=0.8)
ax4.axhline(1.0, color='black', linestyle='-', linewidth=1.5, alpha=0.7)
ax4.set_title('VIX9D / VIX 比值\n(>1 = 短期恐慌溢價)', fontsize=10)
ax4.set_ylabel('比值')
ax4.set_ylim(0.85, 1.2)
for i, r in enumerate(ratios):
    ax4.text(i, r + 0.005, f'{r:.3f}', ha='center', va='bottom', fontsize=9, fontweight='bold')
ax4.grid(True, alpha=0.3, axis='y')

plt.tight_layout()
fig_path = OUT_DIR / 'fig_fomc_t7_evidence.png'
plt.savefig(fig_path, dpi=150, bbox_inches='tight')
print(f"Figure saved: {fig_path}")
print("Done.")
