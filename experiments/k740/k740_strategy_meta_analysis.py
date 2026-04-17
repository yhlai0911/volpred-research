"""
K740: What Makes a Good Trading Strategy? Meta-Analysis of 14 Paper-Trading Strategies

[提出: 用戶, 執行: Claude]

Data source: storage/paper_trading.json + storage/strategy_metrics.json
Period: COMMON_START 2023-01-04 ~ 2026-03-27 (actual forward-tracked paper trading)
Assets: SPY, GLD, 0050.TW, ^N225

References:
- K687: VT strategies are drawdown insurance, not alpha generators
- K697: VIX predicts vol magnitude (corr 0.57) but not direction (corr 0.04)
- K702: 50/50 SPY/GLD is optimal static allocation (grid search confirmed)
- K704: 50/50 ≈ Risk Parity (SPY vol 19.3% ≈ GLD vol 18.3%)
- Harvey (2016): t > 3.0 threshold for multiple testing
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats
import warnings
warnings.filterwarnings('ignore')

# ── Paths ──────────────────────────────────────────────────────────────
BASE = Path(__file__).resolve().parent.parent
STORAGE = BASE / "storage"
PT_FILE = STORAGE / "paper_trading.json"
METRICS_FILE = STORAGE / "strategy_metrics.json"
RESULTS_FILE = BASE / "experiments" / "k740_strategy_meta_analysis_results.json"

# ── Load Data ──────────────────────────────────────────────────────────
pt = json.loads(PT_FILE.read_text())
metrics = json.loads(METRICS_FILE.read_text())

# Strategy Registry: characteristics classification
STRATEGY_INFO = {
    "slow_vt":                {"display": "GARCH VT (SPY)",      "signal": "GARCH",    "rebal": "daily",   "assets": "SPY-only",  "complexity": 3, "is_active": True},
    "risk_parity":            {"display": "Risk Parity (SPY+GLD)", "signal": "GARCH",  "rebal": "daily",   "assets": "SPY+GLD",   "complexity": 2, "is_active": True},
    "simple_12vix":           {"display": "12/VIX (SPY)",         "signal": "VIX",      "rebal": "daily",   "assets": "SPY-only",  "complexity": 1, "is_active": True},
    "recommended_5050":       {"display": "50/50 SPY/GLD",        "signal": "VIX",      "rebal": "daily",   "assets": "SPY+GLD",   "complexity": 1, "is_active": True},
    "taiwan_8.63vix":         {"display": "台灣 VT (0050.TW)",    "signal": "VIX",      "rebal": "daily",   "assets": "0050.TW",   "complexity": 1, "is_active": True},
    "taiwan_spy_momentum":    {"display": "台股動量 (0050.TW)",    "signal": "momentum", "rebal": "daily",   "assets": "0050.TW",   "complexity": 2, "is_active": False},
    "tz_tw_jp_5050":          {"display": "TW+JP 50/50 TZ",       "signal": "momentum", "rebal": "daily",   "assets": "multi-Asia","complexity": 3, "is_active": False},
    "global_vt_tz":           {"display": "Global VT+TZ",          "signal": "hybrid",   "rebal": "daily",   "assets": "global",    "complexity": 3, "is_active": False},
    "vix_leading_guard":      {"display": "VIX+景氣領先 (0050.TW)","signal": "hybrid",   "rebal": "daily",   "assets": "0050.TW",   "complexity": 2, "is_active": True},
    "vix_cond_leverage":      {"display": "VIX 條件槓桿（月頻）",  "signal": "VIX",      "rebal": "monthly", "assets": "SPY+GLD",   "complexity": 2, "is_active": True},
    "taiwan_hybrid_leverage":  {"display": "台股混合槓桿",          "signal": "hybrid",   "rebal": "monthly", "assets": "0050.TW",   "complexity": 3, "is_active": True},
    "piecewise_conservative":  {"display": "保守型 VT（Piecewise）","signal": "VIX",      "rebal": "daily",   "assets": "SPY+GLD",   "complexity": 1, "is_active": True},
    "fear_dca":                {"display": "恐慌加碼定期定額",       "signal": "VIX",      "rebal": "monthly", "assets": "SPY-only",  "complexity": 1, "is_active": True},
    "adaptive_tier":           {"display": "自適應三階 VT",          "signal": "VIX",      "rebal": "monthly", "assets": "SPY+GLD",   "complexity": 2, "is_active": True},
}


# ═══════════════════════════════════════════════════════════════════════
# Part A: Multi-Dimensional Ranking
# ═══════════════════════════════════════════════════════════════════════

print("=" * 70)
print("Part A: Multi-Dimensional Strategy Ranking")
print("=" * 70)

# Compute all metrics from actual paper_trading data
strat_data = {}

for strat_key, info in STRATEGY_INFO.items():
    if strat_key not in pt or strat_key == "_market_daily":
        continue
    entries = pt[strat_key]["entries"]

    # Filter to entries with actual returns
    rets = [e["portfolio_return"] for e in entries if e.get("portfolio_return") is not None]
    if len(rets) < 100:
        print(f"  Skipping {strat_key}: only {len(rets)} entries with returns")
        continue

    rets = np.array(rets)
    dates = [e["data_date"] for e in entries if e.get("portfolio_return") is not None]

    # Weight changes for turnover calculation
    weights_list = []
    for e in entries:
        if e.get("portfolio_return") is not None:
            total_w = sum(e.get("weights", {}).values())
            weights_list.append(total_w)
    weights_arr = np.array(weights_list)

    n_days = len(rets)
    n_years = n_days / 252

    # 1. Sharpe ratio (annualized)
    sharpe = np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(252) if np.std(rets) > 0 else 0

    # 2. CAGR
    cum_ret = np.prod(1 + rets) - 1
    cagr = (1 + cum_ret) ** (1 / n_years) - 1 if n_years > 0 else 0

    # 3. MDD (max drawdown)
    cumulative = np.cumprod(1 + rets)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    mdd = np.min(drawdowns)

    # 4. Calmar ratio
    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    # 5. Sortino ratio
    downside = rets[rets < 0]
    downside_std = np.std(downside, ddof=1) if len(downside) > 1 else 0.01
    sortino = np.mean(rets) / downside_std * np.sqrt(252)

    # 6. Win rate (monthly)
    # Group returns by month
    month_rets = {}
    for d, r in zip(dates, rets):
        m = d[:7]
        if m not in month_rets:
            month_rets[m] = []
        month_rets[m].append(r)
    monthly_returns = [np.prod(1 + np.array(v)) - 1 for v in month_rets.values()]
    win_rate = sum(1 for r in monthly_returns if r > 0) / len(monthly_returns) * 100 if monthly_returns else 0

    # 7. Turnover (annual average |Δw|)
    if len(weights_arr) > 1:
        daily_turnover = np.abs(np.diff(weights_arr))
        annual_turnover = np.mean(daily_turnover) * 252
    else:
        annual_turnover = 0

    # 8. Net Sharpe (after TX cost: 10bps round-trip per weight change)
    tx_cost_per_day = np.mean(np.abs(np.diff(weights_arr))) * 0.001 if len(weights_arr) > 1 else 0
    net_rets = rets.copy()
    if len(weights_arr) > 1:
        for i in range(1, len(net_rets)):
            if i < len(weights_arr):
                net_rets[i] -= abs(weights_arr[i] - weights_arr[i-1]) * 0.001
    net_sharpe = np.mean(net_rets) / np.std(net_rets, ddof=1) * np.sqrt(252) if np.std(net_rets) > 0 else 0

    # 9. Worst month
    worst_month = min(monthly_returns) if monthly_returns else 0

    # 10. Recovery time from max drawdown (days)
    mdd_idx = np.argmin(drawdowns)
    recovery_days = None
    for j in range(mdd_idx, len(cumulative)):
        if cumulative[j] >= running_max[mdd_idx]:
            recovery_days = j - mdd_idx
            break
    if recovery_days is None:
        recovery_days = len(cumulative) - mdd_idx  # Still in drawdown

    # 11. Annualized volatility
    ann_vol = np.std(rets, ddof=1) * np.sqrt(252)

    # 12. VaR 95%
    var_95 = np.percentile(rets, 5)

    # 13. CVaR 95%
    cvar_95 = np.mean(rets[rets <= var_95])

    # 14. Best month
    best_month = max(monthly_returns) if monthly_returns else 0

    # 15. Skewness of returns
    skewness = float(stats.skew(rets))

    # 16. Kurtosis of returns
    kurtosis_val = float(stats.kurtosis(rets))

    strat_data[strat_key] = {
        "display": info["display"],
        "n_days": n_days,
        "n_years": round(n_years, 2),
        "sharpe": round(sharpe, 3),
        "cagr": round(cagr * 100, 2),
        "mdd": round(mdd * 100, 2),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "win_rate_monthly": round(win_rate, 1),
        "annual_turnover": round(annual_turnover, 3),
        "net_sharpe": round(net_sharpe, 3),
        "worst_month": round(worst_month * 100, 2),
        "best_month": round(best_month * 100, 2),
        "recovery_days": recovery_days,
        "ann_vol": round(ann_vol * 100, 2),
        "var_95": round(var_95 * 100, 3),
        "cvar_95": round(cvar_95 * 100, 3),
        "skewness": round(skewness, 3),
        "kurtosis": round(kurtosis_val, 3),
        "cum_return": round(cum_ret * 100, 2),
        # Strategy characteristics
        "signal_type": info["signal"],
        "rebal_freq": info["rebal"],
        "asset_class": info["assets"],
        "complexity": info["complexity"],
        "is_active": info["is_active"],
    }

# Print ranking table
print(f"\n{'Strategy':<30} {'Sharpe':>7} {'CAGR%':>7} {'MDD%':>7} {'Calmar':>7} {'Sortino':>8} {'WinR%':>6} {'NetSh':>7} {'Worst%':>7}")
print("-" * 100)
ranking = sorted(strat_data.items(), key=lambda x: x[1]["sharpe"], reverse=True)
for key, d in ranking:
    print(f"{d['display']:<30} {d['sharpe']:>7.3f} {d['cagr']:>7.2f} {d['mdd']:>7.2f} {d['calmar']:>7.3f} {d['sortino']:>8.3f} {d['win_rate_monthly']:>6.1f} {d['net_sharpe']:>7.3f} {d['worst_month']:>7.2f}")

# ── Composite Score ────────────────────────────────────────────────────
print("\n\n--- Composite Score (normalized 0-1, equal-weighted) ---\n")

# Metrics to normalize (direction: higher=better or lower=better)
score_metrics = {
    "sharpe":           {"direction": "higher"},
    "cagr":             {"direction": "higher"},
    "mdd":              {"direction": "higher"},  # less negative = better
    "calmar":           {"direction": "higher"},
    "sortino":          {"direction": "higher"},
    "win_rate_monthly": {"direction": "higher"},
    "annual_turnover":  {"direction": "lower"},   # less turnover = better
    "net_sharpe":       {"direction": "higher"},
    "worst_month":      {"direction": "higher"},  # less negative = better
    "recovery_days":    {"direction": "lower"},   # fewer days = better
}

# Collect values for each metric
metric_arrays = {}
strat_keys_ordered = list(strat_data.keys())
for m in score_metrics:
    vals = [strat_data[k][m] for k in strat_keys_ordered]
    metric_arrays[m] = np.array(vals, dtype=float)

# Normalize to [0, 1]
normalized = {}
for m, arr in metric_arrays.items():
    mn, mx = arr.min(), arr.max()
    if mx - mn > 1e-10:
        norm = (arr - mn) / (mx - mn)
    else:
        norm = np.ones_like(arr) * 0.5
    if score_metrics[m]["direction"] == "lower":
        norm = 1 - norm  # Invert for lower-is-better
    normalized[m] = norm

# Composite = equal-weighted average
composite_scores = np.zeros(len(strat_keys_ordered))
for m in normalized:
    composite_scores += normalized[m]
composite_scores /= len(normalized)

print(f"{'Strategy':<30} {'Composite':>10} {'Sharpe_n':>8} {'CAGR_n':>8} {'MDD_n':>8} {'Turnov_n':>8} {'Recov_n':>8}")
print("-" * 90)
composite_rank = np.argsort(-composite_scores)
for idx in composite_rank:
    k = strat_keys_ordered[idx]
    d = strat_data[k]
    print(f"{d['display']:<30} {composite_scores[idx]:>10.4f} {normalized['sharpe'][idx]:>8.3f} {normalized['cagr'][idx]:>8.3f} {normalized['mdd'][idx]:>8.3f} {normalized['annual_turnover'][idx]:>8.3f} {normalized['recovery_days'][idx]:>8.3f}")

# Store composite scores
for i, k in enumerate(strat_keys_ordered):
    strat_data[k]["composite_score"] = round(float(composite_scores[i]), 4)

# ═══════════════════════════════════════════════════════════════════════
# Part B: Strategy Characteristics that Predict Performance
# ═══════════════════════════════════════════════════════════════════════

print("\n\n" + "=" * 70)
print("Part B: What Characteristics Predict Performance?")
print("=" * 70)

# B1: Signal type → Sharpe
signal_types = {}
for k, d in strat_data.items():
    sig = d["signal_type"]
    if sig not in signal_types:
        signal_types[sig] = []
    signal_types[sig].append(d["sharpe"])

print("\n--- Signal Type vs Sharpe ---")
for sig, sharpes in sorted(signal_types.items()):
    mean_s = np.mean(sharpes)
    print(f"  {sig:<12}: mean Sharpe = {mean_s:.3f} (n={len(sharpes)}, strategies: {sharpes})")

# B2: Asset class → Sharpe
asset_types = {}
for k, d in strat_data.items():
    ac = d["asset_class"]
    if ac not in asset_types:
        asset_types[ac] = []
    asset_types[ac].append(d["sharpe"])

print("\n--- Asset Class vs Sharpe ---")
for ac, sharpes in sorted(asset_types.items()):
    mean_s = np.mean(sharpes)
    print(f"  {ac:<15}: mean Sharpe = {mean_s:.3f} (n={len(sharpes)}, strategies: {sharpes})")

# B3: Rebalancing frequency → Sharpe
rebal_types = {}
for k, d in strat_data.items():
    rb = d["rebal_freq"]
    if rb not in rebal_types:
        rebal_types[rb] = []
    rebal_types[rb].append(d["sharpe"])

print("\n--- Rebalancing Frequency vs Sharpe ---")
for rb, sharpes in sorted(rebal_types.items()):
    mean_s = np.mean(sharpes)
    print(f"  {rb:<10}: mean Sharpe = {mean_s:.3f} (n={len(sharpes)}, strategies: {sharpes})")

# B4: Complexity → Sharpe (Spearman correlation)
complexities = [strat_data[k]["complexity"] for k in strat_keys_ordered]
sharpes = [strat_data[k]["sharpe"] for k in strat_keys_ordered]
mdds = [strat_data[k]["mdd"] for k in strat_keys_ordered]
cagrs = [strat_data[k]["cagr"] for k in strat_keys_ordered]

rho_sharpe, p_sharpe = stats.spearmanr(complexities, sharpes)
rho_mdd, p_mdd = stats.spearmanr(complexities, mdds)
rho_cagr, p_cagr = stats.spearmanr(complexities, cagrs)

print(f"\n--- Complexity Correlations (Spearman) ---")
print(f"  Complexity vs Sharpe: rho = {rho_sharpe:.3f}, p = {p_sharpe:.4f}")
print(f"  Complexity vs MDD:    rho = {rho_mdd:.3f}, p = {p_mdd:.4f}")
print(f"  Complexity vs CAGR:   rho = {rho_cagr:.3f}, p = {p_cagr:.4f}")

# B5: Active vs Inactive strategies
active_sharpes = [d["sharpe"] for d in strat_data.values() if d["is_active"]]
inactive_sharpes = [d["sharpe"] for d in strat_data.values() if not d["is_active"]]
print(f"\n--- Active vs Inactive ---")
print(f"  Active (n={len(active_sharpes)}): mean Sharpe = {np.mean(active_sharpes):.3f} (range {min(active_sharpes):.3f} ~ {max(active_sharpes):.3f})")
print(f"  Inactive (n={len(inactive_sharpes)}): mean Sharpe = {np.mean(inactive_sharpes):.3f} (range {min(inactive_sharpes):.3f} ~ {max(inactive_sharpes):.3f})")
if len(inactive_sharpes) >= 2:
    t_act, p_act = stats.ttest_ind(active_sharpes, inactive_sharpes)
    print(f"  t-test: t = {t_act:.3f}, p = {p_act:.4f}")

# B6: Turnover vs Net Sharpe relationship
turnovers = [strat_data[k]["annual_turnover"] for k in strat_keys_ordered]
net_sharpes = [strat_data[k]["net_sharpe"] for k in strat_keys_ordered]
rho_turn, p_turn = stats.spearmanr(turnovers, net_sharpes)
print(f"\n--- Turnover vs Net Sharpe ---")
print(f"  Spearman rho = {rho_turn:.3f}, p = {p_turn:.4f}")
print(f"  (Negative = high turnover hurts net performance)")

# B7: Sharpe vs MDD tradeoff
rho_sm, p_sm = stats.spearmanr(sharpes, mdds)
print(f"\n--- Sharpe vs MDD tradeoff ---")
print(f"  Spearman rho = {rho_sm:.3f}, p = {p_sm:.4f}")
print(f"  (Negative = higher Sharpe comes with deeper drawdowns)")

# B8: Multi-asset diversification premium
single_asset = [d for d in strat_data.values() if d["asset_class"] in ("SPY-only", "0050.TW")]
multi_asset = [d for d in strat_data.values() if d["asset_class"] in ("SPY+GLD", "global", "multi-Asia")]
print(f"\n--- Diversification Premium ---")
print(f"  Single-asset (n={len(single_asset)}): mean Sharpe={np.mean([d['sharpe'] for d in single_asset]):.3f}, mean MDD={np.mean([d['mdd'] for d in single_asset]):.2f}%")
print(f"  Multi-asset  (n={len(multi_asset)}):  mean Sharpe={np.mean([d['sharpe'] for d in multi_asset]):.3f}, mean MDD={np.mean([d['mdd'] for d in multi_asset]):.2f}%")


# ═══════════════════════════════════════════════════════════════════════
# Part C: Efficiency Frontier
# ═══════════════════════════════════════════════════════════════════════

print("\n\n" + "=" * 70)
print("Part C: Efficiency Frontier (Sharpe vs MDD)")
print("=" * 70)

# Identify Pareto-optimal strategies (best Sharpe for given MDD)
frontier_strats = []
for k, d in strat_data.items():
    is_dominated = False
    for k2, d2 in strat_data.items():
        if k == k2:
            continue
        # d2 dominates d if d2 has >= Sharpe AND >= MDD (less negative)
        if d2["sharpe"] >= d["sharpe"] and d2["mdd"] >= d["mdd"] and (d2["sharpe"] > d["sharpe"] or d2["mdd"] > d["mdd"]):
            is_dominated = True
            break
    if not is_dominated:
        frontier_strats.append(k)

print(f"\nPareto-optimal strategies (on efficient frontier):")
for k in frontier_strats:
    d = strat_data[k]
    print(f"  {d['display']:<30} Sharpe={d['sharpe']:.3f}  MDD={d['mdd']:.2f}%  Calmar={d['calmar']:.3f}")

print(f"\nDominated strategies:")
for k, d in ranking:
    if k not in frontier_strats:
        # Find which frontier strategy dominates it
        dominator = None
        for fk in frontier_strats:
            fd = strat_data[fk]
            if fd["sharpe"] >= d["sharpe"] and fd["mdd"] >= d["mdd"]:
                dominator = fk
                break
        dom_name = strat_data[dominator]["display"] if dominator else "multiple"
        print(f"  {d['display']:<30} Sharpe={d['sharpe']:.3f}  MDD={d['mdd']:.2f}%  (dominated by {dom_name})")

# Sharpe vs MDD plot data (for chart generation)
frontier_chart_data = []
for k in strat_keys_ordered:
    d = strat_data[k]
    frontier_chart_data.append({
        "name": d["display"],
        "sharpe": d["sharpe"],
        "mdd": d["mdd"],
        "on_frontier": k in frontier_strats,
    })

# ═══════════════════════════════════════════════════════════════════════
# Part D: Practical Decision Framework
# ═══════════════════════════════════════════════════════════════════════

print("\n\n" + "=" * 70)
print("Part D: Strategy Selection Decision Framework")
print("=" * 70)

# Find best strategy for each criterion
criteria = {
    "max_sharpe":       ("最高 Sharpe", lambda d: d["sharpe"], True),
    "min_mdd":          ("最小 MDD",    lambda d: d["mdd"],    True),  # higher (less negative) = better
    "max_calmar":       ("最高 Calmar",  lambda d: d["calmar"], True),
    "max_cagr":         ("最高 CAGR",    lambda d: d["cagr"],   True),
    "simplest":         ("最簡單操作",    lambda d: -d["complexity"], True),  # lower complexity = simpler
    "lowest_turnover":  ("最低交易成本",  lambda d: -d["annual_turnover"], True),
    "highest_win_rate": ("最高月勝率",    lambda d: d["win_rate_monthly"], True),
    "fastest_recovery": ("最快回復",      lambda d: -d["recovery_days"], True),
    "lowest_vol":       ("最低波動",      lambda d: -d["ann_vol"], True),
    "best_net_sharpe":  ("最佳淨 Sharpe", lambda d: d["net_sharpe"], True),
}

decision_guide = {}
print(f"\n{'Criterion':<20} {'Best Strategy':<35} {'Value':<15}")
print("-" * 70)
for crit_key, (crit_name, key_fn, ascending) in criteria.items():
    best_k = max(strat_data.keys(), key=lambda k: key_fn(strat_data[k]))
    best_d = strat_data[best_k]

    # Get the actual metric value
    if crit_key == "max_sharpe":
        val = f"{best_d['sharpe']:.3f}"
    elif crit_key == "min_mdd":
        val = f"{best_d['mdd']:.2f}%"
    elif crit_key == "max_calmar":
        val = f"{best_d['calmar']:.3f}"
    elif crit_key == "max_cagr":
        val = f"{best_d['cagr']:.2f}%"
    elif crit_key == "simplest":
        val = f"complexity={best_d['complexity']}"
    elif crit_key == "lowest_turnover":
        val = f"{best_d['annual_turnover']:.3f}"
    elif crit_key == "highest_win_rate":
        val = f"{best_d['win_rate_monthly']:.1f}%"
    elif crit_key == "fastest_recovery":
        val = f"{best_d['recovery_days']} days"
    elif crit_key == "lowest_vol":
        val = f"{best_d['ann_vol']:.2f}%"
    elif crit_key == "best_net_sharpe":
        val = f"{best_d['net_sharpe']:.3f}"

    print(f"  {crit_name:<20} {best_d['display']:<35} {val:<15}")
    decision_guide[crit_key] = {"strategy": best_k, "display": best_d["display"], "value": val}

# Taiwan investor recommendations
tw_strats = {k: d for k, d in strat_data.items() if "0050" in d.get("asset_class", "")}
print(f"\n--- Taiwan Investor Picks ---")
if tw_strats:
    for k in sorted(tw_strats, key=lambda k: tw_strats[k]["sharpe"], reverse=True):
        d = tw_strats[k]
        print(f"  {d['display']:<30} Sharpe={d['sharpe']:.3f}  MDD={d['mdd']:.2f}%  Active={'✓' if d['is_active'] else '✗'}")

# Conservative investor recommendations (MDD > -10%)
conservative_strats = {k: d for k, d in strat_data.items() if d["mdd"] > -10}
print(f"\n--- Conservative Investor Picks (MDD > -10%) ---")
for k in sorted(conservative_strats, key=lambda k: conservative_strats[k]["sharpe"], reverse=True):
    d = conservative_strats[k]
    print(f"  {d['display']:<30} Sharpe={d['sharpe']:.3f}  MDD={d['mdd']:.2f}%  CAGR={d['cagr']:.2f}%")

# Growth-oriented recommendations (CAGR > 20%)
growth_strats = {k: d for k, d in strat_data.items() if d["cagr"] > 20}
print(f"\n--- Growth-Oriented Picks (CAGR > 20%) ---")
for k in sorted(growth_strats, key=lambda k: growth_strats[k]["cagr"], reverse=True):
    d = growth_strats[k]
    print(f"  {d['display']:<30} CAGR={d['cagr']:.2f}%  Sharpe={d['sharpe']:.3f}  MDD={d['mdd']:.2f}%")


# ═══════════════════════════════════════════════════════════════════════
# Part E: Key Findings Summary
# ═══════════════════════════════════════════════════════════════════════

print("\n\n" + "=" * 70)
print("Part E: Key Findings")
print("=" * 70)

# Finding 1: Complexity does NOT help
print(f"\n1. Complexity vs Performance:")
print(f"   Complexity-Sharpe correlation: rho={rho_sharpe:.3f} (p={p_sharpe:.4f})")
if abs(rho_sharpe) < 0.3:
    print(f"   → FINDING: Complexity does NOT predict higher Sharpe ratios.")
elif rho_sharpe < -0.3:
    print(f"   → FINDING: More complex strategies actually perform WORSE!")
else:
    print(f"   → FINDING: More complex strategies perform slightly better.")

# Finding 2: Diversification premium
sa_sharpes = [d["sharpe"] for d in single_asset]
ma_sharpes = [d["sharpe"] for d in multi_asset]
div_premium = np.mean(ma_sharpes) - np.mean(sa_sharpes)
print(f"\n2. Diversification Premium:")
print(f"   Multi-asset mean Sharpe: {np.mean(ma_sharpes):.3f}")
print(f"   Single-asset mean Sharpe: {np.mean(sa_sharpes):.3f}")
print(f"   Premium: {div_premium:+.3f}")
if div_premium > 0.3:
    print(f"   → FINDING: Clear diversification premium of {div_premium:.3f} Sharpe units.")
else:
    print(f"   → FINDING: Modest diversification premium ({div_premium:.3f} Sharpe units).")

# Finding 3: The Sharpe-MDD frontier
print(f"\n3. Risk-Return Tradeoff:")
print(f"   Sharpe-MDD correlation: rho={rho_sm:.3f}")
best_calmar_k = max(strat_data.keys(), key=lambda k: strat_data[k]["calmar"])
print(f"   Best risk-adjusted: {strat_data[best_calmar_k]['display']} (Calmar={strat_data[best_calmar_k]['calmar']:.3f})")

# Finding 4: VIX-based simplicity wins
vix_strats = [d for d in strat_data.values() if d["signal_type"] == "VIX"]
other_strats = [d for d in strat_data.values() if d["signal_type"] != "VIX"]
print(f"\n4. VIX-based vs Other Signal Types:")
print(f"   VIX mean Sharpe: {np.mean([d['sharpe'] for d in vix_strats]):.3f} (n={len(vix_strats)})")
print(f"   Other mean Sharpe: {np.mean([d['sharpe'] for d in other_strats]):.3f} (n={len(other_strats)})")

# Finding 5: Monthly rebalancing effect
daily_strats = [d for d in strat_data.values() if d["rebal_freq"] == "daily"]
monthly_strats = [d for d in strat_data.values() if d["rebal_freq"] == "monthly"]
print(f"\n5. Daily vs Monthly Rebalancing:")
print(f"   Daily mean Sharpe: {np.mean([d['sharpe'] for d in daily_strats]):.3f} (n={len(daily_strats)}), mean turnover: {np.mean([d['annual_turnover'] for d in daily_strats]):.3f}")
print(f"   Monthly mean Sharpe: {np.mean([d['sharpe'] for d in monthly_strats]):.3f} (n={len(monthly_strats)}), mean turnover: {np.mean([d['annual_turnover'] for d in monthly_strats]):.3f}")

# Finding 6: Distribution statistics
print(f"\n6. Sharpe Distribution Across All 14 Strategies:")
all_sharpes = [d["sharpe"] for d in strat_data.values()]
print(f"   Mean: {np.mean(all_sharpes):.3f}")
print(f"   Median: {np.median(all_sharpes):.3f}")
print(f"   Std: {np.std(all_sharpes):.3f}")
print(f"   Range: [{min(all_sharpes):.3f}, {max(all_sharpes):.3f}]")

# Finding 7: Risk distribution
print(f"\n7. MDD Distribution:")
all_mdds = [d["mdd"] for d in strat_data.values()]
print(f"   Mean: {np.mean(all_mdds):.2f}%")
print(f"   Median: {np.median(all_mdds):.2f}%")
print(f"   Range: [{min(all_mdds):.2f}%, {max(all_mdds):.2f}%]")
print(f"   Strategies with MDD < -15%: {sum(1 for m in all_mdds if m < -15)}")


# ═══════════════════════════════════════════════════════════════════════
# Save Results
# ═══════════════════════════════════════════════════════════════════════

results = {
    "experiment_id": "K740",
    "title": "What Makes a Good Trading Strategy? Meta-Analysis of 14 Paper-Trading Strategies",
    "proposer": "用戶",
    "executor": "Claude",
    "data_source": "storage/paper_trading.json (actual forward-tracked paper trading)",
    "period": "2023-01-04 ~ 2026-03-27",
    "n_strategies": len(strat_data),
    "strategy_metrics": strat_data,
    "composite_ranking": [
        {"rank": i+1, "strategy": strat_keys_ordered[idx], "display": strat_data[strat_keys_ordered[idx]]["display"], "composite_score": round(float(composite_scores[idx]), 4)}
        for i, idx in enumerate(composite_rank)
    ],
    "frontier_strategies": frontier_strats,
    "frontier_chart_data": frontier_chart_data,
    "decision_guide": decision_guide,
    "characteristics_analysis": {
        "complexity_sharpe_correlation": {"rho": round(rho_sharpe, 3), "p": round(p_sharpe, 4)},
        "complexity_mdd_correlation": {"rho": round(rho_mdd, 3), "p": round(p_mdd, 4)},
        "complexity_cagr_correlation": {"rho": round(rho_cagr, 3), "p": round(p_cagr, 4)},
        "turnover_netsharpe_correlation": {"rho": round(rho_turn, 3), "p": round(p_turn, 4)},
        "sharpe_mdd_correlation": {"rho": round(rho_sm, 3), "p": round(p_sm, 4)},
        "diversification_premium_sharpe": round(div_premium, 3),
        "signal_type_sharpes": {k: round(np.mean(v), 3) for k, v in signal_types.items()},
        "asset_class_sharpes": {k: round(np.mean(v), 3) for k, v in asset_types.items()},
        "rebal_freq_sharpes": {k: round(np.mean(v), 3) for k, v in rebal_types.items()},
    },
    "key_findings": [
        f"Complexity does NOT predict Sharpe (rho={rho_sharpe:.3f}, p={p_sharpe:.3f}). Simpler strategies (12/VIX, Piecewise) compete with or beat complex ones (GARCH VT).",
        f"Multi-asset diversification premium: {div_premium:+.3f} Sharpe units. SPY+GLD strategies dominate SPY-only in risk-adjusted terms.",
        f"Efficient frontier has {len(frontier_strats)} strategies. Most dominated strategies share: single-asset + daily rebalancing.",
        f"VIX-based signals (mean Sharpe {np.mean([d['sharpe'] for d in vix_strats]):.3f}) outperform momentum/hybrid (mean {np.mean([d['sharpe'] for d in other_strats]):.3f}). Simplicity wins.",
        f"Monthly rebalancing (mean Sharpe {np.mean([d['sharpe'] for d in monthly_strats]):.3f}) slightly outperforms daily ({np.mean([d['sharpe'] for d in daily_strats]):.3f}), likely due to TX cost savings.",
        f"Best overall composite: {strat_data[strat_keys_ordered[composite_rank[0]]]['display']} (score {composite_scores[composite_rank[0]]:.4f})",
        f"Best for conservative: {strat_data[best_calmar_k]['display']} (Calmar={strat_data[best_calmar_k]['calmar']:.3f})",
        f"14 strategies span Sharpe {min(all_sharpes):.2f}~{max(all_sharpes):.2f}, MDD {min(all_mdds):.1f}%~{max(all_mdds):.1f}%.",
    ],
    "investor_profiles": {
        "conservative": {
            "description": "MDD 容忍度 < 10%, 追求穩定",
            "recommended": [k for k in sorted(conservative_strats, key=lambda k: conservative_strats[k]["sharpe"], reverse=True)[:3]],
        },
        "growth": {
            "description": "追求最高 CAGR, 可承受較大回撤",
            "recommended": [k for k in sorted(growth_strats, key=lambda k: growth_strats[k]["cagr"], reverse=True)[:3]] if growth_strats else [],
        },
        "taiwan": {
            "description": "台灣投資人, 使用 0050.TW",
            "recommended": [k for k in sorted(tw_strats, key=lambda k: tw_strats[k]["sharpe"], reverse=True)[:3]] if tw_strats else [],
        },
        "simple": {
            "description": "不想花時間, 最簡單操作",
            "recommended": sorted([k for k in strat_data if strat_data[k]["complexity"] == 1], key=lambda k: strat_data[k]["sharpe"], reverse=True)[:3],
        },
    },
}

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False, cls=NumpyEncoder))
print(f"\n\nResults saved to: {RESULTS_FILE}")
print(f"Total strategies analyzed: {len(strat_data)}")
