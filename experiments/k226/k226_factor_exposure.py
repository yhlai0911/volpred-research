"""
K226: Factor Exposure of 50/50+VT — What Risk Are You Taking?
==============================================================
[提出: 用戶, 執行: Claude]

Understanding the factor exposure of the 50/50 SPY/GLD + VT strategy:
- What factors drive its returns?
- How does VT overlay change factor loadings?
- Does VT reduce market beta during crises?

Portfolios:
  1. SPY B&H (100% SPY)
  2. 50/50 SPY/GLD B&H (static rebalancing)
  3. 50/50 SPY/GLD + VT (12/VIX vol targeting)

Factor proxies:
  - Market: SPY return
  - Gold: GLD return
  - Size: IWM - SPY (small cap premium)
  - Duration: TLT return (long-term bond)
  - Vol: dVIX / VIX (relative VIX change)

Methodology:
  1. Full-sample OLS regression of portfolio returns on factors
  2. Rolling 252-day beta estimation for time-varying exposure
  3. Crisis-period factor exposure comparison

Data: yfinance 2005-2024 daily
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
DATA_START = "2004-06-01"       # buffer for warm-up + IWM availability
BACKTEST_START = "2005-01-03"   # actual backtest start
BACKTEST_END = "2024-12-31"
VIX_TARGET = 12.0               # 12/VIX threshold
ROLLING_WINDOW = 252            # 1 year rolling window for betas
RF_ANNUAL = 0.02
RF_DAILY = RF_ANNUAL / 252

# Crisis periods
CRISES = {
    "GFC": ("2008-09-01", "2009-03-31"),
    "COVID": ("2020-02-15", "2020-04-30"),
    "Rate Hike 2022": ("2022-01-01", "2022-10-31"),
    "VIX Spike Aug 2015": ("2015-08-15", "2015-10-15"),
    "Volmageddon Feb 2018": ("2018-01-26", "2018-04-30"),
}

print("=" * 80)
print("K226: FACTOR EXPOSURE OF 50/50+VT — WHAT RISK ARE YOU TAKING?")
print("[提出: 用戶, 執行: Claude]")
print("=" * 80)

# ==================================================================
# DATA DOWNLOAD
# ==================================================================
print("\n[1] Downloading data from yfinance...")

tickers = {
    "SPY": "SPY",
    "GLD": "GLD",
    "VIX": "^VIX",
    "IWM": "IWM",
    "TLT": "TLT",
    "QQQ": "QQQ",
}

prices = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=DATA_START, end=BACKTEST_END,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    prices[name] = df["Close"].copy()
    print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Merge into single DataFrame
price_df = pd.DataFrame(prices)
price_df = price_df.dropna()
price_df = price_df.loc[BACKTEST_START:BACKTEST_END]
print(f"\n  Merged: {len(price_df)} trading days, {price_df.index[0].strftime('%Y-%m-%d')} to {price_df.index[-1].strftime('%Y-%m-%d')}")

# ==================================================================
# CONSTRUCT RETURNS AND FACTORS
# ==================================================================
print("\n[2] Constructing factor returns...")

ret = price_df.pct_change().dropna()

# Factor definitions
factors = pd.DataFrame(index=ret.index)
factors["Market"] = ret["SPY"]                              # Market factor
factors["Gold"] = ret["GLD"]                                # Gold factor
factors["Size"] = ret["IWM"] - ret["SPY"]                   # Size premium (small - large)
factors["Duration"] = ret["TLT"]                            # Duration / bond factor
factors["Vol"] = price_df["VIX"].pct_change().dropna()      # Relative VIX change (dVIX/VIX)

# Align
factors = factors.dropna()
ret = ret.loc[factors.index]
price_df_aligned = price_df.loc[factors.index]

print(f"  Factor matrix: {factors.shape[0]} obs x {factors.shape[1]} factors")
print(f"  Factor correlations:")
corr = factors.corr()
for i, f1 in enumerate(factors.columns):
    for j, f2 in enumerate(factors.columns):
        if j > i:
            print(f"    {f1:10s} vs {f2:10s}: {corr.loc[f1, f2]:+.3f}")

# ==================================================================
# CONSTRUCT PORTFOLIOS
# ==================================================================
print("\n[3] Constructing portfolio returns...")

# Portfolio 1: SPY B&H
port_spy = ret["SPY"].copy()

# Portfolio 2: 50/50 SPY/GLD B&H (daily rebalanced for simplicity)
port_5050 = 0.5 * ret["SPY"] + 0.5 * ret["GLD"]

# Portfolio 3: 50/50 SPY/GLD + VT (12/VIX)
# VT weight = min(12/VIX_{t-1}, 1.0), applied to next day's return
vix_lagged = price_df_aligned["VIX"].shift(1)  # use previous day's VIX
vt_weight = np.minimum(VIX_TARGET / vix_lagged, 1.0)
vt_weight = vt_weight.loc[factors.index]

# 50/50 underlying return
underlying_5050 = 0.5 * ret["SPY"] + 0.5 * ret["GLD"]
port_vt = vt_weight * underlying_5050 + (1 - vt_weight) * RF_DAILY

# Drop any NaN from lagged VIX
valid = ~(port_spy.isna() | port_5050.isna() | port_vt.isna())
port_spy = port_spy[valid]
port_5050 = port_5050[valid]
port_vt = port_vt[valid]
factors_clean = factors.loc[valid]
vt_weight_clean = vt_weight[valid]

portfolios = {
    "SPY B&H": port_spy,
    "50/50 B&H": port_5050,
    "50/50 + VT": port_vt,
}

# Quick performance summary
print(f"\n  Portfolio Performance Summary:")
print(f"  {'Portfolio':<15s} {'CAGR':>8s} {'Vol':>8s} {'Sharpe':>8s} {'MDD':>8s}")
print(f"  {'-'*47}")
for name, p in portfolios.items():
    cagr = (1 + p).prod() ** (252 / len(p)) - 1
    vol = p.std() * np.sqrt(252)
    sharpe = (p.mean() - RF_DAILY) / p.std() * np.sqrt(252)
    cum = (1 + p).cumprod()
    mdd = ((cum / cum.cummax()) - 1).min()
    print(f"  {name:<15s} {cagr:>7.1%} {vol:>7.1%} {sharpe:>8.2f} {mdd:>7.1%}")

# ==================================================================
# FULL-SAMPLE FACTOR REGRESSIONS
# ==================================================================
print("\n[4] Full-sample factor regressions...")
print("=" * 80)

def run_regression(y, X, name):
    """Run OLS regression with intercept, report coefficients and stats."""
    X_with_const = np.column_stack([np.ones(len(X)), X.values])
    factor_names = ["Alpha"] + list(X.columns)

    # OLS
    beta_hat = np.linalg.lstsq(X_with_const, y.values, rcond=None)[0]
    y_hat = X_with_const @ beta_hat
    resid = y.values - y_hat
    n, k = X_with_const.shape

    # R-squared
    ss_res = np.sum(resid ** 2)
    ss_tot = np.sum((y.values - y.values.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot
    r2_adj = 1 - (1 - r2) * (n - 1) / (n - k)

    # Standard errors (heteroskedasticity-robust, HC1)
    # Simple OLS SE for now (factor regressions typically use OLS)
    sigma2 = ss_res / (n - k)
    var_beta = sigma2 * np.linalg.inv(X_with_const.T @ X_with_const)
    se = np.sqrt(np.diag(var_beta))
    t_stats = beta_hat / se
    p_values = 2 * (1 - stats.t.cdf(np.abs(t_stats), df=n-k))

    # Annualized alpha
    alpha_annual = beta_hat[0] * 252 * 100  # in percent

    print(f"\n  --- {name} ---")
    print(f"  R² = {r2:.4f},  Adj R² = {r2_adj:.4f},  N = {n}")
    print(f"  Annualized Alpha = {alpha_annual:+.2f}% per year")
    print(f"  {'Factor':<12s} {'Beta':>8s} {'SE':>8s} {'t-stat':>8s} {'p-val':>8s} {'Sig':>5s}")
    print(f"  {'-'*49}")

    results = {}
    for i, fname in enumerate(factor_names):
        sig = ""
        if p_values[i] < 0.001: sig = "***"
        elif p_values[i] < 0.01: sig = "**"
        elif p_values[i] < 0.05: sig = "*"

        if fname == "Alpha":
            # Show alpha in bps/day for readability
            print(f"  {fname:<12s} {beta_hat[i]*10000:>7.2f}bp {se[i]*10000:>7.2f}bp {t_stats[i]:>8.2f} {p_values[i]:>8.4f} {sig:>5s}")
        else:
            print(f"  {fname:<12s} {beta_hat[i]:>8.4f} {se[i]:>8.4f} {t_stats[i]:>8.2f} {p_values[i]:>8.4f} {sig:>5s}")

        results[fname] = {
            "beta": float(beta_hat[i]),
            "se": float(se[i]),
            "t_stat": float(t_stats[i]),
            "p_value": float(p_values[i]),
        }

    results["R2"] = float(r2)
    results["R2_adj"] = float(r2_adj)
    results["alpha_annual_pct"] = float(alpha_annual)
    return results

regression_results = {}
for name, port_ret in portfolios.items():
    aligned_factors = factors_clean.loc[port_ret.index]
    regression_results[name] = run_regression(port_ret, aligned_factors, name)

# ==================================================================
# FACTOR EXPOSURE COMPARISON TABLE
# ==================================================================
print("\n\n[5] Factor Exposure Comparison (Beta)")
print("=" * 80)
print(f"  {'Factor':<12s}", end="")
for pname in portfolios.keys():
    print(f" {pname:>14s}", end="")
print(f" {'VT Effect':>14s}")
print(f"  {'-'*68}")

factor_names_list = ["Market", "Gold", "Size", "Duration", "Vol"]
for fname in factor_names_list:
    print(f"  {fname:<12s}", end="")
    betas = []
    for pname in portfolios.keys():
        b = regression_results[pname][fname]["beta"]
        t = regression_results[pname][fname]["t_stat"]
        sig = ""
        if abs(t) > 2.58: sig = "***"
        elif abs(t) > 1.96: sig = "**"
        elif abs(t) > 1.64: sig = "*"
        print(f" {b:>10.4f}{sig:<3s}", end="")
        betas.append(b)
    # VT effect = 50/50+VT minus 50/50 B&H
    vt_effect = betas[2] - betas[1]
    print(f" {vt_effect:>+13.4f}")

# Alpha comparison
print(f"\n  {'Alpha(%/yr)':<12s}", end="")
for pname in portfolios.keys():
    a = regression_results[pname]["alpha_annual_pct"]
    t = regression_results[pname]["Alpha"]["t_stat"]
    sig = ""
    if abs(t) > 2.58: sig = "***"
    elif abs(t) > 1.96: sig = "**"
    elif abs(t) > 1.64: sig = "*"
    print(f" {a:>10.2f}{sig:<3s}", end="")
a_vt = regression_results["50/50 + VT"]["alpha_annual_pct"] - regression_results["50/50 B&H"]["alpha_annual_pct"]
print(f" {a_vt:>+13.2f}")

print(f"\n  {'R²':<12s}", end="")
for pname in portfolios.keys():
    r2 = regression_results[pname]["R2"]
    print(f" {r2:>13.4f}", end="")
print()

# ==================================================================
# ROLLING 252-DAY BETAS (TIME-VARYING FACTOR EXPOSURE)
# ==================================================================
print("\n\n[6] Rolling 252-day factor betas (time-varying exposure)...")

def compute_rolling_betas(y, X, window=252):
    """Compute rolling OLS betas for each factor."""
    n = len(y)
    factor_names = list(X.columns)
    betas = pd.DataFrame(index=y.index, columns=["Alpha"] + factor_names, dtype=float)

    for i in range(window, n):
        y_win = y.iloc[i-window:i].values
        X_win = X.iloc[i-window:i].values
        X_const = np.column_stack([np.ones(window), X_win])
        try:
            b = np.linalg.lstsq(X_const, y_win, rcond=None)[0]
            betas.iloc[i] = b
        except:
            pass

    return betas.dropna()

rolling_betas = {}
for pname, port_ret in portfolios.items():
    aligned_f = factors_clean.loc[port_ret.index]
    rolling_betas[pname] = compute_rolling_betas(port_ret, aligned_f, ROLLING_WINDOW)
    print(f"  {pname}: {len(rolling_betas[pname])} rolling windows")

# ==================================================================
# ROLLING BETA STATISTICS
# ==================================================================
print("\n[7] Rolling Beta Statistics (252-day window)")
print("=" * 80)

for fname in factor_names_list:
    print(f"\n  --- {fname} Beta ---")
    print(f"  {'Portfolio':<15s} {'Mean':>8s} {'Std':>8s} {'Min':>8s} {'Max':>8s} {'Skew':>8s}")
    print(f"  {'-'*55}")
    for pname in portfolios.keys():
        rb = rolling_betas[pname][fname]
        print(f"  {pname:<15s} {rb.mean():>8.4f} {rb.std():>8.4f} {rb.min():>8.4f} {rb.max():>8.4f} {rb.skew():>8.2f}")

# ==================================================================
# CRISIS-PERIOD FACTOR EXPOSURE
# ==================================================================
print("\n\n[8] Crisis-Period Factor Exposure")
print("=" * 80)

crisis_results = {}
for crisis_name, (start, end) in CRISES.items():
    print(f"\n  === {crisis_name} ({start} to {end}) ===")

    mask = (factors_clean.index >= start) & (factors_clean.index <= end)
    n_days = mask.sum()

    if n_days < 20:
        print(f"  Only {n_days} days — skipping regression")
        continue

    crisis_results[crisis_name] = {}

    print(f"  ({n_days} trading days)")
    print(f"  {'Factor':<12s}", end="")
    for pname in portfolios.keys():
        print(f" {pname:>14s}", end="")
    print(f" {'VT Effect':>14s}")
    print(f"  {'-'*68}")

    for fname in factor_names_list:
        print(f"  {fname:<12s}", end="")
        betas_crisis = []
        for pname in portfolios.keys():
            rb = rolling_betas[pname]
            rb_crisis = rb.loc[(rb.index >= start) & (rb.index <= end)]
            if len(rb_crisis) > 0:
                b = rb_crisis[fname].mean()
            else:
                b = np.nan
            betas_crisis.append(b)
            print(f" {b:>14.4f}", end="")

        vt_eff = betas_crisis[2] - betas_crisis[1] if not (np.isnan(betas_crisis[1]) or np.isnan(betas_crisis[2])) else np.nan
        if not np.isnan(vt_eff):
            print(f" {vt_eff:>+14.4f}")
        else:
            print(f" {'N/A':>14s}")

    # VT weight during crisis (use date-range slicing to avoid length mismatch)
    vt_w_crisis = vt_weight_clean[(vt_weight_clean.index >= start) & (vt_weight_clean.index <= end)]
    if len(vt_w_crisis) > 0:
        print(f"\n  VT Weight: mean={vt_w_crisis.mean():.2%}, min={vt_w_crisis.min():.2%}, max={vt_w_crisis.max():.2%}")
        vix_crisis = price_df_aligned.loc[start:end, "VIX"]
        if len(vix_crisis) > 0:
            print(f"  VIX:       mean={vix_crisis.mean():.1f}, min={vix_crisis.min():.1f}, max={vix_crisis.max():.1f}")

    crisis_results[crisis_name] = {
        "n_days": int(n_days),
        "vt_weight_mean": float(vt_w_crisis.mean()) if len(vt_w_crisis) > 0 else None,
    }

# ==================================================================
# KEY QUESTION: DOES VT CHANGE FACTOR EXPOSURE?
# ==================================================================
print("\n\n[9] Key Analysis: How Does VT Change Factor Exposure?")
print("=" * 80)

# 9a. Full-sample beta differences
print("\n  (a) Full-sample beta differences (50/50+VT minus 50/50 B&H):")
print(f"  {'Factor':<12s} {'50/50 B&H':>10s} {'50/50+VT':>10s} {'Diff':>10s} {'% Change':>10s}")
print(f"  {'-'*52}")
for fname in factor_names_list:
    b_bh = regression_results["50/50 B&H"][fname]["beta"]
    b_vt = regression_results["50/50 + VT"][fname]["beta"]
    diff = b_vt - b_bh
    pct = (diff / abs(b_bh) * 100) if abs(b_bh) > 1e-8 else 0
    print(f"  {fname:<12s} {b_bh:>10.4f} {b_vt:>10.4f} {diff:>+10.4f} {pct:>+9.1f}%")

# 9b. Conditional analysis: high VIX vs low VIX
print("\n  (b) Conditional betas: High VIX (>20) vs Low VIX (<15):")
vix_vals = price_df_aligned.loc[factors_clean.index, "VIX"]
high_vix = vix_vals > 20
low_vix = vix_vals < 15

for regime_name, regime_mask in [("Low VIX (<15)", low_vix), ("High VIX (>20)", high_vix)]:
    regime_mask_aligned = regime_mask.reindex(factors_clean.index, fill_value=False)
    n_regime = regime_mask_aligned.sum()
    print(f"\n  {regime_name} ({n_regime} days):")

    if n_regime < 50:
        print(f"    Too few observations, skipping")
        continue

    factors_regime = factors_clean[regime_mask_aligned]

    print(f"  {'Factor':<12s} {'50/50 B&H':>10s} {'50/50+VT':>10s} {'Diff':>10s}")
    print(f"  {'-'*42}")

    for pname in ["50/50 B&H", "50/50 + VT"]:
        port_regime = portfolios[pname][regime_mask_aligned]

    # Run quick regressions for each
    for fname in factor_names_list:
        betas_regime = []
        for pname in ["50/50 B&H", "50/50 + VT"]:
            port_regime = portfolios[pname][regime_mask_aligned]
            X_regime = factors_regime.values
            X_const = np.column_stack([np.ones(len(X_regime)), X_regime])
            y_regime = port_regime.values
            try:
                b = np.linalg.lstsq(X_const, y_regime, rcond=None)[0]
                # Find the index of this factor
                fidx = list(factors_clean.columns).index(fname) + 1  # +1 for intercept
                betas_regime.append(b[fidx])
            except:
                betas_regime.append(np.nan)

        diff = betas_regime[1] - betas_regime[0]
        print(f"  {fname:<12s} {betas_regime[0]:>10.4f} {betas_regime[1]:>10.4f} {diff:>+10.4f}")

# 9c. VT weight and market beta relationship
print("\n  (c) Correlation between VT weight and rolling market beta:")
rb_vt = rolling_betas["50/50 + VT"]["Market"]
rb_bh = rolling_betas["50/50 B&H"]["Market"]
vt_w_aligned = vt_weight_clean.reindex(rb_vt.index)
valid_corr = ~(vt_w_aligned.isna() | rb_vt.isna())
if valid_corr.sum() > 50:
    corr_w_beta = np.corrcoef(vt_w_aligned[valid_corr], rb_vt[valid_corr])[0, 1]
    print(f"  corr(VT weight, Market Beta of 50/50+VT) = {corr_w_beta:+.3f}")

    corr_vix_beta_bh = np.corrcoef(
        vix_vals.reindex(rb_bh.index).dropna(),
        rb_bh.loc[vix_vals.reindex(rb_bh.index).dropna().index]
    )[0, 1]
    print(f"  corr(VIX level, Market Beta of 50/50 B&H) = {corr_vix_beta_bh:+.3f}")

# ==================================================================
# VT WEIGHT DISTRIBUTION AND FACTOR EXPOSURE BY REGIME
# ==================================================================
print("\n\n[10] VT Weight Distribution & Market Beta by VT Regime")
print("=" * 80)

vt_w_for_bins = vt_weight_clean.reindex(rolling_betas["50/50 + VT"].index).dropna()
common_idx = vt_w_for_bins.index.intersection(rolling_betas["50/50 + VT"].index)
vt_w_for_bins = vt_w_for_bins.loc[common_idx]

# Quintile analysis
quintiles = pd.qcut(vt_w_for_bins, 5, labels=["Q1(lowest)", "Q2", "Q3", "Q4", "Q5(highest)"])
print(f"\n  VT Weight Quintile Analysis:")
print(f"  {'Quintile':<15s} {'VT Weight':>10s} {'Mkt Beta':>10s} {'Gold Beta':>10s} {'Vol Beta':>10s} {'Return':>10s}")
print(f"  {'-'*65}")

for q in ["Q1(lowest)", "Q2", "Q3", "Q4", "Q5(highest)"]:
    q_mask = quintiles == q
    q_idx = common_idx[q_mask]

    avg_w = vt_w_for_bins[q_mask].mean()
    avg_mkt = rolling_betas["50/50 + VT"].loc[q_idx, "Market"].mean()
    avg_gold = rolling_betas["50/50 + VT"].loc[q_idx, "Gold"].mean()
    avg_vol = rolling_betas["50/50 + VT"].loc[q_idx, "Vol"].mean()
    avg_ret = portfolios["50/50 + VT"].reindex(q_idx).mean() * 252 * 100  # annualized %

    print(f"  {q:<15s} {avg_w:>9.1%} {avg_mkt:>10.4f} {avg_gold:>10.4f} {avg_vol:>10.4f} {avg_ret:>9.1f}%")

# ==================================================================
# VARIANCE DECOMPOSITION
# ==================================================================
print("\n\n[11] Variance Decomposition (% of portfolio variance explained by each factor)")
print("=" * 80)

def variance_decomposition(y, X, factor_names):
    """Decompose variance contribution of each factor."""
    X_const = np.column_stack([np.ones(len(X)), X.values])
    b = np.linalg.lstsq(X_const, y.values, rcond=None)[0]

    # Each factor's contribution = beta_i * Var(factor_i) + covariance terms
    # Simpler: marginal R² approach
    total_var = np.var(y.values)
    y_hat = X_const @ b
    r2_full = 1 - np.var(y.values - y_hat) / total_var

    # Drop-one approach for marginal contribution
    contributions = {}
    for i, fname in enumerate(factor_names):
        cols_without = [j for j in range(len(factor_names)) if j != i]
        X_reduced = np.column_stack([np.ones(len(X)), X.values[:, cols_without]])
        b_reduced = np.linalg.lstsq(X_reduced, y.values, rcond=None)[0]
        y_hat_reduced = X_reduced @ b_reduced
        r2_reduced = 1 - np.var(y.values - y_hat_reduced) / total_var

        marginal_r2 = r2_full - r2_reduced
        contributions[fname] = marginal_r2

    return contributions, r2_full

print(f"\n  {'Factor':<12s}", end="")
for pname in portfolios.keys():
    print(f" {pname:>14s}", end="")
print()
print(f"  {'-'*56}")

decomp_results = {}
for pname, port_ret in portfolios.items():
    aligned_f = factors_clean.loc[port_ret.index]
    contributions, r2_full = variance_decomposition(port_ret, aligned_f, factor_names_list)
    decomp_results[pname] = contributions

for fname in factor_names_list:
    print(f"  {fname:<12s}", end="")
    for pname in portfolios.keys():
        v = decomp_results[pname][fname]
        print(f" {v:>13.1%}", end="")
    print()

print(f"  {'Total R²':<12s}", end="")
for pname, port_ret in portfolios.items():
    aligned_f = factors_clean.loc[port_ret.index]
    _, r2_full = variance_decomposition(port_ret, aligned_f, factor_names_list)
    print(f" {r2_full:>13.1%}", end="")
print()

# ==================================================================
# STRUCTURAL BREAK TEST: FACTOR EXPOSURE STABILITY
# ==================================================================
print("\n\n[12] Factor Exposure Stability: 5-year sub-period analysis")
print("=" * 80)

periods = [
    ("2005-2009", "2005-01-01", "2009-12-31"),
    ("2010-2014", "2010-01-01", "2014-12-31"),
    ("2015-2019", "2015-01-01", "2019-12-31"),
    ("2020-2024", "2020-01-01", "2024-12-31"),
]

print(f"\n  Market Beta across sub-periods:")
print(f"  {'Period':<12s}", end="")
for pname in portfolios.keys():
    print(f" {pname:>14s}", end="")
print()
print(f"  {'-'*56}")

for period_name, start, end in periods:
    mask = (factors_clean.index >= start) & (factors_clean.index <= end)
    print(f"  {period_name:<12s}", end="")

    for pname, port_ret in portfolios.items():
        port_sub = port_ret[mask]
        f_sub = factors_clean[mask]
        if len(port_sub) < 50:
            print(f" {'N/A':>14s}", end="")
            continue

        X_const = np.column_stack([np.ones(len(f_sub)), f_sub.values])
        b = np.linalg.lstsq(X_const, port_sub.values, rcond=None)[0]
        mkt_beta = b[1]  # Market is first factor
        print(f" {mkt_beta:>14.4f}", end="")
    print()

# Gold beta across sub-periods
print(f"\n  Gold Beta across sub-periods:")
print(f"  {'Period':<12s}", end="")
for pname in portfolios.keys():
    print(f" {pname:>14s}", end="")
print()
print(f"  {'-'*56}")

for period_name, start, end in periods:
    mask = (factors_clean.index >= start) & (factors_clean.index <= end)
    print(f"  {period_name:<12s}", end="")

    for pname, port_ret in portfolios.items():
        port_sub = port_ret[mask]
        f_sub = factors_clean[mask]
        if len(port_sub) < 50:
            print(f" {'N/A':>14s}", end="")
            continue

        X_const = np.column_stack([np.ones(len(f_sub)), f_sub.values])
        b = np.linalg.lstsq(X_const, port_sub.values, rcond=None)[0]
        gold_beta = b[2]  # Gold is second factor
        print(f" {gold_beta:>14.4f}", end="")
    print()

# ==================================================================
# SUMMARY AND INTERPRETATION
# ==================================================================
print("\n\n" + "=" * 80)
print("SUMMARY: K226 Factor Exposure Analysis")
print("=" * 80)

# Extract key numbers
mkt_bh = regression_results["50/50 B&H"]["Market"]["beta"]
mkt_vt = regression_results["50/50 + VT"]["Market"]["beta"]
gold_bh = regression_results["50/50 B&H"]["Gold"]["beta"]
gold_vt = regression_results["50/50 + VT"]["Gold"]["beta"]
vol_bh = regression_results["50/50 B&H"]["Vol"]["beta"]
vol_vt = regression_results["50/50 + VT"]["Vol"]["beta"]

alpha_bh = regression_results["50/50 B&H"]["alpha_annual_pct"]
alpha_vt = regression_results["50/50 + VT"]["alpha_annual_pct"]

r2_spy = regression_results["SPY B&H"]["R2"]
r2_bh = regression_results["50/50 B&H"]["R2"]
r2_vt = regression_results["50/50 + VT"]["R2"]

mkt_reduction = (mkt_vt - mkt_bh) / mkt_bh * 100

print(f"""
  KEY FINDINGS:

  1. MARKET BETA REDUCTION BY VT:
     - 50/50 B&H market beta:   {mkt_bh:.4f}
     - 50/50 + VT market beta:  {mkt_vt:.4f}
     - Change:                  {mkt_reduction:+.1f}%
     → VT {"reduces" if mkt_reduction < 0 else "does not reduce"} market exposure

  2. GOLD EXPOSURE:
     - 50/50 B&H gold beta:     {gold_bh:.4f}
     - 50/50 + VT gold beta:    {gold_vt:.4f}
     → VT {"reduces" if gold_vt < gold_bh else "maintains/increases"} gold exposure proportionally

  3. VOLATILITY FACTOR:
     - 50/50 B&H vol beta:      {vol_bh:.4f}
     - 50/50 + VT vol beta:     {vol_vt:.4f}
     → VT {"makes the portfolio less sensitive" if abs(vol_vt) < abs(vol_bh) else "makes the portfolio more sensitive"} to VIX changes

  4. ALPHA (unexplained return):
     - 50/50 B&H alpha:         {alpha_bh:+.2f}%/yr
     - 50/50 + VT alpha:        {alpha_vt:+.2f}%/yr
     → VT {'generates' if alpha_vt > alpha_bh else 'reduces'} {abs(alpha_vt - alpha_bh):.2f}%/yr of factor-unexplained return

  5. MODEL FIT:
     - SPY B&H R²:              {r2_spy:.4f} (trivially high — SPY IS the market factor)
     - 50/50 B&H R²:            {r2_bh:.4f}
     - 50/50 + VT R²:           {r2_vt:.4f}
     → VT {'reduces' if r2_vt < r2_bh else 'maintains'} explainability — {'the VT mechanism introduces return variation not captured by static factors' if r2_vt < r2_bh else 'factor model still captures VT returns well'}

  6. MECHANISM:
     - VT weight = min(12/VIX, 1): when VIX>12, equity allocation shrinks
     - This mechanically reduces ALL factor exposures during high-vol periods
     - The key insight: VT is a CONDITIONAL beta strategy — it doesn't create alpha,
       it TIMES factor exposure (reducing it when vol is high)
     - The "alpha" (if any) comes from the asymmetry: VIX spikes are associated
       with negative returns, so reducing exposure then is beneficial
""")

# ==================================================================
# SAVE RESULTS
# ==================================================================
output = {
    "experiment": "K226",
    "title": "Factor Exposure of 50/50+VT",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "period": f"{BACKTEST_START} to {BACKTEST_END}",
    "n_obs": int(len(factors_clean)),
    "full_sample_regressions": {},
    "rolling_beta_stats": {},
    "variance_decomposition": decomp_results,
}

for pname in portfolios.keys():
    output["full_sample_regressions"][pname] = regression_results[pname]

for pname in portfolios.keys():
    rb = rolling_betas[pname]
    output["rolling_beta_stats"][pname] = {}
    for fname in factor_names_list:
        output["rolling_beta_stats"][pname][fname] = {
            "mean": float(rb[fname].mean()),
            "std": float(rb[fname].std()),
            "min": float(rb[fname].min()),
            "max": float(rb[fname].max()),
        }

results_path = "experiments/k226_factor_exposure_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\nResults saved to {results_path}")
print("K226 complete.")
