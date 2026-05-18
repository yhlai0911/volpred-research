"""
K1375: 高股息 ETF 除息日波動率事件研究（0056 / 00878 / 00919）

Extension of K1374 (PASS, 17 TWSE stocks, peak-season d=0.306) to HIGH-DIVIDEND ETFs.
Three product types: annual (0056), quarterly (00878), monthly (00919).
Focus questions:
  1. Do high-div ETFs show same ex-date vol elevation as individual stocks (K1374)?
  2. Does dividend frequency affect the effect size?
  3. What is the [-5,+5] event profile shape (pre vs post)?

Lookahead note: DESCRIPTIVE EVENT STUDY. Ex-dates from yfinance .dividends external
calendar, NOT derived from return series → no lookahead issue. signal.shift(1) only
applies to predictive strategies, not event studies.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
from pathlib import Path
import warnings

warnings.filterwarnings('ignore')
np.random.seed(42)

OUTPUT_DIR = Path(__file__).parent

# --- Configuration (consistent with K1374) ---
TICKERS = ['0056.TW', '00878.TW', '00919.TW']
TICKER_LABELS = {
    '0056.TW':  '0056 (年配)',
    '00878.TW': '00878 (季配)',
    '00919.TW': '00919 (月配)',
}
PERIOD_START = '2008-01-01'
PERIOD_END   = '2026-04-30'

EVENT_HALF_WINDOW = 10   # show [-10,+10] profile
MAIN_TEST_WINDOW  = 1    # T=[-1,0,+1] vs control for main stat
MIN_CTRL_DISTANCE = 10   # days from any ex-date to be a clean control


# -------------------------
# Data Fetching
# -------------------------
def fetch_data(ticker: str):
    """Return (abs_returns: pd.Series, ex_dates: pd.DatetimeIndex) or None."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(start=PERIOD_START, end=PERIOD_END, auto_adjust=True)
        if hist.empty or len(hist) < 100:
            print(f"  SKIP {ticker}: insufficient data ({len(hist)} rows)")
            return None

        prices = hist['Close'].dropna()
        prices.index = prices.index.tz_localize(None)

        abs_ret = prices.pct_change().abs().dropna()

        divs = t.dividends
        if divs.empty:
            print(f"  SKIP {ticker}: no dividends")
            return None
        divs.index = divs.index.tz_localize(None)

        ex_dates = divs.index[
            (divs.index >= pd.Timestamp(PERIOD_START)) &
            (divs.index <= pd.Timestamp(PERIOD_END))
        ]
        # Keep only ex-dates that exist in price index (skip non-trading days)
        ex_dates = ex_dates[ex_dates.isin(abs_ret.index)]
        if len(ex_dates) == 0:
            print(f"  SKIP {ticker}: no ex-dates align with price data")
            return None

        print(f"  {ticker}: {len(abs_ret)} price days, {len(ex_dates)} ex-dates")
        return abs_ret, ex_dates
    except Exception as e:
        print(f"  ERROR {ticker}: {e}")
        return None


# -------------------------
# Event Study
# -------------------------
def build_event_profile(abs_ret: pd.Series, ex_dates, half_window: int = 10):
    """
    Returns matrix of shape (n_events, 2*half_window+1) with |return| at each
    event day offset.
    Rows where the window hits a data boundary are dropped.
    """
    price_idx = abs_ret.index
    rows = []
    for ex_date in ex_dates:
        loc = price_idx.get_loc(ex_date)
        lo = loc - half_window
        hi = loc + half_window + 1
        if lo < 0 or hi > len(price_idx):
            continue
        rows.append(abs_ret.iloc[lo:hi].values)
    if not rows:
        return None
    return np.array(rows)  # (n_events, 2*half_window+1)


def get_control_days(abs_ret: pd.Series, ex_dates):
    """Return |return| values on 'clean' control days (far from any ex-date)."""
    all_ex = set(ex_dates)
    control_mask = pd.Series(True, index=abs_ret.index)
    for ex_date in ex_dates:
        loc = abs_ret.index.get_loc(ex_date)
        lo = max(0, loc - MIN_CTRL_DISTANCE)
        hi = min(len(abs_ret), loc + MIN_CTRL_DISTANCE + 1)
        for i in range(lo, hi):
            control_mask.iloc[i] = False
    return abs_ret[control_mask].values


def ttest_and_cohens_d(event_vals, ctrl_vals):
    """Welch t-test + Cohen's d (pooled SD)."""
    t_stat, p_val = stats.ttest_ind(event_vals, ctrl_vals, equal_var=False)
    n1, n2 = len(event_vals), len(ctrl_vals)
    s1, s2 = np.std(event_vals, ddof=1), np.std(ctrl_vals, ddof=1)
    pooled_sd = np.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))
    d = (np.mean(event_vals) - np.mean(ctrl_vals)) / pooled_sd
    return float(t_stat), float(p_val), float(d)


def bootstrap_ci(event_vals, ctrl_vals, n_boot=2000, seed=42):
    """Bootstrap 95% CI on (mean_event - mean_ctrl)."""
    rng = np.random.default_rng(seed)
    diffs = []
    for _ in range(n_boot):
        e = rng.choice(event_vals, size=len(event_vals), replace=True)
        c = rng.choice(ctrl_vals,  size=len(ctrl_vals),  replace=True)
        diffs.append(e.mean() - c.mean())
    diffs = np.array(diffs)
    return (float(np.percentile(diffs, 2.5)),
            float(np.percentile(diffs, 97.5)),
            float(np.mean(diffs)))


# -------------------------
# Main Analysis
# -------------------------
def analyze_ticker(ticker: str, cached_data: dict | None = None):
    if cached_data is not None and ticker in cached_data:
        abs_ret, ex_dates = cached_data[ticker]
    else:
        result = fetch_data(ticker)
        if result is None:
            return None
        abs_ret, ex_dates = result
        if cached_data is not None:
            cached_data[ticker] = (abs_ret, ex_dates)

    # Build event profile matrix
    matrix = build_event_profile(abs_ret, ex_dates, half_window=EVENT_HALF_WINDOW)
    if matrix is None or len(matrix) < 3:
        print(f"  SKIP {ticker}: too few complete event windows ({0 if matrix is None else len(matrix)})")
        return None

    n_events = len(matrix)
    # Profile: mean |return| at each day offset
    profile_mean = matrix.mean(axis=0)
    profile_sem  = matrix.std(axis=0, ddof=1) / np.sqrt(n_events)
    offsets = list(range(-EVENT_HALF_WINDOW, EVENT_HALF_WINDOW + 1))

    # Main test: T=0 vs control
    t0_idx = EVENT_HALF_WINDOW  # index 10 = offset 0
    event_t0   = matrix[:, t0_idx]         # ex-date day
    event_pm1  = matrix[:, t0_idx-1:t0_idx+2].mean(axis=1)  # [-1,0,+1] window

    ctrl_vals  = get_control_days(abs_ret, ex_dates)

    t_t0,  p_t0,  d_t0  = ttest_and_cohens_d(event_t0, ctrl_vals)
    t_pm1, p_pm1, d_pm1 = ttest_and_cohens_d(event_pm1, ctrl_vals)

    ci_lo, ci_hi, ci_mean = bootstrap_ci(event_t0, ctrl_vals)

    # Pre (-5 to -1) vs Post (+1 to +5) test
    pre_window  = matrix[:, t0_idx-5:t0_idx].mean(axis=1)
    post_window = matrix[:, t0_idx+1:t0_idx+6].mean(axis=1)
    t_prepost, p_prepost = stats.ttest_rel(pre_window, post_window)

    return {
        'ticker': ticker,
        'label':  TICKER_LABELS.get(ticker, ticker),
        'n_events': n_events,
        'n_ctrl': int(len(ctrl_vals)),
        'mean_event_t0':  float(event_t0.mean()),
        'mean_ctrl':      float(ctrl_vals.mean()),
        't_stat_t0':      t_t0,
        'p_value_t0':     p_t0,
        'cohens_d_t0':    d_t0,
        'ci_95_lo':       ci_lo,
        'ci_95_hi':       ci_hi,
        't_stat_pm1':     t_pm1,
        'p_value_pm1':    p_pm1,
        'cohens_d_pm1':   d_pm1,
        't_stat_prepost': float(t_prepost),
        'p_value_prepost': float(p_prepost),
        'profile_mean':   [float(x) for x in profile_mean],
        'profile_sem':    [float(x) for x in profile_sem],
        'offsets':        offsets,
    }


# -------------------------
# Pooled Analysis
# -------------------------
def pooled_analysis(cached_data: dict, ticker_results: list):
    """Pool all T=0 events across tickers using pre-fetched data."""
    all_t0 = []
    all_ctrl = []
    for tr in ticker_results:
        ticker = tr['ticker']
        if ticker not in cached_data:
            continue
        abs_ret, ex_dates = cached_data[ticker]
        matrix = build_event_profile(abs_ret, ex_dates, half_window=EVENT_HALF_WINDOW)
        if matrix is None:
            continue
        t0_idx = EVENT_HALF_WINDOW
        all_t0.extend(matrix[:, t0_idx].tolist())
        ctrl_vals = get_control_days(abs_ret, ex_dates)
        all_ctrl.extend(ctrl_vals.tolist())

    all_t0   = np.array(all_t0)
    all_ctrl = np.array(all_ctrl)
    t_stat, p_val, d = ttest_and_cohens_d(all_t0, all_ctrl)
    ci_lo, ci_hi, ci_mean = bootstrap_ci(all_t0, all_ctrl)
    return {
        'n_events': len(all_t0),
        'n_ctrl':   len(all_ctrl),
        'mean_event': float(all_t0.mean()),
        'mean_ctrl':  float(all_ctrl.mean()),
        't_stat':     t_stat,
        'p_value':    p_val,
        'cohens_d':   d,
        'ci_95_lo':   ci_lo,
        'ci_95_hi':   ci_hi,
    }


# -------------------------
# Plotting
# -------------------------
def plot_event_profiles(ticker_results):
    fig, ax = plt.subplots(figsize=(10, 6))
    colors = ['#1f77b4', '#ff7f0e', '#2ca02c']
    for i, tr in enumerate(ticker_results):
        offsets = tr['offsets']
        mean    = np.array(tr['profile_mean']) * 100   # to %
        sem     = np.array(tr['profile_sem'])  * 100
        ax.plot(offsets, mean, label=tr['label'], color=colors[i], linewidth=2)
        ax.fill_between(offsets, mean - sem, mean + sem,
                        alpha=0.15, color=colors[i])

    ax.axvline(x=0, color='red', linestyle='--', linewidth=1.5, label='Ex-date (T=0)')
    ax.axvline(x=-1, color='gray', linestyle=':', linewidth=1, alpha=0.6)
    ax.axvline(x=1,  color='gray', linestyle=':', linewidth=1, alpha=0.6)
    ax.set_xlabel('Event Day Offset (Trading Days)', fontsize=12)
    ax.set_ylabel('Mean |Return| (%)', fontsize=12)
    ax.set_title('K1375: 高股息 ETF 除息日前後 |Return| 事件研究\n(±SEM shading)', fontsize=13)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'k1375_event_profiles.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved k1375_event_profiles.png")


def plot_t0_comparison(ticker_results):
    """Bar chart: mean |return| at T=0 vs control for each ETF."""
    fig, ax = plt.subplots(figsize=(8, 5))
    labels   = [tr['label'] for tr in ticker_results]
    t0_means = [tr['mean_event_t0'] * 100 for tr in ticker_results]
    ct_means = [tr['mean_ctrl'] * 100 for tr in ticker_results]
    d_vals   = [tr['cohens_d_t0'] for tr in ticker_results]
    p_vals   = [tr['p_value_t0'] for tr in ticker_results]

    x = np.arange(len(labels))
    w = 0.35
    bars_ev = ax.bar(x - w/2, t0_means, w, label='除息日 (T=0)', color='#d62728', alpha=0.8)
    bars_ct = ax.bar(x + w/2, ct_means, w, label='控制組 (非事件)',  color='#1f77b4', alpha=0.8)

    for i, (t0, ct, d, p) in enumerate(zip(t0_means, ct_means, d_vals, p_vals)):
        sig = '***' if p < 0.01 else '**' if p < 0.05 else '*' if p < 0.10 else ''
        ax.text(x[i] - w/2, t0 + 0.01, f'd={d:.2f}{sig}', ha='center', va='bottom', fontsize=9)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylabel('Mean |Return| (%)', fontsize=12)
    ax.set_title('K1375: 除息日 T=0 vs 控制組 |Return| 比較\n(*** p<0.01, ** p<0.05, * p<0.10)', fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(True, alpha=0.3, axis='y')
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / 'k1375_t0_comparison.png', dpi=150, bbox_inches='tight')
    plt.close()
    print("  Saved k1375_t0_comparison.png")


# -------------------------
# Entry Point
# -------------------------
def main():
    print("=" * 60)
    print("K1375: 高股息 ETF 除息日波動率事件研究")
    print("=" * 60)

    cached_data: dict = {}
    ticker_results = []
    for ticker in TICKERS:
        print(f"\nProcessing {ticker}...")
        res = analyze_ticker(ticker, cached_data)
        if res:
            ticker_results.append(res)
            print(f"  n_events={res['n_events']}, d={res['cohens_d_t0']:.3f}, p={res['p_value_t0']:.4f}")

    if not ticker_results:
        print("ERROR: no valid results")
        return

    print(f"\n{'='*60}")
    print("Pooled analysis...")
    pooled = pooled_analysis(cached_data, ticker_results)
    print(f"  Pooled: n={pooled['n_events']}, d={pooled['cohens_d']:.3f}, p={pooled['p_value']:.4f}")

    print("\nGenerating plots...")
    plot_event_profiles(ticker_results)
    plot_t0_comparison(ticker_results)

    # Compare with K1374 benchmark
    k1374_d_peak = 0.3055  # from K1374 results peak-season

    results = {
        'experiment_id': 'K1375',
        'title': '高股息 ETF 除息日波動率事件研究（0056 / 00878 / 00919）',
        'date': '2026-05-18',
        'method': 'Event study: |return| at ex-date T=0 vs clean control days; Welch t-test; Cohen\'s d; 2000-rep bootstrap 95% CI',
        'lookahead_note': 'DESCRIPTIVE EVENT STUDY: ex-dates from yfinance external calendar, NOT from return series. No predictive signal used.',
        'tickers': ticker_results,
        'pooled': pooled,
        'k1374_benchmark': {
            'peak_season_d': k1374_d_peak,
            'description': 'K1374 peak-season (Apr-Sep) Cohen\'s d for individual stocks',
        },
        'summary': {
            'n_tickers': len(ticker_results),
            'total_events': sum(tr['n_events'] for tr in ticker_results),
            'pooled_d': pooled['cohens_d'],
            'pooled_p': pooled['p_value'],
            'pooled_significant_05': pooled['p_value'] < 0.05,
        }
    }

    out_path = OUTPUT_DIR / 'k1375_results.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nResults saved: {out_path}")

    print("\n=== SUMMARY ===")
    for tr in ticker_results:
        sig = '✓' if tr['p_value_t0'] < 0.05 else '~' if tr['p_value_t0'] < 0.10 else '✗'
        print(f"  {tr['label']:20s}: n={tr['n_events']:3d}, d={tr['cohens_d_t0']:+.3f}, p={tr['p_value_t0']:.4f} {sig}")
    print(f"\n  POOLED: n={pooled['n_events']:3d}, d={pooled['cohens_d']:+.3f}, p={pooled['p_value']:.4f}")
    print(f"  K1374 benchmark (peak-season d): {k1374_d_peak:.3f}")


if __name__ == '__main__':
    main()
