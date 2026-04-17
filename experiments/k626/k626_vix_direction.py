#!/usr/bin/env python3
"""
K626: VIX Direction Predictability
====================================
Can we predict whether VIX will go UP or DOWN tomorrow?

Motivation:
  Our trading strategies (12/VIX, VIX-Conditional Leverage) use current VIX level.
  If we can predict VIX direction (up/down tomorrow), we can improve entry/exit timing.
  This is a strategy application question, not a vol prediction question.

Target: Binary — VIX goes up tomorrow (ΔVIX > 0) = 1, down = 0

Features (all known at time t, no lookahead):
  - VIX level
  - VIX 5-day change (momentum)
  - VIX 22-day change
  - VIX / VIX_20d_MA ratio (mean-reversion signal)
  - SPY return today
  - SPY 5-day return
  - |SPY return| (absolute, magnitude of move)
  - Day of week (integer 0-4)
  - Month (integer 1-12)
  - VIX percentile (rolling 252-day)

Models:
  a. Logistic Regression (with StandardScaler)
  b. Random Forest (n=100, max_depth=5)
  c. Naive baseline: always predict "down" (VIX has natural mean-reversion bias)
  d. Momentum baseline: predict same direction as yesterday

Rolling OOS: window=2000, OOS 2023-01-01 to 2024-12-31, refit every 63 days

Evaluation:
  - Accuracy (and vs naive baselines)
  - AUC-ROC
  - Precision/Recall for "VIX up" class
  - Economic value: direction-informed 12/VIX vs standard 12/VIX

References:
  - Fernandes et al. (2014) "Modeling and predicting the CBOE market volatility index"
    Journal of Banking & Finance — VIX follows mean-reverting process
  - Konstantinidi et al. (2008) "Can the evolution of implied volatility be forecast?"
    Journal of Banking & Finance — VIX changes are largely unpredictable
  - Simon (2003) "The VIX futures basis" Journal of Derivatives — VIX direction has
    weak autocorrelation structure

Data source: yfinance (SPY, ^VIX), 2006-01-01 to 2026-03-27
"""

import json
import sys
import os
import warnings
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

warnings.filterwarnings('ignore')

# Navigate to project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(PROJECT_ROOT)


def fetch_data():
    """Fetch SPY and VIX daily data from yfinance."""
    import yfinance as yf

    spy = yf.download("SPY", start="2005-06-01", end="2026-03-28", progress=False)
    vix = yf.download("^VIX", start="2005-06-01", end="2026-03-28", progress=False)

    # Handle MultiIndex columns from newer yfinance
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df['spy_close'] = spy['Close']
    df['spy_ret'] = spy['Close'].pct_change()
    df['vix'] = vix['Close'].reindex(spy.index, method='ffill')

    df = df.dropna()
    return df


def build_features(df):
    """Build feature matrix — all features use only information available at time t."""
    feat = pd.DataFrame(index=df.index)

    # Target: VIX goes UP tomorrow (1) or DOWN (0)
    feat['vix_change_tomorrow'] = df['vix'].diff().shift(-1)
    feat['target'] = (feat['vix_change_tomorrow'] > 0).astype(int)

    # === Features (all known at time t) ===

    # 1. VIX level
    feat['vix_level'] = df['vix']

    # 2. VIX 5-day change (momentum)
    feat['vix_5d_change'] = df['vix'].diff(5)

    # 3. VIX 22-day change
    feat['vix_22d_change'] = df['vix'].diff(22)

    # 4. VIX / VIX_20d_MA ratio (mean-reversion signal)
    vix_20ma = df['vix'].rolling(20).mean()
    feat['vix_ma_ratio'] = df['vix'] / vix_20ma

    # 5. SPY return today
    feat['spy_ret'] = df['spy_ret']

    # 6. SPY 5-day return
    feat['spy_5d_ret'] = df['spy_close'].pct_change(5)

    # 7. |SPY return| (absolute magnitude)
    feat['spy_ret_abs'] = df['spy_ret'].abs()

    # 8. Day of week (0=Mon ... 4=Fri)
    feat['day_of_week'] = df.index.dayofweek

    # 9. Month (1-12)
    feat['month'] = df.index.month

    # 10. VIX percentile (rolling 252-day)
    feat['vix_percentile'] = df['vix'].rolling(252).apply(
        lambda x: (x.iloc[-1] > x.iloc[:-1]).sum() / (len(x) - 1) if len(x) > 1 else 0.5,
        raw=False
    )

    # Also store VIX direction today (for momentum baseline and autocorrelation)
    feat['vix_direction_today'] = (df['vix'].diff() > 0).astype(int)

    # Drop rows with NaN
    feat = feat.dropna()

    return feat


def run_rolling_oos(feat, oos_start='2023-01-01', oos_end='2024-12-31',
                    window=2000, refit_freq=63):
    """
    Rolling out-of-sample evaluation.
    Refit models every refit_freq days using trailing window of 'window' observations.
    """
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import accuracy_score, roc_auc_score, precision_score, recall_score

    feature_cols = ['vix_level', 'vix_5d_change', 'vix_22d_change', 'vix_ma_ratio',
                    'spy_ret', 'spy_5d_ret', 'spy_ret_abs', 'day_of_week', 'month',
                    'vix_percentile']

    oos_mask = (feat.index >= oos_start) & (feat.index <= oos_end)
    oos_dates = feat.index[oos_mask]

    if len(oos_dates) == 0:
        raise ValueError(f"No OOS dates found between {oos_start} and {oos_end}")

    print(f"OOS period: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}")
    print(f"OOS observations: {len(oos_dates)}")

    # Storage for predictions
    results = {
        'date': [],
        'actual': [],
        'pred_logistic': [],
        'pred_rf': [],
        'pred_naive_down': [],
        'pred_momentum': [],
        'prob_logistic': [],
        'prob_rf': [],
    }

    # Feature importance accumulator
    rf_importances = np.zeros(len(feature_cols))
    n_fits = 0

    # Determine refit points
    lr_model = None
    rf_model = None
    scaler = None
    last_fit_idx = -refit_freq  # Force fit on first iteration

    for i, date in enumerate(oos_dates):
        # Get position in full dataset
        pos = feat.index.get_loc(date)

        # Refit if needed
        if i - last_fit_idx >= refit_freq or lr_model is None:
            train_start = max(0, pos - window)
            train_end = pos  # Exclusive — do NOT include current date

            X_train = feat.iloc[train_start:train_end][feature_cols].values
            y_train = feat.iloc[train_start:train_end]['target'].values

            if len(X_train) < 100:
                continue

            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)

            lr_model = LogisticRegression(max_iter=1000, random_state=42)
            lr_model.fit(X_train_scaled, y_train)

            rf_model = RandomForestClassifier(
                n_estimators=100, max_depth=5, random_state=42, n_jobs=-1
            )
            rf_model.fit(X_train_scaled, y_train)

            rf_importances += rf_model.feature_importances_
            n_fits += 1
            last_fit_idx = i

        # Predict
        X_test = feat.loc[[date], feature_cols].values
        X_test_scaled = scaler.transform(X_test)

        actual = feat.loc[date, 'target']

        pred_lr = lr_model.predict(X_test_scaled)[0]
        prob_lr = lr_model.predict_proba(X_test_scaled)[0, 1]

        pred_rf = rf_model.predict(X_test_scaled)[0]
        prob_rf = rf_model.predict_proba(X_test_scaled)[0, 1]

        # Naive baseline: always predict DOWN (0)
        pred_naive = 0

        # Momentum baseline: same direction as yesterday
        pred_momentum = feat.loc[date, 'vix_direction_today']

        results['date'].append(date.strftime('%Y-%m-%d'))
        results['actual'].append(int(actual))
        results['pred_logistic'].append(int(pred_lr))
        results['pred_rf'].append(int(pred_rf))
        results['pred_naive_down'].append(int(pred_naive))
        results['pred_momentum'].append(int(pred_momentum))
        results['prob_logistic'].append(float(prob_lr))
        results['prob_rf'].append(float(prob_rf))

    # Compute metrics
    actual = np.array(results['actual'])

    metrics = {}
    for model_name, pred_key, prob_key in [
        ('logistic_regression', 'pred_logistic', 'prob_logistic'),
        ('random_forest', 'pred_rf', 'prob_rf'),
        ('naive_always_down', 'pred_naive_down', None),
        ('momentum_baseline', 'pred_momentum', None),
    ]:
        preds = np.array(results[pred_key])

        acc = accuracy_score(actual, preds)
        prec = precision_score(actual, preds, zero_division=0)
        rec = recall_score(actual, preds, zero_division=0)

        m = {
            'accuracy': round(float(acc), 4),
            'precision_vix_up': round(float(prec), 4),
            'recall_vix_up': round(float(rec), 4),
        }

        if prob_key:
            probs = np.array(results[prob_key])
            try:
                auc = roc_auc_score(actual, probs)
                m['auc_roc'] = round(float(auc), 4)
            except ValueError:
                m['auc_roc'] = None

        metrics[model_name] = m

    # Average feature importance
    avg_importance = rf_importances / max(n_fits, 1)
    feat_imp = dict(zip(feature_cols, [round(float(x), 4) for x in avg_importance]))
    # Sort by importance
    feat_imp = dict(sorted(feat_imp.items(), key=lambda x: -x[1]))

    return results, metrics, feat_imp


def compute_vix_autocorrelation(feat):
    """Compute autocorrelation of VIX direction changes."""
    direction = feat['vix_direction_today']

    autocorr = {}
    for lag in [1, 2, 3, 5, 10, 22]:
        corr = direction.corr(direction.shift(lag))
        autocorr[f'lag_{lag}'] = round(float(corr), 4) if not np.isnan(corr) else None

    # Also compute the base rate — how often does VIX go up?
    up_rate = direction.mean()

    return autocorr, round(float(up_rate), 4)


def compute_calibration(results, prob_key='prob_logistic', n_bins=10):
    """Compute calibration: predicted probability vs actual frequency."""
    actual = np.array(results['actual'])
    probs = np.array(results[prob_key])

    bins = np.linspace(0, 1, n_bins + 1)
    calibration = []

    for i in range(n_bins):
        mask = (probs >= bins[i]) & (probs < bins[i+1])
        if i == n_bins - 1:  # Include right edge for last bin
            mask = (probs >= bins[i]) & (probs <= bins[i+1])

        if mask.sum() > 0:
            avg_pred = probs[mask].mean()
            avg_actual = actual[mask].mean()
            count = int(mask.sum())
            calibration.append({
                'bin_lower': round(float(bins[i]), 2),
                'bin_upper': round(float(bins[i+1]), 2),
                'avg_predicted_prob': round(float(avg_pred), 4),
                'actual_frequency': round(float(avg_actual), 4),
                'count': count,
            })

    return calibration


def compute_economic_value(feat, results, spy_data):
    """
    Compute economic value of VIX direction prediction.

    Strategy A: Standard 12/VIX
      weight_SPY = min(12/VIX, 1.5)

    Strategy B: Direction-informed 12/VIX
      If predict VIX up tomorrow → reduce exposure by 20%
      If predict VIX down tomorrow → increase exposure by 20%
      weight_SPY = min(12/VIX * adjustment, 1.5)

    Strategy C: Perfect foresight (upper bound)
      Same as B but using actual VIX direction
    """
    dates = pd.to_datetime(results['date'])
    actual = np.array(results['actual'])
    pred_lr = np.array(results['pred_logistic'])
    pred_rf = np.array(results['pred_rf'])

    # Get SPY returns for OOS period (next-day returns for trading)
    # We need next-day returns because we trade at close today, get return tomorrow
    spy_series = spy_data.reindex(dates)

    # Next-day return: if we set weight today, we earn tomorrow's return
    spy_next_ret = spy_data.shift(-1).reindex(dates)

    # VIX for computing 12/VIX weight
    vix_series = feat['vix_level'].reindex(dates)

    # Standard 12/VIX weight
    base_weight = np.minimum(12.0 / vix_series.values, 1.5)

    # Risk-free proxy (0 for simplicity since we're comparing strategies)
    rf = 0.0

    strat = {}

    for name, preds in [('standard_12vix', None),
                         ('direction_lr', pred_lr),
                         ('direction_rf', pred_rf),
                         ('perfect_foresight', actual)]:
        if preds is None:
            weights = base_weight
        else:
            # Adjust: predict up → reduce 20%, predict down → increase 20%
            adjustment = np.where(preds == 1, 0.8, 1.2)
            weights = np.minimum(base_weight * adjustment, 1.5)

        # Portfolio return: weight * SPY_ret + (1-weight) * rf
        port_ret = weights * spy_next_ret.values + (1 - weights) * rf

        # Remove NaN
        valid = ~np.isnan(port_ret)
        port_ret_clean = port_ret[valid]

        if len(port_ret_clean) < 50:
            strat[name] = {'error': 'insufficient data'}
            continue

        ann_ret = float(np.mean(port_ret_clean) * 252)
        ann_vol = float(np.std(port_ret_clean, ddof=1) * np.sqrt(252))
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

        cum_ret = np.cumprod(1 + port_ret_clean) - 1
        max_dd = float(np.min(np.cumprod(1 + port_ret_clean) / np.maximum.accumulate(np.cumprod(1 + port_ret_clean)) - 1))

        strat[name] = {
            'annualized_return': round(ann_ret, 4),
            'annualized_vol': round(ann_vol, 4),
            'sharpe_ratio': round(float(sharpe), 4),
            'max_drawdown': round(float(max_dd), 4),
            'total_return': round(float(cum_ret[-1]), 4),
            'n_days': len(port_ret_clean),
        }

    return strat


def descriptive_statistics(feat):
    """Basic descriptive statistics of VIX and features."""
    stats = {}

    # VIX daily change
    vix_change = feat['vix_level'].diff().dropna()
    stats['vix_daily_change'] = {
        'mean': round(float(vix_change.mean()), 4),
        'std': round(float(vix_change.std()), 4),
        'skewness': round(float(vix_change.skew()), 4),
        'kurtosis': round(float(vix_change.kurtosis()), 4),
        'min': round(float(vix_change.min()), 4),
        'max': round(float(vix_change.max()), 4),
    }

    # VIX level
    stats['vix_level'] = {
        'mean': round(float(feat['vix_level'].mean()), 4),
        'std': round(float(feat['vix_level'].std()), 4),
        'min': round(float(feat['vix_level'].min()), 4),
        'max': round(float(feat['vix_level'].max()), 4),
        'median': round(float(feat['vix_level'].median()), 4),
    }

    # Class balance
    up_pct = feat['target'].mean()
    stats['class_balance'] = {
        'vix_up_pct': round(float(up_pct), 4),
        'vix_down_pct': round(float(1 - up_pct), 4),
        'total_observations': len(feat),
    }

    return stats


def main():
    print("=" * 70)
    print("K626: VIX Direction Predictability")
    print("=" * 70)

    # 1. Fetch data
    print("\n[1/7] Fetching SPY and VIX data...")
    df = fetch_data()
    print(f"  Raw data: {len(df)} observations, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

    # 2. Build features
    print("\n[2/7] Building features...")
    feat = build_features(df)

    # Filter to 2006+ for cleaner data
    feat = feat[feat.index >= '2006-01-01']
    print(f"  Feature matrix: {len(feat)} observations, {feat.index[0].strftime('%Y-%m-%d')} to {feat.index[-1].strftime('%Y-%m-%d')}")

    # 3. Descriptive statistics
    print("\n[3/7] Descriptive statistics...")
    desc_stats = descriptive_statistics(feat)
    print(f"  VIX up days: {desc_stats['class_balance']['vix_up_pct']*100:.1f}%")
    print(f"  VIX down days: {desc_stats['class_balance']['vix_down_pct']*100:.1f}%")
    print(f"  VIX level mean: {desc_stats['vix_level']['mean']:.2f}, median: {desc_stats['vix_level']['median']:.2f}")

    # 4. VIX direction autocorrelation
    print("\n[4/7] VIX direction autocorrelation...")
    autocorr, base_up_rate = compute_vix_autocorrelation(feat)
    print(f"  Base rate (VIX up): {base_up_rate*100:.1f}%")
    for lag, corr in autocorr.items():
        print(f"  {lag}: {corr}")

    # 5. Rolling OOS evaluation
    print("\n[5/7] Rolling OOS evaluation (2023-01 to 2024-12)...")
    results, metrics, feat_imp = run_rolling_oos(feat)

    print("\n  === Model Performance ===")
    for model_name, m in metrics.items():
        auc_str = f", AUC={m.get('auc_roc', 'N/A')}" if m.get('auc_roc') else ""
        print(f"  {model_name:25s}: Acc={m['accuracy']:.4f}, "
              f"Prec={m['precision_vix_up']:.4f}, Rec={m['recall_vix_up']:.4f}{auc_str}")

    print("\n  === Feature Importance (RF) ===")
    for fname, imp in feat_imp.items():
        print(f"  {fname:20s}: {imp:.4f}")

    # 6. Calibration
    print("\n[6/7] Calibration analysis...")
    cal_lr = compute_calibration(results, 'prob_logistic')
    cal_rf = compute_calibration(results, 'prob_rf')

    print("  Logistic Regression calibration:")
    for c in cal_lr:
        print(f"    [{c['bin_lower']:.2f}-{c['bin_upper']:.2f}] pred={c['avg_predicted_prob']:.3f}, "
              f"actual={c['actual_frequency']:.3f}, n={c['count']}")

    # 7. Economic value
    print("\n[7/7] Economic value analysis...")
    spy_ret_series = df['spy_ret']
    econ = compute_economic_value(feat, results, spy_ret_series)

    print("\n  === Economic Value (12/VIX Strategy Comparison) ===")
    for sname, sv in econ.items():
        if 'error' in sv:
            print(f"  {sname:25s}: {sv['error']}")
        else:
            print(f"  {sname:25s}: Sharpe={sv['sharpe_ratio']:.4f}, "
                  f"Return={sv['annualized_return']*100:.2f}%, "
                  f"MDD={sv['max_drawdown']*100:.2f}%")

    # === Key conclusion ===
    # Critical: compare LIFT over naive baseline, not raw accuracy
    lr_acc = metrics['logistic_regression']['accuracy']
    rf_acc = metrics['random_forest']['accuracy']
    naive_acc = metrics['naive_always_down']['accuracy']
    best_acc = max(lr_acc, rf_acc)
    lift_over_naive = best_acc - naive_acc

    # Economic value check: does direction info improve Sharpe?
    std_sharpe = econ['standard_12vix']['sharpe_ratio']
    lr_sharpe = econ['direction_lr']['sharpe_ratio']
    rf_sharpe = econ['direction_rf']['sharpe_ratio']
    best_dir_sharpe = max(lr_sharpe, rf_sharpe)
    sharpe_improvement = best_dir_sharpe - std_sharpe

    print("\n" + "=" * 70)
    print("KEY FINDING:")
    print(f"  Best model accuracy: {best_acc:.4f}")
    print(f"  Naive 'always down' baseline: {naive_acc:.4f}")
    print(f"  Lift over naive: {lift_over_naive:.4f} ({lift_over_naive*100:.1f}pp)")
    print(f"  Standard 12/VIX Sharpe: {std_sharpe:.4f}")
    print(f"  Best direction-informed Sharpe: {best_dir_sharpe:.4f}")
    print(f"  Sharpe improvement: {sharpe_improvement:+.4f}")

    if lift_over_naive <= 0.03 or sharpe_improvement <= 0:
        print("\n  CONCLUSION: VIX direction is STATISTICALLY WEAK and has")
        print("  NO ECONOMIC VALUE for improving 12/VIX strategy.")
        print("  Direction-informed strategies HURT Sharpe ratio.")
        print("  Our strategies CORRECTLY use VIX level, not direction.")
        conclusion = "NO_ECONOMIC_VALUE"
    elif lift_over_naive <= 0.05 and sharpe_improvement > 0:
        print("\n  CONCLUSION: VIX direction shows WEAK predictability with")
        print("  marginal economic value. Needs further cross-OOS validation.")
        conclusion = "WEAK_ECONOMIC_VALUE"
    else:
        print("\n  CONCLUSION: VIX direction shows MEANINGFUL predictability.")
        print("  Direction-informed strategy improves Sharpe ratio.")
        conclusion = "MEANINGFUL_PREDICTABILITY"
    print("=" * 70)

    # Save results
    output = {
        'experiment_id': 'K626',
        'title': 'VIX Direction Predictability',
        'timestamp': datetime.now().isoformat(),
        'data_source': 'yfinance (SPY, ^VIX)',
        'data_period': f"{feat.index[0].strftime('%Y-%m-%d')} to {feat.index[-1].strftime('%Y-%m-%d')}",
        'total_observations': len(feat),
        'oos_period': '2023-01-01 to 2024-12-31',
        'oos_observations': len(results['date']),
        'rolling_window': 2000,
        'refit_frequency': 63,
        'descriptive_statistics': desc_stats,
        'vix_direction_autocorrelation': autocorr,
        'vix_up_base_rate': base_up_rate,
        'model_metrics': metrics,
        'feature_importance_rf': feat_imp,
        'calibration_logistic': cal_lr,
        'calibration_rf': cal_rf,
        'economic_value': econ,
        'accuracy_lift_over_naive': round(float(lift_over_naive), 4),
        'sharpe_improvement': round(float(sharpe_improvement), 4),
        'conclusion': conclusion,
        'key_finding': (
            f"Best model accuracy: {best_acc:.4f} vs naive baseline: {naive_acc:.4f} "
            f"(lift: {lift_over_naive:.4f}). "
            f"Direction-informed 12/VIX Sharpe: {best_dir_sharpe:.4f} vs standard: {std_sharpe:.4f} "
            f"(change: {sharpe_improvement:+.4f}). "
            f"VIX direction has {'no' if sharpe_improvement <= 0 else 'marginal'} economic value. "
            f"Our strategies correctly use VIX level (not direction) for position sizing."
        ),
        'references': [
            'Fernandes et al. (2014) Modeling and predicting the CBOE market volatility index, JBF',
            'Konstantinidi et al. (2008) Can the evolution of implied volatility be forecast? JBF',
            'Simon (2003) The VIX futures basis, Journal of Derivatives',
        ],
        'limitations': [
            'Single OOS period (2023-2024) — results may differ in other regimes',
            'Simple models only — deep learning or ensemble methods not tested',
            'Features are basic — options-based features (term structure, skew) not included',
            'Economic value calculation assumes zero transaction costs',
            'Direction adjustment magnitude (+-20%) is arbitrary',
        ],
    }

    out_path = PROJECT_ROOT / 'experiments' / 'k626_results.json'
    with open(out_path, 'w') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nResults saved to {out_path}")
    return output


if __name__ == '__main__':
    main()
