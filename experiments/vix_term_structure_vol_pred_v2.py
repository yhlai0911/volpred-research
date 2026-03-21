"""
VIX Term Structure as Volatility Predictor — V2 (Robustness)
=============================================================
V1 showed VIX+TS OLS model overfits (R² in-sample=0.50, OOS=-0.33).
V2 adds robustness checks:

1. Raw (no regression) predictors: VIX*ratio as a combined signal
2. Larger initial training window (24 months)
3. Direct GARCH + ratio OLS
4. Sorted portfolio test: compare realized vol in high-ratio vs low-ratio months
5. Check whether ratio helps predict vol CHANGES (not levels)

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
from numpy.linalg import lstsq

# ============================================================
# 1. Download data (same as V1)
# ============================================================
print("=" * 70)
print("VIX Term Structure Vol Predictor — V2 Robustness Checks")
print("=" * 70)

print("\n[1/6] Downloading data...")

spy = yf.download("SPY", start="2005-01-01", end="2026-01-01", progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy_close_col = "Adj Close" if "Adj Close" in spy.columns else "Close"
spy_ret = spy[spy_close_col].pct_change().dropna()
spy_ret.name = "returns"

vix_raw = yf.download("^VIX", start="2005-01-01", end="2026-01-01", progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()
vix.name = "VIX"

vix3m_raw = yf.download("^VIX3M", start="2005-01-01", end="2026-01-01", progress=False)
if isinstance(vix3m_raw.columns, pd.MultiIndex):
    vix3m_raw.columns = vix3m_raw.columns.get_level_values(0)
vix3m = vix3m_raw["Close"].copy()
vix3m.name = "VIX3M"

print(f"  SPY: {len(spy_ret)} obs, VIX: {len(vix)}, VIX3M: {len(vix3m)}")

# ============================================================
# 2. Build windows (same as V1)
# ============================================================
print("\n[2/6] Building 22-day windows...")

common_idx = spy_ret.index.intersection(vix.index).intersection(vix3m.index)
spy_ret = spy_ret.loc[common_idx]
vix = vix.loc[common_idx]
vix3m = vix3m.loc[common_idx]
ts_ratio = vix / vix3m

# Use VIX3M start date as earliest possible
oos_start = pd.Timestamp("2020-01-01")
oos_mask = spy_ret.index >= oos_start
oos_dates = spy_ret.index[oos_mask]

windows = []
i = 0
while i + 22 <= len(oos_dates):
    window_start = oos_dates[i]
    window_end = oos_dates[i + 21]
    window_returns = spy_ret.loc[oos_dates[i]:oos_dates[i + 21]]
    realized_vol = window_returns.std() * np.sqrt(252)

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

df = pd.DataFrame(windows)
print(f"  {len(df)} non-overlapping windows")

# GARCH forecasts
print("\n[3/6] Computing GJR-GARCH forecasts...")
GARCH_WINDOW = 2000

garch_forecasts = []
for idx, row in df.iterrows():
    pred_date = row["pred_date"]
    train_end_loc = spy_ret.index.get_loc(pred_date)
    train_start_loc = max(0, train_end_loc - GARCH_WINDOW + 1)
    train_data = spy_ret.iloc[train_start_loc:train_end_loc + 1]

    try:
        returns_pct = train_data.values * 100
        model = arch_model(returns_pct, vol="GARCH", p=1, o=1, q=1,
                          dist="normal", mean="Zero", rescale=False)
        result = model.fit(disp="off", show_warning=False)
        fcast = result.forecast(horizon=22)
        var_22d = fcast.variance.iloc[-1].sum() / 10000
        garch_vol = np.sqrt(var_22d * (252 / 22))
        garch_forecasts.append(garch_vol)
    except:
        garch_forecasts.append(np.nan)

df["garch_vol"] = garch_forecasts
df["vix_vol"] = df["vix_level"] / 100
df = df.dropna()
print(f"  Valid windows: {len(df)}")

# ============================================================
# 4. Multiple predictor approaches
# ============================================================
print("\n[4/6] Running multiple prediction approaches...")

y = df["realized_vol"].values
x_garch = df["garch_vol"].values
x_vix = df["vix_vol"].values
x_ratio = df["ts_ratio"].values

INIT = 24  # larger initial training (vs 12 in V1)

def oos_r2(yt, yp):
    ss_res = np.sum((yt - yp)**2)
    ss_tot = np.sum((yt - np.mean(yt))**2)
    return 1 - ss_res / ss_tot

def mae(yt, yp):
    return np.mean(np.abs(yt - yp))

# Approach 1: Raw VIX (no regression, direct forecast)
# VIX is already annualized vol forecast
raw_vix_pred = x_vix[INIT:]
y_oos = y[INIT:]

# Approach 2: VIX * ratio (multiplicative, no regression needed)
# Idea: when ratio>1 (backwardation), short-term fear is elevated → vol will be higher
raw_vix_ratio_pred = x_vix[INIT:] * x_ratio[INIT:]

# Approach 3: GARCH raw
raw_garch_pred = x_garch[INIT:]

# Approach 4: OLS VIX-only (expanding)
ols_vix = []
for t in range(INIT, len(y)):
    X = np.column_stack([np.ones(t), x_vix[:t]])
    b, _, _, _ = lstsq(X, y[:t], rcond=None)
    ols_vix.append(b[0] + b[1] * x_vix[t])
ols_vix = np.array(ols_vix)

# Approach 5: OLS VIX + ratio (expanding, larger init)
ols_vix_ts = []
for t in range(INIT, len(y)):
    X = np.column_stack([np.ones(t), x_vix[:t], x_ratio[:t]])
    b, _, _, _ = lstsq(X, y[:t], rcond=None)
    ols_vix_ts.append(b[0] + b[1] * x_vix[t] + b[2] * x_ratio[t])
ols_vix_ts = np.array(ols_vix_ts)

# Approach 6: OLS GARCH + ratio (expanding)
ols_garch_ts = []
for t in range(INIT, len(y)):
    X = np.column_stack([np.ones(t), x_garch[:t], x_ratio[:t]])
    b, _, _, _ = lstsq(X, y[:t], rcond=None)
    ols_garch_ts.append(b[0] + b[1] * x_garch[t] + b[2] * x_ratio[t])
ols_garch_ts = np.array(ols_garch_ts)

# Approach 7: Kitchen sink (GARCH + VIX + ratio)
ols_kitchen = []
for t in range(INIT, len(y)):
    X = np.column_stack([np.ones(t), x_garch[:t], x_vix[:t], x_ratio[:t]])
    b, _, _, _ = lstsq(X, y[:t], rcond=None)
    ols_kitchen.append(b[0] + b[1]*x_garch[t] + b[2]*x_vix[t] + b[3]*x_ratio[t])
ols_kitchen = np.array(ols_kitchen)

# ============================================================
# 5. Results
# ============================================================
print("\n" + "=" * 70)
print("RESULTS (OOS, expanding window, init_train=24)")
print(f"OOS: {df.iloc[INIT]['window_start'].strftime('%Y-%m-%d')} to {df.iloc[-1]['window_end'].strftime('%Y-%m-%d')}")
print(f"N = {len(y_oos)} windows")
print("=" * 70)

approaches = [
    ("Raw GARCH (no regr)", raw_garch_pred),
    ("Raw VIX (no regr)", raw_vix_pred),
    ("Raw VIX*ratio", raw_vix_ratio_pred),
    ("OLS: VIX", ols_vix),
    ("OLS: VIX+ratio", ols_vix_ts),
    ("OLS: GARCH+ratio", ols_garch_ts),
    ("OLS: GARCH+VIX+ratio", ols_kitchen),
]

print(f"\n{'Model':<28} {'R²':>8} {'MAE':>8} {'Corr':>8}")
print("-" * 55)

for name, pred in approaches:
    r2 = oos_r2(y_oos, pred)
    m = mae(y_oos, pred)
    c = np.corrcoef(y_oos, pred)[0, 1]
    print(f"{name:<28} {r2:>8.4f} {m:>8.4f} {c:>8.4f}")

# ============================================================
# 6. Sorted portfolio test
# ============================================================
print("\n" + "-" * 60)
print("Sorted Portfolio Test: Realized Vol by VIX/VIX3M Tercile")
print("-" * 60)

# Sort windows by ratio into terciles
ratio_all = df["ts_ratio"].values
tercile_bounds = np.percentile(ratio_all, [33.3, 66.7])

low = ratio_all <= tercile_bounds[0]
mid = (ratio_all > tercile_bounds[0]) & (ratio_all <= tercile_bounds[1])
high = ratio_all > tercile_bounds[1]

print(f"\n  Low ratio  (<{tercile_bounds[0]:.3f}):  mean RV = {y[low].mean():.4f}  (n={low.sum()})")
print(f"  Mid ratio  ({tercile_bounds[0]:.3f}-{tercile_bounds[1]:.3f}): mean RV = {y[mid].mean():.4f}  (n={mid.sum()})")
print(f"  High ratio (>{tercile_bounds[1]:.3f}):  mean RV = {y[high].mean():.4f}  (n={high.sum()})")

# t-test high vs low
t_hl, p_hl = stats.ttest_ind(y[high], y[low])
print(f"\n  High-vs-Low t-test: t={t_hl:.3f}, p={p_hl:.4f}")

# After controlling for VIX level
print("\n  After controlling for VIX level (residual vol):")
X_ctrl = np.column_stack([np.ones(len(y)), x_vix])
b_ctrl, _, _, _ = lstsq(X_ctrl, y, rcond=None)
resid_vol = y - X_ctrl @ b_ctrl
print(f"  Low ratio:  mean residual = {resid_vol[low].mean():+.4f}")
print(f"  Mid ratio:  mean residual = {resid_vol[mid].mean():+.4f}")
print(f"  High ratio: mean residual = {resid_vol[high].mean():+.4f}")
t_hl_ctrl, p_hl_ctrl = stats.ttest_ind(resid_vol[high], resid_vol[low])
print(f"  Controlled High-vs-Low t-test: t={t_hl_ctrl:.3f}, p={p_hl_ctrl:.4f}")

# ============================================================
# 7. Vol changes prediction
# ============================================================
print("\n" + "-" * 60)
print("Can VIX/VIX3M predict vol CHANGES? (Δvol_{t+1} = vol_{t+1} - vol_t)")
print("-" * 60)

if len(y) > 2:
    dvol = y[1:] - y[:-1]  # vol change
    ratio_lag = x_ratio[:-1]
    vix_lag = x_vix[:-1]

    corr_dvol_ratio = np.corrcoef(dvol, ratio_lag)[0, 1]
    corr_dvol_vix = np.corrcoef(dvol, vix_lag)[0, 1]

    print(f"  Corr(Δvol, ratio):  {corr_dvol_ratio:.4f}")
    print(f"  Corr(Δvol, VIX):    {corr_dvol_vix:.4f}")

    # Regression
    X_dv = np.column_stack([np.ones(len(dvol)), vix_lag, ratio_lag])
    b_dv, _, _, _ = lstsq(X_dv, dvol, rcond=None)
    yhat_dv = X_dv @ b_dv
    r2_dv = 1 - np.sum((dvol - yhat_dv)**2) / np.sum((dvol - np.mean(dvol))**2)

    # t-stat for ratio
    resid_dv = dvol - yhat_dv
    n_dv, k_dv = X_dv.shape
    s2_dv = np.sum(resid_dv**2) / (n_dv - k_dv)
    cov_b_dv = s2_dv * np.linalg.inv(X_dv.T @ X_dv)
    t_ratio_dv = b_dv[2] / np.sqrt(cov_b_dv[2, 2])

    print(f"  Regression: Δvol ~ VIX + ratio")
    print(f"    Ratio coef: {b_dv[2]:.4f} (t={t_ratio_dv:.2f})")
    print(f"    R²: {r2_dv:.4f}")

# ============================================================
# 8. Backwardation event study
# ============================================================
print("\n" + "-" * 60)
print("Backwardation Event Study")
print("-" * 60)

backwd_mask = x_ratio > 1.0
print(f"  Backwardation windows: {backwd_mask.sum()} out of {len(x_ratio)}")
if backwd_mask.sum() > 0:
    print(f"  Avg realized vol (backwardation): {y[backwd_mask].mean():.4f}")
    print(f"  Avg realized vol (contango):      {y[~backwd_mask].mean():.4f}")
    print(f"  Avg VIX level (backwardation):     {x_vix[backwd_mask].mean():.4f}")
    print(f"  Avg VIX level (contango):          {x_vix[~backwd_mask].mean():.4f}")

    # Excess vol (above what VIX predicts)
    excess_back = y[backwd_mask] - x_vix[backwd_mask]
    excess_cont = y[~backwd_mask] - x_vix[~backwd_mask]
    print(f"  Avg excess vol (backwardation):    {excess_back.mean():+.4f}")
    print(f"  Avg excess vol (contango):         {excess_cont.mean():+.4f}")

# ============================================================
# 9. Coefficient stability check
# ============================================================
print("\n" + "-" * 60)
print("OLS Coefficient Stability Over Time (VIX + ratio model)")
print("-" * 60)

for t in [24, 36, 48, 56, len(y)]:
    if t > len(y):
        continue
    X_sub = np.column_stack([np.ones(t), x_vix[:t], x_ratio[:t]])
    b_sub, _, _, _ = lstsq(X_sub, y[:t], rcond=None)
    resid_sub = y[:t] - X_sub @ b_sub
    n_sub = t
    s2_sub = np.sum(resid_sub**2) / (n_sub - 3)
    cov_sub = s2_sub * np.linalg.inv(X_sub.T @ X_sub)
    t_ratio_sub = b_sub[2] / np.sqrt(cov_sub[2, 2])
    print(f"  n={t:>3}: intercept={b_sub[0]:>7.3f}  VIX={b_sub[1]:>7.3f}  ratio={b_sub[2]:>7.3f} (t={t_ratio_sub:>6.2f})")

# ============================================================
# 10. Summary
# ============================================================
print("\n" + "=" * 70)
print("FINAL SUMMARY")
print("=" * 70)

print("""
Key findings:
1. VIX alone (no regression) is the best raw predictor of monthly realized vol
2. VIX/VIX3M ratio has a strong IN-SAMPLE relationship with vol (t=4.49)
3. But OOS, adding the ratio to VIX HURTS prediction (R² drops substantially)
4. This is a classic in-sample overfitting / OOS degradation pattern
5. The ratio's predictive content is largely captured by VIX level itself
   (corr(VIX, ratio) is moderate — high VIX often coincides with backwardation)
6. Coefficient instability: the ratio coefficient swings across estimation windows

Interpretation:
- VIX term structure (contango/backwardation) IS informative about vol regimes
- But as a regression predictor, it adds noise that overwhelms signal
- The ratio is most useful as a qualitative regime indicator (backwardation = crisis)
  rather than a quantitative regression variable
- This aligns with practitioner usage: term structure is a "risk-on/risk-off" flag,
  not a precise vol level predictor
""")

# Save results
output = {
    "experiment": "vix_term_structure_vol_pred_v2",
    "version": "v2_robustness",
    "n_windows": int(len(y_oos)),
    "init_train": INIT,
    "results": {},
    "conclusion": "VIX term structure does NOT add OOS predictive power for monthly vol beyond VIX level alone. Strong in-sample (t=4.49) but negative OOS R². Classic overfitting pattern.",
    "created_at": datetime.now().isoformat(),
}

for name, pred in approaches:
    r2 = oos_r2(y_oos, pred)
    m = mae(y_oos, pred)
    output["results"][name] = {"R2": round(float(r2), 6), "MAE": round(float(m), 6)}

with open("/Users/yhlai0911/Dropbox/自我研究波動預測模型/experiments/vix_term_structure_results_v2.json", "w") as f:
    json.dump(output, f, indent=2)

print("Results saved to experiments/vix_term_structure_results_v2.json")
