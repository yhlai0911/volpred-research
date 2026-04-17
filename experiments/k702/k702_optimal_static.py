"""K702: Optimal Static Asset Allocation — Beyond 50/50 SPY/GLD
=================================================================
K687 showed BH 50/50 SPY/GLD has the best lag-corrected Sharpe (0.545).
But is 50/50 itself optimal? What about adding TLT (bonds), EFA (international),
or using different weights?

This experiment tests 8 static allocations (buy-and-hold with annual rebalance):
  a. SPY only (100/0/0/0)
  b. 50/50 SPY/GLD (current best from K687)
  c. 60/40 SPY/TLT (traditional balanced)
  d. 60/40 SPY/GLD (K646 suggested)
  e. 40/30/30 SPY/GLD/TLT (3-asset)
  f. 25/25/25/25 equal weight (4-asset)
  g. Risk Parity static (weight ∝ 1/σ, estimated on first 2 years, held constant)
  h. Markowitz mean-variance optimal (estimated on first half, tested on second)

Evaluation: Sharpe, MDD, CAGR, Calmar (full period 2007-2026)
Cross-OOS: Top 3 allocations across 5 periods
Key question: Can we beat 50/50 SPY/GLD with a better STATIC mix?

No timing, no VIX — pure asset allocation optimization.

Data source: yfinance (SPY, GLD, TLT, EFA)
Period: 2006-01-01 to 2026-03-27
Evaluation: 2007-01-03 to 2026-03-27

References:
  - K687: Post-Correction Definitive Strategy Ranking (BH 50/50 Sharpe=0.545)
  - K646: Cross-OOS 80/20 vs 50/50 — 80/20 wins 4/5
  - K645: GLD Role Analysis — optimal 20% with VT
  - Markowitz (1952), Portfolio Selection, Journal of Finance
  - Maillard, Roncalli & Teiletche (2010), On the Properties of Equally
    Weighted Risk Contributions Portfolios, Journal of Portfolio Management
  - DeMiguel, Garlappi & Uppal (2009), Optimal Versus Naive Diversification,
    RFS — 1/N often beats MV out-of-sample
  - Asness, Frazzini & Pedersen (2012), Leverage Aversion and Risk Parity, FAJ

Attribution: [提出: Claude, 執行: Claude]
Author: VolPred Research System
Date: 2026-03-28
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats as sp_stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

# ============================================================
# CONFIGURATION
# ============================================================
TICKERS = ["SPY", "GLD", "TLT", "EFA"]
START_DATE = "2006-01-01"
END_DATE = "2026-03-27"
WARMUP_DAYS = 252  # 1 year warmup for estimation
RF_ANNUAL = 0.04   # risk-free rate
TX_COST_BPS = 5    # 5 bps per rebalance leg
BOOTSTRAP_REPS = 5000

# Cross-OOS periods (5 non-overlapping ~4-year windows)
OOS_PERIODS = [
    ("2007-01-03", "2010-12-31"),  # includes GFC
    ("2011-01-03", "2014-12-31"),  # recovery
    ("2015-01-02", "2018-12-31"),  # bull + volmageddon
    ("2019-01-02", "2022-12-31"),  # covid + inflation
    ("2023-01-03", "2026-03-27"),  # recent
]


# ============================================================
# DATA DOWNLOAD
# ============================================================
def download_data():
    """Download daily adjusted close prices for all tickers."""
    print(f"Downloading {TICKERS} from {START_DATE} to {END_DATE}...")
    data = yf.download(TICKERS, start=START_DATE, end=END_DATE, auto_adjust=True)

    # Handle multi-level columns
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data[["Close"]].copy()
        prices.columns = TICKERS

    prices = prices.dropna()
    print(f"  Got {len(prices)} trading days, {prices.columns.tolist()}")
    print(f"  Date range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")

    return prices


# ============================================================
# PORTFOLIO SIMULATION
# ============================================================
def simulate_static_portfolio(prices, weights, name, rebalance_freq="annual"):
    """
    Simulate a buy-and-hold portfolio with periodic rebalancing.

    Parameters:
        prices: DataFrame of daily prices (columns = tickers)
        weights: dict {ticker: target_weight} — must sum to 1.0
        name: strategy name string
        rebalance_freq: 'annual' or 'none'

    Returns:
        dict with performance metrics
    """
    # Align weights to price columns
    tickers_used = [t for t in prices.columns if t in weights and weights[t] > 0]
    w = np.array([weights.get(t, 0.0) for t in prices.columns])

    if abs(w.sum() - 1.0) > 0.01:
        raise ValueError(f"Weights sum to {w.sum()}, expected ~1.0")

    # Daily returns
    rets = prices.pct_change().dropna()

    # Portfolio value tracking
    n_days = len(rets)
    portfolio_val = np.ones(n_days + 1)  # start at 1.0
    current_weights = w.copy()

    total_turnover = 0.0
    n_rebalances = 0
    last_rebal_year = rets.index[0].year - 1

    for i in range(n_days):
        date = rets.index[i]
        day_ret = rets.iloc[i].values

        # Check if annual rebalance needed
        if rebalance_freq == "annual" and date.year != last_rebal_year:
            # Rebalance: compute turnover
            if i > 0:  # skip first day
                turnover = np.sum(np.abs(current_weights - w))
                total_turnover += turnover
                n_rebalances += 1
                # TX cost = turnover * cost_per_leg
                tx_cost = turnover * TX_COST_BPS / 10000
                portfolio_val[i] *= (1 - tx_cost)

            current_weights = w.copy()
            last_rebal_year = date.year

        # Portfolio return = sum(w_i * r_i)
        port_ret = np.dot(current_weights, day_ret)
        portfolio_val[i + 1] = portfolio_val[i] * (1 + port_ret)

        # Drift weights (BH between rebalances)
        new_vals = current_weights * (1 + day_ret)
        current_weights = new_vals / new_vals.sum()

    # Compute metrics
    port_rets_daily = np.diff(portfolio_val) / portfolio_val[:-1]
    # Align with dates
    port_rets_series = pd.Series(port_rets_daily, index=rets.index)

    metrics = compute_metrics(port_rets_series, name)
    metrics["tickers_used"] = tickers_used
    metrics["target_weights"] = {t: round(weights.get(t, 0), 4) for t in tickers_used}
    metrics["n_rebalances"] = n_rebalances
    metrics["total_turnover"] = round(total_turnover, 4)
    metrics["avg_annual_turnover"] = round(total_turnover / max(1, metrics["n_years"]), 4)

    return metrics, port_rets_series


def compute_metrics(rets_series, name):
    """Compute standard performance metrics from a daily return series."""
    n = len(rets_series)
    n_years = n / 252

    ann_ret = (1 + rets_series).prod() ** (252 / n) - 1
    ann_vol = rets_series.std() * np.sqrt(252)
    rf_daily = (1 + RF_ANNUAL) ** (1/252) - 1
    excess = rets_series - rf_daily
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

    # Sortino
    downside = excess[excess < 0]
    downside_vol = np.sqrt((downside ** 2).mean()) * np.sqrt(252)
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0

    # CAGR
    total_ret = (1 + rets_series).prod()
    cagr = total_ret ** (1 / n_years) - 1

    # MDD
    cum = (1 + rets_series).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    return {
        "strategy": name,
        "cagr_pct": round(cagr * 100, 2),
        "ann_ret_pct": round(ann_ret * 100, 2),
        "ann_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "mdd_pct": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "total_return_pct": round((total_ret - 1) * 100, 2),
        "n_days": n,
        "n_years": round(n_years, 1),
    }


# ============================================================
# RISK PARITY (STATIC)
# ============================================================
def compute_risk_parity_weights(prices, estimation_end):
    """
    Compute risk parity weights using 1/σ on the estimation period.
    Weight_i ∝ 1/σ_i (inverse volatility).
    """
    est_prices = prices.loc[:estimation_end]
    rets = est_prices.pct_change().dropna()
    vols = rets.std() * np.sqrt(252)

    inv_vols = 1.0 / vols
    weights = inv_vols / inv_vols.sum()

    print(f"\nRisk Parity weights (estimated on data through {estimation_end}):")
    for t, w in zip(prices.columns, weights):
        print(f"  {t}: {w:.4f} (ann vol = {vols[t]:.4f})")

    return {t: round(w, 4) for t, w in zip(prices.columns, weights)}


# ============================================================
# MARKOWITZ MEAN-VARIANCE OPTIMAL
# ============================================================
def compute_markowitz_weights(prices, estimation_end):
    """
    Compute Markowitz mean-variance optimal weights on the estimation period.
    Maximize Sharpe ratio subject to long-only, fully invested constraints.
    """
    est_prices = prices.loc[:estimation_end]
    rets = est_prices.pct_change().dropna()
    mu = rets.mean() * 252  # annualized returns
    cov = rets.cov() * 252  # annualized covariance

    n_assets = len(prices.columns)
    rf_daily_ann = RF_ANNUAL

    def neg_sharpe(w):
        port_ret = np.dot(w, mu)
        port_vol = np.sqrt(np.dot(w, cov.values @ w))
        if port_vol < 1e-10:
            return 0
        return -(port_ret - rf_daily_ann) / port_vol

    # Constraints: long-only, fully invested
    constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
    bounds = [(0.0, 1.0) for _ in range(n_assets)]
    x0 = np.ones(n_assets) / n_assets

    result = minimize(neg_sharpe, x0, method="SLSQP",
                      bounds=bounds, constraints=constraints,
                      options={"maxiter": 1000, "ftol": 1e-12})

    if not result.success:
        print(f"  WARNING: Markowitz optimization did not converge: {result.message}")

    weights = result.x
    print(f"\nMarkowitz MV-Optimal weights (estimated on data through {estimation_end}):")
    for t, w in zip(prices.columns, weights):
        print(f"  {t}: {w:.4f}")
    print(f"  In-sample Sharpe: {-result.fun:.3f}")

    return {t: round(w, 4) for t, w in zip(prices.columns, weights)}


# ============================================================
# BOOTSTRAP SHARPE CONFIDENCE INTERVALS
# ============================================================
def bootstrap_sharpe(daily_rets, n_boot=BOOTSTRAP_REPS):
    """Bootstrap 95% CI for Sharpe ratio."""
    n = len(daily_rets)
    rf_daily = (1 + RF_ANNUAL) ** (1/252) - 1
    excess = daily_rets - rf_daily

    sharpes = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        sample = excess.values[idx]
        sharpes[b] = sample.mean() / sample.std() * np.sqrt(252)

    return {
        "mean": round(np.mean(sharpes), 3),
        "std": round(np.std(sharpes), 3),
        "ci_lower": round(np.percentile(sharpes, 2.5), 3),
        "ci_upper": round(np.percentile(sharpes, 97.5), 3),
    }


# ============================================================
# DIEBOLD-MARIANO TEST (utility-based)
# ============================================================
def dm_test_returns(rets_a, rets_b, name_a, name_b):
    """
    Diebold-Mariano test comparing mean daily returns.
    H0: E[r_a - r_b] = 0
    Uses Newey-West HAC with lag = int(n^(1/3)).
    """
    diff = rets_a.values - rets_b.values
    n = len(diff)
    d_mean = diff.mean()

    # Newey-West HAC
    lag = int(n ** (1/3))
    gamma0 = np.var(diff, ddof=1)
    nw_var = gamma0
    for k in range(1, lag + 1):
        gamma_k = np.cov(diff[k:], diff[:-k])[0, 1]
        nw_var += 2 * (1 - k / (lag + 1)) * gamma_k

    se = np.sqrt(nw_var / n)
    t_stat = d_mean / se if se > 0 else 0
    p_value = 2 * (1 - sp_stats.norm.cdf(abs(t_stat)))

    return {
        "comparison": f"{name_a} vs {name_b}",
        "mean_diff_daily_bps": round(d_mean * 10000, 2),
        "t_stat": round(t_stat, 3),
        "p_value": round(p_value, 4),
        "significant_5pct": p_value < 0.05,
        "significant_harvey": abs(t_stat) > 3.0,
        "nw_lag": lag,
    }


# ============================================================
# CROSS-OOS EVALUATION
# ============================================================
def cross_oos_evaluation(prices, allocations_to_test, periods=OOS_PERIODS):
    """
    Evaluate top allocations across multiple OOS periods.
    Returns a dict of {strategy_name: {period: metrics}}.
    """
    results = {}

    for name, weights in allocations_to_test.items():
        results[name] = {"periods": [], "sharpes": [], "mdds": [], "cagrs": []}

        for start, end in periods:
            period_prices = prices.loc[start:end]
            if len(period_prices) < 100:
                print(f"  WARNING: {name} period {start}-{end} has only {len(period_prices)} days, skipping")
                continue

            metrics, _ = simulate_static_portfolio(period_prices, weights, name)
            results[name]["periods"].append(f"{start[:4]}-{end[:4]}")
            results[name]["sharpes"].append(metrics["sharpe"])
            results[name]["mdds"].append(metrics["mdd_pct"])
            results[name]["cagrs"].append(metrics["cagr_pct"])

        results[name]["mean_sharpe"] = round(np.mean(results[name]["sharpes"]), 3)
        results[name]["std_sharpe"] = round(np.std(results[name]["sharpes"]), 3)
        results[name]["min_sharpe"] = round(np.min(results[name]["sharpes"]), 3)
        results[name]["mean_mdd"] = round(np.mean(results[name]["mdds"]), 2)
        results[name]["mean_cagr"] = round(np.mean(results[name]["cagrs"]), 2)
        results[name]["worst_mdd"] = round(np.min(results[name]["mdds"]), 2)

    return results


# ============================================================
# GRID SEARCH: Optimal 2-asset mix (SPY/GLD)
# ============================================================
def grid_search_2asset(prices, eval_start):
    """
    Brute-force grid search over SPY/GLD weights from 0% to 100% in 5% steps.
    Returns the allocation with highest Sharpe.
    """
    eval_prices = prices.loc[eval_start:][["SPY", "GLD"]]
    best_sharpe = -999
    best_w = None
    all_results = []

    for spy_pct in range(0, 105, 5):
        gld_pct = 100 - spy_pct
        w = {"SPY": spy_pct / 100, "GLD": gld_pct / 100}
        metrics, _ = simulate_static_portfolio(eval_prices, w, f"SPY {spy_pct}/GLD {gld_pct}")
        all_results.append({
            "spy_pct": spy_pct,
            "gld_pct": gld_pct,
            "sharpe": metrics["sharpe"],
            "cagr_pct": metrics["cagr_pct"],
            "mdd_pct": metrics["mdd_pct"],
            "calmar": metrics["calmar"],
            "ann_vol_pct": metrics["ann_vol_pct"],
        })
        if metrics["sharpe"] > best_sharpe:
            best_sharpe = metrics["sharpe"]
            best_w = (spy_pct, gld_pct)

    return all_results, best_w


# ============================================================
# MAIN
# ============================================================
def main():
    print("=" * 70)
    print("K702: Optimal Static Asset Allocation — Beyond 50/50 SPY/GLD")
    print("=" * 70)

    # 1. Download data
    prices = download_data()

    # Descriptive statistics
    rets = prices.pct_change().dropna()
    print("\n--- Descriptive Statistics (annualized) ---")
    for t in TICKERS:
        r = rets[t]
        ann_ret = (1 + r).prod() ** (252 / len(r)) - 1
        ann_vol = r.std() * np.sqrt(252)
        sharpe_ind = (ann_ret - RF_ANNUAL) / ann_vol
        print(f"  {t}: Return={ann_ret*100:.2f}%, Vol={ann_vol*100:.2f}%, "
              f"Sharpe={sharpe_ind:.3f}, Skew={r.skew():.3f}, Kurt={r.kurtosis():.3f}")

    # Correlation matrix
    corr = rets.corr()
    print("\n--- Correlation Matrix ---")
    print(corr.round(3).to_string())

    # 2. Define static allocations
    eval_start = "2007-01-03"

    # Risk Parity: estimate on first 2 years (2006)
    rp_estimation_end = "2007-12-31"
    rp_weights = compute_risk_parity_weights(prices, rp_estimation_end)

    # Markowitz: estimate on first half
    mid_date = prices.index[len(prices) // 2].strftime("%Y-%m-%d")
    mk_weights = compute_markowitz_weights(prices, mid_date)

    allocations = {
        "SPY Only": {"SPY": 1.0, "GLD": 0.0, "TLT": 0.0, "EFA": 0.0},
        "50/50 SPY/GLD": {"SPY": 0.5, "GLD": 0.5, "TLT": 0.0, "EFA": 0.0},
        "60/40 SPY/TLT": {"SPY": 0.6, "GLD": 0.0, "TLT": 0.4, "EFA": 0.0},
        "60/40 SPY/GLD": {"SPY": 0.6, "GLD": 0.4, "TLT": 0.0, "EFA": 0.0},
        "40/30/30 SPY/GLD/TLT": {"SPY": 0.4, "GLD": 0.3, "TLT": 0.3, "EFA": 0.0},
        "25/25/25/25 Equal Weight": {"SPY": 0.25, "GLD": 0.25, "TLT": 0.25, "EFA": 0.25},
        "Risk Parity Static": rp_weights,
        "Markowitz MV-Optimal": mk_weights,
    }

    # 3. Full-sample evaluation
    print("\n" + "=" * 70)
    print("FULL-SAMPLE EVALUATION (2007-2026)")
    print("=" * 70)

    eval_prices = prices.loc[eval_start:]
    all_metrics = []
    all_rets = {}

    for name, weights in allocations.items():
        metrics, port_rets = simulate_static_portfolio(eval_prices, weights, name)
        all_metrics.append(metrics)
        all_rets[name] = port_rets
        print(f"\n  {name}:")
        print(f"    Sharpe={metrics['sharpe']:.3f}  CAGR={metrics['cagr_pct']:.2f}%  "
              f"MDD={metrics['mdd_pct']:.2f}%  Calmar={metrics['calmar']:.3f}  "
              f"Vol={metrics['ann_vol_pct']:.2f}%  Turnover/yr={metrics['avg_annual_turnover']:.4f}")

    # Sort by Sharpe
    all_metrics.sort(key=lambda x: x["sharpe"], reverse=True)

    print("\n--- Ranking by Sharpe (descending) ---")
    for i, m in enumerate(all_metrics, 1):
        print(f"  #{i}: {m['strategy']:30s} Sharpe={m['sharpe']:.3f}  "
              f"CAGR={m['cagr_pct']:6.2f}%  MDD={m['mdd_pct']:7.2f}%  "
              f"Calmar={m['calmar']:.3f}")

    # 4. Bootstrap Sharpe CIs for top strategies
    print("\n" + "=" * 70)
    print("BOOTSTRAP SHARPE 95% CIs")
    print("=" * 70)
    bootstrap_results = {}
    for m in all_metrics[:5]:  # top 5
        name = m["strategy"]
        bs = bootstrap_sharpe(all_rets[name])
        bootstrap_results[name] = bs
        print(f"  {name:30s}: Sharpe={bs['mean']:.3f} [{bs['ci_lower']:.3f}, {bs['ci_upper']:.3f}]")

    # 5. DM tests vs 50/50 SPY/GLD (benchmark)
    print("\n" + "=" * 70)
    print("DM TESTS vs 50/50 SPY/GLD (NW-HAC)")
    print("=" * 70)
    benchmark_name = "50/50 SPY/GLD"
    dm_results = []

    for name in all_rets:
        if name == benchmark_name:
            continue
        dm = dm_test_returns(all_rets[name], all_rets[benchmark_name], name, benchmark_name)
        dm_results.append(dm)
        sig_str = "***" if dm["significant_harvey"] else ("*" if dm["significant_5pct"] else "NS")
        print(f"  {name:30s} vs 50/50: diff={dm['mean_diff_daily_bps']:+.2f} bps/day  "
              f"t={dm['t_stat']:+.3f}  p={dm['p_value']:.4f}  {sig_str}")

    # 6. Grid search: optimal SPY/GLD mix
    print("\n" + "=" * 70)
    print("GRID SEARCH: Optimal SPY/GLD Mix (5% steps)")
    print("=" * 70)
    grid_results, best_mix = grid_search_2asset(prices, eval_start)

    print(f"\n  Best mix by Sharpe: SPY {best_mix[0]}% / GLD {best_mix[1]}%")
    print("\n  Full grid:")
    print(f"  {'SPY%':>5s} {'GLD%':>5s} {'Sharpe':>8s} {'CAGR%':>8s} {'MDD%':>8s} {'Calmar':>8s} {'Vol%':>8s}")
    for g in grid_results:
        marker = " <-- BEST" if (g["spy_pct"], g["gld_pct"]) == best_mix else ""
        print(f"  {g['spy_pct']:5d} {g['gld_pct']:5d} {g['sharpe']:8.3f} {g['cagr_pct']:8.2f} "
              f"{g['mdd_pct']:8.2f} {g['calmar']:8.3f} {g['ann_vol_pct']:8.2f}{marker}")

    # 7. Cross-OOS for top 3
    print("\n" + "=" * 70)
    print("CROSS-OOS EVALUATION (5 periods)")
    print("=" * 70)

    # Take top 3 by full-sample Sharpe + always include 50/50 as reference
    top3_names = [m["strategy"] for m in all_metrics[:3]]
    if benchmark_name not in top3_names:
        top3_names.append(benchmark_name)

    oos_allocations = {name: allocations[name] for name in top3_names}
    oos_results = cross_oos_evaluation(prices, oos_allocations)

    for name, res in oos_results.items():
        print(f"\n  {name}:")
        for i, period in enumerate(res["periods"]):
            print(f"    {period}: Sharpe={res['sharpes'][i]:.3f}  "
                  f"CAGR={res['cagrs'][i]:.2f}%  MDD={res['mdds'][i]:.2f}%")
        print(f"    --- Mean Sharpe={res['mean_sharpe']:.3f} (std={res['std_sharpe']:.3f}), "
              f"Min={res['min_sharpe']:.3f}, Mean MDD={res['mean_mdd']:.2f}%, "
              f"Worst MDD={res['worst_mdd']:.2f}%")

    # Cross-OOS: which wins in most periods?
    print("\n  --- Cross-OOS Winner by Period ---")
    period_winners = []
    for p_idx in range(len(OOS_PERIODS)):
        best_name = None
        best_s = -999
        for name, res in oos_results.items():
            if p_idx < len(res["sharpes"]) and res["sharpes"][p_idx] > best_s:
                best_s = res["sharpes"][p_idx]
                best_name = name
        period_winners.append(best_name)
        print(f"    {oos_results[list(oos_results.keys())[0]]['periods'][p_idx]}: "
              f"{best_name} (Sharpe={best_s:.3f})")

    from collections import Counter
    win_counts = Counter(period_winners)
    print(f"\n  Win counts: {dict(win_counts)}")

    # 8. Compile results
    print("\n" + "=" * 70)
    print("SUMMARY & CONCLUSIONS")
    print("=" * 70)

    # Identify the overall winner
    winner = all_metrics[0]
    beats_5050 = winner["strategy"] != benchmark_name

    if beats_5050:
        diff_sharpe = winner["sharpe"] - [m for m in all_metrics if m["strategy"] == benchmark_name][0]["sharpe"]
        print(f"\n  WINNER: {winner['strategy']} (Sharpe={winner['sharpe']:.3f})")
        print(f"  Improvement over 50/50: {diff_sharpe:+.3f} Sharpe points")
    else:
        print(f"\n  50/50 SPY/GLD remains the best static allocation (Sharpe={winner['sharpe']:.3f})")

    # Check if any DM test is significant
    any_significant = any(d["significant_5pct"] for d in dm_results)
    any_harvey = any(d["significant_harvey"] for d in dm_results)
    print(f"  Any DM test significant at 5%? {any_significant}")
    print(f"  Any DM test passes Harvey t>3.0? {any_harvey}")

    # Limitations
    print("\n  LIMITATIONS:")
    print("  - Risk Parity weights estimated on 2006-2007 only (may not reflect current regime)")
    print("  - Markowitz estimated on first half (well-known overfitting issue)")
    print("  - Annual rebalance assumes costless timing; real-world may differ")
    print("  - TLT started Nov 2002 — full history available but short vs SPY")
    print("  - EFA exposed to currency risk (USD/basket) not hedged")
    print("  - No inflation adjustment; real returns may rank differently")

    # Save results
    results = {
        "experiment_id": "K702",
        "title": "Optimal Static Asset Allocation — Beyond 50/50 SPY/GLD",
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "description": (
            "Tests 8 static allocations (SPY/GLD/TLT/EFA) to determine if 50/50 SPY/GLD "
            "is truly optimal. Includes grid search (SPY/GLD 0-100%), risk parity, "
            "Markowitz MV-optimal, and cross-OOS validation across 5 periods."
        ),
        "data_source": "yfinance",
        "data_period": f"{START_DATE} to {END_DATE}",
        "eval_period": f"{eval_start} to {END_DATE}",
        "configuration": {
            "tickers": TICKERS,
            "rf_annual": RF_ANNUAL,
            "tx_cost_bps": TX_COST_BPS,
            "rebalance_freq": "annual",
            "bootstrap_reps": BOOTSTRAP_REPS,
            "risk_parity_estimation": f"through {rp_estimation_end}",
            "markowitz_estimation": f"through {mid_date}",
        },
        "descriptive_stats": {
            t: {
                "ann_return_pct": round(((1 + rets[t]).prod() ** (252/len(rets[t])) - 1) * 100, 2),
                "ann_vol_pct": round(rets[t].std() * np.sqrt(252) * 100, 2),
                "sharpe": round(
                    (((1 + rets[t]).prod() ** (252/len(rets[t])) - 1) - RF_ANNUAL)
                    / (rets[t].std() * np.sqrt(252)), 3
                ),
                "skewness": round(float(rets[t].skew()), 3),
                "kurtosis": round(float(rets[t].kurtosis()), 3),
            }
            for t in TICKERS
        },
        "correlation_matrix": corr.round(4).to_dict(),
        "full_sample_ranking": all_metrics,
        "bootstrap_sharpe_ci": bootstrap_results,
        "dm_tests_vs_5050": dm_results,
        "grid_search_spy_gld": {
            "best_mix": {"SPY_pct": best_mix[0], "GLD_pct": best_mix[1]},
            "full_grid": grid_results,
        },
        "cross_oos": {
            name: {
                "periods": res["periods"],
                "sharpes": res["sharpes"],
                "cagrs": res["cagrs"],
                "mdds": res["mdds"],
                "mean_sharpe": res["mean_sharpe"],
                "std_sharpe": res["std_sharpe"],
                "min_sharpe": res["min_sharpe"],
                "mean_mdd": res["mean_mdd"],
                "worst_mdd": res["worst_mdd"],
            }
            for name, res in oos_results.items()
        },
        "cross_oos_period_winners": period_winners,
        "cross_oos_win_counts": dict(win_counts),
        "risk_parity_weights": rp_weights,
        "markowitz_weights": mk_weights,
        "key_findings": {
            "winner_full_sample": winner["strategy"],
            "winner_sharpe": winner["sharpe"],
            "beats_5050": beats_5050,
            "any_dm_significant_5pct": any_significant,
            "any_dm_harvey_significant": any_harvey,
            "optimal_spy_gld_mix": f"SPY {best_mix[0]}% / GLD {best_mix[1]}%",
        },
        "references": [
            "K687: Post-Correction Definitive Strategy Ranking (BH 50/50 Sharpe=0.545)",
            "K646: Cross-OOS 80/20 vs 50/50",
            "K645: GLD Role Analysis — optimal 20% with VT",
            "Markowitz (1952), Portfolio Selection, JoF",
            "Maillard, Roncalli & Teiletche (2010), Equally Weighted Risk Contributions, JPM",
            "DeMiguel, Garlappi & Uppal (2009), Optimal vs Naive Diversification, RFS",
            "Asness, Frazzini & Pedersen (2012), Leverage Aversion and Risk Parity, FAJ",
        ],
        "limitations": [
            "Risk Parity weights estimated on 2006-2007 only",
            "Markowitz in-sample optimization overfits (well-documented)",
            "Annual rebalance; real-world trading may differ",
            "No inflation adjustment",
            "EFA has unhedged currency exposure",
            "Survivorship bias: we test assets that 'survived' to 2026",
        ],
    }

    out_path = Path(__file__).parent / "k702_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {out_path}")

    return results


if __name__ == "__main__":
    results = main()
