"""
K489: VIX Term Structure for Multi-Horizon Volatility Forecasting
=================================================================
[提出: User, 執行: Claude]

Research Question:
1. How well does each VIX tenor predict its "natural" horizon realized vol?
   - VIX9D → RV_5d, VIX → RV_21d, VIX3M → RV_63d
2. Which tenor predicts which horizon best? (cross-tenor analysis)
3. Does term structure shape (contango/backwardation) predict vol direction?

Builds on K429 (VIX slope → null for next-day vol).
Key difference: K429 tested slope for 1d prediction; K489 matches tenors to horizons.

Data: yfinance (^VIX, ^VIX3M, ^VIX9D, SPY), 2011-01-01 to present
IS: start-2022, OOS: 2023-2025
Metrics: R², QLIKE, DM test

References:
- Carr & Wu (2006) "A Tale of Two Indices" — VIX term structure
- Mixon (2007) "The Implied Volatility Term Structure of Stock Index Options" — JFE
- Johnson (2017) "VIX Term Structure as Predictor" — SSRN
- K429: VIX term structure slope → null for next-day vol (24th VIX sufficiency)
"""

import json
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats

warnings.filterwarnings('ignore')

# ============================================================
# 1. Data Download
# ============================================================
print("=" * 70)
print("K489: VIX Term Structure for Multi-Horizon Vol Forecasting")
print("=" * 70)

tickers = {
    'SPY': 'SPY',
    'VIX': '^VIX',
    'VIX3M': '^VIX3M',
    'VIX9D': '^VIX9D',
}

data = {}
for name, ticker in tickers.items():
    try:
        df_raw = yf.download(ticker, start='2011-01-01', end='2026-03-26', progress=False)
        if isinstance(df_raw.columns, pd.MultiIndex):
            df_raw.columns = df_raw.columns.get_level_values(0)
        data[name] = df_raw['Close'].dropna()
        print(f"  {name}: {len(data[name])} obs, "
              f"{data[name].index[0].date()} ~ {data[name].index[-1].date()}")
    except Exception as e:
        print(f"  {name}: FAILED - {e}")

has_vix9d = 'VIX9D' in data and len(data['VIX9D']) > 500
print(f"\nVIX9D available: {has_vix9d} "
      f"({len(data.get('VIX9D', [])) if 'VIX9D' in data else 0} obs)")

# ============================================================
# 2. Build Master DataFrame
# ============================================================
df = pd.DataFrame({
    'spy_close': data['SPY'],
    'vix': data['VIX'],
    'vix3m': data['VIX3M'],
})
if has_vix9d:
    df['vix9d'] = data['VIX9D']

df = df.dropna()
print(f"\nMerged data (VIX+VIX3M+SPY): {len(df)} obs, "
      f"{df.index[0].date()} ~ {df.index[-1].date()}")

# ============================================================
# 3. Feature & Target Engineering
# ============================================================
print("\n--- Feature & Target Engineering ---")

# Daily log returns
df['ret'] = np.log(df['spy_close'] / df['spy_close'].shift(1))
df['ret_sq'] = df['ret'] ** 2

# ---------- Realized Vol (annualized, forward-looking) ----------
# RV_h = sqrt(252/h * sum(r_{t+1}^2 ... r_{t+h}^2))
# Using forward rolling sum of squared returns

for h, label in [(5, 'rv_5d'), (21, 'rv_21d'), (63, 'rv_63d')]:
    # Forward-looking: sum of squared returns from t+1 to t+h
    fwd_sum = df['ret_sq'].shift(-h).rolling(h).sum().shift(1)
    # This gives sum(r_{t-h+1}^2..r_t^2) shifted to be forward
    # Correct: use .shift(-1) cumsum trick
    # Simpler: rolling on reversed or direct computation
    pass

# More robust approach: compute forward RV directly
ret_arr = df['ret'].values
n = len(ret_arr)

for h, label in [(5, 'rv_5d'), (21, 'rv_21d'), (63, 'rv_63d')]:
    rv = np.full(n, np.nan)
    for i in range(n - h):
        rv[i] = np.sqrt(252.0 / h * np.sum(ret_arr[i+1:i+1+h] ** 2))
    df[label] = rv

print(f"  RV_5d:  mean={df['rv_5d'].dropna().mean():.4f}, "
      f"std={df['rv_5d'].dropna().std():.4f}")
print(f"  RV_21d: mean={df['rv_21d'].dropna().mean():.4f}, "
      f"std={df['rv_21d'].dropna().std():.4f}")
print(f"  RV_63d: mean={df['rv_63d'].dropna().mean():.4f}, "
      f"std={df['rv_63d'].dropna().std():.4f}")

# ---------- Implied vol (convert VIX from % to decimal) ----------
df['iv_30d'] = df['vix'] / 100.0       # VIX ≈ 30-day implied vol
df['iv_90d'] = df['vix3m'] / 100.0     # VIX3M ≈ 90-day implied vol
if has_vix9d:
    df['iv_9d'] = df['vix9d'] / 100.0  # VIX9D ≈ 9-day implied vol

# ---------- Term structure features ----------
df['ts_slope'] = df['iv_90d'] - df['iv_30d']           # positive = contango
df['ts_ratio'] = df['iv_30d'] / df['iv_90d']           # >1 = backwardation
df['ts_contango'] = (df['ts_slope'] > 0).astype(int)   # binary contango flag

if has_vix9d:
    df['ts_curvature'] = df['iv_9d'] - 2 * df['iv_30d'] + df['iv_90d']
    df['ts_front_slope'] = df['iv_30d'] - df['iv_9d']  # front-end slope

# ---------- Lagged RV (persistence baseline) ----------
for h, label in [(5, 'rv_5d_lag'), (21, 'rv_21d_lag'), (63, 'rv_63d_lag')]:
    base = label.replace('_lag', '')
    df[label] = df[base].shift(h)  # lag by h to avoid overlap

# ============================================================
# 4. Descriptive Statistics
# ============================================================
print("\n--- Descriptive Statistics (Full Sample) ---")

desc_cols = ['iv_30d', 'iv_90d', 'ts_slope', 'ts_ratio',
             'rv_5d', 'rv_21d', 'rv_63d']
if has_vix9d:
    desc_cols = ['iv_9d'] + desc_cols

desc_stats = {}
for col in desc_cols:
    if col in df.columns:
        s = df[col].dropna()
        desc_stats[col] = {
            'mean': float(s.mean()), 'std': float(s.std()),
            'skew': float(s.skew()), 'kurt': float(s.kurtosis()),
            'min': float(s.min()), 'max': float(s.max()),
            'median': float(s.median()), 'n': int(len(s)),
        }
        print(f"  {col:15s}: mean={s.mean():.4f}, std={s.std():.4f}, "
              f"skew={s.skew():.2f}, kurt={s.kurtosis():.2f}")

# Term structure shape distribution
contango_pct = df['ts_contango'].dropna().mean()
print(f"\n  Contango frequency: {contango_pct:.1%}")
print(f"  Backwardation frequency: {1-contango_pct:.1%}")

# ============================================================
# 5. OOS Split
# ============================================================
IS_END = '2022-12-31'
OOS_START = '2023-01-01'

is_mask = df.index <= IS_END
oos_mask = df.index >= OOS_START

print(f"\n  IS:  {is_mask.sum()} obs "
      f"({df[is_mask].index[0].date()} ~ {df[is_mask].index[-1].date()})")
print(f"  OOS: {oos_mask.sum()} obs "
      f"({df[oos_mask].index[0].date()} ~ {df[oos_mask].index[-1].date()})")

# ============================================================
# 6. Helper Functions
# ============================================================
def qlike(actual, forecast):
    """QLIKE loss: E[actual^2/forecast^2 + ln(forecast^2)]. Lower = better."""
    a2 = actual ** 2
    f2 = forecast ** 2
    mask = (f2 > 1e-20) & (a2 > 1e-20) & np.isfinite(a2) & np.isfinite(f2)
    return float(np.mean(np.log(f2[mask]) + a2[mask] / f2[mask]))

def r2_oos(actual, forecast):
    """Out-of-sample R²: 1 - SS_res/SS_tot."""
    ss_res = np.sum((actual - forecast) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    return float(1 - ss_res / ss_tot)

def mse(actual, forecast):
    return float(np.mean((actual - forecast) ** 2))

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test with HAC variance (Newey-West).
    H0: equal predictive ability.
    Negative t-stat means model 1 (loss1) is better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_mean = np.mean(d)
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max(h, 2)):
        if k >= n:
            break
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / h) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma0 / n
    t_stat = d_mean / np.sqrt(max(var_d, 1e-20))
    p_value = 2 * stats.t.cdf(-abs(t_stat), df=n - 1)
    return float(t_stat), float(p_value)

def ols_predict(X_is, y_is, X_oos):
    """OLS with intercept. Returns OOS predictions."""
    n_is = X_is.shape[0]
    X_is_c = np.column_stack([np.ones(n_is), X_is])
    # OLS: beta = (X'X)^{-1} X'y
    try:
        beta = np.linalg.lstsq(X_is_c, y_is, rcond=None)[0]
    except np.linalg.LinAlgError:
        return np.full(X_oos.shape[0], np.nan), None
    n_oos = X_oos.shape[0]
    X_oos_c = np.column_stack([np.ones(n_oos), X_oos])
    y_pred = X_oos_c @ beta
    return y_pred, beta

# ============================================================
# 7. PART A: Matched-Tenor Forecasting
# ============================================================
print("\n" + "=" * 70)
print("PART A: Matched-Tenor Forecasting (IV → RV at natural horizon)")
print("=" * 70)

# Define tenor-horizon pairs
# Format: (name, IV_feature, RV_target, horizon_days, lag_feature)
pairs = [
    ('VIX→RV_21d',   'iv_30d',  'rv_21d', 21, 'rv_21d_lag'),  # natural match
    ('VIX3M→RV_63d', 'iv_90d',  'rv_63d', 63, 'rv_63d_lag'),  # natural match
]
if has_vix9d:
    pairs.insert(0, ('VIX9D→RV_5d', 'iv_9d', 'rv_5d', 5, 'rv_5d_lag'))

matched_results = {}

for pair_name, iv_col, rv_col, horizon, lag_col in pairs:
    print(f"\n--- {pair_name} (h={horizon}d) ---")

    # Valid data: need both IV and forward RV
    valid = df[iv_col].notna() & df[rv_col].notna() & df[lag_col].notna()
    df_valid = df[valid].copy()

    is_v = df_valid.index <= IS_END
    oos_v = df_valid.index >= OOS_START

    n_is = is_v.sum()
    n_oos = oos_v.sum()
    print(f"  IS: {n_is}, OOS: {n_oos}")

    if n_oos < 30:
        print(f"  Skipping: insufficient OOS data")
        continue

    y_is = df_valid.loc[is_v, rv_col].values
    y_oos = df_valid.loc[oos_v, rv_col].values

    models = {}

    # Model 1: Persistence baseline (lagged RV)
    X_is_lag = df_valid.loc[is_v, lag_col].values.reshape(-1, 1)
    X_oos_lag = df_valid.loc[oos_v, lag_col].values.reshape(-1, 1)
    pred_lag, beta_lag = ols_predict(X_is_lag, y_is, X_oos_lag)
    pred_lag = np.maximum(pred_lag, 1e-6)

    models['RV_lag'] = {
        'pred': pred_lag,
        'r2': r2_oos(y_oos, pred_lag),
        'qlike': qlike(y_oos, pred_lag),
        'mse': mse(y_oos, pred_lag),
        'losses_sq': (y_oos - pred_lag) ** 2,
        'losses_ql': np.log(pred_lag**2) + y_oos**2 / pred_lag**2,
        'beta': beta_lag.tolist() if beta_lag is not None else None,
    }

    # Model 2: IV only (matched tenor)
    X_is_iv = df_valid.loc[is_v, iv_col].values.reshape(-1, 1)
    X_oos_iv = df_valid.loc[oos_v, iv_col].values.reshape(-1, 1)
    pred_iv, beta_iv = ols_predict(X_is_iv, y_is, X_oos_iv)
    pred_iv = np.maximum(pred_iv, 1e-6)

    models['IV_only'] = {
        'pred': pred_iv,
        'r2': r2_oos(y_oos, pred_iv),
        'qlike': qlike(y_oos, pred_iv),
        'mse': mse(y_oos, pred_iv),
        'losses_sq': (y_oos - pred_iv) ** 2,
        'losses_ql': np.log(pred_iv**2) + y_oos**2 / pred_iv**2,
        'beta': beta_iv.tolist() if beta_iv is not None else None,
    }

    # Model 3: IV + lagged RV (combination)
    X_is_both = df_valid.loc[is_v, [iv_col, lag_col]].values
    X_oos_both = df_valid.loc[oos_v, [iv_col, lag_col]].values
    pred_both, beta_both = ols_predict(X_is_both, y_is, X_oos_both)
    pred_both = np.maximum(pred_both, 1e-6)

    models['IV+RV_lag'] = {
        'pred': pred_both,
        'r2': r2_oos(y_oos, pred_both),
        'qlike': qlike(y_oos, pred_both),
        'mse': mse(y_oos, pred_both),
        'losses_sq': (y_oos - pred_both) ** 2,
        'losses_ql': np.log(pred_both**2) + y_oos**2 / pred_both**2,
        'beta': beta_both.tolist() if beta_both is not None else None,
    }

    # Model 4: IV + lagged RV + term structure shape
    ts_features = [iv_col, lag_col, 'ts_slope', 'ts_ratio']
    X_is_full = df_valid.loc[is_v, ts_features].values
    X_oos_full = df_valid.loc[oos_v, ts_features].values
    pred_full, beta_full = ols_predict(X_is_full, y_is, X_oos_full)
    pred_full = np.maximum(pred_full, 1e-6)

    models['IV+RV_lag+TS'] = {
        'pred': pred_full,
        'r2': r2_oos(y_oos, pred_full),
        'qlike': qlike(y_oos, pred_full),
        'mse': mse(y_oos, pred_full),
        'losses_sq': (y_oos - pred_full) ** 2,
        'losses_ql': np.log(pred_full**2) + y_oos**2 / pred_full**2,
        'beta': beta_full.tolist() if beta_full is not None else None,
        'feature_names': ['intercept'] + ts_features,
    }

    # Print results
    print(f"  {'Model':<20s} {'R²':>8s} {'QLIKE':>10s} {'MSE':>12s}")
    print(f"  {'-'*52}")
    for mname, mdata in models.items():
        print(f"  {mname:<20s} {mdata['r2']:>8.4f} {mdata['qlike']:>10.4f} {mdata['mse']:>12.6f}")

    # DM tests vs RV_lag baseline (MSE-based)
    print(f"\n  DM tests vs RV_lag (MSE loss, h={horizon}):")
    base_losses = models['RV_lag']['losses_sq']
    for mname in ['IV_only', 'IV+RV_lag', 'IV+RV_lag+TS']:
        t, p = dm_test(models[mname]['losses_sq'], base_losses, h=horizon)
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
        print(f"    {mname:<20s}: t={t:+.3f}, p={p:.4f} {sig}")
        models[mname][f'dm_vs_RV_lag_t'] = t
        models[mname][f'dm_vs_RV_lag_p'] = p

    # DM tests vs RV_lag baseline (QLIKE-based)
    print(f"\n  DM tests vs RV_lag (QLIKE loss, h={horizon}):")
    base_ql = models['RV_lag']['losses_ql']
    for mname in ['IV_only', 'IV+RV_lag', 'IV+RV_lag+TS']:
        t, p = dm_test(models[mname]['losses_ql'], base_ql, h=horizon)
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
        print(f"    {mname:<20s}: t={t:+.3f}, p={p:.4f} {sig}")
        models[mname][f'dm_ql_vs_RV_lag_t'] = t
        models[mname][f'dm_ql_vs_RV_lag_p'] = p

    # DM test: IV+RV_lag+TS vs IV+RV_lag (does TS add value?)
    t_ts, p_ts = dm_test(models['IV+RV_lag+TS']['losses_sq'],
                         models['IV+RV_lag']['losses_sq'], h=horizon)
    print(f"\n  TS incremental value (IV+RV_lag+TS vs IV+RV_lag):")
    sig = "***" if p_ts < 0.01 else "**" if p_ts < 0.05 else "*" if p_ts < 0.10 else ""
    print(f"    MSE DM: t={t_ts:+.3f}, p={p_ts:.4f} {sig}")

    # Correlation: IV forecast vs RV
    corr_iv_rv = np.corrcoef(y_oos, pred_iv)[0, 1]
    print(f"\n  Corr(IV forecast, RV): {corr_iv_rv:.4f}")

    # Store results (clean up non-serializable arrays)
    pair_result = {
        'pair_name': pair_name,
        'iv_col': iv_col,
        'rv_col': rv_col,
        'horizon': horizon,
        'n_is': int(n_is),
        'n_oos': int(n_oos),
        'corr_iv_rv': float(corr_iv_rv),
    }
    for mname, mdata in models.items():
        pair_result[mname] = {
            'r2': mdata['r2'],
            'qlike': mdata['qlike'],
            'mse': mdata['mse'],
            'beta': mdata.get('beta'),
        }
        for key in mdata:
            if key.startswith('dm_'):
                pair_result[mname][key] = mdata[key]

    matched_results[pair_name] = pair_result

# ============================================================
# 8. PART B: Cross-Tenor Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART B: Cross-Tenor Analysis (each IV → each RV horizon)")
print("=" * 70)

iv_cols = ['iv_30d', 'iv_90d']
if has_vix9d:
    iv_cols = ['iv_9d'] + iv_cols

rv_targets = [
    ('rv_5d', 5, 'rv_5d_lag'),
    ('rv_21d', 21, 'rv_21d_lag'),
    ('rv_63d', 63, 'rv_63d_lag'),
]

cross_results = {}

print(f"\n  {'IV → RV':<25s} {'R² (OOS)':>10s} {'QLIKE':>10s} {'Corr':>8s} {'DM vs lag t':>12s} {'p':>8s}")
print(f"  {'-'*75}")

for iv_col in iv_cols:
    for rv_col, horizon, lag_col in rv_targets:
        label = f"{iv_col}→{rv_col}"

        valid = (df[iv_col].notna() & df[rv_col].notna() &
                 df[lag_col].notna())
        df_v = df[valid]

        is_v = df_v.index <= IS_END
        oos_v = df_v.index >= OOS_START

        if oos_v.sum() < 30:
            continue

        y_is = df_v.loc[is_v, rv_col].values
        y_oos = df_v.loc[oos_v, rv_col].values

        # IV-only model
        X_is = df_v.loc[is_v, iv_col].values.reshape(-1, 1)
        X_oos = df_v.loc[oos_v, iv_col].values.reshape(-1, 1)
        pred, beta = ols_predict(X_is, y_is, X_oos)
        pred = np.maximum(pred, 1e-6)

        r2 = r2_oos(y_oos, pred)
        ql = qlike(y_oos, pred)
        corr = float(np.corrcoef(y_oos, pred)[0, 1])

        # Lag baseline
        X_is_l = df_v.loc[is_v, lag_col].values.reshape(-1, 1)
        X_oos_l = df_v.loc[oos_v, lag_col].values.reshape(-1, 1)
        pred_l, _ = ols_predict(X_is_l, y_is, X_oos_l)
        pred_l = np.maximum(pred_l, 1e-6)

        losses_iv = (y_oos - pred) ** 2
        losses_lag = (y_oos - pred_l) ** 2
        t_dm, p_dm = dm_test(losses_iv, losses_lag, h=horizon)

        sig = "***" if p_dm < 0.01 else "**" if p_dm < 0.05 else "*" if p_dm < 0.10 else ""
        print(f"  {label:<25s} {r2:>10.4f} {ql:>10.4f} {corr:>8.4f} {t_dm:>12.3f} {p_dm:>8.4f} {sig}")

        cross_results[label] = {
            'iv_col': iv_col,
            'rv_col': rv_col,
            'horizon': horizon,
            'r2_oos': float(r2),
            'qlike': float(ql),
            'corr': float(corr),
            'mse': float(mse(y_oos, pred)),
            'r2_lag_baseline': float(r2_oos(y_oos, pred_l)),
            'dm_vs_lag_t': float(t_dm) if np.isfinite(t_dm) else None,
            'dm_vs_lag_p': float(p_dm) if np.isfinite(p_dm) else None,
            'n_oos': int(oos_v.sum()),
            'beta': beta.tolist() if beta is not None else None,
        }

# Identify best IV for each horizon
print(f"\n  Best IV for each RV horizon:")
for rv_col, _, _ in rv_targets:
    candidates = {k: v for k, v in cross_results.items() if v['rv_col'] == rv_col}
    if candidates:
        best = min(candidates.items(), key=lambda x: x[1]['qlike'])
        print(f"    {rv_col}: {best[0]} (QLIKE={best[1]['qlike']:.4f}, R²={best[1]['r2_oos']:.4f})")

# ============================================================
# 9. PART C: Term Structure Shape → Vol Direction
# ============================================================
print("\n" + "=" * 70)
print("PART C: Term Structure Shape → Vol Direction")
print("=" * 70)

# Question: does contango/backwardation predict whether vol will rise or fall?
# "Vol direction" = RV_h(t+h) > RV_h(t) for horizon h

for rv_col, horizon, _ in rv_targets:
    label = f"Direction({rv_col})"
    print(f"\n--- {label} (h={horizon}d) ---")

    # Direction: future RV > current RV
    df[f'dir_{rv_col}'] = (df[rv_col].shift(-horizon) > df[rv_col]).astype(float)
    df.loc[df[rv_col].shift(-horizon).isna(), f'dir_{rv_col}'] = np.nan

# Direction prediction using term structure
dir_results = {}

for rv_col, horizon, _ in rv_targets:
    dir_col = f'dir_{rv_col}'
    label = f"dir_{rv_col}"

    valid = (df[dir_col].notna() & df['ts_slope'].notna() &
             df['ts_ratio'].notna() & df['iv_30d'].notna())
    df_v = df[valid]
    is_v = df_v.index <= IS_END
    oos_v = df_v.index >= OOS_START

    if oos_v.sum() < 30:
        print(f"  {label}: insufficient OOS data ({oos_v.sum()})")
        continue

    y_oos = df_v.loc[oos_v, dir_col].values
    base_rate = float(y_oos.mean())
    n_oos = int(len(y_oos))

    print(f"  {label}: n_oos={n_oos}, base_rate(vol_up)={base_rate:.3f}")

    model_accs = {}

    # Simple rule: backwardation → vol rises, contango → vol falls
    # (Intuition: backwardation = short-term fear > long-term → mean-revert down)
    # Actually: backwardation = VIX > VIX3M → short term vol elevated → might decline
    # So contango might predict vol staying low, backwardation → vol declining
    # Let's test empirically

    # Rule 1: contango (slope>0) → vol stays/falls (predict 0), backwardation → vol rises (predict 1)
    pred_rule1 = (df_v.loc[oos_v, 'ts_ratio'] > 1.0).astype(float).values  # backwardation→1
    acc_rule1 = float(np.mean(pred_rule1 == y_oos))

    # Rule 2: opposite (contango → vol rises)
    acc_rule2 = float(np.mean((1 - pred_rule1) == y_oos))

    model_accs['backwardation→up'] = acc_rule1
    model_accs['contango→up'] = acc_rule2

    # OLS-based direction (probability model)
    features_dir = ['ts_slope', 'ts_ratio', 'iv_30d']
    X_is_d = df_v.loc[is_v, features_dir].values
    y_is_d = df_v.loc[is_v, dir_col].values
    X_oos_d = df_v.loc[oos_v, features_dir].values

    pred_ols, beta_ols = ols_predict(X_is_d, y_is_d, X_oos_d)
    pred_ols_binary = (pred_ols > 0.5).astype(float)
    acc_ols = float(np.mean(pred_ols_binary == y_oos))
    model_accs['OLS(slope+ratio+IV)'] = acc_ols

    # Add curvature if VIX9D available
    if has_vix9d:
        features_full = ['ts_slope', 'ts_ratio', 'iv_30d', 'ts_curvature', 'ts_front_slope']
        valid_full = df_v[features_full].notna().all(axis=1)
        if valid_full[oos_v].sum() > 30:
            X_is_f = df_v.loc[is_v & valid_full, features_full].values
            y_is_f = df_v.loc[is_v & valid_full, dir_col].values
            X_oos_f = df_v.loc[oos_v & valid_full, features_full].values
            y_oos_f = df_v.loc[oos_v & valid_full, dir_col].values
            pred_f, _ = ols_predict(X_is_f, y_is_f, X_oos_f)
            pred_f_binary = (pred_f > 0.5).astype(float)
            acc_f = float(np.mean(pred_f_binary == y_oos_f))
            model_accs['OLS(full_TS)'] = acc_f

    # Statistical significance vs 50%
    print(f"  Model accuracies:")
    for mname, acc in model_accs.items():
        n = n_oos
        se = np.sqrt(0.5 * 0.5 / n)
        z = (acc - 0.5) / se
        p = 2 * (1 - stats.norm.cdf(abs(z)))
        sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
        print(f"    {mname:<30s}: Acc={acc:.4f}, z={z:+.3f}, p={p:.4f} {sig}")

    dir_results[label] = {
        'rv_col': rv_col,
        'horizon': horizon,
        'n_oos': n_oos,
        'base_rate': base_rate,
        'model_accuracies': model_accs,
    }

# ============================================================
# 10. PART D: Contango/Backwardation Conditional RV
# ============================================================
print("\n" + "=" * 70)
print("PART D: Conditional Analysis — RV by Term Structure Regime")
print("=" * 70)

oos_df = df[oos_mask].copy()

regimes_ts = {
    'Strong Contango (slope>0.02)': oos_df['ts_slope'] > 0.02,
    'Mild Contango (0<slope≤0.02)': (oos_df['ts_slope'] > 0) & (oos_df['ts_slope'] <= 0.02),
    'Flat (|slope|≤0.005)': oos_df['ts_slope'].abs() <= 0.005,
    'Mild Backwardation (-0.02≤slope<0)': (oos_df['ts_slope'] >= -0.02) & (oos_df['ts_slope'] < 0),
    'Strong Backwardation (slope<-0.02)': oos_df['ts_slope'] < -0.02,
}

cond_results = {}
print(f"\n  {'Regime':<40s} {'n':>5s} {'RV_5d':>8s} {'RV_21d':>8s} {'RV_63d':>8s}")
print(f"  {'-'*72}")

for regime_name, mask in regimes_ts.items():
    n_reg = int(mask.sum())
    if n_reg < 10:
        continue

    rv5 = oos_df.loc[mask, 'rv_5d'].dropna().mean()
    rv21 = oos_df.loc[mask, 'rv_21d'].dropna().mean()
    rv63 = oos_df.loc[mask, 'rv_63d'].dropna().mean()

    print(f"  {regime_name:<40s} {n_reg:>5d} {rv5:>8.4f} {rv21:>8.4f} {rv63:>8.4f}")

    cond_results[regime_name] = {
        'n': n_reg,
        'rv_5d_mean': float(rv5) if np.isfinite(rv5) else None,
        'rv_21d_mean': float(rv21) if np.isfinite(rv21) else None,
        'rv_63d_mean': float(rv63) if np.isfinite(rv63) else None,
    }

# t-test: contango vs backwardation RV difference
contango_mask = oos_df['ts_slope'] > 0
backw_mask = oos_df['ts_slope'] < 0

for rv_col in ['rv_5d', 'rv_21d', 'rv_63d']:
    rv_cont = oos_df.loc[contango_mask, rv_col].dropna()
    rv_back = oos_df.loc[backw_mask, rv_col].dropna()
    if len(rv_cont) > 10 and len(rv_back) > 10:
        t, p = stats.ttest_ind(rv_cont, rv_back)
        print(f"\n  {rv_col} — Contango({len(rv_cont)}) mean={rv_cont.mean():.4f} vs "
              f"Backwardation({len(rv_back)}) mean={rv_back.mean():.4f}: "
              f"t={t:.3f}, p={p:.4f}")
        cond_results[f'ttest_{rv_col}'] = {
            'contango_mean': float(rv_cont.mean()),
            'contango_n': int(len(rv_cont)),
            'backwardation_mean': float(rv_back.mean()),
            'backwardation_n': int(len(rv_back)),
            't_stat': float(t),
            'p_value': float(p),
        }

# ============================================================
# 11. PART E: Rolling OOS Stability
# ============================================================
print("\n" + "=" * 70)
print("PART E: Rolling OOS Stability (Annual)")
print("=" * 70)

annual_stability = {}

for year in [2023, 2024, 2025]:
    yr_mask = (df.index >= f'{year}-01-01') & (df.index <= f'{year}-12-31')
    yr_data = df[yr_mask].copy()

    if len(yr_data) < 50:
        continue

    yr_results = {}
    print(f"\n  {year} (n={len(yr_data)}):")

    for rv_col, horizon, lag_col in rv_targets:
        valid_yr = yr_data[rv_col].notna() & yr_data['iv_30d'].notna() & yr_data[lag_col].notna()
        if valid_yr.sum() < 20:
            continue

        y_yr = yr_data.loc[valid_yr, rv_col].values

        # IV only (VIX30d)
        X_is_iv = df.loc[is_mask & df['iv_30d'].notna() & df[rv_col].notna(), 'iv_30d'].values.reshape(-1, 1)
        y_is_iv = df.loc[is_mask & df['iv_30d'].notna() & df[rv_col].notna(), rv_col].values
        X_yr_iv = yr_data.loc[valid_yr, 'iv_30d'].values.reshape(-1, 1)
        pred_iv_yr, _ = ols_predict(X_is_iv, y_is_iv, X_yr_iv)
        pred_iv_yr = np.maximum(pred_iv_yr, 1e-6)

        # Lag baseline
        X_is_l = df.loc[is_mask & df[lag_col].notna() & df[rv_col].notna(), lag_col].values.reshape(-1, 1)
        y_is_l = df.loc[is_mask & df[lag_col].notna() & df[rv_col].notna(), rv_col].values
        X_yr_l = yr_data.loc[valid_yr, lag_col].values.reshape(-1, 1)
        pred_l_yr, _ = ols_predict(X_is_l, y_is_l, X_yr_l)
        pred_l_yr = np.maximum(pred_l_yr, 1e-6)

        r2_iv = r2_oos(y_yr, pred_iv_yr)
        r2_lag = r2_oos(y_yr, pred_l_yr)

        yr_results[rv_col] = {
            'n': int(valid_yr.sum()),
            'r2_iv30d': float(r2_iv),
            'r2_lag': float(r2_lag),
        }

        print(f"    {rv_col}: IV R²={r2_iv:.4f}, Lag R²={r2_lag:.4f} "
              f"(IV {'>' if r2_iv > r2_lag else '<'} Lag)")

    annual_stability[str(year)] = yr_results

# ============================================================
# 12. PART F: Implied-Realized Spread Analysis
# ============================================================
print("\n" + "=" * 70)
print("PART F: Implied-Realized Spread (Variance Risk Premium)")
print("=" * 70)

# VRP = IV - RV (positive = risk premium)
df['vrp_30d'] = df['iv_30d'] - df['rv_21d']
df['vrp_90d'] = df['iv_90d'] - df['rv_63d']
if has_vix9d:
    df['vrp_9d'] = df['iv_9d'] - df['rv_5d']

print(f"\n  VRP Statistics (OOS):")
vrp_results = {}
vrp_cols = ['vrp_30d', 'vrp_90d']
if has_vix9d:
    vrp_cols = ['vrp_9d'] + vrp_cols

for col in vrp_cols:
    s = df.loc[oos_mask, col].dropna()
    if len(s) > 10:
        print(f"    {col}: mean={s.mean():.4f}, std={s.std():.4f}, "
              f"median={s.median():.4f}, pct_positive={float((s>0).mean()):.1%}")

        # t-test: VRP > 0?
        t, p = stats.ttest_1samp(s, 0)
        print(f"      H0: VRP=0 → t={t:.3f}, p={p:.4f}")

        vrp_results[col] = {
            'mean': float(s.mean()),
            'std': float(s.std()),
            'median': float(s.median()),
            'pct_positive': float((s > 0).mean()),
            'ttest_t': float(t),
            'ttest_p': float(p),
            'n': int(len(s)),
        }

# Does VRP predict future RV?
print(f"\n  VRP as predictor of next-period RV:")
vrp_pred_results = {}

for vrp_col, rv_col, horizon, lag_col in [
    ('vrp_30d', 'rv_21d', 21, 'rv_21d_lag'),
    ('vrp_90d', 'rv_63d', 63, 'rv_63d_lag'),
]:
    valid = df[vrp_col].notna() & df[rv_col].notna() & df[lag_col].notna()
    df_v = df[valid]
    is_v = df_v.index <= IS_END
    oos_v = df_v.index >= OOS_START

    if oos_v.sum() < 30:
        continue

    y_is = df_v.loc[is_v, rv_col].values
    y_oos = df_v.loc[oos_v, rv_col].values

    # Lag + VRP model
    X_is_vp = df_v.loc[is_v, [lag_col, vrp_col]].values
    X_oos_vp = df_v.loc[oos_v, [lag_col, vrp_col]].values
    pred_vp, beta_vp = ols_predict(X_is_vp, y_is, X_oos_vp)
    pred_vp = np.maximum(pred_vp, 1e-6)

    # Lag only baseline
    X_is_l = df_v.loc[is_v, lag_col].values.reshape(-1, 1)
    X_oos_l = df_v.loc[oos_v, lag_col].values.reshape(-1, 1)
    pred_l, _ = ols_predict(X_is_l, y_is, X_oos_l)
    pred_l = np.maximum(pred_l, 1e-6)

    r2_vp = r2_oos(y_oos, pred_vp)
    r2_l = r2_oos(y_oos, pred_l)

    losses_vp = (y_oos - pred_vp) ** 2
    losses_l = (y_oos - pred_l) ** 2
    t_dm, p_dm = dm_test(losses_vp, losses_l, h=horizon)

    sig = "***" if p_dm < 0.01 else "**" if p_dm < 0.05 else "*" if p_dm < 0.10 else ""
    print(f"    {vrp_col}→{rv_col}: R²(lag+VRP)={r2_vp:.4f}, R²(lag)={r2_l:.4f}, "
          f"DM t={t_dm:+.3f}, p={p_dm:.4f} {sig}")

    vrp_pred_results[f'{vrp_col}→{rv_col}'] = {
        'r2_lag_vrp': float(r2_vp),
        'r2_lag_only': float(r2_l),
        'dm_t': float(t_dm) if np.isfinite(t_dm) else None,
        'dm_p': float(p_dm) if np.isfinite(p_dm) else None,
        'beta': beta_vp.tolist() if beta_vp is not None else None,
    }

# ============================================================
# 13. Summary & Conclusions
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY & CONCLUSIONS")
print("=" * 70)

conclusions = {}

# Q1: How well does each tenor predict its natural horizon?
print("\nQ1: Matched-tenor forecasting quality")
for pair_name, res in matched_results.items():
    iv_r2 = res['IV_only']['r2']
    lag_r2 = res['RV_lag']['r2']
    combo_r2 = res['IV+RV_lag']['r2']
    print(f"  {pair_name}: IV R²={iv_r2:.4f}, Lag R²={lag_r2:.4f}, "
          f"IV+Lag R²={combo_r2:.4f}")

# Q2: Which tenor is best for each horizon?
print("\nQ2: Best IV tenor for each horizon (by QLIKE)")
best_cross = {}
for rv_col, _, _ in rv_targets:
    candidates = {k: v for k, v in cross_results.items() if v['rv_col'] == rv_col}
    if candidates:
        best = min(candidates.items(), key=lambda x: x[1]['qlike'])
        best_cross[rv_col] = best[0]
        print(f"  {rv_col}: {best[0]} (QLIKE={best[1]['qlike']:.4f})")

conclusions['best_iv_per_horizon'] = best_cross

# Q3: Does term structure shape predict vol direction?
print("\nQ3: Term structure shape → vol direction")
any_significant = False
for label, res in dir_results.items():
    best_acc_name = max(res['model_accuracies'].items(), key=lambda x: x[1])
    n = res['n_oos']
    se = np.sqrt(0.5 * 0.5 / n)
    z = (best_acc_name[1] - 0.5) / se
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    significant = p < 0.05 and best_acc_name[1] > 0.55
    if significant:
        any_significant = True
    sig_str = "SIGNIFICANT" if significant else "not significant"
    print(f"  {label}: best={best_acc_name[0]} (Acc={best_acc_name[1]:.4f}, p={p:.4f}) — {sig_str}")

conclusions['direction_prediction_significant'] = any_significant

# Overall verdict
print("\n" + "-" * 70)

# Check if matched tenor beats lag baseline significantly
matched_beats_lag = {}
for pair_name, res in matched_results.items():
    dm_p = res['IV_only'].get('dm_vs_RV_lag_p', 1.0)
    iv_r2 = res['IV_only']['r2']
    lag_r2 = res['RV_lag']['r2']
    beats = (dm_p is not None and dm_p < 0.05 and iv_r2 > lag_r2)
    matched_beats_lag[pair_name] = beats
    if beats:
        print(f"  ✓ {pair_name}: IV BEATS lag baseline (DM p={dm_p:.4f})")
    else:
        print(f"  ✗ {pair_name}: IV does NOT beat lag baseline (DM p={dm_p:.4f})")

conclusions['matched_beats_lag'] = {k: bool(v) for k, v in matched_beats_lag.items()}

# Term structure incremental value
ts_incremental = {}
for pair_name, res in matched_results.items():
    if 'IV+RV_lag+TS' in res and 'IV+RV_lag' in res:
        ts_r2 = res['IV+RV_lag+TS']['r2']
        no_ts_r2 = res['IV+RV_lag']['r2']
        ts_incremental[pair_name] = {
            'r2_with_ts': float(ts_r2),
            'r2_without_ts': float(no_ts_r2),
            'improvement': float(ts_r2 - no_ts_r2),
        }
        print(f"  TS incremental for {pair_name}: "
              f"R² {no_ts_r2:.4f} → {ts_r2:.4f} (Δ={ts_r2-no_ts_r2:+.4f})")

conclusions['ts_incremental'] = ts_incremental

# Final verdict
all_beats = all(matched_beats_lag.values()) if matched_beats_lag else False
some_beats = any(matched_beats_lag.values()) if matched_beats_lag else False

if all_beats:
    verdict = "VIX tenor-matched IV consistently beats persistence baseline across all horizons"
elif some_beats:
    beating = [k for k, v in matched_beats_lag.items() if v]
    verdict = f"VIX IV beats persistence for some horizons ({', '.join(beating)}) but not all"
else:
    verdict = "VIX IV does NOT significantly beat persistence baseline at any horizon"

if any_significant:
    verdict += ". Term structure shape has predictive power for vol direction."
else:
    verdict += ". Term structure shape does NOT predict vol direction."

conclusions['overall_verdict'] = verdict
print(f"\n  OVERALL: {verdict}")

# ============================================================
# 14. Save Results
# ============================================================
final_results = {
    'experiment_id': 'K489',
    'title': 'VIX Term Structure for Multi-Horizon Volatility Forecasting',
    'hypothesis': 'VIX term structure tenors predict corresponding-horizon realized vol, and term structure shape predicts vol direction',
    'builds_on': 'K429 (VIX slope → null for next-day vol)',
    'data_source': 'yfinance: ^VIX (30d), ^VIX3M (90d), ^VIX9D (9d), SPY',
    'data_period': f"{df.index[0].date()} ~ {df.index[-1].date()}",
    'is_period': f"{df[is_mask].index[0].date()} ~ {df[is_mask].index[-1].date()}",
    'oos_period': f"{df[oos_mask].index[0].date()} ~ {df[oos_mask].index[-1].date()}",
    'n_total': int(len(df)),
    'n_is': int(is_mask.sum()),
    'n_oos': int(oos_mask.sum()),
    'vix9d_available': has_vix9d,
    'methodology': {
        'rv_computation': 'RV_h = sqrt(252/h * sum(r_{t+1}^2 ... r_{t+h}^2)), annualized',
        'models': 'OLS with intercept',
        'evaluation': 'R² (OOS), QLIKE, MSE, DM test (HAC)',
        'direction': 'Binary (RV_h(t+h) > RV_h(t)), tested with z-test vs 50%',
    },
    'references': [
        'Carr & Wu (2006) - A Tale of Two Indices',
        'Mixon (2007) - Implied Volatility Term Structure, JFE',
        'Johnson (2017) - VIX Term Structure as Predictor, SSRN',
        'K429 - VIX term structure slope null for next-day vol',
    ],
    'descriptive_statistics': desc_stats,
    'part_a_matched_tenor': matched_results,
    'part_b_cross_tenor': cross_results,
    'part_c_direction': dir_results,
    'part_d_conditional_rv': cond_results,
    'part_e_annual_stability': annual_stability,
    'part_f_vrp': {
        'vrp_stats': vrp_results,
        'vrp_as_predictor': vrp_pred_results,
    },
    'conclusions': conclusions,
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

output_path = 'experiments/k489_vix_term_structure_results.json'
with open(output_path, 'w') as f:
    json.dump(final_results, f, indent=2, default=str)

print(f"\nResults saved to {output_path}")
print("Done.")
