#!/usr/bin/env python3
"""
K877: Gold-Silver Ratio as Equity Volatility Predictor

Research Question: Does the gold/silver ratio add predictive power for SPY
realized volatility beyond VIX?

Gold/Silver ratio rises during risk-off (gold is safer haven than silver).
Historical range: ~40 (risk-on) to 120+ (extreme crisis, 126 in March 2020).
This captures a DIFFERENT dimension of risk than VIX (precious metals market stress).

Methodology:
  1. Gold-Silver ratio = GLD / SLV (ETF-based, liquid, investable)
  2. Ratio variables: level, 22d change, z-score (rolling 252d)
  3. Target: forward 22-day SPY realized volatility (annualized sqrt of mean r²)
  4. Models (all with shift(1) lag):
     a. VIX only (baseline)
     b. VIX + GS_ratio
     c. VIX + GS_ratio_change
     d. GS_ratio only (no VIX)
  5. OOS: IS 2006-2018, OOS 2019-2026
  6. Evaluation: QLIKE + DM test (Harvey |t|>3.0) + Spearman rank correlation

Data source: yfinance (GLD, SLV, SPY, ^VIX), 2006-01 to 2026-04.
Error log rules: DM test uses dm_test from volpred.stats.model_evaluation (not custom).
Signal lag: all predictors use shift(1) — today's prediction uses yesterday's info.

References:
  - Baur & Lucey (2010) "Is gold a hedge or a safe haven?" Finance Research Letters
  - Patton (2011) "Volatility forecast comparison using imperfect volatility proxies"
    J. Econometrics 160
  - Harvey et al. (2016) "...and the Cross-Section of Expected Returns" RFS — t>3.0
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from sklearn.linear_model import LinearRegression

warnings.filterwarnings("ignore")

# ─── Import standard DM test (error log rule: don't write your own) ───
try:
    from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr
except ImportError:
    # Fallback: inline implementations matching the module
    def qlike(actual, predicted):
        a = np.asarray(actual, dtype=np.float64)
        f = np.asarray(predicted, dtype=np.float64)
        valid = (a > 0) & (f > 0) & np.isfinite(a) & np.isfinite(f)
        if valid.sum() < 10:
            return np.nan
        a, f = a[valid], f[valid]
        ratio = a / f
        return float(np.mean(ratio - np.log(ratio) - 1))

    def qlike_pointwise(actual, predicted):
        a = np.maximum(np.asarray(actual, dtype=np.float64), 1e-16)
        f = np.maximum(np.asarray(predicted, dtype=np.float64), 1e-16)
        ratio = a / f
        return ratio - np.log(ratio) - 1

    def dm_test(loss1, loss2, h=1):
        d = np.asarray(loss1, dtype=np.float64) - np.asarray(loss2, dtype=np.float64)
        valid = np.isfinite(d)
        d = d[valid]
        n = len(d)
        if n < 10:
            return (0.0, 1.0)
        d_mean = np.mean(d)
        max_lag = max(1, min(int(np.ceil(h ** (1/3) * n ** (1/3))), n // 4))
        gamma0 = np.mean((d - d_mean) ** 2)
        var_d = gamma0
        for lag in range(1, max_lag + 1):
            weight = 1 - lag / (max_lag + 1)
            gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
            var_d += 2 * weight * gamma_l
        if var_d <= 0:
            return (0.0, 1.0)
        se = np.sqrt(var_d / n)
        if se < 1e-15:
            return (0.0, 1.0)
        t_stat = d_mean / se
        p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
        return (float(t_stat), float(p_val))

    def spearman_corr(actual, predicted):
        valid = np.isfinite(actual) & np.isfinite(predicted)
        if valid.sum() < 10:
            return (np.nan, np.nan)
        rho, p = stats.spearmanr(actual[valid], predicted[valid])
        return (float(rho), float(p))


# ─── 1. Data Download ────────────────────────────────────────────
print("=" * 70)
print("K877: Gold-Silver Ratio as Equity Volatility Predictor")
print("=" * 70)

tickers = ["GLD", "SLV", "SPY", "^VIX"]
data = {}
for t in tickers:
    print(f"  Downloading {t}...")
    df = yf.download(t, start="2005-11-01", end="2026-04-06", progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    clean_name = t.replace("^", "")
    data[clean_name] = df["Close"]

prices = pd.DataFrame(data).dropna()
print(f"  Combined data: {prices.index[0].date()} to {prices.index[-1].date()}, N={len(prices)}")

# ─── 2. Construct Variables ──────────────────────────────────────
df = pd.DataFrame(index=prices.index)

# Gold-Silver ratio
df["gs_ratio"] = prices["GLD"] / prices["SLV"]
df["gs_ratio_change"] = df["gs_ratio"].pct_change(22)  # 22-day change
df["gs_ratio_zscore"] = (
    (df["gs_ratio"] - df["gs_ratio"].rolling(252).mean())
    / df["gs_ratio"].rolling(252).std()
)

# VIX
df["vix"] = prices["VIX"]

# SPY returns
df["spy_ret"] = prices["SPY"].pct_change()

# Forward 22-day realized vol (annualized) — TARGET
# RV_t = sqrt(252 * mean(r²_{t+1:t+22}))
df["fwd_rv22"] = (
    df["spy_ret"] ** 2
).rolling(22).mean().shift(-22).apply(lambda x: np.sqrt(252 * x) if pd.notna(x) else np.nan)

# Also compute squared target for QLIKE (variance, not vol)
df["fwd_var22"] = (
    df["spy_ret"] ** 2
).rolling(22).mean().shift(-22) * 252  # annualized variance

df = df.dropna()
print(f"  After dropping NaN: {df.index[0].date()} to {df.index[-1].date()}, N={len(df)}")

# ─── 3. Descriptive Statistics ───────────────────────────────────
print("\n--- Descriptive Statistics ---")
desc_vars = ["gs_ratio", "gs_ratio_change", "gs_ratio_zscore", "vix", "fwd_rv22"]
desc = df[desc_vars].describe().T
desc["skew"] = df[desc_vars].skew()
desc["kurt"] = df[desc_vars].kurtosis()
print(desc[["mean", "std", "min", "max", "skew", "kurt"]].round(4))

# Correlations
print("\n--- Correlations with forward 22d RV ---")
for v in ["gs_ratio", "gs_ratio_change", "gs_ratio_zscore", "vix"]:
    r = df[v].corr(df["fwd_rv22"])
    print(f"  {v:25s}: Pearson r = {r:.4f}")

# Spearman correlations
print("\n--- Spearman Rank Correlations with forward 22d RV ---")
for v in ["gs_ratio", "gs_ratio_change", "gs_ratio_zscore", "vix"]:
    rho, p = spearman_corr(df[v].values, df["fwd_rv22"].values)
    print(f"  {v:25s}: Spearman ρ = {rho:.4f} (p={p:.4e})")


# ─── 4. Rolling OOS Regression Models ───────────────────────────
# IS: before 2019-01-01, OOS: 2019-01-01 onwards
# Expanding window: retrain every 63 days (quarterly)
IS_END = "2018-12-31"
OOS_START = "2019-01-01"

is_mask = df.index <= IS_END
oos_mask = df.index >= OOS_START

print(f"\n  IS: {df[is_mask].index[0].date()} to {df[is_mask].index[-1].date()}, N={is_mask.sum()}")
print(f"  OOS: {df[oos_mask].index[0].date()} to {df[oos_mask].index[-1].date()}, N={oos_mask.sum()}")

# Define models — predictors for each
# All use shift(1) for lag: today's prediction uses yesterday's data
models = {
    "VIX_only": ["vix"],
    "VIX_GS_ratio": ["vix", "gs_ratio"],
    "VIX_GS_change": ["vix", "gs_ratio_change"],
    "VIX_GS_zscore": ["vix", "gs_ratio_zscore"],
    "GS_ratio_only": ["gs_ratio"],
    "GS_change_only": ["gs_ratio_change"],
    "GS_zscore_only": ["gs_ratio_zscore"],
}

# Prepare lagged predictors — shift(1) enforced in code
df_lagged = pd.DataFrame(index=df.index)
for col in ["vix", "gs_ratio", "gs_ratio_change", "gs_ratio_zscore"]:
    df_lagged[col] = df[col].shift(1)  # ← signal.shift(1) as required
df_lagged["target_var"] = df["fwd_var22"]  # annualized variance (for QLIKE)
df_lagged["target_rv"] = df["fwd_rv22"]    # annualized vol
df_lagged = df_lagged.dropna()

# Re-align masks
is_mask_l = df_lagged.index <= IS_END
oos_mask_l = df_lagged.index >= OOS_START

oos_dates = df_lagged.index[oos_mask_l]
n_oos = len(oos_dates)
print(f"  OOS dates after lag alignment: N={n_oos}")

# Rolling expanding window predictions
REFIT_EVERY = 63  # quarterly refit
predictions = {name: np.full(n_oos, np.nan) for name in models}

print("\n--- Running OOS Predictions (expanding window, quarterly refit) ---")
for model_name, features in models.items():
    last_coefs = None
    for i, date in enumerate(oos_dates):
        # Get training data: all data up to this date
        train_mask = df_lagged.index < date
        X_train = df_lagged.loc[train_mask, features].values
        y_train = df_lagged.loc[train_mask, "target_var"].values

        # Refit every REFIT_EVERY days or at start
        if i % REFIT_EVERY == 0 or last_coefs is None:
            valid = np.all(np.isfinite(X_train), axis=1) & np.isfinite(y_train)
            if valid.sum() < 50:
                continue
            reg = LinearRegression()
            reg.fit(X_train[valid], y_train[valid])
            last_coefs = (reg.coef_, reg.intercept_)

        # Predict
        x_today = df_lagged.loc[date, features].values.reshape(1, -1)
        if np.all(np.isfinite(x_today)):
            pred = last_coefs[0] @ x_today.T + last_coefs[1]
            predictions[model_name][i] = max(pred[0], 1e-6)  # floor at small positive

    valid_preds = np.sum(np.isfinite(predictions[model_name]))
    print(f"  {model_name:25s}: {valid_preds}/{n_oos} valid OOS predictions")


# ─── 5. Evaluation ──────────────────────────────────────────────
print("\n" + "=" * 70)
print("OOS Evaluation (2019-2026)")
print("=" * 70)

actual_var = df_lagged.loc[oos_dates, "target_var"].values
actual_rv = df_lagged.loc[oos_dates, "target_rv"].values

results = {}

# 5a. QLIKE and Spearman for each model
print("\n--- Model Performance ---")
print(f"{'Model':25s} {'QLIKE':>10s} {'MSE_var':>10s} {'Spearman_ρ':>12s} {'Sp_p':>10s} {'R²_OOS':>10s}")
print("-" * 80)

for model_name in models:
    pred = predictions[model_name]
    valid = np.isfinite(pred) & np.isfinite(actual_var) & (pred > 0) & (actual_var > 0)

    if valid.sum() < 50:
        print(f"  {model_name:25s}: insufficient valid predictions")
        continue

    a = actual_var[valid]
    p_vals = pred[valid]

    ql = qlike(a, p_vals)
    mse_val = np.mean((a - p_vals) ** 2)
    sp_rho, sp_p = spearman_corr(a, p_vals)

    # OOS R²
    ss_res = np.sum((a - p_vals) ** 2)
    ss_tot = np.sum((a - np.mean(a)) ** 2)
    r2_oos = 1 - ss_res / ss_tot

    results[model_name] = {
        "qlike": ql,
        "mse": mse_val,
        "spearman_rho": sp_rho,
        "spearman_p": sp_p,
        "r2_oos": r2_oos,
        "n_valid": int(valid.sum()),
    }

    print(f"{model_name:25s} {ql:10.4f} {mse_val:10.6f} {sp_rho:12.4f} {sp_p:10.2e} {r2_oos:10.4f}")

# 5b. DM Tests (Harvey |t| > 3.0 threshold)
print("\n--- DM Tests (QLIKE loss, vs VIX_only baseline) ---")
print(f"{'Comparison':35s} {'DM_t':>8s} {'p':>10s} {'Harvey':>8s}")
print("-" * 65)

baseline_name = "VIX_only"
baseline_pred = predictions[baseline_name]

dm_results = {}
for model_name in models:
    if model_name == baseline_name:
        continue

    pred = predictions[model_name]
    valid = (np.isfinite(baseline_pred) & np.isfinite(pred)
             & np.isfinite(actual_var) & (baseline_pred > 0) & (pred > 0) & (actual_var > 0))

    if valid.sum() < 50:
        continue

    a = actual_var[valid]
    loss_base = qlike_pointwise(a, baseline_pred[valid])
    loss_model = qlike_pointwise(a, pred[valid])

    # DM test: negative t → model 1 (baseline) better
    # We pass (loss_base, loss_model): negative t → baseline has lower loss → baseline better
    t_stat, p_val = dm_test(loss_base, loss_model, h=22)

    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else "NS"))
    direction = "MODEL" if t_stat > 0 else "BASELINE"

    label = f"VIX_only vs {model_name}"
    dm_results[model_name] = {
        "dm_t": t_stat,
        "dm_p": p_val,
        "significant_harvey": abs(t_stat) > 3.0,
        "better": direction,
    }

    print(f"{label:35s} {t_stat:8.3f} {p_val:10.4e} {sig:>8s} ({direction})")


# 5c. In-sample analysis: partial correlations
print("\n--- In-Sample Partial Correlation Analysis ---")
# Does GS ratio add info beyond VIX?
is_data = df_lagged[is_mask_l].dropna()
from numpy.linalg import lstsq

# Partial corr: GS_ratio with fwd_var after controlling for VIX
# Residualize both on VIX
X_vix = is_data["vix"].values.reshape(-1, 1)
y_gs = is_data["gs_ratio"].values
y_rv = is_data["target_var"].values

# Residuals of GS_ratio ~ VIX
coef_gs, _, _, _ = lstsq(np.c_[X_vix, np.ones(len(X_vix))], y_gs, rcond=None)
resid_gs = y_gs - (X_vix @ coef_gs[:1].reshape(-1, 1) + coef_gs[1]).ravel()

# Residuals of fwd_var ~ VIX
coef_rv, _, _, _ = lstsq(np.c_[X_vix, np.ones(len(X_vix))], y_rv, rcond=None)
resid_rv = y_rv - (X_vix @ coef_rv[:1].reshape(-1, 1) + coef_rv[1]).ravel()

partial_r = np.corrcoef(resid_gs, resid_rv)[0, 1]
n_is = len(is_data)
t_partial = partial_r * np.sqrt((n_is - 3) / (1 - partial_r**2))

print(f"  Partial corr (GS_ratio | VIX) with fwd_var: r = {partial_r:.4f}, t = {t_partial:.3f}")

# Same for GS_ratio_change
y_gsc = is_data["gs_ratio_change"].values
coef_gsc, _, _, _ = lstsq(np.c_[X_vix, np.ones(len(X_vix))], y_gsc, rcond=None)
resid_gsc = y_gsc - (X_vix @ coef_gsc[:1].reshape(-1, 1) + coef_gsc[1]).ravel()
partial_r_change = np.corrcoef(resid_gsc, resid_rv)[0, 1]
t_partial_change = partial_r_change * np.sqrt((n_is - 3) / (1 - partial_r_change**2))
print(f"  Partial corr (GS_change | VIX) with fwd_var: r = {partial_r_change:.4f}, t = {t_partial_change:.3f}")

# Same for GS_ratio_zscore
y_gsz = is_data["gs_ratio_zscore"].values
coef_gsz, _, _, _ = lstsq(np.c_[X_vix, np.ones(len(X_vix))], y_gsz, rcond=None)
resid_gsz = y_gsz - (X_vix @ coef_gsz[:1].reshape(-1, 1) + coef_gsz[1]).ravel()
partial_r_zscore = np.corrcoef(resid_gsz, resid_rv)[0, 1]
t_partial_zscore = partial_r_zscore * np.sqrt((n_is - 3) / (1 - partial_r_zscore**2))
print(f"  Partial corr (GS_zscore | VIX) with fwd_var: r = {partial_r_zscore:.4f}, t = {t_partial_zscore:.3f}")


# 5d. Regime analysis: does GS ratio help more in certain VIX regimes?
print("\n--- Regime Analysis: GS Ratio Predictive Power by VIX Regime ---")
oos_data = df_lagged[oos_mask_l].copy()
oos_data["vix_regime"] = pd.cut(
    oos_data["vix"],
    bins=[0, 15, 20, 30, 100],
    labels=["Low(<15)", "Normal(15-20)", "Elevated(20-30)", "High(>30)"]
)

for regime in ["Low(<15)", "Normal(15-20)", "Elevated(20-30)", "High(>30)"]:
    mask_regime = oos_data["vix_regime"] == regime
    idx_regime = oos_data.index[mask_regime]
    n_r = len(idx_regime)
    if n_r < 30:
        print(f"  {regime}: N={n_r} (too few)")
        continue

    # Get OOS indices
    oos_idx = np.array([np.where(oos_dates == d)[0][0] for d in idx_regime if d in oos_dates])
    if len(oos_idx) < 30:
        continue

    a_regime = actual_var[oos_idx]
    p_vix = predictions["VIX_only"][oos_idx]
    p_vix_gs = predictions["VIX_GS_ratio"][oos_idx]

    valid = np.isfinite(p_vix) & np.isfinite(p_vix_gs) & np.isfinite(a_regime) & (p_vix > 0) & (p_vix_gs > 0) & (a_regime > 0)
    if valid.sum() < 20:
        print(f"  {regime}: insufficient valid predictions")
        continue

    ql_vix = qlike(a_regime[valid], p_vix[valid])
    ql_gs = qlike(a_regime[valid], p_vix_gs[valid])
    improvement = (ql_vix - ql_gs) / ql_vix * 100

    print(f"  {regime:20s}: N={valid.sum():4d}, QLIKE_VIX={ql_vix:.4f}, QLIKE_VIX+GS={ql_gs:.4f}, Δ={improvement:+.2f}%")


# 5e. Time-varying GS ratio behavior
print("\n--- Gold-Silver Ratio Summary Statistics by Period ---")
for period, (start, end) in {
    "2006-2010 (GFC)": ("2006-01-01", "2010-12-31"),
    "2011-2015 (Recovery)": ("2011-01-01", "2015-12-31"),
    "2016-2019 (Pre-COVID)": ("2016-01-01", "2019-12-31"),
    "2020-2023 (COVID+)": ("2020-01-01", "2023-12-31"),
    "2024-2026 (Recent)": ("2024-01-01", "2026-12-31"),
}.items():
    mask_p = (df.index >= start) & (df.index <= end)
    if mask_p.sum() > 0:
        gs = df.loc[mask_p, "gs_ratio"]
        r = df.loc[mask_p, "gs_ratio"].corr(df.loc[mask_p, "fwd_rv22"])
        print(f"  {period:30s}: GS mean={gs.mean():.1f}, std={gs.std():.1f}, range=[{gs.min():.1f}, {gs.max():.1f}], corr_w_rv={r:.3f}")


# ─── 6. Save Results ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("CONCLUSION")
print("=" * 70)

# Determine if any model beats VIX baseline at Harvey threshold
any_significant = any(
    dm_results.get(m, {}).get("significant_harvey", False)
    and dm_results[m]["better"] == "MODEL"
    for m in dm_results
)

best_augmented = min(
    [(name, results[name]["qlike"]) for name in results if name != baseline_name and name in results],
    key=lambda x: x[1],
    default=(None, None)
)

baseline_qlike = results.get(baseline_name, {}).get("qlike", np.nan)
if best_augmented[0]:
    best_name, best_ql = best_augmented
    improvement = (baseline_qlike - best_ql) / baseline_qlike * 100
    print(f"  Best augmented model: {best_name} (QLIKE={best_ql:.4f} vs baseline {baseline_qlike:.4f}, Δ={improvement:+.2f}%)")
else:
    print("  No valid augmented model found.")

if any_significant:
    print("  ★ At least one model significantly beats VIX baseline (Harvey |t|>3.0)")
else:
    print("  ✗ No model significantly beats VIX baseline at Harvey |t|>3.0 threshold")
    print("  → Gold-Silver ratio does NOT add statistically significant predictive power beyond VIX")

# Compile full results
output = {
    "experiment_id": "K877",
    "title": "Gold-Silver Ratio as Equity Volatility Predictor",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "data_source": "yfinance (GLD, SLV, SPY, ^VIX)",
    "data_period": f"{df.index[0].date()} to {df.index[-1].date()}",
    "n_total": len(df),
    "n_is": int(is_mask_l.sum()),
    "n_oos": n_oos,
    "oos_period": f"{oos_dates[0].date()} to {oos_dates[-1].date()}",
    "methodology": {
        "target": "forward 22-day annualized variance",
        "lag": "shift(1) on all predictors",
        "estimation": "expanding window OLS, quarterly refit",
        "evaluation": "QLIKE (Patton 2011) + DM test (Harvey t>3.0) + Spearman",
    },
    "descriptive": {
        "gs_ratio": {
            "mean": float(df["gs_ratio"].mean()),
            "std": float(df["gs_ratio"].std()),
            "min": float(df["gs_ratio"].min()),
            "max": float(df["gs_ratio"].max()),
            "corr_with_fwd_rv": float(df["gs_ratio"].corr(df["fwd_rv22"])),
        },
        "vix_gs_correlation": float(df["vix"].corr(df["gs_ratio"])),
    },
    "in_sample_partial_correlations": {
        "gs_ratio_given_vix": {"partial_r": partial_r, "t_stat": t_partial},
        "gs_change_given_vix": {"partial_r": partial_r_change, "t_stat": t_partial_change},
        "gs_zscore_given_vix": {"partial_r": partial_r_zscore, "t_stat": t_partial_zscore},
    },
    "oos_results": results,
    "dm_tests_vs_vix_baseline": dm_results,
    "conclusion": {
        "vix_sufficient": not any_significant,
        "any_model_beats_vix_harvey": any_significant,
        "best_augmented_model": best_augmented[0] if best_augmented[0] else "none",
        "summary": (
            "Gold-Silver ratio does NOT add statistically significant predictive power "
            "beyond VIX for SPY forward realized volatility."
            if not any_significant else
            f"Gold-Silver ratio ({best_augmented[0]}) significantly improves on VIX baseline."
        ),
    },
    "references": [
        "Baur & Lucey (2010) 'Is gold a hedge or a safe haven?' Finance Research Letters",
        "Patton (2011) J. Econometrics 160 — proxy-robust loss functions",
        "Harvey et al. (2016) RFS — multiple testing threshold t>3.0",
    ],
}

# Save
out_path = Path(__file__).parent / "k877_results.json"
with open(out_path, "w") as f:
    json.dump(output, f, indent=2, default=str)
print(f"\n  Results saved to {out_path}")
print("  Done.")
