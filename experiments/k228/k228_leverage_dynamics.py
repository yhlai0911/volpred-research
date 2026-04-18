"""
K228: Time-Varying Leverage Effect — Is Gamma Increasing Over Time?

Background:
  K197 found gamma is trending UP for SPY/QQQ/BTC.
  K143 established CV(gamma) as mechanism classifier.
  This experiment does a formal analysis of leverage effect dynamics.

Methodology:
  1. Rolling GJR-GARCH(1,1,1) w=2000, step=22 → track gamma over time
  2. Rolling CV(gamma) in 5-year windows
  3. Mann-Kendall trend test on gamma series
  4. Bai-Perron structural break detection (via statsmodels)
  5. Gamma drivers: correlation with market level, VIX, volume
  6. Cross-asset gamma synchronization
  7. Implications for VT: does higher gamma → better VT?

Data: SPY, QQQ, GLD, TLT, BTC-USD daily from yfinance (full history).
"""
import json
import warnings
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "BTC-USD"]
WINDOW = 2000          # rolling GJR-GARCH window
STEP = 22              # monthly steps
CV_WINDOW_YEARS = 5    # 5-year rolling CV window
CV_WINDOW = CV_WINDOW_YEARS * 12  # in monthly steps (~60 gamma estimates)

RESULTS_FILE = Path(__file__).parent / "k228_leverage_dynamics_results.json"


# ─────────────────────────────────────────────
# Mann-Kendall trend test (manual implementation)
# ─────────────────────────────────────────────
def mann_kendall_test(x):
    """
    Mann-Kendall trend test for monotonic trend.
    Returns: (tau, p_value, trend_direction)
    """
    x = np.asarray(x)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 8:
        return np.nan, np.nan, "insufficient_data"

    # Calculate S statistic
    s = 0
    for i in range(n - 1):
        for j in range(i + 1, n):
            diff = x[j] - x[i]
            if diff > 0:
                s += 1
            elif diff < 0:
                s -= 1

    # Calculate variance of S
    # Account for ties
    unique, counts = np.unique(x, return_counts=True)
    tie_sum = 0
    for t in counts:
        if t > 1:
            tie_sum += t * (t - 1) * (2 * t + 5)

    var_s = (n * (n - 1) * (2 * n + 5) - tie_sum) / 18.0

    if var_s == 0:
        return 0.0, 1.0, "no_trend"

    # Calculate Z statistic
    if s > 0:
        z = (s - 1) / np.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / np.sqrt(var_s)
    else:
        z = 0.0

    p_value = 2.0 * stats.norm.sf(abs(z))

    # Kendall's tau
    tau = s / (n * (n - 1) / 2.0)

    if p_value < 0.05:
        trend = "increasing" if z > 0 else "decreasing"
    else:
        trend = "no_trend"

    return float(tau), float(p_value), trend


# ─────────────────────────────────────────────
# Sen's slope estimator
# ─────────────────────────────────────────────
def sens_slope(x):
    """Theil-Sen slope estimator."""
    x = np.asarray(x)
    x = x[~np.isnan(x)]
    n = len(x)
    if n < 3:
        return np.nan
    slopes = []
    for i in range(n):
        for j in range(i + 1, n):
            if j != i:
                slopes.append((x[j] - x[i]) / (j - i))
    return float(np.median(slopes))


# ─────────────────────────────────────────────
# Structural break detection (CUSUM-based)
# ─────────────────────────────────────────────
def detect_structural_breaks(series, max_breaks=3, min_segment=24):
    """
    Detect structural breaks using recursive binary segmentation
    with CUSUM test. Returns list of breakpoint indices.
    """
    series = np.asarray(series, dtype=float)
    series = series[~np.isnan(series)]
    n = len(series)
    if n < 2 * min_segment:
        return []

    def cusum_test(y):
        """CUSUM test statistic for a single break."""
        n_y = len(y)
        if n_y < 2 * min_segment:
            return None, np.inf
        mean_y = np.mean(y)
        cumsum = np.cumsum(y - mean_y)
        # Normalize
        std_y = np.std(y, ddof=1)
        if std_y < 1e-12:
            return None, np.inf
        cumsum_norm = cumsum / (std_y * np.sqrt(n_y))
        # Find max absolute CUSUM
        best_idx = np.argmax(np.abs(cumsum_norm[min_segment:-min_segment])) + min_segment
        stat = abs(cumsum_norm[best_idx])
        return best_idx, stat

    # Critical values for CUSUM (approximate, Brownian bridge)
    # At 5% level, critical value ~ 1.36 for normalized CUSUM
    critical = 1.36

    breaks = []
    segments = [(0, n)]

    for _ in range(max_breaks):
        best_break = None
        best_stat = critical
        best_seg_idx = None

        for seg_idx, (start, end) in enumerate(segments):
            seg = series[start:end]
            if len(seg) < 2 * min_segment:
                continue
            idx, stat = cusum_test(seg)
            if idx is not None and stat > best_stat:
                best_break = start + idx
                best_stat = stat
                best_seg_idx = seg_idx

        if best_break is not None:
            breaks.append(best_break)
            start, end = segments[best_seg_idx]
            segments.pop(best_seg_idx)
            segments.insert(best_seg_idx, (start, best_break))
            segments.insert(best_seg_idx + 1, (best_break, end))
        else:
            break

    return sorted(breaks)


# ─────────────────────────────────────────────
# Chow test for structural break significance
# ─────────────────────────────────────────────
def chow_test(y, breakpoint):
    """F-test for structural break at given index."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    k = 2  # intercept + trend

    y1 = y[:breakpoint]
    y2 = y[breakpoint:]

    if len(y1) < k + 2 or len(y2) < k + 2:
        return np.nan, np.nan

    # Full model RSS
    x_full = np.column_stack([np.ones(n), np.arange(n)])
    beta_full = np.linalg.lstsq(x_full, y, rcond=None)[0]
    rss_full = np.sum((y - x_full @ beta_full) ** 2)

    # Split model RSS
    x1 = np.column_stack([np.ones(len(y1)), np.arange(len(y1))])
    beta1 = np.linalg.lstsq(x1, y1, rcond=None)[0]
    rss1 = np.sum((y1 - x1 @ beta1) ** 2)

    x2 = np.column_stack([np.ones(len(y2)), np.arange(len(y2))])
    beta2 = np.linalg.lstsq(x2, y2, rcond=None)[0]
    rss2 = np.sum((y2 - x2 @ beta2) ** 2)

    rss_split = rss1 + rss2

    f_stat = ((rss_full - rss_split) / k) / (rss_split / (n - 2 * k))
    p_value = 1.0 - stats.f.cdf(f_stat, k, n - 2 * k)

    return float(f_stat), float(p_value)


# ─────────────────────────────────────────────
# Data download
# ─────────────────────────────────────────────
def download_data():
    """Download full history for all assets."""
    print("=" * 70)
    print("K228: Time-Varying Leverage Effect — Is Gamma Increasing Over Time?")
    print("=" * 70)
    print(f"\nDownloading data for: {ASSETS}")

    data = {}
    for asset in ASSETS:
        ticker = yf.Ticker(asset)
        df = ticker.history(period="max", auto_adjust=True)
        if len(df) > 0:
            df.index = df.index.tz_localize(None)
            df["returns"] = np.log(df["Close"] / df["Close"].shift(1))
            df = df.dropna(subset=["returns"])
            data[asset] = df
            print(f"  {asset}: {len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {asset}: NO DATA")

    # Download VIX for driver analysis
    vix = yf.Ticker("^VIX")
    vix_df = vix.history(period="max", auto_adjust=True)
    if len(vix_df) > 0:
        vix_df.index = vix_df.index.tz_localize(None)
        data["VIX"] = vix_df
        print(f"  VIX: {len(vix_df)} obs")

    return data


# ─────────────────────────────────────────────
# Rolling GJR-GARCH estimation
# ─────────────────────────────────────────────
def rolling_gjr_garch(returns, window=WINDOW, step=STEP):
    """
    Rolling GJR-GARCH(1,1,1) estimation.
    Returns DataFrame with columns: date, gamma, alpha, beta, omega, converged
    """
    from arch import arch_model

    n = len(returns)
    results = []

    for start in range(0, n - window, step):
        end = start + window
        r = returns[start:end] * 100  # arch expects percentage

        try:
            model = arch_model(r, vol="GARCH", p=1, o=1, q=1,
                               dist="normal", mean="Zero", rescale=False)
            res = model.fit(disp="off", show_warning=False)

            if res.convergence_flag == 0:
                params = dict(res.params)
                # gamma is the asymmetric term (gamma[1] in arch notation)
                gamma = params.get("gamma[1]", np.nan)
                alpha = params.get("alpha[1]", np.nan)
                beta = params.get("beta[1]", np.nan)
                omega = params.get("omega", np.nan)

                results.append({
                    "date": returns.index[end - 1],
                    "window_start": returns.index[start],
                    "gamma": gamma,
                    "alpha": alpha,
                    "beta": beta,
                    "omega": omega,
                    "persistence": alpha + beta + 0.5 * gamma,
                    "converged": True,
                    "loglik": res.loglikelihood,
                })
        except Exception:
            pass

    return pd.DataFrame(results)


# ─────────────────────────────────────────────
# Part 1: Rolling gamma estimation & trend
# ─────────────────────────────────────────────
def analyze_gamma_trends(data):
    """Estimate rolling gamma and test for trends."""
    print("\n" + "=" * 70)
    print("PART 1: Rolling Gamma Estimation & Trend Analysis")
    print("=" * 70)

    gamma_series = {}
    trend_results = {}

    for asset in ASSETS:
        if asset not in data or asset == "VIX":
            continue

        df = data[asset]
        if len(df) < WINDOW + STEP:
            print(f"\n{asset}: Insufficient data ({len(df)} < {WINDOW + STEP})")
            continue

        print(f"\n{'─' * 50}")
        print(f"  {asset}: Rolling GJR-GARCH(1,1,1), w={WINDOW}, step={STEP}")
        print(f"{'─' * 50}")

        t0 = time.time()
        roll = rolling_gjr_garch(df["returns"], window=WINDOW, step=STEP)
        elapsed = time.time() - t0

        n_converged = roll["converged"].sum()
        n_total = len(roll)
        print(f"  Estimated {n_total} windows, {n_converged} converged ({elapsed:.1f}s)")

        if n_converged < 10:
            print(f"  Too few converged estimates, skipping")
            continue

        # Filter converged
        roll = roll[roll["converged"]].reset_index(drop=True)
        gamma_series[asset] = roll

        # Summary statistics
        gamma_vals = roll["gamma"].values
        print(f"  Gamma: mean={np.mean(gamma_vals):.4f}, std={np.std(gamma_vals):.4f}, "
              f"CV={np.std(gamma_vals)/np.mean(gamma_vals):.3f}" if np.mean(gamma_vals) > 0
              else f"  Gamma: mean={np.mean(gamma_vals):.4f}, std={np.std(gamma_vals):.4f}")
        print(f"  Range: [{np.min(gamma_vals):.4f}, {np.max(gamma_vals):.4f}]")
        print(f"  First 5y mean: {np.mean(gamma_vals[:min(60, len(gamma_vals))]):.4f}")
        print(f"  Last 5y mean: {np.mean(gamma_vals[-min(60, len(gamma_vals))::]):.4f}")

        # Mann-Kendall test
        tau, mk_p, direction = mann_kendall_test(gamma_vals)
        slope = sens_slope(gamma_vals)
        print(f"\n  Mann-Kendall Test:")
        print(f"    tau = {tau:.4f}, p = {mk_p:.4f}")
        print(f"    Sen's slope = {slope:.6f} per step")
        print(f"    Trend: {direction}")

        # OLS trend for comparison
        x = np.arange(len(gamma_vals))
        ols_slope, ols_intercept, ols_r, ols_p, ols_se = stats.linregress(x, gamma_vals)
        print(f"\n  OLS Trend:")
        print(f"    slope = {ols_slope:.6f}/step, p = {ols_p:.4f}")
        print(f"    R² = {ols_r**2:.4f}")
        print(f"    Annual change = {ols_slope * 12:.4f}")  # 12 steps/year

        trend_results[asset] = {
            "n_estimates": int(n_total),
            "n_converged": int(n_converged),
            "gamma_mean": float(np.mean(gamma_vals)),
            "gamma_std": float(np.std(gamma_vals)),
            "gamma_cv": float(np.std(gamma_vals) / abs(np.mean(gamma_vals))) if np.mean(gamma_vals) != 0 else np.nan,
            "gamma_min": float(np.min(gamma_vals)),
            "gamma_max": float(np.max(gamma_vals)),
            "first_5y_mean": float(np.mean(gamma_vals[:min(60, len(gamma_vals))])),
            "last_5y_mean": float(np.mean(gamma_vals[-min(60, len(gamma_vals)):])),
            "mann_kendall_tau": tau,
            "mann_kendall_p": mk_p,
            "mann_kendall_trend": direction,
            "sens_slope": slope,
            "ols_slope": float(ols_slope),
            "ols_p": float(ols_p),
            "ols_r2": float(ols_r**2),
            "annual_change": float(ols_slope * 12),
            "date_range": f"{roll['date'].iloc[0].strftime('%Y-%m-%d')} to {roll['date'].iloc[-1].strftime('%Y-%m-%d')}",
        }

    return gamma_series, trend_results


# ─────────────────────────────────────────────
# Part 2: Rolling CV(gamma) in 5-year windows
# ─────────────────────────────────────────────
def analyze_rolling_cv(gamma_series):
    """Compute rolling CV(gamma) to see stability evolution."""
    print("\n" + "=" * 70)
    print("PART 2: Rolling CV(gamma) in 5-Year Windows")
    print("=" * 70)

    cv_results = {}

    for asset, roll in gamma_series.items():
        gamma_vals = roll["gamma"].values
        dates = roll["date"].values
        n = len(gamma_vals)

        if n < CV_WINDOW:
            print(f"\n  {asset}: Only {n} estimates, need {CV_WINDOW} for 5y rolling CV")
            # Use full sample
            cv = np.std(gamma_vals) / abs(np.mean(gamma_vals)) if np.mean(gamma_vals) != 0 else np.nan
            cv_results[asset] = {
                "full_sample_cv": float(cv),
                "rolling_cv_available": False,
            }
            continue

        # Rolling CV
        rolling_cvs = []
        rolling_dates = []
        rolling_means = []
        for i in range(CV_WINDOW, n + 1):
            window = gamma_vals[i - CV_WINDOW:i]
            m = np.mean(window)
            s = np.std(window)
            cv = s / abs(m) if abs(m) > 1e-8 else np.nan
            rolling_cvs.append(cv)
            rolling_dates.append(dates[i - 1])
            rolling_means.append(m)

        rolling_cvs = np.array(rolling_cvs)
        rolling_means = np.array(rolling_means)
        valid = ~np.isnan(rolling_cvs)

        print(f"\n  {asset}:")
        print(f"    Full-sample CV(gamma): {np.std(gamma_vals)/abs(np.mean(gamma_vals)):.3f}" if np.mean(gamma_vals) != 0 else "    Full-sample CV(gamma): N/A")
        print(f"    Rolling CV range: [{np.nanmin(rolling_cvs):.3f}, {np.nanmax(rolling_cvs):.3f}]")
        print(f"    Rolling CV mean: {np.nanmean(rolling_cvs):.3f}")

        # Trend in CV
        if np.sum(valid) >= 10:
            tau_cv, p_cv, dir_cv = mann_kendall_test(rolling_cvs[valid])
            print(f"    CV trend: tau={tau_cv:.3f}, p={p_cv:.4f} ({dir_cv})")
        else:
            tau_cv, p_cv, dir_cv = np.nan, np.nan, "insufficient"

        # Trend in rolling mean gamma
        if np.sum(~np.isnan(rolling_means)) >= 10:
            tau_m, p_m, dir_m = mann_kendall_test(rolling_means[~np.isnan(rolling_means)])
            print(f"    Mean gamma trend: tau={tau_m:.3f}, p={p_m:.4f} ({dir_m})")
        else:
            tau_m, p_m, dir_m = np.nan, np.nan, "insufficient"

        cv_results[asset] = {
            "full_sample_cv": float(np.std(gamma_vals) / abs(np.mean(gamma_vals))) if np.mean(gamma_vals) != 0 else None,
            "rolling_cv_available": True,
            "rolling_cv_min": float(np.nanmin(rolling_cvs)),
            "rolling_cv_max": float(np.nanmax(rolling_cvs)),
            "rolling_cv_mean": float(np.nanmean(rolling_cvs)),
            "cv_trend_tau": float(tau_cv) if not np.isnan(tau_cv) else None,
            "cv_trend_p": float(p_cv) if not np.isnan(p_cv) else None,
            "cv_trend_direction": dir_cv,
            "mean_gamma_trend_tau": float(tau_m) if not np.isnan(tau_m) else None,
            "mean_gamma_trend_p": float(p_m) if not np.isnan(p_m) else None,
            "mean_gamma_trend_direction": dir_m,
        }

    return cv_results


# ─────────────────────────────────────────────
# Part 3: Structural break detection
# ─────────────────────────────────────────────
def analyze_structural_breaks(gamma_series):
    """Detect structural breaks in gamma series."""
    print("\n" + "=" * 70)
    print("PART 3: Structural Break Detection (CUSUM + Chow Test)")
    print("=" * 70)

    break_results = {}

    for asset, roll in gamma_series.items():
        gamma_vals = roll["gamma"].values
        dates = roll["date"].values

        print(f"\n  {asset}:")

        # CUSUM-based detection
        breaks = detect_structural_breaks(gamma_vals, max_breaks=3, min_segment=24)

        if not breaks:
            print(f"    No structural breaks detected")
            break_results[asset] = {
                "n_breaks": 0,
                "breaks": [],
            }
            continue

        print(f"    Detected {len(breaks)} break(s):")
        break_details = []
        for bp in breaks:
            bp_date = pd.Timestamp(dates[bp]).strftime("%Y-%m-%d")
            gamma_before = np.mean(gamma_vals[:bp])
            gamma_after = np.mean(gamma_vals[bp:])
            change_pct = (gamma_after - gamma_before) / abs(gamma_before) * 100 if gamma_before != 0 else np.nan

            # Chow test
            f_stat, chow_p = chow_test(gamma_vals, bp)

            print(f"    Break at index {bp} ({bp_date}):")
            print(f"      gamma before: {gamma_before:.4f}")
            print(f"      gamma after:  {gamma_after:.4f}")
            print(f"      change: {change_pct:+.1f}%")
            print(f"      Chow F={f_stat:.2f}, p={chow_p:.4f}" +
                  (" ***" if chow_p < 0.01 else " **" if chow_p < 0.05 else " *" if chow_p < 0.10 else ""))

            break_details.append({
                "index": int(bp),
                "date": bp_date,
                "gamma_before": float(gamma_before),
                "gamma_after": float(gamma_after),
                "change_pct": float(change_pct) if not np.isnan(change_pct) else None,
                "chow_f": float(f_stat) if not np.isnan(f_stat) else None,
                "chow_p": float(chow_p) if not np.isnan(chow_p) else None,
            })

        break_results[asset] = {
            "n_breaks": len(breaks),
            "breaks": break_details,
        }

    return break_results


# ─────────────────────────────────────────────
# Part 4: What drives gamma changes?
# ─────────────────────────────────────────────
def analyze_gamma_drivers(gamma_series, data):
    """Correlate gamma with market level, VIX, volume."""
    print("\n" + "=" * 70)
    print("PART 4: Gamma Drivers (Market Level, VIX, Volume)")
    print("=" * 70)

    driver_results = {}

    for asset, roll in gamma_series.items():
        if asset == "VIX" or asset not in data:
            continue

        print(f"\n  {asset}:")
        df = data[asset]

        # For each gamma estimate, get the corresponding market conditions
        market_levels = []
        vix_levels = []
        volumes = []
        realized_vols = []

        for _, row in roll.iterrows():
            date = row["date"]
            # Get market level (trailing 252d cumulative return)
            mask = df.index <= date
            if mask.sum() < 252:
                market_levels.append(np.nan)
            else:
                trailing = df.loc[mask].tail(252)
                cum_ret = (1 + trailing["returns"]).prod() - 1
                market_levels.append(cum_ret)

            # Get VIX level (average of last 22 days)
            if "VIX" in data:
                vix_df = data["VIX"]
                vix_mask = vix_df.index <= date
                if vix_mask.sum() >= 22:
                    vix_level = vix_df.loc[vix_mask].tail(22)["Close"].mean()
                    vix_levels.append(vix_level)
                else:
                    vix_levels.append(np.nan)

            # Get average volume (trailing 22d)
            if "Volume" in df.columns:
                vol_mask = df.index <= date
                if vol_mask.sum() >= 22:
                    avg_vol = df.loc[vol_mask].tail(22)["Volume"].mean()
                    volumes.append(np.log(avg_vol) if avg_vol > 0 else np.nan)
                else:
                    volumes.append(np.nan)

            # Realized vol (trailing 22d)
            if mask.sum() >= 22:
                rv = df.loc[mask].tail(22)["returns"].std() * np.sqrt(252)
                realized_vols.append(rv)
            else:
                realized_vols.append(np.nan)

        gamma = roll["gamma"].values

        # Correlations
        drivers = {}

        # Market level vs gamma
        ml = np.array(market_levels)
        valid = ~np.isnan(ml) & ~np.isnan(gamma)
        if valid.sum() >= 10:
            r, p = stats.spearmanr(gamma[valid], ml[valid])
            print(f"    gamma vs market_level: rho={r:.3f}, p={p:.4f}")
            drivers["market_level"] = {"spearman_rho": float(r), "p": float(p)}

        # VIX vs gamma
        if vix_levels:
            vl = np.array(vix_levels)
            valid = ~np.isnan(vl) & ~np.isnan(gamma[:len(vl)])
            if valid.sum() >= 10:
                r, p = stats.spearmanr(gamma[:len(vl)][valid], vl[valid])
                print(f"    gamma vs VIX_level:    rho={r:.3f}, p={p:.4f}")
                drivers["vix_level"] = {"spearman_rho": float(r), "p": float(p)}

        # Volume vs gamma
        if volumes:
            vol_arr = np.array(volumes)
            valid = ~np.isnan(vol_arr) & ~np.isnan(gamma[:len(vol_arr)])
            if valid.sum() >= 10:
                r, p = stats.spearmanr(gamma[:len(vol_arr)][valid], vol_arr[valid])
                print(f"    gamma vs log_volume:   rho={r:.3f}, p={p:.4f}")
                drivers["log_volume"] = {"spearman_rho": float(r), "p": float(p)}

        # Realized vol vs gamma
        rv = np.array(realized_vols)
        valid = ~np.isnan(rv) & ~np.isnan(gamma[:len(rv)])
        if valid.sum() >= 10:
            r, p = stats.spearmanr(gamma[:len(rv)][valid], rv[valid])
            print(f"    gamma vs realized_vol: rho={r:.3f}, p={p:.4f}")
            drivers["realized_vol"] = {"spearman_rho": float(r), "p": float(p)}

        # Bull vs bear market gamma
        if len(ml) >= 20:
            valid_ml = ~np.isnan(ml)
            if valid_ml.sum() >= 20:
                median_ml = np.median(ml[valid_ml])
                bull = gamma[valid_ml & (ml > median_ml)]
                bear = gamma[valid_ml & (ml <= median_ml)]
                if len(bull) >= 5 and len(bear) >= 5:
                    t_stat, t_p = stats.mannwhitneyu(bull, bear, alternative="two-sided")
                    print(f"    Bull gamma: {np.mean(bull):.4f} vs Bear gamma: {np.mean(bear):.4f}")
                    print(f"    Mann-Whitney U p={t_p:.4f}")
                    drivers["bull_vs_bear"] = {
                        "bull_gamma_mean": float(np.mean(bull)),
                        "bear_gamma_mean": float(np.mean(bear)),
                        "mann_whitney_p": float(t_p),
                    }

        driver_results[asset] = drivers

    return driver_results


# ─────────────────────────────────────────────
# Part 5: Cross-asset gamma synchronization
# ─────────────────────────────────────────────
def analyze_cross_asset_sync(gamma_series):
    """Analyze cross-asset gamma correlation."""
    print("\n" + "=" * 70)
    print("PART 5: Cross-Asset Gamma Synchronization")
    print("=" * 70)

    # Align gamma series by date (monthly granularity)
    aligned = {}
    for asset, roll in gamma_series.items():
        # Create monthly index
        roll_indexed = roll.set_index("date")["gamma"]
        roll_monthly = roll_indexed.resample("ME").mean()
        aligned[asset] = roll_monthly

    if len(aligned) < 2:
        print("  Not enough assets for cross-asset analysis")
        return {}

    # Build correlation matrix on overlapping period
    combined = pd.DataFrame(aligned)
    combined = combined.dropna()

    print(f"\n  Overlapping period: {len(combined)} months")
    if len(combined) < 12:
        print("  Insufficient overlap for meaningful analysis")
        return {}

    print(f"  Date range: {combined.index[0].strftime('%Y-%m')} to {combined.index[-1].strftime('%Y-%m')}")

    # Correlation matrix
    corr_matrix = combined.corr(method="spearman")
    print(f"\n  Spearman Correlation Matrix of Gamma Series:")
    print(f"  {'':>10}", end="")
    for col in corr_matrix.columns:
        print(f"  {col:>8}", end="")
    print()
    for row in corr_matrix.index:
        print(f"  {row:>10}", end="")
        for col in corr_matrix.columns:
            val = corr_matrix.loc[row, col]
            print(f"  {val:>8.3f}", end="")
        print()

    # Pairwise significance
    sync_results = {"n_months_overlap": int(len(combined))}
    pair_details = {}

    for i, a1 in enumerate(combined.columns):
        for a2 in combined.columns[i+1:]:
            valid = combined[[a1, a2]].dropna()
            if len(valid) >= 10:
                r, p = stats.spearmanr(valid[a1], valid[a2])
                sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
                print(f"\n  {a1} vs {a2}: rho={r:.3f}, p={p:.4f} {sig}")

                # Rolling correlation (3-year window)
                if len(valid) >= 36:
                    rolling_corr = valid[a1].rolling(36).corr(valid[a2])
                    rc_valid = rolling_corr.dropna()
                    if len(rc_valid) > 0:
                        print(f"    3y rolling corr: [{rc_valid.min():.3f}, {rc_valid.max():.3f}], mean={rc_valid.mean():.3f}")
                        pair_details[f"{a1}_vs_{a2}"] = {
                            "spearman_rho": float(r),
                            "p": float(p),
                            "rolling_corr_min": float(rc_valid.min()),
                            "rolling_corr_max": float(rc_valid.max()),
                            "rolling_corr_mean": float(rc_valid.mean()),
                        }
                    else:
                        pair_details[f"{a1}_vs_{a2}"] = {
                            "spearman_rho": float(r),
                            "p": float(p),
                        }
                else:
                    pair_details[f"{a1}_vs_{a2}"] = {
                        "spearman_rho": float(r),
                        "p": float(p),
                    }

    # Principal component: what fraction of gamma variation is common?
    if len(combined) >= 24 and combined.shape[1] >= 3:
        from numpy.linalg import eig
        # Standardize
        standardized = (combined - combined.mean()) / combined.std()
        cov_matrix = standardized.cov().values
        eigenvalues, eigenvectors = eig(cov_matrix)
        eigenvalues = np.real(eigenvalues)
        eigenvalues = np.sort(eigenvalues)[::-1]
        total_var = np.sum(eigenvalues)
        pc1_share = eigenvalues[0] / total_var
        pc2_share = eigenvalues[1] / total_var if len(eigenvalues) > 1 else 0
        print(f"\n  PCA of gamma series:")
        print(f"    PC1 explains {pc1_share*100:.1f}% of variance")
        print(f"    PC1+PC2 explains {(pc1_share+pc2_share)*100:.1f}% of variance")
        sync_results["pc1_variance_share"] = float(pc1_share)
        sync_results["pc1_pc2_variance_share"] = float(pc1_share + pc2_share)

    sync_results["pairs"] = pair_details

    return sync_results


# ─────────────────────────────────────────────
# Part 6: Gamma → VT effectiveness
# ─────────────────────────────────────────────
def analyze_gamma_vt_link(gamma_series, data):
    """Does higher gamma predict better VT performance?"""
    print("\n" + "=" * 70)
    print("PART 6: Gamma → VT Effectiveness (Does Higher Gamma Help VT?)")
    print("=" * 70)

    vt_link_results = {}

    for asset, roll in gamma_series.items():
        if asset not in data or "VIX" not in data:
            continue

        df = data[asset]
        vix_df = data["VIX"]

        print(f"\n  {asset}:")

        # For each gamma window, compute forward VT performance
        # Use simple 12/VIX strategy for 22-day forward period
        gamma_vals = []
        vt_sharpes = []
        bh_sharpes = []
        vt_mdd_improvements = []

        for _, row in roll.iterrows():
            date = row["date"]
            gamma = row["gamma"]

            # Get forward 252 trading days
            future_mask = df.index > date
            future = df.loc[future_mask].head(252)

            if len(future) < 126:  # need at least 6 months
                continue

            # VIX alignment
            vix_aligned = vix_df["Close"].reindex(future.index, method="ffill")
            if vix_aligned.isna().sum() > len(future) * 0.2:
                continue
            vix_aligned = vix_aligned.ffill().fillna(20)

            # Simple VT: w = 12/VIX (lagged by 1 day)
            weights = np.minimum(12.0 / vix_aligned.shift(1), 1.5)
            weights = weights.fillna(1.0)

            ret = future["returns"].values
            w = weights.values

            vt_ret = ret * w
            bh_ret = ret

            # Sharpe
            if np.std(vt_ret) > 0 and np.std(bh_ret) > 0:
                vt_sharpe = np.mean(vt_ret) / np.std(vt_ret) * np.sqrt(252)
                bh_sharpe = np.mean(bh_ret) / np.std(bh_ret) * np.sqrt(252)

                # MDD
                vt_cum = np.cumsum(vt_ret)
                bh_cum = np.cumsum(bh_ret)
                vt_mdd = np.min(vt_cum - np.maximum.accumulate(vt_cum))
                bh_mdd = np.min(bh_cum - np.maximum.accumulate(bh_cum))

                mdd_improvement = (abs(bh_mdd) - abs(vt_mdd)) / abs(bh_mdd) * 100 if bh_mdd != 0 else 0

                gamma_vals.append(gamma)
                vt_sharpes.append(vt_sharpe)
                bh_sharpes.append(bh_sharpe)
                vt_mdd_improvements.append(mdd_improvement)

        if len(gamma_vals) < 10:
            print(f"    Insufficient data for gamma-VT link analysis")
            continue

        gamma_arr = np.array(gamma_vals)
        vt_arr = np.array(vt_sharpes)
        bh_arr = np.array(bh_sharpes)
        mdd_arr = np.array(vt_mdd_improvements)
        vt_advantage = vt_arr - bh_arr

        # Correlation: gamma vs VT advantage
        r_sharpe, p_sharpe = stats.spearmanr(gamma_arr, vt_advantage)
        r_mdd, p_mdd = stats.spearmanr(gamma_arr, mdd_arr)

        print(f"    N windows: {len(gamma_vals)}")
        print(f"    gamma vs VT Sharpe advantage: rho={r_sharpe:.3f}, p={p_sharpe:.4f}")
        print(f"    gamma vs MDD improvement:     rho={r_mdd:.3f}, p={p_mdd:.4f}")

        # Split by high/low gamma
        median_gamma = np.median(gamma_arr)
        high_mask = gamma_arr > median_gamma
        low_mask = gamma_arr <= median_gamma

        if high_mask.sum() >= 5 and low_mask.sum() >= 5:
            high_sharpe = np.mean(vt_advantage[high_mask])
            low_sharpe = np.mean(vt_advantage[low_mask])
            high_mdd = np.mean(mdd_arr[high_mask])
            low_mdd = np.mean(mdd_arr[low_mask])

            print(f"\n    High gamma (>{median_gamma:.3f}):")
            print(f"      VT Sharpe advantage: {high_sharpe:+.3f}")
            print(f"      MDD improvement: {high_mdd:.1f}%")
            print(f"    Low gamma (<={median_gamma:.3f}):")
            print(f"      VT Sharpe advantage: {low_sharpe:+.3f}")
            print(f"      MDD improvement: {low_mdd:.1f}%")

            vt_link_results[asset] = {
                "n_windows": len(gamma_vals),
                "gamma_vs_vt_sharpe_rho": float(r_sharpe),
                "gamma_vs_vt_sharpe_p": float(p_sharpe),
                "gamma_vs_mdd_improvement_rho": float(r_mdd),
                "gamma_vs_mdd_improvement_p": float(p_mdd),
                "high_gamma_vt_advantage": float(high_sharpe),
                "low_gamma_vt_advantage": float(low_sharpe),
                "high_gamma_mdd_improvement": float(high_mdd),
                "low_gamma_mdd_improvement": float(low_mdd),
                "median_gamma": float(median_gamma),
            }

    return vt_link_results


# ─────────────────────────────────────────────
# Part 7: Decade analysis
# ─────────────────────────────────────────────
def analyze_by_decade(gamma_series):
    """Analyze gamma by decade."""
    print("\n" + "=" * 70)
    print("PART 7: Gamma by Decade")
    print("=" * 70)

    decade_results = {}

    for asset, roll in gamma_series.items():
        print(f"\n  {asset}:")

        roll = roll.copy()
        roll["year"] = roll["date"].dt.year
        roll["decade"] = (roll["year"] // 10) * 10

        decades = sorted(roll["decade"].unique())
        asset_decades = {}

        for decade in decades:
            dec_data = roll[roll["decade"] == decade]
            if len(dec_data) < 5:
                continue

            gamma = dec_data["gamma"].values
            m = np.mean(gamma)
            s = np.std(gamma)
            cv = s / abs(m) if abs(m) > 1e-8 else np.nan

            print(f"    {decade}s: n={len(dec_data)}, gamma={m:.4f} ± {s:.4f}, CV={cv:.3f}")

            asset_decades[str(decade)] = {
                "n": int(len(dec_data)),
                "gamma_mean": float(m),
                "gamma_std": float(s),
                "gamma_cv": float(cv) if not np.isnan(cv) else None,
            }

        # Kruskal-Wallis test across decades
        if len(decades) >= 3:
            groups = [roll[roll["decade"] == d]["gamma"].values for d in decades if len(roll[roll["decade"] == d]) >= 5]
            if len(groups) >= 3:
                kw_stat, kw_p = stats.kruskal(*groups)
                print(f"    Kruskal-Wallis across decades: H={kw_stat:.2f}, p={kw_p:.4f}")
                asset_decades["kruskal_wallis_h"] = float(kw_stat)
                asset_decades["kruskal_wallis_p"] = float(kw_p)

        decade_results[asset] = asset_decades

    return decade_results


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    t_start = time.time()

    # Download data
    data = download_data()

    # Part 1: Rolling gamma & trend
    gamma_series, trend_results = analyze_gamma_trends(data)

    # Part 2: Rolling CV(gamma)
    cv_results = analyze_rolling_cv(gamma_series)

    # Part 3: Structural breaks
    break_results = analyze_structural_breaks(gamma_series)

    # Part 4: Gamma drivers
    driver_results = analyze_gamma_drivers(gamma_series, data)

    # Part 5: Cross-asset synchronization
    sync_results = analyze_cross_asset_sync(gamma_series)

    # Part 6: Gamma → VT link
    vt_link_results = analyze_gamma_vt_link(gamma_series, data)

    # Part 7: Decade analysis
    decade_results = analyze_by_decade(gamma_series)

    elapsed = time.time() - t_start

    # ─────────────────────────────────────────────
    # Summary
    # ─────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("SUMMARY: K228 Time-Varying Leverage Effect")
    print("=" * 70)

    print("\n1. GAMMA TRENDS:")
    for asset, tr in trend_results.items():
        trend_str = tr["mann_kendall_trend"]
        sig_str = f"(p={tr['mann_kendall_p']:.4f})"
        annual = tr.get("annual_change", 0)
        print(f"   {asset:>8}: MK trend={trend_str:>12} {sig_str}, "
              f"annual change={annual:+.4f}, first5y={tr['first_5y_mean']:.4f} → last5y={tr['last_5y_mean']:.4f}")

    print("\n2. CV(GAMMA) STABILITY:")
    for asset, cv in cv_results.items():
        full_cv = cv.get("full_sample_cv", "N/A")
        if isinstance(full_cv, float):
            print(f"   {asset:>8}: full-sample CV={full_cv:.3f}", end="")
        else:
            print(f"   {asset:>8}: full-sample CV=N/A", end="")
        if cv.get("rolling_cv_available"):
            print(f", rolling range=[{cv['rolling_cv_min']:.3f}, {cv['rolling_cv_max']:.3f}]")
        else:
            print()

    print("\n3. STRUCTURAL BREAKS:")
    for asset, br in break_results.items():
        if br["n_breaks"] == 0:
            print(f"   {asset:>8}: No breaks detected")
        else:
            for b in br["breaks"]:
                print(f"   {asset:>8}: Break at {b['date']}, gamma {b['gamma_before']:.4f} → {b['gamma_after']:.4f} "
                      f"({b.get('change_pct', 0):+.1f}%), Chow p={b.get('chow_p', 'N/A')}")

    print("\n4. GAMMA DRIVERS (significant correlations):")
    for asset, drivers in driver_results.items():
        sigs = []
        for driver, vals in drivers.items():
            if isinstance(vals, dict) and "spearman_rho" in vals:
                if vals["p"] < 0.05:
                    sigs.append(f"{driver}: rho={vals['spearman_rho']:.3f}")
        if sigs:
            print(f"   {asset:>8}: {', '.join(sigs)}")
        else:
            print(f"   {asset:>8}: No significant drivers")

    print("\n5. CROSS-ASSET SYNC:")
    if sync_results and "pairs" in sync_results:
        for pair, vals in sync_results["pairs"].items():
            sig = "*" if vals["p"] < 0.10 else ""
            print(f"   {pair:>20}: rho={vals['spearman_rho']:.3f}, p={vals['p']:.4f} {sig}")
        if "pc1_variance_share" in sync_results:
            print(f"   PC1 explains {sync_results['pc1_variance_share']*100:.1f}% of gamma variation")

    print("\n6. GAMMA → VT LINK:")
    for asset, vt in vt_link_results.items():
        print(f"   {asset:>8}: gamma→Sharpe rho={vt['gamma_vs_vt_sharpe_rho']:.3f} (p={vt['gamma_vs_vt_sharpe_p']:.4f}), "
              f"gamma→MDD rho={vt['gamma_vs_mdd_improvement_rho']:.3f} (p={vt['gamma_vs_mdd_improvement_p']:.4f})")
        print(f"            High gamma VT adv: {vt['high_gamma_vt_advantage']:+.3f} Sharpe, "
              f"MDD impr: {vt['high_gamma_mdd_improvement']:.1f}%")
        print(f"            Low gamma VT adv:  {vt['low_gamma_vt_advantage']:+.3f} Sharpe, "
              f"MDD impr: {vt['low_gamma_mdd_improvement']:.1f}%")

    print(f"\nTotal time: {elapsed:.1f}s")

    # Save results
    all_results = {
        "experiment": "K228",
        "title": "Time-Varying Leverage Effect — Is Gamma Increasing Over Time?",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "assets": ASSETS,
            "window": WINDOW,
            "step": STEP,
            "cv_window_years": CV_WINDOW_YEARS,
        },
        "trend_analysis": trend_results,
        "cv_analysis": cv_results,
        "structural_breaks": break_results,
        "gamma_drivers": driver_results,
        "cross_asset_sync": sync_results,
        "gamma_vt_link": vt_link_results,
        "decade_analysis": decade_results,
        "runtime_seconds": round(elapsed, 1),
    }

    with open(RESULTS_FILE, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()
