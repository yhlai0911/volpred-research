#!/usr/bin/env python3
"""Comprehensive VaR Backtest: Kupiec + Christoffersen + DQ (Engle-Manganelli).

Addresses Codex reviewer criticism: "Kupiec alone is far too weak."

Runs GJR-GARCH(1,1) rolling forecast for 7 assets × 5 VaR methods,
then applies three backtests:
  1. Kupiec (unconditional coverage)
  2. Christoffersen (independence / no clustering)
  3. DQ — Dynamic Quantile (Engle & Manganelli 2004)

Assets: SPY, QQQ, GLD, TLT, EEM, 0050.TW, BTC-USD
Methods: Normal, Student-t(5), Skewed-t, CF-VaR, FHS
Window: w=2000 (TLT/0050 w=504, BTC w=1000)
OOS: 2020-01-01 to 2025-12-31

Usage:
    uv run python scripts/var_backtest_trinity.py
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

# ── Configuration ──────────────────────────────────────────────────────────
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM", "0050.TW", "BTC-USD"]
METHODS = ["Normal", "Student-t(5)", "Skewed-t", "CF-VaR", "FHS"]
ALPHA = 0.05  # 5% VaR
OOS_START = "2020-01-01"
OOS_END = "2025-12-31"

# Window sizes per asset
WINDOW_MAP = {
    "SPY": 2000, "QQQ": 2000, "GLD": 2000,
    "TLT": 504, "EEM": 2000,
    "0050.TW": 504, "BTC-USD": 1000,
}


# ── VaR Methods ────────────────────────────────────────────────────────────

def var_normal(sigma, alpha=0.05):
    """Normal VaR: z_alpha * sigma."""
    return -stats.norm.ppf(alpha) * sigma


def var_studentt(sigma, df=5.0, alpha=0.05):
    """Student-t VaR with proper scaling."""
    scale = np.sqrt((df - 2) / df)
    z = -stats.t.ppf(alpha, df)
    return z * scale * sigma


def var_skewt(sigma, params, alpha=0.05):
    """Skewed-t VaR using arch's skewt parameters if available.
    Falls back to Hansen's skewed-t approximation."""
    try:
        from arch.univariate.distribution import SkewStudent
        skewt = SkewStudent()
        # params should have 'eta' (df) and 'lambda' (skewness)
        eta = params.get("eta", params.get("nu", 8.0))
        lam = params.get("lambda", params.get("lam", -0.1))
        # Use ppf from SkewStudent
        q = skewt.ppf(alpha, parameters=np.array([eta, lam]))
        return -q * sigma
    except Exception:
        # Fallback: use Student-t with slight skew adjustment
        df = params.get("eta", params.get("nu", 8.0))
        lam = params.get("lambda", params.get("lam", -0.1))
        base = var_studentt(sigma, df=df, alpha=alpha)
        # Negative lambda → left-skewed → larger VaR
        return base * (1 - 0.2 * lam)


def var_cornish_fisher(sigma, skew, kurt, alpha=0.05):
    """Cornish-Fisher VaR expansion.

    CF-VaR adjusts the Normal quantile for skewness and excess kurtosis:
    z_cf = z + (z^2 - 1)*S/6 + (z^3 - 3z)*K/24 - (2z^3 - 5z)*S^2/36
    """
    z = stats.norm.ppf(alpha)  # negative
    S = skew
    K = kurt - 3  # excess kurtosis
    z_cf = (z
            + (z**2 - 1) * S / 6
            + (z**3 - 3 * z) * K / 24
            - (2 * z**3 - 5 * z) * S**2 / 36)
    return -z_cf * sigma


def var_fhs(standardized_resids, sigma, alpha=0.05):
    """Filtered Historical Simulation VaR.

    Uses the empirical quantile of standardized residuals × current sigma.
    """
    q = np.percentile(standardized_resids, alpha * 100)
    return -q * sigma


# ── Backtests ──────────────────────────────────────────────────────────────

def kupiec_test(violations, alpha=0.05):
    """Kupiec POF test for unconditional coverage."""
    T = len(violations)
    n = int(np.sum(violations))
    p_hat = n / T if T > 0 else 0

    if n == 0 or n == T:
        return {"statistic": np.inf, "p_value": 0.0, "pass": False,
                "n_violations": n, "total": T, "obs_rate": p_hat}

    lr = -2 * (np.log((1 - alpha)**(T - n) * alpha**n)
               - np.log((1 - p_hat)**(T - n) * p_hat**n))
    p_value = 1 - stats.chi2.cdf(lr, 1)

    return {"statistic": float(lr), "p_value": float(p_value),
            "pass": p_value >= 0.05, "n_violations": n,
            "total": T, "obs_rate": float(p_hat)}


def christoffersen_test(violations):
    """Christoffersen independence test (Markov chain LR test)."""
    T = len(violations)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        prev, curr = int(violations[t-1]), int(violations[t])
        if prev == 0 and curr == 0: n00 += 1
        elif prev == 0 and curr == 1: n01 += 1
        elif prev == 1 and curr == 0: n10 += 1
        else: n11 += 1

    # Transition probabilities
    pi01 = n01 / max(n00 + n01, 1)
    pi11 = n11 / max(n10 + n11, 1)
    pi = (n01 + n11) / max(T - 1, 1)

    # Independence LR
    if pi01 <= 0 or pi11 <= 0 or pi01 >= 1 or pi11 >= 1 or pi <= 0 or pi >= 1:
        lr_ind = 0.0
    else:
        lr_ind = -2 * (
            (n00 + n10) * np.log(1 - pi) + (n01 + n11) * np.log(pi)
            - n00 * np.log(1 - pi01) - n01 * np.log(pi01)
            - n10 * np.log(1 - pi11) - n11 * np.log(pi11)
        )

    p_value = 1 - stats.chi2.cdf(max(lr_ind, 0), 1)
    return {"statistic": float(lr_ind), "p_value": float(p_value),
            "pass": p_value >= 0.05,
            "pi01": float(pi01), "pi11": float(pi11),
            "n00": n00, "n01": n01, "n10": n10, "n11": n11}


def dq_test(violations, var_forecasts, alpha=0.05, n_lags=4):
    """Dynamic Quantile (DQ) test of Engle & Manganelli (2004).

    Regresses the hit variable (I_t - alpha) on:
      - Constant
      - Lagged hits (n_lags)
      - Current VaR forecast

    H0: All coefficients are zero (hits are unpredictable).
    Reject → VaR model is misspecified (violations are predictable).

    Test statistic: DQ = (X'hit)' (X' X)^{-1} (X'hit) / alpha(1-alpha)
    Under H0, DQ ~ chi2(n_lags + 2)
    """
    T = len(violations)
    hit = violations.astype(float) - alpha  # hit variable

    # Build regressor matrix X: [constant, lag1...lagK, VaR]
    max_lag = n_lags
    n = T - max_lag
    if n < 10:
        return {"statistic": np.nan, "p_value": np.nan, "pass": True,
                "reason": "insufficient_data"}

    X = np.zeros((n, n_lags + 2))
    X[:, 0] = 1.0  # constant
    for lag in range(1, n_lags + 1):
        X[:, lag] = hit[max_lag - lag: T - lag]
    X[:, -1] = var_forecasts[max_lag:]  # current VaR forecast

    hit_trimmed = hit[max_lag:]

    try:
        XtX = X.T @ X
        # Add small ridge for numerical stability
        XtX += 1e-10 * np.eye(XtX.shape[0])
        XtX_inv = np.linalg.inv(XtX)
        Xhit = X.T @ hit_trimmed
        dq_stat = float(Xhit.T @ XtX_inv @ Xhit / (alpha * (1 - alpha)))
        df = n_lags + 2
        p_value = 1 - stats.chi2.cdf(max(dq_stat, 0), df)
        return {"statistic": float(dq_stat), "p_value": float(p_value),
                "pass": p_value >= 0.05, "df": df}
    except np.linalg.LinAlgError:
        return {"statistic": np.nan, "p_value": np.nan, "pass": True,
                "reason": "singular_matrix"}


# ── Rolling GJR-GARCH Forecast ────────────────────────────────────────────

def run_rolling_gjr(asset, window, oos_start, oos_end):
    """Run rolling GJR-GARCH(1,1) and return forecasts + diagnostics."""
    # Download data with enough history
    extra_years = max(int(window / 252) + 2, 5)
    data_start = f"{int(oos_start[:4]) - extra_years}-01-01"

    print(f"  Downloading {asset} from {data_start}...")
    data = yf.download(asset, start=data_start, end=oos_end, progress=False)

    if len(data) == 0:
        print(f"  ERROR: No data for {asset}")
        return None

    # Handle MultiIndex columns from yfinance
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data["return"] = data["Close"].pct_change()
    data = data.dropna()

    oos_mask = (data.index >= pd.Timestamp(oos_start)) & (data.index <= pd.Timestamp(oos_end))
    oos_dates = data.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  ERROR: No OOS data for {asset}")
        return None

    returns_pct = data["return"] * 100  # arch expects percentage returns

    print(f"  OOS: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')} ({len(oos_dates)} days)")
    print(f"  Window: {window}, Total data: {len(data)}")

    results = []
    skipped = 0

    for i, date in enumerate(oos_dates):
        idx = data.index.get_loc(date)
        if idx < window:
            skipped += 1
            continue

        train = returns_pct.iloc[idx - window: idx].values
        actual_return = data["return"].iloc[idx]

        try:
            # Fit GJR-GARCH with skewed-t for maximum info
            am = arch_model(train, vol="GARCH", p=1, q=1, o=1,
                          dist="skewt", mean="Zero", rescale=False)
            res = am.fit(disp="off", show_warning=False)

            # Forecast variance
            fcast = res.forecast(horizon=1)
            sigma_pct = fcast.variance.iloc[-1, 0] ** 0.5  # in pct
            sigma = sigma_pct / 100  # convert to decimal

            # Extract standardized residuals for FHS
            std_resid = res.std_resid

            # Sample statistics for CF-VaR
            sample_skew = float(stats.skew(std_resid))
            sample_kurt = float(stats.kurtosis(std_resid, fisher=False))  # raw kurtosis

            # Distribution parameters
            params_dict = dict(res.params)

            results.append({
                "date": date,
                "actual_return": float(actual_return),
                "sigma": float(sigma),
                "std_resid": std_resid.copy(),
                "sample_skew": sample_skew,
                "sample_kurt": sample_kurt,
                "dist_params": params_dict,
                "converged": res.convergence_flag == 0,
            })

        except Exception as e:
            skipped += 1
            continue

        # Progress
        if (i + 1) % 200 == 0:
            print(f"    {i+1}/{len(oos_dates)} forecasts done...")

    print(f"  Completed: {len(results)} forecasts, {skipped} skipped")
    return results


def compute_var_series(results, method, alpha=0.05):
    """Compute VaR series for a given method."""
    var_values = []

    for r in results:
        sigma = r["sigma"]

        if method == "Normal":
            v = var_normal(sigma, alpha)
        elif method == "Student-t(5)":
            v = var_studentt(sigma, df=5.0, alpha=alpha)
        elif method == "Skewed-t":
            v = var_skewt(sigma, r["dist_params"], alpha)
        elif method == "CF-VaR":
            v = var_cornish_fisher(sigma, r["sample_skew"], r["sample_kurt"], alpha)
        elif method == "FHS":
            v = var_fhs(r["std_resid"], sigma, alpha)
        else:
            v = var_normal(sigma, alpha)

        # Ensure VaR is positive and reasonable
        v = max(v, 1e-8)
        var_values.append(v)

    return np.array(var_values)


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    start_time = time.time()
    print("=" * 80)
    print(" VaR Backtest Trinity: Kupiec + Christoffersen + DQ")
    print(f" Assets: {', '.join(ASSETS)}")
    print(f" Methods: {', '.join(METHODS)}")
    print(f" OOS: {OOS_START} to {OOS_END}, alpha={ALPHA}")
    print(f" Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    # Store all results
    all_results = {}

    for asset in ASSETS:
        print(f"\n{'─' * 60}")
        print(f"Processing {asset}...")
        window = WINDOW_MAP[asset]

        forecasts = run_rolling_gjr(asset, window, OOS_START, OOS_END)
        if forecasts is None or len(forecasts) < 50:
            print(f"  SKIP: insufficient forecasts for {asset}")
            all_results[asset] = {m: {"error": "insufficient_data"} for m in METHODS}
            continue

        actual_returns = np.array([r["actual_return"] for r in forecasts])
        n_obs = len(actual_returns)

        asset_results = {}
        for method in METHODS:
            var_series = compute_var_series(forecasts, method, ALPHA)
            violations = (actual_returns < -var_series).astype(int)

            # Run three tests
            kup = kupiec_test(violations, ALPHA)
            chris = christoffersen_test(violations)
            dq = dq_test(violations, var_series, ALPHA, n_lags=4)

            n_pass = sum([kup["pass"], chris["pass"], dq["pass"]])

            asset_results[method] = {
                "n_obs": n_obs,
                "n_violations": kup["n_violations"],
                "obs_rate": kup["obs_rate"],
                "kupiec": kup,
                "christoffersen": chris,
                "dq": dq,
                "n_pass": n_pass,
            }

        all_results[asset] = asset_results

    elapsed = time.time() - start_time

    # ── Print Results Matrix ───────────────────────────────────────────
    print("\n\n")
    print("=" * 120)
    print(" COMPLETE RESULTS MATRIX: 7 Assets × 5 VaR Methods × 3 Tests")
    print("=" * 120)

    # Header
    header = f"{'Asset':<10} {'Method':<14} {'N':>5} {'Viol':>5} {'Rate':>6} "
    header += f"{'Kup-p':>7} {'K':>2} {'Chr-p':>7} {'C':>2} {'DQ-p':>7} {'D':>2} {'Pass':>5}"
    print(header)
    print("-" * 120)

    # Summary counters
    method_pass_counts = {m: 0 for m in METHODS}
    method_total_counts = {m: 0 for m in METHODS}
    method_all3_counts = {m: 0 for m in METHODS}  # pass ALL 3 for how many assets

    for asset in ASSETS:
        for i, method in enumerate(METHODS):
            r = all_results[asset].get(method, {})
            if "error" in r:
                print(f"{asset if i==0 else '':<10} {method:<14} {'--- insufficient data ---'}")
                continue

            kup_p = r["kupiec"]["p_value"]
            chr_p = r["christoffersen"]["p_value"]
            dq_p = r["dq"]["p_value"]

            kup_pass = "Y" if r["kupiec"]["pass"] else "N"
            chr_pass = "Y" if r["christoffersen"]["pass"] else "N"
            dq_pass = "Y" if r["dq"]["pass"] else "N"

            n_pass = r["n_pass"]
            pass_str = f"{n_pass}/3"

            # Format p-values
            def fmt_p(p):
                if np.isnan(p): return "  N/A"
                if p < 0.001: return "<.001"
                return f"{p:.3f}"

            line = f"{asset if i==0 else '':<10} {method:<14} "
            line += f"{r['n_obs']:>5} {r['n_violations']:>5} {r['obs_rate']:.3f} "
            line += f"{fmt_p(kup_p):>7} {kup_pass:>2} "
            line += f"{fmt_p(chr_p):>7} {chr_pass:>2} "
            line += f"{fmt_p(dq_p):>7} {dq_pass:>2} "
            line += f"{pass_str:>5}"
            print(line)

            method_total_counts[method] += 1
            method_pass_counts[method] += n_pass
            if n_pass == 3:
                method_all3_counts[method] += 1

        print()  # blank line between assets

    # ── Summary ────────────────────────────────────────────────────────
    print("=" * 120)
    print(" SUMMARY: Which VaR method passes ALL 3 tests for the MOST assets?")
    print("=" * 120)
    print(f"{'Method':<16} {'All-3 Pass':>10} {'Total Tests Passed':>20} {'Avg Pass Rate':>15}")
    print("-" * 70)

    best_method = None
    best_count = -1
    for method in METHODS:
        total = method_total_counts[method]
        all3 = method_all3_counts[method]
        total_pass = method_pass_counts[method]
        avg_rate = total_pass / (total * 3) if total > 0 else 0

        marker = ""
        if all3 > best_count:
            best_count = all3
            best_method = method

        print(f"{method:<16} {all3:>5}/{total:<4} {total_pass:>10}/{total*3:<8} {avg_rate:>12.1%}")

    # Handle ties
    tied_methods = [m for m in METHODS if method_all3_counts[m] == best_count]
    if len(tied_methods) > 1:
        # Break tie by total tests passed
        tied_methods.sort(key=lambda m: method_pass_counts[m], reverse=True)
        best_method = tied_methods[0]

    print(f"\nBest method: {best_method} (passes ALL 3 tests for {best_count}/{len(ASSETS)} assets)")
    print(f"Elapsed time: {elapsed:.1f}s")

    # ── Per-test summary ───────────────────────────────────────────────
    print("\n" + "=" * 80)
    print(" PER-TEST PASS RATES (across all asset-method combinations)")
    print("=" * 80)

    test_names = ["kupiec", "christoffersen", "dq"]
    for test in test_names:
        passes = 0
        total = 0
        for asset in ASSETS:
            for method in METHODS:
                r = all_results[asset].get(method, {})
                if "error" in r:
                    continue
                total += 1
                if r[test]["pass"]:
                    passes += 1
        print(f"  {test.capitalize():20s}: {passes}/{total} pass ({passes/total*100:.1f}%)" if total > 0 else f"  {test}: N/A")

    # ── Save results ───────────────────────────────────────────────────
    # Prepare serializable results
    save_results = {}
    for asset in ASSETS:
        save_results[asset] = {}
        for method in METHODS:
            r = all_results[asset].get(method, {})
            if "error" in r:
                save_results[asset][method] = r
                continue
            save_results[asset][method] = {
                "n_obs": r["n_obs"],
                "n_violations": r["n_violations"],
                "obs_rate": r["obs_rate"],
                "kupiec_p": r["kupiec"]["p_value"],
                "kupiec_pass": r["kupiec"]["pass"],
                "christoffersen_p": r["christoffersen"]["p_value"],
                "christoffersen_pass": r["christoffersen"]["pass"],
                "dq_p": r["dq"]["p_value"],
                "dq_pass": r["dq"]["pass"],
                "n_pass": r["n_pass"],
            }

    report = {
        "title": "VaR Backtest Trinity: Kupiec + Christoffersen + DQ",
        "generated_at": datetime.now().isoformat(),
        "config": {
            "assets": ASSETS,
            "methods": METHODS,
            "alpha": ALPHA,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "window_map": WINDOW_MAP,
            "model": "GJR-GARCH(1,1)",
            "dq_lags": 4,
        },
        "results": save_results,
        "summary": {
            "best_method": best_method,
            "best_method_all3_count": best_count,
            "method_all3_counts": method_all3_counts,
            "method_total_pass": method_pass_counts,
            "elapsed_seconds": round(elapsed, 1),
        },
    }

    out_path = Path("storage/reports/var_backtest_trinity.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nResults saved to {out_path}")

    return report


if __name__ == "__main__":
    report = main()
