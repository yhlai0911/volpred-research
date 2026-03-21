"""
K134: Cross-Asset Information Topology — TDA + Transfer Entropy Combined
========================================================================
[提出: Gemini Round 2 #2, 執行: Claude]

結合 K128 (Transfer Entropy) 和 K131 (TDA) 的跨學科實驗。
核心問題：如果 VIX 具有 economic sufficiency，其拓撲特徵的變化
是否領先於資產間依賴關係的崩潰？

方法論（精簡版）：
1. 5 資產 rolling 22d realized vol 矩陣
2. Sliding window (252d, step=22d) 計算：
   - Eigenvalue ratio (λ1/Σλ) 作為市場耦合度 proxy
   - Binned Transfer Entropy (VIX → each asset RV)
3. 分析 eigenvalue ratio 與 TE 的共演化
4. 危機前後動態

結論強度：descriptive/exploratory
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import os
from datetime import datetime
import time

print("=" * 70)
print("K134: Cross-Asset Information Topology")
print("       TDA Eigenvalue Proxy + Transfer Entropy Combined")
print("=" * 70)

# ============================================================
# 1. DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance ...")

assets = ["SPY", "QQQ", "GLD", "TLT", "EEM"]
vix_ticker = "^VIX"

t0 = time.time()

# Download all assets + VIX
data = {}
for ticker in assets + [vix_ticker]:
    df_raw = yf.download(ticker, start="2006-01-01", end="2025-01-01", progress=False)
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)
    data[ticker] = df_raw["Close"]

# Merge into single DataFrame
prices = pd.DataFrame(data)
prices.columns = assets + ["VIX"]
prices = prices.dropna()

print(f"   Date range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
print(f"   Observations: {len(prices)}")
print(f"   Assets: {assets}")

# ============================================================
# 2. COMPUTE REALIZED VOLATILITIES
# ============================================================
print("\n[2] Computing rolling 22d realized volatilities ...")

# Log returns
log_returns = np.log(prices / prices.shift(1))

# 22-day rolling realized volatility (annualized)
rv_window = 22
rv = log_returns.rolling(rv_window).std() * np.sqrt(252)
rv = rv.dropna()

# Separate VIX level (not RV of VIX, but VIX itself)
vix_level = prices["VIX"].reindex(rv.index)

# Asset RVs (excluding VIX column from RV — we use VIX level instead)
asset_rv = rv[assets]

print(f"   RV data: {rv.index[0].strftime('%Y-%m-%d')} to {rv.index[-1].strftime('%Y-%m-%d')}")
print(f"   RV observations: {len(rv)}")
for a in assets:
    print(f"   {a} RV: mean={asset_rv[a].mean()*100:.1f}%, std={asset_rv[a].std()*100:.1f}%")
print(f"   VIX: mean={vix_level.mean():.1f}, std={vix_level.std():.1f}")

# ============================================================
# 3. EIGENVALUE RATIO — MARKET COUPLING PROXY
# ============================================================
print("\n[3] Computing rolling eigenvalue ratio (market coupling) ...")

window = 252
step = 22  # monthly stepping

# Prepare correlation matrix series
dates_eigen = []
eigen_ratios = []
n_components_80 = []  # number of components explaining 80% variance

idx = rv.index
valid_start = rv_window  # skip initial RV estimation period

for start_pos in range(0, len(idx) - window, step):
    end_pos = start_pos + window
    window_data = asset_rv.iloc[start_pos:end_pos]

    # Skip if too many NaNs
    if window_data.isna().sum().sum() > window * 0.1:
        continue

    window_data = window_data.dropna()
    if len(window_data) < window * 0.8:
        continue

    # Correlation matrix of asset RVs
    corr_matrix = window_data.corr().values

    # Eigenvalue decomposition
    eigenvalues = np.linalg.eigvalsh(corr_matrix)
    eigenvalues = np.sort(eigenvalues)[::-1]  # descending

    # Eigenvalue ratio: λ1 / Σλ
    total = eigenvalues.sum()
    ratio = eigenvalues[0] / total if total > 0 else np.nan

    # Number of components for 80% variance
    cumsum = np.cumsum(eigenvalues) / total
    n80 = np.searchsorted(cumsum, 0.80) + 1

    dates_eigen.append(idx[end_pos - 1])
    eigen_ratios.append(ratio)
    n_components_80.append(n80)

eigen_df = pd.DataFrame({
    "date": dates_eigen,
    "eigen_ratio": eigen_ratios,
    "n_components_80pct": n_components_80
}).set_index("date")

print(f"   Windows computed: {len(eigen_df)}")
print(f"   Eigenvalue ratio: mean={eigen_df['eigen_ratio'].mean():.3f}, "
      f"std={eigen_df['eigen_ratio'].std():.3f}")
print(f"   Range: [{eigen_df['eigen_ratio'].min():.3f}, {eigen_df['eigen_ratio'].max():.3f}]")
print(f"   N components (80%): mean={eigen_df['n_components_80pct'].mean():.1f}")

# ============================================================
# 4. BINNED TRANSFER ENTROPY (SIMPLIFIED)
# ============================================================
print("\n[4] Computing rolling Transfer Entropy (VIX → asset RV) ...")

def binned_transfer_entropy(source, target, n_bins=3, lag=1):
    """
    Estimate Transfer Entropy TE(source → target) using binning.
    TE = H(target_future | target_past) - H(target_future | target_past, source_past)

    Simplified: discretize into n_bins quantile bins, then compute
    TE = Σ p(y_{t+1}, y_t, x_t) * log[ p(y_{t+1}|y_t, x_t) / p(y_{t+1}|y_t) ]
    """
    n = len(source)
    if n < 50:
        return np.nan

    # Quantile binning
    try:
        s_bins = pd.qcut(source, n_bins, labels=False, duplicates='drop').astype(int)
        t_bins = pd.qcut(target, n_bins, labels=False, duplicates='drop').astype(int)
    except (ValueError, TypeError):
        return np.nan

    # Construct (y_{t+lag}, y_t, x_t) tuples
    y_future = t_bins[lag:]
    y_past = t_bins[:-lag]
    x_past = s_bins[:-lag]

    n_valid = len(y_future)

    # Count joint and marginal probabilities
    # Using direct counting for speed
    max_bin = n_bins

    # Joint: p(y_future, y_past, x_past)
    joint_3 = {}
    joint_2_yx = {}  # p(y_future, y_past)
    joint_2_ypxp = {}  # p(y_past, x_past)
    marginal_yp = {}  # p(y_past)

    for i in range(n_valid):
        yf = int(y_future.iloc[i]) if hasattr(y_future, 'iloc') else int(y_future[i])
        yp = int(y_past.iloc[i]) if hasattr(y_past, 'iloc') else int(y_past[i])
        xp = int(x_past.iloc[i]) if hasattr(x_past, 'iloc') else int(x_past[i])

        key3 = (yf, yp, xp)
        joint_3[key3] = joint_3.get(key3, 0) + 1

        key_yx = (yf, yp)
        joint_2_yx[key_yx] = joint_2_yx.get(key_yx, 0) + 1

        key_ypxp = (yp, xp)
        joint_2_ypxp[key_ypxp] = joint_2_ypxp.get(key_ypxp, 0) + 1

        marginal_yp[yp] = marginal_yp.get(yp, 0) + 1

    # Compute TE
    te = 0.0
    for (yf, yp, xp), count3 in joint_3.items():
        p_yf_yp_xp = count3 / n_valid
        p_yf_yp = joint_2_yx.get((yf, yp), 0) / n_valid
        p_yp_xp = joint_2_ypxp.get((yp, xp), 0) / n_valid
        p_yp = marginal_yp.get(yp, 0) / n_valid

        if p_yf_yp > 0 and p_yp_xp > 0 and p_yp > 0:
            # TE = Σ p(yf,yp,xp) * log[ p(yf|yp,xp) / p(yf|yp) ]
            #    = Σ p(yf,yp,xp) * log[ p(yf,yp,xp)*p(yp) / (p(yf,yp)*p(yp,xp)) ]
            ratio = (p_yf_yp_xp * p_yp) / (p_yf_yp * p_yp_xp)
            if ratio > 0:
                te += p_yf_yp_xp * np.log2(ratio)

    return te


def te_significance(source, target, n_bins=3, lag=1, n_surr=100):
    """Shuffle test for TE significance."""
    te_real = binned_transfer_entropy(source, target, n_bins, lag)
    if np.isnan(te_real):
        return te_real, np.nan, np.nan

    te_surr = []
    rng = np.random.RandomState(42)
    for _ in range(n_surr):
        shuffled = source.copy()
        if hasattr(shuffled, 'values'):
            vals = shuffled.values.copy()
            rng.shuffle(vals)
            shuffled = pd.Series(vals, index=shuffled.index)
        else:
            rng.shuffle(shuffled)
        te_s = binned_transfer_entropy(shuffled, target, n_bins, lag)
        if not np.isnan(te_s):
            te_surr.append(te_s)

    if len(te_surr) < 10:
        return te_real, np.nan, np.nan

    te_surr = np.array(te_surr)
    z_score = (te_real - te_surr.mean()) / (te_surr.std() + 1e-12)
    p_value = 1 - stats.norm.cdf(z_score)

    return te_real, z_score, p_value


# --- 4a. Static full-sample TE ---
print("\n   [4a] Full-sample TE (VIX → asset RV) with significance test ...")

# Use VIX changes (not levels) for TE
vix_changes = vix_level.pct_change().dropna()
common_idx = asset_rv.index.intersection(vix_changes.index)

te_results = {}
for asset in assets:
    src = vix_changes.reindex(common_idx).dropna()
    tgt = asset_rv[asset].reindex(common_idx).dropna()

    # Align
    common = src.index.intersection(tgt.index)
    src = src.reindex(common)
    tgt = tgt.reindex(common)

    te_val, z, p = te_significance(src, tgt, n_bins=3, lag=1, n_surr=200)
    te_results[asset] = {"te": te_val, "z": z, "p": p}
    sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
    print(f"   TE(VIX → {asset:>4s} RV) = {te_val:.4f} bits  z={z:.2f}  p={p:.4f} {sig}")

# --- 4b. Rolling TE ---
print("\n   [4b] Rolling TE (252d window, 22d step) ...")

te_rolling = {asset: [] for asset in assets}
te_dates = []

for start_pos in range(0, len(common_idx) - window, step):
    end_pos = start_pos + window
    window_idx = common_idx[start_pos:end_pos]

    src_w = vix_changes.reindex(window_idx).dropna()

    te_vals_this = {}
    valid = True
    for asset in assets:
        tgt_w = asset_rv[asset].reindex(window_idx).dropna()
        cidx = src_w.index.intersection(tgt_w.index)
        if len(cidx) < 100:
            valid = False
            break
        te_val = binned_transfer_entropy(src_w.reindex(cidx), tgt_w.reindex(cidx), n_bins=3, lag=1)
        te_vals_this[asset] = te_val

    if valid and all(not np.isnan(v) for v in te_vals_this.values()):
        te_dates.append(common_idx[end_pos - 1])
        for asset in assets:
            te_rolling[asset].append(te_vals_this[asset])

te_df = pd.DataFrame(te_rolling, index=te_dates)
te_df["mean_TE"] = te_df.mean(axis=1)

print(f"   Rolling TE windows computed: {len(te_df)}")
for asset in assets:
    print(f"   {asset}: mean TE={te_df[asset].mean():.4f}, std={te_df[asset].std():.4f}")

# ============================================================
# 5. ALIGN & ANALYZE CO-EVOLUTION
# ============================================================
print("\n[5] Analyzing eigenvalue ratio vs TE co-evolution ...")

# Align on common dates (nearest date matching)
common_dates = eigen_df.index.intersection(te_df.index)
if len(common_dates) < 10:
    # Try nearest-date matching
    from functools import reduce
    all_dates_e = set(eigen_df.index)
    all_dates_t = set(te_df.index)
    # Match each eigen date to nearest TE date
    matched = []
    for d in eigen_df.index:
        diffs = [(abs((d - td).days), td) for td in te_df.index]
        if diffs:
            best_diff, best_td = min(diffs)
            if best_diff <= 15:  # within 15 days
                matched.append((d, best_td))

    if matched:
        eigen_aligned = eigen_df.loc[[m[0] for m in matched], "eigen_ratio"].values
        te_aligned = te_df.loc[[m[1] for m in matched], "mean_TE"].values
        dates_aligned = [m[0] for m in matched]
    else:
        eigen_aligned = np.array([])
        te_aligned = np.array([])
        dates_aligned = []
else:
    eigen_aligned = eigen_df.loc[common_dates, "eigen_ratio"].values
    te_aligned = te_df.loc[common_dates, "mean_TE"].values
    dates_aligned = list(common_dates)

print(f"   Aligned observations: {len(dates_aligned)}")

# 5a. Contemporaneous correlation
if len(eigen_aligned) > 10:
    corr_contemp, p_contemp = stats.pearsonr(eigen_aligned, te_aligned)
    rho_contemp, p_rho = stats.spearmanr(eigen_aligned, te_aligned)
    print(f"\n   [5a] Contemporaneous correlation:")
    print(f"   Pearson  r = {corr_contemp:.3f}  (p={p_contemp:.4f})")
    print(f"   Spearman ρ = {rho_contemp:.3f}  (p={p_rho:.4f})")
else:
    corr_contemp, p_contemp = np.nan, np.nan
    rho_contemp, p_rho = np.nan, np.nan
    print("   Insufficient aligned data for correlation.")

# 5b. Lead-lag analysis
print(f"\n   [5b] Lead-lag analysis (eigen_ratio leading/lagging TE):")
lead_lag_results = {}
if len(eigen_aligned) > 20:
    for lag in [-3, -2, -1, 0, 1, 2, 3]:
        if lag >= 0:
            e = eigen_aligned[:len(eigen_aligned)-lag] if lag > 0 else eigen_aligned
            t = te_aligned[lag:] if lag > 0 else te_aligned
        else:
            e = eigen_aligned[-lag:]
            t = te_aligned[:len(te_aligned)+lag]

        if len(e) > 10 and len(t) > 10:
            min_len = min(len(e), len(t))
            r, p = stats.pearsonr(e[:min_len], t[:min_len])
            lead_lag_results[lag] = {"r": r, "p": p}
            leader = "eigen→TE" if lag > 0 else ("TE→eigen" if lag < 0 else "contemp")
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
            print(f"   Lag={lag:+d} ({leader:>10s}): r={r:.3f}  p={p:.4f} {sig}")

# 5c. Granger-like test using lagged cross-correlation
print(f"\n   [5c] Best lead-lag structure:")
if lead_lag_results:
    best_lag = max(lead_lag_results, key=lambda k: abs(lead_lag_results[k]["r"]))
    print(f"   Best lag: {best_lag:+d} (r={lead_lag_results[best_lag]['r']:.3f}, p={lead_lag_results[best_lag]['p']:.4f})")
    if best_lag > 0:
        print(f"   → Eigenvalue ratio LEADS Transfer Entropy by ~{best_lag} months")
    elif best_lag < 0:
        print(f"   → Transfer Entropy LEADS Eigenvalue ratio by ~{-best_lag} months")
    else:
        print(f"   → Contemporaneous relationship is strongest")

# ============================================================
# 6. CRISIS DYNAMICS
# ============================================================
print("\n[6] Crisis dynamics analysis ...")

crisis_periods = {
    "GFC_2008": ("2008-09-01", "2009-03-31"),
    "Euro_2011": ("2011-07-01", "2011-12-31"),
    "China_2015": ("2015-08-01", "2015-12-31"),
    "COVID_2020": ("2020-02-01", "2020-05-31"),
    "Rate_Hike_2022": ("2022-01-01", "2022-12-31"),
}

# Also define pre-crisis windows (6 months before)
pre_crisis_windows = {
    "GFC_2008": ("2008-03-01", "2008-08-31"),
    "Euro_2011": ("2011-01-01", "2011-06-30"),
    "China_2015": ("2015-02-01", "2015-07-31"),
    "COVID_2020": ("2019-08-01", "2020-01-31"),
    "Rate_Hike_2022": ("2021-07-01", "2021-12-31"),
}

# Normal period: 2013-01-01 to 2014-12-31
normal_start, normal_end = "2013-01-01", "2014-12-31"

print(f"\n   Normal period baseline ({normal_start} to {normal_end}):")
normal_eigen = eigen_df.loc[normal_start:normal_end, "eigen_ratio"]
normal_te = te_df.loc[normal_start:normal_end, "mean_TE"]
if len(normal_eigen) > 0 and len(normal_te) > 0:
    print(f"   Eigen ratio: {normal_eigen.mean():.3f} ± {normal_eigen.std():.3f}")
    print(f"   Mean TE:     {normal_te.mean():.4f} ± {normal_te.std():.4f}")

crisis_table = []
for crisis_name, (cs, ce) in crisis_periods.items():
    ps, pe = pre_crisis_windows[crisis_name]

    # Pre-crisis
    pre_eigen = eigen_df.loc[ps:pe, "eigen_ratio"]
    pre_te = te_df.loc[ps:pe, "mean_TE"]

    # During crisis
    crisis_eigen = eigen_df.loc[cs:ce, "eigen_ratio"]
    crisis_te = te_df.loc[cs:ce, "mean_TE"]

    if len(pre_eigen) > 0 and len(crisis_eigen) > 0:
        eigen_change = crisis_eigen.mean() - pre_eigen.mean()
        eigen_pct = eigen_change / pre_eigen.mean() * 100
    else:
        eigen_change, eigen_pct = np.nan, np.nan

    if len(pre_te) > 0 and len(crisis_te) > 0:
        te_change = crisis_te.mean() - pre_te.mean()
        te_pct = te_change / (pre_te.mean() + 1e-10) * 100
    else:
        te_change, te_pct = np.nan, np.nan

    row = {
        "crisis": crisis_name,
        "pre_eigen": pre_eigen.mean() if len(pre_eigen) > 0 else np.nan,
        "crisis_eigen": crisis_eigen.mean() if len(crisis_eigen) > 0 else np.nan,
        "eigen_change_pct": eigen_pct,
        "pre_te": pre_te.mean() if len(pre_te) > 0 else np.nan,
        "crisis_te": crisis_te.mean() if len(crisis_te) > 0 else np.nan,
        "te_change_pct": te_pct,
    }
    crisis_table.append(row)

    print(f"\n   {crisis_name}:")
    print(f"   Pre-crisis  eigen={row['pre_eigen']:.3f}  TE={row['pre_te']:.4f}" if not np.isnan(row['pre_eigen']) else f"   Pre-crisis: insufficient data")
    print(f"   Crisis      eigen={row['crisis_eigen']:.3f}  TE={row['crisis_te']:.4f}" if not np.isnan(row['crisis_eigen']) else f"   Crisis: insufficient data")
    if not np.isnan(eigen_pct):
        eigen_dir = "↑" if eigen_pct > 0 else "↓"
        te_dir = "↑" if te_pct > 0 else "↓"
        print(f"   Change:     eigen {eigen_dir}{abs(eigen_pct):.1f}%   TE {te_dir}{abs(te_pct):.1f}%")

# ============================================================
# 7. REGIME ANALYSIS — HIGH vs LOW COUPLING
# ============================================================
print("\n[7] Regime analysis: high vs low coupling periods ...")

if len(eigen_df) > 10:
    median_eigen = eigen_df["eigen_ratio"].median()
    high_coupling = eigen_df[eigen_df["eigen_ratio"] > median_eigen]
    low_coupling = eigen_df[eigen_df["eigen_ratio"] <= median_eigen]

    print(f"   Median eigenvalue ratio: {median_eigen:.3f}")
    print(f"   High coupling periods: {len(high_coupling)}")
    print(f"   Low coupling periods:  {len(low_coupling)}")

    # Compare TE in high vs low coupling
    high_te = te_df.reindex(high_coupling.index).dropna()["mean_TE"]
    low_te = te_df.reindex(low_coupling.index).dropna()["mean_TE"]

    # Nearest-date matching for those not exactly aligned
    if len(high_te) < 5 or len(low_te) < 5:
        high_te_vals = []
        low_te_vals = []
        for d in high_coupling.index:
            diffs = [(abs((d - td).days), td) for td in te_df.index]
            if diffs:
                best_diff, best_td = min(diffs)
                if best_diff <= 15:
                    high_te_vals.append(te_df.loc[best_td, "mean_TE"])
        for d in low_coupling.index:
            diffs = [(abs((d - td).days), td) for td in te_df.index]
            if diffs:
                best_diff, best_td = min(diffs)
                if best_diff <= 15:
                    low_te_vals.append(te_df.loc[best_td, "mean_TE"])
        high_te = pd.Series(high_te_vals)
        low_te = pd.Series(low_te_vals)

    if len(high_te) > 5 and len(low_te) > 5:
        print(f"\n   High coupling → mean TE: {high_te.mean():.4f} ± {high_te.std():.4f}")
        print(f"   Low coupling  → mean TE: {low_te.mean():.4f} ± {low_te.std():.4f}")

        t_stat, p_val = stats.ttest_ind(high_te, low_te, equal_var=False)
        mw_stat, mw_p = stats.mannwhitneyu(high_te, low_te, alternative='two-sided')

        print(f"   Welch t-test: t={t_stat:.3f}, p={p_val:.4f}")
        print(f"   Mann-Whitney: U={mw_stat:.0f}, p={mw_p:.4f}")

        if p_val < 0.05:
            direction = "higher" if high_te.mean() > low_te.mean() else "lower"
            print(f"   → Significant: TE is {direction} during high coupling (p<0.05)")
        else:
            print(f"   → Not significant: TE does not differ between coupling regimes")

# ============================================================
# 8. ASSET-SPECIFIC TE vs EIGENVALUE RATIO
# ============================================================
print("\n[8] Asset-specific TE vs eigenvalue ratio ...")

for asset in assets:
    if asset not in te_df.columns:
        continue

    # Align
    te_asset = te_df[asset]
    common = eigen_df.index.intersection(te_asset.index)

    if len(common) < 5:
        # Nearest-date match
        matched_e = []
        matched_t = []
        for d in eigen_df.index:
            diffs = [(abs((d - td).days), td) for td in te_asset.index]
            if diffs:
                best_diff, best_td = min(diffs)
                if best_diff <= 15:
                    matched_e.append(eigen_df.loc[d, "eigen_ratio"])
                    matched_t.append(te_asset.loc[best_td])
        if len(matched_e) > 10:
            r, p = stats.pearsonr(matched_e, matched_t)
            rho, rho_p = stats.spearmanr(matched_e, matched_t)
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
            print(f"   {asset:>4s}: Pearson r={r:.3f} (p={p:.4f}{sig})  Spearman ρ={rho:.3f} (p={rho_p:.4f})")
        else:
            print(f"   {asset:>4s}: Insufficient aligned data")
    else:
        e_vals = eigen_df.loc[common, "eigen_ratio"].values
        t_vals = te_asset.loc[common].values
        r, p = stats.pearsonr(e_vals, t_vals)
        rho, rho_p = stats.spearmanr(e_vals, t_vals)
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
        print(f"   {asset:>4s}: Pearson r={r:.3f} (p={p:.4f}{sig})  Spearman ρ={rho:.3f} (p={rho_p:.4f})")

# ============================================================
# 9. EARLY WARNING SIGNAL TEST
# ============================================================
print("\n[9] Early warning signal test ...")
print("   Question: Does eigenvalue ratio or TE spike BEFORE crises?")

# For each crisis, check if the pre-crisis period shows anomalous values
# compared to the full-sample distribution
if len(eigen_df) > 0:
    eigen_mean = eigen_df["eigen_ratio"].mean()
    eigen_std = eigen_df["eigen_ratio"].std()
    te_mean_full = te_df["mean_TE"].mean() if len(te_df) > 0 else np.nan
    te_std_full = te_df["mean_TE"].std() if len(te_df) > 0 else np.nan

    print(f"\n   Full-sample baselines:")
    print(f"   Eigen ratio: {eigen_mean:.3f} ± {eigen_std:.3f}")
    print(f"   Mean TE:     {te_mean_full:.4f} ± {te_std_full:.4f}")

    for crisis_name, (ps, pe) in pre_crisis_windows.items():
        pre_eigen = eigen_df.loc[ps:pe, "eigen_ratio"]
        pre_te = te_df.loc[ps:pe, "mean_TE"]

        if len(pre_eigen) > 0:
            z_eigen = (pre_eigen.mean() - eigen_mean) / (eigen_std + 1e-10)
        else:
            z_eigen = np.nan

        if len(pre_te) > 0:
            z_te = (pre_te.mean() - te_mean_full) / (te_std_full + 1e-10)
        else:
            z_te = np.nan

        eigen_flag = "⚠ ANOMALOUS" if abs(z_eigen) > 1.5 else ""
        te_flag = "⚠ ANOMALOUS" if abs(z_te) > 1.5 else ""

        print(f"\n   Pre-{crisis_name}:")
        if not np.isnan(z_eigen):
            print(f"   Eigen ratio z-score: {z_eigen:+.2f} {eigen_flag}")
        if not np.isnan(z_te):
            print(f"   Mean TE z-score:     {z_te:+.2f} {te_flag}")

# ============================================================
# 10. VIX LEVEL vs EIGENVALUE RATIO
# ============================================================
print("\n[10] VIX level vs eigenvalue ratio relationship ...")

vix_at_eigen = vix_level.reindex(eigen_df.index)
valid_mask = ~(vix_at_eigen.isna() | eigen_df["eigen_ratio"].isna())

if valid_mask.sum() > 10:
    r_vix_eigen, p_vix_eigen = stats.pearsonr(
        vix_at_eigen[valid_mask].values,
        eigen_df.loc[valid_mask.values, "eigen_ratio"].values
    )
    rho_vix_eigen, rho_p = stats.spearmanr(
        vix_at_eigen[valid_mask].values,
        eigen_df.loc[valid_mask.values, "eigen_ratio"].values
    )
    print(f"   VIX level vs eigen ratio:")
    print(f"   Pearson  r = {r_vix_eigen:.3f}  (p={p_vix_eigen:.4f})")
    print(f"   Spearman ρ = {rho_vix_eigen:.3f}  (p={rho_p:.4f})")

    if abs(r_vix_eigen) > 0.3 and p_vix_eigen < 0.05:
        print(f"   → VIX and market coupling are significantly correlated")
        print(f"   → Interpretation: {'High VIX = high coupling (risk-on/off regime)' if r_vix_eigen > 0 else 'High VIX = low coupling (flight to quality)'}")
    else:
        print(f"   → Weak/non-significant relationship between VIX level and coupling")
else:
    r_vix_eigen, p_vix_eigen = np.nan, np.nan
    print("   Insufficient data for VIX-eigenvalue comparison")

# ============================================================
# 11. COMPREHENSIVE SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("COMPREHENSIVE SUMMARY — K134")
print("=" * 70)

print(f"""
Data: {len(prices)} observations, {assets}, 2006-2024
Method: Eigenvalue ratio (market coupling) + Binned TE (VIX information flow)
Windows: 252d rolling, 22d step

KEY FINDINGS:
""")

# Finding 1: Market coupling dynamics
print("1. MARKET COUPLING DYNAMICS (Eigenvalue Ratio)")
print(f"   Mean λ1/Σλ = {eigen_df['eigen_ratio'].mean():.3f} ± {eigen_df['eigen_ratio'].std():.3f}")
print(f"   Range: [{eigen_df['eigen_ratio'].min():.3f}, {eigen_df['eigen_ratio'].max():.3f}]")
print(f"   → {'Single factor dominates' if eigen_df['eigen_ratio'].mean() > 0.5 else 'Multi-factor structure'}")

# Finding 2: VIX information transfer
print(f"\n2. VIX INFORMATION TRANSFER (Transfer Entropy)")
for asset in assets:
    r = te_results[asset]
    sig = "SIG" if r["p"] < 0.05 else "NS"
    print(f"   TE(VIX→{asset:>4s}) = {r['te']:.4f} bits  [{sig}]")

# Finding 3: Co-evolution
print(f"\n3. COUPLING ↔ INFORMATION FLOW CO-EVOLUTION")
if not np.isnan(corr_contemp):
    print(f"   Contemporaneous: r={corr_contemp:.3f} (p={p_contemp:.4f})")
    if abs(corr_contemp) > 0.3 and p_contemp < 0.05:
        direction = "positive" if corr_contemp > 0 else "negative"
        print(f"   → Significant {direction} co-evolution")
        if corr_contemp > 0:
            print(f"   → When markets couple more, VIX carries more information")
        else:
            print(f"   → When markets couple more, VIX information DECREASES (paradox)")
    else:
        print(f"   → No significant co-evolution")

# Finding 4: Crisis dynamics
print(f"\n4. CRISIS DYNAMICS")
for row in crisis_table:
    if not np.isnan(row['eigen_change_pct']):
        e_dir = "↑" if row['eigen_change_pct'] > 0 else "↓"
        t_dir = "↑" if row['te_change_pct'] > 0 else "↓"
        concordant = (row['eigen_change_pct'] > 0) == (row['te_change_pct'] > 0)
        print(f"   {row['crisis']:20s}: eigen {e_dir}{abs(row['eigen_change_pct']):5.1f}%  "
              f"TE {t_dir}{abs(row['te_change_pct']):5.1f}%  "
              f"{'CONCORDANT' if concordant else 'DISCORDANT'}")

# Finding 5: VIX sufficiency implication
print(f"\n5. VIX SUFFICIENCY IMPLICATION")
if not np.isnan(r_vix_eigen):
    print(f"   VIX ↔ Market coupling: r={r_vix_eigen:.3f}")
    if abs(r_vix_eigen) > 0.3:
        print(f"   → VIX captures market coupling information")
        print(f"   → Supports VIX sufficient statistic hypothesis")
    else:
        print(f"   → VIX does NOT capture market coupling")
        print(f"   → Eigenvalue ratio contains INDEPENDENT information")

# Overall conclusion
print(f"\n{'='*70}")
print("CONCLUSION:")
n_sig_te = sum(1 for a in assets if te_results[a]["p"] < 0.05)
print(f"   VIX→Asset TE significant for {n_sig_te}/{len(assets)} assets")

if not np.isnan(corr_contemp) and abs(corr_contemp) > 0.3 and p_contemp < 0.05:
    print(f"   Eigenvalue ratio and TE co-evolve (r={corr_contemp:.3f})")
    print(f"   → Market topology and information flow are coupled")
else:
    print(f"   Eigenvalue ratio and TE show {'weak' if abs(corr_contemp) < 0.2 else 'moderate but NS'} relationship")
    print(f"   → Market topology and information flow may be INDEPENDENT channels")

concordant_count = sum(1 for row in crisis_table
                       if not np.isnan(row['eigen_change_pct'])
                       and (row['eigen_change_pct'] > 0) == (row['te_change_pct'] > 0))
total_crises = sum(1 for row in crisis_table if not np.isnan(row['eigen_change_pct']))
print(f"   Crisis concordance: {concordant_count}/{total_crises} crises show same direction")

print(f"\n   Time elapsed: {time.time()-t0:.1f}s")
print("=" * 70)
