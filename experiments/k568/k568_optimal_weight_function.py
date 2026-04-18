#!/usr/bin/env python3
"""K568: Optimal VT Weight Function — Is 12/VIX truly the best weight formula?
=============================================================================

Research question: Is the linear 1/VIX relationship optimal, or does a nonlinear
mapping better capture the VIX-to-weight relationship?

Motivation:
  - 12/VIX has been confirmed irreducible 9+ times, but always testing OVERLAYS
  - No prior experiment has questioned the FUNCTIONAL FORM itself
  - 12/VIX is linear in 1/VIX; what about sqrt, log, exp, sigmoid, piecewise, power?

Related experiments:
  - K23: Multi-period VT = mathematical non-issue (sqrt(h) cancels)
  - K275: Complete case for 50/50 SPY/GLD + 12/VIX
  - K499: Optimal VT rebalancing frequency
  - K503: VIX mean-reversion strategy — 12/VIX IS the MR trade
  - K524: Decision-focused policy grid search, 0 survive BH correction
  - K533: HAR best predictor but worst VT strategy
  - K540: HAR-VIX ensemble VT, 5 strategies fail
  - K544: Tail hedge efficiency — 12/VIX IS the tail hedge

Weight functions tested (all capped at [0, 1]):
  a. Linear:         w = c / VIX              (c = 10, 11, 12, 13, 14)
  b. Square root:    w = c / sqrt(VIX)         (c optimized)
  c. Logarithmic:    w = c / ln(VIX)           (c optimized)
  d. Exp decay:      w = exp(-VIX / c)          (c optimized)
  e. Sigmoid:        w = 1 / (1 + exp((VIX - c1) / c2))  (c1, c2 optimized)
  f. Piecewise:      w = 1 if VIX<c1, linear ramp to 0 if c1<VIX<c2, 0 if VIX>c2
  g. Power:          w = (c / VIX)^p            (p = 0.5, 1.0, 1.5, 2.0)

Methodology:
  1. Data: SPY + GLD + VIX from yfinance (2005-2026)
  2. In-sample optimization (2005-2017) for each function family
  3. OOS evaluation (2018-2026) — single long OOS
  4. Cross-OOS: 3 non-overlapping periods for robustness
  5. DM test vs 12/VIX benchmark (Harvey t>3.0)
  6. Metrics: Sharpe, MDD, Calmar, net Sharpe (after TX cost)

References:
  - Moreira & Muir (2017, JoF): Volatility-managed portfolios
  - Fleming, Kirby & Ostdiek (2001, JFE): Economic value of volatility timing
  - Kirby & Ostdiek (2012, JFE): It's all in the timing
  - Harvey (2016, JoF): ... and the cross-section of expected returns (t>3 threshold)

Data source: yfinance (SPY, GLD, ^VIX)
Author: [Proposed: User, Executed: Claude]

Usage:
    uv run python experiments/k568_optimal_weight_function.py
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import optimize, stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ============================================================
#  Constants & Configuration
# ============================================================
TARGET_VOL = 0.12  # 12% annualized target volatility
TX_COST = 0.001    # 0.1% one-way transaction cost
ANNUALIZE = np.sqrt(252)
RF_ANNUAL = 0.02   # Risk-free rate for Sharpe

# Training / OOS split
TRAIN_END = "2017-12-31"
OOS_START = "2018-01-01"

# Cross-OOS periods (3 non-overlapping)
CROSS_OOS = {
    "OOS_A_2012_2015": ("2012-01-01", "2015-12-31"),
    "OOS_B_2016_2019": ("2016-01-01", "2019-12-31"),
    "OOS_C_2020_2024": ("2020-01-01", "2024-12-31"),
}


# ============================================================
#  Weight Function Definitions
# ============================================================
def w_linear(vix: np.ndarray, c: float) -> np.ndarray:
    """Linear: w = c / VIX"""
    return np.clip(c / vix, 0.0, 1.0)


def w_sqrt(vix: np.ndarray, c: float) -> np.ndarray:
    """Square root: w = c / sqrt(VIX)"""
    return np.clip(c / np.sqrt(vix), 0.0, 1.0)


def w_log(vix: np.ndarray, c: float) -> np.ndarray:
    """Logarithmic: w = c / ln(VIX)"""
    return np.clip(c / np.log(vix), 0.0, 1.0)


def w_exp(vix: np.ndarray, c: float) -> np.ndarray:
    """Exponential decay: w = exp(-VIX / c)"""
    return np.clip(np.exp(-vix / c), 0.0, 1.0)


def w_sigmoid(vix: np.ndarray, c1: float, c2: float) -> np.ndarray:
    """Sigmoid: w = 1 / (1 + exp((VIX - c1) / c2))"""
    z = (vix - c1) / max(c2, 0.1)
    return np.clip(1.0 / (1.0 + np.exp(z)), 0.0, 1.0)


def w_piecewise(vix: np.ndarray, c1: float, c2: float) -> np.ndarray:
    """Piecewise linear: 1 if VIX<c1, ramp down to 0, 0 if VIX>c2"""
    c1, c2 = min(c1, c2 - 1), max(c1 + 1, c2)  # ensure c1 < c2
    w = np.where(vix < c1, 1.0,
                 np.where(vix > c2, 0.0,
                          (c2 - vix) / (c2 - c1)))
    return np.clip(w, 0.0, 1.0)


def w_power(vix: np.ndarray, c: float, p: float) -> np.ndarray:
    """Power: w = (c / VIX)^p"""
    return np.clip((c / vix) ** p, 0.0, 1.0)


# ============================================================
#  Data Loading
# ============================================================
def load_data() -> pd.DataFrame:
    """Load SPY, GLD, VIX from yfinance."""
    print("Downloading data from yfinance...")
    tickers = ["SPY", "GLD", "^VIX"]
    data = yf.download(tickers, start="2004-11-01", end="2026-03-27",
                       auto_adjust=True, progress=False)

    # Handle multi-level columns
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data

    df = pd.DataFrame({
        "SPY": close["SPY"],
        "GLD": close["GLD"],
        "VIX": close["^VIX"],
    }).dropna()

    # Daily returns
    df["r_SPY"] = np.log(df["SPY"] / df["SPY"].shift(1))
    df["r_GLD"] = np.log(df["GLD"] / df["GLD"].shift(1))

    # 50/50 portfolio return (equal weight between SPY and GLD)
    df["r_port"] = 0.5 * df["r_SPY"] + 0.5 * df["r_GLD"]

    df = df.dropna()
    print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")
    return df


# ============================================================
#  Strategy Evaluation
# ============================================================
def compute_vt_returns(df: pd.DataFrame, weights: np.ndarray,
                       tx_cost: float = TX_COST) -> dict:
    """Compute VT strategy returns given weight series."""
    r_port = df["r_port"].values
    n = len(r_port)

    # Transaction cost = proportional to absolute weight change
    w_chg = np.abs(np.diff(weights, prepend=weights[0]))
    cost = w_chg * tx_cost

    # VT return: w * r_port - cost
    r_vt = weights * r_port - cost

    # Metrics
    ann_ret = np.mean(r_vt) * 252
    ann_vol = np.std(r_vt) * ANNUALIZE
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = np.cumsum(r_vt)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    mdd = np.min(dd)

    calmar = ann_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Net Sharpe (already includes TX)
    net_sharpe = sharpe

    # Gross Sharpe (without TX)
    r_vt_gross = weights * r_port
    ann_ret_gross = np.mean(r_vt_gross) * 252
    ann_vol_gross = np.std(r_vt_gross) * ANNUALIZE
    gross_sharpe = (ann_ret_gross - RF_ANNUAL) / ann_vol_gross if ann_vol_gross > 0 else 0

    return {
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "gross_sharpe": float(gross_sharpe),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "avg_weight": float(np.mean(weights)),
        "weight_std": float(np.std(weights)),
        "n_days": int(n),
        "turnover": float(np.mean(w_chg) * 252),
    }


def dm_test(e1: np.ndarray, e2: np.ndarray) -> tuple[float, float]:
    """Diebold-Mariano test for Sharpe ratio comparison.
    Uses return differentials, HAC standard errors."""
    d = e1 - e2  # loss differential
    n = len(d)
    d_mean = np.mean(d)

    # Newey-West HAC variance (lag = int(n^(1/3)))
    lag = max(1, int(n ** (1 / 3)))
    gamma_0 = np.var(d)
    gamma_sum = 0
    for j in range(1, lag + 1):
        gamma_j = np.cov(d[j:], d[:-j])[0, 1]
        gamma_sum += 2 * (1 - j / (lag + 1)) * gamma_j

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0

    t_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# ============================================================
#  Optimization: Find best parameters for each weight function
# ============================================================
def optimize_sharpe(df_train: pd.DataFrame, weight_fn, param_grid: list[dict],
                    label: str) -> dict:
    """Grid search over parameter grid, maximize IS Sharpe."""
    best = {"sharpe": -999, "params": None, "label": label}

    for params in param_grid:
        vix = df_train["VIX"].values
        if "p" in params:
            w = weight_fn(vix, params["c"], params["p"])
        elif "c2" in params:
            w = weight_fn(vix, params["c1"], params["c2"])
        else:
            w = weight_fn(vix, params["c"])

        metrics = compute_vt_returns(df_train, w, tx_cost=0)  # no TX in IS
        if metrics["sharpe"] > best["sharpe"]:
            best["sharpe"] = metrics["sharpe"]
            best["params"] = params
            best["metrics"] = metrics

    return best


def build_param_grids() -> list[tuple[str, callable, list[dict]]]:
    """Build parameter grids for all weight function families."""
    families = []

    # a. Linear: w = c / VIX
    families.append(("Linear (c/VIX)", w_linear,
                     [{"c": c} for c in np.arange(6, 20.1, 0.5)]))

    # b. Square root: w = c / sqrt(VIX)
    families.append(("Sqrt (c/sqrt(VIX))", w_sqrt,
                     [{"c": c} for c in np.arange(0.5, 6.1, 0.25)]))

    # c. Logarithmic: w = c / ln(VIX)
    families.append(("Log (c/ln(VIX))", w_log,
                     [{"c": c} for c in np.arange(0.5, 5.1, 0.25)]))

    # d. Exponential decay: w = exp(-VIX / c)
    families.append(("Exp decay (exp(-VIX/c))", w_exp,
                     [{"c": c} for c in np.arange(5, 50.1, 1.0)]))

    # e. Sigmoid: w = 1 / (1 + exp((VIX - c1) / c2))
    sigmoid_grid = []
    for c1 in np.arange(10, 35.1, 2.5):
        for c2 in np.arange(1, 12.1, 1.0):
            sigmoid_grid.append({"c1": c1, "c2": c2})
    families.append(("Sigmoid", w_sigmoid, sigmoid_grid))

    # f. Piecewise linear
    pw_grid = []
    for c1 in np.arange(10, 22.1, 2.0):
        for c2 in np.arange(20, 45.1, 2.5):
            if c2 > c1 + 2:
                pw_grid.append({"c1": c1, "c2": c2})
    families.append(("Piecewise linear", w_piecewise, pw_grid))

    # g. Power: w = (c / VIX)^p
    power_grid = []
    for c in np.arange(6, 20.1, 1.0):
        for p in [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0]:
            power_grid.append({"c": c, "p": p})
    power_grid_list = power_grid
    families.append(("Power ((c/VIX)^p)", w_power, power_grid_list))

    return families


# ============================================================
#  Main Experiment
# ============================================================
def run_experiment():
    t0 = time.time()
    results = {
        "experiment_id": "K568",
        "title": "Optimal VT Weight Function — Is 12/VIX truly the best weight formula?",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "methodology": "Grid search IS optimization + single long OOS + 3-period cross-OOS + DM test",
        "references": [
            "Moreira & Muir (2017, JoF): Volatility-managed portfolios",
            "Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing",
            "Kirby & Ostdiek (2012, JFE): It's all in the timing",
            "Harvey (2016, JoF): t>3 threshold for multiple testing",
        ],
    }

    # Load data
    df = load_data()

    # Descriptive stats on VIX
    vix = df["VIX"]
    vix_stats = {
        "mean": float(vix.mean()),
        "median": float(vix.median()),
        "std": float(vix.std()),
        "min": float(vix.min()),
        "max": float(vix.max()),
        "skew": float(vix.skew()),
        "kurtosis": float(vix.kurtosis()),
        "q25": float(vix.quantile(0.25)),
        "q75": float(vix.quantile(0.75)),
    }
    results["vix_descriptive"] = vix_stats
    print(f"\nVIX: mean={vix_stats['mean']:.1f}, median={vix_stats['median']:.1f}, "
          f"range=[{vix_stats['min']:.1f}, {vix_stats['max']:.1f}]")

    # Split data
    df_train = df[df.index <= TRAIN_END].copy()
    df_oos = df[df.index >= OOS_START].copy()
    results["train_period"] = f"{df_train.index[0].strftime('%Y-%m-%d')} to {df_train.index[-1].strftime('%Y-%m-%d')}"
    results["oos_period"] = f"{df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')}"
    results["train_n"] = len(df_train)
    results["oos_n"] = len(df_oos)
    print(f"Train: {results['train_period']} (N={len(df_train)})")
    print(f"OOS:   {results['oos_period']} (N={len(df_oos)})")

    # ========================================
    # BENCHMARK: 12/VIX
    # ========================================
    print("\n" + "=" * 70)
    print("BENCHMARK: 12/VIX")
    print("=" * 70)
    w_bench_train = w_linear(df_train["VIX"].values, 12.0)
    w_bench_oos = w_linear(df_oos["VIX"].values, 12.0)
    bench_train = compute_vt_returns(df_train, w_bench_train)
    bench_oos = compute_vt_returns(df_oos, w_bench_oos)
    print(f"  IS  Sharpe: {bench_train['sharpe']:.4f}, MDD: {bench_train['mdd']:.4f}")
    print(f"  OOS Sharpe: {bench_oos['sharpe']:.4f}, MDD: {bench_oos['mdd']:.4f}")
    results["benchmark_12_vix"] = {
        "is_metrics": bench_train,
        "oos_metrics": bench_oos,
    }

    # Buy-and-hold 50/50 (no VT) for reference
    w_bh = np.ones(len(df_oos))
    bh_oos = compute_vt_returns(df_oos, w_bh, tx_cost=0)
    results["buy_hold_50_50_oos"] = bh_oos
    print(f"  B&H 50/50 Sharpe: {bh_oos['sharpe']:.4f}, MDD: {bh_oos['mdd']:.4f}")

    # ========================================
    # OPTIMIZE ALL FAMILIES ON TRAINING SET
    # ========================================
    print("\n" + "=" * 70)
    print("IN-SAMPLE OPTIMIZATION (Training Set)")
    print("=" * 70)

    families = build_param_grids()
    is_results = {}

    for name, fn, grid in families:
        best = optimize_sharpe(df_train, fn, grid, name)
        is_results[name] = best
        print(f"  {name:30s} | IS Sharpe: {best['sharpe']:.4f} | Params: {best['params']}")

    results["is_optimization"] = {}
    for name, res in is_results.items():
        results["is_optimization"][name] = {
            "best_params": {k: float(v) for k, v in res["params"].items()},
            "is_sharpe": res["sharpe"],
        }

    # ========================================
    # OUT-OF-SAMPLE EVALUATION
    # ========================================
    print("\n" + "=" * 70)
    print("OUT-OF-SAMPLE EVALUATION")
    print("=" * 70)

    oos_results = {}
    r_bench_oos = w_bench_oos * df_oos["r_port"].values  # benchmark returns for DM test

    for name, fn, _ in families:
        params = is_results[name]["params"]
        vix_oos = df_oos["VIX"].values

        if "p" in params:
            w_oos = fn(vix_oos, params["c"], params["p"])
        elif "c2" in params:
            w_oos = fn(vix_oos, params["c1"], params["c2"])
        else:
            w_oos = fn(vix_oos, params["c"])

        metrics = compute_vt_returns(df_oos, w_oos)

        # DM test vs benchmark
        r_strategy = w_oos * df_oos["r_port"].values
        dm_t, dm_p = dm_test(r_strategy, r_bench_oos)

        # Weight correlation with 12/VIX
        w_corr = float(np.corrcoef(w_oos, w_bench_oos)[0, 1])

        oos_results[name] = {
            "metrics": metrics,
            "dm_t_vs_benchmark": dm_t,
            "dm_p_vs_benchmark": dm_p,
            "weight_corr_vs_12vix": w_corr,
            "params": {k: float(v) for k, v in params.items()},
        }

        sharpe_diff = metrics["sharpe"] - bench_oos["sharpe"]
        sig_marker = "***" if abs(dm_t) > 3.0 else ("**" if abs(dm_t) > 2.0 else ("*" if abs(dm_t) > 1.65 else ""))
        print(f"  {name:30s} | Sharpe: {metrics['sharpe']:.4f} (diff: {sharpe_diff:+.4f}) "
              f"| DM t: {dm_t:+.3f} {sig_marker:3s} | w_corr: {w_corr:.3f} | MDD: {metrics['mdd']:.4f}")

    results["oos_evaluation"] = oos_results

    # ========================================
    # SENSITIVITY: Linear c/VIX for c = 8..16
    # ========================================
    print("\n" + "=" * 70)
    print("SENSITIVITY: Linear c/VIX (c = 8 to 16)")
    print("=" * 70)

    sensitivity = {}
    for c in np.arange(8, 16.1, 1.0):
        w_s = w_linear(df_oos["VIX"].values, c)
        m = compute_vt_returns(df_oos, w_s)
        sensitivity[f"c={c:.0f}"] = {
            "sharpe": m["sharpe"],
            "mdd": m["mdd"],
            "calmar": m["calmar"],
            "avg_weight": m["avg_weight"],
        }
        print(f"  c={c:4.0f} | Sharpe: {m['sharpe']:.4f} | MDD: {m['mdd']:.4f} | "
              f"Calmar: {m['calmar']:.3f} | Avg w: {m['avg_weight']:.3f}")

    results["sensitivity_linear_c"] = sensitivity

    # ========================================
    # CROSS-OOS VALIDATION (3 periods)
    # ========================================
    print("\n" + "=" * 70)
    print("CROSS-OOS VALIDATION (3 non-overlapping periods)")
    print("=" * 70)

    cross_oos_results = {}

    for period_name, (start, end) in CROSS_OOS.items():
        df_period = df[(df.index >= start) & (df.index <= end)].copy()
        if len(df_period) < 100:
            print(f"  {period_name}: SKIP (N={len(df_period)})")
            continue

        # Benchmark in this period
        w_b = w_linear(df_period["VIX"].values, 12.0)
        bench_p = compute_vt_returns(df_period, w_b)
        r_bench_p = w_b * df_period["r_port"].values

        print(f"\n  --- {period_name} ({start} to {end}, N={len(df_period)}) ---")
        print(f"  Benchmark 12/VIX: Sharpe={bench_p['sharpe']:.4f}")

        period_results = {"benchmark": bench_p, "strategies": {}}

        for name, fn, _ in families:
            params = is_results[name]["params"]
            vix_p = df_period["VIX"].values

            if "p" in params:
                w_p = fn(vix_p, params["c"], params["p"])
            elif "c2" in params:
                w_p = fn(vix_p, params["c1"], params["c2"])
            else:
                w_p = fn(vix_p, params["c"])

            m = compute_vt_returns(df_period, w_p)
            r_strat = w_p * df_period["r_port"].values
            dm_t, dm_p = dm_test(r_strat, r_bench_p)

            period_results["strategies"][name] = {
                "sharpe": m["sharpe"],
                "mdd": m["mdd"],
                "dm_t": dm_t,
                "dm_p": dm_p,
                "sharpe_diff": m["sharpe"] - bench_p["sharpe"],
            }

            sdiff = m["sharpe"] - bench_p["sharpe"]
            sig = "***" if abs(dm_t) > 3.0 else ("**" if abs(dm_t) > 2.0 else ("*" if abs(dm_t) > 1.65 else ""))
            print(f"    {name:30s} | Sharpe: {m['sharpe']:.4f} (diff: {sdiff:+.4f}) | DM t: {dm_t:+.3f} {sig}")

        cross_oos_results[period_name] = period_results

    results["cross_oos"] = cross_oos_results

    # ========================================
    # ANALYSIS: Effective VIX-to-Weight Curves
    # ========================================
    print("\n" + "=" * 70)
    print("VIX-TO-WEIGHT MAPPING ANALYSIS")
    print("=" * 70)

    vix_range = np.arange(10, 50.1, 1.0)
    curve_data = {}

    # Benchmark
    curve_data["12/VIX"] = [float(w_linear(np.array([v]), 12.0)[0]) for v in vix_range]

    for name, fn, _ in families:
        params = is_results[name]["params"]
        if "p" in params:
            ws = [float(fn(np.array([v]), params["c"], params["p"])[0]) for v in vix_range]
        elif "c2" in params:
            ws = [float(fn(np.array([v]), params["c1"], params["c2"])[0]) for v in vix_range]
        else:
            ws = [float(fn(np.array([v]), params["c"])[0]) for v in vix_range]
        curve_data[name] = ws

    # Print comparison at key VIX levels
    key_vix = [12, 15, 18, 20, 25, 30, 35, 40, 50]
    print(f"\n{'VIX':>5s}", end="")
    for name in curve_data:
        short = name[:12]
        print(f" | {short:>12s}", end="")
    print()
    print("-" * (6 + 15 * len(curve_data)))

    for v in key_vix:
        idx = int(v - 10)
        if idx < 0 or idx >= len(vix_range):
            continue
        print(f"{v:5d}", end="")
        for name in curve_data:
            print(f" | {curve_data[name][idx]:12.4f}", end="")
        print()

    results["weight_curves"] = {
        "vix_range": [float(v) for v in vix_range],
        "curves": {k: v for k, v in curve_data.items()},
    }

    # ========================================
    # SUMMARY & CONCLUSIONS
    # ========================================
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Find best OOS strategy
    best_oos_name = max(oos_results, key=lambda k: oos_results[k]["metrics"]["sharpe"])
    best_oos = oos_results[best_oos_name]
    worst_oos_name = min(oos_results, key=lambda k: oos_results[k]["metrics"]["sharpe"])
    worst_oos = oos_results[worst_oos_name]

    print(f"\n  Benchmark (12/VIX) OOS Sharpe: {bench_oos['sharpe']:.4f}")
    print(f"  Best OOS:  {best_oos_name} | Sharpe: {best_oos['metrics']['sharpe']:.4f} | "
          f"DM t: {best_oos['dm_t_vs_benchmark']:+.3f}")
    print(f"  Worst OOS: {worst_oos_name} | Sharpe: {worst_oos['metrics']['sharpe']:.4f} | "
          f"DM t: {worst_oos['dm_t_vs_benchmark']:+.3f}")

    # Cross-OOS consistency check
    n_beat_cross = {}
    for name in [n for n, _, _ in families]:
        wins = 0
        for period_name in cross_oos_results:
            if name in cross_oos_results[period_name]["strategies"]:
                if cross_oos_results[period_name]["strategies"][name]["sharpe_diff"] > 0:
                    wins += 1
        n_beat_cross[name] = wins

    print(f"\n  Cross-OOS consistency (beat 12/VIX in N/3 periods):")
    for name, wins in sorted(n_beat_cross.items(), key=lambda x: -x[1]):
        print(f"    {name:30s}: {wins}/3")

    # Harvey significance check
    any_significant = False
    for name, res in oos_results.items():
        if abs(res["dm_t_vs_benchmark"]) > 3.0:
            any_significant = True
            print(f"\n  *** HARVEY SIGNIFICANT: {name} (t={res['dm_t_vs_benchmark']:+.3f}) ***")

    if not any_significant:
        print(f"\n  >>> NO strategy passes Harvey t>3.0 threshold vs 12/VIX <<<")

    # Final verdict
    verdict_parts = []
    if not any_significant:
        verdict_parts.append("No nonlinear weight function significantly outperforms 12/VIX (Harvey t>3.0)")
    if best_oos["metrics"]["sharpe"] - bench_oos["sharpe"] < 0.05:
        verdict_parts.append(f"Best improvement is only {best_oos['metrics']['sharpe'] - bench_oos['sharpe']:+.4f} Sharpe")
    if best_oos["weight_corr_vs_12vix"] > 0.9:
        verdict_parts.append(f"Best strategy weights highly correlated with 12/VIX (r={best_oos['weight_corr_vs_12vix']:.3f})")

    verdict = ". ".join(verdict_parts) + "." if verdict_parts else "Some nonlinear forms show promise."
    print(f"\n  VERDICT: {verdict}")

    results["summary"] = {
        "benchmark_oos_sharpe": bench_oos["sharpe"],
        "best_oos_strategy": best_oos_name,
        "best_oos_sharpe": best_oos["metrics"]["sharpe"],
        "best_oos_sharpe_diff": best_oos["metrics"]["sharpe"] - bench_oos["sharpe"],
        "best_oos_dm_t": best_oos["dm_t_vs_benchmark"],
        "worst_oos_strategy": worst_oos_name,
        "worst_oos_sharpe": worst_oos["metrics"]["sharpe"],
        "any_harvey_significant": any_significant,
        "cross_oos_consistency": n_beat_cross,
        "verdict": verdict,
        "n_families_tested": len(families),
        "total_param_configs_tested": sum(len(g) for _, _, g in families),
    }

    # Timing
    elapsed = time.time() - t0
    results["runtime_seconds"] = elapsed
    print(f"\n  Runtime: {elapsed:.1f}s")
    print(f"  Total parameter configurations tested: {results['summary']['total_param_configs_tested']}")

    # Save results
    out_path = project_root / "experiments" / "k568_optimal_weight_function_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    run_experiment()
