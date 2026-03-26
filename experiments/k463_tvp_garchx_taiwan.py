"""
K463: Time-Varying Parameter GARCH-X for Taiwan (TVP Approaches)
================================================================
[提出: 用戶, 執行: Claude]

背景:
- K461: SSVS 選出 SPY_ret (PIP=1.000) 但 QLIKE 不改善 (mean vs variance disconnect)
- K462: GARCH-X(VIX) IS t=3.58 但 OOS QLIKE +7.1% 更差
- 問題: rolling corr(SPY,TW) 從 -0.02 到 0.86 劇烈波動 → 固定 delta 無法適應
- 本實驗: 用簡單的 adaptive/rolling/EWMA 方法讓 delta 隨時間變化

文獻:
- Creal et al. (2013) GAS: score-driven time-varying parameters
- Engle & Rangel (2008): Spline-GARCH for slowly-moving component
- K462: rolling corr SPY-TW unstable (range -0.02 to 0.86)

Models:
1. GJR baseline（台股）
2. Fixed GARCH-X(VIX²) — K462 null result baseline
3. Rolling GARCH-X — 每 63 天重估 delta（rolling window = 500）
4. Adaptive delta — VIX<20 用 delta_low, VIX≥20 用 delta_high
5. EWMA delta — delta_t = λ·delta_{t-1} + (1-λ)·delta_local
6. SPY realized vol proxy — σ²_tw = a + b·RV_spy + c·h_{t-1}（直接傳遞）

Data: 0050.TW + SPY + ^VIX (yfinance)
OOS: 2023-01-01 ~ 2024-12-31
Window: 2000, refit every 21 days
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy import stats
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox
import yfinance as yf
import json, time, warnings

warnings.filterwarnings('ignore')
np.random.seed(42)

# ============================================================
# CORE GARCH FUNCTIONS
# ============================================================

def gjr_filter(params, returns):
    """GJR-GARCH(1,1) filter. params: [omega, alpha, gamma, beta]"""
    omega, alpha, gamma_p, beta = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        lev = float(returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + gamma_p * lev + beta * h[t-1]
        h[t] = max(h[t], 1e-8)
    return h

def gjr_negll(params, returns):
    omega, alpha, gamma_p, beta = params
    if omega < 1e-8 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    if alpha + gamma_p/2 + beta >= 1.0:
        return 1e10
    h = gjr_filter(params, returns)
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

def gjr_x1_filter(params, returns, X1):
    """GJR-GARCH-X with 1 exogenous variable. params: [omega, alpha, gamma, beta, delta1]"""
    omega, alpha, gamma_p, beta, delta1 = params
    T = len(returns)
    h = np.zeros(T)
    h[0] = np.var(returns)
    for t in range(1, T):
        lev = float(returns[t-1] < 0) * returns[t-1]**2
        h[t] = omega + alpha * returns[t-1]**2 + gamma_p * lev + beta * h[t-1] + delta1 * X1[t-1]
        h[t] = max(h[t], 1e-8)
    return h

def gjr_x1_negll(params, returns, X1):
    omega, alpha, gamma_p, beta, delta1 = params
    if omega < 1e-8 or alpha < 0 or gamma_p < 0 or beta < 0:
        return 1e10
    if alpha + gamma_p/2 + beta >= 1.0:
        return 1e10
    h = gjr_x1_filter(params, returns, X1)
    ll = -0.5 * np.sum(np.log(h) + returns**2 / h)
    return -ll if np.isfinite(ll) else 1e10

# ============================================================
# FITTING FUNCTIONS
# ============================================================

def fit_gjr(returns, n_starts=3):
    var0 = np.var(returns)
    bounds = [(1e-8, var0*2), (1e-8, 0.5), (1e-8, 0.5), (1e-8, 0.999)]
    starts = [
        [var0*0.05, 0.05, 0.05, 0.90],
        [var0*0.02, 0.03, 0.08, 0.92],
        [var0*0.10, 0.08, 0.03, 0.85],
    ]
    best = None
    for x0 in starts[:n_starts]:
        try:
            r = minimize(gjr_negll, x0, args=(returns,), method='L-BFGS-B',
                         bounds=bounds, options={'maxiter': 500, 'ftol': 1e-12})
            if best is None or r.fun < best.fun:
                best = r
        except:
            pass
    if best is None or best.fun > 1e9:
        return None
    p = best.x
    return {
        'params': {'omega': p[0], 'alpha': p[1], 'gamma': p[2], 'beta': p[3]},
        'persistence': p[1] + p[2]/2 + p[3],
        'converged': best.success, 'nll': best.fun,
        'h': gjr_filter(p, returns), 'n_params': 4,
        'loglik': -best.fun,
        'aic': 2*best.fun + 2*4, 'bic': 2*best.fun + 4*np.log(len(returns))
    }

def fit_gjr_x1(returns, X1, n_starts=4):
    var0 = np.var(returns)
    bounds = [(1e-8, var0*2), (1e-8, 0.5), (1e-8, 0.5), (1e-8, 0.999), (-1.0, 1.0)]
    starts = [
        [var0*0.05, 0.05, 0.05, 0.88, 0.01],
        [var0*0.02, 0.03, 0.08, 0.90, 0.05],
        [var0*0.10, 0.08, 0.03, 0.85, 0.10],
        [var0*0.05, 0.05, 0.05, 0.88, -0.01],
    ]
    best = None
    for x0 in starts[:n_starts]:
        try:
            r = minimize(gjr_x1_negll, x0, args=(returns, X1), method='L-BFGS-B',
                         bounds=bounds, options={'maxiter': 500, 'ftol': 1e-12})
            if best is None or r.fun < best.fun:
                best = r
        except:
            pass
    if best is None or best.fun > 1e9:
        return None
    p = best.x
    return {
        'params': {'omega': p[0], 'alpha': p[1], 'gamma': p[2], 'beta': p[3], 'delta1': p[4]},
        'persistence': p[1] + p[2]/2 + p[3],
        'converged': best.success, 'nll': best.fun,
        'h': gjr_x1_filter(p, returns, X1), 'n_params': 5,
        'loglik': -best.fun,
        'aic': 2*best.fun + 2*5, 'bic': 2*best.fun + 5*np.log(len(returns))
    }

# ============================================================
# DATA LOADING
# ============================================================
print("=" * 60)
print("K463: Time-Varying Parameter GARCH-X for Taiwan")
print("=" * 60)

t0 = time.time()

# Download data
print("\n[1] Loading data...")
tw = yf.download("0050.TW", start="2008-01-01", end="2026-03-26", progress=False)
spy = yf.download("SPY", start="2008-01-01", end="2026-03-26", progress=False)
vix = yf.download("^VIX", start="2008-01-01", end="2026-03-26", progress=False)

# Handle multi-level columns
for df in [tw, spy, vix]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Returns (%)
tw_ret = tw['Close'].pct_change().dropna() * 100
spy_ret = spy['Close'].pct_change().dropna() * 100
vix_close = vix['Close'].dropna()

# Filter out extreme outliers (data errors like split artifacts)
# 0050.TW has a -75% return on 2014-01-02 which is a data error
extreme_mask = tw_ret.abs() > 30  # no single day should move >30%
if extreme_mask.any():
    n_extreme = extreme_mask.sum()
    print(f"   WARNING: Removing {n_extreme} extreme return(s) >30%: {tw_ret[extreme_mask].to_dict()}")
    tw_ret = tw_ret[~extreme_mask]

# Align dates
common = tw_ret.index.intersection(spy_ret.index).intersection(vix_close.index)
tw_ret = tw_ret.loc[common]
spy_ret = spy_ret.loc[common]
vix_close = vix_close.loc[common]

# Construct exogenous variables
vix_var = vix_close**2 / 252  # VIX² scaled to daily
spy_r2 = spy_ret**2  # SPY squared return as realized vol proxy

# 5-day rolling realized vol of SPY (for Model 6)
spy_rv5 = spy_ret.rolling(5).var()  # 5-day realized variance

print(f"   Total obs: {len(tw_ret)}")
print(f"   Date range: {tw_ret.index[0].date()} to {tw_ret.index[-1].date()}")

# ============================================================
# DESCRIPTIVE STATISTICS & DIAGNOSTICS
# ============================================================
print("\n[2] Descriptive statistics...")

vals = tw_ret.values
desc = {
    'tw_return(%)': {
        'mean': float(np.mean(vals)),
        'std': float(np.std(vals)),
        'skew': float(stats.skew(vals)),
        'kurt': float(stats.kurtosis(vals)),
        'min': float(np.min(vals)),
        'max': float(np.max(vals)),
        'N': int(len(vals))
    },
    'vix_var': {
        'mean': float(np.mean(vix_var.values)),
        'std': float(np.std(vix_var.values)),
        'min': float(np.min(vix_var.values)),
        'max': float(np.max(vix_var.values))
    }
}

# ADF test
adf_tw = adfuller(tw_ret.values, maxlag=10)
adf_vix = adfuller(vix_var.values, maxlag=10)
adf_tests = {
    'tw_return': {'statistic': adf_tw[0], 'p_value': adf_tw[1]},
    'vix_var': {'statistic': adf_vix[0], 'p_value': adf_vix[1]}
}
print(f"   ADF tw_ret: {adf_tw[0]:.3f} (p={adf_tw[1]:.2e}) — {'stationary' if adf_tw[1]<0.05 else 'NOT stationary'}")
print(f"   ADF vix_var: {adf_vix[0]:.3f} (p={adf_vix[1]:.2e}) — {'stationary' if adf_vix[1]<0.05 else 'NOT stationary'}")

# ARCH LM test (on demeaned returns)
tw_demeaned = tw_ret.values - np.mean(tw_ret.values)
lm_stat, lm_pval, _, _ = het_arch(tw_demeaned, nlags=10)
arch_lm = {'lm_stat': float(lm_stat), 'p_value': float(lm_pval)}
print(f"   ARCH LM: {lm_stat:.1f} (p={lm_pval:.2e}) — {'ARCH effects present' if lm_pval<0.05 else 'no ARCH'}")

# Rolling correlation analysis (key diagnostic for TVP)
print("\n[3] Rolling correlation analysis (motivation for TVP)...")
roll_corr_63 = tw_ret.rolling(63).corr(spy_ret).dropna()
roll_corr_126 = tw_ret.rolling(126).corr(spy_ret).dropna()

# Also correlate squared returns (volatility transmission)
roll_vol_corr = (tw_ret**2).rolling(63).corr(spy_ret**2).dropna()
# VIX-TW volatility correlation
roll_vix_tw_corr = (tw_ret**2).rolling(63).corr(vix_var).dropna()

corr_stability = {
    'return_corr_63d': {
        'mean': float(roll_corr_63.mean()),
        'std': float(roll_corr_63.std()),
        'min': float(roll_corr_63.min()),
        'max': float(roll_corr_63.max()),
        'pct_negative': float((roll_corr_63 < 0).mean() * 100)
    },
    'return_corr_126d': {
        'mean': float(roll_corr_126.mean()),
        'std': float(roll_corr_126.std()),
        'min': float(roll_corr_126.min()),
        'max': float(roll_corr_126.max())
    },
    'vol_corr_63d(r2_tw vs r2_spy)': {
        'mean': float(roll_vol_corr.mean()),
        'std': float(roll_vol_corr.std()),
        'min': float(roll_vol_corr.min()),
        'max': float(roll_vol_corr.max())
    },
    'vix_tw_vol_corr_63d': {
        'mean': float(roll_vix_tw_corr.mean()),
        'std': float(roll_vix_tw_corr.std()),
        'min': float(roll_vix_tw_corr.min()),
        'max': float(roll_vix_tw_corr.max())
    }
}

print(f"   Return corr (63d): mean={roll_corr_63.mean():.3f}, std={roll_corr_63.std():.3f}, "
      f"range=[{roll_corr_63.min():.3f}, {roll_corr_63.max():.3f}]")
print(f"   Vol corr (r²,63d): mean={roll_vol_corr.mean():.3f}, std={roll_vol_corr.std():.3f}")
print(f"   VIX-TW vol corr:   mean={roll_vix_tw_corr.mean():.3f}, std={roll_vix_tw_corr.std():.3f}")
print(f"   % negative return corr (63d): {(roll_corr_63 < 0).mean()*100:.1f}%")

# ============================================================
# OOS CONFIGURATION
# ============================================================
WINDOW = 2000
REFIT_EVERY = 21
OOS_START = '2023-01-01'
OOS_END = '2024-12-31'

returns_arr = tw_ret.values
vix_var_arr = vix_var.values
spy_r2_arr = spy_r2.values
spy_rv5_arr = spy_rv5.values
dates = tw_ret.index

oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)

print(f"\n[4] OOS configuration:")
print(f"   Window: {WINDOW}, Refit every: {REFIT_EVERY}")
print(f"   OOS: {dates[oos_indices[0]].date()} to {dates[oos_indices[-1]].date()} ({n_oos} obs)")

# ============================================================
# MODEL 1: GJR Baseline
# ============================================================
print("\n[5] Model 1: GJR Baseline...")
fc_gjr = np.full(n_oos, np.nan)

for i, t in enumerate(oos_indices):
    start = max(0, t - WINDOW)
    if i % REFIT_EVERY == 0 or i == 0:
        fit = fit_gjr(returns_arr[start:t])
        if fit is None or not fit['converged']:
            continue
        gjr_params = [fit['params']['omega'], fit['params']['alpha'],
                      fit['params']['gamma'], fit['params']['beta']]
    # One-step forecast
    lev = float(returns_arr[t-1] < 0) * returns_arr[t-1]**2
    h_prev = gjr_filter(gjr_params, returns_arr[start:t])[-1]
    fc_gjr[i] = gjr_params[0] + gjr_params[1]*returns_arr[t-1]**2 + gjr_params[2]*lev + gjr_params[3]*h_prev

fc_gjr = np.maximum(fc_gjr, 1e-8)
print(f"   Done. Mean forecast: {np.nanmean(fc_gjr):.4f}")

# ============================================================
# MODEL 2: Fixed GARCH-X(VIX²) — K462 replication
# ============================================================
print("\n[6] Model 2: Fixed GARCH-X(VIX²)...")
fc_fixed = np.full(n_oos, np.nan)
delta_fixed_track = []

for i, t in enumerate(oos_indices):
    start = max(0, t - WINDOW)
    if i % REFIT_EVERY == 0 or i == 0:
        fit = fit_gjr_x1(returns_arr[start:t], vix_var_arr[start:t])
        if fit is None or not fit['converged']:
            continue
        fx_params = [fit['params']['omega'], fit['params']['alpha'],
                     fit['params']['gamma'], fit['params']['beta'], fit['params']['delta1']]
        delta_fixed_track.append({'day': i, 'delta': fx_params[4]})
    # One-step forecast
    lev = float(returns_arr[t-1] < 0) * returns_arr[t-1]**2
    h_prev = gjr_x1_filter(fx_params, returns_arr[start:t], vix_var_arr[start:t])[-1]
    fc_fixed[i] = (fx_params[0] + fx_params[1]*returns_arr[t-1]**2 + fx_params[2]*lev
                   + fx_params[3]*h_prev + fx_params[4]*vix_var_arr[t-1])

fc_fixed = np.maximum(fc_fixed, 1e-8)
print(f"   Done. Mean forecast: {np.nanmean(fc_fixed):.4f}")

# ============================================================
# MODEL 3: Rolling GARCH-X — refit delta every 63 days with rolling window 500
# ============================================================
print("\n[7] Model 3: Rolling GARCH-X (refit delta every 63 days, window=500)...")
fc_rolling = np.full(n_oos, np.nan)
ROLL_WINDOW = 500
ROLL_REFIT = 63
delta_rolling_track = []

# First fit: use GARCH base from Model 2 but with shorter window for delta
for i, t in enumerate(oos_indices):
    start = max(0, t - WINDOW)
    # Refit GJR base every REFIT_EVERY days
    if i % REFIT_EVERY == 0 or i == 0:
        fit_base = fit_gjr(returns_arr[start:t])
        if fit_base is None or not fit_base['converged']:
            continue
        base_params = [fit_base['params']['omega'], fit_base['params']['alpha'],
                       fit_base['params']['gamma'], fit_base['params']['beta']]

    # Refit delta every ROLL_REFIT days using recent ROLL_WINDOW observations
    if i % ROLL_REFIT == 0 or i == 0:
        delta_start = max(0, t - ROLL_WINDOW)
        fit_x = fit_gjr_x1(returns_arr[delta_start:t], vix_var_arr[delta_start:t])
        if fit_x is not None and fit_x['converged']:
            rolling_delta = fit_x['params']['delta1']
        else:
            rolling_delta = 0.0  # fallback to no exogenous
        delta_rolling_track.append({'day': i, 'delta': rolling_delta})

    # One-step forecast
    lev = float(returns_arr[t-1] < 0) * returns_arr[t-1]**2
    h_prev = gjr_filter(base_params, returns_arr[start:t])[-1]
    fc_rolling[i] = (base_params[0] + base_params[1]*returns_arr[t-1]**2 + base_params[2]*lev
                     + base_params[3]*h_prev + rolling_delta*vix_var_arr[t-1])

fc_rolling = np.maximum(fc_rolling, 1e-8)
print(f"   Done. Mean forecast: {np.nanmean(fc_rolling):.4f}")

# ============================================================
# MODEL 4: Adaptive Delta — VIX<20 vs VIX≥20
# ============================================================
print("\n[8] Model 4: Adaptive Delta (VIX regime)...")
fc_adaptive = np.full(n_oos, np.nan)
delta_adaptive_track = []

for i, t in enumerate(oos_indices):
    start = max(0, t - WINDOW)

    # Refit base GJR every REFIT_EVERY
    if i % REFIT_EVERY == 0 or i == 0:
        fit_base = fit_gjr(returns_arr[start:t])
        if fit_base is None or not fit_base['converged']:
            continue
        base_params_a = [fit_base['params']['omega'], fit_base['params']['alpha'],
                         fit_base['params']['gamma'], fit_base['params']['beta']]

        # Split IS data by VIX regime and fit separate deltas
        vix_level = np.sqrt(vix_var_arr[start:t] * 252)  # convert back to VIX level
        low_mask = vix_level < 20
        high_mask = vix_level >= 20

        delta_low = 0.0
        delta_high = 0.0

        # Fit on low-VIX subsample
        if np.sum(low_mask) > 100:
            fit_low = fit_gjr_x1(returns_arr[start:t][low_mask], vix_var_arr[start:t][low_mask])
            if fit_low is not None and fit_low['converged']:
                delta_low = fit_low['params']['delta1']

        # Fit on high-VIX subsample
        if np.sum(high_mask) > 100:
            fit_high = fit_gjr_x1(returns_arr[start:t][high_mask], vix_var_arr[start:t][high_mask])
            if fit_high is not None and fit_high['converged']:
                delta_high = fit_high['params']['delta1']

        delta_adaptive_track.append({
            'day': i, 'delta_low': delta_low, 'delta_high': delta_high
        })

    # Choose delta based on current VIX level
    current_vix = np.sqrt(vix_var_arr[t-1] * 252)
    delta_use = delta_low if current_vix < 20 else delta_high

    # One-step forecast
    lev = float(returns_arr[t-1] < 0) * returns_arr[t-1]**2
    h_prev = gjr_filter(base_params_a, returns_arr[start:t])[-1]
    fc_adaptive[i] = (base_params_a[0] + base_params_a[1]*returns_arr[t-1]**2 + base_params_a[2]*lev
                      + base_params_a[3]*h_prev + delta_use*vix_var_arr[t-1])

fc_adaptive = np.maximum(fc_adaptive, 1e-8)
print(f"   Done. Mean forecast: {np.nanmean(fc_adaptive):.4f}")

# ============================================================
# MODEL 5: EWMA Delta — exponential smoothing of delta estimates
# ============================================================
print("\n[9] Model 5: EWMA Delta (λ=0.95)...")
fc_ewma = np.full(n_oos, np.nan)
LAMBDA = 0.95
LOCAL_WINDOW = 252  # 1 year local window for delta estimation
EWMA_REFIT = 21  # refit local delta every 21 days
delta_ewma_track = []

ewma_delta = None  # will initialize from first fit

for i, t in enumerate(oos_indices):
    start = max(0, t - WINDOW)

    # Refit base GJR every REFIT_EVERY
    if i % REFIT_EVERY == 0 or i == 0:
        fit_base = fit_gjr(returns_arr[start:t])
        if fit_base is None or not fit_base['converged']:
            continue
        base_params_e = [fit_base['params']['omega'], fit_base['params']['alpha'],
                         fit_base['params']['gamma'], fit_base['params']['beta']]

    # Update EWMA delta periodically
    if i % EWMA_REFIT == 0 or i == 0:
        local_start = max(0, t - LOCAL_WINDOW)
        fit_local = fit_gjr_x1(returns_arr[local_start:t], vix_var_arr[local_start:t])
        if fit_local is not None and fit_local['converged']:
            delta_new = fit_local['params']['delta1']
        else:
            delta_new = 0.0

        if ewma_delta is None:
            ewma_delta = delta_new  # initialize
        else:
            ewma_delta = LAMBDA * ewma_delta + (1 - LAMBDA) * delta_new

        delta_ewma_track.append({'day': i, 'delta_ewma': ewma_delta, 'delta_local': delta_new})

    # One-step forecast
    lev = float(returns_arr[t-1] < 0) * returns_arr[t-1]**2
    h_prev = gjr_filter(base_params_e, returns_arr[start:t])[-1]
    fc_ewma[i] = (base_params_e[0] + base_params_e[1]*returns_arr[t-1]**2 + base_params_e[2]*lev
                  + base_params_e[3]*h_prev + ewma_delta*vix_var_arr[t-1])

fc_ewma = np.maximum(fc_ewma, 1e-8)
print(f"   Done. Mean forecast: {np.nanmean(fc_ewma):.4f}")

# ============================================================
# MODEL 6: SPY Realized Vol Proxy (direct transmission)
# ============================================================
print("\n[10] Model 6: SPY Realized Vol Proxy...")
fc_proxy = np.full(n_oos, np.nan)

# σ²_tw,t = a + b·RV_spy,t-1 + c·h_{t-1}
# This is essentially a HAR-like model with SPY vol as predictor

for i, t in enumerate(oos_indices):
    start = max(0, t - WINDOW)

    if i % REFIT_EVERY == 0 or i == 0:
        # Fit: h_tw = a + b * spy_r2_{t-1} + c * h_tw_{t-1}
        # Use OLS on realized variance proxy
        y = returns_arr[start+1:t]**2  # realized variance
        x_spy = spy_r2_arr[start:t-1]  # lagged SPY r²

        # First get GJR h for lagged conditional variance
        fit_base = fit_gjr(returns_arr[start:t])
        if fit_base is None or not fit_base['converged']:
            continue
        h_base = gjr_filter(
            [fit_base['params']['omega'], fit_base['params']['alpha'],
             fit_base['params']['gamma'], fit_base['params']['beta']],
            returns_arr[start:t]
        )
        x_h = h_base[:-1]  # lagged h

        # OLS regression: y = a + b*x_spy + c*x_h
        X = np.column_stack([np.ones(len(y)), x_spy, x_h])
        try:
            beta_ols = np.linalg.lstsq(X, y, rcond=None)[0]
            a_proxy, b_proxy, c_proxy = beta_ols
            # Constrain: b >= 0, 0 < c < 1
            b_proxy = max(b_proxy, 0)
            c_proxy = min(max(c_proxy, 0.01), 0.99)
            a_proxy = max(a_proxy, 1e-8)
        except:
            a_proxy, b_proxy, c_proxy = np.var(y), 0.0, 0.5

        proxy_params = [a_proxy, b_proxy, c_proxy]
        base_params_p = [fit_base['params']['omega'], fit_base['params']['alpha'],
                         fit_base['params']['gamma'], fit_base['params']['beta']]

    # Forecast using proxy model
    h_prev = gjr_filter(base_params_p, returns_arr[start:t])[-1]
    fc_proxy[i] = proxy_params[0] + proxy_params[1]*spy_r2_arr[t-1] + proxy_params[2]*h_prev

fc_proxy = np.maximum(fc_proxy, 1e-8)
print(f"   Done. Mean forecast: {np.nanmean(fc_proxy):.4f}")

# ============================================================
# EVALUATION
# ============================================================
print("\n[11] Evaluation...")

realized = returns_arr[oos_indices]**2  # realized variance
valid = ~np.isnan(fc_gjr) & ~np.isnan(realized) & (realized > 0)

def compute_metrics(forecast, realized, mask, name):
    f = forecast[mask]
    r = realized[mask]
    qlike = np.mean(r/f - np.log(r/f) - 1)
    mse = np.mean((f - r)**2)
    mae = np.mean(np.abs(f - r))
    return {
        'name': name,
        'qlike': float(qlike),
        'mse': float(mse),
        'mae': float(mae),
        'n_obs': int(np.sum(mask)),
        'mean_forecast': float(np.mean(f)),
        'mean_realized': float(np.mean(r))
    }

models = {
    'GJR baseline': fc_gjr,
    'Fixed GARCH-X(VIX²)': fc_fixed,
    'Rolling GARCH-X(63d)': fc_rolling,
    'Adaptive GARCH-X(VIX regime)': fc_adaptive,
    'EWMA GARCH-X(λ=0.95)': fc_ewma,
    'SPY vol proxy': fc_proxy,
}

oos_metrics = []
for name, fc in models.items():
    m = valid & ~np.isnan(fc)
    metrics = compute_metrics(fc, realized, m, name)
    oos_metrics.append(metrics)
    print(f"   {name:35s} QLIKE={metrics['qlike']:.6f}  MSE={metrics['mse']:.2f}  MAE={metrics['mae']:.3f}")

# ============================================================
# DIEBOLD-MARIANO TESTS
# ============================================================
print("\n[12] Diebold-Mariano tests (vs GJR baseline, QLIKE loss)...")

# QLIKE loss differential
def dm_test(loss1, loss2, h=1):
    """DM test: H0: E[d_t] = 0 where d_t = loss1_t - loss2_t"""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0,1]
        var_d += 2 * (1 - k/h) * gamma_k
    se = np.sqrt(var_d / n)
    if se < 1e-12:
        return 0.0, 1.0
    dm_stat = d_bar / se
    p_val = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(p_val)

# QLIKE loss for baseline
loss_baseline = realized[valid] / fc_gjr[valid] - np.log(realized[valid] / fc_gjr[valid]) - 1

dm_results = {}
for name, fc in models.items():
    if name == 'GJR baseline':
        continue
    m = valid & ~np.isnan(fc)
    loss_alt = realized[m] / fc[m] - np.log(realized[m] / fc[m]) - 1
    # Ensure same length
    loss_b = loss_baseline[:len(loss_alt)]
    loss_a = loss_alt[:len(loss_b)]

    dm_stat, dm_pval = dm_test(loss_a, loss_b)

    qlike_base = np.mean(loss_b)
    qlike_alt = np.mean(loss_a)
    qlike_diff_pct = (qlike_alt - qlike_base) / qlike_base * 100

    if dm_stat < -1.96:
        result = "ALT wins **"
    elif dm_stat > 1.96:
        result = "GJR wins **"
    else:
        result = "No sig diff"

    dm_results[name] = {
        'dm_stat': float(dm_stat),
        'dm_pvalue': float(dm_pval),
        'qlike_diff_pct': float(qlike_diff_pct),
        'result': result
    }

    print(f"   {name:35s} DM={dm_stat:+.3f} (p={dm_pval:.4f}) ΔQLIKE={qlike_diff_pct:+.2f}% → {result}")

# ============================================================
# RESIDUAL DIAGNOSTICS
# ============================================================
print("\n[13] Residual diagnostics (standardized residuals)...")

resid_diag = {}
for name, fc in models.items():
    m = valid & ~np.isnan(fc)
    std_resid = realized[m] / fc[m]  # should be ~chi²(1)
    # Test: are there remaining ARCH effects?
    try:
        lm_s, lm_p, _, _ = het_arch(std_resid - np.mean(std_resid), nlags=5)
        resid_diag[name] = {'lm_stat': float(lm_s), 'p_value': float(lm_p)}
    except:
        resid_diag[name] = {'lm_stat': None, 'p_value': None}

for name, d in resid_diag.items():
    pstr = f"p={d['p_value']:.4f}" if d['p_value'] is not None else "N/A"
    lm_str = f"{d['lm_stat']:.2f}" if d['lm_stat'] is not None else "N/A"
    print(f"   {name:35s} ARCH LM={lm_str} ({pstr})")

# ============================================================
# DELTA DYNAMICS ANALYSIS
# ============================================================
print("\n[14] Delta dynamics analysis...")

delta_dynamics = {}

# Fixed model delta trajectory
if delta_fixed_track:
    deltas_f = [d['delta'] for d in delta_fixed_track]
    delta_dynamics['fixed'] = {
        'mean': float(np.mean(deltas_f)),
        'std': float(np.std(deltas_f)),
        'min': float(np.min(deltas_f)),
        'max': float(np.max(deltas_f)),
        'n_refits': len(deltas_f),
        'trajectory': [{'day': d['day'], 'delta': float(d['delta'])} for d in delta_fixed_track]
    }
    print(f"   Fixed delta: mean={np.mean(deltas_f):.4f}, std={np.std(deltas_f):.4f}, "
          f"range=[{np.min(deltas_f):.4f}, {np.max(deltas_f):.4f}]")

# Rolling delta trajectory
if delta_rolling_track:
    deltas_r = [d['delta'] for d in delta_rolling_track]
    delta_dynamics['rolling'] = {
        'mean': float(np.mean(deltas_r)),
        'std': float(np.std(deltas_r)),
        'min': float(np.min(deltas_r)),
        'max': float(np.max(deltas_r)),
        'n_refits': len(deltas_r),
        'trajectory': [{'day': d['day'], 'delta': float(d['delta'])} for d in delta_rolling_track]
    }
    print(f"   Rolling delta: mean={np.mean(deltas_r):.4f}, std={np.std(deltas_r):.4f}, "
          f"range=[{np.min(deltas_r):.4f}, {np.max(deltas_r):.4f}]")

# Adaptive deltas
if delta_adaptive_track:
    dl = [d['delta_low'] for d in delta_adaptive_track]
    dh = [d['delta_high'] for d in delta_adaptive_track]
    delta_dynamics['adaptive'] = {
        'delta_low_mean': float(np.mean(dl)),
        'delta_high_mean': float(np.mean(dh)),
        'delta_low_std': float(np.std(dl)),
        'delta_high_std': float(np.std(dh)),
        'n_refits': len(dl),
        'trajectory': [{'day': d['day'], 'delta_low': float(d['delta_low']),
                        'delta_high': float(d['delta_high'])} for d in delta_adaptive_track]
    }
    print(f"   Adaptive: δ_low mean={np.mean(dl):.4f}±{np.std(dl):.4f}, "
          f"δ_high mean={np.mean(dh):.4f}±{np.std(dh):.4f}")

# EWMA delta trajectory
if delta_ewma_track:
    de = [d['delta_ewma'] for d in delta_ewma_track]
    dl_e = [d['delta_local'] for d in delta_ewma_track]
    delta_dynamics['ewma'] = {
        'ewma_mean': float(np.mean(de)),
        'ewma_std': float(np.std(de)),
        'local_mean': float(np.mean(dl_e)),
        'local_std': float(np.std(dl_e)),
        'ewma_range': [float(np.min(de)), float(np.max(de))],
        'local_range': [float(np.min(dl_e)), float(np.max(dl_e))],
        'n_updates': len(de),
        'trajectory': [{'day': d['day'], 'delta_ewma': float(d['delta_ewma']),
                        'delta_local': float(d['delta_local'])} for d in delta_ewma_track]
    }
    print(f"   EWMA: ewma_mean={np.mean(de):.4f}±{np.std(de):.4f}, "
          f"local_mean={np.mean(dl_e):.4f}±{np.std(dl_e):.4f}")

# ============================================================
# VIX REGIME ANALYSIS IN OOS
# ============================================================
print("\n[15] VIX regime analysis in OOS period...")
oos_vix_level = np.sqrt(vix_var_arr[oos_indices] * 252)
low_vix_mask = oos_vix_level < 20
high_vix_mask = oos_vix_level >= 20

regime_analysis = {
    'n_low_vix': int(np.sum(low_vix_mask)),
    'n_high_vix': int(np.sum(high_vix_mask)),
    'pct_low_vix': float(np.mean(low_vix_mask) * 100),
    'mean_vix_low': float(np.mean(oos_vix_level[low_vix_mask])) if np.sum(low_vix_mask) > 0 else None,
    'mean_vix_high': float(np.mean(oos_vix_level[high_vix_mask])) if np.sum(high_vix_mask) > 0 else None,
}

# QLIKE by regime for each model
regime_qlike = {}
for name, fc in models.items():
    m = valid & ~np.isnan(fc)
    low_m = m & low_vix_mask
    high_m = m & high_vix_mask

    if np.sum(low_m) > 10:
        qlike_low = float(np.mean(realized[low_m] / fc[low_m] - np.log(realized[low_m] / fc[low_m]) - 1))
    else:
        qlike_low = None

    if np.sum(high_m) > 10:
        qlike_high = float(np.mean(realized[high_m] / fc[high_m] - np.log(realized[high_m] / fc[high_m]) - 1))
    else:
        qlike_high = None

    regime_qlike[name] = {'qlike_low_vix': qlike_low, 'qlike_high_vix': qlike_high}

print(f"   Low VIX (<20): {np.sum(low_vix_mask)} days ({np.mean(low_vix_mask)*100:.1f}%)")
print(f"   High VIX (≥20): {np.sum(high_vix_mask)} days ({np.mean(high_vix_mask)*100:.1f}%)")
print(f"\n   QLIKE by regime:")
for name in models:
    rq = regime_qlike[name]
    low_str = f"{rq['qlike_low_vix']:.6f}" if rq['qlike_low_vix'] is not None else "N/A"
    high_str = f"{rq['qlike_high_vix']:.6f}" if rq['qlike_high_vix'] is not None else "N/A"
    print(f"   {name:35s} Low={low_str}  High={high_str}")

# ============================================================
# CONVERGENCE CHECK & IS FIT
# ============================================================
print("\n[16] In-sample fit (full sample)...")
is_results = {}

# GJR on full IS
full_is_end = oos_indices[0]
is_ret = returns_arr[:full_is_end]
is_vix = vix_var_arr[:full_is_end]

fit_is_gjr = fit_gjr(is_ret)
if fit_is_gjr:
    is_results['GJR baseline'] = {
        'params': fit_is_gjr['params'],
        'persistence': fit_is_gjr['persistence'],
        'converged': fit_is_gjr['converged'],
        'loglik': fit_is_gjr['loglik'],
        'aic': fit_is_gjr['aic'],
        'bic': fit_is_gjr['bic']
    }
    print(f"   GJR: pers={fit_is_gjr['persistence']:.4f}, LL={fit_is_gjr['loglik']:.1f}, converged={fit_is_gjr['converged']}")

fit_is_x = fit_gjr_x1(is_ret, is_vix)
if fit_is_x:
    # Compute delta SE via numerical Hessian
    from scipy.optimize import approx_fprime

    def neg_ll_wrapper(p):
        return gjr_x1_negll(p, is_ret, is_vix)

    # Numerical Hessian
    eps_h = 1e-5
    p_opt = np.array([fit_is_x['params']['omega'], fit_is_x['params']['alpha'],
                      fit_is_x['params']['gamma'], fit_is_x['params']['beta'],
                      fit_is_x['params']['delta1']])
    n_p = len(p_opt)
    hess = np.zeros((n_p, n_p))
    for j in range(n_p):
        e_j = np.zeros(n_p)
        e_j[j] = eps_h
        g_plus = approx_fprime(p_opt + e_j, neg_ll_wrapper, eps_h)
        g_minus = approx_fprime(p_opt - e_j, neg_ll_wrapper, eps_h)
        hess[j, :] = (g_plus - g_minus) / (2 * eps_h)

    try:
        inv_hess = np.linalg.inv(hess)
        se = np.sqrt(np.abs(np.diag(inv_hess)))
        delta_se = se[4]
        delta_t = fit_is_x['params']['delta1'] / delta_se
    except:
        delta_se = None
        delta_t = None

    is_results['GARCH-X(VIX²)'] = {
        'params': fit_is_x['params'],
        'persistence': fit_is_x['persistence'],
        'converged': fit_is_x['converged'],
        'loglik': fit_is_x['loglik'],
        'aic': fit_is_x['aic'],
        'bic': fit_is_x['bic'],
        'delta_se': float(delta_se) if delta_se else None,
        'delta_t_stat': float(delta_t) if delta_t else None
    }
    print(f"   GARCH-X(VIX²): δ={fit_is_x['params']['delta1']:.4f}, "
          f"t={delta_t:.2f}, pers={fit_is_x['persistence']:.4f}, LL={fit_is_x['loglik']:.1f}")

# ============================================================
# SUMMARY
# ============================================================
elapsed = time.time() - t0

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

# Find best model
baseline_qlike = oos_metrics[0]['qlike']  # GJR
best_alt = None
best_improvement = 0
for m in oos_metrics[1:]:
    diff_pct = (m['qlike'] - baseline_qlike) / baseline_qlike * 100
    if diff_pct < best_improvement:
        best_improvement = diff_pct
        best_alt = m['name']

if best_improvement < 0:
    verdict = "TVP_PARTIAL"
    conclusion = (f"Best TVP variant: {best_alt} (ΔQLIKE={best_improvement:+.2f}%). "
                  f"Time-varying delta {'improves' if best_improvement < -2 else 'marginally helps'} over fixed GARCH-X.")
else:
    verdict = "NULL"
    conclusion = (f"No TVP GARCH-X variant beats GJR baseline. "
                  f"Best attempt: {best_alt} (ΔQLIKE={best_improvement:+.2f}%). "
                  f"GARCH ceiling extends to TVP approaches on Taiwan.")

print(f"\nVerdict: {verdict}")
print(f"Conclusion: {conclusion}")
print(f"Runtime: {elapsed:.1f}s")

# Print ranking
print("\nModel ranking by QLIKE:")
ranked = sorted(oos_metrics, key=lambda x: x['qlike'])
for i, m in enumerate(ranked):
    diff = (m['qlike'] - baseline_qlike) / baseline_qlike * 100
    marker = "★" if m['name'] == 'GJR baseline' else " "
    print(f"   {i+1}. {marker} {m['name']:35s} QLIKE={m['qlike']:.6f} (Δ={diff:+.2f}%)")

# ============================================================
# SAVE RESULTS
# ============================================================
results = {
    'experiment_id': 'K463',
    'title': 'Time-Varying Parameter GARCH-X for Taiwan (TVP Approaches)',
    'proposer': '用戶',
    'executor': 'Claude',
    'asset': '0050.TW',
    'data_source': 'yfinance (0050.TW, SPY, ^VIX)',
    'data_period': f"{dates[0].date()} to {dates[-1].date()}",
    'total_obs': int(len(dates)),
    'oos_period': f"{dates[oos_indices[0]].date()} to {dates[oos_indices[-1]].date()}",
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'runtime_seconds': round(elapsed, 1),
    'hypothesis': 'Fixed delta GARCH-X fails OOS because SPY-TW relationship is time-varying. '
                  'TVP approaches (rolling/adaptive/EWMA) may capture regime changes better.',
    'descriptive': desc,
    'adf_tests': adf_tests,
    'arch_lm': arch_lm,
    'correlation_stability': corr_stability,
    'in_sample': is_results,
    'oos_metrics': oos_metrics,
    'dm_tests': dm_results,
    'residual_diagnostics': resid_diag,
    'delta_dynamics': delta_dynamics,
    'regime_analysis': regime_analysis,
    'regime_qlike': regime_qlike,
    'verdict': verdict,
    'conclusion': conclusion,
    'comparison_with_prior': {
        'K461': 'SSVS SPY_ret PIP=1.000 but QLIKE not improved (mean vs variance disconnect)',
        'K462': 'GARCH-X(VIX) IS t=3.58 but OOS +7.1% worse, rolling corr -0.02 to 0.86',
        'K463_improvement': f'Best TVP: {best_alt} (ΔQLIKE={best_improvement:+.2f}%)'
    },
    'limitations': [
        'Simple TVP methods (not full Kalman filter or GAS)',
        'OOS only 2023-2024 (481 obs, mostly low-VIX regime)',
        'Delta estimation on subsamples may be noisy',
        'No cross-OOS validation (single split)',
        'EWMA lambda=0.95 is ad hoc (not optimized)'
    ]
}

import os
out_path = os.path.join(os.path.dirname(__file__), 'k463_tvp_garchx_taiwan_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to {out_path}")
print("Done.")
