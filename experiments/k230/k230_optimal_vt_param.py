"""
K230: Optimal VT Parameter Search — Is 12/VIX Really the Best?
=============================================================
[提出: 用戶, 執行: Claude]

Background: We've used 12/VIX as the VT rule throughout. But is 12 optimal?
What about 10/VIX or 15/VIX? And should the denominator really be VIX,
or VIX^0.5 or log(VIX)?

Data: SPY, GLD daily from yfinance. 5-period cross-OOS 2015-2024.

Methodology:
1. Grid search over K in K/VIX: K = 6, 8, 10, 12, 14, 16, 18, 20
2. Alternative functional forms:
   - Linear: K/VIX (current)
   - Square root: K/sqrt(VIX)
   - Log: K/log(VIX)
   - Threshold: 1 if VIX<K else 0.5 (binary)
   - Sigmoid: 1/(1+exp((VIX-K)/5))
3. For 50/50 SPY/GLD portfolio with monthly rebalance
4. Metrics: Sharpe, MDD, Calmar, net Sharpe (after 5bps TX)
5. 5-period cross-OOS (MANDATORY)
6. Key question: is there a K that significantly beats 12?

Statistical requirements: DM test between K=12 and best alternative.
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

# ============================================================
# CONFIG
# ============================================================
ASSETS = ["SPY", "GLD"]
ASSET_WEIGHTS = {"SPY": 0.5, "GLD": 0.5}
TX_COST_BPS = 5  # 5 bps per rebalance
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

# K values for grid search
K_VALUES = [6, 8, 10, 12, 14, 16, 18, 20]

# Functional forms
FORMS = ["linear", "sqrt", "log", "threshold", "sigmoid"]

# 5-period cross-OOS design (2015-2024)
OOS_PERIODS = [
    ("2015-01-01", "2016-12-31"),   # Period 1: low vol + China shock
    ("2017-01-01", "2018-12-31"),   # Period 2: low vol + vol explosion
    ("2019-01-01", "2020-12-31"),   # Period 3: COVID crash
    ("2021-01-01", "2022-12-31"),   # Period 4: recovery + rate hikes
    ("2023-01-01", "2024-12-31"),   # Period 5: AI rally + geopolitics
]

DATA_START = "2010-01-01"  # enough lookback for monthly rebalance setup

print("=" * 80)
print("K230: OPTIMAL VT PARAMETER SEARCH")
print("Is 12/VIX Really the Best?")
print("=" * 80)


# ============================================================
# 1. Download Data
# ============================================================
print("\n[1/6] Downloading SPY, GLD, ^VIX data from yfinance...")

tickers = ["SPY", "GLD", "^VIX"]
raw = {}
for t in tickers:
    df = yf.download(t, start=DATA_START, end="2025-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[t] = df["Close"].dropna()
    print(f"  {t}: {len(raw[t])} days ({raw[t].index[0].strftime('%Y-%m-%d')} to {raw[t].index[-1].strftime('%Y-%m-%d')})")

spy_close = raw["SPY"]
gld_close = raw["GLD"]
vix_close = raw["^VIX"]

# Compute returns
spy_ret = spy_close.pct_change().dropna()
gld_ret = gld_close.pct_change().dropna()

# Align all series
common_idx = spy_ret.index.intersection(gld_ret.index).intersection(vix_close.index)
spy_ret = spy_ret.loc[common_idx]
gld_ret = gld_ret.loc[common_idx]
vix_aligned = vix_close.loc[common_idx]

print(f"  Common dates: {len(common_idx)} ({common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')})")


# ============================================================
# 2. VT Weight Functions
# ============================================================
def vt_weight_linear(vix, K):
    """Standard: w = K / VIX, capped [0, 1]"""
    return np.clip(K / vix, 0.0, 1.0)

def vt_weight_sqrt(vix, K):
    """Square root: w = K / sqrt(VIX), capped [0, 1]"""
    return np.clip(K / np.sqrt(vix), 0.0, 1.0)

def vt_weight_log(vix, K):
    """Log: w = K / log(VIX), capped [0, 1]"""
    return np.clip(K / np.log(vix), 0.0, 1.0)

def vt_weight_threshold(vix, K):
    """Binary threshold: 1.0 if VIX < K else 0.5"""
    return np.where(vix < K, 1.0, 0.5)

def vt_weight_sigmoid(vix, K):
    """Sigmoid: 1 / (1 + exp((VIX - K) / 5))"""
    return 1.0 / (1.0 + np.exp((vix - K) / 5.0))

WEIGHT_FUNCS = {
    "linear": vt_weight_linear,
    "sqrt": vt_weight_sqrt,
    "log": vt_weight_log,
    "threshold": vt_weight_threshold,
    "sigmoid": vt_weight_sigmoid,
}


# ============================================================
# 3. Portfolio Backtest Engine
# ============================================================
def run_vt_portfolio(spy_ret_series, gld_ret_series, vix_series,
                     K, form="linear", monthly_rebal=True):
    """
    Run 50/50 SPY/GLD portfolio with VT weighting.

    VT weight is applied identically to both assets:
      portfolio_ret_t = w_{t-1} * (0.5 * spy_ret_t + 0.5 * gld_ret_t)
                        + (1 - w_{t-1}) * rf_daily

    Lagged: VIX on day t-1 determines weight for day t.
    Monthly rebalance: weight changes only on first trading day of each month.

    Returns daily portfolio returns series.
    """
    weight_func = WEIGHT_FUNCS[form]

    # Compute raw weight from VIX
    vix_vals = vix_series.values
    raw_w = weight_func(vix_vals, K)
    raw_w_series = pd.Series(raw_w, index=vix_series.index)

    # Lag by 1 day
    lagged_w = raw_w_series.shift(1)

    # Monthly rebalance: hold weight constant within month
    if monthly_rebal:
        monthly_w = lagged_w.copy()
        months = monthly_w.index.to_period("M")
        for m in months.unique():
            mask = months == m
            idx = monthly_w.index[mask]
            if len(idx) > 0:
                first_valid = monthly_w.loc[idx].first_valid_index()
                if first_valid is not None:
                    monthly_w.loc[idx] = monthly_w.loc[first_valid]
        lagged_w = monthly_w

    lagged_w = lagged_w.dropna()
    common = lagged_w.index.intersection(spy_ret_series.index).intersection(gld_ret_series.index)

    w = lagged_w.loc[common]
    sr = spy_ret_series.loc[common]
    gr = gld_ret_series.loc[common]

    # Portfolio return: weighted exposure to 50/50 + cash remainder
    asset_ret = 0.5 * sr + 0.5 * gr
    port_ret = w * asset_ret + (1 - w) * RF_DAILY

    return port_ret, w


def compute_metrics(returns, weights=None, label=""):
    """Compute Sharpe, MDD, Calmar, Net Sharpe."""
    ret_arr = returns.values if isinstance(returns, pd.Series) else np.array(returns)

    n_days = len(ret_arr)
    if n_days < 20:
        return None

    # Annualized return and vol
    ann_ret = np.mean(ret_arr) * 252
    ann_vol = np.std(ret_arr, ddof=1) * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0.0

    # Max drawdown
    cum = (1 + pd.Series(ret_arr)).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0.0

    # Net Sharpe (after TX cost for monthly rebalance)
    if weights is not None:
        w_arr = weights.values if isinstance(weights, pd.Series) else np.array(weights)
        # Count rebalances: weight changes > 1%
        n_rebal = np.sum(np.abs(np.diff(w_arr)) > 0.01)
        years = n_days / 252
        annual_tx = (n_rebal * TX_COST_BPS / 10000) / years if years > 0 else 0
        net_ret = ann_ret - annual_tx
        net_sharpe = (net_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0.0
    else:
        net_sharpe = sharpe
        annual_tx = 0.0

    # Sortino
    downside = ret_arr[ret_arr < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 1 else ann_vol
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 0 else 0.0

    return {
        "label": label,
        "ann_ret": round(ann_ret * 100, 2),
        "ann_vol": round(ann_vol * 100, 2),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "net_sharpe": round(net_sharpe, 3),
        "annual_tx_pct": round(annual_tx * 100, 3),
        "n_days": n_days,
    }


# ============================================================
# 4. Diebold-Mariano Test
# ============================================================
def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    H0: loss1 = loss2. H1: loss1 != loss2 (two-sided).
    loss = -return (so lower loss = higher return).
    Returns t-stat and p-value (two-sided).
    """
    d = loss1 - loss2  # differential loss
    n = len(d)
    if n < 10:
        return 0.0, 1.0

    d_mean = np.mean(d)
    # Newey-West style variance estimate
    gamma0 = np.var(d, ddof=1)
    nw_sum = 0
    max_lag = min(h, n - 1)
    for k in range(1, max_lag + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_sum += 2 * (1 - k / (max_lag + 1)) * gamma_k
    var_d = (gamma0 + nw_sum) / n
    var_d = max(var_d, 1e-20)

    t_stat = d_mean / np.sqrt(var_d)
    p_value = stats.t.sf(abs(t_stat), df=n - 1) * 2  # two-sided

    return t_stat, p_value


# ============================================================
# 5. Run Grid Search with 5-Period Cross-OOS
# ============================================================
print("\n[2/6] Running grid search: K-values x functional forms x 5 OOS periods...")

all_results = {}
period_returns = {}  # Store daily returns for DM test

total_configs = len(K_VALUES) * len(FORMS)
config_count = 0

for form in FORMS:
    for K in K_VALUES:
        config_count += 1
        config_key = f"{form}_K{K}"
        period_metrics = []
        period_daily_returns = []

        for p_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
            # Filter to OOS period
            mask = (spy_ret.index >= oos_start) & (spy_ret.index <= oos_end)
            spy_oos = spy_ret[mask]
            gld_oos = gld_ret[mask]
            vix_oos = vix_aligned[mask]

            if len(spy_oos) < 50:
                continue

            port_ret, weights = run_vt_portfolio(spy_oos, gld_oos, vix_oos,
                                                  K=K, form=form, monthly_rebal=True)

            m = compute_metrics(port_ret, weights,
                                label=f"{config_key}_P{p_idx+1}")

            if m is not None:
                m["period"] = p_idx + 1
                m["oos_start"] = oos_start
                m["oos_end"] = oos_end
                period_metrics.append(m)
                period_daily_returns.append(port_ret)

        if len(period_metrics) > 0:
            all_results[config_key] = period_metrics
            period_returns[config_key] = period_daily_returns

        if config_count % 10 == 0:
            print(f"  Progress: {config_count}/{total_configs} configs done")

print(f"  Total: {len(all_results)} valid configurations")


# ============================================================
# 6. Aggregate Cross-OOS Results
# ============================================================
print("\n[3/6] Aggregating cross-OOS results...")

summary = []
for config_key, period_metrics in all_results.items():
    sharpes = [m["sharpe"] for m in period_metrics]
    mdds = [m["mdd"] for m in period_metrics]
    calmars = [m["calmar"] for m in period_metrics]
    net_sharpes = [m["net_sharpe"] for m in period_metrics]
    sortinos = [m["sortino"] for m in period_metrics]

    parts = config_key.split("_K")
    form = parts[0]
    K = int(parts[1])

    summary.append({
        "config": config_key,
        "form": form,
        "K": K,
        "mean_sharpe": round(np.mean(sharpes), 4),
        "std_sharpe": round(np.std(sharpes, ddof=1), 4),
        "median_sharpe": round(np.median(sharpes), 4),
        "mean_mdd": round(np.mean(mdds), 2),
        "worst_mdd": round(np.min(mdds), 2),
        "mean_calmar": round(np.mean(calmars), 3),
        "mean_sortino": round(np.mean(sortinos), 3),
        "mean_net_sharpe": round(np.mean(net_sharpes), 4),
        "std_net_sharpe": round(np.std(net_sharpes, ddof=1), 4),
        "n_periods": len(period_metrics),
        "sharpes_by_period": [round(s, 3) for s in sharpes],
        "mdds_by_period": [round(m, 2) for m in mdds],
    })

summary_df = pd.DataFrame(summary)
summary_df = summary_df.sort_values("mean_sharpe", ascending=False)


# ============================================================
# 7. PART A: K-Value Grid Search (Linear Form Only)
# ============================================================
print("\n[4/6] === PART A: K-Value Grid Search (Linear K/VIX) ===")
print("-" * 80)

linear_df = summary_df[summary_df["form"] == "linear"].sort_values("K")
print(f"\n{'K':>3} | {'Mean Sharpe':>11} | {'Std Sharpe':>10} | {'Mean MDD%':>9} | "
      f"{'Worst MDD%':>10} | {'Mean Calmar':>11} | {'Net Sharpe':>10} | "
      f"{'Periods':>7}")
print("-" * 95)

for _, row in linear_df.iterrows():
    print(f"{row['K']:>3} | {row['mean_sharpe']:>11.4f} | {row['std_sharpe']:>10.4f} | "
          f"{row['mean_mdd']:>9.2f} | {row['worst_mdd']:>10.2f} | "
          f"{row['mean_calmar']:>11.3f} | {row['mean_net_sharpe']:>10.4f} | "
          f"{row['n_periods']:>7}")

# Find best K
best_k_row = linear_df.loc[linear_df["mean_sharpe"].idxmax()]
print(f"\n>>> Best K (by mean Sharpe): K={int(best_k_row['K'])} "
      f"(Sharpe={best_k_row['mean_sharpe']:.4f})")

# K=12 baseline
k12_row = linear_df[linear_df["K"] == 12].iloc[0]
print(f">>> K=12 baseline: Sharpe={k12_row['mean_sharpe']:.4f}, "
      f"MDD={k12_row['mean_mdd']:.2f}%, Net Sharpe={k12_row['mean_net_sharpe']:.4f}")

# Period-by-period breakdown for linear
print("\nPeriod-by-Period Sharpe Ratios (Linear K/VIX):")
print(f"{'K':>3} | {'P1 (15-16)':>10} | {'P2 (17-18)':>10} | {'P3 (19-20)':>10} | "
      f"{'P4 (21-22)':>10} | {'P5 (23-24)':>10}")
print("-" * 70)
for _, row in linear_df.iterrows():
    sharpes = row["sharpes_by_period"]
    vals = " | ".join(f"{s:>10.3f}" for s in sharpes)
    print(f"{row['K']:>3} | {vals}")


# ============================================================
# 8. PART B: Functional Form Comparison (at K=12)
# ============================================================
print("\n\n[5/6] === PART B: Functional Form Comparison (at K=12) ===")
print("-" * 80)

k12_all = summary_df[summary_df["K"] == 12].sort_values("mean_sharpe", ascending=False)
print(f"\n{'Form':>12} | {'Mean Sharpe':>11} | {'Std Sharpe':>10} | {'Mean MDD%':>9} | "
      f"{'Worst MDD%':>10} | {'Mean Calmar':>11} | {'Net Sharpe':>10}")
print("-" * 90)

for _, row in k12_all.iterrows():
    print(f"{row['form']:>12} | {row['mean_sharpe']:>11.4f} | {row['std_sharpe']:>10.4f} | "
          f"{row['mean_mdd']:>9.2f} | {row['worst_mdd']:>10.2f} | "
          f"{row['mean_calmar']:>11.3f} | {row['mean_net_sharpe']:>10.4f}")

# Best form at each K
print("\nBest Functional Form at Each K (by mean Sharpe):")
print(f"{'K':>3} | {'Best Form':>12} | {'Mean Sharpe':>11} | {'vs Linear':>10}")
print("-" * 50)
for K in K_VALUES:
    k_df = summary_df[summary_df["K"] == K].sort_values("mean_sharpe", ascending=False)
    best = k_df.iloc[0]
    linear_at_k = k_df[k_df["form"] == "linear"]
    if len(linear_at_k) > 0:
        diff = best["mean_sharpe"] - linear_at_k.iloc[0]["mean_sharpe"]
        print(f"{K:>3} | {best['form']:>12} | {best['mean_sharpe']:>11.4f} | {diff:>+10.4f}")


# ============================================================
# 9. Overall Best Configuration
# ============================================================
print("\n\n=== TOP 10 CONFIGURATIONS (ALL FORMS x ALL K) ===")
print("-" * 110)
print(f"{'Rank':>4} | {'Config':>15} | {'Mean Sharpe':>11} | {'Std Sharpe':>10} | "
      f"{'Mean MDD%':>9} | {'Calmar':>7} | {'Net Sharpe':>10} | {'Sharpes by Period':>35}")
print("-" * 110)

top10 = summary_df.head(10)
for rank, (_, row) in enumerate(top10.iterrows(), 1):
    sharpes_str = ", ".join(f"{s:.2f}" for s in row["sharpes_by_period"])
    print(f"{rank:>4} | {row['config']:>15} | {row['mean_sharpe']:>11.4f} | "
          f"{row['std_sharpe']:>10.4f} | {row['mean_mdd']:>9.2f} | "
          f"{row['mean_calmar']:>7.3f} | {row['mean_net_sharpe']:>10.4f} | "
          f"[{sharpes_str}]")


# ============================================================
# 10. Statistical Tests: DM test K=12 vs Alternatives
# ============================================================
print("\n\n[6/6] === STATISTICAL TESTS ===")
print("-" * 80)

# DM test: K=12 linear vs best overall
baseline_key = "linear_K12"
best_overall = summary_df.iloc[0]
best_key = best_overall["config"]

print(f"\nBaseline: {baseline_key}")
print(f"Challenger: {best_key} (best overall by mean Sharpe)")

# Run DM test for each OOS period and aggregate
dm_results = []
pooled_t = 0.0
pooled_p = 1.0

if baseline_key in period_returns and best_key in period_returns:
    for p_idx in range(min(len(period_returns[baseline_key]),
                           len(period_returns[best_key]))):
        baseline_ret = period_returns[baseline_key][p_idx]
        challenger_ret = period_returns[best_key][p_idx]

        # Align dates
        common = baseline_ret.index.intersection(challenger_ret.index)
        if len(common) < 50:
            continue

        b_ret = baseline_ret.loc[common].values
        c_ret = challenger_ret.loc[common].values

        # Loss = negative return (DM test: lower loss = better)
        loss_b = -b_ret
        loss_c = -c_ret

        t_stat, p_val = dm_test(loss_b, loss_c, h=5)
        dm_results.append({
            "period": p_idx + 1,
            "t_stat": round(t_stat, 3),
            "p_value": round(p_val, 4),
            "baseline_mean_ret": round(np.mean(b_ret) * 252 * 100, 2),
            "challenger_mean_ret": round(np.mean(c_ret) * 252 * 100, 2),
            "diff_bps": round((np.mean(c_ret) - np.mean(b_ret)) * 252 * 10000, 1),
        })

    print(f"\nDiebold-Mariano Test: {baseline_key} vs {best_key}")
    print(f"{'Period':>7} | {'DM t-stat':>10} | {'p-value':>8} | "
          f"{'Base Ret%':>10} | {'Chall Ret%':>11} | {'Diff (bps)':>11}")
    print("-" * 70)
    for r in dm_results:
        sig = "**" if r["p_value"] < 0.05 else "  "
        print(f"  P{r['period']:>4} | {r['t_stat']:>10.3f} | {r['p_value']:>8.4f}{sig} | "
              f"{r['baseline_mean_ret']:>10.2f} | {r['challenger_mean_ret']:>11.2f} | "
              f"{r['diff_bps']:>11.1f}")

    # Pooled DM test (concatenate all OOS periods)
    all_b = np.concatenate([r.values for r in period_returns[baseline_key]])
    all_c = np.concatenate([r.values for r in period_returns[best_key]])
    min_len = min(len(all_b), len(all_c))
    all_b = all_b[:min_len]
    all_c = all_c[:min_len]

    pooled_t, pooled_p = dm_test(-all_b, -all_c, h=5)
    print(f"\n  Pooled DM test (all periods): t={pooled_t:.3f}, p={pooled_p:.4f}")
    print(f"  Harvey (2016) threshold: |t| > 3.0 for new factor/strategy claims")
    print(f"  {'SIGNIFICANT' if abs(pooled_t) > 1.96 else 'NOT SIGNIFICANT'} at 5% level")
    print(f"  {'PASSES Harvey threshold' if abs(pooled_t) > 3.0 else 'FAILS Harvey threshold'}")

# Also test: K=12 linear vs K=12 each alternative form
print(f"\n\nDM Test: linear_K12 vs other forms at K=12")
print(f"{'Form':>12} | {'Pooled t':>9} | {'Pooled p':>9} | {'Significant?':>12}")
print("-" * 55)
for form in FORMS:
    if form == "linear":
        continue
    alt_key = f"{form}_K12"
    if alt_key not in period_returns or baseline_key not in period_returns:
        continue

    all_b = np.concatenate([r.values for r in period_returns[baseline_key]])
    all_c = np.concatenate([r.values for r in period_returns[alt_key]])
    min_len = min(len(all_b), len(all_c))
    all_b = all_b[:min_len]
    all_c = all_c[:min_len]

    t, p = dm_test(-all_b, -all_c, h=5)
    sig_str = "YES**" if p < 0.05 else "no"
    print(f"{form:>12} | {t:>9.3f} | {p:>9.4f} | {sig_str:>12}")

# Cross-K DM tests within linear form
print(f"\n\nDM Test: linear_K12 vs other K values (linear form)")
print(f"{'K':>3} | {'Pooled t':>9} | {'Pooled p':>9} | {'Mean Sharpe diff':>16} | {'Significant?':>12}")
print("-" * 65)
for K in K_VALUES:
    if K == 12:
        continue
    alt_key = f"linear_K{K}"
    if alt_key not in period_returns:
        continue

    all_b = np.concatenate([r.values for r in period_returns[baseline_key]])
    all_c = np.concatenate([r.values for r in period_returns[alt_key]])
    min_len = min(len(all_b), len(all_c))
    all_b = all_b[:min_len]
    all_c = all_c[:min_len]

    t, p = dm_test(-all_b, -all_c, h=5)

    # Get Sharpe diff
    s12 = summary_df[summary_df["config"] == baseline_key]["mean_sharpe"].values[0]
    sK = summary_df[summary_df["config"] == alt_key]["mean_sharpe"].values[0]
    diff = sK - s12

    sig_str = "YES**" if p < 0.05 else "no"
    print(f"{K:>3} | {t:>9.3f} | {p:>9.4f} | {diff:>+16.4f} | {sig_str:>12}")


# ============================================================
# 11. Buy-and-Hold Benchmark
# ============================================================
print("\n\n=== BENCHMARK: 50/50 BUY & HOLD ===")
bh_sharpes = []
for p_idx, (oos_start, oos_end) in enumerate(OOS_PERIODS):
    mask = (spy_ret.index >= oos_start) & (spy_ret.index <= oos_end)
    bh_ret = 0.5 * spy_ret[mask] + 0.5 * gld_ret[mask]
    m = compute_metrics(bh_ret, label=f"BH_P{p_idx+1}")
    if m:
        bh_sharpes.append(m['sharpe'])
        print(f"  P{p_idx+1} ({oos_start[:4]}-{oos_end[:4]}): "
              f"Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:.2f}%, Calmar={m['calmar']:.3f}")
print(f"  Mean BH Sharpe: {np.mean(bh_sharpes):.4f}")


# ============================================================
# 12. Weight Distribution Analysis
# ============================================================
print("\n\n=== WEIGHT DISTRIBUTION (Full Sample 2015-2024) ===")
full_mask = (spy_ret.index >= "2015-01-01") & (spy_ret.index <= "2024-12-31")
spy_full = spy_ret[full_mask]
gld_full = gld_ret[full_mask]
vix_full = vix_aligned[full_mask]

print(f"\n{'Config':>15} | {'Mean W':>7} | {'Std W':>7} | {'Min W':>7} | {'Max W':>7} | "
      f"{'% Full':>7} | {'% < 0.5':>7}")
print("-" * 80)

for form in FORMS:
    for K in [8, 12, 16, 20]:
        _, weights = run_vt_portfolio(spy_full, gld_full, vix_full,
                                       K=K, form=form, monthly_rebal=True)
        w_arr = weights.values
        pct_full = np.mean(w_arr >= 0.99) * 100
        pct_low = np.mean(w_arr < 0.5) * 100
        label = f"{form}_K{K}"
        print(f"{label:>15} | {np.mean(w_arr):>7.3f} | {np.std(w_arr):>7.3f} | "
              f"{np.min(w_arr):>7.3f} | {np.max(w_arr):>7.3f} | "
              f"{pct_full:>6.1f}% | {pct_low:>6.1f}%")


# ============================================================
# 13. Robustness: Monotonicity Check
# ============================================================
print("\n\n=== MONOTONICITY CHECK (Linear Form) ===")
print("Does increasing K monotonically improve Sharpe? If so, K=12 is arbitrary.")

linear_sharpes = linear_df.set_index("K")["mean_sharpe"]
monotone_up = all(linear_sharpes.iloc[i] <= linear_sharpes.iloc[i+1]
                  for i in range(len(linear_sharpes)-1))
monotone_down = all(linear_sharpes.iloc[i] >= linear_sharpes.iloc[i+1]
                    for i in range(len(linear_sharpes)-1))

if monotone_up:
    print("  Result: MONOTONICALLY INCREASING — higher K always better (corner solution)")
elif monotone_down:
    print("  Result: MONOTONICALLY DECREASING — lower K always better (corner solution)")
else:
    # Find local maxima
    sharpe_vals = linear_sharpes.values
    k_vals = linear_sharpes.index.values
    print("  Result: NON-MONOTONE — interior optimum exists")
    peak_idx = np.argmax(sharpe_vals)
    print(f"  Peak at K={k_vals[peak_idx]}, Sharpe={sharpe_vals[peak_idx]:.4f}")
    print(f"  Shape: {' -> '.join(f'K{k}:{s:.3f}' for k, s in zip(k_vals, sharpe_vals))}")


# ============================================================
# 14. Robustness: Period Win Count
# ============================================================
print("\n\n=== PERIOD WIN COUNT (Linear Form, which K wins each period?) ===")
period_winners = {p: {} for p in range(1, 6)}
for _, row in linear_df.iterrows():
    K = int(row["K"])
    for i, s in enumerate(row["sharpes_by_period"]):
        period_winners[i+1][K] = s

print(f"{'Period':>7} | {'Winner K':>9} | {'Winner Sharpe':>13} | {'K=12 Sharpe':>11} | {'K=12 Rank':>10}")
print("-" * 60)
for p in range(1, 6):
    if p in period_winners and len(period_winners[p]) > 0:
        sorted_ks = sorted(period_winners[p].items(), key=lambda x: -x[1])
        winner_k, winner_s = sorted_ks[0]
        k12_s = period_winners[p].get(12, float('nan'))
        k12_rank = next((i+1 for i, (k, _) in enumerate(sorted_ks) if k == 12), '-')
        print(f"  P{p:>4} | K={winner_k:>6} | {winner_s:>13.3f} | {k12_s:>11.3f} | {k12_rank:>10}")


# ============================================================
# 15. Summary & Conclusions
# ============================================================
print("\n\n" + "=" * 80)
print("K230 SUMMARY: OPTIMAL VT PARAMETER SEARCH")
print("=" * 80)

# Best linear K
best_linear = linear_df.loc[linear_df["mean_sharpe"].idxmax()]
print(f"\n1. BEST K (LINEAR K/VIX):")
print(f"   Best K = {int(best_linear['K'])}, Mean Sharpe = {best_linear['mean_sharpe']:.4f}")
print(f"   K=12 baseline: Mean Sharpe = {k12_row['mean_sharpe']:.4f}")
sharpe_diff = best_linear['mean_sharpe'] - k12_row['mean_sharpe']
print(f"   Difference: {sharpe_diff:+.4f}")

# Best overall
best_overall = summary_df.iloc[0]
print(f"\n2. BEST OVERALL CONFIGURATION:")
print(f"   {best_overall['config']}: Mean Sharpe = {best_overall['mean_sharpe']:.4f}, "
      f"MDD = {best_overall['mean_mdd']:.2f}%")

# Statistical significance
print(f"\n3. STATISTICAL SIGNIFICANCE:")
if len(dm_results) > 0:
    print(f"   Pooled DM test ({baseline_key} vs {best_key}): t={pooled_t:.3f}, p={pooled_p:.4f}")
    if abs(pooled_t) > 3.0:
        print(f"   -> SIGNIFICANT improvement over K=12 (Harvey threshold passed)")
    elif abs(pooled_t) > 1.96:
        print(f"   -> Marginally significant (p<0.05) but FAILS Harvey threshold (|t|>3.0)")
    else:
        print(f"   -> NOT significant: K=12 is statistically equivalent to the best alternative")

# Practical conclusion
print(f"\n4. PRACTICAL CONCLUSION:")
if abs(sharpe_diff) < 0.05:
    print(f"   K=12 is 'good enough'. The Sharpe difference ({sharpe_diff:+.4f}) is economically negligible.")
    print(f"   12/VIX targets ~12% annual volatility — a reasonable default for balanced portfolios.")
else:
    print(f"   K={int(best_linear['K'])} shows meaningful improvement ({sharpe_diff:+.4f} Sharpe).")
    print(f"   Consider updating the VT rule if this survives additional robustness checks.")

print(f"\n5. FUNCTIONAL FORM RANKING (at K=12):")
k12_sorted = summary_df[summary_df["K"] == 12].sort_values("mean_sharpe", ascending=False)
for rank, (_, row) in enumerate(k12_sorted.iterrows(), 1):
    print(f"   {rank}. {row['form']:>10}: Sharpe={row['mean_sharpe']:.4f}, "
          f"MDD={row['mean_mdd']:.2f}%, Net Sharpe={row['mean_net_sharpe']:.4f}")


# ============================================================
# 16. Save Results
# ============================================================
output = {
    "experiment": "K230",
    "title": "Optimal VT Parameter Search — Is 12/VIX Really the Best?",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance (SPY, GLD, ^VIX)",
    "data_period": f"{DATA_START} to 2024-12-31",
    "oos_periods": [{"start": s, "end": e} for s, e in OOS_PERIODS],
    "methodology": {
        "portfolio": "50/50 SPY/GLD with monthly rebalance",
        "k_values": K_VALUES,
        "functional_forms": FORMS,
        "tx_cost_bps": TX_COST_BPS,
        "rf_annual": RF_ANNUAL,
        "lagged_weights": True,
        "monthly_rebalance": True,
    },
    "summary": summary_df.to_dict(orient="records"),
    "best_linear_k": int(best_linear["K"]),
    "best_linear_sharpe": best_linear["mean_sharpe"],
    "best_overall_config": best_overall["config"],
    "best_overall_sharpe": best_overall["mean_sharpe"],
    "k12_baseline_sharpe": k12_row["mean_sharpe"],
    "sharpe_diff_best_vs_k12": round(sharpe_diff, 4),
    "dm_test_results": dm_results if len(dm_results) > 0 else None,
    "pooled_dm": {
        "t_stat": round(float(pooled_t), 3),
        "p_value": round(float(pooled_p), 4),
        "significant_5pct": bool(abs(pooled_t) > 1.96),
        "passes_harvey": bool(abs(pooled_t) > 3.0),
    } if len(dm_results) > 0 else None,
    "buy_and_hold_mean_sharpe": round(np.mean(bh_sharpes), 4),
}

output_path = "experiments/k230_optimal_vt_param_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {output_path}")

print("\n[DONE] K230 complete.")
