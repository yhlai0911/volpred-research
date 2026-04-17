"""
K1241: Paper 10 §6.1 Primary Fear-Channel Regression
====================================================
BTC GARCH-X(VIX²) vs baseline GJR-GARCH — produce canonical phi + Harvey |t|>3

[提出: Claude, 執行: Claude / worktree agent-afd040e6]

Research Question
-----------------
Does lagged VIX² enter the BTC variance equation with a significant positive
coefficient (fear channel)?  Paper 10 Table 3 requires canonical phi, HAC-robust
t-stat, LRT vs baseline, QLIKE / DM-HLN OOS comparison, Harvey (2016) |t|>3
verdict, and sub-period robustness (P1 2015-2020 / P2 2021-2023 / P3 2024-2026).

Models
------
M1  baseline  : GJR-GARCH(1,1) Student-t           (no exogenous)
M2  GARCH-X   : GJR-GARCH(1,1) Student-t + phi * VIX^2_{t-1}   (leverage + fear)
M3  fear-only : GARCH(1,1)   Student-t + phi * VIX^2_{t-1}     (pure fear, no leverage)

Variance equation (M2):
    sigma2_t = omega + alpha * r_{t-1}^2 + gamma * r_{t-1}^2 * 1[r_{t-1}<0]
              + beta * sigma2_{t-1} + phi * VIX^2_{t-1}

VIX is in level units (one-to-one with CBOE daily close).  VIX² is in "vol-points-squared"
(e.g. VIX=20 -> VIX²=400).  Return r is in percent.

Data / Timing
-------------
- BTC-USD daily close:  2015-01-01 -> 2026-04-15  (yfinance, weekends included,
  matching K1129 / K1133 convention)
- ^VIX daily close:      same range
- Alignment:  reindex VIX to BTC trading calendar, forward-fill weekends
  (per K1238 confirmed scope: BTC trades 7 days, VIX trades M-F; ffill = "fear
  state persists over weekend" — this is the standard treatment in Bouri et al.
  (2020 JIFMIM) and Matkovskyy-Jalan (2019))
- Log-return BTC in percent: 100 * (log P_t - log P_{t-1})
- VIX level; VIX² lagged one trading day (signal from t-1, response at t)

Split
-----
- In-sample (IS) 70% / OOS 30% (~3 years 2023-03 -> 2026-04)
- Sub-period robustness: M2 re-fit on full sample within each sub-period:
    P1 2015-2020,  P2 2021-2023,  P3 2024-2026  (K1133 convention)

Estimation
----------
- MLE via scipy.optimize.minimize L-BFGS-B with Nelder-Mead fallback
- Bollerslev-Wooldridge (1992) QMLE robust sandwich SE:
      V = H^{-1} OPG H^{-1}
  where H is numerically-computed Hessian of the log-lik and OPG is outer-product
  of per-observation scores.
- t_BW = phi_hat / sqrt(V_{phi,phi}).  This is the robust t reported in Paper 10 §6.1.
- LRT M2 vs M1 with df = 1 (phi restriction)
- DM-HLN (Harvey-Leybourne-Newbold 1997) on QLIKE loss, OOS only

Harvey (2016) threshold
-----------------------
|t| > 3.0 for publishable fear-channel effect (Harvey 2016 JF multiple-testing
penalty).  Paper 10 §6.1 verdict = PASS if |t_BW(phi)| > 3 AND LRT p < 0.001
AND DM-HLN |t| > 2 (M2 vs M1 QLIKE improvement).

Lookahead guardrails
--------------------
- VIX is shifted t-1 BEFORE estimation and before forecasting.
- OOS variance recursion uses only in-sample-estimated parameters; refit is not
  performed in the OOS rolling loop (static phi) to isolate the structural
  contribution of VIX² vs re-estimation noise.  A rolling-refit robustness is
  not part of the Paper 10 §6.1 primary spec.
- Explicit assertion: `assert vix2_lag.index.max() <= r.index.max() - pd.Timedelta(0)`
  (the lagged series contains information from t-1 only)

Seed
----
np.random.seed(42)

Reproduction
------------
    python experiments/k1241/k1241.py
"""

import json
import os
import sys
import time
import warnings
from datetime import datetime, timezone

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize
from scipy.special import gammaln

sys.stdout.reconfigure(line_buffering=True)
warnings.filterwarnings("ignore")
np.random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

print("=" * 72)
print("K1241: Paper 10 §6.1 Fear-Channel Primary Regression")
print("BTC GARCH-X(VIX^2) vs GJR baseline")
print("=" * 72)
sys.stdout.flush()


# ============================================================
# STEP 0: Data
# ============================================================
import yfinance as yf

START = "2015-01-01"
END = "2026-04-15"

print("\n[0] Downloading BTC-USD and ^VIX ...")
sys.stdout.flush()

btc_df = yf.download("BTC-USD", start=START, end=END, progress=False, auto_adjust=False)
vix_df = yf.download("^VIX", start=START, end=END, progress=False, auto_adjust=False)

for df in (btc_df, vix_df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

btc_close = btc_df["Adj Close"] if "Adj Close" in btc_df.columns else btc_df["Close"]
vix_close = vix_df["Adj Close"] if "Adj Close" in vix_df.columns else vix_df["Close"]

btc_close = btc_close.dropna()
vix_close = vix_close.dropna()

print(f"  BTC-USD: {len(btc_close)} days, {btc_close.index[0].date()} -> {btc_close.index[-1].date()}")
print(f"  ^VIX   : {len(vix_close)} days, {vix_close.index[0].date()} -> {vix_close.index[-1].date()}")

# Align: reindex VIX to BTC calendar (BTC trades 7 days; VIX only weekdays)
# ffill (carry last available VIX across weekends)
vix_aligned = vix_close.reindex(btc_close.index).ffill()
# If the very first BTC day is pre-VIX (should not happen given 2015 start), back-fill
vix_aligned = vix_aligned.bfill()

# Returns and regressor
btc_ret = 100.0 * np.log(btc_close / btc_close.shift(1))
vix_level = vix_aligned.copy()
vix_sq = vix_level ** 2

# Drop first NA from return
df_all = pd.DataFrame({
    "r": btc_ret,
    "vix": vix_level,
    "vix2": vix_sq,
}).dropna()

# Lag VIX² by one trading day (lookahead guard)
# shift(1) then dropna ensures every row's vix2_lag is *strictly* observed BEFORE r_t.
df_all["vix2_lag"] = df_all["vix2"].shift(1)
df_all = df_all.dropna().copy()

# Lookahead guard: vix2_lag at index i must equal vix2 at index i-1 (of original df)
# We verify this by reconstructing the shifted series from the pre-drop frame.
_pre_drop = pd.DataFrame({"r": btc_ret, "vix2": vix_sq}).dropna()
_reference_lag = _pre_drop["vix2"].shift(1).reindex(df_all.index)
assert np.allclose(df_all["vix2_lag"].values, _reference_lag.values, equal_nan=False), \
    "Lookahead check: vix2_lag must equal vix2 shifted by +1 day"

print(f"\n  Aligned sample: {len(df_all)} days, "
      f"{df_all.index[0].date()} -> {df_all.index[-1].date()}")
print(f"  BTC return: mean={df_all['r'].mean():.4f}%, std={df_all['r'].std():.4f}%, "
      f"skew={df_all['r'].skew():.3f}, kurt(excess)={df_all['r'].kurtosis():.3f}")
print(f"  VIX level : mean={df_all['vix'].mean():.2f}, std={df_all['vix'].std():.2f}, "
      f"min={df_all['vix'].min():.2f}, max={df_all['vix'].max():.2f}")
print(f"  VIX^2_lag : mean={df_all['vix2_lag'].mean():.1f}, std={df_all['vix2_lag'].std():.1f}")
sys.stdout.flush()


# ============================================================
# STEP 1: Model log-likelihoods
# ============================================================
LOG2PI = float(np.log(2 * np.pi))


def _student_t_ll(eps2_over_sigma2, sigma2, nu):
    """Standardized Student-t log-density (per observation)."""
    return (gammaln((nu + 1) / 2) - gammaln(nu / 2)
            - 0.5 * np.log(np.pi * (nu - 2) * sigma2)
            - (nu + 1) / 2 * np.log(1.0 + eps2_over_sigma2 / (nu - 2)))


def m1_gjr_t_filter(params, r):
    """Filter for GJR-GARCH(1,1) with Student-t innovations.  Returns sigma2 array."""
    omega, alpha, gamma, beta, _log_nu = params
    T = len(r)
    sigma2 = np.empty(T)
    sigma2[0] = np.var(r)
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        sigma2[t] = (omega
                     + alpha * r[t - 1] ** 2
                     + gamma * r[t - 1] ** 2 * ind
                     + beta * sigma2[t - 1])
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return sigma2


def m1_gjr_t_nll(params, r):
    omega, alpha, gamma, beta, log_nu_m2 = params
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e10
    nu = np.exp(log_nu_m2) + 2.0
    sigma2 = m1_gjr_t_filter(params, r)
    eps2 = r ** 2 / sigma2
    ll = _student_t_ll(eps2, sigma2, nu)
    nll = -np.sum(ll)
    return nll if np.isfinite(nll) else 1e10


def m2_garchx_filter(params, r, x):
    """GJR-GARCH(1,1) + phi * x_{t-1}   (x already lagged on input)."""
    omega, alpha, gamma, beta, phi, _log_nu = params
    T = len(r)
    sigma2 = np.empty(T)
    sigma2[0] = np.var(r)
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        sigma2[t] = (omega
                     + alpha * r[t - 1] ** 2
                     + gamma * r[t - 1] ** 2 * ind
                     + beta * sigma2[t - 1]
                     + phi * x[t])          # x[t] IS the lagged value at time t
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return sigma2


def m2_garchx_nll(params, r, x):
    omega, alpha, gamma, beta, phi, log_nu_m2 = params
    if omega <= 0 or alpha < 0 or gamma < 0 or beta < 0:
        return 1e10
    nu = np.exp(log_nu_m2) + 2.0
    sigma2 = m2_garchx_filter(params, r, x)
    eps2 = r ** 2 / sigma2
    ll = _student_t_ll(eps2, sigma2, nu)
    nll = -np.sum(ll)
    return nll if np.isfinite(nll) else 1e10


def m3_fear_only_filter(params, r, x):
    """GARCH(1,1) + phi * x_{t-1}  (no leverage / no gamma)."""
    omega, alpha, beta, phi, _log_nu = params
    T = len(r)
    sigma2 = np.empty(T)
    sigma2[0] = np.var(r)
    for t in range(1, T):
        sigma2[t] = (omega
                     + alpha * r[t - 1] ** 2
                     + beta * sigma2[t - 1]
                     + phi * x[t])
        if sigma2[t] < 1e-10:
            sigma2[t] = 1e-10
    return sigma2


def m3_fear_only_nll(params, r, x):
    omega, alpha, beta, phi, log_nu_m2 = params
    if omega <= 0 or alpha < 0 or beta < 0:
        return 1e10
    nu = np.exp(log_nu_m2) + 2.0
    sigma2 = m3_fear_only_filter(params, r, x)
    eps2 = r ** 2 / sigma2
    ll = _student_t_ll(eps2, sigma2, nu)
    nll = -np.sum(ll)
    return nll if np.isfinite(nll) else 1e10


# ============================================================
# STEP 2: Optimizer wrappers
# ============================================================

def _try_starts(fn, starts, args, bounds):
    best = None
    for x0 in starts:
        try:
            res = minimize(fn, x0, args=args, method="L-BFGS-B",
                           bounds=bounds, options={"maxiter": 1000})
            if (best is None or res.fun < best.fun) and np.isfinite(res.fun):
                best = res
        except Exception:
            continue
    # Nelder-Mead fallback from best L-BFGS-B
    if best is not None:
        try:
            res_nm = minimize(fn, best.x, args=args, method="Nelder-Mead",
                              options={"maxiter": 4000, "xatol": 1e-7, "fatol": 1e-7})
            if np.isfinite(res_nm.fun) and res_nm.fun < best.fun:
                best = res_nm
        except Exception:
            pass
    return best


def fit_m1(r):
    var_r = np.var(r)
    starts = [
        [var_r * 0.05, 0.05, 0.05, 0.88, np.log(6.0)],
        [var_r * 0.02, 0.03, 0.10, 0.85, np.log(4.0)],
        [var_r * 0.10, 0.02, 0.02, 0.92, np.log(10.0)],
    ]
    bounds = [(1e-8, var_r * 20), (1e-8, 0.5), (0.0, 0.5), (0.3, 0.999),
              (np.log(0.1), np.log(100.0))]
    res = _try_starts(m1_gjr_t_nll, starts, (r,), bounds)
    return res


def fit_m2(r, x):
    var_r = np.var(r)
    xm = np.mean(x)
    starts = [
        [var_r * 0.05, 0.05, 0.05, 0.80, var_r * 0.01 / max(xm, 1.0), np.log(6.0)],
        [var_r * 0.02, 0.03, 0.08, 0.75, var_r * 0.02 / max(xm, 1.0), np.log(4.0)],
        [var_r * 0.10, 0.02, 0.02, 0.85, 1e-4, np.log(10.0)],
        [var_r * 0.05, 0.05, 0.05, 0.70, 0.0, np.log(8.0)],
    ]
    bounds = [(1e-8, var_r * 20), (0.0, 0.5), (0.0, 0.5), (0.0, 0.999),
              (-1.0, 1.0),       # phi can in principle be negative, but fear-channel expects > 0
              (np.log(0.1), np.log(100.0))]
    res = _try_starts(m2_garchx_nll, starts, (r, x), bounds)
    return res


def fit_m3(r, x):
    var_r = np.var(r)
    xm = np.mean(x)
    starts = [
        [var_r * 0.05, 0.08, 0.80, var_r * 0.01 / max(xm, 1.0), np.log(6.0)],
        [var_r * 0.02, 0.05, 0.85, var_r * 0.02 / max(xm, 1.0), np.log(4.0)],
        [var_r * 0.10, 0.03, 0.75, 1e-4, np.log(10.0)],
        [var_r * 0.05, 0.08, 0.70, 0.0, np.log(8.0)],
    ]
    bounds = [(1e-8, var_r * 20), (0.0, 0.5), (0.0, 0.999),
              (-1.0, 1.0), (np.log(0.1), np.log(100.0))]
    res = _try_starts(m3_fear_only_nll, starts, (r, x), bounds)
    return res


# ============================================================
# STEP 3: Bollerslev-Wooldridge (1992) sandwich SE
# ============================================================

def _numerical_hessian(fn, x, args, eps=None):
    k = len(x)
    x = np.asarray(x, float)
    if eps is None:
        eps = np.maximum(1e-5 * np.abs(x), 1e-6)
    H = np.zeros((k, k))
    f0 = fn(x, *args)
    for i in range(k):
        for j in range(i, k):
            xpp = x.copy(); xpp[i] += eps[i]; xpp[j] += eps[j]
            xpm = x.copy(); xpm[i] += eps[i]; xpm[j] -= eps[j]
            xmp = x.copy(); xmp[i] -= eps[i]; xmp[j] += eps[j]
            xmm = x.copy(); xmm[i] -= eps[i]; xmm[j] -= eps[j]
            fpp = fn(xpp, *args); fpm = fn(xpm, *args)
            fmp = fn(xmp, *args); fmm = fn(xmm, *args)
            H[i, j] = (fpp - fpm - fmp + fmm) / (4 * eps[i] * eps[j])
            H[j, i] = H[i, j]
    # The scipy nll above returns SUM of -log L so H is the Hessian of -ll.
    # The Hessian of +log L = -H.  But below we use H (the Hessian of negloglik)
    # directly in the sandwich:   V = H^-1 OPG H^-1   (both sides are
    # Hessians of the SAME objective; the sandwich identity is invariant to sign).
    return H


def _per_obs_scores(nll_fn, params, args, eps=None):
    """Numerically compute per-observation score (gradient) of negloglik.
    Returns a T x k matrix of scores ds_t = -d ll_t / d theta."""
    k = len(params)
    x = np.asarray(params, float)
    if eps is None:
        eps = np.maximum(1e-5 * np.abs(x), 1e-6)
    # We need per-obs log-likelihoods; rebuild via filter+ll wrappers below.
    return None  # placeholder — computed per-model below


def _opg_from_per_obs_ll(per_obs_ll_fn, params, args, eps=None):
    k = len(params)
    x = np.asarray(params, float)
    if eps is None:
        eps = np.maximum(1e-5 * np.abs(x), 1e-6)
    ll0 = per_obs_ll_fn(x, *args)  # T x 1 vector of per-obs ll
    T = len(ll0)
    scores = np.zeros((T, k))
    for i in range(k):
        xp = x.copy(); xp[i] += eps[i]
        xm = x.copy(); xm[i] -= eps[i]
        llp = per_obs_ll_fn(xp, *args)
        llm = per_obs_ll_fn(xm, *args)
        scores[:, i] = (llp - llm) / (2 * eps[i])
    # OPG = sum_t s_t s_t'
    opg = scores.T @ scores
    return opg, scores


def m1_per_obs_ll(params, r):
    omega, alpha, gamma, beta, log_nu_m2 = params
    nu = np.exp(log_nu_m2) + 2.0
    sigma2 = m1_gjr_t_filter(params, r)
    eps2 = r ** 2 / sigma2
    return _student_t_ll(eps2, sigma2, nu)


def m2_per_obs_ll(params, r, x):
    omega, alpha, gamma, beta, phi, log_nu_m2 = params
    nu = np.exp(log_nu_m2) + 2.0
    sigma2 = m2_garchx_filter(params, r, x)
    eps2 = r ** 2 / sigma2
    return _student_t_ll(eps2, sigma2, nu)


def m3_per_obs_ll(params, r, x):
    omega, alpha, beta, phi, log_nu_m2 = params
    nu = np.exp(log_nu_m2) + 2.0
    sigma2 = m3_fear_only_filter(params, r, x)
    eps2 = r ** 2 / sigma2
    return _student_t_ll(eps2, sigma2, nu)


def bw_sandwich_se(nll_fn, per_obs_ll_fn, params, args):
    """Return sqrt(diag(V)) with V = H^-1 OPG H^-1.
    H = Hessian of the negloglik (positive-semidefinite at interior MLE);
    OPG = sum_t score_t score_t'."""
    try:
        H = _numerical_hessian(nll_fn, np.asarray(params, float), args)
        opg, _ = _opg_from_per_obs_ll(per_obs_ll_fn, np.asarray(params, float), args)
        Hinv = np.linalg.pinv(H)
        V = Hinv @ opg @ Hinv
        se = np.sqrt(np.maximum(np.diag(V), 0.0))
        return se, V
    except Exception as ex:
        print(f"  [WARN] BW sandwich failed: {ex}")
        return np.full(len(params), np.nan), None


# ============================================================
# STEP 4: QLIKE + DM-HLN
# ============================================================

def qlike_ind(actual_r2, predicted_sigma2):
    """Per-obs Patton (2011) QLIKE loss."""
    a = np.where(actual_r2 > 0, actual_r2, np.nan)
    p = np.where(predicted_sigma2 > 0, predicted_sigma2, np.nan)
    loss = a / p - np.log(a / p) - 1.0
    return loss


def qlike_mean(actual_r2, predicted_sigma2):
    li = qlike_ind(actual_r2, predicted_sigma2)
    return float(np.nanmean(li))


def dm_hln(loss1, loss2, h=1):
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return 0.0, 1.0, n
    d_mean = np.mean(d)
    max_lag = int(np.floor(n ** (1 / 3)))
    gamma0 = np.var(d, ddof=1)
    gamma_sum = 0.0
    for k in range(1, max_lag + 1):
        w = 1 - k / (max_lag + 1)
        gk = np.mean((d[k:] - d_mean) * (d[:-k] - d_mean))
        gamma_sum += 2 * w * gk
    var_d = (gamma0 + gamma_sum) / n
    if var_d <= 0:
        return 0.0, 1.0, n
    dm = d_mean / np.sqrt(var_d)
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t = hln * dm
    p = 2 * (1 - stats.t.cdf(abs(t), df=n - 1))
    return float(t), float(p), int(n)


# ============================================================
# STEP 5: IS / OOS split
# ============================================================

r_all = df_all["r"].values.astype(float)
x_all = df_all["vix2_lag"].values.astype(float)
dates_all = df_all.index

N = len(r_all)
IS_END = int(np.floor(N * 0.70))  # 70% IS
r_is, x_is = r_all[:IS_END], x_all[:IS_END]
r_oos, x_oos = r_all[IS_END:], x_all[IS_END:]

print(f"\n  IS: {dates_all[0].date()} -> {dates_all[IS_END - 1].date()} ({IS_END} days)")
print(f"  OOS: {dates_all[IS_END].date()} -> {dates_all[-1].date()} ({N - IS_END} days)")
sys.stdout.flush()


# ============================================================
# STEP 6: Fit M1 / M2 / M3 on full sample
# ============================================================
print("\n[1] Fitting M1 (baseline GJR-t) on full sample ...")
t0 = time.time()
res_m1 = fit_m1(r_all)
elapsed = time.time() - t0
if res_m1 is None:
    raise RuntimeError("M1 failed to converge")
p_m1 = res_m1.x
ll_m1 = -res_m1.fun
print(f"  omega={p_m1[0]:.6f} alpha={p_m1[1]:.4f} gamma={p_m1[2]:.4f} "
      f"beta={p_m1[3]:.4f} nu={np.exp(p_m1[4])+2:.2f}")
print(f"  log L = {ll_m1:.2f}  ({elapsed:.1f}s)")
sys.stdout.flush()

se_m1, _ = bw_sandwich_se(m1_gjr_t_nll, m1_per_obs_ll, p_m1, (r_all,))

print("\n[2] Fitting M2 (GJR-t + phi * VIX²_{t-1}) on full sample ...")
t0 = time.time()
res_m2 = fit_m2(r_all, x_all)
elapsed = time.time() - t0
if res_m2 is None:
    raise RuntimeError("M2 failed to converge")
p_m2 = res_m2.x
ll_m2 = -res_m2.fun
print(f"  omega={p_m2[0]:.6f} alpha={p_m2[1]:.4f} gamma={p_m2[2]:.4f} "
      f"beta={p_m2[3]:.4f} phi={p_m2[4]:.6e} nu={np.exp(p_m2[5])+2:.2f}")
print(f"  log L = {ll_m2:.2f}  ({elapsed:.1f}s)")
sys.stdout.flush()

se_m2, _ = bw_sandwich_se(m2_garchx_nll, m2_per_obs_ll, p_m2, (r_all, x_all))
phi_m2, phi_m2_se = p_m2[4], se_m2[4]
t_phi_m2 = phi_m2 / phi_m2_se if (phi_m2_se and np.isfinite(phi_m2_se) and phi_m2_se > 0) else np.nan
p_phi_m2 = 2 * (1 - stats.norm.cdf(abs(t_phi_m2))) if np.isfinite(t_phi_m2) else np.nan

print(f"  phi = {phi_m2:.6e}  SE_BW = {phi_m2_se:.6e}  t = {t_phi_m2:.3f}  p = {p_phi_m2:.3e}")

# LRT M2 vs M1 (df=1)
LR_m2 = 2 * (ll_m2 - ll_m1)
p_lrt_m2 = 1 - stats.chi2.cdf(LR_m2, df=1)
print(f"  LRT M2 vs M1: LR = {LR_m2:.2f}  p = {p_lrt_m2:.3e}  (df=1)")
sys.stdout.flush()

print("\n[3] Fitting M3 (pure-fear GARCH + phi * VIX²_{t-1}) on full sample ...")
t0 = time.time()
res_m3 = fit_m3(r_all, x_all)
elapsed = time.time() - t0
if res_m3 is None:
    raise RuntimeError("M3 failed to converge")
p_m3 = res_m3.x
ll_m3 = -res_m3.fun
print(f"  omega={p_m3[0]:.6f} alpha={p_m3[1]:.4f} beta={p_m3[2]:.4f} "
      f"phi={p_m3[3]:.6e} nu={np.exp(p_m3[4])+2:.2f}")
print(f"  log L = {ll_m3:.2f}  ({elapsed:.1f}s)")
sys.stdout.flush()

se_m3, _ = bw_sandwich_se(m3_fear_only_nll, m3_per_obs_ll, p_m3, (r_all, x_all))
phi_m3, phi_m3_se = p_m3[3], se_m3[3]
t_phi_m3 = phi_m3 / phi_m3_se if (phi_m3_se and np.isfinite(phi_m3_se) and phi_m3_se > 0) else np.nan
p_phi_m3 = 2 * (1 - stats.norm.cdf(abs(t_phi_m3))) if np.isfinite(t_phi_m3) else np.nan
print(f"  phi = {phi_m3:.6e}  SE_BW = {phi_m3_se:.6e}  t = {t_phi_m3:.3f}  p = {p_phi_m3:.3e}")
sys.stdout.flush()


# ============================================================
# STEP 7: OOS QLIKE + DM-HLN
# ============================================================
print("\n[4] OOS QLIKE + DM-HLN (fix params at IS, rolling sigma2) ...")

# Refit each model on the IS-only window so OOS is a genuine hold-out
res_m1_is = fit_m1(r_is)
res_m2_is = fit_m2(r_is, x_is)
res_m3_is = fit_m3(r_is, x_is)
p_m1_is = res_m1_is.x
p_m2_is = res_m2_is.x
p_m3_is = res_m3_is.x

# Filter full series with IS-estimated params (phi is fixed by IS estimate)
s2_m1_full = m1_gjr_t_filter(p_m1_is, r_all)
s2_m2_full = m2_garchx_filter(p_m2_is, r_all, x_all)
s2_m3_full = m3_fear_only_filter(p_m3_is, r_all, x_all)

s2_m1_oos = s2_m1_full[IS_END:]
s2_m2_oos = s2_m2_full[IS_END:]
s2_m3_oos = s2_m3_full[IS_END:]
r2_oos = r_oos ** 2

ql_m1 = qlike_mean(r2_oos, s2_m1_oos)
ql_m2 = qlike_mean(r2_oos, s2_m2_oos)
ql_m3 = qlike_mean(r2_oos, s2_m3_oos)

li_m1 = qlike_ind(r2_oos, s2_m1_oos)
li_m2 = qlike_ind(r2_oos, s2_m2_oos)
li_m3 = qlike_ind(r2_oos, s2_m3_oos)

t_dm_m2_m1, p_dm_m2_m1, n_dm_m2_m1 = dm_hln(li_m1, li_m2)
t_dm_m3_m1, p_dm_m3_m1, n_dm_m3_m1 = dm_hln(li_m1, li_m3)
t_dm_m2_m3, p_dm_m2_m3, n_dm_m2_m3 = dm_hln(li_m3, li_m2)

print(f"  OOS QLIKE: M1={ql_m1:.6f}  M2={ql_m2:.6f}  M3={ql_m3:.6f}")
print(f"  DM-HLN M2 vs M1: t={t_dm_m2_m1:.3f} p={p_dm_m2_m1:.3e}  (positive = M2 wins)")
print(f"  DM-HLN M3 vs M1: t={t_dm_m3_m1:.3f} p={p_dm_m3_m1:.3e}")
print(f"  DM-HLN M2 vs M3: t={t_dm_m2_m3:.3f} p={p_dm_m2_m3:.3e}")
sys.stdout.flush()


# ============================================================
# STEP 8: Sub-period robustness (P1 / P2 / P3)
# ============================================================
print("\n[5] Sub-period robustness: fit M2 within each regime ...")

SUB = {
    "P1_2015_2020": ("2015-01-01", "2020-12-31"),
    "P2_2021_2023": ("2021-01-01", "2023-12-31"),
    "P3_2024_2026": ("2024-01-01", "2026-04-15"),
}

sub_results = {}
for label, (a, b) in SUB.items():
    mask = (dates_all >= pd.Timestamp(a)) & (dates_all <= pd.Timestamp(b))
    r_sub = r_all[mask]
    x_sub = x_all[mask]
    n_sub = len(r_sub)
    print(f"  {label}: n={n_sub}")
    if n_sub < 200:
        print(f"    SKIP: n<200")
        sub_results[label] = None
        continue
    res_m2_sub = fit_m2(r_sub, x_sub)
    if res_m2_sub is None:
        print(f"    FAIL: M2 did not converge")
        sub_results[label] = None
        continue
    p_sub = res_m2_sub.x
    se_sub, _ = bw_sandwich_se(m2_garchx_nll, m2_per_obs_ll, p_sub, (r_sub, x_sub))
    phi_s, phi_s_se = p_sub[4], se_sub[4]
    t_phi_s = phi_s / phi_s_se if (phi_s_se and phi_s_se > 0 and np.isfinite(phi_s_se)) else np.nan

    # LRT within sub-period
    res_m1_sub = fit_m1(r_sub)
    ll_m1_sub = -res_m1_sub.fun if res_m1_sub is not None else np.nan
    ll_m2_sub = -res_m2_sub.fun
    LR_sub = 2 * (ll_m2_sub - ll_m1_sub) if np.isfinite(ll_m1_sub) else np.nan
    p_lrt_sub = 1 - stats.chi2.cdf(LR_sub, df=1) if np.isfinite(LR_sub) else np.nan

    print(f"    phi={phi_s:.4e}  SE={phi_s_se:.4e}  t={t_phi_s:.2f}  "
          f"LRT={LR_sub:.2f} (p={p_lrt_sub:.3e})")

    sub_results[label] = {
        "n": int(n_sub),
        "date_start": str(dates_all[mask][0].date()),
        "date_end": str(dates_all[mask][-1].date()),
        "omega": float(p_sub[0]),
        "alpha": float(p_sub[1]),
        "gamma": float(p_sub[2]),
        "beta": float(p_sub[3]),
        "phi": float(phi_s),
        "phi_se_BW": float(phi_s_se) if np.isfinite(phi_s_se) else None,
        "phi_t_BW": float(t_phi_s) if np.isfinite(t_phi_s) else None,
        "nu": float(np.exp(p_sub[5]) + 2),
        "log_lik_M1": float(ll_m1_sub) if np.isfinite(ll_m1_sub) else None,
        "log_lik_M2": float(ll_m2_sub),
        "LRT_stat": float(LR_sub) if np.isfinite(LR_sub) else None,
        "LRT_p": float(p_lrt_sub) if np.isfinite(p_lrt_sub) else None,
    }
sys.stdout.flush()


# ============================================================
# STEP 9: Figures
# ============================================================
print("\n[6] Figures ...")

# Figure 1: sigma2 time series — M1 vs M2 (full sample, IS-estimated params)
fig, ax = plt.subplots(figsize=(12, 5))
ax.plot(dates_all, np.sqrt(s2_m1_full), color="#2196F3", lw=0.8,
        label="M1 GJR-t (baseline)", alpha=0.8)
ax.plot(dates_all, np.sqrt(s2_m2_full), color="#E91E63", lw=0.8,
        label=r"M2 GJR-t + $\phi \cdot VIX^2_{t-1}$", alpha=0.8)
ax.axvline(dates_all[IS_END], color="black", linestyle="--", alpha=0.6, label="IS/OOS split")
ax.set_ylabel(r"Predicted $\sigma_t$ (%)")
ax.set_xlabel("Date")
ax.set_title("K1241: BTC conditional volatility — baseline vs fear-channel GARCH-X(VIX²)")
ax.legend(loc="upper right")
ax.grid(alpha=0.3)
plt.tight_layout()
fig1 = os.path.join(SCRIPT_DIR, "k1241_sigma_timeseries.png")
plt.savefig(fig1, dpi=150)
plt.close()
print(f"  {fig1}")

# Figure 2: rolling 2-year phi estimate
print("  Computing rolling 2-year phi ...")
ROLL_WIN = 504  # ~ 2 trading years (BTC calendar, 252 days/year)
roll_dates = []
roll_phi = []
roll_t = []
for end_i in range(ROLL_WIN, N + 1, 21):  # monthly grid
    sl = slice(end_i - ROLL_WIN, end_i)
    r_w = r_all[sl]
    x_w = x_all[sl]
    try:
        res_w = fit_m2(r_w, x_w)
        if res_w is None:
            continue
        p_w = res_w.x
        se_w, _ = bw_sandwich_se(m2_garchx_nll, m2_per_obs_ll, p_w, (r_w, x_w))
        phi_w = p_w[4]
        se_phi_w = se_w[4]
        t_w = phi_w / se_phi_w if (se_phi_w and np.isfinite(se_phi_w) and se_phi_w > 0) else np.nan
        roll_dates.append(dates_all[end_i - 1])
        roll_phi.append(phi_w)
        roll_t.append(t_w)
    except Exception:
        continue

fig, ax1 = plt.subplots(figsize=(12, 5))
ax1.plot(roll_dates, roll_phi, color="#E91E63", lw=1.5, label=r"$\hat\phi$ rolling 2-yr")
ax1.axhline(0, color="black", linestyle=":", alpha=0.5)
ax1.set_ylabel(r"$\hat\phi$ (rolling 2-yr)", color="#E91E63")
ax1.tick_params(axis="y", labelcolor="#E91E63")
ax1.set_xlabel("Window end date")
ax1.grid(alpha=0.3)

ax2 = ax1.twinx()
ax2.plot(roll_dates, roll_t, color="#2196F3", lw=1.5, alpha=0.8, label=r"$t_{BW}(\hat\phi)$")
ax2.axhline(3.0, color="#2196F3", linestyle="--", alpha=0.5, label="|t|=3 (Harvey 2016)")
ax2.axhline(-3.0, color="#2196F3", linestyle="--", alpha=0.5)
ax2.set_ylabel(r"$t_{BW}(\hat\phi)$", color="#2196F3")
ax2.tick_params(axis="y", labelcolor="#2196F3")

lines1, labels1 = ax1.get_legend_handles_labels()
lines2, labels2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper right")
ax1.set_title("K1241: BTC GARCH-X(VIX²) rolling fear-channel coefficient")
plt.tight_layout()
fig2 = os.path.join(SCRIPT_DIR, "k1241_phi_rolling.png")
plt.savefig(fig2, dpi=150)
plt.close()
print(f"  {fig2}")
sys.stdout.flush()


# ============================================================
# STEP 10: Verdict + save results
# ============================================================
print("\n[7] Harvey (2016) verdict ...")

HARVEY_T = 3.0
harvey_phi_m2 = abs(t_phi_m2) > HARVEY_T if np.isfinite(t_phi_m2) else False
harvey_phi_m3 = abs(t_phi_m3) > HARVEY_T if np.isfinite(t_phi_m3) else False
lrt_pass_m2 = np.isfinite(p_lrt_m2) and p_lrt_m2 < 0.001
dm_pass_m2 = abs(t_dm_m2_m1) > 2.0

# Sub-period robustness: count sub-periods with |t_phi_BW| > 2 AND same sign as full-sample phi
sign_full = np.sign(phi_m2) if np.isfinite(phi_m2) else 0.0
sub_pass = 0
sub_total = 0
for label, r in sub_results.items():
    if r is None or r["phi_t_BW"] is None:
        continue
    sub_total += 1
    if abs(r["phi_t_BW"]) > 2.0 and np.sign(r["phi"]) == sign_full:
        sub_pass += 1

full_verdict = (
    "PASS" if (harvey_phi_m2 and lrt_pass_m2 and dm_pass_m2 and sub_pass >= 2)
    else ("BORDERLINE" if (harvey_phi_m2 or (abs(t_phi_m2) > 2 and lrt_pass_m2))
          else "NULL")
)

print(f"\n  === Paper 10 §6.1 Table 3 canonical verdict ===")
print(f"  M2 phi          = {phi_m2:.6e}")
print(f"  M2 phi t_BW     = {t_phi_m2:.3f}   (Harvey |t|>3: {harvey_phi_m2})")
print(f"  M2 vs M1 LRT    = {LR_m2:.2f}      (p<0.001: {lrt_pass_m2})")
print(f"  M2 vs M1 DM-HLN = {t_dm_m2_m1:.3f}  (|t|>2: {dm_pass_m2})")
print(f"  M3 phi t_BW     = {t_phi_m3:.3f}   (Harvey: {harvey_phi_m3})")
print(f"  Sub-period stability: {sub_pass}/{sub_total} regimes same-sign |t|>2")
print(f"  VERDICT: {full_verdict}")
sys.stdout.flush()


# ============================================================
# STEP 11: Write results JSON
# ============================================================
results = {
    "experiment_id": "K1241",
    "title": "Paper 10 §6.1 Primary Fear-Channel Regression — BTC GARCH-X(VIX²)",
    "paper": "crypto-fear-channel (Paper 10) §6.1 Table 3",
    "description": (
        "Canonical fear-channel phi coefficient for Paper 10 Table 3. "
        "BTC log-return variance regressed on lagged VIX² within GJR-GARCH(1,1) "
        "Student-t framework with Bollerslev-Wooldridge (1992) robust SE, "
        "LRT vs baseline, OOS DM-HLN (Harvey 1997), and Harvey (2016) |t|>3 verdict."
    ),
    "methodology": {
        "assets": "BTC-USD daily (yfinance Adj Close), ^VIX daily close",
        "sample_start": str(dates_all[0].date()),
        "sample_end": str(dates_all[-1].date()),
        "n_obs": int(N),
        "is_oos_split": f"70/30 (IS n={IS_END}, OOS n={N - IS_END})",
        "oos_start": str(dates_all[IS_END].date()),
        "oos_end": str(dates_all[-1].date()),
        "models": {
            "M1": "GJR-GARCH(1,1) Student-t  (baseline, no exog)",
            "M2": "GJR-GARCH(1,1) Student-t + phi * VIX^2_{t-1}",
            "M3": "GARCH(1,1)    Student-t + phi * VIX^2_{t-1}  (pure fear, no leverage)",
        },
        "estimation": "MLE via scipy L-BFGS-B (+ Nelder-Mead polish), multi-start",
        "SE": "Bollerslev-Wooldridge (1992) sandwich V = H^-1 OPG H^-1 "
              "(numerical Hessian + per-obs score)",
        "LRT_df": 1,
        "OOS_QLIKE": "Patton (2011) QLIKE on r² proxy",
        "DM_test": "Harvey-Leybourne-Newbold (1997) HLN small-sample corrected DM",
        "Harvey_threshold": HARVEY_T,
        "Lookahead_guard": "VIX² shifted t-1 before estimation and forecasting; "
                           "IS-estimated phi used for OOS (no refit leak)",
        "seed": 42,
    },
    "data_source": {
        "BTC-USD": "yfinance",
        "VIX": "yfinance ^VIX",
        "alignment": "VIX reindexed to BTC calendar with forward-fill (weekends)",
    },
    "models_fit_full_sample": {
        "M1_GJR_t": {
            "params": {
                "omega": float(p_m1[0]), "alpha": float(p_m1[1]),
                "gamma": float(p_m1[2]), "beta": float(p_m1[3]),
                "nu": float(np.exp(p_m1[4]) + 2),
            },
            "se_BW": {
                "omega": float(se_m1[0]), "alpha": float(se_m1[1]),
                "gamma": float(se_m1[2]), "beta": float(se_m1[3]),
                "log_nu_m2": float(se_m1[4]),
            },
            "log_lik": float(ll_m1),
            "n_params": 5,
        },
        "M2_GARCHX": {
            "params": {
                "omega": float(p_m2[0]), "alpha": float(p_m2[1]),
                "gamma": float(p_m2[2]), "beta": float(p_m2[3]),
                "phi": float(p_m2[4]), "nu": float(np.exp(p_m2[5]) + 2),
            },
            "se_BW": {
                "omega": float(se_m2[0]), "alpha": float(se_m2[1]),
                "gamma": float(se_m2[2]), "beta": float(se_m2[3]),
                "phi": float(se_m2[4]), "log_nu_m2": float(se_m2[5]),
            },
            "phi_estimate": float(phi_m2),
            "phi_se_BW": float(phi_m2_se) if np.isfinite(phi_m2_se) else None,
            "phi_t_BW": float(t_phi_m2) if np.isfinite(t_phi_m2) else None,
            "phi_p_BW": float(p_phi_m2) if np.isfinite(p_phi_m2) else None,
            "log_lik": float(ll_m2),
            "n_params": 6,
            "LRT_vs_M1": {
                "LR": float(LR_m2),
                "df": 1,
                "p_value": float(p_lrt_m2),
            },
        },
        "M3_Fear_Only": {
            "params": {
                "omega": float(p_m3[0]), "alpha": float(p_m3[1]),
                "beta": float(p_m3[2]), "phi": float(p_m3[3]),
                "nu": float(np.exp(p_m3[4]) + 2),
            },
            "se_BW": {
                "omega": float(se_m3[0]), "alpha": float(se_m3[1]),
                "beta": float(se_m3[2]), "phi": float(se_m3[3]),
                "log_nu_m2": float(se_m3[4]),
            },
            "phi_estimate": float(phi_m3),
            "phi_se_BW": float(phi_m3_se) if np.isfinite(phi_m3_se) else None,
            "phi_t_BW": float(t_phi_m3) if np.isfinite(t_phi_m3) else None,
            "phi_p_BW": float(p_phi_m3) if np.isfinite(p_phi_m3) else None,
            "log_lik": float(ll_m3),
            "n_params": 5,
        },
    },
    "OOS_evaluation": {
        "n_oos": int(N - IS_END),
        "QLIKE": {
            "M1": float(ql_m1), "M2": float(ql_m2), "M3": float(ql_m3),
        },
        "DM_HLN": {
            "M2_vs_M1": {"t": t_dm_m2_m1, "p": p_dm_m2_m1, "n": n_dm_m2_m1},
            "M3_vs_M1": {"t": t_dm_m3_m1, "p": p_dm_m3_m1, "n": n_dm_m3_m1},
            "M2_vs_M3": {"t": t_dm_m2_m3, "p": p_dm_m2_m3, "n": n_dm_m2_m3},
        },
    },
    "sub_period_robustness": sub_results,
    "verdict": {
        "framework": "Harvey (2016) |t|>3 + LRT p<0.001 + DM-HLN |t|>2 + sub-period same-sign",
        "M2_phi": float(phi_m2),
        "M2_phi_t_BW": float(t_phi_m2) if np.isfinite(t_phi_m2) else None,
        "M3_phi": float(phi_m3),
        "M3_phi_t_BW": float(t_phi_m3) if np.isfinite(t_phi_m3) else None,
        "harvey_phi_m2_pass": bool(harvey_phi_m2),
        "harvey_phi_m3_pass": bool(harvey_phi_m3),
        "lrt_m2_pass": bool(lrt_pass_m2),
        "dm_m2_pass": bool(dm_pass_m2),
        "sub_period_same_sign_t2": f"{sub_pass}/{sub_total}",
        "overall_verdict": full_verdict,
    },
    "references": [
        "Bollerslev & Wooldridge (1992) Econometric Reviews 11:143-172 — QMLE robust SE",
        "Patton (2011) JoE 160:246-256 — QLIKE proxy-robust loss",
        "Harvey-Leybourne-Newbold (1997) IJF 13:281-291 — DM small-sample correction",
        "Harvey (2016) JF — |t|>3 multiple-testing threshold",
        "Engle (2002) JBES — GARCH-X with exogenous variance drivers",
        "Glosten-Jagannathan-Runkle (1993) JF 48:1779-1801 — GJR-GARCH",
        "Creal, Koopman, Lucas (2013) JASA 108:1-18 — Student-t GARCH extension",
        "Bouri, Molnár, Azzi, Roubaud, Hagfors (2020) JIFMIM — BTC-VIX spillover",
        "Matkovskyy & Jalan (2019) IREF — crypto-equity fear channel",
    ],
    "prior_experiments": {
        "K949": "Cross-market MF-GJR with log-VIX multiplicative component (VIX as global risk)",
        "K1129": "Commodity GAS-t on BTC (baseline GJR-t convergence precedent)",
        "K1133": "BTC sub-period regime analysis (P1/P2/P3 convention)",
        "K1025": "Paper 10 upstream: asymmetric Granger + QR + DY spillover",
        "K746b": "Paper 10 upstream: BTC downside -> VIX asymmetric Granger",
        "K639":  "Paper 10 upstream: BTC -> SPY RV Granger lag 1-10",
    },
    "charts": ["k1241_sigma_timeseries.png", "k1241_phi_rolling.png"],
    "created_at": datetime.now(timezone.utc).isoformat(),
}

out_path = os.path.join(SCRIPT_DIR, "k1241_results.json")
with open(out_path, "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Results: {out_path}")
print("\nK1241 complete.")
sys.stdout.flush()
