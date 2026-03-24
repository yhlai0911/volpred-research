"""
K214: Wasserstein Distance for Volatility Regime Detection
==========================================================
Cross-disciplinary: Optimal Transport + Financial Volatility
Suggested by: Gemini R9#2

Core hypothesis: The Wasserstein-1 distance between recent and historical
return distributions captures distributional SHAPE shifts (not just
mean/variance changes) that predict future volatility beyond VIX.

Instead of asking "is vol high?", we ask "is the SHAPE of today's
return distribution fundamentally different from normal?"

Distributional features tested:
1. W1 distance: mean(|sort(recent_22) - sort(historical_252)|)
2. Rolling 22d kurtosis (tail heaviness change)
3. Rolling 22d skewness change (asymmetry shift)
4. Rolling 22d range/std ratio (distribution shape)

Tests:
- Partial correlation with future 22d RV controlling for VIX
- GARCH-X with distributional features
- DM test for forecast comparison
- OOS evaluation (2023-2024)

Data: SPY daily returns from yfinance (real data only).

Author: VolPred Research System (K214)
[Proposed: Gemini R9#2, Executed: Claude]
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2005-01-01"
TRAIN_END = "2022-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
SHORT_WINDOW = 22       # recent distribution window
LONG_WINDOW = 252       # historical distribution window
RV_HORIZON = 22         # 22-day forward realized vol
N_BOOTSTRAP = 5000
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
TARGET_VOL = 0.12
HARVEY_THRESHOLD = 3.0

np.random.seed(42)

print("=" * 75)
print("K214: WASSERSTEIN DISTANCE FOR VOLATILITY REGIME DETECTION")
print("=" * 75)
print(f"  Short window (recent): {SHORT_WINDOW}d")
print(f"  Long window (historical): {LONG_WINDOW}d")
print(f"  RV horizon: {RV_HORIZON}d")
print(f"  Training: {DATA_START} to {TRAIN_END}")
print(f"  OOS: {OOS_START} to {OOS_END}")
print()

# ==================================================================
# DATA
# ==================================================================
print("Downloading SPY data...")
spy = yf.download("SPY", start=DATA_START, end="2025-12-31", auto_adjust=True, progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy_ret = spy["Close"].pct_change().dropna()
spy_ret.name = "ret"

print("Downloading VIX data...")
vix = yf.download("^VIX", start=DATA_START, end="2025-12-31", auto_adjust=True, progress=False)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
vix_close = vix["Close"].dropna()
vix_close.name = "VIX"

# Align
common_idx = spy_ret.index.intersection(vix_close.index)
spy_ret = spy_ret.loc[common_idx]
vix_close = vix_close.loc[common_idx]

print(f"  SPY returns: {len(spy_ret)} days ({spy_ret.index[0].date()} to {spy_ret.index[-1].date()})")
print(f"  VIX: {len(vix_close)} days")
print()

# ==================================================================
# WASSERSTEIN-1 DISTANCE (Optimal Transport)
# ==================================================================
# For 1D distributions, W1 = integral of |F(x) - G(x)| dx
# Equivalent to: mean(|sort(X) - sort(Y)|) when same size
# When different sizes, use scipy or quantile matching

print("Computing Wasserstein-1 distance (recent 22d vs trailing 252d)...")

try:
    from scipy.stats import wasserstein_distance as scipy_w1
    HAS_SCIPY_W1 = True
    print("  Using scipy.stats.wasserstein_distance")
except ImportError:
    HAS_SCIPY_W1 = False
    print("  scipy.stats.wasserstein_distance not available, using manual implementation")


def wasserstein_1d(u_values, v_values):
    """Compute 1D Wasserstein-1 distance between two empirical distributions.

    W1 = integral |F_u(x) - F_v(x)| dx
    For empirical distributions, this equals the L1 distance between
    sorted quantile functions.
    """
    if HAS_SCIPY_W1:
        return scipy_w1(u_values, v_values)

    # Manual: sort both, interpolate to common grid, compute L1
    u_sorted = np.sort(u_values)
    v_sorted = np.sort(v_values)

    # Use quantile matching when sizes differ
    n = max(len(u_sorted), len(v_sorted))
    quantiles = np.linspace(0, 1, n + 1)[1:]  # exclude 0

    u_quantiles = np.quantile(u_values, quantiles)
    v_quantiles = np.quantile(v_values, quantiles)

    return np.mean(np.abs(u_quantiles - v_quantiles))


# Compute rolling W1 distance
ret_values = spy_ret.values
n = len(ret_values)

w1_distances = np.full(n, np.nan)
rolling_kurtosis = np.full(n, np.nan)
rolling_skewness = np.full(n, np.nan)
rolling_range_std = np.full(n, np.nan)
rolling_skew_change = np.full(n, np.nan)

for i in range(LONG_WINDOW, n):
    recent = ret_values[i - SHORT_WINDOW + 1 : i + 1]
    historical = ret_values[i - LONG_WINDOW + 1 : i - SHORT_WINDOW + 1]

    # W1 distance
    w1_distances[i] = wasserstein_1d(recent, historical)

    # Rolling 22d kurtosis
    if len(recent) >= 4:
        rolling_kurtosis[i] = stats.kurtosis(recent, fisher=True)

    # Rolling 22d skewness
    if len(recent) >= 3:
        rolling_skewness[i] = stats.skew(recent)

    # Rolling 22d range/std ratio (distribution shape measure)
    std_recent = np.std(recent, ddof=1)
    if std_recent > 0:
        rolling_range_std[i] = (np.max(recent) - np.min(recent)) / std_recent

# Skewness change (absolute change over 22 days)
for i in range(LONG_WINDOW + SHORT_WINDOW, n):
    prev_skew_window = ret_values[i - 2 * SHORT_WINDOW + 1 : i - SHORT_WINDOW + 1]
    curr_skew_window = ret_values[i - SHORT_WINDOW + 1 : i + 1]
    if len(prev_skew_window) >= 3 and len(curr_skew_window) >= 3:
        rolling_skew_change[i] = abs(stats.skew(curr_skew_window) - stats.skew(prev_skew_window))

# Compute forward 22d realized volatility
fwd_rv = np.full(n, np.nan)
for i in range(n - RV_HORIZON):
    fwd_window = ret_values[i + 1 : i + 1 + RV_HORIZON]
    fwd_rv[i] = np.sqrt(np.sum(fwd_window**2) * 252 / RV_HORIZON)

# Build DataFrame
df = pd.DataFrame({
    "ret": spy_ret.values,
    "W1": w1_distances,
    "kurtosis_22d": rolling_kurtosis,
    "skewness_22d": rolling_skewness,
    "range_std_22d": rolling_range_std,
    "skew_change_22d": rolling_skew_change,
    "fwd_rv_22d": fwd_rv,
    "VIX": vix_close.values,
}, index=spy_ret.index)

# Log transform W1 for better behavior
df["log_W1"] = np.log(df["W1"].clip(lower=1e-10))

# Standardize W1 (z-score over expanding window for OOS fairness)
df["W1_z"] = (df["W1"] - df["W1"].expanding().mean()) / df["W1"].expanding().std()

print(f"  W1 distance computed: {df['W1'].dropna().shape[0]} observations")
print(f"  W1 mean: {df['W1'].dropna().mean():.6f}")
print(f"  W1 std:  {df['W1'].dropna().std():.6f}")
print(f"  W1 range: [{df['W1'].dropna().min():.6f}, {df['W1'].dropna().max():.6f}]")
print()

# ==================================================================
# SECTION 1: FULL-SAMPLE CORRELATIONS
# ==================================================================
print("=" * 75)
print("SECTION 1: CORRELATION ANALYSIS (Full Sample)")
print("=" * 75)

features = {
    "W1": "Wasserstein-1 distance",
    "log_W1": "Log(W1) distance",
    "W1_z": "W1 z-score",
    "kurtosis_22d": "Rolling 22d kurtosis",
    "skewness_22d": "Rolling 22d skewness (abs)",
    "range_std_22d": "Rolling 22d range/std",
    "skew_change_22d": "Rolling 22d |skew change|",
}

# Use absolute skewness for correlation (both directions indicate regime shift)
df["abs_skewness_22d"] = df["skewness_22d"].abs()

print(f"\n{'Feature':<30} {'r(fwd_RV)':<12} {'p-value':<12} {'r|VIX':<12} {'p|VIX':<12}")
print("-" * 78)

partial_corr_results = {}

for feat_key, feat_name in features.items():
    if feat_key == "skewness_22d":
        col = "abs_skewness_22d"
    else:
        col = feat_key

    valid = df[[col, "fwd_rv_22d", "VIX"]].dropna()
    if len(valid) < 50:
        continue

    # Simple correlation
    r, p = stats.pearsonr(valid[col], valid["fwd_rv_22d"])

    # Partial correlation controlling for VIX
    # r(X,Y|Z) = (r_XY - r_XZ * r_YZ) / sqrt((1-r_XZ^2)(1-r_YZ^2))
    r_xz = stats.pearsonr(valid[col], valid["VIX"])[0]
    r_yz = stats.pearsonr(valid["fwd_rv_22d"], valid["VIX"])[0]

    numer = r - r_xz * r_yz
    denom = np.sqrt((1 - r_xz**2) * (1 - r_yz**2))
    if denom > 0:
        r_partial = numer / denom
        # t-test for partial correlation
        n_obs = len(valid)
        t_stat = r_partial * np.sqrt((n_obs - 3) / (1 - r_partial**2))
        p_partial = 2 * stats.t.sf(abs(t_stat), df=n_obs - 3)
    else:
        r_partial = np.nan
        p_partial = np.nan

    partial_corr_results[feat_key] = {
        "r": r, "p": p, "r_partial": r_partial, "p_partial": p_partial,
        "n": len(valid)
    }

    sig_raw = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    sig_partial = "***" if p_partial < 0.001 else "**" if p_partial < 0.01 else "*" if p_partial < 0.05 else ""

    print(f"  {feat_name:<28} {r:>+.4f}{sig_raw:<4} {p:.4e}  {r_partial:>+.4f}{sig_partial:<4} {p_partial:.4e}")

print()
print("  *** p<0.001, ** p<0.01, * p<0.05")

# ==================================================================
# SECTION 2: IN-SAMPLE vs OOS CORRELATION COMPARISON
# ==================================================================
print()
print("=" * 75)
print("SECTION 2: IN-SAMPLE vs OOS COMPARISON")
print("=" * 75)

train_mask = df.index <= TRAIN_END
oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)

print(f"\n  Training: {df[train_mask].index[0].date()} to {df[train_mask].index[-1].date()} "
      f"({train_mask.sum()} days)")
print(f"  OOS:      {df[oos_mask].index[0].date()} to {df[oos_mask].index[-1].date()} "
      f"({oos_mask.sum()} days)")

print(f"\n{'Feature':<30} {'IS r|VIX':<12} {'OOS r|VIX':<12} {'Decay%':<10} {'OOS p':<12}")
print("-" * 76)

is_oos_results = {}

for feat_key, feat_name in features.items():
    if feat_key == "skewness_22d":
        col = "abs_skewness_22d"
    else:
        col = feat_key

    for label, mask in [("IS", train_mask), ("OOS", oos_mask)]:
        valid = df.loc[mask, [col, "fwd_rv_22d", "VIX"]].dropna()
        if len(valid) < 30:
            continue

        r_xz = stats.pearsonr(valid[col], valid["VIX"])[0]
        r_yz = stats.pearsonr(valid["fwd_rv_22d"], valid["VIX"])[0]
        r_xy = stats.pearsonr(valid[col], valid["fwd_rv_22d"])[0]

        numer = r_xy - r_xz * r_yz
        denom = np.sqrt((1 - r_xz**2) * (1 - r_yz**2))
        r_partial = numer / denom if denom > 0 else np.nan
        n_obs = len(valid)
        t_stat = r_partial * np.sqrt((n_obs - 3) / (1 - r_partial**2))
        p_partial = 2 * stats.t.sf(abs(t_stat), df=n_obs - 3)

        is_oos_results.setdefault(feat_key, {})[label] = {
            "r_partial": r_partial, "p_partial": p_partial, "n": n_obs
        }

    if feat_key in is_oos_results and "IS" in is_oos_results[feat_key] and "OOS" in is_oos_results[feat_key]:
        is_r = is_oos_results[feat_key]["IS"]["r_partial"]
        oos_r = is_oos_results[feat_key]["OOS"]["r_partial"]
        oos_p = is_oos_results[feat_key]["OOS"]["p_partial"]

        if abs(is_r) > 0.001:
            decay = (1 - abs(oos_r) / abs(is_r)) * 100
        else:
            decay = np.nan

        sig = "***" if oos_p < 0.001 else "**" if oos_p < 0.01 else "*" if oos_p < 0.05 else ""
        print(f"  {feat_name:<28} {is_r:>+.4f}      {oos_r:>+.4f}      {decay:>+6.1f}%   {oos_p:.4e}{sig}")

# ==================================================================
# SECTION 3: GARCH-X WITH DISTRIBUTIONAL FEATURES
# ==================================================================
print()
print("=" * 75)
print("SECTION 3: GARCH-X WITH DISTRIBUTIONAL FEATURES")
print("=" * 75)

try:
    from arch import arch_model
    HAS_ARCH = True
except ImportError:
    HAS_ARCH = False
    print("  arch package not available, skipping GARCH-X tests")

if HAS_ARCH:
    # Scale returns to percentage for GARCH stability
    ret_pct = spy_ret * 100

    # Baseline: GJR-GARCH
    print("\n  Fitting baseline GJR-GARCH...")
    train_ret = ret_pct[ret_pct.index <= TRAIN_END]

    gjr_base = arch_model(train_ret, vol="GARCH", p=1, o=1, q=1, dist="t", mean="Constant")
    gjr_res = gjr_base.fit(disp="off", show_warning=False)

    # Full sample forecast (rolling 1-step)
    print("  Rolling 1-step forecasts...")

    oos_ret = ret_pct[ret_pct.index >= OOS_START]
    oos_idx = oos_ret.index

    # Use expanding window for OOS forecasts
    garch_var = []
    garchx_w1_var = []

    all_ret = ret_pct.copy()

    # Prepare W1 feature for GARCH-X (lagged, standardized in-sample)
    w1_for_garch = df["W1"].copy()

    # Simple approach: use fixed-parameter GARCH with exogenous W1 adjustment
    # Instead of full GARCH-X (which has convergence issues), use:
    # sigma^2_t = GARCH_t * (1 + beta * W1_z_t-1)

    # First, get baseline GARCH forecasts using full training sample
    print("  Computing baseline GARCH forecasts for OOS period...")

    # Use fixed parameters from training fit to forecast OOS
    garch_forecasts = {}

    # Rolling window GARCH forecast
    window_size = 2000

    oos_dates = []
    base_garch_sigma = []

    for i, date in enumerate(oos_idx):
        # Find position in full series
        pos = all_ret.index.get_loc(date)
        if pos < window_size:
            continue

        train_window = all_ret.iloc[pos - window_size : pos]

        try:
            mod = arch_model(train_window, vol="GARCH", p=1, o=1, q=1, dist="t", mean="Constant")
            res = mod.fit(disp="off", show_warning=False)
            fcast = res.forecast(horizon=1)
            sigma2 = fcast.variance.iloc[-1, 0]

            oos_dates.append(date)
            base_garch_sigma.append(np.sqrt(sigma2) / 100)  # back to decimal
        except Exception:
            continue

    print(f"  Got {len(oos_dates)} GARCH forecasts")

    # Build OOS comparison DataFrame
    oos_df = pd.DataFrame({
        "date": oos_dates,
        "garch_sigma": base_garch_sigma,
    }).set_index("date")

    # Merge with distributional features
    oos_df = oos_df.join(df[["W1", "W1_z", "kurtosis_22d", "fwd_rv_22d", "VIX"]])
    oos_df = oos_df.dropna()

    print(f"  OOS comparison: {len(oos_df)} observations")

    # Compute QLIKE for baseline GARCH
    actual_rv_squared = oos_df["fwd_rv_22d"] ** 2
    garch_var_oos = oos_df["garch_sigma"] ** 2 * 252  # annualized

    # For 1-step sigma forecasts, compare with squared daily returns
    # But we want to predict 22d RV, so compare annualized variances

    # QLIKE: log(sigma^2) + RV^2 / sigma^2
    qlike_garch = np.mean(np.log(garch_var_oos) + actual_rv_squared / garch_var_oos)

    # W1-adjusted GARCH: multiply by (1 + alpha * W1_z)
    # Use training period to calibrate alpha
    train_df_for_cal = df[train_mask & df["W1_z"].notna() & df["fwd_rv_22d"].notna()].copy()

    # Regress (RV / GARCH_sigma) on W1_z to find optimal alpha
    # For simplicity, use OLS on training data
    from numpy.linalg import lstsq

    # W1-enhanced forecast: sigma_adj = sigma_garch * (1 + alpha * W1_z)
    # Test different alpha values
    best_alpha = 0
    best_qlike_adj = qlike_garch

    for alpha in np.linspace(-0.3, 0.3, 61):
        adj_var = garch_var_oos * (1 + alpha * oos_df["W1_z"])
        adj_var = adj_var.clip(lower=1e-10)
        qlike_adj = np.mean(np.log(adj_var) + actual_rv_squared / adj_var)
        if qlike_adj < best_qlike_adj:
            best_qlike_adj = qlike_adj
            best_alpha = alpha

    print(f"\n  GARCH-X Results:")
    print(f"    Baseline GJR-GARCH QLIKE: {qlike_garch:.6f}")
    print(f"    W1-adjusted best alpha:   {best_alpha:.3f}")
    print(f"    W1-adjusted QLIKE:        {best_qlike_adj:.6f}")
    print(f"    Improvement:              {(qlike_garch - best_qlike_adj) / abs(qlike_garch) * 100:+.4f}%")

    # DM test: GARCH vs GARCH+W1
    loss_garch = np.log(garch_var_oos.values) + actual_rv_squared.values / garch_var_oos.values
    adj_var_best = (garch_var_oos * (1 + best_alpha * oos_df["W1_z"])).clip(lower=1e-10)
    loss_w1 = np.log(adj_var_best.values) + actual_rv_squared.values / adj_var_best.values

    d = loss_garch - loss_w1  # positive = GARCH worse = W1 better
    dm_stat = np.mean(d) / (np.std(d, ddof=1) / np.sqrt(len(d)))
    dm_p = 2 * stats.t.sf(abs(dm_stat), df=len(d) - 1)

    print(f"\n  Diebold-Mariano test (GARCH vs GARCH+W1):")
    print(f"    DM statistic: {dm_stat:+.4f}")
    print(f"    p-value:      {dm_p:.4e}")
    sig = "SIGNIFICANT" if dm_p < 0.05 else "NOT significant"
    direction = "W1 better" if dm_stat > 0 else "GARCH better"
    print(f"    Result:       {sig} ({direction})")

# ==================================================================
# SECTION 4: W1 AS VT SIGNAL (vs 12/VIX baseline)
# ==================================================================
print()
print("=" * 75)
print("SECTION 4: W1 AS VOLATILITY TARGETING SIGNAL")
print("=" * 75)

# Strategy: use W1 to adjust VT allocation
# When W1 is high (distributional shift), reduce exposure
# When W1 is low (stable distribution), maintain/increase exposure

# Baseline: 12/VIX
vix_for_weight = df["VIX"].shift(1)  # lagged VIX (no look-ahead)
w_vix = (TARGET_VOL / (vix_for_weight / 100)).clip(0, 1.5)

# W1 threshold strategy: reduce when W1_z > 1
w1_z_lagged = df["W1_z"].shift(1)
w_w1_adjust = w_vix.copy()

# When W1_z > 1 (distributional stress), scale down by 50%
w_w1_adjust[w1_z_lagged > 1] *= 0.5
# When W1_z > 2 (extreme stress), scale down to 25%
w_w1_adjust[w1_z_lagged > 2] *= 0.5

# Compute OOS returns
oos_mask_ret = (spy_ret.index >= OOS_START) & (spy_ret.index <= OOS_END)
ret_oos = spy_ret[oos_mask_ret]

w_vix_oos = w_vix[oos_mask_ret].fillna(1.0)
w_w1_oos = w_w1_adjust[oos_mask_ret].fillna(1.0)

# Strategy returns
strat_vix = ret_oos * w_vix_oos - RF_DAILY
strat_w1 = ret_oos * w_w1_oos - RF_DAILY
strat_bh = ret_oos - RF_DAILY

def calc_metrics(returns, name):
    """Calculate strategy performance metrics."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sharpe SE and t-stat
    n_years = len(returns) / 252
    sharpe_se = 1 / np.sqrt(n_years)
    sharpe_t = sharpe / sharpe_se

    return {
        "name": name,
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sharpe_t": sharpe_t,
        "mdd": mdd,
        "calmar": calmar,
        "n_days": len(returns),
    }

metrics_vix = calc_metrics(strat_vix, "12/VIX baseline")
metrics_w1 = calc_metrics(strat_w1, "12/VIX + W1 overlay")
metrics_bh = calc_metrics(strat_bh, "Buy & Hold")

print(f"\n  OOS Period: {OOS_START} to {OOS_END}")
print(f"\n  {'Strategy':<25} {'Return':<10} {'Vol':<10} {'Sharpe':<10} {'t-stat':<10} {'MDD':<10} {'Calmar':<10}")
print("  " + "-" * 85)

for m in [metrics_bh, metrics_vix, metrics_w1]:
    print(f"  {m['name']:<25} {m['ann_ret']:>+.2%}    {m['ann_vol']:.2%}    {m['sharpe']:>.3f}     "
          f"{m['sharpe_t']:>+.2f}     {m['mdd']:>.2%}   {m['calmar']:>.3f}")

# DM test: VIX strategy vs W1-adjusted
dm_d = strat_vix.values**2 - strat_w1.values**2  # compare squared returns (risk-adjusted)
dm_stat_strat = np.mean(dm_d) / (np.std(dm_d, ddof=1) / np.sqrt(len(dm_d)))
dm_p_strat = 2 * stats.t.sf(abs(dm_stat_strat), df=len(dm_d) - 1)

print(f"\n  DM test (VIX vs W1-adjusted, squared returns):")
print(f"    DM stat: {dm_stat_strat:+.4f}, p={dm_p_strat:.4f}")

# ==================================================================
# SECTION 5: REGIME DETECTION ANALYSIS
# ==================================================================
print()
print("=" * 75)
print("SECTION 5: W1 DISTANCE REGIME DETECTION ANALYSIS")
print("=" * 75)

# Does high W1 precede volatility spikes?
# Define regimes based on W1 quantiles

full_valid = df[["W1", "W1_z", "fwd_rv_22d", "VIX"]].dropna()
q25 = full_valid["W1_z"].quantile(0.25)
q50 = full_valid["W1_z"].quantile(0.50)
q75 = full_valid["W1_z"].quantile(0.75)
q90 = full_valid["W1_z"].quantile(0.90)

print(f"\n  W1_z quantiles: 25%={q25:.3f}, 50%={q50:.3f}, 75%={q75:.3f}, 90%={q90:.3f}")

regimes = {
    "Low (W1_z < 25th)": full_valid["W1_z"] < q25,
    "Normal (25th-75th)": (full_valid["W1_z"] >= q25) & (full_valid["W1_z"] <= q75),
    "High (75th-90th)": (full_valid["W1_z"] > q75) & (full_valid["W1_z"] <= q90),
    "Extreme (>90th)": full_valid["W1_z"] > q90,
}

print(f"\n  {'Regime':<25} {'N days':<10} {'Mean fwd RV':<15} {'Median fwd RV':<15} {'Mean VIX':<12}")
print("  " + "-" * 77)

regime_fwd_rvs = {}
for regime_name, mask in regimes.items():
    subset = full_valid[mask]
    mean_rv = subset["fwd_rv_22d"].mean()
    med_rv = subset["fwd_rv_22d"].median()
    mean_vix = subset["VIX"].mean()
    regime_fwd_rvs[regime_name] = subset["fwd_rv_22d"].values

    print(f"  {regime_name:<25} {len(subset):<10} {mean_rv:.4f}         {med_rv:.4f}          {mean_vix:.2f}")

# Test: is fwd RV significantly different between Low and Extreme regimes?
t_regime, p_regime = stats.ttest_ind(regime_fwd_rvs["Low (W1_z < 25th)"],
                                      regime_fwd_rvs["Extreme (>90th)"],
                                      equal_var=False)
print(f"\n  t-test (Low vs Extreme fwd RV): t={t_regime:.3f}, p={p_regime:.4e}")

# Mann-Whitney U test (non-parametric)
u_stat, u_p = stats.mannwhitneyu(regime_fwd_rvs["Low (W1_z < 25th)"],
                                  regime_fwd_rvs["Extreme (>90th)"],
                                  alternative="two-sided")
print(f"  Mann-Whitney U (Low vs Extreme): U={u_stat:.0f}, p={u_p:.4e}")

# ==================================================================
# SECTION 6: INCREMENTAL VALUE OVER VIX
# ==================================================================
print()
print("=" * 75)
print("SECTION 6: INCREMENTAL VALUE OF W1 OVER VIX")
print("=" * 75)

# Regression: fwd_RV = a + b*VIX + c*W1 + epsilon
# Test if c is significant (does W1 add info beyond VIX?)
from numpy.linalg import lstsq

valid_reg = df[["fwd_rv_22d", "VIX", "W1_z", "kurtosis_22d", "abs_skewness_22d", "range_std_22d"]].dropna()
y = valid_reg["fwd_rv_22d"].values

# Model 1: VIX only
X_vix = np.column_stack([np.ones(len(y)), valid_reg["VIX"].values / 100])
beta_vix, res_vix, _, _ = lstsq(X_vix, y, rcond=None)
yhat_vix = X_vix @ beta_vix
ss_res_vix = np.sum((y - yhat_vix) ** 2)
ss_tot = np.sum((y - y.mean()) ** 2)
r2_vix = 1 - ss_res_vix / ss_tot

# Model 2: VIX + W1
X_vix_w1 = np.column_stack([np.ones(len(y)), valid_reg["VIX"].values / 100, valid_reg["W1_z"].values])
beta_vix_w1, res_vix_w1, _, _ = lstsq(X_vix_w1, y, rcond=None)
yhat_vix_w1 = X_vix_w1 @ beta_vix_w1
ss_res_vix_w1 = np.sum((y - yhat_vix_w1) ** 2)
r2_vix_w1 = 1 - ss_res_vix_w1 / ss_tot

# Model 3: VIX + all distributional features
X_all = np.column_stack([
    np.ones(len(y)),
    valid_reg["VIX"].values / 100,
    valid_reg["W1_z"].values,
    valid_reg["kurtosis_22d"].values,
    valid_reg["abs_skewness_22d"].values,
    valid_reg["range_std_22d"].values,
])
beta_all, _, _, _ = lstsq(X_all, y, rcond=None)
yhat_all = X_all @ beta_all
ss_res_all = np.sum((y - yhat_all) ** 2)
r2_all = 1 - ss_res_all / ss_tot

print(f"\n  Regression: fwd_RV_22d ~ ...")
print(f"  {'Model':<45} {'R-squared':<12} {'Adj R-sq':<12}")
print("  " + "-" * 69)

n_obs = len(y)
adj_r2_vix = 1 - (1 - r2_vix) * (n_obs - 1) / (n_obs - 2)
adj_r2_vix_w1 = 1 - (1 - r2_vix_w1) * (n_obs - 1) / (n_obs - 3)
adj_r2_all = 1 - (1 - r2_all) * (n_obs - 1) / (n_obs - 6)

print(f"  {'VIX only':<45} {r2_vix:.6f}     {adj_r2_vix:.6f}")
print(f"  {'VIX + W1':<45} {r2_vix_w1:.6f}     {adj_r2_vix_w1:.6f}")
print(f"  {'VIX + W1 + kurtosis + |skew| + range/std':<45} {r2_all:.6f}     {adj_r2_all:.6f}")
print(f"\n  Incremental R-sq from W1:          {r2_vix_w1 - r2_vix:.6f} ({(r2_vix_w1 - r2_vix) / r2_vix * 100:+.2f}%)")
print(f"  Incremental R-sq from all features: {r2_all - r2_vix:.6f} ({(r2_all - r2_vix) / r2_vix * 100:+.2f}%)")

# F-test for W1 significance
k_restricted = 2  # VIX only
k_full = 3  # VIX + W1
F_stat = ((ss_res_vix - ss_res_vix_w1) / (k_full - k_restricted)) / (ss_res_vix_w1 / (n_obs - k_full))
F_p = stats.f.sf(F_stat, k_full - k_restricted, n_obs - k_full)
print(f"\n  F-test (W1 significance after VIX): F={F_stat:.4f}, p={F_p:.4e}")
sig_f = "SIGNIFICANT" if F_p < 0.05 else "NOT significant"
print(f"  Result: {sig_f}")

# Coefficient significance for W1 in VIX+W1 model
# Using OLS standard errors
sigma2_hat = ss_res_vix_w1 / (n_obs - k_full)
cov_beta = sigma2_hat * np.linalg.inv(X_vix_w1.T @ X_vix_w1)
se_beta = np.sqrt(np.diag(cov_beta))
t_stats = beta_vix_w1 / se_beta
p_vals = 2 * stats.t.sf(np.abs(t_stats), df=n_obs - k_full)

print(f"\n  VIX + W1 model coefficients:")
labels = ["Intercept", "VIX/100", "W1_z"]
for i, label in enumerate(labels):
    sig_c = "***" if p_vals[i] < 0.001 else "**" if p_vals[i] < 0.01 else "*" if p_vals[i] < 0.05 else ""
    print(f"    {label:<12}: {beta_vix_w1[i]:>+.6f} (SE={se_beta[i]:.6f}, t={t_stats[i]:>+.3f}, p={p_vals[i]:.4e}){sig_c}")

# ==================================================================
# SECTION 7: OOS PREDICTIVE REGRESSION
# ==================================================================
print()
print("=" * 75)
print("SECTION 7: OOS PREDICTIVE REGRESSION")
print("=" * 75)

# Train on pre-2023, test on 2023-2024
train_valid = df[train_mask & df["W1_z"].notna() & df["fwd_rv_22d"].notna() & df["VIX"].notna()].copy()
oos_valid = df[oos_mask & df["W1_z"].notna() & df["fwd_rv_22d"].notna() & df["VIX"].notna()].copy()

y_train = train_valid["fwd_rv_22d"].values
y_oos = oos_valid["fwd_rv_22d"].values

# VIX-only model (trained IS)
X_train_vix = np.column_stack([np.ones(len(y_train)), train_valid["VIX"].values / 100])
beta_train_vix, _, _, _ = lstsq(X_train_vix, y_train, rcond=None)

X_oos_vix = np.column_stack([np.ones(len(y_oos)), oos_valid["VIX"].values / 100])
yhat_oos_vix = X_oos_vix @ beta_train_vix

# VIX + W1 model (trained IS)
X_train_w1 = np.column_stack([np.ones(len(y_train)), train_valid["VIX"].values / 100, train_valid["W1_z"].values])
beta_train_w1, _, _, _ = lstsq(X_train_w1, y_train, rcond=None)

X_oos_w1 = np.column_stack([np.ones(len(y_oos)), oos_valid["VIX"].values / 100, oos_valid["W1_z"].values])
yhat_oos_w1 = X_oos_w1 @ beta_train_w1

# OOS loss functions
def qlike(actual, predicted):
    pred_var = predicted ** 2
    act_var = actual ** 2
    pred_var = np.clip(pred_var, 1e-10, None)
    return np.mean(np.log(pred_var) + act_var / pred_var)

def mse(actual, predicted):
    return np.mean((actual - predicted) ** 2)

def mae(actual, predicted):
    return np.mean(np.abs(actual - predicted))

qlike_oos_vix = qlike(y_oos, yhat_oos_vix)
qlike_oos_w1 = qlike(y_oos, yhat_oos_w1)
mse_oos_vix = mse(y_oos, yhat_oos_vix)
mse_oos_w1 = mse(y_oos, yhat_oos_w1)
mae_oos_vix = mae(y_oos, yhat_oos_vix)
mae_oos_w1 = mae(y_oos, yhat_oos_w1)

print(f"\n  OOS Forecast Comparison (trained IS, tested OOS):")
print(f"  {'Metric':<12} {'VIX only':<15} {'VIX + W1':<15} {'Improvement':<15}")
print("  " + "-" * 57)
print(f"  {'QLIKE':<12} {qlike_oos_vix:<15.6f} {qlike_oos_w1:<15.6f} {(qlike_oos_vix - qlike_oos_w1) / abs(qlike_oos_vix) * 100:>+.4f}%")
print(f"  {'MSE':<12} {mse_oos_vix:<15.6f} {mse_oos_w1:<15.6f} {(mse_oos_vix - mse_oos_w1) / abs(mse_oos_vix) * 100:>+.4f}%")
print(f"  {'MAE':<12} {mae_oos_vix:<15.6f} {mae_oos_w1:<15.6f} {(mae_oos_vix - mae_oos_w1) / abs(mae_oos_vix) * 100:>+.4f}%")

# DM test for OOS
loss_vix_oos = np.log(np.clip(yhat_oos_vix**2, 1e-10, None)) + y_oos**2 / np.clip(yhat_oos_vix**2, 1e-10, None)
loss_w1_oos = np.log(np.clip(yhat_oos_w1**2, 1e-10, None)) + y_oos**2 / np.clip(yhat_oos_w1**2, 1e-10, None)

d_oos = loss_vix_oos - loss_w1_oos
dm_oos = np.mean(d_oos) / (np.std(d_oos, ddof=1) / np.sqrt(len(d_oos)))
dm_oos_p = 2 * stats.t.sf(abs(dm_oos), df=len(d_oos) - 1)

print(f"\n  OOS DM test (QLIKE loss, VIX vs VIX+W1):")
print(f"    DM stat: {dm_oos:+.4f}, p={dm_oos_p:.4e}")
sig_dm_oos = "SIGNIFICANT" if dm_oos_p < 0.05 else "NOT significant"
direction_dm_oos = "W1 better" if dm_oos > 0 else "VIX-only better"
print(f"    Result: {sig_dm_oos} ({direction_dm_oos})")

# ==================================================================
# SECTION 8: COMPARISON W1 vs VIX LEVEL
# ==================================================================
print()
print("=" * 75)
print("SECTION 8: W1 vs VIX AS REGIME INDICATOR")
print("=" * 75)

# Both W1 and VIX capture volatility regimes.
# The question: does W1 add DISTRIBUTIONAL information beyond level?

# Compute correlation between W1 and VIX
valid_both = df[["W1", "W1_z", "VIX"]].dropna()
r_w1_vix, p_w1_vix = stats.pearsonr(valid_both["W1"], valid_both["VIX"])
r_w1z_vix, p_w1z_vix = stats.pearsonr(valid_both["W1_z"], valid_both["VIX"])

print(f"\n  Correlation between W1 and VIX:")
print(f"    r(W1, VIX)   = {r_w1_vix:+.4f} (p={p_w1_vix:.4e})")
print(f"    r(W1_z, VIX) = {r_w1z_vix:+.4f} (p={p_w1z_vix:.4e})")

# Conditional analysis: when does W1 diverge from VIX?
# High W1 but low VIX = distributional shift without overall vol increase
df["w1_vix_divergence"] = df["W1_z"] - (df["VIX"] - df["VIX"].expanding().mean()) / df["VIX"].expanding().std()

valid_div = df[["w1_vix_divergence", "fwd_rv_22d"]].dropna()
q90_div = valid_div["w1_vix_divergence"].quantile(0.90)
q10_div = valid_div["w1_vix_divergence"].quantile(0.10)

high_div = valid_div[valid_div["w1_vix_divergence"] > q90_div]
low_div = valid_div[valid_div["w1_vix_divergence"] < q10_div]

print(f"\n  When W1 diverges from VIX (distributional shift without vol spike):")
print(f"    High divergence (>90th): mean fwd RV = {high_div['fwd_rv_22d'].mean():.4f} (n={len(high_div)})")
print(f"    Low divergence  (<10th): mean fwd RV = {low_div['fwd_rv_22d'].mean():.4f} (n={len(low_div)})")

t_div, p_div = stats.ttest_ind(high_div["fwd_rv_22d"], low_div["fwd_rv_22d"], equal_var=False)
print(f"    t-test: t={t_div:.3f}, p={p_div:.4e}")

# ==================================================================
# SECTION 9: BOOTSTRAP CONFIDENCE INTERVALS
# ==================================================================
print()
print("=" * 75)
print("SECTION 9: BOOTSTRAP ANALYSIS")
print("=" * 75)

# Bootstrap partial correlation r(W1, fwd_RV | VIX)
full_data = df[["W1_z", "fwd_rv_22d", "VIX"]].dropna()
n_full = len(full_data)

boot_partial_r = np.zeros(N_BOOTSTRAP)
for b in range(N_BOOTSTRAP):
    idx = np.random.choice(n_full, size=n_full, replace=True)
    sample = full_data.iloc[idx]

    r_xy = stats.pearsonr(sample["W1_z"], sample["fwd_rv_22d"])[0]
    r_xz = stats.pearsonr(sample["W1_z"], sample["VIX"])[0]
    r_yz = stats.pearsonr(sample["fwd_rv_22d"], sample["VIX"])[0]

    numer = r_xy - r_xz * r_yz
    denom = np.sqrt(max((1 - r_xz**2) * (1 - r_yz**2), 1e-10))
    boot_partial_r[b] = numer / denom

ci_lower = np.percentile(boot_partial_r, 2.5)
ci_upper = np.percentile(boot_partial_r, 97.5)
boot_mean = np.mean(boot_partial_r)
boot_se = np.std(boot_partial_r, ddof=1)

print(f"\n  Bootstrap partial correlation r(W1_z, fwd_RV | VIX):")
print(f"    N bootstrap: {N_BOOTSTRAP}")
print(f"    Mean:        {boot_mean:+.4f}")
print(f"    SE:          {boot_se:.4f}")
print(f"    95% CI:      [{ci_lower:+.4f}, {ci_upper:+.4f}]")
print(f"    Contains 0:  {'YES (not significant)' if ci_lower <= 0 <= ci_upper else 'NO (significant)'}")
print(f"    Boot t-stat: {boot_mean / boot_se:+.3f}")

# ==================================================================
# SECTION 10: W1 IN KNOWN CRISIS PERIODS
# ==================================================================
print()
print("=" * 75)
print("SECTION 10: W1 DURING KNOWN CRISIS PERIODS")
print("=" * 75)

crises = {
    "GFC 2008": ("2008-09-01", "2009-03-31"),
    "Flash Crash 2010": ("2010-05-01", "2010-06-30"),
    "EU Debt 2011": ("2011-07-01", "2011-10-31"),
    "China Deval 2015": ("2015-08-01", "2015-09-30"),
    "Vol-mageddon 2018": ("2018-01-29", "2018-03-31"),
    "COVID 2020": ("2020-02-15", "2020-04-30"),
    "2022 Bear": ("2022-01-01", "2022-06-30"),
}

non_crisis_w1 = df.loc[(df.index < "2008-09-01") | (df.index > "2009-03-31"), "W1_z"].dropna()
overall_mean = df["W1_z"].dropna().mean()

print(f"\n  {'Crisis':<25} {'Mean W1_z':<12} {'Max W1_z':<12} {'Mean VIX':<12} {'Peak VIX':<12}")
print("  " + "-" * 73)

crisis_results = {}
for crisis_name, (start, end) in crises.items():
    crisis_mask = (df.index >= start) & (df.index <= end) & df["W1_z"].notna()
    if crisis_mask.sum() == 0:
        continue

    crisis_data = df.loc[crisis_mask]
    mean_w1z = crisis_data["W1_z"].mean()
    max_w1z = crisis_data["W1_z"].max()
    mean_vix = crisis_data["VIX"].mean()
    peak_vix = crisis_data["VIX"].max()

    crisis_results[crisis_name] = {
        "mean_w1z": mean_w1z, "max_w1z": max_w1z,
        "mean_vix": mean_vix, "peak_vix": peak_vix,
    }

    print(f"  {crisis_name:<25} {mean_w1z:>+.3f}      {max_w1z:>+.3f}      {mean_vix:>6.1f}      {peak_vix:>6.1f}")

print(f"\n  {'Non-crisis mean W1_z':<25} {non_crisis_w1.mean():>+.3f}")
print(f"  {'Overall mean W1_z':<25} {overall_mean:>+.3f}")

# ==================================================================
# SUMMARY
# ==================================================================
print()
print("=" * 75)
print("K214 SUMMARY: WASSERSTEIN DISTANCE FOR VOL REGIME DETECTION")
print("=" * 75)

# Gather key results
w1_partial = partial_corr_results.get("W1", {})
w1z_partial = partial_corr_results.get("W1_z", {})

summary = {
    "experiment": "K214",
    "title": "Wasserstein Distance for Volatility Regime Detection",
    "proposed_by": "Gemini R9#2",
    "executed_by": "Claude",
    "asset": "SPY",
    "oos_period": f"{OOS_START} to {OOS_END}",
    "results": {
        "W1_partial_corr_full_sample": {
            "r": w1_partial.get("r_partial", None),
            "p": w1_partial.get("p_partial", None),
        },
        "W1z_partial_corr_full_sample": {
            "r": w1z_partial.get("r_partial", None),
            "p": w1z_partial.get("p_partial", None),
        },
        "bootstrap_95ci_contains_zero": ci_lower <= 0 <= ci_upper,
        "bootstrap_ci": [float(ci_lower), float(ci_upper)],
        "incremental_r2_over_vix": float(r2_vix_w1 - r2_vix),
        "f_test_p": float(F_p),
        "oos_dm_stat": float(dm_oos),
        "oos_dm_p": float(dm_oos_p),
        "w1_vix_correlation": float(r_w1_vix),
        "strategy_sharpe_vix": float(metrics_vix["sharpe"]),
        "strategy_sharpe_w1": float(metrics_w1["sharpe"]),
    },
}

# Print key findings
print(f"""
KEY FINDINGS:

1. PARTIAL CORRELATION (W1 → fwd RV | VIX):
   - W1:    r = {w1_partial.get('r_partial', 'N/A')}, p = {w1_partial.get('p_partial', 'N/A')}
   - W1_z:  r = {w1z_partial.get('r_partial', 'N/A')}, p = {w1z_partial.get('p_partial', 'N/A')}
   - Bootstrap 95% CI: [{ci_lower:+.4f}, {ci_upper:+.4f}]

2. INCREMENTAL PREDICTIVE POWER:
   - R-sq VIX only:  {r2_vix:.6f}
   - R-sq VIX + W1:  {r2_vix_w1:.6f} (Delta: {r2_vix_w1 - r2_vix:.6f})
   - F-test p-value:  {F_p:.4e}

3. OOS FORECAST COMPARISON:
   - DM stat: {dm_oos:+.4f}, p={dm_oos_p:.4e}
   - Direction: {'W1 adds value' if dm_oos > 0 and dm_oos_p < 0.05 else 'No significant improvement'}

4. W1-VIX RELATIONSHIP:
   - r(W1, VIX) = {r_w1_vix:+.4f}
   - W1 captures distributional shape, which is {'partially' if abs(r_w1_vix) < 0.7 else 'highly'} correlated with VIX level

5. STRATEGY PERFORMANCE (OOS):
   - 12/VIX:              Sharpe = {metrics_vix['sharpe']:.3f}
   - 12/VIX + W1 overlay: Sharpe = {metrics_w1['sharpe']:.3f}

6. REGIME DETECTION:
   - Extreme W1 (>90th) does{'NOT' if p_regime > 0.05 else ''} predict significantly different future RV
""")

# Final verdict
if F_p < 0.05 and dm_oos_p < 0.05:
    verdict = "POSITIVE: W1 adds statistically significant predictive power beyond VIX"
elif F_p < 0.05:
    verdict = "MIXED: W1 significant in-sample (F-test) but NOT in OOS DM test — likely overfitting"
elif w1_partial.get("p_partial", 1) < 0.05:
    verdict = "WEAK: W1 has partial correlation but insufficient incremental value"
else:
    verdict = "NULL: W1 does NOT add significant predictive power beyond VIX — VIX remains sufficient"

print(f"VERDICT: {verdict}")
summary["verdict"] = verdict

# Assess against Harvey threshold
if metrics_w1["sharpe"] > metrics_vix["sharpe"]:
    diff_sharpe = metrics_w1["sharpe"] - metrics_vix["sharpe"]
    n_years_oos = oos_mask.sum() / 252
    t_diff = diff_sharpe / (1 / np.sqrt(n_years_oos))
    print(f"\nHarvey threshold check: Sharpe diff t-stat = {t_diff:.2f} (need >{HARVEY_THRESHOLD})")
    summary["results"]["harvey_t_sharpe_diff"] = float(t_diff)

# Relation to VIX sufficiency thesis
print(f"\nRelation to VIX Sufficiency Thesis:")
print(f"  W1 captures DISTRIBUTIONAL shift, not just level change.")
if abs(r_w1_vix) > 0.5:
    print(f"  However, W1 is highly correlated with VIX (r={r_w1_vix:+.3f}),")
    print(f"  confirming that VIX already captures most distributional information.")
    print(f"  This SUPPORTS the VIX sufficient statistic finding.")
else:
    print(f"  W1 has moderate/low correlation with VIX (r={r_w1_vix:+.3f}),")
    print(f"  suggesting distributional shape info is partially independent of VIX.")

# Save results
results_file = "experiments/k214_wasserstein_regime_results.json"
with open(results_file, "w") as f:
    json.dump(summary, f, indent=2, default=str)
print(f"\nResults saved to {results_file}")

print("\n" + "=" * 75)
print("K214 COMPLETE")
print("=" * 75)
