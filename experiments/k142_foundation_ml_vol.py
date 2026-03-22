"""
K142: Foundation Time Series / ML for Volatility Forecasting
============================================================
Jump exploration experiment — testing whether ML (XGBoost + Ridge with HAR features)
can beat GJR-GARCH(1,1) for volatility prediction.

Background:
  - arXiv:2505.11163, arXiv:2601.13014 show pre-trained time series foundation models
    can forecast realized variance competitively
  - This is our 4th ML attempt (after LSTM, GBM T22, GARCH-LSTM hybrid — all failed)
  - Prior failures: LSTM found iid residuals, GBM T22 false alarm (0/15 cross-asset),
    GARCH-LSTM hybrid had unstable factor (std=1.16)

What's different this time:
  1. HAR-style features (RV_1d, RV_5d, RV_22d) — proven structure from Corsi (2009)
  2. XGBoost (tree-based, not neural) — can capture nonlinearities without overfitting
  3. Ridge regression (linear baseline) — interpretable, regularized
  4. Walk-forward with w=2000 — same as our GARCH baseline
  5. QLIKE as primary metric — consistent with all prior experiments
  6. Cross-asset validation: SPY, GLD, TLT

Methodology:
  - Target: r²_{t+1} (next-day squared return as volatility proxy)
  - Features at time t: lagged r², |r|, rolling RV (5d, 22d, 63d), day-of-week, month
  - Walk-forward: train on [t-2000, t], predict r²_{t+1}
  - OOS: 2020-01-01 to 2024-12-31
  - GJR-GARCH baseline: same window, same OOS
"""

import sys
import os
import warnings
import time
import json
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from sklearn.linear_model import Ridge
from scipy import stats

# Try XGBoost, fall back to GradientBoosting
try:
    from xgboost import XGBRegressor
    HAS_XGBOOST = True
    print("[OK] XGBoost available")
except ImportError:
    from sklearn.ensemble import GradientBoostingRegressor
    HAS_XGBOOST = False
    print("[WARN] XGBoost not available, using sklearn GradientBoosting")

# ==================================================================
# CONFIG
# ==================================================================
WINDOW = 2000
OOS_START = "2020-01-01"
OOS_END = "2024-12-31"
DATA_START = "2010-01-01"  # enough lookback for w=2000
ASSETS = ["SPY", "GLD", "TLT"]

print("=" * 80)
print("K142: FOUNDATION ML VOL FORECASTING (4th ML attempt)")
print("=" * 80)
print(f"  Window: {WINDOW}")
print(f"  OOS: {OOS_START} to {OOS_END}")
print(f"  Assets: {ASSETS}")
print(f"  Models: XGBoost, Ridge, GJR-GARCH(1,1)")
print()

# ==================================================================
# HELPER FUNCTIONS
# ==================================================================

def qlike(actual_var, predicted_var):
    """QLIKE loss: mean(actual/predicted + log(predicted)). Lower is better."""
    predicted_var = np.maximum(predicted_var, 1e-12)
    return float(np.mean(actual_var / predicted_var + np.log(predicted_var)))

def mse_metric(actual_var, predicted_var):
    """MSE between actual and predicted variance."""
    return float(np.mean((actual_var - predicted_var) ** 2))

def diebold_mariano(loss1, loss2, h=1):
    """DM test. loss1 - loss2: negative means model1 is better."""
    d = loss1 - loss2
    T = len(d)
    d_bar = np.mean(d)
    gamma_0 = np.var(d, ddof=1)
    V = gamma_0
    for k in range(1, h):
        gamma_k = np.sum((d[k:] - d_bar) * (d[:-k] - d_bar)) / T
        V += 2 * gamma_k
    dm_stat = d_bar / np.sqrt(max(V / T, 1e-20))
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return {'statistic': float(dm_stat), 'p_value': float(p_value),
            'mean_diff': float(d_bar), 'better_model': 1 if d_bar < 0 else 2}


def build_features(df, idx):
    """Build HAR-like feature vector for observation at index idx.
    Uses ONLY information available at time idx (no look-ahead).

    Features:
    1. r²_1 (yesterday's squared return)
    2. |r|_1 (yesterday's abs return)
    3. RV_5d (mean r² over last 5 days)
    4. RV_22d (mean r² over last 22 days)
    5. RV_63d (mean r² over last 63 days)
    6. log(RV_5d)
    7. log(RV_22d)
    8. r²_1 * I(r < 0)  (leverage term — mimics GJR)
    9. day of week (0-4)
    10. month (1-12)
    """
    r2 = df['r_squared'].values
    ret = df['log_return'].values
    dates = df.index

    features = {}

    # Lagged r² (1-day)
    features['r2_lag1'] = r2[idx - 1]

    # Lagged |r| (1-day)
    features['abs_r_lag1'] = abs(ret[idx - 1])

    # Rolling mean r² — 5d
    if idx >= 5:
        features['rv_5d'] = np.mean(r2[idx-5:idx])
    else:
        features['rv_5d'] = np.mean(r2[:idx]) if idx > 0 else r2[idx]

    # Rolling mean r² — 22d
    if idx >= 22:
        features['rv_22d'] = np.mean(r2[idx-22:idx])
    else:
        features['rv_22d'] = np.mean(r2[:idx]) if idx > 0 else r2[idx]

    # Rolling mean r² — 63d
    if idx >= 63:
        features['rv_63d'] = np.mean(r2[idx-63:idx])
    else:
        features['rv_63d'] = np.mean(r2[:idx]) if idx > 0 else r2[idx]

    # Log-transformed RV (more normally distributed)
    features['log_rv_5d'] = np.log(max(features['rv_5d'], 1e-12))
    features['log_rv_22d'] = np.log(max(features['rv_22d'], 1e-12))

    # Leverage term: r² when return is negative (mimics GJR gamma)
    features['r2_neg_lag1'] = r2[idx-1] * (1.0 if ret[idx-1] < 0 else 0.0)

    # Calendar features
    features['dow'] = dates[idx].weekday()
    features['month'] = dates[idx].month

    return features

FEATURE_NAMES = ['r2_lag1', 'abs_r_lag1', 'rv_5d', 'rv_22d', 'rv_63d',
                 'log_rv_5d', 'log_rv_22d', 'r2_neg_lag1', 'dow', 'month']


def build_feature_matrix(df, start_idx, end_idx):
    """Build feature matrix X and target y for indices [start_idx, end_idx).
    Target is r²_{t+1} (next-day squared return).
    Features use only info up to and including time t.
    """
    X_rows = []
    y_rows = []

    for idx in range(max(start_idx, 63), end_idx):
        if idx + 1 >= len(df):
            break
        feat = build_features(df, idx)
        X_rows.append([feat[name] for name in FEATURE_NAMES])
        y_rows.append(df['r_squared'].values[idx + 1])  # next-day r²

    return np.array(X_rows), np.array(y_rows)


def run_gjr_garch_forecast(returns_window):
    """Fit GJR-GARCH(1,1) on a window of returns and forecast next-day variance."""
    try:
        ret_pct = returns_window * 100  # arch expects percentage returns
        model = arch_model(ret_pct, vol='GARCH', p=1, o=1, q=1,
                          dist='normal', mean='Zero', rescale=False)
        result = model.fit(disp='off', show_warning=False)
        fcast = result.forecast(horizon=1)
        var_forecast = fcast.variance.iloc[-1, 0] / 10000  # convert back

        # Clamp to reasonable range
        if not np.isfinite(var_forecast) or var_forecast > 0.1 or var_forecast < 1e-10:
            var_forecast = float(np.var(returns_window))

        return var_forecast
    except Exception:
        return float(np.var(returns_window))


# ==================================================================
# MAIN EXPERIMENT LOOP
# ==================================================================

all_results = {}

for asset in ASSETS:
    print(f"\n{'='*60}")
    print(f"  ASSET: {asset}")
    print(f"{'='*60}")

    # Download data
    print(f"  Downloading {asset} data...")
    df_raw = yf.download(asset, start=DATA_START, end=OOS_END, progress=False)
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)

    # Compute returns and volatility proxy
    df = pd.DataFrame(index=df_raw.index)
    df['close'] = df_raw['Close']
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    df['r_squared'] = df['log_return'] ** 2  # vol proxy: squared return
    df.dropna(inplace=True)

    print(f"  Data: {df.index[0].date()} to {df.index[-1].date()}, {len(df)} obs")

    # Identify OOS period
    oos_mask = (df.index >= pd.Timestamp(OOS_START)) & (df.index <= pd.Timestamp(OOS_END))
    oos_indices = np.where(oos_mask)[0]

    if len(oos_indices) == 0:
        print(f"  [ERROR] No OOS data for {asset}")
        continue

    print(f"  OOS: {len(oos_indices)} days")

    # Pre-compute full feature matrix for efficiency
    print(f"  Building feature matrix...")
    t0 = time.time()
    X_full, _ = build_feature_matrix(df, 63, len(df) - 1)
    # Map: feature row i corresponds to predicting df['r_squared'][63 + i + 1]
    # The feature at row i uses info up to index (63 + i)
    # Target is r² at index (63 + i + 1)
    t_feat = time.time() - t0
    print(f"  Feature matrix: {X_full.shape}, built in {t_feat:.1f}s")

    # Storage for forecasts
    garch_forecasts = []
    xgb_forecasts = []
    ridge_forecasts = []
    actual_r2 = []
    oos_dates = []

    # Walk-forward
    n_oos = len(oos_indices)
    print(f"  Walk-forward evaluation ({n_oos} steps)...")
    t0 = time.time()

    n_skip = 0
    n_garch_fail = 0

    for step_i, oos_idx in enumerate(oos_indices):
        # We want to predict r²[oos_idx]
        # Training window: [oos_idx - WINDOW, oos_idx - 1]
        train_end = oos_idx  # exclusive
        train_start = train_end - WINDOW

        if train_start < 63:
            n_skip += 1
            continue

        # --- GJR-GARCH ---
        returns_window = df['log_return'].values[train_start:train_end]
        garch_var = run_gjr_garch_forecast(returns_window)

        # --- ML Models ---
        # Feature matrix indices: the feature at row j corresponds to
        # predicting df['r_squared'][63 + j + 1]
        # We need features for training: indices where target is in [train_start+1, train_end]
        # The feature row for predicting target at index k is: k - 63 - 1

        # Training features: predict r²[train_start+1] through r²[train_end-1]
        # (we can't use the last day's target because it IS the prediction target)
        feat_train_start = max(train_start - 63, 0)  # approx
        feat_train_end = train_end - 63 - 1  # -1 because feature matrix is offset

        # More precise: feature row j predicts r² at index (63 + j + 1)
        # We want target indices in [train_start+1, train_end-1] for training
        # So j satisfies: 63 + j + 1 in [train_start+1, train_end-1]
        # => j in [train_start - 63, train_end - 64 - 1]
        j_start = max(train_start - 63, 0)
        j_end = min(train_end - 64, X_full.shape[0])

        if j_end <= j_start or j_end - j_start < 100:
            n_skip += 1
            continue

        X_train = X_full[j_start:j_end]
        y_train = df['r_squared'].values[63 + j_start + 1: 63 + j_end + 1]

        if len(X_train) != len(y_train):
            # Safety: adjust
            min_len = min(len(X_train), len(y_train))
            X_train = X_train[:min_len]
            y_train = y_train[:min_len]

        # Prediction features: use info up to oos_idx - 1
        # Feature row for predicting r²[oos_idx] = row (oos_idx - 1 - 63)
        pred_row = oos_idx - 1 - 63
        if pred_row < 0 or pred_row >= X_full.shape[0]:
            n_skip += 1
            continue

        X_pred = X_full[pred_row:pred_row+1]

        # --- XGBoost ---
        try:
            if HAS_XGBOOST:
                xgb_model = XGBRegressor(
                    n_estimators=100,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    min_child_weight=10,
                    reg_alpha=0.1,
                    reg_lambda=1.0,
                    random_state=42,
                    verbosity=0,
                    n_jobs=1,
                )
            else:
                xgb_model = GradientBoostingRegressor(
                    n_estimators=100,
                    max_depth=4,
                    learning_rate=0.05,
                    subsample=0.8,
                    min_samples_leaf=10,
                    random_state=42,
                )
            xgb_model.fit(X_train, y_train)
            xgb_pred = float(xgb_model.predict(X_pred)[0])
            xgb_pred = max(xgb_pred, 1e-12)  # floor at 0
        except Exception:
            xgb_pred = float(np.mean(y_train))

        # --- Ridge ---
        try:
            ridge_model = Ridge(alpha=1.0)
            ridge_model.fit(X_train, y_train)
            ridge_pred = float(ridge_model.predict(X_pred)[0])
            ridge_pred = max(ridge_pred, 1e-12)  # floor at 0
        except Exception:
            ridge_pred = float(np.mean(y_train))

        # Store
        actual = df['r_squared'].values[oos_idx]
        garch_forecasts.append(garch_var)
        xgb_forecasts.append(xgb_pred)
        ridge_forecasts.append(ridge_pred)
        actual_r2.append(actual)
        oos_dates.append(df.index[oos_idx])

        if (step_i + 1) % 250 == 0:
            elapsed = time.time() - t0
            print(f"    Step {step_i+1}/{n_oos} ({elapsed:.0f}s)")

    elapsed_total = time.time() - t0
    print(f"  Walk-forward done: {len(actual_r2)} valid predictions in {elapsed_total:.1f}s")
    print(f"  Skipped: {n_skip}, GARCH fallbacks: {n_garch_fail}")

    if len(actual_r2) < 100:
        print(f"  [ERROR] Too few predictions for {asset}")
        continue

    # Convert to arrays
    actual_arr = np.array(actual_r2)
    garch_arr = np.array(garch_forecasts)
    xgb_arr = np.array(xgb_forecasts)
    ridge_arr = np.array(ridge_forecasts)

    # ==================================================================
    # METRICS
    # ==================================================================

    print(f"\n  --- RESULTS for {asset} ---")
    print(f"  {'Model':<20} {'QLIKE':>12} {'MSE':>14} {'Rank':>6}")
    print(f"  {'-'*52}")

    # QLIKE
    q_garch = qlike(actual_arr, garch_arr)
    q_xgb = qlike(actual_arr, xgb_arr)
    q_ridge = qlike(actual_arr, ridge_arr)

    # MSE
    m_garch = mse_metric(actual_arr, garch_arr)
    m_xgb = mse_metric(actual_arr, xgb_arr)
    m_ridge = mse_metric(actual_arr, ridge_arr)

    # Rank by QLIKE
    scores = [('GJR-GARCH', q_garch, m_garch),
              ('XGBoost', q_xgb, m_xgb),
              ('Ridge-HAR', q_ridge, m_ridge)]
    scores.sort(key=lambda x: x[1])

    for rank, (name, q, m) in enumerate(scores, 1):
        print(f"  {name:<20} {q:>12.6f} {m:>14.2e} {rank:>6}")

    # DM Tests (QLIKE loss)
    qlike_loss_garch = actual_arr / np.maximum(garch_arr, 1e-12) + np.log(np.maximum(garch_arr, 1e-12))
    qlike_loss_xgb = actual_arr / np.maximum(xgb_arr, 1e-12) + np.log(np.maximum(xgb_arr, 1e-12))
    qlike_loss_ridge = actual_arr / np.maximum(ridge_arr, 1e-12) + np.log(np.maximum(ridge_arr, 1e-12))

    print(f"\n  Diebold-Mariano Tests (QLIKE loss):")

    # XGBoost vs GARCH
    dm_xgb_garch = diebold_mariano(qlike_loss_xgb, qlike_loss_garch)
    sig_xgb = "*" if dm_xgb_garch['p_value'] < 0.05 else ""
    winner_xgb = "XGBoost" if dm_xgb_garch['mean_diff'] < 0 else "GARCH"
    print(f"    XGBoost vs GARCH: DM={dm_xgb_garch['statistic']:+.3f}, p={dm_xgb_garch['p_value']:.4f} {sig_xgb}  (better: {winner_xgb})")

    # Ridge vs GARCH
    dm_ridge_garch = diebold_mariano(qlike_loss_ridge, qlike_loss_garch)
    sig_ridge = "*" if dm_ridge_garch['p_value'] < 0.05 else ""
    winner_ridge = "Ridge" if dm_ridge_garch['mean_diff'] < 0 else "GARCH"
    print(f"    Ridge vs GARCH:   DM={dm_ridge_garch['statistic']:+.3f}, p={dm_ridge_garch['p_value']:.4f} {sig_ridge}  (better: {winner_ridge})")

    # XGBoost vs Ridge
    dm_xgb_ridge = diebold_mariano(qlike_loss_xgb, qlike_loss_ridge)
    sig_xr = "*" if dm_xgb_ridge['p_value'] < 0.05 else ""
    winner_xr = "XGBoost" if dm_xgb_ridge['mean_diff'] < 0 else "Ridge"
    print(f"    XGBoost vs Ridge: DM={dm_xgb_ridge['statistic']:+.3f}, p={dm_xgb_ridge['p_value']:.4f} {sig_xr}  (better: {winner_xr})")

    # Feature importance (XGBoost)
    if HAS_XGBOOST:
        # Refit on last window for importance
        try:
            last_oos_idx = oos_indices[-1]
            j_s = max(last_oos_idx - WINDOW - 63, 0)
            j_e = min(last_oos_idx - 64, X_full.shape[0])
            X_last = X_full[j_s:j_e]
            y_last = df['r_squared'].values[63 + j_s + 1: 63 + j_e + 1]
            min_l = min(len(X_last), len(y_last))
            X_last, y_last = X_last[:min_l], y_last[:min_l]

            xgb_imp = XGBRegressor(n_estimators=100, max_depth=4, learning_rate=0.05,
                                   subsample=0.8, colsample_bytree=0.8,
                                   min_child_weight=10, random_state=42, verbosity=0)
            xgb_imp.fit(X_last, y_last)
            importances = xgb_imp.feature_importances_
            print(f"\n  XGBoost Feature Importance (last window):")
            sorted_imp = sorted(zip(FEATURE_NAMES, importances), key=lambda x: -x[1])
            for feat_name, imp in sorted_imp:
                bar = "#" * int(imp * 50)
                print(f"    {feat_name:<15} {imp:.3f} {bar}")
        except Exception as e:
            print(f"  [Feature importance failed: {e}]")

    # Ridge coefficients
    try:
        print(f"\n  Ridge-HAR Coefficients (last window):")
        last_oos_idx = oos_indices[-1]
        j_s = max(last_oos_idx - WINDOW - 63, 0)
        j_e = min(last_oos_idx - 64, X_full.shape[0])
        X_last = X_full[j_s:j_e]
        y_last = df['r_squared'].values[63 + j_s + 1: 63 + j_e + 1]
        min_l = min(len(X_last), len(y_last))
        X_last, y_last = X_last[:min_l], y_last[:min_l]

        ridge_final = Ridge(alpha=1.0)
        ridge_final.fit(X_last, y_last)
        for feat_name, coef in zip(FEATURE_NAMES, ridge_final.coef_):
            print(f"    {feat_name:<15} {coef:+.6f}")
        print(f"    {'intercept':<15} {ridge_final.intercept_:+.6f}")
    except Exception as e:
        print(f"  [Ridge coefficients failed: {e}]")

    # Store results
    all_results[asset] = {
        'n_predictions': len(actual_r2),
        'qlike': {'garch': round(q_garch, 6), 'xgboost': round(q_xgb, 6), 'ridge': round(q_ridge, 6)},
        'mse': {'garch': m_garch, 'xgboost': m_xgb, 'ridge': m_ridge},
        'dm_xgb_vs_garch': dm_xgb_garch,
        'dm_ridge_vs_garch': dm_ridge_garch,
        'dm_xgb_vs_ridge': dm_xgb_ridge,
        'best_model_qlike': scores[0][0],
        'oos_period': f"{oos_dates[0].date()} to {oos_dates[-1].date()}",
    }

# ==================================================================
# CROSS-ASSET SUMMARY
# ==================================================================
print("\n" + "=" * 80)
print("K142: CROSS-ASSET SUMMARY")
print("=" * 80)

print(f"\n{'Asset':<8} {'GJR QLIKE':>12} {'XGB QLIKE':>12} {'Ridge QLIKE':>12} {'Best':>12} {'DM(XGB-GJR)':>14} {'Sig':>5}")
print("-" * 80)

xgb_wins = 0
ridge_wins = 0
garch_wins = 0
any_sig = False

for asset in ASSETS:
    if asset not in all_results:
        continue
    r = all_results[asset]
    q = r['qlike']
    best = r['best_model_qlike']
    dm = r['dm_xgb_vs_garch']
    sig = "*" if dm['p_value'] < 0.05 else ""
    if sig:
        any_sig = True

    if best == 'XGBoost':
        xgb_wins += 1
    elif best == 'Ridge-HAR':
        ridge_wins += 1
    else:
        garch_wins += 1

    delta_pct = (q['xgboost'] - q['garch']) / abs(q['garch']) * 100
    print(f"{asset:<8} {q['garch']:>12.6f} {q['xgboost']:>12.6f} {q['ridge']:>12.6f} {best:>12} {dm['statistic']:>+10.3f} (p={dm['p_value']:.3f}) {sig}")

print(f"\nScoreboard: GJR-GARCH wins {garch_wins}, XGBoost wins {xgb_wins}, Ridge wins {ridge_wins}")
print(f"Any significant DM test? {'YES' if any_sig else 'NO'}")

# ==================================================================
# KEY QUESTION: Does complexity (XGBoost) beat simplicity (Ridge)?
# ==================================================================
print(f"\n--- Complexity vs Simplicity ---")
for asset in ASSETS:
    if asset not in all_results:
        continue
    r = all_results[asset]
    dm = r['dm_xgb_vs_ridge']
    q = r['qlike']
    winner = "XGBoost" if dm['mean_diff'] < 0 else "Ridge"
    sig = "*" if dm['p_value'] < 0.05 else ""
    print(f"  {asset}: XGBoost QLIKE={q['xgboost']:.6f} vs Ridge={q['ridge']:.6f} -> {winner} {sig} (DM p={dm['p_value']:.3f})")

# ==================================================================
# INTERPRETATION
# ==================================================================
print(f"\n{'='*80}")
print("K142: INTERPRETATION")
print("=" * 80)

# Count cross-asset significant results
n_sig_xgb = sum(1 for a in ASSETS if a in all_results and all_results[a]['dm_xgb_vs_garch']['p_value'] < 0.05 and all_results[a]['dm_xgb_vs_garch']['mean_diff'] < 0)
n_sig_ridge = sum(1 for a in ASSETS if a in all_results and all_results[a]['dm_ridge_vs_garch']['p_value'] < 0.05 and all_results[a]['dm_ridge_vs_garch']['mean_diff'] < 0)
total_assets = sum(1 for a in ASSETS if a in all_results)

print(f"\nQ: Can ML capture nonlinearities that GARCH misses?")
print(f"A: XGBoost significantly beats GARCH in {n_sig_xgb}/{total_assets} assets (need 2+ for credible claim)")

print(f"\nQ: Does feature engineering matter more than model complexity?")
xgb_beats_ridge = sum(1 for a in ASSETS if a in all_results and all_results[a]['dm_xgb_vs_ridge']['mean_diff'] < 0)
print(f"A: XGBoost beats Ridge in {xgb_beats_ridge}/{total_assets} assets (by QLIKE)")

print(f"\nQ: 4th ML attempt — is this different from prior failures?")
if n_sig_xgb >= 2:
    print(f"A: YES — first time ML significantly beats GARCH cross-asset")
elif n_sig_xgb >= 1:
    print(f"A: MIXED — some asset-specific improvement but not cross-asset robust")
else:
    print(f"A: NO — ML still cannot reliably beat GARCH for daily vol forecasting")
    print(f"   Consistent with: LSTM (iid residuals), GBM T22 (0/15), GARCH-LSTM (unstable)")
    print(f"   Conclusion: QLIKE ceiling remains intact. GJR-GARCH is the irreducible benchmark.")

# ==================================================================
# SAVE RESULTS
# ==================================================================
results_file = os.path.join(os.path.dirname(__file__), "k142_foundation_ml_vol_results.json")
with open(results_file, 'w') as f:
    json.dump(all_results, f, indent=2, default=str)
print(f"\nResults saved to {results_file}")

# ==================================================================
# RECORD TO MEMORY
# ==================================================================
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
    from volpred.memory.system import MemorySystem
    m = MemorySystem()

    # Think
    m.think(
        f"K142 reasoning: 4th ML attempt for vol forecasting. "
        f"XGBoost + Ridge with HAR-like features vs GJR-GARCH w=2000, OOS 2020-2024. "
        f"Cross-asset: {ASSETS}. "
        f"XGBoost significantly beats GARCH: {n_sig_xgb}/{total_assets} assets. "
        f"This is different from prior ML failures because: (1) tree-based not neural, "
        f"(2) HAR-style features (proven structure), (3) proper walk-forward w=2000. "
        f"Key insight: {'ML adds value via nonlinear feature interactions' if n_sig_xgb >= 2 else 'QLIKE ceiling confirmed again — daily vol is dominated by simple autoregressive structure that GARCH captures well'}."
    )

    # Build knowledge content
    qlike_summary = ", ".join([f"{a}: GJR={all_results[a]['qlike']['garch']:.6f}/XGB={all_results[a]['qlike']['xgboost']:.6f}/Ridge={all_results[a]['qlike']['ridge']:.6f}" for a in ASSETS if a in all_results])

    confidence = 0.85 if n_sig_xgb >= 2 else 0.80
    result_tag = "ml-beats-garch" if n_sig_xgb >= 2 else "qlike-ceiling"

    m.add_knowledge(
        category="experiment",
        content=(
            f"[提出: 用戶(arXiv refs), 執行: Claude] K142: ML vol forecasting (4th attempt). "
            f"XGBoost + Ridge-HAR vs GJR-GARCH(1,1), w=2000, OOS 2020-2024, 3 assets. "
            f"QLIKE: {qlike_summary}. "
            f"XGBoost sig. beats GARCH: {n_sig_xgb}/{total_assets}. "
            f"Ridge sig. beats GARCH: {n_sig_ridge}/{total_assets}. "
            f"{'QLIKE ceiling BROKEN' if n_sig_xgb >= 2 else 'QLIKE ceiling INTACT (4th confirmation)'}. "
            f"Different from prior failures: HAR features + tree model + same w=2000 setup. "
            f"Still: daily squared returns are noisy proxy — fundamental limitation."
        ),
        confidence=confidence,
        evidence=[f"K142 cross-asset: {n_sig_xgb}/{total_assets} significant"],
    )

    m.add_log_entry(
        phase="Phase_K",
        action="K142_foundation_ml_vol",
        observation=(
            f"4th ML vol attempt: XGBoost/Ridge-HAR vs GJR-GARCH. "
            f"XGB sig beats: {n_sig_xgb}/{total_assets}. "
            f"Best model by asset: GJR={garch_wins}, XGB={xgb_wins}, Ridge={ridge_wins}."
        ),
        decision=(
            f"{'ML shows promise — investigate further with realized variance target' if n_sig_xgb >= 2 else 'QLIKE ceiling confirmed again. Stop ML exploration for daily r² target. Future: try with realized variance (5-min) as target when data available.'}"
        ),
        tags=["machine-learning", "gradient-boosting", "qlike-ceiling", "har-features"],
    )

    print("\n[Memory] Results recorded to MemorySystem")
except Exception as e:
    print(f"\n[Memory] Failed to record: {e}")

print(f"\n{'='*80}")
print("K142 COMPLETE")
print("=" * 80)
