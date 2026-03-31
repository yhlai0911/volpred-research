"""K738v2: VT Insurance Cost-Benefit Analysis — CLEAN 0050.TW Data
=====================================================================
Reruns K738 for 0050.TW ONLY with split-artifact-corrected data.

Problem in K738:
  - 0050.TW yfinance data has a split artifact at 2014-01-02
  - Pre-2014 prices are ~4x too high (split not retroactively applied before that date)
  - K738 used a crude filter (|r| > 30%) which masks the artifact but loses information
  - This contaminates MDD, CAGR, Sharpe, and CRRA break-even gamma

Fix:
  - Uses `from volpred.utils import clean_tw50_data` to properly fix the split discontinuity
  - Pre-2014 prices divided by 4 to create continuous price series
  - Returns recomputed from clean prices

Key question: "Did the 0050.TW conclusions change?"
  - Break-even gamma for 12/VIX (was 3.6) and EWMA VT (was 7.6)
  - Insurance cost (return drag was 1.70% for 12/VIX, 2.63% for EWMA)
  - MDD reduction (was +5.1pp for 12/VIX, -3.0pp for EWMA)

SPY/GLD/QQQ/EEM results are unchanged — only 0050.TW is rerun.

Data source: yfinance (0050.TW, ^VIX, GLD) with split correction
Period: 2006-01-01 to 2026-03-31
Type: Empirical analysis (real data, split-corrected)

[提出: User (split artifact fix), 執行: Claude]
Author: VolPred Research System
Date: 2026-03-31
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats

# CRITICAL FIX: use clean_tw50_data to fix split artifact
from volpred.utils import clean_tw50_data, download_tw50_clean

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration (same as K738)
# ============================================================================
START_DATE = "2006-01-01"
END_DATE = "2026-03-31"
EVAL_START = "2007-01-03"
EWMA_LAMBDA = 0.94
TARGET_VOL = 0.10
VIX_12_CAP = 1.5
TC_BPS = 5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
GAMMAS = list(range(1, 31))
BULL_THRESHOLD = 0.20

RESULTS_DIR = Path("/Users/yhlai0911/Desktop/volpred-research/experiments")


# ============================================================================
# EWMA Volatility
# ============================================================================
def compute_ewma_vol(returns, lam=EWMA_LAMBDA):
    var = np.zeros(len(returns))
    var[0] = returns.iloc[0] ** 2 if len(returns) > 0 else 0.0001
    for i in range(1, len(returns)):
        var[i] = lam * var[i - 1] + (1 - lam) * returns.iloc[i] ** 2
    vol_daily = np.sqrt(var)
    vol_ann = vol_daily * np.sqrt(252)
    return pd.Series(vol_ann, index=returns.index, name="ewma_vol")


# ============================================================================
# CRRA Utility
# ============================================================================
def crra_utility(daily_returns, gamma):
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
    return ce_annual * 100


# ============================================================================
# Main
# ============================================================================
def main():
    start_time = datetime.now()

    print("=" * 70)
    print("K738v2: VT INSURANCE COST-BENEFIT — CLEAN 0050.TW DATA")
    print("=" * 70)
    print(f"Period: {START_DATE} to {END_DATE}")
    print(f"Evaluation from: {EVAL_START}")

    # ================================================================
    # Download data
    # ================================================================
    print("\nDownloading data...")

    # VIX
    vix_df = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)
    vix_close = vix_df["Close"].copy()
    vix_close.name = "vix"
    print(f"  VIX: {len(vix_df)} rows")

    # GLD
    gld_df = yf.download("GLD", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    if isinstance(gld_df.columns, pd.MultiIndex):
        gld_df.columns = gld_df.columns.get_level_values(0)
    gld_ret = gld_df["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"
    print(f"  GLD: {len(gld_df)} rows")

    # 0050.TW — CLEAN DATA (the whole point of this v2)
    tw50_df = download_tw50_clean(start=START_DATE, end=END_DATE)
    tw50_ret = tw50_df["Return"].dropna()
    tw50_ret.name = "0050.TW_ret"
    print(f"  0050.TW (CLEAN): {len(tw50_df)} rows")

    # Also download RAW 0050.TW for comparison
    raw_tw_df = yf.download("0050.TW", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    if isinstance(raw_tw_df.columns, pd.MultiIndex):
        raw_tw_df.columns = raw_tw_df.columns.get_level_values(0)
    raw_tw_ret = raw_tw_df["Close"].pct_change().dropna()
    # Apply same filter as K738 for fair comparison
    raw_tw_ret_filtered = raw_tw_ret[(raw_tw_ret > -0.30) & (raw_tw_ret < 0.30)]
    n_raw_filtered = len(raw_tw_ret) - len(raw_tw_ret_filtered)
    print(f"  0050.TW (RAW, K738 filter): {len(raw_tw_ret_filtered)} rows ({n_raw_filtered} filtered)")

    # Show the difference around the split date
    split_date = pd.Timestamp("2014-01-02")
    if split_date in tw50_df.index and split_date in raw_tw_df.index:
        print(f"\n  Split artifact check at {split_date.date()}:")
        pre_clean = tw50_df["Close"].loc[:split_date].iloc[-2] if len(tw50_df["Close"].loc[:split_date]) > 1 else None
        post_clean = tw50_df["Close"].loc[split_date]
        pre_raw = raw_tw_df["Close"].loc[:split_date].iloc[-2] if len(raw_tw_df["Close"].loc[:split_date]) > 1 else None
        post_raw = raw_tw_df["Close"].loc[split_date]
        if pre_clean is not None:
            print(f"    CLEAN: {float(pre_clean):.2f} -> {float(post_clean):.2f} (ratio: {float(pre_clean)/float(post_clean):.2f})")
        if pre_raw is not None:
            print(f"    RAW:   {float(pre_raw):.2f} -> {float(post_raw):.2f} (ratio: {float(pre_raw)/float(post_raw):.2f})")

    # ================================================================
    # Run analysis: 0050.TW with CLEAN data
    # ================================================================
    asset_name = "0050.TW"
    asset_ret = tw50_ret

    print(f"\n{'='*70}")
    print(f"  ASSET: {asset_name} (CLEAN split-corrected data)")
    print(f"{'='*70}")

    # Merge data
    data = pd.concat([asset_ret, gld_ret, vix_close], axis=1).dropna()
    data.columns = ["asset_ret", "gld_ret", "vix"]
    data["port_ret"] = 0.5 * data["asset_ret"] + 0.5 * data["gld_ret"]

    # 12/VIX signal (lagged)
    raw_12vix = np.minimum(12.0 / data["vix"], VIX_12_CAP)
    data["w_12vix"] = raw_12vix.shift(1)  # LAG: signal from t-1

    # EWMA VT signal (lagged)
    ewma_vol = compute_ewma_vol(data["port_ret"], lam=EWMA_LAMBDA)
    raw_ewma_w = np.minimum(TARGET_VOL / ewma_vol.clip(lower=0.01), 2.0)
    data["w_ewma"] = raw_ewma_w.shift(1)  # LAG: signal from t-1

    # Trim to evaluation period
    data = data.loc[EVAL_START:]
    data = data.dropna()

    print(f"  Evaluation: {len(data)} days, {data.index[0].date()} to {data.index[-1].date()}")

    # ================================================================
    # Strategy returns
    # ================================================================
    strategies = {}
    strategies["BH_100"] = data["asset_ret"].copy()
    strategies["BH_5050"] = data["port_ret"].copy()

    # 12/VIX
    w = data["w_12vix"]
    raw_ret = w * data["port_ret"] + (1 - w) * RF_DAILY
    dw = w.diff().abs()
    tc = dw * (TC_BPS / 10000)
    strategies["12/VIX"] = raw_ret - tc

    # EWMA VT
    w = data["w_ewma"]
    raw_ret = w * data["port_ret"] + (1 - w) * RF_DAILY
    dw = w.diff().abs()
    tc = dw * (TC_BPS / 10000)
    strategies["EWMA_VT"] = raw_ret - tc

    # ================================================================
    # Compute metrics
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

        monthly_rets = rets.resample("ME").apply(lambda x: (1 + x).prod() - 1)
        worst_month = monthly_rets.min() * 100
        best_month = monthly_rets.max() * 100

        if sname in ["12/VIX", "EWMA_VT"]:
            ws = data["w_12vix"] if sname == "12/VIX" else data["w_ewma"]
            avg_turnover = ws.diff().abs().mean() * 252 * 100
            total_tc = (ws.diff().abs() * (TC_BPS / 10000)).sum() * 100
            tc_annual = total_tc / years
        else:
            avg_turnover = 0.0
            tc_annual = 0.0

        downside = rets[rets < 0]
        downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-6
        sortino = (rets.mean() * 252 - RF_ANNUAL) / downside_vol
        calmar = cagr / abs(mdd) if abs(mdd) > 0.01 else np.nan

        days_in_deep_dd = (drawdown < -0.05).sum()
        pct_in_deep_dd = days_in_deep_dd / n * 100

        crra_results = {}
        for g in GAMMAS:
            ce = crra_utility(rets, g)
            crra_results[f"gamma_{g}"] = round(ce, 3) if not np.isnan(ce) else None

        yearly_bh = strategies["BH_100"].resample("YE").apply(lambda x: (1 + x).prod() - 1)
        yearly_strat = rets.resample("YE").apply(lambda x: (1 + x).prod() - 1)
        bull_years = yearly_bh[yearly_bh > BULL_THRESHOLD].index
        if len(bull_years) > 0:
            bull_ret_bh = yearly_bh.loc[bull_years].mean() * 100
            matching_bull = yearly_strat.reindex(bull_years)
            bull_ret_strat = matching_bull.mean() * 100
            bull_drag = bull_ret_strat - bull_ret_bh
        else:
            bull_ret_bh = bull_ret_strat = bull_drag = np.nan

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
    # Cost-Benefit vs BH 50/50
    # ================================================================
    print(f"\n  --- Cost-Benefit vs BH 50/50 ---")
    cost_benefit = {}
    bh5050 = results["BH_5050"]

    for sname in ["12/VIX", "EWMA_VT"]:
        s = results[sname]
        return_drag = bh5050["cagr_pct"] - s["cagr_pct"]
        tc_cost = s["tc_annual_pct"]
        mdd_reduction = s["mdd_pct"] - bh5050["mdd_pct"]
        mdd_reduction_ratio = s["mdd_pct"] / bh5050["mdd_pct"] if bh5050["mdd_pct"] != 0 else np.nan
        worst_month_improvement = s["worst_month_pct"] - bh5050["worst_month_pct"]
        dd_time_reduction = bh5050["days_in_deep_dd_pct"] - s["days_in_deep_dd_pct"]

        if abs(mdd_reduction) > 0.1:
            cost_per_mdd_pct = return_drag / abs(mdd_reduction)
        else:
            cost_per_mdd_pct = np.nan

        # Break-even gamma
        breakeven_gamma = None
        ce_diffs = []
        for g in GAMMAS:
            ce_vt = s["crra_ce"].get(f"gamma_{g}")
            ce_bh = bh5050["crra_ce"].get(f"gamma_{g}")
            if ce_vt is not None and ce_bh is not None:
                ce_diffs.append((g, ce_vt - ce_bh))

        for i in range(1, len(ce_diffs)):
            g_prev, d_prev = ce_diffs[i - 1]
            g_curr, d_curr = ce_diffs[i]
            if d_prev <= 0 < d_curr:
                frac = -d_prev / (d_curr - d_prev) if (d_curr - d_prev) != 0 else 0
                breakeven_gamma = round(g_prev + frac * (g_curr - g_prev), 1)
                break

        if len(ce_diffs) >= 3:
            diffs_only = [d for _, d in ce_diffs]
            increasing_count = sum(1 for i in range(1, len(diffs_only)) if diffs_only[i] > diffs_only[i-1])
            monotonicity_ratio = increasing_count / (len(diffs_only) - 1) if len(diffs_only) > 1 else 0
            if monotonicity_ratio < 0.6 and breakeven_gamma is not None:
                breakeven_gamma = None

        cb = {
            "return_drag_pct": round(return_drag, 3),
            "tc_annual_pct": round(tc_cost, 4),
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
        print(f"    MDD reduction: {mdd_reduction:+.1f}pp ({mdd_reduction_ratio:.2f}x)")
        print(f"    Break-even gamma: {breakeven_gamma}")

    # Diversification cost-benefit
    bh100 = results["BH_100"]
    div_drag = bh100["cagr_pct"] - bh5050["cagr_pct"]
    div_mdd_reduction = bh5050["mdd_pct"] - bh100["mdd_pct"]
    div_cost_per_mdd = div_drag / abs(div_mdd_reduction) if abs(div_mdd_reduction) > 0.1 else np.nan

    div_breakeven = None
    div_ce_diffs = []
    for g in GAMMAS:
        ce_div = bh5050["crra_ce"].get(f"gamma_{g}")
        ce_100 = bh100["crra_ce"].get(f"gamma_{g}")
        if ce_div is not None and ce_100 is not None:
            div_ce_diffs.append((g, ce_div - ce_100))

    for i in range(1, len(div_ce_diffs)):
        g_prev, d_prev = div_ce_diffs[i - 1]
        g_curr, d_curr = div_ce_diffs[i]
        if d_prev <= 0 < d_curr:
            frac = -d_prev / (d_curr - d_prev) if (d_curr - d_prev) != 0 else 0
            div_breakeven = round(g_prev + frac * (g_curr - g_prev), 1)
            break

    cost_benefit["diversification_5050"] = {
        "return_drag_pct": round(div_drag, 3),
        "mdd_reduction_pp": round(div_mdd_reduction, 3),
        "cost_per_pct_mdd_reduction": round(div_cost_per_mdd, 4) if not np.isnan(div_cost_per_mdd) else None,
        "breakeven_gamma": div_breakeven,
    }

    # ================================================================
    # Compare with K738 original results
    # ================================================================
    print(f"\n{'='*70}")
    print("  COMPARISON: K738 (raw data) vs K738v2 (clean data)")
    print(f"{'='*70}")

    k738_path = RESULTS_DIR / "k738_vt_insurance_cost_benefit_results.json"
    comparison = {}
    try:
        with open(k738_path) as f:
            k738 = json.load(f)
        k738_tw = k738.get("per_asset_results", {}).get("0050.TW", {})

        if k738_tw:
            k738_strats = k738_tw.get("strategies", {})
            k738_cb = k738_tw.get("cost_benefit", {})

            print(f"\n  {'Metric':<30s} | {'K738 (raw)':>12s} | {'K738v2 (clean)':>14s} | {'Delta':>10s}")
            print("  " + "-" * 75)

            comparisons = []
            for sname in ["BH_100", "BH_5050", "12/VIX", "EWMA_VT"]:
                old = k738_strats.get(sname, {})
                new = results.get(sname, {})
                for metric in ["cagr_pct", "sharpe", "mdd_pct"]:
                    old_val = old.get(metric)
                    new_val = new.get(metric)
                    if old_val is not None and new_val is not None:
                        delta = new_val - old_val
                        label = f"{sname} {metric}"
                        print(f"  {label:<30s} | {old_val:>12.3f} | {new_val:>14.3f} | {delta:>+10.3f}")
                        comparisons.append({
                            "metric": label,
                            "k738_raw": old_val,
                            "k738v2_clean": new_val,
                            "delta": round(delta, 3),
                        })

            # Cost-benefit comparison
            print(f"\n  {'Cost-Benefit':<30s} | {'K738 (raw)':>12s} | {'K738v2 (clean)':>14s} | {'Delta':>10s}")
            print("  " + "-" * 75)
            for sname in ["12/VIX", "EWMA_VT"]:
                old_cb = k738_cb.get(sname, {})
                new_cb = cost_benefit.get(sname, {})
                for metric in ["return_drag_pct", "mdd_reduction_pp", "breakeven_gamma"]:
                    old_val = old_cb.get(metric)
                    new_val = new_cb.get(metric)
                    if old_val is not None and new_val is not None:
                        delta = new_val - old_val
                        label = f"{sname} {metric}"
                        print(f"  {label:<30s} | {old_val:>12.3f} | {new_val:>14.3f} | {delta:>+10.3f}")
                        comparisons.append({
                            "metric": label,
                            "k738_raw": old_val,
                            "k738v2_clean": new_val,
                            "delta": round(delta, 3),
                        })
                    elif old_val is not None or new_val is not None:
                        label = f"{sname} {metric}"
                        print(f"  {label:<30s} | {str(old_val):>12s} | {str(new_val):>14s} | {'N/A':>10s}")

            comparison["comparisons"] = comparisons

            # Did conclusions change?
            old_be_12vix = k738_cb.get("12/VIX", {}).get("breakeven_gamma")
            new_be_12vix = cost_benefit.get("12/VIX", {}).get("breakeven_gamma")
            old_be_ewma = k738_cb.get("EWMA_VT", {}).get("breakeven_gamma")
            new_be_ewma = cost_benefit.get("EWMA_VT", {}).get("breakeven_gamma")

            gamma_changed_12vix = old_be_12vix != new_be_12vix
            gamma_changed_ewma = old_be_ewma != new_be_ewma

            print(f"\n  CONCLUSION CHANGES:")
            print(f"    12/VIX break-even gamma: {old_be_12vix} → {new_be_12vix} {'*** CHANGED ***' if gamma_changed_12vix else '(same)'}")
            print(f"    EWMA VT break-even gamma: {old_be_ewma} → {new_be_ewma} {'*** CHANGED ***' if gamma_changed_ewma else '(same)'}")

            comparison["gamma_12vix_old"] = old_be_12vix
            comparison["gamma_12vix_new"] = new_be_12vix
            comparison["gamma_12vix_changed"] = gamma_changed_12vix
            comparison["gamma_ewma_old"] = old_be_ewma
            comparison["gamma_ewma_new"] = new_be_ewma
            comparison["gamma_ewma_changed"] = gamma_changed_ewma

    except FileNotFoundError:
        print("  K738 results not found — skipping comparison")
        comparison["error"] = "K738 results not found"

    # ================================================================
    # Save results
    # ================================================================
    elapsed = (datetime.now() - start_time).total_seconds()

    output = {
        "experiment_id": "K738v2",
        "title": "VT Insurance Cost-Benefit — CLEAN 0050.TW Data (Split Fix)",
        "description": "Rerun of K738 for 0050.TW only, using clean_tw50_data to fix split artifact at 2014-01-02",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance + clean_tw50_data (volpred.utils)",
        "period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "type": "empirical_analysis",
        "proposer": "User (split artifact fix)",
        "executor": "Claude",
        "fix_applied": "Pre-2014 0050.TW prices divided by 4 (split ratio) to remove discontinuity",
        "original_experiment": "K738",
        "references": [
            "K738: Original VT insurance cost-benefit (raw 0050.TW data, |r|>30% filter)",
            "K687: Post-correction definitive ranking",
            "K688: CRRA lag-corrected",
            "Moreira & Muir (2017), Volatility-Managed Portfolios, JF",
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
        },
        "tw50_clean_results": {
            "asset": "0050.TW",
            "eval_days": int(len(data)),
            "eval_start": str(data.index[0].date()),
            "eval_end": str(data.index[-1].date()),
            "strategies": results,
            "cost_benefit": cost_benefit,
        },
        "comparison_k738_vs_k738v2": comparison,
        "runtime_seconds": round(elapsed, 1),
    }

    # Conclusions
    conclusions = []
    if comparison.get("gamma_12vix_changed"):
        conclusions.append(
            f"12/VIX break-even gamma CHANGED: {comparison['gamma_12vix_old']} → {comparison['gamma_12vix_new']}"
        )
    else:
        conclusions.append(
            f"12/VIX break-even gamma UNCHANGED at {comparison.get('gamma_12vix_new', 'N/A')}"
        )

    if comparison.get("gamma_ewma_changed"):
        conclusions.append(
            f"EWMA VT break-even gamma CHANGED: {comparison['gamma_ewma_old']} → {comparison['gamma_ewma_new']}"
        )
    else:
        conclusions.append(
            f"EWMA VT break-even gamma UNCHANGED at {comparison.get('gamma_ewma_new', 'N/A')}"
        )

    # Check if core conclusion survives
    drag_12vix = cost_benefit.get("12/VIX", {}).get("return_drag_pct", 0)
    mdd_red_12vix = cost_benefit.get("12/VIX", {}).get("mdd_reduction_pp", 0)
    conclusions.append(
        f"12/VIX insurance cost: {drag_12vix:+.2f}%/yr return drag for {mdd_red_12vix:+.1f}pp MDD reduction"
    )
    conclusions.append(
        f"Core finding: VT is drawdown insurance (not alpha generator) — {'CONFIRMED' if drag_12vix > 0 else 'CHALLENGED'} with clean data"
    )

    output["conclusions"] = conclusions

    # Save
    results_path = RESULTS_DIR / "k738v2_vt_insurance_clean_tw50_results.json"
    with open(results_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    print(f"\n{'='*70}")
    print(f"  CONCLUSIONS:")
    print(f"{'='*70}")
    for i, c in enumerate(conclusions, 1):
        print(f"  {i}. {c}")

    print(f"\n  Runtime: {elapsed:.1f}s")
    print(f"  Results saved to: {results_path}")


if __name__ == "__main__":
    main()
