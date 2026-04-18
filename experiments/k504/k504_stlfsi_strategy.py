"""
K504: FRED STLFSI4 Macro Stress Regime Strategy
=================================================
Background: Gemini suggested using the St. Louis Fed Financial Stress Index (STLFSI4)
for regime switching. K503 showed 12/VIX is the irreducible kernel, but maybe
macro regime can adjust target volatility (not replace 12/VIX).

Strategy Design:
  Not replacing 12/VIX but adjusting target vol:
  - STLFSI4 < 0 (normal) → target vol = 12% (standard)
  - STLFSI4 0-1 (mild stress) → target vol = 10%
  - STLFSI4 > 1 (severe stress) → target vol = 8%
  weight = adjusted_target / VIX

Comparison:
  1. Buy & Hold SPY
  2. 12/VIX (fixed target=12%)
  3. STLFSI4-adjusted 12/VIX (variable target 8-12%)
  4. 50/50 SPY/GLD + 12/VIX
  5. 50/50 SPY/GLD + STLFSI4-adjusted

Data: FRED STLFSI4 (weekly, forward-filled to daily), SPY/GLD/VIX from yfinance
Period: 2000-2025 (STLFSI4 available from 1993)
TX cost: 0.05% (monthly rebalancing per K499)

Cross-OOS: 5 biennial periods (2006-07, 2008-09, ..., 2014-15 for first pass,
  then rolling 2016-2025)

References:
  - Kliesen, Owyang, Vermann (2012) "Disentangling Diverse Measures: A Survey
    of Financial Stress Indexes" Federal Reserve Bank of St. Louis Review
  - Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
  - Harvey, Liu, Zhu (2016) "...and the Cross-Section of Expected Returns" RFS
  - Bozovic (2024) "VIX-managed portfolios" IRFA

Author: [提出: Gemini, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import json
import time
import io
from datetime import datetime

print("=" * 80)
print("K504: FRED STLFSI4 Macro Stress Regime Strategy")
print("=" * 80)

t0 = time.time()

# ============================================================
# 1. Download data
# ============================================================
print("\n[1/7] Downloading data...")

# SPY, GLD, VIX
spy_raw = yf.download("SPY", start="1999-01-01", end="2026-01-01", progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="1999-01-01", end="2026-01-01", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="1999-01-01", end="2026-01-01", progress=False, auto_adjust=False)

# Flatten MultiIndex if present
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

# FRED STLFSI4 — download CSV directly
print("  Downloading STLFSI4 from FRED...")
try:
    import urllib.request
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=STLFSI4"
    response = urllib.request.urlopen(url, timeout=30)
    csv_data = response.read().decode('utf-8')
    stlfsi_raw = pd.read_csv(io.StringIO(csv_data))
    # Identify date column (could be 'DATE' or 'observation_date')
    date_col = [c for c in stlfsi_raw.columns if 'date' in c.lower()][0]
    val_col = [c for c in stlfsi_raw.columns if c != date_col][0]
    stlfsi_raw[date_col] = pd.to_datetime(stlfsi_raw[date_col])
    stlfsi_raw = stlfsi_raw.set_index(date_col)
    stlfsi_raw.columns = ["stlfsi4"]
    stlfsi_raw["stlfsi4"] = pd.to_numeric(stlfsi_raw["stlfsi4"], errors="coerce")
    stlfsi_raw = stlfsi_raw.dropna()
    print(f"  STLFSI4 downloaded: {stlfsi_raw.index[0].date()} to {stlfsi_raw.index[-1].date()}")
    print(f"  STLFSI4 range: {stlfsi_raw['stlfsi4'].min():.3f} to {stlfsi_raw['stlfsi4'].max():.3f}")
    print(f"  STLFSI4 observations: {len(stlfsi_raw)}")
except Exception as e:
    print(f"  STLFSI4 download failed: {e}")
    import traceback; traceback.print_exc()
    raise RuntimeError("Cannot download STLFSI4 data")

# ============================================================
# 2. Merge and prepare data
# ============================================================
print("\n[2/7] Preparing data...")

# Forward-fill STLFSI4 to daily frequency
stlfsi_daily = stlfsi_raw.resample("D").last().ffill()

# Merge all
data = spy.join(vix, how="inner").join(gld, how="left").join(stlfsi_daily, how="left")
data["stlfsi4"] = data["stlfsi4"].ffill()  # forward fill weekly to daily
data = data.dropna(subset=["spy_close", "vix_close", "stlfsi4"])

# Returns
data["spy_ret"] = np.log(data["spy_close"] / data["spy_close"].shift(1))
data["gld_ret"] = np.log(data["gld_close"] / data["gld_close"].shift(1))
data = data.dropna(subset=["spy_ret"])

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  VIX range: {data['vix_close'].min():.1f} - {data['vix_close'].max():.1f}")
print(f"  STLFSI4 range: {data['stlfsi4'].min():.3f} - {data['stlfsi4'].max():.3f}")

# GLD starts 2004-11, so fill NaN with 0 returns before that
data["gld_ret"] = data["gld_ret"].fillna(0)
data["gld_close"] = data["gld_close"].ffill().bfill()

# ============================================================
# 3. Descriptive statistics of STLFSI4
# ============================================================
print("\n[3/7] STLFSI4 descriptive statistics...")

stlfsi = data["stlfsi4"]
print(f"  Mean: {stlfsi.mean():.4f}")
print(f"  Std:  {stlfsi.std():.4f}")
print(f"  Skew: {stlfsi.skew():.4f}")
print(f"  Kurt: {stlfsi.kurtosis():.4f}")
print(f"  Min:  {stlfsi.min():.4f}")
print(f"  Max:  {stlfsi.max():.4f}")
print(f"  Median: {stlfsi.median():.4f}")

# Regime distribution
n_normal = (stlfsi < 0).sum()
n_mild = ((stlfsi >= 0) & (stlfsi < 1)).sum()
n_severe = (stlfsi >= 1).sum()
total = len(stlfsi)
print(f"\n  Regime distribution:")
print(f"    Normal (STLFSI4 < 0):  {n_normal:5d} days ({100*n_normal/total:.1f}%)")
print(f"    Mild stress (0-1):     {n_mild:5d} days ({100*n_mild/total:.1f}%)")
print(f"    Severe stress (> 1):   {n_severe:5d} days ({100*n_severe/total:.1f}%)")

# Check correlation with VIX
corr_vix_stlfsi = data[["vix_close", "stlfsi4"]].corr().iloc[0, 1]
print(f"\n  Correlation(VIX, STLFSI4): {corr_vix_stlfsi:.4f}")

# Lagged STLFSI4 correlation with VIX (check lead-lag)
for lag in [5, 10, 21]:
    c = data["stlfsi4"].shift(lag).corr(data["vix_close"])
    print(f"  Correlation(STLFSI4 lag-{lag}d, VIX): {c:.4f}")


# ============================================================
# 4. Strategy implementation
# ============================================================
print("\n[4/7] Implementing strategies...")

TX_COST = 0.0005  # 0.05% round-trip
RF_DAILY = 0.04 / 252  # 4% risk-free rate

def compute_strategy_returns(data, weights, tx_cost=TX_COST, rebal="monthly"):
    """Compute strategy returns with transaction costs and monthly rebalancing.

    weights: Series of target weights (0 to 1.5 for levered, 0 to 1 for unlevered)
    Returns: daily return series
    """
    # Monthly rebalancing: only update weights on 1st trading day of month
    if rebal == "monthly":
        month_starts = data.groupby(data.index.to_period("M")).apply(
            lambda x: x.index[0]).values
        monthly_weights = pd.Series(np.nan, index=data.index)
        for d in month_starts:
            if d in weights.index:
                monthly_weights.loc[d] = weights.loc[d]
        monthly_weights = monthly_weights.ffill()
        monthly_weights = monthly_weights.reindex(data.index).ffill()
        actual_weights = monthly_weights
    else:
        actual_weights = weights

    # Ensure no NaN
    actual_weights = actual_weights.fillna(0)

    # Transaction costs on weight changes
    weight_changes = actual_weights.diff().abs().fillna(0)
    tx_costs = weight_changes * tx_cost

    return actual_weights, tx_costs


def run_spy_strategy(data, target_vols, name, cap=1.5):
    """Run SPY-only strategy with variable target vol."""
    weights = (target_vols / data["vix_close"]).clip(0, cap)
    actual_w, tx = compute_strategy_returns(data, weights)

    # Daily portfolio return
    port_ret = actual_w * data["spy_ret"] + (1 - actual_w.clip(0, 1)) * RF_DAILY - tx

    return port_ret, actual_w, tx


def run_spy_gld_strategy(data, target_vols, name, spy_alloc=0.5, gld_alloc=0.5, cap=1.5):
    """Run SPY+GLD strategy with variable target vol."""
    # VIX-managed weights for SPY portion
    spy_vt_weight = (target_vols / data["vix_close"]).clip(0, cap)

    # SPY + GLD: each gets their allocation, SPY is VT-managed
    spy_w = spy_alloc * spy_vt_weight  # VT-managed SPY
    gld_w = pd.Series(gld_alloc, index=data.index)  # Fixed GLD allocation

    total_risky = spy_w + gld_w
    cash_w = (1 - total_risky).clip(0, 1)

    # Monthly rebalancing
    month_starts = data.groupby(data.index.to_period("M")).apply(
        lambda x: x.index[0]).values

    for col_w in [spy_w, gld_w, cash_w]:
        monthly = pd.Series(np.nan, index=data.index)
        for d in month_starts:
            if d in col_w.index:
                monthly.loc[d] = col_w.loc[d]
        monthly = monthly.ffill().reindex(data.index).ffill()
        col_w.update(monthly)

    # Recalculate with monthly rebalanced weights
    spy_w_m = pd.Series(np.nan, index=data.index)
    gld_w_m = pd.Series(np.nan, index=data.index)
    for d in month_starts:
        if d in spy_w.index:
            spy_w_m.loc[d] = spy_alloc * (target_vols.loc[d] / data["vix_close"].loc[d]) if d in target_vols.index else 0
            gld_w_m.loc[d] = gld_alloc
    spy_w_m = spy_w_m.ffill().clip(0, cap * spy_alloc)
    gld_w_m = gld_w_m.ffill()
    cash_w_m = (1 - spy_w_m - gld_w_m).clip(0, 1)

    # TX costs
    tx_spy = spy_w_m.diff().abs().fillna(0) * TX_COST
    tx_gld = gld_w_m.diff().abs().fillna(0) * TX_COST

    port_ret = (spy_w_m * data["spy_ret"] +
                gld_w_m * data["gld_ret"] +
                cash_w_m * RF_DAILY -
                tx_spy - tx_gld)

    return port_ret, spy_w_m, gld_w_m


def calc_metrics(returns, name, bh_returns=None):
    """Calculate strategy performance metrics."""
    ret = returns.dropna()
    n_years = len(ret) / 252

    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + ret).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    neg_ret = ret[ret < 0]
    downside_vol = neg_ret.std() * np.sqrt(252) if len(neg_ret) > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0

    total_ret = cum.iloc[-1] - 1
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    result = {
        "name": name,
        "ann_ret": round(float(ann_ret), 6),
        "ann_vol": round(float(ann_vol), 6),
        "sharpe": round(float(sharpe), 4),
        "mdd": round(float(mdd), 4),
        "calmar": round(float(calmar), 4),
        "sortino": round(float(sortino), 4),
        "cagr": round(float(cagr), 6),
        "total_ret": round(float(total_ret), 4),
        "n_days": len(ret),
    }

    # Harvey t-stat vs BH if provided
    if bh_returns is not None:
        excess = ret - bh_returns.reindex(ret.index).fillna(0)
        t_stat = excess.mean() / (excess.std() / np.sqrt(len(excess))) if excess.std() > 0 else 0
        result["harvey_t"] = round(float(t_stat), 4)

    return result


# ---- Define target vol functions ----

# Strategy 1: Buy & Hold SPY (benchmark)
bh_ret = data["spy_ret"].copy()

# Strategy 2: Fixed 12/VIX
target_12 = pd.Series(12.0, index=data.index)

# Strategy 3: STLFSI4-adjusted target vol
def stlfsi_target(stlfsi_val):
    """STLFSI4 < 0 → 12%, 0-1 → 10%, >1 → 8%"""
    if stlfsi_val < 0:
        return 12.0
    elif stlfsi_val < 1:
        return 10.0
    else:
        return 8.0

target_stlfsi = data["stlfsi4"].apply(stlfsi_target)

# Strategy 3b: Continuous STLFSI4 adjustment (smoother)
# target = 12 - 2 * clip(STLFSI4, 0, 2)  → range [8, 12]
target_stlfsi_cont = (12 - 2 * data["stlfsi4"].clip(0, 2))

# Strategy 3c: More aggressive STLFSI4 adjustment
# target = 12 - 4 * clip(STLFSI4, 0, 1) → range [8, 12] but faster ramp
target_stlfsi_aggressive = (12 - 4 * data["stlfsi4"].clip(0, 1))

print("  Running SPY-only strategies...")

# Run SPY strategies
ret_12vix, w_12vix, _ = run_spy_strategy(data, target_12, "12/VIX")
ret_stlfsi, w_stlfsi, _ = run_spy_strategy(data, target_stlfsi, "STLFSI-Step")
ret_stlfsi_c, w_stlfsi_c, _ = run_spy_strategy(data, target_stlfsi_cont, "STLFSI-Cont")
ret_stlfsi_a, w_stlfsi_a, _ = run_spy_strategy(data, target_stlfsi_aggressive, "STLFSI-Aggr")

print("  Running SPY+GLD strategies...")

# Run 50/50 SPY+GLD strategies
ret_5050_12, sw_5050_12, gw_5050_12 = run_spy_gld_strategy(data, target_12, "50/50+12VIX")
ret_5050_stlfsi, sw_5050_st, gw_5050_st = run_spy_gld_strategy(data, target_stlfsi, "50/50+STLFSI")
ret_5050_stlfsi_c, _, _ = run_spy_gld_strategy(data, target_stlfsi_cont, "50/50+STLFSI-C")

# ============================================================
# 5. Full-sample metrics
# ============================================================
print("\n[5/7] Full-sample performance metrics...")

# Use overlapping period (need GLD data from 2005+)
eval_start = "2005-01-01"
eval_end = "2025-12-31"

eval_mask = (data.index >= eval_start) & (data.index <= eval_end)
bh_eval = bh_ret[eval_mask]

strategies = {
    "BH_SPY": bh_eval,
    "12/VIX_SPY": ret_12vix[eval_mask],
    "STLFSI_Step_SPY": ret_stlfsi[eval_mask],
    "STLFSI_Cont_SPY": ret_stlfsi_c[eval_mask],
    "STLFSI_Aggr_SPY": ret_stlfsi_a[eval_mask],
    "50/50_12VIX": ret_5050_12[eval_mask],
    "50/50_STLFSI_Step": ret_5050_stlfsi[eval_mask],
    "50/50_STLFSI_Cont": ret_5050_stlfsi_c[eval_mask],
}

metrics = {}
for name, rets in strategies.items():
    bh_ref = bh_eval if name != "BH_SPY" else None
    metrics[name] = calc_metrics(rets, name, bh_ref)

print(f"\n  {'Strategy':<22} {'Sharpe':>8} {'Ann.Ret':>8} {'Ann.Vol':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
print("  " + "-" * 80)
for name, m in metrics.items():
    print(f"  {name:<22} {m['sharpe']:>8.4f} {m['ann_ret']:>8.4f} {m['ann_vol']:>8.4f} {m['mdd']:>8.4f} {m['calmar']:>8.4f} {m['sortino']:>8.4f}")

# ============================================================
# 6. Cross-OOS Validation (5+ periods)
# ============================================================
print("\n[6/7] Cross-OOS validation...")

# Define OOS periods (2-year blocks)
oos_periods = [
    ("2006-01-01", "2007-12-31"),
    ("2008-01-01", "2009-12-31"),
    ("2010-01-01", "2011-12-31"),
    ("2012-01-01", "2013-12-31"),
    ("2014-01-01", "2015-12-31"),
    ("2016-01-01", "2017-12-31"),
    ("2018-01-01", "2019-12-31"),
    ("2020-01-01", "2021-12-31"),
    ("2022-01-01", "2023-12-31"),
    ("2024-01-01", "2025-12-31"),
]

oos_results = []
stlfsi_wins = 0
n_periods = 0

print(f"\n  {'Period':<22} {'BH Sharpe':>10} {'12/VIX':>10} {'STLFSI-Step':>12} {'STLFSI-Cont':>12} {'Winner':>12}")
print("  " + "-" * 90)

for start, end in oos_periods:
    mask = (data.index >= start) & (data.index <= end)
    if mask.sum() < 100:
        continue

    bh_p = bh_ret[mask]
    r12 = ret_12vix[mask]
    rst = ret_stlfsi[mask]
    rsc = ret_stlfsi_c[mask]

    m_bh = calc_metrics(bh_p, "BH")
    m_12 = calc_metrics(r12, "12/VIX", bh_p)
    m_st = calc_metrics(rst, "STLFSI-Step", bh_p)
    m_sc = calc_metrics(rsc, "STLFSI-Cont", bh_p)

    # Which is better: 12/VIX or STLFSI?
    winner = "STLFSI" if m_st["sharpe"] > m_12["sharpe"] else "12/VIX"
    if m_st["sharpe"] > m_12["sharpe"]:
        stlfsi_wins += 1
    n_periods += 1

    oos_results.append({
        "period": f"{start[:4]}-{end[:4]}",
        "bh_sharpe": m_bh["sharpe"],
        "vix12_sharpe": m_12["sharpe"],
        "stlfsi_step_sharpe": m_st["sharpe"],
        "stlfsi_cont_sharpe": m_sc["sharpe"],
        "vix12_mdd": m_12["mdd"],
        "stlfsi_step_mdd": m_st["mdd"],
        "stlfsi_cont_mdd": m_sc["mdd"],
        "winner": winner,
    })

    print(f"  {start[:4]}-{end[:4]:>4}             {m_bh['sharpe']:>10.4f} {m_12['sharpe']:>10.4f} {m_st['sharpe']:>12.4f} {m_sc['sharpe']:>12.4f} {winner:>12}")

print(f"\n  STLFSI wins: {stlfsi_wins}/{n_periods} periods ({100*stlfsi_wins/n_periods:.0f}%)")

# ============================================================
# 7. Statistical significance: DM-like test
# ============================================================
print("\n[7/7] Statistical tests...")

# Paired t-test: STLFSI vs 12/VIX (daily return differences)
diff_step = ret_stlfsi[eval_mask] - ret_12vix[eval_mask]
diff_cont = ret_stlfsi_c[eval_mask] - ret_12vix[eval_mask]

t_step = diff_step.mean() / (diff_step.std() / np.sqrt(len(diff_step)))
t_cont = diff_cont.mean() / (diff_cont.std() / np.sqrt(len(diff_cont)))

print(f"  Paired t-test (STLFSI-Step vs 12/VIX): t = {t_step:.4f}")
print(f"  Paired t-test (STLFSI-Cont vs 12/VIX): t = {t_cont:.4f}")
print(f"  Harvey (2016) threshold: |t| > 3.0 for significance")
print(f"  Step significant? {'YES' if abs(t_step) > 3.0 else 'NO'}")
print(f"  Cont significant? {'YES' if abs(t_cont) > 3.0 else 'NO'}")

# MDD comparison
mdd_12 = metrics["12/VIX_SPY"]["mdd"]
mdd_st = metrics["STLFSI_Step_SPY"]["mdd"]
mdd_sc = metrics["STLFSI_Cont_SPY"]["mdd"]
print(f"\n  MDD comparison:")
print(f"    12/VIX:       {mdd_12:.4f}")
print(f"    STLFSI-Step:  {mdd_st:.4f} (diff: {mdd_st - mdd_12:+.4f})")
print(f"    STLFSI-Cont:  {mdd_sc:.4f} (diff: {mdd_sc - mdd_12:+.4f})")

# Regime-specific analysis
print(f"\n  Regime-specific performance (SPY strategies):")
for regime_name, regime_mask_fn in [
    ("Normal (STLFSI<0)", lambda d: d["stlfsi4"] < 0),
    ("Mild (0<=STLFSI<1)", lambda d: (d["stlfsi4"] >= 0) & (d["stlfsi4"] < 1)),
    ("Severe (STLFSI>=1)", lambda d: d["stlfsi4"] >= 1),
]:
    rmask = regime_mask_fn(data) & eval_mask
    if rmask.sum() < 50:
        print(f"    {regime_name}: insufficient data ({rmask.sum()} days)")
        continue

    bh_r = bh_ret[rmask]
    r12_r = ret_12vix[rmask]
    rst_r = ret_stlfsi[rmask]

    m_bh_r = calc_metrics(bh_r, "BH")
    m_12_r = calc_metrics(r12_r, "12/VIX")
    m_st_r = calc_metrics(rst_r, "STLFSI")

    print(f"    {regime_name} ({rmask.sum()} days):")
    print(f"      BH Sharpe:     {m_bh_r['sharpe']:.4f}, MDD: {m_bh_r['mdd']:.4f}")
    print(f"      12/VIX Sharpe: {m_12_r['sharpe']:.4f}, MDD: {m_12_r['mdd']:.4f}")
    print(f"      STLFSI Sharpe: {m_st_r['sharpe']:.4f}, MDD: {m_st_r['mdd']:.4f}")

# STLFSI4 spike dates
print(f"\n  Top 5 STLFSI4 spike periods:")
stlfsi_vals = data.loc[eval_mask, "stlfsi4"]
# Group by year-month to find peaks
monthly_max = stlfsi_vals.resample("ME").max().nlargest(5)
for date, val in monthly_max.items():
    vix_at_date = data.loc[data.index <= date, "vix_close"].iloc[-1]
    print(f"    {date.strftime('%Y-%m')}: STLFSI4 = {val:.3f}, VIX = {vix_at_date:.1f}")

# ============================================================
# Summary
# ============================================================
elapsed = time.time() - t0
print(f"\n{'='*80}")
print(f"SUMMARY")
print(f"{'='*80}")

sharpe_diff_step = metrics["STLFSI_Step_SPY"]["sharpe"] - metrics["12/VIX_SPY"]["sharpe"]
sharpe_diff_cont = metrics["STLFSI_Cont_SPY"]["sharpe"] - metrics["12/VIX_SPY"]["sharpe"]

print(f"\n  Full sample ({eval_start} to {eval_end}):")
print(f"    12/VIX:       Sharpe = {metrics['12/VIX_SPY']['sharpe']:.4f}, MDD = {metrics['12/VIX_SPY']['mdd']:.4f}")
print(f"    STLFSI-Step:  Sharpe = {metrics['STLFSI_Step_SPY']['sharpe']:.4f}, MDD = {metrics['STLFSI_Step_SPY']['mdd']:.4f}")
print(f"    STLFSI-Cont:  Sharpe = {metrics['STLFSI_Cont_SPY']['sharpe']:.4f}, MDD = {metrics['STLFSI_Cont_SPY']['mdd']:.4f}")
print(f"    Sharpe diff (Step): {sharpe_diff_step:+.4f}")
print(f"    Sharpe diff (Cont): {sharpe_diff_cont:+.4f}")

print(f"\n  Cross-OOS: STLFSI wins {stlfsi_wins}/{n_periods} periods")
print(f"  Harvey t-stat (Step): {t_step:.4f} {'✓' if abs(t_step) > 3.0 else '✗'}")
print(f"  Harvey t-stat (Cont): {t_cont:.4f} {'✓' if abs(t_cont) > 3.0 else '✗'}")

# Verdict
verdict = "NULL RESULT"
if sharpe_diff_step > 0.05 and stlfsi_wins >= n_periods * 0.6 and abs(t_step) > 3.0:
    verdict = "SIGNIFICANT IMPROVEMENT"
elif sharpe_diff_step > 0.02 and stlfsi_wins >= n_periods * 0.5:
    verdict = "MARGINAL IMPROVEMENT (not significant)"
elif sharpe_diff_step < -0.02:
    verdict = "STLFSI HURTS PERFORMANCE"
else:
    verdict = "NULL RESULT — no meaningful difference"

print(f"\n  VERDICT: {verdict}")
print(f"  Elapsed: {elapsed:.1f}s")

# ============================================================
# Save results
# ============================================================
results = {
    "experiment_id": "K504",
    "title": "FRED STLFSI4 Macro Stress Regime Strategy",
    "timestamp": datetime.now().isoformat(),
    "author": "[提出: Gemini, 執行: Claude]",
    "data_source": "yfinance (SPY, GLD, ^VIX) + FRED (STLFSI4)",
    "data_period": f"{data.index[0].date()} to {data.index[-1].date()}",
    "eval_period": f"{eval_start} to {eval_end}",
    "sample_size": int(len(data)),
    "tx_cost": "0.05% round-trip (monthly rebalancing)",
    "rf_rate": "4% annual",
    "stlfsi4_stats": {
        "mean": round(float(stlfsi.mean()), 4),
        "std": round(float(stlfsi.std()), 4),
        "min": round(float(stlfsi.min()), 4),
        "max": round(float(stlfsi.max()), 4),
        "pct_normal": round(float(100 * n_normal / total), 1),
        "pct_mild": round(float(100 * n_mild / total), 1),
        "pct_severe": round(float(100 * n_severe / total), 1),
        "corr_with_vix": round(float(corr_vix_stlfsi), 4),
    },
    "strategy_design": {
        "base": "weight = target_vol / VIX (monthly rebalancing, cap 1.5)",
        "stlfsi_step": "STLFSI4 < 0 → target=12, 0-1 → target=10, >1 → target=8",
        "stlfsi_cont": "target = 12 - 2*clip(STLFSI4, 0, 2)",
        "stlfsi_aggr": "target = 12 - 4*clip(STLFSI4, 0, 1)",
        "5050": "50% SPY (VT-managed) + 50% GLD (fixed) + cash",
    },
    "full_sample_metrics": metrics,
    "cross_oos": {
        "n_periods": n_periods,
        "stlfsi_wins": stlfsi_wins,
        "stlfsi_win_rate": round(float(stlfsi_wins / n_periods), 2) if n_periods > 0 else 0,
        "periods": oos_results,
    },
    "statistical_tests": {
        "paired_t_step": round(float(t_step), 4),
        "paired_t_cont": round(float(t_cont), 4),
        "harvey_threshold": 3.0,
        "step_significant": bool(abs(t_step) > 3.0),
        "cont_significant": bool(abs(t_cont) > 3.0),
    },
    "mdd_comparison": {
        "vix12_mdd": round(float(mdd_12), 4),
        "stlfsi_step_mdd": round(float(mdd_st), 4),
        "stlfsi_cont_mdd": round(float(mdd_sc), 4),
        "step_mdd_diff": round(float(mdd_st - mdd_12), 4),
        "cont_mdd_diff": round(float(mdd_sc - mdd_12), 4),
    },
    "verdict": verdict,
    "conclusion": "",
    "references": [
        "Kliesen, Owyang, Vermann (2012) 'Disentangling Diverse Measures' Fed StL Review",
        "Moreira & Muir (2017) 'Volatility-Managed Portfolios' JF",
        "Harvey, Liu, Zhu (2016) '...and the Cross-Section of Expected Returns' RFS",
        "Bozovic (2024) 'VIX-managed portfolios' IRFA",
    ],
    "related_knowledge": "N79 (12/VIX), N80 (19yr backtest), N105 (Harvey test), K503 (VIX mean revert)",
    "elapsed_seconds": round(elapsed, 1),
}

# Write conclusion based on verdict
if "NULL" in verdict:
    results["conclusion"] = (
        f"STLFSI4 macro stress adjustment does NOT meaningfully improve 12/VIX strategy. "
        f"Sharpe difference (Step): {sharpe_diff_step:+.4f}, t-stat: {t_step:.4f}. "
        f"Cross-OOS: STLFSI wins {stlfsi_wins}/{n_periods} periods. "
        f"MDD diff: {mdd_st - mdd_12:+.4f}. "
        f"12/VIX remains the irreducible kernel — macro regime overlay adds complexity without benefit."
    )
elif "HURTS" in verdict:
    results["conclusion"] = (
        f"STLFSI4 adjustment HURTS performance. Reducing target vol during stress periods "
        f"means missing the recovery bounce. Sharpe diff: {sharpe_diff_step:+.4f}. "
        f"12/VIX already adapts to stress via VIX itself."
    )
else:
    results["conclusion"] = (
        f"STLFSI4 shows {verdict.lower()}. Sharpe diff: {sharpe_diff_step:+.4f}, "
        f"Cross-OOS wins: {stlfsi_wins}/{n_periods}."
    )

output_path = "experiments/k504_stlfsi_strategy_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print(f"\n{'='*80}")
print("K504 COMPLETE")
print(f"{'='*80}")
