"""
K181: CBOE SKEW Index as Volatility Predictor
===============================================
The IV surface curvature contains tail-risk info beyond VIX level.
CBOE SKEW measures tail risk expectations from OTM put pricing.
VIX sufficiency confirmed 23 times — does SKEW break this?

Methodology:
  1. Download SKEW index (^SKEW via yfinance)
  2. Correlation: SKEW vs next-day/week/month realized vol
  3. Partial correlation: SKEW → future RV | controlling for VIX
  4. GARCH-X: Add SKEW as exogenous regressor, compare QLIKE
  5. SKEW regime: High (>130, tail fear) vs Low (<120) realized vol diff
  6. VT overlay: Use SKEW to adjust VT exposure
  7. DM test + Harvey threshold

Data: SPY, QQQ + ^VIX + ^SKEW, 2005-2025
OOS: 2023-01-01 to 2024-12-31

Key checks:
  - SKEW is known ex-ante (traded options, no look-ahead)
  - If partial r|VIX is NS → VIX sufficient #24
  - If SKEW adds alpha → first crack in VIX sufficiency

[提出: Gemini R8#2, 執行: Claude]
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

np.random.seed(42)

results = {
    "experiment": "K181",
    "title": "CBOE SKEW Index as Volatility Predictor",
    "proposed_by": "Gemini R8#2",
    "executed_by": "Claude",
    "timestamp": datetime.now().isoformat(),
    "sections": {}
}

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K181: CBOE SKEW Index as Volatility Predictor")
print("=" * 70)

print("\n[1/7] Downloading data...")

tickers = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "VIX": "^VIX",
    "SKEW": "^SKEW",
}

raw_data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2005-01-01", end="2025-03-01", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    raw_data[name] = df[close_col].copy()
    raw_data[name].name = name
    print(f"  {name}: {len(df)} obs ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")

# Align on common dates
common_idx = raw_data["SPY"].dropna().index
for name in ["QQQ", "VIX", "SKEW"]:
    common_idx = common_idx.intersection(raw_data[name].dropna().index)

print(f"  Common dates: {len(common_idx)} ({common_idx[0].strftime('%Y-%m-%d')} to {common_idx[-1].strftime('%Y-%m-%d')})")

spy_close = raw_data["SPY"].loc[common_idx]
qqq_close = raw_data["QQQ"].loc[common_idx]
vix = raw_data["VIX"].loc[common_idx]
skew = raw_data["SKEW"].loc[common_idx]

spy_ret = spy_close.pct_change().dropna()
qqq_ret = qqq_close.pct_change().dropna()

# Align everything after pct_change dropna
common_idx2 = spy_ret.index.intersection(qqq_ret.index).intersection(vix.index).intersection(skew.index)
spy_ret = spy_ret.loc[common_idx2]
qqq_ret = qqq_ret.loc[common_idx2]
vix = vix.loc[common_idx2]
skew = skew.loc[common_idx2]

print(f"  Final aligned: {len(spy_ret)} obs")
print(f"  SKEW range: {skew.min():.1f} to {skew.max():.1f}, mean={skew.mean():.1f}, std={skew.std():.1f}")
print(f"  VIX range: {vix.min():.1f} to {vix.max():.1f}")

results["sections"]["data"] = {
    "n_obs": len(spy_ret),
    "date_range": f"{common_idx2[0].strftime('%Y-%m-%d')} to {common_idx2[-1].strftime('%Y-%m-%d')}",
    "skew_stats": {
        "min": float(skew.min()),
        "max": float(skew.max()),
        "mean": float(skew.mean()),
        "std": float(skew.std()),
        "median": float(skew.median()),
    },
    "vix_stats": {
        "min": float(vix.min()),
        "max": float(vix.max()),
        "mean": float(vix.mean()),
    }
}

# ============================================================
# 2. Realized Vol Computation (multiple horizons)
# ============================================================
print("\n[2/7] Computing realized volatility at multiple horizons...")

horizons = {"1d": 1, "5d": 5, "22d": 22, "66d": 66}
rv = {}
for label, h in horizons.items():
    if h == 1:
        rv[label] = spy_ret.abs()  # |r_t| as proxy for daily vol
    else:
        rv[label] = spy_ret.rolling(h).std() * np.sqrt(252)
    rv[label] = rv[label].shift(-h)  # future RV
    rv[label].name = f"RV_{label}"
    valid = rv[label].dropna()
    print(f"  RV_{label}: {len(valid)} obs, mean={valid.mean():.4f}")

# ============================================================
# 3. Raw Correlation: SKEW vs future RV
# ============================================================
print("\n[3/7] Correlation analysis: SKEW vs future realized vol...")

corr_results = {}
for label in horizons:
    valid_mask = rv[label].notna()
    s = skew[valid_mask]
    r = rv[label][valid_mask]
    v = vix[valid_mask]

    # SKEW vs future RV
    rho_skew, p_skew = stats.pearsonr(s, r)
    rho_skew_sp, p_skew_sp = stats.spearmanr(s, r)

    # VIX vs future RV (benchmark)
    rho_vix, p_vix = stats.pearsonr(v, r)

    corr_results[label] = {
        "skew_pearson_r": float(rho_skew),
        "skew_pearson_p": float(p_skew),
        "skew_spearman_r": float(rho_skew_sp),
        "skew_spearman_p": float(p_skew_sp),
        "vix_pearson_r": float(rho_vix),
        "vix_pearson_p": float(p_vix),
        "n": int(valid_mask.sum()),
    }

    sig_skew = "***" if p_skew < 0.001 else "**" if p_skew < 0.01 else "*" if p_skew < 0.05 else "NS"
    sig_vix = "***" if p_vix < 0.001 else "**" if p_vix < 0.01 else "*" if p_vix < 0.05 else "NS"

    print(f"  RV_{label}: SKEW r={rho_skew:+.4f} (p={p_skew:.4f}) {sig_skew} | "
          f"VIX r={rho_vix:+.4f} (p={p_vix:.4f}) {sig_vix}")

results["sections"]["raw_correlation"] = corr_results

# ============================================================
# 4. Partial Correlation: SKEW → RV | VIX
# ============================================================
print("\n[4/7] Partial correlation: SKEW → future RV | controlling for VIX...")

def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    # Residualize x on z
    from numpy.linalg import lstsq
    Z = np.column_stack([z, np.ones(len(z))])

    beta_x, _, _, _ = lstsq(Z, x, rcond=None)
    resid_x = x - Z @ beta_x

    beta_y, _, _, _ = lstsq(Z, y, rcond=None)
    resid_y = y - Z @ beta_y

    r, p = stats.pearsonr(resid_x, resid_y)
    return r, p

partial_results = {}
for label in horizons:
    valid_mask = rv[label].notna()
    s = skew[valid_mask].values
    r = rv[label][valid_mask].values
    v = vix[valid_mask].values

    # Partial corr: SKEW → RV | VIX
    pr, pp = partial_corr(s, r, v)

    # Also: SKEW → RV | VIX + VIX²  (nonlinear VIX control)
    v_quad = np.column_stack([v, v**2])
    Z = np.column_stack([v_quad, np.ones(len(v))])
    beta_x, _, _, _ = np.linalg.lstsq(Z, s, rcond=None)
    resid_x = s - Z @ beta_x
    beta_y, _, _, _ = np.linalg.lstsq(Z, r, rcond=None)
    resid_y = r - Z @ beta_y
    pr_quad, pp_quad = stats.pearsonr(resid_x, resid_y)

    partial_results[label] = {
        "partial_r_linear": float(pr),
        "partial_p_linear": float(pp),
        "partial_r_quadratic": float(pr_quad),
        "partial_p_quadratic": float(pp_quad),
    }

    sig_lin = "***" if pp < 0.001 else "**" if pp < 0.01 else "*" if pp < 0.05 else "NS"
    sig_quad = "***" if pp_quad < 0.001 else "**" if pp_quad < 0.01 else "*" if pp_quad < 0.05 else "NS"

    print(f"  RV_{label}: partial r|VIX = {pr:+.4f} (p={pp:.4f}) {sig_lin} | "
          f"partial r|VIX+VIX² = {pr_quad:+.4f} (p={pp_quad:.4f}) {sig_quad}")

results["sections"]["partial_correlation"] = partial_results

# ============================================================
# 5. GARCH-X: SKEW as exogenous variable
# ============================================================
print("\n[5/7] GARCH-X models: adding SKEW as exogenous regressor...")

oos_start = pd.Timestamp("2023-01-01")
oos_end = pd.Timestamp("2024-12-31")

# Scale returns for arch
ret_scaled = spy_ret * 100  # percent returns

# In-sample: everything before OOS
is_mask = ret_scaled.index < oos_start
oos_mask = (ret_scaled.index >= oos_start) & (ret_scaled.index <= oos_end)

is_ret = ret_scaled[is_mask]
oos_ret = ret_scaled[oos_mask]
oos_dates = oos_ret.index

print(f"  In-sample: {len(is_ret)} obs, OOS: {len(oos_ret)} obs ({oos_start.strftime('%Y-%m-%d')} to {oos_end.strftime('%Y-%m-%d')})")

# Prepare SKEW as exogenous variable (standardized using IS stats)
is_skew_mask = skew.index.isin(is_ret.index)
skew_is_mean = skew[is_skew_mask].mean()
skew_is_std = skew[is_skew_mask].std()
skew_std = (skew - skew_is_mean) / skew_is_std

# Two approaches:
# A) GJR-GARCH baseline + forecast encompassing (does SKEW add info to GJR forecast?)
# B) OLS: r²_{t+1} = a + b*GJR_forecast + c*SKEW_t  (expanding window)

print("\n  Fitting GJR-GARCH baseline (expanding window, every 5th day for speed)...")
garch_forecasts = {}
actual_rv = {}
skew_at_forecast = {}

window_min = 1500  # minimum in-sample
n_oos = len(oos_dates)

for i in range(n_oos):
    train_end = oos_dates[i]
    train_ret = ret_scaled[ret_scaled.index < train_end]

    if len(train_ret) < window_min:
        continue

    actual_rv[oos_dates[i]] = float(oos_ret.iloc[i] ** 2)

    # Record SKEW value at forecast time (known ex-ante)
    if train_end in skew.index:
        skew_at_forecast[oos_dates[i]] = float(skew.loc[train_end])
    else:
        prior = skew.index[skew.index <= train_end]
        skew_at_forecast[oos_dates[i]] = float(skew.loc[prior[-1]]) if len(prior) > 0 else np.nan

    # Only re-estimate every 5th day (expanding window, otherwise reuse last)
    if i % 5 == 0:
        try:
            am = arch_model(train_ret, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Zero')
            res = am.fit(disp='off', show_warning=False)
            fcast = res.forecast(horizon=1)
            last_gjr_forecast = float(fcast.variance.iloc[-1, 0])
        except Exception:
            last_gjr_forecast = np.nan

    garch_forecasts[oos_dates[i]] = last_gjr_forecast

    if (i + 1) % 100 == 0:
        print(f"    {i+1}/{n_oos} done...")

n_valid_gjr = sum(1 for v in garch_forecasts.values() if not np.isnan(v))
print(f"  GJR forecasts: {n_valid_gjr}/{n_oos}")

# Forecast encompassing test: r²_{t+1} = a + b1*GJR_t + b2*SKEW_t + eps
# If b2 is significant, SKEW adds info beyond GJR
print("\n  Forecast encompassing test (OOS)...")
common_dates_fc = sorted(set(garch_forecasts.keys()) & set(actual_rv.keys()) & set(skew_at_forecast.keys()))
a_arr = np.array([actual_rv[d] for d in common_dates_fc])
g_arr = np.array([garch_forecasts[d] for d in common_dates_fc])
s_arr = np.array([skew_at_forecast[d] for d in common_dates_fc])

valid_fc = ~(np.isnan(a_arr) | np.isnan(g_arr) | np.isnan(s_arr) | (g_arr <= 0))
a_v = a_arr[valid_fc]
g_v = g_arr[valid_fc]
s_v = s_arr[valid_fc]

# OLS: actual = a + b1*GJR + b2*SKEW
from numpy.linalg import lstsq as np_lstsq
X_fc = np.column_stack([g_v, s_v, np.ones(len(g_v))])
beta_fc, _, _, _ = np_lstsq(X_fc, a_v, rcond=None)
resid_fc = a_v - X_fc @ beta_fc
se_fc = np.sqrt(np.diag(np.var(resid_fc, ddof=3) * np.linalg.inv(X_fc.T @ X_fc)))
t_gjr = beta_fc[0] / se_fc[0]
t_skew = beta_fc[1] / se_fc[1]
p_gjr = 2 * (1 - stats.norm.cdf(abs(t_gjr)))
p_skew = 2 * (1 - stats.norm.cdf(abs(t_skew)))

print(f"    r²_{{t+1}} = {beta_fc[2]:.4f} + {beta_fc[0]:.4f}*GJR + {beta_fc[1]:.6f}*SKEW")
print(f"    GJR coef:  {beta_fc[0]:.4f} (t={t_gjr:.3f}, p={p_gjr:.4f})")
print(f"    SKEW coef: {beta_fc[1]:.6f} (t={t_skew:.3f}, p={p_skew:.4f})")

# Also: GJR-only model for R² comparison
X_gjr_only = np.column_stack([g_v, np.ones(len(g_v))])
beta_go, _, _, _ = np_lstsq(X_gjr_only, a_v, rcond=None)
resid_go = a_v - X_gjr_only @ beta_go
r2_gjr = 1 - np.var(resid_go) / np.var(a_v)
r2_combined = 1 - np.var(resid_fc) / np.var(a_v)

print(f"    R²(GJR only): {r2_gjr:.4f}")
print(f"    R²(GJR+SKEW): {r2_combined:.4f}")
print(f"    Incremental R²: {r2_combined - r2_gjr:.6f}")

# QLIKE comparison: GJR vs GJR+SKEW adjusted
# Adjusted forecast = GJR + beta2*(SKEW - mean_SKEW)
garch_adj_forecasts = g_v + beta_fc[1] * (s_v - s_v.mean())
garch_adj_forecasts = np.maximum(garch_adj_forecasts, 0.01)  # floor

# Compute QLIKE
def qlike(actual, forecast):
    """QLIKE loss: mean(log(forecast) + actual/forecast)"""
    valid = ~(np.isnan(actual) | np.isnan(forecast) | (forecast <= 0))
    a = actual[valid]
    f = forecast[valid]
    return np.mean(np.log(f) + a / f), int(valid.sum())

# QLIKE: GJR vs GJR+SKEW adjusted
q_gjr, n_gjr = qlike(a_v, g_v)
q_gjrx, n_gjrx = qlike(a_v, garch_adj_forecasts)

print(f"\n  QLIKE (lower=better):")
print(f"    GJR-GARCH:             {q_gjr:.6f} (n={n_gjr})")
print(f"    GJR+SKEW adjusted:     {q_gjrx:.6f} (n={n_gjrx})")
print(f"    Difference:            {q_gjrx - q_gjr:+.6f} ({'SKEW helps' if q_gjrx < q_gjr else 'SKEW no help'})")

# DM test on QLIKE losses
loss_gjr = np.log(g_v) + a_v / g_v
loss_gjrx = np.log(garch_adj_forecasts) + a_v / garch_adj_forecasts

d = loss_gjr - loss_gjrx  # positive = SKEW-adjusted model better
dm_stat = np.mean(d) / (np.std(d, ddof=1) / np.sqrt(len(d)))
dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

sig = "***" if dm_p < 0.001 else "**" if dm_p < 0.01 else "*" if dm_p < 0.05 else "NS"
print(f"\n  DM test (GJR vs GJR+SKEW):")
print(f"    t-stat = {dm_stat:+.4f}, p = {dm_p:.4f} {sig}")
print(f"    Harvey threshold: |t| > 3.0 → {'PASS' if abs(dm_stat) > 3.0 else 'FAIL'}")

results["sections"]["garch_x"] = {
    "encompassing_test": {
        "gjr_coef": float(beta_fc[0]),
        "gjr_t": float(t_gjr),
        "gjr_p": float(p_gjr),
        "skew_coef": float(beta_fc[1]),
        "skew_t": float(t_skew),
        "skew_p": float(p_skew),
        "r2_gjr_only": float(r2_gjr),
        "r2_gjr_skew": float(r2_combined),
        "incremental_r2": float(r2_combined - r2_gjr),
    },
    "qlike_gjr": float(q_gjr),
    "qlike_gjr_skew": float(q_gjrx),
    "qlike_diff": float(q_gjrx - q_gjr),
    "dm_stat": float(dm_stat),
    "dm_p": float(dm_p),
    "harvey_pass": bool(abs(dm_stat) > 3.0),
    "n_forecasts": int(len(a_v)),
    "conclusion": "SKEW improves GARCH" if (q_gjrx < q_gjr and dm_p < 0.05) else "SKEW does NOT improve GARCH"
}

# ============================================================
# 6. SKEW Regime Analysis
# ============================================================
print("\n[6/7] SKEW regime analysis...")

# Define regimes
regime_thresholds = {
    "Low SKEW (<120)": skew < 120,
    "Mid SKEW (120-130)": (skew >= 120) & (skew < 130),
    "High SKEW (>130)": skew >= 130,
    "Very High SKEW (>140)": skew >= 140,
}

regime_results = {}
for regime_name, mask in regime_thresholds.items():
    n_days = mask.sum()
    if n_days < 30:
        print(f"  {regime_name}: only {n_days} days, skipping")
        regime_results[regime_name] = {"n_days": int(n_days), "skipped": True}
        continue

    # Future 1d |return|
    future_1d = spy_ret.shift(-1).loc[mask].dropna()
    future_abs = future_1d.abs()

    # Future 22d realized vol
    rv_22d = spy_ret.rolling(22).std() * np.sqrt(252)
    rv_22d_shifted = rv_22d.shift(-22)
    future_22d = rv_22d_shifted.loc[mask].dropna()

    # VIX level in this regime
    vix_in_regime = vix.loc[mask]

    regime_results[regime_name] = {
        "n_days": int(n_days),
        "pct_of_total": float(n_days / len(skew) * 100),
        "mean_abs_1d_ret": float(future_abs.mean()),
        "mean_future_22d_rv": float(future_22d.mean()) if len(future_22d) > 0 else None,
        "mean_vix": float(vix_in_regime.mean()),
        "mean_skew": float(skew.loc[mask].mean()),
        "mean_spy_ret": float(future_1d.mean()),
    }

    print(f"  {regime_name}: {n_days} days ({n_days/len(skew)*100:.1f}%)")
    print(f"    Mean |ret_1d|: {future_abs.mean():.4f}, Mean VIX: {vix_in_regime.mean():.1f}")
    if len(future_22d) > 0:
        print(f"    Mean future 22d RV: {future_22d.mean():.4f}")

# Cross-regime comparison: High vs Low SKEW
high_mask = skew >= 130
low_mask = skew < 120

high_abs_ret = spy_ret.shift(-1).loc[high_mask].dropna().abs()
low_abs_ret = spy_ret.shift(-1).loc[low_mask].dropna().abs()

t_regime, p_regime = stats.ttest_ind(high_abs_ret, low_abs_ret)
print(f"\n  High (>130) vs Low (<120) SKEW — mean |ret|:")
print(f"    High: {high_abs_ret.mean():.5f} (n={len(high_abs_ret)})")
print(f"    Low:  {low_abs_ret.mean():.5f} (n={len(low_abs_ret)})")
print(f"    t-stat = {t_regime:.3f}, p = {p_regime:.4f}")

# But controlling for VIX level
high_vix = vix.loc[high_mask].dropna()
low_vix = vix.loc[low_mask].dropna()
print(f"    ⚠ Mean VIX in High SKEW: {high_vix.mean():.1f}, in Low SKEW: {low_vix.mean():.1f}")

regime_results["high_vs_low_test"] = {
    "high_mean_abs_ret": float(high_abs_ret.mean()),
    "low_mean_abs_ret": float(low_abs_ret.mean()),
    "t_stat": float(t_regime),
    "p_value": float(p_regime),
    "high_mean_vix": float(high_vix.mean()),
    "low_mean_vix": float(low_vix.mean()),
    "vix_confound_warning": abs(high_vix.mean() - low_vix.mean()) > 2,
}

results["sections"]["regime_analysis"] = regime_results

# ============================================================
# 7. VT Overlay: SKEW-adjusted allocation
# ============================================================
print("\n[7/7] VT overlay: SKEW-adjusted VT strategy...")

# Baseline: 12/VIX with lagged weights (VIX_t → w_{t+1})
# SKEW overlay: reduce equity when SKEW > threshold

def compute_vt_strategy(ret, vix_series, skew_series=None, skew_threshold=None,
                        skew_reduction=0.0, name="Baseline"):
    """
    Compute VT strategy returns.
    - Base weight = 12/VIX (lagged)
    - If skew_series and skew_threshold provided: reduce weight by skew_reduction when SKEW > threshold
    """
    w_base = 12.0 / vix_series
    w_base = w_base.clip(0, 1.5)  # cap at 150%

    if skew_series is not None and skew_threshold is not None:
        skew_adj = np.where(skew_series > skew_threshold, 1.0 - skew_reduction, 1.0)
        w = w_base * skew_adj
    else:
        w = w_base

    w = w.clip(0, 1.5)

    # Lagged weights: w_t determines exposure on t+1
    w_lagged = w.shift(1)

    # Strategy return: w * equity_ret + (1-w) * rf (assume rf ≈ 0 for simplicity)
    strat_ret = w_lagged * ret
    strat_ret = strat_ret.dropna()

    return strat_ret, w_lagged

# OOS period
oos_mask = (spy_ret.index >= oos_start) & (spy_ret.index <= oos_end)
spy_oos = spy_ret[oos_mask]
vix_oos = vix[oos_mask]
skew_oos = skew[oos_mask]

# Baseline 12/VIX
ret_base, w_base = compute_vt_strategy(spy_oos, vix_oos, name="12/VIX")

# SKEW overlays with different thresholds and reductions
overlays = [
    (125, 0.20, "SKEW>125: -20%"),
    (130, 0.20, "SKEW>130: -20%"),
    (130, 0.30, "SKEW>130: -30%"),
    (135, 0.25, "SKEW>135: -25%"),
    (140, 0.30, "SKEW>140: -30%"),
]

print(f"\n  OOS period: {oos_start.strftime('%Y-%m-%d')} to {oos_end.strftime('%Y-%m-%d')}")
print(f"  {'Strategy':<25} {'Sharpe':>8} {'Ann.Ret%':>9} {'Ann.Vol%':>9} {'MDD%':>8} {'Turnover':>9}")
print(f"  {'-'*70}")

def strategy_metrics(returns, name):
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = drawdown.min()

    return {
        "name": name,
        "sharpe": float(sharpe),
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "mdd": float(mdd),
        "n_days": int(len(returns)),
    }

# Buy & Hold SPY
bh_metrics = strategy_metrics(spy_oos, "Buy & Hold SPY")
print(f"  {'Buy & Hold SPY':<25} {bh_metrics['sharpe']:>8.3f} {bh_metrics['ann_ret']*100:>8.2f}% {bh_metrics['ann_vol']*100:>8.2f}% {bh_metrics['mdd']*100:>7.2f}%")

# 12/VIX baseline
base_metrics = strategy_metrics(ret_base, "12/VIX Baseline")
print(f"  {'12/VIX Baseline':<25} {base_metrics['sharpe']:>8.3f} {base_metrics['ann_ret']*100:>8.2f}% {base_metrics['ann_vol']*100:>8.2f}% {base_metrics['mdd']*100:>7.2f}%")

vt_results = {"buy_hold": bh_metrics, "baseline_12vix": base_metrics, "overlays": []}

for thresh, reduction, label in overlays:
    ret_ov, w_ov = compute_vt_strategy(spy_oos, vix_oos, skew_oos, thresh, reduction, label)
    ov_metrics = strategy_metrics(ret_ov, label)

    # Count days SKEW triggered
    triggered = (skew_oos > thresh).sum()
    ov_metrics["triggered_days"] = int(triggered)
    ov_metrics["triggered_pct"] = float(triggered / len(skew_oos) * 100)

    vt_results["overlays"].append(ov_metrics)

    print(f"  {label:<25} {ov_metrics['sharpe']:>8.3f} {ov_metrics['ann_ret']*100:>8.2f}% "
          f"{ov_metrics['ann_vol']*100:>8.2f}% {ov_metrics['mdd']*100:>7.2f}%  "
          f"({triggered} days, {triggered/len(skew_oos)*100:.1f}%)")

# Statistical test: best overlay vs baseline
best_overlay = max(vt_results["overlays"], key=lambda x: x["sharpe"])
best_label = best_overlay["name"]

# Find the best overlay returns for DM test
for thresh, reduction, label in overlays:
    if label == best_label:
        ret_best_ov, _ = compute_vt_strategy(spy_oos, vix_oos, skew_oos, thresh, reduction, label)
        break

# Paired t-test on returns
common_idx_vt = ret_base.index.intersection(ret_best_ov.index)
r1 = ret_base.loc[common_idx_vt].values
r2 = ret_best_ov.loc[common_idx_vt].values
t_vt, p_vt = stats.ttest_rel(r2, r1)

print(f"\n  Best overlay ({best_label}) vs 12/VIX baseline:")
print(f"    Sharpe diff: {best_overlay['sharpe'] - base_metrics['sharpe']:+.3f}")
print(f"    Paired t-test: t={t_vt:.3f}, p={p_vt:.4f}")
print(f"    Harvey threshold: {'PASS' if abs(t_vt) > 3.0 else 'FAIL'}")

vt_results["best_overlay_test"] = {
    "best_overlay": best_label,
    "sharpe_diff": float(best_overlay["sharpe"] - base_metrics["sharpe"]),
    "t_stat": float(t_vt),
    "p_value": float(p_vt),
    "harvey_pass": bool(abs(t_vt) > 3.0),
}

results["sections"]["vt_overlay"] = vt_results

# ============================================================
# 8. Multi-asset check (QQQ)
# ============================================================
print("\n[Bonus] Multi-asset: QQQ SKEW correlation check...")

qqq_rv_22d = qqq_ret.rolling(22).std() * np.sqrt(252)
qqq_rv_22d_future = qqq_rv_22d.shift(-22)

valid_mask_qqq = qqq_rv_22d_future.notna()
s_qqq = skew[valid_mask_qqq].values
r_qqq = qqq_rv_22d_future[valid_mask_qqq].values
v_qqq = vix[valid_mask_qqq].values

rho_raw_qqq, p_raw_qqq = stats.pearsonr(s_qqq, r_qqq)
pr_qqq, pp_qqq = partial_corr(s_qqq, r_qqq, v_qqq)

sig_raw = "***" if p_raw_qqq < 0.001 else "**" if p_raw_qqq < 0.01 else "*" if p_raw_qqq < 0.05 else "NS"
sig_part = "***" if pp_qqq < 0.001 else "**" if pp_qqq < 0.01 else "*" if pp_qqq < 0.05 else "NS"

print(f"  QQQ 22d RV: raw r(SKEW)={rho_raw_qqq:+.4f} {sig_raw}, partial r|VIX={pr_qqq:+.4f} {sig_part}")

results["sections"]["multi_asset_qqq"] = {
    "raw_r": float(rho_raw_qqq),
    "raw_p": float(p_raw_qqq),
    "partial_r_vix": float(pr_qqq),
    "partial_p_vix": float(pp_qqq),
}

# ============================================================
# 9. SKEW-VIX interaction (does SKEW matter MORE when VIX is elevated?)
# ============================================================
print("\n[Bonus] SKEW-VIX interaction analysis...")

# Split by VIX regime
vix_low = vix < 15
vix_mid = (vix >= 15) & (vix < 25)
vix_high = vix >= 25

rv_22d_future_all = spy_ret.rolling(22).std().shift(-22) * np.sqrt(252)

interaction_results = {}
for regime_name, regime_mask in [("VIX<15", vix_low), ("VIX 15-25", vix_mid), ("VIX>25", vix_high)]:
    valid = regime_mask & rv_22d_future_all.notna()
    n = valid.sum()
    if n < 50:
        interaction_results[regime_name] = {"n": int(n), "skipped": True}
        continue

    s = skew[valid].values
    r = rv_22d_future_all[valid].values

    rho, p = stats.pearsonr(s, r)
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else "NS"

    interaction_results[regime_name] = {
        "n": int(n),
        "skew_rv_corr": float(rho),
        "p_value": float(p),
    }
    print(f"  {regime_name}: r(SKEW, future RV) = {rho:+.4f} (p={p:.4f}) {sig} (n={n})")

results["sections"]["skew_vix_interaction"] = interaction_results

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY — K181: CBOE SKEW Index as Volatility Predictor")
print("=" * 70)

# Determine overall conclusion
partial_sig_count = sum(1 for label in horizons
                        if partial_results[label]["partial_p_linear"] < 0.05)
garch_helps = results["sections"].get("garch_x", {}).get("conclusion", "").startswith("SKEW improves")
vt_harvey = results["sections"].get("vt_overlay", {}).get("best_overlay_test", {}).get("harvey_pass", False)

print(f"\n1. Raw correlation (SKEW → future RV):")
for label in horizons:
    cr = corr_results[label]
    print(f"   {label}: r={cr['skew_pearson_r']:+.4f} (p={cr['skew_pearson_p']:.4f})")

print(f"\n2. Partial correlation (SKEW → RV | VIX):")
for label in horizons:
    pr = partial_results[label]
    print(f"   {label}: r={pr['partial_r_linear']:+.4f} (p={pr['partial_p_linear']:.4f})")
print(f"   Significant at p<0.05: {partial_sig_count}/{len(horizons)} horizons")

print(f"\n3. Forecast encompassing + QLIKE:")
gx = results["sections"].get("garch_x", {})
if "encompassing_test" in gx:
    et = gx["encompassing_test"]
    print(f"   SKEW coef in encompassing: {et['skew_coef']:.6f} (t={et['skew_t']:.3f}, p={et['skew_p']:.4f})")
    print(f"   Incremental R²: {et['incremental_r2']:.6f}")
if "qlike_diff" in gx:
    print(f"   QLIKE diff: {gx['qlike_diff']:+.6f} ({'SKEW helps' if gx['qlike_diff'] < 0 else 'SKEW no help'})")
    print(f"   DM test: t={gx['dm_stat']:+.4f}, p={gx['dm_p']:.4f}")

print(f"\n4. VT SKEW overlay:")
vt = results["sections"].get("vt_overlay", {})
if "best_overlay_test" in vt:
    bot = vt["best_overlay_test"]
    print(f"   Best overlay: {bot['best_overlay']}, Sharpe diff: {bot['sharpe_diff']:+.3f}")
    print(f"   Paired t: t={bot['t_stat']:.3f}, p={bot['p_value']:.4f}")
    print(f"   Harvey: {'PASS' if bot['harvey_pass'] else 'FAIL'}")

# Overall verdict
if partial_sig_count == 0 and not garch_helps and not vt_harvey:
    verdict = "VIX sufficient #24 — SKEW adds no incremental predictive power"
    vix_sufficient_count = 24
elif partial_sig_count > 0 and garch_helps:
    verdict = "SKEW cracks VIX sufficiency — significant incremental info found"
    vix_sufficient_count = "cracked"
else:
    verdict = f"Mixed results — partial corr sig in {partial_sig_count}/{len(horizons)} horizons, GARCH-X {'helps' if garch_helps else 'no help'}, VT overlay Harvey {'PASS' if vt_harvey else 'FAIL'}"
    vix_sufficient_count = "ambiguous"

print(f"\n★ VERDICT: {verdict}")

results["verdict"] = verdict
results["vix_sufficient_count"] = vix_sufficient_count

# Save results
output_path = "experiments/k181_skew_predictor_results.json"
with open(output_path, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("=" * 70)
