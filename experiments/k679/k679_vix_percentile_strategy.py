"""K679: VIX Percentile-Based Strategy — Relative vs Absolute VIX

Motivation:
  12/VIX uses ABSOLUTE VIX level. But VIX's "normal" level has changed over time
  (2017 avg ~11, 2020 avg ~29). Would using VIX PERCENTILE (relative to recent
  history) be more robust? If VIX is at the 90th percentile of the last year,
  that's "high" regardless of the absolute number.

Strategies:
  a. 12/VIX (absolute): w = min(12/VIX, 1.0), baseline
  b. Percentile-based: w = 1 - VIX_percentile (rolling 252d)
  c. Z-score based: w = max(0, min(1, 1 - VIX_zscore/3))
  d. Adaptive 12/VIX: w = min(k/VIX, 1.0) where k = 12 * (avg_VIX_252d / historical_avg_VIX)

All applied to 50/50 SPY/GLD portfolio (cash remainder in risk-free).

References:
  - Copeland & Copeland (1999), "Market Timing: Style and Size Rotation Using the VIX"
  - Szado (2009), "VIX Futures and Options: A Case Study of Portfolio Diversification"
  - Our K-series: K003 (12/VIX origin), K459/K474 (cross-OOS validation)

Data source: yfinance (SPY, GLD, ^VIX)
Period: 2006-01-01 to 2026-03-27

Author: VolPred Research System
Date: 2026-03-28
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
END_DATE = "2026-03-27"
EVAL_START = "2007-01-03"  # Need 252d warmup for rolling stats
ROLLING_WINDOW = 252       # 1 year for percentile/z-score
TC_BPS = 5                 # Transaction cost in basis points (one-way)
RF_DAILY = 0.04 / 252      # ~4% annual risk-free for cash portion


def download_data():
    """Download SPY, GLD, VIX data."""
    print("Downloading SPY, GLD, ^VIX data...")
    spy = yf.download("SPY", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    gld = yf.download("GLD", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start=START_DATE, end=END_DATE, progress=False, auto_adjust=True)

    # Handle MultiIndex columns from newer yfinance
    for df in [spy, gld, vix]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    spy_ret = spy["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    gld_ret = gld["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"
    vix_close = vix["Close"].copy()
    vix_close.name = "vix"

    data = pd.concat([spy_ret, gld_ret, vix_close], axis=1).dropna()
    print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}, {len(data)} days")
    return data


def compute_vix_stats(data):
    """Compute rolling VIX percentile and z-score."""
    vix = data["vix"]

    # Rolling 252-day percentile rank
    def rolling_percentile(series, window=ROLLING_WINDOW):
        result = pd.Series(index=series.index, dtype=float)
        vals = series.values
        for i in range(window, len(vals)):
            window_vals = vals[i - window:i]
            result.iloc[i] = sp_stats.percentileofscore(window_vals, vals[i]) / 100.0
        return result

    # Rolling 252-day z-score
    rolling_mean = vix.rolling(ROLLING_WINDOW).mean()
    rolling_std = vix.rolling(ROLLING_WINDOW).std()
    z_score = (vix - rolling_mean) / rolling_std

    # Rolling 252-day average for adaptive k
    rolling_avg = vix.rolling(ROLLING_WINDOW).mean()

    # Historical expanding average (for adaptive k normalization)
    expanding_avg = vix.expanding(min_periods=ROLLING_WINDOW).mean()

    percentile = rolling_percentile(vix)

    data = data.copy()
    data["vix_percentile"] = percentile
    data["vix_zscore"] = z_score
    data["vix_rolling_avg"] = rolling_avg
    data["vix_expanding_avg"] = expanding_avg

    return data


def compute_weights(data):
    """Compute strategy weights for all four strategies."""
    vix = data["vix"]
    pct = data["vix_percentile"]
    z = data["vix_zscore"]
    rolling_avg = data["vix_rolling_avg"]
    expanding_avg = data["vix_expanding_avg"]

    # Strategy A: 12/VIX (absolute baseline)
    w_12vix = np.minimum(12.0 / vix, 1.0)

    # Strategy B: Percentile-based
    # VIX at 90th percentile → w = 0.10 (defensive)
    # VIX at 10th percentile → w = 0.90 (aggressive)
    w_percentile = 1.0 - pct

    # Strategy C: Z-score based
    # z = 0 (average VIX) → w = 1.0
    # z = 3 (3 std above) → w = 0.0
    # z < 0 (below average) → w = 1.0 (capped)
    w_zscore = np.clip(1.0 - z / 3.0, 0.0, 1.0)

    # Strategy D: Adaptive 12/VIX
    # k = 12 * (current_rolling_avg / historical_expanding_avg)
    # When VIX regime is high (avg 25 vs historical 18), k increases proportionally
    k_adaptive = 12.0 * (rolling_avg / expanding_avg)
    w_adaptive = np.minimum(k_adaptive / vix, 1.0)

    data = data.copy()
    data["w_12vix"] = w_12vix
    data["w_percentile"] = w_percentile
    data["w_zscore"] = w_zscore
    data["w_adaptive"] = w_adaptive

    return data


def backtest_strategy(data, weight_col, name, tc_bps=TC_BPS):
    """Backtest a 50/50 SPY/GLD strategy with given weight column."""
    eval_mask = data.index >= EVAL_START
    df = data[eval_mask].copy()

    if len(df) == 0:
        return None

    weights = df[weight_col].values
    spy_ret = df["spy_ret"].values
    gld_ret = df["gld_ret"].values

    # 50/50 SPY/GLD portfolio return (when invested)
    portfolio_ret = 0.5 * spy_ret + 0.5 * gld_ret

    # Strategy return = w * portfolio_ret + (1 - w) * rf
    strategy_ret = np.zeros(len(df))
    tc_rate = tc_bps / 10000.0

    prev_w = 0.0
    for i in range(len(df)):
        w = weights[i]
        if np.isnan(w):
            w = prev_w  # carry forward if NaN

        # Transaction cost from weight change
        tc = abs(w - prev_w) * tc_rate
        strategy_ret[i] = w * portfolio_ret[i] + (1 - w) * RF_DAILY - tc
        prev_w = w

    # Compute metrics
    cum_ret = np.cumprod(1 + strategy_ret)
    total_ret = cum_ret[-1] - 1
    n_years = len(df) / 252.0
    cagr = (1 + total_ret) ** (1 / n_years) - 1

    ann_ret = np.mean(strategy_ret) * 252
    ann_vol = np.std(strategy_ret, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0  # excess over 4% rf

    # Max drawdown
    running_max = np.maximum.accumulate(cum_ret)
    drawdowns = (cum_ret - running_max) / running_max
    mdd = np.min(drawdowns)

    # Calmar ratio
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    # Sortino ratio (downside deviation)
    downside = strategy_ret[strategy_ret < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 0 else ann_vol
    sortino = (ann_ret - 0.04) / downside_vol if downside_vol > 0 else 0

    # Average weight (exposure)
    avg_weight = np.nanmean(weights)

    # Turnover
    weight_changes = np.abs(np.diff(weights[~np.isnan(weights)]))
    avg_daily_turnover = np.mean(weight_changes) if len(weight_changes) > 0 else 0
    annual_turnover = avg_daily_turnover * 252

    return {
        "strategy": name,
        "cagr": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "ann_vol": round(ann_vol * 100, 2),
        "avg_weight": round(avg_weight, 3),
        "annual_turnover": round(annual_turnover, 2),
        "total_return_pct": round(total_ret * 100, 2),
        "n_days": len(df),
        "n_years": round(n_years, 1),
        "cum_ret_series": cum_ret.tolist(),
        "dates": [d.strftime("%Y-%m-%d") for d in df.index],
    }


def analyze_regime_periods(data):
    """Analyze how each strategy behaves during key VIX regime periods."""
    periods = {
        "Low VIX 2017": ("2017-01-01", "2017-12-31"),
        "COVID 2020": ("2020-01-01", "2020-12-31"),
        "Post-COVID 2021": ("2021-01-01", "2021-12-31"),
        "Rate Hike 2022": ("2022-01-01", "2022-12-31"),
        "Normalization 2023-24": ("2023-01-01", "2024-12-31"),
        "Recent 2025-26": ("2025-01-01", "2026-03-27"),
    }

    weight_cols = ["w_12vix", "w_percentile", "w_zscore", "w_adaptive"]
    strategy_names = ["12/VIX", "Percentile", "Z-Score", "Adaptive 12/VIX"]

    regime_analysis = {}

    for period_name, (start, end) in periods.items():
        mask = (data.index >= start) & (data.index <= end)
        period_data = data[mask]

        if len(period_data) < 10:
            continue

        avg_vix = period_data["vix"].mean()
        vix_std = period_data["vix"].std()

        period_info = {
            "avg_vix": round(float(avg_vix), 2),
            "vix_std": round(float(vix_std), 2),
            "n_days": len(period_data),
            "strategies": {},
        }

        portfolio_ret = 0.5 * period_data["spy_ret"] + 0.5 * period_data["gld_ret"]

        for wc, sn in zip(weight_cols, strategy_names):
            w = period_data[wc]
            valid_w = w.dropna()
            if len(valid_w) == 0:
                continue

            avg_w = float(valid_w.mean())
            strat_ret = w * portfolio_ret + (1 - w) * RF_DAILY
            strat_ret = strat_ret.dropna()

            cum = (1 + strat_ret).cumprod()
            total = float(cum.iloc[-1] - 1) if len(cum) > 0 else 0
            ann_ret = float(strat_ret.mean() * 252)
            ann_vol = float(strat_ret.std() * np.sqrt(252)) if len(strat_ret) > 1 else 0

            period_info["strategies"][sn] = {
                "avg_weight": round(avg_w, 3),
                "period_return_pct": round(total * 100, 2),
                "ann_return_pct": round(ann_ret * 100, 2),
                "ann_vol_pct": round(ann_vol * 100, 2),
            }

        regime_analysis[period_name] = period_info

    return regime_analysis


def analyze_vix_regimes_detail(data):
    """Deeper analysis: how weights differ in VIX regimes."""
    eval_data = data[data.index >= EVAL_START].dropna(subset=["w_12vix", "w_percentile", "w_zscore", "w_adaptive"])

    vix = eval_data["vix"]
    regimes = {
        "Very Low (VIX<12)": vix < 12,
        "Low (12-15)": (vix >= 12) & (vix < 15),
        "Normal (15-20)": (vix >= 15) & (vix < 20),
        "Elevated (20-25)": (vix >= 20) & (vix < 25),
        "High (25-30)": (vix >= 25) & (vix < 30),
        "Very High (>30)": vix >= 30,
    }

    weight_cols = ["w_12vix", "w_percentile", "w_zscore", "w_adaptive"]
    strategy_names = ["12/VIX", "Percentile", "Z-Score", "Adaptive 12/VIX"]

    regime_weights = {}
    for regime_name, mask in regimes.items():
        regime_data = eval_data[mask]
        n_days = len(regime_data)
        if n_days == 0:
            continue

        avg_vix = float(regime_data["vix"].mean())
        weights_by_strat = {}
        for wc, sn in zip(weight_cols, strategy_names):
            w = regime_data[wc].dropna()
            if len(w) > 0:
                weights_by_strat[sn] = {
                    "avg_weight": round(float(w.mean()), 3),
                    "std_weight": round(float(w.std()), 3),
                    "min_weight": round(float(w.min()), 3),
                    "max_weight": round(float(w.max()), 3),
                }

        regime_weights[regime_name] = {
            "n_days": n_days,
            "pct_of_total": round(n_days / len(eval_data) * 100, 1),
            "avg_vix": round(avg_vix, 2),
            "weights": weights_by_strat,
        }

    return regime_weights


def statistical_comparison(data):
    """Pairwise Diebold-Mariano style comparison of daily returns."""
    eval_data = data[data.index >= EVAL_START].copy()
    weight_cols = ["w_12vix", "w_percentile", "w_zscore", "w_adaptive"]
    strategy_names = ["12/VIX", "Percentile", "Z-Score", "Adaptive 12/VIX"]

    portfolio_ret = 0.5 * eval_data["spy_ret"] + 0.5 * eval_data["gld_ret"]

    # Compute daily strategy returns
    strat_returns = {}
    for wc, sn in zip(weight_cols, strategy_names):
        w = eval_data[wc].ffill().fillna(0)
        sr = w * portfolio_ret + (1 - w) * RF_DAILY
        strat_returns[sn] = sr.dropna()

    # Pairwise t-tests on return differences
    comparisons = {}
    baseline = "12/VIX"
    for sn in strategy_names:
        if sn == baseline:
            continue

        # Align indices
        common_idx = strat_returns[baseline].index.intersection(strat_returns[sn].index)
        r_base = strat_returns[baseline].loc[common_idx]
        r_alt = strat_returns[sn].loc[common_idx]

        diff = r_alt - r_base
        t_stat = float(diff.mean() / (diff.std() / np.sqrt(len(diff))))
        p_val = float(2 * sp_stats.t.sf(abs(t_stat), df=len(diff) - 1))

        comparisons[f"{sn} vs {baseline}"] = {
            "mean_diff_bps": round(float(diff.mean() * 10000), 3),
            "t_stat": round(t_stat, 3),
            "p_value": round(p_val, 4),
            "significant_5pct": p_val < 0.05,
            "significant_1pct": p_val < 0.01,
            "n_obs": len(diff),
        }

    # Correlation of weights
    weight_corr = {}
    for i, (wc1, sn1) in enumerate(zip(weight_cols, strategy_names)):
        for wc2, sn2 in zip(weight_cols[i + 1:], strategy_names[i + 1:]):
            w1 = eval_data[wc1].dropna()
            w2 = eval_data[wc2].dropna()
            common = w1.index.intersection(w2.index)
            if len(common) > 10:
                corr = float(w1.loc[common].corr(w2.loc[common]))
                weight_corr[f"{sn1} vs {sn2}"] = round(corr, 4)

    return {"return_comparisons": comparisons, "weight_correlations": weight_corr}


def sub_period_analysis(data):
    """Split into sub-periods to check robustness."""
    eval_data = data[data.index >= EVAL_START]
    mid_point = eval_data.index[len(eval_data) // 2]

    sub_periods = {
        "First Half": (EVAL_START, mid_point.strftime("%Y-%m-%d")),
        "Second Half": (mid_point.strftime("%Y-%m-%d"), END_DATE),
        "Pre-COVID (2007-2019)": (EVAL_START, "2019-12-31"),
        "Post-COVID (2020-2026)": ("2020-01-01", END_DATE),
    }

    weight_cols = ["w_12vix", "w_percentile", "w_zscore", "w_adaptive"]
    strategy_names = ["12/VIX", "Percentile", "Z-Score", "Adaptive 12/VIX"]

    results = {}
    for period_name, (start, end) in sub_periods.items():
        mask = (data.index >= start) & (data.index <= end)
        period_data = data[mask].dropna(subset=weight_cols)

        if len(period_data) < 50:
            continue

        portfolio_ret = 0.5 * period_data["spy_ret"] + 0.5 * period_data["gld_ret"]

        period_results = {"n_days": len(period_data)}
        for wc, sn in zip(weight_cols, strategy_names):
            w = period_data[wc]
            sr = w * portfolio_ret + (1 - w) * RF_DAILY
            sr = sr.dropna()

            cum = (1 + sr).cumprod()
            total = float(cum.iloc[-1] - 1) if len(cum) > 0 else 0
            ann_ret = float(sr.mean() * 252)
            ann_vol = float(sr.std() * np.sqrt(252)) if len(sr) > 1 else 0
            sharpe = (ann_ret - 0.04) / ann_vol if ann_vol > 0 else 0

            # Max drawdown
            running_max = np.maximum.accumulate(cum.values)
            dd = (cum.values - running_max) / running_max
            mdd = float(np.min(dd))

            period_results[sn] = {
                "sharpe": round(sharpe, 3),
                "cagr_pct": round((((1 + total) ** (252 / max(len(sr), 1))) - 1) * 100, 2),
                "mdd_pct": round(mdd * 100, 2),
                "avg_weight": round(float(w.mean()), 3),
            }

        results[period_name] = period_results

    return results


def main():
    print("=" * 70)
    print("K679: VIX Percentile-Based Strategy — Relative vs Absolute VIX")
    print("=" * 70)

    # Step 1: Download data
    data = download_data()

    # Step 2: Descriptive statistics on VIX
    print("\n--- VIX Descriptive Statistics ---")
    vix = data["vix"]
    print(f"  Mean: {vix.mean():.2f}")
    print(f"  Std:  {vix.std():.2f}")
    print(f"  Min:  {vix.min():.2f}")
    print(f"  Max:  {vix.max():.2f}")
    print(f"  Skew: {vix.skew():.2f}")
    print(f"  Kurt: {vix.kurtosis():.2f}")

    vix_descriptive = {
        "mean": round(float(vix.mean()), 2),
        "std": round(float(vix.std()), 2),
        "min": round(float(vix.min()), 2),
        "max": round(float(vix.max()), 2),
        "skewness": round(float(vix.skew()), 2),
        "kurtosis": round(float(vix.kurtosis()), 2),
        "median": round(float(vix.median()), 2),
        "pct_25": round(float(vix.quantile(0.25)), 2),
        "pct_75": round(float(vix.quantile(0.75)), 2),
    }

    # Step 3: Compute VIX stats
    print("\n--- Computing VIX rolling statistics ---")
    data = compute_vix_stats(data)

    # Step 4: Compute weights
    print("--- Computing strategy weights ---")
    data = compute_weights(data)

    # Step 5: Full backtest
    print("\n--- Full Backtest Results ---")
    strategies = [
        ("w_12vix", "12/VIX (Absolute)"),
        ("w_percentile", "Percentile-Based"),
        ("w_zscore", "Z-Score Based"),
        ("w_adaptive", "Adaptive 12/VIX"),
    ]

    backtest_results = []
    for wcol, sname in strategies:
        result = backtest_strategy(data, wcol, sname)
        if result:
            # Don't include large series in print
            print(f"\n  {sname}:")
            print(f"    CAGR: {result['cagr']:.2f}%")
            print(f"    Sharpe: {result['sharpe']:.3f}")
            print(f"    Sortino: {result['sortino']:.3f}")
            print(f"    MDD: {result['mdd']:.2f}%")
            print(f"    Calmar: {result['calmar']:.3f}")
            print(f"    Avg Weight: {result['avg_weight']:.3f}")
            print(f"    Annual Turnover: {result['annual_turnover']:.2f}")
            backtest_results.append(result)

    # Step 6: Regime analysis
    print("\n--- VIX Regime Period Analysis ---")
    regime_periods = analyze_regime_periods(data)
    for period, info in regime_periods.items():
        print(f"\n  {period} (Avg VIX={info['avg_vix']}, {info['n_days']} days):")
        for sn, si in info["strategies"].items():
            print(f"    {sn}: w={si['avg_weight']:.3f}, ret={si['period_return_pct']:.1f}%")

    # Step 7: VIX regime weight analysis
    print("\n--- Weight Behavior by VIX Level ---")
    regime_weights = analyze_vix_regimes_detail(data)
    for regime, info in regime_weights.items():
        print(f"\n  {regime} ({info['n_days']} days, {info['pct_of_total']}%):")
        for sn, wi in info["weights"].items():
            print(f"    {sn}: avg={wi['avg_weight']:.3f} [{wi['min_weight']:.3f}-{wi['max_weight']:.3f}]")

    # Step 8: Statistical comparison
    print("\n--- Statistical Comparison vs 12/VIX ---")
    stat_comp = statistical_comparison(data)
    for comp_name, comp_info in stat_comp["return_comparisons"].items():
        sig = "***" if comp_info["significant_1pct"] else ("**" if comp_info["significant_5pct"] else "ns")
        print(f"  {comp_name}: diff={comp_info['mean_diff_bps']:.3f} bps/day, t={comp_info['t_stat']:.3f} {sig}")

    print("\n  Weight correlations:")
    for pair, corr in stat_comp["weight_correlations"].items():
        print(f"    {pair}: {corr:.4f}")

    # Step 9: Sub-period robustness
    print("\n--- Sub-Period Robustness ---")
    sub_periods = sub_period_analysis(data)
    for period, info in sub_periods.items():
        print(f"\n  {period} ({info['n_days']} days):")
        for sn in ["12/VIX", "Percentile", "Z-Score", "Adaptive 12/VIX"]:
            if sn in info:
                si = info[sn]
                print(f"    {sn}: Sharpe={si['sharpe']:.3f}, CAGR={si['cagr_pct']:.1f}%, MDD={si['mdd_pct']:.1f}%")

    # Step 10: Buy-and-hold comparison
    print("\n--- Buy-and-Hold Comparison ---")
    eval_data = data[data.index >= EVAL_START]
    portfolio_ret = 0.5 * eval_data["spy_ret"] + 0.5 * eval_data["gld_ret"]
    bh_cum = (1 + portfolio_ret).cumprod()
    bh_total = float(bh_cum.iloc[-1] - 1)
    bh_n_years = len(eval_data) / 252.0
    bh_cagr = (1 + bh_total) ** (1 / bh_n_years) - 1
    bh_ann_vol = float(portfolio_ret.std() * np.sqrt(252))
    bh_sharpe = (float(portfolio_ret.mean() * 252) - 0.04) / bh_ann_vol if bh_ann_vol > 0 else 0
    bh_running_max = np.maximum.accumulate(bh_cum.values)
    bh_dd = (bh_cum.values - bh_running_max) / bh_running_max
    bh_mdd = float(np.min(bh_dd))

    bh_result = {
        "strategy": "Buy-and-Hold 50/50",
        "cagr": round(bh_cagr * 100, 2),
        "sharpe": round(bh_sharpe, 3),
        "mdd": round(bh_mdd * 100, 2),
    }
    print(f"  Buy-and-Hold 50/50: CAGR={bh_cagr*100:.2f}%, Sharpe={bh_sharpe:.3f}, MDD={bh_mdd*100:.2f}%")

    # ============================================================================
    # Save results
    # ============================================================================
    # Strip large series from saved results to keep JSON manageable
    backtest_summary = []
    for r in backtest_results:
        summary = {k: v for k, v in r.items() if k not in ("cum_ret_series", "dates")}
        backtest_summary.append(summary)

    results = {
        "experiment_id": "K679",
        "title": "VIX Percentile-Based Strategy vs Absolute 12/VIX",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance (SPY, GLD, ^VIX)",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "n_eval_days": len(data[data.index >= EVAL_START]),
        "methodology": {
            "portfolio": "50/50 SPY/GLD, cash remainder at 4% annual",
            "transaction_cost": f"{TC_BPS} bps one-way",
            "rolling_window": ROLLING_WINDOW,
            "strategies": {
                "12/VIX": "w = min(12/VIX, 1.0) — absolute VIX level",
                "Percentile": "w = 1 - percentile_rank(VIX, 252d) — relative to recent history",
                "Z-Score": "w = clip(1 - z/3, 0, 1) where z = (VIX - mean_252d) / std_252d",
                "Adaptive 12/VIX": "w = min(k/VIX, 1.0) where k = 12 * (avg_252d / expanding_avg)",
            },
        },
        "references": [
            "Copeland & Copeland (1999), Market Timing with VIX",
            "Szado (2009), VIX Futures Portfolio Diversification",
            "VolPred K003: 12/VIX origin",
        ],
        "vix_descriptive_stats": vix_descriptive,
        "backtest_results": backtest_summary,
        "buy_and_hold": bh_result,
        "regime_period_analysis": regime_periods,
        "vix_level_weight_analysis": regime_weights,
        "statistical_comparison": stat_comp,
        "sub_period_robustness": sub_periods,
        "key_findings": [],  # Filled below
    }

    # Determine key findings
    findings = []
    best = max(backtest_summary, key=lambda x: x["sharpe"])
    worst = min(backtest_summary, key=lambda x: x["sharpe"])
    baseline_sharpe = next(r["sharpe"] for r in backtest_summary if r["strategy"] == "12/VIX (Absolute)")

    findings.append(
        f"Best strategy: {best['strategy']} (Sharpe={best['sharpe']:.3f}, CAGR={best['cagr']:.2f}%)"
    )
    findings.append(
        f"Worst strategy: {worst['strategy']} (Sharpe={worst['sharpe']:.3f}, CAGR={worst['cagr']:.2f}%)"
    )
    findings.append(
        f"12/VIX baseline Sharpe: {baseline_sharpe:.3f}"
    )

    # Check if any alternative beats baseline significantly
    for comp_name, comp_info in stat_comp["return_comparisons"].items():
        if comp_info["significant_5pct"] and comp_info["mean_diff_bps"] > 0:
            findings.append(f"{comp_name}: statistically significant improvement ({comp_info['mean_diff_bps']:.3f} bps/day, t={comp_info['t_stat']:.3f})")
        elif comp_info["significant_5pct"] and comp_info["mean_diff_bps"] < 0:
            findings.append(f"{comp_name}: statistically significant underperformance ({comp_info['mean_diff_bps']:.3f} bps/day)")
        else:
            findings.append(f"{comp_name}: no significant difference (t={comp_info['t_stat']:.3f}, p={comp_info['p_value']:.4f})")

    # COVID period insight
    covid_info = regime_periods.get("COVID 2020", {})
    if covid_info:
        findings.append(
            f"COVID 2020 avg VIX={covid_info['avg_vix']}: "
            + ", ".join(f"{sn} w={si['avg_weight']:.3f}" for sn, si in covid_info.get("strategies", {}).items())
        )

    # Low VIX 2017 insight
    low_vix_info = regime_periods.get("Low VIX 2017", {})
    if low_vix_info:
        findings.append(
            f"Low VIX 2017 avg VIX={low_vix_info['avg_vix']}: "
            + ", ".join(f"{sn} w={si['avg_weight']:.3f}" for sn, si in low_vix_info.get("strategies", {}).items())
        )

    results["key_findings"] = findings

    # Save
    out_path = Path(__file__).parent / "k679_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    # Print key findings
    print("\n" + "=" * 70)
    print("KEY FINDINGS:")
    print("=" * 70)
    for i, finding in enumerate(findings, 1):
        print(f"  {i}. {finding}")


if __name__ == "__main__":
    main()
