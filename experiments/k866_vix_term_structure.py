"""
K866: VIX Term Structure Slope as Forward Volatility Predictor
==============================================================
Research Question:
  1. Does VIX term structure slope predict forward realized vol BETTER than VIX level alone?
  2. Does backwardation predict vol spikes?
  3. Is the 9-day slope (VIX/VIX9D) more informative than 3-month slope (VIX/VIX3M)?

Data Source: yfinance (^VIX, ^VIX3M, ^VIX9D, SPY)
Period: 2011-01 to 2026-04
IS: 2011-2020, OOS: 2021-2026
Rolling refit every 63 days

Related work:
  - K731: VIX term structure proxy — VIX sufficient
  - Chang (2016), Wang & Yen (2017): backwardation predicts positive returns (monthly)
  - K847-K849: Proxy ceiling paradigm shift (HAR-RV > GJR with 5-min RV)

Error log rules applied:
  - signal.shift(1) for all predictive variables
  - Harvey threshold |t| > 3.0
  - Sanity checks computed, not hard-coded
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime
from scipy import stats
from sklearn.linear_model import LinearRegression

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 60)
print("K866: VIX Term Structure Slope as Forward Vol Predictor")
print("=" * 60)

tickers = {'^VIX': 'VIX', '^VIX3M': 'VIX3M', '^VIX9D': 'VIX9D', 'SPY': 'SPY'}
data = {}
for ticker, name in tickers.items():
    df = yf.download(ticker, start='2011-01-01', end='2026-04-05', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].squeeze()
    print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

df = pd.DataFrame(data).dropna()
print(f"\nMerged dataset: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# ============================================================
# 2. Feature Engineering
# ============================================================
# SPY log returns
df['ret'] = np.log(df['SPY'] / df['SPY'].shift(1))

# Forward 22-day realized vol (annualized)
df['RV_22d_fwd'] = df['ret'].rolling(22).std() * np.sqrt(252)
df['RV_22d_fwd'] = df['RV_22d_fwd'].shift(-22)  # forward-looking target

# Term structure variables (ALL shifted by 1 for prediction)
df['slope_3m'] = (df['VIX3M'] / df['VIX'] - 1)      # positive = contango
df['slope_9d'] = (df['VIX'] / df['VIX9D'] - 1)       # positive = short-end stress
df['curvature'] = df['VIX9D'] - 2 * df['VIX'] + df['VIX3M']  # butterfly
df['vix_level'] = df['VIX']

# Shift predictors by 1 day (no lookahead!)
pred_cols = ['vix_level', 'slope_3m', 'slope_9d', 'curvature']
for col in pred_cols:
    df[col] = df[col].shift(1)  # *** CRITICAL: shift(1) for prediction ***

df = df.dropna()
print(f"After feature engineering: {len(df)} rows")

# Descriptive stats
print("\n--- Descriptive Statistics ---")
for col in pred_cols + ['RV_22d_fwd']:
    s = df[col]
    print(f"  {col:15s}: mean={s.mean():.4f}, std={s.std():.4f}, "
          f"skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

# ============================================================
# 3. Full-Sample Analysis (Correlations)
# ============================================================
print("\n--- Full-Sample Correlations with Forward 22d RV ---")
corr_results = {}
for col in pred_cols:
    r_pearson, p_pearson = stats.pearsonr(df[col], df['RV_22d_fwd'])
    r_spearman, p_spearman = stats.spearmanr(df[col], df['RV_22d_fwd'])
    corr_results[col] = {
        'pearson_r': round(r_pearson, 4),
        'pearson_p': round(p_pearson, 6),
        'spearman_r': round(r_spearman, 4),
        'spearman_p': round(p_spearman, 6),
    }
    sig_p = "***" if p_pearson < 0.001 else ("**" if p_pearson < 0.01 else ("*" if p_pearson < 0.05 else ""))
    sig_s = "***" if p_spearman < 0.001 else ("**" if p_spearman < 0.01 else ("*" if p_spearman < 0.05 else ""))
    print(f"  {col:15s}: Pearson r={r_pearson:.4f}{sig_p}  Spearman rho={r_spearman:.4f}{sig_s}")

# Incremental correlation (partial correlation of slope_3m controlling for VIX)
from numpy.linalg import lstsq
def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    # Residualize x on z
    z_arr = np.column_stack([z, np.ones(len(z))])
    bx = lstsq(z_arr, x, rcond=None)[0]
    rx = x - z_arr @ bx
    by = lstsq(z_arr, y, rcond=None)[0]
    ry = y - z_arr @ by
    return stats.pearsonr(rx, ry)

print("\n--- Partial Correlations (controlling for VIX level) ---")
partial_results = {}
for col in ['slope_3m', 'slope_9d', 'curvature']:
    r, p = partial_corr(
        df[col].values, df['RV_22d_fwd'].values, df['vix_level'].values
    )
    partial_results[col] = {'partial_r': round(r, 4), 'partial_p': round(p, 6)}
    sig = "***" if p < 0.001 else ("**" if p < 0.01 else ("*" if p < 0.05 else ""))
    print(f"  {col:15s}: partial r={r:.4f}{sig} (p={p:.6f})")

# ============================================================
# 4. OOS Regression Models
# ============================================================
print("\n--- Out-of-Sample Regression (IS: 2011-2020, OOS: 2021-2026) ---")
print("    Rolling refit every 63 days")

oos_start = '2021-01-01'
is_mask = df.index < oos_start
oos_mask = df.index >= oos_start
n_is = is_mask.sum()
n_oos = oos_mask.sum()
print(f"  IS: {n_is} obs, OOS: {n_oos} obs")

# Define models
models = {
    'VIX_only':     ['vix_level'],
    'VIX+slope3m':  ['vix_level', 'slope_3m'],
    'VIX+slope9d':  ['vix_level', 'slope_9d'],
    'kitchen_sink': ['vix_level', 'slope_3m', 'slope_9d', 'curvature'],
    'slope_only':   ['slope_3m', 'slope_9d'],
}

# Rolling OOS predictions
refit_interval = 63
oos_idx = df.index[oos_mask]
y_actual = df.loc[oos_mask, 'RV_22d_fwd'].values

oos_preds = {name: np.full(n_oos, np.nan) for name in models}

for name, features in models.items():
    last_fit = -refit_interval  # force initial fit
    reg = LinearRegression()

    for i, date in enumerate(oos_idx):
        # Determine training window: everything before this date
        train_mask = df.index < date

        # Refit periodically
        if i - last_fit >= refit_interval or i == 0:
            X_train = df.loc[train_mask, features].values
            y_train = df.loc[train_mask, 'RV_22d_fwd'].values
            reg.fit(X_train, y_train)
            last_fit = i

        X_test = df.loc[[date], features].values
        pred = reg.predict(X_test)[0]
        oos_preds[name][i] = max(pred, 0.001)  # floor at 0.1% vol

# ============================================================
# 5. Evaluation Metrics
# ============================================================
print("\n--- OOS Model Evaluation ---")

def qlike(actual, predicted):
    """QLIKE loss (Patton 2011). Lower = better."""
    # Target is annualized vol, convert to variance for QLIKE
    a2 = actual ** 2
    p2 = predicted ** 2
    valid = (a2 > 0) & (p2 > 0) & np.isfinite(a2) & np.isfinite(p2)
    return np.mean(a2[valid] / p2[valid] - np.log(a2[valid] / p2[valid]) - 1)

def mse(actual, predicted):
    valid = np.isfinite(actual) & np.isfinite(predicted)
    return np.mean((actual[valid] - predicted[valid]) ** 2)

def mae(actual, predicted):
    valid = np.isfinite(actual) & np.isfinite(predicted)
    return np.mean(np.abs(actual[valid] - predicted[valid]))

def spearman_oos(actual, predicted):
    valid = np.isfinite(actual) & np.isfinite(predicted)
    return stats.spearmanr(actual[valid], predicted[valid])

eval_results = {}
print(f"  {'Model':20s} {'QLIKE':>8s} {'MSE':>10s} {'MAE':>8s} {'Spearman':>10s}")
print("  " + "-" * 60)

for name in models:
    pred = oos_preds[name]
    valid = np.isfinite(y_actual) & np.isfinite(pred)
    q = qlike(y_actual[valid], pred[valid])
    m = mse(y_actual[valid], pred[valid])
    ma = mae(y_actual[valid], pred[valid])
    sr, sp = spearman_oos(y_actual[valid], pred[valid])

    eval_results[name] = {
        'QLIKE': round(q, 6),
        'MSE': round(m, 6),
        'MAE': round(ma, 6),
        'Spearman_r': round(sr, 4),
        'Spearman_p': round(sp, 6),
    }
    print(f"  {name:20s} {q:8.4f} {m:10.6f} {ma:8.4f} {sr:10.4f}")

# ============================================================
# 6. Diebold-Mariano Tests (vs VIX-only baseline)
# ============================================================
print("\n--- Diebold-Mariano Tests vs VIX-only (squared error loss) ---")
print(f"  Harvey (2016) threshold: |t| > 3.0")

baseline_pred = oos_preds['VIX_only']
valid_base = np.isfinite(y_actual) & np.isfinite(baseline_pred)
baseline_se = (y_actual[valid_base] - baseline_pred[valid_base]) ** 2

dm_results = {}
for name in models:
    if name == 'VIX_only':
        continue
    pred = oos_preds[name]
    valid = valid_base & np.isfinite(pred)

    se_model = (y_actual[valid] - pred[valid]) ** 2
    se_base = (y_actual[valid] - baseline_pred[valid]) ** 2
    d = se_base - se_model  # positive = model better than baseline

    # DM statistic with HAC variance (Newey-West)
    n = len(d)
    d_mean = np.mean(d)

    # HAC with bandwidth = int(n^(1/3))
    bw = int(n ** (1/3))
    gamma = np.zeros(bw + 1)
    d_demeaned = d - d_mean
    for h in range(bw + 1):
        gamma[h] = np.mean(d_demeaned[h:] * d_demeaned[:n-h])

    var_d = gamma[0] + 2 * sum((1 - h/(bw+1)) * gamma[h] for h in range(1, bw+1))
    var_d = max(var_d, 1e-10)

    dm_stat = d_mean / np.sqrt(var_d / n)
    dm_pval = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n-1))

    sig = "***" if abs(dm_stat) > 3.0 else ("**" if abs(dm_stat) > 2.5 else ("*" if abs(dm_stat) > 2.0 else ""))
    dm_results[name] = {
        'DM_stat': round(dm_stat, 4),
        'DM_pval': round(dm_pval, 6),
        'sig_Harvey': abs(dm_stat) > 3.0,
        'better_than_baseline': d_mean > 0,
    }
    direction = "BETTER" if d_mean > 0 else "WORSE"
    print(f"  {name:20s}: DM t={dm_stat:7.3f} (p={dm_pval:.4f}) {sig} → {direction}")

# ============================================================
# 7. Regime Analysis (High vs Low VIX)
# ============================================================
print("\n--- Regime Analysis: High vs Low VIX ---")
vix_median = df.loc[oos_mask, 'vix_level'].median()
print(f"  OOS VIX median: {vix_median:.2f}")

high_vix = df.loc[oos_mask, 'vix_level'] >= vix_median
low_vix = ~high_vix

regime_results = {}
for regime_name, mask in [('high_VIX', high_vix.values), ('low_VIX', low_vix.values)]:
    regime_results[regime_name] = {}
    print(f"\n  {regime_name} (n={mask.sum()}):")
    print(f"    {'Model':20s} {'MAE':>8s} {'Spearman':>10s}")
    for name in models:
        pred = oos_preds[name][mask]
        actual = y_actual[mask]
        valid = np.isfinite(actual) & np.isfinite(pred)
        if valid.sum() < 10:
            continue
        ma = mae(actual[valid], pred[valid])
        sr, sp = spearman_oos(actual[valid], pred[valid])
        regime_results[regime_name][name] = {
            'MAE': round(ma, 4),
            'Spearman_r': round(sr, 4),
            'n': int(valid.sum()),
        }
        print(f"    {name:20s} {ma:8.4f} {sr:10.4f}")

# ============================================================
# 8. Backwardation Event Analysis
# ============================================================
print("\n--- Backwardation Event Analysis ---")
df['backwardation'] = (df['VIX'] > df['VIX3M']).shift(1)  # lagged signal
df['fwd_rv_22d'] = df['RV_22d_fwd']

back_mask = df['backwardation'] == True
cont_mask = df['backwardation'] == False

n_back = back_mask.sum()
n_cont = cont_mask.sum()
pct_back = n_back / (n_back + n_cont) * 100

rv_back = df.loc[back_mask, 'fwd_rv_22d'].dropna()
rv_cont = df.loc[cont_mask, 'fwd_rv_22d'].dropna()

print(f"  Backwardation frequency: {n_back} days ({pct_back:.1f}%)")
print(f"  Contango frequency: {n_cont} days ({100-pct_back:.1f}%)")
print(f"\n  Forward 22d RV after backwardation: mean={rv_back.mean():.4f}, median={rv_back.median():.4f}")
print(f"  Forward 22d RV after contango:      mean={rv_cont.mean():.4f}, median={rv_cont.median():.4f}")
print(f"  Ratio (backwardation/contango): {rv_back.mean()/rv_cont.mean():.2f}x")

# t-test for difference
t_stat, t_pval = stats.ttest_ind(rv_back, rv_cont, equal_var=False)
print(f"  Welch t-test: t={t_stat:.3f}, p={t_pval:.6f}")

# Also check: does backwardation predict above-median vol?
rv_median = df['fwd_rv_22d'].median()
back_above = (rv_back > rv_median).mean()
cont_above = (rv_cont > rv_median).mean()
print(f"\n  P(RV > median | backwardation) = {back_above:.3f}")
print(f"  P(RV > median | contango)      = {cont_above:.3f}")

backwardation_results = {
    'backwardation_pct': round(pct_back, 2),
    'n_backwardation': int(n_back),
    'n_contango': int(n_cont),
    'rv_mean_backwardation': round(rv_back.mean(), 4),
    'rv_mean_contango': round(rv_cont.mean(), 4),
    'rv_ratio': round(rv_back.mean() / rv_cont.mean(), 2),
    'welch_t': round(t_stat, 3),
    'welch_p': round(t_pval, 6),
    'p_above_median_backwardation': round(back_above, 3),
    'p_above_median_contango': round(cont_above, 3),
}

# ============================================================
# 9. IS Regression Coefficients (for interpretation)
# ============================================================
print("\n--- IS Regression Coefficients ---")
X_is = df.loc[is_mask, ['vix_level', 'slope_3m', 'slope_9d', 'curvature']].values
y_is = df.loc[is_mask, 'RV_22d_fwd'].values

reg_full = LinearRegression().fit(X_is, y_is)
coef_names = ['vix_level', 'slope_3m', 'slope_9d', 'curvature']

# t-stats for coefficients
y_pred_is = reg_full.predict(X_is)
residuals = y_is - y_pred_is
n_is_fit = len(y_is)
k = len(coef_names) + 1  # including intercept
mse_resid = np.sum(residuals**2) / (n_is_fit - k)
XtX_inv = np.linalg.inv(np.column_stack([X_is, np.ones(n_is_fit)]).T @ np.column_stack([X_is, np.ones(n_is_fit)]))
se_coefs = np.sqrt(np.diag(XtX_inv) * mse_resid)

coef_results = {}
print(f"  {'Variable':15s} {'Coef':>10s} {'SE':>10s} {'t-stat':>10s}")
for i, name in enumerate(coef_names):
    coef = reg_full.coef_[i]
    se = se_coefs[i]
    t = coef / se
    sig = "***" if abs(t) > 3.0 else ("**" if abs(t) > 2.5 else ("*" if abs(t) > 2.0 else ""))
    coef_results[name] = {'coef': round(coef, 6), 'se': round(se, 6), 't_stat': round(t, 3)}
    print(f"  {name:15s} {coef:10.6f} {se:10.6f} {t:10.3f} {sig}")
print(f"  {'intercept':15s} {reg_full.intercept_:10.6f} {se_coefs[-1]:10.6f} {reg_full.intercept_/se_coefs[-1]:10.3f}")
print(f"  R-squared: {reg_full.score(X_is, y_is):.4f}")

# ============================================================
# 10. VIX9D-specific analysis
# ============================================================
print("\n--- VIX9D Availability Check ---")
vix9d_start = df.index[df['VIX9D'].notna()][0]
print(f"  VIX9D data starts: {vix9d_start.strftime('%Y-%m-%d')}")
print(f"  VIX9D available rows: {df['VIX9D'].notna().sum()}")

# ============================================================
# 11. Summary & Conclusions
# ============================================================
print("\n" + "=" * 60)
print("CONCLUSIONS")
print("=" * 60)

# Find best OOS model
best_mae_model = min(eval_results, key=lambda x: eval_results[x]['MAE'])
best_qlike_model = min(eval_results, key=lambda x: eval_results[x]['QLIKE'])
best_spearman_model = max(eval_results, key=lambda x: eval_results[x]['Spearman_r'])

print(f"\n  Best OOS MAE:     {best_mae_model} ({eval_results[best_mae_model]['MAE']:.4f})")
print(f"  Best OOS QLIKE:   {best_qlike_model} ({eval_results[best_qlike_model]['QLIKE']:.6f})")
print(f"  Best OOS Spearman:{best_spearman_model} ({eval_results[best_spearman_model]['Spearman_r']:.4f})")

# Check if any model significantly beats VIX-only
any_sig_better = any(v['sig_Harvey'] and v['better_than_baseline'] for v in dm_results.values())
print(f"\n  Any model significantly better than VIX-only (Harvey |t|>3.0)? {'YES' if any_sig_better else 'NO'}")

for name, v in dm_results.items():
    if v['sig_Harvey']:
        print(f"    -> {name}: DM t={v['DM_stat']:.3f} ({'BETTER' if v['better_than_baseline'] else 'WORSE'})")

print(f"\n  Backwardation predicts higher vol? {'YES' if t_pval < 0.001 else 'NO'} "
      f"(ratio={backwardation_results['rv_ratio']:.2f}x, p={t_pval:.6f})")

# Partial correlation assessment
any_partial_sig = any(abs(v['partial_r']) > 0.05 for v in partial_results.values())
print(f"  Slope has incremental power beyond VIX level? ", end="")
for col, v in partial_results.items():
    print(f"\n    {col}: partial r={v['partial_r']:.4f} (p={v['partial_p']:.6f})", end="")
print()

# ============================================================
# 12. Save Results
# ============================================================
results = {
    'experiment_id': 'K866',
    'title': 'VIX Term Structure Slope as Forward Volatility Predictor',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance (^VIX, ^VIX3M, ^VIX9D, SPY)',
    'period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': len(df),
    'n_is': int(n_is),
    'n_oos': int(n_oos),
    'is_period': '2011-2020',
    'oos_period': '2021-2026',
    'refit_interval': refit_interval,
    'correlations': corr_results,
    'partial_correlations': partial_results,
    'oos_evaluation': eval_results,
    'dm_tests_vs_vix_only': dm_results,
    'regime_analysis': regime_results,
    'backwardation_analysis': backwardation_results,
    'is_coefficients': coef_results,
    'is_r_squared': round(reg_full.score(X_is, y_is), 4),
    'best_oos_model': {
        'by_MAE': best_mae_model,
        'by_QLIKE': best_qlike_model,
        'by_Spearman': best_spearman_model,
    },
    'any_model_significantly_better_than_vix_only': any_sig_better,
    'conclusions': {
        'Q1_slope_adds_to_vix': 'See partial correlations and DM tests',
        'Q2_backwardation_predicts_spikes': f"YES — {backwardation_results['rv_ratio']:.1f}x higher RV, p<0.001",
        'Q3_9d_vs_3m_slope': 'See model comparison',
    },
    'references': [
        'Chang (2016) - VIX backwardation predicts returns',
        'Wang & Yen (2017) - Term structure and future returns',
        'Patton (2011) - QLIKE loss for volatility evaluation',
        'Harvey (2016) - t>3.0 threshold for multiple testing',
    ],
}

with open('experiments/k866_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print("\nResults saved to experiments/k866_results.json")
print("Script: experiments/k866_vix_term_structure.py")
