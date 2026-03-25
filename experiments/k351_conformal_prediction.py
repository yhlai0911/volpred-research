"""
K351: Conformal Prediction for Volatility — Distribution-Free Uncertainty Quantification
========================================================================================
[提出: Claude, 執行: Claude]

COMPLETELY NEW METHODOLOGY: Zero mentions of "conformal" in 1191 knowledge entries.

Research Question:
  1. Can split-conformal prediction provide valid coverage for σ² forecasts?
  2. How do conformal PIs compare to Normal/Historical simulation PIs?
  3. Does Adaptive Conformal Inference (ACI) handle regime changes better?
  4. KEY: narrow PI + correct coverage = best. Wide PI = uninformative.

Related:
  - K350: Heston = EWMA from daily (models converge)
  - K188: QLIKE ceiling in data
  - K168: GARCH Vol-of-Vol — VoV measures model uncertainty

Data: SPY daily from yfinance. 2005-2024. REAL DATA ONLY.

Methodology:
  1. Split-conformal PI for σ² at α = 0.05, 0.10, 0.20
  2. Rolling: train GJR-GARCH w=2000 → calibrate conformal on next 252d → predict
  3. Compare PI width: conformal vs Normal(±z*σ) vs Historical simulation
  4. Adaptive Conformal Inference (ACI): width adjusts based on recent coverage
  5. Metrics: coverage probability AND average PI width

Output: experiments/k351_conformal_results.json
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime
import json
from pathlib import Path

RESULTS_PATH = Path(__file__).resolve().parent / "k351_conformal_results.json"

# ==================================================================
# CONFIG
# ==================================================================
WINDOW = 2000         # GARCH training window
CAL_SIZE = 252        # Calibration set size (1 year)
ALPHA_LEVELS = [0.05, 0.10, 0.20]  # Nominal miscoverage rates
ACI_GAMMA = 0.005     # ACI learning rate (Gibbs & Candes 2021)

DATA_START = "2000-01-01"
DATA_END = "2025-01-01"

print("=" * 80)
print("K351: CONFORMAL PREDICTION FOR VOLATILITY")
print("         Distribution-Free Uncertainty Quantification")
print("=" * 80)
print(f"  GARCH window: {WINDOW}")
print(f"  Calibration size: {CAL_SIZE}")
print(f"  Alpha levels: {ALPHA_LEVELS}")
print(f"  ACI gamma: {ACI_GAMMA}")

# ==================================================================
# 1. DOWNLOAD DATA
# ==================================================================
print("\n[1/7] Downloading SPY data...")

spy_raw = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)

if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)

data = pd.DataFrame()
data["close"] = spy_raw["Close"]
data["returns"] = np.log(data["close"] / data["close"].shift(1))
data = data.dropna()

# Realized variance proxy: squared return
data["rv"] = data["returns"] ** 2

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")

# ==================================================================
# 2. ROLLING GJR-GARCH FORECASTS
# ==================================================================
print("\n[2/7] Computing rolling GJR-GARCH(1,1,1) forecasts...")

# We need: WINDOW for training, CAL_SIZE for calibration, then predict
# Minimum start index = WINDOW + CAL_SIZE
min_start = WINDOW + CAL_SIZE

returns_arr = data["returns"].values * 100  # arch expects percentage returns
dates = data.index
rv_arr = data["rv"].values  # in decimal (raw squared return)

n_total = len(returns_arr)
n_forecast = n_total - min_start
print(f"  Forecast period: {n_forecast} days")
print(f"  Forecast start: {dates[min_start].date()}")

# Store forecasts and realized
forecasts = np.full(n_total, np.nan)
forecast_dates = []

# Rolling GARCH
n_fit = 0
n_fail = 0

for t in range(min_start, n_total):
    train_start = t - WINDOW - CAL_SIZE
    train_end = t  # exclusive (predict for t)

    try:
        am = arch_model(
            returns_arr[train_start:train_end],
            vol="GARCH", p=1, o=1, q=1,  # GJR
            mean="Zero", dist="normal"
        )
        res = am.fit(disp="off", show_warning=False)

        # One-step-ahead forecast
        fcast = res.forecast(horizon=1)
        # Convert from percentage variance back to decimal
        sigma2_forecast = fcast.variance.values[-1, 0] / 10000.0

        forecasts[t] = sigma2_forecast
        forecast_dates.append(dates[t])
        n_fit += 1

    except Exception:
        n_fail += 1
        # Fallback: use expanding EWMA
        if t > 0:
            forecasts[t] = np.mean(rv_arr[max(0, t-252):t])
        forecast_dates.append(dates[t])

    if (t - min_start) % 500 == 0:
        print(f"    Progress: {t - min_start}/{n_forecast} "
              f"({100*(t-min_start)/n_forecast:.0f}%)")

print(f"  GARCH fits: {n_fit} success, {n_fail} failures")

# ==================================================================
# 3. SPLIT-CONFORMAL PREDICTION INTERVALS
# ==================================================================
print("\n[3/7] Computing split-conformal prediction intervals...")

# For each test point t:
#   - Calibration set: [t-CAL_SIZE, t) — compute non-conformity scores
#   - Non-conformity score = |RV_i - forecast_i|
#   - PI: forecast_t ± quantile(scores, ceil((n+1)*(1-alpha))/n)

results_conformal = {alpha: {"coverage": [], "widths": [], "lower": [], "upper": []}
                     for alpha in ALPHA_LEVELS}

# Test period starts after first full calibration window
test_start = min_start
test_indices = list(range(test_start, n_total))

for alpha in ALPHA_LEVELS:
    covered = 0
    total = 0
    widths = []

    for t in test_indices:
        if np.isnan(forecasts[t]):
            continue

        # Calibration window: [t-CAL_SIZE, t)
        cal_start = t - CAL_SIZE
        if cal_start < WINDOW:
            continue

        cal_forecasts = forecasts[cal_start:t]
        cal_rv = rv_arr[cal_start:t]

        # Skip if too many NaN
        valid_mask = ~np.isnan(cal_forecasts)
        if np.sum(valid_mask) < 50:
            continue

        cal_f = cal_forecasts[valid_mask]
        cal_r = cal_rv[valid_mask]

        # Non-conformity scores: |RV - forecast|
        scores = np.abs(cal_r - cal_f)

        # Quantile: ceil((n+1)*(1-alpha))/n
        n_cal = len(scores)
        q_level = np.ceil((n_cal + 1) * (1 - alpha)) / n_cal
        q_level = min(q_level, 1.0)

        q_val = np.quantile(scores, q_level)

        # Prediction interval
        lower = max(0, forecasts[t] - q_val)  # variance >= 0
        upper = forecasts[t] + q_val
        width = upper - lower

        # Coverage check
        actual_rv = rv_arr[t]
        is_covered = (actual_rv >= lower) and (actual_rv <= upper)

        covered += int(is_covered)
        total += 1
        widths.append(width)

        results_conformal[alpha]["lower"].append(float(lower))
        results_conformal[alpha]["upper"].append(float(upper))

    emp_coverage = covered / total if total > 0 else 0
    avg_width = np.mean(widths) if widths else 0

    results_conformal[alpha]["coverage"] = float(emp_coverage)
    results_conformal[alpha]["avg_width"] = float(avg_width)
    results_conformal[alpha]["n_test"] = total

    # Annualize width for interpretability
    ann_width_vol = np.sqrt(avg_width * 252) * 100  # in percentage vol points

    target_cov = 1 - alpha
    print(f"  alpha={alpha:.2f} | Target coverage: {target_cov:.0%} | "
          f"Empirical: {emp_coverage:.3f} | "
          f"Avg PI width (ann vol): {ann_width_vol:.1f}% | "
          f"N={total}")

# ==================================================================
# 4. NORMAL ASSUMPTION PI (benchmark)
# ==================================================================
print("\n[4/7] Computing Normal-assumption prediction intervals...")

results_normal = {alpha: {} for alpha in ALPHA_LEVELS}

for alpha in ALPHA_LEVELS:
    z = stats.norm.ppf(1 - alpha / 2)
    covered = 0
    total = 0
    widths = []

    for t in test_indices:
        if np.isnan(forecasts[t]):
            continue
        if t < WINDOW + CAL_SIZE:
            continue

        # Normal PI: forecast ± z * se(forecast)
        # se of variance ~ variance * sqrt(2/df) under normality
        # But we use a simpler approach: compute std of calibration residuals
        cal_start = t - CAL_SIZE
        cal_forecasts = forecasts[cal_start:t]
        cal_rv = rv_arr[cal_start:t]

        valid_mask = ~np.isnan(cal_forecasts)
        if np.sum(valid_mask) < 50:
            continue

        residuals = cal_rv[valid_mask] - cal_forecasts[valid_mask]
        se = np.std(residuals)

        lower = max(0, forecasts[t] - z * se)
        upper = forecasts[t] + z * se
        width = upper - lower

        actual_rv = rv_arr[t]
        is_covered = (actual_rv >= lower) and (actual_rv <= upper)

        covered += int(is_covered)
        total += 1
        widths.append(width)

    emp_coverage = covered / total if total > 0 else 0
    avg_width = np.mean(widths) if widths else 0
    ann_width_vol = np.sqrt(avg_width * 252) * 100

    results_normal[alpha]["coverage"] = float(emp_coverage)
    results_normal[alpha]["avg_width"] = float(avg_width)
    results_normal[alpha]["n_test"] = total

    target_cov = 1 - alpha
    print(f"  alpha={alpha:.2f} | Target coverage: {target_cov:.0%} | "
          f"Empirical: {emp_coverage:.3f} | "
          f"Avg PI width (ann vol): {ann_width_vol:.1f}% | "
          f"N={total}")

# ==================================================================
# 5. HISTORICAL SIMULATION PI (benchmark)
# ==================================================================
print("\n[5/7] Computing historical simulation prediction intervals...")

results_hist = {alpha: {} for alpha in ALPHA_LEVELS}

for alpha in ALPHA_LEVELS:
    covered = 0
    total = 0
    widths = []

    for t in test_indices:
        if t < WINDOW + CAL_SIZE:
            continue

        # Use empirical quantiles of past RV directly (no model needed)
        cal_rv = rv_arr[t - CAL_SIZE:t]

        lower = np.quantile(cal_rv, alpha / 2)
        upper = np.quantile(cal_rv, 1 - alpha / 2)
        width = upper - lower

        actual_rv = rv_arr[t]
        is_covered = (actual_rv >= lower) and (actual_rv <= upper)

        covered += int(is_covered)
        total += 1
        widths.append(width)

    emp_coverage = covered / total if total > 0 else 0
    avg_width = np.mean(widths) if widths else 0
    ann_width_vol = np.sqrt(avg_width * 252) * 100

    results_hist[alpha]["coverage"] = float(emp_coverage)
    results_hist[alpha]["avg_width"] = float(avg_width)
    results_hist[alpha]["n_test"] = total

    target_cov = 1 - alpha
    print(f"  alpha={alpha:.2f} | Target coverage: {target_cov:.0%} | "
          f"Empirical: {emp_coverage:.3f} | "
          f"Avg PI width (ann vol): {ann_width_vol:.1f}% | "
          f"N={total}")

# ==================================================================
# 6. ADAPTIVE CONFORMAL INFERENCE (ACI)
# ==================================================================
print("\n[6/7] Computing Adaptive Conformal Inference (ACI)...")
print(f"  Learning rate gamma = {ACI_GAMMA}")

# ACI (Gibbs & Candes 2021): adjusts alpha_t based on recent coverage
# alpha_{t+1} = alpha_t + gamma * (alpha - err_t)
# where err_t = 1 if not covered, 0 if covered

results_aci = {alpha: {} for alpha in ALPHA_LEVELS}

for alpha in ALPHA_LEVELS:
    alpha_t = alpha  # adaptive miscoverage rate
    covered = 0
    total = 0
    widths = []
    alpha_history = []
    coverage_history = []  # rolling coverage

    for t in test_indices:
        if np.isnan(forecasts[t]):
            continue
        if t < WINDOW + CAL_SIZE:
            continue

        # Calibration
        cal_start = t - CAL_SIZE
        cal_forecasts = forecasts[cal_start:t]
        cal_rv = rv_arr[cal_start:t]

        valid_mask = ~np.isnan(cal_forecasts)
        if np.sum(valid_mask) < 50:
            continue

        cal_f = cal_forecasts[valid_mask]
        cal_r = cal_rv[valid_mask]

        scores = np.abs(cal_r - cal_f)
        n_cal = len(scores)

        # Use current adaptive alpha
        alpha_use = max(0.001, min(alpha_t, 0.999))  # clip
        q_level = np.ceil((n_cal + 1) * (1 - alpha_use)) / n_cal
        q_level = min(q_level, 1.0)

        q_val = np.quantile(scores, q_level)

        lower = max(0, forecasts[t] - q_val)
        upper = forecasts[t] + q_val
        width = upper - lower

        actual_rv = rv_arr[t]
        is_covered = (actual_rv >= lower) and (actual_rv <= upper)
        err_t = 0 if is_covered else 1

        # ACI update
        alpha_t = alpha_t + ACI_GAMMA * (alpha - err_t)

        covered += int(is_covered)
        total += 1
        widths.append(width)
        alpha_history.append(float(alpha_t))

    emp_coverage = covered / total if total > 0 else 0
    avg_width = np.mean(widths) if widths else 0
    ann_width_vol = np.sqrt(avg_width * 252) * 100

    # Track alpha drift
    alpha_std = np.std(alpha_history) if alpha_history else 0
    alpha_range = (min(alpha_history), max(alpha_history)) if alpha_history else (0, 0)

    results_aci[alpha]["coverage"] = float(emp_coverage)
    results_aci[alpha]["avg_width"] = float(avg_width)
    results_aci[alpha]["n_test"] = total
    results_aci[alpha]["alpha_std"] = float(alpha_std)
    results_aci[alpha]["alpha_range"] = [float(alpha_range[0]), float(alpha_range[1])]

    target_cov = 1 - alpha
    print(f"  alpha={alpha:.2f} | Target: {target_cov:.0%} | "
          f"Empirical: {emp_coverage:.3f} | "
          f"PI width (ann vol): {ann_width_vol:.1f}% | "
          f"alpha_t range: [{alpha_range[0]:.4f}, {alpha_range[1]:.4f}]")

# ==================================================================
# 7. REGIME-CONDITIONAL ANALYSIS
# ==================================================================
print("\n[7/7] Regime-conditional coverage analysis...")

# Split test period by VIX regime (proxy: realized vol quintile)
# We'll use rolling 22d realized vol as regime proxy
rolling_rv_22d = pd.Series(rv_arr).rolling(22).mean().values
rv_quintiles = np.nanpercentile(rolling_rv_22d[test_start:n_total], [20, 40, 60, 80])

regime_labels = ["Low vol (Q1)", "Mid-low (Q2)", "Mid (Q3)", "Mid-high (Q4)", "High vol (Q5)"]

for alpha in [0.10]:  # Focus on 90% PI
    print(f"\n  90% PI coverage by volatility regime:")
    print(f"  {'Regime':<20s} {'Conformal':>12s} {'Normal':>12s} {'Hist Sim':>12s} {'ACI':>12s}")
    print(f"  {'-'*68}")

    for method_name, method_label in [("conformal", "Conformal"), ("normal", "Normal"),
                                       ("hist", "Hist Sim"), ("aci", "ACI")]:
        pass  # Will compute below

    # Re-compute per regime for all methods
    regime_results = {}

    for method_name in ["conformal", "normal", "hist", "aci"]:
        regime_results[method_name] = {r: {"covered": 0, "total": 0} for r in range(5)}

    alpha = 0.10
    alpha_t_aci = alpha

    for t_idx, t in enumerate(test_indices):
        if np.isnan(forecasts[t]):
            continue
        if t < WINDOW + CAL_SIZE:
            continue

        # Determine regime
        rv_22d = rolling_rv_22d[t] if not np.isnan(rolling_rv_22d[t]) else 0
        regime = np.searchsorted(rv_quintiles, rv_22d)
        regime = min(regime, 4)

        actual_rv = rv_arr[t]

        # --- Conformal ---
        cal_start = t - CAL_SIZE
        cal_forecasts = forecasts[cal_start:t]
        cal_rv_window = rv_arr[cal_start:t]
        valid_mask = ~np.isnan(cal_forecasts)

        if np.sum(valid_mask) >= 50:
            scores = np.abs(cal_rv_window[valid_mask] - cal_forecasts[valid_mask])
            n_cal = len(scores)
            q_level = min(np.ceil((n_cal + 1) * 0.9) / n_cal, 1.0)
            q_val = np.quantile(scores, q_level)

            lower_c = max(0, forecasts[t] - q_val)
            upper_c = forecasts[t] + q_val

            is_covered_c = (actual_rv >= lower_c) and (actual_rv <= upper_c)
            regime_results["conformal"][regime]["covered"] += int(is_covered_c)
            regime_results["conformal"][regime]["total"] += 1

            # --- Normal ---
            residuals = cal_rv_window[valid_mask] - cal_forecasts[valid_mask]
            se = np.std(residuals)
            z = stats.norm.ppf(0.95)
            lower_n = max(0, forecasts[t] - z * se)
            upper_n = forecasts[t] + z * se

            is_covered_n = (actual_rv >= lower_n) and (actual_rv <= upper_n)
            regime_results["normal"][regime]["covered"] += int(is_covered_n)
            regime_results["normal"][regime]["total"] += 1

            # --- ACI ---
            alpha_use = max(0.001, min(alpha_t_aci, 0.999))
            q_level_aci = min(np.ceil((n_cal + 1) * (1 - alpha_use)) / n_cal, 1.0)
            q_val_aci = np.quantile(scores, q_level_aci)

            lower_a = max(0, forecasts[t] - q_val_aci)
            upper_a = forecasts[t] + q_val_aci

            is_covered_a = (actual_rv >= lower_a) and (actual_rv <= upper_a)
            regime_results["aci"][regime]["covered"] += int(is_covered_a)
            regime_results["aci"][regime]["total"] += 1

            err_t = 0 if is_covered_a else 1
            alpha_t_aci = alpha_t_aci + ACI_GAMMA * (alpha - err_t)

        # --- Historical Simulation ---
        cal_rv_hist = rv_arr[t - CAL_SIZE:t]
        lower_h = np.quantile(cal_rv_hist, 0.05)
        upper_h = np.quantile(cal_rv_hist, 0.95)

        is_covered_h = (actual_rv >= lower_h) and (actual_rv <= upper_h)
        regime_results["hist"][regime]["covered"] += int(is_covered_h)
        regime_results["hist"][regime]["total"] += 1

    # Print regime table
    for r in range(5):
        row = f"  {regime_labels[r]:<20s}"
        for method in ["conformal", "normal", "hist", "aci"]:
            d = regime_results[method][r]
            if d["total"] > 0:
                cov = d["covered"] / d["total"]
                row += f" {cov:>11.1%} "
            else:
                row += f" {'N/A':>11s} "
        print(row)

    # Coverage deviation from 90% target
    print(f"\n  Coverage deviation from 90% target (ideal = 0.0%):")
    for method in ["conformal", "normal", "hist", "aci"]:
        deviations = []
        for r in range(5):
            d = regime_results[method][r]
            if d["total"] > 0:
                dev = abs(d["covered"] / d["total"] - 0.90)
                deviations.append(dev)
        avg_dev = np.mean(deviations) if deviations else 0
        max_dev = max(deviations) if deviations else 0
        print(f"    {method:<12s}: avg |dev| = {avg_dev:.3f}, max |dev| = {max_dev:.3f}")

# ==================================================================
# 8. EFFICIENCY ANALYSIS: WIDTH COMPARISON
# ==================================================================
print("\n" + "=" * 80)
print("SUMMARY: PI Width Efficiency Comparison")
print("=" * 80)

print(f"\n{'Method':<20s} {'alpha':>6s} {'Coverage':>10s} {'Target':>8s} {'OK?':>5s} "
      f"{'Width(ann vol%)':>16s} {'Relative':>10s}")
print("-" * 80)

# Collect all results for comparison
all_results = {}

for alpha in ALPHA_LEVELS:
    target = 1 - alpha

    methods = {
        "Conformal": results_conformal[alpha],
        "Normal": results_normal[alpha],
        "Hist Simulation": results_hist[alpha],
        "ACI": results_aci[alpha],
    }

    # Find conformal width as reference
    ref_width = results_conformal[alpha].get("avg_width", 1e-10)

    for name, res in methods.items():
        cov = res.get("coverage", 0)
        width = res.get("avg_width", 0)
        ann_vol = np.sqrt(width * 252) * 100

        # Coverage check: within 2% of target
        ok = "YES" if abs(cov - target) < 0.02 else "NO"

        relative = width / ref_width if ref_width > 0 else float("inf")

        print(f"{name:<20s} {alpha:>6.2f} {cov:>10.3f} {target:>8.0%} {ok:>5s} "
              f"{ann_vol:>14.1f}% {relative:>10.2f}x")

        key = f"{name}_{alpha}"
        all_results[key] = {
            "method": name,
            "alpha": alpha,
            "target_coverage": float(target),
            "empirical_coverage": float(cov),
            "avg_width": float(width),
            "ann_vol_width_pct": float(ann_vol),
            "coverage_ok": ok == "YES",
            "relative_to_conformal": float(relative),
            "n_test": res.get("n_test", 0),
        }

# ==================================================================
# 9. STATISTICAL TESTS
# ==================================================================
print("\n" + "=" * 80)
print("STATISTICAL TESTS")
print("=" * 80)

# Kupiec-like test for coverage: H0: coverage = target
for alpha in ALPHA_LEVELS:
    target = 1 - alpha
    print(f"\n  Binomial test for alpha={alpha} (target coverage = {target:.0%}):")

    for name, res in [("Conformal", results_conformal[alpha]),
                       ("Normal", results_normal[alpha]),
                       ("Hist Sim", results_hist[alpha]),
                       ("ACI", results_aci[alpha])]:
        n = res.get("n_test", 0)
        k = int(round(res.get("coverage", 0) * n))

        if n > 0:
            # Two-sided binomial test
            p_val = stats.binomtest(k, n, target).pvalue
            print(f"    {name:<16s}: {k}/{n} = {k/n:.3f}, "
                  f"p-value = {p_val:.4f} {'***' if p_val < 0.001 else '**' if p_val < 0.01 else '*' if p_val < 0.05 else 'NS'}")

# ==================================================================
# 10. CONCLUSIONS
# ==================================================================
print("\n" + "=" * 80)
print("CONCLUSIONS")
print("=" * 80)

# Determine best method: valid coverage + narrowest PI
print("\nBest method per alpha (valid coverage + narrowest PI):")
for alpha in ALPHA_LEVELS:
    target = 1 - alpha
    candidates = [
        ("Conformal", results_conformal[alpha]),
        ("Normal", results_normal[alpha]),
        ("Hist Simulation", results_hist[alpha]),
        ("ACI", results_aci[alpha]),
    ]

    # Filter for valid coverage (within 3% of target)
    valid = [(n, r) for n, r in candidates if abs(r.get("coverage", 0) - target) < 0.03]

    if valid:
        best = min(valid, key=lambda x: x[1].get("avg_width", float("inf")))
        ann_vol = np.sqrt(best[1]["avg_width"] * 252) * 100
        print(f"  alpha={alpha:.2f}: {best[0]} (coverage={best[1]['coverage']:.3f}, "
              f"width={ann_vol:.1f}% ann vol)")
    else:
        print(f"  alpha={alpha:.2f}: NO METHOD achieves valid coverage!")
        # Show closest
        closest = min(candidates, key=lambda x: abs(x[1].get("coverage", 0) - target))
        print(f"    Closest: {closest[0]} (coverage={closest[1]['coverage']:.3f})")

# Key findings
print("\nKEY FINDINGS:")

# 1. Conformal coverage guarantee
conf_10 = results_conformal[0.10]
print(f"  1. Conformal 90% PI: empirical coverage = {conf_10['coverage']:.1%} "
      f"(target 90%)")

# 2. Width comparison
conf_w = results_conformal[0.10].get("avg_width", 0)
norm_w = results_normal[0.10].get("avg_width", 0)
hist_w = results_hist[0.10].get("avg_width", 0)
aci_w = results_aci[0.10].get("avg_width", 0)

if conf_w > 0:
    print(f"  2. PI width ratios (vs conformal): "
          f"Normal={norm_w/conf_w:.2f}x, Hist={hist_w/conf_w:.2f}x, ACI={aci_w/conf_w:.2f}x")

# 3. ACI adaptation
aci_10 = results_aci[0.10]
print(f"  3. ACI alpha drift: std={aci_10.get('alpha_std', 0):.4f}, "
      f"range=[{aci_10.get('alpha_range', [0,0])[0]:.4f}, {aci_10.get('alpha_range', [0,0])[1]:.4f}]")

# 4. Regime robustness
print(f"  4. Regime-conditional coverage — see table above")

# ==================================================================
# SAVE RESULTS
# ==================================================================
print("\n" + "=" * 80)
print("Saving results...")

output = {
    "experiment": "K351",
    "title": "Conformal Prediction for Volatility — Distribution-Free Uncertainty Quantification",
    "timestamp": datetime.now().isoformat(),
    "data": {
        "asset": "SPY",
        "source": "yfinance",
        "period": f"{data.index[0].date()} to {data.index[-1].date()}",
        "n_total": int(n_total),
        "n_forecast": int(n_forecast),
    },
    "config": {
        "garch_window": WINDOW,
        "calibration_size": CAL_SIZE,
        "alpha_levels": ALPHA_LEVELS,
        "aci_gamma": ACI_GAMMA,
    },
    "results": {
        "conformal": {str(a): {
            "coverage": results_conformal[a].get("coverage", 0),
            "avg_width": results_conformal[a].get("avg_width", 0),
            "ann_vol_width_pct": float(np.sqrt(results_conformal[a].get("avg_width", 0) * 252) * 100),
            "n_test": results_conformal[a].get("n_test", 0),
        } for a in ALPHA_LEVELS},
        "normal": {str(a): {
            "coverage": results_normal[a].get("coverage", 0),
            "avg_width": results_normal[a].get("avg_width", 0),
            "ann_vol_width_pct": float(np.sqrt(results_normal[a].get("avg_width", 0) * 252) * 100),
            "n_test": results_normal[a].get("n_test", 0),
        } for a in ALPHA_LEVELS},
        "hist_simulation": {str(a): {
            "coverage": results_hist[a].get("coverage", 0),
            "avg_width": results_hist[a].get("avg_width", 0),
            "ann_vol_width_pct": float(np.sqrt(results_hist[a].get("avg_width", 0) * 252) * 100),
            "n_test": results_hist[a].get("n_test", 0),
        } for a in ALPHA_LEVELS},
        "aci": {str(a): {
            "coverage": results_aci[a].get("coverage", 0),
            "avg_width": results_aci[a].get("avg_width", 0),
            "ann_vol_width_pct": float(np.sqrt(results_aci[a].get("avg_width", 0) * 252) * 100),
            "n_test": results_aci[a].get("n_test", 0),
            "alpha_std": results_aci[a].get("alpha_std", 0),
            "alpha_range": results_aci[a].get("alpha_range", [0, 0]),
        } for a in ALPHA_LEVELS},
    },
    "regime_results": {
        method: {
            regime_labels[r]: {
                "coverage": regime_results[method][r]["covered"] / regime_results[method][r]["total"]
                if regime_results[method][r]["total"] > 0 else None,
                "n": regime_results[method][r]["total"]
            }
            for r in range(5)
        }
        for method in ["conformal", "normal", "hist", "aci"]
    },
    "all_comparisons": all_results,
}

with open(RESULTS_PATH, "w") as f:
    json.dump(output, f, indent=2)

print(f"Results saved to {RESULTS_PATH}")
print("\n" + "=" * 80)
print("K351 COMPLETE")
print("=" * 80)
