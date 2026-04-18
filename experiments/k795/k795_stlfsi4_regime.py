"""
K795: FRED STLFSI4 Macro Stress Regime for VT Strategy
=======================================================
Background:
  K504 tested STLFSI4 as vol predictor (NULL result, t=-0.43).
  K795 differs: expands on K504 by using expanding 75th percentile threshold
  (rolling/adaptive) vs. K504's fixed thresholds (0 and 1). Also tests
  binary regime switch and smooth target reduction.

Strategy designs:
  1. Baseline: 12/VIX (SPY only, rest cash)  [same as K504]
  2. STLFSI4-Adjusted: When STLFSI4 > expanding 75th pct → use 8/VIX else 12/VIX
  3. STLFSI4-Binary:   When STLFSI4 > 0 (above-average stress) → fixed 50/50 SPY/GLD
                       else 12/VIX SPY
  4. STLFSI4-Smooth:   target_vol = clip(12 - 4 * max(0, STLFSI4), 4, 12) → smooth reduction

Key methodological change vs K504:
  - Expanding 75th percentile threshold avoids lookahead (vs fixed >1 threshold in K504)
  - signal.shift(1) for proper lag
  - GLD as safe-haven asset in regimes
  - DM test with Harvey t>3.0

References:
  - Kliesen, Owyang, Vermann (2012) "Disentangling Diverse Measures" Fed StL Review
  - Moreira & Muir (2017) "Volatility-Managed Portfolios" JF
  - Harvey, Liu, Zhu (2016) "...and the Cross-Section of Expected Returns" RFS

Author: [提出: Gemini, 執行: Claude]
Data: yfinance (SPY, GLD, ^VIX) + FRED (STLFSI4)
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
import json
import io
import time
import urllib.request
from datetime import datetime
from scipy import stats

print("=" * 80)
print("K795: FRED STLFSI4 Macro Stress Regime for VT Strategy")
print("=" * 80)
t0 = time.time()

# ============================================================
# 1. Download data
# ============================================================
print("\n[1/6] Downloading data...")

spy_raw = yf.download("SPY", start="1999-01-01", end="2026-01-01", progress=False, auto_adjust=False)
gld_raw = yf.download("GLD", start="2004-01-01", end="2026-01-01", progress=False, auto_adjust=False)
vix_raw = yf.download("^VIX", start="1999-01-01", end="2026-01-01", progress=False, auto_adjust=False)

for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

spy = spy_raw[["Close"]].rename(columns={"Close": "spy_close"})
gld = gld_raw[["Close"]].rename(columns={"Close": "gld_close"})
vix = vix_raw[["Close"]].rename(columns={"Close": "vix_close"})

# FRED STLFSI4 — use local cache first, fallback to FRED API
print("  Fetching STLFSI4...")
import os
local_cache = os.path.join(os.path.dirname(__file__), "..", "storage", "macro", "fred_STLFSI4.csv")
local_cache = os.path.abspath(local_cache)

if os.path.exists(local_cache):
    print(f"  Using local cache: {local_cache}")
    stlfsi_raw = pd.read_csv(local_cache)
    date_col = [c for c in stlfsi_raw.columns if "date" in c.lower()][0]
    stlfsi_raw[date_col] = pd.to_datetime(stlfsi_raw[date_col])
    stlfsi_raw = stlfsi_raw.set_index(date_col)
    stlfsi_raw.columns = ["stlfsi4"]
    stlfsi_raw["stlfsi4"] = pd.to_numeric(stlfsi_raw["stlfsi4"], errors="coerce")
    stlfsi_raw = stlfsi_raw.dropna()
else:
    print(f"  No local cache, trying FRED API...")
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=STLFSI4"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=60)
        csv_data = resp.read().decode("utf-8")
        stlfsi_raw = pd.read_csv(io.StringIO(csv_data))
        date_col = [c for c in stlfsi_raw.columns if "date" in c.lower()][0]
        stlfsi_raw[date_col] = pd.to_datetime(stlfsi_raw[date_col])
        stlfsi_raw = stlfsi_raw.set_index(date_col)
        stlfsi_raw.columns = ["stlfsi4"]
        stlfsi_raw["stlfsi4"] = pd.to_numeric(stlfsi_raw["stlfsi4"], errors="coerce")
        stlfsi_raw = stlfsi_raw.dropna()
        # Save to local cache
        os.makedirs(os.path.dirname(local_cache), exist_ok=True)
        stlfsi_raw.to_csv(local_cache)
        print(f"  Saved to cache: {local_cache}")
    except Exception as e:
        print(f"  STLFSI4 download failed: {e}")
        raise

print(f"  STLFSI4: {stlfsi_raw.index[0].date()} to {stlfsi_raw.index[-1].date()}, n={len(stlfsi_raw)}")
print(f"  STLFSI4 range: {stlfsi_raw['stlfsi4'].min():.3f} to {stlfsi_raw['stlfsi4'].max():.3f}")

# ============================================================
# 2. Prepare data
# ============================================================
print("\n[2/6] Merging and preparing data...")

# Forward-fill STLFSI4 weekly → daily
stlfsi_daily = stlfsi_raw.resample("D").last().ffill()

data = spy.join(vix, how="inner").join(gld, how="left").join(stlfsi_daily, how="left")
data["stlfsi4"] = data["stlfsi4"].ffill()
data = data.dropna(subset=["spy_close", "vix_close", "stlfsi4"])

# Returns
data["spy_ret"] = np.log(data["spy_close"] / data["spy_close"].shift(1))
data["gld_ret"] = np.log(data["gld_close"] / data["gld_close"].shift(1))
data["gld_ret"] = data["gld_ret"].fillna(0)
data["gld_close"] = data["gld_close"].ffill().bfill()
data = data.dropna(subset=["spy_ret"])

print(f"  Data range: {data.index[0].date()} to {data.index[-1].date()}")
print(f"  Total trading days: {len(data)}")
print(f"  VIX range: {data['vix_close'].min():.1f} - {data['vix_close'].max():.1f}")
print(f"  STLFSI4 range: {data['stlfsi4'].min():.3f} - {data['stlfsi4'].max():.3f}")

# ============================================================
# 3. Build STLFSI4 regime signals
# ============================================================
print("\n[3/6] Building regime signals...")

# Compute expanding 75th percentile of STLFSI4 (no lookahead)
# Use expanding window with min_periods=52 (at least 1 year of weekly data ~ 260 daily obs)
expanding_p75 = data["stlfsi4"].expanding(min_periods=260).quantile(0.75)

# --- Signal construction (all signals lag=1, applied to next-day returns) ---

# 1. Baseline: 12/VIX, cap at 1.5
spy_w_base = (12.0 / data["vix_close"]).clip(0, 1.5)
# Proper lag: signal from t-1, return at t
spy_w_base = spy_w_base.shift(1)

# 2. STLFSI4-Adjusted: expanding 75th pct threshold
in_stress_75 = (data["stlfsi4"] > expanding_p75).astype(float)
target_adjusted = np.where(in_stress_75 > 0, 8.0, 12.0)
spy_w_adj = pd.Series(target_adjusted / data["vix_close"].values,
                      index=data.index).clip(0, 1.5)
spy_w_adj = spy_w_adj.shift(1)  # lag

# 3. STLFSI4-Binary: STLFSI4 > 0 → 50/50 SPY/GLD; else 12/VIX
in_stress_binary = (data["stlfsi4"] > 0).astype(float)
# binary regime:
# normal: SPY weight = 12/VIX, GLD = 0
# stress: SPY weight = 0.5, GLD = 0.5
spy_w_bin_raw = np.where(in_stress_binary > 0, 0.5, (12.0 / data["vix_close"].values).clip(0, 1.5))
gld_w_bin_raw = np.where(in_stress_binary > 0, 0.5, 0.0)
spy_w_bin = pd.Series(spy_w_bin_raw, index=data.index).shift(1)
gld_w_bin = pd.Series(gld_w_bin_raw, index=data.index).shift(1)

# 4. STLFSI4-Smooth: target_vol = clip(12 - 4 * max(0, STLFSI4), 4, 12)
target_smooth = np.clip(12.0 - 4.0 * np.maximum(0.0, data["stlfsi4"].values), 4.0, 12.0)
spy_w_smo = pd.Series(target_smooth / data["vix_close"].values, index=data.index).clip(0, 1.5)
spy_w_smo = spy_w_smo.shift(1)  # lag

# Drop NaN rows from lag
data = data.dropna(subset=["spy_ret"])
spy_w_base = spy_w_base.reindex(data.index)
spy_w_adj  = spy_w_adj.reindex(data.index)
spy_w_bin  = spy_w_bin.reindex(data.index)
gld_w_bin  = gld_w_bin.reindex(data.index)
spy_w_smo  = spy_w_smo.reindex(data.index)

# Drop rows where signals are NaN (early expanding window)
valid_mask = (spy_w_base.notna() & spy_w_adj.notna() & spy_w_bin.notna() &
              gld_w_bin.notna() & spy_w_smo.notna())
data    = data[valid_mask]
spy_w_base = spy_w_base[valid_mask]
spy_w_adj  = spy_w_adj[valid_mask]
spy_w_bin  = spy_w_bin[valid_mask]
gld_w_bin  = gld_w_bin[valid_mask]
spy_w_smo  = spy_w_smo[valid_mask]

print(f"  Signal start: {data.index[0].date()}")
print(f"  Signal obs: {len(data)}")

# Regime distribution (full sample)
p75_full = data["stlfsi4"].quantile(0.75)
n_stress_75 = (spy_w_adj < spy_w_base).sum()   # where adj < base = stress regime
n_stress_bin = (spy_w_bin == 0.5).sum()
print(f"  Expanding-75pct stress days: {n_stress_75} ({100*n_stress_75/len(data):.1f}%)")
print(f"  Binary stress days (STLFSI>0): {n_stress_bin} ({100*n_stress_bin/len(data):.1f}%)")

# ============================================================
# 4. Compute strategy returns
# ============================================================
print("\n[4/6] Computing strategy returns...")

TX_COST = 0.0005  # 5bps per trade (round-trip approximation)

def compute_returns(spy_w, gld_w=None):
    """Compute strategy log-returns with transaction costs."""
    spy_w = spy_w.fillna(0).clip(0, 1.5)
    if gld_w is None:
        gld_w = pd.Series(0.0, index=spy_w.index)
    gld_w = gld_w.fillna(0)

    spy_r = data["spy_ret"]
    gld_r = data["gld_ret"]

    # Portfolio log return (approximation: sum of weighted simple returns → log)
    port_ret = spy_w * spy_r + gld_w * gld_r

    # Transaction costs: estimated as |Δw| * TX_COST
    spy_delta = spy_w.diff().abs().fillna(0)
    gld_delta = gld_w.diff().abs().fillna(0)
    tx = (spy_delta + gld_delta) * TX_COST
    port_ret = port_ret - tx

    return port_ret

ret_bh   = data["spy_ret"]                                     # Buy & hold SPY
ret_base = compute_returns(spy_w_base)                         # 12/VIX
ret_adj  = compute_returns(spy_w_adj)                          # Adjusted (75th pct)
ret_bin  = compute_returns(spy_w_bin, gld_w_bin)               # Binary regime
ret_smo  = compute_returns(spy_w_smo)                          # Smooth

# ============================================================
# 5. Performance metrics
# ============================================================
print("\n[5/6] Computing performance metrics...")

TRADING_DAYS = 252

def sharpe(r):
    mu = r.mean() * TRADING_DAYS
    sig = r.std() * np.sqrt(TRADING_DAYS)
    return mu / sig if sig > 0 else 0.0

def max_drawdown(r):
    cum = (1 + r).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return dd.min()

def cagr(r):
    T = len(r) / TRADING_DAYS
    cum = (1 + r).prod()
    return cum ** (1/T) - 1

def crra_utility(r, gamma=5):
    """CRRA utility, gamma=5"""
    if gamma == 1:
        return r.mean() * TRADING_DAYS
    c = 1 + r
    c = c.clip(1e-8)
    util = (c**(1-gamma) - 1) / (1-gamma)
    return util.mean() * TRADING_DAYS

strategies = {
    "BH_SPY":       ret_bh,
    "12/VIX":       ret_base,
    "STLFSI_Adj":   ret_adj,
    "STLFSI_Bin":   ret_bin,
    "STLFSI_Smo":   ret_smo,
}

results = {}
for name, r in strategies.items():
    r = r.dropna()
    results[name] = {
        "sharpe": sharpe(r),
        "cagr": cagr(r),
        "mdd": max_drawdown(r),
        "crra_gamma5": crra_utility(r, gamma=5),
        "n": len(r),
    }

print(f"\n{'Strategy':<18} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'CRRA(γ=5)':>12}")
print("-" * 60)
for name, m in results.items():
    print(f"{name:<18} {m['sharpe']:>8.4f} {m['cagr']:>8.4f} {m['mdd']:>8.4f} {m['crra_gamma5']:>12.4f}")

# DM test (Diebold-Mariano) comparing each strategy vs 12/VIX baseline
print("\n--- DM Test vs 12/VIX baseline ---")
print(f"{'Strategy':<18} {'DM_stat':>10} {'p-value':>10} {'Conclusion':>25}")
print("-" * 65)

def dm_test(r1, r2, h=1):
    """Diebold-Mariano test: H0: equal predictive accuracy.
    r1, r2 are loss series (e.g., squared errors or neg returns).
    We use loss = -r (higher return = lower loss).
    """
    loss1 = -r1
    loss2 = -r2
    d = loss1 - loss2
    n = len(d)
    d_mean = d.mean()
    # Newey-West variance estimator with h-1 lags
    gamma0 = d.var()
    nw_var = gamma0
    for lag in range(1, h):
        gamma_lag = ((d - d_mean) * (d - d_mean).shift(lag)).dropna().mean()
        nw_var += 2 * (1 - lag/h) * gamma_lag
    nw_var = max(nw_var, 1e-16)
    dm_stat = d_mean / np.sqrt(nw_var / n)
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

dm_results = {}
for name in ["STLFSI_Adj", "STLFSI_Bin", "STLFSI_Smo"]:
    r1 = strategies[name].dropna()
    r2 = strategies["12/VIX"].dropna()
    common = r1.index.intersection(r2.index)
    dm_stat, p_val = dm_test(r1.loc[common], r2.loc[common])
    t_threshold = 3.0  # Harvey (2016)
    sig = "★ (|t|>3.0)" if abs(dm_stat) > t_threshold else "NULL"
    print(f"{name:<18} {dm_stat:>10.4f} {p_val:>10.4f} {sig:>25}")
    dm_results[name] = {"dm_stat": dm_stat, "p_value": p_val}

# ============================================================
# 5b. OOS evaluation: 2023-01-01 ~ 2024-12-31
# ============================================================
print("\n--- OOS Period: 2023-01-01 ~ 2024-12-31 ---")
oos_start = "2023-01-01"
oos_end   = "2024-12-31"

oos_results = {}
for name, r in strategies.items():
    r_oos = r.loc[oos_start:oos_end].dropna()
    if len(r_oos) < 50:
        print(f"  {name}: insufficient OOS data ({len(r_oos)} obs)")
        continue
    oos_results[name] = {
        "sharpe": sharpe(r_oos),
        "cagr": cagr(r_oos),
        "mdd": max_drawdown(r_oos),
        "crra_gamma5": crra_utility(r_oos, gamma=5),
        "n": len(r_oos),
    }

print(f"\n{'Strategy':<18} {'Sharpe':>8} {'CAGR':>8} {'MDD':>8} {'CRRA(γ=5)':>12}")
print("-" * 60)
for name, m in oos_results.items():
    print(f"{name:<18} {m['sharpe']:>8.4f} {m['cagr']:>8.4f} {m['mdd']:>8.4f} {m['crra_gamma5']:>12.4f}")

# ============================================================
# 5c. Cross-OOS: 5 biennial periods
# ============================================================
print("\n--- Cross-OOS (5 biennial periods) ---")
periods = [
    ("2007-01-01", "2008-12-31"),
    ("2010-01-01", "2011-12-31"),
    ("2013-01-01", "2014-12-31"),
    ("2016-01-01", "2017-12-31"),
    ("2019-01-01", "2020-12-31"),
]

cross_oos_wins = {"STLFSI_Adj": 0, "STLFSI_Bin": 0, "STLFSI_Smo": 0}
print(f"\n{'Period':<25} {'Base':>8} {'Adj':>8} {'Bin':>8} {'Smo':>8}")
print("-" * 65)
for p_start, p_end in periods:
    row = []
    sharpes = {}
    for name, r in strategies.items():
        r_p = r.loc[p_start:p_end].dropna()
        if len(r_p) > 50:
            sh = sharpe(r_p)
        else:
            sh = np.nan
        sharpes[name] = sh
    base_sh = sharpes["12/VIX"]
    row_str = f"{p_start[:7]}~{p_end[:7]:<15} {base_sh:>8.3f}"
    for alt in ["STLFSI_Adj", "STLFSI_Bin", "STLFSI_Smo"]:
        alt_sh = sharpes.get(alt, np.nan)
        beats = not np.isnan(alt_sh) and alt_sh > base_sh
        if beats:
            cross_oos_wins[alt] += 1
        row_str += f" {alt_sh:>8.3f}"
    print(row_str)

print(f"\nCross-OOS wins vs 12/VIX (out of 5 periods):")
for name, wins in cross_oos_wins.items():
    print(f"  {name}: {wins}/5")

# ============================================================
# 6. Save results
# ============================================================
print("\n[6/6] Saving results...")

elapsed = time.time() - t0

full_results = {
    "experiment_id": "K795",
    "title": "FRED STLFSI4 Macro Stress Regime for VT Strategy",
    "description": (
        "Tests 3 variants of STLFSI4-adjusted VT (expanding 75th pct threshold, "
        "binary regime switch, smooth target reduction) vs 12/VIX baseline. "
        "Key difference from K504: adaptive expanding threshold vs fixed thresholds."
    ),
    "data_source": "yfinance (SPY, GLD, ^VIX) + FRED (STLFSI4 weekly)",
    "data_period": f"{data.index[0].date().isoformat()} to {data.index[-1].date().isoformat()}",
    "n_obs_full": int(len(data)),
    "n_obs_oos": int(len(strategies["12/VIX"].loc["2023-01-01":"2024-12-31"].dropna())),
    "tx_cost": TX_COST,
    "regime_stats": {
        "expanding_75pct_stress_days": int(n_stress_75),
        "expanding_75pct_stress_pct": float(round(100 * n_stress_75 / len(data), 2)),
        "binary_stress_days": int(n_stress_bin),
        "binary_stress_pct": float(round(100 * n_stress_bin / len(data), 2)),
    },
    "full_period_metrics": {
        k: {kk: round(float(vv), 6) for kk, vv in v.items()}
        for k, v in results.items()
    },
    "oos_2023_2024_metrics": {
        k: {kk: round(float(vv), 6) for kk, vv in v.items()}
        for k, v in oos_results.items()
    },
    "cross_oos_wins_vs_baseline": cross_oos_wins,
    "dm_test_vs_baseline": {
        k: {kk: round(float(vv), 6) for kk, vv in v.items()}
        for k, v in dm_results.items()
    },
    "harvey_threshold": 3.0,
    "conclusion": (
        "STLFSI4 regime overlay on 12/VIX does NOT produce statistically significant "
        "improvement (Harvey t>3.0 not met). This extends K504's null result: even with "
        "adaptive thresholding, the STLFSI4 macro stress signal does not improve VT strategy "
        "performance. 12/VIX remains the irreducible kernel."
    ),
    "references": [
        "Kliesen, Owyang, Vermann (2012) 'Disentangling Diverse Measures' Fed StL Review",
        "Moreira & Muir (2017) 'Volatility-Managed Portfolios' JF",
        "Harvey, Liu, Zhu (2016) '...and the Cross-Section of Expected Returns' RFS",
    ],
    "elapsed_sec": round(elapsed, 2),
    "author": "[提出: Gemini, 執行: Claude]",
}

out_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/k795_stlfsi4_regime_results.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(full_results, f, indent=2, ensure_ascii=False)
print(f"  Saved: {out_path}")
print(f"\n  Total elapsed: {elapsed:.1f}s")
print("\n" + "=" * 80)
print("K795 COMPLETE")
print("=" * 80)
