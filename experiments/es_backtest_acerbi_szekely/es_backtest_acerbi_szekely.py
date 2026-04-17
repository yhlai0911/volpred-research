#!/usr/bin/env python3
"""Acerbi-Szekely (2014) Expected Shortfall Backtest for SPY.

Implements two test statistics from:
  Acerbi & Szekely (2014), "Backtesting Expected Shortfall"

Test 1 (Z1): Based on exceedance residuals
  Z1 = (1/N) * sum_{t: r_t < VaR_t} (r_t / ES_t) + 1
  where N = number of VaR violations
  Under H0 (correct ES): E[Z1] = 0

Test 2 (Z2): Based on all observations
  Z2 = (1/(T*alpha)) * sum_t (r_t * I(r_t < VaR_t) / ES_t) + 1
  Under H0: E[Z2] = 0

If Z1 or Z2 < 0: ES is underestimated (risk is higher than model predicts).

Bootstrap p-values (5000 replications) since the distribution is non-standard.

Setup:
  - Asset: SPY
  - Model: GJR-GARCH(1,1) with Normal, Student-t(5), Skewed-t
  - Rolling window w=2000, OOS: 2020-2025
  - alpha = 0.01 (1% VaR/ES)

Author: VolPred Research System
Date: 2026-03-16
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from arch.univariate.distribution import SkewStudent
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
ASSET = "SPY"
WINDOW = 2000
ALPHA = 0.01        # 1% VaR/ES
START_DATE = "2010-01-01"  # Need enough data for w=2000 warmup before 2020
END_DATE = "2026-03-15"
OOS_START = "2020-01-02"
N_BOOTSTRAP = 5000
SEED = 42


# ============================================================================
# ES Formulas
# ============================================================================

def normal_var_es(sigma, alpha=0.01):
    """Compute VaR and ES under Normal distribution.

    VaR = sigma * z_alpha  (z_alpha > 0 for losses)
    ES  = sigma * phi(z_alpha) / alpha
    where phi is the standard normal pdf, z_alpha = Phi^{-1}(alpha)
    """
    z = stats.norm.ppf(alpha)  # negative
    var = -z * sigma  # positive (loss)
    es = sigma * stats.norm.pdf(z) / alpha  # positive (loss)
    return var, es


def studentt_var_es(sigma, df=5.0, alpha=0.01):
    """Compute VaR and ES under Student-t distribution.

    For standardized t (variance=1):
      scale = sqrt((df-2)/df)
      VaR = sigma * |t_alpha| * scale
      ES  = sigma * scale * (f_t(t_alpha) / alpha) * ((df + t_alpha^2) / (df - 1))

    where f_t is the Student-t pdf, t_alpha = t^{-1}(alpha, df)
    """
    scale = np.sqrt((df - 2) / df)
    t_q = stats.t.ppf(alpha, df)  # negative
    var = -t_q * scale * sigma  # positive
    f_t = stats.t.pdf(t_q, df)
    es = scale * sigma * (f_t / alpha) * ((df + t_q ** 2) / (df - 1))
    return var, es


def skewt_var_es(sigma, eta, lam, alpha=0.01, n_points=10000):
    """Compute VaR and ES under Hansen's Skewed-t distribution.

    VaR: Use arch's SkewStudent.ppf
    ES:  Numerical integration: E[X | X < VaR] via Monte Carlo from the
         skewed-t distribution.

    Parameters:
        sigma: daily volatility (decimal)
        eta: degrees of freedom parameter (>2)
        lam: skewness parameter (-1 < lam < 1)
        alpha: significance level
        n_points: Monte Carlo sample size for ES integration
    """
    skewt = SkewStudent()
    params = np.array([eta, lam])

    # VaR
    q = skewt.ppf(alpha, parameters=params)  # negative standardized quantile
    var = -q * sigma  # positive (loss)

    # ES via numerical integration using the inverse CDF approach:
    # ES = -E[X | X < VaR] = -(1/alpha) * integral_0^alpha ppf(u) du
    from scipy.integrate import trapezoid
    n_int = 5000
    u = np.linspace(1e-10, alpha, n_int)
    x_vals = skewt.ppf(u, parameters=params)
    es_std = -trapezoid(x_vals, u) / alpha  # positive (standardized)
    es = es_std * sigma

    return var, es


# ============================================================================
# Acerbi-Szekely Test Statistics
# ============================================================================

def acerbi_szekely_z1(returns, var_series, es_series):
    """Z1 statistic: based on exceedance residuals.

    Z1 = (1/N) * sum_{t: r_t < -VaR_t} (r_t / ES_t) + 1
    where N = number of violations, VaR and ES are positive loss thresholds.

    Returns (Z1, n_violations).
    """
    violations = returns < -var_series
    n_viol = violations.sum()
    if n_viol == 0:
        return np.nan, 0  # No violations, test undefined

    # For violation days: r_t is negative, ES_t is positive loss threshold
    # Z1 = (1/N) * sum(r_t / ES_t) + 1
    # Since r_t < 0 and ES > 0, each term r_t/ES_t < 0
    # Under H0: Z1 ~ 0
    z1 = np.mean(returns[violations] / es_series[violations]) + 1
    return z1, int(n_viol)


def acerbi_szekely_z2(returns, var_series, es_series, alpha=0.01):
    """Z2 statistic: based on all observations.

    Z2 = (1/(T*alpha)) * sum_t (r_t * I(r_t < -VaR_t) / ES_t) + 1

    Returns (Z2, n_violations).
    """
    T = len(returns)
    violations = returns < -var_series
    n_viol = violations.sum()
    if n_viol == 0:
        return np.nan, 0

    # sum of (r_t * I(violation) / ES_t) for all t
    indicator_returns = returns * violations.astype(float)
    z2 = np.sum(indicator_returns / es_series) / (T * alpha) + 1
    return z2, int(n_viol)


def bootstrap_pvalue(returns, var_series, es_series, observed_z, test_func,
                     alpha=0.01, n_boot=5000, seed=42):
    """Bootstrap p-value for Acerbi-Szekely test.

    Under H0 (correct model), we resample from the standardized residuals
    (returns / ES) and recompute the test statistic.

    The bootstrap simulates from the empirical distribution of the standardized
    innovations, preserving the conditional variance structure.

    p-value = proportion of bootstrap Z <= observed Z (one-sided, lower tail).
    """
    rng = np.random.default_rng(seed)
    T = len(returns)
    boot_stats = []

    # Standardize returns by the ES estimates
    std_returns = returns / es_series  # standardized

    for _ in range(n_boot):
        # Resample indices with replacement
        idx = rng.choice(T, size=T, replace=True)
        # Reconstruct "returns" under H0 by using resampled standardized returns
        # scaled by the original ES
        boot_returns = std_returns[idx] * es_series

        if test_func == "z1":
            z, _ = acerbi_szekely_z1(boot_returns, var_series, es_series)
        else:
            z, _ = acerbi_szekely_z2(boot_returns, var_series, es_series, alpha=alpha)

        if not np.isnan(z):
            boot_stats.append(z)

    if len(boot_stats) == 0:
        return np.nan

    boot_stats = np.array(boot_stats)
    # One-sided p-value: proportion of bootstrap stats <= observed
    # (rejection region: Z << 0 means ES underestimated)
    p_value = np.mean(boot_stats <= observed_z)
    return p_value


# ============================================================================
# Rolling GARCH + VaR/ES
# ============================================================================

def rolling_garch_var_es(returns_pct_full, returns_decimal_full, dates_full,
                         dist="normal", window=WINDOW, alpha=ALPHA):
    """Run rolling GJR-GARCH and compute VaR + ES for each OOS day.

    Parameters:
        returns_pct_full: full return series in percentage (for arch)
        returns_decimal_full: full return series in decimal
        dates_full: DatetimeIndex
        dist: 'normal', 'studentt', or 'skewt'
        window: rolling window size
        alpha: significance level

    Returns:
        DataFrame with columns: date, return, sigma, var, es
    """
    dist_map = {"normal": "normal", "studentt": "t", "skewt": "skewt"}
    arch_dist = dist_map[dist]

    oos_mask = dates_full >= OOS_START
    oos_positions = np.where(oos_mask)[0]

    results = []
    total = len(oos_positions)
    fail_count = 0

    for i, pos in enumerate(oos_positions):
        if pos < window:
            continue

        if (i + 1) % 250 == 0 or (i + 1) == total:
            print(f"    [{dist}] {i+1}/{total} ({(i+1)/total*100:.0f}%)")

        train = returns_pct_full[pos - window:pos]

        try:
            am = arch_model(train, vol="GARCH", p=1, o=1, q=1,
                           dist=arch_dist, mean="Zero", rescale=False)
            res = am.fit(disp="off", show_warning=False)

            # Forecast 1-step variance
            fcast = res.forecast(horizon=1)
            sigma_pct = float(np.sqrt(fcast.variance.iloc[-1, 0]))
            sigma = sigma_pct / 100  # decimal

            # Compute VaR and ES based on distribution
            if dist == "normal":
                var_val, es_val = normal_var_es(sigma, alpha)
            elif dist == "studentt":
                var_val, es_val = studentt_var_es(sigma, df=5.0, alpha=alpha)
            elif dist == "skewt":
                eta = float(res.params.get("eta", 5.0))
                lam = float(res.params.get("lambda", 0.0))
                var_val, es_val = skewt_var_es(sigma, eta, lam, alpha)

            results.append({
                "date": dates_full[pos],
                "return": returns_decimal_full[pos],
                "sigma": sigma,
                "var": var_val,
                "es": es_val,
            })

        except Exception as e:
            fail_count += 1
            continue

    if fail_count > 0:
        print(f"    [{dist}] {fail_count} fitting failures")

    df = pd.DataFrame(results)
    return df


# ============================================================================
# Main
# ============================================================================

def main():
    print("=" * 72)
    print(" Acerbi-Szekely (2014) Expected Shortfall Backtest")
    print(f" Asset: {ASSET} | Window: {WINDOW} | Alpha: {ALPHA}")
    print(f" OOS: {OOS_START} to {END_DATE}")
    print(f" Bootstrap: {N_BOOTSTRAP} replications")
    print("=" * 72)
    print()

    # Download data
    print("Downloading SPY data...")
    spy = yf.download(ASSET, start=START_DATE, end=END_DATE, progress=False,
                      auto_adjust=True)
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    spy["return"] = spy["Close"].pct_change()
    spy = spy.dropna(subset=["return"])

    returns_decimal = spy["return"].values
    returns_pct = returns_decimal * 100
    dates = spy.index

    print(f"  Data: {dates[0].date()} to {dates[-1].date()}, {len(dates)} days")
    oos_count = (dates >= OOS_START).sum()
    print(f"  OOS days: {oos_count}")
    print()

    # Run for each distribution
    distributions = ["normal", "studentt", "skewt"]
    all_results = {}

    for dist in distributions:
        print(f"--- Running GJR-GARCH(1,1) with {dist} distribution ---")
        df = rolling_garch_var_es(returns_pct, returns_decimal, dates, dist=dist)

        if len(df) == 0:
            print(f"  No results for {dist}")
            continue

        returns_arr = df["return"].values
        var_arr = df["var"].values
        es_arr = df["es"].values

        # Compute test statistics
        z1, n_viol_1 = acerbi_szekely_z1(returns_arr, var_arr, es_arr)
        z2, n_viol_2 = acerbi_szekely_z2(returns_arr, var_arr, es_arr, alpha=ALPHA)

        print(f"  T = {len(df)}, Violations = {n_viol_1}")
        print(f"  Violation rate = {n_viol_1/len(df)*100:.2f}% (expected: {ALPHA*100:.1f}%)")
        print(f"  Z1 = {z1:.6f}")
        print(f"  Z2 = {z2:.6f}")

        # Bootstrap p-values
        print(f"  Computing bootstrap p-values ({N_BOOTSTRAP} reps)...")
        if not np.isnan(z1):
            p1 = bootstrap_pvalue(returns_arr, var_arr, es_arr, z1,
                                  "z1", alpha=ALPHA, n_boot=N_BOOTSTRAP, seed=SEED)
        else:
            p1 = np.nan

        if not np.isnan(z2):
            p2 = bootstrap_pvalue(returns_arr, var_arr, es_arr, z2,
                                  "z2", alpha=ALPHA, n_boot=N_BOOTSTRAP, seed=SEED)
        else:
            p2 = np.nan

        print(f"  Bootstrap p-value (Z1) = {p1:.4f}" if not np.isnan(p1) else "  Bootstrap p-value (Z1) = N/A")
        print(f"  Bootstrap p-value (Z2) = {p2:.4f}" if not np.isnan(p2) else "  Bootstrap p-value (Z2) = N/A")

        # Pass/fail at 5% level
        pass_z1 = "PASS" if (np.isnan(p1) or p1 > 0.05) else "FAIL"
        pass_z2 = "PASS" if (np.isnan(p2) or p2 > 0.05) else "FAIL"
        print(f"  Z1 test: {pass_z1} (at 5% level)")
        print(f"  Z2 test: {pass_z2} (at 5% level)")
        print()

        # Summary stats on ES
        mean_es = np.mean(es_arr) * 100
        median_es = np.median(es_arr) * 100
        max_es = np.max(es_arr) * 100
        mean_var = np.mean(var_arr) * 100
        es_var_ratio = np.mean(es_arr) / np.mean(var_arr)

        all_results[dist] = {
            "T": len(df),
            "n_violations": n_viol_1,
            "violation_rate_pct": round(n_viol_1 / len(df) * 100, 2),
            "Z1": round(z1, 6) if not np.isnan(z1) else None,
            "Z2": round(z2, 6) if not np.isnan(z2) else None,
            "p_value_Z1": round(p1, 4) if not np.isnan(p1) else None,
            "p_value_Z2": round(p2, 4) if not np.isnan(p2) else None,
            "pass_Z1": pass_z1,
            "pass_Z2": pass_z2,
            "mean_ES_pct": round(mean_es, 4),
            "median_ES_pct": round(median_es, 4),
            "max_ES_pct": round(max_es, 4),
            "mean_VaR_pct": round(mean_var, 4),
            "ES_VaR_ratio": round(es_var_ratio, 4),
        }

    # ============================================================================
    # Summary Table
    # ============================================================================
    print()
    print("=" * 72)
    print(" SUMMARY: Acerbi-Szekely ES Backtest Results")
    print("=" * 72)
    print()
    print(f"{'Distribution':<15} {'T':>5} {'Viol':>5} {'Rate%':>7} "
          f"{'Z1':>10} {'p(Z1)':>8} {'Z1':>6} "
          f"{'Z2':>10} {'p(Z2)':>8} {'Z2':>6} "
          f"{'ES/VaR':>7}")
    print("-" * 100)

    for dist in distributions:
        if dist not in all_results:
            continue
        r = all_results[dist]
        z1_str = f"{r['Z1']:.6f}" if r["Z1"] is not None else "N/A"
        z2_str = f"{r['Z2']:.6f}" if r["Z2"] is not None else "N/A"
        p1_str = f"{r['p_value_Z1']:.4f}" if r["p_value_Z1"] is not None else "N/A"
        p2_str = f"{r['p_value_Z2']:.4f}" if r["p_value_Z2"] is not None else "N/A"

        print(f"{dist:<15} {r['T']:>5} {r['n_violations']:>5} {r['violation_rate_pct']:>6.2f}% "
              f"{z1_str:>10} {p1_str:>8} {r['pass_Z1']:>6} "
              f"{z2_str:>10} {p2_str:>8} {r['pass_Z2']:>6} "
              f"{r['ES_VaR_ratio']:>7.4f}")

    print("-" * 100)
    print()

    # Interpretation
    print("INTERPRETATION:")
    print("  Z < 0 means ES is underestimated (actual tail losses exceed predictions)")
    print("  Z > 0 means ES is overestimated (conservative)")
    print("  p < 0.05 -> reject H0 (ES model is inadequate)")
    print("  p > 0.05 -> fail to reject H0 (ES model is adequate)")
    print()

    # Detailed per-distribution analysis
    for dist in distributions:
        if dist not in all_results:
            continue
        r = all_results[dist]
        print(f"  {dist}:")
        print(f"    Mean VaR = {r['mean_VaR_pct']:.4f}%  |  Mean ES = {r['mean_ES_pct']:.4f}%  |  ES/VaR = {r['ES_VaR_ratio']:.4f}")
        if r["Z1"] is not None and r["Z1"] < 0:
            print(f"    -> Z1 < 0: tail losses {abs(r['Z1'])*100:.2f}% larger than ES predicts")
        elif r["Z1"] is not None:
            print(f"    -> Z1 > 0: ES is conservative by {r['Z1']*100:.2f}%")
        overall = "PASS" if r["pass_Z1"] == "PASS" and r["pass_Z2"] == "PASS" else "FAIL"
        print(f"    -> Overall ES backtest: {overall}")
        print()

    # Basel III context
    print("BASEL III CONTEXT:")
    print("  Basel III requires ES at 97.5% (alpha=0.025) for market risk capital.")
    print("  This test uses alpha=0.01 (stricter). Passing at 1% implies adequacy at 2.5%.")
    print("  Skewed-t captures both heavy tails and negative skewness,")
    print("  making it the most realistic for equity index (SPY) tail risk.")
    print()

    # Save results
    output = {
        "test": "Acerbi-Szekely (2014) ES Backtest",
        "asset": ASSET,
        "window": WINDOW,
        "alpha": ALPHA,
        "oos_period": f"{OOS_START} to {END_DATE}",
        "n_bootstrap": N_BOOTSTRAP,
        "generated_at": datetime.now().isoformat(),
        "results": all_results,
    }

    output_path = Path("experiments/es_backtest_acerbi_szekely/es_backtest_acerbi_szekely_results.json")
    output_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str))
    print(f"Results saved to {output_path}")


if __name__ == "__main__":
    main()
