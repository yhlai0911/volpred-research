"""
VIX Term Structure as Volatility Predictor
==========================================
Test whether VIX/VIX3M ratio (term structure slope) adds predictive
power for next-month SPY realized volatility beyond GARCH alone.

Predictors compared:
  1. GARCH-only: GJR-GARCH(1,1) 22-day-ahead variance forecast
  2. VIX-only: VIX / sqrt(12) as daily vol proxy → monthly
  3. VIX + VIX/VIX3M: OLS regression with both VIX level & term structure ratio

OOS period: 2020-01 to 2025-12, non-overlapping 22-day windows
Metric: R² of predicted vs realized monthly vol, QLIKE, MAE

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
import json
from datetime import datetime

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("VIX Term Structure as Monthly Vol Predictor")
print("=" * 70)

print("\n[1/5] Downloading data...")

# SPY for returns
spy = yf.download("SPY", start="2005-01-01", end="2026-01-01", progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy_close_col = "Adj Close" if "Adj Close" in spy.columns else "Close"
spy_ret = spy[spy_close_col].pct_change().dropna()
spy_ret.name = "returns"

# VIX
vix_raw = yf.download("^VIX", start="2005-01-01", end="2026-01-01", progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()
vix.name = "VIX"

# VIX3M (3-month VIX)
vix3m_raw = yf.download("^VIX3M", start="2005-01-01", end="2026-01-01", progress=False)
if isinstance(vix3m_raw.columns, pd.MultiIndex):
    vix3m_raw.columns = vix3m_raw.columns.get_level_values(0)
vix3m = vix3m_raw["Close"].copy()
vix3m.name = "VIX3M"

print(f"  SPY returns: {spy_ret.index[0].strftime('%Y-%m-%d')} to {spy_ret.index[-1].strftime('%Y-%m-%d')} ({len(spy_ret)} obs)")
print(f"  VIX: {vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')} ({len(vix)} obs)")
print(f"  VIX3M: {vix3m.index[0].strftime('%Y-%m-%d')} to {vix3m.index[-1].strftime('%Y-%m-%d')} ({len(vix3m)} obs)")

# ============================================================
# 2. Build non-overlapping 22-day windows
# ============================================================
print("\n[2/5] Building non-overlapping 22-day windows...")

# Align all series
common_idx = spy_ret.index.intersection(vix.index).intersection(vix3m.index)
spy_ret = spy_ret.loc[common_idx]
vix = vix.loc[common_idx]
vix3m = vix3m.loc[common_idx]

# Term structure ratio
ts_ratio = vix / vix3m
ts_ratio.name = "VIX_VIX3M_ratio"

# OOS start: 2020-01-01 (need training data before this)
oos_start = pd.Timestamp("2020-01-01")
oos_mask = spy_ret.index >= oos_start
oos_dates = spy_ret.index[oos_mask]

# Build non-overlapping 22-day windows in OOS
windows = []
i = 0
while i + 22 <= len(oos_dates):
    window_start = oos_dates[i]
    window_end = oos_dates[i + 21]  # 22 trading days

    # Realized vol for this window (annualized)
    window_returns = spy_ret.loc[oos_dates[i]:oos_dates[i + 21]]
    realized_vol = window_returns.std() * np.sqrt(252)

    # Predictors: use the last trading day BEFORE the window
    # Find the date just before window_start
    all_dates_before = spy_ret.index[spy_ret.index < window_start]
    if len(all_dates_before) == 0:
        i += 22
        continue
    pred_date = all_dates_before[-1]

    if pred_date in vix.index and pred_date in vix3m.index:
        windows.append({
            "window_start": window_start,
            "window_end": window_end,
            "pred_date": pred_date,
            "realized_vol": realized_vol,
            "vix_level": vix.loc[pred_date],
            "vix3m_level": vix3m.loc[pred_date],
            "ts_ratio": ts_ratio.loc[pred_date],
        })
    i += 22

df_windows = pd.DataFrame(windows)
print(f"  Total non-overlapping 22-day windows: {len(df_windows)}")
print(f"  Period: {df_windows['window_start'].iloc[0].strftime('%Y-%m-%d')} to {df_windows['window_end'].iloc[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 3. GJR-GARCH rolling forecasts
# ============================================================
print("\n[3/5] Computing GJR-GARCH rolling 22-day forecasts...")

GARCH_WINDOW = 2000  # 2000-day rolling window

garch_forecasts = []
for idx, row in df_windows.iterrows():
    pred_date = row["pred_date"]

    # Get training data: GARCH_WINDOW days ending at pred_date
    train_end_loc = spy_ret.index.get_loc(pred_date)
    train_start_loc = max(0, train_end_loc - GARCH_WINDOW + 1)
    train_data = spy_ret.iloc[train_start_loc:train_end_loc + 1]

    if len(train_data) < 500:
        garch_forecasts.append(np.nan)
        continue

    try:
        returns_pct = train_data.values * 100
        model = arch_model(
            returns_pct,
            vol="GARCH", p=1, o=1, q=1,
            dist="normal", mean="Zero", rescale=False
        )
        result = model.fit(disp="off", show_warning=False)

        # Multi-step forecast: sum of 22-day variances
        fcast = result.forecast(horizon=22)
        # Sum variances over 22 days, convert from pct^2 back
        var_22d = fcast.variance.iloc[-1].sum() / 10000
        # Annualized vol
        garch_vol = np.sqrt(var_22d * (252 / 22))
        garch_forecasts.append(garch_vol)
    except Exception as e:
        garch_forecasts.append(np.nan)

df_windows["garch_vol"] = garch_forecasts

# VIX-implied monthly vol (VIX is already annualized)
df_windows["vix_vol"] = df_windows["vix_level"] / 100  # VIX is in percentage

# Drop any NaN
df_valid = df_windows.dropna().copy()
print(f"  Valid windows after GARCH: {len(df_valid)}")

# ============================================================
# 4. Regression analysis (expanding window OOS)
# ============================================================
print("\n[4/5] Running OOS regression analysis...")

# We'll use expanding-window OOS: first 12 months for initial training
INIT_TRAIN = 12  # first 12 windows (~1 year) for initial fit

y = df_valid["realized_vol"].values
x_garch = df_valid["garch_vol"].values
x_vix = df_valid["vix_vol"].values
x_ratio = df_valid["ts_ratio"].values

# Storage for OOS predictions
oos_pred_garch = []
oos_pred_vix = []
oos_pred_vix_ts = []
oos_realized = []

from numpy.linalg import lstsq

for t in range(INIT_TRAIN, len(y)):
    # Training: all data up to t-1
    y_train = y[:t]

    # Model 1: GARCH-only (OLS: realized_vol ~ alpha + beta * garch_vol)
    X1 = np.column_stack([np.ones(t), x_garch[:t]])
    beta1, _, _, _ = lstsq(X1, y_train, rcond=None)
    pred1 = beta1[0] + beta1[1] * x_garch[t]
    oos_pred_garch.append(pred1)

    # Model 2: VIX-only (OLS: realized_vol ~ alpha + beta * vix_vol)
    X2 = np.column_stack([np.ones(t), x_vix[:t]])
    beta2, _, _, _ = lstsq(X2, y_train, rcond=None)
    pred2 = beta2[0] + beta2[1] * x_vix[t]
    oos_pred_vix.append(pred2)

    # Model 3: VIX + Term Structure (realized_vol ~ alpha + beta1*vix + beta2*ratio)
    X3 = np.column_stack([np.ones(t), x_vix[:t], x_ratio[:t]])
    beta3, _, _, _ = lstsq(X3, y_train, rcond=None)
    pred3 = beta3[0] + beta3[1] * x_vix[t] + beta3[2] * x_ratio[t]
    oos_pred_vix_ts.append(pred3)

    oos_realized.append(y[t])

oos_realized = np.array(oos_realized)
oos_pred_garch = np.array(oos_pred_garch)
oos_pred_vix = np.array(oos_pred_vix)
oos_pred_vix_ts = np.array(oos_pred_vix_ts)

# ============================================================
# 5. Evaluation metrics
# ============================================================
print("\n[5/5] Computing evaluation metrics...")

def oos_r2(y_true, y_pred):
    """OOS R² = 1 - SS_res / SS_tot"""
    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    return 1 - ss_res / ss_tot

def mae(y_true, y_pred):
    return np.mean(np.abs(y_true - y_pred))

def qlike(y_true, y_pred):
    """QLIKE loss: mean(sigma2_true/sigma2_pred + log(sigma2_pred))"""
    # Use variance (vol^2)
    s2_true = y_true ** 2
    s2_pred = np.maximum(y_pred ** 2, 1e-12)
    return np.mean(s2_true / s2_pred + np.log(s2_pred))

def rmse(y_true, y_pred):
    return np.sqrt(np.mean((y_true - y_pred) ** 2))

# Compute metrics
models = {
    "GARCH-only": oos_pred_garch,
    "VIX-only": oos_pred_vix,
    "VIX + Term Structure": oos_pred_vix_ts,
}

print("\n" + "=" * 70)
print("RESULTS: OOS Monthly Vol Prediction (expanding window)")
print(f"OOS period: {df_valid.iloc[INIT_TRAIN]['window_start'].strftime('%Y-%m-%d')} to {df_valid.iloc[-1]['window_end'].strftime('%Y-%m-%d')}")
print(f"Number of OOS windows: {len(oos_realized)}")
print("=" * 70)

print(f"\n{'Model':<25} {'R²':>8} {'RMSE':>8} {'MAE':>8} {'QLIKE':>8}")
print("-" * 60)

results = {}
for name, pred in models.items():
    r2 = oos_r2(oos_realized, pred)
    r = rmse(oos_realized, pred)
    m = mae(oos_realized, pred)
    q = qlike(oos_realized, pred)
    results[name] = {"R2": r2, "RMSE": r, "MAE": m, "QLIKE": q}
    print(f"{name:<25} {r2:>8.4f} {r:>8.4f} {m:>8.4f} {q:>8.4f}")

# ============================================================
# 6. Statistical tests
# ============================================================
print("\n" + "-" * 60)
print("Statistical Tests")
print("-" * 60)

# Diebold-Mariano test: GARCH vs VIX+TS
def dm_test(e1, e2, h=1):
    """Diebold-Mariano test for equal predictive accuracy (squared errors)."""
    d = e1**2 - e2**2
    d_bar = np.mean(d)
    # Newey-West-style variance for h-step ahead
    T = len(d)
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        var_d += 2 * (1 - k/h) * gamma_k
    se = np.sqrt(var_d / T)
    if se < 1e-12:
        return 0, 1.0
    dm_stat = d_bar / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return dm_stat, p_val

e_garch = oos_realized - oos_pred_garch
e_vix = oos_realized - oos_pred_vix
e_vix_ts = oos_realized - oos_pred_vix_ts

dm1, p1 = dm_test(e_garch, e_vix)
print(f"DM test GARCH vs VIX-only: stat={dm1:.3f}, p={p1:.4f}")
dm2, p2 = dm_test(e_garch, e_vix_ts)
print(f"DM test GARCH vs VIX+TS:   stat={dm2:.3f}, p={p2:.4f}")
dm3, p3 = dm_test(e_vix, e_vix_ts)
print(f"DM test VIX vs VIX+TS:     stat={dm3:.3f}, p={p3:.4f}")

# ============================================================
# 7. In-sample regression diagnostics (full sample)
# ============================================================
print("\n" + "-" * 60)
print("Full-sample Regression Diagnostics")
print("-" * 60)

# Model 3 full sample: check coefficient on term structure ratio
X_full = np.column_stack([np.ones(len(y)), x_vix, x_ratio])
beta_full, residuals, rank, sv = lstsq(X_full, y, rcond=None)

# Standard errors
y_hat = X_full @ beta_full
resid = y - y_hat
n, k = X_full.shape
sigma2_resid = np.sum(resid**2) / (n - k)
cov_beta = sigma2_resid * np.linalg.inv(X_full.T @ X_full)
se_beta = np.sqrt(np.diag(cov_beta))
t_stats = beta_full / se_beta

print(f"\nFull-sample VIX + Term Structure regression (n={n}):")
print(f"  Intercept:        {beta_full[0]:>8.4f}  (t={t_stats[0]:>6.2f})")
print(f"  VIX level:        {beta_full[1]:>8.4f}  (t={t_stats[1]:>6.2f})")
print(f"  VIX/VIX3M ratio:  {beta_full[2]:>8.4f}  (t={t_stats[2]:>6.2f})")

# In-sample R²
ss_res = np.sum(resid**2)
ss_tot = np.sum((y - np.mean(y))**2)
r2_is = 1 - ss_res / ss_tot
print(f"  In-sample R²:     {r2_is:.4f}")

# ============================================================
# 8. Descriptive stats on term structure ratio
# ============================================================
print("\n" + "-" * 60)
print("VIX Term Structure Descriptive Stats (OOS period)")
print("-" * 60)

ratio_oos = df_valid["ts_ratio"].values
print(f"  Mean VIX/VIX3M:   {np.mean(ratio_oos):.4f}")
print(f"  Std:              {np.std(ratio_oos):.4f}")
print(f"  Min:              {np.min(ratio_oos):.4f}")
print(f"  Max:              {np.max(ratio_oos):.4f}")
print(f"  % in backwardation (>1): {100*np.mean(ratio_oos > 1):.1f}%")

# Correlation matrix
print(f"\n  Correlation with realized vol:")
corr_garch = np.corrcoef(oos_realized, oos_pred_garch[:])[0, 1]
corr_vix = np.corrcoef(oos_realized, oos_pred_vix[:])[0, 1]
corr_ts = np.corrcoef(df_valid["realized_vol"].values[INIT_TRAIN:], df_valid["ts_ratio"].values[INIT_TRAIN:])[0, 1]
print(f"    GARCH forecast:  {corr_garch:.4f}")
print(f"    VIX level:       {corr_vix:.4f}")
print(f"    VIX/VIX3M ratio: {corr_ts:.4f}")

# ============================================================
# 9. Sub-period analysis
# ============================================================
print("\n" + "-" * 60)
print("Sub-period Analysis (R²)")
print("-" * 60)

# Split OOS into sub-periods
oos_window_dates = df_valid.iloc[INIT_TRAIN:]["window_start"].values
oos_years = pd.DatetimeIndex(oos_window_dates).year

for year in sorted(oos_years.unique()):
    mask = oos_years == year
    if mask.sum() < 3:
        continue
    r2_g = oos_r2(oos_realized[mask], oos_pred_garch[mask])
    r2_v = oos_r2(oos_realized[mask], oos_pred_vix[mask])
    r2_vt = oos_r2(oos_realized[mask], oos_pred_vix_ts[mask])
    print(f"  {year}: GARCH={r2_g:>7.3f}  VIX={r2_v:>7.3f}  VIX+TS={r2_vt:>7.3f}  (n={mask.sum()})")

# ============================================================
# 10. Backwardation regime analysis
# ============================================================
print("\n" + "-" * 60)
print("Regime Analysis: Contango vs Backwardation")
print("-" * 60)

ratio_oos_windows = df_valid["ts_ratio"].values[INIT_TRAIN:]
backwardation = ratio_oos_windows > 1.0
contango = ~backwardation

print(f"\n  Contango (VIX/VIX3M < 1, n={contango.sum()}):")
if contango.sum() > 3:
    for name, pred in [("GARCH", oos_pred_garch), ("VIX", oos_pred_vix), ("VIX+TS", oos_pred_vix_ts)]:
        r2 = oos_r2(oos_realized[contango], pred[contango])
        m = mae(oos_realized[contango], pred[contango])
        print(f"    {name:<10} R²={r2:.4f}  MAE={m:.4f}")

print(f"\n  Backwardation (VIX/VIX3M > 1, n={backwardation.sum()}):")
if backwardation.sum() > 3:
    for name, pred in [("GARCH", oos_pred_garch), ("VIX", oos_pred_vix), ("VIX+TS", oos_pred_vix_ts)]:
        r2 = oos_r2(oos_realized[backwardation], pred[backwardation])
        m = mae(oos_realized[backwardation], pred[backwardation])
        print(f"    {name:<10} R²={r2:.4f}  MAE={m:.4f}")

# ============================================================
# 11. Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

best_model = max(results.items(), key=lambda x: x[1]["R2"])
print(f"\nBest model by OOS R²: {best_model[0]} (R²={best_model[1]['R2']:.4f})")

ts_incremental = results["VIX + Term Structure"]["R2"] - results["VIX-only"]["R2"]
garch_vs_vix = results["VIX-only"]["R2"] - results["GARCH-only"]["R2"]
print(f"\nIncremental R² from term structure (VIX+TS vs VIX): {ts_incremental:+.4f}")
print(f"VIX vs GARCH R² difference: {garch_vs_vix:+.4f}")
print(f"DM test VIX vs VIX+TS: p={p3:.4f} ({'significant' if p3 < 0.10 else 'not significant'} at 10%)")

if ts_incremental > 0.01 and p3 < 0.10:
    conclusion = "VIX term structure ADDS meaningful predictive power beyond VIX alone"
elif ts_incremental > 0:
    conclusion = "VIX term structure adds marginal improvement, but NOT statistically significant"
else:
    conclusion = "VIX term structure does NOT add predictive power beyond VIX alone"

print(f"\nConclusion: {conclusion}")
print(f"VIX/VIX3M ratio coefficient (full-sample): {beta_full[2]:.4f} (t={t_stats[2]:.2f})")

# Save results
output = {
    "experiment": "vix_term_structure_vol_prediction",
    "oos_period": f"{df_valid.iloc[INIT_TRAIN]['window_start'].strftime('%Y-%m-%d')} to {df_valid.iloc[-1]['window_end'].strftime('%Y-%m-%d')}",
    "n_windows_total": len(df_windows),
    "n_windows_oos": len(oos_realized),
    "init_train_windows": INIT_TRAIN,
    "garch_window": GARCH_WINDOW,
    "results": {k: {m: round(float(v), 6) for m, v in metrics.items()} for k, metrics in results.items()},
    "dm_tests": {
        "garch_vs_vix": {"stat": round(float(dm1), 4), "p": round(float(p1), 4)},
        "garch_vs_vix_ts": {"stat": round(float(dm2), 4), "p": round(float(p2), 4)},
        "vix_vs_vix_ts": {"stat": round(float(dm3), 4), "p": round(float(p3), 4)},
    },
    "full_sample_regression": {
        "intercept": round(float(beta_full[0]), 6),
        "vix_coef": round(float(beta_full[1]), 6),
        "ts_ratio_coef": round(float(beta_full[2]), 6),
        "ts_ratio_t_stat": round(float(t_stats[2]), 4),
        "in_sample_r2": round(float(r2_is), 6),
    },
    "conclusion": conclusion,
    "created_at": datetime.now().isoformat(),
}

output_path = "/Users/yhlai0911/Dropbox/自我研究波動預測模型/experiments/vix_term_structure_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2)
print(f"\nResults saved to {output_path}")
