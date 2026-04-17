"""
K338: Emerging Market Contagion — Does EM Stress Predict Developed Market Vol?
==============================================================================
[提出: 用戶, 執行: Claude]

跳躍式探索：新興市場危機（亞洲1997、Taper Tantrum 2013、土耳其2018、中國2015）
是否會外溢到已開發市場？EM stress 信號能否預測 SPY 波動率？

數據來源：yfinance（真實市場數據）
- EEM (iShares MSCI Emerging Markets ETF)
- FXI (iShares China Large-Cap ETF)
- EWZ (iShares MSCI Brazil ETF)
- TUR (iShares MSCI Turkey ETF)
- SPY, ^VIX

方法論：
1. EM stress indicators:
   - EEM drawdown from peak (EM stress proxy)
   - EEM-SPY return divergence (EM underperforming = contagion risk)
   - EM vol / SPY vol ratio (relative stress)
   - FXI vs EEM (China-specific vs broad EM)
2. Granger causality: EEM vol → SPY vol (partial r controlling for VIX)
3. Contagion asymmetry: does EM stress matter more than EM calm?
4. Portfolio: should we reduce SPY when EM stress is high?

結論強度：exploratory（跨資產類別的新領域）
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
import os
import time
from datetime import datetime

print("=" * 70)
print("K338: Emerging Market Contagion")
print("       Does EM Stress Predict Developed Market Volatility?")
print("=" * 70)

# ============================================================
# 1. DATA LOADING
# ============================================================
print("\n[1] Loading data from yfinance ...")

tickers = {
    "EEM": "EEM",       # Broad EM
    "FXI": "FXI",       # China
    "EWZ": "EWZ",       # Brazil
    "TUR": "TUR",       # Turkey
    "SPY": "SPY",       # US benchmark
    "VIX": "^VIX",      # VIX
}

t0 = time.time()

data = {}
for name, ticker in tickers.items():
    try:
        df_raw = yf.download(ticker, start="2007-01-01", end="2026-01-01", progress=False)
        if isinstance(df_raw.columns, pd.MultiIndex):
            df_raw.columns = df_raw.columns.get_level_values(0)
        data[name] = df_raw["Close"]
        print(f"  {name} ({ticker}): {len(df_raw)} obs, {df_raw.index[0].date()} to {df_raw.index[-1].date()}")
    except Exception as e:
        print(f"  {name} ({ticker}): FAILED - {e}")

elapsed = time.time() - t0
print(f"  Data download: {elapsed:.1f}s")

# Merge into single DataFrame
prices = pd.DataFrame(data)
prices = prices.dropna()
print(f"\n  Merged dataset: {len(prices)} obs, {prices.index[0].date()} to {prices.index[-1].date()}")

# Compute returns
returns = prices[["EEM", "FXI", "EWZ", "TUR", "SPY"]].pct_change().dropna()

# Realized vol (22-day rolling)
rv22 = returns.rolling(22).std() * np.sqrt(252)
rv22 = rv22.dropna()

# Align VIX
vix = prices["VIX"].reindex(rv22.index)
vix = vix.ffill()

print(f"  Returns: {len(returns)} obs")
print(f"  Realized Vol (22d): {len(rv22)} obs")

# ============================================================
# 2. EM STRESS INDICATORS
# ============================================================
print("\n" + "=" * 70)
print("[2] Constructing EM Stress Indicators")
print("=" * 70)

# --- 2a. EEM Drawdown from Peak ---
eem_cum = (1 + returns["EEM"]).cumprod()
eem_peak = eem_cum.cummax()
eem_drawdown = (eem_cum / eem_peak - 1) * 100  # in percent
print(f"\n  2a. EEM Drawdown:")
print(f"      Mean: {eem_drawdown.mean():.2f}%")
print(f"      Worst: {eem_drawdown.min():.2f}%")
print(f"      % below -20%: {(eem_drawdown < -20).mean()*100:.1f}% of days")

# --- 2b. EEM-SPY Return Divergence (rolling 22d) ---
eem_spy_div = (returns["EEM"].rolling(22).mean() - returns["SPY"].rolling(22).mean()) * 252
eem_spy_div = eem_spy_div.dropna()
print(f"\n  2b. EEM-SPY Return Divergence (annualized rolling 22d):")
print(f"      Mean: {eem_spy_div.mean():.4f}")
print(f"      Std: {eem_spy_div.std():.4f}")
print(f"      Most negative (EM crisis): {eem_spy_div.min():.4f}")

# --- 2c. EM Vol / SPY Vol Ratio ---
em_spy_vol_ratio = rv22["EEM"] / rv22["SPY"]
print(f"\n  2c. EM/SPY Vol Ratio:")
print(f"      Mean: {em_spy_vol_ratio.mean():.3f}")
print(f"      Median: {em_spy_vol_ratio.median():.3f}")
print(f"      P95: {em_spy_vol_ratio.quantile(0.95):.3f}")

# --- 2d. FXI vs EEM relative (China-specific stress) ---
fxi_eem_div = (returns["FXI"].rolling(22).mean() - returns["EEM"].rolling(22).mean()) * 252
fxi_eem_div = fxi_eem_div.dropna()
print(f"\n  2d. FXI-EEM Divergence (China-specific):")
print(f"      Mean: {fxi_eem_div.mean():.4f}")
print(f"      Std: {fxi_eem_div.std():.4f}")

# --- Composite EM Stress Score ---
# Z-score each indicator and average
common_idx = eem_drawdown.index.intersection(eem_spy_div.index).intersection(em_spy_vol_ratio.index)

stress_dd = eem_drawdown.reindex(common_idx)
stress_div = eem_spy_div.reindex(common_idx)
stress_vol = em_spy_vol_ratio.reindex(common_idx)

# Higher = more stress: flip drawdown (more negative = more stress), flip divergence
z_dd = (stress_dd - stress_dd.mean()) / stress_dd.std() * (-1)  # flip: deeper drawdown = higher stress
z_div = (stress_div - stress_div.mean()) / stress_div.std() * (-1)  # flip: EM underperform = higher stress
z_vol = (stress_vol - stress_vol.mean()) / stress_vol.std()  # already: higher = more stress

em_stress_composite = (z_dd + z_div + z_vol) / 3
print(f"\n  Composite EM Stress Score:")
print(f"      Mean: {em_stress_composite.mean():.4f}")
print(f"      Std: {em_stress_composite.std():.4f}")
print(f"      P95 (high stress): {em_stress_composite.quantile(0.95):.3f}")
print(f"      P5 (low stress): {em_stress_composite.quantile(0.05):.3f}")

# ============================================================
# 3. GRANGER CAUSALITY: EM VOL → SPY VOL
# ============================================================
print("\n" + "=" * 70)
print("[3] Granger Causality: Does EM Vol Lead SPY Vol?")
print("=" * 70)

# Prepare aligned data
spy_rv_fwd = rv22["SPY"].shift(-5)  # SPY vol 5 days ahead
eem_rv = rv22["EEM"]
vix_aligned = vix.reindex(rv22.index)

# Drop NAs
gc_df = pd.DataFrame({
    "spy_rv_fwd": spy_rv_fwd,
    "eem_rv": eem_rv,
    "spy_rv": rv22["SPY"],
    "vix": vix_aligned,
    "em_stress": em_stress_composite.reindex(rv22.index),
}).dropna()

print(f"\n  Sample: {len(gc_df)} obs")

# --- 3a. Raw correlation: EEM RV → SPY future RV ---
r_raw, p_raw = stats.pearsonr(gc_df["eem_rv"], gc_df["spy_rv_fwd"])
print(f"\n  3a. Raw correlation (EEM_RV → SPY_RV_5d_ahead):")
print(f"      r = {r_raw:.4f}, p = {p_raw:.2e}")

# --- 3b. Partial correlation controlling for current SPY RV ---
from numpy.linalg import lstsq

def partial_corr(x, y, z_mat):
    """Partial correlation between x and y controlling for columns in z_mat."""
    # Residualize x on z
    A = np.column_stack([z_mat, np.ones(len(z_mat))])
    bx, _, _, _ = lstsq(A, x, rcond=None)
    res_x = x - A @ bx

    by, _, _, _ = lstsq(A, y, rcond=None)
    res_y = y - A @ by

    r, p = stats.pearsonr(res_x, res_y)
    return r, p

r_partial_spy, p_partial_spy = partial_corr(
    gc_df["eem_rv"].values,
    gc_df["spy_rv_fwd"].values,
    gc_df[["spy_rv"]].values
)
print(f"\n  3b. Partial r (controlling for SPY_RV_current):")
print(f"      r = {r_partial_spy:.4f}, p = {p_partial_spy:.2e}")

# --- 3c. Partial correlation controlling for both SPY RV and VIX ---
r_partial_both, p_partial_both = partial_corr(
    gc_df["eem_rv"].values,
    gc_df["spy_rv_fwd"].values,
    gc_df[["spy_rv", "vix"]].values
)
print(f"\n  3c. Partial r (controlling for SPY_RV + VIX):")
print(f"      r = {r_partial_both:.4f}, p = {p_partial_both:.2e}")

# --- 3d. Formal Granger test using OLS with lags ---
print(f"\n  3d. Granger Causality (OLS with lags 1-5):")
from numpy.linalg import lstsq as np_lstsq

# Prepare lagged data
max_lag = 5
granger_data = pd.DataFrame({
    "spy_rv": rv22["SPY"],
    "eem_rv": rv22["EEM"],
})
granger_data = granger_data.dropna()

for lag in range(1, max_lag + 1):
    granger_data[f"spy_rv_lag{lag}"] = granger_data["spy_rv"].shift(lag)
    granger_data[f"eem_rv_lag{lag}"] = granger_data["eem_rv"].shift(lag)

granger_data = granger_data.dropna()
y = granger_data["spy_rv"].values

# Restricted model: SPY RV ~ SPY RV lags only
X_r = granger_data[[f"spy_rv_lag{i}" for i in range(1, max_lag+1)]].values
X_r = np.column_stack([X_r, np.ones(len(X_r))])

# Unrestricted model: SPY RV ~ SPY RV lags + EEM RV lags
X_u = granger_data[[f"spy_rv_lag{i}" for i in range(1, max_lag+1)] +
                    [f"eem_rv_lag{i}" for i in range(1, max_lag+1)]].values
X_u = np.column_stack([X_u, np.ones(len(X_u))])

# F-test
b_r, _, _, _ = np_lstsq(X_r, y, rcond=None)
b_u, _, _, _ = np_lstsq(X_u, y, rcond=None)

rss_r = np.sum((y - X_r @ b_r) ** 2)
rss_u = np.sum((y - X_u @ b_u) ** 2)

n = len(y)
k_r = X_r.shape[1]
k_u = X_u.shape[1]
df1 = k_u - k_r
df2 = n - k_u

F_stat = ((rss_r - rss_u) / df1) / (rss_u / df2)
p_granger = 1 - stats.f.cdf(F_stat, df1, df2)

print(f"      F({df1},{df2}) = {F_stat:.2f}, p = {p_granger:.2e}")
print(f"      RSS restricted: {rss_r:.4f}, RSS unrestricted: {rss_u:.4f}")
print(f"      {'*** SIGNIFICANT (p<0.01)' if p_granger < 0.01 else '** SIGNIFICANT (p<0.05)' if p_granger < 0.05 else 'NOT SIGNIFICANT (p>=0.05)'}")

# --- 3e. Individual EM countries Granger test ---
print(f"\n  3e. Granger Causality by Country (each → SPY RV):")
em_tickers = ["EEM", "FXI", "EWZ", "TUR"]
granger_results = {}

for em in em_tickers:
    gd = pd.DataFrame({
        "spy_rv": rv22["SPY"],
        "em_rv": rv22[em],
    }).dropna()

    for lag in range(1, max_lag + 1):
        gd[f"spy_lag{lag}"] = gd["spy_rv"].shift(lag)
        gd[f"em_lag{lag}"] = gd["em_rv"].shift(lag)
    gd = gd.dropna()

    y_g = gd["spy_rv"].values
    X_r_g = gd[[f"spy_lag{i}" for i in range(1, max_lag+1)]].values
    X_r_g = np.column_stack([X_r_g, np.ones(len(X_r_g))])
    X_u_g = gd[[f"spy_lag{i}" for i in range(1, max_lag+1)] +
                [f"em_lag{i}" for i in range(1, max_lag+1)]].values
    X_u_g = np.column_stack([X_u_g, np.ones(len(X_u_g))])

    b_r_g, _, _, _ = np_lstsq(X_r_g, y_g, rcond=None)
    b_u_g, _, _, _ = np_lstsq(X_u_g, y_g, rcond=None)

    rss_r_g = np.sum((y_g - X_r_g @ b_r_g) ** 2)
    rss_u_g = np.sum((y_g - X_u_g @ b_u_g) ** 2)

    n_g = len(y_g)
    F_g = ((rss_r_g - rss_u_g) / max_lag) / (rss_u_g / (n_g - X_u_g.shape[1]))
    p_g = 1 - stats.f.cdf(F_g, max_lag, n_g - X_u_g.shape[1])

    sig = "***" if p_g < 0.001 else "**" if p_g < 0.01 else "*" if p_g < 0.05 else "n.s."
    print(f"      {em:4s} → SPY: F = {F_g:.2f}, p = {p_g:.2e} {sig}")
    granger_results[em] = {"F": float(F_g), "p": float(p_g)}


# ============================================================
# 4. CONTAGION ASYMMETRY
# ============================================================
print("\n" + "=" * 70)
print("[4] Contagion Asymmetry: Does EM Stress Matter More Than EM Calm?")
print("=" * 70)

# Split into EM stress vs calm periods using composite score
stress_threshold_high = em_stress_composite.quantile(0.80)
stress_threshold_low = em_stress_composite.quantile(0.20)

# Align forward SPY vol
asym_df = pd.DataFrame({
    "em_stress": em_stress_composite,
    "spy_rv_fwd5": rv22["SPY"].shift(-5),
    "spy_rv_fwd22": rv22["SPY"].shift(-22),
    "spy_rv_now": rv22["SPY"],
    "vix": vix.reindex(em_stress_composite.index),
}).dropna()

high_stress = asym_df[asym_df["em_stress"] > stress_threshold_high]
low_stress = asym_df[asym_df["em_stress"] < stress_threshold_low]
mid_stress = asym_df[(asym_df["em_stress"] >= stress_threshold_low) &
                      (asym_df["em_stress"] <= stress_threshold_high)]

print(f"\n  Thresholds: High > {stress_threshold_high:.3f}, Low < {stress_threshold_low:.3f}")
print(f"  High stress periods: {len(high_stress)} obs ({len(high_stress)/len(asym_df)*100:.1f}%)")
print(f"  Low stress periods:  {len(low_stress)} obs ({len(low_stress)/len(asym_df)*100:.1f}%)")
print(f"  Mid stress periods:  {len(mid_stress)} obs ({len(mid_stress)/len(asym_df)*100:.1f}%)")

# Compare SPY forward vol in each regime
print(f"\n  SPY Future Vol (5d ahead) by EM Stress Regime:")
print(f"  {'Regime':<15} {'Mean':>10} {'Median':>10} {'Std':>10} {'N':>6}")
print(f"  {'-'*55}")
for name, subset in [("High Stress", high_stress), ("Mid", mid_stress), ("Low Stress", low_stress)]:
    rv = subset["spy_rv_fwd5"]
    print(f"  {name:<15} {rv.mean():>10.4f} {rv.median():>10.4f} {rv.std():>10.4f} {len(rv):>6d}")

# T-test: high vs low stress
t_asym, p_asym = stats.ttest_ind(high_stress["spy_rv_fwd5"], low_stress["spy_rv_fwd5"])
print(f"\n  T-test (High vs Low): t = {t_asym:.3f}, p = {p_asym:.2e}")
print(f"  {'*** SIGNIFICANT' if p_asym < 0.001 else '** SIGNIFICANT' if p_asym < 0.01 else '* SIGNIFICANT' if p_asym < 0.05 else 'NOT SIGNIFICANT'}")

# Same for 22d ahead
print(f"\n  SPY Future Vol (22d ahead) by EM Stress Regime:")
print(f"  {'Regime':<15} {'Mean':>10} {'Median':>10}")
print(f"  {'-'*40}")
for name, subset in [("High Stress", high_stress), ("Mid", mid_stress), ("Low Stress", low_stress)]:
    rv = subset["spy_rv_fwd22"]
    print(f"  {name:<15} {rv.mean():>10.4f} {rv.median():>10.4f}")

t_asym22, p_asym22 = stats.ttest_ind(high_stress["spy_rv_fwd22"], low_stress["spy_rv_fwd22"])
print(f"\n  T-test 22d (High vs Low): t = {t_asym22:.3f}, p = {p_asym22:.2e}")

# --- 4b. Incremental info beyond VIX ---
print(f"\n  4b. Does EM stress add info BEYOND VIX?")

# Regression: SPY_RV_fwd = a + b*VIX (restricted)
# vs SPY_RV_fwd = a + b*VIX + c*EM_stress (unrestricted)
y_a = asym_df["spy_rv_fwd5"].values
X_vix = np.column_stack([asym_df["vix"].values, np.ones(len(asym_df))])
X_vix_em = np.column_stack([asym_df["vix"].values, asym_df["em_stress"].values, np.ones(len(asym_df))])

b_vix, _, _, _ = np_lstsq(X_vix, y_a, rcond=None)
b_vix_em, _, _, _ = np_lstsq(X_vix_em, y_a, rcond=None)

rss_vix = np.sum((y_a - X_vix @ b_vix) ** 2)
rss_vix_em = np.sum((y_a - X_vix_em @ b_vix_em) ** 2)

r2_vix = 1 - rss_vix / np.sum((y_a - y_a.mean()) ** 2)
r2_vix_em = 1 - rss_vix_em / np.sum((y_a - y_a.mean()) ** 2)

n_a = len(y_a)
F_incr = ((rss_vix - rss_vix_em) / 1) / (rss_vix_em / (n_a - 3))
p_incr = 1 - stats.f.cdf(F_incr, 1, n_a - 3)

print(f"      R² (VIX only):       {r2_vix:.4f}")
print(f"      R² (VIX + EM stress): {r2_vix_em:.4f}")
print(f"      ΔR²:                 {r2_vix_em - r2_vix:.4f}")
print(f"      F-test for EM stress: F = {F_incr:.2f}, p = {p_incr:.2e}")
print(f"      EM stress coeff:     {b_vix_em[1]:.6f}")
print(f"      {'*** EM stress adds info beyond VIX' if p_incr < 0.001 else '** EM stress adds info' if p_incr < 0.01 else '* Marginal' if p_incr < 0.05 else 'EM stress REDUNDANT given VIX'}")


# ============================================================
# 5. CRISIS CASE STUDIES
# ============================================================
print("\n" + "=" * 70)
print("[5] Crisis Case Studies: EM Stress → SPY Vol Spillover")
print("=" * 70)

crises = {
    "GFC 2008": ("2008-08-01", "2009-03-31"),
    "EU Debt 2011": ("2011-07-01", "2011-12-31"),
    "Taper Tantrum 2013": ("2013-05-01", "2013-09-30"),
    "China Crash 2015": ("2015-06-01", "2015-12-31"),
    "Turkey 2018": ("2018-07-01", "2018-12-31"),
    "COVID 2020": ("2020-02-01", "2020-05-31"),
    "EM Selloff 2022": ("2022-01-01", "2022-06-30"),
}

print(f"\n  {'Crisis':<25} {'EEM DD%':>10} {'SPY DD%':>10} {'EEM/SPY':>10} {'EEM Vol':>10} {'SPY Vol':>10} {'VIX':>8}")
print(f"  {'-'*88}")

# Also compute EM cum returns for drawdown
spy_cum = (1 + returns["SPY"]).cumprod()
spy_peak = spy_cum.cummax()
spy_drawdown = (spy_cum / spy_peak - 1) * 100

crisis_data = {}
for name, (start, end) in crises.items():
    # Use each series' own index for date filtering
    eem_dd_period = eem_drawdown[(eem_drawdown.index >= start) & (eem_drawdown.index <= end)]
    spy_dd_period = spy_drawdown[(spy_drawdown.index >= start) & (spy_drawdown.index <= end)]

    if len(eem_dd_period) == 0:
        continue

    period_eem_dd = eem_dd_period.min()
    period_spy_dd = spy_dd_period.min() if len(spy_dd_period) > 0 else np.nan

    em_rv_period = rv22["EEM"][(rv22.index >= start) & (rv22.index <= end)].mean()
    spy_rv_period = rv22["SPY"][(rv22.index >= start) & (rv22.index <= end)].mean()
    ratio = em_rv_period / spy_rv_period if spy_rv_period > 0 else np.nan
    vix_period = vix[(vix.index >= start) & (vix.index <= end)].mean()

    print(f"  {name:<25} {period_eem_dd:>10.1f} {period_spy_dd:>10.1f} {ratio:>10.2f} {em_rv_period:>10.2f} {spy_rv_period:>10.2f} {vix_period:>8.1f}")

    crisis_data[name] = {
        "eem_dd": float(period_eem_dd) if not np.isnan(period_eem_dd) else None,
        "spy_dd": float(period_spy_dd) if not np.isnan(period_spy_dd) else None,
        "em_spy_vol_ratio": float(ratio) if not np.isnan(ratio) else None,
        "vix_mean": float(vix_period) if not np.isnan(vix_period) else None,
    }

# --- Which country leads? ---
print(f"\n  Lead-Lag: Which EM country vol peaks first?")
for name, (start, end) in crises.items():
    rv22_period = rv22[(rv22.index >= start) & (rv22.index <= end)]
    if len(rv22_period) == 0:
        continue

    peak_dates = {}
    for em in ["EEM", "FXI", "EWZ", "TUR", "SPY"]:
        series = rv22_period[em]
        if len(series) > 0:
            peak_dates[em] = series.idxmax()

    if peak_dates:
        sorted_peaks = sorted(peak_dates.items(), key=lambda x: x[1])
        order_str = " → ".join([f"{k}({v.strftime('%m/%d')})" for k, v in sorted_peaks])
        spy_lag = (peak_dates.get("SPY", pd.Timestamp("2099-01-01")) - sorted_peaks[0][1]).days
        print(f"  {name:<25}: {order_str}")
        if "SPY" in peak_dates:
            print(f"  {'':25}  SPY vol peak {spy_lag:+d} days after first EM peak")


# ============================================================
# 6. PORTFOLIO STRATEGY
# ============================================================
print("\n" + "=" * 70)
print("[6] Portfolio Strategy: Reduce SPY When EM Stress is High")
print("=" * 70)

# Strategy: Use lagged EM stress to scale SPY allocation
# High stress → reduce to 50% SPY + 50% cash (SHY proxy)
# Normal → 100% SPY
# Use lookback to avoid forward bias

strat_df = pd.DataFrame({
    "spy_ret": returns["SPY"],
    "em_stress": em_stress_composite,
}).dropna()

# Lag the signal by 1 day (no forward bias)
strat_df["em_stress_lag"] = strat_df["em_stress"].shift(1)
strat_df = strat_df.dropna()

# Strategy variants
strategies = {}

# Buy-and-hold SPY
strategies["BH_SPY"] = strat_df["spy_ret"]

# Binary: reduce when stress > P80
p80 = strat_df["em_stress_lag"].quantile(0.80)
weight_binary = np.where(strat_df["em_stress_lag"] > p80, 0.5, 1.0)
strategies["EM_Binary_P80"] = strat_df["spy_ret"] * weight_binary

# Graduated: proportional reduction
# Map stress to weight: stress < P20 → 1.0, stress > P80 → 0.3, linear between
p20 = strat_df["em_stress_lag"].quantile(0.20)
weight_grad = 1.0 - 0.7 * np.clip((strat_df["em_stress_lag"].values - p20) / (p80 - p20), 0, 1)
strategies["EM_Graduated"] = strat_df["spy_ret"] * weight_grad

# VIX-based (benchmark): 12/VIX
vix_strat = vix.reindex(strat_df.index).shift(1)
weight_vix = np.clip(12 / vix_strat.values, 0, 1)
strategies["VIX_12"] = strat_df["spy_ret"] * weight_vix

# Combined: EM stress + VIX
weight_combined = np.minimum(weight_grad, weight_vix)
strategies["EM_VIX_Combined"] = strat_df["spy_ret"] * weight_combined

print(f"\n  Backtest: {strat_df.index[0].date()} to {strat_df.index[-1].date()} ({len(strat_df)} days)")
print(f"\n  {'Strategy':<20} {'CAGR%':>8} {'Vol%':>8} {'Sharpe':>8} {'MDD%':>8} {'Calmar':>8} {'Turnover':>10}")
print(f"  {'-'*78}")

results = {}
for name, rets in strategies.items():
    cum = (1 + rets).cumprod()
    n_years = len(rets) / 252
    cagr = (cum.iloc[-1] ** (1 / n_years) - 1) * 100
    vol = rets.std() * np.sqrt(252) * 100
    sharpe = (rets.mean() * 252) / (rets.std() * np.sqrt(252)) if rets.std() > 0 else 0

    # MDD
    peak = cum.cummax()
    dd = (cum / peak - 1)
    mdd = dd.min() * 100

    calmar = cagr / abs(mdd) if abs(mdd) > 0 else 0

    # Turnover (for non-BH strategies)
    if name == "BH_SPY":
        turnover = 0
    elif name == "EM_Binary_P80":
        turnover = np.sum(np.abs(np.diff(weight_binary))) / n_years
    elif name == "EM_Graduated":
        turnover = np.sum(np.abs(np.diff(weight_grad))) / n_years
    elif name == "VIX_12":
        w = np.clip(12 / vix_strat.dropna().values, 0, 1)
        turnover = np.sum(np.abs(np.diff(w))) / n_years
    elif name == "EM_VIX_Combined":
        turnover = np.sum(np.abs(np.diff(weight_combined))) / n_years
    else:
        turnover = 0

    print(f"  {name:<20} {cagr:>8.2f} {vol:>8.2f} {sharpe:>8.3f} {mdd:>8.2f} {calmar:>8.3f} {turnover:>10.1f}")

    results[name] = {
        "cagr": float(cagr),
        "vol": float(vol),
        "sharpe": float(sharpe),
        "mdd": float(mdd),
        "calmar": float(calmar),
        "turnover": float(turnover),
    }

# --- 6b. Statistical test: EM strategy vs BH ---
print(f"\n  6b. Statistical Tests vs Buy-and-Hold:")
bh = strategies["BH_SPY"]
for name, rets in strategies.items():
    if name == "BH_SPY":
        continue
    diff = rets - bh
    t_stat = diff.mean() / (diff.std() / np.sqrt(len(diff)))
    p_val = 2 * stats.t.sf(abs(t_stat), len(diff) - 1)
    print(f"      {name:<20}: mean diff = {diff.mean()*252*100:.2f}% ann, t = {t_stat:.3f}, p = {p_val:.4f}")


# ============================================================
# 7. OOS VALIDATION (Split Sample)
# ============================================================
print("\n" + "=" * 70)
print("[7] Out-of-Sample Validation")
print("=" * 70)

# Split at midpoint
mid_idx = len(strat_df) // 2
is_data = strat_df.iloc[:mid_idx]
oos_data = strat_df.iloc[mid_idx:]

print(f"\n  In-sample:  {is_data.index[0].date()} to {is_data.index[-1].date()} ({len(is_data)} obs)")
print(f"  Out-of-sample: {oos_data.index[0].date()} to {oos_data.index[-1].date()} ({len(oos_data)} obs)")

# Recalculate thresholds from IS data only
p80_is = is_data["em_stress_lag"].quantile(0.80)
p20_is = is_data["em_stress_lag"].quantile(0.20)

# Apply IS thresholds to OOS data
oos_weight_binary = np.where(oos_data["em_stress_lag"] > p80_is, 0.5, 1.0)
oos_weight_grad = 1.0 - 0.7 * np.clip((oos_data["em_stress_lag"].values - p20_is) / (p80_is - p20_is), 0, 1)

vix_oos = vix.reindex(oos_data.index).shift(1).ffill()
oos_weight_vix = np.clip(12 / vix_oos.values, 0, 1)

oos_strats = {
    "BH_SPY": oos_data["spy_ret"],
    "EM_Binary_P80": oos_data["spy_ret"] * oos_weight_binary,
    "EM_Graduated": oos_data["spy_ret"] * oos_weight_grad,
    "VIX_12": oos_data["spy_ret"] * oos_weight_vix,
}

print(f"\n  OOS Results:")
print(f"  {'Strategy':<20} {'Sharpe':>8} {'MDD%':>8} {'CAGR%':>8}")
print(f"  {'-'*50}")

oos_results = {}
for name, rets in oos_strats.items():
    rets = rets.dropna()
    if len(rets) == 0:
        continue
    cum = (1 + rets).cumprod()
    n_years = len(rets) / 252
    cagr = (cum.iloc[-1] ** (1 / n_years) - 1) * 100 if n_years > 0 else 0
    sharpe = (rets.mean() * 252) / (rets.std() * np.sqrt(252)) if rets.std() > 0 else 0
    mdd = ((cum / cum.cummax()) - 1).min() * 100

    print(f"  {name:<20} {sharpe:>8.3f} {mdd:>8.2f} {cagr:>8.2f}")
    oos_results[name] = {"sharpe": float(sharpe), "mdd": float(mdd), "cagr": float(cagr)}


# ============================================================
# 8. CROSS-CORRELATION ANALYSIS
# ============================================================
print("\n" + "=" * 70)
print("[8] Cross-Correlation: EM Vol Leads/Lags SPY Vol")
print("=" * 70)

# Compute cross-correlation at different lags
spy_rv_daily = rv22["SPY"]
eem_rv_daily = rv22["EEM"]

lags = range(-20, 21)
xcorr = []
for lag in lags:
    if lag >= 0:
        x = eem_rv_daily.iloc[:len(eem_rv_daily)-lag] if lag > 0 else eem_rv_daily
        y = spy_rv_daily.iloc[lag:] if lag > 0 else spy_rv_daily
    else:
        x = eem_rv_daily.iloc[-lag:]
        y = spy_rv_daily.iloc[:len(spy_rv_daily)+lag]

    common = x.index.intersection(y.index)
    if len(common) > 100:
        r, _ = stats.pearsonr(x.reindex(common), y.reindex(common))
        xcorr.append(r)
    else:
        xcorr.append(np.nan)

# Find peak
xcorr_arr = np.array(xcorr)
lags_arr = np.array(list(lags))
peak_idx = np.nanargmax(xcorr_arr)
peak_lag = lags_arr[peak_idx]
peak_corr = xcorr_arr[peak_idx]

print(f"\n  Cross-correlation (EEM_RV(t) vs SPY_RV(t+lag)):")
print(f"  Peak at lag = {peak_lag} days, r = {peak_corr:.4f}")
print(f"  (Positive lag = EEM leads SPY)")
print(f"\n  Selected lags:")
for lag_val in [-10, -5, -2, -1, 0, 1, 2, 5, 10, 20]:
    idx = lag_val - lags[0]
    if 0 <= idx < len(xcorr):
        print(f"    Lag {lag_val:+3d}d: r = {xcorr[idx]:.4f}")


# ============================================================
# 9. EM CONTAGION ASYMMETRY (DETAILED)
# ============================================================
print("\n" + "=" * 70)
print("[9] Detailed Contagion Asymmetry Analysis")
print("=" * 70)

# Break into quintiles of EM stress
quintile_labels = ["Q1 (Calm)", "Q2", "Q3", "Q4", "Q5 (Stress)"]
asym_df2 = asym_df.copy()
asym_df2["stress_q"] = pd.qcut(asym_df2["em_stress"], 5, labels=quintile_labels)

print(f"\n  SPY Forward Vol (5d) by EM Stress Quintile:")
print(f"  {'Quintile':<15} {'Mean RV':>10} {'Median RV':>10} {'SPY Ret%':>10} {'N':>6}")
print(f"  {'-'*55}")

quintile_data = {}
for q in quintile_labels:
    subset = asym_df2[asym_df2["stress_q"] == q]
    rv_mean = subset["spy_rv_fwd5"].mean()
    rv_median = subset["spy_rv_fwd5"].median()
    # Also check SPY return during these periods
    spy_ret = returns["SPY"].reindex(subset.index).mean() * 252 * 100
    print(f"  {q:<15} {rv_mean:>10.4f} {rv_median:>10.4f} {spy_ret:>10.2f} {len(subset):>6d}")
    quintile_data[q] = {"mean_rv": float(rv_mean), "median_rv": float(rv_median), "spy_ret_ann": float(spy_ret)}

# Monotonicity test
means = [quintile_data[q]["mean_rv"] for q in quintile_labels]
is_monotone = all(means[i] <= means[i+1] for i in range(len(means)-1))
spearman_q, p_spearman_q = stats.spearmanr(range(5), means)
print(f"\n  Monotonicity: {'YES' if is_monotone else 'NO'}")
print(f"  Spearman rank correlation (quintile vs mean RV): rho = {spearman_q:.4f}, p = {p_spearman_q:.4f}")

# Q5/Q1 ratio
q5q1_ratio = means[4] / means[0] if means[0] > 0 else np.nan
print(f"  Q5/Q1 vol ratio: {q5q1_ratio:.2f}x")


# ============================================================
# 10. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("[10] SUMMARY & CONCLUSIONS")
print("=" * 70)

print(f"""
  DATA:
  - Assets: EEM, FXI, EWZ, TUR, SPY, VIX
  - Period: {prices.index[0].date()} to {prices.index[-1].date()} ({len(prices)} obs)
  - Source: yfinance (real market data)

  KEY FINDINGS:

  1. Granger Causality (EEM RV → SPY RV):
     F = {F_stat:.2f}, p = {p_granger:.2e}
     {'EM vol DOES Granger-cause SPY vol' if p_granger < 0.05 else 'EM vol does NOT Granger-cause SPY vol'}

  2. Partial Correlation (controlling for VIX):
     r = {r_partial_both:.4f}, p = {p_partial_both:.2e}
     {'EM vol has info BEYOND VIX' if p_partial_both < 0.05 else 'EM vol is REDUNDANT given VIX'}

  3. Contagion Asymmetry:
     High EM stress → SPY future vol: {high_stress["spy_rv_fwd5"].mean():.4f}
     Low EM stress  → SPY future vol: {low_stress["spy_rv_fwd5"].mean():.4f}
     T-test: t = {t_asym:.3f}, p = {p_asym:.2e}
     Q5/Q1 vol ratio: {q5q1_ratio:.2f}x

  4. Incremental Info Beyond VIX:
     ΔR² = {r2_vix_em - r2_vix:.4f}, F = {F_incr:.2f}, p = {p_incr:.2e}
     {'EM stress ADDS info beyond VIX' if p_incr < 0.05 else 'EM stress is REDUNDANT given VIX'}

  5. Portfolio Strategy (full sample):
""")

for name in ["BH_SPY", "EM_Binary_P80", "EM_Graduated", "VIX_12", "EM_VIX_Combined"]:
    r = results[name]
    print(f"     {name:<20}: Sharpe={r['sharpe']:.3f}, MDD={r['mdd']:.1f}%, CAGR={r['cagr']:.1f}%")

print(f"""
  6. Cross-Correlation Peak:
     EEM_RV leads SPY_RV by {peak_lag} days (r = {peak_corr:.4f})

  LIMITATIONS:
  - EEM/FXI/EWZ/TUR are equity proxies for EM stress (not bond spreads/CDS)
  - Rolling 22d RV smooths out sudden regime changes
  - EM stress composite is equally weighted (no optimization)
  - No transaction costs in portfolio strategy
  - Drawdown indicator is path-dependent and slow to reset
""")


# ============================================================
# SAVE RESULTS
# ============================================================
output = {
    "experiment": "K338",
    "title": "Emerging Market Contagion — Does EM Stress Predict Developed Market Vol?",
    "attribution": "[提出: 用戶, 執行: Claude]",
    "date": datetime.now().isoformat(),
    "data": {
        "source": "yfinance",
        "assets": list(tickers.keys()),
        "period": f"{prices.index[0].date()} to {prices.index[-1].date()}",
        "n_obs": len(prices),
    },
    "granger_causality": {
        "eem_to_spy": {"F": float(F_stat), "p": float(p_granger), "lags": max_lag},
        "by_country": granger_results,
    },
    "partial_correlation": {
        "controlling_spy_rv": {"r": float(r_partial_spy), "p": float(p_partial_spy)},
        "controlling_spy_rv_and_vix": {"r": float(r_partial_both), "p": float(p_partial_both)},
    },
    "contagion_asymmetry": {
        "high_stress_spy_rv": float(high_stress["spy_rv_fwd5"].mean()),
        "low_stress_spy_rv": float(low_stress["spy_rv_fwd5"].mean()),
        "t_stat": float(t_asym),
        "p_value": float(p_asym),
        "q5_q1_ratio": float(q5q1_ratio),
    },
    "incremental_beyond_vix": {
        "r2_vix_only": float(r2_vix),
        "r2_vix_plus_em": float(r2_vix_em),
        "delta_r2": float(r2_vix_em - r2_vix),
        "F_stat": float(F_incr),
        "p_value": float(p_incr),
    },
    "portfolio_strategies": results,
    "oos_results": oos_results,
    "cross_correlation_peak": {
        "lag_days": int(peak_lag),
        "correlation": float(peak_corr),
    },
    "quintile_analysis": quintile_data,
    "crisis_case_studies": crisis_data,
}

results_path = os.path.join(os.path.dirname(__file__), "k338_em_contagion_results.json")
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to: {results_path}")
print(f"\n{'='*70}")
print("K338 COMPLETE")
print(f"{'='*70}")
