#!/usr/bin/env python3
"""
K1063: Realized Semi-Variance — Upside vs Downside Asymmetry Decomposition

Tests whether decomposing realized variance into positive (RV+) and negative
(RV-) semi-variances improves daily RV forecasting, based on Barndorff-Nielsen,
Kinnebrock & Shephard (2010) and Patton & Sheppard (2015).

Research Questions:
1. Are RV+ and RV- symmetric on average, or does downside dominate?
2. Does HAR-SV (positive/negative decomposition) beat plain HAR-RV?
3. Signed jump variation SJ = RV+ - RV- — any incremental predictive power?
4. Is the downside half-variance coefficient (beta-) larger than beta+ ?
5. How do HAR variants compare to GJR-GARCH and A4f-VIX (Patton 2011 fair)?

Data:
- 5-min SPY data: data/intraday/SPY_5min_YYYY-MM-DD.csv (60 files, 2026-01-14 ~ 2026-04-10)
- Daily SPY/VIX: yfinance (expanding window for GARCH/A4f)

References:
- Barndorff-Nielsen, Kinnebrock & Shephard (2010). Measuring downside
  risk-realised semivariance. Festschrift for R. Engle.
- Patton & Sheppard (2015). Good volatility, bad volatility: Signed jumps and
  the persistence of volatility. Review of Economics and Statistics 97(3).
- Corsi (2009). A simple approximate long-memory model of realized volatility.
  Journal of Financial Econometrics 7(2).
- Patton (2011). Volatility forecast comparison using imperfect volatility
  proxies. Journal of Econometrics.

Status: PRELIMINARY (OOS ~30 days; 60-day 5-min sample, same sample as K1057)
Random seed: 42

Prior: K1054 (60-day HAR-RV vs A4f baseline), K1057 (jump decomposition NULL)
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from glob import glob
import math as _math

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings('ignore')
np.random.seed(42)

# ── Paths ──
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'
DATA_DIR = os.path.join(MAIN_REPO, 'data', 'intraday')
OUTPUT_DIR = BASE_DIR

print("=" * 72)
print("K1063: Realized Semi-Variance Decomposition (Upside vs Downside)")
print("=" * 72)


# ═══════════════════════════════════════════════════════════════════════
# 1. LOAD 5-MIN DATA AND COMPUTE RV, RV+, RV-
# ═══════════════════════════════════════════════════════════════════════

print("\n[1] Loading 5-min data and computing RV, RV+, RV- ...")

fivemin_files = sorted(glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv')))
print(f"  Found {len(fivemin_files)} 5-min CSV files")


def compute_semi_variance(filepath):
    """Compute RV, RV+ (upside), RV- (downside) from 5-min data.

    RV   = sum(r_i^2)
    RV+  = sum(r_i^2 * 1{r_i > 0})
    RV-  = sum(r_i^2 * 1{r_i < 0})
    SJ   = RV+ - RV-   (signed jump, BNKS 2010 / PS 2015)

    Decomposition identity: RV = RV+ + RV- (up to r_i=0 contributions).
    """
    df = pd.read_csv(filepath, header=[0, 1], index_col=0, parse_dates=True)

    close = df[('Close', 'SPY')].dropna()
    if len(close) < 5:
        return None

    returns = close.pct_change().dropna()
    n = len(returns)
    if n < 3:
        return None

    r = returns.values
    r2 = r ** 2

    pos_mask = r > 0
    neg_mask = r < 0

    rv = float(np.sum(r2))
    rv_pos = float(np.sum(r2[pos_mask]))
    rv_neg = float(np.sum(r2[neg_mask]))
    sj = rv_pos - rv_neg

    n_pos = int(np.sum(pos_mask))
    n_neg = int(np.sum(neg_mask))

    # Daily close-to-open daily-direction proxy (first vs last)
    close_price = float(close.iloc[-1])
    open_price = float(close.iloc[0])
    day_ret = (close_price / open_price - 1.0) if open_price > 0 else 0.0

    return {
        'rv': rv,
        'rv_pos': rv_pos,
        'rv_neg': rv_neg,
        'sj': sj,
        'n_bars': n,
        'n_pos': n_pos,
        'n_neg': n_neg,
        'day_ret': day_ret,
    }


daily_data = {}
for fpath in fivemin_files:
    date_str = os.path.basename(fpath).replace('SPY_5min_', '').replace('.csv', '')
    out = compute_semi_variance(fpath)
    if out is not None:
        daily_data[date_str] = out

print(f"  Successfully processed: {len(daily_data)} days")

dates = sorted(daily_data.keys())
df_rv = pd.DataFrame([daily_data[d] for d in dates], index=pd.to_datetime(dates))
df_rv.index.name = 'Date'

# Sanity check: RV+ + RV- should approx equal RV (allowing for r=0 ticks)
decomp_error = (df_rv['rv'] - (df_rv['rv_pos'] + df_rv['rv_neg'])).abs().max()
print(f"  Decomposition check: max |RV - (RV+ + RV-)| = {decomp_error:.3e}")

print(f"  Date range: {df_rv.index[0].date()} to {df_rv.index[-1].date()}")
print(f"  RV    mean: {df_rv['rv'].mean():.6e}")
print(f"  RV+   mean: {df_rv['rv_pos'].mean():.6e}   ({df_rv['rv_pos'].mean()/df_rv['rv'].mean()*100:.1f}% of RV)")
print(f"  RV-   mean: {df_rv['rv_neg'].mean():.6e}   ({df_rv['rv_neg'].mean()/df_rv['rv'].mean()*100:.1f}% of RV)")
print(f"  SJ    mean: {df_rv['sj'].mean():.6e}")


# ═══════════════════════════════════════════════════════════════════════
# 2. LOAD DAILY SPY / VIX FOR BENCHMARKS AND LEVERAGE DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════

print("\n[2] Loading daily SPY/VIX data...")

try:
    import yfinance as yf
    spy_data = yf.download('SPY', start='2016-01-01', end='2026-04-11', progress=False)
    vix_data = yf.download('^VIX', start='2016-01-01', end='2026-04-11', progress=False)

    if isinstance(spy_data.columns, pd.MultiIndex):
        spy_close = spy_data[('Close', 'SPY')].squeeze()
    else:
        spy_close = spy_data['Close'].squeeze()

    if isinstance(vix_data.columns, pd.MultiIndex):
        vix_close = vix_data[('Close', '^VIX')].squeeze()
    else:
        vix_close = vix_data['Close'].squeeze()

    daily_ret = spy_close.pct_change().dropna()
    daily_r2 = daily_ret ** 2

    print(f"  Daily SPY: {len(daily_ret)} returns, VIX: {len(vix_close)} obs")
except Exception as e:
    print(f"  ERROR loading yfinance data: {e}")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════
# 3. DESCRIPTIVE + DIAGNOSTIC STATS (LEVERAGE / ASYMMETRY)
# ═══════════════════════════════════════════════════════════════════════

print("\n[3] Descriptive statistics and leverage diagnostics...")


def acf_k(x, k):
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n <= k:
        return float('nan')
    xm = x - x.mean()
    c0 = float(np.sum(xm ** 2))
    if c0 <= 0:
        return 0.0
    ck = float(np.sum(xm[k:] * xm[:-k]))
    return ck / c0


acf_table = {}
for name, series in [('rv', df_rv['rv']), ('rv_pos', df_rv['rv_pos']),
                     ('rv_neg', df_rv['rv_neg']), ('sj', df_rv['sj'])]:
    vals = series.values
    acf_table[name] = {
        'lag1': acf_k(vals, 1),
        'lag5': acf_k(vals, 5),
        'lag22': acf_k(vals, 22),
    }
    print(f"  ACF {name:7s}: lag1={acf_table[name]['lag1']:+.3f} | "
          f"lag5={acf_table[name]['lag5']:+.3f} | lag22={acf_table[name]['lag22']:+.3f}")

# Symmetry: paired t-test for mean(RV+) vs mean(RV-)
diff_pn = df_rv['rv_pos'].values - df_rv['rv_neg'].values
t_sym, p_sym = stats.ttest_rel(df_rv['rv_pos'].values, df_rv['rv_neg'].values)
print(f"\n  Symmetry: mean(RV+) - mean(RV-) = {diff_pn.mean():+.3e}, "
      f"paired t={t_sym:+.3f}, p={p_sym:.3f}")
print(f"    Interpretation: {'RV+ != RV-' if p_sym < 0.05 else 'cannot reject RV+ = RV-'}")

# Leverage: corr(daily_ret_t, RV-_{t+1} - RV+_{t+1})
# Align daily_ret with df_rv dates (daily_ret indexed on SPY trading dates)
# We need daily SPY returns for dates matching df_rv
daily_ret_aligned = daily_ret.reindex(df_rv.index).dropna()

# Shift RV to get future values
future_rv_pos = df_rv['rv_pos'].shift(-1)
future_rv_neg = df_rv['rv_neg'].shift(-1)
future_sj = (future_rv_neg - future_rv_pos).reindex(daily_ret_aligned.index).dropna()
lev_align = daily_ret_aligned.reindex(future_sj.index)

leverage_corr = float(lev_align.corr(future_sj))
print(f"  Leverage effect: corr(r_t, RV-_{{t+1}} - RV+_{{t+1}}) = {leverage_corr:+.3f}")

# Also: corr(r_t, RV-_{t+1}) and corr(r_t, RV+_{t+1}) separately
fut_rv_neg_a = future_rv_neg.reindex(daily_ret_aligned.index).dropna()
fut_rv_pos_a = future_rv_pos.reindex(daily_ret_aligned.index).dropna()
lev_neg = float(daily_ret_aligned.reindex(fut_rv_neg_a.index).corr(fut_rv_neg_a))
lev_pos = float(daily_ret_aligned.reindex(fut_rv_pos_a.index).corr(fut_rv_pos_a))
print(f"    corr(r_t, RV-_{{t+1}}) = {lev_neg:+.3f}  (negative expected)")
print(f"    corr(r_t, RV+_{{t+1}}) = {lev_pos:+.3f}")

desc_stats = {
    'n_days': int(len(df_rv)),
    'date_start': str(df_rv.index[0].date()),
    'date_end': str(df_rv.index[-1].date()),
    'rv': {
        'mean': float(df_rv['rv'].mean()),
        'std': float(df_rv['rv'].std()),
        'min': float(df_rv['rv'].min()),
        'max': float(df_rv['rv'].max()),
        'skew': float(df_rv['rv'].skew()),
        'kurtosis': float(df_rv['rv'].kurtosis()),
    },
    'rv_pos': {
        'mean': float(df_rv['rv_pos'].mean()),
        'std': float(df_rv['rv_pos'].std()),
        'share_of_rv': float(df_rv['rv_pos'].sum() / df_rv['rv'].sum()),
    },
    'rv_neg': {
        'mean': float(df_rv['rv_neg'].mean()),
        'std': float(df_rv['rv_neg'].std()),
        'share_of_rv': float(df_rv['rv_neg'].sum() / df_rv['rv'].sum()),
    },
    'signed_jump': {
        'mean': float(df_rv['sj'].mean()),
        'std': float(df_rv['sj'].std()),
        'pct_positive': float((df_rv['sj'] > 0).mean()),
    },
    'symmetry_ttest': {
        't_stat': float(t_sym),
        'p_value': float(p_sym),
        'reject_symmetry': bool(p_sym < 0.05),
    },
    'decomp_max_abs_error': float(decomp_error),
    'acf': acf_table,
    'leverage_corr': {
        'r_t_vs_rv_neg_minus_pos_tp1': leverage_corr,
        'r_t_vs_rv_neg_tp1': lev_neg,
        'r_t_vs_rv_pos_tp1': lev_pos,
    },
}


# ═══════════════════════════════════════════════════════════════════════
# 4. HAR VARIANTS (EXPANDING WINDOW OLS)
# ═══════════════════════════════════════════════════════════════════════

print("\n[4] Fitting HAR variants (expanding-window OLS)...")


def make_har_features(series, prefix):
    """Daily / weekly (5d) / monthly (22d) rolling means."""
    d = pd.DataFrame({f'{prefix}_d': series})
    d[f'{prefix}_w'] = series.rolling(5, min_periods=1).mean()
    d[f'{prefix}_m'] = series.rolling(22, min_periods=1).mean()
    return d


feat_rv = make_har_features(df_rv['rv'], 'rv')
feat_pos = make_har_features(df_rv['rv_pos'], 'p')
feat_neg = make_har_features(df_rv['rv_neg'], 'n')

rv_values = df_rv['rv'].values
rv_pos_values = df_rv['rv_pos'].values
rv_neg_values = df_rv['rv_neg'].values
sj_values = df_rv['sj'].values

INIT_WINDOW = 30
n_total = len(df_rv)
oos_start_idx = INIT_WINDOW
if oos_start_idx >= n_total:
    print("  ERROR: Not enough data for OOS forecasting!")
    sys.exit(1)
n_oos = n_total - oos_start_idx
print(f"  Training window: expanding from {INIT_WINDOW} days")
print(f"  OOS period: {n_oos} days "
      f"({df_rv.index[oos_start_idx].date()} to {df_rv.index[-1].date()})")


def ols_forecast(X_train, y_train, x_test, fallback):
    """OLS forecast with intercept; returns forecast and coefficients (including intercept)."""
    n = X_train.shape[0]
    X = np.column_stack([np.ones(n), X_train])
    try:
        beta = np.linalg.lstsq(X, y_train, rcond=None)[0]
    except Exception:
        return fallback, None
    x_t = np.concatenate([[1.0], x_test])
    fc = float(x_t @ beta)
    if not np.isfinite(fc):
        return fallback, beta
    return max(fc, 1e-12), beta


# Model specifications. Each entry: (feature_builder_fn, feature_names_test)
# feature_builder_fn(train_end) -> (X_train (T-1, k), x_test (k,))

def _rv_features(t):
    """HAR-RV baseline features at time t (features) and t-1 (test)."""
    X = feat_rv[['rv_d', 'rv_w', 'rv_m']].values[:t - 1]
    x = feat_rv[['rv_d', 'rv_w', 'rv_m']].values[t - 1]
    return X, x


def _sv_features(t):
    """HAR-SV: RV+_{t-1}, RV-_{t-1}, RV_w_{t-1}, RV_m_{t-1}."""
    X = np.column_stack([
        rv_pos_values[:t - 1],
        rv_neg_values[:t - 1],
        feat_rv['rv_w'].values[:t - 1],
        feat_rv['rv_m'].values[:t - 1],
    ])
    x = np.array([
        rv_pos_values[t - 1],
        rv_neg_values[t - 1],
        feat_rv['rv_w'].values[t - 1],
        feat_rv['rv_m'].values[t - 1],
    ])
    return X, x


def _rvsj_features(t):
    """HAR-RV-SJ: RV_d, SJ_d, RV_w, RV_m."""
    X = np.column_stack([
        rv_values[:t - 1],
        sj_values[:t - 1],
        feat_rv['rv_w'].values[:t - 1],
        feat_rv['rv_m'].values[:t - 1],
    ])
    x = np.array([
        rv_values[t - 1],
        sj_values[t - 1],
        feat_rv['rv_w'].values[t - 1],
        feat_rv['rv_m'].values[t - 1],
    ])
    return X, x


def _down_features(t):
    """HAR-RV-down: all downside (RV-_d, RV-_w, RV-_m)."""
    X = feat_neg[['n_d', 'n_w', 'n_m']].values[:t - 1]
    x = feat_neg[['n_d', 'n_w', 'n_m']].values[t - 1]
    return X, x


def _ll_features(t):
    """HAR-LL leverage-only: RV_d, RV-_d, RV_w, RV_m."""
    X = np.column_stack([
        rv_values[:t - 1],
        rv_neg_values[:t - 1],
        feat_rv['rv_w'].values[:t - 1],
        feat_rv['rv_m'].values[:t - 1],
    ])
    x = np.array([
        rv_values[t - 1],
        rv_neg_values[t - 1],
        feat_rv['rv_w'].values[t - 1],
        feat_rv['rv_m'].values[t - 1],
    ])
    return X, x


model_specs = {
    'HAR-RV': (_rv_features, ['RV_d', 'RV_w', 'RV_m']),
    'HAR-SV': (_sv_features, ['RV+_d', 'RV-_d', 'RV_w', 'RV_m']),
    'HAR-RV-SJ': (_rvsj_features, ['RV_d', 'SJ_d', 'RV_w', 'RV_m']),
    'HAR-RV-down': (_down_features, ['RV-_d', 'RV-_w', 'RV-_m']),
    'HAR-LL': (_ll_features, ['RV_d', 'RV-_d', 'RV_w', 'RV_m']),
}

forecasts = {name: np.full(n_oos, np.nan) for name in model_specs}
coef_series = {name: [] for name in model_specs}  # track beta coefficients over time
fallback_mean = float(np.mean(rv_values[:INIT_WINDOW]))

for i in range(n_oos):
    t = oos_start_idx + i  # predicting RV at index t using info up to t-1
    train_end = t  # exclusive
    y_train = rv_values[1:train_end]  # targets RV_1, ..., RV_{t-1}

    for name, (feat_fn, _) in model_specs.items():
        X_train, x_test = feat_fn(t)
        fc, beta = ols_forecast(X_train, y_train, x_test, fallback_mean)
        forecasts[name][i] = fc
        coef_series[name].append(beta.tolist() if beta is not None else None)

print("  HAR variants fitted.")
for name in model_specs:
    m = np.nanmean(forecasts[name])
    print(f"    {name:14s}: mean forecast = {m:.6e}")

# Summary: final-window coefficient estimates (full-sample OLS for interpretation)
print("\n  Full-sample OLS coefficients (for interpretation only, not used in OOS):")
full_sample_coefs = {}
for name, (feat_fn, feat_names) in model_specs.items():
    X_full, _ = feat_fn(n_total)
    y_full = rv_values[1:n_total]
    X = np.column_stack([np.ones(len(X_full)), X_full])
    try:
        beta = np.linalg.lstsq(X, y_full, rcond=None)[0]
        # Standard errors
        resid = y_full - X @ beta
        sigma2 = np.sum(resid ** 2) / max(len(y_full) - X.shape[1], 1)
        try:
            cov = sigma2 * np.linalg.inv(X.T @ X)
            se = np.sqrt(np.diag(cov))
        except np.linalg.LinAlgError:
            se = np.full(len(beta), np.nan)
        t_stats = beta / np.where(se > 0, se, np.nan)
    except Exception:
        beta = None
        se = None
        t_stats = None

    coefs = {'intercept': float(beta[0]) if beta is not None else None,
             'intercept_t': float(t_stats[0]) if t_stats is not None else None}
    for j, nm in enumerate(feat_names):
        coefs[nm] = float(beta[j + 1]) if beta is not None else None
        coefs[f'{nm}_t'] = float(t_stats[j + 1]) if t_stats is not None else None
    full_sample_coefs[name] = coefs
    print(f"    {name:14s}:")
    for k, v in coefs.items():
        if k.endswith('_t'):
            continue
        tkey = f'{k}_t'
        tval = coefs.get(tkey, None)
        tstr = f"(t={tval:+.2f})" if tval is not None and np.isfinite(tval) else ""
        print(f"      {k:10s} = {v:+.4e} {tstr}")


# ═══════════════════════════════════════════════════════════════════════
# 5. GARCH + A4f BENCHMARKS
# ═══════════════════════════════════════════════════════════════════════

print("\n[5] Fitting GJR-GARCH and A4f-VIX² benchmarks...")

oos_dates = df_rv.index[oos_start_idx:]

# GJR-GARCH: rolling w=2000 estimate, forecast 1-step variance in daily units
garch_forecasts = {}
try:
    from arch import arch_model
    for d in oos_dates:
        if d not in daily_ret.index:
            continue
        d_loc = daily_ret.index.get_loc(d)
        if d_loc < 2000:
            continue
        train_ret = daily_ret.iloc[d_loc - 2000:d_loc] * 100.0  # to percent

        try:
            model = arch_model(train_ret, vol='GARCH', p=1, o=1, q=1, dist='normal')
            res = model.fit(disp='off', show_warning=False)
            fc = res.forecast(horizon=1)
            sigma2 = float(fc.variance.values[-1, 0]) / 10000.0
            garch_forecasts[d] = max(sigma2, 1e-12)
        except Exception:
            pass
    print(f"  GJR-GARCH: {len(garch_forecasts)} OOS forecasts")
except Exception as e:
    print(f"  GJR-GARCH skipped: {e}")

# A4f-VIX²: VIX²/252 (lagged one day)
a4f_forecasts = {}
for d in oos_dates:
    if d not in vix_close.index:
        continue
    d_loc = vix_close.index.get_loc(d)
    if d_loc < 1:
        continue
    vix_prev = float(vix_close.iloc[d_loc - 1])
    a4f_forecasts[d] = (vix_prev / 100.0) ** 2 / 252.0
print(f"  A4f-VIX²: {len(a4f_forecasts)} OOS forecasts")


# ═══════════════════════════════════════════════════════════════════════
# 6. EVALUATION (QLIKE / MSE / MAE, RV + r² PROXIES)
# ═══════════════════════════════════════════════════════════════════════

print("\n[6] Evaluation...")


def qlike(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    predicted = np.maximum(predicted, 1e-12)
    loss = actual / predicted + np.log(predicted)
    return float(np.nanmean(loss))


def qlike_losses(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.maximum(np.asarray(predicted, dtype=float), 1e-12)
    return actual / predicted + np.log(predicted)


def mse(actual, predicted):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    return float(np.nanmean((a - p) ** 2))


def mae(actual, predicted):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    return float(np.nanmean(np.abs(a - p)))


def dm_test(loss1, loss2):
    """Diebold-Mariano with HAC (Newey-West); Harvey (2016) style |t|>3.0 threshold."""
    d = np.asarray(loss1, dtype=float) - np.asarray(loss2, dtype=float)
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 5:
        return float('nan'), float('nan')
    d_mean = float(np.mean(d))
    max_lag = max(1, int(n ** (1.0 / 3.0)))
    gamma0 = float(np.var(d, ddof=1))
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1.0 - k / (max_lag + 1.0)
        gamma_k = float(np.mean((d[k:] - d_mean) * (d[:-k] - d_mean)))
        gamma_sum += 2.0 * w * gamma_k
    var_d = gamma0 + gamma_sum
    if var_d <= 0:
        return float('nan'), float('nan')
    t_stat = d_mean / np.sqrt(var_d / n)
    p_val = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


# Build arrays on common OOS dates (all-model intersection)
har_idx_map = {d: i for i, d in enumerate(oos_dates)}

common_dates = sorted(
    set(oos_dates)
    & set(garch_forecasts.keys())
    & set(a4f_forecasts.keys())
    & set(daily_r2.index)
)
print(f"  Common OOS dates (all models): {len(common_dates)}")

if len(common_dates) < 5:
    print("  WARNING: very few common dates, DM tests unreliable")

rv_common = np.array([float(df_rv.loc[d, 'rv']) for d in common_dates])
r2_common = np.array([float(daily_r2.loc[d]) for d in common_dates])
garch_common = np.array([garch_forecasts[d] for d in common_dates])
a4f_common = np.array([a4f_forecasts[d] for d in common_dates])

har_common = {}
for name in model_specs:
    har_common[name] = np.array([forecasts[name][har_idx_map[d]] for d in common_dates])

all_fc = {**har_common, 'GJR-GARCH': garch_common, 'A4f-VIX²': a4f_common}

# QLIKE / MSE / MAE
print("\n  === Metrics on RV proxy (HAR native) ===")
metrics_rv = {}
for name, fc in all_fc.items():
    metrics_rv[name] = {
        'QLIKE': qlike(rv_common, fc),
        'MSE': mse(rv_common, fc),
        'MAE': mae(rv_common, fc),
    }
    print(f"    {name:15s}: QLIKE={metrics_rv[name]['QLIKE']:.4f} | "
          f"MSE={metrics_rv[name]['MSE']:.3e} | MAE={metrics_rv[name]['MAE']:.3e}")

print("\n  === Metrics on r² proxy (Patton 2011 fair) ===")
metrics_r2 = {}
for name, fc in all_fc.items():
    metrics_r2[name] = {
        'QLIKE': qlike(r2_common, fc),
        'MSE': mse(r2_common, fc),
        'MAE': mae(r2_common, fc),
    }
    print(f"    {name:15s}: QLIKE={metrics_r2[name]['QLIKE']:.4f} | "
          f"MSE={metrics_r2[name]['MSE']:.3e} | MAE={metrics_r2[name]['MAE']:.3e}")

# Spearman rank correlation
print("\n  === Spearman Rank Correlation ===")
spearman = {}
for name, fc in all_fc.items():
    sr_rv, _ = stats.spearmanr(rv_common, fc)
    sr_r2, _ = stats.spearmanr(r2_common, fc)
    spearman[name] = {'rho_RV': float(sr_rv), 'rho_r2': float(sr_r2)}
    print(f"    {name:15s}: rho(RV)={sr_rv:+.3f} | rho(r²)={sr_r2:+.3f}")


# ═══════════════════════════════════════════════════════════════════════
# 7. DM TESTS (pairwise)
# ═══════════════════════════════════════════════════════════════════════

print("\n[7] Diebold-Mariano tests (Harvey |t|>3.0 threshold)...")

losses_rv = {name: qlike_losses(rv_common, fc) for name, fc in all_fc.items()}
losses_r2 = {name: qlike_losses(r2_common, fc) for name, fc in all_fc.items()}

dm_pairs = [
    ('HAR-SV', 'HAR-RV'),
    ('HAR-RV-SJ', 'HAR-RV'),
    ('HAR-RV-down', 'HAR-RV'),
    ('HAR-LL', 'HAR-RV'),
    ('HAR-SV', 'HAR-LL'),
    ('HAR-RV', 'A4f-VIX²'),
    ('HAR-SV', 'A4f-VIX²'),
    ('HAR-RV', 'GJR-GARCH'),
    ('A4f-VIX²', 'GJR-GARCH'),
]

dm_results = {}

print("\n  === DM on RV proxy (neg t = first better) ===")
for m1, m2 in dm_pairs:
    t_stat, p_val = dm_test(losses_rv[m1], losses_rv[m2])
    dm_results[f'{m1}_vs_{m2}_rv'] = {'t_stat': t_stat, 'p_value': p_val}
    sig = '***' if np.isfinite(t_stat) and abs(t_stat) > 3.0 else (
          '**' if np.isfinite(t_stat) and abs(t_stat) > 2.0 else (
          '*' if np.isfinite(t_stat) and abs(t_stat) > 1.65 else ''))
    print(f"    {m1:15s} vs {m2:15s}: t={t_stat:+.3f} {sig}")

print("\n  === DM on r² proxy ===")
for m1, m2 in dm_pairs:
    t_stat, p_val = dm_test(losses_r2[m1], losses_r2[m2])
    dm_results[f'{m1}_vs_{m2}_r2'] = {'t_stat': t_stat, 'p_value': p_val}
    sig = '***' if np.isfinite(t_stat) and abs(t_stat) > 3.0 else (
          '**' if np.isfinite(t_stat) and abs(t_stat) > 2.0 else (
          '*' if np.isfinite(t_stat) and abs(t_stat) > 1.65 else ''))
    print(f"    {m1:15s} vs {m2:15s}: t={t_stat:+.3f} {sig}")


# ═══════════════════════════════════════════════════════════════════════
# 8. BETA+ vs BETA- HYPOTHESIS TEST (H1)
# ═══════════════════════════════════════════════════════════════════════

print("\n[8] Testing H1: beta(RV-) > beta(RV+) [leverage in forecasting]...")

# Full-sample HAR-SV: y_t = a + b+ * RV+_{t-1} + b- * RV-_{t-1} + c * RV_w + d * RV_m
sv_coefs = full_sample_coefs['HAR-SV']
b_plus = sv_coefs.get('RV+_d')
b_minus = sv_coefs.get('RV-_d')

# Re-estimate with proper variance-covariance to test b- = b+
X_full, _ = _sv_features(n_total)
y_full = rv_values[1:n_total]
X1 = np.column_stack([np.ones(len(X_full)), X_full])
beta = np.linalg.lstsq(X1, y_full, rcond=None)[0]
resid = y_full - X1 @ beta
dof = max(len(y_full) - X1.shape[1], 1)
sigma2 = float(np.sum(resid ** 2) / dof)
try:
    cov = sigma2 * np.linalg.inv(X1.T @ X1)
    # Contrast: b- - b+ (columns 2 (RV-) and 1 (RV+) in X1 after intercept)
    # X_full columns: [RV+_d, RV-_d, RV_w, RV_m]
    # So in X1: 0=const, 1=RV+_d, 2=RV-_d, 3=RV_w, 4=RV_m
    c_vec = np.zeros(len(beta))
    c_vec[2] = 1.0   # RV-_d
    c_vec[1] = -1.0  # -RV+_d
    contrast = float(c_vec @ beta)
    se_contrast = float(np.sqrt(c_vec @ cov @ c_vec))
    t_contrast = contrast / se_contrast if se_contrast > 0 else float('nan')
    p_contrast = 2.0 * (1.0 - stats.t.cdf(abs(t_contrast), df=dof))
except np.linalg.LinAlgError:
    contrast = float('nan')
    se_contrast = float('nan')
    t_contrast = float('nan')
    p_contrast = float('nan')

h1_test = {
    'beta_plus': float(b_plus) if b_plus is not None else None,
    'beta_minus': float(b_minus) if b_minus is not None else None,
    'diff_minus_minus_plus': contrast,
    'se': se_contrast,
    't_stat': t_contrast,
    'p_value': p_contrast,
    'reject_symmetric_at_5pct': bool(np.isfinite(p_contrast) and p_contrast < 0.05),
}
print(f"  beta+ = {b_plus:+.4f}, beta- = {b_minus:+.4f}")
print(f"  Contrast (beta- - beta+) = {contrast:+.4f}, SE={se_contrast:.4f}, "
      f"t={t_contrast:+.3f}, p={p_contrast:.3f}")
print(f"  H1 (beta- > beta+): "
      f"{'SUPPORTED' if t_contrast > 3.0 else ('marginal' if t_contrast > 1.65 else 'NOT supported')}")


# ═══════════════════════════════════════════════════════════════════════
# 9. RANKING + RESULTS COMPILATION
# ═══════════════════════════════════════════════════════════════════════

print("\n[9] Compiling results...")

rank_rv = sorted(metrics_rv.items(), key=lambda kv: kv[1]['QLIKE'])
rank_r2 = sorted(metrics_r2.items(), key=lambda kv: kv[1]['QLIKE'])

print("\n  Ranking by QLIKE on RV:")
for i, (name, met) in enumerate(rank_rv):
    print(f"    {i + 1}. {name:15s}: {met['QLIKE']:.4f}")

print("  Ranking by QLIKE on r²:")
for i, (name, met) in enumerate(rank_r2):
    print(f"    {i + 1}. {name:15s}: {met['QLIKE']:.4f}")

rv_names = [x[0] for x in rank_rv]
r2_names = [x[0] for x in rank_r2]
print(f"  Ranking consistent across proxies: {rv_names == r2_names}")

results = {
    'experiment_id': 'K1063',
    'title': 'Realized Semi-Variance Decomposition (Upside vs Downside)',
    'status': 'PRELIMINARY',
    'caveat': f'Only {len(common_dates)} common OOS days (<< 252). Results indicative.',
    'seed': 42,
    'data': {
        'source_5min': 'data/intraday/SPY_5min_YYYY-MM-DD.csv (60 files)',
        'source_daily': 'yfinance (SPY, ^VIX)',
        'date_start': str(df_rv.index[0].date()),
        'date_end': str(df_rv.index[-1].date()),
        'n_days': int(len(df_rv)),
        'n_oos_har': int(n_oos),
        'n_oos_common': int(len(common_dates)),
    },
    'decomposition': desc_stats,
    'full_sample_coefs': full_sample_coefs,
    'h1_beta_asymmetry': h1_test,
    'metrics_rv_proxy': metrics_rv,
    'metrics_r2_proxy': metrics_r2,
    'spearman': spearman,
    'dm_tests': dm_results,
    'ranking': {
        'by_QLIKE_RV': rv_names,
        'by_QLIKE_r2': r2_names,
        'consistent': bool(rv_names == r2_names),
    },
    'common_dates': [str(d.date()) for d in common_dates],
    'oos_series': {
        'dates': [str(d.date()) for d in common_dates],
        'rv_actual': rv_common.tolist(),
        'r2_actual': r2_common.tolist(),
        **{name: fc.tolist() for name, fc in all_fc.items()},
    },
    'generated_at': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Barndorff-Nielsen, Kinnebrock & Shephard (2010). Measuring downside risk-realised semivariance.',
        'Patton & Sheppard (2015). Good volatility, bad volatility. REStat 97(3).',
        'Corsi (2009). A simple approximate long-memory model of realized volatility. JFEC 7(2).',
        'Patton (2011). Volatility forecast comparison using imperfect volatility proxies. JoE.',
    ],
}

results_path = os.path.join(OUTPUT_DIR, 'k1063_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Results saved to: {results_path}")


# ═══════════════════════════════════════════════════════════════════════
# 10. PLOTS
# ═══════════════════════════════════════════════════════════════════════

print("\n[10] Generating plots...")

# Plot 1: RV, RV+, RV- time series
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
ax = axes[0]
ax.plot(df_rv.index, df_rv['rv'], color='#222', lw=1.5, label='RV (total)')
ax.plot(df_rv.index, df_rv['rv_pos'], color='#2ca02c', lw=1.1, label='RV+ (upside)')
ax.plot(df_rv.index, df_rv['rv_neg'], color='#d62728', lw=1.1, label='RV- (downside)')
ax.set_ylabel('Variance')
ax.set_title('K1063: Realized Semi-Variance Decomposition (SPY 5-min, 60 days)')
ax.legend(loc='upper left', framealpha=0.9)
ax.grid(alpha=0.3)

ax = axes[1]
ax.plot(df_rv.index, df_rv['sj'], color='#1f77b4', lw=1.2, label='Signed Jump SJ = RV+ - RV-')
ax.axhline(0, color='k', lw=0.5, linestyle='--')
ax.fill_between(df_rv.index, df_rv['sj'], 0,
                where=(df_rv['sj'] >= 0), color='#2ca02c', alpha=0.25, label='SJ>0 (net good)')
ax.fill_between(df_rv.index, df_rv['sj'], 0,
                where=(df_rv['sj'] < 0), color='#d62728', alpha=0.25, label='SJ<0 (net bad)')
ax.set_ylabel('Signed Jump')
ax.set_xlabel('Date')
ax.legend(loc='upper left', framealpha=0.9)
ax.grid(alpha=0.3)
plt.tight_layout()
p1 = os.path.join(OUTPUT_DIR, 'k1063_semi_variance_ts.png')
plt.savefig(p1, dpi=110, bbox_inches='tight')
plt.close()
print(f"  Saved {p1}")

# Plot 2: Asymmetry diagnostics
fig = plt.figure(figsize=(11, 9))
gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.35, wspace=0.3)

# (a) RV+ vs RV- scatter with y=x line
ax = fig.add_subplot(gs[0, 0])
ax.scatter(df_rv['rv_pos'], df_rv['rv_neg'], s=22, alpha=0.75, color='#1f77b4')
lim = max(df_rv['rv_pos'].max(), df_rv['rv_neg'].max()) * 1.05
ax.plot([0, lim], [0, lim], 'k--', lw=0.8, label='y = x (symmetric)')
ax.set_xlabel('RV+ (upside)')
ax.set_ylabel('RV- (downside)')
ax.set_title(f'Symmetry check\npaired t={t_sym:+.3f}, p={p_sym:.3f}')
ax.legend(loc='upper left')
ax.grid(alpha=0.3)

# (b) Histogram of SJ
ax = fig.add_subplot(gs[0, 1])
ax.hist(df_rv['sj'], bins=20, color='#1f77b4', alpha=0.75, edgecolor='k', linewidth=0.3)
ax.axvline(0, color='k', lw=0.8, linestyle='--')
ax.axvline(df_rv['sj'].mean(), color='#d62728', lw=1.2, linestyle='-',
           label=f'mean={df_rv["sj"].mean():+.2e}')
ax.set_xlabel('Signed Jump SJ = RV+ - RV-')
ax.set_ylabel('Frequency')
ax.set_title('Distribution of signed jump')
ax.legend()
ax.grid(alpha=0.3)

# (c) ACF bars for RV/RV+/RV-/SJ at lags 1, 5, 22
ax = fig.add_subplot(gs[1, 0])
lags = [1, 5, 22]
labels = ['RV', 'RV+', 'RV-', 'SJ']
colors = ['#222', '#2ca02c', '#d62728', '#1f77b4']
x = np.arange(len(lags))
width = 0.2
for i, nm in enumerate(labels):
    key = nm.lower().replace('+', '_pos').replace('-', '_neg') if nm != 'SJ' else 'sj'
    vals = [acf_table[key][f'lag{k}'] for k in lags]
    ax.bar(x + i * width - 1.5 * width, vals, width, label=nm, color=colors[i], alpha=0.85)
ax.set_xticks(x)
ax.set_xticklabels([f'lag {k}' for k in lags])
ax.axhline(0, color='k', lw=0.5)
ax.set_ylabel('Autocorrelation')
ax.set_title('ACF of variance components')
ax.legend(ncol=2, fontsize=9)
ax.grid(alpha=0.3)

# (d) Leverage diagnostic: r_t vs (RV- - RV+)_{t+1}
ax = fig.add_subplot(gs[1, 1])
fut_diff = (future_rv_neg - future_rv_pos).reindex(daily_ret_aligned.index).dropna()
x_lev = daily_ret_aligned.reindex(fut_diff.index).values
y_lev = fut_diff.values
ax.scatter(x_lev, y_lev, s=22, alpha=0.75, color='#8c564b')
ax.axhline(0, color='k', lw=0.5, linestyle='--')
ax.axvline(0, color='k', lw=0.5, linestyle='--')
# Fit line
if len(x_lev) > 5:
    coef = np.polyfit(x_lev, y_lev, 1)
    xs = np.linspace(x_lev.min(), x_lev.max(), 50)
    ax.plot(xs, np.polyval(coef, xs), '--', color='#d62728', lw=1.2,
            label=f'slope={coef[0]:+.3e}')
ax.set_xlabel('daily return r_t')
ax.set_ylabel('(RV- - RV+)_{t+1}')
ax.set_title(f'Leverage: corr={leverage_corr:+.3f}')
ax.legend()
ax.grid(alpha=0.3)

plt.suptitle('K1063: Upside vs Downside Asymmetry Diagnostics', fontsize=12)
p2 = os.path.join(OUTPUT_DIR, 'k1063_leverage_asymmetry.png')
plt.savefig(p2, dpi=110, bbox_inches='tight')
plt.close()
print(f"  Saved {p2}")

# Plot 3: Model comparison (QLIKE bars on both proxies + OOS forecast overlay)
fig = plt.figure(figsize=(12, 9))
gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.3)

ax = fig.add_subplot(gs[0, 0])
names_ord = [nm for nm, _ in rank_rv]
qvals_rv = [metrics_rv[nm]['QLIKE'] for nm in names_ord]
colors_rv = ['#1f77b4' if nm.startswith('HAR-SV') or nm.startswith('HAR-LL') or nm.startswith('HAR-RV-SJ')
             else ('#888' if nm == 'HAR-RV'
                   else ('#2ca02c' if nm == 'HAR-RV-down'
                         else '#ff7f0e')) for nm in names_ord]
bars = ax.barh(range(len(names_ord)), qvals_rv, color=colors_rv, alpha=0.9, edgecolor='k', linewidth=0.4)
ax.set_yticks(range(len(names_ord)))
ax.set_yticklabels(names_ord)
ax.invert_yaxis()
ax.set_xlabel('QLIKE (lower is better)')
ax.set_title('QLIKE on RV proxy (HAR native)')
for bar, v in zip(bars, qvals_rv):
    ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f' {v:.3f}',
            va='center', fontsize=9)
ax.grid(alpha=0.3, axis='x')

ax = fig.add_subplot(gs[0, 1])
names_ord2 = [nm for nm, _ in rank_r2]
qvals_r2 = [metrics_r2[nm]['QLIKE'] for nm in names_ord2]
colors_r2 = ['#1f77b4' if nm.startswith('HAR-SV') or nm.startswith('HAR-LL') or nm.startswith('HAR-RV-SJ')
             else ('#888' if nm == 'HAR-RV'
                   else ('#2ca02c' if nm == 'HAR-RV-down'
                         else '#ff7f0e')) for nm in names_ord2]
bars = ax.barh(range(len(names_ord2)), qvals_r2, color=colors_r2, alpha=0.9, edgecolor='k', linewidth=0.4)
ax.set_yticks(range(len(names_ord2)))
ax.set_yticklabels(names_ord2)
ax.invert_yaxis()
ax.set_xlabel('QLIKE (lower is better)')
ax.set_title('QLIKE on r² proxy (Patton 2011 fair)')
for bar, v in zip(bars, qvals_r2):
    ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, f' {v:.3f}',
            va='center', fontsize=9)
ax.grid(alpha=0.3, axis='x')

# Time series overlay: top 3 models vs RV actual
ax = fig.add_subplot(gs[1, :])
ax.plot(common_dates, rv_common, color='k', lw=1.5, label='RV actual')
top3 = names_ord[:3]
palette = ['#1f77b4', '#2ca02c', '#d62728']
for i, nm in enumerate(top3):
    ax.plot(common_dates, all_fc[nm], lw=1.1, color=palette[i], alpha=0.8,
            label=f'{nm} (QLIKE={metrics_rv[nm]["QLIKE"]:.3f})')
ax.set_title(f'Top-3 forecasts vs RV actual (OOS, n={len(common_dates)})')
ax.set_ylabel('Variance')
ax.set_xlabel('Date')
ax.legend(loc='upper left', fontsize=9)
ax.grid(alpha=0.3)

plt.suptitle('K1063: HAR variants + GJR-GARCH + A4f-VIX² comparison', fontsize=12)
p3 = os.path.join(OUTPUT_DIR, 'k1063_model_comparison.png')
plt.savefig(p3, dpi=110, bbox_inches='tight')
plt.close()
print(f"  Saved {p3}")


print("\n" + "=" * 72)
print("K1063 DONE.")
print(f"  N days processed: {len(df_rv)}")
print(f"  OOS common days: {len(common_dates)}")
print(f"  Best QLIKE(RV): {names_ord[0]} = {metrics_rv[names_ord[0]]['QLIKE']:.4f}")
print(f"  Best QLIKE(r²): {names_ord2[0]} = {metrics_r2[names_ord2[0]]['QLIKE']:.4f}")
print(f"  H1 (beta- > beta+): t={t_contrast:+.3f}, p={p_contrast:.3f}")
print(f"  Leverage corr(r_t, (RV- - RV+)_{{t+1}}) = {leverage_corr:+.3f}")
print("=" * 72)
