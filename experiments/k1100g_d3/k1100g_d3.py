"""
K1100g_d3 — Student-t PRG fat-tail fix for K1100g_d1/d2
========================================================

Parent:
  - K1100g_d1 found in-sample LRT chi2=12.48, p=0.0004 for M4 (day + night exog)
    vs M2 (day only). Paper 3 reframe anchor.
  - K1100g_d2 OOS completely rejected: chi2=0.00, DM t=-0.21, QLIKE
    deteriorated 0.48% (SIGNAL REVERSED). In-sample was data mining.

Motivation:
  K1100g_d1 used Gaussian QML. TAIFEX daily returns exhibit heavy tails
  (typical excess kurtosis > 5). A key hypothesis: **Normal innovation
  under-accounts for fat tails, inflating the in-sample likelihood gain
  from adding night exog because M4 can abuse free parameters to soak up
  tail kurtosis rather than capture genuine predictive content.**

  If Student-t innovation handles fat tails naturally (via degrees-of-
  freedom parameter), the IS LRT may drop to a more reasonable level,
  AND the OOS predictive signal may emerge (if the effect was real but
  masked by Normal mis-specification).

Design — same PRG kernel as K1100g_d1 (M1-M5 mapping preserved):

  M1 Combined PRG:   target=r_combined^2          (no exog)
  M2 Day-only PRG:   target=r_day^2               (no exog)
  M3 Night-only PRG: target=r_night^2             (no exog)
  M4 Cross PRG:      target=r_day^2 | r_night[t]^2 contemporaneous
  M5 Reverse Cross:  target=r_night^2 | r_day[t-1]^2 lagged

  Each model is estimated under TWO innovation assumptions:
    (a) Normal (Gaussian QML) — replicating K1100g_d1 spec
    (b) Student-t — MLE with joint df (additional free parameter)

  PRG kernel (unchanged from K1100g_d1):
    tau_t = theta0 + theta1 * r[t-1]^2 + sum_k delta_k D_k,t [+ xn*exog]
    g_t   = omega + alpha*u^2_{t-1} + gamma*u^2_{t-1}*I(r<0) + beta*g_{t-1}
            with u_t = r_t / sqrt(tau_t)
    h_t   = tau_t * g_t
    omega = 1 - alpha - gamma/2 - beta  (identification: E[g]=1)

  Student-t density with scale sqrt((df-2)/df*h):
    r_t | F_{t-1} ~ t_df * sqrt((df-2)/df * h_t)
    sigma_t^2 = h_t  (conditional variance; requires df > 2)

Hypotheses:
  H1 (t saves):       Under Student-t, OOS LRT PASS (M4 vs M2 chi2 > 7.88)
                      AND OOS QLIKE improv > 1%
  H2 (t same):        Student-t gives same rejection (reinforces K1100g_d1
                      as data mining; Paper 3 reframe fully dead)
  H3 (subset):        IS LRT drops but OOS still fails (effect truly null;
                      Normal over-stated IS) — or IS LRT enhanced by t but
                      OOS insensitive (df mainly fits unconditional tails)

Evaluation:
  IS: LRT M4 vs M2 and M5 vs M3 under each innovation — compare statistics
  OOS: expanding-window refit (REFIT_EVERY=5) on Student-t M_null vs M_full
       same spec as K1100g_d2 — report chi2, DM-HLN, QLIKE improv
  VaR Trinity: Kupiec unconditional + Christoffersen CC on OOS 2020-2021
       at 1% and 5% using t_df quantiles with scale sqrt((df-2)/df*h)

Lookahead discipline:
  - Signal r_night[t]^2 is LEGAL because night_t ends 05:00 before day_t
    opens 08:45 (same info-set logic as K1100g_d1/d2).
  - No data modifications; seed=42; L-BFGS-B deterministic.

References:
  - Bollerslev (1987) "A Conditionally Heteroskedastic Time Series Model
    for Speculative Prices and Rates of Return", RESTAT — Student-t GARCH.
  - Engle & Rangel (2008) "The Spline-GARCH Model...", RFS — PRG/MIDAS
    multiplicative tau*g decomposition.
  - Kupiec (1995); Christoffersen (1998) — VaR backtests.
  - Harvey et al. (1997) — HLN small-sample DM correction.

Author: Claude (worktree agent-k1100g-d3)
Date: 2026-04-13
Seed: 42
"""
from __future__ import annotations

import json
import time
import warnings
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import optimize
from scipy.special import gammaln
from scipy.stats import norm, chi2, t as student_t, kurtosis as kurt_fn, skew as skew_fn

warnings.filterwarnings("ignore")
np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
SESSIONS_CACHE = DATA_DIR / "_cache_taifex_sessions_2017-2021.parquet"
RESULTS_PATH = SCRIPT_DIR / "k1100g_d3_results.json"

# Train/test split — identical to K1100g_d2 for apples-to-apples OOS comparison
TRAIN_START = pd.Timestamp("2017-01-01")
TRAIN_END = pd.Timestamp("2019-12-31")
TEST_START = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2021-12-31")
REFIT_EVERY = 5  # weekly expanding-window OOS refits


# ----------------------------------------------------------------------
# 1. PRG kernel — Normal AND Student-t innovation
# ----------------------------------------------------------------------
def make_dow_dummies(dow: np.ndarray) -> np.ndarray:
    N = len(dow)
    X = np.zeros((N, 4), dtype=float)
    for k, d in enumerate((1, 2, 3, 4)):
        X[:, k] = (dow == d).astype(float)
    return X


def _prg_variance_recursion(params: np.ndarray, r: np.ndarray,
                             dow_dum: np.ndarray,
                             exog: Optional[np.ndarray] = None,
                             exog_contemp: bool = False,
                             ) -> Optional[np.ndarray]:
    """Compute h_t[0:N] given PRG params (first 9 entries = PRG, rest ignored).

    Returns None on invalid parameters (for NLL -> 1e10 semantic).
    """
    theta0, theta1, d1, d2, d3, d4, alpha, gamma, beta = params[:9]
    xn = params[9] if len(params) >= 10 else 0.0

    if (theta0 <= 0 or theta1 < 0 or alpha < 0 or gamma < 0 or beta < 0
            or alpha + 0.5 * gamma + beta >= 0.999):
        return None
    omega = 1.0 - alpha - 0.5 * gamma - beta
    if omega <= 0:
        return None

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
        tau_t = theta0 + theta1 * x2_lag + dow_term + exog_term
        if tau_t <= 1e-10:
            return None
        tau[t] = tau_t

        u_lag = r[t - 1] / np.sqrt(max(tau[t - 1], 1e-10))
        u2_lag = u_lag * u_lag
        neg_ind = 1.0 if r[t - 1] < 0 else 0.0
        g_t = omega + alpha * u2_lag + gamma * u2_lag * neg_ind + beta * g[t - 1]
        if g_t <= 1e-10:
            return None
        g[t] = g_t

        h[t] = tau[t] * g[t]
        if h[t] <= 1e-10:
            return None
    return h


def prg_nll_normal(params: np.ndarray, r: np.ndarray, dow_dum: np.ndarray,
                   exog: Optional[np.ndarray] = None,
                   exog_contemp: bool = False) -> float:
    """Gaussian QML NLL for PRG (matches K1100g_d1 spec)."""
    h = _prg_variance_recursion(params, r, dow_dum, exog, exog_contemp)
    if h is None:
        return 1e10
    N = len(r)
    valid = slice(1, N)
    nll = 0.5 * np.sum(np.log(2 * np.pi * h[valid]) + r[valid] ** 2 / h[valid])
    if not np.isfinite(nll):
        return 1e10
    return float(nll)


def prg_nll_student(params: np.ndarray, r: np.ndarray, dow_dum: np.ndarray,
                    exog: Optional[np.ndarray] = None,
                    exog_contemp: bool = False) -> float:
    """Student-t MLE NLL for PRG.

    Parameterization: r_t | F_{t-1} = eps_t * sigma_t where
      sigma_t^2 = h_t (conditional variance)
      eps_t = z_t * sqrt((df-2)/df) with z_t ~ iid t_df(0,1)
    Density:
      f(r_t|h_t, df) = C(df) / sqrt(h_t * (df-2)/df) *
                      (1 + (r_t^2) / (h_t*(df-2)))^(-(df+1)/2)
      with C(df) = Gamma((df+1)/2) / (Gamma(df/2) * sqrt(pi))

    params layout: first 9 (or 10 if exog) = PRG; last = df
    """
    # Slice off df
    df = params[-1]
    prg_params = params[:-1]
    h = _prg_variance_recursion(prg_params, r, dow_dum, exog, exog_contemp)
    if h is None:
        return 1e10
    if df <= 2.01:
        return 1e10

    N = len(r)
    valid = slice(1, N)
    h_v = h[valid]
    r_v = r[valid]

    # Log density of Student-t with variance h
    # scale**2 = h*(df-2)/df so that Var(r) = h
    scale2 = h_v * (df - 2.0) / df
    if np.any(scale2 <= 0):
        return 1e10
    log_const = (gammaln((df + 1.0) / 2.0) - gammaln(df / 2.0)
                 - 0.5 * np.log(np.pi * (df - 2.0)))
    log_pdf = (log_const - 0.5 * np.log(h_v)
               - (df + 1.0) / 2.0 * np.log1p(r_v ** 2 / (h_v * (df - 2.0))))
    nll = -float(np.sum(log_pdf))
    if not np.isfinite(nll):
        return 1e10
    return nll


def fit_prg(r: np.ndarray, dow_dum: np.ndarray,
            exog: Optional[np.ndarray] = None,
            exog_contemp: bool = False,
            innovation: str = "normal",
            n_restarts: int = 8,
            x0_warm: Optional[np.ndarray] = None) -> Dict:
    """Fit PRG under chosen innovation via L-BFGS-B with multiple starts.

    innovation: 'normal' or 'student'
    If student, an extra df parameter is appended.
    """
    r = np.asarray(r, dtype=float)
    use_exog = exog is not None
    local_rng = np.random.default_rng(42)
    best = {"nll": np.inf, "params": None, "success": False, "innovation": innovation}

    prg_base_dim = 10 if use_exog else 9
    dim = prg_base_dim + (1 if innovation == "student" else 0)
    nll_fn = prg_nll_student if innovation == "student" else prg_nll_normal

    for trial in range(n_restarts):
        uncond = float(np.var(r, ddof=1))
        if trial == 0 and x0_warm is not None and len(x0_warm) == dim:
            x0 = np.array(x0_warm, dtype=float).copy()
        elif trial == 0:
            x0 = np.array([uncond * 0.5, 0.05, 0.0, 0.0, 0.0, 0.0,
                           0.05, 0.05, 0.80])
            if use_exog:
                x0 = np.concatenate([x0, [0.0]])
            if innovation == "student":
                x0 = np.concatenate([x0, [8.0]])  # df=8 reasonable start
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
            if innovation == "student":
                df0 = 4.0 + 8.0 * local_rng.random()
                x0 = np.concatenate([x0, [df0]])

        bounds = [
            (1e-8, None), (0.0, 1.0),
            (None, None), (None, None), (None, None), (None, None),
            (0.0, 0.4), (0.0, 0.4), (0.0, 0.9999),
        ]
        if use_exog:
            bounds.append((None, None))
        if innovation == "student":
            bounds.append((2.05, 200.0))  # df > 2 required for finite variance

        try:
            res = optimize.minimize(
                nll_fn, x0, args=(r, dow_dum, exog, exog_contemp),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-8},
            )
            if res.success and res.fun < best["nll"]:
                best = {
                    "nll": float(res.fun),
                    "params": res.x.copy(),
                    "success": True,
                    "trial": trial,
                    "innovation": innovation,
                }
        except Exception:
            continue

    return best


def prg_variance_path(params: np.ndarray, r: np.ndarray, dow_dum: np.ndarray,
                      exog: Optional[np.ndarray] = None,
                      exog_contemp: bool = False,
                      innovation: str = "normal") -> np.ndarray:
    """Given fitted params, return h_t path. Student-t params include df at end;
    h recursion itself does NOT depend on df, so we slice it off."""
    if params is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    prg_params = params[:-1] if innovation == "student" else params
    h = _prg_variance_recursion(prg_params, r, dow_dum, exog, exog_contemp)
    if h is None:
        # Fallback to unconditional
        return np.full(len(r), float(np.var(r, ddof=1)))
    return h


# ----------------------------------------------------------------------
# 2. Evaluation utilities
# ----------------------------------------------------------------------
def qlike_loss(h_hat: np.ndarray, r2: np.ndarray) -> np.ndarray:
    eps = 1e-10
    ratio = r2 / np.maximum(h_hat, eps)
    return ratio - np.log(np.maximum(ratio, eps)) - 1.0


def student_loglik_per_obs(h_hat: np.ndarray, r: np.ndarray,
                           df: float) -> np.ndarray:
    """Per-obs Student-t log-lik with Var=h (scale^2 = h*(df-2)/df)."""
    eps = 1e-12
    h = np.maximum(h_hat, eps)
    if df <= 2.0:
        return np.full_like(h, -np.inf)
    log_const = (gammaln((df + 1.0) / 2.0) - gammaln(df / 2.0)
                 - 0.5 * np.log(np.pi * (df - 2.0)))
    return (log_const - 0.5 * np.log(h)
            - (df + 1.0) / 2.0 * np.log1p(r ** 2 / (h * (df - 2.0))))


def gaussian_loglik_per_obs(h_hat: np.ndarray, r: np.ndarray) -> np.ndarray:
    eps = 1e-12
    h = np.maximum(h_hat, eps)
    return -0.5 * (np.log(2 * np.pi * h) + r * r / h)


def dm_test_hln(loss1: np.ndarray, loss2: np.ndarray) -> Tuple[float, float]:
    """HLN-corrected DM test. Positive t = loss1 > loss2 (model 2 better)."""
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


def lrt_chi2_test(ll_restricted: float, ll_full: float,
                  dof: int = 1) -> Tuple[float, float]:
    if ll_restricted is None or ll_full is None:
        return np.nan, np.nan
    lr = 2.0 * (ll_full - ll_restricted)
    if lr < 0:
        lr = 0.0
    p = 1.0 - chi2.cdf(lr, df=dof)
    return float(lr), float(p)


# ----------------------------------------------------------------------
# 3. VaR Trinity (Kupiec + CC backtests)
# ----------------------------------------------------------------------
def var_quantile(h_hat: np.ndarray, df: Optional[float],
                 level: float = 0.01,
                 innovation: str = "normal") -> np.ndarray:
    """Return one-sided lower VaR (negative for long position).
    For Normal: VaR = z_alpha * sqrt(h)
    For Student-t: VaR = t_alpha_df * sqrt(h*(df-2)/df)  (scale)
    where z_alpha = norm.ppf(level), t_alpha_df = student_t.ppf(level, df)
    """
    sigma2 = np.maximum(h_hat, 1e-12)
    if innovation == "normal":
        q = norm.ppf(level)
        return q * np.sqrt(sigma2)
    else:
        if df is None or df <= 2.0:
            return np.full_like(sigma2, np.nan)
        q = student_t.ppf(level, df)
        scale2 = sigma2 * (df - 2.0) / df
        return q * np.sqrt(scale2)


def kupiec_test(hits: np.ndarray, target_rate: float) -> Tuple[float, float]:
    """Kupiec (1995) unconditional coverage LR test. hits = 1/0 array."""
    N = len(hits)
    x = int(np.sum(hits))
    if N < 30:
        return np.nan, np.nan
    if x == 0:
        # LR = 2 * (0 - N*log(1-p_t)) = -2N log(1-p_t)
        lr = -2.0 * N * np.log(1.0 - target_rate)
    elif x == N:
        lr = -2.0 * N * np.log(target_rate)
    else:
        p_hat = x / N
        ll_unr = x * np.log(p_hat) + (N - x) * np.log(1 - p_hat)
        ll_res = x * np.log(target_rate) + (N - x) * np.log(1 - target_rate)
        lr = -2.0 * (ll_res - ll_unr)
    p = 1.0 - chi2.cdf(lr, df=1)
    return float(lr), float(p)


def christoffersen_cc_test(hits: np.ndarray,
                            target_rate: float) -> Tuple[float, float]:
    """Christoffersen (1998) conditional coverage = Kupiec + independence.
    Under H0: hits are iid Bernoulli(target_rate).
    LR_cc = LR_uc + LR_ind ~ chi2(2).
    """
    hits = np.asarray(hits, dtype=int)
    N = len(hits)
    if N < 30:
        return np.nan, np.nan
    # Independence: transition counts
    n00 = int(np.sum((hits[:-1] == 0) & (hits[1:] == 0)))
    n01 = int(np.sum((hits[:-1] == 0) & (hits[1:] == 1)))
    n10 = int(np.sum((hits[:-1] == 1) & (hits[1:] == 0)))
    n11 = int(np.sum((hits[:-1] == 1) & (hits[1:] == 1)))
    tot = n00 + n01 + n10 + n11
    if tot == 0:
        return np.nan, np.nan

    x = int(np.sum(hits))
    if x == 0 or x == N:
        lr_uc, _ = kupiec_test(hits, target_rate)
        return float(lr_uc), float(1.0 - chi2.cdf(lr_uc, df=2))

    # Restricted pi (same for both states)
    pi_hat = x / N
    ll_res = ((n00 + n10) * np.log(1 - pi_hat)
              + (n01 + n11) * np.log(pi_hat))

    # Unrestricted pi0, pi1
    denom0 = n00 + n01
    denom1 = n10 + n11
    if denom0 == 0 or denom1 == 0 or n01 == 0 or n11 == 0:
        # Degenerate; fall back to Kupiec only
        lr_uc, p = kupiec_test(hits, target_rate)
        return float(lr_uc), float(p)
    pi0 = n01 / denom0
    pi1 = n11 / denom1
    ll_unr = (n00 * np.log(1 - pi0) + n01 * np.log(pi0)
              + n10 * np.log(1 - pi1) + n11 * np.log(pi1))
    lr_ind = -2.0 * (ll_res - ll_unr)

    # Kupiec part
    lr_uc, _ = kupiec_test(hits, target_rate)
    lr_cc = lr_uc + lr_ind
    p = 1.0 - chi2.cdf(lr_cc, df=2)
    return float(lr_cc), float(p)


def var_trinity(r_actual: np.ndarray, var_bound: np.ndarray,
                target_rate: float) -> Dict:
    """Run Kupiec + Christoffersen + pass/fail judgment.
    var_bound is negative threshold; breach when r < var_bound.
    """
    hits = (r_actual < var_bound).astype(int)
    N = len(hits)
    x = int(np.sum(hits))
    rate = x / N if N else np.nan
    lr_uc, p_uc = kupiec_test(hits, target_rate)
    lr_cc, p_cc = christoffersen_cc_test(hits, target_rate)
    return {
        "N": int(N),
        "n_breaches": x,
        "breach_rate": float(rate),
        "target_rate": float(target_rate),
        "kupiec_LR": float(lr_uc) if np.isfinite(lr_uc) else None,
        "kupiec_p": float(p_uc) if np.isfinite(p_uc) else None,
        "kupiec_pass": bool(np.isfinite(p_uc) and p_uc > 0.05),
        "cc_LR": float(lr_cc) if np.isfinite(lr_cc) else None,
        "cc_p": float(p_cc) if np.isfinite(p_cc) else None,
        "cc_pass": bool(np.isfinite(p_cc) and p_cc > 0.05),
        "trinity_pass": bool(np.isfinite(p_uc) and p_uc > 0.05
                              and np.isfinite(p_cc) and p_cc > 0.05),
    }


# ----------------------------------------------------------------------
# 4. OOS expanding-window forecast (M_null vs M_full, Student-t)
# ----------------------------------------------------------------------
def expanding_oos_forecast_student(r_day: np.ndarray, dow_dum: np.ndarray,
                                    r_night2: np.ndarray,
                                    test_start_idx: int,
                                    use_exog: bool,
                                    refit_every: int = REFIT_EVERY) -> Dict:
    """Expanding-window OOS refit under Student-t innovation.
    Mirrors K1100g_d2.expanding_oos_forecast but with innovation='student'.
    """
    N = len(r_day)
    h_oos = np.full(N, np.nan)
    df_log = np.full(N, np.nan)
    params_log: List[Tuple[int, List[float]]] = []
    current_params = None

    for t in range(test_start_idx, N):
        steps = t - test_start_idx
        need_refit = (steps % refit_every == 0)
        if need_refit:
            r_train = r_day[:t]
            dow_train = dow_dum[:t]
            if use_exog:
                exog_train = r_night2[:t]
                fit = fit_prg(r_train, dow_train,
                              exog=exog_train, exog_contemp=True,
                              innovation="student",
                              n_restarts=4, x0_warm=current_params)
            else:
                fit = fit_prg(r_train, dow_train,
                              exog=None, exog_contemp=False,
                              innovation="student",
                              n_restarts=4, x0_warm=current_params)
            if fit["success"]:
                current_params = fit["params"]
                params_log.append((int(t), current_params.tolist()))
            else:
                print(f"  [warn] refit failed at t={t}")
        if current_params is None:
            continue

        df_t = float(current_params[-1])
        df_log[t] = df_t
        r_slice = r_day[:t + 1]
        dow_slice = dow_dum[:t + 1]
        if use_exog:
            exog_slice = r_night2[:t + 1]
            h_path = prg_variance_path(current_params, r_slice, dow_slice,
                                       exog=exog_slice, exog_contemp=True,
                                       innovation="student")
        else:
            h_path = prg_variance_path(current_params, r_slice, dow_slice,
                                       exog=None, exog_contemp=False,
                                       innovation="student")
        h_oos[t] = h_path[t]

    return {
        "h_oos": h_oos,
        "df_log": df_log,
        "params_log": params_log,
        "n_refits": len(params_log),
    }


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
# 5. Main
# ----------------------------------------------------------------------
def run():
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Loading session cache...")
    if not SESSIONS_CACHE.exists():
        raise FileNotFoundError(f"Missing cache: {SESSIONS_CACHE}")
    df = pd.read_parquet(SESSIONS_CACHE)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Align: same filter as K1100g_d1 (r_day + r_night + r_combined)
    mdf = df.dropna(subset=["r_day", "r_night", "r_combined"]).copy()
    mdf = mdf.reset_index(drop=True)
    N = len(mdf)
    print(f"  Aligned rows: {N}")

    dates_ts = pd.to_datetime(mdf["date"])
    dow_arr = mdf["dow"].values.astype(int)
    dow_dum = make_dow_dummies(dow_arr)
    r_day = mdf["r_day"].values.astype(float)
    r_night = mdf["r_night"].values.astype(float)
    r_comb = mdf["r_combined"].values.astype(float)
    r_night2 = r_night ** 2
    r_day2 = r_day ** 2

    # Diagnostic: excess kurtosis (motivates Student-t)
    kurt_day = float(kurt_fn(r_day, fisher=True, nan_policy="omit"))
    kurt_night = float(kurt_fn(r_night, fisher=True, nan_policy="omit"))
    kurt_comb = float(kurt_fn(r_comb, fisher=True, nan_policy="omit"))
    skew_day = float(skew_fn(r_day, nan_policy="omit"))
    skew_night = float(skew_fn(r_night, nan_policy="omit"))
    skew_comb = float(skew_fn(r_comb, nan_policy="omit"))
    print(f"  Excess kurtosis: day={kurt_day:.2f}  night={kurt_night:.2f}  "
          f"combined={kurt_comb:.2f}")
    print(f"  Skew: day={skew_day:.3f}  night={skew_night:.3f}  "
          f"combined={skew_comb:.3f}")

    # ------------------------------------------------------------------
    # A) IS full-sample fits: M1-M5 under Normal vs Student-t
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === IS fits (full sample) ===")
    is_fits = {}
    model_specs = [
        ("M1_combined", r_comb, None, False, 9),
        ("M2_day_only", r_day, None, False, 9),
        ("M3_night_only", r_night, None, False, 9),
        ("M4_cross_night_to_day", r_day, r_night2, True, 10),
        ("M5_reverse_day_to_night", r_night, r_day2, False, 10),
    ]
    for name, rseries, exog, exog_contemp, k_prg in model_specs:
        for innov in ("normal", "student"):
            key = f"{name}__{innov}"
            print(f"  [{time.strftime('%H:%M:%S')}] fitting {key} ...")
            fit = fit_prg(rseries, dow_dum,
                          exog=exog, exog_contemp=exog_contemp,
                          innovation=innov,
                          n_restarts=8)
            nll = fit["nll"]
            ll = -nll if np.isfinite(nll) else None
            k_eff = k_prg + (1 if innov == "student" else 0)
            aic = (2 * k_eff + 2 * nll) if np.isfinite(nll) else None
            bic = (k_eff * np.log(len(rseries) - 1) + 2 * nll) if np.isfinite(nll) else None
            df_est = float(fit["params"][-1]) if (innov == "student" and fit["params"] is not None) else None
            xn_coef = None
            if fit["params"] is not None and k_prg == 10:
                xn_coef = float(fit["params"][9])
            is_fits[key] = {
                "innovation": innov,
                "success": bool(fit["success"]),
                "nll": float(nll) if np.isfinite(nll) else None,
                "log_lik": ll,
                "aic": aic, "bic": bic,
                "k_params": k_eff,
                "df_est": df_est,
                "xn_coef": xn_coef,
                "params": fit["params"].tolist() if fit["params"] is not None else None,
            }
            ll_str = f"{ll:.3f}" if ll is not None else "NA"
            df_str = f" df={df_est:.2f}" if df_est is not None else ""
            print(f"    ll={ll_str}{df_str}  success={fit['success']}")

    # ------------------------------------------------------------------
    # B) IS LRT tests under each innovation
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === IS LRT (M4 vs M2, M5 vs M3) ===")
    is_lrt_tests = {}
    for innov in ("normal", "student"):
        ll_m2 = is_fits[f"M2_day_only__{innov}"]["log_lik"]
        ll_m3 = is_fits[f"M3_night_only__{innov}"]["log_lik"]
        ll_m4 = is_fits[f"M4_cross_night_to_day__{innov}"]["log_lik"]
        ll_m5 = is_fits[f"M5_reverse_day_to_night__{innov}"]["log_lik"]
        lrt_42, p_42 = lrt_chi2_test(ll_m2, ll_m4, dof=1)
        lrt_53, p_53 = lrt_chi2_test(ll_m3, ll_m5, dof=1)
        is_lrt_tests[innov] = {
            "M4_vs_M2": {"chi2": lrt_42, "p_value": p_42},
            "M5_vs_M3": {"chi2": lrt_53, "p_value": p_53},
        }
        print(f"  [{innov}] M4 vs M2: chi2={lrt_42:.3f} p={p_42:.4g}   "
              f"M5 vs M3: chi2={lrt_53:.3f} p={p_53:.4g}")

    # ------------------------------------------------------------------
    # C) OOS expanding-window (Student-t) — replicating K1100g_d2 spec
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === OOS (Student-t expanding window) ===")
    train_mask = (dates_ts >= TRAIN_START) & (dates_ts <= TRAIN_END)
    test_mask = (dates_ts >= TEST_START) & (dates_ts <= TEST_END)
    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]
    test_start_idx = int(test_idx[0])
    test_end_idx = int(test_idx[-1])
    print(f"  Train: n={len(train_idx)}  Test: n={len(test_idx)}")

    print(f"[{time.strftime('%H:%M:%S')}] M_null (day-only, Student-t) OOS...")
    ts_null = time.time()
    oos_null = expanding_oos_forecast_student(
        r_day, dow_dum, r_night2, test_start_idx,
        use_exog=False, refit_every=REFIT_EVERY,
    )
    print(f"  refits={oos_null['n_refits']}  elapsed={time.time() - ts_null:.1f}s")

    print(f"[{time.strftime('%H:%M:%S')}] M_full (day + night exog, Student-t) OOS...")
    ts_full = time.time()
    oos_full = expanding_oos_forecast_student(
        r_day, dow_dum, r_night2, test_start_idx,
        use_exog=True, refit_every=REFIT_EVERY,
    )
    print(f"  refits={oos_full['n_refits']}  elapsed={time.time() - ts_full:.1f}s")

    test_slice = slice(test_start_idx, test_end_idx + 1)
    r_day_test = r_day[test_slice]
    r2_day_test = r_day_test ** 2
    dates_test = dates_ts.iloc[test_slice].values
    h_null_test = oos_null["h_oos"][test_slice]
    h_full_test = oos_full["h_oos"][test_slice]
    df_null_test = oos_null["df_log"][test_slice]
    df_full_test = oos_full["df_log"][test_slice]

    valid = np.isfinite(h_null_test) & np.isfinite(h_full_test) & \
            np.isfinite(df_null_test) & np.isfinite(df_full_test)
    n_valid = int(valid.sum())
    print(f"\n  OOS valid obs: {n_valid} / {len(h_null_test)}")

    r_day_v = r_day_test[valid]
    r2_day_v = r2_day_test[valid]
    h_null_v = h_null_test[valid]
    h_full_v = h_full_test[valid]
    df_null_v = df_null_test[valid]
    df_full_v = df_full_test[valid]
    dates_v = pd.to_datetime(dates_test[valid])

    # QLIKE (variance loss, innovation-agnostic)
    qlike_null = qlike_loss(h_null_v, r2_day_v)
    qlike_full = qlike_loss(h_full_v, r2_day_v)

    # Student-t per-obs log-lik (using time-varying df)
    ll_null_pd = np.array([
        float(student_loglik_per_obs(np.array([h_null_v[i]]),
                                     np.array([r_day_v[i]]),
                                     df_null_v[i])[0])
        for i in range(n_valid)
    ])
    ll_full_pd = np.array([
        float(student_loglik_per_obs(np.array([h_full_v[i]]),
                                     np.array([r_day_v[i]]),
                                     df_full_v[i])[0])
        for i in range(n_valid)
    ])

    ll_null_sum = float(np.sum(ll_null_pd))
    ll_full_sum = float(np.sum(ll_full_pd))
    oos_lrt_stat, oos_lrt_p = lrt_chi2_test(ll_null_sum, ll_full_sum, dof=1)

    # DM on QLIKE and on negative log-lik
    dm_qlike_t, dm_qlike_p = dm_test_hln(qlike_null, qlike_full)
    dm_ll_t, dm_ll_p = dm_test_hln(-ll_null_pd, -ll_full_pd)

    qlike_null_mean = float(np.mean(qlike_null))
    qlike_full_mean = float(np.mean(qlike_full))
    qlike_improv_pct = (qlike_null_mean - qlike_full_mean) / abs(qlike_null_mean) * 100 \
        if qlike_null_mean != 0 else np.nan

    # Sub-period (2020 vs 2021)
    mask_2020 = (dates_v >= pd.Timestamp("2020-01-01")) & \
                (dates_v <= pd.Timestamp("2020-12-31"))
    mask_2021 = (dates_v >= pd.Timestamp("2021-01-01")) & \
                (dates_v <= pd.Timestamp("2021-12-31"))

    def subperiod_stats(mask):
        if mask.sum() < 30:
            return {"n": int(mask.sum()), "pass_h3": False}
        qn = qlike_null[mask]
        qf = qlike_full[mask]
        lln = float(np.sum(ll_null_pd[mask]))
        llf = float(np.sum(ll_full_pd[mask]))
        lr, pp = lrt_chi2_test(lln, llf, dof=1)
        dt, dp = dm_test_hln(qn, qf)
        qn_mean = float(np.mean(qn))
        qf_mean = float(np.mean(qf))
        imp = (qn_mean - qf_mean) / abs(qn_mean) * 100 if qn_mean != 0 else np.nan
        return {
            "n": int(mask.sum()),
            "qlike_null_mean": qn_mean, "qlike_full_mean": qf_mean,
            "qlike_improv_pct": float(imp) if np.isfinite(imp) else None,
            "lrt_chi2": float(lr), "lrt_p": float(pp),
            "dm_t_hln": float(dt) if np.isfinite(dt) else None,
            "dm_p": float(dp) if np.isfinite(dp) else None,
            "pass_h3": bool(np.isfinite(imp) and imp > 1.0),
        }

    sub_2020 = subperiod_stats(mask_2020)
    sub_2021 = subperiod_stats(mask_2021)

    print(f"\n[{time.strftime('%H:%M:%S')}] Student-t OOS results:")
    print(f"  chi2_lrt={oos_lrt_stat:.3f}  p={oos_lrt_p:.4g}")
    print(f"  DM-QLIKE t={dm_qlike_t:.3f}  p={dm_qlike_p:.4g}")
    print(f"  DM-LL    t={dm_ll_t:.3f}  p={dm_ll_p:.4g}")
    print(f"  QLIKE improv: {qlike_improv_pct:+.2f}%")
    print(f"  df_null mean={np.mean(df_null_v):.2f}  df_full mean={np.mean(df_full_v):.2f}")

    # ------------------------------------------------------------------
    # D) VaR Trinity (Kupiec + CC) at 1% and 5% for each OOS model
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === VaR Trinity backtests ===")
    var_results = {}
    for level in (0.01, 0.05):
        # Null: Student-t VaR using df_null_v
        var_null = np.array([
            student_t.ppf(level, df_null_v[i])
            * np.sqrt(h_null_v[i] * (df_null_v[i] - 2.0) / df_null_v[i])
            for i in range(n_valid)
        ])
        var_full = np.array([
            student_t.ppf(level, df_full_v[i])
            * np.sqrt(h_full_v[i] * (df_full_v[i] - 2.0) / df_full_v[i])
            for i in range(n_valid)
        ])
        tri_null = var_trinity(r_day_v, var_null, level)
        tri_full = var_trinity(r_day_v, var_full, level)
        var_results[f"level_{int(level*100)}pct"] = {
            "M_null_student_t": tri_null,
            "M_full_student_t": tri_full,
        }
        print(f"  [{level*100:.0f}% VaR] null: breach={tri_null['breach_rate']:.3%}"
              f"  Kupiec p={tri_null['kupiec_p']}"
              f"  CC p={tri_null['cc_p']}")
        print(f"  [{level*100:.0f}% VaR] full: breach={tri_full['breach_rate']:.3%}"
              f"  Kupiec p={tri_full['kupiec_p']}"
              f"  CC p={tri_full['cc_p']}")

    # ------------------------------------------------------------------
    # E) H1/H2/H3 Verdict
    # ------------------------------------------------------------------
    student_is_lrt_42 = is_lrt_tests["student"]["M4_vs_M2"]["chi2"]
    student_is_lrt_53 = is_lrt_tests["student"]["M5_vs_M3"]["chi2"]
    normal_is_lrt_42 = is_lrt_tests["normal"]["M4_vs_M2"]["chi2"]
    # Conditions
    oos_h1_pass = bool(np.isfinite(oos_lrt_stat) and oos_lrt_stat > 7.88
                        and qlike_improv_pct > 1.0)
    oos_rejected = bool(np.isfinite(oos_lrt_stat) and oos_lrt_stat < 3.84)

    df_flag = False
    mean_df_full = float(np.mean(df_full_v)) if n_valid else np.nan
    if np.isfinite(mean_df_full) and mean_df_full < 3.0:
        df_flag = True

    # Verdict logic (Harvey-aware: DM |t|>3 for strong claim)
    harvey_dm_pass = bool(np.isfinite(dm_qlike_t) and abs(dm_qlike_t) > 3.0)
    lrt_strong = bool(np.isfinite(oos_lrt_stat) and oos_lrt_stat > 7.88)
    qlike_meaningful = bool(np.isfinite(qlike_improv_pct) and qlike_improv_pct > 1.0)
    both_subperiods_positive = bool(
        sub_2020.get("qlike_improv_pct") is not None
        and sub_2021.get("qlike_improv_pct") is not None
        and sub_2020["qlike_improv_pct"] > 1.0
        and sub_2021["qlike_improv_pct"] > 1.0
    )

    if lrt_strong and qlike_meaningful and harvey_dm_pass and both_subperiods_positive:
        verdict = "H1_STUDENT_T_SAVES_STRONG"
        explanation = (
            "Student-t innovation rescues night->day predictive signal with "
            "LRT>7.88, QLIKE improv>1%, Harvey-robust DM |t|>3, and both "
            "2020/2021 sub-periods positive. K1100g_d1 Normal misfit was "
            "masking a real effect — Paper 3 reframe recoverable."
        )
    elif lrt_strong and qlike_meaningful and both_subperiods_positive:
        verdict = "H1_STUDENT_T_SAVES_PARTIAL"
        explanation = (
            "Student-t OOS shows LRT>7.88 and QLIKE>1% and both sub-periods "
            "positive, BUT DM |t| below Harvey (2016) threshold of 3. "
            "Evidence is directionally consistent but not Harvey-robust."
        )
    elif oos_rejected and student_is_lrt_42 < normal_is_lrt_42 * 0.5:
        verdict = "H3_MIXED_IS_DAMPENED_OOS_STILL_DEAD"
        explanation = (
            "Student-t dampens the in-sample LRT substantially (suggesting "
            "Normal over-stated the gain via tail abuse), but OOS still "
            "rejects. K1100g_d1 effect remains data mining."
        )
    elif oos_rejected:
        verdict = "H2_T_SAME_RESULT"
        explanation = (
            "Student-t does not rescue the OOS predictive signal; the "
            "rejection in K1100g_d2 is not an innovation artifact. "
            "Paper 3 reframe still dead."
        )
    else:
        verdict = "H3_SUBSET_MIXED"
        explanation = (
            "Partial rescue — some criteria met but not all. See verdict "
            "details for which sub-tests passed."
        )

    paper3_salvage = bool(lrt_strong and qlike_meaningful and both_subperiods_positive)

    # ------------------------------------------------------------------
    # F) Compile result
    # ------------------------------------------------------------------
    result = {
        "experiment_id": "K1100g_d3",
        "title": "Student-t PRG innovation — re-estimating K1100g_d1/d2 under fat-tail likelihood",
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": 42,
        "references": [
            "Bollerslev (1987) A Conditionally Heteroskedastic Time Series Model, RESTAT 69(3), 542-547 — Student-t GARCH",
            "Engle & Rangel (2008) The Spline-GARCH Model..., RFS 21(3) — tau*g multiplicative PRG",
            "Kupiec (1995) Techniques for Verifying the Accuracy of Risk Measurement Models",
            "Christoffersen (1998) Evaluating Interval Forecasts, IER 39(4), 841-862 — CC test",
            "Harvey, Leybourne & Newbold (1997) Testing the equality of prediction mean squared errors, IJF",
        ],
        "data": {
            "source": "TAIFEX TX 2017-2021 (K1100g_d1 raw-tick session cache)",
            "cache_file": str(SESSIONS_CACHE.name),
            "n_aligned": int(N),
            "descriptive": {
                "excess_kurtosis_day": kurt_day,
                "excess_kurtosis_night": kurt_night,
                "excess_kurtosis_combined": kurt_comb,
                "skew_day": skew_day,
                "skew_night": skew_night,
                "skew_combined": skew_comb,
            },
        },
        "design": {
            "innovation_compared": ["normal", "student"],
            "prg_kernel": "tau*g multiplicative, omega=1-alpha-gamma/2-beta",
            "models": {
                "M1": "combined PRG",
                "M2": "day-only PRG",
                "M3": "night-only PRG",
                "M4": "day PRG + r_night[t]^2 contemp exog",
                "M5": "night PRG + r_day[t-1]^2 lagged exog",
            },
            "train_start": str(TRAIN_START.date()),
            "train_end": str(TRAIN_END.date()),
            "test_start": str(TEST_START.date()),
            "test_end": str(TEST_END.date()),
            "refit_every": REFIT_EVERY,
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
            "n_test_valid": int(n_valid),
        },
        "is_fits": is_fits,
        "is_lrt_tests": is_lrt_tests,
        "oos_student_t": {
            "lrt_chi2": float(oos_lrt_stat) if np.isfinite(oos_lrt_stat) else None,
            "lrt_p": float(oos_lrt_p) if np.isfinite(oos_lrt_p) else None,
            "dm_qlike_t_hln": float(dm_qlike_t) if np.isfinite(dm_qlike_t) else None,
            "dm_qlike_p": float(dm_qlike_p) if np.isfinite(dm_qlike_p) else None,
            "dm_loglik_t_hln": float(dm_ll_t) if np.isfinite(dm_ll_t) else None,
            "dm_loglik_p": float(dm_ll_p) if np.isfinite(dm_ll_p) else None,
            "qlike_null_mean": qlike_null_mean,
            "qlike_full_mean": qlike_full_mean,
            "qlike_improv_pct": float(qlike_improv_pct) if np.isfinite(qlike_improv_pct) else None,
            "ll_null_sum": ll_null_sum,
            "ll_full_sum": ll_full_sum,
            "df_null_mean": float(np.mean(df_null_v)),
            "df_full_mean": float(np.mean(df_full_v)),
            "df_null_min": float(np.min(df_null_v)),
            "df_full_min": float(np.min(df_full_v)),
            "df_flag_below_3": bool(df_flag),
            "sub_period": {"y2020": sub_2020, "y2021": sub_2021},
        },
        "var_trinity_oos": var_results,
        "verdict": {
            "primary": verdict,
            "paper3_salvage": bool(paper3_salvage),
            "explanation": explanation,
            "criteria_detail": {
                "lrt_strong_oos_chi2_gt_7_88": bool(lrt_strong),
                "qlike_meaningful_gt_1pct": bool(qlike_meaningful),
                "harvey_dm_t_gt_3_0": bool(harvey_dm_pass),
                "both_subperiods_positive_gt_1pct": bool(both_subperiods_positive),
                "df_flag_below_3": bool(df_flag),
            },
            "normal_is_lrt_M4_vs_M2": normal_is_lrt_42,
            "student_is_lrt_M4_vs_M2": student_is_lrt_42,
            "oos_lrt_student": float(oos_lrt_stat) if np.isfinite(oos_lrt_stat) else None,
            "oos_qlike_improv_student_pct": float(qlike_improv_pct) if np.isfinite(qlike_improv_pct) else None,
            "oos_dm_qlike_t_hln": float(dm_qlike_t) if np.isfinite(dm_qlike_t) else None,
        },
        "limitations": [
            "N test = ~464 may be small for asymptotic chi-square; OOS LRT is approximate",
            "df estimated jointly with PRG params; may be biased toward interior via optimizer bounds [2.05, 200]",
            "Student-t assumes symmetric innovations; TAIFEX skew is non-zero (asymmetric-t would be further refinement)",
            "Cross-market replication (SPY, N225) remains open (K1100g_d4 candidate)",
            "Only one pair of session-level exogenous variables tested (r_night^2, r_day^2 lag)",
        ],
    }
    result = clean_for_json(result)
    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(f"[OK] results -> {RESULTS_PATH.name}")

    # ------------------------------------------------------------------
    # G) Plots
    # ------------------------------------------------------------------
    plot_all(is_lrt_tests, is_fits,
             dates_v, qlike_null, qlike_full, ll_null_pd, ll_full_pd,
             df_null_v, df_full_v,
             var_results, oos_lrt_stat, dm_qlike_t, qlike_improv_pct)

    print(f"\n[DONE] Total: {time.time() - t0:.1f}s")
    return result


def plot_all(is_lrt_tests, is_fits,
             dates_v, qlike_null, qlike_full, ll_null_pd, ll_full_pd,
             df_null_v, df_full_v,
             var_results, oos_lrt_stat, dm_qlike_t, qlike_improv_pct):

    # Plot 1: IS LRT Normal vs Student-t (M4 vs M2, M5 vs M3)
    fig, ax = plt.subplots(figsize=(9, 5))
    chi2_normal = [is_lrt_tests["normal"]["M4_vs_M2"]["chi2"],
                   is_lrt_tests["normal"]["M5_vs_M3"]["chi2"]]
    chi2_student = [is_lrt_tests["student"]["M4_vs_M2"]["chi2"],
                    is_lrt_tests["student"]["M5_vs_M3"]["chi2"]]
    x = np.arange(2)
    width = 0.35
    ax.bar(x - width/2, chi2_normal, width, label="Normal",
           color="#1f77b4", alpha=0.85)
    ax.bar(x + width/2, chi2_student, width, label="Student-t",
           color="#d62728", alpha=0.85)
    ax.axhline(3.84, linestyle="--", color="#444", alpha=0.6,
               label="chi2(1, p=0.05)=3.84")
    ax.axhline(7.88, linestyle=":", color="#666", alpha=0.6,
               label="chi2(1, p=0.005)=7.88")
    ax.set_xticks(x)
    ax.set_xticklabels(["M4 vs M2\n(night->day)", "M5 vs M3\n(day->night)"])
    ax.set_ylabel("IS LRT chi2 statistic")
    ax.set_title("IS LRT — Normal vs Student-t innovation")
    for xi, (n, s) in enumerate(zip(chi2_normal, chi2_student)):
        if np.isfinite(n):
            ax.text(xi - width/2, n + 0.1, f"{n:.2f}", ha="center", fontsize=9)
        if np.isfinite(s):
            ax.text(xi + width/2, s + 0.1, f"{s:.2f}", ha="center", fontsize=9)
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d3_is_lrt_normal_vs_student.png", dpi=120)
    plt.close()

    # Plot 2: OOS 30-day rolling QLIKE improvement (%), df over time
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    ax1, ax2 = axes
    qd = qlike_null - qlike_full  # positive = full better
    qd_roll = pd.Series(qd, index=pd.to_datetime(dates_v)).rolling(30).mean()
    ax1.plot(qd_roll.index, qd_roll.values, color="#2ca02c", lw=1.3)
    ax1.axhline(0, color="black", lw=0.8)
    ax1.fill_between(qd_roll.index, 0, qd_roll.values,
                      where=(qd_roll.values > 0), alpha=0.25, color="#2ca02c",
                      label="M_full better")
    ax1.fill_between(qd_roll.index, 0, qd_roll.values,
                      where=(qd_roll.values <= 0), alpha=0.25, color="#d62728",
                      label="M_null better")
    ax1.set_ylabel("30d mean QLIKE(null) - QLIKE(full)")
    ax1.set_title(f"Student-t OOS QLIKE improvement "
                  f"(full-sample improv = {qlike_improv_pct:+.2f}%, "
                  f"DM t = {dm_qlike_t:.2f})")
    ax1.legend()
    ax1.grid(alpha=0.3)

    ax2.plot(pd.to_datetime(dates_v), df_null_v, color="#1f77b4",
              lw=1.0, label="M_null df")
    ax2.plot(pd.to_datetime(dates_v), df_full_v, color="#d62728",
              lw=1.0, label="M_full df", alpha=0.8)
    ax2.axhline(3.0, linestyle="--", color="#666", alpha=0.6,
                 label="df=3 fat-tail flag")
    ax2.set_ylabel("Student-t df (degrees of freedom)")
    ax2.set_xlabel("Date")
    ax2.legend()
    ax2.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d3_oos_student_qlike_df.png", dpi=120)
    plt.close()

    print("[OK] 2 charts saved")


if __name__ == "__main__":
    run()
