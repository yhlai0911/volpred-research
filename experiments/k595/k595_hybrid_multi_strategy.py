#!/usr/bin/env python3
"""K595: Hybrid Multi-Strategy Portfolio — Combining validated strategies for optimal risk-return
================================================================================================

Motivation:
    Three validated VT strategies show clear complementarity:
    - Piecewise VT (K569): exits at VIX>20 (21.2% of days = cash), MDD -5.4%, Sharpe 1.327
    - Standard 12/VIX: continuous exposure, MDD -10.2%, Sharpe 1.178
    - VIX-Conditional Leverage (K551): 1.5x in calm (VIX<15), MDD -12.3%, Sharpe 1.474
    They naturally form a "staircase" risk management system.

Design — 5 hybrid strategies:
    1. Staircase: 50% Piecewise + 50% Standard 12/VIX
    2. Adaptive Tier: VIX<15→Leverage, VIX 15-20→12/VIX, VIX>20→Piecewise
    3. Risk Budget Split: 60% 12/VIX (core) + 40% Piecewise (satellite)
    4. Max of Two: MAX(PW weight, Standard weight × 0.5) — non-zero floor
    5. Conviction Blend: PW_weight × Leverage_multiplier — direction × intensity

All applied to 50/50 SPY/GLD. Benchmark: each individual strategy.
Evaluation: Sharpe, MDD, Calmar, Sortino, cross-OOS 5 periods, Harvey t>3.0, bootstrap.

Key question: is the COMBINATION better than any individual strategy?

References:
    - Moreira & Muir (2017, JoF): Volatility-managed portfolios
    - Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing
    - Harvey (2016, JoF): t>3 threshold for multiple testing
    - K548/K551: VIX-Conditional Leverage (validated, Harvey t=7.90)
    - K568/K569: Piecewise VT (validated, 6/8 pass, MDD -0.56% GFC)
    - K275: Complete case for 50/50 SPY/GLD + 12/VIX

Data source: yfinance (SPY, GLD, ^VIX, ^IRX)
Period: 2005-2026 (~21 years, 5300+ trading days)
Author: [Proposed: User, Executed: Claude]
"""
from __future__ import annotations

import json
import sys
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
BORROWING_SPREAD = 0.005  # 50bps above risk-free
FALLBACK_RF = 0.04
np.random.seed(42)

# Piecewise parameters (from K568 IS optimization)
C1 = 12.0  # start ramp-down
C2 = 20.0  # full exit

# VIX-Conditional Leverage parameters (from K548/K551)
VIX_LEV_LOW = 15.0   # below this: 1.5x
VIX_LEV_HIGH = 25.0  # above this: 1.0x
LEV_MAX = 1.5
LEV_MIN = 1.0

# Cross-OOS periods — 5 non-overlapping ~4 year periods
OOS_PERIODS = [
    ("P1_2005_2009", "2005-06-01", "2009-05-31"),
    ("P2_2009_2013", "2009-06-01", "2013-05-31"),
    ("P3_2013_2017", "2013-06-01", "2017-05-31"),
    ("P4_2017_2021", "2017-06-01", "2021-05-31"),
    ("P5_2021_2026", "2021-06-01", "2026-03-28"),
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
#  Weight Functions (building blocks)
# ============================================================
def w_piecewise(vix: np.ndarray) -> np.ndarray:
    """Piecewise linear: w=1 if VIX<C1, ramp to 0 at C2, w=0 if VIX>C2."""
    return np.clip(
        np.where(vix < C1, 1.0,
                 np.where(vix > C2, 0.0,
                          (C2 - vix) / (C2 - C1))),
        0.0, 1.0
    )


def w_12vix(vix: np.ndarray) -> np.ndarray:
    """Standard 12/VIX weight."""
    return np.clip(12.0 / vix, 0.0, 1.0)


def lev_vix_conditional(vix: np.ndarray) -> np.ndarray:
    """VIX-Conditional Leverage: 1.5x if VIX<15, 1.0x if VIX>25, linear between."""
    return np.clip(
        LEV_MAX - (LEV_MAX - LEV_MIN) * (vix - VIX_LEV_LOW) / (VIX_LEV_HIGH - VIX_LEV_LOW),
        LEV_MIN, LEV_MAX
    )


# ============================================================
#  Hybrid Strategy Weights
# ============================================================
def compute_all_weights(vix: np.ndarray) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Compute (equity_weight, leverage_multiplier) for each strategy.

    Returns dict of strategy_name -> (weight, leverage).
    Effective exposure = weight * leverage.
    When leverage > 1.0, borrowing cost applies.
    """
    pw = w_piecewise(vix)
    std = w_12vix(vix)
    lev = lev_vix_conditional(vix)

    strategies = {}

    # === Individual strategies (benchmarks) ===
    # Buy & Hold
    strategies["BuyHold"] = (np.ones_like(vix), np.ones_like(vix))

    # Standard 12/VIX
    strategies["12_VIX"] = (std, np.ones_like(vix))

    # Piecewise VT
    strategies["Piecewise"] = (pw, np.ones_like(vix))

    # VIX-Conditional Leverage (applied to 12/VIX base)
    strategies["VIX_Cond_Lev"] = (std, lev)

    # === Hybrid strategies ===

    # H1: Staircase — 50% capital to PW, 50% to Standard
    # Net weight = 0.5 * pw + 0.5 * std
    h1_weight = 0.5 * pw + 0.5 * std
    strategies["H1_Staircase"] = (h1_weight, np.ones_like(vix))

    # H2: Adaptive Tier — discrete VIX regime switch
    # VIX < 15: use VIX-Cond Leverage (12/VIX weight * 1.5x leverage)
    # VIX 15-20: use Standard 12/VIX (no leverage)
    # VIX > 20: use Piecewise (ramp to 0)
    h2_weight = np.where(vix < 15, std,
                         np.where(vix <= 20, std, pw))
    h2_lev = np.where(vix < 15, lev, np.ones_like(vix))
    strategies["H2_Adaptive_Tier"] = (h2_weight, h2_lev)

    # H3: Risk Budget Split — 60% capital to 12/VIX, 40% to Piecewise
    # Net weight = 0.6 * std + 0.4 * pw
    h3_weight = 0.6 * std + 0.4 * pw
    strategies["H3_Risk_Budget"] = (h3_weight, np.ones_like(vix))

    # H4: Max of Two — MAX(PW weight, Standard weight × 0.5)
    # Ensures non-zero exposure but PW's conservatism limits max
    h4_weight = np.maximum(pw, std * 0.5)
    strategies["H4_Max_of_Two"] = (h4_weight, np.ones_like(vix))

    # H5: Conviction Blend — PW_weight × Leverage_multiplier
    # PW provides direction (0-100%), leverage provides intensity (1.0-1.5x)
    # VIX<12: 100% × 1.5x = 150% aggressive
    # VIX=16: 50% × ~1.25x = 62.5% moderate
    # VIX>20: 0% × 1.0x = 0% full protection
    strategies["H5_Conviction"] = (pw, lev)

    return strategies


# ============================================================
#  Data Loading
# ============================================================
def load_data() -> pd.DataFrame:
    """Load SPY, GLD, VIX, IRX from yfinance."""
    print("=" * 70)
    print("K595: Hybrid Multi-Strategy Portfolio")
    print("=" * 70)
    print("\nDownloading data from yfinance...")

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

    # Risk-free rate
    try:
        irx = yf.download("^IRX", start="2004-11-01", end="2026-03-28",
                           auto_adjust=True, progress=False)
        if isinstance(irx.columns, pd.MultiIndex):
            irx.columns = irx.columns.get_level_values(0)
        df["rf_annual"] = irx["Close"].reindex(df.index).ffill() / 100
        df["rf_daily"] = df["rf_annual"] / 252
        print(f"  Risk-free rate from ^IRX: mean={df['rf_annual'].mean()*100:.2f}%")
    except Exception:
        df["rf_annual"] = FALLBACK_RF
        df["rf_daily"] = FALLBACK_RF / 252
        print(f"  Using fallback RF: {FALLBACK_RF*100:.1f}%")

    df["r_SPY"] = df["SPY"].pct_change()
    df["r_GLD"] = df["GLD"].pct_change()
    df["r_port"] = 0.5 * df["r_SPY"] + 0.5 * df["r_GLD"]  # 50/50 portfolio
    df = df.dropna()

    print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, N={len(df)}")

    # Descriptive statistics
    print(f"\n  VIX: mean={df['VIX'].mean():.1f}, std={df['VIX'].std():.1f}, "
          f"min={df['VIX'].min():.1f}, max={df['VIX'].max():.1f}")
    print(f"  VIX < 15: {(df['VIX'] < 15).mean()*100:.1f}% of days")
    print(f"  VIX 15-20: {((df['VIX'] >= 15) & (df['VIX'] <= 20)).mean()*100:.1f}% of days")
    print(f"  VIX > 20: {(df['VIX'] > 20).mean()*100:.1f}% of days")

    return df


# ============================================================
#  Performance Metrics
# ============================================================
def compute_strategy_returns(r_port: np.ndarray, weights: np.ndarray,
                              leverage: np.ndarray, rf_daily: np.ndarray,
                              tx_cost: float = 0.001) -> np.ndarray:
    """Compute daily strategy returns with leverage and borrowing costs.

    Effective exposure = weight * leverage.
    When leverage > 1: borrowing cost = (leverage - 1) * weight * (rf + spread).
    Cash portion earns rf.
    """
    effective = weights * leverage

    # Transaction cost on effective exposure changes
    eff_chg = np.abs(np.diff(effective, prepend=effective[0]))
    cost = eff_chg * tx_cost

    # Gross return = exposure * portfolio return + (1 - exposure) * rf
    gross = effective * r_port + (1.0 - effective) * rf_daily

    # Borrowing cost (only when leverage > 1)
    borrow = np.maximum(leverage - 1.0, 0.0) * weights * (rf_daily + BORROWING_SPREAD / 252)

    return gross - borrow - cost


def compute_metrics(daily_returns: np.ndarray, rf_daily: np.ndarray = None,
                    weights: np.ndarray = None) -> dict:
    """Compute comprehensive performance metrics."""
    r = daily_returns
    n = len(r)
    if n < 126:  # minimum half year
        return None

    # Annualized return and vol
    ann_ret = np.mean(r) * 252
    ann_vol = np.std(r, ddof=1) * ANNUALIZE

    # Sharpe
    if rf_daily is not None:
        excess = r - rf_daily
    else:
        excess = r - RF_ANNUAL / 252
    sharpe = np.mean(excess) / np.std(excess, ddof=1) * ANNUALIZE if np.std(excess) > 1e-10 else 0

    # Cumulative for drawdown
    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1
    mdd = np.min(dd)

    # CAGR
    years = n / 252
    cagr = cum[-1] ** (1 / years) - 1 if cum[-1] > 0 else -1

    # Calmar
    calmar = cagr / abs(mdd) if abs(mdd) > 1e-10 else 0

    # Sortino
    downside = excess[excess < 0]
    down_vol = np.std(downside, ddof=1) * ANNUALIZE if len(downside) > 10 else 1e-8
    sortino = (ann_ret - RF_ANNUAL) / down_vol

    # Turnover (if weights provided)
    turnover = 0.0
    if weights is not None:
        turnover = float(np.mean(np.abs(np.diff(weights))) * 252)

    # Terminal value ($1M)
    terminal = cum[-1] * 1_000_000

    return {
        "ann_return": round(float(ann_ret) * 100, 2),
        "ann_vol": round(float(ann_vol) * 100, 2),
        "sharpe": round(float(sharpe), 3),
        "mdd": round(float(mdd) * 100, 2),
        "cagr": round(float(cagr) * 100, 2),
        "calmar": round(float(calmar), 3),
        "sortino": round(float(sortino), 3),
        "n_days": int(n),
        "terminal_1M": round(float(terminal), 0),
        "turnover": round(float(turnover), 1),
    }


# ============================================================
#  Statistical Tests
# ============================================================
def dm_test(r1: np.ndarray, r2: np.ndarray) -> tuple[float, float]:
    """Diebold-Mariano test on excess returns (squared loss).
    Positive t means r1 is better (lower squared loss ≈ higher return if positive).
    Here we test on returns directly: d = r1 - r2.
    """
    d = r1 - r2
    n = len(d)
    d_mean = np.mean(d)

    # HAC standard error (Newey-West, bandwidth = int(n^(1/3)))
    bw = int(n ** (1/3))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, bw + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / (bw + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n

    if var_d <= 0:
        return 0.0, 1.0

    t_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


def jkm_sharpe_test(r1: np.ndarray, r2: np.ndarray) -> tuple[float, float]:
    """Jobson-Korkie-Memmel test for Sharpe ratio difference."""
    mu1, mu2 = np.mean(r1), np.mean(r2)
    s1, s2 = np.std(r1, ddof=1), np.std(r2, ddof=1)
    n = len(r1)

    if s1 < 1e-10 or s2 < 1e-10:
        return 0.0, 1.0

    sr1 = mu1 / s1
    sr2 = mu2 / s2

    # Asymptotic variance of SR difference
    rho = np.corrcoef(r1, r2)[0, 1]
    theta = (1 / n) * (2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2 * sr1 * sr2 * rho))

    if theta <= 0:
        return 0.0, 1.0

    z = (sr1 - sr2) / np.sqrt(theta)
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(z), float(p)


def bootstrap_comparison(r1: np.ndarray, r2: np.ndarray,
                         n_boot: int = N_BOOTSTRAP) -> dict:
    """Bootstrap test comparing Sharpe ratios."""
    n = len(r1)
    sr_diffs = np.zeros(n_boot)

    for b in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        b1, b2 = r1[idx], r2[idx]
        s1 = np.mean(b1) / np.std(b1, ddof=1) if np.std(b1) > 1e-10 else 0
        s2 = np.mean(b2) / np.std(b2, ddof=1) if np.std(b2) > 1e-10 else 0
        sr_diffs[b] = s1 - s2

    p_win = float(np.mean(sr_diffs > 0))
    ci_lo, ci_hi = np.percentile(sr_diffs, [2.5, 97.5])
    mean_diff = np.mean(sr_diffs) * ANNUALIZE

    return {
        "p_win": round(p_win, 4),
        "mean_sr_diff_ann": round(float(mean_diff), 4),
        "ci_95_lo": round(float(ci_lo) * ANNUALIZE, 4),
        "ci_95_hi": round(float(ci_hi) * ANNUALIZE, 4),
    }


# ============================================================
#  Main Analysis
# ============================================================
def main():
    start_time = datetime.now(timezone.utc)

    # Load data
    df = load_data()
    vix = df["VIX"].values
    r_port = df["r_port"].values
    rf_daily = df["rf_daily"].values

    # Compute all strategy weights
    strategies = compute_all_weights(vix)

    # ============================================================
    #  Part 1: Full-sample performance comparison
    # ============================================================
    print("\n" + "=" * 70)
    print("PART 1: Full-Sample Performance Comparison")
    print("=" * 70)

    full_results = {}
    daily_returns = {}

    for name, (w, lev) in strategies.items():
        r = compute_strategy_returns(r_port, w, lev, rf_daily, tx_cost=0.001)
        metrics = compute_metrics(r, rf_daily, w * lev)
        if metrics:
            full_results[name] = metrics
            daily_returns[name] = r
            eff = w * lev
            metrics["avg_exposure"] = round(float(np.mean(eff)), 3)
            metrics["max_exposure"] = round(float(np.max(eff)), 3)
            metrics["pct_leveraged"] = round(float(np.mean(lev > 1.01)) * 100, 1)

    # Print comparison table
    header = f"{'Strategy':<20} {'Sharpe':>7} {'CAGR%':>7} {'MDD%':>7} {'Calmar':>7} {'Sortino':>8} {'AvgExp':>7} {'$1M→':>12}"
    print(f"\n{header}")
    print("-" * 85)
    for name in ["BuyHold", "12_VIX", "Piecewise", "VIX_Cond_Lev",
                  "H1_Staircase", "H2_Adaptive_Tier", "H3_Risk_Budget",
                  "H4_Max_of_Two", "H5_Conviction"]:
        if name in full_results:
            m = full_results[name]
            print(f"{name:<20} {m['sharpe']:>7.3f} {m['cagr']:>6.1f}% {m['mdd']:>6.1f}% "
                  f"{m['calmar']:>7.3f} {m['sortino']:>8.3f} {m.get('avg_exposure', 0):>7.3f} "
                  f"${m['terminal_1M']:>11,.0f}")

    # ============================================================
    #  Part 2: DM Tests — each hybrid vs all 3 benchmarks
    # ============================================================
    print("\n" + "=" * 70)
    print("PART 2: Statistical Tests (DM + JKM) — Hybrids vs Benchmarks")
    print("=" * 70)

    benchmarks = ["BuyHold", "12_VIX", "Piecewise", "VIX_Cond_Lev"]
    hybrids = ["H1_Staircase", "H2_Adaptive_Tier", "H3_Risk_Budget",
               "H4_Max_of_Two", "H5_Conviction"]

    stat_tests = {}
    print(f"\n{'Hybrid vs Benchmark':<35} {'DM t':>8} {'DM p':>8} {'JKM z':>8} {'JKM p':>8} {'Harvey':>8}")
    print("-" * 75)

    for h in hybrids:
        stat_tests[h] = {}
        for b in benchmarks:
            if h in daily_returns and b in daily_returns:
                dm_t, dm_p = dm_test(daily_returns[h], daily_returns[b])
                jkm_z, jkm_p = jkm_sharpe_test(daily_returns[h], daily_returns[b])
                harvey = "PASS" if abs(jkm_z) > 3.0 else "FAIL"
                stat_tests[h][b] = {
                    "dm_t": round(dm_t, 3),
                    "dm_p": round(dm_p, 4),
                    "jkm_z": round(jkm_z, 3),
                    "jkm_p": round(jkm_p, 4),
                    "harvey_pass": abs(jkm_z) > 3.0,
                }
                print(f"{h} vs {b:<14} {dm_t:>8.3f} {dm_p:>8.4f} {jkm_z:>8.3f} {jkm_p:>8.4f} {harvey:>8}")

    # ============================================================
    #  Part 3: Cross-OOS Validation (5 periods)
    # ============================================================
    print("\n" + "=" * 70)
    print("PART 3: Cross-OOS Validation (5 periods)")
    print("=" * 70)

    oos_results = {}
    all_strategies = benchmarks + hybrids

    for name in all_strategies:
        oos_results[name] = []

    for period_name, start, end in OOS_PERIODS:
        mask = (df.index >= start) & (df.index <= end)
        if mask.sum() < 126:
            print(f"  {period_name}: too few observations ({mask.sum()}), skipping")
            continue

        sub_vix = df.loc[mask, "VIX"].values
        sub_rport = df.loc[mask, "r_port"].values
        sub_rf = df.loc[mask, "rf_daily"].values
        sub_strats = compute_all_weights(sub_vix)

        print(f"\n  {period_name} ({mask.sum()} days):")

        for name in all_strategies:
            if name in sub_strats:
                w, lev = sub_strats[name]
                r = compute_strategy_returns(sub_rport, w, lev, sub_rf, tx_cost=0.001)
                m = compute_metrics(r, sub_rf, w * lev)
                if m:
                    oos_results[name].append({
                        "period": period_name,
                        **m
                    })

    # Print cross-OOS summary
    print(f"\n{'Strategy':<20}", end="")
    for pname, _, _ in OOS_PERIODS:
        print(f" {pname[-9:]:>11}", end="")
    print(f" {'Mean':>8} {'Wins':>5}")
    print("-" * 90)

    oos_summary = {}
    for name in all_strategies:
        if name in oos_results and len(oos_results[name]) > 0:
            sharpes = [r["sharpe"] for r in oos_results[name]]
            bh_sharpes = [r["sharpe"] for r in oos_results["BuyHold"]] if "BuyHold" in oos_results else [0]*5
            wins_vs_bh = sum(1 for s, b in zip(sharpes, bh_sharpes) if s > b)
            mean_sr = np.mean(sharpes)

            oos_summary[name] = {
                "period_sharpes": sharpes,
                "mean_sharpe": round(float(mean_sr), 3),
                "wins_vs_bh": wins_vs_bh,
                "n_periods": len(sharpes),
            }

            print(f"{name:<20}", end="")
            for s in sharpes:
                print(f" {s:>11.3f}", end="")
            print(f" {mean_sr:>8.3f} {wins_vs_bh:>3}/{len(sharpes)}")

    # ============================================================
    #  Part 4: Bootstrap Comparison
    # ============================================================
    print("\n" + "=" * 70)
    print("PART 4: Bootstrap Comparison (5000 reps)")
    print("=" * 70)

    bootstrap_results = {}
    print(f"\n{'Hybrid vs Benchmark':<35} {'P(win)':>8} {'Mean ΔSR':>10} {'95% CI':>20}")
    print("-" * 75)

    for h in hybrids:
        bootstrap_results[h] = {}
        for b in ["BuyHold", "12_VIX", "Piecewise", "VIX_Cond_Lev"]:
            if h in daily_returns and b in daily_returns:
                bs = bootstrap_comparison(daily_returns[h], daily_returns[b])
                bootstrap_results[h][b] = bs
                print(f"{h} vs {b:<14} {bs['p_win']:>8.1%} {bs['mean_sr_diff_ann']:>10.4f} "
                      f"[{bs['ci_95_lo']:>+.3f}, {bs['ci_95_hi']:>+.3f}]")

    # ============================================================
    #  Part 5: Crisis Period Analysis
    # ============================================================
    print("\n" + "=" * 70)
    print("PART 5: Crisis Period MDD Analysis")
    print("=" * 70)

    crisis_results = {}

    for crisis_name, (cstart, cend) in CRISIS_PERIODS.items():
        mask = (df.index >= cstart) & (df.index <= cend)
        if mask.sum() < 10:
            continue

        sub_vix = df.loc[mask, "VIX"].values
        sub_rport = df.loc[mask, "r_port"].values
        sub_rf = df.loc[mask, "rf_daily"].values
        sub_strats = compute_all_weights(sub_vix)

        crisis_results[crisis_name] = {}
        for name in all_strategies:
            if name in sub_strats:
                w, lev = sub_strats[name]
                r = compute_strategy_returns(sub_rport, w, lev, sub_rf, tx_cost=0.001)
                cum = np.cumprod(1 + r)
                peak = np.maximum.accumulate(cum)
                dd = cum / peak - 1
                crisis_results[crisis_name][name] = {
                    "mdd": round(float(np.min(dd)) * 100, 2),
                    "total_return": round(float(cum[-1] - 1) * 100, 2),
                    "avg_vix": round(float(np.mean(sub_vix)), 1),
                }

    print(f"\n{'Strategy':<20}", end="")
    for crisis in CRISIS_PERIODS:
        print(f" {crisis:>15}", end="")
    print()
    print("-" * (20 + 16 * len(CRISIS_PERIODS)))

    for name in all_strategies:
        print(f"{name:<20}", end="")
        for crisis in CRISIS_PERIODS:
            if crisis in crisis_results and name in crisis_results[crisis]:
                mdd = crisis_results[crisis][name]["mdd"]
                print(f" {mdd:>14.1f}%", end="")
            else:
                print(f" {'N/A':>15}", end="")
        print()

    # ============================================================
    #  Part 6: Transaction Cost Sensitivity
    # ============================================================
    print("\n" + "=" * 70)
    print("PART 6: Transaction Cost Sensitivity")
    print("=" * 70)

    tx_levels = [0, 0.0005, 0.001, 0.002, 0.005, 0.01]
    tx_sensitivity = {}

    for name in all_strategies:
        if name in strategies:
            w, lev = strategies[name]
            tx_sensitivity[name] = {}
            for tx in tx_levels:
                r = compute_strategy_returns(r_port, w, lev, rf_daily, tx_cost=tx)
                m = compute_metrics(r, rf_daily)
                if m:
                    tx_sensitivity[name][f"{tx*10000:.0f}bp"] = m["sharpe"]

    print(f"\n{'Strategy':<20}", end="")
    for tx in tx_levels:
        print(f" {tx*10000:>6.0f}bp", end="")
    print()
    print("-" * (20 + 8 * len(tx_levels)))

    for name in all_strategies:
        if name in tx_sensitivity:
            print(f"{name:<20}", end="")
            for tx in tx_levels:
                key = f"{tx*10000:.0f}bp"
                if key in tx_sensitivity[name]:
                    print(f" {tx_sensitivity[name][key]:>7.3f}", end="")
            print()

    # ============================================================
    #  Part 7: VIX Regime Breakdown
    # ============================================================
    print("\n" + "=" * 70)
    print("PART 7: VIX Regime Performance Breakdown")
    print("=" * 70)

    regimes = {
        "Ultra-Low (<12)": vix < 12,
        "Low (12-15)": (vix >= 12) & (vix < 15),
        "Normal (15-20)": (vix >= 15) & (vix < 20),
        "Elevated (20-25)": (vix >= 20) & (vix < 25),
        "High (25-30)": (vix >= 25) & (vix < 30),
        "Crisis (>30)": vix >= 30,
    }

    regime_results = {}
    for regime_name, mask_arr in regimes.items():
        n_days = int(mask_arr.sum())
        if n_days < 20:
            continue
        regime_results[regime_name] = {"n_days": n_days, "pct": round(n_days / len(vix) * 100, 1)}
        for sname in all_strategies:
            if sname in strategies:
                w, lev = strategies[sname]
                r = compute_strategy_returns(r_port, w, lev, rf_daily, tx_cost=0.001)
                regime_r = r[mask_arr]
                regime_results[regime_name][sname] = round(float(np.mean(regime_r)) * 252 * 100, 2)

    print(f"\n{'Regime':<20} {'Days':>6} {'%':>5}", end="")
    for s in ["BuyHold", "12_VIX", "Piecewise", "H2_Adaptive_Tier", "H5_Conviction"]:
        print(f" {s:>15}", end="")
    print()
    print("-" * 90)

    for regime_name, data_r in regime_results.items():
        print(f"{regime_name:<20} {data_r['n_days']:>6} {data_r['pct']:>4.1f}%", end="")
        for s in ["BuyHold", "12_VIX", "Piecewise", "H2_Adaptive_Tier", "H5_Conviction"]:
            if s in data_r:
                print(f" {data_r[s]:>14.1f}%", end="")
            else:
                print(f" {'N/A':>15}", end="")
        print()

    # ============================================================
    #  Part 8: Best Hybrid Identification & Summary
    # ============================================================
    print("\n" + "=" * 70)
    print("PART 8: Summary — Best Hybrid Identification")
    print("=" * 70)

    # Rank hybrids by multiple criteria
    hybrid_scores = {}
    for h in hybrids:
        if h not in full_results:
            continue
        m = full_results[h]

        # Score: higher Sharpe, higher Calmar, lower MDD, more OOS wins
        oos_wins = oos_summary[h]["wins_vs_bh"] if h in oos_summary else 0
        n_oos = oos_summary[h]["n_periods"] if h in oos_summary else 1

        # Harvey pass vs any benchmark?
        harvey_any = any(
            stat_tests[h][b]["harvey_pass"]
            for b in benchmarks if b in stat_tests.get(h, {})
        )

        score = (
            m["sharpe"] * 2.0 +        # Sharpe is primary
            m["calmar"] * 0.5 +         # Calmar bonus
            (oos_wins / n_oos) * 1.0 +  # OOS consistency
            (1.0 if harvey_any else 0)   # Harvey bonus
        )

        hybrid_scores[h] = {
            "score": round(score, 3),
            "sharpe": m["sharpe"],
            "mdd": m["mdd"],
            "calmar": m["calmar"],
            "cagr": m["cagr"],
            "oos_wins": oos_wins,
            "n_oos": n_oos,
            "harvey_any_pass": harvey_any,
        }

    # Sort by score
    ranked = sorted(hybrid_scores.items(), key=lambda x: x[1]["score"], reverse=True)

    print(f"\n{'Rank':<5} {'Strategy':<22} {'Score':>7} {'Sharpe':>8} {'CAGR%':>8} {'MDD%':>8} {'Calmar':>8} {'OOS':>6} {'Harvey':>8}")
    print("-" * 85)
    for i, (name, sc) in enumerate(ranked, 1):
        print(f"{i:<5} {name:<22} {sc['score']:>7.3f} {sc['sharpe']:>8.3f} {sc['cagr']:>7.1f}% "
              f"{sc['mdd']:>7.1f}% {sc['calmar']:>8.3f} {sc['oos_wins']:>2}/{sc['n_oos']} "
              f"{'PASS' if sc['harvey_any_pass'] else 'FAIL':>8}")

    best_name, best_info = ranked[0]
    print(f"\n  ★ BEST HYBRID: {best_name} (score={best_info['score']:.3f})")
    print(f"    Sharpe={best_info['sharpe']:.3f}, CAGR={best_info['cagr']:.1f}%, "
          f"MDD={best_info['mdd']:.1f}%, Calmar={best_info['calmar']:.3f}")

    # Key comparison: best hybrid vs best individual
    best_individual_sharpe = max(full_results[b]["sharpe"] for b in benchmarks if b in full_results and b != "BuyHold")
    best_individual_name = max(
        [b for b in benchmarks if b in full_results and b != "BuyHold"],
        key=lambda b: full_results[b]["sharpe"]
    )

    improvement = best_info["sharpe"] - best_individual_sharpe
    print(f"\n  vs Best Individual ({best_individual_name}, Sharpe={best_individual_sharpe:.3f}):")
    print(f"    Sharpe improvement: {improvement:+.3f}")
    print(f"    Answer to key question: Combination {'IS' if improvement > 0 else 'is NOT'} better than individual")

    # ============================================================
    #  Save Results
    # ============================================================
    end_time = datetime.now(timezone.utc)

    results = {
        "experiment_id": "k595",
        "title": "K595: Hybrid Multi-Strategy Portfolio — Combining validated strategies",
        "description": "5 hybrid strategies combining Piecewise VT, 12/VIX, and VIX-Conditional Leverage",
        "data_source": "yfinance (SPY, GLD, ^VIX, ^IRX), 2005-2026",
        "methodology": {
            "strategies": {
                "H1_Staircase": "50% Piecewise + 50% Standard 12/VIX",
                "H2_Adaptive_Tier": "VIX<15→Leverage, VIX 15-20→12/VIX, VIX>20→Piecewise",
                "H3_Risk_Budget": "60% 12/VIX (core) + 40% Piecewise (satellite)",
                "H4_Max_of_Two": "MAX(PW weight, Standard weight × 0.5)",
                "H5_Conviction": "PW_weight × Leverage_multiplier",
            },
            "portfolio": "50/50 SPY/GLD",
            "tx_cost_default": "10bp",
            "borrowing_spread": "50bp above risk-free",
            "n_bootstrap": N_BOOTSTRAP,
            "n_oos_periods": len(OOS_PERIODS),
        },
        "references": [
            "Moreira & Muir (2017, JoF): Volatility-managed portfolios",
            "Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing",
            "Harvey (2016, JoF): t>3 threshold",
            "K548/K551: VIX-Conditional Leverage (Harvey t=7.90)",
            "K568/K569: Piecewise VT (6/8 pass, MDD -0.56% GFC)",
        ],
        "full_sample": {},
        "statistical_tests": stat_tests,
        "cross_oos": oos_summary,
        "bootstrap": bootstrap_results,
        "crisis_mdd": crisis_results,
        "tx_sensitivity": tx_sensitivity,
        "regime_breakdown": regime_results,
        "hybrid_ranking": {name: info for name, info in ranked},
        "best_hybrid": best_name,
        "best_hybrid_info": best_info,
        "key_finding": f"Best hybrid: {best_name} (Sharpe={best_info['sharpe']:.3f}, "
                       f"vs best individual {best_individual_name} Sharpe={best_individual_sharpe:.3f}, "
                       f"improvement={improvement:+.3f})",
        "combination_better_than_individual": improvement > 0,
        "timestamp": start_time.isoformat(),
        "runtime_seconds": (end_time - start_time).total_seconds(),
    }

    # Add full sample results (without numpy arrays)
    for name, m in full_results.items():
        results["full_sample"][name] = m

    # Save
    out_path = Path(__file__).parent / "k595_hybrid_multi_strategy_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    print(f"\n  Runtime: {(end_time - start_time).total_seconds():.1f}s")
    print("=" * 70)

    return results


if __name__ == "__main__":
    main()
