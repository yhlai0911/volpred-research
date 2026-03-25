"""
K429: VIX Term Structure Slope for Volatility Direction Prediction
==================================================================
[提出: User, 執行: Claude]

Research Question:
Does VIX term structure slope (VIX3M - VIX) provide incremental information
for predicting volatility changes BEYOND what VIX level and GARCH already capture?

Key difference from prior work (K113, P35-P41, etc.):
- Focus on DIRECTION prediction (vol up/down), not just level
- Multi-horizon (1d, 5d, 22d)
- Systematic comparison: GARCH vs VIX-only vs VIX+slope vs full term structure
- Ridge regression to handle multicollinearity

Data: ^VIX, ^VIX3M, ^VIX9D (if available), SPY from yfinance
IS: 2012-2022, OOS: 2023-2025
Metrics: QLIKE, MSE, DM test, Direction Accuracy
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler
from scipy import stats
from arch import arch_model

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K429: VIX Term Structure Slope - Vol Direction Prediction")
print("=" * 60)

tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'VIX3M': '^VIX3M',
    'VIX9D': '^VIX9D',
}

data = {}
for name, ticker in tickers.items():
    try:
        df = yf.download(ticker, start='2010-01-01', end='2026-01-01', progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        data[name] = df['Close'].dropna()
        print(f"  {name}: {len(data[name])} obs, {data[name].index[0].date()} ~ {data[name].index[-1].date()}")
    except Exception as e:
        print(f"  {name}: FAILED - {e}")

# Check VIX9D availability
has_vix9d = 'VIX9D' in data and len(data['VIX9D']) > 500
print(f"\nVIX9D available: {has_vix9d} ({len(data.get('VIX9D', [])) if 'VIX9D' in data else 0} obs)")

# Merge into single DataFrame
df = pd.DataFrame({
    'spy_close': data['SPY'],
    'vix': data['VIX'],
    'vix3m': data['VIX3M'],
})
if has_vix9d:
    df['vix9d'] = data['VIX9D']

df = df.dropna()
print(f"\nMerged data: {len(df)} obs, {df.index[0].date()} ~ {df.index[-1].date()}")

# ============================================================
# 2. Feature Engineering (all vectorized)
# ============================================================
print("\n--- Feature Engineering ---")

# SPY returns
df['ret'] = np.log(df['spy_close'] / df['spy_close'].shift(1))
df['abs_ret'] = df['ret'].abs()

# Realized vol targets
df['rv_1d'] = df['abs_ret']  # next-day proxy
df['rv_5d'] = df['abs_ret'].rolling(5).mean().shift(-4)  # forward-looking 5d
df['rv_22d'] = df['abs_ret'].rolling(22).mean().shift(-21)  # forward-looking 22d

# VIX term structure features
df['vix_slope'] = df['vix3m'] - df['vix']  # positive = contango
df['vix_ratio'] = df['vix'] / df['vix3m']  # >1 = backwardation
df['vix_slope_norm'] = df['vix_slope'] / df['vix']  # normalized slope

if has_vix9d:
    df['vix_curvature'] = df['vix9d'] - 2 * df['vix'] + df['vix3m']
else:
    df['vix_curvature'] = np.nan

df['vix_momentum'] = df['vix'].pct_change(5)  # 5-day VIX momentum
df['vix_zscore'] = (df['vix'] - df['vix'].rolling(63).mean()) / df['vix'].rolling(63).std()
df['vix_slope_momentum'] = df['vix_slope'].diff(5)  # slope change over 5d

# Historical vol features
df['hist_vol_5d'] = df['ret'].rolling(5).std() * np.sqrt(252)
df['hist_vol_22d'] = df['ret'].rolling(22).std() * np.sqrt(252)

# VIX product (model-free, from prior research)
df['vix_product'] = df['vix'] ** 2 / df['vix3m']

# Direction targets (will be set after shift)
# vol_direction_1d: next day |ret| > today |ret|
# vol_direction_5d: next 5d avg |ret| > current 5d avg |ret|

# ============================================================
# 3. GJR-GARCH Baseline
# ============================================================
print("\n--- Fitting GJR-GARCH(1,1) ---")

# Fit on full sample to get conditional variance series
ret_series = df['ret'].dropna() * 100  # in percentage

am = arch_model(ret_series, vol='GARCH', p=1, o=1, q=1, dist='t', mean='AR', lags=1)
res = am.fit(disp='off', show_warning=False)
print(f"  Convergence: {res.convergence_flag == 0}")
print(f"  Persistence: {res.params.get('alpha[1]', 0) + res.params.get('gamma[1]', 0)/2 + res.params.get('beta[1]', 0):.4f}")

# Conditional vol (annualized, in decimal)
cond_var = res.conditional_volatility / 100 * np.sqrt(252)  # annualized
df['garch_vol'] = cond_var.reindex(df.index)

# One-step ahead forecast (shift by 1)
df['garch_forecast'] = df['garch_vol'].shift(1)  # forecast made at t-1 for t

print(f"  GARCH vol range: {df['garch_vol'].min():.4f} ~ {df['garch_vol'].max():.4f}")

# ============================================================
# 4. Construct Prediction Targets
# ============================================================
# Shift features to avoid look-ahead bias: features at t predict t+1
# All features use information up to and including time t

# Direction targets
df['vol_up_1d'] = (df['abs_ret'].shift(-1) > df['abs_ret']).astype(float)
df['vol_up_5d'] = (df['rv_5d'].shift(-1) > df['rv_5d']).astype(float)

# Drop NaN rows
df = df.dropna(subset=['vix_slope', 'vix_ratio', 'vix_momentum', 'vix_zscore',
                         'garch_forecast', 'hist_vol_5d', 'hist_vol_22d'])

print(f"\nClean data: {len(df)} obs")

# ============================================================
# 5. Define Models and OOS Setup
# ============================================================
IS_END = '2022-12-31'
OOS_START = '2023-01-01'

is_mask = df.index <= IS_END
oos_mask = df.index >= OOS_START

is_data = df[is_mask].copy()
oos_data = df[oos_mask].copy()

# Remove rows with NaN targets in OOS
oos_data = oos_data.dropna(subset=['rv_1d', 'vol_up_1d'])

print(f"IS: {len(is_data)} obs ({is_data.index[0].date()} ~ {is_data.index[-1].date()})")
print(f"OOS: {len(oos_data)} obs ({oos_data.index[0].date()} ~ {oos_data.index[-1].date()})")

# Feature sets for different models
feature_sets = {
    'GARCH_only': ['garch_forecast'],
    'VIX_only': ['vix'],
    'VIX_slope': ['vix', 'vix_slope'],
    'VIX_slope_norm': ['vix', 'vix_slope_norm', 'vix_ratio'],
    'VIX_full': ['vix', 'vix_slope', 'vix_ratio', 'vix_momentum', 'vix_zscore',
                  'vix_slope_momentum'],
    'Kitchen_sink': ['vix', 'vix_slope', 'vix_ratio', 'vix_momentum', 'vix_zscore',
                      'vix_slope_momentum', 'garch_forecast', 'hist_vol_5d', 'hist_vol_22d'],
}

if has_vix9d:
    feature_sets['VIX_full'].append('vix_curvature')
    feature_sets['Kitchen_sink'].append('vix_curvature')

# ============================================================
# 6. Evaluation Functions
# ============================================================
def qlike(actual, forecast):
    """QLIKE loss (lower is better)."""
    actual_sq = actual ** 2
    forecast_sq = forecast ** 2
    # Avoid log(0)
    mask = (forecast_sq > 1e-20) & (actual_sq > 1e-20)
    ql = np.log(forecast_sq[mask]) + actual_sq[mask] / forecast_sq[mask]
    return np.mean(ql)

def mse(actual, forecast):
    """MSE between squared returns and squared forecasts."""
    return np.mean((actual**2 - forecast**2)**2)

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive ability.
    Negative t-stat means model 1 is better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / h) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma0 / n
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * stats.t.cdf(-abs(t_stat), df=n - 1)
    return t_stat, p_value

def direction_accuracy(actual_dir, pred_dir):
    """Direction accuracy."""
    mask = np.isfinite(actual_dir) & np.isfinite(pred_dir)
    if mask.sum() < 30:
        return np.nan
    return np.mean(actual_dir[mask] == pred_dir[mask])

# ============================================================
# 7. Run Models - Continuous Vol Prediction (Ridge)
# ============================================================
print("\n" + "=" * 60)
print("Part A: Continuous Volatility Prediction (Ridge Regression)")
print("=" * 60)

results_continuous = {}

for target_name, target_col, horizon in [
    ('1d_abs_ret', 'rv_1d', 1),
    ('5d_avg_abs_ret', 'rv_5d', 5),
    ('22d_avg_abs_ret', 'rv_22d', 22),
]:
    print(f"\n--- Target: {target_name} (horizon={horizon}d) ---")

    # Forward target: what we're predicting
    # Use shift(-horizon) for the target but features are current
    y_target = df[target_col].shift(-1)  # next period's value

    valid_mask = y_target.notna() & is_mask
    valid_oos = y_target.notna() & oos_mask

    if valid_mask.sum() < 100 or valid_oos.sum() < 30:
        print(f"  Skipping: insufficient data (IS={valid_mask.sum()}, OOS={valid_oos.sum()})")
        continue

    model_results = {}

    for model_name, features in feature_sets.items():
        # Check all features available
        avail = [f for f in features if f in df.columns and df[f].notna().sum() > 100]
        if len(avail) < len(features):
            continue

        X_is = df.loc[valid_mask, avail].values
        y_is = y_target[valid_mask].values
        X_oos = df.loc[valid_oos, avail].values
        y_oos = y_target[valid_oos].values

        # Standardize
        scaler = StandardScaler()
        X_is_s = scaler.fit_transform(X_is)
        X_oos_s = scaler.transform(X_oos)

        # Ridge regression
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_is_s, y_is)

        y_pred = ridge.predict(X_oos_s)
        y_pred = np.maximum(y_pred, 1e-6)  # ensure positive

        # Metrics
        ql = qlike(y_oos, y_pred)
        ms = np.mean((y_oos - y_pred) ** 2)
        corr = np.corrcoef(y_oos, y_pred)[0, 1]
        r2_oos = 1 - np.sum((y_oos - y_pred)**2) / np.sum((y_oos - np.mean(y_oos))**2)

        # Store individual losses for DM test
        losses = (y_oos - y_pred) ** 2

        model_results[model_name] = {
            'qlike': float(ql),
            'mse': float(ms),
            'corr': float(corr),
            'r2_oos': float(r2_oos),
            'losses': losses,
            'coefficients': dict(zip(avail, ridge.coef_.tolist())),
            'n_oos': int(len(y_oos)),
        }

        print(f"  {model_name:20s}: QLIKE={ql:.6f}, MSE={ms:.8f}, Corr={corr:.4f}, R2={r2_oos:.4f}")

    # DM tests vs baselines
    print(f"\n  DM tests (negative = row model better):")
    baseline_names = ['GARCH_only', 'VIX_only']
    for base in baseline_names:
        if base not in model_results:
            continue
        for model_name in model_results:
            if model_name == base:
                continue
            t_stat, p_val = dm_test(model_results[model_name]['losses'],
                                     model_results[base]['losses'], h=max(horizon, 1))
            sig = "***" if p_val < 0.01 else "**" if p_val < 0.05 else "*" if p_val < 0.10 else ""
            print(f"    {model_name:20s} vs {base:15s}: t={t_stat:+.3f}, p={p_val:.4f} {sig}")

            model_results[model_name][f'dm_vs_{base}_t'] = float(t_stat) if np.isfinite(t_stat) else None
            model_results[model_name][f'dm_vs_{base}_p'] = float(p_val) if np.isfinite(p_val) else None

    # Clean up non-serializable
    for m in model_results:
        if 'losses' in model_results[m]:
            del model_results[m]['losses']

    results_continuous[target_name] = model_results

# ============================================================
# 8. Direction Prediction (Logistic-like via Ridge)
# ============================================================
print("\n" + "=" * 60)
print("Part B: Volatility Direction Prediction")
print("=" * 60)

from sklearn.linear_model import RidgeClassifier
from sklearn.metrics import accuracy_score, roc_auc_score, classification_report

results_direction = {}

for target_name, target_col in [
    ('vol_up_1d', 'vol_up_1d'),
    ('vol_up_5d', 'vol_up_5d'),
]:
    print(f"\n--- Target: {target_name} ---")

    y_target = df[target_col]
    valid_mask_dir = y_target.notna() & is_mask
    valid_oos_dir = y_target.notna() & oos_mask

    if valid_mask_dir.sum() < 100 or valid_oos_dir.sum() < 30:
        print(f"  Skipping: insufficient data")
        continue

    # Base rate
    base_rate = y_target[valid_oos_dir].mean()
    print(f"  OOS base rate (vol up): {base_rate:.3f}")

    model_dir_results = {}

    for model_name, features in feature_sets.items():
        avail = [f for f in features if f in df.columns and df[f].notna().sum() > 100]
        if len(avail) < len(features):
            continue

        X_is = df.loc[valid_mask_dir, avail].values
        y_is = y_target[valid_mask_dir].values
        X_oos = df.loc[valid_oos_dir, avail].values
        y_oos = y_target[valid_oos_dir].values

        scaler = StandardScaler()
        X_is_s = scaler.fit_transform(X_is)
        X_oos_s = scaler.transform(X_oos)

        clf = RidgeClassifier(alpha=1.0)
        clf.fit(X_is_s, y_is)

        y_pred = clf.predict(X_oos_s)
        acc = accuracy_score(y_oos, y_pred)

        # Decision function for AUC
        y_scores = clf.decision_function(X_oos_s)
        try:
            auc = roc_auc_score(y_oos, y_scores)
        except:
            auc = np.nan

        # Statistical significance of accuracy vs 50%
        n = len(y_oos)
        se = np.sqrt(0.5 * 0.5 / n)  # SE under H0: p=0.5
        z_stat = (acc - 0.5) / se
        p_val_acc = 2 * (1 - stats.norm.cdf(abs(z_stat)))

        model_dir_results[model_name] = {
            'accuracy': float(acc),
            'auc': float(auc) if np.isfinite(auc) else None,
            'z_stat_vs_50pct': float(z_stat),
            'p_value_vs_50pct': float(p_val_acc),
            'n_oos': int(n),
            'base_rate': float(base_rate),
            'coefficients': dict(zip(avail, clf.coef_[0].tolist() if clf.coef_.ndim > 1 else clf.coef_.tolist())),
        }

        sig = "***" if p_val_acc < 0.01 else "**" if p_val_acc < 0.05 else "*" if p_val_acc < 0.10 else ""
        print(f"  {model_name:20s}: Acc={acc:.4f}, AUC={auc:.4f}, z={z_stat:+.3f} {sig}")

    # Pairwise accuracy comparison (McNemar test)
    print(f"\n  Pairwise comparisons (McNemar-like z-test):")
    for base in ['GARCH_only', 'VIX_only']:
        if base not in model_dir_results:
            continue
        base_acc = model_dir_results[base]['accuracy']
        n = model_dir_results[base]['n_oos']
        for model_name in model_dir_results:
            if model_name == base:
                continue
            model_acc = model_dir_results[model_name]['accuracy']
            # Approximate z-test for difference in proportions
            diff = model_acc - base_acc
            se_diff = np.sqrt(2 * base_acc * (1 - base_acc) / n)  # conservative
            if se_diff > 0:
                z = diff / se_diff
                p = 2 * (1 - stats.norm.cdf(abs(z)))
            else:
                z, p = 0, 1
            sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
            print(f"    {model_name:20s} vs {base:15s}: diff={diff:+.4f}, z={z:+.3f}, p={p:.4f} {sig}")

    results_direction[target_name] = model_dir_results

# ============================================================
# 9. Regime-Conditional Analysis
# ============================================================
print("\n" + "=" * 60)
print("Part C: Regime-Conditional Direction Accuracy")
print("=" * 60)

# Split OOS by VIX regime
oos_df = df[oos_mask].copy()
oos_df = oos_df.dropna(subset=['vol_up_1d'])

regimes = {
    'Low VIX (<15)': oos_df['vix'] < 15,
    'Normal VIX (15-20)': (oos_df['vix'] >= 15) & (oos_df['vix'] < 20),
    'Elevated VIX (20-25)': (oos_df['vix'] >= 20) & (oos_df['vix'] < 25),
    'High VIX (>25)': oos_df['vix'] >= 25,
    'Contango (ratio<0.95)': oos_df['vix_ratio'] < 0.95,
    'Flat (0.95-1.05)': (oos_df['vix_ratio'] >= 0.95) & (oos_df['vix_ratio'] <= 1.05),
    'Backwardation (ratio>1.05)': oos_df['vix_ratio'] > 1.05,
}

regime_results = {}

for regime_name, mask in regimes.items():
    n_regime = mask.sum()
    if n_regime < 20:
        print(f"  {regime_name}: {n_regime} obs (too few)")
        continue

    base_rate = oos_df.loc[mask, 'vol_up_1d'].mean()

    # Fit on full IS, evaluate on regime subset
    regime_accs = {}
    for model_name, features in feature_sets.items():
        avail = [f for f in features if f in df.columns and df[f].notna().sum() > 100]
        if len(avail) < len(features):
            continue

        valid_is = df[target_col].notna() & is_mask
        X_is = df.loc[valid_is, avail].values
        y_is = df.loc[valid_is, 'vol_up_1d'].values

        scaler = StandardScaler()
        X_is_s = scaler.fit_transform(X_is)

        X_regime = oos_df.loc[mask, avail].values
        y_regime = oos_df.loc[mask, 'vol_up_1d'].values
        X_regime_s = scaler.transform(X_regime)

        clf = RidgeClassifier(alpha=1.0)
        clf.fit(X_is_s, y_is)

        y_pred = clf.predict(X_regime_s)
        acc = accuracy_score(y_regime, y_pred)
        regime_accs[model_name] = float(acc)

    regime_results[regime_name] = {
        'n': int(n_regime),
        'base_rate_vol_up': float(base_rate),
        'accuracies': regime_accs,
    }

    accs_str = ", ".join([f"{k}={v:.3f}" for k, v in regime_accs.items()])
    print(f"  {regime_name:30s}: n={n_regime:4d}, base={base_rate:.3f} | {accs_str}")

# ============================================================
# 10. Time-Series Stability (Rolling OOS)
# ============================================================
print("\n" + "=" * 60)
print("Part D: Rolling OOS Stability (Annual)")
print("=" * 60)

annual_results = {}
for year in [2023, 2024, 2025]:
    year_mask = (df.index >= f'{year}-01-01') & (df.index <= f'{year}-12-31')
    year_data = df[year_mask].dropna(subset=['vol_up_1d'])

    if len(year_data) < 50:
        continue

    year_accs = {}
    for model_name, features in feature_sets.items():
        avail = [f for f in features if f in df.columns and df[f].notna().sum() > 100]
        if len(avail) < len(features):
            continue

        valid_is = df['vol_up_1d'].notna() & is_mask
        X_is = df.loc[valid_is, avail].values
        y_is = df.loc[valid_is, 'vol_up_1d'].values

        scaler = StandardScaler()
        X_is_s = scaler.fit_transform(X_is)

        X_yr = year_data[avail].values
        y_yr = year_data['vol_up_1d'].values
        X_yr_s = scaler.transform(X_yr)

        clf = RidgeClassifier(alpha=1.0)
        clf.fit(X_is_s, y_is)

        y_pred = clf.predict(X_yr_s)
        acc = accuracy_score(y_yr, y_pred)
        year_accs[model_name] = float(acc)

    annual_results[str(year)] = {
        'n': int(len(year_data)),
        'accuracies': year_accs,
    }

    accs_str = ", ".join([f"{k}={v:.3f}" for k, v in year_accs.items()])
    print(f"  {year}: n={len(year_data)} | {accs_str}")

# ============================================================
# 11. Descriptive Statistics
# ============================================================
print("\n" + "=" * 60)
print("Part E: Descriptive Statistics (OOS Period)")
print("=" * 60)

desc_cols = ['vix', 'vix3m', 'vix_slope', 'vix_ratio', 'vix_momentum', 'vix_zscore',
             'abs_ret', 'hist_vol_22d', 'garch_vol']
if has_vix9d:
    desc_cols.insert(2, 'vix9d')

desc_stats = {}
for col in desc_cols:
    if col in oos_data.columns:
        s = oos_data[col].dropna()
        desc_stats[col] = {
            'mean': float(s.mean()),
            'std': float(s.std()),
            'skew': float(s.skew()),
            'kurt': float(s.kurtosis()),
            'min': float(s.min()),
            'max': float(s.max()),
            'median': float(s.median()),
        }
        print(f"  {col:20s}: mean={s.mean():.4f}, std={s.std():.4f}, skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

# Correlation matrix of features (OOS)
corr_cols = ['vix', 'vix_slope', 'vix_ratio', 'vix_momentum', 'vix_zscore', 'garch_forecast']
corr_matrix = oos_data[corr_cols].dropna().corr()
print(f"\n  Feature correlations (OOS):")
print(corr_matrix.round(3).to_string())

# ============================================================
# 12. Summary & Conclusions
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

# Best model for 1d direction
if 'vol_up_1d' in results_direction:
    dir_1d = results_direction['vol_up_1d']
    best_dir = max(dir_1d.items(), key=lambda x: x[1]['accuracy'])
    print(f"\nBest 1d direction model: {best_dir[0]} (Acc={best_dir[1]['accuracy']:.4f})")

    # Check if any slope model beats VIX-only
    vix_only_acc = dir_1d.get('VIX_only', {}).get('accuracy', 0)
    slope_models = {k: v for k, v in dir_1d.items() if 'slope' in k.lower() or k in ['VIX_full', 'Kitchen_sink']}
    best_slope = max(slope_models.items(), key=lambda x: x[1]['accuracy']) if slope_models else None

    if best_slope:
        diff = best_slope[1]['accuracy'] - vix_only_acc
        print(f"Best slope model: {best_slope[0]} (Acc={best_slope[1]['accuracy']:.4f})")
        print(f"Improvement over VIX-only: {diff:+.4f} ({diff*100:+.2f}pp)")
        print(f"Slope model significant? z={best_slope[1]['z_stat_vs_50pct']:.3f}, p={best_slope[1]['p_value_vs_50pct']:.4f}")

# Continuous prediction
if '1d_abs_ret' in results_continuous:
    cont_1d = results_continuous['1d_abs_ret']
    best_cont = min(cont_1d.items(), key=lambda x: x[1]['mse'])
    print(f"\nBest 1d continuous model: {best_cont[0]} (MSE={best_cont[1]['mse']:.8f})")

# ============================================================
# 13. Compile & Save Results
# ============================================================
final_results = {
    'experiment_id': 'K429',
    'title': 'VIX Term Structure Slope for Volatility Direction Prediction',
    'hypothesis': 'VIX term structure slope provides incremental information for predicting volatility changes beyond VIX level and GARCH',
    'data_source': 'yfinance: ^VIX, ^VIX3M, ^VIX9D, SPY',
    'data_period': f"{df.index[0].date()} ~ {df.index[-1].date()}",
    'is_period': f"{is_data.index[0].date()} ~ {is_data.index[-1].date()}",
    'oos_period': f"{oos_data.index[0].date()} ~ {oos_data.index[-1].date()}",
    'n_is': int(len(is_data)),
    'n_oos': int(len(oos_data)),
    'vix9d_available': has_vix9d,
    'garch_spec': 'GJR-GARCH(1,1)-t with AR(1) mean',
    'garch_convergence': bool(res.convergence_flag == 0),
    'garch_persistence': float(res.params.get('alpha[1]', 0) + res.params.get('gamma[1]', 0)/2 + res.params.get('beta[1]', 0)),
    'descriptive_statistics': desc_stats,
    'feature_correlations_oos': {str(k): {str(k2): float(v2) for k2, v2 in v.items()}
                                  for k, v in corr_matrix.to_dict().items()},
    'continuous_prediction': results_continuous,
    'direction_prediction': results_direction,
    'regime_conditional': regime_results,
    'annual_stability': annual_results,
    'conclusions': {},
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

# Determine conclusions
conclusions = {}

# 1. Does slope add to VIX for continuous prediction?
if '1d_abs_ret' in results_continuous:
    vix_mse = results_continuous['1d_abs_ret'].get('VIX_only', {}).get('mse', float('inf'))
    slope_mse = results_continuous['1d_abs_ret'].get('VIX_slope', {}).get('mse', float('inf'))
    dm_t = results_continuous['1d_abs_ret'].get('VIX_slope', {}).get('dm_vs_VIX_only_t', None)
    dm_p = results_continuous['1d_abs_ret'].get('VIX_slope', {}).get('dm_vs_VIX_only_p', None)

    conclusions['slope_vs_vix_continuous'] = {
        'vix_mse': vix_mse,
        'slope_mse': slope_mse,
        'dm_t': dm_t,
        'dm_p': dm_p,
        'conclusion': 'slope_helps' if (dm_p is not None and dm_p < 0.05 and slope_mse < vix_mse) else 'no_incremental_value'
    }

# 2. Does any model beat 55% direction accuracy?
if 'vol_up_1d' in results_direction:
    max_acc_model = max(results_direction['vol_up_1d'].items(), key=lambda x: x[1]['accuracy'])
    max_acc = max_acc_model[1]['accuracy']
    conclusions['direction_practical'] = {
        'best_model': max_acc_model[0],
        'best_accuracy': float(max_acc),
        'threshold_55pct': max_acc > 0.55,
        'significant_vs_50pct': max_acc_model[1]['p_value_vs_50pct'] < 0.05,
        'conclusion': 'practical_value' if max_acc > 0.55 and max_acc_model[1]['p_value_vs_50pct'] < 0.05 else 'no_practical_value'
    }

# 3. Overall verdict
slope_helps = conclusions.get('slope_vs_vix_continuous', {}).get('conclusion') == 'slope_helps'
dir_helps = conclusions.get('direction_practical', {}).get('conclusion') == 'practical_value'

if slope_helps and dir_helps:
    conclusions['overall'] = 'VIX term structure slope provides incremental information for both continuous and direction vol prediction'
elif slope_helps:
    conclusions['overall'] = 'VIX term structure slope helps continuous prediction but not direction'
elif dir_helps:
    conclusions['overall'] = 'VIX term structure slope helps direction prediction but not continuous'
else:
    conclusions['overall'] = 'VIX term structure slope does NOT provide significant incremental information beyond VIX level — consistent with prior findings (K113, VIX sufficiency)'

final_results['conclusions'] = conclusions
print(f"\n{'='*60}")
print(f"OVERALL CONCLUSION: {conclusions['overall']}")
print(f"{'='*60}")

# Save
output_path = 'experiments/k429_vix_term_structure_results.json'
with open(output_path, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("Done.")
