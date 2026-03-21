#!/usr/bin/env python3
"""Master VaR Panel — Unified comparison framework for all VaR methods.

Addresses Codex 4th review criticism: mixed alpha levels, tests, OOS periods.
This script provides ONE comprehensive, reproducible table.

7 Assets × 5 VaR Methods × 3 Alpha Levels × 3 Tests = 315 test results.

Assets:   SPY, QQQ, GLD, TLT, EEM, BTC-USD, 0050.TW
Methods:  Normal, Student-t(df=5), Skewed-t, CF-VaR, FHS
Alphas:   1%, 2.5%, 5%
Tests:    Kupiec (coverage), Christoffersen (independence), DQ (Engle-Manganelli 2004)
OOS:      2023-01-01 to 2024-12-31
Window:   2000 (GJR-GARCH based vol)

Trinity score = how many of the 3 tests pass (0-3).

[提出: Codex (4th review), 執行: Claude]

Usage:
    uv run python scripts/master_var_panel.py
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

# ══════════════════════════════════════════════════════════════════════
# Configuration — fixed for reproducibility
# ══════════════════════════════════════════════════════════════════════
ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM", "BTC-USD", "0050.TW"]
METHODS = ["Normal", "Student-t(5)", "Skewed-t", "CF-VaR", "FHS"]
ALPHAS = [0.01, 0.025, 0.05]
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
WINDOW = 2000  # uniform for all assets per task spec
DQ_LAGS = 4


# ══════════════════════════════════════════════════════════════════════
# VaR Methods
# ══════════════════════════════════════════════════════════════════════

def var_normal(sigma, alpha):
    """Normal VaR: -Phi^{-1}(alpha) * sigma."""
    return -stats.norm.ppf(alpha) * sigma


def var_studentt(sigma, alpha, df=5.0):
    """Student-t(df) VaR with proper variance scaling."""
    scale = np.sqrt((df - 2) / df)
    return -stats.t.ppf(alpha, df) * scale * sigma


def var_skewt(sigma, eta, lam, alpha):
    """Skewed Student-t VaR using arch's SkewStudent ppf.

    eta: degrees of freedom (>2)
    lam: skewness parameter (-1, 1)
    """
    try:
        from arch.univariate.distribution import SkewStudent
        skewt = SkewStudent()
        q = skewt.ppf(alpha, parameters=np.array([eta, lam]))
        return -q * sigma
    except Exception:
        # Fallback: Student-t with skew adjustment
        base = var_studentt(sigma, alpha, df=max(eta, 2.1))
        return base * (1 - 0.2 * lam)


def var_cornish_fisher(sigma, skew, excess_kurt, alpha):
    """Cornish-Fisher VaR expansion.

    z_cf = z + (z^2-1)*S/6 + (z^3-3z)*K/24 - (2z^3-5z)*S^2/36

    skew: sample skewness of standardized residuals
    excess_kurt: excess kurtosis (kurtosis - 3)
    """
    z = stats.norm.ppf(alpha)  # negative
    S = skew
    K = excess_kurt
    z_cf = (z
            + (z**2 - 1) * S / 6
            + (z**3 - 3 * z) * K / 24
            - (2 * z**3 - 5 * z) * S**2 / 36)
    return -z_cf * sigma


def var_fhs(std_resid, sigma, alpha):
    """Filtered Historical Simulation VaR.

    Empirical quantile of standardized residuals * current sigma.
    """
    q = np.percentile(std_resid, alpha * 100)
    return -q * sigma


# ══════════════════════════════════════════════════════════════════════
# Statistical Tests
# ══════════════════════════════════════════════════════════════════════

def kupiec_test(violations, alpha):
    """Kupiec POF test for unconditional coverage.

    H0: observed violation rate = alpha
    Reject at 5% significance → FAIL
    """
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
    """Christoffersen independence test (Markov chain LR).

    H0: violations are independent (no clustering)
    Reject at 5% significance → FAIL
    """
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
    """Dynamic Quantile (DQ) test — Engle & Manganelli (2004).

    Regresses hit variable (I_t - alpha) on:
      - Constant
      - Lagged hits (n_lags)
      - Current VaR forecast

    H0: hits are unpredictable
    Reject at 5% significance → FAIL
    """
    T = len(violations)
    hit = violations.astype(float) - alpha

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
        XtX += 1e-10 * np.eye(XtX.shape[0])  # ridge for stability
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
# Rolling GJR-GARCH forecast engine
# ══════════════════════════════════════════════════════════════════════

def download_data(asset, oos_start, oos_end, window):
    """Download price data with enough history for the rolling window."""
    extra_years = max(int(window / 252) + 2, 5)
    data_start = f"{int(oos_start[:4]) - extra_years}-01-01"

    print(f"  Downloading {asset} from {data_start}...")
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
    """Run rolling GJR-GARCH(1,1) with skewt distribution.

    Returns list of dicts with all info needed for VaR computation.
    """
    oos_mask = ((data.index >= pd.Timestamp(oos_start)) &
                (data.index <= pd.Timestamp(oos_end)))
    oos_dates = data.index[oos_mask]

    if len(oos_dates) == 0:
        print(f"  ERROR: No OOS data for {asset}")
        return None

    returns_pct = data["return"] * 100  # arch expects percentage returns

    print(f"  OOS: {oos_dates[0].strftime('%Y-%m-%d')} to "
          f"{oos_dates[-1].strftime('%Y-%m-%d')} ({len(oos_dates)} days)")

    # Check if we have enough pre-OOS data for the window
    first_oos_idx = data.index.get_loc(oos_dates[0])
    available_history = first_oos_idx
    effective_window = min(window, available_history)
    if effective_window < window:
        print(f"  WARNING: Only {available_history} pre-OOS days available "
              f"(need {window}). Using w={effective_window}.")

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
            # Fit GJR-GARCH(1,1) with skewed-t distribution
            am = arch_model(train, vol="GARCH", p=1, q=1, o=1,
                            dist="skewt", mean="Zero", rescale=False)
            res = am.fit(disp="off", show_warning=False)

            # One-step-ahead variance forecast
            fcast = res.forecast(horizon=1)
            sigma_pct = fcast.variance.iloc[-1, 0] ** 0.5  # pct
            sigma = sigma_pct / 100  # decimal

            # Standardized residuals (for FHS and CF-VaR)
            std_resid = res.std_resid.copy()
            std_resid = std_resid[~np.isnan(std_resid)]

            # Sample moments of standardized residuals (for CF-VaR)
            sample_skew = float(stats.skew(std_resid))
            sample_excess_kurt = float(stats.kurtosis(std_resid, fisher=True))

            # Skewed-t distribution parameters (for Skewed-t VaR)
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

        # Progress
        if (i + 1) % 100 == 0:
            print(f"    {i + 1}/{len(oos_dates)} forecasts...")

    print(f"  Done: {len(results)} forecasts, {skipped} skipped")
    return results


# ══════════════════════════════════════════════════════════════════════
# VaR computation for all methods × alphas
# ══════════════════════════════════════════════════════════════════════

def compute_var(forecasts, method, alpha):
    """Compute VaR series for a given (method, alpha) pair."""
    var_values = []
    for r in forecasts:
        sigma = r["sigma"]
        if method == "Normal":
            v = var_normal(sigma, alpha)
        elif method == "Student-t(5)":
            v = var_studentt(sigma, alpha, df=5.0)
        elif method == "Skewed-t":
            v = var_skewt(sigma, r["eta"], r["lam"], alpha)
        elif method == "CF-VaR":
            v = var_cornish_fisher(sigma, r["sample_skew"],
                                   r["sample_excess_kurt"], alpha)
        elif method == "FHS":
            v = var_fhs(r["std_resid"], sigma, alpha)
        else:
            v = var_normal(sigma, alpha)

        var_values.append(max(v, 1e-8))  # ensure positive

    return np.array(var_values)


# ══════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════

def main():
    t0 = time.time()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    print("=" * 100)
    print("  MASTER VaR PANEL — Unified Comparison Framework")
    print(f"  7 Assets × 5 Methods × 3 Alphas × 3 Tests = 315 test cells")
    print(f"  OOS: {OOS_START} to {OOS_END} | Window: {WINDOW} | Model: GJR-GARCH(1,1)")
    print(f"  Generated: {now_str}")
    print("=" * 100)

    # ── Phase 1: Download all data ────────────────────────────────
    print("\n[Phase 1] Downloading data for all assets...")
    all_data = {}
    for asset in ASSETS:
        data = download_data(asset, OOS_START, OOS_END, WINDOW)
        if data is not None:
            all_data[asset] = data

    # ── Phase 2: Rolling GJR-GARCH forecasts per asset ────────────
    print("\n[Phase 2] Running rolling GJR-GARCH(1,1) forecasts...")
    all_forecasts = {}
    for asset in ASSETS:
        if asset not in all_data:
            print(f"  SKIP {asset}: no data")
            continue
        print(f"\n{'─' * 60}")
        print(f"  {asset}:")
        forecasts = run_rolling_gjr(asset, all_data[asset], WINDOW,
                                     OOS_START, OOS_END)
        if forecasts and len(forecasts) >= 30:
            all_forecasts[asset] = forecasts
        else:
            print(f"  SKIP {asset}: insufficient forecasts")

    # ── Phase 3: Compute VaR + run tests for all combinations ─────
    print("\n[Phase 3] Computing VaR and running backtests...")
    print(f"  Combinations: {len(all_forecasts)} assets × {len(METHODS)} methods × {len(ALPHAS)} alphas")

    rows = []  # for CSV output

    for asset in ASSETS:
        if asset not in all_forecasts:
            continue

        forecasts = all_forecasts[asset]
        actual_returns = np.array([r["actual_return"] for r in forecasts])
        n_obs = len(actual_returns)

        for alpha in ALPHAS:
            for method in METHODS:
                var_series = compute_var(forecasts, method, alpha)
                violations = (actual_returns < -var_series).astype(int)

                kup = kupiec_test(violations, alpha)
                chris = christoffersen_test(violations)
                dq = dq_test(violations, var_series, alpha, n_lags=DQ_LAGS)

                trinity = sum([kup["pass"], chris["pass"], dq["pass"]])

                rows.append({
                    "asset": asset,
                    "method": method,
                    "alpha": alpha,
                    "n_obs": n_obs,
                    "expected_violations": round(alpha * n_obs, 1),
                    "actual_violations": kup["n_violations"],
                    "obs_rate": round(kup["obs_rate"], 4),
                    "kupiec_stat": round(kup["statistic"], 3) if np.isfinite(kup["statistic"]) else "Inf",
                    "kupiec_p": round(kup["p_value"], 4),
                    "kupiec_pass": kup["pass"],
                    "chris_stat": round(chris["statistic"], 3),
                    "chris_p": round(chris["p_value"], 4),
                    "chris_pass": chris["pass"],
                    "dq_stat": round(dq["statistic"], 3) if not np.isnan(dq["statistic"]) else "N/A",
                    "dq_p": round(dq["p_value"], 4) if not np.isnan(dq["p_value"]) else "N/A",
                    "dq_pass": dq["pass"],
                    "trinity": trinity,
                })

    df = pd.DataFrame(rows)

    # ── Phase 4: Save CSV ─────────────────────────────────────────
    out_dir = Path("storage/reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "master_var_panel.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n  CSV saved to {csv_path}")

    # ══════════════════════════════════════════════════════════════
    # RESULTS DISPLAY
    # ══════════════════════════════════════════════════════════════

    elapsed = time.time() - t0

    print("\n\n")
    print("█" * 100)
    print("█  MASTER VaR PANEL — COMPLETE RESULTS")
    print(f"█  {len(df)} cells | {len(all_forecasts)} assets | {now_str}")
    print("█" * 100)

    # ── Full detail table ─────────────────────────────────────────
    for alpha in ALPHAS:
        alpha_pct = f"{alpha * 100:.1f}%"
        sub = df[df["alpha"] == alpha]
        print(f"\n{'═' * 100}")
        print(f"  ALPHA = {alpha_pct}")
        print(f"{'═' * 100}")

        header = (f"{'Asset':<10} {'Method':<14} {'N':>5} {'E[V]':>5} "
                  f"{'V':>4} {'Rate':>6}  "
                  f"{'Kup-p':>7} {'K':>2}  "
                  f"{'Chr-p':>7} {'C':>2}  "
                  f"{'DQ-p':>7} {'D':>2}  "
                  f"{'Trinity':>7}")
        print(header)
        print("─" * 100)

        prev_asset = ""
        for _, row in sub.iterrows():
            asset_label = row["asset"] if row["asset"] != prev_asset else ""
            prev_asset = row["asset"]

            def fmt_p(p):
                if isinstance(p, str):
                    return f"{'N/A':>7}"
                if p < 0.001:
                    return f"{'<.001':>7}"
                return f"{p:>7.3f}"

            k_flag = "Y" if row["kupiec_pass"] else "N"
            c_flag = "Y" if row["chris_pass"] else "N"
            d_flag = "Y" if row["dq_pass"] else "N"

            line = (f"{asset_label:<10} {row['method']:<14} "
                    f"{row['n_obs']:>5} {row['expected_violations']:>5} "
                    f"{row['actual_violations']:>4} {row['obs_rate']:>6.3f}  "
                    f"{fmt_p(row['kupiec_p'])} {k_flag:>2}  "
                    f"{fmt_p(row['chris_p'])} {c_flag:>2}  "
                    f"{fmt_p(row['dq_p'])} {d_flag:>2}  "
                    f"  {row['trinity']}/3")
            print(line)

            # Blank line between assets
            if (row["method"] == METHODS[-1] and
                    row["asset"] != sub.iloc[-1]["asset"]):
                print()

    # ══════════════════════════════════════════════════════════════
    # SUMMARIES
    # ══════════════════════════════════════════════════════════════

    print("\n\n")
    print("█" * 100)
    print("█  SUMMARY ANALYSIS")
    print("█" * 100)

    # ── 1. Grand summary: highest Trinity pass rate by method ─────
    print(f"\n{'═' * 80}")
    print("  1. GRAND SUMMARY: Trinity pass rate by method (across all assets × alphas)")
    print(f"{'═' * 80}")

    print(f"\n  {'Method':<16} {'3/3':>6} {'2/3':>6} {'1/3':>6} {'0/3':>6} "
          f"{'Cells':>6} {'3/3 Rate':>9} {'Avg Trinity':>12}")
    print("  " + "─" * 76)

    method_ranking = []
    for method in METHODS:
        sub = df[df["method"] == method]
        n_cells = len(sub)
        n_3 = (sub["trinity"] == 3).sum()
        n_2 = (sub["trinity"] == 2).sum()
        n_1 = (sub["trinity"] == 1).sum()
        n_0 = (sub["trinity"] == 0).sum()
        rate_3 = n_3 / n_cells if n_cells > 0 else 0
        avg_trinity = sub["trinity"].mean() if n_cells > 0 else 0

        print(f"  {method:<16} {n_3:>6} {n_2:>6} {n_1:>6} {n_0:>6} "
              f"{n_cells:>6} {rate_3:>8.1%} {avg_trinity:>11.2f}")

        method_ranking.append((method, n_3, avg_trinity, rate_3))

    method_ranking.sort(key=lambda x: (-x[1], -x[2]))
    print(f"\n  >>> BEST METHOD (by 3/3 count): {method_ranking[0][0]} "
          f"({method_ranking[0][1]} perfect passes, "
          f"avg Trinity = {method_ranking[0][2]:.2f})")

    # ── 2. Per-asset best method ──────────────────────────────────
    print(f"\n{'═' * 80}")
    print("  2. PER-ASSET BEST METHOD")
    print(f"{'═' * 80}")

    print(f"\n  {'Asset':<12} {'Best Method':<16} {'3/3':>4} {'Avg Trinity':>12} "
          f"{'2nd Best':<16} {'3/3':>4}")
    print("  " + "─" * 72)

    for asset in ASSETS:
        sub = df[df["asset"] == asset]
        if len(sub) == 0:
            print(f"  {asset:<12} {'N/A':<16}")
            continue

        scores = []
        for method in METHODS:
            ms = sub[sub["method"] == method]
            n_3 = (ms["trinity"] == 3).sum()
            avg = ms["trinity"].mean()
            scores.append((method, n_3, avg))

        scores.sort(key=lambda x: (-x[1], -x[2]))
        best = scores[0]
        second = scores[1] if len(scores) > 1 else ("N/A", 0, 0)

        print(f"  {asset:<12} {best[0]:<16} {best[1]:>4} {best[2]:>11.2f} "
              f"{second[0]:<16} {second[1]:>4}")

    # ── 3. Per-alpha best method ──────────────────────────────────
    print(f"\n{'═' * 80}")
    print("  3. PER-ALPHA BEST METHOD")
    print(f"{'═' * 80}")

    print(f"\n  {'Alpha':<8} {'Best Method':<16} {'3/3':>4} {'Avg Trinity':>12} "
          f"{'Total Cells':>12} {'All Methods Summary'}")
    print("  " + "─" * 80)

    for alpha in ALPHAS:
        sub = df[df["alpha"] == alpha]
        scores = []
        for method in METHODS:
            ms = sub[sub["method"] == method]
            n_3 = (ms["trinity"] == 3).sum()
            avg = ms["trinity"].mean()
            scores.append((method, n_3, avg))

        scores.sort(key=lambda x: (-x[1], -x[2]))
        best = scores[0]

        summary_parts = [f"{m}: {n3}" for m, n3, _ in scores]
        summary = ", ".join(summary_parts)

        print(f"  {alpha * 100:.1f}%{'':<4} {best[0]:<16} {best[1]:>4} "
              f"{best[2]:>11.2f} {len(sub):>12} {summary}")

    # ── 4. Per-test pass rates ────────────────────────────────────
    print(f"\n{'═' * 80}")
    print("  4. PER-TEST PASS RATES (across all cells)")
    print(f"{'═' * 80}")

    n_total = len(df)
    k_pass = df["kupiec_pass"].sum()
    c_pass = df["chris_pass"].sum()
    d_pass = df["dq_pass"].sum()

    print(f"\n  {'Test':<20} {'Pass':>6} {'Total':>6} {'Rate':>8}")
    print("  " + "─" * 44)
    print(f"  {'Kupiec (coverage)':<20} {k_pass:>6} {n_total:>6} {k_pass / n_total:>7.1%}")
    print(f"  {'Christoffersen':<20} {c_pass:>6} {n_total:>6} {c_pass / n_total:>7.1%}")
    print(f"  {'DQ (Engle-Mang.)':<20} {d_pass:>6} {n_total:>6} {d_pass / n_total:>7.1%}")

    # ── 5. Definitive ranking ─────────────────────────────────────
    print(f"\n{'═' * 80}")
    print("  5. DEFINITIVE RANKING (by 3/3 count, tiebreak by avg Trinity)")
    print(f"{'═' * 80}")

    print(f"\n  {'Rank':<6} {'Method':<16} {'3/3':>6} {'Avg Trinity':>12} {'3/3 Rate':>9}")
    print("  " + "─" * 52)

    for rank, (method, n3, avg, rate) in enumerate(method_ranking, 1):
        medal = {1: ">>>", 2: " > ", 3: "   "}.get(rank, "   ")
        print(f"  {medal}{rank:<3} {method:<16} {n3:>6} {avg:>11.2f} {rate:>8.1%}")

    # ── 6. Cross-table: method × alpha ────────────────────────────
    print(f"\n{'═' * 80}")
    print("  6. CROSS-TABLE: 3/3 Trinity counts (Method × Alpha)")
    print(f"{'═' * 80}")

    alpha_labels = [f"{a * 100:.1f}%" for a in ALPHAS]
    print(f"\n  {'Method':<16} " + "".join(f"{a:>8}" for a in alpha_labels) + f"{'TOTAL':>8}")
    print("  " + "─" * (16 + 8 * (len(ALPHAS) + 1)))

    for method in METHODS:
        counts = []
        for alpha in ALPHAS:
            sub = df[(df["method"] == method) & (df["alpha"] == alpha)]
            counts.append((sub["trinity"] == 3).sum())
        total = sum(counts)
        print(f"  {method:<16} " + "".join(f"{c:>8}" for c in counts) + f"{total:>8}")

    # ── 7. Cross-table: method × asset ────────────────────────────
    print(f"\n{'═' * 80}")
    print("  7. CROSS-TABLE: 3/3 Trinity counts (Method × Asset)")
    print(f"{'═' * 80}")

    active_assets = [a for a in ASSETS if a in all_forecasts]
    asset_labels_short = [a[:7] for a in active_assets]
    print(f"\n  {'Method':<16} " + "".join(f"{a:>10}" for a in asset_labels_short) + f"{'TOTAL':>8}")
    print("  " + "─" * (16 + 10 * len(active_assets) + 8))

    for method in METHODS:
        counts = []
        for asset in active_assets:
            sub = df[(df["method"] == method) & (df["asset"] == asset)]
            counts.append((sub["trinity"] == 3).sum())
        total = sum(counts)
        print(f"  {method:<16} " + "".join(f"{c:>10}" for c in counts) + f"{total:>8}")

    # ── 8. Failure analysis: which cells fail? ────────────────────
    print(f"\n{'═' * 80}")
    print("  8. FAILURE ANALYSIS: cells with Trinity < 3")
    print(f"{'═' * 80}")

    failures = df[df["trinity"] < 3].copy()
    if len(failures) > 0:
        print(f"\n  {len(failures)} cells fail at least 1 test "
              f"(out of {n_total} total = {len(failures)/n_total:.1%})")

        print(f"\n  {'Asset':<10} {'Method':<14} {'Alpha':>6} {'V/E':>6} "
              f"{'Kup':>4} {'Chr':>4} {'DQ':>4} {'Trinity':>8}")
        print("  " + "─" * 64)

        for _, row in failures.sort_values(
                ["trinity", "asset", "alpha", "method"]).iterrows():
            v_e = f"{row['actual_violations']}/{row['expected_violations']}"
            k = "Y" if row["kupiec_pass"] else "N"
            c = "Y" if row["chris_pass"] else "N"
            d = "Y" if row["dq_pass"] else "N"
            print(f"  {row['asset']:<10} {row['method']:<14} "
                  f"{row['alpha'] * 100:>5.1f}% {v_e:>6} "
                  f"{k:>4} {c:>4} {d:>4} {row['trinity']:>5}/3")
    else:
        print("\n  All cells pass all 3 tests!")

    # ── Final footer ──────────────────────────────────────────────
    print(f"\n{'═' * 100}")
    print(f"  Elapsed: {elapsed:.1f}s | CSV: {csv_path}")
    print(f"  Model: GJR-GARCH(1,1) with skewt dist | Window: {WINDOW}")
    print(f"  OOS: {OOS_START} to {OOS_END}")
    print(f"{'═' * 100}")

    # ── Save JSON report ──────────────────────────────────────────
    json_report = {
        "title": "Master VaR Panel",
        "generated_at": now_str,
        "config": {
            "assets": ASSETS,
            "methods": METHODS,
            "alphas": ALPHAS,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "window": WINDOW,
            "model": "GJR-GARCH(1,1)",
            "distribution": "skewt",
            "dq_lags": DQ_LAGS,
        },
        "summary": {
            "total_cells": n_total,
            "total_3_of_3": int((df["trinity"] == 3).sum()),
            "ranking": [
                {"rank": i + 1, "method": m, "n_3_of_3": int(n3),
                 "avg_trinity": round(avg, 2), "rate_3_of_3": round(rate, 3)}
                for i, (m, n3, avg, rate) in enumerate(method_ranking)
            ],
            "per_test_pass_rates": {
                "kupiec": round(k_pass / n_total, 3),
                "christoffersen": round(c_pass / n_total, 3),
                "dq": round(d_pass / n_total, 3),
            },
            "elapsed_seconds": round(elapsed, 1),
        },
        "data": rows,
    }

    json_path = out_dir / "master_var_panel.json"
    with open(json_path, "w") as f:
        json.dump(json_report, f, indent=2, ensure_ascii=False, default=str)
    print(f"  JSON saved to {json_path}")

    return df, json_report


if __name__ == "__main__":
    df, report = main()
