"""
K209: Two-Tier VT Backtest — VIX for Equities, OwnVol for Others
================================================================
Background:
  K207 established a two-tier framework: VIX sufficient for equities,
  own-vol for non-equities. K206 showed asset-specific VT lost in
  portfolio context (predictor paradox). Can we resolve this paradox
  by using the two-tier approach more carefully?

Methodology:
  1. Three portfolio variants (50/50 SPY/GLD base):
     - Uniform VIX: both assets use 12/VIX
     - Two-tier: SPY uses 12/VIX, GLD uses 12/own_22d_vol
     - Hybrid: SPY uses 12/VIX, GLD uses max(12/VIX, 12/own_vol) (conservative)
  2. Monthly rebalancing, TX 0.1%/trade
  3. 5-period cross-OOS validation (MANDATORY)
  4. Also test 3-asset (SPY/GLD/TLT):
     - SPY: 12/VIX, GLD: 12/own_vol, TLT: 12/own_vol
  5. Key metrics: Sharpe, MDD, Calmar, turnover

Data: SPY, GLD, TLT daily from yfinance. OOS: 5-period cross-OOS 2015-2024.
Statistical requirements: Harvey t>3.0, 5 cross-OOS periods.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
TARGET_VOL_ANNUAL = 0.12  # 12% annual target (matching 12/VIX convention)
TARGET_VOL_DAILY = TARGET_VOL_ANNUAL / np.sqrt(252)
MAX_LEVERAGE = 2.0
TX_COST = 0.001  # 0.1% per trade (10bps)
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

DATA_START = "2004-01-01"

# 5-period cross-OOS windows (each ~2 years)
OOS_PERIODS = [
    ("2015-01-01", "2016-12-31"),  # P1: calm + China scare
    ("2017-01-01", "2018-12-31"),  # P2: low vol + Volmageddon
    ("2019-01-01", "2020-12-31"),  # P3: pre-COVID + COVID crash
    ("2021-01-01", "2022-12-31"),  # P4: meme stocks + rate hikes
    ("2023-01-01", "2024-12-31"),  # P5: AI rally + normalization
]

OWN_VOL_WINDOW = 22  # 22-day realized vol (1 month)

print("=" * 80)
print("K209: Two-Tier VT Backtest — VIX for Equities, OwnVol for Others")
print("=" * 80)

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/6] Downloading SPY, GLD, TLT, ^VIX data from yfinance...")

tickers = ["SPY", "GLD", "TLT", "^VIX"]
raw_data = {}
for t in tickers:
    df = yf.download(t, start=DATA_START, end="2025-12-31", progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    key = t.replace("^", "")
    raw_data[key] = df[["Close"]].rename(columns={"Close": key})

# Merge all on date
merged = raw_data["SPY"]
for key in ["GLD", "TLT", "VIX"]:
    merged = merged.join(raw_data[key], how="inner")
merged = merged.dropna()

# Compute log returns
for asset in ["SPY", "GLD", "TLT"]:
    merged[f"{asset}_ret"] = np.log(merged[asset] / merged[asset].shift(1))
merged = merged.dropna()

# VIX daily vol (VIX/100/sqrt(252)) -- used for VIX-based VT
merged["VIX_daily"] = merged["VIX"] / 100 / np.sqrt(252)

# Own 22-day realized vol for each asset
for asset in ["SPY", "GLD", "TLT"]:
    merged[f"{asset}_own_vol"] = merged[f"{asset}_ret"].rolling(OWN_VOL_WINDOW).std()

merged = merged.dropna()

print(f"  Data range: {merged.index[0].date()} to {merged.index[-1].date()}")
print(f"  Total trading days (after dropna): {len(merged)}")

# ==================================================================
# 2. Define Strategy Variants
# ==================================================================
print("\n[2/6] Defining strategy variants...")

def compute_monthly_vt_weights(prices_df, vix_daily, own_vol_dict, strategy_type,
                                target_daily=TARGET_VOL_DAILY, max_lev=MAX_LEVERAGE):
    """
    Compute monthly-rebalanced VT weights for a portfolio.

    strategy_type:
      'uniform_vix'   - all assets use 12/VIX
      'two_tier'      - equities use 12/VIX, non-equities use 12/own_vol
      'hybrid'        - equities use 12/VIX, non-equities use min(12/VIX, 12/own_vol)
                        (i.e. max weight = min exposure = more conservative)
      'buy_hold'      - equal weight, no VT

    own_vol_dict: dict of asset_name -> own_vol_series
    """
    n = len(prices_df)
    assets = [c for c in prices_df.columns if c not in ["VIX", "VIX_daily"] and not c.endswith("_ret") and not c.endswith("_own_vol")]

    # Determine which assets are equities (use VIX) vs non-equities (own vol)
    equity_assets = {"SPY"}
    non_equity_assets = {"GLD", "TLT"}

    n_assets = len(assets)
    base_weight = 1.0 / n_assets  # equal base allocation

    # We'll compute weights at month-start, hold for the month
    weights = pd.DataFrame(index=prices_df.index, columns=assets, dtype=float)

    if strategy_type == "buy_hold":
        weights[:] = base_weight
        return weights

    # Monthly rebalance dates
    month_groups = prices_df.index.to_period("M")
    rebal_dates = []
    for period in month_groups.unique():
        mask = month_groups == period
        first_day = prices_df.index[mask][0]
        rebal_dates.append(first_day)

    # Compute VT weight for each asset at each rebalance date
    current_weights = {a: base_weight for a in assets}

    for i, idx in enumerate(prices_df.index):
        if idx in rebal_dates:
            for asset in assets:
                if strategy_type == "uniform_vix":
                    # All assets use VIX-based vol
                    vol_est = vix_daily.loc[idx]
                    vt_scalar = target_daily / vol_est if vol_est > 0 else 1.0

                elif strategy_type == "two_tier":
                    if asset in equity_assets:
                        vol_est = vix_daily.loc[idx]
                    else:
                        vol_est = own_vol_dict[asset].loc[idx]
                    vt_scalar = target_daily / vol_est if vol_est > 0 else 1.0

                elif strategy_type == "hybrid":
                    if asset in equity_assets:
                        vol_est = vix_daily.loc[idx]
                    else:
                        # Use the HIGHER vol estimate (more conservative = lower weight)
                        vol_vix = vix_daily.loc[idx]
                        vol_own = own_vol_dict[asset].loc[idx]
                        vol_est = max(vol_vix, vol_own)
                    vt_scalar = target_daily / vol_est if vol_est > 0 else 1.0

                vt_scalar = np.clip(vt_scalar, 0, max_lev)
                current_weights[asset] = base_weight * vt_scalar

        for asset in assets:
            weights.loc[idx, asset] = current_weights[asset]

    return weights


def run_strategy(merged_df, assets, strategy_type, own_vol_dict, period_label="full"):
    """Run a single strategy over the given dataframe. Returns metrics dict."""
    # Extract returns
    ret_cols = {a: f"{a}_ret" for a in assets}

    # Compute weights
    weights = compute_monthly_vt_weights(
        merged_df, merged_df["VIX_daily"], own_vol_dict, strategy_type
    )

    # Portfolio return = sum of (weight_i * return_i) for each day
    port_ret = pd.Series(0.0, index=merged_df.index)
    for asset in assets:
        port_ret += weights[asset] * merged_df[ret_cols[asset]]

    # Transaction costs (at monthly rebalance)
    month_groups = merged_df.index.to_period("M")
    rebal_dates = set()
    for period in month_groups.unique():
        mask = month_groups == period
        first_day = merged_df.index[mask][0]
        rebal_dates.add(first_day)

    tx_costs = pd.Series(0.0, index=merged_df.index)
    prev_weights = None
    for idx in merged_df.index:
        w_today = weights.loc[idx].values.astype(float)
        if prev_weights is not None and idx in rebal_dates:
            turnover = np.sum(np.abs(w_today - prev_weights))
            tx_costs.loc[idx] = turnover * TX_COST
        prev_weights = w_today.copy()

    port_ret_net = port_ret - tx_costs

    # Compute metrics
    n_days = len(port_ret_net)
    n_years = n_days / 252

    # Use simple returns for cumulative
    cum_simple = np.exp(port_ret_net.cumsum())
    total_return = cum_simple.iloc[-1] / cum_simple.iloc[0] - 1
    annual_return = (1 + total_return) ** (1 / n_years) - 1 if n_years > 0 else 0

    daily_excess = port_ret_net - RF_DAILY
    sharpe = daily_excess.mean() / daily_excess.std() * np.sqrt(252) if daily_excess.std() > 0 else 0

    # MDD
    cum_max = cum_simple.cummax()
    drawdown = (cum_simple - cum_max) / cum_max
    mdd = drawdown.min()

    # Calmar
    calmar = annual_return / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = daily_excess[daily_excess < 0]
    sortino = daily_excess.mean() / downside.std() * np.sqrt(252) if len(downside) > 0 and downside.std() > 0 else 0

    # Turnover (annualized)
    total_turnover = tx_costs.sum() / TX_COST  # total weight changes
    annual_turnover = total_turnover / n_years if n_years > 0 else 0

    # Average leverage
    avg_leverage = weights.sum(axis=1).mean()

    # Volatility
    annual_vol = port_ret_net.std() * np.sqrt(252)

    return {
        "period": period_label,
        "strategy": strategy_type,
        "n_days": n_days,
        "n_years": round(n_years, 2),
        "annual_return": round(annual_return * 100, 2),
        "annual_vol": round(annual_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "annual_turnover": round(annual_turnover, 1),
        "avg_leverage": round(avg_leverage, 3),
        "daily_returns": port_ret_net.values,
    }


# ==================================================================
# 3. Run 2-Asset (SPY/GLD) across 5 OOS periods
# ==================================================================
print("\n[3/6] Running 2-Asset (50/50 SPY/GLD) across 5 OOS periods...")

ASSETS_2 = ["SPY", "GLD"]
strategies_2 = ["buy_hold", "uniform_vix", "two_tier", "hybrid"]

own_vol_dict = {
    "SPY": merged["SPY_own_vol"],
    "GLD": merged["GLD_own_vol"],
    "TLT": merged["TLT_own_vol"],
}

results_2asset = []

for pi, (start, end) in enumerate(OOS_PERIODS):
    period_data = merged.loc[start:end].copy()
    if len(period_data) < 50:
        print(f"  WARNING: Period {pi+1} ({start} to {end}) has only {len(period_data)} days, skipping")
        continue

    print(f"  Period {pi+1}: {start} to {end} ({len(period_data)} days)")

    for strat in strategies_2:
        result = run_strategy(period_data, ASSETS_2, strat, own_vol_dict,
                             period_label=f"P{pi+1}")
        results_2asset.append(result)
        print(f"    {strat:15s}: Sharpe={result['sharpe']:.3f}  MDD={result['mdd']:.1f}%  "
              f"Calmar={result['calmar']:.3f}  Turnover={result['annual_turnover']:.0f}")

# Summary table for 2-asset
print("\n" + "=" * 80)
print("2-ASSET (50/50 SPY/GLD) CROSS-OOS SUMMARY")
print("=" * 80)

for strat in strategies_2:
    strat_results = [r for r in results_2asset if r["strategy"] == strat]
    sharpes = [r["sharpe"] for r in strat_results]
    mdds = [r["mdd"] for r in strat_results]
    calmars = [r["calmar"] for r in strat_results]

    mean_sharpe = np.mean(sharpes)
    std_sharpe = np.std(sharpes, ddof=1)
    t_stat = mean_sharpe / (std_sharpe / np.sqrt(len(sharpes))) if std_sharpe > 0 else 0
    mean_mdd = np.mean(mdds)
    mean_calmar = np.mean(calmars)

    # Count how many periods beat buy_hold
    if strat != "buy_hold":
        bh_sharpes = [r["sharpe"] for r in results_2asset if r["strategy"] == "buy_hold"]
        wins = sum(1 for s, bh in zip(sharpes, bh_sharpes) if s > bh)
        win_str = f"  Wins vs BH: {wins}/{len(sharpes)}"
    else:
        win_str = ""

    print(f"  {strat:15s}: Mean Sharpe={mean_sharpe:.3f} (t={t_stat:.2f})  "
          f"Mean MDD={mean_mdd:.1f}%  Mean Calmar={mean_calmar:.3f}{win_str}")


# ==================================================================
# 4. Run 3-Asset (SPY/GLD/TLT) across 5 OOS periods
# ==================================================================
print("\n" + "=" * 80)
print("[4/6] Running 3-Asset (SPY/GLD/TLT) across 5 OOS periods...")
print("=" * 80)

ASSETS_3 = ["SPY", "GLD", "TLT"]
strategies_3 = ["buy_hold", "uniform_vix", "two_tier", "hybrid"]

results_3asset = []

for pi, (start, end) in enumerate(OOS_PERIODS):
    period_data = merged.loc[start:end].copy()
    if len(period_data) < 50:
        print(f"  WARNING: Period {pi+1} ({start} to {end}) has only {len(period_data)} days, skipping")
        continue

    print(f"  Period {pi+1}: {start} to {end} ({len(period_data)} days)")

    for strat in strategies_3:
        result = run_strategy(period_data, ASSETS_3, strat, own_vol_dict,
                             period_label=f"P{pi+1}")
        results_3asset.append(result)
        print(f"    {strat:15s}: Sharpe={result['sharpe']:.3f}  MDD={result['mdd']:.1f}%  "
              f"Calmar={result['calmar']:.3f}  Turnover={result['annual_turnover']:.0f}")

# Summary table for 3-asset
print("\n" + "=" * 80)
print("3-ASSET (1/3 SPY/GLD/TLT) CROSS-OOS SUMMARY")
print("=" * 80)

for strat in strategies_3:
    strat_results = [r for r in results_3asset if r["strategy"] == strat]
    sharpes = [r["sharpe"] for r in strat_results]
    mdds = [r["mdd"] for r in strat_results]
    calmars = [r["calmar"] for r in strat_results]

    mean_sharpe = np.mean(sharpes)
    std_sharpe = np.std(sharpes, ddof=1)
    t_stat = mean_sharpe / (std_sharpe / np.sqrt(len(sharpes))) if std_sharpe > 0 else 0
    mean_mdd = np.mean(mdds)
    mean_calmar = np.mean(calmars)

    if strat != "buy_hold":
        bh_sharpes = [r["sharpe"] for r in results_3asset if r["strategy"] == "buy_hold"]
        wins = sum(1 for s, bh in zip(sharpes, bh_sharpes) if s > bh)
        win_str = f"  Wins vs BH: {wins}/{len(sharpes)}"
    else:
        win_str = ""

    print(f"  {strat:15s}: Mean Sharpe={mean_sharpe:.3f} (t={t_stat:.2f})  "
          f"Mean MDD={mean_mdd:.1f}%  Mean Calmar={mean_calmar:.3f}{win_str}")


# ==================================================================
# 5. Pairwise Comparisons (Two-Tier vs Uniform VIX)
# ==================================================================
print("\n" + "=" * 80)
print("[5/6] Pairwise Statistical Tests")
print("=" * 80)

def paired_t_test(results_list, strat_a, strat_b, metric="sharpe"):
    """Paired t-test across OOS periods."""
    vals_a = [r[metric] for r in results_list if r["strategy"] == strat_a]
    vals_b = [r[metric] for r in results_list if r["strategy"] == strat_b]
    diff = np.array(vals_a) - np.array(vals_b)
    if np.std(diff, ddof=1) == 0:
        return 0, 1.0
    t_stat, p_val = stats.ttest_rel(vals_a, vals_b)
    return t_stat, p_val

comparisons = [
    ("two_tier", "uniform_vix", "Two-Tier vs Uniform VIX"),
    ("hybrid", "uniform_vix", "Hybrid vs Uniform VIX"),
    ("two_tier", "buy_hold", "Two-Tier vs Buy&Hold"),
    ("uniform_vix", "buy_hold", "Uniform VIX vs Buy&Hold"),
    ("hybrid", "buy_hold", "Hybrid vs Buy&Hold"),
]

print("\n--- 2-Asset (SPY/GLD) Sharpe Comparisons ---")
for strat_a, strat_b, label in comparisons:
    t_stat, p_val = paired_t_test(results_2asset, strat_a, strat_b, "sharpe")
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else "n.s."
    print(f"  {label:35s}: t={t_stat:.3f}, p={p_val:.4f} {sig}")

print("\n--- 2-Asset (SPY/GLD) MDD Comparisons ---")
for strat_a, strat_b, label in comparisons:
    t_stat, p_val = paired_t_test(results_2asset, strat_a, strat_b, "mdd")
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else "n.s."
    # Note: MDD is negative, so positive t means strat_a has less severe MDD
    print(f"  {label:35s}: t={t_stat:.3f}, p={p_val:.4f} {sig}")

print("\n--- 3-Asset (SPY/GLD/TLT) Sharpe Comparisons ---")
for strat_a, strat_b, label in comparisons:
    t_stat, p_val = paired_t_test(results_3asset, strat_a, strat_b, "sharpe")
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else "n.s."
    print(f"  {label:35s}: t={t_stat:.3f}, p={p_val:.4f} {sig}")

print("\n--- 3-Asset (SPY/GLD/TLT) MDD Comparisons ---")
for strat_a, strat_b, label in comparisons:
    t_stat, p_val = paired_t_test(results_3asset, strat_a, strat_b, "mdd")
    sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else "n.s."
    print(f"  {label:35s}: t={t_stat:.3f}, p={p_val:.4f} {sig}")


# ==================================================================
# 6. Full-Period Analysis + Diagnostics
# ==================================================================
print("\n" + "=" * 80)
print("[6/6] Full-Period Analysis (2015-2024)")
print("=" * 80)

full_data = merged.loc["2015-01-01":"2024-12-31"].copy()
print(f"  Full period: {full_data.index[0].date()} to {full_data.index[-1].date()} ({len(full_data)} days)")

# 2-Asset full period
print("\n--- 2-Asset (50/50 SPY/GLD) Full Period ---")
full_results_2 = {}
for strat in strategies_2:
    result = run_strategy(full_data, ASSETS_2, strat, own_vol_dict, period_label="full")
    full_results_2[strat] = result
    print(f"  {strat:15s}: Sharpe={result['sharpe']:.3f}  MDD={result['mdd']:.1f}%  "
          f"Calmar={result['calmar']:.3f}  Sortino={result['sortino']:.3f}  "
          f"Ann.Ret={result['annual_return']:.1f}%  Ann.Vol={result['annual_vol']:.1f}%  "
          f"Turnover={result['annual_turnover']:.0f}  AvgLev={result['avg_leverage']:.2f}")

# 3-Asset full period
print("\n--- 3-Asset (1/3 SPY/GLD/TLT) Full Period ---")
full_results_3 = {}
for strat in strategies_3:
    result = run_strategy(full_data, ASSETS_3, strat, own_vol_dict, period_label="full")
    full_results_3[strat] = result
    print(f"  {strat:15s}: Sharpe={result['sharpe']:.3f}  MDD={result['mdd']:.1f}%  "
          f"Calmar={result['calmar']:.3f}  Sortino={result['sortino']:.3f}  "
          f"Ann.Ret={result['annual_return']:.1f}%  Ann.Vol={result['annual_vol']:.1f}%  "
          f"Turnover={result['annual_turnover']:.0f}  AvgLev={result['avg_leverage']:.2f}")

# DM-style test on daily returns (Two-Tier vs Uniform VIX)
print("\n--- Diebold-Mariano Style: Two-Tier vs Uniform VIX (Full Period, Daily) ---")
for label, full_results in [("2-Asset", full_results_2), ("3-Asset", full_results_3)]:
    ret_tt = full_results["two_tier"]["daily_returns"]
    ret_uv = full_results["uniform_vix"]["daily_returns"]
    diff = ret_tt - ret_uv
    n = len(diff)
    t_dm = diff.mean() / (diff.std() / np.sqrt(n)) if diff.std() > 0 else 0
    p_dm = 2 * (1 - stats.norm.cdf(abs(t_dm)))
    print(f"  {label}: DM t={t_dm:.3f}, p={p_dm:.4f}, "
          f"mean diff={diff.mean()*252*100:.2f}%/yr")

# Correlation diagnostics
print("\n--- Vol Estimator Diagnostics ---")
for asset in ["SPY", "GLD", "TLT"]:
    vix_d = full_data["VIX_daily"]
    own_v = full_data[f"{asset}_own_vol"]
    corr = vix_d.corr(own_v)
    ratio = (vix_d / own_v).mean()
    print(f"  {asset}: corr(VIX_daily, own_22d_vol) = {corr:.3f}, "
          f"mean ratio(VIX/own) = {ratio:.3f}")


# ==================================================================
# 7. Period-by-Period Detailed Breakdown
# ==================================================================
print("\n" + "=" * 80)
print("PERIOD-BY-PERIOD BREAKDOWN (2-Asset SPY/GLD)")
print("=" * 80)
print(f"{'Period':>8s} | {'Strategy':>15s} | {'Sharpe':>7s} | {'MDD%':>7s} | {'Calmar':>7s} | {'Sortino':>8s} | {'AvgLev':>7s}")
print("-" * 80)
for pi in range(5):
    period_label = f"P{pi+1}"
    for strat in strategies_2:
        r = [x for x in results_2asset if x["period"] == period_label and x["strategy"] == strat][0]
        print(f"{period_label:>8s} | {strat:>15s} | {r['sharpe']:>7.3f} | {r['mdd']:>7.1f} | {r['calmar']:>7.3f} | {r['sortino']:>8.3f} | {r['avg_leverage']:>7.3f}")
    print("-" * 80)

# Same for 3-asset
print(f"\nPERIOD-BY-PERIOD BREAKDOWN (3-Asset SPY/GLD/TLT)")
print("=" * 80)
print(f"{'Period':>8s} | {'Strategy':>15s} | {'Sharpe':>7s} | {'MDD%':>7s} | {'Calmar':>7s} | {'Sortino':>8s} | {'AvgLev':>7s}")
print("-" * 80)
for pi in range(5):
    period_label = f"P{pi+1}"
    for strat in strategies_3:
        r = [x for x in results_3asset if x["period"] == period_label and x["strategy"] == strat][0]
        print(f"{period_label:>8s} | {strat:>15s} | {r['sharpe']:>7.3f} | {r['mdd']:>7.1f} | {r['calmar']:>7.3f} | {r['sortino']:>8.3f} | {r['avg_leverage']:>7.3f}")
    print("-" * 80)


# ==================================================================
# 8. Final Verdict
# ==================================================================
print("\n" + "=" * 80)
print("K209 FINAL VERDICT")
print("=" * 80)

# Aggregate wins across all OOS periods
for label, results in [("2-Asset", results_2asset), ("3-Asset", results_3asset)]:
    print(f"\n--- {label} ---")
    for strat in ["uniform_vix", "two_tier", "hybrid"]:
        sharpes = [r["sharpe"] for r in results if r["strategy"] == strat]
        bh_sharpes = [r["sharpe"] for r in results if r["strategy"] == "buy_hold"]

        sharpe_wins = sum(1 for s, bh in zip(sharpes, bh_sharpes) if s > bh)
        mean_sharpe = np.mean(sharpes)

        mdds = [r["mdd"] for r in results if r["strategy"] == strat]
        bh_mdds = [r["mdd"] for r in results if r["strategy"] == "buy_hold"]
        mdd_wins = sum(1 for m, bh in zip(mdds, bh_mdds) if m > bh)  # less negative = better

        # Sharpe t-stat (Harvey threshold = 3.0)
        std_s = np.std(sharpes, ddof=1)
        t_sharpe = mean_sharpe / (std_s / np.sqrt(len(sharpes))) if std_s > 0 else 0
        harvey = "PASS Harvey" if abs(t_sharpe) > 3.0 else "FAIL Harvey"

        print(f"  {strat:15s}: Mean Sharpe={mean_sharpe:.3f} (t={t_sharpe:.2f}, {harvey})  "
              f"Sharpe wins vs BH: {sharpe_wins}/5  MDD wins vs BH: {mdd_wins}/5")

    # Two-tier vs uniform comparison
    tt_sharpes = [r["sharpe"] for r in results if r["strategy"] == "two_tier"]
    uv_sharpes = [r["sharpe"] for r in results if r["strategy"] == "uniform_vix"]
    tt_wins = sum(1 for a, b in zip(tt_sharpes, uv_sharpes) if a > b)
    diff = np.array(tt_sharpes) - np.array(uv_sharpes)
    mean_diff = np.mean(diff)
    print(f"\n  Two-Tier vs Uniform VIX: {tt_wins}/5 periods, mean Sharpe diff = {mean_diff:.4f}")
    if np.std(diff, ddof=1) > 0:
        t_diff = mean_diff / (np.std(diff, ddof=1) / np.sqrt(len(diff)))
        p_diff = 2 * (1 - stats.t.cdf(abs(t_diff), df=len(diff)-1))
        print(f"  Paired t-test: t={t_diff:.3f}, p={p_diff:.4f}")


# ==================================================================
# 9. Save Results
# ==================================================================
print("\n[Saving results...]")

# Prepare serializable results
def serialize_results(results_list):
    return [{k: v for k, v in r.items() if k != "daily_returns"} for r in results_list]

output = {
    "experiment": "K209",
    "title": "Two-Tier VT Backtest — VIX for Equities, OwnVol for Others",
    "date": datetime.now().isoformat(),
    "config": {
        "target_vol_annual": TARGET_VOL_ANNUAL,
        "max_leverage": MAX_LEVERAGE,
        "tx_cost_bps": TX_COST * 10000,
        "own_vol_window": OWN_VOL_WINDOW,
        "oos_periods": OOS_PERIODS,
        "rf_annual": RF_ANNUAL,
    },
    "results_2asset": serialize_results(results_2asset),
    "results_3asset": serialize_results(results_3asset),
    "full_period_2asset": {k: {kk: vv for kk, vv in v.items() if kk != "daily_returns"}
                           for k, v in full_results_2.items()},
    "full_period_3asset": {k: {kk: vv for kk, vv in v.items() if kk != "daily_returns"}
                           for k, v in full_results_3.items()},
}

with open("experiments/k209_two_tier_vt_results.json", "w") as f:
    json.dump(output, f, indent=2)
print("  Saved to experiments/k209_two_tier_vt_results.json")

print("\n" + "=" * 80)
print("K209 COMPLETE")
print("=" * 80)
