"""K738: VT Insurance Cost-Benefit Analysis — Quantifying the Price of Tail Protection
=====================================================================================
COMPREHENSIVE cost-benefit analysis of Volatility Targeting across 5 assets and
4 strategy variants.

Motivation:
  K687 showed no VT beats BH 50/50 on Sharpe after proper lag. K688 showed VT wins
  on CRRA utility at gamma>=5. K41 found VT insurance premium ~4%/yr. But we haven't
  done a COMPREHENSIVE cross-asset analysis quantifying:
    - Exact cost (return drag, bull-market opportunity cost, TX cost)
    - Exact benefit (MDD reduction, worst-month improvement, recovery)
    - Cost per unit of protection
    - Break-even gamma (where VT becomes worthwhile)

This creates a practical "VT Decision Guide" for investors.

Assets: SPY, GLD, QQQ, EEM, 0050.TW
Strategies: 12/VIX, Risk Parity (50/50), BH 100% equity, BH 50/50

Data source: yfinance (SPY, GLD, QQQ, EEM, 0050.TW, ^VIX)
Period: 2006-01-01 to 2026-03-30 (20 years)
Evaluation: 2007-01-03 to present (1y warmup for EWMA/rolling stats)
Type: Empirical analysis (real data)

References:
  - K687: Post-correction definitive ranking (no VT beats BH 50/50 on Sharpe)
  - K688: CRRA lag-corrected (VT wins utility at gamma>=5)
  - K697: VIX predicts vol magnitude (r=0.57), not direction (r=0.04)
  - K41: VT insurance premium ~4%/yr at ALL horizons
  - K15: VT regime value decomposition
  - Arrow (1965), Aspects of the Theory of Risk-Bearing
  - Pratt (1964), Risk Aversion in the Small and in the Large
  - Copeland & Copeland (1999), Market Timing with VIX
  - Harvey et al. (2016), ...and the Cross-Section of Expected Returns (t>3.0)
  - RiskMetrics (1996), Technical Document (EWMA lambda=0.94)
  - Moreira & Muir (2017), Volatility-Managed Portfolios, JF

[提出: Claude, 執行: Claude]
Author: VolPred Research System
Date: 2026-03-30
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
START_DATE = "2006-01-01"
END_DATE = "2026-03-30"
EVAL_START = "2007-01-03"       # 1y warmup for EWMA / rolling stats
EWMA_LAMBDA = 0.94             # RiskMetrics EWMA decay factor
TARGET_VOL = 0.10              # 10% annualized target volatility
VIX_12_CAP = 1.5               # Cap for 12/VIX weight
TC_BPS = 5                     # Transaction cost in basis points
RF_ANNUAL = 0.04               # Risk-free rate
RF_DAILY = RF_ANNUAL / 252

# CRRA gamma values
GAMMAS = [2, 5, 10, 20]

# Assets to analyze
ASSETS = {
    "SPY": "SPY",
    "GLD": "GLD",
    "QQQ": "QQQ",
    "EEM": "EEM",
    "0050.TW": "0050.TW",
}

# Bull year threshold: SPY annual return > 20%
BULL_THRESHOLD = 0.20


# ============================================================================
# Data Download
# ============================================================================
def download_all_data():
    """Download all asset data + VIX from yfinance."""
    print("=" * 70)
    print("K738: VT INSURANCE COST-BENEFIT ANALYSIS")
    print("=" * 70)
    print(f"\nPeriod: {START_DATE} to {END_DATE}")
    print(f"Evaluation from: {EVAL_START}")
    print(f"\nDownloading data from yfinance...")

    # Download VIX
    vix_df = yf.download("^VIX", start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)
    vix_close = vix_df["Close"].copy()
    vix_close.name = "vix"
    print(f"  VIX: {len(vix_df)} rows, {vix_df.index[0].date()} to {vix_df.index[-1].date()}")

    # Download each asset
    asset_data = {}
    for name, ticker in ASSETS.items():
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        ret = df["Close"].pct_change().dropna()
        # Filter obvious data artifacts (e.g., 0050.TW 2014-01-02 stock split glitch)
        # Taiwan circuit breaker = 10%, US = 20%. Anything beyond 30% is almost certainly bad data
        n_before = len(ret)
        ret = ret[(ret > -0.30) & (ret < 0.30)]
        n_filtered = n_before - len(ret)
        if n_filtered > 0:
            print(f"    WARNING: Filtered {n_filtered} extreme returns (|r| > 30%) from {name}")
        ret.name = f"{name}_ret"
        asset_data[name] = ret
        print(f"  {name}: {len(ret)} rows, {df.index[0].date()} to {df.index[-1].date()}")

    # Download GLD for Risk Parity (need it for 50/50 with each equity asset)
    gld_df = yf.download("GLD", start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
    if isinstance(gld_df.columns, pd.MultiIndex):
        gld_df.columns = gld_df.columns.get_level_values(0)
    gld_ret = gld_df["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"

    return asset_data, vix_close, gld_ret


# ============================================================================
# EWMA Volatility
# ============================================================================
def compute_ewma_vol(returns, lam=EWMA_LAMBDA):
    """EWMA volatility (RiskMetrics), returns annualized vol series."""
    var = np.zeros(len(returns))
    var[0] = returns.iloc[0] ** 2 if len(returns) > 0 else 0.0001
    for i in range(1, len(returns)):
        var[i] = lam * var[i - 1] + (1 - lam) * returns.iloc[i] ** 2
    vol_daily = np.sqrt(var)
    vol_ann = vol_daily * np.sqrt(252)
    return pd.Series(vol_ann, index=returns.index, name="ewma_vol")


# ============================================================================
# CRRA Utility & Certainty Equivalent
# ============================================================================
def crra_utility(daily_returns, gamma):
    """Compute CRRA certainty equivalent (annualized %).

    CE_daily = (E[(1+r)^(1-gamma)])^(1/(1-gamma)) - 1    for gamma != 1
    CE_daily = exp(E[ln(1+r)]) - 1                         for gamma = 1
    CE_annual = (1 + CE_daily)^252 - 1
    """
    gross_returns = 1 + daily_returns.values
    gross_returns = gross_returns[gross_returns > 0]

    if len(gross_returns) < 100:
        return np.nan

    if gamma == 1:
        mean_log = np.mean(np.log(gross_returns))
        ce_daily = np.exp(mean_log) - 1
    else:
        powered = gross_returns ** (1 - gamma)
        mean_powered = np.mean(powered)
        if mean_powered <= 0:
            return np.nan
        ce_daily = mean_powered ** (1 / (1 - gamma)) - 1

    ce_annual = (1 + ce_daily) ** 252 - 1
    return ce_annual * 100  # percentage


# ============================================================================
# Strategy Implementation for ONE Asset
# ============================================================================
def run_single_asset(asset_name, asset_ret, vix_close, gld_ret):
    """Run all 4 strategies on a single asset and compute cost-benefit metrics.

    Strategies:
      1. BH 100%: Buy-and-hold the asset 100%
      2. BH 50/50: 50% asset + 50% GLD (diversification only)
      3. 12/VIX: VT on 50/50 asset+GLD base (smooth weight)
      4. EWMA VT: EWMA vol targeting on 50/50 asset+GLD base

    For assets without GLD pairing (GLD itself), use the asset alone.
    """
    print(f"\n{'='*70}")
    print(f"  ASSET: {asset_name}")
    print(f"{'='*70}")

    # Merge data
    data = pd.concat([asset_ret, gld_ret, vix_close], axis=1).dropna()

    # Rename columns for consistency
    col_names = list(data.columns)
    data.columns = ["asset_ret", "gld_ret", "vix"]

    # 50/50 base portfolio return
    if asset_name == "GLD":
        # For GLD, the 50/50 is with SPY — handled separately since we already have it
        data["port_ret"] = data["asset_ret"]  # Just GLD alone as "equity" side
    else:
        data["port_ret"] = 0.5 * data["asset_ret"] + 0.5 * data["gld_ret"]

    # ================================================================
    # 12/VIX signal (lagged)
    # ================================================================
    raw_12vix = np.minimum(12.0 / data["vix"], VIX_12_CAP)
    data["w_12vix"] = raw_12vix.shift(1)  # LAG: signal from t-1

    # ================================================================
    # EWMA VT signal (lagged)
    # ================================================================
    ewma_vol = compute_ewma_vol(data["port_ret"], lam=EWMA_LAMBDA)
    raw_ewma_w = np.minimum(TARGET_VOL / ewma_vol.clip(lower=0.01), 2.0)
    data["w_ewma"] = raw_ewma_w.shift(1)  # LAG: signal from t-1

    # Trim to evaluation period
    data = data.loc[EVAL_START:]
    data = data.dropna()

    if len(data) < 252:
        print(f"  WARNING: Only {len(data)} days after trimming. Skipping.")
        return None

    print(f"  Evaluation: {len(data)} days, {data.index[0].date()} to {data.index[-1].date()}")

    # ================================================================
    # Compute strategy returns (net of TX)
    # ================================================================
    strategies = {}

    # (1) BH 100% asset
    strategies["BH_100"] = data["asset_ret"].copy()

    # (2) BH 50/50 (asset + GLD) — no TX for static allocation
    if asset_name == "GLD":
        strategies["BH_5050"] = data["asset_ret"].copy()  # GLD alone
    else:
        strategies["BH_5050"] = data["port_ret"].copy()

    # (3) 12/VIX on 50/50
    w = data["w_12vix"]
    raw_ret = w * data["port_ret"]
    dw = w.diff().abs()
    tc = dw * (TC_BPS / 10000)
    strategies["12/VIX"] = raw_ret - tc

    # (4) EWMA VT on 50/50
    w = data["w_ewma"]
    raw_ret = w * data["port_ret"]
    dw = w.diff().abs()
    tc = dw * (TC_BPS / 10000)
    strategies["EWMA_VT"] = raw_ret - tc

    # ================================================================
    # Compute metrics for each strategy
    # ================================================================
    results = {}
    for sname, rets in strategies.items():
        rets = rets.dropna()
        n = len(rets)
        cum = (1 + rets).prod()
        years = n / 252
        cagr = (cum ** (1 / years) - 1) * 100
        ann_vol = rets.std() * np.sqrt(252) * 100
        sharpe = (rets.mean() - RF_DAILY) / rets.std() * np.sqrt(252) if rets.std() > 0 else 0
        cum_wealth = (1 + rets).cumprod()
        drawdown = cum_wealth / cum_wealth.cummax() - 1
        mdd = drawdown.min() * 100

        # Worst month
        monthly_rets = rets.resample("ME").apply(lambda x: (1 + x).prod() - 1)
        worst_month = monthly_rets.min() * 100

        # Best month
        best_month = monthly_rets.max() * 100

        # Average turnover (daily weight change, annualized)
        if sname in ["12/VIX", "EWMA_VT"]:
            if sname == "12/VIX":
                ws = data["w_12vix"]
            else:
                ws = data["w_ewma"]
            avg_turnover = ws.diff().abs().mean() * 252 * 100  # annualized %
            total_tc = (ws.diff().abs() * (TC_BPS / 10000)).sum() * 100  # total TC over period
            tc_annual = total_tc / years
        else:
            avg_turnover = 0.0
            total_tc = 0.0
            tc_annual = 0.0

        # Sortino ratio
        downside = rets[rets < 0]
        downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-6
        sortino = (rets.mean() * 252 - RF_ANNUAL) / downside_vol

        # Calmar ratio
        calmar = cagr / abs(mdd) if abs(mdd) > 0.01 else np.nan

        # Recovery time: average days from drawdown trough to recovery
        # Simplified: count days in drawdown > 5%
        days_in_deep_dd = (drawdown < -0.05).sum()
        pct_in_deep_dd = days_in_deep_dd / n * 100

        # CRRA utility for each gamma
        crra_results = {}
        for g in GAMMAS:
            ce = crra_utility(rets, g)
            crra_results[f"gamma_{g}"] = round(ce, 3) if not np.isnan(ce) else None

        # Bull-market performance (years where BH 100% > 20%)
        yearly_bh = strategies["BH_100"].resample("YE").apply(lambda x: (1 + x).prod() - 1)
        yearly_strat = rets.resample("YE").apply(lambda x: (1 + x).prod() - 1)
        bull_years = yearly_bh[yearly_bh > BULL_THRESHOLD].index
        if len(bull_years) > 0:
            bull_ret_bh = yearly_bh.loc[bull_years].mean() * 100
            # Get strategy returns for same years
            matching_bull = yearly_strat.reindex(bull_years)
            bull_ret_strat = matching_bull.mean() * 100
            bull_drag = bull_ret_strat - bull_ret_bh
        else:
            bull_ret_bh = np.nan
            bull_ret_strat = np.nan
            bull_drag = np.nan

        results[sname] = {
            "n_days": int(n),
            "years": round(years, 1),
            "cagr_pct": round(cagr, 3),
            "ann_vol_pct": round(ann_vol, 3),
            "sharpe": round(sharpe, 4),
            "sortino": round(sortino, 4),
            "calmar": round(calmar, 4) if not np.isnan(calmar) else None,
            "mdd_pct": round(mdd, 3),
            "worst_month_pct": round(worst_month, 3),
            "best_month_pct": round(best_month, 3),
            "avg_turnover_annual_pct": round(avg_turnover, 3),
            "tc_annual_pct": round(tc_annual, 4),
            "days_in_deep_dd_pct": round(pct_in_deep_dd, 2),
            "crra_ce": crra_results,
            "bull_year_count": int(len(bull_years)),
            "bull_avg_ret_bh100_pct": round(bull_ret_bh, 3) if not np.isnan(bull_ret_bh) else None,
            "bull_avg_ret_strat_pct": round(bull_ret_strat, 3) if not np.isnan(bull_ret_strat) else None,
            "bull_drag_pct": round(bull_drag, 3) if not np.isnan(bull_drag) else None,
        }

        print(f"\n  {sname:12s}: CAGR={cagr:6.2f}%, Vol={ann_vol:5.2f}%, "
              f"Sharpe={sharpe:.3f}, MDD={mdd:.1f}%, Worst Mo={worst_month:.1f}%")

    # ================================================================
    # Cost-Benefit Analysis (relative to BH 50/50)
    # ================================================================
    print(f"\n  --- Cost-Benefit vs BH 50/50 ---")
    cost_benefit = {}
    bh5050 = results["BH_5050"]

    for sname in ["12/VIX", "EWMA_VT"]:
        s = results[sname]

        # Costs
        return_drag = bh5050["cagr_pct"] - s["cagr_pct"]  # positive = VT costs return
        tc_cost = s["tc_annual_pct"]

        # Benefits
        mdd_reduction = bh5050["mdd_pct"] - s["mdd_pct"]  # positive = VT improves (less negative)
        mdd_reduction_ratio = s["mdd_pct"] / bh5050["mdd_pct"] if bh5050["mdd_pct"] != 0 else np.nan
        worst_month_improvement = bh5050["worst_month_pct"] - s["worst_month_pct"]  # positive = VT improves
        dd_time_reduction = bh5050["days_in_deep_dd_pct"] - s["days_in_deep_dd_pct"]

        # Cost per unit MDD reduction
        if abs(mdd_reduction) > 0.1:
            cost_per_mdd_pct = return_drag / abs(mdd_reduction)  # % return per % MDD reduction
        else:
            cost_per_mdd_pct = np.nan

        # Break-even gamma: find gamma where VT CE > BH 50/50 CE
        breakeven_gamma = None
        for g in GAMMAS:
            ce_vt = s["crra_ce"].get(f"gamma_{g}")
            ce_bh = bh5050["crra_ce"].get(f"gamma_{g}")
            if ce_vt is not None and ce_bh is not None:
                if ce_vt > ce_bh:
                    breakeven_gamma = g
                    break

        cb = {
            "return_drag_pct": round(return_drag, 3),
            "tc_annual_pct": round(tc_cost, 4),
            "total_annual_cost_pct": round(return_drag + tc_cost, 3),
            "mdd_reduction_pp": round(mdd_reduction, 3),
            "mdd_reduction_ratio": round(mdd_reduction_ratio, 4) if not np.isnan(mdd_reduction_ratio) else None,
            "worst_month_improvement_pp": round(worst_month_improvement, 3),
            "dd_time_reduction_pp": round(dd_time_reduction, 2),
            "cost_per_pct_mdd_reduction": round(cost_per_mdd_pct, 4) if not np.isnan(cost_per_mdd_pct) else None,
            "breakeven_gamma": breakeven_gamma,
        }
        cost_benefit[sname] = cb

        print(f"\n  {sname}:")
        print(f"    Return drag vs BH 50/50: {return_drag:+.2f}%/yr")
        print(f"    TX cost: {tc_cost:.3f}%/yr")
        print(f"    MDD reduction: {mdd_reduction:+.1f}pp ({mdd_reduction_ratio:.2f}x)")
        print(f"    Worst-month improvement: {worst_month_improvement:+.1f}pp")
        print(f"    Cost per 1pp MDD reduction: {cost_per_mdd_pct:.3f}%/yr" if not np.isnan(cost_per_mdd_pct) else "    Cost per 1pp MDD reduction: N/A")
        print(f"    Break-even gamma: {breakeven_gamma}")

    # Also compare BH 100% vs BH 50/50 (diversification cost-benefit)
    bh100 = results["BH_100"]
    div_drag = bh100["cagr_pct"] - bh5050["cagr_pct"]
    div_mdd_reduction = bh100["mdd_pct"] - bh5050["mdd_pct"]
    div_cost_per_mdd = div_drag / abs(div_mdd_reduction) if abs(div_mdd_reduction) > 0.1 else np.nan

    div_breakeven = None
    for g in GAMMAS:
        ce_div = bh5050["crra_ce"].get(f"gamma_{g}")
        ce_100 = bh100["crra_ce"].get(f"gamma_{g}")
        if ce_div is not None and ce_100 is not None:
            if ce_div > ce_100:
                div_breakeven = g
                break

    cost_benefit["diversification_5050"] = {
        "return_drag_pct": round(div_drag, 3),
        "mdd_reduction_pp": round(div_mdd_reduction, 3),
        "cost_per_pct_mdd_reduction": round(div_cost_per_mdd, 4) if not np.isnan(div_cost_per_mdd) else None,
        "breakeven_gamma": div_breakeven,
    }

    print(f"\n  Diversification (BH 50/50 vs BH 100%):")
    print(f"    Return drag: {div_drag:+.2f}%/yr")
    print(f"    MDD reduction: {div_mdd_reduction:+.1f}pp")
    if not np.isnan(div_cost_per_mdd):
        print(f"    Cost per 1pp MDD reduction: {div_cost_per_mdd:.3f}%/yr")
    print(f"    Break-even gamma: {div_breakeven}")

    return {
        "asset": asset_name,
        "eval_days": int(len(data)),
        "eval_start": str(data.index[0].date()),
        "eval_end": str(data.index[-1].date()),
        "strategies": results,
        "cost_benefit": cost_benefit,
    }


# ============================================================================
# Cross-Asset Summary
# ============================================================================
def cross_asset_summary(all_results):
    """Create a summary table across all assets."""
    print("\n" + "=" * 70)
    print("  CROSS-ASSET SUMMARY: INSURANCE COST-BENEFIT")
    print("=" * 70)

    summary = {}

    # --- Table 1: Return Drag (cost of insurance) ---
    print("\n  Table 1: Annual Return Drag vs BH 50/50 (pp/yr)")
    print(f"  {'Asset':10s} | {'12/VIX':>10s} | {'EWMA VT':>10s} | {'Diversif.':>10s}")
    print("  " + "-" * 50)

    drags_12vix = []
    drags_ewma = []
    drags_div = []

    for asset_name, res in all_results.items():
        if res is None:
            continue
        cb = res["cost_benefit"]
        d12 = cb.get("12/VIX", {}).get("return_drag_pct", np.nan)
        dew = cb.get("EWMA_VT", {}).get("return_drag_pct", np.nan)
        ddiv = cb.get("diversification_5050", {}).get("return_drag_pct", np.nan)
        print(f"  {asset_name:10s} | {d12:+10.2f} | {dew:+10.2f} | {ddiv:+10.2f}")
        if not np.isnan(d12): drags_12vix.append(d12)
        if not np.isnan(dew): drags_ewma.append(dew)
        if not np.isnan(ddiv): drags_div.append(ddiv)

    if drags_12vix:
        print(f"  {'AVERAGE':10s} | {np.mean(drags_12vix):+10.2f} | {np.mean(drags_ewma):+10.2f} | {np.mean(drags_div):+10.2f}")

    # --- Table 2: MDD Reduction (benefit of insurance) ---
    print("\n  Table 2: MDD Reduction vs BH 50/50 (pp, positive = improvement)")
    print(f"  {'Asset':10s} | {'12/VIX':>10s} | {'EWMA VT':>10s} | {'Diversif.':>10s}")
    print("  " + "-" * 50)

    for asset_name, res in all_results.items():
        if res is None:
            continue
        cb = res["cost_benefit"]
        m12 = cb.get("12/VIX", {}).get("mdd_reduction_pp", np.nan)
        mew = cb.get("EWMA_VT", {}).get("mdd_reduction_pp", np.nan)
        mdiv = cb.get("diversification_5050", {}).get("mdd_reduction_pp", np.nan)
        print(f"  {asset_name:10s} | {m12:+10.1f} | {mew:+10.1f} | {mdiv:+10.1f}")

    # --- Table 3: Cost per 1pp MDD Reduction ---
    print("\n  Table 3: Cost per 1pp MDD Reduction (%/yr per pp)")
    print(f"  {'Asset':10s} | {'12/VIX':>10s} | {'EWMA VT':>10s} | {'Diversif.':>10s}")
    print("  " + "-" * 50)

    costs_12vix = []
    costs_ewma = []
    costs_div = []

    for asset_name, res in all_results.items():
        if res is None:
            continue
        cb = res["cost_benefit"]
        c12 = cb.get("12/VIX", {}).get("cost_per_pct_mdd_reduction")
        cew = cb.get("EWMA_VT", {}).get("cost_per_pct_mdd_reduction")
        cdiv = cb.get("diversification_5050", {}).get("cost_per_pct_mdd_reduction")

        c12_str = f"{c12:10.3f}" if c12 is not None else f"{'N/A':>10s}"
        cew_str = f"{cew:10.3f}" if cew is not None else f"{'N/A':>10s}"
        cdiv_str = f"{cdiv:10.3f}" if cdiv is not None else f"{'N/A':>10s}"
        print(f"  {asset_name:10s} | {c12_str} | {cew_str} | {cdiv_str}")
        if c12 is not None: costs_12vix.append(c12)
        if cew is not None: costs_ewma.append(cew)
        if cdiv is not None: costs_div.append(cdiv)

    if costs_12vix:
        print(f"  {'AVERAGE':10s} | {np.mean(costs_12vix):10.3f} | {np.mean(costs_ewma):10.3f} | {np.mean(costs_div):10.3f}")

    # --- Table 4: Break-Even Gamma ---
    print("\n  Table 4: Break-Even Gamma (VT > BH 50/50 on CRRA utility)")
    print(f"  {'Asset':10s} | {'12/VIX':>10s} | {'EWMA VT':>10s} | {'Diversif.':>10s}")
    print("  " + "-" * 50)

    for asset_name, res in all_results.items():
        if res is None:
            continue
        cb = res["cost_benefit"]
        g12 = cb.get("12/VIX", {}).get("breakeven_gamma")
        gew = cb.get("EWMA_VT", {}).get("breakeven_gamma")
        gdiv = cb.get("diversification_5050", {}).get("breakeven_gamma")

        g12_str = f"{g12:>10d}" if g12 is not None else f"{'>20':>10s}"
        gew_str = f"{gew:>10d}" if gew is not None else f"{'>20':>10s}"
        gdiv_str = f"{gdiv:>10d}" if gdiv is not None else f"{'>20':>10s}"
        print(f"  {asset_name:10s} | {g12_str} | {gew_str} | {gdiv_str}")

    # --- Table 5: Bull Market Drag ---
    print("\n  Table 5: Bull Market Drag (avg return in BH100% >20% years)")
    print(f"  {'Asset':10s} | {'Bull Yrs':>8s} | {'BH100%':>10s} | {'12/VIX':>10s} | {'EWMA VT':>10s} | {'BH 50/50':>10s}")
    print("  " + "-" * 70)

    for asset_name, res in all_results.items():
        if res is None:
            continue
        strats = res["strategies"]
        bcount = strats["BH_100"].get("bull_year_count", 0)
        bh100_r = strats["BH_100"].get("bull_avg_ret_bh100_pct")
        vix12_r = strats["12/VIX"].get("bull_avg_ret_strat_pct")
        ewma_r = strats["EWMA_VT"].get("bull_avg_ret_strat_pct")
        bh5050_r = strats["BH_5050"].get("bull_avg_ret_strat_pct")

        bh100_s = f"{bh100_r:10.1f}" if bh100_r is not None else f"{'N/A':>10s}"
        vix12_s = f"{vix12_r:10.1f}" if vix12_r is not None else f"{'N/A':>10s}"
        ewma_s = f"{ewma_r:10.1f}" if ewma_r is not None else f"{'N/A':>10s}"
        bh5050_s = f"{bh5050_r:10.1f}" if bh5050_r is not None else f"{'N/A':>10s}"
        print(f"  {asset_name:10s} | {bcount:>8d} | {bh100_s} | {vix12_s} | {ewma_s} | {bh5050_s}")

    # --- Build cross-asset summary dict ---
    summary["avg_return_drag_12vix"] = round(np.mean(drags_12vix), 3) if drags_12vix else None
    summary["avg_return_drag_ewma"] = round(np.mean(drags_ewma), 3) if drags_ewma else None
    summary["avg_return_drag_diversification"] = round(np.mean(drags_div), 3) if drags_div else None
    summary["avg_cost_per_mdd_12vix"] = round(np.mean(costs_12vix), 4) if costs_12vix else None
    summary["avg_cost_per_mdd_ewma"] = round(np.mean(costs_ewma), 4) if costs_ewma else None
    summary["avg_cost_per_mdd_diversification"] = round(np.mean(costs_div), 4) if costs_div else None

    return summary


# ============================================================================
# Investor Decision Guide
# ============================================================================
def print_decision_guide(all_results, summary):
    """Print a practical decision guide for investors."""
    print("\n" + "=" * 70)
    print("  VT DECISION GUIDE FOR INVESTORS")
    print("=" * 70)

    # Compute median break-even gammas across assets
    be_12vix = []
    be_ewma = []
    for asset_name, res in all_results.items():
        if res is None:
            continue
        cb = res["cost_benefit"]
        g12 = cb.get("12/VIX", {}).get("breakeven_gamma")
        gew = cb.get("EWMA_VT", {}).get("breakeven_gamma")
        if g12 is not None:
            be_12vix.append(g12)
        if gew is not None:
            be_ewma.append(gew)

    med_g12 = int(np.median(be_12vix)) if be_12vix else None
    med_gew = int(np.median(be_ewma)) if be_ewma else None

    print(f"\n  KEY FINDINGS:")
    print(f"  1. Average annual return drag: 12/VIX = {summary.get('avg_return_drag_12vix', 'N/A')}%, "
          f"EWMA = {summary.get('avg_return_drag_ewma', 'N/A')}%")
    print(f"  2. Average cost per 1pp MDD reduction: 12/VIX = {summary.get('avg_cost_per_mdd_12vix', 'N/A')}, "
          f"EWMA = {summary.get('avg_cost_per_mdd_ewma', 'N/A')}")
    print(f"  3. Median break-even gamma: 12/VIX = {med_g12}, EWMA = {med_gew}")

    print(f"\n  INVESTOR TYPE RECOMMENDATIONS:")
    print(f"  - Risk Tolerance HIGH (gamma < 2):  BH 100% equity (no insurance needed)")
    print(f"  - Risk Tolerance MODERATE (gamma 2-5): BH 50/50 diversification (cheapest insurance)")
    print(f"  - Risk Tolerance LOW (gamma 5-10):   12/VIX VT on 50/50 (active insurance)")
    print(f"  - Risk Tolerance VERY LOW (gamma >10): EWMA VT on 50/50 (maximum protection)")

    guide = {
        "median_breakeven_gamma_12vix": med_g12,
        "median_breakeven_gamma_ewma": med_gew,
        "recommendations": {
            "high_risk_tolerance": "BH 100% equity — no insurance needed, gamma < 2",
            "moderate_risk_tolerance": "BH 50/50 diversification — cheapest insurance, gamma 2-5",
            "low_risk_tolerance": "12/VIX VT on 50/50 — active insurance, gamma 5-10",
            "very_low_risk_tolerance": "EWMA VT on 50/50 — maximum protection, gamma > 10",
        },
    }
    return guide


# ============================================================================
# Main
# ============================================================================
def main():
    start_time = datetime.now()

    # Download data
    asset_data, vix_close, gld_ret = download_all_data()

    # Run analysis for each asset
    all_results = {}
    for asset_name, asset_ret in asset_data.items():
        result = run_single_asset(asset_name, asset_ret, vix_close, gld_ret)
        all_results[asset_name] = result

    # Cross-asset summary
    summary = cross_asset_summary(all_results)

    # Decision guide
    guide = print_decision_guide(all_results, summary)

    # ================================================================
    # Save results
    # ================================================================
    elapsed = (datetime.now() - start_time).total_seconds()

    output = {
        "experiment_id": "K738",
        "title": "VT Insurance Cost-Benefit Analysis",
        "description": "Comprehensive cost-benefit analysis of Volatility Targeting across 5 assets",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance",
        "period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "type": "empirical_analysis",
        "proposer": "Claude",
        "executor": "Claude",
        "references": [
            "K687: Post-correction definitive ranking",
            "K688: CRRA lag-corrected",
            "K697: VIX predicts vol not direction",
            "K41: VT insurance premium ~4%/yr",
            "Moreira & Muir (2017), Volatility-Managed Portfolios, JF",
            "Arrow (1965), Aspects of the Theory of Risk-Bearing",
            "Copeland & Copeland (1999), Market Timing with VIX",
        ],
        "configuration": {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "eval_start": EVAL_START,
            "ewma_lambda": EWMA_LAMBDA,
            "target_vol": TARGET_VOL,
            "vix_12_cap": VIX_12_CAP,
            "tc_bps": TC_BPS,
            "rf_annual": RF_ANNUAL,
            "gammas": GAMMAS,
            "bull_threshold": BULL_THRESHOLD,
            "assets": list(ASSETS.keys()),
        },
        "per_asset_results": {},
        "cross_asset_summary": summary,
        "decision_guide": guide,
        "runtime_seconds": round(elapsed, 1),
    }

    # Add per-asset results
    for asset_name, res in all_results.items():
        if res is not None:
            output["per_asset_results"][asset_name] = res

    # Generate conclusions
    conclusions = []

    # 1. Average insurance cost
    avg_drag_12 = summary.get("avg_return_drag_12vix")
    avg_drag_ew = summary.get("avg_return_drag_ewma")
    if avg_drag_12 is not None:
        conclusions.append(
            f"12/VIX costs {avg_drag_12:+.2f}%/yr return drag (avg across {len([r for r in all_results.values() if r is not None])} assets)"
        )
    if avg_drag_ew is not None:
        conclusions.append(
            f"EWMA VT costs {avg_drag_ew:+.2f}%/yr return drag (avg across assets)"
        )

    # 2. Cost-efficiency
    avg_cpm_12 = summary.get("avg_cost_per_mdd_12vix")
    avg_cpm_ew = summary.get("avg_cost_per_mdd_ewma")
    if avg_cpm_12 is not None and avg_cpm_ew is not None:
        better = "12/VIX" if abs(avg_cpm_12) < abs(avg_cpm_ew) else "EWMA VT"
        conclusions.append(
            f"Cost per 1pp MDD reduction: 12/VIX={avg_cpm_12:.3f}, EWMA={avg_cpm_ew:.3f} → {better} more cost-efficient"
        )

    # 3. Break-even gamma
    med_g12 = guide.get("median_breakeven_gamma_12vix")
    med_gew = guide.get("median_breakeven_gamma_ewma")
    if med_g12 is not None:
        conclusions.append(
            f"Break-even gamma: 12/VIX={med_g12}, EWMA={med_gew} — investors with gamma>={min(med_g12 or 99, med_gew or 99)} should use VT"
        )

    # 4. Diversification as cheapest insurance
    avg_div_drag = summary.get("avg_return_drag_diversification")
    avg_div_cpm = summary.get("avg_cost_per_mdd_diversification")
    if avg_div_drag is not None:
        conclusions.append(
            f"Simple 50/50 diversification: {avg_div_drag:+.2f}%/yr drag, cost per 1pp MDD = {avg_div_cpm:.3f} — cheapest form of insurance"
        )

    output["conclusions"] = conclusions

    # Save
    results_path = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k738_vt_insurance_cost_benefit_results.json")
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print(f"  CONCLUSIONS:")
    print(f"{'='*70}")
    for i, c in enumerate(conclusions, 1):
        print(f"  {i}. {c}")

    print(f"\n  Runtime: {elapsed:.1f}s")
    print(f"  Results saved to: {results_path}")
    print(f"\nDone.")


if __name__ == "__main__":
    main()
