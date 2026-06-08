"""K1424 — Hurst as GARCH covariate (SPY OOS forecasting).

Follow-up to K1423 (EWMA Hurst pilot, ρ(H,VIX)=+0.32). K1423 was descriptive;
K1424 is forecasting: does H_{t-1} provide incremental predictive value for
realized variance once we control for GARCH dynamics and VIX?

Lineage / contrast:
- K1423: EWMA Hurst pilot (λ ∈ {0.94, 0.97, 0.99}), descriptive + corr only.
- K1424 (this): Use EWMA λ=0.94 H_{t-1} (K1423's strongest signal) as a
  covariate in GARCH(1,1). OOS DM test vs baseline.

Models (all forecasting σ²_t / RV_t):
  1. GARCH(1,1) baseline:   σ²_t = ω + α r²_{t-1} + β σ²_{t-1}
  2. GARCH + H:             ... + γ · H_{t-1}
  3. GARCH + VIX:           ... + δ · VIX_{t-1}   (control: is H just VIX proxy?)
  4. GARCH + H + VIX:       ... + γ H_{t-1} + δ VIX_{t-1}   (incremental test)

Splits: IS 2010-2019 (estimation), OOS 2020-2026 (forecast eval).
        OOS spans COVID + 2022 bear + 2025-2026 rally → genuine regime stress.

Loss: QLIKE (Patton 2011, robust under noisy proxy) + MSE (report both).
Test: Diebold-Mariano with Newey-West (HAC) covariance, two-sided.
      Moving block bootstrap (fixed length) CI, n_boot=500, seed=42, block_len=5.

Anti-pattern guards (per .claude/rules/experiments.md):
  - Lookahead: all covariates (H, VIX) .shift(1) before merge with target r²_t.
                  Hurst series itself is pre-computed in K1423 using only past
                  observations within rolling window (verified upstream).
  - Seed: bootstrap seed=42; arch GARCH MLE deterministic by default.
  - Over-claim: single OOS split only (2020-2026); do NOT extrapolate to
                full-period claim. Report per-year breakdown.
  - Package limits: if arch GARCH(1,1) fails to converge, fall back to
                    scipy.optimize.minimize hand-rolled MLE with analytic
                    log-likelihood (per K1213 lesson).

Outputs:
  - K1424_hurst_garch_covariate_results.json (main)
  - data/K1424_forecasts.csv (per-day forecasts for 4 GARCH models)
  - data/K1424_loss_diff_series.csv (per-day loss diff for DM)

NOT in scope:
  - knowledge.json write (post Codex review, main thread)
  - feed.json / paper write
  - other K experiments / shared state
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats, optimize

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
RESULTS_PATH = HERE / "K1424_hurst_garch_covariate_results.json"

# Reuse K1423 EWMA Hurst infrastructure
K1423_DIR = HERE.parent / "K1423_ewma_hurst_pilot"
sys.path.insert(0, str(K1423_DIR))

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
HURST_WINDOW = 500
HURST_LAMBDA = 0.94          # K1423's strongest-signal EWMA λ
IS_START, IS_END = "2010-01-01", "2019-12-31"
OOS_START, OOS_END = "2020-01-01", "2030-12-31"
DM_BLOCK_LEN = 5
DM_N_BOOT = 500
SEED = 42

# ------------------------------------------------------------------
# Data
# ------------------------------------------------------------------
def load_data() -> pd.DataFrame:
    """Reuse K1423 cached SPY+VIX parquet. If missing, refetch via K1423 helper.

    Returns DataFrame with index=date, columns=['spy', 'vix', 'ret'].
    """
    cache = K1423_DIR / "data" / "spy_vix_daily.parquet"
    if cache.exists():
        df = pd.read_parquet(cache)
        if len(df) > 1000:
            return df
    # Fallback: re-run K1423 fetch (cached in its dir)
    from K1423_ewma_hurst_pilot import fetch_data
    return fetch_data()


def compute_hurst_series(returns: pd.Series) -> pd.Series:
    """Compute EWMA-weighted rolling Hurst (λ=0.94). Reuse K1423 implementation.

    Per K1423, the rolling window uses only x[t-window:t] (strictly past obs);
    series is then .shift(1) at use site to enforce one-step-ahead forecasting.
    """
    from K1423_ewma_hurst_pilot import rolling_hurst
    return rolling_hurst(returns, HURST_WINDOW, lam=HURST_LAMBDA)


def build_dataset() -> pd.DataFrame:
    """Build master DataFrame with target + lagged covariates.

    Columns:
      ret       = log return r_t           (target = r_t**2 = RV proxy)
      rv2       = r_t**2  (daily squared return as RV proxy)
      h_lag     = H_{t-1}    (Hurst from K1423, EWMA λ=0.94, shifted by 1)
      vix_lag   = VIX_{t-1}  (level)
      rv_lag    = r²_{t-1}   (lagged squared return for GARCH)

    Drops rows with NaN after Hurst burn-in and lag alignment.
    """
    df = load_data().copy()
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    # Hurst series — compute on full sample, then lag
    h = compute_hurst_series(df["ret"])
    df["h_raw"] = h
    df["h_lag"] = df["h_raw"].shift(1)
    df["vix_lag"] = df["vix"].shift(1)

    # RV proxy
    df["rv2"] = df["ret"] ** 2
    df["rv_lag"] = df["rv2"].shift(1)

    df["target_rv2"] = df["rv2"]
    df = df.dropna(subset=["h_lag", "vix_lag", "rv_lag"])
    return df


# ------------------------------------------------------------------
# GARCH MLE (own implementation; scipy optimize only)
# ------------------------------------------------------------------
def _garch_neg_loglik(params: np.ndarray, r: np.ndarray, X: np.ndarray | None) -> float:
    """GARCH(1,1) [+ exogenous] negative log-likelihood (Gaussian).

    σ²_t = ω + α r²_{t-1} + β σ²_{t-1} + X_{t-1} @ γ_vec
    Params: [ω, α, β, γ_1, ..., γ_k]
    Stationarity: ω>0, α≥0, β≥0, α+β<1; γ unconstrained (penalised if σ²<=0).
    """
    omega, alpha, beta = params[0], params[1], params[2]
    gammas = params[3:] if len(params) > 3 else None
    if omega <= 0 or alpha < 0 or beta < 0 or alpha + beta >= 0.999:
        return 1e10
    n = len(r)
    sigma2 = np.empty(n)
    sigma2[0] = max(np.var(r), 1e-8)
    for t in range(1, n):
        base = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
        if X is not None and gammas is not None:
            base += float(X[t-1] @ gammas)
        sigma2[t] = max(base, 1e-12)
    ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + r**2 / sigma2)
    return -ll


def _simulate_sigma2_path(
    params: np.ndarray,
    r: np.ndarray,
    X: np.ndarray | None,
    init_var: float,
) -> tuple[np.ndarray, int]:
    """Simulate conditional variance path and count 1e-12 clamps."""
    omega, alpha, beta = params[0], params[1], params[2]
    gammas = params[3:] if len(params) > 3 else None
    sigma2 = np.empty(len(r))
    sigma2[0] = max(init_var, 1e-8)
    clamp_count = 0
    for t in range(1, len(r)):
        base = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
        if X is not None and gammas is not None:
            base += float(X[t - 1] @ gammas)
        if base <= 1e-12:
            clamp_count += 1
        sigma2[t] = max(base, 1e-12)
    return sigma2, clamp_count


def fit_garch_with_x(r_train: np.ndarray, X_train: np.ndarray | None) -> dict:
    """Fit GARCH(1,1) [+exog] via scipy.optimize (Nelder-Mead fallback after L-BFGS).

    Returns fit summary with multistart diagnostics.
    Falls back to grid init if main optimisation fails (per K1213).
    """
    k = 0 if X_train is None else X_train.shape[1]
    # init: typical GARCH ω≈1e-6, α≈0.1, β≈0.85; γ≈0
    x0 = np.array([1e-6, 0.10, 0.85] + [0.0] * k)

    def obj(p):
        return _garch_neg_loglik(p, r_train, X_train)

    best_res = None
    best_nll = np.inf
    attempted_starts = 0
    finite_nll_starts = 0
    used_fallback = False
    # Multi-start (per K1213 pooled-MLE rule; here 5 inits since simpler model)
    rng = np.random.default_rng(SEED)
    starts = [x0]
    for _ in range(4):
        perturb = x0.copy()
        perturb[0] *= rng.uniform(0.3, 3.0)
        perturb[1] = rng.uniform(0.02, 0.20)
        perturb[2] = rng.uniform(0.70, 0.95)
        for i in range(3, 3 + k):
            perturb[i] = rng.normal(0, 1e-4)
        starts.append(perturb)

    for s in starts:
        attempted_starts += 1
        try:
            res = optimize.minimize(obj, s, method="L-BFGS-B",
                                    bounds=[(1e-10, None), (0, 0.5), (0, 0.999)]
                                           + [(None, None)] * k,
                                    options={"maxiter": 500})
            if np.isfinite(res.fun):
                finite_nll_starts += 1
            if res.fun < best_nll and np.isfinite(res.fun):
                best_nll = res.fun
                best_res = res
        except Exception:
            continue

    if best_res is None:
        # Last-ditch Nelder-Mead
        used_fallback = True
        best_res = optimize.minimize(obj, x0, method="Nelder-Mead",
                                     options={"maxiter": 2000})
        attempted_starts += 1
        if np.isfinite(best_res.fun):
            finite_nll_starts += 1

    params = best_res.x
    sigma2, clamp_count = _simulate_sigma2_path(
        params, r_train, X_train, init_var=float(np.var(r_train))
    )
    termination_flag = getattr(best_res, "message", "")
    if isinstance(termination_flag, bytes):
        termination_flag = termination_flag.decode("utf-8", errors="replace")

    return {
        "params": params.tolist(),
        "nll": float(best_nll if np.isfinite(best_nll) else best_res.fun),
        "sigma2_terminal": float(sigma2[-1]),
        "success": bool(best_res.success) if hasattr(best_res, "success") else True,
        "termination_flag": (
            f"{'fallback_nelder_mead: ' if used_fallback else ''}{termination_flag}"
        ).strip(),
        "nll_finite_ratio": float(finite_nll_starts / max(attempted_starts, 1)),
        "sigma2_clamp_ratio": float(clamp_count / max(len(r_train) - 1, 1)),
        "k_exog": k,
    }


def forecast_garch_one_step(
    fit: dict,
    r_prev: float,
    sigma2_prev: float,
    x_prev: np.ndarray | None,
) -> float:
    """One-step-ahead σ²_t forecast given fitted params and lagged inputs."""
    params = np.asarray(fit["params"])
    omega, alpha, beta = params[0], params[1], params[2]
    gammas = params[3:] if len(params) > 3 else None
    base = omega + alpha * r_prev**2 + beta * sigma2_prev
    if x_prev is not None and gammas is not None:
        base += float(x_prev @ gammas)
    return max(base, 1e-12)


def garch_rolling_forecast(
    r: np.ndarray,
    X: np.ndarray | None,
    is_end_idx: int,
) -> tuple[np.ndarray, dict]:
    """Fit on r[:is_end_idx] then walk-forward σ² updates on r[is_end_idx:].

    Use fixed-parameter rolling (no refit each day) for compute tractability.
    Returns σ²_t forecasts for OOS period (length = len(r) - is_end_idx).
    """
    X_train = X[:is_end_idx] if X is not None else None
    fit = fit_garch_with_x(r[:is_end_idx], X_train)
    params = np.asarray(fit["params"])
    sigma2, _ = _simulate_sigma2_path(
        params, r, X, init_var=float(np.var(r[:is_end_idx]))
    )

    oos_forecasts = sigma2[is_end_idx:]
    return oos_forecasts, fit


# ------------------------------------------------------------------
# Loss functions
# ------------------------------------------------------------------
def qlike(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """Patton (2011) QLIKE: y/ŷ - log(y/ŷ) - 1. Robust to noisy proxy.
    y_true and y_pred must be strictly positive (variances)."""
    y_true = np.maximum(y_true, 1e-12)
    y_pred = np.maximum(y_pred, 1e-12)
    return y_true / y_pred - np.log(y_true / y_pred) - 1.0


def mse(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    return (y_true - y_pred) ** 2


# ------------------------------------------------------------------
# Diebold-Mariano + bootstrap
# ------------------------------------------------------------------
def dm_test(d: np.ndarray, h: int = 1) -> dict:
    """Diebold-Mariano on loss-diff series d = L_a - L_b. h=forecast horizon."""
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 10:
        return {"dm_stat": float("nan"), "p_value": float("nan"), "n": n}
    mean_d = d.mean()
    # Newey-West variance estimator
    # lag selection: floor(4 * (n/100)^(2/9))
    L = max(1, int(np.floor(4 * (n / 100) ** (2 / 9))))
    gamma0 = np.var(d, ddof=1)
    var_d = gamma0
    for lag in range(1, L + 1):
        cov = np.mean((d[lag:] - mean_d) * (d[:-lag] - mean_d))
        weight = 1.0 - lag / (L + 1)
        var_d += 2 * weight * cov
    var_d = max(var_d, 1e-12)
    dm_stat = mean_d / np.sqrt(var_d / n)
    p = 2 * (1 - stats.norm.cdf(abs(dm_stat)))
    return {
        "dm_stat": float(dm_stat),
        "p_value": float(p),
        "n": int(n),
        "lag_nw": int(L),
        "mean_loss_diff": float(mean_d),
    }


def block_bootstrap_ci(
    d: np.ndarray, n_boot: int = DM_N_BOOT,
    block_len: int = DM_BLOCK_LEN, seed: int = SEED,
) -> dict:
    """Moving block bootstrap (fixed length) CI for mean loss diff."""
    d = d[~np.isnan(d)]
    n = len(d)
    if n < block_len * 2:
        return {"ci_low": float("nan"), "ci_high": float("nan"), "n_boot": 0}
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_boot)
    n_blocks = int(np.ceil(n / block_len))
    for b in range(n_boot):
        starts = rng.integers(0, n - block_len + 1, size=n_blocks)
        sample = np.concatenate([d[s:s + block_len] for s in starts])[:n]
        boot_means[b] = sample.mean()
    return {
        "ci_low": float(np.quantile(boot_means, 0.025)),
        "ci_high": float(np.quantile(boot_means, 0.975)),
        "boot_mean": float(boot_means.mean()),
        "n_boot": int(n_boot),
        "block_len": int(block_len),
        "seed": int(seed),
    }


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
def main() -> dict:
    print("[K1424] Building dataset (load K1423 cache, compute Hurst, build lags) ...")
    df = build_dataset()
    print(f"[K1424] N={len(df)} obs, {df.index[0].date()} ~ {df.index[-1].date()}")

    # Splits
    is_mask = (df.index >= IS_START) & (df.index <= IS_END)
    oos_mask = (df.index >= OOS_START) & (df.index <= OOS_END)
    is_end_idx = int(is_mask.sum())
    n_oos = int(oos_mask.sum())
    print(f"[K1424] IS={is_end_idx} obs (2010-2019), OOS={n_oos} obs (2020-2026)")

    # Restrict to IS ∪ OOS window
    df = df[is_mask | oos_mask].copy()
    is_end_idx = int(((df.index >= IS_START) & (df.index <= IS_END)).sum())

    r = df["ret"].values
    rv2 = df["rv2"].values  # GARCH target (proxy)

    # =========================
    # GARCH-family forecasts
    # =========================
    results: dict = {
        "k_id": "K1424",
        "title": "Hurst as GARCH covariate — SPY OOS forecasting",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lineage": {
            "parent_k": "K1423_ewma_hurst_pilot",
            "rationale": "K1423 ρ(H,VIX)=+0.32 descriptive; K1424 tests forecasting use",
        },
        "data": {
            "symbol": "SPY",
            "covar": ["^VIX", "EWMA-Hurst λ=0.94 (from K1423)"],
            "n_obs_total": int(len(df)),
            "is_period": [IS_START, IS_END],
            "oos_period": [OOS_START, OOS_END],
            "n_is": is_end_idx,
            "n_oos": int(len(df) - is_end_idx),
            "source": "yfinance (cached via K1423)",
        },
        "config": {
            "hurst_window": HURST_WINDOW,
            "hurst_lambda": HURST_LAMBDA,
            "dm_n_boot": DM_N_BOOT,
            "dm_block_len": DM_BLOCK_LEN,
            "seed": SEED,
        },
        "lookahead_audit": {
            "h_shifted": True,
            "vix_shifted": True,
            "rv_lagged": True,
            "split_strict_by_time": True,
            "rule": "all covariates use t-1 info only; verified at build_dataset()",
        },
        "models": {},
    }

    print("[K1424] Fitting GARCH(1,1) baseline ...")
    f_g0, fit_g0 = garch_rolling_forecast(r, None, is_end_idx)
    print("[K1424] Fitting GARCH + H ...")
    X_h = df[["h_lag"]].values
    f_gh, fit_gh = garch_rolling_forecast(r, X_h, is_end_idx)
    print("[K1424] Fitting GARCH + VIX ...")
    X_v = df[["vix_lag"]].values
    f_gv, fit_gv = garch_rolling_forecast(r, X_v, is_end_idx)
    print("[K1424] Fitting GARCH + H + VIX ...")
    X_hv = df[["h_lag", "vix_lag"]].values
    f_ghv, fit_ghv = garch_rolling_forecast(r, X_hv, is_end_idx)

    rv2_oos = rv2[is_end_idx:]
    forecasts_garch = {
        "garch_baseline": (f_g0, fit_g0),
        "garch_plus_h":   (f_gh, fit_gh),
        "garch_plus_vix": (f_gv, fit_gv),
        "garch_plus_h_vix": (f_ghv, fit_ghv),
    }

    for name, (fc, fit) in forecasts_garch.items():
        l_q = qlike(rv2_oos, fc)
        l_m = mse(rv2_oos, fc)
        results["models"][name] = {
            "type": "GARCH",
            "fit": fit,
            "qlike_mean": float(np.nanmean(l_q)),
            "qlike_median": float(np.nanmedian(l_q)),
            "mse_mean": float(np.nanmean(l_m)),
            "n_oos": int(len(fc)),
        }

    # =========================
    # DM tests
    # =========================
    print("[K1424] Running DM tests + block bootstrap ...")
    dm_comparisons: list[dict] = []

    # GARCH family pairwise (vs baseline) on QLIKE
    base_q = qlike(rv2_oos, f_g0)
    for name, fc in [("garch_plus_h", f_gh),
                     ("garch_plus_vix", f_gv),
                     ("garch_plus_h_vix", f_ghv)]:
        new_q = qlike(rv2_oos, fc)
        d = base_q - new_q  # positive d → new model has lower loss = better
        dm_comparisons.append({
            "compare": f"garch_baseline vs {name}",
            "loss": "QLIKE",
            "sign_convention": "positive d → 'new' model lower loss (better)",
            "dm": dm_test(d),
            "bootstrap_ci": block_bootstrap_ci(d),
        })

    # GARCH H+VIX vs GARCH VIX → incremental contribution of H beyond VIX
    d_inc = qlike(rv2_oos, f_gv) - qlike(rv2_oos, f_ghv)
    dm_comparisons.append({
        "compare": "garch_plus_vix vs garch_plus_h_vix",
        "loss": "QLIKE",
        "interpretation": "incremental value of H beyond VIX control",
        "dm": dm_test(d_inc),
        "bootstrap_ci": block_bootstrap_ci(d_inc),
    })

    results["dm_tests"] = dm_comparisons

    # =========================
    # Per-year OOS breakdown (avoid over-claim from single window)
    # =========================
    print("[K1424] Per-year OOS breakdown ...")
    oos_dates = df.index[is_end_idx:]
    years = pd.Series(oos_dates).dt.year.values
    per_year: dict = {}
    for yr in np.unique(years):
        mask = years == yr
        if mask.sum() < 30:
            continue
        per_year[int(yr)] = {
            "n": int(mask.sum()),
            "qlike_garch_baseline": float(np.nanmean(qlike(rv2_oos[mask], f_g0[mask]))),
            "qlike_garch_plus_h": float(np.nanmean(qlike(rv2_oos[mask], f_gh[mask]))),
            "qlike_garch_plus_vix": float(np.nanmean(qlike(rv2_oos[mask], f_gv[mask]))),
            "qlike_garch_plus_h_vix": float(np.nanmean(qlike(rv2_oos[mask], f_ghv[mask]))),
        }
    results["per_year_oos"] = per_year

    # =========================
    # Persist artifacts
    # =========================
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fc_df = pd.DataFrame({
        "date": oos_dates,
        "rv2_true": rv2_oos,
        "garch_baseline": f_g0,
        "garch_plus_h": f_gh,
        "garch_plus_vix": f_gv,
        "garch_plus_h_vix": f_ghv,
    })
    fc_df.to_csv(DATA_DIR / "K1424_forecasts.csv", index=False)

    loss_df = pd.DataFrame({
        "date": oos_dates,
        "qlike_garch_baseline": qlike(rv2_oos, f_g0),
        "qlike_garch_plus_h": qlike(rv2_oos, f_gh),
        "qlike_garch_plus_vix": qlike(rv2_oos, f_gv),
        "qlike_garch_plus_h_vix": qlike(rv2_oos, f_ghv),
    })
    loss_df.to_csv(DATA_DIR / "K1424_loss_diff_series.csv", index=False)

    results["artifacts"] = {
        "forecasts_csv": str((DATA_DIR / "K1424_forecasts.csv").relative_to(HERE.parent.parent)),
        "loss_csv": str((DATA_DIR / "K1424_loss_diff_series.csv").relative_to(HERE.parent.parent)),
    }

    # =========================
    # Verdict heuristic (descriptive only; final verdict by main thread post-Codex)
    # =========================
    print("[K1424] Computing heuristic verdict ...")
    incremental_dm = next(
        (c for c in dm_comparisons
         if c["compare"] == "garch_plus_vix vs garch_plus_h_vix"), None
    )
    if incremental_dm and not np.isnan(incremental_dm["dm"]["p_value"]):
        p = incremental_dm["dm"]["p_value"]
        mean_d = incremental_dm["dm"]["mean_loss_diff"]
        if p < 0.05 and mean_d > 0:
            verdict_hint = "PASS_candidate: H provides incremental value beyond VIX (DM p<0.05, d>0)"
        elif p < 0.10 and mean_d > 0:
            verdict_hint = "CONDITIONAL_PASS_candidate: H marginally incremental (p<0.10)"
        else:
            verdict_hint = "NULL_candidate: H not incremental beyond VIX"
    else:
        verdict_hint = "INCONCLUSIVE: DM test produced NaN"
    results["verdict_hint"] = verdict_hint
    print(f"[K1424] verdict_hint = {verdict_hint}")

    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str))
    print(f"[K1424] Results → {RESULTS_PATH}")
    return results


if __name__ == "__main__":
    main()
