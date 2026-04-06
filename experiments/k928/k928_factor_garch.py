"""
K928: Factor GARCH — Common Volatility Factor Across SPY/QQQ/GLD

Research Question:
    Does a data-driven common volatility factor (PCA on cross-asset squared returns)
    improve individual asset volatility forecasting beyond what VIX already provides?

Background:
    - T24: PCA on 22-day RV found PC1=76.6%, r(PC1,VIX)=-0.81, incremental R²=0.00%
    - K907: TCI=50% but TCI ≠ VIX (r=0.001)
    - K912: MF-GJR advantage in low VIX regimes
    - K918: BEKK no cross-spillover (SPY-GLD)

Literature:
    - Engle, Ng & Rothschild (1990): Factor ARCH
    - Patton (2011): Proxy-robust QLIKE
    - Harvey (2016): |t| > 3.0

Data Source: yfinance (SPY, QQQ, IWM, GLD, TLT, ^VIX), 2006-2026

Error log rules for this experiment:
    - DM test: use volpred.stats.model_evaluation.dm_test
    - GARCH OOS: rolling refit with recursive h[t]=f(h[t-1], r²[t-1])
    - All random seeds fixed: np.random.seed(42)
    - Statistical thresholds: Harvey |t| > 3.0, OOS >= 252 days

Approach:
    Standard GJR baseline, then MF-GJR style augmentation:
    h_t = tau_t * g_t
    where g_t is GJR(1,1,1) and tau_t = exp(delta * X_{t-1})
    This is more robust than arch library's x= parameter.
"""

import numpy as np
np.random.seed(42)

import pandas as pd
import json
import os
import sys
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime
from pathlib import Path
from scipy.optimize import minimize
from scipy.stats import spearmanr

import yfinance as yf
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from arch import arch_model
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'src'))

from volpred.stats.model_evaluation import qlike_pointwise, dm_test

OUTPUT_DIR = Path(__file__).resolve().parent

# ============================================================
# Configuration
# ============================================================
ASSETS = ['SPY', 'QQQ', 'IWM', 'GLD', 'TLT']
VIX_TICKER = '^VIX'
START_DATE = '2006-01-01'
END_DATE = '2026-04-04'
PCA_WINDOW = 250        # Rolling PCA window
GARCH_WINDOW = 2000     # In-sample GARCH estimation window
REFIT_FREQ = 63         # Refit GARCH every 63 trading days (~quarterly)
OOS_START_IDX = 2500    # Start OOS after this many observations (~10 years)

print("=" * 70)
print("K928: Factor GARCH — Common Volatility Factor")
print("=" * 70)

# ============================================================
# Step 1: Data Collection
# ============================================================
print("\n[Step 1] Downloading data...")

tickers = ASSETS + [VIX_TICKER]
data = yf.download(tickers, start=START_DATE, end=END_DATE, auto_adjust=True)

# Extract adjusted close prices
if 'Close' in data.columns.get_level_values(0):
    prices = data['Close'][ASSETS].copy()
    vix = data['Close'][VIX_TICKER].copy()
else:
    prices = data['Adj Close'][ASSETS].copy()
    vix = data['Adj Close'][VIX_TICKER].copy()

# Drop NaN rows (align all assets)
combined = pd.concat([prices, vix.rename('VIX')], axis=1).dropna()
prices = combined[ASSETS]
vix = combined['VIX']

# Calculate returns
returns = prices.pct_change().dropna()
vix = vix.reindex(returns.index)

# Squared returns as vol proxy
r2 = returns ** 2

print(f"  Data range: {returns.index[0].strftime('%Y-%m-%d')} to {returns.index[-1].strftime('%Y-%m-%d')}")
print(f"  N observations: {len(returns)}")
print(f"  Assets: {ASSETS}")

# Descriptive stats
print("\n  Descriptive Statistics (annualized vol %):")
for col in ASSETS:
    ann_vol = returns[col].std() * np.sqrt(252) * 100
    skew = returns[col].skew()
    kurt = returns[col].kurtosis()
    print(f"    {col}: vol={ann_vol:.1f}%, skew={skew:.2f}, kurt={kurt:.2f}")

# ============================================================
# Step 2: Full-sample PCA on r² matrix
# ============================================================
print("\n[Step 2] Full-sample PCA on squared returns...")

scaler = StandardScaler()
r2_std = pd.DataFrame(
    scaler.fit_transform(r2),
    index=r2.index,
    columns=r2.columns
)

pca_full = PCA(n_components=5)
pca_full.fit(r2_std)

explained = pca_full.explained_variance_ratio_
print("\n  PCA Explained Variance Ratios:")
for i, ev in enumerate(explained):
    print(f"    PC{i+1}: {ev*100:.1f}%")
print(f"    Cumulative (PC1+PC2): {sum(explained[:2])*100:.1f}%")

# Factor loadings
loadings = pd.DataFrame(
    pca_full.components_,
    columns=ASSETS,
    index=[f'PC{i+1}' for i in range(5)]
)
print("\n  Factor Loadings:")
print(loadings.round(3).to_string())

# Extract PC1 (full sample for characteristics analysis only)
pc_scores_full = pd.DataFrame(
    pca_full.transform(r2_std),
    index=r2.index,
    columns=[f'PC{i+1}' for i in range(5)]
)

# PC1 vs VIX correlation
pc1_vix_corr = pc_scores_full['PC1'].corr(vix.reindex(pc_scores_full.index))
pc1_vix_spearman = pc_scores_full['PC1'].corr(vix.reindex(pc_scores_full.index), method='spearman')

print(f"\n  PC1 vs VIX: Pearson r = {pc1_vix_corr:.3f}, Spearman rho = {pc1_vix_spearman:.3f}")

# PC1 autocorrelation
pc1_ac1 = pc_scores_full['PC1'].autocorr(lag=1)
pc1_ac5 = pc_scores_full['PC1'].autocorr(lag=5)
pc1_ac22 = pc_scores_full['PC1'].autocorr(lag=22)
print(f"  PC1 autocorrelation: lag1={pc1_ac1:.3f}, lag5={pc1_ac5:.3f}, lag22={pc1_ac22:.3f}")

# ============================================================
# Step 3: Rolling PCA for OOS
# ============================================================
print("\n[Step 3] Rolling PCA (window={})...".format(PCA_WINDOW))

rolling_pc1 = pd.Series(np.nan, index=r2.index)
rolling_explained = pd.Series(np.nan, index=r2.index)
rolling_loadings = {}

for i in range(PCA_WINDOW, len(r2)):
    window_data = r2.iloc[i - PCA_WINDOW:i]
    scaler_roll = StandardScaler()
    window_std = scaler_roll.fit_transform(window_data)

    pca_roll = PCA(n_components=1)
    scores = pca_roll.fit_transform(window_std)

    rolling_pc1.iloc[i] = scores[-1, 0]
    rolling_explained.iloc[i] = pca_roll.explained_variance_ratio_[0]

    if i % 500 == 0:
        rolling_loadings[r2.index[i].strftime('%Y-%m-%d')] = dict(zip(ASSETS, pca_roll.components_[0].tolist()))

rolling_pc1 = rolling_pc1.dropna()
rolling_explained = rolling_explained.dropna()

print(f"  Rolling PC1 available: {len(rolling_pc1)} observations")
print(f"  Rolling PC1 explained variance: mean={rolling_explained.mean()*100:.1f}%, "
      f"std={rolling_explained.std()*100:.1f}%")
print(f"  Range: [{rolling_explained.min()*100:.1f}%, {rolling_explained.max()*100:.1f}%]")

# Check loading stability
if rolling_loadings:
    dates_list = list(rolling_loadings.keys())
    print(f"\n  Loading stability (sample dates):")
    for d in dates_list[:3] + dates_list[-3:]:
        lds = rolling_loadings[d]
        print(f"    {d}: " + ", ".join([f"{a}={v:.2f}" for a, v in lds.items()]))

# ============================================================
# Step 4: Factor-Augmented GJR — OOS Rolling Forecast
# ============================================================
print("\n[Step 4] Factor-Augmented GJR — OOS Rolling Forecast")
print(f"  GARCH window: {GARCH_WINDOW}, Refit freq: {REFIT_FREQ} days")

# We'll evaluate on 3 target assets: SPY, QQQ, GLD
TARGET_ASSETS = ['SPY', 'QQQ', 'GLD']

# Prepare exogenous variables (all lagged by 1)
vix_lagged = vix.shift(1)
pc1_rolling_lagged = rolling_pc1.shift(1)

# Determine OOS period
oos_start = max(OOS_START_IDX, PCA_WINDOW + GARCH_WINDOW + 1)
total_n = len(returns)

if oos_start >= total_n - 252:
    print(f"  WARNING: Not enough data for OOS. Adjusting OOS start.")
    oos_start = total_n - 1260  # At least 5 years OOS

print(f"  OOS start index: {oos_start}")
print(f"  OOS start date: {returns.index[oos_start].strftime('%Y-%m-%d')}")
print(f"  OOS length: {total_n - oos_start} days")

all_results = {}

def fit_gjr_and_forecast(y_train, y_full, oos_start_idx, total_n, refit_freq):
    """Fit GJR(1,1,1) with rolling refit and produce 1-step ahead OOS forecasts.

    Returns array of forecasts (in return-decimal² scale, not percentage).
    """
    forecasts = np.full(total_n, np.nan)
    last_fit_idx = -refit_freq
    omega, alpha, gamma, beta = 0.01, 0.05, 0.05, 0.9
    h_prev = np.var(y_train[:500]) if len(y_train) >= 500 else np.var(y_train)
    fitted = False

    for t in range(oos_start_idx, total_n):
        need_refit = (t - last_fit_idx >= refit_freq) or (not fitted)

        if need_refit:
            fit_start = max(0, t - GARCH_WINDOW)
            fit_end = t
            y_fit = y_full[fit_start:fit_end] * 100  # percentage scale for arch

            try:
                am = arch_model(y_fit, vol='GARCH', p=1, o=1, q=1,
                               mean='Constant', dist='t')
                res = am.fit(disp='off', options={'maxiter': 500})

                omega = res.params.get('omega', omega)
                alpha = res.params.get('alpha[1]', alpha)
                gamma = res.params.get('gamma[1]', gamma)
                beta = res.params.get('beta[1]', beta)

                # Get last conditional variance from fit
                # conditional_volatility may be numpy array or pandas Series
                cv = res.conditional_volatility
                h_prev = float(cv[-1]) ** 2
                last_fit_idx = t
                fitted = True
            except Exception as e:
                if not fitted:
                    continue  # Skip until we get a successful fit

        if not fitted:
            continue

        # 1-step recursive forecast (in percentage scale)
        eps_prev = y_full[t-1] * 100  # previous return in %
        eps2_prev = eps_prev ** 2
        indicator = 1.0 if eps_prev < 0 else 0.0

        h_t = omega + alpha * eps2_prev + gamma * indicator * eps2_prev + beta * h_prev
        h_t = max(h_t, 1e-8)

        # Store in decimal scale: h_t is in %² → divide by 10000
        forecasts[t] = h_t / 10000.0

        # Update h_prev for next step
        h_prev = h_t

    return forecasts


def multiplicative_factor_forecast(gjr_forecasts, factor_series, y_full, oos_start_idx, total_n, refit_freq):
    """Multiplicative factor adjustment: h_t^aug = h_t^gjr * exp(delta * X_{t-1})

    Two-stage approach:
    Stage 1: GJR forecasts (already computed)
    Stage 2: Regress log(r² / h_gjr) on X_{t-1} to estimate delta

    Uses rolling estimation window.
    """
    forecasts = np.full(total_n, np.nan)
    last_fit_idx = -refit_freq
    delta = 0.0
    fitted = False

    for t in range(oos_start_idx, total_n):
        need_refit = (t - last_fit_idx >= refit_freq) or (not fitted)

        if need_refit:
            fit_start = max(0, t - GARCH_WINDOW)
            fit_end = t

            # Get GJR forecasts and actual r² for the training window
            h_gjr_train = gjr_forecasts[fit_start:fit_end]
            r2_train = (y_full[fit_start:fit_end]) ** 2
            x_train = factor_series.iloc[fit_start:fit_end].values if hasattr(factor_series, 'iloc') else factor_series[fit_start:fit_end]

            # Valid mask: need positive h_gjr, positive r², valid X
            valid = (~np.isnan(h_gjr_train)) & (h_gjr_train > 0) & (r2_train > 0) & (~np.isnan(x_train))

            if valid.sum() < 100:
                if not fitted:
                    continue
            else:
                # log(r² / h_gjr) = delta * X + noise
                log_ratio = np.log(r2_train[valid] / h_gjr_train[valid])
                x_valid = x_train[valid]

                # Simple OLS: delta = cov(log_ratio, X) / var(X)
                x_mean = np.mean(x_valid)
                x_centered = x_valid - x_mean
                var_x = np.var(x_valid)

                if var_x > 1e-12:
                    delta = np.sum((log_ratio - np.mean(log_ratio)) * x_centered) / (len(x_valid) * var_x)
                else:
                    delta = 0.0

                last_fit_idx = t
                fitted = True

        if not fitted:
            continue

        # Get factor value at t (already lagged in the series)
        idx_t = returns.index[t]
        if hasattr(factor_series, 'index'):
            if idx_t in factor_series.index and not np.isnan(factor_series[idx_t]):
                x_t = factor_series[idx_t]
            else:
                x_t = 0.0
        else:
            x_t = factor_series[t] if not np.isnan(factor_series[t]) else 0.0

        # GJR forecast at t
        h_gjr_t = gjr_forecasts[t]
        if np.isnan(h_gjr_t) or h_gjr_t <= 0:
            continue

        # Multiplicative adjustment
        h_aug = h_gjr_t * np.exp(delta * x_t)
        h_aug = max(h_aug, 1e-12)

        forecasts[t] = h_aug

    return forecasts


for asset in TARGET_ASSETS:
    print(f"\n  --- {asset} ---")

    y_full = returns[asset].values  # decimal scale
    r2_actual = y_full ** 2

    dates_idx = returns.index

    # Step A: Fit baseline GJR
    print(f"    Fitting GJR baseline...")
    gjr_forecasts = fit_gjr_and_forecast(
        y_full[:oos_start], y_full, oos_start, total_n, REFIT_FREQ
    )
    n_gjr_valid = np.sum(~np.isnan(gjr_forecasts[oos_start:]))
    print(f"    GJR forecasts: {n_gjr_valid}/{total_n - oos_start}")

    # Step B: Factor-augmented models
    # Standardize VIX and PC1 for the factor regression
    vix_series = vix_lagged.reindex(returns.index)
    pc1_series = pc1_rolling_lagged.reindex(returns.index)

    # Standardize using rolling stats (to avoid lookahead)
    vix_std = pd.Series(np.nan, index=returns.index)
    pc1_std = pd.Series(np.nan, index=returns.index)

    for t in range(oos_start, total_n):
        ws = max(0, t - GARCH_WINDOW)
        # VIX standardization
        vix_window = vix_series.iloc[ws:t].dropna()
        if len(vix_window) > 50:
            vix_std.iloc[t] = (vix_series.iloc[t] - vix_window.mean()) / vix_window.std() if vix_window.std() > 0 else 0
        # PC1 standardization
        pc1_window = pc1_series.iloc[ws:t].dropna()
        if len(pc1_window) > 50:
            pc1_std.iloc[t] = (pc1_series.iloc[t] - pc1_window.mean()) / pc1_window.std() if pc1_window.std() > 0 else 0

    print(f"    Fitting GJR-X(VIX)...")
    gjr_vix_forecasts = multiplicative_factor_forecast(
        gjr_forecasts, vix_std, y_full, oos_start, total_n, REFIT_FREQ
    )
    n_vix_valid = np.sum(~np.isnan(gjr_vix_forecasts[oos_start:]))
    print(f"    GJR-X(VIX) forecasts: {n_vix_valid}/{total_n - oos_start}")

    print(f"    Fitting GJR-X(PC1)...")
    gjr_pc1_forecasts = multiplicative_factor_forecast(
        gjr_forecasts, pc1_std, y_full, oos_start, total_n, REFIT_FREQ
    )
    n_pc1_valid = np.sum(~np.isnan(gjr_pc1_forecasts[oos_start:]))
    print(f"    GJR-X(PC1) forecasts: {n_pc1_valid}/{total_n - oos_start}")

    # GJR-X(VIX+PC1): use both factors
    print(f"    Fitting GJR-X(VIX+PC1)...")
    # Combine: create a combined factor
    combined_factor = pd.Series(np.nan, index=returns.index)
    for t in range(oos_start, total_n):
        # Fit two-factor model
        pass  # We'll handle this differently

    # For VIX+PC1, run two separate multiplicative adjustments sequentially
    # h_aug = h_gjr * exp(d1*VIX + d2*PC1)
    # Implemented as a joint regression
    gjr_both_forecasts = np.full(total_n, np.nan)
    last_fit_idx_both = -REFIT_FREQ
    delta_vix, delta_pc1 = 0.0, 0.0
    fitted_both = False

    for t in range(oos_start, total_n):
        need_refit = (t - last_fit_idx_both >= REFIT_FREQ) or (not fitted_both)

        if need_refit:
            fit_start = max(0, t - GARCH_WINDOW)
            fit_end = t

            h_gjr_train = gjr_forecasts[fit_start:fit_end]
            r2_train = y_full[fit_start:fit_end] ** 2
            x1_train = vix_std.iloc[fit_start:fit_end].values
            x2_train = pc1_std.iloc[fit_start:fit_end].values

            valid = (~np.isnan(h_gjr_train)) & (h_gjr_train > 0) & (r2_train > 0) & \
                    (~np.isnan(x1_train)) & (~np.isnan(x2_train))

            if valid.sum() < 100:
                if not fitted_both:
                    continue
            else:
                log_ratio = np.log(r2_train[valid] / h_gjr_train[valid])
                X_mat = np.column_stack([x1_train[valid], x2_train[valid]])
                X_mat_with_const = np.column_stack([np.ones(X_mat.shape[0]), X_mat])

                try:
                    # OLS: log_ratio = const + d1*VIX + d2*PC1
                    betas = np.linalg.lstsq(X_mat_with_const, log_ratio, rcond=None)[0]
                    delta_vix = betas[1]
                    delta_pc1 = betas[2]
                except Exception:
                    pass

                last_fit_idx_both = t
                fitted_both = True

        if not fitted_both:
            continue

        h_gjr_t = gjr_forecasts[t]
        if np.isnan(h_gjr_t) or h_gjr_t <= 0:
            continue

        v_t = vix_std.iloc[t] if not np.isnan(vix_std.iloc[t]) else 0.0
        p_t = pc1_std.iloc[t] if not np.isnan(pc1_std.iloc[t]) else 0.0

        h_aug = h_gjr_t * np.exp(delta_vix * v_t + delta_pc1 * p_t)
        h_aug = max(h_aug, 1e-12)
        gjr_both_forecasts[t] = h_aug

    n_both_valid = np.sum(~np.isnan(gjr_both_forecasts[oos_start:]))
    print(f"    GJR-X(VIX+PC1) forecasts: {n_both_valid}/{total_n - oos_start}")

    # Collect all forecasts
    all_forecasts = {
        'GJR': gjr_forecasts,
        'GJR-X(VIX)': gjr_vix_forecasts,
        'GJR-X(PC1)': gjr_pc1_forecasts,
        'GJR-X(VIX+PC1)': gjr_both_forecasts,
    }

    # Evaluate OOS
    print(f"\n    OOS Evaluation ({asset}):")

    oos_mask = np.zeros(total_n, dtype=bool)
    oos_mask[oos_start:] = True

    # Get valid indices where all forecasts exist
    valid = oos_mask.copy()
    for name in all_forecasts:
        valid &= ~np.isnan(all_forecasts[name])
    valid &= ~np.isnan(r2_actual)
    valid &= r2_actual > 0  # Need positive actual for QLIKE

    n_valid = valid.sum()
    print(f"    Valid OOS observations: {n_valid}")

    if n_valid < 252:
        print(f"    WARNING: Too few valid OOS observations ({n_valid} < 252)")
        all_results[asset] = {'error': f'Too few valid OOS obs: {n_valid}'}
        continue

    oos_dates = dates_idx[valid]
    print(f"    OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")

    actual_oos = r2_actual[valid]

    # QLIKE for each model
    qlike_results = {}
    for name in all_forecasts:
        pred_oos = all_forecasts[name][valid]
        pred_oos = np.maximum(pred_oos, 1e-12)

        ql = qlike_pointwise(actual_oos, pred_oos)
        qlike_mean = np.mean(ql)
        qlike_results[name] = {
            'qlike': float(qlike_mean),
            'pointwise': ql
        }
        print(f"    {name:20s}: QLIKE = {qlike_mean:.6f}")

    # DM tests vs baseline GJR
    print(f"\n    DM Tests vs GJR (Harvey t>3.0):")
    dm_results = {}
    baseline_loss = qlike_results['GJR']['pointwise']

    for name in ['GJR-X(VIX)', 'GJR-X(PC1)', 'GJR-X(VIX+PC1)']:
        model_loss = qlike_results[name]['pointwise']
        t_stat, p_val = dm_test(model_loss, baseline_loss, h=1)
        significant = abs(t_stat) > 3.0
        direction = "better" if t_stat < 0 else "worse"
        dm_results[name] = {
            't_stat': float(t_stat),
            'p_value': float(p_val),
            'significant': significant,
            'direction': direction
        }
        sig_marker = "***" if significant else ""
        print(f"    {name:20s}: t={t_stat:+.3f}, p={p_val:.4f} ({direction}) {sig_marker}")

    # DM test: GJR-X(PC1) vs GJR-X(VIX) — does PC1 compete with VIX?
    pc1_loss = qlike_results['GJR-X(PC1)']['pointwise']
    vix_loss = qlike_results['GJR-X(VIX)']['pointwise']
    t_pc1_vs_vix, p_pc1_vs_vix = dm_test(pc1_loss, vix_loss, h=1)
    print(f"\n    GJR-X(PC1) vs GJR-X(VIX): t={t_pc1_vs_vix:+.3f}, p={p_pc1_vs_vix:.4f}")

    # DM test: GJR-X(VIX+PC1) vs GJR-X(VIX) — does PC1 add incremental value?
    both_loss = qlike_results['GJR-X(VIX+PC1)']['pointwise']
    t_incr, p_incr = dm_test(both_loss, vix_loss, h=1)
    print(f"    GJR-X(VIX+PC1) vs GJR-X(VIX): t={t_incr:+.3f}, p={p_incr:.4f} (PC1 incremental)")

    # Spearman rank correlation
    print(f"\n    Spearman Rank Correlation (forecast vs actual):")
    spearman_results = {}
    for name in all_forecasts:
        pred_oos = all_forecasts[name][valid]
        rho, p = spearmanr(actual_oos, pred_oos)
        spearman_results[name] = {'rho': float(rho), 'p_value': float(p)}
        print(f"    {name:20s}: rho={rho:.4f}, p={p:.2e}")

    all_results[asset] = {
        'n_oos': int(n_valid),
        'oos_start': oos_dates[0].strftime('%Y-%m-%d'),
        'oos_end': oos_dates[-1].strftime('%Y-%m-%d'),
        'qlike': {name: qlike_results[name]['qlike'] for name in all_forecasts},
        'dm_vs_gjr': dm_results,
        'dm_pc1_vs_vix': {'t_stat': float(t_pc1_vs_vix), 'p_value': float(p_pc1_vs_vix)},
        'dm_incremental_pc1': {'t_stat': float(t_incr), 'p_value': float(p_incr)},
        'spearman': spearman_results,
    }

# ============================================================
# Step 5: Summary & Interpretation
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Aggregate results
summary = {
    'experiment_id': 'K928',
    'title': 'Factor GARCH — Common Volatility Factor Across SPY/QQQ/GLD',
    'data_source': 'yfinance',
    'data_period': f'{returns.index[0].strftime("%Y-%m-%d")} to {returns.index[-1].strftime("%Y-%m-%d")}',
    'n_total': int(len(returns)),
    'assets': ASSETS,
    'target_assets': TARGET_ASSETS,
    'pca': {
        'explained_variance': [float(x) for x in explained],
        'pc1_explained_pct': float(explained[0] * 100),
        'pc1_vix_pearson': float(pc1_vix_corr),
        'pc1_vix_spearman': float(pc1_vix_spearman),
        'pc1_autocorr': {
            'lag1': float(pc1_ac1),
            'lag5': float(pc1_ac5),
            'lag22': float(pc1_ac22)
        },
        'loadings': {pc: {asset: float(loadings.loc[pc, asset]) for asset in ASSETS} for pc in loadings.index},
        'rolling_explained_mean': float(rolling_explained.mean()),
        'rolling_explained_std': float(rolling_explained.std()),
    },
    'oos_results': all_results,
    'methodology': {
        'garch_window': GARCH_WINDOW,
        'pca_window': PCA_WINDOW,
        'refit_freq': REFIT_FREQ,
        'oos_start_idx': oos_start,
        'model': 'GJR-GARCH(1,1,1) with Student-t innovations',
        'augmentation': 'Multiplicative: h_aug = h_gjr * exp(delta * X_{t-1})',
        'loss_function': 'QLIKE on r² (Patton 2011 proxy-robust)',
        'dm_threshold': 'Harvey (2016) |t| > 3.0',
    },
    'references': [
        'Engle, Ng & Rothschild (1990): Factor ARCH, JoE',
        'Patton (2011): Volatility forecast comparison using imperfect proxies, JoE',
        'Harvey (2016): ...and the cross-section of expected returns, RFS',
        'Engle & Rangel (2008): Spline-GARCH, multiplicative decomposition',
    ],
    'timestamp': datetime.now().isoformat(),
}

# Determine overall conclusion
any_significant = False
for asset in TARGET_ASSETS:
    if asset in all_results and 'dm_vs_gjr' in all_results[asset]:
        for name, dm in all_results[asset]['dm_vs_gjr'].items():
            if dm.get('significant', False) and dm.get('direction') == 'better':
                any_significant = True

pc1_adds_to_vix = False
for asset in TARGET_ASSETS:
    if asset in all_results and 'dm_incremental_pc1' in all_results[asset]:
        incr = all_results[asset]['dm_incremental_pc1']
        if incr.get('t_stat', 0) < -3.0:
            pc1_adds_to_vix = True

print(f"\n  PC1 Explained Variance: {explained[0]*100:.1f}%")
print(f"  PC1-VIX Correlation: {pc1_vix_corr:.3f}")
print(f"  Any Factor-GJR significantly beats GJR? {any_significant}")
print(f"  PC1 adds incremental value beyond VIX? {pc1_adds_to_vix}")

conclusion = []
conclusion.append(f"PC1 explains {explained[0]*100:.1f}% of cross-asset daily r² variation (cf. T24: 76.6% on 22d RV)")
conclusion.append(f"PC1-VIX correlation: Pearson {pc1_vix_corr:.3f}, Spearman {pc1_vix_spearman:.3f}")
conclusion.append(f"Rolling PC1 explained variance: {rolling_explained.mean()*100:.1f}% +/- {rolling_explained.std()*100:.1f}%")

if any_significant:
    conclusion.append("Factor-augmented GJR significantly beats baseline GJR for some assets (Harvey |t|>3.0)")
else:
    conclusion.append("Factor-augmented GJR does NOT significantly beat baseline GJR (Harvey |t|<3.0)")
    conclusion.append("Confirms VIX sufficiency at daily frequency — cross-asset vol factor is redundant")

if pc1_adds_to_vix:
    conclusion.append("PC1 provides incremental value beyond VIX in some assets")
else:
    conclusion.append("PC1 provides NO incremental value beyond VIX — VIX already captures the common factor")

# Check if VIX augmentation helps
vix_helps = False
for asset in TARGET_ASSETS:
    if asset in all_results and 'dm_vs_gjr' in all_results[asset]:
        dm_vix = all_results[asset]['dm_vs_gjr'].get('GJR-X(VIX)', {})
        if dm_vix.get('significant', False) and dm_vix.get('direction') == 'better':
            vix_helps = True
            conclusion.append(f"VIX augmentation significantly improves GJR for {asset}")

if not vix_helps:
    conclusion.append("Even VIX augmentation does not significantly improve baseline GJR")

summary['conclusion'] = conclusion
summary['is_null_result'] = not any_significant

print("\n  Conclusions:")
for c in conclusion:
    print(f"    - {c}")

# ============================================================
# Step 6: Visualizations
# ============================================================
print("\n[Step 6] Creating visualizations...")

# --- Plot 1: PCA Explained Variance ---
fig, ax = plt.subplots(figsize=(8, 5))
pcs = [f'PC{i+1}' for i in range(5)]
bars = ax.bar(pcs, [x*100 for x in explained], color=['#2196F3', '#4CAF50', '#FF9800', '#F44336', '#9C27B0'])
ax.set_ylabel('Explained Variance (%)')
ax.set_title('K928: PCA on Cross-Asset Squared Returns\n(SPY, QQQ, IWM, GLD, TLT)')
for bar, val in zip(bars, explained):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.5,
            f'{val*100:.1f}%', ha='center', va='bottom', fontweight='bold')

# Add cumulative line
cumulative = np.cumsum([x*100 for x in explained])
ax2 = ax.twinx()
ax2.plot(pcs, cumulative, 'r-o', linewidth=2, label='Cumulative')
ax2.set_ylabel('Cumulative (%)')
ax2.set_ylim(0, 105)
ax2.legend(loc='right')

plt.tight_layout()
fig.savefig(OUTPUT_DIR / 'k928_pca_explained.png', dpi=150)
plt.close()
print("  Saved k928_pca_explained.png")

# --- Plot 2: PC1 vs VIX Time Series ---
fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

ax1 = axes[0]
ax1.plot(pc_scores_full.index, pc_scores_full['PC1'], color='#2196F3', alpha=0.7, linewidth=0.5)
ax1.set_ylabel('PC1 Score (standardized)')
ax1.set_title(f'K928: PC1 vs VIX (Pearson r = {pc1_vix_corr:.3f})')
ax1.axhline(0, color='gray', linestyle='--', alpha=0.5)

ax2 = axes[1]
ax2.plot(vix.index, vix, color='#F44336', alpha=0.7, linewidth=0.5)
ax2.set_ylabel('VIX Level')
ax2.set_xlabel('Date')

plt.tight_layout()
fig.savefig(OUTPUT_DIR / 'k928_factor_vs_vix.png', dpi=150)
plt.close()
print("  Saved k928_factor_vs_vix.png")

# --- Plot 3: QLIKE Comparison Bar Chart ---
valid_assets = [a for a in TARGET_ASSETS if a in all_results and 'qlike' in all_results[a]]
if valid_assets:
    n_assets = len(valid_assets)
    fig, axes = plt.subplots(1, n_assets, figsize=(5*n_assets, 5))
    if n_assets == 1:
        axes = [axes]

    for idx, asset in enumerate(valid_assets):
        ax = axes[idx]
        model_names = list(all_results[asset]['qlike'].keys())
        qlike_vals = [all_results[asset]['qlike'][m] for m in model_names]

        colors = ['#607D8B', '#2196F3', '#4CAF50', '#FF9800']
        bars = ax.bar(range(len(model_names)), qlike_vals, color=colors[:len(model_names)])
        ax.set_xticks(range(len(model_names)))
        ax.set_xticklabels(model_names, rotation=45, ha='right', fontsize=9)
        ax.set_ylabel('QLIKE (lower = better)')
        ax.set_title(f'{asset}')

        # Add DM significance markers
        for i, name in enumerate(model_names):
            if name in all_results[asset].get('dm_vs_gjr', {}):
                dm = all_results[asset]['dm_vs_gjr'][name]
                if dm.get('significant'):
                    marker = '***'
                elif dm.get('p_value', 1) < 0.05:
                    marker = '*'
                else:
                    marker = ''
                if marker:
                    ax.text(i, qlike_vals[i], marker, ha='center', va='bottom',
                           fontsize=14, color='red')

    fig.suptitle('K928: QLIKE Comparison — Factor-Augmented GJR\n(*** = Harvey |t| > 3.0)',
                fontsize=12, fontweight='bold')
    plt.tight_layout()
    fig.savefig(OUTPUT_DIR / 'k928_model_comparison.png', dpi=150)
    plt.close()
    print("  Saved k928_model_comparison.png")

# --- Plot 4: Rolling PC1 Explained Variance ---
fig, ax = plt.subplots(figsize=(12, 4))
ax.plot(rolling_explained.index, rolling_explained * 100, color='#2196F3', alpha=0.7, linewidth=0.5)
ax.axhline(rolling_explained.mean() * 100, color='red', linestyle='--', alpha=0.5,
           label=f'Mean: {rolling_explained.mean()*100:.1f}%')
ax.set_ylabel('PC1 Explained Variance (%)')
ax.set_title('K928: Rolling PC1 Explained Variance (250-day window)')
ax.legend()
plt.tight_layout()
fig.savefig(OUTPUT_DIR / 'k928_rolling_explained.png', dpi=150)
plt.close()
print("  Saved k928_rolling_explained.png")

# ============================================================
# Step 7: Save Results
# ============================================================
results_path = OUTPUT_DIR / 'k928_factor_garch_results.json'
with open(results_path, 'w') as f:
    json.dump(summary, f, indent=2, default=str)
print(f"\n  Results saved to {results_path}")

print("\n" + "=" * 70)
print("K928 COMPLETE")
print("=" * 70)
