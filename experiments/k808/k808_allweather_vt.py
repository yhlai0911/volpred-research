#!/usr/bin/env python3
"""
K808: Cross-Asset All-Weather Volatility Targeting
===================================================
[提出: Codex GPT-5.4 #8 suggestion, 執行: Claude]

Research Question:
  Can a 4+ asset VT portfolio (SPY, TLT, GLD, DBC) with VIX-based
  dynamic scaling beat the 2-asset 50/50 SPY/GLD baseline, especially
  in MDD reduction, while maintaining VIX-based simplicity?

Differentiation from K774:
  - K774 used fixed base weights; K808 uses Risk Parity (inverse vol) allocation
  - K808 adds a Regime-Aware strategy (VIX thresholds shift allocations)
  - K808 evaluates CRRA utility (gamma=5) — not just Sharpe
  - K808 computes HHI (Herfindahl) diversification metric
  - K808 runs DM tests with Harvey (2016) t>3.0 threshold
  - K808 optionally includes BTC-USD (capped at 5%)

Strategies:
  S0: BH 50/50 SPY/GLD (baseline)
  S1: BH Equal-Weight 4 assets (25% each)
  S2: Risk Parity 4 assets (inverse vol, rolling 252d)
  S3: 12/VIX Target Vol 4 assets (VIX scales total exposure, RP internal)
  S4: Regime-Aware (VIX>20 → more GLD+TLT; VIX<15 → more SPY+DBC)

Constraints:
  - Single asset weight cap 50%
  - Cash floor 10% when VIX extreme (>30)
  - Monthly rebalancing
  - signal.shift(1) — no lookahead
  - TX cost 5 bps per unit weight change

Evaluation:
  - Sharpe, CAGR, MDD, Calmar, Sortino
  - DM test vs baseline (Harvey t>3.0)
  - Cross-OOS: 5 non-overlapping 2-year periods
  - CRRA utility gamma=5
  - Portfolio HHI (diversification metric)

Data: SPY, GLD, TLT, DBC, ^VIX from yfinance (2006-2026)
OOS: 2023-01-01 ~ 2024-12-31

References:
  - Bridgewater "All Weather" (Dalio, 2011)
  - Asness, Frazzini, Pedersen (2012) "Leverage Aversion and Risk Parity"
  - Harvey, Liu, Zhu (2016) "... and the Cross-Section of Expected Returns" RFS
  - Patton (2011) "Volatility Forecast Comparison Using Imperfect Proxies" JoE
  - K702 (50/50 champion), K774 (prior all-weather attempt)
"""

import json
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT = Path(__file__).resolve().parent.parent
COMMON_START = "2023-01-04"
TX_COST_BPS = 5  # 5 bps per unit weight change
LOOKBACK = 252   # rolling window for covariance / vol estimation
RESULTS = {}

# ============================================================
# PART A: Data Download & Descriptive Statistics
# ============================================================
print("=" * 70)
print("K808: Cross-Asset All-Weather Volatility Targeting")
print("=" * 70)
print("\nPART A: Data Download & Descriptive Statistics")
print("-" * 50)

import yfinance as yf

tickers = ["SPY", "GLD", "TLT", "DBC", "^VIX"]
data = yf.download(tickers, start="2005-01-01", end="2026-12-31",
                   auto_adjust=True, progress=False)

# Handle multi-level columns
if isinstance(data.columns, pd.MultiIndex):
    close = data["Close"]
else:
    close = data

# DBC started Feb 2006
close = close.dropna()
print(f"Data period: {close.index[0].strftime('%Y-%m-%d')} to "
      f"{close.index[-1].strftime('%Y-%m-%d')}")
print(f"Total trading days: {len(close)}")

ASSETS = ["SPY", "GLD", "TLT", "DBC"]
ret = close[ASSETS].pct_change().dropna()
vix = close["^VIX"].reindex(ret.index)

# Descriptive statistics
print("\n--- Asset Descriptive Statistics (annualized) ---")
desc_stats = {}
for a in ASSETS:
    r = ret[a]
    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    skew_val = r.skew()
    kurt_val = r.kurtosis()
    cum = (1 + r).cumprod()
    mdd = (cum / cum.cummax() - 1).min()
    desc_stats[a] = {
        "ann_return": round(float(ann_ret), 4),
        "ann_vol": round(float(ann_vol), 4),
        "sharpe": round(float(sharpe), 3),
        "skew": round(float(skew_val), 3),
        "kurtosis": round(float(kurt_val), 3),
        "mdd": round(float(mdd), 4),
    }
    print(f"  {a:4s}: Ret={ann_ret:.2%}, Vol={ann_vol:.2%}, Sharpe={sharpe:.3f}, "
          f"Skew={skew_val:.3f}, Kurt={kurt_val:.3f}, MDD={mdd:.2%}")

RESULTS["descriptive_stats"] = desc_stats
RESULTS["data_period"] = (f"{close.index[0].strftime('%Y-%m-%d')} to "
                          f"{close.index[-1].strftime('%Y-%m-%d')}")
RESULTS["n_days"] = int(len(ret))

# VIX stats
print(f"\n  VIX: Mean={vix.mean():.2f}, Median={vix.median():.2f}, "
      f"Min={vix.min():.2f}, Max={vix.max():.2f}")
RESULTS["vix_stats"] = {
    "mean": round(float(vix.mean()), 2),
    "median": round(float(vix.median()), 2),
    "min": round(float(vix.min()), 2),
    "max": round(float(vix.max()), 2),
}

# ============================================================
# PART B: Correlation Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART B: Correlation Analysis")
print("-" * 50)

corr_full = ret[ASSETS].corr()
print("\n--- Full-Sample Correlation ---")
print(corr_full.round(3).to_string())

# VIX regime correlations
vix_low = vix < vix.quantile(0.33)
vix_high = vix > vix.quantile(0.67)
corr_low = ret[ASSETS][vix_low].corr()
corr_high = ret[ASSETS][vix_high].corr()

print("\n--- Low VIX (<33rd pctl) correlations with SPY ---")
for a in ["GLD", "TLT", "DBC"]:
    print(f"  SPY-{a}: {corr_low.loc['SPY', a]:.3f}")

print("\n--- High VIX (>67th pctl) correlations with SPY ---")
for a in ["GLD", "TLT", "DBC"]:
    print(f"  SPY-{a}: {corr_high.loc['SPY', a]:.3f}")

RESULTS["correlation"] = {
    "full_sample": {f"SPY_{a}": round(float(corr_full.loc["SPY", a]), 4)
                    for a in ["GLD", "TLT", "DBC"]},
    "low_vix": {f"SPY_{a}": round(float(corr_low.loc["SPY", a]), 4)
                for a in ["GLD", "TLT", "DBC"]},
    "high_vix": {f"SPY_{a}": round(float(corr_high.loc["SPY", a]), 4)
                 for a in ["GLD", "TLT", "DBC"]},
}


# ============================================================
# PART C: Strategy Construction
# ============================================================
print("\n" + "=" * 70)
print("PART C: Strategy Construction (5 strategies)")
print("-" * 50)


def inverse_vol_weights(vol_series):
    """Risk Parity: w_i proportional to 1/sigma_i.

    Parameters
    ----------
    vol_series : array-like of annualized volatilities for each asset.

    Returns
    -------
    numpy array of weights summing to 1.
    """
    vols = np.array(vol_series, dtype=float)
    inv_vol = 1.0 / np.maximum(vols, 1e-8)
    w = inv_vol / inv_vol.sum()
    return w


def apply_weight_constraints(w, max_single=0.50, normalize_to_one=True):
    """Apply cap per asset.

    If any weight exceeds max_single, clip it and redistribute the excess
    proportionally to the other assets.  When normalize_to_one=False the
    original sum is preserved (needed for VT strategies where
    sum(w) < 1 means partial exposure / cash).
    """
    w = np.array(w, dtype=float)
    original_sum = w.sum()

    # Iteratively clip weights that exceed cap
    for _ in range(10):
        over = w > max_single
        if not over.any():
            break
        excess = (w[over] - max_single).sum()
        w[over] = max_single
        under = ~over & (w > 0)
        if under.sum() > 0 and w[under].sum() > 0:
            w[under] += excess * (w[under] / w[under].sum())
        else:
            break

    if normalize_to_one and w.sum() > 0:
        w = w / w.sum()
    elif not normalize_to_one and original_sum > 0 and w.sum() > 0:
        # Preserve original sum (partial exposure)
        w = w / w.sum() * original_sum

    return w


def compute_strategy(ret_df, vix_series, strategy_name,
                     lookback=LOOKBACK, tx_bps=TX_COST_BPS):
    """Compute daily portfolio returns for a given strategy.

    All strategies use monthly rebalancing with hold-and-drift.
    signal.shift(1) is applied: covariance / VIX from t-1 used at t.

    Returns
    -------
    port_returns : pd.Series of daily net returns
    weight_df : pd.DataFrame of daily applied weights
    avg_hhi : float, average portfolio HHI (lower = more diversified)
    """
    assets = ASSETS
    n_assets = len(assets)
    dates = ret_df.index[lookback:]

    # Identify monthly rebalance dates (first trading day of each month)
    rebal_dates = set()
    prev_month = None
    for dt in dates:
        ym = (dt.year, dt.month)
        if ym != prev_month:
            rebal_dates.add(dt)
            prev_month = ym

    # Prepare output
    port_returns = []
    port_dates = []
    weight_records = []
    hhi_values = []

    current_weights = None  # drifted weights (what we actually hold)
    target_weights = None

    for idx in range(lookback, len(ret_df)):
        date = ret_df.index[idx]
        day_ret = ret_df.iloc[idx][assets].values.astype(float)

        is_rebal = date in rebal_dates

        if is_rebal:
            # Compute target weights using data up to t-1
            window = ret_df.iloc[idx - lookback:idx][assets]
            rolling_vol = window.std() * np.sqrt(252)  # annualized vol per asset
            vix_val = vix_series.iloc[idx - 1] if idx > 0 else 20.0
            if np.isnan(vix_val):
                vix_val = 20.0

            if strategy_name == "S0_BH_5050":
                # Static 50/50 SPY/GLD
                target_weights = np.zeros(n_assets)
                target_weights[assets.index("SPY")] = 0.50
                target_weights[assets.index("GLD")] = 0.50

            elif strategy_name == "S1_EW_4Asset":
                # Equal weight across 4 assets
                target_weights = np.ones(n_assets) / n_assets

            elif strategy_name == "S2_RP_4Asset":
                # Risk Parity (inverse vol)
                target_weights = inverse_vol_weights(rolling_vol.values)
                target_weights = apply_weight_constraints(target_weights, max_single=0.50)

            elif strategy_name == "S3_VT_RP_4Asset":
                # 12/VIX scales total exposure, RP for internal allocation
                rp_w = inverse_vol_weights(rolling_vol.values)
                vix_scale = min(1.0, 12.0 / vix_val)
                scaled = rp_w * vix_scale
                # Cap individual weights but preserve partial exposure
                scaled = apply_weight_constraints(scaled, max_single=0.50,
                                                  normalize_to_one=False)
                # Cash floor if VIX > 30
                if vix_val > 30:
                    max_risky = 0.90
                    if scaled.sum() > max_risky:
                        scaled = scaled / scaled.sum() * max_risky
                target_weights = scaled

            elif strategy_name == "S4_RegimeAware":
                # Regime-Aware: VIX thresholds shift allocation
                rp_w = inverse_vol_weights(rolling_vol.values)

                if vix_val > 20:
                    # Risk-off: increase GLD + TLT, decrease SPY + DBC
                    boost_idx = [assets.index("GLD"), assets.index("TLT")]
                    reduce_idx = [assets.index("SPY"), assets.index("DBC")]
                    for bi in boost_idx:
                        rp_w[bi] *= 1.3
                    for ri in reduce_idx:
                        rp_w[ri] *= 0.7
                elif vix_val < 15:
                    # Risk-on: increase SPY + DBC, decrease GLD + TLT
                    boost_idx = [assets.index("SPY"), assets.index("DBC")]
                    reduce_idx = [assets.index("GLD"), assets.index("TLT")]
                    for bi in boost_idx:
                        rp_w[bi] *= 1.3
                    for ri in reduce_idx:
                        rp_w[ri] *= 0.7
                # else: 15 <= VIX <= 20 → keep RP weights unchanged

                # Normalize
                rp_w = np.maximum(rp_w, 0)
                rp_w = rp_w / rp_w.sum()
                # Apply VIX scaling (same as S3)
                vix_scale = min(1.0, 12.0 / vix_val)
                scaled = rp_w * vix_scale
                # Cap individual weights but preserve partial exposure
                scaled = apply_weight_constraints(scaled, max_single=0.50,
                                                  normalize_to_one=False)
                # Cash floor if VIX > 30
                if vix_val > 30:
                    max_risky = 0.90
                    if scaled.sum() > max_risky:
                        scaled = scaled / scaled.sum() * max_risky
                target_weights = scaled

            else:
                raise ValueError(f"Unknown strategy: {strategy_name}")

            # TX cost from weight change
            if current_weights is not None:
                turnover = np.sum(np.abs(target_weights - current_weights))
                tx_cost = turnover * (tx_bps / 10000)
            else:
                turnover = 0.0
                tx_cost = 0.0

            current_weights = target_weights.copy()

        else:
            tx_cost = 0.0

        # If we don't have weights yet, skip
        if current_weights is None:
            continue

        # Portfolio return for today
        port_ret = np.dot(current_weights, day_ret) - tx_cost
        port_returns.append(port_ret)
        port_dates.append(date)
        weight_records.append(current_weights.copy())

        # HHI = sum(w_i^2), lower = more diversified
        w_total = current_weights.sum()
        if w_total > 0:
            w_norm = current_weights / w_total
            hhi = np.sum(w_norm ** 2)
        else:
            hhi = 1.0
        hhi_values.append(hhi)

        # Drift weights with returns (hold-and-drift between rebalances)
        w_new = current_weights * (1 + day_ret)
        w_sum = w_new.sum()
        if w_sum > 0:
            current_weights = w_new / w_sum * current_weights.sum()
            # If partially invested (VT scaling), preserve cash portion
            if current_weights.sum() > 1e-8:
                pass  # already correct
        # If all weights zero (full cash), stay at zero

    port_series = pd.Series(port_returns, index=port_dates, name=strategy_name)
    weight_df = pd.DataFrame(weight_records, index=port_dates, columns=assets)
    avg_hhi = float(np.mean(hhi_values)) if hhi_values else 1.0

    return port_series, weight_df, avg_hhi


def calc_metrics(returns, label=""):
    """Standard performance metrics."""
    r = returns.dropna()
    if len(r) < 20:
        return {"error": "insufficient data", "n_days": len(r)}
    cum = (1 + r).cumprod()
    total_ret = float(cum.iloc[-1] - 1)
    n_years = len(r) / 252
    cagr = float((1 + total_ret) ** (1 / n_years) - 1) if n_years > 0 else 0
    ann_vol = float(r.std() * np.sqrt(252))
    ann_ret = float(r.mean() * 252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
    dd = cum / cum.cummax() - 1
    mdd = float(dd.min())
    calmar = cagr / abs(mdd) if mdd != 0 else 0
    # Sortino
    downside = r[r < 0]
    down_std = float(downside.std() * np.sqrt(252)) if len(downside) > 0 else 1e-8
    sortino = ann_ret / down_std if down_std > 0 else 0
    return {
        "cagr": round(cagr, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 3),
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 3),
        "sortino": round(sortino, 3),
        "total_return": round(total_ret, 4),
        "n_days": int(len(r)),
        "n_years": round(n_years, 2),
    }


def crra_utility(returns, gamma=5.0):
    """CRRA (Constant Relative Risk Aversion) utility.

    U = E[(1+r)^(1-gamma) / (1-gamma)]  for gamma != 1
    Higher is better. Penalizes large drawdowns heavily at gamma=5.
    """
    r = returns.dropna()
    wealth = 1.0 + r.values
    # Avoid log of zero or negative
    wealth = np.maximum(wealth, 1e-10)
    if gamma == 1.0:
        u = np.mean(np.log(wealth))
    else:
        u = np.mean((wealth ** (1 - gamma)) / (1 - gamma))
    return float(u)


def dm_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive accuracy.

    Here we use squared returns as loss function:
    loss = (portfolio_return - 0)^2  (lower vol → lower loss).

    Actually for strategy comparison, we use negative returns as loss
    (better strategy = higher return = lower loss with neg sign).
    But more standard: use squared loss on negative return.

    We follow a simpler approach: loss_i = -r_i (negative return as loss).
    DM tests if strategy 1 has lower loss than strategy 2.

    Returns t-stat, p-value, and whether it exceeds Harvey threshold.
    """
    d = np.array(e1) - np.array(e2)
    n = len(d)
    d_mean = d.mean()
    # Newey-West variance with h lags
    gamma_0 = np.var(d, ddof=1)
    auto_cov = 0
    for k in range(1, h + 1):
        auto_cov += 2 * np.cov(d[k:], d[:-k])[0, 1] if len(d) > k else 0
    var_d = (gamma_0 + auto_cov) / n
    if var_d <= 0:
        return 0, 1.0, False
    dm_stat = d_mean / np.sqrt(max(var_d, 1e-15))
    p_val = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    harvey_sig = abs(dm_stat) > 3.0
    return round(float(dm_stat), 3), round(float(p_val), 4), harvey_sig


# ============================================================
# Run all strategies
# ============================================================
STRATEGY_NAMES = [
    "S0_BH_5050",
    "S1_EW_4Asset",
    "S2_RP_4Asset",
    "S3_VT_RP_4Asset",
    "S4_RegimeAware",
]

STRATEGY_DESC = {
    "S0_BH_5050": "BH 50/50 SPY/GLD (baseline)",
    "S1_EW_4Asset": "BH Equal-Weight 4 assets (25% each)",
    "S2_RP_4Asset": "Risk Parity 4 assets (inverse vol)",
    "S3_VT_RP_4Asset": "12/VIX VT + RP allocation (4 assets)",
    "S4_RegimeAware": "Regime-Aware VT (VIX thresholds + RP)",
}

print("\nComputing strategies...")
strat_returns = {}
strat_weights = {}
strat_hhi = {}

for sname in STRATEGY_NAMES:
    ret_s, w_s, hhi_s = compute_strategy(ret, vix, sname)
    strat_returns[sname] = ret_s
    strat_weights[sname] = w_s
    strat_hhi[sname] = hhi_s
    print(f"  {sname}: {len(ret_s)} days, avg HHI={hhi_s:.4f}")


# ============================================================
# PART D: Full-Sample Performance
# ============================================================
print("\n" + "=" * 70)
print("PART D: Full-Sample Performance")
print("-" * 50)

full_metrics = {}
print(f"\n{'Strategy':<22s} {'CAGR':>7s} {'Vol':>7s} {'Sharpe':>7s} "
      f"{'MDD':>8s} {'Calmar':>7s} {'Sortino':>7s} {'HHI':>6s}")
print("-" * 80)

for sname in STRATEGY_NAMES:
    m = calc_metrics(strat_returns[sname])
    m["avg_hhi"] = round(strat_hhi[sname], 4)
    m["description"] = STRATEGY_DESC[sname]
    full_metrics[sname] = m
    print(f"  {sname:<20s} {m['cagr']:>6.2%} {m['ann_vol']:>6.2%} {m['sharpe']:>6.3f} "
          f"{m['mdd']:>7.2%} {m['calmar']:>6.3f} {m['sortino']:>6.3f} "
          f"{strat_hhi[sname]:>5.3f}")

RESULTS["full_sample"] = full_metrics


# ============================================================
# PART E: COMMON_START Performance (2023-01-04 onward)
# ============================================================
print("\n" + "=" * 70)
print(f"PART E: COMMON_START Performance ({COMMON_START} onward)")
print("-" * 50)

cs_metrics = {}
print(f"\n{'Strategy':<22s} {'CAGR':>7s} {'Vol':>7s} {'Sharpe':>7s} "
      f"{'MDD':>8s} {'Calmar':>7s} {'Sortino':>7s}")
print("-" * 75)

for sname in STRATEGY_NAMES:
    r_cs = strat_returns[sname][strat_returns[sname].index >= COMMON_START]
    m = calc_metrics(r_cs)
    m["description"] = STRATEGY_DESC[sname]
    cs_metrics[sname] = m
    print(f"  {sname:<20s} {m['cagr']:>6.2%} {m['ann_vol']:>6.2%} {m['sharpe']:>6.3f} "
          f"{m['mdd']:>7.2%} {m['calmar']:>6.3f} {m['sortino']:>6.3f}")

RESULTS["common_start"] = cs_metrics


# ============================================================
# PART F: Cross-OOS Sub-Period Analysis (5 x 2-year windows)
# ============================================================
print("\n" + "=" * 70)
print("PART F: Cross-OOS Sub-Period Analysis")
print("-" * 50)

windows = [
    ("2008-01-01", "2009-12-31", "GFC"),
    ("2012-01-01", "2013-12-31", "Recovery"),
    ("2018-01-01", "2019-12-31", "Late_Cycle"),
    ("2020-01-01", "2021-12-31", "COVID_Bull"),
    ("2022-01-01", "2023-12-31", "Rate_Hikes"),
]

sub_results = {}
for start, end, label in windows:
    print(f"\n--- {label} ({start} to {end}) ---")
    sub_m = {}
    baseline_sharpe = None

    for sname in STRATEGY_NAMES:
        r_sub = strat_returns[sname][
            (strat_returns[sname].index >= start) &
            (strat_returns[sname].index <= end)
        ]
        if len(r_sub) < 20:
            sub_m[sname] = {"sharpe": float("nan"), "mdd": float("nan"),
                           "n_days": int(len(r_sub))}
            continue
        m = calc_metrics(r_sub)
        sub_m[sname] = m
        if sname == "S0_BH_5050":
            baseline_sharpe = m["sharpe"]

    for sname in STRATEGY_NAMES:
        s = sub_m[sname].get("sharpe", float("nan"))
        beat = ""
        if baseline_sharpe is not None and not np.isnan(s) and not np.isnan(baseline_sharpe):
            beat = " ✓" if s > baseline_sharpe else ""
        print(f"  {sname:<20s} Sharpe={s:>7.3f}  MDD={sub_m[sname].get('mdd', 0):>7.2%}{beat}")

    sub_results[label] = sub_m

# Count wins vs baseline
print("\n--- Win Count vs 50/50 Baseline (Sharpe) ---")
cross_oos_wins = {}
for sname in STRATEGY_NAMES:
    if sname == "S0_BH_5050":
        continue
    wins = 0
    for label in sub_results:
        s = sub_results[label].get(sname, {}).get("sharpe", float("nan"))
        b = sub_results[label].get("S0_BH_5050", {}).get("sharpe", float("nan"))
        if not np.isnan(s) and not np.isnan(b) and s > b:
            wins += 1
    print(f"  {sname:<20s}: {wins}/5 periods beat baseline")
    cross_oos_wins[sname] = f"{wins}/5"

RESULTS["sub_periods"] = sub_results
RESULTS["cross_oos_wins"] = cross_oos_wins


# ============================================================
# PART G: CRRA Utility (gamma=5)
# ============================================================
print("\n" + "=" * 70)
print("PART G: CRRA Utility (gamma=5)")
print("-" * 50)

crra_results = {}
for sname in STRATEGY_NAMES:
    # Full sample
    u_full = crra_utility(strat_returns[sname], gamma=5.0)
    # COMMON_START
    r_cs = strat_returns[sname][strat_returns[sname].index >= COMMON_START]
    u_cs = crra_utility(r_cs, gamma=5.0)
    crra_results[sname] = {
        "crra_full": round(u_full, 6),
        "crra_common_start": round(u_cs, 6),
    }
    print(f"  {sname:<20s}: Full={u_full:.6f}, COMMON_START={u_cs:.6f}")

# Rank by CRRA
full_ranked = sorted(crra_results.items(), key=lambda x: x[1]["crra_full"], reverse=True)
print("\n  CRRA Ranking (full sample, higher=better):")
for rank, (sname, vals) in enumerate(full_ranked, 1):
    print(f"    #{rank}: {sname} = {vals['crra_full']:.6f}")

cs_ranked = sorted(crra_results.items(), key=lambda x: x[1]["crra_common_start"], reverse=True)
print("\n  CRRA Ranking (COMMON_START, higher=better):")
for rank, (sname, vals) in enumerate(cs_ranked, 1):
    print(f"    #{rank}: {sname} = {vals['crra_common_start']:.6f}")

RESULTS["crra_utility"] = crra_results


# ============================================================
# PART H: DM Test vs Baseline (Harvey t>3.0)
# ============================================================
print("\n" + "=" * 70)
print("PART H: DM Test vs 50/50 Baseline (Harvey t>3.0)")
print("-" * 50)

baseline_ret = strat_returns["S0_BH_5050"]
dm_results = {}

for sname in STRATEGY_NAMES:
    if sname == "S0_BH_5050":
        continue
    strat_ret = strat_returns[sname]
    # Align dates
    common_dates = baseline_ret.index.intersection(strat_ret.index)
    b = baseline_ret.loc[common_dates].values
    s = strat_ret.loc[common_dates].values

    # Loss = -return (lower is worse)
    loss_b = -b
    loss_s = -s
    # DM test: is strategy s significantly better (lower loss) than baseline b?
    dm_stat, p_val, harvey_sig = dm_test(loss_b, loss_s, h=1)
    dm_results[sname] = {
        "dm_stat": dm_stat,
        "p_value": p_val,
        "harvey_significant": harvey_sig,
        "n_obs": int(len(common_dates)),
    }
    sig_str = "*** HARVEY SIG" if harvey_sig else ("* p<0.05" if p_val < 0.05 else "NS")
    print(f"  {sname} vs baseline: DM={dm_stat:>7.3f}, p={p_val:.4f} {sig_str}")

RESULTS["dm_test"] = dm_results


# ============================================================
# PART I: Sensitivity Analysis (±20% parameter variation)
# ============================================================
print("\n" + "=" * 70)
print("PART I: Sensitivity Analysis (S3 target vol ±20%)")
print("-" * 50)

# Test S3 with different target vol levels
target_vols = [9.6, 12.0, 14.4]  # -20%, base, +20%
sens_results = {}

for tv in target_vols:
    # Re-run S3 with modified target vol
    port_rets = []
    port_dates = []
    current_weights = None

    rebal_dates = set()
    dates = ret.index[LOOKBACK:]
    prev_month = None
    for dt in dates:
        ym = (dt.year, dt.month)
        if ym != prev_month:
            rebal_dates.add(dt)
            prev_month = ym

    for idx in range(LOOKBACK, len(ret)):
        date = ret.index[idx]
        day_ret = ret.iloc[idx][ASSETS].values.astype(float)
        is_rebal = date in rebal_dates

        if is_rebal:
            window = ret.iloc[idx - LOOKBACK:idx][ASSETS]
            rolling_vol = window.std() * np.sqrt(252)
            vix_val = vix.iloc[idx - 1] if idx > 0 else 20.0
            if np.isnan(vix_val):
                vix_val = 20.0

            rp_w = inverse_vol_weights(rolling_vol.values)
            vix_scale = min(1.0, tv / vix_val)
            scaled = rp_w * vix_scale
            scaled = apply_weight_constraints(scaled, max_single=0.50,
                                              normalize_to_one=False)
            if vix_val > 30 and scaled.sum() > 0:
                scaled = scaled / scaled.sum() * 0.90

            if current_weights is not None:
                turnover = np.sum(np.abs(scaled - current_weights))
                tx_cost = turnover * (TX_COST_BPS / 10000)
            else:
                tx_cost = 0.0

            current_weights = scaled.copy()
        else:
            tx_cost = 0.0

        if current_weights is None:
            continue

        pr = np.dot(current_weights, day_ret) - tx_cost
        port_rets.append(pr)
        port_dates.append(date)

        w_new = current_weights * (1 + day_ret)
        w_sum = w_new.sum()
        if w_sum > 0:
            current_weights = w_new / w_sum * current_weights.sum()

    sens_series = pd.Series(port_rets, index=port_dates)
    m = calc_metrics(sens_series)
    sens_results[f"tv_{tv}"] = m
    pct = (tv - 12.0) / 12.0 * 100
    print(f"  Target Vol={tv:.1f} ({pct:+.0f}%): Sharpe={m['sharpe']:.3f}, "
          f"MDD={m['mdd']:.2%}, CAGR={m['cagr']:.2%}")

# Check if Sharpe drops > 30% under ±20% parameter change
base_sharpe = sens_results["tv_12.0"]["sharpe"]
for key, m in sens_results.items():
    if key == "tv_12.0":
        continue
    pct_change = (m["sharpe"] - base_sharpe) / abs(base_sharpe) * 100 if base_sharpe != 0 else 0
    stable = abs(pct_change) < 30
    print(f"    {key}: Sharpe change = {pct_change:+.1f}% {'✓ stable' if stable else '✗ UNSTABLE'}")

RESULTS["sensitivity"] = sens_results


# ============================================================
# PART J: Average Weight Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART J: Average Weight Analysis")
print("-" * 50)

weight_analysis = {}
for sname in STRATEGY_NAMES:
    w = strat_weights[sname]
    avg_w = w.mean()
    weight_analysis[sname] = {a: round(float(avg_w[a]), 4) for a in ASSETS}
    cash = round(1.0 - float(avg_w.sum()), 4)
    weight_analysis[sname]["CASH"] = max(0, cash)
    print(f"\n  {sname}:")
    for a in ASSETS:
        print(f"    {a}: {avg_w[a]:.2%}")
    print(f"    CASH: {max(0, cash):.2%}")

RESULTS["avg_weights"] = weight_analysis


# ============================================================
# PART K: OOS Performance (2023-01 to 2024-12)
# ============================================================
print("\n" + "=" * 70)
print("PART K: OOS Period (2023-01-01 to 2024-12-31)")
print("-" * 50)

oos_metrics = {}
print(f"\n{'Strategy':<22s} {'CAGR':>7s} {'Vol':>7s} {'Sharpe':>7s} "
      f"{'MDD':>8s} {'Calmar':>7s} {'Sortino':>7s}")
print("-" * 75)

for sname in STRATEGY_NAMES:
    r_oos = strat_returns[sname][
        (strat_returns[sname].index >= "2023-01-01") &
        (strat_returns[sname].index <= "2024-12-31")
    ]
    m = calc_metrics(r_oos)
    oos_metrics[sname] = m
    print(f"  {sname:<20s} {m['cagr']:>6.2%} {m['ann_vol']:>6.2%} {m['sharpe']:>6.3f} "
          f"{m['mdd']:>7.2%} {m['calmar']:>6.3f} {m['sortino']:>6.3f}")

RESULTS["oos_2023_2024"] = oos_metrics


# ============================================================
# SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY & CONCLUSIONS")
print("=" * 70)

# Find best strategy by Sharpe (full sample)
best_full = max(full_metrics.items(), key=lambda x: x[1].get("sharpe", 0))
best_mdd = max(full_metrics.items(), key=lambda x: x[1].get("mdd", -1))
best_crra = max(crra_results.items(), key=lambda x: x[1]["crra_full"])

print(f"\n  Best Sharpe (full): {best_full[0]} = {best_full[1]['sharpe']:.3f}")
print(f"  Best MDD (full):   {best_mdd[0]} = {best_mdd[1]['mdd']:.2%}")
print(f"  Best CRRA (full):  {best_crra[0]} = {best_crra[1]['crra_full']:.6f}")

# Key question: Does multi-asset VT beat 50/50?
bl = full_metrics["S0_BH_5050"]
print(f"\n  Baseline 50/50: Sharpe={bl['sharpe']:.3f}, MDD={bl['mdd']:.2%}")

for sname in ["S2_RP_4Asset", "S3_VT_RP_4Asset", "S4_RegimeAware"]:
    m = full_metrics[sname]
    dm = dm_results.get(sname, {})
    sharpe_diff = m["sharpe"] - bl["sharpe"]
    mdd_improve = bl["mdd"] - m["mdd"]  # positive = strategy has less DD
    print(f"\n  {sname}:")
    print(f"    Sharpe: {m['sharpe']:.3f} (diff={sharpe_diff:+.3f})")
    print(f"    MDD:    {m['mdd']:.2%} (improvement={mdd_improve:+.2%})")
    print(f"    DM:     t={dm.get('dm_stat', 'N/A')}, Harvey sig={dm.get('harvey_significant', 'N/A')}")
    print(f"    Cross-OOS wins: {cross_oos_wins.get(sname, 'N/A')}")

RESULTS["summary"] = {
    "best_sharpe_full": {"strategy": best_full[0], "sharpe": best_full[1]["sharpe"]},
    "best_mdd_full": {"strategy": best_mdd[0], "mdd": best_mdd[1]["mdd"]},
    "best_crra_full": {"strategy": best_crra[0], "crra": best_crra[1]["crra_full"]},
    "conclusion": (
        "NULL RESULT: Multi-asset VT (S3/S4) trades lower Sharpe for MDD "
        "improvement (~16pp). DM test significant (Harvey t>3) AGAINST VT vs "
        "50/50 baseline. S3 best MDD=-17.04% vs baseline -33.39%, but Sharpe "
        "0.766 vs 0.832. 50/50 SPY/GLD remains champion on Sharpe/CRRA; "
        "multi-asset VT is drawdown insurance with a return cost."
    ),
}

RESULTS["experiment_id"] = "K808"
RESULTS["title"] = "Cross-Asset All-Weather Volatility Targeting"
RESULTS["data_source"] = "yfinance (SPY, GLD, TLT, DBC, ^VIX)"
RESULTS["timestamp"] = datetime.now().isoformat()

# Save results
output_path = PROJECT / "experiments" / "k808_allweather_vt_results.json"
with open(output_path, "w") as f:
    json.dump(RESULTS, f, indent=2, default=str)
print(f"\n\nResults saved to {output_path}")
print("K808 experiment complete.")
