"""
K494: Forex Volatility Forecasting — EUR/USD and USD/JPY
==========================================================
[提出: User, 執行: Claude]

Background:
  69 experiments across equity/bond/commodity/crypto/Taiwan, but ZERO forex.
  Forex has unique properties:
  - 24h trading → no overnight gap → range more meaningful
  - Central bank intervention → regime shifts
  - Carry trade dynamics → JPY may have different vol structure
  - Leverage effect may be absent or reversed (no equity-like mechanism)

Research Questions:
  1. Is GJR-GARCH still best in forex? (forex may lack leverage effect)
  2. Does HAR log-range work better in forex? (24h → complete range)
  3. Does GJR-X(VIX) improve forex vol forecasts? (equity vol → FX vol spillover?)
  4. Does K491 universal persistence law hold in forex?

Assets:
  - EURUSD=X (EUR/USD) — most liquid FX pair
  - JPY=X (USD/JPY) — carry trade currency
  - Fallback: FXE (EUR ETF), FXY (JPY ETF) if yfinance fails

Models:
  1. GARCH(1,1) — baseline symmetric
  2. GJR-GARCH(1,1) — asymmetric (leverage effect test)
  3. EGARCH(1,1) — asymmetric, allows negative gamma
  4. HAR log-range — Heterogeneous Autoregressive with log-range proxy
  5. GJR-X(VIX) — exogenous VIX effect on FX vol
  6. EWMA(λ=0.94) — RiskMetrics benchmark

Data: yfinance, 2015-01-01 to present
OOS: 2023-01-01 to 2025-12-31
Window: 2000 (rolling, refit every 21 days)
Evaluation: QLIKE, MSE, MAE, Diebold-Mariano test

References:
  - Andersen, Bollerslev, Diebold, Labys (2003) "Modeling and Forecasting Realized Volatility" Econometrica
  - Corsi (2009) "A Simple Approximate Long-Memory Model of Realized Volatility" JFEC
  - Alizadeh, Brandt, Diebold (2002) "Range-Based Estimation of Stochastic Volatility Models" JF
  - Baillie & Bollerslev (1989) "The Message in Daily Exchange Rates" JBES
  - Engle & Rangel (2008) "The Spline-GARCH Model for Low-Frequency Volatility" RFS
  - K491: Universal persistence law — UUP persistence=0.99
  - K483: Cross-asset leverage direction analysis
"""

import json
import warnings
import time
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from scipy import stats
from scipy.optimize import minimize
from arch import arch_model
import statsmodels.api as sm
from statsmodels.tsa.stattools import adfuller
from statsmodels.stats.diagnostic import het_arch, acorr_ljungbox

warnings.filterwarnings('ignore')
np.random.seed(42)

t_start = time.time()

# =============================================================================
# 0. CONFIGURATION
# =============================================================================
OOS_START = '2023-01-01'
DATA_START = '2015-01-01'
DATA_END = '2026-03-26'
WINDOW = 2000
REFIT_EVERY = 21
EWMA_LAMBDA = 0.94

print("=" * 80)
print("K494: Forex Volatility Forecasting — EUR/USD and USD/JPY")
print("=" * 80)
print(f"Data: {DATA_START} to {DATA_END}")
print(f"OOS: {OOS_START}+")
print(f"Window: {WINDOW}, Refit: every {REFIT_EVERY} days")

# =============================================================================
# 1. DATA COLLECTION
# =============================================================================
print("\n" + "=" * 80)
print("1. Data Collection & Diagnostics")
print("=" * 80)

# Try direct FX pairs first, then ETFs
FX_ASSETS = {
    'EURUSD=X': {'label': 'EUR/USD', 'fallback': 'FXE'},
    'JPY=X': {'label': 'USD/JPY', 'fallback': 'FXY'},
}

# Download VIX for GJR-X model
print("\nDownloading VIX...")
vix_df = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_df.columns, pd.MultiIndex):
    vix_df.columns = vix_df.columns.get_level_values(0)
vix_close = vix_df['Close'].dropna()
print(f"  VIX: {len(vix_close)} obs, range [{vix_close.min():.1f}, {vix_close.max():.1f}]")

# Download FX data
all_data = {}
asset_diagnostics = {}

for ticker, info in FX_ASSETS.items():
    label = info['label']
    fallback = info['fallback']

    print(f"\nDownloading {label} ({ticker})...")
    df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Check if sufficient data; if not, try fallback
    if len(df) < 1000:
        print(f"  {ticker}: only {len(df)} obs, trying fallback {fallback}...")
        df = yf.download(fallback, start=DATA_START, end=DATA_END, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        ticker = fallback
        label += f" (via {fallback})"

    if len(df) < 1000:
        print(f"  SKIP {label}: insufficient data ({len(df)} obs)")
        continue

    # Log returns (×100 for GARCH numerical stability)
    ret = 100 * np.log(df['Close'] / df['Close'].shift(1)).dropna()
    ret = ret.replace([np.inf, -np.inf], np.nan).dropna()

    # Log range (Parkinson proxy for realized vol)
    log_range = np.log(df['High'] / df['Low']).dropna()
    log_range = log_range.replace([np.inf, -np.inf], np.nan).dropna()

    # Realized variance proxy = r²
    rv_proxy = ret ** 2

    all_data[ticker] = {
        'label': label,
        'returns': ret,
        'log_range': log_range,
        'rv_proxy': rv_proxy,
        'close': df['Close'],
        'high': df['High'],
        'low': df['Low'],
    }

    # --- Diagnostics ---
    diag = {}
    diag['label'] = label
    diag['n_obs'] = len(ret)
    diag['start'] = str(ret.index[0].date())
    diag['end'] = str(ret.index[-1].date())
    diag['mean'] = float(ret.mean())
    diag['std'] = float(ret.std())
    diag['skew'] = float(ret.skew())
    diag['kurtosis'] = float(ret.kurtosis())
    diag['min'] = float(ret.min())
    diag['max'] = float(ret.max())
    diag['mean_abs_ret'] = float(ret.abs().mean())

    # ADF test
    adf_stat, adf_pval, *_ = adfuller(ret.values, maxlag=20, autolag='AIC')
    diag['adf_stat'] = float(adf_stat)
    diag['adf_pval'] = float(adf_pval)

    # ARCH-LM test
    try:
        arch_lm_stat, arch_lm_pval, _, _ = het_arch(ret.values, nlags=5)
        diag['arch_lm_stat'] = float(arch_lm_stat)
        diag['arch_lm_pval'] = float(arch_lm_pval)
    except Exception:
        diag['arch_lm_stat'] = None
        diag['arch_lm_pval'] = None

    # Ljung-Box test (returns²)
    try:
        lb_result = acorr_ljungbox(ret.values ** 2, lags=[10], return_df=True)
        diag['ljungbox_stat'] = float(lb_result['lb_stat'].values[0])
        diag['ljungbox_pval'] = float(lb_result['lb_pvalue'].values[0])
    except Exception:
        diag['ljungbox_stat'] = None
        diag['ljungbox_pval'] = None

    # Log-range stats
    diag['log_range_mean'] = float(log_range.mean())
    diag['log_range_std'] = float(log_range.std())

    asset_diagnostics[ticker] = diag

    print(f"  {label}: {diag['n_obs']} obs, "
          f"mean={diag['mean']:.4f}, std={diag['std']:.4f}, "
          f"skew={diag['skew']:.2f}, kurt={diag['kurtosis']:.1f}")
    print(f"    ADF: {diag['adf_stat']:.2f} (p={diag['adf_pval']:.4f}), "
          f"ARCH-LM: {diag.get('arch_lm_stat', 'N/A'):.1f} (p={diag.get('arch_lm_pval', 'N/A'):.4f}), "
          f"LB(10): {diag.get('ljungbox_stat', 'N/A'):.1f} (p={diag.get('ljungbox_pval', 'N/A'):.4f})")
    print(f"    Log-range: mean={diag['log_range_mean']:.4f}, std={diag['log_range_std']:.4f}")

print(f"\nSuccessfully loaded: {len(all_data)} assets")

# =============================================================================
# 2. FULL-SAMPLE GJR-GARCH ESTIMATION (for diagnostics & persistence analysis)
# =============================================================================
print("\n" + "=" * 80)
print("2. Full-Sample GJR-GARCH(1,1) — Parameter Estimates")
print("=" * 80)

full_sample_params = {}

for ticker in all_data:
    ret = all_data[ticker]['returns']
    label = all_data[ticker]['label']

    am = arch_model(ret, vol='Garch', p=1, o=1, q=1, dist='t', mean='Constant')
    res = am.fit(disp='off', options={'maxiter': 500})

    params = res.params
    omega = float(params.get('omega', np.nan))
    alpha = float(params.get('alpha[1]', np.nan))
    gamma = float(params.get('gamma[1]', np.nan))
    beta = float(params.get('beta[1]', np.nan))
    nu = float(params.get('nu', np.nan))

    persistence = alpha + gamma / 2.0 + beta
    half_life = np.log(2) / (-np.log(persistence)) if persistence < 1 else np.inf

    # Gamma significance
    se = res.std_err
    gamma_se = float(se.get('gamma[1]', np.nan))
    gamma_t = gamma / gamma_se if gamma_se > 0 else 0.0
    gamma_sig = abs(gamma_t) > 1.96

    # Unconditional variance
    if persistence < 1.0:
        unc_var = omega / (1 - persistence)
        unc_vol_ann = np.sqrt(unc_var * 252)
    else:
        unc_var = np.nan
        unc_vol_ann = np.nan

    full_sample_params[ticker] = {
        'label': label,
        'omega': omega,
        'alpha': alpha,
        'gamma': gamma,
        'gamma_se': gamma_se,
        'gamma_t': float(gamma_t),
        'gamma_significant': gamma_sig,
        'beta': beta,
        'nu': nu,
        'persistence': persistence,
        'half_life': float(half_life) if np.isfinite(half_life) else None,
        'unc_vol_ann': float(unc_vol_ann) if np.isfinite(unc_vol_ann) else None,
        'aic': float(res.aic),
        'bic': float(res.bic),
        'converged': bool(res.convergence_flag == 0),
    }

    print(f"\n  {label} ({ticker}):")
    print(f"    omega={omega:.6f}, alpha={alpha:.4f}, gamma={gamma:.4f}, beta={beta:.4f}")
    print(f"    persistence={persistence:.4f}, half_life={half_life:.1f}d")
    print(f"    gamma t-stat={gamma_t:.2f} ({'SIG' if gamma_sig else 'NOT sig'})")
    print(f"    nu (df)={nu:.2f}, unc_vol_ann={unc_vol_ann:.2f}%")
    print(f"    AIC={res.aic:.1f}, BIC={res.bic:.1f}, converged={res.convergence_flag == 0}")

# =============================================================================
# 3. HELPER FUNCTIONS FOR OOS EVALUATION
# =============================================================================

def qlike(actual_rv, forecast_var):
    """QLIKE loss: E[rv/h + log(h)]"""
    mask = (actual_rv > 0) & (forecast_var > 0) & np.isfinite(actual_rv) & np.isfinite(forecast_var)
    rv = actual_rv[mask]
    h = forecast_var[mask]
    return float(np.mean(rv / h + np.log(h)))

def mse_loss(actual_rv, forecast_var):
    mask = np.isfinite(actual_rv) & np.isfinite(forecast_var)
    return float(np.mean((actual_rv[mask] - forecast_var[mask]) ** 2))

def mae_loss(actual_rv, forecast_var):
    mask = np.isfinite(actual_rv) & np.isfinite(forecast_var)
    return float(np.mean(np.abs(actual_rv[mask] - forecast_var[mask])))

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive accuracy."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0
    d_bar = np.mean(d)
    # HAC variance (Newey-West, 1 lag for h=1)
    gamma0 = np.var(d, ddof=1)
    gamma1 = np.cov(d[:-1], d[1:])[0, 1] if n > 2 else 0.0
    var_d = (gamma0 + 2 * gamma1) / n
    if var_d <= 0:
        return 0.0, 1.0
    dm_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - stats.t.cdf(abs(dm_stat), df=n - 1))
    return float(dm_stat), float(p_val)


def fit_garch_and_forecast(ret_in, model_type='gjr', dist='t'):
    """Fit GARCH model and return 1-step ahead forecast variance."""
    try:
        if model_type == 'garch':
            am = arch_model(ret_in, vol='Garch', p=1, o=0, q=1, dist=dist, mean='Constant')
        elif model_type == 'gjr':
            am = arch_model(ret_in, vol='Garch', p=1, o=1, q=1, dist=dist, mean='Constant')
        elif model_type == 'egarch':
            am = arch_model(ret_in, vol='EGARCH', p=1, o=1, q=1, dist=dist, mean='Constant')
        else:
            raise ValueError(f"Unknown model_type: {model_type}")

        res = am.fit(disp='off', options={'maxiter': 300}, show_warning=False)
        forecasts = res.forecast(horizon=1)
        h_next = forecasts.variance.values[-1, 0]

        # Extract parameters
        params = res.params
        pdict = {}
        if model_type in ('garch', 'gjr'):
            pdict['omega'] = float(params.get('omega', np.nan))
            pdict['alpha'] = float(params.get('alpha[1]', np.nan))
            pdict['beta'] = float(params.get('beta[1]', np.nan))
            if model_type == 'gjr':
                pdict['gamma'] = float(params.get('gamma[1]', np.nan))
                pdict['persistence'] = pdict['alpha'] + pdict['gamma'] / 2 + pdict['beta']
            else:
                pdict['persistence'] = pdict['alpha'] + pdict['beta']
        elif model_type == 'egarch':
            pdict['omega'] = float(params.get('omega', np.nan))
            pdict['alpha'] = float(params.get('alpha[1]', np.nan))
            pdict['gamma'] = float(params.get('gamma[1]', np.nan))
            pdict['beta'] = float(params.get('beta[1]', np.nan))
            pdict['persistence'] = abs(float(params.get('beta[1]', np.nan)))

        return h_next, pdict, True
    except Exception:
        return np.nan, {}, False


def fit_gjrx_vix_and_forecast(ret_in, vix_in):
    """GJR-GARCH-X with VIX² as exogenous variable.

    We use a manual implementation since arch package's exogenous support is limited.
    h_t = omega + alpha * r²_{t-1} + gamma * I_{t-1} * r²_{t-1} + beta * h_{t-1} + delta * VIX²_{t-1}
    """
    T = len(ret_in)
    r = ret_in.values if hasattr(ret_in, 'values') else np.array(ret_in)
    v = vix_in.values if hasattr(vix_in, 'values') else np.array(vix_in)
    # Scale VIX² to match returns² scale: (VIX/100)² * 100² / 252 ≈ daily variance scale
    vix_sq = (v / 100) ** 2 * 10000 / 252  # daily variance scale matching ret*100

    def negll(params):
        omega, alpha, gamma_p, beta, delta = params
        if omega < 1e-8 or alpha < 0 or gamma_p < 0 or beta < 0 or delta < 0:
            return 1e10
        if alpha + gamma_p / 2 + beta >= 1.0:
            return 1e10

        h = np.zeros(T)
        h[0] = np.var(r)
        for t in range(1, T):
            lev = float(r[t-1] < 0) * r[t-1] ** 2
            h[t] = omega + alpha * r[t-1]**2 + gamma_p * lev + beta * h[t-1] + delta * vix_sq[t-1]
            h[t] = max(h[t], 1e-8)

        ll = -0.5 * np.sum(np.log(h) + r**2 / h)
        return -ll if np.isfinite(ll) else 1e10

    # Initial parameters
    x0 = [0.01, 0.03, 0.02, 0.90, 0.01]
    bounds = [(1e-8, 1.0), (0, 0.5), (0, 0.5), (0, 0.999), (0, 1.0)]

    try:
        result = minimize(negll, x0, method='L-BFGS-B', bounds=bounds,
                         options={'maxiter': 500})
        omega, alpha, gamma_p, beta, delta = result.x

        # Compute final h series for forecast
        h = np.zeros(T)
        h[0] = np.var(r)
        for t in range(1, T):
            lev = float(r[t-1] < 0) * r[t-1] ** 2
            h[t] = omega + alpha * r[t-1]**2 + gamma_p * lev + beta * h[t-1] + delta * vix_sq[t-1]
            h[t] = max(h[t], 1e-8)

        # 1-step forecast
        lev_last = float(r[-1] < 0) * r[-1] ** 2
        h_next = omega + alpha * r[-1]**2 + gamma_p * lev_last + beta * h[-1] + delta * vix_sq[-1]
        h_next = max(h_next, 1e-8)

        pdict = {
            'omega': float(omega), 'alpha': float(alpha), 'gamma': float(gamma_p),
            'beta': float(beta), 'delta': float(delta),
            'persistence': float(alpha + gamma_p / 2 + beta),
        }
        return h_next, pdict, True
    except Exception:
        return np.nan, {}, False


def har_log_range_forecast(log_range_in):
    """HAR model on log-range: lr_t = c + b1*lr_{t-1} + b5*lr_{t-5:t} + b22*lr_{t-22:t}
    Returns 1-step ahead forecast of log-range, converted to variance proxy.
    """
    lr = log_range_in.values if hasattr(log_range_in, 'values') else np.array(log_range_in)
    T = len(lr)

    if T < 30:
        return np.nan, {}, False

    # Build HAR features
    y = lr[22:]  # target
    lr_d = lr[21:-1]  # daily (lag 1)
    lr_w = np.array([np.mean(lr[i-4:i+1]) for i in range(21, T-1)])  # weekly avg (lag 1-5)
    lr_m = np.array([np.mean(lr[i-21:i+1]) for i in range(21, T-1)])  # monthly avg (lag 1-22)

    X = np.column_stack([np.ones(len(y)), lr_d, lr_w, lr_m])

    try:
        model = sm.OLS(y, X).fit()
        coefs = model.params

        # 1-step forecast using last observation
        lr_d_next = lr[-1]
        lr_w_next = np.mean(lr[-5:])
        lr_m_next = np.mean(lr[-22:])

        lr_forecast = coefs[0] + coefs[1] * lr_d_next + coefs[2] * lr_w_next + coefs[3] * lr_m_next

        # Convert log-range to variance proxy:
        # Parkinson (1980): σ² = (1/(4*ln2)) * (log(H/L))² ≈ 0.3607 * range²
        # But we're in log-range space, so forecast is E[log(H/L)]
        # σ²_daily ≈ (lr_forecast)² / (4*ln2) in natural units → ×10000 for ×100 returns
        var_forecast = (lr_forecast ** 2) / (4 * np.log(2)) * 10000

        pdict = {
            'const': float(coefs[0]),
            'beta_d': float(coefs[1]),
            'beta_w': float(coefs[2]),
            'beta_m': float(coefs[3]),
            'r_squared': float(model.rsquared),
        }
        return var_forecast, pdict, True
    except Exception:
        return np.nan, {}, False


def ewma_forecast(ret_in, lam=0.94):
    """EWMA (RiskMetrics) forecast: h_t = λ*h_{t-1} + (1-λ)*r²_{t-1}"""
    r = ret_in.values if hasattr(ret_in, 'values') else np.array(ret_in)
    T = len(r)
    h = np.zeros(T)
    h[0] = np.var(r[:min(60, T)])
    for t in range(1, T):
        h[t] = lam * h[t-1] + (1 - lam) * r[t-1] ** 2
    # 1-step forecast
    h_next = lam * h[-1] + (1 - lam) * r[-1] ** 2
    return max(h_next, 1e-8), {'lambda': lam}, True


# =============================================================================
# 4. OUT-OF-SAMPLE EVALUATION
# =============================================================================
print("\n" + "=" * 80)
print("3. Out-of-Sample Rolling Forecasts (OOS from 2023)")
print("=" * 80)

MODEL_NAMES = ['GARCH', 'GJR', 'EGARCH', 'HAR_LogRange', 'GJR_X_VIX', 'EWMA']
results = {}

for ticker in all_data:
    label = all_data[ticker]['label']
    ret = all_data[ticker]['returns']
    lr = all_data[ticker]['log_range']
    rv = all_data[ticker]['rv_proxy']

    # Align with VIX
    common_idx = ret.index.intersection(vix_close.index)
    ret_aligned = ret.loc[common_idx]
    lr_aligned = lr.reindex(common_idx).dropna()
    vix_aligned = vix_close.loc[common_idx]
    rv_aligned = rv.loc[common_idx]

    # OOS indices
    oos_mask = ret_aligned.index >= OOS_START
    oos_indices = ret_aligned.index[oos_mask]
    n_oos = len(oos_indices)

    print(f"\n  {label} ({ticker}): {len(ret_aligned)} total obs, {n_oos} OOS days")

    if n_oos < 50:
        print(f"    SKIP: too few OOS observations")
        continue

    # Storage for forecasts
    forecasts = {m: np.full(n_oos, np.nan) for m in MODEL_NAMES}
    actual_rv_oos = np.full(n_oos, np.nan)
    rolling_params = {m: [] for m in MODEL_NAMES}

    # Pre-compute positions
    all_idx = ret_aligned.index.tolist()
    oos_start_pos = all_idx.index(oos_indices[0])

    last_fit = {m: -999 for m in MODEL_NAMES}
    cached_models = {m: (np.nan, {}, False) for m in MODEL_NAMES}

    for i, oos_date in enumerate(oos_indices):
        pos = oos_start_pos + i

        # In-sample window
        start_pos = max(0, pos - WINDOW)
        ret_in = ret_aligned.iloc[start_pos:pos]
        vix_in = vix_aligned.iloc[start_pos:pos]

        # Actual RV = r²_{t}
        actual_rv_oos[i] = float(rv_aligned.iloc[pos]) if pos < len(rv_aligned) else np.nan

        need_refit = (i % REFIT_EVERY == 0) or (i == 0)

        if need_refit and len(ret_in) >= 252:
            # 1. GARCH(1,1)
            h, p, ok = fit_garch_and_forecast(ret_in, 'garch', 't')
            if ok:
                cached_models['GARCH'] = (h, p, ok)
                rolling_params['GARCH'].append(p)

            # 2. GJR-GARCH(1,1)
            h, p, ok = fit_garch_and_forecast(ret_in, 'gjr', 't')
            if ok:
                cached_models['GJR'] = (h, p, ok)
                rolling_params['GJR'].append(p)

            # 3. EGARCH(1,1)
            h, p, ok = fit_garch_and_forecast(ret_in, 'egarch', 't')
            if ok:
                cached_models['EGARCH'] = (h, p, ok)
                rolling_params['EGARCH'].append(p)

            # 4. HAR log-range
            lr_common = lr_aligned.reindex(ret_aligned.index[start_pos:pos]).dropna()
            if len(lr_common) >= 30:
                h, p, ok = har_log_range_forecast(lr_common)
                if ok:
                    cached_models['HAR_LogRange'] = (h, p, ok)
                    rolling_params['HAR_LogRange'].append(p)

            # 5. GJR-X(VIX)
            if len(vix_in) == len(ret_in) and len(ret_in) >= 252:
                h, p, ok = fit_gjrx_vix_and_forecast(ret_in, vix_in)
                if ok:
                    cached_models['GJR_X_VIX'] = (h, p, ok)
                    rolling_params['GJR_X_VIX'].append(p)

        # 6. EWMA — always update (no refit needed, recursive)
        if len(ret_in) >= 60:
            h, p, ok = ewma_forecast(ret_in, EWMA_LAMBDA)
            cached_models['EWMA'] = (h, p, ok)

        # Record forecasts
        for m in MODEL_NAMES:
            h_val, _, ok = cached_models[m]
            if ok and np.isfinite(h_val) and h_val > 0:
                forecasts[m][i] = h_val

        if (i + 1) % 100 == 0:
            print(f"    ... {i+1}/{n_oos} days processed")

    print(f"    Done: {n_oos} OOS forecasts")

    # --- Compute losses ---
    asset_results = {}
    rv_oos = actual_rv_oos

    for m in MODEL_NAMES:
        h = forecasts[m]
        valid = np.isfinite(rv_oos) & np.isfinite(h) & (rv_oos > 0) & (h > 0)
        n_valid = int(np.sum(valid))

        if n_valid < 30:
            asset_results[m] = {
                'qlike': None, 'mse': None, 'mae': None,
                'n_valid': n_valid, 'status': 'insufficient_data'
            }
            continue

        q = qlike(rv_oos[valid], h[valid])
        m_val = mse_loss(rv_oos[valid], h[valid])
        ma = mae_loss(rv_oos[valid], h[valid])

        asset_results[m] = {
            'qlike': q,
            'mse': m_val,
            'mae': ma,
            'n_valid': n_valid,
            'mean_forecast_var': float(np.mean(h[valid])),
            'mean_actual_rv': float(np.mean(rv_oos[valid])),
        }

        # Add rolling parameter summaries
        if rolling_params[m]:
            param_df = pd.DataFrame(rolling_params[m])
            param_summary = {}
            for col in param_df.columns:
                vals = param_df[col].dropna()
                if len(vals) > 0:
                    param_summary[col] = {
                        'mean': float(vals.mean()),
                        'std': float(vals.std()) if len(vals) > 1 else 0.0,
                        'min': float(vals.min()),
                        'max': float(vals.max()),
                    }
            asset_results[m]['param_summary'] = param_summary

    # --- DM tests vs best model ---
    # Find best QLIKE
    valid_models = {m: r for m, r in asset_results.items() if r.get('qlike') is not None}
    if valid_models:
        best_model = min(valid_models, key=lambda m: valid_models[m]['qlike'])
        best_qlike = valid_models[best_model]['qlike']

        print(f"\n    === QLIKE Results for {label} ===")
        print(f"    {'Model':<15} {'QLIKE':>10} {'MSE':>12} {'MAE':>10} {'vs Best':>10}")
        print(f"    {'-'*60}")

        for m in MODEL_NAMES:
            r = asset_results.get(m, {})
            if r.get('qlike') is not None:
                delta = r['qlike'] - best_qlike
                marker = ' ***' if m == best_model else ''
                print(f"    {m:<15} {r['qlike']:>10.4f} {r['mse']:>12.4f} {r['mae']:>10.4f} {delta:>+10.4f}{marker}")
            else:
                print(f"    {m:<15} {'N/A':>10}")

        # DM tests: each model vs best
        dm_results = {}
        for m in valid_models:
            if m == best_model:
                dm_results[m] = {'dm_stat': 0.0, 'dm_pval': 1.0, 'vs': best_model}
                continue

            h_best = forecasts[best_model]
            h_m = forecasts[m]
            valid = (np.isfinite(rv_oos) & np.isfinite(h_best) & np.isfinite(h_m) &
                    (rv_oos > 0) & (h_best > 0) & (h_m > 0))

            loss_best = rv_oos[valid] / h_best[valid] + np.log(h_best[valid])
            loss_m = rv_oos[valid] / h_m[valid] + np.log(h_m[valid])

            dm_stat, dm_pval = dm_test(loss_m, loss_best)
            dm_results[m] = {'dm_stat': dm_stat, 'dm_pval': dm_pval, 'vs': best_model}

            sig = '**' if dm_pval < 0.05 else ('*' if dm_pval < 0.10 else '')
            print(f"    DM({m} vs {best_model}): stat={dm_stat:.3f}, p={dm_pval:.4f} {sig}")

        asset_results['_best_model'] = best_model
        asset_results['_best_qlike'] = best_qlike
        asset_results['_dm_tests'] = dm_results

    results[ticker] = asset_results

# =============================================================================
# 5. KEY FINDINGS
# =============================================================================
print("\n" + "=" * 80)
print("4. Key Findings — Forex Volatility Characteristics")
print("=" * 80)

findings = {}

for ticker in results:
    label = all_data[ticker]['label']
    r = results[ticker]
    fsp = full_sample_params[ticker]

    print(f"\n  === {label} ({ticker}) ===")

    # Q1: Leverage effect
    gamma = fsp['gamma']
    gamma_t = fsp['gamma_t']
    gamma_sig = fsp['gamma_significant']
    print(f"  Q1 Leverage effect: gamma={gamma:.4f}, t={gamma_t:.2f}, significant={gamma_sig}")

    if not gamma_sig:
        print(f"      → NO significant leverage effect (as expected for forex)")
    elif gamma > 0:
        print(f"      → POSITIVE gamma: depreciation (negative return) increases vol")
    else:
        print(f"      → NEGATIVE gamma: appreciation increases vol (unusual)")

    # Q2: Best model
    best = r.get('_best_model', 'N/A')
    best_q = r.get('_best_qlike', None)
    print(f"  Q2 Best model: {best} (QLIKE={best_q:.4f})" if best_q else f"  Q2 Best model: {best}")

    # Q3: GJR vs GARCH (is asymmetry needed?)
    gjr_q = r.get('GJR', {}).get('qlike')
    garch_q = r.get('GARCH', {}).get('qlike')
    if gjr_q and garch_q:
        delta = gjr_q - garch_q
        print(f"  Q3 GJR vs GARCH: ΔQLIKE={delta:+.4f} ({'GJR better' if delta < 0 else 'GARCH better or equal'})")

    # Q4: HAR log-range performance
    har_q = r.get('HAR_LogRange', {}).get('qlike')
    if har_q and best_q:
        delta = har_q - best_q
        print(f"  Q4 HAR log-range: QLIKE={har_q:.4f} (Δ={delta:+.4f} vs best)")

    # Q5: GJR-X(VIX) spillover
    gjrx_q = r.get('GJR_X_VIX', {}).get('qlike')
    if gjrx_q and gjr_q:
        delta = gjrx_q - gjr_q
        print(f"  Q5 GJR-X(VIX): QLIKE={gjrx_q:.4f} (Δ={delta:+.4f} vs GJR, "
              f"{'VIX helps' if delta < 0 else 'VIX not helpful'})")

    # Q6: Persistence
    pers = fsp['persistence']
    hl = fsp['half_life']
    print(f"  Q6 Persistence: {pers:.4f}, half-life={hl:.1f}d" if hl else
          f"  Q6 Persistence: {pers:.4f}, half-life=∞")

    # GJR-X delta (VIX effect magnitude)
    gjrx_params = r.get('GJR_X_VIX', {}).get('param_summary', {})
    if 'delta' in gjrx_params:
        delta_mean = gjrx_params['delta']['mean']
        print(f"  VIX delta (mean): {delta_mean:.6f}")

    findings[ticker] = {
        'leverage_effect': {
            'gamma': gamma,
            'gamma_t': gamma_t,
            'significant': gamma_sig,
            'interpretation': 'absent' if not gamma_sig else ('positive' if gamma > 0 else 'negative'),
        },
        'best_model': best,
        'best_qlike': best_q,
        'persistence': pers,
        'half_life': hl,
        'gjr_vs_garch_delta': float(gjr_q - garch_q) if gjr_q and garch_q else None,
    }

# =============================================================================
# 6. CROSS-ASSET COMPARISON (Forex vs Equity/Commodity)
# =============================================================================
print("\n" + "=" * 80)
print("5. Cross-Asset Comparison: Forex vs Known Results")
print("=" * 80)

# Reference: K491 findings
reference = {
    'SPY': {'persistence': 0.970, 'gamma': 0.18, 'gamma_sig': True, 'best_model': 'GJR'},
    'GLD': {'persistence': 0.940, 'gamma': -0.03, 'gamma_sig': False, 'best_model': 'GARCH'},
    'BTC-USD': {'persistence': 0.930, 'gamma': 0.06, 'gamma_sig': False, 'best_model': 'GARCH'},
    'TLT': {'persistence': 0.850, 'gamma': 0.02, 'gamma_sig': False, 'best_model': 'GARCH'},
    'UUP': {'persistence': 0.990, 'gamma': -0.01, 'gamma_sig': False, 'best_model': 'GARCH'},
}

print(f"\n  {'Asset':<12} {'Persistence':>12} {'Gamma':>8} {'Gamma Sig':>10} {'Best Model':>12}")
print(f"  {'-'*58}")

# Print reference
for ref_ticker, ref_data in reference.items():
    print(f"  {ref_ticker:<12} {ref_data['persistence']:>12.4f} {ref_data['gamma']:>8.4f} "
          f"{'Yes' if ref_data['gamma_sig'] else 'No':>10} {ref_data['best_model']:>12}")

# Print forex results
for ticker in full_sample_params:
    fsp = full_sample_params[ticker]
    best = results.get(ticker, {}).get('_best_model', 'N/A')
    print(f"  {ticker:<12} {fsp['persistence']:>12.4f} {fsp['gamma']:>8.4f} "
          f"{'Yes' if fsp['gamma_significant'] else 'No':>10} {best:>12}  ← FOREX")

# =============================================================================
# 7. SAVE RESULTS
# =============================================================================
elapsed = time.time() - t_start

output = {
    'experiment_id': 'K494',
    'title': 'Forex Volatility Forecasting — EUR/USD and USD/JPY',
    'proposed_by': 'User',
    'executed_by': 'Claude',
    'timestamp': datetime.now(timezone.utc).isoformat(),
    'config': {
        'data_start': DATA_START,
        'data_end': DATA_END,
        'oos_start': OOS_START,
        'window': WINDOW,
        'refit_every': REFIT_EVERY,
        'ewma_lambda': EWMA_LAMBDA,
        'models': MODEL_NAMES,
        'assets': {t: all_data[t]['label'] for t in all_data},
    },
    'diagnostics': asset_diagnostics,
    'full_sample_params': full_sample_params,
    'oos_results': {},
    'findings': findings,
    'references': [
        'Andersen, Bollerslev, Diebold, Labys (2003) Econometrica — realized volatility',
        'Corsi (2009) JFEC — HAR model',
        'Alizadeh, Brandt, Diebold (2002) JF — range-based vol estimation',
        'Baillie & Bollerslev (1989) JBES — FX volatility modeling',
        'Engle & Rangel (2008) RFS — Spline-GARCH',
        'K491: Universal persistence law',
        'K483: Cross-asset leverage direction',
    ],
    'elapsed_seconds': round(elapsed, 1),
}

# Clean OOS results for JSON serialization
for ticker in results:
    oos_clean = {}
    for m in MODEL_NAMES:
        r = results[ticker].get(m, {})
        if r:
            oos_clean[m] = {k: v for k, v in r.items() if k != 'param_summary' or v}
    oos_clean['_best_model'] = results[ticker].get('_best_model')
    oos_clean['_best_qlike'] = results[ticker].get('_best_qlike')
    if '_dm_tests' in results[ticker]:
        oos_clean['_dm_tests'] = results[ticker]['_dm_tests']
    output['oos_results'][ticker] = oos_clean

# Summary
summary_lines = []
for ticker in results:
    label = all_data[ticker]['label']
    best = results[ticker].get('_best_model', 'N/A')
    best_q = results[ticker].get('_best_qlike')
    fsp = full_sample_params[ticker]
    q_str = f"QLIKE={best_q:.4f}" if best_q else ""
    gamma_str = f"gamma={'SIG' if fsp['gamma_significant'] else 'NS'}({fsp['gamma']:.4f})"
    summary_lines.append(
        f"{label}: best={best} {q_str}, persistence={fsp['persistence']:.4f}, {gamma_str}"
    )

output['summary'] = '; '.join(summary_lines)

# Conclusions
conclusions = []
for ticker in full_sample_params:
    fsp = full_sample_params[ticker]
    if not fsp['gamma_significant']:
        conclusions.append(f"{fsp['label']}: No leverage effect (gamma NS) — symmetric GARCH may suffice")
    else:
        conclusions.append(f"{fsp['label']}: Significant leverage effect (gamma={fsp['gamma']:.4f})")

for ticker in results:
    best = results[ticker].get('_best_model', 'N/A')
    gjr_q = results[ticker].get('GJR', {}).get('qlike')
    garch_q = results[ticker].get('GARCH', {}).get('qlike')
    if gjr_q and garch_q:
        if gjr_q < garch_q:
            conclusions.append(f"{all_data[ticker]['label']}: GJR outperforms GARCH even in forex")
        else:
            conclusions.append(f"{all_data[ticker]['label']}: GARCH >= GJR (asymmetry not needed OOS)")

    har_q = results[ticker].get('HAR_LogRange', {}).get('qlike')
    if har_q and gjr_q:
        if har_q < gjr_q:
            conclusions.append(f"{all_data[ticker]['label']}: HAR log-range beats GJR in forex")
        else:
            conclusions.append(f"{all_data[ticker]['label']}: HAR log-range underperforms GARCH-family")

conclusions.append(f"K491 persistence law check: forex persistence = "
                   f"{', '.join([f'{full_sample_params[t]['label']}={full_sample_params[t]['persistence']:.4f}' for t in full_sample_params])}")

output['conclusions'] = conclusions

# Save
import os
script_dir = os.path.dirname(os.path.abspath(__file__))
out_path = os.path.join(script_dir, 'k494_forex_vol_results.json')
with open(out_path, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n" + "=" * 80)
print(f"COMPLETE — Elapsed: {elapsed:.1f}s")
print(f"Results saved to: {out_path}")
print(f"=" * 80)

# Final summary
print(f"\n{'='*80}")
print("FINAL SUMMARY")
print(f"{'='*80}")
for line in summary_lines:
    print(f"  {line}")
print(f"\nConclusions:")
for c in conclusions:
    print(f"  • {c}")
