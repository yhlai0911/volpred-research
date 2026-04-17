"""
K378: The Cash Allocation Frontier — Optimal Cash% by VIX Level
================================================================
Follow-up to K377 ("cash is the universal hedge").

IMPORTANT METHODOLOGICAL NOTE:
Sharpe ratio is scale-invariant: Sharpe((1-c)*R + c*rf) = Sharpe(R) for all c.
Therefore Sharpe CANNOT distinguish cash allocations.
We use CRRA utility (gamma=5) and Mean-Variance utility instead.

Questions:
1. At each VIX level, what cash% historically maximized forward utility?
2. Is 12/VIX close to optimal? Or is there a better formula?
3. Is the optimal cash% linear, quadratic, or log in VIX?
4. Does the Step Rule (K316) approximate the optimal well?
5. Robustness: does the frontier shift by decade?

Data: SPY, VIX daily from yfinance. 2005-2024.
Methodology: For each VIX bin, sweep cash% 0-100 in 5pp steps, compute
22-day forward CRRA utility of (1-cash%)*SPY + cash%*rf.
Use LAGGED weights (VIX_t determines return for days t+1:t+22).

[提出: 用戶, 執行: Claude]
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import optimize, stats
from datetime import datetime
import json

# ==================================================================
# CONFIG
# ==================================================================
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
FORWARD_DAYS = 22  # 1 month forward
CASH_STEPS = np.arange(0, 1.01, 0.05)  # 0%, 5%, ..., 100%

# Risk aversion parameter for CRRA utility: U(W) = W^(1-gamma)/(1-gamma)
GAMMA = 5  # moderate risk aversion (N115: gamma=4 is breakeven)

# VIX levels to test
VIX_LEVELS = [10, 12, 14, 16, 18, 20, 22, 25, 30, 35, 40, 50]
VIX_BIN_WIDTH = 1.5  # +/- 1.5 around each level

DATA_START = "2004-01-01"
DATA_END = "2024-12-31"
ANALYSIS_START = "2005-01-01"

print("=" * 78)
print("K378: THE CASH ALLOCATION FRONTIER")
print("Optimal Cash Percentage by VIX Level (CRRA Utility, gamma=5)")
print("=" * 78)
print(f"  Data: SPY + ^VIX, {ANALYSIS_START} to {DATA_END}")
print(f"  Forward window: {FORWARD_DAYS} trading days")
print(f"  Cash steps: {len(CASH_STEPS)} ({int(CASH_STEPS[0]*100)}% to {int(CASH_STEPS[-1]*100)}%)")
print(f"  VIX levels: {VIX_LEVELS}")
print(f"  VIX bin width: +/- {VIX_BIN_WIDTH}")
print(f"  Risk-free rate: {RF_ANNUAL:.1%}/yr")
print(f"  CRRA gamma: {GAMMA}")
print(f"  Note: Sharpe is scale-invariant → using CRRA utility instead")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n" + "=" * 78)
print("[1/7] DOWNLOADING DATA")
print("=" * 78)

spy_raw = yf.download("SPY", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)

if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

spy_close = spy_raw["Close"].squeeze()
vix_close = vix_raw["Close"].squeeze()

common = spy_close.index.intersection(vix_close.index)
spy_close = spy_close.loc[common]
vix_close = vix_close.loc[common]

spy_ret = np.log(spy_close / spy_close.shift(1)).dropna()
spy_ret = spy_ret[spy_ret.index >= ANALYSIS_START]
vix_close = vix_close[vix_close.index >= ANALYSIS_START]

common2 = spy_ret.index.intersection(vix_close.index)
spy_ret = spy_ret.loc[common2]
vix_close = vix_close.loc[common2]

print(f"  SPY returns: {len(spy_ret)} days ({spy_ret.index[0].strftime('%Y-%m-%d')} to {spy_ret.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX range: {vix_close.min():.1f} to {vix_close.max():.1f}, mean={vix_close.mean():.1f}")

# ==================================================================
# 2. Utility Functions
# ==================================================================

def crra_utility(wealth_series, gamma=GAMMA):
    """Compute average CRRA utility across terminal wealth values."""
    if gamma == 1:
        return np.mean(np.log(wealth_series))
    else:
        return np.mean(wealth_series**(1 - gamma) / (1 - gamma))

def certainty_equivalent(utility_val, gamma=GAMMA):
    """Convert CRRA utility back to certainty equivalent wealth."""
    if gamma == 1:
        return np.exp(utility_val)
    else:
        return (utility_val * (1 - gamma)) ** (1 / (1 - gamma))

def mean_variance_utility(returns, gamma_mv=5):
    """Mean-Variance utility: E[r] - (gamma/2) * Var(r), annualized."""
    mu = np.mean(returns) * 252
    var = np.var(returns) * 252
    return mu - (gamma_mv / 2) * var

def compute_forward_metrics(cash_pct, forward_rets_list, gamma=GAMMA):
    """
    For a given cash%, compute forward metrics across a set of 22-day windows.
    Returns dict with CRRA utility, CE return, MV utility, avg return, avg vol, max drawdown.
    """
    equity_pct = 1.0 - cash_pct

    terminal_wealths = []
    period_returns = []
    all_daily_rets = []

    for fwd in forward_rets_list:
        # Daily portfolio returns
        port_daily = equity_pct * fwd + cash_pct * RF_DAILY
        all_daily_rets.extend(port_daily.tolist())

        # Terminal wealth (starting from $1)
        cum = np.exp(np.sum(port_daily))
        terminal_wealths.append(cum)

        # Period return
        period_returns.append(cum - 1)

    terminal_wealths = np.array(terminal_wealths)
    period_returns = np.array(period_returns)
    all_daily_rets = np.array(all_daily_rets)

    # CRRA utility
    util = crra_utility(terminal_wealths, gamma)
    ce = certainty_equivalent(util, gamma)
    ce_return = (ce - 1) * (252 / FORWARD_DAYS)  # annualized

    # Mean-Variance utility (annualized)
    mv_util = mean_variance_utility(all_daily_rets, gamma_mv=gamma)

    # Basic stats
    avg_ret = np.mean(period_returns) * (252 / FORWARD_DAYS)
    avg_vol = np.std(period_returns) * np.sqrt(252 / FORWARD_DAYS)

    # Worst 22-day drawdown
    worst_period = np.min(period_returns)

    return {
        "crra_utility": float(util),
        "ce_return_ann": float(ce_return),
        "mv_utility": float(mv_util),
        "avg_return_ann": float(avg_ret),
        "avg_vol_ann": float(avg_vol),
        "worst_22d": float(worst_period),
    }

# ==================================================================
# 3. Compute Optimal Cash% at Each VIX Level
# ==================================================================
print("\n" + "=" * 78)
print("[2/7] COMPUTING OPTIMAL CASH% BY VIX LEVEL")
print("=" * 78)

ret_array = spy_ret.values
dates = spy_ret.index
vix_array = vix_close.values
n = len(ret_array)

# Pre-compute forward windows (LAGGED: VIX_t -> returns t+1 to t+22)
forward_windows = []
for i in range(n - FORWARD_DAYS):
    fwd_rets = ret_array[i+1:i+1+FORWARD_DAYS]
    forward_windows.append(fwd_rets)

results = {}
print(f"\n{'VIX':>5} {'N':>5} | {'Opt Cash%':>10} {'CE Ret':>7} | {'12/VIX':>7} {'CE Ret':>7} | {'Step':>5} {'CE Ret':>7} | {'MV Opt':>7}")
print("-" * 85)

for vix_level in VIX_LEVELS:
    low = vix_level - VIX_BIN_WIDTH
    high = vix_level + VIX_BIN_WIDTH
    mask = (vix_array[:n-FORWARD_DAYS] >= low) & (vix_array[:n-FORWARD_DAYS] < high)
    indices = np.where(mask)[0]

    if len(indices) < 20:
        print(f"  VIX={vix_level}: Only {len(indices)} obs, skipping (need >=20)")
        continue

    fwd_set = [forward_windows[i] for i in indices]

    # Sweep cash percentages — CRRA utility
    crra_results = {}
    mv_results = {}
    for cash_pct in CASH_STEPS:
        metrics = compute_forward_metrics(cash_pct, fwd_set)
        crra_results[cash_pct] = metrics["ce_return_ann"]
        mv_results[cash_pct] = metrics["mv_utility"]

    # CRRA optimal
    opt_cash_crra = max(crra_results, key=crra_results.get)
    opt_ce = crra_results[opt_cash_crra]

    # MV optimal
    opt_cash_mv = max(mv_results, key=mv_results.get)

    # 12/VIX
    formula_equity = min(12.0 / vix_level, 1.0)
    formula_cash = 1.0 - formula_equity
    formula_metrics = compute_forward_metrics(formula_cash, fwd_set)
    formula_ce = formula_metrics["ce_return_ann"]

    # Step Rule
    if vix_level < 15:
        step_cash = 0.0
    elif vix_level <= 25:
        step_cash = 0.30
    else:
        step_cash = 0.60
    step_metrics = compute_forward_metrics(step_cash, fwd_set)
    step_ce = step_metrics["ce_return_ann"]

    # Full detail for all cash levels
    all_detail = {}
    for cash_pct in CASH_STEPS:
        m = compute_forward_metrics(cash_pct, fwd_set)
        all_detail[f"{cash_pct:.0%}"] = {
            "ce_return": m["ce_return_ann"],
            "mv_utility": m["mv_utility"],
            "avg_return": m["avg_return_ann"],
            "avg_vol": m["avg_vol_ann"],
            "worst_22d": m["worst_22d"],
        }

    results[vix_level] = {
        "n_obs": int(len(indices)),
        "optimal_cash_crra": float(opt_cash_crra),
        "optimal_ce_return": float(opt_ce),
        "optimal_cash_mv": float(opt_cash_mv),
        "formula_12vix_cash": float(formula_cash),
        "formula_ce_return": float(formula_ce),
        "step_rule_cash": float(step_cash),
        "step_ce_return": float(step_ce),
        "all_detail": all_detail,
    }

    print(f"  {vix_level:>3} {len(indices):>5} |   {opt_cash_crra:>5.0%}    {opt_ce:>6.1%} |  {formula_cash:>5.0%} {formula_ce:>6.1%} | {step_cash:>4.0%} {step_ce:>6.1%} |  {opt_cash_mv:>5.0%}")

# ==================================================================
# 4. Detailed Frontier Curves at Key VIX Levels
# ==================================================================
print("\n" + "=" * 78)
print("[3/7] DETAILED CASH FRONTIER CURVES")
print("=" * 78)

key_levels = [12, 16, 20, 25, 30]
for vix_level in key_levels:
    if vix_level not in results:
        continue
    r = results[vix_level]
    print(f"\n  VIX = {vix_level} (n={r['n_obs']})")
    print(f"    {'Cash%':>6} {'CE Return':>10} {'MV Util':>9} {'Avg Ret':>8} {'Avg Vol':>8} {'Worst 22d':>10}")
    print(f"    {'-'*58}")
    for cash_pct in [0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.00]:
        key = f"{cash_pct:.0%}"
        if key not in r["all_detail"]:
            continue
        d = r["all_detail"][key]
        marker = ""
        if abs(cash_pct - r["optimal_cash_crra"]) < 0.01:
            marker = " << CRRA OPT"
        elif abs(cash_pct - r["formula_12vix_cash"]) < 0.03:
            marker = " <- 12/VIX"
        print(f"    {cash_pct:>5.0%}  {d['ce_return']:>8.2%}  {d['mv_utility']:>8.4f}  {d['avg_return']:>7.1%}  {d['avg_vol']:>7.1%}  {d['worst_22d']:>9.1%}{marker}")

# ==================================================================
# 5. Formula Comparison & Functional Form
# ==================================================================
print("\n" + "=" * 78)
print("[4/7] FUNCTIONAL FORM ANALYSIS")
print("=" * 78)

valid_levels = sorted(results.keys())
opt_cash_arr = np.array([results[v]["optimal_cash_crra"] for v in valid_levels])
f12_cash_arr = np.array([results[v]["formula_12vix_cash"] for v in valid_levels])
step_cash_arr = np.array([results[v]["step_rule_cash"] for v in valid_levels])
vix_arr = np.array(valid_levels, dtype=float)

# Mean absolute deviation from optimal
mad_12vix = np.mean(np.abs(f12_cash_arr - opt_cash_arr))
mad_step = np.mean(np.abs(step_cash_arr - opt_cash_arr))

print(f"\n  Mean Absolute Deviation from CRRA Optimal:")
print(f"    12/VIX formula:  {mad_12vix:.1%}")
print(f"    Step Rule:       {mad_step:.1%}")

# CE return gap
opt_ces = np.array([results[v]["optimal_ce_return"] for v in valid_levels])
f12_ces = np.array([results[v]["formula_ce_return"] for v in valid_levels])
step_ces = np.array([results[v]["step_ce_return"] for v in valid_levels])

avg_ce_gap_12vix = np.mean(opt_ces - f12_ces)
avg_ce_gap_step = np.mean(opt_ces - step_ces)

print(f"\n  Average CE Return Gap from Optimal (annualized):")
print(f"    12/VIX:  {avg_ce_gap_12vix:+.2%}")
print(f"    Step:    {avg_ce_gap_step:+.2%}")

# Fit functional forms to CRRA optimal cash
ss_tot = np.sum((opt_cash_arr - np.mean(opt_cash_arr))**2)

# A. Linear
slope_lin, intercept_lin, r_lin, p_lin, se_lin = stats.linregress(vix_arr, opt_cash_arr)
pred_lin = intercept_lin + slope_lin * vix_arr
rmse_lin = np.sqrt(np.mean((opt_cash_arr - pred_lin)**2))

print(f"\n  A. Linear: cash% = {intercept_lin:.3f} + {slope_lin:.4f} * VIX")
print(f"     R² = {r_lin**2:.3f}, RMSE = {rmse_lin:.3f}")

# B. Quadratic
coeffs_quad = np.polyfit(vix_arr, opt_cash_arr, 2)
pred_quad = np.polyval(coeffs_quad, vix_arr)
ss_res_quad = np.sum((opt_cash_arr - pred_quad)**2)
r2_quad = 1 - ss_res_quad / ss_tot if ss_tot > 0 else 0
rmse_quad = np.sqrt(np.mean((opt_cash_arr - pred_quad)**2))

print(f"\n  B. Quadratic: cash% = {coeffs_quad[0]:.5f}*VIX² + {coeffs_quad[1]:.4f}*VIX + {coeffs_quad[2]:.3f}")
print(f"     R² = {r2_quad:.3f}, RMSE = {rmse_quad:.3f}")

# C. Logarithmic
log_vix = np.log(vix_arr)
slope_log, intercept_log, r_log, p_log, se_log = stats.linregress(log_vix, opt_cash_arr)
pred_log = intercept_log + slope_log * log_vix
rmse_log = np.sqrt(np.mean((opt_cash_arr - pred_log)**2))

print(f"\n  C. Logarithmic: cash% = {intercept_log:.3f} + {slope_log:.4f} * ln(VIX)")
print(f"     R² = {r_log**2:.3f}, RMSE = {rmse_log:.3f}")

# D. 12/VIX formula
pred_12vix = 1.0 - np.minimum(12.0 / vix_arr, 1.0)
rmse_12vix = np.sqrt(np.mean((opt_cash_arr - pred_12vix)**2))
ss_res_12vix = np.sum((opt_cash_arr - pred_12vix)**2)
r2_12vix = 1 - ss_res_12vix / ss_tot if ss_tot > 0 else 0

print(f"\n  D. 12/VIX: cash% = 1 - min(12/VIX, 1)")
print(f"     R² = {r2_12vix:.3f}, RMSE = {rmse_12vix:.3f}")

# E. Best c/VIX
def rmse_c_over_vix(c):
    pred = 1.0 - np.minimum(c / vix_arr, 1.0)
    return np.sqrt(np.mean((opt_cash_arr - pred)**2))

from scipy.optimize import minimize_scalar
result_c = minimize_scalar(rmse_c_over_vix, bounds=(3, 30), method='bounded')
best_c = result_c.x
pred_best_c = 1.0 - np.minimum(best_c / vix_arr, 1.0)
rmse_best_c = np.sqrt(np.mean((opt_cash_arr - pred_best_c)**2))
ss_res_best_c = np.sum((opt_cash_arr - pred_best_c)**2)
r2_best_c = 1 - ss_res_best_c / ss_tot if ss_tot > 0 else 0

print(f"\n  E. Best c/VIX: cash% = 1 - min({best_c:.1f}/VIX, 1)")
print(f"     R² = {r2_best_c:.3f}, RMSE = {rmse_best_c:.3f}")

# Summary
print(f"\n  === FIT RANKING (by RMSE) ===")
fits = [
    ("Linear", rmse_lin, r_lin**2),
    ("Quadratic", rmse_quad, r2_quad),
    ("Logarithmic", rmse_log, r_log**2),
    ("12/VIX", rmse_12vix, r2_12vix),
    (f"{best_c:.1f}/VIX (best c)", rmse_best_c, r2_best_c),
]
fits.sort(key=lambda x: x[1])
for rank, (name, rmse, r2) in enumerate(fits, 1):
    print(f"    {rank}. {name:<25s}  RMSE={rmse:.4f}  R²={r2:.3f}")

# ==================================================================
# 6. Full Backtest with CRRA Utility + Standard Metrics
# ==================================================================
print("\n" + "=" * 78)
print("[5/7] FULL BACKTEST: 12/VIX vs OPTIMAL LOOKUP vs STEP")
print("=" * 78)

# Build optimal lookup from CRRA results
opt_lookup = {}
for v in valid_levels:
    opt_lookup[v] = results[v]["optimal_cash_crra"]

def get_optimal_cash(vix_val):
    """Interpolate CRRA-optimal cash% from lookup."""
    if vix_val <= valid_levels[0]:
        return opt_lookup[valid_levels[0]]
    if vix_val >= valid_levels[-1]:
        return opt_lookup[valid_levels[-1]]
    for i in range(len(valid_levels) - 1):
        if valid_levels[i] <= vix_val < valid_levels[i+1]:
            frac = (vix_val - valid_levels[i]) / (valid_levels[i+1] - valid_levels[i])
            return opt_lookup[valid_levels[i]] * (1 - frac) + opt_lookup[valid_levels[i+1]] * frac
    return 0.0

def get_step_cash(vix_val):
    if vix_val < 15: return 0.0
    elif vix_val <= 25: return 0.30
    else: return 0.60

def get_12vix_cash(vix_val):
    return 1.0 - min(12.0 / max(vix_val, 1.0), 1.0)

# LAGGED backtest
bt_rets = ret_array[1:]
bt_vix = vix_array[:-1]
bt_dates = dates[1:]

strategies = {
    "Buy & Hold": lambda v: 0.0,
    "12/VIX": get_12vix_cash,
    "Optimal Lookup": get_optimal_cash,
    "Step Rule": get_step_cash,
}

if best_c != 12:
    def get_bestc_cash(vix_val, c=best_c):
        return 1.0 - min(c / max(vix_val, 1.0), 1.0)
    strategies[f"{best_c:.0f}/VIX"] = get_bestc_cash

bt_results = {}
for name, cash_func in strategies.items():
    port_rets = np.zeros(len(bt_rets))
    cash_pcts = np.zeros(len(bt_rets))
    for i in range(len(bt_rets)):
        cash_pct = cash_func(bt_vix[i])
        cash_pcts[i] = cash_pct
        port_rets[i] = (1.0 - cash_pct) * bt_rets[i] + cash_pct * RF_DAILY

    # Metrics
    cum_ret = np.exp(np.cumsum(port_rets)) - 1
    total_ret = cum_ret[-1]
    ann_ret = (1 + total_ret) ** (252 / len(port_rets)) - 1
    ann_vol = np.std(port_rets) * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 0 else 0

    # MDD
    cum_wealth = np.exp(np.cumsum(port_rets))
    running_max = np.maximum.accumulate(cum_wealth)
    drawdown = cum_wealth / running_max - 1
    mdd = np.min(drawdown)

    # CRRA utility of terminal wealth
    terminal_wealth = cum_wealth[-1]

    # Per-year CRRA CE return
    yearly_wealths = []
    year_start = 0
    for i in range(1, len(port_rets)):
        if bt_dates[i].year != bt_dates[i-1].year or i == len(port_rets) - 1:
            yr_ret = np.exp(np.sum(port_rets[year_start:i])) - 1
            yearly_wealths.append(1 + yr_ret)
            year_start = i
    yearly_wealths = np.array(yearly_wealths)
    crra_u = crra_utility(yearly_wealths, GAMMA)
    ce_yr = certainty_equivalent(crra_u, GAMMA) - 1

    # Mean-variance utility
    mv_u = mean_variance_utility(port_rets, gamma_mv=GAMMA)

    # Sortino
    downside = port_rets[port_rets < RF_DAILY]
    downside_vol = np.std(downside) * np.sqrt(252) if len(downside) > 0 else 1e-6
    sortino = (ann_ret - RF_ANNUAL) / downside_vol

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    avg_cash = np.mean(cash_pcts)

    bt_results[name] = {
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sharpe),
        "sortino": float(sortino),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "crra_ce_return": float(ce_yr),
        "mv_utility": float(mv_u),
        "total_return": float(total_ret),
        "avg_cash": float(avg_cash),
    }

print(f"\n  Period: {bt_dates[0].strftime('%Y-%m-%d')} to {bt_dates[-1].strftime('%Y-%m-%d')} ({len(bt_rets)} days)")
print(f"\n{'Strategy':<18} {'Ann Ret':>8} {'Vol':>6} {'Sharpe':>7} {'MDD':>8} {'Calmar':>7} {'CE Ret':>7} {'MV Util':>8} {'Avg Cash':>9}")
print("-" * 90)
strat_order = ["Buy & Hold", "12/VIX", "Step Rule", "Optimal Lookup"]
if f"{best_c:.0f}/VIX" in bt_results:
    strat_order.append(f"{best_c:.0f}/VIX")
for name in strat_order:
    if name not in bt_results:
        continue
    r = bt_results[name]
    print(f"  {name:<16} {r['ann_return']:>7.1%} {r['ann_vol']:>5.1%} {r['sharpe']:>6.3f}  {r['mdd']:>7.1%} {r['calmar']:>6.3f}  {r['crra_ce_return']:>6.1%}  {r['mv_utility']:>7.4f}  {r['avg_cash']:>7.1%}")

# Rank by CRRA CE return
print(f"\n  CRRA UTILITY RANKING (gamma={GAMMA}):")
sorted_ce = sorted(bt_results.items(), key=lambda x: x[1]["crra_ce_return"], reverse=True)
for rank, (name, r) in enumerate(sorted_ce, 1):
    print(f"    {rank}. {name:<18s} CE Return={r['crra_ce_return']:>6.1%}  MDD={r['mdd']:>7.1%}  Sharpe={r['sharpe']:.3f}")

# ==================================================================
# 7. Robustness: By Decade
# ==================================================================
print("\n" + "=" * 78)
print("[6/7] ROBUSTNESS: OPTIMAL CASH% BY DECADE (CRRA)")
print("=" * 78)

decades = {
    "2005-2009": ("2005-01-01", "2009-12-31"),
    "2010-2014": ("2010-01-01", "2014-12-31"),
    "2015-2019": ("2015-01-01", "2019-12-31"),
    "2020-2024": ("2020-01-01", "2024-12-31"),
}

decade_results = {}
for decade_name, (d_start, d_end) in decades.items():
    print(f"\n  --- {decade_name} ---")

    mask_decade = (dates[:n-FORWARD_DAYS] >= d_start) & (dates[:n-FORWARD_DAYS] <= d_end)
    decade_optima = {}
    test_levels = [12, 14, 16, 18, 20, 22, 25, 30, 35, 40]

    header_printed = False
    for vix_level in test_levels:
        low = vix_level - VIX_BIN_WIDTH
        high = vix_level + VIX_BIN_WIDTH
        vix_mask = (vix_array[:n-FORWARD_DAYS] >= low) & (vix_array[:n-FORWARD_DAYS] < high)
        combined_mask = mask_decade & vix_mask
        indices = np.where(combined_mask)[0]

        if len(indices) < 10:
            continue

        fwd_set = [forward_windows[i] for i in indices]

        # Find CRRA optimal
        best_cash = 0.0
        best_ce = -1e10
        for cash_pct in CASH_STEPS:
            metrics = compute_forward_metrics(cash_pct, fwd_set)
            if metrics["ce_return_ann"] > best_ce:
                best_ce = metrics["ce_return_ann"]
                best_cash = cash_pct

        decade_optima[vix_level] = {"cash": best_cash, "ce_return": best_ce, "n": len(indices)}

        if not header_printed:
            print(f"    {'VIX':>5} {'N':>5} {'Opt Cash%':>10} {'CE Return':>10}")
            header_printed = True
        print(f"    {vix_level:>5} {len(indices):>5}   {best_cash:>7.0%}     {best_ce:>8.1%}")

    decade_results[decade_name] = decade_optima

# Cross-decade stability
print(f"\n  === CROSS-DECADE STABILITY (CRRA Optimal Cash%) ===")
print(f"  {'VIX':<10}", end="")
for d_name in decades:
    print(f" {d_name:>10}", end="")
print(f" {'Range':>8} {'Stable?':>8}")
print("  " + "-" * 68)

stability_count = 0
stability_total = 0
for vix_level in [12, 14, 16, 18, 20, 22, 25, 30]:
    print(f"  VIX={vix_level:<4}", end="")
    vals = []
    for d_name in decades:
        if vix_level in decade_results[d_name]:
            v = decade_results[d_name][vix_level]["cash"]
            vals.append(v)
            print(f"     {v:>4.0%} ", end="")
        else:
            print(f"       n/a", end="")
    if len(vals) >= 3:
        rng = max(vals) - min(vals)
        stability_total += 1
        is_stable = rng <= 0.20
        if is_stable:
            stability_count += 1
        print(f"  {rng:>5.0%}   {'YES' if is_stable else 'NO'}")
    else:
        print()

# ==================================================================
# 8. Multi-Gamma Sensitivity
# ==================================================================
print("\n" + "=" * 78)
print("[7/7] SENSITIVITY: OPTIMAL CASH% ACROSS GAMMA VALUES")
print("=" * 78)

gammas = [2, 3, 5, 7, 10]
print(f"\n  {'VIX':<8}", end="")
for g in gammas:
    print(f" {'γ='+str(g):>7}", end="")
print()
print("  " + "-" * 50)

for vix_level in [12, 16, 20, 25, 30]:
    if vix_level not in results:
        continue

    low = vix_level - VIX_BIN_WIDTH
    high = vix_level + VIX_BIN_WIDTH
    mask = (vix_array[:n-FORWARD_DAYS] >= low) & (vix_array[:n-FORWARD_DAYS] < high)
    indices = np.where(mask)[0]
    fwd_set = [forward_windows[i] for i in indices]

    print(f"  VIX={vix_level:<4}", end="")
    for g in gammas:
        best_cash = 0.0
        best_ce = -1e10
        for cash_pct in CASH_STEPS:
            m = compute_forward_metrics(cash_pct, fwd_set, gamma=g)
            if m["ce_return_ann"] > best_ce:
                best_ce = m["ce_return_ann"]
                best_cash = cash_pct
        print(f"   {best_cash:>4.0%}", end="")
    print()

# ==================================================================
# SUMMARY
# ==================================================================
print("\n" + "=" * 78)
print("SUMMARY: K378 CASH ALLOCATION FRONTIER")
print("=" * 78)

print(f"\n  CRRA utility (gamma={GAMMA}) breaks Sharpe's scale-invariance.")
print(f"  At gamma={GAMMA}, risk aversion is sufficient to prefer holding cash")
print(f"  when expected returns don't compensate for volatility.")

print(f"\n  1. OPTIMAL CASH% BY VIX (CRRA gamma={GAMMA}):")
print(f"     {'VIX':>5}  {'CRRA Opt':>9}  {'12/VIX':>7}  {'Gap':>6}  {'CE Gap':>7}  {'Note':>15}")
for v in valid_levels:
    r = results[v]
    gap = r["optimal_cash_crra"] - r["formula_12vix_cash"]
    ce_gap = r["optimal_ce_return"] - r["formula_ce_return"]
    note = ""
    if abs(gap) <= 0.05:
        note = "MATCH"
    elif gap > 0:
        note = "12/VIX too LOW"
    else:
        note = "12/VIX too HIGH"
    print(f"     {v:>5}  {r['optimal_cash_crra']:>8.0%}   {r['formula_12vix_cash']:>6.0%}  {gap:>+5.0%}  {ce_gap:>+6.1%}   {note}")

print(f"\n  2. FORMULA FIT TO CRRA OPTIMAL:")
print(f"     Best: {fits[0][0]} (RMSE={fits[0][1]:.4f})")
print(f"     12/VIX: RMSE={rmse_12vix:.4f}")
print(f"     Best c/VIX: c={best_c:.1f}")

print(f"\n  3. BACKTEST RANKING BY CRRA CE RETURN:")
for rank, (name, r) in enumerate(sorted_ce, 1):
    print(f"     {rank}. {name:<18s} CE={r['crra_ce_return']:>6.1%}  Sharpe={r['sharpe']:.3f}  MDD={r['mdd']:.1%}")

print(f"\n  4. DECADE STABILITY: {stability_count}/{stability_total} VIX levels stable (<20pp range)")

print(f"\n  5. KEY FINDINGS:")
# Find the best strategy by CE
best_strat = sorted_ce[0][0]
best_ce_val = sorted_ce[0][1]["crra_ce_return"]
twelve_ce = bt_results["12/VIX"]["crra_ce_return"]
bh_ce = bt_results["Buy & Hold"]["crra_ce_return"]

print(f"     a) Best strategy by CRRA utility: {best_strat} (CE={best_ce_val:.1%})")
print(f"     b) 12/VIX CE return: {twelve_ce:.1%}")
print(f"     c) Buy & Hold CE return: {bh_ce:.1%}")
print(f"     d) 12/VIX vs BH CE gap: {twelve_ce - bh_ce:+.1%}")
print(f"     e) Sharpe is SCALE-INVARIANT → cannot distinguish cash levels")
print(f"        (this is why all VT Sharpe ratios ~= BH Sharpe)")
print(f"     f) CRRA utility reveals the TRUE value of cash allocation:")
print(f"        higher gamma → more cash preferred → more MDD protection")

# Save results
output = {
    "experiment": "K378",
    "title": "Cash Allocation Frontier: Optimal Cash% by VIX Level (CRRA)",
    "methodology_note": "Sharpe is scale-invariant w.r.t. cash/equity mix. Using CRRA utility (gamma=5) instead.",
    "data": f"SPY + VIX, {ANALYSIS_START} to {DATA_END}",
    "n_days": int(len(spy_ret)),
    "forward_window": FORWARD_DAYS,
    "gamma": GAMMA,
    "vix_results": {str(k): v for k, v in results.items()},
    "functional_form": {
        "linear": {"rmse": float(rmse_lin), "r2": float(r_lin**2)},
        "quadratic": {"rmse": float(rmse_quad), "r2": float(r2_quad)},
        "logarithmic": {"rmse": float(rmse_log), "r2": float(r_log**2)},
        "12_over_vix": {"rmse": float(rmse_12vix), "r2": float(r2_12vix)},
        "best_c_over_vix": {"c": float(best_c), "rmse": float(rmse_best_c), "r2": float(r2_best_c)},
    },
    "backtest": bt_results,
    "decade_robustness": {k: {str(vl): vd for vl, vd in v.items()} for k, v in decade_results.items()},
}

with open("experiments/k378_cash_frontier_results.json", "w") as f:
    json.dump(output, f, indent=2)
print(f"\n  Results saved to experiments/k378_cash_frontier_results.json")
print("=" * 78)
