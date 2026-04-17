#!/usr/bin/env python3
"""K116: Tail Risk Parity Portfolio — GARCH CVaR-based Risk Budgeting

Background:
  - K2 proved 50/50 SPY/GLD beats all variance-based optimizers (RP, MinVar, MaxSharpe, BL)
  - But those all use variance as the risk measure
  - Tail Risk Parity (TRP) uses CVaR/ES instead of variance for risk budgeting
  - Hypothesis: If investors truly care about tail risk, ES-based weights may outperform

Methods:
  1. Variance-based Risk Parity (inverse volatility)
  2. CVaR-based Tail Risk Parity (inverse GARCH-Skewed-t ES)
  3. VaR-based Risk Parity (inverse GARCH-Skewed-t VaR)
  4. Static 50/50 baseline (the "unbeatable" benchmark from K2)

Asset universes:
  A. SPY + GLD (2 assets)
  B. SPY + GLD + TLT (3 assets)

Rebalancing: Monthly (K48/J10 optimal)
OOS: 2015-01-01 ~ 2024-12-31 (10 years)

Author: VolPred Research System
Date: 2026-03-22
Experiment: K116
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from arch.univariate.distribution import SkewStudent
from scipy import stats
from scipy.integrate import trapezoid

warnings.filterwarnings("ignore")

# ============================================================================
# Configuration
# ============================================================================
GARCH_WINDOW = 2000       # Rolling window for GARCH fitting
START_DATE = "2005-01-01"  # Need enough history for GARCH warmup before 2015
END_DATE = "2025-12-31"
OOS_START = "2015-01-01"
OOS_END = "2024-12-31"
ES_ALPHA = 0.05            # 5% CVaR/ES (standard for portfolio risk budgeting)
VAR_ALPHA = 0.05           # 5% VaR
TX_COST_BPS = 5            # 5 bps per trade (monthly rebalancing)
N_BOOTSTRAP = 5000         # Bootstrap replications for MDD comparison
SEED = 42

ASSETS_2 = ["SPY", "GLD"]
ASSETS_3 = ["SPY", "GLD", "TLT"]

CRISIS_PERIODS = {
    "COVID-2020": ("2020-02-19", "2020-03-23"),
    "Rate_Hike_2022": ("2022-01-03", "2022-10-12"),
    "SVB_2023": ("2023-03-08", "2023-03-15"),
    "Aug_2024_Selloff": ("2024-07-16", "2024-08-05"),
}


# ============================================================================
# Data Download
# ============================================================================
def download_data(assets):
    """Download price data for assets."""
    print(f"Downloading data for {assets}...")
    all_prices = {}
    for asset in assets:
        df = yf.download(asset, start=START_DATE, end=END_DATE,
                         progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        all_prices[asset] = df["Close"]

    prices = pd.DataFrame(all_prices).dropna()
    returns = prices.pct_change().dropna()
    print(f"  Data range: {returns.index[0].date()} to {returns.index[-1].date()}, "
          f"{len(returns)} days, {len(assets)} assets")
    return prices, returns


# ============================================================================
# GARCH-Skewed-t Fitting + ES/VaR Computation
# ============================================================================
def fit_gjr_skewt(returns_pct):
    """Fit GJR-GARCH(1,1) with Skewed-t distribution.

    Args:
        returns_pct: returns in percentage (already *100)

    Returns:
        result: arch model result object
    """
    model = arch_model(
        returns_pct, vol="GARCH", p=1, o=1, q=1,
        dist="skewt", mean="Zero", rescale=False
    )
    result = model.fit(disp="off", show_warning=False)
    return result


def compute_skewt_es(sigma, eta, lam, alpha=0.05):
    """Compute ES (CVaR) under Hansen's Skewed-t distribution.

    Args:
        sigma: daily volatility (decimal, not %)
        eta: degrees of freedom (>2)
        lam: skewness parameter (-1 < lam < 1)
        alpha: significance level

    Returns:
        es: Expected Shortfall (positive number = loss)
    """
    skewt = SkewStudent()
    params = np.array([eta, lam])

    # ES via numerical integration: ES = -(1/alpha) * integral_0^alpha ppf(u) du
    n_int = 5000
    u = np.linspace(1e-10, alpha, n_int)
    x_vals = skewt.ppf(u, parameters=params)
    es_std = -trapezoid(x_vals, u) / alpha  # positive (standardized)
    es = es_std * sigma

    return es


def compute_skewt_var(sigma, eta, lam, alpha=0.05):
    """Compute VaR under Hansen's Skewed-t distribution.

    Args:
        sigma: daily volatility (decimal)
        eta: degrees of freedom (>2)
        lam: skewness parameter (-1 < lam < 1)
        alpha: significance level

    Returns:
        var: Value-at-Risk (positive number = loss)
    """
    skewt = SkewStudent()
    params = np.array([eta, lam])
    q = skewt.ppf(alpha, parameters=params)  # negative quantile
    var = -q * sigma
    return var


def rolling_garch_risk_estimates(returns_series, window=2000):
    """Compute rolling GARCH-Skewed-t volatility, ES, and VaR for a single asset.

    Returns DataFrame with columns: sigma, es_5pct, var_5pct
    """
    returns_pct = returns_series * 100  # GARCH needs percentage returns

    results = []
    dates = returns_series.index

    # We need at least `window` observations before we start
    print(f"    Computing rolling GARCH estimates ({len(dates) - window} forecasts)...")
    total = len(dates) - window
    for i in range(window, len(dates)):
        if (i - window) % 500 == 0:
            print(f"      Progress: {i - window}/{total}")

        train = returns_pct.iloc[i - window:i]
        try:
            res = fit_gjr_skewt(train)
            # One-step-ahead forecast
            forecast = res.forecast(horizon=1)
            sigma_pct = np.sqrt(forecast.variance.values[-1, 0])
            sigma = sigma_pct / 100  # Convert to decimal

            # Extract distribution parameters
            eta = res.params.get("eta", 5.0)  # df
            lam = res.params.get("lambda", 0.0)  # skewness

            es = compute_skewt_es(sigma, eta, lam, alpha=ES_ALPHA)
            var = compute_skewt_var(sigma, eta, lam, alpha=VAR_ALPHA)

            results.append({
                "date": dates[i],
                "sigma": sigma,
                "es_5pct": es,
                "var_5pct": var,
                "eta": eta,
                "lam": lam,
            })
        except Exception:
            # If GARCH fails, use EWMA fallback
            ewma_var = train.ewm(span=60).var().iloc[-1]
            sigma = np.sqrt(ewma_var) / 100
            # Use normal approximation for ES/VaR
            es = sigma * stats.norm.pdf(stats.norm.ppf(ES_ALPHA)) / ES_ALPHA
            var = -stats.norm.ppf(VAR_ALPHA) * sigma
            results.append({
                "date": dates[i],
                "sigma": sigma,
                "es_5pct": es,
                "var_5pct": var,
                "eta": 5.0,
                "lam": 0.0,
            })

    df = pd.DataFrame(results).set_index("date")
    return df


# ============================================================================
# Portfolio Construction Methods
# ============================================================================
def static_equal_weight(n_assets):
    """Static equal weight (e.g., 50/50 or 33/33/33)."""
    return np.ones(n_assets) / n_assets


def variance_risk_parity(sigmas):
    """Variance-based Risk Parity: inverse volatility weighting.

    w_i = (1/sigma_i) / sum(1/sigma_j)
    """
    inv_vol = 1.0 / sigmas
    weights = inv_vol / inv_vol.sum()
    return weights


def cvar_tail_risk_parity(es_values):
    """CVaR-based Tail Risk Parity: inverse ES weighting.

    w_i = (1/ES_i) / sum(1/ES_j)
    """
    inv_es = 1.0 / es_values
    weights = inv_es / inv_es.sum()
    return weights


def var_risk_parity(var_values):
    """VaR-based Risk Parity: inverse VaR weighting.

    w_i = (1/VaR_i) / sum(1/VaR_j)
    """
    inv_var = 1.0 / var_values
    weights = inv_var / inv_var.sum()
    return weights


# ============================================================================
# Backtest Engine
# ============================================================================
def backtest_monthly_rebalance(returns, weight_func, risk_estimates_dict,
                               strategy_name, tx_cost_bps=5):
    """Run monthly rebalanced portfolio backtest.

    Args:
        returns: DataFrame of daily returns for all assets
        weight_func: function(risk_dict_at_date) -> weights array
        risk_estimates_dict: {asset: DataFrame with sigma/es/var columns}
        strategy_name: name for logging
        tx_cost_bps: transaction cost in basis points per rebalance

    Returns:
        DataFrame with portfolio returns and weights
    """
    oos_returns = returns.loc[OOS_START:OOS_END]
    assets = list(returns.columns)
    n_assets = len(assets)

    # Get monthly rebalance dates (last trading day of each month)
    monthly_dates = oos_returns.resample("ME").last().index
    # We need a rebalance schedule: rebalance at end of each month
    rebalance_months = pd.Series(oos_returns.index).dt.to_period("M").unique()

    portfolio_returns = []
    weight_history = []
    current_weights = np.ones(n_assets) / n_assets  # Start equal weight

    prev_month = None
    for date in oos_returns.index:
        current_month = date.to_period("M")

        # Rebalance at start of each new month
        if current_month != prev_month:
            # Get risk estimates for this date (or closest prior)
            risk_at_date = {}
            valid = True
            for asset in assets:
                if asset in risk_estimates_dict:
                    df = risk_estimates_dict[asset]
                    mask = df.index <= date
                    if mask.any():
                        latest = df.loc[mask].iloc[-1]
                        risk_at_date[asset] = latest
                    else:
                        valid = False
                        break
                else:
                    valid = False
                    break

            if valid:
                new_weights = weight_func(risk_at_date, assets)

                # Transaction cost
                turnover = np.abs(new_weights - current_weights).sum()
                tc = turnover * tx_cost_bps / 10000

                current_weights = new_weights
            else:
                tc = 0.0
            prev_month = current_month
        else:
            tc = 0.0

        # Daily portfolio return
        daily_ret = oos_returns.loc[date].values
        port_ret = np.sum(current_weights * daily_ret) - tc

        portfolio_returns.append({
            "date": date,
            "portfolio_return": port_ret,
            **{f"w_{a}": current_weights[i] for i, a in enumerate(assets)},
        })

    result = pd.DataFrame(portfolio_returns).set_index("date")
    return result


# ============================================================================
# Weight Functions (closures for backtest engine)
# ============================================================================
def make_static_weight_func(n_assets):
    def func(risk_at_date, assets):
        return np.ones(n_assets) / n_assets
    return func


def make_var_rp_weight_func():
    def func(risk_at_date, assets):
        sigmas = np.array([risk_at_date[a]["sigma"] for a in assets])
        sigmas = np.maximum(sigmas, 1e-8)  # Floor to avoid division by zero
        return variance_risk_parity(sigmas)
    return func


def make_cvar_trp_weight_func():
    def func(risk_at_date, assets):
        es_values = np.array([risk_at_date[a]["es_5pct"] for a in assets])
        es_values = np.maximum(es_values, 1e-8)
        return cvar_tail_risk_parity(es_values)
    return func


def make_var_based_rp_weight_func():
    def func(risk_at_date, assets):
        var_values = np.array([risk_at_date[a]["var_5pct"] for a in assets])
        var_values = np.maximum(var_values, 1e-8)
        return var_risk_parity(var_values)
    return func


# ============================================================================
# Performance Metrics
# ============================================================================
def compute_metrics(returns_series, rf_annual=0.04):
    """Compute comprehensive performance metrics."""
    daily_rf = rf_annual / 252
    excess = returns_series - daily_rf

    ann_ret = returns_series.mean() * 252
    ann_vol = returns_series.std() * np.sqrt(252)
    sharpe = excess.mean() / returns_series.std() * np.sqrt(252) if returns_series.std() > 0 else 0

    # MDD
    cum = (1 + returns_series).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns_series[returns_series < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-8
    sortino = (ann_ret - rf_annual) / downside_std

    # Tail metrics
    worst_month = returns_series.resample("ME").sum().min()
    skewness = returns_series.skew()
    kurtosis = returns_series.kurtosis()

    # VaR/ES at 5%
    var_5 = -np.percentile(returns_series, 5)
    es_5 = -returns_series[returns_series <= -var_5].mean() if (returns_series <= -var_5).any() else var_5

    # Win rate
    win_rate = (returns_series > 0).mean()

    # Annual turnover (estimated from weight changes - computed outside)

    n_years = len(returns_series) / 252
    sharpe_se = 1 / np.sqrt(n_years)
    sharpe_t = sharpe / sharpe_se if sharpe_se > 0 else 0

    return {
        "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "sharpe_t": round(sharpe_t, 2),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "worst_month": round(worst_month * 100, 2),
        "skewness": round(skewness, 3),
        "kurtosis": round(kurtosis, 2),
        "var_5pct": round(var_5 * 100, 3),
        "es_5pct": round(es_5 * 100, 3),
        "win_rate": round(win_rate * 100, 1),
    }


def diebold_mariano_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive accuracy.

    Here we use squared returns difference as loss differential.
    Positive t-stat means e2 is worse (e1 is better).
    """
    d = e1 ** 2 - e2 ** 2
    d_mean = d.mean()
    # Newey-West with h-1 lags
    T = len(d)
    gamma0 = np.var(d, ddof=1)
    nw_var = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * (1 - k / h) * gamma_k

    se = np.sqrt(nw_var / T)
    if se < 1e-12:
        return 0.0, 1.0
    t_stat = d_mean / se
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value


def bootstrap_mdd_comparison(ret1, ret2, n_boot=5000, seed=42):
    """Bootstrap test: is MDD(ret1) significantly less severe than MDD(ret2)?

    Returns p-value for H0: MDD(ret1) >= MDD(ret2).
    """
    rng = np.random.RandomState(seed)
    T = len(ret1)

    def calc_mdd(r):
        cum = np.cumprod(1 + r)
        peak = np.maximum.accumulate(cum)
        dd = (cum - peak) / peak
        return dd.min()

    actual_diff = calc_mdd(ret1.values) - calc_mdd(ret2.values)

    # Block bootstrap (block size = 21 trading days ~ 1 month)
    block_size = 21
    n_blocks = T // block_size + 1
    count_better = 0

    for _ in range(n_boot):
        # Sample blocks with replacement
        block_starts = rng.randint(0, T - block_size, size=n_blocks)
        indices = np.concatenate([np.arange(s, s + block_size) for s in block_starts])[:T]

        boot_r1 = ret1.values[indices]
        boot_r2 = ret2.values[indices]

        diff = calc_mdd(boot_r1) - calc_mdd(boot_r2)
        if diff > 0:
            count_better += 1

    p_value = count_better / n_boot
    return actual_diff, p_value


# ============================================================================
# Crisis Analysis
# ============================================================================
def crisis_analysis(portfolios, crisis_periods):
    """Analyze portfolio performance during crisis periods."""
    print("\n" + "=" * 80)
    print("CRISIS PERIOD ANALYSIS")
    print("=" * 80)

    results = {}
    for crisis_name, (start, end) in crisis_periods.items():
        print(f"\n  {crisis_name} ({start} to {end}):")
        crisis_results = {}
        for strat_name, port_df in portfolios.items():
            mask = (port_df.index >= start) & (port_df.index <= end)
            if mask.sum() == 0:
                continue
            crisis_ret = port_df.loc[mask, "portfolio_return"]
            cum_ret = (1 + crisis_ret).prod() - 1
            crisis_mdd = ((1 + crisis_ret).cumprod() / (1 + crisis_ret).cumprod().cummax() - 1).min()
            crisis_vol = crisis_ret.std() * np.sqrt(252)

            crisis_results[strat_name] = {
                "cum_return": round(cum_ret * 100, 2),
                "mdd": round(crisis_mdd * 100, 2),
                "ann_vol": round(crisis_vol * 100, 2),
            }
            print(f"    {strat_name:30s}: Return={cum_ret*100:+6.2f}%, "
                  f"MDD={crisis_mdd*100:+6.2f}%, Vol={crisis_vol*100:5.1f}%")

        results[crisis_name] = crisis_results
    return results


# ============================================================================
# Weight Analysis
# ============================================================================
def analyze_weights(portfolios, assets):
    """Analyze weight characteristics across strategies."""
    print("\n" + "=" * 80)
    print("WEIGHT ANALYSIS")
    print("=" * 80)

    weight_stats = {}
    for strat_name, port_df in portfolios.items():
        w_cols = [f"w_{a}" for a in assets]
        weights = port_df[w_cols]

        # Monthly weight changes
        monthly_w = weights.resample("ME").last()
        monthly_changes = monthly_w.diff().abs()

        avg_weights = weights.mean()
        std_weights = weights.std()
        avg_turnover = monthly_changes.sum(axis=1).mean()

        stats_dict = {}
        print(f"\n  {strat_name}:")
        for a in assets:
            col = f"w_{a}"
            stats_dict[a] = {
                "mean": round(avg_weights[col] * 100, 1),
                "std": round(std_weights[col] * 100, 1),
                "min": round(weights[col].min() * 100, 1),
                "max": round(weights[col].max() * 100, 1),
            }
            print(f"    {a}: mean={avg_weights[col]*100:5.1f}%, "
                  f"std={std_weights[col]*100:5.1f}%, "
                  f"range=[{weights[col].min()*100:4.1f}%, {weights[col].max()*100:4.1f}%]")

        stats_dict["avg_monthly_turnover"] = round(avg_turnover * 100, 2)
        print(f"    Avg monthly turnover: {avg_turnover*100:.2f}%")
        weight_stats[strat_name] = stats_dict

    return weight_stats


# ============================================================================
# Main Experiment
# ============================================================================
def run_experiment(assets, universe_name):
    """Run the full TRP experiment for a given asset universe."""
    print(f"\n{'#' * 80}")
    print(f"# UNIVERSE: {universe_name} — {assets}")
    print(f"{'#' * 80}")

    # 1. Download data
    prices, returns = download_data(assets)

    # 2. Compute rolling GARCH risk estimates for each asset
    print(f"\n--- Computing GARCH-Skewed-t risk estimates ---")
    risk_estimates = {}
    for asset in assets:
        print(f"  Asset: {asset}")
        risk_df = rolling_garch_risk_estimates(returns[asset], window=GARCH_WINDOW)
        risk_estimates[asset] = risk_df
        print(f"    Estimates computed: {len(risk_df)} days")
        print(f"    Avg sigma: {risk_df['sigma'].mean()*100:.2f}%")
        print(f"    Avg ES(5%): {risk_df['es_5pct'].mean()*100:.2f}%")
        print(f"    Avg VaR(5%): {risk_df['var_5pct'].mean()*100:.2f}%")
        print(f"    Avg eta (df): {risk_df['eta'].mean():.2f}")
        print(f"    Avg lambda (skew): {risk_df['lam'].mean():.3f}")

    # 3. Run backtests
    print(f"\n--- Running backtests ---")
    strategies = {
        f"Static_Equal_{universe_name}": make_static_weight_func(len(assets)),
        f"Var_RP_{universe_name}": make_var_rp_weight_func(),
        f"CVaR_TRP_{universe_name}": make_cvar_trp_weight_func(),
        f"VaR_Based_RP_{universe_name}": make_var_based_rp_weight_func(),
    }

    portfolios = {}
    for strat_name, weight_func in strategies.items():
        print(f"  Backtesting: {strat_name}")
        port_df = backtest_monthly_rebalance(
            returns, weight_func, risk_estimates,
            strat_name, tx_cost_bps=TX_COST_BPS
        )
        portfolios[strat_name] = port_df
        print(f"    Days: {len(port_df)}")

    # 4. Compute metrics
    print(f"\n--- Performance Metrics (OOS: {OOS_START} to {OOS_END}) ---")
    all_metrics = {}
    for strat_name, port_df in portfolios.items():
        metrics = compute_metrics(port_df["portfolio_return"])
        all_metrics[strat_name] = metrics

    # Print comparison table
    print(f"\n{'Strategy':<35s} {'Sharpe':>7s} {'MDD':>8s} {'Calmar':>8s} "
          f"{'Sortino':>8s} {'Worst_Mo':>9s} {'Skew':>6s} {'Kurt':>6s} "
          f"{'ES(5%)':>7s} {'Ret%':>6s} {'Vol%':>6s}")
    print("-" * 120)
    for strat_name, m in all_metrics.items():
        print(f"{strat_name:<35s} {m['sharpe']:>7.3f} {m['mdd']:>7.2f}% "
              f"{m['calmar']:>8.3f} {m['sortino']:>8.3f} {m['worst_month']:>8.2f}% "
              f"{m['skewness']:>6.3f} {m['kurtosis']:>6.2f} {m['es_5pct']:>6.3f}% "
              f"{m['ann_return']:>5.2f}% {m['ann_vol']:>5.2f}%")

    # 5. Statistical tests
    print(f"\n--- Statistical Tests ---")
    static_key = f"Static_Equal_{universe_name}"
    static_ret = portfolios[static_key]["portfolio_return"]
    test_results = {}

    for strat_name, port_df in portfolios.items():
        if strat_name == static_key:
            continue
        strat_ret = port_df["portfolio_return"]

        # Align
        common_idx = static_ret.index.intersection(strat_ret.index)
        s1 = static_ret.loc[common_idx]
        s2 = strat_ret.loc[common_idx]

        # DM test (using returns as "forecast errors")
        dm_t, dm_p = diebold_mariano_test(s1, s2)

        # Bootstrap MDD comparison
        mdd_diff, mdd_p = bootstrap_mdd_comparison(s2, s1, n_boot=N_BOOTSTRAP, seed=SEED)

        test_results[strat_name] = {
            "dm_t_vs_static": round(dm_t, 3),
            "dm_p_vs_static": round(dm_p, 4),
            "mdd_diff_vs_static": round(mdd_diff * 100, 2),
            "mdd_p_vs_static": round(mdd_p, 4),
        }

        print(f"\n  {strat_name} vs {static_key}:")
        print(f"    DM test: t={dm_t:.3f}, p={dm_p:.4f} "
              f"{'*' if dm_p < 0.05 else '(NS)'}")
        print(f"    Bootstrap MDD: diff={mdd_diff*100:+.2f}%, p={mdd_p:.4f} "
              f"{'*' if mdd_p < 0.05 else '(NS)'}")

    # 6. Crisis analysis
    crisis_results = crisis_analysis(portfolios, CRISIS_PERIODS)

    # 7. Weight analysis
    weight_stats = analyze_weights(portfolios, assets)

    # 8. Pairwise comparisons between RP methods
    print(f"\n--- Pairwise RP Method Comparisons ---")
    rp_keys = [k for k in portfolios.keys() if k != static_key]
    pairwise_results = {}
    for i, k1 in enumerate(rp_keys):
        for k2 in rp_keys[i + 1:]:
            r1 = portfolios[k1]["portfolio_return"]
            r2 = portfolios[k2]["portfolio_return"]
            common_idx = r1.index.intersection(r2.index)
            dm_t, dm_p = diebold_mariano_test(r1.loc[common_idx], r2.loc[common_idx])
            mdd_diff, mdd_p = bootstrap_mdd_comparison(
                r1.loc[common_idx], r2.loc[common_idx],
                n_boot=N_BOOTSTRAP, seed=SEED
            )
            key = f"{k1}_vs_{k2}"
            pairwise_results[key] = {
                "dm_t": round(dm_t, 3),
                "dm_p": round(dm_p, 4),
                "mdd_diff": round(mdd_diff * 100, 2),
                "mdd_p": round(mdd_p, 4),
            }
            print(f"  {k1} vs {k2}:")
            print(f"    DM: t={dm_t:.3f}, p={dm_p:.4f}")
            print(f"    MDD diff: {mdd_diff*100:+.2f}%, p={mdd_p:.4f}")

    return {
        "universe": universe_name,
        "assets": assets,
        "metrics": all_metrics,
        "tests_vs_static": test_results,
        "pairwise_tests": pairwise_results,
        "crisis_analysis": crisis_results,
        "weight_stats": weight_stats,
    }


def main():
    print("=" * 80)
    print("K116: TAIL RISK PARITY PORTFOLIO")
    print("GARCH-Skewed-t CVaR-based Risk Budgeting")
    print(f"OOS: {OOS_START} to {OOS_END}")
    print(f"Rebalancing: Monthly, TX cost: {TX_COST_BPS} bps")
    print(f"ES/VaR alpha: {ES_ALPHA}")
    print("=" * 80)

    results = {}

    # Run for 2-asset universe
    results["2_asset"] = run_experiment(ASSETS_2, "2A")

    # Run for 3-asset universe
    results["3_asset"] = run_experiment(ASSETS_3, "3A")

    # ========================================================================
    # Summary
    # ========================================================================
    print("\n" + "=" * 80)
    print("FINAL SUMMARY: K116 Tail Risk Parity")
    print("=" * 80)

    for uname, res in results.items():
        print(f"\n--- {uname} ({res['assets']}) ---")
        static_key = [k for k in res["metrics"] if "Static" in k][0]
        static_sharpe = res["metrics"][static_key]["sharpe"]
        static_mdd = res["metrics"][static_key]["mdd"]

        for strat, m in res["metrics"].items():
            sharpe_diff = m["sharpe"] - static_sharpe
            mdd_diff = m["mdd"] - static_mdd
            marker = ""
            if strat in res["tests_vs_static"]:
                t = res["tests_vs_static"][strat]
                if t["dm_p_vs_static"] < 0.05:
                    marker += " *DM"
                if t["mdd_p_vs_static"] < 0.05:
                    marker += " *MDD"
            print(f"  {strat:<35s}: Sharpe={m['sharpe']:.3f} (delta={sharpe_diff:+.3f}), "
                  f"MDD={m['mdd']:.2f}% (delta={mdd_diff:+.2f}%){marker}")

    # Key question: Does TRP outperform variance RP or static?
    print("\n--- KEY FINDINGS ---")
    for uname, res in results.items():
        metrics = res["metrics"]
        trp_key = [k for k in metrics if "CVaR_TRP" in k][0]
        vrp_key = [k for k in metrics if "Var_RP" in k][0]
        static_key = [k for k in metrics if "Static" in k][0]

        trp = metrics[trp_key]
        vrp = metrics[vrp_key]
        static = metrics[static_key]

        print(f"\n  {uname}:")
        print(f"    CVaR TRP Sharpe: {trp['sharpe']:.3f} vs Var RP: {vrp['sharpe']:.3f} "
              f"vs Static: {static['sharpe']:.3f}")
        print(f"    CVaR TRP MDD: {trp['mdd']:.2f}% vs Var RP: {vrp['mdd']:.2f}% "
              f"vs Static: {static['mdd']:.2f}%")
        print(f"    CVaR TRP ES(5%): {trp['es_5pct']:.3f}% vs Var RP: {vrp['es_5pct']:.3f}% "
              f"vs Static: {static['es_5pct']:.3f}%")
        print(f"    CVaR TRP worst month: {trp['worst_month']:.2f}% vs Var RP: "
              f"{vrp['worst_month']:.2f}% vs Static: {static['worst_month']:.2f}%")

    # ========================================================================
    # Save results
    # ========================================================================
    output = {
        "experiment": "K116",
        "title": "Tail Risk Parity Portfolio",
        "date": datetime.now().isoformat(),
        "config": {
            "garch_window": GARCH_WINDOW,
            "oos_start": OOS_START,
            "oos_end": OOS_END,
            "es_alpha": ES_ALPHA,
            "var_alpha": VAR_ALPHA,
            "tx_cost_bps": TX_COST_BPS,
            "n_bootstrap": N_BOOTSTRAP,
            "rebalancing": "monthly",
        },
        "results": {},
    }

    for uname, res in results.items():
        output["results"][uname] = {
            "universe": res["universe"],
            "assets": res["assets"],
            "metrics": res["metrics"],
            "tests_vs_static": res["tests_vs_static"],
            "pairwise_tests": res["pairwise_tests"],
            "crisis_analysis": res["crisis_analysis"],
            "weight_stats": res["weight_stats"],
        }

    output_path = Path(__file__).parent / "tail_risk_parity_results.json"
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == "__main__":
    main()
