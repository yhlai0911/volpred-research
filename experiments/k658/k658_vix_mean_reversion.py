"""
K658: VIX Mean-Reversion Speed and Strategy Re-Entry Implications
==================================================================
Motivation:
  K652 found VIX mean-reverts from >25 to <20 in median 24 calendar days (67 episodes).
  T20 showed half-life by era: normal 9.7-15d, crisis 25-33d.
  P30 showed AR(1) rho=0.969, half-life 22 days.
  N182 showed Excess Fear Signal (buying fear) passes Harvey threshold (t=4.48).

  But HOW FAST VIX reverts matters for strategy timing — should we re-enter
  immediately after a spike, or wait? This experiment provides actionable guidance.

Prior knowledge:
  - K652: VIX action thresholds, mean-reversion analysis
  - K656: VIX-based VT reconciliation — VIX VT works
  - T20: VIX half-life structural stability
  - T39: VIX half-life as crisis warning (null result)
  - P30: VIX AR(1) rho=0.969, long-term mean 17.5
  - N182: Excess Fear Signal — Z>1.5: 5d return +0.72% (t=4.48)

Data source: yfinance (SPY, ^VIX), 2006-01-01 to 2026-03-27
Type: Empirical analysis (real data)

References:
  - Whaley (2000) "The Investor Fear Gauge" JPC — VIX as fear index
  - Bekaert & Hoerova (2014) "The VIX, the Variance Premium and Stock Market
    Volatility" JoE — VIX decomposition and mean-reversion
  - Todorov & Tauchen (2011) "Volatility Jumps" JFE — volatility jump dynamics
  - Simon & Wiggins (2001) "S&P Futures Returns and Contrary Sentiment" JFQA
  - Giot (2005) "Relationships Between IV Indexes and Stock Index Returns" JPM
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from pathlib import Path
from scipy import stats, optimize
import warnings
warnings.filterwarnings('ignore')

# ── Configuration ─────────────────────────────────────────────────────
START_DATE = "2006-01-01"
END_DATE = "2026-03-27"
SPIKE_THRESHOLD = 25       # VIX crosses above this from below
REVERSION_TARGET_20 = 20   # "normalized" threshold
REVERSION_TARGET_15 = 15   # "calm" threshold
RE_ENTRY_TRIGGER = 30      # For re-entry analysis: VIX must cross above 30
RESULTS_FILE = Path(__file__).resolve().parent / "k658_results.json"


def download_data():
    """Download SPY and VIX data."""
    print("=" * 70)
    print("K658: VIX Mean-Reversion Speed and Strategy Re-Entry Implications")
    print("=" * 70)
    print(f"\nDownloading data: SPY, ^VIX ({START_DATE} to {END_DATE})")

    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False)

    # Handle multi-level columns from yfinance
    for df in [spy, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    data = pd.DataFrame({
        'spy_close': spy['Close'],
        'vix_close': vix['Close']
    }).dropna()

    data['spy_ret'] = data['spy_close'].pct_change()
    data = data.dropna()

    print(f"Data: {len(data)} trading days "
          f"({data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')})")
    return data


# ═══════════════════════════════════════════════════════════════════════
# PART 1: Identify VIX spike events (VIX crosses above 25 from below)
# ═══════════════════════════════════════════════════════════════════════
def identify_spike_events(data, threshold=SPIKE_THRESHOLD):
    """
    Identify VIX spike events: VIX crosses above threshold from below.
    Merge events that are within 5 trading days of each other.
    """
    vix = data['vix_close'].values
    dates = data.index

    # Find crossing-up points
    crossings = []
    for i in range(1, len(vix)):
        if vix[i] >= threshold and vix[i-1] < threshold:
            crossings.append(i)

    # Merge close events (within 5 days)
    merged = []
    if crossings:
        merged.append(crossings[0])
        for c in crossings[1:]:
            if c - merged[-1] > 20:  # New episode if >20 days apart
                merged.append(c)

    print(f"\n{'='*60}")
    print(f"PART 1: VIX Spike Events (crossing above {threshold})")
    print(f"{'='*60}")
    print(f"Raw crossings: {len(crossings)}")
    print(f"Merged episodes (>20 days apart): {len(merged)}")

    events = []
    for idx in merged:
        # Find peak VIX in the episode (within 60 days or until VIX drops below 20)
        peak_vix = vix[idx]
        peak_idx = idx
        search_end = min(idx + 60, len(vix))
        for j in range(idx, search_end):
            if vix[j] > peak_vix:
                peak_vix = vix[j]
                peak_idx = j
            if j > peak_idx + 10 and vix[j] < 20:
                break

        time_to_peak = peak_idx - idx

        # Time to return below 20
        time_to_20 = None
        for j in range(peak_idx, min(peak_idx + 252, len(vix))):
            if vix[j] < 20:
                time_to_20 = j - peak_idx
                break

        # Time to return below 15
        time_to_15 = None
        for j in range(peak_idx, min(peak_idx + 504, len(vix))):
            if vix[j] < 15:
                time_to_15 = j - peak_idx
                break

        events.append({
            'cross_date': str(dates[idx].date()),
            'cross_idx': int(idx),
            'peak_date': str(dates[peak_idx].date()),
            'peak_idx': int(peak_idx),
            'cross_vix': float(vix[idx]),
            'peak_vix': float(peak_vix),
            'time_to_peak': int(time_to_peak),
            'time_to_20': int(time_to_20) if time_to_20 is not None else None,
            'time_to_15': int(time_to_15) if time_to_15 is not None else None,
        })

    print(f"\nTotal spike events: {len(events)}")
    return events


# ═══════════════════════════════════════════════════════════════════════
# PART 2: Distribution and half-life analysis
# ═══════════════════════════════════════════════════════════════════════
def analyze_reversion_distribution(events, data):
    """Analyze the distribution of reversion times and fit exponential decay."""
    print(f"\n{'='*60}")
    print("PART 2: Reversion Distribution & Half-Life")
    print(f"{'='*60}")

    vix = data['vix_close'].values

    # ── Distribution of reversion times ──
    times_to_20 = [e['time_to_20'] for e in events if e['time_to_20'] is not None]
    times_to_15 = [e['time_to_15'] for e in events if e['time_to_15'] is not None]
    peak_vixes = [e['peak_vix'] for e in events]

    print(f"\n--- Reversion from peak to <20 ---")
    print(f"  N events with reversion: {len(times_to_20)}/{len(events)}")
    if times_to_20:
        t20 = np.array(times_to_20)
        print(f"  Mean: {np.mean(t20):.1f} trading days")
        print(f"  Median: {np.median(t20):.1f} trading days")
        print(f"  Std: {np.std(t20):.1f}")
        print(f"  25th pctl: {np.percentile(t20, 25):.1f}")
        print(f"  75th pctl: {np.percentile(t20, 75):.1f}")
        print(f"  Min: {np.min(t20)}, Max: {np.max(t20)}")

    print(f"\n--- Reversion from peak to <15 ---")
    print(f"  N events with reversion: {len(times_to_15)}/{len(events)}")
    if times_to_15:
        t15 = np.array(times_to_15)
        print(f"  Mean: {np.mean(t15):.1f} trading days")
        print(f"  Median: {np.median(t15):.1f} trading days")
        print(f"  Std: {np.std(t15):.1f}")
        print(f"  25th pctl: {np.percentile(t15, 25):.1f}")
        print(f"  75th pctl: {np.percentile(t15, 75):.1f}")

    print(f"\n--- Peak VIX Distribution ---")
    pv = np.array(peak_vixes)
    print(f"  Mean: {np.mean(pv):.1f}")
    print(f"  Median: {np.median(pv):.1f}")
    print(f"  Max: {np.max(pv):.1f}")
    print(f"  >30: {np.sum(pv > 30)}, >40: {np.sum(pv > 40)}, >50: {np.sum(pv > 50)}")

    # ── Correlation: peak VIX vs reversion time ──
    paired_peak_t20 = [(e['peak_vix'], e['time_to_20'])
                       for e in events if e['time_to_20'] is not None]
    if len(paired_peak_t20) > 5:
        peaks, times = zip(*paired_peak_t20)
        r, p = stats.pearsonr(peaks, times)
        rho_s, p_s = stats.spearmanr(peaks, times)
        print(f"\n--- Peak VIX vs Time-to-20 Correlation ---")
        print(f"  Pearson: r={r:.3f} (p={p:.4f})")
        print(f"  Spearman: rho={rho_s:.3f} (p={p_s:.4f})")

    # ── Fit exponential half-life model ──
    # VIX_t = VIX_long + (VIX_peak - VIX_long) * exp(-t/tau)
    # Collect all post-peak VIX paths (first 60 days)
    print(f"\n--- Exponential Decay Half-Life Fit ---")
    all_paths = []
    max_horizon = 60
    for e in events:
        peak_idx = e['peak_idx']
        if peak_idx + max_horizon < len(vix):
            path = vix[peak_idx:peak_idx + max_horizon + 1]
            # Normalize: (VIX_t - VIX_long) / (VIX_peak - VIX_long)
            vix_long = 17.5  # long-term VIX mean (from P30)
            if e['peak_vix'] > vix_long + 2:
                normalized = (path - vix_long) / (e['peak_vix'] - vix_long)
                all_paths.append(normalized)

    if all_paths:
        # Average normalized path
        avg_path = np.mean(all_paths, axis=0)
        t_vals = np.arange(len(avg_path))

        # Fit: normalized(t) = exp(-t/tau)
        def exp_decay(t, tau):
            return np.exp(-t / tau)

        try:
            popt, pcov = optimize.curve_fit(
                exp_decay, t_vals[1:], avg_path[1:],
                p0=[15.0], bounds=(1.0, 200.0)
            )
            tau = popt[0]
            half_life = tau * np.log(2)
            tau_se = np.sqrt(pcov[0, 0])

            print(f"  Decay constant tau: {tau:.1f} days (SE: {tau_se:.2f})")
            print(f"  Half-life: {half_life:.1f} days")
            print(f"  90% decay: {tau * np.log(10):.1f} days")
            print(f"  N paths used: {len(all_paths)}")

            # R-squared
            fitted = exp_decay(t_vals[1:], tau)
            ss_res = np.sum((avg_path[1:] - fitted) ** 2)
            ss_tot = np.sum((avg_path[1:] - np.mean(avg_path[1:])) ** 2)
            r_sq = 1 - ss_res / ss_tot
            print(f"  R-squared: {r_sq:.4f}")
        except Exception as ex:
            print(f"  Fit failed: {ex}")
            tau = None
            half_life = None
            r_sq = None
    else:
        tau = half_life = r_sq = None

    return {
        'reversion_to_20': {
            'n': len(times_to_20),
            'mean': float(np.mean(times_to_20)) if times_to_20 else None,
            'median': float(np.median(times_to_20)) if times_to_20 else None,
            'std': float(np.std(times_to_20)) if times_to_20 else None,
            'p25': float(np.percentile(times_to_20, 25)) if times_to_20 else None,
            'p75': float(np.percentile(times_to_20, 75)) if times_to_20 else None,
        },
        'reversion_to_15': {
            'n': len(times_to_15),
            'mean': float(np.mean(times_to_15)) if times_to_15 else None,
            'median': float(np.median(times_to_15)) if times_to_15 else None,
        },
        'peak_vix': {
            'mean': float(np.mean(peak_vixes)),
            'median': float(np.median(peak_vixes)),
            'max': float(np.max(peak_vixes)),
            'gt_30': int(np.sum(pv > 30)),
            'gt_40': int(np.sum(pv > 40)),
        },
        'half_life': {
            'tau': float(tau) if tau else None,
            'half_life_days': float(half_life) if half_life else None,
            'r_squared': float(r_sq) if r_sq else None,
            'n_paths': len(all_paths),
        },
        'peak_vs_reversion_corr': {
            'pearson_r': float(r) if 'r' in dir() else None,
            'pearson_p': float(p) if 'p' in dir() else None,
            'spearman_rho': float(rho_s) if 'rho_s' in dir() else None,
        }
    }


# ═══════════════════════════════════════════════════════════════════════
# PART 3: SPY returns during VIX reversion phase
# ═══════════════════════════════════════════════════════════════════════
def analyze_spy_during_reversion(events, data):
    """
    Compare SPY returns during VIX reversion phase vs non-reversion.
    Reversion phase = peak_idx to time_to_20 completion.
    """
    print(f"\n{'='*60}")
    print("PART 3: SPY Returns During VIX Reversion Phase")
    print(f"{'='*60}")

    spy_ret = data['spy_ret'].values
    n = len(spy_ret)

    # Mark reversion days
    is_reversion = np.zeros(n, dtype=bool)
    reversion_returns = []
    for e in events:
        if e['time_to_20'] is not None:
            start = e['peak_idx']
            end = min(start + e['time_to_20'], n)
            is_reversion[start:end] = True
            reversion_returns.append(
                float(np.sum(spy_ret[start:end]))  # cumulative return
            )

    rev_daily = spy_ret[is_reversion]
    non_rev_daily = spy_ret[~is_reversion]

    # Annualized stats
    rev_mean = np.mean(rev_daily) * 252
    rev_std = np.std(rev_daily) * np.sqrt(252)
    rev_sharpe = rev_mean / rev_std if rev_std > 0 else 0

    non_mean = np.mean(non_rev_daily) * 252
    non_std = np.std(non_rev_daily) * np.sqrt(252)
    non_sharpe = non_mean / non_std if non_std > 0 else 0

    # t-test for difference
    t_stat, t_pval = stats.ttest_ind(rev_daily, non_rev_daily, equal_var=False)

    print(f"\n  Reversion phase days: {np.sum(is_reversion)} ({np.sum(is_reversion)/n*100:.1f}%)")
    print(f"  Non-reversion days: {np.sum(~is_reversion)} ({np.sum(~is_reversion)/n*100:.1f}%)")
    print(f"\n  --- Annualized SPY Returns ---")
    print(f"  {'Phase':<20} {'Return':>10} {'Vol':>10} {'Sharpe':>10}")
    print(f"  {'Reversion':<20} {rev_mean:>10.2%} {rev_std:>10.2%} {rev_sharpe:>10.3f}")
    print(f"  {'Non-reversion':<20} {non_mean:>10.2%} {non_std:>10.2%} {non_sharpe:>10.3f}")
    print(f"\n  Mean diff t-stat: {t_stat:.3f} (p={t_pval:.4f})")

    # Average cumulative return during reversion episodes
    avg_cum_ret = np.mean(reversion_returns) if reversion_returns else 0
    print(f"\n  Avg cumulative SPY return per reversion episode: {avg_cum_ret:.2%}")
    print(f"  Median: {np.median(reversion_returns):.2%}" if reversion_returns else "")

    return {
        'reversion_days': int(np.sum(is_reversion)),
        'pct_of_total': float(np.sum(is_reversion) / n * 100),
        'reversion_ann_return': float(rev_mean),
        'reversion_ann_vol': float(rev_std),
        'reversion_sharpe': float(rev_sharpe),
        'non_reversion_ann_return': float(non_mean),
        'non_reversion_ann_vol': float(non_std),
        'non_reversion_sharpe': float(non_sharpe),
        'mean_diff_t': float(t_stat),
        'mean_diff_p': float(t_pval),
        'avg_cum_return_per_episode': float(avg_cum_ret),
        'n_episodes': len(reversion_returns),
    }


# ═══════════════════════════════════════════════════════════════════════
# PART 4: Optimal re-entry strategy after VIX > 30
# ═══════════════════════════════════════════════════════════════════════
def analyze_reentry_strategies(events, data):
    """
    After VIX > 30, compare different re-entry rules:
    a) Immediately (VIX drops below 30)
    b) Wait for VIX < 25
    c) Wait for VIX < 20
    d) Wait N days after peak (N = 5, 10, 20, 30)
    e) Gradual re-entry (10% per day for 10 days starting at peak+5)

    For each: total SPY return captured in 60 days after entry,
    max drawdown during 60 days.
    """
    print(f"\n{'='*60}")
    print("PART 4: Optimal Re-Entry Strategy After VIX > 30")
    print(f"{'='*60}")

    vix = data['vix_close'].values
    spy_ret = data['spy_ret'].values
    spy_px = data['spy_close'].values
    n = len(vix)

    # Filter events with peak VIX > 30
    high_events = [e for e in events if e['peak_vix'] >= 30]
    print(f"\n  Events with peak VIX >= 30: {len(high_events)}")

    if not high_events:
        print("  No events to analyze.")
        return {}

    horizon = 60  # measure performance over 60 days after re-entry

    strategies = {
        'vix_below_30': {'desc': 'Re-enter when VIX < 30'},
        'vix_below_25': {'desc': 'Re-enter when VIX < 25'},
        'vix_below_20': {'desc': 'Re-enter when VIX < 20'},
        'wait_5d': {'desc': 'Re-enter 5 days after peak'},
        'wait_10d': {'desc': 'Re-enter 10 days after peak'},
        'wait_20d': {'desc': 'Re-enter 20 days after peak'},
        'wait_30d': {'desc': 'Re-enter 30 days after peak'},
        'gradual_10d': {'desc': 'Gradual: 10% per day starting peak+5'},
    }

    for key in strategies:
        strategies[key]['returns_60d'] = []
        strategies[key]['mdds'] = []
        strategies[key]['wait_days'] = []

    for e in high_events:
        peak_idx = e['peak_idx']
        if peak_idx + 90 + horizon >= n:
            continue  # not enough future data

        # ── Strategy a: VIX drops below 30 ──
        entry_idx = None
        for j in range(peak_idx, min(peak_idx + 252, n)):
            if vix[j] < 30:
                entry_idx = j
                break
        if entry_idx and entry_idx + horizon < n:
            ret_60 = np.prod(1 + spy_ret[entry_idx:entry_idx + horizon]) - 1
            cum = np.cumprod(1 + spy_ret[entry_idx:entry_idx + horizon])
            mdd = np.min(cum / np.maximum.accumulate(cum)) - 1
            strategies['vix_below_30']['returns_60d'].append(ret_60)
            strategies['vix_below_30']['mdds'].append(mdd)
            strategies['vix_below_30']['wait_days'].append(entry_idx - peak_idx)

        # ── Strategy b: VIX drops below 25 ──
        entry_idx = None
        for j in range(peak_idx, min(peak_idx + 252, n)):
            if vix[j] < 25:
                entry_idx = j
                break
        if entry_idx and entry_idx + horizon < n:
            ret_60 = np.prod(1 + spy_ret[entry_idx:entry_idx + horizon]) - 1
            cum = np.cumprod(1 + spy_ret[entry_idx:entry_idx + horizon])
            mdd = np.min(cum / np.maximum.accumulate(cum)) - 1
            strategies['vix_below_25']['returns_60d'].append(ret_60)
            strategies['vix_below_25']['mdds'].append(mdd)
            strategies['vix_below_25']['wait_days'].append(entry_idx - peak_idx)

        # ── Strategy c: VIX drops below 20 ──
        entry_idx = None
        for j in range(peak_idx, min(peak_idx + 252, n)):
            if vix[j] < 20:
                entry_idx = j
                break
        if entry_idx and entry_idx + horizon < n:
            ret_60 = np.prod(1 + spy_ret[entry_idx:entry_idx + horizon]) - 1
            cum = np.cumprod(1 + spy_ret[entry_idx:entry_idx + horizon])
            mdd = np.min(cum / np.maximum.accumulate(cum)) - 1
            strategies['vix_below_20']['returns_60d'].append(ret_60)
            strategies['vix_below_20']['mdds'].append(mdd)
            strategies['vix_below_20']['wait_days'].append(entry_idx - peak_idx)

        # ── Strategies d: Wait N days after peak ──
        for wait_n, key in [(5, 'wait_5d'), (10, 'wait_10d'),
                            (20, 'wait_20d'), (30, 'wait_30d')]:
            entry_idx = peak_idx + wait_n
            if entry_idx + horizon < n:
                ret_60 = np.prod(1 + spy_ret[entry_idx:entry_idx + horizon]) - 1
                cum = np.cumprod(1 + spy_ret[entry_idx:entry_idx + horizon])
                mdd = np.min(cum / np.maximum.accumulate(cum)) - 1
                strategies[key]['returns_60d'].append(ret_60)
                strategies[key]['mdds'].append(mdd)
                strategies[key]['wait_days'].append(wait_n)

        # ── Strategy e: Gradual re-entry (10% per day for 10 days from peak+5) ──
        start = peak_idx + 5
        if start + 10 + horizon < n:
            # Weighted average of returns from different entry points
            # Day peak+5: 10% exposure, peak+6: 20%, ... peak+14: 100%
            weighted_returns = np.zeros(horizon)
            for day_offset in range(10):
                entry = start + day_offset
                weight = (day_offset + 1) / 10.0  # 0.1 to 1.0
                if entry + horizon < n:
                    weighted_returns += weight * spy_ret[entry:entry + horizon]
            # Normalize: average weight = 0.55
            avg_weight = 0.55
            daily_ret = weighted_returns / (10 * avg_weight)
            ret_60 = np.prod(1 + daily_ret) - 1
            cum = np.cumprod(1 + daily_ret)
            mdd = np.min(cum / np.maximum.accumulate(cum)) - 1
            strategies['gradual_10d']['returns_60d'].append(ret_60)
            strategies['gradual_10d']['mdds'].append(mdd)
            strategies['gradual_10d']['wait_days'].append(10)

    # ── Summarize ──
    print(f"\n  {'Strategy':<30} {'N':>4} {'Mean Ret 60d':>14} {'Med Ret':>10} "
          f"{'Mean MDD':>10} {'Avg Wait':>10}")
    print(f"  {'-'*80}")

    results = {}
    for key, s in strategies.items():
        rets = s['returns_60d']
        mdds = s['mdds']
        waits = s['wait_days']
        if rets:
            mean_ret = np.mean(rets)
            med_ret = np.median(rets)
            mean_mdd = np.mean(mdds)
            avg_wait = np.mean(waits)
            # Win rate (positive 60d return)
            win_rate = np.mean(np.array(rets) > 0)
            print(f"  {s['desc']:<30} {len(rets):>4} {mean_ret:>14.2%} {med_ret:>10.2%} "
                  f"{mean_mdd:>10.2%} {avg_wait:>10.1f}d")
            results[key] = {
                'description': s['desc'],
                'n_events': len(rets),
                'mean_return_60d': float(mean_ret),
                'median_return_60d': float(med_ret),
                'mean_mdd': float(mean_mdd),
                'avg_wait_days': float(avg_wait),
                'win_rate': float(win_rate),
                'std_return': float(np.std(rets)),
            }

    # ── Best strategy ──
    if results:
        # Risk-adjusted: return / abs(mdd)
        print(f"\n  --- Risk-Adjusted Ranking (Return / |MDD|) ---")
        ranked = []
        for key, r in results.items():
            if r['mean_mdd'] != 0:
                risk_adj = r['mean_return_60d'] / abs(r['mean_mdd'])
            else:
                risk_adj = 0
            ranked.append((key, risk_adj, r['mean_return_60d'], r['mean_mdd']))
            results[key]['risk_adjusted'] = float(risk_adj)

        ranked.sort(key=lambda x: x[1], reverse=True)
        for i, (key, ra, ret, mdd) in enumerate(ranked):
            print(f"  {i+1}. {results[key]['description']:<30} "
                  f"RA={ra:.3f}  Ret={ret:.2%}  MDD={mdd:.2%}")

    # ── Statistical tests between strategies ──
    if 'vix_below_30' in results and 'wait_20d' in results:
        rets_30 = strategies['vix_below_30']['returns_60d']
        rets_w20 = strategies['wait_20d']['returns_60d']
        min_n = min(len(rets_30), len(rets_w20))
        if min_n >= 5:
            t_s, t_p = stats.ttest_ind(rets_30[:min_n], rets_w20[:min_n], equal_var=False)
            print(f"\n  VIX<30 vs Wait20d: t={t_s:.3f}, p={t_p:.4f}")
            results['stat_test_30_vs_w20'] = {
                't_stat': float(t_s), 'p_value': float(t_p)
            }

    return results


# ═══════════════════════════════════════════════════════════════════════
# PART 5: Half-life by era — structural change analysis
# ═══════════════════════════════════════════════════════════════════════
def analyze_halflife_by_era(data):
    """
    Has VIX mean-reversion speed changed over time?
    Use rolling AR(1) on VIX to estimate half-life by era.
    """
    print(f"\n{'='*60}")
    print("PART 5: Half-Life by Era — Structural Change Analysis")
    print(f"{'='*60}")

    vix = data['vix_close']
    log_vix = np.log(vix)

    # AR(1) on log(VIX): log(VIX_t) = c + rho * log(VIX_{t-1}) + e
    # Half-life = -log(2) / log(rho)

    # Define eras
    eras = {
        'Pre-GFC (2006-2007)': ('2006-01-01', '2007-12-31'),
        'GFC (2008-2009)': ('2008-01-01', '2009-12-31'),
        'Recovery (2010-2012)': ('2010-01-01', '2012-12-31'),
        'Low Vol (2013-2017)': ('2013-01-01', '2017-12-31'),
        'Vol Return (2018-2019)': ('2018-01-01', '2019-12-31'),
        'COVID (2020)': ('2020-01-01', '2020-12-31'),
        'Post-COVID (2021-2022)': ('2021-01-01', '2022-12-31'),
        'Normalization (2023-2024)': ('2023-01-01', '2024-12-31'),
        'Current (2025-2026)': ('2025-01-01', '2026-12-31'),
    }

    results = {}
    print(f"\n  {'Era':<30} {'N':>5} {'rho':>8} {'Half-Life':>12} {'VIX Mean':>10} {'VIX Std':>10}")
    print(f"  {'-'*80}")

    for era_name, (start, end) in eras.items():
        mask = (vix.index >= start) & (vix.index <= end)
        sub = log_vix[mask].dropna()
        if len(sub) < 30:
            continue

        y = sub.values[1:]
        x = sub.values[:-1]
        slope, intercept, r_val, p_val, se = stats.linregress(x, y)
        rho = slope

        if 0 < rho < 1:
            hl = -np.log(2) / np.log(rho)
        else:
            hl = np.nan

        vix_sub = vix[mask]
        vix_mean = float(vix_sub.mean())
        vix_std = float(vix_sub.std())

        print(f"  {era_name:<30} {len(sub):>5} {rho:>8.4f} {hl:>12.1f}d {vix_mean:>10.1f} {vix_std:>10.1f}")

        results[era_name] = {
            'n': int(len(sub)),
            'rho': float(rho),
            'half_life': float(hl) if not np.isnan(hl) else None,
            'vix_mean': float(vix_mean),
            'vix_std': float(vix_std),
        }

    # ── Rolling half-life (252-day window) ──
    print(f"\n--- Rolling Half-Life (252-day window) ---")
    window = 252
    rolling_hl = []
    rolling_dates = []
    for i in range(window, len(log_vix)):
        sub = log_vix.values[i - window:i]
        y = sub[1:]
        x = sub[:-1]
        slope, _, _, _, _ = stats.linregress(x, y)
        if 0 < slope < 1:
            hl = -np.log(2) / np.log(slope)
            rolling_hl.append(hl)
            rolling_dates.append(str(vix.index[i].date()))

    if rolling_hl:
        hl_arr = np.array(rolling_hl)
        print(f"  Mean rolling HL: {np.mean(hl_arr):.1f} days")
        print(f"  Std: {np.std(hl_arr):.1f}")
        print(f"  Min: {np.min(hl_arr):.1f} ({rolling_dates[np.argmin(hl_arr)]})")
        print(f"  Max: {np.max(hl_arr):.1f} ({rolling_dates[np.argmax(hl_arr)]})")

        # Trend test: is half-life getting faster or slower?
        time_idx = np.arange(len(hl_arr))
        slope, intercept, r_val, p_val, se = stats.linregress(time_idx, hl_arr)
        print(f"\n  Linear trend in half-life: {slope*252:.2f} days/year (p={p_val:.4f})")
        if p_val < 0.05:
            direction = "accelerating (faster reversion)" if slope < 0 else "decelerating (slower reversion)"
            print(f"  Trend is significant: VIX mean-reversion is {direction}")
        else:
            print(f"  No significant trend in mean-reversion speed")

        results['rolling_summary'] = {
            'mean_hl': float(np.mean(hl_arr)),
            'std_hl': float(np.std(hl_arr)),
            'min_hl': float(np.min(hl_arr)),
            'max_hl': float(np.max(hl_arr)),
            'trend_slope_per_year': float(slope * 252),
            'trend_p_value': float(p_val),
        }

    return results


# ═══════════════════════════════════════════════════════════════════════
# PART 6: Additional — Reversion speed conditional on VIX level
# ═══════════════════════════════════════════════════════════════════════
def analyze_conditional_reversion(events, data):
    """
    Does the speed of reversion depend on how high VIX went?
    Group events by peak VIX level and compare reversion characteristics.
    """
    print(f"\n{'='*60}")
    print("PART 6: Conditional Reversion — Speed by Peak VIX Level")
    print(f"{'='*60}")

    brackets = [
        ('25-30', 25, 30),
        ('30-40', 30, 40),
        ('40-50', 40, 50),
        ('50+', 50, 200),
    ]

    results = {}
    print(f"\n  {'Bracket':<12} {'N':>4} {'Med Peak':>10} {'Med t→20':>10} "
          f"{'Med t→15':>10} {'Avg SPY cum':>12}")

    spy_ret = data['spy_ret'].values

    for name, lo, hi in brackets:
        subset = [e for e in events if lo <= e['peak_vix'] < hi]
        if not subset:
            continue

        med_peak = np.median([e['peak_vix'] for e in subset])
        t20 = [e['time_to_20'] for e in subset if e['time_to_20'] is not None]
        t15 = [e['time_to_15'] for e in subset if e['time_to_15'] is not None]

        # SPY cumulative return during reversion
        cum_rets = []
        for e in subset:
            if e['time_to_20'] is not None:
                start = e['peak_idx']
                end = min(start + e['time_to_20'], len(spy_ret))
                cum_rets.append(float(np.sum(spy_ret[start:end])))

        med_t20 = np.median(t20) if t20 else None
        med_t15 = np.median(t15) if t15 else None
        avg_cum = np.mean(cum_rets) if cum_rets else None

        print(f"  {name:<12} {len(subset):>4} {med_peak:>10.1f} "
              f"{med_t20 if med_t20 else 'N/A':>10} "
              f"{med_t15 if med_t15 else 'N/A':>10} "
              f"{avg_cum:>12.2%}" if avg_cum else f"  {name:<12} {len(subset):>4}")

        results[name] = {
            'n': len(subset),
            'median_peak': float(med_peak),
            'median_time_to_20': float(med_t20) if med_t20 is not None else None,
            'median_time_to_15': float(med_t15) if med_t15 is not None else None,
            'avg_spy_cum_return': float(avg_cum) if avg_cum is not None else None,
        }

    return results


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════
def main():
    data = download_data()

    # Part 1: Spike events
    events = identify_spike_events(data)

    # Part 2: Distribution & half-life
    dist_results = analyze_reversion_distribution(events, data)

    # Part 3: SPY returns during reversion
    spy_results = analyze_spy_during_reversion(events, data)

    # Part 4: Re-entry strategies
    reentry_results = analyze_reentry_strategies(events, data)

    # Part 5: Half-life by era
    era_results = analyze_halflife_by_era(data)

    # Part 6: Conditional reversion
    cond_results = analyze_conditional_reversion(events, data)

    # ── Summary ──
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    print(f"\n1. VIX spikes (>{SPIKE_THRESHOLD}): {len(events)} episodes since 2006")
    if dist_results['reversion_to_20']['median']:
        print(f"2. Median reversion to <20: {dist_results['reversion_to_20']['median']:.0f} trading days")
    if dist_results['half_life']['half_life_days']:
        print(f"3. Exponential half-life: {dist_results['half_life']['half_life_days']:.1f} days")
    print(f"4. SPY reversion-phase Sharpe: {spy_results['reversion_sharpe']:.3f} "
          f"vs non-reversion: {spy_results['non_reversion_sharpe']:.3f}")
    if reentry_results:
        best_key = max(
            [k for k in reentry_results if k != 'stat_test_30_vs_w20'],
            key=lambda k: reentry_results[k].get('risk_adjusted', 0)
        )
        print(f"5. Best re-entry: {reentry_results[best_key]['description']} "
              f"(RA={reentry_results[best_key].get('risk_adjusted', 0):.3f})")

    # ── Save results ──
    full_results = {
        'experiment_id': 'K658',
        'title': 'VIX Mean-Reversion Speed and Strategy Re-Entry Implications',
        'timestamp': datetime.now().isoformat(),
        'data_source': 'yfinance (SPY, ^VIX)',
        'data_period': f'{START_DATE} to {END_DATE}',
        'n_trading_days': int(len(data)),
        'type': 'empirical',
        'prior_knowledge': ['K652', 'K656', 'T20', 'T39', 'P30', 'N182'],
        'references': [
            'Whaley (2000) JPC',
            'Bekaert & Hoerova (2014) JoE',
            'Todorov & Tauchen (2011) JFE',
            'Simon & Wiggins (2001) JFQA',
        ],
        'spike_events': events,
        'n_events': len(events),
        'reversion_distribution': dist_results,
        'spy_during_reversion': spy_results,
        'reentry_strategies': reentry_results,
        'halflife_by_era': era_results,
        'conditional_reversion': cond_results,
    }

    with open(RESULTS_FILE, 'w') as f:
        json.dump(full_results, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_FILE}")


if __name__ == '__main__':
    main()
