"""
K1100g_d7 — Cross-market replication of gap² session asymmetry
==============================================================

Parent chain:
  K1100g    : TAIFEX overnight/intraday vol ratio 1.586 (vs SPY 1.001)
              Paper 3 reframe anchor candidate
  K1100g_d1 : TAIFEX ratio decomposed: 13:45→15:00 + 05:00→08:45 gap
  K1100g_d3 : Student-t night r² exog → DM t=1.92 borderline
  K1100g_d5 : TAIFEX pure gap² exog → DM t=+1.49 (M2_gap_total) vs
              REF_night_r² DM t=+2.01 — same signal class, neither past Harvey
  K1100g_d6 : extending TAIFEX OOS to 2022-2025 (concurrent)

K1100g_d7 hypothesis:
  If overnight gap² predictive power is UNIVERSAL (not TAIFEX-specific
  microstructure), we should see same-direction gap² loading in
  SPY (US equity, 17.5h close-to-open gap 16:00 ET → 09:30 ET next day)
  and N225 (Japan equity, 18h close-to-open gap 15:00 JST → 09:00 JST next day).

  Universal gap effect → Paper 3 reframe anchor strengthened (structural claim)
  TAIFEX-only → Paper 3 narrative should be scoped to Taiwan microstructure

Models (per market, using daily OHLC only):
  M_base = Student-t GJR-like PRG (no exog)
    σ²_t = τ_t × g_t
    τ_t  = θ0 + θ1·r²_{t-1} + Σ d_k·DOW_k(t)
    g_t  = (1 - α - γ/2 - β) + α·u²_{t-1} + γ·u²_{t-1}·I(r_{t-1}<0) + β·g_{t-1}
  M_gap  = M_base + ξ · gap²_t
    gap²_t = (log Open_t − log Close_{t-1})²   realized before intraday return begins
    exog_contemp=True (known at open_t, forecasting intraday r_t=log Close_t − log Open_t)

Target return:
  r_intraday_t = log Close_t − log Open_t   (replicates TAIFEX day session)

Data:
  yfinance daily OHLC
    SPY : 2010-01-01 .. 2026-03-31  (≥ 4000 trading days)
    ^N225 : 2010-01-01 .. 2026-03-31

Train/OOS split:
  Train: 2010-2019 (~2500 obs)   Test: 2020-01-01 .. 2025-12-31 (≥ 504 obs)
  Expanding-window refit every 5 days (matches K1100g_d5 cadence)

Evaluation:
  IS  : LRT M_gap vs M_base (dof=1)
  OOS : QLIKE, Student-t log-lik, DM-HLN (positive t = M_gap better than M_base)
  Harvey (2016) |t|>3 threshold

Cross-market verdict logic:
  PASS_UNIVERSAL : all 3 markets (TAIFEX + SPY + N225) same positive direction
                    AND ≥2 past Harvey 3.0
  PASS_SOME      : all same direction, ≥1 past Harvey
  TAIFEX_ONLY    : SPY/N225 DM t < 1 or reverse direction
  MIXED          : direction inconsistent across markets

Lookahead discipline:
  - gap²_t uses Open_t and Close_{t-1} — both realized BEFORE
    intraday r_t = log(Close_t/Open_t) begins. LEGAL contemp exog.
  - seed=42, deterministic L-BFGS-B
  - TAIFEX source: K1100g_d5 result JSON (read-only, not re-running)

Author: Claude (worktree agent-a6989c35)
Date: 2026-04-17
Seed: 42
References:
  - Bollerslev (1987) RESTAT — Student-t GARCH
  - Engle & Rangel (2008) RFS — τ×g multiplicative PRG
  - French & Roll (1986) JFE — non-trading-hour information
  - Harvey, Leybourne & Newbold (1997) IJF — HLN DM correction
  - Harvey (2016) JF — t>3 threshold
  - Ito & Lin (1994) JFQA — intraday vol structure in Japan
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
from scipy.stats import norm, chi2, spearmanr, kurtosis as kurt_fn, skew as skew_fn

warnings.filterwarnings("ignore")
np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
RESULTS_PATH = SCRIPT_DIR / "k1100g_d7_results.json"

# Cross-market spec
MARKETS = [
    # (label, yfinance ticker, cache filename)
    ("SPY", "SPY", "spy_daily_2010-2026.parquet"),
    ("N225", "^N225", "n225_daily_2010-2026.parquet"),
]
START_DATE = "2010-01-01"
END_DATE = "2026-04-01"

TRAIN_START = pd.Timestamp("2010-01-01")
TRAIN_END = pd.Timestamp("2019-12-31")
TEST_START = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2025-12-31")
REFIT_EVERY = 5

# K1100g_d5 TAIFEX anchor (for cross-market comparison; read-only)
TAIFEX_D5_RESULTS = (Path(__file__).resolve().parent.parent
                     / "k1100g_d5" / "k1100g_d5_results.json")


# ----------------------------------------------------------------------
# 1. Data fetch + gap² construction
# ----------------------------------------------------------------------
def fetch_daily(ticker: str, cache_file: str) -> pd.DataFrame:
    cache_path = DATA_DIR / cache_file
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        print(f"  [cache] {ticker} -> {cache_path.name} n={len(df)}")
        return df
    print(f"  [fetch] {ticker} {START_DATE}..{END_DATE}")
    import yfinance as yf
    raw = yf.download(ticker, start=START_DATE, end=END_DATE,
                      progress=False, auto_adjust=False)
    # Flatten any MultiIndex columns (single-ticker download)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    df = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    df.index.name = "date"
    df = df.reset_index()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").dropna(
        subset=["Open", "High", "Low", "Close"]).reset_index(drop=True)
    df.to_parquet(cache_path, index=False)
    print(f"  [OK] {ticker} cached n={len(df)}")
    return df


def build_market_series(df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Construct:
      r_intraday[t]  = log(Close_t / Open_t)   target
      r_overnight[t] = log(Open_t / Close_{t-1})  gap
      r_full[t]      = log(Close_t / Close_{t-1})  full-day (for descriptives)
    """
    close = df["Close"].values.astype(float)
    openp = df["Open"].values.astype(float)
    prev_close = np.r_[np.nan, close[:-1]]
    r_intraday = np.log(close / openp)
    r_overnight = np.log(openp / prev_close)
    r_full = np.log(close / prev_close)
    dow = df["date"].dt.dayofweek.values.astype(int)
    return {
        "date": df["date"].values,
        "r_intraday": r_intraday,
        "r_overnight": r_overnight,
        "r_full": r_full,
        "gap2": r_overnight ** 2,
        "dow": dow,
    }


def make_dow_dummies(dow: np.ndarray) -> np.ndarray:
    """Use weekdays 1..4 (Tue..Fri) vs Mon=0 base."""
    N = len(dow)
    X = np.zeros((N, 4), dtype=float)
    for k, d in enumerate((1, 2, 3, 4)):
        X[:, k] = (dow == d).astype(float)
    return X


# ----------------------------------------------------------------------
# 2. Student-t PRG (identical kernel to K1100g_d5)
# ----------------------------------------------------------------------
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
    tau = np.zeros(N); g = np.zeros(N); h = np.zeros(N)
    uncond = float(np.mean(r * r))
    tau[0] = max(uncond, 1e-10); g[0] = 1.0; h[0] = tau[0] * g[0]
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
    h_v = h[1:N]; r_v = r[1:N]
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


# ----------------------------------------------------------------------
# 3. Eval utilities
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
# 4. OOS expanding-window
# ----------------------------------------------------------------------
def expanding_oos_student(r_target: np.ndarray, dow_dum: np.ndarray,
                          exog: Optional[np.ndarray],
                          exog_contemp: bool,
                          test_start_idx: int,
                          label: str = "",
                          refit_every: int = REFIT_EVERY) -> Dict:
    N = len(r_target)
    h_oos = np.full(N, np.nan)
    df_log = np.full(N, np.nan)
    params_log: List[Tuple[int, List[float]]] = []
    current_params: Optional[np.ndarray] = None

    for t in range(test_start_idx, N):
        steps = t - test_start_idx
        need_refit = (steps % refit_every == 0)
        if need_refit:
            r_train = r_target[:t]
            dow_train = dow_dum[:t]
            if exog is not None:
                exog_train = exog[:t]
                fit = fit_prg_student(r_train, dow_train,
                                      exog=exog_train,
                                      exog_contemp=exog_contemp,
                                      n_restarts=4, x0_warm=current_params)
            else:
                fit = fit_prg_student(r_train, dow_train,
                                      exog=None, exog_contemp=False,
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
        r_slice = r_target[:t + 1]
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
# 5. Per-market pipeline
# ----------------------------------------------------------------------
def run_market(label: str, ticker: str, cache_file: str) -> Dict:
    print(f"\n=== [{label}] ({ticker}) ===")
    df_raw = fetch_daily(ticker, cache_file)
    s = build_market_series(df_raw)

    # Filter: drop first row (overnight undefined) and require finite
    valid = (np.isfinite(s["r_intraday"]) & np.isfinite(s["gap2"]))
    # Additional: drop zero-variance rows (holidays with Open=Close=prev)
    valid &= (s["gap2"] > 0) | (s["r_intraday"] != 0)
    dates = pd.DatetimeIndex(pd.to_datetime(s["date"][valid]))
    r_intra = s["r_intraday"][valid].astype(float)
    r_ovn = s["r_overnight"][valid].astype(float)
    gap2 = s["gap2"][valid].astype(float)
    dow = s["dow"][valid].astype(int)
    N = len(r_intra)
    print(f"  Aligned rows (finite overnight): {N}")
    print(f"  Date range: {dates.min().date()} .. {dates.max().date()}")

    # Descriptives
    desc = {
        "n": int(N),
        "date_min": str(pd.Timestamp(dates.min()).date()),
        "date_max": str(pd.Timestamp(dates.max()).date()),
        "r_intraday": {
            "mean": float(np.mean(r_intra)),
            "sd": float(np.std(r_intra)),
            "skew": float(skew_fn(r_intra)),
            "excess_kurt": float(kurt_fn(r_intra, fisher=True)),
        },
        "r_overnight": {
            "mean": float(np.mean(r_ovn)),
            "sd": float(np.std(r_ovn)),
            "skew": float(skew_fn(r_ovn)),
            "excess_kurt": float(kurt_fn(r_ovn, fisher=True)),
        },
        "gap2": {
            "mean": float(np.mean(gap2)),
            "sd": float(np.std(gap2)),
        },
        "overnight_over_intraday_var_ratio": float(
            np.var(r_ovn) / np.var(r_intra)) if np.var(r_intra) > 0 else None,
    }
    print(f"  r_intraday sd={desc['r_intraday']['sd']:.4e}  "
          f"r_overnight sd={desc['r_overnight']['sd']:.4e}  "
          f"ratio(ovn/day var)={desc['overnight_over_intraday_var_ratio']:.3f}")

    dow_dum = make_dow_dummies(dow)

    # Train/Test split
    train_mask = (dates >= TRAIN_START) & (dates <= TRAIN_END)
    test_mask = (dates >= TEST_START) & (dates <= TEST_END)
    train_mask_arr = np.asarray(train_mask)
    test_mask_arr = np.asarray(test_mask)
    train_idx = np.where(train_mask_arr)[0]
    test_idx = np.where(test_mask_arr)[0]
    if len(test_idx) == 0:
        raise RuntimeError(f"{label}: no test obs in range")
    test_start_idx = int(test_idx[0])
    test_end_idx = int(test_idx[-1])
    print(f"  Train n={len(train_idx)}  Test n={len(test_idx)}")

    # IS fits on FULL aligned sample (matching K1100g_d5 pattern)
    print(f"  [{time.strftime('%H:%M:%S')}] IS fits ...")
    fit_base = fit_prg_student(r_intra, dow_dum,
                               exog=None, exog_contemp=False, n_restarts=8)
    fit_gap = fit_prg_student(r_intra, dow_dum,
                              exog=gap2, exog_contemp=True, n_restarts=8)
    ll_base = -fit_base["nll"] if np.isfinite(fit_base["nll"]) else None
    ll_gap = -fit_gap["nll"] if np.isfinite(fit_gap["nll"]) else None
    xn_gap = (float(fit_gap["params"][9])
              if fit_gap["params"] is not None else None)
    df_base = (float(fit_base["params"][-1])
               if fit_base["params"] is not None else None)
    df_gap = (float(fit_gap["params"][-1])
              if fit_gap["params"] is not None else None)
    is_lrt_chi2, is_lrt_p = lrt_chi2_test(ll_base, ll_gap, dof=1)
    print(f"    M_base  ll={ll_base:.3f} df={df_base:.2f} success={fit_base['success']}")
    print(f"    M_gap   ll={ll_gap:.3f} df={df_gap:.2f} xn={xn_gap:+.4f} "
          f"LRT={is_lrt_chi2:.3f} (p={is_lrt_p:.4g})")

    is_result = {
        "M_base": {
            "success": bool(fit_base["success"]),
            "log_lik": ll_base,
            "df": df_base,
            "params": (fit_base["params"].tolist()
                       if fit_base["params"] is not None else None),
        },
        "M_gap": {
            "success": bool(fit_gap["success"]),
            "log_lik": ll_gap,
            "df": df_gap,
            "xn_coef": xn_gap,
            "params": (fit_gap["params"].tolist()
                       if fit_gap["params"] is not None else None),
        },
        "lrt_chi2": float(is_lrt_chi2) if np.isfinite(is_lrt_chi2) else None,
        "lrt_p": float(is_lrt_p) if np.isfinite(is_lrt_p) else None,
    }

    # OOS expanding-window
    print(f"  [{time.strftime('%H:%M:%S')}] OOS M_base ...")
    t_oos = time.time()
    oos_base = expanding_oos_student(r_intra, dow_dum, None, False,
                                     test_start_idx, label=f"{label}_base",
                                     refit_every=REFIT_EVERY)
    print(f"    refits={oos_base['n_refits']} elapsed={time.time() - t_oos:.1f}s")
    print(f"  [{time.strftime('%H:%M:%S')}] OOS M_gap ...")
    t_oos = time.time()
    oos_gap = expanding_oos_student(r_intra, dow_dum, gap2, True,
                                    test_start_idx, label=f"{label}_gap",
                                    refit_every=REFIT_EVERY)
    print(f"    refits={oos_gap['n_refits']} elapsed={time.time() - t_oos:.1f}s")

    # OOS metrics
    test_slice = slice(test_start_idx, test_end_idx + 1)
    r_test = r_intra[test_slice]
    r2_test = r_test ** 2
    d_test = pd.DatetimeIndex(np.asarray(dates)[test_slice])

    h_base = oos_base["h_oos"][test_slice]
    h_gap = oos_gap["h_oos"][test_slice]
    df_base_arr = oos_base["df_log"][test_slice]
    df_gap_arr = oos_gap["df_log"][test_slice]
    valid = (np.isfinite(h_base) & np.isfinite(h_gap)
             & np.isfinite(df_base_arr) & np.isfinite(df_gap_arr))
    n_valid = int(valid.sum())
    print(f"  [OOS] n_valid={n_valid}")

    r_v = r_test[valid]; r2_v = r2_test[valid]
    hb = h_base[valid]; hg = h_gap[valid]
    dfb = df_base_arr[valid]; dfg = df_gap_arr[valid]
    d_v = d_test[valid]

    q_base = qlike_loss(hb, r2_v)
    q_gap = qlike_loss(hg, r2_v)
    ll_base_obs = np.array([
        float(student_loglik_per_obs(np.array([hb[i]]),
                                     np.array([r_v[i]]), dfb[i])[0])
        for i in range(n_valid)])
    ll_gap_obs = np.array([
        float(student_loglik_per_obs(np.array([hg[i]]),
                                     np.array([r_v[i]]), dfg[i])[0])
        for i in range(n_valid)])

    ll_base_sum = float(np.sum(ll_base_obs))
    ll_gap_sum = float(np.sum(ll_gap_obs))
    oos_lrt_chi2, oos_lrt_p = lrt_chi2_test(ll_base_sum, ll_gap_sum, dof=1)
    dm_q_t, dm_q_p = dm_test_hln(q_base, q_gap)
    dm_ll_t, dm_ll_p = dm_test_hln(-ll_base_obs, -ll_gap_obs)

    qb_mean = float(np.mean(q_base)); qg_mean = float(np.mean(q_gap))
    imp_pct = ((qb_mean - qg_mean) / abs(qb_mean) * 100
               if qb_mean != 0 else np.nan)
    harvey_pass = (np.isfinite(dm_q_t) and abs(dm_q_t) > 3.0)

    print(f"  [OOS] LRT={oos_lrt_chi2:.3f}  DM-QLIKE t={dm_q_t:+.3f}  "
          f"QLIKE improv={imp_pct:+.2f}%  Harvey_pass={harvey_pass}")

    # Sub-period breakdown (annual)
    annual = {}
    for yr in range(TEST_START.year, TEST_END.year + 1):
        mask = (d_v >= pd.Timestamp(yr, 1, 1)) & (d_v <= pd.Timestamp(yr, 12, 31))
        if mask.sum() < 30:
            continue
        qb_y = q_base[mask]; qg_y = q_gap[mask]
        dm_y, _ = dm_test_hln(qb_y, qg_y)
        qbm_y = float(np.mean(qb_y))
        imp_y = ((qbm_y - float(np.mean(qg_y))) / abs(qbm_y) * 100
                 if qbm_y != 0 else np.nan)
        annual[str(yr)] = {
            "n": int(mask.sum()),
            "dm_qlike_t_hln": float(dm_y) if np.isfinite(dm_y) else None,
            "qlike_improv_pct": float(imp_y) if np.isfinite(imp_y) else None,
        }

    oos_result = {
        "n_valid": n_valid,
        "test_start": str(TEST_START.date()),
        "test_end": str(TEST_END.date()),
        "lrt_chi2": float(oos_lrt_chi2) if np.isfinite(oos_lrt_chi2) else None,
        "lrt_p": float(oos_lrt_p) if np.isfinite(oos_lrt_p) else None,
        "dm_qlike_t_hln": float(dm_q_t) if np.isfinite(dm_q_t) else None,
        "dm_qlike_p": float(dm_q_p) if np.isfinite(dm_q_p) else None,
        "dm_loglik_t_hln": float(dm_ll_t) if np.isfinite(dm_ll_t) else None,
        "dm_loglik_p": float(dm_ll_p) if np.isfinite(dm_ll_p) else None,
        "qlike_base_mean": qb_mean,
        "qlike_gap_mean": qg_mean,
        "qlike_improv_pct": float(imp_pct) if np.isfinite(imp_pct) else None,
        "ll_base_sum": ll_base_sum,
        "ll_gap_sum": ll_gap_sum,
        "harvey_pass": bool(harvey_pass),
        "annual": annual,
    }

    return {
        "label": label,
        "ticker": ticker,
        "descriptives": desc,
        "is": is_result,
        "oos": oos_result,
        "_internals": {
            "dates_test": d_v,
            "r_test": r_v,
            "h_base": hb,
            "h_gap": hg,
            "q_base": q_base,
            "q_gap": q_gap,
            "n_train": int(len(train_idx)),
            "n_test": int(len(test_idx)),
        },
    }


# ----------------------------------------------------------------------
# 6. Load K1100g_d5 TAIFEX anchor (read-only)
# ----------------------------------------------------------------------
def load_taifex_anchor() -> Dict:
    if not TAIFEX_D5_RESULTS.exists():
        print(f"  [warn] TAIFEX d5 results not found at {TAIFEX_D5_RESULTS}")
        return {}
    with open(TAIFEX_D5_RESULTS) as f:
        d5 = json.load(f)
    # Prefer M2_gap_total as pure-gap² anchor for cross-market comparison
    m = d5.get("oos_metrics", {}).get("M2_gap_total", {})
    is_lrt = d5.get("is_lrt_vs_M1", {}).get("M2_gap_total", {})
    return {
        "label": "TAIFEX",
        "ticker": "TX (TAIFEX)",
        "source": "K1100g_d5",
        "oos": {
            "n_valid": m.get("n_valid"),
            "test_start": "2020-01-01",
            "test_end": "2021-12-31",
            "dm_qlike_t_hln": m.get("dm_qlike_t_hln"),
            "dm_qlike_p": m.get("dm_qlike_p"),
            "qlike_improv_pct": m.get("qlike_improv_pct"),
            "lrt_chi2": m.get("lrt_chi2"),
            "lrt_p": m.get("lrt_p"),
            "harvey_pass": (abs(m.get("dm_qlike_t_hln") or 0.0) > 3.0),
        },
        "is": {
            "lrt_chi2": is_lrt.get("chi2"),
            "lrt_p": is_lrt.get("p_value"),
        },
    }


# ----------------------------------------------------------------------
# 7. Cross-market verdict
# ----------------------------------------------------------------------
def classify_verdict(markets_out: Dict[str, Dict], taifex: Dict) -> Dict:
    """Build cross-market verdict."""
    # Collect DM t-stat signs
    entries = []
    if taifex and taifex.get("oos", {}).get("dm_qlike_t_hln") is not None:
        entries.append(("TAIFEX", taifex["oos"]["dm_qlike_t_hln"],
                        taifex["oos"].get("qlike_improv_pct")))
    for k, v in markets_out.items():
        t = v.get("oos", {}).get("dm_qlike_t_hln")
        imp = v.get("oos", {}).get("qlike_improv_pct")
        if t is not None:
            entries.append((k, t, imp))

    if not entries:
        return {"verdict": "NO_DATA", "explanation": "No DM statistics available",
                "entries": entries}

    signs = [np.sign(e[1]) for e in entries]
    directions_consistent = len(set(signs)) == 1 and signs[0] != 0

    # Harvey passes (|t|>3)
    harvey_count = sum(1 for _, t, _ in entries if abs(t) > 3.0)
    positive_count = sum(1 for s in signs if s > 0)
    n = len(entries)

    # Spearman correlation rank of (DM t) across markets — at n=3, just report
    if n >= 2:
        try:
            ts = np.array([e[1] for e in entries])
            imps = np.array([e[2] if e[2] is not None else 0.0
                             for e in entries])
            rho_t_imp, _ = spearmanr(ts, imps)
        except Exception:
            rho_t_imp = None
    else:
        rho_t_imp = None

    if directions_consistent and positive_count == n and harvey_count >= 2:
        verdict = "PASS_UNIVERSAL"
        explanation = (
            f"All {n} markets (TAIFEX/SPY/N225) gap² loading positive and "
            f"{harvey_count}/{n} past Harvey threshold |t|>3. Overnight gap² "
            "predictive effect is structural, not TAIFEX-specific — Paper 3 "
            "reframe anchor established."
        )
    elif directions_consistent and positive_count == n and harvey_count >= 1:
        verdict = "PASS_SOME"
        explanation = (
            f"All {n} markets positive, but only {harvey_count}/{n} past "
            "Harvey threshold. Direction universal, strength borderline — "
            "Paper 3 reframe supported as direction-consistent weak effect."
        )
    elif directions_consistent and positive_count == n:
        verdict = "DIRECTION_CONSISTENT_ALL_BORDERLINE"
        explanation = (
            f"All {n} markets positive direction but none past Harvey t>3. "
            "Consistent direction suggests real but weak structural effect; "
            "Paper 3 should frame as direction-consistent borderline signal."
        )
    elif (not directions_consistent) and any(
            lbl == "TAIFEX" and t > 0 for lbl, t, _ in entries):
        # TAIFEX positive but SPY/N225 flip
        verdict = "TAIFEX_ONLY"
        explanation = (
            f"TAIFEX positive (t={entries[0][1]:+.2f}) but cross-markets "
            "disagree: " + ", ".join(f"{l} t={t:+.2f}"
                                      for l, t, _ in entries[1:]) +
            ". Gap² effect is Taiwan-specific microstructural — Paper 3 "
            "narrative must be scoped to TAIFEX/PRG, not universal claim."
        )
    else:
        verdict = "MIXED"
        explanation = (
            "Mixed cross-market signs: " + ", ".join(
                f"{l} t={t:+.2f}" for l, t, _ in entries) +
            ". Neither universal nor cleanly TAIFEX-only — further markets "
            "needed before Paper 3 can anchor the claim."
        )

    return {
        "verdict": verdict,
        "explanation": explanation,
        "n_markets_evaluated": n,
        "directions_consistent": bool(directions_consistent),
        "positive_count": int(positive_count),
        "harvey_count": int(harvey_count),
        "spearman_t_vs_qlike_imp": (float(rho_t_imp)
                                      if rho_t_imp is not None
                                      and np.isfinite(rho_t_imp) else None),
        "entries": [{"market": l, "dm_qlike_t_hln": float(t),
                     "qlike_improv_pct": (float(imp) if imp is not None
                                          else None)}
                    for l, t, imp in entries],
    }


# ----------------------------------------------------------------------
# 8. Plots
# ----------------------------------------------------------------------
def plot_cross_market(markets_out: Dict[str, Dict], taifex: Dict,
                      verdict: Dict):
    # Plot 1: Per-market DM + LRT bar
    labels = []
    dm_vals = []
    lrt_vals = []
    imp_vals = []
    if taifex:
        labels.append("TAIFEX\n(d5 M2_gap_total)")
        dm_vals.append(taifex["oos"].get("dm_qlike_t_hln") or 0.0)
        lrt_vals.append(taifex["oos"].get("lrt_chi2") or 0.0)
        imp_vals.append(taifex["oos"].get("qlike_improv_pct") or 0.0)
    for k, v in markets_out.items():
        labels.append(k)
        dm_vals.append(v["oos"].get("dm_qlike_t_hln") or 0.0)
        lrt_vals.append(v["oos"].get("lrt_chi2") or 0.0)
        imp_vals.append(v["oos"].get("qlike_improv_pct") or 0.0)

    fig, axes = plt.subplots(3, 1, figsize=(10, 9), sharex=True)
    ax0, ax1, ax2 = axes
    colors = ["#d62728", "#1f77b4", "#2ca02c"][:len(labels)]

    # DM bar
    bars = ax0.bar(range(len(labels)), dm_vals, color=colors, alpha=0.85)
    ax0.axhline(3.0, ls="--", color="#444", alpha=0.7, label="Harvey |t|=3")
    ax0.axhline(-3.0, ls="--", color="#444", alpha=0.7)
    ax0.axhline(1.96, ls=":", color="#666", alpha=0.5, label="|t|=1.96")
    ax0.axhline(-1.96, ls=":", color="#666", alpha=0.5)
    ax0.axhline(0, color="black", lw=0.8)
    ax0.set_ylabel("OOS DM-HLN t-stat\n(M_gap vs M_base)")
    ax0.set_title("K1100g_d7 Cross-market gap² predictive power "
                  f"— verdict: {verdict['verdict']}")
    for b, v in zip(bars, dm_vals):
        ax0.text(b.get_x() + b.get_width() / 2,
                 v + 0.08 * (1 if v >= 0 else -1),
                 f"{v:+.2f}", ha="center", fontsize=9)
    ax0.legend(loc="upper right", fontsize=8)
    ax0.grid(alpha=0.3, axis="y")

    # LRT bar
    bars1 = ax1.bar(range(len(labels)), lrt_vals, color=colors, alpha=0.85)
    ax1.axhline(3.84, ls="--", color="#444", alpha=0.6, label="chi²(1,0.05)=3.84")
    ax1.axhline(7.88, ls=":", color="#666", alpha=0.6, label="chi²(1,0.005)=7.88")
    ax1.set_ylabel("OOS LRT chi²")
    for b, v in zip(bars1, lrt_vals):
        ax1.text(b.get_x() + b.get_width() / 2,
                 v + max(lrt_vals + [1]) * 0.02,
                 f"{v:.2f}", ha="center", fontsize=9)
    ax1.legend(loc="upper right", fontsize=8)
    ax1.grid(alpha=0.3, axis="y")

    # QLIKE improv bar
    bars2 = ax2.bar(range(len(labels)), imp_vals, color=colors, alpha=0.85)
    ax2.axhline(0, color="black", lw=0.8)
    ax2.set_ylabel("OOS QLIKE improv (%)")
    ax2.set_xticks(range(len(labels)))
    ax2.set_xticklabels(labels, fontsize=9)
    for b, v in zip(bars2, imp_vals):
        ax2.text(b.get_x() + b.get_width() / 2,
                 v + 0.1 * (1 if v >= 0 else -1),
                 f"{v:+.2f}%", ha="center", fontsize=9)
    ax2.grid(alpha=0.3, axis="y")

    plt.tight_layout()
    out = SCRIPT_DIR / "k1100g_d7_cross_market_bars.png"
    plt.savefig(out, dpi=120)
    plt.close()
    print(f"  [plot] {out.name}")

    # Plot 2: Gap² contribution ranking (QLIKE improvement across markets)
    fig, ax = plt.subplots(figsize=(9, 4.5))
    order = np.argsort(imp_vals)[::-1]
    ordered_labels = [labels[i] for i in order]
    ordered_imps = [imp_vals[i] for i in order]
    ordered_colors = [colors[i] for i in order]
    bars = ax.barh(range(len(ordered_labels)), ordered_imps,
                   color=ordered_colors, alpha=0.85)
    ax.axvline(0, color="black", lw=0.8)
    ax.set_yticks(range(len(ordered_labels)))
    ax.set_yticklabels(ordered_labels, fontsize=10)
    ax.set_xlabel("Gap² contribution to QLIKE improvement (%)")
    ax.set_title("K1100g_d7 Cross-market ranking — gap² contribution strength")
    for b, v in zip(bars, ordered_imps):
        ax.text(v + 0.1 * (1 if v >= 0 else -1),
                b.get_y() + b.get_height() / 2,
                f"{v:+.2f}%", va="center", fontsize=9)
    ax.grid(alpha=0.3, axis="x")
    plt.tight_layout()
    out2 = SCRIPT_DIR / "k1100g_d7_gap2_contribution_ranking.png"
    plt.savefig(out2, dpi=120)
    plt.close()
    print(f"  [plot] {out2.name}")


# ----------------------------------------------------------------------
# 9. Main
# ----------------------------------------------------------------------
def run():
    t_total = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] K1100g_d7 cross-market gap² start")

    # 1. Run each market
    markets_out: Dict[str, Dict] = {}
    for label, ticker, cache_file in MARKETS:
        try:
            res = run_market(label, ticker, cache_file)
            markets_out[label] = res
        except Exception as exc:
            import traceback
            traceback.print_exc()
            markets_out[label] = {"error": str(exc)}

    # 2. TAIFEX anchor (from d5)
    print(f"\n[{time.strftime('%H:%M:%S')}] Loading TAIFEX d5 anchor ...")
    taifex = load_taifex_anchor()
    if taifex:
        print(f"  TAIFEX d5: DM t={taifex['oos']['dm_qlike_t_hln']:+.3f}  "
              f"LRT={taifex['oos']['lrt_chi2']:.3f}  "
              f"QLIKE improv={taifex['oos']['qlike_improv_pct']:+.2f}%")

    # 3. Cross-market verdict
    verdict = classify_verdict(markets_out, taifex)
    print(f"\n[{time.strftime('%H:%M:%S')}] === Verdict: {verdict['verdict']} ===")
    print(f"  {verdict['explanation']}")

    # 4. Compile result (strip _internals)
    clean_markets = {}
    for k, v in markets_out.items():
        if "error" in v:
            clean_markets[k] = v
            continue
        cv = {kk: vv for kk, vv in v.items() if kk != "_internals"}
        clean_markets[k] = cv

    result = {
        "experiment_id": "K1100g_d7",
        "title": ("Cross-market replication of overnight gap² session "
                  "asymmetry — SPY + N225 vs TAIFEX (K1100g_d5 anchor)"),
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": 42,
        "parent_chain": [
            "K1100g", "K1100g_d1", "K1100g_d3", "K1100g_d5", "K1100g_d6",
        ],
        "references": [
            "Bollerslev (1987) REStat — Student-t GARCH",
            "Engle & Rangel (2008) RFS — tau*g PRG",
            "French & Roll (1986) JFE — non-trading-hour information",
            "Harvey et al. (1997) IJF — HLN DM correction",
            "Harvey (2016) JF — t>3 threshold",
            "Ito & Lin (1994) JFQA — Japan intraday vol structure",
        ],
        "design": {
            "markets": [{"label": l, "ticker": t, "cache": c}
                         for l, t, c in MARKETS],
            "target_return": "r_intraday[t] = log(Close_t / Open_t)",
            "exog": "gap²[t] = (log Open_t - log Close_{t-1})²",
            "innovation": "student",
            "prg_kernel": "tau*g multiplicative, Student-t (Var(r)=h)",
            "train_start": str(TRAIN_START.date()),
            "train_end": str(TRAIN_END.date()),
            "test_start": str(TEST_START.date()),
            "test_end": str(TEST_END.date()),
            "refit_every": REFIT_EVERY,
            "note_data_granularity": (
                "Daily OHLC only. 5-min intraday not sufficient on yfinance "
                "for SPY/N225 at 2010-2025 span (only last ~60 days available); "
                "using daily close-to-open gap² as second-best consistent "
                "with K1100g_d5 TAIFEX gap² definition."),
        },
        "markets": clean_markets,
        "taifex_d5_anchor": taifex,
        "cross_market_verdict": verdict,
        "limitations": [
            "Daily OHLC only — 5-min intraday RV not used (yfinance 5-min "
            "limited to ~60 days). K1100g_d5 TAIFEX result also based on "
            "daily close-to-open gap², so comparison is apples-to-apples.",
            "SPY/N225 DOW structure differs from TAIFEX "
            "(no Saturday half-day, no lunch break on daily OHLC)",
            "TAIFEX anchor is d5 Student-t gap_total DM t=+1.49 "
            "(BORDERLINE not Harvey-passing); d7 tests whether other "
            "markets behave similarly or whether TAIFEX is idiosyncratic.",
            "N225 trading hours partially overlap US close → overnight gap "
            "may be dampened by Asia daylight trading in other venues "
            "(unlike TAIFEX night session which is structurally separated).",
            "No winsorization — COVID Mar 2020 extreme gaps may dominate "
            "gap² mass in SPY/N225 (similar issue to TAIFEX_d5 limitation).",
        ],
    }

    result = clean_for_json(result)
    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(f"\n[OK] results -> {RESULTS_PATH.name}")

    # 5. Plots
    try:
        plot_cross_market(markets_out, taifex, verdict)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"  [warn] plotting failed: {exc}")

    print(f"\n[DONE] total elapsed: {time.time() - t_total:.1f}s")
    return result


if __name__ == "__main__":
    run()
