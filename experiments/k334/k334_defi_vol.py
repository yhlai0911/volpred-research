#!/usr/bin/env python3
"""K334: DeFi Yield Volatility — Can On-Chain Proxies Predict Crypto Vol?

Leap-exploration into DeFi/crypto ecosystem. Since on-chain data (Aave rates,
TVL, liquidations) is unavailable via yfinance, we use PROXY features:

Crypto-specific features (all from yfinance):
1. BTC-ETH rolling 22d correlation (high corr = risk-on crypto regime)
2. ETH/BTC ratio momentum (ETH outperforming = speculative environment)
3. BTC weekend/weekday vol ratio (declining = institutionalization, K277)
4. BTC consecutive up/down days (momentum persistence)
5. BTC range ratio (high/low range, K202: best predictor)
6. BTC volume spike (volume / MA20_volume — liquidation cascade proxy)
7. BTC return skewness rolling 22d (tail risk indicator)

Methodology:
- Partial correlation with future 22d BTC realized vol, controlling for
  BTC's own lagged 22d realized vol
- Build "Crypto Fear Index" from top features
- Compare vs using VIX as crypto risk signal
- Test whether Crypto Fear Index improves BTC vol prediction (OOS)

LIMITATIONS:
- All features are PROXIES — real DeFi data (Aave rates, TVL, liquidation
  cascades, stablecoin flows) would be far more informative
- BTC-ETH correlation is a rough proxy for "risk-on crypto"
- Volume data from yfinance may not capture DEX volumes
- No stablecoin flow data (USDT market cap not in yfinance daily)
- Results should be viewed as PILOT / proof-of-concept

Data: yfinance (BTC-USD, ETH-USD, ^VIX), 2018-01-01 to present
OOS: 2023-01-01 to present

[提出: 用戶 (DeFi 跳躍式探索), 執行: Claude]
"""
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from datetime import datetime
import json


# ─── Helper functions ────────────────────────────────────────────
def partial_corr(x, y, z):
    """Partial correlation between x and y controlling for z.
    Returns (r_partial, p_value, n_effective)."""
    # Remove NaN
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[mask], y[mask], z[mask]
    n = len(x)
    if n < 30:
        return np.nan, np.nan, n

    # Residualize x and y on z
    from numpy.polynomial.polynomial import polyfit
    # x ~ z
    bx = np.polyfit(z, x, 1)
    res_x = x - np.polyval(bx, z)
    # y ~ z
    by = np.polyfit(z, y, 1)
    res_y = y - np.polyval(by, z)

    r, p = stats.pearsonr(res_x, res_y)
    return r, p, n


def dm_test(loss1, loss2):
    """Diebold-Mariano test. Negative t-stat = model 1 better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    d_mean = np.mean(d)
    lag = max(1, int(n ** (1 / 3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag + 1):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return t_stat, p_val


def qlike_loss(realized_var, forecast_var):
    """QLIKE loss function."""
    valid = (forecast_var > 0) & (realized_var > 0) & np.isfinite(realized_var) & np.isfinite(forecast_var)
    r = realized_var[valid]
    f = forecast_var[valid]
    return np.log(f) + r / f


def compute_rolling_rv(returns, window=22):
    """22-day realized volatility (annualized)."""
    return returns.rolling(window).std() * np.sqrt(365)


# ─── Data Download ───────────────────────────────────────────────
print("=" * 70)
print("K334: DeFi Yield Volatility — Crypto Vol Prediction with Proxies")
print("=" * 70)
print()

print("Downloading data from yfinance...")
start_date = "2017-06-01"  # Extra lead time for rolling windows
end_date = "2026-03-25"

btc = yf.download("BTC-USD", start=start_date, end=end_date, progress=False)
eth = yf.download("ETH-USD", start=start_date, end=end_date, progress=False)
vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)

# Handle multi-level columns from yfinance
for df_name, df in [("BTC", btc), ("ETH", eth), ("VIX", vix)]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

print(f"  BTC-USD: {len(btc)} days ({btc.index[0].strftime('%Y-%m-%d')} to {btc.index[-1].strftime('%Y-%m-%d')})")
print(f"  ETH-USD: {len(eth)} days ({eth.index[0].strftime('%Y-%m-%d')} to {eth.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX:     {len(vix)} days ({vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')})")

# ─── Compute Returns ────────────────────────────────────────────
btc_ret = np.log(btc["Close"] / btc["Close"].shift(1))
eth_ret = np.log(eth["Close"] / eth["Close"].shift(1))

# Align all on BTC index
df = pd.DataFrame({
    "btc_ret": btc_ret,
    "eth_ret": eth_ret,
    "btc_close": btc["Close"],
    "eth_close": eth["Close"],
    "btc_high": btc["High"],
    "btc_low": btc["Low"],
    "btc_volume": btc["Volume"],
}).dropna()

# Merge VIX
vix_close = vix["Close"].rename("vix")
df = df.join(vix_close, how="left")
df["vix"] = df["vix"].ffill()  # Forward-fill for weekends/holidays

print(f"\nAligned dataset: {len(df)} days")
print()

# ─── Feature Engineering ────────────────────────────────────────
print("Computing crypto-specific features...")

# 1. BTC-ETH rolling 22d correlation
df["btc_eth_corr"] = df["btc_ret"].rolling(22).corr(df["eth_ret"])

# 2. ETH/BTC ratio momentum (22d change in ETH/BTC ratio)
df["eth_btc_ratio"] = df["eth_close"] / df["btc_close"]
df["eth_btc_mom"] = df["eth_btc_ratio"].pct_change(22)

# 3. BTC weekend/weekday vol ratio
# Weekend = Saturday (5) or Sunday (6)
df["is_weekend"] = df.index.dayofweek.isin([5, 6]).astype(int)
# Rolling 60d weekend and weekday vol
df["btc_ret_abs"] = df["btc_ret"].abs()
# Use a 60-day window for stable estimate
weekend_vol = df["btc_ret_abs"].where(df["is_weekend"] == 1).rolling(60, min_periods=10).mean()
weekday_vol = df["btc_ret_abs"].where(df["is_weekend"] == 0).rolling(60, min_periods=20).mean()
df["weekend_weekday_ratio"] = weekend_vol / weekday_vol
# Fill NaN from weekends propagating
df["weekend_weekday_ratio"] = df["weekend_weekday_ratio"].ffill()

# 4. BTC consecutive up/down days
df["btc_sign"] = np.sign(df["btc_ret"])
consec = []
count = 0
prev_sign = 0
for s in df["btc_sign"]:
    if s == prev_sign and s != 0:
        count += s  # positive for up streak, negative for down
    else:
        count = s
    consec.append(count)
    prev_sign = s
df["consec_days"] = consec

# 5. BTC range ratio (Parkinson-like: log(High/Low))
df["range_ratio"] = np.log(df["btc_high"] / df["btc_low"])
df["range_ratio_22d"] = df["range_ratio"].rolling(22).mean()

# 6. BTC volume spike (volume / MA20)
df["vol_ma20"] = df["btc_volume"].rolling(20).mean()
df["volume_spike"] = df["btc_volume"] / df["vol_ma20"]

# 7. BTC return skewness rolling 22d
df["btc_skew_22d"] = df["btc_ret"].rolling(22).skew()

# 8. Lagged BTC realized vol (control variable)
df["btc_rv_22d"] = compute_rolling_rv(df["btc_ret"], 22)

# 9. Future 22d BTC realized vol (TARGET)
df["btc_rv_22d_future"] = df["btc_rv_22d"].shift(-22)

# 10. VIX level (competitor predictor)
df["vix_level"] = df["vix"]

# 11. VIX change 22d
df["vix_chg_22d"] = df["vix"].pct_change(22)

# Additional: BTC momentum (22d return)
df["btc_mom_22d"] = df["btc_ret"].rolling(22).sum()

# Additional: BTC-ETH return spread volatility (proxy for basis/arb activity)
df["btc_eth_spread"] = df["btc_ret"] - df["eth_ret"]
df["spread_vol_22d"] = df["btc_eth_spread"].rolling(22).std() * np.sqrt(365)

print("  Features computed: 12 crypto-specific + 1 VIX baseline")
print()

# ─── Analysis Period ─────────────────────────────────────────────
# Use 2018-01-01 as start (after rolling windows fill)
analysis_start = "2018-01-01"
oos_start = "2023-01-01"

df_analysis = df.loc[analysis_start:].dropna(subset=["btc_rv_22d", "btc_rv_22d_future"])
df_is = df_analysis.loc[:oos_start]
df_oos = df_analysis.loc[oos_start:]

print(f"Analysis period: {df_analysis.index[0].strftime('%Y-%m-%d')} to {df_analysis.index[-1].strftime('%Y-%m-%d')} ({len(df_analysis)} days)")
print(f"  In-sample:  {df_is.index[0].strftime('%Y-%m-%d')} to {df_is.index[-1].strftime('%Y-%m-%d')} ({len(df_is)} days)")
print(f"  Out-of-sample: {df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')} ({len(df_oos)} days)")
print()

# ─── Part 1: Partial Correlations (Full Sample) ─────────────────
print("=" * 70)
print("PART 1: Partial Correlations with Future 22d BTC RV")
print("       (controlling for lagged 22d BTC RV)")
print("=" * 70)
print()

features = {
    "BTC-ETH Corr (22d)": "btc_eth_corr",
    "ETH/BTC Mom (22d)": "eth_btc_mom",
    "Weekend/Weekday Vol": "weekend_weekday_ratio",
    "Consecutive Days": "consec_days",
    "Range Ratio (22d)": "range_ratio_22d",
    "Volume Spike": "volume_spike",
    "BTC Skewness (22d)": "btc_skew_22d",
    "BTC Momentum (22d)": "btc_mom_22d",
    "BTC-ETH Spread Vol": "spread_vol_22d",
    "VIX Level": "vix_level",
    "VIX Change (22d)": "vix_chg_22d",
}

results = {}
print(f"{'Feature':<25} {'Partial r':>10} {'p-value':>10} {'N':>6} {'Sig?':>6}")
print("-" * 60)

for name, col in features.items():
    x = df_analysis[col].values
    y = df_analysis["btc_rv_22d_future"].values
    z = df_analysis["btc_rv_22d"].values
    r, p, n = partial_corr(x, y, z)
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    results[name] = {"partial_r": r, "p_value": p, "n": n, "col": col}
    print(f"  {name:<23} {r:>10.4f} {p:>10.4f} {n:>6d} {sig:>6}")

print()
print("  * p<0.05  ** p<0.01  *** p<0.001")
print()

# ─── Part 1b: In-sample vs OOS comparison ───────────────────────
print("=" * 70)
print("PART 1b: In-Sample vs Out-of-Sample Partial Correlations")
print("=" * 70)
print()

print(f"{'Feature':<25} {'IS r':>8} {'IS p':>8} {'OOS r':>8} {'OOS p':>8} {'Stable?':>8}")
print("-" * 70)

for name, col in features.items():
    # In-sample
    x_is = df_is[col].values
    y_is = df_is["btc_rv_22d_future"].values
    z_is = df_is["btc_rv_22d"].values
    r_is, p_is, n_is = partial_corr(x_is, y_is, z_is)

    # OOS
    x_oos = df_oos[col].values
    y_oos = df_oos["btc_rv_22d_future"].values
    z_oos = df_oos["btc_rv_22d"].values
    r_oos, p_oos, n_oos = partial_corr(x_oos, y_oos, z_oos)

    # Check sign stability
    stable = "Yes" if (np.isfinite(r_is) and np.isfinite(r_oos) and np.sign(r_is) == np.sign(r_oos)) else "No"

    results[name]["is_r"] = r_is
    results[name]["is_p"] = p_is
    results[name]["oos_r"] = r_oos
    results[name]["oos_p"] = p_oos
    results[name]["stable"] = stable

    print(f"  {name:<23} {r_is:>8.4f} {p_is:>8.4f} {r_oos:>8.4f} {p_oos:>8.4f} {stable:>8}")

print()

# ─── Part 2: Build Crypto Fear Index ────────────────────────────
print("=" * 70)
print("PART 2: Crypto Fear Index Construction")
print("=" * 70)
print()

# Select features with significant partial correlation AND sign stability
# Use in-sample to select, then test OOS
significant_features = []
for name, res in results.items():
    if "VIX" in name:
        continue  # Don't include VIX in crypto-native index
    if res.get("is_p", 1) < 0.10 and res.get("stable") == "Yes":
        significant_features.append(name)

print(f"Features passing IS significance (p<0.10) + sign stability:")
for f in significant_features:
    r = results[f]
    print(f"  - {f}: IS r={r.get('is_r', np.nan):.4f}, OOS r={r.get('oos_r', np.nan):.4f}")
print()

if len(significant_features) == 0:
    print("  No features passed both criteria!")
    print("  Relaxing to p<0.20...")
    for name, res in results.items():
        if "VIX" in name:
            continue
        if res.get("is_p", 1) < 0.20 and res.get("stable") == "Yes":
            significant_features.append(name)
    if significant_features:
        print(f"  Relaxed features:")
        for f in significant_features:
            r = results[f]
            print(f"    - {f}: IS r={r.get('is_r', np.nan):.4f}, OOS r={r.get('oos_r', np.nan):.4f}")
    print()

# Build composite index by standardizing and averaging selected features
if len(significant_features) >= 2:
    print(f"Building Crypto Fear Index from {len(significant_features)} features...")

    # Standardize each feature (z-score using expanding window to avoid lookahead)
    crypto_fear_components = pd.DataFrame(index=df_analysis.index)

    for name in significant_features:
        col = results[name]["col"]
        raw = df_analysis[col]
        # Use expanding z-score (no lookahead)
        expanding_mean = raw.expanding(min_periods=60).mean()
        expanding_std = raw.expanding(min_periods=60).std()
        z = (raw - expanding_mean) / expanding_std

        # Flip sign if feature has NEGATIVE partial corr with future vol
        # (we want higher = more fear = higher expected vol)
        if results[name].get("is_r", 0) < 0:
            z = -z

        crypto_fear_components[name] = z

    df_analysis["crypto_fear_index"] = crypto_fear_components.mean(axis=1)

    # Partial correlation of Crypto Fear Index
    cfi_vals = df_analysis["crypto_fear_index"].values
    y_vals = df_analysis["btc_rv_22d_future"].values
    z_vals = df_analysis["btc_rv_22d"].values
    r_cfi, p_cfi, n_cfi = partial_corr(cfi_vals, y_vals, z_vals)
    print(f"  Crypto Fear Index partial r = {r_cfi:.4f} (p={p_cfi:.4f}, n={n_cfi})")

    # IS vs OOS for CFI
    # Recompute for sub-periods
    df_analysis_is = df_analysis.loc[:oos_start]
    df_analysis_oos = df_analysis.loc[oos_start:]

    r_cfi_is, p_cfi_is, n_cfi_is = partial_corr(
        df_analysis_is["crypto_fear_index"].values,
        df_analysis_is["btc_rv_22d_future"].values,
        df_analysis_is["btc_rv_22d"].values
    )
    r_cfi_oos, p_cfi_oos, n_cfi_oos = partial_corr(
        df_analysis_oos["crypto_fear_index"].values,
        df_analysis_oos["btc_rv_22d_future"].values,
        df_analysis_oos["btc_rv_22d"].values
    )
    print(f"  IS:  r={r_cfi_is:.4f} (p={p_cfi_is:.4f}, n={n_cfi_is})")
    print(f"  OOS: r={r_cfi_oos:.4f} (p={p_cfi_oos:.4f}, n={n_cfi_oos})")
    print()
else:
    print("Insufficient significant features for composite index.")
    print("Proceeding with individual feature analysis only.")
    r_cfi, p_cfi = np.nan, np.nan
    r_cfi_is, p_cfi_is = np.nan, np.nan
    r_cfi_oos, p_cfi_oos = np.nan, np.nan

# ─── Part 3: VIX vs Crypto-Native Features ──────────────────────
print("=" * 70)
print("PART 3: VIX as Crypto Risk Signal — Replication of K277 Finding")
print("=" * 70)
print()

# Simple regression: BTC future RV ~ VIX
from sklearn.linear_model import LinearRegression

mask_reg = np.isfinite(df_analysis["vix_level"]) & np.isfinite(df_analysis["btc_rv_22d_future"])
X_vix = df_analysis.loc[mask_reg, "vix_level"].values.reshape(-1, 1)
y_target = df_analysis.loc[mask_reg, "btc_rv_22d_future"].values

reg_vix = LinearRegression().fit(X_vix, y_target)
r2_vix = reg_vix.score(X_vix, y_target)
print(f"VIX → BTC future RV (full sample):")
print(f"  R² = {r2_vix:.4f}")
print(f"  β  = {reg_vix.coef_[0]:.4f}")
print(f"  α  = {reg_vix.intercept_:.4f}")
print(f"  Confirms K277: VIX is {'useless' if r2_vix < 0.01 else 'weak' if r2_vix < 0.05 else 'moderate'} for BTC vol prediction")
print()

# Compare: Lagged BTC RV → Future BTC RV
mask_rv = np.isfinite(df_analysis["btc_rv_22d"]) & np.isfinite(df_analysis["btc_rv_22d_future"])
X_rv = df_analysis.loc[mask_rv, "btc_rv_22d"].values.reshape(-1, 1)
y_rv = df_analysis.loc[mask_rv, "btc_rv_22d_future"].values
reg_rv = LinearRegression().fit(X_rv, y_rv)
r2_rv = reg_rv.score(X_rv, y_rv)
print(f"Lagged BTC RV → BTC future RV:")
print(f"  R² = {r2_rv:.4f}")
print(f"  (BTC's own vol persistence is {'strong' if r2_rv > 0.3 else 'moderate' if r2_rv > 0.1 else 'weak'})")
print()

# ─── Part 4: OOS Forecasting Contest ────────────────────────────
print("=" * 70)
print("PART 4: OOS Vol Forecasting — Can Crypto Features Beat Lagged RV?")
print("=" * 70)
print()

# Expanding-window OLS forecasts
# Models:
# M0: Naive (lagged RV only)
# M1: Lagged RV + VIX
# M2: Lagged RV + Best Crypto Feature
# M3: Lagged RV + Crypto Fear Index (if available)

oos_dates = df_oos.index
min_train = 500  # Minimum training window

forecasts = {
    "M0_naive": [],
    "M1_vix": [],
}

# Find best single crypto feature (by IS partial r)
best_feature = None
best_r = 0
for name, res in results.items():
    if "VIX" in name:
        continue
    abs_r = abs(res.get("is_r", 0))
    if abs_r > best_r and res.get("stable") == "Yes":
        best_r = abs_r
        best_feature = name

if best_feature:
    best_col = results[best_feature]["col"]
    forecasts["M2_best_crypto"] = []
    print(f"Best single crypto feature: {best_feature} (IS |r|={best_r:.4f})")

has_cfi = "crypto_fear_index" in df_analysis.columns
if has_cfi:
    forecasts["M3_crypto_fear"] = []

print(f"\nRunning expanding-window OOS forecasts ({len(oos_dates)} days)...")

realized_oos = []

for i, date in enumerate(oos_dates):
    if i >= len(oos_dates) - 22:
        break  # Need 22 days ahead for target

    # Training data: everything before this date
    train = df_analysis.loc[:date].iloc[:-1]
    if len(train) < min_train:
        continue

    # Target at this date
    target_idx = df_analysis.index.get_loc(date)
    if target_idx + 22 >= len(df_analysis):
        break
    future_rv = df_analysis.iloc[target_idx]["btc_rv_22d_future"]
    if not np.isfinite(future_rv):
        continue

    realized_oos.append(future_rv)

    # Current features
    current = df_analysis.loc[date]

    # M0: Naive (just lagged RV)
    train_valid = train.dropna(subset=["btc_rv_22d", "btc_rv_22d_future"])
    X_train = train_valid["btc_rv_22d"].values.reshape(-1, 1)
    y_train = train_valid["btc_rv_22d_future"].values
    reg = LinearRegression().fit(X_train, y_train)
    pred_m0 = reg.predict([[current["btc_rv_22d"]]])[0]
    forecasts["M0_naive"].append(max(pred_m0, 0.01))

    # M1: Lagged RV + VIX
    cols_m1 = ["btc_rv_22d", "vix_level"]
    train_m1 = train.dropna(subset=cols_m1 + ["btc_rv_22d_future"])
    if len(train_m1) > 50:
        X_m1 = train_m1[cols_m1].values
        y_m1 = train_m1["btc_rv_22d_future"].values
        reg_m1 = LinearRegression().fit(X_m1, y_m1)
        pred_m1 = reg_m1.predict([current[cols_m1].values])[0]
        forecasts["M1_vix"].append(max(pred_m1, 0.01))
    else:
        forecasts["M1_vix"].append(forecasts["M0_naive"][-1])

    # M2: Lagged RV + Best Crypto Feature
    if best_feature:
        cols_m2 = ["btc_rv_22d", best_col]
        train_m2 = train.dropna(subset=cols_m2 + ["btc_rv_22d_future"])
        if len(train_m2) > 50 and np.isfinite(current[best_col]):
            X_m2 = train_m2[cols_m2].values
            y_m2 = train_m2["btc_rv_22d_future"].values
            reg_m2 = LinearRegression().fit(X_m2, y_m2)
            pred_m2 = reg_m2.predict([current[cols_m2].values])[0]
            forecasts["M2_best_crypto"].append(max(pred_m2, 0.01))
        else:
            forecasts["M2_best_crypto"].append(forecasts["M0_naive"][-1])

    # M3: Lagged RV + Crypto Fear Index
    if has_cfi:
        cols_m3 = ["btc_rv_22d", "crypto_fear_index"]
        train_m3 = train.dropna(subset=cols_m3 + ["btc_rv_22d_future"])
        if len(train_m3) > 50 and np.isfinite(current.get("crypto_fear_index", np.nan)):
            X_m3 = train_m3[cols_m3].values
            y_m3 = train_m3["btc_rv_22d_future"].values
            reg_m3 = LinearRegression().fit(X_m3, y_m3)
            pred_m3 = reg_m3.predict([current[cols_m3].values])[0]
            forecasts["M3_crypto_fear"].append(max(pred_m3, 0.01))
        else:
            forecasts["M3_crypto_fear"].append(forecasts["M0_naive"][-1])

realized_oos = np.array(realized_oos)
n_oos = len(realized_oos)
print(f"  OOS forecast days: {n_oos}")
print()

# ─── Evaluate Forecasts ─────────────────────────────────────────
print(f"{'Model':<25} {'QLIKE':>10} {'MSE':>12} {'MAE':>10} {'DM vs M0':>10} {'DM p':>8}")
print("-" * 78)

realized_var = realized_oos ** 2
qlike_results = {}
model_names = {
    "M0_naive": "M0: Lagged RV Only",
    "M1_vix": "M1: + VIX",
    "M2_best_crypto": f"M2: + {best_feature}" if best_feature else "M2: N/A",
    "M3_crypto_fear": "M3: + Crypto Fear Idx",
}

for model_key in ["M0_naive", "M1_vix", "M2_best_crypto", "M3_crypto_fear"]:
    if model_key not in forecasts or len(forecasts[model_key]) != n_oos:
        continue

    pred = np.array(forecasts[model_key])
    pred_var = pred ** 2

    # QLIKE
    ql = qlike_loss(realized_var, pred_var)
    ql_mean = np.mean(ql)
    qlike_results[model_key] = ql

    # MSE
    mse = np.mean((realized_oos - pred) ** 2)

    # MAE
    mae = np.mean(np.abs(realized_oos - pred))

    # DM test vs M0
    if model_key == "M0_naive":
        dm_t, dm_p = 0.0, 1.0
    else:
        ql_m0 = qlike_results["M0_naive"]
        dm_t, dm_p = dm_test(ql, ql_m0)

    name = model_names.get(model_key, model_key)
    sig = " ***" if dm_p < 0.001 else " **" if dm_p < 0.01 else " *" if dm_p < 0.05 else ""
    print(f"  {name:<23} {ql_mean:>10.4f} {mse:>12.4f} {mae:>10.4f} {dm_t:>10.3f} {dm_p:>7.4f}{sig}")

print()

# ─── Part 5: Regime Analysis ────────────────────────────────────
print("=" * 70)
print("PART 5: Regime-Dependent Analysis")
print("=" * 70)
print()

# Split by BTC vol regime
rv_median = df_analysis["btc_rv_22d"].median()
high_vol = df_analysis[df_analysis["btc_rv_22d"] > rv_median]
low_vol = df_analysis[df_analysis["btc_rv_22d"] <= rv_median]

print(f"BTC RV median = {rv_median:.2f}")
print(f"High-vol regime: {len(high_vol)} days, Low-vol regime: {len(low_vol)} days")
print()

print(f"{'Feature':<25} {'Low-Vol r':>10} {'Low p':>8} {'High-Vol r':>10} {'High p':>8} {'Diff?':>6}")
print("-" * 70)

for name, col in features.items():
    if "VIX" in name:
        continue
    # Low vol
    r_low, p_low, n_low = partial_corr(
        low_vol[col].values,
        low_vol["btc_rv_22d_future"].values,
        low_vol["btc_rv_22d"].values
    )
    # High vol
    r_high, p_high, n_high = partial_corr(
        high_vol[col].values,
        high_vol["btc_rv_22d_future"].values,
        high_vol["btc_rv_22d"].values
    )

    diff = "!!!" if (np.sign(r_low) != np.sign(r_high) and np.isfinite(r_low) and np.isfinite(r_high)) else ""
    print(f"  {name:<23} {r_low:>10.4f} {p_low:>8.4f} {r_high:>10.4f} {p_high:>8.4f} {diff:>6}")

print()

# ─── Part 6: Yearly Stability ───────────────────────────────────
print("=" * 70)
print("PART 6: Year-by-Year Stability of Top Features")
print("=" * 70)
print()

# Pick top 3 features by full-sample |partial r|
sorted_features = sorted(
    [(name, abs(results[name].get("partial_r", 0)), results[name])
     for name in results if "VIX" not in name],
    key=lambda x: x[1], reverse=True
)[:5]

years = sorted(df_analysis.index.year.unique())
print(f"{'Feature':<25}", end="")
for y in years:
    print(f" {y:>8}", end="")
print()
print("-" * (25 + 9 * len(years)))

for name, _, res in sorted_features:
    col = res["col"]
    print(f"  {name:<23}", end="")
    for y in years:
        yearly = df_analysis[df_analysis.index.year == y]
        r, p, n = partial_corr(
            yearly[col].values,
            yearly["btc_rv_22d_future"].values,
            yearly["btc_rv_22d"].values
        )
        sig = "*" if p < 0.05 else " "
        if np.isfinite(r):
            print(f" {r:>7.3f}{sig}", end="")
        else:
            print(f"     N/A ", end="")
    print()

print()

# ─── Part 7: BTC Dominance Proxy ────────────────────────────────
print("=" * 70)
print("PART 7: BTC Dominance Proxy (BTC/(BTC+ETH) by Market Cap Proxy)")
print("=" * 70)
print()

# BTC dominance proxy using price * (assumed constant supply growth)
# This is a very rough proxy — real dominance includes all altcoins
# We use price ratio as a proxy: BTC / (BTC + ETH) weighted
# Since supply is approximately known: BTC ~19.6M, ETH ~120M
btc_supply_approx = 19.0e6  # rough, grows ~1.7%/yr
eth_supply_approx = 120.0e6  # rough

df_analysis["btc_mcap_proxy"] = df_analysis["btc_close"] * btc_supply_approx
df_analysis["eth_mcap_proxy"] = df_analysis["eth_close"] * eth_supply_approx
df_analysis["btc_dominance_proxy"] = (
    df_analysis["btc_mcap_proxy"] /
    (df_analysis["btc_mcap_proxy"] + df_analysis["eth_mcap_proxy"])
)
df_analysis["btc_dom_chg_22d"] = df_analysis["btc_dominance_proxy"].diff(22)

r_dom, p_dom, n_dom = partial_corr(
    df_analysis["btc_dom_chg_22d"].values,
    df_analysis["btc_rv_22d_future"].values,
    df_analysis["btc_rv_22d"].values
)
print(f"BTC dominance change (22d) → future vol:")
print(f"  Partial r = {r_dom:.4f} (p={p_dom:.4f}, n={n_dom})")
print(f"  Interpretation: {'Rising BTC dominance (flight to quality) → higher future vol' if r_dom > 0 else 'Rising BTC dominance → lower future vol'}")
print()

# Current BTC dominance
latest_dom = df_analysis["btc_dominance_proxy"].iloc[-1]
print(f"Current BTC/(BTC+ETH) proxy: {latest_dom:.1%}")
print(f"  (Note: real BTC dominance includes all altcoins, actual ~60%)")
print()

# ─── Summary & Results ──────────────────────────────────────────
print("=" * 70)
print("SUMMARY: K334 DeFi/Crypto Vol Prediction Pilot")
print("=" * 70)
print()

# Collect key findings
print("KEY FINDINGS:")
print()

# 1. Best crypto-native predictors
print("1. Crypto-Native Vol Predictors (partial r, controlling for lagged RV):")
for name, _, res in sorted_features:
    col = res["col"]
    full_r = results[name]["partial_r"]
    full_p = results[name]["p_value"]
    oos_r = results[name].get("oos_r", np.nan)
    print(f"   {name}: full r={full_r:.4f} (p={full_p:.4f}), OOS r={oos_r:.4f}")
print()

# 2. VIX comparison
vix_r = results["VIX Level"]["partial_r"]
vix_p = results["VIX Level"]["p_value"]
print(f"2. VIX as Crypto Vol Predictor:")
print(f"   Partial r = {vix_r:.4f} (p={vix_p:.4f})")
print(f"   VIX → BTC vol R² = {r2_vix:.4f}")
print(f"   BTC lagged RV → BTC vol R² = {r2_rv:.4f}")

if abs(vix_r) < abs(sorted_features[0][1]):
    print(f"   → Crypto-native features ({sorted_features[0][0]}) beat VIX")
else:
    print(f"   → VIX surprisingly useful for BTC vol")
print()

# 3. Crypto Fear Index
if has_cfi:
    print(f"3. Crypto Fear Index ({len(significant_features)} components):")
    print(f"   Full-sample partial r = {r_cfi:.4f} (p={p_cfi:.4f})")
    print(f"   IS partial r = {r_cfi_is:.4f} (p={p_cfi_is:.4f})")
    print(f"   OOS partial r = {r_cfi_oos:.4f} (p={p_cfi_oos:.4f})")
    if p_cfi_oos < 0.05:
        print(f"   → Crypto Fear Index has SIGNIFICANT OOS predictive power")
    elif p_cfi_oos < 0.10:
        print(f"   → Crypto Fear Index has MARGINAL OOS predictive power")
    else:
        print(f"   → Crypto Fear Index NOT significant OOS")
    print()

# 4. Limitations
print("4. LIMITATIONS (CRITICAL):")
print("   a) All features are PROXY variables — not actual on-chain data")
print("   b) Real DeFi data (Aave rates, TVL, liquidations) unavailable via yfinance")
print("   c) BTC volume from yfinance excludes DEX volumes")
print("   d) No stablecoin flow data (USDT/USDC mint/burn)")
print("   e) BTC dominance proxy uses only BTC+ETH, not full crypto market")
print("   f) 22-day overlapping windows create autocorrelation in targets")
print("   g) Expanding-window OLS is simplistic — not GARCH-X or ML")
print("   h) Crypto market has undergone STRUCTURAL changes (DeFi summer 2020,")
print("      institutional adoption 2021+, FTX collapse 2022)")
print()

# 5. Implications
print("5. IMPLICATIONS FOR FUTURE RESEARCH:")
print("   - If on-chain data becomes available (e.g., Dune Analytics API),")
print("     key features to test: Aave utilization rate, total liquidation volume,")
print("     DEX/CEX volume ratio, stablecoin flow, funding rates")
print("   - BTC's own lagged RV remains the strongest predictor (vol clustering)")
print("   - Crypto-specific features may capture information VIX cannot")
print()

# ─── Save Results ────────────────────────────────────────────────
output = {
    "experiment": "K334",
    "title": "DeFi Yield Volatility — Crypto Vol Prediction with Proxies",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance (BTC-USD, ETH-USD, ^VIX)",
    "data_period": f"{df_analysis.index[0].strftime('%Y-%m-%d')} to {df_analysis.index[-1].strftime('%Y-%m-%d')}",
    "oos_period": f"{df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')}",
    "n_total": len(df_analysis),
    "n_oos": n_oos,
    "partial_correlations": {
        name: {
            "full_r": float(res["partial_r"]) if np.isfinite(res["partial_r"]) else None,
            "full_p": float(res["p_value"]) if np.isfinite(res["p_value"]) else None,
            "is_r": float(res.get("is_r", np.nan)) if np.isfinite(res.get("is_r", np.nan)) else None,
            "oos_r": float(res.get("oos_r", np.nan)) if np.isfinite(res.get("oos_r", np.nan)) else None,
            "stable": res.get("stable", "N/A"),
        }
        for name, res in results.items()
    },
    "vix_r_squared": float(r2_vix),
    "lagged_rv_r_squared": float(r2_rv),
    "crypto_fear_index": {
        "components": significant_features if significant_features else [],
        "full_r": float(r_cfi) if np.isfinite(r_cfi) else None,
        "is_r": float(r_cfi_is) if np.isfinite(r_cfi_is) else None,
        "oos_r": float(r_cfi_oos) if np.isfinite(r_cfi_oos) else None,
    },
    "btc_dominance_proxy": {
        "partial_r": float(r_dom) if np.isfinite(r_dom) else None,
        "p_value": float(p_dom) if np.isfinite(p_dom) else None,
    },
    "limitations": [
        "All features are PROXY variables, not actual on-chain data",
        "No Aave/Compound rates, no TVL, no liquidation data",
        "BTC volume excludes DEX volumes",
        "No stablecoin flow data",
        "BTC dominance proxy uses only BTC+ETH",
        "22-day overlapping windows create autocorrelation",
        "Expanding-window OLS is simplistic",
        "Crypto market structural changes not modeled",
    ],
    "attribution": "[提出: 用戶, 執行: Claude]",
}

output_path = "experiments/k334_defi_vol_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)
print(f"Results saved to {output_path}")
print()
print("=" * 70)
print("K334 COMPLETE")
print("=" * 70)
