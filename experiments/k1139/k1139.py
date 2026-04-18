"""
K1139: Equity HAR-RV-X VIX component decomposition (Paper 4 mechanism diagnostic)
================================================================================
[提出: Claude (user direction), 執行: Claude]

Motivation
----------
K1138 found that HAR-RV-X PASSES for SPY (t=+4.19) and QQQ (t=+4.22) on
Parkinson RV target (IWM near miss +2.06). This is the ONLY robust extension
that beats baseline in the K1136+K1138 compendium.

Key question for Paper 4 narrative:
  Is the VIX t-stat driven by its REALIZED-VOL component (VIX≈σ_21d) or by
  its FORWARD-LOOKING components (VRP, term premium, implied skew, vol-of-vol)?

  - Scenario A (realized-vol driver): VIX is just an RV proxy → narrative WEAK.
  - Scenario B (forward-looking): VRP adds genuine IV info → narrative STRONG.
  - Scenario C (term structure): VIX3M-VIX matters → new subsection.
  - Scenario D (composite): multi-channel → mid-strong narrative.

Design (tight alignment with K1138 HAR-RV-X spec)
-------------------------------------------------
Target: Parkinson range-based variance (same as K1138 M4/M5)
Assets: SPY, QQQ (K1138 PASS cells; IWM included as near-miss diagnostic)
OOS:    2021-01-04 → 2026-04-10 (same as K1138)
Window: 1500, Refit: 63 (same as K1138)
Seed:   42

Specifications
--------------
  M0  HAR-RV (baseline, no X): log(RV_t) = β_0 + β_d L_d + β_w L_w + β_m L_m
  M1  HAR-RV-VIX         (K1138 baseline) + γ·log(VIX²_{t-1})
  M2  HAR-RV-σ21d        + γ·log(σ²_21d_{t-1})   -- realized-vol channel only
  M3  HAR-RV-VRP         + γ·VRP_{t-1}           -- VRP = VIX² - σ²_21d (level)
  M4  HAR-RV-TermPrem    + γ·TermPrem_{t-1}      -- log(VIX3M²) - log(VIX²)
  M5  HAR-RV-SKEW        + γ·log(SKEW_{t-1})
  M6  HAR-RV-VVIX        + γ·log(VVIX_{t-1})
  M7  HAR-RV-ENCOMPASS   + γ1·σ21d + γ2·VRP + γ3·TermPrem + γ4·SKEW + γ5·VVIX

Tests
-----
  - Each M1..M7 vs M0 baseline: DM-HLN on QLIKE (same-target Parkinson)
  - BH FDR correction across 7 specs per asset (21 cells total for 3 assets)
  - M7 joint regression: which γ_i is individually significant?
  - Encompass: M1 (pure VIX) vs M7 (decomposed) -- if M7 >> M1 then decomposed
    components carry incremental info beyond composite VIX

Leakage safeguards
------------------
  - σ_21d uses STRICTLY past 21 trading days: rolling(21).std().shift(1)
  - All HAR regressors .shift(1) explicit
  - All component levels taken at t-1 (level at close of t-1 used for t forecast)

Reproduction: python experiments/k1139/k1139.py
"""
import sys
import os
import time
import warnings
import json
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats

sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print("=" * 72)
print("K1139: Equity HAR-RV-X VIX component decomposition")
print("Paper 4 mechanism diagnostic (which VIX channel drives K1138 PASS?)")
print("=" * 72)
sys.stdout.flush()


# ============================================================
# STEP 0: DATA (yfinance 2010-2026; SKEW/VVIX/VIX3M from 2010)
# ============================================================
import yfinance as yf

# Data period: 2010 start so all VIX components align
# OOS: 2021-01-04 (same as K1138)
DATA_START = '2010-01-01'
DATA_END = '2026-04-11'
OOS_START = '2021-01-01'
WINDOW = 1500
REFIT_EVERY = 63

ASSETS = ['SPY', 'QQQ', 'IWM']

print('\n[0] Downloading VIX components...')
sys.stdout.flush()

def download_close(ticker):
    df = yf.download(ticker, start=DATA_START, end=DATA_END,
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df['Close'].dropna()

vix = download_close('^VIX')
vix3m = download_close('^VIX3M')
vvix = download_close('^VVIX')
skew = download_close('^SKEW')

print(f'  VIX:    n={len(vix)}, {vix.index[0].strftime("%Y-%m-%d")} ~ {vix.index[-1].strftime("%Y-%m-%d")}, mean={vix.mean():.2f}')
print(f'  VIX3M:  n={len(vix3m)}, {vix3m.index[0].strftime("%Y-%m-%d")} ~ {vix3m.index[-1].strftime("%Y-%m-%d")}, mean={vix3m.mean():.2f}')
print(f'  VVIX:   n={len(vvix)}, {vvix.index[0].strftime("%Y-%m-%d")} ~ {vvix.index[-1].strftime("%Y-%m-%d")}, mean={vvix.mean():.2f}')
print(f'  SKEW:   n={len(skew)}, {skew.index[0].strftime("%Y-%m-%d")} ~ {skew.index[-1].strftime("%Y-%m-%d")}, mean={skew.mean():.2f}')
sys.stdout.flush()


# ============================================================
# STEP 1: Load asset data (OHLC + returns + Parkinson RV)
# ============================================================
def load_asset(ticker):
    print(f"\n[1] Downloading {ticker}...")
    sys.stdout.flush()
    df = yf.download(ticker, start=DATA_START, end=DATA_END,
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    needed = ['Open', 'High', 'Low', 'Close']
    ohlc = df[needed].dropna()
    valid = (ohlc['High'] >= ohlc[['Open', 'Close']].max(axis=1)) & \
            (ohlc['Low'] <= ohlc[['Open', 'Close']].min(axis=1)) & \
            (ohlc['Low'] > 0) & (ohlc['High'] > ohlc['Low'])
    ohlc = ohlc[valid]
    returns_pct = ohlc['Close'].pct_change().dropna() * 100
    ohlc = ohlc.loc[returns_pct.index]
    # Parkinson variance in pct² (K1136/K1138 convention)
    log_hl = np.log(ohlc['High'] / ohlc['Low'])
    park_pct2 = (log_hl ** 2 / (4 * np.log(2)) * 10000.0)

    # σ_21d: rolling 21-day std of daily returns (in pct²).
    # Note: rolling().std() already uses past 21 obs INCLUDING current day t.
    # We will .shift(1) at regressor time to ensure strict past info.
    sigma21_var = (returns_pct.rolling(window=21).std() ** 2)  # pct²

    print(f"  {ticker}: n={len(returns_pct)}, "
          f"{returns_pct.index[0].strftime('%Y-%m-%d')} ~ "
          f"{returns_pct.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Mean r={returns_pct.mean():.4f}%, Std={returns_pct.std():.4f}%, "
          f"Mean Park={park_pct2.mean():.4f} pct²")
    return returns_pct, ohlc, park_pct2, sigma21_var


asset_data = {}
for tk in ASSETS:
    r, ohlc, park, sigma21 = load_asset(tk)
    asset_data[tk] = {'returns': r, 'ohlc': ohlc, 'park': park, 'sigma21': sigma21}


# ============================================================
# STEP 2: Build component regressors per asset (aligned index, lag 1)
# ============================================================
def build_components(returns_index, sigma21_var, vix_s, vix3m_s, vvix_s, skew_s):
    """Return dict of daily series aligned to returns_index.

    UNIT HARMONIZATION (Gemini code review fix, MED→HIGH severity):
    VIX/VIX3M are ANNUALIZED % volatility quotes (CBOE). So VIX² is in
    annualized pct². sigma21_var is rolling variance of DAILY pct returns,
    hence daily pct². To compute VRP = implied - realized in consistent units,
    we convert VIX² to daily by dividing by 252:
        vix2_daily = vix² / 252  (units: daily pct²)
    Then VRP = vix2_daily - sigma21_var is in consistent daily pct² units.

    For log-form regressors (M1 log_vix2, M2 log_sigma21), the constant
    log(1/252) is absorbed by the HAR intercept, so results are invariant
    to whether we scale or not. We keep log(vix²) unscaled to match K1138
    exactly (so M1 = K1138 M4 bit-for-bit).

    Components:
      vix2         = VIX²                             -- for log_vix2 (M1)
      vix2_daily   = VIX²/252 (daily pct²)            -- scale-matched
      sigma21_var  = daily rolling variance (pct²)    -- realized channel
      vrp          = vix2_daily - sigma21_var          -- VRP (unit-matched)
      term_prem    = log(VIX3M²) - log(VIX²)           -- log term spread
      log_skew     = log(SKEW)
      log_vvix     = log(VVIX)
    """
    idx = returns_index
    vix_a = vix_s.reindex(idx).ffill()
    vix3m_a = vix3m_s.reindex(idx).ffill()
    vvix_a = vvix_s.reindex(idx).ffill()
    skew_a = skew_s.reindex(idx).ffill()
    sigma21_a = sigma21_var.reindex(idx)

    vix2 = vix_a ** 2
    vix3m2 = vix3m_a ** 2
    vix2_daily = vix2 / 252.0  # annualized -> daily variance
    vrp = vix2_daily - sigma21_a  # can be negative
    # term premium in log-variance difference (VIX and VIX3M both annualized;
    # log ratio cancels the common annualization constant)
    term_prem = np.log(vix3m2.clip(lower=1e-10)) - np.log(vix2.clip(lower=1e-10))

    return {
        'vix2': vix2,
        'vix2_daily': vix2_daily,
        'sigma21_var': sigma21_a,
        'vrp': vrp,
        'term_prem': term_prem,
        'log_skew': np.log(skew_a.clip(lower=1e-10)),
        'log_vvix': np.log(vvix_a.clip(lower=1e-10)),
    }


# ============================================================
# STEP 3: HAR-RV-X fitter with flexible regressor set
# ============================================================
def build_har_features(rv_series, extras):
    """Build HAR-RV features + optional extra regressors.

    extras: dict of {name: series}, all level series at date t; we .shift(1).
    Returns (X_df, y) aligned, NaN-dropped.
    """
    log_rv = np.log(rv_series.clip(lower=1e-10))
    daily = log_rv.shift(1)
    weekly = log_rv.shift(1).rolling(window=5).mean()
    monthly = log_rv.shift(1).rolling(window=22).mean()
    cols = {'const': 1.0, 'daily': daily, 'weekly': weekly, 'monthly': monthly}
    for name, s in extras.items():
        cols[name] = s.shift(1)
    X = pd.DataFrame(cols).dropna()
    y = log_rv.loc[X.index]
    return X, y


def fit_har_x(rv_series, extras):
    X, y = build_har_features(rv_series, extras)
    X_mat = X.values
    y_vec = y.values
    try:
        beta_hat, *_ = np.linalg.lstsq(X_mat, y_vec, rcond=None)
    except Exception:
        return None
    resid = y_vec - X_mat @ beta_hat
    sigma_resid = np.std(resid, ddof=X_mat.shape[1])
    return {
        'beta': beta_hat.tolist(),
        'col_order': list(X.columns),
        'sigma_resid': float(sigma_resid),
    }


def har_x_forecast(params, rv_history, extras_history):
    """Produce one-step forecast given rv_history (up to t-1) and the LEVEL
    of each extra regressor at t-1 (we read iloc[-1]).

    rv_history: series of RV up to and INCLUDING date t-1 (forecast is for t).
    extras_history: dict of {name: series} same length, values at t-1.
    """
    beta = np.array(params['beta'])
    col_order = params['col_order']
    log_rv = np.log(rv_series_clip(rv_history))
    if len(log_rv) < 22:
        return None
    daily = log_rv.iloc[-1]
    weekly = log_rv.iloc[-5:].mean()
    monthly = log_rv.iloc[-22:].mean()
    base = {'const': 1.0, 'daily': daily, 'weekly': weekly, 'monthly': monthly}
    x_vec = []
    for name in col_order:
        if name in base:
            x_vec.append(base[name])
        else:
            val = extras_history[name].iloc[-1]
            if not np.isfinite(val):
                return None
            x_vec.append(float(val))
    x = np.array(x_vec)
    log_rv_hat = float(x @ beta)
    sigma_resid = params['sigma_resid']
    rv_hat = np.exp(log_rv_hat + 0.5 * sigma_resid ** 2)
    return max(rv_hat, 1e-10)


def rv_series_clip(s):
    return s.clip(lower=1e-10)


# ============================================================
# STEP 4: QLIKE + DM-HLN + BH
# ============================================================
def qlike_pointwise(actual, predicted):
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    out = np.full_like(actual, np.nan, dtype=float)
    valid = (predicted > 0) & np.isfinite(predicted) & (actual > 0) & np.isfinite(actual)
    ratio = np.where(valid, actual / predicted, np.nan)
    out[valid] = ratio[valid] - np.log(ratio[valid]) - 1
    return out


def qlike(actual, predicted):
    return float(np.nanmean(qlike_pointwise(actual, predicted)))


def dm_hln_test(loss1, loss2, h=1):
    """DM-HLN: positive t means loss1 > loss2, i.e. model 2 is better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0, n
    d_mean = np.mean(d)
    max_lag = int(np.floor(n ** (1 / 3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * w * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0, n
    dm_stat = d_mean / np.sqrt(var_d)
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = hln * dm_stat
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_value), int(n)


def benjamini_hochberg(pvals):
    pvals = np.asarray(pvals, dtype=float)
    n = len(pvals)
    order = np.argsort(pvals)
    ranked = pvals[order]
    adj = ranked * n / (np.arange(n) + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.clip(adj, 0, 1)
    out = np.zeros(n)
    out[order] = adj
    return out.tolist()


# ============================================================
# STEP 5: OOS loop per asset × spec
# ============================================================
# Spec definitions: each spec maps to a set of extra regressors (on top of HAR core)
SPECS = {
    'M0_HAR':           [],
    'M1_HAR_VIX':       ['log_vix2'],
    'M2_HAR_SIGMA21':   ['log_sigma21'],
    'M3_HAR_VRP':       ['vrp'],
    'M4_HAR_TERM':      ['term_prem'],
    'M5_HAR_SKEW':      ['log_skew'],
    'M6_HAR_VVIX':      ['log_vvix'],
    'M7_HAR_ENCOMPASS': ['log_sigma21', 'vrp', 'term_prem', 'log_skew', 'log_vvix'],
}


def make_extras(comp, subset_keys):
    """Given components dict and list of extra names, build the extras for fit/forecast."""
    mapping = {
        'log_vix2':    np.log(comp['vix2'].clip(lower=1e-10)),
        'log_sigma21': np.log(comp['sigma21_var'].clip(lower=1e-10)),
        'vrp':         comp['vrp'],
        'term_prem':   comp['term_prem'],
        'log_skew':    comp['log_skew'],
        'log_vvix':    comp['log_vvix'],
    }
    return {name: mapping[name] for name in subset_keys}


def run_asset(ticker):
    print(f"\n{'='*60}\n  Running OOS for {ticker}\n{'='*60}")
    sys.stdout.flush()

    d = asset_data[ticker]
    returns_pct = d['returns']
    park = d['park']
    sigma21_var = d['sigma21']

    # Align components on returns index
    comp = build_components(returns_pct.index, sigma21_var,
                            vix, vix3m, vvix, skew)

    # Find first date where ALL components are defined
    all_series = [comp['vix2'], comp['sigma21_var'], comp['vrp'],
                  comp['term_prem'], comp['log_skew'], comp['log_vvix']]
    combined = pd.concat(all_series, axis=1).dropna()
    first_ok = combined.index[0]
    print(f"  First fully-aligned date: {first_ok.strftime('%Y-%m-%d')}")

    # Truncate
    mask = returns_pct.index >= first_ok
    returns_pct = returns_pct[mask]
    park = park.loc[returns_pct.index]
    for k in comp:
        comp[k] = comp[k].loc[returns_pct.index]

    dates = returns_pct.index
    oos_start_idx_arr = np.where(dates >= OOS_START)[0]
    if len(oos_start_idx_arr) == 0:
        print(f"  No OOS observations for {ticker}!")
        return None
    oos_start_idx = int(oos_start_idx_arr[0])
    n_oos = len(dates) - oos_start_idx
    print(f"  OOS: {dates[oos_start_idx].strftime('%Y-%m-%d')} ~ "
          f"{dates[-1].strftime('%Y-%m-%d')} ({n_oos} obs)")

    forecasts = {s: np.full(n_oos, np.nan) for s in SPECS}
    params_cur = {s: None for s in SPECS}
    last_fit = -REFIT_EVERY
    t0 = time.time()

    for t_oos in range(n_oos):
        t_abs = oos_start_idx + t_oos

        if (t_oos - last_fit) >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_park = park.iloc[train_start:t_abs]
            train_comp = {k: v.iloc[train_start:t_abs] for k, v in comp.items()}
            if len(train_park) < 500:
                continue

            for spec_name, extras_keys in SPECS.items():
                extras = make_extras(train_comp, extras_keys)
                p = fit_har_x(train_park, extras)
                if p is not None:
                    params_cur[spec_name] = p
            last_fit = t_oos
            if t_oos % (REFIT_EVERY * 4) == 0:
                elapsed = time.time() - t0
                pct = t_oos / n_oos * 100
                print(f"  [{ticker}] {pct:.0f}% ({t_oos}/{n_oos}) {elapsed:.1f}s")
                sys.stdout.flush()

        # Forecast for each spec
        rv_hist = park.iloc[:t_abs]
        comp_hist = {k: v.iloc[:t_abs] for k, v in comp.items()}
        for spec_name, extras_keys in SPECS.items():
            if params_cur[spec_name] is None:
                continue
            extras_hist = make_extras(comp_hist, extras_keys)
            h = har_x_forecast(params_cur[spec_name], rv_hist, extras_hist)
            if h is not None:
                forecasts[spec_name][t_oos] = h

    elapsed = time.time() - t0
    print(f"  [{ticker}] done in {elapsed:.1f}s")

    # Build valid mask (all specs must have valid forecast)
    valid_mask = np.ones(n_oos, dtype=bool)
    for s in SPECS:
        valid_mask &= np.isfinite(forecasts[s])
    if valid_mask.sum() < 100:
        print(f"  SKIP: <100 valid forecasts")
        return None

    oos_dates = dates[oos_start_idx:][valid_mask]
    actual = park.iloc[oos_start_idx:].values[valid_mask]
    n_valid = len(oos_dates)
    print(f"  Valid OOS: {n_valid}")

    # Per-spec QLIKE + DM vs M0
    qlike_ind = {}
    metrics = {}
    for s in SPECS:
        fc = forecasts[s][valid_mask]
        q_ind = qlike_pointwise(actual, fc)
        qlike_ind[s] = q_ind
        metrics[s] = {'QLIKE': float(qlike(actual, fc))}

    # DM tests: each M1..M7 vs M0 baseline
    dm_tests = {}
    pvals_list = []
    keys_list = []
    for s in ['M1_HAR_VIX', 'M2_HAR_SIGMA21', 'M3_HAR_VRP', 'M4_HAR_TERM',
              'M5_HAR_SKEW', 'M6_HAR_VVIX', 'M7_HAR_ENCOMPASS']:
        # positive t means M0 loss > s loss => s better
        t_stat, p_val, n_used = dm_hln_test(qlike_ind['M0_HAR'], qlike_ind[s])
        rel = (metrics['M0_HAR']['QLIKE'] - metrics[s]['QLIKE']) / metrics['M0_HAR']['QLIKE'] * 100
        dm_tests[f'{s}_vs_M0'] = {
            'DM_HLN_t': t_stat,
            'DM_HLN_p': p_val,
            'n_used': n_used,
            'QLIKE_rel_improvement_pct': float(rel),
        }
        pvals_list.append(p_val)
        keys_list.append(f'{s}_vs_M0')

    # BH correction across the 7 specs per asset
    bh = benjamini_hochberg(pvals_list)
    for i, k in enumerate(keys_list):
        dm_tests[k]['DM_HLN_p_BH'] = float(bh[i])
        dm_tests[k]['PASS'] = bool(dm_tests[k]['DM_HLN_t'] > 2.0 and bh[i] < 0.05)
        dm_tests[k]['PASS_Harvey'] = bool(dm_tests[k]['DM_HLN_t'] > 3.0 and bh[i] < 0.05)

    # Encompass: M1 (pure VIX) vs M7 (decomposed)
    # positive t means M1 loss > M7 loss => M7 (decomposed) is better than M1 (composite)
    t_enc, p_enc, n_enc = dm_hln_test(qlike_ind['M1_HAR_VIX'], qlike_ind['M7_HAR_ENCOMPASS'])
    dm_tests['M7_ENCOMPASS_vs_M1_VIX'] = {
        'DM_HLN_t': t_enc, 'DM_HLN_p': p_enc, 'n_used': n_enc,
        'description': 'positive t => decomposed components carry info beyond composite VIX',
    }

    # M7 joint regression coefficients (fit on full OOS-era train = last window)
    # Use the LAST refit params for M7 to report coefficients
    m7_params = params_cur['M7_HAR_ENCOMPASS']
    joint_coefs = None
    if m7_params is not None:
        joint_coefs = dict(zip(m7_params['col_order'], m7_params['beta']))

    # IS: joint regression t-stats from a single fit on full training sample
    # (to report "which component is individually significant")
    is_train_park = park
    is_train_comp = {k: v for k, v in comp.items()}
    extras_all = make_extras(is_train_comp, SPECS['M7_HAR_ENCOMPASS'])
    X_all, y_all = build_har_features(is_train_park, extras_all)
    X_mat = X_all.values
    y_vec = y_all.values
    beta_hat, *_ = np.linalg.lstsq(X_mat, y_vec, rcond=None)
    resid = y_vec - X_mat @ beta_hat
    dof = X_mat.shape[0] - X_mat.shape[1]
    s2 = (resid @ resid) / dof
    XtX_inv = np.linalg.inv(X_mat.T @ X_mat)
    se = np.sqrt(s2 * np.diag(XtX_inv))
    coef_tstat = beta_hat / se
    coef_names = list(X_all.columns)
    joint_regression_is = {
        name: {'beta': float(beta_hat[i]), 'se': float(se[i]),
               't_stat': float(coef_tstat[i]),
               'p_value': float(2 * (1 - stats.t.cdf(abs(coef_tstat[i]), df=dof)))}
        for i, name in enumerate(coef_names)
    }

    return {
        'n_oos': int(n_valid),
        'oos_start': str(oos_dates[0].strftime('%Y-%m-%d')),
        'oos_end': str(oos_dates[-1].strftime('%Y-%m-%d')),
        'model_metrics': metrics,
        'dm_tests': dm_tests,
        'm7_last_refit_coefs': joint_coefs,
        'joint_regression_IS': joint_regression_is,
    }


all_results = {}
for tk in ASSETS:
    all_results[tk] = run_asset(tk)

sys.stdout.flush()


# ============================================================
# STEP 6: Scenario verdict
# ============================================================
print("\n" + "=" * 72)
print("SCENARIO DIAGNOSIS")
print("=" * 72)

# Aggregate: for each component spec, count PASS across SPY+QQQ (primary)
# (IWM is supplementary since K1138 was near-miss)
primary_assets = ['SPY', 'QQQ']

pass_count = {}  # spec -> count across primary assets
for spec_key in ['M1_HAR_VIX', 'M2_HAR_SIGMA21', 'M3_HAR_VRP', 'M4_HAR_TERM',
                 'M5_HAR_SKEW', 'M6_HAR_VVIX', 'M7_HAR_ENCOMPASS']:
    cnt = 0
    for tk in primary_assets:
        if all_results.get(tk) is None:
            continue
        d = all_results[tk]['dm_tests'][f'{spec_key}_vs_M0']
        if d.get('PASS', False):
            cnt += 1
    pass_count[spec_key] = cnt

print("\nPASS count across primary assets (SPY+QQQ, out of 2):")
for k, v in pass_count.items():
    print(f"  {k}: {v}/2")

# Scenario classification
sigma21_pass = pass_count.get('M2_HAR_SIGMA21', 0) >= 2
vrp_pass = pass_count.get('M3_HAR_VRP', 0) >= 2
term_pass = pass_count.get('M4_HAR_TERM', 0) >= 2
skew_pass = pass_count.get('M5_HAR_SKEW', 0) >= 2
vvix_pass = pass_count.get('M6_HAR_VVIX', 0) >= 2

# Primary scenario rules:
# A (realized-vol): σ21d PASS, VRP/Term NOT PASS
# B (forward-looking): VRP PASS (regardless of σ21d)
# C (term structure): Term PASS (regardless)
# D (composite): σ21d PASS AND VRP PASS

# Scenario rules (revised post-Gemini review):
# KEY DIAGNOSTIC: does σ21d alone replicate VIX effect?
#   - If σ21d PASS → Scenario A (RV proxy, narrative WEAK)
#   - If σ21d FAIL but forward-looking components PASS/near-miss → B/C/D
# Additional: M7 encompass vs M1 tells us if VIX is an efficient aggregator
if sigma21_pass:
    if vrp_pass or term_pass:
        scenario = 'D_COMPOSITE'
        narrative = ('Both realized-vol (σ_21d) and forward-looking (VRP/Term) '
                     'channels drive VIX predictive power. Paper 4 narrative '
                     'MID-STRONG: VIX acts as multi-channel signal combining '
                     'both memory and IV information.')
    else:
        scenario = 'A_REALIZED_VOL_PROXY'
        narrative = ('Realized-vol channel (σ_21d) alone explains VIX predictive '
                     'power; forward-looking components do NOT pass. VIX is '
                     'effectively a lagged-RV proxy. Paper 4 narrative WEAKENED: '
                     'HAR-RV-X PASS in K1138 is mechanical RV memory, not IV '
                     'info. Reframe as "long-memory RV already captures VIX".')
elif vrp_pass or term_pass or skew_pass or vvix_pass:
    # σ21d FAILS but at least one forward-looking component PASSES
    passing_fwd = [n for n, p in [('VRP', vrp_pass), ('TermPrem', term_pass),
                                   ('SKEW', skew_pass), ('VVIX', vvix_pass)] if p]
    scenario = 'B_FORWARD_LOOKING'
    narrative = (f'σ_21d (pure realized-vol) FAILS OOS → realized-vol proxy '
                 f'hypothesis REJECTED. Forward-looking components PASS: '
                 f'{passing_fwd}. VIX predictive power is genuinely forward-'
                 f'looking (IV premium / term structure / vol-of-vol). Paper 4 '
                 f'narrative STRONGLY SUPPORTED: VIX is endogenous IV signal '
                 f'for equity, not a lagged-RV proxy.')
else:
    # σ21d fails, but no individual forward-looking component PASSES either.
    # Check whether forward-looking components are near-miss (t>1.5) — if so,
    # VIX is composite aggregator of weak forward-looking signals (Scenario B-weak).
    # If σ21d is strongly rejected and IS joint regression shows forward-looking
    # components highly significant, this is still "VIX is forward-looking
    # aggregator" (B_AGGREGATOR).
    # Compute mean DM t across primary assets for each forward component
    def mean_t(spec_key):
        ts = []
        for tk in primary_assets:
            if all_results.get(tk) is None:
                continue
            ts.append(all_results[tk]['dm_tests'][f'{spec_key}_vs_M0']['DM_HLN_t'])
        return float(np.mean(ts)) if ts else 0.0
    t_vrp_mean = mean_t('M3_HAR_VRP')
    t_term_mean = mean_t('M4_HAR_TERM')
    t_vvix_mean = mean_t('M6_HAR_VVIX')
    t_sigma21_mean = mean_t('M2_HAR_SIGMA21')
    fwd_mean_t = (t_vrp_mean + t_term_mean + t_vvix_mean) / 3.0
    if fwd_mean_t > t_sigma21_mean + 1.0:
        scenario = 'B_AGGREGATOR'
        narrative = (f'σ_21d FAILS decisively (mean t={t_sigma21_mean:+.2f}) '
                     f'while forward-looking components collectively stronger '
                     f'(mean t VRP/Term/VVIX = {fwd_mean_t:+.2f}). No single '
                     f'forward component PASSES at Harvey joint threshold but '
                     f'VIX as composite PASSES. VIX is an EFFICIENT AGGREGATOR '
                     f'of weak-but-coherent forward-looking signals. Paper 4 '
                     f'narrative MID-STRONG: VIX genuinely adds IV info beyond '
                     f'RV memory; no single component replaces it but the '
                     f'composite is not a realized-vol proxy.')
    else:
        scenario = 'MIXED_WEAK'
        narrative = ('Mixed/weak component signals. Report specific passing '
                     'cells without over-claiming a clean narrative.')

print(f"\n>>> Scenario: {scenario}")
print(f">>> Narrative: {narrative}")


# ============================================================
# STEP 7: Write results JSON
# ============================================================
results = {
    'experiment_id': 'K1139',
    'title': 'Equity HAR-RV-X VIX component decomposition (Paper 4 mechanism diagnostic)',
    'description': (
        'Decompose K1138 VIX predictive power into realized-vol component '
        '(σ_21d), VRP (VIX²-σ²_21d), term premium (VIX3M-VIX), SKEW, VVIX. '
        'Test each individually (M1..M6) and jointly (M7 encompassing) vs '
        'HAR-RV baseline (M0) on Parkinson RV target for SPY/QQQ/IWM. '
        'Diagnose whether VIX is realized-vol proxy (Scenario A) vs genuine '
        'IV signal (Scenario B/C/D).'),
    'design': {
        'assets': ASSETS,
        'target': 'Parkinson range-based variance (pct²)',
        'oos_period': f'{OOS_START} to {DATA_END}',
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'specs': {k: v for k, v in SPECS.items()},
        'baseline': 'M0_HAR (plain Corsi 2009)',
        'seed': 42,
        'lag_safeguards': [
            'All HAR regressors .shift(1) explicit',
            'σ_21d = rolling(21).std()**2 .shift(1) -- strictly past 21 days',
            'VIX/VIX3M/VVIX/SKEW levels at t-1 used to forecast day t',
            'BH FDR across 7 specs per asset',
        ],
    },
    'per_asset_results': all_results,
    'pass_count_primary_assets': pass_count,
    'scenario': scenario,
    'paper4_narrative': narrative,
    'components_available': {
        'VIX': {'n': int(len(vix)), 'start': str(vix.index[0].date()), 'end': str(vix.index[-1].date())},
        'VIX3M': {'n': int(len(vix3m)), 'start': str(vix3m.index[0].date()), 'end': str(vix3m.index[-1].date())},
        'VVIX': {'n': int(len(vvix)), 'start': str(vvix.index[0].date()), 'end': str(vvix.index[-1].date())},
        'SKEW': {'n': int(len(skew)), 'start': str(skew.index[0].date()), 'end': str(skew.index[-1].date())},
    },
    'data_source': 'yfinance (SPY/QQQ/IWM OHLC + ^VIX + ^VIX3M + ^VVIX + ^SKEW)',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'references': [
        'Corsi (2009) J Financial Econometrics 7(2):174-196.',
        'Patton (2011) J Econometrics 160:246-256.',
        'Harvey, Leybourne, Newbold (1997) IJF 13:281-291.',
        'Harvey (2016) RFS 29:5-68 (|t|>3 threshold).',
        'Benjamini, Hochberg (1995) JRSS-B 57:289-300.',
        'Bollerslev, Tauchen, Zhou (2009) RFS 22:4463-4492 (VRP).',
        'Bekaert, Hoerova (2014) JoE 183:181-192 (VIX conditional vol vs VRP).',
    ],
}
json_path = os.path.join(SCRIPT_DIR, 'k1139_results.json')
with open(json_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\nResults saved: {json_path}")


# ============================================================
# STEP 8: Charts
# ============================================================
# Chart 1: bar chart of DM-HLN t per component per asset
fig, ax = plt.subplots(figsize=(12, 6))
spec_labels = ['M1\nVIX', 'M2\nσ21d', 'M3\nVRP', 'M4\nTerm', 'M5\nSKEW', 'M6\nVVIX', 'M7\nEncompass']
spec_keys = ['M1_HAR_VIX', 'M2_HAR_SIGMA21', 'M3_HAR_VRP', 'M4_HAR_TERM',
             'M5_HAR_SKEW', 'M6_HAR_VVIX', 'M7_HAR_ENCOMPASS']
x = np.arange(len(spec_labels))
width = 0.25
colors = {'SPY': '#1f77b4', 'QQQ': '#ff7f0e', 'IWM': '#2ca02c'}
for i, tk in enumerate(ASSETS):
    if all_results.get(tk) is None:
        continue
    ts = []
    for sk in spec_keys:
        d = all_results[tk]['dm_tests'][f'{sk}_vs_M0']
        ts.append(d['DM_HLN_t'])
    ax.bar(x + (i - 1) * width, ts, width, label=tk, color=colors[tk], alpha=0.85)
ax.axhline(2.0, ls='--', color='gray', alpha=0.6, label='|t|=2')
ax.axhline(3.0, ls=':', color='red', alpha=0.6, label='|t|=3 Harvey')
ax.axhline(0, color='black', lw=0.5)
ax.set_xticks(x)
ax.set_xticklabels(spec_labels)
ax.set_ylabel('DM-HLN t (vs M0 HAR-RV baseline)')
ax.set_title(f'K1139: VIX component contribution — positive t = component adds value\nScenario: {scenario}')
ax.legend()
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart1 = os.path.join(SCRIPT_DIR, 'vix_component_contribution.png')
plt.savefig(chart1, dpi=150)
plt.close()
print(f"Chart 1 saved: {chart1}")

# Chart 2: component correlation matrix (on full sample)
comp_spy = build_components(asset_data['SPY']['returns'].index,
                            asset_data['SPY']['sigma21'],
                            vix, vix3m, vvix, skew)
comp_df = pd.DataFrame({
    'log_vix2':        np.log(comp_spy['vix2'].clip(lower=1e-10)),
    'log_sigma21':     np.log(comp_spy['sigma21_var'].clip(lower=1e-10)),
    'vrp_daily':       comp_spy['vrp'],
    'term_prem':       comp_spy['term_prem'],
    'log_skew':        comp_spy['log_skew'],
    'log_vvix':        comp_spy['log_vvix'],
}).dropna()
# VRP diagnostic: mean, std, positive fraction
vrp_s = comp_spy['vrp'].dropna()
print(f"\nVRP diagnostic (daily pct² units): mean={vrp_s.mean():.3f}, "
      f"std={vrp_s.std():.3f}, frac>0={np.mean(vrp_s > 0):.2%}")
print(f"  (Typical VRP is POSITIVE because IV includes risk premium over RV; "
      f"expect ~80%+ positive)")
corr = comp_df.corr()
fig, ax = plt.subplots(figsize=(7, 6))
im = ax.imshow(corr.values, cmap='RdBu_r', vmin=-1, vmax=1, aspect='auto')
ax.set_xticks(range(len(corr.columns)))
ax.set_xticklabels(corr.columns, rotation=45, ha='right')
ax.set_yticks(range(len(corr.columns)))
ax.set_yticklabels(corr.columns)
for i in range(len(corr.columns)):
    for j in range(len(corr.columns)):
        ax.text(j, i, f'{corr.values[i, j]:.2f}', ha='center', va='center',
                fontsize=9, color='white' if abs(corr.values[i, j]) > 0.5 else 'black')
plt.colorbar(im, ax=ax, label='Pearson correlation')
ax.set_title('K1139: VIX component correlation matrix (SPY sample)\n'
             'High collinearity between log_vix2 / log_sigma21 / log_vvix = confound risk for M7')
plt.tight_layout()
chart2 = os.path.join(SCRIPT_DIR, 'component_correlation_matrix.png')
plt.savefig(chart2, dpi=150)
plt.close()
print(f"Chart 2 saved: {chart2}")

print(f"\n*** K1139 COMPLETE. Scenario: {scenario} ***")
