#!/usr/bin/env python3
"""
K510: Volume-GARCH — Lamoureux & Lastrapes (1990) Replication + Extension

Literature:
  Lamoureux & Lastrapes (1990) "Heteroskedasticity in Stock Return Data:
  Volume versus GARCH Effects" Journal of Finance 45(1):221-229
  - h_t = ω + α·ε²_{t-1} + β·h_{t-1} + δ·V_t  (V = detrended volume)
  - Adding volume dramatically reduces persistence (α+β)
  - ARCH effects nearly vanish when volume included

  Clark (1973) — Mixture of Distributions Hypothesis (MDH)
  Tauchen & Pitts (1983) — formal MDH derivation

Key difference from K113/K160/K186:
  K113: used volume surprise (volume / 21d MA - 1) → null
  K160: MDH contemporaneous r=0.31-0.43 but lagged partial|VIX < 0.08 → null
  K186: Volume displacement proxies → 0/25 DM pass
  THIS: L&L (1990) detrended volume directly in variance equation,
        focus on PERSISTENCE DROP + ARCH-LM disappearance, then OOS QLIKE

Models (5):
  1. GJR-GARCH baseline (no volume)
  2. GJR + raw volume (K113 style, expect null)
  3. GJR + detrended volume (L&L 1990 style — key test)
  4. GJR + log volume
  5. GJR + volume z-score

Core tests:
  A. Persistence drop: does α+γ/2+β decrease with volume?
  B. ARCH-LM disappearance: do standardized residuals lose ARCH?
  C. OOS QLIKE improvement (L&L didn't do this — our extension)
  D. Cross-OOS 5 periods (if C passes)

Assets: SPY (primary) + QQQ (validation)
OOS: 2023-2025
Window: 2000, refit every 21 days

Data: yfinance (daily OHLCV)
Proxy: realized variance = close-to-close squared returns (standard)

Refs:
  Lamoureux & Lastrapes (1990) JoF 45(1):221-229
  Clark (1973) "A Subordinated Stochastic Process Model"
  Tauchen & Pitts (1983) Econometrica
  K113, K160, K186 (prior volume experiments — all null)
"""

import json
import warnings
import time
from datetime import datetime, timezone
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats, signal, optimize
from statsmodels.stats.diagnostic import het_arch

warnings.filterwarnings('ignore')

# ============================================================
# Configuration
# ============================================================
ASSETS = ['SPY', 'QQQ']
DATA_START = '2010-01-01'
OOS_START = '2023-01-01'
WINDOW = 2000
REFIT_EVERY = 21

MODEL_NAMES = {
    'baseline': 'GJR-GARCH (no volume)',
    'raw_vol': 'GJR + raw volume',
    'detrended': 'GJR + detrended volume (L&L 1990)',
    'log_vol': 'GJR + log volume',
    'zscore': 'GJR + volume z-score',
}


# ============================================================
# Data download & preparation
# ============================================================
def download_data():
    """Download daily OHLCV for SPY and QQQ."""
    data = {}
    for ticker in ASSETS:
        df = yf.download(ticker, start=DATA_START, end='2025-12-31',
                        progress=False, auto_adjust=True)
        if len(df) > 500:
            data[ticker] = df
            print(f"  {ticker}: {len(df)} obs ({df.index[0].date()} to {df.index[-1].date()})")
        else:
            print(f"  {ticker}: insufficient data ({len(df)} obs)")
    return data


def prepare_volume_features(df):
    """
    Prepare 4 volume transformations + returns + realized var.
    """
    close = df['Close'].squeeze()
    volume = df['Volume'].squeeze()

    log_ret = np.log(close / close.shift(1)) * 100  # percent for arch
    rv = (np.log(close / close.shift(1))) ** 2  # raw squared return

    # Volume transformations
    raw_vol = volume / 1e6  # scale to millions
    log_vol = np.log(volume.replace(0, np.nan))

    # L&L (1990) detrending: linear detrend on log volume
    log_vol_clean = log_vol.dropna()
    detrended = pd.Series(signal.detrend(log_vol_clean.values),
                         index=log_vol_clean.index)

    # Volume surprise (K113 style)
    vol_surprise = volume / volume.rolling(21).mean() - 1

    # Z-score (rolling 252d)
    roll_mean = log_vol.rolling(252).mean()
    roll_std = log_vol.rolling(252).std()
    zscore = (log_vol - roll_mean) / roll_std

    result = pd.DataFrame({
        'ret': log_ret,
        'rv': rv,
        'raw_vol': raw_vol,
        'log_vol': log_vol,
        'detrended': detrended,
        'vol_surprise': vol_surprise,
        'zscore': zscore,
    })

    return result.dropna()


# ============================================================
# Custom GJR-GARCH-X via MLE
# ============================================================
def gjr_garchx_loglik(params, returns, x_vol=None):
    """
    Negative log-likelihood for GJR-GARCH(1,1)-X model.

    Model:
      r_t = μ + ε_t,  ε_t ~ N(0, h_t)
      h_t = ω + α·ε²_{t-1} + γ·ε²_{t-1}·I(ε_{t-1}<0) + β·h_{t-1} [+ δ·V_t]

    params: [mu, omega, alpha, gamma, beta, (delta if x_vol)]
    """
    has_x = x_vol is not None

    mu = params[0]
    omega = params[1]
    alpha = params[2]
    gamma = params[3]
    beta = params[4]
    delta = params[5] if has_x else 0.0

    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)

    # Initialize h[0] with sample variance
    h[0] = np.var(returns)

    for t in range(1, T):
        indicator = 1.0 if eps[t-1] < 0 else 0.0
        h[t] = omega + alpha * eps[t-1]**2 + gamma * eps[t-1]**2 * indicator + beta * h[t-1]
        if has_x:
            h[t] += delta * x_vol[t]
        if h[t] <= 0:
            h[t] = 1e-8  # floor

    # Gaussian log-likelihood (ignoring constant)
    ll = -0.5 * np.sum(np.log(h) + eps**2 / h)

    if np.isnan(ll) or np.isinf(ll):
        return 1e10

    return -ll  # negative for minimization


def fit_gjr_garchx(returns_arr, x_vol_arr=None, verbose=False):
    """
    Fit GJR-GARCH(1,1)-X model via MLE.

    Returns dict with params, loglik, aic, bic, conditional_var, std_resid.
    """
    has_x = x_vol_arr is not None
    T = len(returns_arr)

    # Initial values from standard GJR fit
    try:
        am = arch_model(pd.Series(returns_arr), vol='GARCH', p=1, o=1, q=1,
                       mean='Constant', dist='normal')
        res0 = am.fit(disp='off')
        mu0 = res0.params['mu']
        omega0 = res0.params['omega']
        alpha0 = res0.params['alpha[1]']
        gamma0 = res0.params['gamma[1]']
        beta0 = res0.params['beta[1]']
    except:
        mu0 = np.mean(returns_arr)
        omega0 = 0.01
        alpha0 = 0.05
        gamma0 = 0.10
        beta0 = 0.85

    if has_x:
        x0 = [mu0, omega0, alpha0, gamma0, beta0, 0.001]
        bounds = [
            (None, None),       # mu
            (1e-8, None),       # omega > 0
            (1e-8, 0.5),        # alpha > 0
            (0.0, 0.5),         # gamma >= 0
            (1e-8, 0.9999),     # beta > 0
            (None, None),       # delta (can be negative)
        ]
    else:
        x0 = [mu0, omega0, alpha0, gamma0, beta0]
        bounds = [
            (None, None),       # mu
            (1e-8, None),       # omega > 0
            (1e-8, 0.5),        # alpha > 0
            (0.0, 0.5),         # gamma >= 0
            (1e-8, 0.9999),     # beta > 0
        ]

    try:
        res = optimize.minimize(
            gjr_garchx_loglik,
            x0,
            args=(returns_arr, x_vol_arr),
            method='L-BFGS-B',
            bounds=bounds,
            options={'maxiter': 500, 'ftol': 1e-10}
        )

        if not res.success and verbose:
            print(f"    Optimization warning: {res.message}")

        params = res.x
        mu = params[0]
        omega = params[1]
        alpha = params[2]
        gamma = params[3]
        beta = params[4]
        delta = params[5] if has_x else 0.0

        # Recompute conditional variance
        eps = returns_arr - mu
        h = np.zeros(T)
        h[0] = np.var(returns_arr)
        for t in range(1, T):
            indicator = 1.0 if eps[t-1] < 0 else 0.0
            h[t] = omega + alpha * eps[t-1]**2 + gamma * eps[t-1]**2 * indicator + beta * h[t-1]
            if has_x:
                h[t] += delta * x_vol_arr[t]
            if h[t] <= 0:
                h[t] = 1e-8

        nparams = len(params)
        loglik = -res.fun
        aic = -2 * loglik + 2 * nparams
        bic = -2 * loglik + np.log(T) * nparams

        std_resid = eps / np.sqrt(h)

        persistence = alpha + gamma / 2 + beta

        return {
            'mu': float(mu),
            'omega': float(omega),
            'alpha': float(alpha),
            'gamma': float(gamma),
            'beta': float(beta),
            'delta': float(delta) if has_x else None,
            'persistence': float(persistence),
            'loglik': float(loglik),
            'aic': float(aic),
            'bic': float(bic),
            'h': h,
            'std_resid': std_resid,
            'eps': eps,
            'success': True,
        }
    except Exception as e:
        if verbose:
            print(f"    Fit failed: {e}")
        return {'success': False, 'error': str(e)}


def arch_lm_test(resid, lags=10):
    """ARCH-LM test on residuals. Returns (stat, p-value)."""
    try:
        lm_stat, lm_pval, _, _ = het_arch(resid, nlags=lags)
        return float(lm_stat), float(lm_pval)
    except:
        return np.nan, np.nan


# ============================================================
# In-sample analysis (L&L 1990 replication)
# ============================================================
def in_sample_analysis(features, asset):
    """Replicate L&L (1990): fit full-sample models, compare persistence & ARCH-LM."""
    print(f"\n{'='*60}")
    print(f"IN-SAMPLE ANALYSIS: {asset}")
    print(f"{'='*60}")

    ret = features['ret'].values

    results = {}

    # 1. Baseline GJR-GARCH
    print("\n  [1] GJR-GARCH baseline...")
    res_base = fit_gjr_garchx(ret, x_vol_arr=None, verbose=True)
    if res_base['success']:
        lm_stat, lm_pval = arch_lm_test(res_base['std_resid'])
        results['baseline'] = {
            'alpha': res_base['alpha'],
            'gamma': res_base['gamma'],
            'beta': res_base['beta'],
            'persistence': res_base['persistence'],
            'delta': None,
            'arch_lm_stat': lm_stat,
            'arch_lm_pval': lm_pval,
            'loglik': res_base['loglik'],
            'aic': res_base['aic'],
            'bic': res_base['bic'],
        }
        p = res_base
        print(f"    Persistence = {p['persistence']:.4f} (α={p['alpha']:.4f}, γ={p['gamma']:.4f}, β={p['beta']:.4f})")
        print(f"    ARCH-LM(10): stat={lm_stat:.2f}, p={lm_pval:.4f} "
              f"{'***' if lm_pval < 0.01 else '**' if lm_pval < 0.05 else 'NS'}")
    else:
        print(f"    BASELINE FIT FAILED")
        return results

    # 2-5. Volume models
    vol_configs = [
        ('raw_vol', 'raw_vol', 'GJR + raw volume'),
        ('detrended', 'detrended', 'GJR + detrended (L&L 1990)'),
        ('log_vol', 'log_vol', 'GJR + log volume'),
        ('zscore', 'zscore', 'GJR + volume z-score'),
    ]

    for i, (key, col, name) in enumerate(vol_configs, 2):
        print(f"\n  [{i}] {name}...")
        x_vol = features[col].values

        res = fit_gjr_garchx(ret, x_vol_arr=x_vol, verbose=True)
        if res['success']:
            lm_stat, lm_pval = arch_lm_test(res['std_resid'])

            results[key] = {
                'alpha': res['alpha'],
                'gamma': res['gamma'],
                'beta': res['beta'],
                'persistence': res['persistence'],
                'delta': res['delta'],
                'arch_lm_stat': lm_stat,
                'arch_lm_pval': lm_pval,
                'loglik': res['loglik'],
                'aic': res['aic'],
                'bic': res['bic'],
            }
            print(f"    Persistence = {res['persistence']:.4f} (α={res['alpha']:.4f}, γ={res['gamma']:.4f}, β={res['beta']:.4f})")
            print(f"    Volume coeff δ = {res['delta']:.6f}")
            print(f"    ARCH-LM(10): stat={lm_stat:.2f}, p={lm_pval:.4f} "
                  f"{'***' if lm_pval < 0.01 else '**' if lm_pval < 0.05 else 'NS'}")

            # Persistence comparison
            base_pers = results['baseline']['persistence']
            drop = base_pers - res['persistence']
            drop_pct = drop / base_pers * 100
            print(f"    Persistence drop: {drop:.4f} ({drop_pct:+.1f}%)")

            # AIC comparison
            aic_diff = res['aic'] - results['baseline']['aic']
            print(f"    AIC diff vs baseline: {aic_diff:+.2f} ({'better' if aic_diff < 0 else 'worse'})")
        else:
            results[key] = {'error': 'fit failed'}
            print(f"    FIT FAILED")

    return results


# ============================================================
# Out-of-sample walk-forward
# ============================================================
def walk_forward_oos(features, asset):
    """
    OOS walk-forward with refitting every 21 days.
    For each model, forecast 1-step-ahead conditional variance.
    """
    print(f"\n{'='*60}")
    print(f"OOS WALK-FORWARD: {asset}")
    print(f"{'='*60}")

    ret_full = features['ret'].values
    rv_full = features['rv'].values
    idx = features.index

    oos_mask = idx >= OOS_START
    oos_positions = np.where(oos_mask)[0]

    if len(oos_positions) == 0:
        print("  No OOS data available!")
        return {}

    print(f"  OOS period: {idx[oos_positions[0]].date()} to {idx[oos_positions[-1]].date()} ({len(oos_positions)} days)")

    vol_cols = {
        'baseline': None,
        'raw_vol': 'raw_vol',
        'detrended': 'detrended',
        'log_vol': 'log_vol',
        'zscore': 'zscore',
    }

    forecasts = {k: [] for k in vol_cols}
    actual_rv = []
    forecast_dates = []

    # Cache fitted models
    cached_fits = {k: None for k in vol_cols}
    last_refit = -999

    n_refits = 0
    t0 = time.time()

    for i, pos in enumerate(oos_positions):
        train_start = max(0, pos - WINDOW)
        train_end = pos  # train on [train_start, train_end)

        if train_end - train_start < 500:
            continue

        need_refit = (i - last_refit) >= REFIT_EVERY or cached_fits['baseline'] is None

        if need_refit:
            train_ret = ret_full[train_start:train_end]

            for model_key, vol_col in vol_cols.items():
                if vol_col is None:
                    res = fit_gjr_garchx(train_ret, x_vol_arr=None)
                else:
                    x_vol_train = features[vol_col].values[train_start:train_end]

                    # For detrended: re-detrend within training window
                    if vol_col == 'detrended':
                        log_v_train = features['log_vol'].values[train_start:train_end]
                        x_vol_train = signal.detrend(log_v_train)

                    res = fit_gjr_garchx(train_ret, x_vol_arr=x_vol_train)

                if res['success']:
                    cached_fits[model_key] = res

            last_refit = i
            n_refits += 1

        # Generate 1-step ahead forecast for each model
        for model_key, vol_col in vol_cols.items():
            fit = cached_fits[model_key]
            if fit is None or not fit.get('success', False):
                forecasts[model_key].append(np.nan)
                continue

            # h_{t+1} = ω + α·ε²_t + γ·ε²_t·I(ε_t<0) + β·h_t [+ δ·V_{t+1}]
            # For forecasting: use last values from training
            last_h = fit['h'][-1]
            last_eps = fit['eps'][-1]
            indicator = 1.0 if last_eps < 0 else 0.0

            h_fc = (fit['omega'] + fit['alpha'] * last_eps**2
                    + fit['gamma'] * last_eps**2 * indicator
                    + fit['beta'] * last_h)

            # Add volume term using t-1 (yesterday's) volume for forecasting
            if vol_col is not None and fit['delta'] is not None:
                # Use previous day's volume (pos-1) to avoid look-ahead
                prev_pos = pos - 1
                if prev_pos >= 0:
                    if vol_col == 'detrended':
                        # Approximate: use log_vol - training mean
                        vol_val = features['log_vol'].values[prev_pos]
                        train_log = features['log_vol'].values[train_start:train_end]
                        vol_val = vol_val - np.mean(train_log)
                    else:
                        vol_val = features[vol_col].values[prev_pos]

                    if not np.isnan(vol_val):
                        h_fc += fit['delta'] * vol_val

            # Convert from (100*return)^2 to return^2 scale
            h_fc_rv = h_fc / (100 ** 2)

            if h_fc_rv > 0 and not np.isnan(h_fc_rv):
                forecasts[model_key].append(h_fc_rv)
            else:
                forecasts[model_key].append(np.nan)

        actual_rv.append(rv_full[pos])
        forecast_dates.append(idx[pos])

    elapsed = time.time() - t0
    print(f"  {n_refits} refits, {len(forecast_dates)} forecast days, {elapsed:.1f}s")

    # Evaluate
    actual = np.array(actual_rv)
    results = {}

    for model_key in vol_cols:
        fc = np.array(forecasts[model_key])
        valid = ~np.isnan(fc) & ~np.isnan(actual) & (fc > 0) & (actual > 0)

        if valid.sum() < 100:
            results[model_key] = {'error': f'too few valid ({valid.sum()})'}
            continue

        a = actual[valid]
        f = fc[valid]

        qlike = np.mean(a / f + np.log(f))
        mse = np.mean((a - f) ** 2)

        results[model_key] = {
            'qlike': float(qlike),
            'mse': float(mse),
            'n_valid': int(valid.sum()),
            'mean_forecast': float(np.mean(f)),
            'mean_actual': float(np.mean(a)),
        }
        print(f"  {MODEL_NAMES.get(model_key, model_key)}: QLIKE={qlike:.6f}, MSE={mse:.2e}, N={valid.sum()}")

    # DM tests vs baseline
    if 'baseline' in results and 'qlike' in results.get('baseline', {}):
        base_fc = np.array(forecasts['baseline'])

        print(f"\n  DM Tests vs baseline (QLIKE loss):")
        for model_key in ['raw_vol', 'detrended', 'log_vol', 'zscore']:
            if model_key not in results or 'qlike' not in results[model_key]:
                continue

            alt_fc = np.array(forecasts[model_key])
            valid = (~np.isnan(base_fc) & ~np.isnan(alt_fc) &
                     ~np.isnan(actual) & (base_fc > 0) & (alt_fc > 0) & (actual > 0))

            if valid.sum() < 100:
                continue

            a = actual[valid]
            bf = base_fc[valid]
            af = alt_fc[valid]

            # QLIKE loss differential
            loss_base = a / bf + np.log(bf)
            loss_alt = a / af + np.log(af)
            d = loss_base - loss_alt  # positive = alt better

            d_mean = np.mean(d)
            n = len(d)

            # HAC variance (Newey-West with 5 lags)
            nw_lags = 5
            gamma0 = np.var(d, ddof=1)
            hac_var = gamma0
            for lag in range(1, nw_lags + 1):
                w = 1 - lag / (nw_lags + 1)
                gamma_l = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
                hac_var += 2 * w * gamma_l

            if hac_var <= 0:
                hac_var = gamma0  # fallback

            dm_stat = d_mean / np.sqrt(max(hac_var, 1e-15) / n)
            dm_pval = 2 * (1 - stats.norm.cdf(abs(dm_stat)))

            qlike_change = ((results[model_key]['qlike'] - results['baseline']['qlike'])
                           / abs(results['baseline']['qlike']) * 100)

            # DM > 0 means volume model is BETTER (lower loss)
            # DM < 0 means baseline is BETTER
            sig = '***' if abs(dm_stat) > 3.0 else '**' if abs(dm_stat) > 2.0 else '*' if abs(dm_stat) > 1.65 else 'NS'
            # Harvey PASS requires DM > +3.0 (volume model significantly better)
            harvey = 'PASS' if dm_stat > 3.0 else 'FAIL'
            direction = 'vol BETTER' if dm_stat > 0 else 'baseline BETTER'

            results[model_key]['dm_stat'] = float(dm_stat)
            results[model_key]['dm_pval'] = float(dm_pval)
            results[model_key]['qlike_change_pct'] = float(qlike_change)
            results[model_key]['harvey_pass'] = harvey == 'PASS'

            print(f"    {MODEL_NAMES.get(model_key, model_key)}: "
                  f"DM={dm_stat:+.3f} (p={dm_pval:.4f}) {sig} [{direction}] | "
                  f"QLIKE Δ={qlike_change:+.2f}% | Harvey: {harvey}")

    return results


# ============================================================
# Descriptive statistics
# ============================================================
def descriptive_stats(features, asset):
    """Print descriptive statistics for diagnostics."""
    print(f"\n{'='*60}")
    print(f"DESCRIPTIVE STATISTICS: {asset}")
    print(f"{'='*60}")

    ret = features['ret']
    print(f"\n  Returns (×100):")
    print(f"    N = {len(ret)}")
    print(f"    Mean = {ret.mean():.4f}")
    print(f"    Std = {ret.std():.4f}")
    print(f"    Skew = {ret.skew():.4f}")
    print(f"    Kurt = {ret.kurtosis():.4f}")

    from statsmodels.tsa.stattools import adfuller
    adf_stat, adf_pval, _, _, _, _ = adfuller(ret.dropna(), maxlag=20, autolag='AIC')
    print(f"    ADF: stat={adf_stat:.4f}, p={adf_pval:.4f} ({'stationary' if adf_pval < 0.05 else 'non-stationary'})")

    lm_stat, lm_pval = arch_lm_test(ret.dropna().values)
    print(f"    ARCH-LM(10): stat={lm_stat:.2f}, p={lm_pval:.4f} ({'ARCH present' if lm_pval < 0.05 else 'no ARCH'})")

    # Volume stats
    for col in ['raw_vol', 'log_vol', 'detrended', 'vol_surprise', 'zscore']:
        v = features[col].dropna()
        print(f"\n  {col}:")
        print(f"    N={len(v)}, Mean={v.mean():.4f}, Std={v.std():.4f}, Skew={v.skew():.2f}, Kurt={v.kurtosis():.2f}")

    # Contemporaneous correlation: |return| vs volume (MDH test)
    abs_ret = ret.abs()
    for col in ['raw_vol', 'log_vol', 'detrended', 'zscore']:
        v = features[col]
        common = abs_ret.index.intersection(v.dropna().index)
        r, p = stats.pearsonr(abs_ret.loc[common], v.loc[common])
        print(f"\n  Corr(|ret|, {col}) = {r:.4f} (p={p:.4f})")


# ============================================================
# Main
# ============================================================
def main():
    print("=" * 70)
    print("K510: Volume-GARCH — Lamoureux & Lastrapes (1990) Replication + Extension")
    print("=" * 70)
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print(f"Assets: {ASSETS}")
    print(f"OOS: {OOS_START} onwards | Window: {WINDOW} | Refit: {REFIT_EVERY}d")
    print(f"Method: Custom MLE for GJR-GARCH(1,1)-X")

    t_start = time.time()

    # Download data
    print("\n--- Downloading data ---")
    raw_data = download_data()

    all_results = {}

    for asset in ASSETS:
        if asset not in raw_data:
            print(f"\n  {asset}: no data, skipping")
            continue

        # Prepare features
        features = prepare_volume_features(raw_data[asset])
        print(f"\n  {asset}: {len(features)} usable observations")

        # Step 1: Descriptive statistics
        descriptive_stats(features, asset)

        # Step 2: In-sample analysis (L&L 1990 replication)
        is_results = in_sample_analysis(features, asset)

        # Step 3: OOS walk-forward
        oos_results = walk_forward_oos(features, asset)

        all_results[asset] = {
            'in_sample': is_results,
            'oos': oos_results,
        }

    total_time = time.time() - t_start
    print(f"\n{'='*70}")
    print(f"Total time: {total_time:.1f}s")

    # ============================================================
    # Summary
    # ============================================================
    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")

    # Persistence comparison table
    print("\n  A. Persistence (α + γ/2 + β) — L&L core test:")
    print(f"  {'Model':<35} {'SPY':>10} {'QQQ':>10}")
    print(f"  {'-'*55}")
    for model_key in ['baseline', 'raw_vol', 'detrended', 'log_vol', 'zscore']:
        row = f"  {MODEL_NAMES.get(model_key, model_key):<35}"
        for asset in ASSETS:
            if asset in all_results:
                is_r = all_results[asset]['in_sample'].get(model_key, {})
                if 'persistence' in is_r:
                    row += f" {is_r['persistence']:>10.4f}"
                else:
                    row += f" {'FAIL':>10}"
            else:
                row += f" {'N/A':>10}"
        print(row)

    # Volume coefficient
    print("\n  Volume coefficient δ:")
    print(f"  {'Model':<35} {'SPY':>10} {'QQQ':>10}")
    print(f"  {'-'*55}")
    for model_key in ['raw_vol', 'detrended', 'log_vol', 'zscore']:
        row = f"  {MODEL_NAMES.get(model_key, model_key):<35}"
        for asset in ASSETS:
            if asset in all_results:
                is_r = all_results[asset]['in_sample'].get(model_key, {})
                if 'delta' in is_r and is_r['delta'] is not None:
                    row += f" {is_r['delta']:>10.4f}"
                else:
                    row += f" {'FAIL':>10}"
            else:
                row += f" {'N/A':>10}"
        print(row)

    # ARCH-LM comparison
    print("\n  B. ARCH-LM p-value (>0.05 = ARCH eliminated):")
    print(f"  {'Model':<35} {'SPY':>10} {'QQQ':>10}")
    print(f"  {'-'*55}")
    for model_key in ['baseline', 'raw_vol', 'detrended', 'log_vol', 'zscore']:
        row = f"  {MODEL_NAMES.get(model_key, model_key):<35}"
        for asset in ASSETS:
            if asset in all_results:
                is_r = all_results[asset]['in_sample'].get(model_key, {})
                if 'arch_lm_pval' in is_r:
                    p = is_r['arch_lm_pval']
                    row += f" {p:>10.4f}"
                else:
                    row += f" {'FAIL':>10}"
            else:
                row += f" {'N/A':>10}"
        print(row)

    # AIC comparison
    print("\n  AIC (lower = better):")
    print(f"  {'Model':<35} {'SPY':>10} {'QQQ':>10}")
    print(f"  {'-'*55}")
    for model_key in ['baseline', 'raw_vol', 'detrended', 'log_vol', 'zscore']:
        row = f"  {MODEL_NAMES.get(model_key, model_key):<35}"
        for asset in ASSETS:
            if asset in all_results:
                is_r = all_results[asset]['in_sample'].get(model_key, {})
                if 'aic' in is_r:
                    row += f" {is_r['aic']:>10.1f}"
                else:
                    row += f" {'FAIL':>10}"
            else:
                row += f" {'N/A':>10}"
        print(row)

    # OOS QLIKE comparison
    print("\n  C. OOS QLIKE (lower = better):")
    print(f"  {'Model':<35} {'SPY':>10} {'QQQ':>10}")
    print(f"  {'-'*55}")
    for model_key in ['baseline', 'raw_vol', 'detrended', 'log_vol', 'zscore']:
        row = f"  {MODEL_NAMES.get(model_key, model_key):<35}"
        for asset in ASSETS:
            if asset in all_results:
                oos_r = all_results[asset]['oos'].get(model_key, {})
                if 'qlike' in oos_r:
                    row += f" {oos_r['qlike']:>10.6f}"
                else:
                    row += f" {'FAIL':>10}"
            else:
                row += f" {'N/A':>10}"
        print(row)

    # DM test summary
    print("\n  D. DM Tests (vs baseline, DM>0 = vol model better, Harvey t>3.0):")
    any_pass = False
    any_sig_worse = False
    for asset in ASSETS:
        if asset not in all_results:
            continue
        for model_key in ['raw_vol', 'detrended', 'log_vol', 'zscore']:
            oos_r = all_results[asset]['oos'].get(model_key, {})
            if 'dm_stat' in oos_r:
                dm = oos_r['dm_stat']
                harvey = 'PASS ★' if oos_r.get('harvey_pass', False) else 'FAIL'
                direction = 'vol BETTER' if dm > 0 else 'baseline BETTER'
                if oos_r.get('harvey_pass', False):
                    any_pass = True
                if dm < -2.0:
                    any_sig_worse = True
                print(f"    {asset} {MODEL_NAMES.get(model_key, model_key)}: "
                      f"DM={dm:+.3f} [{direction}], QLIKE Δ={oos_r['qlike_change_pct']:+.2f}% — {harvey}")

    # Verdict
    print(f"\n{'='*70}")

    # Check L&L replication
    ll_replicated = False
    ll_details = {}
    for asset in ASSETS:
        if asset in all_results:
            is_r = all_results[asset]['in_sample']
            if 'baseline' in is_r and 'detrended' in is_r:
                if ('persistence' in is_r['baseline'] and 'persistence' in is_r['detrended']):
                    base_p = is_r['baseline']['persistence']
                    detr_p = is_r['detrended']['persistence']
                    drop_pct = (base_p - detr_p) / base_p * 100
                    ll_details[asset] = {
                        'base_persistence': base_p,
                        'detrended_persistence': detr_p,
                        'drop_pct': drop_pct,
                    }
                    if drop_pct > 5:  # at least 5% drop
                        ll_replicated = True

    if ll_replicated:
        print("L&L (1990) IN-SAMPLE REPLICATION: CONFIRMED — volume reduces persistence")
        for a, d in ll_details.items():
            print(f"  {a}: {d['base_persistence']:.4f} → {d['detrended_persistence']:.4f} ({d['drop_pct']:+.1f}%)")
    else:
        print("L&L (1990) IN-SAMPLE REPLICATION: NOT CONFIRMED — persistence drop < 5%")
        for a, d in ll_details.items():
            print(f"  {a}: {d['base_persistence']:.4f} → {d['detrended_persistence']:.4f} ({d['drop_pct']:+.1f}%)")

    if any_pass:
        verdict = "POSITIVE — Volume-GARCH improves OOS forecasting (Harvey t>+3.0)"
    elif any_sig_worse:
        verdict = "NEGATIVE — Volume-GARCH significantly WORSENS OOS forecasting (DM<-2.0). L&L persistence drop is in-sample artifact."
    else:
        verdict = "NULL — Volume-GARCH does NOT improve OOS forecasting despite in-sample persistence drop"

    print(f"\nOOS VERDICT: {verdict}")
    print(f"{'='*70}")

    # ============================================================
    # Save results
    # ============================================================
    output = {
        'experiment_id': 'K510',
        'title': 'Volume-GARCH — Lamoureux & Lastrapes (1990) Replication + Extension',
        'date': datetime.now(timezone.utc).isoformat(),
        'status': 'completed',
        'literature': {
            'primary': 'Lamoureux & Lastrapes (1990) "Heteroskedasticity in Stock Return Data: Volume versus GARCH Effects" JoF 45(1):221-229',
            'theory': 'Clark (1973) MDH; Tauchen & Pitts (1983) Econometrica',
            'prior_work': 'K113 (volume surprise GARCH-X null), K160 (MDH vol null), K186 (volume displacement 0/25)',
        },
        'data': {
            'source': 'yfinance (daily OHLCV)',
            'assets': ASSETS,
            'period': f'{DATA_START} to 2025-12-31',
            'oos_start': OOS_START,
            'proxy': 'close-to-close squared returns',
        },
        'methodology': {
            'models': MODEL_NAMES,
            'volume_treatments': {
                'raw_vol': 'raw volume / 1e6',
                'detrended': 'linearly detrended log volume (L&L 1990)',
                'log_vol': 'log(volume)',
                'zscore': 'rolling 252d z-score of log volume',
            },
            'estimation': 'Custom MLE with L-BFGS-B (arch library has no GARCH-X support)',
            'window': WINDOW,
            'refit_every': REFIT_EVERY,
            'evaluation': 'QLIKE, MSE, DM test (Newey-West HAC)',
            'harvey_threshold': 3.0,
        },
        'results': {},
        'verdict': verdict,
        'll_replicated': ll_replicated,
        'll_details': ll_details,
        'any_dm_pass': any_pass,
        'total_time_s': round(total_time, 1),
    }

    for asset in ASSETS:
        if asset in all_results:
            output['results'][asset] = all_results[asset]

    output_path = 'experiments/k510_volume_garch_results.json'
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved to {output_path}")


if __name__ == '__main__':
    main()
