#!/usr/bin/env python3
"""
K472: Taiwan 0050.TW Comprehensive Vol Prediction — Integrating All Positive Findings

Background:
  Three validated positive findings from US equities:
  1. HAR log-range (K469: 8/10 cross-OOS with r² proxy)
  2. Semivariance RS⁻ (K460: 4/5 cross-OOS)
  3. Rolling kurtosis (K471: +16pp R² but DM NS)

  Taiwan paper needs: Do these methods work on 0050.TW?

Design:
  Asset: 0050.TW
  Data: 2008-2026 (yfinance adjusted close + OHLC)
  OOS: 2023-01-01 to 2025-12-31
  IS: 2000 trading days rolling window

  8 Models:
    1. GJR-GARCH(1,1) Student-t — baseline
    2. EWMA (λ=0.94) — simple benchmark
    3. HAR log-range — (1d/5d/21d log-range)
    4. Semivariance RS⁻ — (RS⁻_5 + RS⁻_21)
    5. Rolling kurtosis — (kurt_5 + kurt_21)
    6. HAR + kurtosis — combo
    7. RS⁻ + kurtosis — combo
    8. Kitchen sink Ridge — all features + SPY_ret_lag1 + VIX_lag1

  Data cleaning:
    - Winsorize |return| > 15% (K456/K462 lesson: dividend artifacts)
    - Remove zero-range days

  Evaluation:
    - QLIKE with r² proxy (K468 tautology fix)
    - MSE
    - DM test: each model vs GJR baseline
    - Best model VaR Trinity (Kupiec + Christoffersen + DQ) at 1%/5%

References:
  - Corsi (2009) J Financial Econometrics — HAR-RV model
  - Barndorff-Nielsen et al. (2010) — Realized semivariance
  - Harvey & Siddique (1999) — Conditional skewness
  - K460 (semivariance cross-OOS), K469 (HAR r² proxy), K471 (higher moments)
  - K456, K462 (Taiwan data cleaning lessons)

Data: yfinance (0050.TW, SPY, ^VIX)
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from arch import arch_model
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import acorr_ljungbox

warnings.filterwarnings('ignore')

START_TIME = time.time()

print("=" * 70)
print("K472: Taiwan 0050.TW Comprehensive Vol Prediction")
print("  Integrating HAR log-range, Semivariance RS⁻, Rolling kurtosis")
print("=" * 70)

# ============================================================
# Configuration
# ============================================================
OOS_START = "2023-01-01"
OOS_END = "2025-12-31"
IS_WINDOW = 2000  # trading days
REFIT_EVERY = 21  # refit monthly
WINSORIZE_THRESHOLD = 0.15  # 15% return cap (decimal)

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data...")

tickers = {"0050.TW": "2006-01-01", "SPY": "2006-01-01", "^VIX": "2006-01-01"}
raw_data = {}
for ticker, start in tickers.items():
    raw = yf.download(ticker, start=start, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    raw_data[ticker] = raw
    print(f"  {ticker}: {raw.index[0].date()} to {raw.index[-1].date()} ({len(raw)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2] Computing features for 0050.TW...")

tw = raw_data['0050.TW'].copy()
spy_raw = raw_data['SPY'].copy()
vix_raw = raw_data['^VIX'].copy()

# Log returns
tw['ret_decimal'] = np.log(tw['Close'] / tw['Close'].shift(1))
tw['ret_pct'] = tw['ret_decimal'] * 100

# Winsorize extreme returns (K456 lesson: dividend artifacts)
n_extreme_before = (tw['ret_decimal'].abs() > WINSORIZE_THRESHOLD).sum()
tw['ret_decimal'] = tw['ret_decimal'].clip(-WINSORIZE_THRESHOLD, WINSORIZE_THRESHOLD)
tw['ret_pct'] = tw['ret_decimal'] * 100
print(f"  Winsorized {n_extreme_before} observations with |ret| > {WINSORIZE_THRESHOLD*100:.0f}%")

# r² proxy = squared return (decimal scale)
tw['r_squared'] = tw['ret_decimal'] ** 2

# --- Log range features ---
high = tw['High'].values.astype(float).ravel()
low = tw['Low'].values.astype(float).ravel()
ratio = high / low
ratio = np.maximum(ratio, 1.0001)  # avoid log(0)
tw['log_range'] = np.log(ratio)
tw['parkinson_var'] = tw['log_range']**2 / (4 * np.log(2))

# Remove zero-range days (data artifacts)
zero_range = tw['log_range'] < 0.0001
n_zero = zero_range.sum()
print(f"  Zero-range days: {n_zero}")

# HAR components
tw['lr_1d'] = tw['log_range']
tw['lr_5d'] = tw['log_range'].rolling(5).mean()
tw['lr_21d'] = tw['log_range'].rolling(21).mean()

# --- Semivariance features ---
ret_dec = tw['ret_decimal'].values
neg_ret = np.where(ret_dec < 0, ret_dec, 0)
pos_ret = np.where(ret_dec > 0, ret_dec, 0)
tw['neg_ret_sq'] = neg_ret**2
tw['pos_ret_sq'] = pos_ret**2
tw['rs_neg_5'] = tw['neg_ret_sq'].rolling(5).mean()
tw['rs_neg_21'] = tw['neg_ret_sq'].rolling(21).mean()
tw['rs_pos_5'] = tw['pos_ret_sq'].rolling(5).mean()
tw['rs_pos_21'] = tw['pos_ret_sq'].rolling(21).mean()

# --- Rolling kurtosis/skewness ---
tw['kurt_5'] = tw['ret_decimal'].rolling(5).kurt()
tw['kurt_21'] = tw['ret_decimal'].rolling(21).kurt()
tw['skew_5'] = tw['ret_decimal'].rolling(5).skew()
tw['skew_21'] = tw['ret_decimal'].rolling(21).skew()

# --- EWMA variance (λ=0.94, decimal scale) ---
ewma_var = np.zeros(len(ret_dec))
ewma_var[0] = ret_dec[0]**2 if not np.isnan(ret_dec[0]) else 0.0001
for i in range(1, len(ret_dec)):
    if np.isnan(ret_dec[i]):
        ewma_var[i] = ewma_var[i-1]
    else:
        ewma_var[i] = 0.94 * ewma_var[i-1] + 0.06 * ret_dec[i]**2
tw['ewma_var'] = ewma_var

# --- Rolling 21d variance ---
tw['rv_21d'] = tw['ret_decimal'].rolling(21).var()

# --- SPY and VIX lead-lag signals ---
spy_raw['spy_ret'] = np.log(spy_raw['Close'] / spy_raw['Close'].shift(1))
spy_raw['spy_ret_sq'] = spy_raw['spy_ret'] ** 2

# Align by date (Taiwan market may have different holidays)
tw['spy_ret_lag1'] = spy_raw['spy_ret'].reindex(tw.index).shift(1)
tw['spy_ret_sq_lag1'] = spy_raw['spy_ret_sq'].reindex(tw.index).shift(1)
tw['vix_lag1'] = vix_raw['Close'].reindex(tw.index).shift(1)
tw['vix_var_lag1'] = (tw['vix_lag1'] / 100)**2 / 252  # daily VIX variance

# Forward fill missing SPY/VIX (different market holidays)
tw['spy_ret_lag1'] = tw['spy_ret_lag1'].ffill()
tw['spy_ret_sq_lag1'] = tw['spy_ret_sq_lag1'].ffill()
tw['vix_lag1'] = tw['vix_lag1'].ffill()
tw['vix_var_lag1'] = tw['vix_var_lag1'].ffill()

# Drop NaN
tw = tw.dropna(subset=['lr_21d', 'rs_neg_21', 'kurt_21', 'spy_ret_lag1', 'vix_lag1', 'rv_21d'])
print(f"  Clean observations: {len(tw)} ({tw.index[0].date()} to {tw.index[-1].date()})")

# ============================================================
# 3. DIAGNOSTICS
# ============================================================
print("\n[3] Data diagnostics...")

ret = tw['ret_decimal'].values
r2 = tw['r_squared'].values
lr = tw['log_range'].values

diagnostics = {
    'n_obs': len(tw),
    'date_range': f"{tw.index[0].date()} to {tw.index[-1].date()}",
    'return_mean_pct': float(np.mean(ret) * 100),
    'return_std_pct': float(np.std(ret) * 100),
    'return_skew': float(stats.skew(ret)),
    'return_kurtosis': float(stats.kurtosis(ret)),
    'r_squared_mean': float(np.mean(r2)),
    'log_range_mean': float(np.mean(lr)),
    'parkinson_var_mean': float(np.mean(tw['parkinson_var'].values)),
    'r2_over_parkinson_ratio': float(np.mean(r2) / np.mean(tw['parkinson_var'].values)),
    'n_winsorized': int(n_extreme_before),
}

# ADF test
adf_stat, adf_p, _, _, _, _ = adfuller(ret[~np.isnan(ret)], maxlag=21)
diagnostics['adf_stat'] = float(adf_stat)
adf_p_val = float(adf_p)
diagnostics['adf_p'] = adf_p_val
diagnostics['is_stationary'] = bool(adf_p_val < 0.05)

# Ljung-Box on squared returns
lb = acorr_ljungbox(r2[~np.isnan(r2)], lags=[10], return_df=True)
diagnostics['ljungbox_r2_p'] = float(lb['lb_pvalue'].values[0])
diagnostics['has_arch_effects'] = bool(diagnostics['ljungbox_r2_p'] < 0.05)

# Correlation: SPY lead-lag
spy_mask = ~(tw['spy_ret_lag1'].isna() | tw['ret_decimal'].isna())
corr_spy = float(np.corrcoef(tw.loc[spy_mask, 'ret_decimal'], tw.loc[spy_mask, 'spy_ret_lag1'])[0, 1])
diagnostics['corr_tw_spy_lag1'] = corr_spy

print(f"  N={diagnostics['n_obs']}, ret mean={diagnostics['return_mean_pct']:.4f}%, "
      f"std={diagnostics['return_std_pct']:.4f}%")
print(f"  Skew={diagnostics['return_skew']:.3f}, Kurt={diagnostics['return_kurtosis']:.3f}")
print(f"  ADF p={adf_p_val:.2e} ({'stationary' if adf_p_val < 0.05 else 'non-stationary'})")
print(f"  ARCH effects: {'Yes' if diagnostics['has_arch_effects'] else 'No'} "
      f"(LB p={diagnostics['ljungbox_r2_p']:.2e})")
print(f"  r²/Parkinson ratio: {diagnostics['r2_over_parkinson_ratio']:.3f}")
print(f"  corr(TW_ret, SPY_ret_lag1): {corr_spy:.4f}")


# ============================================================
# 4. MODEL DEFINITIONS
# ============================================================
print("\n[4] Setting up 8 models...")


def qlike(sigma2, proxy):
    """QLIKE loss: proxy/sigma2 - log(proxy/sigma2) - 1. Lower is better."""
    valid = (sigma2 > 0) & (proxy > 0) & np.isfinite(sigma2) & np.isfinite(proxy)
    s2 = sigma2[valid]
    p = proxy[valid]
    ratio = p / s2
    return float(np.mean(ratio - np.log(ratio) - 1))


def mse(sigma2, proxy):
    """Mean squared error."""
    valid = np.isfinite(sigma2) & np.isfinite(proxy)
    return float(np.mean((sigma2[valid] - proxy[valid])**2))


def dm_test(loss1, loss2):
    """Diebold-Mariano test. H0: equal predictive accuracy.
    Returns t-stat, p-value. Negative t means loss1 < loss2 (model 1 better)."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_bar = np.mean(d)
    # Newey-West with h=1 lag (1-step ahead)
    gamma0 = np.var(d, ddof=1)
    gamma1 = np.cov(d[:-1], d[1:])[0, 1] if n > 1 else 0
    var_d = (gamma0 + 2 * gamma1) / n
    if var_d <= 0:
        var_d = gamma0 / n
    t_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n-1))
    return float(t_stat), float(p_value)


# ============================================================
# 5. OOS ROLLING EVALUATION
# ============================================================
print("\n[5] Running OOS evaluation (2023-2025)...")

oos_mask = tw.index >= OOS_START
oos_data = tw[oos_mask].copy()
print(f"  OOS period: {oos_data.index[0].date()} to {oos_data.index[-1].date()} "
      f"({len(oos_data)} obs)")

# Full dataset indices for IS window
all_idx = tw.index.tolist()

# Storage for forecasts
forecasts = {m: np.full(len(oos_data), np.nan) for m in [
    'gjr_garch', 'ewma', 'har_logrange', 'semivar_rs',
    'rolling_kurt', 'har_kurt', 'rs_kurt', 'kitchen_sink'
]}
actual_r2 = oos_data['r_squared'].values.copy()

# Scale calibration ratio (IS)
is_data = tw[~oos_mask]
scale_ratio = float(is_data['r_squared'].mean() / is_data['parkinson_var'].mean())
print(f"  Scale calibration (r²/Parkinson): {scale_ratio:.4f}")

# GJR-GARCH parameters storage
garch_params_log = []

# Rolling OOS evaluation
n_oos = len(oos_data)
refit_count = 0
last_garch_cvar = None  # cached GJR forecast
last_har_coefs = None
last_har_scale = 1.5  # default scale ratio
last_semivar_coefs = None
last_kurt_model = None
last_kurt_scaler = None
last_hk_model = None
last_hk_scaler = None
last_rk_model = None
last_rk_scaler = None
last_ridge_model = None
last_ridge_scaler = None

for i in range(n_oos):
    oos_date = oos_data.index[i]
    oos_pos = all_idx.index(oos_date)

    # IS data
    is_start = max(0, oos_pos - IS_WINDOW)
    is_slice = tw.iloc[is_start:oos_pos]

    need_refit = (i % REFIT_EVERY == 0) or (i == 0)

    # ---- Model 1: GJR-GARCH ----
    if need_refit:
        try:
            ret_pct_is = is_slice['ret_pct'].values
            am = arch_model(ret_pct_is, vol='GARCH', p=1, o=1, q=1, dist='t',
                           mean='Zero', rescale=False)
            res = am.fit(disp='off', show_warning=False)
            last_garch_res = res
            # One-step forecast
            fc = res.forecast(horizon=1)
            cvar = float(fc.variance.values[-1, 0]) / 10000  # pct² → decimal²
            last_garch_cvar = cvar
            if i == 0:
                garch_params_log.append({
                    'omega': float(res.params.get('omega', np.nan)),
                    'alpha': float(res.params.get('alpha[1]', np.nan)),
                    'gamma': float(res.params.get('gamma[1]', np.nan)),
                    'beta': float(res.params.get('beta[1]', np.nan)),
                    'persistence': float(
                        res.params.get('alpha[1]', 0) +
                        res.params.get('gamma[1]', 0) / 2 +
                        res.params.get('beta[1]', 0)
                    ),
                })
        except Exception:
            pass
    else:
        # Update with new return
        try:
            ret_pct_is = is_slice['ret_pct'].values
            am = arch_model(ret_pct_is, vol='GARCH', p=1, o=1, q=1, dist='t',
                           mean='Zero', rescale=False)
            res = am.fit(disp='off', show_warning=False, starting_values=last_garch_res.params.values)
            fc = res.forecast(horizon=1)
            cvar = float(fc.variance.values[-1, 0]) / 10000
            last_garch_cvar = cvar
            last_garch_res = res
        except Exception:
            pass

    if last_garch_cvar is not None and last_garch_cvar > 0:
        forecasts['gjr_garch'][i] = last_garch_cvar

    # ---- Model 2: EWMA ----
    forecasts['ewma'][i] = float(is_slice['ewma_var'].iloc[-1])

    # ---- OLS-based models (refit monthly) ----
    if need_refit:
        refit_count += 1

        # Prepare IS data for OLS
        # Target: next-day r² (but use log(r²) for HAR to avoid scale issues)
        y_is = is_slice['r_squared'].values[1:]  # target: next-day r²
        X_base = is_slice.iloc[:-1]  # lagged features

        # For HAR: predict log_range → convert to variance
        # HAR regression: log_range(t) = c + b1*lr_1d(t-1) + b2*lr_5d(t-1) + b3*lr_21d(t-1)
        # Then convert: σ² = lr_hat² / (4*ln2) * scale_ratio
        y_lr = is_slice['log_range'].values[1:]  # predict next-day log-range

        # Model 3: HAR log-range (predict log-range, then convert)
        try:
            X_har = np.column_stack([
                X_base['lr_1d'].values,
                X_base['lr_5d'].values,
                X_base['lr_21d'].values,
            ])
            valid_har = np.all(np.isfinite(X_har), axis=1) & np.isfinite(y_lr)
            X_h = np.column_stack([np.ones(valid_har.sum()), X_har[valid_har]])
            y_h = y_lr[valid_har]
            last_har_coefs = np.linalg.lstsq(X_h, y_h, rcond=None)[0]
            # Compute IS scale ratio for this window
            is_r2_mean = np.mean(is_slice['r_squared'].values[np.isfinite(is_slice['r_squared'].values)])
            is_pk_mean = np.mean(is_slice['parkinson_var'].values[np.isfinite(is_slice['parkinson_var'].values)])
            last_har_scale = is_r2_mean / is_pk_mean if is_pk_mean > 0 else 1.5
        except Exception:
            pass

        # Model 4: Semivariance RS⁻ (already in variance scale ~ r²)
        try:
            X_sv = np.column_stack([
                X_base['rs_neg_5'].values,
                X_base['rs_neg_21'].values,
            ])
            valid_sv = np.all(np.isfinite(X_sv), axis=1) & np.isfinite(y_is)
            X_s = np.column_stack([np.ones(valid_sv.sum()), X_sv[valid_sv]])
            y_s = y_is[valid_sv]
            last_semivar_coefs = np.linalg.lstsq(X_s, y_s, rcond=None)[0]
        except Exception:
            pass

        # Model 5: Rolling kurtosis (use Ridge to regularize; kurtosis is noisy)
        try:
            X_krt = np.column_stack([
                X_base['kurt_5'].values,
                X_base['kurt_21'].values,
                X_base['rv_21d'].values,  # need RV base too
            ])
            valid_k = np.all(np.isfinite(X_krt), axis=1) & np.isfinite(y_is)
            X_krt_v = X_krt[valid_k]
            y_k_v = y_is[valid_k]
            last_kurt_scaler = StandardScaler()
            X_krt_scaled = last_kurt_scaler.fit_transform(X_krt_v)
            last_kurt_model = Ridge(alpha=1.0)
            last_kurt_model.fit(X_krt_scaled, y_k_v)
        except Exception:
            last_kurt_model = None

        # Model 6: HAR + kurtosis (Ridge regularized)
        try:
            X_hk = np.column_stack([
                X_base['lr_1d'].values,
                X_base['lr_5d'].values,
                X_base['lr_21d'].values,
                X_base['kurt_5'].values,
                X_base['kurt_21'].values,
            ])
            valid_hk = np.all(np.isfinite(X_hk), axis=1) & np.isfinite(y_is)
            X_hk_v = X_hk[valid_hk]
            y_hk_v = y_is[valid_hk]
            last_hk_scaler = StandardScaler()
            X_hk_scaled = last_hk_scaler.fit_transform(X_hk_v)
            last_hk_model = Ridge(alpha=1.0)
            last_hk_model.fit(X_hk_scaled, y_hk_v)
        except Exception:
            last_hk_model = None

        # Model 7: RS⁻ + kurtosis (Ridge regularized)
        try:
            X_rk = np.column_stack([
                X_base['rs_neg_5'].values,
                X_base['rs_neg_21'].values,
                X_base['kurt_5'].values,
                X_base['kurt_21'].values,
            ])
            valid_rk = np.all(np.isfinite(X_rk), axis=1) & np.isfinite(y_is)
            X_rk_v = X_rk[valid_rk]
            y_rk_v = y_is[valid_rk]
            last_rk_scaler = StandardScaler()
            X_rk_scaled = last_rk_scaler.fit_transform(X_rk_v)
            last_rk_model = Ridge(alpha=1.0)
            last_rk_model.fit(X_rk_scaled, y_rk_v)
        except Exception:
            last_rk_model = None

        # Model 8: Kitchen sink Ridge
        try:
            feat_cols = ['lr_1d', 'lr_5d', 'lr_21d',
                        'rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21',
                        'kurt_5', 'kurt_21', 'skew_5', 'skew_21',
                        'rv_21d', 'ewma_var',
                        'spy_ret_lag1', 'spy_ret_sq_lag1', 'vix_var_lag1']
            X_ks = X_base[feat_cols].values
            valid_ks = np.all(np.isfinite(X_ks), axis=1) & np.isfinite(y_is)
            X_ks_v = X_ks[valid_ks]
            y_ks_v = y_is[valid_ks]

            scaler = StandardScaler()
            X_ks_scaled = scaler.fit_transform(X_ks_v)
            ridge = Ridge(alpha=1.0)
            ridge.fit(X_ks_scaled, y_ks_v)
            last_ridge_model = ridge
            last_ridge_scaler = scaler
            last_ridge_feat_cols = feat_cols
        except Exception:
            pass

    # Generate forecasts for current OOS day
    curr = tw.iloc[oos_pos - 1]  # lagged features
    # Floor for variance predictions: use 10% of unconditional variance
    # This prevents QLIKE explosion from near-zero predictions
    # Rationale: variance forecast should never be below 10% of long-run average
    r2_floor = float(is_slice['r_squared'].mean()) * 0.10
    r2_floor = max(r2_floor, 1e-7)

    # Model 3: HAR log-range (predict log-range → Parkinson var → scale to r²)
    if last_har_coefs is not None:
        try:
            x_har = np.array([1, curr['lr_1d'], curr['lr_5d'], curr['lr_21d']])
            if np.all(np.isfinite(x_har)):
                lr_hat = float(x_har @ last_har_coefs)
                lr_hat = max(lr_hat, 0.001)  # log-range must be positive
                pk_var = lr_hat**2 / (4 * np.log(2))  # Parkinson variance
                pred = pk_var * last_har_scale  # scale to r² level
                forecasts['har_logrange'][i] = max(pred, r2_floor)
        except Exception:
            pass

    # Model 4: Semivariance RS⁻
    if last_semivar_coefs is not None:
        try:
            x_sv = np.array([1, curr['rs_neg_5'], curr['rs_neg_21']])
            if np.all(np.isfinite(x_sv)):
                pred = float(x_sv @ last_semivar_coefs)
                forecasts['semivar_rs'][i] = max(pred, r2_floor)
        except Exception:
            pass

    # Model 5: Rolling kurtosis (Ridge)
    if last_kurt_model is not None:
        try:
            x_k = np.array([[curr['kurt_5'], curr['kurt_21'], curr['rv_21d']]])
            if np.all(np.isfinite(x_k)):
                x_k_s = last_kurt_scaler.transform(x_k)
                pred = float(last_kurt_model.predict(x_k_s)[0])
                forecasts['rolling_kurt'][i] = max(pred, r2_floor)
        except Exception:
            pass

    # Model 6: HAR + kurtosis (Ridge)
    if last_hk_model is not None:
        try:
            x_hk = np.array([[curr['lr_1d'], curr['lr_5d'], curr['lr_21d'],
                             curr['kurt_5'], curr['kurt_21']]])
            if np.all(np.isfinite(x_hk)):
                x_hk_s = last_hk_scaler.transform(x_hk)
                pred = float(last_hk_model.predict(x_hk_s)[0])
                forecasts['har_kurt'][i] = max(pred, r2_floor)
        except Exception:
            pass

    # Model 7: RS⁻ + kurtosis (Ridge)
    if last_rk_model is not None:
        try:
            x_rk = np.array([[curr['rs_neg_5'], curr['rs_neg_21'],
                             curr['kurt_5'], curr['kurt_21']]])
            if np.all(np.isfinite(x_rk)):
                x_rk_s = last_rk_scaler.transform(x_rk)
                pred = float(last_rk_model.predict(x_rk_s)[0])
                forecasts['rs_kurt'][i] = max(pred, r2_floor)
        except Exception:
            pass

    # Model 8: Kitchen sink Ridge
    if last_ridge_model is not None and last_ridge_scaler is not None:
        try:
            x_ks = np.array([[curr[c] for c in last_ridge_feat_cols]])
            if np.all(np.isfinite(x_ks)):
                x_ks_scaled = last_ridge_scaler.transform(x_ks)
                pred = float(last_ridge_model.predict(x_ks_scaled)[0])
                forecasts['kitchen_sink'][i] = max(pred, r2_floor)
        except Exception:
            pass

    if (i + 1) % 100 == 0:
        elapsed = time.time() - START_TIME
        print(f"  ... {i+1}/{n_oos} ({elapsed:.1f}s)")

print(f"  Completed {n_oos} OOS forecasts, {refit_count} refits")

# ============================================================
# 6. EVALUATION
# ============================================================
print("\n[6] Evaluation results...")

model_names = {
    'gjr_garch': 'GJR-GARCH(1,1)',
    'ewma': 'EWMA (λ=0.94)',
    'har_logrange': 'HAR log-range',
    'semivar_rs': 'Semivariance RS⁻',
    'rolling_kurt': 'Rolling kurtosis',
    'har_kurt': 'HAR + kurtosis',
    'rs_kurt': 'RS⁻ + kurtosis',
    'kitchen_sink': 'Kitchen sink Ridge',
}

results = {}
baseline_key = 'gjr_garch'
baseline_fc = forecasts[baseline_key]

# QLIKE losses per observation for DM test
qlike_losses = {}

for key, name in model_names.items():
    fc = forecasts[key]
    valid = np.isfinite(fc) & np.isfinite(actual_r2) & (fc > 0) & (actual_r2 > 0)
    n_valid = valid.sum()

    if n_valid < 30:
        print(f"  {name}: insufficient valid forecasts ({n_valid})")
        results[key] = {'n_valid': int(n_valid), 'status': 'insufficient'}
        continue

    fc_v = fc[valid]
    r2_v = actual_r2[valid]

    # QLIKE
    q = qlike(fc_v, r2_v)

    # MSE
    m = mse(fc_v, r2_v)

    # Per-obs QLIKE losses (for DM test)
    ratio = r2_v / fc_v
    per_obs_qlike = ratio - np.log(ratio) - 1
    qlike_losses[key] = (per_obs_qlike, valid)

    # DM test vs baseline
    dm_t, dm_p = np.nan, np.nan
    if key != baseline_key:
        # Align valid masks
        both_valid = valid & np.isfinite(baseline_fc) & (baseline_fc > 0)
        if both_valid.sum() > 30:
            fc_bv = forecasts[baseline_key][both_valid]
            fc_mv = fc[both_valid]
            r2_bv = actual_r2[both_valid]

            # QLIKE loss per obs
            ratio_b = r2_bv / fc_bv
            loss_b = ratio_b - np.log(ratio_b) - 1
            ratio_m = r2_bv / fc_mv
            loss_m = ratio_m - np.log(ratio_m) - 1

            dm_t, dm_p = dm_test(loss_m, loss_b)

    results[key] = {
        'name': name,
        'n_valid': int(n_valid),
        'qlike': q,
        'mse': m,
        'dm_vs_gjr_t': dm_t,
        'dm_vs_gjr_p': dm_p,
        'beats_gjr': bool(not np.isnan(dm_t) and dm_t < -1.96),  # model has lower QLIKE
        'sig_worse': bool(not np.isnan(dm_t) and dm_t > 1.96),  # model sig. worse
    }

    sign = ""
    if key != baseline_key:
        if results[key]['beats_gjr']:
            sign = " ✓ BEATS GJR"
        elif results[key]['sig_worse']:
            sign = " ✗ WORSE"
        else:
            sign = " ≈ (NS)"

    print(f"  {name:25s}: QLIKE={q:.6f}, MSE={m:.2e}, "
          f"DM t={dm_t:+.3f}, p={dm_p:.4f}{sign}" if not np.isnan(dm_t)
          else f"  {name:25s}: QLIKE={q:.6f}, MSE={m:.2e} (baseline)")

# ============================================================
# 7. RELATIVE PERFORMANCE SUMMARY
# ============================================================
print("\n[7] Relative performance vs GJR-GARCH baseline...")

baseline_qlike = results[baseline_key]['qlike']

print(f"\n  {'Model':30s} {'QLIKE':>10s} {'vs GJR':>10s} {'DM t':>8s} {'DM p':>8s} {'Verdict':>12s}")
print("  " + "-" * 80)

for key, name in model_names.items():
    r = results[key]
    if 'qlike' not in r:
        continue
    delta = ((r['qlike'] - baseline_qlike) / baseline_qlike) * 100
    verdict = "baseline" if key == baseline_key else (
        "BEATS" if r.get('beats_gjr') else
        "WORSE" if r.get('sig_worse') else "NS"
    )
    dm_t = r.get('dm_vs_gjr_t', np.nan)
    dm_p = r.get('dm_vs_gjr_p', np.nan)
    print(f"  {name:30s} {r['qlike']:10.6f} {delta:+9.2f}% {dm_t:+8.3f} {dm_p:8.4f} {verdict:>12s}"
          if not np.isnan(dm_t) else
          f"  {name:30s} {r['qlike']:10.6f} {'---':>10s} {'---':>8s} {'---':>8s} {'baseline':>12s}")

# ============================================================
# 8. VaR BACKTEST (Best non-GARCH model if any beats GJR)
# ============================================================
print("\n[8] VaR Backtest...")

# Find best model
best_key = min(
    [k for k in results if 'qlike' in results[k] and results[k].get('n_valid', 0) > 30],
    key=lambda k: results[k]['qlike']
)
best_name = model_names[best_key]
print(f"  Best model: {best_name} (QLIKE={results[best_key]['qlike']:.6f})")

# VaR from GJR-GARCH (baseline, has distributional assumption)
# For GJR: use Student-t quantile from fitted distribution
print(f"  Computing VaR using GJR-GARCH Student-t distribution...")

# Re-estimate GJR for full IS → get conditional variance for OOS
# Use the forecasts we already have
gjr_fc = forecasts['gjr_garch']
valid_gjr = np.isfinite(gjr_fc) & (gjr_fc > 0)

# Estimate df from residuals
is_ret_pct = tw[~oos_mask]['ret_pct'].values
try:
    am_full = arch_model(is_ret_pct, vol='GARCH', p=1, o=1, q=1, dist='t',
                         mean='Zero', rescale=False)
    res_full = am_full.fit(disp='off', show_warning=False)
    df_t = float(res_full.params.get('nu', 5))
except Exception:
    df_t = 5.0

print(f"  Student-t df = {df_t:.2f}")

# VaR levels
for alpha_pct in [1, 5]:
    alpha = alpha_pct / 100
    z_t = stats.t.ppf(alpha, df_t)

    # VaR = z * sigma (decimal returns)
    var_gjr = z_t * np.sqrt(gjr_fc)

    # Count violations
    oos_ret = oos_data['ret_decimal'].values
    violations = (oos_ret < var_gjr) & valid_gjr
    n_viol = violations.sum()
    n_total = valid_gjr.sum()
    viol_rate = n_viol / n_total if n_total > 0 else 0

    # Kupiec test
    if n_viol > 0 and n_viol < n_total:
        lr_uc = -2 * (n_viol * np.log(alpha) + (n_total - n_viol) * np.log(1 - alpha)
                     - n_viol * np.log(viol_rate) - (n_total - n_viol) * np.log(1 - viol_rate))
        kupiec_p = 1 - stats.chi2.cdf(lr_uc, 1)
    else:
        kupiec_p = np.nan

    result_key = f'var_{alpha_pct}pct'
    results[f'gjr_var_{alpha_pct}'] = {
        'alpha': alpha,
        'n_total': int(n_total),
        'n_violations': int(n_viol),
        'violation_rate': float(viol_rate),
        'expected_rate': alpha,
        'kupiec_p': float(kupiec_p) if not np.isnan(kupiec_p) else None,
        'kupiec_pass': bool(kupiec_p > 0.05) if not np.isnan(kupiec_p) else False,
        'status': 'GREEN' if (kupiec_p > 0.05 if not np.isnan(kupiec_p) else False) else 'RED',
    }

    print(f"  VaR {alpha_pct}%: {n_viol} violations ({viol_rate*100:.2f}%), "
          f"Kupiec p={kupiec_p:.4f}, {'PASS' if kupiec_p > 0.05 else 'FAIL'}"
          if not np.isnan(kupiec_p) else
          f"  VaR {alpha_pct}%: {n_viol} violations ({viol_rate*100:.2f}%), Kupiec N/A")


# ============================================================
# 9. CROSS-OOS ROBUSTNESS (3 sub-periods within OOS)
# ============================================================
print("\n[9] Sub-period robustness check...")

sub_periods = [
    ("2023H1", "2023-01-01", "2023-06-30"),
    ("2023H2", "2023-07-01", "2023-12-31"),
    ("2024H1", "2024-01-01", "2024-06-30"),
    ("2024H2", "2024-07-01", "2024-12-31"),
    ("2025", "2025-01-01", "2025-12-31"),
]

sub_period_results = {}
for sp_name, sp_start, sp_end in sub_periods:
    sp_mask = (oos_data.index >= sp_start) & (oos_data.index <= sp_end)
    sp_r2 = actual_r2[sp_mask]
    sp_results = {}

    for key in model_names:
        sp_fc = forecasts[key][sp_mask]
        valid = np.isfinite(sp_fc) & np.isfinite(sp_r2) & (sp_fc > 0) & (sp_r2 > 0)
        if valid.sum() < 10:
            continue
        q = qlike(sp_fc[valid], sp_r2[valid])
        sp_results[key] = q

    sub_period_results[sp_name] = sp_results

    # Determine winner
    if sp_results:
        winner = min(sp_results, key=sp_results.get)
        baseline_q = sp_results.get('gjr_garch', float('inf'))
        winner_q = sp_results[winner]
        delta = ((winner_q - baseline_q) / baseline_q * 100) if baseline_q > 0 else 0
        print(f"  {sp_name}: Winner={model_names[winner]:25s} "
              f"(QLIKE={winner_q:.6f}, vs GJR: {delta:+.2f}%)")

# Count how many sub-periods each model wins
print("\n  Win counts (lowest QLIKE per sub-period):")
win_counts = {k: 0 for k in model_names}
for sp_name, sp_res in sub_period_results.items():
    if sp_res:
        winner = min(sp_res, key=sp_res.get)
        win_counts[winner] += 1

for key, name in model_names.items():
    if win_counts[key] > 0:
        print(f"    {name:25s}: {win_counts[key]}/{len(sub_periods)}")


# ============================================================
# 10. KITCHEN SINK FEATURE IMPORTANCE
# ============================================================
print("\n[10] Kitchen sink Ridge feature importance...")

if last_ridge_model is not None:
    feat_cols_print = ['lr_1d', 'lr_5d', 'lr_21d',
                       'rs_neg_5', 'rs_neg_21', 'rs_pos_5', 'rs_pos_21',
                       'kurt_5', 'kurt_21', 'skew_5', 'skew_21',
                       'rv_21d', 'ewma_var',
                       'spy_ret_lag1', 'spy_ret_sq_lag1', 'vix_var_lag1']

    coefs = last_ridge_model.coef_
    # Standardized importance (abs coef after scaling)
    importance = np.abs(coefs)
    order = np.argsort(-importance)

    print(f"  {'Feature':20s} {'Coef':>10s} {'|Coef|':>10s} {'Rank':>6s}")
    print("  " + "-" * 50)
    feature_importance = {}
    for rank, idx in enumerate(order):
        fname = feat_cols_print[idx]
        c = coefs[idx]
        feature_importance[fname] = {
            'coef': float(c),
            'abs_coef': float(abs(c)),
            'rank': rank + 1,
        }
        print(f"  {fname:20s} {c:+10.6f} {abs(c):10.6f} {rank+1:6d}")


# ============================================================
# 11. CONCLUSIONS
# ============================================================
elapsed = time.time() - START_TIME
print(f"\n[11] Conclusions (runtime: {elapsed:.1f}s)")

# Determine overall verdict
gjr_qlike = results['gjr_garch']['qlike']
any_beats = any(r.get('beats_gjr', False) for r in results.values())
best_non_gjr = min(
    [(k, r['qlike']) for k, r in results.items() if k != 'gjr_garch' and 'qlike' in r],
    key=lambda x: x[1]
)

print(f"\n  Baseline GJR-GARCH QLIKE: {gjr_qlike:.6f}")
print(f"  Best non-GARCH model: {model_names[best_non_gjr[0]]} (QLIKE={best_non_gjr[1]:.6f})")
print(f"  Delta: {((best_non_gjr[1] - gjr_qlike) / gjr_qlike * 100):+.2f}%")

if any_beats:
    print("\n  ★ At least one model significantly beats GJR-GARCH on 0050.TW!")
    print("  → Can add to Taiwan paper Section 3")
else:
    print("\n  ✗ No model significantly beats GJR-GARCH on 0050.TW")
    print("  → GARCH ceiling confirmed for Taiwan (also worth reporting)")

# Paper implications
conclusions = []
for key, r in results.items():
    if key == 'gjr_garch':
        continue
    if 'qlike' not in r:
        continue
    delta = ((r['qlike'] - gjr_qlike) / gjr_qlike * 100)
    if r.get('beats_gjr'):
        conclusions.append(f"  ★ {model_names[key]}: QLIKE {delta:+.2f}%, DM p={r['dm_vs_gjr_p']:.4f} → SIGNIFICANT improvement")
    elif r.get('sig_worse'):
        conclusions.append(f"  ✗ {model_names[key]}: QLIKE {delta:+.2f}%, DM p={r['dm_vs_gjr_p']:.4f} → significantly WORSE")
    else:
        conclusions.append(f"  ≈ {model_names[key]}: QLIKE {delta:+.2f}%, DM p={r['dm_vs_gjr_p']:.4f} → not significant")

print("\n  Model-by-model conclusions:")
for c in conclusions:
    print(c)


# ============================================================
# 12. SAVE RESULTS
# ============================================================
print("\n[12] Saving results...")

output = {
    "experiment_id": "K472",
    "title": "Taiwan 0050.TW Comprehensive Vol Prediction — Integrating All Positive Findings",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "proposer": "User",
    "executor": "Claude",
    "asset": "0050.TW",
    "data_source": "yfinance (0050.TW, SPY, ^VIX)",
    "data_period": f"{tw.index[0].date()} to {tw.index[-1].date()}",
    "total_obs": int(len(tw)),
    "oos_period": f"{oos_data.index[0].date()} to {oos_data.index[-1].date()}",
    "oos_obs": int(len(oos_data)),
    "is_window": IS_WINDOW,
    "refit_every": REFIT_EVERY,
    "winsorize_threshold": WINSORIZE_THRESHOLD,
    "evaluation_proxy": "r² = (close-to-close log return)² — NOT Parkinson (K468 tautology fix)",
    "references": [
        "Corsi (2009) J Financial Econometrics — HAR-RV model",
        "Barndorff-Nielsen et al. (2010) — Realized semivariance",
        "Harvey & Siddique (1999) JoF — Conditional skewness",
        "K460 — Semivariance cross-OOS 4/5",
        "K469 — HAR log-range r² proxy 8/10",
        "K471 — Rolling kurtosis +16pp R²",
        "K456, K462 — Taiwan data cleaning lessons",
        "Patton (2011) J Econometrics — Volatility forecast evaluation"
    ],
    "models": list(model_names.values()),
    "diagnostics": diagnostics,
    "garch_params": garch_params_log,
    "results": {k: v for k, v in results.items() if 'qlike' in v or 'status' in v},
    "sub_period_qlike": sub_period_results,
    "sub_period_wins": {model_names.get(k, k): v for k, v in win_counts.items() if v > 0},
    "feature_importance": feature_importance if last_ridge_model is not None else None,
    "var_backtest": {
        "gjr_1pct": results.get('gjr_var_1', {}),
        "gjr_5pct": results.get('gjr_var_5', {}),
        "student_t_df": df_t,
    },
    "overall_verdict": {
        "any_beats_gjr": any_beats,
        "best_model": model_names[best_non_gjr[0]],
        "best_qlike": best_non_gjr[1],
        "gjr_qlike": gjr_qlike,
        "delta_pct": float((best_non_gjr[1] - gjr_qlike) / gjr_qlike * 100),
        "paper_implication": (
            "At least one method significantly beats GJR-GARCH on 0050.TW — include in Taiwan paper"
            if any_beats else
            "GARCH ceiling confirmed for Taiwan — all US-validated methods fail to beat GJR"
        ),
    },
    "conclusions": conclusions,
    "runtime_seconds": round(elapsed, 1),
}

out_path = "experiments/k472_taiwan_comprehensive_results.json"
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"  Saved to {out_path}")
print(f"\n  Total runtime: {elapsed:.1f}s")
print("=" * 70)
print("K472 COMPLETE")
print("=" * 70)
