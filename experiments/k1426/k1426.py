"""K1426: Partial Cointegration Hedging (PCH) — IS-only Proof of Concept.

Implements Clegg & Krauss (2018) state-space partial cointegration model:
    x_t = beta * y_t + M_t + R_t
    M_t = rho * M_{t-1} + eps_M,t,  eps_M ~ N(0, sigma_M^2)   (mean-reverting AR(1))
    R_t = R_{t-1} + eps_R,t,        eps_R ~ N(0, sigma_R^2)   (random walk)

Compared against:
    Baseline 1: OLS static hedge (beta_OLS)
    Baseline 2: Engle-Granger cointegration (residual-based, equivalent to OLS
                for the cointegrating vector; spread = x - beta*y - mu)
                We add VECM 1-step adjustment to differentiate.

Pairs (yfinance, daily 2015-01-01 — 2024-12-31):
    pair_1: SPY vs IVV  (S&P 500 ETF cross-listing, expected high cointegration)
    pair_2: USO vs BNO  (WTI vs Brent oil ETFs)
    pair_3: GLD vs IAU  (gold ETFs, expected high cointegration)

Honesty gates:
    - If rho >= 0.999 OR R2_MR < 0.05 => report NULL for that pair
    - All seeds fixed (seed=42)
    - signal lag not applicable (this is hedge ratio estimation, IS-only)

Reproduce:
    uv run python experiments/k1426/k1426.py
"""

from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Data
# ============================================================================
def fetch_pair(symbol_x: str, symbol_y: str, start: str, end: str) -> pd.DataFrame:
    """Fetch log prices of (x, y) from yfinance, inner-join on date."""
    import yfinance as yf

    df_x = yf.download(symbol_x, start=start, end=end, progress=False, auto_adjust=True)
    df_y = yf.download(symbol_y, start=start, end=end, progress=False, auto_adjust=True)
    if df_x.empty or df_y.empty:
        raise RuntimeError(f"yfinance returned empty for {symbol_x}/{symbol_y}")
    px = df_x["Close"].squeeze().rename("x")
    py = df_y["Close"].squeeze().rename("y")
    out = pd.concat([np.log(px), np.log(py)], axis=1).dropna()
    out.columns = ["log_x", "log_y"]
    return out


# ============================================================================
# Partial Cointegration State-Space MLE (Clegg & Krauss 2018)
# ============================================================================
# Observed: y_t = beta * z_t + M_t + R_t  (here z=log_y, y=log_x, with intercept mu)
# State: s_t = (M_t, R_t)
#   M_t = rho * M_{t-1} + eta_M
#   R_t = R_{t-1} + eta_R
# Observation: log_x_t = mu + beta * log_y_t + M_t + R_t + 0 (no measurement noise)
#
# Kalman filter form:
#   x_t = T s_{t-1} + eta_t,  T = diag(rho, 1),  Q = diag(sigma_M^2, sigma_R^2)
#   y_t (residual) = Z s_t = M_t + R_t,  Z = [1, 1]
#
# This is the standard PCAR(1) decomposition (Clegg-Krauss eq. 4).


def kalman_loglik(
    resid: np.ndarray, rho: float, sigma_M: float, sigma_R: float
) -> Tuple[float, np.ndarray, np.ndarray]:
    """Run Kalman filter on residual series, return (loglik, M_filt, R_filt).

    Model:
        s_t = [M_t, R_t]'
        Transition: s_t = T s_{t-1} + eta_t,  T=diag(rho,1), Q=diag(sM^2, sR^2)
        Observation: resid_t = [1, 1] s_t (no obs noise)
    """
    n = len(resid)
    T_mat = np.array([[rho, 0.0], [0.0, 1.0]])
    Q = np.array([[sigma_M ** 2, 0.0], [0.0, sigma_R ** 2]])
    Z = np.array([1.0, 1.0])

    # Diffuse init for R (random walk), stationary init for M.
    # M_0 ~ N(0, sigma_M^2 / (1 - rho^2)), R_0 ~ N(0, kappa) with large kappa.
    kappa = 1e7
    var_M0 = sigma_M ** 2 / max(1.0 - rho ** 2, 1e-8) if abs(rho) < 1 else kappa
    s = np.array([0.0, 0.0])
    P = np.array([[var_M0, 0.0], [0.0, kappa]])

    ll = 0.0
    M_filt = np.zeros(n)
    R_filt = np.zeros(n)

    for t in range(n):
        # Predict
        s_pred = T_mat @ s
        P_pred = T_mat @ P @ T_mat.T + Q

        # Innovation
        y_pred = Z @ s_pred
        v = resid[t] - y_pred
        F = Z @ P_pred @ Z  # scalar (since no obs noise)
        F = max(F, 1e-10)

        # Update (univariate)
        K = (P_pred @ Z) / F  # 2-vector
        s = s_pred + K * v
        P = P_pred - np.outer(K, Z @ P_pred)

        ll += -0.5 * (np.log(2 * np.pi) + np.log(F) + v * v / F)
        M_filt[t] = s[0]
        R_filt[t] = s[1]

    return ll, M_filt, R_filt


def neg_loglik(params: np.ndarray, log_x: np.ndarray, log_y: np.ndarray) -> float:
    """Negative log-likelihood. Params: (mu, beta, rho, log_sigma_M, log_sigma_R).

    rho is mapped via tanh to keep |rho|<1.
    """
    mu, beta, rho_raw, log_sM, log_sR = params
    rho = np.tanh(rho_raw)
    sigma_M = np.exp(log_sM)
    sigma_R = np.exp(log_sR)

    if sigma_M < 1e-8 or sigma_R < 1e-8:
        return 1e10

    resid = log_x - mu - beta * log_y
    try:
        ll, _, _ = kalman_loglik(resid, rho, sigma_M, sigma_R)
    except Exception:
        return 1e10
    if not np.isfinite(ll):
        return 1e10
    return -ll


@dataclass
class PCHFit:
    mu: float
    beta: float
    rho: float
    sigma_M: float
    sigma_R: float
    loglik: float
    n_starts_converged: int
    M_filt: np.ndarray
    R_filt: np.ndarray
    resid: np.ndarray


def fit_pch(
    log_x: np.ndarray, log_y: np.ndarray, n_starts: int = 100, seed: int = SEED
) -> PCHFit:
    """Fit PCH model via multistart MLE.

    Returns best fit. Enforces ≥100 multistart per pooled-MLE rule
    (K1213→K1216c lesson).
    """
    rng = np.random.default_rng(seed)

    # Initial OLS guess for (mu, beta)
    X = np.column_stack([np.ones_like(log_y), log_y])
    ols_coef, *_ = np.linalg.lstsq(X, log_x, rcond=None)
    mu0, beta0 = ols_coef[0], ols_coef[1]
    resid0 = log_x - mu0 - beta0 * log_y
    sigma0 = float(np.std(np.diff(resid0)))

    best_ll = -np.inf
    best_params = None
    n_converged = 0

    for i in range(n_starts):
        if i == 0:
            # canonical start
            p0 = np.array([mu0, beta0, np.arctanh(0.5), np.log(sigma0), np.log(sigma0)])
        else:
            p0 = np.array(
                [
                    mu0 + rng.normal(0, 0.05),
                    beta0 * (1 + rng.normal(0, 0.1)),
                    np.arctanh(rng.uniform(-0.99, 0.99)),
                    np.log(sigma0) + rng.normal(0, 0.5),
                    np.log(sigma0) + rng.normal(0, 0.5),
                ]
            )

        try:
            res = minimize(
                neg_loglik,
                p0,
                args=(log_x, log_y),
                method="L-BFGS-B",
                options={"maxiter": 200, "ftol": 1e-8},
            )
            if res.success and np.isfinite(res.fun):
                n_converged += 1
                ll = -res.fun
                if ll > best_ll:
                    best_ll = ll
                    best_params = res.x
        except Exception:
            continue

    if best_params is None:
        raise RuntimeError("All multistart MLE attempts failed")

    mu, beta, rho_raw, log_sM, log_sR = best_params
    rho = float(np.tanh(rho_raw))
    sigma_M = float(np.exp(log_sM))
    sigma_R = float(np.exp(log_sR))

    resid = log_x - mu - beta * log_y
    _, M_filt, R_filt = kalman_loglik(resid, rho, sigma_M, sigma_R)

    return PCHFit(
        mu=float(mu),
        beta=float(beta),
        rho=rho,
        sigma_M=sigma_M,
        sigma_R=sigma_R,
        loglik=float(best_ll),
        n_starts_converged=int(n_converged),
        M_filt=M_filt,
        R_filt=R_filt,
        resid=resid,
    )


# ============================================================================
# Baselines
# ============================================================================
def fit_ols_hedge(log_x: np.ndarray, log_y: np.ndarray) -> Tuple[float, float, np.ndarray]:
    """OLS static hedge: log_x = mu + beta * log_y + eps. Returns (mu, beta, spread)."""
    X = np.column_stack([np.ones_like(log_y), log_y])
    coef, *_ = np.linalg.lstsq(X, log_x, rcond=None)
    spread = log_x - coef[0] - coef[1] * log_y
    return float(coef[0]), float(coef[1]), spread


def fit_eg_vecm_hedge(
    log_x: np.ndarray, log_y: np.ndarray
) -> Tuple[float, float, np.ndarray, float]:
    """Engle-Granger cointegration with VECM 1-step adjustment.

    Stage 1: OLS to get cointegrating vector (mu, beta) — same as OLS hedge.
    Stage 2: ECM:  d(log_x)_t = alpha * (log_x_{t-1} - mu - beta*log_y_{t-1})
                                + gamma * d(log_y)_t + eps_t
            ECM-implied spread is the equilibrium residual.

    We return the EG spread (same residual as OLS, since stage-1 is OLS),
    but report alpha (speed of adjustment) for context.
    """
    mu, beta, spread = fit_ols_hedge(log_x, log_y)
    # VECM step: regress d(log_x) on lagged residual & d(log_y)
    d_x = np.diff(log_x)
    d_y = np.diff(log_y)
    ecm_term = spread[:-1]
    X2 = np.column_stack([ecm_term, d_y, np.ones_like(d_y)])
    coef2, *_ = np.linalg.lstsq(X2, d_x, rcond=None)
    alpha = float(coef2[0])
    return mu, beta, spread, alpha


# ============================================================================
# Hedge effectiveness
# ============================================================================
def hedge_effectiveness(unhedged: np.ndarray, hedged_spread: np.ndarray) -> float:
    """HE = 1 - Var(hedged) / Var(unhedged).

    'unhedged' = d log_x (long-only return).
    'hedged' = d(spread) = d log_x - beta * d log_y.
    """
    d_un = np.diff(unhedged)
    d_he = np.diff(hedged_spread)
    var_un = float(np.var(d_un, ddof=1))
    var_he = float(np.var(d_he, ddof=1))
    if var_un < 1e-12:
        return float("nan")
    return 1.0 - var_he / var_un


# ============================================================================
# Per-pair pipeline
# ============================================================================
def analyze_pair(name: str, sym_x: str, sym_y: str, start: str, end: str) -> Dict:
    print(f"\n[{name}] Fetching {sym_x} / {sym_y} ...")
    df = fetch_pair(sym_x, sym_y, start, end)
    log_x = df["log_x"].values
    log_y = df["log_y"].values
    n = len(df)
    print(f"[{name}] N obs = {n}, range = {df.index[0].date()} → {df.index[-1].date()}")

    # OLS baseline
    mu_ols, beta_ols, spread_ols = fit_ols_hedge(log_x, log_y)
    he_ols = hedge_effectiveness(log_x, spread_ols)

    # EG-VECM
    _, beta_eg, spread_eg, alpha_eg = fit_eg_vecm_hedge(log_x, log_y)
    he_eg = hedge_effectiveness(log_x, spread_eg)

    # PCH
    print(f"[{name}] Fitting PCH with 100 multistarts ...")
    pch = fit_pch(log_x, log_y, n_starts=100, seed=SEED)
    # PCH spread = M_t + R_t (the modeled deviation), which equals resid by
    # construction since obs noise = 0. The hedged position uses beta_PCH.
    spread_pch = log_x - pch.mu - pch.beta * log_y
    he_pch = hedge_effectiveness(log_x, spread_pch)

    # Diagnostics
    r2_mr = float(pch.sigma_M ** 2 / (pch.sigma_M ** 2 + pch.sigma_R ** 2))
    if abs(pch.rho) < 0.999 and pch.rho > 0:
        half_life = float(-np.log(2) / np.log(pch.rho))
    else:
        half_life = float("inf")

    # Verdict per honesty gate (aligned with run_fast.py — Codex CONDITIONAL_PASS fix 2026-06-08)
    if pch.rho >= 0.999 or r2_mr < 0.05:
        verdict = "NULL"
        notes = f"PCH degenerates: rho={pch.rho:.4f}, R2_MR={r2_mr:.4f}"
    elif pch.rho <= 0:
        verdict = "NULL_RHO_NEGATIVE"
        notes = f"PCH rho={pch.rho:.4f} not mean-reverting (oscillating, not AR(1) Clegg-Krauss)"
    elif half_life is not None and half_life < 1.0:
        verdict = "NULL_HALFLIFE_TRIVIAL"
        notes = f"PCH half-life={half_life:.3f}d trivial (~i.i.d. noise, not partial cointegration)"
    elif he_pch < max(he_ols, he_eg) - 0.05:
        verdict = "FAIL"
        notes = "PCH underperforms baselines by >5pp HE"
    else:
        verdict = "PASS"
        notes = f"PCH HE comparable to baselines; rho={pch.rho:.4f}, half-life={half_life:.1f}d"

    print(
        f"[{name}] beta_ols={beta_ols:.4f}, beta_pch={pch.beta:.4f}, "
        f"rho={pch.rho:.4f}, R2_MR={r2_mr:.4f}, half_life={half_life:.2f}d"
    )
    print(f"[{name}] HE: ols={he_ols:.4f}, eg={he_eg:.4f}, pch={he_pch:.4f}  ⇒ {verdict}")

    # Figures
    plot_pair(name, df, spread_ols, spread_eg, spread_pch, pch)

    return {
        "symbols": {"x": sym_x, "y": sym_y},
        "n_obs": int(n),
        "date_start": str(df.index[0].date()),
        "date_end": str(df.index[-1].date()),
        "ols": {"mu": mu_ols, "beta": beta_ols, "he": he_ols},
        "eg_vecm": {"beta": beta_eg, "alpha": alpha_eg, "he": he_eg},
        "pch": {
            "mu": pch.mu,
            "beta": pch.beta,
            "rho": pch.rho,
            "sigma_M": pch.sigma_M,
            "sigma_R": pch.sigma_R,
            "loglik": pch.loglik,
            "n_starts_converged": pch.n_starts_converged,
            "r2_mr": r2_mr,
            "half_life_days": half_life if np.isfinite(half_life) else None,
            "he": he_pch,
        },
        "verdict": verdict,
        "notes": notes,
    }


def plot_pair(
    name: str,
    df: pd.DataFrame,
    spread_ols: np.ndarray,
    spread_eg: np.ndarray,
    spread_pch: np.ndarray,
    pch: PCHFit,
):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Fig 1: spread comparison
    fig, ax = plt.subplots(figsize=(10, 5))
    idx = df.index
    ax.plot(idx, spread_ols, label="OLS spread", alpha=0.7, lw=0.9)
    ax.plot(idx, spread_eg, label="EG-VECM spread", alpha=0.7, lw=0.9, ls="--")
    ax.plot(idx, spread_pch, label="PCH spread", alpha=0.9, lw=1.1, color="crimson")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title(f"K1426 {name} — Spread Comparison (IS)")
    ax.set_ylabel("log spread")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / f"fig_{name}_spread.png", dpi=120)
    plt.close(fig)

    # Fig 2: PCH state decomposition (M = mean-reverting, R = random walk)
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(idx, pch.M_filt, color="steelblue", lw=0.9)
    axes[0].axhline(0, color="k", lw=0.5)
    axes[0].set_title(
        f"K1426 {name} — PCH State Decomposition  "
        f"(rho={pch.rho:.3f}, sigma_M={pch.sigma_M:.4f}, sigma_R={pch.sigma_R:.4f})"
    )
    axes[0].set_ylabel("M_t (mean-rev)")
    axes[1].plot(idx, pch.R_filt, color="darkorange", lw=0.9)
    axes[1].set_ylabel("R_t (random walk)")
    axes[1].set_xlabel("Date")
    fig.tight_layout()
    fig.savefig(FIG_DIR / f"fig_{name}_decomp.png", dpi=120)
    plt.close(fig)


# ============================================================================
# Main
# ============================================================================
def main():
    pairs = [
        ("pair_1_SPY_IVV", "SPY", "IVV"),
        ("pair_2_USO_BNO", "USO", "BNO"),
        ("pair_3_GLD_IAU", "GLD", "IAU"),
    ]
    start, end = "2015-01-01", "2024-12-31"

    results = {}
    for name, sx, sy in pairs:
        try:
            results[name] = analyze_pair(name, sx, sy, start, end)
        except Exception as e:
            results[name] = {"error": str(e), "verdict": "FAIL"}
            print(f"[{name}] ERROR: {e}")

    # Overall verdict (aligned with run_fast.py — Codex CONDITIONAL_PASS fix 2026-06-08)
    verdicts = [r.get("verdict", "FAIL") for r in results.values()]
    null_like = {"NULL", "NULL_RHO_NEGATIVE", "NULL_HALFLIFE_TRIVIAL"}
    if any(v == "PASS" for v in verdicts):
        overall = "PASS"  # at least one pair shows PCH works
    elif all(v in null_like for v in verdicts):
        overall = "NULL"
    else:
        overall = "FAIL"

    payload = {
        "experiment_id": "k1426",
        "title": "Partial Cointegration Hedging — IS Proof of Concept",
        "seed": SEED,
        "data_range": {"start": start, "end": end},
        "pairs": results,
        "verdict": overall,
        "notes": (
            "IS-only PoC; OOS rolling-window + bootstrap CI deferred to compute_queue. "
            "PCH HE compared vs OLS static and EG-VECM. Multistart MLE n=100, seed=42."
        ),
        "reproduce": "uv run python experiments/k1426/k1426.py",
    }

    out_path = OUT_DIR / "k1426_results.json"
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=float)
    print(f"\n✓ Wrote {out_path}")
    print(f"Overall verdict: {overall}")
    return payload


if __name__ == "__main__":
    main()
