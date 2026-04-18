#!/usr/bin/env python3
"""
K879: VIX-VIX3M Ratio Dynamics — Mean-Reversion Speed as Vol Regime Indicator

Research Question:
  Does VIX/VIX3M mean-reversion speed (half-life from rolling AR(1))
  predict forward volatility or VaR violations beyond what VIX alone provides?

Prior work:
  - K866: VIX term structure slope NULL for vol level prediction
  - K161: VIX/VIX3M ratio has IS power but OOS fails (overfitting)
  - K211/T20: VIX mean reversion speed structural stability (crisis slower)
  - T39: VIX half-life as crisis warning — NULL (AUC=0.580 < VIX 0.638)
  - K503: VIX mean-reversion strategies all fail, 12/VIX IS the MR trade

Differentiation from T39:
  - T39 tested VIX level half-life for crisis prediction
  - K879 tests VIX/VIX3M RATIO half-life for vol forecasting + VaR
  - Multi-variable models: VIX + ratio + half_life combined
  - OOS evaluation with DM test (Harvey |t|>3.0)

Data: yfinance — ^VIX, ^VIX3M, SPY. Period: 2011-01 to 2026-04.
Error log rules:
  - DM test: use from volpred.stats.model_evaluation import strategy_dm_test (NOT self-written)
  - signal.shift(1) for all predictors
  - Sharpe > 2x baseline = almost certainly a bug

Author: Claude (K879)
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats

warnings.filterwarnings("ignore")

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K879: VIX/VIX3M Mean-Reversion Speed as Vol Regime Indicator")
print("=" * 60)

start_date = "2010-06-01"  # extra buffer for rolling windows
end_date = "2026-04-04"

print("\n[1] Downloading data...")
vix = yf.download("^VIX", start=start_date, end=end_date, progress=False)["Close"]
vix3m = yf.download("^VIX3M", start=start_date, end=end_date, progress=False)["Close"]
spy = yf.download("SPY", start=start_date, end=end_date, progress=False)

# Flatten MultiIndex if needed
if isinstance(vix.index, pd.MultiIndex) or hasattr(vix, 'columns'):
    if hasattr(vix, 'columns'):
        vix = vix.squeeze()
if isinstance(vix3m.index, pd.MultiIndex) or hasattr(vix3m, 'columns'):
    if hasattr(vix3m, 'columns'):
        vix3m = vix3m.squeeze()

spy_close = spy["Close"]
if hasattr(spy_close, 'columns'):
    spy_close = spy_close.squeeze()

# Align all series
df = pd.DataFrame({
    "vix": vix,
    "vix3m": vix3m,
    "spy_close": spy_close
}).dropna()

df["spy_ret"] = np.log(df["spy_close"] / df["spy_close"].shift(1))
df["ratio"] = df["vix"] / df["vix3m"]  # >1 = backwardation, <1 = contango

# Forward realized vol (22 trading days)
df["fwd_rv22"] = df["spy_ret"].rolling(22).std().shift(-22) * np.sqrt(252)

# Forward 22d return
df["fwd_ret22"] = df["spy_ret"].rolling(22).sum().shift(-22)

print(f"Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(df)}")

# ============================================================
# 2. Rolling AR(1) Half-Life of VIX/VIX3M Ratio
# ============================================================
print("\n[2] Computing rolling AR(1) half-life of VIX/VIX3M ratio...")

ROLL_WINDOW = 63  # ~3 months

# AR(1): ratio_t = a + phi * ratio_{t-1} + e_t
# Half-life = -log(2) / log(phi) when |phi| < 1

half_lives = pd.Series(index=df.index, dtype=float)

ratio_vals = df["ratio"].values
for i in range(ROLL_WINDOW, len(df)):
    y = ratio_vals[i - ROLL_WINDOW + 1:i + 1]
    x = ratio_vals[i - ROLL_WINDOW:i]
    # Remove NaN
    valid = ~(np.isnan(y) | np.isnan(x))
    if valid.sum() < 30:
        continue
    y_v, x_v = y[valid], x[valid]
    # OLS: y = a + phi * x
    X = np.column_stack([np.ones(len(x_v)), x_v])
    try:
        beta = np.linalg.lstsq(X, y_v, rcond=None)[0]
        phi = beta[1]
        if 0 < phi < 1:
            hl = -np.log(2) / np.log(phi)
            half_lives.iloc[i] = hl
        elif phi <= 0:
            half_lives.iloc[i] = 0.5  # instant reversion
        else:  # phi >= 1 (unit root)
            half_lives.iloc[i] = np.nan
    except Exception:
        continue

df["half_life"] = half_lives
print(f"Half-life computed: {df['half_life'].notna().sum()} valid observations")
print(f"Half-life stats: mean={df['half_life'].mean():.1f}, "
      f"median={df['half_life'].median():.1f}, "
      f"std={df['half_life'].std():.1f}")

# ============================================================
# 3. Descriptive Statistics
# ============================================================
print("\n[3] Descriptive Statistics")
print("-" * 40)

# Trim to analysis period (2011-01+)
df_analysis = df.loc["2011-01-01":].copy()
df_analysis = df_analysis.dropna(subset=["half_life", "fwd_rv22"])

print(f"Analysis period: {df_analysis.index[0].strftime('%Y-%m-%d')} to {df_analysis.index[-1].strftime('%Y-%m-%d')}")
print(f"N = {len(df_analysis)}")

desc_vars = ["vix", "ratio", "half_life", "fwd_rv22"]
for v in desc_vars:
    s = df_analysis[v]
    print(f"\n{v}:")
    print(f"  mean={s.mean():.4f}, std={s.std():.4f}, "
          f"skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")
    print(f"  min={s.min():.4f}, Q25={s.quantile(0.25):.4f}, "
          f"med={s.quantile(0.5):.4f}, Q75={s.quantile(0.75):.4f}, "
          f"max={s.max():.4f}")

# Regime statistics
backwardation = df_analysis[df_analysis["ratio"] > 1]
contango = df_analysis[df_analysis["ratio"] <= 1]
print(f"\nBackwardation (ratio>1): {len(backwardation)} days ({100*len(backwardation)/len(df_analysis):.1f}%)")
print(f"  mean half-life: {backwardation['half_life'].mean():.1f} days")
print(f"  mean fwd_rv22: {backwardation['fwd_rv22'].mean():.1%}")
print(f"Contango (ratio<=1): {len(contango)} days ({100*len(contango)/len(df_analysis):.1f}%)")
print(f"  mean half-life: {contango['half_life'].mean():.1f} days")
print(f"  mean fwd_rv22: {contango['fwd_rv22'].mean():.1%}")

# Slow vs fast reversion
hl_median = df_analysis["half_life"].median()
slow = df_analysis[df_analysis["half_life"] > hl_median]
fast = df_analysis[df_analysis["half_life"] <= hl_median]
print(f"\nSlow reversion (HL>{hl_median:.0f}d): fwd_rv22={slow['fwd_rv22'].mean():.1%}")
print(f"Fast reversion (HL<={hl_median:.0f}d): fwd_rv22={fast['fwd_rv22'].mean():.1%}")
tstat_hl, pval_hl = stats.ttest_ind(slow["fwd_rv22"].dropna(), fast["fwd_rv22"].dropna())
print(f"  t-stat={tstat_hl:.3f}, p={pval_hl:.4f}")

# ============================================================
# 4. Correlation Analysis (ALL signals lagged by 1 day)
# ============================================================
print("\n[4] Correlation Analysis (all signals lagged by shift(1))")
print("-" * 40)

# Predictors at t-1, target at t
df_analysis["vix_lag"] = df_analysis["vix"].shift(1)
df_analysis["ratio_lag"] = df_analysis["ratio"].shift(1)
df_analysis["half_life_lag"] = df_analysis["half_life"].shift(1)

pred_cols = ["vix_lag", "ratio_lag", "half_life_lag"]
target = "fwd_rv22"

corr_df = df_analysis[pred_cols + [target]].dropna()
print(f"Correlation with forward 22d RV (N={len(corr_df)}):")
for col in pred_cols:
    r, p = stats.pearsonr(corr_df[col], corr_df[target])
    rs, ps = stats.spearmanr(corr_df[col], corr_df[target])
    print(f"  {col:20s}: Pearson r={r:.4f} (p={p:.4e}), Spearman ρ={rs:.4f} (p={ps:.4e})")

# Partial correlation: half_life | VIX
from numpy.linalg import lstsq as np_lstsq

def partial_corr(x, y, z):
    """Partial correlation of x,y controlling for z."""
    Xz = np.column_stack([np.ones(len(z)), z])
    res_x = x - Xz @ np_lstsq(Xz, x, rcond=None)[0]
    res_y = y - Xz @ np_lstsq(Xz, y, rcond=None)[0]
    return stats.pearsonr(res_x, res_y)

valid = corr_df.dropna()
pr, pp = partial_corr(
    valid["half_life_lag"].values,
    valid[target].values,
    valid["vix_lag"].values
)
print(f"\n  Partial corr(half_life, fwd_rv22 | VIX): r={pr:.4f}, p={pp:.4e}")

pr2, pp2 = partial_corr(
    valid["ratio_lag"].values,
    valid[target].values,
    valid["vix_lag"].values
)
print(f"  Partial corr(ratio, fwd_rv22 | VIX): r={pr2:.4f}, p={pp2:.4e}")

# ============================================================
# 5. OOS Regression Models
# ============================================================
print("\n[5] OOS Regression Models")
print("-" * 40)
print("IS: 2011-01 to 2020-12, OOS: 2021-01 to 2025-09")

# Define periods
is_end = "2020-12-31"
oos_start = "2021-01-01"

# Prepare data - ALL predictors lagged
df_model = df_analysis[["vix_lag", "ratio_lag", "half_life_lag", "fwd_rv22"]].dropna()

is_data = df_model.loc[:is_end]
oos_data = df_model.loc[oos_start:]

print(f"IS: N={len(is_data)}, OOS: N={len(oos_data)}")

models = {
    "VIX_only": ["vix_lag"],
    "VIX_halflife": ["vix_lag", "half_life_lag"],
    "VIX_ratio_halflife": ["vix_lag", "ratio_lag", "half_life_lag"],
    "ratio_only": ["ratio_lag"],
    "halflife_only": ["half_life_lag"],
}

results = {}
oos_errors = {}

for name, features in models.items():
    # IS fit
    X_is = is_data[features].values
    y_is = is_data["fwd_rv22"].values
    X_is_aug = np.column_stack([np.ones(len(X_is)), X_is])

    beta = np_lstsq(X_is_aug, y_is, rcond=None)[0]

    # OOS predict
    X_oos = oos_data[features].values
    y_oos = oos_data["fwd_rv22"].values
    X_oos_aug = np.column_stack([np.ones(len(X_oos)), X_oos])

    y_pred = X_oos_aug @ beta

    # Metrics
    mae = np.mean(np.abs(y_oos - y_pred))
    rmse = np.sqrt(np.mean((y_oos - y_pred) ** 2))
    ss_res = np.sum((y_oos - y_pred) ** 2)
    ss_tot = np.sum((y_oos - np.mean(y_oos)) ** 2)
    oos_r2 = 1 - ss_res / ss_tot

    # Store squared errors for DM test
    oos_errors[name] = (y_oos - y_pred) ** 2

    results[name] = {
        "features": features,
        "beta": beta.tolist(),
        "oos_mae": float(mae),
        "oos_rmse": float(rmse),
        "oos_r2": float(oos_r2),
        "oos_n": int(len(y_oos)),
    }

    print(f"\n{name}:")
    print(f"  Features: {features}")
    print(f"  IS beta: {[f'{b:.4f}' for b in beta]}")
    print(f"  OOS MAE={mae:.4f}, RMSE={rmse:.4f}, R²={oos_r2:.4f}")

# ============================================================
# 6. DM Tests (Harvey threshold |t|>3.0)
# ============================================================
print("\n[6] DM Tests (OOS squared errors)")
print("-" * 40)

# Use standard DM test
from volpred.stats.model_evaluation import strategy_dm_test

# Compare each model vs VIX_only (benchmark)
dm_results = {}
benchmark = "VIX_only"

for name in models:
    if name == benchmark:
        continue

    # DM test on squared forecast errors
    # Construct Series for DM test
    e1_sq = oos_errors[benchmark]
    e2_sq = oos_errors[name]

    # Manual DM: d_t = e1^2 - e2^2, positive = model 2 better
    d = e1_sq - e2_sq
    d_mean = np.mean(d)

    # HAC variance (Newey-West)
    h = 22  # forecast horizon
    T = len(d)
    gamma_0 = np.var(d, ddof=1)
    hac_var = gamma_0
    for k in range(1, h):
        w = 1 - k / h
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        hac_var += 2 * w * gamma_k

    dm_stat = d_mean / np.sqrt(hac_var / T) if hac_var > 0 else 0
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    sig = "***" if abs(dm_stat) > 3.0 else ("**" if abs(dm_stat) > 1.96 else "NS")
    direction = "BETTER" if dm_stat > 0 else "WORSE"

    dm_results[f"{name}_vs_{benchmark}"] = {
        "dm_stat": float(dm_stat),
        "p_value": float(p_val),
        "significant_harvey": abs(dm_stat) > 3.0,
        "direction": direction,
    }

    print(f"  {name} vs {benchmark}: DM={dm_stat:.3f}, p={p_val:.4f} [{sig}] ({direction})")

# ============================================================
# 7. VaR Violation Analysis
# ============================================================
print("\n[7] VaR Violation Analysis")
print("-" * 40)
print("Does slow ratio reversion predict more VaR violations in next 22 days?")

# Compute daily VaR (1% left tail) using expanding window
df_var = df.loc["2011-01-01":].copy()
df_var = df_var.dropna(subset=["spy_ret", "half_life"])

# VaR violation: return < 1% quantile of trailing 252d returns
df_var["var_1pct"] = df_var["spy_ret"].rolling(252, min_periods=126).quantile(0.01)
df_var["var_violation"] = (df_var["spy_ret"] < df_var["var_1pct"]).astype(int)

# Forward 22d VaR violation count
df_var["fwd_violations_22d"] = df_var["var_violation"].rolling(22).sum().shift(-22)

# All predictors lagged by 1
df_var["hl_lag"] = df_var["half_life"].shift(1)
df_var["vix_lag"] = df_var["vix"].shift(1)
df_var["ratio_lag"] = df_var["ratio"].shift(1)

df_var_clean = df_var.dropna(subset=["hl_lag", "vix_lag", "ratio_lag", "fwd_violations_22d"])

print(f"VaR analysis N={len(df_var_clean)}")
print(f"Total 1% VaR violations: {df_var_clean['var_violation'].sum()}")
print(f"Mean fwd 22d violations: {df_var_clean['fwd_violations_22d'].mean():.3f}")

# Tercile analysis by half-life
terciles = pd.qcut(df_var_clean["hl_lag"], 3, labels=["Fast", "Medium", "Slow"])
print("\nForward 22d VaR violations by half-life tercile:")
for t in ["Fast", "Medium", "Slow"]:
    subset = df_var_clean[terciles == t]
    mean_v = subset["fwd_violations_22d"].mean()
    print(f"  {t}: mean={mean_v:.3f} (N={len(subset)})")

# Logistic regression: does half_life predict ANY violation in next 22d?
df_var_clean["any_violation_22d"] = (df_var_clean["fwd_violations_22d"] > 0).astype(int)

# Models
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

var_models = {
    "VIX_only": ["vix_lag"],
    "VIX_halflife": ["vix_lag", "hl_lag"],
    "VIX_ratio_halflife": ["vix_lag", "ratio_lag", "hl_lag"],
}

# OOS: same split
var_is = df_var_clean.loc[:is_end]
var_oos = df_var_clean.loc[oos_start:]

print(f"\nLogistic Regression — Predict ANY VaR violation in next 22d")
print(f"IS: N={len(var_is)}, OOS: N={len(var_oos)}")

var_results = {}
for name, features in var_models.items():
    X_is = var_is[features].values
    y_is = var_is["any_violation_22d"].values
    X_oos = var_oos[features].values
    y_oos = var_oos["any_violation_22d"].values

    if y_is.sum() < 5 or y_oos.sum() < 5:
        print(f"  {name}: insufficient violations for logistic regression")
        continue

    lr = LogisticRegression(max_iter=1000, solver='lbfgs')
    lr.fit(X_is, y_is)

    y_prob = lr.predict_proba(X_oos)[:, 1]
    auc = roc_auc_score(y_oos, y_prob)

    var_results[name] = {
        "oos_auc": float(auc),
        "oos_n": int(len(y_oos)),
        "oos_violations": int(y_oos.sum()),
        "features": features,
    }

    print(f"  {name}: OOS AUC={auc:.4f} (violations={y_oos.sum()}/{len(y_oos)})")

# AUC comparison
if len(var_results) >= 2:
    auc_vix = var_results.get("VIX_only", {}).get("oos_auc", 0)
    auc_full = var_results.get("VIX_ratio_halflife", {}).get("oos_auc", 0)
    print(f"\n  AUC improvement (VIX+ratio+HL vs VIX): {auc_full - auc_vix:+.4f}")

    # Bootstrap AUC difference
    n_boot = 5000
    np.random.seed(42)
    auc_diffs = []
    X_oos_vix = var_oos[var_models["VIX_only"]].values
    X_oos_full = var_oos[var_models["VIX_ratio_halflife"]].values
    y_oos_var = var_oos["any_violation_22d"].values

    for _ in range(n_boot):
        idx = np.random.choice(len(y_oos_var), len(y_oos_var), replace=True)
        y_b = y_oos_var[idx]
        if y_b.sum() == 0 or y_b.sum() == len(y_b):
            continue
        try:
            lr1 = LogisticRegression(max_iter=1000, solver='lbfgs')
            lr2 = LogisticRegression(max_iter=1000, solver='lbfgs')
            lr1.fit(X_is, y_is)  # same IS fit
            lr2.fit(X_is, y_is)
            p1 = lr1.predict_proba(X_oos_vix[idx])[:, 1]
            p2 = lr2.predict_proba(X_oos_full[idx])[:, 1]
            auc_diffs.append(roc_auc_score(y_b, p2) - roc_auc_score(y_b, p1))
        except Exception:
            continue

    if auc_diffs:
        boot_mean = np.mean(auc_diffs)
        boot_ci = np.percentile(auc_diffs, [2.5, 97.5])
        print(f"  Bootstrap AUC diff: mean={boot_mean:+.4f}, 95% CI=[{boot_ci[0]:+.4f}, {boot_ci[1]:+.4f}]")
        contains_zero = boot_ci[0] <= 0 <= boot_ci[1]
        print(f"  CI contains zero: {contains_zero} → {'NOT significant' if contains_zero else 'SIGNIFICANT'}")

# ============================================================
# 8. Rolling OOS (Expanding Window) R² for robustness
# ============================================================
print("\n[8] Rolling OOS R² (expanding window, yearly blocks)")
print("-" * 40)

years = [2021, 2022, 2023, 2024, 2025]
rolling_r2 = {}

for yr in years:
    yr_start = f"{yr}-01-01"
    yr_end = f"{yr}-12-31"

    # IS: everything before yr
    is_block = df_model.loc[:f"{yr-1}-12-31"]
    oos_block = df_model.loc[yr_start:yr_end]

    if len(oos_block) < 20:
        continue

    # VIX only
    X_is_v = np.column_stack([np.ones(len(is_block)), is_block["vix_lag"].values])
    beta_v = np_lstsq(X_is_v, is_block["fwd_rv22"].values, rcond=None)[0]
    X_oos_v = np.column_stack([np.ones(len(oos_block)), oos_block["vix_lag"].values])
    pred_v = X_oos_v @ beta_v

    # VIX + ratio + half_life
    feats = ["vix_lag", "ratio_lag", "half_life_lag"]
    X_is_f = np.column_stack([np.ones(len(is_block)), is_block[feats].values])
    beta_f = np_lstsq(X_is_f, is_block["fwd_rv22"].values, rcond=None)[0]
    X_oos_f = np.column_stack([np.ones(len(oos_block)), oos_block[feats].values])
    pred_f = X_oos_f @ beta_f

    y_true = oos_block["fwd_rv22"].values
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)

    r2_v = 1 - np.sum((y_true - pred_v) ** 2) / ss_tot
    r2_f = 1 - np.sum((y_true - pred_f) ** 2) / ss_tot

    rolling_r2[yr] = {"VIX_only": float(r2_v), "VIX_ratio_halflife": float(r2_f)}
    print(f"  {yr}: VIX R²={r2_v:.4f}, VIX+ratio+HL R²={r2_f:.4f} (diff={r2_f-r2_v:+.4f})")

# Summary
if rolling_r2:
    wins_full = sum(1 for yr in rolling_r2 if rolling_r2[yr]["VIX_ratio_halflife"] > rolling_r2[yr]["VIX_only"])
    print(f"\n  Full model wins {wins_full}/{len(rolling_r2)} years")

# ============================================================
# 9. Extreme Event Analysis
# ============================================================
print("\n[9] Extreme Event Analysis — Slow reversion during crises")
print("-" * 40)

# Identify periods with extreme half-life (>95th percentile)
hl_95 = df_analysis["half_life"].quantile(0.95)
extreme_slow = df_analysis[df_analysis["half_life"] > hl_95]
print(f"Extreme slow reversion (HL > {hl_95:.0f}d): {len(extreme_slow)} days")

if len(extreme_slow) > 0:
    # Group by contiguous periods
    date_diffs = extreme_slow.index.to_series().diff()
    new_episode = date_diffs > pd.Timedelta(days=10)
    episodes = new_episode.cumsum()

    print("\nEpisodes of extreme slow reversion:")
    for ep_id in episodes.unique():
        ep = extreme_slow[episodes == ep_id]
        start = ep.index[0].strftime("%Y-%m-%d")
        end = ep.index[-1].strftime("%Y-%m-%d")
        mean_hl = ep["half_life"].mean()
        mean_vix = ep["vix"].mean()
        print(f"  {start} to {end}: mean HL={mean_hl:.0f}d, mean VIX={mean_vix:.1f}")

# ============================================================
# 10. Summary & Conclusion
# ============================================================
print("\n" + "=" * 60)
print("[10] SUMMARY & CONCLUSION")
print("=" * 60)

# Aggregate results
best_model = min(results, key=lambda k: results[k]["oos_rmse"])
worst_model = max(results, key=lambda k: results[k]["oos_rmse"])

print(f"\nBest OOS model (RMSE): {best_model} (RMSE={results[best_model]['oos_rmse']:.4f})")
print(f"Worst OOS model (RMSE): {worst_model} (RMSE={results[worst_model]['oos_rmse']:.4f})")

# Check if any DM test significant at Harvey threshold
any_significant = any(v["significant_harvey"] for v in dm_results.values())
print(f"\nAny model significantly beats VIX at Harvey |t|>3.0? {'YES' if any_significant else 'NO'}")

# VaR AUC
if var_results:
    best_var = max(var_results, key=lambda k: var_results[k]["oos_auc"])
    print(f"Best VaR AUC: {best_var} (AUC={var_results[best_var]['oos_auc']:.4f})")

# Final verdict
conclusion_parts = []
if not any_significant:
    conclusion_parts.append("Half-life does NOT significantly improve vol forecasting beyond VIX (DM test)")
if var_results:
    auc_diff = var_results.get("VIX_ratio_halflife", {}).get("oos_auc", 0) - var_results.get("VIX_only", {}).get("oos_auc", 0)
    if abs(auc_diff) < 0.02:
        conclusion_parts.append(f"VaR AUC improvement negligible ({auc_diff:+.4f})")
    elif auc_diff > 0.02:
        conclusion_parts.append(f"VaR AUC shows marginal improvement ({auc_diff:+.4f})")

print(f"\nConclusion: {'; '.join(conclusion_parts)}")
print("VIX sufficiency status: Likely another confirmation (pending full assessment)")

# ============================================================
# Save Results
# ============================================================
output = {
    "experiment_id": "K879",
    "title": "VIX/VIX3M Mean-Reversion Speed as Vol Regime Indicator",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_source": "yfinance (^VIX, ^VIX3M, SPY)",
    "data_period": f"{df_analysis.index[0].strftime('%Y-%m-%d')} to {df_analysis.index[-1].strftime('%Y-%m-%d')}",
    "sample_size": len(df_analysis),
    "methodology": {
        "rolling_ar1_window": ROLL_WINDOW,
        "half_life_formula": "-log(2)/log(phi) from AR(1)",
        "is_period": "2011-01 to 2020-12",
        "oos_period": "2021-01 to 2025-09",
        "lag": "All predictors shift(1)",
        "dm_test": "HAC (Newey-West), Harvey |t|>3.0 threshold",
    },
    "descriptive_stats": {
        "half_life_mean": float(df_analysis["half_life"].mean()),
        "half_life_median": float(df_analysis["half_life"].median()),
        "half_life_std": float(df_analysis["half_life"].std()),
        "backwardation_pct": float(100 * len(backwardation) / len(df_analysis)),
        "slow_vs_fast_fwd_rv": {
            "slow_mean": float(slow["fwd_rv22"].mean()),
            "fast_mean": float(fast["fwd_rv22"].mean()),
            "t_stat": float(tstat_hl),
            "p_value": float(pval_hl),
        },
    },
    "correlations": {
        "vix_fwd_rv22": float(stats.pearsonr(corr_df["vix_lag"], corr_df["fwd_rv22"])[0]),
        "ratio_fwd_rv22": float(stats.pearsonr(corr_df["ratio_lag"], corr_df["fwd_rv22"])[0]),
        "halflife_fwd_rv22": float(stats.pearsonr(corr_df["half_life_lag"], corr_df["fwd_rv22"])[0]),
        "partial_halflife_given_vix": float(pr),
        "partial_halflife_given_vix_p": float(pp),
        "partial_ratio_given_vix": float(pr2),
        "partial_ratio_given_vix_p": float(pp2),
    },
    "oos_regression": results,
    "dm_tests": dm_results,
    "var_analysis": var_results,
    "rolling_oos_r2": rolling_r2,
    "conclusion": {
        "any_dm_significant": any_significant,
        "best_oos_model": best_model,
        "verdict": "; ".join(conclusion_parts),
        "vix_sufficiency": "Confirmed if no DM significant" if not any_significant else "Challenged",
    },
    "references": [
        "K866: VIX term structure slope NULL",
        "T39: VIX half-life as crisis warning NULL",
        "K161: VIX/VIX3M ratio OOS fails (overfitting)",
        "K211/T20: VIX mean reversion speed stability",
        "Harvey (2016): |t|>3.0 threshold",
    ],
}

output_path = "/Users/yhlai0911/Desktop/volpred-research/experiments/k879_results.json"
with open(output_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("Done.")
