#!/usr/bin/env python3
"""
K826: KAN-GARCH-MIDAS — Kolmogorov-Arnold Networks for Long-Run Volatility
============================================================================
[提出: Claude (research_program.md), 執行: Claude]

Background:
  - K526: GARCH-MIDAS OOS did not beat GJR (QLIKE GJR=1.517 < MIDAS-RV=1.523)
  - ML ceiling confirmed 6 times (K784, K787, K816v2, etc.)
  - KAN (Liu et al. 2024) uses learnable B-spline basis instead of fixed activations

Model Structure:
  σ²_t = τ_t · g_t   (multiplicative decomposition)
  Short-run: GJR-GARCH(1,1) via arch package (recursive OOS)
  Long-run:
    - KAN-MIDAS: τ = softplus(W2 @ tanh(B_spline(x) @ W1 + b1) + b2)
      where B_spline(x) is pre-computed basis matrix — KAN-inspired 1-hidden layer
    - Linear-MIDAS: τ = exp(a + b·log(RV22)) — K526 simplified
    - GJR: standard recursive (no τ decomposition)

  KAN implementation: pre-compute B-spline basis matrix, then optimize
  weights via L-BFGS-B. This is computationally efficient because basis
  evaluation happens once per refit, not per optimizer iteration.

Data: yfinance (SPY), OOS: 2023-01-01 ~ 2024-12-31
Window: expanding, refit every 63 days

Error log rules:
  - GARCH OOS: recursive h[t]=f(h[t-1],r²[t-1]) — properly implemented
  - DM test: use volpred.stats.model_evaluation.dm_test
  - Sharpe > 2x baseline = bug

References:
  Liu et al. (2024) KAN: Kolmogorov-Arnold Networks, arXiv:2404.19756
  Engle, Ghysels & Sohn (2013) RFS 26(11):2471-2509
  Patton (2011) JoE — QLIKE proxy-robust
  J. Applied Economics (2025) KAN-GARCH-MIDAS
"""

import json
import warnings
import time
import os
import sys
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import optimize, stats
from scipy.interpolate import BSpline

warnings.filterwarnings('ignore')

START_TIME = time.time()
EXPERIMENT_ID = "K826"
OOS_START = "2023-01-01"
OOS_END = "2024-12-31"
REFIT_EVERY = 63
RV_WINDOW = 22
KAN_WIDTH = 5       # hidden neurons
KAN_ORDER = 3       # B-spline order
KAN_N_KNOTS = 10    # internal knots
MAIN_REPO = '/Users/yhlai0911/Desktop/volpred-research'

print("=" * 70)
print(f"{EXPERIMENT_ID}: KAN-GARCH-MIDAS — KAN for Long-Run Volatility")
print("=" * 70)

# ============================================================
# 1: DATA
# ============================================================
print("\n[1] Loading data...")

import yfinance as yf

spy = yf.download("SPY", start="2006-01-01", end="2025-01-01", progress=False)
if isinstance(spy.columns, pd.MultiIndex):
    spy.columns = spy.columns.get_level_values(0)

spy['log_ret'] = np.log(spy['Close'] / spy['Close'].shift(1))
spy = spy.dropna(subset=['log_ret'])

data = spy[['Close', 'log_ret']].copy()
data['r2'] = data['log_ret'] ** 2
data['rv22'] = data['r2'].rolling(RV_WINDOW).sum()
data = data.dropna()

print(f"  SPY: {data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}, n={len(data)}")

# ============================================================
# 2: DIAGNOSTICS
# ============================================================
print("\n[2] Diagnostics...")

ret = data['log_ret'].values
desc = {
    'mean': float(np.mean(ret)), 'std': float(np.std(ret)),
    'skew': float(stats.skew(ret)), 'kurtosis': float(stats.kurtosis(ret)),
    'n': len(ret),
}
print(f"  Mean={desc['mean']:.6f}, Std={desc['std']:.4f}, Skew={desc['skew']:.3f}, Kurt={desc['kurtosis']:.3f}")

from statsmodels.tsa.stattools import adfuller
adf_stat, adf_pval = adfuller(ret, maxlag=20)[:2]
print(f"  ADF: stat={adf_stat:.4f}, p={adf_pval:.6f}")

from statsmodels.stats.diagnostic import het_arch
arch_lm = het_arch(ret, nlags=5)
print(f"  ARCH LM(5): stat={arch_lm[0]:.2f}, p={arch_lm[1]:.6f}")

# ============================================================
# 3: EFFICIENT KAN — PRE-COMPUTE BASIS, OPTIMIZE WEIGHTS ONLY
# ============================================================
print("\n[3] KAN implementation (pre-computed B-spline basis)...")

def make_bspline_basis_matrix(x, n_knots, order, x_min=None, x_max=None):
    """
    Build B-spline basis matrix B[i,j] = B_j(x_i).
    This is computed ONCE per refit, then weights are optimized.
    """
    if x_min is None:
        x_min = x.min() - 0.5
    if x_max is None:
        x_max = x.max() + 0.5

    n_basis = n_knots + order - 1
    internal = np.linspace(x_min, x_max, n_knots)
    dt = internal[1] - internal[0]
    left = internal[0] - dt * np.arange(order, 0, -1)
    right = internal[-1] + dt * np.arange(1, order + 1)
    knots = np.concatenate([left, internal, right])

    B = np.zeros((len(x), n_basis))
    for j in range(n_basis):
        c = np.zeros(n_basis)
        c[j] = 1.0
        B[:, j] = BSpline(knots, c, order, extrapolate=True)(x)

    return B, knots


def kan_forward_precomputed(B_in, params, width, n_basis_in):
    """
    KAN forward pass using pre-computed input basis matrix.

    Architecture: input(B-spline basis) → hidden(tanh) → output(linear)

    B_in: (n, n_basis) — pre-computed basis matrix
    params layout:
      W1: (n_basis, width) — input→hidden weights
      b1: (width,) — hidden bias
      W2: (width,) — hidden→output weights
      b2: scalar — output bias
    """
    n_b = n_basis_in
    w = width

    W1 = params[:n_b * w].reshape(n_b, w)
    b1 = params[n_b * w:n_b * w + w]
    W2 = params[n_b * w + w:n_b * w + w + w]
    b2 = params[n_b * w + 2 * w]

    # Layer 1: B-spline features → hidden (with tanh activation)
    hidden = np.tanh(B_in @ W1 + b1)  # (n, width)

    # Layer 2: hidden → scalar output
    output = hidden @ W2 + b2  # (n,)

    return output


def count_kan_params(n_basis, width):
    """Count total parameters."""
    return n_basis * width + width + width + 1


def kan_qlike_loss(params, B_in, r2, width, n_basis, lam=1e-3):
    """QLIKE loss with L2 regularization."""
    log_tau = kan_forward_precomputed(B_in, params, width, n_basis)
    tau = np.exp(np.clip(log_tau, -20, 5))
    qlike = np.mean(log_tau + r2 / tau)
    reg = lam * np.sum(params ** 2)
    return qlike + reg


N_BASIS = KAN_N_KNOTS + KAN_ORDER - 1  # 12
N_PARAMS = count_kan_params(N_BASIS, KAN_WIDTH)
print(f"  Architecture: 1 input → {N_BASIS} B-spline basis → {KAN_WIDTH} hidden (tanh) → 1 output")
print(f"  Parameters: {N_PARAMS}")

# ============================================================
# 4: LINEAR MIDAS
# ============================================================
def fit_linear_midas(r2, log_rv):
    """Fit linear MIDAS via QLIKE minimization."""
    mean_log_r2 = np.mean(np.log(r2 + 1e-12))

    def loss(p):
        lt = p[0] + p[1] * log_rv
        tau = np.exp(np.clip(lt, -20, 5))
        return np.mean(lt + r2 / tau)

    # Grid init
    best = (np.inf, mean_log_r2, 0.5)
    for b in np.linspace(0.0, 1.0, 11):
        for a_off in np.linspace(-1, 1, 11):
            l = loss([mean_log_r2 + a_off, b])
            if l < best[0]:
                best = (l, mean_log_r2 + a_off, b)

    res = optimize.minimize(loss, [best[1], best[2]], method='Nelder-Mead',
                           options={'maxiter': 300})
    return res.x


# ============================================================
# 5: OOS FORECASTING
# ============================================================
print("\n[5] Out-of-sample forecasting...")

from arch import arch_model

oos_mask = (data.index >= OOS_START) & (data.index <= OOS_END)
oos_dates = data.index[oos_mask]
n_oos = len(oos_dates)
print(f"  OOS: {oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}, n={n_oos}")

all_pos = {d: i for i, d in enumerate(data.index)}
pre_oos_n = all_pos[oos_dates[0]]

forecasts = {k: np.full(n_oos, np.nan) for k in ['GJR', 'MIDAS_Linear', 'KAN_MIDAS']}
proxy = data.loc[oos_dates, 'r2'].values

all_ret_pct = data['log_ret'].values * 100
all_ret_raw = data['log_ret'].values
all_rv22 = data['rv22'].values
all_r2 = data['r2'].values

refit_set = set(range(0, n_oos, REFIT_EVERY))

# --- GJR ---
print("  [5a] GJR-GARCH...")
gjr_mu = gjr_omega = gjr_alpha = gjr_gamma = gjr_beta = 0.0
gjr_h = None

for t_idx in range(n_oos):
    pos = pre_oos_n + t_idx

    if t_idx in refit_set:
        try:
            gjr = arch_model(all_ret_pct[:pos], vol='GARCH', p=1, o=1, q=1,
                           mean='Constant', dist='normal')
            res = gjr.fit(disp='off', show_warning=False)
            pars = res.params
            gjr_mu = float(pars['mu']) if 'mu' in pars.index else 0.0
            gjr_omega = float(pars['omega']) if 'omega' in pars.index else 0.0
            gjr_alpha = float(pars['alpha[1]']) if 'alpha[1]' in pars.index else 0.0
            gjr_gamma = float(pars['gamma[1]']) if 'gamma[1]' in pars.index else 0.0
            gjr_beta = float(pars['beta[1]']) if 'beta[1]' in pars.index else 0.0

            cv = res.conditional_volatility
            if hasattr(cv, 'iloc'):
                gjr_h = float(cv.iloc[-1]) ** 2
            elif hasattr(cv, '__len__') and len(cv) > 0:
                gjr_h = float(cv[-1]) ** 2
            else:
                gjr_h = gjr_omega / max(1 - gjr_alpha - gjr_beta - gjr_gamma/2, 0.01)

            if t_idx == 0:
                print(f"    GJR params: α={gjr_alpha:.4f}, γ={gjr_gamma:.4f}, β={gjr_beta:.4f}, "
                      f"persist={gjr_alpha + gjr_beta + gjr_gamma/2:.4f}")
        except Exception as e:
            print(f"    GJR refit error at t={t_idx}: {e}")
            # Fallback: use unconditional variance
            if gjr_h is None:
                unc_var = np.var(all_ret_pct[:pos])
                gjr_h = unc_var

    if gjr_h is None:
        continue

    eps = all_ret_pct[pos - 1] - gjr_mu
    ind = 1.0 if eps < 0 else 0.0
    gjr_h = gjr_omega + gjr_alpha * eps**2 + gjr_gamma * ind * eps**2 + gjr_beta * gjr_h
    forecasts['GJR'][t_idx] = gjr_h / 1e4

print(f"    GJR valid: {np.sum(np.isfinite(forecasts['GJR']))}/{n_oos}")

# --- KAN + Linear MIDAS ---
print("  [5b] KAN-MIDAS + Linear-MIDAS...")

kan_params = None
kan_knots = None
kan_log_rv_mean = kan_log_rv_std = 0.0
lin_params = None

for t_idx in range(n_oos):
    pos = pre_oos_n + t_idx

    if t_idx in refit_set:
        t0 = time.time()

        train_r2 = all_r2[:pos]
        train_rv22 = all_rv22[:pos]
        log_rv_train = np.log(train_rv22 + 1e-12)

        # Standardize
        kan_log_rv_mean = np.mean(log_rv_train)
        kan_log_rv_std = np.std(log_rv_train) + 1e-8
        X_std = (log_rv_train - kan_log_rv_mean) / kan_log_rv_std

        # Pre-compute B-spline basis matrix (ONCE per refit)
        B_train, kan_knots = make_bspline_basis_matrix(
            X_std, KAN_N_KNOTS, KAN_ORDER, x_min=-3.5, x_max=3.5)

        # Initialize KAN parameters
        rng = np.random.default_rng(42 + t_idx)
        init_p = rng.normal(0, 0.05, N_PARAMS)
        init_p[-1] = np.mean(np.log(train_r2 + 1e-12))

        # Optimize KAN (basis is pre-computed → fast)
        try:
            res = optimize.minimize(
                kan_qlike_loss, init_p,
                args=(B_train, train_r2, KAN_WIDTH, N_BASIS, 1e-3),
                method='L-BFGS-B',
                options={'maxiter': 150, 'ftol': 1e-8}
            )
            kan_params = res.x
            kan_conv = res.success
        except Exception as e:
            kan_params = init_p
            kan_conv = False

        # Linear MIDAS
        try:
            lin_params = fit_linear_midas(train_r2, log_rv_train)
        except:
            pass

        dt = time.time() - t0
        if t_idx % (REFIT_EVERY * 2) == 0 or t_idx == 0:
            print(f"    Refit t={t_idx}/{n_oos}: KAN conv={kan_conv}, time={dt:.2f}s")

    # Forecast using rv22 from t-1 (no lookahead)
    rv22_prev = all_rv22[pos - 1]
    log_rv_prev = np.log(rv22_prev + 1e-12)
    x_std_prev = (log_rv_prev - kan_log_rv_mean) / kan_log_rv_std

    # KAN forecast
    if kan_params is not None and kan_knots is not None:
        B_pred, _ = make_bspline_basis_matrix(
            np.array([x_std_prev]), KAN_N_KNOTS, KAN_ORDER,
            x_min=-3.5, x_max=3.5)
        log_tau = kan_forward_precomputed(B_pred, kan_params, KAN_WIDTH, N_BASIS)[0]
        forecasts['KAN_MIDAS'][t_idx] = np.exp(np.clip(log_tau, -20, 5))

    # Linear MIDAS forecast
    if lin_params is not None:
        lt = lin_params[0] + lin_params[1] * log_rv_prev
        forecasts['MIDAS_Linear'][t_idx] = np.exp(np.clip(lt, -20, 5))

elapsed_fcast = time.time() - START_TIME
print(f"\n  Forecasting done in {elapsed_fcast:.1f}s")
for k, v in forecasts.items():
    print(f"    {k}: {np.sum(np.isfinite(v))}/{n_oos} valid")

# ============================================================
# 6: EVALUATION
# ============================================================
print("\n[6] Evaluation...")

sys.path.insert(0, os.path.join(MAIN_REPO, 'src'))
from volpred.stats.model_evaluation import dm_test

results = {}
for name, fcast in forecasts.items():
    v = np.isfinite(fcast) & np.isfinite(proxy) & (fcast > 0)
    n_v = np.sum(v)
    if n_v < 10:
        results[name] = {'n_valid': int(n_v), 'error': 'insufficient'}
        continue

    p, f = proxy[v], fcast[v]
    ql = float(np.mean(np.log(f) + p / f))
    mse = float(np.mean((p - f) ** 2))
    mae = float(np.mean(np.abs(p - f)))
    _, _, r_val, _, _ = stats.linregress(f, p)
    mz_r2 = float(r_val ** 2)
    rho, rho_p = stats.spearmanr(p, f)

    results[name] = {
        'n_valid': int(n_v), 'qlike': ql, 'mse': mse, 'mae': mae,
        'r2_mz': mz_r2, 'spearman_rho': float(rho), 'spearman_p': float(rho_p),
        'mean_forecast': float(np.mean(f)), 'mean_proxy': float(np.mean(p)),
        'forecast_bias': float((np.mean(f) - np.mean(p)) / np.mean(p)),
    }
    print(f"  {name:<15}: QLIKE={ql:.4f}, MSE={mse:.2e}, MAE={mae:.2e}, "
          f"MZ-R²={mz_r2:.4f}, ρ={rho:.4f}")

# ============================================================
# 7: DM TESTS
# ============================================================
print("\n[7] DM tests (Harvey t>3.0)...")

dm_results = {}
mnames = list(forecasts.keys())
for i in range(len(mnames)):
    for j in range(i+1, len(mnames)):
        m1, m2 = mnames[i], mnames[j]
        f1, f2 = forecasts[m1], forecasts[m2]
        v = np.isfinite(f1) & np.isfinite(f2) & np.isfinite(proxy) & (f1 > 0) & (f2 > 0)
        if np.sum(v) < 20:
            continue

        ql1 = np.log(f1[v]) + proxy[v] / f1[v]
        ql2 = np.log(f2[v]) + proxy[v] / f2[v]
        t_s, p_v = dm_test(ql1, ql2)
        sig = "***" if abs(t_s) > 3.0 else ("**" if abs(t_s) > 2.0 else ("*" if abs(t_s) > 1.64 else ""))
        better = m1 if t_s < 0 else m2

        dm_results[f"{m1}_vs_{m2}"] = {
            't_stat': float(t_s), 'p_value': float(p_v),
            'significant_harvey': abs(t_s) > 3.0, 'better_model': better,
        }
        print(f"  {m1} vs {m2}: t={t_s:.3f}, p={p_v:.4f} {sig} → {better}")

# ============================================================
# 8: REGIME ANALYSIS
# ============================================================
print("\n[8] Regime analysis...")

rv22_oos = data.loc[oos_dates, 'rv22'].values
rv_p75 = np.percentile(rv22_oos, 75)
rv_p25 = np.percentile(rv22_oos, 25)

regime_results = {}
for rname, rmask in [
    ('high_vol', rv22_oos > rv_p75),
    ('low_vol', rv22_oos < rv_p25),
    ('mid_vol', (rv22_oos >= rv_p25) & (rv22_oos <= rv_p75)),
]:
    regime_results[rname] = {'n': int(np.sum(rmask))}
    if np.sum(rmask) < 5:
        continue
    p_r = proxy[rmask]
    print(f"  {rname} (n={np.sum(rmask)}):")
    for mname, fcast in forecasts.items():
        f_r = fcast[rmask]
        vv = np.isfinite(f_r) & np.isfinite(p_r) & (f_r > 0)
        if np.sum(vv) < 5:
            continue
        ql = float(np.mean(np.log(f_r[vv]) + p_r[vv] / f_r[vv]))
        regime_results[rname][mname] = {'qlike': ql, 'n': int(np.sum(vv))}
        print(f"    {mname}: QLIKE={ql:.4f}")

# ============================================================
# 9: KAN INTERPRETABILITY
# ============================================================
print("\n[9] KAN interpretability...")

interpretability = {}
if kan_params is not None:
    x_range = np.linspace(-3, 3, 200)
    B_range, _ = make_bspline_basis_matrix(x_range, KAN_N_KNOTS, KAN_ORDER, -3.5, 3.5)
    y_kan = kan_forward_precomputed(B_range, kan_params, KAN_WIDTH, N_BASIS)

    from numpy.polynomial import polynomial as P
    coeffs = P.polyfit(x_range, y_kan, 1)
    y_lin = P.polyval(x_range, coeffs)

    nl_mse = np.mean((y_kan - y_lin) ** 2)
    total_var = np.var(y_kan)
    nl_ratio = nl_mse / (total_var + 1e-15)

    interpretability = {
        'output_range': [float(y_kan.min()), float(y_kan.max())],
        'nonlinearity_ratio': float(nl_ratio),
        'significant_nonlinearity': nl_ratio > 0.05,
        'output_std': float(np.std(y_kan)),
    }
    print(f"  Output range: [{y_kan.min():.4f}, {y_kan.max():.4f}]")
    print(f"  Nonlinearity ratio: {nl_ratio:.4f} ({'significant' if nl_ratio > 0.05 else 'minimal'})")

# ============================================================
# 10: SUMMARY
# ============================================================
elapsed = time.time() - START_TIME
print(f"\n[10] Summary ({elapsed:.1f}s)")

qlike_scores = {m: r.get('qlike', np.inf) for m, r in results.items() if 'qlike' in r}
winner = min(qlike_scores, key=qlike_scores.get) if qlike_scores else "N/A"

print(f"\n  {'Model':<15} {'QLIKE':>10} {'MSE':>12} {'MAE':>12} {'MZ-R²':>8} {'ρ':>8}")
print(f"  {'-'*15} {'-'*10} {'-'*12} {'-'*12} {'-'*8} {'-'*8}")
for m, r in results.items():
    if 'qlike' in r:
        print(f"  {m:<15} {r['qlike']:>10.4f} {r['mse']:>12.2e} {r['mae']:>12.2e} "
              f"{r['r2_mz']:>8.4f} {r['spearman_rho']:>8.4f}")

print(f"\n  Winner (QLIKE): {winner}")

conclusion_parts = []
if 'KAN_MIDAS' in qlike_scores and 'GJR' in qlike_scores:
    impr = (qlike_scores['GJR'] - qlike_scores['KAN_MIDAS']) / abs(qlike_scores['GJR']) * 100
    dm_key = 'GJR_vs_KAN_MIDAS'
    if qlike_scores['KAN_MIDAS'] < qlike_scores['GJR']:
        if dm_key in dm_results and dm_results[dm_key].get('significant_harvey'):
            conclusion_parts.append(f"KAN-MIDAS beats GJR ({impr:+.2f}% QLIKE, Harvey t>3.0)")
        else:
            conclusion_parts.append(f"KAN-MIDAS lower QLIKE ({impr:+.2f}%) but NOT significant")
    else:
        conclusion_parts.append(f"GJR wins — ML ceiling confirmed (7th time)")

if 'KAN_MIDAS' in qlike_scores and 'MIDAS_Linear' in qlike_scores:
    impr2 = (qlike_scores['MIDAS_Linear'] - qlike_scores['KAN_MIDAS']) / abs(qlike_scores['MIDAS_Linear']) * 100
    if impr2 > 0:
        conclusion_parts.append(f"KAN adds {impr2:.2f}% over linear MIDAS")
    else:
        conclusion_parts.append(f"KAN does NOT beat linear MIDAS ({impr2:+.2f}%)")

if interpretability.get('significant_nonlinearity'):
    conclusion_parts.append("significant KAN nonlinearity detected")
else:
    conclusion_parts.append("KAN learned mostly linear mapping")

conclusion = "; ".join(conclusion_parts)
print(f"\n  Conclusion: {conclusion}")

# Save
output = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'K826: KAN-GARCH-MIDAS — KAN for Long-Run Volatility',
    'proposer': 'Claude (research_program.md)',
    'executor': 'Claude',
    'date': datetime.now(timezone.utc).strftime('%Y-%m-%d'),
    'asset': 'SPY',
    'data_source': 'yfinance (SPY daily)',
    'data_period': f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}",
    'total_observations': len(data),
    'oos_period': f"{oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')}",
    'oos_observations': n_oos,
    'refit_frequency': REFIT_EVERY,
    'proxy': 'squared returns (r²_t)',
    'models': {
        'GJR': 'GJR-GARCH(1,1) — recursive OOS, refit/63d',
        'MIDAS_Linear': 'Linear: τ = exp(a + b·log(RV22))',
        'KAN_MIDAS': f'KAN: B-spline({KAN_ORDER})→{KAN_WIDTH}→1, {N_PARAMS} params',
    },
    'kan_config': {
        'n_input': 1, 'n_hidden': KAN_WIDTH, 'bspline_order': KAN_ORDER,
        'n_knots': KAN_N_KNOTS, 'n_basis': N_BASIS, 'n_params': N_PARAMS,
        'optimizer': 'L-BFGS-B', 'max_iter': 150, 'reg_lambda': 1e-3,
    },
    'results': results,
    'dm_tests': dm_results,
    'regime_analysis': regime_results,
    'kan_interpretability': interpretability,
    'diagnostics': desc,
    'conclusion': conclusion,
    'winner_qlike': winner,
    'elapsed_seconds': elapsed,
    'references': [
        'Liu et al. (2024) KAN: Kolmogorov-Arnold Networks, arXiv:2404.19756',
        'Engle, Ghysels & Sohn (2013) Stock Market Volatility, RFS 26(11)',
        'Patton (2011) Volatility forecast comparison, JoE',
    ],
    'limitations': [
        'KAN 1D input only (log RV22)',
        'Sequential estimation (not joint MLE)',
        'OOS 2 years (2023-2024)',
        'MIDAS models use τ only (no short-run g_t component)',
        'Simplified B-spline KAN (no grid refinement)',
    ],
    'timestamp': datetime.now(timezone.utc).isoformat(),
}

rpath = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    f'{EXPERIMENT_ID.lower()}_kan_garch_midas_results.json')
with open(rpath, 'w') as f:
    json.dump(output, f, indent=2, default=str)

print(f"\n  Saved: {rpath}")
print(f"  Total: {elapsed:.1f}s")
print("=" * 70)
