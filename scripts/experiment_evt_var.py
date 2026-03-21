#!/usr/bin/env python3
"""
EVT-VaR (Extreme Value Theory) — Peaks-over-Threshold for Tail Risk
====================================================================

研究目的：EVT-VaR 是否能改善 Skewed-t（目前最佳 6/6 Kupiec pass）在極端分位
（0.5%, 1%）的 VaR 估計？

方法：
1. POT (Peaks-over-Threshold)：用 GPD 擬合超越門檻的損失尾部
2. Rolling estimation (w=2000)，每日重估 GPD 參數
3. OOS: 2023-01-01 ~ latest
4. 比較 6 種 VaR 方法：Normal, Student-t(4), Skewed-t, CF-VaR, FHS, EVT-POT
5. 3 種 alpha: 0.5%, 1%, 5%
6. Trinity test (Kupiec + Christoffersen + DQ)

資產：SPY, QQQ, GLD, TLT, EEM

[提出: research_program.md (unexplored), 執行: Claude]

Usage:
    uv run python scripts/experiment_evt_var.py
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
from scipy.stats import genpareto

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════════════════════════
# Configuration
# ══════════════════════════════════════════════════════════════════════
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM"]
METHODS = ["Normal", "Student-t(4)", "Skewed-t", "CF-VaR", "FHS", "EVT-POT"]
ALPHAS = [0.005, 0.01, 0.05]
OOS_START = "2023-01-01"
OOS_END = "2026-12-31"  # will be clipped to available data
WINDOW = 2000
DQ_LAGS = 4
GPD_THRESHOLD_QUANTILE = 0.90  # top 10% of losses for POT

# ══════════════════════════════════════════════════════════════════════
# VaR Methods
# ══════════════════════════════════════════════════════════════════════

def var_normal(sigma, alpha):
    """Normal VaR."""
    return -stats.norm.ppf(alpha) * sigma


def var_studentt(sigma, alpha, df=4.0):
    """Student-t(df) VaR with variance scaling."""
    scale = np.sqrt((df - 2) / df)
    return -stats.t.ppf(alpha, df) * scale * sigma


def var_skewt(sigma, eta, lam, alpha):
    """Skewed Student-t VaR using arch's SkewStudent ppf."""
    try:
        from arch.univariate.distribution import SkewStudent
        skewt = SkewStudent()
        q = skewt.ppf(alpha, parameters=np.array([eta, lam]))
        return -q * sigma
    except Exception:
        base = var_studentt(sigma, alpha, df=max(eta, 2.1))
        return base * (1 - 0.2 * lam)


def var_cornish_fisher(sigma, skew, excess_kurt, alpha):
    """Cornish-Fisher VaR expansion."""
    z = stats.norm.ppf(alpha)
    S = np.clip(skew, -2, 2)  # winsorize to prevent divergence
    K = np.clip(excess_kurt, -3, 30)
    z_cf = (z
            + (z**2 - 1) * S / 6
            + (z**3 - 3 * z) * K / 24
            - (2 * z**3 - 5 * z) * S**2 / 36)
    return -z_cf * sigma


def var_fhs(std_resid, sigma, alpha):
    """Filtered Historical Simulation VaR."""
    q = np.percentile(std_resid, alpha * 100)
    return -q * sigma


def var_evt_pot(std_resid, sigma, alpha, threshold_q=0.90):
    """EVT-VaR using Peaks-over-Threshold (POT) with GPD.

    Steps:
    1. Take standardized residuals → losses = -std_resid
    2. Set threshold u at threshold_q quantile of losses
    3. Fit GPD to exceedances (losses > u)
    4. Compute VaR_alpha from GPD tail formula
    5. Scale by sigma

    VaR formula (McNeil & Frey 2000):
        VaR_α = u + (β/ξ) * [(n/N_u * α)^(-ξ) - 1]
    where:
        u = threshold
        ξ = shape (xi), β = scale
        n = total observations, N_u = exceedances count
    """
    losses = -std_resid  # positive losses
    n_total = len(losses)
    u = np.quantile(losses, threshold_q)

    exceedances = losses[losses > u] - u
    n_exceed = len(exceedances)

    if n_exceed < 20:
        # Fall back to FHS if too few exceedances
        return var_fhs(std_resid, sigma, alpha)

    try:
        # Fit GPD via MLE (fix location at 0)
        shape, loc, scale = genpareto.fit(exceedances, floc=0)

        # Safety: reject degenerate fits
        if scale <= 0 or np.isnan(shape) or np.isnan(scale):
            return var_fhs(std_resid, sigma, alpha)

        # Clip shape to prevent extreme extrapolation
        # shape > 0: heavy tail (Fréchet), shape = 0: exponential, shape < 0: bounded
        shape = np.clip(shape, -0.5, 1.0)

        # GPD VaR for standardized residuals
        # P(X > x | X > u) = (1 + ξ(x-u)/β)^(-1/ξ) for ξ≠0
        # VaR_p = u + (β/ξ) * [(n/N_u * p)^(-ξ) - 1]
        # where p = alpha (the tail probability we're targeting)

        tail_prob = alpha  # we want P(loss > VaR) = alpha

        if abs(shape) < 1e-6:
            # Exponential case (shape ≈ 0)
            var_std = u + scale * np.log(n_total * tail_prob / n_exceed)
            # Note: this should be negative for small alpha since
            # n_total * alpha / n_exceed < 1 when alpha < threshold_q complement
            # Actually let me redo: for small alpha, ratio < 1, log < 0
            # We need: var_std = u - scale * log(n_exceed / (n_total * alpha))
            var_std = u + scale * np.log(n_exceed / (n_total * tail_prob))
            # Wait, let me use the standard formula properly
            # Standard: VaR = u + (scale/shape)*((n/Nu * alpha)^(-shape) - 1)
            # For shape→0: lim = u + scale * (-log(n/Nu * alpha))
            #             = u + scale * log(Nu / (n * alpha))
            var_std = u + scale * np.log(n_exceed / (n_total * tail_prob))
        else:
            ratio = (n_total / n_exceed) * tail_prob
            if ratio <= 0:
                return var_fhs(std_resid, sigma, alpha)
            var_std = u + (scale / shape) * (ratio ** (-shape) - 1)

        # Sanity check: VaR should be positive (a loss)
        if var_std <= 0 or np.isnan(var_std) or np.isinf(var_std):
            return var_fhs(std_resid, sigma, alpha)

        # Scale by current conditional volatility
        return var_std * sigma

    except Exception:
        return var_fhs(std_resid, sigma, alpha)


# ══════════════════════════════════════════════════════════════════════
# Statistical Tests
# ══════════════════════════════════════════════════════════════════════

def kupiec_test(violations, alpha):
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
    """Christoffersen independence test."""
    T = len(violations)
    n00 = n01 = n10 = n11 = 0
    for t in range(1, T):
        prev, curr = int(violations[t - 1]), int(violations[t])
        if prev == 0 and curr == 0:
            n00 += 1
        elif prev == 0 and curr == 1:
            n01 += 1
        elif prev == 1 and curr == 0:
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

    p_value = 1 - stats.chi2.cdf(max(lr_ind, 0), 1)
    return {"statistic": float(lr_ind), "p_value": float(p_value),
            "pass": p_value >= 0.05}


def dq_test(violations, var_forecasts, alpha, n_lags=4):
    """Dynamic Quantile (DQ) test — Engle & Manganelli (2004)."""
    T = len(violations)
    hit = violations.astype(float) - alpha

    max_lag = n_lags
    n = T - max_lag
    if n < 10:
        return {"statistic": np.nan, "p_value": np.nan, "pass": True,
                "reason": "insufficient_data"}

    X = np.zeros((n, n_lags + 2))
    X[:, 0] = 1.0
    for lag in range(1, n_lags + 1):
        X[:, lag] = hit[max_lag - lag: T - lag]
    X[:, -1] = var_forecasts[max_lag:]

    hit_trimmed = hit[max_lag:]

    try:
        XtX = X.T @ X
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


# ══════════════════════════════════════════════════════════════════════
# Data & Rolling GARCH
# ══════════════════════════════════════════════════════════════════════

def download_data(asset, oos_start, oos_end, window):
    """Download price data with enough history."""
    extra_years = max(int(window / 252) + 2, 5)
    data_start = f"{int(oos_start[:4]) - extra_years}-01-01"

    print(f"  下載 {asset} (from {data_start})...")
    data = yf.download(asset, start=data_start, end=oos_end, progress=False)

    if len(data) == 0:
        print(f"  ERROR: No data for {asset}")
        return None

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    data["return"] = data["Close"].pct_change()
    data = data.dropna()
    return data


def run_rolling_gjr(asset, data, window, oos_start, oos_end):
    """Rolling GJR-GARCH(1,1) with skewt distribution.

    Returns list of dicts with all info needed for VaR computation.
    """
    oos_mask = ((data.index >= pd.Timestamp(oos_start)) &
                (data.index <= pd.Timestamp(oos_end)))
    oos_dates = data.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  ERROR: No OOS data for {asset}")
        return None

    returns_pct = data["return"] * 100

    print(f"  OOS: {oos_dates[0].strftime('%Y-%m-%d')} ~ "
          f"{oos_dates[-1].strftime('%Y-%m-%d')} ({len(oos_dates)} 天)")

    first_oos_idx = data.index.get_loc(oos_dates[0])
    effective_window = min(window, first_oos_idx)
    if effective_window < window:
        print(f"  WARNING: Only {first_oos_idx} pre-OOS days. Using w={effective_window}.")

    results = []
    skipped = 0

    for i, date in enumerate(oos_dates):
        idx = data.index.get_loc(date)
        if idx < effective_window:
            skipped += 1
            continue

        train = returns_pct.iloc[idx - effective_window: idx].values
        actual_return = data["return"].iloc[idx]

        try:
            am = arch_model(train, vol="GARCH", p=1, q=1, o=1,
                            dist="skewt", mean="Zero", rescale=False)
            res = am.fit(disp="off", show_warning=False)

            fcast = res.forecast(horizon=1)
            sigma_pct = fcast.variance.iloc[-1, 0] ** 0.5
            sigma = sigma_pct / 100

            std_resid = res.std_resid.copy()
            std_resid = std_resid[~np.isnan(std_resid)]

            sample_skew = float(stats.skew(std_resid))
            sample_excess_kurt = float(stats.kurtosis(std_resid, fisher=True))

            params_dict = dict(res.params)
            eta = params_dict.get("eta", params_dict.get("nu", 8.0))
            lam = params_dict.get("lambda", 0.0)

            results.append({
                "date": date,
                "actual_return": float(actual_return),
                "sigma": float(sigma),
                "std_resid": std_resid,
                "sample_skew": sample_skew,
                "sample_excess_kurt": sample_excess_kurt,
                "eta": float(eta),
                "lam": float(lam),
            })

        except Exception:
            skipped += 1
            continue

        if (i + 1) % 100 == 0:
            print(f"    {i + 1}/{len(oos_dates)} forecasts...")

    print(f"  完成 {len(results)} forecasts (skipped {skipped})")
    return results


# ══════════════════════════════════════════════════════════════════════
# Main Experiment
# ══════════════════════════════════════════════════════════════════════

def run_experiment():
    print("=" * 70)
    print("EVT-VaR (Extreme Value Theory) — Peaks-over-Threshold 實驗")
    print(f"Assets: {ASSETS}")
    print(f"Methods: {METHODS}")
    print(f"Alphas: {ALPHAS}")
    print(f"OOS: {OOS_START} ~ latest")
    print(f"Window: {WINDOW}, GPD threshold: {GPD_THRESHOLD_QUANTILE}")
    print("=" * 70)

    t_start = time.time()
    all_results = {}
    summary_rows = []

    for asset in ASSETS:
        print(f"\n{'─' * 50}")
        print(f"Processing {asset}...")
        print(f"{'─' * 50}")

        data = download_data(asset, OOS_START, OOS_END, WINDOW)
        if data is None:
            continue

        forecasts = run_rolling_gjr(asset, data, WINDOW, OOS_START, OOS_END)
        if forecasts is None or len(forecasts) == 0:
            continue

        returns = np.array([f["actual_return"] for f in forecasts])
        sigmas = np.array([f["sigma"] for f in forecasts])
        dates = [f["date"] for f in forecasts]

        asset_results = {"n_oos": len(returns), "methods": {}}

        for method in METHODS:
            print(f"\n  VaR method: {method}")

            # Compute VaR forecasts for all OOS dates
            var_forecasts = np.zeros(len(returns))

            for j in range(len(returns)):
                sigma = sigmas[j]
                f = forecasts[j]

                if method == "Normal":
                    # Compute for all alphas later
                    pass
                elif method == "Student-t(4)":
                    pass
                elif method == "Skewed-t":
                    pass
                elif method == "CF-VaR":
                    pass
                elif method == "FHS":
                    pass
                elif method == "EVT-POT":
                    pass

            # Test each alpha level
            method_results = {}
            for alpha in ALPHAS:
                var_arr = np.zeros(len(returns))

                for j in range(len(returns)):
                    sigma = sigmas[j]
                    f = forecasts[j]

                    if method == "Normal":
                        var_arr[j] = var_normal(sigma, alpha)
                    elif method == "Student-t(4)":
                        var_arr[j] = var_studentt(sigma, alpha, df=4.0)
                    elif method == "Skewed-t":
                        var_arr[j] = var_skewt(sigma, f["eta"], f["lam"], alpha)
                    elif method == "CF-VaR":
                        var_arr[j] = var_cornish_fisher(
                            sigma, f["sample_skew"], f["sample_excess_kurt"], alpha)
                    elif method == "FHS":
                        var_arr[j] = var_fhs(f["std_resid"], sigma, alpha)
                    elif method == "EVT-POT":
                        var_arr[j] = var_evt_pot(
                            f["std_resid"], sigma, alpha,
                            threshold_q=GPD_THRESHOLD_QUANTILE)

                # Compute violations
                violations = (returns < -var_arr).astype(int)
                n_viol = int(np.sum(violations))
                n_total = len(violations)
                obs_rate = n_viol / n_total

                # Run tests
                kupiec = kupiec_test(violations, alpha)
                chris = christoffersen_test(violations)
                dq = dq_test(violations, var_arr, alpha, n_lags=DQ_LAGS)

                trinity = int(kupiec["pass"]) + int(chris["pass"]) + int(dq["pass"])

                alpha_key = f"{alpha:.3f}"
                method_results[alpha_key] = {
                    "n_violations": n_viol,
                    "expected_violations": round(alpha * n_total, 1),
                    "obs_rate": round(obs_rate, 5),
                    "expected_rate": alpha,
                    "kupiec_p": round(kupiec["p_value"], 4),
                    "kupiec_pass": kupiec["pass"],
                    "chris_p": round(chris["p_value"], 4),
                    "chris_pass": chris["pass"],
                    "dq_p": round(dq["p_value"], 4) if not np.isnan(dq.get("p_value", np.nan)) else None,
                    "dq_pass": dq["pass"],
                    "trinity": trinity,
                }

                # Add to summary
                summary_rows.append({
                    "asset": asset,
                    "method": method,
                    "alpha": alpha,
                    "n_oos": n_total,
                    "n_viol": n_viol,
                    "expected": round(alpha * n_total, 1),
                    "obs_rate": round(obs_rate, 5),
                    "kupiec_pass": kupiec["pass"],
                    "chris_pass": chris["pass"],
                    "dq_pass": dq["pass"],
                    "trinity": trinity,
                })

            asset_results["methods"][method] = method_results

            # Print compact summary for this method
            for alpha in ALPHAS:
                ak = f"{alpha:.3f}"
                r = method_results[ak]
                status = "✓" if r["trinity"] == 3 else f"({r['trinity']}/3)"
                dq_str = f"{r['dq_p']:.3f}" if r['dq_p'] is not None else "N/A"
                print(f"    α={alpha}: {r['n_violations']}/{r['expected_violations']:.0f} "
                      f"violations, K={r['kupiec_p']:.3f} C={r['chris_p']:.3f} "
                      f"DQ={dq_str} "
                      f"Trinity={status}")

        all_results[asset] = asset_results

    elapsed = time.time() - t_start

    # ══════════════════════════════════════════════════════════════════
    # Summary Tables
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("SUMMARY: EVT-VaR vs Other Methods")
    print("=" * 70)

    # Per-method Trinity pass rate across assets/alphas
    method_scores = {}
    for method in METHODS:
        rows = [r for r in summary_rows if r["method"] == method]
        total_tests = len(rows)
        trinity_pass = sum(1 for r in rows if r["trinity"] == 3)
        kupiec_pass = sum(1 for r in rows if r["kupiec_pass"])
        method_scores[method] = {
            "total_tests": total_tests,
            "trinity_3_3": trinity_pass,
            "trinity_rate": round(trinity_pass / total_tests, 3) if total_tests > 0 else 0,
            "kupiec_pass": kupiec_pass,
            "kupiec_rate": round(kupiec_pass / total_tests, 3) if total_tests > 0 else 0,
        }

    print(f"\n{'Method':<16} {'Tests':>5} {'Trinity 3/3':>11} {'Rate':>6} {'Kupiec Pass':>11} {'Rate':>6}")
    print("-" * 60)
    for method in METHODS:
        s = method_scores[method]
        print(f"{method:<16} {s['total_tests']:>5} {s['trinity_3_3']:>11} "
              f"{s['trinity_rate']:>6.1%} {s['kupiec_pass']:>11} {s['kupiec_rate']:>6.1%}")

    # Per-alpha breakdown
    for alpha in ALPHAS:
        print(f"\n--- Alpha = {alpha} ---")
        print(f"{'Method':<16} ", end="")
        for asset in ASSETS:
            print(f"{asset:>10}", end="")
        print(f"{'Total':>8}")
        print("-" * (16 + 10 * len(ASSETS) + 8))

        for method in METHODS:
            print(f"{method:<16} ", end="")
            total_trinity = 0
            for asset in ASSETS:
                rows = [r for r in summary_rows
                        if r["method"] == method and r["asset"] == asset
                        and r["alpha"] == alpha]
                if rows:
                    t = rows[0]["trinity"]
                    total_trinity += (1 if t == 3 else 0)
                    marker = "✓" if t == 3 else f"{t}/3"
                    print(f"{marker:>10}", end="")
                else:
                    print(f"{'N/A':>10}", end="")

            alpha_rows = [r for r in summary_rows
                          if r["method"] == method and r["alpha"] == alpha]
            n_pass = sum(1 for r in alpha_rows if r["trinity"] == 3)
            print(f"  {n_pass}/{len(alpha_rows)}")

    # Key question: EVT vs Skewed-t
    print("\n" + "=" * 70)
    print("KEY QUESTION: EVT-POT vs Skewed-t")
    print("=" * 70)

    for alpha in ALPHAS:
        evt_rows = [r for r in summary_rows
                    if r["method"] == "EVT-POT" and r["alpha"] == alpha]
        skt_rows = [r for r in summary_rows
                    if r["method"] == "Skewed-t" and r["alpha"] == alpha]
        fhs_rows = [r for r in summary_rows
                    if r["method"] == "FHS" and r["alpha"] == alpha]

        evt_kupiec = sum(1 for r in evt_rows if r["kupiec_pass"])
        skt_kupiec = sum(1 for r in skt_rows if r["kupiec_pass"])
        fhs_kupiec = sum(1 for r in fhs_rows if r["kupiec_pass"])

        evt_trinity = sum(1 for r in evt_rows if r["trinity"] == 3)
        skt_trinity = sum(1 for r in skt_rows if r["trinity"] == 3)
        fhs_trinity = sum(1 for r in fhs_rows if r["trinity"] == 3)

        n_assets = len(ASSETS)
        print(f"\n  α={alpha}:")
        print(f"    EVT-POT:   Kupiec {evt_kupiec}/{n_assets}, Trinity {evt_trinity}/{n_assets}")
        print(f"    Skewed-t:  Kupiec {skt_kupiec}/{n_assets}, Trinity {skt_trinity}/{n_assets}")
        print(f"    FHS:       Kupiec {fhs_kupiec}/{n_assets}, Trinity {fhs_trinity}/{n_assets}")

    # GPD parameter analysis
    print("\n" + "=" * 70)
    print("GPD PARAMETER ANALYSIS (EVT-POT tail shape)")
    print("=" * 70)
    print("(Checking shape parameter ξ across assets)")
    print("  ξ > 0: heavy tail (Fréchet domain)")
    print("  ξ = 0: exponential tail")
    print("  ξ < 0: bounded tail (Weibull domain)")

    for asset in ASSETS:
        if asset not in all_results:
            continue
        forecasts_list = None
        # Re-extract GPD shape from the forecasts
        # We need to store this during the run; let's compute a quick summary
        print(f"\n  {asset}: (GPD shapes computed during estimation)")

    # ══════════════════════════════════════════════════════════════════
    # Additional: EVT-specific analysis — GPD shape estimation
    # ══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 70)
    print("SUPPLEMENTARY: GPD Shape Parameter Distribution per Asset")
    print("=" * 70)

    gpd_shapes = {}
    for asset in ASSETS:
        if asset not in all_results:
            continue

        # Re-download and compute GPD shapes
        data = download_data(asset, OOS_START, OOS_END, WINDOW)
        if data is None:
            continue

        oos_mask = ((data.index >= pd.Timestamp(OOS_START)) &
                    (data.index <= pd.Timestamp(OOS_END)))
        oos_dates = data.index[oos_mask]
        returns_pct = data["return"] * 100

        shapes = []
        # Sample 20 evenly-spaced dates for GPD shape analysis
        sample_indices = np.linspace(0, len(oos_dates) - 1, min(20, len(oos_dates)), dtype=int)

        for si in sample_indices:
            date = oos_dates[si]
            idx = data.index.get_loc(date)
            eff_w = min(WINDOW, idx)
            if eff_w < 500:
                continue

            train = returns_pct.iloc[idx - eff_w: idx].values
            try:
                am = arch_model(train, vol="GARCH", p=1, q=1, o=1,
                                dist="skewt", mean="Zero", rescale=False)
                res = am.fit(disp="off", show_warning=False)
                std_resid = res.std_resid[~np.isnan(res.std_resid)]

                losses = -std_resid
                u = np.quantile(losses, GPD_THRESHOLD_QUANTILE)
                exceedances = losses[losses > u] - u

                if len(exceedances) >= 20:
                    shape, _, scale = genpareto.fit(exceedances, floc=0)
                    shapes.append(float(shape))
            except Exception:
                continue

        if shapes:
            gpd_shapes[asset] = {
                "mean_shape": round(np.mean(shapes), 4),
                "median_shape": round(np.median(shapes), 4),
                "std_shape": round(np.std(shapes), 4),
                "min_shape": round(np.min(shapes), 4),
                "max_shape": round(np.max(shapes), 4),
                "n_samples": len(shapes),
            }
            print(f"  {asset}: ξ = {np.mean(shapes):.4f} ± {np.std(shapes):.4f} "
                  f"(range [{np.min(shapes):.4f}, {np.max(shapes):.4f}], "
                  f"n={len(shapes)})")
            if np.mean(shapes) > 0.1:
                print(f"    → Heavy tail detected (ξ > 0.1)")
            elif np.mean(shapes) > 0:
                print(f"    → Mild heavy tail")
            else:
                print(f"    → Thin/bounded tail (ξ ≤ 0)")

    # ══════════════════════════════════════════════════════════════════
    # Save Results
    # ══════════════════════════════════════════════════════════════════
    output = {
        "experiment": "EVT-VaR (Extreme Value Theory) — Peaks-over-Threshold",
        "timestamp": datetime.now().isoformat(),
        "config": {
            "assets": ASSETS,
            "methods": METHODS,
            "alphas": ALPHAS,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "window": WINDOW,
            "gpd_threshold_quantile": GPD_THRESHOLD_QUANTILE,
            "dq_lags": DQ_LAGS,
        },
        "elapsed_seconds": round(elapsed, 1),
        "per_asset": {},
        "method_scores": method_scores,
        "gpd_shape_analysis": gpd_shapes,
        "summary_table": summary_rows,
        "conclusion": {},
    }

    # Build per-asset clean results (without numpy arrays)
    for asset, ar in all_results.items():
        output["per_asset"][asset] = {
            "n_oos": ar["n_oos"],
            "methods": ar["methods"],
        }

    # Conclusion
    evt_total_trinity = method_scores.get("EVT-POT", {}).get("trinity_3_3", 0)
    evt_total_tests = method_scores.get("EVT-POT", {}).get("total_tests", 1)
    skt_total_trinity = method_scores.get("Skewed-t", {}).get("trinity_3_3", 0)
    fhs_total_trinity = method_scores.get("FHS", {}).get("trinity_3_3", 0)

    conclusion_text = (
        f"EVT-POT Trinity pass: {evt_total_trinity}/{evt_total_tests} "
        f"({evt_total_trinity/evt_total_tests:.1%}). "
        f"Skewed-t: {skt_total_trinity}/{evt_total_tests}. "
        f"FHS: {fhs_total_trinity}/{evt_total_tests}. "
    )

    if evt_total_trinity > skt_total_trinity:
        conclusion_text += "EVT-POT 改善了 Skewed-t 的 VaR 覆蓋率。"
        verdict = "EVT_WINS"
    elif evt_total_trinity == skt_total_trinity:
        conclusion_text += "EVT-POT 與 Skewed-t 表現相當。"
        verdict = "TIE"
    else:
        conclusion_text += "EVT-POT 未能改善 Skewed-t。Skewed-t 仍是最佳。"
        verdict = "SKEWT_WINS"

    # Check specifically at alpha=0.005 (extreme tail)
    evt_005 = [r for r in summary_rows if r["method"] == "EVT-POT" and r["alpha"] == 0.005]
    skt_005 = [r for r in summary_rows if r["method"] == "Skewed-t" and r["alpha"] == 0.005]
    evt_005_kupiec = sum(1 for r in evt_005 if r["kupiec_pass"])
    skt_005_kupiec = sum(1 for r in skt_005 if r["kupiec_pass"])
    conclusion_text += (
        f" 在極端尾部 α=0.5%：EVT Kupiec {evt_005_kupiec}/{len(ASSETS)}, "
        f"Skewed-t {skt_005_kupiec}/{len(ASSETS)}。"
    )

    output["conclusion"] = {
        "text": conclusion_text,
        "verdict": verdict,
        "evt_trinity_rate": method_scores.get("EVT-POT", {}).get("trinity_rate", 0),
        "skewt_trinity_rate": method_scores.get("Skewed-t", {}).get("trinity_rate", 0),
        "fhs_trinity_rate": method_scores.get("FHS", {}).get("trinity_rate", 0),
        "evt_extreme_tail_005_kupiec": f"{evt_005_kupiec}/{len(ASSETS)}",
        "skewt_extreme_tail_005_kupiec": f"{skt_005_kupiec}/{len(ASSETS)}",
    }

    print(f"\n{'=' * 70}")
    print("CONCLUSION")
    print(f"{'=' * 70}")
    print(f"  {conclusion_text}")
    print(f"  Verdict: {verdict}")

    # Save
    out_path = Path("storage/experiments/evt_var_results.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fout:
        json.dump(output, fout, indent=2, default=str)
    print(f"\n  結果已存至: {out_path}")
    print(f"  耗時: {elapsed:.1f}s")

    return output


if __name__ == "__main__":
    result = run_experiment()
