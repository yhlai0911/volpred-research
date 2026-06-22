#!/usr/bin/env python3
"""Experiment: Adaptive Window VaR vs Fixed Window VaR.

Motivation (T4): Normal VaR fails for opposite reasons:
  - GLD has fat tails → too many violations
  - TLT/IEF have regime shifts → too few violations (2022 rate-hike vol
    still in w=2000 window inflates sigma)
This suggests window choice matters more than distribution choice.

Window Strategies:
  1. Fixed w=2000 (baseline)
  2. Fixed w=504 (shorter, more reactive)
  3. Adaptive: w = min(2000, max(504, days_since_last_regime_change))
     Regime change = CUSUM test on rolling variance
  4. EWMA lambda=0.94 (RiskMetrics style, no fixed window)
  5. Expanding window (all available data)

For each: 1% Normal VaR and 1% CF-VaR, Kupiec test, VaR volatility.
OOS: 2023-01-01 to 2024-12-31.

Usage:
    uv run python scripts/experiment_adaptive_window_var.py
"""
import json
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "IEF", "EEM", "BTC-USD"]
ALPHA = 0.01  # 1% VaR
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
VAR_METHODS = ["Normal", "CF-VaR"]
WINDOW_STRATEGIES = ["Fixed_2000", "Fixed_504", "Adaptive_CUSUM", "EWMA_094", "Expanding"]

# EWMA decay factor
EWMA_LAMBDA = 0.94


def warn_garch_forecast_failure(asset, strategy, date, idx, window, exc):
    """Warn without aborting the asset-level forecast sweep."""
    date_label = date.strftime("%Y-%m-%d") if hasattr(date, "strftime") else str(date)
    print(
        f"[adaptive_window_var] WARN GARCH forecast failed "
        f"asset={asset} strategy={strategy} date={date_label} "
        f"idx={idx} window={window}: {type(exc).__name__}: {exc}",
        flush=True,
    )


# ── VaR Computation ───────────────────────────────────────────────────

def var_normal(sigma, alpha=0.01):
    """Normal VaR: z_alpha * sigma."""
    return -stats.norm.ppf(alpha) * sigma


def var_cornish_fisher(sigma, skew, kurt, alpha=0.01):
    """Cornish-Fisher VaR expansion.
    z_cf = z + (z^2 - 1)*S/6 + (z^3 - 3z)*K/24 - (2z^3 - 5z)*S^2/36
    where K = excess kurtosis.
    """
    z = stats.norm.ppf(alpha)  # negative
    S = skew
    K = kurt - 3  # excess kurtosis
    z_cf = (z
            + (z**2 - 1) * S / 6
            + (z**3 - 3 * z) * K / 24
            - (2 * z**3 - 5 * z) * S**2 / 36)
    return -z_cf * sigma


# ── Kupiec Test ───────────────────────────────────────────────────────

def kupiec_test(violations, alpha=0.01):
    """Kupiec POF test for unconditional coverage."""
    T = len(violations)
    n = int(np.sum(violations))
    p_hat = n / T if T > 0 else 0

    if n == 0 or n == T:
        return {"statistic": np.inf, "p_value": 0.0, "pass": False,
                "n_violations": n, "total": T, "obs_rate": p_hat,
                "expected": alpha}

    lr = -2 * (np.log((1 - alpha)**(T - n) * alpha**n)
               - np.log((1 - p_hat)**(T - n) * p_hat**n))
    p_value = 1 - stats.chi2.cdf(lr, 1)

    return {"statistic": float(lr), "p_value": float(p_value),
            "pass": p_value >= 0.05, "n_violations": n,
            "total": T, "obs_rate": float(p_hat),
            "expected": alpha}


# ── Structural Break Detection ────────────────────────────────────────

def detect_structural_breaks(returns, min_segment=252):
    """Detect variance regime breaks using sequential F-test.

    Searches for points where the variance of returns significantly changes,
    requiring at least min_segment=252 days (1 year) between breaks.
    This avoids the over-detection problem of standard CUSUM.

    Returns: list of break-point indices.
    """
    T = len(returns)
    if T < 2 * min_segment:
        return []

    breaks = []
    start = 0

    while start + 2 * min_segment <= T:
        best_f = 0
        best_bp = None

        # Search for break point within reachable range
        search_end = min(start + 5 * min_segment, T - min_segment)
        for bp in range(start + min_segment, search_end):
            seg1 = returns[start:bp]
            seg2 = returns[bp:min(bp + min_segment, T)]

            if len(seg1) < min_segment or len(seg2) < min_segment // 2:
                continue

            var1 = np.var(seg1)
            var2 = np.var(seg2)

            if var1 < 1e-12 or var2 < 1e-12:
                continue

            # F-test for equal variances
            f_stat = max(var1 / var2, var2 / var1)

            if f_stat > best_f:
                best_f = f_stat
                best_bp = bp

        # Conservative F-test threshold (≈1% significance)
        if best_bp is not None and best_f > 2.0:
            breaks.append(best_bp)
            start = best_bp
        else:
            break

    return breaks


def compute_adaptive_window(returns_up_to_idx, min_w=504, max_w=2000):
    """Compute adaptive window size based on last structural break.

    w = min(max_w, max(min_w, days_since_last_break))
    """
    if len(returns_up_to_idx) < min_w:
        return min_w

    breaks = detect_structural_breaks(returns_up_to_idx, min_segment=252)

    if len(breaks) == 0:
        return max_w  # No break detected → use full window

    last_break_idx = breaks[-1]
    days_since = len(returns_up_to_idx) - last_break_idx

    return min(max_w, max(min_w, days_since))


# ── EWMA Variance ────────────────────────────────────────────────────

def ewma_variance(returns, lam=0.94):
    """Compute EWMA variance series.

    sigma^2_t = lambda * sigma^2_{t-1} + (1-lambda) * r^2_{t-1}
    """
    T = len(returns)
    var_series = np.zeros(T)
    var_series[0] = np.var(returns[:min(20, T)])  # initialize

    for t in range(1, T):
        var_series[t] = lam * var_series[t-1] + (1 - lam) * returns[t-1]**2

    return var_series


# ── Rolling Forecast Engine ──────────────────────────────────────────

def download_data(asset, oos_start, oos_end):
    """Download and prepare data."""
    extra_years = 12  # Enough for w=2000 + buffer
    data_start = f"{int(oos_start[:4]) - extra_years}-01-01"

    print(f"  Downloading {asset} from {data_start}...")
    data = yf.download(asset, start=data_start, end=oos_end, progress=False)

    if len(data) == 0:
        return None, None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data["return"] = data["Close"].pct_change()
    data = data.dropna()

    oos_mask = (data.index >= pd.Timestamp(oos_start)) & (data.index <= pd.Timestamp(oos_end))
    oos_dates = data.index[oos_mask]

    return data, oos_dates


def run_garch_forecast(train_pct):
    """Fit GJR-GARCH(1,1) and return forecast sigma (in decimal)."""
    am = arch_model(train_pct, vol="GARCH", p=1, q=1, o=1,
                    dist="normal", mean="Zero", rescale=False)
    res = am.fit(disp="off", show_warning=False)
    fcast = res.forecast(horizon=1)
    sigma_pct = fcast.variance.iloc[-1, 0] ** 0.5
    sigma = sigma_pct / 100

    # Standardized residuals for skewness/kurtosis
    std_resid = res.std_resid
    sample_skew = float(stats.skew(std_resid))
    sample_kurt = float(stats.kurtosis(std_resid, fisher=False))

    return sigma, sample_skew, sample_kurt


def run_forecasts_for_asset(asset, data, oos_dates):
    """Run all window strategies for one asset.

    Returns dict: strategy -> list of {date, actual_return, sigma, skew, kurt}
    """
    returns = data["return"].values
    returns_pct = data["return"].values * 100
    all_idx = data.index

    results = {s: [] for s in WINDOW_STRATEGIES}

    # Pre-compute EWMA variance for the entire series
    ewma_var = ewma_variance(returns, lam=EWMA_LAMBDA)

    n_oos = len(oos_dates)
    print(f"  OOS: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')} ({n_oos} days)")

    # Pre-compute adaptive windows: detect breaks once using data up to OOS start,
    # then compute window for each OOS day based on last break relative to that day.
    first_oos_idx = data.index.get_loc(oos_dates[0])
    all_breaks = detect_structural_breaks(returns[:first_oos_idx], min_segment=252)
    print(f"  Structural breaks detected (pre-OOS): {len(all_breaks)} at indices {all_breaks}")
    adaptive_windows = []
    for i, date in enumerate(oos_dates):
        idx = data.index.get_loc(date)
        if len(all_breaks) == 0:
            adaptive_windows.append(2000)
        else:
            last_break = all_breaks[-1]
            days_since = idx - last_break
            adaptive_windows.append(min(2000, max(504, days_since)))
    if len(adaptive_windows) > 0:
        print(f"  Adaptive window range: {min(adaptive_windows)}-{max(adaptive_windows)} (mean={np.mean(adaptive_windows):.0f})")

    for i, date in enumerate(oos_dates):
        idx = data.index.get_loc(date)
        actual_return = returns[idx]

        # ── Strategy 1: Fixed w=2000 ──
        w = 2000
        if idx >= w:
            try:
                train = returns_pct[idx - w: idx]
                sigma, skew, kurt = run_garch_forecast(train)
                results["Fixed_2000"].append({
                    "date": date, "actual_return": actual_return,
                    "sigma": sigma, "skew": skew, "kurt": kurt
                })
            except Exception as exc:
                warn_garch_forecast_failure(asset, "Fixed_2000", date, idx, w, exc)

        # ── Strategy 2: Fixed w=504 ──
        w = 504
        if idx >= w:
            try:
                train = returns_pct[idx - w: idx]
                sigma, skew, kurt = run_garch_forecast(train)
                results["Fixed_504"].append({
                    "date": date, "actual_return": actual_return,
                    "sigma": sigma, "skew": skew, "kurt": kurt
                })
            except Exception as exc:
                warn_garch_forecast_failure(asset, "Fixed_504", date, idx, w, exc)

        # ── Strategy 3: Adaptive (Structural Break) ──
        if idx >= 504:
            try:
                actual_w = min(adaptive_windows[i], idx)
                train = returns_pct[idx - actual_w: idx]
                sigma, skew, kurt = run_garch_forecast(train)
                results["Adaptive_CUSUM"].append({
                    "date": date, "actual_return": actual_return,
                    "sigma": sigma, "skew": skew, "kurt": kurt,
                    "window_used": actual_w
                })
            except Exception as exc:
                warn_garch_forecast_failure(asset, "Adaptive_CUSUM", date, idx, actual_w, exc)

        # ── Strategy 4: EWMA lambda=0.94 ──
        if idx >= 20:
            sigma_ewma = np.sqrt(ewma_var[idx])
            if sigma_ewma > 0:
                # For EWMA, compute skew/kurt from recent 504 standardized returns
                lookback = min(504, idx)
                recent_returns = returns[idx - lookback: idx]
                recent_sigma = np.sqrt(ewma_var[idx - lookback: idx])
                recent_sigma = np.maximum(recent_sigma, 1e-10)
                std_resid = recent_returns / recent_sigma
                skew_ewma = float(stats.skew(std_resid))
                kurt_ewma = float(stats.kurtosis(std_resid, fisher=False))
                results["EWMA_094"].append({
                    "date": date, "actual_return": actual_return,
                    "sigma": sigma_ewma, "skew": skew_ewma, "kurt": kurt_ewma
                })

        # ── Strategy 5: Expanding window ──
        if idx >= 504:
            try:
                train = returns_pct[:idx]  # all available data
                sigma, skew, kurt = run_garch_forecast(train)
                results["Expanding"].append({
                    "date": date, "actual_return": actual_return,
                    "sigma": sigma, "skew": skew, "kurt": kurt,
                    "window_used": idx
                })
            except Exception as exc:
                warn_garch_forecast_failure(asset, "Expanding", date, idx, idx, exc)

        # Progress
        if (i + 1) % 100 == 0:
            print(f"    {i+1}/{n_oos} days done...")

    for s in WINDOW_STRATEGIES:
        print(f"    {s}: {len(results[s])} forecasts")

    return results


# ── Main ──────────────────────────────────────────────────────────────

def main():
    start_time = time.time()
    print("=" * 100)
    print(" EXPERIMENT: Adaptive Window VaR vs Fixed Window VaR")
    print(f" Assets: {', '.join(ASSETS)}")
    print(f" Window Strategies: {', '.join(WINDOW_STRATEGIES)}")
    print(f" VaR Methods: {', '.join(VAR_METHODS)}")
    print(f" Alpha: {ALPHA} (1% VaR)")
    print(f" OOS: {OOS_START} to {OOS_END}")
    print(f" Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 100)

    # Master results table
    master_results = []  # list of dicts for DataFrame

    for asset in ASSETS:
        print(f"\n{'─' * 80}")
        print(f"Processing {asset}...")

        data, oos_dates = download_data(asset, OOS_START, OOS_END)
        if data is None or oos_dates is None or len(oos_dates) < 50:
            print(f"  SKIP: insufficient data for {asset}")
            continue

        print(f"  Total data: {len(data)} days")

        # Run all strategies
        strategy_results = run_forecasts_for_asset(asset, data, oos_dates)

        # Evaluate each strategy × VaR method
        for strategy in WINDOW_STRATEGIES:
            forecasts = strategy_results[strategy]
            if len(forecasts) < 50:
                print(f"  SKIP {strategy}: only {len(forecasts)} forecasts")
                continue

            actual_returns = np.array([f["actual_return"] for f in forecasts])
            sigmas = np.array([f["sigma"] for f in forecasts])
            skews = np.array([f["skew"] for f in forecasts])
            kurts = np.array([f["kurt"] for f in forecasts])

            for var_method in VAR_METHODS:
                # Compute VaR series
                if var_method == "Normal":
                    var_series = np.array([var_normal(s, ALPHA) for s in sigmas])
                elif var_method == "CF-VaR":
                    var_series = np.array([
                        var_cornish_fisher(s, sk, ku, ALPHA)
                        for s, sk, ku in zip(sigmas, skews, kurts)
                    ])
                else:
                    continue

                # Ensure VaR is positive
                var_series = np.maximum(var_series, 1e-8)

                # Violations
                violations = (actual_returns < -var_series).astype(int)

                # Kupiec test
                kup = kupiec_test(violations, ALPHA)

                # VaR volatility: std of daily VaR changes (measures stability)
                var_changes = np.diff(var_series)
                var_volatility = np.std(var_changes) if len(var_changes) > 1 else 0.0

                # Mean VaR level
                mean_var = np.mean(var_series)

                # Adaptive window stats
                if strategy == "Adaptive_CUSUM":
                    windows_used = [f.get("window_used", 0) for f in forecasts]
                    avg_window = np.mean(windows_used)
                    min_window = np.min(windows_used)
                    max_window = np.max(windows_used)
                elif strategy == "Expanding":
                    windows_used = [f.get("window_used", 0) for f in forecasts]
                    avg_window = np.mean(windows_used)
                    min_window = np.min(windows_used)
                    max_window = np.max(windows_used)
                else:
                    avg_window = min_window = max_window = None

                row = {
                    "asset": asset,
                    "strategy": strategy,
                    "var_method": var_method,
                    "n_obs": kup["total"],
                    "n_violations": kup["n_violations"],
                    "obs_rate": kup["obs_rate"],
                    "expected_rate": ALPHA,
                    "kupiec_stat": kup["statistic"],
                    "kupiec_p": kup["p_value"],
                    "kupiec_pass": kup["pass"],
                    "var_volatility": var_volatility,
                    "mean_var": mean_var,
                    "avg_window": avg_window,
                    "min_window": min_window,
                    "max_window": max_window,
                }
                master_results.append(row)

    elapsed = time.time() - start_time
    df = pd.DataFrame(master_results)

    # ── Print Results ─────────────────────────────────────────────────
    print("\n\n")
    print("=" * 130)
    print(" RESULTS: Adaptive Window VaR vs Fixed Window VaR")
    print(f" 1% VaR, OOS {OOS_START} to {OOS_END}")
    print("=" * 130)

    # Table 1: Full results matrix
    print("\n── Table 1: Full Results (all assets × strategies × VaR methods) ──")
    header = f"{'Asset':<10} {'Strategy':<17} {'VaR':<8} {'N':>5} {'Viol':>5} {'Rate':>6} {'Exp':>5} {'Kup-p':>7} {'Pass':>5} {'VaR-Vol':>9} {'MeanVaR':>8}"
    print(header)
    print("-" * 130)

    for asset in ASSETS:
        asset_df = df[df["asset"] == asset]
        if len(asset_df) == 0:
            continue

        first_row = True
        for _, row in asset_df.iterrows():
            asset_label = asset if first_row else ""
            first_row = False

            kup_p_str = f"{row['kupiec_p']:.3f}" if row['kupiec_p'] < 100 else "<.001"
            if row['kupiec_p'] < 0.001:
                kup_p_str = "<.001"

            pass_str = "PASS" if row["kupiec_pass"] else "FAIL"
            var_vol_str = f"{row['var_volatility']*100:.4f}%" if row['var_volatility'] else "N/A"
            mean_var_str = f"{row['mean_var']*100:.3f}%"

            line = f"{asset_label:<10} {row['strategy']:<17} {row['var_method']:<8} "
            line += f"{row['n_obs']:>5} {row['n_violations']:>5} {row['obs_rate']:.3f} {row['expected_rate']:.3f} "
            line += f"{kup_p_str:>7} {pass_str:>5} {var_vol_str:>9} {mean_var_str:>8}"
            print(line)
        print()

    # ── Table 2: Kupiec Pass Rate by Strategy ─────────────────────────
    print("\n── Table 2: Kupiec Pass Rate by Window Strategy ──")
    print(f"{'Strategy':<17} {'Normal Pass':>12} {'CF-VaR Pass':>12} {'Total Pass':>12} {'Pass Rate':>10}")
    print("-" * 70)

    for strategy in WINDOW_STRATEGIES:
        sdf = df[df["strategy"] == strategy]
        if len(sdf) == 0:
            continue

        normal_pass = sdf[sdf["var_method"] == "Normal"]["kupiec_pass"].sum()
        normal_total = len(sdf[sdf["var_method"] == "Normal"])
        cf_pass = sdf[sdf["var_method"] == "CF-VaR"]["kupiec_pass"].sum()
        cf_total = len(sdf[sdf["var_method"] == "CF-VaR"])
        total_pass = int(sdf["kupiec_pass"].sum())
        total_count = len(sdf)
        pass_rate = total_pass / total_count if total_count > 0 else 0

        print(f"{strategy:<17} {normal_pass:>5}/{normal_total:<5} {cf_pass:>5}/{cf_total:<5} {total_pass:>5}/{total_count:<5} {pass_rate:>9.1%}")

    # ── Table 3: Per-Asset Best Strategy ──────────────────────────────
    print("\n── Table 3: Per-Asset Analysis (which strategy works best?) ──")
    print(f"{'Asset':<10} {'Best Strategy (Normal)':>25} {'Best Strategy (CF-VaR)':>25} {'Issue':>30}")
    print("-" * 100)

    for asset in ASSETS:
        asset_df = df[df["asset"] == asset]
        if len(asset_df) == 0:
            continue

        # Find best strategy per VaR method (closest to 1% without fail)
        for var_method in VAR_METHODS:
            method_df = asset_df[asset_df["var_method"] == var_method]
            if len(method_df) == 0:
                continue
            # Best = pass Kupiec AND closest to 1%
            passing = method_df[method_df["kupiec_pass"] == True]
            if len(passing) > 0:
                best_idx = (passing["obs_rate"] - ALPHA).abs().idxmin()
                best_strategy = passing.loc[best_idx, "strategy"]
                best_rate = passing.loc[best_idx, "obs_rate"]
            else:
                best_idx = (method_df["obs_rate"] - ALPHA).abs().idxmin()
                best_strategy = method_df.loc[best_idx, "strategy"] + " (FAIL)"
                best_rate = method_df.loc[best_idx, "obs_rate"]

        # Determine issue for this asset
        normal_2000 = asset_df[(asset_df["strategy"] == "Fixed_2000") & (asset_df["var_method"] == "Normal")]
        if len(normal_2000) > 0:
            rate = normal_2000.iloc[0]["obs_rate"]
            if rate > ALPHA * 1.5:
                issue = "Fat tails (too many violations)"
            elif rate < ALPHA * 0.5:
                issue = "Regime shift (too few violations)"
            else:
                issue = "OK with baseline"
        else:
            issue = "No baseline data"

        # Find best Normal and best CF-VaR
        best_normal = "N/A"
        best_cf = "N/A"
        for vm, label_var in [("Normal", "best_normal"), ("CF-VaR", "best_cf")]:
            mdf = asset_df[asset_df["var_method"] == vm]
            if len(mdf) == 0:
                continue
            passing = mdf[mdf["kupiec_pass"] == True]
            if len(passing) > 0:
                best_idx = (passing["obs_rate"] - ALPHA).abs().idxmin()
                best_s = f"{passing.loc[best_idx, 'strategy']} ({passing.loc[best_idx, 'obs_rate']:.3f})"
            else:
                best_idx = (mdf["obs_rate"] - ALPHA).abs().idxmin()
                best_s = f"{mdf.loc[best_idx, 'strategy']} ({mdf.loc[best_idx, 'obs_rate']:.3f}) FAIL"
            if vm == "Normal":
                best_normal = best_s
            else:
                best_cf = best_s

        print(f"{asset:<10} {best_normal:>25} {best_cf:>25} {issue:>30}")

    # ── Table 4: Key Hypothesis Test ──────────────────────────────────
    print("\n── Table 4: Key Hypothesis — Does Adaptive/EWMA fix BOTH GLD and TLT? ──")
    print(f"{'Asset':<10} {'Strategy':<17} {'VaR Method':<10} {'Viol Rate':>10} {'Kupiec Pass':>12} {'Fixed_2000 Rate':>16}")
    print("-" * 85)

    focus_assets = ["GLD", "TLT", "IEF"]
    focus_strategies = ["Adaptive_CUSUM", "EWMA_094"]

    for asset in focus_assets:
        # Baseline
        baseline_normal = df[(df["asset"] == asset) & (df["strategy"] == "Fixed_2000") & (df["var_method"] == "Normal")]
        baseline_rate = baseline_normal.iloc[0]["obs_rate"] if len(baseline_normal) > 0 else float("nan")

        for strategy in focus_strategies:
            for vm in VAR_METHODS:
                row_df = df[(df["asset"] == asset) & (df["strategy"] == strategy) & (df["var_method"] == vm)]
                if len(row_df) == 0:
                    continue
                row = row_df.iloc[0]
                pass_str = "PASS" if row["kupiec_pass"] else "FAIL"
                print(f"{asset:<10} {strategy:<17} {vm:<10} {row['obs_rate']:>10.3f} {pass_str:>12} {baseline_rate:>16.3f}")
        print()

    # ── Table 5: Cross-Sectional Comparison ───────────────────────────
    print("\n── Table 5: Cross-Sectional — Adaptive+Normal vs Fixed+CF-VaR ──")
    print("Does adaptive window + Normal beat fixed window + CF-VaR?")
    print()

    combos = [
        ("Fixed_2000", "Normal"),
        ("Fixed_2000", "CF-VaR"),
        ("Fixed_504", "Normal"),
        ("Fixed_504", "CF-VaR"),
        ("Adaptive_CUSUM", "Normal"),
        ("Adaptive_CUSUM", "CF-VaR"),
        ("EWMA_094", "Normal"),
        ("EWMA_094", "CF-VaR"),
        ("Expanding", "Normal"),
        ("Expanding", "CF-VaR"),
    ]

    print(f"{'Strategy + VaR':<30} {'Pass':>5} {'Total':>6} {'Rate':>7} {'Avg |Rate-1%|':>14}")
    print("-" * 70)

    for strategy, vm in combos:
        combo_df = df[(df["strategy"] == strategy) & (df["var_method"] == vm)]
        if len(combo_df) == 0:
            continue
        n_pass = int(combo_df["kupiec_pass"].sum())
        n_total = len(combo_df)
        avg_dev = float((combo_df["obs_rate"] - ALPHA).abs().mean())
        label = f"{strategy} + {vm}"
        print(f"{label:<30} {n_pass:>5} {n_total:>6} {n_pass/n_total:>7.1%} {avg_dev:>14.4f}")

    # ── Table 6: VaR Stability ────────────────────────────────────────
    print("\n── Table 6: VaR Stability (lower VaR volatility = more stable) ──")
    print(f"{'Strategy':<17} {'Avg VaR-Vol (bps)':>18} {'Max VaR-Vol (bps)':>18}")
    print("-" * 60)

    for strategy in WINDOW_STRATEGIES:
        sdf = df[df["strategy"] == strategy]
        if len(sdf) == 0:
            continue
        avg_vol = sdf["var_volatility"].mean() * 10000
        max_vol = sdf["var_volatility"].max() * 10000
        print(f"{strategy:<17} {avg_vol:>18.2f} {max_vol:>18.2f}")

    # ── Table 7: Adaptive Window Statistics ───────────────────────────
    print("\n── Table 7: Adaptive Window Statistics (window sizes used) ──")
    adaptive_df = df[df["strategy"].isin(["Adaptive_CUSUM", "Expanding"])]
    if len(adaptive_df) > 0:
        print(f"{'Asset':<10} {'Strategy':<17} {'Avg Window':>11} {'Min Window':>11} {'Max Window':>11}")
        print("-" * 65)
        for _, row in adaptive_df.iterrows():
            if row["avg_window"] is not None:
                print(f"{row['asset']:<10} {row['strategy']:<17} {row['avg_window']:>11.0f} {row['min_window']:>11.0f} {row['max_window']:>11.0f}")

    # ── Summary / Conclusion ──────────────────────────────────────────
    print("\n\n" + "=" * 100)
    print(" SUMMARY & CONCLUSIONS")
    print("=" * 100)

    # Best overall strategy
    strategy_pass = df.groupby("strategy")["kupiec_pass"].agg(["sum", "count"])
    strategy_pass["rate"] = strategy_pass["sum"] / strategy_pass["count"]
    best_strategy = strategy_pass["rate"].idxmax()
    best_rate = strategy_pass.loc[best_strategy, "rate"]
    print(f"\n1. Best overall window strategy: {best_strategy} (Kupiec pass rate: {best_rate:.1%})")

    # Best combo
    combo_pass = df.groupby(["strategy", "var_method"])["kupiec_pass"].agg(["sum", "count"])
    combo_pass["rate"] = combo_pass["sum"] / combo_pass["count"]
    best_combo = combo_pass["rate"].idxmax()
    best_combo_rate = combo_pass.loc[best_combo, "rate"]
    print(f"2. Best strategy+VaR combo: {best_combo[0]} + {best_combo[1]} (pass rate: {best_combo_rate:.1%})")

    # Does adaptive+Normal beat fixed+CF-VaR?
    adaptive_normal = df[(df["strategy"] == "Adaptive_CUSUM") & (df["var_method"] == "Normal")]
    fixed_cf = df[(df["strategy"] == "Fixed_2000") & (df["var_method"] == "CF-VaR")]
    an_pass = adaptive_normal["kupiec_pass"].sum() / max(len(adaptive_normal), 1)
    fc_pass = fixed_cf["kupiec_pass"].sum() / max(len(fixed_cf), 1)
    print(f"3. Adaptive+Normal pass rate: {an_pass:.1%} vs Fixed_2000+CF-VaR: {fc_pass:.1%}")
    if an_pass > fc_pass:
        print("   → YES: Adaptive window + Normal beats fixed window + CF-VaR")
    elif an_pass == fc_pass:
        print("   → TIE: Both strategies have equal pass rates")
    else:
        print("   → NO: Fixed window + CF-VaR is better (distribution > window)")

    # Focus check: GLD and TLT
    for focus_asset in ["GLD", "TLT"]:
        print(f"\n4. {focus_asset} deep dive:")
        fdf = df[df["asset"] == focus_asset]
        for _, row in fdf.iterrows():
            status = "PASS" if row["kupiec_pass"] else "FAIL"
            print(f"   {row['strategy']:>17} + {row['var_method']:<8}: rate={row['obs_rate']:.3f} {status}")

    print(f"\nElapsed time: {elapsed:.1f}s")

    # ── Save results ──────────────────────────────────────────────────
    save_data = {
        "title": "Adaptive Window VaR vs Fixed Window VaR",
        "generated_at": datetime.now().isoformat(),
        "config": {
            "assets": ASSETS,
            "alpha": ALPHA,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "window_strategies": WINDOW_STRATEGIES,
            "var_methods": VAR_METHODS,
            "ewma_lambda": EWMA_LAMBDA,
        },
        "results": df.to_dict(orient="records"),
        "summary": {
            "best_strategy": best_strategy,
            "best_strategy_pass_rate": float(best_rate),
            "best_combo": f"{best_combo[0]} + {best_combo[1]}",
            "best_combo_pass_rate": float(best_combo_rate),
            "adaptive_normal_pass_rate": float(an_pass),
            "fixed_cfvar_pass_rate": float(fc_pass),
            "elapsed_seconds": round(elapsed, 1),
        },
    }

    out_path = Path("storage/reports/experiment_adaptive_window_var.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(save_data, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {out_path}")

    return save_data


if __name__ == "__main__":
    main()
