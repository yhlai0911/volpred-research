"""
K783: GARCH Window Size Sensitivity Analysis
=============================================
Inspired by Feng & Zhang (2025, J. Forecasting) on estimation window effects.

Research Question: Is w=2000 truly optimal for OOS QLIKE? What is the empirically
optimal window size for daily GARCH volatility forecasting on SPY?

Prior Knowledge:
- K-entry: "QLIKE varies <0.5% across 126/252/504" (narrow range tested)
- User insight 2026-03-16: U-shape, w=504 local optimum, w=5000 best
- M1/M4: w<500 has >5% persistence bias, w=2000 near-unbiased
- Expanding window worst (includes irrelevant old regimes)

Design:
- Window sizes: {252, 504, 756, 1000, 1260, 1500, 2000, 2520, 3000, 3780, 5040, ALL}
- Models: GJR-GARCH(1,1), GARCH(1,1), EWMA(0.94)
- OOS: 2023-01-01 ~ 2024-12-31 (~504 days)
- Data: SPY from yfinance, start=2000-01-01
- Metrics: QLIKE, MSE, persistence, param stability, convergence failure rate
- DM test: each window vs w=2000
- Multiprocessing for speed (M1 Max 10 cores)

References:
- Feng & Zhang (2025), "Window size effects on GARCH forecasting", J. Forecasting
- Patton (2011), "Volatility forecast comparison using imperfect volatility proxies", J. Econometrics
- Harvey et al. (2016), "...and the cross-section of expected returns", RFS (t>3.0 threshold)
- Hansen & Lunde (2005), "A forecast comparison of volatility models", J. Applied Econometrics

Data source: yfinance (SPY, 2000-01-01 to 2024-12-31)
"""

import json
import time
import warnings
from datetime import datetime
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================
# Configuration
# ============================================================
ASSET = "SPY"
DATA_START = "2000-01-01"
DATA_END = "2024-12-31"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"

WINDOW_SIZES = [252, 504, 756, 1000, 1260, 1500, 2000, 2520, 3000, 3780, 5040, "ALL"]
EWMA_LAMBDA = 0.94

# Harvey (2016) threshold
HARVEY_T_THRESHOLD = 3.0


# ============================================================
# Data Loading
# ============================================================
def load_data():
    """Load SPY data from yfinance."""
    print(f"Downloading {ASSET} data from {DATA_START} to {DATA_END}...")
    df = yf.download(ASSET, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df["Return"] = df["Close"].pct_change()
    df = df.dropna(subset=["Return"])
    # Scale returns to percentage for arch package
    df["Return_pct"] = df["Return"] * 100
    print(f"Loaded {len(df)} observations ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
    return df


# ============================================================
# GARCH Estimation
# ============================================================
def fit_garch(returns_pct, model_type="GJR"):
    """
    Fit GARCH or GJR-GARCH(1,1) and return 1-step forecast variance (in pct^2).
    Returns: (forecast_var_pct2, persistence, params_dict, converged)
    """
    try:
        if model_type == "GJR":
            am = arch_model(returns_pct, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Zero")
        else:
            am = arch_model(returns_pct, vol="GARCH", p=1, o=0, q=1, dist="normal", mean="Zero")

        res = am.fit(disp="off", show_warning=False, options={"maxiter": 300})

        # Extract parameters
        omega = res.params.get("omega", np.nan)
        alpha = res.params.get("alpha[1]", np.nan)
        beta = res.params.get("beta[1]", np.nan)
        gamma = res.params.get("gamma[1]", 0.0) if model_type == "GJR" else 0.0

        persistence = alpha + beta + gamma / 2.0

        # 1-step ahead forecast
        forecast = res.forecast(horizon=1)
        fvar = forecast.variance.iloc[-1, 0]  # pct^2

        converged = res.convergence_flag == 0

        return fvar, persistence, {"omega": omega, "alpha": alpha, "beta": beta, "gamma": gamma}, converged

    except Exception:
        return np.nan, np.nan, {}, False


def ewma_variance(returns_pct, lam=0.94):
    """
    Compute EWMA variance (RiskMetrics) for the full series.
    Returns the last variance as forecast. No window needed.
    """
    var = np.zeros(len(returns_pct))
    var[0] = returns_pct.iloc[0] ** 2
    for i in range(1, len(returns_pct)):
        var[i] = lam * var[i - 1] + (1 - lam) * returns_pct.iloc[i] ** 2
    return var[-1]


# ============================================================
# Rolling Forecast for One Window Size + Model
# ============================================================
def rolling_forecast_worker(args):
    """
    Worker function for multiprocessing.
    Computes rolling 1-step forecasts for a given window size and model.
    """
    window_size, model_type, returns_pct, oos_indices, all_dates = args

    n_oos = len(oos_indices)
    forecasts = np.full(n_oos, np.nan)
    realized = np.full(n_oos, np.nan)
    persistences = np.full(n_oos, np.nan)
    convergence = np.full(n_oos, False)
    all_params = []

    for i, idx in enumerate(oos_indices):
        # Realized variance: r_t^2 (in pct^2)
        realized[i] = returns_pct.iloc[idx] ** 2

        if model_type == "EWMA":
            # EWMA uses all data up to t-1 (exponential decay, no fixed window)
            train = returns_pct.iloc[:idx]
            if len(train) < 10:
                continue
            forecasts[i] = ewma_variance(train, EWMA_LAMBDA)
            persistences[i] = EWMA_LAMBDA
            convergence[i] = True
            all_params.append({"lambda": EWMA_LAMBDA})
        else:
            # Fixed window
            if window_size == "ALL":
                start_idx = 0
            else:
                start_idx = max(0, idx - window_size)

            train = returns_pct.iloc[start_idx:idx]
            if len(train) < 100:  # minimum for estimation
                continue

            fvar, pers, params, conv = fit_garch(train, model_type)
            forecasts[i] = fvar
            persistences[i] = pers
            convergence[i] = conv
            all_params.append(params)

    # Compute metrics (exclude NaN)
    valid = ~np.isnan(forecasts) & ~np.isnan(realized) & (forecasts > 0) & (realized > 0)

    if valid.sum() < 10:
        return {
            "window": window_size,
            "model": model_type,
            "n_valid": int(valid.sum()),
            "qlike": np.nan,
            "mse": np.nan,
            "mean_persistence": np.nan,
            "std_persistence": np.nan,
            "convergence_rate": np.nan,
            "param_stability": {},
            "forecasts": [],
            "realized": [],
        }

    f = forecasts[valid]
    r = realized[valid]

    # QLIKE = mean(r/f + log(f)) — Patton (2011)
    qlike = np.mean(r / f + np.log(f))

    # MSE = mean((f - r)^2)
    mse = np.mean((f - r) ** 2)

    # Persistence stats
    valid_pers = persistences[~np.isnan(persistences)]
    mean_pers = float(np.mean(valid_pers)) if len(valid_pers) > 0 else np.nan
    std_pers = float(np.std(valid_pers)) if len(valid_pers) > 0 else np.nan

    # Convergence rate
    conv_rate = float(np.mean(convergence[valid])) if valid.sum() > 0 else np.nan

    # Parameter stability (std of each param across rolling estimates)
    param_stab = {}
    if all_params and model_type != "EWMA":
        for key in ["omega", "alpha", "beta", "gamma"]:
            vals = [p.get(key, np.nan) for p in all_params if key in p and not np.isnan(p.get(key, np.nan))]
            if vals:
                param_stab[key] = {"mean": float(np.mean(vals)), "std": float(np.std(vals))}

    return {
        "window": window_size if window_size != "ALL" else "ALL",
        "model": model_type,
        "n_valid": int(valid.sum()),
        "qlike": float(qlike),
        "mse": float(mse),
        "mean_persistence": mean_pers,
        "std_persistence": std_pers,
        "convergence_rate": conv_rate,
        "param_stability": param_stab,
        "forecasts": f.tolist(),
        "realized": r.tolist(),
    }


# ============================================================
# Diebold-Mariano Test
# ============================================================
def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test for equal predictive accuracy.
    loss1, loss2: loss series (e.g., QLIKE contributions).
    Returns: DM statistic, p-value.
    Positive DM = loss1 > loss2 (model 2 better).
    """
    d = np.array(loss1) - np.array(loss2)
    n = len(d)
    if n < 10:
        return np.nan, np.nan

    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=0)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan

    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return float(dm_stat), float(p_value)


# ============================================================
# Main Experiment
# ============================================================
def main():
    start_time = time.time()
    print("=" * 70)
    print("K783: GARCH Window Size Sensitivity Analysis")
    print("=" * 70)

    # Load data
    df = load_data()
    returns_pct = df["Return_pct"]
    all_dates = df.index

    # Descriptive stats
    print(f"\nDescriptive Statistics (full sample):")
    print(f"  Mean return: {returns_pct.mean():.4f}% per day")
    print(f"  Std: {returns_pct.std():.4f}%")
    print(f"  Skewness: {returns_pct.skew():.4f}")
    print(f"  Kurtosis: {returns_pct.kurtosis():.4f}")

    # Identify OOS period
    oos_mask = (all_dates >= OOS_START) & (all_dates <= OOS_END)
    oos_positions = np.where(oos_mask)[0]
    print(f"\nOOS period: {all_dates[oos_positions[0]].strftime('%Y-%m-%d')} to {all_dates[oos_positions[-1]].strftime('%Y-%m-%d')}")
    print(f"OOS observations: {len(oos_positions)}")

    # Check data availability for largest window
    first_oos = oos_positions[0]
    print(f"Data available before first OOS day: {first_oos} observations")
    print(f"Largest fixed window (5040) requires: 5040 observations")
    if first_oos < 5040:
        print(f"  WARNING: Only {first_oos} available, w=5040 will use truncated window for early days")

    # Build task list
    models = ["GJR", "GARCH", "EWMA"]
    tasks = []
    for w in WINDOW_SIZES:
        for m in models:
            if m == "EWMA" and w != 252:
                # EWMA is window-free, only run once
                continue
            tasks.append((w, m, returns_pct, oos_positions, all_dates))

    # Add single EWMA task
    ewma_tasks = [(252, "EWMA", returns_pct, oos_positions, all_dates)]
    # Remove duplicate EWMA from tasks
    tasks = [(w, m, r, o, d) for w, m, r, o, d in tasks if m != "EWMA"]
    tasks.extend(ewma_tasks)

    print(f"\nTotal tasks: {len(tasks)} (window x model combinations)")
    print(f"Using {min(cpu_count(), 10)} cores for parallel execution...")

    # Run with multiprocessing
    n_workers = min(cpu_count(), 10)
    with Pool(n_workers) as pool:
        results = pool.map(rolling_forecast_worker, tasks)

    elapsed = time.time() - start_time
    print(f"\nAll estimations complete in {elapsed:.1f} seconds")

    # ============================================================
    # Organize Results
    # ============================================================

    # Build lookup
    results_lookup = {}
    for r in results:
        results_lookup[(r["window"], r["model"])] = r

    # Print QLIKE matrix
    print("\n" + "=" * 70)
    print("QLIKE Matrix (window x model) — lower is better")
    print("=" * 70)
    header = f"{'Window':>8} | {'GJR':>10} | {'GARCH':>10} | {'EWMA':>10}"
    print(header)
    print("-" * len(header))

    ewma_result = results_lookup.get((252, "EWMA"), {})
    ewma_qlike = ewma_result.get("qlike", np.nan)

    for w in WINDOW_SIZES:
        gjr_q = results_lookup.get((w, "GJR"), {}).get("qlike", np.nan)
        garch_q = results_lookup.get((w, "GARCH"), {}).get("qlike", np.nan)
        ew_q = ewma_qlike if w == WINDOW_SIZES[0] else np.nan
        w_str = str(w) if w != "ALL" else "ALL"
        ew_str = f"{ew_q:.4f}" if not np.isnan(ew_q) else "  ---"
        print(f"{w_str:>8} | {gjr_q:>10.4f} | {garch_q:>10.4f} | {ew_str:>10}")

    # Print Persistence matrix
    print("\n" + "=" * 70)
    print("Mean Persistence (alpha + beta + gamma/2)")
    print("=" * 70)
    header = f"{'Window':>8} | {'GJR':>10} | {'GARCH':>10}"
    print(header)
    print("-" * len(header))
    for w in WINDOW_SIZES:
        gjr_p = results_lookup.get((w, "GJR"), {}).get("mean_persistence", np.nan)
        garch_p = results_lookup.get((w, "GARCH"), {}).get("mean_persistence", np.nan)
        w_str = str(w) if w != "ALL" else "ALL"
        print(f"{w_str:>8} | {gjr_p:>10.4f} | {garch_p:>10.4f}")

    # Print Convergence failure rates
    print("\n" + "=" * 70)
    print("Convergence Rate (% of estimations that converged)")
    print("=" * 70)
    header = f"{'Window':>8} | {'GJR':>10} | {'GARCH':>10}"
    print(header)
    print("-" * len(header))
    for w in WINDOW_SIZES:
        gjr_c = results_lookup.get((w, "GJR"), {}).get("convergence_rate", np.nan)
        garch_c = results_lookup.get((w, "GARCH"), {}).get("convergence_rate", np.nan)
        w_str = str(w) if w != "ALL" else "ALL"
        gjr_str = f"{gjr_c*100:.1f}%" if not np.isnan(gjr_c) else "N/A"
        garch_str = f"{garch_c*100:.1f}%" if not np.isnan(garch_c) else "N/A"
        print(f"{w_str:>8} | {gjr_str:>10} | {garch_str:>10}")

    # Print Parameter stability
    print("\n" + "=" * 70)
    print("Parameter Stability — std(alpha) across rolling estimates")
    print("=" * 70)
    header = f"{'Window':>8} | {'GJR alpha':>12} | {'GARCH alpha':>12} | {'GJR gamma':>12}"
    print(header)
    print("-" * len(header))
    for w in WINDOW_SIZES:
        gjr_ps = results_lookup.get((w, "GJR"), {}).get("param_stability", {})
        garch_ps = results_lookup.get((w, "GARCH"), {}).get("param_stability", {})
        gjr_a_std = gjr_ps.get("alpha", {}).get("std", np.nan)
        garch_a_std = garch_ps.get("alpha", {}).get("std", np.nan)
        gjr_g_std = gjr_ps.get("gamma", {}).get("std", np.nan)
        w_str = str(w) if w != "ALL" else "ALL"
        print(f"{w_str:>8} | {gjr_a_std:>12.6f} | {garch_a_std:>12.6f} | {gjr_g_std:>12.6f}")

    # ============================================================
    # DM Tests: each window vs w=2000 (for GJR)
    # ============================================================
    print("\n" + "=" * 70)
    print("DM Test: each window vs w=2000 (GJR-GARCH, QLIKE loss)")
    print("Harvey (2016) threshold: |t| > 3.0")
    print("=" * 70)

    ref_key = (2000, "GJR")
    ref_result = results_lookup.get(ref_key)
    dm_results = {}

    if ref_result and len(ref_result.get("forecasts", [])) > 0:
        ref_f = np.array(ref_result["forecasts"])
        ref_r = np.array(ref_result["realized"])
        # QLIKE loss per observation
        ref_loss = ref_r / ref_f + np.log(ref_f)

        header = f"{'Window':>8} | {'DM stat':>10} | {'p-value':>10} | {'Significant':>12} | {'Better?':>10}"
        print(header)
        print("-" * len(header))

        for w in WINDOW_SIZES:
            if w == 2000:
                print(f"{'2000':>8} | {'(ref)':>10} | {'(ref)':>10} | {'(ref)':>12} | {'(ref)':>10}")
                continue

            key = (w, "GJR")
            res = results_lookup.get(key)
            if not res or len(res.get("forecasts", [])) == 0:
                continue

            test_f = np.array(res["forecasts"])
            test_r = np.array(res["realized"])

            # Align lengths (may differ due to NaN)
            min_len = min(len(ref_loss), len(test_f))
            test_loss = test_r[:min_len] / test_f[:min_len] + np.log(test_f[:min_len])
            rl = ref_loss[:min_len]

            dm_stat, p_val = dm_test(test_loss, rl, h=1)

            sig = "|t|>3.0" if abs(dm_stat) > HARVEY_T_THRESHOLD else "NOT sig"
            better = "w=" + str(w) if dm_stat < 0 else "w=2000" if dm_stat > 0 else "tie"
            if np.isnan(dm_stat):
                sig = "N/A"
                better = "N/A"

            w_str = str(w) if w != "ALL" else "ALL"
            print(f"{w_str:>8} | {dm_stat:>10.3f} | {p_val:>10.4f} | {sig:>12} | {better:>10}")

            dm_results[str(w)] = {"dm_stat": dm_stat, "p_value": p_val, "significant": abs(dm_stat) > HARVEY_T_THRESHOLD}

    # Also do DM for GARCH
    print("\n" + "=" * 70)
    print("DM Test: each window vs w=2000 (GARCH(1,1), QLIKE loss)")
    print("=" * 70)

    ref_key_g = (2000, "GARCH")
    ref_result_g = results_lookup.get(ref_key_g)
    dm_results_garch = {}

    if ref_result_g and len(ref_result_g.get("forecasts", [])) > 0:
        ref_f_g = np.array(ref_result_g["forecasts"])
        ref_r_g = np.array(ref_result_g["realized"])
        ref_loss_g = ref_r_g / ref_f_g + np.log(ref_f_g)

        header = f"{'Window':>8} | {'DM stat':>10} | {'p-value':>10} | {'Significant':>12} | {'Better?':>10}"
        print(header)
        print("-" * len(header))

        for w in WINDOW_SIZES:
            if w == 2000:
                print(f"{'2000':>8} | {'(ref)':>10} | {'(ref)':>10} | {'(ref)':>12} | {'(ref)':>10}")
                continue

            key = (w, "GARCH")
            res = results_lookup.get(key)
            if not res or len(res.get("forecasts", [])) == 0:
                continue

            test_f_g = np.array(res["forecasts"])
            test_r_g = np.array(res["realized"])

            min_len = min(len(ref_loss_g), len(test_f_g))
            test_loss_g = test_r_g[:min_len] / test_f_g[:min_len] + np.log(test_f_g[:min_len])
            rl_g = ref_loss_g[:min_len]

            dm_stat, p_val = dm_test(test_loss_g, rl_g, h=1)

            sig = "|t|>3.0" if abs(dm_stat) > HARVEY_T_THRESHOLD else "NOT sig"
            better = "w=" + str(w) if dm_stat < 0 else "w=2000" if dm_stat > 0 else "tie"
            if np.isnan(dm_stat):
                sig = "N/A"
                better = "N/A"

            w_str = str(w) if w != "ALL" else "ALL"
            print(f"{w_str:>8} | {dm_stat:>10.3f} | {p_val:>10.4f} | {sig:>12} | {better:>10}")

            dm_results_garch[str(w)] = {"dm_stat": dm_stat, "p_value": p_val, "significant": abs(dm_stat) > HARVEY_T_THRESHOLD}

    # ============================================================
    # Find optimal windows
    # ============================================================
    print("\n" + "=" * 70)
    print("OPTIMAL WINDOW SUMMARY")
    print("=" * 70)

    for model in ["GJR", "GARCH"]:
        best_qlike = np.inf
        best_w = None
        for w in WINDOW_SIZES:
            q = results_lookup.get((w, model), {}).get("qlike", np.inf)
            if q < best_qlike:
                best_qlike = q
                best_w = w
        print(f"  {model}: optimal window = {best_w} (QLIKE = {best_qlike:.4f})")

    # Compare best GARCH window vs EWMA
    print(f"\n  EWMA (lambda=0.94): QLIKE = {ewma_qlike:.4f}")

    # GJR vs GARCH at each window
    print("\n" + "=" * 70)
    print("GJR vs GARCH at each window (QLIKE difference)")
    print("=" * 70)
    header = f"{'Window':>8} | {'GJR QLIKE':>10} | {'GARCH QLIKE':>10} | {'Diff':>10} | {'Better':>10}"
    print(header)
    print("-" * len(header))
    for w in WINDOW_SIZES:
        gjr_q = results_lookup.get((w, "GJR"), {}).get("qlike", np.nan)
        garch_q = results_lookup.get((w, "GARCH"), {}).get("qlike", np.nan)
        diff = gjr_q - garch_q
        better = "GJR" if diff < 0 else "GARCH"
        w_str = str(w) if w != "ALL" else "ALL"
        print(f"{w_str:>8} | {gjr_q:>10.4f} | {garch_q:>10.4f} | {diff:>10.4f} | {better:>10}")

    # ============================================================
    # Save Results
    # ============================================================
    total_time = time.time() - start_time
    print(f"\nTotal execution time: {total_time:.1f} seconds")

    # Build results JSON
    qlike_matrix = {}
    mse_matrix = {}
    persistence_matrix = {}
    convergence_matrix = {}
    param_stability_matrix = {}

    for r in results:
        key = f"{r['model']}_{r['window']}"
        qlike_matrix[key] = r["qlike"]
        mse_matrix[key] = r["mse"]
        persistence_matrix[key] = r["mean_persistence"]
        convergence_matrix[key] = r["convergence_rate"]
        param_stability_matrix[key] = r["param_stability"]

    # Find optimal for each model
    optimal = {}
    for model in ["GJR", "GARCH"]:
        best_q = np.inf
        best_w = None
        w2000_q = np.nan
        for w in WINDOW_SIZES:
            q = results_lookup.get((w, model), {}).get("qlike", np.inf)
            if q < best_q:
                best_q = q
                best_w = w
            if w == 2000:
                w2000_q = q
        optimal[model] = {
            "optimal_window": best_w,
            "optimal_qlike": best_q,
            "w2000_qlike": w2000_q,
            "improvement_vs_w2000_pct": float((w2000_q - best_q) / abs(w2000_q) * 100) if not np.isnan(w2000_q) else np.nan,
        }

    # Summary conclusion
    gjr_opt = optimal["GJR"]["optimal_window"]
    garch_opt = optimal["GARCH"]["optimal_window"]
    gjr_opt_q = optimal["GJR"]["optimal_qlike"]
    gjr_2000_q = optimal["GJR"]["w2000_qlike"]
    garch_opt_q = optimal["GARCH"]["optimal_qlike"]
    garch_2000_q = optimal["GARCH"]["w2000_qlike"]

    # Check if any DM test shows w=2000 is significantly worse
    any_significant_gjr = any(v.get("significant", False) and v.get("dm_stat", 0) > 0 for v in dm_results.values())
    any_significant_garch = any(v.get("significant", False) and v.get("dm_stat", 0) > 0 for v in dm_results_garch.values())

    summary = {
        "is_w2000_optimal_gjr": gjr_opt == 2000,
        "is_w2000_optimal_garch": garch_opt == 2000,
        "gjr_optimal_window": gjr_opt,
        "garch_optimal_window": garch_opt,
        "gjr_improvement_vs_w2000": optimal["GJR"]["improvement_vs_w2000_pct"],
        "garch_improvement_vs_w2000": optimal["GARCH"]["improvement_vs_w2000_pct"],
        "any_window_significantly_beats_w2000_gjr_t3": any_significant_gjr,
        "any_window_significantly_beats_w2000_garch_t3": any_significant_garch,
        "ewma_qlike": ewma_qlike,
        "ewma_vs_best_gjr": f"EWMA {ewma_qlike:.4f} vs GJR-best {gjr_opt_q:.4f} (diff {ewma_qlike - gjr_opt_q:.4f})",
    }

    print("\n" + "=" * 70)
    print("FINAL CONCLUSIONS")
    print("=" * 70)
    print(f"  GJR optimal window: {gjr_opt} (QLIKE={gjr_opt_q:.4f})")
    print(f"  GJR w=2000 QLIKE: {gjr_2000_q:.4f}")
    print(f"  GJR improvement: {optimal['GJR']['improvement_vs_w2000_pct']:.2f}%")
    print(f"  Any window significantly beats w=2000 (GJR, t>3.0)? {any_significant_gjr}")
    print(f"  GARCH optimal window: {garch_opt} (QLIKE={garch_opt_q:.4f})")
    print(f"  GARCH w=2000 QLIKE: {garch_2000_q:.4f}")
    print(f"  GARCH improvement: {optimal['GARCH']['improvement_vs_w2000_pct']:.2f}%")
    print(f"  Any window significantly beats w=2000 (GARCH, t>3.0)? {any_significant_garch}")
    print(f"  EWMA (lambda=0.94) QLIKE: {ewma_qlike:.4f}")

    results_json = {
        "experiment_id": "K783",
        "title": "GARCH Window Size Sensitivity Analysis",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance",
        "asset": ASSET,
        "data_period": f"{DATA_START} to {DATA_END}",
        "oos_period": f"{OOS_START} to {OOS_END}",
        "n_oos": int(len(oos_positions)),
        "window_sizes_tested": [str(w) for w in WINDOW_SIZES],
        "models_tested": models,
        "references": [
            "Feng & Zhang (2025), Window size effects on GARCH forecasting, J. Forecasting",
            "Patton (2011), Volatility forecast comparison using imperfect volatility proxies, J. Econometrics",
            "Harvey et al. (2016), ...and the cross-section of expected returns, RFS",
            "Hansen & Lunde (2005), A forecast comparison of volatility models, J. Applied Econometrics",
        ],
        "qlike_matrix": qlike_matrix,
        "mse_matrix": mse_matrix,
        "persistence_matrix": persistence_matrix,
        "convergence_matrix": convergence_matrix,
        "param_stability_matrix": param_stability_matrix,
        "dm_tests_vs_w2000_gjr": dm_results,
        "dm_tests_vs_w2000_garch": dm_results_garch,
        "optimal_per_model": optimal,
        "summary": summary,
        "execution_time_seconds": round(total_time, 1),
        "descriptive_stats": {
            "mean_return_pct": float(returns_pct.mean()),
            "std_return_pct": float(returns_pct.std()),
            "skewness": float(returns_pct.skew()),
            "kurtosis": float(returns_pct.kurtosis()),
            "n_total": int(len(returns_pct)),
        },
    }

    out_path = Path(__file__).parent / "k783_window_sensitivity_results.json"
    with open(out_path, "w") as f:
        json.dump(results_json, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
