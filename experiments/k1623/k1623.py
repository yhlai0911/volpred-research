"""
K1623 — RV persistence: true long memory vs level-shift artifact
================================================================

Question
--------
The slow ACF decay of volatility ("apparent long memory") can arise from
(i) genuine long-range dependence (ARFIMA / rough-vol, d in (0, 0.5)) OR
(ii) short memory contaminated by unmodelled structural LEVEL SHIFTS, which
inflate the ACF and bias fractional-integration estimators upward
(Diebold & Inoue 2001; Granger & Hyung 2004; Perron & Qu 2010; Qu 2011).

Identification (core): estimate d-hat on the RAW log-RV series vs on the
BREAK-DEMEANED residual (piecewise-constant mean removed at Bai-Perron breaks).
  - if d-hat collapses toward 0 after break-demeaning  -> spurious LM (level shifts)
  - if d-hat stays significantly > 0                    -> genuine long memory
  - partial drop                                        -> mixed

Forecast implication (OOS): if persistence is a level-shift artifact, a
break-robust / adaptive model should beat a fractional-integration (ARFIMA)
model out of sample.

Assets (deep, not wide): ^VIX (implied-vol level), SPY, 0050.TW range-based RV.
RV proxy = Parkinson high-low range variance (daily); VIX proxy = (VIX/100)^2.
Work in log-variance throughout.

Anti-lookahead
--------------
- One-step expanding-window OOS; every forecast of y_{i+1} uses only y_0..y_i.
- HAR/ARFIMA/break detectors at origin i see only data up to i.
- QLIKE canonical: actual/predicted - log(actual/predicted) - 1 via
  volpred.stats.model_evaluation.qlike_pointwise.
- All randomness seeded (np.random.seed(SEED)).

Run:  uv run python experiments/k1623/k1623.py
"""
from __future__ import annotations

import json
import sqlite3
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.signal import fftconvolve
from statsmodels.tsa.stattools import acf

from volpred.stats.model_evaluation import qlike_pointwise

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
PLOTS = HERE / "plots"
PLOTS.mkdir(exist_ok=True)


def _resolve_db() -> Path:
    """Locate price_cache.db (gitignored -> lives in the main checkout, not the worktree)."""
    candidates = []
    for p in HERE.parents:
        candidates.append(p / "data" / "cache" / "price_cache.db")
    candidates.append(Path.home() / "volpred-research" / "data" / "cache" / "price_cache.db")
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError("price_cache.db not found in any candidate path")


DB = _resolve_db()

# Assets: (ticker, proxy_kind, label). "range" = Parkinson HL variance; "vix" = (VIX/100)^2.
ASSETS = [
    ("^VIX", "vix", "VIX"),
    ("SPY", "range", "SPY"),
    ("0050.TW", "range", "TW0050"),
    ("QQQ", "range", "QQQ"),      # extra if time permits
    ("^N225", "range", "N225"),   # extra if time permits
]

OOS_TEST_N = 750          # size of one-step OOS test window (last N obs)
REEST_EVERY = 22          # re-estimate d (ARFIMA) & break window every 22 origins
HAR_MINTRAIN = 300        # minimum training obs before OOS starts
FD_MAXK = 2000            # fractional-difference weight truncation
EWMA_LAMBDA = 0.94
LOG_FLOOR = 1e-12


# --------------------------------------------------------------------------- #
# Data / RV proxy
# --------------------------------------------------------------------------- #
def load_ohlc(ticker: str) -> pd.DataFrame:
    con = sqlite3.connect(DB)
    df = pd.read_sql_query(
        "SELECT date, open, high, low, close FROM price_data "
        "WHERE ticker = ? ORDER BY date",
        con, params=(ticker,),
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.dropna(subset=["close"]).reset_index(drop=True)


def rv_proxy(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    """
    Return DataFrame date, rv (variance), logrv. .attrs['n_dropped'] = number of
    degenerate observations removed. For range assets, days with high<=low are
    data artifacts (halted / stale / non-trading quotes with zero traded range,
    NOT genuine zero-volatility days) and are DROPPED (not floored), because a
    floored ~0 realized value detonates QLIKE (-log(actual/pred) -> +inf).
    """
    d = df.copy()
    if kind == "vix":
        rv = (d["close"].to_numpy(dtype=float) / 100.0) ** 2
        dates = d["date"].to_numpy()
        keep = np.isfinite(rv) & (rv > 0)
        n_dropped = int(np.sum(~keep))
        rv, dates = rv[keep], dates[keep]
    elif kind == "range":
        hi = d["high"].to_numpy(dtype=float)
        lo = d["low"].to_numpy(dtype=float)
        dates = d["date"].to_numpy()
        ok = (hi > 0) & (lo > 0) & np.isfinite(hi) & np.isfinite(lo) & (hi > lo)
        n_dropped = int(np.sum(~ok))
        loghl = np.log(hi[ok] / lo[ok])
        rv = (loghl ** 2) / (4.0 * np.log(2.0))  # Parkinson variance
        dates = dates[ok]
    else:
        raise ValueError(kind)
    out = pd.DataFrame({"date": dates, "rv": rv})
    out["logrv"] = np.log(out["rv"].to_numpy())
    out.attrs["n_dropped"] = n_dropped
    return out.dropna().reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Spectral / long-memory estimators
# --------------------------------------------------------------------------- #
def periodogram(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    n = len(x)
    ft = np.fft.fft(x)
    return (np.abs(ft) ** 2) / (2.0 * np.pi * n)


def gph_estimator(x: np.ndarray, m: int) -> dict:
    """Geweke-Porter-Hudak log-periodogram regression. d = -slope."""
    n = len(x)
    I = periodogram(x)
    j = np.arange(1, m + 1)
    lam = 2.0 * np.pi * j / n
    Ij = np.maximum(I[1:m + 1], 1e-300)
    X = np.log(4.0 * np.sin(lam / 2.0) ** 2)
    Y = np.log(Ij)
    Xc = X - X.mean()
    Sxx = float(np.sum(Xc ** 2))
    slope = float(np.sum(Xc * (Y - Y.mean())) / Sxx)
    d_hat = -slope
    se = float(np.sqrt((np.pi ** 2 / 6.0) / Sxx))
    return {"d": d_hat, "se": se, "m": int(m), "t": d_hat / se if se > 0 else float("nan"),
            "ci": [d_hat - 1.96 * se, d_hat + 1.96 * se],
            "sig_gt0": bool(d_hat - 1.96 * se > 0)}


def _fd_weights(d: float, K: int) -> np.ndarray:
    w = np.empty(K + 1)
    w[0] = 1.0
    for k in range(1, K + 1):
        w[k] = w[k - 1] * (k - 1 - d) / k
    return w


def fracdiff(x: np.ndarray, d: float, maxK: int = FD_MAXK) -> np.ndarray:
    n = len(x)
    K = min(maxK, n - 1)
    w = _fd_weights(d, K)
    return fftconvolve(np.asarray(x, dtype=float), w)[:n]


def local_whittle(x: np.ndarray, m: int, exact: bool = False) -> dict:
    """
    Local Whittle (exact=False, valid d in (-0.5, 0.5)) or Exact Local Whittle
    (exact=True, Shimotsu-Phillips 2005 style with sample-mean demeaning, valid
    up to non-stationary d). SE = 1/(2 sqrt(m)). CI = d +/- 1.96 SE.
    Standard LW bounded to (-0.49, 0.49); a boundary hit is flagged (true d is
    in the non-stationary region -> defer to ELW/GPH).
    """
    n = len(x)
    m = int(m)
    j = np.arange(1, m + 1)
    lam = 2.0 * np.pi * j / n
    log_lam_mean = float(np.mean(np.log(lam)))

    if not exact:
        I = periodogram(x)
        Ij = np.maximum(I[1:m + 1], 1e-300)

        def obj(d):
            G = float(np.mean((lam ** (2.0 * d)) * Ij))
            return np.log(max(G, 1e-300)) - 2.0 * d * log_lam_mean

        lo, hi = (-0.49, 0.49)
    else:
        xd = np.asarray(x, dtype=float) - float(np.mean(x))
        K = min(FD_MAXK, n - 1)

        def obj(d):
            fd = fftconvolve(xd, _fd_weights(d, K))[:n]
            Ifd = periodogram(fd)
            Ij = np.maximum(Ifd[1:m + 1], 1e-300)
            G = float(np.mean(Ij))
            return np.log(max(G, 1e-300)) - 2.0 * d * log_lam_mean

        lo, hi = (-0.49, 0.99)

    res = minimize_scalar(obj, bounds=(lo, hi), method="bounded",
                          options={"xatol": 1e-4})
    d_hat = float(res.x)
    se = 1.0 / (2.0 * np.sqrt(m))
    boundary = bool(abs(d_hat - hi) < 1e-3 or abs(d_hat - lo) < 1e-3)
    return {"d": d_hat, "se": se, "m": m, "t": d_hat / se if se > 0 else float("nan"),
            "ci": [d_hat - 1.96 * se, d_hat + 1.96 * se],
            "sig_gt0": bool(d_hat - 1.96 * se > 0), "boundary_hit": boundary,
            "exact": bool(exact)}


# --------------------------------------------------------------------------- #
# Bai-Perron multiple breaks in mean (vectorised dynamic programming)
# --------------------------------------------------------------------------- #
def _seg_prefix(y: np.ndarray):
    S1 = np.concatenate([[0.0], np.cumsum(y)])
    S2 = np.concatenate([[0.0], np.cumsum(y ** 2)])
    return S1, S2


def _seg_ssr_vec(S1, S2, s_arr, t):
    """SSR of segments (s+1 .. t) inclusive for a vector of s (0-based inclusive)."""
    L = (t - s_arr).astype(float)
    sy = S1[t + 1] - S1[s_arr + 1]
    sy2 = S2[t + 1] - S2[s_arr + 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        ssr = sy2 - (sy ** 2) / L
    return ssr


def bai_perron(y: np.ndarray, max_breaks: int = 5, min_frac: float = 0.15):
    """
    Global-minimiser Bai-Perron partition (mean shifts) for m = 0..max_breaks,
    select m by BIC. Vectorised DP: O(max_breaks * n) numpy row-ops.
    """
    y = np.asarray(y, dtype=float)
    n = len(y)
    h = max(int(np.floor(min_frac * n)), 5)
    max_breaks = min(max_breaks, max(0, n // h - 1))
    S1, S2 = _seg_prefix(y)

    def full_ssr(a, b):  # inclusive a..b
        L = b - a + 1
        sy = S1[b + 1] - S1[a]
        sy2 = S2[b + 1] - S2[a]
        return sy2 - sy * sy / L

    INF = np.inf
    opt = np.full((max_breaks + 1, n), INF)
    arg = np.full((max_breaks + 1, n), -1, dtype=int)

    for t in range(n):
        if t + 1 >= h:
            opt[0][t] = full_ssr(0, t)

    for k in range(1, max_breaks + 1):
        for t in range(n):
            s_hi = t - h
            s_lo = k * h - 1
            if s_hi < s_lo:
                continue
            s_arr = np.arange(s_lo, s_hi + 1)
            prev = opt[k - 1][s_arr]
            valid = np.isfinite(prev)
            if not np.any(valid):
                continue
            seg = _seg_ssr_vec(S1, S2, s_arr, t)
            tot = prev + seg
            tot[~valid] = INF
            idx = int(np.argmin(tot))
            opt[k][t] = tot[idx]
            arg[k][t] = s_arr[idx]

    def breaks_for(k):
        if k == 0 or not np.isfinite(opt[k][n - 1]):
            return []
        bks = []
        t = n - 1
        kk = k
        while kk > 0:
            s = arg[kk][t]
            if s < 0:
                break
            bks.append(s + 1)
            t = s
            kk -= 1
        return sorted(bks)

    results = {}
    for k in range(0, max_breaks + 1):
        ssr = float(opt[k][n - 1])
        if not np.isfinite(ssr):
            continue
        p = 2 * k + 1
        bic = n * np.log(ssr / n) + p * np.log(n)
        results[k] = {"ssr": ssr, "bic": bic, "breaks": breaks_for(k)}

    best_k = min(results, key=lambda kk: results[kk]["bic"]) if results else 0
    chosen = results.get(best_k, {"breaks": []})
    return {"best_k": best_k, "breaks": chosen["breaks"],
            "all": {str(k): {"n_breaks": k, "bic": v["bic"], "ssr": v["ssr"],
                             "breaks": v["breaks"]} for k, v in results.items()}}


def piecewise_demean(y: np.ndarray, breaks: list) -> np.ndarray:
    n = len(y)
    bnds = [0] + sorted(breaks) + [n]
    out = np.asarray(y, dtype=float).copy()
    for a, b in zip(bnds[:-1], bnds[1:]):
        if b > a:
            out[a:b] = y[a:b] - y[a:b].mean()
    return out


def latest_break(y: np.ndarray, min_seg: int = 60, look: int = 1000):
    """Fast single-break detector on trailing `look` obs; BIC-gated. In-sample only."""
    y = np.asarray(y, dtype=float)
    n = len(y)
    if n < 2 * min_seg:
        return None
    start = max(0, n - look)
    ys = y[start:]
    m = len(ys)
    S1, S2 = _seg_prefix(ys)

    def ssr(a, b):
        L = b - a + 1
        sy = S1[b + 1] - S1[a]
        sy2 = S2[b + 1] - S2[a]
        return sy2 - sy * sy / L

    base = ssr(0, m - 1)
    cand = np.arange(min_seg, m - min_seg)
    if len(cand) == 0:
        return None
    left = _seg_ssr_vec(S1, S2, cand - 1, m - 1)   # seg (cand..m-1)
    sy_l = S1[cand]
    sy2_l = S2[cand]
    ssr_pre = sy2_l - (sy_l ** 2) / cand           # seg (0..cand-1)
    tot = ssr_pre + left
    k = int(np.argmin(tot))
    ssr_split = tot[k]
    bic0 = m * np.log(base / m) + 1 * np.log(m)
    bic1 = m * np.log(ssr_split / m) + 3 * np.log(m)
    if bic1 < bic0:
        return start + int(cand[k])
    return None


# --------------------------------------------------------------------------- #
# HAR design
# --------------------------------------------------------------------------- #
def har_design(logrv: np.ndarray):
    n = len(logrv)
    daily = np.full(n, np.nan)
    weekly = np.full(n, np.nan)
    monthly = np.full(n, np.nan)
    for t in range(1, n):
        daily[t] = logrv[t - 1]
        if t >= 5:
            weekly[t] = logrv[t - 5:t].mean()
        if t >= 22:
            monthly[t] = logrv[t - 22:t].mean()
    X = np.column_stack([np.ones(n), daily, weekly, monthly])
    return X, np.asarray(logrv, dtype=float), 22


def ols_fit(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(1, X.shape[0] - X.shape[1])
    return beta, float(np.sum(resid ** 2) / dof)


# --------------------------------------------------------------------------- #
# OOS forecasting
# --------------------------------------------------------------------------- #
def run_oos(logrv: np.ndarray, rv: np.ndarray) -> dict:
    n = len(logrv)
    i0 = max(HAR_MINTRAIN + 22, n - OOS_TEST_N)
    origins = list(range(i0, n - 1))
    if len(origins) < 60:
        return {"error": "insufficient OOS window", "n": n}

    Xall, yall, _ = har_design(logrv)
    fc = {k: [] for k in ["HAR", "AR1", "ARFIMA", "BreakHAR", "EWMA"]}
    clip_hits = {k: 0 for k in fc}
    actual = []

    d_arf = None
    w_arf = None
    arf_mu = None
    arf_sig2 = 0.0
    brk_start = None
    # EWMA warm-up: fold in rv[0..i0-1] so that at origin i0 the state = forecast
    # for i0 (made at i0-1); the loop then advances it with rv[i] each step.
    ewma_var = float(rv[:i0].mean())
    for t in range(i0):
        ewma_var = EWMA_LAMBDA * ewma_var + (1 - EWMA_LAMBDA) * rv[t]

    for step, i in enumerate(origins):
        y_tr = logrv[0:i + 1]
        x_next = Xall[i + 1]  # regressors for target i+1 (strictly lagged)

        # in-sample log-variance support (clip forecasts to avoid pathological
        # extrapolation blowing up exp(); disclosed guard applied to all log models).
        # clip_hits tracks how often the guard actually binds per model, so we can
        # report whether QLIKE reflects raw model performance or the guard.
        lf_lo = float(np.min(y_tr)) - 1.0
        lf_hi = float(np.max(y_tr)) + 1.0

        def var_fc(logf, name):
            if logf < lf_lo or logf > lf_hi:
                clip_hits[name] += 1
            return float(np.exp(np.clip(logf, lf_lo, lf_hi)))

        # HAR
        rows = np.arange(22, i + 1)
        beta_h, sig2_h = ols_fit(Xall[rows], yall[rows])
        mu_h = float(x_next @ beta_h)
        fc["HAR"].append(var_fc(mu_h + 0.5 * sig2_h, "HAR"))

        # AR(1)
        y1 = logrv[1:i + 1]
        y0 = logrv[0:i]
        A = np.column_stack([np.ones(len(y0)), y0])
        b_ar, sig2_ar = ols_fit(A, y1)
        mu_ar = float(b_ar[0] + b_ar[1] * logrv[i])
        fc["AR1"].append(var_fc(mu_ar + 0.5 * sig2_ar, "AR1"))

        # ARFIMA(0,d,0): d via Exact Local Whittle (no silent LW fallback -- ELW
        # handles the non-stationary region and has been numerically robust; a
        # genuine failure should surface, not be masked)
        if (step % REEST_EVERY == 0) or (d_arf is None):
            m_lw = int(len(y_tr) ** 0.65)
            d_arf = float(np.clip(local_whittle(y_tr, m_lw, exact=True)["d"], -0.45, 0.95))
            arf_mu = float(y_tr.mean())
            K = min(FD_MAXK, i)
            w_arf = _fd_weights(d_arf, K)
            fd_tr = fracdiff(y_tr - arf_mu, d_arf)
            arf_sig2 = float(np.var(fd_tr[22:])) if len(fd_tr) > 40 else float(np.var(fd_tr))
        K = len(w_arf) - 1
        kmax = min(K, i + 1)
        hist = logrv[i + 1 - kmax:i + 1][::-1] - arf_mu  # y_i, y_{i-1}, ...
        contrib = float(np.dot(w_arf[1:kmax + 1], hist))
        mu_arf = arf_mu - contrib
        fc["ARFIMA"].append(var_fc(mu_arf + 0.5 * arf_sig2, "ARFIMA"))

        # Break-robust HAR (post-latest-break window)
        if (step % REEST_EVERY == 0) or (brk_start is None):
            lb = latest_break(logrv[:i + 1], min_seg=60, look=1000)
            brk_start = lb if lb is not None else max(0, i + 1 - 750)
        wstart = max(0, min(brk_start, i - 22 - 60))
        rows_b = np.arange(max(wstart, 22), i + 1)
        if len(rows_b) >= 60:
            beta_b, sig2_b = ols_fit(Xall[rows_b], yall[rows_b])
            mu_b = float(x_next @ beta_b)
            fc["BreakHAR"].append(var_fc(mu_b + 0.5 * sig2_b, "BreakHAR"))
        else:
            fc["BreakHAR"].append(var_fc(mu_h + 0.5 * sig2_h, "BreakHAR"))

        # EWMA (variance space)
        ewma_var = EWMA_LAMBDA * ewma_var + (1 - EWMA_LAMBDA) * rv[i]
        fc["EWMA"].append(ewma_var)

        actual.append(rv[i + 1])

    actual = np.array(actual)
    out = {"n_oos": len(actual), "models": {}}
    ql = {}
    for k, v in fc.items():
        pred = np.maximum(np.array(v), LOG_FLOOR)
        loss = qlike_pointwise(actual, pred)
        ql[k] = loss
        out["models"][k] = {"qlike_mean": float(np.mean(loss)),
                            "qlike_median": float(np.median(loss)),
                            "mse": float(np.mean((actual - pred) ** 2)),
                            "clip_hits": int(clip_hits[k]),
                            "clip_hit_rate": float(clip_hits[k] / len(actual))}
    out["dm_vs_HAR"] = {}
    for k in fc:
        if k == "HAR":
            continue
        t_hln, p_hln = dm_hln(ql[k], ql["HAR"], h=1)
        out["dm_vs_HAR"][k] = {"t_hln": t_hln, "p_value": p_hln,
                               "sign": "model_better" if np.mean(ql[k]) < np.mean(ql["HAR"]) else "HAR_better"}
    out["best_model_by_qlike"] = min(out["models"], key=lambda kk: out["models"][kk]["qlike_mean"])
    out["arfima_final_d"] = d_arf
    return out


def dm_hln(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1):
    """DM with Harvey-Leybourne-Newbold correction. Negative t => A better."""
    from scipy import stats
    d = np.asarray(loss_a) - np.asarray(loss_b)
    T = len(d)
    dbar = d.mean()
    gamma0 = np.sum((d - dbar) ** 2) / T
    var_d = gamma0
    for lag in range(1, h):
        cov = np.sum((d[lag:] - dbar) * (d[:-lag] - dbar)) / T
        var_d += 2 * (1 - lag / h) * cov
    dm = dbar / np.sqrt(var_d / T)
    corr = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    stat = dm * corr
    p = 2 * stats.t.sf(np.abs(stat), df=T - 1)
    return float(stat), float(p)


# --------------------------------------------------------------------------- #
# Per-asset analysis
# --------------------------------------------------------------------------- #
def demeaned_d_under_breaks(logrv, min_frac, max_breaks):
    """Break-granularity sensitivity: how much does d fall as we allow finer breaks?"""
    bp = bai_perron(logrv, max_breaks=max_breaks, min_frac=min_frac)
    dem = piecewise_demean(logrv, bp["breaks"])
    m = int(len(logrv) ** 0.60)
    e = local_whittle(dem, m, exact=True)
    return {"min_frac": min_frac, "max_breaks_cap": max_breaks,
            "n_breaks_selected": bp["best_k"], "d_demeaned_elw": e["d"],
            "d_ci": e["ci"], "sig_gt0": e["sig_gt0"]}


def classify_identification(d_raw, d_dem_bic, dem_bic_sig, d_perm, perm_sig) -> str:
    """
    Bracket the level-shift contribution between a parsimonious (BIC) lower bound
    and a permissive (fine-break) upper bound, following the two-sided Diebold-
    Inoue / Perron-Qu logic:
      - BIC breaks remove only a few big regime shifts   -> LOWER bound on shift share
      - fine breaks (up to 15) can over-absorb genuine LM -> UPPER bound on shift share
    A significant fractional d that survives even the permissive demeaning => a
    genuine long-memory component is present; the magnitude of the permissive drop
    grades how much of the apparent persistence is attributable to level shifts.
    """
    if not dem_bic_sig:
        return "level_shift_artifact"           # even a few breaks kill d
    if not (perm_sig and d_perm > 0.12):
        return "level_shift_dominant"           # fine breaks absorb ~all of d
    frac_drop_perm = (d_raw - d_perm) / d_raw if abs(d_raw) > 1e-6 else 0.0
    if frac_drop_perm < 0.25:
        return "genuine_long_memory_dominant"   # persistence robust to fine breaks
    if frac_drop_perm < 0.55:
        return "mixed_true_and_shifts"          # both contribute materially
    return "mixed_shifts_substantial"           # genuine LM survives but shifts explain most


def analyse_asset(ticker: str, kind: str, label: str, do_oos: bool = True) -> dict:
    t0 = time.time()
    df = load_ohlc(ticker)
    proxy = rv_proxy(df, kind)
    logrv = proxy["logrv"].to_numpy()
    rv = proxy["rv"].to_numpy()
    dates = proxy["date"].dt.strftime("%Y-%m-%d").to_numpy()
    n = len(logrv)
    res = {"ticker": ticker, "label": label, "kind": kind, "n": int(n),
           "period": [str(dates[0]), str(dates[-1])],
           "n_dropped_degenerate": int(proxy.attrs.get("n_dropped", 0))}

    ac = acf(logrv, nlags=100, fft=True)
    res["descriptive"] = {
        "logrv_mean": float(np.mean(logrv)), "logrv_std": float(np.std(logrv)),
        "logrv_skew": float(pd.Series(logrv).skew()), "logrv_kurt": float(pd.Series(logrv).kurt()),
        "acf_lag1": float(ac[1]), "acf_lag5": float(ac[5]),
        "acf_lag22": float(ac[22]), "acf_lag100": float(ac[100]),
        "acf_sum_1_100": float(np.sum(ac[1:101])),
    }

    bws = {"m_050": int(n ** 0.50), "m_060": int(n ** 0.60), "m_070": int(n ** 0.70)}
    raw = {"gph": {}, "lw": {}, "elw": {}}
    for name, m in bws.items():
        raw["gph"][name] = gph_estimator(logrv, m)
        raw["lw"][name] = local_whittle(logrv, m, exact=False)
        raw["elw"][name] = local_whittle(logrv, m, exact=True)
    res["d_raw"] = raw

    bp = bai_perron(logrv, max_breaks=5, min_frac=0.15)
    res["breaks"] = {
        "n_breaks": bp["best_k"], "break_indices": bp["breaks"],
        "break_dates": [str(dates[b]) for b in bp["breaks"]],
        "bic_by_m": {k: v["bic"] for k, v in bp["all"].items()},
    }

    demeaned = piecewise_demean(logrv, bp["breaks"])
    dem = {"gph": {}, "lw": {}, "elw": {}}
    for name, m in bws.items():
        dem["gph"][name] = gph_estimator(demeaned, m)
        dem["lw"][name] = local_whittle(demeaned, m, exact=False)
        dem["elw"][name] = local_whittle(demeaned, m, exact=True)
    res["d_break_demeaned"] = dem

    hb = "m_060"
    d_raw_elw = raw["elw"][hb]["d"]
    d_dem_elw = dem["elw"][hb]["d"]
    drop = d_raw_elw - d_dem_elw
    frac_drop = float(drop / d_raw_elw) if abs(d_raw_elw) > 1e-6 else float("nan")

    # Perron-Qu-style bandwidth stability: ELW d as m grows.
    # Genuine LM -> d ~ stable; level-shift low-freq contamination -> d falls with m.
    dm_seq = [raw["elw"]["m_050"]["d"], raw["elw"]["m_060"]["d"], raw["elw"]["m_070"]["d"]]
    bw_slope = float(dm_seq[2] - dm_seq[0])  # negative => decreasing (shift signature)
    if bw_slope < -0.08:
        bw_pattern = "decreasing_with_m (level-shift signature)"
    elif bw_slope > 0.08:
        bw_pattern = "increasing_with_m"
    else:
        bw_pattern = "stable (genuine-LM signature)"

    # Break-granularity sensitivity: parsimonious (BIC/0.15) vs permissive (0.05, fine)
    dem_perm = demeaned_d_under_breaks(logrv, min_frac=0.05, max_breaks=15)
    d_perm = dem_perm["d_demeaned_elw"]
    frac_drop_perm = float((d_raw_elw - d_perm) / d_raw_elw) if abs(d_raw_elw) > 1e-6 else float("nan")

    res["identification"] = {
        "headline_bandwidth": hb,
        "d_raw_elw": d_raw_elw, "d_raw_ci": raw["elw"][hb]["ci"],
        "d_break_demeaned_elw": d_dem_elw, "d_demeaned_ci": dem["elw"][hb]["ci"],
        "d_drop": drop, "d_drop_frac_bic": frac_drop,
        "demeaned_d_significant": bool(dem["elw"][hb]["sig_gt0"]),
        "bandwidth_d_sequence_elw": {"m050": dm_seq[0], "m060": dm_seq[1], "m070": dm_seq[2]},
        "bandwidth_slope": bw_slope, "bandwidth_pattern": bw_pattern,
        "demeaned_permissive_breaks": dem_perm,
        "shift_contribution_bracket": {
            "lower_bound_bic_frac": frac_drop,        # parsimonious breaks -> min share
            "upper_bound_permissive_frac": frac_drop_perm,  # fine breaks -> max share
            "interpretation": "fraction of raw fractional d attributable to level shifts, "
                              "bracketed by parsimonious (BIC) and permissive (15-break) models",
        },
        "verdict": classify_identification(
            d_raw_elw, d_dem_elw, dem["elw"][hb]["sig_gt0"], d_perm, dem_perm["sig_gt0"]),
        "note": "significance via asymptotic ELW SE=1/(2 sqrt(m)); block bootstrap "
                "invalid for long-memory inference and intentionally NOT used.",
    }

    if do_oos:
        res["oos"] = run_oos(logrv, rv)

    try:
        make_plots(label, logrv, dates, bp["breaks"], raw, res.get("oos"))
    except Exception as e:
        res["plot_error"] = str(e)

    res["runtime_sec"] = round(time.time() - t0, 1)
    return res


# --------------------------------------------------------------------------- #
# Plots
# --------------------------------------------------------------------------- #
def make_plots(label, logrv, dates, breaks, raw, oos):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    n = len(logrv)

    fig, ax = plt.subplots(figsize=(11, 3.2))
    ax.plot(np.arange(n), logrv, lw=0.5, color="#333")
    bnds = [0] + sorted(breaks) + [n]
    for a, b in zip(bnds[:-1], bnds[1:]):
        ax.hlines(logrv[a:b].mean(), a, b, color="crimson", lw=1.8)
    for b in breaks:
        ax.axvline(b, color="crimson", ls="--", lw=0.8, alpha=0.6)
    ax.set_title(f"{label}: log-RV proxy with Bai-Perron level breaks (n={n})")
    ax.set_xlabel("obs"); ax.set_ylabel("log RV")
    fig.tight_layout(); fig.savefig(PLOTS / f"{label}_levelbreaks.png", dpi=110); plt.close(fig)

    ac = acf(logrv, nlags=120, fft=True)
    fig, ax = plt.subplots(figsize=(7, 3.2))
    ax.bar(np.arange(len(ac)), ac, color="#3b6ea5", width=0.9)
    ax.axhline(2 / np.sqrt(n), color="gray", ls=":", lw=0.8)
    ax.set_title(f"{label}: ACF of log-RV (slow decay = apparent long memory)")
    ax.set_xlabel("lag"); ax.set_ylabel("ACF")
    fig.tight_layout(); fig.savefig(PLOTS / f"{label}_acf.png", dpi=110); plt.close(fig)

    m = raw["gph"]["m_060"]["m"]
    I = periodogram(logrv)
    j = np.arange(1, m + 1)
    lam = 2 * np.pi * j / n
    X = np.log(4 * np.sin(lam / 2) ** 2)
    Y = np.log(np.maximum(I[1:m + 1], 1e-300))
    d = raw["gph"]["m_060"]["d"]
    fig, ax = plt.subplots(figsize=(6.5, 3.6))
    ax.scatter(X, Y, s=6, alpha=0.4, color="#666")
    b0 = Y.mean() + d * X.mean()
    ax.plot(X, b0 - d * X, color="crimson", lw=1.6, label=f"GPH slope: d={d:.3f}")
    ax.set_title(f"{label}: log-periodogram (GPH, m={m})")
    ax.set_xlabel("log(4 sin^2(lambda/2))"); ax.set_ylabel("log I(lambda)")
    ax.legend()
    fig.tight_layout(); fig.savefig(PLOTS / f"{label}_periodogram.png", dpi=110); plt.close(fig)

    if oos and "models" in oos:
        mods = list(oos["models"].keys())
        qs = [oos["models"][mm]["qlike_mean"] for mm in mods]
        fig, ax = plt.subplots(figsize=(6.5, 3.4))
        colors = ["#d1495b" if mm == oos.get("best_model_by_qlike") else "#3b6ea5" for mm in mods]
        ax.bar(mods, qs, color=colors)
        ax.set_title(f"{label}: OOS mean QLIKE (n={oos.get('n_oos')}), lower=better")
        ax.set_ylabel("mean QLIKE")
        for i2, q in enumerate(qs):
            ax.text(i2, q, f"{q:.3f}", ha="center", va="bottom", fontsize=8)
        fig.tight_layout(); fig.savefig(PLOTS / f"{label}_oos_qlike.png", dpi=110); plt.close(fig)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    t_start = time.time()
    core = ASSETS[:3]
    extras = ASSETS[3:]
    results = {
        "experiment_id": "K1623",
        "title": "RV persistence: true long memory vs level-shift artifact",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "db_path": str(DB),
        "config": {
            "rv_proxy": "Parkinson HL range variance (range assets); (VIX/100)^2 (VIX)",
            "estimators": ["GPH (log-periodogram)", "Local Whittle", "Exact Local Whittle (Shimotsu-Phillips)"],
            "bandwidths": ["T^0.50", "T^0.60", "T^0.70"],
            "breaks": "Bai-Perron mean shifts, max_breaks=5, trim=0.15, BIC-selected",
            "oos": {"scheme": "expanding one-step", "test_n": OOS_TEST_N,
                    "models": ["HAR", "AR1", "ARFIMA(0,d,0)", "BreakRobustHAR", "EWMA(0.94)"],
                    "loss": "QLIKE (canonical actual/pred) + MSE",
                    "test": "DM with Harvey-Leybourne-Newbold correction, h=1",
                    "reest_every": REEST_EVERY,
                    "forecast_guard": "log-variance forecast clipped to in-sample "
                                      "[min-1, max+1] to prevent exp() blow-ups"},
            "inference": "d significance via asymptotic ELW/GPH SE (block bootstrap "
                         "deliberately avoided: invalid for long-memory series)",
            "break_granularity_sensitivity": "demeaned d re-estimated under permissive "
                                             "(min_frac=0.05, up to 15 breaks) vs BIC/0.15",
        },
        "assets": {},
    }

    for tk, kind, label in core:
        print(f"[{label}] analysing ...", flush=True)
        results["assets"][label] = analyse_asset(tk, kind, label, do_oos=True)
        r = results["assets"][label]
        print(f"[{label}] done {r['runtime_sec']}s verdict={r['identification']['verdict']} "
              f"d_raw={r['identification']['d_raw_elw']:.3f} d_dem={r['identification']['d_break_demeaned_elw']:.3f}",
              flush=True)

    for tk, kind, label in extras:
        if time.time() - t_start > 40 * 60:
            print(f"[{label}] SKIPPED (time budget)", flush=True)
            results["assets"][label] = {"skipped": "time_budget"}
            continue
        print(f"[{label}] analysing (extra) ...", flush=True)
        results["assets"][label] = analyse_asset(tk, kind, label, do_oos=True)
        print(f"[{label}] done verdict={results['assets'][label]['identification']['verdict']}", flush=True)

    summary = {}
    for label, r in results["assets"].items():
        if "identification" not in r:
            continue
        summary[label] = {
            "n": r["n"], "period": r["period"],
            "d_raw_elw": r["identification"]["d_raw_elw"],
            "d_demeaned_elw": r["identification"]["d_break_demeaned_elw"],
            "d_drop": r["identification"]["d_drop"],
            "n_breaks": r["breaks"]["n_breaks"],
            "verdict": r["identification"]["verdict"],
            "oos_best": r.get("oos", {}).get("best_model_by_qlike"),
            "oos_dm_ARFIMA_vs_HAR": r.get("oos", {}).get("dm_vs_HAR", {}).get("ARFIMA"),
            "oos_dm_BreakHAR_vs_HAR": r.get("oos", {}).get("dm_vs_HAR", {}).get("BreakHAR"),
        }
    results["cross_asset_summary_diagnostic"] = summary
    results["total_runtime_sec"] = round(time.time() - t_start, 1)

    out_path = HERE / "k1623_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=float)
    print(f"\nSaved -> {out_path}  (total {results['total_runtime_sec']}s)")
    print("\n=== IDENTIFICATION SUMMARY (per-asset, no pooling) ===")
    for label, s in summary.items():
        print(f"{label:8s} n={s['n']:5d} d_raw={s['d_raw_elw']:.3f} "
              f"d_dem={s['d_demeaned_elw']:.3f} drop={s['d_drop']:+.3f} "
              f"breaks={s['n_breaks']} -> {s['verdict']:22s} OOS_best={s['oos_best']}")


if __name__ == "__main__":
    main()
