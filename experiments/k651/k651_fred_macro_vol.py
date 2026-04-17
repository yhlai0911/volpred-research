#!/usr/bin/env python3
"""
K651: FRED Macro Indicators as Volatility Predictors
=====================================================
Test whether macro indicators (yield curve, credit spreads, bond vol,
equity-bond correlation) add predictive power for SPY realized volatility
beyond what VIX and GARCH capture.

Data sources: yfinance (SPY, ^VIX, TLT, HYG, LQD, ^TNX)
Period: 2010-01-01 to 2026-03-27

Macro signal proxies (all lagged, no lookahead):
  1. Yield curve slope proxy: TLT 60-day return momentum (lower = flatter curve)
  2. Credit spread proxy: HYG/LQD total return ratio (lower = wider spread = stress)
  3. Bond vol: Rolling 22-day volatility of TLT
  4. Equity-bond correlation: Rolling 60-day corr(SPY, TLT)

Models (rolling OOS w=1500, OOS=2023-2024, refit every 63 days):
  a. GJR-GARCH(1,1) baseline
  b. HAR + all 4 macro signals (OLS)
  c. HAR + credit_spread only (most likely to add value)
  d. Comparison: QLIKE, MAE, DM test

Regime analysis:
  - Logistic regression: P(VIX>20) = f(macro signals)
  - AUC-ROC for regime prediction

Key hypothesis: Credit spreads capture credit risk not embedded in VIX
(equity options-based), so HYG/LQD ratio may have incremental value.

References:
  - Paye (2012, JFE): "Deja vol: Predictive regressions for aggregate stock market volatility using macroeconomic variables"
  - Christiansen et al. (2012, JFE): "A comprehensive look at financial volatility prediction by economic variables"
  - Engle & Rangel (2008, RFS): "The Spline-GARCH model for low-frequency volatility and its global macroeconomic causes"

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
import json
from datetime import datetime
from pathlib import Path

np.random.seed(42)

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K651: FRED Macro Indicators as Volatility Predictors")
print("=" * 70)

print("\n[1/7] Downloading data from yfinance...")

tickers = {
    "SPY": "SPY",
    "VIX": "^VIX",
    "TLT": "TLT",      # Long-term Treasury bond ETF
    "HYG": "HYG",      # High Yield Corporate Bond ETF
    "LQD": "LQD",      # Investment Grade Corporate Bond ETF
    "TNX": "^TNX",      # 10-Year Treasury Yield
}

start_date = "2009-01-01"  # Extra buffer for rolling windows
end_date = "2026-03-28"

data = {}
for name, ticker in tickers.items():
    raw = yf.download(ticker, start=start_date, end=end_date, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close_col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    data[name] = raw[close_col].copy()
    data[name].name = name
    print(f"  {name}: {data[name].index[0].strftime('%Y-%m-%d')} to "
          f"{data[name].index[-1].strftime('%Y-%m-%d')} ({len(data[name])} obs)")

# ============================================================
# 2. Construct macro signals
# ============================================================
print("\n[2/7] Constructing macro signals...")

# Align all series to common dates
common_idx = data["SPY"].index
for name in ["VIX", "TLT", "HYG", "LQD", "TNX"]:
    common_idx = common_idx.intersection(data[name].index)

spy_close = data["SPY"].loc[common_idx]
vix_close = data["VIX"].loc[common_idx]
tlt_close = data["TLT"].loc[common_idx]
hyg_close = data["HYG"].loc[common_idx]
lqd_close = data["LQD"].loc[common_idx]
tnx_close = data["TNX"].loc[common_idx]

# Returns
spy_ret = spy_close.pct_change().dropna()
tlt_ret = tlt_close.pct_change().dropna()

# Re-align after pct_change
common_idx2 = spy_ret.index.intersection(tlt_ret.index)
spy_ret = spy_ret.loc[common_idx2]
tlt_ret = tlt_ret.loc[common_idx2]

# Realized volatility (daily squared return as proxy)
rv_daily = spy_ret ** 2  # daily RV proxy

# 22-day realized volatility (annualized)
rv_22 = spy_ret.rolling(22).std() * np.sqrt(252)
rv_22.name = "RV_22"

# --- Macro Signal 1: TLT 60-day return momentum ---
# Rolling 60-day cumulative return of TLT (yield curve slope proxy)
tlt_mom_60 = tlt_close.pct_change(60).loc[common_idx2]
tlt_mom_60.name = "tlt_momentum_60d"

# --- Macro Signal 2: Credit spread proxy ---
# HYG/LQD ratio: lower = wider credit spread = stress
hyg_lqd_ratio = (hyg_close / lqd_close).loc[common_idx2]
hyg_lqd_ratio.name = "hyg_lqd_ratio"
# Use rolling z-score for stationarity
hyg_lqd_zscore = (hyg_lqd_ratio - hyg_lqd_ratio.rolling(252).mean()) / hyg_lqd_ratio.rolling(252).std()
hyg_lqd_zscore.name = "credit_spread_zscore"

# --- Macro Signal 3: Bond volatility ---
# Rolling 22-day TLT vol (annualized)
tlt_vol_22 = tlt_ret.rolling(22).std() * np.sqrt(252)
tlt_vol_22.name = "tlt_vol_22d"

# --- Macro Signal 4: Equity-bond correlation ---
# Rolling 60-day correlation between SPY and TLT
eq_bond_corr = spy_ret.rolling(60).corr(tlt_ret)
eq_bond_corr.name = "spy_tlt_corr_60d"

# Combine all signals
signals = pd.DataFrame({
    "spy_ret": spy_ret,
    "rv_daily": rv_daily,
    "rv_22": rv_22,
    "vix": vix_close.loc[common_idx2],
    "tlt_momentum": tlt_mom_60,
    "credit_spread": hyg_lqd_zscore,
    "tlt_vol": tlt_vol_22,
    "eq_bond_corr": eq_bond_corr,
    "tnx": tnx_close.loc[common_idx2],
}).dropna()

print(f"  Combined dataset: {signals.index[0].strftime('%Y-%m-%d')} to "
      f"{signals.index[-1].strftime('%Y-%m-%d')} ({len(signals)} obs)")
print(f"\n  Signal statistics:")
for col in ["tlt_momentum", "credit_spread", "tlt_vol", "eq_bond_corr"]:
    s = signals[col]
    print(f"    {col:25s}: mean={s.mean():.4f}, std={s.std():.4f}, "
          f"skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

# ============================================================
# 3. Data diagnostics
# ============================================================
print("\n[3/7] Data diagnostics...")

# Descriptive stats for SPY returns
r = signals["spy_ret"]
print(f"  SPY daily returns:")
print(f"    Mean={r.mean()*252:.4f} (ann.), Std={r.std()*np.sqrt(252):.4f} (ann.)")
print(f"    Skew={r.skew():.3f}, Kurt={r.kurtosis():.3f}")

# ADF test on SPY returns
from statsmodels.tsa.stattools import adfuller
adf_ret = adfuller(r.values, maxlag=10)
print(f"    ADF test: stat={adf_ret[0]:.3f}, p={adf_ret[1]:.6f} ({'Stationary' if adf_ret[1] < 0.05 else 'Non-stationary'})")

# ARCH LM test
from statsmodels.stats.diagnostic import het_arch
arch_lm = het_arch(r.values, nlags=10)
print(f"    ARCH LM test: stat={arch_lm[0]:.1f}, p={arch_lm[1]:.6f} ({'ARCH effects' if arch_lm[1] < 0.05 else 'No ARCH'})")

# Correlation matrix of macro signals with future RV
print(f"\n  Correlation of macro signals with next-day RV (r²):")
for col in ["vix", "tlt_momentum", "credit_spread", "tlt_vol", "eq_bond_corr"]:
    sig_lagged = signals[col].shift(1).dropna()
    rv_fwd = signals["rv_daily"].loc[sig_lagged.index]
    corr = sig_lagged.corr(rv_fwd)
    print(f"    {col:25s}: r={corr:.4f}")

# ============================================================
# 4. HAR-RV + Macro signals — Rolling OOS forecasting
# ============================================================
print("\n[4/7] Rolling OOS forecasting (w=1500, refit every 63 days)...")

# HAR components
signals["rv_1"] = signals["rv_daily"].shift(1)  # lagged 1-day RV
signals["rv_5"] = signals["rv_daily"].rolling(5).mean().shift(1)  # lagged 5-day avg RV
signals["rv_22"] = signals["rv_daily"].rolling(22).mean().shift(1)  # lagged 22-day avg RV

# Lagged macro signals (all lagged by 1 day to avoid lookahead)
signals["tlt_momentum_lag"] = signals["tlt_momentum"].shift(1)
signals["credit_spread_lag"] = signals["credit_spread"].shift(1)
signals["tlt_vol_lag"] = signals["tlt_vol"].shift(1)
signals["eq_bond_corr_lag"] = signals["eq_bond_corr"].shift(1)
# Convert VIX to daily variance scale: VIX=20 → annualized vol=20% → daily var = (0.20)²/252
signals["vix_var"] = (signals["vix"] / 100) ** 2 / 252  # VIX in daily variance units
signals["vix_lag"] = signals["vix_var"].shift(1)
signals["vix_raw_lag"] = signals["vix"].shift(1)  # Raw VIX for regime logistic regression

signals = signals.dropna()

# OOS period: 2023-01-01 to 2024-12-31
oos_start = pd.Timestamp("2023-01-01")
oos_end = pd.Timestamp("2024-12-31")
oos_mask = (signals.index >= oos_start) & (signals.index <= oos_end)

# Ensure enough training data
train_start_idx = signals.index.get_loc(signals.index[signals.index >= oos_start][0])
if train_start_idx < 1500:
    print(f"  WARNING: Not enough training data. Have {train_start_idx}, need 1500.")
    print(f"  Adjusting window to {train_start_idx}")
    w = train_start_idx
else:
    w = 1500

oos_indices = signals.index[oos_mask]
print(f"  Training window: {w}")
print(f"  OOS period: {oos_indices[0].strftime('%Y-%m-%d')} to {oos_indices[-1].strftime('%Y-%m-%d')} ({len(oos_indices)} days)")

# Define models
from sklearn.linear_model import LinearRegression

def rolling_oos_forecast(signals_df, feature_cols, target_col, oos_mask, w, refit_every=63):
    """Rolling OOS forecast with periodic refitting."""
    oos_idx = signals_df.index[oos_mask]
    forecasts = []
    actuals = []
    model = None
    last_fit = -refit_every  # Force fit on first iteration

    # Compute training mean for floor
    first_oos_loc = signals_df.index.get_loc(oos_idx[0])
    train_mean = signals_df.iloc[max(0, first_oos_loc - w):first_oos_loc][target_col].mean()
    floor_val = train_mean * 0.01  # 1% of training mean as floor

    for i, date in enumerate(oos_idx):
        loc = signals_df.index.get_loc(date)

        # Training window
        train_end = loc
        train_start = max(0, loc - w)
        train_data = signals_df.iloc[train_start:train_end]

        X_train = train_data[feature_cols].values
        y_train = train_data[target_col].values

        # Refit periodically
        if i - last_fit >= refit_every or model is None:
            model = LinearRegression()
            model.fit(X_train, y_train)
            last_fit = i

        # Forecast
        X_test = signals_df.loc[[date], feature_cols].values
        y_pred = model.predict(X_test)[0]
        y_pred = max(y_pred, floor_val)  # Floor at small fraction of mean

        y_actual = signals_df.loc[date, target_col]

        forecasts.append(y_pred)
        actuals.append(y_actual)

    return np.array(forecasts), np.array(actuals)


# Model A: GJR-GARCH baseline
print("\n  Fitting Model A: GJR-GARCH(1,1) baseline...")
spy_returns_full = signals["spy_ret"] * 100  # Scale for arch

garch_forecasts = []
garch_actuals = []
garch_last_fit = -63

garch_model = None
for i, date in enumerate(oos_indices):
    loc = signals.index.get_loc(date)
    train_end = loc
    train_start = max(0, loc - w)
    train_returns = spy_returns_full.iloc[train_start:train_end]

    # Refit every 63 days
    if i % 63 == 0 or garch_model is None:
        try:
            am = arch_model(train_returns, vol='GARCH', p=1, o=1, q=1, dist='normal')
            garch_model = am.fit(disp='off', show_warning=False)
        except Exception:
            pass

    if garch_model is not None:
        fcast = garch_model.forecast(horizon=1, reindex=False)
        var_pred = fcast.variance.values[-1, 0] / 10000  # Convert back from %²
    else:
        var_pred = train_returns.var() / 10000

    garch_forecasts.append(var_pred)
    garch_actuals.append(signals.loc[date, "rv_daily"])

garch_forecasts = np.array(garch_forecasts)
garch_actuals = np.array(garch_actuals)
print(f"    GARCH forecasts: {len(garch_forecasts)} obs")

# Check GARCH convergence
if garch_model is not None:
    params = garch_model.params
    persistence = params.get("alpha[1]", 0) + params.get("gamma[1]", 0) * 0.5 + params.get("beta[1]", 0)
    print(f"    Last fit: alpha={params.get('alpha[1]', 0):.4f}, gamma={params.get('gamma[1]', 0):.4f}, "
          f"beta={params.get('beta[1]', 0):.4f}, persistence={persistence:.4f}")
    if persistence >= 1.0:
        print("    WARNING: persistence >= 1.0, model may be non-stationary!")

# Model B: HAR + all 4 macro signals
print("\n  Fitting Model B: HAR + all macro signals...")
har_macro_features = ["rv_1", "rv_5", "rv_22", "tlt_momentum_lag",
                      "credit_spread_lag", "tlt_vol_lag", "eq_bond_corr_lag"]
har_macro_fcast, har_macro_actual = rolling_oos_forecast(
    signals, har_macro_features, "rv_daily", oos_mask, w, refit_every=63
)
print(f"    HAR+macro forecasts: {len(har_macro_fcast)} obs")

# Model C: HAR + credit spread only
print("\n  Fitting Model C: HAR + credit spread only...")
har_credit_features = ["rv_1", "rv_5", "rv_22", "credit_spread_lag"]
har_credit_fcast, har_credit_actual = rolling_oos_forecast(
    signals, har_credit_features, "rv_daily", oos_mask, w, refit_every=63
)
print(f"    HAR+credit forecasts: {len(har_credit_fcast)} obs")

# Model D: HAR-only baseline (for comparing macro contribution)
print("\n  Fitting Model D: HAR-only baseline...")
har_only_features = ["rv_1", "rv_5", "rv_22"]
har_only_fcast, har_only_actual = rolling_oos_forecast(
    signals, har_only_features, "rv_daily", oos_mask, w, refit_every=63
)
print(f"    HAR-only forecasts: {len(har_only_fcast)} obs")

# Model E: HAR + VIX (to see if VIX already captures macro info)
print("\n  Fitting Model E: HAR + VIX...")
har_vix_features = ["rv_1", "rv_5", "rv_22", "vix_lag"]
har_vix_fcast, har_vix_actual = rolling_oos_forecast(
    signals, har_vix_features, "rv_daily", oos_mask, w, refit_every=63
)
print(f"    HAR+VIX forecasts: {len(har_vix_fcast)} obs")


# ============================================================
# 5. Evaluation metrics
# ============================================================
print("\n[5/7] Evaluation metrics...")

def qlike(actual, forecast):
    """QLIKE loss function (lower is better)."""
    # Avoid division by zero
    forecast = np.maximum(forecast, 1e-12)
    actual = np.maximum(actual, 1e-12)
    return np.mean(actual / forecast - np.log(actual / forecast) - 1)

def mae(actual, forecast):
    """Mean Absolute Error."""
    return np.mean(np.abs(actual - forecast))

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Returns (t-stat, p-value). Negative t-stat means model 1 is better."""
    d = loss1 - loss2
    n = len(d)
    d_mean = d.mean()
    # Newey-West HAC variance with h-1 lags
    gamma0 = np.var(d, ddof=1)
    dk_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        dk_sum += 2 * gamma_k
    var_d = (gamma0 + dk_sum) / n
    if var_d <= 0:
        var_d = gamma0 / n
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value

# QLIKE losses
qlike_garch = qlike(garch_actuals, garch_forecasts)
qlike_har_macro = qlike(har_macro_actual, har_macro_fcast)
qlike_har_credit = qlike(har_credit_actual, har_credit_fcast)
qlike_har_only = qlike(har_only_actual, har_only_fcast)
qlike_har_vix = qlike(har_vix_actual, har_vix_fcast)

# Per-observation QLIKE for DM test
def qlike_per_obs(actual, forecast):
    forecast = np.maximum(forecast, 1e-12)
    actual = np.maximum(actual, 1e-12)
    return actual / forecast - np.log(actual / forecast) - 1

garch_loss = qlike_per_obs(garch_actuals, garch_forecasts)
har_macro_loss = qlike_per_obs(har_macro_actual, har_macro_fcast)
har_credit_loss = qlike_per_obs(har_credit_actual, har_credit_fcast)
har_only_loss = qlike_per_obs(har_only_actual, har_only_fcast)
har_vix_loss = qlike_per_obs(har_vix_actual, har_vix_fcast)

# MAE
mae_garch = mae(garch_actuals, garch_forecasts)
mae_har_macro = mae(har_macro_actual, har_macro_fcast)
mae_har_credit = mae(har_credit_actual, har_credit_fcast)
mae_har_only = mae(har_only_actual, har_only_fcast)
mae_har_vix = mae(har_vix_actual, har_vix_fcast)

print(f"\n  {'Model':30s} {'QLIKE':>10s} {'MAE':>12s}")
print(f"  {'-'*55}")
print(f"  {'A: GJR-GARCH(1,1)':30s} {qlike_garch:10.6f} {mae_garch:12.8f}")
print(f"  {'B: HAR + all macro':30s} {qlike_har_macro:10.6f} {mae_har_macro:12.8f}")
print(f"  {'C: HAR + credit only':30s} {qlike_har_credit:10.6f} {mae_har_credit:12.8f}")
print(f"  {'D: HAR only':30s} {qlike_har_only:10.6f} {mae_har_only:12.8f}")
print(f"  {'E: HAR + VIX':30s} {qlike_har_vix:10.6f} {mae_har_vix:12.8f}")

# DM tests
print(f"\n  DM tests (QLIKE loss, H0: equal accuracy):")
dm_tests = {}

# GARCH vs HAR+macro
t, p = dm_test(garch_loss, har_macro_loss)
winner = "GARCH" if t < 0 else "HAR+macro"
sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
print(f"    GARCH vs HAR+macro:       t={t:+.3f}, p={p:.4f} {sig} → {winner}")
dm_tests["garch_vs_har_macro"] = {"t_stat": round(t, 4), "p_value": round(p, 4), "winner": winner}

# GARCH vs HAR+credit
t, p = dm_test(garch_loss, har_credit_loss)
winner = "GARCH" if t < 0 else "HAR+credit"
sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
print(f"    GARCH vs HAR+credit:      t={t:+.3f}, p={p:.4f} {sig} → {winner}")
dm_tests["garch_vs_har_credit"] = {"t_stat": round(t, 4), "p_value": round(p, 4), "winner": winner}

# HAR-only vs HAR+macro (incremental value of macro)
t, p = dm_test(har_only_loss, har_macro_loss)
winner = "HAR-only" if t < 0 else "HAR+macro"
sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
print(f"    HAR-only vs HAR+macro:    t={t:+.3f}, p={p:.4f} {sig} → {winner}")
dm_tests["har_only_vs_har_macro"] = {"t_stat": round(t, 4), "p_value": round(p, 4), "winner": winner}

# HAR-only vs HAR+credit (incremental value of credit only)
t, p = dm_test(har_only_loss, har_credit_loss)
winner = "HAR-only" if t < 0 else "HAR+credit"
sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
print(f"    HAR-only vs HAR+credit:   t={t:+.3f}, p={p:.4f} {sig} → {winner}")
dm_tests["har_only_vs_har_credit"] = {"t_stat": round(t, 4), "p_value": round(p, 4), "winner": winner}

# HAR+VIX vs HAR+macro (does macro add beyond VIX?)
t, p = dm_test(har_vix_loss, har_macro_loss)
winner = "HAR+VIX" if t < 0 else "HAR+macro"
sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
print(f"    HAR+VIX vs HAR+macro:     t={t:+.3f}, p={p:.4f} {sig} → {winner}")
dm_tests["har_vix_vs_har_macro"] = {"t_stat": round(t, 4), "p_value": round(p, 4), "winner": winner}

# HAR+VIX vs HAR+credit
t, p = dm_test(har_vix_loss, har_credit_loss)
winner = "HAR+VIX" if t < 0 else "HAR+credit"
sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
print(f"    HAR+VIX vs HAR+credit:    t={t:+.3f}, p={p:.4f} {sig} → {winner}")
dm_tests["har_vix_vs_har_credit"] = {"t_stat": round(t, 4), "p_value": round(p, 4), "winner": winner}

# GARCH vs HAR+VIX
t, p = dm_test(garch_loss, har_vix_loss)
winner = "GARCH" if t < 0 else "HAR+VIX"
sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
print(f"    GARCH vs HAR+VIX:         t={t:+.3f}, p={p:.4f} {sig} → {winner}")
dm_tests["garch_vs_har_vix"] = {"t_stat": round(t, 4), "p_value": round(p, 4), "winner": winner}


# ============================================================
# 6. Regime analysis — Can macro signals predict VIX > 20?
# ============================================================
print("\n[6/7] Regime analysis: P(VIX > 20) = f(macro signals)...")

# Build regime target (VIX > 20 = high vol regime)
signals["vix_high"] = (signals["vix"] > 20).astype(int)
regime_pct = signals.loc[oos_mask, "vix_high"].mean() * 100

print(f"  VIX > 20 frequency in OOS: {regime_pct:.1f}%")

# Features for logistic regression
regime_features = ["tlt_momentum_lag", "credit_spread_lag", "tlt_vol_lag", "eq_bond_corr_lag"]

# Rolling logistic regression
regime_probs = []
regime_actuals = []

for i, date in enumerate(oos_indices):
    loc = signals.index.get_loc(date)
    train_end = loc
    train_start = max(0, loc - w)

    X_train = signals.iloc[train_start:train_end][regime_features].values
    y_train = signals.iloc[train_start:train_end]["vix_high"].values

    # Only fit if both classes present
    if len(np.unique(y_train)) < 2:
        continue

    if i % 63 == 0 or i == 0:
        lr = LogisticRegression(max_iter=1000, random_state=42)
        lr.fit(X_train, y_train)

    X_test = signals.loc[[date], regime_features].values
    prob = lr.predict_proba(X_test)[0, 1]
    actual = signals.loc[date, "vix_high"]

    regime_probs.append(prob)
    regime_actuals.append(actual)

regime_probs = np.array(regime_probs)
regime_actuals = np.array(regime_actuals)

# AUC-ROC
try:
    auc = roc_auc_score(regime_actuals, regime_probs)
    print(f"  AUC-ROC (macro signals → VIX>20): {auc:.4f}")
    if auc > 0.7:
        print(f"    → Decent discriminative power")
    elif auc > 0.6:
        print(f"    → Weak discriminative power")
    else:
        print(f"    → No useful discriminative power (≈ random)")
except ValueError:
    auc = np.nan
    print(f"  AUC-ROC: could not compute (single class in OOS)")

# Logistic regression coefficients (from last fit)
print(f"\n  Logistic regression coefficients (last fit):")
for feat, coef in zip(regime_features, lr.coef_[0]):
    print(f"    {feat:25s}: {coef:+.4f}")

# VIX-only baseline AUC
# Use lagged VIX as single predictor
vix_regime_probs = []
vix_regime_actuals = []
for i, date in enumerate(oos_indices):
    loc = signals.index.get_loc(date)
    train_end = loc
    train_start = max(0, loc - w)

    X_train = signals.iloc[train_start:train_end][["vix_raw_lag"]].values
    y_train = signals.iloc[train_start:train_end]["vix_high"].values

    if len(np.unique(y_train)) < 2:
        continue

    if i % 63 == 0 or i == 0:
        lr_vix = LogisticRegression(max_iter=1000, random_state=42)
        lr_vix.fit(X_train, y_train)

    X_test = signals.loc[[date], ["vix_raw_lag"]].values
    prob = lr_vix.predict_proba(X_test)[0, 1]
    actual = signals.loc[date, "vix_high"]

    vix_regime_probs.append(prob)
    vix_regime_actuals.append(actual)

vix_regime_probs = np.array(vix_regime_probs)
vix_regime_actuals = np.array(vix_regime_actuals)

try:
    auc_vix = roc_auc_score(vix_regime_actuals, vix_regime_probs)
    print(f"\n  AUC-ROC (VIX-only → VIX>20): {auc_vix:.4f}")
    print(f"  AUC-ROC (macro signals → VIX>20): {auc:.4f}")
    auc_diff = auc - auc_vix
    print(f"  Incremental AUC from macro: {auc_diff:+.4f}")
except ValueError:
    auc_vix = np.nan
    auc_diff = np.nan


# ============================================================
# 7. In-sample coefficient analysis + sub-period robustness
# ============================================================
print("\n[7/7] In-sample analysis & sub-period robustness...")

# Full in-sample regression: RV ~ HAR + macro
import statsmodels.api as sm

X_full = signals[har_macro_features]
y_full = signals["rv_daily"]
X_full_const = sm.add_constant(X_full)
ols_full = sm.OLS(y_full, X_full_const).fit(cov_type='HAC', cov_kwds={'maxlags': 22})

print(f"\n  Full-sample OLS: RV_daily ~ HAR + macro signals")
print(f"  R² = {ols_full.rsquared:.4f}, Adj R² = {ols_full.rsquared_adj:.4f}")
print(f"  N = {len(y_full)}")
print(f"\n  {'Variable':25s} {'Coef':>10s} {'t-stat':>10s} {'p-value':>10s}")
print(f"  {'-'*58}")
for var in ols_full.params.index:
    coef = ols_full.params[var]
    t = ols_full.tvalues[var]
    p = ols_full.pvalues[var]
    sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
    print(f"  {var:25s} {coef:10.6f} {t:10.3f} {p:10.4f} {sig}")

# Sub-period analysis
sub_periods = [
    ("2010-2015", "2010-01-01", "2015-12-31"),
    ("2016-2019", "2016-01-01", "2019-12-31"),
    ("2020-2021 (COVID)", "2020-01-01", "2021-12-31"),
    ("2022-2024", "2022-01-01", "2024-12-31"),
]

print(f"\n  Sub-period credit spread coefficient:")
print(f"  {'Period':25s} {'Coef':>10s} {'t-stat':>10s} {'p-value':>10s}")
print(f"  {'-'*58}")

sub_period_results = {}
for label, start, end in sub_periods:
    mask = (signals.index >= start) & (signals.index <= end)
    if mask.sum() < 100:
        continue
    X_sub = signals.loc[mask, har_macro_features]
    y_sub = signals.loc[mask, "rv_daily"]
    X_sub_c = sm.add_constant(X_sub)
    try:
        ols_sub = sm.OLS(y_sub, X_sub_c).fit(cov_type='HAC', cov_kwds={'maxlags': 22})
        cs_coef = ols_sub.params.get("credit_spread_lag", 0)
        cs_t = ols_sub.tvalues.get("credit_spread_lag", 0)
        cs_p = ols_sub.pvalues.get("credit_spread_lag", 1)
        sig = "***" if cs_p < 0.01 else "**" if cs_p < 0.05 else "*" if cs_p < 0.10 else ""
        print(f"  {label:25s} {cs_coef:10.6f} {cs_t:10.3f} {cs_p:10.4f} {sig}")
        sub_period_results[label] = {
            "credit_spread_coef": round(cs_coef, 6),
            "credit_spread_t": round(cs_t, 3),
            "credit_spread_p": round(cs_p, 4),
            "r_squared": round(ols_sub.rsquared, 4),
            "n_obs": int(mask.sum()),
        }
    except Exception as e:
        print(f"  {label:25s} ERROR: {e}")
        sub_period_results[label] = {"error": str(e)}


# ============================================================
# Save results
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

print(f"\n  Key finding: Do macro signals improve vol prediction beyond GARCH/VIX?")

# Determine the key conclusion
best_qlike = min(qlike_garch, qlike_har_macro, qlike_har_credit, qlike_har_only, qlike_har_vix)
best_model = {
    qlike_garch: "GJR-GARCH",
    qlike_har_macro: "HAR+macro",
    qlike_har_credit: "HAR+credit",
    qlike_har_only: "HAR-only",
    qlike_har_vix: "HAR+VIX",
}[best_qlike]

print(f"  Best model by QLIKE: {best_model} ({best_qlike:.6f})")

# Incremental value of macro over HAR-only
macro_improvement = (qlike_har_only - qlike_har_macro) / qlike_har_only * 100
credit_improvement = (qlike_har_only - qlike_har_credit) / qlike_har_only * 100
vix_improvement = (qlike_har_only - qlike_har_vix) / qlike_har_only * 100

print(f"\n  QLIKE improvement over HAR-only:")
print(f"    HAR+macro:  {macro_improvement:+.2f}%")
print(f"    HAR+credit: {credit_improvement:+.2f}%")
print(f"    HAR+VIX:    {vix_improvement:+.2f}%")

if abs(macro_improvement) < 1.0:
    conclusion = "NULL RESULT: Macro signals provide negligible improvement over HAR-only for daily vol prediction"
elif macro_improvement > 0:
    conclusion = f"POSITIVE: Macro signals improve QLIKE by {macro_improvement:.1f}% over HAR-only"
else:
    conclusion = f"NEGATIVE: Macro signals hurt prediction by {abs(macro_improvement):.1f}% — overfitting likely"

print(f"\n  Conclusion: {conclusion}")
print(f"  Regime AUC: macro={auc:.4f}, VIX-only={auc_vix:.4f} (diff={auc_diff:+.4f})")

# Full-sample macro coefficient significance
sig_vars = [v for v in ["tlt_momentum_lag", "credit_spread_lag", "tlt_vol_lag", "eq_bond_corr_lag"]
            if v in ols_full.pvalues.index and ols_full.pvalues[v] < 0.05]
print(f"  In-sample significant macro variables (p<0.05): {sig_vars if sig_vars else 'None'}")

# Limitations
print(f"\n  Limitations:")
print(f"    1. HYG/LQD ratio is a proxy for credit spreads, not actual OAS")
print(f"    2. TLT momentum is a proxy for yield curve, not actual 10Y-2Y spread")
print(f"    3. Daily RV proxy (r²) is noisy — monthly aggregation may show different results")
print(f"    4. OOS period (2023-2024) may not represent all regimes")
print(f"    5. Linear models — nonlinear macro effects may exist but are not captured")

# Save to JSON
results = {
    "experiment_id": "K651",
    "title": "FRED Macro Indicators as Volatility Predictors",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance (SPY, ^VIX, TLT, HYG, LQD, ^TNX)",
    "period": f"{signals.index[0].strftime('%Y-%m-%d')} to {signals.index[-1].strftime('%Y-%m-%d')}",
    "n_obs_total": len(signals),
    "oos_period": f"{oos_indices[0].strftime('%Y-%m-%d')} to {oos_indices[-1].strftime('%Y-%m-%d')}",
    "n_obs_oos": len(oos_indices),
    "training_window": w,
    "refit_every": 63,
    "macro_signals": {
        "tlt_momentum_60d": "Rolling 60-day TLT return (yield curve slope proxy)",
        "credit_spread_zscore": "HYG/LQD ratio z-score (credit spread proxy)",
        "tlt_vol_22d": "Rolling 22-day TLT volatility (bond vol)",
        "spy_tlt_corr_60d": "Rolling 60-day SPY-TLT correlation (equity-bond)",
    },
    "signal_statistics": {
        col: {
            "mean": round(signals[col].mean(), 6),
            "std": round(signals[col].std(), 6),
            "skew": round(signals[col].skew(), 3),
            "kurt": round(signals[col].kurtosis(), 3),
        }
        for col in ["tlt_momentum", "credit_spread", "tlt_vol", "eq_bond_corr"]
    },
    "models": {
        "A_gjr_garch": {"qlike": round(qlike_garch, 6), "mae": round(mae_garch, 8)},
        "B_har_all_macro": {"qlike": round(qlike_har_macro, 6), "mae": round(mae_har_macro, 8)},
        "C_har_credit_only": {"qlike": round(qlike_har_credit, 6), "mae": round(mae_har_credit, 8)},
        "D_har_only": {"qlike": round(qlike_har_only, 6), "mae": round(mae_har_only, 8)},
        "E_har_vix": {"qlike": round(qlike_har_vix, 6), "mae": round(mae_har_vix, 8)},
    },
    "best_model": best_model,
    "qlike_improvement_over_har_only": {
        "har_macro_pct": round(macro_improvement, 2),
        "har_credit_pct": round(credit_improvement, 2),
        "har_vix_pct": round(vix_improvement, 2),
    },
    "dm_tests": dm_tests,
    "regime_analysis": {
        "vix_high_pct_oos": round(regime_pct, 1),
        "auc_macro_signals": round(float(auc), 4) if not np.isnan(auc) else None,
        "auc_vix_only": round(float(auc_vix), 4) if not np.isnan(auc_vix) else None,
        "auc_increment": round(float(auc_diff), 4) if not np.isnan(auc_diff) else None,
        "logistic_coefficients": {
            feat: round(coef, 4) for feat, coef in zip(regime_features, lr.coef_[0])
        },
    },
    "full_sample_ols": {
        "r_squared": round(ols_full.rsquared, 4),
        "adj_r_squared": round(ols_full.rsquared_adj, 4),
        "n_obs": len(y_full),
        "coefficients": {
            var: {
                "coef": round(float(ols_full.params[var]), 6),
                "t_stat": round(float(ols_full.tvalues[var]), 3),
                "p_value": round(float(ols_full.pvalues[var]), 4),
            }
            for var in ols_full.params.index
        },
        "significant_macro_vars_p005": sig_vars,
    },
    "sub_period_analysis": sub_period_results,
    "conclusion": conclusion,
    "limitations": [
        "HYG/LQD ratio is a proxy for credit spreads, not actual OAS",
        "TLT momentum is a proxy for yield curve, not actual 10Y-2Y spread",
        "Daily RV proxy (r^2) is noisy -- monthly aggregation may show different results",
        "OOS period (2023-2024) may not represent all regimes",
        "Linear models -- nonlinear macro effects may exist but are not captured",
    ],
    "references": [
        "Paye (2012, JFE): Deja vol: Predictive regressions for aggregate stock market volatility using macroeconomic variables",
        "Christiansen et al. (2012, JFE): A comprehensive look at financial volatility prediction by economic variables",
        "Engle & Rangel (2008, RFS): The Spline-GARCH model for low-frequency volatility and its global macroeconomic causes",
    ],
}

out_path = Path(__file__).resolve().parent / "k651_results.json"
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {out_path}")

print("\n" + "=" * 70)
print("K651 complete.")
print("=" * 70)
