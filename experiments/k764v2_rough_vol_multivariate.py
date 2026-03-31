"""
K764v2: Rough Volatility Multivariate — RERUN 0050.TW portion with clean_tw50_data
=====================================================================================

This is a partial rerun of K764 focusing only on the 0050.TW portion.
SPY and GLD results are unaffected by the 0050.TW split fix.

Original K764 finding for 0050.TW: H=0.003 (extremely rough, suspiciously low).
Key question: Does H=0.003 survive with clean data?

Data: 0050.TW daily from yfinance, 2005-2026
Author: [提出: User (rerun request), 執行: Claude]
"""

from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))
from volpred.utils import clean_tw50_data


# ============================================================
#  Utility functions (same as K764)
# ============================================================

def print_section(title: str, char: str = "=", width: int = 72):
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def estimate_hurst_variogram(log_vol: np.ndarray, max_lag: int = 50) -> tuple:
    """Variogram estimator (Gatheral et al. 2018)."""
    T = len(log_vol)
    if T < max_lag + 10:
        max_lag = max(T // 3, 2)
    lags = np.arange(1, max_lag + 1)
    m2_vals = np.empty(len(lags))
    for i, delta in enumerate(lags):
        diffs = log_vol[delta:] - log_vol[:-delta]
        m2_vals[i] = np.mean(diffs ** 2)
    log_lags = np.log(lags.astype(float))
    log_m2 = np.log(m2_vals)
    slope, intercept, r_value, p_value, _ = stats.linregress(log_lags, log_m2)
    H = slope / 2.0
    return float(H), float(r_value ** 2)


def estimate_hurst_rolling(log_vol: np.ndarray, window: int = 252,
                           max_lag: int = 30) -> np.ndarray:
    """Rolling window Hurst estimation via variogram."""
    T = len(log_vol)
    H_rolling = np.full(T, np.nan)
    for t in range(window - 1, T):
        segment = log_vol[t - window + 1:t + 1]
        H_val, _ = estimate_hurst_variogram(segment, max_lag=max_lag)
        H_rolling[t] = np.clip(H_val, 0.01, 0.99)
    return H_rolling


def descriptive_stats(series: np.ndarray, name: str):
    print(f"  {name}:")
    print(f"    N={len(series)}, Mean={np.mean(series):.6f}, Std={np.std(series):.6f}")
    print(f"    Skew={stats.skew(series):.3f}, Kurt={stats.kurtosis(series):.3f}")
    q = np.percentile(series, [5, 25, 50, 75, 95])
    print(f"    P5={q[0]:.6f}, P25={q[1]:.6f}, P50={q[2]:.6f}, P75={q[3]:.6f}, P95={q[4]:.6f}")


def adf_test(series: np.ndarray, name: str) -> dict:
    from statsmodels.tsa.stattools import adfuller
    result = adfuller(series, maxlag=20, autolag="AIC")
    print(f"  ADF ({name}): stat={result[0]:.4f}, p={result[1]:.4f}, "
          f"{'Stationary' if result[1] < 0.05 else 'Non-stationary'}")
    return {"stat": round(result[0], 4), "p": round(result[1], 4),
            "stationary": result[1] < 0.05}


# ============================================================
#  Data Loading
# ============================================================

def load_tw50_data():
    """Load and clean 0050.TW from yfinance."""
    import yfinance as yf

    print_section("Data Loading — 0050.TW (clean)")

    print("  Loading 0050.TW...")
    df = yf.download("0050.TW", start="2005-01-01", end="2026-04-01",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    prices_raw = df["Close"].dropna()
    print(f"  Raw: {len(prices_raw)} obs, {prices_raw.index[0].date()} to {prices_raw.index[-1].date()}")

    # Apply clean_tw50_data
    print("  Applying clean_tw50_data...")
    clean_prices, clean_returns = clean_tw50_data(prices_raw)

    n_changed = (prices_raw != clean_prices).sum()
    print(f"  Prices changed: {n_changed}")

    # Check breakpoint
    bp = pd.Timestamp("2014-01-02")
    if bp in prices_raw.index:
        pre_dates = prices_raw.index[prices_raw.index < bp]
        if len(pre_dates) > 0:
            pre_date = pre_dates[-1]
            print(f"  Before fix: {pre_date.date()}={prices_raw.loc[pre_date]:.2f}, "
                  f"2014-01-02={prices_raw.loc[bp]:.2f}")
            print(f"  After fix:  {pre_date.date()}={clean_prices.loc[pre_date]:.2f}, "
                  f"2014-01-02={clean_prices.loc[bp]:.2f}")

    # Build returns from clean prices
    result_df = pd.DataFrame({"Close": clean_prices}).dropna()
    result_df["returns"] = np.log(result_df["Close"] / result_df["Close"].shift(1))
    result_df = result_df.dropna()
    result_df["abs_ret"] = np.abs(result_df["returns"])
    result_df["log_vol"] = np.log(result_df["abs_ret"].clip(lower=1e-10))

    print(f"  Clean data: {len(result_df)} obs, "
          f"{result_df.index[0].date()} to {result_df.index[-1].date()}")

    return result_df


# ============================================================
#  Part A: Roughness Estimation
# ============================================================

def run_part_a(df: pd.DataFrame) -> dict:
    """Estimate Hurst exponents for 0050.TW."""
    print_section("PART A: 0050.TW Roughness Estimation (clean data)")

    log_vol = df["log_vol"].values
    abs_ret = df["abs_ret"].values

    # Descriptive stats
    descriptive_stats(abs_ret, "0050.TW |r| (clean)")
    adf_result = adf_test(abs_ret, "0050.TW |r|")

    # Full-sample Hurst
    H_full, R2_full = estimate_hurst_variogram(log_vol, max_lag=50)
    print(f"\n  Full-sample Hurst (variogram): H={H_full:.4f}, R^2={R2_full:.4f}")

    # Rolling Hurst
    print(f"  Computing rolling Hurst (252-day window)...")
    H_rolling = estimate_hurst_rolling(log_vol, window=252, max_lag=30)
    valid_H = H_rolling[~np.isnan(H_rolling)]
    print(f"  Rolling H: mean={np.mean(valid_H):.4f}, std={np.std(valid_H):.4f}, "
          f"min={np.min(valid_H):.4f}, max={np.max(valid_H):.4f}")

    # Sub-period analysis
    n_valid = len(valid_H)
    third = n_valid // 3
    h_early = valid_H[:third]
    h_mid = valid_H[third:2*third]
    h_late = valid_H[2*third:]
    print(f"  H by sub-period: early={np.mean(h_early):.4f}, "
          f"mid={np.mean(h_mid):.4f}, late={np.mean(h_late):.4f}")

    frac_rough = np.mean(valid_H < 0.5)
    print(f"  Fraction H < 0.5 (rough): {frac_rough:.2%}")

    results = {
        "H_full_sample": round(H_full, 4),
        "H_R2": round(R2_full, 4),
        "H_rolling_mean": round(float(np.mean(valid_H)), 4),
        "H_rolling_std": round(float(np.std(valid_H)), 4),
        "H_rolling_min": round(float(np.min(valid_H)), 4),
        "H_rolling_max": round(float(np.max(valid_H)), 4),
        "H_early": round(float(np.mean(h_early)), 4),
        "H_mid": round(float(np.mean(h_mid)), 4),
        "H_late": round(float(np.mean(h_late)), 4),
        "frac_rough": round(frac_rough, 4),
        "adf": adf_result,
        "n_obs": len(df)
    }

    return results, H_rolling


# ============================================================
#  Part B: Compare with original K764 TW0050 results
# ============================================================

def run_comparison(results_a: dict) -> dict:
    """Compare with original K764 TW0050 results."""
    print_section("COMPARISON WITH ORIGINAL K764 (TW0050 portion)")

    orig_path = project_root / "experiments" / "k764_rough_vol_multivariate_results.json"
    try:
        with open(orig_path) as f:
            orig = json.load(f)

        orig_tw = orig.get('part_a_roughness', {}).get('TW0050', {})
        if orig_tw:
            orig_H = orig_tw.get('H_full_sample', None)
            new_H = results_a['H_full_sample']
            print(f"\n  Full-sample Hurst:")
            print(f"    Original K764: H = {orig_H}")
            print(f"    V2 (clean):    H = {new_H}")
            if orig_H is not None:
                print(f"    Change:        ΔH = {new_H - orig_H:+.4f}")

            orig_frac = orig_tw.get('frac_rough', None)
            new_frac = results_a['frac_rough']
            print(f"\n  Fraction rough (H<0.5):")
            print(f"    Original: {orig_frac}")
            print(f"    V2:       {new_frac}")

            orig_rolling_mean = orig_tw.get('H_rolling_mean', None)
            new_rolling_mean = results_a['H_rolling_mean']
            print(f"\n  Rolling H mean:")
            print(f"    Original: {orig_rolling_mean}")
            print(f"    V2:       {new_rolling_mean}")

            return {
                'original_H': orig_H,
                'new_H': new_H,
                'delta_H': round(new_H - orig_H, 4) if orig_H is not None else None,
                'original_frac_rough': orig_frac,
                'new_frac_rough': new_frac,
            }
        else:
            print("  No TW0050 data in original K764 results.")
            return {}

    except Exception as e:
        print(f"  Could not load original results: {e}")
        return {}


# ============================================================
#  Main
# ============================================================

def main():
    print("=" * 72)
    print("  K764v2: Rough Vol Multivariate — 0050.TW Rerun with clean_tw50_data")
    print("=" * 72)
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Load clean data
    tw_df = load_tw50_data()

    # Part A: Roughness
    part_a_results, H_rolling = run_part_a(tw_df)

    # Comparison
    comparison = run_comparison(part_a_results)

    # Conclusion
    print_section("CONCLUSION")
    H_new = part_a_results['H_full_sample']
    orig_H = comparison.get('original_H', None)

    conclusion_lines = []
    conclusion_lines.append(f"0050.TW full-sample Hurst: H={H_new:.4f} (clean data)")

    if orig_H is not None:
        delta = H_new - orig_H
        if abs(delta) < 0.02:
            conclusion_lines.append(f"CONCLUSION UNCHANGED: H shifted only {delta:+.4f} from original {orig_H}")
            changed = False
        else:
            conclusion_lines.append(f"CONCLUSION CHANGED: H shifted {delta:+.4f} (original {orig_H} → new {H_new})")
            changed = True
    else:
        conclusion_lines.append("Cannot compare — no original TW0050 data found")
        changed = None

    if H_new < 0.1:
        conclusion_lines.append(f"Extremely rough (H={H_new:.4f} < 0.1) — consistent with Gatheral et al. (2018)")
    elif H_new < 0.5:
        conclusion_lines.append(f"Rough (H={H_new:.4f} < 0.5) — confirms rough volatility for Taiwan equity")
    else:
        conclusion_lines.append(f"NOT rough (H={H_new:.4f} >= 0.5) — roughness NOT confirmed for 0050.TW")

    for line in conclusion_lines:
        print(f"  {line}")

    # Save results
    results = {
        "experiment_id": "K764v2",
        "title": "Rough Vol Multivariate — 0050.TW Rerun with clean_tw50_data",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "yfinance (0050.TW)",
        "vol_proxy": "|r| (daily absolute return)",
        "fix_applied": "clean_tw50_data — fixes 2014-01-02 split breakpoint",
        "part_a_roughness_tw0050": part_a_results,
        "comparison_with_original": comparison,
        "conclusion": {
            "lines": conclusion_lines,
            "changed": changed,
            "new_H": H_new,
            "original_H": orig_H,
        },
        "attribution": "[提出: User (rerun request), 執行: Claude]"
    }

    class NumpyEncoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            elif isinstance(obj, (np.floating,)):
                return float(obj)
            elif isinstance(obj, (np.bool_,)):
                return bool(obj)
            elif isinstance(obj, np.ndarray):
                return obj.tolist()
            return super().default(obj)

    results_path = project_root / "experiments" / "k764v2_rough_vol_multivariate_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
    print(f"\n  Results saved to: {results_path}")

    print(f"\n{'=' * 72}")
    print(f"  K764v2 COMPLETE")
    print(f"{'=' * 72}")

    return results


if __name__ == "__main__":
    main()
