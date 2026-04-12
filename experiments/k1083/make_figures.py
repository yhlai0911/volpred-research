#!/usr/bin/env python3
"""K1083 figure generation."""
import os
import json
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1083_results.json')
with open(RESULTS_PATH) as f:
    R = json.load(f)

# Reference DM values from task brief / completed experiments
ref = R['decomposition']

# -------------------------------------------------
# FIG 1: Currency decomposition bars
#  TWD | USD-synth | EWT | EEM | SPY
# -------------------------------------------------
labels = ['0050.TW\n(TWD)\nK1077',
          '0050.TW\n(USD-synth)\nK1083',
          'EWT\n(USD ETF)\nK1082',
          'EEM\n(USD)\nK1081',
          'SPY\n(USD)\nK1075']
dm_t = [ref['baseline_0050_TWD'],
        ref['0050_USD_synth'],
        ref['EWT_reference_from_K1082'],
        ref['EEM_reference_from_K1081'],
        ref['SPY_reference_from_K1075']]
colors = ['#d62728', '#ff7f0e', '#2ca02c', '#1f77b4', '#17becf']

fig, ax = plt.subplots(figsize=(11, 6))
bars = ax.bar(labels, dm_t, color=colors, edgecolor='black', linewidth=0.8)
ax.axhline(3.0, color='gray', linestyle='--', linewidth=1, label='Harvey (2016) |t|=3.0')
ax.axhline(-3.0, color='gray', linestyle='--', linewidth=1)
ax.axhline(0.0, color='black', linewidth=0.5)
ax.set_ylabel('DM t-statistic (A4f vs GJR)', fontsize=12)
ax.set_title('K1083: Currency Decomposition of A4f-VIX² Performance Across Assets',
             fontsize=13, fontweight='bold')
for bar, v in zip(bars, dm_t):
    offset = 0.2 if v >= 0 else -0.4
    ax.text(bar.get_x() + bar.get_width()/2, v + offset,
            f'{v:+.2f}', ha='center', fontsize=11, fontweight='bold')
ax.legend(loc='upper left')
ax.set_ylim(-2, 10)
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k1083_currency_decomposition.png'), dpi=130)
plt.close(fig)
print("Saved k1083_currency_decomposition.png")

# -------------------------------------------------
# FIG 2: FX contribution per refit window
# -------------------------------------------------
fx_log = R.get('fx_contribution_log', [])
if fx_log:
    import datetime as dt
    dates = [dt.datetime.strptime(r['date'], '%Y-%m-%d') for r in fx_log]
    fx_std = [r['fx_std'] for r in fx_log]
    twd_std = [r['twd_std'] for r in fx_log]
    usd_std = [r['usd_std'] for r in fx_log]
    fx_share = [r['fx_vol_share'] for r in fx_log]

    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    ax1 = axes[0]
    ax1.plot(dates, np.array(twd_std)*np.sqrt(252), label='0050-TWD daily vol (ann)',
             color='#d62728', linewidth=1.4)
    ax1.plot(dates, np.array(usd_std)*np.sqrt(252), label='0050-USD-synth daily vol (ann)',
             color='#ff7f0e', linewidth=1.4)
    ax1.plot(dates, np.array(fx_std)*np.sqrt(252), label='TWDUSD FX daily vol (ann)',
             color='#2ca02c', linewidth=1.4)
    ax1.set_ylabel('Annualised volatility (63d rolling)')
    ax1.set_title('K1083: FX Contribution Per Refit Window')
    ax1.legend()
    ax1.grid(alpha=0.3)

    ax2 = axes[1]
    ax2.plot(dates, np.array(fx_share)*100, color='#9467bd', linewidth=1.4)
    ax2.set_ylabel('FX vol share of USD-synth vol (%)')
    ax2.set_xlabel('Refit date')
    ax2.grid(alpha=0.3)
    ax2.axhline(30, color='gray', linestyle='--', alpha=0.5, label='30% reference')
    ax2.legend()
    plt.tight_layout()
    fig.savefig(os.path.join(SCRIPT_DIR, 'k1083_fx_contribution.png'), dpi=130)
    plt.close(fig)
    print("Saved k1083_fx_contribution.png")

# -------------------------------------------------
# FIG 3: Marginal contribution decomposition
#   bars show delta-DM between adjacent assets
# -------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))
steps = [
    ('Currency\nwrapper\n(TWD→USD)', ref['0050_USD_synth'] - ref['baseline_0050_TWD'], '#ff7f0e'),
    ('Composition\n(0050-USD→EWT)', ref['EWT_reference_from_K1082'] - ref['0050_USD_synth'], '#2ca02c'),
    ('Diversification\n(EWT→EEM)', ref['EEM_reference_from_K1081'] - ref['EWT_reference_from_K1082'], '#1f77b4'),
    ('US-native\n(EEM→SPY)', ref['SPY_reference_from_K1075'] - ref['EEM_reference_from_K1081'], '#17becf'),
]
step_labels = [s[0] for s in steps]
step_vals = [s[1] for s in steps]
step_colors = [s[2] for s in steps]
bars = ax.bar(step_labels, step_vals, color=step_colors, edgecolor='black', linewidth=0.8)
for bar, v in zip(bars, step_vals):
    off = 0.1 if v >= 0 else -0.3
    ax.text(bar.get_x() + bar.get_width()/2, v + off,
            f'{v:+.2f}', ha='center', fontsize=11, fontweight='bold')
ax.axhline(0, color='black', linewidth=0.5)
ax.set_ylabel('Marginal Δ DM t-statistic')
ax.set_title('K1083: Marginal Contribution Decomposition of A4f Performance')
ax.grid(axis='y', alpha=0.3)
# annotate cumulative
cum_txt = (f"Cumulative path:  K1077={ref['baseline_0050_TWD']:+.2f}"
           f"  →  K1083={ref['0050_USD_synth']:+.2f}"
           f"  →  K1082={ref['EWT_reference_from_K1082']:+.2f}"
           f"  →  K1081={ref['EEM_reference_from_K1081']:+.2f}"
           f"  →  K1075={ref['SPY_reference_from_K1075']:+.2f}")
ax.text(0.5, -0.22, cum_txt, transform=ax.transAxes, ha='center', fontsize=9,
        bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.7))
plt.tight_layout()
fig.savefig(os.path.join(SCRIPT_DIR, 'k1083_decomposition_bars.png'),
            dpi=130, bbox_inches='tight')
plt.close(fig)
print("Saved k1083_decomposition_bars.png")

# -------------------------------------------------
# FIG 4: θ₁ stability (TWD vs USD-synth)
# -------------------------------------------------
twd_refit = R.get('refit_log_twd', [])
usd_refit = R.get('refit_log_usd', [])
if twd_refit and usd_refit:
    import datetime as dt
    dates_t = [dt.datetime.strptime(r['date'], '%Y-%m-%d') for r in twd_refit
               if r.get('a4f_theta1') is not None]
    theta1_t = [r['a4f_theta1'] for r in twd_refit if r.get('a4f_theta1') is not None]
    dates_u = [dt.datetime.strptime(r['date'], '%Y-%m-%d') for r in usd_refit
               if r.get('a4f_theta1') is not None]
    theta1_u = [r['a4f_theta1'] for r in usd_refit if r.get('a4f_theta1') is not None]

    fig, ax = plt.subplots(figsize=(11, 6))
    ax.semilogy(dates_t, theta1_t, 'o-', label='0050.TW (TWD) θ₁',
                color='#d62728', markersize=5, linewidth=1.3)
    ax.semilogy(dates_u, theta1_u, 's-', label='0050.TW (USD-synth) θ₁',
                color='#ff7f0e', markersize=5, linewidth=1.3)
    ax.axhline(1e-7, color='#1f77b4', linestyle='--', alpha=0.6,
               label='SPY K1075 θ₁ ≈ 1e-7')
    ax.set_ylabel('θ₁ (A4f VIX² loading, log scale)')
    ax.set_xlabel('Refit date')
    ax.set_title('K1083: A4f θ₁ Stability — TWD vs USD-synthetic Return Series')
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(os.path.join(SCRIPT_DIR, 'k1083_theta1_stability.png'), dpi=130)
    plt.close(fig)
    print("Saved k1083_theta1_stability.png")

print("All figures saved.")
