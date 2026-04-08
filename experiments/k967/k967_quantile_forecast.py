"""
K967: Probabilistic Volatility Quantile Forecasting
=====================================================
GARCH-based VaR vs CAViaR vs Quantile Regression

Methods:
1. GJR-GARCH(1,1) with Student-t → parametric VaR/ES
2. CAViaR (SAV, AS) — Engle & Manganelli (2004) JBE
3. Quantile Regression on |r_t| — statsmodels QuantReg

Data: SPY 2006-2026, IS: 2006-2020, OOS: 2021-2026
Evaluation: Pinball loss, Coverage (Kupiec), Christoffersen, DM test

References:
- Engle & Manganelli (2004) "CAViaR", JBE 22, 367-381
- Xiao & Koenker (2009) "Conditional Quantile Estimation for GARCH Models", JASA
- Patton (2011) "Volatility Forecast Comparison Using Imperfect Proxies", JoE

Author: VolPred Research System
Seed: 42 (all random operations)
"""

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')
np.random.seed(42)

import yfinance as yf
from arch import arch_model
from scipy import optimize, stats
from statsmodels.regression.quantile_regression import QuantReg
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import json
import os
from datetime import datetime

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. DATA
# ============================================================
print("=" * 60)
print("K967: Probabilistic Volatile Quantile Forecasting")
print("=" * 60)

print("\n[1] Downloading data...")
spy = yf.download('SPY', start='2006-01-01', end='2026-04-07', progress=False)
vix = yf.download('^VIX', start='2006-01-01', end='2026-04-07', progress=False)

# Handle multi-level columns from yfinance
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)
if isinstance(vix.columns, pd.MultiIndex):
    vix.columns = vix.columns.get_level_values(0)

# Returns
spy['ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy['abs_ret'] = spy['ret'].abs()
spy['ret_sq'] = spy['ret'] ** 2
spy = spy.dropna(subset=['ret'])

# Merge VIX
vix_close = vix[['Close']].rename(columns={'Close': 'VIX'})
data = spy[['ret', 'abs_ret', 'ret_sq']].join(vix_close, how='left')
data['VIX'] = data['VIX'].ffill()
data = data.dropna()

print(f"  Total observations: {len(data)}")
print(f"  Period: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}")

# IS/OOS split
is_end = '2020-12-31'
is_data = data.loc[:is_end]
oos_data = data.loc[is_end:].iloc[1:]  # exclude boundary

print(f"  IS: {len(is_data)} obs ({is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')})")
print(f"  OOS: {len(oos_data)} obs ({oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')})")

# Quantile levels
ALPHAS = [0.01, 0.05, 0.10, 0.90, 0.95, 0.99]

# ============================================================
# 2. METHOD 1: GJR-GARCH(1,1) Student-t VaR
# ============================================================
print("\n[2] GJR-GARCH(1,1) with Student-t...")

# Fit on full IS data
returns_pct = data['ret'] * 100  # arch package uses percentage returns
is_ret_pct = returns_pct.loc[:is_end]

gjr = arch_model(is_ret_pct, vol='GARCH', p=1, o=1, q=1, dist='studentst', mean='ARX')
gjr_fit = gjr.fit(disp='off')
print(f"  Convergence: {gjr_fit.convergence_flag}")
print(f"  Parameters: omega={gjr_fit.params.get('omega', 'N/A'):.6f}, "
      f"alpha={gjr_fit.params.get('alpha[1]', 'N/A'):.6f}, "
      f"gamma={gjr_fit.params.get('gamma[1]', 'N/A'):.6f}, "
      f"beta={gjr_fit.params.get('beta[1]', 'N/A'):.6f}")

nu = gjr_fit.params.get('nu', 5.0)
print(f"  DoF (nu): {nu:.2f}")
persistence = gjr_fit.params.get('alpha[1]', 0) + gjr_fit.params.get('gamma[1]', 0) / 2 + gjr_fit.params.get('beta[1]', 0)
print(f"  Persistence: {persistence:.4f}")

# OOS recursive VaR forecast using GARCH
# For each OOS day, use expanding window GARCH
# But full re-estimation is too slow for ~1300 days
# Instead: use fixed parameters, recursive h_t update

omega = gjr_fit.params.get('omega', 0.01)
alpha1 = gjr_fit.params.get('alpha[1]', 0.05)
gamma1 = gjr_fit.params.get('gamma[1]', 0.05)
beta1 = gjr_fit.params.get('beta[1]', 0.90)
mu_param = gjr_fit.params.get('Const', 0.0)

# Build conditional variance series for IS period
h_series = pd.Series(index=data.index, dtype=float)
eps_series = pd.Series(index=data.index, dtype=float)

# Initialize with unconditional variance
h_uncond = omega / (1 - alpha1 - gamma1 / 2 - beta1) if persistence < 1 else is_ret_pct.var()
h_series.iloc[0] = h_uncond
eps_series.iloc[0] = returns_pct.iloc[0] - mu_param

for t in range(1, len(data)):
    r_prev = returns_pct.iloc[t - 1] - mu_param
    h_prev = h_series.iloc[t - 1]
    indicator = 1.0 if r_prev < 0 else 0.0
    h_t = omega + alpha1 * r_prev**2 + gamma1 * indicator * r_prev**2 + beta1 * h_prev
    h_series.iloc[t] = max(h_t, 1e-8)
    eps_series.iloc[t] = returns_pct.iloc[t] - mu_param

# GARCH VaR: VaR_alpha = mu + sigma * q_alpha(t_nu) * sqrt((nu-2)/nu)
# Student-t quantile with scale correction
scale_factor = np.sqrt((nu - 2) / nu) if nu > 2 else 1.0

garch_var = {}
garch_es = {}
for alpha in ALPHAS:
    q_t = stats.t.ppf(alpha, df=nu) * scale_factor
    # VaR in percentage returns, convert back
    var_pct = mu_param + np.sqrt(h_series) * q_t
    garch_var[alpha] = var_pct / 100  # back to decimal

    # ES: E[r | r < VaR] for Student-t
    # ES_alpha = mu + sigma * scale * (-t_pdf(q) / alpha) * (nu + q^2) / (nu - 1)
    q_raw = stats.t.ppf(alpha, df=nu)
    if alpha <= 0.5:
        es_factor = (-stats.t.pdf(q_raw, df=nu) / alpha) * (nu + q_raw**2) / (nu - 1)
        es_pct = mu_param + np.sqrt(h_series) * scale_factor * es_factor
        garch_es[alpha] = es_pct / 100
    else:
        # Upper tail ES
        q_upper = stats.t.ppf(1 - alpha, df=nu)
        es_factor = (stats.t.pdf(q_upper, df=nu) / (1 - alpha)) * (nu + q_upper**2) / (nu - 1)
        es_pct = mu_param + np.sqrt(h_series) * scale_factor * es_factor
        garch_es[alpha] = es_pct / 100

print("  GARCH VaR computed for all quantile levels.")

# ============================================================
# 3. METHOD 2: CAViaR (SAV and AS)
# ============================================================
print("\n[3] CAViaR models...")

def caviar_sav(params, returns, alpha):
    """Symmetric Absolute Value CAViaR: Q_t = b0 + b1*Q_{t-1} + b2*|r_{t-1}|"""
    b0, b1, b2 = params
    T = len(returns)
    Q = np.zeros(T)
    Q[0] = np.quantile(returns[:100], alpha) if alpha <= 0.5 else np.quantile(returns[:100], alpha)

    for t in range(1, T):
        Q[t] = b0 + b1 * Q[t - 1] + b2 * abs(returns[t - 1])

    return Q

def caviar_as(params, returns, alpha):
    """Asymmetric Slope CAViaR: Q_t = b0 + b1*Q_{t-1} + b2*max(r_{t-1},0) + b3*max(-r_{t-1},0)"""
    b0, b1, b2, b3 = params
    T = len(returns)
    Q = np.zeros(T)
    Q[0] = np.quantile(returns[:100], alpha) if alpha <= 0.5 else np.quantile(returns[:100], alpha)

    for t in range(1, T):
        Q[t] = b0 + b1 * Q[t - 1] + b2 * max(returns[t - 1], 0) + b3 * max(-returns[t - 1], 0)

    return Q

def pinball_loss(returns, quantiles, alpha):
    """Quantile loss / check function"""
    errors = returns - quantiles
    loss = np.where(errors >= 0, alpha * errors, (alpha - 1) * errors)
    return np.mean(loss)

def caviar_objective_sav(params, returns, alpha):
    Q = caviar_sav(params, returns, alpha)
    return pinball_loss(returns, Q, alpha)

def caviar_objective_as(params, returns, alpha):
    Q = caviar_as(params, returns, alpha)
    return pinball_loss(returns, Q, alpha)

is_returns = is_data['ret'].values
all_returns = data['ret'].values

caviar_var = {}

for alpha in ALPHAS:
    print(f"  Fitting CAViaR for alpha={alpha}...")

    # SAV
    q_init = np.quantile(is_returns, alpha)
    x0_sav = [q_init * 0.1, 0.9, 0.1 if alpha <= 0.5 else -0.1]
    bounds_sav = [(-0.1, 0.1), (0.5, 0.999), (-0.5, 0.5)]

    try:
        res_sav = optimize.minimize(
            caviar_objective_sav, x0_sav,
            args=(is_returns, alpha),
            method='Nelder-Mead',
            options={'maxiter': 10000, 'xatol': 1e-8, 'fatol': 1e-8}
        )
        Q_sav_full = caviar_sav(res_sav.x, all_returns, alpha)
        loss_sav = pinball_loss(is_returns, Q_sav_full[:len(is_returns)], alpha)
    except Exception as e:
        print(f"    SAV failed: {e}")
        Q_sav_full = np.full(len(all_returns), np.quantile(all_returns, alpha))
        loss_sav = 1e10

    # AS
    x0_as = [q_init * 0.1, 0.9, 0.05, 0.15]
    bounds_as = [(-0.1, 0.1), (0.5, 0.999), (-0.5, 0.5), (-0.5, 0.5)]

    try:
        res_as = optimize.minimize(
            caviar_objective_as, x0_as,
            args=(is_returns, alpha),
            method='Nelder-Mead',
            options={'maxiter': 10000, 'xatol': 1e-8, 'fatol': 1e-8}
        )
        Q_as_full = caviar_as(res_as.x, all_returns, alpha)
        loss_as = pinball_loss(is_returns, Q_as_full[:len(is_returns)], alpha)
    except Exception as e:
        print(f"    AS failed: {e}")
        Q_as_full = np.full(len(all_returns), np.quantile(all_returns, alpha))
        loss_as = 1e10

    # Pick better model
    if loss_sav <= loss_as:
        caviar_var[alpha] = pd.Series(Q_sav_full, index=data.index)
        print(f"    Best: SAV (loss={loss_sav:.6f})")
    else:
        caviar_var[alpha] = pd.Series(Q_as_full, index=data.index)
        print(f"    Best: AS (loss={loss_as:.6f})")

print("  CAViaR done.")

# ============================================================
# 4. METHOD 3: Quantile Regression
# ============================================================
print("\n[4] Quantile Regression...")

# Features: lagged |r| (1-5), VIX
qr_data = data.copy()
for lag in range(1, 6):
    qr_data[f'abs_ret_lag{lag}'] = qr_data['abs_ret'].shift(lag)
qr_data['vix_lag1'] = qr_data['VIX'].shift(1)
qr_data = qr_data.dropna()

# Align IS/OOS
qr_is = qr_data.loc[:is_end]
qr_oos = qr_data.loc[is_end:].iloc[1:] if is_end in qr_data.index else qr_data.loc[is_end:]

features = [f'abs_ret_lag{i}' for i in range(1, 6)] + ['vix_lag1']

qr_var = {}

for alpha in ALPHAS:
    print(f"  QR for alpha={alpha}...")
    # For return quantiles, use ret as dependent variable
    model = QuantReg(qr_is['ret'], qr_is[features])
    try:
        qr_fit = model.fit(q=alpha, max_iter=1000)
        # Predict on full data
        qr_pred = qr_fit.predict(qr_data[features])
        qr_var[alpha] = pd.Series(qr_pred, index=qr_data.index)
        print(f"    Coefficients: {dict(zip(features, qr_fit.params.round(6)))}")
    except Exception as e:
        print(f"    QR failed for alpha={alpha}: {e}")
        qr_var[alpha] = pd.Series(np.quantile(qr_data['ret'], alpha), index=qr_data.index)

# Also fit QR with constant (intercept)
qr_var_const = {}
import statsmodels.api as sm

for alpha in ALPHAS:
    X_is = sm.add_constant(qr_is[features])
    X_all = sm.add_constant(qr_data[features])
    model = QuantReg(qr_is['ret'], X_is)
    try:
        qr_fit = model.fit(q=alpha, max_iter=1000)
        qr_pred = qr_fit.predict(X_all)
        qr_var_const[alpha] = pd.Series(qr_pred, index=qr_data.index)
    except:
        qr_var_const[alpha] = qr_var.get(alpha, pd.Series(np.quantile(qr_data['ret'], alpha), index=qr_data.index))

# Use QR with constant as our QR model
qr_var = qr_var_const

print("  QR done.")

# ============================================================
# 5. EVALUATION (OOS only)
# ============================================================
print("\n[5] OOS Evaluation...")

oos_returns = oos_data['ret']
oos_start_idx = data.index.get_loc(oos_data.index[0])

# Align all predictions to OOS
def align_to_oos(pred_dict, oos_idx):
    """Align predictions to OOS index"""
    aligned = {}
    for alpha, pred in pred_dict.items():
        if isinstance(pred, pd.Series):
            common = pred.index.intersection(oos_idx)
            aligned[alpha] = pred.loc[common]
        else:
            aligned[alpha] = pred
    return aligned

garch_oos = align_to_oos(garch_var, oos_data.index)
caviar_oos = align_to_oos(caviar_var, oos_data.index)
qr_oos = align_to_oos(qr_var, oos_data.index)

# Common OOS index (intersection of all)
common_idx = oos_data.index
for alpha in ALPHAS:
    if alpha in garch_oos and isinstance(garch_oos[alpha], pd.Series):
        common_idx = common_idx.intersection(garch_oos[alpha].index)
    if alpha in caviar_oos and isinstance(caviar_oos[alpha], pd.Series):
        common_idx = common_idx.intersection(caviar_oos[alpha].index)
    if alpha in qr_oos and isinstance(qr_oos[alpha], pd.Series):
        common_idx = common_idx.intersection(qr_oos[alpha].index)

oos_ret_common = data.loc[common_idx, 'ret']
n_oos = len(common_idx)
print(f"  Common OOS observations: {n_oos}")

# Compute metrics
results = {}

def kupiec_test(violations, n, alpha):
    """Kupiec (1995) LR test for unconditional coverage"""
    v = np.sum(violations)
    if v == 0 or v == n:
        return np.nan, np.nan
    p_hat = v / n
    lr = 2 * (v * np.log(p_hat / alpha) + (n - v) * np.log((1 - p_hat) / (1 - alpha)))
    p_value = 1 - stats.chi2.cdf(lr, df=1)
    return lr, p_value

def christoffersen_test(violations):
    """Christoffersen (1998) independence test"""
    n = len(violations)
    # Count transitions
    n00, n01, n10, n11 = 0, 0, 0, 0
    for t in range(1, n):
        if violations[t - 1] == 0 and violations[t] == 0:
            n00 += 1
        elif violations[t - 1] == 0 and violations[t] == 1:
            n01 += 1
        elif violations[t - 1] == 1 and violations[t] == 0:
            n10 += 1
        else:
            n11 += 1

    if (n00 + n01) == 0 or (n10 + n11) == 0 or n01 == 0 or n11 == 0:
        return np.nan, np.nan

    pi01 = n01 / (n00 + n01)
    pi11 = n11 / (n10 + n11)
    pi = (n01 + n11) / n

    if pi01 <= 0 or pi01 >= 1 or pi11 <= 0 or pi11 >= 1 or pi <= 0 or pi >= 1:
        return np.nan, np.nan

    lr_ind = 2 * (n00 * np.log(1 - pi01) + n01 * np.log(pi01) +
                  n10 * np.log(1 - pi11) + n11 * np.log(pi11) -
                  (n00 + n10) * np.log(1 - pi) - (n01 + n11) * np.log(pi))
    p_value = 1 - stats.chi2.cdf(lr_ind, df=1)
    return lr_ind, p_value

def dm_test_pinball(loss1, loss2):
    """Diebold-Mariano test on pinball loss differences"""
    d = loss1 - loss2
    d_mean = np.mean(d)
    # HAC variance (Newey-West with lag = int(n^(1/3)))
    n = len(d)
    lag = int(n ** (1/3))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, lag + 1):
        gamma_k = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * (1 - k / (lag + 1)) * gamma_k
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_mean / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value

models = {
    'GARCH': garch_oos,
    'CAViaR': caviar_oos,
    'QR': qr_oos
}

for model_name, var_dict in models.items():
    results[model_name] = {}
    for alpha in ALPHAS:
        if alpha not in var_dict:
            continue

        pred = var_dict[alpha]
        if isinstance(pred, pd.Series):
            pred_aligned = pred.reindex(common_idx)
        else:
            pred_aligned = pd.Series(pred, index=common_idx)

        ret_vals = oos_ret_common.values
        pred_vals = pred_aligned.values

        # Remove NaN
        mask = ~(np.isnan(ret_vals) | np.isnan(pred_vals))
        ret_clean = ret_vals[mask]
        pred_clean = pred_vals[mask]
        n_clean = len(ret_clean)

        # Pinball loss
        errors = ret_clean - pred_clean
        pl = np.mean(np.where(errors >= 0, alpha * errors, (alpha - 1) * errors))

        # Coverage
        if alpha <= 0.5:
            violations = (ret_clean < pred_clean).astype(int)
        else:
            violations = (ret_clean > pred_clean).astype(int)

        coverage = np.mean(violations)

        # Kupiec
        target_alpha = alpha if alpha <= 0.5 else (1 - alpha)
        kup_lr, kup_p = kupiec_test(violations, n_clean, target_alpha)

        # Christoffersen
        chr_lr, chr_p = christoffersen_test(violations)

        results[model_name][str(alpha)] = {
            'pinball_loss': float(pl),
            'coverage': float(coverage),
            'target_coverage': float(target_alpha),
            'kupiec_lr': float(kup_lr) if not np.isnan(kup_lr) else None,
            'kupiec_pvalue': float(kup_p) if not np.isnan(kup_p) else None,
            'christoffersen_lr': float(chr_lr) if not np.isnan(chr_lr) else None,
            'christoffersen_pvalue': float(chr_p) if not np.isnan(chr_p) else None,
            'n_obs': int(n_clean),
            'n_violations': int(np.sum(violations))
        }

        print(f"  {model_name} alpha={alpha}: PL={pl:.6f}, "
              f"Coverage={coverage:.4f} (target={target_alpha:.2f}), "
              f"Kupiec p={kup_p:.4f}" if not np.isnan(kup_p) else f"  {model_name} alpha={alpha}: PL={pl:.6f}, Coverage={coverage:.4f}")

# DM tests between models
print("\n[5b] DM Tests (pairwise)...")
dm_results = {}

for alpha in ALPHAS:
    dm_results[str(alpha)] = {}

    # Compute pinball losses for each model
    losses = {}
    for model_name, var_dict in models.items():
        pred = var_dict.get(alpha)
        if pred is None:
            continue
        if isinstance(pred, pd.Series):
            pred_aligned = pred.reindex(common_idx).values
        else:
            pred_aligned = np.full(len(common_idx), pred)

        ret_vals = oos_ret_common.values
        mask = ~(np.isnan(ret_vals) | np.isnan(pred_aligned))
        errors = ret_vals[mask] - pred_aligned[mask]
        loss_t = np.where(errors >= 0, alpha * errors, (alpha - 1) * errors)
        losses[model_name] = loss_t

    # Pairwise DM tests
    model_names = list(losses.keys())
    for i in range(len(model_names)):
        for j in range(i + 1, len(model_names)):
            m1, m2 = model_names[i], model_names[j]
            min_len = min(len(losses[m1]), len(losses[m2]))
            t_stat, p_val = dm_test_pinball(losses[m1][:min_len], losses[m2][:min_len])
            key = f"{m1}_vs_{m2}"
            dm_results[str(alpha)][key] = {
                't_stat': float(t_stat) if not np.isnan(t_stat) else None,
                'p_value': float(p_val) if not np.isnan(p_val) else None,
                'significant_harvey': bool(abs(t_stat) > 3.0) if not np.isnan(t_stat) else False,
                'better_model': m1 if t_stat < 0 else m2  # negative means m1 has lower loss
            }
            print(f"  alpha={alpha}: {m1} vs {m2}: t={t_stat:.3f}, p={p_val:.4f}" +
                  (" ***" if not np.isnan(t_stat) and abs(t_stat) > 3.0 else ""))

# ============================================================
# 6. PLOTS
# ============================================================
print("\n[6] Generating plots...")

# --- Plot 1: Coverage Rates ---
fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Lower tail
lower_alphas = [0.01, 0.05, 0.10]
for ax_idx, alphas_subset in enumerate([lower_alphas, [0.90, 0.95, 0.99]]):
    ax = axes[ax_idx]
    x = np.arange(len(alphas_subset))
    width = 0.25

    for i, model_name in enumerate(['GARCH', 'CAViaR', 'QR']):
        coverages = []
        for a in alphas_subset:
            r = results.get(model_name, {}).get(str(a), {})
            coverages.append(r.get('coverage', np.nan))
        ax.bar(x + i * width, coverages, width, label=model_name, alpha=0.8)

    # Target lines
    for j, a in enumerate(alphas_subset):
        target = a if a <= 0.5 else (1 - a)
        ax.axhline(y=target, color='red', linestyle='--', alpha=0.3)
        ax.text(j, target + 0.002, f'{target:.2f}', color='red', fontsize=8, ha='center')

    ax.set_xlabel('Quantile Level')
    ax.set_ylabel('Actual Coverage Rate')
    ax.set_title('Lower Tail' if ax_idx == 0 else 'Upper Tail')
    ax.set_xticks(x + width)
    ax.set_xticklabels([str(a) for a in alphas_subset])
    ax.legend()
    ax.grid(axis='y', alpha=0.3)

plt.suptitle('K967: Coverage Rates by Model and Quantile Level (OOS)', fontsize=14, fontweight='bold')
plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k967_coverage_rates.png'), dpi=150, bbox_inches='tight')
plt.close()

# --- Plot 2: Pinball Loss ---
fig, ax = plt.subplots(figsize=(12, 6))

x = np.arange(len(ALPHAS))
width = 0.25

for i, model_name in enumerate(['GARCH', 'CAViaR', 'QR']):
    losses_plot = []
    for a in ALPHAS:
        r = results.get(model_name, {}).get(str(a), {})
        losses_plot.append(r.get('pinball_loss', np.nan))
    ax.bar(x + i * width, losses_plot, width, label=model_name, alpha=0.8)

ax.set_xlabel('Quantile Level (alpha)')
ax.set_ylabel('Pinball Loss (lower = better)')
ax.set_title('K967: Pinball Loss Comparison (OOS)', fontsize=14, fontweight='bold')
ax.set_xticks(x + width)
ax.set_xticklabels([str(a) for a in ALPHAS])
ax.legend()
ax.grid(axis='y', alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k967_pinball_loss.png'), dpi=150, bbox_inches='tight')
plt.close()

# --- Plot 3: VaR Time Series (5% lower tail) ---
fig, ax = plt.subplots(figsize=(16, 7))

plot_alpha = 0.05
oos_ret_plot = oos_ret_common * 100  # to percentage

ax.plot(common_idx, oos_ret_plot, color='gray', alpha=0.4, linewidth=0.5, label='SPY returns (%)')

# GARCH VaR
if plot_alpha in garch_oos and isinstance(garch_oos[plot_alpha], pd.Series):
    garch_plot = garch_oos[plot_alpha].reindex(common_idx) * 100
    ax.plot(common_idx, garch_plot, color='blue', linewidth=1.0, label='GARCH VaR 5%', alpha=0.8)

# CAViaR VaR
if plot_alpha in caviar_oos and isinstance(caviar_oos[plot_alpha], pd.Series):
    caviar_plot = caviar_oos[plot_alpha].reindex(common_idx) * 100
    ax.plot(common_idx, caviar_plot, color='red', linewidth=1.0, label='CAViaR VaR 5%', alpha=0.8)

# QR VaR
if plot_alpha in qr_oos and isinstance(qr_oos[plot_alpha], pd.Series):
    qr_plot = qr_oos[plot_alpha].reindex(common_idx) * 100
    ax.plot(common_idx, qr_plot, color='green', linewidth=1.0, label='QR VaR 5%', alpha=0.8)

# Mark violations
for model_name, color in [('GARCH', 'blue'), ('CAViaR', 'red'), ('QR', 'green')]:
    var_dict = models[model_name]
    if plot_alpha in var_dict and isinstance(var_dict[plot_alpha], pd.Series):
        pred = var_dict[plot_alpha].reindex(common_idx)
        violations_mask = oos_ret_common < pred
        if violations_mask.any():
            ax.scatter(common_idx[violations_mask],
                       oos_ret_plot[violations_mask],
                       color=color, marker='x', s=20, alpha=0.5, zorder=5)

ax.set_xlabel('Date')
ax.set_ylabel('Return (%)')
ax.set_title('K967: 5% VaR Forecasts vs Actual Returns (OOS 2021-2026)', fontsize=14, fontweight='bold')
ax.legend(loc='lower left')
ax.grid(alpha=0.3)

plt.tight_layout()
plt.savefig(os.path.join(OUT_DIR, 'k967_var_timeseries.png'), dpi=150, bbox_inches='tight')
plt.close()

print("  Plots saved.")

# ============================================================
# 7. SUMMARY & SAVE
# ============================================================
print("\n[7] Summary...")

# Best model per alpha (by pinball loss)
best_models = {}
for alpha in ALPHAS:
    best_loss = float('inf')
    best_name = None
    for model_name in ['GARCH', 'CAViaR', 'QR']:
        r = results.get(model_name, {}).get(str(alpha), {})
        pl = r.get('pinball_loss', float('inf'))
        if pl < best_loss:
            best_loss = pl
            best_name = model_name
    best_models[str(alpha)] = {'model': best_name, 'pinball_loss': best_loss}
    print(f"  alpha={alpha}: Best = {best_name} (PL={best_loss:.6f})")

# Summary table
print("\n  === Summary Table ===")
print(f"  {'Alpha':<8} {'Model':<8} {'PL':<12} {'Coverage':<12} {'Target':<10} {'Kupiec p':<10}")
print("  " + "-" * 60)
for alpha in ALPHAS:
    for model_name in ['GARCH', 'CAViaR', 'QR']:
        r = results.get(model_name, {}).get(str(alpha), {})
        pl = r.get('pinball_loss', np.nan)
        cov = r.get('coverage', np.nan)
        target = r.get('target_coverage', np.nan)
        kup_p = r.get('kupiec_pvalue', np.nan)
        best_marker = " *" if best_models.get(str(alpha), {}).get('model') == model_name else ""
        print(f"  {alpha:<8} {model_name:<8} {pl:<12.6f} {cov:<12.4f} {target:<10.2f} {kup_p if kup_p else 'N/A':<10}{best_marker}")

# VIX incremental value
print("\n  === VIX Incremental Value ===")
# Compare QR with and without VIX
for alpha in [0.01, 0.05, 0.10]:
    # Fit QR without VIX
    features_no_vix = [f'abs_ret_lag{i}' for i in range(1, 6)]
    X_is_nv = sm.add_constant(qr_is[features_no_vix])
    X_all_nv = sm.add_constant(qr_data[features_no_vix])
    model_nv = QuantReg(qr_is['ret'], X_is_nv)
    try:
        fit_nv = model_nv.fit(q=alpha, max_iter=1000)
        pred_nv = fit_nv.predict(X_all_nv)
        pred_nv = pd.Series(pred_nv, index=qr_data.index)
        pred_nv_oos = pred_nv.reindex(common_idx).values

        # QR with VIX
        pred_vix_oos = qr_var[alpha].reindex(common_idx).values

        ret_vals = oos_ret_common.values
        mask = ~(np.isnan(ret_vals) | np.isnan(pred_nv_oos) | np.isnan(pred_vix_oos))

        err_nv = ret_vals[mask] - pred_nv_oos[mask]
        loss_nv = np.mean(np.where(err_nv >= 0, alpha * err_nv, (alpha - 1) * err_nv))

        err_vix = ret_vals[mask] - pred_vix_oos[mask]
        loss_vix = np.mean(np.where(err_vix >= 0, alpha * err_vix, (alpha - 1) * err_vix))

        improvement = (loss_nv - loss_vix) / loss_nv * 100
        t_dm, p_dm = dm_test_pinball(
            np.where(err_nv >= 0, alpha * err_nv, (alpha - 1) * err_nv),
            np.where(err_vix >= 0, alpha * err_vix, (alpha - 1) * err_vix)
        )
        print(f"  alpha={alpha}: QR w/o VIX PL={loss_nv:.6f}, QR w/ VIX PL={loss_vix:.6f}, "
              f"Improvement={improvement:.2f}%, DM t={t_dm:.3f}")
    except Exception as e:
        print(f"  alpha={alpha}: VIX comparison failed: {e}")

# Save results
output = {
    'experiment_id': 'K967',
    'title': 'Probabilistic Volatility Quantile Forecasting: GARCH vs CAViaR vs QR',
    'date': datetime.now().strftime('%Y-%m-%d'),
    'data_source': 'yfinance (SPY, ^VIX)',
    'data_period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'is_period': f"{is_data.index[0].strftime('%Y-%m-%d')} to {is_data.index[-1].strftime('%Y-%m-%d')}",
    'oos_period': f"{oos_data.index[0].strftime('%Y-%m-%d')} to {oos_data.index[-1].strftime('%Y-%m-%d')}",
    'n_is': len(is_data),
    'n_oos': n_oos,
    'seed': 42,
    'methods': {
        'GARCH': 'GJR-GARCH(1,1) with Student-t, fixed parameters recursive forecast',
        'CAViaR': 'SAV and AS variants, best selected by IS pinball loss (Engle & Manganelli 2004)',
        'QR': 'Quantile Regression with lagged |r|(1-5) + VIX (statsmodels QuantReg)'
    },
    'garch_params': {
        'omega': float(omega),
        'alpha1': float(alpha1),
        'gamma1': float(gamma1),
        'beta1': float(beta1),
        'nu': float(nu),
        'persistence': float(persistence),
        'convergence': int(gjr_fit.convergence_flag)
    },
    'quantile_levels': ALPHAS,
    'results': results,
    'dm_tests': dm_results,
    'best_models': best_models,
    'references': [
        'Engle & Manganelli (2004) CAViaR: Conditional Autoregressive Value at Risk by Regression Quantiles. JBE 22, 367-381',
        'Xiao & Koenker (2009) Conditional Quantile Estimation for GARCH Models. JASA 104(488), 1696-1712',
        'Patton (2011) Volatility Forecast Comparison Using Imperfect Proxies. JoE 160, 246-256',
        'Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models. Journal of Derivatives',
        'Christoffersen (1998) Evaluating Interval Forecasts. International Economic Review 39, 841-862'
    ]
}

with open(os.path.join(OUT_DIR, 'k967_quantile_forecast_results.json'), 'w') as f:
    json.dump(output, f, indent=2, default=str)

print("\n  Results saved to k967_quantile_forecast_results.json")
print("\n" + "=" * 60)
print("K967 COMPLETE")
print("=" * 60)
