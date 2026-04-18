"""
K861: Climate Events and Market Volatility — Do Extreme Weather Events Predict Vol Spikes?

Research Question:
    Do publicly available climate/commodity proxy indicators predict equity market volatility?

Methodology:
    - Oil price shocks as proxy for climate-related supply disruptions
    - Event study: equity RV after oil shocks
    - Granger causality: oil RV → SPY RV
    - Asymmetry: positive vs negative oil shocks
    - Sector analysis: XLE, DBA vs SPY sensitivity
    - Regime shift: pre-2020 vs post-2020 (climate awareness era)

Data Sources:
    - yfinance: SPY, XLE, DBA (2005-01 to 2026-04)
    - FRED: DCOILWTICO (WTI crude oil price)

References:
    - Giglio, Maggiori, Stroebel, Weber (2021) "Climate Finance" Annual Review
    - Engle, Giglio, Kelly, Lee, Stroebel (2020) "Hedging Climate Change News" RFS
    - Hong, Li, Xu (2019) "Climate Risks and Market Efficiency" JFE
    - Kilian (2009) "Not All Oil Price Shocks Are Alike" AER
    - Sadorsky (1999) "Oil price shocks and stock market activity" Energy Economics

Error Log Rules Applied:
    - Sanity check: compute actual values, never hard-code
    - Harvey threshold |t| > 3.0 for significance claims
    - DM test: use volpred implementation if available
    - No lookahead: all signals use strictly past data

Author: [提出: Claude (跳躍式探索), 執行: Claude]
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
from statsmodels.tsa.stattools import grangercausalitytests
from pathlib import Path

warnings.filterwarnings("ignore")

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 70)
print("K861: Climate Events and Market Volatility")
print("=" * 70)

# Download equity data
tickers = {"SPY": "SPY", "XLE": "XLE", "DBA": "DBA"}
start_date = "2005-01-01"
end_date = "2026-04-05"

print("\n[1] Downloading data...")

equity_data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    equity_data[name] = df["Close"].copy()
    print(f"  {name}: {len(df)} observations, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Download oil data from FRED via pandas_datareader or yfinance proxy
# Using yfinance for CL=F (WTI futures) as more reliable than FRED download
try:
    import pandas_datareader.data as web
    oil_raw = web.DataReader("DCOILWTICO", "fred", start_date, end_date)
    oil_price = oil_raw["DCOILWTICO"].dropna()
    print(f"  OIL (FRED DCOILWTICO): {len(oil_price)} observations")
    oil_source = "FRED DCOILWTICO"
except Exception as e:
    print(f"  FRED download failed ({e}), using yfinance CL=F...")
    oil_df = yf.download("CL=F", start=start_date, end=end_date, progress=False)
    if isinstance(oil_df.columns, pd.MultiIndex):
        oil_df.columns = oil_df.columns.get_level_values(0)
    oil_price = oil_df["Close"].dropna()
    print(f"  OIL (yfinance CL=F): {len(oil_price)} observations")
    oil_source = "yfinance CL=F (WTI futures)"

# Align all data to common dates
price_df = pd.DataFrame(equity_data)
price_df["OIL"] = oil_price
price_df = price_df.dropna()
print(f"\n  Aligned dataset: {len(price_df)} observations, {price_df.index[0].strftime('%Y-%m-%d')} to {price_df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. COMPUTE RETURNS AND REALIZED VOLATILITY
# ============================================================
print("\n[2] Computing returns and realized volatility...")

# Log returns
returns = np.log(price_df / price_df.shift(1)).dropna()

# 22-day realized volatility (annualized)
rv_window = 22
rv = returns.rolling(rv_window).std() * np.sqrt(252)
rv = rv.dropna()

print(f"  Returns: {len(returns)} obs")
print(f"  RV ({rv_window}d): {len(rv)} obs")

# Descriptive statistics
print("\n  --- Descriptive Statistics (Annualized RV) ---")
for col in rv.columns:
    print(f"  {col}: mean={rv[col].mean():.4f}, std={rv[col].std():.4f}, "
          f"skew={rv[col].skew():.2f}, kurt={rv[col].kurt():.2f}")

# ============================================================
# 3. DEFINE OIL SHOCKS
# ============================================================
print("\n[3] Defining oil price shocks...")

oil_ret = returns["OIL"]
rolling_std = oil_ret.rolling(60).std()
rolling_mean = oil_ret.rolling(60).mean()

# Oil shock: |return| > 2 * rolling std
shock_threshold = 2.0
oil_shock = (oil_ret.abs() > shock_threshold * rolling_std).astype(int)
oil_shock = oil_shock.dropna()

# Positive shock (price spike) vs negative shock (price drop)
oil_spike = ((oil_ret > shock_threshold * rolling_std) & (oil_ret > 0)).astype(int)
oil_drop = ((oil_ret < -shock_threshold * rolling_std) & (oil_ret < 0)).astype(int)

# Align
common_idx = rv.index.intersection(oil_shock.index)
rv_aligned = rv.loc[common_idx]
oil_shock_aligned = oil_shock.loc[common_idx]
oil_spike_aligned = oil_spike.loc[common_idx]
oil_drop_aligned = oil_drop.loc[common_idx]
oil_ret_aligned = oil_ret.loc[common_idx]

n_shocks = oil_shock_aligned.sum()
n_spikes = oil_spike_aligned.sum()
n_drops = oil_drop_aligned.sum()
print(f"  Total oil shocks (|ret| > 2σ): {n_shocks} ({n_shocks/len(oil_shock_aligned)*100:.1f}%)")
print(f"    Positive spikes: {n_spikes}")
print(f"    Negative drops: {n_drops}")

# ============================================================
# 4. EVENT STUDY: EQUITY VOL AFTER OIL SHOCKS
# ============================================================
print("\n[4] Event Study: SPY RV after oil shocks...")

def event_study(rv_series, event_indicator, window_before=5, window_after=20):
    """Compute average RV around events."""
    event_dates = event_indicator[event_indicator == 1].index

    pre_rv = []
    post_rv = []
    change_rv = []

    for date in event_dates:
        loc = rv_series.index.get_loc(date)
        if loc >= window_before and loc + window_after < len(rv_series):
            pre = rv_series.iloc[loc-window_before:loc].mean()
            post = rv_series.iloc[loc+1:loc+window_after+1].mean()
            pre_rv.append(pre)
            post_rv.append(post)
            change_rv.append(post - pre)

    return np.array(pre_rv), np.array(post_rv), np.array(change_rv)

results = {}

# Event study for SPY
for asset in ["SPY", "XLE", "DBA"]:
    pre, post, change = event_study(rv_aligned[asset], oil_shock_aligned)

    # t-test: is the change significantly different from 0?
    if len(change) > 2:
        t_stat, p_val = stats.ttest_1samp(change, 0)
    else:
        t_stat, p_val = np.nan, np.nan

    results[f"event_study_{asset}"] = {
        "n_events": int(len(change)),
        "mean_pre_rv": float(np.mean(pre)),
        "mean_post_rv": float(np.mean(post)),
        "mean_change": float(np.mean(change)),
        "std_change": float(np.std(change)),
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "significant_harvey": bool(abs(t_stat) > 3.0)
    }

    sig = "***" if abs(t_stat) > 3.0 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
    print(f"  {asset}: pre-RV={np.mean(pre):.4f}, post-RV={np.mean(post):.4f}, "
          f"Δ={np.mean(change):+.4f}, t={t_stat:.3f} {sig}")

# ============================================================
# 5. ASYMMETRY: SPIKES vs DROPS
# ============================================================
print("\n[5] Asymmetry Analysis: Oil spikes vs drops effect on SPY RV...")

for shock_type, shock_indicator, label in [
    ("spike", oil_spike_aligned, "Oil Price SPIKE (positive)"),
    ("drop", oil_drop_aligned, "Oil Price DROP (negative)")
]:
    pre, post, change = event_study(rv_aligned["SPY"], shock_indicator)

    if len(change) > 2:
        t_stat, p_val = stats.ttest_1samp(change, 0)
    else:
        t_stat, p_val = np.nan, np.nan

    results[f"asymmetry_{shock_type}"] = {
        "n_events": int(len(change)),
        "mean_change": float(np.mean(change)) if len(change) > 0 else None,
        "t_stat": float(t_stat),
        "p_value": float(p_val),
        "significant_harvey": bool(abs(t_stat) > 3.0) if not np.isnan(t_stat) else False
    }

    sig = "***" if abs(t_stat) > 3.0 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
    if len(change) > 0:
        print(f"  {label}: n={len(change)}, Δ={np.mean(change):+.4f}, t={t_stat:.3f} {sig}")
    else:
        print(f"  {label}: n=0, insufficient data")

# Two-sample test: is spike effect different from drop effect?
pre_spike, post_spike, change_spike = event_study(rv_aligned["SPY"], oil_spike_aligned)
pre_drop, post_drop, change_drop = event_study(rv_aligned["SPY"], oil_drop_aligned)

if len(change_spike) > 2 and len(change_drop) > 2:
    t_diff, p_diff = stats.ttest_ind(change_spike, change_drop)
    results["asymmetry_diff_test"] = {
        "spike_mean_change": float(np.mean(change_spike)),
        "drop_mean_change": float(np.mean(change_drop)),
        "t_stat_diff": float(t_diff),
        "p_value_diff": float(p_diff),
        "significant_harvey": bool(abs(t_diff) > 3.0)
    }
    print(f"\n  Spike vs Drop difference: t={t_diff:.3f}, p={p_diff:.4f}")
else:
    results["asymmetry_diff_test"] = {"note": "insufficient events for comparison"}

# ============================================================
# 6. GRANGER CAUSALITY: OIL RV → EQUITY RV
# ============================================================
print("\n[6] Granger Causality: Oil RV → SPY RV...")

max_lag = 5
granger_results = {}

for asset in ["SPY", "XLE", "DBA"]:
    gc_data = pd.DataFrame({
        "equity_rv": rv_aligned[asset],
        "oil_rv": rv_aligned["OIL"]
    }).dropna()

    print(f"\n  {asset} (n={len(gc_data)}):")

    try:
        gc_test = grangercausalitytests(gc_data[["equity_rv", "oil_rv"]], maxlag=max_lag, verbose=False)

        asset_gc = {}
        for lag in range(1, max_lag + 1):
            f_stat = gc_test[lag][0]["ssr_ftest"][0]
            p_val = gc_test[lag][0]["ssr_ftest"][1]
            sig = "***" if p_val < 0.001 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
            print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f} {sig}")
            asset_gc[f"lag_{lag}"] = {
                "f_stat": float(f_stat),
                "p_value": float(p_val),
                "significant_005": bool(p_val < 0.05)
            }

        granger_results[asset] = asset_gc

    except Exception as e:
        print(f"    Error: {e}")
        granger_results[asset] = {"error": str(e)}

results["granger_causality"] = granger_results

# Also test reverse: SPY RV → Oil RV
print("\n  Reverse test: SPY RV → Oil RV")
gc_data_rev = pd.DataFrame({
    "oil_rv": rv_aligned["OIL"],
    "spy_rv": rv_aligned["SPY"]
}).dropna()

try:
    gc_rev = grangercausalitytests(gc_data_rev[["oil_rv", "spy_rv"]], maxlag=max_lag, verbose=False)
    reverse_gc = {}
    for lag in range(1, max_lag + 1):
        f_stat = gc_rev[lag][0]["ssr_ftest"][0]
        p_val = gc_rev[lag][0]["ssr_ftest"][1]
        sig = "***" if p_val < 0.001 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
        print(f"    Lag {lag}: F={f_stat:.3f}, p={p_val:.4f} {sig}")
        reverse_gc[f"lag_{lag}"] = {"f_stat": float(f_stat), "p_value": float(p_val)}
    results["granger_reverse_spy_to_oil"] = reverse_gc
except Exception as e:
    results["granger_reverse_spy_to_oil"] = {"error": str(e)}

# ============================================================
# 7. CORRELATION ANALYSIS
# ============================================================
print("\n[7] Correlation Analysis: Oil RV vs Equity RV...")

for asset in ["SPY", "XLE", "DBA"]:
    corr_pearson = rv_aligned[asset].corr(rv_aligned["OIL"])
    corr_spearman = rv_aligned[asset].corr(rv_aligned["OIL"], method="spearman")

    # Bootstrap CI for Spearman
    n_boot = 10000
    boot_corrs = []
    n = len(rv_aligned)
    for _ in range(n_boot):
        idx = np.random.choice(n, n, replace=True)
        bc = stats.spearmanr(rv_aligned[asset].iloc[idx], rv_aligned["OIL"].iloc[idx])[0]
        boot_corrs.append(bc)
    ci_lo, ci_hi = np.percentile(boot_corrs, [2.5, 97.5])

    results[f"correlation_{asset}_oil"] = {
        "pearson": float(corr_pearson),
        "spearman": float(corr_spearman),
        "spearman_95ci": [float(ci_lo), float(ci_hi)]
    }

    print(f"  {asset}-OIL: Pearson={corr_pearson:.4f}, Spearman={corr_spearman:.4f} "
          f"[{ci_lo:.4f}, {ci_hi:.4f}]")

# ============================================================
# 8. REGIME ANALYSIS: PRE-2020 vs POST-2020
# ============================================================
print("\n[8] Regime Analysis: Pre-2020 vs Post-2020...")

cutoff = pd.Timestamp("2020-01-01")

for period_name, mask in [("pre_2020", rv_aligned.index < cutoff),
                          ("post_2020", rv_aligned.index >= cutoff)]:
    rv_sub = rv_aligned.loc[mask]
    shock_sub = oil_shock_aligned.loc[mask]

    if shock_sub.sum() < 5:
        print(f"  {period_name}: too few shocks ({shock_sub.sum()}), skipping")
        results[f"regime_{period_name}"] = {"note": f"too few shocks: {int(shock_sub.sum())}"}
        continue

    pre, post, change = event_study(rv_sub["SPY"], shock_sub)

    if len(change) > 2:
        t_stat, p_val = stats.ttest_1samp(change, 0)
    else:
        t_stat, p_val = np.nan, np.nan

    # Correlation in this period
    corr = rv_sub["SPY"].corr(rv_sub["OIL"], method="spearman")

    results[f"regime_{period_name}"] = {
        "n_obs": int(len(rv_sub)),
        "n_shocks": int(shock_sub.sum()),
        "mean_spy_rv": float(rv_sub["SPY"].mean()),
        "mean_oil_rv": float(rv_sub["OIL"].mean()),
        "event_study_change": float(np.mean(change)) if len(change) > 0 else None,
        "event_study_t": float(t_stat),
        "event_study_p": float(p_val),
        "spy_oil_spearman": float(corr),
        "significant_harvey": bool(abs(t_stat) > 3.0) if not np.isnan(t_stat) else False
    }

    sig = "***" if abs(t_stat) > 3.0 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
    print(f"  {period_name}: n_shocks={shock_sub.sum()}, Δ_RV={np.mean(change):+.4f}, "
          f"t={t_stat:.3f} {sig}, SPY-OIL ρ={corr:.4f}")

# ============================================================
# 9. ROLLING CORRELATION: SPY RV vs OIL RV
# ============================================================
print("\n[9] Rolling Correlation (252d): SPY RV vs OIL RV...")

rolling_corr = rv_aligned["SPY"].rolling(252).corr(rv_aligned["OIL"]).dropna()
results["rolling_corr_stats"] = {
    "mean": float(rolling_corr.mean()),
    "std": float(rolling_corr.std()),
    "min": float(rolling_corr.min()),
    "max": float(rolling_corr.max()),
    "pct_positive": float((rolling_corr > 0).mean() * 100),
    "recent_252d": float(rolling_corr.iloc[-1]) if len(rolling_corr) > 0 else None
}
print(f"  Mean={rolling_corr.mean():.4f}, Std={rolling_corr.std():.4f}")
print(f"  Range: [{rolling_corr.min():.4f}, {rolling_corr.max():.4f}]")
print(f"  % Positive: {(rolling_corr > 0).mean()*100:.1f}%")
print(f"  Recent (last 252d): {rolling_corr.iloc[-1]:.4f}")

# ============================================================
# 10. OIL VOL REGIME → FORWARD EQUITY VOL
# ============================================================
print("\n[10] Oil Vol Regime → Forward SPY RV...")

# High oil vol = above median
oil_rv_median = rv_aligned["OIL"].median()
high_oil_vol = rv_aligned["OIL"] > oil_rv_median

# Forward SPY RV (next 22 days) — NO LOOKAHEAD: use shift(-22) carefully
# This means: when oil vol is high TODAY, what is SPY RV 22 days LATER?
forward_spy_rv = rv_aligned["SPY"].shift(-22)  # shift back = future value

# Remove last 22 rows (no forward data)
valid_idx = forward_spy_rv.dropna().index
high_mask = high_oil_vol.loc[valid_idx]
forward_rv = forward_spy_rv.loc[valid_idx]

rv_high = forward_rv[high_mask]
rv_low = forward_rv[~high_mask]

t_regime, p_regime = stats.ttest_ind(rv_high, rv_low)
diff = rv_high.mean() - rv_low.mean()

results["oil_vol_regime_prediction"] = {
    "n_high": int(len(rv_high)),
    "n_low": int(len(rv_low)),
    "mean_forward_rv_high_oil": float(rv_high.mean()),
    "mean_forward_rv_low_oil": float(rv_low.mean()),
    "difference": float(diff),
    "t_stat": float(t_regime),
    "p_value": float(p_regime),
    "significant_harvey": bool(abs(t_regime) > 3.0),
    "note": "Forward RV = SPY 22d RV shifted 22 days ahead. High oil vol = above median."
}

sig = "***" if abs(t_regime) > 3.0 else ("**" if p_regime < 0.01 else ("*" if p_regime < 0.05 else ""))
print(f"  High oil vol → forward SPY RV: {rv_high.mean():.4f}")
print(f"  Low oil vol → forward SPY RV:  {rv_low.mean():.4f}")
print(f"  Difference: {diff:+.4f}, t={t_regime:.3f} {sig}")

# ============================================================
# 11. SECTOR SENSITIVITY
# ============================================================
print("\n[11] Sector Sensitivity: Beta of equity RV on oil RV...")

for asset in ["SPY", "XLE", "DBA"]:
    # OLS: equity_rv = α + β * oil_rv + ε
    from numpy.polynomial.polynomial import polyfit

    x = rv_aligned["OIL"].values
    y = rv_aligned[asset].values

    # Manual OLS for proper t-stats
    X = np.column_stack([np.ones(len(x)), x])
    beta_hat = np.linalg.lstsq(X, y, rcond=None)[0]
    y_hat = X @ beta_hat
    resid = y - y_hat
    n_obs = len(y)
    se = np.sqrt(np.sum(resid**2) / (n_obs - 2) * np.linalg.inv(X.T @ X).diagonal())
    t_stats = beta_hat / se

    results[f"sensitivity_{asset}"] = {
        "alpha": float(beta_hat[0]),
        "beta_oil_rv": float(beta_hat[1]),
        "t_stat_beta": float(t_stats[1]),
        "r_squared": float(1 - np.sum(resid**2) / np.sum((y - y.mean())**2)),
        "significant_harvey": bool(abs(t_stats[1]) > 3.0)
    }

    sig = "***" if abs(t_stats[1]) > 3.0 else ""
    print(f"  {asset}: β={beta_hat[1]:.4f} (t={t_stats[1]:.3f}{sig}), R²={1-np.sum(resid**2)/np.sum((y-y.mean())**2):.4f}")

# ============================================================
# 12. SANITY CHECKS
# ============================================================
print("\n[12] Sanity Checks...")

# Check 1: Oil return distribution
print(f"  Oil daily return: mean={oil_ret.mean():.6f}, std={oil_ret.std():.4f}")
print(f"  SPY daily return: mean={returns['SPY'].mean():.6f}, std={returns['SPY'].std():.4f}")

# Check 2: Verify shock count is reasonable (should be ~5% of obs)
pct_shocks = n_shocks / len(oil_shock_aligned) * 100
print(f"  Oil shocks as % of days: {pct_shocks:.1f}% (expect ~5%)")
assert 1.0 < pct_shocks < 15.0, f"Shock frequency {pct_shocks}% is outside reasonable range"

# Check 3: RV levels are reasonable (10-30% annualized for SPY)
spy_rv_mean = rv_aligned["SPY"].mean()
print(f"  SPY mean RV: {spy_rv_mean:.4f} (expect 0.10-0.30)")
assert 0.05 < spy_rv_mean < 0.50, f"SPY RV {spy_rv_mean} is unreasonable"

# Check 4: Verify we used actual computed values, not hard-coded
print(f"  [SANITY] SPY-OIL Spearman computed: {results['correlation_SPY_oil']['spearman']:.6f}")
print(f"  [SANITY] Event study SPY n_events: {results['event_study_SPY']['n_events']}")
print(f"  [SANITY] Granger lag-1 SPY p-value: {results['granger_causality']['SPY']['lag_1']['p_value']:.6f}")

# ============================================================
# 13. SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K861 Climate Proxy (Oil) → Equity Volatility")
print("=" * 70)

# Compile key findings
findings = []

# Event study
es = results["event_study_SPY"]
if es["significant_harvey"]:
    findings.append(f"[SIGNIFICANT] Oil shocks predict SPY vol changes (Δ={es['mean_change']:+.4f}, t={es['t_stat']:.2f})")
else:
    findings.append(f"[WEAK/NULL] Oil shock event study: Δ={es['mean_change']:+.4f}, t={es['t_stat']:.2f} (below Harvey |t|>3.0)")

# Granger
gc_spy = results["granger_causality"].get("SPY", {})
any_gc_sig = any(gc_spy.get(f"lag_{i}", {}).get("significant_005", False) for i in range(1, 6))
findings.append(f"Granger causality (Oil→SPY): {'YES at some lags' if any_gc_sig else 'NO at any lag'}")

# Asymmetry
asym_spike = results.get("asymmetry_spike", {})
asym_drop = results.get("asymmetry_drop", {})
if asym_spike.get("mean_change") and asym_drop.get("mean_change"):
    findings.append(f"Asymmetry: Spike Δ={asym_spike['mean_change']:+.4f} vs Drop Δ={asym_drop['mean_change']:+.4f}")

# Regime
pre = results.get("regime_pre_2020", {})
post = results.get("regime_post_2020", {})
if pre.get("spy_oil_spearman") and post.get("spy_oil_spearman"):
    findings.append(f"Regime shift: SPY-OIL ρ pre-2020={pre['spy_oil_spearman']:.3f}, post-2020={post['spy_oil_spearman']:.3f}")

# Oil vol regime
ovr = results["oil_vol_regime_prediction"]
findings.append(f"Oil vol regime → forward SPY RV: diff={ovr['difference']:+.4f}, t={ovr['t_stat']:.2f} "
               f"{'(Harvey sig)' if ovr['significant_harvey'] else '(NOT Harvey sig)'}")

# Sensitivity
for asset in ["SPY", "XLE", "DBA"]:
    s = results[f"sensitivity_{asset}"]
    findings.append(f"Sensitivity {asset}: β_oil={s['beta_oil_rv']:.4f}, R²={s['r_squared']:.4f}")

for i, f in enumerate(findings, 1):
    print(f"  {i}. {f}")

# ============================================================
# 14. SAVE RESULTS
# ============================================================
output = {
    "experiment_id": "K861",
    "title": "Climate Events and Market Volatility: Oil Shocks as Climate Proxy",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_sources": {
        "equities": "yfinance (SPY, XLE, DBA)",
        "oil": oil_source,
        "period": f"{price_df.index[0].strftime('%Y-%m-%d')} to {price_df.index[-1].strftime('%Y-%m-%d')}",
        "n_observations": int(len(price_df))
    },
    "methodology": {
        "rv_window": rv_window,
        "shock_threshold": f"|return| > {shock_threshold}x rolling 60d std",
        "granger_max_lag": max_lag,
        "bootstrap_n": 10000,
        "significance_threshold": "Harvey (2016) |t| > 3.0"
    },
    "results": results,
    "findings_summary": findings,
    "limitations": [
        "Oil price is a PROXY for climate events, not direct weather data",
        "Oil shocks can be geopolitical (Iran, Russia) not climate-related",
        "Realized vol uses overlapping windows (22d) — serial correlation",
        "No control for other macro factors (VIX, rates, recession)",
        "DBA may have structural issues similar to USO (contango/roll)",
        "Forward RV analysis uses shift(-22) which is technically known at event time"
    ],
    "references": [
        "Giglio, Maggiori, Stroebel, Weber (2021) Climate Finance, Annual Review",
        "Engle, Giglio, Kelly, Lee, Stroebel (2020) Hedging Climate Change News, RFS",
        "Hong, Li, Xu (2019) Climate Risks and Market Efficiency, JFE",
        "Kilian (2009) Not All Oil Price Shocks Are Alike, AER",
        "Sadorsky (1999) Oil price shocks and stock market activity, Energy Economics",
        "Harvey (2016) ...and the cross-section of expected returns, RFS"
    ],
    "prior_related_work": [
        "K25 series (Iran crisis 2026): oil-equity transmission is contemporaneous, no Granger causality",
        "Commodity leverage asymmetry experiments: oil has standard leverage (γ=+0.10)"
    ]
}

results_path = Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k861_results.json")
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to {results_path}")
print("\nK861 COMPLETE.")
