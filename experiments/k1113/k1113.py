"""
K1113 — Firm-level covariate rule for Paper 2 selection (CONFIRMATORY, pre-registered)

Motivation
----------
K1109 confirmed (pre-registered N=31) that **sector dummies fail**:
  Joint F(7,20)=1.31, p=0.297; no BH-FDR survives.
  fabless raw p=0.040 but BH-adj p=0.278.

But K1109 regression_full showed in White-SE:
  log_mktcap_z: t=-2.38, p_white=0.027  (marginal)
  beta_rolling_z: t=2.84, p_white=0.010  (marginal)

K1113 pre-registers a continuous-covariate-only regression, expanding to 6 covariates.
Paper 2 selection rule will be built from fitted model → Tier A/B/C classification.

Pre-registration (locked before looking at extended covariates regression):
  H1 (primary):  at least one covariate survives BH-FDR (adj p<0.05).
  H2 (size):     log_mktcap coefficient is negative with p<0.10.
  H3 (vol):      price_volatility coefficient is positive with p<0.10.
  H4 (CV):       5-fold CV R² > 0 (fold-seed=42).
  H5 (Tier A):   at least 3 firms classified Tier A (predicted θ₂>0, CI excludes 0).

Design
------
- Input  : K1109 firm_level_results.csv (31 firms × θ₂ already estimated)
- Add    : log_avg_volume, price_volatility, ind_momentum from yfinance (cached parquet).
- Analyst_count: yfinance .info['numberOfAnalystOpinions'], optional.
- Regress: θ₂ ~ log_mktcap + beta + earn_freq + log_avg_volume + price_volatility + ind_momentum
- Tests  : OLS + White HC1; BH-FDR on 6 covariates; bootstrap 5000 reps for each coef 95% CI.
- CV     : 5-fold CV with GroupKFold on firms, seed=42; report CV R² + CV MAE.
- Tier classification based on in-sample predicted θ₂ and prediction SE.

References
----------
- K1104 (cross-sectional heterogeneity of θ₂, N=24 from a-prior stratification)
- K1106b (cherry-picked sector sample, later disproven in K1109)
- K1109 (pre-registered random sector sample, rejected sector dummies)
- E052, E053 (experiences on cherry-pick and pre-registration)
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------------------------------------------------------------
# Paths & pre-registration hash
# ---------------------------------------------------------------------

EXP_DIR = Path(__file__).resolve().parent
K1109_DIR = EXP_DIR.parent / "k1109"
DATA_DIR = EXP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
PARQUET_CACHE = K1109_DIR / "data"  # reuse K1109 price parquets

FIRM_LEVEL_CSV = K1109_DIR / "firm_level_results.csv"

RNG_SEED = 42
BOOT_N = 5000
CV_FOLDS = 5
TIER_T_CRIT = 1.96  # 95% one-sided? actually two-sided threshold

# Pre-registered covariate order (locked 2026-04-13 BEFORE running extended regression)
PRIMARY_COVARIATES = [
    "log_mktcap",
    "beta_rolling_0050",
    "earnings_freq_per_year",
    "log_avg_volume",
    "price_volatility",
    "ind_momentum",
]


# ---------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------

def _log(msg: str) -> None:
    print(msg, flush=True)


def _read_prices(ticker: str) -> pd.DataFrame | None:
    """Load cached parquet from K1109; return None if missing."""
    p = PARQUET_CACHE / f"{ticker}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    # Standardize column names
    if "Close" not in df.columns:
        # yfinance multi-index handling may have happened
        lc = {c.lower(): c for c in df.columns}
        if "close" in lc:
            df = df.rename(columns={lc["close"]: "Close"})
        else:
            return None
    df.index = pd.to_datetime(df.index)
    return df.sort_index()


def _compute_vol_momentum_volume(
    ticker: str, bench_df: pd.DataFrame | None = None
) -> dict[str, float | None]:
    """Compute log_avg_volume, price_volatility, ind_momentum from cached price."""
    df = _read_prices(ticker)
    if df is None:
        return {"log_avg_volume": None, "price_volatility": None, "ind_momentum": None}

    # Ensure numeric
    for col in ("Close", "Volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Past 252-day window (use last 252 trading days of available data)
    df = df.dropna(subset=["Close"])
    if len(df) < 260:
        return {"log_avg_volume": None, "price_volatility": None, "ind_momentum": None}
    tail = df.iloc[-252:].copy()

    # price_volatility: std of daily log return, annualized
    log_ret = np.log(tail["Close"] / tail["Close"].shift(1)).dropna()
    price_vol = float(log_ret.std(ddof=1) * np.sqrt(252))

    # log_avg_volume: log of mean daily volume
    if "Volume" in tail.columns and tail["Volume"].notna().any():
        avg_vol = float(tail["Volume"].mean())
        log_avg_vol = float(np.log(max(avg_vol, 1.0)))
    else:
        log_avg_vol = None

    # ind_momentum: past-252-day return of ticker minus past-252-day return of 0050.TW
    ticker_ret252 = float(tail["Close"].iloc[-1] / tail["Close"].iloc[0] - 1.0)
    if bench_df is not None and len(bench_df) >= 260:
        bench_tail = bench_df.iloc[-252:]
        bench_ret252 = float(
            bench_tail["Close"].iloc[-1] / bench_tail["Close"].iloc[0] - 1.0
        )
        ind_mom = ticker_ret252 - bench_ret252
    else:
        ind_mom = None
    return {
        "log_avg_volume": log_avg_vol,
        "price_volatility": price_vol,
        "ind_momentum": ind_mom,
    }


def _compute_analyst_count(ticker: str) -> int | None:
    """Optional: fetch analyst opinion count from yfinance .info. May return None."""
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        info = t.info
        n = info.get("numberOfAnalystOpinions")
        if n is None or (isinstance(n, float) and np.isnan(n)):
            return None
        return int(n)
    except Exception:
        return None


# ---------------------------------------------------------------------
# Regression & diagnostics (pure-numpy to avoid external dep quirks)
# ---------------------------------------------------------------------

def _ols(X: np.ndarray, y: np.ndarray) -> dict:
    """OLS with HC1 robust SE. X must include intercept column."""
    n, k = X.shape
    XtX = X.T @ X
    XtX_inv = np.linalg.pinv(XtX)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    dof = n - k
    sigma2 = float(resid @ resid / max(dof, 1))
    cov_ols = sigma2 * XtX_inv
    se_ols = np.sqrt(np.diag(cov_ols))

    # White (HC0) then HC1 scaling
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    cov_hc0 = XtX_inv @ S @ XtX_inv
    cov_hc1 = cov_hc0 * n / max(dof, 1)
    se_hc1 = np.sqrt(np.diag(cov_hc1))

    tvals = beta / np.where(se_ols > 0, se_ols, np.nan)
    tvals_w = beta / np.where(se_hc1 > 0, se_hc1, np.nan)

    from scipy import stats as sstats

    pvals = 2 * (1 - sstats.t.cdf(np.abs(tvals), df=max(dof, 1)))
    pvals_w = 2 * (1 - sstats.t.cdf(np.abs(tvals_w), df=max(dof, 1)))

    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    r2_adj = 1 - (1 - r2) * (n - 1) / max(dof, 1) if not np.isnan(r2) else np.nan

    return {
        "beta": beta,
        "se_ols": se_ols,
        "se_hc1": se_hc1,
        "t_ols": tvals,
        "t_hc1": tvals_w,
        "p_ols": pvals,
        "p_hc1": pvals_w,
        "r2": r2,
        "r2_adj": r2_adj,
        "n": n,
        "dof": dof,
        "ss_res": ss_res,
        "ss_tot": ss_tot,
        "cov_hc1": cov_hc1,
    }


def _bh_adjust(pvals: np.ndarray) -> np.ndarray:
    """Benjamini-Hochberg FDR adjustment (Benjamini & Hochberg 1995)."""
    p = np.asarray(pvals, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adj_sorted = np.minimum.accumulate((ranked * n / np.arange(1, n + 1))[::-1])[::-1]
    adj = np.empty(n)
    adj[order] = np.clip(adj_sorted, 0, 1)
    return adj


def _bootstrap_coefs(
    X: np.ndarray, y: np.ndarray, n_boot: int = BOOT_N, seed: int = RNG_SEED
) -> np.ndarray:
    """Pairs-bootstrap beta CI. Returns (n_boot, k) array of beta draws."""
    rng = np.random.default_rng(seed)
    n = len(y)
    k = X.shape[1]
    out = np.empty((n_boot, k))
    for b in range(n_boot):
        idx = rng.integers(0, n, size=n)
        Xb, yb = X[idx], y[idx]
        try:
            bb = np.linalg.pinv(Xb.T @ Xb) @ (Xb.T @ yb)
        except Exception:
            bb = np.full(k, np.nan)
        out[b] = bb
    return out


def _kfold_cv(X: np.ndarray, y: np.ndarray, k: int = CV_FOLDS, seed: int = RNG_SEED) -> dict:
    """K-fold CV, returning CV R² and MAE. Uses fixed seed shuffle.

    NOTE: This accepts an ALREADY-DESIGNED matrix X (intercept + covariates).
    Use `_kfold_cv_with_refit` for leakage-free z-scoring per fold.
    """
    rng = np.random.default_rng(seed)
    n = len(y)
    idx = rng.permutation(n)
    fold_assign = np.array_split(idx, k)
    preds = np.full(n, np.nan)
    for fold in fold_assign:
        mask = np.ones(n, dtype=bool)
        mask[fold] = False
        X_tr, y_tr = X[mask], y[mask]
        X_te = X[fold]
        try:
            beta_tr = np.linalg.pinv(X_tr.T @ X_tr) @ (X_tr.T @ y_tr)
            preds[fold] = X_te @ beta_tr
        except Exception:
            preds[fold] = np.nan
    resid = y - preds
    ss_res = float(np.nansum(resid ** 2))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    cv_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    cv_mae = float(np.nanmean(np.abs(resid)))
    return {"cv_r2": cv_r2, "cv_mae": cv_mae, "preds": preds.tolist()}


def _kfold_cv_leakage_free(
    X_raw: np.ndarray, y: np.ndarray, k: int = CV_FOLDS, seed: int = RNG_SEED
) -> dict:
    """K-fold CV with per-fold z-scoring (leakage-free).

    X_raw has shape (n, p_raw) containing covariates WITHOUT intercept, WITHOUT z-scoring.
    For each fold:
        - compute mean/sd on training fold
        - apply that transform to test fold
        - refit OLS
        - predict on test fold
    """
    rng = np.random.default_rng(seed)
    n = len(y)
    idx = rng.permutation(n)
    fold_assign = np.array_split(idx, k)
    preds = np.full(n, np.nan)
    for fold in fold_assign:
        mask = np.ones(n, dtype=bool)
        mask[fold] = False
        Xr_tr, y_tr = X_raw[mask], y[mask]
        Xr_te = X_raw[fold]
        mu = Xr_tr.mean(axis=0)
        sd = Xr_tr.std(axis=0, ddof=1)
        sd_safe = np.where(sd > 0, sd, 1.0)
        Xz_tr = (Xr_tr - mu) / sd_safe
        Xz_te = (Xr_te - mu) / sd_safe  # use training mu/sd on test
        # Add intercept
        X_tr = np.column_stack([np.ones(len(Xz_tr)), Xz_tr])
        X_te = np.column_stack([np.ones(len(Xz_te)), Xz_te])
        try:
            beta_tr = np.linalg.pinv(X_tr.T @ X_tr) @ (X_tr.T @ y_tr)
            preds[fold] = X_te @ beta_tr
        except Exception:
            preds[fold] = np.nan
    resid = y - preds
    ss_res = float(np.nansum(resid ** 2))
    ss_tot = float(((y - y.mean()) ** 2).sum())
    cv_r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan
    cv_mae = float(np.nanmean(np.abs(resid)))
    return {
        "cv_r2": cv_r2,
        "cv_mae": cv_mae,
        "preds": preds.tolist(),
        "note": "leakage-free: z-score mu/sd computed within each training fold only",
    }


# ---------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------

def load_firm_panel() -> pd.DataFrame:
    df = pd.read_csv(FIRM_LEVEL_CSV)
    _log(f"[panel] loaded {len(df)} firms from K1109 firm_level_results.csv")
    _log(f"        columns: {list(df.columns)}")
    return df


def build_covariates(df: pd.DataFrame) -> pd.DataFrame:
    # Benchmark for momentum
    bench = _read_prices("0050.TW")
    if bench is None:
        _log("[warn] 0050.TW parquet not in K1109 cache; ind_momentum will be NaN")

    rows = []
    for _, row in df.iterrows():
        ticker = row["ticker"]
        ext = _compute_vol_momentum_volume(ticker, bench_df=bench)
        rows.append({"code": row["code"], "ticker": ticker, **ext})
    ext_df = pd.DataFrame(rows)
    merged = df.merge(ext_df, on=["code", "ticker"], how="left")
    _log(f"[covar] extended covariates built, missing counts:")
    for c in ("log_avg_volume", "price_volatility", "ind_momentum"):
        _log(f"        {c}: {merged[c].isna().sum()} NaN")
    return merged


def _safe_float(x):
    if x is None:
        return np.nan
    try:
        fx = float(x)
        return fx if np.isfinite(fx) else np.nan
    except Exception:
        return np.nan


def _zscore(s: pd.Series) -> pd.Series:
    s = s.astype(float)
    mu, sd = s.mean(), s.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return s * 0
    return (s - mu) / sd


def run_regression(panel: pd.DataFrame) -> dict:
    # Keep only firms with finite θ₂ and θ₂_se
    panel = panel.copy()
    panel["theta2"] = panel["theta2"].astype(float)
    panel["theta2_se"] = pd.to_numeric(panel["theta2_se"], errors="coerce")
    # Note: K1109 had 1 firm (Synnex) with missing SE — we still include in regression
    # since OLS uses θ₂ not SE. But we drop firms with NaN θ₂.
    before_n = len(panel)
    panel = panel.dropna(subset=["theta2"]).reset_index(drop=True)
    _log(f"[regression] kept {len(panel)}/{before_n} firms with non-null θ₂")

    # Fill covariates — drop firms missing any primary covariate
    cov_cols = PRIMARY_COVARIATES
    for c in cov_cols:
        if c not in panel.columns:
            raise RuntimeError(f"missing covariate column: {c}")
    for c in cov_cols:
        panel[c] = pd.to_numeric(panel[c], errors="coerce")

    keep_mask = panel[cov_cols].notna().all(axis=1)
    dropped = panel.loc[~keep_mask, ["code", "ticker"]].to_dict(orient="records")
    panel = panel.loc[keep_mask].reset_index(drop=True)
    _log(f"[regression] after covariate NA drop: n={len(panel)}")
    if dropped:
        _log(f"[regression] dropped firms: {dropped}")

    # Z-score covariates (ease of coefficient comparison)
    for c in cov_cols:
        panel[f"{c}_z"] = _zscore(panel[c])

    X_cols = [f"{c}_z" for c in cov_cols]
    X = np.column_stack([np.ones(len(panel))] + [panel[c].to_numpy() for c in X_cols])
    y = panel["theta2"].to_numpy()

    res = _ols(X, y)

    param_names = ["const"] + X_cols
    # BH-FDR on non-intercept covariates (HC1 p-values)
    p_for_bh = res["p_hc1"][1:]
    bh_adj = _bh_adjust(p_for_bh)

    bh_dict = {name: float(adj) for name, adj in zip(X_cols, bh_adj)}
    coef_table = []
    for i, name in enumerate(param_names):
        coef_table.append({
            "name": name,
            "coef": float(res["beta"][i]),
            "se_ols": float(res["se_ols"][i]),
            "se_hc1": float(res["se_hc1"][i]),
            "t_ols": float(res["t_ols"][i]),
            "t_hc1": float(res["t_hc1"][i]),
            "p_ols": float(res["p_ols"][i]),
            "p_hc1": float(res["p_hc1"][i]),
            "bh_adj_p_hc1": bh_dict.get(name, None),
        })

    # Bootstrap CIs
    boots = _bootstrap_coefs(X, y, n_boot=BOOT_N, seed=RNG_SEED)
    for i, row in enumerate(coef_table):
        bi = boots[:, i]
        bi = bi[np.isfinite(bi)]
        if len(bi) > 0:
            row["boot_ci_low"] = float(np.quantile(bi, 0.025))
            row["boot_ci_high"] = float(np.quantile(bi, 0.975))
            row["boot_se"] = float(bi.std(ddof=1))
        else:
            row["boot_ci_low"] = row["boot_ci_high"] = row["boot_se"] = None

    # CV — leakage-free (z-score mu/sd computed per training fold)
    X_raw_no_intercept = np.column_stack([panel[c].to_numpy() for c in cov_cols])
    cv = _kfold_cv_leakage_free(X_raw_no_intercept, y, k=CV_FOLDS, seed=RNG_SEED)
    _log(f"[CV] leakage-free R²={cv['cv_r2']:.4f}, MAE={cv['cv_mae']:.3e}")

    # AIC / BIC proxy (Gaussian)
    n, kk = X.shape
    llf = -0.5 * n * (np.log(2 * np.pi) + np.log(res["ss_res"] / max(n, 1)) + 1)
    aic = 2 * kk - 2 * llf
    bic = kk * np.log(n) - 2 * llf

    return {
        "panel_after_dropna": panel[[
            "code", "ticker", "name", "sector",
            "theta2", "theta2_se", "theta2_t",
            *cov_cols, *X_cols,
        ]].to_dict(orient="records"),
        "coefficients": coef_table,
        "r2": float(res["r2"]),
        "r2_adj": float(res["r2_adj"]),
        "n": int(res["n"]),
        "dof": int(res["dof"]),
        "ss_res": float(res["ss_res"]),
        "ss_tot": float(res["ss_tot"]),
        "aic": float(aic),
        "bic": float(bic),
        "llf": float(llf),
        "cv": cv,
        "bootstrap_seed": RNG_SEED,
        "bootstrap_n": BOOT_N,
        "param_names": param_names,
        "design_notes": {
            "intercept_included": True,
            "covariate_order_locked": cov_cols,
            "transform": "all covariates z-scored (mean 0, sd 1 across sample)",
            "analyst_count_included": False,
            "standard_errors": "HC1 White + OLS both reported; BH-FDR applied to HC1 p-values of 6 covariates.",
        },
        "X_matrix_shape": list(X.shape),
        "cov_hc1": res["cov_hc1"].tolist(),
    }


def assess_hypotheses(reg: dict) -> dict:
    coef_map = {c["name"]: c for c in reg["coefficients"]}
    # H1: any BH-adj p < 0.05
    min_bh = min(c["bh_adj_p_hc1"] for c in reg["coefficients"] if c["name"] != "const")
    survivors = [
        c["name"]
        for c in reg["coefficients"]
        if c["name"] != "const" and c["bh_adj_p_hc1"] is not None and c["bh_adj_p_hc1"] < 0.05
    ]
    # H2: log_mktcap_z negative with p<0.10 (HC1)
    size_coef = coef_map["log_mktcap_z"]
    h2_pass = size_coef["coef"] < 0 and size_coef["p_hc1"] < 0.10

    # H3: price_volatility_z positive with p<0.10
    vol_coef = coef_map["price_volatility_z"]
    h3_pass = vol_coef["coef"] > 0 and vol_coef["p_hc1"] < 0.10

    # H4: CV R² > 0
    h4_pass = reg["cv"]["cv_r2"] > 0

    return {
        "H1_any_bh_survives": {
            "rule": "At least 1 covariate BH-adj p_hc1 < 0.05",
            "min_bh_adj": float(min_bh),
            "survivors": survivors,
            "passes": len(survivors) > 0,
        },
        "H2_size_negative": {
            "rule": "log_mktcap_z coef < 0 AND p_hc1 < 0.10",
            "coef": size_coef["coef"],
            "p_hc1": size_coef["p_hc1"],
            "passes": bool(h2_pass),
        },
        "H3_vol_positive": {
            "rule": "price_volatility_z coef > 0 AND p_hc1 < 0.10",
            "coef": vol_coef["coef"],
            "p_hc1": vol_coef["p_hc1"],
            "passes": bool(h3_pass),
        },
        "H4_cv_r2_positive": {
            "rule": "5-fold CV R² > 0",
            "cv_r2": reg["cv"]["cv_r2"],
            "passes": bool(h4_pass),
        },
    }


def tier_classification(reg: dict, panel_df: pd.DataFrame) -> dict:
    """
    For each firm, compute:
      predicted θ₂ = X_i @ β_hat
      PREDICTION SE (not fitted-mean SE):
          pred_se^2 = σ̂² + x' Cov_HC1 x
      where σ̂² = ss_res / dof (residual variance).
      predicted t = pred / pred_se
    Tier A : 95% prediction CI is fully above 0  (pred - 1.96*pred_se > 0)
    Tier C : 95% prediction CI is fully below 0
    Tier B : CI overlaps 0
    """
    panel = pd.DataFrame(reg["panel_after_dropna"])
    betas = np.array([c["coef"] for c in reg["coefficients"]])
    cov_hc1 = np.array(reg["cov_hc1"])
    X_cols = reg["param_names"][1:]  # skip const
    X = np.column_stack([
        np.ones(len(panel)),
        *(panel[c].to_numpy() for c in X_cols),
    ])
    pred = X @ betas
    # Coefficient-uncertainty term (SE of fitted mean)
    coef_var = np.einsum("ij,jk,ik->i", X, cov_hc1, X)
    # Residual variance (unexplained)
    resid_var = reg["ss_res"] / max(reg["dof"], 1)
    # Full prediction variance
    pred_var = resid_var + coef_var
    pred_se = np.sqrt(np.maximum(pred_var, 0))
    t_pred = pred / np.where(pred_se > 0, pred_se, np.nan)

    panel = panel.copy()
    panel["predicted_theta2"] = pred
    panel["predicted_se"] = pred_se
    panel["predicted_t"] = t_pred
    panel["predicted_ci_low"] = pred - 1.96 * pred_se
    panel["predicted_ci_high"] = pred + 1.96 * pred_se

    def _assign(row):
        if row["predicted_ci_low"] > 0:
            return "A"
        if row["predicted_ci_high"] < 0:
            return "C"
        return "B"

    panel["tier"] = panel.apply(_assign, axis=1)

    tiers = {}
    for tier in ("A", "B", "C"):
        sub = panel[panel["tier"] == tier]
        tiers[tier] = {
            "n_firms": int(len(sub)),
            "firms": sub[[
                "code", "ticker", "name", "sector",
                "theta2", "theta2_se", "theta2_t",
                "predicted_theta2", "predicted_se",
                "predicted_ci_low", "predicted_ci_high",
            ]].to_dict(orient="records"),
        }
    return {
        "tiers": tiers,
        "panel_with_predictions": panel.to_dict(orient="records"),
    }


def try_analyst_supplement(panel: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """Fetch analyst_count for each ticker. Return (panel with col, n_ok, n_null)."""
    analyst_counts = []
    n_ok = n_null = 0
    for tkr in panel["ticker"].tolist():
        n = _compute_analyst_count(tkr)
        analyst_counts.append(n)
        if n is None:
            n_null += 1
        else:
            n_ok += 1
    panel = panel.copy()
    panel["analyst_count"] = analyst_counts
    return panel, n_ok, n_null


def run_secondary_with_analyst(panel: pd.DataFrame) -> dict | None:
    """Secondary regression adding analyst_count (if sufficient data).
    Skip if >50% missing; otherwise median-impute missing.
    """
    if "analyst_count" not in panel.columns:
        return None
    n = len(panel)
    miss = panel["analyst_count"].isna().sum()
    if miss > n / 2:
        return {
            "status": "skipped",
            "reason": f"analyst_count missing for {miss}/{n} firms (> 50%)",
            "n_missing": int(miss),
            "n_total": int(n),
        }
    med = panel["analyst_count"].median()
    filled = panel["analyst_count"].fillna(med)
    imputed_flag = panel["analyst_count"].isna().astype(int)

    for c in PRIMARY_COVARIATES + ["analyst_count"]:
        if c == "analyst_count":
            panel["analyst_count"] = filled

    cov_cols = PRIMARY_COVARIATES + ["analyst_count"]
    # Keep only finite rows
    for c in cov_cols:
        panel[c] = pd.to_numeric(panel[c], errors="coerce")
    keep = panel[cov_cols].notna().all(axis=1)
    panel = panel.loc[keep].reset_index(drop=True)

    # z-score
    for c in cov_cols:
        panel[f"{c}_z"] = _zscore(panel[c])
    X_cols = [f"{c}_z" for c in cov_cols]
    X = np.column_stack([np.ones(len(panel))] + [panel[c].to_numpy() for c in X_cols])
    y = panel["theta2"].astype(float).to_numpy()
    res = _ols(X, y)
    X_raw_sec = np.column_stack([panel[c].to_numpy() for c in cov_cols])
    cv = _kfold_cv_leakage_free(X_raw_sec, y, k=CV_FOLDS, seed=RNG_SEED)
    names = ["const"] + X_cols
    p_for_bh = res["p_hc1"][1:]
    bh_adj = _bh_adjust(p_for_bh)
    bh_map = dict(zip(X_cols, bh_adj))
    coef_table = []
    for i, nm in enumerate(names):
        coef_table.append({
            "name": nm,
            "coef": float(res["beta"][i]),
            "se_hc1": float(res["se_hc1"][i]),
            "t_hc1": float(res["t_hc1"][i]),
            "p_hc1": float(res["p_hc1"][i]),
            "bh_adj_p_hc1": float(bh_map.get(nm, np.nan)) if nm != "const" else None,
        })
    return {
        "status": "ok",
        "n_missing_pre_impute": int(miss),
        "n_total": int(n),
        "median_impute": float(med),
        "coefficients": coef_table,
        "r2": float(res["r2"]),
        "r2_adj": float(res["r2_adj"]),
        "cv": cv,
    }


# ---------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------

def plot_forest(reg: dict, out_path: Path) -> None:
    coefs = [c for c in reg["coefficients"] if c["name"] != "const"]
    names = [c["name"].replace("_z", "") for c in coefs]
    betas = [c["coef"] for c in coefs]
    lo = [c["boot_ci_low"] for c in coefs]
    hi = [c["boot_ci_high"] for c in coefs]

    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    y = np.arange(len(names))
    ax.errorbar(
        betas, y,
        xerr=[np.array(betas) - np.array(lo), np.array(hi) - np.array(betas)],
        fmt="o", color="C0", capsize=4,
    )
    ax.axvline(0, color="gray", linestyle="--", linewidth=0.8)
    ax.set_yticks(y)
    ax.set_yticklabels(names)
    ax.invert_yaxis()
    ax.set_xlabel("Coefficient (on z-scored covariate)")
    ax.set_title(
        f"K1113 — Firm-level covariate coefficients (N={reg['n']}, bootstrap 95% CI)"
    )
    plt.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_tier_scatter(tiers: dict, out_path: Path) -> None:
    panel = pd.DataFrame(tiers["panel_with_predictions"])
    color_map = {"A": "C2", "B": "C7", "C": "C3"}
    fig, ax = plt.subplots(figsize=(7.5, 5.0))
    for tier in ("A", "B", "C"):
        sub = panel[panel["tier"] == tier]
        if sub.empty:
            continue
        ax.errorbar(
            sub["predicted_theta2"], sub["theta2"],
            xerr=1.96 * sub["predicted_se"],
            fmt="o", alpha=0.8, label=f"Tier {tier} (n={len(sub)})",
            color=color_map[tier], capsize=3,
        )
    lims = [
        min(panel["predicted_theta2"].min(), panel["theta2"].min()) * 1.1,
        max(panel["predicted_theta2"].max(), panel["theta2"].max()) * 1.1,
    ]
    ax.plot(lims, lims, "k--", linewidth=0.8, label="y=x")
    ax.axhline(0, color="gray", linewidth=0.5)
    ax.axvline(0, color="gray", linewidth=0.5)
    ax.set_xlabel("Predicted θ₂ (in-sample, 95% pred CI)")
    ax.set_ylabel("Observed θ₂")
    ax.set_title("K1113 — In-sample θ₂ prediction by Tier")
    ax.legend(loc="best")
    plt.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_model_comparison(reg: dict, k1109_regression_full: dict, out_path: Path) -> None:
    """Compare sector-dummy model (K1109) vs firm-level (K1113) in R² and AIC."""
    r2_sector_full = k1109_regression_full["r2"]
    r2_sector_reduced = 0.03830269874815284  # from K1109 reduced model
    r2_firm = reg["r2"]
    cv_r2 = reg["cv"]["cv_r2"]

    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    labels = ["K1109 sector+cov (full)", "K1109 cov only (reduced)", "K1113 firm cov (in-sample)", "K1113 firm cov (5-fold CV)"]
    vals = [r2_sector_full, r2_sector_reduced, r2_firm, cv_r2]
    colors = ["C0", "C7", "C2", "C4"]
    ax.bar(labels, vals, color=colors)
    ax.axhline(0, color="k", linewidth=0.8)
    ax.set_ylabel("R²")
    ax.set_title("K1113 — model fit comparison")
    for i, v in enumerate(vals):
        ax.text(i, v + (0.01 if v >= 0 else -0.03), f"{v:.3f}", ha="center", fontsize=9)
    plt.xticks(rotation=15, ha="right")
    plt.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------

def main() -> None:
    _log("=== K1113 — Firm-level covariate rule (pre-registered) ===")

    # 0. Pre-registration hash = hash of this very script above the __main__ line.
    script_text = Path(__file__).read_text(encoding="utf-8")
    pre_reg_hash = hashlib.sha256(script_text.encode("utf-8")).hexdigest()[:16]
    _log(f"[prereg] script hash (short): {pre_reg_hash}")

    # 1. Load K1109 θ₂ panel
    panel = load_firm_panel()

    # 2. Build extended covariates
    panel_ext = build_covariates(panel)
    panel_ext.to_csv(EXP_DIR / "firm_covariates_extended.csv", index=False)
    _log(f"[save] firm_covariates_extended.csv (n={len(panel_ext)})")

    # 3. Attempt analyst_count supplement (optional)
    _log("[analyst] fetching numberOfAnalystOpinions via yfinance...")
    panel_ext, n_ok, n_null = try_analyst_supplement(panel_ext)
    _log(f"[analyst] ok={n_ok}, missing={n_null}")

    # 4. Primary regression (pre-registered)
    reg = run_regression(panel_ext)
    _log(f"[primary] R²={reg['r2']:.4f}, R²_adj={reg['r2_adj']:.4f}, CV R²={reg['cv']['cv_r2']:.4f}")
    for c in reg["coefficients"]:
        if c["name"] == "const":
            continue
        _log(
            f"        {c['name']:<30} coef={c['coef']:+.3e}  "
            f"t_hc1={c['t_hc1']:+.2f}  p_hc1={c['p_hc1']:.4f}  bh_adj={c['bh_adj_p_hc1']:.4f}"
        )

    # 5. Hypotheses
    verdict = assess_hypotheses(reg)

    # 6. Tier classification
    tiers = tier_classification(reg, panel_ext)
    n_A = tiers["tiers"]["A"]["n_firms"]
    n_B = tiers["tiers"]["B"]["n_firms"]
    n_C = tiers["tiers"]["C"]["n_firms"]
    _log(f"[tier]  A (recommended)={n_A}, B (neutral)={n_B}, C (avoid)={n_C}")
    h5 = {"rule": "Tier A count ≥ 3", "n_A": n_A, "passes": n_A >= 3}
    verdict["H5_tier_A_usable"] = h5

    # 7. Secondary: add analyst_count if data available
    sec = run_secondary_with_analyst(panel_ext)

    # 8. Reduced model (covariates only — no intercept modification)
    #    Already in reg as "primary"; for comparison we also report without beta_rolling / without size.
    #    We keep it simple: store 2 leave-one-out regressions.
    loo_regs = {}
    for drop_cov in ("log_mktcap", "beta_rolling_0050"):
        cov_subset = [c for c in PRIMARY_COVARIATES if c != drop_cov]
        z_cols = [f"{c}_z" for c in cov_subset]
        sub = panel_ext.copy()
        for c in cov_subset:
            sub[c] = pd.to_numeric(sub[c], errors="coerce")
        keep = sub[cov_subset].notna().all(axis=1) & sub["theta2"].notna()
        sub = sub.loc[keep].reset_index(drop=True)
        for c in cov_subset:
            sub[f"{c}_z"] = _zscore(sub[c])
        X = np.column_stack([np.ones(len(sub))] + [sub[c].to_numpy() for c in z_cols])
        y = sub["theta2"].astype(float).to_numpy()
        r = _ols(X, y)
        X_raw_loo = np.column_stack([sub[c].to_numpy() for c in cov_subset])
        cv_r = _kfold_cv_leakage_free(X_raw_loo, y, k=CV_FOLDS, seed=RNG_SEED)
        loo_regs[f"drop_{drop_cov}"] = {
            "coef": [
                {
                    "name": nm,
                    "coef": float(r["beta"][i]),
                    "t_hc1": float(r["t_hc1"][i]),
                    "p_hc1": float(r["p_hc1"][i]),
                }
                for i, nm in enumerate(["const"] + z_cols)
            ],
            "r2": float(r["r2"]),
            "r2_adj": float(r["r2_adj"]),
            "cv_r2": cv_r["cv_r2"],
        }

    # 9. Plots
    plot_forest(reg, EXP_DIR / "k1113_coefficient_forest.png")
    plot_tier_scatter(tiers, EXP_DIR / "k1113_tier_scatter.png")
    # load K1109 regression_full summary for comparison
    with open(K1109_DIR / "regression_results.json", "r", encoding="utf-8") as f:
        k1109_raw = json.load(f)
    plot_model_comparison(reg, k1109_raw["regression_full"], EXP_DIR / "k1113_vs_k1109_sector_comparison.png")

    # 10. Pack output
    out = {
        "experiment_id": "K1113",
        "title": "Firm-level covariate rule for Paper 2 selection (pre-registered, confirmatory)",
        "parent_experiment": "K1109",
        "pre_registration": {
            "script_sha256_short": pre_reg_hash,
            "covariates_locked": PRIMARY_COVARIATES,
            "hypotheses": [
                "H1: at least one covariate BH-adj p_hc1 < 0.05",
                "H2: log_mktcap_z coef < 0 AND p_hc1 < 0.10",
                "H3: price_volatility_z coef > 0 AND p_hc1 < 0.10",
                "H4: 5-fold CV R² > 0",
                "H5: Tier A count >= 3",
            ],
        },
        "primary_regression": reg,
        "hypothesis_verdict": verdict,
        "tier_classification_summary": {
            tier: {
                "n_firms": d["n_firms"],
                "tickers": [f["ticker"] for f in d["firms"]],
            }
            for tier, d in tiers["tiers"].items()
        },
        "tier_classification_full": tiers["tiers"],
        "leave_one_out_regressions": loo_regs,
        "secondary_analyst_regression": sec,
        "analyst_coverage": {"n_ok": n_ok, "n_null": n_null},
        "k1109_benchmark": {
            "sector_full_r2": k1109_raw["regression_full"]["r2"],
            "sector_reduced_r2": k1109_raw["regression_reduced"]["r2"],
            "anova_p": k1109_raw["anova"]["p_value"],
        },
        "seed": RNG_SEED,
        "bootstrap_n": BOOT_N,
        "cv_folds": CV_FOLDS,
        "limitations": [
            "N=31 firms is still small; 6 covariates pushes dof=24 for primary model.",
            "Continuous covariates may be collinear (log_mktcap vs log_avg_volume).",
            "In-sample Tier classification uses in-sample SE; out-of-sample Tier would require separate holdout.",
            "earnings_freq derived from 台灣公告日期 file; sector-specific disclosure patterns may confound.",
            "analyst_count coverage from yfinance is patchy for TW small caps.",
        ],
        "references": [
            "Benjamini & Hochberg (1995) BH-FDR",
            "White (1980) HC0/HC1 heteroskedasticity-consistent SE",
            "E052 (cherry-pick bias)",
            "E053 (pre-registration value)",
            "K1104, K1106b, K1109 (ancestors)",
        ],
    }

    out_path = EXP_DIR / "k1113_regression_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, default=str)
    _log(f"[save] {out_path.name}")

    # Separate tier file (Paper 2 appendix-ready)
    tier_only = {
        "experiment_id": "K1113",
        "tier_definition": {
            "A": "predicted θ₂ > 0 AND 95% prediction CI excludes 0 (use A4f-EAV)",
            "B": "95% prediction CI overlaps 0 (neutral, default baseline A4f)",
            "C": "predicted θ₂ < 0 AND 95% prediction CI excludes 0 (avoid EAV)",
        },
        "tiers": tiers["tiers"],
    }
    with open(EXP_DIR / "tier_classification.json", "w", encoding="utf-8") as f:
        json.dump(tier_only, f, indent=2, default=str)

    _log("=== K1113 done ===")


if __name__ == "__main__":
    main()
