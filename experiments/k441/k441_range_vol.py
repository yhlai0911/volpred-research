"""
K441: Range-Based Volatility Estimators as GARCH Proxy
========================================================
[提出: User, 執行: Claude]

Literature:
- Parkinson (1980) "The extreme value method for estimating the variance of
  the rate of return" J. Business — σ²_P = (H-L)²/(4·ln2), efficiency 5x
- Garman & Klass (1980) "On the estimation of security price volatilities
  from historical data" J. Business — σ²_GK = 0.5·(H-L)² - (2ln2-1)·(C-O)², efficiency 7.4x
- Rogers & Satchell (1991) — σ²_RS = (H-C)(H-O)+(L-C)(L-O), no zero-drift assumption
- Yang & Zhang (2000) — Combines overnight + OHLC, drift-independent
- Alizadeh, Brandt & Diebold (2002) "Range-based estimation of stochastic
  volatility" JoF — Log range ≈ Gaussian
- Chou (2005) "Forecasting financial volatilities with extreme values:
  the CARR model" JME — Conditional AutoRegressive Range

Research Questions:
1. Does GARCH QLIKE improve when evaluated against range-based proxies?
2. Can range-based proxies substitute 5-min RV?
3. Which range estimator is best?
4. Does CARR (range model) beat standard GARCH?

Data: SPY 2005-2026, yfinance OHLC
OOS: 2023-2024
"""

import json
import time
import warnings
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy.stats import norm, describe
from scipy.optimize import minimize

warnings.filterwarnings('ignore')

start_time = time.time()
results = {
    "experiment_id": "K441",
    "title": "Range-Based Volatility Estimators as GARCH Proxy",
    "proposer": "User",
    "executor": "Claude",
    "literature": [
        "Parkinson (1980) J. Business",
        "Garman & Klass (1980) J. Business",
        "Rogers & Satchell (1991)",
        "Yang & Zhang (2000)",
        "Alizadeh, Brandt & Diebold (2002) JoF",
        "Chou (2005) JME"
    ],
    "asset": "SPY",
    "data_source": "yfinance",
    "oos_period": "2023-2024",
}

# ============================================================
# 1. DATA DOWNLOAD & PREPARATION
# ============================================================
print("=" * 70)
print("K441: Range-Based Volatility Estimators as GARCH Proxy")
print("=" * 70)

spy = yf.download('SPY', start='2005-01-01', end='2026-01-01', progress=False)
# Handle MultiIndex columns if present
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)

print(f"Data period: {spy.index[0].strftime('%Y-%m-%d')} to {spy.index[-1].strftime('%Y-%m-%d')}")
print(f"Total observations: {len(spy)}")

O = spy['Open'].values.astype(float)
H = spy['High'].values.astype(float)
L = spy['Low'].values.astype(float)
C = spy['Close'].values.astype(float)

log_O = np.log(O)
log_H = np.log(H)
log_L = np.log(L)
log_C = np.log(C)

# Returns (close-to-close)
log_ret = np.diff(log_C)  # length N-1
dates = spy.index[1:]  # align with returns

# ============================================================
# 2. RANGE-BASED ESTIMATORS (all vectorized)
# ============================================================
print("\n--- Range-Based Estimators ---")

# All estimators use OHLC from day t (aligned with return from t-1 to t)
# So use indices [1:] for OHLC to match log_ret
log_O_t = log_O[1:]
log_H_t = log_H[1:]
log_L_t = log_L[1:]
log_C_t = log_C[1:]
log_C_prev = log_C[:-1]

N = len(log_ret)

# 1. Close-to-close squared return (baseline)
rv_cc = log_ret ** 2

# 2. Parkinson (1980): σ² = (H-L)² / (4·ln2)
rv_park = (log_H_t - log_L_t) ** 2 / (4 * np.log(2))

# 3. Garman-Klass (1980): σ² = 0.5·(H-L)² - (2ln2-1)·(C-O)²
rv_gk = 0.5 * (log_H_t - log_L_t) ** 2 - (2 * np.log(2) - 1) * (log_C_t - log_O_t) ** 2

# 4. Rogers-Satchell (1991): σ² = (H-C)(H-O) + (L-C)(L-O)
rv_rs = (log_H_t - log_C_t) * (log_H_t - log_O_t) + \
        (log_L_t - log_C_t) * (log_L_t - log_O_t)

# 5. Yang-Zhang (2000): combines overnight + OHLC
# Overnight variance
overnight = log_O_t - log_C_prev
overnight_var = np.var(overnight, ddof=1)

# Open-to-close variance
oc = log_C_t - log_O_t
oc_var = np.var(oc, ddof=1)

# Rogers-Satchell component (already computed per-day)
rs_mean = np.mean(rv_rs)

# Yang-Zhang k factor
n = len(overnight)
k = 0.34 / (1.34 + (n + 1) / (n - 1))

# Yang-Zhang per-day: need rolling version; for simplicity use per-day components
# σ²_YZ = σ²_overnight + k·σ²_open-to-close + (1-k)·σ²_RS
# Per-day proxy: use centered overnight and oc deviations
overnight_mean = np.mean(overnight)
oc_mean = np.mean(oc)

rv_yz = (overnight - overnight_mean) ** 2 + \
        k * (oc - oc_mean) ** 2 + \
        (1 - k) * rv_rs

# 6. Log range (Alizadeh et al. 2002)
log_range = log_H_t - log_L_t  # This is log(H/L)
# Convert to variance proxy: E[log_range] ≈ sqrt(8/π)·σ → σ² ≈ (log_range)² · π/8
# But we'll keep it as an estimator: σ² = log_range² / (4·ln2) is equivalent to Parkinson
# More useful: use log_range as the target for CARR model

# Collect all estimators in a dict
estimators = {
    'CC (r²)': rv_cc,
    'Parkinson': rv_park,
    'Garman-Klass': rv_gk,
    'Rogers-Satchell': rv_rs,
    'Yang-Zhang': rv_yz,
}

# ============================================================
# 3. DESCRIPTIVE STATISTICS
# ============================================================
print("\n--- Descriptive Statistics (annualized vol = sqrt(252*mean)) ---")
print(f"{'Estimator':<20} {'Mean':>12} {'Std':>12} {'Skew':>8} {'Kurt':>8} {'Ann.Vol%':>10} {'%Neg':>8}")
print("-" * 80)

desc_stats = {}
for name, rv in estimators.items():
    # Handle negative values for GK
    mean_rv = np.mean(rv)
    std_rv = np.std(rv)
    skew_rv = float(pd.Series(rv).skew())
    kurt_rv = float(pd.Series(rv).kurtosis())
    ann_vol = np.sqrt(252 * np.abs(mean_rv)) * 100
    pct_neg = np.mean(rv < 0) * 100

    print(f"{name:<20} {mean_rv:>12.6f} {std_rv:>12.6f} {skew_rv:>8.2f} {kurt_rv:>8.1f} {ann_vol:>10.2f} {pct_neg:>8.1f}%")
    desc_stats[name] = {
        'mean': float(mean_rv),
        'std': float(std_rv),
        'skewness': float(skew_rv),
        'kurtosis': float(kurt_rv),
        'annualized_vol_pct': float(ann_vol),
        'pct_negative': float(pct_neg),
    }

results['descriptive_stats'] = desc_stats

# Log range descriptive stats (Alizadeh et al. key insight)
print("\n--- Log Range Distribution (Alizadeh et al. 2002 key insight) ---")
print(f"  Log range mean: {np.mean(log_range):.4f}")
print(f"  Log range std:  {np.std(log_range):.4f}")
print(f"  Log range skew: {float(pd.Series(log_range).skew()):.4f}")
print(f"  Log range kurt: {float(pd.Series(log_range).kurtosis()):.4f}")
print(f"  Squared return skew: {float(pd.Series(rv_cc).skew()):.4f}")
print(f"  Squared return kurt: {float(pd.Series(rv_cc).kurtosis()):.4f}")
print("  (Key: log range is much more Gaussian than r² — better for modeling)")

results['log_range_stats'] = {
    'mean': float(np.mean(log_range)),
    'std': float(np.std(log_range)),
    'skewness': float(pd.Series(log_range).skew()),
    'kurtosis': float(pd.Series(log_range).kurtosis()),
    'r2_skewness': float(pd.Series(rv_cc).skew()),
    'r2_kurtosis': float(pd.Series(rv_cc).kurtosis()),
}

# ============================================================
# 4. CROSS-CORRELATIONS between estimators
# ============================================================
print("\n--- Cross-Correlations Between Estimators ---")
est_names = list(estimators.keys())
corr_matrix = np.zeros((len(est_names), len(est_names)))
for i, n1 in enumerate(est_names):
    for j, n2 in enumerate(est_names):
        corr_matrix[i, j] = np.corrcoef(estimators[n1], estimators[n2])[0, 1]

print(f"{'':>20}", end='')
for n in est_names:
    print(f"{n:>15}", end='')
print()
for i, n1 in enumerate(est_names):
    print(f"{n1:>20}", end='')
    for j in range(len(est_names)):
        print(f"{corr_matrix[i, j]:>15.3f}", end='')
    print()

results['cross_correlations'] = {
    'estimators': est_names,
    'matrix': corr_matrix.tolist()
}

# ============================================================
# 5. GARCH ESTIMATION & EVALUATION WITH DIFFERENT PROXIES
# ============================================================
print("\n" + "=" * 70)
print("GARCH(1,1) and GJR-GARCH(1,1) evaluation with different proxies")
print("=" * 70)

# Define OOS period
oos_start = '2023-01-01'
oos_end = '2024-12-31'
dates_pd = pd.DatetimeIndex(dates)
is_oos = (dates_pd >= oos_start) & (dates_pd <= oos_end)
is_insample = ~is_oos

n_oos = np.sum(is_oos)
n_is = np.sum(is_insample)
print(f"In-sample: {n_is} obs, OOS: {n_oos} obs")

# Fit GARCH models on returns (standard approach)
returns_pct = log_ret * 100  # arch package uses % returns
returns_series = pd.Series(returns_pct, index=dates)

# Fit models
models_spec = {
    'GARCH(1,1)': {'vol': 'GARCH', 'p': 1, 'q': 1, 'o': 0},
    'GJR-GARCH(1,1)': {'vol': 'GARCH', 'p': 1, 'q': 1, 'o': 1},
    'EGARCH(1,1)': {'vol': 'EGARCH', 'p': 1, 'q': 1, 'o': 1},
}

def qlike(proxy, forecast):
    """QLIKE loss: proxy/forecast + log(forecast) - 1"""
    # Both should be variance (not %)
    ratio = proxy / forecast
    return np.mean(ratio - np.log(ratio) - 1)

def mse(proxy, forecast):
    """Mean Squared Error"""
    return np.mean((proxy - forecast) ** 2)

print("\n--- Model Fitting ---")
fitted_models = {}
for model_name, spec in models_spec.items():
    am = arch_model(returns_series, mean='Constant', vol=spec['vol'],
                    p=spec['p'], q=spec['q'], o=spec['o'], dist='normal')
    res = am.fit(disp='off', last_obs=oos_start)
    fitted_models[model_name] = res

    # Get conditional variance for full sample
    # Need to forecast OOS
    forecast = res.forecast(horizon=1, start=oos_start, reindex=False)

    print(f"\n{model_name}:")
    print(f"  Params: {dict(res.params)}")
    print(f"  Convergence: {res.convergence_flag == 0}")
    persistence = res.params.get('alpha[1]', 0) + res.params.get('beta[1]', 0) + \
                  res.params.get('gamma[1]', 0) * 0.5
    if 'EGARCH' in model_name:
        persistence = res.params.get('alpha[1]', 0) + res.params.get('beta[1]', 0)
    print(f"  Persistence: {persistence:.4f}")

# Get OOS conditional variance forecasts
print("\n--- OOS Evaluation: QLIKE with Different Proxies ---")
print(f"{'Model':<20} {'Proxy':<20} {'QLIKE':>10} {'MSE(×1e6)':>12}")
print("-" * 65)

eval_results = {}
for model_name, res in fitted_models.items():
    # Get conditional variance (in %² units, convert to decimal²)
    # Use rolling 1-step-ahead forecast for OOS
    cond_var_full = res.conditional_volatility ** 2  # in %²

    # For OOS, we need forecasted variance
    forecast = res.forecast(horizon=1, start=oos_start, reindex=False)
    oos_var_pct2 = forecast.variance.dropna().values.flatten()

    # Ensure alignment
    oos_dates = dates_pd[is_oos]
    min_len = min(len(oos_var_pct2), int(np.sum(is_oos)))
    oos_var = oos_var_pct2[:min_len] / (100 ** 2)  # convert to decimal variance

    eval_results[model_name] = {}

    for proxy_name, rv_full in estimators.items():
        rv_oos = rv_full[is_oos][:min_len]

        # Skip if proxy has negatives (truncate at small positive for QLIKE)
        rv_oos_clean = np.maximum(rv_oos, 1e-12)
        oos_var_clean = np.maximum(oos_var, 1e-12)

        ql = qlike(rv_oos_clean, oos_var_clean)
        ms = mse(rv_oos_clean, oos_var_clean)

        print(f"{model_name:<20} {proxy_name:<20} {ql:>10.4f} {ms * 1e6:>12.4f}")
        eval_results[model_name][proxy_name] = {
            'qlike': float(ql),
            'mse': float(ms * 1e6),
        }

results['oos_evaluation'] = eval_results

# ============================================================
# 6. CROSS-PROXY CONSISTENCY: Do different proxies give same model ranking?
# ============================================================
print("\n--- Cross-Proxy Consistency: Model Rankings ---")
print(f"{'Proxy':<20}", end='')
for m in models_spec:
    print(f" {m:>20}", end='')
print(f" {'Best Model':>20}")
print("-" * 100)

ranking_results = {}
for proxy_name in estimators:
    qlikes = {}
    for model_name in models_spec:
        qlikes[model_name] = eval_results[model_name][proxy_name]['qlike']

    ranked = sorted(qlikes.items(), key=lambda x: x[1])
    best = ranked[0][0]

    print(f"{proxy_name:<20}", end='')
    for m in models_spec:
        rank = [r[0] for r in ranked].index(m) + 1
        print(f" {qlikes[m]:>14.4f}(#{rank})", end='')
    print(f" {best:>20}")

    ranking_results[proxy_name] = {
        'rankings': {m: [r[0] for r in ranked].index(m) + 1 for m in models_spec},
        'best_model': best,
        'qlikes': {m: float(qlikes[m]) for m in models_spec}
    }

results['cross_proxy_consistency'] = ranking_results

# Check if rankings are consistent
all_bests = [v['best_model'] for v in ranking_results.values()]
consistent = len(set(all_bests)) == 1
print(f"\nConsistency: {'YES — all proxies agree on best model' if consistent else 'NO — proxies disagree'}")
print(f"Best model votes: {dict(pd.Series(all_bests).value_counts())}")
results['ranking_consistent'] = consistent

# ============================================================
# 7. DIEBOLD-MARIANO TESTS
# ============================================================
print("\n--- Diebold-Mariano Tests (QLIKE loss differential) ---")

def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: E[d]=0. Returns t-stat, p-value."""
    d = loss1 - loss2
    n = len(d)
    d_bar = np.mean(d)

    # HAC variance (Newey-West)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h + 1):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * (1 - k / (h + 1)) * gamma_k

    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        var_d = gamma_0 / n

    dm_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * (1 - norm.cdf(np.abs(dm_stat)))
    return float(dm_stat), float(p_val)

# Use Parkinson as the "best" proxy (most commonly cited)
dm_results = {}

# For each proxy, test GJR vs GARCH and EGARCH vs GARCH
for proxy_name in estimators:
    rv_oos = estimators[proxy_name][is_oos]

    dm_results[proxy_name] = {}

    for model_name in ['GJR-GARCH(1,1)', 'EGARCH(1,1)']:
        # Get losses
        # GARCH losses
        res_garch = fitted_models['GARCH(1,1)']
        fc_garch = res_garch.forecast(horizon=1, start=oos_start, reindex=False)
        var_garch = fc_garch.variance.dropna().values.flatten() / (100 ** 2)

        res_alt = fitted_models[model_name]
        fc_alt = res_alt.forecast(horizon=1, start=oos_start, reindex=False)
        var_alt = fc_alt.variance.dropna().values.flatten() / (100 ** 2)

        min_len = min(len(var_garch), len(var_alt), int(np.sum(is_oos)))
        rv_clean = np.maximum(rv_oos[:min_len], 1e-12)
        var_garch_c = np.maximum(var_garch[:min_len], 1e-12)
        var_alt_c = np.maximum(var_alt[:min_len], 1e-12)

        # QLIKE losses
        loss_garch = rv_clean / var_garch_c + np.log(var_garch_c)
        loss_alt = rv_clean / var_alt_c + np.log(var_alt_c)

        dm_stat, p_val = dm_test(loss_garch, loss_alt, h=1)
        sig = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''

        dm_results[proxy_name][f"GARCH_vs_{model_name}"] = {
            'dm_stat': dm_stat,
            'p_value': p_val,
            'direction': f"{'GARCH better' if dm_stat < 0 else model_name + ' better'}"
        }

# Print DM results compactly
print(f"\nH0: GARCH(1,1) = Alternative (positive DM → Alternative better)")
print(f"{'Proxy':<20} {'GJR vs GARCH':>20} {'EGARCH vs GARCH':>20}")
print("-" * 65)
for proxy_name in estimators:
    gjr = dm_results[proxy_name]['GARCH_vs_GJR-GARCH(1,1)']
    egarch = dm_results[proxy_name]['GARCH_vs_EGARCH(1,1)']
    gjr_sig = '***' if gjr['p_value'] < 0.01 else '**' if gjr['p_value'] < 0.05 else '*' if gjr['p_value'] < 0.10 else ''
    egarch_sig = '***' if egarch['p_value'] < 0.01 else '**' if egarch['p_value'] < 0.05 else '*' if egarch['p_value'] < 0.10 else ''
    print(f"{proxy_name:<20} {gjr['dm_stat']:>8.3f} (p={gjr['p_value']:.3f}){gjr_sig:>4} {egarch['dm_stat']:>8.3f} (p={egarch['p_value']:.3f}){egarch_sig:>4}")

results['dm_tests'] = dm_results

# ============================================================
# 8. CARR MODEL (Chou 2005)
# ============================================================
print("\n" + "=" * 70)
print("CARR Model (Chou 2005): Conditional AutoRegressive Range")
print("=" * 70)

# CARR: R_t = λ_t · ε_t, where ε_t ~ Exp(1)
# λ_t = ω + α · R_{t-1} + β · λ_{t-1}
# Log-likelihood: -log(λ_t) - R_t/λ_t (exponential)

range_t = H[1:] / L[1:]  # price range ratio
# Or use: (H-L)/C as normalized range (Chou uses actual range)
# We'll use log range for better numerical properties
range_vals = (H[1:] - L[1:]).astype(float)  # actual range in price
range_pct = range_vals / C[1:].astype(float) * 100  # percentage range

print(f"Range (%) stats: mean={np.mean(range_pct):.4f}, std={np.std(range_pct):.4f}")

def carr_loglik(params, R, return_lambda=False):
    """
    CARR(1,1) log-likelihood with exponential distribution.
    R_t = λ_t · ε_t, ε_t ~ Exp(1)
    λ_t = ω + α·R_{t-1} + β·λ_{t-1}
    LL = Σ [-log(λ_t) - R_t/λ_t]
    """
    omega, alpha, beta = params
    T = len(R)

    # Constraints
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1:
        return 1e10 if not return_lambda else (1e10, np.ones(T))

    lam = np.zeros(T)
    lam[0] = omega / (1 - alpha - beta)  # unconditional mean

    for t in range(1, T):
        lam[t] = omega + alpha * R[t - 1] + beta * lam[t - 1]
        if lam[t] <= 0:
            lam[t] = 1e-8

    ll = -np.log(lam) - R / lam

    if return_lambda:
        return -np.sum(ll), lam
    return -np.sum(ll)


def carr_weibull_loglik(params, R, return_lambda=False):
    """
    CARR(1,1) with Weibull distribution.
    f(ε) = κ · ε^(κ-1) · exp(-ε^κ)
    LL = Σ [log(κ) + (κ-1)·log(R_t/λ_t) - (R_t/λ_t)^κ - log(λ_t)]
    """
    omega, alpha, beta, kappa = params
    T = len(R)

    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 1 or kappa <= 0:
        return 1e10 if not return_lambda else (1e10, np.ones(T))

    lam = np.zeros(T)
    lam[0] = omega / (1 - alpha - beta)

    for t in range(1, T):
        lam[t] = omega + alpha * R[t - 1] + beta * lam[t - 1]
        if lam[t] <= 0:
            lam[t] = 1e-8

    eps = R / lam
    ll = np.log(kappa) + (kappa - 1) * np.log(np.maximum(eps, 1e-12)) - \
         eps ** kappa - np.log(lam)

    if return_lambda:
        return -np.sum(ll), lam
    return -np.sum(ll)


# Fit CARR on in-sample
range_is = range_pct[is_insample]
range_oos = range_pct[is_oos]

# CARR-Exponential
print("\nFitting CARR-Exp...")
x0_exp = [0.1, 0.1, 0.8]
bounds_exp = [(1e-6, 5), (1e-6, 0.5), (1e-6, 0.999)]

res_carr_exp = minimize(carr_loglik, x0_exp, args=(range_is,),
                        method='L-BFGS-B', bounds=bounds_exp,
                        options={'maxiter': 5000})

if res_carr_exp.success:
    omega_e, alpha_e, beta_e = res_carr_exp.x
    pers_e = alpha_e + beta_e
    print(f"  CARR-Exp: ω={omega_e:.4f}, α={alpha_e:.4f}, β={beta_e:.4f}, persistence={pers_e:.4f}")
    print(f"  Convergence: {res_carr_exp.success}, LL={-res_carr_exp.fun:.2f}")
else:
    print(f"  CARR-Exp convergence FAILED: {res_carr_exp.message}")

# CARR-Weibull
print("\nFitting CARR-Weibull...")
x0_weib = [0.1, 0.1, 0.8, 1.5]
bounds_weib = [(1e-6, 5), (1e-6, 0.5), (1e-6, 0.999), (0.5, 5.0)]

res_carr_weib = minimize(carr_weibull_loglik, x0_weib, args=(range_is,),
                         method='L-BFGS-B', bounds=bounds_weib,
                         options={'maxiter': 5000})

if res_carr_weib.success:
    omega_w, alpha_w, beta_w, kappa_w = res_carr_weib.x
    pers_w = alpha_w + beta_w
    print(f"  CARR-Weibull: ω={omega_w:.4f}, α={alpha_w:.4f}, β={beta_w:.4f}, κ={kappa_w:.4f}, persistence={pers_w:.4f}")
    print(f"  Convergence: {res_carr_weib.success}, LL={-res_carr_weib.fun:.2f}")
else:
    print(f"  CARR-Weibull convergence FAILED: {res_carr_weib.message}")

# OOS forecast for CARR
print("\nCARR OOS Forecasting...")
# Re-fit on full in-sample and forecast OOS
full_range = range_pct.copy()
T_full = len(full_range)

# Get lambda for full sample using in-sample params
_, lam_full_exp = carr_loglik(res_carr_exp.x, full_range, return_lambda=True)
_, lam_full_weib = carr_weibull_loglik(res_carr_weib.x, full_range, return_lambda=True)

# OOS lambda forecasts
lam_oos_exp = lam_full_exp[is_oos]
lam_oos_weib = lam_full_weib[is_oos]

# Convert CARR lambda (range forecast) to variance forecast
# Range ≈ k · σ (Parkinson: k = sqrt(4·ln2) ≈ 1.665)
# So σ = range / k, σ² = range² / k²
parkinson_k = np.sqrt(4 * np.log(2))
var_oos_carr_exp = (lam_oos_exp / 100) ** 2 / (parkinson_k ** 2)  # convert back to decimal variance
var_oos_carr_weib = (lam_oos_weib / 100) ** 2 / (parkinson_k ** 2)

# CARR results
carr_results = {
    'CARR_Exp': {
        'omega': float(omega_e),
        'alpha': float(alpha_e),
        'beta': float(beta_e),
        'persistence': float(pers_e),
        'converged': bool(res_carr_exp.success),
        'loglik': float(-res_carr_exp.fun),
    },
    'CARR_Weibull': {
        'omega': float(omega_w),
        'alpha': float(alpha_w),
        'beta': float(beta_w),
        'kappa': float(kappa_w),
        'persistence': float(pers_w),
        'converged': bool(res_carr_weib.success),
        'loglik': float(-res_carr_weib.fun),
    }
}

# Evaluate CARR against different proxies
print(f"\n{'Model':<20} {'Proxy':<20} {'QLIKE':>10}")
print("-" * 55)

carr_eval = {}
for proxy_name, rv_full in estimators.items():
    rv_oos = rv_full[is_oos]
    min_len = min(len(rv_oos), len(var_oos_carr_exp))
    rv_clean = np.maximum(rv_oos[:min_len], 1e-12)

    # CARR-Exp
    var_exp_c = np.maximum(var_oos_carr_exp[:min_len], 1e-12)
    ql_exp = qlike(rv_clean, var_exp_c)

    # CARR-Weibull
    var_weib_c = np.maximum(var_oos_carr_weib[:min_len], 1e-12)
    ql_weib = qlike(rv_clean, var_weib_c)

    print(f"{'CARR-Exp':<20} {proxy_name:<20} {ql_exp:>10.4f}")
    print(f"{'CARR-Weibull':<20} {proxy_name:<20} {ql_weib:>10.4f}")

    carr_eval[proxy_name] = {
        'CARR_Exp_QLIKE': float(ql_exp),
        'CARR_Weibull_QLIKE': float(ql_weib),
    }

results['carr_model'] = carr_results
results['carr_evaluation'] = carr_eval

# ============================================================
# 9. COMPREHENSIVE COMPARISON: All models × All proxies
# ============================================================
print("\n" + "=" * 70)
print("COMPREHENSIVE COMPARISON: All Models × All Proxies (QLIKE)")
print("=" * 70)

# Combine all models
all_models_qlike = {}
for model_name in models_spec:
    all_models_qlike[model_name] = {}
    res = fitted_models[model_name]
    fc = res.forecast(horizon=1, start=oos_start, reindex=False)
    var_oos = fc.variance.dropna().values.flatten() / (100 ** 2)

    for proxy_name in estimators:
        rv_oos = estimators[proxy_name][is_oos]
        min_len = min(len(var_oos), int(np.sum(is_oos)))
        rv_clean = np.maximum(rv_oos[:min_len], 1e-12)
        var_clean = np.maximum(var_oos[:min_len], 1e-12)
        all_models_qlike[model_name][proxy_name] = float(qlike(rv_clean, var_clean))

# Add CARR models
all_models_qlike['CARR-Exp'] = {}
all_models_qlike['CARR-Weibull'] = {}
for proxy_name in estimators:
    rv_oos = estimators[proxy_name][is_oos]
    min_len = min(len(rv_oos), len(var_oos_carr_exp))
    rv_clean = np.maximum(rv_oos[:min_len], 1e-12)
    all_models_qlike['CARR-Exp'][proxy_name] = float(qlike(rv_clean, np.maximum(var_oos_carr_exp[:min_len], 1e-12)))
    all_models_qlike['CARR-Weibull'][proxy_name] = float(qlike(rv_clean, np.maximum(var_oos_carr_weib[:min_len], 1e-12)))

# Print table
all_model_names = list(all_models_qlike.keys())
print(f"\n{'Model':<20}", end='')
for p in estimators:
    print(f" {p:>15}", end='')
print(f" {'Avg Rank':>10}")
print("-" * (20 + 15 * len(estimators) + 12))

# Compute rankings per proxy
rankings_per_proxy = {}
for proxy_name in estimators:
    qlikes = [(m, all_models_qlike[m][proxy_name]) for m in all_model_names]
    qlikes.sort(key=lambda x: x[1])
    rankings_per_proxy[proxy_name] = {m: rank + 1 for rank, (m, _) in enumerate(qlikes)}

avg_ranks = {}
for m in all_model_names:
    ranks = [rankings_per_proxy[p][m] for p in estimators]
    avg_ranks[m] = np.mean(ranks)

    print(f"{m:<20}", end='')
    for p in estimators:
        ql = all_models_qlike[m][p]
        rank = rankings_per_proxy[p][m]
        print(f" {ql:>10.4f}(#{rank})", end='')
    print(f" {avg_ranks[m]:>10.2f}")

results['comprehensive_comparison'] = {
    'qlike_table': all_models_qlike,
    'average_ranks': {k: float(v) for k, v in avg_ranks.items()},
}

# ============================================================
# 10. DM TEST: CARR vs GJR-GARCH (the key test)
# ============================================================
print("\n--- DM Test: CARR vs GJR-GARCH ---")

res_gjr = fitted_models['GJR-GARCH(1,1)']
fc_gjr = res_gjr.forecast(horizon=1, start=oos_start, reindex=False)
var_gjr_oos = fc_gjr.variance.dropna().values.flatten() / (100 ** 2)

dm_carr_vs_gjr = {}
for proxy_name in estimators:
    rv_oos = estimators[proxy_name][is_oos]
    min_len = min(len(rv_oos), len(var_gjr_oos), len(var_oos_carr_exp))
    rv_clean = np.maximum(rv_oos[:min_len], 1e-12)
    var_gjr_c = np.maximum(var_gjr_oos[:min_len], 1e-12)
    var_carr_c = np.maximum(var_oos_carr_exp[:min_len], 1e-12)

    loss_gjr = rv_clean / var_gjr_c + np.log(var_gjr_c)
    loss_carr = rv_clean / var_carr_c + np.log(var_carr_c)

    dm_stat, p_val = dm_test(loss_gjr, loss_carr, h=1)
    sig = '***' if p_val < 0.01 else '**' if p_val < 0.05 else '*' if p_val < 0.10 else ''
    direction = 'CARR better' if dm_stat > 0 else 'GJR better'

    print(f"  {proxy_name:<20} DM={dm_stat:>7.3f} (p={p_val:.3f}){sig:>4} → {direction}")

    dm_carr_vs_gjr[proxy_name] = {
        'dm_stat': float(dm_stat),
        'p_value': float(p_val),
        'direction': direction,
    }

results['dm_carr_vs_gjr'] = dm_carr_vs_gjr

# ============================================================
# 11. EFFICIENCY COMPARISON: Variance of estimators
# ============================================================
print("\n--- Efficiency: Relative Variance of Estimators ---")
print("(Lower = more efficient. Normalized to CC baseline)")

# Use rolling 22-day windows to estimate monthly variance, then compare
window = 22
efficiency = {}
baseline_vars = []
for i in range(window, N):
    baseline_vars.append(np.var(rv_cc[i - window:i]))
baseline_var_mean = np.mean(baseline_vars)

print(f"{'Estimator':<20} {'Var(est)':>12} {'Relative':>10} {'Efficiency':>12}")
print("-" * 60)
for name, rv in estimators.items():
    rolling_vars = []
    for i in range(window, N):
        rolling_vars.append(np.var(rv[i - window:i]))
    mean_var = np.mean(rolling_vars)
    relative = mean_var / baseline_var_mean
    eff = 1 / relative if relative > 0 else float('inf')

    print(f"{name:<20} {mean_var:>12.2e} {relative:>10.3f} {eff:>12.2f}x")
    efficiency[name] = {
        'variance': float(mean_var),
        'relative_to_cc': float(relative),
        'efficiency_multiple': float(eff),
    }

results['efficiency'] = efficiency

# ============================================================
# 12. RESIDUAL DIAGNOSTICS
# ============================================================
print("\n--- Residual Diagnostics (GJR-GARCH) ---")
res_gjr_full = fitted_models['GJR-GARCH(1,1)']
std_resid = res_gjr_full.std_resid.dropna()

from scipy.stats import jarque_bera
from statsmodels.stats.diagnostic import acorr_ljungbox

jb_stat, jb_p = jarque_bera(std_resid)
print(f"Jarque-Bera: stat={jb_stat:.2f}, p={jb_p:.4f}")

lb = acorr_ljungbox(std_resid ** 2, lags=[10, 20], return_df=True)
print(f"Ljung-Box (squared resid):")
for lag in lb.index:
    print(f"  Lag {lag}: Q={lb.loc[lag, 'lb_stat']:.2f}, p={lb.loc[lag, 'lb_pvalue']:.4f}")

results['diagnostics'] = {
    'jarque_bera': {'stat': float(jb_stat), 'p_value': float(jb_p)},
    'ljung_box_sq_resid': {
        f'lag_{lag}': {'Q': float(lb.loc[lag, 'lb_stat']), 'p': float(lb.loc[lag, 'lb_pvalue'])}
        for lag in lb.index
    }
}

# ============================================================
# 13. RANGE-BASED PROXY AS 5-MIN RV SUBSTITUTE?
# ============================================================
print("\n--- Can Range-Based Proxy Substitute 5-Min RV? ---")
# Load 5-min RV if available
import os
rv5_path = os.path.join(os.path.dirname(__file__), '..', 'data', '5min', 'SPY_5min.parquet')
has_5min = os.path.exists(rv5_path)

if has_5min:
    print("Loading 5-min data for comparison...")
    df_5min = pd.read_parquet(rv5_path)
    # Compute daily RV from 5-min returns
    df_5min['date'] = df_5min.index.date
    if 'Close' in df_5min.columns:
        df_5min['log_ret'] = np.log(df_5min['Close'] / df_5min['Close'].shift(1))
        daily_rv = df_5min.groupby('date')['log_ret'].apply(lambda x: np.sum(x.dropna() ** 2))

        # Align with our dates
        common_dates = set(daily_rv.index) & set([d.date() for d in dates_pd])
        print(f"  Common dates with 5-min RV: {len(common_dates)}")

        if len(common_dates) > 100:
            # Compare correlations
            aligned = pd.DataFrame(index=sorted(common_dates))
            aligned['rv_5min'] = [daily_rv.loc[d] if d in daily_rv.index else np.nan for d in aligned.index]

            for name, rv in estimators.items():
                rv_series = pd.Series(rv, index=[d.date() for d in dates_pd])
                aligned[name] = [rv_series.loc[d] if d in rv_series.index else np.nan for d in aligned.index]

            aligned = aligned.dropna()

            print(f"\n  Correlations with 5-Min RV:")
            rv5_corr = {}
            for name in estimators:
                corr = aligned['rv_5min'].corr(aligned[name])
                print(f"    {name:<20}: {corr:.4f}")
                rv5_corr[name] = float(corr)

            results['rv5min_comparison'] = rv5_corr
        else:
            print("  Not enough overlapping 5-min RV data for comparison")
            results['rv5min_comparison'] = 'insufficient_data'
    else:
        print("  5-min data format not compatible")
        results['rv5min_comparison'] = 'format_error'
else:
    print("  No 5-min data available. Using theoretical efficiency ratios.")
    print("  Parkinson efficiency: ~5x close-to-close")
    print("  Garman-Klass efficiency: ~7.4x close-to-close")
    print("  5-min RV (78 intervals) efficiency: ~78x close-to-close (in theory)")
    print("  → Range estimators are better than CC but worse than 5-min RV")
    print("  → However, range estimators require only daily OHLC (universally available)")
    results['rv5min_comparison'] = 'no_5min_data_available'

# ============================================================
# 14. SUMMARY
# ============================================================
elapsed = time.time() - start_time
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)

# Find best model overall
best_model_overall = min(avg_ranks, key=avg_ranks.get)
print(f"\n1. Best model (avg rank across all proxies): {best_model_overall} (avg rank: {avg_ranks[best_model_overall]:.2f})")

# Proxy impact on QLIKE
print(f"\n2. Proxy impact on QLIKE (GJR-GARCH):")
for proxy_name in estimators:
    ql = all_models_qlike['GJR-GARCH(1,1)'][proxy_name]
    print(f"   {proxy_name:<20}: QLIKE = {ql:.4f}")

print(f"\n3. Cross-proxy consistency: {'YES' if consistent else 'NO'}")

print(f"\n4. Key findings:")
# Which proxy gives lowest QLIKE?
gjr_qlikes = {p: all_models_qlike['GJR-GARCH(1,1)'][p] for p in estimators}
best_proxy = min(gjr_qlikes, key=gjr_qlikes.get)
worst_proxy = max(gjr_qlikes, key=gjr_qlikes.get)
print(f"   Best proxy for GJR evaluation: {best_proxy} (QLIKE={gjr_qlikes[best_proxy]:.4f})")
print(f"   Worst proxy: {worst_proxy} (QLIKE={gjr_qlikes[worst_proxy]:.4f})")
print(f"   QLIKE reduction: {(gjr_qlikes[worst_proxy] - gjr_qlikes[best_proxy]) / gjr_qlikes[worst_proxy] * 100:.1f}%")

print(f"\n5. CARR model:")
if res_carr_exp.success:
    print(f"   CARR-Exp persistence: {pers_e:.4f}")
    carr_avg_ql = np.mean([all_models_qlike['CARR-Exp'][p] for p in estimators])
    gjr_avg_ql = np.mean([all_models_qlike['GJR-GARCH(1,1)'][p] for p in estimators])
    print(f"   CARR-Exp avg QLIKE: {carr_avg_ql:.4f} vs GJR avg QLIKE: {gjr_avg_ql:.4f}")
    print(f"   → {'CARR better' if carr_avg_ql < gjr_avg_ql else 'GJR better'}")

print(f"\n6. Efficiency ratios (vs close-to-close):")
for name in ['Parkinson', 'Garman-Klass', 'Rogers-Satchell', 'Yang-Zhang']:
    eff = efficiency[name]['efficiency_multiple']
    print(f"   {name:<20}: {eff:.2f}x")

print(f"\n7. Log range normality (Alizadeh et al.):")
lr_skew = results['log_range_stats']['skewness']
lr_kurt = results['log_range_stats']['kurtosis']
r2_skew = results['log_range_stats']['r2_skewness']
r2_kurt = results['log_range_stats']['r2_kurtosis']
print(f"   Log range: skew={lr_skew:.2f}, kurt={lr_kurt:.2f}")
print(f"   Squared return: skew={r2_skew:.2f}, kurt={r2_kurt:.2f}")
print(f"   → Log range is {'much more' if abs(lr_skew) < abs(r2_skew) else 'NOT more'} Gaussian")

results['summary'] = {
    'best_model_overall': best_model_overall,
    'best_model_avg_rank': float(avg_ranks[best_model_overall]),
    'best_proxy_for_gjr': best_proxy,
    'worst_proxy_for_gjr': worst_proxy,
    'qlike_reduction_pct': float((gjr_qlikes[worst_proxy] - gjr_qlikes[best_proxy]) / gjr_qlikes[worst_proxy] * 100),
    'ranking_consistent': consistent,
    'log_range_more_gaussian': bool(abs(lr_skew) < abs(r2_skew)),
    'elapsed_seconds': float(elapsed),
}

results['elapsed_seconds'] = float(elapsed)
print(f"\nTotal runtime: {elapsed:.1f}s")

# Save results
output_path = os.path.join(os.path.dirname(__file__), 'k441_range_vol_results.json')
with open(output_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nResults saved to: {output_path}")
