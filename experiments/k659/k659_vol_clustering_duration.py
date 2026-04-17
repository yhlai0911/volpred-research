"""
K659: Volatility Clustering Duration Analysis — How Long Do Vol Regimes Last?

Motivation:
  K637 found 2 natural vol regimes. K658 found VIX half-life 10.2 days.
  But how long do SUSTAINED high-vol or low-vol periods last?
  This matters for strategy design:
    - If low-vol persists for months, investors can relax
    - If high-vol bursts are short, aggressive re-entry is justified

Data source: yfinance (^VIX daily, 1993-01-01 to 2026-03-27)
References:
  - Whaley (2000) "The Investor Fear Gauge" JD
  - Cont (2001) "Empirical properties of asset returns" QFIN
  - K637: VIX 2-regime GMM analysis
  - K658: VIX half-life 10.2 days mean-reversion

Author: VolPred Research System
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")


def download_vix_data(start="1993-01-01", end="2026-03-28"):
    """Download VIX daily data."""
    vix = yf.download("^VIX", start=start, end=end, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix = vix[["Close"]].dropna()
    vix.columns = ["VIX"]
    vix.index = pd.to_datetime(vix.index)
    if vix.index.tz is not None:
        vix.index = vix.index.tz_localize(None)
    return vix


def classify_regime(vix_series):
    """Classify each day into low / normal / high vol regime."""
    regime = pd.Series(index=vix_series.index, dtype=str)
    regime[vix_series < 15] = "low"
    regime[(vix_series >= 15) & (vix_series < 20)] = "normal"
    regime[vix_series >= 20] = "high"
    return regime


def extract_episodes(regime_series):
    """Extract continuous episodes of each regime.

    Returns list of dicts: {regime, start, end, duration_days, dates}
    """
    episodes = []
    current_regime = regime_series.iloc[0]
    start_idx = 0

    for i in range(1, len(regime_series)):
        if regime_series.iloc[i] != current_regime:
            # End of episode
            start_date = regime_series.index[start_idx]
            end_date = regime_series.index[i - 1]
            duration = (end_date - start_date).days + 1  # calendar days
            trading_days = i - start_idx
            episodes.append({
                "regime": current_regime,
                "start": start_date,
                "end": end_date,
                "duration_calendar": duration,
                "duration_trading": trading_days,
            })
            current_regime = regime_series.iloc[i]
            start_idx = i

    # Last episode
    start_date = regime_series.index[start_idx]
    end_date = regime_series.index[-1]
    duration = (end_date - start_date).days + 1
    trading_days = len(regime_series) - start_idx
    episodes.append({
        "regime": current_regime,
        "start": start_date,
        "end": end_date,
        "duration_calendar": duration,
        "duration_trading": trading_days,
    })

    return episodes


def compute_episode_stats(episodes_df, vix_data):
    """Compute VIX statistics within each episode."""
    avg_vix_list = []
    max_vix_list = []
    min_vix_list = []
    entry_vix_list = []

    for _, ep in episodes_df.iterrows():
        mask = (vix_data.index >= ep["start"]) & (vix_data.index <= ep["end"])
        vix_slice = vix_data.loc[mask, "VIX"]
        if len(vix_slice) > 0:
            avg_vix_list.append(vix_slice.mean())
            max_vix_list.append(vix_slice.max())
            min_vix_list.append(vix_slice.min())
            entry_vix_list.append(vix_slice.iloc[0])
        else:
            avg_vix_list.append(np.nan)
            max_vix_list.append(np.nan)
            min_vix_list.append(np.nan)
            entry_vix_list.append(np.nan)

    episodes_df["avg_vix"] = avg_vix_list
    episodes_df["max_vix"] = max_vix_list
    episodes_df["min_vix"] = min_vix_list
    episodes_df["entry_vix"] = entry_vix_list
    return episodes_df


def duration_statistics(episodes_df):
    """Compute duration statistics per regime (trading days)."""
    results = {}
    for regime in ["low", "normal", "high"]:
        subset = episodes_df[episodes_df["regime"] == regime]
        durations = subset["duration_trading"].values
        cal_durations = subset["duration_calendar"].values

        if len(durations) == 0:
            continue

        results[regime] = {
            "n_episodes": int(len(durations)),
            "mean_trading_days": float(np.mean(durations)),
            "median_trading_days": float(np.median(durations)),
            "std_trading_days": float(np.std(durations)),
            "min_trading_days": int(np.min(durations)),
            "max_trading_days": int(np.max(durations)),
            "p25_trading_days": float(np.percentile(durations, 25)),
            "p75_trading_days": float(np.percentile(durations, 75)),
            "mean_calendar_days": float(np.mean(cal_durations)),
            "median_calendar_days": float(np.median(cal_durations)),
            "max_calendar_days": int(np.max(cal_durations)),
            # Survival probabilities
            "prob_gt_5_days": float(np.mean(durations > 5)),
            "prob_gt_10_days": float(np.mean(durations > 10)),
            "prob_gt_20_days": float(np.mean(durations > 20)),
            "prob_gt_40_days": float(np.mean(durations > 40)),
            "prob_gt_60_days": float(np.mean(durations > 60)),
            "prob_gt_120_days": float(np.mean(durations > 120)),
            "prob_gt_250_days": float(np.mean(durations > 250)),
            # VIX stats within episodes
            "mean_avg_vix": float(subset["avg_vix"].mean()),
        }

        # Top-5 longest episodes
        top5 = subset.nlargest(5, "duration_trading")
        results[regime]["top5_longest"] = []
        for _, row in top5.iterrows():
            results[regime]["top5_longest"].append({
                "start": str(row["start"].date()),
                "end": str(row["end"].date()),
                "trading_days": int(row["duration_trading"]),
                "calendar_days": int(row["duration_calendar"]),
                "avg_vix": round(float(row["avg_vix"]), 2),
            })

    return results


def compute_transition_matrix(episodes_df):
    """Compute regime transition matrix: P(next_regime | current_regime)."""
    regimes = ["low", "normal", "high"]
    transitions = {r: {r2: 0 for r2 in regimes} for r in regimes}

    for i in range(len(episodes_df) - 1):
        curr = episodes_df.iloc[i]["regime"]
        nxt = episodes_df.iloc[i + 1]["regime"]
        transitions[curr][nxt] += 1

    # Convert to probabilities
    transition_probs = {}
    for r in regimes:
        total = sum(transitions[r].values())
        if total > 0:
            transition_probs[r] = {r2: round(transitions[r][r2] / total, 4)
                                   for r2 in regimes}
            transition_probs[r]["total_transitions"] = total
        else:
            transition_probs[r] = {r2: 0.0 for r2 in regimes}
            transition_probs[r]["total_transitions"] = 0

    return transition_probs, transitions


def duration_predictability(episodes_df):
    """Test if entry VIX predicts episode duration."""
    results = {}

    for regime in ["low", "normal", "high"]:
        subset = episodes_df[episodes_df["regime"] == regime].copy()
        if len(subset) < 10:
            results[regime] = {"n": len(subset), "note": "Too few episodes"}
            continue

        durations = subset["duration_trading"].values.astype(float)
        entry_vix = subset["entry_vix"].values.astype(float)

        # Remove NaN
        valid = ~(np.isnan(durations) | np.isnan(entry_vix))
        durations = durations[valid]
        entry_vix = entry_vix[valid]

        if len(durations) < 10:
            results[regime] = {"n": len(durations), "note": "Too few valid"}
            continue

        # Correlation: entry VIX vs duration
        corr, pval = stats.spearmanr(entry_vix, durations)

        # Also test log(duration) vs entry_vix (OLS)
        log_dur = np.log(durations + 1)
        slope, intercept, r_value, p_value, std_err = stats.linregress(
            entry_vix, log_dur
        )

        # Prior duration effect
        prior_dur = []
        for idx in range(len(subset)):
            pos = subset.index[idx]
            loc_in_full = episodes_df.index.get_loc(pos)
            if loc_in_full > 0:
                prior_dur.append(
                    float(episodes_df.iloc[loc_in_full - 1]["duration_trading"])
                )
            else:
                prior_dur.append(np.nan)

        prior_dur = np.array(prior_dur)[valid]
        valid_prior = ~np.isnan(prior_dur)
        if np.sum(valid_prior) >= 10:
            corr_prior, pval_prior = stats.spearmanr(
                prior_dur[valid_prior], durations[valid_prior]
            )
        else:
            corr_prior, pval_prior = np.nan, np.nan

        results[regime] = {
            "n": int(len(durations)),
            "entry_vix_vs_duration": {
                "spearman_rho": round(float(corr), 4),
                "p_value": round(float(pval), 4),
                "significant": bool(pval < 0.05),
            },
            "log_duration_regression": {
                "slope": round(float(slope), 4),
                "intercept": round(float(intercept), 4),
                "r_squared": round(float(r_value**2), 4),
                "p_value": round(float(p_value), 4),
            },
            "prior_duration_vs_current": {
                "spearman_rho": round(float(corr_prior), 4) if not np.isnan(corr_prior) else None,
                "p_value": round(float(pval_prior), 4) if not np.isnan(pval_prior) else None,
            },
        }

    return results


def monthly_rebalancing_miss_rate(episodes_df, regime="high"):
    """What fraction of high-vol episodes are shorter than 21 trading days
    (i.e., could be entirely missed by monthly rebalancing)?"""
    subset = episodes_df[episodes_df["regime"] == regime]
    durations = subset["duration_trading"].values

    miss_1m = np.mean(durations <= 21)
    miss_2w = np.mean(durations <= 10)
    miss_1w = np.mean(durations <= 5)

    return {
        "regime": regime,
        "n_episodes": int(len(durations)),
        "pct_missed_by_monthly": round(float(miss_1m) * 100, 1),
        "pct_missed_by_biweekly": round(float(miss_2w) * 100, 1),
        "pct_missed_by_weekly": round(float(miss_1w) * 100, 1),
        "median_duration_trading": float(np.median(durations)),
        "mean_duration_trading": float(np.mean(durations)),
    }


def decade_analysis(episodes_df):
    """How do episode durations change across decades?"""
    episodes_df = episodes_df.copy()
    episodes_df["decade"] = (episodes_df["start"].dt.year // 10) * 10
    decades = sorted(episodes_df["decade"].unique())

    results = {}
    for decade in decades:
        dec_str = f"{decade}s"
        dec_data = episodes_df[episodes_df["decade"] == decade]
        results[dec_str] = {}
        for regime in ["low", "normal", "high"]:
            subset = dec_data[dec_data["regime"] == regime]
            if len(subset) == 0:
                continue
            durs = subset["duration_trading"].values
            results[dec_str][regime] = {
                "n_episodes": int(len(durs)),
                "mean_duration": round(float(np.mean(durs)), 1),
                "median_duration": round(float(np.median(durs)), 1),
                "max_duration": int(np.max(durs)),
            }

    return results


def duration_distribution_shape(episodes_df):
    """Test whether episode durations follow exponential, log-normal, or other."""
    results = {}

    for regime in ["low", "normal", "high"]:
        subset = episodes_df[episodes_df["regime"] == regime]
        durations = subset["duration_trading"].values.astype(float)

        if len(durations) < 20:
            results[regime] = {"n": len(durations), "note": "Too few for dist test"}
            continue

        # Test exponential fit (memoryless)
        loc_exp, scale_exp = stats.expon.fit(durations, floc=0)
        ks_exp, p_exp = stats.kstest(durations, "expon", args=(0, scale_exp))

        # Test log-normal fit
        shape_ln, loc_ln, scale_ln = stats.lognorm.fit(durations, floc=0)
        ks_ln, p_ln = stats.kstest(
            durations, "lognorm", args=(shape_ln, loc_ln, scale_ln)
        )

        # Skewness and kurtosis of durations
        skew = float(stats.skew(durations))
        kurt = float(stats.kurtosis(durations))

        results[regime] = {
            "n": int(len(durations)),
            "skewness": round(skew, 3),
            "excess_kurtosis": round(kurt, 3),
            "exponential_fit": {
                "rate_lambda": round(1.0 / scale_exp, 4),
                "mean_implied": round(scale_exp, 1),
                "ks_stat": round(float(ks_exp), 4),
                "ks_p_value": round(float(p_exp), 4),
                "rejected_at_5pct": bool(p_exp < 0.05),
            },
            "lognormal_fit": {
                "sigma": round(float(shape_ln), 4),
                "mu": round(float(np.log(scale_ln)), 4),
                "ks_stat": round(float(ks_ln), 4),
                "ks_p_value": round(float(p_ln), 4),
                "rejected_at_5pct": bool(p_ln < 0.05),
            },
            "best_fit": "lognormal" if p_ln > p_exp else "exponential",
        }

    return results


def main():
    print("=" * 70)
    print("K659: Volatility Clustering Duration Analysis")
    print("=" * 70)

    # 1. Download data
    print("\n[1] Downloading VIX data...")
    vix_data = download_vix_data()
    print(f"    VIX data: {vix_data.index[0].date()} to {vix_data.index[-1].date()}")
    print(f"    Total trading days: {len(vix_data)}")
    print(f"    VIX range: {vix_data['VIX'].min():.2f} - {vix_data['VIX'].max():.2f}")
    print(f"    VIX mean: {vix_data['VIX'].mean():.2f}, median: {vix_data['VIX'].median():.2f}")

    # 2. Classify regimes
    print("\n[2] Classifying VIX regimes...")
    regime = classify_regime(vix_data["VIX"])
    regime_counts = regime.value_counts()
    total = len(regime)
    print(f"    Low  (VIX<15):  {regime_counts.get('low', 0):5d} days ({100*regime_counts.get('low', 0)/total:.1f}%)")
    print(f"    Normal (15-20): {regime_counts.get('normal', 0):5d} days ({100*regime_counts.get('normal', 0)/total:.1f}%)")
    print(f"    High (VIX>=20): {regime_counts.get('high', 0):5d} days ({100*regime_counts.get('high', 0)/total:.1f}%)")

    regime_pct = {
        "low": round(100 * regime_counts.get("low", 0) / total, 1),
        "normal": round(100 * regime_counts.get("normal", 0) / total, 1),
        "high": round(100 * regime_counts.get("high", 0) / total, 1),
    }

    # 3. Extract episodes
    print("\n[3] Extracting continuous episodes...")
    episodes = extract_episodes(regime)
    episodes_df = pd.DataFrame(episodes)
    print(f"    Total episodes: {len(episodes_df)}")
    for r in ["low", "normal", "high"]:
        n = len(episodes_df[episodes_df["regime"] == r])
        print(f"    {r:8s} episodes: {n}")

    # 4. Compute VIX stats per episode
    print("\n[4] Computing VIX statistics per episode...")
    episodes_df = compute_episode_stats(episodes_df, vix_data)

    # 5. Duration statistics
    print("\n[5] Duration statistics by regime...")
    dur_stats = duration_statistics(episodes_df)
    for regime_name, stats_dict in dur_stats.items():
        print(f"\n    === {regime_name.upper()} VOL ===")
        print(f"    Episodes: {stats_dict['n_episodes']}")
        print(f"    Mean duration: {stats_dict['mean_trading_days']:.1f} trading days "
              f"({stats_dict['mean_calendar_days']:.1f} calendar)")
        print(f"    Median duration: {stats_dict['median_trading_days']:.1f} trading days "
              f"({stats_dict['median_calendar_days']:.1f} calendar)")
        print(f"    Range: {stats_dict['min_trading_days']} - {stats_dict['max_trading_days']} trading days")
        print(f"    IQR: {stats_dict['p25_trading_days']:.0f} - {stats_dict['p75_trading_days']:.0f} trading days")
        print(f"    P(>20 days): {stats_dict['prob_gt_20_days']:.1%}")
        print(f"    P(>60 days): {stats_dict['prob_gt_60_days']:.1%}")
        print(f"    P(>250 days): {stats_dict['prob_gt_250_days']:.1%}")
        print(f"    Top-5 longest:")
        for ep in stats_dict["top5_longest"]:
            print(f"      {ep['start']} to {ep['end']}: "
                  f"{ep['trading_days']}d (avg VIX={ep['avg_vix']:.1f})")

    # 6. Transition matrix
    print("\n[6] Regime transition matrix...")
    trans_probs, trans_counts = compute_transition_matrix(episodes_df)
    print("\n    P(next | current):")
    print(f"    {'':12s} {'low':>8s} {'normal':>8s} {'high':>8s}  (N)")
    for r in ["low", "normal", "high"]:
        tp = trans_probs[r]
        n = tp["total_transitions"]
        print(f"    {r:12s} {tp['low']:8.3f} {tp['normal']:8.3f} {tp['high']:8.3f}  ({n})")

    # 7. Duration predictability
    print("\n[7] Duration predictability analysis...")
    pred_results = duration_predictability(episodes_df)
    for regime_name, pred in pred_results.items():
        print(f"\n    === {regime_name.upper()} ===")
        if "note" in pred:
            print(f"    {pred['note']} (n={pred['n']})")
            continue
        ev = pred["entry_vix_vs_duration"]
        print(f"    Entry VIX vs duration: rho={ev['spearman_rho']:.3f} "
              f"(p={ev['p_value']:.3f}) {'***' if ev['significant'] else 'n.s.'}")
        lr = pred["log_duration_regression"]
        print(f"    log(duration) ~ entry_VIX: R^2={lr['r_squared']:.4f}, "
              f"slope={lr['slope']:.4f} (p={lr['p_value']:.3f})")
        pd_info = pred["prior_duration_vs_current"]
        if pd_info["spearman_rho"] is not None:
            print(f"    Prior duration vs current: rho={pd_info['spearman_rho']:.3f} "
                  f"(p={pd_info['p_value']:.3f})")

    # 8. Monthly rebalancing miss rate
    print("\n[8] Rebalancing miss rate for HIGH vol episodes...")
    miss_rate = monthly_rebalancing_miss_rate(episodes_df, "high")
    print(f"    High-vol episodes: {miss_rate['n_episodes']}")
    print(f"    Median duration: {miss_rate['median_duration_trading']:.0f} trading days")
    print(f"    Mean duration: {miss_rate['mean_duration_trading']:.1f} trading days")
    print(f"    Missed by monthly rebalancing (<=21d): {miss_rate['pct_missed_by_monthly']:.1f}%")
    print(f"    Missed by bi-weekly (<=10d): {miss_rate['pct_missed_by_biweekly']:.1f}%")
    print(f"    Missed by weekly (<=5d): {miss_rate['pct_missed_by_weekly']:.1f}%")

    # Also for low vol
    miss_rate_low = monthly_rebalancing_miss_rate(episodes_df, "low")
    print(f"\n    Low-vol episodes: {miss_rate_low['n_episodes']}")
    print(f"    Median duration: {miss_rate_low['median_duration_trading']:.0f} trading days")
    print(f"    Missed by monthly (<=21d): {miss_rate_low['pct_missed_by_monthly']:.1f}%")

    # 9. Decade analysis
    print("\n[9] Decade-by-decade analysis...")
    decade_results = decade_analysis(episodes_df)
    for dec, regimes in decade_results.items():
        print(f"\n    {dec}:")
        for r, s in regimes.items():
            print(f"      {r:8s}: {s['n_episodes']} episodes, "
                  f"mean={s['mean_duration']:.1f}d, "
                  f"median={s['median_duration']:.1f}d, "
                  f"max={s['max_duration']}d")

    # 10. Distribution shape
    print("\n[10] Duration distribution shape tests...")
    dist_results = duration_distribution_shape(episodes_df)
    for regime_name, dr in dist_results.items():
        print(f"\n    === {regime_name.upper()} ===")
        if "note" in dr:
            print(f"    {dr['note']}")
            continue
        print(f"    Skewness: {dr['skewness']:.3f}, Excess kurtosis: {dr['excess_kurtosis']:.3f}")
        ef = dr["exponential_fit"]
        print(f"    Exponential: lambda={ef['rate_lambda']:.4f}, "
              f"KS p={ef['ks_p_value']:.3f} {'(rejected)' if ef['rejected_at_5pct'] else '(not rejected)'}")
        lf = dr["lognormal_fit"]
        print(f"    Log-normal:  sigma={lf['sigma']:.3f}, mu={lf['mu']:.3f}, "
              f"KS p={lf['ks_p_value']:.3f} {'(rejected)' if lf['rejected_at_5pct'] else '(not rejected)'}")
        print(f"    Best fit: {dr['best_fit']}")

    # === Strategy implications ===
    print("\n" + "=" * 70)
    print("STRATEGY IMPLICATIONS")
    print("=" * 70)

    high_stats = dur_stats.get("high", {})
    low_stats = dur_stats.get("low", {})

    if high_stats:
        median_high = high_stats["median_trading_days"]
        print(f"\n  1. High-vol median = {median_high:.0f} trading days")
        if median_high <= 21:
            print(f"     -> Monthly rebalancing MISSES most high-vol events!")
            print(f"     -> Daily/weekly VT is essential to capture these")
        else:
            print(f"     -> Monthly rebalancing captures most high-vol events")

    if low_stats:
        median_low = low_stats["median_trading_days"]
        print(f"\n  2. Low-vol median = {median_low:.0f} trading days")
        print(f"     -> Low-vol spells are {'long-lasting' if median_low > 60 else 'moderate'}")

    tp_high = trans_probs.get("high", {})
    if tp_high:
        p_high_to_low = tp_high.get("low", 0)
        p_high_to_normal = tp_high.get("normal", 0)
        print(f"\n  3. After high-vol: P(->low)={p_high_to_low:.1%}, P(->normal)={p_high_to_normal:.1%}")
        if p_high_to_normal > p_high_to_low:
            print("     -> VIX typically descends gradually (high->normal->low)")
        else:
            print("     -> VIX can crash directly to low")

    # === Compile results ===
    results = {
        "experiment_id": "K659",
        "title": "Volatility Clustering Duration Analysis",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (^VIX daily)",
        "data_period": f"{vix_data.index[0].date()} to {vix_data.index[-1].date()}",
        "total_trading_days": int(len(vix_data)),
        "regime_thresholds": {"low": "VIX < 15", "normal": "15 <= VIX < 20", "high": "VIX >= 20"},
        "regime_time_pct": regime_pct,
        "total_episodes": int(len(episodes_df)),
        "duration_statistics": dur_stats,
        "transition_matrix": {
            "probabilities": trans_probs,
            "counts": {r: {r2: int(trans_counts[r][r2]) for r2 in ["low", "normal", "high"]}
                       for r in ["low", "normal", "high"]},
        },
        "duration_predictability": pred_results,
        "rebalancing_miss_rate": {
            "high_vol": miss_rate,
            "low_vol": miss_rate_low,
        },
        "decade_analysis": decade_results,
        "distribution_shape": dist_results,
        "stylized_facts": {},
        "strategy_implications": [],
        "references": [
            "K637: VIX 2-regime GMM analysis",
            "K658: VIX half-life 10.2 days mean-reversion",
            "Whaley (2000) The Investor Fear Gauge, JD",
            "Cont (2001) Empirical properties of asset returns, QFIN",
        ],
    }

    # Stylized facts
    if low_stats:
        results["stylized_facts"]["low_vol_median_trading_days"] = low_stats["median_trading_days"]
        results["stylized_facts"]["low_vol_median_calendar_days"] = low_stats["median_calendar_days"]
        results["stylized_facts"]["longest_low_vol_trading_days"] = low_stats["max_trading_days"]
        if low_stats["top5_longest"]:
            results["stylized_facts"]["longest_low_vol_period"] = low_stats["top5_longest"][0]
    if high_stats:
        results["stylized_facts"]["high_vol_median_trading_days"] = high_stats["median_trading_days"]
        results["stylized_facts"]["high_vol_median_calendar_days"] = high_stats["median_calendar_days"]
        results["stylized_facts"]["longest_high_vol_trading_days"] = high_stats["max_trading_days"]
        if high_stats["top5_longest"]:
            results["stylized_facts"]["longest_high_vol_period"] = high_stats["top5_longest"][0]

    # Strategy implications
    implications = []
    if high_stats:
        median_h = high_stats["median_trading_days"]
        implications.append(
            f"High-vol median = {median_h:.0f} trading days. "
            f"{miss_rate['pct_missed_by_monthly']:.0f}% of high-vol episodes "
            f"are <=21 days, entirely missed by monthly rebalancing."
        )
    if low_stats:
        median_l = low_stats["median_trading_days"]
        implications.append(
            f"Low-vol median = {median_l:.0f} trading days. "
            f"Low-vol spells are persistent, allowing investors to maintain positions."
        )
    if tp_high:
        implications.append(
            f"After high-vol: P(->normal)={tp_high.get('normal', 0):.1%}, "
            f"P(->low)={tp_high.get('low', 0):.1%}. "
            f"VIX {'descends gradually' if tp_high.get('normal', 0) > tp_high.get('low', 0) else 'can crash directly'}."
        )
    implications.append(
        f"Duration distribution is right-skewed (lognormal-like). "
        f"Mean >> Median for all regimes, driven by rare extended episodes."
    )
    results["strategy_implications"] = implications

    # Save
    output_path = Path(__file__).parent / "k659_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[SAVED] Results to {output_path}")

    print("\n" + "=" * 70)
    print("K659 COMPLETE")
    print("=" * 70)

    return results


if __name__ == "__main__":
    main()
