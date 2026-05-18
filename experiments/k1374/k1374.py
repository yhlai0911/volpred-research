"""
K1374: 台股除息日波動率 — 擴展樣本分析（K1373 延伸）

Extension of K1373 (CONDITIONAL_PASS, p=0.052, Cohen's d=0.188) to 17 TWSE major
constituent stocks (~3-4x more events). Tests whether ex-date volatility elevation
is confirmed at larger sample.

Lookahead note: This is a DESCRIPTIVE EVENT STUDY. Ex-dates come from yfinance .dividends
external calendar, NOT derived from return series → no lookahead. signal.shift(1) is
for PREDICTIVE models only.
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from statsmodels.stats.multitest import multipletests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
from pathlib import Path
import warnings

warnings.filterwarnings('ignore')

np.random.seed(42)

OUTPUT_DIR = Path(__file__).parent

# --- Configuration ---
TICKERS = [
    '0050.TW', '0056.TW',             # ETFs
    '2330.TW', '2317.TW', '2454.TW',  # Tech
    '2412.TW',                          # Telecom
    '2882.TW', '2881.TW', '2886.TW', '2880.TW', '2891.TW',  # Financials
    '2303.TW', '2308.TW',             # Semiconductors
    '1301.TW', '1303.TW',             # Petrochemicals
    '1216.TW',                          # Consumer
    '2002.TW',                          # Steel
]

SECTOR_MAP = {
    '0050.TW': 'ETF',
    '0056.TW': 'ETF',
    '2330.TW': 'Tech',
    '2317.TW': 'Tech',
    '2454.TW': 'Tech',
    '2412.TW': 'Industrial',
    '2882.TW': 'Financial',
    '2881.TW': 'Financial',
    '2886.TW': 'Financial',
    '2880.TW': 'Financial',
    '2891.TW': 'Financial',
    '2303.TW': 'Tech',
    '2308.TW': 'Tech',
    '1301.TW': 'Industrial',
    '1303.TW': 'Industrial',
    '1216.TW': 'Industrial',
    '2002.TW': 'Industrial',
}

PERIOD_START = '2015-01-01'
PERIOD_END = '2025-12-31'
EVENT_WINDOW = 10   # trading days around ex-date
MIN_CTRL_DISTANCE = 10  # min distance from any ex-date for a day to be "control"
MIN_DIVIDENDS = 1
MIN_PRICES = 100


# -------------------------
# Data Fetching
# -------------------------
def fetch_data(ticker: str):
    """Fetch adjusted close prices and ex-dates for a ticker.
    Returns (prices: pd.Series, ex_dates: pd.DatetimeIndex) or None on failure.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(start=PERIOD_START, end=PERIOD_END, auto_adjust=True)
        if hist.empty or len(hist) < MIN_PRICES:
            print(f"  SKIP {ticker}: insufficient price data ({len(hist)} rows)")
            return None

        prices = hist['Close'].dropna()
        prices.index = prices.index.tz_localize(None)

        divs = t.dividends
        if divs.empty or len(divs) < MIN_DIVIDENDS:
            print(f"  SKIP {ticker}: no dividends found")
            return None

        divs.index = divs.index.tz_localize(None)
        # Filter ex-dates to our study period
        ex_dates = divs.index[
            (divs.index >= pd.Timestamp(PERIOD_START)) &
            (divs.index <= pd.Timestamp(PERIOD_END))
        ]
        if len(ex_dates) == 0:
            print(f"  SKIP {ticker}: no ex-dates in study period")
            return None

        print(f"  OK {ticker}: {len(prices)} price rows, {len(ex_dates)} ex-dates")
        return prices, ex_dates

    except Exception as e:
        print(f"  ERROR {ticker}: {e}")
        return None


# -------------------------
# Absolute Returns
# -------------------------
def compute_abs_returns(prices: pd.Series) -> pd.Series:
    """Compute absolute log returns: |log(P_t / P_{t-1})|"""
    log_ret = np.log(prices / prices.shift(1))
    return log_ret.abs().dropna()


# -------------------------
# Day Classification
# -------------------------
def classify_days(abs_ret: pd.Series, ex_dates: pd.DatetimeIndex) -> dict:
    """
    Classify each trading day:
    - ex_days: the ex-date itself (t=0), snapped to nearest trading day
    - pre_days: t in [-EVENT_WINDOW, -1]
    - post_days: t in [+1, +EVENT_WINDOW]
    - control_days: min distance > MIN_CTRL_DISTANCE from any ex-date
    Returns dict with the |r| values for each category.
    """
    trading_days = abs_ret.index
    trading_days_list = list(trading_days)

    # Snap each ex-date to next available trading day
    snapped_ex_dates = []
    for ex_dt in ex_dates:
        # Find nearest trading day >= ex_dt
        future = [d for d in trading_days_list if d >= ex_dt]
        if len(future) == 0:
            continue
        # If within 3 calendar days, accept; otherwise likely a data issue
        nearest = future[0]
        if (nearest - ex_dt).days <= 5:
            snapped_ex_dates.append(nearest)

    if len(snapped_ex_dates) == 0:
        return None

    snapped_ex_dates = pd.DatetimeIndex(sorted(set(snapped_ex_dates)))

    # Index positions for fast lookup
    trading_day_pos = {d: i for i, d in enumerate(trading_days_list)}

    # Build sets
    ex_set = set(snapped_ex_dates)
    pre_set = set()
    post_set = set()

    for ex_dt in snapped_ex_dates:
        if ex_dt not in trading_day_pos:
            continue
        ex_pos = trading_day_pos[ex_dt]
        for offset in range(-EVENT_WINDOW, 0):
            pos = ex_pos + offset
            if 0 <= pos < len(trading_days_list):
                pre_set.add(trading_days_list[pos])
        for offset in range(1, EVENT_WINDOW + 1):
            pos = ex_pos + offset
            if 0 <= pos < len(trading_days_list):
                post_set.add(trading_days_list[pos])

    # Event window dates (all t in [-EVENT_WINDOW, +EVENT_WINDOW])
    event_set = ex_set | pre_set | post_set

    # Control: distance > MIN_CTRL_DISTANCE from any ex-date
    control_days = []
    for dt in trading_days_list:
        if dt in event_set:
            continue
        dt_pos = trading_day_pos[dt]
        min_dist = min(
            abs(dt_pos - trading_day_pos[ex])
            for ex in snapped_ex_dates
            if ex in trading_day_pos
        )
        if min_dist > MIN_CTRL_DISTANCE:
            control_days.append(dt)

    return {
        'ex_days': abs_ret[abs_ret.index.isin(ex_set)],
        'pre_days': abs_ret[abs_ret.index.isin(pre_set)],
        'post_days': abs_ret[abs_ret.index.isin(post_set)],
        'control_days': abs_ret[abs_ret.index.isin(control_days)],
        'snapped_ex_dates': snapped_ex_dates,
        'n_ex_dates': len(snapped_ex_dates),
    }


# -------------------------
# Event Study Stats
# -------------------------
def event_study_stats(ex_r: pd.Series, ctrl_r: pd.Series) -> dict:
    """Compute Welch t-test, Mann-Whitney U, and Cohen's d."""
    if len(ex_r) == 0 or len(ctrl_r) < 10:
        return None

    t_stat, p_value = stats.ttest_ind(ex_r.values, ctrl_r.values, equal_var=False)
    mw_stat, mw_p = stats.mannwhitneyu(ex_r.values, ctrl_r.values, alternative='two-sided')

    # Cohen's d (pooled std)
    n1, n2 = len(ex_r), len(ctrl_r)
    s1, s2 = ex_r.std(ddof=1), ctrl_r.std(ddof=1)
    pooled_std = np.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))
    cohens_d = (ex_r.mean() - ctrl_r.mean()) / pooled_std if pooled_std > 0 else 0.0

    return {
        't_stat': float(t_stat),
        'p_value': float(p_value),
        'mw_stat': float(mw_stat),
        'mw_p': float(mw_p),
        'cohens_d': float(cohens_d),
        'n_ex': int(n1),
        'n_ctrl': int(n2),
        'mean_ex': float(ex_r.mean()),
        'mean_ctrl': float(ctrl_r.mean()),
    }


# -------------------------
# Cumulative Event Profile
# -------------------------
def compute_event_profile(abs_ret: pd.Series, snapped_ex_dates, window: int = 10):
    """
    For each ex-date, get |r| at offsets t = -window to +window.
    Returns DataFrame (n_events x (2*window+1)).
    """
    trading_days_list = list(abs_ret.index)
    trading_day_pos = {d: i for i, d in enumerate(trading_days_list)}

    rows = []
    for ex_dt in snapped_ex_dates:
        if ex_dt not in trading_day_pos:
            continue
        ex_pos = trading_day_pos[ex_dt]
        row = {}
        for offset in range(-window, window + 1):
            pos = ex_pos + offset
            if 0 <= pos < len(trading_days_list):
                row[offset] = abs_ret.iloc[pos]
            else:
                row[offset] = np.nan
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


# -------------------------
# Plots
# -------------------------
def plot_event_profile(profile_df: pd.DataFrame, control_mean: float,
                       output_path: Path, n_events: int):
    """Plot mean |r| from t=-10 to t=+10, with control mean line."""
    offsets = list(range(-EVENT_WINDOW, EVENT_WINDOW + 1))
    means = profile_df[offsets].mean()
    sems = profile_df[offsets].sem()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.errorbar(offsets, means, yerr=1.96 * sems, fmt='o-', color='steelblue',
                label='Mean |r| (ex-date events)', capsize=4, linewidth=1.5)
    ax.axhline(control_mean, color='tomato', linestyle='--', linewidth=1.5,
               label=f'Control mean = {control_mean:.4f}')
    ax.axvline(0, color='gray', linestyle=':', linewidth=1.0, alpha=0.7)
    ax.fill_betweenx([0, means.max() * 1.5], -0.5, 0.5, color='yellow', alpha=0.2,
                     label='Ex-date (t=0)')
    ax.set_xlabel('Offset from Ex-date (trading days)', fontsize=12)
    ax.set_ylabel('Mean Absolute Log Return |r|', fontsize=12)
    ax.set_title(f'K1374: Event Study Profile — Ex-date |r| (N={n_events} events, 17 tickers)',
                 fontsize=13)
    ax.legend(fontsize=10)
    ax.set_xlim(-11, 11)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {output_path.name}")


def plot_sector_cohens_d(sector_d: dict, output_path: Path):
    """Bar chart of Cohen's d by sector."""
    sectors = list(sector_d.keys())
    ds = [sector_d[s] for s in sectors]
    colors = ['steelblue' if d > 0.20 else ('orange' if d > 0.15 else 'lightgray')
              for d in ds]

    fig, ax = plt.subplots(figsize=(7, 4))
    bars = ax.bar(sectors, ds, color=colors, edgecolor='black', linewidth=0.7)
    ax.axhline(0.20, color='green', linestyle='--', linewidth=1.5, label="PASS threshold (d=0.20)")
    ax.axhline(0.15, color='orange', linestyle=':', linewidth=1.5, label="CONDITIONAL_PASS (d=0.15)")
    ax.axhline(0.0, color='black', linewidth=0.5)
    for bar, d in zip(bars, ds):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.005,
                f'{d:.3f}', ha='center', va='bottom', fontsize=10)
    ax.set_xlabel('Sector', fontsize=12)
    ax.set_ylabel("Cohen's d", fontsize=12)
    ax.set_title("K1374: Cohen's d by Sector (Ex-date vs Control |r|)", fontsize=13)
    ax.legend(fontsize=9)
    ax.set_ylim(min(min(ds) - 0.05, -0.05), max(max(ds) + 0.08, 0.35))
    ax.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {output_path.name}")


def plot_pooled_distribution(ex_r: pd.Series, ctrl_r: pd.Series, output_path: Path):
    """Box plot of ex-date vs control |r| distributions."""
    fig, axes = plt.subplots(1, 2, figsize=(10, 5))

    # Box plot
    ax = axes[0]
    data = [ctrl_r.values, ex_r.values]
    labels = [f'Control\n(n={len(ctrl_r):,})', f'Ex-date\n(n={len(ex_r):,})']
    bp = ax.boxplot(data, labels=labels, patch_artist=True, showfliers=False,
                    notch=False, whis=1.5)
    bp['boxes'][0].set_facecolor('lightblue')
    bp['boxes'][1].set_facecolor('salmon')
    ax.set_ylabel('Absolute Log Return |r|', fontsize=11)
    ax.set_title('Distribution Comparison\n(whiskers = 1.5×IQR, outliers hidden)', fontsize=11)
    ax.grid(axis='y', alpha=0.3)

    # Histogram overlay
    ax2 = axes[1]
    q99 = np.percentile(np.concatenate([ctrl_r.values, ex_r.values]), 99)
    bins = np.linspace(0, q99, 40)
    ax2.hist(ctrl_r.values, bins=bins, alpha=0.5, color='steelblue', density=True,
             label=f'Control (n={len(ctrl_r):,})')
    ax2.hist(ex_r.values, bins=bins, alpha=0.6, color='tomato', density=True,
             label=f'Ex-date (n={len(ex_r):,})')
    ax2.axvline(ctrl_r.mean(), color='steelblue', linestyle='--', linewidth=1.5,
                label=f'Ctrl mean={ctrl_r.mean():.4f}')
    ax2.axvline(ex_r.mean(), color='tomato', linestyle='--', linewidth=1.5,
                label=f'Ex mean={ex_r.mean():.4f}')
    ax2.set_xlabel('Absolute Log Return |r|', fontsize=11)
    ax2.set_ylabel('Density', fontsize=11)
    ax2.set_title('Density Overlay (Pooled)', fontsize=11)
    ax2.legend(fontsize=9)
    ax2.grid(alpha=0.3)

    fig.suptitle('K1374: Pooled Ex-date vs Control |r| Distribution (17 Tickers)', fontsize=13)
    plt.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    print(f"  Saved: {output_path.name}")


# -------------------------
# Main
# -------------------------
def main():
    print("=" * 60)
    print("K1374: 台股除息日波動率擴展分析")
    print("=" * 60)

    # --- Per-ticker collection ---
    ticker_results = {}
    skipped = []

    # For pooled analysis
    all_ex_r = []
    all_ctrl_r = []

    # For event profile
    all_profile_rows = []
    all_ctrl_for_profile = []

    # For per-ticker FDR correction
    fdr_tickers = []
    fdr_pvals = []

    # For sector analysis
    sector_ex = {s: [] for s in set(SECTOR_MAP.values())}
    sector_ctrl = {s: [] for s in set(SECTOR_MAP.values())}

    # For seasonal analysis (Q2+Q3 = Apr-Sep; Q4+Q1 = Oct-Mar)
    peak_ex_r = []
    off_ex_r = []

    for ticker in TICKERS:
        print(f"\nProcessing {ticker}...")
        result = fetch_data(ticker)
        if result is None:
            skipped.append(ticker)
            continue

        prices, ex_dates = result
        abs_ret = compute_abs_returns(prices)

        classified = classify_days(abs_ret, ex_dates)
        if classified is None or len(classified['ex_days']) == 0:
            print(f"  SKIP {ticker}: no valid ex-days after classification")
            skipped.append(ticker)
            continue

        ex_r = classified['ex_days']
        ctrl_r = classified['control_days']
        snapped_ex = classified['snapped_ex_dates']

        if len(ctrl_r) < 50:
            print(f"  SKIP {ticker}: insufficient control days ({len(ctrl_r)})")
            skipped.append(ticker)
            continue

        s = event_study_stats(ex_r, ctrl_r)
        if s is None:
            skipped.append(ticker)
            continue

        ticker_results[ticker] = {
            'n_events': classified['n_ex_dates'],
            'n_ex_obs': int(len(ex_r)),
            'n_ctrl_obs': int(len(ctrl_r)),
            'mean_ex': float(ex_r.mean()),
            'mean_ctrl': float(ctrl_r.mean()),
            't_stat': s['t_stat'],
            'p_value': s['p_value'],
            'mw_p': s['mw_p'],
            'cohens_d': s['cohens_d'],
            'sector': SECTOR_MAP.get(ticker, 'Unknown'),
        }

        fdr_tickers.append(ticker)
        fdr_pvals.append(s['p_value'])

        # Accumulate for pooled
        all_ex_r.extend(ex_r.values)
        all_ctrl_r.extend(ctrl_r.values)

        # Sector
        sec = SECTOR_MAP.get(ticker, 'Other')
        sector_ex[sec].extend(ex_r.values)
        sector_ctrl[sec].extend(ctrl_r.values)

        # Seasonal: classify each ex-date by month
        for ex_dt, r_val in ex_r.items():
            month = ex_dt.month
            if 4 <= month <= 9:
                peak_ex_r.append(r_val)
            else:
                off_ex_r.append(r_val)

        # Event profile
        profile_df = compute_event_profile(abs_ret, snapped_ex, window=EVENT_WINDOW)
        if not profile_df.empty:
            all_profile_rows.append(profile_df)
        all_ctrl_for_profile.extend(ctrl_r.values)

    print(f"\n--- Data collection complete ---")
    print(f"Processed: {len(ticker_results)} tickers")
    print(f"Skipped: {skipped}")

    if len(ticker_results) == 0:
        print("ERROR: No tickers processed successfully. Aborting.")
        return

    # -----------------------------------------------
    # FDR correction (Benjamini-Hochberg)
    # -----------------------------------------------
    if len(fdr_pvals) > 0:
        reject_bh, pvals_bh, _, _ = multipletests(fdr_pvals, method='fdr_bh')
        for i, ticker in enumerate(fdr_tickers):
            ticker_results[ticker]['p_value_bh'] = float(pvals_bh[i])
            ticker_results[ticker]['reject_bh'] = bool(reject_bh[i])

    # -----------------------------------------------
    # Pooled analysis (PRIMARY)
    # -----------------------------------------------
    pool_ex = np.array(all_ex_r)
    pool_ctrl = np.array(all_ctrl_r)

    t_stat, p_val = stats.ttest_ind(pool_ex, pool_ctrl, equal_var=False)
    mw_stat, mw_p = stats.mannwhitneyu(pool_ex, pool_ctrl, alternative='two-sided')

    n1, n2 = len(pool_ex), len(pool_ctrl)
    s1, s2 = pool_ex.std(ddof=1), pool_ctrl.std(ddof=1)
    pooled_std = np.sqrt(((n1 - 1) * s1**2 + (n2 - 1) * s2**2) / (n1 + n2 - 2))
    cohens_d_pooled = (pool_ex.mean() - pool_ctrl.mean()) / pooled_std

    print(f"\n=== POOLED RESULTS ===")
    print(f"  N ex events:   {n1}")
    print(f"  N control obs: {n2}")
    print(f"  Mean ex |r|:   {pool_ex.mean():.6f}")
    print(f"  Mean ctrl |r|: {pool_ctrl.mean():.6f}")
    print(f"  Welch t:       {t_stat:.4f},  p = {p_val:.4f}")
    print(f"  Mann-Whitney:  p = {mw_p:.4f}")
    print(f"  Cohen's d:     {cohens_d_pooled:.4f}")

    # -----------------------------------------------
    # Sector Cohen's d
    # -----------------------------------------------
    sector_cohens_d = {}
    for sec in set(SECTOR_MAP.values()):
        ex_vals = np.array(sector_ex[sec])
        ctrl_vals = np.array(sector_ctrl[sec])
        if len(ex_vals) == 0 or len(ctrl_vals) < 10:
            sector_cohens_d[sec] = None
            continue
        n1s, n2s = len(ex_vals), len(ctrl_vals)
        s1s, s2s = ex_vals.std(ddof=1), ctrl_vals.std(ddof=1)
        ps = np.sqrt(((n1s - 1) * s1s**2 + (n2s - 1) * s2s**2) / (n1s + n2s - 2))
        d = (ex_vals.mean() - ctrl_vals.mean()) / ps if ps > 0 else 0.0
        sector_cohens_d[sec] = float(d)
        print(f"  Sector {sec}: d={d:.4f} (n_ex={n1s}, n_ctrl={n2s})")

    # -----------------------------------------------
    # Seasonal analysis
    # -----------------------------------------------
    peak_arr = np.array(peak_ex_r)
    off_arr = np.array(off_ex_r)
    ctrl_arr = pool_ctrl

    peak_d = None
    off_d = None
    if len(peak_arr) > 0 and len(ctrl_arr) > 0:
        n_p, n_c = len(peak_arr), len(ctrl_arr)
        s_p, s_c = peak_arr.std(ddof=1), ctrl_arr.std(ddof=1)
        ps_peak = np.sqrt(((n_p - 1) * s_p**2 + (n_c - 1) * s_c**2) / (n_p + n_c - 2))
        peak_d = float((peak_arr.mean() - ctrl_arr.mean()) / ps_peak) if ps_peak > 0 else 0.0
    if len(off_arr) > 0 and len(ctrl_arr) > 0:
        n_o, n_c = len(off_arr), len(ctrl_arr)
        s_o, s_c = off_arr.std(ddof=1), ctrl_arr.std(ddof=1)
        ps_off = np.sqrt(((n_o - 1) * s_o**2 + (n_c - 1) * s_c**2) / (n_o + n_c - 2))
        off_d = float((off_arr.mean() - ctrl_arr.mean()) / ps_off) if ps_off > 0 else 0.0

    print(f"  Peak-season (Apr-Sep) Cohen's d: {peak_d}")
    print(f"  Off-season (Oct-Mar) Cohen's d:  {off_d}")

    # -----------------------------------------------
    # Verdict
    # -----------------------------------------------
    if p_val < 0.05 and cohens_d_pooled > 0.20:
        verdict = "PASS"
        verdict_rationale = (
            f"Pooled Welch t-test: p={p_val:.4f} < 0.05 and Cohen's d={cohens_d_pooled:.3f} > 0.20. "
            "Both criteria met — ex-date volatility elevation confirmed at large sample."
        )
    elif p_val < 0.10 and cohens_d_pooled > 0.15:
        verdict = "CONDITIONAL_PASS"
        verdict_rationale = (
            f"Pooled p={p_val:.4f} (0.05 ≤ p < 0.10) and d={cohens_d_pooled:.3f} > 0.15. "
            "Marginal result — effect present but not firmly established."
        )
    else:
        verdict = "NULL"
        verdict_rationale = (
            f"Pooled p={p_val:.4f} and d={cohens_d_pooled:.3f} — "
            "at least one of p<0.10 or d>0.15 not met. K1373 finding does not survive expansion to 17 tickers."
        )

    print(f"\n  VERDICT: {verdict}")
    print(f"  Rationale: {verdict_rationale}")

    # -----------------------------------------------
    # Plots
    # -----------------------------------------------
    print("\n--- Generating plots ---")
    ctrl_mean_overall = pool_ctrl.mean()

    # Plot 1: Event profile
    if all_profile_rows:
        profile_combined = pd.concat(all_profile_rows, ignore_index=True)
        plot_event_profile(
            profile_combined,
            ctrl_mean_overall,
            OUTPUT_DIR / 'k1374_event_study_profile.png',
            n_events=n1,
        )

    # Plot 2: Sector Cohen's d
    sector_d_clean = {k: v for k, v in sector_cohens_d.items() if v is not None}
    if sector_d_clean:
        plot_sector_cohens_d(
            sector_d_clean,
            OUTPUT_DIR / 'k1374_cohens_d_by_sector.png',
        )

    # Plot 3: Pooled distribution
    plot_pooled_distribution(
        pd.Series(pool_ex),
        pd.Series(pool_ctrl),
        OUTPUT_DIR / 'k1374_pooled_distribution.png',
    )

    # -----------------------------------------------
    # Save results JSON
    # -----------------------------------------------
    n_total_events = sum(v['n_events'] for v in ticker_results.values())
    results = {
        "experiment_id": "K1374",
        "title": "台股除息日波動率 — 擴展樣本分析",
        "verdict": verdict,
        "summary": (
            f"Pooled {n1} ex-date events across {len(ticker_results)} TWSE tickers. "
            f"Mean ex |r|={pool_ex.mean():.5f} vs ctrl={pool_ctrl.mean():.5f} "
            f"(ratio={pool_ex.mean()/pool_ctrl.mean():.3f}). "
            f"Welch t={t_stat:.3f}, p={p_val:.4f}; MW p={mw_p:.4f}; Cohen's d={cohens_d_pooled:.3f}. "
            f"Verdict: {verdict}."
        ),
        "pooled_stats": {
            "n_ex_events": int(n1),
            "n_control_obs": int(n2),
            "mean_ex_abs_ret": float(pool_ex.mean()),
            "mean_ctrl_abs_ret": float(pool_ctrl.mean()),
            "ex_ctrl_ratio": float(pool_ex.mean() / pool_ctrl.mean()),
            "t_stat": float(t_stat),
            "p_value": float(p_val),
            "mw_stat": float(mw_stat),
            "mw_p": float(mw_p),
            "cohens_d": float(cohens_d_pooled),
        },
        "per_ticker": {
            t: {
                "n_events": r['n_events'],
                "n_ex_obs": r['n_ex_obs'],
                "mean_ex": round(r['mean_ex'], 6),
                "mean_ctrl": round(r['mean_ctrl'], 6),
                "cohens_d": round(r['cohens_d'], 4),
                "p_value": round(r['p_value'], 4),
                "p_value_bh": round(r.get('p_value_bh', r['p_value']), 4),
                "reject_bh": r.get('reject_bh', False),
                "sector": r['sector'],
            }
            for t, r in ticker_results.items()
        },
        "sector_cohens_d": {
            k: round(v, 4) if v is not None else None
            for k, v in sector_cohens_d.items()
        },
        "seasonal_analysis": {
            "peak_season_months": "Apr-Sep",
            "off_season_months": "Oct-Mar",
            "n_peak_events": int(len(peak_arr)),
            "n_off_events": int(len(off_arr)),
            "peak_season_d": round(peak_d, 4) if peak_d is not None else None,
            "off_season_d": round(off_d, 4) if off_d is not None else None,
        },
        "verdict_rationale": verdict_rationale,
        "tickers_processed": list(ticker_results.keys()),
        "tickers_skipped": skipped,
        "data_source": "yfinance adjusted close + .dividends",
        "period": f"{PERIOD_START} to {PERIOD_END}",
        "seed": 42,
        "related_experiments": ["K1373"],
        "date": "2026-05-18",
    }

    results_path = OUTPUT_DIR / 'k1374_results.json'
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved: {results_path.name}")

    print("\n" + "=" * 60)
    print(f"K1374 COMPLETE — Verdict: {verdict}")
    print("=" * 60)
    return results


if __name__ == '__main__':
    main()
