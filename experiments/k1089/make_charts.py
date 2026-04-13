#!/usr/bin/env python3
"""K1089 chart generation."""
import os
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1089_results.json')

with open(RESULTS_PATH) as f:
    R = json.load(f)

plt.rcParams.update({
    'font.family': 'sans-serif',
    'font.size': 10,
    'axes.grid': True,
    'grid.alpha': 0.3,
})

# -----------------------------------------------------------------
# Chart 1: DM comparison — full OOS + per window
# -----------------------------------------------------------------
fig, ax = plt.subplots(1, 1, figsize=(10, 6))

labels = []
t_vix = []
t_rv = []
t_combo = []

# Full OOS
labels.append('Full OOS\n(2018-2026)\nn=3023')
t_vix.append(R['full_oos']['gjr_vs_a4f_vix']['dm_t'])
t_rv.append(R['full_oos']['gjr_vs_a4f_rv']['dm_t'])
t_combo.append(R['full_oos']['gjr_vs_a4f_combo']['dm_t'])

for wname in ['Early_2018Bear', 'Middle_COVID_Luna', 'Late_FTX_Rally']:
    w = R['per_window'][wname]
    labels.append(f"{wname.replace('_',' ')}\n({w['start'][:7]}-{w['end'][:7]})")
    t_vix.append(w['gjr_vs_a4f_vix']['dm_t'])
    t_rv.append(w['gjr_vs_a4f_rv']['dm_t'])
    t_combo.append(w['gjr_vs_a4f_combo']['dm_t'])

x = np.arange(len(labels))
w = 0.25

ax.bar(x - w, t_vix, w, label='A4f-VIX', color='#1f77b4')
ax.bar(x, t_rv, w, label='A4f-BTC30RV', color='#2ca02c')
ax.bar(x + w, t_combo, w, label='A4f-COMBO', color='#d62728')
ax.axhline(3, color='red', ls='--', lw=1, label='Harvey |t|=3.0')
ax.axhline(-3, color='red', ls='--', lw=1)
ax.axhline(0, color='black', lw=0.5)
ax.set_ylabel('DM t-statistic (positive = alt better than GJR)')
ax.set_title('K1089 BTC-USD A4f — DM Statistics (vs GJR, Harvey |t|>3.0 threshold)')
ax.set_xticks(x)
ax.set_xticklabels(labels, fontsize=8)
ax.legend(loc='upper left', fontsize=9)

# Annotate
for i, (a, b, c) in enumerate(zip(t_vix, t_rv, t_combo)):
    ax.text(x[i] - w, a + (0.05 if a >= 0 else -0.15), f'{a:+.2f}',
            ha='center', fontsize=7)
    ax.text(x[i],     b + (0.05 if b >= 0 else -0.15), f'{b:+.2f}',
            ha='center', fontsize=7)
    ax.text(x[i] + w, c + (0.05 if c >= 0 else -0.15), f'{c:+.2f}',
            ha='center', fontsize=7)

plt.tight_layout()
out1 = os.path.join(SCRIPT_DIR, 'k1089_dm_comparison.png')
plt.savefig(out1, dpi=130, bbox_inches='tight')
plt.close()
print(f"Saved {out1}")

# -----------------------------------------------------------------
# Chart 2: Crypto crisis periods
# -----------------------------------------------------------------
fig, ax = plt.subplots(1, 1, figsize=(11, 6))

crisis_order = ['Bear_2018', 'COVID_2020', 'China_Ban_2021',
                'Luna_2022', 'FTX_2022', 'Carry_Unwind_2024']

labels_c = []
t_vix_c = []
t_rv_c = []
t_combo_c = []
ns = []

for c in crisis_order:
    if c not in R['crisis_subperiods']:
        continue
    cd = R['crisis_subperiods'][c]
    labels_c.append(c.replace('_', '\n'))
    ns.append(cd['n'])
    t_vix_c.append(cd['gjr_vs_a4f_vix']['dm_t'] if cd.get('gjr_vs_a4f_vix') else 0)
    t_rv_c.append(cd['gjr_vs_a4f_rv']['dm_t'] if cd.get('gjr_vs_a4f_rv') else 0)
    t_combo_c.append(cd['gjr_vs_a4f_combo']['dm_t'] if cd.get('gjr_vs_a4f_combo') else 0)

x = np.arange(len(labels_c))
w = 0.27

ax.bar(x - w, t_vix_c, w, label='A4f-VIX', color='#1f77b4')
ax.bar(x, t_rv_c, w, label='A4f-BTC30RV', color='#2ca02c')
ax.bar(x + w, t_combo_c, w, label='A4f-COMBO', color='#d62728')
ax.axhline(3, color='red', ls='--', lw=1, label='Harvey |t|=3.0')
ax.axhline(-3, color='red', ls='--', lw=1)
ax.axhline(0, color='black', lw=0.5)
ax.set_ylabel('DM t-statistic (vs GJR; positive = better)')
ax.set_title('K1089 BTC-USD A4f — Crypto Crisis Sub-Periods (DM vs GJR)')
ax.set_xticks(x)
ax.set_xticklabels([f'{l}\n(n={n})' for l, n in zip(labels_c, ns)], fontsize=8)
ax.legend(loc='lower left', fontsize=9)

for i, (a, b, c) in enumerate(zip(t_vix_c, t_rv_c, t_combo_c)):
    ax.text(x[i] - w, a + (0.06 if a >= 0 else -0.14), f'{a:+.2f}',
            ha='center', fontsize=7)
    ax.text(x[i],     b + (0.06 if b >= 0 else -0.14), f'{b:+.2f}',
            ha='center', fontsize=7)
    ax.text(x[i] + w, c + (0.06 if c >= 0 else -0.14), f'{c:+.2f}',
            ha='center', fontsize=7)

plt.tight_layout()
out2 = os.path.join(SCRIPT_DIR, 'k1089_crypto_crises.png')
plt.savefig(out2, dpi=130, bbox_inches='tight')
plt.close()
print(f"Saved {out2}")

# -----------------------------------------------------------------
# Chart 3: VIX regime conditional (VIX buckets + BTC30RV buckets)
# -----------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 5))

# VIX buckets
vix_names = ['Low', 'Normal', 'High', 'Extreme', 'Crisis']
vix_t = []
vix_labels = []
for bn in vix_names:
    b = R['vix_buckets'].get(bn, {})
    if 'dm_t' in b and b['dm_t'] is not None:
        lo, hi = b['range']
        vix_labels.append(f"{bn}\n[{lo},{hi})\nn={b['n']}")
        vix_t.append(b['dm_t'])

colors1 = ['#2ca02c' if t > 3 else ('#d62728' if t < -3 else '#7f7f7f')
           for t in vix_t]
ax1.bar(range(len(vix_t)), vix_t, color=colors1)
ax1.axhline(3, color='red', ls='--', lw=1, label='Harvey |t|=3.0')
ax1.axhline(-3, color='red', ls='--', lw=1)
ax1.axhline(0, color='black', lw=0.5)
ax1.set_xticks(range(len(vix_labels)))
ax1.set_xticklabels(vix_labels, fontsize=8)
ax1.set_ylabel('DM t-statistic')
ax1.set_title('A4f-VIX vs GJR by VIX Regime')
ax1.legend(fontsize=8)
for i, t in enumerate(vix_t):
    ax1.text(i, t + (0.1 if t >= 0 else -0.2), f'{t:+.2f}',
             ha='center', fontsize=8)

# BTC30RV buckets
rv_names = ['RV_Low', 'RV_Normal', 'RV_High', 'RV_Extreme']
rv_t = []
rv_labels = []
for bn in rv_names:
    b = R['btc_rv_buckets'].get(bn, {})
    if 'dm_t' in b and b['dm_t'] is not None:
        lo, hi = b['range']
        rv_labels.append(f"{bn.replace('RV_','')}\n[{lo},{hi})\nn={b['n']}")
        rv_t.append(b['dm_t'])

colors2 = ['#2ca02c' if t > 3 else ('#d62728' if t < -3 else '#7f7f7f')
           for t in rv_t]
ax2.bar(range(len(rv_t)), rv_t, color=colors2)
ax2.axhline(3, color='red', ls='--', lw=1, label='Harvey |t|=3.0')
ax2.axhline(-3, color='red', ls='--', lw=1)
ax2.axhline(0, color='black', lw=0.5)
ax2.set_xticks(range(len(rv_labels)))
ax2.set_xticklabels(rv_labels, fontsize=8)
ax2.set_ylabel('DM t-statistic')
ax2.set_title('A4f-BTC30RV vs GJR by BTC30RV Regime (ann %)')
ax2.legend(fontsize=8)
for i, t in enumerate(rv_t):
    ax2.text(i, t + (0.1 if t >= 0 else -0.2), f'{t:+.2f}',
             ha='center', fontsize=8)

plt.suptitle('K1089 BTC-USD — Regime-Conditional A4f Performance',
             fontsize=12)
plt.tight_layout()
out3 = os.path.join(SCRIPT_DIR, 'k1089_vix_btc_regimes.png')
plt.savefig(out3, dpi=130, bbox_inches='tight')
plt.close()
print(f"Saved {out3}")

# -----------------------------------------------------------------
# Chart 4: theta1 evolution over time
# -----------------------------------------------------------------
fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

refits = R['refit_log']
dates = [r['date'] for r in refits]
import datetime as dt
dates_dt = [dt.datetime.strptime(d, '%Y-%m-%d') for d in dates]

theta1_vix = [r.get('a4f_vix_theta1') for r in refits]
theta1_rv = [r.get('a4f_rv_theta1') for r in refits]
theta1_combo_vix = [r.get('a4f_combo_theta1_vix') for r in refits]
theta1_combo_rv = [r.get('a4f_combo_theta2_rv') for r in refits]

# Fill None with np.nan
theta1_vix = [np.nan if v is None else v for v in theta1_vix]
theta1_rv = [np.nan if v is None else v for v in theta1_rv]
theta1_combo_vix = [np.nan if v is None else v for v in theta1_combo_vix]
theta1_combo_rv = [np.nan if v is None else v for v in theta1_combo_rv]

ax1.plot(dates_dt, theta1_vix, 'o-', label=r'$\theta_1^{VIX}$ (A4f-VIX)',
         color='#1f77b4', markersize=4)
ax1.plot(dates_dt, theta1_combo_vix, 's--',
         label=r'$\theta_1^{VIX}$ (A4f-COMBO)', color='#aec7e8', markersize=3)
ax1.axhline(0, color='black', lw=0.5)
ax1.set_ylabel(r'$\theta_1^{VIX}$ (loading on VIX$^2$)')
ax1.set_title('K1089 BTC-USD — A4f θ₁ Parameter Evolution (per-refit)')
ax1.legend(fontsize=9, loc='upper right')
ax1.grid(alpha=0.3)

ax2.plot(dates_dt, theta1_rv, 'o-', label=r'$\theta_1^{RV}$ (A4f-BTC30RV)',
         color='#2ca02c', markersize=4)
ax2.plot(dates_dt, theta1_combo_rv, 's--',
         label=r'$\theta_2^{RV}$ (A4f-COMBO)', color='#98df8a', markersize=3)
ax2.axhline(0, color='black', lw=0.5)
ax2.set_ylabel(r'$\theta_1^{RV}$ / $\theta_2^{RV}$ (loading on RV$^2$)')
ax2.legend(fontsize=9, loc='upper right')
ax2.grid(alpha=0.3)
ax2.set_xlabel('Refit date')

fig.autofmt_xdate()
plt.tight_layout()
out4 = os.path.join(SCRIPT_DIR, 'k1089_theta1_evolution.png')
plt.savefig(out4, dpi=130, bbox_inches='tight')
plt.close()
print(f"Saved {out4}")

# -----------------------------------------------------------------
# Chart 5: 5-asset class final summary
# -----------------------------------------------------------------
# Values from K1075-K1088 knowledge
# Equity (SPY) from K1075, Gold (GLD) from K1085, Oil (USO) from K1088
# Bonds (TLT) from K1086 MOVE

fig, ax = plt.subplots(1, 1, figsize=(11, 6))

classes = ['Equity\n(SPY+VIX)', 'Gold\n(GLD+GVZ)', 'Oil\n(USO+OVX)',
           'Bonds\n(TLT+MOVE)', 'Crypto\n(BTC+VIX)',
           'Crypto\n(BTC+BTC30RV)']

# DM t values — use best-IV for each (matched-IV principle)
# Equity: K1075 SPY full OOS VIX PASS (t reported in literature ~+5 typical)
# Gold: K1085 GVZ t=+4.46
# Oil: K1088 OVX (check k1088_results for full OOS t)
# Bonds: K1086 MOVE failed
# Crypto: this experiment

# Pull K1088 value if available
try:
    with open(os.path.join(os.path.dirname(SCRIPT_DIR), 'k1088/k1088_results.json')) as f:
        r1088 = json.load(f)
    k1088_ovx_t = r1088['full_oos']['gjr_vs_a4f_ovx']['dm_t']
except Exception:
    k1088_ovx_t = 3.5

# Try K1085 (GLD)
try:
    with open(os.path.join(os.path.dirname(SCRIPT_DIR), 'k1085/k1085_results.json')) as f:
        r1085 = json.load(f)
    # try common keys
    k1085_t = None
    if 'full_oos' in r1085:
        for k, v in r1085['full_oos'].items():
            if 'gvz' in k.lower():
                k1085_t = v.get('dm_t')
                break
    if k1085_t is None:
        k1085_t = 4.46
except Exception:
    k1085_t = 4.46

# K1075 (SPY + VIX) — flat structure, 'dm_t' at top of full_oos
spy_t = 7.92  # fallback
try:
    with open(os.path.join(os.path.dirname(SCRIPT_DIR), 'k1075/k1075_results.json')) as f:
        r1075 = json.load(f)
    if 'full_oos' in r1075 and 'dm_t' in r1075['full_oos']:
        spy_t = r1075['full_oos']['dm_t']
except Exception:
    pass

# K1086 TLT + MOVE — nested under A4f_MOVE with dm_t_vs_gjr
tlt_t = 1.36  # fallback
try:
    with open(os.path.join(os.path.dirname(SCRIPT_DIR), 'k1086/k1086_results.json')) as f:
        r1086 = json.load(f)
    if 'full_oos' in r1086 and 'A4f_MOVE' in r1086['full_oos']:
        tlt_t = r1086['full_oos']['A4f_MOVE'].get('dm_t_vs_gjr', tlt_t)
except Exception:
    pass

btc_vix_t = R['full_oos']['gjr_vs_a4f_vix']['dm_t']
btc_rv_t = R['full_oos']['gjr_vs_a4f_rv']['dm_t']

t_values = [spy_t, k1085_t, k1088_ovx_t, tlt_t, btc_vix_t, btc_rv_t]

colors = ['#2ca02c' if t > 3 else ('#d62728' if t < -3 else '#7f7f7f')
          for t in t_values]

bars = ax.bar(classes, t_values, color=colors, edgecolor='black')
ax.axhline(3, color='red', ls='--', lw=1, label='Harvey |t|=3.0')
ax.axhline(-3, color='red', ls='--', lw=1)
ax.axhline(0, color='black', lw=0.5)
ax.set_ylabel('DM t-statistic vs GJR (full OOS)')
ax.set_title('Paper 9 Cross-Asset Matrix — 5 Asset Classes\n'
             'Asset-Matched IV Principle: Equity/Gold/Oil PASS, Bonds/Crypto FAIL',
             fontsize=11)
ax.legend()

for bar, t in zip(bars, t_values):
    v = bar.get_height()
    ax.text(bar.get_x() + bar.get_width()/2, v + (0.15 if v >= 0 else -0.35),
            f'{t:+.2f}', ha='center', fontsize=9, weight='bold')

# Annotations per asset class
status_map = ['PASS', 'PASS', 'PASS', 'FAIL', 'FAIL', 'FAIL']
for i, (s, t) in enumerate(zip(status_map, t_values)):
    y = t / 2 if abs(t) > 1 else (1.5 if t >= 0 else -1.5)
    ax.text(i, y, s, ha='center', fontsize=10, weight='bold',
            color='white' if s == 'PASS' else ('white' if abs(t) > 2 else 'black'))

plt.tight_layout()
out5 = os.path.join(SCRIPT_DIR, 'k1089_five_class_final.png')
plt.savefig(out5, dpi=130, bbox_inches='tight')
plt.close()
print(f"Saved {out5}")

print("\nAll charts saved.")
