"""
K206: Asset-Specific VT Design Framework — Optimal Predictor Per Asset Class
=============================================================================
Background: K202-K203 discovered VIX sufficiency has boundaries:
  - Equities (SPY/QQQ/EEM): VIX sufficient
  - BTC: Range ratio (r=0.483) >> VIX (r=0.048)
  - GLD: Momentum (partial r=0.39) >> VIX
  - TLT: Momentum (partial r=0.22) + Persistence (r=0.23)

Can we build an OPTIMAL per-asset VT system that uses VIX for equities
but asset-specific predictors for non-equities?

Methodology:
  1. Asset-specific VT rules:
     - SPY: 12/VIX (proven optimal)
     - GLD: 12/rolling_22d_vol (use own vol, not VIX) + momentum adjustment
     - TLT: 12/rolling_22d_vol + persistence signal
     - BTC: 12/range_ratio_22d (from K205)
  2. Multi-asset portfolio: 25% each (SPY/GLD/TLT/BTC)
  3. Compare:
     - Uniform 12/VIX for all assets
     - Asset-specific VT (different predictor per asset)
     - Simple 50/50 SPY/GLD with 12/VIX
  4. Monthly rebalancing, TX costs 0.1% per trade
  5. Walk-forward validation (OOS: 2023-2024)
  6. Statistical tests: DM test, bootstrap Sharpe comparison, Harvey threshold

Data: SPY, GLD, TLT, BTC-USD daily from yfinance (2015-2024)

[提出: 用戶, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
from datetime import datetime
from pathlib import Path

np.random.seed(42)
EXPERIMENT_DIR = Path(__file__).resolve().parent

# ============================================================
# 1. DOWNLOAD DATA
# ============================================================
print("=" * 70)
print("K206: Asset-Specific VT Design Framework")
print("=" * 70)

print("\n[1/8] Downloading data from yfinance...")

tickers = {
    "SPY": "SPY",
    "GLD": "GLD",
    "TLT": "TLT",
    "BTC": "BTC-USD",
    "VIX": "^VIX",
}

raw_prices = {}
raw_high = {}
raw_low = {}

for name, ticker in tickers.items():
    df = yf.download(ticker, start="2014-01-01", end="2025-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col = "Adj Close" if "Adj Close" in df.columns else "Close"
    raw_prices[name] = df[col].copy()
    if name != "VIX":
        raw_high[name] = df["High"].copy()
        raw_low[name] = df["Low"].copy()
    print(f"  {name}: {len(df)} obs, {df.index[0].date()} ~ {df.index[-1].date()}")

# Combine into DataFrames
prices = pd.DataFrame(raw_prices).dropna()
highs = pd.DataFrame(raw_high).reindex(prices.index).ffill()
lows = pd.DataFrame(raw_low).reindex(prices.index).ffill()

# Compute returns
assets = ["SPY", "GLD", "TLT", "BTC"]
returns = prices[assets].pct_change().dropna()
vix = prices["VIX"].reindex(returns.index).ffill()

print(f"\n  Combined: {len(returns)} obs, {returns.index[0].date()} ~ {returns.index[-1].date()}")

# ============================================================
# 2. COMPUTE PREDICTORS
# ============================================================
print("\n[2/8] Computing asset-specific predictors...")

# 2a. VIX (for SPY and uniform baseline)
# Already have VIX series

# 2b. Rolling 22d realized vol (annualized, for GLD and TLT)
rolling_vol = {}
for asset in assets:
    rv = returns[asset].rolling(22).std() * np.sqrt(252) * 100  # annualized %
    rolling_vol[asset] = rv
rolling_vol_df = pd.DataFrame(rolling_vol)

# 2c. Momentum signals
momentum = {}
for asset in assets:
    # 22d log return momentum
    mom_22d = np.log(prices[asset] / prices[asset].shift(22))
    momentum[asset] = mom_22d.reindex(returns.index)
momentum_df = pd.DataFrame(momentum)

# 2d. Range ratio for BTC (22d average of daily high/low range)
range_ratio = {}
for asset in assets:
    daily_range = (highs[asset] - lows[asset]) / prices[asset].reindex(highs.index).ffill()
    rr_22d = daily_range.rolling(22).mean() * np.sqrt(252) * 100  # annualized %
    range_ratio[asset] = rr_22d.reindex(returns.index)
range_ratio_df = pd.DataFrame(range_ratio)

# 2e. Persistence signal for TLT (autocorrelation of returns, 22d rolling)
persistence = {}
for asset in assets:
    ret_series = returns[asset]
    pers = ret_series.rolling(22).apply(lambda x: x.autocorr(lag=1), raw=False)
    persistence[asset] = pers
persistence_df = pd.DataFrame(persistence)

print("  Predictors computed: VIX, rolling_vol_22d, momentum_22d, range_ratio_22d, persistence_22d")

# ============================================================
# 3. DEFINE VT WEIGHT FUNCTIONS
# ============================================================
print("\n[3/8] Defining VT weight functions...")

def vt_weight_vix(vix_val, target=12.0):
    """Standard 12/VIX VT weight, capped [0, 1.5]"""
    if pd.isna(vix_val) or vix_val <= 0:
        return 1.0
    w = target / vix_val
    return np.clip(w, 0.0, 1.5)

def vt_weight_own_vol(own_vol, target=12.0):
    """VT using asset's own 22d realized vol, capped [0, 1.5]"""
    if pd.isna(own_vol) or own_vol <= 0:
        return 1.0
    w = target / own_vol
    return np.clip(w, 0.0, 1.5)

def vt_weight_own_vol_mom(own_vol, mom, target=12.0, mom_scale=0.2):
    """
    VT using own vol + momentum adjustment:
      - Positive momentum → slightly increase weight (confidence)
      - Negative momentum → slightly decrease weight (caution)
    """
    if pd.isna(own_vol) or own_vol <= 0:
        return 1.0
    base_w = target / own_vol
    # Momentum adjustment: scale mom to [-1, +1] range, apply small adjustment
    if pd.isna(mom):
        mom_adj = 0.0
    else:
        mom_adj = np.clip(mom * 5.0, -1.0, 1.0) * mom_scale  # 20% adjustment max
    w = base_w * (1.0 + mom_adj)
    return np.clip(w, 0.0, 1.5)

def vt_weight_own_vol_persistence(own_vol, pers, target=12.0, pers_scale=0.15):
    """
    VT using own vol + persistence signal:
      - High persistence (AC1 > 0) → vol tends to continue → reduce weight
      - Low persistence (AC1 < 0) → vol may reverse → increase weight
    """
    if pd.isna(own_vol) or own_vol <= 0:
        return 1.0
    base_w = target / own_vol
    if pd.isna(pers):
        pers_adj = 0.0
    else:
        # Negative persistence → more mean-reversion → be bolder
        pers_adj = np.clip(-pers, -1.0, 1.0) * pers_scale
    w = base_w * (1.0 + pers_adj)
    return np.clip(w, 0.0, 1.5)

def vt_weight_range_ratio(rr, target=12.0):
    """VT using range ratio (better vol proxy for BTC), capped [0, 1.5]"""
    if pd.isna(rr) or rr <= 0:
        return 1.0
    w = target / rr
    return np.clip(w, 0.0, 1.5)

# ============================================================
# 4. BACKTEST ENGINE
# ============================================================
print("\n[4/8] Running backtests...")

# Define OOS period
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
IS_START = "2015-01-01"

# Filter data to have all predictors available
valid_start = max(
    returns.index[0],
    rolling_vol_df.dropna().index[0],
    momentum_df.dropna().index[0],
    range_ratio_df.dropna().index[0],
    persistence_df.dropna().index[0],
)
print(f"  Valid data start: {valid_start.date()}")

# Mask for OOS
oos_mask = (returns.index >= OOS_START) & (returns.index <= OOS_END)
is_mask = (returns.index >= valid_start) & (returns.index < OOS_START)

print(f"  IS period: {returns.index[is_mask][0].date()} ~ {returns.index[is_mask][-1].date()} (N={is_mask.sum()})")
print(f"  OOS period: {returns.index[oos_mask][0].date()} ~ {returns.index[oos_mask][-1].date()} (N={oos_mask.sum()})")

def compute_monthly_weights(dates, weight_func_dict, rebal_freq=22):
    """
    Compute VT weights for each asset, rebalanced monthly.
    weight_func_dict: {asset: callable(date_idx) -> weight}
    Returns DataFrame of weights.
    """
    weights = pd.DataFrame(index=dates, columns=assets, dtype=float)

    last_rebal = None
    current_weights = {a: 1.0 for a in assets}

    for i, dt in enumerate(dates):
        # Rebalance monthly (every ~22 trading days)
        if last_rebal is None or (i - last_rebal) >= rebal_freq:
            for asset in assets:
                current_weights[asset] = weight_func_dict[asset](dt)
            last_rebal = i

        for asset in assets:
            weights.loc[dt, asset] = current_weights[asset]

    return weights

def backtest_portfolio(returns_df, weights_df, port_weights, tx_cost=0.001):
    """
    Backtest a multi-asset portfolio with VT weights and transaction costs.

    port_weights: dict of {asset: portfolio_allocation} (sum to 1)
    weights_df: VT weights per asset per day
    tx_cost: one-way transaction cost per trade

    Returns: Series of daily portfolio returns (after TX)
    """
    dates = returns_df.index
    port_returns = pd.Series(0.0, index=dates)

    prev_effective_weights = None

    for i, dt in enumerate(dates):
        # Effective weight = portfolio_allocation * VT_weight
        eff_weights = {}
        total_risky = 0.0
        for asset in assets:
            if asset in port_weights:
                vt_w = weights_df.loc[dt, asset] if dt in weights_df.index else 1.0
                eff_w = port_weights[asset] * vt_w
                eff_weights[asset] = eff_w
                total_risky += eff_w
            else:
                eff_weights[asset] = 0.0

        # Cash portion earns 0 (simplification)
        # Portfolio return = sum of (effective_weight * asset_return)
        daily_ret = 0.0
        for asset in assets:
            if asset in port_weights:
                daily_ret += eff_weights[asset] * returns_df.loc[dt, asset]

        # Transaction cost on weight changes
        if prev_effective_weights is not None:
            turnover = sum(abs(eff_weights[a] - prev_effective_weights[a]) for a in assets)
            daily_ret -= turnover * tx_cost

        port_returns.iloc[i] = daily_ret
        prev_effective_weights = eff_weights.copy()

    return port_returns

# ============================================================
# 5. DEFINE STRATEGIES
# ============================================================
print("\n[5/8] Computing strategy weights and returns...")

all_dates = returns.index[returns.index >= valid_start]

# Strategy 1: Uniform 12/VIX for all assets
def make_vix_func(asset):
    def func(dt):
        v = vix.loc[dt] if dt in vix.index else 20.0
        return vt_weight_vix(v)
    return func

uniform_vix_funcs = {a: make_vix_func(a) for a in assets}
uniform_vix_weights = compute_monthly_weights(all_dates, uniform_vix_funcs)

# Strategy 2: Asset-specific VT
def spy_vix_func(dt):
    """SPY: 12/VIX (proven optimal)"""
    v = vix.loc[dt] if dt in vix.index else 20.0
    return vt_weight_vix(v)

def gld_own_vol_mom_func(dt):
    """GLD: 12/own_vol + momentum adjustment"""
    vol = rolling_vol_df.loc[dt, "GLD"] if dt in rolling_vol_df.index else 15.0
    mom = momentum_df.loc[dt, "GLD"] if dt in momentum_df.index else 0.0
    return vt_weight_own_vol_mom(vol, mom, target=12.0)

def tlt_own_vol_pers_func(dt):
    """TLT: 12/own_vol + persistence signal"""
    vol = rolling_vol_df.loc[dt, "TLT"] if dt in rolling_vol_df.index else 10.0
    pers = persistence_df.loc[dt, "TLT"] if dt in persistence_df.index else 0.0
    return vt_weight_own_vol_persistence(vol, pers, target=12.0)

def btc_range_func(dt):
    """BTC: 12/range_ratio_22d"""
    rr = range_ratio_df.loc[dt, "BTC"] if dt in range_ratio_df.index else 50.0
    return vt_weight_range_ratio(rr, target=12.0)

asset_specific_funcs = {
    "SPY": spy_vix_func,
    "GLD": gld_own_vol_mom_func,
    "TLT": tlt_own_vol_pers_func,
    "BTC": btc_range_func,
}
asset_specific_weights = compute_monthly_weights(all_dates, asset_specific_funcs)

# Strategy 3: Buy-and-hold (no VT, full weight)
buyhold_weights = pd.DataFrame(1.0, index=all_dates, columns=assets)

# Strategy 4: GLD own-vol only (no momentum)
def gld_own_vol_func(dt):
    """GLD: 12/own_vol (no momentum)"""
    vol = rolling_vol_df.loc[dt, "GLD"] if dt in rolling_vol_df.index else 15.0
    return vt_weight_own_vol(vol, target=12.0)

# Strategy 5: TLT own-vol only (no persistence)
def tlt_own_vol_func(dt):
    """TLT: 12/own_vol (no persistence)"""
    vol = rolling_vol_df.loc[dt, "TLT"] if dt in rolling_vol_df.index else 10.0
    return vt_weight_own_vol(vol, target=12.0)

# Portfolio allocations
port_equal = {"SPY": 0.25, "GLD": 0.25, "TLT": 0.25, "BTC": 0.25}
port_5050 = {"SPY": 0.50, "GLD": 0.50, "TLT": 0.0, "BTC": 0.0}

# Run backtests for all strategies
strategies = {}

# A. 4-asset equal weight with uniform VIX
strategies["Uniform_VIX_4asset"] = backtest_portfolio(
    returns.loc[all_dates], uniform_vix_weights, port_equal
)

# B. 4-asset equal weight with asset-specific VT
strategies["AssetSpecific_4asset"] = backtest_portfolio(
    returns.loc[all_dates], asset_specific_weights, port_equal
)

# C. 4-asset buy-and-hold (no VT)
strategies["BuyHold_4asset"] = backtest_portfolio(
    returns.loc[all_dates], buyhold_weights, port_equal
)

# D. 50/50 SPY/GLD with uniform VIX
strategies["Uniform_VIX_5050"] = backtest_portfolio(
    returns.loc[all_dates], uniform_vix_weights, port_5050
)

# E. 50/50 SPY/GLD with asset-specific VT (SPY=VIX, GLD=own_vol+mom)
asset_specific_5050_funcs = {
    "SPY": spy_vix_func,
    "GLD": gld_own_vol_mom_func,
    "TLT": tlt_own_vol_pers_func,  # not used in 5050
    "BTC": btc_range_func,  # not used in 5050
}
asset_specific_5050_weights = compute_monthly_weights(all_dates, asset_specific_5050_funcs)
strategies["AssetSpecific_5050"] = backtest_portfolio(
    returns.loc[all_dates], asset_specific_5050_weights, port_5050
)

# F. 50/50 SPY/GLD buy-and-hold
strategies["BuyHold_5050"] = backtest_portfolio(
    returns.loc[all_dates], buyhold_weights, port_5050
)

print("  6 strategies computed.")

# ============================================================
# 6. PERFORMANCE METRICS
# ============================================================
print("\n[6/8] Computing performance metrics...")

def compute_metrics(ret_series, period_mask=None):
    """Compute comprehensive performance metrics."""
    if period_mask is not None:
        r = ret_series[period_mask]
    else:
        r = ret_series

    if len(r) == 0:
        return {}

    ann_ret = r.mean() * 252
    ann_vol = r.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0

    # MDD
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Sortino
    downside = r[r < 0].std() * np.sqrt(252) if (r < 0).sum() > 1 else ann_vol
    sortino = ann_ret / downside if downside > 0 else 0.0

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0.0

    # Win rate
    win_rate = (r > 0).mean()

    # Sharpe t-stat
    n_years = len(r) / 252
    sharpe_t = sharpe * np.sqrt(n_years)

    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sharpe_t": sharpe_t,
        "mdd": mdd,
        "sortino": sortino,
        "calmar": calmar,
        "win_rate": win_rate,
        "n_days": len(r),
    }

# Full sample metrics
print("\n  === FULL SAMPLE METRICS ===")
print(f"  {'Strategy':<30s} {'AnnRet':>8s} {'AnnVol':>8s} {'Sharpe':>8s} {'Sharpe_t':>8s} {'MDD':>8s} {'Sortino':>8s} {'Calmar':>8s}")
print("  " + "-" * 100)

full_metrics = {}
for name, ret in strategies.items():
    m = compute_metrics(ret)
    full_metrics[name] = m
    print(f"  {name:<30s} {m['ann_ret']:>8.2%} {m['ann_vol']:>8.2%} {m['sharpe']:>8.3f} {m['sharpe_t']:>8.2f} {m['mdd']:>8.2%} {m['sortino']:>8.3f} {m['calmar']:>8.3f}")

# OOS metrics
print("\n  === OOS METRICS (2023-2024) ===")
print(f"  {'Strategy':<30s} {'AnnRet':>8s} {'AnnVol':>8s} {'Sharpe':>8s} {'Sharpe_t':>8s} {'MDD':>8s} {'Sortino':>8s} {'Calmar':>8s}")
print("  " + "-" * 100)

oos_mask_series = pd.Series(oos_mask, index=returns.index)

oos_metrics = {}
for name, ret in strategies.items():
    oos_m = oos_mask_series.reindex(ret.index, fill_value=False)
    m = compute_metrics(ret, oos_m)
    oos_metrics[name] = m
    print(f"  {name:<30s} {m['ann_ret']:>8.2%} {m['ann_vol']:>8.2%} {m['sharpe']:>8.3f} {m['sharpe_t']:>8.2f} {m['mdd']:>8.2%} {m['sortino']:>8.3f} {m['calmar']:>8.3f}")

# ============================================================
# 7. STATISTICAL TESTS
# ============================================================
print("\n[7/8] Statistical tests...")

# 7a. Diebold-Mariano test: Asset-Specific vs Uniform VIX
def dm_test(ret1, ret2, mask=None):
    """
    DM test comparing risk-adjusted returns.
    H0: E[d_t] = 0 where d_t = ret1_t - ret2_t
    H1: E[d_t] > 0 (ret1 is better)
    """
    if mask is not None:
        r1 = ret1[mask]
        r2 = ret2[mask]
    else:
        r1 = ret1
        r2 = ret2

    d = r1 - r2
    d = d.dropna()

    n = len(d)
    d_mean = d.mean()

    # Newey-West HAC with bandwidth = int(n^(1/3))
    bw = int(n ** (1/3))
    gamma_0 = np.var(d, ddof=1)

    hac_var = gamma_0
    for j in range(1, bw + 1):
        weight = 1 - j / (bw + 1)
        gamma_j = np.cov(d[j:], d[:-j])[0, 1]
        hac_var += 2 * weight * gamma_j

    hac_se = np.sqrt(hac_var / n)

    if hac_se > 0:
        t_stat = d_mean / hac_se
        p_value = 1 - stats.t.cdf(t_stat, df=n-1)
    else:
        t_stat = 0.0
        p_value = 0.5

    return {
        "d_mean_ann": d_mean * 252,
        "t_stat": t_stat,
        "p_value": p_value,
        "n": n,
    }

print("\n  === DM Tests (OOS: 2023-2024) ===")
print(f"  {'Comparison':<50s} {'d_mean_ann':>10s} {'t_stat':>8s} {'p_value':>8s} {'Sig':>5s}")
print("  " + "-" * 85)

oos_idx = returns.index[oos_mask]

comparisons = [
    ("AssetSpecific_4asset", "Uniform_VIX_4asset", "Asset-Specific vs Uniform VIX (4-asset)"),
    ("AssetSpecific_4asset", "BuyHold_4asset", "Asset-Specific vs Buy&Hold (4-asset)"),
    ("Uniform_VIX_4asset", "BuyHold_4asset", "Uniform VIX vs Buy&Hold (4-asset)"),
    ("AssetSpecific_5050", "Uniform_VIX_5050", "Asset-Specific vs Uniform VIX (50/50)"),
    ("AssetSpecific_5050", "BuyHold_5050", "Asset-Specific vs Buy&Hold (50/50)"),
    ("AssetSpecific_4asset", "Uniform_VIX_5050", "Asset-Specific 4-asset vs VIX 50/50"),
]

dm_results = {}
for s1, s2, label in comparisons:
    oos_r1 = strategies[s1].reindex(oos_idx).dropna()
    oos_r2 = strategies[s2].reindex(oos_idx).dropna()
    common = oos_r1.index.intersection(oos_r2.index)

    dm = dm_test(oos_r1.loc[common], oos_r2.loc[common])
    sig = "***" if dm["p_value"] < 0.01 else "**" if dm["p_value"] < 0.05 else "*" if dm["p_value"] < 0.10 else ""
    print(f"  {label:<50s} {dm['d_mean_ann']:>10.4f} {dm['t_stat']:>8.3f} {dm['p_value']:>8.4f} {sig:>5s}")
    dm_results[f"{s1}_vs_{s2}"] = dm

# 7b. Bootstrap Sharpe ratio comparison
print("\n  === Bootstrap Sharpe Comparison (OOS, 10000 reps) ===")

def bootstrap_sharpe_diff(ret1, ret2, n_boot=10000):
    """Bootstrap test for Sharpe ratio difference."""
    r1 = ret1.dropna().values
    r2 = ret2.dropna().values
    n = min(len(r1), len(r2))
    r1 = r1[:n]
    r2 = r2[:n]

    sharpe1 = r1.mean() / r1.std() * np.sqrt(252)
    sharpe2 = r2.mean() / r2.std() * np.sqrt(252)
    obs_diff = sharpe1 - sharpe2

    boot_diffs = np.zeros(n_boot)
    for b in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        b1 = r1[idx]
        b2 = r2[idx]
        s1 = b1.mean() / b1.std() * np.sqrt(252) if b1.std() > 0 else 0
        s2 = b2.mean() / b2.std() * np.sqrt(252) if b2.std() > 0 else 0
        boot_diffs[b] = s1 - s2

    p_value = (boot_diffs <= 0).mean()  # P(diff <= 0)
    ci_lo = np.percentile(boot_diffs, 2.5)
    ci_hi = np.percentile(boot_diffs, 97.5)

    return {
        "obs_diff": obs_diff,
        "p_value": p_value,
        "ci_95": (ci_lo, ci_hi),
        "boot_mean": boot_diffs.mean(),
        "boot_std": boot_diffs.std(),
    }

boot_comparisons = [
    ("AssetSpecific_4asset", "Uniform_VIX_4asset", "Asset-Specific vs Uniform VIX (4-asset)"),
    ("AssetSpecific_4asset", "BuyHold_4asset", "Asset-Specific vs Buy&Hold (4-asset)"),
    ("AssetSpecific_5050", "Uniform_VIX_5050", "Asset-Specific vs Uniform VIX (50/50)"),
]

print(f"  {'Comparison':<50s} {'SR_diff':>8s} {'p(diff<=0)':>10s} {'95% CI':>20s} {'Harvey':>8s}")
print("  " + "-" * 100)

boot_results = {}
for s1, s2, label in boot_comparisons:
    oos_r1 = strategies[s1].reindex(oos_idx).dropna()
    oos_r2 = strategies[s2].reindex(oos_idx).dropna()
    common = oos_r1.index.intersection(oos_r2.index)

    br = bootstrap_sharpe_diff(oos_r1.loc[common], oos_r2.loc[common])
    harvey = "PASS" if abs(br["obs_diff"]) / br["boot_std"] > 3.0 else "FAIL"
    print(f"  {label:<50s} {br['obs_diff']:>8.3f} {br['p_value']:>10.4f} [{br['ci_95'][0]:>8.3f}, {br['ci_95'][1]:>8.3f}] {harvey:>8s}")
    boot_results[f"{s1}_vs_{s2}"] = br

# ============================================================
# 7c. Per-asset VT weight analysis
# ============================================================
print("\n  === Per-Asset VT Weight Statistics (OOS) ===")
print(f"  {'Asset':<8s} {'VIX_mean':>10s} {'Specific_mean':>14s} {'VIX_std':>10s} {'Specific_std':>14s} {'Corr':>8s}")
print("  " + "-" * 70)

for asset in assets:
    vix_w = uniform_vix_weights.loc[oos_idx, asset].dropna()
    spec_w = asset_specific_weights.loc[oos_idx, asset].dropna()
    common = vix_w.index.intersection(spec_w.index)

    corr = vix_w.loc[common].corr(spec_w.loc[common])
    print(f"  {asset:<8s} {vix_w.mean():>10.3f} {spec_w.mean():>14.3f} {vix_w.std():>10.3f} {spec_w.std():>14.3f} {corr:>8.3f}")

# ============================================================
# 7d. Per-asset contribution analysis
# ============================================================
print("\n  === Per-Asset Contribution to Portfolio Return (OOS) ===")

for portfolio_name, port_w, vt_weights in [
    ("Uniform VIX", port_equal, uniform_vix_weights),
    ("Asset-Specific", port_equal, asset_specific_weights),
]:
    print(f"\n  {portfolio_name}:")
    print(f"  {'Asset':<8s} {'AnnRet':>10s} {'AnnVol':>10s} {'Sharpe':>8s} {'Avg_VT_w':>10s}")
    print("  " + "-" * 50)

    for asset in assets:
        if port_w.get(asset, 0) == 0:
            continue
        alloc = port_w[asset]
        vt_w = vt_weights.loc[oos_idx, asset].dropna()
        asset_ret = returns.loc[oos_idx, asset].dropna()
        common = vt_w.index.intersection(asset_ret.index)

        contrib = alloc * vt_w.loc[common] * asset_ret.loc[common]
        ann_ret = contrib.mean() * 252
        ann_vol = contrib.std() * np.sqrt(252)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

        print(f"  {asset:<8s} {ann_ret:>10.2%} {ann_vol:>10.2%} {sharpe:>8.3f} {vt_w.mean():>10.3f}")

# ============================================================
# 8. WALK-FORWARD VALIDATION
# ============================================================
print("\n[8/8] Walk-forward validation...")

# Split OOS into 4 quarters
oos_dates = returns.index[oos_mask]
n_oos = len(oos_dates)
quarter_size = n_oos // 4

print(f"\n  === Walk-Forward: Quarterly OOS Performance ===")
print(f"  {'Period':<20s} {'Uniform_VIX':>12s} {'Asset_Spec':>12s} {'Diff':>8s} {'Winner':>10s}")
print("  " + "-" * 65)

quarterly_wins = {"Uniform_VIX_4asset": 0, "AssetSpecific_4asset": 0}

for q in range(4):
    start_idx = q * quarter_size
    end_idx = (q + 1) * quarter_size if q < 3 else n_oos
    q_dates = oos_dates[start_idx:end_idx]

    q_mask = returns.index.isin(q_dates)

    r_unif = strategies["Uniform_VIX_4asset"].reindex(q_dates).dropna()
    r_spec = strategies["AssetSpecific_4asset"].reindex(q_dates).dropna()

    sr_unif = r_unif.mean() / r_unif.std() * np.sqrt(252) if r_unif.std() > 0 else 0
    sr_spec = r_spec.mean() / r_spec.std() * np.sqrt(252) if r_spec.std() > 0 else 0

    diff = sr_spec - sr_unif
    winner = "AssetSpec" if diff > 0 else "UnifVIX"

    if diff > 0:
        quarterly_wins["AssetSpecific_4asset"] += 1
    else:
        quarterly_wins["Uniform_VIX_4asset"] += 1

    period = f"{q_dates[0].strftime('%Y-%m')} ~ {q_dates[-1].strftime('%Y-%m')}"
    print(f"  {period:<20s} {sr_unif:>12.3f} {sr_spec:>12.3f} {diff:>8.3f} {winner:>10s}")

print(f"\n  Quarterly wins: Asset-Specific={quarterly_wins['AssetSpecific_4asset']}/4, Uniform VIX={quarterly_wins['Uniform_VIX_4asset']}/4")

# ============================================================
# 8b. Extended walk-forward: 2-year rolling windows
# ============================================================
print("\n  === Walk-Forward: Annual Rolling Sharpe (full sample) ===")
print(f"  {'Year':<8s} {'Uniform_VIX':>12s} {'Asset_Spec':>12s} {'BuyHold':>10s} {'Best':>12s}")
print("  " + "-" * 58)

annual_wins = {"Uniform": 0, "AssetSpec": 0, "BuyHold": 0}

for year in range(2016, 2025):
    year_mask = (returns.index >= f"{year}-01-01") & (returns.index <= f"{year}-12-31")
    year_dates = returns.index[year_mask]

    if len(year_dates) < 50:
        continue

    r_unif = strategies["Uniform_VIX_4asset"].reindex(year_dates).dropna()
    r_spec = strategies["AssetSpecific_4asset"].reindex(year_dates).dropna()
    r_bh = strategies["BuyHold_4asset"].reindex(year_dates).dropna()

    sr_unif = r_unif.mean() / r_unif.std() * np.sqrt(252) if r_unif.std() > 0 else 0
    sr_spec = r_spec.mean() / r_spec.std() * np.sqrt(252) if r_spec.std() > 0 else 0
    sr_bh = r_bh.mean() / r_bh.std() * np.sqrt(252) if r_bh.std() > 0 else 0

    best_sr = max(sr_unif, sr_spec, sr_bh)
    if best_sr == sr_unif:
        best = "Uniform"
    elif best_sr == sr_spec:
        best = "AssetSpec"
    else:
        best = "BuyHold"
    annual_wins[best] += 1

    print(f"  {year:<8d} {sr_unif:>12.3f} {sr_spec:>12.3f} {sr_bh:>10.3f} {best:>12s}")

print(f"\n  Annual wins: Uniform={annual_wins['Uniform']}, AssetSpec={annual_wins['AssetSpec']}, BuyHold={annual_wins['BuyHold']}")

# ============================================================
# 9. DIAGNOSTIC: VT weight paths
# ============================================================
print("\n  === VT Weight Path Diagnostics (OOS) ===")

for asset in assets:
    vix_w = uniform_vix_weights.loc[oos_idx, asset].dropna()
    spec_w = asset_specific_weights.loc[oos_idx, asset].dropna()

    # Weight path volatility
    vix_turnover = vix_w.diff().abs().mean() * 252
    spec_turnover = spec_w.diff().abs().mean() * 252

    print(f"  {asset}: VIX_turnover={vix_turnover:.3f}/yr, Specific_turnover={spec_turnover:.3f}/yr, "
          f"VIX_range=[{vix_w.min():.2f}, {vix_w.max():.2f}], Spec_range=[{spec_w.min():.2f}, {spec_w.max():.2f}]")

# ============================================================
# 10. ADDITIONAL: Correlation of VT weights with realized vol
# ============================================================
print("\n  === VT Weight vs Next-22d Realized Vol Correlation (Full Sample) ===")

# Forward-looking 22d RV
fwd_rv = {}
for asset in assets:
    fwd_rv[asset] = returns[asset].rolling(22).std().shift(-22) * np.sqrt(252) * 100
fwd_rv_df = pd.DataFrame(fwd_rv)

print(f"  {'Asset':<8s} {'corr(VIX_w, fwd_RV)':>20s} {'corr(Spec_w, fwd_RV)':>22s} {'Better':>8s}")
print("  " + "-" * 62)

for asset in assets:
    vix_w = uniform_vix_weights[asset].dropna()
    spec_w = asset_specific_weights[asset].dropna()
    fwd = fwd_rv_df[asset].dropna()

    common_v = vix_w.index.intersection(fwd.index)
    common_s = spec_w.index.intersection(fwd.index)

    corr_vix = vix_w.loc[common_v].corr(fwd.loc[common_v])
    corr_spec = spec_w.loc[common_s].corr(fwd.loc[common_s])

    better = "Specific" if abs(corr_spec) > abs(corr_vix) else "VIX"
    print(f"  {asset:<8s} {corr_vix:>20.4f} {corr_spec:>22.4f} {better:>8s}")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K206 Asset-Specific VT Design Framework")
print("=" * 70)

print(f"""
Key findings:

1. OOS Performance (2023-2024):
   - Uniform VIX (4-asset):   Sharpe = {oos_metrics['Uniform_VIX_4asset']['sharpe']:.3f}, MDD = {oos_metrics['Uniform_VIX_4asset']['mdd']:.2%}
   - Asset-Specific (4-asset): Sharpe = {oos_metrics['AssetSpecific_4asset']['sharpe']:.3f}, MDD = {oos_metrics['AssetSpecific_4asset']['mdd']:.2%}
   - Buy&Hold (4-asset):       Sharpe = {oos_metrics['BuyHold_4asset']['sharpe']:.3f}, MDD = {oos_metrics['BuyHold_4asset']['mdd']:.2%}
   - 50/50 VIX:                Sharpe = {oos_metrics['Uniform_VIX_5050']['sharpe']:.3f}, MDD = {oos_metrics['Uniform_VIX_5050']['mdd']:.2%}

2. DM test: Asset-Specific vs Uniform VIX (4-asset):
   t = {dm_results['AssetSpecific_4asset_vs_Uniform_VIX_4asset']['t_stat']:.3f}, p = {dm_results['AssetSpecific_4asset_vs_Uniform_VIX_4asset']['p_value']:.4f}

3. Bootstrap Sharpe diff: Asset-Specific vs Uniform VIX:
   diff = {boot_results['AssetSpecific_4asset_vs_Uniform_VIX_4asset']['obs_diff']:.3f}, p(diff<=0) = {boot_results['AssetSpecific_4asset_vs_Uniform_VIX_4asset']['p_value']:.4f}

4. Walk-forward quarterly wins (OOS): Asset-Specific = {quarterly_wins['AssetSpecific_4asset']}/4
   Walk-forward annual wins (full): Uniform={annual_wins['Uniform']}, AssetSpec={annual_wins['AssetSpec']}, BuyHold={annual_wins['BuyHold']}
""")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    "experiment": "K206",
    "title": "Asset-Specific VT Design Framework",
    "timestamp": datetime.now().isoformat(),
    "data": {
        "assets": assets,
        "is_period": f"{returns.index[is_mask][0].date()} ~ {returns.index[is_mask][-1].date()}",
        "oos_period": f"{returns.index[oos_mask][0].date()} ~ {returns.index[oos_mask][-1].date()}",
        "n_is": int(is_mask.sum()),
        "n_oos": int(oos_mask.sum()),
    },
    "full_sample_metrics": {k: {kk: float(vv) if isinstance(vv, (np.floating, float)) else int(vv)
                                  for kk, vv in v.items()}
                             for k, v in full_metrics.items()},
    "oos_metrics": {k: {kk: float(vv) if isinstance(vv, (np.floating, float)) else int(vv)
                          for kk, vv in v.items()}
                     for k, v in oos_metrics.items()},
    "dm_tests": {k: {kk: float(vv) if isinstance(vv, (np.floating, float)) else int(vv)
                       for kk, vv in v.items()}
                  for k, v in dm_results.items()},
    "bootstrap_sharpe": {k: {
        "obs_diff": float(v["obs_diff"]),
        "p_value": float(v["p_value"]),
        "ci_95_lo": float(v["ci_95"][0]),
        "ci_95_hi": float(v["ci_95"][1]),
    } for k, v in boot_results.items()},
    "quarterly_wins": quarterly_wins,
    "annual_wins": annual_wins,
}

output_path = EXPERIMENT_DIR / "k206_asset_specific_vt_results.json"
with output_path.open("w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)
print(f"\nResults saved to {output_path}")
print("Done.")
