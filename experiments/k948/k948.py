#!/usr/bin/env python3
"""
K948: Weekly Return Predictability — Does predictability improve at weekly horizon?

Background:
- K924: daily return unpredictable (all 10 candidates PIP < 0.5)
- K143/K943: vol signal-to-noise peaks at h=5 (weekly)
- Literature: Fama & French (1988), Campbell & Shiller (1988), Welch & Goyal (2008)

Method:
- Target: 5-day cumulative return (non-overlapping weeks)
- Predictors: VIX, momentum, GARCH vol, realized vol, TLT
- Models: OLS, Ridge, LASSO, Random Forest, Historical Mean (baseline)
- OOS: 2016-01-01 ~ 2025-12-31, expanding window, retrain every 21 days
- Evaluation: OOS R², directional accuracy, DM test, long/short strategy Sharpe

Data source: yfinance (SPY, ^VIX, TLT), 2006-2026
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime
from pathlib import Path
from sklearn.linear_model import Ridge, Lasso, LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from arch import arch_model

warnings.filterwarnings('ignore')
np.random.seed(42)

OUT_DIR = Path(__file__).parent
OOS_START = '2016-01-01'

# ============================================================
# 1. Data Download
# ============================================================
print("=== K948: Weekly Return Predictability ===")
print("Downloading data...")

spy = yf.download('SPY', start='2004-01-01', end='2026-04-01', auto_adjust=True, progress=False)
vix = yf.download('^VIX', start='2004-01-01', end='2026-04-01', auto_adjust=True, progress=False)
tlt = yf.download('TLT', start='2004-01-01', end='2026-04-01', auto_adjust=True, progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)
if isinstance(tlt.columns, pd.MultiIndex):
    tlt.columns = tlt.columns.get_level_values(0)

# Align indices
df = pd.DataFrame(index=spy.index)
df['spy_close'] = spy['Close']
df['spy_ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
df['vix'] = vix['Close'].reindex(spy.index, method='ffill')
df['tlt_ret'] = np.log(tlt['Close'] / tlt['Close'].shift(1)).reindex(spy.index, method='ffill')
df = df.dropna()

print(f"Data range: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(df)}")

# ============================================================
# 2. Feature Construction (all lagged)
# ============================================================
print("\nConstructing features...")

# 5-day cumulative return (target) — forward-looking
df['ret_5d'] = df['spy_ret'].rolling(5).sum().shift(-4)  # r_{t:t+4}

# Features (all use information up to t-1 or earlier)
df['log_vix'] = np.log(df['vix'])
df['vix_change_5d'] = df['log_vix'] - df['log_vix'].shift(5)
df['mom_20d'] = df['spy_ret'].rolling(20).sum()  # t-19 to t
df['mom_5d'] = df['spy_ret'].rolling(5).sum()    # t-4 to t
df['vix_ma20_ratio'] = df['vix'] / df['vix'].rolling(20).mean()
df['realized_vol_5d'] = df['spy_ret'].rolling(5).std() * np.sqrt(252)
df['tlt_ret_5d'] = df['tlt_ret'].rolling(5).sum()

# GARCH(1,1) conditional variance — fitted on expanding window
print("Fitting GARCH for conditional variance...")
garch_var = pd.Series(index=df.index, dtype=float)
ret_series = df['spy_ret'].dropna() * 100  # in percentage for arch

# Pre-compute GARCH variance for all dates using expanding window
# Refit every 252 days for efficiency
last_fit_idx = 0
refit_interval = 252
min_window = 500

for i in range(min_window, len(ret_series)):
    if i == min_window or (i - last_fit_idx) >= refit_interval:
        try:
            am = arch_model(ret_series.iloc[:i], vol='Garch', p=1, q=1, dist='normal', mean='Zero')
            res = am.fit(disp='off', show_warning=False)
            last_fit_idx = i
            omega = res.params.get('omega', 0.01)
            alpha = res.params.get('alpha[1]', 0.05)
            beta = res.params.get('beta[1]', 0.9)
        except:
            continue

    # Recursive variance: h[t] = omega + alpha*r²[t-1] + beta*h[t-1]
    if i > min_window:
        prev_var = garch_var.iloc[i-1] if not np.isnan(garch_var.iloc[i-1]) else omega / (1 - alpha - beta)
        prev_ret_sq = (ret_series.iloc[i-1])**2
        h_t = omega + alpha * prev_ret_sq + beta * prev_var
        garch_var.iloc[i] = h_t
    else:
        garch_var.iloc[i] = omega / max(1 - alpha - beta, 0.01)

df['garch_var'] = garch_var / 10000  # convert back from percentage squared

# Lag all features by 1 day to prevent lookahead
feature_cols = ['log_vix', 'vix_change_5d', 'mom_20d', 'mom_5d',
                'vix_ma20_ratio', 'garch_var', 'realized_vol_5d', 'tlt_ret_5d']

for col in feature_cols:
    df[f'{col}_lag'] = df[col].shift(1)  # CRITICAL: lag by 1

lagged_features = [f'{c}_lag' for c in feature_cols]

# Drop NaN
df_clean = df.dropna(subset=['ret_5d'] + lagged_features)
print(f"Clean observations: {len(df_clean)}")

# ============================================================
# 3. Non-overlapping Weekly Sampling
# ============================================================
print("\nCreating non-overlapping weekly samples...")

# Sample every 5 trading days
weekly_idx = list(range(0, len(df_clean), 5))
df_weekly = df_clean.iloc[weekly_idx].copy()
print(f"Weekly samples: {len(df_weekly)}")

# Split IS/OOS
oos_mask = df_weekly.index >= OOS_START
is_data = df_weekly[~oos_mask]
oos_data = df_weekly[oos_mask]
print(f"In-sample: {len(is_data)} weeks ({is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')})")
print(f"Out-of-sample: {len(oos_data)} weeks ({oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')})")

# ============================================================
# 4. OOS Prediction with Expanding Window
# ============================================================
print("\nRunning OOS predictions...")

models = {
    'OLS': LinearRegression(),
    'Ridge': Ridge(alpha=1.0),
    'LASSO': Lasso(alpha=0.001, max_iter=10000),
    'RandomForest': RandomForestRegressor(n_estimators=100, max_depth=3, random_state=42),
}

# Storage for predictions
predictions = {name: [] for name in models}
predictions['HistMean'] = []
actuals = []
pred_dates = []

X_all = df_weekly[lagged_features].values
y_all = df_weekly['ret_5d'].values
dates_all = df_weekly.index

# Find OOS start index
oos_start_idx = np.where(oos_mask)[0][0]

# Retrain every ~21 days ≈ 4 weeks (since we sample weekly)
retrain_interval = 4
last_retrain = -retrain_interval  # force initial training

fitted_models = {}
scaler = StandardScaler()

for i in range(oos_start_idx, len(df_weekly)):
    # Expanding window training data
    X_train = X_all[:i]
    y_train = y_all[:i]

    X_test = X_all[i:i+1]
    y_test = y_all[i]

    # Retrain if needed
    if (i - last_retrain) >= retrain_interval:
        scaler_fit = StandardScaler()
        X_train_scaled = scaler_fit.fit_transform(X_train)

        for name, model_template in models.items():
            if name == 'RandomForest':
                m = RandomForestRegressor(n_estimators=100, max_depth=3, random_state=42)
            elif name == 'OLS':
                m = LinearRegression()
            elif name == 'Ridge':
                m = Ridge(alpha=1.0)
            elif name == 'LASSO':
                m = Lasso(alpha=0.001, max_iter=10000)

            m.fit(X_train_scaled, y_train)
            fitted_models[name] = (m, scaler_fit)

        last_retrain = i

    # Predict
    X_test_scaled = fitted_models['OLS'][1].transform(X_test)

    for name in models:
        m, sc = fitted_models[name]
        pred = m.predict(sc.transform(X_test))[0]
        predictions[name].append(pred)

    # Historical mean (expanding)
    hist_mean = np.mean(y_train)
    predictions['HistMean'].append(hist_mean)

    actuals.append(y_test)
    pred_dates.append(dates_all[i])

actuals = np.array(actuals)
for name in predictions:
    predictions[name] = np.array(predictions[name])

print(f"OOS predictions: {len(actuals)} weeks")

# ============================================================
# 5. Evaluation Metrics
# ============================================================
print("\n=== Evaluation Results ===")

results = {}

for name in ['OLS', 'Ridge', 'LASSO', 'RandomForest', 'HistMean']:
    preds = predictions[name]

    # OOS R² (vs historical mean)
    ss_res = np.sum((actuals - preds)**2)
    ss_tot = np.sum((actuals - predictions['HistMean'])**2)
    oos_r2 = 1 - ss_res / ss_tot if name != 'HistMean' else 0.0

    # MSE
    mse = np.mean((actuals - preds)**2)

    # Directional accuracy
    correct_dir = np.mean(np.sign(preds) == np.sign(actuals))

    # Long/short strategy with lag
    # Signal from week t prediction → trade week t+1
    # But our predictions are already for week t's return using t-1 features
    # So the signal IS lagged (features at t-1, predict r_{t:t+4})
    # For strategy: if predicted return > 0, go long; else go short
    signal = np.where(preds > 0, 1.0, -1.0)

    # Strategy returns (already properly lagged via feature construction)
    strat_ret = signal * actuals

    # Transaction costs: 10bps per trade (when signal changes)
    signal_changes = np.abs(np.diff(np.concatenate([[0], signal]))) / 2  # 0 or 1
    tc = signal_changes * 0.001  # 10bps round trip
    strat_ret_net = strat_ret - tc

    # Annualized Sharpe (weekly → annualized)
    ann_factor = np.sqrt(52)
    sharpe_gross = np.mean(strat_ret) / np.std(strat_ret) * ann_factor if np.std(strat_ret) > 0 else 0
    sharpe_net = np.mean(strat_ret_net) / np.std(strat_ret_net) * ann_factor if np.std(strat_ret_net) > 0 else 0

    # Buy-and-hold benchmark
    bh_sharpe = np.mean(actuals) / np.std(actuals) * ann_factor if np.std(actuals) > 0 else 0

    results[name] = {
        'oos_r2': float(oos_r2),
        'mse': float(mse),
        'directional_accuracy': float(correct_dir),
        'sharpe_gross': float(sharpe_gross),
        'sharpe_net': float(sharpe_net),
        'bh_sharpe': float(bh_sharpe),
        'mean_pred': float(np.mean(preds)),
        'std_pred': float(np.std(preds)),
        'n_trades': int(np.sum(signal_changes > 0)),
        'pct_long': float(np.mean(signal > 0)),
    }

    print(f"\n{name}:")
    print(f"  OOS R²: {oos_r2:.4f}")
    print(f"  MSE: {mse:.6f}")
    print(f"  Directional accuracy: {correct_dir:.3f}")
    print(f"  Sharpe (gross): {sharpe_gross:.3f}")
    print(f"  Sharpe (net): {sharpe_net:.3f}")
    print(f"  BH Sharpe: {bh_sharpe:.3f}")
    print(f"  # trades: {int(np.sum(signal_changes > 0))}")

# ============================================================
# 6. DM Test (each model vs Historical Mean)
# ============================================================
print("\n=== DM Tests (vs Historical Mean) ===")

from scipy import stats

def dm_test(e1, e2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    d = e1**2 - e2**2
    n = len(d)
    d_bar = np.mean(d)

    # Newey-West variance with h-1 lags
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0

    dm_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_value)

e_hist = actuals - predictions['HistMean']
dm_results = {}

for name in ['OLS', 'Ridge', 'LASSO', 'RandomForest']:
    e_model = actuals - predictions[name]
    t_stat, p_val = dm_test(e_model, e_hist, h=5)
    dm_results[name] = {'t_stat': t_stat, 'p_value': p_val}
    sig = '***' if abs(t_stat) > 3.0 else '**' if abs(t_stat) > 2.0 else '*' if abs(t_stat) > 1.65 else ''
    print(f"  {name} vs HistMean: DM t={t_stat:.3f}, p={p_val:.4f} {sig}")

# ============================================================
# 7. Feature Importance (from OLS and RF)
# ============================================================
print("\n=== Feature Importance ===")

# Final OLS coefficients
X_full = df_weekly[lagged_features].iloc[:oos_start_idx].values
y_full = df_weekly['ret_5d'].iloc[:oos_start_idx].values
sc_full = StandardScaler()
X_full_sc = sc_full.fit_transform(X_full)

ols_final = LinearRegression().fit(X_full_sc, y_full)
print("\nOLS standardized coefficients:")
coef_dict = {}
for feat, coef in zip(feature_cols, ols_final.coef_):
    print(f"  {feat:25s}: {coef:.6f}")
    coef_dict[feat] = float(coef)

# RF feature importance
rf_final = RandomForestRegressor(n_estimators=100, max_depth=3, random_state=42)
rf_final.fit(X_full_sc, y_full)
print("\nRandom Forest feature importance:")
rf_imp = {}
for feat, imp in zip(feature_cols, rf_final.feature_importances_):
    print(f"  {feat:25s}: {imp:.4f}")
    rf_imp[feat] = float(imp)

# ============================================================
# 8. Descriptive Statistics
# ============================================================
print("\n=== Descriptive Statistics (OOS period) ===")
desc = {
    'mean_weekly_ret': float(np.mean(actuals)),
    'std_weekly_ret': float(np.std(actuals)),
    'skew': float(pd.Series(actuals).skew()),
    'kurt': float(pd.Series(actuals).kurtosis()),
    'min': float(np.min(actuals)),
    'max': float(np.max(actuals)),
    'pct_positive': float(np.mean(actuals > 0)),
}
for k, v in desc.items():
    print(f"  {k}: {v:.4f}")

# ============================================================
# 9. Visualization
# ============================================================
print("\nGenerating plots...")

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle('K948: Weekly Return Predictability (OOS 2016-2026)', fontsize=14, fontweight='bold')

# (a) OOS R² comparison
ax = axes[0, 0]
model_names = ['OLS', 'Ridge', 'LASSO', 'RandomForest']
r2_vals = [results[m]['oos_r2'] for m in model_names]
colors = ['#e74c3c' if v < 0 else '#27ae60' for v in r2_vals]
bars = ax.bar(model_names, r2_vals, color=colors, edgecolor='black', linewidth=0.5)
ax.axhline(y=0, color='black', linewidth=1)
ax.set_ylabel('OOS R²')
ax.set_title('(a) OOS R² vs Historical Mean')
for bar, val in zip(bars, r2_vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.001,
            f'{val:.4f}', ha='center', va='bottom', fontsize=9)

# (b) Directional accuracy
ax = axes[0, 1]
all_models = ['OLS', 'Ridge', 'LASSO', 'RandomForest', 'HistMean']
da_vals = [results[m]['directional_accuracy'] for m in all_models]
colors_da = ['#3498db' if v > 0.5 else '#e74c3c' for v in da_vals]
bars = ax.bar(all_models, da_vals, color=colors_da, edgecolor='black', linewidth=0.5)
ax.axhline(y=0.5, color='red', linestyle='--', linewidth=1, label='Random (50%)')
ax.set_ylabel('Directional Accuracy')
ax.set_title('(b) Directional Accuracy')
ax.legend()
for bar, val in zip(bars, da_vals):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.003,
            f'{val:.1%}', ha='center', va='bottom', fontsize=9)

# (c) Strategy Sharpe ratios
ax = axes[1, 0]
sharpe_gross = [results[m]['sharpe_gross'] for m in all_models]
sharpe_net = [results[m]['sharpe_net'] for m in all_models]
x_pos = np.arange(len(all_models))
width = 0.35
ax.bar(x_pos - width/2, sharpe_gross, width, label='Gross', color='#2ecc71', edgecolor='black', linewidth=0.5)
ax.bar(x_pos + width/2, sharpe_net, width, label='Net of TC', color='#e67e22', edgecolor='black', linewidth=0.5)
ax.axhline(y=results['HistMean']['bh_sharpe'], color='red', linestyle='--', linewidth=1.5, label=f'Buy & Hold ({results["HistMean"]["bh_sharpe"]:.2f})')
ax.set_xticks(x_pos)
ax.set_xticklabels(all_models, rotation=15)
ax.set_ylabel('Annualized Sharpe')
ax.set_title('(c) Long/Short Strategy Sharpe')
ax.legend(fontsize=8)

# (d) Cumulative returns comparison
ax = axes[1, 1]
cum_bh = np.cumsum(actuals)
for name in ['Ridge', 'LASSO', 'RandomForest']:
    signal = np.where(predictions[name] > 0, 1.0, -1.0)
    signal_changes = np.abs(np.diff(np.concatenate([[0], signal]))) / 2
    tc = signal_changes * 0.001
    strat_ret = signal * actuals - tc
    cum_strat = np.cumsum(strat_ret)
    ax.plot(pred_dates, cum_strat, label=f'{name}', linewidth=1)
ax.plot(pred_dates, cum_bh, label='Buy & Hold', color='black', linewidth=2, linestyle='--')
ax.set_ylabel('Cumulative Return')
ax.set_title('(d) Cumulative Returns (OOS)')
ax.legend(fontsize=8)
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig(OUT_DIR / 'k948_comparison.png', dpi=150, bbox_inches='tight')
plt.close()
print(f"Saved: {OUT_DIR / 'k948_comparison.png'}")

# ============================================================
# 10. Save Results
# ============================================================
output = {
    'experiment_id': 'K948',
    'title': 'Weekly Return Predictability — daily unpredictable, what about weekly?',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX, TLT)',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')}",
    'n_weekly_samples_total': len(df_weekly),
    'n_oos_samples': len(actuals),
    'target': '5-day cumulative log return (non-overlapping)',
    'features': feature_cols,
    'feature_lag': 1,
    'retrain_interval': '~21 trading days (4 weekly samples)',
    'transaction_cost_bps': 10,
    'results': results,
    'dm_tests_vs_hist_mean': dm_results,
    'ols_standardized_coefficients': coef_dict,
    'rf_feature_importance': rf_imp,
    'descriptive_stats_oos': desc,
    'conclusion': '',
    'references': [
        'Fama & French (1988) - Dividend yields and expected stock returns, JFE',
        'Campbell & Shiller (1988) - Stock prices, earnings, and expected dividends, JF',
        'Welch & Goyal (2008) - A comprehensive look at the empirical performance of equity premium prediction, RFS',
    ],
}

# Determine conclusion
best_r2_model = max(model_names, key=lambda m: results[m]['oos_r2'])
best_r2 = results[best_r2_model]['oos_r2']
any_dm_sig = any(abs(dm_results[m]['t_stat']) > 3.0 for m in dm_results)
best_da = max(all_models, key=lambda m: results[m]['directional_accuracy'])
best_da_val = results[best_da]['directional_accuracy']
best_sharpe_model = max(all_models, key=lambda m: results[m]['sharpe_net'])
best_sharpe = results[best_sharpe_model]['sharpe_net']
bh_sharpe = results['HistMean']['bh_sharpe']

if best_r2 > 0.02 and any_dm_sig:
    conclusion = f"POSITIVE: Weekly returns show predictability. Best OOS R²={best_r2:.4f} ({best_r2_model}), DM significant."
elif best_r2 > 0 and best_da_val > 0.55:
    conclusion = f"WEAK POSITIVE: Marginal predictability. Best OOS R²={best_r2:.4f}, best DA={best_da_val:.1%}."
elif best_sharpe > bh_sharpe * 1.2:
    conclusion = f"STRATEGY VALUE: Models don't predict well (R²={best_r2:.4f}) but strategy Sharpe ({best_sharpe:.3f}) > BH ({bh_sharpe:.3f})."
else:
    conclusion = f"NULL: Weekly returns also largely unpredictable. Best OOS R²={best_r2:.4f}, best DA={best_da_val:.1%}, best strategy Sharpe ({best_sharpe:.3f}) ≈ BH ({bh_sharpe:.3f}). Consistent with Welch & Goyal (2008)."

output['conclusion'] = conclusion
print(f"\n{'='*60}")
print(f"CONCLUSION: {conclusion}")
print(f"{'='*60}")

with open(OUT_DIR / 'k948_results.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False, default=str)

print(f"\nSaved: {OUT_DIR / 'k948_results.json'}")
print("K948 complete.")
