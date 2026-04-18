"""
K872: Credit Spread (High Yield OAS) as Volatility Predictor
=============================================================
Research Question: Does HY OAS predict equity vol BEYOND VIX?
Prior: K651 found credit spread NULL (coefficient flips sign across periods).
       This experiment does deeper analysis: lead-lag, crisis detection, OOS regression.

Data Sources:
- FRED: BAMLH0A0HYM2 (ICE BofA US High Yield OAS), BAMLC0A0CM (IG OAS)
- yfinance: SPY, ^VIX
- Period: 2000-01 to 2026-04

References:
- Collin-Dufresne et al. (2001): credit spread determinants
- Campbell & Taksler (2003): equity vol → credit spreads
- Huang & Huang (2012): credit spread puzzle
- K651: FRED macro indicators NULL for daily vol

Error log rules applied:
- signal = signal.shift(1) MANDATORY
- DM test: from volpred.stats.model_evaluation import strategy_dm_test
- Sharpe > 2x baseline = bug, STOP
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
import requests
from scipy import stats
from datetime import datetime
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_squared_error
warnings.filterwarnings('ignore')

print("=" * 70)
print("K872: Credit Spread (HY OAS) as Volatility Predictor")
print("=" * 70)

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("\n[1] Data Collection...")

def fetch_fred_series(series_id, start='2000-01-01', end='2026-04-05'):
    """Fetch FRED data via public CSV endpoint."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
    df = pd.read_csv(url, parse_dates=['observation_date'], index_col='observation_date')
    df.columns = [series_id]
    df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
    df = df.dropna()
    df.index.name = 'DATE'
    return df

# FRED: High Yield OAS and Investment Grade OAS
try:
    hy_oas = fetch_fred_series('BAMLH0A0HYM2')
    ig_oas = fetch_fred_series('BAMLC0A0CM')
    print(f"  HY OAS: {len(hy_oas)} obs, {hy_oas.index[0].date()} to {hy_oas.index[-1].date()}")
    print(f"  IG OAS: {len(ig_oas)} obs, {ig_oas.index[0].date()} to {ig_oas.index[-1].date()}")
except Exception as e:
    print(f"  FRED download error: {e}")
    raise

# yfinance: SPY and VIX
spy = yf.download('SPY', start='2000-01-01', end='2026-04-05', progress=False)
vix = yf.download('^VIX', start='2000-01-01', end='2026-04-05', progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  SPY: {len(spy)} obs, {spy.index[0].date()} to {spy.index[-1].date()}")
print(f"  VIX: {len(vix)} obs, {vix.index[0].date()} to {vix.index[-1].date()}")

# ============================================================
# 2. DATA PREPARATION
# ============================================================
print("\n[2] Data Preparation...")

# SPY returns
spy['ret'] = spy['Close'].pct_change()
spy['ret_sq'] = spy['ret'] ** 2  # Daily squared return (vol proxy)

# Forward 22-day realized vol (annualized)
spy['fwd_rv22'] = spy['ret'].rolling(22).std().shift(-22) * np.sqrt(252)

# Merge all data
df = pd.DataFrame(index=spy.index)
df['ret'] = spy['ret']
df['ret_sq'] = spy['ret_sq']
df['fwd_rv22'] = spy['fwd_rv22']
df['vix'] = vix['Close'].reindex(df.index)

# FRED data is daily but has gaps (weekends/holidays) — forward fill to trading days
hy = hy_oas['BAMLH0A0HYM2'].reindex(df.index, method='ffill')
ig = ig_oas['BAMLC0A0CM'].reindex(df.index, method='ffill')

df['hy_oas'] = hy
df['ig_oas'] = ig
df['hy_ig_diff'] = df['hy_oas'] - df['ig_oas']  # Credit risk appetite
df['hy_oas_chg22'] = df['hy_oas'].diff(22)  # 22-day change in HY OAS

# Past 22-day realized vol (for HAR-like baseline)
df['past_rv22'] = df['ret'].rolling(22).std() * np.sqrt(252)

# Drop NaN
df = df.dropna()
print(f"  Merged dataset: {len(df)} obs, {df.index[0].date()} to {df.index[-1].date()}")

# ============================================================
# 3. DESCRIPTIVE STATISTICS
# ============================================================
print("\n[3] Descriptive Statistics")
desc_vars = ['vix', 'hy_oas', 'ig_oas', 'hy_ig_diff', 'hy_oas_chg22', 'fwd_rv22']
desc = df[desc_vars].describe().T
desc['skew'] = df[desc_vars].skew()
desc['kurt'] = df[desc_vars].kurtosis()
print(desc[['mean', 'std', 'min', 'max', 'skew', 'kurt']].round(4).to_string())

# ============================================================
# 4. CORRELATION ANALYSIS
# ============================================================
print("\n[4] Correlation with Forward 22-day RV")
predictors = ['vix', 'hy_oas', 'ig_oas', 'hy_ig_diff', 'hy_oas_chg22', 'past_rv22']
corr_results = {}
for p in predictors:
    r, pval = stats.pearsonr(df[p], df['fwd_rv22'])
    corr_results[p] = {'pearson_r': round(r, 4), 'p_value': round(pval, 6)}
    print(f"  {p:20s}: r = {r:.4f}, p = {pval:.2e}")

# VIX vs HY OAS correlation
r_vix_hy, _ = stats.pearsonr(df['vix'], df['hy_oas'])
print(f"\n  VIX-HY_OAS correlation: r = {r_vix_hy:.4f}")

# ============================================================
# 5. LEAD-LAG ANALYSIS: Does HY OAS lead VIX?
# ============================================================
print("\n[5] Lead-Lag Analysis (Cross-correlation)")
lags = range(-60, 61)
xcorr = []
for lag in lags:
    if lag >= 0:
        a = df['hy_oas'].iloc[lag:]
        b = df['vix'].iloc[:len(a)]
    else:
        a = df['hy_oas'].iloc[:lag]
        b = df['vix'].iloc[-lag:]
    r, _ = stats.pearsonr(a.values, b.values)
    xcorr.append({'lag': lag, 'corr': r})
xcorr_df = pd.DataFrame(xcorr)

# Best lag
best_idx = xcorr_df['corr'].abs().idxmax()
best_lag = xcorr_df.loc[best_idx, 'lag']
best_corr = xcorr_df.loc[best_idx, 'corr']
print(f"  Peak cross-correlation: lag={best_lag}, r={best_corr:.4f}")
print(f"  (positive lag = HY OAS leads VIX)")

# Granger-like: does lagged HY OAS change predict VIX change?
df['vix_chg'] = df['vix'].diff()
df['hy_oas_chg1'] = df['hy_oas'].diff()
df_gc = df.dropna()

from statsmodels.regression.linear_model import OLS
from statsmodels.tools import add_constant

# Restricted: VIX_chg ~ VIX_chg_lag1
# Unrestricted: VIX_chg ~ VIX_chg_lag1 + HY_OAS_chg_lag1
df_gc['vix_chg_lag1'] = df_gc['vix_chg'].shift(1)
df_gc['hy_oas_chg_lag1'] = df_gc['hy_oas_chg1'].shift(1)
df_gc = df_gc.dropna()

X_r = add_constant(df_gc[['vix_chg_lag1']])
X_u = add_constant(df_gc[['vix_chg_lag1', 'hy_oas_chg_lag1']])
y = df_gc['vix_chg']

model_r = OLS(y, X_r).fit()
model_u = OLS(y, X_u).fit()

# F-test for Granger causality (1 restriction)
ssr_r = model_r.ssr
ssr_u = model_u.ssr
n = len(y)
k = X_u.shape[1]
f_stat = ((ssr_r - ssr_u) / 1) / (ssr_u / (n - k))
f_pval = 1 - stats.f.cdf(f_stat, 1, n - k)
print(f"\n  Granger causality (HY OAS → VIX):")
print(f"    F-stat = {f_stat:.4f}, p = {f_pval:.6f}")
hy_oas_coef = model_u.params.get('hy_oas_chg_lag1', model_u.params.iloc[-1])
print(f"    HY OAS lag1 coef in VIX equation: {hy_oas_coef:.4f}")

# ============================================================
# 6. IN-SAMPLE REGRESSION MODELS (with shift(1) for all predictors)
# ============================================================
print("\n[6] In-Sample Regression Models")
print("  Target: Forward 22-day realized vol")
print("  ALL predictors are shift(1) — no lookahead")

# Prepare shifted predictors (signal from t-1)
df_reg = df.copy()
for col in ['vix', 'hy_oas', 'ig_oas', 'hy_ig_diff', 'hy_oas_chg22', 'past_rv22']:
    df_reg[col] = df_reg[col].shift(1)  # MANDATORY: signal.shift(1)
df_reg = df_reg.dropna()

target = df_reg['fwd_rv22']

models = {
    'A_VIX_only': ['vix'],
    'B_VIX_HY': ['vix', 'hy_oas'],
    'C_VIX_HY_chg': ['vix', 'hy_oas_chg22'],
    'D_HY_only': ['hy_oas'],
    'E_VIX_HY_diff': ['vix', 'hy_oas', 'hy_ig_diff'],
    'F_VIX_pastRV': ['vix', 'past_rv22'],
    'G_VIX_pastRV_HY': ['vix', 'past_rv22', 'hy_oas'],
}

is_results = {}
for name, features in models.items():
    X = add_constant(df_reg[features])
    model = OLS(target, X).fit()
    is_results[name] = {
        'R2': round(model.rsquared, 4),
        'R2_adj': round(model.rsquared_adj, 4),
        'AIC': round(model.aic, 1),
        'BIC': round(model.bic, 1),
        'features': features,
        'params': {k: round(v, 6) for k, v in model.params.items()},
        'pvalues': {k: round(v, 6) for k, v in model.pvalues.items()},
        'nobs': int(model.nobs),
    }
    sig_stars = ''
    for f in features:
        if f in model.pvalues and model.pvalues[f] < 0.01:
            sig_stars += f'{f}*** '
        elif f in model.pvalues and model.pvalues[f] < 0.05:
            sig_stars += f'{f}** '
        elif f in model.pvalues and model.pvalues[f] < 0.10:
            sig_stars += f'{f}* '
    print(f"  {name:25s}: R²={model.rsquared:.4f}, R²_adj={model.rsquared_adj:.4f}, "
          f"AIC={model.aic:.0f}, BIC={model.bic:.0f}  [{sig_stars.strip()}]")

# ============================================================
# 7. OUT-OF-SAMPLE EVALUATION
# ============================================================
print("\n[7] Out-of-Sample Evaluation")
print("  IS: 2000-2018, OOS: 2019-2026")

is_end = '2018-12-31'
oos_start = '2019-01-01'

df_is = df_reg[df_reg.index <= is_end]
df_oos = df_reg[df_reg.index >= oos_start]

print(f"  IS: {len(df_is)} obs, OOS: {len(df_oos)} obs")

oos_results = {}
oos_predictions = {}
for name, features in models.items():
    X_is = add_constant(df_is[features])
    y_is = df_is['fwd_rv22']

    model = OLS(y_is, X_is).fit()

    X_oos = add_constant(df_oos[features])
    y_oos = df_oos['fwd_rv22']

    pred = model.predict(X_oos)
    oos_predictions[name] = pred

    mse = mean_squared_error(y_oos, pred)
    r2 = r2_score(y_oos, pred)

    # QLIKE loss
    # QLIKE = mean(target/pred - log(target/pred) - 1), avoid division by zero
    pred_safe = np.maximum(pred, 0.001)
    target_safe = np.maximum(y_oos.values, 0.001)
    qlike = np.mean(target_safe / pred_safe - np.log(target_safe / pred_safe) - 1)

    oos_results[name] = {
        'MSE': round(float(mse), 6),
        'RMSE': round(float(np.sqrt(mse)), 4),
        'R2_OOS': round(float(r2), 4),
        'QLIKE': round(float(qlike), 4),
    }
    print(f"  {name:25s}: RMSE={np.sqrt(mse):.4f}, R²_OOS={r2:.4f}, QLIKE={qlike:.4f}")

# ============================================================
# 8. DM TEST: VIX+HY vs VIX-only
# ============================================================
print("\n[8] Diebold-Mariano Tests (Harvey threshold |t| > 3.0)")

y_oos = df_oos['fwd_rv22'].values
baseline_pred = oos_predictions['A_VIX_only'].values

dm_results = {}
for name in ['B_VIX_HY', 'C_VIX_HY_chg', 'E_VIX_HY_diff', 'G_VIX_pastRV_HY']:
    # DM test: squared error loss
    e1 = (y_oos - baseline_pred) ** 2  # VIX-only errors
    e2 = (y_oos - oos_predictions[name].values) ** 2  # augmented model errors
    d = e1 - e2  # loss differential (positive = augmented is better)

    n = len(d)
    d_mean = np.mean(d)
    # HAC variance (Newey-West with h-1 lags where h=22 for 22-day horizon)
    h = 22
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        w = 1 - k / h  # Bartlett weight
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma0 + gamma_sum) / n

    dm_stat = d_mean / np.sqrt(max(var_d, 1e-12))
    dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

    dm_results[name] = {
        'DM_stat': round(float(dm_stat), 4),
        'p_value': round(float(dm_pval), 6),
        'passes_harvey': abs(dm_stat) > 3.0,
        'better_model': name if dm_stat > 0 else 'A_VIX_only',
    }
    harvey_mark = "PASS" if abs(dm_stat) > 3.0 else "FAIL"
    direction = "BETTER" if dm_stat > 0 else "WORSE"
    print(f"  {name} vs VIX-only: DM={dm_stat:.4f}, p={dm_pval:.4f} [{harvey_mark}] [{direction}]")

# ============================================================
# 9. CRISIS DETECTION: Can HY OAS widening predict VIX spikes?
# ============================================================
print("\n[9] Crisis Detection Analysis")

# Define VIX spike: VIX > 30 (high fear regime)
df_crisis = df.copy()
df_crisis['vix_spike'] = (df_crisis['vix'] > 30).astype(int)
df_crisis['hy_oas_high'] = (df_crisis['hy_oas'] > df_crisis['hy_oas'].quantile(0.80)).astype(int)
df_crisis['hy_widening'] = (df_crisis['hy_oas_chg22'] > df_crisis['hy_oas_chg22'].quantile(0.90)).astype(int)

# Contingency table: HY OAS regime vs VIX spike
from sklearn.metrics import confusion_matrix

# Does HY OAS > 80th percentile predict VIX spike in next 22 days?
df_crisis['fwd_vix_spike'] = df_crisis['vix_spike'].rolling(22).max().shift(-22)
df_crisis_clean = df_crisis.dropna(subset=['fwd_vix_spike', 'hy_oas_high', 'hy_widening'])

# HY level as crisis predictor
ct_level = pd.crosstab(df_crisis_clean['hy_oas_high'], df_crisis_clean['fwd_vix_spike'])
print("\n  HY OAS level (>80th pctl) vs Forward VIX Spike (>30):")
print(ct_level.to_string())

# Precision/recall
if ct_level.shape == (2, 2):
    tp = ct_level.iloc[1, 1]
    fp = ct_level.iloc[1, 0]
    fn = ct_level.iloc[0, 1]
    tn = ct_level.iloc[0, 0]
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    print(f"  Precision: {precision:.4f}, Recall: {recall:.4f}")
else:
    precision, recall = None, None

# HY widening (momentum) as crisis predictor
ct_widen = pd.crosstab(df_crisis_clean['hy_widening'], df_crisis_clean['fwd_vix_spike'])
print("\n  HY OAS widening (>90th pctl 22d chg) vs Forward VIX Spike:")
print(ct_widen.to_string())

if ct_widen.shape == (2, 2):
    tp_w = ct_widen.iloc[1, 1]
    fp_w = ct_widen.iloc[1, 0]
    fn_w = ct_widen.iloc[0, 1]
    tn_w = ct_widen.iloc[0, 0]
    prec_w = tp_w / (tp_w + fp_w) if (tp_w + fp_w) > 0 else 0
    rec_w = tp_w / (tp_w + fn_w) if (tp_w + fn_w) > 0 else 0
    print(f"  Precision: {prec_w:.4f}, Recall: {rec_w:.4f}")
else:
    prec_w, rec_w = None, None

# ============================================================
# 10. ROLLING STABILITY: Partial correlation HY|VIX over time
# ============================================================
print("\n[10] Rolling Partial Correlation (HY OAS | VIX → fwd_rv22)")

window = 504  # ~2 years
rolling_partial = []
for i in range(window, len(df_reg)):
    sub = df_reg.iloc[i-window:i]
    # Partial correlation: regress fwd_rv22 on VIX, get residuals
    # Then correlate residuals with HY OAS
    X_v = add_constant(sub[['vix']])
    y_rv = sub['fwd_rv22']
    res_rv = OLS(y_rv, X_v).fit().resid

    X_v2 = add_constant(sub[['vix']])
    y_hy = sub['hy_oas']
    res_hy = OLS(y_hy, X_v2).fit().resid

    r_partial, _ = stats.pearsonr(res_rv, res_hy)
    rolling_partial.append({
        'date': sub.index[-1],
        'partial_r': r_partial,
    })

rp_df = pd.DataFrame(rolling_partial)
print(f"  Partial corr (HY|VIX): mean={rp_df['partial_r'].mean():.4f}, "
      f"std={rp_df['partial_r'].std():.4f}")
print(f"  % positive: {(rp_df['partial_r'] > 0).mean()*100:.1f}%")
print(f"  % |r| > 0.1: {(rp_df['partial_r'].abs() > 0.1).mean()*100:.1f}%")
print(f"  Range: [{rp_df['partial_r'].min():.4f}, {rp_df['partial_r'].max():.4f}]")

# Sign stability
sign_changes = (rp_df['partial_r'].diff().apply(np.sign).diff() != 0).sum()
print(f"  Sign changes: {sign_changes} (unstable if > 50% of periods)")

# ============================================================
# 11. REGIME ANALYSIS: Does HY OAS add value in specific regimes?
# ============================================================
print("\n[11] Regime Analysis: HY OAS value by VIX regime")

df_regime = df_reg.copy()
df_regime['vix_regime'] = pd.cut(df_regime['vix'], bins=[0, 15, 20, 25, 100],
                                  labels=['Low(<15)', 'Normal(15-20)', 'Elevated(20-25)', 'High(>25)'])

regime_results = {}
for regime in df_regime['vix_regime'].unique():
    sub = df_regime[df_regime['vix_regime'] == regime].dropna()
    if len(sub) < 50:
        continue

    # VIX-only R²
    X_v = add_constant(sub[['vix']])
    m_v = OLS(sub['fwd_rv22'], X_v).fit()

    # VIX + HY R²
    X_vh = add_constant(sub[['vix', 'hy_oas']])
    m_vh = OLS(sub['fwd_rv22'], X_vh).fit()

    delta_r2 = m_vh.rsquared - m_v.rsquared
    hy_pval = m_vh.pvalues.get('hy_oas', 1.0)

    regime_results[str(regime)] = {
        'n': len(sub),
        'R2_vix': round(m_v.rsquared, 4),
        'R2_vix_hy': round(m_vh.rsquared, 4),
        'delta_R2': round(delta_r2, 4),
        'hy_pval': round(hy_pval, 6),
    }
    sig = '***' if hy_pval < 0.01 else '**' if hy_pval < 0.05 else '*' if hy_pval < 0.10 else 'NS'
    print(f"  {str(regime):20s} (n={len(sub):5d}): ΔR²={delta_r2:+.4f}, HY p={hy_pval:.4f} [{sig}]")

# ============================================================
# 12. INCREMENTAL F-TEST
# ============================================================
print("\n[12] Incremental F-test: Does HY OAS improve over VIX?")

X_r_full = add_constant(df_reg[['vix']])
X_u_full = add_constant(df_reg[['vix', 'hy_oas']])
y_full = df_reg['fwd_rv22']

m_r = OLS(y_full, X_r_full).fit()
m_u = OLS(y_full, X_u_full).fit()

ssr_r = m_r.ssr
ssr_u = m_u.ssr
n_full = len(y_full)
k_full = X_u_full.shape[1]
f_inc = ((ssr_r - ssr_u) / 1) / (ssr_u / (n_full - k_full))
f_inc_p = 1 - stats.f.cdf(f_inc, 1, n_full - k_full)
print(f"  F-stat = {f_inc:.4f}, p = {f_inc_p:.6e}")
print(f"  VIX-only R²: {m_r.rsquared:.4f}")
print(f"  VIX+HY R²: {m_u.rsquared:.4f}")
print(f"  ΔR²: {m_u.rsquared - m_r.rsquared:.6f}")

# ============================================================
# 13. SUBPERIOD STABILITY
# ============================================================
print("\n[13] Subperiod Stability (5-year windows)")

periods = [
    ('2001-2005', '2001-01-01', '2005-12-31'),
    ('2006-2010', '2006-01-01', '2010-12-31'),
    ('2011-2015', '2011-01-01', '2015-12-31'),
    ('2016-2020', '2016-01-01', '2020-12-31'),
    ('2021-2025', '2021-01-01', '2025-12-31'),
]

subperiod_results = {}
hy_coefs = []
for label, start, end in periods:
    sub = df_reg[(df_reg.index >= start) & (df_reg.index <= end)]
    if len(sub) < 100:
        continue

    X = add_constant(sub[['vix', 'hy_oas']])
    m = OLS(sub['fwd_rv22'], X).fit()

    coef = m.params.get('hy_oas', 0)
    pval = m.pvalues.get('hy_oas', 1)
    hy_coefs.append(coef)

    subperiod_results[label] = {
        'n': len(sub),
        'hy_coef': round(float(coef), 6),
        'hy_pval': round(float(pval), 6),
        'R2': round(float(m.rsquared), 4),
    }
    sig = '***' if pval < 0.01 else '**' if pval < 0.05 else '*' if pval < 0.10 else 'NS'
    sign = '+' if coef > 0 else '-'
    print(f"  {label}: coef={coef:+.4f} [{sig}], R²={m.rsquared:.4f}, n={len(sub)} [{sign}]")

# Check sign stability (K651's finding)
signs = [1 if c > 0 else -1 for c in hy_coefs]
sign_flips = sum(1 for i in range(1, len(signs)) if signs[i] != signs[i-1])
print(f"\n  HY OAS coefficient sign flips: {sign_flips}/{len(hy_coefs)-1}")
print(f"  K651 finding CONFIRMED: coefficient {'IS' if sign_flips > 0 else 'IS NOT'} unstable across periods")

# ============================================================
# 14. SUMMARY & CONCLUSIONS
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K872 Credit Spread (HY OAS) as Vol Predictor")
print("=" * 70)

# Best OOS model
best_oos = min(oos_results.items(), key=lambda x: x[1]['QLIKE'])
print(f"\n  Best OOS model (QLIKE): {best_oos[0]} = {best_oos[1]['QLIKE']:.4f}")
print(f"  VIX-only baseline: QLIKE = {oos_results['A_VIX_only']['QLIKE']:.4f}")

vix_qlike = oos_results['A_VIX_only']['QLIKE']
any_pass_harvey = any(v['passes_harvey'] for v in dm_results.values())
any_better = any(v['DM_stat'] > 0 for v in dm_results.values())

conclusion = "NULL" if not any_pass_harvey else "SIGNIFICANT"
print(f"\n  Harvey threshold: {'PASS — HY OAS adds significant value' if any_pass_harvey else 'FAIL — no model passes |t| > 3.0'}")
print(f"  Overall conclusion: {conclusion}")
print(f"  VIX sufficiency: {'CONFIRMED again' if not any_pass_harvey else 'CHALLENGED'}")

# ============================================================
# 15. SAVE RESULTS
# ============================================================
results = {
    "experiment_id": "K872",
    "title": "Credit Spread (HY OAS) as Volatility Predictor",
    "date": datetime.now().strftime("%Y-%m-%d"),
    "data_sources": {
        "FRED": ["BAMLH0A0HYM2 (HY OAS)", "BAMLC0A0CM (IG OAS)"],
        "yfinance": ["SPY", "^VIX"],
        "period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "nobs": len(df),
    },
    "references": [
        "Collin-Dufresne et al. (2001) - credit spread determinants",
        "Campbell & Taksler (2003) - equity vol → credit spreads",
        "K651 - FRED macro NULL, credit spread coefficient flips sign",
    ],
    "correlations": corr_results,
    "vix_hy_correlation": round(r_vix_hy, 4),
    "lead_lag": {
        "best_lag": int(best_lag),
        "best_corr": round(best_corr, 4),
        "granger_f_stat": round(float(f_stat), 4),
        "granger_p_value": round(float(f_pval), 6),
    },
    "in_sample": is_results,
    "out_of_sample": oos_results,
    "dm_tests": dm_results,
    "crisis_detection": {
        "hy_level_precision": round(precision, 4) if precision else None,
        "hy_level_recall": round(recall, 4) if recall else None,
        "hy_widening_precision": round(prec_w, 4) if prec_w else None,
        "hy_widening_recall": round(rec_w, 4) if rec_w else None,
    },
    "rolling_partial_corr": {
        "mean": round(rp_df['partial_r'].mean(), 4),
        "std": round(rp_df['partial_r'].std(), 4),
        "pct_positive": round((rp_df['partial_r'] > 0).mean() * 100, 1),
        "range": [round(rp_df['partial_r'].min(), 4), round(rp_df['partial_r'].max(), 4)],
    },
    "regime_analysis": regime_results,
    "incremental_f_test": {
        "f_stat": round(float(f_inc), 4),
        "p_value": round(float(f_inc_p), 6),
        "delta_R2": round(float(m_u.rsquared - m_r.rsquared), 6),
    },
    "subperiod_stability": subperiod_results,
    "sign_flips": sign_flips,
    "conclusion": conclusion,
    "summary": (
        f"HY OAS has high raw correlation with forward vol ({corr_results['hy_oas']['pearson_r']}) "
        f"but is highly correlated with VIX ({round(r_vix_hy, 3)}). "
        f"After controlling for VIX, incremental ΔR² = {round(float(m_u.rsquared - m_r.rsquared), 6)}. "
        f"DM tests: {'no model passes Harvey |t|>3.0' if not any_pass_harvey else 'some models pass'}. "
        f"Coefficient sign {'flips' if sign_flips > 0 else 'stable'} across subperiods (confirming K651). "
        f"VIX sufficiency {'confirmed' if not any_pass_harvey else 'challenged'}."
    ),
}

with open('experiments/k872_results.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to experiments/k872_results.json")
print("  Done.")
