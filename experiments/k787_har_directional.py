"""
K787: HAR Directional Volatility Prediction
============================================
Can we predict whether volatility goes UP or DOWN?

Context:
- K697: VIX predicts vol magnitude (corr 0.57) but NOT direction (corr 0.04)
- K782: GJR beats HAR on r² magnitude forecasting
- Literature: Applied Economics Letters 2024 — HAR for directional RV prediction

Target Variable:
  Direction_t = 1 if RV_5d(t) > RV_5d(t-5) else 0 (weekly vol went UP)
  RV_5d = sum of r²(t-4:t) — 5-day realized variance from daily squared returns

Models:
  1. HAR-Direction: Logistic regression with HAR features (RV_d, RV_5d, RV_22d, VIX)
  2. VIX-Direction: VIX above median → predict vol UP
  3. Momentum-Direction: If RV increased last week → predict increase this week
  4. Random Forest: Same HAR features, classification
  5. Naive: Always predict majority class

CRITICAL: signal.shift(1) — predict direction at t using features at t-1

Data: SPY + ^VIX from yfinance, 2006-01-01 ~ latest
OOS: 2023-01-01 ~ 2024-12-31
Expanding window, retrain every 63 trading days

References:
- Patton & Sheppard (2015): Good Volatility, Bad Volatility — directional decomposition
- Applied Economics Letters 2024 — HAR directional RV prediction
- Corsi (2009): HAR model for realized volatility
- Moreira & Muir (2017): Volatility-Managed Portfolios (VT framework)

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
from datetime import datetime
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score, confusion_matrix
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Collection
# ============================================================
print("=" * 70)
print("K787: HAR Directional Volatility Prediction")
print("=" * 70)

print("\n[1/6] Downloading data...")
spy_raw = yf.download('SPY', start='2005-01-01', end='2025-01-01', progress=False, auto_adjust=True)
vix_raw = yf.download('^VIX', start='2005-01-01', end='2025-01-01', progress=False, auto_adjust=True)

# Handle multi-level columns if present
if isinstance(spy_raw.columns, pd.MultiIndex):
    spy_raw.columns = spy_raw.columns.get_level_values(0)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)

spy = spy_raw.copy()

# Daily returns (auto_adjust=True means Close is already adjusted)
spy['ret'] = spy['Close'].pct_change()
spy['ret_sq'] = spy['ret'] ** 2  # Daily squared return (proxy for daily RV)

# Merge VIX
spy['VIX'] = vix_raw['Close']
spy = spy.dropna(subset=['ret', 'VIX'])

print(f"  SPY data: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"  Total observations: {len(spy)}")

# ============================================================
# 2. Feature Engineering
# ============================================================
print("\n[2/6] Engineering features...")

# Realized Variance at different horizons
spy['RV_1d'] = spy['ret_sq']  # Daily RV proxy
spy['RV_5d'] = spy['ret_sq'].rolling(5).sum()    # Weekly RV
spy['RV_22d'] = spy['ret_sq'].rolling(22).sum()   # Monthly RV

# Log RV features (log to reduce skewness, add small constant to avoid log(0))
eps = 1e-10
spy['log_RV_1d'] = np.log(spy['RV_1d'] + eps)
spy['log_RV_5d'] = np.log(spy['RV_5d'] + eps)
spy['log_RV_22d'] = np.log(spy['RV_22d'] + eps)
spy['VIX_scaled'] = spy['VIX'] / 100.0

# Target: Direction of 5-day RV change
# Direction_t = 1 if RV_5d(t) > RV_5d(t-5), else 0
spy['RV_5d_lag5'] = spy['RV_5d'].shift(5)
spy['direction'] = (spy['RV_5d'] > spy['RV_5d_lag5']).astype(int)

# CRITICAL: shift features by 1 day to avoid lookahead bias
# We predict direction at t using features known at t-1
feature_cols = ['log_RV_1d', 'log_RV_5d', 'log_RV_22d', 'VIX_scaled']
for col in feature_cols:
    spy[f'{col}_lag1'] = spy[col].shift(1)

lagged_feature_cols = [f'{col}_lag1' for col in feature_cols]

# Also create momentum feature: was RV increasing last week?
spy['RV_momentum'] = (spy['RV_5d'].shift(1) > spy['RV_5d'].shift(6)).astype(int)

# Drop NaN rows
df = spy.dropna(subset=lagged_feature_cols + ['direction', 'RV_momentum']).copy()
print(f"  Clean observations: {len(df)}")
print(f"  Direction class balance: UP={df['direction'].mean():.3f}, DOWN={1-df['direction'].mean():.3f}")

# ============================================================
# 3. Descriptive Statistics
# ============================================================
print("\n[3/6] Descriptive statistics...")

# Full sample stats
print(f"\n  --- Feature statistics (full sample) ---")
for col in feature_cols:
    vals = df[f'{col}_lag1']
    print(f"  {col:20s}: mean={vals.mean():.4f}, std={vals.std():.4f}, "
          f"skew={vals.skew():.2f}, kurt={vals.kurtosis():.2f}")

# Direction stats by year
yearly_up = df.groupby(df.index.year)['direction'].mean()
print(f"\n  --- Direction = UP proportion by year ---")
for yr, prop in yearly_up.items():
    if yr >= 2006:
        print(f"  {yr}: {prop:.3f}")

# ============================================================
# 4. Model Training & Evaluation (Expanding Window)
# ============================================================
print("\n[4/6] Training models with expanding window...")

# Define OOS period
oos_start = '2023-01-01'
oos_end = '2024-12-31'
oos_mask = (df.index >= oos_start) & (df.index <= oos_end)
oos_dates = df.index[oos_mask]

if len(oos_dates) == 0:
    raise ValueError("No OOS data found!")

print(f"  OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
print(f"  OOS observations: {len(oos_dates)}")

# Storage for predictions
predictions = {
    'HAR_Logistic': [],
    'HAR_Logistic_prob': [],
    'VIX_Direction': [],
    'Momentum': [],
    'Random_Forest': [],
    'Random_Forest_prob': [],
    'Naive': [],
    'actual': [],
    'dates': [],
    'spy_ret': [],  # For economic value calculation
}

# Get indices for expanding window retraining
oos_indices = np.where(oos_mask)[0]
retrain_interval = 63  # Retrain every ~quarter

# Models
har_model = None
rf_model = None
scaler = None
last_train_idx = -retrain_interval  # Force initial training
majority_class = None

# VIX median (computed from training data only)
vix_median = None

for i, oos_idx in enumerate(oos_indices):
    date = df.index[oos_idx]

    # Check if we need to retrain
    if i == 0 or (i - last_train_idx) >= retrain_interval:
        # Training data: everything before this OOS point
        train_mask = np.arange(len(df)) < oos_idx
        X_train = df.iloc[train_mask][lagged_feature_cols].values
        y_train = df.iloc[train_mask]['direction'].values

        # Standardize features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)

        # 1. HAR Logistic Regression
        har_model = LogisticRegression(
            C=1.0, max_iter=1000, random_state=42, solver='lbfgs'
        )
        har_model.fit(X_train_scaled, y_train)

        # 2. Random Forest
        rf_model = RandomForestClassifier(
            n_estimators=100, max_depth=5, random_state=42, n_jobs=-1
        )
        rf_model.fit(X_train_scaled, y_train)

        # 3. Naive: majority class
        majority_class = int(y_train.mean() >= 0.5)

        # 4. VIX median from training data
        vix_median = df.iloc[train_mask]['VIX_scaled'].median() * 100  # Back to VIX level

        last_train_idx = i
        if i == 0:
            print(f"  Initial training: {train_mask.sum()} samples, majority_class={majority_class}")
            print(f"  VIX median (training): {vix_median:.1f}")

    # Get features for this OOS point
    X_test = df.iloc[oos_idx:oos_idx+1][lagged_feature_cols].values
    X_test_scaled = scaler.transform(X_test)
    actual = df.iloc[oos_idx]['direction']
    spy_ret_val = df.iloc[oos_idx]['ret']

    # Model 1: HAR Logistic
    har_pred = har_model.predict(X_test_scaled)[0]
    har_prob = har_model.predict_proba(X_test_scaled)[0, 1]

    # Model 2: VIX Direction (VIX above median → predict UP)
    current_vix = df.iloc[oos_idx - 1]['VIX']  # Use yesterday's VIX (lag!)
    vix_pred = int(current_vix > vix_median)

    # Model 3: Momentum
    mom_pred = int(df.iloc[oos_idx]['RV_momentum'])

    # Model 4: Random Forest
    rf_pred = rf_model.predict(X_test_scaled)[0]
    rf_prob = rf_model.predict_proba(X_test_scaled)[0, 1]

    # Model 5: Naive
    naive_pred = majority_class

    # Store
    predictions['HAR_Logistic'].append(har_pred)
    predictions['HAR_Logistic_prob'].append(har_prob)
    predictions['VIX_Direction'].append(vix_pred)
    predictions['Momentum'].append(mom_pred)
    predictions['Random_Forest'].append(rf_pred)
    predictions['Random_Forest_prob'].append(rf_prob)
    predictions['Naive'].append(naive_pred)
    predictions['actual'].append(int(actual))
    predictions['dates'].append(date.strftime('%Y-%m-%d'))
    predictions['spy_ret'].append(float(spy_ret_val))

# Convert to arrays
for key in predictions:
    if key != 'dates':
        predictions[key] = np.array(predictions[key])

actual = predictions['actual']
print(f"\n  OOS class balance: UP={actual.mean():.3f}, DOWN={1-actual.mean():.3f}")

# ============================================================
# 5. Evaluation
# ============================================================
print("\n[5/6] Evaluating models...")

results = {}
model_names = ['HAR_Logistic', 'VIX_Direction', 'Momentum', 'Random_Forest', 'Naive']

print(f"\n  {'Model':<20s} {'Accuracy':>10s} {'F1':>8s} {'AUC-ROC':>10s} {'Prec(UP)':>10s} {'Rec(UP)':>10s}")
print("  " + "-" * 68)

for name in model_names:
    preds = predictions[name]

    acc = accuracy_score(actual, preds)
    f1 = f1_score(actual, preds, average='binary')

    # AUC-ROC (use probabilities if available)
    if name == 'HAR_Logistic':
        auc = roc_auc_score(actual, predictions['HAR_Logistic_prob'])
    elif name == 'Random_Forest':
        auc = roc_auc_score(actual, predictions['Random_Forest_prob'])
    else:
        auc = roc_auc_score(actual, preds)

    cm = confusion_matrix(actual, preds)
    # Precision and recall for UP class
    tp = cm[1, 1] if cm.shape[0] > 1 else 0
    fp = cm[0, 1] if cm.shape[0] > 1 else 0
    fn = cm[1, 0] if cm.shape[0] > 1 else 0
    prec_up = tp / (tp + fp) if (tp + fp) > 0 else 0
    rec_up = tp / (tp + fn) if (tp + fn) > 0 else 0

    results[name] = {
        'accuracy': float(acc),
        'f1_score': float(f1),
        'auc_roc': float(auc),
        'precision_up': float(prec_up),
        'recall_up': float(rec_up),
        'confusion_matrix': cm.tolist(),
        'n_predict_up': int(preds.sum()),
        'n_predict_down': int(len(preds) - preds.sum()),
    }

    print(f"  {name:<20s} {acc:>10.3f} {f1:>8.3f} {auc:>10.3f} {prec_up:>10.3f} {rec_up:>10.3f}")

# ============================================================
# 5b. Directional accuracy by quintile of actual vol change
# ============================================================
print("\n  --- Accuracy by quintile of actual vol change magnitude ---")

vol_change = df.loc[oos_mask, 'RV_5d'].values - df.loc[oos_mask, 'RV_5d_lag5'].values
quintiles = pd.qcut(vol_change, 5, labels=['Q1(big drop)', 'Q2', 'Q3', 'Q4', 'Q5(big rise)'])

for name in ['HAR_Logistic', 'Random_Forest', 'VIX_Direction']:
    preds = predictions[name]
    print(f"\n  {name}:")
    for q in quintiles.categories:
        q_mask = quintiles == q
        if q_mask.sum() > 0:
            q_acc = accuracy_score(actual[q_mask], preds[q_mask])
            print(f"    {q}: accuracy={q_acc:.3f} (n={q_mask.sum()})")

# ============================================================
# 5c. Rolling accuracy (stability check)
# ============================================================
print("\n  --- Rolling 63-day accuracy ---")
window = 63
for name in ['HAR_Logistic', 'Random_Forest', 'VIX_Direction']:
    preds = predictions[name]
    rolling_acc = []
    for start in range(0, len(actual) - window + 1, window):
        end = start + window
        w_acc = accuracy_score(actual[start:end], preds[start:end])
        rolling_acc.append(w_acc)
    print(f"  {name}: min={min(rolling_acc):.3f}, max={max(rolling_acc):.3f}, "
          f"std={np.std(rolling_acc):.3f}, n_windows={len(rolling_acc)}")
    results[name]['rolling_63d_accuracy'] = {
        'min': float(min(rolling_acc)),
        'max': float(max(rolling_acc)),
        'std': float(np.std(rolling_acc)),
        'values': [float(x) for x in rolling_acc],
    }

# ============================================================
# 5d. Economic value test
# ============================================================
print("\n  --- Economic value test ---")
print("  Strategy: if predict vol UP → hold cash (0%), else → hold SPY (100%)")
print("  (Inverse: high vol = bad for SPY, so avoid)")

spy_oos_ret = predictions['spy_ret']
cum_bh = np.cumprod(1 + spy_oos_ret)[-1] - 1  # Buy & Hold

econ_results = {}
for name in ['HAR_Logistic', 'Random_Forest', 'VIX_Direction', 'Momentum', 'Naive']:
    preds = predictions[name]
    # If predict vol UP → hold cash; if DOWN → hold SPY
    # CRITICAL: preds are already lagged (based on t-1 features)
    strat_ret = spy_oos_ret * (1 - preds)  # 1=UP predicted → 0 weight, 0=DOWN → 1 weight

    cum_strat = np.cumprod(1 + strat_ret)[-1] - 1
    sharpe = np.mean(strat_ret) / np.std(strat_ret) * np.sqrt(252) if np.std(strat_ret) > 0 else 0
    mdd_series = np.cumprod(1 + strat_ret)
    mdd = np.min(mdd_series / np.maximum.accumulate(mdd_series)) - 1

    econ_results[name] = {
        'cumulative_return': float(cum_strat),
        'annualized_sharpe': float(sharpe),
        'max_drawdown': float(mdd),
        'days_invested': int((1 - preds).sum()),
        'days_cash': int(preds.sum()),
    }

    print(f"  {name:<20s}: cum_ret={cum_strat:>7.1%}, Sharpe={sharpe:>6.3f}, "
          f"MDD={mdd:>7.1%}, invested={int((1-preds).sum())}/{len(preds)} days")

print(f"  {'Buy & Hold':<20s}: cum_ret={cum_bh:>7.1%}")
econ_results['Buy_Hold'] = {'cumulative_return': float(cum_bh)}

# Also test: opposite strategy (predict UP → hold SPY, i.e. vol momentum is rewarded)
print("\n  --- Alternative: vol UP → hold SPY (momentum view) ---")
for name in ['HAR_Logistic', 'Random_Forest']:
    preds = predictions[name]
    strat_ret = spy_oos_ret * preds  # 1=UP predicted → invest, 0=DOWN → cash
    cum_strat = np.cumprod(1 + strat_ret)[-1] - 1
    sharpe = np.mean(strat_ret) / np.std(strat_ret) * np.sqrt(252) if np.std(strat_ret) > 0 else 0
    print(f"  {name} (alt):<20s cum_ret={cum_strat:>7.1%}, Sharpe={sharpe:>6.3f}")

# ============================================================
# 5e. Statistical significance tests
# ============================================================
print("\n  --- Statistical significance ---")

# Test: is accuracy significantly > 50%?
from scipy import stats

for name in ['HAR_Logistic', 'Random_Forest', 'VIX_Direction', 'Momentum']:
    preds = predictions[name]
    correct = (preds == actual).astype(int)
    n = len(correct)
    acc = correct.mean()
    # Binomial test: H0: p = 0.5
    # z = (p_hat - 0.5) / sqrt(0.5 * 0.5 / n)
    z = (acc - 0.5) / np.sqrt(0.25 / n)
    p_val = 2 * (1 - stats.norm.cdf(abs(z)))
    sig = "***" if p_val < 0.001 else "**" if p_val < 0.01 else "*" if p_val < 0.05 else "ns"
    print(f"  {name:<20s}: acc={acc:.3f}, z={z:.3f}, p={p_val:.4f} {sig}")
    results[name]['significance'] = {
        'z_stat': float(z),
        'p_value': float(p_val),
        'significant_05': bool(p_val < 0.05),
    }

# Test: HAR vs Naive (McNemar's test)
print("\n  --- McNemar's test (HAR vs Naive) ---")
for name in ['HAR_Logistic', 'Random_Forest', 'VIX_Direction']:
    preds_model = predictions[name]
    preds_naive = predictions['Naive']
    # Contingency: model correct/incorrect vs naive correct/incorrect
    model_correct = (preds_model == actual)
    naive_correct = (preds_naive == actual)

    b = int(np.sum(model_correct & ~naive_correct))  # model right, naive wrong
    c = int(np.sum(~model_correct & naive_correct))  # model wrong, naive right

    if b + c > 0:
        mcnemar_stat = (abs(b - c) - 1) ** 2 / (b + c)  # With continuity correction
        mcnemar_p = 1 - stats.chi2.cdf(mcnemar_stat, df=1)
    else:
        mcnemar_stat = 0
        mcnemar_p = 1.0

    sig = "***" if mcnemar_p < 0.001 else "**" if mcnemar_p < 0.01 else "*" if mcnemar_p < 0.05 else "ns"
    print(f"  {name} vs Naive: b={b}, c={c}, chi2={mcnemar_stat:.3f}, p={mcnemar_p:.4f} {sig}")
    results[name]['mcnemar_vs_naive'] = {
        'b': b, 'c': c,
        'chi2_stat': float(mcnemar_stat),
        'p_value': float(mcnemar_p),
    }

# ============================================================
# 5f. Feature importance (HAR Logistic)
# ============================================================
print("\n  --- HAR Logistic: Feature coefficients ---")
for col, coef in zip(lagged_feature_cols, har_model.coef_[0]):
    print(f"    {col:30s}: {coef:>8.4f}")
print(f"    {'intercept':30s}: {har_model.intercept_[0]:>8.4f}")

results['HAR_Logistic']['coefficients'] = {
    col: float(coef) for col, coef in zip(lagged_feature_cols, har_model.coef_[0])
}
results['HAR_Logistic']['intercept'] = float(har_model.intercept_[0])

# Random Forest feature importance
print("\n  --- Random Forest: Feature importance ---")
for col, imp in zip(lagged_feature_cols, rf_model.feature_importances_):
    print(f"    {col:30s}: {imp:>8.4f}")

results['Random_Forest']['feature_importance'] = {
    col: float(imp) for col, imp in zip(lagged_feature_cols, rf_model.feature_importances_)
}

# ============================================================
# 6. Save Results
# ============================================================
print("\n[6/6] Saving results...")

output = {
    'experiment_id': 'K787',
    'title': 'HAR Directional Volatility Prediction',
    'description': 'Can we predict whether vol goes UP or DOWN using HAR features + VIX?',
    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'data_source': 'yfinance (SPY + ^VIX)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}",
    'oos_n': len(oos_dates),
    'train_n_initial': int((df.index < oos_start).sum()),
    'target': 'Direction of 5-day RV change (binary: UP/DOWN)',
    'target_balance_oos': {
        'UP': float(actual.mean()),
        'DOWN': float(1 - actual.mean()),
    },
    'features': lagged_feature_cols,
    'lag': 'All features shifted by 1 day (signal.shift(1))',
    'retrain_interval': 63,
    'models': results,
    'economic_value': econ_results,
    'key_findings': [],
    'references': [
        'Corsi (2009): A Simple Approximate Long-Memory Model of Realized Volatility, Journal of Financial Econometrics',
        'Applied Economics Letters 2024: HAR for directional RV prediction',
        'Patton & Sheppard (2015): Good Volatility, Bad Volatility, JFE',
        'K697: VIX predicts vol magnitude (corr 0.57) but NOT direction (corr 0.04)',
        'K782: GJR beats HAR on r² magnitude forecasting',
    ],
}

# Determine key findings
best_model = max(model_names, key=lambda m: results[m]['accuracy'])
best_acc = results[best_model]['accuracy']

findings = []
findings.append(f"Best directional accuracy: {best_model} at {best_acc:.1%} (OOS 2023-2024)")

if best_acc > 0.55:
    findings.append(f"Direction prediction ABOVE 55% threshold — potentially useful")
elif best_acc > 0.50:
    findings.append(f"Direction prediction barely above random — marginal at best")
else:
    findings.append(f"Direction prediction at or below random — confirms K697 null result")

# Check if any model significantly beats naive
sig_models = [m for m in model_names if m != 'Naive' and
              results[m].get('mcnemar_vs_naive', {}).get('p_value', 1) < 0.05]
if sig_models:
    findings.append(f"Models significantly beating naive (McNemar p<0.05): {sig_models}")
else:
    findings.append("No model significantly beats naive baseline (McNemar test)")

# Check economic value
bh_ret = econ_results['Buy_Hold']['cumulative_return']
for name in ['HAR_Logistic', 'Random_Forest']:
    strat_ret = econ_results[name]['cumulative_return']
    if strat_ret > bh_ret:
        findings.append(f"{name} direction-timing strategy outperforms B&H ({strat_ret:.1%} vs {bh_ret:.1%})")
    else:
        findings.append(f"{name} direction-timing strategy underperforms B&H ({strat_ret:.1%} vs {bh_ret:.1%})")

# VIX sufficiency check
vix_acc = results['VIX_Direction']['accuracy']
har_acc = results['HAR_Logistic']['accuracy']
findings.append(f"VIX-only direction: {vix_acc:.1%} vs HAR: {har_acc:.1%} — "
                f"{'VIX sufficient' if abs(vix_acc - har_acc) < 0.02 else 'HAR adds marginal value'}")

output['key_findings'] = findings

# Save
output_path = 'experiments/k787_har_directional_results.json'
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY: K787 HAR Directional Volatility Prediction")
print("=" * 70)
for finding in findings:
    print(f"  - {finding}")
print("=" * 70)
