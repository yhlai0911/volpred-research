"""
K737: Maximum Diversification Portfolio — Can We Beat 50/50 SPY/GLD With Better Asset Selection?

Research Question:
  Among liquid ETFs, does a Maximum Diversification, Minimum Variance, Risk Parity,
  or Equal Weight portfolio improve on 50/50 SPY/GLD?

Assets tested:
  SPY (US large cap), GLD (Gold), TLT (Long-term Treasury), IEF (Intermediate Treasury),
  EFA (International developed), EEM (Emerging markets), VNQ (REITs), DBC (Commodities),
  TIP (Inflation-protected)

Methods:
  1. Equal Weight (1/N)
  2. Minimum Variance (quadratic optimization)
  3. Maximum Diversification (Choueifaty & Coignard 2008)
  4. Risk Parity (inverse-vol weighted, normalized)
  5. Baseline: 50/50 SPY/GLD (static), Buy & Hold SPY

All portfolios use:
  - Rolling 252-day covariance matrix
  - Monthly rebalancing (21 trading days)
  - TX cost: 5 bps per total turnover
  - signal.shift(1): weights computed from t-1 data, applied to t returns

References:
  - Choueifaty & Coignard (2008) "Toward Maximum Diversification" JPM
  - DeMiguel, Garlappi & Uppal (2009) "Optimal vs Naive Diversification" RFS
  - Maillard, Roncalli & Teïlétché (2010) "On the Properties of ERC Portfolios" JPM

Data: yfinance, 2006-01-01 to present (for cross-OOS), COMMON_START 2023-01-04 for ranking
[提出: Claude, 執行: Claude]
"""

import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parent.parent
COMMON_START = "2023-01-04"
TX_COST_BPS = 5
LOOKBACK = 252  # rolling covariance window
REBAL_DAYS = 21  # monthly rebalancing

# All candidate assets
ALL_ASSETS = ["SPY", "GLD", "TLT", "IEF", "EFA", "EEM", "VNQ", "DBC", "TIP"]

# Subsets to test
SUBSETS = {
    "2_asset_spy_gld": ["SPY", "GLD"],
    "3_asset_no_tlt": ["SPY", "GLD", "EFA"],
    "3_asset_with_tlt": ["SPY", "GLD", "TLT"],
    "4_asset_diversified": ["SPY", "GLD", "EFA", "DBC"],
    "5_asset": ["SPY", "GLD", "EFA", "VNQ", "DBC"],
    "6_asset": ["SPY", "GLD", "TLT", "EFA", "VNQ", "DBC"],
    "all_9_asset": ALL_ASSETS,
}


def download_data(start="2005-01-01"):
    """Download all asset prices from yfinance."""
    import yfinance as yf

    prices = {}
    for t in ALL_ASSETS:
        d = yf.download(t, start=start, end="2026-12-31", progress=False)
        if len(d) > 0:
            prices[t] = d["Close"].squeeze()
            print(f"  {t}: {len(d)} days, {d.index[0].strftime('%Y-%m-%d')} to {d.index[-1].strftime('%Y-%m-%d')}")
        else:
            print(f"  {t}: NO DATA")

    # Also download VIX for reference
    vix = yf.download("^VIX", start=start, end="2026-12-31", progress=False)
    prices["VIX"] = vix["Close"].squeeze()

    df = pd.DataFrame(prices).dropna()
    print(f"\n  Combined dataset: {len(df)} days, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
    return df


def compute_returns(df, assets):
    """Compute daily returns for given assets."""
    rets = pd.DataFrame()
    for a in assets:
        rets[a] = df[a].pct_change()
    return rets.dropna()


# ===== Portfolio Optimization Methods =====

def equal_weight(assets):
    """1/N equal weight."""
    n = len(assets)
    return {a: 1.0 / n for a in assets}


def minimum_variance(cov_matrix, assets):
    """Minimum variance portfolio via quadratic optimization."""
    n = len(assets)
    if n == 1:
        return {assets[0]: 1.0}

    cov = cov_matrix.values

    def objective(w):
        return w @ cov @ w

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0)] * n
    x0 = np.ones(n) / n

    result = minimize(objective, x0, method="SLSQP", bounds=bounds, constraints=constraints)
    if result.success:
        w = result.x
        w = np.maximum(w, 0)  # clip negatives
        w /= w.sum()  # renormalize
        return {a: float(w[i]) for i, a in enumerate(assets)}
    else:
        # Fallback to equal weight
        return equal_weight(assets)


def max_diversification(cov_matrix, assets):
    """Maximum Diversification portfolio (Choueifaty & Coignard 2008).

    Maximize DR = (w' * sigma) / sqrt(w' * Sigma * w)
    where sigma = vector of individual volatilities
    """
    n = len(assets)
    if n == 1:
        return {assets[0]: 1.0}

    cov = cov_matrix.values
    sigmas = np.sqrt(np.diag(cov))

    def neg_div_ratio(w):
        port_vol = np.sqrt(w @ cov @ w)
        if port_vol < 1e-12:
            return 0
        return -(w @ sigmas) / port_vol

    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0)] * n
    x0 = np.ones(n) / n

    result = minimize(neg_div_ratio, x0, method="SLSQP", bounds=bounds, constraints=constraints)
    if result.success:
        w = result.x
        w = np.maximum(w, 0)
        w /= w.sum()
        return {a: float(w[i]) for i, a in enumerate(assets)}
    else:
        return equal_weight(assets)


def risk_parity(cov_matrix, assets):
    """Risk Parity: weights proportional to 1/vol, normalized."""
    vols = np.sqrt(np.diag(cov_matrix.values))
    inv_vol = 1.0 / np.maximum(vols, 1e-8)
    w = inv_vol / inv_vol.sum()
    return {a: float(w[i]) for i, a in enumerate(assets)}


def static_50_50_spy_gld(assets=None):
    """Static 50/50 SPY/GLD baseline."""
    return {"SPY": 0.5, "GLD": 0.5}


# ===== Backtest Engine =====

def run_backtest(prices_df, assets, method_name, method_func, start_date=None, end_date=None, lookback=None):
    """Run a single backtest for a given method and asset set.

    method_func: callable(cov_matrix, assets) -> dict of weights
                 or callable(assets) -> dict (for static methods)
    """
    if lookback is None:
        lookback = LOOKBACK

    rets = compute_returns(prices_df, assets)

    if start_date:
        rets = rets[rets.index >= pd.Timestamp(start_date)]
    if end_date:
        rets = rets[rets.index <= pd.Timestamp(end_date)]

    if len(rets) < lookback + 50:
        return None

    # Compute rolling covariance-based weights with PROPER LAG
    # Weight computed at end of day t-1, applied to return on day t
    weights_series = []

    for i in range(lookback, len(rets)):
        day_idx = i

        # Only rebalance monthly
        days_since_start = i - lookback
        if days_since_start % REBAL_DAYS != 0 and len(weights_series) > 0:
            # Keep previous weights
            weights_series.append(weights_series[-1])
            continue

        # Use LOOKBACK days ending at t-1 (i-1) to compute weights for day t (i)
        # This is the signal.shift(1) equivalent
        window_rets = rets.iloc[day_idx - lookback:day_idx]  # days [i-lookback, i) = up to t-1
        cov_matrix = window_rets.cov() * 252  # annualized

        if method_name in ["equal_weight"]:
            w = method_func(assets)
        elif method_name == "static_50_50":
            w = static_50_50_spy_gld()
        else:
            w = method_func(cov_matrix, assets)

        weights_series.append(w)

    # Apply weights to returns (weights are already lagged by construction)
    backtest_rets = rets.iloc[lookback:]

    if len(weights_series) != len(backtest_rets):
        print(f"  WARNING: weights ({len(weights_series)}) != returns ({len(backtest_rets)})")
        min_len = min(len(weights_series), len(backtest_rets))
        weights_series = weights_series[:min_len]
        backtest_rets = backtest_rets.iloc[:min_len]

    port_returns = []
    prev_w = {}
    for idx in range(len(backtest_rets)):
        w = weights_series[idx]
        row = backtest_rets.iloc[idx]

        # Portfolio return
        r = sum(w.get(a, 0) * row.get(a, 0) for a in assets)

        # TX cost on weight changes
        if prev_w:
            # Sum absolute weight changes across ALL assets
            all_assets_union = set(list(w.keys()) + list(prev_w.keys()))
            turnover = sum(abs(w.get(a, 0) - prev_w.get(a, 0)) for a in all_assets_union)
            r -= turnover * TX_COST_BPS / 10000

        port_returns.append(r)
        prev_w = w

    backtest_rets = backtest_rets.copy()
    backtest_rets["port_return"] = port_returns

    return backtest_rets


def calc_metrics(returns_series, label=""):
    """Calculate performance metrics from daily returns."""
    r = np.array(returns_series)
    n = len(r)
    if n < 20:
        return {"error": "too few observations"}

    mean_r = np.mean(r)
    std_r = np.std(r, ddof=1)
    sharpe = mean_r / std_r * np.sqrt(252) if std_r > 0 else 0

    # Cumulative for drawdown
    cum = np.cumprod(1 + r)
    peak = np.maximum.accumulate(cum)
    dd = (cum - peak) / peak
    mdd = float(np.min(dd)) * 100

    # CAGR
    total_ret = cum[-1] / cum[0] - 1 if cum[0] > 0 else 0
    years = n / 252
    cagr = ((1 + total_ret) ** (1 / years) - 1) * 100 if years > 0 else 0

    # Calmar
    calmar = cagr / abs(mdd) if abs(mdd) > 0.01 else 0

    # Sortino
    downside = r[r < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else std_r
    sortino = mean_r / downside_std * np.sqrt(252) if downside_std > 0 else 0

    # Annual volatility
    ann_vol = std_r * np.sqrt(252) * 100

    # Monthly win rate
    monthly_r = []
    for i in range(0, n, 21):
        chunk = r[i:i + 21]
        if len(chunk) > 10:
            monthly_r.append(np.sum(chunk))
    win_rate = sum(1 for x in monthly_r if x > 0) / len(monthly_r) * 100 if monthly_r else 0

    # Turnover (not computed here, done in backtest)

    return {
        "label": label,
        "sharpe": round(sharpe, 3),
        "cagr": round(cagr, 2),
        "ann_vol": round(ann_vol, 2),
        "mdd": round(mdd, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "win_rate": round(win_rate, 1),
        "n_days": n,
    }


def diversification_ratio(weights, cov_matrix, assets):
    """Compute the diversification ratio for given weights."""
    w = np.array([weights.get(a, 0) for a in assets])
    cov = cov_matrix.values
    sigmas = np.sqrt(np.diag(cov))
    port_vol = np.sqrt(w @ cov @ w)
    if port_vol < 1e-12:
        return 1.0
    return float((w @ sigmas) / port_vol)


# ===== Main Experiment =====

def run_experiment():
    print("=" * 80)
    print("K737: Maximum Diversification Portfolio")
    print("Can We Beat 50/50 SPY/GLD With Better Asset Selection?")
    print("=" * 80)

    # ---- Step 1: Download data ----
    print("\n[1] Downloading data...")
    prices = download_data(start="2005-01-01")

    # ---- Step 2: Data diagnostics ----
    print("\n[2] Data diagnostics")
    rets_all = compute_returns(prices, ALL_ASSETS)
    print(f"  Full sample: {rets_all.index[0].strftime('%Y-%m-%d')} to {rets_all.index[-1].strftime('%Y-%m-%d')}")
    print(f"  N days: {len(rets_all)}")

    print("\n  Annualized stats (full sample):")
    print(f"  {'Asset':<6} {'Return%':>8} {'Vol%':>8} {'Sharpe':>8} {'Skew':>8} {'Kurt':>8}")
    stats_table = {}
    for a in ALL_ASSETS:
        r = rets_all[a]
        ann_ret = r.mean() * 252 * 100
        ann_vol = r.std() * np.sqrt(252) * 100
        sh = (r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else 0
        skew = float(r.skew())
        kurt = float(r.kurtosis())
        print(f"  {a:<6} {ann_ret:>8.2f} {ann_vol:>8.2f} {sh:>8.3f} {skew:>8.3f} {kurt:>8.3f}")
        stats_table[a] = {"ann_ret": round(ann_ret, 2), "ann_vol": round(ann_vol, 2),
                          "sharpe": round(sh, 3), "skew": round(skew, 3), "kurt": round(kurt, 3)}

    # Correlation matrix
    print("\n  Correlation matrix (full sample):")
    corr = rets_all.corr()
    print("  " + "".join(f"{a:>6}" for a in ALL_ASSETS))
    for a1 in ALL_ASSETS:
        row = f"  {a1:<6}"
        for a2 in ALL_ASSETS:
            row += f"{corr.loc[a1, a2]:>6.2f}"
        print(row)

    results = {
        "experiment_id": "K737",
        "title": "Maximum Diversification Portfolio vs 50/50 SPY/GLD",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "data_source": "yfinance",
        "assets": ALL_ASSETS,
        "methods": ["equal_weight", "minimum_variance", "max_diversification", "risk_parity", "static_50_50"],
        "params": {
            "lookback": LOOKBACK,
            "rebal_days": REBAL_DAYS,
            "tx_cost_bps": TX_COST_BPS,
            "common_start": COMMON_START,
        },
        "diagnostics": {
            "full_sample_stats": stats_table,
            "correlation_matrix": {a1: {a2: round(corr.loc[a1, a2], 4) for a2 in ALL_ASSETS} for a1 in ALL_ASSETS},
        },
    }

    # ---- Step 3: Run backtests on all subsets × all methods ----
    print("\n[3] Running backtests (COMMON_START to present)...")

    methods = {
        "equal_weight": equal_weight,
        "minimum_variance": minimum_variance,
        "max_diversification": max_diversification,
        "risk_parity": risk_parity,
    }

    comparison_results = {}

    # Also add baselines
    # BH SPY baseline
    rets_spy = compute_returns(prices, ["SPY"])
    rets_spy_common = rets_spy[rets_spy.index >= pd.Timestamp(COMMON_START)]
    if len(rets_spy_common) > 20:
        bh_spy = calc_metrics(rets_spy_common["SPY"].values, "BH_SPY")
        comparison_results["BH_SPY"] = bh_spy
        print(f"  BH_SPY: Sharpe={bh_spy['sharpe']:.3f}, CAGR={bh_spy['cagr']:.2f}%, MDD={bh_spy['mdd']:.2f}%")

    # Static 50/50 SPY/GLD
    bt_5050 = run_backtest(prices, ["SPY", "GLD"], "static_50_50", None, start_date="2022-01-01")
    if bt_5050 is not None:
        common_5050 = bt_5050[bt_5050.index >= pd.Timestamp(COMMON_START)]
        if len(common_5050) > 20:
            m_5050 = calc_metrics(common_5050["port_return"].values, "Static_50_50_SPY_GLD")
            comparison_results["Static_50_50_SPY_GLD"] = m_5050
            print(f"  Static 50/50 SPY/GLD: Sharpe={m_5050['sharpe']:.3f}, CAGR={m_5050['cagr']:.2f}%, MDD={m_5050['mdd']:.2f}%")

    # Run each method × each subset
    subset_results = {}

    for subset_name, assets in SUBSETS.items():
        print(f"\n  --- Subset: {subset_name} ({', '.join(assets)}) ---")
        subset_results[subset_name] = {}

        for method_name, method_func in methods.items():
            label = f"{method_name}_{subset_name}"
            bt = run_backtest(prices, assets, method_name, method_func, start_date="2022-01-01")

            if bt is None:
                print(f"    {method_name}: SKIPPED (insufficient data)")
                continue

            common_bt = bt[bt.index >= pd.Timestamp(COMMON_START)]
            if len(common_bt) < 20:
                print(f"    {method_name}: SKIPPED (too few days in COMMON period)")
                continue

            m = calc_metrics(common_bt["port_return"].values, label)
            subset_results[subset_name][method_name] = m
            comparison_results[label] = m

            print(f"    {method_name}: Sharpe={m['sharpe']:.3f}, CAGR={m['cagr']:.2f}%, MDD={m['mdd']:.2f}%, Vol={m['ann_vol']:.2f}%")

    results["common_period_results"] = comparison_results
    results["subset_results"] = subset_results

    # ---- Step 4: Rank all strategies ----
    print("\n[4] Ranking all strategies (COMMON_START to present)")
    print(f"\n  {'Strategy':<45} {'Sharpe':>8} {'CAGR%':>8} {'Vol%':>8} {'MDD%':>8} {'Calmar':>8} {'Sortino':>8} {'WinR%':>7}")
    print("  " + "-" * 102)

    ranked = sorted(comparison_results.items(), key=lambda x: x[1].get("sharpe", -99), reverse=True)
    for name, m in ranked:
        marker = " ***" if name == "Static_50_50_SPY_GLD" else ""
        print(f"  {name:<45} {m['sharpe']:>8.3f} {m['cagr']:>8.2f} {m['ann_vol']:>8.2f} {m['mdd']:>8.2f} {m['calmar']:>8.3f} {m['sortino']:>8.3f} {m['win_rate']:>7.1f}{marker}")

    results["ranking"] = [{"rank": i + 1, "strategy": name, **m} for i, (name, m) in enumerate(ranked)]

    # ---- Step 5: Best method per subset ----
    print("\n[5] Best method per asset subset:")
    best_per_subset = {}
    for subset_name, methods_dict in subset_results.items():
        if not methods_dict:
            continue
        best = max(methods_dict.items(), key=lambda x: x[1].get("sharpe", -99))
        best_per_subset[subset_name] = {"method": best[0], **best[1]}
        print(f"  {subset_name}: {best[0]} (Sharpe={best[1]['sharpe']:.3f}, MDD={best[1]['mdd']:.2f}%)")

    results["best_per_subset"] = best_per_subset

    # ---- Step 6: Cross-OOS validation ----
    print("\n[6] Cross-OOS validation (5 × 2-year periods)")
    oos_periods = [
        ("2006-06-01", "2008-05-31"),
        ("2008-06-01", "2010-05-31"),
        ("2012-01-01", "2013-12-31"),
        ("2016-01-01", "2017-12-31"),
        ("2020-01-01", "2021-12-31"),
    ]

    # Test best overall method vs static 50/50
    # Find best method from COMMON period
    # Focus on max_diversification with the best subset
    oos_test_configs = [
        ("max_diversification", "all_9_asset", ALL_ASSETS),
        ("risk_parity", "all_9_asset", ALL_ASSETS),
        ("minimum_variance", "all_9_asset", ALL_ASSETS),
        ("equal_weight", "all_9_asset", ALL_ASSETS),
    ]

    oos_results = {}
    for method_name, subset_label, assets in oos_test_configs:
        key = f"{method_name}_{subset_label}"
        oos_results[key] = {"wins": 0, "periods": []}

        for start, end in oos_periods:
            # Run method
            bt = run_backtest(prices, assets, method_name, methods.get(method_name, equal_weight),
                              start_date=str(pd.Timestamp(start) - pd.DateOffset(days=400)),
                              end_date=end)

            # Run static 50/50 baseline
            bt_base = run_backtest(prices, ["SPY", "GLD"], "static_50_50", None,
                                   start_date=str(pd.Timestamp(start) - pd.DateOffset(days=400)),
                                   end_date=end)

            if bt is None or bt_base is None:
                oos_results[key]["periods"].append({
                    "period": f"{start} to {end}",
                    "status": "skipped",
                })
                continue

            # Filter to OOS period
            bt_oos = bt[(bt.index >= pd.Timestamp(start)) & (bt.index <= pd.Timestamp(end))]
            bt_base_oos = bt_base[(bt_base.index >= pd.Timestamp(start)) & (bt_base.index <= pd.Timestamp(end))]

            if len(bt_oos) < 50 or len(bt_base_oos) < 50:
                oos_results[key]["periods"].append({
                    "period": f"{start} to {end}",
                    "status": "insufficient data",
                })
                continue

            m_test = calc_metrics(bt_oos["port_return"].values, f"{key}_{start[:4]}")
            m_base = calc_metrics(bt_base_oos["port_return"].values, f"50_50_{start[:4]}")

            win = m_test["sharpe"] > m_base["sharpe"]
            if win:
                oos_results[key]["wins"] += 1

            oos_results[key]["periods"].append({
                "period": f"{start} to {end}",
                "method_sharpe": m_test["sharpe"],
                "baseline_sharpe": m_base["sharpe"],
                "win": win,
            })

        total_valid = sum(1 for p in oos_results[key]["periods"] if p.get("status") is None)
        wins = oos_results[key]["wins"]
        print(f"  {key}: {wins}/{total_valid} wins vs 50/50 SPY/GLD")
        for p in oos_results[key]["periods"]:
            if "method_sharpe" in p:
                marker = "WIN" if p["win"] else "LOSE"
                print(f"    {p['period']}: method={p['method_sharpe']:.3f} vs base={p['baseline_sharpe']:.3f} [{marker}]")
            else:
                print(f"    {p['period']}: {p.get('status', 'unknown')}")

    results["cross_oos"] = oos_results

    # ---- Step 7: Diversification Ratio Analysis ----
    print("\n[7] Diversification Ratio analysis (end of sample)")
    rets_recent = compute_returns(prices, ALL_ASSETS)
    recent_cov = rets_recent.iloc[-252:].cov() * 252

    dr_results = {}
    for method_name, method_func in methods.items():
        if method_name == "equal_weight":
            w = method_func(ALL_ASSETS)
        else:
            w = method_func(recent_cov, ALL_ASSETS)
        dr = diversification_ratio(w, recent_cov, ALL_ASSETS)
        dr_results[method_name] = {
            "weights": {a: round(v, 4) for a, v in w.items()},
            "diversification_ratio": round(dr, 4),
        }
        print(f"  {method_name}: DR={dr:.4f}")
        wstr = ", ".join(f"{a}:{v:.1%}" for a, v in sorted(w.items(), key=lambda x: -x[1]) if v > 0.01)
        print(f"    Weights: {wstr}")

    # Also compute for static 50/50
    w_5050 = {"SPY": 0.5, "GLD": 0.5}
    # Need to use only SPY/GLD cov for fair comparison
    cov_2 = rets_recent[["SPY", "GLD"]].iloc[-252:].cov() * 252
    dr_5050 = diversification_ratio(w_5050, cov_2, ["SPY", "GLD"])
    dr_results["static_50_50"] = {
        "weights": w_5050,
        "diversification_ratio": round(dr_5050, 4),
    }
    print(f"  static_50_50 (SPY/GLD only): DR={dr_5050:.4f}")

    results["diversification_ratios"] = dr_results

    # ---- Step 8: Sensitivity to lookback window ----
    print("\n[8] Sensitivity: lookback window (126 vs 252 vs 504)")

    sensitivity_results = {}
    for lb in [126, 252, 504]:
        bt = run_backtest(prices, ALL_ASSETS, "max_diversification", max_diversification,
                          start_date="2022-01-01", lookback=lb)
        if bt is not None:
            common_bt = bt[bt.index >= pd.Timestamp(COMMON_START)]
            if len(common_bt) > 20:
                m = calc_metrics(common_bt["port_return"].values, f"maxdiv_lb{lb}")
                sensitivity_results[f"lookback_{lb}"] = m
                print(f"  lookback={lb}: Sharpe={m['sharpe']:.3f}, CAGR={m['cagr']:.2f}%, MDD={m['mdd']:.2f}%")

    results["sensitivity_lookback"] = sensitivity_results

    # ---- Step 9: Final verdict ----
    print("\n" + "=" * 80)
    print("[9] FINAL VERDICT")
    print("=" * 80)

    baseline_sharpe = comparison_results.get("Static_50_50_SPY_GLD", {}).get("sharpe", 0)
    baseline_mdd = comparison_results.get("Static_50_50_SPY_GLD", {}).get("mdd", 0)

    # Find the single best strategy
    best_overall = ranked[0] if ranked else ("none", {})

    print(f"\n  Baseline: Static 50/50 SPY/GLD — Sharpe={baseline_sharpe:.3f}, MDD={baseline_mdd:.2f}%")
    print(f"  Best:     {best_overall[0]} — Sharpe={best_overall[1].get('sharpe', 0):.3f}, MDD={best_overall[1].get('mdd', 0):.2f}%")

    # Key conclusions
    conclusions = []

    # Did any multi-asset beat 50/50?
    multi_asset_winners = [(name, m) for name, m in ranked
                           if m.get("sharpe", 0) > baseline_sharpe
                           and name != "Static_50_50_SPY_GLD"
                           and name != "BH_SPY"]

    if multi_asset_winners:
        conclusions.append(f"{len(multi_asset_winners)} strategies beat 50/50 SPY/GLD on Sharpe")
        for name, m in multi_asset_winners[:5]:
            conclusions.append(f"  - {name}: Sharpe={m['sharpe']:.3f} (+{m['sharpe']-baseline_sharpe:.3f})")
    else:
        conclusions.append("NO multi-asset strategy beats 50/50 SPY/GLD on Sharpe")

    # MDD improvement?
    mdd_improvements = [(name, m) for name, m in ranked
                         if m.get("mdd", -100) > baseline_mdd  # less negative = better
                         and name != "Static_50_50_SPY_GLD"
                         and name != "BH_SPY"]

    if mdd_improvements:
        conclusions.append(f"\n  {len(mdd_improvements)} strategies have lower MDD than 50/50:")
        for name, m in sorted(mdd_improvements, key=lambda x: x[1]["mdd"], reverse=True)[:5]:
            conclusions.append(f"  - {name}: MDD={m['mdd']:.2f}% (vs {baseline_mdd:.2f}%)")

    # Cross-OOS verdict
    oos_winners = {k: v for k, v in oos_results.items()
                   if v["wins"] >= 3}
    if oos_winners:
        conclusions.append(f"\n  Cross-OOS winners (≥3/5): {list(oos_winners.keys())}")
    else:
        conclusions.append("\n  NO strategy passes cross-OOS (≥3/5 wins vs 50/50)")

    # DeMiguel 1/N finding
    ew_sharpes = {k: v["sharpe"] for k, v in comparison_results.items() if k.startswith("equal_weight")}
    if ew_sharpes:
        best_ew = max(ew_sharpes, key=ew_sharpes.get)
        opt_sharpes = {k: v["sharpe"] for k, v in comparison_results.items()
                       if not k.startswith("equal_weight") and k not in ["BH_SPY", "Static_50_50_SPY_GLD"]}
        if opt_sharpes:
            best_opt = max(opt_sharpes, key=opt_sharpes.get)
            conclusions.append(f"\n  DeMiguel check: Best 1/N={ew_sharpes[best_ew]:.3f} ({best_ew}) vs Best optimized={opt_sharpes[best_opt]:.3f} ({best_opt})")
            if ew_sharpes[best_ew] >= opt_sharpes[best_opt]:
                conclusions.append("  → 1/N WINS over optimization (confirms DeMiguel et al 2009)")
            else:
                conclusions.append(f"  → Optimization wins by {opt_sharpes[best_opt]-ew_sharpes[best_ew]:.3f}")

    for c in conclusions:
        print(f"  {c}")

    results["conclusions"] = conclusions
    results["verdict"] = {
        "baseline_sharpe": baseline_sharpe,
        "baseline_mdd": baseline_mdd,
        "best_strategy": best_overall[0],
        "best_sharpe": best_overall[1].get("sharpe", 0),
        "best_mdd": best_overall[1].get("mdd", 0),
        "multi_asset_beats_50_50": len(multi_asset_winners) > 0,
        "n_winners": len(multi_asset_winners),
        "cross_oos_pass": len(oos_winners) > 0,
    }

    # ---- Save results ----
    out_path = PROJECT / "experiments" / "k737_max_diversification_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to {out_path}")

    return results


if __name__ == "__main__":
    run_experiment()
