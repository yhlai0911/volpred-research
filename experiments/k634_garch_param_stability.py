#!/usr/bin/env python3
"""
K634: GARCH Parameter Stability Analysis
==========================================
[提出: 用戶, 執行: Claude]

Motivation:
  GJR-GARCH uses fixed parameters within each estimation window, but parameters
  (especially gamma = leverage effect) may change over time. K435 found Hillebrand
  persistence inflation (full-sample 0.9704 vs regime-avg 0.8974). This experiment
  systematically quantifies parameter instability and its forecasting impact.

Prior Knowledge:
  - K435: ICSS structural breaks + Hillebrand persistence inflation confirmed
  - K174/K175: Crisis parameter stability — γ and persistence change < 0.01 with w=2000
  - K35: GJR-GARCH baseline for SPY
  - K461: Cross-asset comparison (SPY vs 0050.TW different gamma)

References:
  - Hillebrand (2005) "Neglecting parameter changes in GARCH models" JoE
  - Lamoureux & Lastrapes (1990) "Persistence in variance, structural change, and the GARCH model" JBES
  - Mikosch & Stărică (2004) "Nonstationarities in Financial Time Series" ReStat
  - Hansen & Lunde (2005) "A forecast comparison of volatility models" JoAE
  - Francq & Zakoïan (2019) "GARCH Models" (stability conditions ch.7)

Data: SPY, GLD, 0050.TW from yfinance (2005-01-01 to 2026-03-28)
"""

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.optimize import minimize
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

warnings.filterwarnings("ignore")

START_TIME = time.time()
EXPERIMENT_ID = "K634"
MAIN_REPO = "/Users/yhlai0911/Desktop/volpred-research"

# ============================================================================
# Configuration
# ============================================================================
DATA_START = "2005-01-01"
DATA_END = "2026-03-28"
ANALYSIS_START = "2006-01-01"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
ROLLING_WINDOW = 2000
REFIT_STEP = 21  # monthly
RANDOM_SEED = 42

ASSETS = ["SPY", "GLD", "0050.TW"]

np.random.seed(RANDOM_SEED)


def P(msg):
    """Print with flush for real-time output."""
    print(msg, flush=True)


# ============================================================================
# Data Download
# ============================================================================
def download_data(ticker: str) -> pd.DataFrame:
    P(f"  Downloading {ticker}...")
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()
    df["return"] = np.log(df["Close"] / df["Close"].shift(1))
    df = df.dropna()
    df["rv"] = df["return"] ** 2
    return df


def download_vix() -> pd.Series:
    P("  Downloading VIX...")
    vix = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    return vix["Close"].dropna()


# ============================================================================
# GJR-GARCH(1,1) — using arch library for speed
# ============================================================================
try:
    from arch import arch_model
    HAS_ARCH = True
    P("  Using arch library for GARCH estimation (fast)")
except ImportError:
    HAS_ARCH = False
    P("  arch library not found, using scipy MLE (slower)")


def fit_gjr_garch(returns):
    """Fit GJR-GARCH(1,1). Returns dict with omega, alpha, gamma, beta, persistence."""
    r = np.asarray(returns, dtype=np.float64) * 100  # scale to percentage for arch lib

    if HAS_ARCH:
        try:
            am = arch_model(r, vol='Garch', p=1, o=1, q=1, dist='normal', mean='Zero')
            res = am.fit(disp='off', options={'maxiter': 200})
            if res.convergence_flag != 0:
                return None
            omega = res.params['omega'] / 10000  # back to decimal
            alpha = res.params['alpha[1]']
            gamma = res.params['gamma[1]']
            beta = res.params['beta[1]']
            persistence = alpha + beta + gamma / 2.0
            return {
                "omega": float(omega),
                "alpha": float(alpha),
                "gamma": float(gamma),
                "beta": float(beta),
                "persistence": float(persistence),
                "converged": True,
                "loglik": float(res.loglikelihood),
            }
        except Exception:
            return None
    else:
        return _fit_gjr_scipy(returns)


def _fit_gjr_scipy(returns):
    """Fallback scipy-based estimation."""
    r = np.asarray(returns, dtype=np.float64)
    var_r = np.var(r)
    best_result = None
    best_nll = np.inf

    starts = [
        [var_r * 0.05, 0.05, 0.10, 0.85],
        [var_r * 0.02, 0.03, 0.15, 0.80],
    ]
    bounds = [(1e-10, var_r * 10), (1e-8, 0.5), (0.0, 0.5), (0.3, 0.999)]

    for x0 in starts:
        try:
            result = minimize(
                _gjr_nll, x0, args=(r,), method="L-BFGS-B",
                bounds=bounds, options={"maxiter": 150, "ftol": 1e-10},
            )
            if result.fun < best_nll:
                best_nll = result.fun
                best_result = result
        except Exception:
            continue

    if best_result is None or not best_result.success:
        return None

    omega, alpha, gamma, beta = best_result.x
    return {
        "omega": float(omega),
        "alpha": float(alpha),
        "gamma": float(gamma),
        "beta": float(beta),
        "persistence": float(alpha + beta + gamma / 2.0),
        "converged": True,
        "loglik": float(-best_result.fun),
    }


def _gjr_nll(params, returns):
    """Negative log-likelihood for GJR-GARCH(1,1)."""
    omega, alpha, gamma, beta = params
    T = len(returns)
    sigma2 = np.empty(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        ind = 1.0 if returns[t - 1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t - 1] ** 2 + gamma * ind * returns[t - 1] ** 2 + beta * sigma2[t - 1]
        if sigma2[t] < 1e-12:
            sigma2[t] = 1e-12
    return -(-0.5 * np.sum(np.log(2 * np.pi) + np.log(sigma2) + returns ** 2 / sigma2))


# ============================================================================
# Forecast helpers
# ============================================================================
def gjr_forecast_oos(returns_full, rv_full, param_records, oos_start_idx, oos_end_idx, refit_step):
    """
    Generate OOS forecasts using rolling re-estimated params.
    Uses pre-computed param_records from Part 1 to avoid redundant re-fitting.
    """
    T = len(returns_full)
    forecasts = np.full(T, np.nan)

    # Build a lookup: for each date index, which param set applies?
    # param_records has 'date_idx' — use the most recent before t
    sorted_records = sorted(param_records, key=lambda x: x['date_idx'])
    param_indices = [r['date_idx'] for r in sorted_records]

    prev_sigma2 = np.var(returns_full[:ROLLING_WINDOW])

    for t in range(ROLLING_WINDOW, T):
        # Find the most recent param set estimated at or before t
        idx = np.searchsorted(param_indices, t, side='right') - 1
        if idx < 0:
            continue
        p = sorted_records[idx]

        r_prev = returns_full[t - 1]
        ind = 1.0 if r_prev < 0 else 0.0
        sigma2_t = p['omega'] + p['alpha'] * r_prev ** 2 + p['gamma'] * ind * r_prev ** 2 + p['beta'] * prev_sigma2
        sigma2_t = max(sigma2_t, 1e-12)
        forecasts[t] = sigma2_t
        prev_sigma2 = sigma2_t

    return forecasts


def gjr_forecast_fixed(returns_full, params, start_idx):
    """Generate forecasts using fixed parameters."""
    T = len(returns_full)
    forecasts = np.full(T, np.nan)
    prev_sigma2 = np.var(returns_full[:start_idx])

    for t in range(start_idx, T):
        r_prev = returns_full[t - 1]
        ind = 1.0 if r_prev < 0 else 0.0
        sigma2_t = params['omega'] + params['alpha'] * r_prev ** 2 + params['gamma'] * ind * r_prev ** 2 + params['beta'] * prev_sigma2
        sigma2_t = max(sigma2_t, 1e-12)
        forecasts[t] = sigma2_t
        prev_sigma2 = sigma2_t

    return forecasts


# ============================================================================
# CUSUM test
# ============================================================================
def cusum_test(series):
    n = len(series)
    s = np.asarray(series)
    mean_s = np.mean(s)
    std_s = np.std(s, ddof=1)
    if std_s < 1e-12:
        return 0.0, 1.0
    cumsum = np.cumsum(s - mean_s) / (std_s * np.sqrt(n))
    max_cusum = np.max(np.abs(cumsum))
    if max_cusum > 1.63:
        p_approx = 0.001
    elif max_cusum > 1.36:
        p_approx = 0.03
    elif max_cusum > 1.22:
        p_approx = 0.10
    else:
        p_approx = 0.50
    return float(max_cusum), float(p_approx)


# ============================================================================
# QLIKE
# ============================================================================
def qlike(rv, sigma2):
    mask = (rv > 0) & (sigma2 > 0) & np.isfinite(rv) & np.isfinite(sigma2)
    rv_m, s2_m = rv[mask], sigma2[mask]
    if len(rv_m) == 0:
        return np.nan
    return float(np.mean(rv_m / s2_m - np.log(rv_m / s2_m) - 1))


# ============================================================================
# Main Analysis per Asset
# ============================================================================
def analyze_asset(ticker: str, data: pd.DataFrame, vix_series: pd.Series) -> dict:
    P(f"\n{'='*60}")
    P(f"  Analyzing {ticker}")
    P(f"{'='*60}")

    analysis_data = data.loc[ANALYSIS_START:]
    returns = analysis_data["return"].values
    rv = analysis_data["rv"].values
    dates = analysis_data.index
    n_total = len(returns)

    P(f"  Total observations: {n_total}")
    P(f"  Period: {dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}")

    desc_stats = {
        "n_obs": n_total,
        "mean_return": float(np.mean(returns)),
        "std_return": float(np.std(returns)),
        "skewness": float(stats.skew(returns)),
        "kurtosis": float(stats.kurtosis(returns)),
        "period": f"{dates[0].strftime('%Y-%m-%d')} to {dates[-1].strftime('%Y-%m-%d')}",
    }
    P(f"  Mean: {desc_stats['mean_return']:.6f}, Std: {desc_stats['std_return']:.4f}")
    P(f"  Skew: {desc_stats['skewness']:.3f}, Kurt: {desc_stats['kurtosis']:.3f}")

    # ── Part 1: Rolling parameter estimation ──
    P(f"\n  --- Rolling GJR-GARCH (w={ROLLING_WINDOW}, step={REFIT_STEP}) ---")
    param_records = []
    n_fits = 0
    n_converged = 0

    t = ROLLING_WINDOW
    while t <= n_total:
        window_returns = returns[t - ROLLING_WINDOW: t]
        result = fit_gjr_garch(window_returns)

        if result is not None and result["converged"]:
            record = {
                "date": dates[t - 1].strftime("%Y-%m-%d"),
                "date_idx": t - 1,
                **result,
            }
            param_records.append(record)
            n_converged += 1

        n_fits += 1
        if n_fits % 50 == 0:
            P(f"    ... {n_fits} fits done ({n_converged} converged)")
        t += REFIT_STEP

    P(f"  Total fits: {n_fits}, Converged: {n_converged} ({100*n_converged/max(n_fits,1):.1f}%)")

    if len(param_records) < 10:
        P(f"  WARNING: Too few converged fits ({len(param_records)}), skipping")
        return {"error": "too_few_converged", "n_converged": len(param_records)}

    param_df = pd.DataFrame(param_records)
    param_df["date"] = pd.to_datetime(param_df["date"])
    param_df = param_df.set_index("date")

    # ── Part 2: Stability statistics ──
    P(f"\n  --- Parameter Stability Statistics ---")
    stability_stats = {}
    for p in ["omega", "alpha", "gamma", "beta", "persistence"]:
        vals = param_df[p].values
        mean_v = float(np.mean(vals))
        std_v = float(np.std(vals))
        cv = std_v / mean_v if abs(mean_v) > 1e-12 else np.nan
        stability_stats[p] = {
            "mean": mean_v, "std": std_v, "cv": float(cv),
            "min": float(np.min(vals)), "max": float(np.max(vals)),
            "range": float(np.max(vals) - np.min(vals)),
            "q25": float(np.percentile(vals, 25)),
            "q75": float(np.percentile(vals, 75)),
            "iqr": float(np.percentile(vals, 75) - np.percentile(vals, 25)),
            "n_estimates": len(vals),
        }
        P(f"  {p:12s}: mean={mean_v:.6f}, std={std_v:.6f}, CV={cv:.3f}, "
          f"range=[{np.min(vals):.6f}, {np.max(vals):.6f}]")

    # ── Part 3: CUSUM test ──
    P(f"\n  --- CUSUM Test ---")
    cusum_results = {}
    for p in ["omega", "alpha", "gamma", "beta", "persistence"]:
        stat, pval = cusum_test(param_df[p].values)
        cusum_results[p] = {"statistic": stat, "p_value_approx": pval}
        sig = "***" if pval < 0.01 else ("**" if pval < 0.05 else ("*" if pval < 0.10 else ""))
        P(f"  {p:12s}: CUSUM = {stat:.4f}, p ~ {pval:.3f} {sig}")

    # ── Part 4: Regime dependence ──
    P(f"\n  --- Regime Dependence (VIX) ---")
    vix_aligned = vix_series.reindex(param_df.index, method="ffill")
    high_mask = vix_aligned > 25
    low_mask = vix_aligned < 15
    n_high, n_low = int(high_mask.sum()), int(low_mask.sum())
    n_mid = len(param_df) - n_high - n_low
    P(f"  Low(<15)={n_low}, Mid={n_mid}, High(>25)={n_high}")

    regime_results = {}
    for p in ["omega", "alpha", "gamma", "beta", "persistence"]:
        vals_low = param_df.loc[low_mask, p].values if n_low > 2 else np.array([])
        vals_high = param_df.loc[high_mask, p].values if n_high > 2 else np.array([])
        rr = {
            "low_vix_mean": float(np.mean(vals_low)) if len(vals_low) > 0 else None,
            "high_vix_mean": float(np.mean(vals_high)) if len(vals_high) > 0 else None,
            "low_n": int(len(vals_low)), "high_n": int(len(vals_high)),
        }
        if len(vals_low) > 2 and len(vals_high) > 2:
            t_stat, t_pval = stats.ttest_ind(vals_low, vals_high, equal_var=False)
            rr["t_stat"] = float(t_stat)
            rr["p_value"] = float(t_pval)
            sig = "***" if t_pval < 0.01 else ("**" if t_pval < 0.05 else "")
            P(f"  {p:12s}: Low={rr['low_vix_mean']:.6f} High={rr['high_vix_mean']:.6f} "
              f"t={t_stat:.3f} p={t_pval:.4f} {sig}")
        regime_results[p] = rr

    # ── Part 5: Gamma sign stability ──
    P(f"\n  --- Gamma Sign ---")
    gv = param_df["gamma"].values
    gamma_sign = {
        "n_negative": int(np.sum(gv < 0)),
        "n_zero": int(np.sum(np.abs(gv) < 1e-6)),
        "n_positive": int(np.sum(gv > 0)),
        "pct_positive": float(np.mean(gv > 0) * 100),
        "min_gamma": float(np.min(gv)),
        "max_gamma": float(np.max(gv)),
        "leverage_always_present": int(np.sum(gv < 0)) == 0,
    }
    P(f"  Positive: {gamma_sign['n_positive']}/{len(gv)} ({gamma_sign['pct_positive']:.1f}%)")
    P(f"  Negative: {gamma_sign['n_negative']}, Near-zero: {gamma_sign['n_zero']}")
    P(f"  Range: [{gamma_sign['min_gamma']:.6f}, {gamma_sign['max_gamma']:.6f}]")

    # ── Part 6: Parameter correlations ──
    P(f"\n  --- Parameter Correlations ---")
    param_corr = {}
    for p1, p2 in [("alpha", "gamma"), ("alpha", "beta"), ("gamma", "beta"),
                    ("alpha", "persistence"), ("gamma", "persistence")]:
        corr, pval = stats.pearsonr(param_df[p1].values, param_df[p2].values)
        param_corr[f"{p1}_vs_{p2}"] = {"correlation": float(corr), "p_value": float(pval)}
        sig = "***" if pval < 0.01 else ("**" if pval < 0.05 else "")
        P(f"  corr({p1}, {p2}) = {corr:.4f} (p={pval:.4f}) {sig}")

    # ── Part 7: Persistence stability ──
    P(f"\n  --- Persistence Stability ---")
    pv = param_df["persistence"].values
    persist_stats = {
        "mean": float(np.mean(pv)), "std": float(np.std(pv)),
        "min": float(np.min(pv)), "max": float(np.max(pv)),
        "pct_above_0_99": float(np.mean(pv > 0.99) * 100),
        "pct_above_0_95": float(np.mean(pv > 0.95) * 100),
        "near_igarch_count": int(np.sum(pv > 0.99)),
    }
    P(f"  Persistence: {persist_stats['mean']:.4f} +/- {persist_stats['std']:.4f}")
    P(f"  Range: [{persist_stats['min']:.4f}, {persist_stats['max']:.4f}]")
    P(f"  >0.99: {persist_stats['pct_above_0_99']:.1f}%, >0.95: {persist_stats['pct_above_0_95']:.1f}%")

    # ── Part 8: Forecasting impact ──
    P(f"\n  --- Forecast Impact: Rolling vs Fixed ---")
    oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) < 50:
        P(f"  Not enough OOS data ({len(oos_indices)})")
        forecast_comparison = {"error": "insufficient_oos"}
    else:
        oos_s, oos_e = oos_indices[0], oos_indices[-1]

        # Rolling: reuse Part 1 param_records
        f_rolling = gjr_forecast_oos(returns, rv, param_records, oos_s, oos_e, REFIT_STEP)

        # Fixed: estimate once on pre-OOS data
        fixed_params = fit_gjr_garch(returns[:oos_s])
        if fixed_params and fixed_params["converged"]:
            f_fixed = gjr_forecast_fixed(returns, fixed_params, ROLLING_WINDOW)

            oos_rv = rv[oos_s:oos_e + 1]
            oos_r = f_rolling[oos_s:oos_e + 1]
            oos_f = f_fixed[oos_s:oos_e + 1]

            valid = ~np.isnan(oos_r) & ~np.isnan(oos_f) & (oos_rv > 0) & (oos_r > 0) & (oos_f > 0)
            q_roll = qlike(oos_rv[valid], oos_r[valid])
            q_fix = qlike(oos_rv[valid], oos_f[valid])

            # DM test
            d_r = oos_rv[valid] / oos_r[valid] - np.log(oos_rv[valid] / oos_r[valid]) - 1
            d_f = oos_rv[valid] / oos_f[valid] - np.log(oos_rv[valid] / oos_f[valid]) - 1
            d_diff = d_r - d_f
            n_dm = len(d_diff)
            if n_dm > 30:
                dm_stat = float(np.mean(d_diff) / (np.std(d_diff, ddof=1) / np.sqrt(n_dm)))
                dm_p = float(2 * (1 - stats.norm.cdf(abs(dm_stat))))
            else:
                dm_stat, dm_p = np.nan, np.nan

            improvement = float((q_fix - q_roll) / q_fix * 100) if q_fix > 0 else 0.0

            forecast_comparison = {
                "qlike_rolling": q_roll,
                "qlike_fixed": q_fix,
                "improvement_pct": improvement,
                "dm_stat": dm_stat,
                "dm_p_value": dm_p,
                "oos_n": int(valid.sum()),
                "fixed_params_used": {k: fixed_params[k] for k in ["omega", "alpha", "gamma", "beta", "persistence"]},
                "rolling_better": q_roll < q_fix,
            }
            P(f"  QLIKE rolling: {q_roll:.6f}")
            P(f"  QLIKE fixed:   {q_fix:.6f}")
            P(f"  Improvement:   {improvement:.2f}%")
            P(f"  DM: {dm_stat:.4f}, p={dm_p:.4f}")
            P(f"  Rolling better: {q_roll < q_fix}")
        else:
            forecast_comparison = {"error": "fixed_convergence_failed"}
            P(f"  Fixed estimation failed")

    return {
        "ticker": ticker,
        "descriptive_stats": desc_stats,
        "n_rolling_estimates": len(param_records),
        "convergence_rate": float(n_converged / max(n_fits, 1) * 100),
        "stability_stats": stability_stats,
        "cusum_tests": cusum_results,
        "regime_dependence": regime_results,
        "gamma_sign_stability": gamma_sign,
        "parameter_correlations": param_corr,
        "persistence_stability": persist_stats,
        "forecast_comparison": forecast_comparison,
        "param_time_series": [
            {"date": r["date"], "omega": r["omega"], "alpha": r["alpha"],
             "gamma": r["gamma"], "beta": r["beta"], "persistence": r["persistence"]}
            for r in param_records
        ],
    }


# ============================================================================
# Plotting
# ============================================================================
def plot_param_evolution(results: dict, save_path: str):
    fig, axes = plt.subplots(5, len(results), figsize=(6 * len(results), 14), squeeze=False)
    params = ["omega", "alpha", "gamma", "beta", "persistence"]
    labels = ["omega (intercept)", "alpha (ARCH)", "gamma (leverage)", "beta (GARCH)", "Persistence"]
    colors = {"SPY": "#2563eb", "GLD": "#d97706", "0050.TW": "#059669"}

    for j, (ticker, r) in enumerate(results.items()):
        if "error" in r:
            continue
        ts = r["param_time_series"]
        dates = pd.to_datetime([x["date"] for x in ts])

        for i, (p, label) in enumerate(zip(params, labels)):
            ax = axes[i][j]
            vals = [x[p] for x in ts]
            ax.plot(dates, vals, color=colors.get(ticker, "#6366f1"), lw=0.8, alpha=0.8)
            if len(vals) > 12:
                rm = pd.Series(vals).rolling(12).mean().values
                ax.plot(dates, rm, color="red", lw=1.5, alpha=0.7, label="12-pt MA")
            ax.axhline(np.mean(vals), color="gray", ls="--", lw=0.8, alpha=0.5)
            if j == 0:
                ax.set_ylabel(label, fontsize=10)
            if i == 0:
                ax.set_title(ticker, fontsize=12, fontweight="bold")
            if i == len(params) - 1:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
                ax.xaxis.set_major_locator(mdates.YearLocator(2))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
            else:
                ax.set_xticklabels([])
            ax.grid(True, alpha=0.3)
            ax.tick_params(labelsize=8)
            for cs, ce in [("2008-09-01", "2009-03-31"), ("2020-02-20", "2020-04-30"), ("2022-01-01", "2022-10-31")]:
                ax.axvspan(pd.Timestamp(cs), pd.Timestamp(ce), alpha=0.1, color="red")

    fig.suptitle("K634: GJR-GARCH Parameter Evolution (w=2000, step=21)", fontsize=14, fontweight="bold", y=0.98)
    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    P(f"  Plot saved: {save_path}")


def plot_cross_asset_cv(results: dict, save_path: str):
    params = ["omega", "alpha", "gamma", "beta", "persistence"]
    tickers = [t for t in results if "error" not in results[t]]
    if len(tickers) < 2:
        return

    fig, ax = plt.subplots(figsize=(10, 5))
    x = np.arange(len(params))
    w = 0.8 / len(tickers)
    colors = {"SPY": "#2563eb", "GLD": "#d97706", "0050.TW": "#059669"}

    for i, t in enumerate(tickers):
        cvs = [results[t]["stability_stats"][p]["cv"] for p in params]
        ax.bar(x + i * w, cvs, w, label=t, color=colors.get(t, "#6366f1"), alpha=0.8)

    ax.set_ylabel("Coefficient of Variation")
    ax.set_title("K634: Parameter Instability (CV) by Asset")
    ax.set_xticks(x + w)
    ax.set_xticklabels(["omega", "alpha", "gamma", "beta", "Persistence"])
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.close()
    P(f"  CV plot saved: {save_path}")


# ============================================================================
# Main
# ============================================================================
def main():
    P(f"{'='*60}")
    P(f"  K634: GARCH Parameter Stability Analysis")
    P(f"  Window: {ROLLING_WINDOW}, Step: {REFIT_STEP}, OOS: {OOS_START}~{OOS_END}")
    P(f"{'='*60}")

    P("\n--- Downloading Data ---")
    all_data = {}
    for t in ASSETS:
        all_data[t] = download_data(t)
        P(f"  {t}: {len(all_data[t])} obs")

    vix = download_vix()
    P(f"  VIX: {len(vix)} obs")

    results = {}
    for t in ASSETS:
        t0 = time.time()
        results[t] = analyze_asset(t, all_data[t], vix)
        P(f"  {t} done in {time.time()-t0:.1f}s")

    # Cross-asset comparison
    P(f"\n{'='*60}")
    P(f"  Cross-Asset Comparison")
    P(f"{'='*60}")
    valid = [t for t in ASSETS if "error" not in results[t]]

    cross_asset = {}
    if len(valid) >= 2:
        P(f"\n  {'Param':12s}" + "".join(f"  {t:>10s}" for t in valid) + f"  {'Most Stable':>12s}")
        for p in ["omega", "alpha", "gamma", "beta", "persistence"]:
            cvs = {t: results[t]["stability_stats"][p]["cv"] for t in valid}
            line = f"  {p:12s}" + "".join(f"  {cvs[t]:10.4f}" for t in valid)
            most_stable = min(cvs, key=cvs.get)
            P(line + f"  {most_stable:>12s}")
            cross_asset[p] = {"cvs": {k: float(v) for k, v in cvs.items()}, "most_stable": most_stable}

    # Conclusions
    conclusions = []
    for t in valid:
        r = results[t]
        gs = r["gamma_sign_stability"]
        if gs["leverage_always_present"]:
            conclusions.append(f"{t}: Leverage (gamma>0) always present ({gs['n_positive']}/{gs['n_positive']+gs['n_negative']})")
        else:
            conclusions.append(f"{t}: Leverage reversal! gamma<0 in {gs['n_negative']} estimates")

        cvs = {p: r["stability_stats"][p]["cv"] for p in ["alpha", "gamma", "beta"]}
        conclusions.append(f"{t}: Most stable={min(cvs, key=cvs.get)} (CV={min(cvs.values()):.4f}), "
                          f"Least stable={max(cvs, key=cvs.get)} (CV={max(cvs.values()):.4f})")

        fc = r.get("forecast_comparison", {})
        if "error" not in fc:
            conclusions.append(f"{t}: Rolling {'BETTER' if fc.get('rolling_better') else 'WORSE'} "
                             f"(QLIKE {fc['qlike_rolling']:.6f} vs {fc['qlike_fixed']:.6f}, "
                             f"DM p={fc.get('dm_p_value', 'N/A')})")

    P(f"\n  Conclusions:")
    for c in conclusions:
        P(f"  - {c}")

    # Plots
    exp_dir = Path(MAIN_REPO) / "experiments"
    plot_param_evolution(results, str(exp_dir / "k634_param_evolution.png"))
    plot_cross_asset_cv(results, str(exp_dir / "k634_cross_asset_cv.png"))

    # Save
    elapsed = time.time() - START_TIME
    results_json = {}
    for t in ASSETS:
        r = results[t].copy()
        if "param_time_series" in r and len(r.get("param_time_series", [])) > 10:
            r["param_time_series_sample"] = r["param_time_series"][:5] + r["param_time_series"][-5:]
            r["param_time_series_count"] = len(r["param_time_series"])
            del r["param_time_series"]
        results_json[t] = r

    output = {
        "experiment_id": EXPERIMENT_ID,
        "title": "GARCH Parameter Stability Analysis",
        "description": "Systematic quantification of GJR-GARCH parameter instability and forecasting impact across SPY, GLD, 0050.TW",
        "attribution": "[提出: 用戶, 執行: Claude]",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "rolling_window": ROLLING_WINDOW,
            "refit_step": REFIT_STEP,
            "analysis_start": ANALYSIS_START,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "data_source": "yfinance",
            "assets": ASSETS,
        },
        "references": [
            "Hillebrand (2005) 'Neglecting parameter changes in GARCH models' JoE",
            "Lamoureux & Lastrapes (1990) 'Persistence in variance' JBES",
            "Hansen & Lunde (2005) 'A forecast comparison of volatility models' JoAE",
        ],
        "prior_knowledge": ["K435 (structural breaks + Hillebrand)", "K174/K175 (crisis stability)"],
        "results": results_json,
        "cross_asset_comparison": cross_asset,
        "conclusions": conclusions,
        "elapsed_seconds": elapsed,
    }

    out_path = exp_dir / "k634_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    P(f"\n  Results: {out_path}")
    P(f"  Elapsed: {elapsed:.1f}s")


if __name__ == "__main__":
    main()
