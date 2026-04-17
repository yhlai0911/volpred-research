#!/usr/bin/env python3
"""
K863: Phase Transition Detection in Financial Markets
Physics-Inspired Regime Change Indicator (v2)

Differentiates from K98 (AUC 0.560):
- Better crash definition (drawdown-based, not threshold-based)
- Composite indicator combining 3 physics-inspired signals
- Rigorous lead-lag analysis with proper shift(1)
- ROC analysis with bootstrap CIs
- Practical test: trading strategy with signal.shift(1)

References:
- Sornette (2003) "Why Stock Markets Crash"
- Scheffer et al. (2009) Nature "Early-warning signals for critical transitions"
- Harmon et al. (2015) "Anticipating Economic Market Crises Using Measures of Collective Panic"
- K98: phase_transition_crashes (AUC=0.560, VIX=0.694)

Data source: yfinance, 2005-01 to 2026-04
"""

import json
import warnings
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore")

start_time = time.time()

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 60)
print("K863: Phase Transition Detection in Financial Markets")
print("=" * 60)

tickers = ["SPY", "QQQ", "GLD", "TLT", "EEM", "^VIX"]
ticker_names = {"SPY": "SPY", "QQQ": "QQQ", "GLD": "GLD", "TLT": "TLT", "EEM": "EEM", "^VIX": "VIX"}

print("\n[1] Downloading data (2005-01 to 2026-04)...")
data = {}
for t in tickers:
    df = yf.download(t, start="2005-01-01", end="2026-04-05", progress=False, auto_adjust=True)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[ticker_names.get(t, t)] = df["Close"]

prices = pd.DataFrame(data)
prices = prices.dropna()
print(f"  Data: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}, {len(prices)} obs")

# Returns for assets (not VIX)
asset_tickers = ["SPY", "QQQ", "GLD", "TLT", "EEM"]
returns = np.log(prices[asset_tickers] / prices[asset_tickers].shift(1)).dropna()

# ============================================================
# 2. CRASH EPISODE IDENTIFICATION
# ============================================================
print("\n[2] Identifying crash episodes (SPY drawdown > 10% in 63 days)...")

spy_prices = prices["SPY"]
# Rolling 63-day max drawdown
rolling_max = spy_prices.rolling(63, min_periods=1).max()
drawdown = (spy_prices - rolling_max) / rolling_max

# Mark crash episodes: drawdown < -10%
crash_threshold = -0.10
crash_mask = drawdown < crash_threshold

# Group contiguous crash days into episodes
crash_episodes = []
in_crash = False
episode_start = None
for i, (date, is_crash) in enumerate(crash_mask.items()):
    if is_crash and not in_crash:
        in_crash = True
        episode_start = date
    elif not is_crash and in_crash:
        in_crash = False
        crash_episodes.append({
            "start": episode_start,
            "end": date,
            "min_dd": drawdown.loc[episode_start:date].min()
        })

if in_crash:
    crash_episodes.append({
        "start": episode_start,
        "end": drawdown.index[-1],
        "min_dd": drawdown.loc[episode_start:].min()
    })

# Merge episodes within 30 days of each other
merged = [crash_episodes[0]]
for ep in crash_episodes[1:]:
    if (ep["start"] - merged[-1]["end"]).days < 30:
        merged[-1]["end"] = ep["end"]
        merged[-1]["min_dd"] = min(merged[-1]["min_dd"], ep["min_dd"])
    else:
        merged.append(ep)
crash_episodes = merged

print(f"  Found {len(crash_episodes)} crash episodes:")
for i, ep in enumerate(crash_episodes):
    print(f"    [{i+1}] {ep['start'].strftime('%Y-%m-%d')} to {ep['end'].strftime('%Y-%m-%d')} "
          f"(max DD: {ep['min_dd']:.1%})")

# Create binary labels: 1 = within 63 days BEFORE crash start (pre-crash)
# 0 = calm period (not within 63 days before or during crash)
pre_crash_window = 63  # trading days

labels = pd.Series(0, index=returns.index)
during_crash = pd.Series(0, index=returns.index)

for ep in crash_episodes:
    # Mark "during crash"
    during_mask = (returns.index >= ep["start"]) & (returns.index <= ep["end"])
    during_crash[during_mask] = 1

    # Mark pre-crash (63 trading days before crash start)
    crash_start_idx = returns.index.get_indexer([ep["start"]], method="nearest")[0]
    pre_start = max(0, crash_start_idx - pre_crash_window)
    pre_end = crash_start_idx
    labels.iloc[pre_start:pre_end] = 1

# Exclude "during crash" from analysis (ambiguous)
valid_mask = during_crash == 0
print(f"  Pre-crash days: {labels[valid_mask].sum()}, Calm days: {(labels[valid_mask] == 0).sum()}")

# ============================================================
# 3. PHASE TRANSITION INDICATORS
# ============================================================
print("\n[3] Computing phase transition indicators...")

# --- 3a. Cross-Asset Correlation (Order Parameter) ---
print("  3a. Cross-asset correlation order parameter...")
window_corr = 22  # 1 month

# Compute rolling pairwise correlations
pair_corrs = pd.DataFrame(index=returns.index)
pairs = [(a, b) for i, a in enumerate(asset_tickers) for b in asset_tickers[i+1:]]

for a, b in pairs:
    pair_corrs[f"{a}_{b}"] = returns[a].rolling(window_corr).corr(returns[b])

# Order parameter = mean absolute correlation
order_param = pair_corrs.abs().mean(axis=1)
order_param.name = "order_parameter"

# Susceptibility = rolling variance of order parameter
susceptibility = order_param.rolling(63).var()
susceptibility.name = "susceptibility"

# Rate of change of order parameter
order_param_roc = order_param.diff(22) / order_param.shift(22)
order_param_roc.name = "order_param_roc"

print(f"    Order parameter: mean={order_param.mean():.3f}, std={order_param.std():.3f}")

# --- 3b. Shannon Entropy ---
print("  3b. Shannon entropy of return distribution...")
window_entropy = 63
n_bins = 10

def rolling_entropy(series, window, n_bins):
    """Compute rolling Shannon entropy of return distribution."""
    entropies = pd.Series(np.nan, index=series.index)
    for i in range(window, len(series)):
        chunk = series.iloc[i-window:i].dropna()
        if len(chunk) < window // 2:
            continue
        hist, _ = np.histogram(chunk, bins=n_bins, density=True)
        hist = hist / hist.sum()  # normalize
        hist = hist[hist > 0]  # remove zeros
        entropies.iloc[i] = -np.sum(hist * np.log2(hist))
    return entropies

spy_entropy = rolling_entropy(returns["SPY"], window_entropy, n_bins)
spy_entropy.name = "spy_entropy"

# Entropy change (drop = potential transition)
entropy_change = spy_entropy.diff(22)
entropy_change.name = "entropy_change"

print(f"    SPY entropy: mean={spy_entropy.mean():.3f}, std={spy_entropy.std():.3f}")

# --- 3c. Critical Slowing Down (CSD) ---
print("  3c. Critical slowing down indicators...")
vix = prices["VIX"]
window_csd = 63

# AR(1) of VIX (autocorrelation at lag 1)
vix_ar1 = vix.rolling(window_csd).apply(
    lambda x: pd.Series(x).autocorr(lag=1) if len(x) >= 10 else np.nan,
    raw=False
)
vix_ar1.name = "vix_ar1"

# Rolling variance of VIX
vix_variance = vix.rolling(window_csd).var()
vix_variance.name = "vix_variance"

# Rolling variance of SPY returns
spy_ret_var = returns["SPY"].rolling(window_csd).var()
spy_ret_var.name = "spy_ret_var"

# VIX level (benchmark)
vix_level = vix.copy()
vix_level.name = "vix_level"

print(f"    VIX AR(1): mean={vix_ar1.mean():.3f}")
print(f"    VIX variance: mean={vix_variance.mean():.1f}")

# ============================================================
# 4. COMBINE INTO ANALYSIS DATAFRAME
# ============================================================
print("\n[4] Building analysis dataframe...")

indicators = pd.DataFrame({
    "order_parameter": order_param,
    "susceptibility": susceptibility,
    "order_param_roc": order_param_roc,
    "spy_entropy": spy_entropy,
    "entropy_change": entropy_change,
    "vix_ar1": vix_ar1,
    "vix_variance": vix_variance,
    "spy_ret_var": spy_ret_var,
    "vix_level": vix_level,
    "label": labels,
    "during_crash": during_crash,
})

# Drop during-crash and NaN rows
df = indicators[indicators["during_crash"] == 0].drop(columns=["during_crash"]).dropna()
print(f"  Analysis sample: {len(df)} obs, {df['label'].sum()} pre-crash, "
      f"{(df['label']==0).sum()} calm")

# ============================================================
# 5. INDIVIDUAL INDICATOR ANALYSIS
# ============================================================
print("\n[5] Individual indicator analysis...")

indicator_cols = ["order_parameter", "susceptibility", "order_param_roc",
                  "spy_entropy", "entropy_change", "vix_ar1",
                  "vix_variance", "spy_ret_var", "vix_level"]

results_individual = {}

for col in indicator_cols:
    x = df[col].values
    y = df["label"].values

    # Mean in pre-crash vs calm
    mean_precrash = df.loc[df["label"] == 1, col].mean()
    mean_calm = df.loc[df["label"] == 0, col].mean()

    # t-test
    t_stat, p_val = stats.ttest_ind(
        df.loc[df["label"] == 1, col],
        df.loc[df["label"] == 0, col],
        equal_var=False
    )

    # AUC
    # For entropy_change, lower = more dangerous, so flip
    if col in ["spy_entropy", "entropy_change"]:
        auc = roc_auc_score(y, -x)
    else:
        auc = roc_auc_score(y, x)

    results_individual[col] = {
        "mean_precrash": float(mean_precrash),
        "mean_calm": float(mean_calm),
        "ratio": float(mean_precrash / mean_calm) if mean_calm != 0 else np.nan,
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "auc": float(auc),
        "passes_harvey": abs(t_stat) > 3.0
    }

    direction = "higher" if mean_precrash > mean_calm else "lower"
    harvey_flag = " ***" if abs(t_stat) > 3.0 else ""
    print(f"  {col:20s}: AUC={auc:.3f}, t={t_stat:+.2f}{harvey_flag}, "
          f"pre-crash {direction} ({mean_precrash:.4f} vs {mean_calm:.4f})")

# ============================================================
# 6. LEAD-LAG ANALYSIS
# ============================================================
print("\n[6] Lead-lag analysis (do indicators rise BEFORE crashes?)...")

# For each crash episode, look at indicator trajectory in the 126 days before
lead_lag_results = {}

for col in indicator_cols:
    indicator_series = indicators[col].dropna()
    avg_trajectory = []

    for ep in crash_episodes:
        crash_start_idx = indicator_series.index.get_indexer([ep["start"]], method="nearest")[0]

        # 126 trading days before crash
        lookback = 126
        start_idx = max(0, crash_start_idx - lookback)

        if crash_start_idx - start_idx < 60:  # need at least 60 days
            continue

        trajectory = indicator_series.iloc[start_idx:crash_start_idx].values
        # Normalize to z-score
        trajectory_z = (trajectory - np.nanmean(trajectory)) / (np.nanstd(trajectory) + 1e-10)

        # Resample to fixed length (126 points)
        target_len = lookback
        actual_len = len(trajectory_z)
        if actual_len < target_len:
            # Pad with NaN at the start
            padded = np.full(target_len, np.nan)
            padded[target_len - actual_len:] = trajectory_z
            trajectory_z = padded
        else:
            trajectory_z = trajectory_z[-target_len:]

        avg_trajectory.append(trajectory_z)

    if len(avg_trajectory) >= 3:
        avg_traj = np.nanmean(avg_trajectory, axis=0)
        # Does the indicator trend upward in the last 63 days?
        last_half = avg_traj[-63:]
        first_half = avg_traj[:63]

        # Regression slope in last 63 days
        valid = ~np.isnan(last_half)
        if valid.sum() > 10:
            x_reg = np.arange(valid.sum())
            slope, intercept, r, p, se = stats.linregress(x_reg, last_half[valid])

            lead_lag_results[col] = {
                "n_episodes": len(avg_trajectory),
                "slope_last63": float(slope),
                "r_squared": float(r**2),
                "p_value": float(p),
                "mean_first_half": float(np.nanmean(first_half)),
                "mean_last_half": float(np.nanmean(last_half)),
                "rising_before_crash": slope > 0
            }

            direction = "RISING" if slope > 0 else "falling"
            sig = " *" if p < 0.05 else ""
            if col in ["spy_entropy", "entropy_change"]:
                direction = "FALLING" if slope < 0 else "rising"
            print(f"  {col:20s}: {direction} before crash (slope={slope:.4f}, "
                  f"R²={r**2:.3f}, p={p:.4f}){sig}")

# ============================================================
# 7. COMPOSITE INDICATOR
# ============================================================
print("\n[7] Building composite phase transition indicator...")

# Select top indicators and combine
# Standardize all indicators
scaler = StandardScaler()
X_all = df[indicator_cols].copy()

# Handle infinity
X_all = X_all.replace([np.inf, -np.inf], np.nan)
X_all = X_all.fillna(X_all.median())

X_scaled = pd.DataFrame(
    scaler.fit_transform(X_all),
    index=X_all.index,
    columns=indicator_cols
)

# Flip signs for entropy indicators (lower entropy = more risk)
X_scaled["spy_entropy"] = -X_scaled["spy_entropy"]
X_scaled["entropy_change"] = -X_scaled["entropy_change"]

# Simple equal-weight composite
composite_equal = X_scaled.mean(axis=1)
composite_equal.name = "composite_equal"

# Logistic regression composite (with proper train/test split)
y = df["label"].values
X = X_scaled.values

# Time-series split: first 70% train, last 30% test
split_idx = int(len(X) * 0.7)
X_train, X_test = X[:split_idx], X[split_idx:]
y_train, y_test = y[:split_idx], y[split_idx:]

lr = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
lr.fit(X_train, y_train)
prob_train = lr.predict_proba(X_train)[:, 1]
prob_test = lr.predict_proba(X_test)[:, 1]

auc_train = roc_auc_score(y_train, prob_train)
auc_test = roc_auc_score(y_test, prob_test)

# Equal weight composite AUC
auc_equal_all = roc_auc_score(y, composite_equal.values)
auc_vix_all = roc_auc_score(y, X_scaled["vix_level"].values)

print(f"  Logistic regression coefficients:")
for col, coef in zip(indicator_cols, lr.coef_[0]):
    print(f"    {col:20s}: {coef:+.3f}")

print(f"\n  AUC Results:")
print(f"    VIX alone (full sample):      {auc_vix_all:.3f}")
print(f"    Equal-weight composite:        {auc_equal_all:.3f}")
print(f"    Logistic (train):              {auc_train:.3f}")
print(f"    Logistic (OOS test):           {auc_test:.3f}")

# Bootstrap CI for OOS AUC
n_boot = 2000
auc_boot = []
for _ in range(n_boot):
    idx = np.random.choice(len(y_test), len(y_test), replace=True)
    if len(np.unique(y_test[idx])) < 2:
        continue
    auc_boot.append(roc_auc_score(y_test[idx], prob_test[idx]))

auc_ci = np.percentile(auc_boot, [2.5, 97.5])
print(f"    Logistic OOS 95% CI:           [{auc_ci[0]:.3f}, {auc_ci[1]:.3f}]")

# ============================================================
# 8. FALSE POSITIVE ANALYSIS
# ============================================================
print("\n[8] False positive analysis...")

# Use composite equal-weight as the signal
composite_full = X_scaled.mean(axis=1)
threshold_pcts = [80, 85, 90, 95]

fp_results = {}
for pct in threshold_pcts:
    threshold = np.percentile(composite_full, pct)
    signal = (composite_full > threshold).astype(int)

    # True positive: signal=1 and label=1
    tp = ((signal == 1) & (df["label"] == 1)).sum()
    fp = ((signal == 1) & (df["label"] == 0)).sum()
    fn = ((signal == 1) & (df["label"] == 1)).sum()
    tn = ((signal == 0) & (df["label"] == 0)).sum()

    # Precision = TP / (TP + FP)
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    # Recall = TP / (TP + FN)
    total_precrash = df["label"].sum()
    recall = tp / total_precrash if total_precrash > 0 else 0
    # False positive rate
    total_calm = (df["label"] == 0).sum()
    fpr = fp / total_calm if total_calm > 0 else 0

    fp_results[f"p{pct}"] = {
        "threshold_pct": pct,
        "threshold_value": float(threshold),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "precision": float(precision),
        "recall": float(recall),
        "false_positive_rate": float(fpr),
        "signal_days": int(signal.sum())
    }

    print(f"  Threshold p{pct}: TP={tp}, FP={fp}, "
          f"precision={precision:.1%}, recall={recall:.1%}, FPR={fpr:.1%}")

# ============================================================
# 9. PRACTICAL TRADING TEST
# ============================================================
print("\n[9] Practical trading test...")

# Strategy: reduce equity exposure when composite > threshold
# Use signal.shift(1) to avoid lookahead!
# Compare with buy-and-hold SPY

spy_ret = returns["SPY"].loc[df.index]

# Build composite signal for full sample (this is the signal we'd see in real-time)
composite_signal = composite_full.copy()

# CRITICAL: shift(1) — use yesterday's signal for today's position
signal_lagged = composite_signal.shift(1)  # signal.shift(1) for no lookahead

# Strategy: if signal > 90th percentile, go to 50% equity / 50% cash
# Otherwise: 100% equity
threshold_90 = np.percentile(composite_signal.dropna(), 90)
threshold_80 = np.percentile(composite_signal.dropna(), 80)

# Test multiple strategies
strategies = {}

# Strategy 1: Binary switch at 90th pct
weight_binary90 = pd.Series(1.0, index=spy_ret.index)
weight_binary90[signal_lagged > threshold_90] = 0.5
strat_ret_binary90 = spy_ret * weight_binary90
strategies["phase_binary_90"] = strat_ret_binary90

# Strategy 2: Binary switch at 80th pct
weight_binary80 = pd.Series(1.0, index=spy_ret.index)
weight_binary80[signal_lagged > threshold_80] = 0.5
strat_ret_binary80 = spy_ret * weight_binary80
strategies["phase_binary_80"] = strat_ret_binary80

# Strategy 3: Continuous scaling (higher signal = lower equity)
# Weight = max(0.3, 1 - 0.7 * percentile_rank(signal))
signal_pctrank = signal_lagged.rank(pct=True)
weight_continuous = (1.0 - 0.7 * signal_pctrank).clip(0.3, 1.0)
strat_ret_continuous = spy_ret * weight_continuous
strategies["phase_continuous"] = strat_ret_continuous

# Benchmark: VIX-based (12/VIX capped)
vix_signal = prices["VIX"].reindex(spy_ret.index)
vix_weight = (12.0 / vix_signal).clip(0.3, 1.0).shift(1)  # shift(1)!
strat_ret_vix = spy_ret * vix_weight
strategies["vix_12vix"] = strat_ret_vix

# Buy and hold
strategies["buy_hold"] = spy_ret

# Calculate metrics for all strategies
def calc_metrics(ret_series, name):
    """Calculate standard performance metrics."""
    ret = ret_series.dropna()
    n = len(ret)
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = (1 + ret).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    return {
        "name": name,
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "max_dd": float(mdd),
        "calmar": float(calmar),
        "n_obs": int(n)
    }

print(f"\n  Strategy comparison (full sample, signal.shift(1)):")
print(f"  {'Strategy':<25s} {'AnnRet':>8s} {'AnnVol':>8s} {'Sharpe':>8s} {'MDD':>8s} {'Calmar':>8s}")
print(f"  {'-'*73}")

strategy_metrics = {}
for name, ret_series in strategies.items():
    m = calc_metrics(ret_series, name)
    strategy_metrics[name] = m
    print(f"  {name:<25s} {m['ann_return']:>7.1%} {m['ann_vol']:>7.1%} "
          f"{m['sharpe']:>7.3f} {m['max_dd']:>7.1%} {m['calmar']:>7.3f}")

# ============================================================
# 10. CRASH-SPECIFIC PERFORMANCE
# ============================================================
print("\n[10] Crash episode performance (return during crash)...")

crash_perf = {}
for ep_idx, ep in enumerate(crash_episodes):
    ep_mask = (spy_ret.index >= ep["start"]) & (spy_ret.index <= ep["end"])
    if ep_mask.sum() == 0:
        continue

    ep_name = f"Crash {ep_idx+1} ({ep['start'].strftime('%Y-%m')})"
    crash_perf[ep_name] = {}

    for name, ret_series in strategies.items():
        ep_ret = ret_series[ep_mask]
        cum_ret = (1 + ep_ret).prod() - 1
        crash_perf[ep_name][name] = float(cum_ret)

print(f"  {'Episode':<30s}", end="")
for name in strategies:
    print(f" {name[:12]:>12s}", end="")
print()
print(f"  {'-'*90}")

for ep_name, perf in crash_perf.items():
    print(f"  {ep_name:<30s}", end="")
    for name in strategies:
        if name in perf:
            print(f" {perf[name]:>11.1%}", end="")
        else:
            print(f" {'N/A':>12s}", end="")
    print()

# ============================================================
# 11. COMPARISON WITH VIX
# ============================================================
print("\n[11] Phase transition indicators vs VIX comparison...")

# Correlation between composite and VIX
corr_composite_vix = composite_full.corr(X_scaled["vix_level"])
print(f"  Correlation(composite, VIX): {corr_composite_vix:.3f}")

# Incremental value: does composite add to VIX?
# Logistic regression: VIX only vs VIX + composite
from sklearn.metrics import log_loss

X_vix_only_train = X_train[:, indicator_cols.index("vix_level")].reshape(-1, 1)
X_vix_only_test = X_test[:, indicator_cols.index("vix_level")].reshape(-1, 1)

lr_vix = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
lr_vix.fit(X_vix_only_train, y_train)
prob_vix_test = lr_vix.predict_proba(X_vix_only_test)[:, 1]
auc_vix_test = roc_auc_score(y_test, prob_vix_test)

# Partial indicators (without VIX)
non_vix_cols = [c for c in indicator_cols if c != "vix_level"]
non_vix_idx = [indicator_cols.index(c) for c in non_vix_cols]
X_novix_train = X_train[:, non_vix_idx]
X_novix_test = X_test[:, non_vix_idx]

lr_novix = LogisticRegression(C=0.1, max_iter=1000, random_state=42)
lr_novix.fit(X_novix_train, y_train)
prob_novix_test = lr_novix.predict_proba(X_novix_test)[:, 1]
auc_novix_test = roc_auc_score(y_test, prob_novix_test)

print(f"\n  OOS AUC comparison:")
print(f"    VIX only:                      {auc_vix_test:.3f}")
print(f"    Physics indicators (no VIX):   {auc_novix_test:.3f}")
print(f"    All combined:                  {auc_test:.3f}")
print(f"    Incremental over VIX:          {auc_test - auc_vix_test:+.3f}")

# ============================================================
# 12. BOOTSTRAP SIGNIFICANCE TEST
# ============================================================
print("\n[12] Bootstrap significance test (AUC difference)...")

n_boot_sig = 5000
auc_diff_boot = []

for _ in range(n_boot_sig):
    idx = np.random.choice(len(y_test), len(y_test), replace=True)
    if len(np.unique(y_test[idx])) < 2:
        continue
    auc_all_b = roc_auc_score(y_test[idx], prob_test[idx])
    auc_vix_b = roc_auc_score(y_test[idx], prob_vix_test[idx])
    auc_diff_boot.append(auc_all_b - auc_vix_b)

auc_diff_ci = np.percentile(auc_diff_boot, [2.5, 97.5])
auc_diff_mean = np.mean(auc_diff_boot)
pct_positive = np.mean(np.array(auc_diff_boot) > 0) * 100

print(f"  AUC(all) - AUC(VIX only):")
print(f"    Mean difference:  {auc_diff_mean:+.4f}")
print(f"    95% CI:           [{auc_diff_ci[0]:+.4f}, {auc_diff_ci[1]:+.4f}]")
print(f"    P(diff > 0):      {pct_positive:.1f}%")

significant = auc_diff_ci[0] > 0
print(f"    Significant at 5%: {'YES' if significant else 'NO'}")

# ============================================================
# 13. DM TEST: Phase Strategy vs 12/VIX
# ============================================================
print("\n[13] DM test: Phase strategies vs 12/VIX...")

try:
    from volpred.stats.model_evaluation import strategy_dm_test

    for strat_name in ["phase_binary_90", "phase_binary_80", "phase_continuous"]:
        strat_ret = strategies[strat_name].dropna()
        vix_ret = strategies["vix_12vix"].dropna()

        common_idx = strat_ret.index.intersection(vix_ret.index)
        dm_stat, dm_pval = strategy_dm_test(
            strat_ret.loc[common_idx].values,
            vix_ret.loc[common_idx].values
        )
        harvey_pass = abs(dm_stat) > 3.0
        print(f"  {strat_name} vs 12/VIX: DM={dm_stat:+.3f}, p={dm_pval:.4f}, "
              f"Harvey: {'PASS' if harvey_pass else 'FAIL'}")
except ImportError:
    print("  (volpred.stats not available, skipping DM test)")
    # Manual DM test
    for strat_name in ["phase_binary_90", "phase_binary_80", "phase_continuous"]:
        strat_ret = strategies[strat_name].dropna()
        vix_ret = strategies["vix_12vix"].dropna()
        common_idx = strat_ret.index.intersection(vix_ret.index)

        d = strat_ret.loc[common_idx].values - vix_ret.loc[common_idx].values
        d_bar = np.mean(d)
        d_var = np.var(d, ddof=1)
        dm_stat = d_bar / np.sqrt(d_var / len(d)) if d_var > 0 else 0
        dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
        harvey_pass = abs(dm_stat) > 3.0
        print(f"  {strat_name} vs 12/VIX: DM={dm_stat:+.3f}, p={dm_pval:.4f}, "
              f"Harvey: {'PASS' if harvey_pass else 'FAIL'}")

# ============================================================
# 14. SUMMARY
# ============================================================
elapsed = time.time() - start_time
print(f"\n{'='*60}")
print(f"SUMMARY (runtime: {elapsed:.1f}s)")
print(f"{'='*60}")

# Determine key conclusions
best_individual = max(results_individual.items(), key=lambda x: x[1]["auc"])
print(f"\n  Best individual indicator: {best_individual[0]} (AUC={best_individual[1]['auc']:.3f})")
print(f"  VIX benchmark AUC: {auc_vix_all:.3f}")
print(f"  Composite OOS AUC: {auc_test:.3f}")
print(f"  VIX-only OOS AUC: {auc_vix_test:.3f}")
print(f"  Incremental AUC: {auc_test - auc_vix_test:+.3f}")
print(f"  Significant improvement: {'YES' if significant else 'NO'}")

# Best trading strategy
best_strat = max(
    [(k, v) for k, v in strategy_metrics.items() if k != "buy_hold"],
    key=lambda x: x[1]["sharpe"]
)
print(f"\n  Best strategy: {best_strat[0]} (Sharpe={best_strat[1]['sharpe']:.3f})")
print(f"  Buy-hold Sharpe: {strategy_metrics['buy_hold']['sharpe']:.3f}")
print(f"  12/VIX Sharpe: {strategy_metrics['vix_12vix']['sharpe']:.3f}")

# ============================================================
# 15. SAVE RESULTS
# ============================================================
print("\n[15] Saving results...")

results = {
    "experiment_id": "K863",
    "title": "Phase Transition Detection in Financial Markets (v2)",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "runtime_seconds": round(elapsed, 1),
    "data_source": "yfinance",
    "period": f"{prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}",
    "n_observations": len(df),
    "n_crash_episodes": len(crash_episodes),
    "crash_episodes": [
        {
            "start": ep["start"].strftime("%Y-%m-%d"),
            "end": ep["end"].strftime("%Y-%m-%d"),
            "max_drawdown": float(ep["min_dd"])
        }
        for ep in crash_episodes
    ],
    "prior_work": "K98: AUC=0.560 (physics) vs 0.694 (VIX). 81% false alarm rate.",
    "methodology": {
        "indicators": {
            "order_parameter": "Mean absolute 22-day rolling pairwise correlation of 5 assets",
            "susceptibility": "63-day rolling variance of order parameter",
            "order_param_roc": "22-day rate of change of order parameter",
            "spy_entropy": "Shannon entropy of 63-day return distribution (10 bins)",
            "entropy_change": "22-day change in entropy",
            "vix_ar1": "63-day rolling AR(1) of VIX (critical slowing down)",
            "vix_variance": "63-day rolling variance of VIX",
            "spy_ret_var": "63-day rolling variance of SPY returns",
            "vix_level": "VIX level (benchmark)"
        },
        "crash_definition": "SPY drawdown > 10% within 63 trading days",
        "pre_crash_window": "63 trading days before crash start",
        "composite": "Logistic regression + equal-weight (70/30 train/test split)",
        "trading_test": "signal.shift(1), no lookahead",
        "references": [
            "Sornette (2003) Why Stock Markets Crash",
            "Scheffer et al. (2009) Nature, Early-warning signals for critical transitions",
            "Harmon et al. (2015) Anticipating Economic Market Crises",
            "K98 (prior experiment, AUC=0.560)"
        ]
    },
    "individual_indicators": results_individual,
    "lead_lag_analysis": lead_lag_results,
    "composite_results": {
        "auc_vix_full": float(auc_vix_all),
        "auc_equal_weight_full": float(auc_equal_all),
        "auc_logistic_train": float(auc_train),
        "auc_logistic_oos": float(auc_test),
        "auc_logistic_oos_ci": [float(auc_ci[0]), float(auc_ci[1])],
        "auc_vix_only_oos": float(auc_vix_test),
        "auc_physics_no_vix_oos": float(auc_novix_test),
        "incremental_auc_over_vix": float(auc_test - auc_vix_test),
        "bootstrap_auc_diff": {
            "mean": float(auc_diff_mean),
            "ci_95": [float(auc_diff_ci[0]), float(auc_diff_ci[1])],
            "pct_positive": float(pct_positive),
            "significant": bool(significant)
        },
        "correlation_composite_vix": float(corr_composite_vix),
        "logistic_coefficients": {
            col: float(coef) for col, coef in zip(indicator_cols, lr.coef_[0])
        }
    },
    "false_positive_analysis": fp_results,
    "strategy_metrics": strategy_metrics,
    "crash_episode_performance": crash_perf,
    "conclusions": {
        "headline": "",
        "findings": [],
        "vs_k98": "",
        "limitations": [
            "Small sample: only {n_crash} crash episodes in 20 years".format(n_crash=len(crash_episodes)),
            "In-sample bias: crash definition is backward-looking",
            "Physics analogy may not hold: markets have reflexive agents, not inert particles",
            "Composite overfit risk despite train/test split (limited crash events in test set)",
            "Transaction costs not modeled in trading test"
        ]
    }
}

# Fill conclusions based on actual results
findings = []

# Finding 1: Best individual indicator
findings.append(
    f"Best individual indicator: {best_individual[0]} (AUC={best_individual[1]['auc']:.3f}), "
    f"vs VIX AUC={auc_vix_all:.3f}"
)

# Finding 2: Composite performance
findings.append(
    f"Composite OOS AUC: {auc_test:.3f} vs VIX-only OOS AUC: {auc_vix_test:.3f} "
    f"(incremental: {auc_test - auc_vix_test:+.3f}, significant={significant})"
)

# Finding 3: Physics indicators without VIX
findings.append(
    f"Physics indicators without VIX: OOS AUC={auc_novix_test:.3f} "
    f"({'above' if auc_novix_test > 0.5 else 'below'} random)"
)

# Finding 4: Trading test
best_phase = max(
    [(k, v) for k, v in strategy_metrics.items() if k.startswith("phase_")],
    key=lambda x: x[1]["sharpe"]
)
findings.append(
    f"Best phase strategy: {best_phase[0]} (Sharpe={best_phase[1]['sharpe']:.3f}) "
    f"vs 12/VIX (Sharpe={strategy_metrics['vix_12vix']['sharpe']:.3f}) "
    f"vs BH (Sharpe={strategy_metrics['buy_hold']['sharpe']:.3f})"
)

# Finding 5: False positives
fp_90 = fp_results.get("p90", {})
findings.append(
    f"False positive rate at 90th pct: {fp_90.get('false_positive_rate', 0):.1%}, "
    f"precision: {fp_90.get('precision', 0):.1%}"
)

# Harvey survivors
harvey_survivors = [k for k, v in results_individual.items() if v["passes_harvey"]]
findings.append(
    f"Harvey |t|>3.0 survivors: {harvey_survivors if harvey_survivors else 'NONE'}"
)

results["conclusions"]["findings"] = findings

# Headline
if auc_test > auc_vix_test and significant:
    results["conclusions"]["headline"] = (
        f"Phase transition composite adds significant predictive power over VIX "
        f"(OOS AUC {auc_test:.3f} vs {auc_vix_test:.3f})"
    )
elif auc_test > auc_vix_test:
    results["conclusions"]["headline"] = (
        f"Phase transition indicators show marginal improvement over VIX "
        f"(OOS AUC {auc_test:.3f} vs {auc_vix_test:.3f}) but NOT statistically significant"
    )
else:
    results["conclusions"]["headline"] = (
        f"Phase transition indicators do NOT improve upon VIX for crash prediction "
        f"(OOS AUC {auc_test:.3f} vs {auc_vix_test:.3f}). VIX remains sufficient."
    )

# vs K98
results["conclusions"]["vs_k98"] = (
    f"K98 found AUC=0.560 for physics indicators vs VIX 0.694. "
    f"K863 with improved methodology: composite OOS AUC={auc_test:.3f} vs VIX {auc_vix_test:.3f}. "
    f"{'Confirms' if auc_test <= auc_vix_test else 'Challenges'} K98 conclusion that VIX is sufficient."
)

# Save
output_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/k863_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to: {output_path}")
print(f"\n  HEADLINE: {results['conclusions']['headline']}")
print(f"\n  vs K98: {results['conclusions']['vs_k98']}")

print(f"\n{'='*60}")
print("K863 COMPLETE")
print(f"{'='*60}")
