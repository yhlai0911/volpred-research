#!/usr/bin/env python3
"""
K1084: Realized Skewness and Kurtosis — Higher-Order Moments for Volatility Prediction

Extends K1063 (semi-variance decomposition) by examining whether higher-order
realized moments (Realized Skewness RSk, Realized Kurtosis RKt, Signed Jump)
carry incremental predictive power for daily RV beyond the HAR baseline.

Research Questions:
1. H1: Does RSk have incremental predictive power for next-day RV (controlling
   for HAR-RV)?
2. H2: Does RKt predict tail risk (VaR violations)?
3. H3: Does adding RSk/RKt to a HAR extension improve QLIKE vs plain HAR-RV?
4. H4: Are higher-moment effects regime-dependent (Low vs High VIX)?

Data:
- 5-min SPY data: data/intraday/SPY_5min_YYYY-MM-DD.csv (60 files,
  2026-01-14 ~ 2026-04-10)
- Daily SPY/VIX: yfinance (for regime split, leverage diagnostics, VaR target)

Definitions (ACJV 2015, BNKS 2010):
- RV_t  = Σ r_i^2
- RSk_t = sqrt(N) * Σ r_i^3 / RV_t^{1.5}           (standardised)
- RKt_t = N * Σ r_i^4 / RV_t^2                      (standardised)
- SJ_t  = RV+_t - RV-_t                             (signed jump component)

Status: PRELIMINARY (60-day 5-min sample, same as K1057/K1063/K1065)
Random seed: 42

References:
- Amaya, Christoffersen, Jacobs & Vasquez (2015). "Does realized skewness
  predict the cross-section of equity returns?" Journal of Financial
  Economics 118(1), 135-167.
- Barndorff-Nielsen, Kinnebrock & Shephard (2010). "Measuring downside
  risk-realised semivariance." Festschrift for R. Engle.
- Neuberger (2012). "Realized skewness." Review of Financial Studies 25(11).
- Corsi (2009). "A simple approximate long-memory model of realized
  volatility." Journal of Financial Econometrics 7(2).
- Patton (2011). "Volatility forecast comparison using imperfect volatility
  proxies." Journal of Econometrics.
- Harvey (2016). "... and the cross-section of expected returns." RFS 29(1).

Prior: K1057 (jumps NULL), K1063 (semi-variance PASS), K1065 (overnight/intraday).
"""

import json
import os
import sys
import warnings
from datetime import datetime, timezone
from glob import glob

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
print("K1084: Realized Skewness and Kurtosis (Higher-Moment Predictability)")
print("=" * 72)


# ═══════════════════════════════════════════════════════════════════════
# 1. LOAD 5-MIN DATA — COMPUTE RV, RSk, RKt, SJ
# ═══════════════════════════════════════════════════════════════════════

print("\n[1] Loading 5-min data and computing higher-order realized moments...")

fivemin_files = sorted(glob(os.path.join(DATA_DIR, 'SPY_5min_*.csv')))
print(f"  Found {len(fivemin_files)} 5-min CSV files")


def compute_realized_moments(filepath):
    """Compute realized second, third, fourth moments from 5-min data.

    Standardisation follows Amaya, Christoffersen, Jacobs & Vasquez (2015):
      RV   = Σ r_i^2
      RSk  = sqrt(N) * Σ r_i^3 / RV^{1.5}
      RKt  = N * Σ r_i^4 / RV^2
    These have asymptotic mean 0 / 3 under Brownian semi-martingale null.

    Also compute RV+, RV-, SJ (BNKS 2010 / PS 2015) for comparability with K1063.
    """
    df = pd.read_csv(filepath, header=[0, 1], index_col=0, parse_dates=True)

    close = df[('Close', 'SPY')].dropna()
    if len(close) < 5:
        return None

    returns = close.pct_change().dropna()
    n = len(returns)
    if n < 5:
        return None

    r = returns.values
    r2 = r ** 2
    r3 = r ** 3
    r4 = r ** 4

    rv = float(np.sum(r2))
    if rv <= 0:
        return None

    # Standardised realized skewness and kurtosis (ACJV 2015)
    rsk = float(np.sqrt(n) * np.sum(r3) / (rv ** 1.5))
    rkt = float(n * np.sum(r4) / (rv ** 2))

    # Unstandardised raw third/fourth moments (for diagnostics)
    raw_m3 = float(np.sum(r3))
    raw_m4 = float(np.sum(r4))

    # Semi-variance decomposition (K1063-compatible)
    pos_mask = r > 0
    neg_mask = r < 0
    rv_pos = float(np.sum(r2[pos_mask]))
    rv_neg = float(np.sum(r2[neg_mask]))
    sj = rv_pos - rv_neg

    # Daily open/close direction proxy
    open_price = float(close.iloc[0])
    close_price = float(close.iloc[-1])
    day_ret = (close_price / open_price - 1.0) if open_price > 0 else 0.0

    return {
        'rv': rv,
        'rsk': rsk,
        'rkt': rkt,
        'raw_m3': raw_m3,
        'raw_m4': raw_m4,
        'rv_pos': rv_pos,
        'rv_neg': rv_neg,
        'sj': sj,
        'n_bars': int(n),
        'day_ret': day_ret,
    }


daily_data = {}
for fpath in fivemin_files:
    date_str = os.path.basename(fpath).replace('SPY_5min_', '').replace('.csv', '')
    out = compute_realized_moments(fpath)
    if out is not None:
        daily_data[date_str] = out

print(f"  Successfully processed: {len(daily_data)} days")

dates = sorted(daily_data.keys())
df_rm = pd.DataFrame([daily_data[d] for d in dates], index=pd.to_datetime(dates))
df_rm.index.name = 'Date'

# Winsorise RSk and RKt at 1% / 99% for robustness diagnostic copies
q_low_sk, q_high_sk = df_rm['rsk'].quantile([0.01, 0.99])
q_low_kt, q_high_kt = df_rm['rkt'].quantile([0.01, 0.99])
df_rm['rsk_wins'] = df_rm['rsk'].clip(q_low_sk, q_high_sk)
df_rm['rkt_wins'] = df_rm['rkt'].clip(q_low_kt, q_high_kt)

print(f"  Date range: {df_rm.index[0].date()} to {df_rm.index[-1].date()}")
print(f"  N bars per day: mean={df_rm['n_bars'].mean():.1f}, "
      f"min={df_rm['n_bars'].min()}, max={df_rm['n_bars'].max()}")
print(f"  RV    mean: {df_rm['rv'].mean():.6e}")
print(f"  RSk   mean: {df_rm['rsk'].mean():+.4f}   (BM null: 0)")
print(f"  RKt   mean: {df_rm['rkt'].mean():+.4f}   (BM null: 3)")
print(f"  SJ    mean: {df_rm['sj'].mean():+.4e}")


# ═══════════════════════════════════════════════════════════════════════
# 2. DAILY SPY / VIX — REGIME + LEVERAGE DIAGNOSTICS
# ═══════════════════════════════════════════════════════════════════════

print("\n[2] Loading daily SPY/VIX data...")

try:
    import yfinance as yf
    spy_data = yf.download('SPY', start='2016-01-01', end='2026-04-12', progress=False)
    vix_data = yf.download('^VIX', start='2016-01-01', end='2026-04-12', progress=False)

    if isinstance(spy_data.columns, pd.MultiIndex):
        spy_close = spy_data[('Close', 'SPY')].squeeze()
    else:
        spy_close = spy_data['Close'].squeeze()

    if isinstance(vix_data.columns, pd.MultiIndex):
        vix_close = vix_data[('Close', '^VIX')].squeeze()
    else:
        vix_close = vix_data['Close'].squeeze()

    daily_ret = spy_close.pct_change().dropna()

    print(f"  Daily SPY: {len(daily_ret)} returns, VIX: {len(vix_close)} obs")
except Exception as e:
    print(f"  ERROR loading yfinance data: {e}")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════
# 3. DESCRIPTIVE + DIAGNOSTIC STATS
# ═══════════════════════════════════════════════════════════════════════

print("\n[3] Descriptive statistics for higher moments...")


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
for name, series in [('rv', df_rm['rv']), ('rsk', df_rm['rsk']),
                     ('rkt', df_rm['rkt']), ('sj', df_rm['sj']),
                     ('abs_rsk', df_rm['rsk'].abs())]:
    vals = series.values
    acf_table[name] = {
        'lag1': acf_k(vals, 1),
        'lag5': acf_k(vals, 5),
        'lag22': acf_k(vals, 22),
    }
    print(f"  ACF {name:10s}: lag1={acf_table[name]['lag1']:+.3f} | "
          f"lag5={acf_table[name]['lag5']:+.3f} | lag22={acf_table[name]['lag22']:+.3f}")

# BM null tests
rsk_vals = df_rm['rsk'].values
rkt_vals = df_rm['rkt'].values

t_sk_null, p_sk_null = stats.ttest_1samp(rsk_vals, 0.0)
t_kt_null, p_kt_null = stats.ttest_1samp(rkt_vals, 3.0)

print(f"\n  BM null test:")
print(f"    mean(RSk) = {rsk_vals.mean():+.4f}, t(null=0) = {t_sk_null:+.3f}, p={p_sk_null:.3f}")
print(f"    mean(RKt) = {rkt_vals.mean():+.4f}, t(null=3) = {t_kt_null:+.3f}, p={p_kt_null:.3f}")

# Pairwise correlations
corr_rv_rsk = float(np.corrcoef(df_rm['rv'].values, df_rm['rsk'].values)[0, 1])
corr_rv_rkt = float(np.corrcoef(df_rm['rv'].values, df_rm['rkt'].values)[0, 1])
corr_rv_abs_rsk = float(np.corrcoef(df_rm['rv'].values, df_rm['rsk'].abs().values)[0, 1])
corr_rsk_rkt = float(np.corrcoef(df_rm['rsk'].values, df_rm['rkt'].values)[0, 1])

print(f"\n  Cross-section correlations:")
print(f"    corr(RV,   RSk)     = {corr_rv_rsk:+.3f}")
print(f"    corr(RV,   |RSk|)   = {corr_rv_abs_rsk:+.3f}")
print(f"    corr(RV,   RKt)     = {corr_rv_rkt:+.3f}")
print(f"    corr(RSk,  RKt)     = {corr_rsk_rkt:+.3f}")

# Leverage diagnostic: corr(r_t, RSk_{t+1})
daily_ret_aligned = daily_ret.reindex(df_rm.index).dropna()
future_rsk = df_rm['rsk'].shift(-1).reindex(daily_ret_aligned.index).dropna()
lev_r_rsk = float(daily_ret_aligned.reindex(future_rsk.index).corr(future_rsk))
future_rkt = df_rm['rkt'].shift(-1).reindex(daily_ret_aligned.index).dropna()
lev_r_rkt = float(daily_ret_aligned.reindex(future_rkt.index).corr(future_rkt))
print(f"  Leverage:")
print(f"    corr(r_t, RSk_{{t+1}}) = {lev_r_rsk:+.3f} (negative expected — leverage)")
print(f"    corr(r_t, RKt_{{t+1}}) = {lev_r_rkt:+.3f}")

desc_stats = {
    'n_days': int(len(df_rm)),
    'date_start': str(df_rm.index[0].date()),
    'date_end': str(df_rm.index[-1].date()),
    'n_bars': {
        'mean': float(df_rm['n_bars'].mean()),
        'min': int(df_rm['n_bars'].min()),
        'max': int(df_rm['n_bars'].max()),
    },
    'rv': {
        'mean': float(df_rm['rv'].mean()),
        'std': float(df_rm['rv'].std()),
        'skew': float(df_rm['rv'].skew()),
        'kurtosis': float(df_rm['rv'].kurtosis()),
    },
    'rsk': {
        'mean': float(rsk_vals.mean()),
        'std': float(rsk_vals.std()),
        'min': float(rsk_vals.min()),
        'max': float(rsk_vals.max()),
        'pct_negative': float((rsk_vals < 0).mean()),
        'p01': float(q_low_sk),
        'p99': float(q_high_sk),
        't_null_zero': float(t_sk_null),
        'p_null_zero': float(p_sk_null),
    },
    'rkt': {
        'mean': float(rkt_vals.mean()),
        'std': float(rkt_vals.std()),
        'min': float(rkt_vals.min()),
        'max': float(rkt_vals.max()),
        'pct_above_bm_null_3': float((rkt_vals > 3.0).mean()),
        'p01': float(q_low_kt),
        'p99': float(q_high_kt),
        't_null_bm3': float(t_kt_null),
        'p_null_bm3': float(p_kt_null),
    },
    'acf': acf_table,
    'correlations': {
        'rv_rsk': corr_rv_rsk,
        'rv_abs_rsk': corr_rv_abs_rsk,
        'rv_rkt': corr_rv_rkt,
        'rsk_rkt': corr_rsk_rkt,
    },
    'leverage': {
        'r_t_vs_rsk_tp1': lev_r_rsk,
        'r_t_vs_rkt_tp1': lev_r_rkt,
    },
}


# ═══════════════════════════════════════════════════════════════════════
# 4. HAR VARIANTS — EXPANDING-WINDOW OLS OOS FORECASTS
# ═══════════════════════════════════════════════════════════════════════

print("\n[4] Fitting HAR variants (expanding-window OLS)...")


def make_har_features(series, prefix):
    d = pd.DataFrame({f'{prefix}_d': series})
    d[f'{prefix}_w'] = series.rolling(5, min_periods=1).mean()
    d[f'{prefix}_m'] = series.rolling(22, min_periods=1).mean()
    return d


feat_rv = make_har_features(df_rm['rv'], 'rv')

rv_values = df_rm['rv'].values
rsk_values = df_rm['rsk'].values  # raw (not winsorised) — robustness below if needed
rkt_values = df_rm['rkt'].values
sj_values = df_rm['sj'].values

INIT_WINDOW = 30
n_total = len(df_rm)
oos_start_idx = INIT_WINDOW
if oos_start_idx >= n_total - 2:
    print("  ERROR: Not enough data for OOS forecasting!")
    sys.exit(1)
n_oos = n_total - oos_start_idx
print(f"  Training window: expanding from {INIT_WINDOW} days")
print(f"  OOS period: {n_oos} days "
      f"({df_rm.index[oos_start_idx].date()} to {df_rm.index[-1].date()})")


def ols_forecast(X_train, y_train, x_test, fallback):
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


def _rv_features(t):
    """HAR-RV baseline."""
    X = feat_rv[['rv_d', 'rv_w', 'rv_m']].values[:t - 1]
    x = feat_rv[['rv_d', 'rv_w', 'rv_m']].values[t - 1]
    return X, x


def _rv_sk_features(t):
    """HAR + RSk_{t-1}."""
    X = np.column_stack([
        feat_rv[['rv_d', 'rv_w', 'rv_m']].values[:t - 1],
        rsk_values[:t - 1],
    ])
    x = np.concatenate([
        feat_rv[['rv_d', 'rv_w', 'rv_m']].values[t - 1],
        [rsk_values[t - 1]],
    ])
    return X, x


def _rv_kt_features(t):
    """HAR + RKt_{t-1}."""
    X = np.column_stack([
        feat_rv[['rv_d', 'rv_w', 'rv_m']].values[:t - 1],
        rkt_values[:t - 1],
    ])
    x = np.concatenate([
        feat_rv[['rv_d', 'rv_w', 'rv_m']].values[t - 1],
        [rkt_values[t - 1]],
    ])
    return X, x


def _rv_sj_features(t):
    """HAR + SJ_{t-1}."""
    X = np.column_stack([
        feat_rv[['rv_d', 'rv_w', 'rv_m']].values[:t - 1],
        sj_values[:t - 1],
    ])
    x = np.concatenate([
        feat_rv[['rv_d', 'rv_w', 'rv_m']].values[t - 1],
        [sj_values[t - 1]],
    ])
    return X, x


def _rv_full_features(t):
    """HAR + RSk + RKt + SJ."""
    X = np.column_stack([
        feat_rv[['rv_d', 'rv_w', 'rv_m']].values[:t - 1],
        rsk_values[:t - 1],
        rkt_values[:t - 1],
        sj_values[:t - 1],
    ])
    x = np.concatenate([
        feat_rv[['rv_d', 'rv_w', 'rv_m']].values[t - 1],
        [rsk_values[t - 1], rkt_values[t - 1], sj_values[t - 1]],
    ])
    return X, x


model_specs = {
    'HAR-RV':      (_rv_features,       ['RV_d', 'RV_w', 'RV_m']),
    'HAR-RSk':     (_rv_sk_features,    ['RV_d', 'RV_w', 'RV_m', 'RSk_d']),
    'HAR-RKt':     (_rv_kt_features,    ['RV_d', 'RV_w', 'RV_m', 'RKt_d']),
    'HAR-SJ':      (_rv_sj_features,    ['RV_d', 'RV_w', 'RV_m', 'SJ_d']),
    'HAR-Full':    (_rv_full_features,  ['RV_d', 'RV_w', 'RV_m', 'RSk_d', 'RKt_d', 'SJ_d']),
}

forecasts = {name: np.full(n_oos, np.nan) for name in model_specs}
fallback_mean = float(np.mean(rv_values[:INIT_WINDOW]))

for i in range(n_oos):
    t = oos_start_idx + i
    y_train = rv_values[1:t]

    for name, (feat_fn, _) in model_specs.items():
        X_train, x_test = feat_fn(t)
        fc, _ = ols_forecast(X_train, y_train, x_test, fallback_mean)
        forecasts[name][i] = fc

print("  HAR variants fitted.")
for name in model_specs:
    m = np.nanmean(forecasts[name])
    print(f"    {name:14s}: mean forecast = {m:.6e}")

# Full-sample OLS coefficient for interpretation (not used in OOS)
print("\n  Full-sample OLS coefficients (interpretation only):")
full_sample_coefs = {}
for name, (feat_fn, feat_names) in model_specs.items():
    X_full, _ = feat_fn(n_total)
    y_full = rv_values[1:n_total]
    X = np.column_stack([np.ones(len(X_full)), X_full])
    try:
        beta = np.linalg.lstsq(X, y_full, rcond=None)[0]
        resid = y_full - X @ beta
        dof = max(len(y_full) - X.shape[1], 1)
        sigma2 = np.sum(resid ** 2) / dof
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

    coefs = {
        'intercept': float(beta[0]) if beta is not None else None,
        'intercept_t': float(t_stats[0]) if t_stats is not None else None,
    }
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
        print(f"      {k:12s} = {v:+.4e} {tstr}")


# ═══════════════════════════════════════════════════════════════════════
# 5. GARCH + A4f-VIX² BENCHMARKS
# ═══════════════════════════════════════════════════════════════════════

print("\n[5] Fitting GJR-GARCH and A4f-VIX² benchmarks...")

oos_dates = df_rm.index[oos_start_idx:]

garch_forecasts = {}
try:
    from arch import arch_model
    for d in oos_dates:
        if d not in daily_ret.index:
            continue
        d_loc = daily_ret.index.get_loc(d)
        if d_loc < 2000:
            continue
        train_ret = daily_ret.iloc[d_loc - 2000:d_loc] * 100.0
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
# 6. EVALUATION — QLIKE + DM TEST
# ═══════════════════════════════════════════════════════════════════════

print("\n[6] Evaluation (QLIKE, DM test, Harvey |t|>3.0)...")


def qlike(actual, predicted):
    a = np.asarray(actual, dtype=float)
    p = np.maximum(np.asarray(predicted, dtype=float), 1e-12)
    return float(np.nanmean(a / p + np.log(p)))


def qlike_losses(actual, predicted):
    a = np.asarray(actual, dtype=float)
    p = np.maximum(np.asarray(predicted, dtype=float), 1e-12)
    return a / p + np.log(p)


def mse(actual, predicted):
    a = np.asarray(actual, dtype=float)
    p = np.asarray(predicted, dtype=float)
    return float(np.nanmean((a - p) ** 2))


def dm_test(loss1, loss2):
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


# Actual target: RV_{t+1}, i.e. rv_values shifted one forward
actual_rv_oos = rv_values[oos_start_idx + 1:n_total]  # next-day RV for each OOS forecast
# forecasts are for index oos_start_idx..n_total-1 using info up to t-1
# We need to align: forecast[i] predicts rv_values[oos_start_idx + i]
# But to evaluate "next-day" we use rv at same index. The convention in the
# script is: forecast at step i uses features at t-1 to predict RV_t where
# t = oos_start_idx + i. So actual is rv_values[oos_start_idx:].
actual_rv_full = rv_values[oos_start_idx:n_total]

# Also r² actual (daily close-to-close squared return) for comparability
daily_r2 = (daily_ret.reindex(df_rm.index).fillna(0.0).values) ** 2
actual_r2_full = daily_r2[oos_start_idx:n_total]

# Per-model evaluation — RV target (native for HAR)
rv_eval = {}
qlike_loss_store = {}
for name, fc_arr in forecasts.items():
    fc_arr = np.asarray(fc_arr, dtype=float)
    mask = ~(np.isnan(fc_arr) | np.isnan(actual_rv_full))
    q = qlike(actual_rv_full[mask], fc_arr[mask])
    m = mse(actual_rv_full[mask], fc_arr[mask])
    rv_eval[name] = {'QLIKE': q, 'MSE': m, 'n': int(mask.sum())}
    qlike_loss_store[name] = qlike_losses(actual_rv_full, fc_arr)
    print(f"  {name:14s}: QLIKE={q:+.4f}  MSE={m:.3e}  n={mask.sum()}")

# External benchmarks on RV + r² targets
for label, ext_dict in [('GJR-GARCH', garch_forecasts), ('A4f-VIX2', a4f_forecasts)]:
    if not ext_dict:
        continue
    fc_arr = np.array([ext_dict.get(d, np.nan) for d in oos_dates])
    mask_rv = ~(np.isnan(fc_arr) | np.isnan(actual_rv_full))
    q_rv = qlike(actual_rv_full[mask_rv], fc_arr[mask_rv])
    mask_r2 = ~(np.isnan(fc_arr) | np.isnan(actual_r2_full))
    q_r2 = qlike(actual_r2_full[mask_r2], fc_arr[mask_r2])
    rv_eval[label] = {'QLIKE_RV': q_rv, 'QLIKE_r2': q_r2, 'n_rv': int(mask_rv.sum()),
                      'n_r2': int(mask_r2.sum())}
    qlike_loss_store[label] = qlike_losses(actual_rv_full, fc_arr)
    print(f"  {label:14s}: QLIKE(RV)={q_rv:+.4f}  QLIKE(r2)={q_r2:+.4f}")

# DM tests — pairwise HAR variants vs HAR-RV (baseline)
print("\n  DM tests vs HAR-RV (Harvey |t|>3.0 threshold):")
dm_results = {}
base_loss = qlike_loss_store['HAR-RV']
for name in ['HAR-RSk', 'HAR-RKt', 'HAR-SJ', 'HAR-Full']:
    alt_loss = qlike_loss_store[name]
    t_dm, p_dm = dm_test(alt_loss, base_loss)
    # Negative t_dm means alt_loss < base_loss, i.e. alt beats baseline.
    dm_results[f'{name}_vs_HAR-RV'] = {
        't_stat': t_dm, 'p_value': p_dm,
        'harvey_significant': bool(np.isfinite(t_dm) and abs(t_dm) > 3.0),
        'direction': 'alt_better' if np.isfinite(t_dm) and t_dm < 0 else 'base_better',
    }
    sig = 'HARVEY SIG' if abs(t_dm) > 3.0 else ('weak' if abs(t_dm) > 1.96 else 'ns')
    direction = 'alt<base (alt wins)' if t_dm < 0 else 'alt>base'
    print(f"    {name:10s} vs HAR-RV: t={t_dm:+.3f}  p={p_dm:.3f}  "
          f"[{sig}, {direction}]")


# ═══════════════════════════════════════════════════════════════════════
# 7. TAIL RISK — VaR USING RKt-ADJUSTED + NORMAL + STUDENT-T
# ═══════════════════════════════════════════════════════════════════════

print("\n[7] Tail risk (VaR) — RKt-adjusted vs Normal vs Student-t...")


def kupiec_lr(violations, n, alpha):
    """Kupiec (1995) unconditional coverage test."""
    x = int(violations)
    pi = alpha
    p_hat = x / n if n > 0 else 0.0
    if p_hat in (0.0, 1.0):
        lr = 0.0
    else:
        ll_null = x * np.log(pi) + (n - x) * np.log(1 - pi)
        ll_alt = x * np.log(p_hat) + (n - x) * np.log(1 - p_hat)
        lr = -2.0 * (ll_null - ll_alt)
    p_val = 1.0 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(p_val)


# VaR target: next-day daily return r_{t+1} (to match HAR RV horizon)
# Use raw RV_{t+1} estimate from HAR variants as σ² proxy
# Then apply Normal / Student-t / RKt-adjusted quantile
# r_t is the daily close-to-close return aligned with df_rm.index
daily_ret_oos = daily_ret.reindex(df_rm.index).values[oos_start_idx:n_total]
mask_r = ~np.isnan(daily_ret_oos)

# Use HAR-RV forecast as σ² point estimate
sigma2_fc = forecasts['HAR-RV']
sigma_fc = np.sqrt(np.maximum(sigma2_fc, 1e-12))

var_tests = {}
for alpha_str, alpha in [('5%', 0.05), ('1%', 0.01)]:
    # Normal
    z_n = stats.norm.ppf(alpha)
    var_normal = z_n * sigma_fc

    # Student-t (df=5 fixed — typical for financial returns; robustness)
    df_t = 5
    z_t = stats.t.ppf(alpha, df=df_t) * np.sqrt((df_t - 2) / df_t)
    var_student = z_t * sigma_fc

    # RKt-adjusted: use Cornish-Fisher expansion
    # q_CF = z + (z²-1)/6 * Sk + (z³-3z)/24 * (Kt-3) - (2z³-5z)/36 * Sk²
    # Use forecast RKt as the (t-1) value with expanding mean, RSk = 0 (sym)
    # Actually use prior RKt (lag 1) as predictor of t+1 kurtosis
    rkt_lag = np.concatenate([[float('nan')], rkt_values[:-1]])[oos_start_idx:n_total]
    rsk_lag = np.concatenate([[float('nan')], rsk_values[:-1]])[oos_start_idx:n_total]

    # Winsorise lag inputs to avoid extreme CF corrections
    rkt_lag_w = np.clip(rkt_lag, q_low_kt, q_high_kt)
    rsk_lag_w = np.clip(rsk_lag, q_low_sk, q_high_sk)

    # Cornish-Fisher
    z = z_n
    excess_kt = rkt_lag_w - 3.0
    cf_quantile = (z
                   + (z ** 2 - 1) / 6.0 * rsk_lag_w
                   + (z ** 3 - 3 * z) / 24.0 * excess_kt
                   - (2 * z ** 3 - 5 * z) / 36.0 * rsk_lag_w ** 2)
    var_cf = cf_quantile * sigma_fc

    results_alpha = {}
    for label, var_fc in [('Normal', var_normal), ('Student-t_df5', var_student),
                          ('Cornish-Fisher', var_cf)]:
        mm = mask_r & ~np.isnan(var_fc)
        n_eval = int(mm.sum())
        if n_eval == 0:
            continue
        violations = int(np.sum(daily_ret_oos[mm] < var_fc[mm]))
        viol_rate = violations / n_eval
        lr, p_lr = kupiec_lr(violations, n_eval, alpha)
        results_alpha[label] = {
            'n': n_eval,
            'violations': violations,
            'viol_rate': float(viol_rate),
            'target_rate': float(alpha),
            'kupiec_LR': lr,
            'kupiec_p': p_lr,
            'pass_kupiec': bool(p_lr > 0.05),
        }
        print(f"  {alpha_str} {label:15s}: viol={violations}/{n_eval} "
              f"({viol_rate*100:.1f}% vs target {alpha*100:.0f}%) "
              f"Kupiec p={p_lr:.3f}")

    var_tests[alpha_str] = results_alpha


# ═══════════════════════════════════════════════════════════════════════
# 8. REGIME ANALYSIS — LOW / HIGH VIX
# ═══════════════════════════════════════════════════════════════════════

print("\n[8] Regime analysis (Low / High VIX split at sample median)...")

# Align VIX
vix_aligned = vix_close.reindex(df_rm.index).ffill()
vix_oos = vix_aligned.values[oos_start_idx:n_total]
vix_median_oos = float(np.nanmedian(vix_oos))

low_mask = vix_oos <= vix_median_oos
high_mask = vix_oos > vix_median_oos

print(f"  VIX median (OOS): {vix_median_oos:.2f}")
print(f"  Low-VIX n={low_mask.sum()}, High-VIX n={high_mask.sum()}")

regime_results = {}
for regime_label, regime_mask in [('Low', low_mask), ('High', high_mask)]:
    regime_eval = {}
    for name in ['HAR-RV', 'HAR-RSk', 'HAR-RKt', 'HAR-Full']:
        fc_arr = forecasts[name]
        mm = regime_mask & ~np.isnan(fc_arr) & ~np.isnan(actual_rv_full)
        if mm.sum() < 5:
            continue
        q = qlike(actual_rv_full[mm], fc_arr[mm])
        regime_eval[name] = {'QLIKE': q, 'n': int(mm.sum())}
        print(f"    {regime_label}-VIX {name:10s}: QLIKE={q:+.4f}  n={mm.sum()}")
    # DM regime: HAR-Full vs HAR-RV restricted to regime
    l_base = qlike_loss_store['HAR-RV'][regime_mask]
    l_full = qlike_loss_store['HAR-Full'][regime_mask]
    mm_both = ~np.isnan(l_base) & ~np.isnan(l_full)
    if mm_both.sum() >= 5:
        t_dm_r, p_dm_r = dm_test(l_full[mm_both], l_base[mm_both])
        regime_eval['DM_Full_vs_RV'] = {
            't_stat': t_dm_r, 'p_value': p_dm_r,
            'harvey_significant': bool(np.isfinite(t_dm_r) and abs(t_dm_r) > 3.0),
        }
    regime_results[regime_label] = regime_eval


# ═══════════════════════════════════════════════════════════════════════
# 9. CHARTS
# ═══════════════════════════════════════════════════════════════════════

print("\n[9] Generating charts...")

# 9.1 Moments time series
fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
axes[0].plot(df_rm.index, df_rm['rv'], color='#1f77b4', lw=1.3, label='RV')
axes[0].set_ylabel('RV')
axes[0].set_title('K1084 — Realized Moments Time Series (SPY 5-min)')
axes[0].legend(loc='upper right')
axes[0].grid(alpha=0.3)
axes[1].plot(df_rm.index, df_rm['rsk'], color='#d62728', lw=1.3, label='RSk')
axes[1].axhline(0, color='k', ls='--', alpha=0.4)
axes[1].set_ylabel('RSk (standardised)')
axes[1].legend(loc='upper right')
axes[1].grid(alpha=0.3)
axes[2].plot(df_rm.index, df_rm['rkt'], color='#2ca02c', lw=1.3, label='RKt')
axes[2].axhline(3.0, color='k', ls='--', alpha=0.4, label='BM null (3)')
axes[2].set_ylabel('RKt (standardised)')
axes[2].legend(loc='upper right')
axes[2].grid(alpha=0.3)
plt.xticks(rotation=30)
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1084_moments_ts.png'), dpi=120, bbox_inches='tight')
plt.close()

# 9.2 Scatter: RV vs |RSk| vs RKt
fig, axes = plt.subplots(1, 3, figsize=(14, 4.5))
axes[0].scatter(df_rm['rsk'], df_rm['rv'], alpha=0.7, color='#d62728')
axes[0].set_xlabel('RSk')
axes[0].set_ylabel('RV')
axes[0].set_title(f'RV vs RSk (r = {corr_rv_rsk:+.3f})')
axes[0].grid(alpha=0.3)

axes[1].scatter(df_rm['rsk'].abs(), df_rm['rv'], alpha=0.7, color='#ff7f0e')
axes[1].set_xlabel('|RSk|')
axes[1].set_ylabel('RV')
axes[1].set_title(f'RV vs |RSk| (r = {corr_rv_abs_rsk:+.3f})')
axes[1].grid(alpha=0.3)

axes[2].scatter(df_rm['rkt'], df_rm['rv'], alpha=0.7, color='#2ca02c')
axes[2].axvline(3.0, color='k', ls='--', alpha=0.5, label='BM null')
axes[2].set_xlabel('RKt')
axes[2].set_ylabel('RV')
axes[2].set_title(f'RV vs RKt (r = {corr_rv_rkt:+.3f})')
axes[2].legend(loc='upper right')
axes[2].grid(alpha=0.3)
plt.suptitle('K1084 — Higher Moments vs Realized Variance', y=1.02)
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1084_moments_scatter.png'), dpi=120,
            bbox_inches='tight')
plt.close()

# 9.3 HAR variants QLIKE comparison
fig, ax = plt.subplots(figsize=(10, 5))
har_names = ['HAR-RV', 'HAR-RSk', 'HAR-RKt', 'HAR-SJ', 'HAR-Full']
har_qlikes = [rv_eval[n]['QLIKE'] for n in har_names]
bar_colors = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e']
bars = ax.bar(har_names, har_qlikes, color=bar_colors, edgecolor='k')
for b, v in zip(bars, har_qlikes):
    ax.text(b.get_x() + b.get_width() / 2, v + 0.002 if v > 0 else v - 0.01,
            f'{v:+.3f}', ha='center', fontsize=10)
ax.axhline(rv_eval['HAR-RV']['QLIKE'], color='gray', ls='--', alpha=0.6,
           label='HAR-RV baseline')
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title(f'K1084 — HAR Variants QLIKE (OOS n={n_oos})')
ax.legend(loc='best')
ax.grid(alpha=0.3, axis='y')
plt.xticks(rotation=20)
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1084_har_extended.png'), dpi=120,
            bbox_inches='tight')
plt.close()

# 9.4 VaR tail — actual vs VaR
fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
for alpha_idx, (alpha_str, alpha) in enumerate([('5%', 0.05), ('1%', 0.01)]):
    ax = axes[alpha_idx]
    z_n = stats.norm.ppf(alpha)
    var_normal = z_n * sigma_fc
    rkt_lag = np.concatenate([[float('nan')], rkt_values[:-1]])[oos_start_idx:n_total]
    rsk_lag = np.concatenate([[float('nan')], rsk_values[:-1]])[oos_start_idx:n_total]
    rkt_lag_w = np.clip(rkt_lag, q_low_kt, q_high_kt)
    rsk_lag_w = np.clip(rsk_lag, q_low_sk, q_high_sk)
    z = z_n
    excess_kt = rkt_lag_w - 3.0
    cf_quantile = (z
                   + (z ** 2 - 1) / 6.0 * rsk_lag_w
                   + (z ** 3 - 3 * z) / 24.0 * excess_kt
                   - (2 * z ** 3 - 5 * z) / 36.0 * rsk_lag_w ** 2)
    var_cf = cf_quantile * sigma_fc

    dates_oos = df_rm.index[oos_start_idx:n_total]
    ax.plot(dates_oos, daily_ret_oos * 100, color='k', lw=1.0, label='Actual r (%)')
    ax.plot(dates_oos, var_normal * 100, color='#1f77b4', lw=1.1,
            label=f'Normal VaR {alpha_str}')
    ax.plot(dates_oos, var_cf * 100, color='#d62728', lw=1.1,
            label=f'Cornish-Fisher {alpha_str}')
    viol_n = np.sum(daily_ret_oos < var_normal)
    viol_c = np.sum(daily_ret_oos < var_cf)
    ax.set_title(f'VaR {alpha_str} — Normal viol={viol_n}, CF viol={viol_c} '
                 f'(target {alpha*100:.0f}% of {mask_r.sum()})')
    ax.set_ylabel('Return (%)')
    ax.legend(loc='lower left', fontsize=9)
    ax.grid(alpha=0.3)
plt.xticks(rotation=30)
plt.suptitle('K1084 — VaR Tail: Normal vs Cornish-Fisher (RKt-adjusted)', y=1.01)
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1084_var_tail.png'), dpi=120, bbox_inches='tight')
plt.close()

# 9.5 Regime analysis
fig, ax = plt.subplots(figsize=(10, 5))
regime_names = ['HAR-RV', 'HAR-RSk', 'HAR-RKt', 'HAR-Full']
low_vals = [regime_results['Low'].get(n, {}).get('QLIKE', np.nan) for n in regime_names]
high_vals = [regime_results['High'].get(n, {}).get('QLIKE', np.nan) for n in regime_names]
x = np.arange(len(regime_names))
w = 0.35
ax.bar(x - w / 2, low_vals, w, label=f'Low VIX (n={low_mask.sum()})', color='#4fc3f7')
ax.bar(x + w / 2, high_vals, w, label=f'High VIX (n={high_mask.sum()})', color='#e57373')
for xi, v in zip(x - w / 2, low_vals):
    if np.isfinite(v):
        ax.text(xi, v + 0.005 if v > 0 else v - 0.015, f'{v:+.3f}',
                ha='center', fontsize=9)
for xi, v in zip(x + w / 2, high_vals):
    if np.isfinite(v):
        ax.text(xi, v + 0.005 if v > 0 else v - 0.015, f'{v:+.3f}',
                ha='center', fontsize=9)
ax.set_xticks(x)
ax.set_xticklabels(regime_names)
ax.set_ylabel('QLIKE')
ax.set_title(f'K1084 — HAR Variants QLIKE by VIX Regime (median split = {vix_median_oos:.1f})')
ax.legend(loc='best')
ax.grid(alpha=0.3, axis='y')
plt.tight_layout()
plt.savefig(os.path.join(OUTPUT_DIR, 'k1084_regime_analysis.png'), dpi=120,
            bbox_inches='tight')
plt.close()

print("  Charts saved.")


# ═══════════════════════════════════════════════════════════════════════
# 10. RESULTS JSON
# ═══════════════════════════════════════════════════════════════════════

print("\n[10] Saving results...")

results = {
    'experiment_id': 'K1084',
    'title': 'Realized Skewness and Kurtosis — Higher-Order Moments for Volatility Prediction',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'status': 'PRELIMINARY',
    'random_seed': 42,
    'data': {
        'source': 'SPY 5-min CSV (data/intraday/) + yfinance daily',
        'n_5min_files': len(fivemin_files),
        'n_5min_days_processed': int(len(df_rm)),
        'n_daily_spy': int(len(daily_ret)),
        'n_vix': int(len(vix_close)),
    },
    'design': {
        'target': 'RV_{t+1}',
        'init_window': INIT_WINDOW,
        'n_oos': int(n_oos),
        'oos_start': str(df_rm.index[oos_start_idx].date()),
        'oos_end': str(df_rm.index[-1].date()),
        'models': list(model_specs.keys()) + ['GJR-GARCH', 'A4f-VIX2'],
        'var_methods': ['Normal', 'Student-t_df5', 'Cornish-Fisher'],
    },
    'descriptive': desc_stats,
    'full_sample_coefs': full_sample_coefs,
    'evaluation_rv_target': rv_eval,
    'dm_tests_vs_har_rv': dm_results,
    'var_tests': var_tests,
    'regime_analysis': {
        'vix_median_oos': vix_median_oos,
        'low_n': int(low_mask.sum()),
        'high_n': int(high_mask.sum()),
        'by_regime': regime_results,
    },
    'references': [
        'Amaya, Christoffersen, Jacobs & Vasquez (2015). JFE 118(1), 135-167.',
        'Barndorff-Nielsen, Kinnebrock & Shephard (2010). Festschrift for R. Engle.',
        'Neuberger (2012). RFS 25(11).',
        'Corsi (2009). JoFE 7(2).',
        'Patton (2011). JoE.',
        'Harvey (2016). RFS 29(1).',
    ],
    'conclusions': {},
}


# Conclusions (auto-derived)
base_qlike = rv_eval['HAR-RV']['QLIKE']
best_name = min(rv_eval.keys(), key=lambda k: rv_eval[k].get('QLIKE', float('inf')))
best_qlike = rv_eval[best_name]['QLIKE']

conclusions = {
    'H1_rsk_beats_har': {
        'question': 'Does RSk have incremental predictive power for RV?',
        'dm_t_stat': dm_results['HAR-RSk_vs_HAR-RV']['t_stat'],
        'dm_p_value': dm_results['HAR-RSk_vs_HAR-RV']['p_value'],
        'harvey_significant': dm_results['HAR-RSk_vs_HAR-RV']['harvey_significant'],
        'qlike_improvement_pct': float(
            (base_qlike - rv_eval['HAR-RSk']['QLIKE']) / abs(base_qlike) * 100),
        'verdict': ('PASS' if dm_results['HAR-RSk_vs_HAR-RV']['harvey_significant']
                    and dm_results['HAR-RSk_vs_HAR-RV']['t_stat'] < 0 else 'NULL'),
    },
    'H2_rkt_predicts_tail': {
        'question': 'Does RKt predict tail risk (VaR violations)?',
        'kupiec_5pct_normal': var_tests.get('5%', {}).get('Normal', {}).get('pass_kupiec'),
        'kupiec_5pct_cf': var_tests.get('5%', {}).get('Cornish-Fisher', {}).get('pass_kupiec'),
        'kupiec_1pct_normal': var_tests.get('1%', {}).get('Normal', {}).get('pass_kupiec'),
        'kupiec_1pct_cf': var_tests.get('1%', {}).get('Cornish-Fisher', {}).get('pass_kupiec'),
        'verdict': 'see var_tests section',
    },
    'H3_har_full_improvement': {
        'question': 'Does HAR-Full (RV+RSk+RKt+SJ) beat HAR-RV?',
        'dm_t_stat': dm_results['HAR-Full_vs_HAR-RV']['t_stat'],
        'dm_p_value': dm_results['HAR-Full_vs_HAR-RV']['p_value'],
        'harvey_significant': dm_results['HAR-Full_vs_HAR-RV']['harvey_significant'],
        'qlike_improvement_pct': float(
            (base_qlike - rv_eval['HAR-Full']['QLIKE']) / abs(base_qlike) * 100),
        'verdict': ('PASS' if dm_results['HAR-Full_vs_HAR-RV']['harvey_significant']
                    and dm_results['HAR-Full_vs_HAR-RV']['t_stat'] < 0 else 'NULL'),
    },
    'H4_regime_dependent': {
        'question': 'Are higher-moment effects regime-dependent?',
        'low_vix_dm': regime_results['Low'].get('DM_Full_vs_RV', {}),
        'high_vix_dm': regime_results['High'].get('DM_Full_vs_RV', {}),
        'verdict': 'see regime_analysis section',
    },
    'best_model_by_qlike': {
        'name': best_name,
        'qlike': best_qlike,
        'improvement_vs_har_rv_pct': float((base_qlike - best_qlike) / abs(base_qlike) * 100),
    },
    'paper9_implication': (
        'PASS' if any(dm_results[k]['harvey_significant'] and dm_results[k]['t_stat'] < 0
                      for k in dm_results)
        else 'NULL — semi-variance (K1063) already captures the asymmetry signal; '
             'higher moments do not add Harvey-significant incremental predictive power. '
             'Paper 9 should stick with HAR-semi-variance specification.'
    ),
    'caveats': (
        'PRELIMINARY: 60-day 5-min sample. OOS n={} days. Harvey |t|>3.0 is strict. '
        'Results may differ with longer sample. Replicate in K1085+ when 5-min backfill '
        'extends beyond 2026-04-10.'.format(int(n_oos))
    ),
}
results['conclusions'] = conclusions

results_path = os.path.join(OUTPUT_DIR, 'k1084_results.json')
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Saved: {results_path}")

print("\n" + "=" * 72)
print("K1084 Summary")
print("=" * 72)
print(f"  Best HAR variant: {best_name} (QLIKE={best_qlike:+.4f})")
print(f"  HAR-RV baseline:  QLIKE={base_qlike:+.4f}")
print(f"  H1 (RSk):   {conclusions['H1_rsk_beats_har']['verdict']}  "
      f"(t={conclusions['H1_rsk_beats_har']['dm_t_stat']:+.2f})")
print(f"  H3 (Full):  {conclusions['H3_har_full_improvement']['verdict']}  "
      f"(t={conclusions['H3_har_full_improvement']['dm_t_stat']:+.2f})")
print(f"  Paper9 implication: {conclusions['paper9_implication'][:60]}...")
print(f"\n  Results JSON: {results_path}")
print("=" * 72)
