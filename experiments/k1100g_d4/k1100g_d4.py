"""
K1100g_d4 — Annual stability of night->day PRG predictability (Student-t)
========================================================================

Parent:
  - K1100g_d3 (Student-t PRG): OOS LRT chi2=14.61 (p=1.3e-4),
    DM-HLN t=+1.92 (borderline vs Harvey 2016 t>3), QLIKE improv +3.78%.
    BUT sub-period split: 2020 +4.74% vs 2021 +2.64% (~1.8x gap).
    Question: is the "night->day" asymmetric structure genuinely stable
    year-to-year, or is K1100g_d3 mostly driven by 2020 COVID regime shift
    (tail-fat state creates transient predictability)?

Hypotheses (annual stability):
  H1 (genuine structure): every year (2017-2021) LRT chi2 > 7.88 (1%) and
      LRT direction positive + coefficient stable — TAIFEX night->day
      asymmetric predictive mechanism holds independent of regime.
  H2 (COVID-driven):      only 2020 LRT >> 7.88; other years LRT NS.
      2020 regime shift is the sole driver. Paper 3 reframe retracted.
  H3 (mixed / partial):   3-4 years PASS, remainder NS. Transitional
      effect; reframe salvageable with explicit caveat.

Design:
  Data: TAIFEX TX 2017-2021 daily session cache from K1100g_d3.
  Models (mirroring K1100g_d3):
    M2 day-only PRG  (k=10 under Student-t: 9 PRG params + df)
    M4 cross PRG (day + r_night[t]^2 contemporaneous exog, k=11)

  Annual fit (Student-t, n_restarts=8):
    For each year y in {2017, 2018, 2019, 2020, 2021}:
      fit M2 and M4 on that year's rows only (~150-233 days)
      compute LRT chi2 (df=1: the xn coef) and p-value @ 1% threshold 7.88.
      Record xn coef + its estimate stability.

  Pseudo-OOS per year (expanding train):
    For each test year y in {2018, 2019, 2020, 2021}:
      train = years < y (all aligned rows)
      test  = year y
      Fit M2 and M4 on train once.
      Compute h_null / h_full for TEST rows using frozen params, appending
        sequentially (h recursion is recursive but params frozen).
      Compute per-year QLIKE for M_null and M_full, DM-HLN t.
      Also report OOS LRT analogue via log-lik difference.
      (Single-fit expanding-window: lighter than K1100g_d3's 5-day refit;
       each test year gets its own train window ending at Dec 31 y-1.)

  Innovation: Student-t only (K1100g_d3 confirmed Normal QML biases results;
              E074/E074-like lesson about Gaussian tail artifact).

Lookahead discipline:
  - Annual fit is within-year; straightforward (full-year data).
  - Pseudo-OOS train ends strictly before test year starts; params frozen.
  - Signal r_night[t]^2 is LEGAL (night_t ends 05:00 before day_t opens).
  - Seed fixed: np.random.seed(42), default_rng(42).

References (same as K1100g_d3):
  - Bollerslev (1987) REStat 69(3) — Student-t GARCH
  - Engle & Rangel (2008) RFS 21(3) — tau*g PRG
  - Harvey, Leybourne & Newbold (1997) IJF 13(2) — HLN DM correction
  - Harvey (2016) JF — t>3 threshold

Author: Claude (worktree agent-a14899fe)
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
RESULTS_PATH = SCRIPT_DIR / "k1100g_d4_results.json"

YEARS_ANNUAL = [2017, 2018, 2019, 2020, 2021]
YEARS_OOS = [2018, 2019, 2020, 2021]


# ----------------------------------------------------------------------
# 1. PRG kernel — Student-t (inherited from K1100g_d3)
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
    """Compute h_t[0:N] given PRG params (first 9 = PRG, opt 10 = xn, last=df ignored)."""
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


def prg_nll_student(params: np.ndarray, r: np.ndarray, dow_dum: np.ndarray,
                    exog: Optional[np.ndarray] = None,
                    exog_contemp: bool = False) -> float:
    """Student-t MLE NLL for PRG (scale^2 = h*(df-2)/df so Var(r)=h)."""
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


def fit_prg_student(r: np.ndarray, dow_dum: np.ndarray,
                    exog: Optional[np.ndarray] = None,
                    exog_contemp: bool = False,
                    n_restarts: int = 8,
                    x0_warm: Optional[np.ndarray] = None) -> Dict:
    """Fit PRG under Student-t via L-BFGS-B with multiple restarts."""
    r = np.asarray(r, dtype=float)
    use_exog = exog is not None
    local_rng = np.random.default_rng(42)
    best = {"nll": np.inf, "params": None, "success": False}

    prg_base_dim = 10 if use_exog else 9
    dim = prg_base_dim + 1  # + df

    for trial in range(n_restarts):
        uncond = float(np.var(r, ddof=1))
        if trial == 0 and x0_warm is not None and len(x0_warm) == dim:
            x0 = np.array(x0_warm, dtype=float).copy()
        elif trial == 0:
            x0 = np.array([uncond * 0.5, 0.05, 0.0, 0.0, 0.0, 0.0,
                           0.05, 0.05, 0.80])
            if use_exog:
                x0 = np.concatenate([x0, [0.0]])
            x0 = np.concatenate([x0, [8.0]])  # df=8 start
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
            df0 = 4.0 + 8.0 * local_rng.random()
            x0 = np.concatenate([x0, [df0]])

        bounds = [
            (1e-8, None), (0.0, 1.0),
            (None, None), (None, None), (None, None), (None, None),
            (0.0, 0.4), (0.0, 0.4), (0.0, 0.9999),
        ]
        if use_exog:
            bounds.append((None, None))
        bounds.append((2.05, 200.0))  # df > 2

        try:
            res = optimize.minimize(
                prg_nll_student, x0, args=(r, dow_dum, exog, exog_contemp),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-8},
            )
            if res.success and res.fun < best["nll"]:
                best = {
                    "nll": float(res.fun),
                    "params": res.x.copy(),
                    "success": True,
                    "trial": trial,
                }
        except Exception:
            continue

    return best


def prg_variance_path_student(params: np.ndarray, r: np.ndarray,
                               dow_dum: np.ndarray,
                               exog: Optional[np.ndarray] = None,
                               exog_contemp: bool = False) -> np.ndarray:
    if params is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    prg_params = params[:-1]
    h = _prg_variance_recursion(prg_params, r, dow_dum, exog, exog_contemp)
    if h is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    return h


# ----------------------------------------------------------------------
# 2. Evaluation utilities (from K1100g_d3)
# ----------------------------------------------------------------------
def qlike_loss(h_hat: np.ndarray, r2: np.ndarray) -> np.ndarray:
    eps = 1e-10
    ratio = r2 / np.maximum(h_hat, eps)
    return ratio - np.log(np.maximum(ratio, eps)) - 1.0


def dm_test_hln(loss1: np.ndarray, loss2: np.ndarray) -> Tuple[float, float]:
    """HLN-corrected DM. Positive t = loss1 > loss2 (model 2 better)."""
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
# 3. Main
# ----------------------------------------------------------------------
def run():
    t_start = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Loading session cache...")
    if not SESSIONS_CACHE.exists():
        raise FileNotFoundError(f"Missing cache: {SESSIONS_CACHE}")
    df = pd.read_parquet(SESSIONS_CACHE)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    mdf = df.dropna(subset=["r_day", "r_night", "r_combined"]).copy()
    mdf = mdf.reset_index(drop=True)
    mdf["year"] = pd.to_datetime(mdf["date"]).dt.year

    N = len(mdf)
    print(f"  Aligned rows: {N}")
    year_counts = mdf.groupby("year").size().to_dict()
    print(f"  Per-year counts: {year_counts}")

    dow_all = mdf["dow"].values.astype(int)
    dow_dum_all = make_dow_dummies(dow_all)
    r_day_all = mdf["r_day"].values.astype(float)
    r_night_all = mdf["r_night"].values.astype(float)
    r_night2_all = r_night_all ** 2
    year_all = mdf["year"].values.astype(int)

    # ------------------------------------------------------------------
    # A) Annual in-year fits: M2 (day-only) vs M4 (day + night exog)
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === Annual IS fits (Student-t) ===")
    annual_fits: Dict[int, Dict] = {}
    annual_lrt: Dict[int, Dict] = {}

    for y in YEARS_ANNUAL:
        mask = year_all == y
        idx = np.where(mask)[0]
        n_y = len(idx)
        print(f"\n  --- Year {y}  (n={n_y}) ---")

        r_day_y = r_day_all[idx]
        r_night2_y = r_night2_all[idx]
        dow_dum_y = dow_dum_all[idx]

        # Diagnostics
        ex_kurt_d = float(kurt_fn(r_day_y, fisher=True, nan_policy="omit"))
        ex_kurt_n = float(kurt_fn(r_night_all[idx], fisher=True, nan_policy="omit"))
        sk_d = float(skew_fn(r_day_y, nan_policy="omit"))
        sk_n = float(skew_fn(r_night_all[idx], nan_policy="omit"))

        print(f"    [{time.strftime('%H:%M:%S')}] fitting M2 (day-only, t) ...")
        fit_m2 = fit_prg_student(r_day_y, dow_dum_y,
                                  exog=None, exog_contemp=False,
                                  n_restarts=8)
        ll_m2 = -fit_m2["nll"] if fit_m2["success"] else None
        df_m2 = float(fit_m2["params"][-1]) if fit_m2["params"] is not None else None
        ll_m2_str = f"{ll_m2:.3f}" if ll_m2 is not None else "NA"
        df_m2_str = f"{df_m2:.2f}" if df_m2 is not None else "NA"
        print(f"      ll={ll_m2_str}  df={df_m2_str}  success={fit_m2['success']}")

        print(f"    [{time.strftime('%H:%M:%S')}] fitting M4 (day + night exog, t) ...")
        fit_m4 = fit_prg_student(r_day_y, dow_dum_y,
                                  exog=r_night2_y, exog_contemp=True,
                                  n_restarts=8)
        ll_m4 = -fit_m4["nll"] if fit_m4["success"] else None
        df_m4 = float(fit_m4["params"][-1]) if fit_m4["params"] is not None else None
        xn_m4 = float(fit_m4["params"][9]) if fit_m4["params"] is not None else None
        ll_m4_str = f"{ll_m4:.3f}" if ll_m4 is not None else "NA"
        df_m4_str = f"{df_m4:.2f}" if df_m4 is not None else "NA"
        xn_m4_str = f"{xn_m4:+.4g}" if xn_m4 is not None else "NA"
        print(f"      ll={ll_m4_str}  df={df_m4_str}  xn={xn_m4_str}  success={fit_m4['success']}")

        # LRT M4 vs M2 (xn coef df=1)
        lrt_stat, lrt_p = lrt_chi2_test(ll_m2, ll_m4, dof=1)
        print(f"    LRT M4 vs M2: chi2={lrt_stat:.3f}  p={lrt_p:.4g}")

        annual_fits[y] = {
            "n_obs": int(n_y),
            "excess_kurt_day": ex_kurt_d,
            "excess_kurt_night": ex_kurt_n,
            "skew_day": sk_d,
            "skew_night": sk_n,
            "M2_day_only": {
                "success": bool(fit_m2["success"]),
                "nll": float(fit_m2["nll"]) if np.isfinite(fit_m2["nll"]) else None,
                "log_lik": ll_m2,
                "df_est": df_m2,
                "params": fit_m2["params"].tolist() if fit_m2["params"] is not None else None,
            },
            "M4_night_to_day": {
                "success": bool(fit_m4["success"]),
                "nll": float(fit_m4["nll"]) if np.isfinite(fit_m4["nll"]) else None,
                "log_lik": ll_m4,
                "df_est": df_m4,
                "xn_coef": xn_m4,
                "params": fit_m4["params"].tolist() if fit_m4["params"] is not None else None,
            },
        }
        annual_lrt[y] = {
            "chi2": lrt_stat,
            "p_value": lrt_p,
            "dof": 1,
            "threshold_1pct": 6.63,
            "threshold_1pct_two_sided_like": 7.88,  # spec
            "pass_at_1pct": bool(np.isfinite(lrt_stat) and lrt_stat > 7.88),
        }

    # ------------------------------------------------------------------
    # B) Pseudo-OOS per year: expanding train (all prior aligned rows),
    #    params frozen, test on that year
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === Pseudo-OOS per year (Student-t, frozen params) ===")
    oos_per_year: Dict[int, Dict] = {}

    for y in YEARS_OOS:
        train_mask = year_all < y
        test_mask = year_all == y
        train_idx = np.where(train_mask)[0]
        test_idx = np.where(test_mask)[0]
        n_tr = len(train_idx)
        n_te = len(test_idx)
        print(f"\n  --- Test year {y}  (train n={n_tr},  test n={n_te}) ---")
        if n_tr < 150 or n_te < 50:
            print(f"    skipped (train/test size too small)")
            continue

        # Train M_null (M2) and M_full (M4) on train set only
        r_day_tr = r_day_all[train_idx]
        r_night2_tr = r_night2_all[train_idx]
        dow_dum_tr = dow_dum_all[train_idx]

        print(f"    [{time.strftime('%H:%M:%S')}] train M_null (day-only, t)...")
        fit_null = fit_prg_student(r_day_tr, dow_dum_tr,
                                    exog=None, exog_contemp=False,
                                    n_restarts=6)
        df_null_dbg = fit_null['params'][-1] if fit_null['params'] is not None else None
        print(f"      success={fit_null['success']}  df={df_null_dbg}")

        print(f"    [{time.strftime('%H:%M:%S')}] train M_full (day + night exog, t)...")
        fit_full = fit_prg_student(r_day_tr, dow_dum_tr,
                                    exog=r_night2_tr, exog_contemp=True,
                                    n_restarts=6)
        df_full_dbg = fit_full['params'][-1] if fit_full['params'] is not None else None
        xn_full_dbg = fit_full['params'][9] if fit_full['params'] is not None else None
        print(f"      success={fit_full['success']}  df={df_full_dbg}  xn={xn_full_dbg}")

        if not fit_null["success"] or not fit_full["success"]:
            print("    [warn] train fit failed; skipping this year")
            oos_per_year[y] = {"error": "train_fit_failed"}
            continue

        # For OOS forecasts, we need the full path up to each test-day
        # using frozen params. Build full-sample path: [train+test] = all
        # rows <= last test day. Simplest: use all rows 0..test_idx[-1].
        end_idx = int(test_idx[-1])
        r_day_upto = r_day_all[:end_idx + 1]
        r_night2_upto = r_night2_all[:end_idx + 1]
        dow_dum_upto = dow_dum_all[:end_idx + 1]

        h_null_path = prg_variance_path_student(
            fit_null["params"], r_day_upto, dow_dum_upto,
            exog=None, exog_contemp=False,
        )
        h_full_path = prg_variance_path_student(
            fit_full["params"], r_day_upto, dow_dum_upto,
            exog=r_night2_upto, exog_contemp=True,
        )

        # Extract test slice
        ti = test_idx  # indices into full array (aligned)
        h_null_t = h_null_path[ti]
        h_full_t = h_full_path[ti]
        r_day_t = r_day_all[ti]
        r2_day_t = r_day_t ** 2

        valid = (np.isfinite(h_null_t) & np.isfinite(h_full_t)
                 & np.isfinite(r2_day_t)
                 & (h_null_t > 0) & (h_full_t > 0))
        n_valid = int(np.sum(valid))

        q_null = qlike_loss(h_null_t[valid], r2_day_t[valid])
        q_full = qlike_loss(h_full_t[valid], r2_day_t[valid])
        qlike_null = float(np.mean(q_null))
        qlike_full = float(np.mean(q_full))
        improv = (qlike_null - qlike_full) / max(qlike_null, 1e-12)

        # DM-HLN: loss_null - loss_full; positive t = full better
        dm_t, dm_p = dm_test_hln(q_null, q_full)

        # Per-obs log-lik (Student-t) on test rows; LRT analogue = 2*(ll_full-ll_null)
        df_null = float(fit_null["params"][-1])
        df_full = float(fit_full["params"][-1])

        def ll_obs_student(h_hat: np.ndarray, r: np.ndarray, df: float) -> np.ndarray:
            eps = 1e-12
            h = np.maximum(h_hat, eps)
            if df <= 2.0:
                return np.full_like(h, -np.inf)
            log_const = (gammaln((df + 1.0) / 2.0) - gammaln(df / 2.0)
                         - 0.5 * np.log(np.pi * (df - 2.0)))
            return (log_const - 0.5 * np.log(h)
                    - (df + 1.0) / 2.0 * np.log1p(r ** 2 / (h * (df - 2.0))))

        ll_null_obs = ll_obs_student(h_null_t[valid], r_day_t[valid], df_null)
        ll_full_obs = ll_obs_student(h_full_t[valid], r_day_t[valid], df_full)
        ll_null = float(np.sum(ll_null_obs))
        ll_full = float(np.sum(ll_full_obs))
        lrt_oos, p_lrt_oos = lrt_chi2_test(ll_null, ll_full, dof=1)

        # Report
        print(f"    n_valid={n_valid}")
        print(f"    QLIKE null={qlike_null:.4f}  full={qlike_full:.4f}  "
              f"improv={improv*100:+.3f}%")
        print(f"    DM-HLN t={dm_t:.3f}  p={dm_p:.4g}")
        print(f"    OOS LRT chi2={lrt_oos:.3f}  p={p_lrt_oos:.4g}  "
              f"(threshold 1% = 7.88)")

        oos_per_year[y] = {
            "n_train": int(n_tr),
            "n_test": int(n_te),
            "n_test_valid": int(n_valid),
            "qlike_null": qlike_null,
            "qlike_full": qlike_full,
            "qlike_improv_pct": float(improv * 100.0),
            "dm_hln_t": float(dm_t) if np.isfinite(dm_t) else None,
            "dm_hln_p": float(dm_p) if np.isfinite(dm_p) else None,
            "oos_lrt_chi2": float(lrt_oos) if np.isfinite(lrt_oos) else None,
            "oos_lrt_p": float(p_lrt_oos) if np.isfinite(p_lrt_oos) else None,
            "oos_lrt_pass_1pct": bool(np.isfinite(lrt_oos) and lrt_oos > 7.88),
            "ll_null": ll_null,
            "ll_full": ll_full,
            "df_null": df_null,
            "df_full": df_full,
            "xn_coef_train": float(fit_full["params"][9]),
        }

    # ------------------------------------------------------------------
    # C) Verdict logic: H1 vs H2 vs H3
    # ------------------------------------------------------------------
    n_years_pass_is = sum(1 for y in YEARS_ANNUAL
                          if annual_lrt[y]["pass_at_1pct"])
    n_years_pass_oos = sum(1 for y in YEARS_OOS
                            if oos_per_year.get(y, {}).get("oos_lrt_pass_1pct", False))
    # Direction stability: xn coef sign consistency
    xn_signs = [np.sign(annual_fits[y]["M4_night_to_day"]["xn_coef"])
                for y in YEARS_ANNUAL
                if annual_fits[y]["M4_night_to_day"]["xn_coef"] is not None]
    n_positive = int(np.sum(np.array(xn_signs) > 0))
    n_negative = int(np.sum(np.array(xn_signs) < 0))

    # 2020-only driver check
    is_2020_dominant = (
        annual_lrt.get(2020, {}).get("chi2", 0) > 7.88
        and sum(1 for y in [2017, 2018, 2019, 2021]
                if annual_lrt.get(y, {}).get("chi2", 0) > 7.88) == 0
    )

    if n_years_pass_is == 5 and n_positive >= 4:
        verdict = "H1_GENUINE_STRUCTURE"
    elif is_2020_dominant:
        verdict = "H2_COVID_DRIVEN"
    elif n_years_pass_is >= 3:
        verdict = "H3_MIXED_MAJORITY_PASS"
    else:
        verdict = "H3_MIXED_MINORITY_PASS"

    summary = {
        "n_years_is_pass_1pct": int(n_years_pass_is),
        "n_years_oos_pass_1pct": int(n_years_pass_oos),
        "n_positive_xn": int(n_positive),
        "n_negative_xn": int(n_negative),
        "is_2020_dominant": bool(is_2020_dominant),
        "verdict": verdict,
        "verdict_reasoning": {
            "H1_if": "5/5 years IS LRT > 7.88 AND >=4 positive xn coef",
            "H2_if": "2020 alone IS LRT > 7.88, all other years NS",
            "H3_if": "partial pass (3-4 years) OR mixed xn signs",
        },
        "annual_is_lrt_chi2": {
            y: annual_lrt[y]["chi2"] for y in YEARS_ANNUAL
        },
        "annual_xn_coef": {
            y: annual_fits[y]["M4_night_to_day"]["xn_coef"]
            for y in YEARS_ANNUAL
        },
        "annual_oos_qlike_improv_pct": {
            y: oos_per_year.get(y, {}).get("qlike_improv_pct")
            for y in YEARS_OOS
        },
        "annual_oos_dm_t": {
            y: oos_per_year.get(y, {}).get("dm_hln_t")
            for y in YEARS_OOS
        },
        "annual_oos_lrt_chi2": {
            y: oos_per_year.get(y, {}).get("oos_lrt_chi2")
            for y in YEARS_OOS
        },
    }

    print(f"\n[{time.strftime('%H:%M:%S')}] === Summary ===")
    print(f"  IS LRT pass @ 1% (threshold 7.88): {n_years_pass_is}/5 years")
    print(f"  xn coef positive: {n_positive}/{len(xn_signs)} years")
    print(f"  OOS LRT pass @ 1% (threshold 7.88): {n_years_pass_oos}/4 years")
    print(f"  2020-only dominance: {is_2020_dominant}")
    print(f"  VERDICT: {verdict}")

    # ------------------------------------------------------------------
    # D) Plots
    # ------------------------------------------------------------------
    # Plot 1: annual LRT bar
    fig, ax = plt.subplots(1, 1, figsize=(9, 5.5))
    years = YEARS_ANNUAL
    lrts = [annual_lrt[y]["chi2"] for y in years]
    colors = ["#2E86AB" if l > 7.88 else "#C73E1D" for l in lrts]
    bars = ax.bar(years, lrts, color=colors, alpha=0.85, edgecolor="black")
    ax.axhline(7.88, color="#1a1a1a", linestyle="--",
               label=r"$\chi^2_{0.01,1}$ = 7.88")
    ax.axhline(3.84, color="grey", linestyle=":",
               label=r"$\chi^2_{0.05,1}$ = 3.84")
    for bar, lrt in zip(bars, lrts):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.2,
                f"{lrt:.2f}", ha="center", fontsize=10)
    ax.set_xlabel("Year")
    ax.set_ylabel(r"LRT $\chi^2$ (M4 vs M2, df=1)")
    ax.set_title("K1100g_d4 Annual IS LRT (Student-t) — night->day exog coef significance")
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig_path_1 = SCRIPT_DIR / "k1100g_d4_annual_lrt.png"
    fig.savefig(fig_path_1, dpi=150)
    plt.close(fig)
    print(f"  Saved {fig_path_1}")

    # Plot 2: xn coefficient stability + OOS QLIKE improv
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    xn_coefs = [annual_fits[y]["M4_night_to_day"]["xn_coef"] for y in YEARS_ANNUAL]
    colors2 = ["#2E86AB" if x is not None and x > 0 else "#C73E1D" for x in xn_coefs]
    axes[0].bar(YEARS_ANNUAL,
                [x if x is not None else 0 for x in xn_coefs],
                color=colors2, alpha=0.85, edgecolor="black")
    axes[0].axhline(0, color="black", linewidth=0.8)
    axes[0].set_xlabel("Year")
    axes[0].set_ylabel("xn coefficient (night exog on day variance)")
    axes[0].set_title("Annual xn coefficient (M4)")
    axes[0].grid(True, alpha=0.3)

    oos_improvs = [oos_per_year.get(y, {}).get("qlike_improv_pct", 0)
                   for y in YEARS_OOS]
    colors3 = ["#2E86AB" if (v or 0) > 0 else "#C73E1D" for v in oos_improvs]
    axes[1].bar(YEARS_OOS, oos_improvs, color=colors3, alpha=0.85,
                edgecolor="black")
    axes[1].axhline(0, color="black", linewidth=0.8)
    for y, v in zip(YEARS_OOS, oos_improvs):
        if v is not None:
            axes[1].text(y, v + (0.1 if v >= 0 else -0.3),
                         f"{v:+.2f}%", ha="center", fontsize=10)
    axes[1].set_xlabel("Test Year")
    axes[1].set_ylabel("QLIKE improv % (M_full vs M_null)")
    axes[1].set_title("Pseudo-OOS annual QLIKE improvement")
    axes[1].grid(True, alpha=0.3)

    fig.tight_layout()
    fig_path_2 = SCRIPT_DIR / "k1100g_d4_xn_and_oos.png"
    fig.savefig(fig_path_2, dpi=150)
    plt.close(fig)
    print(f"  Saved {fig_path_2}")

    # ------------------------------------------------------------------
    # E) Persist results JSON
    # ------------------------------------------------------------------
    results = {
        "experiment_id": "K1100g_d4",
        "title": "Annual stability of night->day PRG predictability (Student-t)",
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": 42,
        "parent_experiments": ["K1100g_d1", "K1100g_d2", "K1100g_d3"],
        "references": [
            "Bollerslev (1987) A Conditionally Heteroskedastic Time Series Model, RESTAT 69(3) — Student-t GARCH",
            "Engle & Rangel (2008) The Spline-GARCH Model..., RFS 21(3) — tau*g multiplicative PRG",
            "Harvey, Leybourne & Newbold (1997) Testing the equality of prediction mean squared errors, IJF 13(2)",
            "Harvey (2016) Presidential Address: The Scientific Outlook in Financial Economics, JF — t>3 threshold",
        ],
        "hypotheses": {
            "H1": "5/5 years IS LRT > 7.88 and xn coefficient stable (>=4/5 positive) -> genuine structural night->day mechanism.",
            "H2": "Only 2020 IS LRT >> 7.88; other years NS -> COVID regime shift is sole driver; Paper 3 reframe retracted.",
            "H3": "Mixed: 3-4 years pass -> transitional pattern; reframe salvageable with caveat.",
        },
        "data": {
            "source": "TAIFEX TX 2017-2021 (K1100g_d1/d3 session cache)",
            "cache_file": "_cache_taifex_sessions_2017-2021.parquet",
            "n_aligned": int(N),
            "year_counts": {int(k): int(v) for k, v in year_counts.items()},
        },
        "design": {
            "innovation": "student",
            "models": {
                "M2": "day-only PRG (no exog)",
                "M4": "day PRG + r_night[t]^2 contemporaneous exog",
            },
            "annual_fit": "within-year MLE Student-t, 8 L-BFGS-B restarts",
            "pseudo_oos": (
                "Expanding train (all years < y) + frozen params, h recursion through test year; "
                "test year y in {2018, 2019, 2020, 2021}."
            ),
            "lrt_threshold_1pct": 7.88,
            "harvey_t_threshold": 3.0,
        },
        "annual_fits": annual_fits,
        "annual_lrt_tests": annual_lrt,
        "pseudo_oos_by_year": oos_per_year,
        "summary": summary,
        "figures": [str(fig_path_1.name), str(fig_path_2.name)],
    }

    RESULTS_PATH.write_text(
        json.dumps(clean_for_json(results), ensure_ascii=False, indent=2)
    )
    print(f"\n  Saved {RESULTS_PATH}")
    print(f"\nTotal elapsed: {time.time() - t_start:.1f}s")


if __name__ == "__main__":
    run()
