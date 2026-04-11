#!/usr/bin/env python3
"""
K1050: Earnings Season Volatility Patterns — Does A4f Capture Earnings Vol?
==========================================================================
[提出: Claude, 執行: Claude]

Motivation:
  K964 found earnings season vol patterns exist for SPY at individual-quarter level
  (Q1/Q3 more volatile, Q4 less) but cancel out in aggregate. K988 found A4f
  (VIX²-based multiplicative GARCH-X with free omega) beats GJR by DM t=+4.48
  (QLIKE on r²). This experiment tests whether A4f's advantage is concentrated
  in earnings seasons, which would indicate VIX captures earnings uncertainty.

  If A4f improvement is UNIFORM across seasons → VIX information is general,
  not earnings-specific. If concentrated in earnings season → VIX captures
  forward-looking earnings uncertainty that GARCH history misses.

Method:
  1. SPY daily returns + VIX, 2005-2026, from yfinance
  2. Define earnings season (K964 definition): Jan 10-Feb 15, Apr 10-May 15,
     Jul 10-Aug 15, Oct 10-Nov 15
  3. Run A4f and GJR with w=2000, refit/63d, OOS 2019-2026
  4. Split OOS into earnings/non-earnings
  5. Compare QLIKE and DM test on each subset

References:
  - Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.
  - Harvey et al. (2016). t > 3.0 threshold.
  - Engle, Ghysels & Sohn (2013). Stock Market Volatility and Macroeconomic
    Fundamentals. RES 95(3):776-797.
  - Patell & Wolfson (1984). Earnings announcements and intraday volatility.
  - Savor & Wilson (2016). Earnings announcements and systematic risk.

Data: SPY 2005-2026, ^VIX from yfinance. OOS: 2019-01-01 to latest.
Evaluation: QLIKE on r² (Patton 2011), DM test (Harvey |t| > 3.0).

Author: VolPred Research System
Date: 2026-04-11
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime, timezone
from scipy import stats, optimize

warnings.filterwarnings('ignore')
np.random.seed(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1050"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise, spearman_corr

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'K1050_results.json')
CHART_PATH = os.path.join(SCRIPT_DIR, 'K1050_seasonal_qlike.png')

# Configuration
DATA_START = '2005-01-01'
DATA_END = '2026-04-11'
OOS_START = '2019-01-01'
WINDOW = 2000
REFIT_EVERY = 63

print("=" * 70)
print(f"{EXPERIMENT_ID}: Earnings Season Vol — A4f Seasonal Decomposition")
print("  Does A4f's VIX component capture earnings-season volatility?")
print("=" * 70)

# ============================================================
# SECTION 1: DATA LOADING
# ============================================================
print("\n[1] Loading data...")
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close})
df = df.dropna()

oos_mask = np.array(df.index >= OOS_START)
n_total = len(df)
n_oos = oos_mask.sum()
print(f"  SPY: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")
print(f"  OOS: {OOS_START} onwards, n_oos={n_oos}")

ret = df['log_ret'].values
vix = df['VIX'].values
log_vix = np.log(np.maximum(vix, 1.0))
r2 = ret ** 2

# ============================================================
# SECTION 2: EARNINGS SEASON DEFINITION (from K964)
# ============================================================
print("\n[2] Defining earnings seasons...")


def is_earnings_season(date):
    """
    K964 earnings season windows:
    Q4 earnings: Jan 10 - Feb 15
    Q1 earnings: Apr 10 - May 15
    Q2 earnings: Jul 10 - Aug 15
    Q3 earnings: Oct 10 - Nov 15
    """
    m, d = date.month, date.day
    if m == 1 and d >= 10:
        return 'Q4_earnings'
    if m == 2 and d <= 15:
        return 'Q4_earnings'
    if m == 4 and d >= 10:
        return 'Q1_earnings'
    if m == 5 and d <= 15:
        return 'Q1_earnings'
    if m == 7 and d >= 10:
        return 'Q2_earnings'
    if m == 8 and d <= 15:
        return 'Q2_earnings'
    if m == 10 and d >= 10:
        return 'Q3_earnings'
    if m == 11 and d <= 15:
        return 'Q3_earnings'
    return 'non_earnings'


df['earnings_period'] = df.index.map(is_earnings_season)
df['is_earnings'] = (df['earnings_period'] != 'non_earnings').astype(int)

# Get OOS earnings masks
oos_dates = df.index[oos_mask]
oos_earnings_period = df['earnings_period'].values[oos_mask]
oos_is_earnings = df['is_earnings'].values[oos_mask]

n_oos_earnings = int(oos_is_earnings.sum())
n_oos_non_earnings = n_oos - n_oos_earnings
print(f"  OOS earnings season days: {n_oos_earnings} ({n_oos_earnings/n_oos*100:.1f}%)")
print(f"  OOS non-earnings days: {n_oos_non_earnings} ({n_oos_non_earnings/n_oos*100:.1f}%)")

# VIX descriptive during earnings vs non-earnings (OOS)
oos_vix = vix[oos_mask]
vix_earn = oos_vix[oos_is_earnings == 1]
vix_non = oos_vix[oos_is_earnings == 0]
print(f"  VIX during earnings: mean={np.mean(vix_earn):.2f}, median={np.median(vix_earn):.2f}")
print(f"  VIX non-earnings:    mean={np.mean(vix_non):.2f}, median={np.median(vix_non):.2f}")

# ============================================================
# SECTION 3: MODEL IMPLEMENTATIONS
# ============================================================
print("\n[3] Model implementations...")


# --- GJR-GARCH(1,1) ---
def gjr_loglik(params, returns):
    """Standard GJR-GARCH(1,1) log-likelihood."""
    omega, alpha, gamma, beta = params
    n = len(returns)
    h = np.empty(n)
    h[0] = np.var(returns[:min(250, n)])
    ll = 0.0
    for t in range(1, n):
        asym = gamma * returns[t-1]**2 if returns[t-1] < 0 else 0.0
        h[t] = omega + alpha * returns[t-1]**2 + asym + beta * h[t-1]
        if h[t] < 1e-10:
            h[t] = 1e-10
    for t in range(n):
        if h[t] > 0:
            ll += -0.5 * (np.log(2 * np.pi) + np.log(h[t]) + returns[t]**2 / h[t])
    return -ll


def fit_gjr(returns):
    """Fit GJR-GARCH(1,1)."""
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    starts = [
        [var0 * 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.02, 0.03, 0.08, 0.88],
        [var0 * 0.10, 0.08, 0.10, 0.80],
    ]
    bounds = [(1e-8, var0), (1e-4, 0.3), (1e-4, 0.3), (0.5, 0.999)]
    for s in starts:
        try:
            res = optimize.minimize(gjr_loglik, s, args=(returns,),
                                    method='L-BFGS-B', bounds=bounds)
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue
    return best_params


def gjr_forecast_1step(params, h_prev, r_prev):
    """One-step-ahead GJR forecast."""
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


# --- A4f: Multiplicative GARCH-X (VIX², free omega) ---
def compute_tau_a4f(theta0, theta1, vix_lag):
    """Compute tau = max(theta0 + theta1 * VIX_lag^2, eps)."""
    return np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)


def fit_a4f(returns, log_vix_vals, vix_vals):
    """
    Fit A4f: multiplicative GJR with tau = theta0 + theta1 * VIX_{t-1}^2,
    free omega, denom_mode = tau_t.

    Parameters: [theta0, theta1, omega_g, alpha, gamma, beta]
    """
    n = len(returns)

    # Lagged VIX (no lookahead)
    log_vix_lag = np.empty(n)
    log_vix_lag[0] = log_vix_vals[0]
    log_vix_lag[1:] = log_vix_vals[:-1]
    vix_lag = np.exp(log_vix_lag)

    # Initial theta from OLS on log(r^2) ~ 1 + VIX_lag^2
    r2_pos = np.maximum(returns**2, 1e-16)
    log_r2 = np.log(r2_pos)
    X = np.column_stack([np.ones(n), vix_lag**2])
    theta_init = np.linalg.lstsq(X, log_r2, rcond=None)[0]

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        tau = np.maximum(theta0 + theta1 * vix_lag**2, 1e-16)

        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10

        eg = omega_g / (1.0 - persist)
        g = np.empty(n)
        g[0] = eg

        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])  # denom_mode = tau_t
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10

        ll = 0.0
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)

        return -ll

    # Multiple starting points
    best_ll = np.inf
    best_params = None

    starts = [
        [1e-6, 1e-6, 0.05, 0.05, 0.05, 0.88],
        [1e-5, 5e-7, 0.03, 0.03, 0.08, 0.85],
        [5e-6, 1e-6, 0.08, 0.08, 0.10, 0.80],
    ]

    bounds = [
        (-0.01, 0.01),    # theta0
        (1e-8, 1e-4),     # theta1
        (1e-4, 0.5),      # omega_g
        (1e-4, 0.3),      # alpha
        (1e-4, 0.3),      # gamma
        (0.5, 0.999),     # beta
    ]

    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 1000})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
        except Exception:
            continue

    return best_params


# ============================================================
# SECTION 4: OOS FORECASTING
# ============================================================
print("\n[4] OOS forecasting (this will take a few minutes)...")

# Find OOS start index
oos_start_idx = np.where(oos_mask)[0][0]
oos_end_idx = np.where(oos_mask)[0][-1]
oos_indices = np.where(oos_mask)[0]
n_oos_actual = len(oos_indices)

print(f"  OOS observations: {n_oos_actual}")
print(f"  Refit every {REFIT_EVERY} days")

# Forecast arrays
fc_gjr = np.full(n_oos_actual, np.nan)
fc_a4f = np.full(n_oos_actual, np.nan)

# State variables
gjr_state = {'params': None, 'h': None}
a4f_state = {'params': None, 'g': None, 'tau_prev': None}

refit_count = 0

for t_idx, abs_idx in enumerate(oos_indices):
    if t_idx % 250 == 0:
        elapsed = time.time() - START_TIME
        print(f"  OOS step {t_idx}/{n_oos_actual} ({elapsed:.0f}s elapsed)")

    need_refit = (t_idx % REFIT_EVERY == 0) or (t_idx == 0)

    if need_refit:
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_log_vix = log_vix[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # Fit GJR
        gjr_params = fit_gjr(train_ret)
        if gjr_params is not None:
            gjr_state['params'] = gjr_params
            h = np.var(train_ret)
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_state['h'] = h

        # Fit A4f
        a4f_params = fit_a4f(train_ret, train_log_vix, train_vix)
        if a4f_params is not None:
            a4f_state['params'] = a4f_params
            theta0, theta1 = a4f_params[0], a4f_params[1]
            omega_g, alpha_p, gamma_p, beta_p = a4f_params[2], a4f_params[3], a4f_params[4], a4f_params[5]

            n_train = len(train_ret)
            log_vix_lag_tr = np.empty(n_train)
            log_vix_lag_tr[0] = train_log_vix[0]
            log_vix_lag_tr[1:] = train_log_vix[:-1]
            vix_lag_tr = np.exp(log_vix_lag_tr)

            tau_train = compute_tau_a4f(theta0, theta1, vix_lag_tr)

            persist = alpha_p + gamma_p / 2.0 + beta_p
            eg = omega_g / (1.0 - persist) if persist < 1.0 else 1.0
            g = eg
            for i in range(1, n_train):
                u_prev = train_ret[i-1] / np.sqrt(max(tau_train[i], 1e-16))
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)

            a4f_state['g'] = g
            # tau for the current forecast uses VIX from abs_idx-1
            a4f_state['tau_prev'] = tau_train[-1]  # will be updated below

    # --- GJR Forecast ---
    if gjr_state['params'] is not None:
        r_prev = ret[abs_idx - 1]
        h_prev = gjr_state['h']
        h_new = gjr_forecast_1step(gjr_state['params'], h_prev, r_prev)
        fc_gjr[t_idx] = h_new
        gjr_state['h'] = h_new

    # --- A4f Forecast ---
    if a4f_state['params'] is not None:
        theta0, theta1 = a4f_state['params'][0], a4f_state['params'][1]
        omega_g = a4f_state['params'][2]
        alpha_p, gamma_p, beta_p = a4f_state['params'][3], a4f_state['params'][4], a4f_state['params'][5]

        # tau uses VIX_{t-1} (lagged, no lookahead)
        vix_prev = vix[abs_idx - 1]
        tau_now = max(theta0 + theta1 * vix_prev**2, 1e-16)

        # Update g using previous return and current tau (denom_mode = tau_t)
        r_prev = ret[abs_idx - 1]
        g_prev = a4f_state['g']
        u_prev = r_prev / np.sqrt(tau_now)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * g_prev
        g_new = max(g_new, 1e-10)

        fc_a4f[t_idx] = tau_now * g_new
        a4f_state['g'] = g_new

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s, {refit_count} refits")

# ============================================================
# SECTION 5: SEASONAL DECOMPOSITION
# ============================================================
print("\n[5] Seasonal decomposition of forecast accuracy...")

oos_r2 = r2[oos_mask]

# Validate forecasts
valid = np.isfinite(fc_gjr) & np.isfinite(fc_a4f) & (fc_gjr > 0) & (fc_a4f > 0)
print(f"  Valid forecasts: {valid.sum()}/{n_oos_actual}")

# Overall QLIKE
qlike_gjr_all = qlike(oos_r2[valid], fc_gjr[valid])
qlike_a4f_all = qlike(oos_r2[valid], fc_a4f[valid])
dm_t_all, dm_p_all = dm_test(
    qlike_pointwise(oos_r2[valid], fc_a4f[valid]),
    qlike_pointwise(oos_r2[valid], fc_gjr[valid])
)
rho_gjr_all, _ = spearman_corr(oos_r2[valid], fc_gjr[valid])
rho_a4f_all, _ = spearman_corr(oos_r2[valid], fc_a4f[valid])

print(f"\n  --- Overall (n={valid.sum()}) ---")
print(f"  GJR QLIKE:  {qlike_gjr_all:.6f}")
print(f"  A4f QLIKE:  {qlike_a4f_all:.6f}")
print(f"  Improvement: {(qlike_gjr_all - qlike_a4f_all)/abs(qlike_gjr_all)*100:.2f}%")
print(f"  DM t-stat (A4f vs GJR, neg=A4f better): {dm_t_all:.3f}, p={dm_p_all:.4f}")
print(f"  Spearman rho: GJR={rho_gjr_all:.4f}, A4f={rho_a4f_all:.4f}")

# Earnings season subset
earn_mask_oos = (oos_is_earnings == 1) & valid
non_earn_mask_oos = (oos_is_earnings == 0) & valid

n_earn_valid = earn_mask_oos.sum()
n_non_valid = non_earn_mask_oos.sum()

print(f"\n  --- Earnings Season (n={n_earn_valid}) ---")
qlike_gjr_earn = qlike(oos_r2[earn_mask_oos], fc_gjr[earn_mask_oos])
qlike_a4f_earn = qlike(oos_r2[earn_mask_oos], fc_a4f[earn_mask_oos])
dm_t_earn, dm_p_earn = dm_test(
    qlike_pointwise(oos_r2[earn_mask_oos], fc_a4f[earn_mask_oos]),
    qlike_pointwise(oos_r2[earn_mask_oos], fc_gjr[earn_mask_oos])
)
rho_gjr_earn, _ = spearman_corr(oos_r2[earn_mask_oos], fc_gjr[earn_mask_oos])
rho_a4f_earn, _ = spearman_corr(oos_r2[earn_mask_oos], fc_a4f[earn_mask_oos])
improve_earn = (qlike_gjr_earn - qlike_a4f_earn) / abs(qlike_gjr_earn) * 100

print(f"  GJR QLIKE:  {qlike_gjr_earn:.6f}")
print(f"  A4f QLIKE:  {qlike_a4f_earn:.6f}")
print(f"  Improvement: {improve_earn:.2f}%")
print(f"  DM t-stat: {dm_t_earn:.3f}, p={dm_p_earn:.4f}")
print(f"  Spearman rho: GJR={rho_gjr_earn:.4f}, A4f={rho_a4f_earn:.4f}")

print(f"\n  --- Non-Earnings Season (n={n_non_valid}) ---")
qlike_gjr_non = qlike(oos_r2[non_earn_mask_oos], fc_gjr[non_earn_mask_oos])
qlike_a4f_non = qlike(oos_r2[non_earn_mask_oos], fc_a4f[non_earn_mask_oos])
dm_t_non, dm_p_non = dm_test(
    qlike_pointwise(oos_r2[non_earn_mask_oos], fc_a4f[non_earn_mask_oos]),
    qlike_pointwise(oos_r2[non_earn_mask_oos], fc_gjr[non_earn_mask_oos])
)
rho_gjr_non, _ = spearman_corr(oos_r2[non_earn_mask_oos], fc_gjr[non_earn_mask_oos])
rho_a4f_non, _ = spearman_corr(oos_r2[non_earn_mask_oos], fc_a4f[non_earn_mask_oos])
improve_non = (qlike_gjr_non - qlike_a4f_non) / abs(qlike_gjr_non) * 100

print(f"  GJR QLIKE:  {qlike_gjr_non:.6f}")
print(f"  A4f QLIKE:  {qlike_a4f_non:.6f}")
print(f"  Improvement: {improve_non:.2f}%")
print(f"  DM t-stat: {dm_t_non:.3f}, p={dm_p_non:.4f}")
print(f"  Spearman rho: GJR={rho_gjr_non:.4f}, A4f={rho_a4f_non:.4f}")

# ============================================================
# SECTION 6: PER-QUARTER BREAKDOWN
# ============================================================
print("\n[6] Per-quarter earnings breakdown...")

quarter_results = {}
quarters = ['Q4_earnings', 'Q1_earnings', 'Q2_earnings', 'Q3_earnings']
quarter_labels = {
    'Q4_earnings': 'Q4 Earnings (Jan-Feb)',
    'Q1_earnings': 'Q1 Earnings (Apr-May)',
    'Q2_earnings': 'Q2 Earnings (Jul-Aug)',
    'Q3_earnings': 'Q3 Earnings (Oct-Nov)',
}

for q in quarters:
    q_mask = (oos_earnings_period == q) & valid
    n_q = q_mask.sum()
    if n_q < 30:
        print(f"  {quarter_labels[q]}: n={n_q} (too few, skipping)")
        continue

    qlike_gjr_q = qlike(oos_r2[q_mask], fc_gjr[q_mask])
    qlike_a4f_q = qlike(oos_r2[q_mask], fc_a4f[q_mask])
    dm_t_q, dm_p_q = dm_test(
        qlike_pointwise(oos_r2[q_mask], fc_a4f[q_mask]),
        qlike_pointwise(oos_r2[q_mask], fc_gjr[q_mask])
    )
    improve_q = (qlike_gjr_q - qlike_a4f_q) / abs(qlike_gjr_q) * 100

    quarter_results[q] = {
        'n': int(n_q),
        'qlike_gjr': float(qlike_gjr_q),
        'qlike_a4f': float(qlike_a4f_q),
        'improvement_pct': float(improve_q),
        'dm_t': float(dm_t_q),
        'dm_p': float(dm_p_q),
    }

    print(f"  {quarter_labels[q]}: n={n_q}, improve={improve_q:.2f}%, DM t={dm_t_q:.3f}")

# ============================================================
# SECTION 7: CONCENTRATION TEST
# ============================================================
print("\n[7] Testing whether A4f advantage is concentrated in earnings season...")

# Ratio of improvement
if abs(improve_non) > 1e-10:
    concentration_ratio = improve_earn / improve_non
else:
    concentration_ratio = float('inf') if improve_earn > 0 else float('nan')

print(f"  Earnings improvement:     {improve_earn:.2f}%")
print(f"  Non-earnings improvement: {improve_non:.2f}%")
print(f"  Concentration ratio:      {concentration_ratio:.3f}")

# Bootstrap test for difference in improvement
print("\n  Bootstrap test: is the improvement difference significant?")
n_boot = 5000
np.random.seed(42)

loss_a4f_pw = qlike_pointwise(oos_r2[valid], fc_a4f[valid])
loss_gjr_pw = qlike_pointwise(oos_r2[valid], fc_gjr[valid])
diff_pw = loss_a4f_pw - loss_gjr_pw  # negative = A4f better

# Subset indices (relative to valid mask)
earn_idx = np.where(oos_is_earnings[valid] == 1)[0]
non_idx = np.where(oos_is_earnings[valid] == 0)[0]

boot_diff_earn = np.empty(n_boot)
boot_diff_non = np.empty(n_boot)

for b in range(n_boot):
    # Resample within each group
    e_idx = np.random.choice(earn_idx, size=len(earn_idx), replace=True)
    n_idx = np.random.choice(non_idx, size=len(non_idx), replace=True)
    boot_diff_earn[b] = np.mean(diff_pw[e_idx])
    boot_diff_non[b] = np.mean(diff_pw[n_idx])

# Test H0: mean(diff_earn) = mean(diff_non)
boot_contrast = boot_diff_earn - boot_diff_non
contrast_mean = np.mean(boot_contrast)
contrast_se = np.std(boot_contrast)
contrast_t = contrast_mean / contrast_se if contrast_se > 1e-15 else 0.0
contrast_p = 2 * (1 - stats.norm.cdf(abs(contrast_t)))

# Percentile CI for contrast
ci_low = np.percentile(boot_contrast, 2.5)
ci_high = np.percentile(boot_contrast, 97.5)

print(f"  Mean loss diff (earnings):     {np.mean(diff_pw[earn_idx]):.6f}")
print(f"  Mean loss diff (non-earnings): {np.mean(diff_pw[non_idx]):.6f}")
print(f"  Contrast (earn - non):         {contrast_mean:.6f}")
print(f"  Bootstrap t-stat:              {contrast_t:.3f}")
print(f"  Bootstrap p-value:             {contrast_p:.4f}")
print(f"  95% CI: [{ci_low:.6f}, {ci_high:.6f}]")

if abs(contrast_t) > 3.0:
    print("  ** Significant at Harvey (2016) threshold! A4f improvement differs by season.")
elif contrast_p < 0.05:
    print("  * Significant at 5% but not at Harvey threshold.")
else:
    print("  Not significant: A4f improvement is UNIFORM across seasons.")

# ============================================================
# SECTION 8: VIX LEVEL DURING EARNINGS
# ============================================================
print("\n[8] VIX level analysis during earnings season...")

# Full sample
full_vix = vix
full_is_earn = df['is_earnings'].values

vix_earn_full = full_vix[full_is_earn == 1]
vix_non_full = full_vix[full_is_earn == 0]

t_vix, p_vix = stats.ttest_ind(vix_earn_full, vix_non_full, equal_var=False)

print(f"  Full sample VIX (earnings):     mean={np.mean(vix_earn_full):.2f}, std={np.std(vix_earn_full):.2f}")
print(f"  Full sample VIX (non-earnings): mean={np.mean(vix_non_full):.2f}, std={np.std(vix_non_full):.2f}")
print(f"  Welch t-test: t={t_vix:.3f}, p={p_vix:.4f}")

# ============================================================
# SECTION 9: CHART
# ============================================================
print("\n[9] Generating chart...")
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

fig, axes = plt.subplots(1, 2, figsize=(14, 6))

# Left panel: QLIKE by season
seasons = ['Overall', 'Earnings', 'Non-Earnings']
qlike_gjr_vals = [qlike_gjr_all, qlike_gjr_earn, qlike_gjr_non]
qlike_a4f_vals = [qlike_a4f_all, qlike_a4f_earn, qlike_a4f_non]

x = np.arange(len(seasons))
width = 0.35

bars1 = axes[0].bar(x - width/2, qlike_gjr_vals, width, label='GJR-GARCH', color='#2196F3', alpha=0.85)
bars2 = axes[0].bar(x + width/2, qlike_a4f_vals, width, label='A4f (VIX²)', color='#FF5722', alpha=0.85)
axes[0].set_xlabel('Season Type')
axes[0].set_ylabel('QLIKE Loss (lower = better)')
axes[0].set_title('QLIKE: A4f vs GJR by Season')
axes[0].set_xticks(x)
axes[0].set_xticklabels(seasons)
axes[0].legend()

# Add sample sizes
for i, s in enumerate(seasons):
    n_s = [valid.sum(), n_earn_valid, n_non_valid][i]
    axes[0].text(i, max(qlike_gjr_vals[i], qlike_a4f_vals[i]) * 1.001,
                 f'n={n_s}', ha='center', va='bottom', fontsize=9)

# Right panel: Improvement % by quarter
q_names = []
q_improvements = []
q_dm_ts = []
for q in quarters:
    if q in quarter_results:
        q_names.append(quarter_labels[q].split(' (')[0])
        q_improvements.append(quarter_results[q]['improvement_pct'])
        q_dm_ts.append(quarter_results[q]['dm_t'])

# Add overall earnings and non-earnings
q_names = ['Non-Earn', 'Earnings'] + q_names
q_improvements = [improve_non, improve_earn] + q_improvements
q_dm_ts_ext = [float(dm_t_non), float(dm_t_earn)] + q_dm_ts

colors = ['#4CAF50' if imp > 0 else '#F44336' for imp in q_improvements]

bars = axes[1].barh(range(len(q_names)), q_improvements, color=colors, alpha=0.85)
axes[1].set_xlabel('A4f QLIKE Improvement over GJR (%)')
axes[1].set_title('A4f Improvement by Season/Quarter')
axes[1].set_yticks(range(len(q_names)))
axes[1].set_yticklabels(q_names)
axes[1].axvline(x=0, color='black', linewidth=0.5)

# Add DM t-stats as annotations
for i, (imp, t_val) in enumerate(zip(q_improvements, q_dm_ts_ext)):
    sig = '***' if abs(t_val) > 3.0 else '**' if abs(t_val) > 2.0 else '*' if abs(t_val) > 1.65 else ''
    axes[1].text(imp + 0.02 * max(abs(v) for v in q_improvements), i,
                 f't={t_val:.2f}{sig}', va='center', fontsize=8)

plt.tight_layout()
plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight')
plt.close()
print(f"  Chart saved to {CHART_PATH}")

# ============================================================
# SECTION 10: RESULTS JSON
# ============================================================
print("\n[10] Saving results...")

results = {
    'experiment_id': EXPERIMENT_ID,
    'title': 'Earnings Season Volatility Patterns — Does A4f Capture Earnings Vol?',
    'date': datetime.now(timezone.utc).isoformat(),
    'data_source': 'yfinance',
    'asset': 'SPY',
    'data_period': f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}",
    'n_total': int(n_total),
    'n_oos': int(n_oos_actual),
    'oos_start': OOS_START,
    'window': WINDOW,
    'refit_every': REFIT_EVERY,
    'n_refits': refit_count,
    'random_seed': 42,

    'earnings_definition': {
        'source': 'K964',
        'Q4_earnings': 'Jan 10 - Feb 15',
        'Q1_earnings': 'Apr 10 - May 15',
        'Q2_earnings': 'Jul 10 - Aug 15',
        'Q3_earnings': 'Oct 10 - Nov 15',
    },

    'oos_sample_split': {
        'earnings_days': int(n_oos_earnings),
        'non_earnings_days': int(n_oos_non_earnings),
        'earnings_pct': float(round(n_oos_earnings / n_oos * 100, 1)),
    },

    'vix_descriptives': {
        'earnings_mean': float(round(np.mean(vix_earn), 2)),
        'earnings_median': float(round(np.median(vix_earn), 2)),
        'non_earnings_mean': float(round(np.mean(vix_non), 2)),
        'non_earnings_median': float(round(np.median(vix_non), 2)),
        'full_sample_welch_t': float(round(t_vix, 3)),
        'full_sample_welch_p': float(round(p_vix, 4)),
    },

    'overall': {
        'n': int(valid.sum()),
        'qlike_gjr': float(round(qlike_gjr_all, 6)),
        'qlike_a4f': float(round(qlike_a4f_all, 6)),
        'improvement_pct': float(round((qlike_gjr_all - qlike_a4f_all) / abs(qlike_gjr_all) * 100, 2)),
        'dm_t': float(round(dm_t_all, 3)),
        'dm_p': float(round(dm_p_all, 4)),
        'spearman_gjr': float(round(rho_gjr_all, 4)),
        'spearman_a4f': float(round(rho_a4f_all, 4)),
    },

    'earnings_season': {
        'n': int(n_earn_valid),
        'qlike_gjr': float(round(qlike_gjr_earn, 6)),
        'qlike_a4f': float(round(qlike_a4f_earn, 6)),
        'improvement_pct': float(round(improve_earn, 2)),
        'dm_t': float(round(dm_t_earn, 3)),
        'dm_p': float(round(dm_p_earn, 4)),
        'spearman_gjr': float(round(rho_gjr_earn, 4)),
        'spearman_a4f': float(round(rho_a4f_earn, 4)),
    },

    'non_earnings_season': {
        'n': int(n_non_valid),
        'qlike_gjr': float(round(qlike_gjr_non, 6)),
        'qlike_a4f': float(round(qlike_a4f_non, 6)),
        'improvement_pct': float(round(improve_non, 2)),
        'dm_t': float(round(dm_t_non, 3)),
        'dm_p': float(round(dm_p_non, 4)),
        'spearman_gjr': float(round(rho_gjr_non, 4)),
        'spearman_a4f': float(round(rho_a4f_non, 4)),
    },

    'per_quarter': quarter_results,

    'concentration_test': {
        'concentration_ratio': float(round(concentration_ratio, 3)),
        'bootstrap_n': n_boot,
        'bootstrap_contrast_mean': float(round(contrast_mean, 6)),
        'bootstrap_contrast_se': float(round(contrast_se, 6)),
        'bootstrap_t': float(round(contrast_t, 3)),
        'bootstrap_p': float(round(contrast_p, 4)),
        'bootstrap_ci_95': [float(round(ci_low, 6)), float(round(ci_high, 6))],
        'significant_at_harvey': bool(abs(contrast_t) > 3.0),
        'significant_at_5pct': bool(contrast_p < 0.05),
    },

    'conclusion': '',

    'references': [
        'Patton (2011). Volatility forecast comparison. J Econometrics 160:246-256.',
        'Harvey et al. (2016). t > 3.0 threshold.',
        'Engle, Ghysels & Sohn (2013). Stock Market Volatility. RES 95(3):776-797.',
        'Patell & Wolfson (1984). Earnings announcements and intraday volatility.',
        'Savor & Wilson (2016). Earnings announcements and systematic risk.',
    ],

    'runtime_seconds': float(round(time.time() - START_TIME, 1)),
}

# Generate conclusion
if abs(contrast_t) > 3.0:
    if improve_earn > improve_non:
        conclusion = (
            f"A4f improvement is CONCENTRATED in earnings season "
            f"(earn: {improve_earn:.2f}% vs non-earn: {improve_non:.2f}%, "
            f"bootstrap t={contrast_t:.2f}>{3.0}). "
            f"VIX captures forward-looking earnings uncertainty that GARCH misses."
        )
    else:
        conclusion = (
            f"A4f improvement is CONCENTRATED in non-earnings season "
            f"(non-earn: {improve_non:.2f}% vs earn: {improve_earn:.2f}%, "
            f"bootstrap t={contrast_t:.2f}>{3.0}). "
            f"VIX information is more valuable outside earnings windows."
        )
elif contrast_p < 0.05:
    conclusion = (
        f"Weak evidence of seasonal concentration (p={contrast_p:.3f}) "
        f"but not significant at Harvey threshold. "
        f"Earn improve={improve_earn:.2f}%, non-earn={improve_non:.2f}%."
    )
else:
    conclusion = (
        f"A4f improvement is UNIFORM across seasons "
        f"(earn: {improve_earn:.2f}%, non-earn: {improve_non:.2f}%, "
        f"bootstrap p={contrast_p:.3f}). "
        f"VIX captures GENERAL volatility information, not earnings-specific uncertainty. "
        f"This supports VIX as a broad fear gauge rather than an earnings anticipation tool."
    )

results['conclusion'] = conclusion

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to {RESULTS_PATH}")
print(f"\n{'='*70}")
print(f"CONCLUSION: {conclusion}")
print(f"{'='*70}")
print(f"\nTotal runtime: {time.time() - START_TIME:.1f}s")
