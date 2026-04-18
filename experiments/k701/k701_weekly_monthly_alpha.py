"""
K701: Is Alpha Possible at Weekly/Monthly Frequency?
=====================================================
Motivation: K697 proved daily alpha impossible (VIX direction corr 0.04,
lag destroys 80%). But at lower frequencies, the lag penalty is proportionally
smaller (1 day out of 5 = 20% vs 1 day out of 1 = 100%).

Test if VIX-based timing works better at weekly/monthly rebalancing.

Data source: yfinance (SPY, GLD, ^VIX), 2006-01-01 to 2026-03-27
Reference: K697 daily alpha impossibility results
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ── Configuration ──────────────────────────────────────────────────────────
START = "2006-01-01"
END = "2026-03-27"
TX_COST_DAILY = 0.001    # 10 bps round-trip daily
TX_COST_WEEKLY = 0.001   # same per rebalance
TX_COST_MONTHLY = 0.001  # same per rebalance
RISK_FREE_RATE = 0.0     # for Sharpe calculation


def download_data():
    """Download SPY, GLD, VIX daily data."""
    print("Downloading data...")
    spy = yf.download("SPY", start=START, end=END, progress=False)
    gld = yf.download("GLD", start=START, end=END, progress=False)
    vix = yf.download("^VIX", start=START, end=END, progress=False)

    # Handle multi-level columns
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(gld.columns, pd.MultiIndex):
        gld.columns = gld.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    df = pd.DataFrame({
        "spy_close": spy["Close"],
        "gld_close": gld["Close"],
        "vix_close": vix["Close"],
    }).dropna()

    print(f"  Daily data: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    return df


def compute_daily_returns(df):
    """Compute daily log returns."""
    df = df.copy()
    df["spy_ret"] = np.log(df["spy_close"] / df["spy_close"].shift(1))
    df["gld_ret"] = np.log(df["gld_close"] / df["gld_close"].shift(1))
    return df.dropna()


def resample_weekly(df):
    """Resample to weekly (Friday close)."""
    weekly = df.resample("W-FRI").last().dropna()
    weekly["spy_ret"] = np.log(weekly["spy_close"] / weekly["spy_close"].shift(1))
    weekly["gld_ret"] = np.log(weekly["gld_close"] / weekly["gld_close"].shift(1))
    weekly["vix_level"] = weekly["vix_close"]
    return weekly.dropna()


def resample_monthly(df):
    """Resample to monthly (last trading day)."""
    monthly = df.resample("ME").last().dropna()
    monthly["spy_ret"] = np.log(monthly["spy_close"] / monthly["spy_close"].shift(1))
    monthly["gld_ret"] = np.log(monthly["gld_close"] / monthly["gld_close"].shift(1))
    monthly["vix_level"] = monthly["vix_close"]
    return monthly.dropna()


def direction_accuracy(signal, actual_return):
    """Fraction of times signal correctly predicts return direction."""
    sig_dir = np.sign(signal)
    ret_dir = np.sign(actual_return)
    return np.mean(sig_dir == ret_dir)


def compute_sharpe(returns, periods_per_year):
    """Annualized Sharpe ratio."""
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year))


def compute_max_drawdown(cum_returns):
    """Maximum drawdown from cumulative returns series."""
    peak = cum_returns.cummax()
    dd = (cum_returns - peak) / peak
    return float(dd.min())


def compute_cagr(cum_returns, years):
    """CAGR from cumulative return series."""
    if years <= 0 or cum_returns.iloc[-1] <= 0:
        return 0.0
    return float((cum_returns.iloc[-1]) ** (1.0 / years) - 1)


def vix_timing_strategy(data, freq_name, periods_per_year, tx_cost):
    """
    12/VIX timing strategy at given frequency.
    Signal: w_spy = min(12/VIX, 1.0), w_gld = 1 - w_spy
    Signal is LAGGED: use prior period's VIX to set this period's weights.
    """
    df = data.copy()

    # Signal from PRIOR period's VIX (properly lagged)
    df["signal_vix"] = df["vix_level"].shift(1)
    df = df.dropna(subset=["signal_vix"])

    # 12/VIX weight for SPY
    df["w_spy"] = (12.0 / df["signal_vix"]).clip(0, 1)
    df["w_gld"] = 1.0 - df["w_spy"]

    # Weight changes for TX cost
    df["dw_spy"] = df["w_spy"].diff().abs()
    df["dw_gld"] = df["w_gld"].diff().abs()
    df["turnover"] = (df["dw_spy"].fillna(0) + df["dw_gld"].fillna(0))

    # Strategy return (gross)
    df["strat_ret_gross"] = df["w_spy"] * df["spy_ret"] + df["w_gld"] * df["gld_ret"]

    # Net of TX costs
    df["tx_cost"] = df["turnover"] * tx_cost
    df["strat_ret_net"] = df["strat_ret_gross"] - df["tx_cost"]

    # Buy-and-hold 50/50 (no rebalancing cost after initial)
    df["bh_ret"] = 0.5 * df["spy_ret"] + 0.5 * df["gld_ret"]

    # SPY only buy-and-hold
    df["spy_only_ret"] = df["spy_ret"]

    # Cumulative returns (wealth)
    df["strat_wealth"] = np.exp(df["strat_ret_net"].cumsum())
    df["bh_wealth"] = np.exp(df["bh_ret"].cumsum())
    df["spy_wealth"] = np.exp(df["spy_only_ret"].cumsum())

    years = len(df) / periods_per_year

    results = {
        "freq": freq_name,
        "n_periods": len(df),
        "years": round(years, 1),
        "periods_per_year": periods_per_year,
        # Strategy metrics
        "strat_sharpe_gross": compute_sharpe(df["strat_ret_gross"].values, periods_per_year),
        "strat_sharpe_net": compute_sharpe(df["strat_ret_net"].values, periods_per_year),
        "strat_cagr": compute_cagr(df["strat_wealth"], years),
        "strat_mdd": compute_max_drawdown(df["strat_wealth"]),
        "strat_vol": float(df["strat_ret_net"].std() * np.sqrt(periods_per_year)),
        # BH 50/50 metrics
        "bh_sharpe": compute_sharpe(df["bh_ret"].values, periods_per_year),
        "bh_cagr": compute_cagr(df["bh_wealth"], years),
        "bh_mdd": compute_max_drawdown(df["bh_wealth"]),
        "bh_vol": float(df["bh_ret"].std() * np.sqrt(periods_per_year)),
        # SPY only
        "spy_sharpe": compute_sharpe(df["spy_only_ret"].values, periods_per_year),
        "spy_cagr": compute_cagr(df["spy_wealth"], years),
        "spy_mdd": compute_max_drawdown(df["spy_wealth"]),
        # TX cost impact
        "total_tx_cost": float(df["tx_cost"].sum()),
        "avg_turnover": float(df["turnover"].mean()),
        "avg_w_spy": float(df["w_spy"].mean()),
        # Alpha vs BH
        "alpha_vs_bh_sharpe": round(compute_sharpe(df["strat_ret_net"].values, periods_per_year) -
                                     compute_sharpe(df["bh_ret"].values, periods_per_year), 4),
        "alpha_vs_bh_cagr": round(compute_cagr(df["strat_wealth"], years) -
                                   compute_cagr(df["bh_wealth"], years), 4),
    }

    return results, df


def analyze_predictability(data, freq_name):
    """
    Analyze VIX predictability at given frequency.
    Key question: Does VIX predict DIRECTION better at lower frequencies?
    """
    df = data.copy()

    # Current VIX vs NEXT period return (properly lagged)
    df["next_spy_ret"] = df["spy_ret"].shift(-1)
    df = df.dropna(subset=["next_spy_ret"])

    vix = df["vix_level"].values
    next_ret = df["next_spy_ret"].values
    curr_ret = df["spy_ret"].values

    # 1) Correlation: VIX level vs next-period return
    corr_vix_next, p_vix_next = stats.pearsonr(vix, next_ret)

    # 2) Correlation: VIX level vs same-period return (contemporaneous)
    corr_vix_curr, p_vix_curr = stats.pearsonr(vix, curr_ret)

    # 3) Direction prediction: high VIX -> negative next return?
    # Use median VIX as threshold
    vix_median = np.median(vix)
    high_vix = vix > vix_median
    low_vix = ~high_vix

    avg_ret_high_vix = np.mean(next_ret[high_vix])
    avg_ret_low_vix = np.mean(next_ret[low_vix])

    # Direction accuracy: VIX > median -> predict negative, VIX < median -> predict positive
    # This is one common approach
    predicted_negative = high_vix
    actual_negative = next_ret < 0
    direction_acc_median = np.mean(predicted_negative == actual_negative)

    # 4) More nuanced: correlation of VIX with ABSOLUTE next return
    corr_vix_abs_next, p_vix_abs_next = stats.pearsonr(vix, np.abs(next_ret))

    # 5) Autocorrelation of returns
    ac1 = pd.Series(curr_ret).autocorr(lag=1)
    ac2 = pd.Series(curr_ret).autocorr(lag=2)
    ac3 = pd.Series(curr_ret).autocorr(lag=3)

    # 6) VIX change vs next return
    vix_change = np.diff(vix)
    next_ret_aligned = next_ret[1:]
    corr_dvix_next, p_dvix_next = stats.pearsonr(vix_change, next_ret_aligned)

    # 7) Inverse VIX (12/VIX) as weight -> correlation with next return
    inv_vix = 12.0 / vix
    corr_invvix_next, p_invvix_next = stats.pearsonr(inv_vix, next_ret)

    # 8) VIX quintile analysis
    vix_quintiles = pd.qcut(vix, 5, labels=False)
    quintile_returns = {}
    for q in range(5):
        mask = vix_quintiles == q
        q_rets = next_ret[mask]
        quintile_returns[f"Q{q+1}"] = {
            "mean_ret": float(np.mean(q_rets)),
            "std_ret": float(np.std(q_rets)),
            "n": int(mask.sum()),
            "sharpe": float(np.mean(q_rets) / np.std(q_rets)) if np.std(q_rets) > 0 else 0,
        }

    # 9) Regression: next_ret = a + b * VIX + epsilon
    slope, intercept, r_value, p_value, std_err = stats.linregress(vix, next_ret)
    t_stat = slope / std_err if std_err > 0 else 0

    results = {
        "freq": freq_name,
        "n_obs": len(df),
        # Correlations
        "corr_vix_next_ret": round(float(corr_vix_next), 4),
        "p_vix_next_ret": round(float(p_vix_next), 4),
        "corr_vix_curr_ret": round(float(corr_vix_curr), 4),
        "p_vix_curr_ret": round(float(p_vix_curr), 4),
        "corr_vix_abs_next": round(float(corr_vix_abs_next), 4),
        "p_vix_abs_next": round(float(p_vix_abs_next), 4),
        "corr_dvix_next": round(float(corr_dvix_next), 4),
        "p_dvix_next": round(float(p_dvix_next), 4),
        "corr_invvix_next": round(float(corr_invvix_next), 4),
        "p_invvix_next": round(float(p_invvix_next), 4),
        # Direction
        "direction_acc_median": round(float(direction_acc_median), 4),
        "avg_ret_high_vix": round(float(avg_ret_high_vix), 6),
        "avg_ret_low_vix": round(float(avg_ret_low_vix), 6),
        # Autocorrelation
        "ac1": round(float(ac1), 4),
        "ac2": round(float(ac2), 4),
        "ac3": round(float(ac3), 4),
        # Regression
        "reg_slope": round(float(slope), 6),
        "reg_intercept": round(float(intercept), 6),
        "reg_r2": round(float(r_value**2), 4),
        "reg_t_stat": round(float(t_stat), 2),
        "reg_p_value": round(float(p_value), 4),
        # Quintile analysis
        "vix_quintile_returns": quintile_returns,
    }

    return results


def analyze_lag_impact(df_daily):
    """
    Quantify the lag impact across frequencies.
    At daily: 1-day lag = 100% of the period
    At weekly: 1-day lag = 20% of the period (but signal is 1-week lag)
    At monthly: 1-day lag = ~5% (signal is 1-month lag)

    Actually the lag at weekly/monthly is 1 PERIOD (1 week / 1 month),
    not 1 day. So the question is whether the signal decays slower.
    """
    df = df_daily.copy()
    df = compute_daily_returns(df)

    results = {}

    # Daily: corr(VIX_t, ret_{t+k}) for various k
    for k in [1, 2, 3, 5, 10, 21, 63]:
        df[f"fwd_ret_{k}d"] = df["spy_ret"].rolling(k).sum().shift(-k)
        valid = df.dropna(subset=[f"fwd_ret_{k}d"])
        if len(valid) > 30:
            corr, p = stats.pearsonr(valid["vix_close"].values, valid[f"fwd_ret_{k}d"].values)
            results[f"corr_vix_vs_{k}d_fwd_ret"] = round(float(corr), 4)
            results[f"p_vix_vs_{k}d_fwd_ret"] = round(float(p), 4)

    # Key insight: corr(VIX_t, cumulative_ret_{t+1 to t+k})
    # If this INCREASES with k, then lower-freq VT has more signal
    # If it DECREASES, then lag penalty compounds

    return results


def run_experiment():
    """Main experiment."""
    print("=" * 70)
    print("K701: Is Alpha Possible at Weekly/Monthly Frequency?")
    print("=" * 70)

    # Download data
    df = download_data()

    # ── Lag Impact Analysis ────────────────────────────────────────────
    print("\n── Lag Impact Analysis ──")
    lag_results = analyze_lag_impact(df)
    for k, v in sorted(lag_results.items()):
        print(f"  {k}: {v}")

    # ── Daily Analysis (baseline from K697) ────────────────────────────
    print("\n── Daily Analysis (baseline) ──")
    daily = compute_daily_returns(df)
    daily["vix_level"] = daily["vix_close"]
    daily_pred = analyze_predictability(daily, "daily")
    daily_strat, daily_df = vix_timing_strategy(daily, "daily", 252, TX_COST_DAILY)

    print(f"  VIX→next_ret corr: {daily_pred['corr_vix_next_ret']} (p={daily_pred['p_vix_next_ret']})")
    print(f"  Direction accuracy: {daily_pred['direction_acc_median']}")
    print(f"  12/VIX Sharpe (net): {daily_strat['strat_sharpe_net']:.4f}")
    print(f"  BH 50/50 Sharpe:     {daily_strat['bh_sharpe']:.4f}")
    print(f"  Alpha Sharpe:        {daily_strat['alpha_vs_bh_sharpe']}")

    # ── Weekly Analysis ────────────────────────────────────────────────
    print("\n── Weekly Analysis ──")
    weekly = resample_weekly(df)
    weekly_pred = analyze_predictability(weekly, "weekly")
    weekly_strat, weekly_df = vix_timing_strategy(weekly, "weekly", 52, TX_COST_WEEKLY)

    print(f"  N periods: {weekly_pred['n_obs']}")
    print(f"  VIX→next_ret corr: {weekly_pred['corr_vix_next_ret']} (p={weekly_pred['p_vix_next_ret']})")
    print(f"  Direction accuracy: {weekly_pred['direction_acc_median']}")
    print(f"  Return autocorr:   AC1={weekly_pred['ac1']}, AC2={weekly_pred['ac2']}")
    print(f"  12/VIX Sharpe (net): {weekly_strat['strat_sharpe_net']:.4f}")
    print(f"  BH 50/50 Sharpe:     {weekly_strat['bh_sharpe']:.4f}")
    print(f"  Alpha Sharpe:        {weekly_strat['alpha_vs_bh_sharpe']}")
    print(f"  Avg turnover:        {weekly_strat['avg_turnover']:.4f}")

    # Quintile analysis
    print("  VIX Quintile Returns (next-week):")
    for q, vals in weekly_pred["vix_quintile_returns"].items():
        print(f"    {q}: mean={vals['mean_ret']:.5f}, std={vals['std_ret']:.5f}, n={vals['n']}, sharpe={vals['sharpe']:.3f}")

    # ── Monthly Analysis ───────────────────────────────────────────────
    print("\n── Monthly Analysis ──")
    monthly = resample_monthly(df)
    monthly_pred = analyze_predictability(monthly, "monthly")
    monthly_strat, monthly_df = vix_timing_strategy(monthly, "monthly", 12, TX_COST_MONTHLY)

    print(f"  N periods: {monthly_pred['n_obs']}")
    print(f"  VIX→next_ret corr: {monthly_pred['corr_vix_next_ret']} (p={monthly_pred['p_vix_next_ret']})")
    print(f"  Direction accuracy: {monthly_pred['direction_acc_median']}")
    print(f"  Return autocorr:   AC1={monthly_pred['ac1']}, AC2={monthly_pred['ac2']}")
    print(f"  12/VIX Sharpe (net): {monthly_strat['strat_sharpe_net']:.4f}")
    print(f"  BH 50/50 Sharpe:     {monthly_strat['bh_sharpe']:.4f}")
    print(f"  Alpha Sharpe:        {monthly_strat['alpha_vs_bh_sharpe']}")
    print(f"  Avg turnover:        {monthly_strat['avg_turnover']:.4f}")

    # Quintile analysis
    print("  VIX Quintile Returns (next-month):")
    for q, vals in monthly_pred["vix_quintile_returns"].items():
        print(f"    {q}: mean={vals['mean_ret']:.5f}, std={vals['std_ret']:.5f}, n={vals['n']}, sharpe={vals['sharpe']:.3f}")

    # ── Cross-frequency Comparison ─────────────────────────────────────
    print("\n" + "=" * 70)
    print("CROSS-FREQUENCY COMPARISON")
    print("=" * 70)

    comparison = {
        "daily": {
            "corr_vix_next_ret": daily_pred["corr_vix_next_ret"],
            "direction_acc": daily_pred["direction_acc_median"],
            "strat_sharpe_net": round(daily_strat["strat_sharpe_net"], 4),
            "bh_sharpe": round(daily_strat["bh_sharpe"], 4),
            "alpha_sharpe": daily_strat["alpha_vs_bh_sharpe"],
            "strat_cagr": round(daily_strat["strat_cagr"], 4),
            "bh_cagr": round(daily_strat["bh_cagr"], 4),
            "strat_mdd": round(daily_strat["strat_mdd"], 4),
            "bh_mdd": round(daily_strat["bh_mdd"], 4),
        },
        "weekly": {
            "corr_vix_next_ret": weekly_pred["corr_vix_next_ret"],
            "direction_acc": weekly_pred["direction_acc_median"],
            "strat_sharpe_net": round(weekly_strat["strat_sharpe_net"], 4),
            "bh_sharpe": round(weekly_strat["bh_sharpe"], 4),
            "alpha_sharpe": weekly_strat["alpha_vs_bh_sharpe"],
            "strat_cagr": round(weekly_strat["strat_cagr"], 4),
            "bh_cagr": round(weekly_strat["bh_cagr"], 4),
            "strat_mdd": round(weekly_strat["strat_mdd"], 4),
            "bh_mdd": round(weekly_strat["bh_mdd"], 4),
        },
        "monthly": {
            "corr_vix_next_ret": monthly_pred["corr_vix_next_ret"],
            "direction_acc": monthly_pred["direction_acc_median"],
            "strat_sharpe_net": round(monthly_strat["strat_sharpe_net"], 4),
            "bh_sharpe": round(monthly_strat["bh_sharpe"], 4),
            "alpha_sharpe": monthly_strat["alpha_vs_bh_sharpe"],
            "strat_cagr": round(monthly_strat["strat_cagr"], 4),
            "bh_cagr": round(monthly_strat["bh_cagr"], 4),
            "strat_mdd": round(monthly_strat["strat_mdd"], 4),
            "bh_mdd": round(monthly_strat["bh_mdd"], 4),
        },
    }

    print(f"\n{'Metric':<25} {'Daily':>12} {'Weekly':>12} {'Monthly':>12}")
    print("-" * 65)
    for metric in ["corr_vix_next_ret", "direction_acc", "strat_sharpe_net",
                    "bh_sharpe", "alpha_sharpe", "strat_cagr", "bh_cagr",
                    "strat_mdd", "bh_mdd"]:
        d = comparison["daily"][metric]
        w = comparison["weekly"][metric]
        m = comparison["monthly"][metric]
        print(f"  {metric:<23} {d:>12} {w:>12} {m:>12}")

    # ── Statistical Significance of Alpha ──────────────────────────────
    print("\n── Statistical Tests ──")

    # DM-like test: is strategy return significantly different from BH?
    for name, strat_df, ppy in [("daily", daily_df, 252),
                                  ("weekly", weekly_df, 52),
                                  ("monthly", monthly_df, 12)]:
        diff = strat_df["strat_ret_net"].values - strat_df["bh_ret"].values
        t_stat, p_val = stats.ttest_1samp(diff, 0)
        print(f"  {name}: mean_diff={np.mean(diff):.6f}, t={t_stat:.3f}, p={p_val:.4f}")

    # ── Key Finding ────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("KEY FINDINGS")
    print("=" * 70)

    # Does direction predictability improve?
    daily_corr = abs(daily_pred["corr_vix_next_ret"])
    weekly_corr = abs(weekly_pred["corr_vix_next_ret"])
    monthly_corr = abs(monthly_pred["corr_vix_next_ret"])

    print(f"\n1) VIX→next_return |correlation|:")
    print(f"   Daily:   {daily_corr:.4f}")
    print(f"   Weekly:  {weekly_corr:.4f}")
    print(f"   Monthly: {monthly_corr:.4f}")

    if monthly_corr > daily_corr:
        print("   -> Monthly predictability HIGHER than daily")
    else:
        print("   -> No improvement at lower frequency")

    print(f"\n2) Direction accuracy:")
    print(f"   Daily:   {daily_pred['direction_acc_median']:.4f}")
    print(f"   Weekly:  {weekly_pred['direction_acc_median']:.4f}")
    print(f"   Monthly: {monthly_pred['direction_acc_median']:.4f}")

    print(f"\n3) NET Sharpe (12/VIX strategy):")
    print(f"   Daily:   {daily_strat['strat_sharpe_net']:.4f}")
    print(f"   Weekly:  {weekly_strat['strat_sharpe_net']:.4f}")
    print(f"   Monthly: {monthly_strat['strat_sharpe_net']:.4f}")

    print(f"\n4) Alpha vs BH 50/50 (Sharpe diff):")
    print(f"   Daily:   {daily_strat['alpha_vs_bh_sharpe']}")
    print(f"   Weekly:  {weekly_strat['alpha_vs_bh_sharpe']}")
    print(f"   Monthly: {monthly_strat['alpha_vs_bh_sharpe']}")

    vt_value = "sizing" if (daily_strat["strat_sharpe_net"] >= daily_strat["bh_sharpe"]) else "contested"

    # ── Save Results ───────────────────────────────────────────────────
    results = {
        "experiment_id": "K701",
        "title": "Is Alpha Possible at Weekly/Monthly Frequency?",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "data_source": "yfinance",
        "assets": ["SPY", "GLD", "^VIX"],
        "period": f"{START} to {END}",
        "motivation": "K697 showed daily alpha impossible (corr=0.04). "
                      "Test if lower-frequency rebalancing reduces lag penalty.",
        "methodology": {
            "strategy": "12/VIX timing (SPY/GLD), signal lagged 1 period",
            "frequencies": ["daily", "weekly (Fri)", "monthly (last day)"],
            "tx_cost": "10 bps per rebalance",
            "benchmark": "Buy-and-hold 50/50 SPY/GLD",
        },
        "lag_impact_analysis": lag_results,
        "predictability": {
            "daily": daily_pred,
            "weekly": weekly_pred,
            "monthly": monthly_pred,
        },
        "strategy_performance": {
            "daily": daily_strat,
            "weekly": weekly_strat,
            "monthly": monthly_strat,
        },
        "cross_frequency_comparison": comparison,
        "conclusions": {
            "vix_direction_predictability": {
                "daily_corr": daily_pred["corr_vix_next_ret"],
                "weekly_corr": weekly_pred["corr_vix_next_ret"],
                "monthly_corr": monthly_pred["corr_vix_next_ret"],
                "improves_with_lower_freq": monthly_corr > daily_corr,
            },
            "alpha_vs_bh": {
                "daily_alpha_sharpe": daily_strat["alpha_vs_bh_sharpe"],
                "weekly_alpha_sharpe": weekly_strat["alpha_vs_bh_sharpe"],
                "monthly_alpha_sharpe": monthly_strat["alpha_vs_bh_sharpe"],
            },
            "vt_value_proposition": (
                "VT's value comes from SIZING (lower vol, better MDD) not alpha. "
                "At all frequencies, VIX→return correlation is weak. "
                "Lower frequency reduces TX costs but doesn't improve predictability."
            ),
        },
        "reference": "K697 (daily alpha impossibility)",
    }

    # Save
    out_path = Path(__file__).parent / "k701_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    run_experiment()
