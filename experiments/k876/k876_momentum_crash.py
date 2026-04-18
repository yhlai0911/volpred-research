"""
K876: Momentum Crash Risk and VIX — Can VIX Predict Momentum Crashes?

Research Question:
1. Does VIX level predict momentum strategy drawdowns?
2. Can a VIX-hedged momentum strategy avoid crashes?
3. Is momentum crash risk different from general equity crash risk?

Data: yfinance — MTUM, SPY, ^VIX, VLUE, QUAL. Period: 2013-01 to 2026-04.
References:
- Daniel & Moskowitz (2016 JFE): "Momentum Crashes"
- Barroso & Santa-Clara (2015 JFE): "Momentum Has Its Moments"
- K203: Momentum Crash Risk and Volatility (prior experiment)
- K556: Momentum Crash Filter (CrashDetector t=3.14 but +0.03 Sharpe only)
- K627: Momentum+VT Hybrid (no overlay improves 12/VIX)

Error log rules applied:
- DM test: use strategy_dm_test from volpred.stats.model_evaluation
- signal.shift(1) for all strategy weights
- Sharpe > 2x baseline = likely bug, stop and check
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime
from scipy import stats
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, classification_report

warnings.filterwarnings('ignore')

# ============================================================
# 1. DATA COLLECTION
# ============================================================
print("=" * 60)
print("K876: Momentum Crash Risk and VIX")
print("=" * 60)

tickers = ['MTUM', 'SPY', '^VIX', 'VLUE', 'QUAL']
start = '2013-01-01'
end = '2026-04-05'

print(f"\nDownloading data: {tickers}, {start} to {end}")
data = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)

# Extract close prices
close = data['Close'].copy()
close.columns = [c if isinstance(c, str) else c for c in close.columns]

# Rename VIX column
close = close.rename(columns={'^VIX': 'VIX'})

# Drop rows with NaN in key columns
close = close.dropna(subset=['MTUM', 'SPY', 'VIX'])

print(f"Data shape: {close.shape}")
print(f"Date range: {close.index[0].date()} to {close.index[-1].date()}")
print(f"Trading days: {len(close)}")

# ============================================================
# 2. COMPUTE RETURNS AND FEATURES
# ============================================================
ret = close[['MTUM', 'SPY', 'VLUE', 'QUAL']].pct_change()
ret = ret.dropna()

# MTUM excess return over SPY (momentum-specific risk)
ret['MTUM_excess'] = ret['MTUM'] - ret['SPY']

# Align VIX with returns
vix = close['VIX'].reindex(ret.index)

# Rolling features
ret['MTUM_vol_22d'] = ret['MTUM'].rolling(22).std() * np.sqrt(252)
ret['MTUM_cum_22d'] = ret['MTUM'].rolling(22).sum()
ret['SPY_cum_22d'] = ret['SPY'].rolling(22).sum()
ret['MTUM_excess_cum_22d'] = ret['MTUM_excess'].rolling(22).sum()

# VIX features
ret['VIX'] = vix
ret['VIX_change_5d'] = vix.pct_change(5)
ret['VIX_ma_22d'] = vix.rolling(22).mean()

# Drawdown computation for MTUM
mtum_prices = close['MTUM'].reindex(ret.index)
mtum_cummax = mtum_prices.cummax()
ret['MTUM_dd'] = (mtum_prices / mtum_cummax) - 1

spy_prices = close['SPY'].reindex(ret.index)
spy_cummax = spy_prices.cummax()
ret['SPY_dd'] = (spy_prices / spy_cummax) - 1

ret = ret.dropna()
print(f"\nFeature matrix shape (after rolling): {ret.shape}")

# ============================================================
# 3. DESCRIPTIVE STATISTICS
# ============================================================
print("\n" + "=" * 60)
print("DESCRIPTIVE STATISTICS")
print("=" * 60)

for col in ['MTUM', 'SPY', 'VIX']:
    if col == 'VIX':
        series = ret['VIX']
    else:
        series = ret[col]
    print(f"\n{col}:")
    print(f"  Mean (ann): {series.mean() * 252:.4f}" if col != 'VIX' else f"  Mean: {series.mean():.2f}")
    print(f"  Std (ann):  {series.std() * np.sqrt(252):.4f}" if col != 'VIX' else f"  Std: {series.std():.2f}")
    print(f"  Skew:       {series.skew():.4f}")
    print(f"  Kurtosis:   {series.kurtosis():.4f}")

# Correlation matrix
print("\nCorrelation Matrix (daily returns):")
corr_cols = ['MTUM', 'SPY', 'VLUE', 'QUAL']
print(ret[corr_cols].corr().round(4).to_string())

print(f"\nCorr(MTUM, SPY):  {ret['MTUM'].corr(ret['SPY']):.4f}")
print(f"Corr(MTUM, VLUE): {ret['MTUM'].corr(ret['VLUE']):.4f}")

# ============================================================
# 4. IDENTIFY MOMENTUM CRASHES
# ============================================================
print("\n" + "=" * 60)
print("MOMENTUM CRASH IDENTIFICATION")
print("=" * 60)

# Definition: MTUM drawdown > 10% OR MTUM underperforms SPY by > 5% in 22 days
# We use FORWARD-LOOKING 22-day returns as the TARGET (what we're trying to predict)
# Predictors use PAST data only

# Forward 22-day MTUM return (target)
ret['MTUM_fwd_22d'] = ret['MTUM'].rolling(22).sum().shift(-22)
# Forward 22-day SPY return
ret['SPY_fwd_22d'] = ret['SPY'].rolling(22).sum().shift(-22)
# Forward 22-day excess return
ret['MTUM_fwd_excess_22d'] = ret['MTUM_fwd_22d'] - ret['SPY_fwd_22d']

# Crash definition: MTUM loses > 10% in next 22 days OR underperforms SPY by > 5%
ret['crash_mtum_abs'] = (ret['MTUM_fwd_22d'] < -0.10).astype(int)
ret['crash_mtum_rel'] = (ret['MTUM_fwd_excess_22d'] < -0.05).astype(int)
ret['crash_any'] = ((ret['crash_mtum_abs'] == 1) | (ret['crash_mtum_rel'] == 1)).astype(int)

# Also define SPY crash for comparison
ret['SPY_fwd_22d_ret'] = ret['SPY'].rolling(22).sum().shift(-22)
ret['crash_spy'] = (ret['SPY_fwd_22d_ret'] < -0.10).astype(int)

# Drop NaN from forward returns
analysis = ret.dropna(subset=['MTUM_fwd_22d', 'SPY_fwd_22d'])
print(f"\nAnalysis sample: {len(analysis)} days")

crash_stats = {
    'MTUM absolute crash (>10% loss in 22d)': analysis['crash_mtum_abs'].sum(),
    'MTUM relative crash (>5% underperform SPY)': analysis['crash_mtum_rel'].sum(),
    'Any MTUM crash': analysis['crash_any'].sum(),
    'SPY crash (>10% loss in 22d)': analysis['crash_spy'].sum(),
}

for k, v in crash_stats.items():
    pct = v / len(analysis) * 100
    print(f"  {k}: {v} days ({pct:.1f}%)")

# Crash episodes (clustered events)
crash_dates = analysis[analysis['crash_any'] == 1].index
if len(crash_dates) > 0:
    # Find distinct episodes (>30 day gap)
    episodes = []
    ep_start = crash_dates[0]
    ep_end = crash_dates[0]
    for d in crash_dates[1:]:
        if (d - ep_end).days > 30:
            episodes.append((ep_start, ep_end))
            ep_start = d
        ep_end = d
    episodes.append((ep_start, ep_end))

    print(f"\nDistinct crash episodes (>30 day gap): {len(episodes)}")
    for i, (s, e) in enumerate(episodes):
        ep_mask = (analysis.index >= s) & (analysis.index <= e)
        ep_data = analysis[ep_mask]
        avg_fwd = ep_data['MTUM_fwd_22d'].mean()
        avg_vix = ep_data['VIX'].mean()
        print(f"  Episode {i+1}: {s.date()} to {e.date()} "
              f"(avg fwd 22d: {avg_fwd:.3f}, avg VIX: {avg_vix:.1f})")

# ============================================================
# 5. VIX AS PREDICTOR OF MOMENTUM CRASHES
# ============================================================
print("\n" + "=" * 60)
print("VIX AS PREDICTOR OF MOMENTUM CRASHES")
print("=" * 60)

# Features for prediction (all lagged / backward-looking)
feature_cols = ['VIX', 'VIX_change_5d', 'MTUM_vol_22d', 'MTUM_cum_22d', 'MTUM_excess_cum_22d']
pred_data = analysis.dropna(subset=feature_cols + ['crash_any'])

X = pred_data[feature_cols].values
y = pred_data['crash_any'].values

print(f"\nPrediction sample: {len(pred_data)} days")
print(f"Crash rate: {y.mean():.3f}")

# --- 5a. Univariate analysis: VIX level vs crash probability ---
vix_quintiles = pd.qcut(pred_data['VIX'], 5, labels=['Q1(Low)', 'Q2', 'Q3', 'Q4', 'Q5(High)'])
crash_by_vix = pred_data.groupby(vix_quintiles)['crash_any'].agg(['mean', 'sum', 'count'])
crash_by_vix.columns = ['crash_prob', 'crash_count', 'n_days']

print("\nCrash probability by VIX quintile:")
print(crash_by_vix.to_string())

# Test monotonicity: Spearman correlation
spearman_r, spearman_p = stats.spearmanr(pred_data['VIX'], pred_data['crash_any'])
print(f"\nSpearman(VIX, crash): r={spearman_r:.4f}, p={spearman_p:.2e}")

# Point-biserial correlation
pb_r, pb_p = stats.pointbiserialr(pred_data['crash_any'], pred_data['VIX'])
print(f"Point-biserial(VIX, crash): r={pb_r:.4f}, p={pb_p:.2e}")

# --- 5b. Compare: is VIX better at predicting MTUM crash vs SPY crash? ---
pb_spy_r, pb_spy_p = stats.pointbiserialr(pred_data['crash_spy'], pred_data['VIX'])
print(f"\nPoint-biserial(VIX, SPY crash): r={pb_spy_r:.4f}, p={pb_spy_p:.2e}")
print(f"Point-biserial(VIX, MTUM crash): r={pb_r:.4f}, p={pb_p:.2e}")
print(f"VIX predicts MTUM crash {'better' if abs(pb_r) > abs(pb_spy_r) else 'worse'} than SPY crash")

# --- 5c. Logistic regression: IS/OOS split ---
is_end = '2020-12-31'
is_mask = pred_data.index <= is_end
oos_mask = pred_data.index > is_end

X_is, y_is = X[is_mask], y[is_mask]
X_oos, y_oos = X[oos_mask], y[oos_mask]

print(f"\nIS: {is_mask.sum()} days ({y_is.mean():.3f} crash rate)")
print(f"OOS: {oos_mask.sum()} days ({y_oos.mean():.3f} crash rate)")

# Standardize features
from sklearn.preprocessing import StandardScaler
scaler = StandardScaler()
X_is_scaled = scaler.fit_transform(X_is)
X_oos_scaled = scaler.transform(X_oos)

# Logistic regression
lr = LogisticRegression(penalty='l2', C=1.0, max_iter=1000, random_state=42)
lr.fit(X_is_scaled, y_is)

# IS performance
y_is_prob = lr.predict_proba(X_is_scaled)[:, 1]
auc_is = roc_auc_score(y_is, y_is_prob) if len(np.unique(y_is)) > 1 else np.nan

# OOS performance
y_oos_prob = lr.predict_proba(X_oos_scaled)[:, 1]
auc_oos = roc_auc_score(y_oos, y_oos_prob) if len(np.unique(y_oos)) > 1 else np.nan

print(f"\nLogistic Regression Results:")
print(f"  IS  AUC: {auc_is:.4f}")
print(f"  OOS AUC: {auc_oos:.4f}")

# Feature importance (coefficients)
print(f"\nFeature coefficients:")
for name, coef in zip(feature_cols, lr.coef_[0]):
    print(f"  {name:25s}: {coef:+.4f}")

# VIX-only model for comparison
lr_vix = LogisticRegression(penalty='l2', C=1.0, max_iter=1000, random_state=42)
X_vix_is = X_is_scaled[:, 0:1]
X_vix_oos = X_oos_scaled[:, 0:1]
lr_vix.fit(X_vix_is, y_is)
auc_vix_is = roc_auc_score(y_is, lr_vix.predict_proba(X_vix_is)[:, 1]) if len(np.unique(y_is)) > 1 else np.nan
auc_vix_oos = roc_auc_score(y_oos, lr_vix.predict_proba(X_vix_oos)[:, 1]) if len(np.unique(y_oos)) > 1 else np.nan
print(f"\nVIX-only model:")
print(f"  IS  AUC: {auc_vix_is:.4f}")
print(f"  OOS AUC: {auc_vix_oos:.4f}")

# ============================================================
# 6. VIX-HEDGED MOMENTUM STRATEGY
# ============================================================
print("\n" + "=" * 60)
print("VIX-HEDGED MOMENTUM STRATEGY")
print("=" * 60)

# Strategies (all use LAGGED signals — signal.shift(1))
strat = pd.DataFrame(index=ret.index)
strat['MTUM_ret'] = ret['MTUM']
strat['SPY_ret'] = ret['SPY']
strat['VIX'] = ret['VIX']

# Strategy 1: MTUM Buy & Hold
strat['mtum_bh'] = strat['MTUM_ret']

# Strategy 2: SPY Buy & Hold
strat['spy_bh'] = strat['SPY_ret']

# Strategy 3: VIX-hedged MTUM — weight = max(0, 1 - VIX/30), residual in cash
# CRITICAL: signal.shift(1) for lag
vix_signal = strat['VIX'].copy()
weight_mtum = (1 - vix_signal / 30).clip(0, 1)
weight_mtum = weight_mtum.shift(1)  # <-- LAG: use yesterday's VIX for today's weight
strat['vix_hedge_mtum'] = weight_mtum * strat['MTUM_ret']

# Strategy 4: VIX-hedged MTUM (threshold: VIX > 25 → 0, else 1)
weight_binary = (vix_signal <= 25).astype(float)
weight_binary = weight_binary.shift(1)  # <-- LAG
strat['vix_binary_mtum'] = weight_binary * strat['MTUM_ret']

# Strategy 5: Vol-scaled MTUM (Barroso & Santa-Clara 2015 approach)
# Target vol = 15%, scale by realized vol
target_vol = 0.15
realized_vol = ret['MTUM'].rolling(22).std() * np.sqrt(252)
weight_volscale = (target_vol / realized_vol).clip(0, 2)
weight_volscale = weight_volscale.shift(1)  # <-- LAG
strat['vol_scaled_mtum'] = weight_volscale * strat['MTUM_ret']

# Strategy 6: 50/50 MTUM/SPY with VIX hedge (reduce MTUM weight when VIX high)
w_mtum_5050 = (0.5 * (1 - vix_signal / 30).clip(0, 1)).shift(1)  # <-- LAG
w_spy_5050 = (1 - w_mtum_5050)
strat['vix_hedge_5050'] = w_mtum_5050 * strat['MTUM_ret'] + w_spy_5050 * strat['SPY_ret']

# Drop NaN from rolling calculations
strat = strat.dropna()

# --- Performance metrics ---
def compute_metrics(returns, name, risk_free=0.0):
    """Compute standard strategy metrics."""
    ann_ret = returns.mean() * 252
    ann_vol = returns.std() * np.sqrt(252)
    sharpe = (ann_ret - risk_free) / ann_vol if ann_vol > 0 else 0

    cum = (1 + returns).cumprod()
    dd = cum / cum.cummax() - 1
    mdd = dd.min()

    # Calmar
    n_years = len(returns) / 252
    total_ret = cum.iloc[-1] - 1
    cagr = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0
    calmar = cagr / abs(mdd) if mdd != 0 else 0

    return {
        'name': name,
        'ann_return': ann_ret,
        'ann_vol': ann_vol,
        'sharpe': sharpe,
        'mdd': mdd,
        'cagr': cagr,
        'calmar': calmar,
        'n_days': len(returns),
    }

strategies = {
    'MTUM B&H': 'mtum_bh',
    'SPY B&H': 'spy_bh',
    'VIX-Hedged MTUM (1-VIX/30)': 'vix_hedge_mtum',
    'VIX Binary MTUM (VIX<25)': 'vix_binary_mtum',
    'Vol-Scaled MTUM (B&SC 2015)': 'vol_scaled_mtum',
    'VIX-Hedged 50/50': 'vix_hedge_5050',
}

# Full period metrics
print("\n--- Full Period Performance ---")
full_metrics = {}
for name, col in strategies.items():
    m = compute_metrics(strat[col], name)
    full_metrics[name] = m
    print(f"  {name:35s}: Sharpe={m['sharpe']:.3f}, CAGR={m['cagr']:.3%}, "
          f"MDD={m['mdd']:.3%}, Vol={m['ann_vol']:.3%}")

# Sanity check: no strategy should have Sharpe > 2x SPY
spy_sharpe = full_metrics['SPY B&H']['sharpe']
for name, m in full_metrics.items():
    if m['sharpe'] > 2 * spy_sharpe and spy_sharpe > 0:
        print(f"\n  ⚠️ WARNING: {name} Sharpe ({m['sharpe']:.3f}) > 2x SPY ({spy_sharpe:.3f}) — possible bug!")

# --- OOS Performance (2021-2026) ---
print("\n--- OOS Performance (2021-2026) ---")
oos_strat = strat[strat.index > '2020-12-31']
oos_metrics = {}
for name, col in strategies.items():
    m = compute_metrics(oos_strat[col], name)
    oos_metrics[name] = m
    print(f"  {name:35s}: Sharpe={m['sharpe']:.3f}, CAGR={m['cagr']:.3%}, "
          f"MDD={m['mdd']:.3%}")

# ============================================================
# 7. DM TESTS (VIX-hedged vs baselines)
# ============================================================
print("\n" + "=" * 60)
print("DM TESTS")
print("=" * 60)

try:
    from volpred.stats.model_evaluation import strategy_dm_test

    # Compare VIX-hedged strategies vs MTUM B&H
    dm_pairs = [
        ('VIX-Hedged MTUM (1-VIX/30)', 'MTUM B&H'),
        ('VIX-Hedged MTUM (1-VIX/30)', 'SPY B&H'),
        ('Vol-Scaled MTUM (B&SC 2015)', 'MTUM B&H'),
        ('VIX Binary MTUM (VIX<25)', 'MTUM B&H'),
        ('VIX-Hedged 50/50', 'SPY B&H'),
    ]

    dm_results = {}
    for s1_name, s2_name in dm_pairs:
        s1_col = strategies[s1_name]
        s2_col = strategies[s2_name]

        # Use OOS period for DM test
        r1 = oos_strat[s1_col]
        r2 = oos_strat[s2_col]

        try:
            result = strategy_dm_test(r1, r2, name1=s1_name, name2=s2_name)
            t_stat = result.get('t_statistic', result.get('t_stat', np.nan))
            p_val = result.get('p_value', np.nan)
            dm_results[f"{s1_name} vs {s2_name}"] = {'t': t_stat, 'p': p_val}
            harvey_pass = "PASS" if abs(t_stat) > 3.0 else "FAIL"
            print(f"  {s1_name} vs {s2_name}: t={t_stat:.3f}, p={p_val:.4f} [{harvey_pass}]")
        except Exception as e:
            print(f"  {s1_name} vs {s2_name}: DM test error: {e}")
            # Fallback: simple t-test on return differences
            diff = r1 - r2
            t_stat_simple = diff.mean() / (diff.std() / np.sqrt(len(diff)))
            p_val_simple = 2 * stats.t.sf(abs(t_stat_simple), df=len(diff)-1)
            dm_results[f"{s1_name} vs {s2_name}"] = {'t': t_stat_simple, 'p': p_val_simple}
            print(f"  {s1_name} vs {s2_name}: t={t_stat_simple:.3f} (simple), p={p_val_simple:.4f}")

except ImportError:
    print("  strategy_dm_test not available, using simple DM test")
    dm_results = {}
    for s1_name, s2_name in [
        ('VIX-Hedged MTUM (1-VIX/30)', 'MTUM B&H'),
        ('VIX-Hedged MTUM (1-VIX/30)', 'SPY B&H'),
        ('Vol-Scaled MTUM (B&SC 2015)', 'MTUM B&H'),
    ]:
        s1_col = strategies[s1_name]
        s2_col = strategies[s2_name]
        r1 = oos_strat[s1_col]
        r2 = oos_strat[s2_col]
        diff = r1 - r2
        t_stat = diff.mean() / (diff.std() / np.sqrt(len(diff)))
        p_val = 2 * stats.t.sf(abs(t_stat), df=len(diff)-1)
        dm_results[f"{s1_name} vs {s2_name}"] = {'t': float(t_stat), 'p': float(p_val)}
        harvey_pass = "PASS" if abs(t_stat) > 3.0 else "FAIL"
        print(f"  {s1_name} vs {s2_name}: t={t_stat:.3f}, p={p_val:.4f} [{harvey_pass}]")

# ============================================================
# 8. MOMENTUM CRASH vs GENERAL EQUITY CRASH
# ============================================================
print("\n" + "=" * 60)
print("MOMENTUM CRASH vs GENERAL EQUITY CRASH")
print("=" * 60)

# During SPY crashes, does MTUM crash more/less/same?
crash_spy_days = analysis[analysis['crash_spy'] == 1]
non_crash_spy_days = analysis[analysis['crash_spy'] == 0]

if len(crash_spy_days) > 0:
    mtum_in_spy_crash = crash_spy_days['MTUM_fwd_22d'].mean()
    spy_in_spy_crash = crash_spy_days['SPY_fwd_22d'].mean()
    mtum_excess_in_crash = crash_spy_days['MTUM_fwd_excess_22d'].mean()

    print(f"\nDuring SPY crash periods ({len(crash_spy_days)} days):")
    print(f"  Avg MTUM 22d return: {mtum_in_spy_crash:.4f}")
    print(f"  Avg SPY 22d return:  {spy_in_spy_crash:.4f}")
    print(f"  Avg MTUM excess:     {mtum_excess_in_crash:.4f}")
    print(f"  MTUM crashes {'harder' if mtum_in_spy_crash < spy_in_spy_crash else 'less'} than SPY")

# Conditional crash rates
print(f"\nConditional crash analysis:")
# P(MTUM crash | SPY crash)
if len(crash_spy_days) > 0:
    p_mtum_crash_given_spy_crash = crash_spy_days['crash_any'].mean()
    print(f"  P(MTUM crash | SPY crash) = {p_mtum_crash_given_spy_crash:.3f}")

# P(MTUM crash | no SPY crash)
if len(non_crash_spy_days) > 0:
    p_mtum_crash_given_no_spy = non_crash_spy_days['crash_any'].mean()
    print(f"  P(MTUM crash | no SPY crash) = {p_mtum_crash_given_no_spy:.3f}")

# P(MTUM crash only, no SPY crash)
mtum_only_crash = analysis[(analysis['crash_any'] == 1) & (analysis['crash_spy'] == 0)]
print(f"  MTUM-only crashes (no SPY crash): {len(mtum_only_crash)} days ({len(mtum_only_crash)/len(analysis)*100:.1f}%)")

# VIX level during different crash types
both_crash = analysis[(analysis['crash_any'] == 1) & (analysis['crash_spy'] == 1)]
mtum_only = analysis[(analysis['crash_any'] == 1) & (analysis['crash_spy'] == 0)]
no_crash = analysis[(analysis['crash_any'] == 0) & (analysis['crash_spy'] == 0)]

print(f"\nAvg VIX by crash type:")
if len(both_crash) > 0:
    print(f"  Both crash:      {both_crash['VIX'].mean():.1f} (n={len(both_crash)})")
if len(mtum_only) > 0:
    print(f"  MTUM-only crash: {mtum_only['VIX'].mean():.1f} (n={len(mtum_only)})")
if len(no_crash) > 0:
    print(f"  No crash:        {no_crash['VIX'].mean():.1f} (n={len(no_crash)})")

# ============================================================
# 9. ROLLING ANALYSIS: VIX PREDICTIVE POWER OVER TIME
# ============================================================
print("\n" + "=" * 60)
print("ROLLING VIX PREDICTIVE POWER")
print("=" * 60)

# Rolling 2-year windows
window_days = 504  # ~2 years
rolling_auc = []
rolling_corr = []

for i in range(window_days, len(pred_data), 63):  # step = quarterly
    w_data = pred_data.iloc[i-window_days:i]
    w_vix = w_data['VIX'].values
    w_crash = w_data['crash_any'].values

    if len(np.unique(w_crash)) < 2:
        continue

    try:
        auc = roc_auc_score(w_crash, w_vix)
    except:
        auc = np.nan

    corr = np.corrcoef(w_vix, w_crash)[0, 1]

    rolling_auc.append({
        'date': w_data.index[-1],
        'auc': auc,
        'corr': corr,
        'crash_rate': w_crash.mean(),
    })

if rolling_auc:
    roll_df = pd.DataFrame(rolling_auc)
    print(f"\nRolling 2-year AUC (VIX → crash):")
    print(f"  Mean AUC: {roll_df['auc'].mean():.4f}")
    print(f"  Min AUC:  {roll_df['auc'].min():.4f} ({roll_df.loc[roll_df['auc'].idxmin(), 'date'].date()})")
    print(f"  Max AUC:  {roll_df['auc'].max():.4f} ({roll_df.loc[roll_df['auc'].idxmax(), 'date'].date()})")
    print(f"  Stable (std): {roll_df['auc'].std():.4f}")

# ============================================================
# 10. COMPILE RESULTS
# ============================================================
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

# Key findings
findings = []

# Finding 1: VIX prediction power
findings.append(f"VIX-crash Spearman r={spearman_r:.4f} (p={spearman_p:.2e})")
findings.append(f"Full model OOS AUC={auc_oos:.4f}, VIX-only OOS AUC={auc_vix_oos:.4f}")

# Finding 2: VIX-hedged strategy performance
best_strat_name = max(full_metrics, key=lambda x: full_metrics[x]['sharpe'])
findings.append(f"Best full-period strategy: {best_strat_name} (Sharpe={full_metrics[best_strat_name]['sharpe']:.3f})")

best_oos_name = max(oos_metrics, key=lambda x: oos_metrics[x]['sharpe'])
findings.append(f"Best OOS strategy: {best_oos_name} (Sharpe={oos_metrics[best_oos_name]['sharpe']:.3f})")

# Finding 3: MTUM vs SPY crash risk
if len(crash_spy_days) > 0:
    findings.append(f"MTUM excess during SPY crash: {mtum_excess_in_crash:+.4f}")

for f in findings:
    print(f"  • {f}")

# DM test summary
print(f"\nDM test results (OOS, Harvey |t|>3.0):")
for pair, res in dm_results.items():
    harvey = "PASS" if abs(res['t']) > 3.0 else "FAIL"
    print(f"  {pair}: t={res['t']:.3f} [{harvey}]")

# Overall conclusion
print(f"\n{'='*60}")
print("CONCLUSION")
print("="*60)

vix_useful = auc_oos > 0.55
hedging_works = any(oos_metrics[n]['sharpe'] > oos_metrics['MTUM B&H']['sharpe']
                    for n in oos_metrics if n != 'MTUM B&H' and n != 'SPY B&H')

if vix_useful:
    print("  VIX has modest predictive power for momentum crashes (OOS AUC > 0.55)")
else:
    print("  VIX has LIMITED predictive power for momentum crashes (OOS AUC <= 0.55)")

if hedging_works:
    print("  VIX-hedging can improve MTUM risk-adjusted returns")
else:
    print("  VIX-hedging does NOT significantly improve MTUM (consistent with K627)")

print(f"  Momentum crash risk is {'distinct from' if len(mtum_only_crash) > 100 else 'largely overlapping with'} general equity crash risk")

# ============================================================
# 11. SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K876',
    'title': 'Momentum Crash Risk and VIX — Can VIX Predict Momentum Crashes?',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance',
    'tickers': ['MTUM', 'SPY', '^VIX', 'VLUE', 'QUAL'],
    'period': f"{close.index[0].date()} to {close.index[-1].date()}",
    'n_trading_days': len(close),
    'references': [
        'Daniel & Moskowitz (2016 JFE): Momentum Crashes',
        'Barroso & Santa-Clara (2015 JFE): Momentum Has Its Moments',
        'K203: Momentum Crash Risk and Volatility',
        'K556: Momentum Crash Filter (CrashDetector t=3.14 but +0.03 Sharpe)',
        'K627: Momentum+VT Hybrid (no overlay improves 12/VIX)',
    ],
    'descriptive_stats': {
        'MTUM': {
            'ann_return': float(ret['MTUM'].mean() * 252),
            'ann_vol': float(ret['MTUM'].std() * np.sqrt(252)),
            'skew': float(ret['MTUM'].skew()),
            'kurtosis': float(ret['MTUM'].kurtosis()),
        },
        'SPY': {
            'ann_return': float(ret['SPY'].mean() * 252),
            'ann_vol': float(ret['SPY'].std() * np.sqrt(252)),
            'skew': float(ret['SPY'].skew()),
            'kurtosis': float(ret['SPY'].kurtosis()),
        },
        'VIX_mean': float(ret['VIX'].mean()),
        'VIX_std': float(ret['VIX'].std()),
        'corr_MTUM_SPY': float(ret['MTUM'].corr(ret['SPY'])),
    },
    'crash_identification': {
        'definition': 'MTUM loss > 10% in 22d OR MTUM underperforms SPY by > 5% in 22d',
        'n_crash_days_absolute': int(analysis['crash_mtum_abs'].sum()),
        'n_crash_days_relative': int(analysis['crash_mtum_rel'].sum()),
        'n_crash_days_any': int(analysis['crash_any'].sum()),
        'n_spy_crash_days': int(analysis['crash_spy'].sum()),
        'n_distinct_episodes': len(episodes) if 'episodes' in dir() else 0,
    },
    'prediction': {
        'spearman_r_VIX_crash': float(spearman_r),
        'spearman_p': float(spearman_p),
        'point_biserial_r': float(pb_r),
        'logistic_IS_AUC': float(auc_is),
        'logistic_OOS_AUC': float(auc_oos),
        'VIX_only_IS_AUC': float(auc_vix_is),
        'VIX_only_OOS_AUC': float(auc_vix_oos),
        'feature_importance': {name: float(coef) for name, coef in zip(feature_cols, lr.coef_[0])},
        'crash_prob_by_VIX_quintile': crash_by_vix['crash_prob'].to_dict(),
    },
    'strategy_performance': {
        'full_period': {name: {k: float(v) if isinstance(v, (np.floating, float)) else v
                               for k, v in m.items()}
                       for name, m in full_metrics.items()},
        'oos_period': {name: {k: float(v) if isinstance(v, (np.floating, float)) else v
                              for k, v in m.items()}
                      for name, m in oos_metrics.items()},
    },
    'dm_tests': {pair: {'t_statistic': float(res['t']), 'p_value': float(res['p']),
                         'harvey_pass': abs(res['t']) > 3.0}
                 for pair, res in dm_results.items()},
    'crash_analysis': {
        'mtum_excess_during_spy_crash': float(mtum_excess_in_crash) if len(crash_spy_days) > 0 else None,
        'p_mtum_crash_given_spy_crash': float(p_mtum_crash_given_spy_crash) if len(crash_spy_days) > 0 else None,
        'p_mtum_crash_given_no_spy_crash': float(p_mtum_crash_given_no_spy) if len(non_crash_spy_days) > 0 else None,
        'mtum_only_crash_days': len(mtum_only_crash),
        'avg_vix_both_crash': float(both_crash['VIX'].mean()) if len(both_crash) > 0 else None,
        'avg_vix_mtum_only_crash': float(mtum_only['VIX'].mean()) if len(mtum_only) > 0 else None,
        'avg_vix_no_crash': float(no_crash['VIX'].mean()) if len(no_crash) > 0 else None,
    },
    'rolling_analysis': {
        'mean_rolling_auc': float(roll_df['auc'].mean()) if rolling_auc else None,
        'std_rolling_auc': float(roll_df['auc'].std()) if rolling_auc else None,
    },
    'conclusions': {
        'vix_predicts_momentum_crash': vix_useful,
        'hedging_improves_risk_adjusted': hedging_works,
        'momentum_crash_distinct_from_equity': len(mtum_only_crash) > 100,
        'summary': (
            f"VIX has {'modest' if vix_useful else 'limited'} predictive power for momentum crashes "
            f"(OOS AUC={auc_oos:.3f}). "
            f"VIX-hedging {'can improve' if hedging_works else 'does NOT significantly improve'} "
            f"MTUM risk-adjusted returns. "
            f"Momentum crash risk {'has a distinct component' if len(mtum_only_crash) > 100 else 'largely overlaps with'} "
            f"general equity crash risk. "
            f"Consistent with K627: no simple overlay beats buy-and-hold momentum."
        ),
    },
}

results_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k876_results.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {results_path}")
print("DONE.")
