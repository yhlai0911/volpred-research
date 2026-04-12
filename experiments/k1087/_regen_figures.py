#!/usr/bin/env python3
"""Regenerate K1087 figures from saved results JSON (no re-run needed).

This re-downloads TLT/VIX/MOVE/yield data (cheap) and regenerates the 5 figures
using the full_oos, refit_log, and pairwise_dm data from the results JSON.
"""
import os
import sys
import json
import numpy as np
import pandas as pd
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1087_results.json')
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..', '..'))

with open(RESULTS_PATH) as f:
    results = json.load(f)

n_valid = results['metadata']['n_valid']
full = results['full_oos']
refit_log = results['refit_log']
pairwise = results['pairwise_dm']
crisis = results['crisis_subperiods']

MODEL_KEYS = ['GJR', 'A4f_VIX', 'A4f_MOVE', 'A4f_Level', 'A4f_Slope',
              'A4f_RateVol', 'A4f_Butterfly', 'A4f_Combo']

# --- Re-download data for time series figures ---
import yfinance as yf

def _flatten(d):
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)
    return d

tlt_raw = _flatten(yf.download('TLT', start='2003-01-02', end='2026-04-11',
                               progress=False, auto_adjust=False))
tlt_px = tlt_raw['Adj Close'] if 'Adj Close' in tlt_raw.columns else tlt_raw['Close']
vix_raw = _flatten(yf.download('^VIX', start='2003-01-02', end='2026-04-11',
                               progress=False, auto_adjust=False))
vix_close = vix_raw['Close']
move_raw = _flatten(yf.download('^MOVE', start='2003-01-02', end='2026-04-11',
                                progress=False, auto_adjust=False))
move_close = move_raw['Close']


def _load_fred(sid):
    cache = os.path.join(PROJECT_ROOT, 'storage', 'macro', f'fred_{sid}.csv')
    if os.path.exists(cache):
        d = pd.read_csv(cache)
        d['observation_date'] = pd.to_datetime(d['observation_date'])
        d = d.set_index('observation_date')
        return pd.to_numeric(d[sid], errors='coerce').ffill(limit=3)
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd=2003-01-02&coed=2026-04-11'
    d = pd.read_csv(url)
    d['observation_date'] = pd.to_datetime(d['observation_date'])
    d = d.set_index('observation_date')
    return pd.to_numeric(d[sid], errors='coerce').ffill(limit=3)


y10 = _load_fred('DGS10')
y2 = _load_fred('DGS2')
y5 = _load_fred('DGS5')

df = pd.DataFrame({
    'price': tlt_px,
    'log_ret': np.log(tlt_px / tlt_px.shift(1)),
    'VIX': vix_close,
    'MOVE': move_close,
    'Y10': y10, 'Y2': y2, 'Y5': y5,
}).dropna()

dates = df.index
y10_v = df['Y10'].values
y2_v = df['Y2'].values
slope_raw = y10_v - y2_v
dy10_raw = np.concatenate([[0.0], np.diff(y10_v)])
abs_dy10_bps = np.abs(dy10_raw) * 100
tlt_px_aligned = df['price'].values

# Figure 1: Regressor comparison DM matrix
print("Generating Fig 1: regressor comparison...")
fig, ax = plt.subplots(figsize=(10, 5))
model_labels = [k.replace('A4f_', '') for k in MODEL_KEYS if k != 'GJR']
tvals = [full[k]['dm_t_vs_gjr'] for k in MODEL_KEYS if k != 'GJR']
tvals_plot = [t if t is not None and np.isfinite(t) else 0 for t in tvals]
colors = ['#d62728' if (t is not None and np.isfinite(t) and abs(t) > 3.0 and t > 0) else
          ('#2ca02c' if (t is not None and np.isfinite(t) and t > 1.5) else '#1f77b4')
          for t in tvals]
bars = ax.bar(model_labels, tvals_plot, color=colors, alpha=0.85, edgecolor='black')
ax.axhline(3.0, color='red', linestyle='--', label='Harvey |t|=3.0')
ax.axhline(-3.0, color='red', linestyle='--')
ax.axhline(0, color='black', linewidth=0.5)
for bar, t in zip(bars, tvals_plot):
    ax.text(bar.get_x() + bar.get_width()/2, t + (0.1 if t >= 0 else -0.3),
            f'{t:+.2f}', ha='center', fontsize=9)
ax.set_ylabel('DM t-statistic vs GJR (positive = better)')
ax.set_title(f'K1087 TLT: 7 A4f regressor variants vs GJR, Full OOS (n={n_valid})')
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_regressor_comparison.png'), dpi=120)
plt.close()

# Figure 2: Yield-curve time series
print("Generating Fig 2: yield curve time series...")
fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
axes[0].plot(dates, y10_v, color='#1f77b4', linewidth=0.8, label='10Y')
axes[0].plot(dates, y2_v, color='#d62728', linewidth=0.8, alpha=0.7, label='2Y')
axes[0].set_ylabel('Yield (%)')
axes[0].set_title('10Y (blue) and 2Y (red) Treasury Yields')
axes[0].grid(alpha=0.3)
axes[0].legend()

axes[1].plot(dates, slope_raw, color='#2ca02c', linewidth=0.8)
axes[1].axhline(0, color='black', linewidth=0.5, linestyle='--')
axes[1].set_ylabel('Slope (%)')
axes[1].set_title('Yield-Curve Slope (10Y - 2Y) — negative = inverted')
axes[1].grid(alpha=0.3)

axes[2].plot(dates, abs_dy10_bps, color='#9467bd', linewidth=0.5)
axes[2].set_ylabel('|ΔY_10Y| (bps)')
axes[2].set_title('Daily |10Y change| (realized rate vol proxy)')
axes[2].grid(alpha=0.3)
axes[2].set_xlabel('Date')

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_yield_curve.png'), dpi=120)
plt.close()

# Figure 3: 2022 rate-hike period
print("Generating Fig 3: 2022 rate hike...")
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
mask_2022 = (dates >= '2022-01-01') & (dates <= '2022-12-31')
axes[0].plot(dates[mask_2022], tlt_px_aligned[mask_2022], color='black', linewidth=1)
axes[0].set_ylabel('TLT price')
axes[0].set_title('TLT during 2022 rising-rate regime')
axes[0].grid(alpha=0.3)
axes[1].plot(dates[mask_2022], y10_v[mask_2022], color='#1f77b4', label='10Y yield (%)')
ax2b = axes[1].twinx()
ax2b.plot(dates[mask_2022], abs_dy10_bps[mask_2022], color='#d62728', alpha=0.5,
          label='|ΔY| (bps)', linewidth=0.7)
axes[1].set_ylabel('10Y yield (%)', color='#1f77b4')
ax2b.set_ylabel('|ΔY| (bps)', color='#d62728')
axes[1].set_title('Yield level and realized rate vol')
axes[1].grid(alpha=0.3)
axes[1].set_xlabel('Date')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_2022_rate_hike.png'), dpi=120)
plt.close()

# Figure 4: theta1 stability across refits
print("Generating Fig 4: theta1 stability...")
fig, axes = plt.subplots(len([k for k in MODEL_KEYS if k != 'GJR']), 1,
                          figsize=(11, 14), sharex=True)
rl_dates = [datetime.strptime(r['date'], '%Y-%m-%d') for r in refit_log]
for ax_i, mkey in enumerate([k for k in MODEL_KEYS if k != 'GJR']):
    theta_key = mkey + '_theta1'
    thetas = [r.get(theta_key) for r in refit_log]
    axes[ax_i].plot(rl_dates, thetas, 'o-', markersize=4, color='#1f77b4', alpha=0.8)
    axes[ax_i].set_ylabel(f'θ1 ({mkey})')
    axes[ax_i].grid(alpha=0.3)
axes[-1].set_xlabel('Refit date')
axes[0].set_title('K1087 TLT: θ1 evolution across refits (seed=42, W=2000, 63d refit)')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_theta1_compare.png'), dpi=120)
plt.close()

# Figure 5: Asset-class × regressor final matrix
print("Generating Fig 5: asset class matrix...")
fig, ax = plt.subplots(figsize=(10, 4.5))
asset_rows = ['Equity (SPY)', 'Gold (GLD)', 'Bond (TLT)']
col_labels = ['VIX', 'GVZ', 'MOVE', 'Y10 Level', '|ΔY| RateVol', 'Combo']
tlt_vix = full['A4f_VIX']['dm_t_vs_gjr']
tlt_move = full['A4f_MOVE']['dm_t_vs_gjr']
tlt_lvl = full['A4f_Level']['dm_t_vs_gjr']
tlt_rv = full['A4f_RateVol']['dm_t_vs_gjr']
tlt_combo = full['A4f_Combo']['dm_t_vs_gjr']
matrix = np.array([
    [4.48, np.nan, np.nan, np.nan, np.nan, np.nan],
    [1.83, 4.46, np.nan, np.nan, np.nan, np.nan],
    [tlt_vix, np.nan, tlt_move, tlt_lvl, tlt_rv, tlt_combo],
])
im = ax.imshow(matrix, cmap='RdYlGn', vmin=-5, vmax=5, aspect='auto')
ax.set_xticks(np.arange(len(col_labels)))
ax.set_xticklabels(col_labels, rotation=20, ha='right')
ax.set_yticks(np.arange(len(asset_rows)))
ax.set_yticklabels(asset_rows)
for i in range(matrix.shape[0]):
    for j in range(matrix.shape[1]):
        val = matrix[i, j]
        if np.isnan(val):
            ax.text(j, i, 'n/a', ha='center', va='center', color='gray', fontsize=9)
        else:
            ax.text(j, i, f'{val:+.2f}', ha='center', va='center',
                    color='black', fontsize=10, fontweight='bold')
ax.set_title('Asset-matched regressor theory: A4f DM t vs GJR\n'
             '(K1075 SPY + K1085 GLD + K1086 TLT IV + K1087 TLT yield-curve)')
plt.colorbar(im, ax=ax, label='DM t-stat')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1087_asset_class_final.png'), dpi=120)
plt.close()

print("All 5 figures regenerated.")
