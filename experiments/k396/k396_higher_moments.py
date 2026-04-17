"""
K396: Realized Higher Moments — Do Skewness and Kurtosis Predict Vol?
=====================================================================

Hypothesis:
  Rolling realized skewness (RS) and kurtosis (RK) contain information
  about FUTURE volatility beyond what VIX already captures.

  Related prior work:
  - K173: Hill tail index (r=-0.083, NS)
  - K386: SPY daily skewness NOT significant
  - K372: 48.7% noise in daily vol
  - K365: h=5d peak predictability
  - K277: BTC has no leverage effect

  But we've never tested ROLLING realized skewness/kurtosis as predictors.

Method:
  1. Compute 22d rolling realized moments:
     - RV = realized variance (benchmark)
     - RS = realized skewness = mean((r-mean)^3) / sigma^3
     - RK = realized kurtosis = mean((r-mean)^4) / sigma^4 - 3 (excess)
  2. Partial correlations: r(RS_t, RV_{t+22} | VIX_t)
  3. Cross-asset: SPY, GLD, BTC-USD
  4. Nonlinear transforms: |RS|, RS^2, |RK|
  5. OOS rolling validation (expanding window, 2020-2024 OOS)
  6. Bootstrap inference (10,000 reps)

Data: yfinance, 2005-2024 (BTC from 2014).

[提出: Claude (K396 higher moments exploration), 執行: Claude]
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# CONFIG
# ============================================================
DATA_START = "2005-01-01"
DATA_END = "2026-12-31"
OOS_START = "2020-01-01"
WINDOW_RV = 22        # rolling window for realized moments
WINDOW_PRED = 22      # prediction horizon (future 22d RV)
ASSETS = {
    "SPY": {"start": "2005-01-01", "vix": True},
    "GLD": {"start": "2005-01-01", "vix": True},
    "BTC-USD": {"start": "2014-09-17", "vix": False},
}

print("=" * 80)
print("K396: REALIZED HIGHER MOMENTS — DO SKEWNESS AND KURTOSIS PREDICT VOL?")
print("Rolling 22d skewness/kurtosis → future 22d RV, controlling for VIX")
print("=" * 80)


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def compute_rolling_moments(returns, window=22):
    """Compute rolling realized variance, skewness, and kurtosis."""
    n = len(returns)
    rv = np.full(n, np.nan)
    rs = np.full(n, np.nan)
    rk = np.full(n, np.nan)

    for i in range(window - 1, n):
        r = returns[i - window + 1:i + 1]
        mu = np.mean(r)
        sigma = np.std(r, ddof=1)
        if sigma < 1e-10:
            continue
        rv[i] = np.sum(r**2)  # realized variance (sum of squared returns)
        centered = r - mu
        rs[i] = np.mean(centered**3) / (sigma**3)      # skewness
        rk[i] = np.mean(centered**4) / (sigma**4) - 3  # excess kurtosis

    return rv, rs, rk


def compute_future_rv(returns, window=22):
    """Compute forward-looking realized variance (sum of squared returns over next window days)."""
    n = len(returns)
    frv = np.full(n, np.nan)
    for i in range(n - window):
        frv[i] = np.sum(returns[i + 1:i + 1 + window]**2)
    return frv


def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z.
    All inputs must be 1D arrays of same length, no NaN."""
    # Residualize x on z
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    if len(x) < 30:
        return np.nan, np.nan, len(x)

    # OLS residuals
    z_with_const = np.column_stack([z, np.ones(len(z))])
    try:
        beta_x = np.linalg.lstsq(z_with_const, x, rcond=None)[0]
        beta_y = np.linalg.lstsq(z_with_const, y, rcond=None)[0]
    except np.linalg.LinAlgError:
        return np.nan, np.nan, len(x)

    res_x = x - z_with_const @ beta_x
    res_y = y - z_with_const @ beta_y

    r, p = stats.pearsonr(res_x, res_y)
    return r, p, len(x)


def bootstrap_partial_corr(x, y, z, n_boot=10000, seed=42):
    """Bootstrap CI for partial correlation."""
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    n = len(x)
    if n < 30:
        return np.nan, np.nan, np.nan

    rng = np.random.RandomState(seed)
    boot_r = np.zeros(n_boot)

    for b in range(n_boot):
        idx = rng.choice(n, n, replace=True)
        r, _, _ = partial_corr(x[idx], y[idx], z[idx])
        boot_r[b] = r

    # Filter out NaN
    boot_r = boot_r[np.isfinite(boot_r)]
    if len(boot_r) < 100:
        return np.nan, np.nan, np.nan

    ci_lo = np.percentile(boot_r, 2.5)
    ci_hi = np.percentile(boot_r, 97.5)
    se = np.std(boot_r)
    return ci_lo, ci_hi, se


def oos_predictive_r2(predictor, target, oos_start_idx, expanding=True, min_train=500):
    """OOS predictive R² using expanding window regression.
    Benchmark = historical mean of target (random walk in variance)."""
    n = len(predictor)
    oos_errors_model = []
    oos_errors_bench = []

    for t in range(max(oos_start_idx, min_train), n - 1):
        if not np.isfinite(predictor[t]) or not np.isfinite(target[t]):
            continue

        # Training data
        if expanding:
            train_mask = np.arange(0, t)
        else:
            train_mask = np.arange(max(0, t - 2000), t)

        valid = np.isfinite(predictor[train_mask]) & np.isfinite(target[train_mask])
        x_train = predictor[train_mask[valid]]
        y_train = target[train_mask[valid]]

        if len(x_train) < 100:
            continue

        # Simple linear regression
        X = np.column_stack([x_train, np.ones(len(x_train))])
        try:
            beta = np.linalg.lstsq(X, y_train, rcond=None)[0]
        except np.linalg.LinAlgError:
            continue

        # OOS forecast
        y_hat = beta[0] * predictor[t] + beta[1]
        y_bench = np.mean(y_train)  # historical mean benchmark
        y_actual = target[t]

        if not np.isfinite(y_hat) or not np.isfinite(y_actual):
            continue

        oos_errors_model.append((y_actual - y_hat)**2)
        oos_errors_bench.append((y_actual - y_bench)**2)

    if len(oos_errors_model) < 50:
        return np.nan, 0

    msfe_model = np.mean(oos_errors_model)
    msfe_bench = np.mean(oos_errors_bench)

    oos_r2 = 1 - msfe_model / msfe_bench
    return oos_r2, len(oos_errors_model)


# ============================================================
# DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data from yfinance...")

all_data = {}
for asset, config in ASSETS.items():
    print(f"  Downloading {asset}...")
    ticker = yf.Ticker(asset)
    df = ticker.history(start=config["start"], end=DATA_END, auto_adjust=True)
    if len(df) < 500:
        print(f"  WARNING: {asset} only has {len(df)} days, skipping")
        continue
    df = df[['Close']].copy()
    df.columns = ['close']
    df['return'] = np.log(df['close'] / df['close'].shift(1))
    df = df.dropna()
    all_data[asset] = df
    print(f"  {asset}: {len(df)} days ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

# Download VIX for control variable
print("  Downloading ^VIX...")
vix_ticker = yf.Ticker("^VIX")
vix_df = vix_ticker.history(start=DATA_START, end=DATA_END, auto_adjust=True)
vix_df = vix_df[['Close']].copy()
vix_df.columns = ['vix']
print(f"  VIX: {len(vix_df)} days")


# ============================================================
# COMPUTE REALIZED MOMENTS
# ============================================================
print("\n[2] Computing rolling 22d realized moments...")

results_summary = {}

for asset, df in all_data.items():
    print(f"\n{'='*60}")
    print(f"  ASSET: {asset}")
    print(f"{'='*60}")

    returns = df['return'].values
    dates = df.index
    n = len(returns)

    # Compute rolling moments
    rv, rs, rk = compute_rolling_moments(returns, WINDOW_RV)

    # Compute future RV (target)
    frv = compute_future_rv(returns, WINDOW_PRED)

    # Align VIX
    vix_aligned = np.full(n, np.nan)
    if ASSETS[asset].get("vix", False):
        for i, d in enumerate(dates):
            d_naive = d.tz_localize(None) if d.tzinfo else d
            # Find closest VIX date
            vix_dates_naive = vix_df.index.tz_localize(None) if vix_df.index.tzinfo else vix_df.index
            mask = vix_dates_naive <= d_naive
            if mask.any():
                closest_idx = vix_dates_naive[mask][-1]
                if abs((d_naive - closest_idx).days) <= 5:
                    vix_aligned[i] = vix_df.loc[vix_df.index[vix_dates_naive == closest_idx][0], 'vix']

    # Log transform for better distributional properties
    log_frv = np.log(frv + 1e-10)
    log_rv = np.log(rv + 1e-10)

    # ========================================================
    # Part A: Full-sample partial correlations
    # ========================================================
    print(f"\n  --- Part A: Full-sample Partial Correlations ---")

    asset_results = {"asset": asset, "n_obs": n}

    # Basic stats of moments
    valid_rs = rs[np.isfinite(rs)]
    valid_rk = rk[np.isfinite(rk)]
    print(f"  RS: mean={np.mean(valid_rs):.4f}, std={np.std(valid_rs):.4f}, "
          f"median={np.median(valid_rs):.4f}")
    print(f"  RK: mean={np.mean(valid_rk):.4f}, std={np.std(valid_rk):.4f}, "
          f"median={np.median(valid_rk):.4f}")
    asset_results["rs_mean"] = float(np.mean(valid_rs))
    asset_results["rs_std"] = float(np.std(valid_rs))
    asset_results["rk_mean"] = float(np.mean(valid_rk))
    asset_results["rk_std"] = float(np.std(valid_rk))

    # Test 1: Raw partial correlations (controlling for VIX or RV)
    print(f"\n  Predictors → Future 22d RV:")

    tests = {
        "RS → FRV": (rs, frv),
        "RK → FRV": (rk, frv),
        "|RS| → FRV": (np.abs(rs), frv),
        "RS² → FRV": (rs**2, frv),
        "|RK| → FRV": (np.abs(rk), frv),
        "RS → log(FRV)": (rs, log_frv),
        "RK → log(FRV)": (rk, log_frv),
        "|RS| → log(FRV)": (np.abs(rs), log_frv),
    }

    # Control variable: VIX for SPY/GLD, current RV for BTC
    if ASSETS[asset].get("vix", False):
        control = vix_aligned
        control_name = "VIX"
    else:
        control = rv
        control_name = "RV_t"

    test_results = {}
    for test_name, (pred, target) in tests.items():
        r, p, nobs = partial_corr(pred, target, control)

        # Significance assessment
        sig = ""
        if p < 0.001:
            sig = "***"
        elif p < 0.01:
            sig = "**"
        elif p < 0.05:
            sig = "*"

        # Harvey (2016) t-stat check
        t_stat = r * np.sqrt(nobs - 3) / np.sqrt(1 - r**2) if abs(r) < 1 else np.nan
        harvey = "PASS" if abs(t_stat) > 3.0 else "FAIL"

        print(f"    {test_name:20s}: partial r = {r:+.4f}, p = {p:.4f} {sig:3s}, "
              f"t = {t_stat:+.2f} (Harvey: {harvey}), N = {nobs}")

        test_results[test_name] = {
            "partial_r": float(r) if np.isfinite(r) else None,
            "p_value": float(p) if np.isfinite(p) else None,
            "t_stat": float(t_stat) if np.isfinite(t_stat) else None,
            "harvey_pass": harvey == "PASS",
            "n_obs": int(nobs),
        }

    asset_results["partial_correlations"] = test_results

    # ========================================================
    # Part B: Bootstrap CIs for key predictors
    # ========================================================
    print(f"\n  --- Part B: Bootstrap CIs (10,000 reps) ---")

    bootstrap_results = {}
    key_tests = ["RS → FRV", "|RS| → FRV", "RK → FRV"]
    for test_name in key_tests:
        pred, target = tests[test_name]
        ci_lo, ci_hi, se = bootstrap_partial_corr(pred, target, control, n_boot=10000)
        contains_zero = ci_lo <= 0 <= ci_hi if np.isfinite(ci_lo) else True

        print(f"    {test_name:20s}: 95% CI = [{ci_lo:+.4f}, {ci_hi:+.4f}], "
              f"SE = {se:.4f}, contains 0: {contains_zero}")

        bootstrap_results[test_name] = {
            "ci_lo": float(ci_lo) if np.isfinite(ci_lo) else None,
            "ci_hi": float(ci_hi) if np.isfinite(ci_hi) else None,
            "se": float(se) if np.isfinite(se) else None,
            "contains_zero": contains_zero,
        }

    asset_results["bootstrap"] = bootstrap_results

    # ========================================================
    # Part C: OOS Predictive R²
    # ========================================================
    print(f"\n  --- Part C: OOS Predictive R² (expanding window, OOS from 2020) ---")

    # Find OOS start index
    oos_date = pd.Timestamp(OOS_START)
    if dates.tzinfo:
        oos_date = oos_date.tz_localize(dates.tzinfo)
    oos_idx = np.searchsorted(dates, oos_date)

    oos_results = {}
    oos_tests = {
        "RS": rs,
        "|RS|": np.abs(rs),
        "RS²": rs**2,
        "RK": rk,
        "|RK|": np.abs(rk),
        "RV (benchmark)": rv,
    }

    for test_name, pred in oos_tests.items():
        r2, n_oos = oos_predictive_r2(pred, frv, oos_idx)
        print(f"    {test_name:20s}: OOS R² = {r2:+.4f}, N_OOS = {n_oos}"
              if np.isfinite(r2) else f"    {test_name:20s}: OOS R² = N/A")
        oos_results[test_name] = {
            "oos_r2": float(r2) if np.isfinite(r2) else None,
            "n_oos": int(n_oos),
        }

    asset_results["oos_r2"] = oos_results

    # ========================================================
    # Part D: Regime analysis — does RS/RK matter more in high-vol?
    # ========================================================
    print(f"\n  --- Part D: Regime Conditioning (high vs low vol) ---")

    # Split by median RV
    median_rv = np.nanmedian(rv)
    high_vol = rv > median_rv
    low_vol = rv <= median_rv

    regime_results = {}
    for regime_name, mask in [("High Vol", high_vol), ("Low Vol", low_vol)]:
        regime_mask = mask & np.isfinite(rs) & np.isfinite(frv) & np.isfinite(control)
        if np.sum(regime_mask) < 100:
            print(f"    {regime_name}: insufficient data ({np.sum(regime_mask)} obs)")
            continue

        r_rs, p_rs, n_rs = partial_corr(rs[regime_mask], frv[regime_mask], control[regime_mask])
        r_rk, p_rk, n_rk = partial_corr(rk[regime_mask], frv[regime_mask], control[regime_mask])
        r_abs_rs, p_abs_rs, n_abs = partial_corr(np.abs(rs[regime_mask]), frv[regime_mask], control[regime_mask])

        print(f"    {regime_name} (N={n_rs}):")
        print(f"      RS → FRV:   partial r = {r_rs:+.4f}, p = {p_rs:.4f}")
        print(f"      RK → FRV:   partial r = {r_rk:+.4f}, p = {p_rk:.4f}")
        print(f"      |RS| → FRV: partial r = {r_abs_rs:+.4f}, p = {p_abs_rs:.4f}")

        regime_results[regime_name] = {
            "RS_partial_r": float(r_rs),
            "RS_p": float(p_rs),
            "RK_partial_r": float(r_rk),
            "RK_p": float(p_rk),
            "absRS_partial_r": float(r_abs_rs),
            "absRS_p": float(p_abs_rs),
            "n_obs": int(n_rs),
        }

    asset_results["regime_analysis"] = regime_results

    # ========================================================
    # Part E: Incremental R² — does RS/RK add to VIX+RV model?
    # ========================================================
    print(f"\n  --- Part E: Incremental R² (RS/RK beyond VIX + RV) ---")

    # Full valid mask
    full_mask = (np.isfinite(rs) & np.isfinite(rk) & np.isfinite(rv) &
                 np.isfinite(frv) & np.isfinite(control))

    if np.sum(full_mask) > 200:
        y = frv[full_mask]
        x_base = np.column_stack([
            control[full_mask],
            rv[full_mask],
            np.ones(np.sum(full_mask))
        ])
        x_full = np.column_stack([
            control[full_mask],
            rv[full_mask],
            rs[full_mask],
            rk[full_mask],
            np.ones(np.sum(full_mask))
        ])
        x_full_nonlin = np.column_stack([
            control[full_mask],
            rv[full_mask],
            rs[full_mask],
            rk[full_mask],
            np.abs(rs[full_mask]),
            rs[full_mask]**2,
            np.ones(np.sum(full_mask))
        ])

        # Base model R²
        beta_base = np.linalg.lstsq(x_base, y, rcond=None)[0]
        y_hat_base = x_base @ beta_base
        ss_res_base = np.sum((y - y_hat_base)**2)
        ss_tot = np.sum((y - np.mean(y))**2)
        r2_base = 1 - ss_res_base / ss_tot

        # Full model R² (linear RS + RK)
        beta_full = np.linalg.lstsq(x_full, y, rcond=None)[0]
        y_hat_full = x_full @ beta_full
        ss_res_full = np.sum((y - y_hat_full)**2)
        r2_full = 1 - ss_res_full / ss_tot

        # Full model R² (nonlinear RS transforms)
        beta_nonlin = np.linalg.lstsq(x_full_nonlin, y, rcond=None)[0]
        y_hat_nonlin = x_full_nonlin @ beta_nonlin
        ss_res_nonlin = np.sum((y - y_hat_nonlin)**2)
        r2_nonlin = 1 - ss_res_nonlin / ss_tot

        # F-test for incremental R²
        n_full = np.sum(full_mask)
        k_base = x_base.shape[1]
        k_full = x_full.shape[1]
        k_nonlin = x_full_nonlin.shape[1]

        f_stat = ((ss_res_base - ss_res_full) / (k_full - k_base)) / (ss_res_full / (n_full - k_full))
        f_p = 1 - stats.f.cdf(f_stat, k_full - k_base, n_full - k_full)

        f_stat_nl = ((ss_res_base - ss_res_nonlin) / (k_nonlin - k_base)) / (ss_res_nonlin / (n_full - k_nonlin))
        f_p_nl = 1 - stats.f.cdf(f_stat_nl, k_nonlin - k_base, n_full - k_nonlin)

        incr_r2 = r2_full - r2_base
        incr_r2_nonlin = r2_nonlin - r2_base

        print(f"    Base model ({control_name} + RV):     R² = {r2_base:.4f}")
        print(f"    + RS + RK (linear):              R² = {r2_full:.4f}  (ΔR² = {incr_r2:+.4f}, F = {f_stat:.2f}, p = {f_p:.4f})")
        print(f"    + RS + RK + |RS| + RS² (nonlin): R² = {r2_nonlin:.4f}  (ΔR² = {incr_r2_nonlin:+.4f}, F = {f_stat_nl:.2f}, p = {f_p_nl:.4f})")

        # RS coefficient sign and significance
        print(f"\n    Coefficient analysis (full linear model):")
        coef_names = [control_name, "RV_t", "RS_t", "RK_t", "const"]
        for cn, b in zip(coef_names, beta_full):
            print(f"      {cn:10s}: {b:+.6f}")

        asset_results["incremental_r2"] = {
            "r2_base": float(r2_base),
            "r2_with_moments": float(r2_full),
            "r2_with_nonlinear": float(r2_nonlin),
            "delta_r2_linear": float(incr_r2),
            "delta_r2_nonlinear": float(incr_r2_nonlin),
            "f_stat_linear": float(f_stat),
            "f_p_linear": float(f_p),
            "f_stat_nonlinear": float(f_stat_nl),
            "f_p_nonlinear": float(f_p_nl),
            "n_obs": int(n_full),
            "coefficients": {cn: float(b) for cn, b in zip(coef_names, beta_full)},
        }

    # ========================================================
    # Part F: Granger causality (VAR-style) — RS → RV?
    # ========================================================
    print(f"\n  --- Part F: Granger-style test (lagged RS/RK → FRV) ---")

    # Multiple lags: does RS at lag 1, 5, 10, 22 predict future vol?
    granger_results = {}
    for lag in [1, 5, 10, 22]:
        # Create lagged predictor
        rs_lagged = np.full(n, np.nan)
        rk_lagged = np.full(n, np.nan)
        rs_lagged[lag:] = rs[:-lag]
        rk_lagged[lag:] = rk[:-lag]

        # Partial correlation at each lag
        r_rs_lag, p_rs_lag, n_lag = partial_corr(rs_lagged, frv, control)
        r_rk_lag, p_rk_lag, _ = partial_corr(rk_lagged, frv, control)

        print(f"    Lag {lag:2d}d: RS→FRV partial r = {r_rs_lag:+.4f} (p={p_rs_lag:.4f}), "
              f"RK→FRV partial r = {r_rk_lag:+.4f} (p={p_rk_lag:.4f}), N={n_lag}")

        granger_results[f"lag_{lag}"] = {
            "RS_partial_r": float(r_rs_lag) if np.isfinite(r_rs_lag) else None,
            "RS_p": float(p_rs_lag) if np.isfinite(p_rs_lag) else None,
            "RK_partial_r": float(r_rk_lag) if np.isfinite(r_rk_lag) else None,
            "RK_p": float(p_rk_lag) if np.isfinite(p_rk_lag) else None,
        }

    asset_results["granger_lags"] = granger_results

    results_summary[asset] = asset_results


# ============================================================
# CROSS-ASSET COMPARISON
# ============================================================
print("\n" + "=" * 80)
print("CROSS-ASSET COMPARISON")
print("=" * 80)

print(f"\n{'Asset':<10} {'RS→FRV':>10} {'p':>8} {'|RS|→FRV':>10} {'p':>8} {'RK→FRV':>10} {'p':>8} {'ΔR²(lin)':>10} {'F_p':>8}")
print("-" * 86)

for asset, res in results_summary.items():
    pc = res.get("partial_correlations", {})
    rs_res = pc.get("RS → FRV", {})
    abs_rs_res = pc.get("|RS| → FRV", {})
    rk_res = pc.get("RK → FRV", {})
    incr = res.get("incremental_r2", {})

    r_rs = rs_res.get("partial_r", np.nan) or np.nan
    p_rs = rs_res.get("p_value", np.nan) or np.nan
    r_abs = abs_rs_res.get("partial_r", np.nan) or np.nan
    p_abs = abs_rs_res.get("p_value", np.nan) or np.nan
    r_rk = rk_res.get("partial_r", np.nan) or np.nan
    p_rk = rk_res.get("p_value", np.nan) or np.nan
    dr2 = incr.get("delta_r2_linear", np.nan) or np.nan
    fp = incr.get("f_p_linear", np.nan) or np.nan

    print(f"{asset:<10} {r_rs:>+10.4f} {p_rs:>8.4f} {r_abs:>+10.4f} {p_abs:>8.4f} "
          f"{r_rk:>+10.4f} {p_rk:>8.4f} {dr2:>+10.4f} {fp:>8.4f}")


# ============================================================
# FINAL VERDICT
# ============================================================
print("\n" + "=" * 80)
print("K396 FINAL ASSESSMENT")
print("=" * 80)

# Count significant results
sig_count = 0
total_tests = 0
harvey_pass = 0

for asset, res in results_summary.items():
    pc = res.get("partial_correlations", {})
    for test_name, test_res in pc.items():
        total_tests += 1
        if test_res.get("p_value") is not None and test_res["p_value"] < 0.05:
            sig_count += 1
        if test_res.get("harvey_pass", False):
            harvey_pass += 1

print(f"\n  Total partial correlation tests: {total_tests}")
print(f"  Significant at p<0.05: {sig_count} ({sig_count/total_tests*100:.1f}%)")
print(f"  Pass Harvey t>3.0: {harvey_pass} ({harvey_pass/total_tests*100:.1f}%)")

# Check if any OOS R² is positive
any_oos_positive = False
for asset, res in results_summary.items():
    oos = res.get("oos_r2", {})
    for test_name in ["RS", "|RS|", "RK", "|RK|"]:
        r2 = oos.get(test_name, {}).get("oos_r2")
        if r2 is not None and r2 > 0:
            any_oos_positive = True
            print(f"  Positive OOS R²: {asset} {test_name} = {r2:+.4f}")

if not any_oos_positive:
    print("  No moment predictor has positive OOS R²")

# Incremental R² summary
print("\n  Incremental R² (moments beyond VIX+RV):")
for asset, res in results_summary.items():
    incr = res.get("incremental_r2", {})
    dr2 = incr.get("delta_r2_linear")
    fp = incr.get("f_p_linear")
    if dr2 is not None:
        sig_str = "***" if fp < 0.001 else ("**" if fp < 0.01 else ("*" if fp < 0.05 else "NS"))
        print(f"    {asset}: ΔR² = {dr2:+.4f} (F-test p = {fp:.4f}) {sig_str}")

# Key conclusions
print("\n  KEY CONCLUSIONS:")
conclusions = []

# Check leverage effect in skewness
for asset, res in results_summary.items():
    rs_mean = res.get("rs_mean", 0)
    if rs_mean < -0.3:
        conclusions.append(f"  - {asset}: Negative RS (mean={rs_mean:.3f}) → leverage effect in skewness")
    elif rs_mean > 0.3:
        conclusions.append(f"  - {asset}: Positive RS (mean={rs_mean:.3f}) → right-skewed returns")
    else:
        conclusions.append(f"  - {asset}: Near-zero RS (mean={rs_mean:.3f}) → symmetric returns")

# Check if any moment predictor is useful
any_useful = False
for asset, res in results_summary.items():
    incr = res.get("incremental_r2", {})
    fp = incr.get("f_p_linear")
    if fp is not None and fp < 0.05:
        any_useful = True
        conclusions.append(f"  - {asset}: Higher moments add significant information (F-test p={fp:.4f})")

if not any_useful:
    conclusions.append("  - NO asset shows significant incremental predictive power from RS/RK")
    conclusions.append("  - This CONFIRMS VIX sufficient statistic finding (21 prior confirmations)")
    conclusions.append("  - Higher moments do NOT break the vol forecasting ceiling")

for c in conclusions:
    print(c)

# Limitations
print("\n  LIMITATIONS:")
print("  - 22d rolling window for moments → smoothing effect")
print("  - Overlapping observations (22d overlap) → autocorrelation in errors")
print("  - BTC uses RV as control (no VIX equivalent)")
print("  - In-sample partial r may be inflated vs OOS performance")
print("  - Linear framework may miss nonlinear interactions (partially addressed with |RS|, RS²)")

# ============================================================
# SAVE RESULTS
# ============================================================
output_path = PROJECT_ROOT / "experiments" / "k396_higher_moments_results.json"
with open(output_path, "w") as f:
    json.dump(results_summary, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

print("\n" + "=" * 80)
print("K396 COMPLETE")
print("=" * 80)
