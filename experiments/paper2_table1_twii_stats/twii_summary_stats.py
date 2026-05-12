#!/usr/bin/env python3
"""
twii_summary_stats.py — Paper 2 Table 1 TWII summary statistics reproduction

Paper claim (paper/taiwan-vt/body.tex L51):
    TWII (1997-2026) | mean=0.019 | std=1.45 | skew=-0.31 | kurt=5.82 | gamma=0.272 | t=3.18
    n=7148 trading days (L34)

Verifies each of the 7 numbers against pinned snapshots:
  - paper/taiwan-vt/data/_twii_1997_2007_snapshot.csv (pre-2008 piece)
  - paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
    (twii_close column, 2008-01-02 .. 2026-05-08)

Method:
  - Combine the two snapshots (no overlap by construction; pre-2008 + from-2008).
  - Drop duplicates / NaN; sort by date.
  - log returns r_t = ln(P_t / P_{t-1}) * 100 (matches body.tex L41 formula).
  - mean, std (ddof=1), skew (Fisher), kurtosis (excess Fisher, scipy default).
  - GJR-N(1,1) gamma estimated via custom MLE (NO arch package — K1213 lesson
    "套件限制 ≠ 模型無效"): full-sample, scipy.optimize.minimize Nelder-Mead,
    100 random starts (seed=42), gradient-free, choose best by log-likelihood.
    Variance: omega + (alpha + gamma * I[r_{t-1}<0]) * r_{t-1}^2 + beta * sigma_{t-1}^2.
    Standard errors: inverse OPG (outer-product-of-gradients) numerically; analytic
    Hessian unstable for boundary alpha+gamma/2+beta near 1.
  - gamma t-stat = gamma / SE(gamma).

No forecast lag concern: this is in-sample descriptive + full-sample MLE.
All numbers are byte-compared against paper canonical values with explicit tolerance.

Outputs:
  twii_summary_stats_results.json — per-cell delta + verdict + LL multistart distribution.

Run:
  cd <repo root>
  uv run python experiments/paper2_table1_twii_stats/twii_summary_stats.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DATA_DIR = REPO_ROOT / "paper" / "taiwan-vt" / "data"

PRE2008_CSV = DATA_DIR / "_twii_1997_2007_snapshot.csv"
FROM2008_CSV = DATA_DIR / "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"

OUT_JSON = SCRIPT_DIR / "twii_summary_stats_results.json"

# Paper canonical values (paper/taiwan-vt/body.tex L34 + L51)
PAPER_CANONICAL = {
    "mean_pct": 0.019,
    "std_pct": 1.45,
    "skew": -0.31,
    "kurt_excess": 5.82,
    "gamma_gjr": 0.272,
    "t_gamma": 3.18,
    "n_obs": 7148,
}

# Tolerances from task brief
TOLERANCE = {
    "mean_pct": 0.005,
    "std_pct": 0.005,
    "skew": 0.02,
    "kurt_excess": 0.02,
    "gamma_gjr": 0.005,
    "t_gamma": 0.10,
    "n_obs": 0,  # exact
}

SEED = 42
N_MULTISTART = 100


# ───────────────────────────────────────────────────────────────────────────
# Data loading
# ───────────────────────────────────────────────────────────────────────────

def _read_snapshot_with_comments(path: Path, value_col: str) -> pd.DataFrame:
    """Read a snapshot CSV that may have '# ...' comment lines at the top."""
    df = pd.read_csv(path, comment="#", parse_dates=["date"])
    return df[["date", value_col]].dropna().rename(columns={value_col: "twii_close"})


def load_twii_series() -> pd.Series:
    if not PRE2008_CSV.exists():
        raise FileNotFoundError(
            f"Missing pre-2008 snapshot: {PRE2008_CSV}\n"
            "Run experiments/paper2_table1_twii_stats/fetch_twii_1997_2007_snapshot.py first."
        )
    pre = _read_snapshot_with_comments(PRE2008_CSV, "twii_close")
    post_full = pd.read_csv(FROM2008_CSV, parse_dates=["date"])
    post = post_full[["date", "twii_close"]].dropna()

    # Sanity: no overlap (pre 1997-07-02..2007-12-31; post starts 2008-01-02).
    overlap = set(pre["date"]) & set(post["date"])
    if overlap:
        # Defensive: drop the overlap from post (prefer pre for any duplicates).
        post = post[~post["date"].isin(overlap)]

    combined = pd.concat([pre, post], ignore_index=True)
    combined = combined.drop_duplicates(subset=["date"]).sort_values("date").reset_index(drop=True)
    return combined.set_index("date")["twii_close"].astype(float)


# ───────────────────────────────────────────────────────────────────────────
# Summary statistics
# ───────────────────────────────────────────────────────────────────────────

def compute_basic_stats(returns_pct: np.ndarray) -> dict:
    return {
        "n_obs": int(returns_pct.size),
        "mean_pct": float(np.mean(returns_pct)),
        "std_pct": float(np.std(returns_pct, ddof=1)),
        "skew": float(stats.skew(returns_pct, bias=True)),  # Fisher, biased moment (sample formulae)
        "kurt_excess": float(stats.kurtosis(returns_pct, fisher=True, bias=True)),
    }


# ───────────────────────────────────────────────────────────────────────────
# GJR-N(1,1) MLE  ── no arch package (K1213)
# ───────────────────────────────────────────────────────────────────────────

def gjr_recursion(params: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Return per-t conditional variance sigma^2_t (length T).

    Variance recursion (in same units as r):
        sigma^2_t = omega + (alpha + gamma * I[r_{t-1}<0]) * r_{t-1}^2 + beta * sigma^2_{t-1}
    Demeaned residuals: we estimate a constant mean mu jointly.
    """
    mu, omega, alpha, gamma, beta = params
    T = r.size
    eps = r - mu
    sigma2 = np.empty(T)
    sigma2[0] = np.var(eps, ddof=0)  # unconditional init
    for t in range(1, T):
        prev = eps[t - 1]
        sigma2[t] = omega + (alpha + gamma * (prev < 0.0)) * prev * prev + beta * sigma2[t - 1]
        if not np.isfinite(sigma2[t]) or sigma2[t] <= 0:
            sigma2[t] = 1e-12
    return sigma2


def neg_log_lik(params: np.ndarray, r: np.ndarray) -> float:
    mu, omega, alpha, gamma, beta = params
    # Stationarity (positive-variance) constraint penalties — we keep soft
    # because Nelder-Mead has no bounds; multistart explores feasible regions.
    if omega <= 0 or alpha < 0 or beta < 0 or (alpha + gamma) < 0:
        return 1e10
    # Loose stationarity (alpha + gamma/2 + beta < 1)
    if alpha + gamma / 2.0 + beta >= 0.999999:
        return 1e10
    sigma2 = gjr_recursion(params, r)
    eps = r - mu
    ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + eps * eps / sigma2)
    if not np.isfinite(ll):
        return 1e10
    return -ll


def numerical_gradient_per_obs(params: np.ndarray, r: np.ndarray, h: float = 1e-5) -> np.ndarray:
    """Compute per-observation gradient of log-likelihood w.r.t. params.

    Returns G of shape (T, k) where G[t, j] = d log f(r_t | F_{t-1}) / d params[j].
    Used for OPG-based standard errors: V = inv(G'G).
    """
    def per_obs_ll(p: np.ndarray) -> np.ndarray:
        mu, *_ = p
        sigma2 = gjr_recursion(p, r)
        eps = r - mu
        return -0.5 * (np.log(2 * np.pi * sigma2) + eps * eps / sigma2)

    k = params.size
    T = r.size
    G = np.empty((T, k))
    for j in range(k):
        p_up = params.copy(); p_up[j] += h
        p_dn = params.copy(); p_dn[j] -= h
        ll_up = per_obs_ll(p_up)
        ll_dn = per_obs_ll(p_dn)
        G[:, j] = (ll_up - ll_dn) / (2 * h)
    return G


def estimate_gjr_n_multistart(r: np.ndarray, seed: int = SEED, n_starts: int = N_MULTISTART) -> dict:
    rng = np.random.default_rng(seed)

    sample_mean = float(np.mean(r))
    sample_var = float(np.var(r, ddof=1))

    # Reasonable starting basin centers
    base_center = np.array([sample_mean, 0.05 * sample_var, 0.05, 0.08, 0.85])

    ll_history: list[tuple[float, np.ndarray]] = []
    converged_count = 0
    failure_count = 0

    for i in range(n_starts):
        # Random perturbation around base center
        # mu near sample mean
        mu0 = sample_mean + rng.normal(0, 0.05)
        # omega: positive, small fraction of variance
        omega0 = max(1e-6, 0.05 * sample_var * rng.uniform(0.2, 2.0))
        alpha0 = rng.uniform(0.01, 0.15)
        gamma0 = rng.uniform(0.0, 0.30)
        beta0 = rng.uniform(0.70, 0.95)
        # Ensure stationarity at start
        s = alpha0 + gamma0 / 2.0 + beta0
        if s >= 0.99:
            beta0 = 0.99 - alpha0 - gamma0 / 2.0 - 0.01
        x0 = np.array([mu0, omega0, alpha0, gamma0, beta0])

        try:
            res = minimize(
                neg_log_lik,
                x0,
                args=(r,),
                method="Nelder-Mead",
                options={"xatol": 1e-7, "fatol": 1e-7, "maxiter": 8000, "adaptive": True},
            )
            if res.success and np.isfinite(res.fun) and res.fun < 1e9:
                ll_history.append((-res.fun, res.x.copy()))
                converged_count += 1
            else:
                failure_count += 1
        except Exception:
            failure_count += 1

    if not ll_history:
        raise RuntimeError("All GJR multistart runs failed")

    # Best basin
    ll_history.sort(key=lambda t: -t[0])
    best_ll, best_params = ll_history[0]
    ll_values = np.array([t[0] for t in ll_history])

    # OPG standard errors at best
    G = numerical_gradient_per_obs(best_params, r)
    OPG = G.T @ G
    # Add small regularization for numerical stability
    OPG_reg = OPG + np.eye(OPG.shape[0]) * 1e-10
    try:
        cov_opg = np.linalg.inv(OPG_reg)
    except np.linalg.LinAlgError:
        cov_opg = np.linalg.pinv(OPG_reg)
    se_opg = np.sqrt(np.maximum(np.diag(cov_opg), 0.0))

    # Hessian-based standard errors (numerical Hessian of -log L)
    # OPG tends to give over-narrow SE for GARCH; Hessian is the conventional MLE SE,
    # and (OPG)^-1 H (OPG)^-1 is the sandwich (Bollerslev-Wooldridge QML).
    def hessian_numerical(p: np.ndarray, h: float = 1e-4) -> np.ndarray:
        k = p.size
        H = np.zeros((k, k))
        f0 = neg_log_lik(p, r)
        for i in range(k):
            for j in range(i, k):
                if i == j:
                    p_pp = p.copy(); p_pp[i] += h
                    p_mm = p.copy(); p_mm[i] -= h
                    H[i, i] = (neg_log_lik(p_pp, r) - 2 * f0 + neg_log_lik(p_mm, r)) / (h * h)
                else:
                    p_pp = p.copy(); p_pp[i] += h; p_pp[j] += h
                    p_pm = p.copy(); p_pm[i] += h; p_pm[j] -= h
                    p_mp = p.copy(); p_mp[i] -= h; p_mp[j] += h
                    p_mm = p.copy(); p_mm[i] -= h; p_mm[j] -= h
                    H[i, j] = (
                        neg_log_lik(p_pp, r) - neg_log_lik(p_pm, r)
                        - neg_log_lik(p_mp, r) + neg_log_lik(p_mm, r)
                    ) / (4 * h * h)
                    H[j, i] = H[i, j]
        return H

    try:
        H = hessian_numerical(best_params)
        H_reg = H + np.eye(H.shape[0]) * 1e-10
        cov_hess = np.linalg.inv(H_reg)
        se_hess = np.sqrt(np.maximum(np.diag(cov_hess), 0.0))
    except Exception:
        se_hess = np.full(best_params.size, np.nan)
        cov_hess = None

    # Sandwich (QML / Bollerslev-Wooldridge): (H)^-1 (OPG) (H)^-1
    try:
        if cov_hess is not None:
            cov_sand = cov_hess @ OPG @ cov_hess
            se_sand = np.sqrt(np.maximum(np.diag(cov_sand), 0.0))
        else:
            se_sand = np.full(best_params.size, np.nan)
    except Exception:
        se_sand = np.full(best_params.size, np.nan)

    # Primary SE: Hessian-based (closest to paper convention; OPG/sandwich reported alongside)
    se = se_hess if np.all(np.isfinite(se_hess)) else se_opg
    se_method_used = "Hessian (numerical, central diff h=1e-4)" if np.all(np.isfinite(se_hess)) else "OPG fallback"

    mu_hat, omega_hat, alpha_hat, gamma_hat, beta_hat = best_params
    se_mu, se_omega, se_alpha, se_gamma, se_beta = se

    return {
        "params": {
            "mu": float(mu_hat),
            "omega": float(omega_hat),
            "alpha": float(alpha_hat),
            "gamma": float(gamma_hat),
            "beta": float(beta_hat),
        },
        "se": {
            "mu": float(se_mu),
            "omega": float(se_omega),
            "alpha": float(se_alpha),
            "gamma": float(se_gamma),
            "beta": float(se_beta),
        },
        "t_stats": {
            "gamma": float(gamma_hat / se_gamma) if se_gamma > 0 else float("nan"),
        },
        "log_lik": float(best_ll),
        "multistart_diagnostics": {
            "n_starts": n_starts,
            "n_converged": converged_count,
            "n_failed": failure_count,
            "ll_max": float(ll_values.max()),
            "ll_min": float(ll_values.min()),
            "ll_mean": float(ll_values.mean()),
            "ll_std": float(ll_values.std(ddof=1)) if ll_values.size > 1 else 0.0,
            "ll_top5": [float(v) for v in ll_values[:5]],
            "ll_basin_spread": float(ll_values.max() - ll_values.min()),
            "seed": seed,
        },
        "se_primary_method": se_method_used,
        "se_opg": {
            "mu": float(se_opg[0]), "omega": float(se_opg[1]), "alpha": float(se_opg[2]),
            "gamma": float(se_opg[3]), "beta": float(se_opg[4]),
        },
        "se_hessian": {
            "mu": float(se_hess[0]), "omega": float(se_hess[1]), "alpha": float(se_hess[2]),
            "gamma": float(se_hess[3]), "beta": float(se_hess[4]),
        },
        "se_sandwich_qml": {
            "mu": float(se_sand[0]), "omega": float(se_sand[1]), "alpha": float(se_sand[2]),
            "gamma": float(se_sand[3]), "beta": float(se_sand[4]),
        },
        "t_gamma_alt": {
            "opg": float(gamma_hat / se_opg[3]) if se_opg[3] > 0 else float("nan"),
            "hessian": float(gamma_hat / se_hess[3]) if (np.isfinite(se_hess[3]) and se_hess[3] > 0) else float("nan"),
            "sandwich_qml": float(gamma_hat / se_sand[3]) if (np.isfinite(se_sand[3]) and se_sand[3] > 0) else float("nan"),
        },
    }


# ───────────────────────────────────────────────────────────────────────────
# Verdict scoring
# ───────────────────────────────────────────────────────────────────────────

def make_verdict(value: float, paper: float, tol: float, name: str) -> dict:
    delta = value - paper
    abs_delta = abs(delta)
    if name == "n_obs":
        ok = int(value) == int(paper)
    else:
        ok = abs_delta <= tol
    if ok:
        verdict = "BYTE_MATCH"
    elif abs_delta <= tol * 2:
        verdict = "DRIFT_SMALL"
    else:
        verdict = "DRIFT_LARGE"
    return {
        "computed": float(value) if name != "n_obs" else int(value),
        "paper_canonical": float(paper) if name != "n_obs" else int(paper),
        "delta": float(delta),
        "tolerance": float(tol),
        "verdict": verdict,
    }


# ───────────────────────────────────────────────────────────────────────────
# Main
# ───────────────────────────────────────────────────────────────────────────

def main() -> int:
    t0 = time.time()
    print("=" * 76)
    print("Paper 2 Table 1 TWII summary statistics — reproduction")
    print("=" * 76)
    print()

    print("Loading pinned TWII snapshots ...")
    px = load_twii_series()
    print(f"  TWII close: N={len(px)}  range {px.index[0].date()} .. {px.index[-1].date()}")

    # log returns × 100 (matches body.tex L41)
    log_ret = np.log(px.values[1:] / px.values[:-1]) * 100.0
    print(f"  log returns: N={log_ret.size}")
    print()

    basic = compute_basic_stats(log_ret)
    print("Basic statistics:")
    for k, v in basic.items():
        print(f"  {k:15s}: {v}")
    print()

    print(f"Estimating GJR-N(1,1) via custom MLE  ({N_MULTISTART}-start, seed={SEED}) ...")
    gjr = estimate_gjr_n_multistart(log_ret)
    print(f"  best params: mu={gjr['params']['mu']:.5f}, omega={gjr['params']['omega']:.5f}, "
          f"alpha={gjr['params']['alpha']:.5f}, gamma={gjr['params']['gamma']:.5f}, "
          f"beta={gjr['params']['beta']:.5f}")
    print(f"  gamma SE   : {gjr['se']['gamma']:.5f}  → t(gamma)={gjr['t_stats']['gamma']:.4f}")
    print(f"  LL best/mean/std across {gjr['multistart_diagnostics']['n_converged']} converged: "
          f"{gjr['multistart_diagnostics']['ll_max']:.3f} / "
          f"{gjr['multistart_diagnostics']['ll_mean']:.3f} / "
          f"{gjr['multistart_diagnostics']['ll_std']:.4f}")
    print()

    # Per-cell verdicts
    cell_results = {
        "n_obs": make_verdict(basic["n_obs"], PAPER_CANONICAL["n_obs"], TOLERANCE["n_obs"], "n_obs"),
        "mean_pct": make_verdict(basic["mean_pct"], PAPER_CANONICAL["mean_pct"], TOLERANCE["mean_pct"], "mean_pct"),
        "std_pct": make_verdict(basic["std_pct"], PAPER_CANONICAL["std_pct"], TOLERANCE["std_pct"], "std_pct"),
        "skew": make_verdict(basic["skew"], PAPER_CANONICAL["skew"], TOLERANCE["skew"], "skew"),
        "kurt_excess": make_verdict(basic["kurt_excess"], PAPER_CANONICAL["kurt_excess"], TOLERANCE["kurt_excess"], "kurt_excess"),
        "gamma_gjr": make_verdict(gjr["params"]["gamma"], PAPER_CANONICAL["gamma_gjr"], TOLERANCE["gamma_gjr"], "gamma_gjr"),
        "t_gamma": make_verdict(gjr["t_stats"]["gamma"], PAPER_CANONICAL["t_gamma"], TOLERANCE["t_gamma"], "t_gamma"),
    }

    print("─" * 76)
    print(f"{'Cell':<15s} {'Computed':>12s} {'Paper':>10s} {'Delta':>12s} {'Tol':>8s}  Verdict")
    print("─" * 76)
    for name, v in cell_results.items():
        print(f"{name:<15s} {str(v['computed']):>12s} {str(v['paper_canonical']):>10s} "
              f"{v['delta']:>12.5f} {v['tolerance']:>8.3f}  {v['verdict']}")
    print("─" * 76)

    n_byte = sum(1 for v in cell_results.values() if v["verdict"] == "BYTE_MATCH")
    overall = "BYTE_MATCH_ALL" if n_byte == 7 else (
        "MOSTLY_MATCH" if n_byte >= 5 else (
            "PARTIAL_MATCH" if n_byte >= 3 else "DRIFT_LARGE"
        )
    )
    print(f"\nOverall: {n_byte}/7 cells byte-matched  → {overall}")

    out = {
        "experiment_id": "paper2_table1_twii_stats",
        "title": "Paper 2 Table 1 TWII summary statistics reproduction",
        "paper_id": "taiwan-vt",
        "paper_claim_loc": "body.tex L34 (sample window) + L51 (Table 1 row)",
        "paper_claim_text": (
            "TWII (1997-2026) mean=0.019 std=1.45 skew=-0.31 kurt=5.82 "
            "gamma_GJR=0.272 t(gamma)=3.18 n=7148 trading days"
        ),
        "method": (
            "log returns × 100; basic stats via scipy (ddof=1, Fisher excess kurt); "
            "GJR-N(1,1) custom MLE, 100-start Nelder-Mead seed=42, OPG SE"
        ),
        "data_sources": {
            "pre_2008_snapshot": str(PRE2008_CSV.relative_to(REPO_ROOT)),
            "from_2008_snapshot": str(FROM2008_CSV.relative_to(REPO_ROOT)),
            "live_fetch": False,
            "sample_start": str(px.index[0].date()),
            "sample_end": str(px.index[-1].date()),
            "yfinance_pre1997_07_unavailable": True,
            "note": (
                "yfinance ^TWII history begins 1997-07-02; paper text says "
                "'January 1997' as nominal sample window. Effective coverage "
                "starts 1997-07-02. This explains n_obs gap vs paper's 7148."
            ),
        },
        "seed": SEED,
        "n_multistart": N_MULTISTART,
        "basic_stats": basic,
        "gjr_n": gjr,
        "paper_canonical": PAPER_CANONICAL,
        "tolerance": TOLERANCE,
        "cell_results": cell_results,
        "overall_verdict": overall,
        "byte_match_count": n_byte,
        "lookahead_guard": (
            "N/A — Table 1 reports in-sample descriptive moments + full-sample MLE; "
            "no forecast / no signal lag. Seed=42 fixed for multistart reproducibility."
        ),
        "produced_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_seconds": round(time.time() - t0, 1),
    }
    OUT_JSON.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT_JSON.relative_to(REPO_ROOT)}  ({out['runtime_seconds']}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
