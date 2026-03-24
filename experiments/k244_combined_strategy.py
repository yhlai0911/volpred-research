"""
K244: Combined TSMOM + Defensive Sector Rotation — Can Two Harvey-Passing Signals Combine for Alpha?
=====================================================================================================
[提出: 用戶, 執行: Claude]

Background:
  K241: TSMOM 6_1 on SPY/GLD/TLT passes Harvey (t=4.37, Sharpe 0.792)
  K243: VIX-based sector rotation passes Harvey (t=4.00, Sharpe 0.896)
  Neither has significant DM test vs 50/50+VT individually.

Hypothesis:
  Combining two ORTHOGONAL signals (momentum-based asset allocation + VIX-based sector rotation)
  may create genuine alpha that IS DM-significant, because the signals capture different
  market dimensions (trend persistence vs fear regime).

Data: SPY, GLD, TLT, XLU, XLP, XLV, XLK, XLY, VIX daily from yfinance. 2005-2024.

Methodology:
  1. TSMOM signal: 6-1 month momentum on SPY/GLD/TLT
     Long assets with positive momentum, else cash
  2. Sector rotation signal: VIX regime
     Low VIX: overweight offensive (XLK, XLY)
     High VIX: overweight defensive (XLU, XLP, XLV)
  3. Combined strategies:
     A. Hierarchical: TSMOM for asset allocation + sector rotation for equity sleeve
        (TSMOM decides how much equity vs bonds/gold, sector rotation decides WHICH sectors)
     B. Dual signal: only long when BOTH momentum positive AND VIX favorable
     C. Simple blend: 50% TSMOM portfolio + 50% sector rotation portfolio
  4. Benchmarks:
     - 50/50 SPY/GLD + VT (current best)
     - TSMOM alone (K241)
     - Sector rotation alone (K243)
     - SPY B&H
  5. Metrics: Sharpe, MDD, DM test, Harvey t
  6. 5-period cross-OOS MANDATORY

Statistical Requirements:
  - Harvey threshold: t > 3.0
  - DM test for pairwise comparisons
  - Bootstrap CIs for Sharpe / MDD
  - OOS >= 252 days per fold
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import time
from datetime import datetime

# ==================================================================
# CONFIGURATION
# ==================================================================
TSMOM_ASSETS = ["SPY", "GLD", "TLT"]
OFFENSIVE_SECTORS = ["XLK", "XLY"]
DEFENSIVE_SECTORS = ["XLU", "XLP", "XLV"]
ALL_SECTORS = OFFENSIVE_SECTORS + DEFENSIVE_SECTORS
VIX_TICKER = "^VIX"

DATA_START = "2004-01-01"  # buffer for lookback
DATA_END = "2025-01-01"
ANALYSIS_START = "2005-01-01"

VIX_LOW = 15
VIX_HIGH = 25
TSMOM_LOOKBACK = 6  # months
TSMOM_SKIP = 1      # month

N_BOOTSTRAP = 10000
ANNUAL_TRADING_DAYS = 252
RF_ANNUAL = 0.02

OOS_FOLDS = [
    ("2005-01-01", "2008-12-31"),
    ("2009-01-01", "2012-12-31"),
    ("2013-01-01", "2016-12-31"),
    ("2017-01-01", "2020-12-31"),
    ("2021-01-01", "2024-12-31"),
]

print("=" * 90)
print("K244: COMBINED TSMOM + SECTOR ROTATION — TWO HARVEY-PASSING SIGNALS")
print("=" * 90)
print(f"  [提出: 用戶, 執行: Claude]")
print(f"  TSMOM assets:       {TSMOM_ASSETS}")
print(f"  Offensive sectors:  {OFFENSIVE_SECTORS}")
print(f"  Defensive sectors:  {DEFENSIVE_SECTORS}")
print(f"  VIX thresholds:     Low <{VIX_LOW}, High >{VIX_HIGH}")
print(f"  TSMOM lookback:     {TSMOM_LOOKBACK}_{TSMOM_SKIP}")
print(f"  Period:             {ANALYSIS_START} to 2024-12-31")
print(f"  OOS folds:          {len(OOS_FOLDS)}")
print(f"  Bootstrap reps:     {N_BOOTSTRAP}")
print()

# ==================================================================
# 1. DATA DOWNLOAD
# ==================================================================
print("=" * 90)
print("STEP 1: DATA DOWNLOAD (yfinance — real data only)")
print("=" * 90)

all_tickers = TSMOM_ASSETS + ALL_SECTORS + [VIX_TICKER]
# Remove duplicates (SPY is in both lists)
all_tickers = list(dict.fromkeys(all_tickers))

t0 = time.time()
raw_data = {}
for ticker in all_tickers:
    try:
        df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        raw_data[ticker] = df["Close"]
        print(f"  {ticker:>5s}: {len(raw_data[ticker]):>5d} obs, "
              f"{raw_data[ticker].index[0].strftime('%Y-%m-%d')} to "
              f"{raw_data[ticker].index[-1].strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"  {ticker}: FAILED — {e}")

# Build aligned DataFrame
prices = pd.DataFrame(raw_data)
prices = prices.dropna(how="all")
prices = prices.ffill()
prices = prices.dropna()

vix = prices[VIX_TICKER].copy()
asset_prices = prices[[c for c in prices.columns if c != VIX_TICKER]].copy()

# Filter to analysis period
analysis_mask = prices.index >= ANALYSIS_START
vix_analysis = vix[analysis_mask]
asset_returns = asset_prices.pct_change().dropna()
asset_returns = asset_returns[asset_returns.index >= ANALYSIS_START]

# Align
common_idx = asset_returns.index.intersection(vix_analysis.index)
asset_returns = asset_returns.loc[common_idx]
vix_analysis = vix_analysis.loc[common_idx]

print(f"\n  Aligned: {len(asset_returns)} days, "
      f"{asset_returns.index[0].strftime('%Y-%m-%d')} to "
      f"{asset_returns.index[-1].strftime('%Y-%m-%d')}")
print(f"  Download time: {time.time()-t0:.1f}s")


# ==================================================================
# 2. SIGNAL CONSTRUCTION
# ==================================================================
print("\n" + "=" * 90)
print("STEP 2: SIGNAL CONSTRUCTION")
print("=" * 90)


# --- 2a. TSMOM Signal ---
def compute_tsmom_signal(prices_df, lookback_months=6, skip_months=1):
    """
    Compute TSMOM signal for TSMOM_ASSETS.
    Returns monthly signal DataFrame: 1 = long, 0 = cash.
    """
    monthly_prices = prices_df[TSMOM_ASSETS].resample("ME").last()
    signals = pd.DataFrame(index=monthly_prices.index, columns=TSMOM_ASSETS, dtype=float)

    for col in TSMOM_ASSETS:
        # Return from t-lookback to t-skip
        mom = monthly_prices[col].pct_change(lookback_months).shift(skip_months)
        signals[col] = (mom > 0).astype(float)

    signals = signals.dropna(how="any")
    return signals


# --- 2b. VIX Regime Signal ---
def compute_vix_regime(vix_series):
    """
    Classify VIX into regimes. Returns monthly lagged regime.
    """
    monthly_vix = vix_series.resample("ME").last()
    regime = pd.Series("Normal", index=monthly_vix.index)
    regime[monthly_vix < VIX_LOW] = "Low"
    regime[monthly_vix > VIX_HIGH] = "High"
    # Lag by 1 month (signal from this month -> position next month)
    regime_lagged = regime.shift(1)
    regime_lagged = regime_lagged.dropna()
    return regime_lagged, monthly_vix


tsmom_signals = compute_tsmom_signal(asset_prices)
vix_regime, monthly_vix = compute_vix_regime(vix)

print(f"  TSMOM signals: {len(tsmom_signals)} months")
print(f"  VIX regime: {len(vix_regime)} months")

# Align signal dates
common_signal_dates = tsmom_signals.index.intersection(vix_regime.index)
tsmom_signals = tsmom_signals.loc[common_signal_dates]
vix_regime = vix_regime.loc[common_signal_dates]

print(f"  Common signal months: {len(common_signal_dates)}")
print(f"  VIX regime distribution (lagged):")
for r in ["Low", "Normal", "High"]:
    ct = (vix_regime == r).sum()
    print(f"    {r:>7s}: {ct:>4d} months ({ct/len(vix_regime)*100:.1f}%)")

# TSMOM signal summary
for col in TSMOM_ASSETS:
    pct_long = tsmom_signals[col].mean() * 100
    print(f"  TSMOM {col}: {pct_long:.1f}% months long")


# ==================================================================
# 3. STRATEGY CONSTRUCTION
# ==================================================================
print("\n" + "=" * 90)
print("STEP 3: STRATEGY CONSTRUCTION")
print("=" * 90)


def build_daily_returns_from_monthly_weights(daily_ret, signal_dates, weight_func):
    """
    Generic strategy builder.
    weight_func(sig_date) -> dict of {ticker: weight}
    Returns daily portfolio return series.
    """
    portfolio_ret = pd.Series(0.0, index=daily_ret.index)

    for i in range(len(signal_dates) - 1):
        sig_date = signal_dates[i]
        next_sig_date = signal_dates[i + 1]

        weights = weight_func(sig_date)

        mask = (daily_ret.index > sig_date) & (daily_ret.index <= next_sig_date)
        for ticker, w in weights.items():
            if w != 0 and ticker in daily_ret.columns:
                portfolio_ret.loc[mask] += w * daily_ret.loc[mask, ticker]

    return portfolio_ret


# --- Strategy 0: SPY Buy & Hold ---
spy_bh = asset_returns["SPY"].copy()

# --- Strategy 1: 50/50 SPY/GLD + VT ---
def weights_5050vt(sig_date):
    """50/50 SPY/GLD with VT overlay using VIX."""
    if sig_date not in vix_regime.index:
        return {"SPY": 0.50, "GLD": 0.50}
    regime = vix_regime.loc[sig_date]
    if regime == "High":
        return {"SPY": 0.30, "GLD": 0.30, "TLT": 0.40}
    else:
        return {"SPY": 0.50, "GLD": 0.50}


# --- Strategy 2: TSMOM 6_1 alone ---
def weights_tsmom(sig_date):
    """TSMOM 6_1: equal-weight assets with positive momentum, else cash."""
    if sig_date not in tsmom_signals.index:
        return {}
    sigs = tsmom_signals.loc[sig_date]
    n_pos = sigs.sum()
    if n_pos == 0:
        return {}  # all cash
    weights = {}
    for asset in TSMOM_ASSETS:
        if sigs[asset] > 0:
            weights[asset] = 1.0 / n_pos
    return weights


# --- Strategy 3: Sector Rotation (gradual tilt) alone ---
def weights_sector_rotation(sig_date):
    """VIX-based sector rotation: gradual tilt between offense/defense."""
    if sig_date not in vix_regime.index:
        target = OFFENSIVE_SECTORS + DEFENSIVE_SECTORS
        return {s: 1.0 / len(target) for s in target}

    regime = vix_regime.loc[sig_date]
    # Get actual VIX for gradual tilt
    mvix_lagged = monthly_vix.shift(1)
    if sig_date in mvix_lagged.index:
        v = mvix_lagged.loc[sig_date]
    else:
        v = 20  # default

    if np.isnan(v):
        v = 20

    # Gradual tilt based on VIX level
    vix_center = (VIX_LOW + VIX_HIGH) / 2  # 20
    vix_range = (VIX_HIGH - VIX_LOW) / 2   # 5
    offense_frac = 0.5 - 0.3 * (v - vix_center) / max(vix_range, 1)
    offense_frac = np.clip(offense_frac, 0.1, 0.9)
    defense_frac = 1.0 - offense_frac

    weights = {}
    for s in OFFENSIVE_SECTORS:
        weights[s] = offense_frac / len(OFFENSIVE_SECTORS)
    for s in DEFENSIVE_SECTORS:
        weights[s] = defense_frac / len(DEFENSIVE_SECTORS)
    return weights


# --- Combined Strategy A: Hierarchical ---
# TSMOM decides: what fraction goes to equity vs GLD/TLT
# Sector rotation decides: WHICH sectors get the equity allocation
def weights_combined_hierarchical(sig_date):
    """
    Hierarchical combination:
    1. TSMOM determines macro allocation:
       - SPY momentum positive → equity sleeve = active (sector rotation)
       - GLD momentum positive → allocate to GLD
       - TLT momentum positive → allocate to TLT
       - If nothing positive → all cash
    2. Sector rotation determines WHICH sectors for equity sleeve
    """
    if sig_date not in tsmom_signals.index:
        return {}

    sigs = tsmom_signals.loc[sig_date]
    n_pos = sigs.sum()

    if n_pos == 0:
        return {}  # all cash

    # Allocate equally among positive momentum asset classes
    alloc_per_asset = 1.0 / n_pos
    weights = {}

    # GLD and TLT: direct allocation if momentum positive
    if sigs["GLD"] > 0:
        weights["GLD"] = alloc_per_asset
    if sigs["TLT"] > 0:
        weights["TLT"] = alloc_per_asset

    # SPY momentum positive → use sector rotation for that sleeve
    if sigs["SPY"] > 0:
        equity_budget = alloc_per_asset
        # Get sector rotation weights for equity sleeve
        sr_weights = weights_sector_rotation(sig_date)
        total_sr = sum(sr_weights.values())
        if total_sr > 0:
            for sector, w in sr_weights.items():
                weights[sector] = equity_budget * (w / total_sr)
        else:
            weights["SPY"] = equity_budget  # fallback to SPY

    return weights


# --- Combined Strategy B: Dual Signal ---
# Only long when BOTH signals agree
def weights_combined_dual_signal(sig_date):
    """
    Dual signal: only long when BOTH momentum positive AND VIX favorable.
    - For equity (SPY): need SPY momentum >0 AND VIX not High
    - For GLD: need GLD momentum >0 (VIX High OK for gold)
    - For TLT: need TLT momentum >0 AND VIX High (bonds = crisis)
    - For sectors: need SPY momentum >0 AND VIX signal matches
    """
    if sig_date not in tsmom_signals.index:
        return {}

    sigs = tsmom_signals.loc[sig_date]
    regime = vix_regime.loc[sig_date] if sig_date in vix_regime.index else "Normal"

    active_weights = {}

    # GLD: only need positive momentum (gold works in all regimes)
    if sigs["GLD"] > 0:
        active_weights["GLD"] = 1.0

    # TLT: positive momentum AND high VIX (bonds for crisis)
    if sigs["TLT"] > 0 and regime in ["High", "Normal"]:
        active_weights["TLT"] = 1.0

    # Equity sleeve: SPY momentum positive AND VIX not High
    if sigs["SPY"] > 0 and regime != "High":
        # Use sector rotation for equity allocation
        if regime == "Low":
            # Offensive sectors
            for s in OFFENSIVE_SECTORS:
                active_weights[s] = 1.0 / len(OFFENSIVE_SECTORS)
        else:
            # Normal: balanced sectors
            target = OFFENSIVE_SECTORS + DEFENSIVE_SECTORS
            for s in target:
                active_weights[s] = 1.0 / len(target)
    elif sigs["SPY"] > 0 and regime == "High":
        # SPY momentum positive but VIX high → defensive sectors only
        for s in DEFENSIVE_SECTORS:
            active_weights[s] = 1.0 / len(DEFENSIVE_SECTORS)

    if not active_weights:
        return {}  # all cash

    # Normalize to sum = 1
    total = sum(active_weights.values())
    return {k: v / total for k, v in active_weights.items()}


# --- Combined Strategy C: Simple Blend ---
# 50% TSMOM + 50% Sector Rotation
def weights_combined_blend(sig_date):
    """50% TSMOM portfolio + 50% sector rotation portfolio."""
    tsmom_w = weights_tsmom(sig_date)
    sr_w = weights_sector_rotation(sig_date)

    combined = {}
    all_keys = set(list(tsmom_w.keys()) + list(sr_w.keys()))
    for k in all_keys:
        combined[k] = 0.5 * tsmom_w.get(k, 0) + 0.5 * sr_w.get(k, 0)
    return combined


# Build all strategy returns
print("\n  Building strategy returns...")
sig_dates = common_signal_dates

strategies = {}
strategy_names = {
    "SPY_BH": "SPY Buy & Hold",
    "5050_VT": "50/50 SPY/GLD + VT",
    "TSMOM_6_1": "TSMOM 6_1 (K241)",
    "SectorRot": "Sector Rotation (K243)",
    "Combined_A": "A: Hierarchical (TSMOM→Sectors)",
    "Combined_B": "B: Dual Signal (Both Agree)",
    "Combined_C": "C: 50/50 Blend",
}

strategies["SPY_BH"] = spy_bh
strategies["5050_VT"] = build_daily_returns_from_monthly_weights(asset_returns, sig_dates, weights_5050vt)
strategies["TSMOM_6_1"] = build_daily_returns_from_monthly_weights(asset_returns, sig_dates, weights_tsmom)
strategies["SectorRot"] = build_daily_returns_from_monthly_weights(asset_returns, sig_dates, weights_sector_rotation)
strategies["Combined_A"] = build_daily_returns_from_monthly_weights(asset_returns, sig_dates, weights_combined_hierarchical)
strategies["Combined_B"] = build_daily_returns_from_monthly_weights(asset_returns, sig_dates, weights_combined_dual_signal)
strategies["Combined_C"] = build_daily_returns_from_monthly_weights(asset_returns, sig_dates, weights_combined_blend)

# Trim to common analysis period (drop initial NaN/zero from signal warmup)
analysis_start_actual = pd.Timestamp(ANALYSIS_START)
for key in strategies:
    strategies[key] = strategies[key][strategies[key].index >= analysis_start_actual]

print(f"  Done. Strategy return series lengths:")
for key, ret in strategies.items():
    nonzero = (ret != 0).sum()
    print(f"    {key:>15s}: {len(ret)} days, {nonzero} non-zero ({nonzero/len(ret)*100:.1f}%)")


# ==================================================================
# 4. PERFORMANCE METRICS
# ==================================================================
print("\n" + "=" * 90)
print("STEP 4: FULL-SAMPLE PERFORMANCE")
print("=" * 90)


def compute_metrics(returns, name=""):
    """Compute comprehensive performance metrics."""
    r = returns.dropna()
    if len(r) < 252:
        return {}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 1e-8 else 0

    # Max drawdown
    cum = (1 + r).cumprod()
    rolling_max = cum.cummax()
    dd = cum / rolling_max - 1
    max_dd = dd.min()

    # Calmar
    calmar = ann_ret / abs(max_dd) if abs(max_dd) > 1e-8 else 0

    # Sortino
    downside = r[r < 0]
    downside_vol = downside.std() * np.sqrt(252) if len(downside) > 10 else ann_vol
    sortino = (ann_ret - RF_ANNUAL) / downside_vol if downside_vol > 1e-8 else 0

    # Monthly t-stat (Harvey test)
    monthly_ret = (1 + r).resample("ME").prod() - 1
    monthly_excess = monthly_ret - RF_ANNUAL / 12
    if monthly_excess.std() > 1e-8:
        t_stat = monthly_excess.mean() / (monthly_excess.std() / np.sqrt(len(monthly_excess)))
    else:
        t_stat = 0

    # Win rate
    win_rate = (r > 0).mean()

    # Time in market
    time_in_market = (r.abs() > 1e-10).mean()

    # Skew / Kurtosis
    skew = r.skew()
    kurt = r.kurtosis()

    return {
        "name": name,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "max_dd": max_dd,
        "calmar": calmar,
        "sortino": sortino,
        "t_stat": t_stat,
        "harvey_pass": abs(t_stat) > 3.0,
        "n_months": len(monthly_ret),
        "win_rate": win_rate,
        "time_in_market": time_in_market,
        "skew": skew,
        "kurtosis": kurt,
    }


# Full sample metrics
print(f"\n  {'Strategy':<35s} | {'Ann.Ret':>8s} | {'Ann.Vol':>8s} | {'Sharpe':>7s} | "
      f"{'MDD':>8s} | {'Calmar':>7s} | {'Sortino':>8s} | {'t-stat':>7s} | {'Harvey':>6s} | {'TiM':>5s}")
print("  " + "-" * 130)

full_metrics = {}
for key in strategy_names:
    m = compute_metrics(strategies[key], name=strategy_names[key])
    full_metrics[key] = m
    if m:
        harvey = "PASS" if m["harvey_pass"] else "fail"
        print(f"  {strategy_names[key]:<35s} | {m['ann_return']:>+7.1%} | {m['ann_vol']:>7.1%} | "
              f"{m['sharpe']:>7.3f} | {m['max_dd']:>+7.1%} | {m['calmar']:>7.3f} | "
              f"{m['sortino']:>8.3f} | {m['t_stat']:>7.3f} | {harvey:>6s} | "
              f"{m['time_in_market']:>4.0%}")


# ==================================================================
# 5. DIEBOLD-MARIANO TESTS
# ==================================================================
print("\n" + "=" * 90)
print("STEP 5: DIEBOLD-MARIANO TESTS (pairwise)")
print("=" * 90)


def dm_test(ret1, ret2, name1="Strategy", name2="Benchmark"):
    """
    Diebold-Mariano test using return differentials.
    H0: mean(ret1 - ret2) = 0
    Returns t-stat and p-value.
    """
    common = ret1.index.intersection(ret2.index)
    r1 = ret1.loc[common].dropna()
    r2 = ret2.loc[common].dropna()
    common2 = r1.index.intersection(r2.index)
    r1 = r1.loc[common2]
    r2 = r2.loc[common2]

    d = r1 - r2
    if len(d) < 30:
        return {"t_stat": np.nan, "p_value": np.nan, "n": len(d)}

    # Newey-West HAC adjustment (lag = int(len^(1/3)))
    n = len(d)
    max_lag = int(n ** (1 / 3))
    d_mean = d.mean()
    d_demean = d - d_mean

    # Autocovariance
    gamma_0 = (d_demean ** 2).sum() / n
    gamma_sum = gamma_0
    for lag in range(1, max_lag + 1):
        gamma_j = (d_demean.iloc[lag:].values * d_demean.iloc[:-lag].values).sum() / n
        weight = 1 - lag / (max_lag + 1)  # Bartlett kernel
        gamma_sum += 2 * weight * gamma_j

    var_d = gamma_sum / n
    if var_d <= 0:
        return {"t_stat": np.nan, "p_value": np.nan, "n": n}

    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))

    return {"t_stat": t_stat, "p_value": p_value, "n": n}


# Test combined strategies vs all benchmarks
combined_keys = ["Combined_A", "Combined_B", "Combined_C"]
benchmark_keys = ["SPY_BH", "5050_VT", "TSMOM_6_1", "SectorRot"]

print(f"\n  {'Strategy vs Benchmark':<50s} | {'DM t-stat':>10s} | {'p-value':>8s} | {'Significant':>11s}")
print("  " + "-" * 85)

dm_results = {}
for comb in combined_keys:
    for bench in benchmark_keys:
        result = dm_test(strategies[comb], strategies[bench],
                         strategy_names[comb], strategy_names[bench])
        label = f"{strategy_names[comb]} vs {strategy_names[bench]}"
        dm_results[f"{comb}_vs_{bench}"] = result
        sig = "YES (p<0.05)" if result["p_value"] < 0.05 else "no"
        if not np.isnan(result["t_stat"]):
            print(f"  {label:<50s} | {result['t_stat']:>10.3f} | {result['p_value']:>8.4f} | {sig:>11s}")
        else:
            print(f"  {label:<50s} | {'N/A':>10s} | {'N/A':>8s} | {'N/A':>11s}")

# Also test TSMOM vs Sector Rotation (orthogonality check)
print(f"\n  Orthogonality check:")
result = dm_test(strategies["TSMOM_6_1"], strategies["SectorRot"])
print(f"  TSMOM vs SectorRot: DM t={result['t_stat']:.3f}, p={result['p_value']:.4f}")

# Return correlation between TSMOM and sector rotation (orthogonality)
common_idx2 = strategies["TSMOM_6_1"].index.intersection(strategies["SectorRot"].index)
tsmom_r = strategies["TSMOM_6_1"].loc[common_idx2]
sr_r = strategies["SectorRot"].loc[common_idx2]
# Only correlate days where both have non-zero returns
both_active = (tsmom_r.abs() > 1e-10) & (sr_r.abs() > 1e-10)
if both_active.sum() > 30:
    corr = tsmom_r[both_active].corr(sr_r[both_active])
    print(f"  Return correlation (active days): {corr:.4f}")
else:
    print(f"  Return correlation: insufficient overlapping active days")


# ==================================================================
# 6. CROSS-OOS VALIDATION (5 periods)
# ==================================================================
print("\n" + "=" * 90)
print("STEP 6: CROSS-OOS VALIDATION (5-period)")
print("=" * 90)


def compute_oos_metrics(returns, fold_start, fold_end):
    """Compute metrics for an OOS fold."""
    mask = (returns.index >= fold_start) & (returns.index <= fold_end)
    r = returns[mask]
    if len(r) < 100:
        return None
    return compute_metrics(r)


oos_results = {}
for key in strategy_names:
    oos_results[key] = []

for fold_idx, (f_start, f_end) in enumerate(OOS_FOLDS):
    print(f"\n  Fold {fold_idx+1}: {f_start} to {f_end}")
    print(f"    {'Strategy':<35s} | {'Ann.Ret':>8s} | {'Sharpe':>7s} | {'MDD':>8s} | {'t-stat':>7s} | Days")
    print("    " + "-" * 80)

    for key in strategy_names:
        m = compute_oos_metrics(strategies[key], f_start, f_end)
        if m:
            m["fold"] = fold_idx + 1
            m["fold_start"] = f_start
            m["fold_end"] = f_end
            oos_results[key].append(m)
            print(f"    {strategy_names[key]:<35s} | {m['ann_return']:>+7.1%} | {m['sharpe']:>7.3f} | "
                  f"{m['max_dd']:>+7.1%} | {m['t_stat']:>7.3f} | {m['n_months']*21}")
        else:
            print(f"    {strategy_names[key]:<35s} | insufficient data")

# OOS summary
print(f"\n  OOS SUMMARY — Average Sharpe across folds:")
print(f"  {'Strategy':<35s} | {'Avg Sharpe':>10s} | {'Min Sharpe':>10s} | {'Max Sharpe':>10s} | "
      f"{'Positive':>8s} | {'Consistency':>11s}")
print("  " + "-" * 100)

oos_summary = {}
for key in strategy_names:
    if oos_results[key]:
        sharpes = [m["sharpe"] for m in oos_results[key]]
        avg_sharpe = np.mean(sharpes)
        min_sharpe = np.min(sharpes)
        max_sharpe = np.max(sharpes)
        n_positive = sum(1 for s in sharpes if s > 0)
        consistency = f"{n_positive}/{len(sharpes)}"
        oos_summary[key] = {
            "avg_sharpe": avg_sharpe,
            "min_sharpe": min_sharpe,
            "max_sharpe": max_sharpe,
            "n_positive": n_positive,
            "n_folds": len(sharpes),
        }
        print(f"  {strategy_names[key]:<35s} | {avg_sharpe:>10.3f} | {min_sharpe:>10.3f} | "
              f"{max_sharpe:>10.3f} | {n_positive:>4d}/{len(sharpes):<3d} | {consistency:>11s}")


# ==================================================================
# 7. BOOTSTRAP CONFIDENCE INTERVALS
# ==================================================================
print("\n" + "=" * 90)
print("STEP 7: BOOTSTRAP CONFIDENCE INTERVALS (Sharpe & MDD)")
print("=" * 90)


def bootstrap_sharpe_mdd(returns, n_boot=10000, block_size=21):
    """
    Stationary block bootstrap for Sharpe ratio and MDD.
    Block size = 21 (monthly blocks to preserve autocorrelation).
    """
    r = returns.dropna().values
    n = len(r)
    if n < 252:
        return None

    sharpes = np.zeros(n_boot)
    mdds = np.zeros(n_boot)

    for b in range(n_boot):
        # Block bootstrap
        boot_r = np.zeros(n)
        idx = 0
        while idx < n:
            # Random block start
            start = np.random.randint(0, n)
            # Geometric block length
            length = min(np.random.geometric(1.0 / block_size), n - idx)
            end = min(start + length, n)
            actual_len = end - start
            boot_r[idx:idx + actual_len] = r[start:end]
            idx += actual_len

        # Sharpe
        ann_ret = np.mean(boot_r) * 252
        ann_vol = np.std(boot_r) * np.sqrt(252)
        sharpes[b] = (ann_ret - RF_ANNUAL) / ann_vol if ann_vol > 1e-8 else 0

        # MDD
        cum = np.cumprod(1 + boot_r)
        running_max = np.maximum.accumulate(cum)
        dd = cum / running_max - 1
        mdds[b] = np.min(dd)

    return {
        "sharpe_mean": np.mean(sharpes),
        "sharpe_ci_lo": np.percentile(sharpes, 2.5),
        "sharpe_ci_hi": np.percentile(sharpes, 97.5),
        "mdd_mean": np.mean(mdds),
        "mdd_ci_lo": np.percentile(mdds, 2.5),
        "mdd_ci_hi": np.percentile(mdds, 97.5),
    }


np.random.seed(42)
print(f"\n  {'Strategy':<35s} | {'Sharpe':>7s} | {'95% CI':>20s} | {'MDD':>8s} | {'95% CI':>20s}")
print("  " + "-" * 100)

boot_results = {}
for key in strategy_names:
    br = bootstrap_sharpe_mdd(strategies[key], n_boot=N_BOOTSTRAP)
    boot_results[key] = br
    if br:
        print(f"  {strategy_names[key]:<35s} | {br['sharpe_mean']:>7.3f} | "
              f"[{br['sharpe_ci_lo']:>+.3f}, {br['sharpe_ci_hi']:>+.3f}] | "
              f"{br['mdd_mean']:>+7.1%} | [{br['mdd_ci_lo']:>+.1%}, {br['mdd_ci_hi']:>+.1%}]")


# ==================================================================
# 8. CRISIS PERIOD ANALYSIS
# ==================================================================
print("\n" + "=" * 90)
print("STEP 8: CRISIS PERIOD ANALYSIS")
print("=" * 90)

crisis_periods = [
    ("GFC (2008)", "2008-09-01", "2009-03-31"),
    ("COVID (2020)", "2020-02-15", "2020-04-15"),
    ("2022 Bear", "2022-01-01", "2022-10-31"),
    ("Taper Tantrum (2013)", "2013-05-01", "2013-09-30"),
    ("VIX Spike (2018)", "2018-01-25", "2018-03-31"),
]

for crisis_name, c_start, c_end in crisis_periods:
    print(f"\n  {crisis_name}: {c_start} to {c_end}")
    print(f"    {'Strategy':<35s} | {'Return':>8s} | {'MDD':>8s} | {'Sharpe':>7s}")
    print(f"    " + "-" * 65)

    for key in strategy_names:
        mask = (strategies[key].index >= c_start) & (strategies[key].index <= c_end)
        r = strategies[key][mask]
        if len(r) > 5:
            total_ret = (1 + r).prod() - 1
            cum = (1 + r).cumprod()
            mdd = (cum / cum.cummax() - 1).min()
            ann_vol = r.std() * np.sqrt(252)
            sharpe = (r.mean() * 252 - RF_ANNUAL) / ann_vol if ann_vol > 1e-8 else 0
            print(f"    {strategy_names[key]:<35s} | {total_ret:>+7.1%} | {mdd:>+7.1%} | {sharpe:>7.3f}")


# ==================================================================
# 9. SIGNAL ORTHOGONALITY ANALYSIS
# ==================================================================
print("\n" + "=" * 90)
print("STEP 9: SIGNAL ORTHOGONALITY & INTERACTION ANALYSIS")
print("=" * 90)

# When do TSMOM and VIX regime agree/disagree?
agreement_analysis = pd.DataFrame(index=common_signal_dates)
agreement_analysis["spy_mom_positive"] = tsmom_signals["SPY"]
agreement_analysis["vix_low"] = (vix_regime == "Low").astype(float)
agreement_analysis["vix_high"] = (vix_regime == "High").astype(float)
agreement_analysis["vix_normal"] = (vix_regime == "Normal").astype(float)

# Quadrants
agreement_analysis["agree_bullish"] = (agreement_analysis["spy_mom_positive"] == 1) & \
                                       (agreement_analysis["vix_low"] == 1)
agreement_analysis["agree_bearish"] = (agreement_analysis["spy_mom_positive"] == 0) & \
                                       (agreement_analysis["vix_high"] == 1)
agreement_analysis["disagree_mom_up_vix_high"] = (agreement_analysis["spy_mom_positive"] == 1) & \
                                                   (agreement_analysis["vix_high"] == 1)
agreement_analysis["disagree_mom_down_vix_low"] = (agreement_analysis["spy_mom_positive"] == 0) & \
                                                    (agreement_analysis["vix_low"] == 1)

print(f"\n  Signal agreement analysis ({len(agreement_analysis)} months):")
n_total = len(agreement_analysis)
for label, col in [
    ("Both bullish (SPY mom+ & VIX low)", "agree_bullish"),
    ("Both bearish (SPY mom- & VIX high)", "agree_bearish"),
    ("Disagree: Mom+ but VIX high", "disagree_mom_up_vix_high"),
    ("Disagree: Mom- but VIX low", "disagree_mom_down_vix_low"),
]:
    ct = agreement_analysis[col].sum()
    print(f"    {label:<45s}: {ct:>4.0f} months ({ct/n_total*100:.1f}%)")

# What happens in each quadrant?
print(f"\n  Next-month SPY return by signal quadrant:")
monthly_spy_ret = (1 + asset_returns["SPY"]).resample("ME").prod() - 1

for label, col in [
    ("Both bullish", "agree_bullish"),
    ("Both bearish", "agree_bearish"),
    ("Mom+ but VIX high", "disagree_mom_up_vix_high"),
    ("Mom- but VIX low", "disagree_mom_down_vix_low"),
]:
    mask_months = agreement_analysis[col]
    # Shift by 1 to get NEXT month return
    next_month_rets = []
    for dt in agreement_analysis.index[mask_months]:
        next_months = monthly_spy_ret.index[monthly_spy_ret.index > dt]
        if len(next_months) > 0:
            next_month_rets.append(monthly_spy_ret.loc[next_months[0]])

    if next_month_rets:
        avg_ret = np.mean(next_month_rets)
        med_ret = np.median(next_month_rets)
        pct_pos = sum(1 for r in next_month_rets if r > 0) / len(next_month_rets)
        print(f"    {label:<30s}: avg={avg_ret:>+.2%}, median={med_ret:>+.2%}, "
              f"hit rate={pct_pos:.1%}, n={len(next_month_rets)}")


# ==================================================================
# 10. TRANSACTION COST SENSITIVITY
# ==================================================================
print("\n" + "=" * 90)
print("STEP 10: TRANSACTION COST SENSITIVITY")
print("=" * 90)


def estimate_turnover(weight_func, signal_dates_list):
    """Estimate annual turnover by counting weight changes."""
    prev_weights = {}
    total_turnover = 0
    n_rebalances = 0

    for sig_date in signal_dates_list:
        current_weights = weight_func(sig_date)
        if prev_weights:
            # Compute turnover = sum of |weight changes|
            all_keys = set(list(prev_weights.keys()) + list(current_weights.keys()))
            turnover = sum(abs(current_weights.get(k, 0) - prev_weights.get(k, 0)) for k in all_keys)
            total_turnover += turnover
            n_rebalances += 1
        prev_weights = current_weights

    if n_rebalances == 0:
        return 0

    # Annualize: n_rebalances over ~20 years, so avg per year
    years = n_rebalances / 12.0
    annual_turnover = total_turnover / years if years > 0 else 0
    return annual_turnover


# Estimate turnover for each combined strategy
turnovers = {
    "TSMOM_6_1": estimate_turnover(weights_tsmom, list(sig_dates)),
    "SectorRot": estimate_turnover(weights_sector_rotation, list(sig_dates)),
    "Combined_A": estimate_turnover(weights_combined_hierarchical, list(sig_dates)),
    "Combined_B": estimate_turnover(weights_combined_dual_signal, list(sig_dates)),
    "Combined_C": estimate_turnover(weights_combined_blend, list(sig_dates)),
}

print(f"\n  Estimated annual turnover:")
for key, to in turnovers.items():
    print(f"    {strategy_names[key]:<35s}: {to:.2f}x")

# Net Sharpe after costs
cost_levels = [5, 10, 20, 50]  # bps per trade
print(f"\n  Net Sharpe after transaction costs:")
print(f"  {'Strategy':<35s} | {'Gross':>7s} | " + " | ".join(f"{c}bps" for c in cost_levels))
print("  " + "-" * (46 + 9 * len(cost_levels)))

for key in ["TSMOM_6_1", "SectorRot", "Combined_A", "Combined_B", "Combined_C"]:
    gross_sharpe = full_metrics[key]["sharpe"]
    turnover = turnovers[key]
    row = f"  {strategy_names[key]:<35s} | {gross_sharpe:>7.3f} |"
    for cost_bps in cost_levels:
        # Annual cost = turnover * cost_bps / 10000
        annual_cost = turnover * cost_bps / 10000
        net_ret = full_metrics[key]["ann_return"] - annual_cost
        net_sharpe = (net_ret - RF_ANNUAL) / full_metrics[key]["ann_vol"] if full_metrics[key]["ann_vol"] > 1e-8 else 0
        row += f" {net_sharpe:>7.3f} |"
    print(row)


# ==================================================================
# 11. CORRELATION MATRIX
# ==================================================================
print("\n" + "=" * 90)
print("STEP 11: STRATEGY RETURN CORRELATIONS")
print("=" * 90)

# Collect returns into DataFrame
ret_df = pd.DataFrame({strategy_names[k]: strategies[k] for k in strategy_names})
corr_matrix = ret_df.corr()

print(f"\n  Correlation matrix (daily returns):")
# Print header
header = "  " + " " * 15
for name in strategy_names.values():
    header += f" | {name[:12]:>12s}"
print(header)
print("  " + "-" * (15 + 15 * len(strategy_names)))

for k1, n1 in strategy_names.items():
    row = f"  {n1[:15]:<15s}"
    for k2, n2 in strategy_names.items():
        c = corr_matrix.loc[n1, n2]
        row += f" | {c:>12.3f}"
    print(row)


# ==================================================================
# 12. FINAL VERDICT
# ==================================================================
print("\n" + "=" * 90)
print("STEP 12: FINAL VERDICT — Does Combining Signals Create Alpha?")
print("=" * 90)

print("\n  KEY FINDINGS:")
print()

# Find the best combined strategy
best_combined = None
best_sharpe = -999
for key in combined_keys:
    if full_metrics[key]["sharpe"] > best_sharpe:
        best_sharpe = full_metrics[key]["sharpe"]
        best_combined = key

print(f"  1. BEST COMBINED STRATEGY: {strategy_names[best_combined]}")
print(f"     Sharpe: {full_metrics[best_combined]['sharpe']:.3f}, "
      f"MDD: {full_metrics[best_combined]['max_dd']:.1%}, "
      f"Harvey t: {full_metrics[best_combined]['t_stat']:.3f} "
      f"({'PASS' if full_metrics[best_combined]['harvey_pass'] else 'FAIL'})")

print()
print(f"  2. DM TEST SIGNIFICANCE:")
for bench in benchmark_keys:
    key = f"{best_combined}_vs_{bench}"
    if key in dm_results:
        r = dm_results[key]
        sig = "SIGNIFICANT" if r["p_value"] < 0.05 else "NOT significant"
        if not np.isnan(r["t_stat"]):
            print(f"     vs {strategy_names[bench]:<25s}: t={r['t_stat']:>+.3f}, p={r['p_value']:.4f} — {sig}")

print()
print(f"  3. CROSS-OOS CONSISTENCY:")
for key in combined_keys:
    if key in oos_summary:
        s = oos_summary[key]
        print(f"     {strategy_names[key]:<35s}: {s['n_positive']}/{s['n_folds']} positive, "
              f"avg Sharpe {s['avg_sharpe']:.3f}")

print()
print(f"  4. KEY QUESTION ANSWER: Does combining create genuine DM-significant alpha?")
dm_significant_any = False
for comb in combined_keys:
    for bench in benchmark_keys:
        key = f"{comb}_vs_{bench}"
        if key in dm_results and not np.isnan(dm_results[key]["p_value"]):
            if dm_results[key]["p_value"] < 0.05 and dm_results[key]["t_stat"] > 0:
                dm_significant_any = True
                print(f"     YES — {strategy_names[comb]} vs {strategy_names[bench]}: "
                      f"DM t={dm_results[key]['t_stat']:.3f}, p={dm_results[key]['p_value']:.4f}")

if not dm_significant_any:
    print(f"     NO — None of the combined strategies achieve DM significance vs ANY benchmark.")
    print(f"     This is consistent with the Efficient Market Hypothesis: combining")
    print(f"     two individually strong signals does not automatically create alpha")
    print(f"     beyond what diversification already provides.")

print()
print(f"  5. PRACTICAL ASSESSMENT:")
# Best risk-adjusted strategy
all_keys_sorted = sorted(strategy_names.keys(), key=lambda k: full_metrics[k].get("sharpe", 0), reverse=True)
print(f"     Ranking by Sharpe:")
for i, key in enumerate(all_keys_sorted):
    m = full_metrics[key]
    tag = " ← BEST" if i == 0 else ""
    tag2 = " ★" if key in combined_keys else ""
    print(f"       {i+1}. {strategy_names[key]:<35s}: Sharpe {m['sharpe']:.3f}, MDD {m['max_dd']:.1%}{tag2}{tag}")


# ==================================================================
# SAVE RESULTS
# ==================================================================
print("\n" + "=" * 90)
print("SAVING RESULTS")
print("=" * 90)

results = {
    "experiment": "K244",
    "title": "Combined TSMOM + Sector Rotation",
    "date": datetime.now().isoformat(),
    "data_source": "yfinance",
    "period": f"{ANALYSIS_START} to 2024-12-31",
    "assets": {
        "tsmom": TSMOM_ASSETS,
        "offensive_sectors": OFFENSIVE_SECTORS,
        "defensive_sectors": DEFENSIVE_SECTORS,
    },
    "full_sample_metrics": {},
    "dm_tests": {},
    "oos_summary": {},
    "bootstrap": {},
    "turnovers": turnovers,
}

for key in strategy_names:
    m = full_metrics[key]
    results["full_sample_metrics"][key] = {
        k: (float(v) if isinstance(v, (np.floating, float)) else v)
        for k, v in m.items()
    }

for key, val in dm_results.items():
    results["dm_tests"][key] = {
        k: (float(v) if isinstance(v, (np.floating, float)) else v)
        for k, v in val.items()
    }

for key in strategy_names:
    if key in oos_summary:
        results["oos_summary"][key] = {
            k: (float(v) if isinstance(v, (np.floating, float)) else v)
            for k, v in oos_summary[key].items()
        }

for key in strategy_names:
    if boot_results.get(key):
        results["bootstrap"][key] = {
            k: float(v) for k, v in boot_results[key].items()
        }

results_path = "experiments/k244_combined_strategy_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to {results_path}")

print("\n" + "=" * 90)
print("K244 COMPLETE")
print("=" * 90)
