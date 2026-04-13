"""
K1100g_d5 — Overnight gap^2 替代 night session r^2 (Student-t PRG)
=================================================================

Parent:
  - K1100g     : TAIFEX overnight/intraday vol ratio = 1.586 (vs SPY 1.001)
                 Paper 3 reframe anchor
  - K1100g_d1  : night session r^2 exog → IS LRT 12.48 significant (Normal)
  - K1100g_d2  : Normal OOS completely rejected (DM -0.21, QLIKE -0.48%)
  - K1100g_d3  : Student-t OOS 部分救回 (LRT 14.61, QLIKE +3.78%, DM t=1.92
                 BORDERLINE, 未過 Harvey 2016 threshold |t|>3)
  - K1100g_d4  : annual stability 弱 (0/5 年 IS LRT > 7.88)

Motivation (K1100g_d5 hypothesis):
  K1100g 原始 ratio 1.586 被 K1100g_d1 揭示為 **gap effect**（13:45→15:00
  close-to-open + 05:00→08:45 overnight gap 兩個 jump 期集中了 session-ratio
  的變異）。K1100g_d3 用 5-min aggregated night r^2 做 exog 得到 borderline
  DM t=1.92。若 gap 才是真正 info carrier (不是整個夜盤 5-min RV),
  改用**純 gap^2** 作 exog 理論上應該更強。

Design:
  Gap^2 construction (cache has all columns needed):
    gap_day[t]   = log(night_open_t / day_close_t)
                   15:00 night open vs 13:45 day close — same-day close→open
    gap_night[t] = log(day_open_t / night_close_{t-1})
                   08:45 day open vs 05:00 night close — overnight close→open
    (= r_overnight_gap in cache)

  Information set for predicting r_day[t]^2:
    - gap_night[t]^2 is KNOWN at 08:45 day t (just before day session opens) ✓
    - gap_day[t]^2 happens 13:45 day t (AFTER day session closes) ✗ lookahead
    - gap_day[t-1]^2 is KNOWN (yesterday's close→night open) ✓ lagged

  Combined gap exog:
    gap2_exog[t] = gap_night[t]^2 + gap_day[t-1]^2  (both legal)

  Also tested separately:
    M2_gap_night : day PRG + gap_night[t]^2 only (most aligned contemp info)
    M2_gap_day   : day PRG + gap_day[t-1]^2 only (pure day-close lagged)
    M2_gap_total : day PRG + gap2_exog[t] (union)
    M2_signed    : day PRG + gap_night[t] (signed, asymmetric test — not ^2)

Models:
  M1            day-only PRG (baseline, no exog)
  M2_gap_total  M1 + (gap_night[t]^2 + gap_day[t-1]^2)  contemporaneous*
  M2_gap_night  M1 + gap_night[t]^2                     contemporaneous
  M2_gap_day    M1 + gap_day[t-1]^2                     lagged
  M2_signed_gn  M1 + gap_night[t] signed (test asymmetric gap direction)
  REF_night_r2  M1 + r_night[t]^2  (K1100g_d3 M4 spec, for direct comparison)

  * "contemporaneous" here means the exog at index t is known before r_day[t]
    is realized (same info-set logic as K1100g_d3).

All models use Student-t innovation (K1100g_d3 lesson: TAIFEX heavy-tailed,
Normal QML mis-specifies).

Evaluation:
  IS  : LRT vs M1 (dof=1 for single-exog, dof=2 for gap_total)
  OOS : expanding-window refit every 5 days, train 2017-2019, test 2020-2021
        (identical cadence to K1100g_d3)
  DM  : HLN-corrected, pairwise — each M2 variant vs M1
        Critical: **M2_gap_night vs REF_night_r2** — who carries more info?

Hypotheses:
  H1 gap_saves   : M2_gap_total OOS DM-HLN |t| > 3.0 (Harvey pass)
                   AND QLIKE improv > 1%  AND LRT > 7.88
                   → pure gap info stronger than 5-min night RV
  H2 both_similar: gap stats comparable to REF_night_r2 (DM t similar)
                   → gap ≈ night RV, just redundant decomposition
  H3 night_better: REF_night_r2 stronger (DM t_REF > t_gap)
                   → 5-min RV contains info beyond gap jumps

Lookahead discipline:
  - gap_night[t] uses day_open[t] and night_close[t-1] — both realized
    BEFORE r_day[t] starts (08:45 day t). LEGAL.
  - gap_day[t-1] uses night_open[t-1] and day_close[t-1] — lagged. LEGAL.
  - Student-t innovation (K1100g_d3 lesson).
  - seed=42; L-BFGS-B deterministic.

Author: Claude (worktree agent-af9d1ed4)
Date: 2026-04-13
Seed: 42
References:
  - Bollerslev (1987) RESTAT — Student-t GARCH
  - Engle & Rangel (2008) RFS — PRG tau*g
  - Harvey et al. (1997) IJF — HLN DM correction
  - Harvey (2016) JF — t>3 threshold
  - French & Roll (1986) JFE — non-trading-hours information
  - Andersen et al. (2011) JoE — overnight jump contribution to volatility
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
RESULTS_PATH = SCRIPT_DIR / "k1100g_d5_results.json"

# Train/test split — identical to K1100g_d3 for apples-to-apples comparison
TRAIN_START = pd.Timestamp("2017-01-01")
TRAIN_END = pd.Timestamp("2019-12-31")
TEST_START = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2021-12-31")
REFIT_EVERY = 5


# ----------------------------------------------------------------------
# 1. PRG kernel (Student-t; identical to K1100g_d3)
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
    """Standard PRG recursion — exog is 1-d here; extended in gap_total."""
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
    """Student-t MLE NLL for PRG (scale s.t. Var(r)=h)."""
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
    """Fit PRG under Student-t innovation via L-BFGS-B multi-start."""
    r = np.asarray(r, dtype=float)
    use_exog = exog is not None
    local_rng = np.random.default_rng(42)
    best = {"nll": np.inf, "params": None, "success": False}

    prg_base_dim = 10 if use_exog else 9
    dim = prg_base_dim + 1  # student: +df

    for trial in range(n_restarts):
        uncond = float(np.var(r, ddof=1))
        if trial == 0 and x0_warm is not None and len(x0_warm) == dim:
            x0 = np.array(x0_warm, dtype=float).copy()
        elif trial == 0:
            x0 = np.array([uncond * 0.5, 0.05, 0.0, 0.0, 0.0, 0.0,
                           0.05, 0.05, 0.80])
            if use_exog:
                x0 = np.concatenate([x0, [0.0]])
            x0 = np.concatenate([x0, [8.0]])
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
        bounds.append((2.05, 200.0))

        try:
            res = optimize.minimize(
                prg_nll_student, x0, args=(r, dow_dum, exog, exog_contemp),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-8},
            )
            if res.success and res.fun < best["nll"]:
                best = {"nll": float(res.fun),
                        "params": res.x.copy(),
                        "success": True,
                        "trial": trial}
        except Exception:
            continue

    return best


def prg_variance_path_student(params: np.ndarray, r: np.ndarray,
                              dow_dum: np.ndarray,
                              exog: Optional[np.ndarray] = None,
                              exog_contemp: bool = False) -> np.ndarray:
    """Forward h path from fitted Student-t params."""
    if params is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    prg_params = params[:-1]  # drop df
    h = _prg_variance_recursion(prg_params, r, dow_dum, exog, exog_contemp)
    if h is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    return h


# ----------------------------------------------------------------------
# 2. Eval utilities (identical to K1100g_d3)
# ----------------------------------------------------------------------
def qlike_loss(h_hat: np.ndarray, r2: np.ndarray) -> np.ndarray:
    eps = 1e-10
    ratio = r2 / np.maximum(h_hat, eps)
    return ratio - np.log(np.maximum(ratio, eps)) - 1.0


def student_loglik_per_obs(h_hat: np.ndarray, r: np.ndarray,
                           df: float) -> np.ndarray:
    eps = 1e-12
    h = np.maximum(h_hat, eps)
    if df <= 2.0:
        return np.full_like(h, -np.inf)
    log_const = (gammaln((df + 1.0) / 2.0) - gammaln(df / 2.0)
                 - 0.5 * np.log(np.pi * (df - 2.0)))
    return (log_const - 0.5 * np.log(h)
            - (df + 1.0) / 2.0 * np.log1p(r ** 2 / (h * (df - 2.0))))


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
# 3. OOS expanding-window (Student-t) — generic over exog series
# ----------------------------------------------------------------------
def expanding_oos_student(r_day: np.ndarray, dow_dum: np.ndarray,
                          exog: Optional[np.ndarray],
                          exog_contemp: bool,
                          test_start_idx: int,
                          label: str = "",
                          refit_every: int = REFIT_EVERY) -> Dict:
    """Expanding-window OOS refit under Student-t. Generic over exog.
    If exog is None → M_null (no exog).
    """
    N = len(r_day)
    h_oos = np.full(N, np.nan)
    df_log = np.full(N, np.nan)
    params_log: List[Tuple[int, List[float]]] = []
    current_params: Optional[np.ndarray] = None

    for t in range(test_start_idx, N):
        steps = t - test_start_idx
        need_refit = (steps % refit_every == 0)
        if need_refit:
            r_train = r_day[:t]
            dow_train = dow_dum[:t]
            if exog is not None:
                exog_train = exog[:t]
                fit = fit_prg_student(r_train, dow_train,
                                      exog=exog_train,
                                      exog_contemp=exog_contemp,
                                      n_restarts=4, x0_warm=current_params)
            else:
                fit = fit_prg_student(r_train, dow_train,
                                      exog=None,
                                      exog_contemp=False,
                                      n_restarts=4, x0_warm=current_params)
            if fit["success"]:
                current_params = fit["params"]
                params_log.append((int(t), current_params.tolist()))
            else:
                # retry without warm start
                if exog is not None:
                    fit = fit_prg_student(r_train, dow_train,
                                          exog=exog[:t],
                                          exog_contemp=exog_contemp,
                                          n_restarts=6, x0_warm=None)
                else:
                    fit = fit_prg_student(r_train, dow_train,
                                          exog=None, exog_contemp=False,
                                          n_restarts=6, x0_warm=None)
                if fit["success"]:
                    current_params = fit["params"]
                    params_log.append((int(t), current_params.tolist()))
                else:
                    print(f"  [warn {label}] refit failed at t={t}")
        if current_params is None:
            continue

        df_t = float(current_params[-1])
        df_log[t] = df_t
        r_slice = r_day[:t + 1]
        dow_slice = dow_dum[:t + 1]
        if exog is not None:
            exog_slice = exog[:t + 1]
            h_path = prg_variance_path_student(current_params, r_slice,
                                               dow_slice, exog=exog_slice,
                                               exog_contemp=exog_contemp)
        else:
            h_path = prg_variance_path_student(current_params, r_slice,
                                               dow_slice, exog=None,
                                               exog_contemp=False)
        h_oos[t] = h_path[t]

    return {
        "h_oos": h_oos,
        "df_log": df_log,
        "params_log": params_log,
        "n_refits": len(params_log),
    }


# ----------------------------------------------------------------------
# 4. clean_for_json
# ----------------------------------------------------------------------
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

    # Construct gap series (all operate on cache columns — no new data)
    # gap_day[t]   = log(night_open[t] / day_close[t])
    # gap_night[t] = log(day_open[t] / night_close[t-1]) = r_overnight_gap
    df["gap_day_t"] = np.log(df["night_open"] / df["day_close"])
    df["gap_night_t"] = df["r_overnight_gap"]  # already computed in cache

    # Lagged gap_day (gap_day[t-1]) — info known at 08:45 day t
    df["gap_day_lag"] = df["gap_day_t"].shift(1)

    # For filter alignment: need r_day, r_night, r_combined (matches K1100g_d3)
    # AND the two gap signals valid
    mdf = df.dropna(subset=["r_day", "r_night", "r_combined",
                             "gap_night_t", "gap_day_lag"]).copy()
    mdf = mdf.reset_index(drop=True)
    N = len(mdf)
    print(f"  Aligned rows: {N}")

    dates_ts = pd.to_datetime(mdf["date"])
    dow_arr = mdf["dow"].values.astype(int)
    dow_dum = make_dow_dummies(dow_arr)

    r_day = mdf["r_day"].values.astype(float)
    r_night = mdf["r_night"].values.astype(float)
    r_night2 = r_night ** 2

    gap_night_t = mdf["gap_night_t"].values.astype(float)
    gap_day_lag = mdf["gap_day_lag"].values.astype(float)
    gap_night_t2 = gap_night_t ** 2
    gap_day_lag2 = gap_day_lag ** 2
    gap_total = gap_night_t2 + gap_day_lag2  # union of legal gap info

    # Descriptives (gap series)
    print("  --- Gap series descriptives ---")
    for name, x in [("gap_night_t", gap_night_t),
                    ("gap_day_lag", gap_day_lag)]:
        print(f"    {name}: mean={np.mean(x):+.2e}  sd={np.std(x):.4e}  "
              f"kurt={kurt_fn(x, fisher=True):.2f}  "
              f"skew={skew_fn(x):.3f}")
    print(f"    gap_total sd={np.std(gap_total):.3e}  "
          f"ratio gap_total/r_night2 var = "
          f"{np.var(gap_total)/np.var(r_night2):.3f}")

    # ------------------------------------------------------------------
    # A) IS full-sample fits (Student-t only, per K1100g_d3 lesson)
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === IS fits (Student-t) ===")
    # model_key: (target_r_series, exog_series, exog_contemp, k_prg_base)
    is_specs = [
        ("M1_baseline",      r_day, None,         False, 9),
        ("M2_gap_night",     r_day, gap_night_t2, True,  10),
        ("M2_gap_day_lag",   r_day, gap_day_lag2, True,  10),  # contemp=True since series is already lagged at construction
        ("M2_gap_total",     r_day, gap_total,    True,  10),
        ("M2_signed_gn",     r_day, gap_night_t,  True,  10),  # signed, asym test
        ("REF_night_r2",     r_day, r_night2,     True,  10),  # K1100g_d3 M4 spec
    ]
    is_fits: Dict[str, Dict] = {}
    for name, rser, exog, exog_contemp, k_prg in is_specs:
        print(f"  [{time.strftime('%H:%M:%S')}] fitting {name} ...")
        fit = fit_prg_student(rser, dow_dum,
                              exog=exog, exog_contemp=exog_contemp,
                              n_restarts=8)
        nll = fit["nll"]
        ll = -nll if np.isfinite(nll) else None
        k_eff = k_prg + 1
        aic = (2 * k_eff + 2 * nll) if np.isfinite(nll) else None
        bic = (k_eff * np.log(len(rser) - 1) + 2 * nll) if np.isfinite(nll) else None
        df_est = float(fit["params"][-1]) if (fit["params"] is not None) else None
        xn_coef = None
        if fit["params"] is not None and k_prg == 10:
            xn_coef = float(fit["params"][9])
        is_fits[name] = {
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
        xn_str = f" xn={xn_coef:+.4f}" if xn_coef is not None else ""
        print(f"    ll={ll_str}{df_str}{xn_str}  success={fit['success']}")

    # ------------------------------------------------------------------
    # B) IS LRT: each exog model vs M1 baseline
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === IS LRT (vs M1_baseline) ===")
    ll_base = is_fits["M1_baseline"]["log_lik"]
    is_lrt: Dict[str, Dict] = {}
    for name in ["M2_gap_night", "M2_gap_day_lag", "M2_gap_total",
                 "M2_signed_gn", "REF_night_r2"]:
        ll_f = is_fits[name]["log_lik"]
        stat, pval = lrt_chi2_test(ll_base, ll_f, dof=1)
        is_lrt[name] = {"chi2": stat, "p_value": pval}
        print(f"  {name} vs M1: chi2={stat:.3f}  p={pval:.4g}")

    # ------------------------------------------------------------------
    # C) OOS expanding-window (Student-t)
    #    Run baseline once + each exog variant
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === OOS expanding-window ===")
    train_mask = (dates_ts >= TRAIN_START) & (dates_ts <= TRAIN_END)
    test_mask = (dates_ts >= TEST_START) & (dates_ts <= TEST_END)
    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]
    test_start_idx = int(test_idx[0])
    test_end_idx = int(test_idx[-1])
    print(f"  Train: n={len(train_idx)}  Test: n={len(test_idx)}")

    oos_runs: Dict[str, Dict] = {}
    oos_specs = [
        ("M1_baseline",      None,         False),
        ("M2_gap_night",     gap_night_t2, True),
        ("M2_gap_day_lag",   gap_day_lag2, True),
        ("M2_gap_total",     gap_total,    True),
        ("M2_signed_gn",     gap_night_t,  True),
        ("REF_night_r2",     r_night2,     True),
    ]
    for name, exog, exog_contemp in oos_specs:
        t_oos = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] OOS {name} ...")
        res = expanding_oos_student(r_day, dow_dum, exog, exog_contemp,
                                    test_start_idx, label=name,
                                    refit_every=REFIT_EVERY)
        print(f"  refits={res['n_refits']}  elapsed={time.time() - t_oos:.1f}s")
        oos_runs[name] = res

    # ------------------------------------------------------------------
    # D) Compute OOS metrics: QLIKE, log-lik, DM, LRT
    # ------------------------------------------------------------------
    test_slice = slice(test_start_idx, test_end_idx + 1)
    r_day_test = r_day[test_slice]
    r2_day_test = r_day_test ** 2
    dates_test = dates_ts.iloc[test_slice].values

    def pack_metrics(name: str, base_name: str = "M1_baseline"):
        h_test = oos_runs[name]["h_oos"][test_slice]
        df_test = oos_runs[name]["df_log"][test_slice]
        h_base = oos_runs[base_name]["h_oos"][test_slice]
        df_base = oos_runs[base_name]["df_log"][test_slice]
        valid = (np.isfinite(h_test) & np.isfinite(h_base)
                 & np.isfinite(df_test) & np.isfinite(df_base))
        n_valid = int(valid.sum())
        r_v = r_day_test[valid]
        r2_v = r2_day_test[valid]
        h_v = h_test[valid]
        h_b = h_base[valid]
        df_v = df_test[valid]
        df_b = df_base[valid]
        d_test = pd.to_datetime(dates_test[valid])

        q_test = qlike_loss(h_v, r2_v)
        q_base = qlike_loss(h_b, r2_v)
        ll_test_obs = np.array([
            float(student_loglik_per_obs(np.array([h_v[i]]),
                                         np.array([r_v[i]]), df_v[i])[0])
            for i in range(n_valid)])
        ll_base_obs = np.array([
            float(student_loglik_per_obs(np.array([h_b[i]]),
                                         np.array([r_v[i]]), df_b[i])[0])
            for i in range(n_valid)])

        ll_test_sum = float(np.sum(ll_test_obs))
        ll_base_sum = float(np.sum(ll_base_obs))
        lrt_stat, lrt_p = lrt_chi2_test(ll_base_sum, ll_test_sum, dof=1)
        dm_q_t, dm_q_p = dm_test_hln(q_base, q_test)
        dm_ll_t, dm_ll_p = dm_test_hln(-ll_base_obs, -ll_test_obs)

        q_base_mean = float(np.mean(q_base))
        q_test_mean = float(np.mean(q_test))
        imp_pct = ((q_base_mean - q_test_mean) / abs(q_base_mean) * 100
                   if q_base_mean != 0 else np.nan)

        # Sub-period
        mask_2020 = (d_test >= pd.Timestamp("2020-01-01")) & \
                    (d_test <= pd.Timestamp("2020-12-31"))
        mask_2021 = (d_test >= pd.Timestamp("2021-01-01")) & \
                    (d_test <= pd.Timestamp("2021-12-31"))

        def sub_stats(mask):
            if mask.sum() < 30:
                return None
            qb = q_base[mask]; qt = q_test[mask]
            lb = float(np.sum(ll_base_obs[mask]))
            lt = float(np.sum(ll_test_obs[mask]))
            lr, pp = lrt_chi2_test(lb, lt, dof=1)
            dt_, dp_ = dm_test_hln(qb, qt)
            qbm = float(np.mean(qb))
            qtm = float(np.mean(qt))
            imp = (qbm - qtm) / abs(qbm) * 100 if qbm != 0 else np.nan
            return {
                "n": int(mask.sum()),
                "qlike_base_mean": qbm, "qlike_test_mean": qtm,
                "qlike_improv_pct": float(imp) if np.isfinite(imp) else None,
                "lrt_chi2": float(lr), "lrt_p": float(pp),
                "dm_t_hln": float(dt_) if np.isfinite(dt_) else None,
                "dm_p": float(dp_) if np.isfinite(dp_) else None,
            }

        return {
            "n_valid": n_valid,
            "lrt_chi2": float(lrt_stat) if np.isfinite(lrt_stat) else None,
            "lrt_p": float(lrt_p) if np.isfinite(lrt_p) else None,
            "dm_qlike_t_hln": float(dm_q_t) if np.isfinite(dm_q_t) else None,
            "dm_qlike_p": float(dm_q_p) if np.isfinite(dm_q_p) else None,
            "dm_loglik_t_hln": float(dm_ll_t) if np.isfinite(dm_ll_t) else None,
            "dm_loglik_p": float(dm_ll_p) if np.isfinite(dm_ll_p) else None,
            "qlike_base_mean": q_base_mean,
            "qlike_test_mean": q_test_mean,
            "qlike_improv_pct": float(imp_pct) if np.isfinite(imp_pct) else None,
            "ll_base_sum": ll_base_sum,
            "ll_test_sum": ll_test_sum,
            "df_test_mean": float(np.mean(df_v)),
            "df_base_mean": float(np.mean(df_b)),
            "sub_2020": sub_stats(mask_2020),
            "sub_2021": sub_stats(mask_2021),
            # Also expose arrays for cross-model DM (test vs ref)
            "_internals": {
                "q_test": q_test, "q_base": q_base,
                "ll_test_obs": ll_test_obs, "ll_base_obs": ll_base_obs,
                "dates_v": d_test,
            }
        }

    oos_metrics: Dict[str, Dict] = {}
    for name in ["M2_gap_night", "M2_gap_day_lag", "M2_gap_total",
                 "M2_signed_gn", "REF_night_r2"]:
        oos_metrics[name] = pack_metrics(name)

    print(f"\n[{time.strftime('%H:%M:%S')}] === OOS summary ===")
    print(f"  {'model':<18} {'n':>4}  {'LRT_chi2':>10}  {'DM_QLIKE t':>11}  "
          f"{'QLIKE %':>8}  {'LL Δ':>8}")
    for name, m in oos_metrics.items():
        lrt = m.get("lrt_chi2")
        dm = m.get("dm_qlike_t_hln")
        imp = m.get("qlike_improv_pct")
        lldelta = (m.get("ll_test_sum", 0) - m.get("ll_base_sum", 0)) \
                   if m.get("ll_test_sum") is not None else None
        print(f"  {name:<18} {m['n_valid']:>4}  "
              f"{lrt if lrt is not None else float('nan'):>10.3f}  "
              f"{dm if dm is not None else float('nan'):>11.3f}  "
              f"{imp if imp is not None else float('nan'):>+8.2f}%  "
              f"{lldelta if lldelta is not None else float('nan'):>+8.2f}")

    # ------------------------------------------------------------------
    # E) Critical cross-model comparison: gap_night vs REF_night_r2
    #    DM between gap and night 5-min RV info carriers
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === Cross-model DM "
          f"(gap vs night_r2) ===")
    cross = {}
    for a, b in [("M2_gap_night", "REF_night_r2"),
                 ("M2_gap_total", "REF_night_r2"),
                 ("M2_gap_night", "M2_gap_total")]:
        # Need both evaluated against common baseline
        q_a = oos_metrics[a]["_internals"]["q_test"]
        q_b = oos_metrics[b]["_internals"]["q_test"]
        # But their valid masks may differ - intersect by test_slice index
        # Simpler: recompute with intersection of validity
        h_a_test = oos_runs[a]["h_oos"][test_slice]
        df_a_test = oos_runs[a]["df_log"][test_slice]
        h_b_test = oos_runs[b]["h_oos"][test_slice]
        df_b_test = oos_runs[b]["df_log"][test_slice]
        valid = (np.isfinite(h_a_test) & np.isfinite(df_a_test)
                 & np.isfinite(h_b_test) & np.isfinite(df_b_test))
        n_valid = int(valid.sum())
        r_v = r_day_test[valid]; r2_v = r_v ** 2
        h_a = h_a_test[valid]; df_a = df_a_test[valid]
        h_b = h_b_test[valid]; df_b = df_b_test[valid]
        qa = qlike_loss(h_a, r2_v)
        qb = qlike_loss(h_b, r2_v)
        ll_a = np.array([
            float(student_loglik_per_obs(np.array([h_a[i]]),
                                         np.array([r_v[i]]), df_a[i])[0])
            for i in range(n_valid)])
        ll_b = np.array([
            float(student_loglik_per_obs(np.array([h_b[i]]),
                                         np.array([r_v[i]]), df_b[i])[0])
            for i in range(n_valid)])
        # DM(qa vs qb): positive t_hln = qa > qb (b better)
        dm_t, dm_p = dm_test_hln(qa, qb)
        dm_ll_t, dm_ll_p = dm_test_hln(-ll_a, -ll_b)
        cross[f"{a}_vs_{b}"] = {
            "n_valid": n_valid,
            "qlike_a": float(np.mean(qa)),
            "qlike_b": float(np.mean(qb)),
            "dm_qlike_t_hln": float(dm_t) if np.isfinite(dm_t) else None,
            "dm_qlike_p": float(dm_p) if np.isfinite(dm_p) else None,
            "dm_loglik_t_hln": float(dm_ll_t) if np.isfinite(dm_ll_t) else None,
            "dm_loglik_p": float(dm_ll_p) if np.isfinite(dm_ll_p) else None,
        }
        print(f"  {a} vs {b}: DM_qlike t={dm_t:+.3f} p={dm_p:.3g}  "
              f"DM_ll t={dm_ll_t:+.3f}  "
              f"(qlike_a={np.mean(qa):.5f} qlike_b={np.mean(qb):.5f})")

    # ------------------------------------------------------------------
    # F) Verdict H1/H2/H3
    # ------------------------------------------------------------------
    # Focus on M2_gap_total (combined gap info) vs M1 baseline
    primary = oos_metrics["M2_gap_total"]
    ref = oos_metrics["REF_night_r2"]
    harvey_pass = (primary.get("dm_qlike_t_hln") is not None
                   and abs(primary["dm_qlike_t_hln"]) > 3.0)
    lrt_strong = (primary.get("lrt_chi2") is not None
                  and primary["lrt_chi2"] > 7.88)
    qlike_mean = (primary.get("qlike_improv_pct") is not None
                  and primary["qlike_improv_pct"] > 1.0)
    # compare gap vs night_r2 DM strength
    gap_dm = primary.get("dm_qlike_t_hln", 0.0) or 0.0
    ref_dm = ref.get("dm_qlike_t_hln", 0.0) or 0.0

    if harvey_pass and qlike_mean and lrt_strong:
        verdict = "H1_GAP_SAVES"
        explanation = (
            "Gap^2 (night+day-lag) exog passes Harvey (2016) t>3 threshold, "
            "OOS LRT>7.88, QLIKE improv>1%. Pure gap information is the true "
            "info carrier — K1100g Paper 3 reframe anchor established."
        )
    elif abs(gap_dm - ref_dm) < 0.5 and (abs(gap_dm) > 1.5 or abs(ref_dm) > 1.5):
        verdict = "H2_GAP_AND_NIGHT_SIMILAR"
        explanation = (
            f"M2_gap_total DM t = {gap_dm:+.2f} vs REF_night_r2 DM t = "
            f"{ref_dm:+.2f} comparable magnitude. Gap^2 does NOT clearly "
            f"dominate night 5-min RV — Paper 3 reframe remains borderline, "
            f"same signal-strength class as K1100g_d3."
        )
    elif abs(gap_dm) < abs(ref_dm) - 0.5:
        verdict = "H3_NIGHT_R2_BETTER"
        explanation = (
            f"REF_night_r2 DM t = {ref_dm:+.2f} dominates M2_gap_total "
            f"DM t = {gap_dm:+.2f}. Pure gap^2 UNDERPERFORMS 5-min night RV; "
            f"true info carrier is intra-session night movement, not just gaps."
        )
    else:
        verdict = "H_MIXED_INCONCLUSIVE"
        explanation = (
            f"M2_gap_total DM t={gap_dm:+.2f}, REF_night_r2 DM t={ref_dm:+.2f}. "
            "Neither Harvey-robust, nor cleanly ordered — effect remains "
            "borderline at this N."
        )

    # Self-check on huge DM t-stats (preamble rule #5)
    sanity_flag: List[str] = []
    for name, m in oos_metrics.items():
        dm = m.get("dm_qlike_t_hln")
        if dm is not None and abs(dm) > 6.0:
            sanity_flag.append(f"{name} DM t={dm:+.2f} > 6: suspicious, review")

    # ------------------------------------------------------------------
    # G) Compile result
    # ------------------------------------------------------------------
    # Remove _internals from oos_metrics before serialization
    for name in list(oos_metrics.keys()):
        oos_metrics[name].pop("_internals", None)

    result = {
        "experiment_id": "K1100g_d5",
        "title": ("Overnight gap^2 as info carrier (Student-t PRG) — "
                  "night+day-lag gap vs 5-min night RV"),
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": 42,
        "references": [
            "Bollerslev (1987) RESTAT 69(3) — Student-t GARCH",
            "Engle & Rangel (2008) RFS 21(3) — tau*g multiplicative PRG",
            "French & Roll (1986) JFE 17(1), 5-26 — Non-trading hour information",
            "Andersen, Bollerslev, Huang (2011) JoE 160(1) — Overnight jumps",
            "Harvey, Leybourne & Newbold (1997) IJF — HLN DM correction",
            "Harvey (2016) JF — t>3 threshold",
        ],
        "data": {
            "source": "TAIFEX TX 2017-2021 (K1100g_d1 tick-derived session cache)",
            "cache_file": str(SESSIONS_CACHE.name),
            "n_aligned": int(N),
            "gap_descriptives": {
                "gap_night_t": {
                    "mean": float(np.mean(gap_night_t)),
                    "sd": float(np.std(gap_night_t)),
                    "skew": float(skew_fn(gap_night_t)),
                    "excess_kurt": float(kurt_fn(gap_night_t, fisher=True)),
                },
                "gap_day_lag": {
                    "mean": float(np.mean(gap_day_lag)),
                    "sd": float(np.std(gap_day_lag)),
                    "skew": float(skew_fn(gap_day_lag)),
                    "excess_kurt": float(kurt_fn(gap_day_lag, fisher=True)),
                },
                "gap_total": {
                    "mean": float(np.mean(gap_total)),
                    "sd": float(np.std(gap_total)),
                },
                "var_ratio_gap_total_to_night_r2": float(
                    np.var(gap_total) / np.var(r_night2)),
            },
        },
        "design": {
            "innovation": "student",
            "prg_kernel": "tau*g multiplicative, Student-t innovation "
                          "(Var(r)=h)",
            "models": {
                "M1_baseline": "day-only PRG (no exog)",
                "M2_gap_night": "M1 + gap_night[t]^2 contemp (overnight gap only)",
                "M2_gap_day_lag": "M1 + gap_day[t-1]^2 lagged (prev day close-to-night-open)",
                "M2_gap_total": "M1 + gap_night[t]^2 + gap_day[t-1]^2 (all legal gap info)",
                "M2_signed_gn": "M1 + gap_night[t] signed (asymmetry test, NOT ^2)",
                "REF_night_r2": "M1 + r_night[t]^2 (K1100g_d3 M4 spec, benchmark)",
            },
            "train_start": str(TRAIN_START.date()),
            "train_end": str(TRAIN_END.date()),
            "test_start": str(TEST_START.date()),
            "test_end": str(TEST_END.date()),
            "refit_every": REFIT_EVERY,
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
        },
        "is_fits": is_fits,
        "is_lrt_vs_M1": is_lrt,
        "oos_metrics": oos_metrics,
        "cross_model_dm": cross,
        "verdict": {
            "primary": verdict,
            "explanation": explanation,
            "criteria_detail": {
                "gap_total_harvey_dm_gt_3": bool(harvey_pass),
                "gap_total_lrt_gt_7_88": bool(lrt_strong),
                "gap_total_qlike_improv_gt_1pct": bool(qlike_mean),
                "gap_total_dm_t_hln": primary.get("dm_qlike_t_hln"),
                "ref_night_r2_dm_t_hln": ref.get("dm_qlike_t_hln"),
                "gap_minus_ref_dm_diff": (gap_dm - ref_dm),
            },
            "sanity_flags": sanity_flag,
            "paper3_reframe_anchor_strengthened": bool(harvey_pass),
        },
        "limitations": [
            "OOS N ≈ 464 test obs still below Harvey asymptotic comfort zone",
            "Gaussian gap^2 assumption ignores occasional extreme gaps (e.g. "
            "flash-crash) — robustness could use winsorized gap",
            "gap_day_lag adds 1-day lag information, but gap_night and r_night "
            "share overlap (r_night includes 15:00 open -> 05:00 close, "
            "while gap_night includes 05:00 -> 08:45 morning gap — "
            "small overlap at the join)",
            "Single market (TAIFEX). Cross-market replication (SPY overnight "
            "gap, N225 Tokyo overnight) still open.",
            "Symmetric Student-t; TAIFEX night skew ≈ −1.6 suggests asymmetric-t "
            "(Hansen 1994) may further refine.",
        ],
    }
    result = clean_for_json(result)
    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(f"[OK] results -> {RESULTS_PATH.name}")

    # ------------------------------------------------------------------
    # H) Plots
    # ------------------------------------------------------------------
    plot_all(is_lrt, oos_metrics, cross, dates_test, r_day_test, oos_runs,
             test_slice)

    print(f"\n[{time.strftime('%H:%M:%S')}] === Verdict: {verdict} ===")
    print(f"  {explanation}")
    if sanity_flag:
        print("  [sanity flags]:")
        for s in sanity_flag:
            print(f"    - {s}")
    print(f"\n[DONE] Total: {time.time() - t0:.1f}s")
    return result


def plot_all(is_lrt, oos_metrics, cross, dates_test, r_day_test,
             oos_runs, test_slice):
    # Plot 1: IS LRT bar chart (each exog variant vs M1)
    fig, ax = plt.subplots(figsize=(10, 5))
    names = ["M2_gap_night", "M2_gap_day_lag", "M2_gap_total",
             "M2_signed_gn", "REF_night_r2"]
    chi2_vals = [is_lrt[n]["chi2"] if is_lrt[n]["chi2"] is not None
                 else 0.0 for n in names]
    colors = ["#2ca02c", "#98df8a", "#1f77b4", "#ff7f0e", "#d62728"]
    bars = ax.bar(range(len(names)), chi2_vals, color=colors, alpha=0.85)
    ax.axhline(3.84, linestyle="--", color="#444", alpha=0.6,
               label="chi2(1, p=0.05)=3.84")
    ax.axhline(7.88, linestyle=":", color="#666", alpha=0.6,
               label="chi2(1, p=0.005)=7.88")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([n.replace("_", "\n") for n in names], fontsize=9)
    ax.set_ylabel("IS LRT chi2 statistic")
    ax.set_title("K1100g_d5 IS LRT — each exog variant vs M1 baseline "
                 "(Student-t)")
    for b, v in zip(bars, chi2_vals):
        ax.text(b.get_x() + b.get_width() / 2,
                v + max(chi2_vals) * 0.01,
                f"{v:.2f}", ha="center", fontsize=9)
    ax.legend(loc="upper right")
    ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d5_is_lrt_bar.png", dpi=120)
    plt.close()

    # Plot 2: OOS 30-day rolling QLIKE(null)-QLIKE(test) for gap vs night_r2
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    ax1, ax2 = axes

    h_base = oos_runs["M1_baseline"]["h_oos"][test_slice]
    for name, color, label in [
        ("M2_gap_total", "#1f77b4", "M2_gap_total (night+day-lag gap^2)"),
        ("REF_night_r2", "#d62728", "REF_night_r2 (5-min night RV)"),
    ]:
        h_t = oos_runs[name]["h_oos"][test_slice]
        valid = np.isfinite(h_t) & np.isfinite(h_base)
        if valid.sum() < 30:
            continue
        r_v = r_day_test[valid]
        r2_v = r_v ** 2
        q_b = qlike_loss(h_base[valid], r2_v)
        q_t = qlike_loss(h_t[valid], r2_v)
        diff = q_b - q_t  # positive = exog improves over baseline
        d_v = pd.to_datetime(dates_test[valid])
        roll = pd.Series(diff, index=d_v).rolling(30).mean()
        ax1.plot(roll.index, roll.values, color=color, lw=1.4, label=label)
    ax1.axhline(0, color="black", lw=0.8)
    ax1.set_ylabel("30d mean QLIKE(M1) − QLIKE(exog)")
    ax1.set_title("K1100g_d5 OOS QLIKE improvement over baseline — "
                  "gap^2 vs night_r^2")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(alpha=0.3)

    # Plot 2 bottom: DM stats bar (each model's DM vs M1)
    dm_names = ["M2_gap_night", "M2_gap_day_lag", "M2_gap_total",
                "M2_signed_gn", "REF_night_r2"]
    dm_vals = [oos_metrics[n].get("dm_qlike_t_hln") for n in dm_names]
    dm_vals_plot = [v if v is not None else 0.0 for v in dm_vals]
    colors2 = ["#2ca02c", "#98df8a", "#1f77b4", "#ff7f0e", "#d62728"]
    bars = ax2.bar(range(len(dm_names)), dm_vals_plot, color=colors2,
                   alpha=0.85)
    ax2.axhline(3.0, linestyle="--", color="#444", alpha=0.7,
                label="Harvey t=±3.0")
    ax2.axhline(-3.0, linestyle="--", color="#444", alpha=0.7)
    ax2.axhline(1.96, linestyle=":", color="#666", alpha=0.5,
                label="t=±1.96")
    ax2.axhline(-1.96, linestyle=":", color="#666", alpha=0.5)
    ax2.axhline(0, color="black", lw=0.8)
    ax2.set_xticks(range(len(dm_names)))
    ax2.set_xticklabels([n.replace("_", "\n") for n in dm_names], fontsize=9)
    ax2.set_ylabel("OOS DM-HLN t-stat (vs M1 baseline)")
    ax2.set_title("OOS DM-HLN t-stat: positive = exog better than M1")
    for b, v in zip(bars, dm_vals_plot):
        if v is not None:
            ax2.text(b.get_x() + b.get_width() / 2,
                     v + 0.05 * (1 if v >= 0 else -1),
                     f"{v:+.2f}", ha="center", fontsize=9)
    ax2.legend(loc="upper right", fontsize=8)
    ax2.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d5_oos_dm_comparison.png", dpi=120)
    plt.close()

    print("[OK] 2 charts saved")


if __name__ == "__main__":
    run()
