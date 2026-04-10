"""
K1019: VIX Regime Transition Prediction
========================================

Background:
- K752 found VIX-return R² varies 0.24-0.64 across eras (CV=0.33)
- K162/K278 explored VIX regime concepts
- K133 found no true VIX info decay regime

Goal:
Test whether VIX regime transitions (low→high volatility) can be predicted,
and whether such predictions improve VT strategy performance.

Method:
1. Define regimes: VIX > 20 (high vol) vs VIX <= 20 (low vol). Also test 25 and 30.
2. Prediction models:
   a. Logistic regression with VIX features
   b. Rolling logistic (adaptive, replaces HMM since hmmlearn unavailable)
   c. Threshold model (ΔlogVIX speed)
3. Evaluate OOS accuracy, F1, and economic value vs 12/VIX baseline

Data: SPY + VIX + VIX3M from yfinance, 2005-2026
OOS: 2019-01-01 to present
seed=42

Author: VolPred Research System
"""

import numpy as np
import pandas as pd
import yfinance as yf
import json
import warnings
import os
from datetime import datetime
from pathlib import Path

warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = Path(__file__).parent
OOS_START = '2019-01-01'

# =============================================================================
# 1. Data Collection
# =============================================================================
print("=" * 70)
print("K1019: VIX Regime Transition Prediction")
print("=" * 70)

print("\n[1] Downloading data...")
tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'VIX3M': '^VIX3M',
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start='2004-01-01', end='2026-12-31', progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df['Close'].rename(name)
    print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Merge
df = pd.DataFrame(data).dropna()
print(f"\n  Merged: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# =============================================================================
# 2. Feature Engineering
# =============================================================================
print("\n[2] Engineering features...")

# Returns
df['spy_ret'] = np.log(df['SPY'] / df['SPY'].shift(1))

# VIX features
df['vix_chg'] = df['VIX'].pct_change()  # daily VIX % change
df['vix_log_chg'] = np.log(df['VIX'] / df['VIX'].shift(1))  # log change
df['vix_5d_chg'] = df['VIX'].pct_change(5)  # 5-day VIX change
df['vix_20d_chg'] = df['VIX'].pct_change(20)  # 20-day VIX change
df['vix_ma5'] = df['VIX'].rolling(5).mean()
df['vix_ma20'] = df['VIX'].rolling(20).mean()
df['vix_above_ma20'] = (df['VIX'] > df['vix_ma20']).astype(int)

# Term structure: VIX / VIX3M (contango = < 1, backwardation = > 1)
df['term_structure'] = df['VIX'] / df['VIX3M']

# Realized vol (trailing 5-day and 20-day)
df['rv5'] = df['spy_ret'].rolling(5).std() * np.sqrt(252)
df['rv20'] = df['spy_ret'].rolling(20).std() * np.sqrt(252)
df['rv_ratio'] = df['rv5'] / df['rv20']  # short-term vs long-term vol

# Return momentum
df['ret_5d'] = df['spy_ret'].rolling(5).sum()
df['ret_20d'] = df['spy_ret'].rolling(20).sum()

# VIX level relative to history
df['vix_pct_rank'] = df['VIX'].rolling(252).rank(pct=True)

# VIX velocity (rate of change of VIX change)
df['vix_accel'] = df['vix_log_chg'] - df['vix_log_chg'].shift(1)

# Drop NaN
df = df.dropna()
print(f"  After feature engineering: {len(df)} rows")

# =============================================================================
# 3. Define Regimes
# =============================================================================
print("\n[3] Defining regimes...")

thresholds = [20, 25, 30]
for th in thresholds:
    col = f'regime_{th}'
    df[col] = (df['VIX'] > th).astype(int)
    n_high = df[col].sum()
    pct = 100 * n_high / len(df)
    print(f"  VIX > {th}: {n_high} days ({pct:.1f}%)")

# Transition indicator: 0→1 (entering high vol regime)
for th in thresholds:
    regime_col = f'regime_{th}'
    trans_col = f'trans_{th}'
    df[trans_col] = ((df[regime_col] == 1) & (df[regime_col].shift(1) == 0)).astype(int)
    n_trans = df[trans_col].sum()
    print(f"  Transitions into VIX > {th}: {n_trans}")

# Target for prediction: will tomorrow be in high-vol regime?
# We predict regime[t+1] using features available at t
# This is equivalent to: target = regime.shift(-1)
for th in thresholds:
    df[f'target_{th}'] = df[f'regime_{th}'].shift(-1)

df = df.dropna()

# =============================================================================
# 4. Feature Selection
# =============================================================================

feature_cols = [
    'vix_chg', 'vix_log_chg', 'vix_5d_chg', 'vix_20d_chg',
    'vix_above_ma20', 'term_structure',
    'rv5', 'rv20', 'rv_ratio',
    'ret_5d', 'ret_20d',
    'vix_pct_rank', 'vix_accel',
    'VIX'  # current VIX level is highly predictive (persistence)
]

# =============================================================================
# 5. Model Training & Evaluation
# =============================================================================
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (accuracy_score, precision_score, recall_score,
                             f1_score, confusion_matrix, classification_report)

print("\n[4] Training models...")

# Split
is_mask = df.index < OOS_START
oos_mask = df.index >= OOS_START

X_is = df.loc[is_mask, feature_cols].values
X_oos = df.loc[oos_mask, feature_cols].values

results = {}

for th in thresholds:
    print(f"\n{'='*50}")
    print(f"  Threshold: VIX > {th}")
    print(f"{'='*50}")

    target_col = f'target_{th}'
    y_is = df.loc[is_mask, target_col].values.astype(int)
    y_oos = df.loc[oos_mask, target_col].values.astype(int)

    print(f"  IS: {len(y_is)} obs, {y_is.sum()} high-vol days ({100*y_is.mean():.1f}%)")
    print(f"  OOS: {len(y_oos)} obs, {y_oos.sum()} high-vol days ({100*y_oos.mean():.1f}%)")

    th_results = {}

    # =========================================================================
    # Model A: Full-sample Logistic Regression (fit on IS, predict OOS)
    # =========================================================================
    print(f"\n  --- Model A: Logistic Regression ---")
    scaler = StandardScaler()
    X_is_scaled = scaler.fit_transform(X_is)
    X_oos_scaled = scaler.transform(X_oos)

    lr = LogisticRegression(max_iter=1000, random_state=42, class_weight='balanced')
    lr.fit(X_is_scaled, y_is)

    y_pred_lr = lr.predict(X_oos_scaled)
    y_prob_lr = lr.predict_proba(X_oos_scaled)[:, 1]

    acc_lr = accuracy_score(y_oos, y_pred_lr)
    prec_lr = precision_score(y_oos, y_pred_lr, zero_division=0)
    rec_lr = recall_score(y_oos, y_pred_lr, zero_division=0)
    f1_lr = f1_score(y_oos, y_pred_lr, zero_division=0)

    print(f"  Accuracy: {acc_lr:.4f}")
    print(f"  Precision: {prec_lr:.4f}")
    print(f"  Recall: {rec_lr:.4f}")
    print(f"  F1: {f1_lr:.4f}")

    # Feature importance
    coef_importance = dict(zip(feature_cols, lr.coef_[0]))
    top_features = sorted(coef_importance.items(), key=lambda x: abs(x[1]), reverse=True)[:5]
    print(f"  Top features: {[(f, round(c, 3)) for f, c in top_features]}")

    th_results['logistic_regression'] = {
        'accuracy': round(acc_lr, 4),
        'precision': round(prec_lr, 4),
        'recall': round(rec_lr, 4),
        'f1': round(f1_lr, 4),
        'top_features': {f: round(c, 4) for f, c in top_features},
    }

    # =========================================================================
    # Model B: Rolling Logistic Regression (re-fit every 63 days, 252-day window)
    # =========================================================================
    print(f"\n  --- Model B: Rolling Logistic Regression (252d window, refit every 63d) ---")

    oos_idx = df.index[oos_mask]
    full_X = df[feature_cols].values
    full_y = df[target_col].values.astype(int)

    # Get integer positions
    all_dates = df.index
    oos_start_pos = np.where(all_dates >= pd.Timestamp(OOS_START))[0][0]

    rolling_preds = np.zeros(len(oos_idx))
    rolling_probs = np.zeros(len(oos_idx))
    refit_interval = 63
    train_window = 252 * 3  # 3 years

    last_model = None
    last_scaler = None

    for i in range(len(oos_idx)):
        pos = oos_start_pos + i

        if i % refit_interval == 0 or last_model is None:
            # Refit
            train_start = max(0, pos - train_window)
            X_train = full_X[train_start:pos]
            y_train = full_y[train_start:pos]

            sc = StandardScaler()
            X_train_sc = sc.fit_transform(X_train)

            model = LogisticRegression(max_iter=1000, random_state=42, class_weight='balanced')
            model.fit(X_train_sc, y_train)

            last_model = model
            last_scaler = sc

        x_test = full_X[pos:pos+1]
        x_test_sc = last_scaler.transform(x_test)
        rolling_preds[i] = last_model.predict(x_test_sc)[0]
        rolling_probs[i] = last_model.predict_proba(x_test_sc)[:, 1][0]

    acc_rl = accuracy_score(y_oos, rolling_preds)
    prec_rl = precision_score(y_oos, rolling_preds, zero_division=0)
    rec_rl = recall_score(y_oos, rolling_preds, zero_division=0)
    f1_rl = f1_score(y_oos, rolling_preds, zero_division=0)

    print(f"  Accuracy: {acc_rl:.4f}")
    print(f"  Precision: {prec_rl:.4f}")
    print(f"  Recall: {rec_rl:.4f}")
    print(f"  F1: {f1_rl:.4f}")

    th_results['rolling_logistic'] = {
        'accuracy': round(acc_rl, 4),
        'precision': round(prec_rl, 4),
        'recall': round(rec_rl, 4),
        'f1': round(f1_rl, 4),
    }

    # =========================================================================
    # Model C: Threshold Model (ΔlogVIX speed)
    # =========================================================================
    print(f"\n  --- Model C: Threshold Model ---")

    # Simple: if VIX is already above threshold OR VIX rising fast → predict high vol
    # Optimize threshold on IS
    best_f1_th = 0
    best_delta = 0

    vix_log_chg_is = df.loc[is_mask, 'vix_log_chg'].values
    vix_is = df.loc[is_mask, 'VIX'].values

    for delta in np.arange(0.01, 0.15, 0.005):
        # Predict high vol if VIX > th*0.9 AND vix_log_chg > delta
        # OR if VIX already > th
        preds_try = ((vix_is > th) | ((vix_is > th * 0.8) & (vix_log_chg_is > delta))).astype(int)
        f1_try = f1_score(y_is, preds_try, zero_division=0)
        if f1_try > best_f1_th:
            best_f1_th = f1_try
            best_delta = delta

    print(f"  Best IS delta: {best_delta:.3f} (F1={best_f1_th:.4f})")

    # Apply to OOS
    vix_log_chg_oos = df.loc[oos_mask, 'vix_log_chg'].values
    vix_oos = df.loc[oos_mask, 'VIX'].values

    y_pred_th = ((vix_oos > th) | ((vix_oos > th * 0.8) & (vix_log_chg_oos > best_delta))).astype(int)

    acc_th = accuracy_score(y_oos, y_pred_th)
    prec_th = precision_score(y_oos, y_pred_th, zero_division=0)
    rec_th = recall_score(y_oos, y_pred_th, zero_division=0)
    f1_th = f1_score(y_oos, y_pred_th, zero_division=0)

    print(f"  Accuracy: {acc_th:.4f}")
    print(f"  Precision: {prec_th:.4f}")
    print(f"  Recall: {rec_th:.4f}")
    print(f"  F1: {f1_th:.4f}")

    th_results['threshold_model'] = {
        'accuracy': round(acc_th, 4),
        'precision': round(prec_th, 4),
        'recall': round(rec_th, 4),
        'f1': round(f1_th, 4),
        'best_delta': round(best_delta, 3),
    }

    # =========================================================================
    # Model D: Naive Persistence (today's regime = tomorrow's regime)
    # =========================================================================
    print(f"\n  --- Model D: Naive Persistence (baseline) ---")
    y_naive = df.loc[oos_mask, f'regime_{th}'].values.astype(int)  # today's regime

    acc_naive = accuracy_score(y_oos, y_naive)
    prec_naive = precision_score(y_oos, y_naive, zero_division=0)
    rec_naive = recall_score(y_oos, y_naive, zero_division=0)
    f1_naive = f1_score(y_oos, y_naive, zero_division=0)

    print(f"  Accuracy: {acc_naive:.4f}")
    print(f"  Precision: {prec_naive:.4f}")
    print(f"  Recall: {rec_naive:.4f}")
    print(f"  F1: {f1_naive:.4f}")

    th_results['naive_persistence'] = {
        'accuracy': round(acc_naive, 4),
        'precision': round(prec_naive, 4),
        'recall': round(rec_naive, 4),
        'f1': round(f1_naive, 4),
    }

    # Store predictions for economic evaluation (use rolling logistic as the "best" model)
    th_results['_oos_dates'] = oos_idx.strftime('%Y-%m-%d').tolist()
    th_results['_oos_preds_rolling'] = rolling_preds.tolist()
    th_results['_oos_probs_rolling'] = rolling_probs.tolist()
    th_results['_oos_preds_lr'] = y_pred_lr.tolist()
    th_results['_oos_probs_lr'] = y_prob_lr.tolist()
    th_results['_oos_actual'] = y_oos.tolist()

    results[f'threshold_{th}'] = th_results

# =============================================================================
# 6. Economic Value: Regime-based VT Strategy
# =============================================================================
print("\n\n" + "=" * 70)
print("[5] Economic Value: Regime-based VT vs 12/VIX Baseline")
print("=" * 70)

# Get OOS returns
spy_ret_oos = df.loc[oos_mask, 'spy_ret'].values
vix_oos_full = df.loc[oos_mask, 'VIX'].values
dates_oos = df.index[oos_mask]

# Baseline: 12/VIX with shift(1) - use yesterday's VIX for today's weight
vix_signal = df.loc[oos_mask, 'VIX'].values
# shift(1): weight[t] = f(VIX[t-1])
baseline_weight = np.clip(12.0 / np.roll(vix_signal, 1), 0, 1)
baseline_weight[0] = 12.0 / vix_signal[0]  # first day
baseline_ret = baseline_weight * spy_ret_oos

econ_results = {}

for th in thresholds:
    print(f"\n  --- Threshold: VIX > {th} ---")

    th_data = results[f'threshold_{th}']

    for model_name in ['logistic_regression', 'rolling_logistic', 'threshold_model']:
        if model_name == 'logistic_regression':
            preds = np.array(th_data['_oos_preds_lr'])
            probs = np.array(th_data['_oos_probs_lr'])
        elif model_name == 'rolling_logistic':
            preds = np.array(th_data['_oos_preds_rolling'])
            probs = np.array(th_data['_oos_probs_rolling'])
        else:
            # Threshold model doesn't have probs easily, use binary
            vix_log_chg_oos_vals = df.loc[oos_mask, 'vix_log_chg'].values
            vix_oos_vals = df.loc[oos_mask, 'VIX'].values
            best_d = th_data['threshold_model']['best_delta']
            preds = ((vix_oos_vals > th) | ((vix_oos_vals > th * 0.8) & (vix_log_chg_oos_vals > best_d))).astype(float)
            probs = preds.copy()

        # Strategy: when predicting high vol, reduce equity weight
        # signal.shift(1): use prediction from t-1 for weight at t
        pred_shifted = np.roll(preds, 1)
        pred_shifted[0] = 0  # no prediction for first day
        prob_shifted = np.roll(probs, 1)
        prob_shifted[0] = 0.5

        # Strategy 1: Binary switch (predict high → weight=0.3, predict low → weight=12/VIX)
        vix_shifted = np.roll(vix_oos_full, 1)
        vix_shifted[0] = vix_oos_full[0]
        base_w = np.clip(12.0 / vix_shifted, 0, 1)

        binary_weight = np.where(pred_shifted == 1, 0.3, base_w)
        binary_ret = binary_weight * spy_ret_oos

        # Strategy 2: Probability-weighted (scale down proportional to P(high vol))
        prob_weight = base_w * (1 - 0.7 * prob_shifted)  # reduce by up to 70% when P(high)=1
        prob_ret = prob_weight * spy_ret_oos

        # Calculate metrics
        def calc_metrics(rets, label):
            cumret = np.exp(np.cumsum(rets)) - 1
            ann_ret = np.mean(rets) * 252
            ann_vol = np.std(rets) * np.sqrt(252)
            sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

            # Max drawdown
            cum = np.exp(np.cumsum(rets))
            peak = np.maximum.accumulate(cum)
            dd = (cum - peak) / peak
            mdd = np.min(dd)

            return {
                'annual_return': round(ann_ret, 4),
                'annual_vol': round(ann_vol, 4),
                'sharpe': round(sharpe, 4),
                'max_drawdown': round(mdd, 4),
                'total_return': round(cumret[-1], 4),
            }

        binary_metrics = calc_metrics(binary_ret, f'{model_name}_binary')
        prob_metrics = calc_metrics(prob_ret, f'{model_name}_prob')

        key = f'{model_name}_th{th}'
        econ_results[key] = {
            'binary_switch': binary_metrics,
            'prob_weighted': prob_metrics,
        }

        print(f"  {model_name}:")
        print(f"    Binary:  Sharpe={binary_metrics['sharpe']:.4f}, "
              f"Return={binary_metrics['annual_return']:.4f}, "
              f"MDD={binary_metrics['max_drawdown']:.4f}")
        print(f"    Prob-wt: Sharpe={prob_metrics['sharpe']:.4f}, "
              f"Return={prob_metrics['annual_return']:.4f}, "
              f"MDD={prob_metrics['max_drawdown']:.4f}")

# Baseline metrics
baseline_metrics = {
    'annual_return': round(np.mean(baseline_ret) * 252, 4),
    'annual_vol': round(np.std(baseline_ret) * np.sqrt(252), 4),
    'sharpe': round((np.mean(baseline_ret) * 252) / (np.std(baseline_ret) * np.sqrt(252)), 4),
}
cum_base = np.exp(np.cumsum(baseline_ret))
peak_base = np.maximum.accumulate(cum_base)
dd_base = (cum_base - peak_base) / peak_base
baseline_metrics['max_drawdown'] = round(np.min(dd_base), 4)
baseline_metrics['total_return'] = round(cum_base[-1] - 1, 4)

print(f"\n  Baseline (12/VIX):")
print(f"    Sharpe={baseline_metrics['sharpe']:.4f}, "
      f"Return={baseline_metrics['annual_return']:.4f}, "
      f"MDD={baseline_metrics['max_drawdown']:.4f}")

# Buy & Hold
bh_ret = spy_ret_oos
bh_metrics = {
    'annual_return': round(np.mean(bh_ret) * 252, 4),
    'annual_vol': round(np.std(bh_ret) * np.sqrt(252), 4),
    'sharpe': round((np.mean(bh_ret) * 252) / (np.std(bh_ret) * np.sqrt(252)), 4),
}
cum_bh = np.exp(np.cumsum(bh_ret))
peak_bh = np.maximum.accumulate(cum_bh)
dd_bh = (cum_bh - peak_bh) / peak_bh
bh_metrics['max_drawdown'] = round(np.min(dd_bh), 4)
bh_metrics['total_return'] = round(cum_bh[-1] - 1, 4)

print(f"  Buy & Hold:")
print(f"    Sharpe={bh_metrics['sharpe']:.4f}, "
      f"Return={bh_metrics['annual_return']:.4f}, "
      f"MDD={bh_metrics['max_drawdown']:.4f}")

# =============================================================================
# 7. Transition Detection Analysis
# =============================================================================
print("\n\n" + "=" * 70)
print("[6] Transition Detection: Can we catch the 0→1 transitions?")
print("=" * 70)

# Focus on VIX=20 threshold
th = 20
oos_regime = df.loc[oos_mask, f'regime_{th}'].values.astype(int)
oos_trans = df.loc[oos_mask, f'trans_{th}'].values.astype(int)

# For each model, check: when an actual transition happens (0→1),
# did the model predict it 1-5 days before?
for model_name in ['rolling_logistic', 'logistic_regression']:
    if model_name == 'rolling_logistic':
        probs = np.array(results[f'threshold_{th}']['_oos_probs_rolling'])
    else:
        probs = np.array(results[f'threshold_{th}']['_oos_probs_lr'])

    # Find actual transition dates
    trans_dates_idx = np.where(oos_trans == 1)[0]
    print(f"\n  {model_name}: {len(trans_dates_idx)} transitions in OOS")

    # For each transition, check if probability was elevated 1-5 days before
    lead_times = [1, 2, 3, 5]
    for lead in lead_times:
        detected = 0
        total = 0
        for t_idx in trans_dates_idx:
            if t_idx - lead >= 0:
                total += 1
                if probs[t_idx - lead] > 0.5:  # model predicted high vol
                    detected += 1
        if total > 0:
            det_rate = detected / total
            print(f"    {lead}-day lead detection rate: {detected}/{total} = {det_rate:.1%}")
        else:
            print(f"    {lead}-day lead: insufficient data")

# =============================================================================
# 8. Regime Persistence Analysis
# =============================================================================
print("\n\n" + "=" * 70)
print("[7] Regime Persistence Analysis")
print("=" * 70)

for th in thresholds:
    regime = df[f'regime_{th}'].values

    # Calculate run lengths
    runs_high = []
    runs_low = []
    current_run = 1
    for i in range(1, len(regime)):
        if regime[i] == regime[i-1]:
            current_run += 1
        else:
            if regime[i-1] == 1:
                runs_high.append(current_run)
            else:
                runs_low.append(current_run)
            current_run = 1

    if len(runs_high) > 0 and len(runs_low) > 0:
        print(f"\n  VIX > {th}:")
        print(f"    High-vol runs: mean={np.mean(runs_high):.1f}d, "
              f"median={np.median(runs_high):.1f}d, max={np.max(runs_high)}d, "
              f"n={len(runs_high)}")
        print(f"    Low-vol runs:  mean={np.mean(runs_low):.1f}d, "
              f"median={np.median(runs_low):.1f}d, max={np.max(runs_low)}d, "
              f"n={len(runs_low)}")

        # Transition probability
        transitions = np.sum(np.diff(regime.astype(int)) != 0)
        trans_prob = transitions / len(regime)
        print(f"    Daily transition probability: {trans_prob:.4f} ({trans_prob*252:.1f}/year)")

# =============================================================================
# 9. Save Results
# =============================================================================
print("\n\n[8] Saving results...")

# Clean internal arrays from results before saving
clean_results = {}
for th_key, th_data in results.items():
    clean_results[th_key] = {k: v for k, v in th_data.items() if not k.startswith('_')}

final_results = {
    'experiment_id': 'K1019',
    'title': 'VIX Regime Transition Prediction',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{OOS_START} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': len(df),
    'n_is': int(is_mask.sum()),
    'n_oos': int(oos_mask.sum()),
    'seed': 42,
    'classification_results': clean_results,
    'economic_results': econ_results,
    'baselines': {
        '12_over_vix': baseline_metrics,
        'buy_and_hold': bh_metrics,
    },
    'regime_persistence': {},
    'key_findings': [],
}

# Add regime persistence
for th in thresholds:
    regime = df[f'regime_{th}'].values
    runs_high = []
    runs_low = []
    current_run = 1
    for i in range(1, len(regime)):
        if regime[i] == regime[i-1]:
            current_run += 1
        else:
            if regime[i-1] == 1:
                runs_high.append(current_run)
            else:
                runs_low.append(current_run)
            current_run = 1

    if len(runs_high) > 0:
        final_results['regime_persistence'][f'vix_gt_{th}'] = {
            'high_vol_mean_days': round(np.mean(runs_high), 1),
            'high_vol_median_days': round(np.median(runs_high), 1),
            'high_vol_max_days': int(np.max(runs_high)),
            'n_high_episodes': len(runs_high),
            'low_vol_mean_days': round(np.mean(runs_low), 1) if len(runs_low) > 0 else None,
            'n_low_episodes': len(runs_low),
        }

# Determine key findings
# Compare best model vs baseline
best_model_key = None
best_sharpe_improvement = -999
for key, val in econ_results.items():
    for strat_type in ['binary_switch', 'prob_weighted']:
        sharpe_diff = val[strat_type]['sharpe'] - baseline_metrics['sharpe']
        if sharpe_diff > best_sharpe_improvement:
            best_sharpe_improvement = sharpe_diff
            best_model_key = f"{key}_{strat_type}"

# Check: did any model beat naive persistence?
for th in thresholds:
    th_key = f'threshold_{th}'
    naive_f1 = results[th_key]['naive_persistence']['f1']
    best_model_f1 = max(
        results[th_key]['logistic_regression']['f1'],
        results[th_key]['rolling_logistic']['f1'],
        results[th_key]['threshold_model']['f1'],
    )
    beat_naive = best_model_f1 > naive_f1

    finding = (f"VIX>{th}: Best model F1={best_model_f1:.4f} vs Naive persistence F1={naive_f1:.4f}. "
               f"{'Models beat' if beat_naive else 'Models did NOT beat'} naive persistence.")
    final_results['key_findings'].append(finding)

final_results['key_findings'].append(
    f"Best economic model: {best_model_key} with Sharpe improvement of {best_sharpe_improvement:+.4f} vs 12/VIX baseline"
)

# Sharpe sanity check
if best_sharpe_improvement > baseline_metrics['sharpe']:
    final_results['key_findings'].append(
        "WARNING: Best model Sharpe > 2x baseline - possible bug, needs manual review"
    )

# Save JSON
json_path = SCRIPT_DIR / 'k1019_results.json'
with open(json_path, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)
print(f"  Saved to {json_path}")

# =============================================================================
# 10. Plots
# =============================================================================
print("\n[9] Generating plots...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

fig, axes = plt.subplots(4, 1, figsize=(14, 16), height_ratios=[2, 1, 1, 1])

# Plot 1: VIX with regime coloring
ax1 = axes[0]
ax1.plot(dates_oos, vix_oos_full, 'k-', linewidth=0.8, label='VIX')
ax1.axhline(20, color='orange', linestyle='--', alpha=0.7, label='VIX=20')
ax1.axhline(25, color='red', linestyle='--', alpha=0.5, label='VIX=25')
ax1.axhline(30, color='darkred', linestyle='--', alpha=0.5, label='VIX=30')

# Color background by regime
regime_20 = df.loc[oos_mask, 'regime_20'].values
for i in range(len(dates_oos) - 1):
    if regime_20[i] == 1:
        ax1.axvspan(dates_oos[i], dates_oos[i+1], alpha=0.15, color='red')

ax1.set_title('K1019: VIX Regime Timeline (OOS 2019-2026)', fontsize=14, fontweight='bold')
ax1.set_ylabel('VIX Level')
ax1.legend(loc='upper right')
ax1.set_xlim(dates_oos[0], dates_oos[-1])

# Plot 2: Rolling logistic prediction probability (VIX>20)
ax2 = axes[1]
probs_rolling = np.array(results['threshold_20']['_oos_probs_rolling'])
ax2.fill_between(dates_oos, probs_rolling, alpha=0.5, color='steelblue', label='P(VIX>20)')
ax2.axhline(0.5, color='gray', linestyle='--', alpha=0.5)
actual_regime = np.array(results['threshold_20']['_oos_actual'])
ax2.plot(dates_oos, actual_regime, 'r-', linewidth=0.5, alpha=0.5, label='Actual regime')
ax2.set_ylabel('Probability / Regime')
ax2.set_title('Rolling Logistic: Predicted P(VIX>20 tomorrow)')
ax2.legend(loc='upper right')
ax2.set_ylim(-0.05, 1.05)
ax2.set_xlim(dates_oos[0], dates_oos[-1])

# Plot 3: Model comparison bar chart
ax3 = axes[2]
models = ['Logistic', 'Rolling Log.', 'Threshold', 'Naive']
metrics_names = ['Accuracy', 'F1', 'Precision', 'Recall']

th20 = results['threshold_20']
bar_data = {
    'Accuracy': [th20['logistic_regression']['accuracy'], th20['rolling_logistic']['accuracy'],
                 th20['threshold_model']['accuracy'], th20['naive_persistence']['accuracy']],
    'F1': [th20['logistic_regression']['f1'], th20['rolling_logistic']['f1'],
           th20['threshold_model']['f1'], th20['naive_persistence']['f1']],
    'Precision': [th20['logistic_regression']['precision'], th20['rolling_logistic']['precision'],
                  th20['threshold_model']['precision'], th20['naive_persistence']['precision']],
    'Recall': [th20['logistic_regression']['recall'], th20['rolling_logistic']['recall'],
               th20['threshold_model']['recall'], th20['naive_persistence']['recall']],
}

x = np.arange(len(models))
width = 0.2
for i, (metric, vals) in enumerate(bar_data.items()):
    ax3.bar(x + i * width, vals, width, label=metric, alpha=0.8)

ax3.set_ylabel('Score')
ax3.set_title('Model Comparison: VIX > 20 Threshold (OOS)')
ax3.set_xticks(x + 1.5 * width)
ax3.set_xticklabels(models)
ax3.legend()
ax3.set_ylim(0, 1.1)

# Plot 4: Economic value - cumulative returns
ax4 = axes[3]

# Baseline
cum_baseline = np.exp(np.cumsum(baseline_ret)) - 1
ax4.plot(dates_oos, cum_baseline, 'k-', linewidth=1.5, label=f"12/VIX (Sharpe={baseline_metrics['sharpe']:.2f})")

# Buy & hold
cum_bh = np.exp(np.cumsum(bh_ret)) - 1
ax4.plot(dates_oos, cum_bh, 'gray', linewidth=1, alpha=0.6, label=f"Buy&Hold (Sharpe={bh_metrics['sharpe']:.2f})")

# Best regime models
# Rolling logistic, prob-weighted, VIX>20
rl_key = 'rolling_logistic_th20'
if rl_key in econ_results:
    # Reconstruct the strategy returns
    probs_rl = np.array(results['threshold_20']['_oos_probs_rolling'])
    prob_shifted_rl = np.roll(probs_rl, 1)
    prob_shifted_rl[0] = 0.5
    vix_shifted_rl = np.roll(vix_oos_full, 1)
    vix_shifted_rl[0] = vix_oos_full[0]
    base_w_rl = np.clip(12.0 / vix_shifted_rl, 0, 1)
    prob_weight_rl = base_w_rl * (1 - 0.7 * prob_shifted_rl)
    prob_ret_rl = prob_weight_rl * spy_ret_oos
    cum_prob_rl = np.exp(np.cumsum(prob_ret_rl)) - 1
    s = econ_results[rl_key]['prob_weighted']['sharpe']
    ax4.plot(dates_oos, cum_prob_rl, 'b-', linewidth=1.2,
             label=f"Rolling Log. Prob-wt (Sharpe={s:.2f})")

# Binary switch
preds_rl = np.array(results['threshold_20']['_oos_preds_rolling'])
pred_shifted_bin = np.roll(preds_rl, 1)
pred_shifted_bin[0] = 0
binary_weight_plot = np.where(pred_shifted_bin == 1, 0.3, base_w_rl)
binary_ret_plot = binary_weight_plot * spy_ret_oos
cum_binary = np.exp(np.cumsum(binary_ret_plot)) - 1
s_bin = econ_results[rl_key]['binary_switch']['sharpe']
ax4.plot(dates_oos, cum_binary, 'r-', linewidth=1.2,
         label=f"Rolling Log. Binary (Sharpe={s_bin:.2f})")

ax4.set_title('Economic Value: Cumulative Returns (OOS 2019-2026)')
ax4.set_ylabel('Cumulative Return')
ax4.legend(loc='upper left', fontsize=8)
ax4.set_xlim(dates_oos[0], dates_oos[-1])
ax4.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))

for ax in axes:
    ax.grid(True, alpha=0.3)

plt.tight_layout()
plot_path = SCRIPT_DIR / 'k1019_regime_prediction.png'
plt.savefig(plot_path, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Saved plot to {plot_path}")

# =============================================================================
# 11. Summary
# =============================================================================
print("\n\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

print("\nKey Findings:")
for finding in final_results['key_findings']:
    print(f"  - {finding}")

print(f"\nBaseline 12/VIX:  Sharpe={baseline_metrics['sharpe']:.4f}, MDD={baseline_metrics['max_drawdown']:.4f}")
print(f"Buy & Hold:       Sharpe={bh_metrics['sharpe']:.4f}, MDD={bh_metrics['max_drawdown']:.4f}")

print("\nBest regime-based strategies (VIX>20):")
for key in ['logistic_regression_th20', 'rolling_logistic_th20', 'threshold_model_th20']:
    if key in econ_results:
        e = econ_results[key]
        print(f"  {key}:")
        print(f"    Binary:  Sharpe={e['binary_switch']['sharpe']:.4f}, MDD={e['binary_switch']['max_drawdown']:.4f}")
        print(f"    Prob-wt: Sharpe={e['prob_weighted']['sharpe']:.4f}, MDD={e['prob_weighted']['max_drawdown']:.4f}")

print("\nRegime persistence (critical for predictability):")
for th in thresholds:
    p = final_results['regime_persistence'].get(f'vix_gt_{th}', {})
    if p:
        print(f"  VIX > {th}: mean high-vol episode = {p['high_vol_mean_days']}d, "
              f"n={p['n_high_episodes']} episodes")

print(f"\nConclusion:")
print(f"  VIX regimes are highly persistent (mean episode >> 1 day), making naive")
print(f"  persistence a very strong baseline. The key challenge is predicting the")
print(f"  exact transition point, not the regime itself.")
print(f"\nDone.")
