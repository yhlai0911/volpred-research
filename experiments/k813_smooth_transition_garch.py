"""
K813: Smooth Transition GARCH (STGARCH) with VIX Transition Variable
====================================================================
[提出: 用戶 (Bayesian 方法論方向), 執行: Claude]

背景:
- K431: STGARCH 在 SPY 上 OOS 未顯著勝過 GJR (QLIKE diff 9.362%)
- K427: GARCH 參數有結構性斷裂 → Smooth Transition 可能比 abrupt regime switch 更合適
- 本實驗改進 K431：(1) GJR baseline 含 leverage (2) expanding window (3) LRT
- González-Rivera (1998), Hagerud (1997): 允許 GARCH 參數漸進轉換

模型:
  Baseline: GJR-GARCH(1,1) (standard MLE via arch package)
  ST-GARCH:
    σ²_t = (ω₁ + α₁ε²_{t-1} + γ₁I_{t-1}ε²_{t-1} + β₁σ²_{t-1}) × (1-G)
          + (ω₂ + α₂ε²_{t-1} + γ₂I_{t-1}ε²_{t-1} + β₂σ²_{t-1}) × G
    G = 1 / (1 + exp(-γ_tr × (VIX_{t-1} - c)))
    γ_tr = transition speed, c = threshold (VIX level)
    I_{t-1} = 1 if ε_{t-1} < 0 (leverage indicator)

  10 parameters: ω₁, α₁, γ₁_gjr, β₁, ω₂, α₂, γ₂_gjr, β₂, γ_transition, c

資產: SPY | 資料: 2005-01-01 ~ 2026-04-01 (yfinance)
OOS: 2023-01-01 ~ 2024-12-31 | Window: expanding (from 2005)
Refit: 每 63 天

評估:
  - QLIKE on r² (Patton 2011 proxy-robust)
  - Spearman rank correlation
  - DM test (Harvey t>3.0)
  - LRT: ST-GARCH vs GJR (nested when γ_transition → 0)

References:
  - González-Rivera (1998) J. Business & Economic Statistics — STGARCH original
  - Hagerud (1997) PhD thesis — Logistic STGARCH
  - Patton (2011) J. Econometrics 160 — proxy-robust loss functions
  - Harvey et al. (2016) — multiple testing threshold t>3.0
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy import stats
import yfinance as yf
import json, time, warnings, signal as signal_module
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch
from arch import arch_model

# Use project evaluation framework
import sys
sys.path.insert(0, '/Users/yhlai0911/Desktop/volpred-research')
from volpred.stats.model_evaluation import (
    dm_test, qlike_pointwise, spearman_corr, qlike
)

warnings.filterwarnings('ignore')

# ============================================================
# TIMEOUT PROTECTION
# ============================================================
class TimeoutError(Exception):
    pass

def timeout_handler(signum, frame):
    raise TimeoutError("MLE optimization timed out")

# ============================================================
# STGARCH CORE: Variance recursion with GJR leverage in both regimes
# ============================================================
def stgarch_filter(params, returns, vix_lagged):
    """
    STGARCH variance recursion with GJR leverage in both regimes.
    params: [mu, w1, a1, g1, b1, w2, a2, g2, b2, gamma_tr, c]
    Returns: (h_array, eps_array)
    """
    mu, w1, a1, g1, b1, w2, a2, g2, b2, gam_tr, c = params
    T = len(returns)
    eps = returns - mu
    h = np.empty(T)
    h[0] = max(np.var(eps[:min(250, T)]), 1e-6)

    for t in range(1, T):
        # Logistic transition function using lagged VIX
        arg = gam_tr * (vix_lagged[t] - c)
        if arg > 500:
            G = 1.0
        elif arg < -500:
            G = 0.0
        else:
            G = 1.0 / (1.0 + np.exp(-arg))

        # Leverage indicator
        I_neg = 1.0 if eps[t-1] < 0 else 0.0
        e2 = eps[t-1] ** 2

        # Low-VIX regime
        h_low = w1 + a1 * e2 + g1 * I_neg * e2 + b1 * h[t-1]
        # High-VIX regime
        h_high = w2 + a2 * e2 + g2 * I_neg * e2 + b2 * h[t-1]

        # Smooth transition
        ht = (1.0 - G) * h_low + G * h_high
        h[t] = max(ht, 1e-8)

    return h, eps


def stgarch_negll(params, returns, vix_lagged):
    """Negative Gaussian log-likelihood for STGARCH.
    Includes -(T/2)*log(2*pi) constant for comparability with arch package.
    """
    try:
        h, eps = stgarch_filter(params, returns, vix_lagged)
        T = len(returns)
        ll = -0.5 * T * np.log(2 * np.pi) - 0.5 * np.sum(np.log(h) + eps**2 / h)
        return -ll if np.isfinite(ll) else 1e10
    except:
        return 1e10


def fit_stgarch(returns, vix_lagged, n_starts=8, timeout_sec=60):
    """
    Fit STGARCH with multiple random starts and timeout protection.
    Returns params dict or None.
    """
    T = len(returns)

    # Bounds: [mu, w1, a1, g1, b1, w2, a2, g2, b2, gamma_tr, c]
    bounds = [
        (-1, 1),         # mu
        (1e-6, 5),       # omega1
        (1e-6, 0.5),     # alpha1
        (0.0, 0.5),      # gamma1 (GJR leverage, >= 0)
        (0.01, 0.999),   # beta1
        (1e-6, 5),       # omega2
        (1e-6, 0.5),     # alpha2
        (0.0, 0.5),      # gamma2 (GJR leverage)
        (0.01, 0.999),   # beta2
        (0.01, 200),     # gamma_transition
        (10.0, 50.0),    # c (VIX threshold)
    ]

    best = None
    np.random.seed(42)
    start_time = time.time()

    for i in range(n_starts):
        # Check timeout
        if time.time() - start_time > timeout_sec:
            print(f"    Timeout after {i} starts, using best so far")
            break

        x0 = [
            np.mean(returns) + np.random.randn() * 0.01,
            np.random.uniform(0.005, 0.1),   # w1
            np.random.uniform(0.02, 0.15),   # a1
            np.random.uniform(0.01, 0.15),   # g1 (GJR)
            np.random.uniform(0.7, 0.95),    # b1
            np.random.uniform(0.005, 0.2),   # w2
            np.random.uniform(0.02, 0.2),    # a2
            np.random.uniform(0.01, 0.2),    # g2 (GJR)
            np.random.uniform(0.6, 0.95),    # b2
            np.random.uniform(0.1, 50),      # gamma_tr
            np.random.uniform(15, 35),       # c
        ]
        try:
            r = minimize(
                stgarch_negll, x0, args=(returns, vix_lagged),
                method='L-BFGS-B', bounds=bounds,
                options={'maxiter': 5000, 'ftol': 1e-10}
            )
            if r.success and (best is None or r.fun < best.fun):
                best = r
        except:
            pass

    if best is None:
        return None

    p = best.x
    names = ['mu', 'omega1', 'alpha1', 'gamma1_gjr', 'beta1',
             'omega2', 'alpha2', 'gamma2_gjr', 'beta2',
             'gamma_transition', 'c']
    d = {n: float(v) for n, v in zip(names, p)}

    # Persistence for each regime (GJR: alpha + gamma/2 + beta)
    d['persistence_low'] = d['alpha1'] + d['gamma1_gjr'] / 2 + d['beta1']
    d['persistence_high'] = d['alpha2'] + d['gamma2_gjr'] / 2 + d['beta2']
    d['loglik'] = float(-best.fun)
    d['n_params'] = 11
    d['aic'] = 2 * 11 + 2 * best.fun
    d['bic'] = 11 * np.log(T) + 2 * best.fun
    d['converged'] = True
    d['T'] = T
    return d


def fit_stgarch_fixed_gamma(returns, vix_lagged, fixed_gamma, timeout_sec=30):
    """
    Simplified STGARCH with fixed transition speed (fallback if full model times out).
    """
    T = len(returns)
    bounds = [
        (-1, 1), (1e-6, 5), (1e-6, 0.5), (0.0, 0.5), (0.01, 0.999),
        (1e-6, 5), (1e-6, 0.5), (0.0, 0.5), (0.01, 0.999),
        (10.0, 50.0),
    ]

    def negll_fixed(params_reduced, ret, vix):
        full_params = list(params_reduced[:9]) + [fixed_gamma] + [params_reduced[9]]
        return stgarch_negll(full_params, ret, vix)

    best = None
    np.random.seed(123)
    start_time = time.time()

    for i in range(6):
        if time.time() - start_time > timeout_sec:
            break
        x0 = [
            np.mean(returns) + np.random.randn() * 0.01,
            np.random.uniform(0.005, 0.1), np.random.uniform(0.02, 0.15),
            np.random.uniform(0.01, 0.15), np.random.uniform(0.7, 0.95),
            np.random.uniform(0.005, 0.2), np.random.uniform(0.02, 0.2),
            np.random.uniform(0.01, 0.2), np.random.uniform(0.6, 0.95),
            np.random.uniform(15, 35),
        ]
        try:
            r = minimize(negll_fixed, x0, args=(returns, vix_lagged),
                        method='L-BFGS-B', bounds=bounds,
                        options={'maxiter': 3000, 'ftol': 1e-10})
            if r.success and (best is None or r.fun < best.fun):
                best = r
        except:
            pass

    if best is None:
        return None

    p = best.x
    names = ['mu', 'omega1', 'alpha1', 'gamma1_gjr', 'beta1',
             'omega2', 'alpha2', 'gamma2_gjr', 'beta2', 'c']
    d = {n: float(v) for n, v in zip(names, p)}
    d['gamma_transition'] = float(fixed_gamma)
    d['persistence_low'] = d['alpha1'] + d['gamma1_gjr'] / 2 + d['beta1']
    d['persistence_high'] = d['alpha2'] + d['gamma2_gjr'] / 2 + d['beta2']
    d['loglik'] = float(-best.fun)
    d['n_params'] = 10  # one fewer (gamma fixed)
    d['aic'] = 2 * 10 + 2 * best.fun
    d['bic'] = 10 * np.log(T) + 2 * best.fun
    d['converged'] = True
    d['T'] = T
    d['fixed_gamma'] = True
    return d


# ============================================================
# OOS FORECAST: Expanding window with refit
# ============================================================
def stgarch_1step_forecast(params, h_prev, eps_prev, vix_prev):
    """Single 1-step ahead STGARCH forecast."""
    mu, w1, a1, g1, b1, w2, a2, g2, b2, gam_tr, c = params
    arg = gam_tr * (vix_prev - c)
    if arg > 500:
        G = 1.0
    elif arg < -500:
        G = 0.0
    else:
        G = 1.0 / (1.0 + np.exp(-arg))

    I_neg = 1.0 if eps_prev < 0 else 0.0
    e2 = eps_prev ** 2

    h_low = w1 + a1 * e2 + g1 * I_neg * e2 + b1 * h_prev
    h_high = w2 + a2 * e2 + g2 * I_neg * e2 + b2 * h_prev
    h = (1.0 - G) * h_low + G * h_high
    return max(h, 1e-8)


def rolling_stgarch_oos(returns, vix_lagged, dates, oos_start, oos_end,
                        refit_every=63, use_expanding=True):
    """
    OOS forecast with expanding window and periodic refit.
    Uses VIX_{t-1} as transition variable (no lookahead).
    """
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]

    if len(oos_idx) == 0:
        return np.array([]), np.array([]), []

    forecasts, realized, fdates = [], [], []
    params = None
    last_refit = -refit_every
    h_t = None
    eps_t = None
    n_refit = 0
    n_fallback = 0

    for count, idx in enumerate(oos_idx):
        # Refit if needed (expanding window: always start from 0)
        if idx - last_refit >= refit_every or params is None:
            if use_expanding:
                est_ret = returns[:idx]
                est_vix = vix_lagged[:idx]
            else:
                est_start = max(0, idx - 2000)
                est_ret = returns[est_start:idx]
                est_vix = vix_lagged[est_start:idx]

            # Try full STGARCH first with timeout
            d = fit_stgarch(est_ret, est_vix, n_starts=4, timeout_sec=45)

            if d is None:
                # Fallback: fixed gamma
                d = fit_stgarch_fixed_gamma(est_ret, est_vix, fixed_gamma=5.0, timeout_sec=20)
                if d is not None:
                    n_fallback += 1

            if d is not None:
                params = [d[k] for k in [
                    'mu', 'omega1', 'alpha1', 'gamma1_gjr', 'beta1',
                    'omega2', 'alpha2', 'gamma2_gjr', 'beta2',
                    'gamma_transition', 'c'
                ]]
                last_refit = idx
                n_refit += 1

                # Re-initialize state by running filter on recent data
                lookback = min(300, idx)
                h_arr, eps_arr = stgarch_filter(
                    params, returns[idx-lookback:idx], vix_lagged[idx-lookback:idx]
                )
                h_t = h_arr[-1]
                eps_t = eps_arr[-1]
            elif params is None:
                continue

        # 1-step forecast using VIX_{t-1} (signal.shift(1) equivalent — no lookahead)
        vix_prev = vix_lagged[idx]  # This is already VIX_{t-1} due to data alignment
        h_forecast = stgarch_1step_forecast(params, h_t, eps_t, vix_prev)

        forecasts.append(h_forecast)
        realized.append(returns[idx] ** 2)
        fdates.append(dates[idx])

        # Update state with realized return
        mu = params[0]
        eps_t = returns[idx] - mu
        h_t = stgarch_1step_forecast(params, h_t, eps_t, vix_prev)

        if (count + 1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)} done")

    print(f"    Refits: {n_refit} (fallback: {n_fallback})")
    return np.array(forecasts), np.array(realized), fdates


def rolling_gjr_oos(returns_s, dates, oos_start, oos_end,
                    refit_every=63, use_expanding=True):
    """Rolling OOS for GJR-GARCH(1,1) using arch package. Expanding window."""
    oos_mask = (dates >= oos_start) & (dates <= oos_end)
    oos_idx = np.where(oos_mask)[0]

    forecasts, realized, fdates = [], [], []
    current_params = None
    last_refit = -refit_every

    for count, idx in enumerate(oos_idx):
        if idx - last_refit >= refit_every or current_params is None:
            if use_expanding:
                est_ret = returns_s.iloc[:idx]
            else:
                est_start = max(0, idx - 2000)
                est_ret = returns_s.iloc[est_start:idx]
            try:
                am = arch_model(est_ret, vol='GARCH', p=1, o=1, q=1,
                               mean='Constant', dist='normal')
                res = am.fit(disp='off', options={'maxiter': 5000})
                current_params = res.params
                last_refit = idx
            except:
                if current_params is None:
                    continue

        # Filter on recent data to get conditional variance
        lookback = min(500, idx)
        recent = returns_s.iloc[idx-lookback:idx+1]
        try:
            am2 = arch_model(recent, vol='GARCH', p=1, o=1, q=1,
                            mean='Constant', dist='normal')
            res2 = am2.fix(current_params)
            h_f = res2.conditional_volatility.iloc[-1] ** 2
        except:
            if len(forecasts) > 0:
                h_f = forecasts[-1]
            else:
                continue

        forecasts.append(h_f)
        realized.append(returns_s.iloc[idx] ** 2)
        fdates.append(dates[idx])

        if (count + 1) % 100 == 0:
            print(f"    {count+1}/{len(oos_idx)} done")

    return np.array(forecasts), np.array(realized), fdates


# ============================================================
# LIKELIHOOD RATIO TEST
# ============================================================
def lrt_test(ll_unrestricted, ll_restricted, df_diff):
    """
    Likelihood ratio test.
    H0: restricted model is adequate
    Returns (LR_stat, p_value, df)
    """
    lr = 2 * (ll_unrestricted - ll_restricted)
    p = 1 - stats.chi2.cdf(lr, df_diff) if lr > 0 else 1.0
    return float(lr), float(p), df_diff


# ============================================================
# MAIN EXPERIMENT
# ============================================================
if __name__ == '__main__':
    print("=" * 72)
    print("K813: Smooth Transition GARCH (STGARCH) — VIX Transition Variable")
    print("=" * 72)
    t_start = time.time()

    # --- Data Download ---
    print("\n[DATA] Downloading SPY and VIX...")
    spy = yf.download('SPY', start='2005-01-01', end='2026-04-01', progress=False)
    vix_data = yf.download('^VIX', start='2005-01-01', end='2026-04-01', progress=False)

    for df in [spy, vix_data]:
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

    spy['Return'] = spy['Close'].pct_change() * 100
    spy = spy.dropna(subset=['Return'])
    vix_data = vix_data[['Close']].rename(columns={'Close': 'VIX'})

    data = spy[['Close', 'Return']].join(vix_data['VIX'], how='inner').dropna()

    # Create lagged VIX (VIX_{t-1}) — signal.shift(1) equivalent
    data['VIX_lag1'] = data['VIX'].shift(1)
    data = data.dropna()

    ret_arr = data['Return'].values
    vix_arr = data['VIX'].values
    vix_lag_arr = data['VIX_lag1'].values
    dates_arr = data.index
    ret_series = data['Return']

    print(f"Data: {dates_arr[0].strftime('%Y-%m-%d')} to {dates_arr[-1].strftime('%Y-%m-%d')}")
    print(f"Total observations: {len(data)}")
    print(f"VIX range: {vix_arr.min():.1f} - {vix_arr.max():.1f}")

    # --- Descriptive Statistics ---
    print("\n" + "-" * 50)
    print("DESCRIPTIVE STATISTICS")
    print("-" * 50)
    desc = {
        'mean': float(np.mean(ret_arr)),
        'std': float(np.std(ret_arr)),
        'skew': float(stats.skew(ret_arr)),
        'kurtosis': float(stats.kurtosis(ret_arr)),
        'min': float(np.min(ret_arr)),
        'max': float(np.max(ret_arr)),
    }
    print(f"  Return: mean={desc['mean']:.4f}%, std={desc['std']:.4f}%, "
          f"skew={desc['skew']:.3f}, kurtosis={desc['kurtosis']:.1f}")

    adf_stat, adf_p = adfuller(ret_arr, maxlag=20, autolag='AIC')[:2]
    arch_stat, arch_p = het_arch(ret_arr, nlags=10)[:2]
    print(f"  ADF test: stat={adf_stat:.2f}, p={adf_p:.6f} {'(stationary)' if adf_p < 0.01 else ''}")
    print(f"  ARCH-LM(10): stat={arch_stat:.1f}, p={arch_p:.2e} {'(ARCH effects present)' if arch_p < 0.05 else ''}")

    desc['adf_stat'] = float(adf_stat)
    desc['adf_p'] = float(adf_p)
    desc['arch_lm_stat'] = float(arch_stat)
    desc['arch_lm_p'] = float(arch_p)

    # --- VIX descriptive ---
    print(f"\n  VIX: mean={np.mean(vix_arr):.1f}, median={np.median(vix_arr):.1f}, "
          f"std={np.std(vix_arr):.1f}")
    print(f"  VIX quantiles: 10%={np.percentile(vix_arr,10):.1f}, "
          f"25%={np.percentile(vix_arr,25):.1f}, "
          f"75%={np.percentile(vix_arr,75):.1f}, "
          f"90%={np.percentile(vix_arr,90):.1f}")

    # ============================================================
    # FULL-SAMPLE ESTIMATION
    # ============================================================
    print("\n" + "=" * 72)
    print("FULL-SAMPLE ESTIMATION")
    print("=" * 72)

    # --- GJR-GARCH Baseline ---
    print("\n[1] GJR-GARCH(1,1) baseline...")
    t0 = time.time()
    gjr_model = arch_model(ret_series, vol='GARCH', p=1, o=1, q=1,
                           mean='Constant', dist='normal')
    gjr_res = gjr_model.fit(disp='off')
    gjr_time = time.time() - t0
    gp = gjr_res.params
    gjr_persistence = gp['alpha[1]'] + gp['gamma[1]'] / 2 + gp['beta[1]']
    print(f"  Time: {gjr_time:.1f}s")
    print(f"  omega={gp['omega']:.6f}, alpha={gp['alpha[1]']:.4f}, "
          f"gamma={gp['gamma[1]']:.4f}, beta={gp['beta[1]']:.4f}")
    print(f"  Persistence: {gjr_persistence:.4f}")
    print(f"  LogLik: {gjr_res.loglikelihood:.1f}, AIC: {gjr_res.aic:.1f}, BIC: {gjr_res.bic:.1f}")

    gjr_fs = {
        'omega': float(gp['omega']),
        'alpha': float(gp['alpha[1]']),
        'gamma_gjr': float(gp['gamma[1]']),
        'beta': float(gp['beta[1]']),
        'persistence': float(gjr_persistence),
        'loglik': float(gjr_res.loglikelihood),
        'aic': float(gjr_res.aic),
        'bic': float(gjr_res.bic),
        'n_params': 5,  # mu, omega, alpha, gamma, beta
    }

    # --- STGARCH Full ---
    print("\n[2] ST-GARCH (VIX transition, full estimation)...")
    t0 = time.time()
    st_full = fit_stgarch(ret_arr, vix_lag_arr, n_starts=10, timeout_sec=120)
    st_full_time = time.time() - t0

    if st_full:
        print(f"  Time: {st_full_time:.1f}s")
        print(f"  Transition: gamma_tr={st_full['gamma_transition']:.3f}, c={st_full['c']:.2f}")
        print(f"  Low-VIX regime (G->0): omega={st_full['omega1']:.4f}, "
              f"alpha={st_full['alpha1']:.4f}, gamma_gjr={st_full['gamma1_gjr']:.4f}, "
              f"beta={st_full['beta1']:.4f}")
        print(f"    Persistence (low): {st_full['persistence_low']:.4f}")
        print(f"  High-VIX regime (G->1): omega={st_full['omega2']:.4f}, "
              f"alpha={st_full['alpha2']:.4f}, gamma_gjr={st_full['gamma2_gjr']:.4f}, "
              f"beta={st_full['beta2']:.4f}")
        print(f"    Persistence (high): {st_full['persistence_high']:.4f}")
        print(f"  LogLik: {st_full['loglik']:.1f}, AIC: {st_full['aic']:.1f}, "
              f"BIC: {st_full['bic']:.1f}")

        # Convergence checks
        issues = []
        if st_full['persistence_low'] > 1.0:
            issues.append(f"Low-regime persistence > 1 ({st_full['persistence_low']:.3f})")
        if st_full['persistence_high'] > 1.0:
            issues.append(f"High-regime persistence > 1 ({st_full['persistence_high']:.3f})")
        if st_full['gamma_transition'] > 100:
            issues.append(f"Very large gamma_tr ({st_full['gamma_transition']:.1f}) = abrupt switch")
        if st_full['gamma_transition'] < 0.1:
            issues.append(f"Very small gamma_tr ({st_full['gamma_transition']:.4f}) = no transition")

        for iss in issues:
            print(f"  WARNING: {iss}")
        st_full['convergence_issues'] = issues

    else:
        print(f"  FAILED to converge in {st_full_time:.0f}s")

    # --- STGARCH Fixed Gamma (fallback / comparison) ---
    print("\n[3] ST-GARCH (fixed gamma=5, moderate transition)...")
    t0 = time.time()
    st_fixed = fit_stgarch_fixed_gamma(ret_arr, vix_lag_arr, fixed_gamma=5.0, timeout_sec=60)
    st_fixed_time = time.time() - t0

    if st_fixed:
        print(f"  Time: {st_fixed_time:.1f}s")
        print(f"  c={st_fixed['c']:.2f}")
        print(f"  Low-VIX: pers={st_fixed['persistence_low']:.4f}")
        print(f"  High-VIX: pers={st_fixed['persistence_high']:.4f}")
        print(f"  LogLik: {st_fixed['loglik']:.1f}, BIC: {st_fixed['bic']:.1f}")

    # --- Residual Diagnostics for STGARCH ---
    if st_full:
        p_best = [st_full[k] for k in [
            'mu', 'omega1', 'alpha1', 'gamma1_gjr', 'beta1',
            'omega2', 'alpha2', 'gamma2_gjr', 'beta2',
            'gamma_transition', 'c'
        ]]
        h_full, eps_full = stgarch_filter(p_best, ret_arr, vix_lag_arr)
        z = eps_full / np.sqrt(h_full)
        arch_z_s, arch_z_p = het_arch(z, nlags=10)[:2]
        print(f"\n  Residual diagnostics (STGARCH full):")
        print(f"    Std resid: mean={np.mean(z):.3f}, std={np.std(z):.3f}, "
              f"skew={stats.skew(z):.3f}, kurt={stats.kurtosis(z):.1f}")
        print(f"    ARCH-LM(10): stat={arch_z_s:.1f}, p={arch_z_p:.4f} "
              f"{'(remaining ARCH!)' if arch_z_p < 0.05 else '(clean)'}")
        st_full['residual_diagnostics'] = {
            'std_resid_mean': float(np.mean(z)),
            'std_resid_std': float(np.std(z)),
            'std_resid_skew': float(stats.skew(z)),
            'std_resid_kurtosis': float(stats.kurtosis(z)),
            'arch_lm_stat': float(arch_z_s),
            'arch_lm_p': float(arch_z_p),
        }

    # --- LRT: STGARCH vs GJR ---
    print("\n" + "-" * 50)
    print("LIKELIHOOD RATIO TESTS")
    print("-" * 50)

    lrt_results = {}
    if st_full:
        # GJR has 5 params (mu, omega, alpha, gamma, beta)
        # STGARCH has 11 params → df_diff = 6
        lr_stat, lr_p, lr_df = lrt_test(
            st_full['loglik'], gjr_res.loglikelihood, df_diff=6
        )
        lrt_results['stgarch_full_vs_gjr'] = {
            'lr_stat': lr_stat, 'p_value': lr_p, 'df': lr_df,
            'significant_0.05': lr_p < 0.05,
            'significant_0.01': lr_p < 0.01,
        }
        print(f"  STGARCH(full) vs GJR: LR={lr_stat:.2f}, df={lr_df}, "
              f"p={lr_p:.6f} {'***' if lr_p < 0.01 else '**' if lr_p < 0.05 else 'NS'}")
        print(f"    Note: LRT may have non-standard distribution under H0: gamma_tr=0 "
              f"(Davies 1987 problem)")

    if st_fixed:
        lr_stat2, lr_p2, lr_df2 = lrt_test(
            st_fixed['loglik'], gjr_res.loglikelihood, df_diff=5
        )
        lrt_results['stgarch_fixed_vs_gjr'] = {
            'lr_stat': lr_stat2, 'p_value': lr_p2, 'df': lr_df2,
            'significant_0.05': lr_p2 < 0.05,
        }
        print(f"  STGARCH(fixed gamma=5) vs GJR: LR={lr_stat2:.2f}, df={lr_df2}, "
              f"p={lr_p2:.6f}")

    # --- In-sample comparison table ---
    print("\n" + "-" * 50)
    print("IN-SAMPLE MODEL COMPARISON (sorted by BIC)")
    print("-" * 50)

    models_is = [
        ('GJR-GARCH(1,1)', 5, gjr_res.loglikelihood, gjr_res.aic, gjr_res.bic),
    ]
    if st_full:
        models_is.append(('STGARCH-VIX (full)', 11, st_full['loglik'],
                         st_full['aic'], st_full['bic']))
    if st_fixed:
        models_is.append(('STGARCH-VIX (gamma=5)', 10, st_fixed['loglik'],
                         st_fixed['aic'], st_fixed['bic']))

    print(f"  {'Model':<28} {'k':>3} {'LogLik':>10} {'AIC':>10} {'BIC':>10}")
    print("  " + "-" * 65)
    for name, k, ll, aic, bic in sorted(models_is, key=lambda x: x[4]):
        print(f"  {name:<28} {k:>3} {ll:>10.1f} {aic:>10.1f} {bic:>10.1f}")

    # ============================================================
    # ROLLING OOS FORECASTING (expanding window)
    # ============================================================
    print("\n" + "=" * 72)
    print("ROLLING OOS FORECASTING (2023-01 to 2024-12, expanding, refit=63d)")
    print("=" * 72)

    oos_start, oos_end = '2023-01-01', '2024-12-31'

    # GJR baseline
    print("\n[1/2] GJR-GARCH(1,1)...")
    t0 = time.time()
    f_gjr, r_gjr, d_gjr = rolling_gjr_oos(
        ret_series, dates_arr, oos_start, oos_end, use_expanding=True
    )
    gjr_oos_time = time.time() - t0
    print(f"  Time: {gjr_oos_time:.0f}s, n={len(f_gjr)}")

    # STGARCH
    print("\n[2/2] STGARCH-VIX (expanding)...")
    t0 = time.time()
    f_st, r_st, d_st = rolling_stgarch_oos(
        ret_arr, vix_lag_arr, dates_arr, oos_start, oos_end, use_expanding=True
    )
    st_oos_time = time.time() - t0
    print(f"  Time: {st_oos_time:.0f}s, n={len(f_st)}")

    # ============================================================
    # OOS EVALUATION (Patton 2011 framework)
    # ============================================================
    print("\n" + "=" * 72)
    print("OOS PERFORMANCE EVALUATION")
    print("=" * 72)

    # Align lengths
    n_common = min(len(f_gjr), len(f_st))
    f_gjr_c = f_gjr[:n_common]
    r_gjr_c = r_gjr[:n_common]
    f_st_c = f_st[:n_common]
    r_st_c = r_st[:n_common]

    # Use common realized values (should be the same)
    r_common = r_gjr_c  # r² is the same for both

    # --- QLIKE (Patton 2011 proxy-robust) ---
    qlike_gjr = qlike(r_common, f_gjr_c)
    qlike_st = qlike(r_common, f_st_c)
    qlike_diff_pct = (qlike_st - qlike_gjr) / abs(qlike_gjr) * 100

    print(f"\n  {'Model':<28} {'QLIKE':>10} {'MSE':>12} {'MAE':>10} {'N':>5}")
    print("  " + "-" * 69)

    # MSE/MAE
    mse_gjr = float(np.mean((f_gjr_c - r_common) ** 2))
    mse_st = float(np.mean((f_st_c - r_common) ** 2))
    mae_gjr = float(np.mean(np.abs(f_gjr_c - r_common)))
    mae_st = float(np.mean(np.abs(f_st_c - r_common)))

    print(f"  {'GJR-GARCH(1,1)':<28} {qlike_gjr:>10.6f} {mse_gjr:>12.6f} {mae_gjr:>10.6f} {n_common:>5}")
    print(f"  {'STGARCH-VIX':<28} {qlike_st:>10.6f} {mse_st:>12.6f} {mae_st:>10.6f} {n_common:>5}")
    print(f"\n  QLIKE difference: {qlike_diff_pct:+.4f}% "
          f"({'STGARCH better' if qlike_diff_pct < 0 else 'GJR better'})")

    oos_metrics = {
        'gjr': {
            'qlike': qlike_gjr, 'mse': mse_gjr, 'mae': mae_gjr,
            'n_obs': int(n_common),
            'mean_forecast': float(np.mean(f_gjr_c)),
            'mean_realized': float(np.mean(r_common)),
        },
        'stgarch': {
            'qlike': qlike_st, 'mse': mse_st, 'mae': mae_st,
            'n_obs': int(n_common),
            'mean_forecast': float(np.mean(f_st_c)),
            'mean_realized': float(np.mean(r_common)),
        },
        'qlike_diff_pct': float(qlike_diff_pct),
    }

    # --- Spearman Rank Correlation ---
    print("\n  Spearman Rank Correlation (distribution-free):")
    rho_gjr, p_gjr_sp = spearman_corr(r_common, f_gjr_c)
    rho_st, p_st_sp = spearman_corr(r_common, f_st_c)
    print(f"    GJR:     rho={rho_gjr:.4f}, p={p_gjr_sp:.2e}")
    print(f"    STGARCH: rho={rho_st:.4f}, p={p_st_sp:.2e}")

    oos_metrics['spearman'] = {
        'gjr': {'rho': rho_gjr, 'p_value': p_gjr_sp},
        'stgarch': {'rho': rho_st, 'p_value': p_st_sp},
    }

    # --- DM Test (Harvey t>3.0 threshold) ---
    print("\n  Diebold-Mariano Test (QLIKE loss, HAC std errors):")
    loss_gjr = qlike_pointwise(r_common, f_gjr_c)
    loss_st = qlike_pointwise(r_common, f_st_c)

    t_dm, p_dm = dm_test(loss_st, loss_gjr)
    harvey_sig = abs(t_dm) > 3.0

    print(f"    STGARCH vs GJR: t={t_dm:.4f}, p={p_dm:.6f}")
    print(f"    Harvey (2016) threshold |t|>3.0: {'PASS' if harvey_sig else 'FAIL'}")
    if t_dm < 0:
        print(f"    Direction: STGARCH has lower loss (better)")
    else:
        print(f"    Direction: GJR has lower loss (better)")

    dm_result = {
        'dm_stat': float(t_dm),
        'dm_pvalue': float(p_dm),
        'harvey_significant': harvey_sig,
        'direction': 'STGARCH better' if t_dm < 0 else 'GJR better',
        'conventional_sig': 'significant' if p_dm < 0.05 else 'not significant',
    }

    # ============================================================
    # TRANSITION FUNCTION ANALYSIS
    # ============================================================
    print("\n" + "=" * 72)
    print("TRANSITION FUNCTION ANALYSIS")
    print("=" * 72)

    trans_analysis = {}
    if st_full:
        gam = st_full['gamma_transition']
        c = st_full['c']

        # G(VIX) = 0.25 and 0.75 thresholds
        G25 = c - np.log(3) / gam if gam > 0.01 else None
        G75 = c + np.log(3) / gam if gam > 0.01 else None
        width = (G75 - G25) if G25 is not None else None

        speed_label = 'abrupt' if gam > 50 else 'smooth' if gam < 5 else 'moderate'

        print(f"\n  Transition speed: gamma={gam:.4f} ({speed_label})")
        print(f"  Threshold: c={c:.2f} (VIX level)")
        if width is not None:
            print(f"  G=0.25 at VIX={G25:.2f}, G=0.75 at VIX={G75:.2f}")
            print(f"  Transition width: {width:.2f} VIX points")

        # What fraction of time in each regime?
        args = gam * (vix_lag_arr - c)
        G_series = 1.0 / (1.0 + np.exp(-np.clip(args, -500, 500)))
        pct_low = float(np.mean(G_series < 0.25) * 100)
        pct_mid = float(np.mean((G_series >= 0.25) & (G_series <= 0.75)) * 100)
        pct_high = float(np.mean(G_series > 0.75) * 100)

        print(f"\n  Time in regimes:")
        print(f"    Low-VIX (G<0.25): {pct_low:.1f}%")
        print(f"    Transition (0.25<=G<=0.75): {pct_mid:.1f}%")
        print(f"    High-VIX (G>0.75): {pct_high:.1f}%")

        # Parameter differences between regimes
        print(f"\n  Parameter comparison:")
        print(f"    {'Param':<15} {'Low-VIX':>10} {'High-VIX':>10} {'Diff':>10}")
        print(f"    {'-'*48}")
        for param_name, low_key, high_key in [
            ('omega', 'omega1', 'omega2'),
            ('alpha', 'alpha1', 'alpha2'),
            ('gamma_gjr', 'gamma1_gjr', 'gamma2_gjr'),
            ('beta', 'beta1', 'beta2'),
        ]:
            low_v = st_full[low_key]
            high_v = st_full[high_key]
            print(f"    {param_name:<15} {low_v:>10.4f} {high_v:>10.4f} {high_v-low_v:>+10.4f}")

        trans_analysis = {
            'gamma_transition': gam,
            'c_threshold': c,
            'speed': speed_label,
            'G25_vix': G25,
            'G75_vix': G75,
            'transition_width': width,
            'pct_low_regime': pct_low,
            'pct_transition': pct_mid,
            'pct_high_regime': pct_high,
        }

    # ============================================================
    # CONCLUSION
    # ============================================================
    print("\n" + "=" * 72)
    print("CONCLUSION")
    print("=" * 72)

    # Determine conclusion
    if abs(t_dm) > 3.0 and t_dm < 0:
        conclusion = (f"STGARCH BEATS GJR at Harvey (2016) threshold. "
                     f"DM t={t_dm:.3f}, QLIKE diff={qlike_diff_pct:+.3f}%. "
                     f"Smooth transition captures regime-dependent volatility dynamics.")
        verdict = "STGARCH_WINS"
    elif p_dm < 0.05 and t_dm < 0:
        conclusion = (f"STGARCH better at 5% level but NOT at Harvey threshold. "
                     f"DM t={t_dm:.3f}, QLIKE diff={qlike_diff_pct:+.3f}%. "
                     f"Marginal improvement, may not survive multiple testing.")
        verdict = "MARGINAL_IMPROVEMENT"
    elif qlike_st < qlike_gjr:
        conclusion = (f"STGARCH numerically better but NOT statistically significant. "
                     f"DM t={t_dm:.3f}, QLIKE diff={qlike_diff_pct:+.3f}%. "
                     f"Added complexity not justified by OOS performance.")
        verdict = "NS_IMPROVEMENT"
    else:
        conclusion = (f"STGARCH does NOT beat GJR. "
                     f"DM t={t_dm:.3f}, QLIKE diff={qlike_diff_pct:+.3f}%. "
                     f"QLIKE ceiling confirmed — smooth transition adds parameters without OOS gain.")
        verdict = "GJR_WINS"

    print(f"\n  Verdict: {verdict}")
    print(f"  {conclusion}")

    t_total = time.time() - t_start
    print(f"\n  Total runtime: {t_total:.0f}s ({t_total/60:.1f} min)")

    # ============================================================
    # SAVE RESULTS
    # ============================================================
    results = {
        'experiment_id': 'K813',
        'title': 'Smooth Transition GARCH (STGARCH) with VIX Transition Variable',
        'proposer': '用戶',
        'executor': 'Claude',
        'asset': 'SPY',
        'data_source': 'yfinance (SPY, ^VIX)',
        'data_period': f"{dates_arr[0].strftime('%Y-%m-%d')} to {dates_arr[-1].strftime('%Y-%m-%d')}",
        'total_obs': len(data),
        'oos_period': f"{oos_start} to {oos_end}",
        'window': 'expanding (from 2005)',
        'refit_every': 63,
        'runtime_seconds': round(t_total, 1),
        'references': [
            'González-Rivera (1998) J. Business & Economic Statistics — STGARCH',
            'Hagerud (1997) PhD thesis — Logistic STGARCH',
            'Patton (2011) J. Econometrics 160 — proxy-robust loss',
            'Harvey et al. (2016) — multiple testing t>3.0',
        ],
        'descriptive': desc,
        'full_sample': {
            'gjr_garch': gjr_fs,
            'stgarch_full': st_full,
            'stgarch_fixed_gamma': st_fixed,
        },
        'in_sample_comparison': [
            {'model': m[0], 'k': m[1], 'loglik': float(m[2]),
             'aic': float(m[3]), 'bic': float(m[4])}
            for m in sorted(models_is, key=lambda x: x[4])
        ],
        'lrt_tests': lrt_results,
        'oos_metrics': oos_metrics,
        'dm_test': dm_result,
        'transition_analysis': trans_analysis,
        'conclusion': conclusion,
        'verdict': verdict,
        'comparison_with_k431': (
            'K431 used fixed rolling window (w=2000) and simpler STGARCH without GJR leverage. '
            'K813 uses expanding window, GJR leverage in both regimes, and proper lagged VIX '
            '(signal.shift(1)). K431 found STGARCH-lagvol diff=9.362% (GJR better).'
        ),
    }

    out_path = '/Users/yhlai0911/Desktop/volpred-research/experiments/k813_smooth_transition_garch_results.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n  Saved: {out_path}")
    print("=" * 72)
