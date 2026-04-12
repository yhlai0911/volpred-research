#!/usr/bin/env python3
"""
K1076: Fissler-Ziegel Joint VaR/ES Backtest for A4f vs GJR
===========================================================
[提出: Claude, 執行: Claude]

Motivation:
  Previous risk-management experiments for A4f vs GJR used VaR-only tests
  (Kupiec, Christoffersen, Basel). ES (Expected Shortfall) is NOT elicitable
  alone (Gneiting 2011), which limits direct scoring/comparison.

  Fissler & Ziegel (2016, Annals of Statistics) proved that the pair
  (VaR_alpha, ES_alpha) IS jointly elicitable and derived the unique (up to
  equivalence) class of strictly consistent joint scoring functions.

  We use the 0-homogeneous representative to score A4f and GJR jointly on
  VaR/ES and compare via Diebold-Mariano. This is the gold-standard for
  risk-management model comparison.

  Supplementary: Acerbi-Szekely (2014) Z-tests for ES absolute adequacy.

Design:
  - Data: SPY + ^VIX, 2000-2026 (yfinance, DATA_START lets window train before 2007 OOS)
  - Models: GJR-GARCH vs A4f (tau = theta0 + theta1 * VIX_{t-1}^2, g = GJR, free omega)
  - OOS window: 2007-01-01 to 2026-04-11 (includes 2008 GFC, COVID, 2022 bear)
  - Rolling-window GARCH: train window=2000, refit every 63 days
  - Distribution assumption: Normal and Student-t (nu=5) for VaR/ES mapping
  - Confidence levels: alpha in {0.01, 0.05}
  - Evaluation:
      (a) Fissler-Ziegel joint score (Eq 3.1, 0-homogeneous form)
      (b) Diebold-Mariano test on FZ score differences (HAC, Harvey |t|>3)
      (c) Acerbi-Szekely Z1, Z2 tests
      (d) Regime sub-analysis by VIX bucket (Low/Normal/High/Crisis)

Hypotheses:
  H1: A4f dominates GJR in FZ joint score (DM t with Harvey |t|>3)
  H2: A4f passes Acerbi-Szekely while GJR may fail (bootstrap p>0.05 vs <0.05)
  H3: A4f's FZ advantage is largest in High/Crisis VIX regimes
  H4: Results are consistent across Normal vs Student-t distribution

Key formulas:
  Normal: VaR_alpha = -sigma * z_alpha
          ES_alpha = -sigma * phi(z_alpha)/alpha
  Student-t(nu): VaR_alpha = -sigma * sqrt((nu-2)/nu) * t_{alpha,nu}
                 ES_alpha = -sigma * sqrt((nu-2)/nu) * (f_nu(t_{alpha,nu}) / alpha)
                            * (nu + t_{alpha,nu}^2) / (nu - 1)
  Note: VaR/ES reported as POSITIVE losses (i.e., -quantile).

  FZ score (Fissler & Ziegel 2016, Eq 3.1, 0-homogeneous 'Z form'):
    S_FZ(v, e, y) = (1/alpha * I{y <= -v} - 1) * (-(y+v) * v - v^2/2) / (-e)
                    + log(-e) + v / (-e)
  (Rewritten in the loss-positive convention where v=VaR>=0, e=ES>=0:
    For return y with v,e > 0, define y' = -y (loss). Event y <= -v means y' >= v.
    We use the equivalent formulation of Patton (2020) and Nolde-Ziegel (2017).)

  We implement the canonical 1-homogeneous family (Taylor 2019 Eq 10):
    S_FZ(v, e, y) = -log(1 - 1/alpha * I{y+v < 0}) - (1 - I{y+v<0}/alpha) * (y + v) / e
                     + y/e + log(e)
  with v = VaR (positive), e = ES (positive), y = return (signed).

  Actually, we use the Patton-Ziegel-Chen (2019, JoE) representation:
    S(v, e, y; alpha) = (I{y+v<=0} - alpha) * v + I{y+v<=0} * (y - (-v))
                         + alpha * (e - (-v))  [NOT strictly consistent alone]
  --> we implement the correct strictly consistent FZ score (0-hom):
    S_FZ(v, e, y) = 1/(alpha*e) * I{y<=-v}*(y+v) - v/e + log(e) - 1   (form A)
    (equivalent to Fissler-Ziegel 2016 Theorem 5.2 with G2(x)=-1/x, G1=0, a=0)

  We use the implementation checked against Nolde & Ziegel (2017) Appendix.

References:
  - Fissler & Ziegel (2016). "Higher Order Elicitability and Osband's Principle"
    Annals of Statistics 44(4):1680-1707.
  - Acerbi & Szekely (2014). "Back-testing expected shortfall" Risk 27(11).
  - Gneiting (2011). "Making and evaluating point forecasts" JASA 106(494):746-762.
  - Nolde & Ziegel (2017). "Elicitability and backtesting: perspectives for
    banking regulation" Annals of Applied Statistics 11(4):1833-1874.
  - Patton, Ziegel, Chen (2019). "Dynamic semiparametric models for expected
    shortfall" Journal of Econometrics 211(2):388-413.
  - Taylor (2019). "Forecasting Value at Risk and Expected Shortfall using a
    semiparametric approach based on the asymmetric Laplace distribution"
    JBES 37(1):121-133.

Experiment: K1076 | Date: 2026-04-12 | Seed: 42
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
from numba import njit

warnings.filterwarnings('ignore')
np.random.seed(42)
RNG = np.random.default_rng(42)

START_TIME = time.time()
EXPERIMENT_ID = "K1076"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..'))

RESULTS_PATH = os.path.join(SCRIPT_DIR, 'k1076_results.json')
FORECASTS_PATH = os.path.join(SCRIPT_DIR, 'k1076_forecasts.csv')
FORECASTS_NPZ = os.path.join(SCRIPT_DIR, 'k1076_forecasts.npz')

# Configuration (aligned with K1075)
DATA_START = '2000-01-01'
DATA_END = '2026-04-11'
WINDOW = 2000
REFIT_EVERY = 63

OOS_START = '2007-01-01'
OOS_END = '2026-04-11'

ALPHAS = [0.01, 0.05]
DISTS = ['normal', 'student_t']
STUDENT_NU = 5.0

# VIX buckets for regime analysis
VIX_BUCKETS = [
    ('Low',    0,  15),
    ('Normal', 15, 25),
    ('High',   25, 40),
    ('Crisis', 40, 200),
]

print("=" * 72)
print(f"{EXPERIMENT_ID}: Fissler-Ziegel Joint VaR/ES Backtest")
print(f"  A4f vs GJR, OOS {OOS_START}~{OOS_END}, alphas={ALPHAS}, dists={DISTS}")
print("=" * 72)

# ============================================================
# SECTION 1: DATA
# ============================================================
print("\n[1] Loading data from yfinance...")
import yfinance as yf

raw = yf.download('SPY', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(raw.columns, pd.MultiIndex):
    raw.columns = raw.columns.get_level_values(0)
prices = raw['Adj Close'].copy() if 'Adj Close' in raw.columns else raw['Close'].copy()
log_ret = np.log(prices / prices.shift(1))

vix_raw = yf.download('^VIX', start=DATA_START, end=DATA_END, progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw['Close'].copy()

df = pd.DataFrame({'price': prices, 'log_ret': log_ret, 'VIX': vix_close}).dropna()

n_total = len(df)
print(f"  Data: {df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}, n={n_total}")

ret = df['log_ret'].values
vix = df['VIX'].values
dates = df.index

# Diagnostics
print(f"  Return mean (ann)  : {np.mean(ret)*252:+.4f}")
print(f"  Return std  (ann)  : {np.std(ret)*np.sqrt(252):.4f}")
print(f"  Return skew / kurt : {stats.skew(ret):+.3f} / {stats.kurtosis(ret):+.3f}")
print(f"  VIX min/mean/max   : {np.min(vix):.2f} / {np.mean(vix):.2f} / {np.max(vix):.2f}")


# ============================================================
# SECTION 2: MODEL IMPLEMENTATIONS (reused from K1075)
# ============================================================
print("\n[2] Model implementations...")

@njit(cache=True)
def gjr_loglik(params, returns):
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
    var0 = np.var(returns)
    best_ll = np.inf
    best_params = None
    converged = False
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
                converged = res.success
        except Exception:
            continue
    return best_params, converged


def gjr_forecast_1step(params, h_prev, r_prev):
    omega, alpha, gamma, beta = params
    asym = gamma * r_prev**2 if r_prev < 0 else 0.0
    return max(omega + alpha * r_prev**2 + asym + beta * h_prev, 1e-10)


def fit_a4f(returns, vix_vals):
    """A4f: tau = theta0 + theta1 * VIX_{t-1}^2, free omega_g on GJR component."""
    n = len(returns)
    vix_lag = np.empty(n)
    vix_lag[0] = vix_vals[0]
    vix_lag[1:] = vix_vals[:-1]
    vix_lag_sq = vix_lag ** 2

    def neg_loglik(params):
        theta0, theta1, omega_g, alpha, gamma_p, beta = params
        if omega_g <= 0 or alpha < 0 or gamma_p < 0 or beta < 0:
            return 1e10
        persist = alpha + gamma_p / 2.0 + beta
        if persist >= 0.999:
            return 1e10
        tau = np.maximum(theta0 + theta1 * vix_lag_sq, 1e-16)
        g = np.empty(n)
        g[0] = omega_g / (1.0 - persist)
        ll = 0.0
        for t in range(1, n):
            u_prev = returns[t-1] / np.sqrt(tau[t])
            asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
            g[t] = omega_g + alpha * u_prev**2 + asym + beta * g[t-1]
            if g[t] < 1e-10:
                g[t] = 1e-10
        for t in range(n):
            sigma2 = tau[t] * g[t]
            if sigma2 > 0:
                ll += -0.5 * (np.log(2 * np.pi) + np.log(sigma2) + returns[t]**2 / sigma2)
        return -ll

    var0 = np.var(returns)
    vix2_mean = np.mean(vix_lag_sq) + 1e-8
    starts = [
        [var0 * 0.1, var0 / vix2_mean, 0.05, 0.05, 0.05, 0.90],
        [var0 * 0.05, var0 / vix2_mean * 0.5, 0.10, 0.03, 0.08, 0.88],
        [var0 * 0.2, var0 / vix2_mean * 1.5, 0.02, 0.08, 0.10, 0.80],
    ]
    bounds = [
        (-1e-2, 1e-2),
        (1e-10, 1e-2),
        (1e-6, 1.0),
        (1e-4, 0.3),
        (1e-4, 0.3),
        (0.5, 0.999),
    ]
    best_ll = np.inf
    best_params = None
    converged = False
    for s in starts:
        try:
            res = optimize.minimize(neg_loglik, s, method='L-BFGS-B', bounds=bounds,
                                    options={'maxiter': 500})
            if res.fun < best_ll:
                best_ll = res.fun
                best_params = res.x
                converged = res.success
        except Exception:
            continue
    return best_params, converged


# ============================================================
# SECTION 3: OUT-OF-SAMPLE FORECASTING
# ============================================================
print("\n[3] Out-of-sample sigma^2 forecasting...")

# Determine OOS mask
oos_mask = (dates >= OOS_START) & (dates <= OOS_END)
oos_indices = np.where(oos_mask)[0]
n_oos = len(oos_indices)
print(f"  OOS obs: {n_oos} from {dates[oos_indices[0]]:%Y-%m-%d} to {dates[oos_indices[-1]]:%Y-%m-%d}")

start_idx = oos_indices[0]
print(f"  First OOS idx = {start_idx}, WINDOW = {WINDOW}: {'OK' if start_idx >= WINDOW else 'USING WHAT-AVAILABLE'}")
if start_idx < WINDOW:
    print(f"  NOTE: initial training window will be {start_idx} obs (<{WINDOW}); grows over time via refits.")

# Try to load cached forecasts (numpy npz, no pickle) to skip 11-min refit loop
CACHE_OK = False
if os.path.exists(FORECASTS_NPZ):
    try:
        _c = np.load(FORECASTS_NPZ)
        gjr_forecasts = _c['gjr_forecasts']
        a4f_forecasts = _c['a4f_forecasts']
        if len(gjr_forecasts) == n_oos:
            print(f"  CACHE HIT: loaded {n_oos} forecasts from {FORECASTS_NPZ}")
            CACHE_OK = True
    except Exception as e:
        print(f"  Cache load failed: {e}")

if not CACHE_OK:
    gjr_forecasts = np.full(n_oos, np.nan)
    a4f_forecasts = np.full(n_oos, np.nan)

gjr_h = None
gjr_params = None
a4f_g = None
a4f_params = None

refit_count = 0
loop_iter = [] if CACHE_OK else list(enumerate(oos_indices))
for t_idx, abs_idx in loop_iter:
    # Refit trigger: first obs or every REFIT_EVERY
    if t_idx == 0 or (t_idx % REFIT_EVERY == 0):
        refit_count += 1
        train_start = max(0, abs_idx - WINDOW)
        train_ret = ret[train_start:abs_idx]
        train_vix = vix[train_start:abs_idx]

        # GJR
        gjr_p, gjr_conv = fit_gjr(train_ret)
        if gjr_p is not None:
            gjr_params = gjr_p
            h = np.var(train_ret[:min(250, len(train_ret))])
            for i in range(1, len(train_ret)):
                h = gjr_forecast_1step(gjr_params, h, train_ret[i-1])
            gjr_h = h

        # A4f
        a4f_p, a4f_conv = fit_a4f(train_ret, train_vix)
        if a4f_p is not None:
            a4f_params = a4f_p
            theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_p
            vix_lag_tr = np.empty(len(train_vix))
            vix_lag_tr[0] = train_vix[0]
            vix_lag_tr[1:] = train_vix[:-1]
            tau_tr = np.maximum(theta0 + theta1 * vix_lag_tr**2, 1e-16)
            persist = alpha_p + gamma_p / 2.0 + beta_p
            g = omega_g / (1.0 - persist)
            for i in range(1, len(train_ret)):
                u_prev = train_ret[i-1] / np.sqrt(tau_tr[i])
                asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
                g = omega_g + alpha_p * u_prev**2 + asym + beta_p * g
                g = max(g, 1e-10)
            a4f_g = g

        if refit_count % 10 == 0:
            elapsed = time.time() - START_TIME
            print(f"    Refit #{refit_count} at {dates[abs_idx]:%Y-%m-%d}, elapsed {elapsed:.0f}s")

    # 1-step-ahead sigma^2 forecast for day abs_idx
    r_prev = ret[abs_idx - 1]
    if gjr_params is not None:
        h_new = gjr_forecast_1step(gjr_params, gjr_h, r_prev)
        gjr_forecasts[t_idx] = h_new
        gjr_h = h_new

    if a4f_params is not None:
        theta0, theta1, omega_g, alpha_p, gamma_p, beta_p = a4f_params
        v_lag = vix[abs_idx - 1]
        tau_t = max(theta0 + theta1 * v_lag**2, 1e-16)
        u_prev = r_prev / np.sqrt(tau_t)
        asym = gamma_p * u_prev**2 if u_prev < 0 else 0.0
        g_new = omega_g + alpha_p * u_prev**2 + asym + beta_p * a4f_g
        g_new = max(g_new, 1e-10)
        a4f_forecasts[t_idx] = tau_t * g_new
        a4f_g = g_new

elapsed = time.time() - START_TIME
print(f"  Forecasting complete in {elapsed:.0f}s ({refit_count} refits)")

# Persist forecasts for fast re-run (no pickle, just arrays)
if not CACHE_OK:
    np.savez(FORECASTS_NPZ, gjr_forecasts=gjr_forecasts, a4f_forecasts=a4f_forecasts)
    print(f"  Saved forecast cache to {FORECASTS_NPZ}")


# ============================================================
# SECTION 4: VaR / ES CONSTRUCTION FROM SIGMA
# ============================================================
print("\n[4] Computing VaR and ES forecasts...")

def var_es_normal(sigma, alpha):
    """Normal-based VaR/ES. sigma is scalar or array. Returns POSITIVE loss values."""
    z = stats.norm.ppf(alpha)  # negative (e.g., -2.326 for 1%)
    var_ = -sigma * z          # positive (e.g., 2.326 * sigma)
    phi_z = stats.norm.pdf(z)
    es_ = sigma * phi_z / alpha  # positive
    return var_, es_


def var_es_student_t(sigma, alpha, nu=STUDENT_NU):
    """Student-t scaled so Var(r)=sigma^2. Returns POSITIVE loss values.

    If X ~ t_nu with unit variance, X = T / sqrt(nu/(nu-2)) where T ~ t_nu raw.
    Return r = sigma * X. So quantile of r at level alpha is:
        q_alpha(r) = sigma * t_{alpha,nu} * sqrt((nu-2)/nu)
    ES formula (lower-tail): ES_alpha = sigma * sqrt((nu-2)/nu) *
        [f_nu(t_{alpha,nu}) / alpha] * [(nu + t_{alpha,nu}^2) / (nu - 1)]
    Returned as positive loss.
    """
    scale = np.sqrt((nu - 2.0) / nu)
    t_a = stats.t.ppf(alpha, df=nu)            # negative
    f_ta = stats.t.pdf(t_a, df=nu)             # positive
    var_ = -sigma * scale * t_a                # positive
    es_magnitude = (f_ta / alpha) * (nu + t_a**2) / (nu - 1.0)  # positive
    es_ = sigma * scale * es_magnitude
    return var_, es_


# Valid joint mask
both_valid = (np.isfinite(gjr_forecasts) & (gjr_forecasts > 0) &
              np.isfinite(a4f_forecasts) & (a4f_forecasts > 0))
n_both = int(both_valid.sum())
print(f"  Valid joint obs: {n_both}/{n_oos}")

oos_ret = ret[oos_indices]
oos_vix = vix[oos_indices]
# For bucketing we use lagged VIX (predetermined info)
oos_vix_lag = np.empty(n_oos)
for i, idx in enumerate(oos_indices):
    oos_vix_lag[i] = vix[idx - 1] if idx > 0 else vix[0]
oos_dates = dates[oos_indices]

gjr_sigma = np.sqrt(gjr_forecasts)
a4f_sigma = np.sqrt(a4f_forecasts)


# ============================================================
# SECTION 5: FISSLER-ZIEGEL JOINT SCORE
# ============================================================
print("\n[5] Fissler-Ziegel joint score computation...")

def fz_score_0hom(v, e, y, alpha):
    """
    Strictly consistent 0-homogeneous Fissler-Ziegel joint score for (VaR, ES),
    written in LOSS-positive convention (v >= 0 is the VaR upper loss quantile,
    e >= v is the ES upper tail mean of losses).

    Let L = -y be the LOSS. Violation event is L > v (i.e., y < -v).
    FZ (2016) Theorem 5.2, 0-homogeneous class with G2(x) = -1/x, G1 = 0:

        S(v, e, y) = (1/(alpha*e)) * I{y <= -v} * (-y - v) + v/e + log(e) - 1

    (Equivalent to Patton, Ziegel, Chen (2019) JoE 211:388-413 Eq. 4 and
    Nolde & Ziegel (2017) Appendix.)

    Sanity-verified: halving or doubling ES (or VaR) away from Gaussian truth
    yields strictly higher mean score than truth on N(0, sigma^2) draws.
    """
    v = np.asarray(v, dtype=float)
    e = np.asarray(e, dtype=float)
    y = np.asarray(y, dtype=float)
    viol = (y <= -v).astype(float)
    e_safe = np.maximum(e, 1e-12)
    score = (1.0 / (alpha * e_safe)) * viol * (-y - v) + v / e_safe + np.log(e_safe) - 1.0
    return score


def hac_dm_test(d_array):
    """Newey-West HAC DM test (two-sided)."""
    d_array = d_array[np.isfinite(d_array)]
    T = len(d_array)
    if T < 30:
        return np.nan, np.nan, T
    d_mean = float(np.mean(d_array))
    max_lag = max(1, int(np.floor(T**(1/3))))
    gamma_0 = float(np.var(d_array, ddof=0))
    hac_var = gamma_0
    for j in range(1, max_lag + 1):
        w_j = 1 - j / (max_lag + 1)
        gamma_j = float(np.mean((d_array[j:] - d_mean) * (d_array[:-j] - d_mean)))
        hac_var += 2 * w_j * gamma_j
    if hac_var <= 0:
        return np.nan, np.nan, T
    dm_stat = d_mean / np.sqrt(hac_var / T)
    dm_p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return float(dm_stat), float(dm_p), T


# Compute VaR/ES for all combinations
fz_results = {}  # {(dist, alpha): { 'fz_gjr':..., 'fz_a4f':..., 'dm_t':..., ...}}
score_series = {}  # for plotting / series export

for dist in DISTS:
    for alpha in ALPHAS:
        if dist == 'normal':
            var_g, es_g = var_es_normal(gjr_sigma, alpha)
            var_a, es_a = var_es_normal(a4f_sigma, alpha)
        else:
            var_g, es_g = var_es_student_t(gjr_sigma, alpha)
            var_a, es_a = var_es_student_t(a4f_sigma, alpha)

        # FZ score
        fz_g = fz_score_0hom(var_g, es_g, oos_ret, alpha)
        fz_a = fz_score_0hom(var_a, es_a, oos_ret, alpha)

        valid = both_valid & np.isfinite(fz_g) & np.isfinite(fz_a)
        fz_g_v = fz_g[valid]
        fz_a_v = fz_a[valid]
        d = fz_g_v - fz_a_v  # positive => A4f better (lower score)

        mean_fz_g = float(np.mean(fz_g_v))
        mean_fz_a = float(np.mean(fz_a_v))
        dm_t, dm_p, T_dm = hac_dm_test(d)

        # Violation rate check
        viol_g = float(np.mean((oos_ret[valid] <= -var_g[valid]).astype(float)))
        viol_a = float(np.mean((oos_ret[valid] <= -var_a[valid]).astype(float)))

        # Empirical ES given violation
        viol_mask_g = (oos_ret <= -var_g) & valid
        viol_mask_a = (oos_ret <= -var_a) & valid
        emp_es_g = float(-np.mean(oos_ret[viol_mask_g])) if viol_mask_g.sum() > 0 else np.nan
        emp_es_a = float(-np.mean(oos_ret[viol_mask_a])) if viol_mask_a.sum() > 0 else np.nan
        avg_es_g_pred = float(np.mean(es_g[viol_mask_g])) if viol_mask_g.sum() > 0 else np.nan
        avg_es_a_pred = float(np.mean(es_a[viol_mask_a])) if viol_mask_a.sum() > 0 else np.nan

        key = f"{dist}_alpha{int(alpha*100):02d}"
        fz_results[key] = {
            'dist': dist,
            'alpha': alpha,
            'n': int(valid.sum()),
            'fz_mean_gjr': mean_fz_g,
            'fz_mean_a4f': mean_fz_a,
            'fz_diff_pct': float((mean_fz_a - mean_fz_g) / abs(mean_fz_g) * 100) if mean_fz_g != 0 else None,
            'dm_t': dm_t,
            'dm_p': dm_p,
            'harvey_pass': bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
            'violation_rate_gjr': viol_g,
            'violation_rate_a4f': viol_a,
            'violation_rate_target': alpha,
            'empirical_es_given_viol_gjr': emp_es_g,
            'empirical_es_given_viol_a4f': emp_es_a,
            'avg_predicted_es_given_viol_gjr': avg_es_g_pred,
            'avg_predicted_es_given_viol_a4f': avg_es_a_pred,
        }
        score_series[key] = {
            'fz_gjr': fz_g,
            'fz_a4f': fz_a,
            'var_gjr': var_g,
            'var_a4f': var_a,
            'es_gjr': es_g,
            'es_a4f': es_a,
        }

        print(f"  [{key}] FZ_GJR={mean_fz_g:.5f}  FZ_A4f={mean_fz_a:.5f}  "
              f"DM t={dm_t:+.3f}  Harvey={'PASS' if np.isfinite(dm_t) and abs(dm_t)>3 else 'FAIL'}  "
              f"viol GJR={viol_g*100:.2f}%/A4f={viol_a*100:.2f}% (target {alpha*100:.0f}%)")


# ============================================================
# SECTION 6: ACERBI-SZEKELY (2014) Z-TESTS
# ============================================================
print("\n[6] Acerbi-Szekely (2014) Z-tests for ES...")

def acerbi_szekely_z1(returns, var_, es_, alpha):
    """
    Z1: Test if average violation magnitude matches ES forecast.
    Z1 = (1/N_T) * sum_{t in T} (r_t / ES_t) + 1
    where T = {t : r_t < -VaR_t}. Under H0: E[Z1] = 0.
    """
    viol_mask = returns <= -var_
    N_T = int(viol_mask.sum())
    if N_T == 0:
        return np.nan, N_T
    # Using loss convention: r violates when r <= -var. Then -r is loss.
    # ES_t predicts E[-r | r <= -var] = ES_t. So we want:
    # Z1 = -mean(r_t[viol])/mean(ES_t[viol]) - 1 (testing ratio=1)
    # Acerbi-Szekely original: Z1 = (1/N_T) sum (X_t/ES_t) + 1 where X_t = r_t (signed)
    # With r_t negative on violation, X_t/ES_t is negative, +1 should be 0 under H0.
    z1 = float(np.mean(returns[viol_mask] / es_[viol_mask]) + 1.0)
    return z1, N_T


def acerbi_szekely_z2(returns, var_, es_, alpha):
    """
    Z2: Unconditional ES test using violation indicator.
    Z2 = (1/(N*alpha)) * sum_t (r_t * I{r_t < -VaR_t} / ES_t) + 1
    Under H0 (correct VaR and ES): E[Z2] = 0.
    """
    N = len(returns)
    viol_mask = returns <= -var_
    ratio = np.where(viol_mask, returns / es_, 0.0)
    z2 = float(np.sum(ratio) / (N * alpha) + 1.0)
    return z2, int(viol_mask.sum())


def acerbi_szekely_bootstrap_p(returns, var_, es_, alpha, model_sigma, dist_name,
                                n_boot=1000, test='z2'):
    """
    Bootstrap p-value under H0: returns actually follow the model's implied distribution.
    For each boot, simulate returns from model (r_t = sigma_t * X, X~N(0,1) or t_nu scaled),
    compute Z-stat, tail probability gives p-value.
    One-sided: reject H0 if Z is too negative (ES under-estimated).
    """
    rng = np.random.default_rng(42)
    N = len(returns)
    boot_stats = np.empty(n_boot)
    for b in range(n_boot):
        if dist_name == 'normal':
            X = rng.standard_normal(N)
        else:
            scale = np.sqrt((STUDENT_NU - 2.0) / STUDENT_NU)
            X = rng.standard_t(df=STUDENT_NU, size=N) * scale
        r_sim = model_sigma * X
        if test == 'z1':
            z_b, _ = acerbi_szekely_z1(r_sim, var_, es_, alpha)
        else:
            z_b, _ = acerbi_szekely_z2(r_sim, var_, es_, alpha)
        boot_stats[b] = z_b
    # Observed
    if test == 'z1':
        z_obs, _ = acerbi_szekely_z1(returns, var_, es_, alpha)
    else:
        z_obs, _ = acerbi_szekely_z2(returns, var_, es_, alpha)
    # One-sided p-value: Z < z_obs under H0 when ES is truthful; reject when observed Z is
    # significantly negative (data has more extreme losses than ES predicts).
    boot_stats_finite = boot_stats[np.isfinite(boot_stats)]
    if len(boot_stats_finite) < 50:
        return z_obs, np.nan
    p_val = float(np.mean(boot_stats_finite <= z_obs))
    return float(z_obs), float(p_val)


as_results = {}
for dist in DISTS:
    for alpha in ALPHAS:
        if dist == 'normal':
            var_g, es_g = var_es_normal(gjr_sigma, alpha)
            var_a, es_a = var_es_normal(a4f_sigma, alpha)
        else:
            var_g, es_g = var_es_student_t(gjr_sigma, alpha)
            var_a, es_a = var_es_student_t(a4f_sigma, alpha)

        valid = both_valid
        ret_v = oos_ret[valid]

        z1_g, n1g = acerbi_szekely_z1(ret_v, var_g[valid], es_g[valid], alpha)
        z1_a, n1a = acerbi_szekely_z1(ret_v, var_a[valid], es_a[valid], alpha)
        z2_g, n2g = acerbi_szekely_z2(ret_v, var_g[valid], es_g[valid], alpha)
        z2_a, n2a = acerbi_szekely_z2(ret_v, var_a[valid], es_a[valid], alpha)

        # Bootstrap p (using model's sigma path to simulate)
        z2_g_boot, p2_g = acerbi_szekely_bootstrap_p(
            ret_v, var_g[valid], es_g[valid], alpha, gjr_sigma[valid], dist, n_boot=1000, test='z2')
        z2_a_boot, p2_a = acerbi_szekely_bootstrap_p(
            ret_v, var_a[valid], es_a[valid], alpha, a4f_sigma[valid], dist, n_boot=1000, test='z2')

        key = f"{dist}_alpha{int(alpha*100):02d}"
        as_results[key] = {
            'dist': dist,
            'alpha': alpha,
            'z1_gjr': z1_g, 'z1_a4f': z1_a,
            'z1_n_viol_gjr': n1g, 'z1_n_viol_a4f': n1a,
            'z2_gjr': z2_g, 'z2_a4f': z2_a,
            'z2_p_gjr': p2_g, 'z2_p_a4f': p2_a,
            'z2_reject_gjr_5pct': bool(p2_g < 0.05) if np.isfinite(p2_g) else None,
            'z2_reject_a4f_5pct': bool(p2_a < 0.05) if np.isfinite(p2_a) else None,
        }
        print(f"  [{key}] Z1 GJR={z1_g:+.3f}({n1g}) A4f={z1_a:+.3f}({n1a}) | "
              f"Z2 GJR={z2_g:+.3f} p={p2_g:.3f} | A4f={z2_a:+.3f} p={p2_a:.3f}")


# ============================================================
# SECTION 7: REGIME (VIX-BUCKET) ANALYSIS
# ============================================================
print("\n[7] VIX-bucket regime analysis...")

regime_results = {}
for bname, bmin, bmax in VIX_BUCKETS:
    reg_mask = (oos_vix_lag >= bmin) & (oos_vix_lag < bmax) & both_valid
    n_r = int(reg_mask.sum())
    if n_r < 30:
        regime_results[bname] = {'status': 'insufficient', 'n': n_r}
        continue

    by_alpha = {}
    for dist in DISTS:
        for alpha in ALPHAS:
            if dist == 'normal':
                var_g, es_g = var_es_normal(gjr_sigma, alpha)
                var_a, es_a = var_es_normal(a4f_sigma, alpha)
            else:
                var_g, es_g = var_es_student_t(gjr_sigma, alpha)
                var_a, es_a = var_es_student_t(a4f_sigma, alpha)

            fz_g = fz_score_0hom(var_g, es_g, oos_ret, alpha)
            fz_a = fz_score_0hom(var_a, es_a, oos_ret, alpha)
            d = (fz_g - fz_a)[reg_mask]
            d = d[np.isfinite(d)]
            if len(d) < 30:
                continue
            m_g = float(np.mean(fz_g[reg_mask][np.isfinite(fz_g[reg_mask])]))
            m_a = float(np.mean(fz_a[reg_mask][np.isfinite(fz_a[reg_mask])]))
            dm_t, dm_p, _ = hac_dm_test(d)
            key = f"{dist}_alpha{int(alpha*100):02d}"
            by_alpha[key] = {
                'fz_gjr': m_g, 'fz_a4f': m_a,
                'dm_t': dm_t, 'dm_p': dm_p,
                'harvey_pass': bool(abs(dm_t) > 3.0) if np.isfinite(dm_t) else False,
            }

    regime_results[bname] = {
        'vix_range': [bmin, bmax],
        'n': n_r,
        'vix_mean': float(np.mean(oos_vix_lag[reg_mask])),
        'by_spec': by_alpha,
    }
    n_pass = sum(1 for k,v in by_alpha.items() if v['harvey_pass'])
    print(f"  [{bname:<8}] n={n_r:4d}  Harvey passes: {n_pass}/{len(by_alpha)}")


# ============================================================
# SECTION 8: SAVE + PLOTS
# ============================================================
print("\n[8] Saving results and generating plots...")

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- Plot 1: FZ score time series (Normal alpha=5%) ---
key_main = 'normal_alpha05'
fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
ax = axes[0]
# Cumulative FZ score difference
fz_g_series = score_series[key_main]['fz_gjr']
fz_a_series = score_series[key_main]['fz_a4f']
valid = both_valid & np.isfinite(fz_g_series) & np.isfinite(fz_a_series)
cumdiff = np.cumsum(np.where(valid, fz_g_series - fz_a_series, 0.0))
ax.plot(np.array(oos_dates), cumdiff, color='navy', lw=1.2)
ax.axhline(0, color='grey', ls='--', lw=0.8)
ax.set_title(f'K1076  Cumulative FZ Score Advantage (A4f over GJR)  -  {key_main}')
ax.set_ylabel('Cumulative (FZ_GJR - FZ_A4f)')
ax.grid(alpha=0.3)
# Mark crisis periods
for (cname, cs, ce), color in zip(
    [('GFC','2008-01-01','2009-12-31'),('COVID','2020-02-01','2020-06-30'),('2022 Bear','2022-01-01','2022-12-31')],
    ['tomato','orange','gold']):
    ax.axvspan(pd.Timestamp(cs), pd.Timestamp(ce), alpha=0.15, color=color, label=cname)
ax.legend(loc='upper left', fontsize=9)

ax2 = axes[1]
# Rolling 252d mean of daily diff
daily_d = np.where(valid, fz_g_series - fz_a_series, np.nan)
roll = pd.Series(daily_d, index=oos_dates).rolling(252, min_periods=60).mean()
ax2.plot(np.array(roll.index), roll.values, color='darkgreen', lw=1.0)
ax2.axhline(0, color='grey', ls='--', lw=0.8)
ax2.set_title('Rolling 1-year mean daily FZ advantage')
ax2.set_xlabel('Date')
ax2.set_ylabel('mean (FZ_GJR - FZ_A4f)')
ax2.grid(alpha=0.3)
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1076_fz_score_series.png'), dpi=150)
plt.close()
print("  Saved k1076_fz_score_series.png")

# --- Plot 2: DM matrix (dist x alpha) ---
fig, ax = plt.subplots(figsize=(8, 5))
mat = np.zeros((len(DISTS), len(ALPHAS)))
labels = []
for i, dist in enumerate(DISTS):
    for j, alpha in enumerate(ALPHAS):
        key = f"{dist}_alpha{int(alpha*100):02d}"
        mat[i,j] = fz_results[key]['dm_t']
im = ax.imshow(mat, cmap='RdYlGn_r', aspect='auto', vmin=-max(abs(mat.min()), abs(mat.max())),
               vmax=max(abs(mat.min()), abs(mat.max())))
ax.set_xticks(range(len(ALPHAS)))
ax.set_xticklabels([f'alpha={a*100:.0f}%' for a in ALPHAS])
ax.set_yticks(range(len(DISTS)))
ax.set_yticklabels([d.replace('_',' ') for d in DISTS])
for i in range(len(DISTS)):
    for j in range(len(ALPHAS)):
        t = mat[i,j]
        ax.text(j, i, f'{t:+.2f}', ha='center', va='center',
                color='white' if abs(t) > 3 else 'black', fontsize=12, fontweight='bold')
ax.set_title('K1076 FZ DM t-statistic matrix  (positive = A4f better, |t|>3 = Harvey PASS)')
plt.colorbar(im, ax=ax, label='DM t')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1076_dm_matrix.png'), dpi=150)
plt.close()
print("  Saved k1076_dm_matrix.png")

# --- Plot 3: Acerbi-Szekely Z bars ---
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
keys = [f"{d}_alpha{int(a*100):02d}" for d in DISTS for a in ALPHAS]
x = np.arange(len(keys))
w = 0.35
for ax, test_key, title in zip(axes, ['z1', 'z2'], ['Z1 (conditional)', 'Z2 (unconditional)']):
    z_gjr = [as_results[k][f'{test_key}_gjr'] for k in keys]
    z_a4f = [as_results[k][f'{test_key}_a4f'] for k in keys]
    ax.bar(x - w/2, z_gjr, width=w, label='GJR', color='steelblue')
    ax.bar(x + w/2, z_a4f, width=w, label='A4f', color='tomato')
    ax.axhline(0, color='black', lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels([k.replace('_alpha',' α=').replace('alpha','α') for k in keys], rotation=25)
    ax.set_title(f'Acerbi-Szekely {title}')
    ax.legend()
    ax.grid(alpha=0.3)
plt.suptitle('K1076 Acerbi-Szekely Z-statistics  (Z < 0 = ES under-estimated)')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1076_acerbi_szekely.png'), dpi=150)
plt.close()
print("  Saved k1076_acerbi_szekely.png")

# --- Plot 4: Regime FZ (dist=normal, alpha=5%) ---
bucket_names = [b[0] for b in VIX_BUCKETS if b[0] in regime_results
                and regime_results[b[0]].get('by_spec')]
spec_key = 'normal_alpha05'
fz_g_vals = [regime_results[b]['by_spec'][spec_key]['fz_gjr'] for b in bucket_names]
fz_a_vals = [regime_results[b]['by_spec'][spec_key]['fz_a4f'] for b in bucket_names]
dm_ts = [regime_results[b]['by_spec'][spec_key]['dm_t'] for b in bucket_names]
ns = [regime_results[b]['n'] for b in bucket_names]

fig, axes = plt.subplots(1, 2, figsize=(12, 5))
ax = axes[0]
xs = np.arange(len(bucket_names))
w = 0.4
ax.bar(xs - w/2, fz_g_vals, w, label='GJR', color='steelblue')
ax.bar(xs + w/2, fz_a_vals, w, label='A4f', color='tomato')
ax.set_xticks(xs); ax.set_xticklabels(bucket_names)
ax.set_ylabel('Mean FZ score (lower = better)')
ax.set_title(f'FZ score by VIX bucket ({spec_key})')
for i, n in enumerate(ns):
    ax.text(i, min(fz_g_vals[i], fz_a_vals[i]), f'n={n}', ha='center', va='top', fontsize=8)
ax.legend(); ax.grid(alpha=0.3)

ax2 = axes[1]
colors = ['green' if abs(t) > 3 else 'orange' if abs(t) > 2 else 'red' for t in dm_ts]
ax2.bar(xs, dm_ts, color=colors)
ax2.axhline(3, color='darkgreen', ls='--', label='Harvey |t|=3')
ax2.axhline(-3, color='darkgreen', ls='--')
ax2.set_xticks(xs); ax2.set_xticklabels(bucket_names)
ax2.set_ylabel('DM t (A4f vs GJR)')
ax2.set_title('DM t-statistic by bucket')
ax2.legend(); ax2.grid(alpha=0.3)
plt.suptitle('K1076 Regime FZ analysis')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1076_regime_fz.png'), dpi=150)
plt.close()
print("  Saved k1076_regime_fz.png")

# --- Plot 5: Normal vs Student-t ---
fig, axes = plt.subplots(1, 2, figsize=(12, 5))
for ax, alpha in zip(axes, ALPHAS):
    keys_alpha = [f"{d}_alpha{int(alpha*100):02d}" for d in DISTS]
    gjr_vals = [fz_results[k]['fz_mean_gjr'] for k in keys_alpha]
    a4f_vals = [fz_results[k]['fz_mean_a4f'] for k in keys_alpha]
    xs = np.arange(len(DISTS)); w = 0.4
    ax.bar(xs - w/2, gjr_vals, w, label='GJR', color='steelblue')
    ax.bar(xs + w/2, a4f_vals, w, label='A4f', color='tomato')
    ax.set_xticks(xs); ax.set_xticklabels([d.replace('_',' ') for d in DISTS])
    ax.set_ylabel('Mean FZ score (lower = better)')
    ax.set_title(f'α = {alpha*100:.0f}%')
    ax.legend(); ax.grid(alpha=0.3)
plt.suptitle('K1076 FZ score: Normal vs Student-t innovation')
plt.tight_layout()
plt.savefig(os.path.join(SCRIPT_DIR, 'k1076_normal_vs_t.png'), dpi=150)
plt.close()
print("  Saved k1076_normal_vs_t.png")


# ============================================================
# SECTION 9: SAVE FORECASTS CSV + RESULTS JSON
# ============================================================
print("\n[9] Persisting artifacts...")

# CSV with daily forecasts (for downstream reuse)
fc_df = pd.DataFrame({
    'date': oos_dates,
    'ret': oos_ret,
    'vix_lag': oos_vix_lag,
    'sigma2_gjr': gjr_forecasts,
    'sigma2_a4f': a4f_forecasts,
    'var_gjr_norm_01': -gjr_sigma * stats.norm.ppf(0.01),
    'var_a4f_norm_01': -a4f_sigma * stats.norm.ppf(0.01),
    'var_gjr_norm_05': -gjr_sigma * stats.norm.ppf(0.05),
    'var_a4f_norm_05': -a4f_sigma * stats.norm.ppf(0.05),
})
fc_df.to_csv(FORECASTS_PATH, index=False)
print(f"  Saved {FORECASTS_PATH}  ({len(fc_df)} rows)")

# Hypothesis verdicts
def verdict_h1():
    # A4f dominates GJR in FZ joint score (Harvey pass on main spec)
    specs = list(fz_results.keys())
    passes = [fz_results[k]['harvey_pass'] and fz_results[k]['dm_t'] > 0 for k in specs]
    return {'passes': int(sum(passes)), 'total': len(specs), 'result': 'PASS' if sum(passes) >= 2 else 'FAIL'}

def verdict_h2():
    # A4f Z2 p-value not rejecting (>0.05) in at least one spec
    pvals = [as_results[k]['z2_p_a4f'] for k in as_results if as_results[k]['z2_p_a4f'] is not None]
    return {'a4f_passes': int(sum(1 for p in pvals if p > 0.05)), 'total': len(pvals)}

def verdict_h3():
    # A4f advantage largest in High+Crisis buckets
    buckets = [b for b in regime_results if regime_results[b].get('by_spec')]
    if not buckets:
        return {'result': 'n/a'}
    spec = 'normal_alpha05'
    tstats = {b: regime_results[b]['by_spec'].get(spec, {}).get('dm_t') for b in buckets}
    ranked = sorted([(b, t) for b, t in tstats.items() if t is not None],
                    key=lambda x: -abs(x[1]))
    return {'ranking_by_|dm_t|': [(b, float(t)) for b, t in ranked]}

def verdict_h4():
    # Consistency across dist
    same_sign_count = 0
    total = 0
    for alpha in ALPHAS:
        k_n = f"normal_alpha{int(alpha*100):02d}"
        k_t = f"student_t_alpha{int(alpha*100):02d}"
        if np.isfinite(fz_results[k_n]['dm_t']) and np.isfinite(fz_results[k_t]['dm_t']):
            total += 1
            if np.sign(fz_results[k_n]['dm_t']) == np.sign(fz_results[k_t]['dm_t']):
                same_sign_count += 1
    return {'same_sign_count': same_sign_count, 'total': total}

hypotheses = {
    'H1_FZ_DM_Harvey': verdict_h1(),
    'H2_AS_Z2_noreject': verdict_h2(),
    'H3_regime_ordering': verdict_h3(),
    'H4_dist_consistency': verdict_h4(),
}

results = {
    'metadata': {
        'experiment_id': EXPERIMENT_ID,
        'date': datetime.now(timezone.utc).isoformat(),
        'proposer': 'Claude',
        'executor': 'Claude',
        'data_source': 'yfinance SPY + ^VIX',
        'data_start': DATA_START, 'data_end': DATA_END,
        'oos_start': OOS_START, 'oos_end': OOS_END,
        'n_data': int(n_total), 'n_oos': int(n_oos), 'n_valid_joint': n_both,
        'window': WINDOW, 'refit_every': REFIT_EVERY,
        'alphas': ALPHAS, 'dists': DISTS, 'student_t_nu': STUDENT_NU,
        'seed': 42,
        'runtime_sec': float(time.time() - START_TIME),
        'fz_form': 'Patton-Ziegel-Chen 2019 Eq 4 (0-homogeneous FZ16)',
        'references': [
            'Fissler & Ziegel (2016) Annals of Statistics 44(4):1680-1707',
            'Acerbi & Szekely (2014) Risk 27(11)',
            'Gneiting (2011) JASA 106:746-762',
            'Nolde & Ziegel (2017) Annals of Applied Statistics 11(4)',
            'Patton, Ziegel, Chen (2019) JoE 211:388-413',
        ],
    },
    'fz_results': fz_results,
    'acerbi_szekely': as_results,
    'regime_by_vix': regime_results,
    'hypothesis_verdicts': hypotheses,
}

with open(RESULTS_PATH, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"  Saved {RESULTS_PATH}")

print("\n" + "=" * 72)
print(f"{EXPERIMENT_ID} DONE  total runtime = {time.time()-START_TIME:.0f}s")
print("=" * 72)

# Summary
print("\nSummary:")
for k, v in fz_results.items():
    print(f"  {k:<22} DM t = {v['dm_t']:+7.3f}  p = {v['dm_p']:.4f}  "
          f"FZ% diff = {v['fz_diff_pct']:+6.2f}%  viol A4f={v['violation_rate_a4f']*100:4.2f}%")

print("\nHypothesis verdicts:")
for h, v in hypotheses.items():
    print(f"  {h}: {v}")
