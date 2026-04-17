"""
K138: Cross-Asset Roughness Fingerprint — Hurst Exponent Analysis
=================================================================
[提出: Gemini R3#3, 執行: Claude]

Background:
- T3 tested SPY H=0.105 (variogram) but method-dependent
- K132 showed SPY capture rate 63% vs GLD 19% vs BTC 15%
- If assets have different "roughness fingerprints", this may explain
  why a unified GARCH framework performs very differently across assets.

Methodology:
1. Compute Hurst exponent for |return| series using 3 methods:
   - Variogram (Gatheral et al. 2018)
   - DFA (Detrended Fluctuation Analysis)
   - R/S analysis (Rescaled Range)
2. Rolling H (252d window): temporal stability
3. Cross-asset comparison: H vs capture rate, H vs GJR gamma
4. Volume-conditioned H for BTC (link to K136)
5. Theory: H < 0.5 = rough (anti-persistent), H = 0.5 = random walk, H > 0.5 = persistent

Author: VolPred Research System (K138)
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime

# ==================================================================
# CONFIG
# ==================================================================
DATA_START = "2010-01-01"
DATA_END = "2024-12-31"
ROLLING_WINDOW = 252      # 1 year for rolling H
VARIOGRAM_LAGS = range(1, 61)  # lags 1 to 60 days
DFA_SCALES = None         # computed dynamically
RS_MIN_WINDOW = 20
RS_MAX_WINDOW = 500

ASSETS = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "GLD": "GLD",
    "TLT": "TLT",
    "EEM": "EEM",
    "BTC": "BTC-USD",
}

# K132 capture rates (from prior experiment)
CAPTURE_RATES = {
    "SPY": 0.63,
    "QQQ": 0.58,
    "GLD": 0.19,
    "TLT": 0.25,
    "EEM": 0.45,
    "BTC": 0.15,
}

# GJR gamma values (from prior experiments)
GJR_GAMMAS = {
    "SPY": 0.15,
    "QQQ": 0.14,
    "GLD": 0.03,
    "TLT": 0.05,
    "EEM": 0.12,
    "BTC": 0.08,
}

np.random.seed(42)

# ==================================================================
# DATA LOADING
# ==================================================================
def load_data():
    """Download daily data for all assets."""
    print("=" * 70)
    print("K138: Cross-Asset Roughness Fingerprint — Hurst Exponent Analysis")
    print("=" * 70)
    print(f"\nLoading data {DATA_START} to {DATA_END}...")

    all_data = {}
    for name, ticker in ASSETS.items():
        try:
            df = yf.download(ticker, start=DATA_START, end=DATA_END,
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.dropna(subset=["Close"])
            df["return"] = np.log(df["Close"] / df["Close"].shift(1))
            df["abs_return"] = np.abs(df["return"])
            df["sq_return"] = df["return"] ** 2
            df = df.dropna()
            all_data[name] = df
            print(f"  {name}: {len(df)} days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
        except Exception as e:
            print(f"  {name}: FAILED - {e}")

    return all_data


# ==================================================================
# HURST EXPONENT METHODS
# ==================================================================

def hurst_variogram(series, lags=None):
    """
    Variogram method (Gatheral et al. 2018).
    For rough volatility: use log(|return|) as vol proxy.
    H = slope of log-log plot of lag vs E[|Delta log sigma^2|^2] / 2
    """
    if lags is None:
        lags = range(1, min(61, len(series) // 4))

    x = np.array(series)
    if len(x) < max(lags) + 10:
        return np.nan

    log_lags = []
    log_variograms = []

    for lag in lags:
        diffs = x[lag:] - x[:-lag]
        variogram = np.mean(diffs ** 2)
        if variogram > 0:
            log_lags.append(np.log(lag))
            log_variograms.append(np.log(variogram))

    if len(log_lags) < 5:
        return np.nan

    slope, _, _, _, _ = stats.linregress(log_lags, log_variograms)
    H = slope / 2.0  # variogram exponent = 2H
    return H


def hurst_dfa(series, min_scale=10, max_scale=None):
    """
    Detrended Fluctuation Analysis (DFA).
    H = slope of log-log plot of scale vs fluctuation function F(n).
    """
    x = np.array(series)
    N = len(x)

    if max_scale is None:
        max_scale = N // 4

    # Cumulative sum of deviations from mean (profile)
    profile = np.cumsum(x - np.mean(x))

    # Generate scales (logarithmically spaced)
    scales = np.unique(np.logspace(
        np.log10(min_scale),
        np.log10(max_scale),
        num=30
    ).astype(int))
    scales = scales[scales >= min_scale]
    scales = scales[scales <= max_scale]

    if len(scales) < 5:
        return np.nan

    flucts = []
    valid_scales = []

    for scale in scales:
        n_segments = N // scale
        if n_segments < 2:
            continue

        # Split into non-overlapping segments
        rms_list = []
        for i in range(n_segments):
            segment = profile[i * scale: (i + 1) * scale]
            # Fit linear trend
            t = np.arange(len(segment))
            coeffs = np.polyfit(t, segment, 1)
            trend = np.polyval(coeffs, t)
            rms = np.sqrt(np.mean((segment - trend) ** 2))
            rms_list.append(rms)

        if len(rms_list) > 0:
            flucts.append(np.mean(rms_list))
            valid_scales.append(scale)

    if len(valid_scales) < 5:
        return np.nan

    log_scales = np.log(valid_scales)
    log_flucts = np.log(flucts)

    slope, _, _, _, _ = stats.linregress(log_scales, log_flucts)
    return slope  # DFA exponent alpha = H for fBm


def hurst_rs(series, min_window=20, max_window=None):
    """
    Rescaled Range (R/S) analysis.
    H = slope of log-log plot of window size vs R/S statistic.
    """
    x = np.array(series)
    N = len(x)

    if max_window is None:
        max_window = min(N // 2, 500)

    # Window sizes (logarithmically spaced)
    windows = np.unique(np.logspace(
        np.log10(min_window),
        np.log10(max_window),
        num=30
    ).astype(int))
    windows = windows[windows >= min_window]
    windows = windows[windows <= max_window]

    if len(windows) < 5:
        return np.nan

    rs_values = []
    valid_windows = []

    for w in windows:
        n_segments = N // w
        if n_segments < 2:
            continue

        rs_list = []
        for i in range(n_segments):
            segment = x[i * w: (i + 1) * w]
            mean_seg = np.mean(segment)
            std_seg = np.std(segment, ddof=1)
            if std_seg < 1e-12:
                continue
            cumdev = np.cumsum(segment - mean_seg)
            R = np.max(cumdev) - np.min(cumdev)
            rs_list.append(R / std_seg)

        if len(rs_list) > 0:
            rs_values.append(np.mean(rs_list))
            valid_windows.append(w)

    if len(valid_windows) < 5:
        return np.nan

    log_windows = np.log(valid_windows)
    log_rs = np.log(rs_values)

    slope, _, _, _, _ = stats.linregress(log_windows, log_rs)
    return slope


# ==================================================================
# ROLLING HURST
# ==================================================================

def compute_rolling_hurst(series, window=252, method="variogram"):
    """Compute rolling Hurst exponent."""
    H_values = []
    dates = []

    func = {
        "variogram": hurst_variogram,
        "dfa": hurst_dfa,
        "rs": hurst_rs,
    }[method]

    for i in range(window, len(series)):
        segment = series[i - window:i]
        H = func(segment)
        H_values.append(H)
        dates.append(series.index[i] if hasattr(series, 'index') else i)

    return pd.Series(H_values, index=dates)


# ==================================================================
# MAIN ANALYSIS
# ==================================================================

def main():
    all_data = load_data()

    if len(all_data) == 0:
        print("ERROR: No data loaded.")
        return

    # ==============================================================
    # PART 1: Full-sample Hurst exponents (3 methods x 6 assets)
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 1: Full-Sample Hurst Exponents")
    print("=" * 70)
    print("\nUsing log(|return|) as volatility proxy (Gatheral et al. 2018)")

    results = {}

    for name, df in all_data.items():
        # Volatility proxy: log of absolute return
        # Filter out zero returns to avoid -inf
        abs_ret = df["abs_return"].copy()
        abs_ret = abs_ret[abs_ret > 0]
        log_vol = np.log(abs_ret)

        H_var = hurst_variogram(log_vol)
        H_dfa = hurst_dfa(log_vol)
        H_rs = hurst_rs(log_vol)

        results[name] = {
            "H_variogram": H_var,
            "H_dfa": H_dfa,
            "H_rs": H_rs,
            "H_mean": np.nanmean([H_var, H_dfa, H_rs]),
            "n_obs": len(abs_ret),
        }

    # Print table
    print(f"\n{'Asset':<8} {'Variogram':>12} {'DFA':>12} {'R/S':>12} {'Mean H':>12} {'N obs':>8}")
    print("-" * 70)
    for name in ["SPY", "QQQ", "GLD", "TLT", "EEM", "BTC"]:
        if name in results:
            r = results[name]
            print(f"{name:<8} {r['H_variogram']:>12.4f} {r['H_dfa']:>12.4f} {r['H_rs']:>12.4f} {r['H_mean']:>12.4f} {r['n_obs']:>8d}")

    # Also compute H using raw |return| (not log)
    print("\n--- Also using |return| directly (not log) ---")
    results_raw = {}
    for name, df in all_data.items():
        abs_ret = df["abs_return"].values
        H_var = hurst_variogram(abs_ret)
        H_dfa = hurst_dfa(abs_ret)
        H_rs = hurst_rs(abs_ret)
        results_raw[name] = {
            "H_variogram": H_var,
            "H_dfa": H_dfa,
            "H_rs": H_rs,
            "H_mean": np.nanmean([H_var, H_dfa, H_rs]),
        }

    print(f"\n{'Asset':<8} {'Variogram':>12} {'DFA':>12} {'R/S':>12} {'Mean H':>12}")
    print("-" * 55)
    for name in ["SPY", "QQQ", "GLD", "TLT", "EEM", "BTC"]:
        if name in results_raw:
            r = results_raw[name]
            print(f"{name:<8} {r['H_variogram']:>12.4f} {r['H_dfa']:>12.4f} {r['H_rs']:>12.4f} {r['H_mean']:>12.4f}")

    # Also compute H using r^2 (squared returns)
    print("\n--- Also using r^2 (squared returns) ---")
    results_sq = {}
    for name, df in all_data.items():
        sq_ret = df["sq_return"].values
        H_var = hurst_variogram(sq_ret)
        H_dfa = hurst_dfa(sq_ret)
        H_rs = hurst_rs(sq_ret)
        results_sq[name] = {
            "H_variogram": H_var,
            "H_dfa": H_dfa,
            "H_rs": H_rs,
            "H_mean": np.nanmean([H_var, H_dfa, H_rs]),
        }

    print(f"\n{'Asset':<8} {'Variogram':>12} {'DFA':>12} {'R/S':>12} {'Mean H':>12}")
    print("-" * 55)
    for name in ["SPY", "QQQ", "GLD", "TLT", "EEM", "BTC"]:
        if name in results_sq:
            r = results_sq[name]
            print(f"{name:<8} {r['H_variogram']:>12.4f} {r['H_dfa']:>12.4f} {r['H_rs']:>12.4f} {r['H_mean']:>12.4f}")

    # ==============================================================
    # PART 2: Cross-asset comparison with capture rate and GJR gamma
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 2: Cross-Asset Comparison")
    print("=" * 70)

    # Use log-vol variogram H as primary measure (Gatheral standard)
    assets_ordered = ["SPY", "QQQ", "GLD", "TLT", "EEM", "BTC"]
    available = [a for a in assets_ordered if a in results]

    H_values = [results[a]["H_variogram"] for a in available]
    capture_values = [CAPTURE_RATES.get(a, np.nan) for a in available]
    gamma_values = [GJR_GAMMAS.get(a, np.nan) for a in available]

    print(f"\n{'Asset':<8} {'H_var':>8} {'Capture%':>10} {'GJR_gamma':>10}")
    print("-" * 40)
    for i, name in enumerate(available):
        print(f"{name:<8} {H_values[i]:>8.4f} {capture_values[i]:>10.0%} {gamma_values[i]:>10.3f}")

    # Correlation: H vs capture rate
    valid_cap = [(H_values[i], capture_values[i]) for i in range(len(available))
                 if not np.isnan(H_values[i]) and not np.isnan(capture_values[i])]
    if len(valid_cap) >= 4:
        h_arr = [v[0] for v in valid_cap]
        c_arr = [v[1] for v in valid_cap]
        rho_cap, p_cap = stats.spearmanr(h_arr, c_arr)
        print(f"\nSpearman corr(H_variogram, capture_rate): rho = {rho_cap:.3f}, p = {p_cap:.4f}")
        rho_p, p_p = stats.pearsonr(h_arr, c_arr)
        print(f"Pearson  corr(H_variogram, capture_rate): r   = {rho_p:.3f}, p = {p_p:.4f}")
    else:
        print("\nInsufficient data for H vs capture rate correlation.")

    # Correlation: H vs GJR gamma
    valid_gam = [(H_values[i], gamma_values[i]) for i in range(len(available))
                 if not np.isnan(H_values[i]) and not np.isnan(gamma_values[i])]
    if len(valid_gam) >= 4:
        h_arr = [v[0] for v in valid_gam]
        g_arr = [v[1] for v in valid_gam]
        rho_gam, p_gam = stats.spearmanr(h_arr, g_arr)
        print(f"\nSpearman corr(H_variogram, GJR_gamma):   rho = {rho_gam:.3f}, p = {p_gam:.4f}")
        rho_p, p_p = stats.pearsonr(h_arr, g_arr)
        print(f"Pearson  corr(H_variogram, GJR_gamma):   r   = {rho_p:.3f}, p = {p_p:.4f}")

    # Interpretation
    print("\n--- Interpretation ---")
    for name in available:
        H = results[name]["H_variogram"]
        if H < 0.3:
            cat = "ROUGH (strongly anti-persistent)"
        elif H < 0.5:
            cat = "Rough (mildly anti-persistent)"
        elif abs(H - 0.5) < 0.05:
            cat = "Random walk (~0.5)"
        elif H < 0.7:
            cat = "Persistent (mild)"
        else:
            cat = "PERSISTENT (strong)"
        print(f"  {name}: H = {H:.4f} → {cat}")

    # ==============================================================
    # PART 3: Rolling Hurst (252d window) — temporal stability
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 3: Rolling Hurst Exponent (252d window, variogram method)")
    print("=" * 70)

    rolling_results = {}
    for name in ["SPY", "GLD", "BTC"]:  # Focus on 3 representative assets
        if name not in all_data:
            continue
        df = all_data[name]
        abs_ret = df["abs_return"].copy()
        abs_ret = abs_ret[abs_ret > 0]
        log_vol = np.log(abs_ret)

        print(f"\n  Computing rolling H for {name} ({len(log_vol)} obs)...")
        rolling_H = compute_rolling_hurst(log_vol, window=ROLLING_WINDOW, method="variogram")
        rolling_results[name] = rolling_H

        if len(rolling_H) > 0:
            print(f"    Mean H:   {rolling_H.mean():.4f}")
            print(f"    Std H:    {rolling_H.std():.4f}")
            print(f"    Min H:    {rolling_H.min():.4f} ({rolling_H.idxmin().strftime('%Y-%m-%d') if hasattr(rolling_H.idxmin(), 'strftime') else rolling_H.idxmin()})")
            print(f"    Max H:    {rolling_H.max():.4f} ({rolling_H.idxmax().strftime('%Y-%m-%d') if hasattr(rolling_H.idxmax(), 'strftime') else rolling_H.idxmax()})")
            print(f"    Range:    {rolling_H.max() - rolling_H.min():.4f}")

            # Check if H is stable or time-varying
            # Split into halves
            mid = len(rolling_H) // 2
            first_half = rolling_H.iloc[:mid]
            second_half = rolling_H.iloc[mid:]
            t_stat, p_val = stats.ttest_ind(first_half.dropna(), second_half.dropna())
            print(f"    First half mean: {first_half.mean():.4f}, Second half mean: {second_half.mean():.4f}")
            print(f"    t-test (stability): t = {t_stat:.3f}, p = {p_val:.4f}")

    # ==============================================================
    # PART 4: Method agreement analysis
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 4: Method Agreement Analysis")
    print("=" * 70)

    print("\nDoes the ranking of assets by H agree across methods?")
    methods = ["H_variogram", "H_dfa", "H_rs"]
    rankings = {}
    for method in methods:
        vals = {name: results[name][method] for name in available if not np.isnan(results[name][method])}
        ranked = sorted(vals.keys(), key=lambda x: vals[x])
        rankings[method] = ranked
        print(f"  {method:>15}: {' < '.join(ranked)}")

    # Pairwise Spearman between methods
    print("\n  Pairwise Spearman rank correlation between methods:")
    for i in range(len(methods)):
        for j in range(i + 1, len(methods)):
            m1, m2 = methods[i], methods[j]
            v1 = [results[a][m1] for a in available if not np.isnan(results[a][m1]) and not np.isnan(results[a][m2])]
            v2 = [results[a][m2] for a in available if not np.isnan(results[a][m1]) and not np.isnan(results[a][m2])]
            if len(v1) >= 4:
                rho, p = stats.spearmanr(v1, v2)
                print(f"    {m1} vs {m2}: rho = {rho:.3f}, p = {p:.4f}")

    # ==============================================================
    # PART 5: Volume-Conditioned H for BTC
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 5: Volume-Conditioned H for BTC")
    print("=" * 70)

    if "BTC" in all_data:
        btc = all_data["BTC"]
        if "Volume" in btc.columns and btc["Volume"].sum() > 0:
            # Split by volume median
            vol_median = btc["Volume"].median()
            high_vol_mask = btc["Volume"] > vol_median
            low_vol_mask = btc["Volume"] <= vol_median

            # Get abs_return series for each regime
            abs_ret = btc["abs_return"].copy()
            abs_ret = abs_ret[abs_ret > 0]
            log_vol_btc = np.log(abs_ret)

            # High volume periods
            high_vol_dates = btc.index[high_vol_mask]
            low_vol_dates = btc.index[low_vol_mask]

            # Compute Hurst for each regime using DFA (more robust for subsamples)
            high_vol_series = log_vol_btc[log_vol_btc.index.isin(high_vol_dates)]
            low_vol_series = log_vol_btc[log_vol_btc.index.isin(low_vol_dates)]

            print(f"\n  BTC high-volume days: {len(high_vol_series)}")
            print(f"  BTC low-volume days:  {len(low_vol_series)}")

            for method_name, method_func in [("Variogram", hurst_variogram),
                                              ("DFA", hurst_dfa),
                                              ("R/S", hurst_rs)]:
                H_high = method_func(high_vol_series.values)
                H_low = method_func(low_vol_series.values)
                diff = H_high - H_low if not np.isnan(H_high) and not np.isnan(H_low) else np.nan
                print(f"\n  {method_name}:")
                print(f"    H (high volume): {H_high:.4f}" if not np.isnan(H_high) else f"    H (high volume): NaN")
                print(f"    H (low volume):  {H_low:.4f}" if not np.isnan(H_low) else f"    H (low volume):  NaN")
                if not np.isnan(diff):
                    print(f"    Difference:      {diff:+.4f}")

            # Volume terciles
            print("\n  Volume tercile analysis:")
            tercile_33 = btc["Volume"].quantile(0.333)
            tercile_67 = btc["Volume"].quantile(0.667)
            tercile_masks = [
                ("Low (0-33%)", btc["Volume"] <= tercile_33),
                ("Mid (33-67%)", (btc["Volume"] > tercile_33) & (btc["Volume"] <= tercile_67)),
                ("High (67-100%)", btc["Volume"] > tercile_67),
            ]
            for label, mask in tercile_masks:
                subset_dates = btc.index[mask]
                subset = log_vol_btc[log_vol_btc.index.isin(subset_dates)]
                H_var = hurst_variogram(subset.values) if len(subset) > 100 else np.nan
                H_dfa = hurst_dfa(subset.values) if len(subset) > 100 else np.nan
                if not np.isnan(H_var):
                    print(f"    {label:>15}: H_var = {H_var:.4f}, H_dfa = {H_dfa:.4f}, N = {len(subset)}")
                else:
                    print(f"    {label:>15}: insufficient data (N = {len(subset)})")
        else:
            print("  No volume data for BTC, skipping volume-conditioned analysis.")
    else:
        print("  BTC data not loaded, skipping.")

    # ==============================================================
    # PART 6: Roughness vs Return Proxy Choice
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 6: Sensitivity to Volatility Proxy Choice")
    print("=" * 70)

    print(f"\n{'Asset':<8} {'log|r|':>10} {'|r|':>10} {'r^2':>10} {'Spread':>10}")
    print("-" * 55)
    for name in available:
        H_log = results[name]["H_variogram"]
        H_raw = results_raw[name]["H_variogram"]
        H_sq = results_sq[name]["H_variogram"]
        spread = max(H_log, H_raw, H_sq) - min(H_log, H_raw, H_sq)
        print(f"{name:<8} {H_log:>10.4f} {H_raw:>10.4f} {H_sq:>10.4f} {spread:>10.4f}")

    # ==============================================================
    # PART 7: Equity-Only Subgroup Analysis
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 7: Equity vs Non-Equity Roughness")
    print("=" * 70)

    equity = ["SPY", "QQQ", "EEM"]
    non_equity = ["GLD", "TLT", "BTC"]

    eq_H = [results[a]["H_variogram"] for a in equity if a in results]
    ne_H = [results[a]["H_variogram"] for a in non_equity if a in results]

    if len(eq_H) >= 2 and len(ne_H) >= 2:
        eq_detail = ', '.join([a + '=' + f'{results[a]["H_variogram"]:.4f}' for a in equity if a in results])
        ne_detail = ', '.join([a + '=' + f'{results[a]["H_variogram"]:.4f}' for a in non_equity if a in results])
        print(f"\n  Equity H (mean):     {np.mean(eq_H):.4f} ({eq_detail})")
        print(f"  Non-equity H (mean): {np.mean(ne_H):.4f} ({ne_detail})")
        t_stat, p_val = stats.ttest_ind(eq_H, ne_H)
        print(f"  t-test: t = {t_stat:.3f}, p = {p_val:.4f}")

        # Mann-Whitney U (non-parametric, better for small N)
        u_stat, u_pval = stats.mannwhitneyu(eq_H, ne_H, alternative='two-sided')
        print(f"  Mann-Whitney U: U = {u_stat:.1f}, p = {u_pval:.4f}")

    # ==============================================================
    # PART 8: Bootstrap Confidence Intervals for H
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 8: Bootstrap 95% CI for Hurst Exponents (variogram, 1000 reps)")
    print("=" * 70)

    N_BOOT = 1000
    for name in ["SPY", "GLD", "BTC"]:
        if name not in all_data:
            continue
        df = all_data[name]
        abs_ret = df["abs_return"].copy()
        abs_ret = abs_ret[abs_ret > 0]
        log_vol = np.log(abs_ret).values

        boot_H = []
        for b in range(N_BOOT):
            # Block bootstrap (blocks of 50 to preserve autocorrelation)
            block_size = 50
            n_blocks = len(log_vol) // block_size + 1
            indices = np.random.randint(0, len(log_vol) - block_size, size=n_blocks)
            boot_sample = np.concatenate([log_vol[i:i + block_size] for i in indices])[:len(log_vol)]
            H = hurst_variogram(boot_sample)
            if not np.isnan(H):
                boot_H.append(H)

        if len(boot_H) > 10:
            boot_H = np.array(boot_H)
            ci_lo = np.percentile(boot_H, 2.5)
            ci_hi = np.percentile(boot_H, 97.5)
            print(f"\n  {name}: H = {results[name]['H_variogram']:.4f}  95% CI = [{ci_lo:.4f}, {ci_hi:.4f}]  (std = {boot_H.std():.4f})")

            # Test H < 0.5 (rough)
            pct_below_05 = np.mean(boot_H < 0.5) * 100
            print(f"         P(H < 0.5) = {pct_below_05:.1f}%")

    # ==============================================================
    # PART 9: Sub-period Stability
    # ==============================================================
    print("\n" + "=" * 70)
    print("PART 9: Sub-period H (5-year blocks)")
    print("=" * 70)

    periods = [
        ("2010-2014", "2010-01-01", "2014-12-31"),
        ("2015-2019", "2015-01-01", "2019-12-31"),
        ("2020-2024", "2020-01-01", "2024-12-31"),
    ]

    for name in ["SPY", "GLD", "BTC"]:
        if name not in all_data:
            continue
        print(f"\n  {name}:")
        df = all_data[name]
        for period_name, start, end in periods:
            sub = df.loc[start:end]
            abs_ret = sub["abs_return"].copy()
            abs_ret = abs_ret[abs_ret > 0]
            if len(abs_ret) < 200:
                print(f"    {period_name}: insufficient data ({len(abs_ret)} obs)")
                continue
            log_vol = np.log(abs_ret)
            H = hurst_variogram(log_vol)
            H_dfa_val = hurst_dfa(log_vol)
            print(f"    {period_name}: H_var = {H:.4f}, H_dfa = {H_dfa_val:.4f}  (N = {len(abs_ret)})")

    # ==============================================================
    # SUMMARY
    # ==============================================================
    print("\n" + "=" * 70)
    print("SUMMARY: K138 Cross-Asset Roughness Fingerprint")
    print("=" * 70)

    print("\n1. Full-sample Hurst exponents (variogram, log|r| proxy):")
    for name in available:
        H = results[name]["H_variogram"]
        print(f"   {name}: H = {H:.4f}", end="")
        if H < 0.3:
            print(" *** ROUGH ***")
        elif H < 0.5:
            print(" * rough *")
        elif abs(H - 0.5) < 0.05:
            print(" (random walk)")
        else:
            print(" (persistent)")

    print("\n2. Cross-asset correlations (variogram H):")
    valid_cap = [(results[a]["H_variogram"], CAPTURE_RATES[a]) for a in available
                 if not np.isnan(results[a]["H_variogram"]) and a in CAPTURE_RATES]
    if len(valid_cap) >= 4:
        h_arr = [v[0] for v in valid_cap]
        c_arr = [v[1] for v in valid_cap]
        rho, p = stats.spearmanr(h_arr, c_arr)
        print(f"   H vs Capture Rate: Spearman rho = {rho:.3f} (p = {p:.4f})")

    valid_gam = [(results[a]["H_variogram"], GJR_GAMMAS[a]) for a in available
                 if not np.isnan(results[a]["H_variogram"]) and a in GJR_GAMMAS]
    if len(valid_gam) >= 4:
        h_arr = [v[0] for v in valid_gam]
        g_arr = [v[1] for v in valid_gam]
        rho, p = stats.spearmanr(h_arr, g_arr)
        print(f"   H vs GJR Gamma:    Spearman rho = {rho:.3f} (p = {p:.4f})")

    print("\n3. Key findings:")
    # Determine if equity is rougher
    if len(eq_H) >= 2 and len(ne_H) >= 2:
        if np.mean(eq_H) < np.mean(ne_H):
            print(f"   - Equity is ROUGHER than non-equity (mean H: {np.mean(eq_H):.4f} vs {np.mean(ne_H):.4f})")
        else:
            print(f"   - Non-equity is ROUGHER than equity (mean H: {np.mean(ne_H):.4f} vs {np.mean(eq_H):.4f})")

    # Check method agreement
    print("   - Method agreement: see Part 4 above")

    # Rolling stability
    for name in ["SPY", "GLD", "BTC"]:
        if name in rolling_results and len(rolling_results[name]) > 0:
            std_H = rolling_results[name].std()
            print(f"   - {name} rolling H stability: std = {std_H:.4f}")

    print("\n4. Theoretical implications:")
    print("   - H < 0.5 → rough volatility (Gatheral et al. 2018)")
    print("   - Rougher assets may benefit more from models that capture anti-persistence")
    print("   - GARCH assumes H=0.5 (Markov); deviation suggests GARCH misspecification")
    print("   - Rough volatility → fractional models (rBergomi, rough Heston) may be superior")
    print("   - But: H measurement is method-dependent and sample-sensitive")

    print("\n" + "=" * 70)
    print("K138 COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
