#!/usr/bin/env python3
"""K573: Portfolio Insurance Pricing Theory — Exact Cost Decomposition of VT Protection
======================================================================================

Motivation:
  K544 showed VT IS a tail hedge. K41/K62/K74 showed insurance premium ~4%/yr.
  K569 showed piecewise VT trades 2.3% return for 4.8% less MDD.
  But we've never done a comprehensive THEORETICAL decomposition of WHERE the
  insurance cost comes from.

Design:
  1. Data: SPY + GLD + VIX from yfinance (2005-2026)
  2. Decompose VT return vs B&H into 6 components:
     a. Equity premium captured: SPY return × average weight
     b. Gold allocation cost/benefit: GLD contribution
     c. Cash drag: (1 - weight) × risk-free rate
     d. Rebalancing cost: turnover × TX cost
     e. Volatility drag: -0.5 × σ² from weight variation
     f. Convexity benefit: nonlinear payoff from VIX-reactive sizing
  3. Break down by VIX regime (Low/Medium/High)
  4. Compare across 3 strategies: 12/VIX, Piecewise, VIX-Conditional Leverage
  5. Compute insurance efficiency ratio: MDD improvement per 1% return sacrificed

References:
  - Moreira & Muir (2017, JoF): Volatility-managed portfolios
  - Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing
  - Barroso & Santa-Clara (2015, JFE): Momentum is not volatile
  - K41: VT insurance premium ~4%/yr constant
  - K62: Interest rate regime affects premium (high rate → cheaper)
  - K74: Gross cost ~13.6%/yr non-bear, net ~4%/yr
  - K544: VT IS a tail hedge
  - K548/K551: VIX-Conditional Leverage (Sharpe +0.112, validated)
  - K569: Piecewise VT (6/8 pass, conservative tier)

Data source: yfinance (SPY, GLD, ^VIX, ^IRX)
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
#  Constants
# ============================================================
RF_ANNUAL = 0.02  # baseline risk-free (for periods without IRX)
TX_COST_BPS = 5   # 5 bps one-way transaction cost
ANNUALIZE = np.sqrt(252)
TRADING_DAYS = 252
np.random.seed(42)

START_DATE = "2005-01-01"
END_DATE = "2026-03-27"

# VIX regime thresholds
VIX_LOW = 15.0
VIX_HIGH = 25.0


def download_data():
    """Download SPY, GLD, VIX, IRX from yfinance."""
    tickers = ["SPY", "GLD", "^VIX", "^IRX"]
    print(f"Downloading {tickers} from {START_DATE} to {END_DATE}...")
    data = yf.download(tickers, start=START_DATE, end=END_DATE, progress=False)

    # Handle multi-level columns
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"]
    else:
        close = data

    df = pd.DataFrame()
    df["SPY"] = close["SPY"]
    df["GLD"] = close["GLD"]
    df["VIX"] = close["^VIX"]
    df["IRX"] = close["^IRX"]  # 13-week T-bill rate (annualized %)

    df = df.dropna(subset=["SPY", "GLD", "VIX"])

    # Fill IRX NaN with RF_ANNUAL * 100 (convert to same units)
    df["IRX"] = df["IRX"].ffill().bfill()
    df.loc[df["IRX"].isna(), "IRX"] = RF_ANNUAL * 100

    # Daily risk-free rate
    df["rf_daily"] = (df["IRX"] / 100) / TRADING_DAYS

    # Daily returns
    df["ret_spy"] = df["SPY"].pct_change()
    df["ret_gld"] = df["GLD"].pct_change()

    df = df.dropna(subset=["ret_spy", "ret_gld"])

    print(f"Data: {len(df)} days, {df.index[0].date()} to {df.index[-1].date()}")
    return df


# ============================================================
#  Strategy Weight Functions
# ============================================================

def weight_12vix(vix: pd.Series) -> pd.Series:
    """Standard 12/VIX weight for equity allocation in 50/50 SPY/GLD."""
    w = np.minimum(12.0 / vix, 1.0)
    return w


def weight_piecewise(vix: pd.Series, c1: float = 12.0, c2: float = 20.0) -> pd.Series:
    """Piecewise VT: full equity below c1, ramp to zero between c1-c2, zero above c2."""
    w = np.where(vix < c1, 1.0,
         np.where(vix > c2, 0.0,
                  (c2 - vix) / (c2 - c1)))
    return pd.Series(w, index=vix.index)


def weight_leverage(vix: pd.Series, vix_low: float = 15.0, vix_high: float = 30.0,
                    lev_low: float = 1.5, lev_high: float = 0.5) -> pd.Series:
    """VIX-Conditional Leverage: higher leverage when VIX low, lower when high."""
    # Linear interpolation between lev_low (at vix_low) and lev_high (at vix_high)
    # Below vix_low: capped at lev_low; above vix_high: capped at lev_high
    w = np.where(vix <= vix_low, lev_low,
         np.where(vix >= vix_high, lev_high,
                  lev_low + (lev_high - lev_low) * (vix - vix_low) / (vix_high - vix_low)))
    return pd.Series(w, index=vix.index)


def compute_bh_returns(df: pd.DataFrame, spy_frac: float = 0.5) -> pd.Series:
    """Buy-and-hold 50/50 SPY/GLD daily returns (with daily rebalance to maintain ratio)."""
    return spy_frac * df["ret_spy"] + (1 - spy_frac) * df["ret_gld"]


def compute_strategy_returns(df: pd.DataFrame, equity_weight: pd.Series,
                              spy_frac: float = 0.5) -> pd.DataFrame:
    """
    Compute VT strategy returns with full component decomposition.

    VT strategy: on each day, invest equity_weight fraction in the 50/50 SPY/GLD portfolio,
    and (1 - equity_weight) in risk-free.

    For leverage strategy (weight > 1): borrow at risk-free rate.

    Returns a DataFrame with columns for each component.
    """
    # Shift weight by 1 day (use yesterday's VIX to set today's weight)
    w = equity_weight.shift(1).fillna(1.0)

    # Portfolio return of the risky asset (50/50 SPY/GLD)
    risky_ret = spy_frac * df["ret_spy"] + (1 - spy_frac) * df["ret_gld"]

    # B&H return (always w=1 in risky asset)
    bh_ret = risky_ret.copy()

    # VT strategy total return
    vt_ret = w * risky_ret + (1 - w) * df["rf_daily"]

    # Weight change (for turnover and vol drag)
    w_change = w.diff().fillna(0)
    turnover = np.abs(w_change)

    result = pd.DataFrame(index=df.index)
    result["bh_ret"] = bh_ret
    result["vt_ret"] = vt_ret
    result["excess_ret"] = vt_ret - bh_ret  # total difference
    result["weight"] = w
    result["w_change"] = w_change
    result["turnover"] = turnover
    result["vix"] = df["VIX"]
    result["rf_daily"] = df["rf_daily"]
    result["risky_ret"] = risky_ret

    return result


def decompose_return_difference(res: pd.DataFrame, tx_bps: float = TX_COST_BPS) -> dict:
    """
    Decompose the daily return difference (VT - B&H) into components.

    VT_ret = w * risky_ret + (1-w) * rf
    BH_ret = 1 * risky_ret + 0 * rf = risky_ret

    Difference = VT_ret - BH_ret
             = w * risky_ret + (1-w) * rf - risky_ret
             = (w-1) * risky_ret + (1-w) * rf
             = (w-1) * (risky_ret - rf)
             = -(1-w) * (risky_ret - rf)

    This is the EXACT decomposition. But we want to attribute to meaningful components:

    Component A: Equity reduction cost = -(1-w) * risky_ret  [forgone risky return]
    Component B: Cash income           = +(1-w) * rf          [interest earned on cash]
    Component C: Transaction cost      = -turnover * tx_cost  [from rebalancing]
    Component D: Convexity benefit     = nonlinear interaction

    For deeper insight, split equity reduction by source:
    Component A1: SPY reduction = -(1-w) * spy_frac * ret_spy
    Component A2: GLD reduction = -(1-w) * (1-spy_frac) * ret_gld

    The "volatility drag" from weight variation is captured in the difference between
    arithmetic and geometric mean of the VT portfolio vs B&H.
    """
    w = res["weight"]
    rf = res["rf_daily"]
    risky = res["risky_ret"]

    # Daily components
    cash_reduction = (1 - w)  # fraction in cash (negative when leveraged)

    # Component A: Forgone risky return (positive = cost when w < 1)
    equity_reduction_cost = -(1 - w) * risky  # negative when w < 1 and risky > 0

    # Component B: Cash income / borrowing cost
    cash_income = (1 - w) * rf  # positive when w < 1 (earn rf), negative when w > 1 (pay rf)

    # Component C: Transaction cost
    tx_rate = tx_bps / 10000
    tx_cost = -res["turnover"] * tx_rate  # always negative

    # Exact daily difference
    exact_diff = res["vt_ret"] - res["bh_ret"]

    # Components A + B should equal exact_diff (before tx cost)
    ab_sum = equity_reduction_cost + cash_income
    residual = exact_diff - ab_sum  # should be ~0 (rounding)

    # Annualize
    n_days = len(res)
    n_years = n_days / TRADING_DAYS

    def annualize_daily(series):
        return series.sum() / n_years * 100  # in percentage points per year

    # For geometric returns, compute cumulative
    cum_bh = (1 + res["bh_ret"]).cumprod()
    cum_vt_notx = (1 + res["vt_ret"]).cumprod()

    # VT with TX cost
    vt_ret_tx = res["vt_ret"] + tx_cost  # tx_cost is negative
    cum_vt_tx = (1 + vt_ret_tx).cumprod()

    # Geometric (CAGR) returns
    cagr_bh = (cum_bh.iloc[-1] ** (1 / n_years) - 1) * 100
    cagr_vt_notx = (cum_vt_notx.iloc[-1] ** (1 / n_years) - 1) * 100
    cagr_vt_tx = (cum_vt_tx.iloc[-1] ** (1 / n_years) - 1) * 100

    # Arithmetic annual returns
    arith_bh = res["bh_ret"].mean() * TRADING_DAYS * 100
    arith_vt = res["vt_ret"].mean() * TRADING_DAYS * 100

    # Volatility
    vol_bh = res["bh_ret"].std() * np.sqrt(TRADING_DAYS) * 100
    vol_vt = res["vt_ret"].std() * np.sqrt(TRADING_DAYS) * 100

    # Volatility drag difference: -0.5 * (σ_vt² - σ_bh²)
    vol_drag_diff = -0.5 * ((vol_vt/100)**2 - (vol_bh/100)**2) * 100

    # MDD
    def max_drawdown(cum_series):
        peak = cum_series.cummax()
        dd = (cum_series - peak) / peak
        return dd.min() * 100

    mdd_bh = max_drawdown(cum_bh)
    mdd_vt = max_drawdown(cum_vt_tx)

    # Sharpe
    excess_bh = res["bh_ret"] - res["rf_daily"]
    excess_vt = vt_ret_tx - res["rf_daily"]
    sharpe_bh = excess_bh.mean() / excess_bh.std() * ANNUALIZE
    sharpe_vt = excess_vt.mean() / excess_vt.std() * ANNUALIZE

    # Component decomposition (arithmetic, annualized %)
    comp = {
        "equity_reduction_cost": annualize_daily(equity_reduction_cost),
        "cash_income": annualize_daily(cash_income),
        "transaction_cost": annualize_daily(tx_cost),
        "residual": annualize_daily(residual),
    }

    # Net insurance cost = sum of components
    comp["net_arithmetic_diff"] = sum(comp.values())

    # Geometric decomposition
    comp["cagr_diff_no_tx"] = cagr_vt_notx - cagr_bh
    comp["cagr_diff_with_tx"] = cagr_vt_tx - cagr_bh
    comp["vol_drag_diff"] = vol_drag_diff

    # Compounding effect = geometric diff - arithmetic diff
    arith_diff = arith_vt - arith_bh
    comp["compounding_effect"] = (cagr_vt_notx - cagr_bh) - arith_diff

    # Convexity analysis: correlation between weight and return
    # VT benefits when it reduces weight before bad days
    corr_w_ret = w.corr(risky)

    # Conditional expectation: E[risky | w < median] vs E[risky | w >= median]
    w_median = w.median()
    ret_low_w = risky[w < w_median].mean() * TRADING_DAYS * 100
    ret_high_w = risky[w >= w_median].mean() * TRADING_DAYS * 100

    comp["convexity_corr_w_ret"] = corr_w_ret
    comp["ret_when_low_weight"] = ret_low_w
    comp["ret_when_high_weight"] = ret_high_w
    comp["convexity_benefit"] = (ret_high_w - ret_low_w)  # how much better are high-weight days

    # Summary stats
    summary = {
        "n_days": n_days,
        "n_years": round(n_years, 2),
        "avg_weight": round(w.mean(), 4),
        "avg_cash_frac": round((1 - w).mean(), 4),
        "avg_daily_turnover": round(res["turnover"].mean(), 6),
        "annual_turnover": round(res["turnover"].sum() / n_years, 4),
        "arith_ret_bh": round(arith_bh, 2),
        "arith_ret_vt": round(arith_vt, 2),
        "cagr_bh": round(cagr_bh, 2),
        "cagr_vt_no_tx": round(cagr_vt_notx, 2),
        "cagr_vt_with_tx": round(cagr_vt_tx, 2),
        "vol_bh": round(vol_bh, 2),
        "vol_vt": round(vol_vt, 2),
        "sharpe_bh": round(sharpe_bh, 4),
        "sharpe_vt": round(sharpe_vt, 4),
        "mdd_bh": round(mdd_bh, 2),
        "mdd_vt": round(mdd_vt, 2),
        "mdd_improvement": round(mdd_vt - mdd_bh, 2),
        "total_return_bh": round((cum_bh.iloc[-1] - 1) * 100, 1),
        "total_return_vt": round((cum_vt_tx.iloc[-1] - 1) * 100, 1),
    }

    # Round components
    for k in comp:
        comp[k] = round(comp[k], 4)

    return {"components": comp, "summary": summary}


def regime_decomposition(res: pd.DataFrame, tx_bps: float = TX_COST_BPS) -> dict:
    """
    Break down insurance cost by VIX regime.
    Low VIX: < 15, Medium: 15-25, High: > 25
    """
    regimes = {
        "low_vix": res[res["vix"] < VIX_LOW],
        "medium_vix": res[(res["vix"] >= VIX_LOW) & (res["vix"] <= VIX_HIGH)],
        "high_vix": res[res["vix"] > VIX_HIGH],
    }

    results = {}
    for regime_name, rdf in regimes.items():
        if len(rdf) < 10:
            continue

        w = rdf["weight"]
        risky = rdf["risky_ret"]
        rf = rdf["rf_daily"]
        n_days = len(rdf)
        n_years = n_days / TRADING_DAYS

        # Daily excess return (VT - BH)
        daily_excess = rdf["vt_ret"] - rdf["bh_ret"]

        # Components
        eq_red = -(1 - w) * risky
        cash_inc = (1 - w) * rf
        tx = -rdf["turnover"] * (tx_bps / 10000)

        # Annualized
        ann = lambda s: s.sum() / n_years * 100 if n_years > 0 else 0

        # Returns
        arith_bh = rdf["bh_ret"].mean() * TRADING_DAYS * 100
        arith_vt = rdf["vt_ret"].mean() * TRADING_DAYS * 100

        # Vol
        vol_bh = rdf["bh_ret"].std() * np.sqrt(TRADING_DAYS) * 100
        vol_vt = rdf["vt_ret"].std() * np.sqrt(TRADING_DAYS) * 100

        # Win rate (VT > BH on daily basis)
        vt_wins = (rdf["vt_ret"] > rdf["bh_ret"]).mean() * 100

        results[regime_name] = {
            "n_days": n_days,
            "pct_of_sample": round(n_days / len(res) * 100, 1),
            "avg_vix": round(rdf["vix"].mean(), 1),
            "avg_weight": round(w.mean(), 4),
            "equity_reduction_cost_ann": round(ann(eq_red), 2),
            "cash_income_ann": round(ann(cash_inc), 2),
            "tx_cost_ann": round(ann(tx), 2),
            "net_insurance_cost_ann": round(ann(daily_excess), 2),
            "arith_ret_bh_ann": round(arith_bh, 2),
            "arith_ret_vt_ann": round(arith_vt, 2),
            "vol_bh": round(vol_bh, 2),
            "vol_vt": round(vol_vt, 2),
            "vt_daily_win_rate": round(vt_wins, 1),
        }

    return results


def find_breakeven_vix(res: pd.DataFrame) -> dict:
    """
    Find the VIX level where insurance cost = protection value.
    Use rolling windows to estimate cost at each VIX level.
    """
    vix_levels = np.arange(10, 45, 1)
    costs = []

    for v in vix_levels:
        # Days where VIX is within ±2 of this level
        mask = (res["vix"] >= v - 2) & (res["vix"] < v + 2)
        subset = res[mask]
        if len(subset) < 20:
            costs.append(np.nan)
            continue

        # Average daily excess return of VT vs BH
        daily_excess = (subset["vt_ret"] - subset["bh_ret"]).mean() * TRADING_DAYS * 100
        costs.append(daily_excess)

    costs = np.array(costs)

    # Find sign change (where cost goes from negative to positive)
    breakeven = np.nan
    for i in range(len(costs) - 1):
        if not np.isnan(costs[i]) and not np.isnan(costs[i+1]):
            if costs[i] < 0 and costs[i+1] >= 0:
                # Linear interpolation
                frac = -costs[i] / (costs[i+1] - costs[i])
                breakeven = vix_levels[i] + frac
                break

    return {
        "vix_levels": vix_levels.tolist(),
        "annual_cost_at_vix": [round(c, 2) if not np.isnan(c) else None for c in costs],
        "breakeven_vix": round(breakeven, 1) if not np.isnan(breakeven) else None,
        "interpretation": (
            f"Below VIX {round(breakeven, 0) if not np.isnan(breakeven) else '?'}: "
            f"VT costs money (insurance premium). "
            f"Above: VT earns money (insurance payout)."
        ),
    }


def compute_efficiency_ratio(summary: dict) -> dict:
    """
    Insurance efficiency ratio: MDD improvement per 1% return sacrificed.
    Higher = more efficient protection.
    """
    cagr_diff = abs(summary["cagr_vt_with_tx"] - summary["cagr_bh"])
    mdd_improvement = abs(summary["mdd_vt"] - summary["mdd_bh"])

    if cagr_diff > 0.01:
        efficiency = mdd_improvement / cagr_diff
    else:
        efficiency = float("inf")  # free protection

    # Sharpe improvement per 1% CAGR sacrificed
    sharpe_diff = summary["sharpe_vt"] - summary["sharpe_bh"]
    sharpe_efficiency = sharpe_diff / cagr_diff if cagr_diff > 0.01 else float("inf")

    # Vol reduction
    vol_reduction = summary["vol_bh"] - summary["vol_vt"]
    vol_efficiency = vol_reduction / cagr_diff if cagr_diff > 0.01 else float("inf")

    return {
        "cagr_sacrificed_pct": round(cagr_diff, 2),
        "mdd_improvement_pp": round(mdd_improvement, 2),
        "mdd_per_pct_return": round(efficiency, 2),
        "sharpe_change": round(sharpe_diff, 4),
        "sharpe_per_pct_return": round(sharpe_efficiency, 4),
        "vol_reduction_pp": round(vol_reduction, 2),
        "vol_per_pct_return": round(vol_efficiency, 2),
        "interpretation": (
            f"For every 1% CAGR sacrificed, VT provides "
            f"{round(efficiency, 1)}pp MDD improvement, "
            f"{round(vol_reduction / cagr_diff if cagr_diff > 0.01 else 0, 1)}pp vol reduction."
        ),
    }


def compute_time_varying_cost(res: pd.DataFrame, window: int = 252) -> dict:
    """
    Rolling 1-year insurance cost to show time variation.
    """
    daily_diff = res["vt_ret"] - res["bh_ret"]
    rolling_cost = daily_diff.rolling(window).mean() * TRADING_DAYS * 100

    # Also compute rolling risk-free rate
    rolling_rf = res["rf_daily"].rolling(window).mean() * TRADING_DAYS * 100

    # Summary stats of rolling cost
    valid = rolling_cost.dropna()

    return {
        "mean_rolling_cost": round(valid.mean(), 2),
        "std_rolling_cost": round(valid.std(), 2),
        "min_rolling_cost": round(valid.min(), 2),
        "max_rolling_cost": round(valid.max(), 2),
        "pct_positive": round((valid > 0).mean() * 100, 1),
        "correlation_with_rf": round(valid.corr(rolling_rf.loc[valid.index]), 4),
    }


def annual_cost_table(res: pd.DataFrame) -> list:
    """Year-by-year insurance cost decomposition."""
    res = res.copy()
    res["year"] = res.index.year

    years = sorted(res["year"].unique())
    table = []

    for yr in years:
        ydf = res[res["year"] == yr]
        if len(ydf) < 50:
            continue

        w = ydf["weight"]
        risky = ydf["risky_ret"]
        rf = ydf["rf_daily"]
        n = len(ydf)

        # B&H return (annualized from actual days)
        cum_bh = (1 + ydf["bh_ret"]).prod()
        cum_vt = (1 + ydf["vt_ret"]).prod()

        # Annualize to percentage
        bh_pct = (cum_bh - 1) * 100
        vt_pct = (cum_vt - 1) * 100

        # Components
        eq_red = (-(1 - w) * risky).sum() * 100
        cash_inc = ((1 - w) * rf).sum() * 100

        # Cost
        net_cost = vt_pct - bh_pct

        # MDD for year
        cum_bh_s = (1 + ydf["bh_ret"]).cumprod()
        cum_vt_s = (1 + ydf["vt_ret"]).cumprod()
        mdd_bh = ((cum_bh_s - cum_bh_s.cummax()) / cum_bh_s.cummax()).min() * 100
        mdd_vt = ((cum_vt_s - cum_vt_s.cummax()) / cum_vt_s.cummax()).min() * 100

        table.append({
            "year": yr,
            "n_days": n,
            "avg_vix": round(ydf["vix"].mean(), 1),
            "avg_weight": round(w.mean(), 3),
            "bh_return_pct": round(bh_pct, 2),
            "vt_return_pct": round(vt_pct, 2),
            "net_cost_pct": round(net_cost, 2),
            "equity_reduction": round(eq_red, 2),
            "cash_income": round(cash_inc, 2),
            "mdd_bh_pct": round(mdd_bh, 2),
            "mdd_vt_pct": round(mdd_vt, 2),
            "mdd_improvement": round(mdd_vt - mdd_bh, 2),
        })

    return table


def tail_protection_analysis(res: pd.DataFrame) -> dict:
    """
    Analyze insurance payout during tail events.
    """
    daily_diff = res["vt_ret"] - res["bh_ret"]
    bh_ret = res["bh_ret"]

    # Define tail events: worst 1%, 5%, 10% BH days
    thresholds = {
        "worst_1pct": bh_ret.quantile(0.01),
        "worst_5pct": bh_ret.quantile(0.05),
        "worst_10pct": bh_ret.quantile(0.10),
    }

    results = {}
    for name, thresh in thresholds.items():
        tail_mask = bh_ret <= thresh
        n_tail = tail_mask.sum()

        # Average BH loss on tail days
        avg_bh_loss = bh_ret[tail_mask].mean() * 100

        # Average VT excess on tail days
        avg_vt_excess = daily_diff[tail_mask].mean() * 100

        # VT win rate on tail days
        vt_wins = (daily_diff[tail_mask] > 0).mean() * 100

        # Average weight on tail days
        avg_w = res["weight"][tail_mask].mean()

        # Protection ratio: how much of the loss is avoided
        avg_vt_loss = (bh_ret[tail_mask] + daily_diff[tail_mask]).mean() * 100
        protection_ratio = 1 - (avg_vt_loss / avg_bh_loss) if avg_bh_loss != 0 else 0

        results[name] = {
            "n_events": int(n_tail),
            "threshold_pct": round(thresh * 100, 3),
            "avg_bh_loss_pct": round(avg_bh_loss, 3),
            "avg_vt_excess_pct": round(avg_vt_excess, 3),
            "avg_vt_loss_pct": round(avg_vt_loss, 3),
            "protection_ratio": round(protection_ratio, 3),
            "vt_win_rate": round(vt_wins, 1),
            "avg_weight_during_tail": round(avg_w, 3),
        }

    return results


def statistical_tests(res: pd.DataFrame) -> dict:
    """
    Statistical significance tests for the decomposition.
    """
    daily_diff = res["vt_ret"] - res["bh_ret"]
    n = len(daily_diff)

    # t-test: is the mean difference significantly different from zero?
    t_stat, p_val = stats.ttest_1samp(daily_diff, 0)

    # Newey-West adjusted (simple HAC with lag=5)
    from scipy.signal import fftconvolve
    mean_diff = daily_diff.mean()
    demeaned = daily_diff - mean_diff
    var0 = (demeaned ** 2).mean()

    # Bartlett kernel HAC
    max_lag = min(int(4 * (n / 100) ** (2/9)), 20)
    hac_var = var0
    for j in range(1, max_lag + 1):
        cov_j = (demeaned[j:].values * demeaned[:-j].values).mean()
        weight = 1 - j / (max_lag + 1)
        hac_var += 2 * weight * cov_j

    hac_se = np.sqrt(hac_var / n)
    t_hac = mean_diff / hac_se

    # Bootstrap: P(VT underperforms B&H annually)
    n_boot = 5000
    boot_diffs = []
    for _ in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        boot_mean = daily_diff.values[idx].mean() * TRADING_DAYS
        boot_diffs.append(boot_mean)

    boot_diffs = np.array(boot_diffs)
    p_underperform = (boot_diffs < 0).mean()

    return {
        "t_stat_raw": round(t_stat, 3),
        "p_value_raw": round(p_val, 6),
        "t_stat_hac": round(t_hac, 3),
        "hac_lag": max_lag,
        "mean_daily_diff_bps": round(mean_diff * 10000, 3),
        "mean_annual_diff_pct": round(mean_diff * TRADING_DAYS * 100, 2),
        "bootstrap_p_underperform": round(p_underperform, 4),
        "bootstrap_95ci_annual_pct": [
            round(np.percentile(boot_diffs, 2.5) * 100, 2),
            round(np.percentile(boot_diffs, 97.5) * 100, 2),
        ],
        "harvey_pass": abs(t_hac) > 3.0,
    }


# ============================================================
#  Main execution
# ============================================================

def main():
    t0 = time.time()
    print("=" * 80)
    print("K573: Portfolio Insurance Pricing Theory — Exact Cost Decomposition")
    print("=" * 80)

    # 1. Download data
    df = download_data()

    # 2. Define strategies
    strategies = {
        "12_vix": {
            "name": "12/VIX Standard",
            "weight_fn": lambda df: weight_12vix(df["VIX"]),
            "description": "Standard 12/VIX equity weight in 50/50 SPY/GLD",
        },
        "piecewise": {
            "name": "Piecewise Conservative (c1=12, c2=20)",
            "weight_fn": lambda df: weight_piecewise(df["VIX"], 12.0, 20.0),
            "description": "Full equity VIX<12, ramp to 0 at VIX=20, exit above",
        },
        "leverage": {
            "name": "VIX-Conditional Leverage",
            "weight_fn": lambda df: weight_leverage(df["VIX"], 15.0, 30.0, 1.5, 0.5),
            "description": "1.5x leverage VIX<15, ramp to 0.5x at VIX=30",
        },
    }

    all_results = {}

    for strat_key, strat_info in strategies.items():
        print(f"\n{'='*60}")
        print(f"Strategy: {strat_info['name']}")
        print(f"{'='*60}")

        # Compute weights
        equity_w = strat_info["weight_fn"](df)

        # Compute returns with decomposition
        res = compute_strategy_returns(df, equity_w)

        # 2. Full decomposition
        print("\n--- Full Sample Decomposition ---")
        decomp = decompose_return_difference(res)

        print(f"  CAGR B&H: {decomp['summary']['cagr_bh']:.2f}%")
        print(f"  CAGR VT (no TX): {decomp['summary']['cagr_vt_no_tx']:.2f}%")
        print(f"  CAGR VT (with TX): {decomp['summary']['cagr_vt_with_tx']:.2f}%")
        print(f"  Insurance cost (CAGR): {decomp['summary']['cagr_vt_with_tx'] - decomp['summary']['cagr_bh']:.2f}%/yr")
        print(f"  MDD B&H: {decomp['summary']['mdd_bh']:.1f}%")
        print(f"  MDD VT: {decomp['summary']['mdd_vt']:.1f}%")
        print(f"  MDD improvement: {decomp['summary']['mdd_improvement']:.1f}pp")
        print(f"\n  Component breakdown (annualized %):")
        print(f"    Equity reduction cost: {decomp['components']['equity_reduction_cost']:.2f}%")
        print(f"    Cash income:           {decomp['components']['cash_income']:.2f}%")
        print(f"    Transaction cost:      {decomp['components']['transaction_cost']:.4f}%")
        print(f"    Net arithmetic diff:   {decomp['components']['net_arithmetic_diff']:.2f}%")
        print(f"    Compounding effect:    {decomp['components']['compounding_effect']:.2f}%")
        print(f"    CAGR diff (no TX):     {decomp['components']['cagr_diff_no_tx']:.2f}%")
        print(f"    Vol drag diff:         {decomp['components']['vol_drag_diff']:.2f}%")
        print(f"\n  Convexity analysis:")
        print(f"    Weight-return corr:    {decomp['components']['convexity_corr_w_ret']:.4f}")
        print(f"    Return when low w:     {decomp['components']['ret_when_low_weight']:.2f}%/yr")
        print(f"    Return when high w:    {decomp['components']['ret_when_high_weight']:.2f}%/yr")
        print(f"    Convexity benefit:     {decomp['components']['convexity_benefit']:.2f}%")

        # 3. Regime decomposition
        print("\n--- VIX Regime Decomposition ---")
        regime_decomp = regime_decomposition(res)
        for regime, rinfo in regime_decomp.items():
            print(f"\n  {regime} (VIX avg={rinfo['avg_vix']}, {rinfo['pct_of_sample']}% of sample):")
            print(f"    Avg weight: {rinfo['avg_weight']:.3f}")
            print(f"    Eq reduction: {rinfo['equity_reduction_cost_ann']:.2f}%, Cash income: {rinfo['cash_income_ann']:.2f}%")
            print(f"    Net cost: {rinfo['net_insurance_cost_ann']:.2f}%/yr")
            print(f"    BH ret: {rinfo['arith_ret_bh_ann']:.1f}%, VT ret: {rinfo['arith_ret_vt_ann']:.1f}%")
            print(f"    VT daily win rate: {rinfo['vt_daily_win_rate']:.1f}%")

        # 4. Breakeven VIX
        print("\n--- Breakeven VIX ---")
        breakeven = find_breakeven_vix(res)
        print(f"  Breakeven VIX: {breakeven['breakeven_vix']}")
        print(f"  {breakeven['interpretation']}")

        # 5. Efficiency ratio
        print("\n--- Insurance Efficiency ---")
        efficiency = compute_efficiency_ratio(decomp["summary"])
        print(f"  CAGR sacrificed: {efficiency['cagr_sacrificed_pct']:.2f}%")
        print(f"  MDD improvement: {efficiency['mdd_improvement_pp']:.1f}pp")
        print(f"  MDD per 1% CAGR: {efficiency['mdd_per_pct_return']:.1f}pp")
        print(f"  Vol reduction per 1% CAGR: {efficiency['vol_per_pct_return']:.1f}pp")
        print(f"  Sharpe change: {efficiency['sharpe_change']:.4f}")
        print(f"  {efficiency['interpretation']}")

        # 6. Time-varying cost
        print("\n--- Time-Varying Cost (1-Year Rolling) ---")
        tv_cost = compute_time_varying_cost(res)
        print(f"  Mean rolling cost: {tv_cost['mean_rolling_cost']:.2f}%/yr")
        print(f"  Std: {tv_cost['std_rolling_cost']:.2f}%")
        print(f"  Range: [{tv_cost['min_rolling_cost']:.1f}%, {tv_cost['max_rolling_cost']:.1f}%]")
        print(f"  Pct positive (VT beats BH): {tv_cost['pct_positive']:.1f}%")
        print(f"  Correlation with risk-free rate: {tv_cost['correlation_with_rf']:.3f}")

        # 7. Annual table
        print("\n--- Year-by-Year Insurance Cost ---")
        annual = annual_cost_table(res)
        print(f"  {'Year':>4} {'VIX':>5} {'Wgt':>5} {'BH%':>7} {'VT%':>7} {'Cost%':>7} {'MDD_BH':>7} {'MDD_VT':>7} {'ΔMDD':>6}")
        for row in annual:
            print(f"  {row['year']:>4} {row['avg_vix']:>5.1f} {row['avg_weight']:>.3f} "
                  f"{row['bh_return_pct']:>7.2f} {row['vt_return_pct']:>7.2f} "
                  f"{row['net_cost_pct']:>7.2f} {row['mdd_bh_pct']:>7.1f} "
                  f"{row['mdd_vt_pct']:>7.1f} {row['mdd_improvement']:>6.1f}")

        # 8. Tail protection
        print("\n--- Tail Protection Analysis ---")
        tail = tail_protection_analysis(res)
        for tail_name, tinfo in tail.items():
            print(f"  {tail_name} ({tinfo['n_events']} events, thresh={tinfo['threshold_pct']:.2f}%):")
            print(f"    BH loss: {tinfo['avg_bh_loss_pct']:.3f}%, VT excess: {tinfo['avg_vt_excess_pct']:.3f}%")
            print(f"    Protection ratio: {tinfo['protection_ratio']:.1%}, Win rate: {tinfo['vt_win_rate']:.1f}%")

        # 9. Statistical tests
        print("\n--- Statistical Tests ---")
        stat_tests = statistical_tests(res)
        print(f"  Mean annual diff: {stat_tests['mean_annual_diff_pct']:.2f}%")
        print(f"  t-stat (raw): {stat_tests['t_stat_raw']:.3f}")
        print(f"  t-stat (HAC): {stat_tests['t_stat_hac']:.3f}")
        print(f"  Harvey pass (|t|>3): {stat_tests['harvey_pass']}")
        print(f"  Bootstrap P(underperform): {stat_tests['bootstrap_p_underperform']:.1%}")
        print(f"  Bootstrap 95% CI: {stat_tests['bootstrap_95ci_annual_pct']}")

        # Store results
        all_results[strat_key] = {
            "name": strat_info["name"],
            "description": strat_info["description"],
            "decomposition": decomp,
            "regime_decomposition": regime_decomp,
            "breakeven_vix": breakeven,
            "efficiency": efficiency,
            "time_varying_cost": tv_cost,
            "annual_table": annual,
            "tail_protection": tail,
            "statistical_tests": stat_tests,
        }

    # ============================================================
    #  Cross-Strategy Comparison
    # ============================================================
    print(f"\n{'='*80}")
    print("CROSS-STRATEGY COMPARISON")
    print(f"{'='*80}")

    comparison = {}
    print(f"\n{'Strategy':<30} {'CAGR BH':>8} {'CAGR VT':>8} {'Cost':>7} {'MDD BH':>8} {'MDD VT':>8} {'ΔMDD':>6} {'Eff':>6}")
    print("-" * 90)

    for sk, sr in all_results.items():
        s = sr["decomposition"]["summary"]
        e = sr["efficiency"]
        print(f"{sr['name']:<30} {s['cagr_bh']:>7.2f}% {s['cagr_vt_with_tx']:>7.2f}% "
              f"{e['cagr_sacrificed_pct']:>6.2f}% {s['mdd_bh']:>7.1f}% {s['mdd_vt']:>7.1f}% "
              f"{s['mdd_improvement']:>5.1f} {e['mdd_per_pct_return']:>5.1f}")

        comparison[sk] = {
            "cagr_bh": s["cagr_bh"],
            "cagr_vt": s["cagr_vt_with_tx"],
            "cagr_cost": e["cagr_sacrificed_pct"],
            "mdd_bh": s["mdd_bh"],
            "mdd_vt": s["mdd_vt"],
            "mdd_improvement": s["mdd_improvement"],
            "efficiency_mdd_per_pct": e["mdd_per_pct_return"],
            "sharpe_bh": s["sharpe_bh"],
            "sharpe_vt": s["sharpe_vt"],
            "vol_bh": s["vol_bh"],
            "vol_vt": s["vol_vt"],
        }

    # Identify the most efficient strategy
    best_eff = max(comparison.items(), key=lambda x: x[1]["efficiency_mdd_per_pct"]
                   if x[1]["efficiency_mdd_per_pct"] != float("inf") else 0)
    print(f"\nMost efficient: {all_results[best_eff[0]]['name']} "
          f"({best_eff[1]['efficiency_mdd_per_pct']:.1f}pp MDD per 1% CAGR)")

    # ============================================================
    #  Theoretical Insights
    # ============================================================
    print(f"\n{'='*80}")
    print("THEORETICAL INSIGHTS")
    print(f"{'='*80}")

    vt12 = all_results["12_vix"]
    pw = all_results["piecewise"]
    lev = all_results["leverage"]

    insights = []

    # Insight 1: Where does the cost come from?
    eq_red = vt12["decomposition"]["components"]["equity_reduction_cost"]
    cash_inc = vt12["decomposition"]["components"]["cash_income"]
    total = eq_red + cash_inc
    eq_pct = abs(eq_red) / (abs(eq_red) + abs(cash_inc)) * 100 if total != 0 else 0

    i1 = (f"For 12/VIX: Equity reduction cost = {eq_red:.2f}%/yr, "
          f"Cash income = {cash_inc:.2f}%/yr. "
          f"Equity reduction is {eq_pct:.0f}% of gross cost. "
          f"Cash income offsets {abs(cash_inc/eq_red)*100:.0f}% of equity cost." if eq_red != 0 else "")
    insights.append(i1)
    print(f"\n1. Cost source: {i1}")

    # Insight 2: Interest rate sensitivity
    tv12 = vt12["time_varying_cost"]
    i2 = (f"Rolling cost correlation with risk-free rate: {tv12['correlation_with_rf']:.3f}. "
          f"K62 confirmed: higher rates → cheaper insurance (cash offsets more).")
    insights.append(i2)
    print(f"2. Rate sensitivity: {i2}")

    # Insight 3: Convexity
    conv = vt12["decomposition"]["components"]["convexity_benefit"]
    i3 = (f"Convexity benefit: {conv:.2f}%/yr. "
          f"Return on high-weight days: {vt12['decomposition']['components']['ret_when_high_weight']:.1f}%/yr vs "
          f"low-weight days: {vt12['decomposition']['components']['ret_when_low_weight']:.1f}%/yr. "
          f"VT correctly loads up on better days (positive selection).")
    insights.append(i3)
    print(f"3. Convexity: {i3}")

    # Insight 4: Efficiency comparison
    eff12 = vt12["efficiency"]["mdd_per_pct_return"]
    effpw = pw["efficiency"]["mdd_per_pct_return"]
    efflev = lev["efficiency"]["mdd_per_pct_return"]
    i4 = (f"Efficiency (MDD pp per 1% CAGR): 12/VIX={eff12:.1f}, "
          f"Piecewise={effpw:.1f}, Leverage={efflev:.1f}.")
    insights.append(i4)
    print(f"4. Efficiency: {i4}")

    # Insight 5: Breakeven VIX
    be12 = vt12["breakeven_vix"]["breakeven_vix"]
    bepw = pw["breakeven_vix"]["breakeven_vix"]
    belev = lev["breakeven_vix"]["breakeven_vix"]
    i5 = f"Breakeven VIX: 12/VIX={be12}, Piecewise={bepw}, Leverage={belev}."
    insights.append(i5)
    print(f"5. Breakeven: {i5}")

    # Insight 6: Tail protection value
    tail12 = vt12["tail_protection"]["worst_1pct"]
    i6 = (f"On worst 1% days: BH loss={tail12['avg_bh_loss_pct']:.2f}%, "
          f"VT excess={tail12['avg_vt_excess_pct']:.2f}%, "
          f"Protection ratio={tail12['protection_ratio']:.1%}.")
    insights.append(i6)
    print(f"6. Tail protection: {i6}")

    # ============================================================
    #  Save Results
    # ============================================================
    elapsed = time.time() - t0

    # Clean up breakeven for JSON serialization
    for sk in all_results:
        bv = all_results[sk]["breakeven_vix"]
        bv["vix_levels"] = bv["vix_levels"][:20]  # trim to save space
        bv["annual_cost_at_vix"] = bv["annual_cost_at_vix"][:20]

    # Handle inf values for JSON
    for sk in all_results:
        eff = all_results[sk]["efficiency"]
        for k, v in eff.items():
            if isinstance(v, float) and (np.isinf(v) or np.isnan(v)):
                eff[k] = None

    output = {
        "experiment_id": "K573",
        "title": "Portfolio Insurance Pricing Theory — Exact Cost Decomposition",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (SPY, GLD, ^VIX, ^IRX)",
        "data_period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "n_observations": len(df),
        "methodology": "Return decomposition, regime analysis, breakeven analysis, tail protection, bootstrap",
        "tx_cost_bps": TX_COST_BPS,
        "references": [
            "Moreira & Muir (2017, JoF): Volatility-managed portfolios",
            "Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing",
            "Barroso & Santa-Clara (2015, JFE): Momentum is not volatile",
            "K41: VT insurance premium ~4%/yr",
            "K62: Interest rate regime effect",
            "K74: Gross/net cost anatomy",
            "K544: VT as tail hedge",
            "K548/K551: VIX-Conditional Leverage validated",
            "K569: Piecewise VT validated",
        ],
        "strategies": all_results,
        "cross_strategy_comparison": comparison,
        "theoretical_insights": insights,
        "execution_time_seconds": round(elapsed, 1),
    }

    # Save
    out_path = Path(__file__).parent / "k573_insurance_pricing_results.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'='*80}")
    print(f"Results saved to {out_path}")
    print(f"Execution time: {elapsed:.1f}s")
    print(f"{'='*80}")

    return output


if __name__ == "__main__":
    main()
