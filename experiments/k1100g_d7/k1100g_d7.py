"""
K1100g_d7 — Cross-market replication: SPY + N225 overnight gap^2 → intraday r^2
==============================================================================

Parent chain:
  - K1100g       : TAIFEX overnight/day vol ratio 1.586 (anchor)
  - K1100g_d1-d5 : Single-market analyses all landed borderline
                   (DM t 1.3-2.0, below Harvey 2016 threshold 3.0)

Question this experiment addresses:
  Is the TAIFEX "overnight info predicts day session variance" signal
  a **universal structural property** or a **Taiwan-specific artifact**
  of the emerging-market / narrow-breadth index?

Hypotheses:
  H1 universal       : Both SPY and N225 OOS DM t > 3 → TAIFEX borrowed N,
                       structural claim passes cross-market robustness
  H2 market-specific : Both SPY and N225 NS (|t| < 2) → effect is Taiwan-only
  H3 partial         : Exactly one market passes Harvey → regional variation

Design (cross-market common framework):
  Daily OHLC from yfinance 2005-01-01 ~ 2024-12-31:
    SPY  (S&P 500 ETF, US market)        N ~ 5030
    ^N225 (Nikkei 225 index, Japan)      N ~ 4900

  Decomposition (daily OHLC only — no intraday session split):
    r_intraday[t] = log(Close[t] / Open[t])      ← day session return
    r_gap[t]      = log(Open[t] / Close[t-1])    ← overnight gap
    r_cc[t]       = log(Close[t] / Close[t-1]) = r_intraday[t] + r_gap[t]

  Information set (analogous to TAIFEX overnight→day):
    r_gap[t]   is realized BEFORE the day session opens   → exog for r_intraday[t]
    r_gap[t-1] is yesterday's gap, trivially legal        → alternative lag
    r_intraday[t-1], r_gap[t-1] are both legal

Models (all Student-t innovation, per K1100g_d3 lesson E074 fat-tail QML):
  M1 baseline : GJR-GARCH(1,1)-t on r_intraday[t]
                h_t = omega + alpha*r²[t-1] + gamma*r²[t-1]*I(r<0) + beta*h[t-1]
                omega re-parameterized so unconditional var = sample var
  M2_gap      : M1 + xi * r_gap[t]²  (overnight gap² as exog, legal contemp)
  M2_gap_lag  : M1 + xi * r_gap[t-1]² (lagged gap²; sanity check)
  M4_night    : M1 + xi * r_intraday[t-1]² (control: yesterday intraday)

  Note: For TAIFEX we had an explicit "night session" 5-min RV; here we
  don't have free intraday data, so we use gap² as the closest proxy for
  "overnight information aggregated into the open price."

Evaluation:
  IS  : Full-sample LRT (df=1) for each exog model vs M1 baseline
  OOS : Expanding-window refit every 20 days, train first 60%, test last 40%
        (longer window than K1100g_d3 REFIT_EVERY=5 for computational tractability)
  DM  : HLN-corrected DM t-stat (Harvey 2016 threshold |t| > 3)
        QLIKE loss on r_intraday[t]² (Patton 2011 proxy-robust)

Lookahead discipline:
  - r_gap[t] uses Open[t] and Close[t-1] — both realized BEFORE intraday starts
  - Student-t innovation (K1100g_d3 lesson E074)
  - seed=42; L-BFGS-B deterministic
  - OOS h[t] = f(r[t-1], h[t-1], gap_exog[t]) — no future info

Author: Claude (worktree agent-a7aac49d)
Date: 2026-04-13
Seed: 42

References (cross-market replication context):
  - Andersen, Bollerslev, Huang (2011) JoE 160(1) — overnight jump
  - French & Roll (1986) JFE 17(1) — non-trading-hours info
  - Bollerslev (1987) REStat 69(3) — Student-t GARCH
  - Glosten, Jagannathan, Runkle (1993) JoF 48(5) — GJR asymmetry
  - Harvey, Leybourne, Newbold (1997) IJF 13(2) — HLN DM correction
  - Harvey (2016) JF — t>3 threshold
  - Patton (2011) JoE 160(1) — QLIKE proxy-robust
  - Engle & Ng (1993) JoF — news impact curve (asymmetry)
"""
from __future__ import annotations

import json
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import optimize
from scipy.special import gammaln
from scipy.stats import norm, chi2, skew as skew_fn, kurtosis as kurt_fn

warnings.filterwarnings("ignore")
np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)
RESULTS_PATH = SCRIPT_DIR / "k1100g_d7_results.json"

START_DATE = "2005-01-01"
END_DATE = "2024-12-31"
REFIT_EVERY = 20      # OOS expanding-window refit cadence (days)
TRAIN_FRAC = 0.60     # first 60% is in-sample
HARVEY_T = 3.0        # Harvey (2016) threshold
CHI2_1_1pct = 6.635   # chi²(1) critical value at 1%


# ======================================================================
# 1. Data loading (yfinance daily OHLC with cache)
# ======================================================================
def load_market(ticker: str, cache_name: str) -> pd.DataFrame:
    cache_path = DATA_DIR / f"_cache_{cache_name}_{START_DATE}_{END_DATE}.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        print(f"  loaded {ticker} from cache: {df.shape}")
        return df
    print(f"  fetching {ticker} from yfinance...")
    raw = yf.download(ticker, start=START_DATE, end=END_DATE,
                      auto_adjust=False, progress=False)
    # yfinance 1.2 returns MultiIndex columns; flatten
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0] for c in raw.columns]
    raw = raw[["Open", "High", "Low", "Close", "Volume"]].copy()
    raw.index = pd.to_datetime(raw.index)
    raw = raw.dropna()
    raw.to_parquet(cache_path)
    print(f"  cached to {cache_path}: {raw.shape}")
    return raw


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    open_p = df["Open"].astype(float).values
    close_p = df["Close"].astype(float).values

    # intraday return (Close/Open) — day session
    r_intra = np.log(close_p / open_p)
    # overnight gap (Open_t / Close_{t-1}) — NaN for t=0
    r_gap = np.concatenate([[np.nan], np.log(open_p[1:] / close_p[:-1])])
    # close-to-close
    r_cc = np.concatenate([[np.nan], np.log(close_p[1:] / close_p[:-1])])

    out["r_intraday"] = r_intra
    out["r_gap"] = r_gap
    out["r_cc"] = r_cc
    out = out.dropna().copy()

    # demean (so GJR-GARCH operates on approximate zero-mean residuals)
    out["r_intraday"] = out["r_intraday"] - out["r_intraday"].mean()
    out["r_gap"] = out["r_gap"] - out["r_gap"].mean()

    # squared terms and lags used as exog
    out["r_intraday2"] = out["r_intraday"] ** 2
    out["r_gap2"] = out["r_gap"] ** 2
    out["r_gap2_lag1"] = out["r_gap2"].shift(1)   # r_gap[t-1]²
    out["r_intra2_lag1"] = out["r_intraday2"].shift(1)

    out = out.dropna().copy()
    return out


# ======================================================================
# 2. GJR-GARCH(1,1) Student-t kernel
# ======================================================================
def _gjr_recursion(params: np.ndarray, r: np.ndarray,
                   exog: Optional[np.ndarray] = None,
                   exog_contemp: bool = True) -> Optional[np.ndarray]:
    """
    Return conditional variance h[t] under GJR-GARCH(1,1) with optional
    ONE-dimensional exog term.

    params: [theta0, alpha, gamma, beta] (+ [xi] if exog)
      h[t] = theta0 + alpha*r²[t-1] + gamma*r²[t-1]*I(r[t-1]<0) + beta*h[t-1]
             [+ xi * exog[t]        if exog_contemp=True]
             [+ xi * exog[t-1]      otherwise]
    """
    theta0 = params[0]
    alpha = params[1]
    gamma = params[2]
    beta = params[3]
    xi = params[4] if len(params) >= 5 else 0.0

    if (theta0 <= 0 or alpha < 0 or gamma < -alpha or beta < 0
            or alpha + 0.5 * gamma + beta >= 0.999):
        return None

    N = len(r)
    h = np.zeros(N)
    # init at unconditional var proxy
    uncond = float(np.mean(r * r))
    h[0] = max(uncond, 1e-10)

    for t in range(1, N):
        x2_lag = r[t - 1] * r[t - 1]
        neg_ind = 1.0 if r[t - 1] < 0 else 0.0
        h_t = theta0 + alpha * x2_lag + gamma * x2_lag * neg_ind + beta * h[t - 1]
        if exog is not None:
            ex = exog[t] if exog_contemp else exog[t - 1]
            if np.isfinite(ex):
                h_t += xi * ex
        if h_t <= 1e-12:
            return None
        h[t] = h_t
    return h


def gjr_nll_student(params: np.ndarray, r: np.ndarray,
                    exog: Optional[np.ndarray] = None,
                    exog_contemp: bool = True) -> float:
    df = params[-1]
    prg_params = params[:-1]
    h = _gjr_recursion(prg_params, r, exog, exog_contemp)
    if h is None:
        return 1e10
    if df <= 2.01:
        return 1e10

    N = len(r)
    valid = slice(1, N)
    h_v = h[valid]
    r_v = r[valid]

    log_const = (gammaln((df + 1.0) / 2.0) - gammaln(df / 2.0)
                 - 0.5 * np.log(np.pi * (df - 2.0)))
    log_pdf = (log_const - 0.5 * np.log(h_v)
               - (df + 1.0) / 2.0 * np.log1p(r_v ** 2 / (h_v * (df - 2.0))))
    nll = -float(np.sum(log_pdf))
    if not np.isfinite(nll):
        return 1e10
    return nll


def fit_gjr_student(r: np.ndarray,
                    exog: Optional[np.ndarray] = None,
                    exog_contemp: bool = True,
                    n_restarts: int = 8,
                    x0_warm: Optional[np.ndarray] = None) -> Dict:
    r = np.asarray(r, dtype=float)
    use_exog = exog is not None
    local_rng = np.random.default_rng(42)
    best = {"nll": np.inf, "params": None, "success": False}

    base_dim = 5 if use_exog else 4   # [theta0, alpha, gamma, beta, (xi)]
    dim = base_dim + 1  # + df

    uncond = float(np.var(r, ddof=1))

    for trial in range(n_restarts):
        if trial == 0 and x0_warm is not None and len(x0_warm) == dim:
            x0 = np.array(x0_warm, dtype=float).copy()
        elif trial == 0:
            x0 = np.array([uncond * 0.05, 0.05, 0.05, 0.85])
            if use_exog:
                x0 = np.concatenate([x0, [0.0]])
            x0 = np.concatenate([x0, [8.0]])
        else:
            x0 = np.array([
                uncond * (0.02 + 0.08 * local_rng.random()),
                0.02 + 0.06 * local_rng.random(),
                0.02 + 0.08 * local_rng.random(),
                0.75 + 0.15 * local_rng.random(),
            ])
            if use_exog:
                x0 = np.concatenate([x0, [0.5 * (local_rng.random() - 0.5)]])
            df0 = 4.0 + 8.0 * local_rng.random()
            x0 = np.concatenate([x0, [df0]])

        bounds = [
            (1e-10, None),   # theta0
            (0.0, 0.4),      # alpha
            (-0.4, 0.6),     # gamma
            (0.0, 0.9999),   # beta
        ]
        if use_exog:
            bounds.append((None, None))  # xi
        bounds.append((2.05, 200.0))  # df

        try:
            res = optimize.minimize(
                gjr_nll_student, x0, args=(r, exog, exog_contemp),
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


def gjr_variance_path_student(params: np.ndarray, r: np.ndarray,
                              exog: Optional[np.ndarray] = None,
                              exog_contemp: bool = True) -> np.ndarray:
    if params is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    prg_params = params[:-1]  # drop df
    h = _gjr_recursion(prg_params, r, exog, exog_contemp)
    if h is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    return h


# ======================================================================
# 3. Eval utilities
# ======================================================================
def qlike_loss(h_hat: np.ndarray, r2: np.ndarray) -> np.ndarray:
    eps = 1e-12
    ratio = r2 / np.maximum(h_hat, eps)
    return ratio - np.log(np.maximum(ratio, eps)) - 1.0


def dm_test_hln(loss1: np.ndarray, loss2: np.ndarray) -> Tuple[float, float]:
    """HLN-corrected DM. Positive t = loss1 > loss2 (i.e. model 2 better)."""
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


# ======================================================================
# 4. Experiment runner per market
# ======================================================================
def run_market(ticker: str, label: str, cache_name: str) -> Dict:
    t0 = time.time()
    print(f"\n=== {label} ({ticker}) ===")

    raw = load_market(ticker, cache_name)
    feat = build_features(raw)

    r_intra = feat["r_intraday"].values
    r_gap2 = feat["r_gap2"].values
    r_gap2_lag = feat["r_gap2_lag1"].values
    r_intra2_lag = feat["r_intra2_lag1"].values
    dates = feat.index

    N = len(feat)
    # Descriptive stats
    desc = {
        "N": int(N),
        "date_range": [str(dates[0].date()), str(dates[-1].date())],
        "r_intraday_stats": {
            "mean": float(np.mean(r_intra)),
            "std": float(np.std(r_intra, ddof=1)),
            "skew": float(skew_fn(r_intra)),
            "excess_kurt": float(kurt_fn(r_intra)),
        },
        "r_gap_stats": {
            "mean": float(np.mean(feat["r_gap"].values)),
            "std": float(np.std(feat["r_gap"].values, ddof=1)),
            "skew": float(skew_fn(feat["r_gap"].values)),
            "excess_kurt": float(kurt_fn(feat["r_gap"].values)),
        },
        "var_ratio_gap_over_intra": float(
            np.var(feat["r_gap"].values, ddof=1) / np.var(r_intra, ddof=1)
        ),
    }
    print(f"  N={N}, period={desc['date_range']}")
    print(f"  r_intraday: std={desc['r_intraday_stats']['std']:.4e} "
          f"skew={desc['r_intraday_stats']['skew']:.2f} "
          f"kurt={desc['r_intraday_stats']['excess_kurt']:.2f}")
    print(f"  r_gap:      std={desc['r_gap_stats']['std']:.4e} "
          f"skew={desc['r_gap_stats']['skew']:.2f} "
          f"kurt={desc['r_gap_stats']['excess_kurt']:.2f}")

    # ------------------------------------------------------------------
    # IS full-sample fit: M1 baseline, M2_gap, M2_gap_lag, M4_night
    # ------------------------------------------------------------------
    print("\n  IS full-sample fits (Student-t GJR-GARCH)...")
    is_fits = {}

    # Baseline
    fit_m1 = fit_gjr_student(r_intra, exog=None, n_restarts=8)
    ll_m1 = -fit_m1["nll"]
    is_fits["M1"] = {
        "log_lik": ll_m1,
        "params": fit_m1["params"].tolist() if fit_m1["params"] is not None else None,
        "success": fit_m1["success"],
    }
    print(f"    M1 baseline       : LL={ll_m1:.3f}  df={fit_m1['params'][-1]:.2f}")

    # M2_gap: r_gap²[t] contemp
    fit_m2 = fit_gjr_student(r_intra, exog=r_gap2, exog_contemp=True, n_restarts=8)
    ll_m2 = -fit_m2["nll"]
    lrt_m2 = 2 * (ll_m2 - ll_m1)
    is_fits["M2_gap"] = {
        "log_lik": ll_m2,
        "LRT_vs_M1": float(lrt_m2),
        "p_value": float(1 - chi2.cdf(lrt_m2, df=1)) if lrt_m2 > 0 else 1.0,
        "xi_coef": float(fit_m2["params"][4]) if fit_m2["params"] is not None else None,
        "params": fit_m2["params"].tolist() if fit_m2["params"] is not None else None,
        "success": fit_m2["success"],
    }
    print(f"    M2_gap (contemp)  : LL={ll_m2:.3f}  LRT={lrt_m2:.2f} "
          f"p={is_fits['M2_gap']['p_value']:.4e}  xi={is_fits['M2_gap']['xi_coef']:.4e}")

    # M2_gap_lag: r_gap²[t-1]
    fit_m2lag = fit_gjr_student(r_intra, exog=r_gap2_lag, exog_contemp=True, n_restarts=8)
    ll_m2lag = -fit_m2lag["nll"]
    lrt_m2lag = 2 * (ll_m2lag - ll_m1)
    is_fits["M2_gap_lag"] = {
        "log_lik": ll_m2lag,
        "LRT_vs_M1": float(lrt_m2lag),
        "p_value": float(1 - chi2.cdf(lrt_m2lag, df=1)) if lrt_m2lag > 0 else 1.0,
        "xi_coef": float(fit_m2lag["params"][4]) if fit_m2lag["params"] is not None else None,
        "params": fit_m2lag["params"].tolist() if fit_m2lag["params"] is not None else None,
        "success": fit_m2lag["success"],
    }
    print(f"    M2_gap_lag        : LL={ll_m2lag:.3f}  LRT={lrt_m2lag:.2f} "
          f"p={is_fits['M2_gap_lag']['p_value']:.4e}  xi={is_fits['M2_gap_lag']['xi_coef']:.4e}")

    # M4_night: r_intraday²[t-1] (yesterday's intraday) — pure control
    fit_m4 = fit_gjr_student(r_intra, exog=r_intra2_lag, exog_contemp=True, n_restarts=8)
    ll_m4 = -fit_m4["nll"]
    lrt_m4 = 2 * (ll_m4 - ll_m1)
    is_fits["M4_intra_lag"] = {
        "log_lik": ll_m4,
        "LRT_vs_M1": float(lrt_m4),
        "p_value": float(1 - chi2.cdf(lrt_m4, df=1)) if lrt_m4 > 0 else 1.0,
        "xi_coef": float(fit_m4["params"][4]) if fit_m4["params"] is not None else None,
        "params": fit_m4["params"].tolist() if fit_m4["params"] is not None else None,
        "success": fit_m4["success"],
    }
    print(f"    M4_intra_lag      : LL={ll_m4:.3f}  LRT={lrt_m4:.2f} "
          f"p={is_fits['M4_intra_lag']['p_value']:.4e}")

    # ------------------------------------------------------------------
    # OOS expanding-window forecasts
    # ------------------------------------------------------------------
    n_train_init = int(N * TRAIN_FRAC)
    print(f"\n  OOS expanding-window (refit every {REFIT_EVERY}, "
          f"init train={n_train_init}, test={N - n_train_init})...")

    def run_oos(exog_name: str, exog_arr: Optional[np.ndarray]) -> Dict:
        h_forecast = np.full(N, np.nan)
        warm = None
        last_fit_end = n_train_init
        # one-step-ahead forecasts for t in [n_train_init, N-1]
        # at each time t, use data r[0..t-1] (and exog[0..t] if contemp, bc exog[t] is known by design)
        for t in range(n_train_init, N):
            if (t - n_train_init) % REFIT_EVERY == 0 or warm is None:
                r_tr = r_intra[:t]
                ex_tr = exog_arr[:t] if exog_arr is not None else None
                fit = fit_gjr_student(r_tr, exog=ex_tr, n_restarts=3, x0_warm=warm)
                if fit["success"]:
                    warm = fit["params"].copy()
                else:
                    # keep previous warm if fit fails
                    pass
            # one-step-ahead h[t]: run recursion over r[0..t-1] and set h[t] using
            # last r[t-1], h[t-1], and exog[t] (if contemp) known at time t's open
            if warm is None:
                h_forecast[t] = float(np.var(r_intra[:t], ddof=1))
                continue
            prg_params = warm[:-1]  # drop df
            # build recursion through t
            r_slice = r_intra[:t + 1].copy()
            ex_slice = exog_arr[:t + 1] if exog_arr is not None else None
            h_path = _gjr_recursion(prg_params, r_slice, ex_slice, exog_contemp=True)
            if h_path is None:
                h_forecast[t] = float(np.var(r_intra[:t], ddof=1))
            else:
                h_forecast[t] = h_path[t]
        return {"h_forecast": h_forecast, "last_params": warm}

    # OOS runs
    oos_m1 = run_oos("M1", None)
    oos_m2 = run_oos("M2_gap", r_gap2)
    oos_m2lag = run_oos("M2_gap_lag", r_gap2_lag)
    oos_m4 = run_oos("M4_intra_lag", r_intra2_lag)

    test_slice = slice(n_train_init, N)
    r2_target = (r_intra[test_slice]) ** 2
    h_m1_oos = oos_m1["h_forecast"][test_slice]
    h_m2_oos = oos_m2["h_forecast"][test_slice]
    h_m2lag_oos = oos_m2lag["h_forecast"][test_slice]
    h_m4_oos = oos_m4["h_forecast"][test_slice]

    loss_m1 = qlike_loss(h_m1_oos, r2_target)
    loss_m2 = qlike_loss(h_m2_oos, r2_target)
    loss_m2lag = qlike_loss(h_m2lag_oos, r2_target)
    loss_m4 = qlike_loss(h_m4_oos, r2_target)

    # DM tests: each vs M1 baseline (positive t = model better than M1)
    dm_m2_t, dm_m2_p = dm_test_hln(loss_m1, loss_m2)
    dm_m2lag_t, dm_m2lag_p = dm_test_hln(loss_m1, loss_m2lag)
    dm_m4_t, dm_m4_p = dm_test_hln(loss_m1, loss_m4)

    # QLIKE improvement %
    def qlike_improve(loss_base, loss_alt):
        return float((np.mean(loss_base) - np.mean(loss_alt)) / np.mean(loss_base) * 100)

    oos_res = {
        "n_train_init": int(n_train_init),
        "n_test": int(N - n_train_init),
        "test_date_range": [str(dates[n_train_init].date()),
                             str(dates[-1].date())],
        "QLIKE_M1": float(np.mean(loss_m1)),
        "QLIKE_M2_gap": float(np.mean(loss_m2)),
        "QLIKE_M2_gap_lag": float(np.mean(loss_m2lag)),
        "QLIKE_M4_intra_lag": float(np.mean(loss_m4)),
        "DM_M2_gap": {"t_HLN": dm_m2_t, "p": dm_m2_p,
                       "QLIKE_improv_pct": qlike_improve(loss_m1, loss_m2),
                       "harvey_pass": bool(abs(dm_m2_t) > HARVEY_T)
                           if np.isfinite(dm_m2_t) else False},
        "DM_M2_gap_lag": {"t_HLN": dm_m2lag_t, "p": dm_m2lag_p,
                          "QLIKE_improv_pct": qlike_improve(loss_m1, loss_m2lag),
                          "harvey_pass": bool(abs(dm_m2lag_t) > HARVEY_T)
                              if np.isfinite(dm_m2lag_t) else False},
        "DM_M4_intra_lag": {"t_HLN": dm_m4_t, "p": dm_m4_p,
                            "QLIKE_improv_pct": qlike_improve(loss_m1, loss_m4),
                            "harvey_pass": bool(abs(dm_m4_t) > HARVEY_T)
                                if np.isfinite(dm_m4_t) else False},
    }
    print(f"    OOS QLIKE      M1={oos_res['QLIKE_M1']:.4f}  "
          f"M2_gap={oos_res['QLIKE_M2_gap']:.4f} "
          f"M2_lag={oos_res['QLIKE_M2_gap_lag']:.4f} "
          f"M4_lag={oos_res['QLIKE_M4_intra_lag']:.4f}")
    print(f"    DM M2_gap     : t={dm_m2_t:.2f}  p={dm_m2_p:.4f}  "
          f"QLIKE improv={oos_res['DM_M2_gap']['QLIKE_improv_pct']:.2f}%  "
          f"Harvey={oos_res['DM_M2_gap']['harvey_pass']}")
    print(f"    DM M2_gap_lag : t={dm_m2lag_t:.2f}  p={dm_m2lag_p:.4f}  "
          f"QLIKE improv={oos_res['DM_M2_gap_lag']['QLIKE_improv_pct']:.2f}%")
    print(f"    DM M4_intra_l : t={dm_m4_t:.2f}  p={dm_m4_p:.4f}  "
          f"QLIKE improv={oos_res['DM_M4_intra_lag']['QLIKE_improv_pct']:.2f}%")

    elapsed = time.time() - t0
    print(f"  elapsed: {elapsed:.1f}s")

    return {
        "ticker": ticker,
        "label": label,
        "desc": desc,
        "IS": is_fits,
        "OOS": oos_res,
        "elapsed_sec": float(elapsed),
    }


# ======================================================================
# 5. Verdict logic + plots
# ======================================================================
def make_verdict(results: Dict) -> Dict:
    """Decide H1/H2/H3 based on SPY and N225 DM t-stats for M2_gap."""
    markers = []
    for m in ["SPY", "N225"]:
        dm_t = results[m]["OOS"]["DM_M2_gap"]["t_HLN"]
        pass_harvey = abs(dm_t) > HARVEY_T if np.isfinite(dm_t) else False
        markers.append({"market": m, "dm_t": dm_t, "harvey_pass": pass_harvey})
    pass_count = sum(1 for m in markers if m["harvey_pass"])

    if pass_count == 2:
        verdict = "H1_UNIVERSAL"
        narrative = ("Both SPY and N225 pass Harvey threshold. "
                     "Overnight→day predictability is a universal property, "
                     "not TAIFEX-specific. Paper 3 reframe anchor ESTABLISHED.")
    elif pass_count == 0:
        verdict = "H2_TAIFEX_SPECIFIC"
        narrative = ("Neither SPY nor N225 passes Harvey threshold. "
                     "TAIFEX night→day signal is likely a market-specific "
                     "property of the Taiwan emerging-market / narrow-index "
                     "structure. Paper 3 reframe anchor FAILS cross-market.")
    else:
        which = [m["market"] for m in markers if m["harvey_pass"]]
        verdict = "H3_PARTIAL"
        narrative = (f"Only {which[0]} passes Harvey threshold. "
                     "Effect shows regional variation; Paper 3 reframe needs "
                     "caveats about market-structure heterogeneity.")
    return {
        "verdict": verdict,
        "narrative": narrative,
        "pass_count": pass_count,
        "per_market": markers,
    }


def make_plots(results: Dict, out_dir: Path):
    # Plot 1: DM t-stat bar chart (TAIFEX from K1100g_d5, SPY, N225)
    fig, ax = plt.subplots(figsize=(8, 5))
    markets = ["TAIFEX\n(K1100g_d5 REF\nnight_r2)", "SPY\n(M2_gap)", "N225\n(M2_gap)"]
    dm_ts = [
        2.01,  # TAIFEX REF_night_r2 DM from K1100g_d5 (night_r2 as exog)
        results["SPY"]["OOS"]["DM_M2_gap"]["t_HLN"],
        results["N225"]["OOS"]["DM_M2_gap"]["t_HLN"],
    ]
    colors = ["#888888",
              "#2ca02c" if abs(dm_ts[1]) > HARVEY_T else
              "#ff9800" if abs(dm_ts[1]) > 2.0 else "#d62728",
              "#2ca02c" if abs(dm_ts[2]) > HARVEY_T else
              "#ff9800" if abs(dm_ts[2]) > 2.0 else "#d62728"]
    bars = ax.bar(markets, dm_ts, color=colors, edgecolor="black")
    ax.axhline(HARVEY_T, color="red", linestyle="--", label=f"Harvey |t|={HARVEY_T}")
    ax.axhline(-HARVEY_T, color="red", linestyle="--")
    ax.axhline(2.0, color="orange", linestyle=":", label="|t|=2 (conventional)")
    ax.axhline(-2.0, color="orange", linestyle=":")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_ylabel("DM-HLN t-statistic (vs baseline)")
    ax.set_title("Cross-market overnight→day: DM t-stat comparison\n"
                  f"Verdict: {results['VERDICT']['verdict']}")
    for bar, v in zip(bars, dm_ts):
        ax.text(bar.get_x() + bar.get_width() / 2,
                 v + 0.08 * np.sign(v if v != 0 else 1),
                 f"{v:.2f}", ha="center",
                 va="bottom" if v >= 0 else "top", fontsize=10)
    ax.legend(loc="upper left", fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "k1100g_d7_cross_market_dm.png", dpi=120)
    plt.close(fig)

    # Plot 2: QLIKE improvement % comparison
    fig, ax = plt.subplots(figsize=(8, 5))
    markets = ["SPY", "N225"]
    improv_gap = [results[m]["OOS"]["DM_M2_gap"]["QLIKE_improv_pct"] for m in markets]
    improv_lag = [results[m]["OOS"]["DM_M2_gap_lag"]["QLIKE_improv_pct"] for m in markets]
    improv_intra = [results[m]["OOS"]["DM_M4_intra_lag"]["QLIKE_improv_pct"]
                     for m in markets]
    x = np.arange(len(markets))
    w = 0.25
    ax.bar(x - w, improv_gap, w, label="M2_gap (contemp gap²)",
            color="#1f77b4", edgecolor="black")
    ax.bar(x, improv_lag, w, label="M2_gap_lag (gap²[t-1])",
            color="#ff7f0e", edgecolor="black")
    ax.bar(x + w, improv_intra, w, label="M4_intra_lag (r²_intraday[t-1])",
            color="#2ca02c", edgecolor="black")
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set_xticks(x)
    ax.set_xticklabels(markets)
    ax.set_ylabel("OOS QLIKE improvement vs M1 baseline (%)")
    ax.set_title("Cross-market: OOS QLIKE improvement by exog specification")
    ax.legend(fontsize=9)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "k1100g_d7_qlike_improvement.png", dpi=120)
    plt.close(fig)


# ======================================================================
# 6. Main
# ======================================================================
def main():
    t_start = time.time()
    results = {
        "experiment_id": "k1100g_d7",
        "title": "Cross-market replication: SPY + N225 overnight gap²→intraday r²",
        "seed": 42,
        "config": {
            "start_date": START_DATE,
            "end_date": END_DATE,
            "refit_every": REFIT_EVERY,
            "train_frac": TRAIN_FRAC,
            "harvey_threshold": HARVEY_T,
        },
    }

    # Run each market
    results["SPY"] = run_market("SPY", "SPY (S&P 500 ETF)", "spy")
    results["N225"] = run_market("^N225", "Nikkei 225 Index", "n225")

    # Verdict
    results["VERDICT"] = make_verdict(results)
    print(f"\n\n*** VERDICT: {results['VERDICT']['verdict']} ***")
    print(results["VERDICT"]["narrative"])

    # Cross-market summary
    print("\n=== Cross-market summary ===")
    print(f"  TAIFEX (K1100g_d5 REF_night_r2):  DM t = +2.01 (HARVEY FAIL)")
    for m in ["SPY", "N225"]:
        dm = results[m]["OOS"]["DM_M2_gap"]
        passed = "HARVEY PASS" if dm["harvey_pass"] else "HARVEY FAIL"
        print(f"  {m}: DM t = {dm['t_HLN']:+.2f}  QLIKE improv = "
               f"{dm['QLIKE_improv_pct']:+.2f}%  [{passed}]")

    # Plots
    print("\nGenerating plots...")
    make_plots(results, SCRIPT_DIR)

    # Save
    results["total_elapsed_sec"] = float(time.time() - t_start)
    with open(RESULTS_PATH, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nResults saved to {RESULTS_PATH}")
    print(f"Total elapsed: {results['total_elapsed_sec']:.1f}s")


if __name__ == "__main__":
    main()
