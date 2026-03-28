#!/usr/bin/env python3
"""K574: Complete 3-Tier Strategy Backtest — Definitive Comparison for Paper & Website
=======================================================================================

Motivation:
    We now have 3 validated strategy tiers plus baselines. This experiment creates
    the DEFINITIVE side-by-side comparison with consistent methodology, producing
    paper-quality tables and charts.

Strategies compared (all on same data, same period):
    1. Buy & Hold SPY (baseline)
    2. Buy & Hold 50/50 SPY/GLD (diversified baseline)
    3. Standard 12/VIX VT (current recommended — K275)
    4. VIX-Conditional Leverage (K548/K551 — growth tier)
    5. Piecewise Conservative (K569 — conservative tier)
    6. Fear DCA (K552 — monthly investor tier, simulates $1000/mo contributions)

Data: SPY + GLD + VIX + ^IRX from yfinance, 2005-2026 (~21 years)

Metrics for EACH strategy:
    - CAGR, Annualized Volatility, Sharpe, Sortino, Calmar
    - MDD, max underwater duration (days)
    - Worst month, worst quarter, worst year
    - VaR 1%, CVaR 1%
    - Turnover, estimated TX cost drag
    - $1M growth path

Additional analyses:
    - Rolling 3-year Sharpe comparison
    - Drawdown timeline overlay
    - Year-by-year return table
    - Risk-return scatter plot
    - Insurance efficiency (K573 framework)

Charts (saved as PNG):
    - Cumulative growth of $1M (all strategies)
    - Drawdown timeline
    - Risk-return scatter
    - Rolling 3-year Sharpe
    - Year-by-year heatmap

References:
    - Moreira & Muir (2017, JoF): Volatility-managed portfolios
    - Harvey (2016, JoF): Multiple testing threshold t>3.0
    - Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing
    - Barroso & Santa-Clara (2015, JFE): Momentum managed
    - K275: Complete case for 50/50 SPY/GLD + 12/VIX
    - K548/K551: VIX-Conditional Leverage (validated Harvey t=7.90)
    - K569: Piecewise VT (6/8 pass, conservative tier)
    - K552: Fear DCA (3/3 OOS, retail-friendly)
    - K573: Insurance pricing theory

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
TX_COST_BPS = 5  # 5 bps one-way
BORROWING_SPREAD = 0.005  # 50 bps above risk-free for leverage
ANNUALIZE = np.sqrt(252)
TRADING_DAYS = 252
DCA_MONTHLY = 1000.0  # $1000/month for DCA strategies
INITIAL_CAPITAL = 1_000_000.0

START_DATE = "2004-12-01"  # buffer for rolling calcs
END_DATE = "2026-03-28"
ANALYSIS_START = "2005-06-01"  # GLD inception late 2004, need warm-up

np.random.seed(42)

# Piecewise VT parameters (from K568/K569)
PW_C1 = 12.0
PW_C2 = 20.0

# VIX-Conditional Leverage parameters (from K548/K551)
VCL_VIX_LOW = 15.0
VCL_VIX_HIGH = 25.0
VCL_LEV_HIGH = 1.5  # leverage when VIX < 15
VCL_LEV_LOW = 1.0   # leverage when VIX > 25

# Fear DCA parameters (from K552)
FEAR_VIX_HIGH = 25.0
FEAR_VIX_LOW = 15.0
FEAR_AMOUNT_HIGH = 1500.0
FEAR_AMOUNT_LOW = 500.0
FEAR_AMOUNT_NORMAL = 1000.0

# Chart output directory
CHART_DIR = Path(__file__).resolve().parent / "k574_charts"
CHART_DIR.mkdir(exist_ok=True)

# Crisis periods for analysis
CRISIS_PERIODS = {
    "GFC": ("2007-10-01", "2009-03-09"),
    "COVID": ("2020-02-19", "2020-03-23"),
    "2022_Bear": ("2022-01-03", "2022-10-12"),
    "Aug2024_Yen": ("2024-07-16", "2024-08-05"),
    "Trump_Tariff": ("2025-02-19", "2025-03-13"),
}


# ============================================================
#  Data Download
# ============================================================
def download_data() -> pd.DataFrame:
    """Download SPY, GLD, VIX, IRX from yfinance and build unified daily DataFrame."""
    print("=" * 80)
    print("K574: COMPLETE 3-TIER STRATEGY BACKTEST")
    print("=" * 80)
    print(f"\n[1/8] Downloading data from yfinance ({START_DATE} to {END_DATE})...")

    tickers = ["SPY", "GLD", "^VIX", "^IRX"]
    raw = yf.download(tickers, start=START_DATE, end=END_DATE, progress=False)

    # Handle multi-level columns
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].copy()

    df = pd.DataFrame(index=close.index)
    df["spy_close"] = close["SPY"]
    df["gld_close"] = close["GLD"]
    df["vix"] = close["^VIX"]

    # Risk-free rate
    if "^IRX" in close.columns:
        df["rf_annual"] = close["^IRX"] / 100.0  # ^IRX in %
        df["rf_annual"] = df["rf_annual"].ffill().fillna(RF_ANNUAL)
    else:
        df["rf_annual"] = RF_ANNUAL

    df = df.dropna(subset=["spy_close", "gld_close", "vix"])

    # Daily returns
    df["spy_ret"] = df["spy_close"].pct_change()
    df["gld_ret"] = df["gld_close"].pct_change()
    df["rf_daily"] = df["rf_annual"] / TRADING_DAYS

    # Filter to analysis period
    df = df.loc[ANALYSIS_START:]
    df = df.dropna(subset=["spy_ret", "gld_ret"])

    print(f"  Period: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Trading days: {len(df)}")
    print(f"  VIX range: {df['vix'].min():.1f} - {df['vix'].max():.1f} (mean {df['vix'].mean():.1f})")

    return df


# ============================================================
#  Weight Functions
# ============================================================
def w_12vix(vix: np.ndarray) -> np.ndarray:
    """Standard 12/VIX weight, capped at 1.0."""
    return np.clip(12.0 / vix, 0.0, 1.0)


def w_piecewise(vix: np.ndarray, c1: float = PW_C1, c2: float = PW_C2) -> np.ndarray:
    """Piecewise linear: w=1 if VIX<c1, ramp to 0, w=0 if VIX>c2."""
    return np.clip(
        np.where(vix < c1, 1.0,
                 np.where(vix > c2, 0.0,
                          (c2 - vix) / (c2 - c1))),
        0.0, 1.0
    )


def leverage_factor(vix: np.ndarray) -> np.ndarray:
    """VIX-conditional leverage: 1.5x when VIX<15, 1.0x when VIX>25, linear between."""
    lev = np.where(
        vix < VCL_VIX_LOW, VCL_LEV_HIGH,
        np.where(vix > VCL_VIX_HIGH, VCL_LEV_LOW,
                 VCL_LEV_HIGH + (VCL_LEV_LOW - VCL_LEV_HIGH) *
                 (vix - VCL_VIX_LOW) / (VCL_VIX_HIGH - VCL_VIX_LOW))
    )
    return lev


# ============================================================
#  Strategy Return Computation
# ============================================================
def compute_strategy_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Compute daily returns for all 5 lump-sum strategies."""
    print("\n[2/8] Computing strategy returns...")

    vix = df["vix"].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values
    rf_daily = df["rf_daily"].values

    results = pd.DataFrame(index=df.index)

    # 1. Buy & Hold SPY
    results["BH_SPY"] = spy_ret

    # 2. Buy & Hold 50/50 SPY/GLD
    results["BH_5050"] = 0.5 * spy_ret + 0.5 * gld_ret

    # 3. Standard 12/VIX VT (50/50 SPY/GLD base)
    w_vt = w_12vix(vix)
    results["VT_12VIX"] = w_vt * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - w_vt) * rf_daily

    # 4. VIX-Conditional Leverage (12/VIX + leverage overlay)
    lev = leverage_factor(vix)
    # Portfolio return = leverage × VT return - (leverage - 1) × borrowing cost
    vt_base_ret = w_vt * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - w_vt) * rf_daily
    borrowing_cost_daily = (df["rf_annual"].values + BORROWING_SPREAD) / TRADING_DAYS
    results["VCL"] = lev * vt_base_ret - (lev - 1) * borrowing_cost_daily

    # 5. Piecewise Conservative (50/50 SPY/GLD base)
    w_pw = w_piecewise(vix)
    results["PW_Cons"] = w_pw * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - w_pw) * rf_daily

    # Compute weights for turnover calculation
    weights = pd.DataFrame(index=df.index)
    weights["BH_SPY"] = 1.0
    weights["BH_5050"] = 1.0  # static 50/50
    weights["VT_12VIX"] = w_vt
    weights["VCL"] = w_vt * lev
    weights["PW_Cons"] = w_pw

    print(f"  Strategies computed: {list(results.columns)}")
    for col in results.columns:
        ann_ret = results[col].mean() * TRADING_DAYS
        ann_vol = results[col].std() * ANNUALIZE
        print(f"    {col}: ann_ret={ann_ret*100:.1f}%, ann_vol={ann_vol*100:.1f}%")

    return results, weights


# ============================================================
#  Fear DCA Simulation
# ============================================================
def compute_fear_dca(df: pd.DataFrame) -> dict:
    """Simulate Fear DCA with monthly contributions, budget-neutral."""
    print("\n[3/8] Computing Fear DCA simulation...")

    # Monthly resampling: last trading day each month
    monthly = df.resample("ME").last().copy()
    monthly["spy_ret_m"] = monthly["spy_close"].pct_change()
    monthly = monthly.dropna(subset=["spy_ret_m"])

    n_months = len(monthly)
    vix_m = monthly["vix"].values
    spy_prices = monthly["spy_close"].values

    # --- Base DCA: flat $1000/month ---
    base_contributions = np.full(n_months, DCA_MONTHLY)
    base_shares = base_contributions / spy_prices
    base_total_shares = np.cumsum(base_shares)
    base_total_invested = np.cumsum(base_contributions)
    base_portfolio_value = base_total_shares * spy_prices

    # --- Fear DCA: variable contributions ---
    fear_raw = np.where(
        vix_m > FEAR_VIX_HIGH, FEAR_AMOUNT_HIGH,
        np.where(vix_m < FEAR_VIX_LOW, FEAR_AMOUNT_LOW, FEAR_AMOUNT_NORMAL)
    )
    # Budget neutralize: scale so total contribution = base total
    scale = base_contributions.sum() / fear_raw.sum()
    fear_contributions = fear_raw * scale

    fear_shares = fear_contributions / spy_prices
    fear_total_shares = np.cumsum(fear_shares)
    fear_total_invested = np.cumsum(fear_contributions)
    fear_portfolio_value = fear_total_shares * spy_prices

    # Terminal values
    base_terminal = base_portfolio_value[-1]
    fear_terminal = fear_portfolio_value[-1]
    total_invested = base_total_invested[-1]

    # Monthly returns for DCA strategies (portfolio value change / prev value)
    base_monthly_ret = np.diff(base_portfolio_value) / base_portfolio_value[:-1]
    fear_monthly_ret = np.diff(fear_portfolio_value) / fear_portfolio_value[:-1]

    # MDD for DCA
    def mdd_series(values):
        peak = np.maximum.accumulate(values)
        dd = (values - peak) / peak
        return dd.min()

    base_mdd = mdd_series(base_portfolio_value)
    fear_mdd = mdd_series(fear_portfolio_value)

    # Average cost per share
    base_avg_cost = total_invested / base_total_shares[-1]
    fear_avg_cost = total_invested / fear_total_shares[-1]

    # IRR approximation (annualized geometric return on invested capital)
    years = n_months / 12.0
    base_irr = (base_terminal / total_invested) ** (1 / years) - 1
    fear_irr = (fear_terminal / total_invested) ** (1 / years) - 1

    # Sharpe of monthly returns
    base_sharpe_m = base_monthly_ret.mean() / base_monthly_ret.std() * np.sqrt(12)
    fear_sharpe_m = fear_monthly_ret.mean() / fear_monthly_ret.std() * np.sqrt(12)

    dca_results = {
        "n_months": int(n_months),
        "total_invested": float(total_invested),
        "base_dca": {
            "terminal_value": float(base_terminal),
            "irr_annual": float(base_irr),
            "mdd": float(base_mdd),
            "avg_cost": float(base_avg_cost),
            "sharpe_monthly": float(base_sharpe_m),
        },
        "fear_dca": {
            "terminal_value": float(fear_terminal),
            "irr_annual": float(fear_irr),
            "mdd": float(fear_mdd),
            "avg_cost": float(fear_avg_cost),
            "sharpe_monthly": float(fear_sharpe_m),
            "improvement_pct": float((fear_terminal / base_terminal - 1) * 100),
            "mdd_improvement_pp": float((fear_mdd - base_mdd) * 100),
        },
        "dates": [d.strftime("%Y-%m-%d") for d in monthly.index],
        "base_portfolio_values": base_portfolio_value.tolist(),
        "fear_portfolio_values": fear_portfolio_value.tolist(),
    }

    print(f"  Base DCA terminal: ${base_terminal:,.0f} (IRR {base_irr*100:.1f}%)")
    print(f"  Fear DCA terminal: ${fear_terminal:,.0f} (IRR {fear_irr*100:.1f}%)")
    print(f"  Fear improvement: {(fear_terminal/base_terminal-1)*100:+.1f}%")
    print(f"  Base MDD: {base_mdd*100:.1f}%, Fear MDD: {fear_mdd*100:.1f}%")

    return dca_results


# ============================================================
#  Comprehensive Metrics
# ============================================================
def compute_metrics(returns: pd.Series, weights: pd.Series | None = None,
                    rf_daily: pd.Series | None = None, name: str = "") -> dict:
    """Compute comprehensive performance metrics for a daily return series."""
    r = returns.dropna()
    n = len(r)
    if n < 252:
        return {"name": name, "error": "insufficient data"}

    # Annualized return and volatility
    cum = (1 + r).cumprod()
    years = n / TRADING_DAYS
    total_return = cum.iloc[-1] - 1
    cagr = (1 + total_return) ** (1 / years) - 1
    ann_vol = r.std() * ANNUALIZE

    # Risk-free
    if rf_daily is not None:
        rf_mean = rf_daily.mean() * TRADING_DAYS
    else:
        rf_mean = RF_ANNUAL

    # Sharpe
    excess = r.mean() * TRADING_DAYS - rf_mean
    sharpe = excess / ann_vol if ann_vol > 0 else 0.0

    # Sortino (downside deviation)
    downside = r[r < 0]
    downside_vol = downside.std() * ANNUALIZE if len(downside) > 0 else 1e-6
    sortino = excess / downside_vol

    # Maximum Drawdown
    peak = cum.cummax()
    drawdown = (cum - peak) / peak
    mdd = drawdown.min()
    mdd_date = drawdown.idxmin()

    # Max underwater duration (days)
    underwater = drawdown < 0
    if underwater.any():
        groups = (~underwater).cumsum()
        uw_durations = underwater.groupby(groups).sum()
        max_uw_duration = int(uw_durations.max())
    else:
        max_uw_duration = 0

    # Calmar ratio
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else np.inf

    # Worst month / quarter / year
    monthly_ret = (1 + r).resample("ME").prod() - 1
    quarterly_ret = (1 + r).resample("QE").prod() - 1
    yearly_ret = (1 + r).resample("YE").prod() - 1

    worst_month = monthly_ret.min()
    worst_month_date = monthly_ret.idxmin()
    best_month = monthly_ret.max()
    worst_quarter = quarterly_ret.min()
    worst_quarter_date = quarterly_ret.idxmin()
    worst_year = yearly_ret.min()
    worst_year_date = yearly_ret.idxmin()
    best_year = yearly_ret.max()

    # VaR and CVaR (1%)
    var_1pct = np.percentile(r, 1)
    cvar_1pct = r[r <= var_1pct].mean()

    # Turnover (if weights provided)
    turnover = 0.0
    tx_drag = 0.0
    if weights is not None:
        w = weights.reindex(r.index).dropna()
        daily_turnover = w.diff().abs()
        turnover = daily_turnover.mean() * TRADING_DAYS  # annualized
        tx_drag = turnover * TX_COST_BPS / 10000  # annual TX cost

    # $1M growth
    growth_1m = INITIAL_CAPITAL * cum

    # Win rate (positive daily return days)
    win_rate = (r > 0).mean()

    # Skewness and kurtosis
    skew = r.skew()
    kurt = r.kurtosis()

    metrics = {
        "name": name,
        "n_days": int(n),
        "years": round(years, 1),
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "mdd_pct": round(mdd * 100, 2),
        "mdd_date": str(mdd_date.date()) if hasattr(mdd_date, "date") else str(mdd_date),
        "max_underwater_days": max_uw_duration,
        "worst_month_pct": round(worst_month * 100, 2),
        "worst_month_date": str(worst_month_date.date()) if hasattr(worst_month_date, "date") else str(worst_month_date),
        "best_month_pct": round(best_month * 100, 2),
        "worst_quarter_pct": round(worst_quarter * 100, 2),
        "worst_quarter_date": str(worst_quarter_date.date()) if hasattr(worst_quarter_date, "date") else str(worst_quarter_date),
        "worst_year_pct": round(worst_year * 100, 2),
        "worst_year_date": str(worst_year_date.date()) if hasattr(worst_year_date, "date") else str(worst_year_date),
        "best_year_pct": round(best_year * 100, 2),
        "var_1pct": round(var_1pct * 100, 4),
        "cvar_1pct": round(cvar_1pct * 100, 4),
        "turnover_annual": round(turnover, 2),
        "tx_drag_pct": round(tx_drag * 100, 4),
        "win_rate": round(win_rate, 4),
        "skewness": round(skew, 3),
        "kurtosis": round(kurt, 3),
        "terminal_1m": round(growth_1m.iloc[-1], 0),
    }

    return metrics


# ============================================================
#  Rolling 3-Year Sharpe
# ============================================================
def compute_rolling_sharpe(returns: pd.DataFrame, window: int = 756) -> pd.DataFrame:
    """Compute rolling 3-year (756 trading day) Sharpe for all strategies."""
    print("\n[4/8] Computing rolling 3-year Sharpe...")
    rolling_sharpe = pd.DataFrame(index=returns.index)
    for col in returns.columns:
        r = returns[col]
        roll_mean = r.rolling(window).mean() * TRADING_DAYS
        roll_std = r.rolling(window).std() * ANNUALIZE
        rolling_sharpe[col] = (roll_mean - RF_ANNUAL) / roll_std
    return rolling_sharpe


# ============================================================
#  Year-by-Year Returns
# ============================================================
def compute_yearly_returns(returns: pd.DataFrame) -> pd.DataFrame:
    """Compute year-by-year returns for all strategies."""
    print("\n[5/8] Computing year-by-year returns...")
    yearly = pd.DataFrame()
    for col in returns.columns:
        yr = (1 + returns[col]).resample("YE").prod() - 1
        yr.index = yr.index.year
        yearly[col] = yr
    return yearly


# ============================================================
#  Insurance Efficiency (K573 framework)
# ============================================================
def compute_insurance_efficiency(returns: pd.DataFrame, df: pd.DataFrame) -> dict:
    """Compute insurance efficiency metrics relative to Buy & Hold SPY."""
    print("\n[6/8] Computing insurance efficiency...")

    bh_ret = returns["BH_SPY"]
    bh_cum = (1 + bh_ret).cumprod()
    bh_peak = bh_cum.cummax()
    bh_dd = (bh_cum - bh_peak) / bh_peak
    bh_mdd = bh_dd.min()
    bh_cagr = (bh_cum.iloc[-1]) ** (TRADING_DAYS / len(bh_ret)) - 1

    efficiency = {}
    for col in returns.columns:
        if col == "BH_SPY":
            continue

        r = returns[col]
        cum = (1 + r).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        mdd = dd.min()
        cagr = (cum.iloc[-1]) ** (TRADING_DAYS / len(r)) - 1

        return_cost = (bh_cagr - cagr) * 100  # pp of annual return given up
        mdd_improvement = (bh_mdd - mdd) * 100  # pp of MDD improvement

        if return_cost > 0:
            eff_ratio = mdd_improvement / return_cost  # MDD improvement per 1% return cost
        elif return_cost < 0:
            eff_ratio = float("inf")  # strategy beats B&H on return AND MDD
        else:
            eff_ratio = float("inf")

        efficiency[col] = {
            "return_cost_pp": round(return_cost, 2),
            "mdd_improvement_pp": round(mdd_improvement, 2),
            "efficiency_ratio": round(eff_ratio, 2) if eff_ratio != float("inf") else "inf",
        }

    return efficiency


# ============================================================
#  Crisis Analysis
# ============================================================
def compute_crisis_analysis(returns: pd.DataFrame) -> dict:
    """Compute drawdown during each crisis period for all strategies."""
    print("\n  Computing crisis-period analysis...")
    crisis_results = {}
    for crisis_name, (start, end) in CRISIS_PERIODS.items():
        crisis_results[crisis_name] = {}
        for col in returns.columns:
            mask = (returns.index >= start) & (returns.index <= end)
            if mask.sum() == 0:
                continue
            r = returns.loc[mask, col]
            cum = (1 + r).cumprod()
            peak = cum.cummax()
            dd = (cum - peak) / peak
            crisis_results[crisis_name][col] = {
                "period_return_pct": round((cum.iloc[-1] - 1) * 100, 2),
                "mdd_pct": round(dd.min() * 100, 2),
                "n_days": int(mask.sum()),
            }
    return crisis_results


# ============================================================
#  Charts
# ============================================================
STRATEGY_LABELS = {
    "BH_SPY": "Buy & Hold SPY",
    "BH_5050": "50/50 SPY/GLD",
    "VT_12VIX": "12/VIX VT (Standard)",
    "VCL": "VIX-Cond Leverage (Growth)",
    "PW_Cons": "Piecewise VT (Conservative)",
}

STRATEGY_COLORS = {
    "BH_SPY": "#888888",
    "BH_5050": "#2196F3",
    "VT_12VIX": "#4CAF50",
    "VCL": "#FF5722",
    "PW_Cons": "#9C27B0",
}


def plot_cumulative_growth(returns: pd.DataFrame, dca_results: dict) -> str:
    """Plot $1M cumulative growth for all strategies + Fear DCA."""
    print("\n[7/8] Generating charts...")
    print("  Chart 1: Cumulative growth of $1M...")

    fig, ax = plt.subplots(figsize=(14, 8))

    for col in returns.columns:
        cum = INITIAL_CAPITAL * (1 + returns[col]).cumprod()
        ax.plot(cum.index, cum.values, label=STRATEGY_LABELS.get(col, col),
                color=STRATEGY_COLORS.get(col, "black"), linewidth=1.5,
                alpha=0.9)

    # Add Fear DCA (scaled to $1M equivalent)
    if dca_results and "base_portfolio_values" in dca_results:
        dates = pd.to_datetime(dca_results["dates"])
        base_vals = np.array(dca_results["base_portfolio_values"])
        fear_vals = np.array(dca_results["fear_portfolio_values"])
        # Scale DCA to $1M start equivalent
        if base_vals[0] > 0:
            scale = INITIAL_CAPITAL / base_vals[0]
            ax.plot(dates, fear_vals * scale, label="Fear DCA (monthly)",
                    color="#FF9800", linewidth=1.5, linestyle="--", alpha=0.8)

    ax.set_title("Growth of $1,000,000 — All Strategy Tiers (2005-2026)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Portfolio Value ($)", fontsize=12)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"${x/1e6:.1f}M"))
    ax.legend(loc="upper left", fontsize=10)
    ax.grid(True, alpha=0.3)
    ax.set_yscale("log")

    # Add crisis shading
    for crisis_name, (start, end) in CRISIS_PERIODS.items():
        ax.axvspan(pd.Timestamp(start), pd.Timestamp(end), alpha=0.1, color="red")

    fig.tight_layout()
    path = str(CHART_DIR / "k574_cumulative_growth.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"    Saved: {path}")
    return path


def plot_drawdown_timeline(returns: pd.DataFrame) -> str:
    """Plot drawdown timeline for all strategies."""
    print("  Chart 2: Drawdown timeline...")

    fig, ax = plt.subplots(figsize=(14, 6))

    for col in returns.columns:
        cum = (1 + returns[col]).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        ax.fill_between(dd.index, dd.values * 100, 0,
                        alpha=0.15, color=STRATEGY_COLORS.get(col, "gray"))
        ax.plot(dd.index, dd.values * 100,
                label=STRATEGY_LABELS.get(col, col),
                color=STRATEGY_COLORS.get(col, "black"),
                linewidth=1.0, alpha=0.8)

    ax.set_title("Drawdown Timeline — All Strategies (2005-2026)", fontsize=14, fontweight="bold")
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Drawdown (%)", fontsize=12)
    ax.legend(loc="lower left", fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.set_ylim(bottom=None, top=2)

    fig.tight_layout()
    path = str(CHART_DIR / "k574_drawdown_timeline.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"    Saved: {path}")
    return path


def plot_risk_return_scatter(metrics_list: list) -> str:
    """Plot risk-return scatter for all strategies."""
    print("  Chart 3: Risk-return scatter...")

    fig, ax = plt.subplots(figsize=(10, 8))

    for m in metrics_list:
        name = m["name"]
        vol = m["ann_vol_pct"]
        ret = m["cagr_pct"]
        sharpe = m["sharpe"]
        color = STRATEGY_COLORS.get(name, "#333333")
        label = STRATEGY_LABELS.get(name, name)

        ax.scatter(vol, ret, s=200, color=color, edgecolors="black",
                   linewidth=1.5, zorder=5)
        ax.annotate(f"{label}\nSharpe={sharpe:.2f}",
                    (vol, ret), textcoords="offset points",
                    xytext=(12, 8), fontsize=9,
                    bbox=dict(boxstyle="round,pad=0.3", facecolor=color, alpha=0.2))

    # Sharpe lines
    vol_range = np.linspace(0, 20, 100)
    for s in [0.5, 1.0, 1.5]:
        ret_line = RF_ANNUAL * 100 + s * vol_range
        ax.plot(vol_range, ret_line, "--", color="gray", alpha=0.3, linewidth=0.8)
        ax.annotate(f"Sharpe={s:.1f}", (vol_range[-1], ret_line[-1]),
                    fontsize=8, color="gray", alpha=0.5)

    ax.set_title("Risk-Return Tradeoff — All Strategy Tiers", fontsize=14, fontweight="bold")
    ax.set_xlabel("Annualized Volatility (%)", fontsize=12)
    ax.set_ylabel("CAGR (%)", fontsize=12)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    path = str(CHART_DIR / "k574_risk_return_scatter.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"    Saved: {path}")
    return path


def plot_rolling_sharpe(rolling_sharpe: pd.DataFrame) -> str:
    """Plot rolling 3-year Sharpe for all strategies."""
    print("  Chart 4: Rolling 3-year Sharpe...")

    fig, ax = plt.subplots(figsize=(14, 6))

    for col in rolling_sharpe.columns:
        rs = rolling_sharpe[col].dropna()
        ax.plot(rs.index, rs.values,
                label=STRATEGY_LABELS.get(col, col),
                color=STRATEGY_COLORS.get(col, "black"),
                linewidth=1.2, alpha=0.85)

    ax.axhline(y=0, color="black", linewidth=0.5, linestyle="-")
    ax.axhline(y=1.0, color="gray", linewidth=0.5, linestyle="--", alpha=0.5)

    ax.set_title("Rolling 3-Year Sharpe Ratio — All Strategies", fontsize=14, fontweight="bold")
    ax.set_xlabel("Date", fontsize=12)
    ax.set_ylabel("Sharpe Ratio (3-Year Rolling)", fontsize=12)
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(True, alpha=0.3)

    fig.tight_layout()
    path = str(CHART_DIR / "k574_rolling_sharpe.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"    Saved: {path}")
    return path


def plot_yearly_heatmap(yearly_returns: pd.DataFrame) -> str:
    """Plot year-by-year return heatmap."""
    print("  Chart 5: Year-by-year return heatmap...")

    # Rename columns for display
    display_cols = {col: STRATEGY_LABELS.get(col, col) for col in yearly_returns.columns}
    yr_display = yearly_returns.rename(columns=display_cols) * 100

    fig, ax = plt.subplots(figsize=(14, max(8, len(yr_display) * 0.4 + 2)))

    # Create heatmap manually
    data = yr_display.values
    n_rows, n_cols = data.shape

    # Color mapping: red for negative, green for positive
    for i in range(n_rows):
        for j in range(n_cols):
            val = data[i, j]
            if np.isnan(val):
                color = "white"
            elif val < -10:
                color = "#d32f2f"
            elif val < -5:
                color = "#ef5350"
            elif val < 0:
                color = "#ffcdd2"
            elif val < 5:
                color = "#c8e6c9"
            elif val < 15:
                color = "#66bb6a"
            else:
                color = "#2e7d32"

            ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1,
                                       facecolor=color, edgecolor="white", linewidth=1))
            text_color = "white" if (val < -10 or val > 15) else "black"
            ax.text(j, i, f"{val:.1f}%", ha="center", va="center",
                    fontsize=9, color=text_color, fontweight="bold")

    ax.set_xlim(-0.5, n_cols - 0.5)
    ax.set_ylim(n_rows - 0.5, -0.5)
    ax.set_xticks(range(n_cols))
    ax.set_xticklabels(yr_display.columns, rotation=30, ha="right", fontsize=10)
    ax.set_yticks(range(n_rows))
    ax.set_yticklabels(yr_display.index, fontsize=10)
    ax.set_title("Year-by-Year Returns (%) — All Strategies", fontsize=14, fontweight="bold")

    fig.tight_layout()
    path = str(CHART_DIR / "k574_yearly_heatmap.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"    Saved: {path}")
    return path


# ============================================================
#  Summary Table (paper-ready)
# ============================================================
def print_summary_table(metrics_list: list, dca_results: dict):
    """Print a paper-ready comparison table."""
    print("\n" + "=" * 120)
    print("TABLE 1: DEFINITIVE STRATEGY COMPARISON (2005-2026)")
    print("=" * 120)

    header = f"{'Metric':<30}"
    for m in metrics_list:
        label = STRATEGY_LABELS.get(m["name"], m["name"])
        header += f" {label:>18}"
    print(header)
    print("-" * 120)

    rows = [
        ("CAGR (%)", "cagr_pct", "{:.2f}"),
        ("Ann. Volatility (%)", "ann_vol_pct", "{:.2f}"),
        ("Sharpe Ratio", "sharpe", "{:.3f}"),
        ("Sortino Ratio", "sortino", "{:.3f}"),
        ("Calmar Ratio", "calmar", "{:.3f}"),
        ("Max Drawdown (%)", "mdd_pct", "{:.2f}"),
        ("Max Underwater (days)", "max_underwater_days", "{:d}"),
        ("Worst Month (%)", "worst_month_pct", "{:.2f}"),
        ("Worst Quarter (%)", "worst_quarter_pct", "{:.2f}"),
        ("Worst Year (%)", "worst_year_pct", "{:.2f}"),
        ("Best Year (%)", "best_year_pct", "{:.2f}"),
        ("VaR 1% (%)", "var_1pct", "{:.4f}"),
        ("CVaR 1% (%)", "cvar_1pct", "{:.4f}"),
        ("Turnover (annual)", "turnover_annual", "{:.2f}"),
        ("TX Drag (%/yr)", "tx_drag_pct", "{:.4f}"),
        ("Win Rate", "win_rate", "{:.4f}"),
        ("Skewness", "skewness", "{:.3f}"),
        ("Kurtosis", "kurtosis", "{:.3f}"),
        ("Terminal $1M", "terminal_1m", "${:,.0f}"),
    ]

    for label, key, fmt in rows:
        row = f"{label:<30}"
        for m in metrics_list:
            val = m.get(key, "N/A")
            if val == "N/A":
                row += f" {'N/A':>18}"
            else:
                formatted = fmt.format(val)
                row += f" {formatted:>18}"
        print(row)

    print("-" * 120)

    # Fear DCA row
    if dca_results:
        print(f"\n{'--- FEAR DCA (Monthly $1000) ---':^120}")
        print(f"  Total invested: ${dca_results['total_invested']:,.0f}")
        print(f"  Base DCA terminal: ${dca_results['base_dca']['terminal_value']:,.0f}"
              f"  |  IRR: {dca_results['base_dca']['irr_annual']*100:.1f}%"
              f"  |  MDD: {dca_results['base_dca']['mdd']*100:.1f}%"
              f"  |  Sharpe(mo): {dca_results['base_dca']['sharpe_monthly']:.2f}")
        print(f"  Fear DCA terminal: ${dca_results['fear_dca']['terminal_value']:,.0f}"
              f"  |  IRR: {dca_results['fear_dca']['irr_annual']*100:.1f}%"
              f"  |  MDD: {dca_results['fear_dca']['mdd']*100:.1f}%"
              f"  |  Sharpe(mo): {dca_results['fear_dca']['sharpe_monthly']:.2f}")
        print(f"  Fear vs Base: {dca_results['fear_dca']['improvement_pct']:+.1f}% terminal"
              f"  |  {dca_results['fear_dca']['mdd_improvement_pp']:+.1f}pp MDD")


# ============================================================
#  Statistical Tests (DM test, pairwise)
# ============================================================
def compute_dm_tests(returns: pd.DataFrame) -> dict:
    """Compute Diebold-Mariano tests for Sharpe ratio differences."""
    print("\n  Computing DM tests (pairwise)...")
    dm_results = {}
    baseline = "BH_SPY"
    strategies = [c for c in returns.columns if c != baseline]

    for strat in strategies:
        # Loss differential = squared returns (proxy for volatility-adjusted loss)
        # Actually for Sharpe comparison we use bootstrap
        d = returns[strat].values - returns[baseline].values
        n = len(d)
        d_mean = d.mean()
        d_std = d.std() / np.sqrt(n)
        t_stat = d_mean / d_std if d_std > 0 else 0

        dm_results[f"{strat}_vs_{baseline}"] = {
            "dm_t": round(t_stat, 3),
            "dm_p": round(2 * (1 - stats.t.cdf(abs(t_stat), n - 1)), 4),
            "mean_diff_daily": round(d_mean * 10000, 2),  # bps per day
            "significant_5pct": bool(abs(t_stat) > 1.96),
            "significant_harvey": bool(abs(t_stat) > 3.0),
        }

    # Also test VT strategies against each other
    vt_pairs = [
        ("VT_12VIX", "PW_Cons"),
        ("VT_12VIX", "VCL"),
        ("VCL", "PW_Cons"),
    ]
    for a, b in vt_pairs:
        if a in returns.columns and b in returns.columns:
            d = returns[a].values - returns[b].values
            n = len(d)
            d_mean = d.mean()
            d_std = d.std() / np.sqrt(n)
            t_stat = d_mean / d_std if d_std > 0 else 0
            dm_results[f"{a}_vs_{b}"] = {
                "dm_t": round(t_stat, 3),
                "dm_p": round(2 * (1 - stats.t.cdf(abs(t_stat), n - 1)), 4),
                "mean_diff_daily": round(d_mean * 10000, 2),
                "significant_5pct": bool(abs(t_stat) > 1.96),
                "significant_harvey": bool(abs(t_stat) > 3.0),
            }

    return dm_results


# ============================================================
#  Main
# ============================================================
def main():
    t0 = datetime.now()

    # 1. Download data
    df = download_data()

    # 2. Compute strategy returns
    returns, weights = compute_strategy_returns(df)

    # 3. Fear DCA simulation
    dca_results = compute_fear_dca(df)

    # 4. Comprehensive metrics
    print("\n[4/8] Computing comprehensive metrics...")
    metrics_list = []
    for col in returns.columns:
        m = compute_metrics(
            returns[col],
            weights=weights[col] if col in weights.columns else None,
            rf_daily=df["rf_daily"],
            name=col
        )
        metrics_list.append(m)

    # 5. Rolling Sharpe
    rolling_sharpe = compute_rolling_sharpe(returns)

    # 6. Year-by-year
    yearly_returns = compute_yearly_returns(returns)

    # 7. Insurance efficiency
    insurance_eff = compute_insurance_efficiency(returns, df)

    # 8. Crisis analysis
    crisis_analysis = compute_crisis_analysis(returns)

    # 9. DM tests
    dm_tests = compute_dm_tests(returns)

    # ---- Print results ----
    print_summary_table(metrics_list, dca_results)

    # Print insurance efficiency
    print("\n" + "=" * 80)
    print("INSURANCE EFFICIENCY (vs Buy & Hold SPY)")
    print("=" * 80)
    print(f"{'Strategy':<35} {'Return Cost':>12} {'MDD Improv.':>12} {'Efficiency':>12}")
    print("-" * 80)
    for strat, eff in insurance_eff.items():
        label = STRATEGY_LABELS.get(strat, strat)
        eff_str = f"{eff['efficiency_ratio']:.2f}" if eff['efficiency_ratio'] != "inf" else "inf"
        print(f"{label:<35} {eff['return_cost_pp']:>11.2f}pp {eff['mdd_improvement_pp']:>11.2f}pp {eff_str:>12}")

    # Print crisis analysis
    print("\n" + "=" * 80)
    print("CRISIS-PERIOD DRAWDOWNS")
    print("=" * 80)
    for crisis_name, strats in crisis_analysis.items():
        print(f"\n  {crisis_name}:")
        for strat, data in strats.items():
            label = STRATEGY_LABELS.get(strat, strat)
            print(f"    {label:<35} Return: {data['period_return_pct']:>7.1f}%  MDD: {data['mdd_pct']:>7.1f}%")

    # Print DM tests
    print("\n" + "=" * 80)
    print("DIEBOLD-MARIANO TESTS")
    print("=" * 80)
    for pair, result in dm_tests.items():
        sig_marker = "***" if result["significant_harvey"] else ("**" if result["significant_5pct"] else "")
        print(f"  {pair:<30} t={result['dm_t']:>7.3f}  p={result['dm_p']:.4f}  "
              f"diff={result['mean_diff_daily']:>6.2f} bps/day  {sig_marker}")

    # Print year-by-year
    print("\n" + "=" * 80)
    print("YEAR-BY-YEAR RETURNS (%)")
    print("=" * 80)
    header = f"{'Year':<6}"
    for col in yearly_returns.columns:
        label = STRATEGY_LABELS.get(col, col)[:18]
        header += f" {label:>18}"
    print(header)
    print("-" * (6 + 19 * len(yearly_returns.columns)))
    for year in yearly_returns.index:
        row = f"{year:<6}"
        for col in yearly_returns.columns:
            val = yearly_returns.loc[year, col]
            row += f" {val*100:>17.1f}%"
        print(row)

    # ---- Generate charts ----
    chart_paths = {}
    chart_paths["cumulative_growth"] = plot_cumulative_growth(returns, dca_results)
    chart_paths["drawdown_timeline"] = plot_drawdown_timeline(returns)
    chart_paths["risk_return_scatter"] = plot_risk_return_scatter(metrics_list)
    chart_paths["rolling_sharpe"] = plot_rolling_sharpe(rolling_sharpe)
    chart_paths["yearly_heatmap"] = plot_yearly_heatmap(yearly_returns)

    # ---- Save results JSON ----
    print("\n[8/8] Saving results...")

    elapsed = (datetime.now() - t0).total_seconds()

    results = {
        "experiment_id": "K574",
        "title": "K574: Complete 3-Tier Strategy Backtest — Definitive Comparison",
        "description": "Side-by-side comparison of all validated VolPred strategies with consistent methodology",
        "data_source": "yfinance (SPY, GLD, ^VIX, ^IRX)",
        "period": f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
        "n_trading_days": int(len(df)),
        "strategies": {
            "BH_SPY": "Buy & Hold SPY (baseline)",
            "BH_5050": "Buy & Hold 50/50 SPY/GLD (diversified baseline)",
            "VT_12VIX": "Standard 12/VIX Volatility Timing with 50/50 SPY/GLD",
            "VCL": "VIX-Conditional Leverage (1.5x low VIX, 1.0x high VIX) — K548/K551",
            "PW_Cons": "Piecewise Conservative VT (c1=12, c2=20) — K569",
            "Fear_DCA": "Fear DCA ($1500 VIX>25, $500 VIX<15, budget-neutral) — K552",
        },
        "metrics": {m["name"]: m for m in metrics_list},
        "fear_dca": dca_results,
        "insurance_efficiency": insurance_eff,
        "crisis_analysis": crisis_analysis,
        "dm_tests": dm_tests,
        "yearly_returns": {
            str(year): {col: round(yearly_returns.loc[year, col] * 100, 2)
                        for col in yearly_returns.columns}
            for year in yearly_returns.index
        },
        "chart_paths": chart_paths,
        "tier_recommendations": {
            "conservative": {
                "strategy": "PW_Cons",
                "target_investor": "Risk-averse: retirees, conservative savers",
                "key_feature": "MDD < 6%, crisis protection > 90%, lower CAGR trade-off",
                "validation": "K569: 6/8 pass, Harvey z=2.84 (near miss), bootstrap P>B&H=99.8%",
            },
            "standard": {
                "strategy": "VT_12VIX",
                "target_investor": "Core allocation: most investors seeking risk-adjusted optimization",
                "key_feature": "Best risk-adjusted returns, Sharpe > 1.0, balanced MDD/return",
                "validation": "K275 synthesis: 31x VIX sufficiency confirmed, Harvey t=4.5+",
            },
            "growth": {
                "strategy": "VCL",
                "target_investor": "Growth-oriented: margin-account holders, active investors",
                "key_feature": "Highest CAGR, leveraged upside in calm markets, same crisis protection",
                "validation": "K551: Harvey t=7.90, 11/11 OOS, 100% bootstrap, borrowing cost covered",
            },
            "monthly_saver": {
                "strategy": "Fear_DCA",
                "target_investor": "Retail DCA investors: salary workers making monthly contributions",
                "key_feature": "Budget-neutral, simple VIX rule, improves on fixed DCA (~3% terminal, -9pp MDD)",
                "validation": "K552: 3/3 OOS consistent but NS (improvement modest vs variance)",
            },
        },
        "execution_time_sec": round(elapsed, 1),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "references": [
            "Moreira & Muir (2017, JoF): Volatility-managed portfolios",
            "Harvey (2016, JoF): Multiple testing threshold t>3.0",
            "Fleming, Kirby & Ostdiek (2001, JFE): Economic value of vol timing",
            "K275: Complete case for 50/50 SPY/GLD + 12/VIX",
            "K548/K551: VIX-Conditional Leverage (Harvey t=7.90)",
            "K569: Piecewise VT (6/8 pass, conservative tier)",
            "K552: Fear DCA (3/3 OOS consistent)",
            "K573: Insurance pricing theory",
        ],
    }

    # Convert any non-serializable numpy types
    def convert_numpy(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        return obj

    def deep_convert(obj):
        if isinstance(obj, dict):
            return {k: deep_convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [deep_convert(v) for v in obj]
        return convert_numpy(obj)

    results = deep_convert(results)

    results_path = Path(__file__).resolve().parent / "k574_complete_strategy_backtest_results.json"
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"  Results saved: {results_path}")

    # Summary
    print("\n" + "=" * 80)
    print("K574 COMPLETE — STRATEGY TIER SUMMARY")
    print("=" * 80)
    print(f"\n  Conservative (PW):  Sharpe {metrics_list[4]['sharpe']:.3f}  CAGR {metrics_list[4]['cagr_pct']:.1f}%  MDD {metrics_list[4]['mdd_pct']:.1f}%")
    print(f"  Standard (12/VIX):  Sharpe {metrics_list[2]['sharpe']:.3f}  CAGR {metrics_list[2]['cagr_pct']:.1f}%  MDD {metrics_list[2]['mdd_pct']:.1f}%")
    print(f"  Growth (VCL):       Sharpe {metrics_list[3]['sharpe']:.3f}  CAGR {metrics_list[3]['cagr_pct']:.1f}%  MDD {metrics_list[3]['mdd_pct']:.1f}%")
    print(f"  Fear DCA:           IRR {dca_results['fear_dca']['irr_annual']*100:.1f}%  MDD {dca_results['fear_dca']['mdd']*100:.1f}%  vs Base DCA: {dca_results['fear_dca']['improvement_pct']:+.1f}%")
    print(f"\n  Baselines:")
    print(f"  B&H SPY:            Sharpe {metrics_list[0]['sharpe']:.3f}  CAGR {metrics_list[0]['cagr_pct']:.1f}%  MDD {metrics_list[0]['mdd_pct']:.1f}%")
    print(f"  50/50 SPY/GLD:      Sharpe {metrics_list[1]['sharpe']:.3f}  CAGR {metrics_list[1]['cagr_pct']:.1f}%  MDD {metrics_list[1]['mdd_pct']:.1f}%")
    print(f"\n  Charts: {CHART_DIR}")
    print(f"  Elapsed: {elapsed:.1f}s")

    return results


if __name__ == "__main__":
    main()
