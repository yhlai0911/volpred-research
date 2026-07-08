"""
K1662 — Score-driven (GAS / DCS) dynamic-parameter models for direct VaR + ES.

Research question
-----------------
The platform has extensive GAS-t work (K437, K1038, K1129, K1134, K1138, K1143),
but ALL of it evaluated the *point volatility forecast* via QLIKE/DM and found
score-driven dynamics NULL (or actively harmful) for equity sigma^2 forecasting.

K1662 asks an ORTHOGONAL question that the QLIKE line never tested formally:
    Are score-driven models WELL-CALIBRATED for tail risk (VaR + ES)?
K1038 already hinted at this (GAS-t SPY VaR violation 1.70% vs GJR 2.02%) and
K1129 H4 ("VaR violation M3<M1 confirmed; 分配假設準 != vol predict 好"). Here we
run FORMAL VaR + ES backtests and joint FZ0 model comparison, framed honestly:
"does score-driven enter the MCS / is it well-calibrated?", NOT "does it win".

Design — 2x2 fair matrix + naive baseline
------------------------------------------
  Symmetric   : GAS-t   (score-driven, log-var, inverse-Fisher; Creal-Koopman-Lucas 2013)
                    vs GARCH(1,1)-t
  Asymmetric  : DCS-t   (Beta-t-EGARCH with leverage; Harvey 2013)
                    vs GJR-GARCH-t
  Naive       : EWMA / RiskMetrics (lambda=0.94, Normal)

All GARCH-family and score-driven models use the SAME standardized Student-t
innovation and the SAME sigma -> VaR -> ES analytic pipeline, so any calibration
difference is attributable to the *dynamics* (score-driven vs GARCH recursion),
not to the distribution. EWMA-Normal isolates the cost of the Normal assumption.

Method hard rules (per .claude/rules/experiments.md + K802/K445/K783c)
----------------------------------------------------------------------
  * Lookahead: sigma_t uses returns up to t-1 only (one-step-ahead recursion);
    params refit on data strictly before the forecast origin. Same lag for all.
  * seed = 42 everywhere (MC null, bootstrap, MCS bootstrap).
  * Student-t VaR/ES use UNIT-VARIANCE scaling sqrt((nu-2)/nu) (K802). No raw t.ppf.
  * Basel: we report an EXACT-BINOMIAL traffic light at the realized sample size
    (via volpred.stats.model_evaluation.var_backtest) and label it as such — NOT
    the canonical 250-day count table (K802 lesson: custom != canonical Basel).
  * VaR backtest: Kupiec POF + Christoffersen (canonical var_backtest()).
  * ES backtest: Acerbi-Szekely (2014) Z2 with Monte-Carlo null p-value +
    McNeil-Frey (2000) exceedance-residual bootstrap. Two tails: 1% and 5%.
  * Model comparison: DM test on the pinball (tick) loss (VaR) and on the
    Fissler-Ziegel FZ0 joint loss (VaR+ES; Patton-Ziegel-Chen 2019), plus MCS.
  * Cross-asset (SPY + QQQ) run SEPARATELY, no asset-day pooling (K1355).

References
----------
  Creal, Koopman & Lucas (2013) J. Applied Econometrics 28 — GAS.
  Harvey (2013) "Dynamic Models for Volatility and Heavy Tails" — DCS / Beta-t-EGARCH.
  Patton, Ziegel & Chen (2019) J. Econometrics 211 — dynamic semiparametric ES, FZ0 loss.
  Acerbi & Szekely (2014) Risk — backtesting Expected Shortfall (Z2 test).
  McNeil & Frey (2000) J. Empirical Finance 7 — exceedance-residual ES backtest.
  Kupiec (1995), Christoffersen (1998), Fissler & Ziegel (2016).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from scipy.optimize import minimize
from scipy.special import gammaln

# canonical helpers (reuse; do NOT re-implement — K802/K1259 discipline)
REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from volpred.stats.model_evaluation import (  # noqa: E402
    var_backtest,
    unit_variance_student_t_ppf,
    dm_test,
)
# call the proper HLN MCS directly (the model_evaluation wrapper passes a stale
# B= kwarg and reads a .members attribute that the current mcs API doesn't expose)
from volpred.stats.mcs import model_confidence_set as _mcs_hln  # noqa: E402


def run_mcs(losses_dict):
    """HLN stationary-bootstrap MCS; returns list of surviving model names."""
    try:
        out = _mcs_hln(losses_dict, alpha=0.10, n_boot=5000, seed=SEED)
        return out.get("mcs_models", [])
    except Exception as e:  # noqa: BLE001
        print(f"[run_mcs] WARN MCS failed: {e}", file=sys.stderr)
        return []

SEED = 42
np.random.seed(SEED)
OUTDIR = Path(__file__).resolve().parent
DATA_CSV = REPO / "paper" / "garch-x-vix" / "data" / "spy_vix_qqq_eem_fez_2000-2026.csv"

# OOS config
WINDOW = 2000          # rolling estimation window (~8y); bounds MLE cost, defensible (K783)
REFIT_EVERY = 63       # quarterly refit; roll recursion daily between refits
ALPHAS = [0.01, 0.05]  # tail levels
FLOOR_VAR = 1e-8


# ============================================================
# Data
# ============================================================
def load_returns(col: str) -> pd.Series:
    """Log returns in PERCENT from adjusted close. Dedup duplicate dates (known
    2026-05-04..05-15 dup rows in this cache, per error_log 2026-07-05)."""
    df = pd.read_csv(DATA_CSV, parse_dates=["date"])
    df = df.drop_duplicates(subset="date", keep="first").sort_values("date")
    px = df.set_index("date")[col].astype(float).dropna()
    ret = 100.0 * np.log(px / px.shift(1))
    return ret.dropna()


# ============================================================
# Student-t / Normal standardized (unit-variance) VaR & ES multipliers
# Returned as NEGATIVE numbers in units of sigma (left tail).
# ============================================================
def std_t_var_es(alpha: float, nu: float):
    """Unit-variance standardized Student-t left-tail VaR & ES multipliers."""
    if nu <= 2:
        raise ValueError("nu>2 required")
    scale = np.sqrt((nu - 2.0) / nu)
    t_a = stats.t.ppf(alpha, nu)                    # negative
    q_var = t_a * scale                             # == unit_variance_student_t_ppf
    pdf_ta = stats.t.pdf(t_a, nu)
    es_t = -(pdf_ta / alpha) * (nu + t_a ** 2) / (nu - 1.0)   # ES of standard-t (neg)
    q_es = es_t * scale
    return float(q_var), float(q_es)


def normal_var_es(alpha: float):
    z = stats.norm.ppf(alpha)                       # negative
    q_es = -stats.norm.pdf(z) / alpha               # negative
    return float(z), float(q_es)


# ============================================================
# Student-t negative log-likelihood building block (unit-variance t)
# ll_t = gammaln((nu+1)/2) - gammaln(nu/2) - 0.5*log(pi*(nu-2)) - log(sigma)
#        - (nu+1)/2 * log(1 + z^2/(nu-2)),   z = r/sigma
# ============================================================
def _t_ll(r, sigma2, nu):
    sigma2 = np.maximum(sigma2, FLOOR_VAR)
    z2 = r ** 2 / sigma2
    return (gammaln((nu + 1) / 2) - gammaln(nu / 2)
            - 0.5 * np.log(np.pi * (nu - 2))
            - 0.5 * np.log(sigma2)
            - (nu + 1) / 2 * np.log(1 + z2 / (nu - 2)))


# ---------- GARCH(1,1)-t ----------
def garch_t_recursion(params, r):
    omega, alpha, beta, nu = params
    T = len(r)
    s2 = np.empty(T)
    s2[0] = np.var(r[:WINDOW])            # seed on pre-origin window only (no block leak)
    for t in range(1, T):
        s2[t] = omega + alpha * r[t - 1] ** 2 + beta * s2[t - 1]
        if s2[t] < FLOOR_VAR:
            s2[t] = FLOOR_VAR
    return s2


def garch_t_nll(params, r):
    omega, alpha, beta, nu = params
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.9999 or nu <= 2.05:
        return 1e10
    s2 = garch_t_recursion(params, r)
    ll = _t_ll(r, s2, nu)
    v = -np.sum(ll)
    return v if np.isfinite(v) else 1e10


# ---------- GJR-GARCH(1,1)-t ----------
def gjr_t_recursion(params, r):
    omega, alpha, gamma, beta, nu = params
    T = len(r)
    s2 = np.empty(T)
    s2[0] = np.var(r[:WINDOW])            # seed on pre-origin window only (no block leak)
    for t in range(1, T):
        ind = 1.0 if r[t - 1] < 0 else 0.0
        s2[t] = omega + alpha * r[t - 1] ** 2 + gamma * r[t - 1] ** 2 * ind + beta * s2[t - 1]
        if s2[t] < FLOOR_VAR:
            s2[t] = FLOOR_VAR
    return s2


def gjr_t_nll(params, r):
    omega, alpha, gamma, beta, nu = params
    if omega <= 0 or alpha < 0 or beta < 0 or gamma < -alpha or nu <= 2.05:
        return 1e10
    if alpha + gamma / 2 + beta >= 0.9999:
        return 1e10
    s2 = gjr_t_recursion(params, r)
    ll = _t_ll(r, s2, nu)
    v = -np.sum(ll)
    return v if np.isfinite(v) else 1e10


# ---------- GAS-t (Creal-Koopman-Lucas 2013): log-variance, inverse-Fisher score ----------
# f_t = log sigma2_t ; f_{t+1} = omega + alpha*s_t + beta*f_t
# s_t = S * ( -0.5 + (nu+1)/2 * z^2/((nu-2)+z^2) ),
# where the raw score has E[score]=0 (E[b]=1) and inverse-Fisher-information
# scaling for the log-VARIANCE link with a UNIT-VARIANCE t is  S = 2(nu+3)/nu
# (Creal-Koopman-Lucas 2013 §2.2). Sanity: nu->inf => S->2 => s_t->(z^2-1),
# recovering the Gaussian EGARCH scaled score. (An earlier platform version,
# inherited by k1143.py, used S=2nu/((nu+3)(nu-2)) which -> 0 as nu->inf and
# throttled the score coefficient against the alpha bound — corrected here, K1662.)
def gas_t_recursion(params, r):
    omega, alpha, beta, nu = params
    T = len(r)
    f = np.empty(T)
    f[0] = np.log(np.var(r[:WINDOW]))     # seed on pre-origin window only (no block leak)
    S = 2 * (nu + 3) / nu
    for t in range(1, T):
        s2_prev = np.exp(f[t - 1])
        if s2_prev < FLOOR_VAR:
            s2_prev = FLOOR_VAR
        z2 = r[t - 1] ** 2 / s2_prev
        score = -0.5 + (nu + 1) / 2 * z2 / (nu - 2 + z2)
        f[t] = omega + alpha * S * score + beta * f[t - 1]
        if f[t] > 30.0:      # numerical guard; never binds for stable fits
            f[t] = 30.0
        elif f[t] < -30.0:
            f[t] = -30.0
    return np.exp(f)


def gas_t_nll(params, r):
    omega, alpha, beta, nu = params
    if alpha < 0 or beta <= 0 or beta >= 0.9999 or nu <= 2.05:
        return 1e10
    s2 = gas_t_recursion(params, r)
    if not np.all(np.isfinite(s2)):
        return 1e10
    ll = _t_ll(r, s2, nu)
    v = -np.sum(ll)
    return v if np.isfinite(v) else 1e10


# ---------- DCS-t / Beta-t-EGARCH with leverage (Harvey 2013) ----------
# f_t = log sigma2_t (log scale, exp link);  b_t = (nu+1) z^2/((nu-2)+z^2), E[b]=1
# u_t = b_t - 1 (mean-zero beta score);  leverage term uses sign of return.
# f_{t+1} = omega + beta*f_t + alpha*u_t + alpha_lev*sign(-r_t)*b_t
def dcs_t_recursion(params, r):
    omega, alpha, alpha_lev, beta, nu = params
    T = len(r)
    f = np.empty(T)
    f[0] = np.log(np.var(r[:WINDOW]))     # seed on pre-origin window only (no block leak)
    for t in range(1, T):
        s2_prev = np.exp(f[t - 1])
        if s2_prev < FLOOR_VAR:
            s2_prev = FLOOR_VAR
        z2 = r[t - 1] ** 2 / s2_prev
        b = (nu + 1) * z2 / (nu - 2 + z2)          # beta variable in [0, nu+1)
        u = b - 1.0                                 # mean-zero score
        lev = np.sign(-r[t - 1]) * b                # asymmetric (bigger vol on r<0)
        f[t] = omega + beta * f[t - 1] + alpha * u + alpha_lev * lev
        if f[t] > 30.0:      # numerical guard; never binds for stable fits
            f[t] = 30.0
        elif f[t] < -30.0:
            f[t] = -30.0
    return np.exp(f)


def dcs_t_nll(params, r):
    omega, alpha, alpha_lev, beta, nu = params
    if alpha < 0 or beta <= 0 or beta >= 0.9999 or nu <= 2.05:
        return 1e10
    s2 = dcs_t_recursion(params, r)
    if not np.all(np.isfinite(s2)):
        return 1e10
    ll = _t_ll(r, s2, nu)
    v = -np.sum(ll)
    return v if np.isfinite(v) else 1e10


# ---------- EWMA / RiskMetrics (lambda=0.94, Normal) ----------
def ewma_recursion(r, lam=0.94):
    T = len(r)
    s2 = np.empty(T)
    s2[0] = np.var(r[:20]) if T >= 20 else np.var(r)
    for t in range(1, T):
        s2[t] = lam * s2[t - 1] + (1 - lam) * r[t - 1] ** 2
    return s2


# ============================================================
# MLE fitting with multi-start
# ============================================================
MODEL_SPEC = {
    "GARCH-t": {
        "nll": garch_t_nll, "rec": garch_t_recursion,
        "x0": [
            [0.02, 0.08, 0.90, 8.0],
            [0.05, 0.05, 0.92, 6.0],
            [0.01, 0.10, 0.85, 10.0],
        ],
        "bounds": [(1e-6, 5.0), (1e-6, 0.5), (0.3, 0.998), (2.1, 60.0)],
        "dist": "t", "nu_idx": 3,
    },
    "GJR-t": {
        "nll": gjr_t_nll, "rec": gjr_t_recursion,
        "x0": [
            [0.02, 0.02, 0.10, 0.90, 8.0],
            [0.05, 0.01, 0.12, 0.90, 6.0],
            [0.01, 0.04, 0.06, 0.88, 10.0],
        ],
        "bounds": [(1e-6, 5.0), (0.0, 0.4), (0.0, 0.6), (0.3, 0.998), (2.1, 60.0)],
        "dist": "t", "nu_idx": 4,
    },
    "GAS-t": {
        "nll": gas_t_nll, "rec": gas_t_recursion,
        "x0": [
            [0.01, 0.05, 0.95, 8.0],
            [0.02, 0.08, 0.90, 6.0],
            [0.005, 0.03, 0.97, 10.0],
        ],
        "bounds": [(-2.0, 2.0), (0.0, 1.5), (0.3, 0.999), (2.1, 60.0)],
        "dist": "t", "nu_idx": 3,
    },
    "DCS-t": {
        "nll": dcs_t_nll, "rec": dcs_t_recursion,
        "x0": [
            [0.01, 0.05, 0.02, 0.95, 8.0],
            [0.02, 0.08, 0.03, 0.90, 6.0],
            [0.005, 0.03, 0.01, 0.97, 10.0],
        ],
        "bounds": [(-2.0, 2.0), (0.0, 1.5), (-0.5, 0.5), (0.3, 0.999), (2.1, 60.0)],
        "dist": "t", "nu_idx": 4,
    },
}


def fit_model(name, r, x0_list=None):
    spec = MODEL_SPEC[name]
    nll, bounds = spec["nll"], spec["bounds"]
    starts = x0_list if x0_list is not None else spec["x0"]
    best = None
    for x0 in starts:
        try:
            res = minimize(nll, x0, args=(r,), method="L-BFGS-B",
                           bounds=bounds, options={"maxiter": 400})
            if res.success and np.isfinite(res.fun) and res.fun < 1e9:
                if best is None or res.fun < best.fun:
                    best = res
        except Exception as e:  # noqa: BLE001
            print(f"[fit_model] WARN {name} start {x0} failed: {e}", file=sys.stderr)
            continue
    if best is None:
        return None
    return best.x, float(best.fun)


# ============================================================
# One-step-ahead OOS forecasts (rolling window, quarterly refit)
# Returns dict: model -> {sigma, nu, dist, var[alpha], es[alpha]} aligned to r_oos
# ============================================================
def run_oos(r: np.ndarray, dates: pd.DatetimeIndex, label: str):
    n = len(r)
    oos_start = WINDOW
    oos_idx = np.arange(oos_start, n)
    n_oos = len(oos_idx)
    print(f"[{label}] n={n}, OOS days={n_oos} ({dates[oos_start].date()}..{dates[-1].date()})")

    models = list(MODEL_SPEC.keys()) + ["EWMA-N"]
    sigma = {m: np.full(n_oos, np.nan) for m in models}
    nu_arr = {m: np.full(n_oos, np.nan) for m in models}
    params_log = {m: [] for m in MODEL_SPEC}

    # refit anchors: every REFIT_EVERY days. For each anchor we refit on the
    # rolling window strictly before the origin, then run ONE recursion forward
    # over the block so each in-block sigma_t is the one-step-ahead forecast
    # (s2[t] depends only on r[t-1], s2[t-1]) -- ~REFIT_EVERY x faster, identical.
    warm = {m: None for m in MODEL_SPEC}
    t0 = time.time()
    anchors = list(range(0, n_oos, REFIT_EVERY))
    for k0 in anchors:
        i0 = oos_idx[k0]                 # global forecast origin (first day of block)
        win = r[i0 - WINDOW:i0]          # strictly < i0 -> lookahead safe
        k_end = min(k0 + REFIT_EVERY, n_oos)
        i_end = oos_idx[k_end - 1] + 1   # global end (exclusive) of block forecasts
        seg = r[i0 - WINDOW:i_end]       # recursion segment; pos p -> global (i0-WINDOW)+p
        base = i0 - WINDOW
        for m in MODEL_SPEC:
            x0_list = None
            if warm[m] is not None:
                x0_list = [list(warm[m])] + MODEL_SPEC[m]["x0"]
            fit = fit_model(m, win, x0_list=x0_list)
            if fit is not None:
                warm[m] = fit[0]
                params_log[m].append({"origin": str(dates[i0].date()),
                                      "params": [float(x) for x in fit[0]],
                                      "nll": fit[1]})
            p = warm[m]
            if p is None:
                continue
            s2_seg = MODEL_SPEC[m]["rec"](p, seg)
            nu_val = p[MODEL_SPEC[m]["nu_idx"]]
            for k in range(k0, k_end):
                j = oos_idx[k]           # global day; one-step-ahead sigma_j = s2_seg[j-base]
                sigma[m][k] = np.sqrt(max(s2_seg[j - base], FLOOR_VAR))
                nu_arr[m][k] = nu_val
        # EWMA (no fit) over same block
        s2_ewma = ewma_recursion(seg, lam=0.94)
        for k in range(k0, k_end):
            j = oos_idx[k]
            sigma["EWMA-N"][k] = np.sqrt(max(s2_ewma[j - base], FLOOR_VAR))
            nu_arr["EWMA-N"][k] = np.nan
        if k0 % 630 == 0 and k0 > 0:
            print(f"  [{label}] {k0}/{n_oos}  ({time.time()-t0:.0f}s)")

    r_oos = r[oos_start:]
    dates_oos = dates[oos_start:]

    # Build VaR/ES forecasts (negative return-space) per model/alpha
    out = {}
    for m in models:
        dist = "normal" if m == "EWMA-N" else "t"
        var_a, es_a = {}, {}
        for a in ALPHAS:
            v = np.full(n_oos, np.nan)
            e = np.full(n_oos, np.nan)
            for k in range(n_oos):
                sg = sigma[m][k]
                if not np.isfinite(sg):
                    continue
                if dist == "normal":
                    qv, qe = normal_var_es(a)
                else:
                    nu = nu_arr[m][k]
                    if not np.isfinite(nu) or nu <= 2:
                        continue
                    qv, qe = std_t_var_es(a, nu)
                v[k] = sg * qv       # negative
                e[k] = sg * qe       # negative (<= v)
            var_a[a] = v
            es_a[a] = e
        out[m] = {"sigma": sigma[m], "nu": nu_arr[m], "dist": dist,
                  "var": var_a, "es": es_a}
    return {"r_oos": r_oos, "dates_oos": dates_oos, "models": models,
            "forecasts": out, "params_log": params_log,
            "oos_span": [str(dates_oos[0].date()), str(dates_oos[-1].date())]}


# ============================================================
# Loss functions
# ============================================================
def tick_loss(r, v, alpha):
    """Pinball/tick loss for the alpha-quantile VaR. v = VaR forecast (negative)."""
    hit = (r < v).astype(float)
    return (alpha - hit) * (r - v)


def fz0_loss(r, v, e, alpha):
    """Fissler-Ziegel FZ0 joint VaR+ES loss (Patton-Ziegel-Chen 2019).
    v, e negative (return-space). Lower is better."""
    e = np.minimum(e, -FLOOR_VAR)          # ensure e<0
    hit = (r <= v).astype(float)
    return (1.0 / (alpha * e)) * hit * (r - v) + v / e + np.log(-e) - 1.0


# ============================================================
# VaR backtest driven by the model's ACTUAL per-day VaR series
# (mirrors canonical var_backtest() formulas, but tests the exact per-day-nu
#  VaR the model produced instead of reconstructing it from a single median nu)
# ============================================================
def var_backtest_series(r, var_series, alpha):
    """Kupiec POF + Christoffersen independence + exact-binomial traffic light,
    computed directly from a given VaR series (negative return-space)."""
    r = np.asarray(r, dtype=np.float64)
    var = np.asarray(var_series, dtype=np.float64)
    viol = (r < var).astype(int)
    n = len(r)
    n1 = int(viol.sum())
    n0 = n - n1
    pi_hat = n1 / n if n > 0 else 0.0

    # Kupiec (1995) unconditional coverage
    if n1 == 0 or n1 == n:
        kup_stat, kup_p = 0.0, 1.0
    else:
        lr = -2 * (n1 * np.log(alpha) + n0 * np.log(1 - alpha)
                   - n1 * np.log(pi_hat) - n0 * np.log(1 - pi_hat))
        kup_stat, kup_p = float(lr), float(1 - stats.chi2.cdf(lr, df=1))

    # Christoffersen (1998) independence
    cc_computed = True
    try:
        t00 = int(np.sum((viol[:-1] == 0) & (viol[1:] == 0)))
        t01 = int(np.sum((viol[:-1] == 0) & (viol[1:] == 1)))
        t10 = int(np.sum((viol[:-1] == 1) & (viol[1:] == 0)))
        t11 = int(np.sum((viol[:-1] == 1) & (viol[1:] == 1)))
        pi01 = t01 / (t00 + t01) if (t00 + t01) > 0 else 0
        pi11 = t11 / (t10 + t11) if (t10 + t11) > 0 else 0
        pi_all = (t01 + t11) / (t00 + t01 + t10 + t11) if n > 1 else 0
        if 0 < pi01 < 1 and 0 < pi11 < 1 and 0 < pi_all < 1:
            lr_ind = -2 * ((t00 + t10) * np.log(1 - pi_all) + (t01 + t11) * np.log(pi_all)
                           - t00 * np.log(1 - pi01) - t01 * np.log(pi01)
                           - t10 * np.log(1 - pi11) - t11 * np.log(pi11))
            cc_stat, cc_p = float(lr_ind), float(1 - stats.chi2.cdf(lr_ind, df=1))
        else:
            cc_stat, cc_p = 0.0, 1.0
    except Exception as e:  # noqa: BLE001
        print(f"[var_backtest_series] WARN christoffersen failed: {e}", file=sys.stderr)
        cc_computed, cc_stat, cc_p = False, None, None

    green = int(stats.binom.ppf(0.95, n, alpha))
    yellow = int(stats.binom.ppf(0.9999, n, alpha))
    traffic = "green" if n1 <= green else ("yellow" if n1 <= yellow else "red")
    cc_pass = bool(cc_computed and cc_p is not None and cc_p > 0.05)
    return {
        "violation_rate": float(pi_hat), "n_violations": n1, "n_total": n,
        "kupiec": {"stat": kup_stat, "p_value": kup_p, "pass": kup_p > 0.05},
        "christoffersen": {"stat": cc_stat, "p_value": cc_p, "pass": cc_pass,
                           "computed": cc_computed},
        "basel_traffic_light": traffic, "basel_green_cutoff": green,
        "trinity_pass": bool(kup_p > 0.05 and cc_pass and traffic == "green"),
    }


# ============================================================
# ES backtests
# ============================================================
def acerbi_szekely_z2(r, v, e, alpha, dist, nu_arr, n_sim=10000, seed=SEED):
    """Acerbi-Szekely (2014) Test 2 with Monte-Carlo null p-value.

    Standard AS convention with POSITIVE ES magnitude (esmag = -e > 0):
        Z2 = 1 + (1/(N*alpha)) * sum_t [ r_t * 1{r_t<v_t} / esmag_t ].
    Under H0 E[Z2]=0; Z2 < 0 => realized tail losses exceed ES (understated).
    One-sided p for understatement = P(Z2_sim <= Z2_real); reject if p < 0.05.
    Null simulated under each day's predictive distribution (seed=42)."""
    mask = np.isfinite(v) & np.isfinite(e) & np.isfinite(r)
    r, v, e = r[mask], v[mask], e[mask]
    esmag = -e                                       # positive ES magnitude
    N = len(r)
    if N < 30:
        return {"z2": None, "p_value": None, "n": int(N), "computed": False}

    def z2_of(ret):
        hit = (ret < v).astype(float)
        return 1.0 + np.sum(ret * hit / esmag) / (N * alpha)

    z2_real = float(z2_of(r))
    # sigma path implied by e and the ES multiplier -> simulate returns under H0
    rng = np.random.default_rng(seed)
    if dist == "normal":
        _, qe = normal_var_es(alpha)
        sigma_path = e / qe               # recover sigma from ES forecast
        z2_sim = np.empty(n_sim)
        for b in range(n_sim):
            sim = rng.standard_normal(N) * sigma_path
            z2_sim[b] = z2_of(sim)
    else:
        nu_use = nu_arr[mask]
        # sigma and unit-variance scale from EACH day's own predictive nu
        sigma_path = np.empty(N)
        day_scale = np.sqrt((nu_use - 2.0) / nu_use)   # per-day unit-variance factor
        for k in range(N):
            _, qe = std_t_var_es(alpha, nu_use[k])
            sigma_path[k] = e[k] / qe
        z2_sim = np.empty(n_sim)
        for b in range(n_sim):
            # per-day standardized (unit-variance) t draws under each day's own nu
            raw = rng.standard_t(nu_use)               # numpy broadcasts per-element df
            sim = raw * day_scale * sigma_path
            z2_sim[b] = z2_of(sim)
    p = float(np.mean(z2_sim <= z2_real))
    return {"z2": z2_real, "p_value": p, "n": int(N), "computed": True,
            "reject_es_understated": bool(p < 0.05)}


def mcneil_frey_boot(r, v, e, sigma, alpha, n_boot=10000, seed=SEED):
    """McNeil-Frey (2000) exceedance-residual bootstrap.
    On VaR-violation days, residual = (r_t - e_t)/sigma_t.  H0: mean = 0.
    One-sided H1: mean < 0 (realized tail losses worse than predicted ES)."""
    mask = np.isfinite(v) & np.isfinite(e) & np.isfinite(r) & np.isfinite(sigma)
    r, v, e, sigma = r[mask], v[mask], e[mask], sigma[mask]
    viol = r < v
    nv = int(viol.sum())
    if nv < 5:
        return {"mean_resid": None, "p_value": None, "n_viol": nv, "computed": False}
    resid = (r[viol] - e[viol]) / sigma[viol]
    mean_resid = float(np.mean(resid))
    rng = np.random.default_rng(seed)
    centered = resid - mean_resid
    boot_means = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, nv, size=nv)
        boot_means[b] = np.mean(centered[idx])
    # one-sided p for H1 mean<0: fraction of bootstrap means <= observed
    p = float(np.mean(boot_means <= mean_resid))
    return {"mean_resid": mean_resid, "p_value": p, "n_viol": nv, "computed": True,
            "reject_es_understated": bool(p < 0.05 and mean_resid < 0)}


# ============================================================
# Convergence stability check (20 random inits, full sample)
# ============================================================
def convergence_check(name, r, n_init=20, seed=SEED):
    spec = MODEL_SPEC[name]
    rng = np.random.default_rng(seed)
    bounds = spec["bounds"]
    lls = []
    for _ in range(n_init):
        x0 = [rng.uniform(lo if np.isfinite(lo) else -1.0,
                          hi if np.isfinite(hi) else 1.0) for (lo, hi) in bounds]
        try:
            res = minimize(spec["nll"], x0, args=(r,), method="L-BFGS-B",
                           bounds=bounds, options={"maxiter": 400})
            if res.success and np.isfinite(res.fun) and res.fun < 1e9:
                lls.append(float(res.fun))
        except Exception as e:  # noqa: BLE001
            print(f"[convergence_check] WARN {name} init failed: {e}", file=sys.stderr)
            continue
    if not lls:
        return {"n_converged": 0, "best_nll": None, "frac_at_best": None}
    lls = np.array(lls)
    best = float(lls.min())
    frac = float(np.mean(lls <= best + 0.5))   # within 0.5 nll of best
    return {"n_init": n_init, "n_converged": int(len(lls)), "best_nll": best,
            "worst_nll": float(lls.max()), "nll_std": float(lls.std()),
            "frac_at_best": frac}


# ============================================================
# Backtest one asset
# ============================================================
def backtest_asset(oos, label):
    r = oos["r_oos"]
    models = oos["models"]
    fc = oos["forecasts"]
    res = {"label": label, "oos_span": oos["oos_span"], "n_oos": int(len(r)),
           "window": WINDOW, "refit_every": REFIT_EVERY, "models": {}}

    # per model / per alpha
    for m in models:
        res["models"][m] = {"dist": fc[m]["dist"], "alphas": {}}
        for a in ALPHAS:
            v = fc[m]["var"][a]
            e = fc[m]["es"][a]
            sig = fc[m]["sigma"]
            mask = np.isfinite(v)
            rr, vv, ee, ss = r[mask], v[mask], e[mask], sig[mask]

            # VaR backtest on the model's ACTUAL per-day VaR series (vv). This
            # tests the exact per-day-nu VaR the model produced — not a single
            # median-nu reconstruction (reviewer MEDIUM fix). As a cross-check we
            # also run the canonical var_backtest (median-nu) and store its light.
            vb = var_backtest_series(rr, vv, alpha=a)
            if fc[m]["dist"] == "normal":
                vb_canon = var_backtest(rr, ss, alpha=a, distribution="normal")
            else:
                nu_med = float(np.nanmedian(fc[m]["nu"][mask]))
                vb_canon = var_backtest(rr, ss, alpha=a, distribution="t", df=nu_med)

            # ES backtests
            asz = acerbi_szekely_z2(rr, vv, ee, a, fc[m]["dist"], fc[m]["nu"][mask])
            mf = mcneil_frey_boot(rr, vv, ee, ss, a)

            # losses
            tl = tick_loss(rr, vv, a)
            fz = fz0_loss(rr, vv, ee, a)

            res["models"][m]["alphas"][str(a)] = {
                "n": int(mask.sum()),
                "var_breach_rate": float(np.mean(rr < vv)),
                "expected_rate": a,
                "kupiec_p": vb["kupiec"]["p_value"],
                "kupiec_pass": bool(vb["kupiec"]["pass"]),
                "christoffersen_p": vb["christoffersen"]["p_value"],
                "christoffersen_pass": bool(vb["christoffersen"]["pass"]),
                "basel_exact_binomial_light": vb["basel_traffic_light"],
                "basel_green_cutoff": vb["basel_green_cutoff"],
                "trinity_pass": bool(vb["trinity_pass"]),
                "basel_light_medianNu_crosscheck": vb_canon["basel_traffic_light"],
                "acerbi_szekely_z2": asz["z2"],
                "acerbi_szekely_p": asz["p_value"],
                "acerbi_reject_es_understated": asz.get("reject_es_understated"),
                "mcneil_frey_mean_resid": mf["mean_resid"],
                "mcneil_frey_p": mf["p_value"],
                "mcneil_frey_n_viol": mf["n_viol"],
                "mcneil_reject_es_understated": mf.get("reject_es_understated"),
                "pinball_loss_mean": float(np.mean(tl)),
                "fz0_loss_mean": float(np.mean(fz)),
            }

    # ---- model comparison: DM (pinball & FZ0) vs the two GARCH baselines, + MCS ----
    res["comparison"] = {}
    # common finite mask across all models for fair alignment
    for a in ALPHAS:
        finite = np.ones(len(r), dtype=bool)
        for m in models:
            finite &= np.isfinite(fc[m]["var"][a]) & np.isfinite(fc[m]["es"][a])
        rr = r[finite]
        pin = {m: tick_loss(rr, fc[m]["var"][a][finite], a) for m in models}
        fz = {m: fz0_loss(rr, fc[m]["var"][a][finite], fc[m]["es"][a][finite], a) for m in models}

        # DM: score-driven vs its matched baseline (neg t => first better)
        pairs = [("GAS-t", "GARCH-t"), ("DCS-t", "GJR-t"),
                 ("GAS-t", "EWMA-N"), ("DCS-t", "EWMA-N")]
        dm_pin, dm_fz = {}, {}
        for (m1, m2) in pairs:
            t_p, p_p = dm_test(pin[m1], pin[m2])
            t_f, p_f = dm_test(fz[m1], fz[m2])
            dm_pin[f"{m1}_vs_{m2}"] = {"dm_t": t_p, "p": p_p,
                                       "harvey_pass": abs(t_p) > 3.0,
                                       "better": m1 if t_p < 0 else m2}
            dm_fz[f"{m1}_vs_{m2}"] = {"dm_t": t_f, "p": p_f,
                                      "harvey_pass": abs(t_f) > 3.0,
                                      "better": m1 if t_f < 0 else m2}
        mcs_pin = run_mcs(pin)
        mcs_fz = run_mcs(fz)
        res["comparison"][str(a)] = {
            "n_aligned": int(finite.sum()),
            "mean_pinball": {m: float(np.mean(pin[m])) for m in models},
            "mean_fz0": {m: float(np.mean(fz[m])) for m in models},
            "dm_pinball": dm_pin,
            "dm_fz0": dm_fz,
            "mcs_pinball_members": mcs_pin,
            "mcs_fz0_members": mcs_fz,
        }
    return res


# ============================================================
# Charts
# ============================================================
def make_charts(oos, label, tag):
    r = oos["r_oos"]
    dates = oos["dates_oos"]
    fc = oos["forecasts"]
    a = 0.01
    # 1) VaR breach time series: GAS-t, GJR-t, EWMA-N at 1%
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    ax = axes[0]
    ax.plot(dates, r, color="0.6", lw=0.4, label="SPY return (%)" if tag == "spy" else f"{tag.upper()} return (%)")
    for m, c in [("GAS-t", "C0"), ("GJR-t", "C3"), ("EWMA-N", "C2")]:
        ax.plot(dates, fc[m]["var"][a], lw=0.8, label=f"{m} VaR 1%", color=c)
    ax.set_title(f"K1662 {label}: 1% VaR forecasts vs realized returns")
    ax.legend(loc="lower left", fontsize=8, ncol=2)
    ax.set_ylabel("return (%)")

    ax2 = axes[1]
    for m, c in [("GAS-t", "C0"), ("DCS-t", "C1"), ("GARCH-t", "C4"),
                 ("GJR-t", "C3"), ("EWMA-N", "C2")]:
        breach = (r < fc[m]["var"][a]).astype(float)
        cum = np.cumsum(breach) - np.arange(1, len(r) + 1) * a
        ax2.plot(dates, cum, lw=1.0, label=m, color=c)
    ax2.axhline(0, color="k", lw=0.6, ls="--")
    ax2.set_title("Cumulative 1% VaR breaches minus expected (0 = perfectly calibrated)")
    ax2.legend(loc="upper left", fontsize=8, ncol=3)
    ax2.set_ylabel("cum. excess breaches")
    fig.tight_layout()
    p1 = OUTDIR / f"k1662_{tag}_var_breach.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)

    # 2) loss comparison bars (pinball + FZ0 at both alphas)
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    models = oos["models"]
    for j, a in enumerate(ALPHAS):
        finite = np.ones(len(r), dtype=bool)
        for m in models:
            finite &= np.isfinite(fc[m]["var"][a]) & np.isfinite(fc[m]["es"][a])
        rr = r[finite]
        fzm = {m: float(np.mean(fz0_loss(rr, fc[m]["var"][a][finite],
                                         fc[m]["es"][a][finite], a))) for m in models}
        xs = np.arange(len(models))
        cols = ["C0" if m in ("GAS-t", "DCS-t") else ("C2" if m == "EWMA-N" else "C3") for m in models]
        axes[j].bar(xs, [fzm[m] for m in models], color=cols)
        axes[j].set_xticks(xs)
        axes[j].set_xticklabels(models, rotation=30, ha="right", fontsize=8)
        axes[j].set_title(f"Mean FZ0 joint VaR+ES loss @ alpha={a}\n(blue=score-driven, red=GARCH, green=EWMA)")
        axes[j].set_ylabel("mean FZ0 (lower=better)")
    fig.suptitle(f"K1662 {label}: joint VaR+ES loss (lower is better)")
    fig.tight_layout()
    p2 = OUTDIR / f"k1662_{tag}_fz0_loss.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    return [p1.name, p2.name]


# ============================================================
# Main
# ============================================================
def main():
    t_start = time.time()
    assets = {"spy": "spy_adj_close", "qqq": "qqq_adj_close"}
    all_results = {"experiment_id": "K1662",
                   "title": "Score-driven (GAS/DCS) direct VaR+ES estimation & backtest",
                   "seed": SEED, "window": WINDOW, "refit_every": REFIT_EVERY,
                   "alphas": ALPHAS,
                   "notes": {
                       "basel": "traffic light is EXACT-BINOMIAL at realized n (var_backtest), NOT canonical 250-day count table",
                       "var_es_scaling": "Student-t VaR/ES use unit-variance sqrt((nu-2)/nu) scaling (K802)",
                       "lookahead": "sigma_t uses returns up to t-1; params refit on data < forecast origin; same lag all models",
                       "design": "2x2 fair matrix: GAS-t vs GARCH-t (symmetric), DCS-t vs GJR-t (asymmetric), + EWMA-N naive",
                       "prior_k": "K437/K1038/K1129/K1134/K1138/K1143 = QLIKE point-forecast NULL; K1662 tests orthogonal tail-risk calibration",
                       "gas_S_correction": "GAS-t inverse-Fisher scaling S=2(nu+3)/nu (CKL 2013; ->2 as nu->inf). Earlier platform/k1143 used S=2nu/((nu+3)(nu-2)) (->0, wrong); corrected here. Results bit-identical because free alpha compensated (only alpha*S enters; bound never bound).",
                       "backtest_object": "Kupiec/Christoffersen/traffic-light run on the model's actual per-day-nu VaR series (var_backtest_series); median-nu canonical var_backtest kept as basel_light_medianNu_crosscheck.",
                       "reviewer": "feature-dev:code-reviewer fresh-context (Codex usage-limited fallback per K1259/K1261/K1262)",
                   },
                   "assets": {}}

    # convergence stability (full-sample SPY) once
    r_spy_full = load_returns("spy_adj_close").values
    conv = {}
    for m in ["GAS-t", "DCS-t"]:
        conv[m] = convergence_check(m, r_spy_full[-3000:], n_init=20)
        print(f"[convergence] {m}: {conv[m]}")
    all_results["convergence_stability_spy"] = conv

    for tag, col in assets.items():
        ret = load_returns(col)
        r = ret.values
        dates = ret.index
        label = tag.upper()
        oos = run_oos(r, dates, label)
        bt = backtest_asset(oos, label)
        charts = make_charts(oos, label, tag)
        bt["charts"] = charts
        # attach a compact params summary (last fit each model)
        bt["last_fit_params"] = {m: (oos["params_log"][m][-1] if oos["params_log"][m] else None)
                                 for m in MODEL_SPEC}
        all_results["assets"][tag] = bt
        print(f"[{label}] backtest done.")

    all_results["runtime_sec"] = round(time.time() - t_start, 1)
    out = OUTDIR / "k1662_results.json"
    with open(out, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"[done] wrote {out}  ({all_results['runtime_sec']}s)")


if __name__ == "__main__":
    main()
