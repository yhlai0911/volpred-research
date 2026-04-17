"""
K499: Optimal VT Rebalancing Frequency — SPY 12/VIX Strategy
=============================================================
Background: Our 12/VIX VT strategy rebalances daily by default. But transaction
costs (especially Taiwan's 0.585%) erode returns. What is the optimal rebalancing
frequency considering net-of-TX-cost Sharpe?

Data: SPY + ^VIX from yfinance, 2008-2025.
Strategy: weight = min(12/VIX, 1.5), equity portion = weight × SPY, rest in cash (rf=4%).

Frequencies tested:
  1. Daily
  2. Weekly (every Friday)
  3. Bi-weekly (every other Friday)
  4. Monthly (1st trading day of month)
  5. Quarterly (1st trading day of quarter)
  6. Threshold-based: only rebalance when |new_weight - current_weight| > 5%

TX Cost scenarios:
  - Low: 0.05% round-trip (US equity, low-cost broker)
  - Medium: 0.20% round-trip
  - High: 0.585% round-trip (Taiwan futures/ETF)

Evaluation:
  - Gross Sharpe (no TX), Net Sharpe (after TX), annual turnover, MDD,
    Calmar ratio, break-even TX cost vs buy-and-hold

Related knowledge: N79 (12/VIX best lazy VT), N80 (19yr backtest),
  rebalancing_freq_w504 (monthly best for w504), K220 (50/50 SPY/GLD frequency)

References:
  - Harvey, Liechty, Liechty, Mueller (2010) "Portfolio Selection with Higher Moments"
  - Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
  - Fleming, Kirby, Ostdiek (2003) "The Economic Value of Volatility Timing Using Realized Volatility" JFE

Author: [提出: 用戶, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import json
import time
from datetime import datetime

print("=" * 80)
print("K499: Optimal VT Rebalancing Frequency — SPY 12/VIX Strategy")
print("=" * 80)

t0 = time.time()

# ============================================================
# 1. Download data
# ============================================================
print("\n[1/6] Downloading SPY and VIX data...")

spy_raw = yf.download("SPY", start="2007-01-01", end="2026-01-01", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="2007-01-01", end="2026-01-01", progress=False, auto_adjust=False)

# Flatten MultiIndex if present
for df in [spy_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

data = spy.join(vix, how="inner").dropna()
data["spy_ret"] = np.log(data["spy_close"] / data["spy_close"].shift(1))
data = data.dropna()

# Focus on 2008-2025 (includes GFC, COVID, rate hikes, etc.)
data = data.loc["2008-01-01":"2025-12-31"]

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  VIX range: {data['vix_close'].min():.1f} - {data['vix_close'].max():.1f}")

# ============================================================
# 2. Parameters
# ============================================================
print("\n[2/6] Setting parameters...")

FREQUENCIES = ["daily", "weekly", "biweekly", "monthly", "quarterly", "threshold_5pct"]
TX_COSTS = {
    "0bp": 0.0,
    "5bp": 0.0005,
    "20bp": 0.002,
    "18.55bp": 0.001855,  # CORRECTED K625: ETF round-trip (was 58.5bp — WRONG)
}
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252

print(f"  Frequencies: {FREQUENCIES}")
print(f"  TX cost scenarios: {list(TX_COSTS.keys())}")

# ============================================================
# 3. Vectorized rebalancing engine
# ============================================================

def get_rebal_mask(dates: pd.DatetimeIndex, freq: str, vix_vals: np.ndarray = None) -> np.ndarray:
    """Return boolean mask for rebalance days."""
    n = len(dates)
    mask = np.zeros(n, dtype=bool)

    if freq == "daily":
        mask[:] = True
    elif freq == "weekly":
        mask = np.array(dates.weekday == 4)  # Friday
    elif freq == "biweekly":
        fridays = np.where(dates.weekday == 4)[0]
        for i in range(0, len(fridays), 2):
            mask[fridays[i]] = True
    elif freq == "monthly":
        months = dates.to_period("M")
        for m in months.unique():
            idx = np.where(months == m)[0]
            if len(idx) > 0:
                mask[idx[0]] = True
    elif freq == "quarterly":
        quarters = dates.to_period("Q")
        for q in quarters.unique():
            idx = np.where(quarters == q)[0]
            if len(idx) > 0:
                mask[idx[0]] = True
    elif freq == "threshold_5pct":
        # This is handled differently in run_strategy — mask computed dynamically
        pass

    # Always rebalance on day 0
    mask[0] = True
    return mask


def run_strategy(spy_rets: np.ndarray, vix_vals: np.ndarray,
                 dates: pd.DatetimeIndex, freq: str, tx_cost: float) -> dict:
    """
    Run 12/VIX VT strategy on SPY.

    weight = min(12/VIX, 1.5), capped at [0, 1.5].
    Equity allocation = weight * portfolio_value in SPY.
    Cash allocation = (1 - min(weight,1)) * portfolio_value earns rf.
    If weight > 1, we lever up (borrow at rf).

    Returns dict with daily_returns, turnover, final_value.
    """
    n = len(spy_rets)
    if n < 20:
        return None

    # Compute target weights from VIX
    target_weights = np.minimum(12.0 / np.maximum(vix_vals, 1.0), 1.5)
    target_weights = np.maximum(target_weights, 0.0)

    # Get rebalance mask
    is_threshold = (freq == "threshold_5pct")
    if not is_threshold:
        rebal_mask = get_rebal_mask(dates, freq, vix_vals)

    # Simulate
    portfolio_value = 1.0
    current_weight = target_weights[0]

    # Allocations
    equity = portfolio_value * current_weight
    cash = portfolio_value * max(1.0 - current_weight, 0.0)
    # If weight > 1, we borrow: equity = w * PV, cash = (1-w)*PV < 0 means borrowing

    daily_returns = np.zeros(n)
    daily_turnover = np.zeros(n)
    weight_series = np.zeros(n)
    weight_series[0] = current_weight
    rebal_count = 0

    for t in range(1, n):
        # Assets grow
        equity *= np.exp(spy_rets[t])
        cash *= np.exp(RF_DAILY)

        pre_value = equity + cash

        # Determine if we rebalance
        do_rebal = False
        if is_threshold:
            # Rebalance only if weight difference > 5%
            actual_weight = equity / pre_value if pre_value > 0 else 0
            new_target = target_weights[t]
            if abs(new_target - actual_weight) > 0.05:
                do_rebal = True
        else:
            do_rebal = rebal_mask[t]

        if do_rebal:
            new_weight = target_weights[t]

            # Target allocations
            target_equity = pre_value * new_weight
            target_cash = pre_value * (1.0 - new_weight)

            # Turnover: total $ traded
            traded = abs(target_equity - equity) + abs(target_cash - cash)
            daily_turnover[t] = traded / pre_value if pre_value > 0 else 0

            # Pay TX cost
            cost = traded * tx_cost
            post_value = pre_value - cost

            # Reallocate
            equity = post_value * new_weight
            cash = post_value * (1.0 - new_weight)
            current_weight = new_weight
            rebal_count += 1
        else:
            post_value = pre_value

        daily_returns[t] = np.log(post_value / portfolio_value) if portfolio_value > 0 else 0
        portfolio_value = post_value
        weight_series[t] = equity / portfolio_value if portfolio_value > 0 else current_weight

    return {
        "daily_returns": daily_returns,
        "turnover": daily_turnover,
        "weights": weight_series,
        "final_value": portfolio_value,
        "rebal_count": rebal_count,
    }


def compute_metrics(daily_rets: np.ndarray, daily_turnover: np.ndarray,
                    n_days: int) -> dict:
    """Compute performance metrics."""
    years = n_days / 252

    ann_ret = np.mean(daily_rets) * 252
    ann_vol = np.std(daily_rets, ddof=1) * np.sqrt(252)
    excess_daily = daily_rets - RF_DAILY
    sharpe = np.mean(excess_daily) / np.std(daily_rets, ddof=1) * np.sqrt(252) if np.std(daily_rets) > 1e-10 else 0

    # Max drawdown
    cum = np.exp(np.cumsum(daily_rets))
    running_max = np.maximum.accumulate(cum)
    dd = cum / running_max - 1
    max_dd = np.min(dd)

    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-10 else np.inf

    # Sortino
    down_rets = daily_rets[daily_rets < 0]
    down_vol = np.std(down_rets, ddof=1) * np.sqrt(252) if len(down_rets) > 1 else 1e-6
    sortino = (ann_ret - RF_ANNUAL) / down_vol

    # Turnover
    ann_turnover = np.sum(daily_turnover) / years
    n_rebals = np.sum(daily_turnover > 0)

    # Cumulative return
    total_return = np.exp(np.sum(daily_rets)) - 1

    return {
        "sharpe": round(float(sharpe), 4),
        "ann_ret": round(float(ann_ret), 5),
        "ann_vol": round(float(ann_vol), 5),
        "max_dd": round(float(max_dd), 5),
        "calmar": round(float(calmar), 3),
        "sortino": round(float(sortino), 3),
        "ann_turnover_pct": round(float(ann_turnover * 100), 2),
        "n_rebals": int(n_rebals),
        "rebals_per_year": round(float(n_rebals / years), 1),
        "total_return_pct": round(float(total_return * 100), 2),
    }


# ============================================================
# 4. Buy-and-hold benchmark
# ============================================================
print("\n[3/6] Computing buy-and-hold benchmark...")

spy_rets_arr = data["spy_ret"].values
bh_ann_ret = np.mean(spy_rets_arr) * 252
bh_ann_vol = np.std(spy_rets_arr, ddof=1) * np.sqrt(252)
bh_sharpe = (np.mean(spy_rets_arr) - RF_DAILY) / np.std(spy_rets_arr, ddof=1) * np.sqrt(252)
bh_cum = np.exp(np.cumsum(spy_rets_arr))
bh_mdd = np.min(bh_cum / np.maximum.accumulate(bh_cum) - 1)
bh_total = np.exp(np.sum(spy_rets_arr)) - 1

print(f"  Buy-and-hold SPY: Sharpe={bh_sharpe:.4f}, AnnRet={bh_ann_ret:.2%}, "
      f"MDD={bh_mdd:.2%}, TotalReturn={bh_total:.1%}")

# ============================================================
# 5. Run all combinations
# ============================================================
print("\n[4/6] Running all frequency × TX cost combinations...")

results = {}
for freq in FREQUENCIES:
    results[freq] = {}
    for tx_name, tx_val in TX_COSTS.items():
        result = run_strategy(
            data["spy_ret"].values,
            data["vix_close"].values,
            data.index,
            freq,
            tx_val,
        )
        if result is not None:
            metrics = compute_metrics(
                result["daily_returns"],
                result["turnover"],
                len(data),
            )
            metrics["rebal_count_total"] = result["rebal_count"]
            results[freq][tx_name] = metrics

    # Print progress
    s0 = results[freq].get("0bp", {}).get("sharpe", "N/A")
    s58 = results[freq].get("58.5bp", {}).get("sharpe", "N/A")
    print(f"  {freq:>16s}: gross Sharpe={s0}, net Sharpe @58.5bp={s58}")

elapsed = time.time() - t0
print(f"\n  All combinations computed in {elapsed:.1f}s")

# ============================================================
# 6. Analysis and output
# ============================================================
print("\n[5/6] Analysis")
print("=" * 80)

# --- Table 1: Sharpe by Frequency × TX Cost ---
print("\n--- Table 1: Net Sharpe by Frequency × TX Cost ---")
header = f"{'Frequency':<18}"
for tx_name in TX_COSTS.keys():
    header += f" {tx_name:>10}"
print(header)
print("-" * (18 + 11 * len(TX_COSTS)))

for freq in FREQUENCIES:
    row = f"{freq:<18}"
    for tx_name in TX_COSTS.keys():
        s = results[freq].get(tx_name, {}).get("sharpe", None)
        if s is not None:
            row += f" {s:>10.4f}"
        else:
            row += f" {'N/A':>10}"
    print(row)

# Add BH row
bh_row = f"{'buy_and_hold':<18}"
for tx_name in TX_COSTS.keys():
    bh_row += f" {bh_sharpe:>10.4f}"
print(bh_row)

# --- Table 2: Annual Turnover and Rebalance Count ---
print("\n--- Table 2: Annual Turnover (%) and Rebalances/Year ---")
print(f"{'Frequency':<18} {'Turnover%':>12} {'Rebals/yr':>12} {'Rebal_total':>12}")
print("-" * 54)
for freq in FREQUENCIES:
    m = results[freq].get("0bp", {})
    t = m.get("ann_turnover_pct", 0)
    r = m.get("rebals_per_year", 0)
    rc = m.get("rebal_count_total", 0)
    print(f"{freq:<18} {t:>11.1f}% {r:>12.1f} {rc:>12d}")

# --- Table 3: MDD by Frequency × TX Cost ---
print("\n--- Table 3: Max Drawdown by Frequency × TX Cost ---")
header = f"{'Frequency':<18}"
for tx_name in TX_COSTS.keys():
    header += f" {tx_name:>10}"
print(header)
print("-" * (18 + 11 * len(TX_COSTS)))

for freq in FREQUENCIES:
    row = f"{freq:<18}"
    for tx_name in TX_COSTS.keys():
        m = results[freq].get(tx_name, {}).get("max_dd", None)
        if m is not None:
            row += f" {m:>9.1%}"
        else:
            row += f" {'N/A':>10}"
    print(row)
bh_row = f"{'buy_and_hold':<18}"
for tx_name in TX_COSTS.keys():
    bh_row += f" {bh_mdd:>9.1%}"
print(bh_row)

# --- Table 4: Sharpe Delta vs Buy-and-Hold ---
print("\n--- Table 4: Sharpe Improvement over Buy-and-Hold ---")
header = f"{'Frequency':<18}"
for tx_name in TX_COSTS.keys():
    header += f" {tx_name:>10}"
print(header)
print("-" * (18 + 11 * len(TX_COSTS)))

for freq in FREQUENCIES:
    row = f"{freq:<18}"
    for tx_name in TX_COSTS.keys():
        s = results[freq].get(tx_name, {}).get("sharpe", None)
        if s is not None:
            delta = s - bh_sharpe
            sign = "+" if delta >= 0 else ""
            row += f" {sign}{delta:>9.4f}"
        else:
            row += f" {'N/A':>10}"
    print(row)

# --- Break-even TX cost analysis ---
print("\n--- Table 5: Break-Even TX Cost (bps) vs Buy-and-Hold ---")
print("  (At what TX cost does each frequency underperform buy-and-hold?)")
print(f"{'Frequency':<18} {'Break-even (bps)':>18} {'Gross Sharpe':>14}")
print("-" * 50)

tx_bps_vals = [0, 5, 20, 58.5]
tx_names_list = list(TX_COSTS.keys())

for freq in FREQUENCIES:
    gross_sharpe = results[freq].get("0bp", {}).get("sharpe", None)
    if gross_sharpe is None:
        continue

    # Find break-even by interpolation
    sharpe_at_tx = []
    for tx_name in tx_names_list:
        s = results[freq].get(tx_name, {}).get("sharpe", None)
        if s is not None:
            sharpe_at_tx.append(s)
        else:
            sharpe_at_tx.append(np.nan)

    sharpe_at_tx = np.array(sharpe_at_tx)
    diff = sharpe_at_tx - bh_sharpe

    breakeven = None
    for i in range(len(diff) - 1):
        if np.isnan(diff[i]) or np.isnan(diff[i+1]):
            continue
        if diff[i] >= 0 and diff[i+1] < 0:
            # Linear interpolation
            x0, x1 = tx_bps_vals[i], tx_bps_vals[i+1]
            y0, y1 = diff[i], diff[i+1]
            breakeven = x0 - y0 * (x1 - x0) / (y1 - y0)
            break

    if breakeven is not None:
        print(f"{freq:<18} {breakeven:>17.1f} {gross_sharpe:>14.4f}")
    elif all(d >= 0 for d in diff if not np.isnan(d)):
        print(f"{freq:<18} {'> 58.5':>17} {gross_sharpe:>14.4f}")
    else:
        print(f"{freq:<18} {'< 0 (never)':>17} {gross_sharpe:>14.4f}")

# --- Rankings at each TX level ---
print("\n--- Frequency Rankings by Net Sharpe ---")
for tx_name in TX_COSTS.keys():
    freq_sharpes = []
    for freq in FREQUENCIES:
        s = results[freq].get(tx_name, {}).get("sharpe", -999)
        freq_sharpes.append((freq, s))
    freq_sharpes.sort(key=lambda x: -x[1])
    rank_str = " > ".join(f"{f}({s:.3f})" for f, s in freq_sharpes if s > -999)
    print(f"  TX={tx_name:>7s}: {rank_str}")

# --- Sharpe degradation from daily ---
print("\n--- Table 6: Sharpe Cost of TX (daily gross - daily net) ---")
daily_gross = results["daily"].get("0bp", {}).get("sharpe", 0)
for tx_name, tx_val in TX_COSTS.items():
    if tx_name == "0bp":
        continue
    daily_net = results["daily"].get(tx_name, {}).get("sharpe", 0)
    drag = daily_gross - daily_net
    print(f"  Daily @ {tx_name:>7s}: drag = {drag:.4f} Sharpe points "
          f"({drag/daily_gross*100:.1f}% of gross)")

# --- Threshold vs Monthly comparison ---
print("\n--- Threshold-5% vs Monthly (head-to-head) ---")
for tx_name in TX_COSTS.keys():
    t_s = results["threshold_5pct"].get(tx_name, {}).get("sharpe", None)
    m_s = results["monthly"].get(tx_name, {}).get("sharpe", None)
    t_to = results["threshold_5pct"].get(tx_name, {}).get("ann_turnover_pct", None)
    m_to = results["monthly"].get(tx_name, {}).get("ann_turnover_pct", None)
    if t_s is not None and m_s is not None:
        winner = "threshold" if t_s > m_s else "monthly"
        print(f"  TX={tx_name:>7s}: threshold={t_s:.4f}(TO={t_to:.0f}%) "
              f"vs monthly={m_s:.4f}(TO={m_to:.0f}%) → {winner}")

# --- Calmar and Sortino comparison ---
print("\n--- Table 7: Calmar and Sortino at 0bp and 58.5bp ---")
print(f"{'Frequency':<18} {'Calmar_0bp':>12} {'Calmar_58bp':>13} {'Sortino_0bp':>13} {'Sortino_58bp':>14}")
print("-" * 70)
for freq in FREQUENCIES:
    c0 = results[freq].get("0bp", {}).get("calmar", None)
    c58 = results[freq].get("58.5bp", {}).get("calmar", None)
    s0 = results[freq].get("0bp", {}).get("sortino", None)
    s58 = results[freq].get("58.5bp", {}).get("sortino", None)
    print(f"{freq:<18} {c0 if c0 else 0:>12.3f} {c58 if c58 else 0:>13.3f} "
          f"{s0 if s0 else 0:>13.3f} {s58 if s58 else 0:>14.3f}")

# ============================================================
# Summary verdict
# ============================================================
print("\n" + "=" * 80)
print("SUMMARY VERDICT")
print("=" * 80)

# Best at each level
for tx_name in TX_COSTS.keys():
    best = max(FREQUENCIES, key=lambda f: results[f].get(tx_name, {}).get("sharpe", -999))
    best_s = results[best].get(tx_name, {}).get("sharpe", 0)
    print(f"  Best at TX={tx_name:>7s}: {best:<18s} (Sharpe={best_s:.4f})")

print(f"\n  Buy-and-hold reference: Sharpe={bh_sharpe:.4f}")

# Practical advice
print("\n  PRACTICAL RECOMMENDATIONS:")
print(f"  - US investors (5bp):  Monthly or Threshold — both work well")
print(f"  - Taiwan (58.5bp):     Check if VT still beats B&H at this cost level")

# Check Taiwan viability
tw_best = max(FREQUENCIES, key=lambda f: results[f].get("58.5bp", {}).get("sharpe", -999))
tw_best_s = results[tw_best].get("58.5bp", {}).get("sharpe", 0)
if tw_best_s > bh_sharpe:
    print(f"  → YES: {tw_best} still beats B&H by {tw_best_s - bh_sharpe:.4f} Sharpe points")
else:
    print(f"  → NO: Even best ({tw_best}, {tw_best_s:.4f}) underperforms B&H ({bh_sharpe:.4f})")
    print(f"    VT strategy NOT viable at Taiwan TX costs with frequent rebalancing")

print(f"\n  Total runtime: {time.time() - t0:.1f}s")

# ============================================================
# 7. Save results JSON
# ============================================================
print("\n[6/6] Saving results...")

save_data = {
    "experiment": "K499",
    "title": "Optimal VT Rebalancing Frequency — SPY 12/VIX Strategy",
    "date": datetime.now().isoformat(),
    "data_source": "yfinance (SPY, ^VIX)",
    "data_range": f"{data.index[0].date()} to {data.index[-1].date()}",
    "n_trading_days": len(data),
    "strategy": "weight = min(12/VIX, 1.5), equity in SPY, rest in cash @4% rf",
    "frequencies_tested": FREQUENCIES,
    "tx_cost_scenarios": {k: f"{v*100:.3f}% round-trip" for k, v in TX_COSTS.items()},
    "benchmark": {
        "type": "buy_and_hold_SPY",
        "sharpe": round(float(bh_sharpe), 4),
        "ann_ret_pct": round(float(bh_ann_ret * 100), 2),
        "ann_vol_pct": round(float(bh_ann_vol * 100), 2),
        "max_dd_pct": round(float(bh_mdd * 100), 2),
        "total_return_pct": round(float(bh_total * 100), 2),
    },
    "results": {},
    "rankings": {},
    "breakeven_analysis": {},
    "key_findings": [],
    "references": [
        "Fleming, Kirby, Ostdiek (2003) 'The Economic Value of Volatility Timing Using Realized Volatility' JFE",
        "Moreira & Muir (2017) 'Volatility-Managed Portfolios' JF",
        "Harvey, Liechty, Liechty, Mueller (2010) 'Portfolio Selection with Higher Moments'",
    ],
}

# Store all results
for freq in FREQUENCIES:
    save_data["results"][freq] = {}
    for tx_name in TX_COSTS.keys():
        if tx_name in results[freq]:
            save_data["results"][freq][tx_name] = results[freq][tx_name]

# Rankings
for tx_name in TX_COSTS.keys():
    freq_sharpes = []
    for freq in FREQUENCIES:
        s = results[freq].get(tx_name, {}).get("sharpe", -999)
        freq_sharpes.append({"frequency": freq, "sharpe": round(s, 4)})
    freq_sharpes.sort(key=lambda x: -x["sharpe"])
    save_data["rankings"][tx_name] = freq_sharpes

# Break-even analysis
for freq in FREQUENCIES:
    sharpe_at_tx = []
    for i, tx_name in enumerate(tx_names_list):
        s = results[freq].get(tx_name, {}).get("sharpe", None)
        sharpe_at_tx.append(s if s is not None else np.nan)

    sharpe_at_tx = np.array(sharpe_at_tx, dtype=float)
    diff = sharpe_at_tx - bh_sharpe

    breakeven = None
    for i in range(len(diff) - 1):
        if np.isnan(diff[i]) or np.isnan(diff[i+1]):
            continue
        if diff[i] >= 0 and diff[i+1] < 0:
            x0, x1 = tx_bps_vals[i], tx_bps_vals[i+1]
            y0, y1 = float(diff[i]), float(diff[i+1])
            breakeven = x0 - y0 * (x1 - x0) / (y1 - y0)
            break

    save_data["breakeven_analysis"][freq] = {
        "breakeven_bps": round(breakeven, 1) if breakeven is not None else None,
        "beats_bh_at_all_levels": bool(all(d >= 0 for d in diff if not np.isnan(d))),
        "loses_to_bh_at_all_levels": bool(all(d < 0 for d in diff if not np.isnan(d))),
    }

# Key findings
# 1. Best frequency at each TX level
for tx_name in TX_COSTS.keys():
    best = max(FREQUENCIES, key=lambda f: results[f].get(tx_name, {}).get("sharpe", -999))
    best_s = results[best].get(tx_name, {}).get("sharpe", 0)
    save_data["key_findings"].append(
        f"Best frequency at TX={tx_name}: {best} (Sharpe={best_s:.4f})"
    )

# 2. Threshold vs monthly
t_s_0 = results["threshold_5pct"].get("0bp", {}).get("sharpe", 0)
m_s_0 = results["monthly"].get("0bp", {}).get("sharpe", 0)
t_to = results["threshold_5pct"].get("0bp", {}).get("ann_turnover_pct", 0)
m_to = results["monthly"].get("0bp", {}).get("ann_turnover_pct", 0)
save_data["key_findings"].append(
    f"Threshold-5% vs Monthly: gross Sharpe {t_s_0:.4f} vs {m_s_0:.4f}, "
    f"turnover {t_to:.0f}% vs {m_to:.0f}%"
)

# 3. Taiwan viability
tw_best = max(FREQUENCIES, key=lambda f: results[f].get("58.5bp", {}).get("sharpe", -999))
tw_best_s = results[tw_best].get("58.5bp", {}).get("sharpe", 0)
if tw_best_s > bh_sharpe:
    save_data["key_findings"].append(
        f"Taiwan (58.5bp): VT VIABLE with {tw_best}, "
        f"net Sharpe={tw_best_s:.4f} vs B&H={bh_sharpe:.4f}"
    )
else:
    save_data["key_findings"].append(
        f"Taiwan (58.5bp): VT NOT VIABLE — best ({tw_best}) Sharpe={tw_best_s:.4f} "
        f"< B&H={bh_sharpe:.4f}"
    )

# 4. Daily turnover
daily_to = results["daily"].get("0bp", {}).get("ann_turnover_pct", 0)
save_data["key_findings"].append(f"Daily rebalancing annual turnover: {daily_to:.0f}%")

out_path = "experiments/k499_rebalancing_frequency_results.json"
with open(out_path, "w") as f:
    json.dump(save_data, f, indent=2, default=str)
print(f"  Results saved to {out_path}")

print("\n" + "=" * 80)
print("K499 complete.")
print("=" * 80)
