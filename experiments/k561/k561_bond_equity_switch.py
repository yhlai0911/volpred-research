#!/usr/bin/env python3
"""
K561: Dynamic Bond-Equity Allocation in VT — Safe-Side Switching
================================================================
Motivation: Our VT framework uses equity portion = 12/VIX * 50% (in SPY),
and the remaining 50% in "safe" assets (currently GLD). But should the safe
allocation dynamically switch between GLD, TLT, and cash depending on the
interest rate environment?

Key context from prior experiments:
- T19: TLT structural break post-2022 (corr SPY-TLT went from -0.42 to +0.09)
- K425: Yield level drives bond-equity decorrelation (>4% yield → bonds not reliable)
- K507: Dynamic SPY-GLD alloc based on corr regime — fixed beat dynamic
- N176: Conditional TLT (rate < 60d MA → add TLT) showed Sharpe 1.078
- K33: MOVE beats VIX for bonds post-2022

Design:
- Equity portion: always 12/VIX * 50% in SPY, remainder in cash
- Safe portion (other 50%): 6 strategies tested
- Cross-OOS: 5 periods (Harvey t>3.0 threshold)

Data: SPY, GLD, TLT, VIX, ^TNX from yfinance (2005-2026)
References:
- Moreira & Muir (2017), "Volatility-Managed Portfolios", JoF
- Baele et al. (2010), "Flights to Safety", RFS
- Campbell et al. (2017), "Restoring Rational Choice", RFS (bond-equity correlation)

Author: VolPred Research System
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================
# 1. DATA COLLECTION
# ============================================================

def fetch_data():
    """Fetch SPY, GLD, TLT, VIX, ^TNX from yfinance."""
    tickers = {
        "SPY": "SPY",
        "GLD": "GLD",
        "TLT": "TLT",
        "VIX": "^VIX",
        "TNX": "^TNX",
    }

    data = {}
    for name, ticker in tickers.items():
        df = yf.download(ticker, start="2004-11-01", end="2026-03-28", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[name] = df["Close"].rename(name)

    # Combine into single DataFrame
    combined = pd.DataFrame(data)
    combined = combined.dropna()

    # GLD starts Nov 2004, TLT starts Jul 2002
    # Use intersection
    print(f"Data range: {combined.index[0].date()} to {combined.index[-1].date()}")
    print(f"Total observations: {len(combined)}")

    return combined


def compute_returns(prices):
    """Compute daily log returns."""
    returns = np.log(prices / prices.shift(1))
    return returns.dropna()


# ============================================================
# 2. STRATEGY DEFINITIONS
# ============================================================

def compute_equity_weight(vix_level):
    """Equity weight = 12/VIX, capped at [0, 1]."""
    w = 12.0 / vix_level
    return np.clip(w, 0.0, 1.0)


def strategy_static_gld(prices, returns):
    """Strategy A: Static GLD for safe portion (benchmark).
    Equity: 12/VIX * 50% in SPY. Safe: 50% in GLD always."""
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        vix = prices["VIX"].iloc[i]
        eq_w = compute_equity_weight(vix) * 0.50  # equity is 50% of portfolio
        safe_w = 0.50  # safe is other 50%
        cash_w = 0.50 - eq_w  # remainder of equity half goes to cash

        spy_ret = returns["SPY"].iloc[i]
        gld_ret = returns["GLD"].iloc[i]

        port_ret[i] = eq_w * spy_ret + safe_w * gld_ret + cash_w * 0.0

    return pd.Series(port_ret, index=returns.index)


def strategy_static_tlt(prices, returns):
    """Strategy B: Static TLT for safe portion.
    Equity: 12/VIX * 50% in SPY. Safe: 50% in TLT always."""
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        vix = prices["VIX"].iloc[i]
        eq_w = compute_equity_weight(vix) * 0.50
        safe_w = 0.50
        cash_w = 0.50 - eq_w

        spy_ret = returns["SPY"].iloc[i]
        tlt_ret = returns["TLT"].iloc[i]

        port_ret[i] = eq_w * spy_ret + safe_w * tlt_ret + cash_w * 0.0

    return pd.Series(port_ret, index=returns.index)


def strategy_rate_conditional(prices, returns, lookback=63):
    """Strategy C: Rate-conditional switching.
    GLD when TNX 3m change > 0 (rising rates), TLT when TNX falling."""
    n = len(returns)
    port_ret = np.zeros(n)
    choices = []

    for i in range(n):
        vix = prices["VIX"].iloc[i]
        eq_w = compute_equity_weight(vix) * 0.50
        safe_w = 0.50
        cash_w = 0.50 - eq_w

        spy_ret = returns["SPY"].iloc[i]
        gld_ret = returns["GLD"].iloc[i]
        tlt_ret = returns["TLT"].iloc[i]

        # Rate regime: is TNX rising or falling over lookback?
        if i >= lookback:
            tnx_now = prices["TNX"].iloc[i]
            tnx_prev = prices["TNX"].iloc[i - lookback]
            rate_rising = tnx_now > tnx_prev
        else:
            rate_rising = False  # default to TLT

        if rate_rising:
            safe_ret = gld_ret
            choices.append("GLD")
        else:
            safe_ret = tlt_ret
            choices.append("TLT")

        port_ret[i] = eq_w * spy_ret + safe_w * safe_ret + cash_w * 0.0

    return pd.Series(port_ret, index=returns.index), choices


def strategy_momentum(prices, returns, mom_lookback=60):
    """Strategy D: Momentum-based switching.
    Use whichever of GLD/TLT has better trailing 60d return."""
    n = len(returns)
    port_ret = np.zeros(n)
    choices = []

    for i in range(n):
        vix = prices["VIX"].iloc[i]
        eq_w = compute_equity_weight(vix) * 0.50
        safe_w = 0.50
        cash_w = 0.50 - eq_w

        spy_ret = returns["SPY"].iloc[i]
        gld_ret = returns["GLD"].iloc[i]
        tlt_ret = returns["TLT"].iloc[i]

        if i >= mom_lookback:
            gld_mom = prices["GLD"].iloc[i] / prices["GLD"].iloc[i - mom_lookback] - 1
            tlt_mom = prices["TLT"].iloc[i] / prices["TLT"].iloc[i - mom_lookback] - 1
            use_gld = gld_mom > tlt_mom
        else:
            use_gld = True  # default GLD

        if use_gld:
            safe_ret = gld_ret
            choices.append("GLD")
        else:
            safe_ret = tlt_ret
            choices.append("TLT")

        port_ret[i] = eq_w * spy_ret + safe_w * safe_ret + cash_w * 0.0

    return pd.Series(port_ret, index=returns.index), choices


def strategy_equal_split(prices, returns):
    """Strategy E: Equal split — 25% GLD + 25% TLT always."""
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        vix = prices["VIX"].iloc[i]
        eq_w = compute_equity_weight(vix) * 0.50
        cash_w = 0.50 - eq_w

        spy_ret = returns["SPY"].iloc[i]
        gld_ret = returns["GLD"].iloc[i]
        tlt_ret = returns["TLT"].iloc[i]

        port_ret[i] = eq_w * spy_ret + 0.25 * gld_ret + 0.25 * tlt_ret + cash_w * 0.0

    return pd.Series(port_ret, index=returns.index)


def strategy_vol_adjusted(prices, returns, vol_lookback=63):
    """Strategy F: Volatility-adjusted allocation.
    Allocate safe 50% inversely to each asset's trailing vol."""
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        vix = prices["VIX"].iloc[i]
        eq_w = compute_equity_weight(vix) * 0.50
        cash_w = 0.50 - eq_w

        spy_ret = returns["SPY"].iloc[i]
        gld_ret = returns["GLD"].iloc[i]
        tlt_ret = returns["TLT"].iloc[i]

        if i >= vol_lookback:
            gld_vol = returns["GLD"].iloc[i - vol_lookback:i].std()
            tlt_vol = returns["TLT"].iloc[i - vol_lookback:i].std()

            if gld_vol > 0 and tlt_vol > 0:
                inv_gld = 1.0 / gld_vol
                inv_tlt = 1.0 / tlt_vol
                total_inv = inv_gld + inv_tlt
                w_gld = 0.50 * (inv_gld / total_inv)
                w_tlt = 0.50 * (inv_tlt / total_inv)
            else:
                w_gld = 0.25
                w_tlt = 0.25
        else:
            w_gld = 0.25
            w_tlt = 0.25

        port_ret[i] = eq_w * spy_ret + w_gld * gld_ret + w_tlt * tlt_ret + cash_w * 0.0

    return pd.Series(port_ret, index=returns.index)


def strategy_static_cash(prices, returns):
    """Strategy G: Cash for safe portion (pure VT benchmark).
    Equity: 12/VIX * 50% in SPY. Safe: 50% in cash (0% return)."""
    n = len(returns)
    port_ret = np.zeros(n)

    for i in range(n):
        vix = prices["VIX"].iloc[i]
        eq_w = compute_equity_weight(vix) * 0.50
        cash_w = 1.0 - eq_w  # everything else is cash

        spy_ret = returns["SPY"].iloc[i]
        port_ret[i] = eq_w * spy_ret + cash_w * 0.0

    return pd.Series(port_ret, index=returns.index)


# ============================================================
# 3. PERFORMANCE METRICS
# ============================================================

def compute_metrics(returns_series, ann_factor=252):
    """Compute key portfolio metrics."""
    r = returns_series.values
    n = len(r)

    ann_ret = np.mean(r) * ann_factor
    ann_vol = np.std(r, ddof=1) * np.sqrt(ann_factor)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    cum = np.cumsum(r)
    running_max = np.maximum.accumulate(cum)
    dd = cum - running_max
    mdd = np.min(dd)

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = r[r < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(ann_factor) if len(downside) > 0 else 1
    sortino = ann_ret / downside_vol

    # Skewness and kurtosis
    skew = float(stats.skew(r))
    kurt = float(stats.kurtosis(r))

    return {
        "ann_return": round(float(ann_ret) * 100, 2),
        "ann_vol": round(float(ann_vol) * 100, 2),
        "sharpe": round(float(sharpe), 4),
        "max_drawdown": round(float(mdd) * 100, 2),
        "calmar": round(float(calmar), 4),
        "sortino": round(float(sortino), 4),
        "skewness": round(skew, 4),
        "kurtosis": round(kurt, 4),
        "n_days": n,
    }


# ============================================================
# 4. CROSS-OOS TESTING
# ============================================================

def diebold_mariano_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive accuracy.
    Uses squared error loss: d_t = e1_t^2 - e2_t^2.
    Positive DM stat means strategy 2 is better (lower loss)."""
    d = e1**2 - e2**2
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return 0, 1.0

    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return float(dm_stat), float(p_value)


def run_cross_oos(prices, returns, n_periods=5, oos_fraction=0.3):
    """Run cross-OOS validation with expanding window."""
    n = len(returns)
    total_oos = int(n * oos_fraction)
    oos_size = total_oos // n_periods

    # Define OOS periods (non-overlapping, from the back)
    oos_periods = []
    for k in range(n_periods):
        end_idx = n - k * oos_size
        start_idx = end_idx - oos_size
        if start_idx < 252:  # need at least 1 year of IS
            break
        oos_periods.append((start_idx, end_idx))

    oos_periods.reverse()  # chronological order

    print(f"\nCross-OOS: {len(oos_periods)} periods, each ~{oos_size} days")

    strategy_names = [
        "A_Static_GLD", "B_Static_TLT", "C_Rate_Conditional",
        "D_Momentum", "E_Equal_Split", "F_Vol_Adjusted", "G_Static_Cash"
    ]

    all_oos_results = {name: [] for name in strategy_names}
    period_details = []

    for period_idx, (start, end) in enumerate(oos_periods):
        oos_prices = prices.iloc[start:end]
        oos_returns = returns.iloc[start:end]

        date_start = oos_returns.index[0].strftime("%Y-%m-%d")
        date_end = oos_returns.index[-1].strftime("%Y-%m-%d")

        print(f"\n  Period {period_idx+1}: {date_start} to {date_end} ({len(oos_returns)} days)")

        # Need full prices for lookback calculations
        # Use prices/returns from beginning up to end of OOS
        full_prices = prices.iloc[:end]
        full_returns = returns.iloc[:end]

        # Run all strategies on full data, then extract OOS portion
        ret_a = strategy_static_gld(full_prices, full_returns).iloc[start:end]
        ret_b = strategy_static_tlt(full_prices, full_returns).iloc[start:end]
        ret_c, _ = strategy_rate_conditional(full_prices, full_returns)
        ret_c = ret_c.iloc[start:end]
        ret_d, _ = strategy_momentum(full_prices, full_returns)
        ret_d = ret_d.iloc[start:end]
        ret_e = strategy_equal_split(full_prices, full_returns).iloc[start:end]
        ret_f = strategy_vol_adjusted(full_prices, full_returns).iloc[start:end]
        ret_g = strategy_static_cash(full_prices, full_returns).iloc[start:end]

        strat_returns = {
            "A_Static_GLD": ret_a,
            "B_Static_TLT": ret_b,
            "C_Rate_Conditional": ret_c,
            "D_Momentum": ret_d,
            "E_Equal_Split": ret_e,
            "F_Vol_Adjusted": ret_f,
            "G_Static_Cash": ret_g,
        }

        period_info = {
            "period": period_idx + 1,
            "start": date_start,
            "end": date_end,
            "n_days": len(oos_returns),
            "strategies": {},
        }

        for name, ret in strat_returns.items():
            metrics = compute_metrics(ret)
            all_oos_results[name].append(metrics["sharpe"])
            period_info["strategies"][name] = metrics
            print(f"    {name}: Sharpe={metrics['sharpe']:.4f}, Ret={metrics['ann_return']:.2f}%, MDD={metrics['max_drawdown']:.2f}%")

        period_details.append(period_info)

    return all_oos_results, period_details


# ============================================================
# 5. STATISTICAL TESTS
# ============================================================

def paired_t_test(sharpes_a, sharpes_b):
    """Paired t-test across OOS periods."""
    diffs = np.array(sharpes_a) - np.array(sharpes_b)
    n = len(diffs)
    if n < 2:
        return 0, 1.0
    t_stat = np.mean(diffs) / (np.std(diffs, ddof=1) / np.sqrt(n))
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value)


def bootstrap_sharpe_diff(ret1, ret2, n_boot=10000, seed=42):
    """Bootstrap test for Sharpe difference."""
    rng = np.random.RandomState(seed)
    n = len(ret1)

    s1 = np.mean(ret1) / np.std(ret1, ddof=1) * np.sqrt(252)
    s2 = np.mean(ret2) / np.std(ret2, ddof=1) * np.sqrt(252)
    obs_diff = s1 - s2

    boot_diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = rng.randint(0, n, size=n)
        b1 = ret1.values[idx]
        b2 = ret2.values[idx]
        bs1 = np.mean(b1) / np.std(b1, ddof=1) * np.sqrt(252) if np.std(b1) > 0 else 0
        bs2 = np.mean(b2) / np.std(b2, ddof=1) * np.sqrt(252) if np.std(b2) > 0 else 0
        boot_diffs[b] = bs1 - bs2

    p_value = np.mean(np.abs(boot_diffs - np.mean(boot_diffs)) >= abs(obs_diff))
    ci_lo = np.percentile(boot_diffs, 2.5)
    ci_hi = np.percentile(boot_diffs, 97.5)

    return {
        "obs_diff": round(float(obs_diff), 4),
        "p_value": round(float(p_value), 4),
        "ci_95": [round(float(ci_lo), 4), round(float(ci_hi), 4)],
    }


# ============================================================
# 6. REGIME ANALYSIS
# ============================================================

def regime_analysis(prices, returns):
    """Analyze performance across interest rate regimes."""
    # Define regimes based on TNX level
    tnx = prices["TNX"]

    # Rate regimes
    low_rate = tnx < 2.0
    mid_rate = (tnx >= 2.0) & (tnx < 3.5)
    high_rate = tnx >= 3.5

    # Rate direction (3-month change)
    tnx_3m_change = tnx - tnx.shift(63)
    rising = tnx_3m_change > 0
    falling = tnx_3m_change <= 0

    regimes = {
        "low_rate_<2%": low_rate.reindex(returns.index).fillna(False),
        "mid_rate_2-3.5%": mid_rate.reindex(returns.index).fillna(False),
        "high_rate_>3.5%": high_rate.reindex(returns.index).fillna(False),
        "rates_rising": rising.reindex(returns.index).fillna(False),
        "rates_falling": falling.reindex(returns.index).fillna(False),
    }

    # Compute full-sample strategy returns
    ret_a = strategy_static_gld(prices, returns)
    ret_b = strategy_static_tlt(prices, returns)
    ret_c, _ = strategy_rate_conditional(prices, returns)
    ret_d, _ = strategy_momentum(prices, returns)
    ret_e = strategy_equal_split(prices, returns)
    ret_f = strategy_vol_adjusted(prices, returns)
    ret_g = strategy_static_cash(prices, returns)

    strat_returns = {
        "A_Static_GLD": ret_a,
        "B_Static_TLT": ret_b,
        "C_Rate_Conditional": ret_c,
        "D_Momentum": ret_d,
        "E_Equal_Split": ret_e,
        "F_Vol_Adjusted": ret_f,
        "G_Static_Cash": ret_g,
    }

    regime_results = {}
    for regime_name, mask in regimes.items():
        regime_results[regime_name] = {}
        n_days = mask.sum()
        regime_results[regime_name]["n_days"] = int(n_days)

        for strat_name, ret in strat_returns.items():
            if n_days > 30:
                regime_ret = ret[mask]
                ann_ret = float(np.mean(regime_ret)) * 252 * 100
                ann_vol = float(np.std(regime_ret, ddof=1)) * np.sqrt(252) * 100
                sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
                regime_results[regime_name][strat_name] = {
                    "sharpe": round(sharpe, 4),
                    "ann_return": round(ann_ret, 2),
                    "n_days": int(n_days),
                }

    return regime_results


# ============================================================
# 7. SUBPERIOD ANALYSIS (key periods)
# ============================================================

def subperiod_analysis(prices, returns):
    """Analyze critical subperiods."""
    subperiods = {
        "2010-2019_pre_covid": ("2010-01-01", "2019-12-31"),
        "2020_covid": ("2020-01-01", "2020-12-31"),
        "2021_low_rates": ("2021-01-01", "2021-12-31"),
        "2022_rate_hike": ("2022-01-01", "2022-12-31"),
        "2023_elevated_rates": ("2023-01-01", "2023-12-31"),
        "2024_2026_current": ("2024-01-01", "2026-03-27"),
    }

    results = {}
    for period_name, (start, end) in subperiods.items():
        mask = (returns.index >= start) & (returns.index <= end)
        sub_returns = returns[mask]
        sub_prices = prices.reindex(sub_returns.index, method="ffill")
        # For strategies that need lookback, use full prices up to period end
        full_mask = prices.index <= end
        full_prices = prices[full_mask]
        full_returns = returns.reindex(full_prices.index[1:], method=None)
        full_returns = returns[returns.index <= end]

        if len(sub_returns) < 30:
            continue

        # Run strategies on full data, extract subperiod
        ret_a = strategy_static_gld(full_prices, full_returns)
        ret_b = strategy_static_tlt(full_prices, full_returns)
        ret_c, _ = strategy_rate_conditional(full_prices, full_returns)
        ret_d, _ = strategy_momentum(full_prices, full_returns)
        ret_e = strategy_equal_split(full_prices, full_returns)
        ret_f = strategy_vol_adjusted(full_prices, full_returns)
        ret_g = strategy_static_cash(full_prices, full_returns)

        # Extract subperiod indices from the full-length strategy returns
        sub_idx = sub_returns.index
        strat_returns = {
            "A_Static_GLD": ret_a.reindex(sub_idx).dropna(),
            "B_Static_TLT": ret_b.reindex(sub_idx).dropna(),
            "C_Rate_Conditional": ret_c.reindex(sub_idx).dropna(),
            "D_Momentum": ret_d.reindex(sub_idx).dropna(),
            "E_Equal_Split": ret_e.reindex(sub_idx).dropna(),
            "F_Vol_Adjusted": ret_f.reindex(sub_idx).dropna(),
            "G_Static_Cash": ret_g.reindex(sub_idx).dropna(),
        }

        period_results = {"n_days": int(mask.sum()), "strategies": {}}
        for name, ret in strat_returns.items():
            if len(ret) > 10:
                metrics = compute_metrics(ret)
                period_results["strategies"][name] = metrics

        results[period_name] = period_results

    return results


# ============================================================
# 8. MAIN
# ============================================================

def main():
    print("=" * 70)
    print("K561: Dynamic Bond-Equity Allocation in VT — Safe-Side Switching")
    print("=" * 70)

    # 1. Fetch data
    print("\n[1/7] Fetching data...")
    prices = fetch_data()
    returns = compute_returns(prices)

    # 2. Descriptive statistics
    print("\n[2/7] Descriptive statistics...")
    for col in ["SPY", "GLD", "TLT"]:
        r = returns[col]
        print(f"  {col}: mean={r.mean()*252*100:.2f}%/yr, vol={r.std()*np.sqrt(252)*100:.2f}%/yr, "
              f"skew={stats.skew(r):.3f}, kurt={stats.kurtosis(r):.3f}, n={len(r)}")

    print(f"\n  TNX range: {prices['TNX'].min():.2f}% to {prices['TNX'].max():.2f}%")
    print(f"  TNX current: {prices['TNX'].iloc[-1]:.2f}%")
    print(f"  VIX range: {prices['VIX'].min():.2f} to {prices['VIX'].max():.2f}")

    # Correlations
    corr_matrix = returns[["SPY", "GLD", "TLT"]].corr()
    print(f"\n  Correlations (full sample):")
    print(f"    SPY-GLD: {corr_matrix.loc['SPY','GLD']:.4f}")
    print(f"    SPY-TLT: {corr_matrix.loc['SPY','TLT']:.4f}")
    print(f"    GLD-TLT: {corr_matrix.loc['GLD','TLT']:.4f}")

    # Pre vs post 2022
    pre2022 = returns.index < "2022-01-01"
    post2022 = returns.index >= "2022-01-01"
    corr_pre = returns.loc[pre2022, ["SPY", "GLD", "TLT"]].corr()
    corr_post = returns.loc[post2022, ["SPY", "GLD", "TLT"]].corr()
    print(f"\n  Correlations pre-2022:")
    print(f"    SPY-GLD: {corr_pre.loc['SPY','GLD']:.4f}, SPY-TLT: {corr_pre.loc['SPY','TLT']:.4f}")
    print(f"  Correlations post-2022:")
    print(f"    SPY-GLD: {corr_post.loc['SPY','GLD']:.4f}, SPY-TLT: {corr_post.loc['SPY','TLT']:.4f}")

    # 3. Full-sample strategy performance
    print("\n[3/7] Full-sample strategy performance...")
    ret_a = strategy_static_gld(prices, returns)
    ret_b = strategy_static_tlt(prices, returns)
    ret_c, choices_c = strategy_rate_conditional(prices, returns)
    ret_d, choices_d = strategy_momentum(prices, returns)
    ret_e = strategy_equal_split(prices, returns)
    ret_f = strategy_vol_adjusted(prices, returns)
    ret_g = strategy_static_cash(prices, returns)

    full_strats = {
        "A_Static_GLD": ret_a,
        "B_Static_TLT": ret_b,
        "C_Rate_Conditional": ret_c,
        "D_Momentum": ret_d,
        "E_Equal_Split": ret_e,
        "F_Vol_Adjusted": ret_f,
        "G_Static_Cash": ret_g,
    }

    full_metrics = {}
    for name, ret in full_strats.items():
        m = compute_metrics(ret)
        full_metrics[name] = m
        print(f"  {name}: Sharpe={m['sharpe']:.4f}, Ret={m['ann_return']:.2f}%, "
              f"Vol={m['ann_vol']:.2f}%, MDD={m['max_drawdown']:.2f}%, "
              f"Calmar={m['calmar']:.4f}, Sortino={m['sortino']:.4f}")

    # Choice frequency for switching strategies
    gld_pct_c = sum(1 for c in choices_c if c == "GLD") / len(choices_c) * 100
    gld_pct_d = sum(1 for c in choices_d if c == "GLD") / len(choices_d) * 100
    print(f"\n  Rate-conditional GLD%: {gld_pct_c:.1f}%")
    print(f"  Momentum GLD%: {gld_pct_d:.1f}%")

    # 4. Cross-OOS
    print("\n[4/7] Cross-OOS validation (5 periods)...")
    oos_results, period_details = run_cross_oos(prices, returns, n_periods=5)

    # Average OOS Sharpe
    print("\n  Average OOS Sharpe across periods:")
    avg_oos = {}
    for name, sharpes in oos_results.items():
        avg = np.mean(sharpes)
        std = np.std(sharpes, ddof=1)
        avg_oos[name] = {"mean": round(float(avg), 4), "std": round(float(std), 4), "values": [round(s, 4) for s in sharpes]}
        print(f"    {name}: {avg:.4f} +/- {std:.4f}  {[round(s,3) for s in sharpes]}")

    # 5. Statistical tests
    print("\n[5/7] Statistical tests (all vs A_Static_GLD benchmark)...")
    benchmark_sharpes = oos_results["A_Static_GLD"]
    benchmark_returns = ret_a

    test_results = {}
    for name in full_strats:
        if name == "A_Static_GLD":
            continue

        # Paired t-test across OOS periods
        t_stat, p_val = paired_t_test(oos_results[name], benchmark_sharpes)

        # Bootstrap on full sample
        boot = bootstrap_sharpe_diff(full_strats[name], benchmark_returns, n_boot=10000)

        test_results[name] = {
            "paired_t": {"t_stat": round(t_stat, 4), "p_value": round(p_val, 4)},
            "bootstrap": boot,
        }

        sig = "***" if abs(t_stat) > 3.0 else "**" if abs(t_stat) > 2.0 else "*" if abs(t_stat) > 1.645 else "NS"
        harvey = "PASS Harvey" if abs(t_stat) > 3.0 else "FAIL Harvey"
        print(f"  {name} vs GLD: t={t_stat:.3f} ({sig}), p={p_val:.4f}, "
              f"boot_diff={boot['obs_diff']:.4f}, boot_p={boot['p_value']:.4f} [{harvey}]")

    # 6. Regime analysis
    print("\n[6/7] Regime analysis...")
    regime_results = regime_analysis(prices, returns)

    for regime, data in regime_results.items():
        n = data.get("n_days", 0)
        print(f"\n  {regime} ({n} days):")
        for strat in ["A_Static_GLD", "B_Static_TLT", "C_Rate_Conditional", "D_Momentum", "E_Equal_Split", "F_Vol_Adjusted", "G_Static_Cash"]:
            if strat in data and isinstance(data[strat], dict):
                s = data[strat]
                print(f"    {strat}: Sharpe={s['sharpe']:.4f}, Ret={s['ann_return']:.2f}%")

    # 7. Subperiod analysis
    print("\n[7/7] Subperiod analysis...")
    subperiod_results = subperiod_analysis(prices, returns)

    for period_name, data in subperiod_results.items():
        print(f"\n  {period_name} ({data['n_days']} days):")
        for strat in ["A_Static_GLD", "B_Static_TLT", "C_Rate_Conditional", "D_Momentum", "E_Equal_Split", "F_Vol_Adjusted", "G_Static_Cash"]:
            if strat in data.get("strategies", {}):
                s = data["strategies"][strat]
                print(f"    {strat}: Sharpe={s['sharpe']:.4f}, Ret={s['ann_return']:.2f}%, MDD={s['max_drawdown']:.2f}%")

    # ============================================================
    # COMPILE RESULTS
    # ============================================================

    # Best strategy determination
    best_oos = max(avg_oos.items(), key=lambda x: x[1]["mean"])

    # Any strategy significantly beat GLD?
    significant_improvements = []
    for name, tests in test_results.items():
        if tests["paired_t"]["t_stat"] > 3.0:  # Harvey threshold
            significant_improvements.append(name)

    results = {
        "experiment_id": "K561",
        "title": "Dynamic Bond-Equity Allocation in VT - Safe-Side Switching",
        "timestamp": datetime.now().isoformat(),
        "data_source": "yfinance (SPY, GLD, TLT, ^VIX, ^TNX)",
        "data_period": f"{prices.index[0].date()} to {prices.index[-1].date()}",
        "n_observations": len(returns),
        "methodology": {
            "equity_portion": "12/VIX * 50% in SPY, remainder cash",
            "safe_portion": "Other 50% allocated per strategy",
            "strategies": {
                "A_Static_GLD": "50% in GLD always (benchmark)",
                "B_Static_TLT": "50% in TLT always",
                "C_Rate_Conditional": "GLD when TNX 3m change > 0, TLT when falling",
                "D_Momentum": "Whichever of GLD/TLT has better 60d return",
                "E_Equal_Split": "25% GLD + 25% TLT always",
                "F_Vol_Adjusted": "Inverse-vol weighted between GLD and TLT",
                "G_Static_Cash": "50% in cash (pure VT benchmark)",
            },
            "cross_oos_periods": 5,
            "harvey_threshold": 3.0,
            "bootstrap_reps": 10000,
        },
        "descriptive_stats": {
            "correlations_full": {
                "SPY_GLD": round(float(corr_matrix.loc["SPY", "GLD"]), 4),
                "SPY_TLT": round(float(corr_matrix.loc["SPY", "TLT"]), 4),
                "GLD_TLT": round(float(corr_matrix.loc["GLD", "TLT"]), 4),
            },
            "correlations_pre2022": {
                "SPY_GLD": round(float(corr_pre.loc["SPY", "GLD"]), 4),
                "SPY_TLT": round(float(corr_pre.loc["SPY", "TLT"]), 4),
            },
            "correlations_post2022": {
                "SPY_GLD": round(float(corr_post.loc["SPY", "GLD"]), 4),
                "SPY_TLT": round(float(corr_post.loc["SPY", "TLT"]), 4),
            },
            "tnx_range": [round(float(prices["TNX"].min()), 2), round(float(prices["TNX"].max()), 2)],
        },
        "full_sample_metrics": full_metrics,
        "switching_frequency": {
            "rate_conditional_gld_pct": round(gld_pct_c, 1),
            "momentum_gld_pct": round(gld_pct_d, 1),
        },
        "cross_oos_results": avg_oos,
        "cross_oos_period_details": period_details,
        "statistical_tests_vs_gld": test_results,
        "regime_analysis": regime_results,
        "subperiod_analysis": subperiod_results,
        "findings": {
            "best_full_sample": max(full_metrics.items(), key=lambda x: x[1]["sharpe"])[0],
            "best_oos_avg": best_oos[0],
            "best_oos_sharpe": best_oos[1]["mean"],
            "significant_improvements_vs_gld": significant_improvements,
            "harvey_pass": len(significant_improvements) > 0,
        },
        "conclusion": "",  # filled below
        "references": [
            "Moreira & Muir (2017), Volatility-Managed Portfolios, JoF 72(4):1611-1644",
            "Baele et al. (2010), Flights to Safety, RFS",
            "Campbell, Sunderam, Viceira (2017), Inflation Bets or Deflation Hedges?, JoF 72(4):1645-1692",
            "Prior experiments: T19 (TLT structural break), K425 (bond-equity decorrelation), K507 (dynamic SPY-GLD), N176 (conditional TLT)",
        ],
    }

    # Generate conclusion
    if len(significant_improvements) == 0:
        conclusion = (
            f"No dynamic safe-allocation strategy significantly outperforms static GLD "
            f"at Harvey t>3.0 threshold. Best OOS: {best_oos[0]} (Sharpe={best_oos[1]['mean']:.4f}). "
            f"This extends prior findings (K507, N176): the simplicity of static GLD allocation "
            f"is hard to beat. TLT's structural break post-2022 (T19, K425) means rate-conditional "
            f"switching captures the right regime but with too much noise. "
            f"Recommendation: maintain 50/50 SPY/GLD + 12/VIX framework."
        )
    else:
        best_sig = significant_improvements[0]
        t_val = test_results[best_sig]["paired_t"]["t_stat"]
        conclusion = (
            f"Strategy {best_sig} significantly outperforms static GLD (t={t_val:.3f}, passes Harvey). "
            f"Best OOS: {best_oos[0]} (Sharpe={best_oos[1]['mean']:.4f}). "
            f"This suggests the safe-side allocation CAN be improved by dynamic switching. "
            f"However, implementation complexity and transaction costs should be considered."
        )

    results["conclusion"] = conclusion

    print("\n" + "=" * 70)
    print("CONCLUSION:")
    print(conclusion)
    print("=" * 70)

    # Save results
    output_path = "experiments/k561_bond_equity_switch_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == "__main__":
    results = main()
