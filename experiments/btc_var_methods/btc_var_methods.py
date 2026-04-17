#!/usr/bin/env python3
"""BTC-USD VaR Method Comparison: Normal, Student-t(5), Skewed-t, CF-VaR, FHS.

Tests whether crypto assets need different VaR methods than equities.
For equities, Skewed-t is best (6/6 Kupiec pass). Crypto has:
- No stable leverage effect (gamma insignificant)
- Much fatter tails
- Higher volatility (50-80% annualized)

Setup:
- Asset: BTC-USD via yfinance
- Models: GJR-GARCH(1,1) and GARCH(1,1) for comparison
- Rolling window: w=1000
- OOS: 2022-01-01 to 2025-12-31
- VaR level: 1%

[提出: 用戶, 執行: Claude]
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime


# ─── Kupiec test ───────────────────────────────────────────────────
def kupiec_test(violations, alpha=0.01):
    """Kupiec's POF test. Returns dict with statistic, p_value, n, T."""
    T = len(violations)
    n = int(np.sum(violations))
    if n == 0 or n == T:
        return {"statistic": float("inf"), "p_value": 0.0, "n": n, "T": T, "rate": n / T if T > 0 else 0.0}
    p_hat = n / T
    lr = -2 * (
        np.log((1 - alpha) ** (T - n) * alpha**n)
        - np.log((1 - p_hat) ** (T - n) * p_hat**n)
    )
    p_value = 1 - stats.chi2.cdf(lr, 1)
    return {"statistic": round(lr, 4), "p_value": round(p_value, 6), "n": n, "T": T, "rate": round(p_hat, 4)}


def christoffersen_test(violations):
    """Christoffersen independence test."""
    T = len(violations)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        if violations[t - 1] == 0 and violations[t] == 0:
            n00 += 1
        elif violations[t - 1] == 0 and violations[t] == 1:
            n01 += 1
        elif violations[t - 1] == 1 and violations[t] == 0:
            n10 += 1
        else:
            n11 += 1
    pi01 = n01 / max(n00 + n01, 1)
    pi11 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(T - 1, 1)
    if pi01 <= 0 or pi11 <= 0 or pi01 >= 1 or pi11 >= 1 or pi <= 0 or pi >= 1:
        lr_ind = 0.0
    else:
        lr_ind = -2 * (
            (n00 + n10) * np.log(1 - pi) + (n01 + n11) * np.log(pi)
            - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
            - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
        )
    p_ind = 1 - stats.chi2.cdf(max(lr_ind, 0), 1)
    return {
        "independence_stat": round(float(lr_ind), 4),
        "independence_pval": round(float(p_ind), 6),
        "pi01": round(pi01, 4),
        "pi11": round(pi11, 4),
        "conclusion": "independent" if p_ind >= 0.05 else "clustered",
    }


# ─── VaR computation methods ──────────────────────────────────────
def var_normal(sigma, alpha=0.01):
    """Normal VaR: z_norm * sigma."""
    z = -stats.norm.ppf(alpha)
    return z * sigma


def var_student_t5(sigma, alpha=0.01):
    """Student-t(5) VaR: z_t * sigma * scale."""
    df = 5
    scale = np.sqrt((df - 2) / df)
    z = -stats.t.ppf(alpha, df)
    return z * scale * sigma


def var_skewt(sigma, eta, lam, alpha=0.01):
    """Skewed Student-t VaR using arch's SkewStudent ppf."""
    from arch.univariate import SkewStudent
    skewt = SkewStudent()
    # ppf expects (q, parameters=[eta, lam])
    q = skewt.ppf(alpha, parameters=np.array([eta, lam]))
    # q is in standardized residual space; scale by sigma
    # arch residuals are in pct space, so convert
    return -q * sigma  # q is negative for left tail, so -q is positive


def var_cf(sigma, resid_std, alpha=0.01):
    """Cornish-Fisher VaR on standardized residuals (winsorized at +/-5 sigma)."""
    # Winsorize
    z = np.clip(resid_std, -5, 5)
    s = stats.skew(z)
    k = stats.kurtosis(z, fisher=True)  # excess kurtosis
    z_alpha = stats.norm.ppf(alpha)
    # Cornish-Fisher expansion
    cf = (
        z_alpha
        + (z_alpha**2 - 1) * s / 6
        + (z_alpha**3 - 3 * z_alpha) * k / 24
        - (2 * z_alpha**3 - 5 * z_alpha) * s**2 / 36
    )
    return -cf * sigma  # positive value


def var_fhs(sigma, resid_std, alpha=0.01):
    """Filtered Historical Simulation: empirical quantile of std residuals * sigma."""
    q = np.quantile(resid_std, alpha)
    return -q * sigma  # positive value


# ─── Main experiment ───────────────────────────────────────────────
def run_btc_var_experiment(model_type="GJR", window=1000):
    """Run rolling VaR backtest for BTC-USD."""

    print(f"\n{'='*80}")
    print(f" BTC-USD VaR Method Comparison")
    print(f" Model: {model_type}-GARCH(1,1), Window={window}")
    print(f" OOS: 2022-01-01 to 2025-12-31, VaR level: 1%")
    print(f"{'='*80}\n")

    # Download data
    print("Downloading BTC-USD data...")
    data = yf.download("BTC-USD", start="2017-01-01", end="2026-01-01", progress=False)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data["return"] = data["Close"].pct_change()
    data = data.dropna()
    print(f"Total data: {len(data)} days ({data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')})")

    # Basic stats
    ann_vol = data["return"].std() * np.sqrt(365)  # crypto trades 365 days
    print(f"Annualized vol (full sample): {ann_vol:.1%}")
    print(f"Skewness: {stats.skew(data['return'].values):.3f}")
    print(f"Excess kurtosis: {stats.kurtosis(data['return'].values, fisher=True):.3f}")

    # OOS period
    oos_start = "2022-01-01"
    oos_end = "2025-12-31"
    oos_mask = (data.index >= oos_start) & (data.index <= oos_end)
    oos_dates = data.index[oos_mask]
    print(f"\nOOS dates: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')} ({len(oos_dates)} days)")

    returns_pct = data["return"] * 100

    # Storage for results
    results = {
        "dates": [],
        "returns": [],
        "sigmas": [],
        "var_normal": [],
        "var_t5": [],
        "var_skewt": [],
        "var_cf": [],
        "var_fhs": [],
        "skewt_eta": [],
        "skewt_lambda": [],
        "gamma_values": [],
        "gamma_pvalues": [],
    }

    n_failed = 0
    n_total = len(oos_dates)

    for i, date in enumerate(oos_dates):
        idx = data.index.get_loc(date)
        if idx < window:
            continue

        train = returns_pct.iloc[idx - window : idx]

        try:
            # Fit model
            if model_type == "GJR":
                am_norm = arch_model(train, vol="GARCH", p=1, q=1, o=1, dist="normal", mean="Zero", rescale=False)
            else:  # GARCH
                am_norm = arch_model(train, vol="GARCH", p=1, q=1, dist="normal", mean="Zero", rescale=False)
            res_norm = am_norm.fit(disp="off", show_warning=False)

            # Get sigma forecast (in pct)
            sigma_pct = res_norm.forecast(horizon=1).variance.iloc[-1, 0] ** 0.5
            sigma = sigma_pct / 100  # convert to decimal

            # Standardized residuals from the fitted model
            resid_std = res_norm.std_resid.values
            resid_std = resid_std[~np.isnan(resid_std)]

            # 1. Normal VaR
            v_normal = var_normal(sigma)

            # 2. Student-t(5) VaR
            v_t5 = var_student_t5(sigma)

            # 3. Skewed-t VaR — fit with skewt distribution
            if model_type == "GJR":
                am_skewt = arch_model(train, vol="GARCH", p=1, q=1, o=1, dist="skewt", mean="Zero", rescale=False)
            else:
                am_skewt = arch_model(train, vol="GARCH", p=1, q=1, dist="skewt", mean="Zero", rescale=False)
            res_skewt = am_skewt.fit(disp="off", show_warning=False)

            eta = res_skewt.params.get("eta", res_skewt.params.get("nu", 5.0))
            lam = res_skewt.params.get("lambda", 0.0)

            sigma_skewt_pct = res_skewt.forecast(horizon=1).variance.iloc[-1, 0] ** 0.5
            sigma_skewt = sigma_skewt_pct / 100
            v_skewt = var_skewt(sigma_skewt, eta, lam)

            # 4. CF-VaR (on standardized residuals from normal model)
            v_cf = var_cf(sigma, resid_std)

            # 5. FHS
            v_fhs = var_fhs(sigma, resid_std)

            # Get gamma info (GJR only)
            if model_type == "GJR":
                gamma_val = res_norm.params.get("gamma[1]", 0.0)
                # Get p-value from summary
                try:
                    gamma_pval = res_norm.pvalues.get("gamma[1]", 1.0)
                except Exception:
                    gamma_pval = 1.0
            else:
                gamma_val = 0.0
                gamma_pval = 1.0

            actual_return = data["return"].iloc[idx]

            results["dates"].append(date)
            results["returns"].append(actual_return)
            results["sigmas"].append(sigma)
            results["var_normal"].append(v_normal)
            results["var_t5"].append(v_t5)
            results["var_skewt"].append(v_skewt)
            results["var_cf"].append(v_cf)
            results["var_fhs"].append(v_fhs)
            results["skewt_eta"].append(eta)
            results["skewt_lambda"].append(lam)
            results["gamma_values"].append(gamma_val)
            results["gamma_pvalues"].append(gamma_pval)

        except Exception as e:
            n_failed += 1
            if n_failed <= 3:
                print(f"  Failed at {date.strftime('%Y-%m-%d')}: {e}")
            continue

        if (i + 1) % 200 == 0:
            print(f"  Progress: {i+1}/{n_total} ({(i+1)/n_total*100:.0f}%)")

    print(f"\nCompleted: {len(results['dates'])} forecasts, {n_failed} failed")

    if len(results["dates"]) == 0:
        print("ERROR: No forecasts generated. Exiting.")
        return None, None, None, None

    # Convert to arrays
    returns = np.array(results["returns"])
    dates_arr = pd.DatetimeIndex(results["dates"])

    methods = {
        "Normal": np.array(results["var_normal"]),
        "Student-t(5)": np.array(results["var_t5"]),
        "Skewed-t": np.array(results["var_skewt"]),
        "CF-VaR": np.array(results["var_cf"]),
        "FHS": np.array(results["var_fhs"]),
    }

    # ─── Overall Results ───────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f" OVERALL RESULTS ({model_type}-GARCH)")
    print(f"{'='*80}")
    print(f"\n{'Method':<15} {'Viols':>6} {'Rate':>8} {'Expected':>9} {'Kupiec LR':>10} {'Kupiec p':>10} {'Pass?':>6} {'Chr. p':>8} {'Indep?':>7}")
    print("-" * 90)

    for name, var_vals in methods.items():
        violations = (returns < -var_vals).astype(int)
        kup = kupiec_test(violations, alpha=0.01)
        chr_test = christoffersen_test(violations)
        pass_str = "YES" if kup["p_value"] >= 0.05 else "NO"
        indep_str = "YES" if chr_test["independence_pval"] >= 0.05 else "NO"
        print(
            f"{name:<15} {kup['n']:>6} {kup['rate']:>7.3f} {'0.010':>9} "
            f"{kup['statistic']:>10.3f} {kup['p_value']:>10.4f} {pass_str:>6} "
            f"{chr_test['independence_pval']:>8.4f} {indep_str:>7}"
        )

    # ─── Year-by-Year Results ──────────────────────────────────────
    years = dates_arr.year
    unique_years = sorted(set(years))

    print(f"\n{'='*80}")
    print(f" YEAR-BY-YEAR VIOLATIONS ({model_type}-GARCH)")
    print(f"{'='*80}")

    for name, var_vals in methods.items():
        violations = (returns < -var_vals).astype(int)
        print(f"\n  {name}:")
        print(f"  {'Year':>6} {'Days':>6} {'Viols':>6} {'Rate':>8} {'Kupiec p':>10} {'Pass?':>6}")
        print("  " + "-" * 50)
        for yr in unique_years:
            mask = years == yr
            n_days = mask.sum()
            n_viols = violations[mask].sum()
            rate = n_viols / n_days
            kup = kupiec_test(violations[mask], alpha=0.01)
            pass_str = "YES" if kup["p_value"] >= 0.05 else "NO"
            print(f"  {yr:>6} {n_days:>6} {n_viols:>6} {rate:>8.3f} {kup['p_value']:>10.4f} {pass_str:>6}")

    # ─── Skewed-t Parameters ──────────────────────────────────────
    eta_arr = np.array(results["skewt_eta"])
    lam_arr = np.array(results["skewt_lambda"])

    print(f"\n{'='*80}")
    print(f" SKEWED-T PARAMETER STABILITY ({model_type}-GARCH)")
    print(f"{'='*80}")
    print(f"\n  eta (degrees of freedom):")
    print(f"    Mean: {np.mean(eta_arr):.3f}")
    print(f"    Std:  {np.std(eta_arr):.3f}")
    print(f"    Min:  {np.min(eta_arr):.3f}")
    print(f"    Max:  {np.max(eta_arr):.3f}")

    print(f"\n  lambda (skewness):")
    print(f"    Mean: {np.mean(lam_arr):.4f}")
    print(f"    Std:  {np.std(lam_arr):.4f}")
    print(f"    Min:  {np.min(lam_arr):.4f}")
    print(f"    Max:  {np.max(lam_arr):.4f}")

    # Year-by-year skewed-t params
    print(f"\n  Year-by-year averages:")
    print(f"  {'Year':>6} {'eta mean':>10} {'eta std':>10} {'lambda mean':>12} {'lambda std':>12}")
    print("  " + "-" * 50)
    for yr in unique_years:
        mask = years == yr
        print(
            f"  {yr:>6} {np.mean(eta_arr[mask]):>10.3f} {np.std(eta_arr[mask]):>10.3f} "
            f"{np.mean(lam_arr[mask]):>12.4f} {np.std(lam_arr[mask]):>12.4f}"
        )

    # ─── GJR Gamma Analysis ───────────────────────────────────────
    if model_type == "GJR":
        gamma_arr = np.array(results["gamma_values"])
        gamma_pval_arr = np.array(results["gamma_pvalues"])

        print(f"\n{'='*80}")
        print(f" GJR GAMMA (LEVERAGE EFFECT) ANALYSIS")
        print(f"{'='*80}")
        print(f"\n  gamma values:")
        print(f"    Mean: {np.mean(gamma_arr):.6f}")
        print(f"    Std:  {np.std(gamma_arr):.6f}")
        print(f"    Median: {np.median(gamma_arr):.6f}")
        print(f"    % significant (p<0.05): {(gamma_pval_arr < 0.05).mean()*100:.1f}%")
        print(f"    % negative: {(gamma_arr < 0).mean()*100:.1f}%")

        print(f"\n  Year-by-year:")
        print(f"  {'Year':>6} {'gamma mean':>12} {'gamma std':>12} {'% sig':>8}")
        print("  " + "-" * 40)
        for yr in unique_years:
            mask = years == yr
            print(
                f"  {yr:>6} {np.mean(gamma_arr[mask]):>12.6f} {np.std(gamma_arr[mask]):>12.6f} "
                f"{(gamma_pval_arr[mask] < 0.05).mean()*100:>7.1f}%"
            )

    # ─── Sigma Stats ──────────────────────────────────────────────
    sigmas = np.array(results["sigmas"])
    print(f"\n{'='*80}")
    print(f" VOLATILITY STATISTICS ({model_type}-GARCH)")
    print(f"{'='*80}")
    print(f"\n  Annualized vol (sigma * sqrt(365)):")
    for yr in unique_years:
        mask = years == yr
        ann = sigmas[mask] * np.sqrt(365) * 100
        print(f"    {yr}: mean={np.mean(ann):.1f}%, min={np.min(ann):.1f}%, max={np.max(ann):.1f}%")

    # ─── Average VaR by method ─────────────────────────────────────
    print(f"\n  Average daily VaR (in %):")
    for name, var_vals in methods.items():
        print(f"    {name:<15}: {np.mean(var_vals)*100:.2f}%")

    return results, methods, returns, dates_arr


# ─── Run both models ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 80)
    print(" BTC-USD VaR Methods: 5-Way Comparison")
    print(" Normal vs Student-t(5) vs Skewed-t vs CF-VaR vs FHS")
    print(" Both GJR-GARCH(1,1) and GARCH(1,1)")
    print("=" * 80)

    # Run GJR-GARCH
    res_gjr, methods_gjr, returns_gjr, dates_gjr = run_btc_var_experiment("GJR", window=1000)

    # Run GARCH (since gamma is insignificant for BTC)
    res_garch, methods_garch, returns_garch, dates_garch = run_btc_var_experiment("GARCH", window=1000)

    # ─── Side-by-side comparison ──────────────────────────────────
    print(f"\n{'='*80}")
    print(f" SIDE-BY-SIDE: GJR-GARCH vs GARCH")
    print(f"{'='*80}")
    print(f"\n{'Method':<15} {'GJR Viols':>10} {'GJR Rate':>10} {'GJR Kup-p':>10} {'GARCH Viols':>12} {'GARCH Rate':>11} {'GARCH Kup-p':>12}")
    print("-" * 85)

    method_names = ["Normal", "Student-t(5)", "Skewed-t", "CF-VaR", "FHS"]
    for name in method_names:
        v_gjr = (returns_gjr < -methods_gjr[name]).astype(int)
        v_garch = (returns_garch < -methods_garch[name]).astype(int)
        k_gjr = kupiec_test(v_gjr, 0.01)
        k_garch = kupiec_test(v_garch, 0.01)

        print(
            f"{name:<15} {k_gjr['n']:>10} {k_gjr['rate']:>10.3f} {k_gjr['p_value']:>10.4f} "
            f"{k_garch['n']:>12} {k_garch['rate']:>11.3f} {k_garch['p_value']:>12.4f}"
        )

    # ─── Final summary ────────────────────────────────────────────
    print(f"\n{'='*80}")
    print(f" CONCLUSIONS")
    print(f"{'='*80}")

    # Count passes
    for model_name, (methods_dict, rets) in [("GJR-GARCH", (methods_gjr, returns_gjr)), ("GARCH", (methods_garch, returns_garch))]:
        print(f"\n  {model_name}:")
        for name in method_names:
            v = (rets < -methods_dict[name]).astype(int)
            k = kupiec_test(v, 0.01)
            status = "PASS (p={:.4f})".format(k["p_value"]) if k["p_value"] >= 0.05 else "FAIL (p={:.4f})".format(k["p_value"])
            print(f"    {name:<15}: {status} — {k['n']} violations ({k['rate']:.3f})")

    print(f"\n{'='*80}")
    print(" Done.")
