"""
K1100h — TAIFEX tick-derived intraday-feature PRG (Phase 1)
============================================================

Phase 0 plan: experiments/k1100h/README.md (2026-04-18)
Parent      : K1100g_d5/d6 daily PRG with gap²; DM borderline (+1.49 / +1.x)
Hypothesis  : Daily-aggregation平均化掉 intraday 結構; tick → 5-min RV / Parkinson /
              intraday momentum / first-half-day RV ratio 應提升 daily PRG OOS。
Key tests   :
  M1 baseline      : Student-t PRG (no exog)            ← K1100g_d6 daily baseline
  M2 + RV-5min     : add lag(1) day_rv_5min as exog     ← Andersen-Bollerslev (1998)
  M3 + RV+Parkinson: M2 + lag(1) Parkinson hi-lo RV     ← Parkinson (1980) range
  M4 + intraday    : M3 + lag(1) intraday_mom + lag(1) hod_rv_ratio + lag(1) bipower
                     ← Barndorff-Nielsen Shephard (2004) jump-robust + early-info

Lookahead discipline (HARD)
---------------------------
1. The PRG kernel ALWAYS reads `exog_mat[t - 1, :]` internally (multi-exog kernel
   forces lag-1 — see _prg_variance_recursion_multi line ~144). This is equivalent
   to K1100g_d5's `exog_contemp=False` mode.
2. Therefore exog series passed to the kernel MUST be raw (un-shifted) day t
   features. Kernel reads index t-1 → effective predictive lag = 1 day:
   "use day session t-1 features to forecast r_day[t]^2 at 08:45 day t".
3. DO NOT pre-shift exog before passing to fit_prg_student / expanding_oos.
   Pre-shift would make effective lag = 2 days and BREAK comparability with
   K1100g_d5/d6 baselines.
4. Baseline (M1) uses NO exog, but identical r_day series and dow_dummies.
5. seed=42 fixed; n_restarts=8 IS / 4 OOS (matches K1100g_d5).
6. r_day target = log(day_close / day_open) (matches K1100g intraday_ret column).

Eval
----
- IS  : LRT vs M1, dof = number of added exog
- OOS : expanding-window refit every 5 trading days, train 2017-05-16 → 2019-12-31,
        test 2020-01-01 → 2021-12-31
- DM  : HLN-corrected (Harvey 1997), QLIKE loss on r_day²
- Harvey 2016 |t| > 3.0 main threshold; |t| > 1.96 secondary

Author: Claude (K1100h Phase 1)
Date: 2026-05-09
Seed: 42
"""
from __future__ import annotations

import json
import time
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import optimize
from scipy.special import gammaln
from scipy.stats import chi2, norm

warnings.filterwarnings("ignore")
np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
RESULTS_PATH = SCRIPT_DIR / "k1100h_results.json"
DAILY_CACHE = DATA_DIR / "_taifex_daily_features_2017-2021.parquet"
K1100G_CACHE = (
    SCRIPT_DIR.parent / "k1100g" / "_cache_taifex_2017-01-01_2021-12-31.parquet"
)

TRAIN_START = pd.Timestamp("2017-05-16")
TRAIN_END = pd.Timestamp("2019-12-31")
TEST_START = pd.Timestamp("2020-01-01")
TEST_END = pd.Timestamp("2021-12-31")
REFIT_EVERY = 5
SEED = 42


# ----------------------------------------------------------------------
# 1. PRG kernel — Student-t, multi-exog generalization of K1100g_d5
# ----------------------------------------------------------------------
def make_dow_dummies(dow: np.ndarray) -> np.ndarray:
    N = len(dow)
    X = np.zeros((N, 4), dtype=float)
    for k, d in enumerate((1, 2, 3, 4)):
        X[:, k] = (dow == d).astype(float)
    return X


def _prg_variance_recursion_multi(
    params: np.ndarray,
    r: np.ndarray,
    dow_dum: np.ndarray,
    exog_mat: Optional[np.ndarray] = None,
) -> Optional[np.ndarray]:
    """PRG recursion supporting multi-column exog matrix (each col gets own coef).

    params layout:
      [theta0, theta1, d1, d2, d3, d4, alpha, gamma, beta,
       xn_1, ..., xn_K]   where K = exog_mat.shape[1] (0 if None)

    Always uses exog at t-1 (lag-1) — matches K1100g_d5 'exog_contemp=False'.
    """
    base = 9
    theta0, theta1, d1, d2, d3, d4, alpha, gamma, beta = params[:base]
    if exog_mat is not None:
        K = exog_mat.shape[1]
        xn = params[base : base + K]
    else:
        K = 0
        xn = np.array([])

    if (
        theta0 <= 0
        or theta1 < 0
        or alpha < 0
        or gamma < 0
        or beta < 0
        or alpha + 0.5 * gamma + beta >= 0.999
    ):
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
        dow_term = (
            d1 * dow_dum[t, 0]
            + d2 * dow_dum[t, 1]
            + d3 * dow_dum[t, 2]
            + d4 * dow_dum[t, 3]
        )
        if K > 0:
            exog_term = float(np.dot(xn, exog_mat[t - 1, :]))
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


def prg_nll_student(
    params: np.ndarray,
    r: np.ndarray,
    dow_dum: np.ndarray,
    exog_mat: Optional[np.ndarray] = None,
) -> float:
    df = params[-1]
    prg_params = params[:-1]
    h = _prg_variance_recursion_multi(prg_params, r, dow_dum, exog_mat)
    if h is None:
        return 1e10
    if df <= 2.01:
        return 1e10

    N = len(r)
    valid = slice(1, N)
    h_v = h[valid]
    r_v = r[valid]
    if np.any(h_v <= 0):
        return 1e10

    log_const = (
        gammaln((df + 1.0) / 2.0)
        - gammaln(df / 2.0)
        - 0.5 * np.log(np.pi * (df - 2.0))
    )
    log_pdf = (
        log_const
        - 0.5 * np.log(h_v)
        - (df + 1.0) / 2.0 * np.log1p(r_v ** 2 / (h_v * (df - 2.0)))
    )
    nll = -float(np.sum(log_pdf))
    if not np.isfinite(nll):
        return 1e10
    return nll


def fit_prg_student(
    r: np.ndarray,
    dow_dum: np.ndarray,
    exog_mat: Optional[np.ndarray] = None,
    n_restarts: int = 8,
    x0_warm: Optional[np.ndarray] = None,
) -> Dict:
    r = np.asarray(r, dtype=float)
    K = 0 if exog_mat is None else int(exog_mat.shape[1])
    local_rng = np.random.default_rng(SEED)
    best = {"nll": np.inf, "params": None, "success": False}

    prg_base_dim = 9 + K
    dim = prg_base_dim + 1  # +df

    for trial in range(n_restarts):
        uncond = float(np.var(r, ddof=1))
        if trial == 0 and x0_warm is not None and len(x0_warm) == dim:
            x0 = np.array(x0_warm, dtype=float).copy()
        elif trial == 0:
            x0 = np.array(
                [uncond * 0.5, 0.05, 0.0, 0.0, 0.0, 0.0, 0.05, 0.05, 0.80]
            )
            if K > 0:
                x0 = np.concatenate([x0, np.zeros(K)])
            x0 = np.concatenate([x0, [8.0]])
        else:
            x0 = np.array(
                [
                    uncond * (0.3 + 0.4 * local_rng.random()),
                    0.02 + 0.06 * local_rng.random(),
                    uncond * 0.01 * (local_rng.random() - 0.5),
                    uncond * 0.01 * (local_rng.random() - 0.5),
                    uncond * 0.01 * (local_rng.random() - 0.5),
                    uncond * 0.01 * (local_rng.random() - 0.5),
                    0.02 + 0.08 * local_rng.random(),
                    0.02 + 0.08 * local_rng.random(),
                    0.70 + 0.20 * local_rng.random(),
                ]
            )
            if K > 0:
                x0 = np.concatenate(
                    [x0, 0.3 * (local_rng.random(K) - 0.5)]
                )
            df0 = 4.0 + 8.0 * local_rng.random()
            x0 = np.concatenate([x0, [df0]])

        bounds = [
            (1e-8, None),
            (0.0, 1.0),
            (None, None),
            (None, None),
            (None, None),
            (None, None),
            (0.0, 0.4),
            (0.0, 0.4),
            (0.0, 0.9999),
        ]
        if K > 0:
            for _ in range(K):
                bounds.append((None, None))
        bounds.append((2.05, 200.0))

        try:
            res = optimize.minimize(
                prg_nll_student,
                x0,
                args=(r, dow_dum, exog_mat),
                method="L-BFGS-B",
                bounds=bounds,
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


def prg_variance_path(
    params: np.ndarray,
    r: np.ndarray,
    dow_dum: np.ndarray,
    exog_mat: Optional[np.ndarray] = None,
) -> np.ndarray:
    if params is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    prg_params = params[:-1]
    h = _prg_variance_recursion_multi(prg_params, r, dow_dum, exog_mat)
    if h is None:
        return np.full(len(r), float(np.var(r, ddof=1)))
    return h


# ----------------------------------------------------------------------
# 2. Eval utilities
# ----------------------------------------------------------------------
def qlike_loss(h_hat: np.ndarray, r2: np.ndarray) -> np.ndarray:
    eps = 1e-10
    ratio = r2 / np.maximum(h_hat, eps)
    return ratio - np.log(np.maximum(ratio, eps)) - 1.0


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
        gk = float(np.mean(dev[k:] * dev[:-k]))
        w = 1.0 - k / (lag + 1)
        s += 2 * w * gk
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


def lrt_chi2_test(
    ll_restricted: float, ll_full: float, dof: int = 1
) -> Tuple[float, float]:
    if ll_restricted is None or ll_full is None:
        return np.nan, np.nan
    lr = 2.0 * (ll_full - ll_restricted)
    if lr < 0:
        lr = 0.0
    p = 1.0 - chi2.cdf(lr, df=dof)
    return float(lr), float(p)


def block_bootstrap_dm(
    loss1: np.ndarray,
    loss2: np.ndarray,
    block_size: int = 22,
    n_boot: int = 1000,
    seed: int = 42,
) -> Tuple[float, float]:
    """Block bootstrap CI for DM stat (block=22 ~ 1 month)."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    if len(d) < block_size * 5:
        return np.nan, np.nan
    n = len(d)
    rng = np.random.default_rng(seed)
    n_blocks = n // block_size + 1

    boot_means = np.zeros(n_boot)
    for b in range(n_boot):
        starts = rng.integers(0, n - block_size + 1, size=n_blocks)
        sample = np.concatenate([d[s : s + block_size] for s in starts])[:n]
        boot_means[b] = float(np.mean(sample))
    return float(np.percentile(boot_means, 2.5)), float(
        np.percentile(boot_means, 97.5)
    )


# ----------------------------------------------------------------------
# 3. Expanding-window OOS
# ----------------------------------------------------------------------
def expanding_oos(
    r: np.ndarray,
    dow_dum: np.ndarray,
    exog_mat: Optional[np.ndarray],
    test_start_idx: int,
    label: str = "",
    refit_every: int = REFIT_EVERY,
) -> Dict:
    N = len(r)
    h_oos = np.full(N, np.nan)
    df_log = np.full(N, np.nan)
    params_log: List[Tuple[int, List[float]]] = []
    current_params: Optional[np.ndarray] = None

    for t in range(test_start_idx, N):
        steps = t - test_start_idx
        need_refit = steps % refit_every == 0
        if need_refit:
            r_train = r[:t]
            dow_train = dow_dum[:t]
            exog_train = exog_mat[:t] if exog_mat is not None else None
            fit = fit_prg_student(
                r_train, dow_train, exog_mat=exog_train,
                n_restarts=4, x0_warm=current_params,
            )
            if not fit["success"]:
                fit = fit_prg_student(
                    r_train, dow_train, exog_mat=exog_train,
                    n_restarts=6, x0_warm=None,
                )
            if fit["success"]:
                current_params = fit["params"]
                params_log.append((int(t), current_params.tolist()))
            else:
                print(f"  [warn {label}] refit failed at t={t}")

        if current_params is None:
            continue

        df_t = float(current_params[-1])
        df_log[t] = df_t
        r_slice = r[: t + 1]
        dow_slice = dow_dum[: t + 1]
        exog_slice = exog_mat[: t + 1] if exog_mat is not None else None
        h_path = prg_variance_path(current_params, r_slice, dow_slice, exog_slice)
        h_oos[t] = h_path[t]

    return {
        "h_oos": h_oos,
        "df_log": df_log,
        "params_log": params_log,
        "n_refits": len(params_log),
    }


# ----------------------------------------------------------------------
# 4. Main
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


def run():
    t0 = time.time()
    print(f"[{time.strftime('%H:%M:%S')}] Loading caches ...")
    if not DAILY_CACHE.exists():
        raise FileNotFoundError(
            f"Missing daily cache {DAILY_CACHE}. "
            f"Run k1100h_load_taifex.py first."
        )
    feats = pd.read_parquet(DAILY_CACHE)
    feats["date"] = pd.to_datetime(feats["date"])

    if not K1100G_CACHE.exists():
        raise FileNotFoundError(f"Missing K1100g cache {K1100G_CACHE}")
    k1100g = pd.read_parquet(K1100G_CACHE)
    k1100g["date"] = pd.to_datetime(k1100g["date"])

    # Merge: use K1100g dow + intraday_ret as r_day baseline (tick-derived
    # intraday_mom should match K1100g intraday_ret but use cache version
    # for direct comparability with K1100g_d5/d6 baselines).
    df = pd.merge(
        feats, k1100g[["date", "intraday_ret", "dow", "is_roll"]],
        on="date", how="inner"
    )
    df = df.sort_values("date").reset_index(drop=True)

    # Filter: drop roll days (K1100g_d5 convention) + drop rows missing features
    pre_filter = len(df)
    df = df.dropna(subset=[
        "intraday_ret", "day_rv_5min", "day_rv_parkinson",
        "day_intraday_mom", "day_hod_rv_ratio", "day_bipower_var", "dow",
    ])
    df = df[df["is_roll"] == False].copy()  # K1100g_d5 convention
    df = df.reset_index(drop=True)
    print(f"  Pre-filter rows={pre_filter}  Post-filter rows={len(df)}")

    dates_ts = pd.to_datetime(df["date"])
    dow_arr = df["dow"].values.astype(int)
    dow_dum = make_dow_dummies(dow_arr)

    r_day = df["intraday_ret"].values.astype(float)

    # === EXOG construction — DO NOT pre-shift ===
    # The multi-exog kernel ALWAYS reads exog_mat[t-1, :] internally (line 144).
    # Therefore we pass features indexed by TODAY's date (no .shift here).
    # Kernel reads index t-1 → effective predictive lag = 1 day.
    # 預測 r_day[t]² 用 day session t-1 features (legal info set at 08:45 day t).
    # Pre-shifting here would compound to lag-2 and break parity with K1100g_d5.
    rv5 = df["day_rv_5min"].values.astype(float)
    rvp = df["day_rv_parkinson"].values.astype(float)
    mom = df["day_intraday_mom"].values.astype(float)
    hodr = df["day_hod_rv_ratio"].values.astype(float)
    bipv = df["day_bipower_var"].values.astype(float)

    # Standardize exog (zero-mean unit-var) on TRAINING window only — preserve
    # exog scale stability across refits, no train-test contamination.
    train_mask = (dates_ts >= TRAIN_START) & (dates_ts <= TRAIN_END)
    test_mask = (dates_ts >= TEST_START) & (dates_ts <= TEST_END)

    def standardize(x: np.ndarray, train_idx: np.ndarray) -> np.ndarray:
        mu = float(np.mean(x[train_idx]))
        sd = float(np.std(x[train_idx], ddof=1))
        sd = sd if sd > 1e-10 else 1.0
        return (x - mu) / sd

    train_idx = np.where(train_mask)[0]
    rv5_z = standardize(rv5, train_idx)
    rvp_z = standardize(rvp, train_idx)
    mom_z = standardize(mom, train_idx)
    hodr_z = standardize(hodr, train_idx)
    bipv_z = standardize(bipv, train_idx)

    # === MODEL specs (exog matrix; all use kernel's lag-1 indexing) ===
    specs = [
        ("M1_baseline", None),
        ("M2_rv5min", np.column_stack([rv5_z])),
        ("M3_rv5_park", np.column_stack([rv5_z, rvp_z])),
        (
            "M4_full_intraday",
            np.column_stack([rv5_z, rvp_z, mom_z, hodr_z, bipv_z]),
        ),
    ]

    # ------------------------------------------------------------------
    # A) IS full-sample fits
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === IS fits ===")
    is_fits: Dict[str, Dict] = {}
    for name, exog_mat in specs:
        print(f"  [{time.strftime('%H:%M:%S')}] {name} (K={0 if exog_mat is None else exog_mat.shape[1]}) ...")
        fit = fit_prg_student(r_day, dow_dum, exog_mat=exog_mat, n_restarts=8)
        nll = fit["nll"]
        ll = -nll if np.isfinite(nll) else None
        K = 0 if exog_mat is None else exog_mat.shape[1]
        k_eff = 9 + K + 1
        aic = (2 * k_eff + 2 * nll) if np.isfinite(nll) else None
        bic = (k_eff * np.log(len(r_day) - 1) + 2 * nll) if np.isfinite(nll) else None
        df_est = float(fit["params"][-1]) if fit["params"] is not None else None
        xn_coefs = None
        if fit["params"] is not None and K > 0:
            xn_coefs = [float(c) for c in fit["params"][9 : 9 + K]]
        is_fits[name] = {
            "success": bool(fit["success"]),
            "nll": float(nll) if np.isfinite(nll) else None,
            "log_lik": ll,
            "aic": aic,
            "bic": bic,
            "k_params": k_eff,
            "df_est": df_est,
            "xn_coefs": xn_coefs,
            "params": fit["params"].tolist() if fit["params"] is not None else None,
        }
        ll_str = f"{ll:.3f}" if ll is not None else "NA"
        df_str = f" df={df_est:.2f}" if df_est is not None else ""
        xn_str = f" xn={[round(c, 4) for c in xn_coefs]}" if xn_coefs else ""
        print(f"    ll={ll_str}{df_str}{xn_str}  success={fit['success']}")

    # ------------------------------------------------------------------
    # B) IS LRT
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === IS LRT (vs M1_baseline) ===")
    ll_base = is_fits["M1_baseline"]["log_lik"]
    is_lrt: Dict[str, Dict] = {}
    for name in ["M2_rv5min", "M3_rv5_park", "M4_full_intraday"]:
        ll_f = is_fits[name]["log_lik"]
        K_added = {"M2_rv5min": 1, "M3_rv5_park": 2, "M4_full_intraday": 5}[name]
        stat, pval = lrt_chi2_test(ll_base, ll_f, dof=K_added)
        is_lrt[name] = {"chi2": stat, "p_value": pval, "dof": K_added}
        print(f"  {name} vs M1: chi2={stat:.3f}  p={pval:.4g}  dof={K_added}")

    # ------------------------------------------------------------------
    # C) OOS expanding-window
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === OOS expanding-window ===")
    test_idx_arr = np.where(test_mask)[0]
    test_start_idx = int(test_idx_arr[0])
    test_end_idx = int(test_idx_arr[-1])
    print(f"  Train: n={len(train_idx)}  Test: n={len(test_idx_arr)}")

    oos_runs: Dict[str, Dict] = {}
    for name, exog_mat in specs:
        t_oos = time.time()
        print(f"[{time.strftime('%H:%M:%S')}] OOS {name} ...")
        res = expanding_oos(
            r_day, dow_dum, exog_mat, test_start_idx, label=name,
            refit_every=REFIT_EVERY,
        )
        print(f"  refits={res['n_refits']}  elapsed={time.time() - t_oos:.1f}s")
        oos_runs[name] = res

    # ------------------------------------------------------------------
    # D) OOS metrics
    # ------------------------------------------------------------------
    test_slice = slice(test_start_idx, test_end_idx + 1)
    r_test = r_day[test_slice]
    r2_test = r_test ** 2
    dates_test = dates_ts.iloc[test_slice].values

    base_h = oos_runs["M1_baseline"]["h_oos"][test_slice]
    base_valid = np.isfinite(base_h)

    oos_metrics: Dict[str, Dict] = {}
    for name in ["M1_baseline", "M2_rv5min", "M3_rv5_park", "M4_full_intraday"]:
        h_test = oos_runs[name]["h_oos"][test_slice]
        valid = np.isfinite(h_test) & base_valid
        n_v = int(valid.sum())
        h_v = h_test[valid]
        h_b = base_h[valid]
        r2_v = r2_test[valid]

        q_test = qlike_loss(h_v, r2_v)
        q_base = qlike_loss(h_b, r2_v)

        qlike_mean_test = float(np.mean(q_test))
        qlike_mean_base = float(np.mean(q_base))
        qlike_improv = (
            (qlike_mean_base - qlike_mean_test) / qlike_mean_base
            if qlike_mean_base > 0 else np.nan
        )
        # DM
        dm_t, dm_p = dm_test_hln(q_base, q_test)
        # Block bootstrap CI on (loss_base - loss_test) mean
        ci_lo, ci_hi = block_bootstrap_dm(q_base, q_test, block_size=22, n_boot=1000, seed=42)

        oos_metrics[name] = {
            "n_valid": n_v,
            "qlike_mean": qlike_mean_test,
            "qlike_improv_vs_base": float(qlike_improv) if np.isfinite(qlike_improv) else None,
            "dm_t": dm_t,
            "dm_p": dm_p,
            "boot_diff_ci_lo": ci_lo,
            "boot_diff_ci_hi": ci_hi,
            "harvey_pass": bool(np.isfinite(dm_t) and abs(dm_t) > 3.0),
            "secondary_pass": bool(np.isfinite(dm_t) and abs(dm_t) > 1.96),
        }
        print(
            f"  {name}: QLIKE={qlike_mean_test:.4f}  "
            f"improv={qlike_improv*100 if np.isfinite(qlike_improv) else 0:.2f}%  "
            f"DM-t={dm_t:.3f}  p={dm_p:.4g}  "
            f"boot95%CI=[{ci_lo:.4e}, {ci_hi:.4e}]"
        )

    # ------------------------------------------------------------------
    # E) Plots
    # ------------------------------------------------------------------
    print(f"\n[{time.strftime('%H:%M:%S')}] === Plots ===")

    # Plot 1: DM t-stat bar
    fig, ax = plt.subplots(figsize=(8, 5))
    names = ["M2_rv5min", "M3_rv5_park", "M4_full_intraday"]
    dms = [oos_metrics[n]["dm_t"] for n in names]
    colors = ["#4575b4" if d > 0 else "#d73027" for d in dms]
    bars = ax.bar(names, dms, color=colors, edgecolor="black")
    ax.axhline(3.0, color="green", ls="--", lw=1.5, label="Harvey 2016 |t|>3")
    ax.axhline(1.96, color="orange", ls="--", lw=1.0, label="2-sided 5% |t|>1.96")
    ax.axhline(0, color="black", lw=0.5)
    ax.set_ylabel("DM-HLN t-stat (vs M1 baseline)")
    ax.set_title("K1100h — TAIFEX intraday-feature PRG OOS DM (2020-2021)")
    for b, d in zip(bars, dms):
        ax.text(b.get_x() + b.get_width() / 2, d, f"{d:.2f}",
                ha="center", va="bottom" if d >= 0 else "top", fontsize=10)
    ax.legend()
    fig.tight_layout()
    fig.savefig(SCRIPT_DIR / "k1100h_dm_bar.png", dpi=120)
    plt.close(fig)

    # Plot 2: QLIKE timeseries (M1 vs M4)
    fig, ax = plt.subplots(figsize=(11, 5))
    h_m1 = oos_runs["M1_baseline"]["h_oos"][test_slice]
    h_m4 = oos_runs["M4_full_intraday"]["h_oos"][test_slice]
    valid_both = np.isfinite(h_m1) & np.isfinite(h_m4)
    q_m1 = qlike_loss(h_m1[valid_both], r2_test[valid_both])
    q_m4 = qlike_loss(h_m4[valid_both], r2_test[valid_both])
    d_v = pd.to_datetime(dates_test[valid_both])
    ax.plot(d_v, np.cumsum(q_m1 - q_m4), color="#1f77b4", lw=1.5,
            label="cum (QLIKE_M1 - QLIKE_M4)  >0 = M4 better")
    ax.axhline(0, color="black", lw=0.5)
    ax.set_ylabel("Cumulative QLIKE difference")
    ax.set_xlabel("Date (test window)")
    ax.set_title("K1100h — Cumulative loss differential M1 baseline vs M4 full intraday")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(SCRIPT_DIR / "k1100h_qlike_cumdiff.png", dpi=120)
    plt.close(fig)

    # Plot 3: IS LRT chi² bar
    fig, ax = plt.subplots(figsize=(8, 5))
    lrt_names = ["M2_rv5min", "M3_rv5_park", "M4_full_intraday"]
    lrt_vals = [is_lrt[n]["chi2"] for n in lrt_names]
    lrt_dofs = [is_lrt[n]["dof"] for n in lrt_names]
    crit95 = [chi2.ppf(0.95, d) for d in lrt_dofs]
    bars = ax.bar(lrt_names, lrt_vals, color="#5aae61", edgecolor="black")
    for i, (b, v, c) in enumerate(zip(bars, lrt_vals, crit95)):
        ax.plot([b.get_x(), b.get_x() + b.get_width()], [c, c],
                color="red", ls="--", lw=1.2, label="chi² 95% crit" if i == 0 else "")
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.1f}",
                ha="center", va="bottom", fontsize=10)
    ax.set_ylabel("IS LRT chi²")
    ax.set_title("K1100h — IS LRT vs M1 baseline (red dashes = chi² dof 95% crit)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(SCRIPT_DIR / "k1100h_is_lrt_bar.png", dpi=120)
    plt.close(fig)

    # ------------------------------------------------------------------
    # F) Sanity checks
    # ------------------------------------------------------------------
    sanity = {
        "r_day_mean": float(np.mean(r_day)),
        "r_day_std": float(np.std(r_day)),
        "r_day_kurt_excess": float(pd.Series(r_day).kurt()),
        "n_total": int(len(r_day)),
        "n_train": int(len(train_idx)),
        "n_test": int(len(test_idx_arr)),
        "test_start": str(TEST_START.date()),
        "test_end": str(TEST_END.date()),
        "exog_means_pre_z_train": {
            "rv5min": float(np.mean(rv5[train_idx])),
            "rv_parkinson": float(np.mean(rvp[train_idx])),
            "intraday_mom": float(np.mean(mom[train_idx])),
            "hod_rv_ratio": float(np.mean(hodr[train_idx])),
            "bipower_var": float(np.mean(bipv[train_idx])),
        },
    }

    # ------------------------------------------------------------------
    # G) Verdict
    # ------------------------------------------------------------------
    best_name = max(
        ["M2_rv5min", "M3_rv5_park", "M4_full_intraday"],
        key=lambda n: oos_metrics[n]["dm_t"] if np.isfinite(oos_metrics[n]["dm_t"]) else -np.inf,
    )
    best_dm = oos_metrics[best_name]["dm_t"]
    if np.isfinite(best_dm) and abs(best_dm) > 3.0:
        verdict = "PASS — tick-derived intraday features beat daily PRG (Harvey)"
    elif np.isfinite(best_dm) and abs(best_dm) > 1.96:
        verdict = "BORDERLINE — secondary 5% but fail Harvey |t|>3"
    else:
        verdict = "NULL — tick-derived features no DM improvement at daily horizon"

    # ------------------------------------------------------------------
    # H) Write results JSON
    # ------------------------------------------------------------------
    elapsed = time.time() - t0
    out = {
        "experiment_id": "K1100h",
        "phase": "Phase 1 (daily PRG with tick-derived intraday exog)",
        "date_run": time.strftime("%Y-%m-%d %H:%M:%S"),
        "elapsed_sec": elapsed,
        "seed": SEED,
        "data": {
            "train_window": [str(TRAIN_START.date()), str(TRAIN_END.date())],
            "test_window": [str(TEST_START.date()), str(TEST_END.date())],
            "n_total": sanity["n_total"],
            "n_train": sanity["n_train"],
            "n_test": sanity["n_test"],
        },
        "models": {n: {"description": d} for n, d in [
            ("M1_baseline", "Student-t PRG, no exog"),
            ("M2_rv5min", "M1 + lag(1) day_rv_5min"),
            ("M3_rv5_park", "M1 + lag(1) day_rv_5min + lag(1) day_rv_parkinson"),
            ("M4_full_intraday", "M1 + lag(1) [rv_5min, rv_parkinson, intraday_mom, hod_rv_ratio, bipower_var]"),
        ]},
        "is_fits": is_fits,
        "is_lrt": is_lrt,
        "oos_metrics": oos_metrics,
        "sanity": sanity,
        "best_dm_model": best_name,
        "best_dm_t": best_dm,
        "verdict": verdict,
        "harvey_threshold": 3.0,
        "lookahead_check": {
            "exog_lag_in_kernel": "exog[t-1] always (multi-exog kernel forces lag-1)",
            "r_day_target": "intraday_ret = log(day_close/day_open) at day t",
            "info_set": "exog at t-1 = day session t-1 features, all realized "
                        "before day t opens at 08:45 — legal predictive lag",
            "baseline_uses_same_lag": True,
            "is_roll_filtered": True,
        },
        "references": [
            "Andersen & Bollerslev (1998) IER — realized volatility",
            "Parkinson (1980) JBus — high-low range estimator",
            "Barndorff-Nielsen & Shephard (2004) JFEC — bipower variation",
            "Engle & Rangel (2008) RFS — PRG tau*g",
            "Bollerslev (1987) RESTAT — Student-t GARCH",
            "Harvey, Leybourne & Newbold (1997) IJF — HLN DM correction",
            "Harvey (2016) JF — |t|>3 threshold",
        ],
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(clean_for_json(out), f, indent=2, ensure_ascii=False)
    print(f"\n[{time.strftime('%H:%M:%S')}] Done. elapsed={elapsed:.1f}s")
    print(f"  Verdict: {verdict}")
    print(f"  Best DM model: {best_name}  t={best_dm:.3f}")
    print(f"  Results: {RESULTS_PATH}")


if __name__ == "__main__":
    run()
