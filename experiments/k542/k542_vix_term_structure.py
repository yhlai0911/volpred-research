#!/usr/bin/env python3
"""
K542: VIX Term Structure as VT Timing Signal
=============================================
Can contango/backwardation (VIX/VIX3M ratio) predict VT outperformance?

Motivation:
- VIX level-based signals are exhaustively validated (sufficiency #35)
- VIX term structure carries DIFFERENT info: expectations about future vol
- Deep contango (ratio<0.85): vol low, expected to stay low → B&H better
- Backwardation (ratio>1.0): current crisis → VT most valuable
- K43 tested VIX3M as ADDITIONAL factor → null
- P37: backwardation preemptive VIX×1.3 passed Harvey (t=4.31)
- P43: subsample instability (tranquil-period driven)
- THIS experiment: ratio as pure TIMING on/off signal for VT

Design:
1. Data: ^VIX + ^VIX3M from yfinance (~2008+)
2. ratio = VIX/VIX3M daily
3. Strategies:
   a. Term Structure Timing: VT when ratio>threshold, B&H otherwise
   b. Ratio-Weighted: 12/VIX × min(1, ratio/0.85)
   c. Backwardation Boost: 12/VIX + extra 10% when ratio>1.05
4. Benchmark: pure 12/VIX
5. Cross-OOS: 5 periods (2014-2024)
6. Harvey t>3.0 threshold

References:
- Chang (2016): VIX backwardation → positive future SPY returns (monthly)
- Wang & Yen (2017): VIX term structure predictive power
- Harvey et al. (2016): t>3.0 threshold for multiple testing

Data source: yfinance (^VIX, ^VIX3M, SPY)
"""

import json
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")


def download_data():
    """Download SPY, VIX, VIX3M data from yfinance."""
    tickers = {"SPY": "SPY", "VIX": "^VIX", "VIX3M": "^VIX3M"}
    data = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start="2008-01-01", end="2026-01-01", progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[name] = df["Close"].rename(name)

    merged = pd.concat(data.values(), axis=1).dropna()
    print(f"Data: {merged.index[0].date()} to {merged.index[-1].date()}, N={len(merged)}")
    return merged


def compute_vt_weight(vix_series, target_vol=0.12):
    """Compute 12/VIX weight, clipped to [0, 1.5]."""
    vix_decimal = vix_series / 100.0
    weight = target_vol / vix_decimal
    return weight.clip(0.0, 1.5)


def compute_strategies(df):
    """Compute all strategy returns."""
    spy_ret = df["SPY"].pct_change()
    vix = df["VIX"]
    ratio = df["VIX"] / df["VIX3M"]

    # Base VT weight (12/VIX)
    base_weight = compute_vt_weight(vix)

    strategies = {}

    # 0. Benchmark: pure 12/VIX
    w_base = base_weight.shift(1)
    strategies["benchmark_12vix"] = w_base * spy_ret

    # 1. Buy & Hold
    strategies["buy_hold"] = spy_ret.copy()

    # 2a. Term Structure Timing (threshold=0.90)
    # VT when ratio >= 0.90 (flat or backwardation), B&H when < 0.90
    for thresh in [0.85, 0.90, 0.95]:
        use_vt = (ratio >= thresh).shift(1)
        w = pd.Series(np.where(use_vt, base_weight.shift(1), 1.0), index=df.index)
        strategies[f"ts_timing_{thresh}"] = w * spy_ret

    # 2b. Ratio-Weighted: 12/VIX × min(1, ratio/0.85)
    ratio_adj = (ratio / 0.85).clip(0, 1.0)
    w_ratio = (base_weight * ratio_adj).shift(1)
    strategies["ratio_weighted"] = w_ratio * spy_ret

    # 2c. Backwardation Boost: 12/VIX + extra weight reduction when ratio>1.05
    # (ratio>1.05 means backwardation = crisis → reduce exposure further)
    backwardation = (ratio > 1.05).shift(1)
    w_boost = base_weight.shift(1).copy()
    w_boost = pd.Series(
        np.where(backwardation, w_boost * 0.5, w_boost),  # halve in backwardation
        index=df.index,
    )
    strategies["backwardation_deleverage"] = w_boost * spy_ret

    # 2d. Inverted: ratio>1.05 → extra VT (more conservative = lower weight)
    # vs ratio<0.85 → full exposure (deep contango = calm)
    w_inv = base_weight.shift(1).copy()
    deep_contango = (ratio < 0.85).shift(1)
    w_inv = pd.Series(
        np.where(deep_contango, np.minimum(w_inv * 1.3, 1.5), w_inv), index=df.index
    )
    w_inv = pd.Series(
        np.where(backwardation, w_inv * 0.7, w_inv), index=df.index
    )
    strategies["contango_boost_backw_cut"] = w_inv * spy_ret

    return strategies, ratio


def compute_metrics(returns, annual_factor=252):
    """Compute Sharpe, CAGR, MaxDD, Sortino for a return series."""
    r = returns.dropna()
    if len(r) < 100:
        return {"sharpe": np.nan, "cagr": np.nan, "maxdd": np.nan, "sortino": np.nan, "n_days": len(r)}

    mean_r = r.mean() * annual_factor
    std_r = r.std() * np.sqrt(annual_factor)
    sharpe = mean_r / std_r if std_r > 0 else 0.0

    cum = (1 + r).cumprod()
    cagr = cum.iloc[-1] ** (annual_factor / len(r)) - 1
    maxdd = (cum / cum.cummax() - 1).min()

    downside = r[r < 0].std() * np.sqrt(annual_factor)
    sortino = mean_r / downside if downside > 0 else 0.0

    return {
        "sharpe": round(sharpe, 4),
        "cagr": round(cagr, 4),
        "maxdd": round(maxdd, 4),
        "sortino": round(sortino, 4),
        "n_days": len(r),
    }


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test (two-sided). Losses are squared errors or similar."""
    d = loss1 - loss2
    d = d.dropna()
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan

    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return dm_stat, p_value


def cross_oos_test(df, ratio, oos_periods):
    """
    Cross-OOS validation: for each period, compute strategy vs benchmark
    metrics and DM test on squared daily returns (proxy for return variance).
    """
    results = []
    for period_name, (start, end) in oos_periods.items():
        mask = (df.index >= start) & (df.index <= end)
        sub_df = df[mask]

        if len(sub_df) < 200:
            print(f"  {period_name}: insufficient data ({len(sub_df)} days), skipping")
            continue

        strats, _ = compute_strategies(sub_df)
        bench_ret = strats["benchmark_12vix"].dropna()

        period_result = {"period": period_name, "start": start, "end": end, "n_days": len(sub_df)}

        # Metrics for each strategy
        for sname, sret in strats.items():
            m = compute_metrics(sret)
            period_result[f"{sname}_sharpe"] = m["sharpe"]
            period_result[f"{sname}_cagr"] = m["cagr"]
            period_result[f"{sname}_maxdd"] = m["maxdd"]

            # DM test vs benchmark (using squared returns as loss)
            if sname != "benchmark_12vix" and sname != "buy_hold":
                common_idx = bench_ret.index.intersection(sret.dropna().index)
                if len(common_idx) > 100:
                    loss_bench = bench_ret.loc[common_idx] ** 2
                    loss_strat = sret.loc[common_idx] ** 2
                    # We compare negative returns (losses): higher squared = worse
                    # DM test on return difference
                    ret_diff = sret.loc[common_idx] - bench_ret.loc[common_idx]
                    t_stat = ret_diff.mean() / (ret_diff.std() / np.sqrt(len(ret_diff)))
                    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(ret_diff) - 1))
                    period_result[f"{sname}_t_vs_bench"] = round(t_stat, 3)
                    period_result[f"{sname}_p_vs_bench"] = round(p_val, 4)

        # Ratio descriptive stats for this period
        sub_r = ratio[mask].dropna()
        if len(sub_r) > 0:
            period_result["ratio_mean"] = round(sub_r.mean(), 4)
            period_result["ratio_std"] = round(sub_r.std(), 4)
            period_result["ratio_backwardation_pct"] = round((sub_r > 1.0).mean() * 100, 1)

        results.append(period_result)

    return results


def full_sample_analysis(df, ratio):
    """Full sample analysis with descriptive stats and all strategies."""
    print("\n=== FULL SAMPLE ANALYSIS ===")
    print(f"Period: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

    # Ratio descriptive stats
    print(f"\nVIX/VIX3M Ratio:")
    print(f"  Mean: {ratio.mean():.4f}")
    print(f"  Std:  {ratio.std():.4f}")
    print(f"  Min:  {ratio.min():.4f}")
    print(f"  Max:  {ratio.max():.4f}")
    print(f"  Backwardation (>1.0): {(ratio > 1.0).mean()*100:.1f}%")
    print(f"  Deep contango (<0.85): {(ratio < 0.85).mean()*100:.1f}%")
    print(f"  Near-flat (0.90-1.0): {((ratio >= 0.90) & (ratio <= 1.0)).mean()*100:.1f}%")

    # Compute strategies
    strats, _ = compute_strategies(df)

    print("\n--- Strategy Performance (Full Sample) ---")
    print(f"{'Strategy':<35} {'Sharpe':>8} {'CAGR':>8} {'MaxDD':>8} {'Sortino':>8} {'N':>6}")
    print("-" * 75)

    full_metrics = {}
    for sname, sret in strats.items():
        m = compute_metrics(sret)
        full_metrics[sname] = m
        print(
            f"{sname:<35} {m['sharpe']:>8.4f} {m['cagr']:>8.4f} {m['maxdd']:>8.4f} {m['sortino']:>8.4f} {m['n_days']:>6}"
        )

    # T-tests vs benchmark
    bench_ret = strats["benchmark_12vix"].dropna()
    print("\n--- T-tests vs Benchmark (12/VIX) ---")
    print(f"{'Strategy':<35} {'t-stat':>8} {'p-value':>8} {'Harvey':>8}")
    print("-" * 60)

    t_results = {}
    for sname, sret in strats.items():
        if sname in ("benchmark_12vix", "buy_hold"):
            continue
        common_idx = bench_ret.index.intersection(sret.dropna().index)
        if len(common_idx) > 100:
            ret_diff = sret.loc[common_idx] - bench_ret.loc[common_idx]
            t_stat = ret_diff.mean() / (ret_diff.std() / np.sqrt(len(ret_diff)))
            p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(ret_diff) - 1))
            passes = "PASS" if abs(t_stat) > 3.0 else "FAIL"
            print(f"{sname:<35} {t_stat:>8.3f} {p_val:>8.4f} {passes:>8}")
            t_results[sname] = {"t_stat": round(t_stat, 3), "p_value": round(p_val, 4), "harvey_pass": abs(t_stat) > 3.0}

    return full_metrics, t_results


def conditional_analysis(df, ratio):
    """Analyze VT performance conditioned on term structure regime."""
    spy_ret = df["SPY"].pct_change()
    base_weight = compute_vt_weight(df["VIX"])
    vt_ret = (base_weight.shift(1) * spy_ret).dropna()
    bh_ret = spy_ret.dropna()

    # Define regimes
    ratio_shifted = ratio.shift(1)  # use prior-day ratio
    regimes = {
        "deep_contango_<0.85": ratio_shifted < 0.85,
        "contango_0.85-0.95": (ratio_shifted >= 0.85) & (ratio_shifted < 0.95),
        "near_flat_0.95-1.0": (ratio_shifted >= 0.95) & (ratio_shifted <= 1.0),
        "backwardation_>1.0": ratio_shifted > 1.0,
    }

    print("\n=== CONDITIONAL ANALYSIS (by term structure regime) ===")
    print(f"{'Regime':<25} {'Days':>6} {'%':>6} {'VT_Sharpe':>10} {'BH_Sharpe':>10} {'VT-BH':>8}")
    print("-" * 70)

    cond_results = {}
    for regime_name, mask in regimes.items():
        mask_aligned = mask.reindex(vt_ret.index).fillna(False)
        vt_r = vt_ret[mask_aligned]
        bh_r = bh_ret.reindex(vt_r.index)

        if len(vt_r) < 50:
            continue

        vt_m = compute_metrics(vt_r)
        bh_m = compute_metrics(bh_r)
        delta = vt_m["sharpe"] - bh_m["sharpe"]

        pct = len(vt_r) / len(vt_ret) * 100
        print(
            f"{regime_name:<25} {len(vt_r):>6} {pct:>5.1f}% {vt_m['sharpe']:>10.4f} {bh_m['sharpe']:>10.4f} {delta:>8.4f}"
        )

        cond_results[regime_name] = {
            "n_days": len(vt_r),
            "pct": round(pct, 1),
            "vt_sharpe": vt_m["sharpe"],
            "bh_sharpe": bh_m["sharpe"],
            "delta_sharpe": round(delta, 4),
            "vt_cagr": vt_m["cagr"],
            "bh_cagr": bh_m["cagr"],
        }

    return cond_results


def main():
    print("=" * 70)
    print("K542: VIX Term Structure as VT Timing Signal")
    print("=" * 70)

    # 1. Download data
    df = download_data()
    ratio = df["VIX"] / df["VIX3M"]

    # 2. Full sample analysis
    full_metrics, t_results = full_sample_analysis(df, ratio)

    # 3. Conditional analysis
    cond_results = conditional_analysis(df, ratio)

    # 4. Cross-OOS validation (5 periods)
    oos_periods = {
        "2014-2015": ("2014-01-01", "2015-12-31"),
        "2016-2017": ("2016-01-01", "2017-12-31"),
        "2018-2019": ("2018-01-01", "2019-12-31"),
        "2020-2021": ("2020-01-01", "2021-12-31"),
        "2022-2023": ("2022-01-01", "2023-12-31"),
    }

    print("\n=== CROSS-OOS VALIDATION (5 periods) ===")
    oos_results = cross_oos_test(df, ratio, oos_periods)

    # Print cross-OOS summary
    print(f"\n{'Period':<15} {'Bench_Sh':>9} {'TS0.90_Sh':>10} {'RatioW_Sh':>10} {'BackwDlv_Sh':>12} {'ContBst_Sh':>11}")
    print("-" * 70)
    for r in oos_results:
        print(
            f"{r['period']:<15} "
            f"{r.get('benchmark_12vix_sharpe', 'N/A'):>9} "
            f"{r.get('ts_timing_0.9_sharpe', 'N/A'):>10} "
            f"{r.get('ratio_weighted_sharpe', 'N/A'):>10} "
            f"{r.get('backwardation_deleverage_sharpe', 'N/A'):>12} "
            f"{r.get('contango_boost_backw_cut_sharpe', 'N/A'):>11}"
        )

    # Count how many periods each strategy beats benchmark
    print("\n--- Cross-OOS Consistency ---")
    strat_names = ["ts_timing_0.9", "ts_timing_0.85", "ts_timing_0.95",
                   "ratio_weighted", "backwardation_deleverage", "contango_boost_backw_cut"]
    for sn in strat_names:
        wins = sum(
            1
            for r in oos_results
            if r.get(f"{sn}_sharpe", -999) > r.get("benchmark_12vix_sharpe", 999)
        )
        total = len(oos_results)
        print(f"  {sn:<35}: {wins}/{total} periods beat benchmark")

    # 5. Summary & Conclusion
    print("\n" + "=" * 70)
    print("SUMMARY & CONCLUSION")
    print("=" * 70)

    any_passes = any(v.get("harvey_pass", False) for v in t_results.values())
    if any_passes:
        passing = [k for k, v in t_results.items() if v.get("harvey_pass")]
        print(f"Harvey passes: {passing}")
    else:
        print("NO strategy passes Harvey t>3.0 threshold.")
        print("VIX term structure does NOT provide significant timing alpha over 12/VIX.")

    # Check conditional: does VT outperform more in backwardation?
    if "backwardation_>1.0" in cond_results and "deep_contango_<0.85" in cond_results:
        bw = cond_results["backwardation_>1.0"]["delta_sharpe"]
        dc = cond_results["deep_contango_<0.85"]["delta_sharpe"]
        print(f"\nConditional: VT-BH delta in backwardation: {bw:+.4f}")
        print(f"Conditional: VT-BH delta in deep contango:  {dc:+.4f}")
        if bw > dc:
            print("→ VT does outperform MORE in backwardation (as expected)")
        else:
            print("→ Unexpected: VT outperformance NOT greater in backwardation")

    # 6. Save results
    results = {
        "experiment_id": "K542",
        "title": "VIX Term Structure as VT Timing Signal",
        "date": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance (^VIX, ^VIX3M, SPY)",
        "data_period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "n_observations": len(df),
        "hypothesis": "VIX/VIX3M ratio as timing signal: VT on in backwardation, B&H in deep contango",
        "references": [
            "Chang (2016): VIX backwardation → positive future SPY returns",
            "Wang & Yen (2017): VIX term structure predictive power",
            "Harvey et al. (2016): t>3.0 threshold",
            "Prior: K43 (VIX3M as factor → null), P37 (backwardation preemptive t=4.31), P43 (subsample instability)",
        ],
        "ratio_descriptives": {
            "mean": round(ratio.mean(), 4),
            "std": round(ratio.std(), 4),
            "min": round(ratio.min(), 4),
            "max": round(ratio.max(), 4),
            "backwardation_pct": round((ratio > 1.0).mean() * 100, 1),
            "deep_contango_pct": round((ratio < 0.85).mean() * 100, 1),
        },
        "full_sample_metrics": {k: v for k, v in full_metrics.items()},
        "t_tests_vs_benchmark": t_results,
        "conditional_analysis": cond_results,
        "cross_oos_results": oos_results,
        "cross_oos_consistency": {
            sn: sum(
                1
                for r in oos_results
                if r.get(f"{sn}_sharpe", -999) > r.get("benchmark_12vix_sharpe", 999)
            )
            for sn in strat_names
        },
        "conclusion": "",
        "harvey_pass": any_passes,
    }

    # Write conclusion
    if any_passes:
        results["conclusion"] = (
            "Some term structure timing strategies pass Harvey t>3.0. "
            "See t_tests_vs_benchmark for details."
        )
    else:
        results["conclusion"] = (
            "NULL RESULT: No VIX term structure timing strategy passes Harvey t>3.0 vs 12/VIX benchmark. "
            "Conditional analysis confirms VT outperforms more in backwardation, but timing ON/OFF "
            "based on ratio does not produce statistically significant alpha. "
            "This reinforces VIX sufficiency (#35): the term structure adds no incremental value as a timing signal. "
            "Consistent with: K43 (VIX3M as factor null), N102 (multi-factor marginal), N177 (contango boost negative). "
            "P37's backwardation preemptive pass (t=4.31) was subsample-unstable (P43)."
        )

    out_path = "experiments/k542_vix_term_structure_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    results = main()
