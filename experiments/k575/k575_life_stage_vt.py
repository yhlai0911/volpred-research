#!/usr/bin/env python3
"""K575: VT Strategy Tiers for Different Life Stages
=====================================================

Motivation:
    We have 3 validated strategy tiers from K574:
    - Growth: VIX-Conditional Leverage (VCL) — CAGR 19%, Sharpe 1.55, MDD -12.3%
    - Standard: 12/VIX VT — CAGR 13.1%, Sharpe 1.41, MDD -9.6%
    - Conservative: Piecewise (PW) — Sharpe 1.88, MDD -4.9%, worst year +0.2%

    This experiment creates a comprehensive life-stage framework matching strategy
    tier to investor profile, with Monte Carlo simulation of wealth paths.

Design:
    1. Data: SPY + GLD + VIX from yfinance (2005-2026, ~21 years)
    2. Investor profiles:
       a. Young Accumulator (25-40): VCL growth, 30yr horizon, $100K + $1K/mo
       b. Mid-Career (40-55): Standard 12/VIX VT, 20yr horizon, $100K + $1K/mo
       c. Pre-Retirement (55-65): Piecewise Conservative, 10yr, $100K lump sum
       d. Retiree (65+): Piecewise + 4% withdrawal, 30yr, $1M
       e. "Wrong strategy" counterfactuals for each profile
    3. Monte Carlo: 1000 block bootstrap paths (block=12 months)
    4. Key output: strategy recommendation matrix by age/risk tolerance

References:
    - Moreira & Muir (2017, JoF): Volatility-managed portfolios
    - K548/K551: VIX-Conditional Leverage validated
    - K569: Piecewise VT validated
    - K574: Complete 3-tier backtest
    - K79: VT + 4% Withdrawal Rule Monte Carlo
    - Bengen (1994): 4% safe withdrawal rate

Data source: yfinance (SPY, GLD, ^VIX, ^IRX), 2005-2026
Author: [Proposed: User, Executed: Claude] — VolPred Research System
"""
from __future__ import annotations

import json
import sys
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# ============================================================
#  Constants
# ============================================================
RF_ANNUAL = 0.02
TX_COST_BPS = 5
BORROWING_SPREAD = 0.005
ANNUALIZE = np.sqrt(252)
TRADING_DAYS = 252

START_DATE = "2004-12-01"
END_DATE = "2026-03-28"
ANALYSIS_START = "2005-06-01"

N_SIMULATIONS = 1000
BLOCK_SIZE = 252  # 12 months block bootstrap
np.random.seed(42)

# Strategy parameters (from K548/K569/K574)
PW_C1 = 12.0
PW_C2 = 20.0
VCL_VIX_LOW = 15.0
VCL_VIX_HIGH = 25.0
VCL_LEV_HIGH = 1.5
VCL_LEV_LOW = 1.0

# Investor profiles
PROFILES = {
    "young_accumulator": {
        "label": "Young Accumulator (25-40)",
        "short_label": "Young (25-40)",
        "strategy": "VCL",          # Growth tier
        "horizon_years": 30,
        "initial_capital": 100_000,
        "monthly_contribution": 1_000,
        "withdrawal_rate": 0.0,
        "description": "Maximise long-term wealth. High risk tolerance, long horizon.",
        "wrong_strategy": "PW_Cons",  # Too conservative for young
    },
    "mid_career": {
        "label": "Mid-Career (40-55)",
        "short_label": "Mid (40-55)",
        "strategy": "VT_12VIX",      # Standard tier
        "horizon_years": 20,
        "initial_capital": 100_000,
        "monthly_contribution": 1_000,
        "withdrawal_rate": 0.0,
        "description": "Balance growth and protection. Moderate risk tolerance.",
        "wrong_strategy": "VCL",  # Too aggressive
    },
    "pre_retirement": {
        "label": "Pre-Retirement (55-65)",
        "short_label": "Pre-Ret (55-65)",
        "strategy": "PW_Cons",       # Conservative tier
        "horizon_years": 10,
        "initial_capital": 100_000,
        "monthly_contribution": 0,
        "withdrawal_rate": 0.0,
        "description": "Preserve capital approaching retirement. Low risk tolerance.",
        "wrong_strategy": "VCL",  # Far too aggressive
    },
    "retiree": {
        "label": "Retiree (65+)",
        "short_label": "Retiree (65+)",
        "strategy": "PW_Cons",       # Conservative tier + withdrawal
        "horizon_years": 30,
        "initial_capital": 1_000_000,
        "monthly_contribution": 0,
        "withdrawal_rate": 0.04,      # 4% SWR
        "description": "Sustain withdrawals without ruin. Capital preservation paramount.",
        "wrong_strategy": "BH_SPY",  # No VT protection
    },
}

# Chart output
CHART_DIR = Path(__file__).resolve().parent / "k575_charts"
CHART_DIR.mkdir(exist_ok=True)

# ============================================================
#  Data Download
# ============================================================
def download_data() -> pd.DataFrame:
    """Download SPY, GLD, VIX, IRX from yfinance."""
    print("=" * 80)
    print("K575: VT STRATEGY TIERS FOR DIFFERENT LIFE STAGES")
    print("=" * 80)
    print(f"\n[1/7] Downloading data from yfinance ({START_DATE} to {END_DATE})...")

    tickers = ["SPY", "GLD", "^VIX", "^IRX"]
    raw = yf.download(tickers, start=START_DATE, end=END_DATE, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].copy()

    df = pd.DataFrame(index=close.index)
    df["spy_close"] = close["SPY"]
    df["gld_close"] = close["GLD"]
    df["vix"] = close["^VIX"]

    if "^IRX" in close.columns:
        df["rf_annual"] = close["^IRX"] / 100.0
        df["rf_annual"] = df["rf_annual"].ffill().fillna(RF_ANNUAL)
    else:
        df["rf_annual"] = RF_ANNUAL

    df = df.dropna(subset=["spy_close", "gld_close", "vix"])

    df["spy_ret"] = df["spy_close"].pct_change()
    df["gld_ret"] = df["gld_close"].pct_change()
    df["rf_daily"] = df["rf_annual"] / TRADING_DAYS

    df = df.loc[ANALYSIS_START:]
    df = df.dropna(subset=["spy_ret", "gld_ret"])

    print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Trading days: {len(df)}")
    print(f"  VIX range: {df['vix'].min():.1f} - {df['vix'].max():.1f} (mean {df['vix'].mean():.1f})")

    return df


# ============================================================
#  Weight Functions (from K574)
# ============================================================
def w_12vix(vix: np.ndarray) -> np.ndarray:
    return np.clip(12.0 / vix, 0.0, 1.0)


def w_piecewise(vix: np.ndarray) -> np.ndarray:
    return np.clip(
        np.where(vix < PW_C1, 1.0,
                 np.where(vix > PW_C2, 0.0,
                          (PW_C2 - vix) / (PW_C2 - PW_C1))),
        0.0, 1.0
    )


def leverage_factor(vix: np.ndarray) -> np.ndarray:
    return np.where(
        vix < VCL_VIX_LOW, VCL_LEV_HIGH,
        np.where(vix > VCL_VIX_HIGH, VCL_LEV_LOW,
                 VCL_LEV_HIGH + (VCL_LEV_LOW - VCL_LEV_HIGH) *
                 (vix - VCL_VIX_LOW) / (VCL_VIX_HIGH - VCL_VIX_LOW))
    )


# ============================================================
#  Strategy Daily Return Computation
# ============================================================
def compute_strategy_daily_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute daily returns for all strategies from historical data."""
    print("\n[2/7] Computing strategy daily returns...")

    vix = df["vix"].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values
    rf_daily = df["rf_daily"].values
    rf_annual = df["rf_annual"].values

    results = pd.DataFrame(index=df.index)

    # Buy & Hold SPY
    results["BH_SPY"] = spy_ret

    # Buy & Hold 50/50
    results["BH_5050"] = 0.5 * spy_ret + 0.5 * gld_ret

    # Standard 12/VIX VT
    w_vt = w_12vix(vix)
    results["VT_12VIX"] = w_vt * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - w_vt) * rf_daily

    # VIX-Conditional Leverage
    lev = leverage_factor(vix)
    vt_base_ret = w_vt * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - w_vt) * rf_daily
    borrowing_cost_daily = (rf_annual + BORROWING_SPREAD) / TRADING_DAYS
    results["VCL"] = lev * vt_base_ret - (lev - 1) * borrowing_cost_daily

    # Piecewise Conservative
    w_pw = w_piecewise(vix)
    results["PW_Cons"] = w_pw * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - w_pw) * rf_daily

    # Also store VIX for bootstrap block correlation
    results["vix"] = vix

    for col in ["BH_SPY", "BH_5050", "VT_12VIX", "VCL", "PW_Cons"]:
        ann_ret = results[col].mean() * TRADING_DAYS
        ann_vol = results[col].std() * ANNUALIZE
        print(f"    {col}: CAGR≈{ann_ret*100:.1f}%, Vol≈{ann_vol*100:.1f}%")

    return results


# ============================================================
#  Block Bootstrap
# ============================================================
def block_bootstrap_paths(daily_returns: pd.DataFrame,
                          n_sims: int,
                          horizon_days: int,
                          block_size: int = BLOCK_SIZE) -> dict[str, np.ndarray]:
    """Generate n_sims bootstrap paths of horizon_days length for each strategy.

    Returns dict: strategy_name -> array of shape (n_sims, horizon_days).
    Uses correlated block bootstrap (same blocks drawn for all strategies).
    """
    strategy_cols = ["BH_SPY", "BH_5050", "VT_12VIX", "VCL", "PW_Cons"]
    n_obs = len(daily_returns)
    n_blocks = (horizon_days + block_size - 1) // block_size

    # Pre-extract numpy arrays for speed
    data = {col: daily_returns[col].values for col in strategy_cols}

    # Generate all block starting indices at once
    max_start = n_obs - block_size
    if max_start < 1:
        raise ValueError(f"Not enough data ({n_obs} days) for block size {block_size}")
    block_starts = np.random.randint(0, max_start, size=(n_sims, n_blocks))

    # Build paths for all strategies (vectorized)
    result = {}
    for col in strategy_cols:
        ret_arr = data[col]
        paths = np.empty((n_sims, n_blocks * block_size))
        for b in range(n_blocks):
            starts = block_starts[:, b]
            for i in range(n_sims):
                paths[i, b * block_size:(b + 1) * block_size] = ret_arr[starts[i]:starts[i] + block_size]
        result[col] = paths[:, :horizon_days]

    return result


# ============================================================
#  Simulate Wealth Path for a Profile
# ============================================================
def simulate_profile(profile_key: str,
                     profile: dict,
                     daily_returns: pd.DataFrame) -> dict:
    """Run Monte Carlo simulation for a single investor profile.

    Returns summary statistics and key percentiles.
    """
    strategy = profile["strategy"]
    wrong_strategy = profile["wrong_strategy"]
    horizon_years = profile["horizon_years"]
    horizon_days = horizon_years * TRADING_DAYS
    initial = profile["initial_capital"]
    monthly_contrib = profile["monthly_contribution"]
    withdrawal_rate = profile["withdrawal_rate"]

    print(f"\n  Simulating: {profile['label']} (strategy={strategy}, horizon={horizon_years}yr)...")

    # Generate bootstrap paths for all strategies
    paths = block_bootstrap_paths(daily_returns, N_SIMULATIONS, horizon_days)

    # Which strategies to evaluate: recommended + wrong + B&H baseline
    strategies_to_test = [strategy, wrong_strategy, "BH_SPY"]
    if "BH_5050" not in strategies_to_test:
        strategies_to_test.append("BH_5050")
    # Remove duplicates while preserving order
    strategies_to_test = list(dict.fromkeys(strategies_to_test))

    results = {}

    for strat in strategies_to_test:
        strat_paths = paths[strat]  # (n_sims, horizon_days)

        # Simulate wealth paths
        wealth = np.empty((N_SIMULATIONS, horizon_days + 1))
        wealth[:, 0] = initial

        # Monthly contribution schedule (every 21 trading days)
        contrib_schedule = set()
        if monthly_contrib > 0:
            for m in range(1, horizon_years * 12 + 1):
                day = m * 21
                if day < horizon_days:
                    contrib_schedule.add(day)

        # Annual withdrawal schedule (every 252 trading days)
        withdrawal_schedule = set()
        if withdrawal_rate > 0:
            for y in range(1, horizon_years + 1):
                day = y * TRADING_DAYS
                if day < horizon_days:
                    withdrawal_schedule.add(day)

        # Simulate day by day (vectorized across simulations)
        for t in range(horizon_days):
            daily_ret = strat_paths[:, t]
            wealth[:, t + 1] = wealth[:, t] * (1 + daily_ret)

            # Monthly contribution
            if t in contrib_schedule:
                wealth[:, t + 1] += monthly_contrib

            # Annual withdrawal (inflation-adjusted at 2.5%)
            if t in withdrawal_schedule:
                year_num = t // TRADING_DAYS
                inflation_adj = (1.025) ** year_num
                annual_withdrawal = initial * withdrawal_rate * inflation_adj
                wealth[:, t + 1] -= annual_withdrawal

        # Compute metrics
        terminal_wealth = wealth[:, -1]

        # Ruin = wealth drops below 0
        ruin_count = 0
        first_ruin_year = []
        for i in range(N_SIMULATIONS):
            ruin_idx = np.where(wealth[i, :] <= 0)[0]
            if len(ruin_idx) > 0:
                ruin_count += 1
                first_ruin_year.append(ruin_idx[0] / TRADING_DAYS)

        # MDD per simulation
        mdds = []
        for i in range(N_SIMULATIONS):
            peak = np.maximum.accumulate(wealth[i, :])
            dd = (wealth[i, :] - peak) / np.where(peak > 0, peak, 1)
            mdds.append(dd.min())
        mdds = np.array(mdds)

        # Total contributions
        total_contrib = initial
        if monthly_contrib > 0:
            total_contrib += monthly_contrib * min(horizon_years * 12, len(contrib_schedule))

        # Total withdrawals
        total_withdrawn = 0
        if withdrawal_rate > 0:
            for y in range(1, horizon_years + 1):
                inflation_adj = (1.025) ** y
                total_withdrawn += initial * withdrawal_rate * inflation_adj

        # Annualized return from terminal wealth
        positive_terminal = terminal_wealth[terminal_wealth > 0]
        if len(positive_terminal) > 0:
            if monthly_contrib > 0:
                # For DCA, use money-weighted approximation
                median_terminal = np.median(positive_terminal)
                ann_return = (median_terminal / total_contrib) ** (1 / horizon_years) - 1
            else:
                ann_return = float(np.median((positive_terminal / initial) ** (1 / horizon_years) - 1))
        else:
            ann_return = -1.0

        is_recommended = (strat == strategy)
        is_wrong = (strat == wrong_strategy)

        results[strat] = {
            "is_recommended": is_recommended,
            "is_wrong_strategy": is_wrong,
            "n_simulations": N_SIMULATIONS,
            "horizon_years": horizon_years,
            "initial_capital": initial,
            "monthly_contribution": monthly_contrib,
            "withdrawal_rate": withdrawal_rate,
            "total_contributed": float(total_contrib),
            "total_withdrawn": float(total_withdrawn),
            "terminal_wealth": {
                "median": float(np.median(terminal_wealth)),
                "mean": float(np.mean(terminal_wealth)),
                "p5": float(np.percentile(terminal_wealth, 5)),
                "p10": float(np.percentile(terminal_wealth, 10)),
                "p25": float(np.percentile(terminal_wealth, 25)),
                "p75": float(np.percentile(terminal_wealth, 75)),
                "p90": float(np.percentile(terminal_wealth, 90)),
                "p95": float(np.percentile(terminal_wealth, 95)),
                "min": float(np.min(terminal_wealth)),
                "max": float(np.max(terminal_wealth)),
            },
            "annualized_return_median": float(ann_return),
            "probability_of_ruin": float(ruin_count / N_SIMULATIONS),
            "ruin_count": ruin_count,
            "avg_ruin_year": float(np.mean(first_ruin_year)) if first_ruin_year else None,
            "mdd": {
                "median": float(np.median(mdds)),
                "p5_worst": float(np.percentile(mdds, 5)),
                "p95_best": float(np.percentile(mdds, 95)),
                "mean": float(np.mean(mdds)),
            },
            "wealth_ratio_vs_invested": float(np.median(terminal_wealth) / total_contrib) if total_contrib > 0 else 0,
        }

        label = "✓ RECOMMENDED" if is_recommended else ("✗ WRONG" if is_wrong else "  baseline")
        print(f"    [{label}] {strat}: median=${np.median(terminal_wealth):,.0f}, "
              f"P5=${np.percentile(terminal_wealth, 5):,.0f}, "
              f"MDD={np.median(mdds)*100:.1f}%, "
              f"ruin={ruin_count/N_SIMULATIONS*100:.1f}%")

    return results


# ============================================================
#  "Wrong Strategy" Cost Analysis
# ============================================================
def compute_wrong_strategy_cost(profile_results: dict, profile: dict) -> dict:
    """Compute the cost of using the wrong strategy vs recommended."""
    rec = profile["strategy"]
    wrong = profile["wrong_strategy"]

    if rec not in profile_results or wrong not in profile_results:
        return {}

    rec_data = profile_results[rec]
    wrong_data = profile_results[wrong]

    rec_median = rec_data["terminal_wealth"]["median"]
    wrong_median = wrong_data["terminal_wealth"]["median"]

    wealth_gap = rec_median - wrong_median
    wealth_ratio = rec_median / wrong_median if wrong_median > 0 else float("inf")

    mdd_gap = rec_data["mdd"]["median"] - wrong_data["mdd"]["median"]
    ruin_gap = rec_data["probability_of_ruin"] - wrong_data["probability_of_ruin"]

    return {
        "recommended": rec,
        "wrong": wrong,
        "wealth_gap_median": float(wealth_gap),
        "wealth_ratio": float(wealth_ratio),
        "mdd_difference": float(mdd_gap),
        "ruin_rate_difference": float(ruin_gap),
        "wrong_is_better_pct_of_sims": None,  # placeholder, computed below
    }


# ============================================================
#  Charts
# ============================================================
def plot_terminal_wealth_distribution(all_results: dict):
    """Fan chart of terminal wealth by profile."""
    print("\n[5/7] Generating charts...")

    fig, axes = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle("K575: Terminal Wealth Distribution by Life Stage\n"
                 "(1000 Bootstrap Simulations, Block=12 Months)",
                 fontsize=14, fontweight="bold")

    profile_keys = list(PROFILES.keys())

    for idx, pkey in enumerate(profile_keys):
        ax = axes[idx // 2, idx % 2]
        profile = PROFILES[pkey]
        pres = all_results[pkey]

        strategies = list(pres.keys())
        labels = []
        medians = []
        p5s = []
        p95s = []
        p25s = []
        p75s = []
        colors = []

        color_map = {
            "VCL": "#2196F3",
            "VT_12VIX": "#4CAF50",
            "PW_Cons": "#FF9800",
            "BH_SPY": "#9E9E9E",
            "BH_5050": "#795548",
        }

        for s in strategies:
            tw = pres[s]["terminal_wealth"]
            labels.append(s)
            medians.append(tw["median"])
            p5s.append(tw["p5"])
            p95s.append(tw["p95"])
            p25s.append(tw["p25"])
            p75s.append(tw["p75"])
            colors.append(color_map.get(s, "#607D8B"))

        x = np.arange(len(labels))
        width = 0.5

        # Draw bars for median
        bars = ax.bar(x, medians, width, color=colors, alpha=0.8, edgecolor="black", linewidth=0.5)

        # Error bars for P5-P95
        for i in range(len(labels)):
            ax.plot([i, i], [p5s[i], p95s[i]], color="black", linewidth=1.5, zorder=5)
            ax.plot([i - 0.1, i + 0.1], [p5s[i], p5s[i]], color="black", linewidth=1.5, zorder=5)
            ax.plot([i - 0.1, i + 0.1], [p95s[i], p95s[i]], color="black", linewidth=1.5, zorder=5)
            # P25-P75 thicker bar
            ax.plot([i, i], [p25s[i], p75s[i]], color="black", linewidth=4, alpha=0.3, zorder=4)

        # Mark recommended strategy
        rec_idx = labels.index(profile["strategy"]) if profile["strategy"] in labels else -1
        if rec_idx >= 0:
            ax.bar(x[rec_idx:rec_idx+1], [medians[rec_idx]], width,
                   edgecolor="#00C853", linewidth=3, fill=False, zorder=6)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9)
        contrib_str = f" + ${profile['monthly_contribution']:,}/mo" if profile['monthly_contribution'] > 0 else ""
        swr_str = f", {profile['withdrawal_rate']*100:.0f}% SWR" if profile['withdrawal_rate'] > 0 else ""
        ax.set_title(f"{profile['label']}\n({profile['horizon_years']}yr horizon, "
                     f"${profile['initial_capital']:,} initial{contrib_str}{swr_str})",
                     fontsize=10)
        ax.set_ylabel("Terminal Wealth ($)")
        ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M" if x >= 1e6 else f"${x/1e3:.0f}K"))

        # Add text annotations
        for i, (med, lab) in enumerate(zip(medians, labels)):
            if med >= 0:
                ax.text(i, med * 1.05, f"${med/1e6:.2f}M" if med >= 1e6 else f"${med/1e3:.0f}K",
                        ha="center", va="bottom", fontsize=8, fontweight="bold")

    plt.tight_layout()
    path = CHART_DIR / "k575_terminal_wealth_distribution.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_wrong_strategy_cost(all_results: dict, wrong_costs: dict):
    """Bar chart showing cost of wrong strategy."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("K575: Cost of Using the Wrong Strategy\n"
                 "Recommended (green) vs Wrong Choice (red)",
                 fontsize=13, fontweight="bold")

    # Panel 1: Wealth Gap
    ax = axes[0]
    profile_keys = list(PROFILES.keys())
    x = np.arange(len(profile_keys))
    short_labels = [PROFILES[k]["short_label"] for k in profile_keys]

    rec_medians = []
    wrong_medians = []
    for pkey in profile_keys:
        rec_strat = PROFILES[pkey]["strategy"]
        wrong_strat = PROFILES[pkey]["wrong_strategy"]
        rec_medians.append(all_results[pkey][rec_strat]["terminal_wealth"]["median"])
        wrong_medians.append(all_results[pkey][wrong_strat]["terminal_wealth"]["median"])

    width = 0.35
    ax.bar(x - width / 2, rec_medians, width, color="#4CAF50", label="Recommended", alpha=0.85)
    ax.bar(x + width / 2, wrong_medians, width, color="#F44336", label="Wrong", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, fontsize=9)
    ax.set_ylabel("Median Terminal Wealth ($)")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M" if abs(x) >= 1e6 else f"${x/1e3:.0f}K"))
    ax.legend(fontsize=9)
    ax.set_title("Median Terminal Wealth")

    # Panel 2: MDD comparison
    ax = axes[1]
    rec_mdds = []
    wrong_mdds = []
    for pkey in profile_keys:
        rec_strat = PROFILES[pkey]["strategy"]
        wrong_strat = PROFILES[pkey]["wrong_strategy"]
        rec_mdds.append(abs(all_results[pkey][rec_strat]["mdd"]["median"]) * 100)
        wrong_mdds.append(abs(all_results[pkey][wrong_strat]["mdd"]["median"]) * 100)

    ax.bar(x - width / 2, rec_mdds, width, color="#4CAF50", label="Recommended", alpha=0.85)
    ax.bar(x + width / 2, wrong_mdds, width, color="#F44336", label="Wrong", alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(short_labels, fontsize=9)
    ax.set_ylabel("Median Max Drawdown (%)")
    ax.legend(fontsize=9)
    ax.set_title("Median Maximum Drawdown")

    plt.tight_layout()
    path = CHART_DIR / "k575_wrong_strategy_cost.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_recommendation_matrix():
    """Visual recommendation matrix: age vs risk tolerance."""
    fig, ax = plt.subplots(figsize=(12, 7))

    # Matrix: rows = risk tolerance, cols = age bracket
    age_brackets = ["25-35", "35-45", "45-55", "55-65", "65-75", "75+"]
    risk_levels = ["Aggressive", "Moderate", "Conservative"]

    # Strategy assignments
    matrix = [
        # Aggressive row
        ["VCL", "VCL", "VT 12/VIX", "VT 12/VIX", "VT 12/VIX", "PW Cons"],
        # Moderate row
        ["VT 12/VIX", "VT 12/VIX", "VT 12/VIX", "PW Cons", "PW Cons", "PW Cons"],
        # Conservative row
        ["VT 12/VIX", "PW Cons", "PW Cons", "PW Cons", "PW Cons", "PW Cons"],
    ]

    color_map_matrix = {
        "VCL": "#2196F3",
        "VT 12/VIX": "#4CAF50",
        "PW Cons": "#FF9800",
    }

    # Draw grid
    for i, risk in enumerate(risk_levels):
        for j, age in enumerate(age_brackets):
            strat = matrix[i][j]
            color = color_map_matrix.get(strat, "#BDBDBD")
            rect = plt.Rectangle((j, 2 - i), 1, 1, facecolor=color, alpha=0.7,
                                 edgecolor="white", linewidth=2)
            ax.add_patch(rect)
            ax.text(j + 0.5, 2.5 - i, strat, ha="center", va="center",
                    fontsize=11, fontweight="bold", color="black")

    ax.set_xlim(0, len(age_brackets))
    ax.set_ylim(0, len(risk_levels))
    ax.set_xticks([i + 0.5 for i in range(len(age_brackets))])
    ax.set_xticklabels(age_brackets, fontsize=11)
    ax.set_yticks([i + 0.5 for i in range(len(risk_levels))])
    ax.set_yticklabels(list(reversed(risk_levels)), fontsize=11)
    ax.set_xlabel("Age Bracket", fontsize=12)
    ax.set_ylabel("Risk Tolerance", fontsize=12)
    ax.set_title("K575: VT Strategy Recommendation Matrix\n"
                 "Which Tier for Which Investor?", fontsize=14, fontweight="bold")

    # Legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor="#2196F3", alpha=0.7, edgecolor="black", label="VCL (Growth: CAGR 19%, MDD -12%)"),
        Patch(facecolor="#4CAF50", alpha=0.7, edgecolor="black", label="VT 12/VIX (Standard: CAGR 13%, MDD -10%)"),
        Patch(facecolor="#FF9800", alpha=0.7, edgecolor="black", label="PW Cons (Conservative: CAGR 10%, MDD -5%)"),
    ]
    ax.legend(handles=legend_elements, loc="lower center", bbox_to_anchor=(0.5, -0.15),
              ncol=3, fontsize=9)

    plt.tight_layout()
    path = CHART_DIR / "k575_recommendation_matrix.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_retiree_survival(all_results: dict):
    """Compare retiree survival rates across strategies."""
    fig, ax = plt.subplots(figsize=(10, 6))

    pres = all_results["retiree"]
    strategies = list(pres.keys())
    labels = strategies
    ruin_rates = [pres[s]["probability_of_ruin"] * 100 for s in strategies]
    medians = [pres[s]["terminal_wealth"]["median"] for s in strategies]

    color_map = {
        "VCL": "#2196F3",
        "VT_12VIX": "#4CAF50",
        "PW_Cons": "#FF9800",
        "BH_SPY": "#9E9E9E",
        "BH_5050": "#795548",
    }
    colors = [color_map.get(s, "#607D8B") for s in strategies]

    x = np.arange(len(labels))
    width = 0.35

    ax2 = ax.twinx()

    bars1 = ax.bar(x - width / 2, ruin_rates, width, color="#F44336", alpha=0.7, label="Ruin Rate (%)")
    bars2 = ax2.bar(x + width / 2, [m / 1e6 for m in medians], width, color=colors, alpha=0.7, label="Median Terminal ($M)")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=10)
    ax.set_ylabel("Probability of Ruin (%)", color="#F44336", fontsize=11)
    ax2.set_ylabel("Median Terminal Wealth ($M)", fontsize=11)
    ax.set_title("K575: Retiree (65+) — 30yr, $1M Initial, 4% SWR\n"
                 "Ruin Rate vs Terminal Wealth by Strategy",
                 fontsize=13, fontweight="bold")

    # Annotate ruin rates
    for i, (rr, med) in enumerate(zip(ruin_rates, medians)):
        ax.text(i - width / 2, rr + 0.5, f"{rr:.1f}%", ha="center", va="bottom", fontsize=9, color="#F44336", fontweight="bold")
        ax2.text(i + width / 2, med / 1e6 + 0.1, f"${med/1e6:.1f}M", ha="center", va="bottom", fontsize=9, fontweight="bold")

    plt.tight_layout()
    path = CHART_DIR / "k575_retiree_survival.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


def plot_accumulation_growth(all_results: dict):
    """Compare accumulation profiles: young vs mid-career."""
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    fig.suptitle("K575: Wealth Accumulation — Young vs Mid-Career\n"
                 "($100K initial + $1K/month contributions)",
                 fontsize=13, fontweight="bold")

    for idx, pkey in enumerate(["young_accumulator", "mid_career"]):
        ax = axes[idx]
        profile = PROFILES[pkey]
        pres = all_results[pkey]

        strategies = list(pres.keys())
        labels = []
        wealth_ratios = []
        colors = []

        color_map = {
            "VCL": "#2196F3",
            "VT_12VIX": "#4CAF50",
            "PW_Cons": "#FF9800",
            "BH_SPY": "#9E9E9E",
            "BH_5050": "#795548",
        }

        for s in strategies:
            labels.append(s)
            wealth_ratios.append(pres[s]["wealth_ratio_vs_invested"])
            colors.append(color_map.get(s, "#607D8B"))

        x = np.arange(len(labels))
        ax.bar(x, wealth_ratios, 0.5, color=colors, alpha=0.85, edgecolor="black", linewidth=0.5)

        for i, wr in enumerate(wealth_ratios):
            ax.text(i, wr * 1.02, f"{wr:.1f}x", ha="center", va="bottom", fontsize=10, fontweight="bold")

        # Mark recommended
        rec_idx = labels.index(profile["strategy"]) if profile["strategy"] in labels else -1
        if rec_idx >= 0:
            ax.bar(x[rec_idx:rec_idx+1], [wealth_ratios[rec_idx]], 0.5,
                   edgecolor="#00C853", linewidth=3, fill=False, zorder=6)

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=9)
        ax.set_ylabel("Wealth/Total Invested Ratio")
        ax.set_title(f"{profile['label']}\n({profile['horizon_years']}yr horizon)")
        ax.axhline(y=1.0, color="gray", linestyle="--", alpha=0.5, label="Break-even")

    plt.tight_layout()
    path = CHART_DIR / "k575_accumulation_growth.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {path}")


# ============================================================
#  Main
# ============================================================
def main():
    t0 = datetime.now(timezone.utc)

    # 1. Download data
    df = download_data()

    # 2. Compute daily returns
    daily_returns = compute_strategy_daily_returns(df)

    # 3. Run simulations for each profile
    print("\n[3/7] Running Monte Carlo simulations (1000 paths each)...")
    all_results = {}
    for pkey, profile in PROFILES.items():
        all_results[pkey] = simulate_profile(pkey, profile, daily_returns)

    # 4. Compute wrong strategy costs
    print("\n[4/7] Computing wrong strategy costs...")
    wrong_costs = {}
    for pkey, profile in PROFILES.items():
        cost = compute_wrong_strategy_cost(all_results[pkey], profile)
        wrong_costs[pkey] = cost
        if cost:
            gap = cost["wealth_gap_median"]
            ratio = cost["wealth_ratio"]
            print(f"  {profile['short_label']}: "
                  f"Recommended ({cost['recommended']}) beats Wrong ({cost['wrong']}) by "
                  f"{'$'+f'{gap/1e6:.2f}M' if abs(gap) >= 1e6 else '$'+f'{gap/1e3:.0f}K'} "
                  f"({ratio:.2f}x)")

    # 5. Charts
    plot_terminal_wealth_distribution(all_results)
    plot_wrong_strategy_cost(all_results, wrong_costs)
    plot_recommendation_matrix()
    plot_retiree_survival(all_results)
    plot_accumulation_growth(all_results)

    # 6. Build summary
    print("\n[6/7] Building summary...")

    summary = {
        "experiment_id": "K575",
        "title": "VT Strategy Tiers for Different Life Stages",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance SPY+GLD+VIX+IRX 2005-2026",
        "methodology": {
            "n_simulations": N_SIMULATIONS,
            "block_size_days": BLOCK_SIZE,
            "random_seed": 42,
            "inflation_rate": 0.025,
            "tx_cost_bps": TX_COST_BPS,
            "borrowing_spread": BORROWING_SPREAD,
        },
        "profiles": {},
        "wrong_strategy_costs": wrong_costs,
        "recommendation_matrix": {
            "description": "Strategy recommendation by age bracket and risk tolerance",
            "aggressive": {
                "25-35": "VCL", "35-45": "VCL", "45-55": "VT_12VIX",
                "55-65": "VT_12VIX", "65-75": "VT_12VIX", "75+": "PW_Cons",
            },
            "moderate": {
                "25-35": "VT_12VIX", "35-45": "VT_12VIX", "45-55": "VT_12VIX",
                "55-65": "PW_Cons", "65-75": "PW_Cons", "75+": "PW_Cons",
            },
            "conservative": {
                "25-35": "VT_12VIX", "35-45": "PW_Cons", "45-55": "PW_Cons",
                "55-65": "PW_Cons", "65-75": "PW_Cons", "75+": "PW_Cons",
            },
        },
    }

    # Add profile results
    for pkey, profile in PROFILES.items():
        summary["profiles"][pkey] = {
            "label": profile["label"],
            "strategy": profile["strategy"],
            "wrong_strategy": profile["wrong_strategy"],
            "horizon_years": profile["horizon_years"],
            "initial_capital": profile["initial_capital"],
            "monthly_contribution": profile["monthly_contribution"],
            "withdrawal_rate": profile["withdrawal_rate"],
            "results": all_results[pkey],
        }

    # Key findings
    # Young accumulator: recommended vs wrong
    young_rec = all_results["young_accumulator"][PROFILES["young_accumulator"]["strategy"]]
    young_wrong = all_results["young_accumulator"][PROFILES["young_accumulator"]["wrong_strategy"]]
    retiree_rec = all_results["retiree"][PROFILES["retiree"]["strategy"]]
    retiree_wrong = all_results["retiree"][PROFILES["retiree"]["wrong_strategy"]]

    summary["key_findings"] = {
        "young_accumulator_wealth_multiplier": f"{young_rec['terminal_wealth']['median'] / young_wrong['terminal_wealth']['median']:.2f}x",
        "young_recommended_median": f"${young_rec['terminal_wealth']['median']:,.0f}",
        "young_wrong_median": f"${young_wrong['terminal_wealth']['median']:,.0f}",
        "retiree_recommended_ruin_rate": f"{retiree_rec['probability_of_ruin']*100:.1f}%",
        "retiree_wrong_ruin_rate": f"{retiree_wrong['probability_of_ruin']*100:.1f}%",
        "retiree_recommended_median_terminal": f"${retiree_rec['terminal_wealth']['median']:,.0f}",
        "strategy_matching_matters": "Using the wrong tier costs significant wealth or increases ruin risk",
    }

    # 7. Save results
    print("\n[7/7] Saving results...")
    results_path = Path(__file__).resolve().parent / "k575_life_stage_vt_results.json"
    with open(results_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"  Saved: {results_path}")

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    print(f"\n{'='*80}")
    print(f"K575 COMPLETE ({elapsed:.1f}s)")
    print(f"{'='*80}")

    # Print key findings
    print(f"\n{'='*60}")
    print("KEY FINDINGS")
    print(f"{'='*60}")

    for pkey, profile in PROFILES.items():
        rec = profile["strategy"]
        wrong = profile["wrong_strategy"]
        rec_data = all_results[pkey][rec]
        wrong_data = all_results[pkey][wrong]

        rec_med = rec_data["terminal_wealth"]["median"]
        wrong_med = wrong_data["terminal_wealth"]["median"]

        print(f"\n{profile['label']}:")
        print(f"  Recommended ({rec}): Median ${rec_med:,.0f}")
        print(f"  Wrong ({wrong}):       Median ${wrong_med:,.0f}")
        if wrong_med > 0:
            print(f"  Gap: {rec_med/wrong_med:.2f}x")
        if rec_data["probability_of_ruin"] > 0 or wrong_data["probability_of_ruin"] > 0:
            print(f"  Ruin: rec {rec_data['probability_of_ruin']*100:.1f}% vs wrong {wrong_data['probability_of_ruin']*100:.1f}%")

    print(f"\nCharts saved to: {CHART_DIR}")
    print(f"Results saved to: {results_path}")


if __name__ == "__main__":
    main()
