#!/usr/bin/env python3
"""
K662: Does VT Framework Work for Commodities?
==============================================
Jump exploration. Our entire VT framework was built for equity (SPY).
Does the same VIX-based scaling work for commodities like gold (GLD)
and oil (USO)?

Key hypotheses:
  1. VIX is an EQUITY vol measure — may not capture commodity dynamics
  2. Gold often rises when VIX rises (safe haven) → VIX scaling is
     WRONG direction for GLD
  3. Oil is supply-driven → VIX may be irrelevant
  4. Commodity-specific vol signals may outperform VIX-based VT

Strategies tested (for each of GLD, USO):
  a. Buy-and-hold (benchmark)
  b. 12/VIX VT (equity vol measure)
  c. GARCH VT using asset's OWN volatility
  d. Rolling 22-day vol VT (simple own-vol)
  e. Hybrid VT (own-vol primary, VIX regime guard)

Data sources: yfinance (GLD, USO, SPY, ^VIX)
Period: 2010-01-01 to 2026-03-27 (USO: 2010-01-01+, may have ETF restructure issues)

Known context (from knowledge base):
  - K634/K476: GLD has inverted leverage (γ<0), VT still works
  - N165: Optimal target vol GLD=20% (near base), SPY=8% (60% of base)
  - K649: USO flipped γ during 2026 Iran crisis (+0.10 → -0.13)
  - N74: GLD VT alpha only 49% absorbed by trend (vs SPY 135%)
  - Chevallier & Ielpo (2017): inverted leverage in gold, wheat, coffee, cocoa

References:
  - Moreira & Muir (2017, JoF): "Volatility-Managed Portfolios"
  - Chevallier & Ielpo (2017): commodity inverted leverage
  - Baur & Lucey (2010, JFE): "Is gold a safe haven?"
  - Gorton & Rouwenhorst (2006, FAJ): "Facts and Fantasies about Commodity Futures"

[提出: Claude, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import json
from datetime import datetime
from pathlib import Path

np.random.seed(42)

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K662: Does VT Framework Work for Commodities?")
print("=" * 70)

print("\n[1/8] Downloading data from yfinance...")

tickers = {
    "GLD": "GLD",
    "USO": "USO",
    "SPY": "SPY",     # benchmark comparison
    "VIX": "^VIX",
}

start_date = "2009-06-01"  # buffer for rolling windows
end_date = "2026-03-28"

data = {}
for name, ticker in tickers.items():
    raw = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close_col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    data[name] = raw[close_col].copy()
    data[name].name = name
    print(f"  {name}: {data[name].index[0].strftime('%Y-%m-%d')} to "
          f"{data[name].index[-1].strftime('%Y-%m-%d')} ({len(data[name])} obs)")

# Align to common dates starting from 2010-01-01
common_idx = data["GLD"].index
for name in ["USO", "SPY", "VIX"]:
    common_idx = common_idx.intersection(data[name].index)
common_idx = common_idx[common_idx >= "2010-01-01"]

gld_close = data["GLD"].loc[common_idx]
uso_close = data["USO"].loc[common_idx]
spy_close = data["SPY"].loc[common_idx]
vix_close = data["VIX"].loc[common_idx]

# Returns
gld_ret = gld_close.pct_change().dropna()
uso_ret = uso_close.pct_change().dropna()
spy_ret = spy_close.pct_change().dropna()

# Re-align
common_ret_idx = gld_ret.index.intersection(uso_ret.index).intersection(spy_ret.index)
common_ret_idx = common_ret_idx.intersection(vix_close.index)
gld_ret = gld_ret.loc[common_ret_idx]
uso_ret = uso_ret.loc[common_ret_idx]
spy_ret = spy_ret.loc[common_ret_idx]
vix = vix_close.loc[common_ret_idx]

print(f"\n  Common return period: {common_ret_idx[0].strftime('%Y-%m-%d')} to "
      f"{common_ret_idx[-1].strftime('%Y-%m-%d')} ({len(common_ret_idx)} obs)")

# ============================================================
# 2. Data diagnostics
# ============================================================
print("\n[2/8] Data diagnostics...")

for name, ret in [("GLD", gld_ret), ("USO", uso_ret), ("SPY", spy_ret)]:
    ann_ret = ret.mean() * 252
    ann_vol = ret.std() * np.sqrt(252)
    skew = ret.skew()
    kurt = ret.kurtosis()
    print(f"  {name}: mean={ann_ret:.4f}, vol={ann_vol:.4f}, "
          f"skew={skew:.3f}, kurt={kurt:.3f}")

# VIX statistics
print(f"  VIX: mean={vix.mean():.2f}, median={vix.median():.2f}, "
      f"min={vix.min():.2f}, max={vix.max():.2f}")

# VIX correlation with commodity returns
vix_chg = vix.pct_change().dropna()
ci_vix_chg = gld_ret.index.intersection(vix_chg.index)
corr_vix_gld = gld_ret.loc[ci_vix_chg].corr(vix_chg.loc[ci_vix_chg])
corr_vix_uso = uso_ret.loc[ci_vix_chg].corr(vix_chg.loc[ci_vix_chg])
corr_vix_spy = spy_ret.loc[ci_vix_chg].corr(vix_chg.loc[ci_vix_chg])

print(f"\n  VIX-return correlations (daily):")
print(f"    SPY vs VIX change: {corr_vix_spy:.3f}")
print(f"    GLD vs VIX change: {corr_vix_gld:.3f}")
print(f"    USO vs VIX change: {corr_vix_uso:.3f}")

# USO contango/structural issues warning
uso_total_ret = (uso_close.iloc[-1] / uso_close.iloc[0]) - 1
gld_total_ret = (gld_close.iloc[-1] / gld_close.iloc[0]) - 1
print(f"\n  ⚠️  USO total return since 2010: {uso_total_ret:.1%} "
      f"(contango drag + 2020 restructure)")
print(f"  GLD total return since 2010: {gld_total_ret:.1%}")

# ============================================================
# 3. GARCH estimation for each asset
# ============================================================
print("\n[3/8] Fitting GJR-GARCH(1,1) for each commodity...")

def fit_garch(returns, name, window=2000):
    """Fit GJR-GARCH(1,1) with diagnostics."""
    ret_pct = returns * 100  # arch expects percentage returns
    # Use full sample for parameter estimation
    am = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1, dist='t',
                    mean='Constant', rescale=False)
    try:
        res = am.fit(disp='off', options={'maxiter': 1000})
        params = res.params
        omega = params.get('omega', 0)
        alpha = params.get('alpha[1]', 0)
        gamma = params.get('gamma[1]', 0)
        beta = params.get('beta[1]', 0)
        persistence = alpha + gamma / 2 + beta
        cond_vol = res.conditional_volatility / 100  # back to decimal

        print(f"  {name} GJR-GARCH: ω={omega:.4f}, α={alpha:.4f}, "
              f"γ={gamma:.4f}, β={beta:.4f}")
        print(f"    Persistence={persistence:.4f}, LL={res.loglikelihood:.1f}, "
              f"Converged={res.convergence_flag == 0}")
        print(f"    Leverage γ t-stat={params.get('gamma[1]', 0) / res.std_err.get('gamma[1]', 1):.2f}")

        return res, cond_vol
    except Exception as e:
        print(f"  {name} GJR-GARCH failed: {e}")
        # Fallback to simple GARCH
        am2 = arch_model(ret_pct, vol='GARCH', p=1, q=1, dist='t',
                         mean='Constant', rescale=False)
        res2 = am2.fit(disp='off')
        cond_vol2 = res2.conditional_volatility / 100
        return res2, cond_vol2

garch_results = {}
cond_vols = {}

for name, ret in [("GLD", gld_ret), ("USO", uso_ret), ("SPY", spy_ret)]:
    res, cv = fit_garch(ret, name)
    garch_results[name] = res
    cond_vols[name] = cv

# ============================================================
# 4. Build VT strategy signals
# ============================================================
print("\n[4/8] Building VT strategy signals...")

# --- 4a. 12/VIX weight ---
# Standard: w = min(12/VIX, 1.0)
vix_weight = np.minimum(12.0 / vix, 1.0)
vix_weight.name = "vix_weight"

# Shift by 1 day (use yesterday's signal for today's return)
vix_weight_lag = vix_weight.shift(1).loc[common_ret_idx].dropna()

# --- 4b. GARCH VT weight (using OWN asset vol) ---
# Target vol: GLD=20%, USO=15%, SPY=8% (from N165 knowledge)
target_vols = {"GLD": 0.20, "USO": 0.15, "SPY": 0.08}

garch_weights = {}
for name in ["GLD", "USO", "SPY"]:
    cv = cond_vols[name].loc[common_ret_idx]
    ann_cv = cv * np.sqrt(252)
    w = np.minimum(target_vols[name] / ann_cv, 1.0)
    w = w.shift(1).dropna()
    garch_weights[name] = w

# --- 4c. Rolling 22-day vol VT ---
rolling_vol_weights = {}
for name, ret in [("GLD", gld_ret), ("USO", uso_ret), ("SPY", spy_ret)]:
    rv22 = ret.rolling(22).std() * np.sqrt(252)
    w = np.minimum(target_vols[name] / rv22, 1.0)
    w = w.shift(1).dropna()
    rolling_vol_weights[name] = w

# --- 4d. Hybrid VT (own vol + VIX regime guard) ---
# When VIX > 20: use min(own_vol_weight, 12/VIX_weight) — more conservative
# When VIX <= 20: use own_vol_weight
hybrid_weights = {}
for name in ["GLD", "USO", "SPY"]:
    gw = garch_weights[name]
    vw = vix_weight_lag
    ci = gw.index.intersection(vw.index)
    gw_a = gw.loc[ci]
    vw_a = vw.loc[ci]
    vix_a = vix.shift(1).loc[ci].dropna()
    ci2 = gw_a.index.intersection(vix_a.index)
    gw_a = gw_a.loc[ci2]
    vw_a = vw_a.loc[ci2]
    vix_a = vix_a.loc[ci2]

    hw = gw_a.copy()
    high_vix_mask = vix_a > 20
    hw[high_vix_mask] = np.minimum(gw_a[high_vix_mask], vw_a[high_vix_mask])
    hybrid_weights[name] = hw

# ============================================================
# 5. Backtest all strategies
# ============================================================
print("\n[5/8] Backtesting strategies...")

def backtest_strategy(returns, weights, name, strategy_name, tx_cost_bps=2):
    """Run VT backtest with transaction costs."""
    ci = returns.index.intersection(weights.index)
    ret = returns.loc[ci]
    w = weights.loc[ci]

    # Strategy return = w * ret + (1-w) * rf  (rf ≈ 0 for simplicity)
    strat_ret = w * ret

    # Transaction costs from weight changes
    w_diff = w.diff().abs()
    tx = w_diff * (tx_cost_bps / 10000)
    strat_ret_net = strat_ret - tx.fillna(0)

    # Cumulative
    cum = (1 + strat_ret_net).cumprod()
    total_ret = cum.iloc[-1] - 1
    n_years = len(ci) / 252
    ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    ann_vol = strat_ret_net.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # Max drawdown
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    max_dd = drawdown.min()

    # Calmar
    calmar = ann_ret / abs(max_dd) if max_dd != 0 else 0

    # Sortino
    downside = strat_ret_net[strat_ret_net < 0].std() * np.sqrt(252)
    sortino = ann_ret / downside if downside > 0 else 0

    # Average weight
    avg_w = w.mean()

    # Turnover
    turnover = w_diff.mean() * 252  # annualized

    result = {
        "asset": name,
        "strategy": strategy_name,
        "period": f"{ci[0].strftime('%Y-%m-%d')} to {ci[-1].strftime('%Y-%m-%d')}",
        "n_days": len(ci),
        "n_years": round(n_years, 2),
        "ann_return": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_dd, 4),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "avg_weight": round(avg_w, 3),
        "turnover_ann": round(turnover, 3),
    }
    return result, strat_ret_net

# Run backtests for each asset
all_results = []
strat_returns = {}

for name, ret in [("GLD", gld_ret), ("USO", uso_ret), ("SPY", spy_ret)]:
    print(f"\n  --- {name} ---")

    # a. Buy-and-hold
    bh_weights = pd.Series(1.0, index=ret.index)
    r, sr = backtest_strategy(ret, bh_weights, name, "Buy-and-Hold", tx_cost_bps=0)
    all_results.append(r)
    strat_returns[(name, "BH")] = sr
    print(f"    BH: Sharpe={r['sharpe']:.3f}, MDD={r['max_dd']:.1%}, "
          f"CAGR={r['ann_return']:.1%}")

    # b. 12/VIX VT
    r, sr = backtest_strategy(ret, vix_weight_lag, name, "12/VIX VT")
    all_results.append(r)
    strat_returns[(name, "12VIX")] = sr
    print(f"    12/VIX: Sharpe={r['sharpe']:.3f}, MDD={r['max_dd']:.1%}, "
          f"CAGR={r['ann_return']:.1%}, AvgW={r['avg_weight']:.2f}")

    # c. GARCH VT (own vol)
    if name in garch_weights:
        r, sr = backtest_strategy(ret, garch_weights[name], name,
                                  f"GARCH VT (target={target_vols[name]:.0%})")
        all_results.append(r)
        strat_returns[(name, "GARCH")] = sr
        print(f"    GARCH: Sharpe={r['sharpe']:.3f}, MDD={r['max_dd']:.1%}, "
              f"CAGR={r['ann_return']:.1%}, AvgW={r['avg_weight']:.2f}")

    # d. Rolling 22d vol VT
    if name in rolling_vol_weights:
        r, sr = backtest_strategy(ret, rolling_vol_weights[name], name,
                                  f"RollVol VT (target={target_vols[name]:.0%})")
        all_results.append(r)
        strat_returns[(name, "RollVol")] = sr
        print(f"    RollVol: Sharpe={r['sharpe']:.3f}, MDD={r['max_dd']:.1%}, "
              f"CAGR={r['ann_return']:.1%}, AvgW={r['avg_weight']:.2f}")

    # e. Hybrid VT (own vol + VIX guard)
    if name in hybrid_weights:
        r, sr = backtest_strategy(ret, hybrid_weights[name], name,
                                  "Hybrid VT (own vol + VIX guard)")
        all_results.append(r)
        strat_returns[(name, "Hybrid")] = sr
        print(f"    Hybrid: Sharpe={r['sharpe']:.3f}, MDD={r['max_dd']:.1%}, "
              f"CAGR={r['ann_return']:.1%}, AvgW={r['avg_weight']:.2f}")

# ============================================================
# 6. Statistical tests (DM test, bootstrap)
# ============================================================
print("\n[6/8] Statistical testing...")

def diebold_mariano_sharpe(ret1, ret2, name1, name2):
    """Test if Sharpe difference is significant using DM-like test."""
    ci = ret1.index.intersection(ret2.index)
    r1 = ret1.loc[ci].values
    r2 = ret2.loc[ci].values
    n = len(ci)

    # Sharpe difference via bootstrap
    n_boot = 10000
    sharpe_diffs = []
    for _ in range(n_boot):
        idx = np.random.choice(n, n, replace=True)
        s1 = r1[idx].mean() / r1[idx].std() * np.sqrt(252) if r1[idx].std() > 0 else 0
        s2 = r2[idx].mean() / r2[idx].std() * np.sqrt(252) if r2[idx].std() > 0 else 0
        sharpe_diffs.append(s1 - s2)

    sharpe_diffs = np.array(sharpe_diffs)
    mean_diff = sharpe_diffs.mean()
    se = sharpe_diffs.std()
    t_stat = mean_diff / se if se > 0 else 0
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))

    print(f"    {name1} vs {name2}: ΔSharpe={mean_diff:.3f}, "
          f"t={t_stat:.2f}, p={p_value:.4f}")
    return {
        "test": f"{name1} vs {name2}",
        "delta_sharpe": round(mean_diff, 4),
        "t_stat": round(t_stat, 3),
        "p_value": round(p_value, 4),
        "significant_5pct": p_value < 0.05,
        "significant_harvey": abs(t_stat) > 3.0,
    }

stat_tests = []
for name in ["GLD", "USO", "SPY"]:
    print(f"\n  --- {name} statistical tests ---")
    bh_key = (name, "BH")
    if bh_key not in strat_returns:
        continue

    for strat_key, strat_label in [("12VIX", "12/VIX"), ("GARCH", "GARCH VT"),
                                    ("RollVol", "RollVol VT"), ("Hybrid", "Hybrid VT")]:
        key = (name, strat_key)
        if key in strat_returns:
            r = diebold_mariano_sharpe(
                strat_returns[key], strat_returns[bh_key],
                f"{name} {strat_label}", f"{name} BH"
            )
            r["asset"] = name
            stat_tests.append(r)

# ============================================================
# 7. VIX relevance analysis
# ============================================================
print("\n[7/8] VIX relevance analysis...")

# Question: Does VIX predict commodity vol?
# Test: regression of realized vol on lagged VIX

for name, ret in [("GLD", gld_ret), ("USO", uso_ret), ("SPY", spy_ret)]:
    rv22 = ret.rolling(22).std() * np.sqrt(252)
    rv22 = rv22.dropna()
    vix_lag = vix.shift(1).loc[rv22.index].dropna()
    ci = rv22.index.intersection(vix_lag.index)

    y = rv22.loc[ci].values
    x = vix_lag.loc[ci].values / 100  # VIX in decimal

    # Simple regression: RV = a + b * VIX
    slope, intercept, r_value, p_value, std_err = stats.linregress(x, y)
    r_sq = r_value ** 2

    print(f"  {name} RV ~ VIX(lag1): R²={r_sq:.3f}, β={slope:.3f}, "
          f"p={p_value:.6f}")

# Rolling correlation of VIX with commodity vol
print("\n  Rolling 252-day correlation of VIX level with 22d realized vol:")
for name, ret in [("GLD", gld_ret), ("USO", uso_ret), ("SPY", spy_ret)]:
    rv22 = ret.rolling(22).std() * np.sqrt(252)
    ci2 = rv22.dropna().index.intersection(vix.index)
    rv_a = rv22.loc[ci2]
    vix_a = vix.loc[ci2]
    roll_corr = rv_a.rolling(252).corr(vix_a).dropna()
    print(f"    {name}: mean={roll_corr.mean():.3f}, "
          f"min={roll_corr.min():.3f}, max={roll_corr.max():.3f}, "
          f"std={roll_corr.std():.3f}")

# Regime analysis: VT performance in high vs low VIX
print("\n  VT performance by VIX regime:")
for name in ["GLD", "USO", "SPY"]:
    for strat_key, strat_label in [("12VIX", "12/VIX"), ("GARCH", "GARCH"),
                                    ("Hybrid", "Hybrid")]:
        key = (name, strat_key)
        bh_key = (name, "BH")
        if key not in strat_returns or bh_key not in strat_returns:
            continue

        sr = strat_returns[key]
        bh = strat_returns[bh_key]
        ci = sr.index.intersection(bh.index).intersection(vix.index)

        sr_a = sr.loc[ci]
        bh_a = bh.loc[ci]
        vix_a = vix.loc[ci]

        high_vix = vix_a > 20
        low_vix = ~high_vix

        if high_vix.sum() > 50 and low_vix.sum() > 50:
            sr_high = sr_a[high_vix].mean() * 252
            bh_high = bh_a[high_vix].mean() * 252
            sr_low = sr_a[low_vix].mean() * 252
            bh_low = bh_a[low_vix].mean() * 252

            print(f"    {name} {strat_label}: "
                  f"High VIX({high_vix.sum()}d) strat={sr_high:.1%} vs BH={bh_high:.1%} "
                  f"| Low VIX({low_vix.sum()}d) strat={sr_low:.1%} vs BH={bh_low:.1%}")

# ============================================================
# 8. Compile and save results
# ============================================================
print("\n[8/8] Compiling results...")

# Summary table
print("\n" + "=" * 90)
print("RESULTS SUMMARY")
print("=" * 90)
print(f"{'Asset':<6} {'Strategy':<32} {'Sharpe':>7} {'CAGR':>8} {'MaxDD':>8} "
      f"{'Calmar':>8} {'AvgW':>6}")
print("-" * 90)
for r in all_results:
    print(f"{r['asset']:<6} {r['strategy']:<32} {r['sharpe']:>7.3f} "
          f"{r['ann_return']:>7.1%} {r['max_dd']:>7.1%} "
          f"{r['calmar']:>8.3f} {r['avg_weight']:>6.2f}")

# Key findings
print("\n" + "=" * 70)
print("KEY FINDINGS")
print("=" * 70)

# For each asset, find best strategy
for name in ["GLD", "USO", "SPY"]:
    asset_results = [r for r in all_results if r['asset'] == name]
    bh = [r for r in asset_results if r['strategy'] == 'Buy-and-Hold'][0]
    vt_results = [r for r in asset_results if r['strategy'] != 'Buy-and-Hold']
    if vt_results:
        best_vt = max(vt_results, key=lambda x: x['sharpe'])
        sharpe_diff = best_vt['sharpe'] - bh['sharpe']
        mdd_diff = best_vt['max_dd'] - bh['max_dd']
        print(f"\n  {name}:")
        print(f"    BH Sharpe={bh['sharpe']:.3f}, Best VT={best_vt['strategy']} "
              f"Sharpe={best_vt['sharpe']:.3f} (Δ={sharpe_diff:+.3f})")
        print(f"    BH MDD={bh['max_dd']:.1%}, Best VT MDD={best_vt['max_dd']:.1%} "
              f"(Δ={mdd_diff:+.1%})")

        # Does VIX-based VT work for this commodity?
        vix_vt = [r for r in asset_results if '12/VIX' in r['strategy']]
        own_vt = [r for r in asset_results if 'GARCH' in r['strategy']]
        if vix_vt and own_vt:
            vix_s = vix_vt[0]['sharpe']
            own_s = own_vt[0]['sharpe']
            print(f"    12/VIX Sharpe={vix_s:.3f} vs Own-vol GARCH Sharpe={own_s:.3f}"
                  f" → {'Own-vol wins' if own_s > vix_s else 'VIX wins'}")

# Save results
output = {
    "experiment_id": "K662",
    "title": "Does VT Framework Work for Commodities?",
    "type": "empirical_analysis",
    "data_source": "yfinance (GLD, USO, SPY, ^VIX)",
    "period": f"{common_ret_idx[0].strftime('%Y-%m-%d')} to "
              f"{common_ret_idx[-1].strftime('%Y-%m-%d')}",
    "n_observations": len(common_ret_idx),
    "timestamp": datetime.now().isoformat(),
    "methodology": {
        "strategies": [
            "Buy-and-hold (benchmark)",
            "12/VIX VT (equity vol proxy)",
            "GJR-GARCH VT (own asset vol, target vol from N165)",
            "Rolling 22d vol VT (simple own-vol)",
            "Hybrid VT (own vol + VIX regime guard, VIX>20 takes min)"
        ],
        "target_vols": target_vols,
        "transaction_cost_bps": 2,
        "garch_model": "GJR-GARCH(1,1), Student-t, window=full sample",
        "bootstrap_reps": 10000,
    },
    "backtest_results": all_results,
    "statistical_tests": stat_tests,
    "garch_params": {},
    "key_findings": [],
    "limitations": [
        "USO has severe contango drag and 2020 restructure (reverse split) — "
        "results reflect ETF structure issues, not pure commodity exposure",
        "GLD in 2020-2026 was in an extreme bull market — results may not "
        "generalize to normal regimes",
        "VIX as commodity vol proxy tested only with 12/VIX rule — other "
        "VIX-based rules (e.g., VIX term structure) not tested",
        "Target vols from N165 may not be optimal for commodity VT — "
        "further calibration needed",
        "No transaction cost for buy-and-hold; 2bps for VT strategies (conservative)"
    ],
    "references": [
        "Moreira & Muir (2017, JoF): Volatility-Managed Portfolios",
        "Chevallier & Ielpo (2017): Commodity inverted leverage",
        "Baur & Lucey (2010, JFE): Is gold a safe haven?",
        "Gorton & Rouwenhorst (2006, FAJ): Facts and Fantasies about Commodity Futures",
        "Knowledge base: K634, K476, N165, N74, K649"
    ]
}

# Add GARCH params
for name in ["GLD", "USO", "SPY"]:
    res = garch_results[name]
    p = res.params
    output["garch_params"][name] = {
        "omega": round(float(p.get('omega', 0)), 6),
        "alpha": round(float(p.get('alpha[1]', 0)), 4),
        "gamma": round(float(p.get('gamma[1]', 0)), 4),
        "beta": round(float(p.get('beta[1]', 0)), 4),
        "persistence": round(float(p.get('alpha[1]', 0) + p.get('gamma[1]', 0)/2 + p.get('beta[1]', 0)), 4),
        "loglikelihood": round(float(res.loglikelihood), 1),
    }

# Build key findings
findings = []
for name in ["GLD", "USO", "SPY"]:
    asset_results = [r for r in all_results if r['asset'] == name]
    bh = [r for r in asset_results if r['strategy'] == 'Buy-and-Hold'][0]
    vt_12vix = [r for r in asset_results if '12/VIX' in r['strategy']]
    vt_garch = [r for r in asset_results if 'GARCH' in r['strategy']]
    vt_hybrid = [r for r in asset_results if 'Hybrid' in r['strategy']]

    finding = {
        "asset": name,
        "bh_sharpe": bh['sharpe'],
        "bh_mdd": bh['max_dd'],
    }
    if vt_12vix:
        finding["vix_vt_sharpe"] = vt_12vix[0]['sharpe']
        finding["vix_vt_mdd"] = vt_12vix[0]['max_dd']
        finding["vix_vt_vs_bh"] = round(vt_12vix[0]['sharpe'] - bh['sharpe'], 3)
    if vt_garch:
        finding["garch_vt_sharpe"] = vt_garch[0]['sharpe']
        finding["garch_vt_mdd"] = vt_garch[0]['max_dd']
        finding["garch_vt_vs_bh"] = round(vt_garch[0]['sharpe'] - bh['sharpe'], 3)
    if vt_hybrid:
        finding["hybrid_vt_sharpe"] = vt_hybrid[0]['sharpe']
        finding["hybrid_vt_mdd"] = vt_hybrid[0]['max_dd']
        finding["hybrid_vt_vs_bh"] = round(vt_hybrid[0]['sharpe'] - bh['sharpe'], 3)

    # Determine best approach
    vt_all = [(r['strategy'], r['sharpe']) for r in asset_results if r['strategy'] != 'Buy-and-Hold']
    if vt_all:
        best = max(vt_all, key=lambda x: x[1])
        finding["best_strategy"] = best[0]
        finding["best_sharpe"] = best[1]
        finding["vix_based_works"] = (vt_12vix[0]['sharpe'] > bh['sharpe']) if vt_12vix else None

    findings.append(finding)

output["key_findings"] = findings

# Conclusions
conclusions = []
for f in findings:
    name = f["asset"]
    if f.get("vix_based_works") is True:
        conclusions.append(f"{name}: VIX-based 12/VIX VT works "
                          f"(Sharpe {f.get('vix_vt_sharpe', 0):.3f} vs BH {f['bh_sharpe']:.3f})")
    elif f.get("vix_based_works") is False:
        conclusions.append(f"{name}: VIX-based 12/VIX VT does NOT improve Sharpe "
                          f"({f.get('vix_vt_sharpe', 0):.3f} vs BH {f['bh_sharpe']:.3f}), "
                          f"own-vol better ({f.get('garch_vt_sharpe', 'N/A')})")
    if f.get("best_strategy"):
        conclusions.append(f"{name} best: {f['best_strategy']} (Sharpe {f['best_sharpe']:.3f})")

output["conclusions"] = conclusions

# Save
output_path = Path(__file__).parent / "k662_results.json"
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n✅ Results saved to {output_path}")
print(f"\nConclusions:")
for c in conclusions:
    print(f"  • {c}")

print("\n" + "=" * 70)
print("K662 COMPLETE")
print("=" * 70)
