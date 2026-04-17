"""
K201: Can Copula Tail Dependence Improve VT Strategy?
[提出: 用戶 (K193/K195 follow-up), 執行: Claude]

Background:
- K195 found 26/66 pairs pass Bonferroni for TDA predicting vol
- But GARCH-X with TDA failed to improve QLIKE
- New hypothesis: TDA as REGIME INDICATOR for VT timing
  (not to improve vol forecasts, but to improve VT timing)

Methodology:
1. Compute rolling 252d tail dependence for top pairs from K195
2. Define TDA regimes (terciles)
3. VT with TDA overlay: reduce/increase equity weight based on TDA regime
4. 5-period cross-OOS validation
5. Harvey t>3.0 for any strategy improvement claim

Data: SPY, GLD, TLT, QQQ, EEM daily returns from yfinance
OOS: 2023-2024 walk-forward (primary), plus 4 additional cross-OOS periods
"""

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from scipy.optimize import minimize
import warnings
import json
import os
from datetime import datetime

warnings.filterwarnings("ignore")

# ============================================================
# 1. DATA LOADING
# ============================================================
print("=" * 70)
print("K201: Can Copula Tail Dependence Improve VT Strategy?")
print("=" * 70)

print("\n[1] Loading data from yfinance ...")

tickers = ["SPY", "GLD", "TLT", "QQQ", "EEM", "XLK"]
data = {}
for t in tickers:
    df = yf.download(t, start="2005-01-01", end="2025-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[t] = df["Close"]

# VIX for base VT strategy
vix_raw = yf.download("^VIX", start="2005-01-01", end="2025-01-01", progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"]

# Build combined DataFrame
prices = pd.DataFrame(data)
prices["VIX"] = vix
prices = prices.dropna()

# Compute log returns
returns = np.log(prices[tickers] / prices[tickers].shift(1)).dropna()
prices = prices.loc[returns.index]

print(f"   Data: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
print(f"   Observations: {len(returns)}")
print(f"   Assets: {', '.join(tickers)}")

# ============================================================
# 2. COPULA TAIL DEPENDENCE ESTIMATION
# ============================================================
print("\n[2] Computing rolling tail dependence ...")

def estimate_lower_tail_dependence(u1, u2, threshold=0.10):
    """
    Non-parametric lower tail dependence coefficient.
    lambda_L = lim_{q->0} P(U2 < q | U1 < q)
    Estimated as: proportion of joint exceedances below threshold.
    """
    mask = u1 < threshold
    if mask.sum() < 5:
        return np.nan
    return np.mean(u2[mask] < threshold)


def estimate_tail_dep_joe_copula(u1, u2):
    """
    Parametric tail dependence via Joe copula.
    Joe copula C(u,v) = 1 - [(1-u)^theta + (1-v)^theta - (1-u)^theta*(1-v)^theta]^(1/theta)
    Upper tail dependence: lambda_U = 2 - 2^(1/theta)
    For lower tail, we use 1-u, 1-v (survival copula).
    """
    # Convert to survival copula for lower tail
    s1 = 1 - u1
    s2 = 1 - u2

    def joe_loglik(theta, u, v):
        """Negative log-likelihood for Joe copula."""
        theta = max(theta, 1.001)
        a = (1 - u) ** theta
        b = (1 - v) ** theta
        C = 1 - (a + b - a * b) ** (1.0 / theta)
        # Density via numerical differentiation is complex; use CML approach
        # Approximate: use the Kendall's tau relationship
        # tau = 1 - 2 / (theta * (theta - 1)) * digamma(2) ... (complex)
        # Instead, minimize distance to empirical copula
        return -np.sum(np.log(np.maximum(C, 1e-10)))

    # Use method of moments via Kendall's tau
    tau, _ = stats.kendalltau(s1, s2)
    # Joe copula: tau ≈ 1 + 2/(theta*(2-theta)) * (digamma(2) - digamma(1 + 2/theta))
    # Simplified: for theta > 1, use approximate inversion
    if tau <= 0:
        return 0.0  # No tail dependence

    # Grid search for theta
    best_theta = 1.0
    best_diff = 1e10
    for theta in np.arange(1.01, 10.0, 0.1):
        # Approximate tau for Joe copula (numerical)
        sim_tau = 1 - 2.0 / (theta * (theta + 2))  # Rough approximation
        diff = abs(sim_tau - tau)
        if diff < best_diff:
            best_diff = diff
            best_theta = theta

    # lambda_U (Joe) = 2 - 2^(1/theta)
    lambda_upper = 2 - 2 ** (1 / best_theta)
    return lambda_upper


def compute_rolling_tail_dep(ret1, ret2, window=252, method="nonparametric"):
    """
    Compute rolling tail dependence coefficient.
    Uses empirical CDF to transform to uniform margins (pseudo-observations).
    """
    n = len(ret1)
    td_series = np.full(n, np.nan)

    for i in range(window, n):
        r1_win = ret1[i - window:i]
        r2_win = ret2[i - window:i]

        # Transform to pseudo-observations (empirical CDF)
        u1 = stats.rankdata(r1_win) / (window + 1)
        u2 = stats.rankdata(r2_win) / (window + 1)

        if method == "nonparametric":
            # Lower tail dependence (crash co-movement)
            td_series[i] = estimate_lower_tail_dependence(u1, u2, threshold=0.10)
        elif method == "joe":
            td_series[i] = estimate_tail_dep_joe_copula(u1, u2)
        else:
            td_series[i] = estimate_lower_tail_dependence(u1, u2, threshold=0.10)

    return td_series


# Top pairs from K195
pairs = [
    ("EEM", "XLK", "EEM-XLK (strongest OOS t=-12.27)"),
    ("SPY", "EEM", "SPY-EEM (t=-9.65)"),
    ("SPY", "QQQ", "SPY-QQQ (control: highly correlated)"),
]

# Compute tail dependence for all pairs
td_results = {}
for asset1, asset2, label in pairs:
    print(f"   Computing tail dep for {label} ...")
    r1 = returns[asset1].values
    r2 = returns[asset2].values
    td = compute_rolling_tail_dep(r1, r2, window=252, method="nonparametric")
    td_results[f"{asset1}_{asset2}"] = td

# Also compute Joe copula version for robustness
td_joe_results = {}
for asset1, asset2, label in pairs:
    print(f"   Computing Joe copula tail dep for {label} ...")
    r1 = returns[asset1].values
    r2 = returns[asset2].values
    td = compute_rolling_tail_dep(r1, r2, window=252, method="joe")
    td_joe_results[f"{asset1}_{asset2}"] = td

# Create tail dependence DataFrame
td_df = pd.DataFrame(td_results, index=returns.index)
td_joe_df = pd.DataFrame(td_joe_results, index=returns.index)

print(f"\n   Tail dependence computed for {len(pairs)} pairs")
for col in td_df.columns:
    valid = td_df[col].dropna()
    print(f"   {col}: mean={valid.mean():.4f}, std={valid.std():.4f}, "
          f"min={valid.min():.4f}, max={valid.max():.4f}")

# ============================================================
# 3. TDA REGIME CLASSIFICATION
# ============================================================
print("\n[3] Defining TDA regimes ...")

# Use average tail dependence across top pairs as composite signal
td_df["composite"] = td_df.mean(axis=1)
td_joe_df["composite"] = td_joe_df.mean(axis=1)

# Rolling terciles (expanding window to avoid look-ahead)
def assign_rolling_tercile(series, min_window=504):
    """Assign tercile ranks using expanding window (no look-ahead)."""
    n = len(series)
    terciles = np.full(n, np.nan)

    for i in range(min_window, n):
        past = series[:i + 1]
        past_valid = past[~np.isnan(past)]
        if len(past_valid) < 30:
            continue
        val = series[i]
        if np.isnan(val):
            continue
        pct = stats.percentileofscore(past_valid, val) / 100.0
        if pct <= 1/3:
            terciles[i] = 0  # Low TDA
        elif pct <= 2/3:
            terciles[i] = 1  # Medium TDA
        else:
            terciles[i] = 2  # High TDA (strong crash co-movement)

    return terciles

terciles = assign_rolling_tercile(td_df["composite"].values)
td_df["regime"] = terciles

regime_counts = pd.Series(terciles).value_counts().sort_index()
print(f"   Regime distribution (expanding terciles):")
for regime, count in regime_counts.items():
    if not np.isnan(regime):
        label = {0: "Low TDA", 1: "Medium TDA", 2: "High TDA"}[regime]
        print(f"     {label}: {int(count)} days ({count/len(terciles)*100:.1f}%)")

# ============================================================
# 4. VT STRATEGY DEFINITIONS
# ============================================================
print("\n[4] Defining VT strategies ...")

def compute_vt_strategy(spy_returns, vix_series, td_regime=None,
                         base_threshold=12.0, overlay_type=None,
                         reduction_pct=0.30, increase_pct=0.20,
                         rebalance_freq="monthly"):
    """
    Compute VT strategy returns.

    Base: 12/VIX monthly rebalancing (lagged weights: VIX_t -> r_{t+1})

    Overlay types:
    - None: pure 12/VIX
    - "reduce_high": reduce equity weight by reduction_pct when TDA is high
    - "increase_low": increase equity weight by increase_pct when TDA is low
    - "both": reduce in high + increase in low
    """
    n = len(spy_returns)
    weights = np.zeros(n)
    strat_returns = np.zeros(n)

    # Monthly rebalancing dates
    dates = spy_returns.index
    current_weight = 1.0

    for i in range(1, n):
        # Rebalance monthly (first trading day of month)
        if rebalance_freq == "monthly":
            if dates[i].month != dates[i - 1].month:
                # Use lagged VIX (previous day's VIX)
                vix_val = vix_series.iloc[i - 1]
                base_weight = min(base_threshold / vix_val, 1.0)

                # Apply TDA overlay
                if td_regime is not None and overlay_type is not None:
                    regime = td_regime[i - 1]  # Lagged regime (no look-ahead)
                    if not np.isnan(regime):
                        if overlay_type in ("reduce_high", "both") and regime == 2:
                            base_weight *= (1 - reduction_pct)
                        if overlay_type in ("increase_low", "both") and regime == 0:
                            base_weight = min(base_weight * (1 + increase_pct), 1.0)

                current_weight = np.clip(base_weight, 0, 1)

        weights[i] = current_weight
        strat_returns[i] = current_weight * spy_returns.iloc[i]

    return pd.Series(strat_returns, index=spy_returns.index), pd.Series(weights, index=spy_returns.index)


def compute_metrics(returns_series, rf=0.0):
    """Compute Sharpe, MDD, Calmar, Sortino."""
    r = returns_series.values
    r = r[~np.isnan(r)]
    if len(r) < 10:
        return {"sharpe": np.nan, "mdd": np.nan, "calmar": np.nan,
                "sortino": np.nan, "annual_ret": np.nan, "annual_vol": np.nan}

    annual_ret = np.mean(r) * 252
    annual_vol = np.std(r, ddof=1) * np.sqrt(252)
    sharpe = annual_ret / annual_vol if annual_vol > 0 else 0

    # MDD
    cum = np.cumsum(r)
    running_max = np.maximum.accumulate(cum)
    drawdown = cum - running_max
    mdd = np.min(drawdown)

    calmar = annual_ret / abs(mdd) if abs(mdd) > 0 else 0

    # Sortino
    downside = r[r < 0]
    downside_vol = np.std(downside, ddof=1) * np.sqrt(252) if len(downside) > 1 else annual_vol
    sortino = annual_ret / downside_vol if downside_vol > 0 else 0

    return {
        "sharpe": round(sharpe, 4),
        "mdd": round(mdd, 4),
        "calmar": round(calmar, 4),
        "sortino": round(sortino, 4),
        "annual_ret": round(annual_ret, 4),
        "annual_vol": round(annual_vol, 4),
    }


# ============================================================
# 5. CROSS-OOS VALIDATION (5 PERIODS)
# ============================================================
print("\n[5] Running 5-period cross-OOS validation ...")

# Define 5 OOS periods (2-year each, non-overlapping)
oos_periods = [
    ("2015-01-01", "2016-12-31", "OOS1: 2015-2016"),
    ("2017-01-01", "2018-12-31", "OOS2: 2017-2018"),
    ("2019-01-01", "2020-12-31", "OOS3: 2019-2020 (COVID)"),
    ("2021-01-01", "2022-12-31", "OOS4: 2021-2022"),
    ("2023-01-01", "2024-12-31", "OOS5: 2023-2024 (primary)"),
]

# Strategy variants
strategies = {
    "BnH": {"overlay": None},
    "Base 12/VIX": {"overlay": None},
    "TDA Reduce High 30%": {"overlay": "reduce_high", "reduction": 0.30},
    "TDA Increase Low 20%": {"overlay": "increase_low", "increase": 0.20},
    "TDA Both": {"overlay": "both", "reduction": 0.30, "increase": 0.20},
    "TDA Reduce High 50%": {"overlay": "reduce_high", "reduction": 0.50},
}

# Per-pair TDA signals
td_signals = {
    "EEM_XLK": td_df["EEM_XLK"].values,
    "SPY_EEM": td_df["SPY_EEM"].values,
    "composite": td_df["composite"].values,
}

# Compute terciles for each signal
signal_terciles = {}
for sig_name, sig_vals in td_signals.items():
    signal_terciles[sig_name] = assign_rolling_tercile(sig_vals)

all_results = []
print(f"\n{'Period':<25} {'Strategy':<25} {'Signal':<15} {'Sharpe':>8} {'MDD':>8} {'Calmar':>8} {'Sortino':>8}")
print("-" * 115)

spy_ret = returns["SPY"]
vix_series = prices["VIX"]

for oos_start, oos_end, oos_label in oos_periods:
    mask = (returns.index >= oos_start) & (returns.index <= oos_end)
    oos_ret = spy_ret[mask]
    oos_vix = vix_series[mask]

    if len(oos_ret) < 100:
        print(f"  {oos_label}: insufficient data ({len(oos_ret)} obs)")
        continue

    # Buy & Hold
    bh_metrics = compute_metrics(oos_ret)
    print(f"{oos_label:<25} {'Buy & Hold':<25} {'—':<15} {bh_metrics['sharpe']:>8.3f} {bh_metrics['mdd']:>8.3f} {bh_metrics['calmar']:>8.3f} {bh_metrics['sortino']:>8.3f}")
    all_results.append({
        "period": oos_label, "strategy": "Buy & Hold", "signal": "none",
        **bh_metrics
    })

    # Base 12/VIX
    base_ret, base_wt = compute_vt_strategy(oos_ret, oos_vix)
    base_metrics = compute_metrics(base_ret)
    print(f"{'':<25} {'Base 12/VIX':<25} {'—':<15} {base_metrics['sharpe']:>8.3f} {base_metrics['mdd']:>8.3f} {base_metrics['calmar']:>8.3f} {base_metrics['sortino']:>8.3f}")
    all_results.append({
        "period": oos_label, "strategy": "Base 12/VIX", "signal": "none",
        **base_metrics
    })

    # TDA overlay variants
    for sig_name, sig_terc in signal_terciles.items():
        for strat_name, strat_params in strategies.items():
            if strat_name in ("BnH", "Base 12/VIX"):
                continue

            overlay_type = strat_params["overlay"]
            reduction = strat_params.get("reduction", 0.30)
            increase = strat_params.get("increase", 0.20)

            # Map signal terciles to full index
            # We need the terciles aligned to the OOS mask
            full_terciles = np.full(len(returns), np.nan)
            # Only fill where we have the signal
            for j in range(min(len(returns), len(sig_terc))):
                full_terciles[j] = sig_terc[j]

            mask_arr = mask.values if hasattr(mask, 'values') else mask
            oos_terciles = full_terciles[mask_arr]

            strat_ret, strat_wt = compute_vt_strategy(
                oos_ret, oos_vix,
                td_regime=oos_terciles,
                overlay_type=overlay_type,
                reduction_pct=reduction,
                increase_pct=increase,
            )
            strat_metrics = compute_metrics(strat_ret)

            print(f"{'':<25} {strat_name:<25} {sig_name:<15} "
                  f"{strat_metrics['sharpe']:>8.3f} {strat_metrics['mdd']:>8.3f} "
                  f"{strat_metrics['calmar']:>8.3f} {strat_metrics['sortino']:>8.3f}")

            all_results.append({
                "period": oos_label, "strategy": strat_name,
                "signal": sig_name, **strat_metrics
            })

    print()

# ============================================================
# 6. STATISTICAL TESTING: TDA OVERLAY vs BASE
# ============================================================
print("\n[6] Statistical testing: TDA overlay vs Base 12/VIX ...")

# For each TDA strategy, compare Sharpe differences across 5 OOS periods
results_df = pd.DataFrame(all_results)

# Get unique TDA strategies
tda_strategies = results_df[
    ~results_df["strategy"].isin(["Buy & Hold", "Base 12/VIX"])
]["strategy"].unique()

print(f"\n{'Strategy + Signal':<45} {'Mean dSharpe':>12} {'t-stat':>8} {'p-value':>10} {'N_pos':>6}")
print("-" * 85)

statistical_results = {}
for strat in tda_strategies:
    for sig in signal_terciles.keys():
        # Collect Sharpe differences across periods
        sharpe_diffs = []
        for _, _, oos_label in oos_periods:
            base_row = results_df[
                (results_df["period"] == oos_label) &
                (results_df["strategy"] == "Base 12/VIX")
            ]
            tda_row = results_df[
                (results_df["period"] == oos_label) &
                (results_df["strategy"] == strat) &
                (results_df["signal"] == sig)
            ]
            if len(base_row) > 0 and len(tda_row) > 0:
                diff = tda_row.iloc[0]["sharpe"] - base_row.iloc[0]["sharpe"]
                sharpe_diffs.append(diff)

        if len(sharpe_diffs) >= 3:
            diffs = np.array(sharpe_diffs)
            mean_diff = np.mean(diffs)
            se_diff = np.std(diffs, ddof=1) / np.sqrt(len(diffs))
            t_stat = mean_diff / se_diff if se_diff > 0 else 0
            p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(diffs) - 1))
            n_positive = np.sum(diffs > 0)

            label = f"{strat} ({sig})"
            print(f"{label:<45} {mean_diff:>12.4f} {t_stat:>8.3f} {p_val:>10.4f} {n_positive:>6}/{len(diffs)}")

            statistical_results[label] = {
                "mean_d_sharpe": float(mean_diff),
                "t_stat": float(t_stat),
                "p_value": float(p_val),
                "n_positive": int(n_positive),
                "n_periods": len(diffs),
                "per_period_diffs": [round(d, 4) for d in diffs],
                "passes_harvey": abs(t_stat) > 3.0,
            }

# ============================================================
# 7. MDD COMPARISON
# ============================================================
print("\n[7] MDD comparison across OOS periods ...")

print(f"\n{'Strategy + Signal':<45} {'Mean dMDD':>12} {'t-stat':>8} {'p-value':>10} {'N_better':>8}")
print("-" * 87)

mdd_results = {}
for strat in tda_strategies:
    for sig in signal_terciles.keys():
        mdd_diffs = []
        for _, _, oos_label in oos_periods:
            base_row = results_df[
                (results_df["period"] == oos_label) &
                (results_df["strategy"] == "Base 12/VIX")
            ]
            tda_row = results_df[
                (results_df["period"] == oos_label) &
                (results_df["strategy"] == strat) &
                (results_df["signal"] == sig)
            ]
            if len(base_row) > 0 and len(tda_row) > 0:
                # Positive diff = TDA has less drawdown (better)
                diff = abs(base_row.iloc[0]["mdd"]) - abs(tda_row.iloc[0]["mdd"])
                mdd_diffs.append(diff)

        if len(mdd_diffs) >= 3:
            diffs = np.array(mdd_diffs)
            mean_diff = np.mean(diffs)
            se_diff = np.std(diffs, ddof=1) / np.sqrt(len(diffs))
            t_stat = mean_diff / se_diff if se_diff > 0 else 0
            p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(diffs) - 1))
            n_better = np.sum(diffs > 0)

            label = f"{strat} ({sig})"
            print(f"{label:<45} {mean_diff:>12.4f} {t_stat:>8.3f} {p_val:>10.4f} {n_better:>8}/{len(diffs)}")

            mdd_results[label] = {
                "mean_d_mdd": float(mean_diff),
                "t_stat": float(t_stat),
                "p_value": float(p_val),
                "n_better": int(n_better),
                "n_periods": len(diffs),
            }

# ============================================================
# 8. TAIL DEPENDENCE vs VIX CORRELATION
# ============================================================
print("\n[8] Tail dependence vs VIX correlation analysis ...")

# Is TDA just a proxy for VIX?
td_valid = td_df["composite"].dropna()
vix_aligned = prices["VIX"].loc[td_valid.index]

r_td_vix, p_td_vix = stats.pearsonr(td_valid.values, vix_aligned.values)
print(f"\n   Correlation(TDA composite, VIX): r={r_td_vix:.4f}, p={p_td_vix:.2e}")

# Partial correlation: TDA vs future vol, controlling for VIX
# Compute 22-day forward realized vol
fwd_rv = returns["SPY"].rolling(22).std().shift(-22) * np.sqrt(252) * 100
fwd_rv_aligned = fwd_rv.loc[td_valid.index].dropna()
td_aligned = td_valid.loc[fwd_rv_aligned.index]
vix_partial = prices["VIX"].loc[fwd_rv_aligned.index]

if len(td_aligned) > 50:
    r_td_rv, p_td_rv = stats.pearsonr(td_aligned.values, fwd_rv_aligned.values)
    r_vix_rv, p_vix_rv = stats.pearsonr(vix_partial.values, fwd_rv_aligned.values)

    # Partial correlation
    r_xz = r_td_vix
    r_yz = r_vix_rv
    r_xy = r_td_rv
    numer = r_xy - r_xz * r_yz
    denom = np.sqrt((1 - r_xz ** 2) * (1 - r_yz ** 2))
    partial_r = numer / denom if denom > 0 else 0
    n = len(td_aligned)
    t_partial = partial_r * np.sqrt((n - 3) / (1 - partial_r ** 2)) if abs(partial_r) < 1 else 0
    p_partial = 2 * (1 - stats.t.cdf(abs(t_partial), df=n - 3))

    print(f"   Correlation(TDA, Fwd RV22): r={r_td_rv:.4f}, p={p_td_rv:.2e}")
    print(f"   Correlation(VIX, Fwd RV22): r={r_vix_rv:.4f}, p={p_vix_rv:.2e}")
    print(f"   Partial r(TDA, Fwd RV22 | VIX): r={partial_r:.4f}, p={p_partial:.2e}")
else:
    partial_r = np.nan
    p_partial = np.nan
    r_td_rv = np.nan

# ============================================================
# 9. REGIME-CONDITIONAL ANALYSIS
# ============================================================
print("\n[9] Regime-conditional analysis ...")

# What happens to SPY returns in each TDA regime?
for sig_name in ["composite"]:
    terc = signal_terciles.get(sig_name, assign_rolling_tercile(td_df[sig_name].values))
    terc_series = pd.Series(terc, index=returns.index)

    print(f"\n   Signal: {sig_name}")
    print(f"   {'Regime':<15} {'N':>6} {'Mean Ret':>10} {'Vol':>10} {'Sharpe':>8} {'Skew':>8} {'Kurt':>8}")
    print("   " + "-" * 67)

    regime_stats = {}
    for regime_val, regime_label in [(0, "Low TDA"), (1, "Medium TDA"), (2, "High TDA")]:
        mask = terc_series == regime_val
        regime_ret = spy_ret[mask]
        if len(regime_ret) < 20:
            continue
        ann_ret = regime_ret.mean() * 252
        ann_vol = regime_ret.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        skew = stats.skew(regime_ret)
        kurt = stats.kurtosis(regime_ret)

        print(f"   {regime_label:<15} {len(regime_ret):>6} {ann_ret:>10.4f} {ann_vol:>10.4f} "
              f"{sharpe:>8.3f} {skew:>8.3f} {kurt:>8.3f}")

        regime_stats[regime_label] = {
            "n": len(regime_ret),
            "ann_ret": round(ann_ret, 4),
            "ann_vol": round(ann_vol, 4),
            "sharpe": round(sharpe, 4),
            "skew": round(skew, 4),
            "kurt": round(kurt, 4),
        }

    # ANOVA test: do returns differ across regimes?
    groups = []
    for regime_val in [0, 1, 2]:
        mask = terc_series == regime_val
        g = spy_ret[mask].values
        if len(g) > 10:
            groups.append(g)

    if len(groups) >= 2:
        f_stat, f_pval = stats.f_oneway(*groups)
        print(f"\n   ANOVA (returns across regimes): F={f_stat:.3f}, p={f_pval:.4f}")
        kw_stat, kw_pval = stats.kruskal(*groups)
        print(f"   Kruskal-Wallis: H={kw_stat:.3f}, p={kw_pval:.4f}")

# ============================================================
# 10. BOOTSTRAP SHARPE DIFFERENCE TEST
# ============================================================
print("\n[10] Bootstrap test of Sharpe improvement ...")

# Full sample test (most powerful)
full_mask = (returns.index >= "2015-01-01") & (returns.index <= "2024-12-31")
full_spy = spy_ret[full_mask]
full_vix = vix_series[full_mask]

# Base strategy
base_full_ret, base_full_wt = compute_vt_strategy(full_spy, full_vix)

# Best TDA overlay (use composite signal, reduce_high 30%)
full_terciles_raw = assign_rolling_tercile(td_df["composite"].values)
full_terciles = np.full(len(returns), np.nan)
for j in range(len(full_terciles_raw)):
    full_terciles[j] = full_terciles_raw[j]
full_mask_arr = full_mask.values if hasattr(full_mask, 'values') else full_mask
oos_full_terciles = full_terciles[full_mask_arr]

tda_full_ret, tda_full_wt = compute_vt_strategy(
    full_spy, full_vix,
    td_regime=oos_full_terciles,
    overlay_type="reduce_high",
    reduction_pct=0.30,
)

# Point estimates
base_sharpe_full = compute_metrics(base_full_ret)["sharpe"]
tda_sharpe_full = compute_metrics(tda_full_ret)["sharpe"]

print(f"\n   Full period 2015-2024:")
print(f"   Base 12/VIX Sharpe: {base_sharpe_full:.4f}")
print(f"   TDA Reduce 30% Sharpe: {tda_sharpe_full:.4f}")
print(f"   Difference: {tda_sharpe_full - base_sharpe_full:.4f}")

# Bootstrap
n_boot = 10000
boot_diffs = np.zeros(n_boot)
base_arr = base_full_ret.values
tda_arr = tda_full_ret.values
n_obs = len(base_arr)

np.random.seed(42)
for b in range(n_boot):
    idx = np.random.choice(n_obs, n_obs, replace=True)
    b_base = base_arr[idx]
    b_tda = tda_arr[idx]

    sr_base = np.mean(b_base) / np.std(b_base, ddof=1) * np.sqrt(252) if np.std(b_base) > 0 else 0
    sr_tda = np.mean(b_tda) / np.std(b_tda, ddof=1) * np.sqrt(252) if np.std(b_tda) > 0 else 0
    boot_diffs[b] = sr_tda - sr_base

boot_mean = np.mean(boot_diffs)
boot_se = np.std(boot_diffs, ddof=1)
boot_t = boot_mean / boot_se if boot_se > 0 else 0
boot_p = 2 * (1 - stats.norm.cdf(abs(boot_t)))
pct_positive = np.mean(boot_diffs > 0) * 100

print(f"\n   Bootstrap ({n_boot} reps):")
print(f"   Mean d(Sharpe): {boot_mean:.4f}")
print(f"   SE: {boot_se:.4f}")
print(f"   t-stat: {boot_t:.3f}")
print(f"   p-value: {boot_p:.4f}")
print(f"   % positive: {pct_positive:.1f}%")
print(f"   95% CI: [{np.percentile(boot_diffs, 2.5):.4f}, {np.percentile(boot_diffs, 97.5):.4f}]")
print(f"   Passes Harvey (|t|>3.0): {'YES' if abs(boot_t) > 3.0 else 'NO'}")

# ============================================================
# 11. ALSO TEST WITH 50/50 SPY/GLD (strongest baseline)
# ============================================================
print("\n[11] Testing against 50/50 SPY/GLD baseline ...")

gld_ret = returns["GLD"]

# 50/50 SPY/GLD with VT
for _, _, oos_label in oos_periods:
    oos_start, oos_end = oos_label.split(": ")[1].split("-", 1)
    oos_start = oos_start.strip() + "-01-01"
    oos_end = oos_end.strip() + "-12-31"

# Full period - align VIX to returns index
full_spy_r = spy_ret[full_mask]
full_gld_r = gld_ret[full_mask]
full_portfolio_ret = 0.5 * full_spy_r + 0.5 * full_gld_r

# Align VIX to returns index before masking
vix_aligned = vix_series.reindex(returns.index).ffill()
full_vix_period = vix_aligned[full_mask]

# Base VT on portfolio
base_port_ret, base_port_wt = compute_vt_strategy(
    full_portfolio_ret, full_vix_period
)

# TDA overlay on portfolio
tda_port_ret, tda_port_wt = compute_vt_strategy(
    full_portfolio_ret, full_vix_period,
    td_regime=oos_full_terciles,
    overlay_type="reduce_high",
    reduction_pct=0.30,
)

base_port_metrics = compute_metrics(base_port_ret)
tda_port_metrics = compute_metrics(tda_port_ret)

print(f"\n   50/50 SPY/GLD + 12/VIX (2015-2024):")
print(f"   Base Sharpe: {base_port_metrics['sharpe']:.4f}, MDD: {base_port_metrics['mdd']:.4f}")
print(f"   TDA overlay Sharpe: {tda_port_metrics['sharpe']:.4f}, MDD: {tda_port_metrics['mdd']:.4f}")
print(f"   d(Sharpe): {tda_port_metrics['sharpe'] - base_port_metrics['sharpe']:.4f}")
print(f"   d(MDD): {abs(base_port_metrics['mdd']) - abs(tda_port_metrics['mdd']):.4f}")

# ============================================================
# 12. TURNOVER ANALYSIS
# ============================================================
print("\n[12] Turnover analysis ...")

# Base VT turnover
base_turnover = np.sum(np.abs(np.diff(base_full_wt.values))) / (len(base_full_wt) / 252)
tda_turnover = np.sum(np.abs(np.diff(tda_full_wt.values))) / (len(tda_full_wt) / 252)

print(f"   Base 12/VIX annual turnover: {base_turnover:.4f}")
print(f"   TDA overlay annual turnover: {tda_turnover:.4f}")
print(f"   Additional turnover from TDA: {tda_turnover - base_turnover:.4f}")

# Net Sharpe after transaction costs (0.1% per trade)
tc_rate = 0.001
base_tc = base_turnover * tc_rate
tda_tc = tda_turnover * tc_rate
base_net_sharpe = base_sharpe_full - base_tc / (compute_metrics(base_full_ret)["annual_vol"])
tda_net_sharpe = tda_sharpe_full - tda_tc / (compute_metrics(tda_full_ret)["annual_vol"])

print(f"\n   After TC (0.1% per trade):")
print(f"   Base net Sharpe: {base_net_sharpe:.4f}")
print(f"   TDA net Sharpe: {tda_net_sharpe:.4f}")

# ============================================================
# 13. SUMMARY & CONCLUSION
# ============================================================
print("\n" + "=" * 70)
print("[13] SUMMARY & CONCLUSIONS")
print("=" * 70)

# Determine verdict
any_passes_harvey = any(
    v.get("passes_harvey", False)
    for v in statistical_results.values()
)

# Count how many strategies beat base in majority of periods
n_majority_wins = sum(
    1 for v in statistical_results.values()
    if v["n_positive"] > v["n_periods"] / 2
)

print(f"""
EXPERIMENT K201: Copula Tail Dependence for VT Strategy Timing
================================================================

Data: SPY, GLD, TLT, QQQ, EEM, XLK
Period: 2005-2024 (rolling 252d tail dependence)
OOS validation: 5 periods (2015-2024, 2-year each)
Base strategy: 12/VIX monthly rebalancing (SPY)

METHOD:
- Copula-based lower tail dependence (crash co-movement)
- Top pairs from K195: EEM-XLK (t=-12.27), SPY-EEM (t=-9.65)
- Composite signal: average across pairs
- Regime classification: expanding-window terciles
- Overlay: reduce equity weight in High TDA, increase in Low TDA

KEY FINDINGS:

1. CROSS-OOS SHARPE DIFFERENCES:
   - {len(statistical_results)} strategy-signal combinations tested
   - Strategies beating base in majority of periods: {n_majority_wins}/{len(statistical_results)}
   - Any passes Harvey (|t|>3.0): {'YES' if any_passes_harvey else 'NO'}

2. BOOTSTRAP FULL-PERIOD TEST (2015-2024):
   - Base 12/VIX Sharpe: {base_sharpe_full:.4f}
   - TDA Reduce 30% Sharpe: {tda_sharpe_full:.4f}
   - Bootstrap t-stat: {boot_t:.3f} (p={boot_p:.4f})
   - Passes Harvey: {'YES' if abs(boot_t) > 3.0 else 'NO'}

3. TDA vs VIX REDUNDANCY:
   - r(TDA, VIX) = {r_td_vix:.4f}
   - Partial r(TDA, Fwd RV | VIX) = {f'{partial_r:.4f}' if not np.isnan(partial_r) else 'N/A'}
   - TDA {'IS' if abs(r_td_vix) > 0.5 else 'is NOT'} highly correlated with VIX

4. 50/50 SPY/GLD + TDA:
   - Base Sharpe: {base_port_metrics['sharpe']:.4f}
   - TDA overlay: {tda_port_metrics['sharpe']:.4f}
   - Improvement: {tda_port_metrics['sharpe'] - base_port_metrics['sharpe']:.4f}
""")

# Dynamic conclusion
if any_passes_harvey:
    conclusion = ("SIGNIFICANT: Copula tail dependence provides statistically significant "
                  "improvement to VT strategy timing. This passes the Harvey (2016) threshold "
                  "and represents genuine alpha beyond VIX-based VT.")
    verdict = "significant"
elif boot_p < 0.05:
    conclusion = ("MARGINAL: Copula tail dependence shows some improvement to VT timing "
                  f"(bootstrap t={boot_t:.3f}), but fails the Harvey (2016) |t|>3.0 threshold. "
                  "This is consistent with the VIX sufficient statistic finding — TDA carries "
                  "information about crash co-movement, but this information is largely "
                  "captured by VIX already. The overlay adds complexity without reliable "
                  "improvement.")
    verdict = "marginal"
else:
    conclusion = ("NULL: Copula tail dependence does NOT improve VT strategy timing. "
                  "The 12/VIX rule is already an irreducible kernel (J13). "
                  "TDA regime classification adds noise, not signal. "
                  "This is the 22nd confirmation of VIX sufficiency at monthly horizons.")
    verdict = "null"

print(f"CONCLUSION: {conclusion}")

# ============================================================
# 14. SAVE RESULTS
# ============================================================
print("\n[14] Saving results ...")

output = {
    "experiment_id": "K201",
    "title": "Can Copula Tail Dependence Improve VT Strategy?",
    "proposed_by": "User (K193/K195 follow-up)",
    "executed_by": "Claude",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "method": "Copula lower tail dependence as VT regime indicator",
    "data_period": f"{returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}",
    "n_observations": int(len(returns)),
    "pairs_tested": [f"{a1}-{a2}" for a1, a2, _ in pairs],
    "oos_periods": [{"start": s, "end": e, "label": l} for s, e, l in oos_periods],
    "cross_oos_results": {
        k: v for k, v in statistical_results.items()
    },
    "mdd_comparison": mdd_results,
    "bootstrap_test": {
        "n_boot": n_boot,
        "base_sharpe": float(base_sharpe_full),
        "tda_sharpe": float(tda_sharpe_full),
        "mean_d_sharpe": float(boot_mean),
        "boot_se": float(boot_se),
        "boot_t": float(boot_t),
        "boot_p": float(boot_p),
        "pct_positive": float(pct_positive),
        "ci_95": [float(np.percentile(boot_diffs, 2.5)),
                  float(np.percentile(boot_diffs, 97.5))],
        "passes_harvey": abs(boot_t) > 3.0,
    },
    "tda_vix_correlation": {
        "r": float(r_td_vix),
        "p": float(p_td_vix),
        "partial_r_fwd_rv": float(partial_r) if not np.isnan(partial_r) else None,
        "partial_p": float(p_partial) if not np.isnan(p_partial) else None,
    },
    "portfolio_test": {
        "base_sharpe": float(base_port_metrics["sharpe"]),
        "tda_sharpe": float(tda_port_metrics["sharpe"]),
        "base_mdd": float(base_port_metrics["mdd"]),
        "tda_mdd": float(tda_port_metrics["mdd"]),
    },
    "turnover": {
        "base_annual": float(base_turnover),
        "tda_annual": float(tda_turnover),
        "additional": float(tda_turnover - base_turnover),
    },
    "conclusion": conclusion,
    "verdict": verdict,
}

class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

out_path = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "results_k201_tda_vt_strategy.json"
)
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False, cls=NumpyEncoder)
print(f"   Saved to {out_path}")

print("\n" + "=" * 70)
print("K201 complete.")
print("=" * 70)
