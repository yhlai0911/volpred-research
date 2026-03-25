#!/usr/bin/env python3
"""
K411: Pure Sector Momentum — Which Sectors Lead and Follow?
==========================================================
[提出: User, 執行: Claude]

A completely different direction from VT/VIX/GARCH research.
Investigates sector momentum, leadership persistence, lead-lag structure,
and economic cycle rotation using US sector ETFs.

Data: yfinance sector ETFs (2005-2024), monthly frequency.
NO VIX, NO GARCH, NO VT, NO 50/50.
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────
# 0. Configuration
# ─────────────────────────────────────────────
SECTORS = {
    "XLK": "Technology",
    "XLF": "Financials",
    "XLE": "Energy",
    "XLV": "Healthcare",
    "XLY": "Consumer Disc",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLI": "Industrials",
    "XLC": "Communication",
    "XLRE": "Real Estate",
}

START = "2005-01-01"
END = "2024-12-31"
TX_COST_BPS = 10  # one-way transaction cost
MOMENTUM_WINDOW = 3  # months for momentum ranking
TOP_N = 3  # long top N
BOT_N = 3  # short bottom N
RF_ANNUAL = 0.02  # risk-free rate for Sharpe


def download_data():
    """Download adjusted close prices for all sector ETFs."""
    tickers = list(SECTORS.keys())
    print(f"Downloading {len(tickers)} sector ETFs: {', '.join(tickers)}")
    data = yf.download(tickers, start=START, end=END, auto_adjust=True, progress=False)

    # Handle multi-level columns from yfinance
    if isinstance(data.columns, pd.MultiIndex):
        prices = data["Close"]
    else:
        prices = data

    # Drop any columns that are all NaN
    prices = prices.dropna(axis=1, how="all")

    print(f"Data range: {prices.index[0].strftime('%Y-%m-%d')} to {prices.index[-1].strftime('%Y-%m-%d')}")
    print(f"Tickers with data: {list(prices.columns)}")

    # Note: XLC launched 2018-06, XLRE launched 2015-10
    for col in prices.columns:
        first_valid = prices[col].first_valid_index()
        if first_valid is not None:
            print(f"  {col} ({SECTORS.get(col, '?')}): from {first_valid.strftime('%Y-%m-%d')}")

    return prices


def compute_monthly_returns(prices):
    """Resample to month-end and compute returns."""
    monthly = prices.resample("ME").last()
    returns = monthly.pct_change().dropna(how="all")
    return returns


# ─────────────────────────────────────────────
# 1. Sector Momentum Strategy
# ─────────────────────────────────────────────
def sector_momentum_strategy(returns, momentum_window=MOMENTUM_WINDOW, top_n=TOP_N, bot_n=BOT_N):
    """
    Classic sector momentum: rank by trailing N-month return,
    long top_n, short bot_n, equal weight, monthly rebalance.
    """
    # Trailing cumulative return over momentum_window months
    cum_ret = (1 + returns).rolling(window=momentum_window).apply(lambda x: x.prod() - 1, raw=True)

    strategy_returns = []
    dates = []

    for i in range(momentum_window, len(returns)):
        date = returns.index[i]
        # Ranking based on previous month's trailing return
        rank_date = returns.index[i - 1]
        scores = cum_ret.loc[rank_date].dropna()

        if len(scores) < top_n + bot_n:
            continue

        ranked = scores.sort_values(ascending=False)
        longs = ranked.index[:top_n]
        shorts = ranked.index[-bot_n:]

        # Equal weight
        long_ret = returns.loc[date, longs].mean()
        short_ret = returns.loc[date, shorts].mean()

        # Long-short return
        ls_ret = long_ret - short_ret

        strategy_returns.append(ls_ret)
        dates.append(date)

    return pd.Series(strategy_returns, index=dates, name="LS_Momentum")


def evaluate_strategy(returns_series, name="Strategy", rf_annual=RF_ANNUAL, tx_bps=TX_COST_BPS):
    """Compute performance metrics for a return series."""
    # Monthly stats
    n_months = len(returns_series)
    n_years = n_months / 12

    ann_ret = (1 + returns_series.mean()) ** 12 - 1
    ann_vol = returns_series.std() * np.sqrt(12)
    rf_monthly = (1 + rf_annual) ** (1 / 12) - 1

    # Sharpe
    sharpe = (returns_series.mean() - rf_monthly) / returns_series.std() * np.sqrt(12) if returns_series.std() > 0 else 0

    # Transaction cost adjustment: assume full turnover each month (worst case for L/S)
    # Each side has top_n + bot_n positions, assume ~50% turnover per rebalance
    turnover_per_month = 0.5  # conservative estimate
    monthly_tx = turnover_per_month * 2 * (tx_bps / 10000)  # 2x for buy+sell
    net_returns = returns_series - monthly_tx
    net_ann_ret = (1 + net_returns.mean()) ** 12 - 1
    net_sharpe = (net_returns.mean() - rf_monthly) / net_returns.std() * np.sqrt(12) if net_returns.std() > 0 else 0

    # Max drawdown
    cum = (1 + returns_series).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Win rate
    win_rate = (returns_series > 0).mean()

    # Hit ratio by year
    annual = returns_series.resample("YE").apply(lambda x: (1 + x).prod() - 1)
    annual_win = (annual > 0).mean()

    # t-stat for mean return
    t_stat = returns_series.mean() / (returns_series.std() / np.sqrt(n_months)) if returns_series.std() > 0 else 0

    return {
        "name": name,
        "n_months": n_months,
        "n_years": round(n_years, 1),
        "ann_return": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "net_ann_return": round(net_ann_ret * 100, 2),
        "net_sharpe": round(net_sharpe, 3),
        "max_drawdown": round(mdd * 100, 2),
        "monthly_win_rate": round(win_rate * 100, 1),
        "annual_win_rate": round(annual_win * 100, 1),
        "t_stat": round(t_stat, 3),
        "skewness": round(returns_series.skew(), 3),
        "kurtosis": round(returns_series.kurtosis(), 3),
    }


# ─────────────────────────────────────────────
# 2. Sector Leadership Persistence
# ─────────────────────────────────────────────
def leadership_persistence(returns):
    """
    Analyze whether winning sectors keep winning.
    - Monthly rank autocorrelation (Spearman)
    - Regime duration: how many consecutive months does a sector stay in top 3?
    """
    # Monthly rankings (1 = best)
    ranks = returns.rank(axis=1, ascending=False)

    # Spearman rank autocorrelation: correlation of this month's ranks with next month's
    rank_autocorrs = []
    for i in range(len(ranks) - 1):
        r1 = ranks.iloc[i].dropna()
        r2 = ranks.iloc[i + 1].dropna()
        common = r1.index.intersection(r2.index)
        if len(common) >= 5:
            corr, pval = stats.spearmanr(r1[common], r2[common])
            rank_autocorrs.append({"date": ranks.index[i + 1], "corr": corr, "pval": pval})

    autocorr_df = pd.DataFrame(rank_autocorrs)
    mean_autocorr = autocorr_df["corr"].mean()
    sig_frac = (autocorr_df["pval"] < 0.05).mean()

    # Leadership duration: consecutive months in top 3
    in_top3 = ranks <= TOP_N
    leadership_durations = {}

    for sector in in_top3.columns:
        durations = []
        current_streak = 0
        for val in in_top3[sector].dropna():
            if val:
                current_streak += 1
            else:
                if current_streak > 0:
                    durations.append(current_streak)
                current_streak = 0
        if current_streak > 0:
            durations.append(current_streak)

        if durations:
            leadership_durations[sector] = {
                "median_months": float(np.median(durations)),
                "mean_months": round(float(np.mean(durations)), 1),
                "max_months": int(np.max(durations)),
                "n_regimes": len(durations),
                "pct_time_in_top3": round(float(in_top3[sector].mean()) * 100, 1),
            }

    return {
        "mean_rank_autocorrelation": round(mean_autocorr, 4),
        "frac_significant_at_5pct": round(sig_frac, 3),
        "n_months_tested": len(autocorr_df),
        "leadership_durations": leadership_durations,
    }


# ─────────────────────────────────────────────
# 3. Sector Lead-Lag (Granger Causality)
# ─────────────────────────────────────────────
def granger_causality_matrix(returns, max_lag=2):
    """
    Pairwise Granger causality test between all sector pairs.
    Returns a matrix of p-values and identifies "leader" sectors.

    Uses simple OLS F-test implementation to avoid statsmodels dependency issues.
    """
    sectors = [c for c in returns.columns if returns[c].notna().sum() > 24]
    n = len(sectors)

    # Matrix of minimum p-values across lags
    pval_matrix = pd.DataFrame(np.ones((n, n)), index=sectors, columns=sectors)
    fstat_matrix = pd.DataFrame(np.zeros((n, n)), index=sectors, columns=sectors)

    for i, cause in enumerate(sectors):
        for j, effect in enumerate(sectors):
            if i == j:
                continue

            # Get common valid data
            df = pd.DataFrame({"cause": returns[cause], "effect": returns[effect]}).dropna()
            if len(df) < 30:
                continue

            y = df["effect"].values
            x_cause = df["cause"].values

            best_pval = 1.0
            best_fstat = 0.0

            for lag in range(1, max_lag + 1):
                if len(y) <= lag + 5:
                    continue

                # Restricted model: effect_t ~ effect_{t-1}, ..., effect_{t-lag}
                # Unrestricted: effect_t ~ effect_{t-1}, ..., effect_{t-lag}, cause_{t-1}, ..., cause_{t-lag}

                T = len(y) - lag
                Y = y[lag:]

                # Build lagged matrices
                X_restricted = np.ones((T, lag + 1))  # intercept + lagged effect
                X_unrestricted = np.ones((T, 2 * lag + 1))  # intercept + lagged effect + lagged cause

                for l in range(1, lag + 1):
                    X_restricted[:, l] = y[lag - l : -l] if l < len(y) else y[lag - l :]
                    X_unrestricted[:, l] = y[lag - l : -l] if l < len(y) else y[lag - l :]
                    X_unrestricted[:, lag + l] = x_cause[lag - l : -l] if l < len(y) else x_cause[lag - l :]

                # OLS for restricted
                try:
                    beta_r = np.linalg.lstsq(X_restricted, Y, rcond=None)[0]
                    resid_r = Y - X_restricted @ beta_r
                    ssr_r = np.sum(resid_r ** 2)

                    beta_u = np.linalg.lstsq(X_unrestricted, Y, rcond=None)[0]
                    resid_u = Y - X_unrestricted @ beta_u
                    ssr_u = np.sum(resid_u ** 2)

                    # F-test
                    df1 = lag  # additional parameters
                    df2 = T - 2 * lag - 1
                    if df2 <= 0 or ssr_u <= 0:
                        continue

                    f_stat = ((ssr_r - ssr_u) / df1) / (ssr_u / df2)
                    p_val = 1 - stats.f.cdf(f_stat, df1, df2)

                    if p_val < best_pval:
                        best_pval = p_val
                        best_fstat = f_stat
                except Exception:
                    continue

            pval_matrix.loc[cause, effect] = best_pval
            fstat_matrix.loc[cause, effect] = best_fstat

    # Identify leaders: sectors that Granger-cause the most others
    sig_threshold = 0.05
    leader_counts = {}
    for sector in sectors:
        n_caused = (pval_matrix.loc[sector, :] < sig_threshold).sum()
        n_caused_by = (pval_matrix.loc[:, sector] < sig_threshold).sum()
        leader_counts[sector] = {
            "granger_causes_n": int(n_caused),
            "granger_caused_by_n": int(n_caused_by),
            "net_leadership": int(n_caused - n_caused_by),
        }

    # Find significant pairs
    sig_pairs = []
    for cause in sectors:
        for effect in sectors:
            if cause != effect and pval_matrix.loc[cause, effect] < sig_threshold:
                sig_pairs.append({
                    "cause": cause,
                    "effect": effect,
                    "cause_name": SECTORS.get(cause, cause),
                    "effect_name": SECTORS.get(effect, effect),
                    "p_value": round(float(pval_matrix.loc[cause, effect]), 4),
                    "f_stat": round(float(fstat_matrix.loc[cause, effect]), 2),
                })

    return {
        "leader_scores": leader_counts,
        "significant_pairs": sorted(sig_pairs, key=lambda x: x["p_value"]),
        "n_significant": len(sig_pairs),
        "n_total_pairs": n * (n - 1),
    }


# ─────────────────────────────────────────────
# 4. Economic Cycle Rotation
# ─────────────────────────────────────────────
def economic_cycle_analysis(returns):
    """
    Analyze sector behavior in different market environments.
    Use SPY (if available) or equal-weight sector portfolio as market proxy.
    Classify months into: bull (>0, >median), strong bull (>75th pctile),
    bear (<0), crash (<25th pctile).
    """
    # Equal-weight market return
    mkt = returns.mean(axis=1)

    # Define regimes
    median_ret = mkt.median()
    q25 = mkt.quantile(0.25)
    q75 = mkt.quantile(0.75)

    regimes = pd.Series("normal", index=mkt.index)
    regimes[mkt > q75] = "strong_bull"
    regimes[(mkt > 0) & (mkt <= q75)] = "mild_bull"
    regimes[(mkt <= 0) & (mkt > q25)] = "mild_bear"
    regimes[mkt <= q25] = "crash"

    # Average sector return by regime
    results = {}
    for regime in ["strong_bull", "mild_bull", "mild_bear", "crash"]:
        mask = regimes == regime
        n_months = mask.sum()
        regime_returns = returns[mask].mean() * 100  # in percent
        regime_vol = returns[mask].std() * np.sqrt(12) * 100

        # Rank sectors by return in this regime
        ranked = regime_returns.sort_values(ascending=False)

        results[regime] = {
            "n_months": int(n_months),
            "rankings": {
                SECTORS.get(s, s): {
                    "mean_return_pct": round(float(regime_returns[s]), 2),
                    "ann_vol_pct": round(float(regime_vol[s]), 1) if not np.isnan(regime_vol[s]) else None,
                    "rank": int(rank + 1),
                }
                for rank, s in enumerate(ranked.index)
                if not np.isnan(regime_returns[s])
            },
        }

    # Defensive vs Cyclical classification
    defensive = ["XLP", "XLU", "XLV"]  # staples, utilities, healthcare
    cyclical = ["XLK", "XLY", "XLF", "XLE", "XLI"]  # tech, disc, fin, energy, industrials

    def_cyc_spread = {}
    for regime in ["strong_bull", "mild_bull", "mild_bear", "crash"]:
        mask = regimes == regime
        regime_ret = returns[mask]

        def_cols = [c for c in defensive if c in regime_ret.columns]
        cyc_cols = [c for c in cyclical if c in regime_ret.columns]

        if def_cols and cyc_cols:
            def_ret = regime_ret[def_cols].mean(axis=1).mean() * 100
            cyc_ret = regime_ret[cyc_cols].mean(axis=1).mean() * 100
            def_cyc_spread[regime] = {
                "defensive_mean_pct": round(float(def_ret), 2),
                "cyclical_mean_pct": round(float(cyc_ret), 2),
                "spread_cyc_minus_def": round(float(cyc_ret - def_ret), 2),
            }

    return {
        "regime_analysis": results,
        "defensive_vs_cyclical": def_cyc_spread,
    }


# ─────────────────────────────────────────────
# 5. Post-2020 Degradation Analysis
# ─────────────────────────────────────────────
def degradation_analysis(returns):
    """
    Compare sector momentum performance pre-2020 vs post-2020.
    Has the retail/meme stock era changed sector dynamics?
    """
    cutoff = "2020-01-01"
    pre = returns[returns.index < cutoff]
    post = returns[returns.index >= cutoff]

    pre_ls = sector_momentum_strategy(pre)
    post_ls = sector_momentum_strategy(post)

    pre_metrics = evaluate_strategy(pre_ls, "Pre-2020 Momentum")
    post_metrics = evaluate_strategy(post_ls, "Post-2020 Momentum")

    # Rank autocorrelation comparison
    pre_persist = leadership_persistence(pre)
    post_persist = leadership_persistence(post)

    # Cross-sector correlation comparison (has correlation increased = harder to differentiate?)
    pre_corr = pre.corr().values
    post_corr = post.corr().values

    # Get upper triangle (excluding diagonal)
    pre_upper = pre_corr[np.triu_indices_from(pre_corr, k=1)]
    post_upper = post_corr[np.triu_indices_from(post_corr, k=1)]

    # Remove NaN
    pre_upper = pre_upper[~np.isnan(pre_upper)]
    post_upper = post_upper[~np.isnan(post_upper)]

    return {
        "pre_2020": pre_metrics,
        "post_2020": post_metrics,
        "pre_rank_autocorr": pre_persist["mean_rank_autocorrelation"],
        "post_rank_autocorr": post_persist["mean_rank_autocorrelation"],
        "pre_mean_cross_corr": round(float(np.mean(pre_upper)), 4),
        "post_mean_cross_corr": round(float(np.mean(post_upper)), 4),
        "correlation_increased": bool(np.mean(post_upper) > np.mean(pre_upper)),
    }


# ─────────────────────────────────────────────
# 6. Robustness: Different Momentum Windows
# ─────────────────────────────────────────────
def momentum_window_sweep(returns):
    """Test momentum with different lookback windows: 1, 3, 6, 9, 12 months."""
    results = {}
    for window in [1, 3, 6, 9, 12]:
        ls = sector_momentum_strategy(returns, momentum_window=window)
        if len(ls) > 12:
            metrics = evaluate_strategy(ls, f"{window}M Momentum")
            results[f"{window}M"] = metrics
    return results


# ─────────────────────────────────────────────
# 7. Sector Return Correlation Matrix
# ─────────────────────────────────────────────
def sector_correlation_analysis(returns):
    """Full-sample correlation matrix and clustering insights."""
    corr = returns.corr()

    # Rename for readability
    name_map = {k: f"{k} ({v})" for k, v in SECTORS.items() if k in corr.columns}
    corr_named = corr.rename(index=name_map, columns=name_map)

    # Most correlated and least correlated pairs
    pairs = []
    cols = corr.columns
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            pairs.append({
                "pair": f"{cols[i]}-{cols[j]}",
                "pair_names": f"{SECTORS.get(cols[i], cols[i])} & {SECTORS.get(cols[j], cols[j])}",
                "correlation": round(float(corr.iloc[i, j]), 4),
            })

    pairs.sort(key=lambda x: x["correlation"])

    return {
        "most_correlated": pairs[-5:],
        "least_correlated": pairs[:5],
        "mean_correlation": round(float(corr.values[np.triu_indices_from(corr.values, k=1)].mean()), 4),
    }


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────
def main():
    print("=" * 70)
    print("K411: Pure Sector Momentum — Which Sectors Lead and Follow?")
    print("=" * 70)
    print(f"Data: {', '.join(SECTORS.keys())}")
    print(f"Period: {START} to {END}")
    print(f"Momentum window: {MOMENTUM_WINDOW} months")
    print(f"Long top {TOP_N}, Short bottom {BOT_N}")
    print(f"TX cost: {TX_COST_BPS} bps one-way")
    print()

    # Download data
    prices = download_data()
    returns = compute_monthly_returns(prices)
    print(f"\nMonthly returns shape: {returns.shape}")
    print(f"Period: {returns.index[0].strftime('%Y-%m')} to {returns.index[-1].strftime('%Y-%m')}")
    print()

    results = {
        "experiment": "K411",
        "title": "Pure Sector Momentum — Which Sectors Lead and Follow?",
        "data_source": "yfinance",
        "period": f"{returns.index[0].strftime('%Y-%m')} to {returns.index[-1].strftime('%Y-%m')}",
        "n_months": len(returns),
        "sectors": SECTORS,
        "methodology": {
            "momentum_window": MOMENTUM_WINDOW,
            "long_n": TOP_N,
            "short_n": BOT_N,
            "tx_cost_bps": TX_COST_BPS,
            "rebalance": "monthly",
        },
    }

    # ── 1. Sector Momentum Strategy ──
    print("─" * 50)
    print("1. SECTOR MOMENTUM STRATEGY (L/S)")
    print("─" * 50)
    ls_returns = sector_momentum_strategy(returns)
    ls_metrics = evaluate_strategy(ls_returns, "3M Sector Momentum L/S")

    print(f"  Period: {ls_returns.index[0].strftime('%Y-%m')} to {ls_returns.index[-1].strftime('%Y-%m')}")
    print(f"  N months: {ls_metrics['n_months']}")
    print(f"  Ann Return: {ls_metrics['ann_return']:.2f}%")
    print(f"  Ann Vol: {ls_metrics['ann_vol']:.2f}%")
    print(f"  Sharpe: {ls_metrics['sharpe']:.3f}")
    print(f"  Net Sharpe (after {TX_COST_BPS}bps TX): {ls_metrics['net_sharpe']:.3f}")
    print(f"  Max Drawdown: {ls_metrics['max_drawdown']:.2f}%")
    print(f"  Monthly Win Rate: {ls_metrics['monthly_win_rate']:.1f}%")
    print(f"  Annual Win Rate: {ls_metrics['annual_win_rate']:.1f}%")
    print(f"  t-stat: {ls_metrics['t_stat']:.3f}")
    print(f"  Skewness: {ls_metrics['skewness']:.3f}")
    print(f"  Kurtosis: {ls_metrics['kurtosis']:.3f}")
    print()

    results["momentum_strategy"] = ls_metrics

    # Also compute long-only momentum (top 3 equal weight)
    print("  Long-only momentum (top 3 sectors):")
    lo_returns_list = []
    lo_dates = []
    cum_ret = (1 + returns).rolling(window=MOMENTUM_WINDOW).apply(lambda x: x.prod() - 1, raw=True)
    for i in range(MOMENTUM_WINDOW, len(returns)):
        date = returns.index[i]
        rank_date = returns.index[i - 1]
        scores = cum_ret.loc[rank_date].dropna()
        if len(scores) < TOP_N:
            continue
        ranked = scores.sort_values(ascending=False)
        longs = ranked.index[:TOP_N]
        long_ret = returns.loc[date, longs].mean()
        lo_returns_list.append(long_ret)
        lo_dates.append(date)

    lo_returns = pd.Series(lo_returns_list, index=lo_dates, name="LO_Momentum")
    lo_metrics = evaluate_strategy(lo_returns, "3M Long-Only Top 3")
    print(f"  Ann Return: {lo_metrics['ann_return']:.2f}%")
    print(f"  Sharpe: {lo_metrics['sharpe']:.3f}")
    print(f"  Max Drawdown: {lo_metrics['max_drawdown']:.2f}%")
    print()

    results["long_only_momentum"] = lo_metrics

    # Equal-weight benchmark
    ew_returns = returns.mean(axis=1).dropna()
    ew_metrics = evaluate_strategy(ew_returns, "Equal-Weight All Sectors")
    print(f"  Equal-Weight Benchmark:")
    print(f"  Ann Return: {ew_metrics['ann_return']:.2f}%")
    print(f"  Sharpe: {ew_metrics['sharpe']:.3f}")
    print(f"  Max Drawdown: {ew_metrics['max_drawdown']:.2f}%")
    print()

    results["equal_weight_benchmark"] = ew_metrics

    # ── 2. Leadership Persistence ──
    print("─" * 50)
    print("2. SECTOR LEADERSHIP PERSISTENCE")
    print("─" * 50)
    persist = leadership_persistence(returns)

    print(f"  Mean rank autocorrelation (Spearman): {persist['mean_rank_autocorrelation']:.4f}")
    print(f"  Fraction significant at 5%: {persist['frac_significant_at_5pct']:.3f}")
    print()

    print("  Leadership duration (consecutive months in top 3):")
    print(f"  {'Sector':<25} {'Median':>8} {'Mean':>8} {'Max':>6} {'% Time':>8}")
    print(f"  {'-'*55}")

    # Sort by pct_time_in_top3
    sorted_leaders = sorted(
        persist["leadership_durations"].items(),
        key=lambda x: x[1]["pct_time_in_top3"],
        reverse=True,
    )
    for sector, info in sorted_leaders:
        name = SECTORS.get(sector, sector)
        print(f"  {name:<25} {info['median_months']:>8.0f} {info['mean_months']:>8.1f} {info['max_months']:>6d} {info['pct_time_in_top3']:>7.1f}%")
    print()

    results["leadership_persistence"] = persist

    # ── 3. Granger Causality (Lead-Lag) ──
    print("─" * 50)
    print("3. SECTOR LEAD-LAG (GRANGER CAUSALITY)")
    print("─" * 50)
    granger = granger_causality_matrix(returns, max_lag=2)

    print(f"  Significant pairs (p<0.05): {granger['n_significant']} / {granger['n_total_pairs']}")
    print()

    print("  Net Leadership Score (Granger-causes minus caused-by):")
    sorted_leaders_gc = sorted(
        granger["leader_scores"].items(),
        key=lambda x: x[1]["net_leadership"],
        reverse=True,
    )
    for sector, info in sorted_leaders_gc:
        name = SECTORS.get(sector, sector)
        direction = "LEADER" if info["net_leadership"] > 0 else ("FOLLOWER" if info["net_leadership"] < 0 else "NEUTRAL")
        print(f"  {name:<25} causes {info['granger_causes_n']:>2}, caused by {info['granger_caused_by_n']:>2}, net={info['net_leadership']:>+3d} [{direction}]")
    print()

    if granger["significant_pairs"]:
        print("  Top significant causal pairs:")
        for pair in granger["significant_pairs"][:10]:
            print(f"    {pair['cause_name']:<20} → {pair['effect_name']:<20} (p={pair['p_value']:.4f}, F={pair['f_stat']:.2f})")
    print()

    results["granger_causality"] = granger

    # ── 4. Economic Cycle Rotation ──
    print("─" * 50)
    print("4. SECTOR ROTATION BY MARKET REGIME")
    print("─" * 50)
    cycle = economic_cycle_analysis(returns)

    for regime in ["strong_bull", "mild_bull", "mild_bear", "crash"]:
        info = cycle["regime_analysis"][regime]
        print(f"\n  {regime.upper()} ({info['n_months']} months):")
        print(f"  {'Sector':<25} {'Avg Monthly Ret':>15} {'Rank':>6}")
        for name, data in sorted(info["rankings"].items(), key=lambda x: x[1]["rank"]):
            print(f"  {name:<25} {data['mean_return_pct']:>14.2f}% {data['rank']:>6d}")

    print(f"\n  Defensive vs Cyclical spread:")
    print(f"  {'Regime':<15} {'Defensive':>12} {'Cyclical':>12} {'Spread (C-D)':>14}")
    for regime in ["strong_bull", "mild_bull", "mild_bear", "crash"]:
        if regime in cycle["defensive_vs_cyclical"]:
            d = cycle["defensive_vs_cyclical"][regime]
            print(f"  {regime:<15} {d['defensive_mean_pct']:>11.2f}% {d['cyclical_mean_pct']:>11.2f}% {d['spread_cyc_minus_def']:>13.2f}%")
    print()

    results["economic_cycle"] = cycle

    # ── 5. Post-2020 Degradation ──
    print("─" * 50)
    print("5. POST-2020 DEGRADATION ANALYSIS")
    print("─" * 50)
    degrad = degradation_analysis(returns)

    print(f"  {'Metric':<25} {'Pre-2020':>12} {'Post-2020':>12}")
    print(f"  {'-'*49}")
    for key in ["ann_return", "sharpe", "net_sharpe", "max_drawdown", "monthly_win_rate"]:
        pre_val = degrad["pre_2020"][key]
        post_val = degrad["post_2020"][key]
        suffix = "%" if "return" in key or "drawdown" in key or "rate" in key else ""
        print(f"  {key:<25} {pre_val:>11}{suffix} {post_val:>11}{suffix}")

    print(f"\n  Rank autocorrelation:")
    print(f"    Pre-2020:  {degrad['pre_rank_autocorr']:.4f}")
    print(f"    Post-2020: {degrad['post_rank_autocorr']:.4f}")
    print(f"\n  Cross-sector correlation:")
    print(f"    Pre-2020:  {degrad['pre_mean_cross_corr']:.4f}")
    print(f"    Post-2020: {degrad['post_mean_cross_corr']:.4f}")
    print(f"    Increased: {degrad['correlation_increased']}")
    print()

    results["degradation_analysis"] = degrad

    # ── 6. Momentum Window Sweep ──
    print("─" * 50)
    print("6. MOMENTUM WINDOW ROBUSTNESS")
    print("─" * 50)
    sweep = momentum_window_sweep(returns)

    print(f"  {'Window':<10} {'Ann Ret':>10} {'Sharpe':>8} {'Net Sharpe':>12} {'MDD':>8} {'t-stat':>8}")
    print(f"  {'-'*56}")
    for window, metrics in sweep.items():
        print(f"  {window:<10} {metrics['ann_return']:>9.2f}% {metrics['sharpe']:>8.3f} {metrics['net_sharpe']:>12.3f} {metrics['max_drawdown']:>7.2f}% {metrics['t_stat']:>8.3f}")
    print()

    results["momentum_window_sweep"] = sweep

    # ── 7. Correlation Analysis ──
    print("─" * 50)
    print("7. SECTOR CORRELATION STRUCTURE")
    print("─" * 50)
    corr_analysis = sector_correlation_analysis(returns)

    print(f"  Mean pairwise correlation: {corr_analysis['mean_correlation']:.4f}")
    print(f"\n  Most correlated pairs:")
    for pair in reversed(corr_analysis["most_correlated"]):
        print(f"    {pair['pair_names']:<45} r={pair['correlation']:.4f}")
    print(f"\n  Least correlated pairs:")
    for pair in corr_analysis["least_correlated"]:
        print(f"    {pair['pair_names']:<45} r={pair['correlation']:.4f}")
    print()

    results["correlation_structure"] = corr_analysis

    # ── Summary ──
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Key findings
    findings = []

    # 1. Does momentum work?
    if ls_metrics["t_stat"] > 2.0:
        findings.append(f"Sector momentum IS statistically significant (t={ls_metrics['t_stat']:.2f}, Sharpe={ls_metrics['sharpe']:.3f})")
    elif ls_metrics["t_stat"] > 1.5:
        findings.append(f"Sector momentum is MARGINALLY significant (t={ls_metrics['t_stat']:.2f}, Sharpe={ls_metrics['sharpe']:.3f})")
    else:
        findings.append(f"Sector momentum is NOT significant (t={ls_metrics['t_stat']:.2f}, Sharpe={ls_metrics['sharpe']:.3f})")

    # 2. Leadership persistence
    if persist["mean_rank_autocorrelation"] > 0.3:
        findings.append(f"Strong leadership persistence (rank autocorr={persist['mean_rank_autocorrelation']:.3f}) — winners tend to keep winning")
    elif persist["mean_rank_autocorrelation"] > 0.1:
        findings.append(f"Moderate leadership persistence (rank autocorr={persist['mean_rank_autocorrelation']:.3f})")
    else:
        findings.append(f"Weak leadership persistence (rank autocorr={persist['mean_rank_autocorrelation']:.3f}) — momentum is fragile")

    # 3. Canary sector
    if sorted_leaders_gc:
        top_leader = sorted_leaders_gc[0]
        if top_leader[1]["net_leadership"] > 0:
            findings.append(f"'{SECTORS.get(top_leader[0], top_leader[0])}' is the strongest sector leader (net Granger score={top_leader[1]['net_leadership']:+d})")

    # 4. Defensive rotation
    if "crash" in cycle["defensive_vs_cyclical"]:
        crash_spread = cycle["defensive_vs_cyclical"]["crash"]["spread_cyc_minus_def"]
        if crash_spread < 0:
            findings.append(f"Classic defensive rotation CONFIRMED: in crashes, cyclicals underperform defensives by {abs(crash_spread):.2f}%/mo")
        else:
            findings.append(f"Classic defensive rotation NOT confirmed in crashes (cyclicals spread: {crash_spread:+.2f}%)")

    # 5. Post-2020 degradation
    sharpe_diff = degrad["post_2020"]["sharpe"] - degrad["pre_2020"]["sharpe"]
    if sharpe_diff < -0.3:
        findings.append(f"Sector momentum HAS DEGRADED post-2020 (Sharpe drop: {sharpe_diff:.3f})")
    elif sharpe_diff > 0.3:
        findings.append(f"Sector momentum actually IMPROVED post-2020 (Sharpe change: {sharpe_diff:+.3f})")
    else:
        findings.append(f"Sector momentum relatively stable post-2020 (Sharpe change: {sharpe_diff:+.3f})")

    # 6. Best momentum window
    best_window = max(sweep.items(), key=lambda x: x[1]["sharpe"])
    findings.append(f"Best momentum window: {best_window[0]} (Sharpe={best_window[1]['sharpe']:.3f})")

    for i, f in enumerate(findings, 1):
        print(f"  {i}. {f}")
    print()

    results["key_findings"] = findings

    # Harvey threshold check
    harvey_pass = ls_metrics["t_stat"] > 3.0
    results["harvey_threshold"] = {
        "t_stat": ls_metrics["t_stat"],
        "passes_harvey_3.0": harvey_pass,
        "note": "Harvey (2016) requires t > 3.0 for new factor claims",
    }

    if harvey_pass:
        print("  ✓ PASSES Harvey (2016) t>3.0 threshold")
    else:
        print(f"  ✗ Does NOT pass Harvey (2016) t>3.0 threshold (t={ls_metrics['t_stat']:.3f})")
    print()

    # Save results
    output_path = Path(__file__).parent / "k411_sector_momentum_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Results saved to: {output_path}")

    return results


if __name__ == "__main__":
    main()
