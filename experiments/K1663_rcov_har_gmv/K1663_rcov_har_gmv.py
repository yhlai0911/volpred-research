"""
K1663 — Realized-Covariance HAR → Global-Minimum-Variance (GMV) portfolio OOS test
==================================================================================

Question
--------
Does modelling the *covariance matrix* with a HAR structure (Cholesky-HAR of a
daily realized-covariance proxy) build a lower-variance GMV portfolio out-of-sample
than standard covariance estimators (rolling sample cov, RiskMetrics EWMA,
Ledoit-Wolf shrinkage)?

Honesty / proxy disclosure
--------------------------
We ONLY have daily data.  A *true* high-frequency realized covariance is
unavailable.  Our daily "realized covariance" is therefore a 22-day ROLLING
SAMPLE COVARIANCE (RCov_t = Cov of returns over [t-21, t]).  This is a noisy,
smoothed proxy — NOT an intraday RCov.  All conclusions are framed as
"covariance-construction methods under daily data for GMV", we do NOT claim to
reproduce high-frequency realized-covariance-HAR results (Chiriac-Voev 2011 etc.).

Lookahead defences (highest priority risk)
------------------------------------------
* Every covariance forecast Sigma_hat for portfolio day t uses ONLY information
  dated <= t-1 (origin = end of day t-1).
* HAR betas are refit on an EXPANDING window whose training targets end at the
  origin (t-1); the forecast target (t) is never in the training set.
* Rolling RCov windows only look backwards.
* Portfolio weights w_t (from Sigma_hat built with data <= t-1) are realised on
  return r_t of day t  ->  explicit one-day lag (weights.shift(1) equivalent).
* Baselines and HAR share the SAME lag convention.

Reproducibility: fixed seed; no stochastic step actually needs it (Ledoit-Wolf and
OLS are deterministic) but the seed is fixed for defensiveness.

Author: VolPred autonomous research (Claude), 2026-07-09.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize
from sklearn.covariance import LedoitWolf

SEED = 20260709
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_CSV = HERE / "data" / "prices.csv"

TICKERS = ["SPY", "QQQ", "GLD", "TLT", "IWM"]
N = len(TICKERS)

# --- covariance / model windows ---------------------------------------------
RCOV_WIN = 22        # daily realized-cov proxy = 22-day rolling sample cov
LW_WIN = 252         # Ledoit-Wolf estimation window (1y)
EWMA_LAMBDA = 0.94   # RiskMetrics
HAR_REFIT_EVERY = 21 # refit HAR betas every ~month (expanding window)
BURN_IN = 756        # ~3y burn-in before first OOS portfolio day
ANN = 252            # annualisation factor
RIDGE = 1e-10        # tiny ridge added before matrix inversion (numerical safety)
CHOL_DIAG_FLOOR = 1e-5  # floor on reconstructed Cholesky diagonal (PD guarantee)

# lower-triangular (incl diagonal) index pairs, row-major
TRI = [(i, j) for i in range(N) for j in range(i + 1)]
M = len(TRI)  # = N(N+1)/2 = 15


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_returns() -> pd.DataFrame:
    px = pd.read_csv(DATA_CSV, index_col=0, parse_dates=True)[TICKERS].sort_index()
    # simple returns: portfolio return = w . r is exact only for simple returns
    rets = px.pct_change().dropna()
    return rets


# ---------------------------------------------------------------------------
# Daily realized-covariance proxy (22d rolling sample cov) + Cholesky vec
# ---------------------------------------------------------------------------
def rolling_rcov(R: np.ndarray, win: int) -> list:
    """RCov_t for t = win-1 .. T-1 (window [t-win+1, t]); earlier entries None."""
    T = R.shape[0]
    out = [None] * T
    for t in range(win - 1, T):
        w = R[t - win + 1 : t + 1]
        out[t] = np.cov(w, rowvar=False, ddof=1)
    return out


def chol_vec(Sigma: np.ndarray) -> np.ndarray:
    """Lower-triangular Cholesky factor -> flat vector of the M free elements."""
    L = np.linalg.cholesky(Sigma + RIDGE * np.eye(N))
    return np.array([L[i, j] for (i, j) in TRI])


def vec_to_sigma(v: np.ndarray) -> np.ndarray:
    """Rebuild Sigma = L L' from a Cholesky vec, flooring the diagonal for PD."""
    L = np.zeros((N, N))
    for k, (i, j) in enumerate(TRI):
        L[i, j] = v[k]
    # floor diagonal so L is a valid (strictly PD) Cholesky factor
    for i in range(N):
        if L[i, i] < CHOL_DIAG_FLOOR:
            L[i, i] = CHOL_DIAG_FLOOR
    return L @ L.T


# ---------------------------------------------------------------------------
# HAR feature construction on the Cholesky-vec series
# ---------------------------------------------------------------------------
def har_features(C: np.ndarray):
    """
    C : (T, M) Cholesky-vec series (rows before first valid RCov are NaN).
    Returns lagged HAR regressors, each shifted so that the row-t feature uses
    ONLY data dated <= t-1:
        Xd = C_{t-1}                      (daily)
        Xw = mean(C_{t-5 .. t-1})         (weekly)
        Xm = mean(C_{t-22 .. t-1})        (monthly)
    """
    dfC = pd.DataFrame(C)
    Xd = dfC.shift(1)
    Xw = dfC.rolling(5).mean().shift(1)
    Xm = dfC.rolling(22).mean().shift(1)
    return Xd.values, Xw.values, Xm.values


# ---------------------------------------------------------------------------
# GMV portfolios
# ---------------------------------------------------------------------------
def gmv_long_short(Sigma: np.ndarray) -> np.ndarray:
    Sinv = np.linalg.inv(Sigma + RIDGE * np.eye(N))
    ones = np.ones(N)
    w = Sinv @ ones
    return w / (ones @ w)


def gmv_no_short(Sigma: np.ndarray) -> np.ndarray:
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bnds = [(0.0, 1.0)] * N
    w0 = np.ones(N) / N
    res = minimize(
        lambda w: float(w @ Sigma @ w),
        w0,
        method="SLSQP",
        bounds=bnds,
        constraints=cons,
        options={"maxiter": 200, "ftol": 1e-12},
    )
    w = np.clip(res.x, 0.0, None)
    s = w.sum()
    return w / s if s > 0 else np.ones(N) / N


# ---------------------------------------------------------------------------
# Diebold-Mariano test w/ Newey-West HAC + Harvey-Leybourne-Newbold correction
# ---------------------------------------------------------------------------
def dm_hln(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1):
    """
    d_t = loss_a - loss_b.  Negative dbar => method A has LOWER loss (better).
    HAC (Newey-West, Bartlett) with automatic bandwidth + HLN small-sample fix.
    Returns (dm_stat, p_value, nw_lag, dbar).
    """
    d = np.asarray(loss_a) - np.asarray(loss_b)
    T = len(d)
    dbar = d.mean()
    L = int(np.floor(4 * (T / 100.0) ** (2.0 / 9.0)))
    L = max(L, h - 1)
    dc = d - dbar
    gamma0 = np.mean(dc * dc)
    var = gamma0
    for k in range(1, L + 1):
        wk = 1.0 - k / (L + 1.0)
        cov = np.mean(dc[k:] * dc[:-k])
        var += 2.0 * wk * cov
    var_dbar = var / T
    if var_dbar <= 0:
        return float("nan"), float("nan"), L, float(dbar)
    dm = dbar / np.sqrt(var_dbar)
    corr = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    dm_c = dm * corr
    p = 2.0 * stats.t.sf(abs(dm_c), df=T - 1)
    return float(dm_c), float(p), int(L), float(dbar)


# ---------------------------------------------------------------------------
# Covariance forecasters -> one Sigma_hat for portfolio day t (info <= t-1)
# ---------------------------------------------------------------------------
def build_forecasts(R: np.ndarray, rcov: list, C: np.ndarray):
    """
    For each portfolio day t in [BURN_IN, T-1] produce Sigma_hat_t for every
    method, using ONLY information dated <= t-1 (origin tau = t-1).
    Returns dict: method -> list of (t, Sigma_hat).
    """
    T = R.shape[0]
    Xd, Xw, Xm = har_features(C)

    # design matrix per row (constant + 3 HAR regressors) is element-specific in
    # its columns; we fit M independent OLS regressions sharing the same rows.
    # target for row t is C[t]; regressors use Xd/Xw/Xm[t] (all <= t-1 data).
    valid_rows = np.array(
        [t for t in range(T) if not np.isnan(C[t]).any() and not np.isnan(Xm[t]).any()]
    )

    # --- pre-compute EWMA covariance path (recursive, causal) ---------------
    # Sigma_ewma[t] uses returns up to and including day t.
    ewma_path = [None] * T
    init_win = R[:RCOV_WIN]
    S = np.cov(init_win, rowvar=False, ddof=1)
    for t in range(T):
        r = R[t].reshape(-1, 1)
        S = EWMA_LAMBDA * S + (1.0 - EWMA_LAMBDA) * (r @ r.T)
        ewma_path[t] = S.copy()

    methods = {k: [] for k in ["har_chol", "rolling", "ewma", "ledoit_wolf"]}

    # cache for HAR betas (refit every HAR_REFIT_EVERY days on expanding window)
    betas = None  # shape (M, 4)
    last_fit = -10**9

    for t in range(BURN_IN, T):
        tau = t - 1  # origin: last usable day

        # ---- HAR-Cholesky ---------------------------------------------------
        # refit betas on training rows s <= tau (target C[s] uses data <= s <= tau)
        if betas is None or (tau - last_fit) >= HAR_REFIT_EVERY:
            train = valid_rows[valid_rows <= tau]
            if len(train) >= 60:
                ones = np.ones(len(train))
                B = np.empty((M, 4))
                for k in range(M):
                    Xk = np.column_stack(
                        [ones, Xd[train, k], Xw[train, k], Xm[train, k]]
                    )
                    yk = C[train, k]
                    beta, *_ = np.linalg.lstsq(Xk, yk, rcond=None)
                    B[k] = beta
                betas = B
                last_fit = tau
        # forecast C_hat for day t from features at row t (<= t-1 data)
        if betas is not None and not np.isnan(Xm[t]).any():
            feat = np.column_stack([np.ones(M), Xd[t], Xw[t], Xm[t]])  # (M,4)
            c_hat = np.einsum("ij,ij->i", feat, betas)
            sigma_har = vec_to_sigma(c_hat)
            methods["har_chol"].append((t, sigma_har))
        else:
            methods["har_chol"].append((t, rcov[tau]))  # fallback: last RCov

        # ---- rolling sample cov (random-walk of RCov) ----------------------
        methods["rolling"].append((t, rcov[tau]))

        # ---- EWMA (RiskMetrics) --------------------------------------------
        methods["ewma"].append((t, ewma_path[tau]))

        # ---- Ledoit-Wolf shrinkage -----------------------------------------
        win = R[tau - LW_WIN + 1 : tau + 1]
        lw = LedoitWolf().fit(win)
        methods["ledoit_wolf"].append((t, lw.covariance_))

    return methods


# ---------------------------------------------------------------------------
# Run portfolios for a set of Sigma-forecasts
# ---------------------------------------------------------------------------
def run_portfolio(forecasts, R: np.ndarray, gmv_fn):
    """forecasts: list of (t, Sigma_hat).  Returns (dates_idx, port_ret, weights)."""
    idx, prets, W = [], [], []
    for (t, Sigma) in forecasts:
        w = gmv_fn(Sigma)
        pr = float(w @ R[t])  # weights from <=t-1, realised on day-t return
        idx.append(t)
        prets.append(pr)
        W.append(w)
    return np.array(idx), np.array(prets), np.array(W)


def metrics(pret: np.ndarray, W: np.ndarray) -> dict:
    ann_vol = float(np.std(pret, ddof=1) * np.sqrt(ANN))
    ann_ret = float(np.mean(pret) * ANN)
    sharpe = float(np.mean(pret) / np.std(pret, ddof=1) * np.sqrt(ANN))
    turn = float(np.mean(np.sum(np.abs(np.diff(W, axis=0)), axis=1)))
    # max weight / min weight to characterise concentration & shorting
    return {
        "ann_vol": ann_vol,
        "ann_ret": ann_ret,
        "sharpe": sharpe,
        "avg_daily_turnover": turn,
        "max_weight": float(W.max()),
        "min_weight": float(W.min()),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    rets = load_returns()
    R = rets.values
    T = R.shape[0]
    print(f"[data] {TICKERS}  {rets.index.min().date()}..{rets.index.max().date()}  rows={T}")

    rcov = rolling_rcov(R, RCOV_WIN)
    C = np.full((T, M), np.nan)
    for t in range(T):
        if rcov[t] is not None:
            C[t] = chol_vec(rcov[t])

    print("[build] forecasting Sigma_hat for every OOS day / method ...")
    fc = build_forecasts(R, rcov, C)

    method_labels = {
        "har_chol": "HAR-Cholesky (RCov proxy)",
        "rolling": f"Rolling sample cov ({RCOV_WIN}d)",
        "ewma": f"EWMA RiskMetrics (lambda={EWMA_LAMBDA})",
        "ledoit_wolf": f"Ledoit-Wolf shrinkage ({LW_WIN}d)",
    }

    results = {
        "experiment_id": "K1663_rcov_har_gmv",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "tickers": TICKERS,
        "data_period": {
            "start": str(rets.index.min().date()),
            "end": str(rets.index.max().date()),
            "total_days": int(T),
        },
        "config": {
            "rcov_window": RCOV_WIN,
            "ledoit_wolf_window": LW_WIN,
            "ewma_lambda": EWMA_LAMBDA,
            "har_refit_every": HAR_REFIT_EVERY,
            "burn_in": BURN_IN,
            "annualisation": ANN,
            "rcov_proxy": "22-day rolling sample covariance of daily simple returns (NOT high-frequency RCov)",
        },
        "constraints": {},
    }

    oos_n = None
    oos_period = None

    for cname, gmv_fn in [("long_short", gmv_long_short), ("no_short", gmv_no_short)]:
        print(f"[portfolio] GMV constraint = {cname}")
        port = {}
        for m in fc:
            idx, pret, W = run_portfolio(fc[m], R, gmv_fn)
            port[m] = {"idx": idx, "pret": pret, "W": W, "metrics": metrics(pret, W)}

        # equal-weight 1/N reference on the SAME OOS window
        ref_idx = port["rolling"]["idx"]
        ew_pret = R[ref_idx].mean(axis=1)
        ew_W = np.tile(np.ones(N) / N, (len(ref_idx), 1))
        port["equal_weight"] = {
            "idx": ref_idx, "pret": ew_pret, "W": ew_W,
            "metrics": metrics(ew_pret, ew_W),
        }

        if oos_n is None:
            oos_n = int(len(ref_idx))
            oos_period = {
                "start": str(rets.index[ref_idx[0]].date()),
                "end": str(rets.index[ref_idx[-1]].date()),
                "oos_days": oos_n,
            }

        # DM (Engle-Colacito): loss = squared GMV portfolio return
        dm = {}
        base_har = port["har_chol"]["pret"] ** 2
        for m in ["rolling", "ewma", "ledoit_wolf"]:
            lb = port[m]["pret"] ** 2
            stat, p, lag, dbar = dm_hln(base_har, lb, h=1)
            dm[f"har_vs_{m}"] = {
                "dm_stat": stat, "p_value": p, "nw_lag": lag,
                "mean_loss_diff": dbar,
                "interpret": ("HAR lower var" if dbar < 0 else "HAR higher var")
                + (" (sig@5%)" if (p == p and p < 0.05) else " (NS)"),
            }

        results["constraints"][cname] = {
            "metrics": {m: port[m]["metrics"] for m in port},
            "dm_engle_colacito": dm,
        }

    results["oos_period"] = oos_period
    results["method_labels"] = method_labels

    # ---- console summary ---------------------------------------------------
    print("\n==== OOS GMV summary (long_short) ====")
    ls = results["constraints"]["long_short"]["metrics"]
    hdr = f"{'method':30s} {'annVol':>8s} {'turnover':>9s} {'sharpe':>7s} {'maxW':>6s} {'minW':>6s}"
    print(hdr)
    for m in ["har_chol", "rolling", "ewma", "ledoit_wolf", "equal_weight"]:
        mm = ls[m]
        print(f"{method_labels.get(m, m):30s} {mm['ann_vol']*100:7.3f}% "
              f"{mm['avg_daily_turnover']:9.4f} {mm['sharpe']:7.3f} "
              f"{mm['max_weight']:6.2f} {mm['min_weight']:6.2f}")
    print("\nDM (Engle-Colacito, HAR vs baseline, neg=HAR better):")
    for k, v in results["constraints"]["long_short"]["dm_engle_colacito"].items():
        print(f"  {k:22s} dm={v['dm_stat']:+.3f} p={v['p_value']:.3f} -> {v['interpret']}")

    out = HERE / "K1663_rcov_har_gmv_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=lambda o: float(o) if isinstance(o, np.floating) else o)
    print(f"\n[saved] {out}")

    # stash per-day series for plotting (not part of the canonical results json)
    np.savez(
        HERE / "_series.npz",
        idx=port["rolling"]["idx"],
        dates=np.array([str(rets.index[i].date()) for i in port["rolling"]["idx"]]),
        **{f"pret_{m}": results_series(fc, R, m) for m in fc},
    )
    return results


def results_series(fc, R, m):
    # recompute long-short port returns for plotting series
    idx, pret, W = run_portfolio(fc[m], R, gmv_long_short)
    return pret


if __name__ == "__main__":
    main()
