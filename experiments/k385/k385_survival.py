"""
K385: Drawdown Survival Analysis — How Long Do Drawdowns Last?
=============================================================
[提出: Claude, 執行: Claude]

A formal survival analysis of drawdown episodes, applying Kaplan-Meier
estimators, log-rank tests, hazard rate analysis, and Cox proportional
hazards regression to understand drawdown DURATION dynamics.

Key questions:
1. How long does a typical drawdown last for different strategies?
2. Does VT (Volatility Targeting) shorten drawdown duration?
3. What factors predict faster recovery? (VIX level, drawdown speed, GLD)
4. How does hazard rate change with drawdown depth and duration?

Data: SPY, GLD, VIX daily from yfinance, 2005-2024.
Method: Formal survival analysis (lifelines library).

Drawdown episode definition:
  - Start: portfolio drops >=5% from peak
  - End: portfolio recovers to previous peak
  - Censored if drawdown ongoing at study end
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
import json

# Survival analysis
from lifelines import KaplanMeierFitter, CoxPHFitter
from lifelines.statistics import logrank_test, multivariate_logrank_test
from scipy import stats

# ================================================================
# CONFIG
# ================================================================
DATA_START = "2004-01-01"  # Extra history for VIX context
ANALYSIS_START = "2005-01-03"  # OOS start
ANALYSIS_END = "2024-12-31"
DRAWDOWN_THRESHOLD = 0.05  # 5% drawdown to start episode
VIX_SCALING = 12.0  # 12/VIX rule
TARGET_VOL_ANNUAL = 0.10
MAX_LEVERAGE = 1.5

print("=" * 80)
print("K385: DRAWDOWN SURVIVAL ANALYSIS")
print("How Long Do Drawdowns Last? Does VT Shorten Them?")
print("=" * 80)

# ================================================================
# 1. DATA COLLECTION
# ================================================================
print("\n[1] Downloading data from yfinance...")

spy = yf.download("SPY", start=DATA_START, end=ANALYSIS_END, progress=False)
gld = yf.download("GLD", start=DATA_START, end=ANALYSIS_END, progress=False)
vix = yf.download("^VIX", start=DATA_START, end=ANALYSIS_END, progress=False)

# Handle multi-level columns from yfinance
for df_name, df in [("SPY", spy), ("GLD", gld), ("VIX", vix)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Align dates
common_idx = spy.index.intersection(gld.index).intersection(vix.index)
common_idx = common_idx[common_idx >= ANALYSIS_START]
spy = spy.loc[common_idx]
gld = gld.loc[common_idx]
vix = vix.loc[common_idx]

# Daily returns
spy_ret = spy["Close"].pct_change().dropna()
gld_ret = gld["Close"].pct_change().dropna()
vix_close = vix["Close"]

# Align all
common = spy_ret.index.intersection(gld_ret.index).intersection(vix_close.index)
spy_ret = spy_ret.loc[common]
gld_ret = gld_ret.loc[common]
vix_close = vix_close.loc[common]

print(f"  Period: {common[0].strftime('%Y-%m-%d')} to {common[-1].strftime('%Y-%m-%d')}")
print(f"  Trading days: {len(common)}")

# ================================================================
# 2. BUILD STRATEGY CUMULATIVE RETURNS
# ================================================================
print("\n[2] Building strategy cumulative returns...")

# Strategy 1: SPY Buy & Hold
spy_cum = (1 + spy_ret).cumprod()

# Strategy 2: 50/50 SPY/GLD Buy & Hold (monthly rebalance)
port_ret = 0.5 * spy_ret + 0.5 * gld_ret
port_cum = (1 + port_ret).cumprod()

# Strategy 3: SPY 12/VIX (lagged)
vix_lag = vix_close.shift(1)  # Use previous day VIX
spy_vt_weight = np.minimum(VIX_SCALING / vix_lag, MAX_LEVERAGE)
spy_vt_weight = spy_vt_weight.loc[spy_ret.index].fillna(1.0)
spy_vt_ret = spy_vt_weight * spy_ret
spy_vt_cum = (1 + spy_vt_ret).cumprod()

# Strategy 4: 50/50 SPY/GLD + 12/VIX on both (lagged)
port_vt_ret = spy_vt_weight * 0.5 * spy_ret + spy_vt_weight * 0.5 * gld_ret
port_vt_cum = (1 + port_vt_ret).cumprod()

strategies = {
    "SPY_BH": {"cum": spy_cum, "ret": spy_ret, "label": "SPY Buy & Hold"},
    "5050_BH": {"cum": port_cum, "ret": port_ret, "label": "50/50 SPY/GLD B&H"},
    "SPY_VT": {"cum": spy_vt_cum, "ret": spy_vt_ret, "label": "SPY 12/VIX"},
    "5050_VT": {"cum": port_vt_cum, "ret": port_vt_ret, "label": "50/50 + 12/VIX"},
}

for k, v in strategies.items():
    total_ret = v["cum"].iloc[-1] - 1
    ann_ret = (1 + total_ret) ** (252 / len(v["cum"])) - 1
    ann_vol = v["ret"].std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol
    print(f"  {v['label']:25s}: Total={total_ret*100:.1f}%, Ann={ann_ret*100:.1f}%, Vol={ann_vol*100:.1f}%, Sharpe={sharpe:.2f}")


# ================================================================
# 3. EXTRACT DRAWDOWN EPISODES
# ================================================================
print("\n[3] Extracting drawdown episodes (threshold >= 5%)...")

def extract_drawdown_episodes(cum_returns, threshold=0.05, label=""):
    """
    Extract drawdown episodes from cumulative return series.

    Returns DataFrame with columns:
    - start_date, end_date
    - duration (trading days)
    - max_depth (max drawdown during episode)
    - vix_at_start (VIX level when drawdown began)
    - drawdown_speed (how fast the first 5% drop happened)
    - gld_during (GLD cumulative return during episode)
    - censored (1 if still ongoing at study end, 0 if recovered)
    - strategy (label)
    """
    running_max = cum_returns.cummax()
    drawdown = (cum_returns - running_max) / running_max

    episodes = []
    in_episode = False
    episode_start = None
    episode_start_peak = None

    for i in range(len(drawdown)):
        dd_val = drawdown.iloc[i]

        if not in_episode and dd_val <= -threshold:
            # Episode starts
            in_episode = True
            # Find when the peak was (episode actually started at the peak)
            peak_idx = cum_returns.iloc[:i+1].idxmax()
            episode_start = peak_idx
            episode_start_peak = cum_returns.loc[peak_idx]

        elif in_episode and cum_returns.iloc[i] >= episode_start_peak:
            # Recovery: portfolio back to peak
            end_date = cum_returns.index[i]
            duration = np.busday_count(
                np.datetime64(episode_start, 'D'),
                np.datetime64(end_date, 'D')
            )
            if duration < 1:
                duration = (end_date - episode_start).days

            # Max depth during episode
            ep_dd = drawdown.loc[episode_start:end_date]
            max_depth = ep_dd.min()

            # VIX at start
            try:
                vix_start = float(vix_close.loc[episode_start]) if episode_start in vix_close.index else np.nan
            except:
                vix_start = np.nan

            # Drawdown speed: days from peak to first -5%
            ep_cum = cum_returns.loc[episode_start:end_date]
            first_breach = ep_cum.index[((ep_cum - episode_start_peak) / episode_start_peak) <= -threshold]
            if len(first_breach) > 0:
                speed_days = np.busday_count(
                    np.datetime64(episode_start, 'D'),
                    np.datetime64(first_breach[0], 'D')
                )
                if speed_days < 1:
                    speed_days = (first_breach[0] - episode_start).days
            else:
                speed_days = np.nan

            # GLD performance during episode
            if episode_start in gld_ret.index and end_date in gld_ret.index:
                gld_start_idx = gld_ret.index.get_loc(episode_start)
                gld_end_idx = gld_ret.index.get_loc(end_date)
                gld_during = (1 + gld_ret.iloc[gld_start_idx:gld_end_idx+1]).prod() - 1
            else:
                gld_during = np.nan

            episodes.append({
                "start_date": episode_start,
                "end_date": end_date,
                "duration": int(duration),
                "max_depth": float(max_depth),
                "vix_at_start": float(vix_start) if not np.isnan(vix_start) else None,
                "drawdown_speed_days": int(speed_days) if not np.isnan(speed_days) else None,
                "gld_during": float(gld_during) if not np.isnan(gld_during) else None,
                "censored": 0,
                "strategy": label,
            })

            in_episode = False
            episode_start = None
            episode_start_peak = None

    # Handle censored episode (still in drawdown at study end)
    if in_episode and episode_start is not None:
        end_date = cum_returns.index[-1]
        duration = np.busday_count(
            np.datetime64(episode_start, 'D'),
            np.datetime64(end_date, 'D')
        )
        if duration < 1:
            duration = (end_date - episode_start).days

        ep_dd = drawdown.loc[episode_start:end_date]
        max_depth = ep_dd.min()

        try:
            vix_start = float(vix_close.loc[episode_start]) if episode_start in vix_close.index else np.nan
        except:
            vix_start = np.nan

        ep_cum = cum_returns.loc[episode_start:end_date]
        first_breach = ep_cum.index[((ep_cum - episode_start_peak) / episode_start_peak) <= -threshold]
        if len(first_breach) > 0:
            speed_days = np.busday_count(
                np.datetime64(episode_start, 'D'),
                np.datetime64(first_breach[0], 'D')
            )
            if speed_days < 1:
                speed_days = (first_breach[0] - episode_start).days
        else:
            speed_days = np.nan

        if episode_start in gld_ret.index and end_date in gld_ret.index:
            gld_start_idx = gld_ret.index.get_loc(episode_start)
            gld_end_idx = gld_ret.index.get_loc(end_date)
            gld_during = (1 + gld_ret.iloc[gld_start_idx:gld_end_idx+1]).prod() - 1
        else:
            gld_during = np.nan

        episodes.append({
            "start_date": episode_start,
            "end_date": end_date,
            "duration": int(duration),
            "max_depth": float(max_depth),
            "vix_at_start": float(vix_start) if not np.isnan(vix_start) else None,
            "drawdown_speed_days": int(speed_days) if not np.isnan(speed_days) else None,
            "gld_during": float(gld_during) if not np.isnan(gld_during) else None,
            "censored": 1,  # RIGHT-CENSORED
            "strategy": label,
        })

    return pd.DataFrame(episodes)

# Extract episodes for each strategy
all_episodes = []
for key, strat in strategies.items():
    eps = extract_drawdown_episodes(strat["cum"], threshold=DRAWDOWN_THRESHOLD, label=key)
    all_episodes.append(eps)
    n_complete = (eps["censored"] == 0).sum()
    n_censored = (eps["censored"] == 1).sum()
    print(f"  {strat['label']:25s}: {len(eps)} episodes ({n_complete} complete, {n_censored} censored)")

episodes_df = pd.concat(all_episodes, ignore_index=True)
print(f"\n  Total episodes: {len(episodes_df)}")

# ================================================================
# 4. KAPLAN-MEIER SURVIVAL CURVES
# ================================================================
print("\n[4] Kaplan-Meier Survival Analysis...")
print("    (Probability of STILL being in drawdown after N days)")

kmf = KaplanMeierFitter()

km_results = {}
for key, strat in strategies.items():
    mask = episodes_df["strategy"] == key
    subset = episodes_df[mask]
    if len(subset) < 2:
        print(f"  {strat['label']}: Too few episodes ({len(subset)}), skipping KM")
        continue

    T = subset["duration"].values
    E = (1 - subset["censored"]).values  # Event = recovery (1 = recovered)

    kmf.fit(T, event_observed=E, label=strat["label"])

    # Median survival time
    median_surv = kmf.median_survival_time_

    # Survival at key timepoints
    surv_30 = float(kmf.predict(30))
    surv_60 = float(kmf.predict(60))
    surv_120 = float(kmf.predict(120))
    surv_252 = float(kmf.predict(252))

    km_results[key] = {
        "label": strat["label"],
        "n_episodes": int(len(subset)),
        "median_survival_days": float(median_surv) if not np.isinf(median_surv) else None,
        "mean_duration": float(subset["duration"].mean()),
        "prob_still_in_dd_30d": surv_30,
        "prob_still_in_dd_60d": surv_60,
        "prob_still_in_dd_120d": surv_120,
        "prob_still_in_dd_252d": surv_252,
    }

    print(f"\n  {strat['label']}:")
    print(f"    Episodes: {len(subset)}")
    median_str = f"{median_surv:.0f}" if not np.isinf(median_surv) else "undefined (>50% still in DD)"
    print(f"    Median survival: {median_str} trading days")
    print(f"    Mean duration: {subset['duration'].mean():.0f} days")
    print(f"    P(still in DD after 30d):  {surv_30:.1%}")
    print(f"    P(still in DD after 60d):  {surv_60:.1%}")
    print(f"    P(still in DD after 120d): {surv_120:.1%}")
    print(f"    P(still in DD after 252d): {surv_252:.1%}")

# ================================================================
# 5. LOG-RANK TESTS
# ================================================================
print("\n[5] Log-Rank Tests (pairwise comparisons)...")
print("    H0: survival curves are identical")

logrank_results = {}

comparisons = [
    ("SPY_BH", "SPY_VT", "SPY B&H vs SPY 12/VIX"),
    ("5050_BH", "5050_VT", "50/50 B&H vs 50/50+VT"),
    ("SPY_BH", "5050_BH", "SPY B&H vs 50/50 B&H"),
    ("SPY_BH", "5050_VT", "SPY B&H vs 50/50+VT"),
    ("SPY_VT", "5050_VT", "SPY VT vs 50/50 VT"),
]

for s1, s2, desc in comparisons:
    mask1 = episodes_df["strategy"] == s1
    mask2 = episodes_df["strategy"] == s2
    sub1 = episodes_df[mask1]
    sub2 = episodes_df[mask2]

    if len(sub1) < 2 or len(sub2) < 2:
        print(f"  {desc}: insufficient data")
        continue

    result = logrank_test(
        sub1["duration"].values, sub2["duration"].values,
        event_observed_A=(1 - sub1["censored"]).values,
        event_observed_B=(1 - sub2["censored"]).values,
    )

    sig = "***" if result.p_value < 0.001 else "**" if result.p_value < 0.01 else "*" if result.p_value < 0.05 else "n.s."
    print(f"  {desc:35s}: chi2={result.test_statistic:.2f}, p={result.p_value:.4f} {sig}")

    logrank_results[desc] = {
        "chi2": float(result.test_statistic),
        "p_value": float(result.p_value),
        "significant_005": result.p_value < 0.05,
    }

# ================================================================
# 6. HAZARD RATE ANALYSIS
# ================================================================
print("\n[6] Hazard Rate Analysis...")
print("    Conditional probability of recovery given still in drawdown")

def compute_conditional_hazard(episodes, window_start, window_end):
    """
    Among episodes lasting at least window_start days,
    what fraction recovered within window_end days?
    """
    # Episodes that lasted at least window_start days
    survived = episodes[episodes["duration"] >= window_start]
    if len(survived) == 0:
        return np.nan, 0

    # Of those, how many recovered within window_end days?
    recovered = survived[(survived["duration"] <= window_end) & (survived["censored"] == 0)]
    rate = len(recovered) / len(survived)
    return rate, len(survived)

print("\n  Conditional recovery rates (among episodes surviving to day X):")
print(f"  {'Strategy':25s} | {'P(recov in 30d | surv 30d)':>30s} | {'P(recov in 60d | surv 60d)':>30s} | {'P(recov in 90d | surv 120d)':>30s}")
print("  " + "-" * 130)

hazard_results = {}
for key, strat in strategies.items():
    mask = episodes_df["strategy"] == key
    subset = episodes_df[mask]

    h30, n30 = compute_conditional_hazard(subset, 30, 60)
    h60, n60 = compute_conditional_hazard(subset, 60, 120)
    h120, n120 = compute_conditional_hazard(subset, 120, 210)

    hazard_results[key] = {
        "hazard_30_60": float(h30) if not np.isnan(h30) else None,
        "n_at_risk_30": int(n30),
        "hazard_60_120": float(h60) if not np.isnan(h60) else None,
        "n_at_risk_60": int(n60),
        "hazard_120_210": float(h120) if not np.isnan(h120) else None,
        "n_at_risk_120": int(n120),
    }

    h30_str = f"{h30:.1%} (n={n30})" if not np.isnan(h30) else "N/A"
    h60_str = f"{h60:.1%} (n={n60})" if not np.isnan(h60) else "N/A"
    h120_str = f"{h120:.1%} (n={n120})" if not np.isnan(h120) else "N/A"
    print(f"  {strat['label']:25s} | {h30_str:>30s} | {h60_str:>30s} | {h120_str:>30s}")

# ================================================================
# 7. HAZARD vs DRAWDOWN DEPTH
# ================================================================
print("\n[7] Does Drawdown Depth Affect Recovery Speed?")

# Split episodes by depth
all_complete = episodes_df[episodes_df["censored"] == 0].copy()
if len(all_complete) > 0:
    depth_median = all_complete["max_depth"].median()
    shallow = all_complete[all_complete["max_depth"] > depth_median]  # Less negative = shallow
    deep = all_complete[all_complete["max_depth"] <= depth_median]

    print(f"  Depth split at median: {depth_median:.1%}")
    print(f"  Shallow (>{depth_median:.1%}): {len(shallow)} episodes, mean duration={shallow['duration'].mean():.0f} days")
    print(f"  Deep (<={depth_median:.1%}): {len(deep)} episodes, mean duration={deep['duration'].mean():.0f} days")

    # Correlation: depth vs duration
    if len(all_complete) >= 5:
        corr_depth_dur, p_depth_dur = stats.spearmanr(
            all_complete["max_depth"].values,
            all_complete["duration"].values
        )
        print(f"\n  Spearman corr(depth, duration): rho={corr_depth_dur:.3f}, p={p_depth_dur:.4f}")
        print(f"  Interpretation: {'Deeper drawdowns last longer' if corr_depth_dur < -0.2 and p_depth_dur < 0.05 else 'No significant relationship' if p_depth_dur >= 0.05 else 'Deeper drawdowns recover faster'}")

    # Log-rank: shallow vs deep
    if len(shallow) >= 2 and len(deep) >= 2:
        lr_depth = logrank_test(
            shallow["duration"].values, deep["duration"].values,
            event_observed_A=np.ones(len(shallow)),
            event_observed_B=np.ones(len(deep)),
        )
        print(f"  Log-rank (shallow vs deep): chi2={lr_depth.test_statistic:.2f}, p={lr_depth.p_value:.4f}")

# ================================================================
# 8. COX PROPORTIONAL HAZARDS MODEL
# ================================================================
print("\n[8] Cox Proportional Hazards Regression...")
print("    Which factors predict FASTER recovery from drawdowns?")

# Prepare data for Cox PH
cox_data = episodes_df.copy()
cox_data = cox_data.dropna(subset=["duration", "censored"])

# Add covariates
# Standardize for interpretability
cox_features = []

if "vix_at_start" in cox_data.columns:
    cox_data["vix_at_start_z"] = (cox_data["vix_at_start"] - cox_data["vix_at_start"].mean()) / cox_data["vix_at_start"].std()
    cox_features.append("vix_at_start_z")

if "max_depth" in cox_data.columns:
    cox_data["abs_depth"] = cox_data["max_depth"].abs()
    cox_data["abs_depth_z"] = (cox_data["abs_depth"] - cox_data["abs_depth"].mean()) / cox_data["abs_depth"].std()
    cox_features.append("abs_depth_z")

if "drawdown_speed_days" in cox_data.columns:
    cox_data["speed_z"] = (cox_data["drawdown_speed_days"] - cox_data["drawdown_speed_days"].mean()) / cox_data["drawdown_speed_days"].std()
    cox_features.append("speed_z")

if "gld_during" in cox_data.columns:
    cox_data["gld_z"] = (cox_data["gld_during"] - cox_data["gld_during"].mean()) / cox_data["gld_during"].std()
    cox_features.append("gld_z")

# VT indicator
cox_data["is_vt"] = cox_data["strategy"].isin(["SPY_VT", "5050_VT"]).astype(int)
cox_features.append("is_vt")

# Diversification indicator
cox_data["is_diversified"] = cox_data["strategy"].isin(["5050_BH", "5050_VT"]).astype(int)
cox_features.append("is_diversified")

# Event indicator (1 = recovery)
cox_data["event"] = 1 - cox_data["censored"]

# Drop rows with NaN in features
cox_subset = cox_data[["duration", "event"] + cox_features].dropna()

print(f"\n  Cox PH sample: {len(cox_subset)} episodes")
print(f"  Covariates: {cox_features}")

cox_results_dict = {}
if len(cox_subset) >= 10:
    try:
        cph = CoxPHFitter()
        cph.fit(cox_subset, duration_col="duration", event_col="event")

        print("\n  Cox PH Results:")
        print("  " + "-" * 70)
        print(f"  {'Covariate':20s} | {'coef':>8s} | {'HR':>8s} | {'p-value':>8s} | {'Interpretation'}")
        print("  " + "-" * 70)

        summary = cph.summary
        for var in cox_features:
            if var in summary.index:
                coef = summary.loc[var, "coef"]
                hr = np.exp(coef)
                pval = summary.loc[var, "p"]

                # Interpretation
                if pval < 0.05:
                    if hr > 1:
                        interp = "FASTER recovery"
                    else:
                        interp = "SLOWER recovery"
                else:
                    interp = "Not significant"

                sig = "***" if pval < 0.001 else "**" if pval < 0.01 else "*" if pval < 0.05 else ""
                print(f"  {var:20s} | {coef:>8.3f} | {hr:>8.3f} | {pval:>8.4f} | {interp} {sig}")

                cox_results_dict[var] = {
                    "coef": float(coef),
                    "hazard_ratio": float(hr),
                    "p_value": float(pval),
                    "significant": pval < 0.05,
                }

        # Model fit
        concordance = cph.concordance_index_
        log_likelihood_ratio_p = float(cph.log_likelihood_ratio_test().p_value)
        print(f"\n  Model concordance: {concordance:.3f}")
        print(f"  LR test p-value: {log_likelihood_ratio_p:.4f}")
        cox_results_dict["_model_fit"] = {
            "concordance": float(concordance),
            "lr_test_p": log_likelihood_ratio_p,
        }

    except Exception as e:
        print(f"  Cox PH failed: {e}")
else:
    print("  Insufficient episodes for Cox PH regression")

# ================================================================
# 9. VT'S EFFECT ON DRAWDOWN DURATION
# ================================================================
print("\n[9] VT's Effect on Drawdown Duration...")

vt_effect = {}
for pair_name, bh_key, vt_key in [
    ("SPY", "SPY_BH", "SPY_VT"),
    ("50/50", "5050_BH", "5050_VT"),
]:
    bh_eps = episodes_df[episodes_df["strategy"] == bh_key]
    vt_eps = episodes_df[episodes_df["strategy"] == vt_key]

    bh_complete = bh_eps[bh_eps["censored"] == 0]
    vt_complete = vt_eps[vt_eps["censored"] == 0]

    print(f"\n  {pair_name}:")
    print(f"    B&H: {len(bh_eps)} episodes ({len(bh_complete)} complete)")
    print(f"    VT:  {len(vt_eps)} episodes ({len(vt_complete)} complete)")

    if len(bh_complete) > 0 and len(vt_complete) > 0:
        bh_mean = bh_complete["duration"].mean()
        vt_mean = vt_complete["duration"].mean()
        bh_median = bh_complete["duration"].median()
        vt_median = vt_complete["duration"].median()

        print(f"    Mean duration: B&H={bh_mean:.0f}d, VT={vt_mean:.0f}d (diff={vt_mean-bh_mean:+.0f}d)")
        print(f"    Median duration: B&H={bh_median:.0f}d, VT={vt_median:.0f}d (diff={vt_median-bh_median:+.0f}d)")

        # Mann-Whitney U test (non-parametric)
        if len(bh_complete) >= 3 and len(vt_complete) >= 3:
            u_stat, u_pval = stats.mannwhitneyu(
                bh_complete["duration"].values,
                vt_complete["duration"].values,
                alternative="two-sided"
            )
            print(f"    Mann-Whitney U: U={u_stat:.0f}, p={u_pval:.4f}")
        else:
            u_pval = np.nan

        # Max depth comparison
        bh_avg_depth = bh_complete["max_depth"].mean()
        vt_avg_depth = vt_complete["max_depth"].mean()
        print(f"    Mean max depth: B&H={bh_avg_depth:.1%}, VT={vt_avg_depth:.1%}")

        vt_effect[pair_name] = {
            "bh_n": int(len(bh_complete)),
            "vt_n": int(len(vt_complete)),
            "bh_mean_duration": float(bh_mean),
            "vt_mean_duration": float(vt_mean),
            "duration_diff_days": float(vt_mean - bh_mean),
            "bh_median_duration": float(bh_median),
            "vt_median_duration": float(vt_median),
            "mannwhitney_p": float(u_pval) if not np.isnan(u_pval) else None,
            "bh_mean_depth": float(bh_avg_depth),
            "vt_mean_depth": float(vt_avg_depth),
        }

# ================================================================
# 10. DETAILED EPISODE TABLE
# ================================================================
print("\n[10] Detailed Episode Table (all strategies)...")
print("=" * 110)
print(f"  {'Strategy':15s} | {'Start':>12s} | {'End':>12s} | {'Days':>5s} | {'Max DD':>8s} | {'VIX':>6s} | {'Speed':>6s} | {'GLD':>8s} | {'Status'}")
print("  " + "-" * 108)

for _, row in episodes_df.sort_values(["strategy", "start_date"]).iterrows():
    start = row["start_date"].strftime("%Y-%m-%d") if pd.notna(row["start_date"]) else "?"
    end = row["end_date"].strftime("%Y-%m-%d") if pd.notna(row["end_date"]) else "?"
    dur = f"{row['duration']:>5.0f}"
    depth = f"{row['max_depth']:>8.1%}"
    vix_s = f"{row['vix_at_start']:>6.1f}" if pd.notna(row.get("vix_at_start")) else "   N/A"
    speed = f"{row['drawdown_speed_days']:>6.0f}" if pd.notna(row.get("drawdown_speed_days")) else "   N/A"
    gld = f"{row['gld_during']:>8.1%}" if pd.notna(row.get("gld_during")) else "     N/A"
    status = "CENSORED" if row["censored"] == 1 else "recovered"
    print(f"  {row['strategy']:15s} | {start:>12s} | {end:>12s} | {dur} | {depth} | {vix_s} | {speed} | {gld} | {status}")

# ================================================================
# 11. VIX REGIME ANALYSIS
# ================================================================
print("\n[11] VIX Regime Effect on Drawdown Duration...")

complete_eps = episodes_df[(episodes_df["censored"] == 0) & episodes_df["vix_at_start"].notna()].copy()

if len(complete_eps) >= 6:
    vix_median = complete_eps["vix_at_start"].median()
    low_vix = complete_eps[complete_eps["vix_at_start"] <= vix_median]
    high_vix = complete_eps[complete_eps["vix_at_start"] > vix_median]

    print(f"  VIX median at drawdown start: {vix_median:.1f}")
    print(f"  Low VIX (<=median): {len(low_vix)} episodes, mean duration={low_vix['duration'].mean():.0f}d, mean depth={low_vix['max_depth'].mean():.1%}")
    print(f"  High VIX (>median): {len(high_vix)} episodes, mean duration={high_vix['duration'].mean():.0f}d, mean depth={high_vix['max_depth'].mean():.1%}")

    if len(low_vix) >= 2 and len(high_vix) >= 2:
        lr_vix = logrank_test(
            low_vix["duration"].values, high_vix["duration"].values,
            event_observed_A=np.ones(len(low_vix)),
            event_observed_B=np.ones(len(high_vix)),
        )
        print(f"  Log-rank (low vs high VIX): chi2={lr_vix.test_statistic:.2f}, p={lr_vix.p_value:.4f}")

# ================================================================
# 12. SUMMARY STATISTICS
# ================================================================
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

summary = {
    "experiment": "K385",
    "title": "Drawdown Survival Analysis",
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "period": f"{ANALYSIS_START} to {ANALYSIS_END}",
    "trading_days": int(len(common)),
    "drawdown_threshold": DRAWDOWN_THRESHOLD,
    "total_episodes": int(len(episodes_df)),
    "kaplan_meier": km_results,
    "logrank_tests": logrank_results,
    "hazard_rates": hazard_results,
    "cox_ph": cox_results_dict,
    "vt_duration_effect": vt_effect,
    "episodes_per_strategy": {},
}

for key, strat in strategies.items():
    mask = episodes_df["strategy"] == key
    subset = episodes_df[mask]
    complete = subset[subset["censored"] == 0]
    summary["episodes_per_strategy"][key] = {
        "label": strat["label"],
        "total_episodes": int(len(subset)),
        "complete_episodes": int(len(complete)),
        "censored_episodes": int((subset["censored"] == 1).sum()),
        "mean_duration": float(complete["duration"].mean()) if len(complete) > 0 else None,
        "median_duration": float(complete["duration"].median()) if len(complete) > 0 else None,
        "max_duration": int(complete["duration"].max()) if len(complete) > 0 else None,
        "mean_max_depth": float(complete["max_depth"].mean()) if len(complete) > 0 else None,
    }

# Key findings
print("\nKey Findings:")
for key in ["SPY_BH", "5050_BH", "SPY_VT", "5050_VT"]:
    if key in km_results:
        km = km_results[key]
        med_str = f"{km['median_survival_days']:.0f}d" if km['median_survival_days'] else ">50% never recover in sample"
        print(f"  {km['label']:25s}: median DD={med_str}, P(>60d)={km['prob_still_in_dd_60d']:.0%}, P(>252d)={km['prob_still_in_dd_252d']:.0%}")

print("\nLog-Rank Tests (VT effect):")
for desc, lr in logrank_results.items():
    sig = "SIGNIFICANT" if lr["significant_005"] else "not significant"
    print(f"  {desc:35s}: p={lr['p_value']:.4f} ({sig})")

if cox_results_dict:
    print("\nCox PH Key Predictors of Recovery Speed:")
    for var, res in cox_results_dict.items():
        if var.startswith("_"):
            continue
        if res["significant"]:
            direction = "faster" if res["hazard_ratio"] > 1 else "slower"
            print(f"  {var:20s}: HR={res['hazard_ratio']:.3f}, p={res['p_value']:.4f} ({direction} recovery)")

print("\nVT Duration Effect:")
for pair_name, eff in vt_effect.items():
    p_str = f"p={eff['mannwhitney_p']:.4f}" if eff['mannwhitney_p'] else "N/A"
    print(f"  {pair_name}: VT {eff['duration_diff_days']:+.0f} days mean duration ({p_str})")

# Limitations
summary["limitations"] = [
    "Small sample size (drawdowns are rare events, ~5-15 per strategy over 20 years)",
    "5% threshold is somewhat arbitrary; results may differ with 3% or 10% thresholds",
    "GLD data only from Nov 2004, limiting pre-GFC analysis",
    "VT strategy uses simple 12/VIX with max leverage 1.5x cap",
    "Censored observations reduce statistical power",
    "No multiple testing correction applied to log-rank tests",
    "Cox PH assumes proportional hazards (may not hold for all covariates)",
]

print("\nLimitations:")
for lim in summary["limitations"]:
    print(f"  - {lim}")

# ================================================================
# 13. SAVE RESULTS
# ================================================================
output_file = "/Users/yhlai0911/Desktop/volpred-research/.claude/worktrees/agent-a31590c1/experiments/k385_survival_results.json"

# Convert dates for JSON serialization
episodes_list = []
for _, row in episodes_df.iterrows():
    ep = row.to_dict()
    ep["start_date"] = ep["start_date"].strftime("%Y-%m-%d") if pd.notna(ep["start_date"]) else None
    ep["end_date"] = ep["end_date"].strftime("%Y-%m-%d") if pd.notna(ep["end_date"]) else None
    episodes_list.append(ep)

summary["episodes"] = episodes_list

with open(output_file, "w") as f:
    json.dump(summary, f, indent=2, default=str)

print(f"\nResults saved to: {output_file}")
print("\n" + "=" * 80)
print("K385 COMPLETE")
print("=" * 80)
