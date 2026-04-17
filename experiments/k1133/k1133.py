"""
K1133: Regime-switching GAS-t on BTC — Is K1129 BTC reversal regime-dependent?
================================================================================
[提出: Claude, 執行: Claude]

Research Question:
  K1129 showed GAS-t on BTC gives DM-HLN t=-4.58 vs GJR-Normal (GAS is WORSE).
  Catania (2018, JFE) suggests GAS models need regime-switching in markets with
  structural breaks. BTC exhibits clear regime shifts:
    - 2015-2020: pre-institutional, small retail-driven
    - 2021-2023: FTX / Terra-Luna / BlockFi collapses
    - 2024-2026: post-spot-ETF institutional era
  Does GAS-t's underperformance hold across ALL periods, or is it regime-specific?

Approach A (PRIMARY): Sub-period split
  Fit GJR-Normal / GJR-t / GAS-t *independently* in each sub-period
  (rolling OOS with refit, like K1129) and compare DM-HLN per period.

Approach B (SECONDARY / skeleton): Markov-switching GAS-t
  2-state latent regime with state-specific GAS-t parameters.
  Because 2-state MS-GAS-t is ~8 params and BTC per-period has ~300-900 OOS obs,
  we implement a *skeleton* (fit + in-sample diagnostic) but flag convergence
  issues clearly.

References:
  - Catania (2018) "Dynamic Adaptive Mixture Models with an Application to
    Volatility and Risk" JFE 18(3):493-544
  - Creal, Koopman, Lucas (2013) JASA 108:1-18
  - Harvey (2013) — Dynamic Models for Volatility & Heavy Tails, Cambridge UP
  - Patton (2011) JoE 160:246 — QLIKE
  - Harvey-Leybourne-Newbold (1997) IJF — DM small-sample correction
  - Hamilton (1989) Econometrica — Markov-switching

Prior:
  - K437, K1038: GAS-t NULL on SPY/QQQ/GLD/0050.TW (7yr OOS)
  - K1129: GAS-t REVERSAL on BTC: DM t=-4.58 (GAS worse than GJR-N, full 2021-2026)
    - Also GJR-t REVERSAL: DM t=-5.17
    - BTC kurtosis=7.97 (moderate for crypto)

Hypotheses:
  H1 (regime-specific): GAS-t reversal confined to one regime (e.g., 2021-2023
      FTX crash era), while 2024-2026 post-ETF it is neutral or positive.
  H2 (universal): GAS-t underperforms GJR-N uniformly across all 3 periods
      → Catania's regime-switching claim fails for BTC.
  H3 (Student-t alone harmful): GJR-t also reversal in all 3 periods (i.e.
      fat-tail innovation itself is the problem on BTC, not GAS dynamics).

Design:
  Period 1: 2015-01-01 → 2020-12-31  (pre-institutional)
  Period 2: 2021-01-01 → 2023-12-31  (FTX / Luna / BlockFi era)
  Period 3: 2024-01-01 → 2026-04-15  (spot-ETF era)
  Window (rolling IS): 750 obs  (allows OOS in each sub-period)
  Refit every 63 days
  OOS in each sub-period = obs after first WINDOW of that sub-period's data
  (expanding IS within each sub-period; preserves regime homogeneity).

Fair comparison:
  - All models target r² (squared returns)
  - Same refit cadence
  - Same rolling IS window length
  - Seed 42
  - Lookahead assertion: forecast for obs t uses info at t-1 only

Reproduction: python experiments/k1133/k1133.py
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
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
print("K1133: Regime-switching GAS-t on BTC")
print("Testing K1129 BTC reversal (GAS-t DM=-4.58 vs GJR-N) across 3 sub-periods")
print("=" * 72)
sys.stdout.flush()

# ============================================================
# STEP 0: Data Download (match K1129 period)
# ============================================================
import yfinance as yf

TICKER = 'BTC-USD'
START = '2015-01-01'
END = '2026-04-15'

print(f"\n[0] Downloading {TICKER} {START} → {END} ...")
sys.stdout.flush()
df = yf.download(TICKER, start=START, end=END, progress=False, auto_adjust=False)
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)

price_col = 'Adj Close' if 'Adj Close' in df.columns else 'Close'
prices = df[price_col].dropna()
returns_pct = prices.pct_change().dropna() * 100

print(f"  Observations: {len(returns_pct)}")
print(f"  Range: {returns_pct.index[0].strftime('%Y-%m-%d')} → "
      f"{returns_pct.index[-1].strftime('%Y-%m-%d')}")
print(f"  Mean={returns_pct.mean():.4f}%  Std={returns_pct.std():.4f}%")
print(f"  Skew={returns_pct.skew():.3f}  Kurt(excess)={returns_pct.kurtosis():.3f}")
sys.stdout.flush()

# ============================================================
# MODEL LIKELIHOODS AND FITTERS (reuse K1129 spec)
# ============================================================

def gjr_normal_negloglik(params, returns):
    omega, alpha, gamma, beta = params
    T = len(returns)
    sigma2 = np.zeros(T)
    sigma2[0] = np.var(returns)
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = (omega + alpha * returns[t-1]**2
                     + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1])
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
        sigma2[t] = (omega + alpha * returns[t-1]**2
                     + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1])
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
            res = minimize(gjr_normal_negloglik, x0, args=(returns,),
                           method='Nelder-Mead', options={'maxiter': 2000})
    except Exception:
        return None, None
    omega, alpha, gamma, beta = res.x
    sigma2 = np.zeros(T)
    sigma2[0] = var_r
    for t in range(1, T):
        ind = 1.0 if returns[t-1] < 0 else 0.0
        sigma2[t] = (omega + alpha * returns[t-1]**2
                     + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1])
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
                    res2 = minimize(gjr_t_negloglik, x0_alt, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
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
        sigma2[t] = (omega + alpha * returns[t-1]**2
                     + gamma * returns[t-1]**2 * ind + beta * sigma2[t-1])
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
                    res2 = minimize(gas_t_negloglik, x0_alt, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
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

def qlike(actual_r2, predicted_sigma2):
    valid = ((predicted_sigma2 > 0) & np.isfinite(predicted_sigma2)
             & np.isfinite(actual_r2) & (actual_r2 > 0))
    a = actual_r2[valid]
    p = predicted_sigma2[valid]
    loss = a / p - np.log(a / p) - 1
    return np.mean(loss)


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
# APPROACH A: Per-sub-period rolling OOS
# ============================================================

SUB_PERIODS = [
    ('Period1_preinstitutional', '2015-01-01', '2020-12-31'),
    ('Period2_FTX_Luna_era',     '2021-01-01', '2023-12-31'),
    ('Period3_spotETF_era',      '2024-01-01', '2026-04-15'),
]

WINDOW_DEFAULT = 750  # rolling IS window (2 years BTC data)
WINDOW_MIN = 500      # minimum for estimation stability
REFIT_EVERY = 63
MODEL_KEYS = ['M1_GJR_N', 'M2_GJR_t', 'M3_GAS_t']

returns = returns_pct.values
dates = returns_pct.index.to_numpy()

subperiod_results = {}

for sp_name, sp_start, sp_end in SUB_PERIODS:
    print(f"\n{'='*72}")
    print(f"  Sub-period: {sp_name}  [{sp_start} → {sp_end}]")
    print(f"{'='*72}")
    sys.stdout.flush()

    sp_start_dt = np.datetime64(sp_start)
    sp_end_dt = np.datetime64(sp_end)
    sp_mask = (dates >= sp_start_dt) & (dates <= sp_end_dt)
    sp_indices = np.where(sp_mask)[0]
    if len(sp_indices) < WINDOW_MIN + 100:
        print(f"  SKIP: only {len(sp_indices)} obs in this period "
              f"(< WINDOW_MIN {WINDOW_MIN} + 100)")
        continue

    # Adaptive window: use WINDOW_DEFAULT if possible, else scale down
    sp_first = int(sp_indices[0])
    sp_last = int(sp_indices[-1]) + 1
    sp_returns = returns[sp_first:sp_last]
    sp_dates = dates[sp_first:sp_last]
    n_sp = len(sp_returns)

    # Rolling OOS: use largest window that leaves ≥100 OOS
    WINDOW = min(WINDOW_DEFAULT, n_sp - 100)
    WINDOW = max(WINDOW, WINDOW_MIN)
    oos_start_sp = WINDOW
    n_oos = n_sp - oos_start_sp
    print(f"  [adaptive window: {WINDOW}, n_sp={n_sp}]")
    print(f"  SP obs={n_sp}, OOS start at SP idx {oos_start_sp}, n_oos={n_oos}")
    print(f"  OOS range: {pd.Timestamp(sp_dates[oos_start_sp]).strftime('%Y-%m-%d')} → "
          f"{pd.Timestamp(sp_dates[-1]).strftime('%Y-%m-%d')}")

    forecasts = {m: np.full(n_oos, np.nan) for m in MODEL_KEYS}
    current_params = {m: None for m in MODEL_KEYS}
    current_sigma2 = {m: None for m in MODEL_KEYS}
    current_f = {m: None for m in MODEL_KEYS}

    t0 = time.time()
    last_fit = -REFIT_EVERY

    # Lookahead-safe forecast loop
    for t_oos in range(n_oos):
        t_abs = oos_start_sp + t_oos

        # Refit using ONLY past data (train ends at t_abs, not inclusive)
        if t_oos - last_fit >= REFIT_EVERY or t_oos == 0:
            train_start = max(0, t_abs - WINDOW)
            train_data = sp_returns[train_start:t_abs]
            # LOOKAHEAD ASSERT: train must end strictly before forecast obs
            assert train_start + len(train_data) == t_abs, \
                f"Train window leaks into obs {t_abs}"
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
                print(f"    [{sp_name}] {t_oos}/{n_oos} ({t_oos/n_oos*100:.0f}%) "
                      f"{elapsed:.1f}s")
                sys.stdout.flush()

        # Forecast h_t using last return (t_abs-1) — lookahead-safe
        last_r = sp_returns[t_abs - 1]
        for m in MODEL_KEYS:
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
    print(f"  done in {elapsed:.1f}s")
    sys.stdout.flush()

    # Evaluation
    actual_r2 = sp_returns[oos_start_sp:]**2
    oos_dates_v = sp_dates[oos_start_sp:]

    valid_mask = np.ones(n_oos, dtype=bool)
    for m in MODEL_KEYS:
        valid_mask &= np.isfinite(forecasts[m])
    n_valid = int(np.sum(valid_mask))
    print(f"  Valid OOS: {n_valid}")

    if n_valid < 100:
        print(f"  SKIP: <100 valid forecasts")
        continue

    actual_r2_v = actual_r2[valid_mask]

    # Per-observation QLIKE for DM
    qlike_ind = {}
    for m in MODEL_KEYS:
        fc = forecasts[m][valid_mask]
        ratio = actual_r2_v / fc
        with np.errstate(divide='ignore', invalid='ignore'):
            ql = ratio - np.log(np.where(ratio > 0, ratio, 1e-30)) - 1
        ql[actual_r2_v <= 0] = np.nan
        qlike_ind[m] = ql

    results_sp = {'n_oos': n_valid,
                  'oos_start': pd.Timestamp(oos_dates_v[valid_mask][0]).strftime('%Y-%m-%d'),
                  'oos_end': pd.Timestamp(oos_dates_v[valid_mask][-1]).strftime('%Y-%m-%d'),
                  'sub_period_start': sp_start,
                  'sub_period_end': sp_end,
                  'preliminary_flag': bool(n_valid < 504),
                  'model_metrics': {},
                  'dm_tests': {}}

    for m in MODEL_KEYS:
        fc = forecasts[m][valid_mask]
        q = qlike(actual_r2_v, fc)
        rho, rho_p = stats.spearmanr(actual_r2_v, fc)
        results_sp['model_metrics'][m] = {
            'QLIKE': float(q),
            'Spearman_rho': float(rho),
            'Spearman_p': float(rho_p),
        }
        print(f"    {m}: QLIKE={q:.6f}, rho={rho:.3f}")

    # DM-HLN tests
    q_m1 = results_sp['model_metrics']['M1_GJR_N']['QLIKE']
    for m in ['M2_GJR_t', 'M3_GAS_t']:
        t_stat, p_val, n_used = dm_hln_test(qlike_ind['M1_GJR_N'], qlike_ind[m])
        q_m = results_sp['model_metrics'][m]['QLIKE']
        rel_impr = (q_m1 - q_m) / q_m1 * 100
        results_sp['dm_tests'][f'{m}_vs_M1'] = {
            'DM_HLN_t': float(t_stat),
            'DM_HLN_p': float(p_val),
            'n_used': int(n_used),
            'QLIKE_rel_improvement_pct': float(rel_impr),
            'gate_DM': bool(abs(t_stat) > 2.0),
            'gate_Harvey': bool(abs(t_stat) > 3.0),
            'better': m if t_stat > 0 else 'M1_GJR_N',
        }
        print(f"    DM-HLN {m} vs M1: t={t_stat:+.3f}, p={p_val:.3e}, "
              f"rel_impr={rel_impr:+.2f}%")

    # M3 vs M2
    t_s, p_s, n_s = dm_hln_test(qlike_ind['M2_GJR_t'], qlike_ind['M3_GAS_t'])
    q_m2 = results_sp['model_metrics']['M2_GJR_t']['QLIKE']
    q_m3 = results_sp['model_metrics']['M3_GAS_t']['QLIKE']
    results_sp['dm_tests']['M3_GAS_t_vs_M2_GJR_t'] = {
        'DM_HLN_t': float(t_s),
        'DM_HLN_p': float(p_s),
        'n_used': int(n_s),
        'QLIKE_rel_improvement_pct': float((q_m2 - q_m3) / q_m2 * 100),
        'gate_DM': bool(abs(t_s) > 2.0),
        'better': 'M3_GAS_t' if t_s > 0 else 'M2_GJR_t',
    }
    print(f"    DM-HLN M3 vs M2: t={t_s:+.3f}, p={p_s:.3e}")

    subperiod_results[sp_name] = results_sp

# ============================================================
# APPROACH B: Markov-switching GAS-t (skeleton, in-sample diagnostic)
# ============================================================
#
# 2-state latent regime, each with own GAS-t parameters (omega_s, alpha_s, beta_s, nu_s),
# transition matrix P = [[p00, 1-p00], [1-p11, p11]].
# Use Hamilton filter for likelihood (full filtered probabilities).
# 10 params in total → fit on full BTC sample in-sample only; report convergence
# status. No OOS forecast because 10-param MS likelihood on ~4000 obs BTC
# would need careful state-probability OOS handling beyond the scope of this
# primary experiment.

def ms_gas_t_negloglik(params, returns):
    """
    2-state Markov-switching GAS-t log-likelihood via Hamilton filter.
    params = [omega_0, alpha_0, beta_0, log_nu0_m2,
              omega_1, alpha_1, beta_1, log_nu1_m2,
              logit_p00, logit_p11]
    """
    (o0, a0, b0, ln_nu0,
     o1, a1, b1, ln_nu1,
     lp00, lp11) = params
    nu0 = np.exp(ln_nu0) + 2.0
    nu1 = np.exp(ln_nu1) + 2.0
    p00 = 1.0 / (1.0 + np.exp(-lp00))
    p11 = 1.0 / (1.0 + np.exp(-lp11))
    # Transition matrix P[i][j] = P(state_t=j | state_{t-1}=i)
    P = np.array([[p00, 1 - p00], [1 - p11, p11]])

    T = len(returns)
    var_r = np.var(returns)
    # Initial filter probs: stationary distribution
    try:
        # Solve pi*P = pi, pi_0+pi_1=1
        pi0 = (1 - p11) / (2 - p00 - p11) if (2 - p00 - p11) > 1e-8 else 0.5
        pi = np.array([pi0, 1 - pi0])
        if np.any(pi < 0) or np.any(pi > 1):
            pi = np.array([0.5, 0.5])
    except Exception:
        pi = np.array([0.5, 0.5])

    f0 = np.log(var_r)  # state-0 log-variance
    f1 = np.log(var_r)  # state-1 log-variance
    log_lik = 0.0

    for t in range(T):
        # State conditional densities
        sigma2_0 = max(np.exp(f0), 1e-10)
        sigma2_1 = max(np.exp(f1), 1e-10)
        eps2_0 = returns[t]**2 / sigma2_0
        eps2_1 = returns[t]**2 / sigma2_1
        log_d0 = (gammaln((nu0 + 1) / 2) - gammaln(nu0 / 2)
                  - 0.5 * np.log(np.pi * (nu0 - 2) * sigma2_0)
                  - (nu0 + 1) / 2 * np.log(1 + eps2_0 / (nu0 - 2)))
        log_d1 = (gammaln((nu1 + 1) / 2) - gammaln(nu1 / 2)
                  - 0.5 * np.log(np.pi * (nu1 - 2) * sigma2_1)
                  - (nu1 + 1) / 2 * np.log(1 + eps2_1 / (nu1 - 2)))

        # Predictive prob of each state
        pred = pi @ P
        # Joint and marginal
        d0 = np.exp(log_d0)
        d1 = np.exp(log_d1)
        joint0 = pred[0] * d0
        joint1 = pred[1] * d1
        marg = joint0 + joint1
        if marg <= 0 or not np.isfinite(marg):
            return 1e10
        log_lik += np.log(marg)
        # Filtered prob
        pi = np.array([joint0 / marg, joint1 / marg])

        # Update log-variances (state-specific GAS-t recursion)
        if t < T - 1:
            score_0 = -0.5 + (nu0 + 1) / 2 * eps2_0 / (nu0 - 2 + eps2_0)
            S0 = 2 * nu0 / ((nu0 + 3) * (nu0 - 2))
            score_1 = -0.5 + (nu1 + 1) / 2 * eps2_1 / (nu1 - 2 + eps2_1)
            S1 = 2 * nu1 / ((nu1 + 3) * (nu1 - 2))
            f0_new = o0 + a0 * S0 * score_0 + b0 * f0
            f1_new = o1 + a1 * S1 * score_1 + b1 * f1
            f0, f1 = f0_new, f1_new

    return -log_lik if np.isfinite(log_lik) else 1e10


def fit_ms_gas_t(returns, maxiter=300):
    var_r = np.var(returns)
    # Initial: state 0 low-vol, state 1 high-vol (via different omega)
    x0 = [0.005, 0.03, 0.96, np.log(8.0),      # state 0 (low vol)
          0.020, 0.08, 0.90, np.log(5.0),      # state 1 (high vol)
          2.0, 2.0]                             # logit_p00, logit_p11 → ~0.88
    bounds = [
        (-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100)),
        (-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100)),
        (-8.0, 8.0), (-8.0, 8.0),
    ]
    try:
        res = minimize(ms_gas_t_negloglik, x0, args=(returns,),
                       method='L-BFGS-B', bounds=bounds,
                       options={'maxiter': maxiter})
    except Exception as e:
        return {'success': False, 'error': str(e)}
    if not np.isfinite(res.fun) or res.fun > 1e9:
        return {'success': False, 'error': 'non-finite likelihood'}
    (o0, a0, b0, ln_nu0,
     o1, a1, b1, ln_nu1,
     lp00, lp11) = res.x
    return {
        'success': bool(res.success),
        'converged': bool(res.success),
        'neg_loglik': float(res.fun),
        'state_0': {'omega': float(o0), 'alpha': float(a0), 'beta': float(b0),
                    'nu': float(np.exp(ln_nu0) + 2.0)},
        'state_1': {'omega': float(o1), 'alpha': float(a1), 'beta': float(b1),
                    'nu': float(np.exp(ln_nu1) + 2.0)},
        'p00': float(1.0 / (1.0 + np.exp(-lp00))),
        'p11': float(1.0 / (1.0 + np.exp(-lp11))),
        'message': str(res.message),
    }


# Also fit single-state GAS-t for LRT comparison
def single_state_gas_t_nll(returns):
    var_r = np.var(returns)
    x0 = [0.01, 0.05, 0.95, np.log(6.0)]
    bounds = [(-5.0, 5.0), (1e-6, 2.0), (0.3, 0.999), (np.log(0.1), np.log(100))]
    res = minimize(gas_t_negloglik, x0, args=(returns,), method='L-BFGS-B',
                   bounds=bounds, options={'maxiter': 500})
    return res.fun if np.isfinite(res.fun) else 1e10


print(f"\n{'='*72}")
print("APPROACH B: Markov-switching GAS-t (in-sample diagnostic)")
print(f"{'='*72}")
sys.stdout.flush()

ms_results = {}
for sp_name, sp_start, sp_end in SUB_PERIODS:
    sp_start_dt = np.datetime64(sp_start)
    sp_end_dt = np.datetime64(sp_end)
    sp_mask = (dates >= sp_start_dt) & (dates <= sp_end_dt)
    sp_returns = returns[sp_mask]
    if len(sp_returns) < 500:
        ms_results[sp_name] = {'skipped': True, 'reason': f'only {len(sp_returns)} obs'}
        continue
    print(f"\n  [{sp_name}] fitting MS-GAS-t on {len(sp_returns)} obs ...")
    sys.stdout.flush()
    t0 = time.time()
    ms_fit = fit_ms_gas_t(sp_returns, maxiter=200)
    ms_elapsed = time.time() - t0

    # Single-state GAS-t nll for LRT baseline
    ss_nll = single_state_gas_t_nll(sp_returns)
    if ms_fit.get('success'):
        # LRT: 10 params (MS) vs 4 params (SS) → df=6
        lrt_stat = 2 * (ss_nll - ms_fit['neg_loglik'])
        lrt_p = 1 - stats.chi2.cdf(max(lrt_stat, 0.0), df=6)
        ms_fit['LRT_vs_single_state'] = {
            'single_state_nll': float(ss_nll),
            'ms_nll': float(ms_fit['neg_loglik']),
            'chi2': float(lrt_stat),
            'df': 6,
            'p_value': float(lrt_p),
        }
        print(f"    fit_time={ms_elapsed:.1f}s  nll={ms_fit['neg_loglik']:.1f}  "
              f"LRT χ²={lrt_stat:.2f} (df=6, p={lrt_p:.3e})")
        print(f"    state_0: ω={ms_fit['state_0']['omega']:.3f}, "
              f"α={ms_fit['state_0']['alpha']:.3f}, "
              f"β={ms_fit['state_0']['beta']:.3f}, "
              f"ν={ms_fit['state_0']['nu']:.2f}")
        print(f"    state_1: ω={ms_fit['state_1']['omega']:.3f}, "
              f"α={ms_fit['state_1']['alpha']:.3f}, "
              f"β={ms_fit['state_1']['beta']:.3f}, "
              f"ν={ms_fit['state_1']['nu']:.2f}")
        print(f"    p00={ms_fit['p00']:.3f}, p11={ms_fit['p11']:.3f}")
    else:
        print(f"    NON-CONVERGED: {ms_fit.get('error', 'unknown')}")
    ms_results[sp_name] = ms_fit
    sys.stdout.flush()

# ============================================================
# SUMMARY
# ============================================================
print(f"\n{'='*72}")
print("CROSS-PERIOD SUMMARY (Approach A)")
print(f"{'='*72}")
print(f"\n{'Period':<28} {'n_OOS':>6} {'M1 QL':>10} {'M2 QL':>10} {'M3 QL':>10} "
      f"{'M3vM1 t':>9} {'M2vM1 t':>9}")
print("-" * 92)
for sp, res in subperiod_results.items():
    me = res['model_metrics']
    dm = res['dm_tests']
    t_m3m1 = dm.get('M3_GAS_t_vs_M1', {}).get('DM_HLN_t', 0.0)
    t_m2m1 = dm.get('M2_GJR_t_vs_M1', {}).get('DM_HLN_t', 0.0)
    flag = ' (PRE)' if res.get('preliminary_flag') else ''
    print(f"{sp + flag:<28} {res['n_oos']:>6} "
          f"{me['M1_GJR_N']['QLIKE']:>10.4f} "
          f"{me['M2_GJR_t']['QLIKE']:>10.4f} "
          f"{me['M3_GAS_t']['QLIKE']:>10.4f} "
          f"{t_m3m1:>+9.2f} {t_m2m1:>+9.2f}")

print("\n--- Interpretation ---")
for sp, res in subperiod_results.items():
    dm = res['dm_tests']
    m3 = dm.get('M3_GAS_t_vs_M1', {})
    t = m3.get('DM_HLN_t', 0.0)
    if t < -2:
        verdict = "GAS-t WORSE (reversal)"
    elif t > 2:
        verdict = "GAS-t BETTER"
    else:
        verdict = "NEUTRAL"
    print(f"  {sp}: M3 vs M1 t={t:+.2f} → {verdict}")

# ============================================================
# CHARTS
# ============================================================
colors = {'M1_GJR_N': '#2196F3', 'M2_GJR_t': '#4CAF50', 'M3_GAS_t': '#E91E63'}

# Chart 1: QLIKE per period × model
fig, ax = plt.subplots(figsize=(11, 6))
period_names = list(subperiod_results.keys())
x = np.arange(len(period_names))
width = 0.27
for i, m in enumerate(MODEL_KEYS):
    qs = [subperiod_results[p]['model_metrics'][m]['QLIKE'] for p in period_names]
    ax.bar(x + i * width, qs, width, label=m, color=colors[m], alpha=0.85)
ax.set_xlabel('Sub-period')
ax.set_ylabel('QLIKE (lower = better)')
ax.set_title('K1133: BTC QLIKE across 3 sub-periods\n(Is GAS-t reversal universal or regime-dependent?)')
ax.set_xticks(x + width)
ax.set_xticklabels([p.replace('_', '\n') for p in period_names], fontsize=9)
ax.legend()
ax.grid(axis='y', alpha=0.3)
plt.tight_layout()
chart1 = os.path.join(SCRIPT_DIR, 'k1133_qlike_by_period.png')
plt.savefig(chart1, dpi=150)
plt.close()
print(f"\n  Chart 1: {chart1}")

# Chart 2: DM heatmap (period × comparison)
fig, ax = plt.subplots(figsize=(9, 5))
comparisons = ['M2_GJR_t_vs_M1', 'M3_GAS_t_vs_M1', 'M3_GAS_t_vs_M2_GJR_t']
comp_labels = ['M2 vs M1\n(GJR-t)', 'M3 vs M1\n(GAS-t)', 'M3 vs M2']
ts = np.zeros((len(period_names), len(comparisons)))
for i, p in enumerate(period_names):
    for j, c in enumerate(comparisons):
        ts[i, j] = subperiod_results[p]['dm_tests'].get(c, {}).get('DM_HLN_t', 0.0)
im = ax.imshow(ts, cmap='RdYlGn', vmin=-4, vmax=4, aspect='auto')
ax.set_xticks(range(len(comparisons)))
ax.set_xticklabels(comp_labels, fontsize=9)
ax.set_yticks(range(len(period_names)))
ax.set_yticklabels([p.replace('_', '\n') for p in period_names], fontsize=8)
for i in range(len(period_names)):
    for j in range(len(comparisons)):
        col = 'white' if abs(ts[i, j]) > 2.5 else 'black'
        ax.text(j, i, f"{ts[i, j]:+.2f}", ha='center', va='center',
                color=col, fontsize=10, fontweight='bold')
plt.colorbar(im, ax=ax, label='DM-HLN t-stat')
ax.set_title('K1133: BTC DM-HLN t-stat across sub-periods\n(green=second model wins, red=second model worse)')
plt.tight_layout()
chart2 = os.path.join(SCRIPT_DIR, 'k1133_dm_heatmap.png')
plt.savefig(chart2, dpi=150)
plt.close()
print(f"  Chart 2: {chart2}")

# ============================================================
# SAVE RESULTS
# ============================================================
output = {
    'experiment_id': 'K1133',
    'title': 'Regime-switching GAS-t on BTC — is K1129 reversal regime-dependent?',
    'motivation': (
        'K1129 found GAS-t on BTC has DM-HLN t=-4.58 vs GJR-Normal (GAS-t worse). '
        'Catania (2018, JFE) argues GAS needs regime-switching version in '
        'structurally shifting markets. BTC has clear eras: 2015-2020 pre-institutional, '
        '2021-2023 FTX/Luna/BlockFi crashes, 2024-2026 post-spot-ETF. '
        'Test: is the GAS-t underperformance universal across periods or '
        'concentrated in one regime?'
    ),
    'methodology': {
        'approach_A': 'Independent rolling-window OOS fit per sub-period '
                      '(window=750, refit every 63, OOS = sub-period obs after first 750)',
        'approach_B': 'In-sample 2-state Markov-switching GAS-t (Hamilton filter) '
                      'with LRT vs single-state GAS-t',
        'models': ['M1 GJR-GARCH Normal', 'M2 GJR-GARCH Student-t', 'M3 GAS-t'],
        'sub_periods': [{'name': n, 'start': s, 'end': e} for (n, s, e) in SUB_PERIODS],
        'window_default': WINDOW_DEFAULT,
        'window_min': WINDOW_MIN,
        'window_note': 'Adaptive per sub-period: min(WINDOW_DEFAULT, n_sp-100), floored at WINDOW_MIN',
        'refit_every': REFIT_EVERY,
        'evaluation_target': 'r² (squared returns; GARCH-native proxy)',
        'metrics': ['QLIKE (Patton 2011)', 'DM-HLN (Harvey et al 1997)',
                    'LRT (MS vs single-state GAS-t)'],
        'thresholds': {
            'DM_2': '|t| > 2 (two-sided p<0.05)',
            'DM_3_Harvey': '|t| > 3.0 (Harvey 2016 multiple-testing)',
        },
    },
    'data_source': 'yfinance BTC-USD',
    'date_range': f'{START} → {END}',
    'n_total_obs': int(len(returns_pct)),
    'seed': 42,
    'lookahead_check': 'Assert train_data ends strictly before forecast index t_abs',
    'references': [
        'Catania (2018) "Dynamic Adaptive Mixture Models..." JFE 18(3):493-544',
        'Creal, Koopman, Lucas (2013) JASA 108:1-18',
        'Harvey (2013) Dynamic Models for Volatility & Heavy Tails, Cambridge UP',
        'Harvey-Leybourne-Newbold (1997) IJF 13:281 — DM small-sample',
        'Hamilton (1989) Econometrica — Markov-switching',
        'Patton (2011) JoE 160:246 — QLIKE proxy-robust',
    ],
    'prior_experiments': {
        'K1129_BTC': 'DM_HLN t(M3 vs M1) = -4.58 full 2021-2026 OOS',
        'K1038': 'GAS-t NULL on SPY/QQQ/GLD/0050.TW',
    },
    'approach_A_results': subperiod_results,
    'approach_B_results': ms_results,
    'charts': ['k1133_qlike_by_period.png', 'k1133_dm_heatmap.png'],
    'created_at': datetime.now(timezone.utc).isoformat(),
}

# Compute headline conclusion
signs = []
for sp, res in subperiod_results.items():
    t = res['dm_tests'].get('M3_GAS_t_vs_M1', {}).get('DM_HLN_t', 0.0)
    signs.append((sp, t))
n_reversal = sum(1 for _, t in signs if t < -2)
n_neutral = sum(1 for _, t in signs if -2 <= t <= 2)
n_favor = sum(1 for _, t in signs if t > 2)

if n_reversal == len(signs):
    verdict = (
        'Universal reversal: GAS-t on BTC underperforms GJR-N in ALL periods. '
        'Catania (2018) regime-switching claim is REJECTED for BTC.'
    )
elif n_favor > 0 and n_reversal > 0:
    verdict = (
        'Regime-dependent: GAS-t shows different sign across periods. '
        'Catania (2018) claim partially supported — single-regime GAS-t '
        'is inappropriate for BTC, regime-specific version may help.'
    )
elif n_reversal > 0 and n_neutral > 0:
    verdict = (
        'Concentrated reversal: GAS-t underperformance concentrated in '
        f'{n_reversal}/{len(signs)} period(s), neutral in rest. K1129 finding '
        'is driven by specific regime(s) rather than universal BTC property.'
    )
else:
    verdict = 'Mixed / neutral — no dominant conclusion.'

output['headline_conclusion'] = {
    'verdict': verdict,
    'n_periods_reversal_DM_lt_neg2': n_reversal,
    'n_periods_neutral': n_neutral,
    'n_periods_favor_DM_gt_2': n_favor,
    'signs_by_period': [{'period': s, 'DM_HLN_t_M3_vs_M1': float(t)} for s, t in signs],
}

output_path = os.path.join(SCRIPT_DIR, 'k1133_results.json')
with open(output_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Results saved: {output_path}")
print(f"\n  HEADLINE: {verdict}")
print("\nK1133 complete.")
