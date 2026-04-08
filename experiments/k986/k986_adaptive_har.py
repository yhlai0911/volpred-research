"""
K986: Adaptive Multi-Factor HAR — Dynamic Factor Selection
==========================================================

Background:
- Standard HAR uses 3 fixed components (1d, 5d, 22d squared returns)
- K969 found HAR-Bespoke (equal-weight vol proxies + HAR structure) is best
- K987 found VIX² has significant incremental value (OOS R²=0.258)
- This experiment tests whether dynamic factor selection (LASSO/Ridge/ElasticNet)
  outperforms fixed-factor HAR models

Method:
- 10 candidate factors (all shift(1) to avoid lookahead)
- Models: HAR-3, HAR-10 (OLS), HAR-LASSO, HAR-Ridge, HAR-ElasticNet, Rolling HAR-LASSO
- IS: 2006-2018, OOS: 2019-2026
- Evaluation: QLIKE, MSE, OOS R², DM test, MZ regression

Data source: yfinance (SPY, ^VIX)
Reference: Cinquetti et al. (FoFI 2026), Corsi (2009), Patton (2011)
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import os
from datetime import datetime

np.random.seed(42)
warnings.filterwarnings('ignore')

# sklearn imports
from sklearn.linear_model import LassoCV, RidgeCV, ElasticNetCV, LinearRegression
from sklearn.preprocessing import StandardScaler
from scipy import stats

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 60)
print("K986: Adaptive Multi-Factor HAR")
print("=" * 60)

print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

print(f"  SPY: {len(spy)} days ({spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')})")
print(f"  VIX: {len(vix)} days ({vix.index[0].strftime('%Y-%m-%d')} to {vix.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 2. Feature Construction
# ============================================================
print("\n[2] Constructing features...")

# Log returns
spy['log_ret'] = np.log(spy['Close'] / spy['Close'].shift(1))

# Target: r² (squared return) as daily vol proxy
spy['r2'] = spy['log_ret'] ** 2

# Factor 1: r²_t (lag-1 squared return)
spy['f_r2'] = spy['r2'].shift(1)

# Factor 2: r²_{t,5} (5-day avg)
spy['f_r2_5'] = spy['r2'].rolling(5).mean().shift(1)

# Factor 3: r²_{t,22} (22-day avg)
spy['f_r2_22'] = spy['r2'].rolling(22).mean().shift(1)

# Factor 4: |r_t| (absolute return)
spy['f_abs_ret'] = spy['log_ret'].abs().shift(1)

# Factor 5: Parkinson range-based vol
spy['f_parkinson'] = (np.log(spy['High'] / spy['Low']) ** 2 / (4 * np.log(2))).shift(1)

# Factor 6: Garman-Klass vol
u = np.log(spy['High'] / spy['Open'])
d = np.log(spy['Low'] / spy['Open'])
c = np.log(spy['Close'] / spy['Open'])
spy['f_gk'] = (0.5 * (u - d) ** 2 - (2 * np.log(2) - 1) * c ** 2).shift(1)

# Factor 7: VIX daily vol (VIX / sqrt(252))
vix_daily = vix['Close'] / 100.0 / np.sqrt(252)
spy['f_vix_daily'] = vix_daily.reindex(spy.index).shift(1)

# Factor 8: VIX² (quadratic, K987 finding)
spy['f_vix2'] = ((vix['Close'].reindex(spy.index) / 100.0) ** 2).shift(1)

# Factor 9: Leverage term r_t * I(r_t < 0) * |r_t|
spy['f_leverage'] = (spy['log_ret'] * (spy['log_ret'] < 0).astype(float) * spy['log_ret'].abs()).shift(1)

# Factor 10: RV 66-day (quarterly avg)
spy['f_r2_66'] = spy['r2'].rolling(66).mean().shift(1)

# All factor names
FACTOR_NAMES = [
    'f_r2', 'f_r2_5', 'f_r2_22', 'f_abs_ret', 'f_parkinson',
    'f_gk', 'f_vix_daily', 'f_vix2', 'f_leverage', 'f_r2_66'
]
FACTOR_LABELS = [
    'r²(1d)', 'r²(5d)', 'r²(22d)', '|r|(1d)', 'Parkinson',
    'GK', 'VIX/√252', 'VIX²', 'Leverage', 'r²(66d)'
]

# Drop NaN
df = spy[['r2'] + FACTOR_NAMES].dropna()
print(f"  Complete observations: {len(df)} ({df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')})")
print(f"  Factors: {len(FACTOR_NAMES)}")

# ============================================================
# 3. IS/OOS Split
# ============================================================
print("\n[3] IS/OOS split...")
is_end = '2018-12-31'
oos_start = '2019-01-01'

df_is = df.loc[:is_end]
df_oos = df.loc[oos_start:]

print(f"  IS: {len(df_is)} days ({df_is.index[0].strftime('%Y-%m-%d')} to {df_is.index[-1].strftime('%Y-%m-%d')})")
print(f"  OOS: {len(df_oos)} days ({df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')})")

y_is = df_is['r2'].values
X_is = df_is[FACTOR_NAMES].values

y_oos = df_oos['r2'].values
X_oos = df_oos[FACTOR_NAMES].values

# HAR-3 factors only
HAR3_COLS = ['f_r2', 'f_r2_5', 'f_r2_22']
X_is_har3 = df_is[HAR3_COLS].values
X_oos_har3 = df_oos[HAR3_COLS].values

# ============================================================
# 4. Model Estimation & OOS Prediction
# ============================================================
print("\n[4] Estimating models...")

results = {}

# --- HAR-3: Standard HAR (OLS) ---
print("  HAR-3 (OLS)...")
lr_har3 = LinearRegression()
lr_har3.fit(X_is_har3, y_is)
pred_har3 = lr_har3.predict(X_oos_har3)
pred_har3 = np.maximum(pred_har3, 1e-10)  # floor
results['HAR-3'] = {
    'predictions': pred_har3,
    'coefs': dict(zip(HAR3_COLS, lr_har3.coef_.tolist())),
    'intercept': float(lr_har3.intercept_),
    'n_factors': 3
}
print(f"    R²(IS) = {lr_har3.score(X_is_har3, y_is):.4f}")

# --- HAR-10: All 10 factors (OLS) ---
print("  HAR-10 (OLS)...")
lr_har10 = LinearRegression()
lr_har10.fit(X_is, y_is)
pred_har10 = lr_har10.predict(X_oos)
pred_har10 = np.maximum(pred_har10, 1e-10)
results['HAR-10'] = {
    'predictions': pred_har10,
    'coefs': dict(zip(FACTOR_NAMES, lr_har10.coef_.tolist())),
    'intercept': float(lr_har10.intercept_),
    'n_factors': 10
}
print(f"    R²(IS) = {lr_har10.score(X_is, y_is):.4f}")

# --- HAR-LASSO ---
print("  HAR-LASSO (LassoCV)...")
scaler = StandardScaler()
X_is_scaled = scaler.fit_transform(X_is)
X_oos_scaled = scaler.transform(X_oos)

lasso = LassoCV(cv=5, max_iter=10000, random_state=42)
lasso.fit(X_is_scaled, y_is)
pred_lasso = lasso.predict(X_oos_scaled)
pred_lasso = np.maximum(pred_lasso, 1e-10)

lasso_selected = [FACTOR_LABELS[i] for i in range(len(FACTOR_NAMES)) if abs(lasso.coef_[i]) > 1e-8]
lasso_coefs = {FACTOR_LABELS[i]: float(lasso.coef_[i]) for i in range(len(FACTOR_NAMES))}

results['HAR-LASSO'] = {
    'predictions': pred_lasso,
    'coefs': lasso_coefs,
    'alpha': float(lasso.alpha_),
    'selected_factors': lasso_selected,
    'n_factors': len(lasso_selected)
}
print(f"    alpha = {lasso.alpha_:.6f}, selected {len(lasso_selected)} factors: {lasso_selected}")

# --- HAR-Ridge ---
print("  HAR-Ridge (manual implementation)...")
# Manual Ridge regression to avoid sklearn version compatibility issues

def ridge_fit(X, y, alpha):
    """Manual Ridge: beta = (X'X + alpha*I)^{-1} X'y"""
    n, p = X.shape
    XtX = X.T @ X
    Xty = X.T @ y
    beta = np.linalg.solve(XtX + alpha * np.eye(p), Xty)
    return beta

def ridge_predict(X, beta, intercept):
    return X @ beta + intercept

# Manual 5-fold CV for alpha selection
from sklearn.model_selection import KFold
kf = KFold(n_splits=5, shuffle=False)

best_alpha_ridge = None
best_score_ridge = np.inf  # MSE, lower is better
for alpha_val in np.logspace(-4, 4, 50):
    fold_mses = []
    for train_idx, val_idx in kf.split(X_is_scaled):
        X_tr, X_val = X_is_scaled[train_idx], X_is_scaled[val_idx]
        y_tr, y_val = y_is[train_idx], y_is[val_idx]
        # Center y for intercept
        y_mean = y_tr.mean()
        beta = ridge_fit(X_tr, y_tr - y_mean, alpha_val)
        pred_val = X_val @ beta + y_mean
        fold_mses.append(np.mean((y_val - pred_val) ** 2))
    mean_mse = np.mean(fold_mses)
    if mean_mse < best_score_ridge:
        best_score_ridge = mean_mse
        best_alpha_ridge = alpha_val

# Fit on full IS
y_mean_is = y_is.mean()
ridge_beta = ridge_fit(X_is_scaled, y_is - y_mean_is, best_alpha_ridge)
ridge_intercept = y_mean_is

pred_ridge = X_oos_scaled @ ridge_beta + ridge_intercept
pred_ridge = np.maximum(pred_ridge, 1e-10)

ridge_coefs = {FACTOR_LABELS[i]: float(ridge_beta[i]) for i in range(len(FACTOR_NAMES))}

class _RidgeResult:
    def __init__(self, coef, alpha):
        self.coef_ = coef
        self.alpha_ = alpha

ridge = _RidgeResult(ridge_beta, best_alpha_ridge)

results['HAR-Ridge'] = {
    'predictions': pred_ridge,
    'coefs': ridge_coefs,
    'alpha': float(best_alpha_ridge),
    'n_factors': 10  # Ridge keeps all
}
print(f"    alpha = {best_alpha_ridge:.4f}")

# --- HAR-ElasticNet ---
print("  HAR-ElasticNet (ElasticNetCV)...")
enet = ElasticNetCV(cv=5, l1_ratio=[0.1, 0.3, 0.5, 0.7, 0.9], max_iter=10000, random_state=42)
enet.fit(X_is_scaled, y_is)
pred_enet = enet.predict(X_oos_scaled)
pred_enet = np.maximum(pred_enet, 1e-10)

enet_selected = [FACTOR_LABELS[i] for i in range(len(FACTOR_NAMES)) if abs(enet.coef_[i]) > 1e-8]
enet_coefs = {FACTOR_LABELS[i]: float(enet.coef_[i]) for i in range(len(FACTOR_NAMES))}

results['HAR-ElasticNet'] = {
    'predictions': pred_enet,
    'coefs': enet_coefs,
    'alpha': float(enet.alpha_),
    'l1_ratio': float(enet.l1_ratio_),
    'selected_factors': enet_selected,
    'n_factors': len(enet_selected)
}
print(f"    alpha = {enet.alpha_:.6f}, l1_ratio = {enet.l1_ratio_:.2f}, selected {len(enet_selected)} factors: {enet_selected}")

# --- Rolling HAR-LASSO ---
print("  Rolling HAR-LASSO (refit every 252 days, window=3000)...")
rolling_window = 3000
refit_interval = 252

# We need the full dataset for rolling
all_X = df[FACTOR_NAMES].values
all_y = df['r2'].values
all_dates = df.index

# Find OOS start index
oos_idx_start = df.index.get_loc(df_oos.index[0])
n_total = len(df)
n_oos = len(df_oos)

pred_rolling = np.full(n_oos, np.nan)
factor_selection_history = []  # For heatmap

last_fit_idx = -refit_interval  # Force initial fit
current_model = None
current_scaler = None

for i in range(n_oos):
    t = oos_idx_start + i

    # Refit?
    if i - last_fit_idx >= refit_interval or current_model is None:
        # Training window
        train_start = max(0, t - rolling_window)
        train_end = t

        X_train = all_X[train_start:train_end]
        y_train = all_y[train_start:train_end]

        sc = StandardScaler()
        X_train_sc = sc.fit_transform(X_train)

        model = LassoCV(cv=5, max_iter=10000, random_state=42)
        model.fit(X_train_sc, y_train)

        current_model = model
        current_scaler = sc
        last_fit_idx = i

        selected = [FACTOR_LABELS[j] for j in range(len(FACTOR_NAMES)) if abs(model.coef_[j]) > 1e-8]
        coef_dict = {FACTOR_LABELS[j]: float(model.coef_[j]) for j in range(len(FACTOR_NAMES))}

        factor_selection_history.append({
            'date': str(all_dates[t]),
            'alpha': float(model.alpha_),
            'selected': selected,
            'n_selected': len(selected),
            'coefs': coef_dict
        })

    # Predict
    x_test = all_X[t:t+1]
    x_test_sc = current_scaler.transform(x_test)
    pred_rolling[i] = max(current_model.predict(x_test_sc)[0], 1e-10)

results['Rolling-LASSO'] = {
    'predictions': pred_rolling,
    'factor_selection_history': factor_selection_history,
    'n_refits': len(factor_selection_history),
    'rolling_window': rolling_window,
    'refit_interval': refit_interval
}
print(f"    {len(factor_selection_history)} refits over OOS period")

# --- GJR-GARCH baseline ---
print("  GJR-GARCH baseline...")
try:
    from arch import arch_model
    am = arch_model(spy['log_ret'].dropna() * 100, vol='GARCH', p=1, o=1, q=1, dist='normal', mean='Constant')
    res_gjr = am.fit(last_obs=is_end, disp='off')

    # OOS forecast (1-step ahead, rolling)
    gjr_forecasts = []
    ret_series = spy['log_ret'].dropna() * 100
    oos_dates_gjr = df_oos.index

    for dt in oos_dates_gjr:
        try:
            forecast = res_gjr.forecast(horizon=1, start=dt, reindex=False)
            var_forecast = forecast.variance.iloc[0, 0] / 10000  # back to decimal
            gjr_forecasts.append(max(var_forecast, 1e-10))
        except:
            gjr_forecasts.append(np.nan)

    pred_gjr = np.array(gjr_forecasts)

    # Handle any NaN with forward fill
    valid_mask = ~np.isnan(pred_gjr)
    if not valid_mask.all():
        pred_gjr_series = pd.Series(pred_gjr).ffill().bfill()
        pred_gjr = pred_gjr_series.values

    results['GJR-GARCH'] = {
        'predictions': pred_gjr,
        'n_factors': 3,  # omega, alpha+gamma, beta
        'params': {k: float(v) for k, v in res_gjr.params.items()}
    }
    print(f"    Params: {dict(res_gjr.params.round(6))}")
except Exception as e:
    print(f"    GJR-GARCH failed: {e}")
    results['GJR-GARCH'] = None

# ============================================================
# 5. Evaluation
# ============================================================
print("\n[5] Evaluating models...")

def qlike(actual, predicted):
    """QLIKE loss: log(h) + y/h, with robust floor"""
    # Use a floor based on 1% of the mean actual value to avoid extreme QLIKE
    floor = max(np.mean(actual) * 0.01, 1e-8)
    h = np.maximum(predicted, floor)
    y = np.maximum(actual, 1e-10)
    return np.mean(np.log(h) + y / h)

def mse(actual, predicted):
    return np.mean((actual - predicted) ** 2)

def oos_r2(actual, predicted):
    """OOS R² = 1 - MSE(model) / MSE(historical mean)"""
    ss_res = np.sum((actual - predicted) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    return 1 - ss_res / ss_tot

def mz_regression(actual, predicted):
    """Mincer-Zarnowitz regression: y = a + b*h + e"""
    X_mz = np.column_stack([np.ones(len(predicted)), predicted])
    beta = np.linalg.lstsq(X_mz, actual, rcond=None)[0]
    residuals = actual - X_mz @ beta
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    r2 = 1 - ss_res / ss_tot
    return {'intercept': float(beta[0]), 'slope': float(beta[1]), 'R2': float(r2)}

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test (QLIKE loss differential)"""
    d = e1 - e2
    n = len(d)
    d_mean = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0
    for k in range(1, h):
        gamma_k = np.sum((d[k:] - d_mean) * (d[:-k] - d_mean)) / n
        var_d += 2 * (1 - k / h) * gamma_k

    se = np.sqrt(var_d / n)
    if se < 1e-15:
        return 0.0, 1.0

    dm_stat = d_mean / se
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)

eval_results = {}
model_names = ['HAR-3', 'HAR-10', 'HAR-LASSO', 'HAR-Ridge', 'HAR-ElasticNet', 'Rolling-LASSO']
if results.get('GJR-GARCH') is not None:
    model_names.append('GJR-GARCH')

# Compute QLIKE losses for each model (for DM test)
qlike_losses = {}

for name in model_names:
    pred = results[name]['predictions']
    valid = ~np.isnan(pred)
    y_valid = y_oos[valid]
    p_valid = pred[valid]

    q = qlike(y_valid, p_valid)
    m = mse(y_valid, p_valid)
    r2_val = oos_r2(y_valid, p_valid)
    mz = mz_regression(y_valid, p_valid)

    # Individual QLIKE losses for DM test (robust floor)
    floor = max(np.mean(y_valid) * 0.01, 1e-8)
    h = np.maximum(p_valid, floor)
    y_safe = np.maximum(y_valid, 1e-10)
    qlike_losses[name] = np.log(h) + y_safe / h

    # Count negative predictions
    n_neg = int(np.sum(results[name]['predictions'][valid] < 0))

    eval_results[name] = {
        'QLIKE': q,
        'MSE': m,
        'OOS_R2': r2_val,
        'MZ_intercept': mz['intercept'],
        'MZ_slope': mz['slope'],
        'MZ_R2': mz['R2'],
        'n_factors': results[name].get('n_factors', 'N/A'),
        'n_valid': int(np.sum(valid)),
        'n_negative_predictions': n_neg
    }

    neg_info = ""
    if n_neg > 0:
        pct_neg = n_neg / np.sum(valid) * 100
        neg_info = f"  [!{n_neg} neg pred ({pct_neg:.1f}%)]"
    print(f"  {name:20s}: QLIKE={q:.6f}  MSE={m:.2e}  OOS R²={r2_val:.4f}  MZ(a={mz['intercept']:.2e}, b={mz['slope']:.4f}, R²={mz['R2']:.4f}){neg_info}")

# DM tests vs HAR-3
print("\n  DM tests vs HAR-3 (negative = better than HAR-3):")
dm_results = {}
baseline_loss = qlike_losses['HAR-3']

for name in model_names:
    if name == 'HAR-3':
        continue
    model_loss = qlike_losses[name]
    # Align lengths
    n_min = min(len(baseline_loss), len(model_loss))
    dm_stat, dm_pval = dm_test(model_loss[:n_min], baseline_loss[:n_min])
    dm_results[name] = {'DM_stat': dm_stat, 'DM_pval': dm_pval}
    sig = '***' if dm_pval < 0.01 else '**' if dm_pval < 0.05 else '*' if dm_pval < 0.10 else ''
    print(f"    {name:20s}: DM={dm_stat:+.4f}  p={dm_pval:.4f} {sig}")
    eval_results[name]['DM_vs_HAR3_stat'] = dm_stat
    eval_results[name]['DM_vs_HAR3_pval'] = dm_pval

# ============================================================
# 6. Factor Selection Analysis
# ============================================================
print("\n[6] Factor selection analysis...")

# LASSO selected factors
print(f"  Static LASSO selected: {results['HAR-LASSO']['selected_factors']}")
print(f"  Static ElasticNet selected: {results['HAR-ElasticNet']['selected_factors']}")

# Rolling LASSO selection frequency
if results['Rolling-LASSO']['factor_selection_history']:
    selection_freq = {label: 0 for label in FACTOR_LABELS}
    n_refits = len(results['Rolling-LASSO']['factor_selection_history'])

    for entry in results['Rolling-LASSO']['factor_selection_history']:
        for f in entry['selected']:
            selection_freq[f] += 1

    print(f"\n  Rolling LASSO factor selection frequency ({n_refits} refits):")
    for label in FACTOR_LABELS:
        pct = selection_freq[label] / n_refits * 100
        bar = '#' * int(pct / 5)
        print(f"    {label:12s}: {selection_freq[label]:2d}/{n_refits} ({pct:5.1f}%) {bar}")

    eval_results['factor_selection_frequency'] = {
        label: {'count': selection_freq[label], 'pct': round(selection_freq[label] / n_refits * 100, 1)}
        for label in FACTOR_LABELS
    }

# ============================================================
# 7. Plots
# ============================================================
print("\n[7] Generating plots...")

# --- Plot 1: Factor Selection Heatmap ---
fig, ax = plt.subplots(figsize=(14, 6))

if results['Rolling-LASSO']['factor_selection_history']:
    history = results['Rolling-LASSO']['factor_selection_history']
    n_refits = len(history)

    # Build selection matrix
    selection_matrix = np.zeros((len(FACTOR_LABELS), n_refits))
    refit_dates = []

    for j, entry in enumerate(history):
        refit_dates.append(pd.Timestamp(entry['date']))
        for f in entry['selected']:
            idx = FACTOR_LABELS.index(f)
            # Use absolute coefficient value for intensity
            coef_val = abs(entry['coefs'].get(f, 0))
            selection_matrix[idx, j] = coef_val if coef_val > 0 else 0

    # Normalize each row for visibility
    for i in range(len(FACTOR_LABELS)):
        row_max = selection_matrix[i].max()
        if row_max > 0:
            selection_matrix[i] /= row_max

    im = ax.imshow(selection_matrix, aspect='auto', cmap='YlOrRd', interpolation='nearest')
    ax.set_yticks(range(len(FACTOR_LABELS)))
    ax.set_yticklabels(FACTOR_LABELS, fontsize=10)
    ax.set_xlabel('Refit Period', fontsize=12)
    ax.set_title('K986: Rolling LASSO Factor Selection (Normalized |Coefficient|)', fontsize=14)

    # X-axis labels
    if len(refit_dates) > 1:
        tick_positions = list(range(0, len(refit_dates), max(1, len(refit_dates) // 8)))
        ax.set_xticks(tick_positions)
        ax.set_xticklabels([refit_dates[p].strftime('%Y-%m') for p in tick_positions], rotation=45, ha='right')

    plt.colorbar(im, ax=ax, label='Normalized |Coefficient|')

plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k986_factor_selection.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k986_factor_selection.png")

# --- Plot 2: OOS Comparison ---
fig, axes = plt.subplots(2, 2, figsize=(16, 10))

# 2a: QLIKE comparison
ax = axes[0, 0]
model_order = ['HAR-3', 'HAR-10', 'HAR-LASSO', 'HAR-Ridge', 'HAR-ElasticNet', 'Rolling-LASSO']
if 'GJR-GARCH' in eval_results:
    model_order.append('GJR-GARCH')
qlikes = [eval_results[m]['QLIKE'] for m in model_order]
colors = ['#2196F3' if m == 'HAR-3' else '#4CAF50' if 'LASSO' in m or 'Ridge' in m or 'Elastic' in m else '#FF9800' for m in model_order]
bars = ax.bar(range(len(model_order)), qlikes, color=colors)
ax.set_xticks(range(len(model_order)))
ax.set_xticklabels(model_order, rotation=45, ha='right', fontsize=9)
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('OOS QLIKE Comparison')
ax.axhline(y=qlikes[0], color='blue', linestyle='--', alpha=0.5, label='HAR-3 baseline')
ax.legend(fontsize=8)

# 2b: OOS R²
ax = axes[0, 1]
r2s = [eval_results[m]['OOS_R2'] for m in model_order]
bars = ax.bar(range(len(model_order)), r2s, color=colors)
ax.set_xticks(range(len(model_order)))
ax.set_xticklabels(model_order, rotation=45, ha='right', fontsize=9)
ax.set_ylabel('OOS R²')
ax.set_title('OOS R² Comparison')
ax.axhline(y=0, color='red', linestyle='--', alpha=0.3)

# 2c: Factor importance (Ridge coefficients, scaled)
ax = axes[1, 0]
ridge_coefs_vals = [abs(results['HAR-Ridge']['coefs'][label]) for label in FACTOR_LABELS]
sorted_idx = np.argsort(ridge_coefs_vals)[::-1]
ax.barh(range(len(FACTOR_LABELS)), [ridge_coefs_vals[i] for i in sorted_idx], color='#9C27B0')
ax.set_yticks(range(len(FACTOR_LABELS)))
ax.set_yticklabels([FACTOR_LABELS[i] for i in sorted_idx], fontsize=9)
ax.set_xlabel('|Coefficient| (scaled)')
ax.set_title('Ridge Factor Importance')

# 2d: Rolling LASSO alpha over time
ax = axes[1, 1]
if results['Rolling-LASSO']['factor_selection_history']:
    history = results['Rolling-LASSO']['factor_selection_history']
    dates_alpha = [pd.Timestamp(e['date']) for e in history]
    alphas = [e['alpha'] for e in history]
    n_selected = [e['n_selected'] for e in history]

    ax2 = ax.twinx()
    ax.plot(dates_alpha, alphas, 'b-o', markersize=4, label='LASSO alpha')
    ax2.plot(dates_alpha, n_selected, 'r-s', markersize=4, label='# factors selected')

    ax.set_xlabel('Date')
    ax.set_ylabel('LASSO alpha', color='b')
    ax2.set_ylabel('# Factors Selected', color='r')
    ax.set_title('Rolling LASSO: Alpha & Factor Count Over Time')
    ax.legend(loc='upper left', fontsize=8)
    ax2.legend(loc='upper right', fontsize=8)

plt.suptitle('K986: Adaptive Multi-Factor HAR — OOS Evaluation', fontsize=14, y=1.02)
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k986_oos_comparison.png'), dpi=150, bbox_inches='tight')
plt.close()
print("  Saved k986_oos_comparison.png")

# ============================================================
# 8. Save Results JSON
# ============================================================
print("\n[8] Saving results...")

# Build clean results dict (no numpy arrays)
save_results = {
    'experiment_id': 'K986',
    'title': 'Adaptive Multi-Factor HAR — Dynamic Factor Selection',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'is_period': f"{df_is.index[0].strftime('%Y-%m-%d')} to {df_is.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{df_oos.index[0].strftime('%Y-%m-%d')} to {df_oos.index[-1].strftime('%Y-%m-%d')}",
    'n_is': len(df_is),
    'n_oos': len(df_oos),
    'n_factors': len(FACTOR_NAMES),
    'factor_list': FACTOR_LABELS,
    'seed': 42,
    'references': [
        'Corsi (2009) - HAR-RV model',
        'Cinquetti et al. (FoFI 2026) - Multi-factor HAR with 287 HF factors',
        'Patton (2011) - QLIKE loss function',
        'Harvey (2016) - t>3.0 threshold'
    ],
    'models': {},
    'evaluation': eval_results,
    'dm_tests_vs_HAR3': dm_results,
    'factor_selection': {
        'static_lasso': {
            'selected': results['HAR-LASSO'].get('selected_factors', []),
            'alpha': results['HAR-LASSO'].get('alpha'),
            'coefs': results['HAR-LASSO'].get('coefs', {})
        },
        'static_elasticnet': {
            'selected': results['HAR-ElasticNet'].get('selected_factors', []),
            'alpha': results['HAR-ElasticNet'].get('alpha'),
            'l1_ratio': results['HAR-ElasticNet'].get('l1_ratio'),
            'coefs': results['HAR-ElasticNet'].get('coefs', {})
        },
        'rolling_lasso': {
            'n_refits': results['Rolling-LASSO']['n_refits'],
            'window': results['Rolling-LASSO']['rolling_window'],
            'refit_interval': results['Rolling-LASSO']['refit_interval'],
            'history': results['Rolling-LASSO']['factor_selection_history']
        }
    }
}

# Add model-specific info (without predictions array)
for name in model_names:
    model_info = {k: v for k, v in results[name].items() if k != 'predictions' and k != 'factor_selection_history'}
    save_results['models'][name] = model_info

# Ranking
ranking = sorted(eval_results.items(),
                 key=lambda x: x[1]['QLIKE'] if isinstance(x[1], dict) and 'QLIKE' in x[1] else float('inf'))
save_results['ranking_by_QLIKE'] = [
    {'rank': i+1, 'model': name, 'QLIKE': data['QLIKE'], 'OOS_R2': data['OOS_R2']}
    for i, (name, data) in enumerate(ranking)
    if isinstance(data, dict) and 'QLIKE' in data
]

# Conclusions
best_model = ranking[0][0] if ranking else 'N/A'
best_qlike = ranking[0][1]['QLIKE'] if ranking else float('nan')
har3_qlike = eval_results['HAR-3']['QLIKE']
improvement = (har3_qlike - best_qlike) / har3_qlike * 100

save_results['conclusions'] = {
    'best_model': best_model,
    'best_QLIKE': best_qlike,
    'HAR3_QLIKE': har3_qlike,
    'improvement_pct': round(improvement, 2),
    'adaptive_better_than_fixed': best_model in ['HAR-LASSO', 'HAR-Ridge', 'HAR-ElasticNet', 'Rolling-LASSO'],
    'vix2_consistently_selected': 'VIX²' in results['HAR-LASSO'].get('selected_factors', []),
    'summary': f"Best model: {best_model} (QLIKE={best_qlike:.6f}), {improvement:.1f}% improvement over HAR-3"
}

with open(os.path.join(OUTPUT_DIR, 'k986_adaptive_har_results.json'), 'w') as f:
    json.dump(save_results, f, indent=2, default=str)
print("  Saved k986_adaptive_har_results.json")

# ============================================================
# 9. Summary
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"\nRanking by QLIKE (lower = better):")
for i, (name, data) in enumerate(ranking):
    if isinstance(data, dict) and 'QLIKE' in data:
        dm_info = ""
        if name in dm_results:
            dm = dm_results[name]
            sig = '***' if dm['DM_pval'] < 0.01 else '**' if dm['DM_pval'] < 0.05 else '*' if dm['DM_pval'] < 0.10 else 'ns'
            dm_info = f"  DM vs HAR-3: {dm['DM_stat']:+.3f} ({sig})"
        print(f"  {i+1}. {name:20s}: QLIKE={data['QLIKE']:.6f}  OOS R²={data['OOS_R2']:.4f}  MZ R²={data['MZ_R2']:.4f}{dm_info}")

print(f"\nBest model: {best_model}")
print(f"Improvement over HAR-3: {improvement:.1f}%")
print(f"Adaptive methods {'DO' if save_results['conclusions']['adaptive_better_than_fixed'] else 'do NOT'} outperform fixed HAR-3")
print(f"VIX² consistently selected by LASSO: {save_results['conclusions']['vix2_consistently_selected']}")

print("\nStatic LASSO factors:", results['HAR-LASSO'].get('selected_factors', []))
print("Static ElasticNet factors:", results['HAR-ElasticNet'].get('selected_factors', []))

print("\n[DONE] K986 complete.")
