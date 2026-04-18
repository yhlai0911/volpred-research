"""
K370: VIX Term Structure Rolling Validation — Does K369's t=3.94 Survive?
=========================================================================
K266 validation protocol applied to K369's VIX term structure ratio finding.

K369 found VIX3M/VIX ratio passes Harvey threshold (DM t=3.94, +7.6pp R²).
K265→K266 and K335→K339 taught us full-sample results can be artifacts.

Protocol:
1. Rolling 252d OLS (Stage 1: VIX-only, Stage 2: VIX + TS ratio)
2. 5-period cross-validation (~4-year periods, 2008-2026)
3. Per-period: QLIKE improvement, DM test (Newey-West HAC), coefficient sign
4. Pass criteria (ALL must hold):
   - 3+/5 periods show QLIKE improvement
   - Consistent c sign (TS ratio coefficient) across periods
   - Pooled DM passes Harvey (t > 3.0)

Data: yfinance ^VIX, ^VIX3M, SPY daily. Real data only.

[提出: User, 執行: Claude]
"""

import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import json
from datetime import datetime

# ============================================================
# 1. Download data
# ============================================================
print("=" * 70)
print("K370: VIX Term Structure Rolling Validation (K266 Protocol)")
print("=" * 70)

print("\n[1/6] Downloading data from yfinance...")

spy = yf.download("SPY", start="2005-01-01", end="2026-04-01", progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
spy_close_col = "Adj Close" if "Adj Close" in spy.columns else "Close"
spy_ret = spy[spy_close_col].pct_change().dropna()
spy_ret.name = "returns"

vix_raw = yf.download("^VIX", start="2005-01-01", end="2026-04-01", progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix = vix_raw["Close"].copy()
vix.name = "VIX"

vix3m_raw = yf.download("^VIX3M", start="2005-01-01", end="2026-04-01", progress=False)
if isinstance(vix3m_raw.columns, pd.MultiIndex):
    vix3m_raw.columns = vix3m_raw.columns.get_level_values(0)
vix3m = vix3m_raw["Close"].copy()
vix3m.name = "VIX3M"

print(f"  SPY returns: {len(spy_ret)} obs ({spy_ret.index[0].date()} to {spy_ret.index[-1].date()})")
print(f"  VIX: {len(vix)} obs ({vix.index[0].date()} to {vix.index[-1].date()})")
print(f"  VIX3M: {len(vix3m)} obs ({vix3m.index[0].date()} to {vix3m.index[-1].date()})")

# ============================================================
# 2. Build dataset: RV_22d target + lagged predictors
# ============================================================
print("\n[2/6] Building dataset (22-day RV + lagged predictors)...")

# Align all series on common dates
common_idx = spy_ret.index.intersection(vix.index).intersection(vix3m.index)
spy_ret_aligned = spy_ret.loc[common_idx]
vix_aligned = vix.loc[common_idx]
vix3m_aligned = vix3m.loc[common_idx]

# Compute 22-day forward realized volatility (annualized)
rv_22d = spy_ret_aligned.rolling(22).std() * np.sqrt(252)
rv_22d = rv_22d.shift(-22)  # forward-looking target

# TS ratio: VIX3M/VIX (contango > 1, backwardation < 1)
ts_ratio = (vix3m_aligned / vix_aligned).copy()
ts_ratio.name = "TS_ratio"

# Lagged predictors (t-1)
vix_lagged = vix_aligned.shift(1) / 100.0  # Scale to annualized decimal
ts_ratio_lagged = ts_ratio.shift(1)

# Build clean dataframe
df = pd.DataFrame({
    'rv_22d': rv_22d,
    'vix_lag': vix_lagged,
    'ts_ratio_lag': ts_ratio_lagged,
}).dropna()

print(f"  Clean dataset: {len(df)} obs ({df.index[0].date()} to {df.index[-1].date()})")
print(f"  VIX range: {df['vix_lag'].min():.3f} to {df['vix_lag'].max():.3f}")
print(f"  TS ratio range: {df['ts_ratio_lag'].min():.3f} to {df['ts_ratio_lag'].max():.3f}")
print(f"  Mean TS ratio: {df['ts_ratio_lag'].mean():.3f} (>1 = contango)")

# ============================================================
# 3. Define helper functions
# ============================================================

def ols_predict(X_train, y_train, X_test):
    """OLS with intercept. Returns predictions."""
    X_train_c = np.column_stack([np.ones(len(X_train)), X_train])
    X_test_c = np.column_stack([np.ones(len(X_test)), X_test])
    # Use lstsq for numerical stability
    coefs, _, _, _ = np.linalg.lstsq(X_train_c, y_train, rcond=None)
    return X_test_c @ coefs, coefs

def qlike_loss(y_true, y_pred):
    """QLIKE loss: sum(log(pred^2) + true^2/pred^2). Lower is better."""
    # Work with variance (squared)
    y_true_var = y_true ** 2
    y_pred_var = np.maximum(y_pred ** 2, 1e-10)  # Floor to avoid log(0)
    return np.mean(np.log(y_pred_var) + y_true_var / y_pred_var)

def dm_test_hac(loss1, loss2, max_lag=22):
    """
    Diebold-Mariano test with Newey-West HAC standard errors.
    H0: loss1 = loss2. Negative t => model 2 is better.
    """
    d = loss1 - loss2  # loss differential
    n = len(d)
    d_mean = np.mean(d)

    # Newey-West HAC variance
    gamma0 = np.mean((d - d_mean) ** 2)
    hac_var = gamma0
    for lag in range(1, max_lag + 1):
        w = 1 - lag / (max_lag + 1)  # Bartlett kernel
        gamma_lag = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        hac_var += 2 * w * gamma_lag

    hac_var = max(hac_var, 1e-20)  # Floor
    t_stat = d_mean / np.sqrt(hac_var / n)
    p_value = stats.t.sf(abs(t_stat), df=n-1) * 2  # two-sided

    return t_stat, p_value

def mz_r2(y_true, y_pred):
    """Mincer-Zarnowitz R²: regress true on predicted."""
    slope, intercept, r_value, _, _ = stats.linregress(y_pred, y_true)
    return r_value ** 2, slope, intercept

# ============================================================
# 4. Rolling 252-day OLS evaluation
# ============================================================
print("\n[3/6] Rolling 252-day OLS evaluation...")

train_window = 252
results_list = []

for i in range(train_window, len(df)):
    train_slice = df.iloc[i - train_window:i]
    test_row = df.iloc[i:i+1]

    y_train = train_slice['rv_22d'].values
    X1_train = train_slice[['vix_lag']].values
    X2_train = train_slice[['vix_lag', 'ts_ratio_lag']].values

    y_test = test_row['rv_22d'].values[0]
    X1_test = test_row[['vix_lag']].values
    X2_test = test_row[['vix_lag', 'ts_ratio_lag']].values

    # Stage 1: VIX-only
    pred1, coefs1 = ols_predict(X1_train, y_train, X1_test)
    pred1 = max(pred1[0], 0.01)  # Floor predictions

    # Stage 2: VIX + TS ratio
    pred2, coefs2 = ols_predict(X2_train, y_train, X2_test)
    pred2 = max(pred2[0], 0.01)

    # QLIKE loss per observation
    ql1 = np.log(pred1**2) + y_test**2 / pred1**2
    ql2 = np.log(pred2**2) + y_test**2 / pred2**2

    results_list.append({
        'date': df.index[i],
        'rv_true': y_test,
        'pred_vix_only': pred1,
        'pred_vix_ts': pred2,
        'qlike_vix_only': ql1,
        'qlike_vix_ts': ql2,
        'c_coef': coefs2[2],  # TS ratio coefficient
        'b_coef_m1': coefs1[1],  # VIX coef in model 1
        'b_coef_m2': coefs2[1],  # VIX coef in model 2
    })

results_df = pd.DataFrame(results_list)
results_df.set_index('date', inplace=True)

print(f"  Rolling predictions: {len(results_df)} obs")
print(f"  Period: {results_df.index[0].date()} to {results_df.index[-1].date()}")

# ============================================================
# 5. Full-sample rolling results
# ============================================================
print("\n[4/6] Full-sample rolling results...")

full_qlike1 = results_df['qlike_vix_only'].mean()
full_qlike2 = results_df['qlike_vix_ts'].mean()
full_improvement = (full_qlike1 - full_qlike2) / abs(full_qlike1) * 100

full_dm_t, full_dm_p = dm_test_hac(
    results_df['qlike_vix_only'].values,
    results_df['qlike_vix_ts'].values,
    max_lag=22
)

full_r2_m1, _, _ = mz_r2(results_df['rv_true'].values, results_df['pred_vix_only'].values)
full_r2_m2, _, _ = mz_r2(results_df['rv_true'].values, results_df['pred_vix_ts'].values)

mean_c = results_df['c_coef'].mean()
std_c = results_df['c_coef'].std()
pct_negative_c = (results_df['c_coef'] < 0).mean() * 100

print(f"\n  === Full-Sample Rolling Results ===")
print(f"  QLIKE (VIX-only):     {full_qlike1:.6f}")
print(f"  QLIKE (VIX+TS):       {full_qlike2:.6f}")
print(f"  QLIKE improvement:    {full_improvement:+.2f}%")
print(f"  DM t-stat (HAC):      {full_dm_t:.3f} (p={full_dm_p:.4f})")
print(f"  Harvey threshold:     {'PASS' if abs(full_dm_t) > 3.0 else 'FAIL'} (need |t|>3.0)")
print(f"  MZ R² (VIX-only):     {full_r2_m1:.4f}")
print(f"  MZ R² (VIX+TS):       {full_r2_m2:.4f}")
print(f"  R² improvement:       {(full_r2_m2 - full_r2_m1)*100:+.2f}pp")
print(f"  TS ratio coef (c):")
print(f"    Mean:    {mean_c:.4f}")
print(f"    Std:     {std_c:.4f}")
print(f"    % negative: {pct_negative_c:.1f}%")

# ============================================================
# 6. 5-Period Cross-Validation (K266 protocol)
# ============================================================
print("\n[5/6] 5-Period Cross-Validation (K266 protocol)...")

# Define ~4-year periods based on available data
all_dates = results_df.index
start_date = all_dates[0]
end_date = all_dates[-1]
total_days = (end_date - start_date).days

# Create 5 roughly equal periods
period_boundaries = pd.date_range(start=start_date, end=end_date, periods=6)
periods = []
for i in range(5):
    p_start = period_boundaries[i]
    p_end = period_boundaries[i + 1]
    mask = (results_df.index >= p_start) & (results_df.index < p_end)
    if i == 4:  # Last period includes end
        mask = (results_df.index >= p_start) & (results_df.index <= p_end)
    period_data = results_df[mask]
    if len(period_data) > 0:
        periods.append({
            'label': f"P{i+1}: {period_data.index[0].strftime('%Y-%m')} to {period_data.index[-1].strftime('%Y-%m')}",
            'start': period_data.index[0],
            'end': period_data.index[-1],
            'data': period_data
        })

print(f"\n  {'Period':<45} {'N':>5} {'QLIKE_imp':>10} {'DM_t':>8} {'DM_p':>8} {'c_sign':>8} {'c_mean':>10}")
print("  " + "-" * 100)

period_results = []
n_qlike_improved = 0
c_signs = []

for p in periods:
    pdata = p['data']
    n = len(pdata)

    # QLIKE
    ql1 = pdata['qlike_vix_only'].mean()
    ql2 = pdata['qlike_vix_ts'].mean()
    ql_imp = (ql1 - ql2) / abs(ql1) * 100

    # DM test
    dm_t, dm_p = dm_test_hac(
        pdata['qlike_vix_only'].values,
        pdata['qlike_vix_ts'].values,
        max_lag=22
    )

    # Coefficient sign
    c_mean = pdata['c_coef'].mean()
    c_sign = "+" if c_mean > 0 else "-"
    c_signs.append(c_sign)

    improved = ql_imp > 0
    if improved:
        n_qlike_improved += 1

    period_results.append({
        'label': p['label'],
        'n': n,
        'qlike_improvement_pct': ql_imp,
        'dm_t': dm_t,
        'dm_p': dm_p,
        'c_mean': c_mean,
        'c_sign': c_sign,
        'qlike_improved': improved,
    })

    imp_marker = "+" if improved else " "
    print(f"  {p['label']:<45} {n:>5} {ql_imp:>+9.2f}% {dm_t:>8.3f} {dm_p:>8.4f} {c_sign:>8} {c_mean:>+10.4f} {imp_marker}")

# ============================================================
# 7. Validation verdict (K266 criteria)
# ============================================================
print("\n[6/6] Validation Verdict (K266 Protocol)")
print("=" * 70)

# Criterion 1: 3+/5 QLIKE improvement
criterion1 = n_qlike_improved >= 3
print(f"\n  Criterion 1: QLIKE improvement in 3+/5 periods")
print(f"    Result: {n_qlike_improved}/5 periods improved")
print(f"    Verdict: {'PASS' if criterion1 else 'FAIL'}")

# Criterion 2: Consistent c sign across periods
unique_signs = set(c_signs)
criterion2 = len(unique_signs) == 1
print(f"\n  Criterion 2: Consistent TS ratio coefficient sign")
print(f"    Signs by period: {c_signs}")
print(f"    Verdict: {'PASS (all ' + c_signs[0] + ')' if criterion2 else 'FAIL (mixed signs: ' + str(c_signs) + ')'}")

# Criterion 3: Pooled DM passes Harvey
criterion3 = abs(full_dm_t) > 3.0
print(f"\n  Criterion 3: Pooled DM test passes Harvey (|t| > 3.0)")
print(f"    Pooled DM t = {full_dm_t:.3f}")
print(f"    Verdict: {'PASS' if criterion3 else 'FAIL'}")

# Overall
all_pass = criterion1 and criterion2 and criterion3
print(f"\n  {'='*50}")
print(f"  OVERALL: {'ALL CRITERIA PASS — K369 SURVIVES' if all_pass else 'VALIDATION FAILED — K369 IS AN ARTIFACT'}")
print(f"  {'='*50}")

# Additional diagnostics
print("\n  Additional Diagnostics:")
print(f"    Full-sample QLIKE improvement: {full_improvement:+.2f}%")
print(f"    Full-sample R² improvement: {(full_r2_m2 - full_r2_m1)*100:+.2f}pp")
print(f"    TS ratio coef stability (CV): {abs(std_c/mean_c):.2f}" if mean_c != 0 else "    TS ratio coef stability: undefined (mean=0)")
print(f"    % of days c < 0: {pct_negative_c:.1f}%")

# Merge ts_ratio_lag from original df for regime analysis
common_regime_idx = results_df.index.intersection(df.index)
results_df2 = results_df.loc[common_regime_idx].copy()
results_df2['ts_ratio_lag'] = df.loc[common_regime_idx, 'ts_ratio_lag']
contango_mask = results_df2['ts_ratio_lag'] > 1.0

contango_data = results_df2[contango_mask]
backwardation_data = results_df2[~contango_mask]

if len(contango_data) > 50 and len(backwardation_data) > 50:
    ql_imp_contango = ((contango_data['qlike_vix_only'].mean() - contango_data['qlike_vix_ts'].mean())
                       / abs(contango_data['qlike_vix_only'].mean()) * 100)
    ql_imp_backwd = ((backwardation_data['qlike_vix_only'].mean() - backwardation_data['qlike_vix_ts'].mean())
                     / abs(backwardation_data['qlike_vix_only'].mean()) * 100)

    dm_t_cont, dm_p_cont = dm_test_hac(
        contango_data['qlike_vix_only'].values,
        contango_data['qlike_vix_ts'].values,
        max_lag=22
    )
    dm_t_back, dm_p_back = dm_test_hac(
        backwardation_data['qlike_vix_only'].values,
        backwardation_data['qlike_vix_ts'].values,
        max_lag=22
    )

    print(f"\n  Regime Decomposition:")
    print(f"    Contango (VIX3M>VIX, n={len(contango_data)}):")
    print(f"      QLIKE improvement: {ql_imp_contango:+.2f}%, DM t={dm_t_cont:.3f}")
    print(f"    Backwardation (VIX3M<VIX, n={len(backwardation_data)}):")
    print(f"      QLIKE improvement: {ql_imp_backwd:+.2f}%, DM t={dm_t_back:.3f}")

# ============================================================
# Save results
# ============================================================
output = {
    'experiment': 'K370',
    'title': 'VIX Term Structure Rolling Validation (K266 Protocol)',
    'timestamp': datetime.now().isoformat(),
    'data_source': 'yfinance: ^VIX, ^VIX3M, SPY',
    'data_period': f"{df.index[0].date()} to {df.index[-1].date()}",
    'n_observations': len(df),
    'n_rolling_predictions': len(results_df),
    'methodology': {
        'rolling_window': 252,
        'target': 'RV_22d (annualized)',
        'model1': 'RV = a + b*VIX_lag',
        'model2': 'RV = a + b*VIX_lag + c*TS_ratio_lag',
        'ts_ratio': 'VIX3M/VIX',
        'dm_test': 'Newey-West HAC (max_lag=22)',
        'validation': 'K266 5-period cross-validation',
    },
    'full_sample': {
        'qlike_vix_only': float(full_qlike1),
        'qlike_vix_ts': float(full_qlike2),
        'qlike_improvement_pct': float(full_improvement),
        'dm_t_stat': float(full_dm_t),
        'dm_p_value': float(full_dm_p),
        'passes_harvey': bool(abs(full_dm_t) > 3.0),
        'mz_r2_vix_only': float(full_r2_m1),
        'mz_r2_vix_ts': float(full_r2_m2),
        'r2_improvement_pp': float((full_r2_m2 - full_r2_m1) * 100),
        'ts_coef_mean': float(mean_c),
        'ts_coef_std': float(std_c),
        'pct_negative_c': float(pct_negative_c),
    },
    'period_results': [
        {
            'label': pr['label'],
            'n': pr['n'],
            'qlike_improvement_pct': float(pr['qlike_improvement_pct']),
            'dm_t': float(pr['dm_t']),
            'dm_p': float(pr['dm_p']),
            'c_mean': float(pr['c_mean']),
            'c_sign': pr['c_sign'],
            'qlike_improved': pr['qlike_improved'],
        }
        for pr in period_results
    ],
    'validation_criteria': {
        'criterion_1_qlike_3of5': bool(criterion1),
        'criterion_1_count': n_qlike_improved,
        'criterion_2_consistent_sign': bool(criterion2),
        'criterion_2_signs': c_signs,
        'criterion_3_pooled_harvey': bool(criterion3),
        'criterion_3_dm_t': float(full_dm_t),
        'all_pass': bool(all_pass),
    },
    'verdict': 'K369 SURVIVES — all criteria pass' if all_pass else 'K369 IS AN ARTIFACT — validation failed',
}

output_path = 'experiments/k370_vix_ts_validation_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print("\n" + "=" * 70)
print(f"K370 COMPLETE: {'K369 SURVIVES' if all_pass else 'K369 IS AN ARTIFACT'}")
print("=" * 70)
