"""
K541: Weekly Meta-Labeling for VT — Can we predict VT outperformance at weekly frequency?
[提出: 用戶, 執行: Claude]

Motivation: K538 showed daily meta-labeling is pure noise (AUC 0.48-0.52). But weekly
aggregation could reveal patterns: VT's insurance premium (~4%/yr) accumulates over
weeks/months, not days. Weekly frequency reduces daily noise and may expose the
structural VT edge in high-vol regimes.

References:
- López de Prado, M. (2018). "Advances in Financial Machine Learning." Wiley, Ch.3.
- Luo et al. (2023). "Meta-Labeling: Theory and Framework." SSRN 4428790.
- K538: Daily meta-labeling = noise (AUC 0.48-0.52, all 16 features |r|<0.02).
- K65/K279: Weekly VT frequency analysis.
- K142/K46: VT ≈ trend following, premium ~4%/yr.

Data source: yfinance (SPY, ^VIX, ^VIX3M, TLT, GLD)
Period: 2007-01-01 to 2025-12-31
OOS: 2020-2024 split into 3 sub-periods
Train: rolling 104-week (2-year) window

Methodology:
1. Compute WEEKLY returns for VT (12/VIX on SPY) and B&H
2. Binary label: y_w = 1 if VT_weekly_return > BH_weekly_return
3. Features (all end-of-prior-week, no look-ahead):
   - VIX level (Friday close)
   - VIX 4-week change
   - VIX percentile (52-week rolling)
   - SPY 4-week return
   - SPY 13-week return
   - VIX term structure (VIX/VIX3M)
   - Prior 4-week VT outperformance (cumulative)
   - HAR-style weekly realized vol
4. Models: Logistic Regression + XGBoost
5. Strategy: if P(VT > BH) > threshold → VT, else → B&H
6. Evaluate: weekly Sharpe, MDD, win rate, net of TX cost
"""

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
import json
import os
from datetime import datetime, timezone
from scipy import stats

from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    roc_auc_score, brier_score_loss
)
import xgboost as xgb

warnings.filterwarnings('ignore')

print("=" * 70)
print("K541: Weekly Meta-Labeling for VT — Weekly Frequency Prediction")
print("[提出: 用戶, 執行: Claude]")
print("=" * 70)

# ─────────────────────────────────────────────────
# 1. DATA COLLECTION
# ─────────────────────────────────────────────────
print("\n[1/8] Downloading data from yfinance...")
tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'VIX3M': '^VIX3M',
    'TLT': 'TLT',
    'GLD': 'GLD',
}

data = {}
for name, ticker in tickers.items():
    df = yf.download(ticker, start="2006-01-01", end="2026-01-01",
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    data[name] = df
    print(f"  {name}: {len(df)} rows, {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}")

# Align to common dates
common = data['SPY'].index.intersection(data['VIX'].index)
for name in ['VIX3M', 'TLT', 'GLD']:
    if len(data[name]) > 0:
        common = common.intersection(data[name].index)
common = common.sort_values()
print(f"  Common dates: {len(common)} ({common[0].strftime('%Y-%m-%d')} to {common[-1].strftime('%Y-%m-%d')})")

spy_close = data['SPY'].loc[common, 'Close']
vix_close = data['VIX'].loc[common, 'Close']
vix3m_close = data['VIX3M'].loc[common, 'Close'] if 'VIX3M' in data else None
tlt_close = data['TLT'].loc[common, 'Close']
gld_close = data['GLD'].loc[common, 'Close']

spy_ret_daily = spy_close.pct_change()

# ─────────────────────────────────────────────────
# 2. DAILY VT CONSTRUCTION (for weekly aggregation)
# ─────────────────────────────────────────────────
print("\n[2/8] Constructing daily VT returns for weekly aggregation...")

# 12/VIX weight, clipped at [0, 1.5]
vt_weight_daily = (12.0 / vix_close).clip(0, 1.5)

# VT return: weight(t-1) * SPY_return(t) (no look-ahead)
vt_ret_daily = vt_weight_daily.shift(1) * spy_ret_daily
bh_ret_daily = spy_ret_daily.copy()

# Daily realized vol (for HAR-style feature)
spy_abs_ret = spy_ret_daily.abs()

print(f"  Daily VT mean: {vt_ret_daily.dropna().mean()*252:.4f} ann.")
print(f"  Daily BH mean: {bh_ret_daily.dropna().mean()*252:.4f} ann.")

# ─────────────────────────────────────────────────
# 3. WEEKLY AGGREGATION
# ─────────────────────────────────────────────────
print("\n[3/8] Aggregating to weekly frequency (Friday-to-Friday)...")

# Resample to weekly (Friday end)
# Weekly return = compounded daily returns within the week
def compound_returns(daily_rets, freq='W-FRI'):
    """Compound daily returns to weekly."""
    return (1 + daily_rets).resample(freq).prod() - 1

vt_ret_weekly = compound_returns(vt_ret_daily.dropna())
bh_ret_weekly = compound_returns(bh_ret_daily.dropna())

# Weekly excess return
excess_weekly = vt_ret_weekly - bh_ret_weekly

# Friday close values for features
vix_weekly = vix_close.resample('W-FRI').last()
vix3m_weekly = vix3m_close.resample('W-FRI').last() if vix3m_close is not None else None
spy_weekly = spy_close.resample('W-FRI').last()
tlt_weekly = tlt_close.resample('W-FRI').last()
gld_weekly = gld_close.resample('W-FRI').last()

# Weekly realized vol (sum of daily |r| within week, annualized)
rv_weekly = spy_abs_ret.resample('W-FRI').sum() * np.sqrt(52)

# Weekly VT weight (Friday close value)
vt_weight_weekly = vt_weight_daily.resample('W-FRI').last()

# Align all weekly series
common_weekly = vt_ret_weekly.dropna().index
for s in [bh_ret_weekly, vix_weekly, spy_weekly, rv_weekly, vt_weight_weekly]:
    common_weekly = common_weekly.intersection(s.dropna().index)
if vix3m_weekly is not None:
    common_weekly = common_weekly.intersection(vix3m_weekly.dropna().index)
common_weekly = common_weekly.sort_values()

print(f"  Weekly observations: {len(common_weekly)}")
print(f"  Period: {common_weekly[0].strftime('%Y-%m-%d')} to {common_weekly[-1].strftime('%Y-%m-%d')}")

# Restrict to common weekly dates
vt_ret_w = vt_ret_weekly.loc[common_weekly]
bh_ret_w = bh_ret_weekly.loc[common_weekly]
excess_w = excess_weekly.loc[common_weekly]
vix_w = vix_weekly.loc[common_weekly]
spy_w = spy_weekly.loc[common_weekly]
rv_w = rv_weekly.loc[common_weekly]
wt_w = vt_weight_weekly.loc[common_weekly]

# Label: 1 if VT outperforms BH NEXT week
label_w = (excess_w.shift(-1) > 0).astype(int)

print(f"  Label balance: {label_w.dropna().mean():.3f} (fraction of weeks VT > BH)")
print(f"  Mean weekly excess: {excess_w.mean()*52:.4f} ann. ({excess_w.mean()*10000:.2f} bps/wk)")

# ─────────────────────────────────────────────────
# 4. FEATURE ENGINEERING (weekly)
# ─────────────────────────────────────────────────
print("\n[4/8] Engineering weekly features (all lagged, no look-ahead)...")

feat = pd.DataFrame(index=common_weekly)

# --- VIX-based features ---
feat['vix_level'] = vix_w
feat['vix_log'] = np.log(vix_w)
feat['vix_4w_change'] = vix_w.pct_change(4)
feat['vix_13w_change'] = vix_w.pct_change(13)
feat['vix_52w_pctile'] = vix_w.rolling(52).rank(pct=True)

# --- VIX term structure ---
if vix3m_weekly is not None:
    vix3m_w = vix3m_weekly.loc[common_weekly]
    feat['vix_term_ratio'] = vix_w / vix3m_w
    feat['vix_term_slope'] = vix3m_w - vix_w  # positive = contango = calm

# --- SPY momentum ---
spy_wret = spy_w.pct_change()
feat['spy_1w_ret'] = spy_wret
feat['spy_4w_ret'] = spy_w.pct_change(4)
feat['spy_13w_ret'] = spy_w.pct_change(13)

# --- Realized vol (HAR-style) ---
feat['rv_1w'] = rv_w
feat['rv_4w_avg'] = rv_w.rolling(4).mean()
feat['rv_13w_avg'] = rv_w.rolling(13).mean()

# --- VT outperformance history ---
feat['vt_excess_4w'] = excess_w.rolling(4).sum()
feat['vt_excess_13w'] = excess_w.rolling(13).sum()
feat['vt_win_rate_4w'] = (excess_w > 0).rolling(4).mean()
feat['vt_win_rate_13w'] = (excess_w > 0).rolling(13).mean()

# --- Cross-asset features ---
if tlt_weekly is not None:
    tlt_w = tlt_weekly.loc[common_weekly]
    tlt_wret = tlt_w.pct_change()
    feat['tlt_4w_vol'] = tlt_wret.rolling(4).std() * np.sqrt(52)
if gld_weekly is not None:
    gld_w = gld_weekly.loc[common_weekly]
    gld_wret = gld_w.pct_change()
    feat['gld_4w_vol'] = gld_wret.rolling(4).std() * np.sqrt(52)

# --- VT weight (regime proxy) ---
feat['vt_weight'] = wt_w

# Lag all features by 1 week (use prior week's info to predict next week)
feat = feat.shift(1)

# Add second lag for momentum
feat['vix_level_lag2w'] = vix_w.shift(2)
feat['spy_ret_lag2w'] = spy_wret.shift(2)

# Keep only features with sufficient data
feature_cols = [c for c in feat.columns if feat[c].notna().sum() > len(feat) * 0.5]
feat = feat[feature_cols]

# Align with labels
valid_mask = feat.notna().all(axis=1) & label_w.notna()
feat_valid = feat[valid_mask]
label_valid = label_w[valid_mask]
vt_ret_valid = vt_ret_w[valid_mask]
bh_ret_valid = bh_ret_w[valid_mask]
excess_valid = excess_w[valid_mask]

print(f"  Features: {len(feature_cols)} columns")
print(f"  Valid weeks: {len(feat_valid)}")
print(f"  Date range: {feat_valid.index[0].strftime('%Y-%m-%d')} to {feat_valid.index[-1].strftime('%Y-%m-%d')}")

# ─────────────────────────────────────────────────
# 5. FEATURE ANALYSIS
# ─────────────────────────────────────────────────
print("\n[5/8] Feature-label correlations (weekly)...")

correlations = {}
for col in feature_cols:
    r, p = stats.pointbiserialr(label_valid.values, feat_valid[col].values)
    correlations[col] = {'r': float(r), 'p': float(p)}
    sig = "***" if p < 0.001 else "**" if p < 0.01 else "*" if p < 0.05 else ""
    print(f"  {col:25s}: r={r:+.4f}  p={p:.4f} {sig}")

# Compare to K538 daily correlations (all |r| < 0.02)
max_corr_feat = max(correlations, key=lambda k: abs(correlations[k]['r']))
max_corr_val = correlations[max_corr_feat]['r']
print(f"\n  Strongest feature: {max_corr_feat} (r={max_corr_val:+.4f})")
print(f"  K538 daily max |r| was < 0.02 — weekly improvement: {abs(max_corr_val)/0.02:.1f}x")

# ─────────────────────────────────────────────────
# 6. WALK-FORWARD EVALUATION
# ─────────────────────────────────────────────────
print("\n[6/8] Walk-forward evaluation (rolling 104-week train, 3 OOS sub-periods)...")

TRAIN_WEEKS = 104  # 2 years
EMBARGO_WEEKS = 4  # 1 month gap between train and test
THRESHOLD_GRID = [0.40, 0.42, 0.44, 0.46, 0.48, 0.50, 0.52, 0.54, 0.56, 0.58, 0.60]

# OOS periods: 2020-2021, 2022-2023, 2024
oos_periods = [
    ("2020-01-01", "2021-12-31", "2020-2021 (COVID+Recovery)"),
    ("2022-01-01", "2023-06-30", "2022-H1'23 (Bear+Recovery)"),
    ("2023-07-01", "2024-12-31", "H2'23-2024 (Bull)"),
]

all_dates = feat_valid.index
X_all = feat_valid.values
y_all = label_valid.values

results_by_model = {}

for model_name in ['logistic', 'xgboost']:
    print(f"\n  --- {model_name.upper()} ---")

    all_preds = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    all_labels_oos = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    all_vt_oos = pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    all_bh_oos = pd.Series(dtype=float, index=pd.DatetimeIndex([]))

    period_results = []

    for oos_start, oos_end, oos_name in oos_periods:
        oos_mask = (all_dates >= oos_start) & (all_dates <= oos_end)
        oos_idx = np.where(oos_mask)[0]

        if len(oos_idx) == 0:
            print(f"    {oos_name}: no data, skipping")
            continue

        print(f"    {oos_name}: {len(oos_idx)} weeks")

        # Rolling walk-forward within this OOS period
        predictions = []
        actuals = []
        pred_dates = []

        for i in oos_idx:
            # Train on prior TRAIN_WEEKS, with EMBARGO gap
            train_end = i - EMBARGO_WEEKS
            train_start = max(0, train_end - TRAIN_WEEKS)

            if train_end <= train_start or train_end < 0:
                continue

            X_train = X_all[train_start:train_end]
            y_train = y_all[train_start:train_end]
            X_test = X_all[i:i+1]

            if len(X_train) < 52:  # need at least 1 year
                continue

            # Standardize
            scaler = StandardScaler()
            X_train_sc = scaler.fit_transform(X_train)
            X_test_sc = scaler.transform(X_test)

            # Fit model
            if model_name == 'logistic':
                model = LogisticRegression(C=1.0, max_iter=1000, random_state=42)
                model.fit(X_train_sc, y_train)
                prob = model.predict_proba(X_test_sc)[0, 1]
            elif model_name == 'xgboost':
                model = xgb.XGBClassifier(
                    n_estimators=100,
                    max_depth=3,
                    learning_rate=0.05,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    random_state=42,
                    use_label_encoder=False,
                    eval_metric='logloss',
                    verbosity=0,
                )
                model.fit(X_train_sc, y_train)
                prob = model.predict_proba(X_test_sc)[0, 1]

            predictions.append(prob)
            actuals.append(y_all[i])
            pred_dates.append(all_dates[i])

        if len(predictions) < 10:
            print(f"    Skipping {oos_name}: too few predictions ({len(predictions)})")
            continue

        preds_s = pd.Series(predictions, index=pred_dates)
        acts_s = pd.Series(actuals, index=pred_dates)
        vt_s = vt_ret_valid.loc[pred_dates]
        bh_s = bh_ret_valid.loc[pred_dates]

        # Classification metrics
        pred_binary = (preds_s > 0.5).astype(int)
        acc = accuracy_score(acts_s, pred_binary)
        try:
            auc = roc_auc_score(acts_s, preds_s)
        except:
            auc = 0.5
        brier = brier_score_loss(acts_s, preds_s)

        print(f"    Accuracy: {acc:.3f}, AUC: {auc:.3f}, Brier: {brier:.4f}")

        # Optimal threshold (on this period — in-period for diagnostic, not used for trading)
        best_sharpe = -999
        best_thresh = 0.5
        for thresh in THRESHOLD_GRID:
            use_vt = (preds_s > thresh).astype(int)
            strat_ret = use_vt * vt_s + (1 - use_vt) * bh_s
            sr = strat_ret.mean() / strat_ret.std() * np.sqrt(52) if strat_ret.std() > 0 else 0
            if sr > best_sharpe:
                best_sharpe = sr
                best_thresh = thresh

        # Strategy returns at optimal threshold
        use_vt_opt = (preds_s > best_thresh).astype(int)
        strat_ret_opt = use_vt_opt * vt_s + (1 - use_vt_opt) * bh_s

        # Pure VT and B&H benchmarks
        vt_sharpe = vt_s.mean() / vt_s.std() * np.sqrt(52) if vt_s.std() > 0 else 0
        bh_sharpe = bh_s.mean() / bh_s.std() * np.sqrt(52) if bh_s.std() > 0 else 0

        # VT fraction
        vt_frac = use_vt_opt.mean()

        # Cumulative returns
        strat_cum = (1 + strat_ret_opt).cumprod().iloc[-1]
        vt_cum = (1 + vt_s).cumprod().iloc[-1]
        bh_cum = (1 + bh_s).cumprod().iloc[-1]

        # Max drawdown (weekly)
        def max_drawdown(rets):
            cum = (1 + rets).cumprod()
            peak = cum.cummax()
            dd = (cum - peak) / peak
            return dd.min()

        strat_mdd = max_drawdown(strat_ret_opt)
        vt_mdd = max_drawdown(vt_s)
        bh_mdd = max_drawdown(bh_s)

        # TX cost: count switches * 10bps
        switches = (use_vt_opt.diff().abs().sum())
        tx_cost_total = switches * 0.001  # 10bps per switch
        tx_cost_ann = tx_cost_total / (len(use_vt_opt) / 52)
        strat_sharpe_net = (strat_ret_opt.mean() - tx_cost_total/len(strat_ret_opt)) / strat_ret_opt.std() * np.sqrt(52) if strat_ret_opt.std() > 0 else 0

        pr = {
            'period': oos_name,
            'n_weeks': len(predictions),
            'accuracy': float(acc),
            'auc': float(auc),
            'brier': float(brier),
            'best_threshold': float(best_thresh),
            'vt_fraction': float(vt_frac),
            'n_switches': int(switches),
            'strategy_sharpe': float(best_sharpe),
            'strategy_sharpe_net': float(strat_sharpe_net),
            'vt_sharpe': float(vt_sharpe),
            'bh_sharpe': float(bh_sharpe),
            'strategy_cum': float(strat_cum),
            'vt_cum': float(vt_cum),
            'bh_cum': float(bh_cum),
            'strategy_mdd': float(strat_mdd),
            'vt_mdd': float(vt_mdd),
            'bh_mdd': float(bh_mdd),
            'tx_cost_ann': float(tx_cost_ann),
        }
        period_results.append(pr)

        print(f"    Best threshold: {best_thresh:.2f} (VT fraction: {vt_frac:.1%})")
        print(f"    Sharpe — Strategy: {best_sharpe:.3f}, VT: {vt_sharpe:.3f}, B&H: {bh_sharpe:.3f}")
        print(f"    Net Sharpe: {strat_sharpe_net:.3f} ({int(switches)} switches, {tx_cost_ann:.2%}/yr TX)")
        print(f"    Cumulative — Strategy: {strat_cum:.3f}, VT: {vt_cum:.3f}, B&H: {bh_cum:.3f}")
        print(f"    MDD — Strategy: {strat_mdd:.1%}, VT: {vt_mdd:.1%}, B&H: {bh_mdd:.1%}")

        # Accumulate for overall metrics
        all_preds = pd.concat([all_preds, preds_s])
        all_labels_oos = pd.concat([all_labels_oos, acts_s])
        all_vt_oos = pd.concat([all_vt_oos, vt_s])
        all_bh_oos = pd.concat([all_bh_oos, bh_s])

    # Overall OOS metrics
    if len(all_preds) > 20:
        overall_binary = (all_preds > 0.5).astype(int)
        overall_acc = accuracy_score(all_labels_oos, overall_binary)
        try:
            overall_auc = roc_auc_score(all_labels_oos, all_preds)
        except:
            overall_auc = 0.5
        overall_brier = brier_score_loss(all_labels_oos, all_preds)

        # Overall strategy: use best per-period thresholds combined
        # Actually use a single fixed threshold = 0.5 for fairness
        use_vt_all = (all_preds > 0.5).astype(int)
        strat_all = use_vt_all * all_vt_oos + (1 - use_vt_all) * all_bh_oos
        overall_sharpe = strat_all.mean() / strat_all.std() * np.sqrt(52) if strat_all.std() > 0 else 0
        vt_all_sharpe = all_vt_oos.mean() / all_vt_oos.std() * np.sqrt(52) if all_vt_oos.std() > 0 else 0
        bh_all_sharpe = all_bh_oos.mean() / all_bh_oos.std() * np.sqrt(52) if all_bh_oos.std() > 0 else 0

        switches_all = use_vt_all.diff().abs().sum()
        vt_frac_all = use_vt_all.mean()

        print(f"\n  OVERALL OOS ({model_name.upper()}):")
        print(f"    N weeks: {len(all_preds)}")
        print(f"    Accuracy: {overall_acc:.3f}, AUC: {overall_auc:.3f}, Brier: {overall_brier:.4f}")
        print(f"    VT fraction: {vt_frac_all:.1%}, Switches: {int(switches_all)}")
        print(f"    Sharpe — Strategy: {overall_sharpe:.3f}, VT: {vt_all_sharpe:.3f}, B&H: {bh_all_sharpe:.3f}")

        overall = {
            'n_weeks': len(all_preds),
            'accuracy': float(overall_acc),
            'auc': float(overall_auc),
            'brier': float(overall_brier),
            'vt_fraction': float(vt_frac_all),
            'n_switches': int(switches_all),
            'strategy_sharpe_0.5': float(overall_sharpe),
            'vt_sharpe': float(vt_all_sharpe),
            'bh_sharpe': float(bh_all_sharpe),
        }
    else:
        overall = {'error': 'insufficient OOS data'}

    results_by_model[model_name] = {
        'periods': period_results,
        'overall': overall,
    }

# ─────────────────────────────────────────────────
# 7. REGIME ANALYSIS (weekly VT outperformance by VIX regime)
# ─────────────────────────────────────────────────
print("\n[7/8] Regime analysis: weekly VT outperformance by VIX level...")

# VIX regimes (using lagged VIX to avoid look-ahead)
vix_lagged = vix_w.shift(1)
vix_regimes = pd.cut(vix_lagged, bins=[0, 15, 20, 25, 35, 100],
                     labels=['<15', '15-20', '20-25', '25-35', '>35'])

regime_stats = {}
for regime in ['<15', '15-20', '20-25', '25-35', '>35']:
    mask = (vix_regimes == regime) & excess_w.notna()
    if mask.sum() < 5:
        continue
    ex = excess_w[mask]
    regime_stats[regime] = {
        'n_weeks': int(mask.sum()),
        'vt_win_rate': float((ex > 0).mean()),
        'mean_excess_bps': float(ex.mean() * 10000),
        'median_excess_bps': float(ex.median() * 10000),
        'sharpe_of_excess': float(ex.mean() / ex.std() * np.sqrt(52)) if ex.std() > 0 else 0,
    }
    print(f"  VIX {regime:6s}: n={mask.sum():3d}, win_rate={regime_stats[regime]['vt_win_rate']:.3f}, "
          f"mean_excess={regime_stats[regime]['mean_excess_bps']:+.1f}bps/wk, "
          f"Sharpe={regime_stats[regime]['sharpe_of_excess']:+.2f}")

# ─────────────────────────────────────────────────
# 8. SIMPLE REGIME-BASED BENCHMARK
# ─────────────────────────────────────────────────
print("\n[8/8] Simple regime benchmark: VIX > 20 → VT, else → B&H...")

# This is the simplest possible weekly switching rule
vix_lag = vix_w.shift(1)

# Restrict to the same OOS period as ML models
oos_full_mask = (feat_valid.index >= "2020-01-01") & (feat_valid.index <= "2024-12-31")
oos_dates = feat_valid.index[oos_full_mask]

# Intersect with available data
common_oos = oos_dates.intersection(vt_ret_w.index).intersection(vix_lag.dropna().index)

for vix_thresh in [18, 20, 22, 25]:
    use_vt_regime = (vix_lag.loc[common_oos] > vix_thresh).astype(int)
    strat_regime = use_vt_regime * vt_ret_w.loc[common_oos] + (1 - use_vt_regime) * bh_ret_w.loc[common_oos]

    regime_sharpe = strat_regime.mean() / strat_regime.std() * np.sqrt(52) if strat_regime.std() > 0 else 0
    vt_oos_sharpe = vt_ret_w.loc[common_oos].mean() / vt_ret_w.loc[common_oos].std() * np.sqrt(52) if vt_ret_w.loc[common_oos].std() > 0 else 0
    bh_oos_sharpe = bh_ret_w.loc[common_oos].mean() / bh_ret_w.loc[common_oos].std() * np.sqrt(52) if bh_ret_w.loc[common_oos].std() > 0 else 0

    vt_frac_r = use_vt_regime.mean()
    switches_r = use_vt_regime.diff().abs().sum()

    cum_r = (1 + strat_regime).cumprod().iloc[-1]
    mdd_r = ((1 + strat_regime).cumprod() / (1 + strat_regime).cumprod().cummax() - 1).min()

    print(f"  VIX>{vix_thresh}: Sharpe={regime_sharpe:.3f} (VT={vt_oos_sharpe:.3f}, BH={bh_oos_sharpe:.3f}), "
          f"VT%={vt_frac_r:.1%}, switches={int(switches_r)}, cum={cum_r:.3f}, MDD={mdd_r:.1%}")

# Full regime benchmark results (VIX > 20)
use_vt_20 = (vix_lag.loc[common_oos] > 20).astype(int)
strat_20 = use_vt_20 * vt_ret_w.loc[common_oos] + (1 - use_vt_20) * bh_ret_w.loc[common_oos]
regime_benchmark = {
    'vix_threshold': 20,
    'n_weeks': len(common_oos),
    'sharpe': float(strat_20.mean() / strat_20.std() * np.sqrt(52)) if strat_20.std() > 0 else 0,
    'vt_fraction': float(use_vt_20.mean()),
    'n_switches': int(use_vt_20.diff().abs().sum()),
    'cum_return': float((1 + strat_20).cumprod().iloc[-1]),
    'mdd': float(((1 + strat_20).cumprod() / (1 + strat_20).cumprod().cummax() - 1).min()),
}

# ─────────────────────────────────────────────────
# 9. SAVE RESULTS
# ─────────────────────────────────────────────────
print("\n" + "=" * 70)
print("CONCLUSIONS:")
print("=" * 70)

# Determine conclusion
logistic_auc = results_by_model.get('logistic', {}).get('overall', {}).get('auc', 0.5)
xgb_auc = results_by_model.get('xgboost', {}).get('overall', {}).get('auc', 0.5)
best_auc = max(logistic_auc, xgb_auc)

is_null = best_auc < 0.55  # AUC < 0.55 = essentially noise

if is_null:
    conclusion = (
        f"NULL RESULT: Weekly meta-labeling still noise. Best AUC={best_auc:.3f} "
        f"(K538 daily: 0.48-0.52). Weekly aggregation provides marginal improvement "
        f"but not enough to be tradeable. VT outperformance at weekly frequency "
        f"remains largely unpredictable by standard features."
    )
else:
    conclusion = (
        f"POSITIVE: Weekly meta-labeling shows signal. Best AUC={best_auc:.3f} "
        f"(vs K538 daily 0.48-0.52). Weekly aggregation successfully reduces noise."
    )

print(f"\n  {conclusion}")
print(f"\n  Feature correlations: max |r| = {abs(max_corr_val):.4f} (K538 daily: <0.02)")

# Summarize ML vs regime comparison
log_sharpe = results_by_model.get('logistic', {}).get('overall', {}).get('strategy_sharpe_0.5', 0)
xgb_sharpe = results_by_model.get('xgboost', {}).get('overall', {}).get('strategy_sharpe_0.5', 0)
regime_sharpe_val = regime_benchmark['sharpe']
print(f"  ML Sharpe — Logistic: {log_sharpe:.3f}, XGBoost: {xgb_sharpe:.3f}")
print(f"  Simple VIX>20 regime: {regime_sharpe_val:.3f}")
print(f"  Pure VT: {results_by_model.get('logistic', {}).get('overall', {}).get('vt_sharpe', 0):.3f}")
print(f"  B&H:     {results_by_model.get('logistic', {}).get('overall', {}).get('bh_sharpe', 0):.3f}")

results = {
    'experiment_id': 'K541',
    'title': 'Weekly Meta-Labeling for VT — Weekly Frequency Prediction',
    'proposer': '用戶',
    'executor': 'Claude',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance (SPY, ^VIX, ^VIX3M, TLT, GLD)',
    'data_period': f"{common_weekly[0].strftime('%Y-%m-%d')} to {common_weekly[-1].strftime('%Y-%m-%d')}",
    'n_weekly_samples': len(feat_valid),
    'references': [
        'López de Prado (2018) "Advances in Financial Machine Learning" Wiley, Ch.3 Meta-Labeling',
        'Luo et al. (2023) "Meta-Labeling: Theory and Framework" SSRN 4428790',
        'K538: Daily meta-labeling = noise (AUC 0.48-0.52, all features |r|<0.02)',
        'K65/K279: Weekly VT frequency analysis',
    ],
    'methodology': {
        'concept': 'Predict whether VT (12/VIX) outperforms B&H NEXT WEEK (binary classification). Weekly aggregation to reduce daily noise.',
        'features': feature_cols,
        'n_features': len(feature_cols),
        'models': ['logistic', 'xgboost'],
        'train_window_weeks': TRAIN_WEEKS,
        'embargo_weeks': EMBARGO_WEEKS,
        'oos_periods': [p[2] for p in oos_periods],
        'threshold_grid': THRESHOLD_GRID,
    },
    'feature_correlations': correlations,
    'strongest_feature': {
        'name': max_corr_feat,
        'r': float(max_corr_val),
    },
    'label_balance': float(label_valid.mean()),
    'model_results': results_by_model,
    'regime_analysis': regime_stats,
    'regime_benchmark': regime_benchmark,
    'is_null_result': is_null,
    'conclusion': conclusion,
    'comparison_to_k538': {
        'k538_daily_auc': '0.48-0.52',
        'k541_weekly_best_auc': float(best_auc),
        'k538_max_feature_r': '<0.02',
        'k541_max_feature_r': float(abs(max_corr_val)),
        'improvement': 'marginal' if is_null else 'significant',
    },
    'limitations': [
        'Weekly frequency = fewer samples (260/yr → 52/yr), less statistical power',
        'Rolling 2-year train window may be too short for weekly data (104 obs)',
        'Optimal threshold selected within OOS (upward bias) — diagnostic only',
        'Simple VIX>20 regime rule may capture most of the signal without ML',
        'No cross-validation of hyperparameters (fixed XGBoost params)',
    ],
}

out_path = os.path.join(os.path.dirname(__file__), 'k541_weekly_meta_label_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results saved to {out_path}")
print("=" * 70)
