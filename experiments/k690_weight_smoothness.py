"""K690: Weight Smoothness and Lag Robustness — Why Simple Strategies Survive

Motivation:
K689 found 12/VIX barely affected by lag correction (Sharpe 1.87→1.91) while
Piecewise collapses (3.16→1.62). The key difference: 12/VIX has smooth weights
(w_T ≈ w_{T-1}) while Piecewise has sharp discontinuities at VIX=12/20.

This experiment quantifies the relationship between weight smoothness and
lag robustness — a critical practical consideration for retail investors who
cannot trade at the exact closing price.

Analysis:
  1. Weight smoothness metrics for each strategy
  2. Lag sensitivity: Sharpe at lag = {0, 1, 2, 3, 5} days
  3. "Lag Robustness Ratio" = Sharpe(lag=1) / Sharpe(lag=0)
  4. Regression: smoothness → lag robustness

Strategies:
  a. 12/VIX (smooth, continuous mapping VIX → weight)
  b. EWMA VT (smooth, continuous via exponential smoothing)
  c. Piecewise (discontinuous at VIX=15, 20)
  d. P3-AGG Lookup (discontinuous at VIX=15, 25)
  e. VIX Percentile (smooth but data-dependent via rolling rank)

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
Evaluation: 2007-01-03 to 2026-03-27 (1y warmup)

References:
  - K687: Definitive lag-corrected strategy ranking
  - K689: Live vs backtest discrepancy (lag sensitivity discovery)
  - RiskMetrics (1996): EWMA λ=0.94
  - Copeland & Copeland (1999): Market Timing with VIX
  - Kirby & Ostdiek (2012): It's All in the Timing (portfolio rebalancing)
  - Harvey et al. (2016): ...and the Cross-Section of Expected Returns

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
EVAL_START = "2007-01-03"
ROLLING_WINDOW = 252
TC_BPS = 5
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
EWMA_LAMBDA = 0.94
TARGET_VOL = 0.10
VIX_12_CAP = 1.5
RESULTS_FILE = Path(__file__).parent / "k690_results.json"
LAGS = [0, 1, 2, 3, 5]


# ============================================================================
# Data Download
# ============================================================================
def download_data():
    """Download SPY, GLD, VIX data from yfinance."""
    print("=" * 70)
    print("K690: WEIGHT SMOOTHNESS AND LAG ROBUSTNESS")
    print("=" * 70)
    print("\nDownloading data from yfinance...")

    tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX"}
    raw = {}

    for name, ticker in tickers.items():
        df = yf.download(ticker, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        raw[name] = df
        print(f"  {name}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

    spy_ret = raw["SPY"]["Close"].pct_change().dropna()
    spy_ret.name = "spy_ret"
    gld_ret = raw["GLD"]["Close"].pct_change().dropna()
    gld_ret.name = "gld_ret"
    vix_close = raw["VIX"]["Close"].copy()
    vix_close.name = "vix"

    data = pd.concat([spy_ret, gld_ret, vix_close], axis=1).dropna()
    print(f"\n  Merged: {len(data)} rows, {data.index[0].date()} to {data.index[-1].date()}")
    print(f"  VIX: mean={data['vix'].mean():.2f}, std={data['vix'].std():.2f}, "
          f"min={data['vix'].min():.2f}, max={data['vix'].max():.2f}")

    return data


# ============================================================================
# Signal Computation Functions (unlagged — lag applied in backtest)
# ============================================================================
def compute_rolling_percentile_strict(vix_series, window=ROLLING_WINDOW):
    """Rolling percentile rank, STRICTLY excluding current value."""
    result = pd.Series(index=vix_series.index, dtype=float)
    vals = vix_series.values
    for i in range(window, len(vals)):
        prior_window = vals[i - window:i]
        current = vals[i]
        pct_rank = np.sum(prior_window <= current) / len(prior_window)
        result.iloc[i] = pct_rank
    return result


def compute_ewma_vol(returns, lam=EWMA_LAMBDA):
    """EWMA volatility (RiskMetrics), returns annualized vol series."""
    var = np.zeros(len(returns))
    var[0] = returns.iloc[0] ** 2 if len(returns) > 0 else 0.0001
    for i in range(1, len(returns)):
        var[i] = lam * var[i - 1] + (1 - lam) * returns.iloc[i] ** 2
    vol_daily = np.sqrt(var)
    vol_ann = vol_daily * np.sqrt(252)
    return pd.Series(vol_ann, index=returns.index, name="ewma_vol")


def compute_raw_weights(data):
    """Compute RAW (unlagged) weight series for all strategies.

    Returns dict: strategy_name -> pd.Series of raw weights (before any lag).
    """
    vix = data["vix"]
    port_ret = 0.5 * data["spy_ret"] + 0.5 * data["gld_ret"]

    strategies = {}

    # (a) 12/VIX: w = min(12 / VIX, 1.5) — smooth, continuous, hyperbolic
    strategies["12/VIX"] = np.minimum(12.0 / vix, VIX_12_CAP)

    # (b) EWMA VT: target_vol / realized_vol — smooth via exponential decay
    ewma_vol = compute_ewma_vol(port_ret, EWMA_LAMBDA)
    strategies["EWMA VT"] = np.minimum(TARGET_VOL / ewma_vol.replace(0, np.nan), 1.5)

    # (c) Piecewise: VIX<15 → 100%, 15-20 → linear, ≥20 → 0%
    def piecewise_weight(v):
        if v < 15:
            return 1.0
        elif v < 20:
            return 1.0 - (v - 15) / 5.0
        else:
            return 0.0
    strategies["Piecewise"] = vix.apply(piecewise_weight)

    # (d) P3-AGG Lookup: VIX<15 → 80%, 15-25 → 45%, >25 → 10%
    def p3agg_weight(v):
        if v < 15:
            return 0.80
        elif v <= 25:
            return 0.45
        else:
            return 0.10
    strategies["P3-AGG"] = vix.apply(p3agg_weight)

    # (e) VIX Percentile: w = 1 - percentile_rank(VIX, prior 252d)
    pct_rank = compute_rolling_percentile_strict(vix, ROLLING_WINDOW)
    strategies["VIX Pctile"] = 1.0 - pct_rank

    return strategies


# ============================================================================
# Part 1: Weight Smoothness Metrics
# ============================================================================
def compute_smoothness_metrics(raw_weights, eval_start=EVAL_START):
    """Compute weight smoothness metrics for each strategy."""
    print("\n" + "=" * 70)
    print("PART 1: WEIGHT SMOOTHNESS METRICS")
    print("=" * 70)

    results = {}

    for name, w_series in raw_weights.items():
        # Restrict to evaluation period
        w = w_series[w_series.index >= eval_start].dropna()

        if len(w) < 10:
            print(f"  {name}: too few data points ({len(w)})")
            continue

        # Daily weight changes
        dw = w.diff().dropna()
        abs_dw = dw.abs()

        # Weight autocorrelation: corr(w_t, w_{t-1})
        w_arr = w.values
        autocorr = np.corrcoef(w_arr[:-1], w_arr[1:])[0, 1]

        # Mean absolute daily weight change
        mean_abs_dw = float(abs_dw.mean())

        # Median absolute daily weight change
        median_abs_dw = float(abs_dw.median())

        # Max daily weight change
        max_abs_dw = float(abs_dw.max())

        # Std of daily weight changes
        std_dw = float(dw.std())

        # Number of "jumps" (|Δw| > 10%)
        jumps_10pct = int((abs_dw > 0.10).sum())
        jumps_5pct = int((abs_dw > 0.05).sum())
        jumps_20pct = int((abs_dw > 0.20).sum())

        # Jump frequency (per year)
        n_years = len(w) / 252
        jump_freq_10 = jumps_10pct / n_years
        jump_freq_5 = jumps_5pct / n_years

        # Weight level statistics
        mean_w = float(w.mean())
        std_w = float(w.std())
        min_w = float(w.min())
        max_w = float(w.max())

        # "Turnover" proxy: sum of |Δw| per year
        annual_turnover = float(abs_dw.sum() / n_years)

        # Continuity score: 1 - (fraction of days with |Δw| > 0.01)
        # Higher = more continuous
        continuity = float(1.0 - (abs_dw > 0.01).mean())

        results[name] = {
            "n_obs": len(w),
            "n_years": round(n_years, 2),
            "weight_autocorrelation": round(autocorr, 6),
            "mean_abs_daily_change": round(mean_abs_dw, 6),
            "median_abs_daily_change": round(median_abs_dw, 6),
            "max_abs_daily_change": round(max_abs_dw, 4),
            "std_daily_change": round(std_dw, 6),
            "jumps_gt_5pct": jumps_5pct,
            "jumps_gt_10pct": jumps_10pct,
            "jumps_gt_20pct": jumps_20pct,
            "jump_freq_10pct_per_year": round(jump_freq_10, 2),
            "jump_freq_5pct_per_year": round(jump_freq_5, 2),
            "annual_turnover": round(annual_turnover, 4),
            "continuity_score": round(continuity, 4),
            "mean_weight": round(mean_w, 4),
            "std_weight": round(std_w, 4),
            "min_weight": round(min_w, 4),
            "max_weight": round(max_w, 4),
        }

        print(f"\n  {name}:")
        print(f"    Autocorr(w_t, w_{{t-1}}): {autocorr:.4f}")
        print(f"    Mean |Δw|: {mean_abs_dw:.6f}")
        print(f"    Max  |Δw|: {max_abs_dw:.4f}")
        print(f"    Jumps >10%: {jumps_10pct} ({jump_freq_10:.1f}/yr)")
        print(f"    Annual turnover: {annual_turnover:.4f}")
        print(f"    Continuity: {continuity:.4f}")
        print(f"    Weight: mean={mean_w:.3f}, std={std_w:.3f}")

    return results


# ============================================================================
# Part 2: Lag Sensitivity Backtest
# ============================================================================
def annualised_sharpe(returns, rf_daily=RF_DAILY):
    """Annualised Sharpe ratio from daily returns."""
    excess = returns - rf_daily
    mu = np.mean(excess)
    sigma = np.std(excess, ddof=1)
    if sigma == 0 or np.isnan(sigma):
        return np.nan
    return float(mu / sigma * np.sqrt(252))


def compute_cagr(returns):
    """CAGR from daily returns."""
    cum = np.prod(1 + returns) ** (252 / len(returns)) - 1
    return float(cum)


def compute_mdd(returns):
    """Maximum drawdown from daily returns."""
    cum = np.cumprod(1 + returns)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    return float(dd.min())


def backtest_with_lag(data, raw_weights, lag, eval_start=EVAL_START,
                      tc_bps=TC_BPS):
    """Backtest all strategies with a specific lag applied to signals.

    lag=0: lookahead (use today's signal for today's return) — BIASED
    lag=1: standard (use yesterday's signal for today's return) — CORRECT
    lag=2+: delayed execution (practical for slow traders)

    All strategies applied to 50/50 SPY/GLD portfolio.
    """
    eval_mask = data.index >= eval_start
    df = data[eval_mask].copy()

    port_ret = (0.5 * df["spy_ret"] + 0.5 * df["gld_ret"]).values
    tc_rate = tc_bps / 10000.0

    results = {}

    for name, w_raw in raw_weights.items():
        # Apply lag
        w_lagged = w_raw.shift(lag)
        w_eval = w_lagged[eval_mask].values

        # Find valid range (no NaN in weights)
        valid_mask = ~np.isnan(w_eval)
        if valid_mask.sum() < 252:
            results[name] = {"sharpe": np.nan, "cagr": np.nan, "mdd": np.nan,
                             "n_valid": int(valid_mask.sum())}
            continue

        w_valid = w_eval[valid_mask]
        ret_valid = port_ret[valid_mask]

        # Compute net returns with transaction costs
        net_returns = np.zeros(len(w_valid))
        prev_w = 0.0

        for i in range(len(w_valid)):
            w_i = w_valid[i]
            if np.isnan(w_i):
                w_i = prev_w

            # Transaction cost for weight change
            tc = tc_rate * abs(w_i - prev_w)

            # Gross return: w * port_ret + (1-w) * rf_daily
            gross = w_i * ret_valid[i] + (1 - w_i) * RF_DAILY
            net_returns[i] = gross - tc
            prev_w = w_i

        sharpe = annualised_sharpe(net_returns)
        cagr = compute_cagr(net_returns)
        mdd = compute_mdd(net_returns)

        # Annualized volatility
        ann_vol = float(np.std(net_returns, ddof=1) * np.sqrt(252))

        # Sortino ratio
        downside = net_returns[net_returns < RF_DAILY] - RF_DAILY
        downside_vol = float(np.std(downside, ddof=1) * np.sqrt(252)) if len(downside) > 1 else np.nan
        sortino = float((np.mean(net_returns) - RF_DAILY) * 252 / (downside_vol if downside_vol > 0 else np.nan))

        results[name] = {
            "sharpe": round(sharpe, 4),
            "cagr": round(cagr, 4),
            "mdd": round(mdd, 4),
            "ann_vol": round(ann_vol, 4),
            "sortino": round(sortino, 4) if not np.isnan(sortino) else None,
            "n_valid": int(valid_mask.sum()),
        }

    return results


def lag_sensitivity_analysis(data, raw_weights):
    """Test all strategies across multiple lag values."""
    print("\n" + "=" * 70)
    print("PART 2: LAG SENSITIVITY ANALYSIS")
    print("=" * 70)

    all_results = {}

    for lag in LAGS:
        print(f"\n  --- Lag = {lag} day(s) ---")
        bt = backtest_with_lag(data, raw_weights, lag)

        for name, metrics in bt.items():
            if name not in all_results:
                all_results[name] = {}
            all_results[name][f"lag_{lag}"] = metrics

            sharpe_str = f"{metrics['sharpe']:.4f}" if not np.isnan(metrics.get('sharpe', np.nan)) else "N/A"
            print(f"    {name:12s}: Sharpe={sharpe_str}, "
                  f"CAGR={metrics.get('cagr', 0):.4f}, "
                  f"MDD={metrics.get('mdd', 0):.4f}")

    return all_results


# ============================================================================
# Part 3: Lag Robustness Ratio
# ============================================================================
def compute_robustness_ratios(lag_results):
    """Compute Lag Robustness Ratio = Sharpe(lag=L) / Sharpe(lag=0) for each L."""
    print("\n" + "=" * 70)
    print("PART 3: LAG ROBUSTNESS RATIOS")
    print("=" * 70)

    ratios = {}

    for name, lag_data in lag_results.items():
        s0 = lag_data.get("lag_0", {}).get("sharpe", np.nan)
        if np.isnan(s0) or s0 == 0:
            print(f"  {name}: Sharpe(lag=0) = {s0}, skipping")
            continue

        strategy_ratios = {}
        for lag in LAGS:
            s_lag = lag_data.get(f"lag_{lag}", {}).get("sharpe", np.nan)
            if not np.isnan(s_lag):
                ratio = s_lag / s0
                strategy_ratios[f"ratio_lag_{lag}"] = round(ratio, 4)

        # Key metric: ratio at lag=1 (standard proper lag)
        r1 = strategy_ratios.get("ratio_lag_1", np.nan)

        # Sharpe decay rate: fit linear regression on lag vs sharpe
        sharpe_vals = []
        lag_vals = []
        for lag in LAGS:
            s = lag_data.get(f"lag_{lag}", {}).get("sharpe", np.nan)
            if not np.isnan(s):
                sharpe_vals.append(s)
                lag_vals.append(lag)

        if len(sharpe_vals) >= 3:
            slope, intercept, r_value, p_value, std_err = sp_stats.linregress(
                lag_vals, sharpe_vals)
            strategy_ratios["sharpe_decay_slope"] = round(slope, 4)
            strategy_ratios["sharpe_decay_r2"] = round(r_value**2, 4)
            strategy_ratios["sharpe_decay_pvalue"] = round(p_value, 4)
        else:
            slope = np.nan

        ratios[name] = strategy_ratios

        print(f"\n  {name}:")
        print(f"    Sharpe(lag=0) = {s0:.4f}")
        for lag in LAGS[1:]:
            s_lag = lag_data.get(f"lag_{lag}", {}).get("sharpe", np.nan)
            r = strategy_ratios.get(f"ratio_lag_{lag}", np.nan)
            print(f"    Sharpe(lag={lag}) = {s_lag:.4f}  "
                  f"→ Ratio = {r:.4f}" if not np.isnan(r) else "")
        if not np.isnan(slope):
            print(f"    Sharpe decay: {slope:.4f}/day (R² = {strategy_ratios.get('sharpe_decay_r2', 0):.3f})")

    return ratios


# ============================================================================
# Part 4: Smoothness → Robustness Relationship
# ============================================================================
def analyze_smoothness_robustness(smoothness_metrics, robustness_ratios):
    """Analyze the relationship between weight smoothness and lag robustness."""
    print("\n" + "=" * 70)
    print("PART 4: SMOOTHNESS → ROBUSTNESS RELATIONSHIP")
    print("=" * 70)

    # Collect paired data
    strategies = []
    autocorrs = []
    mean_abs_dws = []
    continuities = []
    robustness_1 = []
    turnovers = []

    for name in smoothness_metrics:
        if name in robustness_ratios:
            sm = smoothness_metrics[name]
            rb = robustness_ratios[name]

            r1 = rb.get("ratio_lag_1", np.nan)
            if np.isnan(r1):
                continue

            strategies.append(name)
            autocorrs.append(sm["weight_autocorrelation"])
            mean_abs_dws.append(sm["mean_abs_daily_change"])
            continuities.append(sm["continuity_score"])
            robustness_1.append(r1)
            turnovers.append(sm["annual_turnover"])

    results = {
        "strategies": strategies,
        "data_points": len(strategies),
    }

    if len(strategies) < 3:
        print("  Too few strategies for regression analysis")
        results["insufficient_data"] = True
        return results

    # Correlation: autocorr vs robustness
    corr_auto_rob, p_auto_rob = sp_stats.pearsonr(autocorrs, robustness_1)
    results["corr_autocorr_vs_robustness"] = round(corr_auto_rob, 4)
    results["pval_autocorr_vs_robustness"] = round(p_auto_rob, 4)

    # Correlation: mean |Δw| vs robustness (expected negative)
    corr_dw_rob, p_dw_rob = sp_stats.pearsonr(mean_abs_dws, robustness_1)
    results["corr_mean_abs_dw_vs_robustness"] = round(corr_dw_rob, 4)
    results["pval_mean_abs_dw_vs_robustness"] = round(p_dw_rob, 4)

    # Correlation: continuity vs robustness (expected positive)
    corr_cont_rob, p_cont_rob = sp_stats.pearsonr(continuities, robustness_1)
    results["corr_continuity_vs_robustness"] = round(corr_cont_rob, 4)
    results["pval_continuity_vs_robustness"] = round(p_cont_rob, 4)

    # Correlation: turnover vs robustness (expected negative)
    corr_turn_rob, p_turn_rob = sp_stats.pearsonr(turnovers, robustness_1)
    results["corr_turnover_vs_robustness"] = round(corr_turn_rob, 4)
    results["pval_turnover_vs_robustness"] = round(p_turn_rob, 4)

    # Rank correlation (Spearman) — more robust with 5 points
    spear_auto, sp_auto = sp_stats.spearmanr(autocorrs, robustness_1)
    results["spearman_autocorr_vs_robustness"] = round(spear_auto, 4)
    results["spearman_pval_autocorr_vs_robustness"] = round(sp_auto, 4)

    # Print summary table
    print(f"\n  {'Strategy':12s} | {'Autocorr':>9s} | {'Mean|Δw|':>10s} | {'Continuity':>10s} | {'Turnover':>10s} | {'Robust(L1)':>10s}")
    print(f"  {'-'*12}-+-{'-'*9}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}-+-{'-'*10}")
    for i, name in enumerate(strategies):
        print(f"  {name:12s} | {autocorrs[i]:9.4f} | {mean_abs_dws[i]:10.6f} | "
              f"{continuities[i]:10.4f} | {turnovers[i]:10.4f} | {robustness_1[i]:10.4f}")

    print(f"\n  Correlations with Lag Robustness Ratio (lag=1):")
    print(f"    Autocorr(w):     r={corr_auto_rob:+.4f} (p={p_auto_rob:.4f})"
          f"  Spearman={spear_auto:+.4f} (p={sp_auto:.4f})")
    print(f"    Mean |Δw|:       r={corr_dw_rob:+.4f} (p={p_dw_rob:.4f})")
    print(f"    Continuity:      r={corr_cont_rob:+.4f} (p={p_cont_rob:.4f})")
    print(f"    Turnover:        r={corr_turn_rob:+.4f} (p={p_turn_rob:.4f})")

    # Per-strategy detail
    results["per_strategy"] = {}
    for i, name in enumerate(strategies):
        results["per_strategy"][name] = {
            "autocorrelation": round(autocorrs[i], 4),
            "mean_abs_daily_change": round(mean_abs_dws[i], 6),
            "continuity_score": round(continuities[i], 4),
            "annual_turnover": round(turnovers[i], 4),
            "lag_robustness_ratio_L1": round(robustness_1[i], 4),
        }

    return results


# ============================================================================
# Part 5: Practical Implications
# ============================================================================
def practical_implications(smoothness_metrics, robustness_ratios, lag_results):
    """Summarize practical implications for retail investors."""
    print("\n" + "=" * 70)
    print("PART 5: PRACTICAL IMPLICATIONS FOR RETAIL INVESTORS")
    print("=" * 70)

    implications = {}

    # Rank strategies by lag robustness
    ranked = []
    for name in robustness_ratios:
        r1 = robustness_ratios[name].get("ratio_lag_1", np.nan)
        if not np.isnan(r1):
            # Also get lag=1 Sharpe (the "real" Sharpe)
            s1 = lag_results[name].get("lag_1", {}).get("sharpe", np.nan)
            s0 = lag_results[name].get("lag_0", {}).get("sharpe", np.nan)
            # Sharpe loss from lag
            sharpe_loss = s0 - s1 if not (np.isnan(s0) or np.isnan(s1)) else np.nan
            ranked.append({
                "strategy": name,
                "robustness_ratio": r1,
                "sharpe_lag0": s0,
                "sharpe_lag1": s1,
                "sharpe_loss": sharpe_loss,
            })

    ranked.sort(key=lambda x: x["robustness_ratio"], reverse=True)

    print(f"\n  Strategy Ranking by Lag Robustness:")
    print(f"  {'Rank':>4s} | {'Strategy':12s} | {'Robust':>7s} | {'S(lag=0)':>8s} | {'S(lag=1)':>8s} | {'S loss':>7s}")
    print(f"  {'-'*4}-+-{'-'*12}-+-{'-'*7}-+-{'-'*8}-+-{'-'*8}-+-{'-'*7}")

    for i, entry in enumerate(ranked, 1):
        print(f"  {i:4d} | {entry['strategy']:12s} | "
              f"{entry['robustness_ratio']:7.4f} | "
              f"{entry['sharpe_lag0']:8.4f} | "
              f"{entry['sharpe_lag1']:8.4f} | "
              f"{entry['sharpe_loss']:7.4f}")

    implications["ranking"] = ranked

    # Classify strategies
    robust = [e for e in ranked if e["robustness_ratio"] >= 0.90]
    moderate = [e for e in ranked if 0.70 <= e["robustness_ratio"] < 0.90]
    fragile = [e for e in ranked if e["robustness_ratio"] < 0.70]

    implications["categories"] = {
        "robust_geq_90pct": [e["strategy"] for e in robust],
        "moderate_70_90pct": [e["strategy"] for e in moderate],
        "fragile_lt_70pct": [e["strategy"] for e in fragile],
    }

    print(f"\n  Classification:")
    print(f"    Robust (≥90%):   {', '.join(e['strategy'] for e in robust) or 'none'}")
    print(f"    Moderate (70-90%): {', '.join(e['strategy'] for e in moderate) or 'none'}")
    print(f"    Fragile (<70%):  {', '.join(e['strategy'] for e in fragile) or 'none'}")

    # Best "practical" strategy: highest Sharpe(lag=1) among robust ones
    if robust:
        best_robust = max(robust, key=lambda x: x["sharpe_lag1"])
        implications["best_practical_strategy"] = best_robust["strategy"]
        print(f"\n  Best practical strategy (highest Sharpe among robust): "
              f"{best_robust['strategy']} (Sharpe={best_robust['sharpe_lag1']:.4f})")
    else:
        implications["best_practical_strategy"] = None
        print(f"\n  No strategy meets the 'robust' threshold")

    # Calculate: for lag=5 (e.g. weekly rebalancing), which strategies still work?
    print(f"\n  At lag=5 (weekly rebalancing):")
    for entry in ranked:
        s5 = lag_results[entry["strategy"]].get("lag_5", {}).get("sharpe", np.nan)
        if not np.isnan(s5):
            r5 = s5 / entry["sharpe_lag0"] if entry["sharpe_lag0"] != 0 else np.nan
            print(f"    {entry['strategy']:12s}: Sharpe={s5:.4f} "
                  f"(ratio={r5:.4f})")

    return implications


# ============================================================================
# Main
# ============================================================================
def main():
    start_time = datetime.now()

    # Download data
    data = download_data()

    # Compute raw (unlagged) weights
    raw_weights = compute_raw_weights(data)

    # Part 1: Weight smoothness metrics
    smoothness = compute_smoothness_metrics(raw_weights)

    # Part 2: Lag sensitivity backtest
    lag_results = lag_sensitivity_analysis(data, raw_weights)

    # Part 3: Lag robustness ratios
    robustness = compute_robustness_ratios(lag_results)

    # Part 4: Smoothness → Robustness relationship
    relationship = analyze_smoothness_robustness(smoothness, robustness)

    # Part 5: Practical implications
    implications = practical_implications(smoothness, robustness, lag_results)

    elapsed = (datetime.now() - start_time).total_seconds()

    # =============================================
    # Assemble results
    # =============================================
    results = {
        "experiment_id": "K690",
        "title": "Weight Smoothness and Lag Robustness — Why Simple Strategies Survive",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{EVAL_START} to {END_DATE}",
        "n_strategies": len(raw_weights),
        "lags_tested": LAGS,
        "tx_cost_bps": TC_BPS,
        "rf_annual": RF_ANNUAL,
        "ewma_lambda": EWMA_LAMBDA,
        "target_vol": TARGET_VOL,
        "elapsed_seconds": round(elapsed, 1),
        "smoothness_metrics": smoothness,
        "lag_sensitivity": lag_results,
        "robustness_ratios": robustness,
        "smoothness_robustness_relationship": relationship,
        "practical_implications": implications,
        "references": [
            "K687: Definitive lag-corrected strategy ranking",
            "K689: Live vs backtest discrepancy (lag sensitivity discovery)",
            "RiskMetrics (1996): EWMA λ=0.94",
            "Copeland & Copeland (1999): Market Timing with VIX",
            "Kirby & Ostdiek (2012): It's All in the Timing",
            "Harvey et al. (2016): ...and the Cross-Section of Expected Returns",
        ],
        "limitations": [
            "Only 5 strategies — correlation with 5 points has low statistical power",
            "Lag sensitivity does not account for intraday execution timing",
            "TC model is simplified (fixed 5bps), real costs vary with urgency",
            "VIX Percentile has fewer valid obs due to 252-day warmup",
            "Results are specific to US equity + gold; may differ for other assets",
        ],
    }

    # Save
    print(f"\n{'=' * 70}")
    print(f"SAVING RESULTS to {RESULTS_FILE}")
    print(f"{'=' * 70}")

    RESULTS_FILE.write_text(json.dumps(results, indent=2, default=str))
    print(f"  Saved. Elapsed: {elapsed:.1f}s")

    # Final summary
    print(f"\n{'=' * 70}")
    print(f"K690 FINAL SUMMARY")
    print(f"{'=' * 70}")

    print(f"\n  Key findings:")
    if "per_strategy" in relationship:
        for name, detail in sorted(
            relationship["per_strategy"].items(),
            key=lambda x: x[1]["lag_robustness_ratio_L1"],
            reverse=True
        ):
            ac = detail["autocorrelation"]
            lr = detail["lag_robustness_ratio_L1"]
            print(f"    {name:12s}: Autocorr={ac:.4f}, LagRobust={lr:.4f}")

    print(f"\n  Correlations:")
    if "corr_autocorr_vs_robustness" in relationship:
        print(f"    Autocorr(w) ↔ Robustness: r={relationship['corr_autocorr_vs_robustness']:+.4f}")
        print(f"    Mean|Δw| ↔ Robustness:    r={relationship['corr_mean_abs_dw_vs_robustness']:+.4f}")
        print(f"    Continuity ↔ Robustness:   r={relationship['corr_continuity_vs_robustness']:+.4f}")

    return results


if __name__ == "__main__":
    main()
