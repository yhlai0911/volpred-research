#!/usr/bin/env python3
"""
Experiment: VT Performance Across Interest Rate Regimes
========================================================
Interest rates: ~5% (2007) → ~0% (2009-2021) → ~5% (2022-2026).
VT holds cash when reducing equity. Cash return was 0% for a decade but now 5%.
How does this change VT economics?

Key questions:
1. Does VT Sharpe improve when rates are high?
2. Is the ~4%/yr insurance premium (K41) still accurate when cash earns 5%?
3. Adjusted insurance cost = VT drag - cash yield on cash portion
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ──────────────────────────────────────────────────────────────
# 1. Download data
# ──────────────────────────────────────────────────────────────
print("=== Downloading data ===")
tickers = {"SPY": "SPY", "GLD": "GLD", "VIX": "^VIX", "IRX": "^IRX"}
raw = {}
for name, tk in tickers.items():
    df = yf.download(tk, start="2005-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df["Close"].dropna()
    print(f"  {name}: {len(raw[name])} obs, {raw[name].index[0].date()} ~ {raw[name].index[-1].date()}")

# Align all to common dates
idx = raw["SPY"].index
for k in ["GLD", "VIX", "IRX"]:
    idx = idx.intersection(raw[k].index)

spy = raw["SPY"].reindex(idx)
gld = raw["GLD"].reindex(idx)
vix = raw["VIX"].reindex(idx)
irx = raw["IRX"].reindex(idx)  # 3-month T-bill yield in %

print(f"  Common index: {len(idx)} trading days, {idx[0].date()} ~ {idx[-1].date()}")

# Returns
spy_ret = spy.pct_change().dropna()
gld_ret = gld.pct_change().dropna()

# Daily cash return from IRX (annualized yield → daily)
# IRX is quoted in %, so divide by 100, then by 252
cash_daily = (irx / 100 / 252).reindex(spy_ret.index).ffill().fillna(0)

# ──────────────────────────────────────────────────────────────
# 2. Define rate regimes
# ──────────────────────────────────────────────────────────────
# Fed Funds Rate proxy: IRX is close to Fed Funds for short-term
# Define regimes based on IRX level
def classify_regime(irx_val):
    """Classify interest rate regime based on 3-month T-bill yield."""
    if irx_val > 3.0:
        return "high"
    elif irx_val < 1.0:
        return "low"
    else:
        return "mid"

regime_series = irx.reindex(spy_ret.index).ffill().apply(classify_regime)
regime_series.name = "regime"

# Also compute monthly average IRX for regime labels
monthly_irx = irx.resample("ME").mean()

print("\n=== Rate Regime Distribution ===")
regime_counts = regime_series.value_counts()
for r in ["high", "mid", "low"]:
    if r in regime_counts.index:
        n = regime_counts[r]
        pct = n / len(regime_series) * 100
        print(f"  {r}: {n} days ({pct:.1f}%)")

# ──────────────────────────────────────────────────────────────
# 3. VT Strategy Functions
# ──────────────────────────────────────────────────────────────
def compute_12vix_weight(vix_series):
    """Compute 12/VIX equity weight, capped at [0, 1]."""
    w = 12.0 / vix_series
    return w.clip(0, 1)


def run_vt_strategy(equity_ret, vix_series, cash_return_daily, use_cash_yield=True, label=""):
    """
    Run 12/VIX VT strategy with monthly rebalance and lagged weights.

    Parameters:
    - equity_ret: daily equity returns
    - vix_series: VIX levels for weight computation
    - cash_return_daily: daily T-bill return (annualized / 252)
    - use_cash_yield: if False, cash portion earns 0%
    """
    # Compute daily weights from VIX
    raw_w = compute_12vix_weight(vix_series)

    # Monthly rebalance: use end-of-month VIX for next month's weight (lagged)
    monthly_w = raw_w.resample("ME").last()

    # Map monthly weight to daily: each day uses the previous month-end weight
    daily_w = monthly_w.shift(1).reindex(equity_ret.index, method="ffill")
    daily_w = daily_w.dropna()

    # Align all series
    common = equity_ret.index.intersection(daily_w.index).intersection(cash_return_daily.index)
    eq = equity_ret.reindex(common)
    w = daily_w.reindex(common)
    cash_r = cash_return_daily.reindex(common) if use_cash_yield else pd.Series(0.0, index=common)

    # VT return: w * equity + (1-w) * cash_return
    vt_ret = w * eq + (1 - w) * cash_r

    return vt_ret, w, common


def run_5050_vt(spy_ret, gld_ret, vix_series, cash_return_daily, use_cash_yield=True):
    """
    50/50 SPY/GLD portfolio with 12/VIX scaling.
    Equity portion = 50% SPY + 50% GLD, then scale by 12/VIX.
    """
    # Portfolio return (equal weight)
    port_ret = 0.5 * spy_ret + 0.5 * gld_ret

    # Common index
    common = spy_ret.index.intersection(gld_ret.index)
    port_ret = port_ret.reindex(common)

    return run_vt_strategy(port_ret, vix_series, cash_return_daily, use_cash_yield)


def compute_metrics(returns, rf_daily=None, label=""):
    """Compute Sharpe, MDD, Calmar, annualized return."""
    if len(returns) < 60:
        return {"label": label, "n_days": len(returns), "error": "insufficient data"}

    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)

    if rf_daily is not None:
        rf_ann = rf_daily.reindex(returns.index).mean() * 252
    else:
        rf_ann = 0.0

    sharpe = (ann_ret - rf_ann) / ann_vol if ann_vol > 0 else 0.0

    # MDD
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    calmar = ann_ret / abs(mdd) if mdd != 0 else 0.0

    # Sortino
    downside = returns[returns < 0]
    down_vol = downside.std() * np.sqrt(252) if len(downside) > 10 else ann_vol
    sortino = (ann_ret - rf_ann) / down_vol if down_vol > 0 else 0.0

    return {
        "label": label,
        "n_days": int(len(returns)),
        "ann_return": round(float(ann_ret), 4),
        "ann_vol": round(float(ann_vol), 4),
        "sharpe": round(float(sharpe), 4),
        "sharpe_rf0": round(float(ann_ret / ann_vol) if ann_vol > 0 else 0, 4),
        "mdd": round(float(mdd), 4),
        "calmar": round(float(calmar), 4),
        "sortino": round(float(sortino), 4),
    }


def compute_insurance_cost(bh_ret, vt_ret, cash_portion_ret):
    """
    Insurance cost = B&H return - VT return
    Adjusted insurance cost = raw insurance cost - cash yield earned on cash portion
    """
    raw_cost = bh_ret.mean() * 252 - vt_ret.mean() * 252
    return float(raw_cost)


# ──────────────────────────────────────────────────────────────
# 4. Run experiments
# ──────────────────────────────────────────────────────────────
print("\n=== Running VT Strategies ===")

# Strategy 1: SPY 12/VIX
spy_vt_cash, spy_w, spy_common = run_vt_strategy(spy_ret, vix, cash_daily, use_cash_yield=True, label="SPY VT(cash=Tbill)")
spy_vt_0, _, _ = run_vt_strategy(spy_ret, vix, cash_daily, use_cash_yield=False, label="SPY VT(cash=0%)")
spy_bh = spy_ret.reindex(spy_common)

# Cash portion return for SPY VT
spy_cash_portion_ret = (1 - spy_w.reindex(spy_common)) * cash_daily.reindex(spy_common)

# Strategy 2: 50/50 SPY/GLD 12/VIX
port_vt_cash, port_w, port_common = run_5050_vt(spy_ret, gld_ret, vix, cash_daily, use_cash_yield=True)
port_vt_0, _, _ = run_5050_vt(spy_ret, gld_ret, vix, cash_daily, use_cash_yield=False)
port_bh = (0.5 * spy_ret + 0.5 * gld_ret).reindex(port_common)

# Cash portion return for portfolio VT
port_cash_portion_ret = (1 - port_w.reindex(port_common)) * cash_daily.reindex(port_common)

# ──────────────────────────────────────────────────────────────
# 5. Full-sample results
# ──────────────────────────────────────────────────────────────
print("\n=== Full Sample Results ===")

rf_daily_aligned = cash_daily.reindex(spy_common)

results_full = {
    "spy_bh": compute_metrics(spy_bh, rf_daily_aligned, "SPY B&H"),
    "spy_vt_cash0": compute_metrics(spy_vt_0, rf_daily_aligned, "SPY 12/VIX (cash=0%)"),
    "spy_vt_cash_tbill": compute_metrics(spy_vt_cash, rf_daily_aligned, "SPY 12/VIX (cash=T-bill)"),
    "port_bh": compute_metrics(port_bh, rf_daily_aligned, "50/50 SPY/GLD B&H"),
    "port_vt_cash0": compute_metrics(port_vt_0, rf_daily_aligned, "50/50 12/VIX (cash=0%)"),
    "port_vt_cash_tbill": compute_metrics(port_vt_cash, rf_daily_aligned, "50/50 12/VIX (cash=T-bill)"),
}

for key, m in results_full.items():
    print(f"  {m['label']:30s} | Sharpe={m.get('sharpe','N/A'):>7} | MDD={m.get('mdd','N/A'):>7} | Ann.Ret={m.get('ann_return','N/A'):>7}")

# Full sample insurance costs
spy_raw_insurance = compute_insurance_cost(spy_bh, spy_vt_0, spy_cash_portion_ret)
spy_adj_insurance = compute_insurance_cost(spy_bh, spy_vt_cash, spy_cash_portion_ret)
spy_cash_yield_earned = spy_cash_portion_ret.mean() * 252

port_raw_insurance = compute_insurance_cost(port_bh, port_vt_0, port_cash_portion_ret)
port_adj_insurance = compute_insurance_cost(port_bh, port_vt_cash, port_cash_portion_ret)
port_cash_yield_earned = port_cash_portion_ret.mean() * 252

print(f"\n  SPY Insurance Cost (raw, cash=0%):     {spy_raw_insurance*100:.2f}%/yr")
print(f"  SPY Cash Yield Earned on Cash Portion:  {spy_cash_yield_earned*100:.2f}%/yr")
print(f"  SPY Insurance Cost (adjusted):          {spy_adj_insurance*100:.2f}%/yr")
print(f"  → Cash yield offsets: {(spy_raw_insurance - spy_adj_insurance)*100:.2f}%/yr")

print(f"\n  50/50 Insurance Cost (raw, cash=0%):    {port_raw_insurance*100:.2f}%/yr")
print(f"  50/50 Cash Yield Earned:                {port_cash_yield_earned*100:.2f}%/yr")
print(f"  50/50 Insurance Cost (adjusted):        {port_adj_insurance*100:.2f}%/yr")
print(f"  → Cash yield offsets: {(port_raw_insurance - port_adj_insurance)*100:.2f}%/yr")

# ──────────────────────────────────────────────────────────────
# 6. Sub-period analysis by rate regime
# ──────────────────────────────────────────────────────────────
print("\n=== Sub-Period Analysis by Rate Regime ===")

regime_aligned = regime_series.reindex(spy_common)

regime_results = {}
for regime in ["high", "mid", "low"]:
    mask = regime_aligned == regime
    if mask.sum() < 60:
        print(f"  Skipping {regime} regime: only {mask.sum()} days")
        continue

    # Average IRX in this regime
    avg_irx = irx.reindex(spy_common)[mask].mean()

    print(f"\n  --- {regime.upper()} rate regime (IRX>{3 if regime=='high' else 1}%, avg={avg_irx:.2f}%, {mask.sum()} days) ---")

    r = {}
    r["avg_irx"] = round(float(avg_irx), 2)
    r["n_days"] = int(mask.sum())

    # SPY strategies
    r["spy_bh"] = compute_metrics(spy_bh[mask], rf_daily_aligned[mask], f"SPY B&H [{regime}]")
    r["spy_vt_cash0"] = compute_metrics(spy_vt_0.reindex(spy_common)[mask], rf_daily_aligned[mask], f"SPY VT(0%) [{regime}]")
    r["spy_vt_cash_tbill"] = compute_metrics(spy_vt_cash[mask], rf_daily_aligned[mask], f"SPY VT(Tbill) [{regime}]")

    # Insurance costs for this regime
    spy_raw = compute_insurance_cost(spy_bh[mask], spy_vt_0.reindex(spy_common)[mask], spy_cash_portion_ret[mask])
    spy_cash_earned = spy_cash_portion_ret[mask].mean() * 252
    spy_adj = compute_insurance_cost(spy_bh[mask], spy_vt_cash[mask], spy_cash_portion_ret[mask])

    r["spy_insurance_raw"] = round(spy_raw, 4)
    r["spy_cash_yield_earned"] = round(float(spy_cash_earned), 4)
    r["spy_insurance_adjusted"] = round(spy_adj, 4)

    # 50/50 strategies
    regime_aligned_port = regime_series.reindex(port_common)
    mask_port = regime_aligned_port == regime

    rf_port = cash_daily.reindex(port_common)

    r["port_bh"] = compute_metrics(port_bh[mask_port], rf_port[mask_port], f"50/50 B&H [{regime}]")
    r["port_vt_cash0"] = compute_metrics(port_vt_0.reindex(port_common)[mask_port], rf_port[mask_port], f"50/50 VT(0%) [{regime}]")
    r["port_vt_cash_tbill"] = compute_metrics(port_vt_cash.reindex(port_common)[mask_port], rf_port[mask_port], f"50/50 VT(Tbill) [{regime}]")

    port_raw = compute_insurance_cost(port_bh[mask_port], port_vt_0.reindex(port_common)[mask_port], port_cash_portion_ret.reindex(port_common)[mask_port])
    port_cash_earned = port_cash_portion_ret.reindex(port_common)[mask_port].mean() * 252
    port_adj = compute_insurance_cost(port_bh[mask_port], port_vt_cash.reindex(port_common)[mask_port], port_cash_portion_ret.reindex(port_common)[mask_port])

    r["port_insurance_raw"] = round(port_raw, 4)
    r["port_cash_yield_earned"] = round(float(port_cash_earned), 4)
    r["port_insurance_adjusted"] = round(port_adj, 4)

    regime_results[regime] = r

    for key in ["spy_bh", "spy_vt_cash0", "spy_vt_cash_tbill", "port_bh", "port_vt_cash0", "port_vt_cash_tbill"]:
        m = r[key]
        print(f"    {m['label']:35s} | Sharpe={m.get('sharpe','N/A'):>7} | MDD={m.get('mdd','N/A'):>7} | Ann.Ret={m.get('ann_return','N/A'):>7}")

    print(f"    SPY insurance raw={spy_raw*100:.2f}%, cash earned={spy_cash_earned*100:.2f}%, adjusted={spy_adj*100:.2f}%")
    print(f"    50/50 insurance raw={port_raw*100:.2f}%, cash earned={port_cash_earned*100:.2f}%, adjusted={port_adj*100:.2f}%")


# ──────────────────────────────────────────────────────────────
# 7. Year-by-year insurance cost decomposition
# ──────────────────────────────────────────────────────────────
print("\n=== Year-by-Year Insurance Cost Decomposition (SPY 12/VIX) ===")

yearly_decomp = {}
for year in range(spy_common[0].year, spy_common[-1].year + 1):
    mask_yr = spy_common.year == year
    if mask_yr.sum() < 60:
        continue

    bh_yr = spy_bh[mask_yr]
    vt0_yr = spy_vt_0.reindex(spy_common)[mask_yr]
    vt_cash_yr = spy_vt_cash[mask_yr]
    w_yr = spy_w.reindex(spy_common)[mask_yr]
    cash_r_yr = cash_daily.reindex(spy_common)[mask_yr]
    irx_yr = irx.reindex(spy_common)[mask_yr]

    bh_ann = bh_yr.mean() * 252
    vt0_ann = vt0_yr.mean() * 252
    vt_cash_ann = vt_cash_yr.mean() * 252
    avg_w = w_yr.mean()
    avg_cash_alloc = 1 - avg_w
    avg_irx = irx_yr.mean()
    cash_earned = ((1 - w_yr) * cash_r_yr).mean() * 252

    raw_cost = bh_ann - vt0_ann
    adj_cost = bh_ann - vt_cash_ann

    yr_data = {
        "year": year,
        "avg_irx": round(float(avg_irx), 2),
        "avg_equity_weight": round(float(avg_w), 3),
        "avg_cash_alloc": round(float(avg_cash_alloc), 3),
        "bh_return": round(float(bh_ann), 4),
        "vt_return_cash0": round(float(vt0_ann), 4),
        "vt_return_cash_tbill": round(float(vt_cash_ann), 4),
        "insurance_raw": round(float(raw_cost), 4),
        "cash_yield_earned": round(float(cash_earned), 4),
        "insurance_adjusted": round(float(adj_cost), 4),
    }
    yearly_decomp[str(year)] = yr_data

    print(f"  {year} | IRX={avg_irx:5.2f}% | w_eq={avg_w:.2f} | B&H={bh_ann*100:+6.1f}% | "
          f"VT(0%)={vt0_ann*100:+6.1f}% | VT(Tbill)={vt_cash_ann*100:+6.1f}% | "
          f"Raw cost={raw_cost*100:+5.1f}% | Cash earned={cash_earned*100:+4.1f}% | Adj cost={adj_cost*100:+5.1f}%")


# ──────────────────────────────────────────────────────────────
# 8. Sharpe ratio by rolling 3-year windows
# ──────────────────────────────────────────────────────────────
print("\n=== Rolling 3-Year Sharpe vs Average Rate ===")

rolling_sharpe_data = []
window_days = 756  # ~3 years

for i in range(0, len(spy_common) - window_days, 63):  # step = quarterly
    end_idx = i + window_days
    if end_idx > len(spy_common):
        break

    period_idx = spy_common[i:end_idx]

    bh_r = spy_bh.reindex(period_idx).dropna()
    vt0_r = spy_vt_0.reindex(spy_common).reindex(period_idx).dropna()
    vt_cash_r = spy_vt_cash.reindex(period_idx).dropna()
    irx_r = irx.reindex(period_idx).dropna()

    if len(bh_r) < 500:
        continue

    avg_rate = irx_r.mean()

    bh_sharpe = bh_r.mean() / bh_r.std() * np.sqrt(252) if bh_r.std() > 0 else 0
    vt0_sharpe = vt0_r.mean() / vt0_r.std() * np.sqrt(252) if vt0_r.std() > 0 else 0
    vt_cash_sharpe = vt_cash_r.mean() / vt_cash_r.std() * np.sqrt(252) if vt_cash_r.std() > 0 else 0

    rolling_sharpe_data.append({
        "period_end": period_idx[-1].strftime("%Y-%m-%d"),
        "avg_irx": round(float(avg_rate), 2),
        "bh_sharpe": round(float(bh_sharpe), 3),
        "vt_cash0_sharpe": round(float(vt0_sharpe), 3),
        "vt_tbill_sharpe": round(float(vt_cash_sharpe), 3),
        "sharpe_improvement_cash0": round(float(vt0_sharpe - bh_sharpe), 3),
        "sharpe_improvement_tbill": round(float(vt_cash_sharpe - bh_sharpe), 3),
    })

# Correlation between rate level and VT Sharpe improvement
if len(rolling_sharpe_data) > 5:
    rates_arr = np.array([d["avg_irx"] for d in rolling_sharpe_data])
    sharpe_imp_0 = np.array([d["sharpe_improvement_cash0"] for d in rolling_sharpe_data])
    sharpe_imp_tbill = np.array([d["sharpe_improvement_tbill"] for d in rolling_sharpe_data])

    corr_0 = np.corrcoef(rates_arr, sharpe_imp_0)[0, 1]
    corr_tbill = np.corrcoef(rates_arr, sharpe_imp_tbill)[0, 1]

    print(f"  Correlation(avg_rate, VT Sharpe improvement cash=0%):    r={corr_0:.3f}")
    print(f"  Correlation(avg_rate, VT Sharpe improvement cash=Tbill): r={corr_tbill:.3f}")
    print(f"  Number of rolling windows: {len(rolling_sharpe_data)}")

    # Show a few examples
    for d in rolling_sharpe_data[::10]:
        print(f"    {d['period_end']} | rate={d['avg_irx']:5.2f}% | B&H Sharpe={d['bh_sharpe']:6.3f} | "
              f"VT(0%) Sharpe={d['vt_cash0_sharpe']:6.3f} | VT(Tbill) Sharpe={d['vt_tbill_sharpe']:6.3f}")
else:
    corr_0 = None
    corr_tbill = None
    print("  Insufficient rolling windows for correlation analysis")


# ──────────────────────────────────────────────────────────────
# 9. Key findings
# ──────────────────────────────────────────────────────────────
print("\n=== Key Findings ===")

# Average weight across regimes
avg_w_full = spy_w.reindex(spy_common).mean()
avg_cash_alloc_full = 1 - avg_w_full

# High rate vs low rate comparison
if "high" in regime_results and "low" in regime_results:
    high_r = regime_results["high"]
    low_r = regime_results["low"]

    print(f"\n  1. VT Cash Allocation: avg equity weight={avg_w_full:.2f}, cash alloc={avg_cash_alloc_full:.2f}")
    print(f"\n  2. High-rate regime (IRX avg={high_r['avg_irx']:.1f}%):")
    print(f"     SPY insurance: raw={high_r['spy_insurance_raw']*100:.2f}% → adjusted={high_r['spy_insurance_adjusted']*100:.2f}%")
    print(f"     Cash yield earned: {high_r['spy_cash_yield_earned']*100:.2f}%/yr")
    print(f"\n  3. Low-rate regime (IRX avg={low_r['avg_irx']:.1f}%):")
    print(f"     SPY insurance: raw={low_r['spy_insurance_raw']*100:.2f}% → adjusted={low_r['spy_insurance_adjusted']*100:.2f}%")
    print(f"     Cash yield earned: {low_r['spy_cash_yield_earned']*100:.2f}%/yr")
    print(f"\n  4. Insurance cost reduction in high-rate regime:")
    delta_spy = (high_r['spy_insurance_raw'] - high_r['spy_insurance_adjusted']) * 100
    delta_low = (low_r['spy_insurance_raw'] - low_r['spy_insurance_adjusted']) * 100
    print(f"     High-rate cash offset: {delta_spy:.2f}%/yr")
    print(f"     Low-rate cash offset:  {delta_low:.2f}%/yr")
    print(f"     Difference: {delta_spy - delta_low:.2f}%/yr more offset in high-rate")

if corr_0 is not None:
    print(f"\n  5. Rolling correlation (rate level vs VT Sharpe gain):")
    print(f"     Cash=0%:   r={corr_0:.3f}")
    print(f"     Cash=Tbill: r={corr_tbill:.3f}")
    if corr_tbill > corr_0 + 0.05:
        print(f"     → VT benefits more from high rates when cash earns T-bill")
    elif abs(corr_tbill - corr_0) < 0.05:
        print(f"     → Similar correlation regardless of cash yield assumption")

# K41 comparison
print(f"\n  6. K41 Insurance Premium Update:")
print(f"     K41 original estimate: ~4%/yr (full sample, cash=0%)")
print(f"     This study raw (cash=0%): {spy_raw_insurance*100:.2f}%/yr")
print(f"     This study adjusted (cash=Tbill): {spy_adj_insurance*100:.2f}%/yr")
print(f"     Cash yield offsets {(spy_raw_insurance - spy_adj_insurance)*100:.2f}%/yr of insurance cost")


# ──────────────────────────────────────────────────────────────
# 10. Save results
# ──────────────────────────────────────────────────────────────
output = {
    "experiment": "Interest Rate Regime VT Analysis",
    "description": "利率環境對 VT 策略經濟學的影響。高利率時期，VT 持有的現金部位可賺取 T-bill 收益，降低保險成本。分析 SPY 12/VIX 和 50/50 SPY/GLD 在不同利率環境下的表現。",
    "proposed_by": "用戶",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "status": "draft",
    "config": {
        "start": spy_common[0].strftime("%Y-%m-%d"),
        "end": spy_common[-1].strftime("%Y-%m-%d"),
        "vix_threshold": 12.0,
        "rebalance": "monthly",
        "weight_lag": "1 month (lagged)",
        "cash_proxy": "^IRX (3-month T-bill yield)",
        "regime_thresholds": {"high": ">3%", "mid": "1-3%", "low": "<1%"},
    },
    "full_sample": {
        "results": results_full,
        "insurance_cost": {
            "spy": {
                "raw_annual_pct": round(spy_raw_insurance * 100, 2),
                "cash_yield_earned_pct": round(spy_cash_yield_earned * 100, 2),
                "adjusted_annual_pct": round(spy_adj_insurance * 100, 2),
                "cash_offset_pct": round((spy_raw_insurance - spy_adj_insurance) * 100, 2),
            },
            "port_5050": {
                "raw_annual_pct": round(port_raw_insurance * 100, 2),
                "cash_yield_earned_pct": round(port_cash_yield_earned * 100, 2),
                "adjusted_annual_pct": round(port_adj_insurance * 100, 2),
                "cash_offset_pct": round((port_raw_insurance - port_adj_insurance) * 100, 2),
            },
        },
    },
    "regime_analysis": regime_results,
    "yearly_decomposition": yearly_decomp,
    "rolling_sharpe_vs_rate": {
        "correlation_cash0": round(float(corr_0), 3) if corr_0 is not None else None,
        "correlation_cash_tbill": round(float(corr_tbill), 3) if corr_tbill is not None else None,
        "n_windows": len(rolling_sharpe_data),
        "window_size_days": window_days,
        "data": rolling_sharpe_data,
    },
    "conclusions_zh": [],  # Will be filled below
}

# Generate conclusions
conclusions = []

# K41 comparison
conclusions.append(
    f"K41 原始保險費估計 ~4%/yr (cash=0%)。本研究全樣本：raw={spy_raw_insurance*100:.2f}%/yr, "
    f"adjusted (cash=Tbill)={spy_adj_insurance*100:.2f}%/yr。現金收益抵消 {(spy_raw_insurance - spy_adj_insurance)*100:.2f}%/yr。"
)

if "high" in regime_results and "low" in regime_results:
    high_r = regime_results["high"]
    low_r = regime_results["low"]
    conclusions.append(
        f"高利率期 (IRX>{3}%, avg={high_r['avg_irx']:.1f}%): SPY VT 保險費 raw={high_r['spy_insurance_raw']*100:.2f}% → "
        f"adjusted={high_r['spy_insurance_adjusted']*100:.2f}%。現金收益抵消 {high_r['spy_cash_yield_earned']*100:.2f}%/yr。"
    )
    conclusions.append(
        f"低利率期 (IRX<{1}%, avg={low_r['avg_irx']:.1f}%): SPY VT 保險費 raw={low_r['spy_insurance_raw']*100:.2f}% → "
        f"adjusted={low_r['spy_insurance_adjusted']*100:.2f}%。現金部位幾乎無貢獻 ({low_r['spy_cash_yield_earned']*100:.2f}%/yr)。"
    )
    delta_high = (high_r['spy_insurance_raw'] - high_r['spy_insurance_adjusted']) * 100
    delta_low = (low_r['spy_insurance_raw'] - low_r['spy_insurance_adjusted']) * 100
    conclusions.append(
        f"利率環境差異：高利率期現金抵消 {delta_high:.2f}%/yr vs 低利率期 {delta_low:.2f}%/yr，"
        f"差距 {delta_high - delta_low:.2f}%/yr。"
    )

if corr_tbill is not None:
    conclusions.append(
        f"滾動 3 年相關性（利率水平 vs VT Sharpe 增量）：cash=0% r={corr_0:.3f}, cash=Tbill r={corr_tbill:.3f}。"
        f"{'高利率確實改善 VT 經濟學' if corr_tbill > 0.15 else '利率水平與 VT 相對表現相關性不強'}。"
    )

output["conclusions_zh"] = conclusions

# Save
output_path = Path("/Users/yhlai0911/Desktop/volpred-research/storage/experiments/interest_rate_vt.json")
output_path.parent.mkdir(parents=True, exist_ok=True)
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2, default=str)

print(f"\n=== Results saved to {output_path} ===")
print(f"  Conclusions ({len(conclusions)} items):")
for i, c in enumerate(conclusions, 1):
    print(f"  {i}. {c}")

print("\nDone.")
