#!/usr/bin/env python3
"""
K763: Regime-Switched Carry Filter — When to Sell Vol Premium

[提出: Codex (7th suggestion), 執行: Claude]

Concept: Instead of predicting vol or timing equity, decide WHEN to harvest
the vol risk premium. VIX > realized vol ~85% of days (K430/K720). Build a
binary "admission filter" that only takes risk when structure is favorable.

Carry Signal: VRP = VIX - 22d Realized Vol
Admission Filters (all must pass):
  1. Term Structure: VIX/VIX3M < 0.95 (contango = normal carry)
  2. Momentum: VIX 5d change < 0 (VIX declining = safe)
  3. Level: VIX < 30 (no extreme fear)

Strategy:
  ALL pass → 80% SPY + 20% GLD (risk-on carry)
  ANY fail → 30% SPY + 70% GLD (defensive)
  signal.shift(1) enforced — no lookahead

Comparison: vs 12/VIX, 50/50, BH SPY

Related: K242 (VRP harvest MDD -90%), K430 (VRP OOS null), K440 (VRP VT),
K161 (term structure absorbed by VIX), K760 (alt risk premia dilution)

References:
- Carr & Wu (2009) "Variance Risk Premiums", RFS
- Todorov (2010) "Variance Risk Premium and the Forward Premium Puzzle"
- Mixon (2009) "Option Markets and Implied Volatility: Past versus Future", JBF
- Eraker (2004) "Do Stock Prices and Volatility Jump?"

Data: yfinance SPY/GLD/^VIX/^VIX3M, 2008-2026
"""

import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("=" * 70)
print("K763: Regime-Switched Carry Filter")
print("=" * 70)

tickers = ["SPY", "GLD", "^VIX", "^VIX3M"]
start = "2006-01-01"
end = "2026-03-30"

print(f"\nDownloading {tickers} from {start} to {end}...")
raw = yf.download(tickers, start=start, end=end, auto_adjust=True)

# Extract close prices
close = raw["Close"].copy()
close.columns = [c if isinstance(c, str) else c for c in close.columns]
# Standardize column names
col_map = {"SPY": "SPY", "GLD": "GLD", "^VIX": "VIX", "^VIX3M": "VIX3M"}
close = close.rename(columns=col_map)

# Forward-fill VIX3M (may have some gaps)
close["VIX3M"] = close["VIX3M"].ffill()
close = close.dropna()

print(f"Data shape: {close.shape}, date range: {close.index[0].date()} to {close.index[-1].date()}")

# Simple returns
ret_spy = close["SPY"].pct_change()
ret_gld = close["GLD"].pct_change()

# ============================================================
# 2. CONSTRUCT SIGNALS
# ============================================================

# Realized volatility (22-day annualized)
log_ret_spy = np.log(close["SPY"] / close["SPY"].shift(1))
rv_22d = log_ret_spy.rolling(22).std() * np.sqrt(252) * 100  # in % terms

# VRP = VIX - RV22d (both in %)
vrp = close["VIX"] - rv_22d

# Term structure ratio
ts_ratio = close["VIX"] / close["VIX3M"]

# VIX 5-day change
vix_5d_change = close["VIX"] - close["VIX"].shift(5)

# VIX level
vix_level = close["VIX"]

# ============================================================
# 3. ADMISSION FILTERS
# ============================================================

# Filter 1: Term Structure — contango (VIX/VIX3M < 0.95)
f_term = ts_ratio < 0.95

# Filter 2: Momentum — VIX declining (5d change < 0)
f_momentum = vix_5d_change < 0

# Filter 3: Level — VIX < 30
f_level = vix_level < 30

# Combined: ALL must pass
all_pass = f_term & f_momentum & f_level

# ============================================================
# 4. DESCRIPTIVE STATISTICS
# ============================================================
print("\n" + "=" * 70)
print("DESCRIPTIVE STATISTICS")
print("=" * 70)

# Start from where all signals available
valid = close.index[close.index >= close.index[26]]  # after 22d rv warmup + 5d
mask = all_pass.loc[valid].notna()
valid_dates = valid[mask.loc[valid].values]

print(f"\nTotal trading days: {len(valid_dates)}")
print(f"VRP mean: {vrp.loc[valid_dates].mean():.2f}%")
print(f"VRP > 0 pct: {(vrp.loc[valid_dates] > 0).mean()*100:.1f}%")
print(f"\nTerm structure ratio (VIX/VIX3M):")
print(f"  Mean: {ts_ratio.loc[valid_dates].mean():.3f}")
print(f"  Contango (< 0.95): {(ts_ratio.loc[valid_dates] < 0.95).mean()*100:.1f}%")
print(f"  Backwardation (> 1.0): {(ts_ratio.loc[valid_dates] > 1.0).mean()*100:.1f}%")
print(f"\nVIX 5d change:")
print(f"  Mean: {vix_5d_change.loc[valid_dates].mean():.3f}")
print(f"  Declining pct: {(vix_5d_change.loc[valid_dates] < 0).mean()*100:.1f}%")
print(f"\nVIX level:")
print(f"  Mean: {vix_level.loc[valid_dates].mean():.1f}")
print(f"  < 30 pct: {(vix_level.loc[valid_dates] < 30).mean()*100:.1f}%")
print(f"\nALL filters pass: {all_pass.loc[valid_dates].sum()} days ({all_pass.loc[valid_dates].mean()*100:.1f}%)")
print(f"ANY filter fails: {(~all_pass.loc[valid_dates]).sum()} days ({(~all_pass.loc[valid_dates]).mean()*100:.1f}%)")

# Individual filter fail rates
print(f"\nFilter fail rates (when others pass):")
print(f"  Term structure alone fails: {(~f_term.loc[valid_dates]).mean()*100:.1f}%")
print(f"  Momentum alone fails: {(~f_momentum.loc[valid_dates]).mean()*100:.1f}%")
print(f"  Level alone fails: {(~f_level.loc[valid_dates]).mean()*100:.1f}%")

# VRP conditional on filter
vrp_pass = vrp.loc[valid_dates][all_pass.loc[valid_dates]].mean()
vrp_fail = vrp.loc[valid_dates][~all_pass.loc[valid_dates]].mean()
print(f"\nVRP when ALL pass: {vrp_pass:.2f}%")
print(f"VRP when ANY fail: {vrp_fail:.2f}%")

# Next-day SPY return conditional on filter
next_ret = ret_spy.shift(-1)
ret_pass = next_ret.loc[valid_dates][all_pass.loc[valid_dates]]
ret_fail = next_ret.loc[valid_dates][~all_pass.loc[valid_dates]]
print(f"\nNext-day SPY return when ALL pass: {ret_pass.mean()*252*100:.1f}% ann")
print(f"Next-day SPY return when ANY fail: {ret_fail.mean()*252*100:.1f}% ann")
t_diff, p_diff = stats.ttest_ind(ret_pass.dropna(), ret_fail.dropna())
print(f"  t-stat: {t_diff:.2f}, p-value: {p_diff:.4f}")

# ============================================================
# 5. STRATEGY CONSTRUCTION
# ============================================================
print("\n" + "=" * 70)
print("STRATEGY CONSTRUCTION")
print("=" * 70)

# === CRITICAL: signal.shift(1) — no lookahead ===
signal = all_pass.shift(1)  # Use YESTERDAY's filter for TODAY's allocation

# Weights
w_spy_carry = signal.apply(lambda x: 0.80 if x else 0.30)
w_gld_carry = 1.0 - w_spy_carry

# 12/VIX strategy (benchmark)
w_spy_12vix = (12.0 / close["VIX"]).clip(0.0, 1.0).shift(1)
w_gld_12vix = 1.0 - w_spy_12vix

# 50/50 static
w_spy_5050 = 0.5
w_gld_5050 = 0.5

# BH SPY
w_spy_bh = 1.0
w_gld_bh = 0.0

# Transaction costs: 5bps per leg
TX_COST = 0.0005

def compute_strategy(w_spy, w_gld, ret_spy, ret_gld, name, tx_cost=TX_COST):
    """Compute strategy returns with TX costs."""
    if isinstance(w_spy, (int, float)):
        w_spy = pd.Series(w_spy, index=ret_spy.index)
        w_gld = pd.Series(w_gld, index=ret_spy.index)

    # Portfolio return
    port_ret = w_spy * ret_spy + w_gld * ret_gld

    # TX costs: sum of absolute weight changes × tx_cost
    dw_spy = w_spy.diff().abs()
    dw_gld = w_gld.diff().abs()
    tx = (dw_spy + dw_gld) * tx_cost
    tx = tx.fillna(0)

    net_ret = port_ret - tx

    return net_ret, tx

# Compute all strategies
strats = {}
for name, ws, wg in [
    ("Carry Filter", w_spy_carry, w_gld_carry),
    ("12/VIX", w_spy_12vix, w_gld_12vix),
    ("50/50", w_spy_5050, w_gld_5050),
    ("BH SPY", w_spy_bh, w_gld_bh),
]:
    net_ret, tx = compute_strategy(ws, wg, ret_spy, ret_gld, name)
    strats[name] = {"net_ret": net_ret, "tx": tx, "w_spy": ws if isinstance(ws, pd.Series) else pd.Series(ws, index=ret_spy.index)}

# ============================================================
# 6. FULL SAMPLE METRICS
# ============================================================
print("\n" + "=" * 70)
print("FULL SAMPLE METRICS (2008-2026)")
print("=" * 70)

# Use common start after warmup
common_start = "2008-01-01"
common_end = close.index[-1]

def calc_metrics(returns, name, start_date=common_start):
    """Calculate performance metrics."""
    r = returns.loc[start_date:].dropna()
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0
    downside_vol = r[r < 0].std() * np.sqrt(252) if (r < 0).sum() > 0 else ann_vol
    sortino = ann_ret / downside_vol if downside_vol > 0 else 0
    return {
        "name": name,
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "sortino": float(sortino),
        "n_days": len(r),
    }

metrics_full = {}
for name, data in strats.items():
    m = calc_metrics(data["net_ret"], name)
    metrics_full[name] = m
    print(f"\n{name}:")
    print(f"  Ann Return: {m['ann_return']*100:.1f}%")
    print(f"  Ann Vol:    {m['ann_vol']*100:.1f}%")
    print(f"  Sharpe:     {m['sharpe']:.3f}")
    print(f"  MDD:        {m['mdd']*100:.1f}%")
    print(f"  Calmar:     {m['calmar']:.3f}")
    print(f"  Sortino:    {m['sortino']:.3f}")
    print(f"  N days:     {m['n_days']}")

# TX cost summary
print(f"\nTransaction Cost Summary:")
for name, data in strats.items():
    tx_total = data["tx"].loc[common_start:].sum()
    turnover = data["tx"].loc[common_start:].mean() * 252 / TX_COST if TX_COST > 0 else 0
    print(f"  {name}: total TX drag {tx_total*100:.2f}%, ann turnover {turnover:.1f} turns/yr")

# Carry filter specific stats
print(f"\nCarry Filter regime breakdown:")
sig = signal.loc[common_start:]
print(f"  Risk-on days: {sig.sum():.0f} ({sig.mean()*100:.1f}%)")
print(f"  Defensive days: {(~sig).sum():.0f} ({(~sig).mean()*100:.1f}%)")

# Average SPY weight
w_avg = strats["Carry Filter"]["w_spy"].loc[common_start:].mean()
print(f"  Average SPY weight: {w_avg*100:.1f}%")
w_12vix_avg = strats["12/VIX"]["w_spy"].loc[common_start:].mean()
print(f"  12/VIX average SPY weight: {w_12vix_avg*100:.1f}%")

# ============================================================
# 7. DIEBOLD-MARIANO TESTS
# ============================================================
print("\n" + "=" * 70)
print("DIEBOLD-MARIANO TESTS (vs 12/VIX)")
print("=" * 70)

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Using squared error loss (negative returns = loss)."""
    d = e1**2 - e2**2
    d = d.dropna()
    n = len(d)
    d_mean = d.mean()
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = d.var()
    gamma_sum = 0
    for k in range(1, h):
        gamma_sum += d.iloc[k:].reset_index(drop=True).cov(d.iloc[:-k].reset_index(drop=True))
    var_d = (gamma0 + 2 * gamma_sum) / n
    if var_d <= 0:
        return 0, 1.0
    dm_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)

ref = strats["12/VIX"]["net_ret"].loc[common_start:].dropna()
for name in ["Carry Filter", "50/50", "BH SPY"]:
    test = strats[name]["net_ret"].loc[common_start:].dropna()
    common_idx = ref.index.intersection(test.index)
    dm_stat, dm_p = dm_test(test.loc[common_idx], ref.loc[common_idx])
    print(f"  {name} vs 12/VIX: DM stat={dm_stat:.3f}, p={dm_p:.4f} {'***' if dm_p < 0.01 else '**' if dm_p < 0.05 else '*' if dm_p < 0.10 else 'NS'}")

# ============================================================
# 8. CROSS-OOS VALIDATION (5 periods)
# ============================================================
print("\n" + "=" * 70)
print("CROSS-OOS VALIDATION (5 non-overlapping 2yr periods)")
print("=" * 70)

oos_periods = [
    ("2008-01-01", "2009-12-31"),  # GFC
    ("2012-01-01", "2013-12-31"),  # Post-GFC recovery
    ("2016-01-01", "2017-12-31"),  # Low vol era
    ("2020-01-01", "2021-12-31"),  # COVID
    ("2022-01-01", "2023-12-31"),  # Rate hike + recovery
]

oos_results = []
for i, (s, e) in enumerate(oos_periods):
    print(f"\nPeriod {i+1}: {s} to {e}")
    period_metrics = {}
    for name, data in strats.items():
        m = calc_metrics(data["net_ret"], name, start_date=s)
        # Recalculate with end date
        r = data["net_ret"].loc[s:e].dropna()
        if len(r) < 50:
            print(f"  {name}: insufficient data ({len(r)} days)")
            continue
        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + r).cumprod()
        mdd = (cum / cum.cummax() - 1).min()
        period_metrics[name] = {"sharpe": float(sharpe), "mdd": float(mdd), "ann_ret": float(ann_ret), "n": len(r)}
        print(f"  {name}: Sharpe={sharpe:.3f}, MDD={mdd*100:.1f}%, AnnRet={ann_ret*100:.1f}%")

    oos_results.append({"period": f"{s} to {e}", "metrics": period_metrics})

# Cross-OOS wins vs 50/50 and 12/VIX
print("\nCross-OOS Wins:")
carry_wins_vs_5050 = 0
carry_wins_vs_12vix = 0
for res in oos_results:
    m = res["metrics"]
    if "Carry Filter" in m and "50/50" in m:
        if m["Carry Filter"]["sharpe"] > m["50/50"]["sharpe"]:
            carry_wins_vs_5050 += 1
    if "Carry Filter" in m and "12/VIX" in m:
        if m["Carry Filter"]["sharpe"] > m["12/VIX"]["sharpe"]:
            carry_wins_vs_12vix += 1

print(f"  Carry Filter vs 50/50: {carry_wins_vs_5050}/5")
print(f"  Carry Filter vs 12/VIX: {carry_wins_vs_12vix}/5")

# ============================================================
# 9. SENSITIVITY ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("SENSITIVITY ANALYSIS")
print("=" * 70)

# Vary thresholds ±20%
sensitivity_configs = {
    "Base": {"ts_thresh": 0.95, "vix_max": 30, "risk_on_spy": 0.80, "def_spy": 0.30},
    "TS loose (1.00)": {"ts_thresh": 1.00, "vix_max": 30, "risk_on_spy": 0.80, "def_spy": 0.30},
    "TS tight (0.90)": {"ts_thresh": 0.90, "vix_max": 30, "risk_on_spy": 0.80, "def_spy": 0.30},
    "VIX max 25": {"ts_thresh": 0.95, "vix_max": 25, "risk_on_spy": 0.80, "def_spy": 0.30},
    "VIX max 35": {"ts_thresh": 0.95, "vix_max": 35, "risk_on_spy": 0.80, "def_spy": 0.30},
    "Aggressive (90/10)": {"ts_thresh": 0.95, "vix_max": 30, "risk_on_spy": 0.90, "def_spy": 0.10},
    "Conservative (70/30 vs 40/60)": {"ts_thresh": 0.95, "vix_max": 30, "risk_on_spy": 0.70, "def_spy": 0.40},
}

sensitivity_results = {}
for config_name, params in sensitivity_configs.items():
    sig_s = (ts_ratio < params["ts_thresh"]) & (vix_5d_change < 0) & (vix_level < params["vix_max"])
    sig_s = sig_s.shift(1)  # CRITICAL: lag

    ws = sig_s.apply(lambda x: params["risk_on_spy"] if x else params["def_spy"])
    wg = 1.0 - ws

    net_r, _ = compute_strategy(ws, wg, ret_spy, ret_gld, config_name)
    m = calc_metrics(net_r, config_name)
    sensitivity_results[config_name] = m
    pct_on = sig_s.loc[common_start:].mean() * 100
    print(f"  {config_name}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']*100:.1f}%, Risk-on={pct_on:.0f}%")

base_sharpe = sensitivity_results["Base"]["sharpe"]
print(f"\n  Sharpe sensitivity range: {min(s['sharpe'] for s in sensitivity_results.values()):.3f} to {max(s['sharpe'] for s in sensitivity_results.values()):.3f}")
print(f"  Base Sharpe: {base_sharpe:.3f}")
max_drop = min((s['sharpe'] - base_sharpe) / base_sharpe * 100 for s in sensitivity_results.values() if s['sharpe'] != base_sharpe)
print(f"  Max Sharpe drop from ±20% param change: {max_drop:.1f}%")

# ============================================================
# 10. COMMON_START PERIOD (2023-2026) FOR LISTING COMPARISON
# ============================================================
print("\n" + "=" * 70)
print("COMMON_START PERIOD (2023-01-04 to present)")
print("=" * 70)

cs = "2023-01-04"
for name, data in strats.items():
    m = calc_metrics(data["net_ret"], name, start_date=cs)
    print(f"  {name}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']*100:.1f}%, AnnRet={m['ann_return']*100:.1f}%")

# ============================================================
# 11. INDIVIDUAL FILTER CONTRIBUTION (ABLATION)
# ============================================================
print("\n" + "=" * 70)
print("FILTER ABLATION (remove one filter at a time)")
print("=" * 70)

ablation_configs = {
    "All 3 filters": (f_term, f_momentum, f_level),
    "No term structure": (pd.Series(True, index=close.index), f_momentum, f_level),
    "No momentum": (f_term, pd.Series(True, index=close.index), f_level),
    "No level": (f_term, f_momentum, pd.Series(True, index=close.index)),
    "Only term structure": (f_term, pd.Series(True, index=close.index), pd.Series(True, index=close.index)),
    "Only momentum": (pd.Series(True, index=close.index), f_momentum, pd.Series(True, index=close.index)),
    "Only level": (pd.Series(True, index=close.index), pd.Series(True, index=close.index), f_level),
}

ablation_results = {}
for abl_name, (fa, fb, fc) in ablation_configs.items():
    combined = fa & fb & fc
    sig_a = combined.shift(1)
    ws_a = sig_a.apply(lambda x: 0.80 if x else 0.30)
    wg_a = 1.0 - ws_a
    net_r, _ = compute_strategy(ws_a, wg_a, ret_spy, ret_gld, abl_name)
    m = calc_metrics(net_r, abl_name)
    pct_on = sig_a.loc[common_start:].mean() * 100
    ablation_results[abl_name] = {**m, "pct_risk_on": float(pct_on)}
    print(f"  {abl_name}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']*100:.1f}%, Risk-on={pct_on:.0f}%")

# ============================================================
# 12. REGIME ANALYSIS (What happens in each filter state)
# ============================================================
print("\n" + "=" * 70)
print("REGIME ANALYSIS")
print("=" * 70)

sig_shifted = signal.loc[common_start:].dropna()
r_spy = ret_spy.loc[common_start:].dropna()
common_idx2 = sig_shifted.index.intersection(r_spy.index)

for state, label in [(True, "Risk-On (all pass)"), (False, "Defensive (any fail)")]:
    mask_state = sig_shifted.loc[common_idx2] == state
    r_state = r_spy.loc[common_idx2][mask_state]
    n = len(r_state)
    ann = r_state.mean() * 252
    vol = r_state.std() * np.sqrt(252)
    sr = ann / vol if vol > 0 else 0
    print(f"\n{label} ({n} days, {n/len(common_idx2)*100:.1f}%):")
    print(f"  SPY Ann Return: {ann*100:.1f}%")
    print(f"  SPY Ann Vol:    {vol*100:.1f}%")
    print(f"  SPY Sharpe:     {sr:.3f}")

# Check: which filter is doing the most work?
print("\nFilter correlation matrix:")
filters_df = pd.DataFrame({
    "term_pass": f_term.loc[common_start:].astype(float),
    "momentum_pass": f_momentum.loc[common_start:].astype(float),
    "level_pass": f_level.loc[common_start:].astype(float),
}).dropna()
print(filters_df.corr().round(3).to_string())

# ============================================================
# 13. CARRY FILTER vs SIMPLE VIX THRESHOLD
# ============================================================
print("\n" + "=" * 70)
print("CARRY FILTER vs SIMPLE VIX THRESHOLD")
print("=" * 70)

# Simple VIX < 20 threshold (for comparison)
simple_sig = (vix_level < 20).shift(1)
ws_simple = simple_sig.apply(lambda x: 0.80 if x else 0.30)
wg_simple = 1.0 - ws_simple
net_simple, _ = compute_strategy(ws_simple, wg_simple, ret_spy, ret_gld, "Simple VIX<20")
m_simple = calc_metrics(net_simple, "Simple VIX<20")
print(f"  Simple VIX<20: Sharpe={m_simple['sharpe']:.3f}, MDD={m_simple['mdd']*100:.1f}%")
print(f"  Carry Filter:  Sharpe={metrics_full['Carry Filter']['sharpe']:.3f}, MDD={metrics_full['Carry Filter']['mdd']*100:.1f}%")
print(f"  12/VIX:        Sharpe={metrics_full['12/VIX']['sharpe']:.3f}, MDD={metrics_full['12/VIX']['mdd']*100:.1f}%")

# ============================================================
# 14. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY & CONCLUSIONS")
print("=" * 70)

carry_sharpe = metrics_full["Carry Filter"]["sharpe"]
vix12_sharpe = metrics_full["12/VIX"]["sharpe"]
fifty_sharpe = metrics_full["50/50"]["sharpe"]
bh_sharpe = metrics_full["BH SPY"]["sharpe"]

print(f"""
Strategy Rankings (Full Sample {common_start} to {common_end.date()}):
  1. {'Carry Filter' if carry_sharpe >= max(vix12_sharpe, fifty_sharpe) else '12/VIX' if vix12_sharpe >= fifty_sharpe else '50/50'}: Sharpe {max(carry_sharpe, vix12_sharpe, fifty_sharpe):.3f}
  2. ...

Carry Filter Sharpe: {carry_sharpe:.3f}
12/VIX Sharpe:       {vix12_sharpe:.3f}
50/50 Sharpe:        {fifty_sharpe:.3f}
BH SPY Sharpe:       {bh_sharpe:.3f}

Cross-OOS vs 50/50: {carry_wins_vs_5050}/5
Cross-OOS vs 12/VIX: {carry_wins_vs_12vix}/5

Key Insights:
- Binary admission filter: {all_pass.loc[common_start:].mean()*100:.0f}% risk-on vs {(~all_pass.loc[common_start:]).mean()*100:.0f}% defensive
- vs 12/VIX smooth weights: Carry Filter is a discrete switch (0.80/0.30)
- Term structure filter adds complexity but VIX level is the dominant filter (K161)
""")

# ============================================================
# 15. SAVE RESULTS
# ============================================================
results = {
    "experiment_id": "K763",
    "title": "Regime-Switched Carry Filter — When to Sell Vol Premium",
    "proposer": "Codex (7th suggestion)",
    "executor": "Claude",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance SPY/GLD/^VIX/^VIX3M",
    "data_period": f"{close.index[0].date()} to {close.index[-1].date()}",
    "sample_size": int(len(close)),
    "methodology": {
        "concept": "Binary admission filter for vol risk premium harvesting",
        "filters": {
            "term_structure": "VIX/VIX3M < 0.95 (contango)",
            "momentum": "VIX 5d change < 0 (declining)",
            "level": "VIX < 30 (no extreme fear)"
        },
        "allocations": {
            "risk_on": "80% SPY + 20% GLD (all filters pass)",
            "defensive": "30% SPY + 70% GLD (any filter fails)"
        },
        "lag": "signal.shift(1) — no lookahead",
        "tx_cost": "5bps per leg on weight changes"
    },
    "descriptive_stats": {
        "vrp_mean_pct": float(vrp.loc[valid_dates].mean()),
        "vrp_positive_pct": float((vrp.loc[valid_dates] > 0).mean() * 100),
        "contango_pct": float((ts_ratio.loc[valid_dates] < 0.95).mean() * 100),
        "vix_declining_pct": float((vix_5d_change.loc[valid_dates] < 0).mean() * 100),
        "vix_under30_pct": float((vix_level.loc[valid_dates] < 30).mean() * 100),
        "all_pass_pct": float(all_pass.loc[valid_dates].mean() * 100),
        "vrp_when_pass": float(vrp_pass),
        "vrp_when_fail": float(vrp_fail),
        "spy_ann_ret_when_pass": float(ret_pass.mean() * 252),
        "spy_ann_ret_when_fail": float(ret_fail.mean() * 252),
        "return_diff_tstat": float(t_diff),
        "return_diff_pvalue": float(p_diff),
    },
    "full_sample_metrics": metrics_full,
    "cross_oos": {
        "periods": oos_results,
        "carry_vs_5050_wins": f"{carry_wins_vs_5050}/5",
        "carry_vs_12vix_wins": f"{carry_wins_vs_12vix}/5",
    },
    "sensitivity": sensitivity_results,
    "ablation": ablation_results,
    "simple_vix_threshold_comparison": {
        "simple_vix_lt20_sharpe": float(m_simple["sharpe"]),
        "carry_filter_sharpe": float(carry_sharpe),
        "twelve_vix_sharpe": float(vix12_sharpe),
    },
    "conclusions": [],
    "references": [
        "Carr & Wu (2009) Variance Risk Premiums, RFS",
        "Todorov (2010) Variance Risk Premium and Forward Premium Puzzle",
        "Mixon (2009) Option Markets and Implied Volatility, JBF",
        "Related: K242 (VRP harvest MDD -90%), K430 (VRP OOS null), K440 (VRP VT), K161 (TS absorbed by VIX), K760 (alt risk premia dilution)",
    ]
}

# Determine conclusions dynamically
conclusions = []

if carry_sharpe > vix12_sharpe:
    conclusions.append(f"Carry Filter (Sharpe {carry_sharpe:.3f}) OUTPERFORMS 12/VIX ({vix12_sharpe:.3f})")
elif abs(carry_sharpe - vix12_sharpe) < 0.05:
    conclusions.append(f"Carry Filter (Sharpe {carry_sharpe:.3f}) roughly MATCHES 12/VIX ({vix12_sharpe:.3f})")
else:
    conclusions.append(f"Carry Filter (Sharpe {carry_sharpe:.3f}) UNDERPERFORMS 12/VIX ({vix12_sharpe:.3f})")

if carry_wins_vs_5050 >= 3:
    conclusions.append(f"Cross-OOS: passes vs 50/50 ({carry_wins_vs_5050}/5)")
else:
    conclusions.append(f"Cross-OOS: fails vs 50/50 ({carry_wins_vs_5050}/5)")

if carry_wins_vs_12vix >= 3:
    conclusions.append(f"Cross-OOS: passes vs 12/VIX ({carry_wins_vs_12vix}/5)")
else:
    conclusions.append(f"Cross-OOS: fails vs 12/VIX ({carry_wins_vs_12vix}/5)")

# Ablation insight
best_single = max(
    [(k, v["sharpe"]) for k, v in ablation_results.items() if k.startswith("Only")],
    key=lambda x: x[1]
)
conclusions.append(f"Best single filter: {best_single[0]} (Sharpe {best_single[1]:.3f}) — combining filters {'helps' if carry_sharpe > best_single[1] else 'does not help'}")

conclusions.append(f"Binary switch (80/30) vs continuous 12/VIX: discrete regime change {'outperforms' if carry_sharpe > vix12_sharpe else 'underperforms'} smooth weighting")

if abs(carry_sharpe - m_simple["sharpe"]) < 0.03:
    conclusions.append(f"Term structure + momentum add NO value over simple VIX<20 threshold (Sharpe diff {carry_sharpe - m_simple['sharpe']:.3f})")

results["conclusions"] = conclusions

# Save
output_path = "experiments/k763_regime_carry_filter_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("\nConclusions:")
for i, c in enumerate(conclusions, 1):
    print(f"  {i}. {c}")

print("\nDone.")
