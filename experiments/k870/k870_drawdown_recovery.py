"""K870: Drawdown Recovery Pattern — Does VT Recover Faster After Crashes?

Clean redo of K735 (overturned by Codex: fake OOS + timing misalignment).
Focus on DESCRIPTIVE analysis only — no strategy evaluation.

Research Questions:
  1. After a 10%+ drawdown, does a VT portfolio recover to previous peak FASTER than B&H?
  2. Is recovery speed regime-dependent (faster in V-shaped vs L-shaped crashes)?
  3. Does the robust VT (K859 Floor+Cap+EWMA) recover faster than plain 12/VIX?

Key context:
  - K735 descriptive results (Spearman rho) may still hold, but strategy was contaminated
  - N85: "VT shallower drawdown but SLOWER recovery" — VIX stays elevated post-crisis
  - K688: VT wins CRRA utility gamma>=5, K860: VT wins Prospect Theory lambda=1.52
  - K859: Floor+Cap+EWMA(10) = best robust VT, Sharpe 0.579, turnover -30%
  - VT is drawdown INSURANCE, not alpha generator (K687/K697/K700)

Methodology:
  1. Data: yfinance SPY, GLD, ^VIX. Period: 2005-01 to 2026-04.
  2. Strategies (all monthly rebalance, shift(1)):
     - BH SPY (100% equity baseline)
     - BH 50/50 SPY/GLD
     - 12/VIX monthly (standard VT)
     - Floor(0.3)+Cap(0.9)+EWMA(10) monthly (K859 robust VT)
  3. Identify SPY drawdown episodes > 10% from peak
  4. For each episode: measure recovery time for EACH strategy from its own trough
  5. Recovery ratio: strategy recovery days / BH SPY recovery days
  6. Statistical test: Wilcoxon signed-rank (paired, non-parametric, small N)
  7. Regime split: V-shaped (SPY recovery < 180 days) vs L-shaped (>= 180 days)

Error log rules applied:
  - Lookahead: signal.shift(1) mandatory
  - Sharpe > 2x baseline = almost certainly a bug
  - All signals properly lagged before computing returns

References:
  - K735: Overturned drawdown recovery (Codex review)
  - K859: Robust VT design (Floor/Cap+EWMA)
  - K687: Post-correction VT ranking (no VT beats BH 50/50 on Sharpe)
  - K688: CRRA utility analysis (VT wins gamma>=5)
  - N85: VT recovery paradox (shallower but slower)
  - Copeland & Copeland (1999), Market Timing with VIX
  - Harvey et al. (2016), t > 3.0 threshold

Author: VolPred Research System
Date: 2026-04-05
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2005-01-01"
END_DATE = "2026-04-05"
EVAL_START = "2006-01-03"
TC_BPS = 5                     # Transaction cost in basis points (one-way)
VIX_12_BASELINE_CAP = 1.5     # Original 12/VIX cap
FLOOR = 0.3
CAP = 0.9
EWMA_SPAN = 10                 # K859 best
DD_THRESHOLD = 0.10            # 10% drawdown threshold for episode identification
V_SHAPE_CUTOFF = 180           # Days: recovery < 180 = V-shaped, >= 180 = L-shaped


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("=" * 70)
    print("K870: DRAWDOWN RECOVERY PATTERN — DOES VT RECOVER FASTER?")
    print("=" * 70)
    print("\n[1] DOWNLOADING DATA")

    tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
    raw = {}

    for name, ticker in tickers.items():
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        raw[name] = df
        print(f"  {name}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

    spy_ret = raw["SPY"]["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    gld_ret = raw["GLD"]["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"
    vix_close = raw["VIX"]["Close"].copy()
    vix_close.name = "vix"

    data = pd.concat([spy_ret, gld_ret, vix_close], axis=1).dropna()

    print(f"\n  Merged data: {len(data)} rows, {data.index[0].date()} to {data.index[-1].date()}")
    print(f"  SPY: ann return = {data['spy_ret'].mean()*252*100:.1f}%, ann vol = {data['spy_ret'].std()*np.sqrt(252)*100:.1f}%")
    print(f"  GLD: ann return = {data['gld_ret'].mean()*252*100:.1f}%, ann vol = {data['gld_ret'].std()*np.sqrt(252)*100:.1f}%")
    print(f"  VIX: mean={data['vix'].mean():.1f}, median={data['vix'].median():.1f}")

    return data


# ============================================================================
# Strategy Returns Computation
# ============================================================================
def compute_strategy_returns(data):
    """Compute daily returns for each strategy. ALL signals lagged by shift(1)."""
    print("\n[2] COMPUTING STRATEGY RETURNS (ALL LAGGED BY shift(1))")

    vix = data["vix"]
    spy_ret = data["spy_ret"]
    gld_ret = data["gld_ret"]

    # --- Helper: monthly rebalance ---
    def to_monthly(raw_weight):
        """Hold weight constant between monthly rebalance dates."""
        rebal_dates = raw_weight.groupby(
            raw_weight.index.to_period("M")
        ).apply(lambda g: g.index[0])
        held = raw_weight.copy() * np.nan
        for d in rebal_dates:
            if d in held.index:
                held.loc[d] = raw_weight.loc[d]
        held = held.ffill()
        return held

    strategies = {}

    # --- BH SPY (100% equity) ---
    strategies["BH_SPY"] = spy_ret.copy()

    # --- BH 50/50 SPY/GLD ---
    strategies["BH_5050"] = 0.5 * spy_ret + 0.5 * gld_ret

    # --- 12/VIX monthly (standard VT) ---
    raw_12vix = np.minimum(12.0 / vix, VIX_12_BASELINE_CAP)
    w_12vix = to_monthly(raw_12vix).shift(1)  # LAG
    prev_w_12vix = w_12vix.shift(1)
    turnover_12vix = (w_12vix - prev_w_12vix).abs()
    tc_12vix = turnover_12vix * TC_BPS / 10000
    strategies["VT_12VIX"] = (
        w_12vix * spy_ret + (1 - w_12vix) * gld_ret - tc_12vix
    ).dropna()
    print(f"  12/VIX: mean weight = {w_12vix.dropna().mean():.3f}")

    # --- Floor+Cap+EWMA(10) monthly (K859 robust VT) ---
    vix_ewma = vix.ewm(span=EWMA_SPAN, min_periods=EWMA_SPAN).mean()
    raw_robust = np.maximum(FLOOR, np.minimum(CAP, np.minimum(12.0 / vix_ewma, VIX_12_BASELINE_CAP)))
    w_robust = to_monthly(raw_robust).shift(1)  # LAG
    prev_w_robust = w_robust.shift(1)
    turnover_robust = (w_robust - prev_w_robust).abs()
    tc_robust = turnover_robust * TC_BPS / 10000
    strategies["VT_Robust"] = (
        w_robust * spy_ret + (1 - w_robust) * gld_ret - tc_robust
    ).dropna()
    print(f"  Robust VT: mean weight = {w_robust.dropna().mean():.3f}")

    # Align all to eval period
    for name in strategies:
        s = strategies[name]
        strategies[name] = s.loc[s.index >= pd.Timestamp(EVAL_START)].dropna()

    # Quick sanity: print annualized returns and Sharpe
    print("\n  Quick sanity check (annualized):")
    for name, rets in strategies.items():
        ann_ret = rets.mean() * 252
        ann_vol = rets.std() * np.sqrt(252)
        sharpe = (ann_ret - 0.04) / ann_vol
        mdd = compute_mdd(rets)
        print(f"    {name:15s}: CAGR={ann_ret*100:.1f}%, Vol={ann_vol*100:.1f}%, "
              f"Sharpe={sharpe:.3f}, MDD={mdd*100:.1f}%")

    return strategies


# ============================================================================
# Drawdown Analysis
# ============================================================================
def compute_mdd(returns):
    """Compute max drawdown from a return series."""
    cumret = (1 + returns).cumprod()
    peak = cumret.cummax()
    dd = (cumret - peak) / peak
    return dd.min()


def compute_drawdown_series(returns):
    """Compute cumulative return and drawdown series."""
    cumret = (1 + returns).cumprod()
    peak = cumret.cummax()
    drawdown = (cumret - peak) / peak
    return cumret, peak, drawdown


def identify_drawdown_episodes(returns, threshold=DD_THRESHOLD):
    """Identify drawdown episodes exceeding threshold.

    Uses SPY drawdowns as the 'trigger' — we identify when SPY has a >10% drawdown,
    then measure each strategy's behavior during that same calendar period.

    Returns list of episodes: {peak_date, trough_date, recovery_date, depth}
    """
    cumret, peak, drawdown = compute_drawdown_series(returns)

    episodes = []
    i = 0
    dates = drawdown.index
    n = len(dates)

    while i < n:
        # Find next point where drawdown crosses below -threshold
        if drawdown.iloc[i] <= -threshold:
            # Find the peak date (last date where cumret == peak before this point)
            peak_val = peak.iloc[i]
            # Walk backwards to find when peak was set
            peak_idx = i
            for j in range(i, -1, -1):
                if cumret.iloc[j] >= peak_val * 0.999:  # small tolerance
                    peak_idx = j
                    break
            peak_date = dates[peak_idx]

            # Find the trough (minimum drawdown in this episode)
            trough_idx = i
            min_dd = drawdown.iloc[i]
            j = i
            while j < n:
                if drawdown.iloc[j] < min_dd:
                    min_dd = drawdown.iloc[j]
                    trough_idx = j
                # Episode ends when we recover to peak (drawdown >= 0)
                if drawdown.iloc[j] >= 0 and j > trough_idx:
                    break
                j += 1

            trough_date = dates[trough_idx]
            depth = min_dd

            # Find recovery date (first date after trough where drawdown >= 0)
            recovery_date = None
            for j in range(trough_idx + 1, n):
                if drawdown.iloc[j] >= 0:
                    recovery_date = dates[j]
                    break

            episodes.append({
                "peak_date": peak_date,
                "trough_date": trough_date,
                "recovery_date": recovery_date,
                "depth": float(depth),
                "peak_idx": peak_idx,
                "trough_idx": trough_idx,
            })

            # Skip past the recovery (or trough if no recovery)
            if recovery_date is not None:
                i = j + 1
            else:
                i = trough_idx + 1
                # Skip remaining negative drawdown
                while i < n and drawdown.iloc[i] < 0:
                    i += 1
        else:
            i += 1

    return episodes


def measure_recovery_for_strategy(strategy_returns, episode, spy_returns):
    """For a given SPY drawdown episode, measure this strategy's behavior.

    We use the SPY peak_date as the START of the episode for all strategies.
    Then we measure:
    - Strategy drawdown depth during episode
    - Strategy recovery time from its own trough
    - Strategy cumulative path from SPY peak_date
    """
    peak_date = episode["peak_date"]
    spy_trough_date = episode["trough_date"]

    # Get strategy returns from peak_date onwards
    mask = strategy_returns.index >= peak_date
    strat_rets = strategy_returns.loc[mask]

    if len(strat_rets) < 10:
        return None

    # Compute strategy cumulative return from peak_date
    strat_cumret = (1 + strat_rets).cumprod()
    strat_peak = strat_cumret.cummax()
    strat_dd = (strat_cumret - strat_peak) / strat_peak

    # Find strategy's trough within the episode window
    # Window: peak_date to min(SPY recovery + buffer, end of data)
    # Use a generous window: up to 2x SPY trough-to-recovery distance after SPY trough
    spy_episode_end = episode.get("recovery_date")
    if spy_episode_end is not None:
        spy_recovery_days = (spy_episode_end - spy_trough_date).days
        window_end = spy_episode_end + pd.Timedelta(days=max(spy_recovery_days, 180))
    else:
        window_end = strat_rets.index[-1]

    window_mask = strat_dd.index <= window_end
    strat_dd_window = strat_dd.loc[window_mask]

    if len(strat_dd_window) == 0:
        return None

    # Strategy's trough
    strat_trough_idx = strat_dd_window.idxmin()
    strat_depth = float(strat_dd_window.min())

    # Strategy's recovery: first date after trough where cumret >= peak (dd >= 0)
    after_trough = strat_dd.loc[strat_dd.index > strat_trough_idx]
    recovery_dates = after_trough[after_trough >= 0].index
    strat_recovery_date = recovery_dates[0] if len(recovery_dates) > 0 else None

    # Recovery time: days from strategy trough to recovery
    if strat_recovery_date is not None:
        strat_recovery_days = (strat_recovery_date - strat_trough_idx).days
    else:
        strat_recovery_days = None  # Not yet recovered

    # Total episode duration: peak to recovery
    if strat_recovery_date is not None:
        total_episode_days = (strat_recovery_date - peak_date).days
    else:
        total_episode_days = None

    return {
        "depth": strat_depth,
        "trough_date": str(strat_trough_idx.date()),
        "recovery_date": str(strat_recovery_date.date()) if strat_recovery_date else None,
        "recovery_days_from_trough": strat_recovery_days,
        "total_episode_days": total_episode_days,
    }


def analyze_drawdown_episodes(strategies):
    """Main analysis: identify episodes and measure recovery for each strategy."""
    print("\n[3] IDENTIFYING DRAWDOWN EPISODES (SPY > 10%)")

    # Use BH SPY as the reference for identifying episodes
    spy_episodes = identify_drawdown_episodes(strategies["BH_SPY"], DD_THRESHOLD)

    print(f"  Found {len(spy_episodes)} SPY drawdown episodes > {DD_THRESHOLD*100:.0f}%:")
    for i, ep in enumerate(spy_episodes):
        rec_str = str(ep['recovery_date'].date()) if ep['recovery_date'] else "NOT RECOVERED"
        print(f"    Episode {i+1}: Peak={ep['peak_date'].date()}, "
              f"Trough={ep['trough_date'].date()}, "
              f"Recovery={rec_str}, "
              f"Depth={ep['depth']*100:.1f}%")

    # Measure each strategy's behavior during each SPY episode
    print("\n[4] MEASURING RECOVERY FOR EACH STRATEGY")

    strat_names = list(strategies.keys())
    all_results = []

    for i, ep in enumerate(spy_episodes):
        episode_result = {
            "episode": i + 1,
            "spy_peak_date": str(ep["peak_date"].date()),
            "spy_trough_date": str(ep["trough_date"].date()),
            "spy_depth": float(ep["depth"]),
            "spy_recovery_date": str(ep["recovery_date"].date()) if ep["recovery_date"] else None,
            "strategies": {}
        }

        for name in strat_names:
            result = measure_recovery_for_strategy(
                strategies[name], ep, strategies["BH_SPY"]
            )
            if result:
                episode_result["strategies"][name] = result

        all_results.append(episode_result)

    return spy_episodes, all_results


# ============================================================================
# Statistical Tests
# ============================================================================
def recovery_statistics(all_results, strategies_list):
    """Compute recovery statistics and paired tests."""
    print("\n[5] RECOVERY STATISTICS")

    # Extract paired recovery times (only episodes where BOTH strategies recovered)
    reference = "BH_SPY"
    comparisons = {}

    for strat in strategies_list:
        if strat == reference:
            continue

        ref_times = []
        strat_times = []
        episode_labels = []

        for res in all_results:
            ref_data = res["strategies"].get(reference)
            strat_data = res["strategies"].get(strat)

            if (ref_data and strat_data and
                ref_data["recovery_days_from_trough"] is not None and
                strat_data["recovery_days_from_trough"] is not None):
                ref_times.append(ref_data["recovery_days_from_trough"])
                strat_times.append(strat_data["recovery_days_from_trough"])
                episode_labels.append(res["episode"])

        if len(ref_times) < 3:
            print(f"\n  {strat} vs {reference}: Only {len(ref_times)} paired episodes — skipping test")
            comparisons[strat] = {
                "n_paired": len(ref_times),
                "test": "insufficient_data"
            }
            continue

        ref_arr = np.array(ref_times)
        strat_arr = np.array(strat_times)
        diff = strat_arr - ref_arr  # negative = strategy recovers FASTER

        # Recovery ratio
        ratio = strat_arr / ref_arr

        # Wilcoxon signed-rank test (paired, non-parametric)
        try:
            wilcoxon_stat, wilcoxon_p = sp_stats.wilcoxon(diff, alternative="two-sided")
        except ValueError:
            # All differences are zero
            wilcoxon_stat, wilcoxon_p = 0.0, 1.0

        # Paired t-test (for comparison)
        t_stat, t_p = sp_stats.ttest_rel(strat_arr, ref_arr)

        # Sign test: how many times does strategy recover FASTER?
        n_faster = int(np.sum(diff < 0))
        n_slower = int(np.sum(diff > 0))
        n_same = int(np.sum(diff == 0))

        comp = {
            "n_paired": len(ref_times),
            "ref_mean_days": float(np.mean(ref_arr)),
            "ref_median_days": float(np.median(ref_arr)),
            "strat_mean_days": float(np.mean(strat_arr)),
            "strat_median_days": float(np.median(strat_arr)),
            "mean_diff_days": float(np.mean(diff)),
            "median_diff_days": float(np.median(diff)),
            "mean_ratio": float(np.mean(ratio)),
            "median_ratio": float(np.median(ratio)),
            "n_faster": n_faster,
            "n_slower": n_slower,
            "n_same": n_same,
            "wilcoxon_stat": float(wilcoxon_stat),
            "wilcoxon_p": float(wilcoxon_p),
            "paired_t_stat": float(t_stat),
            "paired_t_p": float(t_p),
            "episode_details": [
                {
                    "episode": episode_labels[j],
                    "ref_days": int(ref_times[j]),
                    "strat_days": int(strat_times[j]),
                    "diff_days": int(strat_times[j] - ref_times[j]),
                    "ratio": round(strat_times[j] / ref_times[j], 3),
                }
                for j in range(len(ref_times))
            ]
        }

        comparisons[strat] = comp

        print(f"\n  {strat} vs {reference} ({len(ref_times)} paired episodes):")
        print(f"    {reference} mean recovery: {np.mean(ref_arr):.0f} days (median {np.median(ref_arr):.0f})")
        print(f"    {strat} mean recovery: {np.mean(strat_arr):.0f} days (median {np.median(strat_arr):.0f})")
        print(f"    Mean diff: {np.mean(diff):+.0f} days (negative = faster)")
        print(f"    Mean ratio: {np.mean(ratio):.3f} (< 1 = faster)")
        print(f"    Faster/Slower/Same: {n_faster}/{n_slower}/{n_same}")
        print(f"    Wilcoxon p = {wilcoxon_p:.4f}, Paired-t t = {t_stat:.3f}, p = {t_p:.4f}")

    return comparisons


def depth_comparison(all_results, strategies_list):
    """Compare drawdown DEPTHS across strategies."""
    print("\n[6] DRAWDOWN DEPTH COMPARISON")

    depth_data = {s: [] for s in strategies_list}
    episode_labels = []

    for res in all_results:
        has_all = all(s in res["strategies"] for s in strategies_list)
        if has_all:
            episode_labels.append(res["episode"])
            for s in strategies_list:
                depth_data[s].append(res["strategies"][s]["depth"])

    print(f"\n  Episodes with all strategies present: {len(episode_labels)}")
    print(f"\n  {'Strategy':20s} {'Mean Depth':>12s} {'Median Depth':>14s} {'Min':>8s} {'Max':>8s}")
    print("  " + "-" * 62)

    depth_stats = {}
    for s in strategies_list:
        arr = np.array(depth_data[s])
        depth_stats[s] = {
            "mean_depth": float(np.mean(arr)),
            "median_depth": float(np.median(arr)),
            "min_depth": float(np.min(arr)),
            "max_depth": float(np.max(arr)),
        }
        print(f"  {s:20s} {np.mean(arr)*100:>11.1f}% {np.median(arr)*100:>13.1f}% "
              f"{np.min(arr)*100:>7.1f}% {np.max(arr)*100:>7.1f}%")

    # Paired test: VT depth vs BH SPY depth
    ref = "BH_SPY"
    for strat in ["BH_5050", "VT_12VIX", "VT_Robust"]:
        if strat in depth_data and len(depth_data[strat]) >= 3:
            ref_arr = np.array(depth_data[ref])
            strat_arr = np.array(depth_data[strat])
            diff = strat_arr - ref_arr  # positive = shallower (less negative)
            try:
                _, wp = sp_stats.wilcoxon(diff, alternative="two-sided")
            except ValueError:
                wp = 1.0
            mean_relief = np.mean(diff)
            print(f"\n  {strat} vs {ref} depth relief: {mean_relief*100:+.1f}pp, Wilcoxon p={wp:.4f}")
            depth_stats[f"{strat}_vs_{ref}_depth_relief"] = {
                "mean_relief_pp": float(mean_relief * 100),
                "wilcoxon_p": float(wp),
            }

    return depth_stats


def regime_analysis(all_results, strategies_list):
    """Split episodes by V-shaped vs L-shaped recovery regime."""
    print("\n[7] REGIME ANALYSIS (V-SHAPED vs L-SHAPED)")

    reference = "BH_SPY"

    # Classify episodes based on SPY recovery time
    v_episodes = []
    l_episodes = []

    for res in all_results:
        spy_data = res["strategies"].get(reference)
        if spy_data and spy_data["recovery_days_from_trough"] is not None:
            if spy_data["recovery_days_from_trough"] < V_SHAPE_CUTOFF:
                v_episodes.append(res)
            else:
                l_episodes.append(res)

    print(f"  V-shaped (SPY recovery < {V_SHAPE_CUTOFF} days): {len(v_episodes)} episodes")
    print(f"  L-shaped (SPY recovery >= {V_SHAPE_CUTOFF} days): {len(l_episodes)} episodes")

    regime_results = {}

    for regime_name, episodes in [("V-shaped", v_episodes), ("L-shaped", l_episodes)]:
        if len(episodes) < 2:
            print(f"\n  {regime_name}: Too few episodes for analysis")
            regime_results[regime_name] = {"n_episodes": len(episodes), "note": "too_few"}
            continue

        print(f"\n  --- {regime_name} Regime ({len(episodes)} episodes) ---")

        regime_data = {}
        for strat in strategies_list:
            recovery_times = []
            depths = []
            for ep in episodes:
                sdata = ep["strategies"].get(strat)
                if sdata:
                    depths.append(sdata["depth"])
                    if sdata["recovery_days_from_trough"] is not None:
                        recovery_times.append(sdata["recovery_days_from_trough"])

            if recovery_times:
                regime_data[strat] = {
                    "n": len(recovery_times),
                    "mean_recovery_days": float(np.mean(recovery_times)),
                    "median_recovery_days": float(np.median(recovery_times)),
                    "mean_depth": float(np.mean(depths)) if depths else None,
                }
                print(f"    {strat:20s}: recovery mean={np.mean(recovery_times):.0f}d, "
                      f"median={np.median(recovery_times):.0f}d (n={len(recovery_times)}), "
                      f"depth mean={np.mean(depths)*100:.1f}%")

        # Recovery ratio vs BH SPY
        if reference in regime_data:
            ref_mean = regime_data[reference]["mean_recovery_days"]
            for strat in strategies_list:
                if strat != reference and strat in regime_data:
                    ratio = regime_data[strat]["mean_recovery_days"] / ref_mean
                    regime_data[strat]["recovery_ratio_vs_BH_SPY"] = float(ratio)
                    print(f"    {strat} ratio vs BH_SPY: {ratio:.3f}")

        regime_results[regime_name] = {
            "n_episodes": len(episodes),
            "strategies": regime_data,
        }

    return regime_results


def total_episode_analysis(all_results, strategies_list):
    """Analyze total episode duration (peak to recovery) — the investor's experience."""
    print("\n[8] TOTAL EPISODE DURATION (PEAK → RECOVERY)")

    total_data = {s: [] for s in strategies_list}
    episode_labels = []

    for res in all_results:
        for s in strategies_list:
            sdata = res["strategies"].get(s)
            if sdata and sdata["total_episode_days"] is not None:
                total_data[s].append(sdata["total_episode_days"])

    print(f"\n  {'Strategy':20s} {'N':>3s} {'Mean Days':>10s} {'Median Days':>12s} {'Min':>6s} {'Max':>6s}")
    print("  " + "-" * 57)

    total_stats = {}
    for s in strategies_list:
        arr = np.array(total_data[s])
        if len(arr) == 0:
            continue
        total_stats[s] = {
            "n": len(arr),
            "mean_days": float(np.mean(arr)),
            "median_days": float(np.median(arr)),
            "min_days": float(np.min(arr)),
            "max_days": float(np.max(arr)),
        }
        print(f"  {s:20s} {len(arr):3d} {np.mean(arr):10.0f} {np.median(arr):12.0f} "
              f"{np.min(arr):6.0f} {np.max(arr):6.0f}")

    return total_stats


# ============================================================================
# VIX Correlation with Recovery Speed
# ============================================================================
def vix_recovery_correlation(all_results, data):
    """Test if VIX at drawdown onset predicts recovery speed (redo K735 descriptive)."""
    print("\n[9] VIX AT ONSET vs RECOVERY SPEED (Descriptive, no strategy)")

    vix_at_peak = []
    spy_recovery_days = []
    spy_depths = []
    vix_change_during = []

    for res in all_results:
        peak_date = pd.Timestamp(res["spy_peak_date"])
        trough_date = pd.Timestamp(res["spy_trough_date"])
        spy_data = res["strategies"].get("BH_SPY")

        if spy_data and spy_data["recovery_days_from_trough"] is not None:
            # VIX at peak date
            if peak_date in data.index:
                vix_peak = data.loc[peak_date, "vix"]
            else:
                # Find nearest date
                nearest = data.index[data.index.get_indexer([peak_date], method="nearest")[0]]
                vix_peak = data.loc[nearest, "vix"]

            # VIX at trough date
            if trough_date in data.index:
                vix_trough = data.loc[trough_date, "vix"]
            else:
                nearest = data.index[data.index.get_indexer([trough_date], method="nearest")[0]]
                vix_trough = data.loc[nearest, "vix"]

            vix_at_peak.append(vix_peak)
            spy_recovery_days.append(spy_data["recovery_days_from_trough"])
            spy_depths.append(spy_data["depth"])
            vix_change_during.append(vix_trough - vix_peak)

    results = {}

    if len(vix_at_peak) < 5:
        print(f"  Only {len(vix_at_peak)} episodes with VIX data — limited analysis")
        results["n"] = len(vix_at_peak)
        results["note"] = "limited_sample"
        return results

    vix_arr = np.array(vix_at_peak)
    rec_arr = np.array(spy_recovery_days)
    depth_arr = np.array(spy_depths)
    vix_chg_arr = np.array(vix_change_during)

    # Spearman rank correlations
    rho_vix_recovery, p_vix_recovery = sp_stats.spearmanr(vix_arr, rec_arr)
    rho_vix_depth, p_vix_depth = sp_stats.spearmanr(vix_arr, depth_arr)
    rho_vixchg_recovery, p_vixchg_recovery = sp_stats.spearmanr(vix_chg_arr, rec_arr)

    print(f"\n  N = {len(vix_arr)} episodes")
    print(f"  VIX at peak → Recovery days: rho = {rho_vix_recovery:+.3f}, p = {p_vix_recovery:.4f}")
    print(f"  VIX at peak → Depth:         rho = {rho_vix_depth:+.3f}, p = {p_vix_depth:.4f}")
    print(f"  VIX change  → Recovery days:  rho = {rho_vixchg_recovery:+.3f}, p = {p_vixchg_recovery:.4f}")

    results = {
        "n": len(vix_arr),
        "vix_peak_vs_recovery_rho": float(rho_vix_recovery),
        "vix_peak_vs_recovery_p": float(p_vix_recovery),
        "vix_peak_vs_depth_rho": float(rho_vix_depth),
        "vix_peak_vs_depth_p": float(p_vix_depth),
        "vix_change_vs_recovery_rho": float(rho_vixchg_recovery),
        "vix_change_vs_recovery_p": float(p_vixchg_recovery),
    }

    # Print episode details
    print(f"\n  {'Episode':>8s} {'VIX@Peak':>10s} {'VIX Chg':>9s} {'Depth':>8s} {'Recovery':>10s}")
    print("  " + "-" * 47)
    for j in range(len(vix_arr)):
        print(f"  {j+1:8d} {vix_arr[j]:10.1f} {vix_chg_arr[j]:+9.1f} "
              f"{depth_arr[j]*100:7.1f}% {rec_arr[j]:10.0f}d")

    return results


# ============================================================================
# Main
# ============================================================================
def main():
    start_time = datetime.now()

    # 1. Download data
    data = download_data()

    # 2. Compute strategy returns
    strategies = compute_strategy_returns(data)
    strategies_list = ["BH_SPY", "BH_5050", "VT_12VIX", "VT_Robust"]

    # 3. Identify drawdown episodes & measure recovery
    spy_episodes, all_results = analyze_drawdown_episodes(strategies)

    # 4. Recovery statistics with paired tests
    recovery_comps = recovery_statistics(all_results, strategies_list)

    # 5. Depth comparison
    depth_stats = depth_comparison(all_results, strategies_list)

    # 6. Regime analysis
    regime_results = regime_analysis(all_results, strategies_list)

    # 7. Total episode duration
    total_stats = total_episode_analysis(all_results, strategies_list)

    # 8. VIX correlation
    vix_corr = vix_recovery_correlation(all_results, data)

    # =========================================================
    # Summary
    # =========================================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Key finding: does VT recover faster?
    for strat in ["BH_5050", "VT_12VIX", "VT_Robust"]:
        comp = recovery_comps.get(strat, {})
        if comp.get("test") == "insufficient_data":
            print(f"\n  {strat}: Insufficient paired episodes")
            continue

        n = comp.get("n_paired", 0)
        if n == 0:
            continue

        mean_ratio = comp.get("mean_ratio", 1.0)
        median_ratio = comp.get("median_ratio", 1.0)
        wp = comp.get("wilcoxon_p", 1.0)
        faster = comp.get("n_faster", 0)
        slower = comp.get("n_slower", 0)

        if mean_ratio < 1:
            direction = "FASTER"
        elif mean_ratio > 1:
            direction = "SLOWER"
        else:
            direction = "SAME"

        sig = "YES" if wp < 0.05 else "NO"
        print(f"\n  {strat} recovery vs BH_SPY: {direction}")
        print(f"    Mean ratio: {mean_ratio:.3f}, Median ratio: {median_ratio:.3f}")
        print(f"    Faster/Slower: {faster}/{slower} episodes")
        print(f"    Wilcoxon p = {wp:.4f} (significant at 5%: {sig})")

    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"\n  Runtime: {elapsed:.1f}s")

    # =========================================================
    # Save results
    # =========================================================
    results = {
        "experiment_id": "K870",
        "title": "K870: Drawdown Recovery Pattern — Does VT Recover Faster After Crashes?",
        "date": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "period": f"{START_DATE} to {END_DATE}",
        "eval_start": EVAL_START,
        "dd_threshold": DD_THRESHOLD,
        "v_shape_cutoff_days": V_SHAPE_CUTOFF,
        "strategies": ["BH_SPY (100% equity)", "BH_5050 (50/50 SPY/GLD)",
                       "VT_12VIX (12/VIX monthly)", "VT_Robust (Floor+Cap+EWMA10 monthly)"],
        "n_episodes": len(spy_episodes),
        "episodes": all_results,
        "recovery_comparisons_vs_BH_SPY": recovery_comps,
        "depth_comparison": depth_stats,
        "regime_analysis": regime_results,
        "total_episode_duration": total_stats,
        "vix_correlation": vix_corr,
        "methodology": {
            "episode_identification": "SPY drawdown > 10% from peak",
            "recovery_measurement": "Each strategy measured from SPY peak date, using own cumulative return",
            "statistical_tests": "Wilcoxon signed-rank (paired, non-parametric) + paired t-test",
            "regime_split": f"V-shaped: SPY recovery < {V_SHAPE_CUTOFF} days, L-shaped: >= {V_SHAPE_CUTOFF} days",
            "lag": "All signals shift(1) — no lookahead",
            "transaction_costs": f"{TC_BPS} bps one-way",
        },
        "key_prior_results": {
            "K735": "OVERTURNED by Codex (fake OOS + timing misalignment). Descriptive rho may hold.",
            "N85": "VT shallower drawdown but SLOWER recovery (VIX elevated post-crisis)",
            "K688": "VT wins CRRA utility gamma>=5",
            "K859": "Floor+Cap+EWMA(10) best robust VT",
        },
        "runtime_seconds": elapsed,
    }

    # Determine key conclusion
    vt_12vix_comp = recovery_comps.get("VT_12VIX", {})
    vt_robust_comp = recovery_comps.get("VT_Robust", {})

    conclusions = []
    for name, comp in [("VT_12VIX", vt_12vix_comp), ("VT_Robust", vt_robust_comp)]:
        if comp.get("test") == "insufficient_data" or comp.get("n_paired", 0) == 0:
            conclusions.append(f"{name}: insufficient data for recovery comparison")
        else:
            ratio = comp.get("mean_ratio", 1.0)
            wp = comp.get("wilcoxon_p", 1.0)
            faster = comp.get("n_faster", 0)
            slower = comp.get("n_slower", 0)

            if ratio < 0.9 and wp < 0.05:
                conclusions.append(f"{name}: significantly FASTER recovery (ratio {ratio:.3f}, p={wp:.4f})")
            elif ratio > 1.1 and wp < 0.05:
                conclusions.append(f"{name}: significantly SLOWER recovery (ratio {ratio:.3f}, p={wp:.4f})")
            elif ratio < 1:
                conclusions.append(f"{name}: slightly faster but NOT significant (ratio {ratio:.3f}, p={wp:.4f}, {faster}/{slower} episodes)")
            elif ratio > 1:
                conclusions.append(f"{name}: slightly slower but NOT significant (ratio {ratio:.3f}, p={wp:.4f}, {faster}/{slower} episodes)")
            else:
                conclusions.append(f"{name}: no difference (ratio {ratio:.3f}, p={wp:.4f})")

    results["conclusions"] = conclusions

    out_path = Path("experiments/k870_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    print("\n  CONCLUSIONS:")
    for c in conclusions:
        print(f"    - {c}")

    print("\n" + "=" * 70)
    print("K870 COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
