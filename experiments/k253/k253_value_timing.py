"""
K253: Value Timing — Can Shiller CAPE / PE Ratio Improve Allocation?
=====================================================================
[提出: 用戶, 執行: Claude]

Background:
  Value investing suggests buying cheap (low PE) and selling expensive (high PE).
  The Shiller CAPE is the most-cited valuation metric. Since CAPE is not trivially
  available from yfinance, we use SPY price relative to its 10-year (2520 trading day)
  moving average as a valuation proxy — this captures the same "reversion to trend"
  logic that underpins Shiller's framework.

Methodology:
  1. Valuation signal: SPY price / 10-year MA (monthly, rebalanced month-end)
       > 1.2  → overvalued  (reduce SPY)
       0.8–1.2 → fair value  (standard allocation)
       < 0.8  → undervalued (increase SPY)
  2. Strategy variants on a 50/50 SPY/GLD base:
       a. Value Tilt:       60/40 cheap, 40/60 expensive
       b. Aggressive Value: 70/30 cheap, 30/70 expensive
       c. Value + VT (12/VIX): apply VT only when overvalued, full invest when cheap
  3. Benchmarks: 50/50 B&H, 50/50+VT (12/VIX), SPY B&H
  4. 5-period cross-OOS validation
  5. DM test, bootstrap Sharpe difference

Data:
  SPY, GLD, ^VIX daily from yfinance (real data only).
  10-year MA requires ~2520 trading days lookback → data from 1993+.
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
import json

# ==================================================================
# CONFIG
# ==================================================================
RF_ANNUAL = 0.04
RF_DAILY = RF_ANNUAL / 252
MA_WINDOW = 2520           # ~10 years of trading days
OVERVALUED_THRESHOLD = 1.2
UNDERVALUED_THRESHOLD = 0.8
VIX_VT_THRESHOLD = 12.0   # 12/VIX rule

# 5-period cross-OOS
OOS_PERIODS = [
    ("2007-2009 (GFC)",       "2007-01-02", "2009-12-31"),
    ("2010-2013 (Recovery)",  "2010-01-04", "2013-12-31"),
    ("2014-2017 (Bull)",      "2014-01-02", "2017-12-31"),
    ("2018-2021 (Vol+COVID)", "2018-01-02", "2021-12-31"),
    ("2022-2026 (Rate hike)", "2022-01-03", "2026-12-31"),
]

# Need 10-year lookback before first OOS
DATA_START = "1993-01-01"

print("=" * 80)
print("K253: VALUE TIMING — SHILLER CAPE PROXY (SPY/10yr MA)")
print("=" * 80)
print(f"  Valuation signal: SPY / {MA_WINDOW}d MA")
print(f"  Overvalued: > {OVERVALUED_THRESHOLD}, Undervalued: < {UNDERVALUED_THRESHOLD}")
print(f"  VT threshold: 12/VIX")
print(f"  Risk-free: {RF_ANNUAL:.0%}")
print(f"  Cross-OOS periods: {len(OOS_PERIODS)}")

# ==================================================================
# 1. Download Data
# ==================================================================
print("\n[1/6] Downloading SPY, GLD, VIX data from yfinance...")

spy_raw = yf.download("SPY", start=DATA_START, end="2026-12-31", progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start=DATA_START, end="2026-12-31", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start=DATA_START, end="2026-12-31", progress=False, auto_adjust=False)

# Flatten MultiIndex if needed
for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

# Merge — GLD starts 2004-11, so the joint set is shorter
data = spy.join(gld, how="inner").join(vix, how="inner").dropna()
data["spy_ret"] = data["spy_close"].pct_change()
data["gld_ret"] = data["gld_close"].pct_change()
data = data.dropna()

print(f"  SPY range: {spy.index[0].date()} to {spy.index[-1].date()} ({len(spy)} days)")
print(f"  GLD range: {gld.index[0].date()} to {gld.index[-1].date()} ({len(gld)} days)")
print(f"  Joint range: {data.index[0].date()} to {data.index[-1].date()} ({len(data)} days)")

# ==================================================================
# 2. Compute Valuation Signal
# ==================================================================
print(f"\n[2/6] Computing valuation signal (SPY / {MA_WINDOW}d MA)...")

# Compute on full SPY history for longest lookback
spy_full = spy_raw.copy()
if isinstance(spy_full.columns, pd.MultiIndex):
    spy_full.columns = spy_full.columns.get_level_values(0)
spy_full = spy_full[["Close"]].rename(columns={"Close": "spy_close"}).dropna()

spy_full["ma_10yr"] = spy_full["spy_close"].rolling(window=MA_WINDOW, min_periods=MA_WINDOW).mean()
spy_full["val_ratio"] = spy_full["spy_close"] / spy_full["ma_10yr"]
spy_full = spy_full.dropna(subset=["val_ratio"])

print(f"  Valuation signal available from: {spy_full.index[0].date()}")
print(f"  Current val_ratio: {spy_full['val_ratio'].iloc[-1]:.3f}")

# Merge valuation signal into joint data
data = data.join(spy_full[["val_ratio"]], how="left")
data["val_ratio"] = data["val_ratio"].ffill()
data = data.dropna(subset=["val_ratio"])

# Classify regimes
data["val_regime"] = "fair"
data.loc[data["val_ratio"] > OVERVALUED_THRESHOLD, "val_regime"] = "overvalued"
data.loc[data["val_ratio"] < UNDERVALUED_THRESHOLD, "val_regime"] = "undervalued"

regime_counts = data["val_regime"].value_counts()
print(f"\n  Regime distribution:")
for regime, count in regime_counts.items():
    pct = count / len(data) * 100
    print(f"    {regime:>12s}: {count:>5d} days ({pct:.1f}%)")

# Monthly valuation signal (use end-of-month value, applied to next month)
data["yearmonth"] = data.index.to_period("M")
monthly_val = data.groupby("yearmonth")["val_ratio"].last()
# Shift: signal from month M applied to month M+1
monthly_val_shifted = monthly_val.shift(1)
monthly_val_map = monthly_val_shifted.to_dict()

# Map monthly signal back to daily
data["val_ratio_signal"] = data["yearmonth"].map(monthly_val_map)
data = data.dropna(subset=["val_ratio_signal"])

data["val_regime_signal"] = "fair"
data.loc[data["val_ratio_signal"] > OVERVALUED_THRESHOLD, "val_regime_signal"] = "overvalued"
data.loc[data["val_ratio_signal"] < UNDERVALUED_THRESHOLD, "val_regime_signal"] = "undervalued"

signal_regime_counts = data["val_regime_signal"].value_counts()
print(f"\n  Signal regime distribution (lagged 1 month):")
for regime, count in signal_regime_counts.items():
    pct = count / len(data) * 100
    print(f"    {regime:>12s}: {count:>5d} days ({pct:.1f}%)")

# ==================================================================
# 3. Strategy Definitions
# ==================================================================
print("\n[3/6] Computing strategy returns...")

def compute_monthly_rebal_returns(data, spy_weight_func, name):
    """Compute daily returns with monthly rebalancing based on valuation signal."""
    daily_rets = []
    for ym in data["yearmonth"].unique():
        mask = data["yearmonth"] == ym
        period_data = data[mask]
        if len(period_data) == 0:
            continue

        # Get the lagged valuation signal for this month
        val_sig = period_data["val_ratio_signal"].iloc[0]
        if pd.isna(val_sig):
            continue

        # Determine weights
        spy_w = spy_weight_func(val_sig, period_data)
        gld_w = 1.0 - spy_w

        # Daily portfolio return (rebalanced at month start)
        port_ret = spy_w * period_data["spy_ret"] + gld_w * period_data["gld_ret"]
        daily_rets.append(port_ret)

    if not daily_rets:
        return pd.Series(dtype=float)
    return pd.concat(daily_rets)

# Strategy A: Value Tilt (60/40 cheap, 40/60 expensive)
def value_tilt_weight(val_ratio, period_data):
    if val_ratio < UNDERVALUED_THRESHOLD:
        return 0.60
    elif val_ratio > OVERVALUED_THRESHOLD:
        return 0.40
    else:
        return 0.50

# Strategy B: Aggressive Value (70/30 cheap, 30/70 expensive)
def aggressive_value_weight(val_ratio, period_data):
    if val_ratio < UNDERVALUED_THRESHOLD:
        return 0.70
    elif val_ratio > OVERVALUED_THRESHOLD:
        return 0.30
    else:
        return 0.50

# Strategy C: Value + VT (apply VT only when overvalued)
def value_vt_weight(val_ratio, period_data):
    """When cheap: full 50/50. When expensive: apply 12/VIX scaling."""
    base_spy = 0.50
    if val_ratio < UNDERVALUED_THRESHOLD:
        # Cheap: stay fully invested 50/50
        return base_spy
    elif val_ratio > OVERVALUED_THRESHOLD:
        # Expensive: apply VT (12/VIX) to reduce exposure
        vix_avg = period_data["vix_close"].mean()
        vt_scale = min(VIX_VT_THRESHOLD / vix_avg, 1.0)
        return base_spy * vt_scale
    else:
        # Fair: standard 50/50
        return base_spy

# Benchmark 1: 50/50 B&H (monthly rebalance to 50/50)
def bh_5050_weight(val_ratio, period_data):
    return 0.50

# Benchmark 2: 50/50 + VT (12/VIX always applied)
def vt_5050_weight(val_ratio, period_data):
    vix_avg = period_data["vix_close"].mean()
    vt_scale = min(VIX_VT_THRESHOLD / vix_avg, 1.0)
    return 0.50 * vt_scale

# Benchmark 3: SPY B&H
def spy_bh_weight(val_ratio, period_data):
    return 1.0

strategies = {
    "50/50 B&H":         bh_5050_weight,
    "50/50+VT(12/VIX)":  vt_5050_weight,
    "SPY B&H":           spy_bh_weight,
    "Value Tilt":        value_tilt_weight,
    "Aggressive Value":  aggressive_value_weight,
    "Value+VT":          value_vt_weight,
}

# Compute all strategy returns
strat_returns = {}
for name, weight_fn in strategies.items():
    rets = compute_monthly_rebal_returns(data, weight_fn, name)
    strat_returns[name] = rets
    print(f"  {name:>20s}: {len(rets)} days computed")

# ==================================================================
# 4. Full-Sample Analysis
# ==================================================================
print("\n[4/6] Full-sample performance...")

def compute_metrics(returns, rf_daily=RF_DAILY):
    """Compute standard performance metrics."""
    if len(returns) < 30:
        return {}
    excess = returns - rf_daily
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = excess.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0

    # MDD
    cum = (1 + returns).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    mdd = dd.min()

    # Calmar
    calmar = ann_ret / abs(mdd) if mdd != 0 else 0

    # Sortino
    downside = returns[returns < 0]
    downside_std = downside.std() * np.sqrt(252) if len(downside) > 0 else 1e-10
    sortino = (ann_ret - RF_ANNUAL) / downside_std

    # Sharpe t-stat
    n_years = len(returns) / 252
    sharpe_se = 1.0 / np.sqrt(n_years)
    sharpe_t = sharpe / sharpe_se if sharpe_se > 0 else 0

    return {
        "ann_ret": ann_ret,
        "ann_vol": ann_vol,
        "sharpe": sharpe,
        "sharpe_t": sharpe_t,
        "mdd": mdd,
        "calmar": calmar,
        "sortino": sortino,
        "n_days": len(returns),
        "n_years": n_years,
    }

print(f"\n{'Strategy':<22s} {'AnnRet':>8s} {'AnnVol':>8s} {'Sharpe':>8s} {'t-stat':>8s} {'MDD':>8s} {'Calmar':>8s} {'Sortino':>8s} {'N_days':>8s}")
print("-" * 98)

full_metrics = {}
for name in strategies:
    m = compute_metrics(strat_returns[name])
    full_metrics[name] = m
    if m:
        print(f"{name:<22s} {m['ann_ret']:>8.3f} {m['ann_vol']:>8.3f} {m['sharpe']:>8.3f} {m['sharpe_t']:>8.2f} {m['mdd']:>8.3f} {m['calmar']:>8.3f} {m['sortino']:>8.3f} {m['n_days']:>8d}")

# ==================================================================
# 5. Cross-OOS Validation (5 periods)
# ==================================================================
print("\n[5/6] Cross-OOS validation (5 periods)...")

oos_results = {}

for period_name, start, end in OOS_PERIODS:
    print(f"\n  --- {period_name} ({start} to {end}) ---")

    period_metrics = {}
    for name in strategies:
        rets = strat_returns[name]
        mask = (rets.index >= start) & (rets.index <= end)
        period_rets = rets[mask]

        m = compute_metrics(period_rets)
        period_metrics[name] = m

    oos_results[period_name] = period_metrics

    # Print period results
    print(f"  {'Strategy':<22s} {'Sharpe':>8s} {'MDD':>8s} {'AnnRet':>8s} {'N_days':>8s}")
    print(f"  {'-'*54}")
    for name in strategies:
        m = period_metrics[name]
        if m:
            print(f"  {name:<22s} {m['sharpe']:>8.3f} {m['mdd']:>8.3f} {m['ann_ret']:>8.3f} {m['n_days']:>8d}")

# ==================================================================
# 5b. Sharpe Difference Tests
# ==================================================================
print("\n  --- Sharpe Difference: Value strategies vs 50/50 B&H ---")

def dm_test_returns(rets1, rets2, rf_daily=RF_DAILY):
    """
    Diebold-Mariano style test on daily excess returns.
    H0: E[r1 - r2] = 0
    """
    common_idx = rets1.index.intersection(rets2.index)
    r1 = rets1.loc[common_idx]
    r2 = rets2.loc[common_idx]
    diff = r1 - r2

    if len(diff) < 30 or diff.std() == 0:
        return 0, 1.0

    t_stat = diff.mean() / (diff.std() / np.sqrt(len(diff)))
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=len(diff)-1))
    return t_stat, p_value

def bootstrap_sharpe_diff(rets1, rets2, n_boot=10000, rf_daily=RF_DAILY):
    """Bootstrap test for Sharpe difference."""
    common_idx = rets1.index.intersection(rets2.index)
    r1 = rets1.loc[common_idx].values
    r2 = rets2.loc[common_idx].values

    n = len(r1)
    if n < 30:
        return 0, 1.0

    def sharpe(r):
        excess = r - rf_daily
        return excess.mean() / r.std() * np.sqrt(252) if r.std() > 0 else 0

    obs_diff = sharpe(r1) - sharpe(r2)

    boot_diffs = np.zeros(n_boot)
    for i in range(n_boot):
        idx = np.random.randint(0, n, size=n)
        boot_diffs[i] = sharpe(r1[idx]) - sharpe(r2[idx])

    p_value = np.mean(boot_diffs <= 0) if obs_diff > 0 else np.mean(boot_diffs >= 0)

    return obs_diff, p_value

benchmark_name = "50/50 B&H"
test_strategies = ["Value Tilt", "Aggressive Value", "Value+VT", "50/50+VT(12/VIX)"]

print(f"\n  {'Strategy':<22s} {'dSharpe':>8s} {'DM_t':>8s} {'DM_p':>8s} {'Boot_p':>8s} {'Signif':>8s}")
print(f"  {'-'*62}")

for name in test_strategies:
    common_idx = strat_returns[name].index.intersection(strat_returns[benchmark_name].index)
    r1 = strat_returns[name].loc[common_idx]
    r2 = strat_returns[benchmark_name].loc[common_idx]

    dm_t, dm_p = dm_test_returns(r1, r2)

    s1 = full_metrics[name].get("sharpe", 0)
    s2 = full_metrics[benchmark_name].get("sharpe", 0)
    d_sharpe = s1 - s2

    boot_diff, boot_p = bootstrap_sharpe_diff(r1, r2)

    signif = "YES" if dm_p < 0.05 else "no"
    print(f"  {name:<22s} {d_sharpe:>+8.3f} {dm_t:>8.3f} {dm_p:>8.4f} {boot_p:>8.4f} {signif:>8s}")

# ==================================================================
# 5c. Cross-OOS Win Count
# ==================================================================
print("\n  --- Cross-OOS Win Count (Sharpe vs 50/50 B&H) ---")

win_counts = {name: 0 for name in test_strategies}
period_details = []

for period_name, start, end in OOS_PERIODS:
    bh_sharpe = oos_results[period_name].get(benchmark_name, {}).get("sharpe", 0)

    for name in test_strategies:
        strat_sharpe = oos_results[period_name].get(name, {}).get("sharpe", 0)
        if strat_sharpe > bh_sharpe:
            win_counts[name] += 1

print(f"\n  {'Strategy':<22s} {'Wins':>6s} {'/ 5':>4s} {'Pass?':>8s}")
print(f"  {'-'*44}")
for name in test_strategies:
    wins = win_counts[name]
    passed = "PASS" if wins >= 4 else "FAIL"
    print(f"  {name:<22s} {wins:>6d}  / 5 {passed:>8s}")

# ==================================================================
# 6. Signal Characteristics Analysis
# ==================================================================
print("\n[6/6] Signal characteristics analysis...")

# How often does the signal change?
data["val_regime_change"] = (data["val_regime_signal"] != data["val_regime_signal"].shift(1)).astype(int)
regime_changes = data["val_regime_change"].sum()
n_years_total = len(data) / 252
changes_per_year = regime_changes / n_years_total

print(f"\n  Signal characteristics:")
print(f"    Total regime changes: {regime_changes}")
print(f"    Changes per year: {changes_per_year:.2f}")
print(f"    Average regime duration: {n_years_total / max(regime_changes, 1) * 12:.1f} months")

# Time in each regime by year
print(f"\n  Regime distribution by period:")
for period_name, start, end in OOS_PERIODS:
    mask = (data.index >= start) & (data.index <= end)
    period = data[mask]
    if len(period) == 0:
        continue

    regimes = period["val_regime_signal"].value_counts(normalize=True)
    regime_str = ", ".join([f"{r}: {v:.0%}" for r, v in regimes.items()])
    print(f"    {period_name}: {regime_str}")

# Current valuation
latest_val = data["val_ratio"].iloc[-1]
latest_regime = data["val_regime"].iloc[-1]
print(f"\n  Current valuation:")
print(f"    SPY/10yr MA ratio: {latest_val:.3f}")
print(f"    Regime: {latest_regime}")
print(f"    Interpretation: {'SPY is {:.0f}% above its 10-year average'.format((latest_val - 1) * 100)}")

# Valuation ratio over time
print(f"\n  Valuation ratio time series (selected dates):")
for year in [2007, 2009, 2013, 2017, 2020, 2022, 2024, 2026]:
    year_data = data[data.index.year == year]
    if len(year_data) > 0:
        mid_idx = len(year_data) // 2
        val = year_data["val_ratio"].iloc[mid_idx]
        regime = year_data["val_regime"].iloc[mid_idx]
        print(f"    {year}: val_ratio = {val:.3f} ({regime})")

# ==================================================================
# 7. Save Results
# ==================================================================
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)

print(f"""
Key Findings:
  1. Signal: SPY / 10-year MA ratio
     - Currently: {latest_val:.3f} ({latest_regime})
     - Changes per year: {changes_per_year:.2f} (VERY slow signal)
     - Mostly in 'fair' or 'overvalued' regime since GLD inception (2004)

  2. Full-sample performance:""")

for name in strategies:
    m = full_metrics[name]
    if m:
        print(f"     {name:<22s}: Sharpe={m['sharpe']:.3f}, MDD={m['mdd']:.3f}")

print(f"""
  3. Cross-OOS wins vs 50/50 B&H:""")
for name in test_strategies:
    print(f"     {name:<22s}: {win_counts[name]}/5")

# Determine overall conclusion
any_significant = False
for name in test_strategies:
    common_idx = strat_returns[name].index.intersection(strat_returns[benchmark_name].index)
    r1 = strat_returns[name].loc[common_idx]
    r2 = strat_returns[benchmark_name].loc[common_idx]
    _, dm_p = dm_test_returns(r1, r2)
    if dm_p < 0.05 and win_counts[name] >= 4:
        any_significant = True
        break

if any_significant:
    conclusion = "POSITIVE — Value timing shows statistically significant improvement"
else:
    conclusion = "NULL RESULT — Value timing does NOT significantly improve allocation"

print(f"""
  4. Conclusion: {conclusion}

  Limitations:
  - GLD only available from 2004, so joint analysis = ~20 years
  - 10-year MA proxy is NOT the actual Shiller CAPE
  - Signal changes VERY slowly → few regime transitions to evaluate
  - Undervalued regime is rare in modern era (post-2009 mostly overvalued)
  - No transaction costs applied (but turnover is minimal)
""")

# Save JSON results
results = {
    "experiment": "K253",
    "title": "Value Timing — Shiller CAPE Proxy",
    "date": datetime.now().isoformat(),
    "methodology": {
        "signal": "SPY / 10-year MA",
        "overvalued_threshold": OVERVALUED_THRESHOLD,
        "undervalued_threshold": UNDERVALUED_THRESHOLD,
        "rebalance": "monthly",
        "base_allocation": "50/50 SPY/GLD",
        "vt_threshold": VIX_VT_THRESHOLD,
        "rf_annual": RF_ANNUAL,
    },
    "full_sample": {
        name: {k: round(v, 6) if isinstance(v, float) else v for k, v in m.items()}
        for name, m in full_metrics.items() if m
    },
    "cross_oos": {
        period: {
            name: {k: round(v, 6) if isinstance(v, float) else v for k, v in m.items()}
            for name, m in metrics.items() if m
        }
        for period, metrics in oos_results.items()
    },
    "win_counts_vs_bh": {name: win_counts[name] for name in test_strategies},
    "signal_characteristics": {
        "regime_changes_total": int(regime_changes),
        "changes_per_year": round(changes_per_year, 2),
        "current_val_ratio": round(latest_val, 3),
        "current_regime": latest_regime,
    },
    "conclusion": conclusion,
}

results_path = "experiments/k253_value_timing_results.json"
with open(results_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"Results saved to {results_path}")
