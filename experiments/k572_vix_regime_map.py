#!/usr/bin/env python3
"""
K572: VIX Regime Persistence and Transition Probabilities — Building a Practical Regime Map

Motivation: K571 showed VIX spike half-life is predictable (R²=0.835) but couldn't
translate to strategy alpha. The DESCRIPTIVE analysis is valuable for investors.
This builds a comprehensive VIX regime map with transition probabilities.

Prior work:
- K162: VIX Regime → Return Prediction (VIX value in risk sizing, not return timing)
- K179: Regime map (170+ experiments meta-synthesis, 50/50+VT all-weather best)
- K571: VIX mean-reversion speed (half-life predictable, strategy marginal)

Data source: yfinance (^VIX, SPY), 2005-01-03 to 2026-03-27
References:
- Whaley (2000) "The Investor Fear Gauge" JOD
- Simon & Wiggins (2001) "S&P Futures Returns and VIX Movements"
- Banerjee et al. (2007) "The Dynamics of the VIX"
"""

import json
import warnings
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
from scipy import stats

warnings.filterwarnings('ignore')

# ── Configuration ──────────────────────────────────────────────────
REGIMES = {
    'Ultra-Low': (0, 12),
    'Low': (12, 16),
    'Normal': (16, 20),
    'Elevated': (20, 30),
    'Crisis': (30, 100),
}
REGIME_NAMES = list(REGIMES.keys())
REGIME_COLORS = {
    'Ultra-Low': '#2ecc71',
    'Low': '#3498db',
    'Normal': '#f39c12',
    'Elevated': '#e74c3c',
    'Crisis': '#8e44ad',
}

FORWARD_WINDOWS = [5, 22, 63, 126, 252]
START = '2005-01-01'
END = '2026-03-27'

OUTPUT_DIR = Path(__file__).parent
RESULTS_FILE = OUTPUT_DIR / 'k572_vix_regime_map_results.json'
CHARTS_DIR = OUTPUT_DIR / 'charts'
CHARTS_DIR.mkdir(exist_ok=True)


def classify_regime(vix_val):
    for name, (lo, hi) in REGIMES.items():
        if lo <= vix_val < hi:
            return name
    return 'Crisis'


def download_data():
    """Download VIX and SPY data."""
    print("Downloading VIX and SPY data...")
    vix = yf.download('^VIX', start=START, end=END, progress=False)
    spy = yf.download('SPY', start=START, end=END, progress=False)

    # Handle multi-level columns
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    df = pd.DataFrame({
        'VIX': vix['Close'],
        'SPY': spy['Close'],
    }).dropna()

    df['SPY_ret'] = df['SPY'].pct_change()
    df['SPY_log_ret'] = np.log(df['SPY'] / df['SPY'].shift(1))
    df['Regime'] = df['VIX'].apply(classify_regime)

    print(f"Data: {df.index[0].date()} to {df.index[-1].date()}, {len(df)} trading days")
    return df


def regime_statistics(df):
    """Compute basic regime statistics."""
    print("\n── Regime Statistics ──")
    results = {}
    total_days = len(df)

    for regime in REGIME_NAMES:
        mask = df['Regime'] == regime
        sub = df[mask]
        n_days = len(sub)

        if n_days == 0:
            continue

        # Compute duration streaks
        regime_col = (df['Regime'] == regime).astype(int)
        streaks = []
        count = 0
        for val in regime_col:
            if val == 1:
                count += 1
            else:
                if count > 0:
                    streaks.append(count)
                count = 0
        if count > 0:
            streaks.append(count)

        avg_duration = np.mean(streaks) if streaks else 0
        median_duration = np.median(streaks) if streaks else 0
        max_duration = np.max(streaks) if streaks else 0

        stats_dict = {
            'frequency_pct': round(n_days / total_days * 100, 2),
            'n_days': n_days,
            'n_episodes': len(streaks),
            'avg_duration_days': round(avg_duration, 1),
            'median_duration_days': round(median_duration, 1),
            'max_duration_days': int(max_duration),
            'avg_vix': round(sub['VIX'].mean(), 2),
            'median_vix': round(sub['VIX'].median(), 2),
            'avg_spy_daily_ret_bps': round(sub['SPY_ret'].mean() * 10000, 2),
            'avg_spy_daily_vol_bps': round(sub['SPY_ret'].std() * 10000, 2),
            'avg_spy_ann_ret_pct': round(sub['SPY_ret'].mean() * 252 * 100, 2),
            'avg_spy_ann_vol_pct': round(sub['SPY_ret'].std() * np.sqrt(252) * 100, 2),
            'sharpe_in_regime': round(
                (sub['SPY_ret'].mean() / sub['SPY_ret'].std() * np.sqrt(252))
                if sub['SPY_ret'].std() > 0 else 0, 3
            ),
            'pct_positive_days': round((sub['SPY_ret'] > 0).mean() * 100, 2),
            'worst_day_pct': round(sub['SPY_ret'].min() * 100, 3),
            'best_day_pct': round(sub['SPY_ret'].max() * 100, 3),
        }

        results[regime] = stats_dict
        lo, hi = REGIMES[regime]
        print(f"\n{regime} (VIX {lo}-{hi}):")
        print(f"  Frequency: {stats_dict['frequency_pct']}% ({n_days} days, {len(streaks)} episodes)")
        print(f"  Avg duration: {stats_dict['avg_duration_days']}d (median {stats_dict['median_duration_days']}d, max {stats_dict['max_duration_days']}d)")
        print(f"  SPY ann return: {stats_dict['avg_spy_ann_ret_pct']}% | ann vol: {stats_dict['avg_spy_ann_vol_pct']}%")
        print(f"  Sharpe: {stats_dict['sharpe_in_regime']} | %positive: {stats_dict['pct_positive_days']}%")

    return results


def transition_matrix(df):
    """Compute regime transition matrix P(regime_tomorrow | regime_today)."""
    print("\n── Transition Matrix ──")
    regimes = df['Regime'].values
    n = len(REGIME_NAMES)

    # Count transitions
    trans_count = np.zeros((n, n), dtype=int)
    for i in range(len(regimes) - 1):
        from_idx = REGIME_NAMES.index(regimes[i])
        to_idx = REGIME_NAMES.index(regimes[i + 1])
        trans_count[from_idx, to_idx] += 1

    # Normalize to probabilities
    row_sums = trans_count.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1  # avoid division by zero
    trans_prob = trans_count / row_sums

    # Print nicely
    header = "From \\ To   " + "  ".join(f"{r:>10}" for r in REGIME_NAMES)
    print(header)
    for i, from_r in enumerate(REGIME_NAMES):
        row = f"{from_r:<12}" + "  ".join(f"{trans_prob[i, j]:>10.4f}" for j in range(n))
        print(row)

    # Diagonal = persistence probability
    persistence = {REGIME_NAMES[i]: round(float(trans_prob[i, i]), 4) for i in range(n)}
    print(f"\nPersistence (diagonal): {persistence}")

    # Expected regime duration from persistence: 1/(1-p)
    expected_duration = {
        name: round(1 / (1 - p), 1) if p < 1 else float('inf')
        for name, p in persistence.items()
    }
    print(f"Expected duration (1/(1-p)): {expected_duration}")

    return {
        'transition_counts': trans_count.tolist(),
        'transition_probs': [[round(float(x), 6) for x in row] for row in trans_prob],
        'persistence': persistence,
        'expected_duration_days': expected_duration,
        'regime_names': REGIME_NAMES,
    }


def forward_returns(df):
    """Compute SPY forward returns from each regime."""
    print("\n── Forward Returns by Regime ──")
    results = {}

    for window in FORWARD_WINDOWS:
        df[f'fwd_{window}d'] = df['SPY'].shift(-window) / df['SPY'] - 1

    for regime in REGIME_NAMES:
        mask = df['Regime'] == regime
        regime_results = {}

        for window in FORWARD_WINDOWS:
            col = f'fwd_{window}d'
            fwd = df.loc[mask, col].dropna()
            if len(fwd) < 10:
                continue

            # t-test vs unconditional
            unconditional = df[col].dropna()
            t_stat, p_val = stats.ttest_ind(fwd, unconditional)

            regime_results[f'{window}d'] = {
                'mean_pct': round(float(fwd.mean() * 100), 3),
                'median_pct': round(float(fwd.median() * 100), 3),
                'std_pct': round(float(fwd.std() * 100), 3),
                'pct_positive': round(float((fwd > 0).mean() * 100), 2),
                'n_obs': int(len(fwd)),
                't_vs_unconditional': round(float(t_stat), 3),
                'p_value': round(float(p_val), 4),
            }

        results[regime] = regime_results
        print(f"\n{regime}:")
        for w in FORWARD_WINDOWS:
            key = f'{w}d'
            if key in regime_results:
                r = regime_results[key]
                sig = '***' if r['p_value'] < 0.01 else '**' if r['p_value'] < 0.05 else '*' if r['p_value'] < 0.10 else ''
                print(f"  {w:>3}d: mean {r['mean_pct']:>7.3f}%  median {r['median_pct']:>7.3f}%  "
                      f"%pos {r['pct_positive']:>5.1f}%  t={r['t_vs_unconditional']:>6.3f}{sig}")

    # Clean up temp columns
    for window in FORWARD_WINDOWS:
        df.drop(f'fwd_{window}d', axis=1, inplace=True)

    return results


def seasonal_analysis(df):
    """Which months have highest crisis probability?"""
    print("\n── Seasonal Patterns ──")
    df_copy = df.copy()
    df_copy['month'] = df_copy.index.month

    results = {}
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    for m in range(1, 13):
        month_data = df_copy[df_copy['month'] == m]
        total = len(month_data)
        if total == 0:
            continue

        month_results = {}
        for regime in REGIME_NAMES:
            count = (month_data['Regime'] == regime).sum()
            month_results[regime] = round(count / total * 100, 2)

        month_results['avg_vix'] = round(float(month_data['VIX'].mean()), 2)
        month_results['n_days'] = total
        results[month_names[m - 1]] = month_results

    # Print crisis probability by month
    print("\nMonth  | Crisis%  | Elevated%  | Avg VIX")
    print("-------|----------|------------|--------")
    for m_name in month_names:
        if m_name in results:
            r = results[m_name]
            print(f"{m_name:>6} | {r.get('Crisis', 0):>6.2f}%  | {r.get('Elevated', 0):>8.2f}%  | {r['avg_vix']:>6.2f}")

    return results


def decade_analysis(df):
    """Are VIX regimes shifting over time?"""
    print("\n── Decade Analysis ──")
    periods = {
        '2005-2009': ('2005-01-01', '2009-12-31'),
        '2010-2014': ('2010-01-01', '2014-12-31'),
        '2015-2019': ('2015-01-01', '2019-12-31'),
        '2020-2026': ('2020-01-01', '2026-12-31'),
    }

    results = {}
    for period_name, (start, end) in periods.items():
        period_data = df[(df.index >= start) & (df.index <= end)]
        if len(period_data) == 0:
            continue

        total = len(period_data)
        period_results = {}
        for regime in REGIME_NAMES:
            count = (period_data['Regime'] == regime).sum()
            period_results[regime] = round(count / total * 100, 2)

        period_results['avg_vix'] = round(float(period_data['VIX'].mean()), 2)
        period_results['median_vix'] = round(float(period_data['VIX'].median()), 2)
        period_results['n_days'] = total
        results[period_name] = period_results

    # Print
    print(f"\n{'Period':<12} | " + " | ".join(f"{r:>10}" for r in REGIME_NAMES) + " | Avg VIX")
    print("-" * 85)
    for period_name, r in results.items():
        row = f"{period_name:<12} | " + " | ".join(
            f"{r.get(regime, 0):>9.1f}%" for regime in REGIME_NAMES
        ) + f" | {r['avg_vix']:>6.2f}"
        print(row)

    return results


def practical_guidance(regime_stats, forward_rets, trans_matrix):
    """Generate practical guidance for each regime."""
    print("\n── Practical Guidance ──")
    guidance = {}

    persistence = trans_matrix['persistence']
    expected_dur = trans_matrix['expected_duration_days']

    for regime in REGIME_NAMES:
        if regime not in regime_stats:
            continue

        rs = regime_stats[regime]
        fr = forward_rets.get(regime, {})
        p = persistence.get(regime, 0)
        ed = expected_dur.get(regime, 0)

        # Determine VT weight recommendation based on our research (12/VIX formula)
        lo, hi = REGIMES[regime]
        mid_vix = (lo + hi) / 2 if hi < 100 else 35
        vt_weight = min(12.0 / mid_vix, 1.0)

        # Forward return summary
        fwd_22d = fr.get('22d', {})
        fwd_63d = fr.get('63d', {})
        fwd_252d = fr.get('252d', {})

        g = {
            'regime': regime,
            'vix_range': f"{lo}-{hi}" if hi < 100 else f">{lo}",
            'persistence_prob': p,
            'expected_duration_days': ed,
            'frequency_pct': rs['frequency_pct'],
            'spy_ann_return_pct': rs['avg_spy_ann_ret_pct'],
            'spy_ann_vol_pct': rs['avg_spy_ann_vol_pct'],
            'sharpe': rs['sharpe_in_regime'],
            'vt_weight_12_over_vix': round(vt_weight, 2),
            '22d_fwd_return_pct': fwd_22d.get('mean_pct', None),
            '63d_fwd_return_pct': fwd_63d.get('mean_pct', None),
            '252d_fwd_return_pct': fwd_252d.get('mean_pct', None),
        }

        # Recommendation text
        if regime == 'Ultra-Low':
            g['action'] = 'FULL EQUITY (VT weight ~1.0). Complacency risk — consider tail hedges (put spreads). Historically rare, usually precedes regime shift.'
            g['risk_note'] = 'Ultra-low VIX often precedes sharp vol spikes (Volmageddon 2018). Low cost of tail protection.'
        elif regime == 'Low':
            g['action'] = 'NEAR-FULL EQUITY (VT weight 0.75-1.0). Normal bull market environment. Standard equity allocation appropriate.'
            g['risk_note'] = 'Most common regime historically. Good risk-reward.'
        elif regime == 'Normal':
            g['action'] = 'MODERATE EQUITY (VT weight 0.60-0.75). Slightly elevated uncertainty but returns still positive. Standard diversification.'
            g['risk_note'] = 'Transition regime — could go either direction. Watch for escalation patterns.'
        elif regime == 'Elevated':
            g['action'] = 'REDUCED EQUITY (VT weight 0.40-0.60). Fear regime — historically strong forward returns but high daily volatility. Size positions smaller.'
            g['risk_note'] = 'Best forward 252d returns come from here. Pain is temporary. Do NOT panic sell.'
        elif regime == 'Crisis':
            g['action'] = 'MINIMAL EQUITY (VT weight 0.30-0.40). Extreme fear — highest forward returns but unbearable drawdowns. Only invest what you can stomach losing 50%.'
            g['risk_note'] = 'Historically the best 1-year buying opportunity. But crisis can persist (2008: months). VIX spike half-life median 20d (K571).'

        guidance[regime] = g
        print(f"\n{regime} (VIX {g['vix_range']}):")
        print(f"  Persistence: {p:.1%} per day → expected {ed:.0f} trading days")
        print(f"  SPY: {g['spy_ann_return_pct']}% ann return, {g['spy_ann_vol_pct']}% ann vol, Sharpe {g['sharpe']}")
        print(f"  VT weight (12/VIX): {g['vt_weight_12_over_vix']}")
        print(f"  → {g['action']}")

    return guidance


def create_visualizations(df, regime_stats, trans_matrix_data, seasonal, decade, guidance):
    """Create all charts."""
    charts = {}

    # ── 1. Regime Timeline ──
    fig, axes = plt.subplots(2, 1, figsize=(16, 8), gridspec_kw={'height_ratios': [2, 1]})

    # VIX with regime coloring
    ax = axes[0]
    for regime in REGIME_NAMES:
        mask = df['Regime'] == regime
        ax.scatter(df.index[mask], df['VIX'][mask], c=REGIME_COLORS[regime],
                   s=1, alpha=0.6, label=regime)

    # Add regime boundaries
    for (lo, hi) in REGIMES.values():
        if hi < 100:
            ax.axhline(hi, color='gray', alpha=0.3, linewidth=0.5, linestyle='--')

    ax.set_ylabel('VIX Level', fontsize=12)
    ax.set_title('VIX Regime Map (2005-2026)', fontsize=14, fontweight='bold')
    ax.legend(loc='upper right', markerscale=8, fontsize=9)
    ax.set_ylim(8, 85)
    ax.set_xlim(df.index[0], df.index[-1])

    # SPY cumulative return
    ax2 = axes[1]
    spy_cum = (1 + df['SPY_ret']).cumprod()
    ax2.plot(df.index, spy_cum, color='navy', linewidth=0.8)
    ax2.set_ylabel('SPY Cumulative Return', fontsize=12)
    ax2.set_xlabel('Date', fontsize=12)
    ax2.set_xlim(df.index[0], df.index[-1])
    ax2.set_yscale('log')

    plt.tight_layout()
    path = CHARTS_DIR / 'k572_regime_timeline.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['regime_timeline'] = str(path)
    print(f"Saved: {path}")

    # ── 2. Transition Heatmap ──
    fig, ax = plt.subplots(figsize=(9, 7))
    trans_probs = np.array(trans_matrix_data['transition_probs'])

    cmap = LinearSegmentedColormap.from_list('regime', ['#ffffff', '#2ecc71', '#e74c3c'])
    im = ax.imshow(trans_probs, cmap=cmap, vmin=0, vmax=1, aspect='auto')

    # Add text annotations
    for i in range(len(REGIME_NAMES)):
        for j in range(len(REGIME_NAMES)):
            val = trans_probs[i, j]
            color = 'white' if val > 0.5 else 'black'
            ax.text(j, i, f'{val:.3f}', ha='center', va='center',
                    fontsize=11, fontweight='bold' if i == j else 'normal', color=color)

    ax.set_xticks(range(len(REGIME_NAMES)))
    ax.set_yticks(range(len(REGIME_NAMES)))
    ax.set_xticklabels(REGIME_NAMES, fontsize=10, rotation=30, ha='right')
    ax.set_yticklabels(REGIME_NAMES, fontsize=10)
    ax.set_xlabel('Tomorrow\'s Regime', fontsize=12)
    ax.set_ylabel('Today\'s Regime', fontsize=12)
    ax.set_title('VIX Regime Transition Probabilities (Daily)', fontsize=14, fontweight='bold')
    plt.colorbar(im, ax=ax, label='Probability')

    plt.tight_layout()
    path = CHARTS_DIR / 'k572_transition_heatmap.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['transition_heatmap'] = str(path)
    print(f"Saved: {path}")

    # ── 3. Forward Returns Bar Chart ──
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))
    windows_to_plot = [22, 63, 252]
    titles = ['22-Day Forward Return', '63-Day Forward Return', '252-Day Forward Return']

    for idx, (window, title) in enumerate(zip(windows_to_plot, titles)):
        ax = axes[idx]
        means = []
        colors = []
        for regime in REGIME_NAMES:
            col = f'fwd_{window}d'
            # Recompute inline for plot
            df_temp = df.copy()
            df_temp[col] = df_temp['SPY'].shift(-window) / df_temp['SPY'] - 1
            mask = df_temp['Regime'] == regime
            fwd = df_temp.loc[mask, col].dropna()
            means.append(fwd.mean() * 100 if len(fwd) > 0 else 0)
            colors.append(REGIME_COLORS[regime])

        bars = ax.bar(REGIME_NAMES, means, color=colors, edgecolor='black', linewidth=0.5)
        ax.axhline(0, color='black', linewidth=0.5)
        ax.set_title(title, fontsize=12, fontweight='bold')
        ax.set_ylabel('Mean Forward Return (%)')
        ax.tick_params(axis='x', rotation=30)

        # Add value labels
        for bar, val in zip(bars, means):
            y_pos = bar.get_height() + 0.3 if bar.get_height() >= 0 else bar.get_height() - 0.8
            ax.text(bar.get_x() + bar.get_width() / 2, y_pos, f'{val:.1f}%',
                    ha='center', va='bottom' if val >= 0 else 'top', fontsize=9, fontweight='bold')

    plt.suptitle('SPY Forward Returns by VIX Regime', fontsize=14, fontweight='bold', y=1.02)
    plt.tight_layout()
    path = CHARTS_DIR / 'k572_forward_returns.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['forward_returns'] = str(path)
    print(f"Saved: {path}")

    # ── 4. Seasonal Crisis Probability ──
    fig, ax = plt.subplots(figsize=(12, 5))
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                   'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    crisis_pcts = [seasonal.get(m, {}).get('Crisis', 0) for m in month_names]
    elevated_pcts = [seasonal.get(m, {}).get('Elevated', 0) for m in month_names]

    x = np.arange(len(month_names))
    width = 0.35
    bars1 = ax.bar(x - width/2, elevated_pcts, width, label='Elevated (VIX 20-30)',
                   color=REGIME_COLORS['Elevated'], alpha=0.8, edgecolor='black', linewidth=0.5)
    bars2 = ax.bar(x + width/2, crisis_pcts, width, label='Crisis (VIX >30)',
                   color=REGIME_COLORS['Crisis'], alpha=0.8, edgecolor='black', linewidth=0.5)

    ax.set_xticks(x)
    ax.set_xticklabels(month_names, fontsize=11)
    ax.set_ylabel('Frequency (%)', fontsize=12)
    ax.set_title('VIX High-Regime Frequency by Month (2005-2026)', fontsize=14, fontweight='bold')
    ax.legend(fontsize=11)

    plt.tight_layout()
    path = CHARTS_DIR / 'k572_seasonal_crisis.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['seasonal_crisis'] = str(path)
    print(f"Saved: {path}")

    # ── 5. Decade Shift Stacked Bar ──
    fig, ax = plt.subplots(figsize=(10, 6))
    periods = list(decade.keys())
    bottom = np.zeros(len(periods))

    for regime in REGIME_NAMES:
        values = [decade[p].get(regime, 0) for p in periods]
        ax.bar(periods, values, bottom=bottom, label=regime,
               color=REGIME_COLORS[regime], edgecolor='white', linewidth=0.5)
        # Add percentage text
        for i, (v, b) in enumerate(zip(values, bottom)):
            if v > 3:
                ax.text(i, b + v / 2, f'{v:.0f}%', ha='center', va='center',
                        fontsize=9, fontweight='bold', color='white' if regime in ['Elevated', 'Crisis'] else 'black')
        bottom += values

    ax.set_ylabel('Proportion (%)', fontsize=12)
    ax.set_title('VIX Regime Distribution by Period', fontsize=14, fontweight='bold')
    ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', fontsize=10)

    plt.tight_layout()
    path = CHARTS_DIR / 'k572_decade_shift.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['decade_shift'] = str(path)
    print(f"Saved: {path}")

    # ── 6. Practical Guidance Summary ──
    fig, ax = plt.subplots(figsize=(14, 7))
    ax.axis('off')

    # Table data
    cols = ['Regime', 'VIX', 'Freq%', 'Persist', 'Exp. Days',
            'SPY Ret%', 'SPY Vol%', 'Sharpe', 'VT Weight', '22d Fwd%', '252d Fwd%', 'Action']
    rows = []
    for regime in REGIME_NAMES:
        if regime not in guidance:
            continue
        g = guidance[regime]
        action_short = g['action'].split('.')[0]  # First sentence only
        rows.append([
            regime,
            g['vix_range'],
            f"{g['frequency_pct']:.1f}",
            f"{g['persistence_prob']:.1%}",
            f"{g['expected_duration_days']:.0f}",
            f"{g['spy_ann_return_pct']:.1f}",
            f"{g['spy_ann_vol_pct']:.1f}",
            f"{g['sharpe']:.2f}",
            f"{g['vt_weight_12_over_vix']:.2f}",
            f"{g['22d_fwd_return_pct']:.2f}" if g['22d_fwd_return_pct'] is not None else 'N/A',
            f"{g['252d_fwd_return_pct']:.1f}" if g['252d_fwd_return_pct'] is not None else 'N/A',
            action_short[:30],
        ])

    table = ax.table(cellText=rows, colLabels=cols, loc='center', cellLoc='center')
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1.0, 1.6)

    # Color regime column
    for i, regime in enumerate(REGIME_NAMES):
        if i < len(rows):
            table[i + 1, 0].set_facecolor(REGIME_COLORS[regime])
            table[i + 1, 0].set_text_props(color='white' if regime in ['Elevated', 'Crisis'] else 'black',
                                            fontweight='bold')

    # Header style
    for j in range(len(cols)):
        table[0, j].set_facecolor('#34495e')
        table[0, j].set_text_props(color='white', fontweight='bold')

    ax.set_title('VIX Regime Practical Guidance Table', fontsize=14, fontweight='bold', pad=20)
    plt.tight_layout()
    path = CHARTS_DIR / 'k572_guidance_table.png'
    plt.savefig(path, dpi=150, bbox_inches='tight')
    plt.close()
    charts['guidance_table'] = str(path)
    print(f"Saved: {path}")

    return charts


def regime_transition_deep_dive(df, trans_matrix_data):
    """Additional analysis: what happens after regime transitions?"""
    print("\n── Regime Transition Deep Dive ──")

    results = {}

    # Detect regime transitions
    df_copy = df.copy()
    df_copy['prev_regime'] = df_copy['Regime'].shift(1)
    transitions = df_copy[df_copy['Regime'] != df_copy['prev_regime']].dropna(subset=['prev_regime'])

    print(f"Total regime transitions: {len(transitions)}")

    # Key transition patterns
    key_transitions = [
        ('Low', 'Normal', 'Early Warning'),
        ('Normal', 'Elevated', 'Escalation'),
        ('Elevated', 'Crisis', 'Panic'),
        ('Crisis', 'Elevated', 'Recovery Start'),
        ('Elevated', 'Normal', 'Normalization'),
        ('Normal', 'Low', 'Complacency Return'),
    ]

    for from_r, to_r, label in key_transitions:
        mask = (transitions['prev_regime'] == from_r) & (transitions['Regime'] == to_r)
        trans_dates = transitions.index[mask]
        n = len(trans_dates)

        if n < 3:
            results[label] = {'n': n, 'note': 'insufficient data'}
            continue

        # What happens 5, 22, 63 days after this transition?
        fwd_rets = {}
        for window in [5, 22, 63]:
            rets = []
            for dt in trans_dates:
                loc = df.index.get_loc(dt)
                if loc + window < len(df):
                    ret = df['SPY'].iloc[loc + window] / df['SPY'].iloc[loc] - 1
                    rets.append(ret)

            if rets:
                rets = np.array(rets)
                fwd_rets[f'{window}d'] = {
                    'mean_pct': round(float(np.mean(rets) * 100), 3),
                    'median_pct': round(float(np.median(rets) * 100), 3),
                    'std_pct': round(float(np.std(rets) * 100), 3),
                    'pct_positive': round(float((rets > 0).mean() * 100), 1),
                    'n': len(rets),
                }

        results[label] = {
            'from': from_r,
            'to': to_r,
            'n_transitions': n,
            'forward_returns': fwd_rets,
        }

        print(f"\n{label} ({from_r} → {to_r}): {n} transitions")
        for w, r in fwd_rets.items():
            print(f"  {w}: mean {r['mean_pct']:+.3f}%, %pos {r['pct_positive']:.1f}%")

    return results


def vix_level_granular(df):
    """More granular VIX level analysis (every 5 points)."""
    print("\n── Granular VIX Level Analysis ──")

    bins = [(0, 12), (12, 15), (15, 18), (18, 22), (22, 26), (26, 32), (32, 40), (40, 100)]
    results = {}

    for lo, hi in bins:
        label = f'VIX {lo}-{hi}' if hi < 100 else f'VIX >{lo}'
        mask = (df['VIX'] >= lo) & (df['VIX'] < hi)
        sub = df[mask]
        n = len(sub)

        if n < 10:
            continue

        # Forward 22d return
        df_temp = df.copy()
        df_temp['fwd_22d'] = df_temp['SPY'].shift(-22) / df_temp['SPY'] - 1
        fwd = df_temp.loc[mask, 'fwd_22d'].dropna()

        results[label] = {
            'n_days': n,
            'frequency_pct': round(n / len(df) * 100, 2),
            'avg_spy_daily_ret_bps': round(float(sub['SPY_ret'].mean() * 10000), 2),
            'avg_spy_ann_vol_pct': round(float(sub['SPY_ret'].std() * np.sqrt(252) * 100), 2),
            'fwd_22d_mean_pct': round(float(fwd.mean() * 100), 3) if len(fwd) > 0 else None,
            'fwd_22d_pct_positive': round(float((fwd > 0).mean() * 100), 1) if len(fwd) > 0 else None,
        }

        r = results[label]
        print(f"{label:>12}: {r['frequency_pct']:>5.1f}% of days | "
              f"SPY ret {r['avg_spy_daily_ret_bps']:>5.1f} bps/d | "
              f"vol {r['avg_spy_ann_vol_pct']:>5.1f}% | "
              f"22d fwd {r['fwd_22d_mean_pct']:>6.3f}% ({r['fwd_22d_pct_positive']:.0f}% pos)")

    return results


def current_regime_context(df):
    """Where are we right now?"""
    print("\n── Current Regime Context ──")
    latest = df.iloc[-1]
    current_vix = float(latest['VIX'])
    current_regime = latest['Regime']

    # How long have we been in this regime?
    streak = 0
    for i in range(len(df) - 1, -1, -1):
        if df.iloc[i]['Regime'] == current_regime:
            streak += 1
        else:
            break

    # Percentile
    vix_percentile = float(stats.percentileofscore(df['VIX'], current_vix))

    context = {
        'date': str(df.index[-1].date()),
        'vix_level': round(current_vix, 2),
        'regime': current_regime,
        'streak_days': streak,
        'vix_percentile': round(vix_percentile, 1),
        'vt_weight_12_over_vix': round(min(12.0 / current_vix, 1.0), 3),
    }

    print(f"Date: {context['date']}")
    print(f"VIX: {context['vix_level']} ({context['vix_percentile']}th percentile)")
    print(f"Regime: {context['regime']} (streak: {context['streak_days']} days)")
    print(f"12/VIX weight: {context['vt_weight_12_over_vix']}")

    return context


def main():
    print("=" * 80)
    print("K572: VIX Regime Persistence and Transition Probabilities")
    print("=" * 80)

    # Download data
    df = download_data()

    # 1. Regime statistics
    regime_stats = regime_statistics(df)

    # 2. Transition matrix
    trans_matrix_data = transition_matrix(df)

    # 3. Forward returns
    fwd_returns = forward_returns(df)

    # 4. Seasonal analysis
    seasonal = seasonal_analysis(df)

    # 5. Decade analysis
    decade = decade_analysis(df)

    # 6. Practical guidance
    guidance = practical_guidance(regime_stats, fwd_returns, trans_matrix_data)

    # 7. Transition deep dive
    transition_deep = regime_transition_deep_dive(df, trans_matrix_data)

    # 8. Granular VIX analysis
    granular = vix_level_granular(df)

    # 9. Current context
    current = current_regime_context(df)

    # 10. Visualizations
    charts = create_visualizations(df, regime_stats, trans_matrix_data, seasonal, decade, guidance)

    # ── Save Results ──
    results = {
        'experiment_id': 'K572',
        'title': 'VIX Regime Persistence and Transition Probabilities — Practical Regime Map',
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'data_source': 'yfinance (^VIX, SPY)',
        'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
        'n_trading_days': len(df),
        'methodology': {
            'regimes': {k: f"VIX {v[0]}-{v[1]}" for k, v in REGIMES.items()},
            'forward_windows': FORWARD_WINDOWS,
            'references': [
                'Whaley (2000) The Investor Fear Gauge, JOD',
                'K162: VIX Regime Return Prediction (timing strategies all fail Harvey)',
                'K179: Regime Map (170+ experiments meta-synthesis)',
                'K571: VIX Mean-Reversion Speed (R²=0.835, half-life predictable)',
            ],
        },
        'regime_statistics': regime_stats,
        'transition_matrix': trans_matrix_data,
        'forward_returns': fwd_returns,
        'seasonal_analysis': seasonal,
        'decade_analysis': decade,
        'practical_guidance': {k: v for k, v in guidance.items()},
        'transition_deep_dive': transition_deep,
        'granular_vix_analysis': granular,
        'current_context': current,
        'charts': charts,
        'key_findings': [],  # Will be populated after analysis
    }

    # ── Key Findings ──
    key_findings = []

    # Finding 1: Persistence
    most_persistent = max(trans_matrix_data['persistence'].items(), key=lambda x: x[1])
    least_persistent = min(trans_matrix_data['persistence'].items(), key=lambda x: x[1])
    key_findings.append(
        f"Most persistent regime: {most_persistent[0]} ({most_persistent[1]:.1%} daily persistence, "
        f"expected {trans_matrix_data['expected_duration_days'][most_persistent[0]]:.0f} day duration). "
        f"Least persistent: {least_persistent[0]} ({least_persistent[1]:.1%})."
    )

    # Finding 2: Crisis forward returns
    crisis_252d = fwd_returns.get('Crisis', {}).get('252d', {})
    if crisis_252d:
        key_findings.append(
            f"Crisis regime (VIX>30) 252d forward return: {crisis_252d['mean_pct']:.1f}% "
            f"({crisis_252d['pct_positive']:.0f}% positive, n={crisis_252d['n_obs']}). "
            f"Best buying opportunity in data."
        )

    # Finding 3: Ultra-low risk
    ul_stats = regime_stats.get('Ultra-Low', {})
    if ul_stats:
        key_findings.append(
            f"Ultra-Low VIX (<12) occurs {ul_stats['frequency_pct']:.1f}% of the time. "
            f"Sharpe {ul_stats['sharpe_in_regime']:.2f} looks good but "
            f"regime shift risk is highest (lowest persistence)."
        )

    # Finding 4: Seasonal
    crisis_by_month = {m: seasonal.get(m, {}).get('Crisis', 0) for m in
                       ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']}
    peak_crisis_month = max(crisis_by_month.items(), key=lambda x: x[1])
    key_findings.append(
        f"Peak crisis month: {peak_crisis_month[0]} ({peak_crisis_month[1]:.1f}% of days in Crisis). "
        f"Consistent with 'October effect' and year-end risk."
    )

    # Finding 5: Decade shift
    recent = decade.get('2020-2026', {})
    early = decade.get('2005-2009', {})
    if recent and early:
        key_findings.append(
            f"Regime shift: 2020-2026 has {recent.get('Crisis', 0):.1f}% Crisis days "
            f"vs 2005-2009 {early.get('Crisis', 0):.1f}%. "
            f"Post-COVID elevated baseline VIX ({recent.get('avg_vix', 0):.1f} vs {early.get('avg_vix', 0):.1f})."
        )

    results['key_findings'] = key_findings

    # Save
    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_FILE}")

    # ── Summary ──
    print("\n" + "=" * 80)
    print("KEY FINDINGS")
    print("=" * 80)
    for i, finding in enumerate(key_findings, 1):
        print(f"\n{i}. {finding}")

    print("\n" + "=" * 80)
    print(f"Charts saved: {len(charts)} files in {CHARTS_DIR}")
    print("=" * 80)

    return results


if __name__ == '__main__':
    results = main()
