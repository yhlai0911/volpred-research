#!/usr/bin/env python3
"""
K488: GJR-GARCH-X(VIX) Based Volatility Targeting Strategy
============================================================

Core Hypothesis:
  K440/K470 showed: better vol forecast ≠ better VT (12/VIX's risk premium
  is a feature, not a bug). But GJR-X(VIX) is different — its σ already
  contains VIX risk premium (via δ·VIX²/252 in variance equation) → it
  may approach 12/VIX's conservative behavior while being more precise.

Background:
  K486: GJR-X(VIX) breaks impossible triangle (forecasting -17% QLIKE + VaR 5/5)
  K440: VRP-VT fails (prediction ≠ trading, VRP-VT hurts Sharpe)
  K470: HAR-VT fails Harvey threshold (better forecaster ≠ better VT)
  K485: GJR-X(VIX) robustly best forecaster (5/5 cross-OOS)

Strategies (applied to 50/50 SPY+GLD blend):
  1. Buy & Hold SPY
  2. Buy & Hold 50/50 SPY+GLD
  3. 12/VIX VT (baseline): w = 12/VIX, cap 100%
  4. GJR-X(VIX) VT: w = target/σ_GARCHX (annualized), cap 100%
  5. GJR-only VT (control): w = target/σ_GJR (annualized), cap 100%
  6. Hybrid VT: σ = 0.5*VIX + 0.5*σ_GARCHX, w = target/σ, cap 100%

Cross-OOS Periods (5):
  1. 2008-2011 (GFC)
  2. 2012-2015 (recovery)
  3. 2016-2018 (Volmageddon)
  4. 2019-2021 (COVID)
  5. 2022-2025 (rate hikes + AI)

Evaluation:
  - Sharpe, MDD, Calmar, Sortino, Net Sharpe (after TX)
  - DM test on returns vs 12/VIX baseline
  - Memmel (2003) Sharpe ratio difference test
  - Harvey (2016) t>3.0 threshold for new factor claims

Data: yfinance (SPY, GLD, ^VIX), 2005-2026
Refs:
  Moreira & Muir (2017) JoF 72(4):1611-1644 — Volatility-Managed Portfolios
  Bollerslev, Tauchen, Zhou (2009) RFS — VRP and returns
  Patton (2011) JoE — Volatility forecast comparison
  Memmel (2003) — Sharpe ratio difference test
  Harvey, Liu, Zhu (2016) RFS — ...and the cross-section of expected returns (t>3)
  K486: GJR-X(VIX) final cross-OOS + VaR trinity
  K440: VRP-VT null result
  K470: HAR-VT null result
Author: [Proposed: User, Executed: Claude]
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats, optimize
from arch import arch_model
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')

print("=" * 70)
print("K488: GJR-GARCH-X(VIX) Based Volatility Targeting Strategy")
print("  Hypothesis: GJR-X(VIX) σ contains risk premium → may match 12/VIX VT")
print("  K440/K470 lesson: prediction ≠ trading, but GJR-X is different")
print("=" * 70)

t_global = time.time()

# ============================================================
# Configuration
# ============================================================
IS_WINDOW = 1500       # ~6 years in-sample for GARCH (less than K486 to allow more OOS)
REFIT_INTERVAL = 63    # refit every ~3 months (for speed)
TARGET_VOL = 12.0      # annualized target volatility (%)
RF_ANNUAL = 0.02       # risk-free rate
RF_DAILY = RF_ANNUAL / 252
TX_BPS = 3             # transaction cost per trade (basis points)

# Cross-OOS periods (5 non-overlapping, spanning GFC to present)
OOS_PERIODS = [
    {"name": "2008-2011 (GFC)", "start": "2008-01-01", "end": "2011-12-31"},
    {"name": "2012-2015 (recovery)", "start": "2012-01-01", "end": "2015-12-31"},
    {"name": "2016-2018 (Volmageddon)", "start": "2016-01-01", "end": "2018-12-31"},
    {"name": "2019-2021 (COVID)", "start": "2019-01-01", "end": "2021-12-31"},
    {"name": "2022-2025 (rate hikes)", "start": "2022-01-01", "end": "2025-12-31"},
]

# ============================================================
# 1. DATA DOWNLOAD
# ============================================================
print("\n[1/8] Downloading data from yfinance...")
spy_raw = yf.download('SPY', start='2005-01-01', progress=False)
gld_raw = yf.download('GLD', start='2005-01-01', progress=False)
vix_raw = yf.download('^VIX', start='2005-01-01', progress=False)

for df in [spy_raw, gld_raw, vix_raw]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

# Align dates
common_idx = spy_raw.index.intersection(vix_raw.index).intersection(gld_raw.index)
spy_raw = spy_raw.loc[common_idx]
gld_raw = gld_raw.loc[common_idx]
vix_raw = vix_raw.loc[common_idx]

print(f"  SPY: {spy_raw.index[0].date()} to {spy_raw.index[-1].date()} ({len(spy_raw)} obs)")
print(f"  GLD: {gld_raw.index[0].date()} to {gld_raw.index[-1].date()} ({len(gld_raw)} obs)")
print(f"  VIX: {vix_raw.index[0].date()} to {vix_raw.index[-1].date()} ({len(vix_raw)} obs)")

# ============================================================
# 2. FEATURE COMPUTATION
# ============================================================
print("\n[2/8] Computing features...")

spy_close = spy_raw['Close'].values.astype(float).ravel()
gld_close = gld_raw['Close'].values.astype(float).ravel()
vix_close = vix_raw['Close'].values.astype(float).ravel()

# Daily returns (decimal)
spy_ret = np.log(spy_close[1:] / spy_close[:-1])
gld_ret = np.log(gld_close[1:] / gld_close[:-1])
# Returns in % for GARCH
spy_ret_pct = spy_ret * 100

idx = spy_raw.index[1:]

feat = pd.DataFrame({
    'spy_ret': spy_ret,
    'gld_ret': gld_ret,
    'spy_ret_pct': spy_ret_pct,
    'VIX': vix_close[1:],
    'vix_daily_var': vix_close[1:]**2 / 252,  # VIX²/252 in %² (for GARCH-X)
}, index=idx)
feat = feat.dropna()

# 50/50 blend return
feat['blend_ret'] = 0.5 * feat['spy_ret'] + 0.5 * feat['gld_ret']

print(f"  Combined: {len(feat)} obs ({feat.index[0].date()} to {feat.index[-1].date()})")
print(f"  VIX: mean={feat['VIX'].mean():.1f}, std={feat['VIX'].std():.1f}")
print(f"  SPY daily ret: mean={feat['spy_ret'].mean()*100:.4f}%, std={feat['spy_ret'].std()*100:.4f}%")
print(f"  GLD daily ret: mean={feat['gld_ret'].mean()*100:.4f}%, std={feat['gld_ret'].std()*100:.4f}%")
print(f"  Blend daily ret: mean={feat['blend_ret'].mean()*100:.4f}%, std={feat['blend_ret'].std()*100:.4f}%")

# ============================================================
# 3. DIAGNOSTICS (CLAUDE.md rule 5)
# ============================================================
print("\n[3/8] Data diagnostics...")
ret = feat['spy_ret_pct'].values

adf_stat, adf_p, _, _, _, _ = adfuller(ret, maxlag=21)
arch_stat_val, arch_p, _, _ = het_arch(ret, nlags=10)
lb = acorr_ljungbox(ret**2, lags=[10], return_df=True)

diagnostics = {
    'n_obs': len(feat),
    'date_range': f"{feat.index[0].date()} to {feat.index[-1].date()}",
    'spy_ret_mean_pct': float(np.mean(feat['spy_ret'])*100),
    'spy_ret_std_pct': float(np.std(feat['spy_ret'])*100),
    'gld_ret_mean_pct': float(np.mean(feat['gld_ret'])*100),
    'gld_ret_std_pct': float(np.std(feat['gld_ret'])*100),
    'blend_ret_mean_pct': float(np.mean(feat['blend_ret'])*100),
    'blend_ret_std_pct': float(np.std(feat['blend_ret'])*100),
    'spy_ret_skew': float(stats.skew(ret)),
    'spy_ret_kurt': float(stats.kurtosis(ret)),
    'vix_mean': float(feat['VIX'].mean()),
    'vix_std': float(feat['VIX'].std()),
    'adf_stat': float(adf_stat),
    'adf_p': float(adf_p),
    'is_stationary': bool(adf_p < 0.05),
    'arch_lm_stat': float(arch_stat_val),
    'arch_lm_p': float(arch_p),
    'has_arch_effects': bool(arch_p < 0.05),
    'ljung_box_sq_p10': float(lb['lb_pvalue'].values[0]),
    'spy_gld_corr': float(feat['spy_ret'].corr(feat['gld_ret'])),
}

print(f"  n={diagnostics['n_obs']}, ADF p={adf_p:.2e} ({'stationary' if adf_p < 0.05 else 'NON-STATIONARY'})")
print(f"  ARCH-LM p={arch_p:.2e} ({'ARCH effects' if arch_p < 0.05 else 'no ARCH'})")
print(f"  SPY ret: mean={np.mean(ret):.4f}%, std={np.std(ret):.4f}%, skew={stats.skew(ret):.3f}, kurt={stats.kurtosis(ret):.3f}")
print(f"  SPY-GLD corr: {diagnostics['spy_gld_corr']:.4f}")


# ============================================================
# 4. MODEL ESTIMATION FUNCTIONS (from K486)
# ============================================================

def gjr_garchx_loglik(params, returns, vix_var_lag):
    """
    Log-likelihood for GJR-GARCH-X(VIX).
    h_t = ω + α·ε²_{t-1} + γ·I(ε<0)·ε²_{t-1} + β·h_{t-1} + δ·VIX²_{t-1}/252
    Returns negative log-likelihood (for minimization).
    """
    mu, omega, alpha, gamma, beta, delta, nu = params
    T = len(returns)
    eps = returns - mu
    h = np.zeros(T)
    h[0] = np.var(eps)
    if h[0] <= 0:
        h[0] = 1.0

    for t in range(1, T):
        shock2 = eps[t-1]**2
        asym = shock2 * (1.0 if eps[t-1] < 0 else 0.0)
        h[t] = omega + alpha * shock2 + gamma * asym + beta * h[t-1] + delta * vix_var_lag[t]
        if h[t] <= 0:
            h[t] = 1e-6

    from scipy.special import gammaln
    ll = (
        gammaln((nu + 1) / 2) - gammaln(nu / 2)
        - 0.5 * np.log(np.pi * (nu - 2))
        - 0.5 * np.log(h)
        - (nu + 1) / 2 * np.log(1 + eps**2 / (h * (nu - 2)))
    )
    return -np.sum(ll)


def fit_gjr_garchx(returns_pct, vix_daily_var):
    """
    Fit GJR-GARCH-X(VIX) via custom MLE.
    Returns dict with params, h_forecast (1-step ahead in %²), or None on failure.
    """
    T = len(returns_pct)
    ret = returns_pct.copy()

    # Lag VIX
    vix_lag = np.zeros(T)
    vix_lag[1:] = vix_daily_var[:-1]
    vix_lag[0] = vix_daily_var[0]

    mu0 = np.mean(ret)
    x0 = [mu0, 0.01, 0.05, 0.05, 0.90, 0.01, 6.0]
    bounds = [
        (-1.0, 1.0),
        (1e-6, 10.0),
        (1e-6, 0.5),
        (0.0, 0.5),
        (0.3, 0.999),
        (0.0, 1.0),
        (2.1, 50.0),
    ]

    try:
        result = optimize.minimize(
            gjr_garchx_loglik, x0, args=(ret, vix_lag),
            method='L-BFGS-B', bounds=bounds,
            options={'maxiter': 500, 'ftol': 1e-10}
        )
        if not result.success and result.fun > 1e10:
            return None

        mu, omega, alpha, gamma_val, beta, delta, nu = result.x

        # Reconstruct h series
        eps = ret - mu
        h = np.zeros(T)
        h[0] = np.var(eps)
        if h[0] <= 0:
            h[0] = 1.0
        for t in range(1, T):
            shock2 = eps[t-1]**2
            asym = shock2 * (1.0 if eps[t-1] < 0 else 0.0)
            h[t] = omega + alpha * shock2 + gamma_val * asym + beta * h[t-1] + delta * vix_lag[t]
            if h[t] <= 0:
                h[t] = 1e-6

        # 1-step ahead forecast (h_{T+1})
        shock2_last = eps[-1]**2
        asym_last = shock2_last * (1.0 if eps[-1] < 0 else 0.0)
        h_forecast = omega + alpha * shock2_last + gamma_val * asym_last + beta * h[-1] + delta * vix_daily_var[-1]
        if h_forecast <= 0:
            h_forecast = 1e-6

        return {
            'params': {'mu': mu, 'omega': omega, 'alpha': alpha, 'gamma': gamma_val,
                       'beta': beta, 'delta': delta, 'nu': nu},
            'persistence': float(alpha + gamma_val / 2 + beta),
            'h_forecast': float(h_forecast),  # in %²
            'h_series': h,
            'converged': result.success,
        }
    except Exception:
        return None


def fit_gjr_garch(returns_pct):
    """Standard GJR-GARCH(1,1) via arch package. Returns h_forecast in %²."""
    try:
        am = arch_model(returns_pct, vol='GARCH', p=1, o=1, q=1, dist='t', mean='Constant')
        res = am.fit(disp='off', show_warning=False)
        # 1-step ahead forecast
        fcst = res.forecast(horizon=1)
        h_forecast = fcst.variance.values[-1, 0]  # in %² (returns are in %)
        # conditional_volatility may be ndarray or Series depending on arch version
        cond_vol = res.conditional_volatility
        if hasattr(cond_vol, 'values'):
            cond_vol = cond_vol.values
        return {
            'h_forecast': float(h_forecast),
            'h_series': cond_vol**2,  # σ² series in %²
            'params': {k: float(v) for k, v in res.params.items()},
            'converged': res.convergence_flag == 0,
        }
    except Exception:
        return None


# ============================================================
# 5. ROLLING VOLATILITY FORECASTS
# ============================================================
print("\n[4/8] Computing rolling volatility forecasts...")
print(f"  IS_WINDOW={IS_WINDOW}, REFIT_INTERVAL={REFIT_INTERVAL}")

ret_pct = feat['spy_ret_pct'].values
vix_dv = feat['vix_daily_var'].values
dates = feat.index

n = len(feat)

# Store annualized vol forecasts (%)
sigma_gjrx = np.full(n, np.nan)   # GJR-X(VIX) annualized vol
sigma_gjr = np.full(n, np.nan)    # standard GJR annualized vol
delta_history = []                 # track δ coefficient over time

# Pre-fit at refit points, then propagate between refits
last_gjrx_result = None
last_gjr_result = None
n_refits = 0
fit_failures_gjrx = 0
fit_failures_gjr = 0

t_fit_start = time.time()

for t in range(IS_WINDOW, n):
    # Refit model?
    need_refit = (t == IS_WINDOW) or ((t - IS_WINDOW) % REFIT_INTERVAL == 0)

    if need_refit:
        train_ret = ret_pct[t - IS_WINDOW:t]
        train_vix = vix_dv[t - IS_WINDOW:t]

        # Fit GJR-X(VIX)
        gjrx_res = fit_gjr_garchx(train_ret, train_vix)
        if gjrx_res is not None:
            last_gjrx_result = gjrx_res
            delta_history.append({
                'date': str(dates[t].date()),
                'delta': gjrx_res['params']['delta'],
                'persistence': gjrx_res['persistence'],
            })
        else:
            fit_failures_gjrx += 1

        # Fit standard GJR
        gjr_res = fit_gjr_garch(train_ret)
        if gjr_res is not None:
            last_gjr_result = gjr_res
        else:
            fit_failures_gjr += 1

        n_refits += 1

    # Extract 1-step ahead σ (annualized %)
    # For GJR-X: re-estimate h_forecast using latest data
    if last_gjrx_result is not None:
        p = last_gjrx_result['params']
        # Use stored parameters to compute h_{t+1}
        # We need the latest residual and h_t, but for simplicity at non-refit points
        # use a rolling update:
        if t == IS_WINDOW or need_refit:
            # Use the full h_series from the last fit
            h_last = last_gjrx_result['h_series'][-1]
            eps_last = ret_pct[t-1] - p['mu']
        else:
            # Propagate h forward from previous step
            eps_last = ret_pct[t-1] - p['mu']
            shock2 = eps_last**2
            asym = shock2 * (1.0 if eps_last < 0 else 0.0)
            # h_t = ω + α·ε²_{t-1} + γ·I·ε²_{t-1} + β·h_{t-1} + δ·VIX²_{t-1}/252
            h_last = (p['omega'] + p['alpha'] * shock2 + p['gamma'] * asym
                      + p['beta'] * _prev_h_gjrx + p['delta'] * vix_dv[t-1])
            if h_last <= 0:
                h_last = 1e-6

        # 1-step ahead: h_{t+1}
        eps_t = ret_pct[t] - p['mu']
        shock2_t = eps_t**2
        asym_t = shock2_t * (1.0 if eps_t < 0 else 0.0)
        h_next = (p['omega'] + p['alpha'] * shock2_t + p['gamma'] * asym_t
                  + p['beta'] * h_last + p['delta'] * vix_dv[t])
        if h_next <= 0:
            h_next = 1e-6

        # Annualize: sqrt(h_next) is daily σ in %, multiply by sqrt(252)
        sigma_gjrx[t] = np.sqrt(h_next) * np.sqrt(252)
        _prev_h_gjrx = h_last
    else:
        _prev_h_gjrx = np.var(ret_pct[:t]) if t > 0 else 1.0

    # For standard GJR: similarly propagate
    if last_gjr_result is not None:
        gp = last_gjr_result['params']
        mu_g = gp.get('mu', gp.get('Const', 0))
        omega_g = gp.get('omega', 0)
        alpha_g = gp.get('alpha[1]', 0)
        gamma_g = gp.get('gamma[1]', 0)
        beta_g = gp.get('beta[1]', 0)

        if t == IS_WINDOW or need_refit:
            h_last_g = last_gjr_result['h_series'][-1]
            eps_last_g = ret_pct[t-1] - mu_g
        else:
            eps_last_g = ret_pct[t-1] - mu_g
            shock2_g = eps_last_g**2
            asym_g = shock2_g * (1.0 if eps_last_g < 0 else 0.0)
            h_last_g = omega_g + alpha_g * shock2_g + gamma_g * asym_g + beta_g * _prev_h_gjr
            if h_last_g <= 0:
                h_last_g = 1e-6

        eps_t_g = ret_pct[t] - mu_g
        shock2_t_g = eps_t_g**2
        asym_t_g = shock2_t_g * (1.0 if eps_t_g < 0 else 0.0)
        h_next_g = omega_g + alpha_g * shock2_t_g + gamma_g * asym_t_g + beta_g * h_last_g
        if h_next_g <= 0:
            h_next_g = 1e-6

        sigma_gjr[t] = np.sqrt(h_next_g) * np.sqrt(252)
        _prev_h_gjr = h_last_g
    else:
        _prev_h_gjr = np.var(ret_pct[:t]) if t > 0 else 1.0

t_fit_elapsed = time.time() - t_fit_start
print(f"  Rolling estimation done in {t_fit_elapsed:.1f}s")
print(f"  Refits: {n_refits}, GJR-X failures: {fit_failures_gjrx}, GJR failures: {fit_failures_gjr}")

# Store in DataFrame
feat['sigma_gjrx'] = sigma_gjrx
feat['sigma_gjr'] = sigma_gjr

# Validate
valid_gjrx = feat['sigma_gjrx'].dropna()
valid_gjr = feat['sigma_gjr'].dropna()
print(f"  GJR-X vol: n={len(valid_gjrx)}, mean={valid_gjrx.mean():.2f}%, "
      f"std={valid_gjrx.std():.2f}%, min={valid_gjrx.min():.2f}%, max={valid_gjrx.max():.2f}%")
print(f"  GJR vol:   n={len(valid_gjr)}, mean={valid_gjr.mean():.2f}%, "
      f"std={valid_gjr.std():.2f}%, min={valid_gjr.min():.2f}%, max={valid_gjr.max():.2f}%")

# Correlation between σ estimates
common_valid = feat[['sigma_gjrx', 'sigma_gjr', 'VIX']].dropna()
corr_gjrx_vix = common_valid['sigma_gjrx'].corr(common_valid['VIX'])
corr_gjr_vix = common_valid['sigma_gjr'].corr(common_valid['VIX'])
corr_gjrx_gjr = common_valid['sigma_gjrx'].corr(common_valid['sigma_gjr'])
print(f"  Corr(σ_GJRX, VIX): {corr_gjrx_vix:.4f}")
print(f"  Corr(σ_GJR, VIX):  {corr_gjr_vix:.4f}")
print(f"  Corr(σ_GJRX, σ_GJR): {corr_gjrx_gjr:.4f}")

# δ history summary
if delta_history:
    deltas = [d['delta'] for d in delta_history]
    print(f"  δ coefficient: mean={np.mean(deltas):.4f}, std={np.std(deltas):.4f}, "
          f"min={np.min(deltas):.4f}, max={np.max(deltas):.4f}")

# ============================================================
# 6. STRATEGY COMPUTATION
# ============================================================
print("\n[5/8] Computing strategy weights and returns...")

# Need all vol estimates valid
valid_mask = feat['sigma_gjrx'].notna() & feat['sigma_gjr'].notna()
df = feat[valid_mask].copy()
print(f"  Strategy sample: {df.index[0].date()} to {df.index[-1].date()} ({len(df)} obs)")

# --- Weights ---
# 1. Buy & Hold SPY (w=1 always)
w_bh_spy = pd.Series(1.0, index=df.index)

# 2. Buy & Hold 50/50 SPY+GLD (w=1 applied to blend)
w_bh_blend = pd.Series(1.0, index=df.index)

# 3. 12/VIX VT
w_vix_vt = (TARGET_VOL / df['VIX']).clip(upper=1.0)

# 4. GJR-X(VIX) VT
w_gjrx_vt = (TARGET_VOL / df['sigma_gjrx']).clip(upper=1.0)

# 5. GJR-only VT (control)
w_gjr_vt = (TARGET_VOL / df['sigma_gjr']).clip(upper=1.0)

# 6. Hybrid: σ = 0.5*VIX + 0.5*σ_GARCHX
sigma_hybrid = 0.5 * df['VIX'] + 0.5 * df['sigma_gjrx']
w_hybrid_vt = (TARGET_VOL / sigma_hybrid).clip(upper=1.0)

# Compute strategy returns (shift weights by 1 day — no look-ahead)
strategies = {}
strategy_weights = {}

# SPY-only strategies
for name, w in [('BH_SPY', w_bh_spy), ('VIX_VT_SPY', w_vix_vt),
                ('GJRX_VT_SPY', w_gjrx_vt), ('GJR_VT_SPY', w_gjr_vt),
                ('Hybrid_VT_SPY', w_hybrid_vt)]:
    w_lagged = w.shift(1)
    ret_s = w_lagged * df['spy_ret'] + (1 - w_lagged) * RF_DAILY
    strategies[name] = ret_s
    strategy_weights[name] = w

# 50/50 blend strategies (VT weight applied to the blend)
for name, w in [('BH_Blend', w_bh_blend), ('VIX_VT_Blend', w_vix_vt),
                ('GJRX_VT_Blend', w_gjrx_vt), ('GJR_VT_Blend', w_gjr_vt),
                ('Hybrid_VT_Blend', w_hybrid_vt)]:
    w_lagged = w.shift(1)
    ret_s = w_lagged * df['blend_ret'] + (1 - w_lagged) * RF_DAILY
    strategies[name] = ret_s
    strategy_weights[name] = w

strat_returns = pd.DataFrame(strategies).dropna()
print(f"  Returns: {strat_returns.index[0].date()} to {strat_returns.index[-1].date()} ({len(strat_returns)} obs)")

# Weight statistics
print("\n  Weight statistics (Blend strategies):")
for name in ['VIX_VT_Blend', 'GJRX_VT_Blend', 'GJR_VT_Blend', 'Hybrid_VT_Blend']:
    w = strategy_weights[name].loc[strat_returns.index]
    print(f"    {name:18s}: mean={w.mean():.3f}, std={w.std():.3f}, "
          f"min={w.min():.3f}, max={w.max():.3f}")


# ============================================================
# 7. PERFORMANCE EVALUATION FUNCTIONS
# ============================================================

def evaluate_performance(returns_df, rf_annual=0.02):
    """Compute standard performance metrics."""
    results = {}
    for col in returns_df.columns:
        r = returns_df[col].dropna()
        n = len(r)
        if n < 50:
            continue

        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)
        sharpe = (ann_ret - rf_annual) / ann_vol if ann_vol > 0 else 0

        downside = r[r < 0]
        downside_vol = downside.std() * np.sqrt(252) if len(downside) > 5 else ann_vol
        sortino = (ann_ret - rf_annual) / downside_vol if downside_vol > 0 else 0

        cum = (1 + r).cumprod()
        peak = cum.cummax()
        dd = (cum - peak) / peak
        max_dd = float(dd.min())

        calmar = (ann_ret - rf_annual) / abs(max_dd) if max_dd != 0 else 0

        results[col] = {
            'n_obs': n,
            'ann_return_pct': round(float(ann_ret * 100), 2),
            'ann_vol_pct': round(float(ann_vol * 100), 2),
            'sharpe': round(float(sharpe), 4),
            'sortino': round(float(sortino), 4),
            'max_drawdown_pct': round(float(max_dd * 100), 2),
            'calmar': round(float(calmar), 4),
        }
    return results


def compute_net_sharpe(returns_df, weight_dict, rf_annual=0.02, tx_bps=3):
    """Sharpe after transaction costs."""
    results = {}
    for col in returns_df.columns:
        r = returns_df[col].dropna()
        n = len(r)
        if n < 50:
            continue

        ann_ret = r.mean() * 252
        ann_vol = r.std() * np.sqrt(252)

        if col in weight_dict:
            w = weight_dict[col].loc[r.index]
            daily_to = w.diff().abs()
            ann_to = daily_to.mean() * 252
            annual_tx_drag = ann_to * (tx_bps / 10000)
        elif col.startswith('BH'):
            annual_tx_drag = 0
            ann_to = 0
        else:
            annual_tx_drag = 0.001
            ann_to = 0

        net_sharpe = ((ann_ret - rf_annual) - annual_tx_drag) / ann_vol if ann_vol > 0 else 0
        results[col] = {
            'net_sharpe': round(float(net_sharpe), 4),
            'annual_turnover': round(float(ann_to), 4),
            'annual_tx_drag_bps': round(float(annual_tx_drag * 10000), 1),
        }
    return results


def dm_test_returns(ret1, ret2, h=1):
    """DM test comparing strategy returns (mean return difference)."""
    d = ret1.values - ret2.values
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 50:
        return np.nan, np.nan

    d_bar = np.mean(d)
    gamma0 = np.var(d, ddof=1)
    hac_var = gamma0
    for k in range(1, max(h + 1, 2)):
        if k >= n:
            break
        gamma_k = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        hac_var += 2 * (1 - k / max(h + 1, 2)) * gamma_k

    se = np.sqrt(max(hac_var, 1e-20) / n)
    if se < 1e-12:
        return np.nan, np.nan

    t_stat = d_bar / se
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    return float(t_stat), float(p_val)


def sharpe_diff_test(ret1, ret2, rf_annual=0.02):
    """Memmel (2003) test for Sharpe ratio difference."""
    r1 = ret1.values
    r2 = ret2.values
    valid = np.isfinite(r1) & np.isfinite(r2)
    r1, r2 = r1[valid], r2[valid]
    n = len(r1)
    if n < 50:
        return np.nan, np.nan

    rf = rf_annual / 252
    mu1 = np.mean(r1) - rf
    mu2 = np.mean(r2) - rf
    s1 = np.std(r1, ddof=1)
    s2 = np.std(r2, ddof=1)
    sr1 = mu1 / s1
    sr2 = mu2 / s2

    rho = np.corrcoef(r1, r2)[0, 1]
    se = np.sqrt((2 * (1 - rho) + 0.5 * (sr1**2 + sr2**2 - 2 * sr1 * sr2 * rho)) / n)
    if se < 1e-12:
        return np.nan, np.nan

    z = (sr1 - sr2) / se
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    return float(z), float(p)


# ============================================================
# 8. CROSS-OOS EVALUATION
# ============================================================
print("\n[6/8] Cross-OOS performance evaluation...")

# Focus on blend strategies (primary) + SPY-only for comparison
blend_cols = ['BH_Blend', 'VIX_VT_Blend', 'GJRX_VT_Blend', 'GJR_VT_Blend', 'Hybrid_VT_Blend']
spy_cols = ['BH_SPY', 'VIX_VT_SPY', 'GJRX_VT_SPY', 'GJR_VT_SPY', 'Hybrid_VT_SPY']

cross_oos_results = {}

for period in OOS_PERIODS:
    pname = period['name']
    mask = (strat_returns.index >= period['start']) & (strat_returns.index <= period['end'])
    period_ret = strat_returns[mask]

    if len(period_ret) < 50:
        print(f"  {pname}: SKIP ({len(period_ret)} obs)")
        continue

    print(f"\n  === {pname} ({len(period_ret)} obs) ===")

    # Performance metrics (blend only for display)
    perf = evaluate_performance(period_ret[blend_cols])
    net = compute_net_sharpe(period_ret[blend_cols], strategy_weights)
    for col in perf:
        if col in net:
            perf[col].update(net[col])

    # Also compute SPY-only
    perf_spy = evaluate_performance(period_ret[spy_cols])
    net_spy = compute_net_sharpe(period_ret[spy_cols], strategy_weights)
    for col in perf_spy:
        if col in net_spy:
            perf_spy[col].update(net_spy[col])

    # DM test: GJRX_VT vs VIX_VT (our key comparison)
    dm_gjrx_vs_vix_blend = dm_test_returns(period_ret['GJRX_VT_Blend'], period_ret['VIX_VT_Blend'])
    dm_gjr_vs_vix_blend = dm_test_returns(period_ret['GJR_VT_Blend'], period_ret['VIX_VT_Blend'])
    dm_hybrid_vs_vix_blend = dm_test_returns(period_ret['Hybrid_VT_Blend'], period_ret['VIX_VT_Blend'])

    # Sharpe difference tests
    sd_gjrx_vs_vix = sharpe_diff_test(period_ret['GJRX_VT_Blend'], period_ret['VIX_VT_Blend'])
    sd_gjr_vs_vix = sharpe_diff_test(period_ret['GJR_VT_Blend'], period_ret['VIX_VT_Blend'])
    sd_hybrid_vs_vix = sharpe_diff_test(period_ret['Hybrid_VT_Blend'], period_ret['VIX_VT_Blend'])

    # Display
    print(f"  {'Strategy':<20s} {'Sharpe':>8s} {'NetShrp':>8s} {'AnnRet%':>8s} {'AnnVol%':>8s} {'MaxDD%':>8s} {'Calmar':>8s}")
    print(f"  {'-'*72}")
    for col in blend_cols:
        if col in perf:
            p = perf[col]
            ns = p.get('net_sharpe', '-')
            ns_str = f"{ns:.4f}" if isinstance(ns, (float, int)) else str(ns)
            print(f"  {col:<20s} {p['sharpe']:8.4f} {ns_str:>8s} {p['ann_return_pct']:8.2f} "
                  f"{p['ann_vol_pct']:8.2f} {p['max_drawdown_pct']:8.2f} {p['calmar']:8.4f}")

    print(f"\n  DM tests vs VIX_VT_Blend:")
    print(f"    GJRX_VT:   t={dm_gjrx_vs_vix_blend[0]:.3f}, p={dm_gjrx_vs_vix_blend[1]:.4f}")
    print(f"    GJR_VT:    t={dm_gjr_vs_vix_blend[0]:.3f}, p={dm_gjr_vs_vix_blend[1]:.4f}")
    print(f"    Hybrid_VT: t={dm_hybrid_vs_vix_blend[0]:.3f}, p={dm_hybrid_vs_vix_blend[1]:.4f}")

    print(f"  Sharpe diff tests vs VIX_VT_Blend:")
    print(f"    GJRX_VT:   z={sd_gjrx_vs_vix[0]:.3f}, p={sd_gjrx_vs_vix[1]:.4f}")
    print(f"    GJR_VT:    z={sd_gjr_vs_vix[0]:.3f}, p={sd_gjr_vs_vix[1]:.4f}")
    print(f"    Hybrid_VT: z={sd_hybrid_vs_vix[0]:.3f}, p={sd_hybrid_vs_vix[1]:.4f}")

    cross_oos_results[pname] = {
        'n_obs': len(period_ret),
        'blend_performance': perf,
        'spy_performance': perf_spy,
        'tests_vs_vix_vt': {
            'GJRX_VT_DM': {'t_stat': dm_gjrx_vs_vix_blend[0], 'p_value': dm_gjrx_vs_vix_blend[1]},
            'GJR_VT_DM': {'t_stat': dm_gjr_vs_vix_blend[0], 'p_value': dm_gjr_vs_vix_blend[1]},
            'Hybrid_VT_DM': {'t_stat': dm_hybrid_vs_vix_blend[0], 'p_value': dm_hybrid_vs_vix_blend[1]},
            'GJRX_VT_Sharpe_diff': {'z_stat': sd_gjrx_vs_vix[0], 'p_value': sd_gjrx_vs_vix[1]},
            'GJR_VT_Sharpe_diff': {'z_stat': sd_gjr_vs_vix[0], 'p_value': sd_gjr_vs_vix[1]},
            'Hybrid_VT_Sharpe_diff': {'z_stat': sd_hybrid_vs_vix[0], 'p_value': sd_hybrid_vs_vix[1]},
        },
    }


# ============================================================
# 9. FULL-PERIOD EVALUATION
# ============================================================
print("\n[7/8] Full-period evaluation...")

full_periods = {
    'Full (2008-2025)': ('2008-01-01', '2025-12-31'),
    'Post-GFC (2010-2025)': ('2010-01-01', '2025-12-31'),
}

full_period_results = {}

for period_name, (p_start, p_end) in full_periods.items():
    mask = (strat_returns.index >= p_start) & (strat_returns.index <= p_end)
    period_ret = strat_returns[mask]
    if len(period_ret) < 50:
        continue

    perf = evaluate_performance(period_ret)
    net = compute_net_sharpe(period_ret, strategy_weights)
    for col in perf:
        if col in net:
            perf[col].update(net[col])

    # DM tests vs VIX_VT_Blend
    dm_gjrx = dm_test_returns(period_ret['GJRX_VT_Blend'], period_ret['VIX_VT_Blend'])
    dm_gjr = dm_test_returns(period_ret['GJR_VT_Blend'], period_ret['VIX_VT_Blend'])
    dm_hybrid = dm_test_returns(period_ret['Hybrid_VT_Blend'], period_ret['VIX_VT_Blend'])
    sd_gjrx = sharpe_diff_test(period_ret['GJRX_VT_Blend'], period_ret['VIX_VT_Blend'])
    sd_gjr = sharpe_diff_test(period_ret['GJR_VT_Blend'], period_ret['VIX_VT_Blend'])
    sd_hybrid = sharpe_diff_test(period_ret['Hybrid_VT_Blend'], period_ret['VIX_VT_Blend'])

    print(f"\n  === {period_name} ({len(period_ret)} obs) ===")
    print(f"  {'Strategy':<20s} {'Sharpe':>8s} {'NetShrp':>8s} {'AnnRet%':>8s} {'AnnVol%':>8s} {'MaxDD%':>8s} {'Calmar':>8s} {'Sortino':>8s}")
    print(f"  {'-'*80}")
    for col in blend_cols + spy_cols:
        if col in perf:
            p = perf[col]
            ns = p.get('net_sharpe', '-')
            ns_str = f"{ns:.4f}" if isinstance(ns, (float, int)) else str(ns)
            print(f"  {col:<20s} {p['sharpe']:8.4f} {ns_str:>8s} {p['ann_return_pct']:8.2f} "
                  f"{p['ann_vol_pct']:8.2f} {p['max_drawdown_pct']:8.2f} {p['calmar']:8.4f} {p['sortino']:8.4f}")

    print(f"\n  DM tests (blend, vs VIX_VT_Blend):")
    print(f"    GJRX_VT:   t={dm_gjrx[0]:.3f}, p={dm_gjrx[1]:.4f}")
    print(f"    GJR_VT:    t={dm_gjr[0]:.3f}, p={dm_gjr[1]:.4f}")
    print(f"    Hybrid_VT: t={dm_hybrid[0]:.3f}, p={dm_hybrid[1]:.4f}")
    print(f"  Sharpe diff tests (blend, vs VIX_VT_Blend):")
    print(f"    GJRX_VT:   z={sd_gjrx[0]:.3f}, p={sd_gjrx[1]:.4f}")
    print(f"    GJR_VT:    z={sd_gjr[0]:.3f}, p={sd_gjr[1]:.4f}")
    print(f"    Hybrid_VT: z={sd_hybrid[0]:.3f}, p={sd_hybrid[1]:.4f}")

    full_period_results[period_name] = {
        'n_obs': len(period_ret),
        'performance': perf,
        'tests_vs_vix_vt': {
            'GJRX_VT_DM': {'t_stat': dm_gjrx[0], 'p_value': dm_gjrx[1]},
            'GJR_VT_DM': {'t_stat': dm_gjr[0], 'p_value': dm_gjr[1]},
            'Hybrid_VT_DM': {'t_stat': dm_hybrid[0], 'p_value': dm_hybrid[1]},
            'GJRX_VT_Sharpe_diff': {'z_stat': sd_gjrx[0], 'p_value': sd_gjrx[1]},
            'GJR_VT_Sharpe_diff': {'z_stat': sd_gjr[0], 'p_value': sd_gjr[1]},
            'Hybrid_VT_Sharpe_diff': {'z_stat': sd_hybrid[0], 'p_value': sd_hybrid[1]},
        },
    }


# ============================================================
# 10. SUMMARY & CROSS-OOS WIN COUNTS
# ============================================================
print("\n[8/8] Cross-OOS summary...")

# Count how many periods each strategy beats VIX_VT_Blend in Sharpe
sharpe_wins = {'GJRX_VT_Blend': 0, 'GJR_VT_Blend': 0, 'Hybrid_VT_Blend': 0}
sharpe_values = {'VIX_VT_Blend': [], 'GJRX_VT_Blend': [], 'GJR_VT_Blend': [], 'Hybrid_VT_Blend': []}

for pname, pdata in cross_oos_results.items():
    perf = pdata['blend_performance']
    vix_sharpe = perf.get('VIX_VT_Blend', {}).get('sharpe', None)
    if vix_sharpe is None:
        continue

    sharpe_values['VIX_VT_Blend'].append(vix_sharpe)
    for name in ['GJRX_VT_Blend', 'GJR_VT_Blend', 'Hybrid_VT_Blend']:
        s = perf.get(name, {}).get('sharpe', None)
        if s is not None:
            sharpe_values[name].append(s)
            if s > vix_sharpe:
                sharpe_wins[name] += 1

n_periods = len(sharpe_values['VIX_VT_Blend'])

print(f"\n  Cross-OOS Sharpe wins vs VIX_VT (out of {n_periods} periods):")
for name, wins in sharpe_wins.items():
    avg_s = np.mean(sharpe_values[name]) if sharpe_values[name] else 0
    vix_avg_s = np.mean(sharpe_values['VIX_VT_Blend'])
    print(f"    {name:20s}: {wins}/{n_periods} wins, avg Sharpe={avg_s:.4f} vs VIX avg={vix_avg_s:.4f}")

# Harvey (2016) check
print(f"\n  Harvey (2016) t>3.0 threshold check:")
for pname, pdata in cross_oos_results.items():
    tests = pdata['tests_vs_vix_vt']
    for test_name in ['GJRX_VT_DM', 'GJR_VT_DM', 'Hybrid_VT_DM']:
        t_val = tests[test_name]['t_stat']
        passes = abs(t_val) > 3.0 if not np.isnan(t_val) else False
        label = "PASS" if passes else "fail"
        print(f"    {pname} / {test_name}: t={t_val:.3f} [{label}]")


# ============================================================
# 11. KEY INSIGHT: WHY GJR-X(VIX) ACTS LIKE VIX
# ============================================================
print("\n" + "=" * 70)
print("KEY INSIGHT: Why GJR-X(VIX) σ ≈ VIX-scaled volatility")
print("=" * 70)

# Compare σ estimates across regimes
if len(common_valid) > 252:
    # Low VIX regime (<15) vs High VIX (>25)
    low_vix = common_valid[common_valid['VIX'] < 15]
    mid_vix = common_valid[(common_valid['VIX'] >= 15) & (common_valid['VIX'] < 25)]
    high_vix = common_valid[common_valid['VIX'] >= 25]

    print(f"\n  Regime analysis (n_low={len(low_vix)}, n_mid={len(mid_vix)}, n_high={len(high_vix)}):")
    for regime_name, regime_data in [('Low VIX <15', low_vix), ('Mid VIX 15-25', mid_vix), ('High VIX >25', high_vix)]:
        if len(regime_data) < 10:
            continue
        # Weight comparison
        w_vix = (TARGET_VOL / regime_data['VIX']).clip(upper=1.0)
        w_gjrx = (TARGET_VOL / regime_data['sigma_gjrx']).clip(upper=1.0)
        w_gjr = (TARGET_VOL / regime_data['sigma_gjr']).clip(upper=1.0)
        w_diff_gjrx_vix = (w_gjrx - w_vix).mean()
        w_diff_gjr_vix = (w_gjr - w_vix).mean()
        print(f"  {regime_name:15s}: VIX_w={w_vix.mean():.3f}, GJRX_w={w_gjrx.mean():.3f}, "
              f"GJR_w={w_gjr.mean():.3f} | GJRX-VIX={w_diff_gjrx_vix:+.3f}, GJR-VIX={w_diff_gjr_vix:+.3f}")


# ============================================================
# 12. SAVE RESULTS
# ============================================================
t_total = time.time() - t_global
print(f"\nTotal time: {t_total:.1f}s")

# Determine overall conclusion
avg_sharpe_vix = np.mean(sharpe_values['VIX_VT_Blend']) if sharpe_values['VIX_VT_Blend'] else 0
avg_sharpe_gjrx = np.mean(sharpe_values['GJRX_VT_Blend']) if sharpe_values['GJRX_VT_Blend'] else 0
avg_sharpe_gjr = np.mean(sharpe_values['GJR_VT_Blend']) if sharpe_values['GJR_VT_Blend'] else 0
avg_sharpe_hybrid = np.mean(sharpe_values['Hybrid_VT_Blend']) if sharpe_values['Hybrid_VT_Blend'] else 0

best_alt = max(avg_sharpe_gjrx, avg_sharpe_gjr, avg_sharpe_hybrid)
best_name = 'GJRX' if best_alt == avg_sharpe_gjrx else ('GJR' if best_alt == avg_sharpe_gjr else 'Hybrid')

if best_alt > avg_sharpe_vix:
    conclusion = f"GJR-X(VIX) VT shows promise: {best_name} avg Sharpe={best_alt:.4f} vs VIX {avg_sharpe_vix:.4f}, but check Harvey threshold"
else:
    conclusion = f"12/VIX remains dominant: VIX avg Sharpe={avg_sharpe_vix:.4f} vs best alt ({best_name})={best_alt:.4f}. K440/K470 pattern confirmed."

# Check if any full-period test passes Harvey
harvey_passes = []
for pname, pdata in full_period_results.items():
    for tname, tvals in pdata['tests_vs_vix_vt'].items():
        if 'DM' in tname and abs(tvals.get('t_stat', 0)) > 3.0:
            harvey_passes.append(f"{pname}/{tname}")

results = {
    'experiment_id': 'K488',
    'title': 'GJR-GARCH-X(VIX) Based Volatility Targeting Strategy',
    'research_question': 'Can GJR-X(VIX) improve VT over 12/VIX? (K440/K470: prediction≠trading, but GJR-X contains VIX risk premium)',
    'hypothesis': 'GJR-X(VIX) σ contains VIX risk premium via δ·VIX²/252 → may match 12/VIX conservatism while being more precise',
    'proposed_by': 'User',
    'data_source': 'yfinance (SPY, GLD, ^VIX) — empirical data',
    'data_period': f"{feat.index[0].date()} to {feat.index[-1].date()}",
    'references': [
        'Moreira & Muir (2017) JoF 72(4):1611-1644 — Volatility-Managed Portfolios',
        'Bollerslev, Tauchen, Zhou (2009) RFS — VRP and returns',
        'Patton (2011) JoE — Volatility forecast comparison',
        'Memmel (2003) — Sharpe ratio difference test',
        'Harvey, Liu, Zhu (2016) RFS — t>3.0 threshold for new factor claims',
        'K486: GJR-X(VIX) breaks impossible triangle (forecasting -17% + VaR 5/5)',
        'K440: VRP-VT null result (prediction ≠ trading)',
        'K470: HAR-VT null result (prediction ≠ trading)',
    ],
    'configuration': {
        'IS_window': IS_WINDOW,
        'refit_interval': REFIT_INTERVAL,
        'target_vol_pct': TARGET_VOL,
        'weight_cap': 1.0,
        'rf_annual': RF_ANNUAL,
        'tx_bps': TX_BPS,
        'n_oos_periods': len(OOS_PERIODS),
        'assets': 'SPY + GLD (50/50 blend)',
        'strategies': [
            'BH_Blend: Buy & Hold 50/50 SPY+GLD',
            'VIX_VT_Blend: w = 12/VIX (baseline)',
            'GJRX_VT_Blend: w = 12/σ_GARCHX (annualized)',
            'GJR_VT_Blend: w = 12/σ_GJR (control)',
            'Hybrid_VT_Blend: w = 12/(0.5*VIX + 0.5*σ_GARCHX)',
        ],
        'models': {
            'GJR-GARCH-X(VIX)': 'h_t = ω + α·ε²_{t-1} + γ·I(ε<0)·ε²_{t-1} + β·h_{t-1} + δ·VIX²_{t-1}/252',
            'GJR-GARCH(1,1)': 'Standard GJR-GARCH(1,1) via arch package (Student-t)',
        },
    },
    'diagnostics': diagnostics,
    'vol_forecast_diagnostics': {
        'n_refits': n_refits,
        'fit_failures_gjrx': fit_failures_gjrx,
        'fit_failures_gjr': fit_failures_gjr,
        'sigma_gjrx_mean': round(float(valid_gjrx.mean()), 2),
        'sigma_gjrx_std': round(float(valid_gjrx.std()), 2),
        'sigma_gjr_mean': round(float(valid_gjr.mean()), 2),
        'sigma_gjr_std': round(float(valid_gjr.std()), 2),
        'corr_gjrx_vix': round(corr_gjrx_vix, 4),
        'corr_gjr_vix': round(corr_gjr_vix, 4),
        'corr_gjrx_gjr': round(corr_gjrx_gjr, 4),
        'delta_stats': {
            'mean': round(float(np.mean(deltas)), 4) if delta_history else None,
            'std': round(float(np.std(deltas)), 4) if delta_history else None,
            'min': round(float(np.min(deltas)), 4) if delta_history else None,
            'max': round(float(np.max(deltas)), 4) if delta_history else None,
        },
    },
    'cross_oos_results': cross_oos_results,
    'full_period_results': full_period_results,
    'cross_oos_summary': {
        'n_periods': n_periods,
        'sharpe_wins_vs_vix': {k: v for k, v in sharpe_wins.items()},
        'avg_sharpe': {k: round(np.mean(v), 4) for k, v in sharpe_values.items() if v},
    },
    'harvey_threshold_passes': harvey_passes,
    'conclusion': conclusion,
    'limitations': [
        'Rolling GARCH refitting every 63 days (quarterly) may miss short-term regime changes',
        'Transaction costs assumed at 3 bps; actual costs may vary',
        'GLD available only from Nov 2004; limits pre-GFC analysis',
        'Weight cap at 100% prevents leverage; results may differ with leverage',
        'DM test on strategy returns tests mean difference, not Sharpe difference directly',
        'Single target vol (12%) — results may differ at other targets',
    ],
    'runtime_seconds': round(t_total, 1),
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

# Save
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(script_dir, 'k488_gjrx_vt_strategy_results.json')
with open(out_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {out_path}")
print(f"\n{'='*70}")
print(f"CONCLUSION: {conclusion}")
print(f"Harvey passes: {harvey_passes if harvey_passes else 'NONE'}")
print(f"{'='*70}")
