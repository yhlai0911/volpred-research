#!/usr/bin/env python3
"""
XGBoost Vol Predictor + SHAP Interpretability
面向 G: ML 可解釋性

Tests whether XGBoost can beat GJR-GARCH for SPY 22-day vol prediction,
and uses SHAP to identify which features matter most.

Key question: Does VIX dominate all other features? (VIX sufficiency test)

Author: VolPred Research System
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from pathlib import Path

warnings.filterwarnings("ignore")

# ─── Config ───
TRAIN_END = "2021-12-31"
TEST_START = "2022-01-01"
TARGET_WINDOW = 22  # 22-day forward realized vol
RANDOM_SEED = 42

print("=" * 70)
print("XGBoost Vol Predictor + SHAP Interpretability")
print("面向 G: ML 可解釋性")
print("=" * 70)

# ─── 1. Data Download ───
print("\n[1/7] Downloading data...")

tickers = {
    "SPY": "SPY",
    "GLD": "GLD",
    "TLT": "TLT",
    "EEM": "EEM",
    "VIX": "^VIX",
    "VIX3M": "^VIX3M",
}

raw = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2006-01-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    raw[name] = df
    print(f"  {name}: {len(df)} rows, {df.index[0].date()} to {df.index[-1].date()}")

spy = raw["SPY"]
vix = raw["VIX"]["Close"]
vix3m = raw["VIX3M"]["Close"]
gld_close = raw["GLD"]["Close"]
tlt_close = raw["TLT"]["Close"]
eem_close = raw["EEM"]["Close"]

# ─── 2. Feature Engineering ───
print("\n[2/7] Engineering features (20+ features)...")

df = pd.DataFrame(index=spy.index)
df["close"] = spy["Close"]
df["log_price"] = np.log(spy["Close"])
df["daily_return"] = spy["Close"].pct_change()

# Price-based features
for w in [5, 10, 22, 63]:
    df[f"ret_{w}d"] = df["close"].pct_change(w)
    df[f"rv_{w}d"] = df["daily_return"].rolling(w).std() * np.sqrt(252)

# Realized vol ratios (short/long)
df["rv_ratio_5_22"] = df["rv_5d"] / df["rv_22d"]
df["rv_ratio_22_63"] = df["rv_22d"] / df["rv_63d"]

# VIX features
df["vix"] = vix
df["vix_chg_1d"] = vix.pct_change()
df["vix_chg_5d"] = vix.pct_change(5)
df["vix_zscore"] = (vix - vix.rolling(63).mean()) / vix.rolling(63).std()
df["vix_vix3m_ratio"] = vix / vix3m  # term structure
df["vix_rv22_spread"] = vix / 100 - df["rv_22d"]  # VRP proxy

# RSI(14)
delta = df["close"].diff()
gain = delta.where(delta > 0, 0).rolling(14).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
rs = gain / loss
df["rsi_14"] = 100 - (100 / (1 + rs))

# MACD
ema12 = df["close"].ewm(span=12).mean()
ema26 = df["close"].ewm(span=26).mean()
macd_line = ema12 - ema26
signal_line = macd_line.ewm(span=9).mean()
df["macd_signal"] = macd_line - signal_line

# Bollinger bandwidth
bb_mid = df["close"].rolling(20).mean()
bb_std = df["close"].rolling(20).std()
df["bb_bandwidth"] = (2 * bb_std) / bb_mid

# Calendar features
df["day_of_week"] = df.index.dayofweek
df["month"] = df.index.month

# FOMC approximation: distance to 3rd Wednesday of next month
def days_to_approx_fomc(dates):
    """Approximate days to next FOMC (3rd Wednesday of month, ~8 meetings/year)"""
    result = []
    # Typical FOMC months: Jan, Mar, May, Jun, Jul, Sep, Nov, Dec
    fomc_months = [1, 3, 5, 6, 7, 9, 11, 12]
    for d in dates:
        # Find next FOMC month
        best = 60
        for m in fomc_months:
            y = d.year if m >= d.month else d.year + 1
            # 3rd Wednesday: find first day of month, compute 3rd Wednesday
            first = pd.Timestamp(y, m, 1)
            # Wednesday = 2
            wed_offset = (2 - first.dayofweek) % 7
            third_wed = first + pd.Timedelta(days=wed_offset + 14)
            diff = (third_wed - d).days
            if 0 < diff < best:
                best = diff
        result.append(best)
    return result

df["days_to_fomc"] = days_to_approx_fomc(df.index)

# Cross-asset features
df["gld_ret_5d"] = gld_close.pct_change(5)
df["tlt_ret_5d"] = tlt_close.pct_change(5)
df["eem_ret_5d"] = eem_close.pct_change(5)

# ─── 3. Target: 22-day forward realized vol ───
print("\n[3/7] Computing target (22-day forward realized vol)...")

fwd_rv = df["daily_return"].rolling(TARGET_WINDOW).std().shift(-TARGET_WINDOW) * np.sqrt(252)
df["target_rv22"] = fwd_rv

# Feature list (exclude target, close, log_price, daily_return)
FEATURE_COLS = [
    "ret_5d", "ret_10d", "ret_22d", "ret_63d",
    "rv_5d", "rv_10d", "rv_22d", "rv_63d",
    "rv_ratio_5_22", "rv_ratio_22_63",
    "vix", "vix_chg_1d", "vix_chg_5d", "vix_zscore",
    "vix_vix3m_ratio", "vix_rv22_spread",
    "rsi_14", "macd_signal", "bb_bandwidth",
    "day_of_week", "month", "days_to_fomc",
    "gld_ret_5d", "tlt_ret_5d", "eem_ret_5d",
]

print(f"  Total features: {len(FEATURE_COLS)}")
print(f"  Features: {FEATURE_COLS}")

# Drop NaN rows
df_clean = df[FEATURE_COLS + ["target_rv22"]].dropna()
print(f"  Clean dataset: {len(df_clean)} rows ({df_clean.index[0].date()} to {df_clean.index[-1].date()})")

# ─── 4. Train/Test Split (proper time-series, NO shuffling) ───
print("\n[4/7] Train/test split (time-series, no shuffling)...")

train = df_clean[df_clean.index <= TRAIN_END]
test = df_clean[df_clean.index >= TEST_START]

X_train = train[FEATURE_COLS].values
y_train = train["target_rv22"].values
X_test = test[FEATURE_COLS].values
y_test = test["target_rv22"].values

print(f"  Train: {len(train)} rows ({train.index[0].date()} to {train.index[-1].date()})")
print(f"  Test:  {len(test)} rows ({test.index[0].date()} to {test.index[-1].date()})")

# ─── 5. Models ───
print("\n[5/7] Training models...")

from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_squared_error, r2_score
import xgboost as xgb

results = {}

# --- A. Linear Regression ---
print("\n  [A] Linear Regression...")
lr = LinearRegression()
lr.fit(X_train, y_train)
y_pred_lr = lr.predict(X_test)
y_pred_lr = np.maximum(y_pred_lr, 0.01)  # floor at 1% vol

mse_lr = mean_squared_error(y_test, y_pred_lr)
r2_lr = r2_score(y_test, y_pred_lr)

# QLIKE: mean(log(pred^2) + actual^2 / pred^2)
# Using annualized vol directly
qlike_lr = np.mean(np.log(y_pred_lr**2) + (y_test**2) / (y_pred_lr**2))

print(f"    MSE:   {mse_lr:.6f}")
print(f"    R²:    {r2_lr:.4f}")
print(f"    QLIKE: {qlike_lr:.4f}")

results["linear_regression"] = {
    "mse": float(mse_lr),
    "r2": float(r2_lr),
    "qlike": float(qlike_lr),
}

# --- B. XGBoost Default ---
print("\n  [B] XGBoost (default params)...")
xgb_default = xgb.XGBRegressor(
    n_estimators=500,
    max_depth=6,
    learning_rate=0.1,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=RANDOM_SEED,
    n_jobs=-1,
    verbosity=0,
)
xgb_default.fit(
    X_train, y_train,
    eval_set=[(X_test, y_test)],
    verbose=False,
)
y_pred_xgb = xgb_default.predict(X_test)
y_pred_xgb = np.maximum(y_pred_xgb, 0.01)

mse_xgb = mean_squared_error(y_test, y_pred_xgb)
r2_xgb = r2_score(y_test, y_pred_xgb)
qlike_xgb = np.mean(np.log(y_pred_xgb**2) + (y_test**2) / (y_pred_xgb**2))

print(f"    MSE:   {mse_xgb:.6f}")
print(f"    R²:    {r2_xgb:.4f}")
print(f"    QLIKE: {qlike_xgb:.4f}")

results["xgboost_default"] = {
    "mse": float(mse_xgb),
    "r2": float(r2_xgb),
    "qlike": float(qlike_xgb),
    "params": {
        "n_estimators": 500,
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
    },
}

# --- C. XGBoost Tuned (Grid Search with Time-Series CV) ---
print("\n  [C] XGBoost (grid search on train set with TS-CV)...")

from sklearn.model_selection import TimeSeriesSplit

tscv = TimeSeriesSplit(n_splits=5)

param_grid = {
    "n_estimators": [200, 500, 1000],
    "max_depth": [3, 5, 7],
    "learning_rate": [0.01, 0.05, 0.1],
    "subsample": [0.7, 0.9],
    "colsample_bytree": [0.7, 0.9],
    "min_child_weight": [3, 10],
}

# Rather than full grid (3*3*3*2*2*2=216 combos), use random search
from sklearn.model_selection import RandomizedSearchCV

xgb_base = xgb.XGBRegressor(random_state=RANDOM_SEED, n_jobs=-1, verbosity=0)

random_search = RandomizedSearchCV(
    xgb_base,
    param_distributions=param_grid,
    n_iter=50,
    cv=tscv,
    scoring="neg_mean_squared_error",
    random_state=RANDOM_SEED,
    n_jobs=-1,
    verbose=0,
)
random_search.fit(X_train, y_train)

best_params = random_search.best_params_
print(f"    Best params: {best_params}")

xgb_tuned = random_search.best_estimator_
y_pred_tuned = xgb_tuned.predict(X_test)
y_pred_tuned = np.maximum(y_pred_tuned, 0.01)

mse_tuned = mean_squared_error(y_test, y_pred_tuned)
r2_tuned = r2_score(y_test, y_pred_tuned)
qlike_tuned = np.mean(np.log(y_pred_tuned**2) + (y_test**2) / (y_pred_tuned**2))

print(f"    MSE:   {mse_tuned:.6f}")
print(f"    R²:    {r2_tuned:.4f}")
print(f"    QLIKE: {qlike_tuned:.4f}")

results["xgboost_tuned"] = {
    "mse": float(mse_tuned),
    "r2": float(r2_tuned),
    "qlike": float(qlike_tuned),
    "best_params": {k: int(v) if isinstance(v, (int, np.integer)) else float(v) for k, v in best_params.items()},
}

# --- D. GJR-GARCH Benchmark ---
print("\n  [D] GJR-GARCH benchmark (rolling 22-day vol forecast)...")

from arch import arch_model

spy_returns = spy["Close"].pct_change().dropna() * 100  # percentage

# Rolling GJR-GARCH: for each test day, estimate model on past 2000 days,
# forecast 22-day ahead vol
test_dates = test.index
gjr_preds = []
gjr_dates = []
window = 2000

for i, date in enumerate(test_dates):
    loc = spy_returns.index.get_loc(date)
    if loc < window:
        continue

    train_data = spy_returns.iloc[loc - window:loc]

    try:
        am = arch_model(train_data, vol="GARCH", p=1, o=1, q=1, dist="t")
        res = am.fit(disp="off", show_warning=False)

        # Forecast 22-day ahead: h-step forecast, annualize
        fcast = res.forecast(horizon=22)
        # Average variance over 22 days, annualize
        avg_var = fcast.variance.iloc[-1].mean()  # mean of h1..h22
        ann_vol = np.sqrt(avg_var * 252) / 100  # back to decimal

        gjr_preds.append(ann_vol)
        gjr_dates.append(date)
    except Exception:
        continue

    if (i + 1) % 100 == 0:
        print(f"    ... {i+1}/{len(test_dates)} done")

print(f"    GJR-GARCH: {len(gjr_preds)} predictions")

# Align GJR predictions with test set
gjr_df = pd.DataFrame({"gjr_pred": gjr_preds}, index=gjr_dates)
aligned = test[["target_rv22"]].join(gjr_df, how="inner")

y_test_gjr = aligned["target_rv22"].values
y_pred_gjr = aligned["gjr_pred"].values
y_pred_gjr = np.maximum(y_pred_gjr, 0.01)

mse_gjr = mean_squared_error(y_test_gjr, y_pred_gjr)
r2_gjr = r2_score(y_test_gjr, y_pred_gjr)
qlike_gjr = np.mean(np.log(y_pred_gjr**2) + (y_test_gjr**2) / (y_pred_gjr**2))

print(f"    MSE:   {mse_gjr:.6f}")
print(f"    R²:    {r2_gjr:.4f}")
print(f"    QLIKE: {qlike_gjr:.4f}")

results["gjr_garch"] = {
    "mse": float(mse_gjr),
    "r2": float(r2_gjr),
    "qlike": float(qlike_gjr),
    "window": window,
    "n_predictions": len(gjr_preds),
}

# ─── 6. Diebold-Mariano Tests ───
print("\n[6/7] Diebold-Mariano tests (QLIKE loss)...")

from scipy import stats

def dm_test_qlike(actual, pred1, pred2, h=22):
    """DM test using QLIKE loss. H0: equal predictive accuracy."""
    loss1 = np.log(pred1**2) + (actual**2) / (pred1**2)
    loss2 = np.log(pred2**2) + (actual**2) / (pred2**2)
    d = loss1 - loss2

    # Newey-West HAC variance (lag = h-1)
    n = len(d)
    d_mean = np.mean(d)

    # Autocovariance
    gamma = np.zeros(h)
    for k in range(h):
        gamma[k] = np.mean((d[:n-k] - d_mean) * (d[k:] - d_mean))

    var_d = gamma[0] + 2 * sum((1 - k/h) * gamma[k] for k in range(1, h))
    var_d = max(var_d, 1e-12)

    dm_stat = d_mean / np.sqrt(var_d / n)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    return float(dm_stat), float(p_value)

# XGBoost tuned vs Linear
dm_xgb_lr, p_xgb_lr = dm_test_qlike(y_test, y_pred_tuned, y_pred_lr)
print(f"  XGBoost(tuned) vs Linear:  DM={dm_xgb_lr:.3f}, p={p_xgb_lr:.4f}")

# For GJR comparison, need aligned predictions
# Re-predict on aligned dates
aligned_idx = aligned.index
test_aligned = test.loc[aligned_idx]
X_test_aligned = test_aligned[FEATURE_COLS].values
y_test_aligned = test_aligned["target_rv22"].values

y_pred_tuned_aligned = xgb_tuned.predict(X_test_aligned)
y_pred_tuned_aligned = np.maximum(y_pred_tuned_aligned, 0.01)
y_pred_lr_aligned = lr.predict(X_test_aligned)
y_pred_lr_aligned = np.maximum(y_pred_lr_aligned, 0.01)

dm_xgb_gjr, p_xgb_gjr = dm_test_qlike(y_test_aligned, y_pred_tuned_aligned, y_pred_gjr)
dm_lr_gjr, p_lr_gjr = dm_test_qlike(y_test_aligned, y_pred_lr_aligned, y_pred_gjr)

print(f"  XGBoost(tuned) vs GJR:     DM={dm_xgb_gjr:.3f}, p={p_xgb_gjr:.4f}")
print(f"  Linear vs GJR:             DM={dm_lr_gjr:.3f}, p={p_lr_gjr:.4f}")

results["dm_tests"] = {
    "xgb_tuned_vs_linear": {"dm_stat": dm_xgb_lr, "p_value": p_xgb_lr,
                            "interpretation": "negative DM = XGBoost better" if dm_xgb_lr < 0 else "positive DM = Linear better"},
    "xgb_tuned_vs_gjr": {"dm_stat": dm_xgb_gjr, "p_value": p_xgb_gjr,
                          "interpretation": "negative DM = XGBoost better" if dm_xgb_gjr < 0 else "positive DM = GJR better"},
    "linear_vs_gjr": {"dm_stat": dm_lr_gjr, "p_value": p_lr_gjr,
                       "interpretation": "negative DM = Linear better" if dm_lr_gjr < 0 else "positive DM = GJR better"},
}

# ─── 7. SHAP Analysis ───
print("\n[7/7] SHAP analysis (feature importance + dependence)...")
import shap

# Use the tuned model for SHAP
explainer = shap.TreeExplainer(xgb_tuned)
shap_values = explainer.shap_values(X_test)

# Global feature importance (mean |SHAP|)
mean_abs_shap = np.mean(np.abs(shap_values), axis=0)
feature_importance = pd.DataFrame({
    "feature": FEATURE_COLS,
    "mean_abs_shap": mean_abs_shap,
}).sort_values("mean_abs_shap", ascending=False)

print("\n  SHAP Feature Importance Ranking:")
print("  " + "-" * 50)
total_shap = feature_importance["mean_abs_shap"].sum()
for i, row in feature_importance.iterrows():
    pct = row["mean_abs_shap"] / total_shap * 100
    bar = "█" * int(pct / 2)
    print(f"  {row['feature']:20s} {row['mean_abs_shap']:.4f} ({pct:5.1f}%) {bar}")

# VIX dominance analysis
vix_features = ["vix", "vix_chg_1d", "vix_chg_5d", "vix_zscore", "vix_vix3m_ratio", "vix_rv22_spread"]
rv_features = ["rv_5d", "rv_10d", "rv_22d", "rv_63d", "rv_ratio_5_22", "rv_ratio_22_63"]
ret_features = ["ret_5d", "ret_10d", "ret_22d", "ret_63d"]
tech_features = ["rsi_14", "macd_signal", "bb_bandwidth"]
calendar_features = ["day_of_week", "month", "days_to_fomc"]
cross_features = ["gld_ret_5d", "tlt_ret_5d", "eem_ret_5d"]

def group_importance(features, name):
    mask = feature_importance["feature"].isin(features)
    total = feature_importance.loc[mask, "mean_abs_shap"].sum()
    pct = total / feature_importance["mean_abs_shap"].sum() * 100
    return {"group": name, "total_shap": float(total), "pct": float(pct)}

groups = [
    group_importance(vix_features, "VIX-based"),
    group_importance(rv_features, "Realized Vol"),
    group_importance(ret_features, "Returns"),
    group_importance(tech_features, "Technical"),
    group_importance(calendar_features, "Calendar"),
    group_importance(cross_features, "Cross-Asset"),
]

print("\n  Feature Group Importance:")
print("  " + "-" * 50)
for g in sorted(groups, key=lambda x: -x["pct"]):
    bar = "█" * int(g["pct"] / 2)
    print(f"  {g['group']:15s} {g['pct']:5.1f}% {bar}")

# Top 5 feature SHAP dependence data
top5 = feature_importance.head(5)["feature"].tolist()
dependence_data = {}
for feat in top5:
    idx = FEATURE_COLS.index(feat)
    feat_vals = X_test[:, idx]
    shap_vals = shap_values[:, idx]

    # Compute correlation
    corr = float(np.corrcoef(feat_vals, shap_vals)[0, 1])

    dependence_data[feat] = {
        "correlation_with_shap": corr,
        "feature_mean": float(np.mean(feat_vals)),
        "feature_std": float(np.std(feat_vals)),
        "shap_mean": float(np.mean(shap_vals)),
        "shap_std": float(np.std(shap_vals)),
        "interpretation": (
            f"Higher {feat} → higher predicted vol" if corr > 0
            else f"Higher {feat} → lower predicted vol"
        ),
    }

# Feature redundancy analysis: correlation matrix of SHAP values
shap_corr = np.corrcoef(shap_values.T)
redundant_pairs = []
for i in range(len(FEATURE_COLS)):
    for j in range(i + 1, len(FEATURE_COLS)):
        if abs(shap_corr[i, j]) > 0.7:
            redundant_pairs.append({
                "feature_1": FEATURE_COLS[i],
                "feature_2": FEATURE_COLS[j],
                "shap_correlation": float(shap_corr[i, j]),
            })

print(f"\n  Redundant feature pairs (|SHAP corr| > 0.7): {len(redundant_pairs)}")
for pair in sorted(redundant_pairs, key=lambda x: -abs(x["shap_correlation"]))[:10]:
    print(f"    {pair['feature_1']:20s} ↔ {pair['feature_2']:20s}: r={pair['shap_correlation']:.3f}")

# ─── Summary ───
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

print(f"\n{'Model':<25} {'MSE':>10} {'R²':>8} {'QLIKE':>10}")
print("-" * 55)
print(f"{'Linear Regression':<25} {mse_lr:>10.6f} {r2_lr:>8.4f} {qlike_lr:>10.4f}")
print(f"{'XGBoost (default)':<25} {mse_xgb:>10.6f} {r2_xgb:>8.4f} {qlike_xgb:>10.4f}")
print(f"{'XGBoost (tuned)':<25} {mse_tuned:>10.6f} {r2_tuned:>8.4f} {qlike_tuned:>10.4f}")
print(f"{'GJR-GARCH':<25} {mse_gjr:>10.6f} {r2_gjr:>8.4f} {qlike_gjr:>10.4f}")

# Determine winner by QLIKE
all_qlike = {
    "linear_regression": qlike_lr,
    "xgboost_default": qlike_xgb,
    "xgboost_tuned": qlike_tuned,
    "gjr_garch": qlike_gjr,
}
best_model = min(all_qlike, key=all_qlike.get)
print(f"\nBest by QLIKE: {best_model} ({all_qlike[best_model]:.4f})")

# VIX sufficiency verdict
vix_pct = next(g["pct"] for g in groups if g["group"] == "VIX-based")
rv_pct = next(g["pct"] for g in groups if g["group"] == "Realized Vol")
print(f"\nVIX sufficiency test:")
print(f"  VIX-based features: {vix_pct:.1f}% of total SHAP")
print(f"  Realized Vol features: {rv_pct:.1f}% of total SHAP")
print(f"  Combined (vol info): {vix_pct + rv_pct:.1f}%")

if vix_pct + rv_pct > 60:
    vix_verdict = "CONFIRMED: Volatility information (VIX + RV) dominates predictions"
else:
    vix_verdict = "REJECTED: Other features contribute meaningfully"
print(f"  Verdict: {vix_verdict}")

# XGBoost vs GARCH verdict
if p_xgb_gjr < 0.05 and dm_xgb_gjr < 0:
    xgb_verdict = "XGBoost SIGNIFICANTLY BEATS GJR-GARCH"
elif p_xgb_gjr < 0.05 and dm_xgb_gjr > 0:
    xgb_verdict = "GJR-GARCH SIGNIFICANTLY BEATS XGBoost"
else:
    xgb_verdict = "NO significant difference between XGBoost and GJR-GARCH"
print(f"\nXGBoost vs GJR-GARCH: {xgb_verdict}")
print(f"  DM stat: {dm_xgb_gjr:.3f}, p-value: {p_xgb_gjr:.4f}")

# ─── Save Results ───
print("\n[SAVE] Writing experiment results...")

output = {
    "experiment_id": f"xgboost_shap_vol_{datetime.now().strftime('%Y%m%d')}",
    "model": "XGBoost + SHAP Interpretability",
    "description": "Tests whether XGBoost can beat GJR-GARCH for SPY 22-day vol prediction. Uses SHAP to identify which features matter most — even if ML doesn't beat GARCH, feature importance ranking is valuable.",
    "hypothesis": "Non-linear ML cannot significantly beat GARCH for vol prediction (Branco 2024), but SHAP can reveal feature importance structure",
    "asset": "SPY",
    "target": "22-day forward realized volatility (annualized)",
    "train_period": f"{train.index[0].date()} to {train.index[-1].date()}",
    "test_period": f"{test.index[0].date()} to {test.index[-1].date()}",
    "n_train": len(train),
    "n_test": len(test),
    "n_features": len(FEATURE_COLS),
    "features": FEATURE_COLS,
    "created_at": datetime.now().strftime("%Y-%m-%d"),
    "results": results,
    "shap_analysis": {
        "feature_importance_ranking": [
            {"rank": i + 1, "feature": row["feature"], "mean_abs_shap": float(row["mean_abs_shap"]),
             "pct_of_total": float(row["mean_abs_shap"] / total_shap * 100)}
            for i, (_, row) in enumerate(feature_importance.iterrows())
        ],
        "feature_group_importance": groups,
        "top5_dependence": dependence_data,
        "redundant_pairs": redundant_pairs[:15],
    },
    "dm_tests": results["dm_tests"],
    "conclusions": {
        "best_model_by_qlike": best_model,
        "xgb_vs_gjr_verdict": xgb_verdict,
        "vix_sufficiency_verdict": vix_verdict,
        "vix_group_pct": float(vix_pct),
        "vol_info_total_pct": float(vix_pct + rv_pct),
        "key_findings": [],
    },
}

# Build key findings
findings = []
findings.append(f"Best model by QLIKE: {best_model}")
findings.append(f"XGBoost vs GJR: {xgb_verdict} (DM={dm_xgb_gjr:.3f}, p={p_xgb_gjr:.4f})")
findings.append(f"VIX + RV features account for {vix_pct + rv_pct:.1f}% of prediction importance")
findings.append(f"Top feature: {feature_importance.iloc[0]['feature']} ({feature_importance.iloc[0]['mean_abs_shap']/total_shap*100:.1f}%)")
findings.append(f"{len(redundant_pairs)} redundant feature pairs found (|SHAP corr| > 0.7)")

# Check if technical/calendar/cross-asset add value
other_pct = 100 - vix_pct - rv_pct - next(g["pct"] for g in groups if g["group"] == "Returns")
findings.append(f"Non-vol features (technical+calendar+cross-asset) contribute {other_pct:.1f}% — {'marginal' if other_pct < 20 else 'meaningful'}")

output["conclusions"]["key_findings"] = findings

out_path = Path("/Users/yhlai0911/Dropbox/自我研究波動預測模型/storage/experiments/xgboost_shap_vol.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"  Saved to {out_path}")
print("\nDone!")
