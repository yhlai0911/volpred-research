"""
K1100g_d6 — Extend K1100g_d5 sample 2017-2021 → 2017-2025 (DM Harvey test)
==========================================================================

Parent:
  - K1100g_d5 : 2017-2021, N_OOS=464, M2_gap_total DM t=+1.49, REF_night_r2
                DM t=+2.01. Harvey (2016) |t|>3 threshold NOT met for any
                encoding (pure gap^2, night r^2). Verdict H3_NIGHT_R2_BETTER
                but essentially H2 (both borderline).

Motivation (K1100g_d6 hypothesis):
  If TAIFEX night→day predictive signal is robust (non-spurious), DM t should
  scale roughly ~sqrt(N). With N_OOS ≈ 464 giving DM t ≈ 2.0 (REF_night_r2),
  extending the sample ~2x should lift DM t to ~2.8 — close to Harvey 3.0.
  Extending test from 2020-2021 to 2020-2025 roughly triples N_OOS, pushing
  expected DM t toward ~3.5 if the signal is truly linear-scaling.

  Expected scaling benchmarks (√N linear scaling from K1100g_d5 baseline):
    N=464 → t≈2.0 (K1100g_d5 REF_night_r2 baseline)
    N=700 → t≈2.46
    N=1000 → t≈2.94
    N=1500 → t≈3.60

Critical discipline:
  Specification (PRG kernel, Student-t, exog definitions, lag convention,
  refit_every=5, dow dummies, train 2017-2019) is IDENTICAL to K1100g_d5.
  The ONLY change is the TAIFEX raw source extending 2022-01-01 .. 2025-12-31
  and the test window 2020-01-01 .. 2025-12-31.

Segmented reporting:
  A. 2017-2021 (baseline replicate) — should match K1100g_d5 to 4 dp
     (test 2020-2021, N≈464)
  B. 2022-2025 (extension only) — pure new sample test
  C. 2020-2025 (combined) — full extended test

Verdict rules:
  - PASS             : |DM t| > 3.0 (Harvey)    on combined M2_gap_total OR REF_night_r2
  - MARGINAL         : |DM t| in [2.0, 3.0)
  - FAIL             : |DM t| < 2.0 but same sign as K1100g_d5
  - REGIME_REVERSAL  : sign flips vs K1100g_d5 or |DM t| grows but opposite sign

Lookahead discipline:
  Same as K1100g_d5:
    gap_night[t] known at 08:45 day t — legal
    gap_day[t-1] from prev day — legal
    r_night[t] from night ending 05:00 day t — legal
    Student-t, seed=42, L-BFGS-B deterministic.

Author: Claude (worktree agent-a71a442b)
Date: 2026-04-17
Seed: 42
References:
  - Bollerslev (1987) RESTAT — Student-t GARCH
  - Engle & Rangel (2008) RFS — PRG tau*g
  - Harvey, Leybourne & Newbold (1997) IJF — HLN DM correction
  - Harvey (2016) JF — t>3 threshold
  - French & Roll (1986) JFE — non-trading-hours info
  - Andersen et al. (2011) JoE — overnight jumps
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
from scipy.stats import norm, chi2, kurtosis as kurt_fn, skew as skew_fn

warnings.filterwarnings("ignore")
np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
SESSIONS_CACHE = DATA_DIR / "_cache_taifex_sessions_2017-2025.parquet"
RESULTS_PATH = SCRIPT_DIR / "k1100g_d6_results.json"

TAIFEX_DIR = Path("/Users/yhlai0911/Dropbox/TAIFEXDATA/TAIFEXDATA/python")

# Time constants (identical to K1100g_d1)
DAY_START = 84500      # 08:45
DAY_END = 134500       # 13:45

# ----------------------------------------------------------------------
# EXTENSION: sample window 2017-2025 (test window extends to 2020-2025)
# Train/test split — train identical to K1100g_d5; test extended
# ----------------------------------------------------------------------
SAMPLE_START = pd.Timestamp("2017-01-01")
SAMPLE_END = pd.Timestamp("2025-12-31")
TRAIN_START = pd.Timestamp("2017-01-01")
TRAIN_END = pd.Timestamp("2019-12-31")
TEST_START = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2025-12-31")
REFIT_EVERY = 5


# ======================================================================
# 1. Build session cache (identical logic to K1100g_d1, extended to 2025)
# ======================================================================
def _parse_date_from_filename(fname: str):
    base = fname.replace("Daily_", "")
    try:
        ymd = base.split("TX")[0]
        parts = ymd.split("_")
        if len(parts) != 3:
            return None
        return pd.Timestamp(int(parts[0]), int(parts[1]), int(parts[2]))
    except Exception:
        return None


def _read_taifex_raw(path: Path):
    if not path.exists() or path.stat().st_size < 100:
        return None
    df = None
    for enc in ("big5", "cp950", "utf-8"):
        try:
            df = pd.read_csv(path, encoding=enc, dtype=str, low_memory=False)
            break
        except Exception:
            df = None
    if df is None or len(df) < 10:
        return None

    try:
        contract = df.iloc[:, 2].astype(str)
        monthly_mask = contract.str.match(r"^\d{6}$")
        df = df.loc[monthly_mask].copy()
        if len(df) < 10:
            return None
        out = pd.DataFrame({
            "trade_date": pd.to_numeric(df.iloc[:, 0], errors="coerce"),
            "contract_month": pd.to_numeric(df.iloc[:, 2], errors="coerce"),
            "time_int": pd.to_numeric(df.iloc[:, 3], errors="coerce"),
            "price": pd.to_numeric(df.iloc[:, 4], errors="coerce"),
            "volume": pd.to_numeric(df.iloc[:, 5], errors="coerce"),
        })
        out = out.dropna()
        if len(out) < 10:
            return None
        for c in ("trade_date", "contract_month", "time_int"):
            out[c] = out[c].astype(np.int64)
        return out
    except Exception:
        return None


def build_sessions_cache(start: pd.Timestamp, end: pd.Timestamp,
                          cache: bool = True) -> pd.DataFrame:
    """Build TAIFEX session cache between start and end. Matches K1100g_d1
    logic byte-for-byte; only the date window changes."""
    if cache and SESSIONS_CACHE.exists():
        print(f"[Sessions] Loading cache: {SESSIONS_CACHE.name}")
        out = pd.read_parquet(SESSIONS_CACHE)
        out["date"] = pd.to_datetime(out["date"])
        return out

    print(f"[Sessions] Rebuilding from raw {start.date()} .. {end.date()}")
    all_files = sorted(TAIFEX_DIR.glob("Daily_*TX.csv"))

    rows = []
    for f in all_files:
        # Skip TX1/TX2 variants — only main TX (same convention as K1100g_d1)
        if not f.name.replace("Daily_", "").replace(".csv", "").endswith("TX"):
            continue
        file_date = _parse_date_from_filename(f.name)
        if file_date is None or file_date < start or file_date > end:
            continue
        raw = _read_taifex_raw(f)
        if raw is None:
            continue

        vol_by_c = raw.groupby("contract_month")["volume"].sum()
        active = int(vol_by_c.idxmax())
        sub = raw[raw["contract_month"] == active].copy()
        if len(sub) < 50:
            continue

        day_mask = (sub["time_int"] >= DAY_START) & (sub["time_int"] <= DAY_END)
        day_df = sub.loc[day_mask].sort_values(["trade_date", "time_int"])
        if len(day_df) < 10:
            continue
        day_open = float(day_df["price"].iloc[0])
        day_close = float(day_df["price"].iloc[-1])

        night_mask = ~day_mask
        night_df = sub.loc[night_mask].copy()
        if len(night_df) >= 10:
            night_df = night_df.sort_values(["trade_date", "time_int"])
            night_open = float(night_df["price"].iloc[0])
            night_close = float(night_df["price"].iloc[-1])
            n_night_ticks = int(len(night_df))
        else:
            night_open = np.nan
            night_close = np.nan
            n_night_ticks = int(len(night_df))

        rows.append({
            "date": file_date,
            "contract_month": active,
            "day_open": day_open,
            "day_close": day_close,
            "night_open": night_open,
            "night_close": night_close,
            "n_day_ticks": int(len(day_df)),
            "n_night_ticks": n_night_ticks,
        })

    if not rows:
        raise RuntimeError("No TAIFEX rows built.")

    out = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    out["date"] = pd.to_datetime(out["date"])
    out["dow"] = out["date"].dt.dayofweek.astype(int)
    out["contract_prev"] = out["contract_month"].shift(1)
    out["is_roll"] = out["contract_month"] != out["contract_prev"]
    out["day_close_prev"] = out["day_close"].shift(1)
    out["r_day"] = np.log(out["day_close"] / out["day_open"])
    out["r_night"] = np.log(out["night_close"] / out["night_open"])
    out["r_combined"] = np.where(
        out["is_roll"], np.nan,
        np.log(out["day_close"] / out["day_close_prev"]),
    )
    out["night_close_prev"] = out["night_close"].shift(1)
    out["r_overnight_gap"] = np.where(
        out["is_roll"], np.nan,
        np.log(out["day_open"] / out["night_close_prev"]),
    )

    if cache:
        try:
            out.to_parquet(SESSIONS_CACHE)
            print(f"[Sessions] Cached to: {SESSIONS_CACHE.name}")
        except Exception as err:
            print(f"[Sessions] cache write failed: {err}")
    print(f"[Sessions] Built {len(out)} trading days.")
    return out


# ======================================================================
# 2. PRG kernel (Student-t; byte-identical to K1100g_d5)
# ======================================================================
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
    r = np.asarray(r, dtype=float)
    use_exog = exog is not None
    local_rng = np.random.default_rng(42)
    best = {"nll": np.inf, "params": None, "success": False}

    prg_base_dim = 10 if use_exog else 9
    dim = prg_base_dim + 1

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
    if params is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    prg_params = params[:-1]
    h = _prg_variance_recursion(prg_params, r, dow_dum, exog, exog_contemp)
    if h is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    return h


# ======================================================================
# 3. Eval utilities (identical to K1100g_d5)
# ======================================================================
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


# ======================================================================
# 4. OOS expanding-window (Student-t) — generic over exog series
# ======================================================================
def expanding_oos_student(r_day: np.ndarray, dow_dum: np.ndarray,
                          exog: Optional[np.ndarray],
                          exog_contemp: bool,
                          test_start_idx: int,
                          label: str = "",
                          refit_every: int = REFIT_EVERY) -> Dict:
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


# ======================================================================
# 5. clean_for_json
# ======================================================================
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


# ======================================================================
# 6. Period-sliced metric packer
# ======================================================================
def period_metrics(name: str, oos_runs: Dict, test_slice: slice,
                   r_day_test: np.ndarray, dates_test: np.ndarray,
                   period_mask: np.ndarray,
                   base_name: str = "M1_baseline") -> Dict:
    """Compute OOS metrics over a SPECIFIC calendar mask within test_slice."""
    h_test = oos_runs[name]["h_oos"][test_slice]
    df_test = oos_runs[name]["df_log"][test_slice]
    h_base = oos_runs[base_name]["h_oos"][test_slice]
    df_base = oos_runs[base_name]["df_log"][test_slice]
    valid = (np.isfinite(h_test) & np.isfinite(h_base)
             & np.isfinite(df_test) & np.isfinite(df_base)
             & period_mask)
    n_valid = int(valid.sum())
    if n_valid < 30:
        return {"n_valid": n_valid, "skipped": True}
    r_v = r_day_test[valid]
    r2_v = r_v ** 2
    h_v = h_test[valid]
    h_b = h_base[valid]
    df_v = df_test[valid]
    df_b = df_base[valid]

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
    }


# ======================================================================
# 7. Main
# ======================================================================
def run():
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] === K1100g_d6 extended sample ===")
    print(f"  Sample: {SAMPLE_START.date()} .. {SAMPLE_END.date()}")
    print(f"  Train : {TRAIN_START.date()} .. {TRAIN_END.date()}")
    print(f"  Test  : {TEST_START.date()} .. {TEST_END.date()}")

    # Build/load cache
    df = build_sessions_cache(SAMPLE_START, SAMPLE_END, cache=True)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Gap series (identical to K1100g_d5)
    df["gap_day_t"] = np.log(df["night_open"] / df["day_close"])
    df["gap_night_t"] = df["r_overnight_gap"]
    df["gap_day_lag"] = df["gap_day_t"].shift(1)

    mdf = df.dropna(subset=["r_day", "r_night", "r_combined",
                             "gap_night_t", "gap_day_lag"]).copy()
    mdf = mdf.reset_index(drop=True)
    N = len(mdf)
    print(f"  Aligned rows: {N}  (K1100g_d5 baseline was 1071)")

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
    gap_total = gap_night_t2 + gap_day_lag2

    # Descriptives
    print("  --- Gap series descriptives (2017-2025) ---")
    gap_desc = {}
    for name, x in [("gap_night_t", gap_night_t),
                    ("gap_day_lag", gap_day_lag)]:
        d = {"mean": float(np.mean(x)), "sd": float(np.std(x)),
             "skew": float(skew_fn(x)),
             "excess_kurt": float(kurt_fn(x, fisher=True))}
        gap_desc[name] = d
        print(f"    {name}: mean={d['mean']:+.2e}  sd={d['sd']:.4e}  "
              f"kurt={d['excess_kurt']:.2f}  skew={d['skew']:.3f}")
    gap_desc["gap_total"] = {"mean": float(np.mean(gap_total)),
                             "sd": float(np.std(gap_total))}
    gap_desc["var_ratio_gap_total_to_night_r2"] = float(
        np.var(gap_total) / np.var(r_night2))

    # ------------------------------------------------------------------
    # A) IS fits (Student-t, full 2017-2025)
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === IS fits (Student-t) ===")
    is_specs = [
        ("M1_baseline",      r_day, None,         False, 9),
        ("M2_gap_night",     r_day, gap_night_t2, True,  10),
        ("M2_gap_day_lag",   r_day, gap_day_lag2, True,  10),
        ("M2_gap_total",     r_day, gap_total,    True,  10),
        ("M2_signed_gn",     r_day, gap_night_t,  True,  10),
        ("REF_night_r2",     r_day, r_night2,     True,  10),
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
    # B) IS LRT vs M1
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
    # C) OOS expanding-window
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === OOS expanding-window ===")
    train_mask = (dates_ts >= TRAIN_START) & (dates_ts <= TRAIN_END)
    test_mask = (dates_ts >= TEST_START) & (dates_ts <= TEST_END)
    train_idx = np.where(train_mask)[0]
    test_idx = np.where(test_mask)[0]
    test_start_idx = int(test_idx[0])
    test_end_idx = int(test_idx[-1])
    print(f"  Train: n={len(train_idx)}  Test(combined): n={len(test_idx)}")

    oos_runs: Dict[str, Dict] = {}
    oos_specs = [
        ("M1_baseline",      None,         False),
        ("M2_gap_night",     gap_night_t2, True),
        ("M2_gap_day_lag",   gap_day_lag2, True),
        ("M2_gap_total",     gap_total,    True),
        ("M2_signed_gn",     gap_night_t,  True),
        ("REF_night_r2",     r_night2,     True),
    ]
    oos_cache_path = DATA_DIR / "_oos_runs_cache.npz"
    if oos_cache_path.exists():
        print(f"[OOS] Loading cached OOS runs: {oos_cache_path.name}")
        npz = np.load(oos_cache_path)
        for name, _, _ in oos_specs:
            oos_runs[name] = {
                "h_oos": npz[f"{name}__h"],
                "df_log": npz[f"{name}__df"],
                "n_refits": int(npz[f"{name}__n"]),
                "params_log": [],
            }
    else:
        for name, exog, exog_contemp in oos_specs:
            t_oos = time.time()
            print(f"[{time.strftime('%H:%M:%S')}] OOS {name} ...")
            res = expanding_oos_student(r_day, dow_dum, exog, exog_contemp,
                                        test_start_idx, label=name,
                                        refit_every=REFIT_EVERY)
            print(f"  refits={res['n_refits']}  elapsed={time.time() - t_oos:.1f}s")
            oos_runs[name] = res
        save_kwargs = {}
        for name in oos_runs:
            save_kwargs[f"{name}__h"] = oos_runs[name]["h_oos"]
            save_kwargs[f"{name}__df"] = oos_runs[name]["df_log"]
            save_kwargs[f"{name}__n"] = np.array(oos_runs[name]["n_refits"])
        np.savez_compressed(oos_cache_path, **save_kwargs)
        print(f"[OOS] Cached to: {oos_cache_path.name}")

    # ------------------------------------------------------------------
    # D) Segmented OOS metrics (3 periods)
    # ------------------------------------------------------------------
    test_slice = slice(test_start_idx, test_end_idx + 1)
    r_day_test = r_day[test_slice]
    dates_test = dates_ts.iloc[test_slice].values

    dt_vec = pd.to_datetime(dates_test)
    dt_arr = np.asarray(dt_vec)  # ensure plain ndarray for boolean ops
    mask_A = ((dt_arr >= np.datetime64("2020-01-01")) &
              (dt_arr <= np.datetime64("2021-12-31")))  # K1100g_d5 replicate
    mask_B = ((dt_arr >= np.datetime64("2022-01-01")) &
              (dt_arr <= np.datetime64("2025-12-31")))  # extension
    mask_C = ((dt_arr >= np.datetime64("2020-01-01")) &
              (dt_arr <= np.datetime64("2025-12-31")))  # combined

    segmented: Dict[str, Dict] = {}
    exog_names = ["M2_gap_night", "M2_gap_day_lag", "M2_gap_total",
                  "M2_signed_gn", "REF_night_r2"]
    for name in exog_names:
        segmented[name] = {
            "period_A_2017_2021_replicate": period_metrics(
                name, oos_runs, test_slice, r_day_test, dates_test, mask_A),
            "period_B_2022_2025_extension": period_metrics(
                name, oos_runs, test_slice, r_day_test, dates_test, mask_B),
            "period_C_2017_2025_combined": period_metrics(
                name, oos_runs, test_slice, r_day_test, dates_test, mask_C),
            # Annual breakdown for diagnostics
            "by_year": {},
        }
        for yr in range(2020, 2026):
            ym = ((dt_arr >= np.datetime64(f"{yr}-01-01")) &
                  (dt_arr <= np.datetime64(f"{yr}-12-31")))
            segmented[name]["by_year"][str(yr)] = period_metrics(
                name, oos_runs, test_slice, r_day_test, dates_test, ym)

    print(f"\n[{time.strftime('%H:%M:%S')}] === Segmented OOS summary ===")
    print(f"  {'model':<18} {'period':<12} {'n':>5} {'DM_t':>8} {'QLIKE%':>8}")
    for name in exog_names:
        for pkey in ("period_A_2017_2021_replicate",
                     "period_B_2022_2025_extension",
                     "period_C_2017_2025_combined"):
            m = segmented[name][pkey]
            if m.get("skipped"):
                continue
            dm = m.get("dm_qlike_t_hln")
            imp = m.get("qlike_improv_pct")
            pabbr = pkey.split("_", 2)[1]
            print(f"  {name:<18} {pabbr:<12} {m['n_valid']:>5}  "
                  f"{dm if dm is not None else float('nan'):>+7.3f}  "
                  f"{imp if imp is not None else float('nan'):>+7.2f}%")

    # ------------------------------------------------------------------
    # E) Cross-model DM on COMBINED period
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === Cross-model DM (combined period) ===")
    cross = {}
    for a, b in [("M2_gap_night", "REF_night_r2"),
                 ("M2_gap_total", "REF_night_r2"),
                 ("M2_gap_night", "M2_gap_total")]:
        h_a_test = oos_runs[a]["h_oos"][test_slice]
        df_a_test = oos_runs[a]["df_log"][test_slice]
        h_b_test = oos_runs[b]["h_oos"][test_slice]
        df_b_test = oos_runs[b]["df_log"][test_slice]
        valid = (np.isfinite(h_a_test) & np.isfinite(df_a_test)
                 & np.isfinite(h_b_test) & np.isfinite(df_b_test)
                 & mask_C)
        n_valid = int(valid.sum())
        if n_valid < 30:
            continue
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
        print(f"  {a} vs {b}: DM_qlike t={dm_t:+.3f} p={dm_p:.3g} "
              f"DM_ll t={dm_ll_t:+.3f}")

    # ------------------------------------------------------------------
    # F) √N scaling check vs K1100g_d5 baseline
    # ------------------------------------------------------------------
    # K1100g_d5 baseline numbers (2020-2021, N=464)
    K1100G_D5_BASELINE = {
        "M2_gap_total": {"dm_t": 1.48987928699781, "n": 464},
        "REF_night_r2": {"dm_t": 2.0095845427719303, "n": 464},
    }
    sqrtN_scaling = {}
    for name, base in K1100G_D5_BASELINE.items():
        combined = segmented[name]["period_C_2017_2025_combined"]
        n_new = combined.get("n_valid", 0)
        t_new = combined.get("dm_qlike_t_hln")
        if n_new > 0 and t_new is not None:
            expected_t = base["dm_t"] * np.sqrt(n_new / base["n"])
            sqrtN_scaling[name] = {
                "baseline_t": base["dm_t"],
                "baseline_n": base["n"],
                "new_t": t_new,
                "new_n": n_new,
                "expected_t_linear_sqrtN": float(expected_t),
                "actual_minus_expected": float(t_new - expected_t),
                "scaling_ratio": float(t_new / expected_t),
                "harvey_pass_actual": bool(abs(t_new) > 3.0),
                "harvey_pass_expected": bool(abs(expected_t) > 3.0),
            }
            print(f"  {name}: t_old={base['dm_t']:+.2f}(N={base['n']}) → "
                  f"t_new={t_new:+.2f}(N={n_new}), "
                  f"expected √N={expected_t:+.2f}, "
                  f"Δ={t_new - expected_t:+.2f}")

    # ------------------------------------------------------------------
    # G) Harvey verdict
    # ------------------------------------------------------------------
    primary_combined = segmented["M2_gap_total"]["period_C_2017_2025_combined"]
    ref_combined = segmented["REF_night_r2"]["period_C_2017_2025_combined"]
    gap_dm = primary_combined.get("dm_qlike_t_hln", 0.0) or 0.0
    ref_dm = ref_combined.get("dm_qlike_t_hln", 0.0) or 0.0

    # K1100g_d5 baseline signs (both positive)
    k5_gap = K1100G_D5_BASELINE["M2_gap_total"]["dm_t"]
    k5_ref = K1100G_D5_BASELINE["REF_night_r2"]["dm_t"]

    gap_sign_flip = (gap_dm * k5_gap) < 0 and abs(gap_dm) > 1.0
    ref_sign_flip = (ref_dm * k5_ref) < 0 and abs(ref_dm) > 1.0

    if gap_sign_flip or ref_sign_flip:
        verdict = "REGIME_REVERSAL"
        explanation = (
            f"Sign flip detected vs K1100g_d5 baseline: "
            f"M2_gap_total t: {k5_gap:+.2f}→{gap_dm:+.2f}, "
            f"REF_night_r2 t: {k5_ref:+.2f}→{ref_dm:+.2f}. "
            "Overnight signal is regime-specific, not robust — "
            "Paper 3 anchor collapses."
        )
    elif max(abs(gap_dm), abs(ref_dm)) > 3.0:
        verdict = "PASS"
        explanation = (
            f"Harvey (2016) |t|>3 threshold crossed: "
            f"max(|M2_gap_total|={abs(gap_dm):.2f}, "
            f"|REF_night_r2|={abs(ref_dm):.2f}) > 3.0. "
            "TAIFEX overnight→day predictability is robust, "
            "Paper 3 reframe anchor ESTABLISHED."
        )
    elif max(abs(gap_dm), abs(ref_dm)) > 2.0:
        verdict = "MARGINAL"
        explanation = (
            f"Between conventional and Harvey: "
            f"|M2_gap_total|={abs(gap_dm):.2f}, |REF_night_r2|={abs(ref_dm):.2f}. "
            "Signal present but does not meet Harvey bar after sample "
            "tripling. Paper 3 anchor borderline even at extended N."
        )
    else:
        verdict = "FAIL"
        explanation = (
            f"DM t weakens or stays weak at extended N: "
            f"|M2_gap_total|={abs(gap_dm):.2f}, |REF_night_r2|={abs(ref_dm):.2f}. "
            "Signal did NOT scale with N as expected — "
            "TAIFEX overnight→day predictability likely spurious/period-specific. "
            "Paper 3 reframe NOT anchored by this analysis."
        )

    sanity_flag: List[str] = []
    for name in exog_names:
        dm = segmented[name]["period_C_2017_2025_combined"].get("dm_qlike_t_hln")
        if dm is not None and abs(dm) > 6.0:
            sanity_flag.append(f"{name} combined DM t={dm:+.2f} > 6: suspicious, review")

    # Replicate check: period_A should ≈ K1100g_d5
    replicate_check = {}
    for name, base_t in [("M2_gap_total", K1100G_D5_BASELINE["M2_gap_total"]["dm_t"]),
                          ("REF_night_r2", K1100G_D5_BASELINE["REF_night_r2"]["dm_t"])]:
        A = segmented[name]["period_A_2017_2021_replicate"]
        A_t = A.get("dm_qlike_t_hln")
        abs_diff = float(abs(A_t - base_t)) if A_t is not None else None
        replicate_check[name] = {
            "k1100g_d5_t": base_t,
            "k1100g_d6_A_t": A_t,
            "abs_diff": abs_diff,
            "n_old": 464,
            "n_new_A": A.get("n_valid"),
        }

    # ------------------------------------------------------------------
    # H) Compile result
    # ------------------------------------------------------------------
    result = {
        "experiment_id": "K1100g_d6",
        "title": ("Extend K1100g_d5 sample 2017-2021 → 2017-2025: "
                  "does DM t scale with √N to cross Harvey |t|>3?"),
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": 42,
        "parent": "K1100g_d5",
        "parent_notes": {
            "K1100g_d5_M2_gap_total_dm_t": 1.48987928699781,
            "K1100g_d5_REF_night_r2_dm_t": 2.0095845427719303,
            "K1100g_d5_n_oos": 464,
            "K1100g_d5_verdict": "H3_NIGHT_R2_BETTER (borderline, all t<2.1)",
        },
        "references": [
            "Bollerslev (1987) RESTAT 69(3) — Student-t GARCH",
            "Engle & Rangel (2008) RFS 21(3) — PRG tau*g",
            "Harvey, Leybourne & Newbold (1997) IJF — HLN DM correction",
            "Harvey (2016) JF — t>3 threshold",
            "French & Roll (1986) JFE 17(1), 5-26",
            "Andersen, Bollerslev, Huang (2011) JoE 160(1)",
        ],
        "data": {
            "source": "TAIFEX TX 2017-2025 (tick-derived session cache)",
            "cache_file": str(SESSIONS_CACHE.name),
            "n_aligned": int(N),
            "gap_descriptives": gap_desc,
        },
        "design": {
            "innovation": "student",
            "prg_kernel": "tau*g multiplicative, Student-t (Var(r)=h)",
            "models": {
                "M1_baseline": "day-only PRG (no exog)",
                "M2_gap_night": "M1 + gap_night[t]^2 contemp",
                "M2_gap_day_lag": "M1 + gap_day[t-1]^2 lagged",
                "M2_gap_total": "M1 + gap_night[t]^2 + gap_day[t-1]^2",
                "M2_signed_gn": "M1 + gap_night[t] signed (asym test)",
                "REF_night_r2": "M1 + r_night[t]^2 (K1100g_d3 M4 spec)",
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
        "oos_segmented": segmented,
        "cross_model_dm_combined": cross,
        "sqrtN_scaling_check": sqrtN_scaling,
        "replicate_check_period_A": replicate_check,
        "verdict": {
            "primary": verdict,
            "explanation": explanation,
            "criteria_detail": {
                "M2_gap_total_combined_dm_t": gap_dm,
                "REF_night_r2_combined_dm_t": ref_dm,
                "max_abs_dm_t": max(abs(gap_dm), abs(ref_dm)),
                "harvey_pass": bool(max(abs(gap_dm), abs(ref_dm)) > 3.0),
                "harvey_marginal": bool(2.0 <= max(abs(gap_dm), abs(ref_dm)) <= 3.0),
                "sign_flip_gap": bool(gap_sign_flip),
                "sign_flip_ref": bool(ref_sign_flip),
            },
            "sanity_flags": sanity_flag,
            "paper3_reframe_anchor_established": bool(verdict == "PASS"),
        },
        "limitations": [
            "TAIFEX night-session rules shifted over 2017-2025 (hours, "
            "trading product evolution); extended sample may not be strictly "
            "stationary.",
            "Expanding-window refits propagate early-period biases deeper "
            "into 2022-2025 OOS path.",
            "COVID 2020 shock dominates early test period — if excluded, "
            "signal strength may further decline.",
            "Contract-roll days remain sparsely handled (NaN r_combined, "
            "no night rebalancing).",
            "Symmetric Student-t; asymmetric gap_night skew remains unmodeled.",
            "Single market (TAIFEX). Cross-market replication (SPY, N225) "
            "still open — K1100g_d7 candidate.",
        ],
    }
    result = clean_for_json(result)
    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(f"[OK] results -> {RESULTS_PATH.name}")

    # ------------------------------------------------------------------
    # I) Plots
    # ------------------------------------------------------------------
    plot_all(segmented, sqrtN_scaling, oos_runs, test_slice, dates_test,
             r_day_test, K1100G_D5_BASELINE)

    print(f"\n[{time.strftime('%H:%M:%S')}] === Verdict: {verdict} ===")
    print(f"  {explanation}")
    if sanity_flag:
        for s in sanity_flag:
            print(f"  [sanity flag] {s}")
    print(f"\n[DONE] Total: {time.time() - t0:.1f}s")
    return result


def plot_all(segmented, sqrtN, oos_runs, test_slice, dates_test,
             r_day_test, baseline):
    # Plot 1: DM t vs N growth curve (per model) + expected √N line
    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = {"M2_gap_total": "#1f77b4", "REF_night_r2": "#d62728"}
    markers = {"M2_gap_total": "o", "REF_night_r2": "s"}
    for name in ("M2_gap_total", "REF_night_r2"):
        pts = []
        # K1100g_d5 baseline point
        pts.append((baseline[name]["n"], baseline[name]["dm_t"], "K1100g_d5"))
        # K1100g_d6 Period A / B / C
        for pkey, plabel in [
            ("period_A_2017_2021_replicate", "d6 A"),
            ("period_B_2022_2025_extension", "d6 B"),
            ("period_C_2017_2025_combined", "d6 C"),
        ]:
            m = segmented[name][pkey]
            if not m.get("skipped") and m.get("dm_qlike_t_hln") is not None:
                pts.append((m["n_valid"], m["dm_qlike_t_hln"], plabel))
        pts = sorted(pts, key=lambda x: x[0])
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        ax.plot(xs, ys, marker=markers[name], color=colors[name],
                lw=2, markersize=8, label=name)
        for x, y, lbl in pts:
            ax.annotate(lbl, (x, y), textcoords="offset points",
                        xytext=(5, 5), fontsize=8, color=colors[name])
        # Expected √N curve based on K1100g_d5 anchor
        n_grid = np.linspace(min(xs), max(xs) * 1.05, 100)
        t_expected = baseline[name]["dm_t"] * np.sqrt(n_grid / baseline[name]["n"])
        ax.plot(n_grid, t_expected, "--", color=colors[name], alpha=0.4,
                lw=1.2, label=f"{name} expected √N scaling")

    ax.axhline(3.0, linestyle="--", color="#444", alpha=0.7, label="Harvey t=±3.0")
    ax.axhline(-3.0, linestyle="--", color="#444", alpha=0.7)
    ax.axhline(1.96, linestyle=":", color="#666", alpha=0.5, label="t=±1.96")
    ax.axhline(-1.96, linestyle=":", color="#666", alpha=0.5)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_xlabel("OOS sample size N")
    ax.set_ylabel("DM-HLN t-stat (vs M1 baseline)")
    ax.set_title("K1100g_d6 — DM t vs N growth curve (observed vs √N scaling)")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d6_dm_t_vs_n_growth.png", dpi=120)
    plt.close()

    # Plot 2: QLIKE timeseries by period (30d rolling improvement vs M1)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    h_base = oos_runs["M1_baseline"]["h_oos"][test_slice]
    for name, color, label in [
        ("M2_gap_total", "#1f77b4", "M2_gap_total"),
        ("REF_night_r2", "#d62728", "REF_night_r2"),
    ]:
        h_t = oos_runs[name]["h_oos"][test_slice]
        valid = np.isfinite(h_t) & np.isfinite(h_base)
        if valid.sum() < 30:
            continue
        r_v = r_day_test[valid]
        r2_v = r_v ** 2
        q_b = qlike_loss(h_base[valid], r2_v)
        q_t = qlike_loss(h_t[valid], r2_v)
        diff = q_b - q_t
        d_v = pd.to_datetime(dates_test[valid])
        roll = pd.Series(diff, index=d_v).rolling(60, min_periods=30).mean()
        ax.plot(roll.index, roll.values, color=color, lw=1.3, label=label)
    ax.axhline(0, color="black", lw=0.8)
    # Period boundaries
    ax.axvspan(pd.Timestamp("2020-01-01"), pd.Timestamp("2021-12-31"),
               alpha=0.08, color="tab:green", label="Period A (K1100g_d5 replicate)")
    ax.axvspan(pd.Timestamp("2022-01-01"), pd.Timestamp("2025-12-31"),
               alpha=0.08, color="tab:orange", label="Period B (extension)")
    ax.set_ylabel("60d mean QLIKE(M1) − QLIKE(exog)\n(positive = exog improves)")
    ax.set_title("K1100g_d6 OOS QLIKE improvement timeseries, by period")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(SCRIPT_DIR / "k1100g_d6_qlike_timeseries_by_period.png", dpi=120)
    plt.close()

    print("[OK] 2 charts saved")


if __name__ == "__main__":
    run()
