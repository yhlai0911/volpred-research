#!/usr/bin/env python3
"""
K506: EWT-0050 Vol Spread Strategy — Cross-OOS Validation
==========================================================
Background:
  K505: VT+VolSpread combo Sharpe=0.698, MDD=-25% (best Taiwan strategy candidate).
  But fails Harvey (t=2.49) and needs cross-OOS validation before deployment.

Strategy:
  Base: weight = min(8.63 / VIX, 1.0)  [Taiwan VT, Q1 finding]
  Vol Spread Adjustment:
    ratio = EWT_realized_vol / TW50_realized_vol (21-day rolling)
    if ratio > 1.2 → weight *= 0.5  (reduce: EWT more volatile = international stress)
    if ratio < 0.8 → weight *= 1.2  (increase: TW50 stable relative to EWT)
    else: no adjustment
  Monthly rebalancing (K499: monthly optimal for high TX cost)
  TX: 0.585% round-trip (Taiwan)
  Cash earns 1.5% annual (Taiwan short-term deposit proxy)

Comparison:
  1. Buy & Hold 0050.TW
  2. 8.63/VIX VT (existing strategy)
  3. VT + VolSpread (K505 candidate)

5 Cross-OOS Periods:
  1. 2012-2013 (post-GFC recovery)
  2. 2014-2015 (China fears, TW slow growth)
  3. 2016-2017 (Trump election, tech rally)
  4. 2018-2019 (trade war, yield inversion)
  5. 2020-2021 (COVID crash + recovery)
  (K505's 2022-2025 is the 6th, already known good)

Evaluation:
  - Net Sharpe (after TX), MDD, Calmar, Annual Return
  - DM test: VT+VS vs VT alone (per-period and pooled)
  - ≥4/5 OOS periods VT+VS beats VT → consider deployment
  - ≤2/5 → do NOT deploy

Data: yfinance (EWT, 0050.TW, ^VIX) — real market data
References:
  - Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
  - Harvey, Liu, Zhu (2016) "...and the Cross-Section of Expected Returns" RFS
  - Bozovic (2024) "VIX-managed portfolios" IRFA
  - K499 (monthly rebalancing optimal), K505 (VT+VolSpread initial results)
  - Q1 (8.63/VIX for Taiwan = 12/(VIX×1.39))

Author: [提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import json
import time
from datetime import datetime, timezone
from scipy import stats
from pathlib import Path

RESULTS_PATH = Path(__file__).parent / "k506_ewt_volspread_cross_oos_results.json"

# ============================================================
# Configuration
# ============================================================
TX_ROUNDTRIP = 0.00585       # 0.585% round-trip (Taiwan)
CASH_RATE_ANNUAL = 0.015     # 1.5% Taiwan short-term deposit
VT_SCALAR = 8.63             # 12/(1.39) adjusted for VIXTWN
MAX_WEIGHT = 1.0             # cap at 100% equity
VOL_WINDOW = 21              # 21-day rolling vol for spread
RATIO_HIGH = 1.2             # reduce when ratio > 1.2
RATIO_LOW = 0.8              # increase when ratio < 0.8
ADJUST_DOWN = 0.5            # multiplier when high spread
ADJUST_UP = 1.2              # multiplier when low spread
TRADING_DAYS = 252

OOS_PERIODS = [
    ("2012-01-01", "2013-12-31", "2012-2013"),
    ("2014-01-01", "2015-12-31", "2014-2015"),
    ("2016-01-01", "2017-12-31", "2016-2017"),
    ("2018-01-01", "2019-12-31", "2018-2019"),
    ("2020-01-01", "2021-12-31", "2020-2021"),
]

# Need IS data before OOS for vol computation
DATA_START = "2010-01-01"   # 2yr buffer before first OOS
DATA_END = "2022-01-01"     # covers through 2021


print("=" * 80)
print("K506: EWT-0050 Vol Spread Strategy — Cross-OOS Validation")
print("=" * 80)
t0 = time.time()

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1/5] Downloading data...")

tickers = {
    "EWT": "EWT",           # iShares MSCI Taiwan ETF (USD)
    "TW50": "0050.TW",      # Yuanta 0050 ETF (TWD)
    "VIX": "^VIX",          # CBOE VIX
}

raw = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df
    print(f"  {name} ({ticker}): {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

# ============================================================
# 2. DATA PREPARATION (vectorized)
# ============================================================
print("\n[2/5] Preparing data...")

# Close prices
ewt_close = raw["EWT"]["Close"].squeeze()
tw50_close = raw["TW50"]["Close"].squeeze()
vix_close = raw["VIX"]["Close"].squeeze()

# Align on common trading days
# Note: EWT trades on US calendar, TW50 on Taiwan calendar, VIX on US calendar
# We use forward-fill to handle calendar mismatches
all_dates = ewt_close.index.union(tw50_close.index).union(vix_close.index)
ewt_aligned = ewt_close.reindex(all_dates).ffill()
tw50_aligned = tw50_close.reindex(all_dates).ffill()
vix_aligned = vix_close.reindex(all_dates).ffill()

# Use TW50 trading calendar as base (strategy trades 0050.TW)
tw_dates = tw50_close.dropna().index
ewt_on_tw = ewt_aligned.reindex(tw_dates)
tw50_on_tw = tw50_aligned.reindex(tw_dates)
vix_on_tw = vix_aligned.reindex(tw_dates)

# Build master dataframe
data = pd.DataFrame({
    "ewt_close": ewt_on_tw,
    "tw50_close": tw50_on_tw,
    "vix": vix_on_tw,
})
data = data.dropna()

# Returns (log returns for vol, simple returns for P&L)
data["ewt_logret"] = np.log(data["ewt_close"] / data["ewt_close"].shift(1))
data["tw50_logret"] = np.log(data["tw50_close"] / data["tw50_close"].shift(1))
data["tw50_ret"] = data["tw50_close"] / data["tw50_close"].shift(1) - 1
data = data.dropna()

# Rolling realized volatility (annualized)
data["ewt_vol"] = data["ewt_logret"].rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)
data["tw50_vol"] = data["tw50_logret"].rolling(VOL_WINDOW).std() * np.sqrt(TRADING_DAYS)
data["vol_ratio"] = data["ewt_vol"] / data["tw50_vol"]

# Drop NaN from rolling window
data = data.dropna()

print(f"  Final aligned dataset: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  Vol ratio stats: mean={data['vol_ratio'].mean():.3f}, "
      f"std={data['vol_ratio'].std():.3f}, "
      f"min={data['vol_ratio'].min():.3f}, max={data['vol_ratio'].max():.3f}")
print(f"  Ratio > {RATIO_HIGH}: {(data['vol_ratio'] > RATIO_HIGH).mean()*100:.1f}% of days")
print(f"  Ratio < {RATIO_LOW}: {(data['vol_ratio'] < RATIO_LOW).mean()*100:.1f}% of days")

# ============================================================
# 3. STRATEGY FUNCTIONS (vectorized)
# ============================================================

def get_month_starts(dates):
    """Return numpy boolean array for first trading day of each month."""
    months = pd.Series(dates.to_period('M'), index=dates)
    result = (months != months.shift(1)).values.copy()
    result[0] = True  # First day is always a rebalance day
    return result


def backtest_buyhold(ret_series):
    """Buy & Hold: 100% equity, no rebalancing."""
    cum = (1 + ret_series).cumprod()
    total_ret = cum.iloc[-1] - 1
    n_years = len(ret_series) / TRADING_DAYS
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1
    ann_vol = ret_series.std() * np.sqrt(TRADING_DAYS)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # MDD
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    return {
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": float(ann_ret / abs(mdd)) if mdd != 0 else 0,
        "total_ret": float(total_ret),
        "n_days": len(ret_series),
        "n_rebalances": 0,
        "tx_total_pct": 0.0,
        "daily_returns": ret_series,
    }


def backtest_vt(data_slice, use_volspread=False):
    """
    VT strategy with monthly rebalancing.
    If use_volspread: apply vol spread adjustment.
    """
    dates = data_slice.index
    tw50_ret = data_slice["tw50_ret"].values
    vix = data_slice["vix"].values
    vol_ratio = data_slice["vol_ratio"].values

    # Identify month starts for rebalancing
    month_starts = get_month_starts(dates)  # numpy boolean array

    n = len(dates)
    portfolio_ret = np.empty(n)
    daily_cash_ret = CASH_RATE_ANNUAL / TRADING_DAYS

    # Track state
    current_weight = 0.0
    n_rebalances = 0
    tx_total = 0.0

    for i in range(n):
        # Check if rebalance day (first day or month start)
        if i == 0 or month_starts[i]:
            # Compute target weight
            target_w = min(VT_SCALAR / vix[i], MAX_WEIGHT) if vix[i] > 0 else 0

            if use_volspread:
                r = vol_ratio[i]
                if r > RATIO_HIGH:
                    target_w *= ADJUST_DOWN
                elif r < RATIO_LOW:
                    target_w *= ADJUST_UP
                target_w = min(target_w, MAX_WEIGHT)

            # Transaction cost on weight change
            weight_change = abs(target_w - current_weight)
            tx_cost = weight_change * TX_ROUNDTRIP
            tx_total += tx_cost

            current_weight = target_w
            n_rebalances += 1

            # Today's return (after rebalancing at open, approximate)
            day_ret = current_weight * tw50_ret[i] + (1 - current_weight) * daily_cash_ret - tx_cost
        else:
            # Normal day: hold current weight
            day_ret = current_weight * tw50_ret[i] + (1 - current_weight) * daily_cash_ret

        portfolio_ret[i] = day_ret

    # Convert to series
    port_ret = pd.Series(portfolio_ret, index=dates)
    cum = (1 + port_ret).cumprod()
    total_ret = cum.iloc[-1] - 1
    n_years = n / TRADING_DAYS
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(TRADING_DAYS)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    return {
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": float(ann_ret / abs(mdd)) if mdd != 0 else 0,
        "total_ret": float(total_ret),
        "n_days": n,
        "n_rebalances": n_rebalances,
        "tx_total_pct": float(tx_total * 100),
        "daily_returns": port_ret,
    }


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    loss1, loss2: loss series (e.g., -daily_returns for comparing strategies).
    H0: equal predictive ability. Reject if |t| > threshold.
    Returns: (t_stat, p_value)
    """
    d = loss1 - loss2
    n = len(d)
    d_mean = d.mean()
    # Newey-West type variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value)


# ============================================================
# 4. CROSS-OOS BACKTEST
# ============================================================
print("\n[3/5] Running cross-OOS backtests...")

all_results = {}
vt_wins = 0
vs_wins = 0
all_vt_returns = []
all_vs_returns = []

for oos_start, oos_end, label in OOS_PERIODS:
    print(f"\n  --- OOS Period: {label} ({oos_start} to {oos_end}) ---")

    # Slice data for this OOS period
    mask = (data.index >= oos_start) & (data.index <= oos_end)
    oos_data = data.loc[mask].copy()

    if len(oos_data) < 100:
        print(f"    ⚠️ Only {len(oos_data)} days — skipping (need >= 100)")
        continue

    print(f"    Trading days: {len(oos_data)}")
    print(f"    Vol ratio: mean={oos_data['vol_ratio'].mean():.3f}, "
          f"std={oos_data['vol_ratio'].std():.3f}")
    print(f"    VIX: mean={oos_data['vix'].mean():.1f}, "
          f"min={oos_data['vix'].min():.1f}, max={oos_data['vix'].max():.1f}")

    # 1. Buy & Hold
    bh = backtest_buyhold(oos_data["tw50_ret"])

    # 2. VT only (8.63/VIX)
    vt = backtest_vt(oos_data, use_volspread=False)

    # 3. VT + VolSpread
    vs = backtest_vt(oos_data, use_volspread=True)

    # DM test: VT+VS vs VT (using negative returns as loss)
    # Positive t-stat means VT+VS has lower loss (= better)
    vt_loss = -vt["daily_returns"].values
    vs_loss = -vs["daily_returns"].values
    dm_t, dm_p = dm_test(vt_loss, vs_loss)

    # Collect for pooled test
    all_vt_returns.append(vt["daily_returns"])
    all_vs_returns.append(vs["daily_returns"])

    # Determine winner
    if vs["sharpe"] > vt["sharpe"]:
        vs_wins += 1
        winner = "VT+VS"
    else:
        vt_wins += 1
        winner = "VT"

    period_result = {
        "period": label,
        "n_days": len(oos_data),
        "vix_mean": round(oos_data["vix"].mean(), 1),
        "vol_ratio_mean": round(oos_data["vol_ratio"].mean(), 3),
        "vol_ratio_std": round(oos_data["vol_ratio"].std(), 3),
        "pct_high_ratio": round((oos_data["vol_ratio"] > RATIO_HIGH).mean() * 100, 1),
        "pct_low_ratio": round((oos_data["vol_ratio"] < RATIO_LOW).mean() * 100, 1),
        "buy_hold": {
            "sharpe": round(bh["sharpe"], 4),
            "ann_ret_pct": round(bh["ann_ret"] * 100, 2),
            "mdd_pct": round(bh["mdd"] * 100, 2),
        },
        "vt_only": {
            "sharpe": round(vt["sharpe"], 4),
            "ann_ret_pct": round(vt["ann_ret"] * 100, 2),
            "ann_vol_pct": round(vt["ann_vol"] * 100, 2),
            "mdd_pct": round(vt["mdd"] * 100, 2),
            "calmar": round(vt["calmar"], 3),
            "n_rebalances": vt["n_rebalances"],
            "tx_total_pct": round(vt["tx_total_pct"], 3),
        },
        "vt_volspread": {
            "sharpe": round(vs["sharpe"], 4),
            "ann_ret_pct": round(vs["ann_ret"] * 100, 2),
            "ann_vol_pct": round(vs["ann_vol"] * 100, 2),
            "mdd_pct": round(vs["mdd"] * 100, 2),
            "calmar": round(vs["calmar"], 3),
            "n_rebalances": vs["n_rebalances"],
            "tx_total_pct": round(vs["tx_total_pct"], 3),
        },
        "dm_test_vs_minus_vt": {
            "t_stat": round(dm_t, 4),
            "p_value": round(dm_p, 4),
            "significant_5pct": dm_p < 0.05,
            "direction": "VT+VS better" if dm_t > 0 else "VT better",
        },
        "sharpe_diff": round(vs["sharpe"] - vt["sharpe"], 4),
        "winner": winner,
    }

    all_results[label] = period_result

    print(f"    Buy&Hold:  Sharpe={bh['sharpe']:.4f}, Ret={bh['ann_ret']*100:.1f}%, MDD={bh['mdd']*100:.1f}%")
    print(f"    VT only:   Sharpe={vt['sharpe']:.4f}, Ret={vt['ann_ret']*100:.1f}%, MDD={vt['mdd']*100:.1f}%")
    print(f"    VT+VS:     Sharpe={vs['sharpe']:.4f}, Ret={vs['ann_ret']*100:.1f}%, MDD={vs['mdd']*100:.1f}%")
    print(f"    DM test:   t={dm_t:.4f}, p={dm_p:.4f} ({'significant' if dm_p < 0.05 else 'NS'})")
    print(f"    Winner:    {winner} (Sharpe diff = {vs['sharpe'] - vt['sharpe']:+.4f})")

# ============================================================
# 5. POOLED ANALYSIS
# ============================================================
print("\n[4/5] Pooled analysis across all OOS periods...")

# Concatenate all daily returns
pooled_vt = pd.concat(all_vt_returns)
pooled_vs = pd.concat(all_vs_returns)

# Pooled DM test
pooled_vt_loss = -pooled_vt.values
pooled_vs_loss = -pooled_vs.values
pooled_dm_t, pooled_dm_p = dm_test(pooled_vt_loss, pooled_vs_loss)

# Pooled Sharpe
n_years_pooled = len(pooled_vt) / TRADING_DAYS
pooled_vt_sharpe = (pooled_vt.mean() * TRADING_DAYS) / (pooled_vt.std() * np.sqrt(TRADING_DAYS))
pooled_vs_sharpe = (pooled_vs.mean() * TRADING_DAYS) / (pooled_vs.std() * np.sqrt(TRADING_DAYS))

# Harvey t-test for each strategy vs 0
# t = Sharpe * sqrt(T/252) approximately
n_total = len(pooled_vt)
harvey_vt_t = pooled_vt_sharpe * np.sqrt(n_total / TRADING_DAYS)
harvey_vs_t = pooled_vs_sharpe * np.sqrt(n_total / TRADING_DAYS)

print(f"\n  Pooled Statistics ({n_total} total days, {n_years_pooled:.1f} years):")
print(f"    VT only   — Pooled Sharpe: {pooled_vt_sharpe:.4f}, Harvey t: {harvey_vt_t:.3f}")
print(f"    VT+VS     — Pooled Sharpe: {pooled_vs_sharpe:.4f}, Harvey t: {harvey_vs_t:.3f}")
print(f"    Pooled DM — t={pooled_dm_t:.4f}, p={pooled_dm_p:.4f}")
print(f"    Harvey threshold: t > 3.0")

print(f"\n  Score: VT+VS wins {vs_wins}/5, VT wins {vt_wins}/5")
if vs_wins >= 4:
    verdict = "PASS — VT+VolSpread consistently outperforms. Consider deployment."
elif vs_wins >= 3:
    verdict = "MARGINAL — Slight edge but not consistent enough. More testing needed."
elif vs_wins <= 2:
    verdict = "FAIL — VT+VolSpread does NOT consistently outperform. Do NOT deploy."
else:
    verdict = "INCONCLUSIVE"

print(f"  Verdict: {verdict}")

# ============================================================
# 6. SAVE RESULTS
# ============================================================
print("\n[5/5] Saving results...")

# Summary table for display
summary_rows = []
for label in [p[2] for p in OOS_PERIODS]:
    if label in all_results:
        r = all_results[label]
        summary_rows.append({
            "Period": label,
            "VIX_mean": r["vix_mean"],
            "VolRatio_mean": r["vol_ratio_mean"],
            "BH_Sharpe": r["buy_hold"]["sharpe"],
            "VT_Sharpe": r["vt_only"]["sharpe"],
            "VS_Sharpe": r["vt_volspread"]["sharpe"],
            "Diff": r["sharpe_diff"],
            "DM_t": r["dm_test_vs_minus_vt"]["t_stat"],
            "DM_p": r["dm_test_vs_minus_vt"]["p_value"],
            "Winner": r["winner"],
        })

summary_df = pd.DataFrame(summary_rows)
print("\n" + "=" * 100)
print("CROSS-OOS SUMMARY TABLE")
print("=" * 100)
print(summary_df.to_string(index=False))
print("=" * 100)

elapsed = time.time() - t0

output = {
    "experiment": "K506",
    "title": "EWT-0050 Vol Spread Strategy — Cross-OOS Validation",
    "date": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (EWT, 0050.TW, ^VIX)",
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_total_days": len(data),
    "strategy": {
        "base": "weight = min(8.63/VIX, 1.0)",
        "vol_spread_adjustment": {
            "vol_window": VOL_WINDOW,
            "ratio_high_threshold": RATIO_HIGH,
            "ratio_low_threshold": RATIO_LOW,
            "adjust_down_multiplier": ADJUST_DOWN,
            "adjust_up_multiplier": ADJUST_UP,
        },
        "rebalancing": "monthly (1st trading day)",
        "tx_cost_roundtrip": TX_ROUNDTRIP,
        "cash_rate_annual": CASH_RATE_ANNUAL,
    },
    "oos_periods": {label: all_results.get(label, "skipped") for _, _, label in OOS_PERIODS},
    "pooled_analysis": {
        "n_total_days": n_total,
        "n_years": round(n_years_pooled, 2),
        "vt_only_pooled_sharpe": round(float(pooled_vt_sharpe), 4),
        "vt_volspread_pooled_sharpe": round(float(pooled_vs_sharpe), 4),
        "harvey_t_vt": round(float(harvey_vt_t), 3),
        "harvey_t_vs": round(float(harvey_vs_t), 3),
        "harvey_threshold": 3.0,
        "pooled_dm_test": {
            "t_stat": round(pooled_dm_t, 4),
            "p_value": round(pooled_dm_p, 4),
            "significant_5pct": pooled_dm_p < 0.05,
        },
    },
    "cross_oos_score": {
        "vs_wins": vs_wins,
        "vt_wins": vt_wins,
        "total_periods": len([l for l in [p[2] for p in OOS_PERIODS] if l in all_results]),
        "pass_threshold": ">=4/5",
        "verdict": verdict,
    },
    "vol_ratio_diagnostics": {
        "full_sample_mean": round(data["vol_ratio"].mean(), 3),
        "full_sample_std": round(data["vol_ratio"].std(), 3),
        "full_sample_min": round(data["vol_ratio"].min(), 3),
        "full_sample_max": round(data["vol_ratio"].max(), 3),
        "pct_above_1.2": round((data["vol_ratio"] > RATIO_HIGH).mean() * 100, 1),
        "pct_below_0.8": round((data["vol_ratio"] < RATIO_LOW).mean() * 100, 1),
    },
    "runtime_seconds": round(elapsed, 2),
    "references": [
        "Moreira & Muir (2017) 'Volatility-Managed Portfolios' JF",
        "Harvey, Liu, Zhu (2016) '...and the Cross-Section of Expected Returns' RFS",
        "Bozovic (2024) 'VIX-managed portfolios' IRFA",
        "K499: Monthly rebalancing optimal for Taiwan TX cost",
        "K505: VT+VolSpread initial results (Sharpe=0.698, MDD=-25%)",
        "Q1: 8.63/VIX for Taiwan = 12/(VIX*1.39)",
    ],
}

RESULTS_PATH.write_text(json.dumps(output, indent=2, default=str))
print(f"\nResults saved to {RESULTS_PATH}")
print(f"Runtime: {elapsed:.1f}s")
print(f"\nFINAL VERDICT: {verdict}")
