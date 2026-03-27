#!/usr/bin/env python3
"""K569: Piecewise VT for Risk-Averse Investors — Full Validation for Potential Listing
=======================================================================================

K568 found Piecewise (VIX 12-20 ramp) achieves Sharpe 1.803 with MDD -3.0% —
dramatically better risk-adjusted returns than 12/VIX (Sharpe 1.449, MDD -7.2%).
The trade-off is lower annual return (9.4% vs 12.5%). For RISK-AVERSE investors
(retirees, conservative savers), this might be the ideal strategy.

This is NOT an overlay on 12/VIX — it's an ALTERNATIVE weight function:
  w = 1.0                    if VIX < c1 (calm market)
  w = (c2 - VIX) / (c2 - c1) if c1 <= VIX <= c2 (ramp down)
  w = 0.0                    if VIX > c2 (exit)

Default: c1=12, c2=20 (from K568 IS optimization)

Validation checklist (same 8 checks as K551/K558):
  1. Harvey t>3.0 (vs Buy-and-Hold, not vs 12/VIX — different risk profile)
  2. Cross-OOS: 5+ periods with TWO different period splits
  3. Sensitivity: ramp parameters (c1=[10,11,12,13,14], c2=[18,19,20,21,22])
  4. TX cost impact: 0-50bp
  5. MDD analysis across crises (GFC, COVID, 2022)
  6. Bootstrap: 5000 reps, CI, P(win vs B&H)
  7. Taiwan adaptation: test with 0050.TW
  8. Compare with existing conservative strategy (recommended_5050 = 50/50 SPY/GLD + 12/VIX)

References:
  - Moreira & Muir (2017, JoF): Volatility-managed portfolios
  - Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing
  - Harvey (2016, JoF): t>3 threshold for multiple testing
  - K568 (this system): Optimal weight function — 12/VIX is return-optimal, piecewise is risk-optimal
  - K275 (this system): Complete case for 50/50 SPY/GLD + 12/VIX

Data source: yfinance (SPY, GLD, ^VIX, 0050.TW)
Author: [Proposed: User, Executed: Claude]
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
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ============================================================
#  Constants & Configuration
# ============================================================
RF_ANNUAL = 0.02
ANNUALIZE = np.sqrt(252)
N_BOOTSTRAP = 5000
np.random.seed(42)

# Default piecewise params (from K568 IS optimization)
C1_DEFAULT = 12.0
C2_DEFAULT = 20.0

# Cross-OOS periods — Primary split (5 periods, ~4 years each)
OOS_PRIMARY = [
    ("P1_2005_2009", "2005-06-01", "2009-05-31"),
    ("P2_2009_2013", "2009-06-01", "2013-05-31"),
    ("P3_2013_2017", "2013-06-01", "2017-05-31"),
    ("P4_2017_2021", "2017-06-01", "2021-05-31"),
    ("P5_2021_2026", "2021-06-01", "2026-03-27"),
]

# Alternative split (6 periods, ~3.5 years each)
OOS_ALTERNATIVE = [
    ("A1_2005_2008", "2005-06-01", "2008-12-31"),
    ("A2_2009_2012", "2009-01-01", "2012-12-31"),
    ("A3_2013_2016", "2013-01-01", "2016-12-31"),
    ("A4_2017_2019", "2017-01-01", "2019-12-31"),
    ("A5_2020_2022", "2020-01-01", "2022-12-31"),
    ("A6_2023_2026", "2023-01-01", "2026-03-27"),
]

# Crisis periods
CRISIS_PERIODS = {
    "GFC": ("2007-10-01", "2009-06-30"),
    "COVID": ("2020-01-15", "2020-06-30"),
    "2022_Bear": ("2022-01-01", "2022-12-31"),
    "Aug2024_Yen": ("2024-07-15", "2024-09-15"),
    "Trump_Tariff_2025": ("2025-01-20", "2025-04-30"),
}


# ============================================================
#  Weight Functions
# ============================================================
def w_piecewise(vix: np.ndarray, c1: float = C1_DEFAULT, c2: float = C2_DEFAULT) -> np.ndarray:
    """Piecewise linear: w=1 if VIX<c1, ramp to 0, w=0 if VIX>c2."""
    return np.clip(
        np.where(vix < c1, 1.0,
                 np.where(vix > c2, 0.0,
                          (c2 - vix) / (c2 - c1))),
        0.0, 1.0
    )


def w_12vix(vix: np.ndarray) -> np.ndarray:
    """Standard 12/VIX weight."""
    return np.clip(12.0 / vix, 0.0, 1.0)


# ============================================================
#  Data Loading
# ============================================================
def load_data() -> pd.DataFrame:
    """Load SPY, GLD, VIX from yfinance."""
    print("Downloading data from yfinance...")
    tickers = ["SPY", "GLD", "^VIX"]
    data = yf.download(tickers, start="2004-11-01", end="2026-03-28",
                       auto_adjust=True, progress=False)

    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data

    df = pd.DataFrame({
        "SPY": close["SPY"],
        "GLD": close["GLD"],
        "VIX": close["^VIX"],
    }).dropna()

    df["r_SPY"] = df["SPY"].pct_change()
    df["r_GLD"] = df["GLD"].pct_change()
    df["r_port"] = 0.5 * df["r_SPY"] + 0.5 * df["r_GLD"]
    df = df.dropna()

    print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")
    return df


def load_taiwan_data() -> pd.DataFrame | None:
    """Load 0050.TW and VIX for Taiwan adaptation test."""
    try:
        print("\nDownloading Taiwan data (0050.TW)...")
        tw = yf.download("0050.TW", start="2004-01-01", end="2026-03-28",
                         auto_adjust=True, progress=False)
        vix = yf.download("^VIX", start="2004-01-01", end="2026-03-28",
                          auto_adjust=True, progress=False)

        if isinstance(tw.columns, pd.MultiIndex):
            tw.columns = tw.columns.get_level_values(0)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)

        df = pd.DataFrame({
            "TW": tw["Close"],
            "VIX": vix["Close"],
        }).dropna()

        df["r_TW"] = df["TW"].pct_change()
        df = df.dropna()
        print(f"  Taiwan data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")
        return df
    except Exception as e:
        print(f"  WARNING: Failed to load Taiwan data: {e}")
        return None


# ============================================================
#  Performance Computation
# ============================================================
def compute_returns(r_port: np.ndarray, weights: np.ndarray,
                    tx_cost: float = 0.001) -> dict:
    """Compute strategy returns and metrics."""
    n = len(r_port)
    w_chg = np.abs(np.diff(weights, prepend=weights[0]))
    cost = w_chg * tx_cost
    r_vt = weights * r_port - cost

    ann_ret = np.mean(r_vt) * 252
    ann_vol = np.std(r_vt, ddof=1) * ANNUALIZE
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 1e-10 else 0

    # Cumulative for drawdown
    cum = (1 + r_vt).cumprod()
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1
    mdd = np.min(dd)

    cagr = cum[-1] ** (252 / n) - 1 if cum[-1] > 0 else -1
    calmar = cagr / abs(mdd) if abs(mdd) > 1e-10 else 0

    # Sortino
    excess = r_vt - RF_ANNUAL / 252
    downside = excess[excess < 0]
    downside_vol = np.std(downside, ddof=1) * ANNUALIZE if len(downside) > 0 else 1e-8
    sortino = (ann_ret - RF_ANNUAL) / downside_vol

    # Turnover
    turnover = np.mean(w_chg) * 252

    return {
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "cagr": float(cagr),
        "calmar": float(calmar),
        "sortino": float(sortino),
        "avg_weight": float(np.mean(weights)),
        "weight_std": float(np.std(weights)),
        "pct_time_invested": float(np.mean(weights > 0.01)),
        "n_days": int(n),
        "turnover": float(turnover),
        "daily_returns": r_vt,  # keep for bootstrap
    }


def dm_test_nw(r_strat: np.ndarray, r_base: np.ndarray) -> tuple[float, float]:
    """Diebold-Mariano test with Newey-West HAC variance."""
    d = r_strat - r_base
    n = len(d)
    d_mean = np.mean(d)

    # Andrews (1991) optimal bandwidth
    opt_lag = max(1, int(4 * (n / 100) ** (2 / 9)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, opt_lag + 1):
        w_k = 1 - k / (opt_lag + 1)  # Bartlett kernel
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * w_k * gamma_k

    nw_var = (gamma0 + gamma_sum) / n
    if nw_var <= 0:
        nw_var = gamma0 / n

    t_stat = d_mean / np.sqrt(nw_var)
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(t_stat), float(p_val)


# ============================================================
#  TEST 1: Harvey (2016) DM Test vs Buy-and-Hold
# ============================================================
def test1_harvey(df: pd.DataFrame, results: dict) -> dict:
    """Harvey (2016) statistical significance vs Buy-and-Hold."""
    print("\n" + "=" * 70)
    print("TEST 1: HARVEY (2016) DM TEST vs BUY-AND-HOLD")
    print("=" * 70)

    r_port = df["r_port"].values
    vix = df["VIX"].values

    # Piecewise strategy
    w_pw = w_piecewise(vix)
    w_chg = np.abs(np.diff(w_pw, prepend=w_pw[0]))
    r_pw = w_pw * r_port - w_chg * 0.001

    # Buy-and-hold 50/50
    r_bh = r_port  # w=1 always, no TX cost

    # 12/VIX (for reference)
    w_12 = w_12vix(vix)
    w_chg_12 = np.abs(np.diff(w_12, prepend=w_12[0]))
    r_12 = w_12 * r_port - w_chg_12 * 0.001

    # DM test: Piecewise vs B&H
    t_vs_bh, p_vs_bh = dm_test_nw(r_pw, r_bh)
    # DM test: Piecewise vs 12/VIX
    t_vs_12, p_vs_12 = dm_test_nw(r_pw, r_12)
    # DM test: 12/VIX vs B&H (for reference)
    t_12_vs_bh, p_12_vs_bh = dm_test_nw(r_12, r_bh)

    # Jobson-Korkie-Memmel Sharpe diff test
    rf_daily = RF_ANNUAL / 252
    e_pw = r_pw - rf_daily
    e_bh = r_bh - rf_daily
    mu_pw, mu_bh = np.mean(e_pw), np.mean(e_bh)
    s_pw, s_bh = np.std(e_pw, ddof=1), np.std(e_bh, ddof=1)
    sr_pw, sr_bh = mu_pw / s_pw, mu_bh / s_bh
    rho = np.corrcoef(e_pw, e_bh)[0, 1]

    n = len(r_pw)
    theta = (1 / n) * (2 * (1 - rho) + 0.5 * (sr_pw**2 + sr_bh**2 - 2 * sr_pw * sr_bh * rho**2))
    jkm_z = (sr_pw - sr_bh) / np.sqrt(theta) if theta > 0 else 0
    jkm_p = 2 * (1 - stats.norm.cdf(abs(jkm_z)))

    print(f"\n  DM Test: Piecewise vs Buy-and-Hold (NW HAC):")
    print(f"    Mean daily return diff: {(np.mean(r_pw) - np.mean(r_bh))*10000:.4f} bps")
    print(f"    Annualized return diff: {(np.mean(r_pw) - np.mean(r_bh))*252*100:.2f}%")
    print(f"    DM t-statistic:  {t_vs_bh:+.4f}")
    print(f"    p-value:         {p_vs_bh:.6f}")
    print(f"    Harvey t>3.0:    {'PASS' if abs(t_vs_bh) > 3.0 else 'FAIL'}")

    print(f"\n  DM Test: Piecewise vs 12/VIX (reference only):")
    print(f"    DM t-statistic:  {t_vs_12:+.4f}")
    print(f"    p-value:         {p_vs_12:.6f}")

    print(f"\n  DM Test: 12/VIX vs Buy-and-Hold (reference):")
    print(f"    DM t-statistic:  {t_12_vs_bh:+.4f}")

    print(f"\n  JKM Sharpe Diff Test (Piecewise vs B&H):")
    print(f"    Piecewise Sharpe (ann): {sr_pw * ANNUALIZE:.4f}")
    print(f"    B&H Sharpe (ann):      {sr_bh * ANNUALIZE:.4f}")
    print(f"    Correlation:           {rho:.4f}")
    print(f"    JKM z-statistic:       {jkm_z:+.4f}")
    print(f"    JKM p-value:           {jkm_p:.6f}")
    print(f"    Harvey t>3.0:          {'PASS' if abs(jkm_z) > 3.0 else 'FAIL'}")

    test1 = {
        "dm_vs_bh_t": round(t_vs_bh, 4),
        "dm_vs_bh_p": round(p_vs_bh, 6),
        "dm_vs_bh_harvey_pass": abs(t_vs_bh) > 3.0,
        "dm_vs_12vix_t": round(t_vs_12, 4),
        "dm_vs_12vix_p": round(p_vs_12, 6),
        "dm_12vix_vs_bh_t": round(t_12_vs_bh, 4),
        "jkm_sharpe_pw": round(float(sr_pw * ANNUALIZE), 4),
        "jkm_sharpe_bh": round(float(sr_bh * ANNUALIZE), 4),
        "jkm_z": round(jkm_z, 4),
        "jkm_p": round(jkm_p, 6),
        "jkm_harvey_pass": abs(jkm_z) > 3.0,
    }
    results["test1_harvey"] = test1
    return results


# ============================================================
#  TEST 2: Cross-OOS (5+ periods, two splits)
# ============================================================
def test2_cross_oos(df: pd.DataFrame, results: dict) -> dict:
    """Cross-OOS validation with two independent period splits."""
    print("\n" + "=" * 70)
    print("TEST 2: CROSS-OOS VALIDATION")
    print("=" * 70)

    cross_results = {}

    for split_name, periods in [("Primary (5 periods)", OOS_PRIMARY),
                                 ("Alternative (6 periods)", OOS_ALTERNATIVE)]:
        print(f"\n  --- {split_name} ---")
        split_data = {}
        wins_vs_bh = 0
        wins_vs_12vix = 0

        for name, start, end in periods:
            mask = (df.index >= start) & (df.index <= end)
            df_p = df[mask].copy()
            if len(df_p) < 100:
                print(f"    {name}: SKIP (N={len(df_p)})")
                continue

            r_port = df_p["r_port"].values
            vix = df_p["VIX"].values

            # Piecewise
            w_pw = w_piecewise(vix)
            m_pw = compute_returns(r_port, w_pw)

            # Buy-and-hold
            w_bh = np.ones(len(r_port))
            m_bh = compute_returns(r_port, w_bh, tx_cost=0)

            # 12/VIX
            w_12 = w_12vix(vix)
            m_12 = compute_returns(r_port, w_12)

            pw_vs_bh = m_pw["sharpe"] > m_bh["sharpe"]
            pw_vs_12 = m_pw["sharpe"] > m_12["sharpe"]

            if pw_vs_bh:
                wins_vs_bh += 1
            if pw_vs_12:
                wins_vs_12vix += 1

            print(f"    {name}: PW Sharpe={m_pw['sharpe']:.3f}, MDD={m_pw['mdd']*100:.1f}% | "
                  f"B&H Sharpe={m_bh['sharpe']:.3f}, MDD={m_bh['mdd']*100:.1f}% | "
                  f"12/VIX Sharpe={m_12['sharpe']:.3f}, MDD={m_12['mdd']*100:.1f}% | "
                  f"PW>BH={'Y' if pw_vs_bh else 'N'} PW>12={'Y' if pw_vs_12 else 'N'}")

            # Remove non-serializable array
            m_pw_clean = {k: v for k, v in m_pw.items() if k != "daily_returns"}
            m_bh_clean = {k: v for k, v in m_bh.items() if k != "daily_returns"}
            m_12_clean = {k: v for k, v in m_12.items() if k != "daily_returns"}

            split_data[name] = {
                "piecewise": m_pw_clean,
                "buy_hold": m_bh_clean,
                "12vix": m_12_clean,
                "pw_beats_bh": pw_vs_bh,
                "pw_beats_12vix": pw_vs_12,
                "pw_mdd_better_than_12vix": m_pw["mdd"] > m_12["mdd"],
            }

        n_periods = len(split_data)
        print(f"\n    Piecewise wins vs B&H: {wins_vs_bh}/{n_periods}")
        print(f"    Piecewise wins vs 12/VIX (Sharpe): {wins_vs_12vix}/{n_periods}")

        # MDD comparison
        mdd_wins = sum(1 for v in split_data.values() if v["pw_mdd_better_than_12vix"])
        print(f"    Piecewise better MDD than 12/VIX: {mdd_wins}/{n_periods}")

        cross_results[split_name] = {
            "periods": split_data,
            "wins_vs_bh": wins_vs_bh,
            "wins_vs_12vix_sharpe": wins_vs_12vix,
            "wins_vs_12vix_mdd": mdd_wins,
            "n_periods": n_periods,
        }

    results["test2_cross_oos"] = cross_results
    return results


# ============================================================
#  TEST 3: Sensitivity Analysis (c1, c2 grid)
# ============================================================
def test3_sensitivity(df: pd.DataFrame, results: dict) -> dict:
    """Sensitivity to ramp parameters c1 and c2."""
    print("\n" + "=" * 70)
    print("TEST 3: SENSITIVITY ANALYSIS (c1, c2 grid)")
    print("=" * 70)

    r_port = df["r_port"].values
    vix = df["VIX"].values

    c1_range = [10, 11, 12, 13, 14]
    c2_range = [18, 19, 20, 21, 22, 24, 26]

    sensitivity = {}
    print(f"\n  {'c1\\c2':>6s}", end="")
    for c2 in c2_range:
        print(f"  c2={c2:2d}  ", end="")
    print("  (Sharpe | MDD%)")
    print("-" * (8 + 10 * len(c2_range) + 20))

    best_sharpe = -999
    best_combo = None

    for c1 in c1_range:
        print(f"  c1={c1:2d}", end="")
        for c2 in c2_range:
            if c2 <= c1 + 2:
                print(f"    ---   ", end="")
                continue

            w = w_piecewise(vix, c1, c2)
            m = compute_returns(r_port, w)

            key = f"c1={c1}_c2={c2}"
            sensitivity[key] = {
                "sharpe": round(m["sharpe"], 4),
                "mdd": round(m["mdd"] * 100, 2),
                "ann_return": round(m["ann_return"] * 100, 2),
                "calmar": round(m["calmar"], 3),
                "avg_weight": round(m["avg_weight"], 3),
            }

            if m["sharpe"] > best_sharpe:
                best_sharpe = m["sharpe"]
                best_combo = (c1, c2)

            print(f"  {m['sharpe']:.2f}/{m['mdd']*100:.1f}", end="")
        print()

    print(f"\n  Best combo: c1={best_combo[0]}, c2={best_combo[1]}, Sharpe={best_sharpe:.4f}")

    # Sharpe range to check flatness
    sharpes = [v["sharpe"] for v in sensitivity.values()]
    sharpe_range = max(sharpes) - min(sharpes)
    sharpe_std = np.std(sharpes)
    print(f"  Sharpe range: {sharpe_range:.4f}, std: {sharpe_std:.4f}")
    print(f"  Sensitivity: {'LOW (robust)' if sharpe_std < 0.15 else 'MODERATE' if sharpe_std < 0.3 else 'HIGH (fragile)'}")

    results["test3_sensitivity"] = {
        "grid": sensitivity,
        "best_combo": {"c1": best_combo[0], "c2": best_combo[1]},
        "best_sharpe": round(best_sharpe, 4),
        "sharpe_range": round(sharpe_range, 4),
        "sharpe_std": round(sharpe_std, 4),
        "robustness": "LOW" if sharpe_std < 0.15 else "MODERATE" if sharpe_std < 0.3 else "HIGH",
    }
    return results


# ============================================================
#  TEST 4: Transaction Cost Impact
# ============================================================
def test4_tx_costs(df: pd.DataFrame, results: dict) -> dict:
    """Impact of transaction costs from 0 to 50bp."""
    print("\n" + "=" * 70)
    print("TEST 4: TRANSACTION COST IMPACT")
    print("=" * 70)

    r_port = df["r_port"].values
    vix = df["VIX"].values
    w_pw = w_piecewise(vix)
    w_12 = w_12vix(vix)

    tx_levels = [0, 0.0005, 0.001, 0.002, 0.003, 0.005]
    tx_results = {}

    print(f"\n  {'TX (bp)':>8s} | {'PW Sharpe':>10s} | {'PW Return':>10s} | {'12/VIX Sharpe':>14s} | {'PW - 12/VIX':>12s}")
    print("-" * 65)

    for tx in tx_levels:
        m_pw = compute_returns(r_port, w_pw, tx_cost=tx)
        m_12 = compute_returns(r_port, w_12, tx_cost=tx)

        key = f"{tx*10000:.0f}bp"
        tx_results[key] = {
            "piecewise_sharpe": round(m_pw["sharpe"], 4),
            "piecewise_return": round(m_pw["ann_return"] * 100, 2),
            "12vix_sharpe": round(m_12["sharpe"], 4),
            "12vix_return": round(m_12["ann_return"] * 100, 2),
            "sharpe_diff": round(m_pw["sharpe"] - m_12["sharpe"], 4),
        }

        print(f"  {tx*10000:6.0f}bp | {m_pw['sharpe']:10.4f} | {m_pw['ann_return']*100:9.2f}% | "
              f"{m_12['sharpe']:14.4f} | {m_pw['sharpe'] - m_12['sharpe']:+12.4f}")

    # Find breakeven TX cost where Piecewise Sharpe == 12/VIX Sharpe
    for tx_test in np.arange(0, 0.02, 0.0001):
        m_pw_t = compute_returns(r_port, w_pw, tx_cost=tx_test)
        m_12_t = compute_returns(r_port, w_12, tx_cost=tx_test)
        if m_pw_t["sharpe"] < m_12_t["sharpe"]:
            # Piecewise loses at this TX cost
            break
    else:
        tx_test = 0.02

    print(f"\n  Piecewise Sharpe advantage vanishes at TX ~{tx_test*10000:.0f}bp")
    print(f"  (Piecewise has higher turnover → more sensitive to TX costs)")

    # Also compute turnover comparison
    m_pw_0 = compute_returns(r_port, w_pw, tx_cost=0)
    m_12_0 = compute_returns(r_port, w_12, tx_cost=0)
    print(f"  Piecewise annual turnover: {m_pw_0['turnover']:.1f}")
    print(f"  12/VIX annual turnover:    {m_12_0['turnover']:.1f}")

    tx_results["breakeven_bp"] = round(tx_test * 10000, 1)
    tx_results["pw_turnover"] = round(m_pw_0["turnover"], 2)
    tx_results["12vix_turnover"] = round(m_12_0["turnover"], 2)

    results["test4_tx_costs"] = tx_results
    return results


# ============================================================
#  TEST 5: Crisis MDD Analysis
# ============================================================
def test5_crisis_mdd(df: pd.DataFrame, results: dict) -> dict:
    """MDD comparison during major crises."""
    print("\n" + "=" * 70)
    print("TEST 5: CRISIS MDD ANALYSIS")
    print("=" * 70)

    crisis_results = {}

    for crisis_name, (start, end) in CRISIS_PERIODS.items():
        mask = (df.index >= start) & (df.index <= end)
        df_c = df[mask].copy()
        if len(df_c) < 10:
            print(f"  {crisis_name}: SKIP (N={len(df_c)})")
            continue

        r_port = df_c["r_port"].values
        vix = df_c["VIX"].values

        # Piecewise
        w_pw = w_piecewise(vix)
        m_pw = compute_returns(r_port, w_pw)

        # Buy-and-hold
        w_bh = np.ones(len(r_port))
        m_bh = compute_returns(r_port, w_bh, tx_cost=0)

        # 12/VIX
        w_12 = w_12vix(vix)
        m_12 = compute_returns(r_port, w_12)

        # Average VIX during crisis
        avg_vix = float(np.mean(vix))
        pct_out = float(np.mean(w_pw < 0.01)) * 100  # % time w=0

        crisis_results[crisis_name] = {
            "n_days": len(df_c),
            "avg_vix": round(avg_vix, 1),
            "pct_time_out": round(pct_out, 1),
            "pw_mdd": round(m_pw["mdd"] * 100, 2),
            "bh_mdd": round(m_bh["mdd"] * 100, 2),
            "12vix_mdd": round(m_12["mdd"] * 100, 2),
            "pw_return": round(m_pw["ann_return"] * 100, 2),
            "bh_return": round(m_bh["ann_return"] * 100, 2),
            "12vix_return": round(m_12["ann_return"] * 100, 2),
            "mdd_reduction_vs_bh": round((1 - abs(m_pw["mdd"]) / abs(m_bh["mdd"])) * 100, 1) if abs(m_bh["mdd"]) > 0.001 else 0,
            "mdd_reduction_vs_12vix": round((1 - abs(m_pw["mdd"]) / abs(m_12["mdd"])) * 100, 1) if abs(m_12["mdd"]) > 0.001 else 0,
        }

        print(f"\n  {crisis_name} ({start} to {end}, N={len(df_c)}, avg VIX={avg_vix:.1f}):")
        print(f"    Piecewise MDD: {m_pw['mdd']*100:.2f}% (out {pct_out:.0f}% of time)")
        print(f"    12/VIX MDD:    {m_12['mdd']*100:.2f}%")
        print(f"    B&H MDD:       {m_bh['mdd']*100:.2f}%")
        print(f"    MDD reduction vs B&H: {crisis_results[crisis_name]['mdd_reduction_vs_bh']:.1f}%")
        print(f"    MDD reduction vs 12/VIX: {crisis_results[crisis_name]['mdd_reduction_vs_12vix']:.1f}%")

    results["test5_crisis_mdd"] = crisis_results
    return results


# ============================================================
#  TEST 6: Bootstrap Confidence Intervals
# ============================================================
def test6_bootstrap(df: pd.DataFrame, results: dict) -> dict:
    """Bootstrap 5000 reps for Sharpe ratio CI and P(win vs B&H)."""
    print("\n" + "=" * 70)
    print(f"TEST 6: BOOTSTRAP ({N_BOOTSTRAP} reps)")
    print("=" * 70)

    r_port = df["r_port"].values
    vix = df["VIX"].values
    n = len(r_port)

    w_pw = w_piecewise(vix)
    w_12 = w_12vix(vix)

    # Precompute daily returns
    w_chg_pw = np.abs(np.diff(w_pw, prepend=w_pw[0]))
    r_pw_daily = w_pw * r_port - w_chg_pw * 0.001

    w_chg_12 = np.abs(np.diff(w_12, prepend=w_12[0]))
    r_12_daily = w_12 * r_port - w_chg_12 * 0.001

    r_bh_daily = r_port  # no tx cost

    # Block bootstrap (block size = 21 trading days = ~1 month)
    block_size = 21
    n_blocks = n // block_size

    sharpe_pw = np.zeros(N_BOOTSTRAP)
    sharpe_12 = np.zeros(N_BOOTSTRAP)
    sharpe_bh = np.zeros(N_BOOTSTRAP)
    pw_minus_bh = np.zeros(N_BOOTSTRAP)
    pw_minus_12 = np.zeros(N_BOOTSTRAP)

    for i in range(N_BOOTSTRAP):
        # Sample block starts
        starts = np.random.randint(0, n - block_size, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block_size) for s in starts])[:n]

        r_pw_b = r_pw_daily[idx]
        r_12_b = r_12_daily[idx]
        r_bh_b = r_bh_daily[idx]

        ann_ret_pw = np.mean(r_pw_b) * 252
        ann_vol_pw = np.std(r_pw_b, ddof=1) * ANNUALIZE
        sharpe_pw[i] = (ann_ret_pw - RF_ANNUAL) / ann_vol_pw if ann_vol_pw > 1e-10 else 0

        ann_ret_12 = np.mean(r_12_b) * 252
        ann_vol_12 = np.std(r_12_b, ddof=1) * ANNUALIZE
        sharpe_12[i] = (ann_ret_12 - RF_ANNUAL) / ann_vol_12 if ann_vol_12 > 1e-10 else 0

        ann_ret_bh = np.mean(r_bh_b) * 252
        ann_vol_bh = np.std(r_bh_b, ddof=1) * ANNUALIZE
        sharpe_bh[i] = (ann_ret_bh - RF_ANNUAL) / ann_vol_bh if ann_vol_bh > 1e-10 else 0

        pw_minus_bh[i] = sharpe_pw[i] - sharpe_bh[i]
        pw_minus_12[i] = sharpe_pw[i] - sharpe_12[i]

    p_win_bh = float(np.mean(sharpe_pw > sharpe_bh)) * 100
    p_win_12 = float(np.mean(sharpe_pw > sharpe_12)) * 100

    print(f"\n  Piecewise Sharpe: {np.mean(sharpe_pw):.4f} "
          f"[{np.percentile(sharpe_pw, 2.5):.4f}, {np.percentile(sharpe_pw, 97.5):.4f}] 95% CI")
    print(f"  12/VIX Sharpe:    {np.mean(sharpe_12):.4f} "
          f"[{np.percentile(sharpe_12, 2.5):.4f}, {np.percentile(sharpe_12, 97.5):.4f}] 95% CI")
    print(f"  B&H Sharpe:       {np.mean(sharpe_bh):.4f} "
          f"[{np.percentile(sharpe_bh, 2.5):.4f}, {np.percentile(sharpe_bh, 97.5):.4f}] 95% CI")
    print(f"\n  P(Piecewise > B&H):   {p_win_bh:.1f}%")
    print(f"  P(Piecewise > 12/VIX): {p_win_12:.1f}%")
    print(f"\n  Sharpe diff (PW - B&H):   {np.mean(pw_minus_bh):.4f} "
          f"[{np.percentile(pw_minus_bh, 2.5):.4f}, {np.percentile(pw_minus_bh, 97.5):.4f}]")
    print(f"  Sharpe diff (PW - 12/VIX): {np.mean(pw_minus_12):.4f} "
          f"[{np.percentile(pw_minus_12, 2.5):.4f}, {np.percentile(pw_minus_12, 97.5):.4f}]")

    bootstrap = {
        "n_reps": N_BOOTSTRAP,
        "block_size": block_size,
        "pw_sharpe_mean": round(float(np.mean(sharpe_pw)), 4),
        "pw_sharpe_ci_025": round(float(np.percentile(sharpe_pw, 2.5)), 4),
        "pw_sharpe_ci_975": round(float(np.percentile(sharpe_pw, 97.5)), 4),
        "12vix_sharpe_mean": round(float(np.mean(sharpe_12)), 4),
        "12vix_sharpe_ci_025": round(float(np.percentile(sharpe_12, 2.5)), 4),
        "12vix_sharpe_ci_975": round(float(np.percentile(sharpe_12, 97.5)), 4),
        "bh_sharpe_mean": round(float(np.mean(sharpe_bh)), 4),
        "bh_sharpe_ci_025": round(float(np.percentile(sharpe_bh, 2.5)), 4),
        "bh_sharpe_ci_975": round(float(np.percentile(sharpe_bh, 97.5)), 4),
        "p_win_vs_bh": round(p_win_bh, 1),
        "p_win_vs_12vix": round(p_win_12, 1),
        "sharpe_diff_pw_bh_mean": round(float(np.mean(pw_minus_bh)), 4),
        "sharpe_diff_pw_bh_ci": [round(float(np.percentile(pw_minus_bh, 2.5)), 4),
                                  round(float(np.percentile(pw_minus_bh, 97.5)), 4)],
        "sharpe_diff_pw_12_mean": round(float(np.mean(pw_minus_12)), 4),
        "sharpe_diff_pw_12_ci": [round(float(np.percentile(pw_minus_12, 2.5)), 4),
                                  round(float(np.percentile(pw_minus_12, 97.5)), 4)],
    }

    results["test6_bootstrap"] = bootstrap
    return results


# ============================================================
#  TEST 7: Taiwan Adaptation (0050.TW)
# ============================================================
def test7_taiwan(results: dict) -> dict:
    """Test piecewise approach with 0050.TW."""
    print("\n" + "=" * 70)
    print("TEST 7: TAIWAN ADAPTATION (0050.TW)")
    print("=" * 70)

    df_tw = load_taiwan_data()
    if df_tw is None:
        results["test7_taiwan"] = {"status": "FAILED", "reason": "Data download failed"}
        return results

    r_tw = df_tw["r_TW"].values
    vix = df_tw["VIX"].values

    # Taiwan uses 8.63/VIX (from K558)
    TW_C = 8.63

    # Test different piecewise configs for Taiwan
    # c1 should be lower (Taiwan is higher-vol, VIX drives more)
    tw_configs = [
        ("PW_8_16", 8, 16),
        ("PW_10_18", 10, 18),
        ("PW_10_20", 10, 20),
        ("PW_12_20", 12, 20),  # same as US
        ("PW_12_25", 12, 25),
        ("PW_14_22", 14, 22),
    ]

    tw_results = {}

    # Baseline: 8.63/VIX (standard Taiwan VT)
    w_tw_base = np.clip(TW_C / vix, 0.0, 1.0)
    m_tw_base = compute_returns(r_tw, w_tw_base)
    m_tw_base_clean = {k: v for k, v in m_tw_base.items() if k != "daily_returns"}
    tw_results["baseline_8.63_VIX"] = m_tw_base_clean

    # Buy-and-hold 0050
    w_bh = np.ones(len(r_tw))
    m_bh = compute_returns(r_tw, w_bh, tx_cost=0)
    m_bh_clean = {k: v for k, v in m_bh.items() if k != "daily_returns"}
    tw_results["buy_hold_0050"] = m_bh_clean

    print(f"\n  Baseline 8.63/VIX: Sharpe={m_tw_base['sharpe']:.4f}, MDD={m_tw_base['mdd']*100:.2f}%")
    print(f"  B&H 0050.TW:       Sharpe={m_bh['sharpe']:.4f}, MDD={m_bh['mdd']*100:.2f}%")

    print(f"\n  {'Config':>12s} | {'Sharpe':>8s} | {'MDD%':>8s} | {'Ret%':>8s} | {'AvgW':>6s} | {'vs 8.63':>7s}")
    print("-" * 65)

    for name, c1, c2 in tw_configs:
        w = w_piecewise(vix, c1, c2)
        m = compute_returns(r_tw, w)
        m_clean = {k: v for k, v in m.items() if k != "daily_returns"}
        tw_results[name] = m_clean

        diff = m["sharpe"] - m_tw_base["sharpe"]
        print(f"  {name:>12s} | {m['sharpe']:8.4f} | {m['mdd']*100:7.2f}% | {m['ann_return']*100:7.2f}% | "
              f"{m['avg_weight']:6.3f} | {diff:+7.4f}")

    # DM test: best piecewise vs 8.63/VIX
    best_tw = max(tw_configs, key=lambda x: compute_returns(r_tw, w_piecewise(vix, x[1], x[2]))["sharpe"])
    w_best = w_piecewise(vix, best_tw[1], best_tw[2])
    w_chg_best = np.abs(np.diff(w_best, prepend=w_best[0]))
    r_best = w_best * r_tw - w_chg_best * 0.001

    w_chg_base = np.abs(np.diff(w_tw_base, prepend=w_tw_base[0]))
    r_base = w_tw_base * r_tw - w_chg_base * 0.001

    t_tw, p_tw = dm_test_nw(r_best, r_base)
    print(f"\n  Best TW config: {best_tw[0]} (c1={best_tw[1]}, c2={best_tw[2]})")
    print(f"  DM t vs 8.63/VIX: {t_tw:+.4f}, p={p_tw:.4f}")

    tw_results["best_config"] = best_tw[0]
    tw_results["best_dm_t_vs_baseline"] = round(t_tw, 4)
    tw_results["best_dm_p_vs_baseline"] = round(p_tw, 4)

    results["test7_taiwan"] = tw_results
    return results


# ============================================================
#  TEST 8: Compare with Existing Conservative Strategy
# ============================================================
def test8_compare_existing(df: pd.DataFrame, results: dict) -> dict:
    """Compare piecewise with recommended_5050 (existing 50/50 + 12/VIX)."""
    print("\n" + "=" * 70)
    print("TEST 8: COMPARISON WITH EXISTING STRATEGIES")
    print("=" * 70)

    r_port = df["r_port"].values
    vix = df["VIX"].values

    strategies = {
        "Piecewise (c1=12, c2=20)": w_piecewise(vix),
        "12/VIX (recommended_5050)": w_12vix(vix),
        "Buy-and-Hold 50/50": np.ones(len(vix)),
    }

    # Risk metrics comparison
    compare = {}
    print(f"\n  {'Strategy':>30s} | {'Sharpe':>7s} | {'MDD%':>7s} | {'Calmar':>7s} | {'Sortino':>8s} | {'Vol%':>6s} | {'Ret%':>6s}")
    print("-" * 90)

    for name, w in strategies.items():
        tx = 0.001 if name != "Buy-and-Hold 50/50" else 0
        m = compute_returns(r_port, w, tx_cost=tx)

        compare[name] = {
            "sharpe": round(m["sharpe"], 4),
            "mdd": round(m["mdd"] * 100, 2),
            "calmar": round(m["calmar"], 3),
            "sortino": round(m["sortino"], 3),
            "ann_vol": round(m["ann_vol"] * 100, 2),
            "ann_return": round(m["ann_return"] * 100, 2),
            "cagr": round(m["cagr"] * 100, 2),
            "avg_weight": round(m["avg_weight"], 3),
            "turnover": round(m["turnover"], 1),
        }

        print(f"  {name:>30s} | {m['sharpe']:7.4f} | {m['mdd']*100:6.2f}% | {m['calmar']:7.3f} | "
              f"{m['sortino']:8.3f} | {m['ann_vol']*100:5.2f}% | {m['ann_return']*100:5.2f}%")

    # Risk-adjusted advantage quantification
    pw = compare["Piecewise (c1=12, c2=20)"]
    v12 = compare["12/VIX (recommended_5050)"]
    bh = compare["Buy-and-Hold 50/50"]

    print(f"\n  --- Risk-Adjusted Advantage of Piecewise ---")
    print(f"  Sharpe:  PW {pw['sharpe']:.4f} vs 12/VIX {v12['sharpe']:.4f} ({pw['sharpe'] - v12['sharpe']:+.4f})")
    print(f"  MDD:     PW {pw['mdd']:.2f}% vs 12/VIX {v12['mdd']:.2f}% ({abs(pw['mdd']) - abs(v12['mdd']):+.2f} pp)")
    print(f"  Calmar:  PW {pw['calmar']:.3f} vs 12/VIX {v12['calmar']:.3f} ({pw['calmar'] - v12['calmar']:+.3f})")
    print(f"  Sortino: PW {pw['sortino']:.3f} vs 12/VIX {v12['sortino']:.3f} ({pw['sortino'] - v12['sortino']:+.3f})")
    print(f"\n  --- Return Trade-off ---")
    print(f"  Return:  PW {pw['ann_return']:.2f}% vs 12/VIX {v12['ann_return']:.2f}% ({pw['ann_return'] - v12['ann_return']:+.2f} pp)")
    print(f"  CAGR:    PW {pw['cagr']:.2f}% vs 12/VIX {v12['cagr']:.2f}% ({pw['cagr'] - v12['cagr']:+.2f} pp)")
    print(f"\n  --- Risk Reduction (% improvement over B&H) ---")
    print(f"  Vol reduction:  PW {(1-pw['ann_vol']/bh['ann_vol'])*100:.1f}% vs 12/VIX {(1-v12['ann_vol']/bh['ann_vol'])*100:.1f}%")
    print(f"  MDD reduction:  PW {(1-abs(pw['mdd'])/abs(bh['mdd']))*100:.1f}% vs 12/VIX {(1-abs(v12['mdd'])/abs(bh['mdd']))*100:.1f}%")

    # Who is this for?
    target_audience = {
        "ideal_for": [
            "Risk-averse investors (retirees, conservative savers)",
            "Investors who prioritize NOT LOSING over maximum growth",
            "People who would panic-sell during a -7% drawdown",
            "Conservative allocation mandates (< 5% MDD tolerance)",
        ],
        "not_for": [
            "Growth-oriented investors (12/VIX is better)",
            "Investors comfortable with 7% drawdowns",
            "Those seeking maximum absolute returns",
        ],
        "key_trade_off": f"Gives up ~{v12['ann_return'] - pw['ann_return']:.1f}% annual return for ~{abs(v12['mdd']) - abs(pw['mdd']):.1f}% less drawdown",
    }

    results["test8_comparison"] = {
        "strategies": compare,
        "target_audience": target_audience,
    }
    return results


# ============================================================
#  Full-Sample Metrics for Reference
# ============================================================
def full_sample_metrics(df: pd.DataFrame, results: dict) -> dict:
    """Compute full-sample metrics for all strategies."""
    print("\n" + "=" * 70)
    print("FULL-SAMPLE METRICS (2005-2026)")
    print("=" * 70)

    r_port = df["r_port"].values
    vix = df["VIX"].values

    # Full sample
    w_pw = w_piecewise(vix)
    m_pw = compute_returns(r_port, w_pw)

    w_12 = w_12vix(vix)
    m_12 = compute_returns(r_port, w_12)

    w_bh = np.ones(len(r_port))
    m_bh = compute_returns(r_port, w_bh, tx_cost=0)

    m_pw_clean = {k: v for k, v in m_pw.items() if k != "daily_returns"}
    m_12_clean = {k: v for k, v in m_12.items() if k != "daily_returns"}
    m_bh_clean = {k: v for k, v in m_bh.items() if k != "daily_returns"}

    print(f"\n  {'Strategy':>25s} | {'Sharpe':>7s} | {'MDD%':>8s} | {'Calmar':>7s} | {'CAGR%':>7s} | {'Vol%':>6s}")
    print("-" * 75)
    for name, m in [("Piecewise (12,20)", m_pw), ("12/VIX", m_12), ("B&H 50/50", m_bh)]:
        print(f"  {name:>25s} | {m['sharpe']:7.4f} | {m['mdd']*100:7.2f}% | {m['calmar']:7.3f} | "
              f"{m['cagr']*100:6.2f}% | {m['ann_vol']*100:5.2f}%")

    results["full_sample"] = {
        "period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        "n_days": len(df),
        "piecewise": m_pw_clean,
        "12vix": m_12_clean,
        "buy_hold": m_bh_clean,
    }
    return results


# ============================================================
#  MAIN
# ============================================================
def run_experiment():
    t0 = time.time()
    results = {
        "experiment_id": "K569",
        "title": "Piecewise VT for Risk-Averse Investors — Full Validation for Potential Listing",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX, 0050.TW)",
        "methodology": "8-check validation: Harvey DM, Cross-OOS (2 splits), Sensitivity, TX costs, Crisis MDD, Bootstrap, Taiwan, Strategy comparison",
        "piecewise_function": "w = 1.0 if VIX<c1, w = (c2-VIX)/(c2-c1) if c1<=VIX<=c2, w = 0.0 if VIX>c2",
        "default_params": {"c1": C1_DEFAULT, "c2": C2_DEFAULT},
        "references": [
            "Moreira & Muir (2017, JoF): Volatility-managed portfolios",
            "Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing",
            "Harvey (2016, JoF): t>3 threshold for multiple testing",
            "K568 (this system): Optimal weight function — 12/VIX return-optimal, piecewise risk-optimal",
            "K275 (this system): Complete case for 50/50 SPY/GLD + 12/VIX",
        ],
    }

    # Load data
    df = load_data()

    # VIX descriptive stats
    vix = df["VIX"]
    results["vix_descriptive"] = {
        "mean": round(float(vix.mean()), 2),
        "median": round(float(vix.median()), 2),
        "std": round(float(vix.std()), 2),
        "min": round(float(vix.min()), 2),
        "max": round(float(vix.max()), 2),
        "q25": round(float(vix.quantile(0.25)), 2),
        "q75": round(float(vix.quantile(0.75)), 2),
        "pct_below_12": round(float((vix < 12).mean()) * 100, 1),
        "pct_12_to_20": round(float(((vix >= 12) & (vix <= 20)).mean()) * 100, 1),
        "pct_above_20": round(float((vix > 20).mean()) * 100, 1),
    }
    print(f"\nVIX Distribution:")
    print(f"  Below 12 (full invest): {results['vix_descriptive']['pct_below_12']:.1f}%")
    print(f"  12-20 (ramp down):      {results['vix_descriptive']['pct_12_to_20']:.1f}%")
    print(f"  Above 20 (fully out):   {results['vix_descriptive']['pct_above_20']:.1f}%")

    # Full-sample metrics first
    results = full_sample_metrics(df, results)

    # Run all 8 tests
    results = test1_harvey(df, results)
    results = test2_cross_oos(df, results)
    results = test3_sensitivity(df, results)
    results = test4_tx_costs(df, results)
    results = test5_crisis_mdd(df, results)
    results = test6_bootstrap(df, results)
    results = test7_taiwan(results)
    results = test8_compare_existing(df, results)

    # ========================================
    # FINAL VERDICT
    # ========================================
    print("\n" + "=" * 70)
    print("FINAL VERDICT: DEPLOYMENT READINESS")
    print("=" * 70)

    checks = {
        "T1_Harvey_vs_BH": results["test1_harvey"]["dm_vs_bh_harvey_pass"],
        "T1_JKM_vs_BH": results["test1_harvey"]["jkm_harvey_pass"],
        "T2_CrossOOS_Primary_majority": results["test2_cross_oos"]["Primary (5 periods)"]["wins_vs_bh"] >= 3,
        "T2_CrossOOS_Alt_majority": results["test2_cross_oos"]["Alternative (6 periods)"]["wins_vs_bh"] >= 4,
        "T3_Sensitivity_robust": results["test3_sensitivity"]["robustness"] in ["LOW", "MODERATE"],
        "T4_TX_survives_10bp": float(results["test4_tx_costs"].get("10bp", {}).get("piecewise_sharpe", 0)) > 1.0 if "10bp" in results["test4_tx_costs"] else True,
        "T5_GFC_MDD_better_than_BH": abs(results["test5_crisis_mdd"].get("GFC", {}).get("pw_mdd", -99)) < abs(results["test5_crisis_mdd"].get("GFC", {}).get("bh_mdd", -1)),
        "T6_Bootstrap_Pwin_gt80": results["test6_bootstrap"]["p_win_vs_bh"] > 80,
    }

    n_pass = sum(checks.values())
    n_total = len(checks)

    print(f"\n  Validation Checklist: {n_pass}/{n_total} PASSED")
    for name, passed in checks.items():
        print(f"    {'PASS' if passed else 'FAIL'} | {name}")

    deployment_ready = n_pass >= 6  # Allow 2 failures at most
    strong_candidate = n_pass >= 7

    print(f"\n  Deployment ready: {'YES' if deployment_ready else 'NO'} ({n_pass}/{n_total})")
    print(f"  Strong candidate: {'YES' if strong_candidate else 'NO'} ({n_pass}/{n_total})")

    if deployment_ready:
        print(f"\n  RECOMMENDATION: List as 'Conservative VT (SPY/GLD)' strategy")
        print(f"    Target audience: Risk-averse investors, retirees, conservative mandates")
        print(f"    Key advantage: ~{abs(results['full_sample']['12vix']['mdd'])*100 - abs(results['full_sample']['piecewise']['mdd'])*100:.0f}% less MDD than 12/VIX")
        print(f"    Key trade-off: ~{(results['full_sample']['12vix']['ann_return'] - results['full_sample']['piecewise']['ann_return'])*100:.0f}% less annual return")
    else:
        print(f"\n  NOT RECOMMENDED for deployment yet — needs more evidence")

    results["verdict"] = {
        "checks": checks,
        "n_pass": n_pass,
        "n_total": n_total,
        "deployment_ready": deployment_ready,
        "strong_candidate": strong_candidate,
    }

    # Timing
    elapsed = time.time() - t0
    results["runtime_seconds"] = round(elapsed, 1)
    print(f"\n  Runtime: {elapsed:.1f}s")

    # Save results (remove daily_returns arrays)
    def clean_for_json(obj):
        if isinstance(obj, dict):
            return {k: clean_for_json(v) for k, v in obj.items() if k != "daily_returns"}
        elif isinstance(obj, (list, tuple)):
            return [clean_for_json(item) for item in obj]
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif isinstance(obj, (np.float64, np.float32)):
            return float(obj)
        elif isinstance(obj, (np.int64, np.int32)):
            return int(obj)
        elif isinstance(obj, np.bool_):
            return bool(obj)
        return obj

    results_clean = clean_for_json(results)

    out_path = project_root / "experiments" / "k569_piecewise_vt_validation_results.json"
    with open(out_path, "w") as f:
        json.dump(results_clean, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results_clean


if __name__ == "__main__":
    run_experiment()
