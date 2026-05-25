"""
K1401: GDP Q1 Second Estimate Event Study
BEA 每年 5 月底發布第一季 GDP 第二估，分析 VIX/SPY 在事件窗口 [-5,+5] 的行為。

Hypotheses:
  H1: Pre-event VIX elevated (T-5 vs T-1, paired t-test on raw VIX levels)
  H2: VIX drops post-announcement (T0 vs T+1, paired t-test on raw VIX levels)
  H3: Asymmetric vol response: upward vs downward GDP revisions (Welch t-test)

Note: Profile chart uses VIX(t)/VIX(T0) normalization for visual shape;
H1/H2 tests use raw VIX levels — complementary perspectives on the same event.

Bonferroni correction: k=3 tests, alpha_adj = 0.05/3 = 0.0167
Seed: 42
No lookahead: pure historical event study (realized prices only)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from scipy import stats
import json
import warnings
from pathlib import Path

warnings.filterwarnings('ignore')
np.random.seed(42)

EXPERIMENT_DIR = Path(__file__).parent
RESULTS_FILE = EXPERIMENT_DIR / "k1401_results.json"
CHART_FILE = EXPERIMENT_DIR / "k1401_event_study.png"

# BEA Q1 GDP Second Estimate release dates (hard-coded from BEA release calendar)
# Source: BEA National Income and Product Accounts release schedule
# Each entry: (year, release_date, first_estimate_pct, second_estimate_pct)
# Growth rates are QoQ annualized percent change
BEA_RELEASE_DATA = [
    # year,  release_date,   first_est,  second_est
    (2001, "2001-05-25",     1.3,         1.3),   # Q1 2001
    (2002, "2002-05-30",     5.6,         6.1),   # Q1 2002
    (2003, "2003-05-29",     1.6,         1.4),   # Q1 2003
    (2004, "2004-05-27",     4.2,         3.9),   # Q1 2004
    (2005, "2005-05-26",     3.5,         3.8),   # Q1 2005
    (2006, "2006-05-25",     4.8,         5.3),   # Q1 2006
    (2007, "2007-05-30",     1.3,         0.6),   # Q1 2007
    (2008, "2008-05-29",     0.9,         1.0),   # Q1 2008
    (2009, "2009-05-28",    -6.1,        -5.7),   # Q1 2009 (GFC)
    (2010, "2010-05-27",     2.7,         3.0),   # Q1 2010
    (2011, "2011-05-26",     1.8,         1.9),   # Q1 2011
    (2012, "2012-05-31",     2.2,         1.9),   # Q1 2012
    (2013, "2013-05-30",     2.4,         2.4),   # Q1 2013
    (2014, "2014-05-29",    -1.0,        -1.0),   # Q1 2014
    (2015, "2015-05-29",     0.2,         0.7),   # Q1 2015
    (2016, "2016-05-27",     0.5,         0.8),   # Q1 2016
    (2017, "2017-05-26",     1.2,         1.2),   # Q1 2017
    (2018, "2018-05-30",     2.3,         2.2),   # Q1 2018
    (2019, "2019-05-30",     3.2,         3.1),   # Q1 2019
    (2020, "2020-05-28",    -4.8,        -5.0),   # Q1 2020 (COVID)
    (2021, "2021-05-27",     6.4,         6.4),   # Q1 2021
    (2022, "2022-05-26",    -1.4,        -1.5),   # Q1 2022
    (2023, "2023-05-25",     1.3,         1.3),   # Q1 2023
    (2024, "2024-05-30",     1.6,         1.3),   # Q1 2024
    (2025, "2025-05-29",     2.4,         2.0),   # Q1 2025 (preliminary estimate used)
]

EVENT_WINDOW = 5  # trading days before and after


def load_market_data():
    """Download SPY and VIX daily data 2000-2026."""
    print("Downloading market data...")
    spy = yf.download("SPY", start="2000-01-01", end="2026-05-25",
                      auto_adjust=True, progress=False)
    vix = yf.download("^VIX", start="2000-01-01", end="2026-05-25",
                      auto_adjust=True, progress=False)

    spy = spy['Close'].squeeze()
    vix = vix['Close'].squeeze()

    spy.name = 'spy'
    vix.name = 'vix'

    df = pd.DataFrame({'spy': spy, 'vix': vix}).dropna()
    df['spy_ret'] = df['spy'].pct_change()
    print(f"Market data: {len(df)} trading days, {df.index[0].date()} to {df.index[-1].date()}")
    return df


def get_trading_date(df, target_date_str, offset=0):
    """Return the trading date at target_date + offset trading days."""
    target = pd.Timestamp(target_date_str)
    # Find nearest trading day on or after target
    mask = df.index >= target
    if not mask.any():
        return None
    idx = df.index[mask][0]
    pos = df.index.get_loc(idx)
    new_pos = pos + offset
    if new_pos < 0 or new_pos >= len(df.index):
        return None
    return df.index[new_pos]


def build_event_windows(df):
    """Build event windows for all BEA releases."""
    events = []
    for year, release_date, first_est, second_est in BEA_RELEASE_DATA:
        revision = second_est - first_est
        direction = "up" if revision > 0 else ("down" if revision < 0 else "flat")

        # Get T0 (announcement day)
        t0 = get_trading_date(df, release_date, offset=0)
        if t0 is None:
            print(f"  Skip {year}: no trading date for {release_date}")
            continue

        # Build window [-EVENT_WINDOW, +EVENT_WINDOW]
        window = {}
        valid = True
        for day_offset in range(-EVENT_WINDOW, EVENT_WINDOW + 1):
            td = get_trading_date(df, release_date, offset=day_offset)
            if td is None:
                valid = False
                break
            window[day_offset] = {
                'date': td.strftime('%Y-%m-%d'),
                'vix': float(df.loc[td, 'vix']),
                'spy': float(df.loc[td, 'spy']),
                'spy_ret': float(df.loc[td, 'spy_ret']) if not pd.isna(df.loc[td, 'spy_ret']) else None,
            }

        if valid and len(window) == 2 * EVENT_WINDOW + 1:
            events.append({
                'year': year,
                'release_date': release_date,
                'first_estimate': first_est,
                'second_estimate': second_est,
                'revision': revision,
                'direction': direction,
                'window': window,
            })

    print(f"Valid event windows: {len(events)} out of {len(BEA_RELEASE_DATA)}")
    return events


def compute_vix_profiles(events):
    """Compute mean VIX by relative day."""
    profiles = {d: [] for d in range(-EVENT_WINDOW, EVENT_WINDOW + 1)}
    for ev in events:
        t0_vix = ev['window'][0]['vix']
        for d, data in ev['window'].items():
            profiles[d].append(data['vix'] / t0_vix)  # normalize to T0=1

    mean_profile = {d: np.mean(v) for d, v in profiles.items()}
    se_profile = {d: np.std(v, ddof=1) / np.sqrt(len(v)) for d, v in profiles.items()}
    return mean_profile, se_profile, profiles


def test_h1_pre_event_elevation(events):
    """H1: VIX elevated pre-event (T-5 vs T-1, paired t-test)."""
    vix_t5 = [ev['window'][-5]['vix'] for ev in events]
    vix_t1 = [ev['window'][-1]['vix'] for ev in events]

    t_stat, p_val = stats.ttest_rel(vix_t5, vix_t1, alternative='less')
    n = len(events)
    mean_diff = np.mean(np.array(vix_t1) - np.array(vix_t5))
    return {
        'hypothesis': 'H1: VIX(T-5) < VIX(T-1) — pre-event vol elevation',
        'test': 'paired t-test (two-sample, one-sided: T-5 < T-1)',
        'n': n,
        'mean_vix_t5': float(np.mean(vix_t5)),
        'mean_vix_t1': float(np.mean(vix_t1)),
        'mean_diff_t1_minus_t5': float(mean_diff),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'alpha_bonferroni': 0.0167,
        'significant': bool(p_val < 0.0167),
    }


def test_h2_post_drop(events):
    """H2: VIX drops day after announcement (T0 vs T+1, paired t-test)."""
    vix_t0 = [ev['window'][0]['vix'] for ev in events]
    vix_tp1 = [ev['window'][1]['vix'] for ev in events]

    # H2: VIX(T0) > VIX(T+1) → one-sided: T0 > T+1 → alternative='greater'
    t_stat, p_val = stats.ttest_rel(vix_t0, vix_tp1, alternative='greater')
    n = len(events)
    return {
        'hypothesis': 'H2: VIX(T0) > VIX(T+1) — post-announcement vol drop',
        'test': 'paired t-test (one-sided: T0 > T+1)',
        'n': n,
        'mean_vix_t0': float(np.mean(vix_t0)),
        'mean_vix_tp1': float(np.mean(vix_tp1)),
        'mean_diff_t0_minus_tp1': float(np.mean(np.array(vix_t0) - np.array(vix_tp1))),
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'alpha_bonferroni': 0.0167,
        'significant': bool(p_val < 0.0167),
    }


def test_h3_asymmetry(events):
    """H3: VIX response asymmetric by revision direction (independent t-test)."""
    up_events = [ev for ev in events if ev['direction'] == 'up']
    down_events = [ev for ev in events if ev['direction'] == 'down']

    # VIX change T0 vs T-1
    def vix_change(ev_list):
        return [(ev['window'][0]['vix'] - ev['window'][-1]['vix']) / ev['window'][-1]['vix']
                for ev in ev_list]

    up_chg = vix_change(up_events)
    down_chg = vix_change(down_events)

    t_stat, p_val = stats.ttest_ind(up_chg, down_chg, alternative='two-sided', equal_var=False)
    return {
        'hypothesis': 'H3: Asymmetric VIX response to upward vs downward GDP revision',
        'test': 'Welch independent t-test (two-sided, equal_var=False)',
        'n_up': len(up_events),
        'n_down': len(down_events),
        'mean_vix_change_up': float(np.mean(up_chg)) if up_chg else None,
        'mean_vix_change_down': float(np.mean(down_chg)) if down_chg else None,
        't_stat': float(t_stat),
        'p_value': float(p_val),
        'alpha_bonferroni': 0.0167,
        'significant': bool(p_val < 0.0167),
    }


def compute_spy_abnormal_returns(events):
    """Compute average SPY return by relative day."""
    ret_by_day = {d: [] for d in range(-EVENT_WINDOW, EVENT_WINDOW + 1)}
    for ev in events:
        for d, data in ev['window'].items():
            if data['spy_ret'] is not None:
                ret_by_day[d].append(data['spy_ret'])
    mean_ret = {d: float(np.mean(v)) * 100 for d, v in ret_by_day.items() if v}
    return mean_ret


def make_chart(events, mean_vix_profile, se_vix_profile, mean_spy_ret, test_results):
    """Create 4-panel event study chart."""
    days = list(range(-EVENT_WINDOW, EVENT_WINDOW + 1))
    up_events = [ev for ev in events if ev['direction'] == 'up']
    down_events = [ev for ev in events if ev['direction'] == 'down']

    def avg_vix(ev_list):
        by_day = {d: [] for d in days}
        for ev in ev_list:
            for d, data in ev['window'].items():
                by_day[d].append(data['vix'])
        return {d: np.mean(v) for d, v in by_day.items() if v}

    vix_up = avg_vix(up_events)
    vix_down = avg_vix(down_events)

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(
        f'K1401: GDP Q1 Second Estimate Event Study\n'
        f'BEA Release Events 2001–2025 (N={len(events)}, Window ±{EVENT_WINDOW} trading days)',
        fontsize=14, fontweight='bold'
    )

    # Panel 1: Normalized VIX profile
    ax = axes[0, 0]
    vix_vals = [mean_vix_profile[d] for d in days]
    se_vals = [se_vix_profile[d] for d in days]
    ax.plot(days, vix_vals, 'b-o', ms=5, lw=1.5, label='Avg VIX (norm T0=1)')
    ax.fill_between(days,
                    [v - s for v, s in zip(vix_vals, se_vals)],
                    [v + s for v, s in zip(vix_vals, se_vals)],
                    alpha=0.2, color='blue')
    ax.axvline(0, color='red', ls='--', lw=1, alpha=0.7, label='Release Day T0')
    ax.axhline(1.0, color='gray', ls=':', lw=1)
    ax.set_xlabel('Trading Days Relative to GDP Release')
    ax.set_ylabel('VIX / VIX(T0)')
    ax.set_title('Average VIX Profile Around Release')
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Panel 2: VIX by revision direction
    ax = axes[0, 1]
    up_vix_vals = [vix_up.get(d, np.nan) for d in days]
    down_vix_vals = [vix_down.get(d, np.nan) for d in days]
    ax.plot(days, up_vix_vals, 'g-o', ms=5, lw=1.5, label=f'GDP Revision Up (N={len(up_events)})')
    ax.plot(days, down_vix_vals, 'r-s', ms=5, lw=1.5, label=f'GDP Revision Down (N={len(down_events)})')
    ax.axvline(0, color='gray', ls='--', lw=1, alpha=0.7)
    ax.set_xlabel('Trading Days Relative to GDP Release')
    ax.set_ylabel('VIX Level')
    ax.set_title('VIX by GDP Revision Direction')
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    # Panel 3: SPY daily returns around event
    ax = axes[1, 0]
    spy_vals = [mean_spy_ret.get(d, 0) for d in days]
    colors = ['green' if v >= 0 else 'red' for v in spy_vals]
    ax.bar(days, spy_vals, color=colors, alpha=0.7, edgecolor='black', lw=0.5)
    ax.axvline(0, color='blue', ls='--', lw=1, alpha=0.7, label='Release Day T0')
    ax.axhline(0, color='black', lw=0.5)
    ax.set_xlabel('Trading Days Relative to GDP Release')
    ax.set_ylabel('Average SPY Return (%)')
    ax.set_title('Average SPY Daily Return by Event Day')
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3, axis='y')

    # Panel 4: Test results summary
    ax = axes[1, 1]
    ax.axis('off')
    h1 = test_results['h1']
    h2 = test_results['h2']
    h3 = test_results['h3']

    sig_sym = lambda t: "✓ REJECT H0" if t['significant'] else "✗ FAIL to REJECT"
    summary_text = (
        f"Statistical Tests (Bonferroni α=0.05/3=0.0167, k=3)\n"
        f"{'─'*45}\n\n"
        f"H1: Pre-event VIX elevation (T-5 → T-1)\n"
        f"  t={h1['t_stat']:.3f}, p={h1['p_value']:.4f}  →  {sig_sym(h1)}\n"
        f"  VIX(T-5)={h1['mean_vix_t5']:.2f}  VIX(T-1)={h1['mean_vix_t1']:.2f}\n\n"
        f"H2: Post-announcement VIX drop (T0 → T+1)\n"
        f"  t={h2['t_stat']:.3f}, p={h2['p_value']:.4f}  →  {sig_sym(h2)}\n"
        f"  VIX(T0)={h2['mean_vix_t0']:.2f}  VIX(T+1)={h2['mean_vix_tp1']:.2f}\n\n"
        f"H3: Asymmetry (up vs down revisions)\n"
        f"  t={h3['t_stat']:.3f}, p={h3['p_value']:.4f}  →  {sig_sym(h3)}\n"
        f"  Up: {h3['mean_vix_change_up']*100:+.2f}%  Down: {h3['mean_vix_change_down']*100:+.2f}%\n\n"
        f"N Events: {len(events)} (2001–2025)"
    )
    ax.text(0.05, 0.95, summary_text, transform=ax.transAxes,
            fontsize=10, verticalalignment='top', fontfamily='monospace',
            bbox=dict(boxstyle='round', facecolor='lightyellow', alpha=0.8))
    ax.set_title('Test Results Summary')

    plt.tight_layout()
    plt.savefig(CHART_FILE, dpi=150, bbox_inches='tight')
    plt.close()
    print(f"Chart saved: {CHART_FILE}")


def main():
    print("=" * 60)
    print("K1401: GDP Q1 Second Estimate Event Study")
    print("=" * 60)

    df = load_market_data()
    events = build_event_windows(df)

    if len(events) < 10:
        raise ValueError(f"Too few valid events: {len(events)}")

    mean_vix_profile, se_vix_profile, vix_profiles = compute_vix_profiles(events)
    mean_spy_ret = compute_spy_abnormal_returns(events)

    h1 = test_h1_pre_event_elevation(events)
    h2 = test_h2_post_drop(events)
    h3 = test_h3_asymmetry(events)

    print("\n--- Test Results ---")
    for test in [h1, h2, h3]:
        sig = "SIGNIFICANT" if test['significant'] else "not significant"
        print(f"  {test['hypothesis']}")
        print(f"    t={test['t_stat']:.3f}, p={test['p_value']:.4f} [{sig}]")

    test_results = {'h1': h1, 'h2': h2, 'h3': h3}
    make_chart(events, mean_vix_profile, se_vix_profile, mean_spy_ret, test_results)

    results = {
        "experiment_id": "k1401",
        "title": "GDP Q1 Second Estimate Event Study — VIX/SPY Response to BEA Releases",
        "data_sources": {
            "market": "yfinance (SPY, ^VIX), 2000-01-01 to 2026-05-25",
            "events": "BEA Q1 GDP Second Estimate release dates 2001-2025 (hard-coded from BEA calendar)",
        },
        "sample": {
            "n_events": len(events),
            "years": [ev['year'] for ev in events],
            "event_window_days": EVENT_WINDOW,
        },
        "vix_mean_profile": {str(k): float(v) for k, v in mean_vix_profile.items()},
        "spy_mean_return_pct": {str(k): float(v) for k, v in mean_spy_ret.items()},
        "statistical_tests": test_results,
        "revision_breakdown": {
            "n_up": len([e for e in events if e['direction'] == 'up']),
            "n_down": len([e for e in events if e['direction'] == 'down']),
            "n_flat": len([e for e in events if e['direction'] == 'flat']),
        },
        "methodology": {
            "event_window": "[-5, +5] trading days around BEA release",
            "vix_normalization": "VIX(t) / VIX(T0) for profile plot",
            "multiple_testing_correction": "Bonferroni k=3, alpha_adj=0.0167",
            "seed": 42,
            "lookahead": "None — pure historical event study, no forward-looking data",
        },
        "chart": "k1401_event_study.png",
    }

    with open(RESULTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nResults saved: {RESULTS_FILE}")
    print("Done.")
    return results


if __name__ == "__main__":
    main()
