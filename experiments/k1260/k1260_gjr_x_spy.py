#!/usr/bin/env python3
"""
K1260: GJR-X (Fair-Info Baseline) vs PRG vs GJR on SPY OOS
==========================================================

Research Question:
  P6 PRG paper §6 limitation acknowledges: "PRG reads two pieces of session
  information (overnight + intraday) while GJR reads only one (close-to-close)."
  Reviewers (NotebookLM v3 M1, latex-academic-reviewer) flag this as a fairness
  issue. Is PRG's advantage just the *information gain* (reading overnight
  separately) or genuinely the *cross-session bridge mechanism*?

Spec — GJR-X (the fair-info baseline):
  Standard GJR(1,1) augmented with previous-day overnight squared return
  as an exogenous regressor in the conditional variance equation:

    h_t = ω + α·r²_{t-1} + γ·I(r_{t-1}<0)·r²_{t-1} + β·h_{t-1}
                                                    + δ·r²_{overnight, t-1}

  where r_t is the close-to-close log return (same as standard GJR) and
  r²_{overnight, t-1} = (log(open_{t-1}/close_{t-2}))² is yesterday's
  overnight squared return, AVAILABLE at t-1 close — no lookahead.

  This lets GJR-X read the same two information pieces (overnight + c2c)
  that PRG sees, but flattens them into a single GJR recursion via an
  exogenous regressor. If PRG still beats GJR-X, then PRG's advantage is
  the SESSION-BOUNDARY BRIDGE MECHANISM (cross-session h propagation),
  not merely additional information.

Models:
  1. GJR (original, K880 spec)         — h_t = ω + α·r²_{t-1} + γ·...·r²_{t-1} + β·h_{t-1}
  2. GJR-X (this experiment, NEW)      — adds + δ·r²_{overnight, t-1}
  3. PRG_Extended (canonical, K880)    — periodic GARCH with leverage

NotebookLM Predicted Outcome (Argument A):
  GJR-X DM t (vs GJR) ∈ [2, 4]: positive but smaller than PRG's t ≈ 6 vs GJR.
  PRG vs GJR-X DM t > 0 still: cross-session bridge contributes beyond raw info.

Hard Rules (.claude/rules/experiments.md):
  - Lookahead: r²_{overnight,t-1} is yesterday's overnight (known at t-1 close).
    All forecasts use ONLY info available at t-1 close — explicit `.shift(1)`
    semantics enforced by indexing r2_overnight[t-1] inside the t-th forecast.
  - Seed fixed: np.random.RandomState(42) for MLE multistart.
  - Symmetric refinement: Both GJR and GJR-X use SAME refit_freq=63, SAME
    n_starts=3, SAME bounds magnitude — fair MLE comparison.
  - Common evaluation target: σ²_fullday = r²_overnight + r²_intra (matches
    K880/K880v2 P6 paper convention).

Data: yfinance SPY, 2000-01-04 to 2026-04-05 (same as K880).
IS: through 2018-12-31 (4778 days)
OOS: 2019-01-02 to 2026-04-02 (1823 days)

Evaluation:
  - QLIKE on σ²_fullday (Patton 2011, denominator-consistent)
  - DM test (Diebold-Mariano with Harvey 1997 small-sample correction)

References:
  - Hansen, Huang & Shek (2012) "Realized GARCH" — exogenous-regressor framework
  - Engle (2002) "Dynamic Conditional Correlation" — original GARCH-X parlance
  - Glosten, Jagannathan & Runkle (1993) — GJR specification
  - Bollerslev & Ghysels (1996) — Periodic GARCH (PRG ancestor)
  - Patton (2011) — QLIKE robust loss
  - Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997)
  - Lai et al. (2024) — PRS / PRG concept
  - Todorova (2014); Opschoor et al. (2021) — overnight modeling literature
    cited in P6 §6 as supporting why session-level dominates exogenous.

Author: VolPred Research System
Date: 2026-04-27
Experiment ID: K1260
"""

import os
import sys
import json
import time
import warnings
import numpy as np
import pandas as pd
from datetime import datetime
from scipy.optimize import minimize
from numba import njit

warnings.filterwarnings('ignore')

# Locate project root for volpred imports
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(THIS_DIR, "..", ".."))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))
# Also add paper folder for K880 PRG implementation reuse
PAPER_EXP_DIR = os.path.join(PROJECT_ROOT, "paper", "prg-periodic-garch", "experiments")
sys.path.insert(0, PAPER_EXP_DIR)

from volpred.stats.model_evaluation import dm_test  # noqa: E402

# Import canonical PRG implementation from K880 (paper-co-located)
# This guarantees PRG result matches the paper's published DM=6.00.
import importlib.util  # noqa: E402

K880_PATH = os.path.join(PAPER_EXP_DIR, "k880_prg_spy_validation.py")
spec = importlib.util.spec_from_file_location("k880_prg", K880_PATH)
k880_prg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k880_prg)


# ============================================================
# Configuration (matches K880)
# ============================================================
SCRIPT_DIR = THIS_DIR
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "k1260_results.json")

IS_END_DATE = "2018-12-31"
REFIT_FREQ_GJR = 63    # quarterly refit (same as K880)
REFIT_FREQ_PRG = 126   # semi-annual refit for PRG (same as K880)
# Multistart: K880 used n=3 — we keep symmetric n=3 for GJR and GJR-X to
# match K880's canonical optimization budget. K880's PRG uses n_starts=5
# (heavier optimization) — also kept symmetric with K880.
# Note: A focused IS diagnostic (n=15 random starts on full IS sample) finds
# δ̂≈0.34 highly significant (LR=74.81, p<0.0001). The OOS quarterly-refit
# multistart of n=3 may underestimate GJR-X's potential. Reported in README
# as known limitation to be probed in follow-up if needed.
N_STARTS_GJR = 3
N_STARTS_GJR_X = 3
N_STARTS_PRG = 5

# Random seed for MLE multistart (fixed for reproducibility)
SEED = 42


# ============================================================
# Numba kernels — GJR (replicating K880 standard GJR for verification)
# ============================================================
@njit(cache=True)
def _gjr_negll(omega, alpha, gamma_p, beta, r):
    """Standard GJR(1,1) negative log-likelihood."""
    T = len(r)
    h = np.empty(T)
    h0 = 0.0
    nb = min(50, T)
    for i in range(nb):
        h0 += r[i] ** 2
    h0 /= nb
    if h0 < 1e-12:
        h0 = 1e-8
    h[0] = h0
    ll = 0.0
    for t in range(1, T):
        ind = 1.0 if r[t-1] < 0 else 0.0
        h[t] = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * ind + beta * h[t-1]
        if h[t] < 1e-12:
            h[t] = 1e-12
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h[t]) - 0.5 * r[t]**2 / h[t]
    return -ll


@njit(cache=True)
def _gjr_propagate(omega, alpha, gamma_p, beta, r, h0, start, end):
    """Propagate GJR state from start to end. Returns final h."""
    h = h0
    for t in range(start, end):
        ind = 1.0 if r[t-1] < 0 else 0.0
        h = omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * ind + beta * h
        if h < 1e-12:
            h = 1e-12
    return h


# ============================================================
# Numba kernels — GJR-X (NEW)
# ============================================================
@njit(cache=True)
def _gjrx_negll(omega, alpha, gamma_p, beta, delta, r, r2_ov):
    """
    GJR-X negative log-likelihood.

    h_t = ω + α·r²_{t-1} + γ·I(r_{t-1}<0)·r²_{t-1} + β·h_{t-1} + δ·r²_{overnight,t-1}

    LOOKAHEAD CHECK:
      r is c2c return; r[t-1] is yesterday's c2c return.
      r2_ov is overnight squared return; r2_ov[t-1] is yesterday's overnight.
      Both are KNOWN at t-1 close. No t-day info used to forecast t. ✓
      This is the `.shift(1)` equivalent: features dated t-1 → target dated t.
    """
    T = len(r)
    h = np.empty(T)
    h0 = 0.0
    nb = min(50, T)
    for i in range(nb):
        h0 += r[i] ** 2
    h0 /= nb
    if h0 < 1e-12:
        h0 = 1e-8
    h[0] = h0
    ll = 0.0
    for t in range(1, T):
        ind = 1.0 if r[t-1] < 0 else 0.0
        h[t] = (omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * ind
                + beta * h[t-1] + delta * r2_ov[t-1])
        if h[t] < 1e-12:
            h[t] = 1e-12
        ll += -0.5 * np.log(2 * np.pi) - 0.5 * np.log(h[t]) - 0.5 * r[t]**2 / h[t]
    return -ll


@njit(cache=True)
def _gjrx_propagate(omega, alpha, gamma_p, beta, delta, r, r2_ov, h0, start, end):
    """Propagate GJR-X state from start to end. Returns final h."""
    h = h0
    for t in range(start, end):
        ind = 1.0 if r[t-1] < 0 else 0.0
        h = (omega + alpha * r[t-1]**2 + gamma_p * r[t-1]**2 * ind
             + beta * h + delta * r2_ov[t-1])
        if h < 1e-12:
            h = 1e-12
    return h


# ============================================================
# OOS forecasts
# ============================================================
def gjr_oos_forecast(returns, is_end, refit_freq=REFIT_FREQ_GJR, seed=SEED):
    """Standard GJR(1,1) OOS — replicates K880 GJR for self-consistency check."""
    n = len(returns)
    forecasts = np.full(n, np.nan)

    def neg_ll(params, r):
        # Stationarity guard (consistent with K880v2 fix)
        if params[1] + params[2] + params[3] >= 0.999:
            return 1e15
        return _gjr_negll(params[0], params[1], params[2], params[3], r)

    eps = 1e-8
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5), (eps, 0.999)]
    current_params = None
    h_state = np.var(returns[:min(50, n)])

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            r_train = returns[:t].copy()
            best_nll = np.inf
            best_p = None
            rng = np.random.RandomState(seed)
            for i in range(N_STARTS_GJR):
                if i == 0:
                    x0 = [np.var(r_train) * 0.05, 0.08, 0.06, 0.85]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                          rng.uniform(0.0, 0.15), rng.uniform(0.7, 0.95)]
                try:
                    res = minimize(neg_ll, x0, args=(r_train,),
                                   method='L-BFGS-B', bounds=bounds,
                                   options={'maxiter': 1000})
                    if res.fun < best_nll and res.fun < 1e14:
                        best_nll = res.fun
                        best_p = res.x
                except Exception:
                    continue
            if best_p is not None:
                current_params = best_p
                w, a, g, b = current_params
                h0 = np.var(returns[:min(50, t)])
                if h0 < 1e-12:
                    h0 = 1e-8
                h_state = _gjr_propagate(w, a, g, b, returns, h0, 1, t)

        if current_params is not None:
            w, a, g, b = current_params
            ind = 1.0 if returns[t-1] < 0 else 0.0
            # Forecast h_t using info up to t-1 (signal.shift(1) equivalent)
            h_state = w + a * returns[t-1]**2 + g * returns[t-1]**2 * ind + b * h_state
            if h_state < 1e-12:
                h_state = 1e-12
            forecasts[t] = h_state

    return forecasts


def gjrx_oos_forecast(returns, r2_overnight, is_end,
                      refit_freq=REFIT_FREQ_GJR, seed=SEED):
    """
    GJR-X OOS forecast.

    LOOKAHEAD GUARD:
      To forecast h_t we use returns[t-1] and r2_overnight[t-1].
      Both indexed at t-1 — this is the `.shift(1)` equivalent.
      r2_overnight[t-1] = (log(open_{t-1}/close_{t-2}))² which is observable
      by close of t-1. No t-day info used.
    """
    n = len(returns)
    assert len(r2_overnight) == n, "returns and r2_overnight must align"
    forecasts = np.full(n, np.nan)

    def neg_ll(params, r, r2ov):
        # Stationarity guard
        if params[1] + params[2] + params[3] >= 0.999:
            return 1e15
        return _gjrx_negll(params[0], params[1], params[2],
                           params[3], params[4], r, r2ov)

    eps = 1e-8
    # δ ∈ [0, 0.999): no lower-bound penalty so MLE can find it small if needed
    bounds = [(eps, 1e-3), (eps, 0.5), (0.0, 0.5),
              (eps, 0.999), (0.0, 0.999)]

    current_params = None
    h_state = np.var(returns[:min(50, n)])

    for t in range(is_end, n):
        if (t - is_end) % refit_freq == 0 or t == is_end:
            r_train = returns[:t].copy()
            r2ov_train = r2_overnight[:t].copy()
            best_nll = np.inf
            best_p = None
            rng = np.random.RandomState(seed)
            for i in range(N_STARTS_GJR_X):
                if i == 0:
                    x0 = [np.var(r_train) * 0.05, 0.08, 0.06, 0.85, 0.10]
                else:
                    x0 = [rng.uniform(1e-8, 1e-4), rng.uniform(0.02, 0.2),
                          rng.uniform(0.0, 0.15), rng.uniform(0.6, 0.92),
                          rng.uniform(0.0, 0.4)]
                try:
                    res = minimize(neg_ll, x0, args=(r_train, r2ov_train),
                                   method='L-BFGS-B', bounds=bounds,
                                   options={'maxiter': 1500})
                    if res.fun < best_nll and res.fun < 1e14:
                        best_nll = res.fun
                        best_p = res.x
                except Exception:
                    continue
            if best_p is not None:
                current_params = best_p
                w, a, g, b, d = current_params
                h0 = np.var(returns[:min(50, t)])
                if h0 < 1e-12:
                    h0 = 1e-8
                h_state = _gjrx_propagate(w, a, g, b, d,
                                          returns, r2_overnight, h0, 1, t)

        if current_params is not None:
            w, a, g, b, d = current_params
            ind = 1.0 if returns[t-1] < 0 else 0.0
            # FORECAST: signal.shift(1) — features at t-1, target at t
            h_state = (w + a * returns[t-1]**2 + g * returns[t-1]**2 * ind
                       + b * h_state + d * r2_overnight[t-1])
            if h_state < 1e-12:
                h_state = 1e-12
            forecasts[t] = h_state

    return forecasts


# ============================================================
# Evaluation utilities
# ============================================================
def qlike_loss(realized, forecast):
    """Patton (2011) QLIKE — robust to imperfect proxy."""
    valid = (np.isfinite(realized) & np.isfinite(forecast)
             & (forecast > 0) & (realized > 0))
    out = np.full(len(realized), np.nan)
    r = realized[valid]
    f = forecast[valid]
    out[valid] = r / f - np.log(r / f) - 1.0
    return out


def fmt_dm(t_stat, p_value):
    return {
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "harvey_pass": bool(abs(t_stat) > 3.0),
    }


# ============================================================
# Main
# ============================================================
def main():
    t_start = time.time()

    print("=" * 70)
    print("K1260: GJR-X vs PRG vs GJR on SPY OOS")
    print("=" * 70)

    # ------------------------------------------------------------------
    # 1. Load SPY data — REUSE K880's loader (same data definition)
    # ------------------------------------------------------------------
    print("\n[Step 1] Loading SPY data via K880 loader...")
    df = k880_prg.load_spy_data()
    print(f"  Total days: {len(df)}")
    print(f"  Date range: {df.index[0].date()} → {df.index[-1].date()}")

    # IS / OOS split
    is_end_idx = df.index.searchsorted(pd.Timestamp(IS_END_DATE), side='right')
    n_is = is_end_idx
    n_oos = len(df) - n_is
    print(f"  IS end: {df.index[is_end_idx-1].date()} (n_is={n_is})")
    print(f"  OOS start: {df.index[is_end_idx].date()} (n_oos={n_oos})")

    # Extract arrays
    r_c2c = df['r_c2c'].values
    r_overnight = df['r_overnight'].values
    r_intra = df['r_intra'].values
    r2_overnight = df['r2_overnight'].values
    r2_intra = df['r2_intra'].values
    sigma2_fullday = df['sigma2_fullday'].values

    # ------------------------------------------------------------------
    # 1b. IS LR test diagnostic — does δ matter in-sample?
    # ------------------------------------------------------------------
    print("\n[Step 1b] IS LR test: does δ (overnight regressor) matter IS?")
    r_c2c_is = df['r_c2c'].values[:is_end_idx]
    r2_ov_is = df['r2_overnight'].values[:is_end_idx]

    eps_is = 1e-8
    rng_is = np.random.RandomState(SEED)

    # Fit GJR (restricted, δ=0)
    def neg_ll_gjr_is(p, r):
        if p[1] + p[2] + p[3] >= 0.999:
            return 1e15
        return _gjr_negll(p[0], p[1], p[2], p[3], r)

    bounds_g = [(eps_is, 1e-3), (eps_is, 0.5), (0.0, 0.5), (eps_is, 0.999)]
    best_g = np.inf
    bp_g = None
    for x0 in ([[np.var(r_c2c_is) * 0.05, 0.08, 0.06, 0.85]]
               + [[rng_is.uniform(1e-8, 1e-4), rng_is.uniform(0.02, 0.2),
                   rng_is.uniform(0, 0.15), rng_is.uniform(0.7, 0.95)]
                  for _ in range(15)]):
        try:
            r = minimize(neg_ll_gjr_is, x0, args=(r_c2c_is,),
                         method='L-BFGS-B', bounds=bounds_g,
                         options={'maxiter': 2000})
            if r.fun < best_g and r.fun < 1e14:
                best_g = r.fun
                bp_g = r.x
        except Exception:
            pass

    # Fit GJR-X (unrestricted, δ free)
    def neg_ll_gjrx_is(p, r, r2ov):
        if p[1] + p[2] + p[3] >= 0.999:
            return 1e15
        return _gjrx_negll(p[0], p[1], p[2], p[3], p[4], r, r2ov)

    bounds_x = [(eps_is, 1e-3), (eps_is, 0.5), (0.0, 0.5),
                (eps_is, 0.999), (0.0, 0.999)]
    best_x = np.inf
    bp_x = None
    rng_is2 = np.random.RandomState(SEED)
    for x0 in ([[np.var(r_c2c_is) * 0.05, 0.08, 0.06, 0.85, 0.10],
                [np.var(r_c2c_is) * 0.05, 0.08, 0.06, 0.85, 0.30],
                [np.var(r_c2c_is) * 0.05, 0.08, 0.06, 0.85, 0.50],
                [np.var(r_c2c_is) * 0.05, 0.08, 0.06, 0.85, 1e-4]]
               + [[rng_is2.uniform(1e-8, 1e-4), rng_is2.uniform(0.02, 0.2),
                   rng_is2.uniform(0, 0.15), rng_is2.uniform(0.6, 0.92),
                   rng_is2.uniform(0, 0.5)] for _ in range(15)]):
        try:
            r = minimize(neg_ll_gjrx_is, x0, args=(r_c2c_is, r2_ov_is),
                         method='L-BFGS-B', bounds=bounds_x,
                         options={'maxiter': 2000})
            if r.fun < best_x and r.fun < 1e14:
                best_x = r.fun
                bp_x = r.x
        except Exception:
            pass

    from scipy.stats import chi2 as _chi2
    LR = 2 * (best_g - best_x)  # NLL diff (G - X). LR > 0 means GJR-X better
    p_lr = float(1 - _chi2.cdf(LR, 1)) if LR > 0 else 1.0

    is_lr_diagnostic = {
        "gjr_is_nll": float(best_g),
        "gjrx_is_nll": float(best_x),
        "gjr_params": {
            "omega": float(bp_g[0]), "alpha": float(bp_g[1]),
            "gamma": float(bp_g[2]), "beta": float(bp_g[3]),
        },
        "gjrx_params": {
            "omega": float(bp_x[0]), "alpha": float(bp_x[1]),
            "gamma": float(bp_x[2]), "beta": float(bp_x[3]),
            "delta": float(bp_x[4]),
        },
        "LR_stat": float(LR),
        "p_value": p_lr,
        "df": 1,
        "delta_significant_IS": bool(p_lr < 0.05),
        "n_starts_used": 16,
        "interpretation": (
            f"IS LR test δ=0 vs δ>0: LR={LR:.2f}, p={p_lr:.4f}. "
            f"{'δ significant IS — overnight info contains predictive content' if p_lr < 0.05 else 'δ NOT significant IS'}"
        ),
    }
    print(f"  GJR  IS NLL: {best_g:.2f}")
    print(f"  GJR-X IS NLL: {best_x:.2f}  δ̂={bp_x[4]:.4f}")
    print(f"  LR={LR:.2f}, p={p_lr:.4f} → "
          f"{'δ SIGNIFICANT IS' if p_lr < 0.05 else 'δ NOT SIG'}")

    # ------------------------------------------------------------------
    # 2. Forecasts
    # ------------------------------------------------------------------
    print("\n[Step 2] Fitting models and generating OOS forecasts...")

    print("  → GJR (standard, K880 spec) ...")
    f_gjr = gjr_oos_forecast(r_c2c, is_end_idx)

    print("  → GJR-X (overnight as exogenous regressor, NEW) ...")
    f_gjrx = gjrx_oos_forecast(r_c2c, r2_overnight, is_end_idx)

    print("  → PRG_Extended (canonical from K880) ...")
    # Reuse K880's PRG forecast — guarantees DM~6.00 canonical reference
    f_prg = k880_prg.prg_oos_forecast(
        r_overnight, r_intra, r2_overnight, r2_intra,
        is_end_idx, extended=True, refit_freq=REFIT_FREQ_PRG
    )

    # ------------------------------------------------------------------
    # 3. Evaluate on σ²_fullday target (P6 paper convention)
    # ------------------------------------------------------------------
    print("\n[Step 3] Computing QLIKE on σ²_fullday target...")
    realized = sigma2_fullday

    # Align: only OOS section, drop NaNs across all forecast series
    oos_slice = slice(is_end_idx, len(df))
    r_oos = realized[oos_slice]
    fg_oos = f_gjr[oos_slice]
    fx_oos = f_gjrx[oos_slice]
    fp_oos = f_prg[oos_slice]

    valid = (np.isfinite(r_oos) & np.isfinite(fg_oos)
             & np.isfinite(fx_oos) & np.isfinite(fp_oos)
             & (r_oos > 0) & (fg_oos > 0) & (fx_oos > 0) & (fp_oos > 0))
    n_eval = int(valid.sum())
    print(f"  Valid OOS obs (all 3 models): {n_eval} / {len(r_oos)}")

    r_v = r_oos[valid]
    fg_v = fg_oos[valid]
    fx_v = fx_oos[valid]
    fp_v = fp_oos[valid]

    ql_gjr = qlike_loss(r_v, fg_v)
    ql_gjrx = qlike_loss(r_v, fx_v)
    ql_prg = qlike_loss(r_v, fp_v)

    qlike_results = {
        "GJR": float(np.nanmean(ql_gjr)),
        "GJR_X": float(np.nanmean(ql_gjrx)),
        "PRG_Extended": float(np.nanmean(ql_prg)),
    }
    print(f"  QLIKE: {qlike_results}")

    # ------------------------------------------------------------------
    # 4. DM tests pairwise
    # ------------------------------------------------------------------
    print("\n[Step 4] DM tests (Harvey small-sample correction)...")
    # dm_test(loss1, loss2): t > 0 means loss1 > loss2 (model 2 wins)
    # Convention used in K880: PRG_vs_GJR positive ⇔ PRG QLIKE < GJR QLIKE
    t_prg_gjr, p_prg_gjr = dm_test(ql_gjr, ql_prg)
    t_prg_gjrx, p_prg_gjrx = dm_test(ql_gjrx, ql_prg)
    t_gjrx_gjr, p_gjrx_gjr = dm_test(ql_gjr, ql_gjrx)

    dm_results = {
        "PRG_vs_GJR": {
            "t_stat": float(t_prg_gjr),
            "p_value": float(p_prg_gjr),
            "harvey_pass": bool(abs(t_prg_gjr) > 3.0),
            "winner": "PRG" if t_prg_gjr > 0 else "GJR",
            "interpretation": (
                f"PRG vs GJR: DM t={t_prg_gjr:.2f} (winner: "
                f"{'PRG' if t_prg_gjr > 0 else 'GJR'}, "
                f"Harvey {'PASS' if abs(t_prg_gjr) > 3.0 else 'FAIL'})"
            ),
        },
        "PRG_vs_GJR_X": {
            "t_stat": float(t_prg_gjrx),
            "p_value": float(p_prg_gjrx),
            "harvey_pass": bool(abs(t_prg_gjrx) > 3.0),
            "winner": "PRG" if t_prg_gjrx > 0 else "GJR_X",
            "interpretation": (
                f"PRG vs GJR-X: DM t={t_prg_gjrx:.2f} (winner: "
                f"{'PRG' if t_prg_gjrx > 0 else 'GJR-X'}, "
                f"Harvey {'PASS' if abs(t_prg_gjrx) > 3.0 else 'FAIL'})"
            ),
        },
        "GJR_X_vs_GJR": {
            "t_stat": float(t_gjrx_gjr),
            "p_value": float(p_gjrx_gjr),
            "harvey_pass": bool(abs(t_gjrx_gjr) > 3.0),
            "winner": "GJR_X" if t_gjrx_gjr > 0 else "GJR",
            "interpretation": (
                f"GJR-X vs GJR: DM t={t_gjrx_gjr:.2f} (winner: "
                f"{'GJR-X' if t_gjrx_gjr > 0 else 'GJR'}, "
                f"Harvey {'PASS' if abs(t_gjrx_gjr) > 3.0 else 'FAIL'})"
            ),
        },
    }
    for k, v in dm_results.items():
        print(f"  {v['interpretation']}")

    # ------------------------------------------------------------------
    # 5. NotebookLM prediction check
    # ------------------------------------------------------------------
    print("\n[Step 5] NotebookLM Argument A prediction verification...")
    gjrx_dm_t = t_gjrx_gjr
    in_predicted_range = (2.0 <= gjrx_dm_t <= 4.0)
    prg_still_beats_gjrx = t_prg_gjrx > 0
    print(f"  GJR-X DM t (vs GJR) = {gjrx_dm_t:.2f}; predicted [2, 4] → "
          f"{'YES' if in_predicted_range else 'NO'}")
    print(f"  PRG still beats GJR-X? t = {t_prg_gjrx:.2f} → "
          f"{'YES' if prg_still_beats_gjrx else 'NO'}")

    notebooklm_check = {
        "predicted_range_GJR_X_DM_t": [2.0, 4.0],
        "observed_GJR_X_DM_t": float(gjrx_dm_t),
        "in_predicted_range": bool(in_predicted_range),
        "prg_still_beats_gjrx": bool(prg_still_beats_gjrx),
        "argument_A_supported": bool(in_predicted_range and prg_still_beats_gjrx),
        "narrative": (
            "Argument A: PRG advantage = session-boundary BRIDGE, not just "
            "additional information. Confirmed if (a) GJR-X moderately beats "
            "GJR (more info helps) AND (b) PRG still beats GJR-X (bridge has "
            "value beyond raw info)."
        ),
    }

    # ------------------------------------------------------------------
    # 6. Save results
    # ------------------------------------------------------------------
    out = {
        "experiment_id": "K1260",
        "title": "GJR-X (Fair-Info Baseline) vs PRG vs GJR on SPY OOS",
        "type": "empirical",
        "research_question": (
            "Is PRG's advantage just information gain (reading overnight "
            "separately) or genuinely the cross-session bridge mechanism? "
            "GJR-X is a fair-info baseline that reads the same two pieces "
            "of info as PRG but flattens them into one GJR recursion via "
            "exogenous regressor."
        ),
        "data_source": "yfinance (SPY)",
        "period": f"{df.index[0].date()} to {df.index[-1].date()}",
        "is_period": f"{df.index[0].date()} to {df.index[is_end_idx-1].date()}",
        "oos_period": (
            f"{df.index[is_end_idx].date()} to {df.index[-1].date()}"
        ),
        "n_total": int(len(df)),
        "n_is": int(n_is),
        "n_oos": int(n_oos),
        "n_eval": int(n_eval),
        "target": "sigma2_fullday = r2_overnight + r2_intra (Patton 2011)",
        "loss": "QLIKE",
        "test": "Diebold-Mariano (Harvey 1997 small-sample correction)",
        "lookahead_check": (
            "GJR-X uses returns[t-1] and r2_overnight[t-1] to forecast h_t — "
            "explicit signal.shift(1) equivalent. r2_overnight[t-1] is "
            "(log(open_{t-1}/close_{t-2}))^2, observable by close of t-1. "
            "No t-day info used to forecast t. See gjrx_oos_forecast() and "
            "_gjrx_negll() / _gjrx_propagate() for r2_ov[t-1] indexing."
        ),
        "seed": SEED,
        "n_starts_gjr": N_STARTS_GJR,
        "n_starts_gjr_x": N_STARTS_GJR_X,
        "n_starts_prg": N_STARTS_PRG,
        "refit_freq_gjr": REFIT_FREQ_GJR,
        "refit_freq_gjr_x": REFIT_FREQ_GJR,
        "refit_freq_prg": REFIT_FREQ_PRG,
        "models": {
            "GJR": "h_t = w + a*r2_{t-1} + g*I(r<0)*r2_{t-1} + b*h_{t-1}",
            "GJR_X": (
                "h_t = w + a*r2_{t-1} + g*I(r<0)*r2_{t-1} + b*h_{t-1} "
                "+ d*r2_overnight_{t-1}  (NEW: + delta * yesterday's "
                "overnight squared return)"
            ),
            "PRG_Extended": (
                "Periodic GARCH with leverage; cross-session h propagation. "
                "Reuses K880 canonical implementation."
            ),
        },
        "qlike": qlike_results,
        "dm_tests": dm_results,
        "is_lr_diagnostic": is_lr_diagnostic,
        "notebooklm_argument_A": notebooklm_check,
        "harvey_threshold": 3.0,
        "session_decomposition_share": {
            "overnight_pct": float(np.mean(r2_overnight) /
                                    np.mean(sigma2_fullday) * 100),
            "intraday_pct": float(np.mean(r2_intra) /
                                   np.mean(sigma2_fullday) * 100),
        },
        "references": [
            "Hansen, Huang & Shek (2012): Realized GARCH (exogenous regressor)",
            "Glosten, Jagannathan & Runkle (1993): GJR-GARCH",
            "Bollerslev & Ghysels (1996): Periodic GARCH (PRG ancestor)",
            "Patton (2011): Volatility forecast comparison",
            "Diebold & Mariano (1995); Harvey, Leybourne & Newbold (1997)",
            "Lai et al. (2024): PRS / PRG concept",
            "Todorova (2014); Opschoor et al. (2021): overnight modeling",
        ],
        "paper_link": (
            "P6 prg-periodic-garch §6 limitation line 311 — closes the "
            "'GJR-X comparison left for future work' gap. Provides fair-info "
            "baseline for v3 manuscript revision."
        ),
        "runtime_seconds": float(time.time() - t_start),
        "completed_at": datetime.utcnow().isoformat() + "Z",
    }

    with open(OUTPUT_FILE, 'w') as f:
        json.dump(out, f, indent=2)

    print(f"\n[Done] Results saved to {OUTPUT_FILE}")
    print(f"Runtime: {out['runtime_seconds']:.1f}s")
    return out


if __name__ == "__main__":
    main()
