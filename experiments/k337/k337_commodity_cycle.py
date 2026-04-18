"""
K337: Commodity Super-Cycle and Equity Volatility
==================================================

Hypothesis:
  Commodity prices move in ~20-year "super-cycles". When commodity prices
  surge (inflation), equity vol tends to rise. Can commodity ETF signals
  predict equity vol and improve portfolio allocation?

Signals:
  1. DBC 12-month return (commodity super-cycle momentum indicator)
  2. USO/SPY ratio (energy's share of economy)
  3. Copper/Gold ratio (risk appetite: copper=growth, gold=fear)

Tests:
  A. Partial correlation: commodity signals vs future 22d SPY RV, controlling for VIX
  B. Commodity regime portfolio: overweight GLD when commodities surging
  C. 40/40/20 SPY+GLD+DBC vs 50/50 SPY+GLD benchmark

Data: yfinance (real data only). OOS: 2020-01 to 2025-12.
All results from actual computations. No fabricated numbers.

[提出: 用戶 (K337 commodity super-cycle), 執行: Claude]
"""

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# CONFIG
# ============================================================
DATA_START = "2007-01-01"  # DBC inception ~2006, use 2007 for safety
DATA_END = "2026-12-31"
OOS_START = "2020-01-01"
OOS_END = "2025-12-31"
MOMENTUM_WINDOW = 252  # 12-month return
RV_WINDOW = 22  # 22-day realized vol
REBAL_FREQ = "M"  # monthly rebalance

TICKERS = {
    "SPY": "SPY",
    "GLD": "GLD",
    "DBC": "DBC",   # Invesco DB Commodity Index
    "USO": "USO",   # US Oil Fund
    "CPER": "CPER", # Copper ETF
}

VIX_TICKER = "^VIX"

print("=" * 80)
print("K337: COMMODITY SUPER-CYCLE AND EQUITY VOLATILITY")
print("Can commodity momentum predict equity vol & improve allocation?")
print("=" * 80)


# ============================================================
# DATA DOWNLOAD
# ============================================================
def download_data():
    """Download all required price data from yfinance."""
    print("\n[1] Downloading data from yfinance...")

    all_data = {}
    for name, ticker in TICKERS.items():
        print(f"  Downloading {name} ({ticker})...", end=" ")
        df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False, auto_adjust=True)
        if df.empty:
            print("FAILED - no data")
            continue
        # Handle MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        all_data[name] = df["Close"].squeeze()
        print(f"OK ({len(df)} obs, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

    # VIX
    print(f"  Downloading VIX ({VIX_TICKER})...", end=" ")
    vix_df = yf.download(VIX_TICKER, start=DATA_START, end=DATA_END, progress=False, auto_adjust=True)
    if isinstance(vix_df.columns, pd.MultiIndex):
        vix_df.columns = vix_df.columns.get_level_values(0)
    all_data["VIX"] = vix_df["Close"].squeeze()
    print(f"OK ({len(vix_df)} obs)")

    # Combine into DataFrame
    prices = pd.DataFrame(all_data)
    prices = prices.ffill().dropna()
    print(f"\n  Combined dataset: {len(prices)} trading days")
    print(f"  Date range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

    return prices


# ============================================================
# SIGNAL CONSTRUCTION
# ============================================================
def build_signals(prices):
    """Build commodity momentum signals."""
    print("\n[2] Building commodity signals...")

    signals = pd.DataFrame(index=prices.index)

    # Signal 1: DBC 12-month return (commodity super-cycle indicator)
    signals["dbc_mom_12m"] = prices["DBC"].pct_change(MOMENTUM_WINDOW)

    # Signal 2: USO/SPY ratio (energy's share of economy)
    signals["uso_spy_ratio"] = prices["USO"] / prices["SPY"]
    # Use 12-month change of the ratio
    signals["uso_spy_ratio_chg"] = signals["uso_spy_ratio"].pct_change(MOMENTUM_WINDOW)

    # Signal 3: Copper/Gold ratio (risk appetite)
    signals["copper_gold_ratio"] = prices["CPER"] / prices["GLD"]
    # Use 12-month change
    signals["copper_gold_ratio_chg"] = signals["copper_gold_ratio"].pct_change(MOMENTUM_WINDOW)

    # Composite: average z-score of all 3 signals
    for col in ["dbc_mom_12m", "uso_spy_ratio_chg", "copper_gold_ratio_chg"]:
        roll_mean = signals[col].expanding(min_periods=MOMENTUM_WINDOW).mean()
        roll_std = signals[col].expanding(min_periods=MOMENTUM_WINDOW).std()
        signals[f"{col}_z"] = (signals[col] - roll_mean) / roll_std

    signals["composite_z"] = signals[["dbc_mom_12m_z", "uso_spy_ratio_chg_z", "copper_gold_ratio_chg_z"]].mean(axis=1)

    # VIX level
    signals["vix"] = prices["VIX"]

    # Future 22d SPY realized volatility (target variable)
    spy_ret = np.log(prices["SPY"] / prices["SPY"].shift(1))
    signals["spy_rv_22d"] = spy_ret.rolling(RV_WINDOW).std() * np.sqrt(252)
    # Shift forward: we want FUTURE RV
    signals["spy_rv_22d_future"] = signals["spy_rv_22d"].shift(-RV_WINDOW)

    # Current RV (for comparison)
    signals["spy_rv_22d_current"] = signals["spy_rv_22d"]

    signals = signals.dropna()
    print(f"  Signals computed: {len(signals)} obs with complete data")
    print(f"  Date range: {signals.index[0].strftime('%Y-%m-%d')} to {signals.index[-1].strftime('%Y-%m-%d')}")

    return signals, spy_ret


def partial_correlation(x, y, z):
    """
    Partial correlation between x and y, controlling for z.
    Uses residual method: regress x on z, regress y on z, correlate residuals.
    """
    # Remove NaN
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    n = len(x)
    if n < 30:
        return np.nan, np.nan, n

    # Residualize
    slope_xz, intercept_xz, _, _, _ = stats.linregress(z, x)
    resid_x = x - (intercept_xz + slope_xz * z)

    slope_yz, intercept_yz, _, _, _ = stats.linregress(z, y)
    resid_y = y - (intercept_yz + slope_yz * z)

    # Correlate residuals
    r, p = stats.pearsonr(resid_x, resid_y)

    # Also compute t-stat
    t = r * np.sqrt((n - 3) / (1 - r**2)) if abs(r) < 1 else np.inf

    return r, p, n


# ============================================================
# TEST A: PREDICTIVE POWER FOR EQUITY VOL
# ============================================================
def test_vol_prediction(signals):
    """Test if commodity signals predict future SPY realized vol."""
    print("\n" + "=" * 80)
    print("TEST A: COMMODITY SIGNALS → FUTURE SPY REALIZED VOL")
    print("Partial correlation controlling for current VIX")
    print("=" * 80)

    oos_mask = (signals.index >= OOS_START) & (signals.index <= OOS_END)
    full_mask = np.ones(len(signals), dtype=bool)

    signal_cols = [
        ("DBC 12m Return", "dbc_mom_12m"),
        ("USO/SPY Ratio Chg", "uso_spy_ratio_chg"),
        ("Copper/Gold Ratio Chg", "copper_gold_ratio_chg"),
        ("Composite Z-Score", "composite_z"),
    ]

    results_a = {}

    for period_name, mask in [("Full Sample", full_mask), ("OOS (2020-2025)", oos_mask)]:
        print(f"\n--- {period_name} ---")
        print(f"{'Signal':<25} {'Partial r':>10} {'t-stat':>8} {'p-value':>10} {'N':>6} {'Significant':>12}")
        print("-" * 75)

        for sig_name, sig_col in signal_cols:
            subset = signals[mask]
            r, p, n = partial_correlation(
                subset[sig_col].values,
                subset["spy_rv_22d_future"].values,
                subset["vix"].values,
            )
            t = r * np.sqrt((n - 3) / (1 - r**2)) if abs(r) < 1 and n > 3 else np.nan
            sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
            print(f"{sig_name:<25} {r:>10.4f} {t:>8.2f} {p:>10.4f} {n:>6d} {sig:>12}")

            results_a[f"{period_name}_{sig_col}"] = {
                "partial_r": round(r, 4) if not np.isnan(r) else None,
                "t_stat": round(t, 2) if not np.isnan(t) else None,
                "p_value": round(p, 4) if not np.isnan(p) else None,
                "n": int(n),
                "period": period_name,
            }

    # Also test raw correlation (without controlling for VIX)
    print(f"\n--- Raw Correlation (no VIX control) - OOS ---")
    print(f"{'Signal':<25} {'Raw r':>10} {'p-value':>10} {'N':>6}")
    print("-" * 55)
    subset = signals[oos_mask]
    for sig_name, sig_col in signal_cols:
        vals = subset[[sig_col, "spy_rv_22d_future"]].dropna()
        r, p = stats.pearsonr(vals[sig_col], vals["spy_rv_22d_future"])
        print(f"{sig_name:<25} {r:>10.4f} {p:>10.4f} {len(vals):>6d}")

    return results_a


# ============================================================
# TEST B: COMMODITY REGIME PORTFOLIO
# ============================================================
def test_commodity_regime_portfolio(prices, signals):
    """
    When commodities are surging (DBC momentum > 0), overweight GLD.
    Compare to static 50/50 SPY/GLD.
    """
    print("\n" + "=" * 80)
    print("TEST B: COMMODITY REGIME PORTFOLIO ALLOCATION")
    print("Commodity surge → overweight GLD (inflation hedge)")
    print("=" * 80)

    # Monthly returns
    spy_monthly = prices["SPY"].resample("ME").last().pct_change()
    gld_monthly = prices["GLD"].resample("ME").last().pct_change()
    dbc_monthly = prices["DBC"].resample("ME").last().pct_change()

    # DBC 12-month momentum (monthly, lagged 1 month to avoid look-ahead)
    dbc_12m_mom = prices["DBC"].resample("ME").last().pct_change(12).shift(1)

    # Copper/Gold ratio momentum (monthly, lagged)
    cg_ratio = (prices["CPER"] / prices["GLD"]).resample("ME").last()
    cg_ratio_12m = cg_ratio.pct_change(12).shift(1)

    # Align all
    combined = pd.DataFrame({
        "spy_ret": spy_monthly,
        "gld_ret": gld_monthly,
        "dbc_ret": dbc_monthly,
        "dbc_mom": dbc_12m_mom,
        "cg_mom": cg_ratio_12m,
    }).dropna()

    # OOS filter
    oos = combined[combined.index >= OOS_START]
    print(f"\n  OOS period: {oos.index[0].strftime('%Y-%m')} to {oos.index[-1].strftime('%Y-%m')} ({len(oos)} months)")

    # Strategy definitions
    strategies = {}

    # 1. Static 50/50 SPY/GLD (benchmark)
    strategies["50/50 SPY+GLD (static)"] = 0.50 * oos["spy_ret"] + 0.50 * oos["gld_ret"]

    # 2. Commodity regime: when DBC mom > 0 (commodities rising), shift to 30/70 SPY/GLD
    #    When DBC mom <= 0, use 70/30 SPY/GLD
    w_spy_regime = np.where(oos["dbc_mom"] > 0, 0.30, 0.70)
    w_gld_regime = 1 - w_spy_regime
    strategies["Regime: DBC Mom"] = w_spy_regime * oos["spy_ret"] + w_gld_regime * oos["gld_ret"]

    # 3. Copper/Gold regime: when CG ratio falling (risk-off), overweight GLD
    w_spy_cg = np.where(oos["cg_mom"] > 0, 0.70, 0.30)
    w_gld_cg = 1 - w_spy_cg
    strategies["Regime: Cu/Au Ratio"] = w_spy_cg * oos["spy_ret"] + w_gld_cg * oos["gld_ret"]

    # 4. Combined: DBC mom > 0 AND CG ratio falling → max GLD
    inflation_signal = (oos["dbc_mom"] > 0).astype(int)
    riskoff_signal = (oos["cg_mom"] < 0).astype(int)
    combined_signal = inflation_signal + riskoff_signal  # 0, 1, or 2
    w_spy_combined = np.where(combined_signal == 2, 0.20,
                     np.where(combined_signal == 1, 0.40, 0.70))
    w_gld_combined = 1 - w_spy_combined
    strategies["Regime: Combined"] = w_spy_combined * oos["spy_ret"] + w_gld_combined * oos["gld_ret"]

    # 5. 40/40/20 SPY+GLD+DBC (direct commodity exposure)
    strategies["40/40/20 SPY+GLD+DBC"] = 0.40 * oos["spy_ret"] + 0.40 * oos["gld_ret"] + 0.20 * oos["dbc_ret"]

    # 6. Equal-weight all 3
    strategies["33/33/33 SPY+GLD+DBC"] = (oos["spy_ret"] + oos["gld_ret"] + oos["dbc_ret"]) / 3

    # Evaluate all strategies
    print(f"\n{'Strategy':<30} {'Ann Ret':>9} {'Ann Vol':>9} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
    print("-" * 90)

    results_b = {}
    for name, rets in strategies.items():
        ann_ret = (1 + rets).prod() ** (12 / len(rets)) - 1
        ann_vol = rets.std() * np.sqrt(12)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + rets).cumprod()
        drawdown = cum / cum.cummax() - 1
        mdd = drawdown.min()
        calmar = ann_ret / abs(mdd) if mdd != 0 else 0
        downside_vol = rets[rets < 0].std() * np.sqrt(12) if (rets < 0).sum() > 0 else ann_vol
        sortino = ann_ret / downside_vol if downside_vol > 0 else 0

        print(f"{name:<30} {ann_ret:>8.1%} {ann_vol:>8.1%} {sharpe:>8.3f} {mdd:>8.1%} {calmar:>8.3f} {sortino:>8.3f}")

        results_b[name] = {
            "ann_ret": round(ann_ret, 4),
            "ann_vol": round(ann_vol, 4),
            "sharpe": round(sharpe, 3),
            "mdd": round(mdd, 4),
            "calmar": round(calmar, 3),
            "sortino": round(sortino, 3),
        }

    return results_b, strategies, oos


# ============================================================
# TEST C: STATISTICAL TESTS
# ============================================================
def statistical_tests(strategies, oos):
    """DM-like test: is commodity regime significantly better than 50/50?"""
    print("\n" + "=" * 80)
    print("TEST C: STATISTICAL SIGNIFICANCE")
    print("Is any commodity strategy significantly better than 50/50 SPY+GLD?")
    print("=" * 80)

    benchmark = strategies["50/50 SPY+GLD (static)"]
    results_c = {}

    for name, rets in strategies.items():
        if name == "50/50 SPY+GLD (static)":
            continue

        # Test: mean difference in returns
        diff = rets.values - benchmark.values
        n = len(diff)
        mean_diff = np.mean(diff)
        se_diff = np.std(diff, ddof=1) / np.sqrt(n)
        t_stat = mean_diff / se_diff if se_diff > 0 else 0
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

        sig = "***" if p_value < 0.001 else "**" if p_value < 0.01 else "*" if p_value < 0.05 else ""
        print(f"\n  {name} vs 50/50:")
        print(f"    Mean monthly excess return: {mean_diff:.4%}")
        print(f"    t-stat: {t_stat:.3f}, p-value: {p_value:.4f} {sig}")
        print(f"    N months: {n}")

        results_c[name] = {
            "mean_excess_return_monthly": round(mean_diff, 6),
            "t_stat": round(t_stat, 3),
            "p_value": round(p_value, 4),
            "n_months": n,
            "significant_5pct": p_value < 0.05,
        }

    return results_c


# ============================================================
# TEST D: COMMODITY REGIME DESCRIPTIVE ANALYSIS
# ============================================================
def commodity_regime_analysis(prices, signals):
    """Analyze commodity regimes and their relationship with equity vol."""
    print("\n" + "=" * 80)
    print("TEST D: COMMODITY REGIME DESCRIPTIVE ANALYSIS")
    print("=" * 80)

    # Monthly data
    dbc_12m_mom = prices["DBC"].resample("ME").last().pct_change(12)
    spy_rv_monthly = (np.log(prices["SPY"] / prices["SPY"].shift(1))).resample("ME").std() * np.sqrt(252)
    vix_monthly = prices["VIX"].resample("ME").last()

    combined = pd.DataFrame({
        "dbc_mom": dbc_12m_mom,
        "spy_rv": spy_rv_monthly,
        "vix": vix_monthly,
    }).dropna()

    # OOS
    oos = combined[combined.index >= OOS_START]

    # Regime split
    surge = oos[oos["dbc_mom"] > 0]
    decline = oos[oos["dbc_mom"] <= 0]

    print(f"\n  Commodity Surge (DBC 12m ret > 0): {len(surge)} months")
    print(f"    Avg SPY RV:  {surge['spy_rv'].mean():.1%}")
    print(f"    Avg VIX:     {surge['vix'].mean():.1f}")

    print(f"\n  Commodity Decline (DBC 12m ret <= 0): {len(decline)} months")
    print(f"    Avg SPY RV:  {decline['spy_rv'].mean():.1%}")
    print(f"    Avg VIX:     {decline['vix'].mean():.1f}")

    # T-test for difference in SPY RV between regimes
    t_rv, p_rv = stats.ttest_ind(surge["spy_rv"], decline["spy_rv"], equal_var=False)
    print(f"\n  T-test (SPY RV: surge vs decline): t={t_rv:.3f}, p={p_rv:.4f}")
    print(f"  {'Significant' if p_rv < 0.05 else 'Not significant'} at 5% level")

    # Quintile analysis of DBC momentum
    print(f"\n  --- DBC Momentum Quintile Analysis (Full OOS) ---")
    oos_sorted = oos.copy()
    oos_sorted["quintile"] = pd.qcut(oos_sorted["dbc_mom"], 5, labels=["Q1(worst)", "Q2", "Q3", "Q4", "Q5(best)"])

    print(f"  {'Quintile':<12} {'Avg DBC Mom':>12} {'Avg SPY RV':>12} {'Avg VIX':>8} {'N':>5}")
    print("  " + "-" * 55)
    for q in ["Q1(worst)", "Q2", "Q3", "Q4", "Q5(best)"]:
        group = oos_sorted[oos_sorted["quintile"] == q]
        print(f"  {q:<12} {group['dbc_mom'].mean():>12.1%} {group['spy_rv'].mean():>12.1%} {group['vix'].mean():>8.1f} {len(group):>5}")

    # Q5-Q1 spread
    q5 = oos_sorted[oos_sorted["quintile"] == "Q5(best)"]["spy_rv"].mean()
    q1 = oos_sorted[oos_sorted["quintile"] == "Q1(worst)"]["spy_rv"].mean()
    print(f"\n  Q5-Q1 SPY RV spread: {q5 - q1:.1%}")

    results_d = {
        "surge_months": len(surge),
        "surge_avg_rv": round(surge["spy_rv"].mean(), 4),
        "surge_avg_vix": round(surge["vix"].mean(), 1),
        "decline_months": len(decline),
        "decline_avg_rv": round(decline["spy_rv"].mean(), 4),
        "decline_avg_vix": round(decline["vix"].mean(), 1),
        "t_stat_rv_diff": round(t_rv, 3),
        "p_value_rv_diff": round(p_rv, 4),
        "q5_q1_rv_spread": round(q5 - q1, 4),
    }

    return results_d


# ============================================================
# TEST E: CROSS-OOS ROBUSTNESS
# ============================================================
def cross_oos_robustness(prices):
    """Test commodity regime portfolio across multiple OOS periods."""
    print("\n" + "=" * 80)
    print("TEST E: CROSS-OOS ROBUSTNESS (5 PERIODS)")
    print("=" * 80)

    periods = [
        ("2012-01", "2014-12"),
        ("2015-01", "2017-12"),
        ("2018-01", "2019-12"),
        ("2020-01", "2022-12"),
        ("2023-01", "2025-12"),
    ]

    spy_monthly = prices["SPY"].resample("ME").last().pct_change()
    gld_monthly = prices["GLD"].resample("ME").last().pct_change()
    dbc_monthly = prices["DBC"].resample("ME").last().pct_change()
    dbc_12m_mom = prices["DBC"].resample("ME").last().pct_change(12).shift(1)

    all_data = pd.DataFrame({
        "spy": spy_monthly,
        "gld": gld_monthly,
        "dbc": dbc_monthly,
        "dbc_mom": dbc_12m_mom,
    }).dropna()

    results_e = {}

    print(f"\n{'Period':<16} {'50/50 Sharpe':>13} {'Regime Sharpe':>14} {'40/40/20 Sharpe':>15} {'Regime Wins':>12}")
    print("-" * 75)

    regime_wins = 0
    for start, end in periods:
        subset = all_data[(all_data.index >= start) & (all_data.index <= end)]
        if len(subset) < 6:
            continue

        # 50/50 benchmark
        bench = 0.50 * subset["spy"] + 0.50 * subset["gld"]
        bench_sharpe = (bench.mean() * 12) / (bench.std() * np.sqrt(12)) if bench.std() > 0 else 0

        # Regime: DBC mom > 0 → 30/70, else 70/30
        w_spy = np.where(subset["dbc_mom"] > 0, 0.30, 0.70)
        regime = w_spy * subset["spy"] + (1 - w_spy) * subset["gld"]
        regime_sharpe = (regime.mean() * 12) / (regime.std() * np.sqrt(12)) if regime.std() > 0 else 0

        # 40/40/20
        tri = 0.40 * subset["spy"] + 0.40 * subset["gld"] + 0.20 * subset["dbc"]
        tri_sharpe = (tri.mean() * 12) / (tri.std() * np.sqrt(12)) if tri.std() > 0 else 0

        wins = "YES" if regime_sharpe > bench_sharpe else "NO"
        if regime_sharpe > bench_sharpe:
            regime_wins += 1

        period_label = f"{start} ~ {end}"
        print(f"{period_label:<16} {bench_sharpe:>13.3f} {regime_sharpe:>14.3f} {tri_sharpe:>15.3f} {wins:>12}")

        results_e[period_label] = {
            "benchmark_sharpe": round(bench_sharpe, 3),
            "regime_sharpe": round(regime_sharpe, 3),
            "triple_sharpe": round(tri_sharpe, 3),
            "regime_wins": regime_sharpe > bench_sharpe,
        }

    print(f"\n  Regime wins: {regime_wins}/{len(periods)} periods")
    results_e["summary"] = {"regime_wins": regime_wins, "total_periods": len(periods)}

    return results_e


# ============================================================
# TEST F: GRANGER CAUSALITY (COMMODITY → VOL)
# ============================================================
def granger_causality_test(prices):
    """Simple Granger-causality: do lagged commodity returns help predict SPY vol changes?"""
    print("\n" + "=" * 80)
    print("TEST F: GRANGER CAUSALITY (COMMODITY → EQUITY VOL)")
    print("Does lagged DBC return improve prediction of SPY vol changes?")
    print("=" * 80)

    spy_ret = np.log(prices["SPY"] / prices["SPY"].shift(1))
    spy_rv = spy_ret.rolling(RV_WINDOW).std() * np.sqrt(252)
    spy_rv_chg = spy_rv.diff()

    dbc_ret = np.log(prices["DBC"] / prices["DBC"].shift(1))
    vix = prices["VIX"]

    # Monthly aggregation for cleaner signal
    spy_rv_monthly = spy_rv.resample("ME").last()
    spy_rv_chg_m = spy_rv_monthly.diff()
    dbc_ret_monthly = dbc_ret.resample("ME").sum()
    vix_monthly = vix.resample("ME").last()

    df = pd.DataFrame({
        "rv_chg": spy_rv_chg_m,
        "rv_chg_lag1": spy_rv_chg_m.shift(1),
        "dbc_ret_lag1": dbc_ret_monthly.shift(1),
        "vix_lag1": vix_monthly.shift(1),
    }).dropna()

    oos = df[df.index >= OOS_START]
    print(f"  OOS: {oos.index[0].strftime('%Y-%m')} to {oos.index[-1].strftime('%Y-%m')} ({len(oos)} months)")

    # Restricted model: rv_chg ~ rv_chg_lag1 + vix_lag1
    from numpy.linalg import lstsq

    X_r = np.column_stack([np.ones(len(oos)), oos["rv_chg_lag1"].values, oos["vix_lag1"].values])
    y = oos["rv_chg"].values

    beta_r, resid_r, _, _ = lstsq(X_r, y, rcond=None)
    ssr_r = np.sum((y - X_r @ beta_r) ** 2)

    # Unrestricted model: rv_chg ~ rv_chg_lag1 + vix_lag1 + dbc_ret_lag1
    X_u = np.column_stack([X_r, oos["dbc_ret_lag1"].values])
    beta_u, resid_u, _, _ = lstsq(X_u, y, rcond=None)
    ssr_u = np.sum((y - X_u @ beta_u) ** 2)

    n = len(oos)
    k_r = X_r.shape[1]
    k_u = X_u.shape[1]
    df_num = k_u - k_r
    df_den = n - k_u

    f_stat = ((ssr_r - ssr_u) / df_num) / (ssr_u / df_den)
    p_value = 1 - stats.f.cdf(f_stat, df_num, df_den)

    # R-squared
    sst = np.sum((y - np.mean(y)) ** 2)
    r2_r = 1 - ssr_r / sst
    r2_u = 1 - ssr_u / sst
    delta_r2 = r2_u - r2_r

    print(f"\n  Restricted model (RV_lag + VIX_lag):     R² = {r2_r:.4f}")
    print(f"  Unrestricted model (+ DBC_ret_lag):       R² = {r2_u:.4f}")
    print(f"  Delta R²:                                 {delta_r2:.4f}")
    print(f"  F-statistic: {f_stat:.3f}")
    print(f"  p-value:     {p_value:.4f}")
    print(f"  {'DBC Granger-causes SPY vol changes' if p_value < 0.05 else 'NO Granger causality detected'}")

    # DBC coefficient in unrestricted model
    print(f"\n  DBC lag-1 coefficient: {beta_u[-1]:.4f}")
    print(f"  (Positive = rising commodities → rising equity vol)")

    results_f = {
        "r2_restricted": round(r2_r, 4),
        "r2_unrestricted": round(r2_u, 4),
        "delta_r2": round(delta_r2, 4),
        "f_stat": round(f_stat, 3),
        "p_value": round(p_value, 4),
        "dbc_coefficient": round(beta_u[-1], 4),
        "granger_significant": p_value < 0.05,
    }

    return results_f


# ============================================================
# MAIN
# ============================================================
def main():
    prices = download_data()

    # Check if all required tickers are present
    required = ["SPY", "GLD", "DBC", "USO", "CPER", "VIX"]
    missing = [t for t in required if t not in prices.columns]
    if missing:
        print(f"\n  ERROR: Missing tickers: {missing}")
        print("  Cannot proceed without all required data.")
        sys.exit(1)

    signals, spy_ret = build_signals(prices)

    # Run all tests
    results_a = test_vol_prediction(signals)
    results_b, strategies, oos = test_commodity_regime_portfolio(prices, signals)
    results_c = statistical_tests(strategies, oos)
    results_d = commodity_regime_analysis(prices, signals)
    results_e = cross_oos_robustness(prices)
    results_f = granger_causality_test(prices)

    # ============================================================
    # SUMMARY
    # ============================================================
    print("\n" + "=" * 80)
    print("K337 SUMMARY: COMMODITY SUPER-CYCLE AND EQUITY VOLATILITY")
    print("=" * 80)

    # Check if any commodity signal has significant partial r
    any_sig_a = any(
        v.get("p_value", 1) < 0.05
        for k, v in results_a.items()
        if "OOS" in k
    )

    # Check if any regime strategy beats 50/50 significantly
    any_sig_c = any(
        v.get("significant_5pct", False)
        for v in results_c.values()
    )

    # Cross-OOS wins
    regime_win_rate = results_e.get("summary", {}).get("regime_wins", 0) / max(results_e.get("summary", {}).get("total_periods", 1), 1)

    print(f"""
  A. Commodity signals → future SPY RV (partial r, controlling VIX):
     {'Some signals significant in OOS' if any_sig_a else 'NO significant partial correlation in OOS'}
     → Commodity momentum has {'incremental' if any_sig_a else 'NO incremental'} predictive power beyond VIX

  B. Commodity regime portfolio allocation:
     50/50 SPY+GLD remains the benchmark to beat
     {'Some regime strategies significantly outperform' if any_sig_c else 'NO regime strategy significantly outperforms 50/50'}

  C. Granger causality (DBC → SPY vol):
     {'DBC Granger-causes SPY vol changes' if results_f['granger_significant'] else 'No Granger causality detected'}
     Delta R² = {results_f['delta_r2']:.4f}

  D. Cross-OOS robustness:
     Regime strategy wins {results_e.get('summary', {}).get('regime_wins', 0)}/{results_e.get('summary', {}).get('total_periods', 0)} periods
     {'Robust' if regime_win_rate >= 0.6 else 'NOT robust'} across periods

  CONCLUSION:
  {'Commodity signals provide incremental information for equity vol prediction' if any_sig_a else 'VIX subsumes commodity information for equity vol prediction (VIX sufficiency reconfirmed)'}
  {'Commodity regime allocation improves on 50/50' if any_sig_c and regime_win_rate >= 0.6 else '50/50 SPY+GLD remains unbeatable (8+ confirmations)'}
""")

    # Limitations
    print("  LIMITATIONS:")
    print("  - DBC inception 2006 limits historical depth (no 20-year super-cycle capture)")
    print("  - USO has contango drag (not a pure oil price proxy)")
    print("  - CPER is small/illiquid ETF, may not represent true copper demand")
    print("  - Monthly rebalancing only; daily signals not tested")
    print("  - OOS includes COVID crash (extreme regime)")

    # Save results
    all_results = {
        "experiment": "K337",
        "title": "Commodity Super-Cycle and Equity Volatility",
        "data_source": "yfinance (real data)",
        "tickers": list(TICKERS.keys()) + ["VIX"],
        "oos_period": f"{OOS_START} to {OOS_END}",
        "test_a_vol_prediction": results_a,
        "test_b_portfolio": results_b,
        "test_c_significance": results_c,
        "test_d_regime_analysis": results_d,
        "test_e_cross_oos": results_e,
        "test_f_granger": results_f,
        "conclusion": {
            "commodity_predicts_vol_oos": any_sig_a,
            "regime_beats_5050": any_sig_c,
            "granger_significant": results_f["granger_significant"],
            "cross_oos_robust": regime_win_rate >= 0.6,
            "vix_sufficiency_reconfirmed": not any_sig_a,
        },
    }

    results_path = PROJECT_ROOT / "experiments" / "k337_commodity_cycle_results.json"
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_path}")


if __name__ == "__main__":
    main()
