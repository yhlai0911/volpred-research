"""
K1100g_d9 — Refit-cadence robustness rerun of K1100g_d8 at d7 cadence
====================================================================

Parent chain:
  K1100g_d5 : TAIFEX pure gap² exog Student-t → DM t=+1.49
  K1100g_d7 : Cross-market Student-t gap² at refit_every=5
              → N225 +2.32, SPY +0.66, verdict DIRECTION_CONSISTENT_ALL_BORDERLINE
  K1100g_d8 : Hansen skewed-t innovation on N225 (+SPY) at refit_every=25
              → Student-t DM FLIPPED to -1.92/-2.10, skewed-t DM -1.33/-1.74
              → verdict STILL_BORDERLINE (PRELIMINARY). d8 Sec 5.1 explicitly
              identifies the Student-t sign flip as "refit cadence artifact"
              and defers robustness confirmation to K1100g_d9.

K1100g_d9 hypothesis (single cadence-robustness test):
  Rerun K1100g_d8 (Hansen skewed-t + Student-t baseline, N225 + SPY)
  at the K1100g_d7 cadence:
      refit_every = 5          (vs d8's 25)
      n_restarts_warm = 4      (vs d8's 2)
      n_restarts_cold = 6      (vs d8's 4)
  Everything else identical (same PRG kernel, same Hansen closed-form,
  same gap², same seed 42, same TRAIN/TEST split, same caches).

  Key questions:
  1. Does d8 Student-t DM sign flip (+2.32 → -1.92 for N225) RESTORE to d7 value
     under d7 cadence? If yes → confirms cadence artifact; d8 baseline rerun
     with proper cadence provides the legitimate Student-t reference for
     comparing skewed-t.
  2. Does Hansen skewed-t gap_sk DM improve under proper cadence?
     - If skewed-t DM > +3.0 → PASS_N225_HARVEY_UNDER_CADENCE
       (d8 was misleading; proper cadence unlocks Harvey)
     - If skewed-t DM still borderline/negative → d8 verdict confirmed
       (cadence not the bottleneck; skewed-t genuinely does not help)
  3. Does innovation-upgrade DM (skewed-t vs Student-t on gap models) change
     sign under proper cadence?

Cadence-sensitivity verdict classification
------------------------------------------
  ROBUST_CONFIRMED       : d9 verdict == d8 verdict; skewed-t does not help even
                           at d7 cadence. d8 conclusions stand.
  CADENCE_ARTIFACT       : d9 Student-t DM ≈ d7 (+2.32 recovered), but skewed-t DM
                           ALSO RESTORED to +2.0+ range (meaning d8 skewed-t decline
                           was also refit-driven). Skewed-t conclusion was artefact.
  ROBUST_WITH_RECOVERY   : d9 Student-t DM recovered to ~+2.32, skewed-t still
                           does not improve on Student-t → canonical conclusion
                           "skewed-t no help" HOLDS but with clean baseline.
  MIXED                  : partial recovery / sign inconsistency across markets.

Lookahead / seed discipline (inherited from d8; unchanged)
----------------------------------------------------------
- gap²_t uses Open_t and Close_{t-1}, realised BEFORE r_intraday_t begins
- np.random.seed(42); np.random.default_rng(42)
- L-BFGS-B deterministic; warm-start from previous OOS refit
- Hansen sanity check enforced at import time

Data
----
Symlink-referenced from experiments/k1100g_d8/data/:
  data/n225_daily_2010-2026.parquet  → ../../k1100g_d8/data/n225_daily_2010-2026.parquet
  data/spy_daily_2010-2026.parquet   → ../../k1100g_d8/data/spy_daily_2010-2026.parquet

This guarantees apples-to-apples raw input with d8; only refit cadence and
n_restarts vary.

Author: Claude (worktree agent-aa9aeb5d)
Date: 2026-04-18
Seed: 42
References
----------
- Hansen, B. E. (1994) IER 35(3) — Autoregressive Conditional Density Estimation
- Jondeau & Rockinger (2003) JEDC 27(10) — Conditional volatility/skewness/kurtosis
- Bollerslev (1987) REStat 69(3) — Student-t GARCH
- Engle & Rangel (2008) RFS 21(3) — τ×g multiplicative PRG
- Harvey, Leybourne & Newbold (1997) IJF 13(2) — HLN DM correction
- Harvey (2016) JF — |t|>3 threshold
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
from scipy.stats import norm, chi2, t as student_t, skew as skew_fn, kurtosis as kurt_fn

warnings.filterwarnings("ignore")
np.random.seed(42)
RNG = np.random.default_rng(42)

# Force line-buffered stdout for progress visibility
import sys as _sys
try:
    _sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
RESULTS_PATH = SCRIPT_DIR / "k1100g_d9_results.json"

# Cross-market spec (match d8)
MARKETS = [
    ("N225", "^N225", "n225_daily_2010-2026.parquet"),
    ("SPY", "SPY", "spy_daily_2010-2026.parquet"),
]
START_DATE = "2010-01-01"
END_DATE = "2026-04-01"

TRAIN_START = pd.Timestamp("2010-01-01")
TRAIN_END = pd.Timestamp("2019-12-31")
TEST_START = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2025-12-31")

# =====================================================================
# K1100g_d9 cadence = K1100g_d7 cadence (the robustness check)
# =====================================================================
# K1100g_d8 used REFIT_EVERY=25, n_restarts_warm=2, cold=4 for runtime.
# K1100g_d7 used REFIT_EVERY=5, n_restarts_warm=4, cold=6.
# d9 aligns to d7 to test whether d8 results are cadence-robust.
REFIT_EVERY = 5
N_RESTARTS_IS = 10       # match d8 (IS is already dense)
N_RESTARTS_OOS_WARM = 4  # match d7 (d8 was 2)
N_RESTARTS_OOS_COLD = 6  # match d7 (d8 was 4)

# Reference results for vs-comparison (read-only)
D7_RESULTS = (SCRIPT_DIR.parent / "k1100g_d7" / "k1100g_d7_results.json")
D8_RESULTS = (SCRIPT_DIR.parent / "k1100g_d8" / "k1100g_d8_results.json")


# ======================================================================
# 1. Hansen (1994) skewed-t closed-form log-pdf (identical to d8)
# ======================================================================
def hansen_skewt_logpdf(z_arr: np.ndarray, eta: float,
                        lam: float) -> np.ndarray:
    """Log-PDF of Hansen (1994) skewed-t with E[z]=0, Var[z]=1."""
    if eta <= 2.0 or abs(lam) >= 1.0:
        return np.full(len(z_arr), -1e10)

    log_c = (gammaln((eta + 1.0) / 2.0)
             - gammaln(eta / 2.0)
             - 0.5 * np.log(np.pi * (eta - 2.0)))
    c_val = np.exp(log_c)

    a = 4.0 * lam * c_val * (eta - 2.0) / (eta - 1.0)
    b2 = 1.0 + 3.0 * lam * lam - a * a
    if b2 <= 0:
        return np.full(len(z_arr), -1e10)
    b = np.sqrt(b2)
    log_b = np.log(b)

    bxa = b * z_arr + a
    sign_part = np.where(z_arr >= -a / b, 1.0 + lam, 1.0 - lam)
    sign_part = np.maximum(sign_part, 1e-10)

    inner = 1.0 + (bxa / sign_part) ** 2 / (eta - 2.0)
    inner = np.maximum(inner, 1e-10)

    return log_b + log_c - ((eta + 1.0) / 2.0) * np.log(inner)


def _hansen_sanity_check():
    """Hansen with lam=0 must match variance-standardised Student-t."""
    z_test = np.array([0.0, 0.5, -0.5, 1.0, -1.0, 2.0, -2.0])
    for eta_t in (4.0, 5.0, 8.0, 12.0):
        lp_h = hansen_skewt_logpdf(z_test, eta=eta_t, lam=0.0)
        scale = np.sqrt((eta_t - 2.0) / eta_t)
        lp_s = student_t.logpdf(z_test / scale, df=eta_t) - np.log(scale)
        if not np.allclose(lp_h, lp_s, atol=1e-5):
            raise AssertionError(
                f"Hansen skewed-t sanity FAILED at eta={eta_t}: "
                f"lp_hansen={lp_h} vs lp_student_scaled={lp_s}")
    print("  [sanity] Hansen skewed-t lam=0 matches scaled Student-t OK")


_hansen_sanity_check()


# ======================================================================
# 2. Data loading (identical to d7/d8 conventions)
# ======================================================================
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
    N = len(dow)
    X = np.zeros((N, 4), dtype=float)
    for k, d in enumerate((1, 2, 3, 4)):
        X[:, k] = (dow == d).astype(float)
    return X


# ======================================================================
# 3. τ×g PRG recursion (identical to d7/d8)
# ======================================================================
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


# ======================================================================
# 4. NLL functions (identical to d8)
# ======================================================================
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
    h_v = h[1:N]
    r_v = r[1:N]
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


def prg_nll_skewt(params: np.ndarray, r: np.ndarray, dow_dum: np.ndarray,
                  exog: Optional[np.ndarray] = None,
                  exog_contemp: bool = False) -> float:
    eta = params[-2]
    lam = params[-1]
    prg_params = params[:-2]
    if eta <= 2.01 or eta > 200.0 or abs(lam) >= 0.999:
        return 1e10
    h = _prg_variance_recursion(prg_params, r, dow_dum, exog, exog_contemp)
    if h is None:
        return 1e10
    N = len(r)
    h_v = h[1:N]
    r_v = r[1:N]
    if np.any(h_v <= 0):
        return 1e10
    z = r_v / np.sqrt(h_v)
    lp_z = hansen_skewt_logpdf(z, eta, lam)
    if not np.all(np.isfinite(lp_z)):
        return 1e10
    log_pdf_r = lp_z - 0.5 * np.log(h_v)
    nll = -float(np.sum(log_pdf_r))
    if not np.isfinite(nll):
        return 1e10
    return nll


# ======================================================================
# 5. Fitters (identical to d8; n_restarts controlled by caller)
# ======================================================================
def fit_prg_student(r: np.ndarray, dow_dum: np.ndarray,
                    exog: Optional[np.ndarray] = None,
                    exog_contemp: bool = False,
                    n_restarts: int = 10,
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


def fit_prg_skewt(r: np.ndarray, dow_dum: np.ndarray,
                  exog: Optional[np.ndarray] = None,
                  exog_contemp: bool = False,
                  n_restarts: int = 10,
                  x0_warm: Optional[np.ndarray] = None) -> Dict:
    r = np.asarray(r, dtype=float)
    use_exog = exog is not None
    local_rng = np.random.default_rng(42)
    best = {"nll": np.inf, "params": None, "success": False,
            "lambda_at_boundary": False}
    prg_base_dim = 10 if use_exog else 9
    dim = prg_base_dim + 2

    for trial in range(n_restarts):
        uncond = float(np.var(r, ddof=1))
        if trial == 0 and x0_warm is not None and len(x0_warm) == dim:
            x0 = np.array(x0_warm, dtype=float).copy()
        elif trial == 0:
            x0 = np.array([uncond * 0.5, 0.05, 0.0, 0.0, 0.0, 0.0,
                           0.05, 0.05, 0.80])
            if use_exog:
                x0 = np.concatenate([x0, [0.0]])
            x0 = np.concatenate([x0, [8.0, -0.10]])
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
            eta0 = 4.0 + 8.0 * local_rng.random()
            lam0 = -0.3 + 0.6 * local_rng.random()
            x0 = np.concatenate([x0, [eta0, lam0]])

        bounds = [
            (1e-8, None), (0.0, 1.0),
            (None, None), (None, None), (None, None), (None, None),
            (0.0, 0.4), (0.0, 0.4), (0.0, 0.9999),
        ]
        if use_exog:
            bounds.append((None, None))
        bounds.append((2.05, 200.0))
        bounds.append((-0.98, 0.98))

        try:
            res = optimize.minimize(
                prg_nll_skewt, x0, args=(r, dow_dum, exog, exog_contemp),
                method="L-BFGS-B", bounds=bounds,
                options={"maxiter": 500, "ftol": 1e-8},
            )
            if res.success and res.fun < best["nll"]:
                lam_at = abs(res.x[-1]) >= 0.95
                best = {"nll": float(res.fun),
                        "params": res.x.copy(),
                        "success": True,
                        "trial": trial,
                        "lambda_at_boundary": bool(lam_at)}
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


def prg_variance_path_skewt(params: np.ndarray, r: np.ndarray,
                            dow_dum: np.ndarray,
                            exog: Optional[np.ndarray] = None,
                            exog_contemp: bool = False) -> np.ndarray:
    if params is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    prg_params = params[:-2]
    h = _prg_variance_recursion(prg_params, r, dow_dum, exog, exog_contemp)
    if h is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    return h


# ======================================================================
# 6. Eval utilities (identical)
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


def skewt_loglik_per_obs(h_hat: np.ndarray, r: np.ndarray,
                         eta: float, lam: float) -> np.ndarray:
    eps = 1e-12
    h = np.maximum(h_hat, eps)
    if eta <= 2.0 or abs(lam) >= 1.0:
        return np.full_like(h, -np.inf)
    z = r / np.sqrt(h)
    lp_z = hansen_skewt_logpdf(z, eta, lam)
    return lp_z - 0.5 * np.log(h)


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


# ======================================================================
# 7. OOS expanding-window engine
# ======================================================================
def expanding_oos(r_target: np.ndarray, dow_dum: np.ndarray,
                  exog: Optional[np.ndarray],
                  exog_contemp: bool,
                  test_start_idx: int,
                  innovation: str,
                  label: str = "",
                  refit_every: int = REFIT_EVERY,
                  n_restarts_warm: int = N_RESTARTS_OOS_WARM,
                  n_restarts_cold: int = N_RESTARTS_OOS_COLD) -> Dict:
    assert innovation in ("student", "skewt")
    N = len(r_target)
    h_oos = np.full(N, np.nan)
    df_log = np.full(N, np.nan)
    eta_log = np.full(N, np.nan)
    lam_log = np.full(N, np.nan)
    params_log: List[Tuple[int, List[float]]] = []
    lambda_boundary_hits = 0
    current_params: Optional[np.ndarray] = None

    fit_fn = fit_prg_student if innovation == "student" else fit_prg_skewt
    path_fn = prg_variance_path_student if innovation == "student" else prg_variance_path_skewt

    t_started = time.time()
    for t in range(test_start_idx, N):
        steps = t - test_start_idx
        need_refit = (steps % refit_every == 0)
        # progress print every (refit_every*20) = every 100 obs
        if need_refit and steps > 0 and steps % (refit_every * 20) == 0:
            print(f"    [{label} t={t}/{N} "
                  f"elapsed={time.time() - t_started:.0f}s "
                  f"refits={len(params_log)}]")
        if need_refit:
            r_train = r_target[:t]
            dow_train = dow_dum[:t]
            ex_train = exog[:t] if exog is not None else None
            fit = fit_fn(r_train, dow_train,
                         exog=ex_train, exog_contemp=exog_contemp,
                         n_restarts=n_restarts_warm, x0_warm=current_params)
            if not fit["success"]:
                fit = fit_fn(r_train, dow_train,
                             exog=ex_train, exog_contemp=exog_contemp,
                             n_restarts=n_restarts_cold, x0_warm=None)
            if fit["success"]:
                current_params = fit["params"]
                params_log.append((int(t), current_params.tolist()))
                if innovation == "skewt" and fit.get("lambda_at_boundary"):
                    lambda_boundary_hits += 1
            else:
                print(f"  [warn {label}] refit failed at t={t}")
        if current_params is None:
            continue
        if innovation == "student":
            df_log[t] = float(current_params[-1])
        else:
            eta_log[t] = float(current_params[-2])
            lam_log[t] = float(current_params[-1])
        r_slice = r_target[:t + 1]
        dow_slice = dow_dum[:t + 1]
        ex_slice = exog[:t + 1] if exog is not None else None
        h_path = path_fn(current_params, r_slice, dow_slice,
                         exog=ex_slice, exog_contemp=exog_contemp)
        h_oos[t] = h_path[t]

    return {
        "h_oos": h_oos,
        "df_log": df_log,
        "eta_log": eta_log,
        "lam_log": lam_log,
        "params_log": params_log,
        "n_refits": len(params_log),
        "lambda_boundary_hits": lambda_boundary_hits,
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


# ======================================================================
# 8. Per-market pipeline (4 models)
# ======================================================================
def run_market(label: str, ticker: str, cache_file: str) -> Dict:
    print(f"\n=== [{label}] ({ticker}) ===")
    df_raw = fetch_daily(ticker, cache_file)
    s = build_market_series(df_raw)

    valid = (np.isfinite(s["r_intraday"]) & np.isfinite(s["gap2"]))
    valid &= (s["gap2"] > 0) | (s["r_intraday"] != 0)
    dates = pd.DatetimeIndex(pd.to_datetime(s["date"][valid]))
    r_intra = s["r_intraday"][valid].astype(float)
    r_ovn = s["r_overnight"][valid].astype(float)
    gap2 = s["gap2"][valid].astype(float)
    dow = s["dow"][valid].astype(int)
    N = len(r_intra)
    print(f"  Aligned rows (finite overnight): {N}")
    print(f"  Date range: {dates.min().date()} .. {dates.max().date()}")

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
        "gap2": {"mean": float(np.mean(gap2)), "sd": float(np.std(gap2))},
    }

    dow_dum = make_dow_dummies(dow)

    train_mask_arr = np.asarray(
        (dates >= TRAIN_START) & (dates <= TRAIN_END))
    test_mask_arr = np.asarray((dates >= TEST_START) & (dates <= TEST_END))
    train_idx = np.where(train_mask_arr)[0]
    test_idx = np.where(test_mask_arr)[0]
    if len(test_idx) == 0:
        raise RuntimeError(f"{label}: no test obs in range")
    test_start_idx = int(test_idx[0])
    test_end_idx = int(test_idx[-1])
    print(f"  Train n={len(train_idx)}  Test n={len(test_idx)}")

    # IS fits (match d8)
    print(f"  [{time.strftime('%H:%M:%S')}] IS fits (4 models) ...")
    t0 = time.time()
    fit_base_st = fit_prg_student(r_intra, dow_dum,
                                  exog=None, exog_contemp=False,
                                  n_restarts=N_RESTARTS_IS)
    t1 = time.time()
    fit_gap_st = fit_prg_student(r_intra, dow_dum,
                                 exog=gap2, exog_contemp=True,
                                 n_restarts=N_RESTARTS_IS)
    t2 = time.time()
    fit_base_sk = fit_prg_skewt(r_intra, dow_dum,
                                exog=None, exog_contemp=False,
                                n_restarts=N_RESTARTS_IS)
    t3 = time.time()
    fit_gap_sk = fit_prg_skewt(r_intra, dow_dum,
                               exog=gap2, exog_contemp=True,
                               n_restarts=N_RESTARTS_IS)
    t4 = time.time()
    print(f"    IS elapsed: base_st={t1 - t0:.1f}s  gap_st={t2 - t1:.1f}s  "
          f"base_sk={t3 - t2:.1f}s  gap_sk={t4 - t3:.1f}s")

    def pack_fit(fit: Dict, innov: str, use_exog: bool) -> Dict:
        if fit["params"] is None:
            return {"success": False, "log_lik": None}
        ll = -fit["nll"]
        out = {
            "success": bool(fit["success"]),
            "log_lik": float(ll),
            "params": fit["params"].tolist(),
        }
        if innov == "student":
            out["df"] = float(fit["params"][-1])
        else:
            out["eta"] = float(fit["params"][-2])
            out["lam"] = float(fit["params"][-1])
            out["lambda_at_boundary"] = bool(fit.get("lambda_at_boundary", False))
        if use_exog:
            out["xn_coef"] = float(fit["params"][9])
        return out

    is_base_st = pack_fit(fit_base_st, "student", False)
    is_gap_st = pack_fit(fit_gap_st, "student", True)
    is_base_sk = pack_fit(fit_base_sk, "skewt", False)
    is_gap_sk = pack_fit(fit_gap_sk, "skewt", True)

    for tag, r in (("base_st", is_base_st), ("gap_st", is_gap_st),
                   ("base_sk", is_base_sk), ("gap_sk", is_gap_sk)):
        ll = r.get("log_lik")
        extras = ""
        if "df" in r:
            extras = f" df={r['df']:.2f}"
        if "eta" in r:
            extras = f" η={r['eta']:.2f} λ={r['lam']:+.3f}"
            if r.get("lambda_at_boundary"):
                extras += " [λ BOUNDARY!]"
        if "xn_coef" in r:
            extras += f" ξ={r['xn_coef']:+.4f}"
        print(f"    M_{tag:8s} ll={ll:10.3f}{extras}  success={r['success']}")

    is_lrt_gap_st_vs_base_st = lrt_chi2_test(
        is_base_st.get("log_lik"), is_gap_st.get("log_lik"), dof=1)
    is_lrt_gap_sk_vs_base_sk = lrt_chi2_test(
        is_base_sk.get("log_lik"), is_gap_sk.get("log_lik"), dof=1)
    is_lrt_sk_vs_st_base = lrt_chi2_test(
        is_base_st.get("log_lik"), is_base_sk.get("log_lik"), dof=1)
    is_lrt_sk_vs_st_gap = lrt_chi2_test(
        is_gap_st.get("log_lik"), is_gap_sk.get("log_lik"), dof=1)

    is_result = {
        "M_base_st": is_base_st, "M_gap_st": is_gap_st,
        "M_base_sk": is_base_sk, "M_gap_sk": is_gap_sk,
        "lrt_gap_within_student": {
            "chi2": float(is_lrt_gap_st_vs_base_st[0])
                    if np.isfinite(is_lrt_gap_st_vs_base_st[0]) else None,
            "p": float(is_lrt_gap_st_vs_base_st[1])
                 if np.isfinite(is_lrt_gap_st_vs_base_st[1]) else None,
        },
        "lrt_gap_within_skewt": {
            "chi2": float(is_lrt_gap_sk_vs_base_sk[0])
                    if np.isfinite(is_lrt_gap_sk_vs_base_sk[0]) else None,
            "p": float(is_lrt_gap_sk_vs_base_sk[1])
                 if np.isfinite(is_lrt_gap_sk_vs_base_sk[1]) else None,
        },
        "lrt_innovation_base": {
            "chi2": float(is_lrt_sk_vs_st_base[0])
                    if np.isfinite(is_lrt_sk_vs_st_base[0]) else None,
            "p": float(is_lrt_sk_vs_st_base[1])
                 if np.isfinite(is_lrt_sk_vs_st_base[1]) else None,
            "note": "SkewT base vs Student-t base, restricting lambda=0",
        },
        "lrt_innovation_gap": {
            "chi2": float(is_lrt_sk_vs_st_gap[0])
                    if np.isfinite(is_lrt_sk_vs_st_gap[0]) else None,
            "p": float(is_lrt_sk_vs_st_gap[1])
                 if np.isfinite(is_lrt_sk_vs_st_gap[1]) else None,
            "note": "SkewT gap vs Student-t gap, restricting lambda=0",
        },
    }

    # OOS at d7 cadence
    print(f"  [{time.strftime('%H:%M:%S')}] OOS 4 models "
          f"(refit_every={REFIT_EVERY}, n_restarts_warm={N_RESTARTS_OOS_WARM}"
          f", cold={N_RESTARTS_OOS_COLD}) ...")
    t0 = time.time()
    oos_base_st = expanding_oos(r_intra, dow_dum, None, False,
                                test_start_idx, innovation="student",
                                label=f"{label}_base_st")
    print(f"    base_st: refits={oos_base_st['n_refits']}  "
          f"elapsed={time.time() - t0:.1f}s")
    t0 = time.time()
    oos_gap_st = expanding_oos(r_intra, dow_dum, gap2, True,
                               test_start_idx, innovation="student",
                               label=f"{label}_gap_st")
    print(f"    gap_st:  refits={oos_gap_st['n_refits']}  "
          f"elapsed={time.time() - t0:.1f}s")
    t0 = time.time()
    oos_base_sk = expanding_oos(r_intra, dow_dum, None, False,
                                test_start_idx, innovation="skewt",
                                label=f"{label}_base_sk")
    print(f"    base_sk: refits={oos_base_sk['n_refits']}  "
          f"λ-boundary hits={oos_base_sk['lambda_boundary_hits']}  "
          f"elapsed={time.time() - t0:.1f}s")
    t0 = time.time()
    oos_gap_sk = expanding_oos(r_intra, dow_dum, gap2, True,
                               test_start_idx, innovation="skewt",
                               label=f"{label}_gap_sk")
    print(f"    gap_sk:  refits={oos_gap_sk['n_refits']}  "
          f"λ-boundary hits={oos_gap_sk['lambda_boundary_hits']}  "
          f"elapsed={time.time() - t0:.1f}s")

    test_slice = slice(test_start_idx, test_end_idx + 1)
    r_test = r_intra[test_slice]
    r2_test = r_test ** 2
    d_test = pd.DatetimeIndex(np.asarray(dates)[test_slice])

    h_base_st = oos_base_st["h_oos"][test_slice]
    h_gap_st = oos_gap_st["h_oos"][test_slice]
    h_base_sk = oos_base_sk["h_oos"][test_slice]
    h_gap_sk = oos_gap_sk["h_oos"][test_slice]
    df_bst = oos_base_st["df_log"][test_slice]
    df_gst = oos_gap_st["df_log"][test_slice]
    eta_bsk = oos_base_sk["eta_log"][test_slice]
    lam_bsk = oos_base_sk["lam_log"][test_slice]
    eta_gsk = oos_gap_sk["eta_log"][test_slice]
    lam_gsk = oos_gap_sk["lam_log"][test_slice]

    valid_mask = (np.isfinite(h_base_st) & np.isfinite(h_gap_st)
                  & np.isfinite(h_base_sk) & np.isfinite(h_gap_sk)
                  & np.isfinite(df_bst) & np.isfinite(df_gst)
                  & np.isfinite(eta_bsk) & np.isfinite(eta_gsk)
                  & np.isfinite(lam_bsk) & np.isfinite(lam_gsk))
    n_valid = int(valid_mask.sum())
    print(f"  [OOS] n_valid across all 4 models = {n_valid}")

    r_v = r_test[valid_mask]
    r2_v = r2_test[valid_mask]
    hbst = h_base_st[valid_mask]
    hgst = h_gap_st[valid_mask]
    hbsk = h_base_sk[valid_mask]
    hgsk = h_gap_sk[valid_mask]
    dfb_v = df_bst[valid_mask]
    dfg_v = df_gst[valid_mask]
    etab_v = eta_bsk[valid_mask]
    lamb_v = lam_bsk[valid_mask]
    etag_v = eta_gsk[valid_mask]
    lamg_v = lam_gsk[valid_mask]
    d_v = d_test[valid_mask]

    q_base_st = qlike_loss(hbst, r2_v)
    q_gap_st = qlike_loss(hgst, r2_v)
    q_base_sk = qlike_loss(hbsk, r2_v)
    q_gap_sk = qlike_loss(hgsk, r2_v)

    ll_base_st_obs = np.array([
        float(student_loglik_per_obs(np.array([hbst[i]]),
                                     np.array([r_v[i]]), dfb_v[i])[0])
        for i in range(n_valid)])
    ll_gap_st_obs = np.array([
        float(student_loglik_per_obs(np.array([hgst[i]]),
                                     np.array([r_v[i]]), dfg_v[i])[0])
        for i in range(n_valid)])
    ll_base_sk_obs = np.array([
        float(skewt_loglik_per_obs(np.array([hbsk[i]]),
                                   np.array([r_v[i]]), etab_v[i], lamb_v[i])[0])
        for i in range(n_valid)])
    ll_gap_sk_obs = np.array([
        float(skewt_loglik_per_obs(np.array([hgsk[i]]),
                                   np.array([r_v[i]]), etag_v[i], lamg_v[i])[0])
        for i in range(n_valid)])

    dm_gap_st = dm_test_hln(q_base_st, q_gap_st)
    dm_gap_sk = dm_test_hln(q_base_sk, q_gap_sk)
    dm_innov_base = dm_test_hln(q_base_st, q_base_sk)
    dm_innov_gap = dm_test_hln(q_gap_st, q_gap_sk)
    dm_cross_best = dm_test_hln(q_base_st, q_gap_sk)

    dm_ll_gap_st = dm_test_hln(-ll_base_st_obs, -ll_gap_st_obs)
    dm_ll_gap_sk = dm_test_hln(-ll_base_sk_obs, -ll_gap_sk_obs)
    dm_ll_innov_gap = dm_test_hln(-ll_gap_st_obs, -ll_gap_sk_obs)

    oos_lrt_gap_st = lrt_chi2_test(float(np.sum(ll_base_st_obs)),
                                   float(np.sum(ll_gap_st_obs)), dof=1)
    oos_lrt_gap_sk = lrt_chi2_test(float(np.sum(ll_base_sk_obs)),
                                   float(np.sum(ll_gap_sk_obs)), dof=1)

    def _pct(a, b):
        return ((a - b) / abs(a) * 100) if a != 0 else np.nan

    imp_gap_st = _pct(float(np.mean(q_base_st)), float(np.mean(q_gap_st)))
    imp_gap_sk = _pct(float(np.mean(q_base_sk)), float(np.mean(q_gap_sk)))
    imp_innov_base = _pct(float(np.mean(q_base_st)), float(np.mean(q_base_sk)))
    imp_innov_gap = _pct(float(np.mean(q_gap_st)), float(np.mean(q_gap_sk)))

    harvey_gap_sk = (np.isfinite(dm_gap_sk[0]) and abs(dm_gap_sk[0]) > 3.0)

    print(f"  [OOS] DM(gap_st): t={dm_gap_st[0]:+.3f}  QLIKE imp={imp_gap_st:+.2f}%")
    print(f"  [OOS] DM(gap_sk): t={dm_gap_sk[0]:+.3f}  QLIKE imp={imp_gap_sk:+.2f}%  "
          f"Harvey |t|>3: {harvey_gap_sk}  <-- KEY")
    print(f"  [OOS] DM(innov_base): t={dm_innov_base[0]:+.3f}  "
          f"QLIKE imp={imp_innov_base:+.2f}%")
    print(f"  [OOS] DM(innov_gap): t={dm_innov_gap[0]:+.3f}  "
          f"QLIKE imp={imp_innov_gap:+.2f}%")

    annual = {}
    for yr in range(TEST_START.year, TEST_END.year + 1):
        mask = (d_v >= pd.Timestamp(yr, 1, 1)) & (d_v <= pd.Timestamp(yr, 12, 31))
        if mask.sum() < 30:
            continue
        dm_y_st, _ = dm_test_hln(q_base_st[mask], q_gap_st[mask])
        dm_y_sk, _ = dm_test_hln(q_base_sk[mask], q_gap_sk[mask])
        qbsk_y = float(np.mean(q_base_sk[mask]))
        imp_y_sk = ((qbsk_y - float(np.mean(q_gap_sk[mask]))) / abs(qbsk_y) * 100
                    if qbsk_y != 0 else np.nan)
        annual[str(yr)] = {
            "n": int(mask.sum()),
            "dm_gap_st_t": float(dm_y_st) if np.isfinite(dm_y_st) else None,
            "dm_gap_sk_t": float(dm_y_sk) if np.isfinite(dm_y_sk) else None,
            "qlike_imp_gap_sk_pct": float(imp_y_sk) if np.isfinite(imp_y_sk) else None,
        }

    oos_result = {
        "n_valid": n_valid,
        "test_start": str(TEST_START.date()),
        "test_end": str(TEST_END.date()),
        "refit_every": REFIT_EVERY,
        "n_restarts_warm": N_RESTARTS_OOS_WARM,
        "n_restarts_cold": N_RESTARTS_OOS_COLD,
        "dm_gap_within_student": {
            "t_hln": float(dm_gap_st[0]) if np.isfinite(dm_gap_st[0]) else None,
            "p": float(dm_gap_st[1]) if np.isfinite(dm_gap_st[1]) else None,
            "qlike_improv_pct": float(imp_gap_st) if np.isfinite(imp_gap_st) else None,
            "lrt_chi2": float(oos_lrt_gap_st[0]) if np.isfinite(oos_lrt_gap_st[0]) else None,
            "lrt_p": float(oos_lrt_gap_st[1]) if np.isfinite(oos_lrt_gap_st[1]) else None,
            "dm_loglik_t_hln": float(dm_ll_gap_st[0]) if np.isfinite(dm_ll_gap_st[0]) else None,
        },
        "dm_gap_within_skewt": {
            "t_hln": float(dm_gap_sk[0]) if np.isfinite(dm_gap_sk[0]) else None,
            "p": float(dm_gap_sk[1]) if np.isfinite(dm_gap_sk[1]) else None,
            "qlike_improv_pct": float(imp_gap_sk) if np.isfinite(imp_gap_sk) else None,
            "lrt_chi2": float(oos_lrt_gap_sk[0]) if np.isfinite(oos_lrt_gap_sk[0]) else None,
            "lrt_p": float(oos_lrt_gap_sk[1]) if np.isfinite(oos_lrt_gap_sk[1]) else None,
            "dm_loglik_t_hln": float(dm_ll_gap_sk[0]) if np.isfinite(dm_ll_gap_sk[0]) else None,
            "harvey_pass": bool(harvey_gap_sk),
        },
        "dm_innov_base": {
            "t_hln": float(dm_innov_base[0]) if np.isfinite(dm_innov_base[0]) else None,
            "p": float(dm_innov_base[1]) if np.isfinite(dm_innov_base[1]) else None,
            "qlike_improv_pct": float(imp_innov_base) if np.isfinite(imp_innov_base) else None,
        },
        "dm_innov_gap": {
            "t_hln": float(dm_innov_gap[0]) if np.isfinite(dm_innov_gap[0]) else None,
            "p": float(dm_innov_gap[1]) if np.isfinite(dm_innov_gap[1]) else None,
            "qlike_improv_pct": float(imp_innov_gap) if np.isfinite(imp_innov_gap) else None,
            "dm_loglik_t_hln": float(dm_ll_innov_gap[0])
                               if np.isfinite(dm_ll_innov_gap[0]) else None,
        },
        "dm_cross_best": {
            "t_hln": float(dm_cross_best[0]) if np.isfinite(dm_cross_best[0]) else None,
            "p": float(dm_cross_best[1]) if np.isfinite(dm_cross_best[1]) else None,
            "note": "DM(M_base_student vs M_gap_skewt)",
        },
        "qlike_means": {
            "base_st": float(np.mean(q_base_st)),
            "gap_st": float(np.mean(q_gap_st)),
            "base_sk": float(np.mean(q_base_sk)),
            "gap_sk": float(np.mean(q_gap_sk)),
        },
        "ll_sums": {
            "base_st": float(np.sum(ll_base_st_obs)),
            "gap_st": float(np.sum(ll_gap_st_obs)),
            "base_sk": float(np.sum(ll_base_sk_obs)),
            "gap_sk": float(np.sum(ll_gap_sk_obs)),
        },
        "skewt_param_oos_summary": {
            "base_sk": {
                "eta_mean": float(np.mean(etab_v)),
                "eta_sd": float(np.std(etab_v)),
                "lam_mean": float(np.mean(lamb_v)),
                "lam_sd": float(np.std(lamb_v)),
                "lambda_boundary_hits": int(oos_base_sk["lambda_boundary_hits"]),
            },
            "gap_sk": {
                "eta_mean": float(np.mean(etag_v)),
                "eta_sd": float(np.std(etag_v)),
                "lam_mean": float(np.mean(lamg_v)),
                "lam_sd": float(np.std(lamg_v)),
                "lambda_boundary_hits": int(oos_gap_sk["lambda_boundary_hits"]),
            },
        },
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
            "q_base_st": q_base_st, "q_gap_st": q_gap_st,
            "q_base_sk": q_base_sk, "q_gap_sk": q_gap_sk,
            "eta_gsk_oos": etag_v, "lam_gsk_oos": lamg_v,
        },
    }


# ======================================================================
# 9. d7 / d8 anchor loaders
# ======================================================================
def load_anchor(path: Path, label: str) -> Dict:
    if not path.exists():
        print(f"  [warn] {label} results not found at {path}")
        return {}
    with open(path) as f:
        data = json.load(f)
    out = {}
    # d7 format: markets -> oos.dm_qlike_t_hln
    # d8 format: markets -> oos.dm_gap_within_student + dm_gap_within_skewt
    for k in ("SPY", "N225"):
        m = data.get("markets", {}).get(k, {})
        if not m:
            continue
        oos = m.get("oos", {})
        entry = {"n_valid": oos.get("n_valid")}
        if "dm_qlike_t_hln" in oos:
            entry["dm_gap_st_t_hln"] = oos.get("dm_qlike_t_hln")
            entry["qlike_imp_gap_st_pct"] = oos.get("qlike_improv_pct")
        if "dm_gap_within_student" in oos:
            entry["dm_gap_st_t_hln"] = oos["dm_gap_within_student"].get("t_hln")
            entry["qlike_imp_gap_st_pct"] = oos["dm_gap_within_student"].get(
                "qlike_improv_pct")
        if "dm_gap_within_skewt" in oos:
            entry["dm_gap_sk_t_hln"] = oos["dm_gap_within_skewt"].get("t_hln")
            entry["qlike_imp_gap_sk_pct"] = oos["dm_gap_within_skewt"].get(
                "qlike_improv_pct")
        if "dm_innov_gap" in oos:
            entry["dm_innov_gap_t_hln"] = oos["dm_innov_gap"].get("t_hln")
        out[k] = entry
    out["source"] = str(path.name)
    return out


# ======================================================================
# 10. Cadence-sensitivity verdict
# ======================================================================
def classify_d9_verdict(markets_out: Dict[str, Dict],
                        d7_anchor: Dict, d8_anchor: Dict) -> Dict:
    """Compare d9 (d7-cadence) results with d7 Student-t anchor and d8 skewed-t anchor."""

    def _get(market, key1, key2=None):
        m = markets_out.get(market, {})
        if not m or "error" in m:
            return None
        oos = m.get("oos", {})
        if key2:
            return oos.get(key1, {}).get(key2)
        return oos.get(key1)

    def _pct_match(a, b, tol=0.3):
        """|a-b| < tol × max(|a|,|b|,1)"""
        if a is None or b is None:
            return None
        scale = max(abs(a), abs(b), 1.0)
        return abs(a - b) < tol * scale

    # d9 DM values
    n225_d9_st = _get("N225", "dm_gap_within_student", "t_hln")
    n225_d9_sk = _get("N225", "dm_gap_within_skewt", "t_hln")
    spy_d9_st = _get("SPY", "dm_gap_within_student", "t_hln")
    spy_d9_sk = _get("SPY", "dm_gap_within_skewt", "t_hln")

    # d7 Student-t anchors (true d7-cadence reference)
    n225_d7_st = d7_anchor.get("N225", {}).get("dm_gap_st_t_hln")
    spy_d7_st = d7_anchor.get("SPY", {}).get("dm_gap_st_t_hln")

    # d8 references (refit=25 cadence)
    n225_d8_st = d8_anchor.get("N225", {}).get("dm_gap_st_t_hln")
    n225_d8_sk = d8_anchor.get("N225", {}).get("dm_gap_sk_t_hln")
    spy_d8_st = d8_anchor.get("SPY", {}).get("dm_gap_st_t_hln")
    spy_d8_sk = d8_anchor.get("SPY", {}).get("dm_gap_sk_t_hln")

    # Sign-flip diagnostics
    n225_st_sign_flip = (
        n225_d7_st is not None and n225_d8_st is not None
        and np.sign(n225_d7_st) != np.sign(n225_d8_st))
    spy_st_sign_flip = (
        spy_d7_st is not None and spy_d8_st is not None
        and np.sign(spy_d7_st) != np.sign(spy_d8_st))

    # Did d9 restore d7 Student-t sign?
    n225_st_restored = (n225_d9_st is not None and n225_d7_st is not None
                       and np.sign(n225_d9_st) == np.sign(n225_d7_st)
                       and abs(n225_d9_st) > 1.0)
    spy_st_restored = (spy_d9_st is not None and spy_d7_st is not None
                      and np.sign(spy_d9_st) == np.sign(spy_d7_st))

    # Harvey on skewed-t under proper cadence
    harvey_n225_sk = (n225_d9_sk is not None and abs(n225_d9_sk) > 3.0
                     and n225_d9_sk > 0)
    harvey_spy_sk = (spy_d9_sk is not None and abs(spy_d9_sk) > 3.0
                    and spy_d9_sk > 0)

    # Innovation-upgrade diagnostic under proper cadence
    innov_gap_n225 = _get("N225", "dm_innov_gap", "t_hln")
    innov_gap_spy = _get("SPY", "dm_innov_gap", "t_hln")

    # Classification
    reasons = []
    if harvey_n225_sk:
        verdict = "PASS_N225_HARVEY_UNDER_CADENCE"
        reasons.append(
            f"N225 gap_sk DM-HLN t={n225_d9_sk:+.2f} PASSES Harvey under proper"
            f" cadence (refit_every=5); d8 at refit=25 reported {n225_d8_sk:+.2f}"
            f" → d8 conclusion REVERSED; skewed-t DOES help when cadence is right.")
    elif n225_st_restored and abs(n225_d9_sk or 0) < 1.96:
        verdict = "ROBUST_WITH_RECOVERY"
        reasons.append(
            f"N225 Student-t DM restored ({n225_d9_st:+.2f} under d9 cadence "
            f"vs {n225_d7_st:+.2f} d7; d8 was {n225_d8_st:+.2f}), confirming "
            f"the refit-cadence artifact. Skewed-t gap DM still borderline "
            f"({n225_d9_sk:+.2f}, |t|<1.96); d8 "
            f"'skewed-t does not help' conclusion HOLDS with a proper baseline.")
    elif n225_st_restored:
        verdict = "ROBUST_WITH_RECOVERY_SK_BORDERLINE"
        reasons.append(
            f"N225 Student-t DM restored ({n225_d9_st:+.2f}), confirming cadence artifact. "
            f"Skewed-t gap DM={n225_d9_sk:+.2f} is 5%-significant but below Harvey "
            f"|t|>3; d7 verdict DIRECTION_CONSISTENT_ALL_BORDERLINE extends to skewed-t.")
    elif not n225_st_restored:
        verdict = "NON_RECOVERY"
        reasons.append(
            f"N225 Student-t DM did NOT restore to d7 sign (d9={n225_d9_st}, "
            f"d7={n225_d7_st}). Either (a) cadence is not the dominant driver of "
            f"d8 sign flip, (b) d7 itself was unstable, or (c) other cadence-related "
            f"numerical issue. Cannot cleanly attribute d8 skewed-t result to "
            f"cadence artifact; d8 conclusion needs independent verification.")
    else:
        verdict = "MIXED"
        reasons.append("Unclear pattern; see per-market details.")

    # SPY-side annotation
    if spy_st_restored:
        reasons.append(f"SPY Student-t DM sign recovered: d9={spy_d9_st:+.2f}, d7={spy_d7_st:+.2f}.")
    elif spy_d9_st is not None and spy_d7_st is not None:
        reasons.append(f"SPY Student-t DM did NOT recover: d9={spy_d9_st:+.2f}, d7={spy_d7_st:+.2f}.")

    if harvey_spy_sk:
        reasons.append(f"SPY skewed-t gap DM PASSES Harvey ({spy_d9_sk:+.2f}).")

    # Cadence-sensitivity verdict (for the Paper 3 narrative state machine)
    if (n225_st_restored and spy_st_restored
        and not harvey_n225_sk and not harvey_spy_sk):
        cadence_verdict = "CADENCE_ARTIFACT_FOR_STUDENT_T_NOT_FOR_SKEWED_T"
    elif harvey_n225_sk or harvey_spy_sk:
        cadence_verdict = "CADENCE_ARTIFACT_MASKED_SKEWT_GAIN"
    elif not n225_st_restored and not spy_st_restored:
        cadence_verdict = "CADENCE_NOT_DOMINANT_DRIVER"
    else:
        cadence_verdict = "MIXED_ACROSS_MARKETS"

    return {
        "verdict": verdict,
        "cadence_sensitivity_verdict": cadence_verdict,
        "reason": " ".join(reasons),
        "evidence": {
            "N225": {
                "d7_st": n225_d7_st, "d8_st": n225_d8_st, "d9_st": n225_d9_st,
                "d8_sk": n225_d8_sk, "d9_sk": n225_d9_sk,
                "d7_to_d8_sign_flip": bool(n225_st_sign_flip),
                "d9_restored_d7_sign": bool(n225_st_restored),
                "d9_innov_gap_t": innov_gap_n225,
            },
            "SPY": {
                "d7_st": spy_d7_st, "d8_st": spy_d8_st, "d9_st": spy_d9_st,
                "d8_sk": spy_d8_sk, "d9_sk": spy_d9_sk,
                "d7_to_d8_sign_flip": bool(spy_st_sign_flip),
                "d9_restored_d7_sign": bool(spy_st_restored),
                "d9_innov_gap_t": innov_gap_spy,
            },
        },
        "harvey_pass_under_cadence": {
            "N225_gap_sk": bool(harvey_n225_sk),
            "SPY_gap_sk": bool(harvey_spy_sk),
        },
    }


# ======================================================================
# 11. Plots
# ======================================================================
def plot_cadence_comparison(markets_out: Dict, d7_anchor: Dict,
                             d8_anchor: Dict, verdict: Dict):
    """Student-t DM: d7 vs d8 vs d9, cross-market bars."""
    markets = ["N225", "SPY"]
    d7_vals = []
    d8_vals = []
    d9_vals = []
    d9_sk_vals = []
    d8_sk_vals = []
    for k in markets:
        d7_vals.append(d7_anchor.get(k, {}).get("dm_gap_st_t_hln", np.nan) or np.nan)
        d8_vals.append(d8_anchor.get(k, {}).get("dm_gap_st_t_hln", np.nan) or np.nan)
        d8_sk_vals.append(d8_anchor.get(k, {}).get("dm_gap_sk_t_hln", np.nan) or np.nan)
        oos = markets_out.get(k, {}).get("oos", {})
        d9_vals.append(oos.get("dm_gap_within_student", {}).get("t_hln") or np.nan)
        d9_sk_vals.append(oos.get("dm_gap_within_skewt", {}).get("t_hln") or np.nan)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    x = np.arange(len(markets))

    # Left: Student-t DM across refits
    ax = axes[0]
    w = 0.25
    ax.bar(x - w, d7_vals, w, color="#1f77b4", label="d7 (refit=5)")
    ax.bar(x, d8_vals, w, color="#ff7f0e", label="d8 (refit=25)")
    ax.bar(x + w, d9_vals, w, color="#2ca02c", label="d9 (refit=5 rerun)")
    ax.axhline(3.0, ls="--", color="#444", alpha=0.7, label="Harvey |t|=3")
    ax.axhline(-3.0, ls="--", color="#444", alpha=0.7)
    ax.axhline(1.96, ls=":", color="#666", alpha=0.5)
    ax.axhline(-1.96, ls=":", color="#666", alpha=0.5)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(markets)
    ax.set_ylabel("OOS DM-HLN t (gap² vs no-gap, Student-t)")
    ax.set_title("Student-t: cadence sensitivity")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=0.3, axis="y")
    for i, (a, b, c) in enumerate(zip(d7_vals, d8_vals, d9_vals)):
        for off, v in ((-w, a), (0, b), (w, c)):
            if np.isfinite(v):
                ax.text(i + off, v + 0.1 * (1 if v >= 0 else -1),
                        f"{v:+.2f}", ha="center", fontsize=7)

    # Right: Skewed-t DM d8 vs d9
    ax = axes[1]
    w = 0.35
    ax.bar(x - w / 2, d8_sk_vals, w, color="#d62728", label="d8 (refit=25)")
    ax.bar(x + w / 2, d9_sk_vals, w, color="#9467bd", label="d9 (refit=5)")
    ax.axhline(3.0, ls="--", color="#444", alpha=0.7, label="Harvey |t|=3")
    ax.axhline(-3.0, ls="--", color="#444", alpha=0.7)
    ax.axhline(1.96, ls=":", color="#666", alpha=0.5)
    ax.axhline(-1.96, ls=":", color="#666", alpha=0.5)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(markets)
    ax.set_title("Hansen skewed-t: cadence sensitivity")
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(alpha=0.3, axis="y")
    for i, (a, b) in enumerate(zip(d8_sk_vals, d9_sk_vals)):
        for off, v in ((-w / 2, a), (w / 2, b)):
            if np.isfinite(v):
                ax.text(i + off, v + 0.1 * (1 if v >= 0 else -1),
                        f"{v:+.2f}", ha="center", fontsize=7)

    fig.suptitle(
        f"K1100g_d9 cadence-sensitivity  —  {verdict['cadence_sensitivity_verdict']}",
        fontsize=11)
    plt.tight_layout()
    out = SCRIPT_DIR / "k1100g_d9_cadence_sensitivity.png"
    plt.savefig(out, dpi=120)
    plt.close()
    print(f"  [plot] {out.name}")


def plot_skewt_param_stability(markets_out: Dict):
    """OOS (eta, lambda) time series for gap_sk — check d8's 'frozen params' concern."""
    fig, axes = plt.subplots(2, 2, figsize=(12, 7), sharex=True)
    for col, k in enumerate(("N225", "SPY")):
        m = markets_out.get(k, {})
        if "error" in m or "oos" not in m:
            continue
        internals = m.get("_internals", {})
        dates = internals.get("dates_test")
        eta = internals.get("eta_gsk_oos")
        lam = internals.get("lam_gsk_oos")
        if dates is None or eta is None or lam is None:
            continue
        axes[0, col].plot(dates, eta, color="#2ca02c", lw=1.0)
        axes[0, col].set_title(f"{k}  η(t) OOS (gap_sk)")
        axes[0, col].set_ylabel("η")
        axes[0, col].grid(alpha=0.3)
        axes[1, col].plot(dates, lam, color="#9467bd", lw=1.0)
        axes[1, col].axhline(0, color="black", ls=":", alpha=0.5)
        axes[1, col].set_title(f"{k}  λ(t) OOS (gap_sk)")
        axes[1, col].set_ylabel("λ")
        axes[1, col].grid(alpha=0.3)
    fig.suptitle("K1100g_d9 OOS skewed-t parameter time series  (vs d8 frozen warm-start)",
                 fontsize=11)
    plt.tight_layout()
    out = SCRIPT_DIR / "k1100g_d9_skewt_param_stability.png"
    plt.savefig(out, dpi=120)
    plt.close()
    print(f"  [plot] {out.name}")


# ======================================================================
# 12. Main
# ======================================================================
def run():
    t_total = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] K1100g_d9 cadence-robustness rerun start")
    print(f"  REFIT_EVERY={REFIT_EVERY} (d7=5, d8=25)")
    print(f"  N_RESTARTS_OOS_WARM={N_RESTARTS_OOS_WARM} (d7=4, d8=2)")
    print(f"  N_RESTARTS_OOS_COLD={N_RESTARTS_OOS_COLD} (d7=6, d8=4)")

    markets_out: Dict[str, Dict] = {}
    for label, ticker, cache_file in MARKETS:
        try:
            res = run_market(label, ticker, cache_file)
            markets_out[label] = res
        except Exception as exc:
            import traceback
            traceback.print_exc()
            markets_out[label] = {"error": str(exc)}

    print(f"\n[{time.strftime('%H:%M:%S')}] Loading d7 + d8 anchors ...")
    d7_anchor = load_anchor(D7_RESULTS, "d7")
    d8_anchor = load_anchor(D8_RESULTS, "d8")
    for k in ("N225", "SPY"):
        d7e = d7_anchor.get(k, {})
        d8e = d8_anchor.get(k, {})
        print(f"  {k}  d7 Student-t DM={d7e.get('dm_gap_st_t_hln')}")
        print(f"  {k}  d8 Student-t DM={d8e.get('dm_gap_st_t_hln')}  "
              f"Skewed-t DM={d8e.get('dm_gap_sk_t_hln')}")

    verdict = classify_d9_verdict(markets_out, d7_anchor, d8_anchor)
    print(f"\n[{time.strftime('%H:%M:%S')}] === Verdict: {verdict['verdict']} ===")
    print(f"  cadence_sensitivity: {verdict['cadence_sensitivity_verdict']}")
    print(f"  {verdict['reason']}")

    clean_markets = {}
    for k, v in markets_out.items():
        if "error" in v:
            clean_markets[k] = v
            continue
        clean_markets[k] = {kk: vv for kk, vv in v.items() if kk != "_internals"}

    # Point estimates + CI (from DM t -> Wald CI assuming asymptotic normality of loss diff)
    def _point_ci(oos_sub):
        """Build (point, 95% CI) triple for DM statistics."""
        out = {}
        for key in ("dm_gap_within_student", "dm_gap_within_skewt",
                    "dm_innov_gap"):
            d = oos_sub.get(key, {})
            t = d.get("t_hln")
            if t is None:
                out[key] = {"t": None, "ci95_lower": None, "ci95_upper": None}
            else:
                out[key] = {
                    "t": t,
                    "ci95_lower": t - 1.96,
                    "ci95_upper": t + 1.96,
                }
        return out

    point_estimates = {}
    ci_all = {}
    for k in ("N225", "SPY"):
        m = clean_markets.get(k, {})
        if "error" in m or "oos" not in m:
            continue
        point_estimates[k] = {
            "dm_gap_st_t": m["oos"].get("dm_gap_within_student", {}).get("t_hln"),
            "dm_gap_sk_t": m["oos"].get("dm_gap_within_skewt", {}).get("t_hln"),
            "dm_innov_gap_t": m["oos"].get("dm_innov_gap", {}).get("t_hln"),
            "qlike_imp_gap_st_pct": m["oos"].get("dm_gap_within_student", {}).get(
                "qlike_improv_pct"),
            "qlike_imp_gap_sk_pct": m["oos"].get("dm_gap_within_skewt", {}).get(
                "qlike_improv_pct"),
        }
        ci_all[k] = _point_ci(m["oos"])

    # DM stat vs d8: approximate (d9_t - d8_t), no joint variance available since d8
    # and d9 use different samples→ just report deltas
    dm_stat_vs_d8 = {}
    for k in ("N225", "SPY"):
        m = clean_markets.get(k, {})
        if "error" in m or "oos" not in m:
            continue
        d9_gap_st = m["oos"].get("dm_gap_within_student", {}).get("t_hln")
        d9_gap_sk = m["oos"].get("dm_gap_within_skewt", {}).get("t_hln")
        d8_gap_st = d8_anchor.get(k, {}).get("dm_gap_st_t_hln")
        d8_gap_sk = d8_anchor.get(k, {}).get("dm_gap_sk_t_hln")
        d7_gap_st = d7_anchor.get(k, {}).get("dm_gap_st_t_hln")
        dm_stat_vs_d8[k] = {
            "delta_gap_st_d9_minus_d8": (
                (d9_gap_st - d8_gap_st) if (d9_gap_st is not None
                                            and d8_gap_st is not None) else None),
            "delta_gap_sk_d9_minus_d8": (
                (d9_gap_sk - d8_gap_sk) if (d9_gap_sk is not None
                                            and d8_gap_sk is not None) else None),
            "delta_gap_st_d9_minus_d7": (
                (d9_gap_st - d7_gap_st) if (d9_gap_st is not None
                                            and d7_gap_st is not None) else None),
            "note": ("d9 and d8 use the same raw data but different refit "
                     "cadence; d9 and d7 use the same cadence and same data "
                     "but different n_restarts. Deltas are descriptive only; "
                     "no formal joint test across nested designs."),
        }

    result = {
        "experiment_id": "K1100g_d9",
        "title": ("Refit-cadence robustness rerun of K1100g_d8 at d7 cadence "
                  "(refit_every=5) — test whether d8 Student-t sign flip and "
                  "skewed-t result were driven by refit cadence"),
        "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "seed": 42,
        "parent_chain": [
            "K1100g", "K1100g_d1", "K1100g_d3", "K1100g_d5",
            "K1100g_d6", "K1100g_d7", "K1100g_d8",
        ],
        "references": [
            "Hansen (1994) IER 35(3) — Autoregressive conditional density",
            "Jondeau & Rockinger (2003) JEDC 27(10)",
            "Bollerslev (1987) REStat 69(3)",
            "Engle & Rangel (2008) RFS 21(3)",
            "Harvey et al. (1997) IJF 13(2) — HLN DM correction",
            "Harvey (2016) JF — t>3 threshold",
        ],
        "design": {
            "markets": [{"label": l, "ticker": t, "cache": c}
                         for l, t, c in MARKETS],
            "target_return": "r_intraday[t] = log(Close_t / Open_t)",
            "exog": "gap²[t] = (log Open_t - log Close_{t-1})²",
            "innovations_compared": ["student", "skewt"],
            "skewt_spec": ("Hansen (1994) eq. 9-10 closed form, E[z]=0, Var[z]=1, "
                           "η∈(2.05, 200), λ∈(-0.98, 0.98)"),
            "train_start": str(TRAIN_START.date()),
            "train_end": str(TRAIN_END.date()),
            "test_start": str(TEST_START.date()),
            "test_end": str(TEST_END.date()),
            "refit_every": REFIT_EVERY,
            "n_restarts_is": N_RESTARTS_IS,
            "n_restarts_oos_warm": N_RESTARTS_OOS_WARM,
            "n_restarts_oos_cold": N_RESTARTS_OOS_COLD,
            "cadence_comparison": {
                "d7": {"refit_every": 5, "n_restarts_warm": 4, "n_restarts_cold": 6,
                       "innovation": "student"},
                "d8": {"refit_every": 25, "n_restarts_warm": 2, "n_restarts_cold": 4,
                       "innovation": "student + skewt"},
                "d9": {"refit_every": 5, "n_restarts_warm": 4, "n_restarts_cold": 6,
                       "innovation": "student + skewt",
                       "purpose": "robustness check"},
            },
        },
        "markets": clean_markets,
        "d7_anchor": d7_anchor,
        "d8_anchor": d8_anchor,
        "point_estimates": point_estimates,
        "CI": ci_all,
        "DM_stat_vs_d8": dm_stat_vs_d8,
        "verdict": verdict,
        "cadence_sensitivity_verdict": verdict["cadence_sensitivity_verdict"],
        "limitations": [
            "d7 cadence (refit_every=5) rerun across 4 models × 2 markets ~6× slower"
            " than d8; runtime ~60-120 minutes expected.",
            "Student-t baseline uses n_restarts_warm=4 (d7) not 8 (d7 original IS) "
            "to match d7's OOS cadence exactly; IS fits still use n_restarts=10.",
            "d9 and d8 use the same raw data + same TRAIN/TEST split; differences "
            "arise only from refit cadence and n_restarts schedule.",
            "DM(d9 vs d8) deltas are descriptive only; no formal joint test across "
            "nested designs because d8 and d9 share samples but produce different "
            "point forecasts.",
            "yfinance daily OHLC only; 5-min intraday not available at 15-year span.",
            "TAIFEX not rerun (small-sample concern + Student-t anchor is d5 reference).",
        ],
    }

    result = clean_for_json(result)
    with open(RESULTS_PATH, "w") as f:
        json.dump(result, f, indent=2, allow_nan=False)
    print(f"\n[OK] results -> {RESULTS_PATH.name}")

    try:
        plot_cadence_comparison(markets_out, d7_anchor, d8_anchor, verdict)
        plot_skewt_param_stability(markets_out)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"  [warn] plotting failed: {exc}")

    print(f"\n[DONE] total elapsed: {time.time() - t_total:.1f}s")
    return result


if __name__ == "__main__":
    run()
