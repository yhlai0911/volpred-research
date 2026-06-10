"""Generate figures for the VT-trend-following paper."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import json
from pathlib import Path

# ── Academic style ──────────────────────────────────────────────────
plt.rcParams.update({
    'font.family': 'serif',
    'font.serif': ['Times New Roman', 'DejaVu Serif'],
    'font.size': 10,
    'axes.labelsize': 11,
    'axes.titlesize': 12,
    'xtick.labelsize': 9,
    'ytick.labelsize': 9,
    'legend.fontsize': 9,
    'figure.dpi': 300,
    'savefig.dpi': 300,
    'savefig.bbox': 'tight',
    'axes.linewidth': 0.8,
    'grid.linewidth': 0.4,
    'grid.alpha': 0.3,
})


# ====================================================================
# Figure 1: VT Return Decomposition — Sharpe vs MDD Channels
# Data from Table 3 (dual mechanism decomposition)
# ====================================================================

def figure1_return_decomposition():
    """
    Stacked bar chart showing how VT's benefits decompose into
    TSMOM-attributable and TSMOM-independent components for both
    Sharpe and MDD channels, across 5 assets.
    """
    paper_dir = Path(__file__).resolve().parents[1]
    fig_dir = Path(__file__).resolve().parent
    k1192 = json.loads((paper_dir.parents[1] / 'experiments' / 'k1192' / 'k1192_results.json').read_text())

    # Panel A: current manuscript's Sharpe decomposition (SPY and 50/50 only).
    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), gridspec_kw={'width_ratios': [1, 1.5]})

    # Left panel: Sharpe decomposition (SPY and 50/50)
    ax1 = axes[0]
    sharpe_assets = ['SPY', '50/50\nSPY/GLD']
    sharpe_total = [0.186, 0.117]
    sharpe_tsmom = [0.060, 0.046]
    sharpe_residual = [0.126, 0.071]

    x = np.arange(len(sharpe_assets))
    width = 0.5

    bars_residual = ax1.bar(x, sharpe_residual, width, label='VIX-level channel\n(TSMOM-independent)',
                            color='#2166ac', edgecolor='black', linewidth=0.5)
    bars_tsmom = ax1.bar(x, sharpe_tsmom, width, bottom=sharpe_residual,
                         label='TSMOM channel',
                         color='#b2182b', edgecolor='black', linewidth=0.5)

    # Add percentage labels
    for i, (res, tsm, tot) in enumerate(zip(sharpe_residual, sharpe_tsmom, sharpe_total)):
        ax1.text(i, res / 2, f'{res/tot*100:.0f}%', ha='center', va='center',
                fontweight='bold', fontsize=10, color='white')
        ax1.text(i, res + tsm / 2, f'{tsm/tot*100:.0f}%', ha='center', va='center',
                fontweight='bold', fontsize=10, color='white')
        ax1.text(i, tot + 0.005, f'+{tot:.3f}', ha='center', va='bottom', fontsize=9)

    ax1.set_ylabel(r'$\Delta$Sharpe (VT $-$ B&H)')
    ax1.set_title('(a) Sharpe Ratio Channel', fontweight='bold')
    ax1.set_xticks(x)
    ax1.set_xticklabels(sharpe_assets)
    ax1.set_ylim(0, 0.24)
    ax1.legend(loc='upper right', framealpha=0.9, edgecolor='gray')
    ax1.yaxis.set_major_formatter(mticker.FormatStrFormatter('%.3f'))
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)

    # Right panel: MDD decomposition (all 5 assets) from K1192 canonical.
    ax2 = axes[1]
    mdd_assets = ['SPY', '50/50\nSPY/GLD', 'DIA', 'QQQ', 'IWM']
    rows = []
    for asset in ['SPY', '50/50', 'DIA', 'QQQ', 'IWM']:
        point = k1192['assets'][asset]['bootstrap_results']['point_estimates']
        total = abs(point['bh_mdd_pct']) - abs(point['vt_mdd_pct'])
        retained = abs(point['bh_mdd_pct']) - abs(point['hedged_mdd_pct'])
        rows.append((total, retained, point['a_retention'] / 100.0))
    mdd_total = [r[0] for r in rows]
    mdd_retained = [r[1] for r in rows]
    mdd_tsmom = [t - r for t, r in zip(mdd_total, mdd_retained)]
    mdd_retention_pct = [r[2] for r in rows]

    x2 = np.arange(len(mdd_assets))
    width2 = 0.5

    bars2_retained = ax2.bar(x2, mdd_retained, width2,
                             label='VIX-level channel\n(TSMOM-independent)',
                             color='#2166ac', edgecolor='black', linewidth=0.5)
    bars2_tsmom = ax2.bar(x2, mdd_tsmom, width2, bottom=mdd_retained,
                          label='TSMOM channel',
                          color='#b2182b', edgecolor='black', linewidth=0.5)

    # Add retention percentage labels
    for i, (ret, tsm, tot, pct) in enumerate(zip(mdd_retained, mdd_tsmom, mdd_total, mdd_retention_pct)):
        ax2.text(i, ret / 2, f'{pct*100:.0f}%', ha='center', va='center',
                fontweight='bold', fontsize=10, color='white')
        if abs(tsm) > 0.75:
            label_y = ret + tsm / 2
            ax2.text(i, label_y, f'{(tot-ret)/tot*100:.0f}%', ha='center', va='center',
                    fontweight='bold', fontsize=9, color='white')
        ax2.text(i, tot + 0.3, f'{tot:.1f} pp', ha='center', va='bottom', fontsize=8)

    ax2.set_ylabel('MDD Protection (percentage points)')
    ax2.set_title('(b) Maximum Drawdown Channel', fontweight='bold')
    ax2.set_xticks(x2)
    ax2.set_xticklabels(mdd_assets)
    ax2.set_ylim(-2.5, 38)
    ax2.legend(loc='upper right', framealpha=0.9, edgecolor='gray')
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)

    fig.suptitle('', y=1.02)
    plt.tight_layout()
    plt.savefig(fig_dir / 'fig1_return_decomposition.pdf', format='pdf')
    plt.savefig(fig_dir / 'fig1_return_decomposition.png', format='png')
    plt.close()
    print("Figure 1 saved: fig1_return_decomposition.pdf")


# ====================================================================
# Figure 2: Cross-Asset VT — Sharpe Change vs MDD Improvement
# Data from Table 4 (13 international markets)
# ====================================================================

def figure2_cross_asset_scatter():
    """
    Scatter plot: X = Delta Sharpe from VT, Y = Delta MDD (pp improvement).
    Each point labeled with ETF ticker. Color-coded by developed/emerging.
    Shows insurance pricing: Sharpe goes down but MDD improves universally.
    """
    # Data directly from Table 4 in main.tex
    # Format: (ticker, label, delta_sharpe, delta_mdd_pp, is_developed)
    data = [
        # Developed markets
        ('EFA',  'EFA',    -0.053, 32.7, True),
        ('EWJ',  'EWJ',     0.004, 28.9, True),
        ('EWG',  'EWG',    -0.052, 33.9, True),
        ('EWU',  'EWU',    -0.068, 33.8, True),
        ('EWA',  'EWA',    -0.104, 33.6, True),
        ('EWC',  'EWC',    -0.050, 27.7, True),
        ('VGK',  'VGK',    -0.058, 33.6, True),
        # Emerging markets
        ('EEM',  'EEM',    -0.055, 33.6, False),
        ('FXI',  'FXI',    -0.024, 29.9, False),
        ('EWZ',  'EWZ',    -0.057, 13.2, False),
        ('INDA', 'INDA',   -0.059, 18.7, False),
        ('EWT',  'EWT',    -0.049, 30.1, False),
        ('MCHI', 'MCHI',    0.006, 23.0, False),
    ]

    fig, ax = plt.subplots(figsize=(8, 6))

    # Separate developed and emerging
    dev_x = [d[2] for d in data if d[4]]
    dev_y = [d[3] for d in data if d[4]]
    dev_labels = [d[1] for d in data if d[4]]

    em_x = [d[2] for d in data if not d[4]]
    em_y = [d[3] for d in data if not d[4]]
    em_labels = [d[1] for d in data if not d[4]]

    # Plot
    ax.scatter(dev_x, dev_y, s=100, c='#2166ac', marker='o', edgecolors='black',
               linewidth=0.8, zorder=5, label='Developed markets ($N=7$)')
    ax.scatter(em_x, em_y, s=100, c='#b2182b', marker='s', edgecolors='black',
               linewidth=0.8, zorder=5, label='Emerging markets ($N=6$)')

    # Label each point — with offset adjustments to avoid overlap
    offsets = {
        'EFA': (5, -10), 'EWJ': (5, 5), 'EWG': (5, 5), 'EWU': (-10, 8),
        'EWA': (5, -10), 'EWC': (5, -10), 'VGK': (-12, -12),
        'EEM': (-12, 8), 'FXI': (5, -10), 'EWZ': (5, 5),
        'INDA': (5, 5), 'EWT': (5, 5), 'MCHI': (5, -10),
    }

    for label, x_val, y_val in zip(dev_labels + em_labels, dev_x + em_x, dev_y + em_y):
        ox, oy = offsets.get(label, (5, 5))
        ax.annotate(label, (x_val, y_val), textcoords='offset points',
                   xytext=(ox, oy), fontsize=8, fontweight='bold',
                   color='#333333')

    # Add quadrant shading and labels
    ax.axvline(x=0, color='gray', linestyle='--', linewidth=0.6, alpha=0.5)
    ax.axhline(y=0, color='gray', linestyle='--', linewidth=0.6, alpha=0.5)

    # Shade the "insurance" quadrant (negative Sharpe change, positive MDD improvement)
    ax.axvspan(ax.get_xlim()[0] if ax.get_xlim()[0] < -0.12 else -0.12, 0,
               alpha=0.04, color='#2166ac')

    # Add average markers
    avg_sharpe = np.mean([d[2] for d in data])
    avg_mdd = np.mean([d[3] for d in data])
    ax.axvline(x=avg_sharpe, color='#666666', linestyle=':', linewidth=1.0, alpha=0.6)
    ax.axhline(y=avg_mdd, color='#666666', linestyle=':', linewidth=1.0, alpha=0.6)
    ax.annotate(f'Avg: $\\Delta$Sharpe = {avg_sharpe:.3f}',
               xy=(avg_sharpe, 12), fontsize=8, color='#666666', ha='center')
    ax.annotate(f'Avg: $\\Delta$MDD = {avg_mdd:.1f} pp',
               xy=(-0.11, avg_mdd + 0.5), fontsize=8, color='#666666', ha='left')

    # Quadrant annotation
    ax.text(-0.065, 36, 'Insurance quadrant:\nSharpe cost, MDD benefit',
            fontsize=8, fontstyle='italic', color='#2166ac', ha='center',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='white', edgecolor='#2166ac',
                     alpha=0.8))

    # Formatting
    ax.set_xlabel(r'$\Delta$Sharpe (VT $-$ B&H)', fontsize=11)
    ax.set_ylabel(r'$\Delta$MDD (percentage points improvement)', fontsize=11)
    ax.set_xlim(-0.12, 0.02)
    ax.set_ylim(10, 38)
    ax.legend(loc='lower left', framealpha=0.9, edgecolor='gray')
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.grid(True, alpha=0.2)

    # Add correlation annotation
    ax.text(0.97, 0.05,
            'VIX Sens. vs. $\\Delta$MDD:\n$r = -0.770$ ($p = 0.002$)\n$\\rho = -0.720$ ($p = 0.006$)',
            transform=ax.transAxes, fontsize=8, va='bottom', ha='right',
            bbox=dict(boxstyle='round,pad=0.4', facecolor='lightyellow',
                     edgecolor='#999999', alpha=0.9))

    plt.tight_layout()
    fig_dir = Path(__file__).resolve().parent
    plt.savefig(fig_dir / 'fig2_cross_asset_scatter.pdf', format='pdf')
    plt.savefig(fig_dir / 'fig2_cross_asset_scatter.png', format='png')
    plt.close()
    print("Figure 2 saved: fig2_cross_asset_scatter.pdf")


if __name__ == '__main__':
    figure1_return_decomposition()
    figure2_cross_asset_scatter()
    print("All figures generated successfully.")
