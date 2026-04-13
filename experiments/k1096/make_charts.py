#!/usr/bin/env python3
"""Charts for K1096 — BTC Regime-Switching A4f."""
import json
import os
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(SCRIPT_DIR, 'k1096_results.json')) as f:
    r = json.load(f)

# =============== Chart 1: 5-model DM t-statistic comparison =================
fig, ax = plt.subplots(figsize=(10, 5.5))
models = [('vix', 'A4f-VIX\n(K1089)'),
          ('reg_voff', 'Reg: VIX-OFF\nwhen VIX>=25'),
          ('reg_corron', 'Reg: VIX-ON\nwhen |corr|>0.3'),
          ('adaptive', 'Adaptive\n(smooth |corr|)')]

full_dm = []
for label, _ in models:
    v = r['full_oos_vs_gjr'].get(f'gjr_vs_{label}', {})
    full_dm.append(v.get('dm_t', np.nan))

x = np.arange(len(models))
colors = ['#2E86AB' if t > 0 else '#C73E1D' for t in full_dm]
bars = ax.bar(x, full_dm, color=colors, edgecolor='black', linewidth=1)

ax.axhline(y=3.0, color='green', linestyle='--', linewidth=1, label='Harvey PASS (|t|>3)')
ax.axhline(y=-3.0, color='green', linestyle='--', linewidth=1)
ax.axhline(y=0, color='black', linewidth=0.5)

ax.set_xticks(x)
ax.set_xticklabels([m[1] for m in models], fontsize=9)
ax.set_ylabel('DM t-statistic (vs GJR baseline)', fontsize=11)
ax.set_title('K1096: BTC Regime-Switching A4f — Full OOS DM t-stat (n=3023, 2018-2026)',
             fontsize=12)
ax.set_ylim(-4, 4)
ax.grid(axis='y', alpha=0.3)
ax.legend(loc='upper right')

for i, (bar, t) in enumerate(zip(bars, full_dm)):
    if np.isfinite(t):
        ax.text(bar.get_x() + bar.get_width()/2, t + 0.15 if t > 0 else t - 0.3,
                f'{t:+.2f}', ha='center', fontsize=9, fontweight='bold')

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1096_regime_dm.png'), dpi=120)
plt.close()
print('Saved k1096_regime_dm.png')

# =============== Chart 2: BTC-SPY rolling correlation time series =================
fc = r['forecasts']
dates = [datetime.strptime(d, '%Y-%m-%d') for d in fc['dates']]
corr = np.array(fc['corr60d_lag'])
vix_lag = np.array(fc['vix_lag'])

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

ax1.plot(dates, corr, color='#1f77b4', linewidth=0.8, label='60d corr(BTC, SPY)')
ax1.axhline(y=0.3, color='orange', linestyle='--', linewidth=1, label='|corr|=0.3 threshold')
ax1.axhline(y=-0.3, color='orange', linestyle='--', linewidth=1)
ax1.axhline(y=0, color='black', linewidth=0.5)
ax1.fill_between(dates, 0.3, corr, where=(corr > 0.3), alpha=0.2, color='green',
                 label='High-corr regime (|corr|>0.3)')
ax1.fill_between(dates, -0.3, corr, where=(corr < -0.3), alpha=0.2, color='green')
ax1.set_ylabel('60d correlation', fontsize=10)
ax1.set_title('K1096: BTC–SPY 60-day Rolling Correlation (lagged, regime switch input)',
              fontsize=12)
ax1.legend(loc='upper left', fontsize=8)
ax1.grid(True, alpha=0.3)
ax1.set_ylim(-0.5, 0.8)

ax2.plot(dates, vix_lag, color='#d62728', linewidth=0.8, label='VIX_{t-1}')
ax2.axhline(y=25, color='orange', linestyle='--', linewidth=1, label='VIX=25 threshold')
ax2.fill_between(dates, 25, vix_lag, where=(vix_lag > 25), alpha=0.2, color='red',
                 label='High-VIX regime')
ax2.set_ylabel('VIX', fontsize=10)
ax2.set_xlabel('Date', fontsize=10)
ax2.legend(loc='upper left', fontsize=8)
ax2.grid(True, alpha=0.3)
ax2.xaxis.set_major_locator(mdates.YearLocator())
ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1096_correlation_ts.png'), dpi=120)
plt.close()
print('Saved k1096_correlation_ts.png')

# =============== Chart 3: theta1 evolution across refits =================
refit_log = r['refit_log']
refit_dates = [datetime.strptime(x['date'], '%Y-%m-%d') for x in refit_log]
theta1_vix = [x.get('vix_theta1', np.nan) for x in refit_log]
theta1_voff = [x.get('voff_theta1', np.nan) for x in refit_log]
theta1_corron = [x.get('corron_theta1', np.nan) for x in refit_log]
theta1_adap = [x.get('adap_theta1', np.nan) for x in refit_log]

fig, ax = plt.subplots(figsize=(11, 5.5))
ax.plot(refit_dates, theta1_vix, marker='o', markersize=4, label='A4f-VIX (full)',
        color='#1f77b4')
ax.plot(refit_dates, theta1_voff, marker='s', markersize=4,
        label='Reg-VIX-OFF-HighVIX', color='#2ca02c')
ax.plot(refit_dates, theta1_corron, marker='^', markersize=4,
        label='Reg-VIX-ON-HighCorr', color='#ff7f0e')
ax.plot(refit_dates, theta1_adap, marker='d', markersize=4, label='Adaptive |corr|',
        color='#9467bd')
ax.axhline(y=0, color='black', linewidth=0.5)
ax.set_ylabel('theta1 (VIX² loading coefficient)', fontsize=10)
ax.set_xlabel('Refit date', fontsize=10)
ax.set_title('K1096: theta1 Evolution Across 49 Refits (BTC A4f variants)',
             fontsize=12)
ax.legend(loc='best', fontsize=9)
ax.grid(True, alpha=0.3)
ax.xaxis.set_major_locator(mdates.YearLocator())
ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1096_theta1_by_regime.png'), dpi=120)
plt.close()
print('Saved k1096_theta1_by_regime.png')

# =============== Chart 4: VIX bucket DM t-stat (show "damage disappears") ===
fig, ax = plt.subplots(figsize=(11, 5.5))

buckets = ['Low\n[0,15)', 'Normal\n[15,25)', 'High\n[25,40)', 'Extreme\n[40,60)']
bucket_keys = ['Low', 'Normal', 'High', 'Extreme']
model_labels = ['vix', 'reg_voff', 'reg_corron', 'adaptive']
model_display = ['A4f-VIX', 'Reg-VIX-OFF', 'Reg-VIX-ON-Corr', 'Adaptive']
colors_m = ['#1f77b4', '#2ca02c', '#ff7f0e', '#9467bd']

x = np.arange(len(buckets))
width = 0.2

for i, (mk, ml, c) in enumerate(zip(model_labels, model_display, colors_m)):
    vals = []
    for bk in bucket_keys:
        b_entry = r['vix_buckets_vs_gjr'].get(bk, {})
        if isinstance(b_entry, dict) and 'models' in b_entry:
            t = b_entry['models'].get(mk, {}).get('dm_t')
            vals.append(t if t is not None else np.nan)
        else:
            vals.append(np.nan)
    ax.bar(x + (i - 1.5) * width, vals, width, label=ml, color=c, edgecolor='black',
           linewidth=0.5)

ax.axhline(y=3.0, color='green', linestyle='--', linewidth=1, label='Harvey |t|=3')
ax.axhline(y=-3.0, color='red', linestyle='--', linewidth=1)
ax.axhline(y=0, color='black', linewidth=0.5)

ax.set_xticks(x)
ax.set_xticklabels(buckets, fontsize=9)
ax.set_ylabel('DM t-statistic (vs GJR)', fontsize=10)
ax.set_title('K1096: VIX-bucket DM t — Does high-VIX damage disappear under regime switching?',
             fontsize=11)
ax.legend(loc='lower right', fontsize=9, ncol=2)
ax.grid(axis='y', alpha=0.3)

# Annotate the High bucket to show the "rescue"
ax.annotate('High-VIX damage\nreduced', xy=(2, -2), xytext=(2.8, -3.5),
            fontsize=9, ha='center', color='darkred',
            arrowprops=dict(arrowstyle='->', color='darkred'))

plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1096_vix_bucket_rescue.png'), dpi=120)
plt.close()
print('Saved k1096_vix_bucket_rescue.png')

print('\nAll charts generated.')
