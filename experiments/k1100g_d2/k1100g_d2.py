"""
K1100g_d2 — OOS validation of night→day predictive power in TAIFEX PRG
=======================================================================

Parent:
  K1100g_d1 found in-sample LRT chi2=12.48, p=0.0004 for M4 (day + night exog)
  vs M2 (day only). Paper 3 reframe anchor: "night carries asymmetric
  predictive information for day". But in-sample fit is not OOS — reviewers
  will ask whether the signal generalizes out-of-sample.

Motivation:
  Validate the in-sample finding with strict expanding-window OOS:
    Train: 2017-01-01 ~ 2019-12-31 (3 years initial)
    Test:  2020-01-01 ~ 2021-12-31 (2 years; expanding refit)

  Two models compared:
    M_null (baseline):  Day-only PRG (K1100g_d1 M2)
    M_full:             Day + contemporaneous night r^2 exog (K1100g_d1 M4)

Hypotheses:
  H1 (Primary):   OOS LRT chi2 > 7.88 (p<0.005, stricter than in-sample)
  H2 (Robustness): OOS DM HLN |t| > 2 (directional confirmation)
  H3 (Magnitude): OOS QLIKE improvement > 1% (meaningful effect size)
  H4 (Sub-period): 2020 (COVID) AND 2021 (recovery) each separately pass H3
                   (effect is not single-event driven)

Data: TAIFEX TX 2017-2021 — reuses K1100g_d1's session-level cache
      (raw-tick rebuild; do NOT use K1100g parquet cache mask-bug data).

Evaluation: one-step-ahead variance forecast, QLIKE loss, DM-HLN t-stat,
            LRT on cumulative OOS loglik.

Refit policy: expanding window, refit every REFIT_EVERY days (default 5).
              Between refits, parameters are held fixed (standard OOS
              convention), but exogenous input (night[t]^2) changes daily.
              Information set at forecast time t: all data up to t-1 for
              refit, night[t] is legally in the info set at t-open since
              night_t ends 05:00 < day_t opens 08:45.

Seed: 42
Author: Claude (worktree agent-k1100g-d2)
Date: 2026-04-13
"""
from __future__ import annotations

import json
import time
import warnings
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import optimize
from scipy.stats import norm, chi2

warnings.filterwarnings("ignore")
np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
SESSIONS_CACHE = DATA_DIR / "_cache_taifex_sessions_2017-2021.parquet"
RESULTS_PATH = SCRIPT_DIR / "k1100g_d2_results.json"
OOS_CSV_PATH = SCRIPT_DIR / "firm_oos_decomposition.csv"

# Train / test split dates
TRAIN_START = pd.Timestamp("2017-01-01")
TRAIN_END = pd.Timestamp("2019-12-31")  # initial fit uses data thru this date
TEST_START = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2021-12-31")

# Expanding-window refit frequency (business days between refits).
# 5 days = weekly refit. Keeps compute tractable; each refit uses ALL data
# from TRAIN_START up to the most recent known day.
REFIT_EVERY = 5


# ----------------------------------------------------------------------
# 1. PRG kernel (copied verbatim from K1100g_d1)
# ----------------------------------------------------------------------
def make_dow_dummies(dow: np.ndarray) -> np.ndarray:
    N = len(dow)
    X = np.zeros((N, 4), dtype=float)
    for k, d in enumerate((1, 2, 3, 4)):
        X[:, k] = (dow == d).astype(float)
    return X


def prg_nll(params: np.ndarray, r: np.ndarray, dow_dum: np.ndarray,
            exog: np.ndarray = None, exog_contemp: bool = False) -> float:
    """Same spec as K1100g_d1: tau*g multiplicative, E[g]=1 identification."""
    theta0, theta1, d1, d2, d3, d4, alpha, gamma, beta = params[:9]
    xn = params[9] if len(params) > 9 else 0.0

    if (theta0 <= 0 or theta1 < 0 or alpha < 0 or gamma < 0 or beta < 0
            or alpha + 0.5 * gamma + beta >= 0.999):
        return 1e10
    omega = 1.0 - alpha - 0.5 * gamma - beta
    if omega <= 0:
        return 1e10

    N = len(r)
    tau = np.zeros(N)
    g = np.zeros(N)
    h = np.zeros(N)

    uncond = float(np.mean(r * r))
    tau[0] = max(uncond, 1e-10)
    g[0] = 1.0
    h[0] = tau[0] * g[0]

    for t in range(1, N):
        x2_lag = r[t - 1] * r[t - 1]
        dow_term = (d1 * dow_dum[t, 0] + d2 * dow_dum[t, 1]
                    + d3 * dow_dum[t, 2] + d4 * dow_dum[t, 3])
        if exog is not None:
            exog_val = exog[t] if exog_contemp else exog[t - 1]
            exog_term = xn * exog_val
        else:
            exog_term = 0.0
        tau[t] = theta0 + theta1 * x2_lag + dow_term + exog_term
        if tau[t] <= 1e-10:
            return 1e10

        u_lag = r[t - 1] / np.sqrt(max(tau[t - 1], 1e-10))
        u2_lag = u_lag * u_lag
        neg_ind = 1.0 if r[t - 1] < 0 else 0.0
        g[t] = omega + alpha * u2_lag + gamma * u2_lag * neg_ind + beta * g[t - 1]
        if g[t] <= 1e-10:
            return 1e10
        h[t] = tau[t] * g[t]
        if h[t] <= 1e-10:
            return 1e10

    valid = slice(1, N)
    nll = 0.5 * np.sum(np.log(2 * np.pi * h[valid]) + r[valid] ** 2 / h[valid])
    if not np.isfinite(nll):
        return 1e10
    return float(nll)


def fit_prg(r: np.ndarray, dow_dum: np.ndarray, exog: np.ndarray = None,
            exog_contemp: bool = False, n_restarts: int = 6,
            x0_warm: np.ndarray = None) -> Dict:
    """Fit PRG via L-BFGS-B.
    If x0_warm provided (from previous refit), use it as first start to
    accelerate convergence (common in expanding-window OOS)."""
    r = np.asarray(r, dtype=float)
    use_exog = exog is not None

    local_rng = np.random.default_rng(42)
    best = {"nll": np.inf, "params": None, "success": False}

    for trial in range(n_restarts):
        uncond = float(np.var(r, ddof=1))
        if trial == 0 and x0_warm is not None:
            x0 = x0_warm.copy()
            # Ensure correct dimension for this fit (exog vs not)
            if use_exog and len(x0) == 9:
                x0 = np.concatenate([x0, [0.0]])
            elif not use_exog and len(x0) == 10:
                x0 = x0[:9]
        elif trial == 0:
            x0 = np.array([uncond * 0.5, 0.05, 0.0, 0.0, 0.0, 0.0,
                           0.05, 0.05, 0.80])
            if use_exog:
                x0 = np.concatenate([x0, [0.0]])
        else:
            x0 = np.array([
                uncond * (0.3 + 0.4 * local_rng.random()),
                0.02 + 0.06 * local_rng.random(),
                uncond * 0.01 * (local_rng.random() - 0.5),
                uncond * 0.01 * (local_rng.random() - 0.5),
                uncond * 0.01 * (local_rng.random() - 0.5),
                uncond * 0.01 * (local_rng.random() - 0.5),
                0.02 + 0.08 * local_rng.random(),
                0.02 + 0.08 * local_rng.random(),
                0.70 + 0.20 * local_rng.random(),
            ])
            if use_exog:
                x0 = np.concatenate([x0, [0.3 * (local_rng.random() - 0.5)]])

        bounds = [
            (1e-8, None), (0.0, 1.0),
            (None, None), (None, None), (None, None), (None, None),
            (0.0, 0.4), (0.0, 0.4), (0.0, 0.9999),
        ]
        if use_exog:
            bounds.append((None, None))

        try:
            res = optimize.minimize(
                prg_nll, x0,
                args=(r, dow_dum, exog, exog_contemp),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 400, "ftol": 1e-8},
            )
            if res.success and res.fun < best["nll"]:
                best = {"nll": float(res.fun), "params": res.x.copy(),
                        "success": True, "trial": trial}
        except Exception:
            continue

    return best


def prg_variance_path(params, r: np.ndarray, dow_dum: np.ndarray,
                      exog: np.ndarray = None,
                      exog_contemp: bool = False) -> np.ndarray:
    """Compute in-sample h_t path given fitted params."""
    if params is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    theta0, theta1, d1, d2, d3, d4, alpha, gamma, beta = params[:9]
    xn = params[9] if len(params) > 9 else 0.0
    omega = 1.0 - alpha - 0.5 * gamma - beta
    N = len(r)
    uncond = float(np.mean(r * r))
    tau = np.zeros(N)
    g = np.zeros(N)
    h = np.zeros(N)

    tau[0] = max(uncond, 1e-10)
    g[0] = 1.0
    h[0] = tau[0] * g[0]

    for t in range(1, N):
        x2_lag = r[t - 1] * r[t - 1]
        dow_term = (d1 * dow_dum[t, 0] + d2 * dow_dum[t, 1]
                    + d3 * dow_dum[t, 2] + d4 * dow_dum[t, 3])
        if exog is not None:
            exog_val = exog[t] if exog_contemp else exog[t - 1]
            exog_term = xn * exog_val
        else:
            exog_term = 0.0
        tau[t] = max(theta0 + theta1 * x2_lag + dow_term + exog_term, 1e-10)
        u_lag = r[t - 1] / np.sqrt(max(tau[t - 1], 1e-10))
        u2_lag = u_lag * u_lag
        neg_ind = 1.0 if r[t - 1] < 0 else 0.0
        g[t] = max(omega + alpha * u2_lag + gamma * u2_lag * neg_ind
                   + beta * g[t - 1], 1e-10)
        h[t] = tau[t] * g[t]
    return h


# ----------------------------------------------------------------------
# 2. Evaluation utilities
# ----------------------------------------------------------------------
def qlike_loss(h_hat: np.ndarray, r2: np.ndarray) -> np.ndarray:
    eps = 1e-10
    ratio = r2 / np.maximum(h_hat, eps)
    return ratio - np.log(np.maximum(ratio, eps)) - 1.0


def gaussian_loglik_per_obs(h_hat: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Per-observation Gaussian QML log-likelihood: -0.5*(log(2pi*h)+r^2/h)."""
    eps = 1e-12
    h = np.maximum(h_hat, eps)
    return -0.5 * (np.log(2 * np.pi * h) + r * r / h)


def dm_test_hln(loss1: np.ndarray, loss2: np.ndarray) -> Tuple[float, float]:
    """DM with HLN small-sample correction. Positive t = loss1 > loss2
    (model 2 is better)."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    if len(d) < 20:
        return np.nan, np.nan
    n = len(d)
    d_bar = float(np.mean(d))
    lag = int(np.floor(n ** (1 / 3)))
    dev = d - d_bar
    gamma0 = float(np.mean(dev * dev))
    s = gamma0
    for k in range(1, lag + 1):
        g = float(np.mean(dev[k:] * dev[:-k]))
        w = 1.0 - k / (lag + 1)
        s += 2 * w * g
    if s <= 0:
        return np.nan, np.nan
    se = np.sqrt(s / n)
    t = d_bar / se
    if n > lag + 1:
        correction = np.sqrt((n + 1 - 2 * lag + lag * (lag - 1) / n) / n)
        t_hln = t * correction
    else:
        t_hln = t
    p = 2 * (1 - norm.cdf(abs(t_hln)))
    return float(t_hln), float(p)


def lrt_chi2(ll_restricted_sum: float, ll_full_sum: float,
             dof: int = 1) -> Tuple[float, float]:
    """LRT on sum of OOS per-obs log-likelihoods. Under nested models
    with consistent params, 2*(LL_full - LL_restricted) ~ chi2(dof)
    asymptotically. For OOS we interpret this as a comparative test rather
    than a strict LR, but is the accepted analogue for OOS model selection
    in the volatility literature (e.g., Engle 2002)."""
    if ll_restricted_sum is None or ll_full_sum is None:
        return np.nan, np.nan
    lr = 2.0 * (ll_full_sum - ll_restricted_sum)
    if lr < 0:
        lr = 0.0
    p = 1.0 - chi2.cdf(lr, df=dof)
    return float(lr), float(p)


def clean_for_json(obj):
    if isinstance(obj, dict):
        return {k: clean_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_for_json(v) for v in obj]
    if isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return None
        return obj
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, np.ndarray):
        return clean_for_json(obj.tolist())
    return obj


# ----------------------------------------------------------------------
# 3. One-step-ahead OOS forecast with expanding refit
# ----------------------------------------------------------------------
def expanding_oos_forecast(r_day: np.ndarray, dow_dum: np.ndarray,
                           r_night2: np.ndarray,
                           test_start_idx: int,
                           use_exog: bool,
                           refit_every: int = REFIT_EVERY) -> Dict:
    """Run expanding-window OOS forecast.

    Parameters
    ----------
    r_day : array (N,)    - day session log returns (target)
    dow_dum : array (N,4) - dow dummies
    r_night2 : array (N,) - r_night^2 (exog for M_full; legal contemp since
                             night[t] ends before day[t] opens)
    test_start_idx : int  - first index in test set
    use_exog : bool       - True for M_full (M4-style), False for M_null (M2-style)
    refit_every : int     - refit frequency (business days)

    Returns
    -------
    dict with:
      h_oos       - array of one-step-ahead variance forecasts (len N)
      h_oos has valid values for t >= test_start_idx
      params_log  - list of (idx, params) tuples at each refit

    CRITICAL: at each forecast day t in test period, parameters come from
    fit using data [0:t] only (strictly pre-t). No peek at r_day[t] in fit.
    Exog r_night[t]^2 IS used at forecast time — justified because
    night_t ends 05:00 before day_t opens 08:45 (information set legal).
    """
    N = len(r_day)
    h_oos = np.full(N, np.nan)
    params_log = []

    # Initial fit on training data [0 : test_start_idx]
    current_params = None

    for t in range(test_start_idx, N):
        # Refit policy: refit at t when (t - test_start_idx) % refit_every == 0
        # Uses data [0:t] (strictly pre-t) => no lookahead
        steps_since_test_start = t - test_start_idx
        need_refit = (steps_since_test_start % refit_every == 0)

        if need_refit:
            r_train = r_day[:t]
            dow_train = dow_dum[:t]
            if use_exog:
                exog_train = r_night2[:t]
                fit = fit_prg(r_train, dow_train,
                              exog=exog_train, exog_contemp=True,
                              n_restarts=4,  # warm-start so fewer restarts
                              x0_warm=current_params)
            else:
                fit = fit_prg(r_train, dow_train,
                              exog=None, exog_contemp=False,
                              n_restarts=4,
                              x0_warm=current_params)
            if fit["success"]:
                current_params = fit["params"]
                params_log.append((int(t), current_params.tolist()))
            else:
                # Keep previous params if fit failed
                print(f"  [warn] refit failed at t={t}, keeping previous")

        if current_params is None:
            continue

        # One-step-ahead forecast for day t using data [0:t+1]
        # We compute h_path over [0:t+1], then h_oos[t] = h_path[t].
        # Because prg_variance_path recursion uses r[t-1] (past) and
        # exog[t] (if contemp, night_t which is legally observable),
        # this is a pure one-step forecast.
        r_slice = r_day[:t + 1]
        dow_slice = dow_dum[:t + 1]
        if use_exog:
            exog_slice = r_night2[:t + 1]
            h_path = prg_variance_path(current_params, r_slice, dow_slice,
                                       exog=exog_slice, exog_contemp=True)
        else:
            h_path = prg_variance_path(current_params, r_slice, dow_slice,
                                       exog=None, exog_contemp=False)
        h_oos[t] = h_path[t]

    return {
        "h_oos": h_oos,
        "params_log": params_log,
        "n_refits": len(params_log),
    }


# ----------------------------------------------------------------------
# 4. Main experiment
# ----------------------------------------------------------------------
def run():
    t0 = time.time()

    # ------------------------------------------------------------------
    # Load K1100g_d1's clean session cache
    # ------------------------------------------------------------------
    print(f"[{time.strftime('%H:%M:%S')}] Loading K1100g_d1 sessions cache...")
    if not SESSIONS_CACHE.exists():
        raise FileNotFoundError(
            f"Missing sessions cache: {SESSIONS_CACHE}\n"
            f"K1100g_d1 must have been run first."
        )
    df = pd.read_parquet(SESSIONS_CACHE)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    print(f"  Raw rows: {len(df)}")

    # Align: require day + night + combined all valid (same rule as K1100g_d1)
    mdf = df.dropna(subset=["r_day", "r_night", "r_combined"]).copy()
    mdf = mdf.reset_index(drop=True)
    N = len(mdf)
    print(f"  Aligned rows (r_day + r_night + r_combined valid): {N}")

    dates = mdf["date"].values
    dow_arr = mdf["dow"].values.astype(int)
    dow_dum = make_dow_dummies(dow_arr)
    r_day = mdf["r_day"].values.astype(float)
    r_night = mdf["r_night"].values.astype(float)
    r_night2 = r_night ** 2

    # ------------------------------------------------------------------
    # Determine train/test split by DATE
    # ------------------------------------------------------------------
    dates_ts = pd.to_datetime(mdf["date"])
    train_mask = (dates_ts >= TRAIN_START) & (dates_ts <= TRAIN_END)
    test_mask = (dates_ts >= TEST_START) & (dates_ts <= TEST_END)

    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]
    if len(train_idx) == 0 or len(test_idx) == 0:
        raise RuntimeError("Empty train or test set")

    test_start_idx = int(test_idx[0])
    test_end_idx = int(test_idx[-1])
    print(f"  Train: [{train_idx[0]}, {train_idx[-1]}]"
          f"  ({dates_ts.iloc[train_idx[0]].date()} .. "
          f"{dates_ts.iloc[train_idx[-1]].date()})"
          f"  n={len(train_idx)}")
    print(f"  Test:  [{test_start_idx}, {test_end_idx}]"
          f"  ({dates_ts.iloc[test_start_idx].date()} .. "
          f"{dates_ts.iloc[test_end_idx].date()})"
          f"  n={len(test_idx)}")

    # ------------------------------------------------------------------
    # OOS forecasting — expanding window, refit every REFIT_EVERY days
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] M_null (day-only PRG) OOS...")
    t_start_null = time.time()
    oos_null = expanding_oos_forecast(
        r_day, dow_dum, r_night2,
        test_start_idx=test_start_idx,
        use_exog=False,
        refit_every=REFIT_EVERY,
    )
    print(f"  refits={oos_null['n_refits']}  "
          f"elapsed={time.time() - t_start_null:.1f}s")

    print(f"[{time.strftime('%H:%M:%S')}] M_full (day + night exog) OOS...")
    t_start_full = time.time()
    oos_full = expanding_oos_forecast(
        r_day, dow_dum, r_night2,
        test_start_idx=test_start_idx,
        use_exog=True,
        refit_every=REFIT_EVERY,
    )
    print(f"  refits={oos_full['n_refits']}  "
          f"elapsed={time.time() - t_start_full:.1f}s")

    # ------------------------------------------------------------------
    # Build OOS loss & loglik arrays
    # ------------------------------------------------------------------
    test_slice = slice(test_start_idx, test_end_idx + 1)
    r_day_test = r_day[test_slice]
    r2_day_test = r_day_test ** 2
    dates_test = dates_ts.iloc[test_slice].values
    h_null_test = oos_null["h_oos"][test_slice]
    h_full_test = oos_full["h_oos"][test_slice]

    # Filter out NaN rows (edge cases where fit failed, if any)
    valid = np.isfinite(h_null_test) & np.isfinite(h_full_test)
    n_valid = int(valid.sum())
    print(f"\n  OOS valid obs: {n_valid} / {len(h_null_test)}")
    if n_valid < 100:
        raise RuntimeError("Too few valid OOS obs")

    r_day_v = r_day_test[valid]
    r2_day_v = r2_day_test[valid]
    h_null_v = h_null_test[valid]
    h_full_v = h_full_test[valid]
    dates_v = pd.to_datetime(dates_test[valid])

    # QLIKE losses
    qlike_null = qlike_loss(h_null_v, r2_day_v)
    qlike_full = qlike_loss(h_full_v, r2_day_v)

    # Per-obs Gaussian log-lik
    ll_null_pd = gaussian_loglik_per_obs(h_null_v, r_day_v)
    ll_full_pd = gaussian_loglik_per_obs(h_full_v, r_day_v)

    # ------------------------------------------------------------------
    # H1: Primary — cumulative OOS LRT chi2 > 7.88 (p<0.005)
    # ------------------------------------------------------------------
    ll_null_sum = float(np.sum(ll_null_pd))
    ll_full_sum = float(np.sum(ll_full_pd))
    lrt_stat, lrt_p = lrt_chi2(ll_null_sum, ll_full_sum, dof=1)
    h1_pass = bool(np.isfinite(lrt_stat) and lrt_stat > 7.88)

    # ------------------------------------------------------------------
    # H2: Robustness — DM HLN |t| > 2
    # ------------------------------------------------------------------
    dm_t, dm_p = dm_test_hln(qlike_null, qlike_full)
    h2_pass = bool(np.isfinite(dm_t) and abs(dm_t) > 2.0)

    # ------------------------------------------------------------------
    # H3: Magnitude — QLIKE improvement > 1%
    # ------------------------------------------------------------------
    qlike_null_mean = float(np.mean(qlike_null))
    qlike_full_mean = float(np.mean(qlike_full))
    # Improvement = (null - full) / |null|  (positive = full better)
    qlike_improv_pct = (qlike_null_mean - qlike_full_mean) / abs(qlike_null_mean) * 100 \
        if qlike_null_mean != 0 else np.nan
    h3_pass = bool(np.isfinite(qlike_improv_pct) and qlike_improv_pct > 1.0)

    # ------------------------------------------------------------------
    # H4: Sub-period stability — 2020 vs 2021 each PASS H3
    # ------------------------------------------------------------------
    mask_2020 = (dates_v >= pd.Timestamp("2020-01-01")) & \
                (dates_v <= pd.Timestamp("2020-12-31"))
    mask_2021 = (dates_v >= pd.Timestamp("2021-01-01")) & \
                (dates_v <= pd.Timestamp("2021-12-31"))

    def subperiod_stats(mask):
        if mask.sum() < 30:
            return {"n": int(mask.sum()), "qlike_null_mean": None,
                    "qlike_full_mean": None, "qlike_improv_pct": None,
                    "lrt_chi2": None, "lrt_p": None,
                    "dm_t_hln": None, "dm_p": None, "pass_h3": False}
        qn = qlike_null[mask]
        qf = qlike_full[mask]
        lln = ll_null_pd[mask].sum()
        llf = ll_full_pd[mask].sum()
        lrts, lrtp = lrt_chi2(lln, llf, dof=1)
        dt, dp = dm_test_hln(qn, qf)
        qn_mean = float(np.mean(qn))
        qf_mean = float(np.mean(qf))
        imp = (qn_mean - qf_mean) / abs(qn_mean) * 100 if qn_mean != 0 else np.nan
        return {
            "n": int(mask.sum()),
            "qlike_null_mean": qn_mean, "qlike_full_mean": qf_mean,
            "qlike_improv_pct": float(imp) if np.isfinite(imp) else None,
            "lrt_chi2": float(lrts), "lrt_p": float(lrtp),
            "dm_t_hln": float(dt) if np.isfinite(dt) else None,
            "dm_p": float(dp) if np.isfinite(dp) else None,
            "pass_h3": bool(np.isfinite(imp) and imp > 1.0),
        }

    sub_2020 = subperiod_stats(mask_2020)
    sub_2021 = subperiod_stats(mask_2021)
    h4_pass = bool(sub_2020["pass_h3"] and sub_2021["pass_h3"])

    # ------------------------------------------------------------------
    # Cumulative LRT over test period (for chart)
    # ------------------------------------------------------------------
    ll_diff = ll_full_pd - ll_null_pd
    cum_lrt = 2.0 * np.cumsum(ll_diff)

    print(f"\n[{time.strftime('%H:%M:%S')}] Results summary:")
    print(f"  H1 OOS LRT:       chi2={lrt_stat:.3f}  p={lrt_p:.4g}   "
          f"pass={h1_pass}")
    print(f"  H2 DM-HLN:        t={dm_t:.3f}  p={dm_p:.4g}   pass={h2_pass}")
    print(f"  H3 QLIKE improv:  {qlike_improv_pct:+.2f}%     pass={h3_pass}")
    print(f"  H4 sub-period:    2020 improv={sub_2020['qlike_improv_pct']:+.2f}%"
          f"  2021 improv={sub_2021['qlike_improv_pct']:+.2f}%   pass={h4_pass}")

    # ------------------------------------------------------------------
    # Save CSV for inspection
    # ------------------------------------------------------------------
    oos_df = pd.DataFrame({
        "date": dates_v,
        "r_day": r_day_v,
        "r_day_sq": r2_day_v,
        "r_night_sq": r_night2[test_slice][valid],
        "h_null": h_null_v,
        "h_full": h_full_v,
        "qlike_null": qlike_null,
        "qlike_full": qlike_full,
        "ll_null": ll_null_pd,
        "ll_full": ll_full_pd,
        "cum_lrt_chi2": cum_lrt,
    })
    oos_df.to_csv(OOS_CSV_PATH, index=False)
    print(f"[OK] firm_oos_decomposition.csv ({len(oos_df)} rows)")

    # ------------------------------------------------------------------
    # JSON result
    # ------------------------------------------------------------------
    # Assemble Paper 3 verdict
    if h1_pass:
        verdict = "PASS — OOS-robust anchor confirmed"
    else:
        if qlike_improv_pct > 0:
            verdict = "PARTIAL — OOS direction correct but effect too weak; in-sample likely data mining"
        else:
            verdict = "FAIL — OOS worse than baseline; in-sample was data mining"

    result = {
        "experiment_id": "K1100g_d2",
        "title": "OOS validation of night->day predictive power in TAIFEX PRG",
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": 42,
        "design": {
            "train_start": str(TRAIN_START.date()),
            "train_end": str(TRAIN_END.date()),
            "test_start": str(TEST_START.date()),
            "test_end": str(TEST_END.date()),
            "refit_every": REFIT_EVERY,
            "refit_policy": "expanding_window_weekly",
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
            "n_test_valid": int(n_valid),
        },
        "data": {
            "source": "TAIFEX TX 2017-2021 via K1100g_d1 session cache (raw-tick rebuild)",
            "cache_file": str(SESSIONS_CACHE.name),
        },
        "models": {
            "M_null": "Day-only PRG (K1100g_d1 M2 spec)",
            "M_full": "Day + contemporaneous night_t^2 exog PRG (K1100g_d1 M4 spec)",
            "info_set": "night_t ends 05:00 < day_t opens 08:45 => legal contemporaneous info",
        },
        "oos_stats": {
            "n_obs": int(n_valid),
            "ll_null_sum": ll_null_sum,
            "ll_full_sum": ll_full_sum,
            "ll_diff_sum": float(ll_full_sum - ll_null_sum),
            "qlike_null_mean": qlike_null_mean,
            "qlike_full_mean": qlike_full_mean,
            "qlike_improv_pct": float(qlike_improv_pct) if np.isfinite(qlike_improv_pct) else None,
            "n_refits_null": int(oos_null["n_refits"]),
            "n_refits_full": int(oos_full["n_refits"]),
        },
        "tests": {
            "H1_oos_lrt_primary": {
                "chi2": float(lrt_stat) if np.isfinite(lrt_stat) else None,
                "p_value": float(lrt_p) if np.isfinite(lrt_p) else None,
                "dof": 1,
                "threshold_chi2": 7.88,
                "threshold_p": 0.005,
                "pass": h1_pass,
                "interpretation": (
                    "2*(LL_full - LL_null) on OOS loglik sums; "
                    "chi2>7.88 (p<0.005) required, stricter than in-sample 0.05 threshold"
                ),
            },
            "H2_dm_hln_robustness": {
                "t_stat": float(dm_t) if np.isfinite(dm_t) else None,
                "p_value": float(dm_p) if np.isfinite(dm_p) else None,
                "threshold_abs_t": 2.0,
                "pass": h2_pass,
                "interpretation": "DM HLN on QLIKE differential; t>0 means full>null",
            },
            "H3_qlike_magnitude": {
                "qlike_improv_pct": float(qlike_improv_pct) if np.isfinite(qlike_improv_pct) else None,
                "threshold_pct": 1.0,
                "pass": h3_pass,
                "interpretation": "Meaningful effect size > 1%",
            },
            "H4_subperiod_stability": {
                "sub_2020": sub_2020,
                "sub_2021": sub_2021,
                "pass": h4_pass,
                "interpretation": "Both 2020 (COVID) and 2021 (recovery) separately pass H3",
            },
        },
        "paper3_reframe_verdict": {
            "verdict": verdict,
            "all_four_pass": bool(h1_pass and h2_pass and h3_pass and h4_pass),
            "h1_pass": h1_pass, "h2_pass": h2_pass,
            "h3_pass": h3_pass, "h4_pass": h4_pass,
        },
        "limitations": [
            "N=2 years OOS is modest for asymptotic chi-square to be precise; "
            "2*(LL_diff) on OOS is an approximate rather than exact chi2.",
            "Single market (TAIFEX). Cross-market replication needed (SPY / N225 etc.) "
            "to establish 'Taiwan microstructure' claim.",
            "COVID 2020 is an atypical volatility regime; H4 sub-period stability check "
            "tests this explicitly.",
            "Active-contract selection at each file uses volume argmax; may cause "
            "contract-month-edge effects at rollover (Codex MED, unchanged from K1100g_d1).",
            "2020 early sample contains ~90 days with missing night session data "
            "(pre-dawn); aligned OOS excludes these.",
            "Refit frequency = 5 days (weekly). Daily refit would be more OOS-rigorous "
            "but >5x compute; robustness to this choice not tested here (candidate for d3).",
        ],
    }

    result = clean_for_json(result)
    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(f"[OK] results -> {RESULTS_PATH.name}")

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------
    plot_all(oos_df, lrt_stat, dm_t, qlike_improv_pct,
             sub_2020, sub_2021, verdict)

    print(f"\n[DONE] Total: {time.time() - t0:.1f}s")
    return result


# ----------------------------------------------------------------------
# 5. Plots
# ----------------------------------------------------------------------
def plot_all(oos_df: pd.DataFrame, lrt_stat: float, dm_t: float,
             qlike_improv_pct: float, sub_2020: dict, sub_2021: dict,
             verdict: str):
    # Plot 1: Cumulative OOS LRT chi2 over test period
    fig, ax = plt.subplots(figsize=(11, 4.8))
    ax.plot(oos_df["date"], oos_df["cum_lrt_chi2"], color="#1f77b4", lw=1.3,
            label="Cumulative 2*(LL_full - LL_null)")
    ax.axhline(7.88, color="#d62728", linestyle="--", alpha=0.75,
               label="chi2(1)=7.88 (p=0.005)")
    ax.axhline(3.84, color="#ff7f0e", linestyle=":", alpha=0.6,
               label="chi2(1)=3.84 (p=0.05)")
    ax.axhline(0, color="black", lw=0.7)
    ax.set_title(f"K1100g_d2 — Cumulative OOS LRT chi2 (final={lrt_stat:.2f})  "
                 f"{verdict}")
    ax.set_ylabel("Cumulative 2*(LL_full - LL_null)")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d2_oos_lrt_cumulative.png", dpi=120)
    plt.close()

    # Plot 2: QLIKE improvement time series
    fig, ax = plt.subplots(figsize=(11, 4.8))
    qlike_diff = oos_df["qlike_null"] - oos_df["qlike_full"]
    roll30 = qlike_diff.rolling(30, min_periods=10).mean()
    ax.plot(oos_df["date"], qlike_diff, color="#888", alpha=0.4, lw=0.6,
            label="Daily QLIKE diff (null - full)")
    ax.plot(oos_df["date"], roll30, color="#2ca02c", lw=1.6,
            label="30-day rolling mean")
    ax.axhline(0, color="black", lw=0.7)
    ax.set_title(f"OOS QLIKE improvement (null-full)  "
                 f"overall={qlike_improv_pct:+.2f}%  DM-HLN t={dm_t:.2f}")
    ax.set_ylabel("QLIKE_null - QLIKE_full (>0 => full better)")
    ax.legend(loc="best")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d2_qlike_improvement.png", dpi=120)
    plt.close()

    # Plot 3: 2020 vs 2021 side-by-side
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(13, 4.8))
    cats = ["QLIKE\nnull", "QLIKE\nfull", "Improv\n(%)"]

    vals_20 = [sub_2020.get("qlike_null_mean") or 0,
               sub_2020.get("qlike_full_mean") or 0,
               sub_2020.get("qlike_improv_pct") or 0]
    vals_21 = [sub_2021.get("qlike_null_mean") or 0,
               sub_2021.get("qlike_full_mean") or 0,
               sub_2021.get("qlike_improv_pct") or 0]

    # Left: raw QLIKE levels 2020 vs 2021
    x = np.arange(2)
    width = 0.35
    ax1.bar(x - width / 2,
            [sub_2020.get("qlike_null_mean") or 0,
             sub_2021.get("qlike_null_mean") or 0],
            width, label="M_null", color="#1f77b4", alpha=0.85)
    ax1.bar(x + width / 2,
            [sub_2020.get("qlike_full_mean") or 0,
             sub_2021.get("qlike_full_mean") or 0],
            width, label="M_full", color="#2ca02c", alpha=0.85)
    ax1.set_xticks(x)
    ax1.set_xticklabels([f"2020 (COVID)\nn={sub_2020['n']}",
                         f"2021 (recovery)\nn={sub_2021['n']}"])
    ax1.set_ylabel("Mean QLIKE (lower = better)")
    ax1.set_title("Sub-period QLIKE comparison")
    ax1.legend()
    ax1.grid(alpha=0.3, axis="y")

    # Right: improvement % + LRT chi2
    improv = [sub_2020.get("qlike_improv_pct") or 0,
              sub_2021.get("qlike_improv_pct") or 0]
    chi2s = [sub_2020.get("lrt_chi2") or 0,
             sub_2021.get("lrt_chi2") or 0]
    colors = ["#2ca02c" if v > 1 else ("#ff7f0e" if v > 0 else "#d62728")
              for v in improv]
    ax2b = ax2.twinx()
    bars = ax2.bar(x, improv, color=colors, alpha=0.85, width=0.4,
                   label="QLIKE improv %")
    ax2.axhline(1.0, color="#d62728", linestyle="--", alpha=0.7,
                label="threshold 1%")
    ax2.axhline(0, color="black", lw=0.7)
    for i, (v, c2) in enumerate(zip(improv, chi2s)):
        ax2.text(i, v, f"{v:+.2f}%\nchi2={c2:.2f}", ha="center",
                 va="bottom" if v >= 0 else "top", fontweight="bold",
                 fontsize=9)
    ax2.set_xticks(x)
    ax2.set_xticklabels(["2020", "2021"])
    ax2.set_ylabel("QLIKE improvement (%)")
    ax2.set_title("H3/H4 sub-period improvement + LRT chi2")
    ax2.legend(loc="best")
    ax2.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d2_covid_recovery_split.png", dpi=120)
    plt.close()

    print("[OK] 3 charts saved")


if __name__ == "__main__":
    run()
