"""
K1134: Range-based volatility proxy + GAS-t on commodities
================================================================================
[提出: Claude (based on user direction), 執行: Claude]

Motivation:
K1129 NULL 4/4 (USO/GLD/UNG/BTC) using close² as proxy for daily σ². But
close² is a *noisy* proxy with high variance. Range-based estimators
(Parkinson 1980, Garman-Klass 1980, Rogers-Satchell 1991) use intraday
High/Low/Open/Close to estimate daily σ² with 5-14x lower variance. A more
precise proxy gives DM tests more power — if GAS-t's advantage exists but
is small, it may emerge under range proxy where it was invisible under r².

Research question: Does a less-noisy daily-variance proxy reveal GAS-t edge
on commodities that close² hid?

Literature:
- Parkinson (1980) J Business 53(1):61-65 — (log H/L)² / (4 log 2)
- Garman & Klass (1980) J Business 53(1):67-78 — 0.5 [log H/L]² - (2 log 2 - 1) [log C/O]²
- Rogers & Satchell (1991) Ann Appl Prob 1(4):504-512 — log(H/C)log(H/O) + log(L/C)log(L/O)
- Patton (2011) J Econometrics 160:246-256 — QLIKE proxy-robustness (Theorem 1)
- Creal, Koopman, Lucas (2013) JASA 108(501):1-18 — GAS framework

Prior:
- K1129: r² proxy, 4/4 commodities NULL (USO, GLD, UNG, BTC-USD)
- K1038: r² proxy, 4/4 equities NULL
- K437: r² proxy, SPY only, NULL

Hypotheses:
- H1 (primary): With Parkinson proxy, GAS-t beats GJR on >= 2/4 assets
  (DM-HLN |t| > 2 AND QLIKE rel-improvement > 5% AND sub-period stable)
- H2: Range-based QLIKE values are smaller absolute magnitude than r²-based
  (Patton 2011 variance reduction in proxy)
- H3: Null repeats (GAS downweight hurts in extreme regime regardless of proxy)
- H4: Estimator ranking robustness — Parkinson / GK / RS give same model
  ranking (QLIKE proxy-robust under Patton 2011)

Design:
- 4 assets: USO / GLD / UNG / BTC-USD (same as K1129)
- 3 models: M1 GJR-GARCH Normal, M2 GJR-GARCH Student-t, M3 GAS-t
  (same as K1129 — models fit to close-to-close returns in pct units)
- 3 range targets: Parkinson (primary), Garman-Klass, Rogers-Satchell
- OOS 2021-2026, window=1500, refit=63 (same as K1129)
- Triple gate as K1129 (DM |t|>2 + QLIKE>5% + sub-period stable)
- Seed: 42

Data source: yfinance (O/H/L/C columns)

Caveats (Research Honesty #5, #10):
- USO/UNG: contango/roll noise in close² may be reduced by range — but
  intraday range is also affected by roll days. Expect small but non-zero
  bias.
- BTC-USD: 24h market, O/H/L/C are daily bar from yfinance. Range estimator
  still measures daily-variance but "close" is 00:00 UTC snapshot, not
  session close.
- Models fit to close returns (pct); range proxy must use same scale
  (100 × log(H/L)).
- HE < 0 / persistence boundary etc. tracked in convergence flags.

Reproduction: python experiments/k1134/k1134.py
"""

import sys
import os
import numpy as np
import pandas as pd
import json
import time
import warnings
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timezone
from scipy import stats
from scipy.optimize import minimize
from scipy.special import gammaln

sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings('ignore')
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print("=" * 72)
print("K1134: Range-based proxy + GAS-t on Commodities (USO/GLD/UNG/BTC-USD)")
print("Parkinson/Garman-Klass/Rogers-Satchell as daily σ² proxy")
print("=" * 72)
sys.stdout.flush()

# ============================================================
# STEP 0: Data Download — need O/H/L/C not just Close
# ============================================================
import yfinance as yf

ASSETS = {
    'USO': {'start': '2007-01-01', 'end': '2026-04-11'},
    'GLD': {'start': '2005-01-01', 'end': '2026-04-11'},
    'UNG': {'start': '2008-01-01', 'end': '2026-04-11'},
    'BTC-USD': {'start': '2015-01-01', 'end': '2026-04-11'},
}

OOS_START = '2021-01-01'
SUB_PERIOD_SPLIT = '2024-01-01'
WINDOW = 1500
REFIT_EVERY = 63

asset_data = {}
for ticker, params in ASSETS.items():
    print(f"\n[0] Downloading {ticker} (O/H/L/C)...")
    sys.stdout.flush()
    df = yf.download(ticker, start=params['start'], end=params['end'],
                     progress=False, auto_adjust=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Require all OHLC columns present
    needed = ['Open', 'High', 'Low', 'Close']
    if not all(c in df.columns for c in needed):
        print(f"  ERROR: {ticker} missing OHLC columns: {df.columns.tolist()}")
        continue

    ohlc = df[needed].dropna()
    # Sanity: H >= max(O,C) and L <= min(O,C), H > L > 0
    valid = (ohlc['High'] >= ohlc[['Open', 'Close']].max(axis=1)) & \
            (ohlc['Low'] <= ohlc[['Open', 'Close']].min(axis=1)) & \
            (ohlc['Low'] > 0) & (ohlc['High'] > ohlc['Low'])
    n_bad = int((~valid).sum())
    if n_bad > 0:
        print(f"  WARN: {n_bad} rows with invalid OHLC — dropping")
        ohlc = ohlc[valid]

    # close-to-close percentage returns for model fitting (matches K1129)
    returns_pct = ohlc['Close'].pct_change().dropna() * 100
    # Align OHLC to returns_pct index (drop first row)
    ohlc = ohlc.loc[returns_pct.index]

    print(f"  Observations: {len(returns_pct)}")
    print(f"  Date range: {returns_pct.index[0].strftime('%Y-%m-%d')} ~ "
          f"{returns_pct.index[-1].strftime('%Y-%m-%d')}")
    print(f"  Mean: {returns_pct.mean():.4f}%, Std: {returns_pct.std():.4f}%")
    print(f"  Skew: {returns_pct.skew():.3f}, Kurt (excess): {returns_pct.kurtosis():.3f}")

    asset_data[ticker] = {'returns_pct': returns_pct, 'ohlc': ohlc}

sys.stdout.flush()


# ============================================================
# RANGE-BASED VOLATILITY ESTIMATORS
# ============================================================
# All estimators return variance estimate in pct² units (to match r² scale).
# Input: OHLC DataFrame (prices, any units), output: pd.Series of σ² in pct².

def parkinson_var_pct2(ohlc):
    """
    Parkinson (1980): σ² = (log(H/L))² / (4 log 2).
    This estimates Var(daily log-return). Multiply by 100² to match pct scale.
    """
    log_hl = np.log(ohlc['High'] / ohlc['Low'])
    var_logret = log_hl**2 / (4 * np.log(2))
    # return in pct² to match r²_pct scale
    return var_logret * 10000.0


def garman_klass_var_pct2(ohlc):
    """
    Garman-Klass (1980): σ² = 0.5 [log(H/L)]² - (2 log 2 - 1) [log(C/O)]².
    Can be negative when C/O range dominates H/L (extreme trend days); floor at 0.
    """
    log_hl = np.log(ohlc['High'] / ohlc['Low'])
    log_co = np.log(ohlc['Close'] / ohlc['Open'])
    var_logret = 0.5 * log_hl**2 - (2 * np.log(2) - 1) * log_co**2
    var_logret = var_logret.clip(lower=1e-12)  # avoid zero/neg for QLIKE
    return var_logret * 10000.0


def rogers_satchell_var_pct2(ohlc):
    """
    Rogers-Satchell (1991): drift-independent.
    σ² = log(H/C)·log(H/O) + log(L/C)·log(L/O).
    """
    log_h_c = np.log(ohlc['High'] / ohlc['Close'])
    log_h_o = np.log(ohlc['High'] / ohlc['Open'])
    log_l_c = np.log(ohlc['Low'] / ohlc['Close'])
    log_l_o = np.log(ohlc['Low'] / ohlc['Open'])
    var_logret = log_h_c * log_h_o + log_l_c * log_l_o
    var_logret = var_logret.clip(lower=1e-12)
    return var_logret * 10000.0


# Compute range proxies for each asset — diagnostic ratio vs r²
for ticker, d in asset_data.items():
    ohlc = d['ohlc']
    r2 = (d['returns_pct'] ** 2)
    d['parkinson'] = parkinson_var_pct2(ohlc)
    d['garman_klass'] = garman_klass_var_pct2(ohlc)
    d['rogers_satchell'] = rogers_satchell_var_pct2(ohlc)
    print(f"\n[diag] {ticker}:")
    print(f"  mean r² = {r2.mean():.4f}, mean Parkinson = {d['parkinson'].mean():.4f} "
          f"(ratio {d['parkinson'].mean()/r2.mean():.3f})")
    print(f"  mean GK = {d['garman_klass'].mean():.4f} "
          f"(ratio {d['garman_klass'].mean()/r2.mean():.3f})")
    print(f"  mean RS = {d['rogers_satchell'].mean():.4f} "
          f"(ratio {d['rogers_satchell'].mean()/r2.mean():.3f})")
    # efficiency (variance of proxy) — Parkinson theoretical efficiency 4.9x
    print(f"  SD(r²) = {r2.std():.4f}, SD(Parkinson) = {d['parkinson'].std():.4f} "
          f"(P/r² SD-ratio {d['parkinson'].std()/r2.std():.3f})")

sys.stdout.flush()


# ============================================================
# MODEL LIKELIHOODS AND FITTERS (identical to K1129)
# ============================================================

def gjr_normal_negloglik(params, returns):
    omega, alpha, gamma, beta = params
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    nll = 0.5 * np.sum(np.log(2 * np.pi * sigma2) + returns**2 / sigma2)
    return nll if np.isfinite(nll) else 1e10


def gjr_t_negloglik(params, returns):
    omega, alpha, gamma, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    nll = 0.0
    for t in range(T):
        eps2 = returns[t]**2 / sigma2[t]
        ll_t = (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2) * sigma2[t])
                - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2)))
        nll -= ll_t
    return nll if np.isfinite(nll) else 1e10


def gas_t_negloglik(params, returns):
    omega, alpha, beta, log_nu_minus2 = params
    nu = np.exp(log_nu_minus2) + 2.0
    T = len(returns)
    f = np.zeros(T)
    f[0] = np.log(np.var(returns))
    nll = 0.0
    for t in range(T):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = returns[t]**2 / sigma2_t
        ll_t = (gammaln((nu + 1) / 2) - gammaln(nu / 2)
                - 0.5 * np.log(np.pi * (nu - 2) * sigma2_t)
                - (nu + 1) / 2 * np.log(1 + eps2 / (nu - 2)))
        nll -= ll_t
        if t < T - 1:
            score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
            S = 2 * nu / ((nu + 3) * (nu - 2))
            scaled_score = S * score
            f[t+1] = omega + alpha * scaled_score + beta * f[t]
    return nll if np.isfinite(nll) else 1e10


def fit_gjr_normal(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.03, 0.05, 0.90]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999)]
    try:
        res = minimize(gjr_normal_negloglik, x0, args=(returns,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 500})
        if not res.success:
            res = minimize(gjr_normal_negloglik, x0, args=(returns,), method='Nelder-Mead',
                          options={'maxiter': 2000})
    except Exception:
        return None, None
    omega, alpha, gamma, beta = res.x
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta,
            'persistence': alpha + gamma / 2 + beta}, sigma2


def fit_gjr_t(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0 = [var_r * 0.05, 0.03, 0.05, 0.90, np.log(6.0)]
    bounds = [(1e-8, var_r * 10), (1e-8, 0.5), (1e-8, 0.5), (0.3, 0.999),
              (np.log(0.1), np.log(100.0))]
    try:
        res = minimize(gjr_t_negloglik, x0, args=(returns,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 500})
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [var_r * 0.02, 0.05, 0.08, 0.88, np.log(4.0)],
                [var_r * 0.08, 0.02, 0.03, 0.92, np.log(10.0)],
            ]:
                try:
                    res2 = minimize(gjr_t_negloglik, x0_alt, args=(returns,), method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None
    omega, alpha, gamma, beta, log_nu_minus2 = res.x
    nu = np.exp(log_nu_minus2) + 2.0
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = omega + alpha * returns[t-1]**2 + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1]
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return {'omega': omega, 'alpha': alpha, 'gamma': gamma, 'beta': beta, 'nu': nu,
            'persistence': alpha + gamma / 2 + beta}, sigma2


def fit_gas_t(returns):
    T = len(returns)
    var_r = np.var(returns)
    x0 = [0.01, 0.05, 0.95, np.log(6.0)]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100.0))]
    try:
        res = minimize(gas_t_negloglik, x0, args=(returns,), method='L-BFGS-B',
                      bounds=bounds, options={'maxiter': 500})
        if not res.success or res.fun > 1e9:
            for x0_alt in [
                [0.005, 0.1, 0.90, np.log(4.0)],
                [0.02, 0.03, 0.97, np.log(10.0)],
                [0.0, 0.08, 0.92, np.log(8.0)],
            ]:
                try:
                    res2 = minimize(gas_t_negloglik, x0_alt, args=(returns,), method='L-BFGS-B',
                                    bounds=bounds, options={'maxiter': 500})
                    if res2.fun < res.fun:
                        res = res2
                except Exception:
                    pass
    except Exception:
        return None, None
    omega, alpha, beta, log_nu_minus2 = res.x
    nu = np.exp(log_nu_minus2) + 2.0
    f = np.zeros(T)
    f[0] = np.log(var_r)
    for t in range(T - 1):
        sigma2_t = np.exp(f[t])
        if sigma2_t < 1e-10:
            sigma2_t = 1e-10
        eps2 = returns[t]**2 / sigma2_t
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        f[t+1] = omega + alpha * scaled_score + beta * f[t]
    sigma2 = np.exp(f)
    return {'omega': omega, 'alpha': alpha, 'beta': beta, 'nu': nu,
            'persistence': beta}, sigma2


def forecast_one_step(model_type, params, last_return, last_sigma2, last_f=None):
    if model_type == 'M1_GJR_N':
        ind = 1.0 if last_return < 0 else 0.0
        h = (params['omega'] + params['alpha'] * last_return**2
             + params['gamma'] * last_return**2 * ind + params['beta'] * last_sigma2)
    elif model_type == 'M2_GJR_t':
        ind = 1.0 if last_return < 0 else 0.0
        h = (params['omega'] + params['alpha'] * last_return**2
             + params['gamma'] * last_return**2 * ind + params['beta'] * last_sigma2)
    elif model_type == 'M3_GAS_t':
        nu = params['nu']
        eps2 = last_return**2 / last_sigma2
        score = -0.5 + (nu + 1) / 2 * eps2 / (nu - 2 + eps2)
        S = 2 * nu / ((nu + 3) * (nu - 2))
        scaled_score = S * score
        new_f = params['omega'] + params['alpha'] * scaled_score + params['beta'] * last_f
        h = np.exp(new_f)
    else:
        raise ValueError(f"Unknown: {model_type}")
    return max(h, 1e-10)


# ============================================================
# EVALUATION METRICS
# ============================================================

def qlike_pointwise(actual, predicted):
    """Element-wise QLIKE; returns array (with NaN for invalid)."""
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    out = np.full_like(actual, np.nan, dtype=float)
    valid = (predicted > 0) & np.isfinite(predicted) & (actual > 0) & np.isfinite(actual)
    ratio = np.where(valid, actual / predicted, np.nan)
    out[valid] = ratio[valid] - np.log(ratio[valid]) - 1
    return out


def qlike(actual, predicted):
    loss = qlike_pointwise(actual, predicted)
    return float(np.nanmean(loss))


def dm_hln_test(loss1, loss2, h=1):
    d = loss1 - loss2
    d = d[np.isfinite(d) & ~np.isnan(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0, n
    d_mean = np.mean(d)
    max_lag = int(np.floor(n ** (1/3)))
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
    hln_correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_stat = hln_correction * dm_stat
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return t_stat, p_value, n


# ============================================================
# OOS FORECASTING LOOP (models same as K1129 — only TARGET changes)
# ============================================================
all_results = {}
model_keys = ['M1_GJR_N', 'M2_GJR_t', 'M3_GAS_t']
targets = ['parkinson', 'garman_klass', 'rogers_satchell', 'r2_close']  # r2_close = K1129 baseline for comparison

for ticker, d in asset_data.items():
    print(f"\n{'='*60}")
    print(f"  Processing: {ticker}")
    print(f"{'='*60}")
    sys.stdout.flush()

    returns_pct = d['returns_pct']
    returns = returns_pct.values
    dates = returns_pct.index

    oos_mask = dates >= OOS_START
    if not any(oos_mask):
        print(f"  SKIP: No OOS data")
        continue
    oos_start_idx = int(np.where(oos_mask)[0][0])
    if oos_start_idx < WINDOW:
        print(f"  SKIP: Not enough IS data ({oos_start_idx} < {WINDOW})")
        continue
    n_oos = len(returns) - oos_start_idx
    print(f"  OOS: {dates[oos_start_idx].strftime('%Y-%m-%d')} ~ "
          f"{dates[-1].strftime('%Y-%m-%d')} ({n_oos} obs)")

    forecasts = {m: np.full(n_oos, np.nan) for m in model_keys}
    current_params = {m: None for m in model_keys}
    current_sigma2 = {m: None for m in model_keys}
    current_f = {m: None for m in model_keys}

    t0 = time.time()
    last_fit = -REFIT_EVERY

    for t_oos in range(n_oos):
        t_abs = oos_start_idx + t_oos

        if t_oos - last_fit >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_data = returns[train_start:t_abs]
            if len(train_data) < 500:
                continue

            p_m1, s2_m1 = fit_gjr_normal(train_data)
            p_m2, s2_m2 = fit_gjr_t(train_data)
            p_m3, s2_m3 = fit_gas_t(train_data)

            if p_m1 is not None:
                current_params['M1_GJR_N'] = p_m1
                current_sigma2['M1_GJR_N'] = s2_m1[-1]
            if p_m2 is not None:
                current_params['M2_GJR_t'] = p_m2
                current_sigma2['M2_GJR_t'] = s2_m2[-1]
            if p_m3 is not None:
                current_params['M3_GAS_t'] = p_m3
                current_sigma2['M3_GAS_t'] = s2_m3[-1]
                current_f['M3_GAS_t'] = np.log(max(s2_m3[-1], 1e-10))

            last_fit = t_oos
            if t_oos % (REFIT_EVERY * 3) == 0:
                elapsed = time.time() - t0
                pct = t_oos / n_oos * 100
                print(f"  [{ticker}] {pct:.0f}% ({t_oos}/{n_oos}) {elapsed:.1f}s")
                sys.stdout.flush()

        last_r = returns[t_abs - 1]
        for m in model_keys:
            if current_params[m] is None:
                continue
            if m == 'M3_GAS_t':
                h = forecast_one_step(m, current_params[m], last_r,
                                      current_sigma2[m], last_f=current_f[m])
                forecasts[m][t_oos] = h
                current_sigma2[m] = h
                current_f[m] = np.log(max(h, 1e-10))
            else:
                h = forecast_one_step(m, current_params[m], last_r, current_sigma2[m])
                forecasts[m][t_oos] = h
                current_sigma2[m] = h

    elapsed = time.time() - t0
    print(f"  [{ticker}] forecasting done in {elapsed:.1f}s")
    sys.stdout.flush()

    # Build OOS slices
    oos_dates = dates[oos_start_idx:]
    valid_mask = np.ones(n_oos, dtype=bool)
    for m in model_keys:
        valid_mask &= np.isfinite(forecasts[m])
    if np.sum(valid_mask) < 100:
        print(f"  SKIP: <100 valid forecasts")
        continue

    oos_dates_v = oos_dates[valid_mask]
    n_valid = len(oos_dates_v)
    print(f"  Valid OOS: {n_valid}")

    # Build targets (aligned to oos_dates)
    oos_targets = {}
    oos_targets['r2_close'] = (returns[oos_start_idx:] ** 2)[valid_mask]
    for proxy_name in ['parkinson', 'garman_klass', 'rogers_satchell']:
        series = d[proxy_name].reindex(oos_dates).values[valid_mask]
        oos_targets[proxy_name] = series

    # Diagnostic: proxy coverage / NaN rate
    for tgt in targets:
        nan_rate = np.mean(~np.isfinite(oos_targets[tgt]))
        mean_v = np.nanmean(oos_targets[tgt])
        print(f"    target={tgt}: NaN={nan_rate*100:.1f}%, mean={mean_v:.4f}")

    # Per-target evaluation
    ticker_results = {
        'n_oos': int(n_valid),
        'oos_start': str(oos_dates_v[0].strftime('%Y-%m-%d')),
        'oos_end': str(oos_dates_v[-1].strftime('%Y-%m-%d')),
        'kurtosis_excess': float(returns_pct.kurtosis()),
        'skewness': float(returns_pct.skew()),
        'std_pct': float(returns_pct.std()),
        'per_target': {},
    }

    for tgt in targets:
        actual = oos_targets[tgt]
        print(f"\n  --- Target: {tgt} ---")
        tgt_res = {'model_metrics': {}, 'dm_tests': {}, 'sub_period_qlike': None}
        qlike_ind = {}
        for m in model_keys:
            fc = forecasts[m][valid_mask]
            q = qlike(actual, fc)
            # Spearman rank correlation — proxy-agnostic for ranking validation
            valid_both = np.isfinite(actual) & np.isfinite(fc) & (actual > 0) & (fc > 0)
            if valid_both.sum() > 10:
                rho, rho_p = stats.spearmanr(actual[valid_both], fc[valid_both])
            else:
                rho, rho_p = np.nan, 1.0
            tgt_res['model_metrics'][m] = {
                'QLIKE': float(q) if np.isfinite(q) else None,
                'Spearman_rho': float(rho) if np.isfinite(rho) else None,
                'Spearman_p': float(rho_p) if np.isfinite(rho_p) else None,
                'n_finite': int(valid_both.sum()),
            }
            qlike_ind[m] = qlike_pointwise(actual, fc)
            print(f"    {m}: QLIKE={q:.6f}, rho={rho:.3f}")

        # DM tests
        q_m1 = tgt_res['model_metrics']['M1_GJR_N']['QLIKE']
        for m in ['M2_GJR_t', 'M3_GAS_t']:
            t_stat, p_val, n_used = dm_hln_test(qlike_ind['M1_GJR_N'], qlike_ind[m])
            q_m = tgt_res['model_metrics'][m]['QLIKE']
            rel_impr = ((q_m1 - q_m) / q_m1 * 100) if (q_m1 and q_m) else np.nan
            tgt_res['dm_tests'][f'{m}_vs_M1'] = {
                'DM_HLN_t': float(t_stat),
                'DM_HLN_p': float(p_val),
                'n_used': int(n_used),
                'QLIKE_rel_improvement_pct': float(rel_impr) if np.isfinite(rel_impr) else None,
                'gate_DM': bool(abs(t_stat) > 2.0),
                'gate_QLIKE_5pct': bool(np.isfinite(rel_impr) and rel_impr > 5.0),
                'significant_Harvey': bool(abs(t_stat) > 3.0),
                'better': m if t_stat > 0 else 'M1_GJR_N',
            }
            print(f"    DM-HLN {m} vs M1: t={t_stat:.3f}, p={p_val:.3e}, "
                  f"rel_impr={rel_impr:+.2f}%")

        # DM M3 vs M2
        t_s, p_s, n_s = dm_hln_test(qlike_ind['M2_GJR_t'], qlike_ind['M3_GAS_t'])
        q_m2 = tgt_res['model_metrics']['M2_GJR_t']['QLIKE']
        q_m3 = tgt_res['model_metrics']['M3_GAS_t']['QLIKE']
        rel32 = ((q_m2 - q_m3) / q_m2 * 100) if (q_m2 and q_m3) else np.nan
        tgt_res['dm_tests']['M3_GAS_t_vs_M2_GJR_t'] = {
            'DM_HLN_t': float(t_s),
            'DM_HLN_p': float(p_s),
            'n_used': int(n_s),
            'QLIKE_rel_improvement_pct': float(rel32) if np.isfinite(rel32) else None,
            'gate_DM': bool(abs(t_s) > 2.0),
            'better': 'M3_GAS_t' if t_s > 0 else 'M2_GJR_t',
        }

        # Sub-period stability (only compute once per target)
        sub_idx = np.where(oos_dates_v >= SUB_PERIOD_SPLIT)[0]
        if len(sub_idx) > 50 and len(sub_idx) < n_valid - 50:
            split = int(sub_idx[0])
            sub_a = slice(0, split)
            sub_b = slice(split, n_valid)
            sub_qlike = {}
            for m in model_keys:
                fc = forecasts[m][valid_mask]
                sub_qlike[m] = {
                    'early': float(qlike(actual[sub_a], fc[sub_a])),
                    'late': float(qlike(actual[sub_b], fc[sub_b])),
                    'n_early': int(split),
                    'n_late': int(n_valid - split),
                }
            tgt_res['sub_period_qlike'] = sub_qlike
            for m in ['M2_GJR_t', 'M3_GAS_t']:
                beat_early = sub_qlike[m]['early'] < sub_qlike['M1_GJR_N']['early']
                beat_late = sub_qlike[m]['late'] < sub_qlike['M1_GJR_N']['late']
                tgt_res['dm_tests'][f'{m}_vs_M1']['gate_subperiod_stable'] = bool(beat_early and beat_late)
                tgt_res['dm_tests'][f'{m}_vs_M1']['sub_early_beats'] = bool(beat_early)
                tgt_res['dm_tests'][f'{m}_vs_M1']['sub_late_beats'] = bool(beat_late)

        # Triple gate
        for key in ['M2_GJR_t_vs_M1', 'M3_GAS_t_vs_M1']:
            gates = tgt_res['dm_tests'].get(key, {})
            gates['triple_gate_PASS'] = bool(
                gates.get('gate_DM', False)
                and gates.get('gate_QLIKE_5pct', False)
                and gates.get('gate_subperiod_stable', False)
            )

        ticker_results['per_target'][tgt] = tgt_res

    all_results[ticker] = ticker_results

sys.stdout.flush()

# ============================================================
# CROSS-ASSET SUMMARY (Primary: Parkinson)
# ============================================================
print("\n" + "=" * 72)
print("CROSS-ASSET SUMMARY — primary target = Parkinson")
print("=" * 72)
print(f"\n{'Asset':<10} {'kurt':>8} {'M1 QL':>10} {'M2 QL':>10} {'M3 QL':>10} {'Best':>10}")
print("-" * 70)
for t in all_results:
    m = all_results[t]['per_target']['parkinson']['model_metrics']
    kurt = all_results[t]['kurtosis_excess']
    best = min(model_keys, key=lambda k: m[k]['QLIKE'] if m[k]['QLIKE'] else 1e9)
    print(f"{t:<10} {kurt:>8.2f} "
          f"{m['M1_GJR_N']['QLIKE']:>10.4f} "
          f"{m['M2_GJR_t']['QLIKE']:>10.4f} "
          f"{m['M3_GAS_t']['QLIKE']:>10.4f} {best:>10}")

print(f"\n{'Asset':<10} {'M2 vs M1':>20} {'M3 vs M1':>20} {'M3 vs M2':>20} (Parkinson)")
print("-" * 80)
for t in all_results:
    dm = all_results[t]['per_target']['parkinson']['dm_tests']
    def fmt(dd):
        if not dd: return 'n/a'
        marker = '***' if dd.get('significant_Harvey') else ('**' if dd.get('gate_DM') else ' ')
        gate = 'GATE' if dd.get('triple_gate_PASS') else ''
        return f"t={dd.get('DM_HLN_t',0):>5.2f}{marker}{gate:>5}"
    m2v = dm.get('M2_GJR_t_vs_M1', {})
    m3v = dm.get('M3_GAS_t_vs_M1', {})
    m32 = dm.get('M3_GAS_t_vs_M2_GJR_t', {})
    print(f"{t:<10} {fmt(m2v):>20} {fmt(m3v):>20} {fmt(m32):>20}")

# Triple gate summary (Parkinson)
print("\n--- TRIPLE GATE (DM |t|>2 + QLIKE >5% + sub-period stable) — Parkinson ---")
h1_pass = 0
for t in all_results:
    dm = all_results[t]['per_target']['parkinson']['dm_tests']
    m3_vs_m1 = dm.get('M3_GAS_t_vs_M1', {})
    if m3_vs_m1.get('triple_gate_PASS'):
        h1_pass += 1
        print(f"  {t}: M3 PASSES all 3 gates")
    else:
        print(f"  {t}: M3 FAILS "
              f"[DM={m3_vs_m1.get('gate_DM', False)}, "
              f"QL5={m3_vs_m1.get('gate_QLIKE_5pct', False)}, "
              f"sub={m3_vs_m1.get('gate_subperiod_stable', False)}]")
print(f"\nH1 (M3 beats M1 on >=2/4 commodities with triple gate): "
      f"{h1_pass}/{len(all_results)} — {'PASS' if h1_pass >= 2 else 'FAIL'}")

# Range vs close² QLIKE magnitude comparison (H2)
print("\n--- H2: Range QLIKE magnitudes vs r² magnitudes ---")
print(f"{'Asset':<10} {'r² M3':>10} {'Park M3':>10} {'GK M3':>10} {'RS M3':>10}")
for t in all_results:
    pt = all_results[t]['per_target']
    r2_ql = pt['r2_close']['model_metrics']['M3_GAS_t']['QLIKE']
    p_ql = pt['parkinson']['model_metrics']['M3_GAS_t']['QLIKE']
    gk_ql = pt['garman_klass']['model_metrics']['M3_GAS_t']['QLIKE']
    rs_ql = pt['rogers_satchell']['model_metrics']['M3_GAS_t']['QLIKE']
    print(f"{t:<10} {r2_ql:>10.4f} {p_ql:>10.4f} {gk_ql:>10.4f} {rs_ql:>10.4f}")

# Cross-proxy H1 count
print("\n--- Cross-proxy H1 count (how many assets PASS triple gate per proxy) ---")
for proxy in ['parkinson', 'garman_klass', 'rogers_satchell', 'r2_close']:
    cnt = 0
    for t in all_results:
        dm = all_results[t]['per_target'][proxy]['dm_tests']
        if dm.get('M3_GAS_t_vs_M1', {}).get('triple_gate_PASS'):
            cnt += 1
    print(f"  {proxy}: {cnt}/{len(all_results)} PASS")

sys.stdout.flush()

# ============================================================
# CHARTS
# ============================================================
colors = {'M1_GJR_N': '#2196F3', 'M2_GJR_t': '#4CAF50', 'M3_GAS_t': '#E91E63'}

# Chart 1: QLIKE comparison — 4 assets × 4 targets × 3 models (big picture)
fig, axes = plt.subplots(1, 4, figsize=(18, 5), sharey=False)
target_labels = {'r2_close': 'r² (close²)', 'parkinson': 'Parkinson',
                 'garman_klass': 'Garman-Klass', 'rogers_satchell': 'Rogers-Satchell'}
for j, proxy in enumerate(['r2_close', 'parkinson', 'garman_klass', 'rogers_satchell']):
    ax = axes[j]
    x = np.arange(len(all_results))
    width = 0.27
    for i, m in enumerate(model_keys):
        qs = [all_results[t]['per_target'][proxy]['model_metrics'][m]['QLIKE']
              for t in all_results]
        ax.bar(x + i * width, qs, width, label=m, color=colors[m], alpha=0.85)
    ax.set_xticks(x + width)
    ax.set_xticklabels(list(all_results.keys()), rotation=30, fontsize=8)
    ax.set_title(target_labels[proxy], fontsize=11)
    ax.grid(axis='y', alpha=0.3)
    if j == 0:
        ax.set_ylabel('QLIKE (lower = better)')
        ax.legend(fontsize=8, loc='upper right')
fig.suptitle('K1134: QLIKE by Target Proxy — GJR-N / GJR-t / GAS-t on Commodities\n(OOS 2021-2026)',
             fontsize=12)
plt.tight_layout()
chart1_path = os.path.join(SCRIPT_DIR, 'k1134_qlike_by_proxy.png')
plt.savefig(chart1_path, dpi=150)
plt.close()
print(f"\n  Chart 1: {chart1_path}")

# Chart 2: DM-HLN t heatmap for M3 vs M1 across proxies and assets
fig, ax = plt.subplots(figsize=(9, 5))
proxies_ord = ['r2_close', 'parkinson', 'garman_klass', 'rogers_satchell']
tkrs = list(all_results.keys())
ts = np.zeros((len(tkrs), len(proxies_ord)))
for i, t in enumerate(tkrs):
    for j, pr in enumerate(proxies_ord):
        ts[i, j] = all_results[t]['per_target'][pr]['dm_tests'].get(
            'M3_GAS_t_vs_M1', {}).get('DM_HLN_t', 0.0)
im = ax.imshow(ts, cmap='RdYlGn', vmin=-3, vmax=3, aspect='auto')
ax.set_xticks(range(len(proxies_ord)))
ax.set_xticklabels([target_labels[p] for p in proxies_ord], rotation=15, fontsize=9)
ax.set_yticks(range(len(tkrs)))
ax.set_yticklabels(tkrs)
for i in range(len(tkrs)):
    for j in range(len(proxies_ord)):
        ax.text(j, i, f"{ts[i,j]:.2f}", ha='center', va='center',
                color='black', fontsize=9)
plt.colorbar(im, ax=ax, label='DM-HLN t (positive = GAS-t wins)')
ax.set_title('K1134: DM-HLN t — M3 GAS-t vs M1 GJR-Normal across 4 proxies')
plt.tight_layout()
chart2_path = os.path.join(SCRIPT_DIR, 'k1134_dm_heatmap.png')
plt.savefig(chart2_path, dpi=150)
plt.close()
print(f"  Chart 2: {chart2_path}")

# Chart 3: QLIKE absolute magnitude — r² vs Parkinson (scatter)
fig, ax = plt.subplots(figsize=(7, 6))
for m in model_keys:
    xs = [all_results[t]['per_target']['r2_close']['model_metrics'][m]['QLIKE']
          for t in all_results]
    ys = [all_results[t]['per_target']['parkinson']['model_metrics'][m]['QLIKE']
          for t in all_results]
    ax.scatter(xs, ys, label=m, color=colors[m], s=80, alpha=0.85)
    for i, tname in enumerate(list(all_results.keys())):
        ax.annotate(tname, (xs[i], ys[i]), fontsize=8, alpha=0.7,
                    xytext=(4, 4), textcoords='offset points')
lim_lo = 0
lim_hi = max(max([all_results[t]['per_target']['r2_close']['model_metrics'][m]['QLIKE']
                  for t in all_results for m in model_keys]),
             max([all_results[t]['per_target']['parkinson']['model_metrics'][m]['QLIKE']
                  for t in all_results for m in model_keys])) * 1.1
ax.plot([lim_lo, lim_hi], [lim_lo, lim_hi], 'k--', alpha=0.4, label='y = x')
ax.set_xlabel('QLIKE with r² (close²) proxy')
ax.set_ylabel('QLIKE with Parkinson proxy')
ax.set_title('K1134: QLIKE Magnitude — r² vs Parkinson\n(below y=x ⇒ Parkinson gives smaller QLIKE)')
ax.legend()
ax.grid(alpha=0.3)
plt.tight_layout()
chart3_path = os.path.join(SCRIPT_DIR, 'k1134_proxy_magnitude.png')
plt.savefig(chart3_path, dpi=150)
plt.close()
print(f"  Chart 3: {chart3_path}")

# ============================================================
# SAVE RESULTS
# ============================================================
results_output = {
    'experiment_id': 'K1134',
    'title': 'Range-based volatility proxy + GAS-t on commodities',
    'description': ('Re-evaluate K1129 NULL using Parkinson/Garman-Klass/'
                    'Rogers-Satchell daily variance proxies. Test whether a '
                    'lower-variance proxy reveals GAS-t advantage hidden under r².'),
    'methodology': {
        'models': ['M1 GJR-GARCH Normal', 'M2 GJR-GARCH Student-t', 'M3 GAS-t'],
        'assets': list(ASSETS.keys()),
        'targets': targets,
        'target_details': {
            'parkinson': '(log H/L)² / (4 log 2) [Parkinson 1980, primary target]',
            'garman_klass': '0.5 [log H/L]² - (2 log 2 - 1) [log C/O]² [GK 1980]',
            'rogers_satchell': 'log(H/C) log(H/O) + log(L/C) log(L/O) [RS 1991]',
            'r2_close': 'Close-to-close squared return [K1129 baseline for comparison]',
        },
        'oos_start': OOS_START,
        'sub_period_split': SUB_PERIOD_SPLIT,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'evaluation_target': 'Parkinson primary; GK+RS robustness; r²_close for direct K1129 comparison',
        'metrics': ['QLIKE (Patton 2011, proxy-robust for ranking)',
                    'DM-HLN test (Harvey-Leybourne-Newbold 1997)',
                    'Spearman rank correlation',
                    'Triple gate: DM |t|>2 + QLIKE>5% + sub-period stable'],
        'dm_threshold_harvey': 'Harvey (2016) |t| > 3.0 (reported separately)',
    },
    'data_source': 'yfinance (Open/High/Low/Close)',
    'seed': 42,
    'references': [
        'Parkinson (1980) J Business 53(1):61-65',
        'Garman & Klass (1980) J Business 53(1):67-78',
        'Rogers & Satchell (1991) Ann Appl Prob 1(4):504-512',
        'Patton (2011) J Econometrics 160:246-256 — QLIKE proxy-robust',
        'Creal, Koopman, Lucas (2013) JASA 108(501):1-18',
        'Harvey-Leybourne-Newbold (1997) IJF 13:281-291',
        'Harvey (2016) — multiple-testing |t|>3.0',
    ],
    'prior_experiments': {
        'K437': 'SPY r²: GAS-t underperforms',
        'K1038': 'SPY/QQQ/GLD/0050.TW r²: 4/4 NULL',
        'K1129': 'USO/GLD/UNG/BTC r²: 4/4 NULL (triple gate)',
    },
    'results': all_results,
    'charts': ['k1134_qlike_by_proxy.png', 'k1134_dm_heatmap.png',
               'k1134_proxy_magnitude.png'],
    'created_at': datetime.now(timezone.utc).isoformat(),
}

results_path = os.path.join(SCRIPT_DIR, 'k1134_results.json')
with open(results_path, 'w') as f:
    json.dump(results_output, f, indent=2, default=str)
print(f"\n  Results saved: {results_path}")
print("\nK1134 complete.")
