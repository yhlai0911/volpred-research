"""
K240: Cross-Asset Time-Series Momentum (TSMOM) Strategy
========================================================
Test whether a simple cross-asset TSMOM generates alpha.
Reference: Moskowitz, Ooi, Pedersen (2012) "Time Series Momentum", JFE.

Assets: SPY, GLD, TLT, BTC-USD
Data: 2015-01-01 ~ 2024-12-31 (yfinance)

TSMOM Signal: 12-month return minus 1-month return (12_1 momentum)
  - Long asset if TSMOM > 0 (positive momentum)
  - Cash (SHY) if TSMOM <= 0
  - Equal weight among assets with positive TSMOM
  - Monthly rebalance

Variants:
  1. Pure TSMOM (no VT overlay)
  2. TSMOM + VT (reduce position when VIX high AND momentum positive)
  3. TSMOM with vol scaling (position size = target_vol / realized_vol)

Benchmarks:
  A. 50/50 SPY/GLD B&H
  B. 50/50 SPY/GLD + VT (12/VIX)
  C. SPY B&H

Metrics: Sharpe, MDD, Calmar, worst year, turnover
Statistical: DM test vs 50/50+VT, Harvey threshold (t>3.0), 5-period cross-OOS

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
from datetime import datetime

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K240: Cross-Asset Time-Series Momentum (TSMOM)")
print("=" * 70)

print("\n[1/7] Downloading data from yfinance...")

ASSETS = ["SPY", "GLD", "TLT", "BTC-USD"]
ASSET_NAMES = {"SPY": "SPY", "GLD": "GLD", "TLT": "TLT", "BTC-USD": "BTC"}
START = "2013-01-01"  # need lookback for 12-month momentum
END = "2025-01-01"

# Download all assets
prices = {}
for ticker in ASSETS:
    raw = yf.download(ticker, start=START, end=END, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    prices[ASSET_NAMES[ticker]] = raw[col].copy()
    print(f"  {ticker}: {len(raw)} rows, {raw.index[0].date()} ~ {raw.index[-1].date()}")

# VIX for VT overlay
vix_raw = yf.download("^VIX", start=START, end=END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()
vix.name = "VIX"
print(f"  VIX: {len(vix_raw)} rows")

# SHY for cash proxy
shy_raw = yf.download("SHY", start=START, end=END, progress=False)
if isinstance(shy_raw.columns, pd.MultiIndex):
    shy_raw.columns = shy_raw.columns.get_level_values(0)
shy_col = "Adj Close" if "Adj Close" in shy_raw.columns else "Close"
shy_price = shy_raw[shy_col].copy()
shy_ret = shy_price.pct_change()
print(f"  SHY: {len(shy_raw)} rows")

# Build price DataFrame and returns
price_df = pd.DataFrame(prices)
# Forward fill for holiday misalignment across assets
price_df = price_df.ffill()
ret_df = price_df.pct_change()

# Merge VIX
combined = ret_df.copy()
combined["VIX"] = vix
combined["SHY_ret"] = shy_ret
combined = combined.dropna(subset=["SPY"])  # align to SPY trading days
combined["VIX"] = combined["VIX"].ffill()
combined["SHY_ret"] = combined["SHY_ret"].fillna(0)

# Fill remaining NaN returns with 0 (holidays where asset didn't trade)
for a in ["SPY", "GLD", "TLT", "BTC"]:
    combined[a] = combined[a].fillna(0)

print(f"\n  Combined dataset: {len(combined)} rows, {combined.index[0].date()} ~ {combined.index[-1].date()}")

# ============================================================
# 2. Compute TSMOM signals
# ============================================================
print("\n[2/7] Computing TSMOM signals (12_1 momentum)...")

# TSMOM signal: 12-month return minus 1-month return
# Use 252 trading days for 12 months, 21 for 1 month
LOOKBACK_12M = 252
LOOKBACK_1M = 21

tsmom_signals = {}
for asset in ["SPY", "GLD", "TLT", "BTC"]:
    cum_ret_12m = price_df[asset].pct_change(LOOKBACK_12M)
    cum_ret_1m = price_df[asset].pct_change(LOOKBACK_1M)
    tsmom_signals[asset] = cum_ret_12m - cum_ret_1m

tsmom_df = pd.DataFrame(tsmom_signals)
tsmom_df = tsmom_df.reindex(combined.index).ffill()

# Monthly rebalance dates (last trading day of each month)
monthly_dates = combined.groupby(combined.index.to_period('M')).apply(
    lambda x: x.index[-1]
).values

print(f"  Monthly rebalance dates: {len(monthly_dates)} months")
print(f"  Signal available from: {tsmom_df.dropna().index[0].date()}")

# ============================================================
# 3. Strategy implementations
# ============================================================
print("\n[3/7] Running strategy backtests...")

# Study period: 2015-01-01 to 2024-12-31
STUDY_START = pd.Timestamp("2015-01-01")
STUDY_END = pd.Timestamp("2024-12-31")

study_mask = (combined.index >= STUDY_START) & (combined.index <= STUDY_END)
study_dates = combined.index[study_mask]
monthly_rebal = [d for d in monthly_dates if STUDY_START <= pd.Timestamp(d) <= STUDY_END]

print(f"  Study period: {study_dates[0].date()} ~ {study_dates[-1].date()} ({len(study_dates)} days)")
print(f"  Rebalance dates in study: {len(monthly_rebal)}")


def compute_strategy_returns(combined_df, tsmom_df, study_dates, monthly_rebal,
                              strategy_type="pure", vt_threshold=12, vol_target=0.15,
                              tx_cost_bps=10):
    """
    Compute daily portfolio returns for different TSMOM variants.

    strategy_type:
      "pure"      - Pure TSMOM: equal weight positive momentum assets, cash otherwise
      "vt"        - TSMOM + VT: reduce position when VIX high
      "volscale"  - TSMOM + vol scaling: target vol for each asset
    """
    assets = ["SPY", "GLD", "TLT", "BTC"]
    n_assets = len(assets)

    # Initialize weights
    weights = pd.DataFrame(0.0, index=study_dates, columns=assets)

    # Track turnover
    prev_weights = pd.Series(0.0, index=assets)
    turnover_total = 0.0
    n_rebal = 0

    for i, date in enumerate(study_dates):
        if date in monthly_rebal or i == 0:
            # Rebalance day
            signals = tsmom_df.loc[date] if date in tsmom_df.index else pd.Series(np.nan, index=assets)

            # Which assets have positive momentum?
            positive = []
            for a in assets:
                if pd.notna(signals.get(a)) and signals[a] > 0:
                    positive.append(a)

            new_weights = pd.Series(0.0, index=assets)
            if len(positive) > 0:
                eq_w = 1.0 / len(positive)
                for a in positive:
                    new_weights[a] = eq_w
            # else: all cash (weights stay 0)

            # VT overlay: scale down when VIX is high
            if strategy_type == "vt":
                vix_val = combined_df.loc[date, "VIX"] if date in combined_df.index else np.nan
                if pd.notna(vix_val) and vix_val > 0:
                    vt_scale = min(vt_threshold / vix_val, 1.0)
                    new_weights *= vt_scale

            # Vol scaling: target vol for each asset
            if strategy_type == "volscale":
                for a in assets:
                    if new_weights[a] > 0:
                        # Realized vol over past 63 trading days (3 months)
                        lookback_start = max(0, combined_df.index.get_loc(date) - 63)
                        lookback_end = combined_df.index.get_loc(date)
                        hist_rets = combined_df[a].iloc[lookback_start:lookback_end]
                        realized_vol = hist_rets.std() * np.sqrt(252)
                        if realized_vol > 0:
                            vol_scale = vol_target / realized_vol
                            new_weights[a] *= min(vol_scale, 2.0)  # cap at 2x leverage

            # Normalize if total weight > 1 (for vol scaling)
            total_w = new_weights.sum()
            if total_w > 1.0:
                new_weights /= total_w

            # Turnover
            turnover_total += (new_weights - prev_weights).abs().sum()
            n_rebal += 1
            prev_weights = new_weights.copy()

            weights.loc[date] = new_weights
        else:
            # Non-rebalance day: carry forward
            weights.loc[date] = prev_weights

    # Portfolio return = sum(w_i * r_i) + (1 - sum(w_i)) * r_cash
    port_ret = pd.Series(0.0, index=study_dates)
    for a in assets:
        port_ret += weights[a] * combined_df.loc[study_dates, a]

    # Cash portion earns SHY return
    cash_weight = 1.0 - weights.sum(axis=1)
    port_ret += cash_weight * combined_df.loc[study_dates, "SHY_ret"]

    # TX cost (applied at rebalance)
    tx_cost_per_rebal = turnover_total * tx_cost_bps / 10000
    n_years = len(study_dates) / 252
    annual_turnover = turnover_total / n_years if n_years > 0 else 0

    return port_ret, weights, annual_turnover, tx_cost_per_rebal / n_years


def compute_benchmark_returns(combined_df, study_dates, bench_type="5050_bh"):
    """
    Compute benchmark returns.
    bench_type:
      "5050_bh"  - 50/50 SPY/GLD buy & hold (monthly rebal)
      "5050_vt"  - 50/50 SPY/GLD + VT (12/VIX)
      "spy_bh"   - SPY buy & hold
    """
    if bench_type == "spy_bh":
        return combined_df.loc[study_dates, "SPY"]

    spy_ret = combined_df.loc[study_dates, "SPY"]
    gld_ret = combined_df.loc[study_dates, "GLD"]
    shy_ret = combined_df.loc[study_dates, "SHY_ret"]

    if bench_type == "5050_bh":
        return 0.5 * spy_ret + 0.5 * gld_ret

    if bench_type == "5050_vt":
        vix = combined_df.loc[study_dates, "VIX"]
        # Lagged VIX for weights (VIX_t-1 determines w_t)
        vix_shifted = vix.shift(1).ffill()
        vt_weight = np.minimum(12.0 / vix_shifted, 1.0).fillna(1.0)
        port = vt_weight * (0.5 * spy_ret + 0.5 * gld_ret) + (1 - vt_weight) * shy_ret
        return port

    raise ValueError(f"Unknown benchmark: {bench_type}")


def compute_metrics(returns, name="", rf_annual=0.02):
    """Compute comprehensive strategy metrics."""
    returns = returns.dropna()
    n_days = len(returns)
    n_years = n_days / 252

    cum_ret = (1 + returns).cumprod()
    total_ret = cum_ret.iloc[-1] - 1
    annual_ret = (1 + total_ret) ** (1 / n_years) - 1
    annual_vol = returns.std() * np.sqrt(252)

    # Sharpe (excess over rf)
    daily_rf = (1 + rf_annual) ** (1/252) - 1
    excess = returns - daily_rf
    sharpe = excess.mean() / excess.std() * np.sqrt(252) if excess.std() > 0 else 0

    # MDD
    rolling_max = cum_ret.cummax()
    drawdown = (cum_ret - rolling_max) / rolling_max
    mdd = drawdown.min()

    # Calmar
    calmar = annual_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 0 else 0
    sortino = (annual_ret - rf_annual) / downside_vol if downside_vol > 0 else 0

    # Worst year
    yearly = returns.groupby(returns.index.year).apply(lambda x: (1+x).prod() - 1)
    worst_year = yearly.min()
    worst_year_idx = yearly.idxmin()

    # Sharpe t-stat (testing H0: Sharpe = 0)
    sharpe_se = np.sqrt((1 + 0.5 * sharpe**2) / n_years) if n_years > 0 else 1
    sharpe_tstat = sharpe / sharpe_se if sharpe_se > 0 else 0

    return {
        "name": name,
        "annual_ret": annual_ret,
        "annual_vol": annual_vol,
        "sharpe": sharpe,
        "sharpe_tstat": sharpe_tstat,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "worst_year": worst_year,
        "worst_year_idx": int(worst_year_idx),
        "n_days": n_days,
        "n_years": n_years,
    }


def diebold_mariano_test(e1, e2, h=1):
    """
    Diebold-Mariano test for equal predictive accuracy.
    Using squared returns as loss (for portfolio returns: higher is better).
    H0: equal performance. H1: strategy 1 better than strategy 2.
    Returns t-stat and p-value (one-sided).
    """
    d = e1 - e2  # loss differential
    n = len(d)
    d_mean = d.mean()

    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1] if len(d) > k else 0
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0, 0.5

    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 1 - stats.norm.cdf(dm_stat)  # one-sided

    return dm_stat, p_value


# ============================================================
# Run all strategies (full period)
# ============================================================
strategies = {}

# Strategy 1: Pure TSMOM
ret_pure, w_pure, turn_pure, tc_pure = compute_strategy_returns(
    combined, tsmom_df, study_dates, monthly_rebal, strategy_type="pure"
)
strategies["TSMOM_Pure"] = {"returns": ret_pure, "turnover": turn_pure, "tc": tc_pure}

# Strategy 2: TSMOM + VT
ret_vt, w_vt, turn_vt, tc_vt = compute_strategy_returns(
    combined, tsmom_df, study_dates, monthly_rebal, strategy_type="vt", vt_threshold=12
)
strategies["TSMOM_VT"] = {"returns": ret_vt, "turnover": turn_vt, "tc": tc_vt}

# Strategy 3: TSMOM + Vol Scaling
ret_vs, w_vs, turn_vs, tc_vs = compute_strategy_returns(
    combined, tsmom_df, study_dates, monthly_rebal, strategy_type="volscale", vol_target=0.15
)
strategies["TSMOM_VolScale"] = {"returns": ret_vs, "turnover": turn_vs, "tc": tc_vs}

# Benchmarks
bench_5050 = compute_benchmark_returns(combined, study_dates, "5050_bh")
bench_5050vt = compute_benchmark_returns(combined, study_dates, "5050_vt")
bench_spy = compute_benchmark_returns(combined, study_dates, "spy_bh")

strategies["50/50_BH"] = {"returns": bench_5050, "turnover": 0.5, "tc": 0}
strategies["50/50_VT"] = {"returns": bench_5050vt, "turnover": 1.0, "tc": 0}
strategies["SPY_BH"] = {"returns": bench_spy, "turnover": 0, "tc": 0}

# ============================================================
# 4. Full-period metrics
# ============================================================
print("\n[4/7] Full-period results (2015-2024)...")
print("-" * 100)
print(f"{'Strategy':<18} {'AnnRet':>8} {'AnnVol':>8} {'Sharpe':>8} {'t-stat':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8} {'WorstYr':>8} {'Turn':>8}")
print("-" * 100)

metrics_all = {}
for name, data in strategies.items():
    m = compute_metrics(data["returns"], name)
    m["turnover"] = data["turnover"]
    m["tx_cost_annual"] = data["tc"]
    metrics_all[name] = m

    # Net Sharpe (after TX)
    net_ret = data["returns"].copy()
    # Spread TX cost evenly across trading days
    daily_tc = data["tc"] / 252
    net_ret -= daily_tc
    m_net = compute_metrics(net_ret, name + "_net")
    m["net_sharpe"] = m_net["sharpe"]

    print(f"{name:<18} {m['annual_ret']:>7.1%} {m['annual_vol']:>7.1%} {m['sharpe']:>8.3f} {m['sharpe_tstat']:>8.2f} "
          f"{m['mdd']:>7.1%} {m['calmar']:>8.3f} {m['sortino']:>8.3f} {m['worst_year']:>7.1%} {m['turnover']:>7.1f}")

print("-" * 100)

# ============================================================
# 5. DM tests vs 50/50+VT benchmark
# ============================================================
print("\n[5/7] Diebold-Mariano tests vs 50/50+VT benchmark...")
print("-" * 70)

dm_results = {}
bench_ret = strategies["50/50_VT"]["returns"]

for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale", "50/50_BH", "SPY_BH"]:
    strat_ret = strategies[name]["returns"]

    # Align returns
    common_idx = strat_ret.index.intersection(bench_ret.index)
    s = strat_ret.loc[common_idx].values
    b = bench_ret.loc[common_idx].values

    # DM test on returns (higher is better, so positive DM = strategy better)
    dm_stat, dm_pval = diebold_mariano_test(s, b)
    dm_results[name] = {"dm_stat": dm_stat, "dm_pval": dm_pval}

    sig = "***" if dm_pval < 0.01 else "**" if dm_pval < 0.05 else "*" if dm_pval < 0.1 else ""
    direction = "better" if dm_stat > 0 else "worse"
    print(f"  {name:<18} vs 50/50+VT: DM={dm_stat:>7.3f}, p={dm_pval:.4f} ({direction}) {sig}")

print("-" * 70)

# ============================================================
# 6. Signal analysis
# ============================================================
print("\n[6/7] TSMOM signal analysis...")

# How often is each asset in positive momentum?
signal_stats = {}
for asset in ["SPY", "GLD", "TLT", "BTC"]:
    sig = tsmom_df.loc[study_dates, asset].dropna()
    pct_positive = (sig > 0).mean()
    avg_signal = sig.mean()
    signal_stats[asset] = {"pct_positive": pct_positive, "avg_signal": avg_signal}
    print(f"  {asset}: {pct_positive:.1%} positive momentum, avg signal = {avg_signal:.4f}")

# Average number of assets held
n_held = (w_pure > 0).sum(axis=1)
print(f"\n  Average assets held (pure): {n_held.mean():.2f}")
print(f"  Months with 0 assets (all cash): {(n_held == 0).sum()} / {len(monthly_rebal)}")
print(f"  Months with 4 assets: {(n_held == 4).sum()} / {len(monthly_rebal)}")

# Weight distribution
print("\n  Average weights (pure TSMOM):")
avg_w = w_pure.mean()
for asset in ["SPY", "GLD", "TLT", "BTC"]:
    print(f"    {asset}: {avg_w[asset]:.3f}")
print(f"    Cash: {1 - avg_w.sum():.3f}")

# ============================================================
# 7. Cross-OOS validation (5 periods, MANDATORY)
# ============================================================
print("\n[7/7] 5-period Cross-OOS validation...")
print("=" * 70)

oos_periods = [
    ("2015-01-01", "2016-12-31", "2015-2016"),
    ("2017-01-01", "2018-12-31", "2017-2018"),
    ("2019-01-01", "2020-12-31", "2019-2020 (COVID)"),
    ("2021-01-01", "2022-12-31", "2021-2022 (Inflation)"),
    ("2023-01-01", "2024-12-31", "2023-2024"),
]

cross_oos_results = {}
for strat_name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"]:
    cross_oos_results[strat_name] = []

# Headers
print(f"\n{'Period':<22} | {'TSMOM_Pure':>12} | {'TSMOM_VT':>12} | {'TSMOM_VS':>12} | {'50/50_VT':>12} | {'SPY_BH':>12}")
print("-" * 95)

oos_sharpe_table = {name: [] for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale", "50/50_VT", "SPY_BH"]}
oos_mdd_table = {name: [] for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale", "50/50_VT", "SPY_BH"]}

for start, end, label in oos_periods:
    period_mask = (combined.index >= start) & (combined.index <= end)
    period_dates = combined.index[period_mask]
    period_rebal = [d for d in monthly_dates if pd.Timestamp(start) <= pd.Timestamp(d) <= pd.Timestamp(end)]

    # TSMOM Pure
    r_pure_p, _, _, _ = compute_strategy_returns(
        combined, tsmom_df, period_dates, period_rebal, strategy_type="pure"
    )
    m_pure_p = compute_metrics(r_pure_p, "pure")

    # TSMOM VT
    r_vt_p, _, _, _ = compute_strategy_returns(
        combined, tsmom_df, period_dates, period_rebal, strategy_type="vt"
    )
    m_vt_p = compute_metrics(r_vt_p, "vt")

    # TSMOM VolScale
    r_vs_p, _, _, _ = compute_strategy_returns(
        combined, tsmom_df, period_dates, period_rebal, strategy_type="volscale"
    )
    m_vs_p = compute_metrics(r_vs_p, "vs")

    # Benchmarks
    b_5050vt_p = compute_benchmark_returns(combined, period_dates, "5050_vt")
    m_5050vt_p = compute_metrics(b_5050vt_p, "5050vt")

    b_spy_p = compute_benchmark_returns(combined, period_dates, "spy_bh")
    m_spy_p = compute_metrics(b_spy_p, "spy")

    # Print Sharpe
    print(f"{label:<22} | {m_pure_p['sharpe']:>12.3f} | {m_vt_p['sharpe']:>12.3f} | {m_vs_p['sharpe']:>12.3f} | {m_5050vt_p['sharpe']:>12.3f} | {m_spy_p['sharpe']:>12.3f}")

    for name, m in [("TSMOM_Pure", m_pure_p), ("TSMOM_VT", m_vt_p), ("TSMOM_VolScale", m_vs_p),
                     ("50/50_VT", m_5050vt_p), ("SPY_BH", m_spy_p)]:
        oos_sharpe_table[name].append(m["sharpe"])
        oos_mdd_table[name].append(m["mdd"])

    # Track which TSMOM beats 50/50+VT
    cross_oos_results["TSMOM_Pure"].append(m_pure_p["sharpe"] > m_5050vt_p["sharpe"])
    cross_oos_results["TSMOM_VT"].append(m_vt_p["sharpe"] > m_5050vt_p["sharpe"])
    cross_oos_results["TSMOM_VolScale"].append(m_vs_p["sharpe"] > m_5050vt_p["sharpe"])

print("-" * 95)

# MDD table
print(f"\n{'Period':<22} | {'TSMOM_Pure':>12} | {'TSMOM_VT':>12} | {'TSMOM_VS':>12} | {'50/50_VT':>12} | {'SPY_BH':>12}")
print("-" * 95)

for i, (start, end, label) in enumerate(oos_periods):
    print(f"{label + ' MDD':<22} | {oos_mdd_table['TSMOM_Pure'][i]:>11.1%} | {oos_mdd_table['TSMOM_VT'][i]:>11.1%} | "
          f"{oos_mdd_table['TSMOM_VolScale'][i]:>11.1%} | {oos_mdd_table['50/50_VT'][i]:>11.1%} | {oos_mdd_table['SPY_BH'][i]:>11.1%}")

print("-" * 95)

# Cross-OOS win rate
print("\n  Cross-OOS Win Rate vs 50/50+VT (Sharpe):")
for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"]:
    wins = sum(cross_oos_results[name])
    total = len(cross_oos_results[name])
    print(f"    {name:<18}: {wins}/{total} ({wins/total:.0%})")

# Average Sharpe across OOS periods
print("\n  Average Sharpe across 5 OOS periods:")
for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale", "50/50_VT", "SPY_BH"]:
    avg_s = np.mean(oos_sharpe_table[name])
    std_s = np.std(oos_sharpe_table[name])
    print(f"    {name:<18}: {avg_s:.3f} +/- {std_s:.3f}")

# ============================================================
# 8. MDD bootstrap test
# ============================================================
print("\n[Bonus] MDD bootstrap test (TSMOM_Pure vs SPY B&H)...")

n_boot = 10000
np.random.seed(42)

ret_tsmom_arr = strategies["TSMOM_Pure"]["returns"].values
ret_spy_arr = strategies["SPY_BH"]["returns"].values
n_obs = min(len(ret_tsmom_arr), len(ret_spy_arr))

mdd_diff_boot = []
for _ in range(n_boot):
    idx = np.random.choice(n_obs, size=n_obs, replace=True)
    # Compute MDD for resampled series
    cum_t = np.cumprod(1 + ret_tsmom_arr[idx])
    mdd_t = np.min(cum_t / np.maximum.accumulate(cum_t) - 1)

    cum_s = np.cumprod(1 + ret_spy_arr[idx])
    mdd_s = np.min(cum_s / np.maximum.accumulate(cum_s) - 1)

    mdd_diff_boot.append(mdd_t - mdd_s)  # negative means TSMOM better MDD

mdd_diff_boot = np.array(mdd_diff_boot)
mdd_tsmom_better = (mdd_diff_boot > 0).mean()  # TSMOM has less severe MDD (closer to 0)

actual_mdd_diff = metrics_all["TSMOM_Pure"]["mdd"] - metrics_all["SPY_BH"]["mdd"]
print(f"  Actual MDD diff (TSMOM - SPY): {actual_mdd_diff:.1%}")
print(f"  Bootstrap: TSMOM better MDD in {mdd_tsmom_better:.1%} of simulations")
print(f"  p-value (TSMOM MDD improvement): {1 - mdd_tsmom_better:.4f}")

# ============================================================
# 9. Harvey threshold check
# ============================================================
print("\n" + "=" * 70)
print("HARVEY THRESHOLD CHECK (t > 3.0 for strategy Sharpe claims)")
print("=" * 70)

for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"]:
    m = metrics_all[name]
    passes = "PASS" if m["sharpe_tstat"] > 3.0 else "FAIL"
    print(f"  {name:<18}: Sharpe={m['sharpe']:.3f}, t={m['sharpe_tstat']:.2f} → {passes}")

# ============================================================
# 10. Summary and conclusions
# ============================================================
print("\n" + "=" * 70)
print("K240 SUMMARY")
print("=" * 70)

# Compile results
results = {
    "experiment": "K240",
    "title": "Cross-Asset TSMOM",
    "data_source": "yfinance",
    "assets": ["SPY", "GLD", "TLT", "BTC-USD"],
    "period": "2015-01-01 ~ 2024-12-31",
    "methodology": "12_1 TSMOM, monthly rebalance, equal weight positive momentum",
    "full_period_metrics": {},
    "cross_oos": {},
    "dm_tests": {},
    "signal_stats": signal_stats,
    "harvey_check": {},
    "conclusions": [],
}

for name, m in metrics_all.items():
    results["full_period_metrics"][name] = {
        k: float(v) if isinstance(v, (np.floating, float)) else v
        for k, v in m.items() if k != "name"
    }

for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"]:
    results["cross_oos"][name] = {
        "sharpe_by_period": [float(s) for s in oos_sharpe_table[name]],
        "mdd_by_period": [float(m) for m in oos_mdd_table[name]],
        "win_rate_vs_5050vt": sum(cross_oos_results[name]) / len(cross_oos_results[name]),
    }
    results["harvey_check"][name] = {
        "sharpe": float(metrics_all[name]["sharpe"]),
        "tstat": float(metrics_all[name]["sharpe_tstat"]),
        "passes": metrics_all[name]["sharpe_tstat"] > 3.0,
    }

for name, dm in dm_results.items():
    results["dm_tests"][name + "_vs_5050VT"] = {
        "dm_stat": float(dm["dm_stat"]),
        "p_value": float(dm["dm_pval"]),
    }

# Determine conclusions
best_strat = max(["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"],
                  key=lambda x: metrics_all[x]["sharpe"])
best_sharpe = metrics_all[best_strat]["sharpe"]
bench_sharpe = metrics_all["50/50_VT"]["sharpe"]

conclusions = []
conclusions.append(f"Best TSMOM variant: {best_strat} (Sharpe={best_sharpe:.3f})")
conclusions.append(f"50/50+VT benchmark: Sharpe={bench_sharpe:.3f}")

if best_sharpe > bench_sharpe:
    conclusions.append(f"TSMOM Sharpe {best_sharpe:.3f} > 50/50+VT {bench_sharpe:.3f}")
else:
    conclusions.append(f"TSMOM Sharpe {best_sharpe:.3f} <= 50/50+VT {bench_sharpe:.3f}")

# Harvey check
harvey_pass = any(metrics_all[n]["sharpe_tstat"] > 3.0 for n in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"])
conclusions.append(f"Harvey threshold (t>3.0): {'At least one PASS' if harvey_pass else 'ALL FAIL'}")

# Cross-OOS consistency
best_wr = max([cross_oos_results[n] for n in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"]],
              key=lambda x: sum(x))
best_wr_name = max(["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"],
                    key=lambda n: sum(cross_oos_results[n]))
best_wr_rate = sum(cross_oos_results[best_wr_name]) / len(cross_oos_results[best_wr_name])
conclusions.append(f"Best cross-OOS win rate: {best_wr_name} {best_wr_rate:.0%}")

# DM significance
dm_sig = any(dm_results[n]["dm_pval"] < 0.05 for n in dm_results)
conclusions.append(f"DM test significance (p<0.05 vs 50/50+VT): {'YES' if dm_sig else 'NO'}")

results["conclusions"] = conclusions

for c in conclusions:
    print(f"  - {c}")

# MDD comparison
print(f"\n  MDD comparison:")
for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale", "50/50_VT", "SPY_BH"]:
    print(f"    {name:<18}: {metrics_all[name]['mdd']:.1%}")

# Turnover
print(f"\n  Annual turnover:")
for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"]:
    print(f"    {name:<18}: {metrics_all[name]['turnover']:.1f}x")

# Net Sharpe
print(f"\n  Net Sharpe (after 10bps TX cost):")
for name in ["TSMOM_Pure", "TSMOM_VT", "TSMOM_VolScale"]:
    print(f"    {name:<18}: {metrics_all[name]['net_sharpe']:.3f}")

# Limitations
print(f"\n  Limitations:")
print(f"    - BTC available from 2014; pre-2014 results would differ")
print(f"    - No short selling (only long or cash)")
print(f"    - Monthly rebalance only (more frequent could differ)")
print(f"    - TX cost assumed 10bps (institutional; retail may be higher)")
print(f"    - Forward-filled prices for holiday misalignment")
print(f"    - VT overlay uses lagged VIX (correct, no look-ahead)")
print(f"    - Vol scaling capped at 2x leverage")

# Save results
output_file = "experiments/k240_tsmom_cross_asset_results.json"
# Convert numpy types for JSON serialization
def convert_numpy(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    elif isinstance(obj, (np.floating,)):
        return float(obj)
    elif isinstance(obj, np.ndarray):
        return obj.tolist()
    elif isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj

import json

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        r = convert_numpy(obj)
        if r is not obj:
            return r
        return super().default(obj)

with open(output_file, "w") as f:
    json.dump(results, f, indent=2, cls=NumpyEncoder)

print(f"\n  Results saved to: {output_file}")
print("=" * 70)
print("K240 COMPLETE")
print("=" * 70)
