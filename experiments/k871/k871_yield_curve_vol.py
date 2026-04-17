"""K871: Yield Curve Slope as Volatility Predictor

Research Questions:
  1. Does yield curve slope predict forward realized vol beyond VIX?
  2. Does curve inversion predict VIX regime transitions (low -> high)?
  3. Is the yield curve a LEADING indicator of vol (predicts weeks/months ahead)?

Background:
  - K503/G5: T10Y2Y theta~0 in GARCH-MIDAS, partial r < 0.03 after VIX control
  - VIX sufficiency confirmed 26+ times — can yield curve ADD to VIX?
  - Yield curve inversion is a well-known recession predictor
  - The EMPIRICAL question: does it predict VOL specifically?

Data:
  - FRED: T10Y2Y (10Y-2Y spread), T10Y3M (10Y-3M spread), DGS10 (10Y yield)
  - yfinance: SPY (returns), ^VIX
  - Period: 2000-01 to 2026-04
  - IS: 2000-2018, OOS: 2019-2026

Methodology:
  1. Variables (all shifted by 1 day for no-lookahead):
     - slope = T10Y2Y (positive = normal, negative = inverted)
     - slope_3m = T10Y3M
     - level = DGS10 (rate level)
     - VIX (benchmark predictor)
     - target = forward 22-day realized vol (annualized stdev of next 22 returns)
  2. Regression models (OLS, IS then OOS):
     a. VIX only (baseline)
     b. VIX + slope
     c. VIX + slope + level
     d. Slope only (no VIX)
     e. Delta_slope (22-day change) + VIX
  3. Event analysis: inversion episodes -> forward vol
  4. Lead-lag cross-correlation: slope vs VIX at lags 0..252
  5. DM test (Harvey t>3.0) for model comparisons on OOS

Error log rules applied:
  - signal.shift(1) mandatory — all predictors lagged
  - DM test: from volpred.stats.model_evaluation import dm_test
  - Sharpe > 2x baseline = bug, STOP

References:
  - Estrella & Mishkin (1998) — yield curve as recession predictor
  - Copeland & Copeland (1999) — VIX market timing
  - Harvey et al. (2016) — t > 3.0 multiple testing threshold
  - Patton (2011) — proxy-robust loss (QLIKE)
  - K503: GARCH-MIDAS with T10Y2Y -> theta~0
  - G5: 5 sentiment/financial indicators null after VIX control

Author: VolPred Research System
Date: 2026-04-05
"""

import json
import warnings
import requests
import numpy as np
import pandas as pd
from datetime import datetime
from io import StringIO

warnings.filterwarnings('ignore')

# ─── Data Collection ───────────────────────────────────────────────

print("=" * 70)
print("K871: Yield Curve Slope as Volatility Predictor")
print("=" * 70)

# FRED data via direct CSV endpoint (no pandas_datareader dependency)
print("\n[1/6] Fetching FRED data...")

start_date = '2000-01-01'
end_date = '2026-04-01'


def fetch_fred_series(series_id, start, end):
    """Fetch a FRED series via the public CSV endpoint."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}&coed={end}"
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        date_col = [c for c in df.columns if 'date' in c.lower()]
        if date_col:
            df.index = pd.to_datetime(df[date_col[0]])
            df = df.drop(columns=date_col)
        df.columns = [series_id]
        df[series_id] = pd.to_numeric(df[series_id], errors='coerce')
        return df.dropna()
    except Exception as e:
        print(f"  WARNING: Could not fetch {series_id}: {e}")
        return pd.DataFrame()


fred_series = {
    'T10Y2Y': 'slope_10y2y',
    'T10Y3M': 'slope_10y3m',
    'DGS10': 'level_10y',
}

fred_data = {}
for code, name in fred_series.items():
    raw = fetch_fred_series(code, start_date, end_date)
    if len(raw) > 0:
        fred_data[name] = raw.iloc[:, 0].rename(name)
        print(f"  {code} ({name}): {len(raw)} obs, {raw.index[0].date()} to {raw.index[-1].date()}")
    else:
        print(f"  WARNING: No data for {code}")

fred_df = pd.DataFrame(fred_data)
fred_df.index = pd.to_datetime(fred_df.index)

# yfinance data
print("\n[2/6] Fetching yfinance data...")
import yfinance as yf

spy = yf.download('SPY', start=start_date, end=end_date, progress=False)
vix = yf.download('^VIX', start=start_date, end=end_date, progress=False)

# Handle MultiIndex columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

spy_ret = spy['Close'].pct_change()
spy_ret.name = 'spy_ret'
vix_close = vix['Close']
vix_close.name = 'vix'

print(f"  SPY: {len(spy)} obs")
print(f"  VIX: {len(vix)} obs")

# ─── Merge & Prepare ──────────────────────────────────────────────

print("\n[3/6] Merging data and computing features...")

# Merge all on trading days
df = pd.DataFrame({'spy_ret': spy_ret, 'vix': vix_close})
df = df.join(fred_df, how='left')

# Forward-fill FRED (weekends/holidays)
for col in fred_df.columns:
    df[col] = df[col].ffill()

df = df.dropna(subset=['spy_ret', 'vix'])

# Compute forward 22-day realized vol (target)
# RV = annualized std of NEXT 22 trading days
fwd_ret = df['spy_ret'].shift(-1)  # next-day returns
rv_22 = fwd_ret.rolling(22).std() * np.sqrt(252)
# Shift back so rv_22[t] = vol of days t+1..t+22
df['fwd_rv22'] = rv_22.shift(-21)  # align so row t has vol of next 22 days

# Compute delta_slope (22-day change in slope)
df['delta_slope_22'] = df['slope_10y2y'] - df['slope_10y2y'].shift(22)

# SHIFT ALL PREDICTORS by 1 day (mandatory no-lookahead)
predictor_cols = ['vix', 'slope_10y2y', 'slope_10y3m', 'level_10y', 'delta_slope_22']
for col in predictor_cols:
    df[f'{col}_lag1'] = df[col].shift(1)

# Drop NaN
analysis_cols = [f'{c}_lag1' for c in predictor_cols] + ['fwd_rv22']
df_clean = df.dropna(subset=analysis_cols).copy()

print(f"  Clean sample: {len(df_clean)} obs ({df_clean.index[0].date()} to {df_clean.index[-1].date()})")

# ─── Descriptive Statistics ────────────────────────────────────────

print("\n" + "=" * 70)
print("DESCRIPTIVE STATISTICS")
print("=" * 70)

desc_cols = ['fwd_rv22', 'vix_lag1', 'slope_10y2y_lag1', 'slope_10y3m_lag1', 'level_10y_lag1', 'delta_slope_22_lag1']
desc = df_clean[desc_cols].describe().T
desc['skew'] = df_clean[desc_cols].skew()
desc['kurtosis'] = df_clean[desc_cols].kurtosis()
print(desc[['count', 'mean', 'std', 'min', '25%', '50%', '75%', 'max', 'skew', 'kurtosis']].round(4))

# Correlation matrix
print("\n--- Correlation Matrix ---")
corr = df_clean[desc_cols].corr().round(4)
print(corr)

# ─── IS/OOS Split ──────────────────────────────────────────────────

split_date = '2019-01-01'
is_data = df_clean[df_clean.index < split_date].copy()
oos_data = df_clean[df_clean.index >= split_date].copy()

print(f"\n  IS: {len(is_data)} obs ({is_data.index[0].date()} to {is_data.index[-1].date()})")
print(f"  OOS: {len(oos_data)} obs ({oos_data.index[0].date()} to {oos_data.index[-1].date()})")

# ─── Regression Models ─────────────────────────────────────────────

print("\n" + "=" * 70)
print("REGRESSION ANALYSIS (OLS)")
print("=" * 70)

from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score, mean_squared_error

target = 'fwd_rv22'

models = {
    'A_vix_only':       ['vix_lag1'],
    'B_vix_slope':      ['vix_lag1', 'slope_10y2y_lag1'],
    'C_vix_slope_lvl':  ['vix_lag1', 'slope_10y2y_lag1', 'level_10y_lag1'],
    'D_slope_only':     ['slope_10y2y_lag1'],
    'E_vix_dslope':     ['vix_lag1', 'delta_slope_22_lag1'],
    'F_slope3m_only':   ['slope_10y3m_lag1'],
    'G_vix_slope3m':    ['vix_lag1', 'slope_10y3m_lag1'],
}

from volpred.stats.model_evaluation import dm_test, qlike_pointwise

results_models = {}

for name, features in models.items():
    # IS fit
    X_is = is_data[features].values
    y_is = is_data[target].values

    lr = LinearRegression()
    lr.fit(X_is, y_is)

    # IS metrics
    y_is_pred = lr.predict(X_is)
    is_r2 = r2_score(y_is, y_is_pred)
    is_rmse = np.sqrt(mean_squared_error(y_is, y_is_pred))

    # OOS metrics
    X_oos = oos_data[features].values
    y_oos = oos_data[target].values
    y_oos_pred = lr.predict(X_oos)

    oos_r2 = r2_score(y_oos, y_oos_pred)
    oos_rmse = np.sqrt(mean_squared_error(y_oos, y_oos_pred))

    # Correlation
    oos_corr = np.corrcoef(y_oos, y_oos_pred)[0, 1]

    # Store predictions for DM test
    results_models[name] = {
        'features': features,
        'coefficients': dict(zip(features, lr.coef_.tolist())),
        'intercept': float(lr.intercept_),
        'IS_R2': round(is_r2, 4),
        'IS_RMSE': round(is_rmse, 4),
        'OOS_R2': round(oos_r2, 4),
        'OOS_RMSE': round(oos_rmse, 4),
        'OOS_corr': round(oos_corr, 4),
        'oos_predictions': y_oos_pred,
        'oos_actual': y_oos,
    }

    coef_str = ", ".join([f"{f}={c:.4f}" for f, c in zip(features, lr.coef_)])
    print(f"\n  {name}:")
    print(f"    Coefficients: {coef_str}, intercept={lr.intercept_:.4f}")
    print(f"    IS  R²={is_r2:.4f}, RMSE={is_rmse:.4f}")
    print(f"    OOS R²={oos_r2:.4f}, RMSE={oos_rmse:.4f}, Corr={oos_corr:.4f}")

# ─── DM Tests ──────────────────────────────────────────────────────

print("\n" + "=" * 70)
print("DIEBOLD-MARIANO TESTS (OOS, Harvey t>3.0)")
print("=" * 70)

# Baseline = A_vix_only
baseline_pred = results_models['A_vix_only']['oos_predictions']
baseline_actual = results_models['A_vix_only']['oos_actual']
baseline_losses = (baseline_actual - baseline_pred) ** 2  # MSE losses

dm_results = {}
comparisons = [
    ('A_vix_only', 'B_vix_slope'),
    ('A_vix_only', 'C_vix_slope_lvl'),
    ('A_vix_only', 'D_slope_only'),
    ('A_vix_only', 'E_vix_dslope'),
    ('A_vix_only', 'G_vix_slope3m'),
    ('D_slope_only', 'F_slope3m_only'),
]

for m1, m2 in comparisons:
    pred1 = results_models[m1]['oos_predictions']
    pred2 = results_models[m2]['oos_predictions']
    actual = results_models[m1]['oos_actual']

    loss1 = (actual - pred1) ** 2
    loss2 = (actual - pred2) ** 2

    t_stat, p_val = dm_test(loss1, loss2, h=22)
    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
    better = m1 if t_stat < 0 else m2

    dm_results[f'{m1}_vs_{m2}'] = {
        't_stat': round(t_stat, 4),
        'p_value': round(p_val, 4),
        'significant_Harvey': abs(t_stat) > 3.0,
        'better': better,
    }
    print(f"  {m1} vs {m2}: DM t={t_stat:.4f}, p={p_val:.4f} {sig}  -> {better} better")

# Also compare using QLIKE (Patton 2011)
print("\n--- QLIKE-based DM tests ---")
dm_qlike_results = {}

for m1, m2 in comparisons:
    pred1 = np.maximum(results_models[m1]['oos_predictions'], 1e-6)
    pred2 = np.maximum(results_models[m2]['oos_predictions'], 1e-6)
    actual = np.maximum(results_models[m1]['oos_actual'], 1e-6)

    # QLIKE on variance (square everything since we predict vol, target is vol)
    ql1 = qlike_pointwise(actual ** 2, pred1 ** 2)
    ql2 = qlike_pointwise(actual ** 2, pred2 ** 2)

    t_stat, p_val = dm_test(ql1, ql2, h=22)
    sig = "***" if abs(t_stat) > 3.0 else ("**" if abs(t_stat) > 2.0 else ("*" if abs(t_stat) > 1.65 else ""))
    better = m1 if t_stat < 0 else m2

    dm_qlike_results[f'{m1}_vs_{m2}'] = {
        't_stat': round(t_stat, 4),
        'p_value': round(p_val, 4),
        'significant_Harvey': abs(t_stat) > 3.0,
        'better': better,
    }
    print(f"  {m1} vs {m2}: DM(QLIKE) t={t_stat:.4f}, p={p_val:.4f} {sig}  -> {better} better")

# ─── Partial Correlation (slope | VIX) ─────────────────────────────

print("\n" + "=" * 70)
print("PARTIAL CORRELATION: slope -> fwd_rv22 | VIX")
print("=" * 70)

from scipy import stats as sp_stats

# Full sample partial correlation
def partial_corr(x, y, z):
    """Partial correlation of x and y controlling for z."""
    # Residuals of x ~ z
    slope_xz, intercept_xz, _, _, _ = sp_stats.linregress(z, x)
    resid_x = x - (slope_xz * z + intercept_xz)
    # Residuals of y ~ z
    slope_yz, intercept_yz, _, _, _ = sp_stats.linregress(z, y)
    resid_y = y - (slope_yz * z + intercept_yz)
    # Correlation of residuals
    r, p = sp_stats.pearsonr(resid_x, resid_y)
    return r, p

slope_vals = df_clean['slope_10y2y_lag1'].values
vix_vals = df_clean['vix_lag1'].values
rv_vals = df_clean['fwd_rv22'].values

# Full sample
pr_full, pp_full = partial_corr(slope_vals, rv_vals, vix_vals)
print(f"  Full sample partial corr(slope, rv22 | VIX): r={pr_full:.4f}, p={pp_full:.4f}")

# IS
pr_is, pp_is = partial_corr(is_data['slope_10y2y_lag1'].values, is_data['fwd_rv22'].values, is_data['vix_lag1'].values)
print(f"  IS partial corr(slope, rv22 | VIX): r={pr_is:.4f}, p={pp_is:.4f}")

# OOS
pr_oos, pp_oos = partial_corr(oos_data['slope_10y2y_lag1'].values, oos_data['fwd_rv22'].values, oos_data['vix_lag1'].values)
print(f"  OOS partial corr(slope, rv22 | VIX): r={pr_oos:.4f}, p={pp_oos:.4f}")

# Also check slope_3m
pr_3m, pp_3m = partial_corr(df_clean['slope_10y3m_lag1'].values, rv_vals, vix_vals)
print(f"  Full sample partial corr(slope_3m, rv22 | VIX): r={pr_3m:.4f}, p={pp_3m:.4f}")

# Delta slope
pr_ds, pp_ds = partial_corr(df_clean['delta_slope_22_lag1'].values, rv_vals, vix_vals)
print(f"  Full sample partial corr(delta_slope22, rv22 | VIX): r={pr_ds:.4f}, p={pp_ds:.4f}")

partial_corr_results = {
    'full_slope_10y2y': {'r': round(pr_full, 4), 'p': round(pp_full, 4)},
    'IS_slope_10y2y': {'r': round(pr_is, 4), 'p': round(pp_is, 4)},
    'OOS_slope_10y2y': {'r': round(pr_oos, 4), 'p': round(pp_oos, 4)},
    'full_slope_10y3m': {'r': round(pr_3m, 4), 'p': round(pp_3m, 4)},
    'full_delta_slope22': {'r': round(pr_ds, 4), 'p': round(pp_ds, 4)},
}

# ─── Event Analysis: Inversion Episodes ────────────────────────────

print("\n" + "=" * 70)
print("EVENT ANALYSIS: Yield Curve Inversion Episodes")
print("=" * 70)

# Identify inversion episodes (T10Y2Y < 0)
# Use unlagged data for event identification, but measure FORWARD vol
df_events = df.dropna(subset=['slope_10y2y', 'fwd_rv22']).copy()
df_events['inverted'] = (df_events['slope_10y2y'] < 0).astype(int)

# Find continuous inversion episodes
df_events['inv_change'] = df_events['inverted'].diff().fillna(0)
df_events['episode_start'] = (df_events['inv_change'] == 1)

# Get all inversion starts
inversion_starts = df_events[df_events['episode_start']].index

print(f"\n  Total inversion days: {df_events['inverted'].sum()}")
print(f"  Inversion episodes found: {len(inversion_starts)}")

inversion_episodes = []
for start in inversion_starts:
    # Find end of this inversion
    mask_after = df_events.index > start
    if mask_after.sum() == 0:
        continue
    post = df_events.loc[mask_after]
    uninvert = post[post['inverted'] == 0]
    if len(uninvert) > 0:
        end = uninvert.index[0]
    else:
        end = df_events.index[-1]

    duration = (end - start).days

    # Forward vol at start, +1m, +3m, +6m, +12m
    fwd_vols = {}
    for label, offset in [('at_start', 0), ('1m', 22), ('3m', 66), ('6m', 132), ('12m', 252)]:
        idx = df_events.index.searchsorted(start) + offset
        if idx < len(df_events):
            fwd_vols[label] = df_events['fwd_rv22'].iloc[idx]
        else:
            fwd_vols[label] = np.nan

    # Mean VIX during episode
    ep_mask = (df_events.index >= start) & (df_events.index < end)
    mean_vix = df_events.loc[ep_mask, 'vix'].mean()

    ep_info = {
        'start': str(start.date()),
        'end': str(end.date()),
        'duration_days': duration,
        'mean_vix': round(mean_vix, 2) if not np.isnan(mean_vix) else None,
        **{f'fwd_rv22_{k}': round(v, 4) if not np.isnan(v) else None for k, v in fwd_vols.items()},
    }
    inversion_episodes.append(ep_info)
    print(f"  Episode: {start.date()} to {end.date()} ({duration}d), VIX={mean_vix:.1f}, "
          f"RV22@start={fwd_vols['at_start']:.2%}, RV22@6m={fwd_vols.get('6m', np.nan):.2%}" if not np.isnan(fwd_vols.get('6m', np.nan)) else
          f"  Episode: {start.date()} to {end.date()} ({duration}d), VIX={mean_vix:.1f}, "
          f"RV22@start={fwd_vols['at_start']:.2%}")

# Compare vol: inverted vs normal periods
inv_mask = df_events['inverted'] == 1
normal_mask = df_events['inverted'] == 0

rv_inverted = df_events.loc[inv_mask, 'fwd_rv22']
rv_normal = df_events.loc[normal_mask, 'fwd_rv22']

t_stat_ev, p_val_ev = sp_stats.ttest_ind(rv_inverted.dropna(), rv_normal.dropna())
mw_stat, mw_p = sp_stats.mannwhitneyu(rv_inverted.dropna(), rv_normal.dropna(), alternative='two-sided')

print(f"\n  Mean fwd RV22 during inversion: {rv_inverted.mean():.4f} ({rv_inverted.mean()*100:.2f}%)")
print(f"  Mean fwd RV22 during normal:    {rv_normal.mean():.4f} ({rv_normal.mean()*100:.2f}%)")
print(f"  Difference: {(rv_inverted.mean() - rv_normal.mean())*100:.2f}%")
print(f"  t-test: t={t_stat_ev:.4f}, p={p_val_ev:.4f}")
print(f"  Mann-Whitney: U={mw_stat:.0f}, p={mw_p:.4f}")

event_analysis = {
    'n_inversion_days': int(df_events['inverted'].sum()),
    'n_episodes': len(inversion_episodes),
    'episodes': inversion_episodes,
    'mean_rv22_inverted': round(rv_inverted.mean(), 4),
    'mean_rv22_normal': round(rv_normal.mean(), 4),
    'difference_pct': round((rv_inverted.mean() - rv_normal.mean()) * 100, 2),
    'ttest': {'t': round(t_stat_ev, 4), 'p': round(p_val_ev, 4)},
    'mann_whitney': {'U': round(mw_stat, 2), 'p': round(mw_p, 4)},
}

# ─── Lead-Lag Cross-Correlation ────────────────────────────────────

print("\n" + "=" * 70)
print("LEAD-LAG ANALYSIS: Slope vs VIX")
print("=" * 70)

# Cross-correlation at various lags
# slope(t-k) vs VIX(t) — does past slope predict current VIX?
lags = [0, 5, 10, 22, 44, 66, 132, 252]
lead_lag_results = {}

slope_series = df_clean['slope_10y2y_lag1']
vix_series = df_clean['vix_lag1']
rv_series = df_clean['fwd_rv22']

print("\n  Lag (days) | corr(slope_lag, VIX) | corr(slope_lag, fwd_rv22)")
print("  " + "-" * 60)

for lag in lags:
    if lag == 0:
        s = slope_series
        v = vix_series
        r = rv_series
    else:
        s = slope_series.shift(lag)
        v = vix_series
        r = rv_series

    valid = s.notna() & v.notna() & r.notna()

    corr_sv, p_sv = sp_stats.pearsonr(s[valid], v[valid])
    corr_sr, p_sr = sp_stats.pearsonr(s[valid], r[valid])

    lead_lag_results[f'lag_{lag}'] = {
        'corr_slope_vix': round(corr_sv, 4),
        'p_slope_vix': round(p_sv, 4),
        'corr_slope_rv22': round(corr_sr, 4),
        'p_slope_rv22': round(p_sr, 4),
    }

    print(f"  {lag:>10d} | {corr_sv:>+.4f} (p={p_sv:.4f}) | {corr_sr:>+.4f} (p={p_sr:.4f})")

# ─── Regime Analysis ───────────────────────────────────────────────

print("\n" + "=" * 70)
print("REGIME ANALYSIS: Slope predictive power by VIX regime")
print("=" * 70)

# Split into VIX regimes
df_clean_copy = df_clean.copy()
df_clean_copy['vix_regime'] = pd.cut(df_clean_copy['vix_lag1'], bins=[0, 15, 20, 25, 100], labels=['Low(<15)', 'Normal(15-20)', 'Elevated(20-25)', 'High(>25)'])

regime_results = {}
for regime in df_clean_copy['vix_regime'].unique():
    if pd.isna(regime):
        continue
    mask = df_clean_copy['vix_regime'] == regime
    sub = df_clean_copy[mask]
    if len(sub) < 50:
        continue

    corr_sr, p_sr = sp_stats.pearsonr(sub['slope_10y2y_lag1'], sub['fwd_rv22'])
    pr_r, pr_p = partial_corr(sub['slope_10y2y_lag1'].values, sub['fwd_rv22'].values, sub['vix_lag1'].values)

    regime_results[str(regime)] = {
        'n': len(sub),
        'corr_slope_rv22': round(corr_sr, 4),
        'p_corr': round(p_sr, 4),
        'partial_corr_given_vix': round(pr_r, 4),
        'p_partial': round(pr_p, 4),
    }
    print(f"  {regime}: n={len(sub)}, corr(slope,rv22)={corr_sr:+.4f} (p={p_sr:.4f}), "
          f"partial_corr|VIX={pr_r:+.4f} (p={pr_p:.4f})")

# ─── Inversion as Regime Transition Predictor ──────────────────────

print("\n" + "=" * 70)
print("INVERSION AS VIX REGIME TRANSITION PREDICTOR")
print("=" * 70)

# Does inversion predict VIX jumping from <20 to >25 within 6 months?
df_regime = df.dropna(subset=['slope_10y2y', 'vix']).copy()
df_regime['inverted'] = (df_regime['slope_10y2y'] < 0).astype(int)

# Forward max VIX in next 132 days (6 months)
df_regime['fwd_max_vix_6m'] = df_regime['vix'].shift(-1).rolling(132).max().shift(-131)
df_regime['vix_spike'] = (df_regime['fwd_max_vix_6m'] > 25).astype(int)

valid_mask = df_regime['vix_spike'].notna()
df_regime_clean = df_regime[valid_mask].copy()

# Contingency table
ct = pd.crosstab(df_regime_clean['inverted'], df_regime_clean['vix_spike'])
print(f"\n  Contingency Table (inverted x VIX_spike_6m):")
print(f"  {ct}")

# Compute conditional probabilities
if 1 in ct.index and 1 in ct.columns:
    prob_spike_given_inv = ct.loc[1, 1] / ct.loc[1].sum()
    prob_spike_given_normal = ct.loc[0, 1] / ct.loc[0].sum() if 0 in ct.index else 0

    # Chi-squared test
    chi2, chi_p, dof, expected = sp_stats.chi2_contingency(ct)

    print(f"\n  P(VIX>25 in 6m | inverted) = {prob_spike_given_inv:.4f} ({prob_spike_given_inv*100:.1f}%)")
    print(f"  P(VIX>25 in 6m | normal)   = {prob_spike_given_normal:.4f} ({prob_spike_given_normal*100:.1f}%)")
    print(f"  Lift: {prob_spike_given_inv/prob_spike_given_normal:.2f}x" if prob_spike_given_normal > 0 else "  Lift: N/A")
    print(f"  Chi-squared: chi2={chi2:.2f}, p={chi_p:.4f}, dof={dof}")

    regime_transition = {
        'prob_spike_given_inverted': round(prob_spike_given_inv, 4),
        'prob_spike_given_normal': round(prob_spike_given_normal, 4),
        'lift': round(prob_spike_given_inv / prob_spike_given_normal, 2) if prob_spike_given_normal > 0 else None,
        'chi2': round(chi2, 2),
        'chi_p': round(chi_p, 4),
    }
else:
    regime_transition = {'note': 'Insufficient data for contingency analysis'}
    print("  Insufficient data for contingency analysis")

# ─── Summary & Results ─────────────────────────────────────────────

print("\n" + "=" * 70)
print("SUMMARY & KEY FINDINGS")
print("=" * 70)

# Clean up model results for JSON (remove numpy arrays)
models_json = {}
for name, res in results_models.items():
    models_json[name] = {k: v for k, v in res.items() if k not in ('oos_predictions', 'oos_actual')}

# Key finding: does slope add to VIX?
vix_only_oos_r2 = results_models['A_vix_only']['OOS_R2']
vix_slope_oos_r2 = results_models['B_vix_slope']['OOS_R2']
slope_only_oos_r2 = results_models['D_slope_only']['OOS_R2']
r2_improvement = vix_slope_oos_r2 - vix_only_oos_r2

# DM significance
dm_vix_vs_vixslope = dm_results.get('A_vix_only_vs_B_vix_slope', {})

print(f"""
  1. OOS R² comparison:
     - VIX only:       {vix_only_oos_r2:.4f}
     - VIX + slope:    {vix_slope_oos_r2:.4f} (delta={r2_improvement:+.4f})
     - Slope only:     {slope_only_oos_r2:.4f}

  2. DM test (VIX vs VIX+slope): t={dm_vix_vs_vixslope.get('t_stat', 'N/A')}, Harvey significant: {dm_vix_vs_vixslope.get('significant_Harvey', 'N/A')}

  3. Partial correlation (slope|VIX): r={pr_full:.4f} (p={pp_full:.4f})

  4. Inversion event analysis:
     - Mean fwd RV22 inverted: {rv_inverted.mean():.4f} vs normal: {rv_normal.mean():.4f}
     - VIX spike (>25) probability: inverted={regime_transition.get('prob_spike_given_inverted', 'N/A')}, normal={regime_transition.get('prob_spike_given_normal', 'N/A')}

  5. Lead-lag: slope at lag-252 vs VIX: {lead_lag_results.get('lag_252', {}).get('corr_slope_vix', 'N/A')}
""")

# Conclusion
if abs(pr_full) < 0.05 and not dm_vix_vs_vixslope.get('significant_Harvey', False):
    conclusion = "YIELD CURVE ADDS NOTHING TO VIX. Partial r ~ 0, DM test not significant. VIX sufficiency CONFIRMED once more."
    verdict = "null"
elif dm_vix_vs_vixslope.get('significant_Harvey', False):
    conclusion = "YIELD CURVE SIGNIFICANTLY IMPROVES VIX-BASED VOL PREDICTION (Harvey t>3.0). Further investigation warranted."
    verdict = "significant"
else:
    conclusion = f"YIELD CURVE SHOWS MARGINAL SIGNAL (partial r={pr_full:.4f}) BUT NOT HARVEY-SIGNIFICANT. VIX remains sufficient."
    verdict = "marginal"

print(f"  VERDICT: {conclusion}")

# ─── Save Results ──────────────────────────────────────────────────

results = {
    'experiment_id': 'K871',
    'title': 'Yield Curve Slope as Volatility Predictor',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'FRED (T10Y2Y, T10Y3M, DGS10) + yfinance (SPY, ^VIX)',
    'period': f"{df_clean.index[0].date()} to {df_clean.index[-1].date()}",
    'sample_size': len(df_clean),
    'IS_period': f"{is_data.index[0].date()} to {is_data.index[-1].date()} (n={len(is_data)})",
    'OOS_period': f"{oos_data.index[0].date()} to {oos_data.index[-1].date()} (n={len(oos_data)})",
    'verdict': verdict,
    'conclusion': conclusion,
    'regression_models': models_json,
    'dm_tests_mse': dm_results,
    'dm_tests_qlike': dm_qlike_results,
    'partial_correlations': partial_corr_results,
    'event_analysis': event_analysis,
    'lead_lag_analysis': lead_lag_results,
    'regime_analysis': regime_results,
    'regime_transition': regime_transition,
    'key_findings': {
        'Q1_slope_adds_to_vix': f"OOS R2 improvement: {r2_improvement:+.4f}, partial r={pr_full:.4f}",
        'Q2_inversion_predicts_regime': f"P(spike|inverted)={regime_transition.get('prob_spike_given_inverted', 'N/A')}, lift={regime_transition.get('lift', 'N/A')}x",
        'Q3_leading_indicator': f"corr(slope_lag252, VIX)={lead_lag_results.get('lag_252', {}).get('corr_slope_vix', 'N/A')}",
    },
    'references': [
        'Estrella & Mishkin (1998) — yield curve as recession predictor',
        'Copeland & Copeland (1999) — VIX market timing',
        'Harvey et al. (2016) — t > 3.0 multiple testing threshold',
        'Patton (2011) — proxy-robust loss (QLIKE)',
        'K503: GARCH-MIDAS with T10Y2Y -> theta~0',
        'G5: 5 sentiment/financial indicators null after VIX control',
    ],
    'limitations': [
        'Forward RV22 uses daily close-to-close returns, not intraday RV',
        'FRED data forward-filled on non-trading days',
        'OOS period (2019-2026) includes COVID crash — may inflate vol differences',
        'Inversion episodes are few (small N), limiting statistical power',
        'Yield curve slope affected by QE/QT (may distort natural signal)',
    ],
}

output_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k871_results.json'
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\n  Results saved to {output_path}")
print("=" * 70)
print("K871 COMPLETE")
print("=" * 70)
