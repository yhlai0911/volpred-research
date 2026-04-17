"""
K1131 - Continuous VIX-dependent beta via natural cubic spline
================================================================

Follow-up to K1128 (VIX tertile regime split) - fixing IS-based regime cutoff
degeneracy.

Problem (from K1128 / error_log 2026-04-13):
  K1128 split by IS (2017-2019) VIX tertile (33%/67% cutoffs = 12.07/14.99).
  Applied to OOS (2020-2021) with COVID VIX up to 82: low=0, mid=854, high=20060
  bars. Discrete IS cutoffs FAIL when OOS contains unprecedented events.

Fix (error_log 2026-04-13 fix #3):
  Replace discrete tertile dummies with continuous VIX-dependent coefficient
  via natural cubic spline basis. The |OFI| and OFI coefficients become smooth
  functions of VIX_{t-1} — no discrete cutoffs, no OOS degeneracy.

Spec:
  logit P(jump_{t+1}=1) = alpha
                        + b_1 * jump_curr
                        + [sum_k theta_abs_k * B_k(VIX_{t-1})] * |OFI|_t
                        + [sum_k theta_sgn_k * B_k(VIX_{t-1})] * OFI_t

  where B_k(·) are K+1 basis functions of a natural cubic spline with K=4
  internal knots at IS VIX 20/40/60/80 percentile.

  The VIX-dependent coefficient:
    f_abs(v) = sum_k theta_abs_k * B_k(v)
    f_sgn(v) = sum_k theta_sgn_k * B_k(v)

Hypotheses:
  H1 (global): Joint LRT theta_abs = 0 AND theta_sgn = 0 vs spline, chi^2(2(K+1)) df.
      PASS p < 0.05
  H2 (vs K1128 tertile): OOS QLIKE DM-HLN t >= 2 (spline beats tertile).
      Since K1128 was logistic, use log-likelihood (neg log-loss) as QLIKE-analog.
  H3 (economic): OOS average f(VIX) * |OFI| contribution non-trivial
  H4 (shape): f(VIX) plot shows sensible monotone / U-shape

Data: Reuse K1124 cached parquet (73,203 bars) and K1128's Lee-Mykland jump
detection pipeline. Strict lag discipline: VIX_{t-1} (prev US close, Taiwan
rule), features at bar t predict jump at bar t+1, seed=42.

Baseline (K1128 tertile): refit identical logistic with VIX tertile dummy
interactions for direct DM comparison on SAME valid samples.

Worktree rules (experiment-preamble.md Section 8):
  - Only writes under experiments/k1131/
  - No knowledge.json / feed.json / thinking_journal.json writes
  - No supabase_sync
  - Commit at end: git commit -m "K1131: ..."

Author: Claude (worktree agent-k1131)
Date: 2026-04-17
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.optimize import minimize

warnings.filterwarnings("ignore")

np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR
CACHE_PATH = ROOT.parent / "k1124" / "_cache_bars_2017-01-01_2021-12-31.parquet"

# ============================================================
# Constants (mirror K1128)
# ============================================================
MU1 = np.sqrt(2.0 / np.pi)
K_WIN = 16  # Lee-Mykland window
JUMP_ALPHA = 0.01

IS_YEARS = [2017, 2018, 2019]
OOS_YEARS = [2020, 2021]
SEED = 42

# ============================================================
# 1. Natural cubic spline basis
# ============================================================
def natural_cubic_basis(x: np.ndarray, knots: np.ndarray) -> np.ndarray:
    """
    Natural cubic regression spline basis (Ruppert, Wand, Carroll 2003 form).
    Uses true "natural" boundary condition: the function is linear beyond the
    outermost knots.

    For K internal knots t_1 < t_2 < ... < t_K, the basis has df = K
    (K - 2 cubic basis + 1 linear term x, plus we reserve main-effect |OFI|
    for the constant; returning K cols).

    Formula (natural cubic spline, Hastie, Tibshirani, Friedman 2009 eq. 5.4-5.5):

      N_1(x) = 1 (intercept - EXCLUDED here, main-effect handles level)
      N_2(x) = x
      N_{k+2}(x) = d_k(x) - d_{K-1}(x)   for k = 1, ..., K-2
      where
        d_k(x) = [(x - t_k)_+^3 - (x - t_K)_+^3] / (t_K - t_k)

    This gives K-1 "interaction-useful" basis columns (1 linear + K-2 cubic).
    With K=4 knots -> 1 linear + 2 cubic = 3 cols. We return this.

    IMPORTANT: Outside [t_1, t_K], d_k(x) is linear -> the spline is linear
    beyond boundary knots. This is the "natural" constraint that guarantees
    smooth extrapolation. Unlike our earlier x^2-based basis, this version is
    SAFE for extrapolation to unprecedented VIX (e.g., COVID=82 > IS max=37).

    Returns basis of shape (n, K-1). Caller should update K_knots usage.
    """
    x = np.asarray(x, dtype=float)
    K = len(knots)
    assert K >= 3, "Need at least 3 knots for natural cubic spline"

    n = len(x)
    t_K = knots[-1]

    def d_k(x_, k):
        tk = knots[k]
        numer = np.maximum(x_ - tk, 0) ** 3 - np.maximum(x_ - t_K, 0) ** 3
        denom = t_K - tk
        return numer / denom if denom > 0 else np.zeros_like(x_)

    # Scale factor to keep cubic terms comparable to linear
    vix_range = knots[-1] - knots[0]
    scale = 1.0 / (vix_range ** 2) if vix_range > 0 else 1.0

    # K-1 columns: 1 linear + (K-2) cubic
    B = np.zeros((n, K - 1))
    B[:, 0] = x  # linear term
    for k in range(K - 2):
        B[:, k + 1] = (d_k(x, k) - d_k(x, K - 2)) * scale
    return B


# ============================================================
# 2. Data loading + jump detection (mirror K1128)
# ============================================================
def compute_jumps_per_day(day_df: pd.DataFrame, K: int = K_WIN):
    r = day_df["log_ret"].values
    n = len(r)
    sigma_hat = np.full(n, np.nan)
    abs_r = np.abs(r)
    pairs = abs_r[:-1] * abs_r[1:]
    for t in range(K, n):
        start = t - K
        stop = t - 1
        if start >= 0 and stop <= len(pairs):
            window_pairs = pairs[start:stop]
            if len(window_pairs) == K - 1:
                bv = window_pairs.sum() / ((K - 1) * MU1 ** 2)
                sigma_hat[t] = np.sqrt(max(bv, 1e-16))
    L = abs_r / sigma_hat
    return sigma_hat, L


def prepare_data(verbose: bool = True) -> pd.DataFrame:
    """Load cached TAIFEX bars + compute jump target + merge VIX T-1 lag."""
    if verbose:
        print("=" * 70)
        print("K1131 - Continuous VIX-dependent beta via spline")
        print("=" * 70)
        print(f"\n[1] Loading cached bars from {CACHE_PATH.name}")

    assert CACHE_PATH.exists(), f"Cache missing: {CACHE_PATH}. Run K1124 first."
    df = pd.read_parquet(CACHE_PATH)
    df = df.sort_values(["date", "bar"]).reset_index(drop=True)
    if verbose:
        print(f"    Loaded {len(df):,} bars, {df['date'].nunique()} days, "
              f"{df['date'].min()} .. {df['date'].max()}")

    # Jump detection (same as K1128)
    if verbose:
        print("\n[2] Lee-Mykland jump detection (K=16, alpha=0.01)")
    all_sigma = np.full(len(df), np.nan)
    all_L = np.full(len(df), np.nan)
    for date, idx in df.groupby("date").groups.items():
        idx_arr = np.array(idx)
        day_df = df.loc[idx_arr]
        s, L = compute_jumps_per_day(day_df, K=K_WIN)
        all_sigma[idx_arr] = s
        all_L[idx_arr] = L
    df["sigma_hat"] = all_sigma
    df["L_stat"] = all_L

    n_valid = int(np.isfinite(all_L).sum())
    C_n = (np.sqrt(2 * np.log(n_valid))
           - 0.5 * (np.log(np.log(n_valid)) + np.log(4 * np.pi)) / np.sqrt(2 * np.log(n_valid)))
    S_n = 1.0 / np.sqrt(2 * np.log(n_valid))
    beta_n = -np.log(-np.log(1 - JUMP_ALPHA))
    thresh = C_n + S_n * beta_n
    df["jump"] = ((df["L_stat"] > thresh) & np.isfinite(df["L_stat"])).astype(int)
    df.loc[~np.isfinite(df["L_stat"]), "jump"] = -1
    n_jumps = int((df["jump"] == 1).sum())
    if verbose:
        print(f"    Gumbel threshold = {thresh:.3f}")
        print(f"    Jumps: {n_jumps:,} ({n_jumps/n_valid*100:.3f}%)")

    # Build target jump_{t+1} (within same day)
    df["jump_next"] = -1
    for _, gdf in df.groupby("date"):
        idx = gdf.index.values
        jumps = gdf["jump"].values
        jump_next = np.full(len(gdf), -1)
        jump_next[:-1] = jumps[1:]
        df.loc[idx, "jump_next"] = jump_next

    valid_mask = (
        df["jump_next"].isin([0, 1])
        & df["ofi"].notna()
        & df["log_ret"].notna()
        & np.isfinite(df["L_stat"])
    )
    df_valid = df[valid_mask].copy().reset_index(drop=True)

    # VIX T-1 lag
    if verbose:
        print("\n[3] Loading VIX (T-1 lag)")
    try:
        import yfinance as yf
        vix = yf.download("^VIX", start="2016-12-01", end="2022-01-31",
                           progress=False, auto_adjust=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        vix_df = vix[["Close"]].reset_index()
        vix_df.columns = ["date", "vix"]
    except Exception as e:
        raise RuntimeError(f"VIX download failed: {e}")

    vix_df["date"] = pd.to_datetime(vix_df["date"]).dt.normalize()
    vix_df = vix_df.dropna().drop_duplicates("date").sort_values("date").reset_index(drop=True)
    vix_df["vix_lag1"] = vix_df["vix"].shift(1)
    vix_df["vix_lag1"] = vix_df["vix_lag1"].ffill()

    df_valid["date_norm"] = pd.to_datetime(df_valid["date"]).dt.normalize()
    df_valid = df_valid.merge(
        vix_df[["date", "vix_lag1"]].rename(columns={"date": "date_norm"}),
        on="date_norm", how="left",
    )
    df_valid["vix_lag1"] = df_valid["vix_lag1"].ffill()
    assert df_valid["vix_lag1"].isna().sum() == 0, "VIX merge has missing"
    if verbose:
        print(f"    VIX lag1 merged. "
              f"IS VIX range: "
              f"{df_valid[df_valid['date'].dt.year.isin(IS_YEARS)]['vix_lag1'].min():.2f} - "
              f"{df_valid[df_valid['date'].dt.year.isin(IS_YEARS)]['vix_lag1'].max():.2f}")
        print(f"    OOS VIX range: "
              f"{df_valid[df_valid['date'].dt.year.isin(OOS_YEARS)]['vix_lag1'].min():.2f} - "
              f"{df_valid[df_valid['date'].dt.year.isin(OOS_YEARS)]['vix_lag1'].max():.2f}")

    # Build features
    df_valid["jump_curr"] = df_valid["jump"].clip(lower=0).astype(int)
    df_valid["ofi_t"] = df_valid["ofi"]
    df_valid["ofi_abs_t"] = df_valid["ofi"].abs()
    df_valid["year"] = df_valid["date"].dt.year

    return df_valid, thresh, n_jumps


# ============================================================
# 3. Manual logistic regression (MLE) with spline interactions
# ============================================================
def sigmoid(z):
    # Numerically stable
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    out[~pos] = np.exp(z[~pos]) / (1.0 + np.exp(z[~pos]))
    return out


def logistic_neg_ll(beta: np.ndarray, X: np.ndarray, y: np.ndarray,
                    l2: float = 0.0) -> float:
    z = X @ beta
    # log(1+exp(z)) = max(z,0) + log(1 + exp(-|z|))  (log-sum-exp trick)
    lse = np.maximum(z, 0) + np.log1p(np.exp(-np.abs(z)))
    nll = -np.sum(y * z - lse)
    if l2 > 0:
        nll += 0.5 * l2 * np.sum(beta[1:] ** 2)  # no penalty on intercept
    return nll


def logistic_grad(beta: np.ndarray, X: np.ndarray, y: np.ndarray,
                  l2: float = 0.0) -> np.ndarray:
    z = X @ beta
    p = sigmoid(z)
    g = X.T @ (p - y)
    if l2 > 0:
        reg = l2 * beta.copy()
        reg[0] = 0.0
        g = g + reg
    return g


def fit_logistic_mle(X: np.ndarray, y: np.ndarray, l2: float = 1e-4,
                      init: np.ndarray = None) -> dict:
    """Fit logistic regression by MLE with small L2 ridge for numerical stability."""
    n, p = X.shape
    if init is None:
        init = np.zeros(p)
    res = minimize(
        fun=logistic_neg_ll, x0=init, args=(X, y, l2),
        jac=logistic_grad, method="L-BFGS-B",
        options={"maxiter": 500, "ftol": 1e-9, "gtol": 1e-7},
    )
    if not res.success:
        # Retry with higher ridge
        res = minimize(
            fun=logistic_neg_ll, x0=init, args=(X, y, max(l2, 1e-2)),
            jac=logistic_grad, method="L-BFGS-B",
            options={"maxiter": 1000, "ftol": 1e-9},
        )
    return {
        "beta": res.x,
        "nll": float(res.fun),
        "success": bool(res.success),
        "n_features": p,
        "n_obs": n,
        "ll": float(-res.fun + 0.5 * l2 * np.sum(res.x[1:] ** 2)),
        "l2": l2,
    }


def logistic_predict_proba(X: np.ndarray, beta: np.ndarray) -> np.ndarray:
    return np.clip(sigmoid(X @ beta), 1e-7, 1 - 1e-7)


def log_loss_per_obs(y, p):
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ============================================================
# 4. DM-HLN (Harvey-Leybourne-Newbold 1997)
# ============================================================
def dm_hln_test(loss1: np.ndarray, loss2: np.ndarray, name: str = "") -> dict:
    """
    Positive t => loss1 - loss2 > 0 => model 2 has smaller loss (model 2 better).
    Uses Newey-West HAC variance with h=ceil(n^(1/3)).
    """
    d = loss1 - loss2
    n = len(d)
    if n < 20:
        return {"t": 0.0, "t_plain": 0.0, "mean_d": float(d.mean()),
                "se": 0.0, "n": int(n), "note": "too few obs"}
    mean_d = float(d.mean())
    q = max(1, int(np.ceil(n ** (1 / 3))))
    d_dm = d - mean_d
    gamma_0 = float(np.mean(d_dm ** 2))
    var_nw = gamma_0
    for k in range(1, q + 1):
        if k < n:
            gamma_k = float(np.mean(d_dm[k:] * d_dm[:-k]))
            w_k = 1.0 - k / (q + 1)
            var_nw += 2.0 * w_k * gamma_k
    se = float(np.sqrt(max(var_nw, 1e-16) / n))
    t_plain = mean_d / se if se > 0 else 0.0
    hln_mult = float(np.sqrt((n + 1 - 2 * 1 + 1 * (1 - 1) / n) / n))
    t_hln = t_plain * hln_mult
    return {
        "t": float(t_hln), "t_plain": float(t_plain),
        "mean_d": float(mean_d), "se": se, "n": int(n),
    }


# ============================================================
# 5. Main experiment
# ============================================================
def main():
    t_start = datetime.now()

    # -----------------------------
    # Data
    # -----------------------------
    df_valid, gumbel_thresh, n_jumps_total = prepare_data(verbose=True)

    is_mask = df_valid["year"].isin(IS_YEARS)
    oos_mask = df_valid["year"].isin(OOS_YEARS)
    df_is = df_valid.loc[is_mask].copy().reset_index(drop=True)
    df_oos = df_valid.loc[oos_mask].copy().reset_index(drop=True)

    print(f"\n[4] IS: N={len(df_is):,} ({df_is['date'].min().date()}..{df_is['date'].max().date()})"
          f"  jumps={df_is['jump_next'].sum():,}")
    print(f"    OOS: N={len(df_oos):,} ({df_oos['date'].min().date()}..{df_oos['date'].max().date()})"
          f"  jumps={df_oos['jump_next'].sum():,}")

    vix_is = df_is["vix_lag1"].values
    vix_oos = df_oos["vix_lag1"].values

    # -----------------------------
    # Spline knots (IS quantile-based, per task spec 20/40/60/80)
    # -----------------------------
    KNOTS_PCT = np.array([0.20, 0.40, 0.60, 0.80])
    knots = np.quantile(vix_is, KNOTS_PCT)
    K_knots = len(knots)
    K_basis = K_knots - 1  # natural cubic spline returns K-1 cols (1 linear + K-2 cubic)
    vix_is_median = float(np.median(vix_is))
    print(f"\n[5] Spline knots (IS {KNOTS_PCT*100} percentile):")
    for i, (q, k) in enumerate(zip(KNOTS_PCT, knots)):
        print(f"    knot_{i} (q={q:.2f}): VIX={k:.3f}")
    print(f"    IS median VIX = {vix_is_median:.3f}")

    # -----------------------------
    # Design matrices
    # -----------------------------
    # Baseline M2 (K1128 "M3"): jump_curr + |OFI| + OFI (no VIX interaction)
    # Model A (tertile, K1128 style): baseline + tertile_mid*|OFI| + tertile_high*|OFI|
    #                                           + tertile_mid*OFI + tertile_high*OFI
    # Model B (spline, K1131 NEW): baseline + spline_basis(VIX)*|OFI| (K cols)
    #                                       + spline_basis(VIX)*OFI (K cols)

    def build_features(df_block: pd.DataFrame, is_cutoffs: tuple,
                       knots_arr: np.ndarray, vix_center: float):
        """Build M_base, M_tertile, M_spline design matrices. Returns dict."""
        n = len(df_block)
        ones = np.ones(n)
        jc = df_block["jump_curr"].values.astype(float)
        abs_ofi = df_block["ofi_abs_t"].values.astype(float)
        ofi = df_block["ofi_t"].values.astype(float)
        v = df_block["vix_lag1"].values.astype(float)

        # Baseline features: intercept, jump_curr, |OFI|, OFI
        X_base = np.column_stack([ones, jc, abs_ofi, ofi])

        # --- Tertile design (K1128 replication) ---
        c33, c67 = is_cutoffs
        mid = ((v > c33) & (v <= c67)).astype(float)
        high = (v > c67).astype(float)
        # Interactions
        X_tertile = np.column_stack([
            ones, jc, abs_ofi, ofi,
            mid * abs_ofi, high * abs_ofi,  # VIX-dependent |OFI|
            mid * ofi, high * ofi,           # VIX-dependent OFI
        ])

        # --- Spline design (K1131) ---
        # Center VIX at IS median so basis is numerically stable and
        # spline basis at VIX=median is close to 0 (identifiability aid).
        v_c = v - vix_center
        knots_c = knots_arr - vix_center
        B = natural_cubic_basis(v_c, knots_c)  # (n, K)
        # Subtract basis value at median (=0 after centering) -> already centered
        # This makes f(VIX_median) close to zero

        X_spline = np.column_stack([
            ones, jc, abs_ofi, ofi,
            B * abs_ofi[:, None],  # K cols: spline_basis * |OFI|
            B * ofi[:, None],      # K cols: spline_basis * OFI
        ])

        return {
            "X_base": X_base,
            "X_tertile": X_tertile,
            "X_spline": X_spline,
            "B": B,
            "v": v,
            "vc": v_c,
        }

    # IS tertile cutoffs (33/67 percentile on IS VIX) - for comparison baseline
    is_cutoff_33 = float(np.quantile(vix_is, 1 / 3))
    is_cutoff_67 = float(np.quantile(vix_is, 2 / 3))
    print(f"\n[6] Tertile cutoffs (K1128 replication): 33%={is_cutoff_33:.3f}  67%={is_cutoff_67:.3f}")

    feats_is = build_features(df_is, (is_cutoff_33, is_cutoff_67), knots, vix_is_median)
    feats_oos = build_features(df_oos, (is_cutoff_33, is_cutoff_67), knots, vix_is_median)

    y_is = df_is["jump_next"].values.astype(int)
    y_oos = df_oos["jump_next"].values.astype(int)

    # -----------------------------
    # Fit 3 models on IS
    # -----------------------------
    print("\n[7] Fitting M_base, M_tertile, M_spline on IS via MLE...")
    M_base = fit_logistic_mle(feats_is["X_base"], y_is, l2=1e-4)
    M_tertile = fit_logistic_mle(feats_is["X_tertile"], y_is, l2=1e-4)
    M_spline = fit_logistic_mle(feats_is["X_spline"], y_is, l2=1e-4)

    for name, M in [("M_base", M_base), ("M_tertile", M_tertile), ("M_spline", M_spline)]:
        print(f"    {name}: p={M['n_features']:<2d}  nll_is={M['nll']:.4f}  success={M['success']}")

    # -----------------------------
    # H1: Joint LRT test for spline
    # -----------------------------
    # Compare M_base (no VIX interaction) vs M_spline (K+K = 2K VIX-interacted cols)
    # -2*(ll_base - ll_spline) ~ chi^2(2*K)
    lr_stat_spline_vs_base = 2.0 * (M_base["nll"] - M_spline["nll"])
    df_spline_vs_base = feats_is["X_spline"].shape[1] - feats_is["X_base"].shape[1]
    p_spline_vs_base = 1.0 - sp_stats.chi2.cdf(lr_stat_spline_vs_base, df_spline_vs_base)
    print(f"\n[8] H1: LRT spline vs base")
    print(f"    chi^2 = {lr_stat_spline_vs_base:.3f}, df = {df_spline_vs_base}, "
          f"p = {p_spline_vs_base:.5f}")

    # Also LRT tertile vs base (for reference)
    lr_stat_tertile_vs_base = 2.0 * (M_base["nll"] - M_tertile["nll"])
    df_tertile_vs_base = feats_is["X_tertile"].shape[1] - feats_is["X_base"].shape[1]
    p_tertile_vs_base = 1.0 - sp_stats.chi2.cdf(lr_stat_tertile_vs_base, df_tertile_vs_base)
    print(f"    (reference) tertile vs base: chi^2={lr_stat_tertile_vs_base:.3f}, "
          f"df={df_tertile_vs_base}, p={p_tertile_vs_base:.5f}")

    # Non-nested comparison spline vs tertile via Vuong-like (LL difference)
    # These are non-nested (different df). Use OOS log-loss diff.

    # -----------------------------
    # OOS predictions + loss
    # -----------------------------
    print("\n[9] OOS predictions (log-loss)")
    p_base_oos = logistic_predict_proba(feats_oos["X_base"], M_base["beta"])
    p_tertile_oos = logistic_predict_proba(feats_oos["X_tertile"], M_tertile["beta"])
    p_spline_oos = logistic_predict_proba(feats_oos["X_spline"], M_spline["beta"])

    loss_base = log_loss_per_obs(y_oos, p_base_oos)
    loss_tertile = log_loss_per_obs(y_oos, p_tertile_oos)
    loss_spline = log_loss_per_obs(y_oos, p_spline_oos)

    print(f"    base   : mean log-loss = {loss_base.mean():.5f}")
    print(f"    tertile: mean log-loss = {loss_tertile.mean():.5f}")
    print(f"    spline : mean log-loss = {loss_spline.mean():.5f}")

    # AUC
    from sklearn.metrics import roc_auc_score
    auc_base = float(roc_auc_score(y_oos, p_base_oos)) if len(np.unique(y_oos)) > 1 else float("nan")
    auc_tertile = float(roc_auc_score(y_oos, p_tertile_oos)) if len(np.unique(y_oos)) > 1 else float("nan")
    auc_spline = float(roc_auc_score(y_oos, p_spline_oos)) if len(np.unique(y_oos)) > 1 else float("nan")
    print(f"    OOS AUC: base={auc_base:.4f}  tertile={auc_tertile:.4f}  spline={auc_spline:.4f}")

    # -----------------------------
    # H2: DM-HLN test spline vs tertile
    # -----------------------------
    dm_spline_vs_tertile = dm_hln_test(loss_tertile, loss_spline,
                                         name="spline_vs_tertile")
    dm_spline_vs_base = dm_hln_test(loss_base, loss_spline, name="spline_vs_base")
    dm_tertile_vs_base = dm_hln_test(loss_base, loss_tertile, name="tertile_vs_base")

    print(f"\n[10] H2: DM-HLN tests on OOS log-loss (positive t => 2nd model better)")
    print(f"     spline vs tertile: t={dm_spline_vs_tertile['t']:+.3f}  "
          f"(n={dm_spline_vs_tertile['n']}, mean_d={dm_spline_vs_tertile['mean_d']:+.2e})")
    print(f"     spline vs base   : t={dm_spline_vs_base['t']:+.3f}")
    print(f"     tertile vs base  : t={dm_tertile_vs_base['t']:+.3f}")

    # -----------------------------
    # H4: Evaluate f(VIX) curve
    # -----------------------------
    # Plot f_abs(VIX) and f_sgn(VIX) over the full VIX range observed
    print("\n[11] Computing f(VIX) curve for H4 visualization")
    vix_grid = np.linspace(
        float(min(vix_is.min(), vix_oos.min())),
        float(max(vix_is.max(), vix_oos.max())),
        200
    )
    vix_grid_c = vix_grid - vix_is_median
    knots_c = knots - vix_is_median
    B_grid = natural_cubic_basis(vix_grid_c, knots_c)

    # spline beta layout: [intercept, jump_curr, |OFI|, OFI, (K cols: B*|OFI|), (K cols: B*OFI)]
    beta_sp = M_spline["beta"]
    beta_abs_main = beta_sp[2]
    beta_ofi_main = beta_sp[3]
    theta_abs = beta_sp[4:4 + K_basis]  # K_basis cols for |OFI| interaction
    theta_sgn = beta_sp[4 + K_basis:4 + 2 * K_basis]  # K_basis cols for OFI interaction

    # f_abs(v) = beta_abs_main + B(v) * theta_abs  (the multiplier on |OFI|)
    # f_sgn(v) = beta_ofi_main + B(v) * theta_sgn
    f_abs_grid = beta_abs_main + B_grid @ theta_abs
    f_sgn_grid = beta_ofi_main + B_grid @ theta_sgn

    # Bootstrap CI for f(VIX): approximate via Hessian-based SE
    # For simplicity we use numerical approx of Hessian
    def logistic_hessian(beta, X, l2=1e-4):
        z = X @ beta
        p = sigmoid(z)
        W = p * (1 - p)
        H = (X.T * W) @ X
        H += l2 * np.eye(len(beta))
        H[0, 0] -= l2  # no penalty on intercept
        return H

    H_sp = logistic_hessian(M_spline["beta"], feats_is["X_spline"], l2=M_spline["l2"])
    try:
        cov_sp = np.linalg.inv(H_sp)
    except np.linalg.LinAlgError:
        cov_sp = np.linalg.pinv(H_sp)

    # Delta method: Var(f_abs(v)) = A.T @ cov_abs @ A
    # where A is the row of [1, 0, ..., B_1(v), ..., B_K(v), 0, ..., 0]
    # and cov_abs is sub-matrix of cov_sp over [idx_abs_main, idx_theta_abs...]
    idx_abs_main = 2
    idx_theta_abs = list(range(4, 4 + K_basis))
    idx_ofi_main = 3
    idx_theta_sgn = list(range(4 + K_basis, 4 + 2 * K_basis))

    def delta_se_f(cov, main_idx, theta_idx_list, B_grid_arr):
        n_grid_ = B_grid_arr.shape[0]
        se = np.zeros(n_grid_)
        idx_all = [main_idx] + theta_idx_list
        cov_sub = cov[np.ix_(idx_all, idx_all)]
        for i in range(n_grid_):
            a = np.concatenate([[1.0], B_grid_arr[i]])
            var_f = a @ cov_sub @ a
            se[i] = np.sqrt(max(var_f, 0))
        return se

    se_f_abs = delta_se_f(cov_sp, idx_abs_main, idx_theta_abs, B_grid)
    se_f_sgn = delta_se_f(cov_sp, idx_ofi_main, idx_theta_sgn, B_grid)
    f_abs_lo = f_abs_grid - 1.96 * se_f_abs
    f_abs_hi = f_abs_grid + 1.96 * se_f_abs
    f_sgn_lo = f_sgn_grid - 1.96 * se_f_sgn
    f_sgn_hi = f_sgn_grid + 1.96 * se_f_sgn

    # Determine shape
    f_abs_diff_sign = np.sign(np.diff(f_abs_grid))
    if np.all(f_abs_diff_sign >= 0):
        shape_abs = "monotone_increasing"
    elif np.all(f_abs_diff_sign <= 0):
        shape_abs = "monotone_decreasing"
    else:
        sign_changes = int(np.sum(np.diff(f_abs_diff_sign) != 0))
        if sign_changes <= 1:
            shape_abs = "U-shape_or_single_turn"
        elif sign_changes <= 3:
            shape_abs = "wiggly"
        else:
            shape_abs = "very_wiggly_(overfitting?)"
    print(f"    f_abs(VIX) shape: {shape_abs}")
    print(f"    f_abs(VIX) range: [{f_abs_grid.min():.3f}, {f_abs_grid.max():.3f}]")
    print(f"    f_sgn(VIX) range: [{f_sgn_grid.min():.3f}, {f_sgn_grid.max():.3f}]")

    # -----------------------------
    # H3: Economic significance - OOS avg contribution
    # -----------------------------
    # f(VIX_{t-1}) * |OFI|_t on linear predictor scale
    B_oos = feats_oos["B"]
    f_abs_oos = beta_abs_main + B_oos @ theta_abs
    f_sgn_oos = beta_ofi_main + B_oos @ theta_sgn
    abs_ofi_oos = df_oos["ofi_abs_t"].values
    ofi_oos = df_oos["ofi_t"].values

    # contribution to linear predictor (log-odds scale)
    contrib_abs = f_abs_oos * abs_ofi_oos
    contrib_sgn = f_sgn_oos * ofi_oos
    contrib_total = contrib_abs + contrib_sgn

    # On OOS, also compute "would-be" contribution for tertile model
    beta_t = M_tertile["beta"]
    # Tertile layout: [intercept, jump_curr, |OFI|, OFI, mid*|OFI|, high*|OFI|, mid*OFI, high*OFI]
    v_oos = feats_oos["v"]
    mid_oos = ((v_oos > is_cutoff_33) & (v_oos <= is_cutoff_67)).astype(float)
    high_oos = (v_oos > is_cutoff_67).astype(float)
    contrib_tertile_abs = (beta_t[2] + beta_t[4] * mid_oos + beta_t[5] * high_oos) * abs_ofi_oos
    contrib_tertile_sgn = (beta_t[3] + beta_t[6] * mid_oos + beta_t[7] * high_oos) * ofi_oos

    print(f"\n[12] H3: OOS economic significance (contribution to log-odds)")
    print(f"    spline  abs_contrib : mean={contrib_abs.mean():+.3e}  std={contrib_abs.std():.3e}")
    print(f"    spline  sgn_contrib : mean={contrib_sgn.mean():+.3e}  std={contrib_sgn.std():.3e}")
    print(f"    spline  total       : mean={contrib_total.mean():+.3e}  std={contrib_total.std():.3e}")
    print(f"    tertile abs_contrib : mean={contrib_tertile_abs.mean():+.3e}  std={contrib_tertile_abs.std():.3e}")
    print(f"    tertile sgn_contrib : mean={contrib_tertile_sgn.mean():+.3e}  std={contrib_tertile_sgn.std():.3e}")

    # -----------------------------
    # OOS regime distribution comparison
    # -----------------------------
    print("\n[13] OOS VIX distribution comparison (tertile vs spline coverage)")
    low_oos = int((v_oos <= is_cutoff_33).sum())
    mid_oos_count = int(((v_oos > is_cutoff_33) & (v_oos <= is_cutoff_67)).sum())
    high_oos_count = int((v_oos > is_cutoff_67).sum())
    print(f"    K1128 tertile OOS count: low={low_oos}, mid={mid_oos_count}, high={high_oos_count}")
    print(f"    Spline: continuous — all {len(v_oos):,} OOS bars get nonzero f(VIX) coefficient")

    # Show f(VIX) values at OOS VIX quartiles
    oos_q = np.quantile(v_oos, [0.25, 0.50, 0.75])
    oos_q_c = oos_q - vix_is_median
    B_oos_q = natural_cubic_basis(oos_q_c, knots - vix_is_median)
    f_at_q = beta_abs_main + B_oos_q @ theta_abs
    print(f"    f_abs at OOS VIX Q25/Q50/Q75 = {oos_q[0]:.1f}/{oos_q[1]:.1f}/{oos_q[2]:.1f}: "
          f"{f_at_q[0]:+.3f} / {f_at_q[1]:+.3f} / {f_at_q[2]:+.3f}")

    # -----------------------------
    # Verdict
    # -----------------------------
    print("\n" + "=" * 70)
    print("K1131 VERDICT")
    print("=" * 70)

    h1_pass = p_spline_vs_base < 0.05
    h2_pass = dm_spline_vs_tertile["t"] >= 2.0
    h3_nontrivial = abs(contrib_total.mean()) > 0 and abs(contrib_total).mean() > 1e-4
    h4_sensible = shape_abs in ("monotone_increasing", "monotone_decreasing", "U-shape_or_single_turn")

    if h1_pass and h2_pass:
        verdict = "SPLINE_SUPERIOR"
    elif h1_pass and (abs(dm_spline_vs_tertile["t"]) < 2.0):
        verdict = "SPLINE_TIED"
    elif (not h1_pass) and (not h2_pass):
        verdict = "NULL"
    elif h2_pass and not h1_pass:
        verdict = "SPLINE_TIED"  # OOS DM wins but IS LRT weak - suspicious
    else:
        verdict = "SPLINE_INFERIOR"

    print(f"H1 global LRT spline vs base: chi^2({df_spline_vs_base})={lr_stat_spline_vs_base:.2f}, "
          f"p={p_spline_vs_base:.4f} -> {'PASS' if h1_pass else 'FAIL'}")
    print(f"H2 OOS DM-HLN spline vs tertile: t={dm_spline_vs_tertile['t']:+.3f} -> "
          f"{'PASS' if h2_pass else 'FAIL'}")
    print(f"H3 OOS contrib nontrivial (|mean|>0, |mean abs|>1e-4): "
          f"mean_total_contrib={contrib_total.mean():+.3e} -> "
          f"{'PASS' if h3_nontrivial else 'FAIL'}")
    print(f"H4 f(VIX) shape sensible: {shape_abs} -> "
          f"{'PASS' if h4_sensible else 'FAIL'}")
    print(f"\n=> VERDICT: {verdict}")

    # -----------------------------
    # Save results
    # -----------------------------
    runtime = (datetime.now() - t_start).total_seconds()
    print(f"\n[14] Saving results (runtime={runtime:.1f}s)...")

    results = {
        "experiment_id": "K1131",
        "title": "Continuous VIX-dependent beta via natural cubic spline (fix K1128 regime degeneracy)",
        "timestamp": datetime.now().isoformat(),
        "seed": SEED,
        "runtime_sec": float(runtime),
        "data_source": "TAIFEX TX 5-min bars 2017-2021 (K1124 cache)",
        "is_period": "2017-2019",
        "oos_period": "2020-2021",
        "n_bars_valid": int(len(df_valid)),
        "n_is": int(len(df_is)),
        "n_oos": int(len(df_oos)),
        "n_is_jumps": int(y_is.sum()),
        "n_oos_jumps": int(y_oos.sum()),
        "jump_detection": {
            "method": "Lee-Mykland K=16 strictly-past BV (same as K1128)",
            "gumbel_thresh_alpha_0.01": float(gumbel_thresh),
            "n_jumps_total": int(n_jumps_total),
        },
        "spline": {
            "type": "natural cubic spline (Ruppert-Wand-Carroll truncated cubic)",
            "K_knots": int(K_knots),
            "K_basis_cols": int(K_basis),
            "knot_percentiles_IS": KNOTS_PCT.tolist(),
            "knot_vix_values": knots.tolist(),
            "vix_is_median_centering": float(vix_is_median),
            "basis_df_per_interaction": int(K_basis),
            "total_params_spline": int(feats_is["X_spline"].shape[1]),
            "total_params_tertile": int(feats_is["X_tertile"].shape[1]),
            "total_params_base": int(feats_is["X_base"].shape[1]),
        },
        "tertile_cutoffs_IS": {
            "cutoff_33": float(is_cutoff_33),
            "cutoff_67": float(is_cutoff_67),
        },
        "oos_vix_range": {
            "min": float(vix_oos.min()),
            "max": float(vix_oos.max()),
            "mean": float(vix_oos.mean()),
        },
        "is_vix_range": {
            "min": float(vix_is.min()),
            "max": float(vix_is.max()),
            "mean": float(vix_is.mean()),
        },
        "oos_tertile_counts_K1128_style": {
            "low": low_oos,
            "mid": mid_oos_count,
            "high": high_oos_count,
        },
        "models": {
            "M_base": {
                "n_params": M_base["n_features"],
                "nll_is": M_base["nll"],
                "beta": M_base["beta"].tolist(),
                "features": ["intercept", "jump_curr", "|OFI|", "OFI"],
            },
            "M_tertile": {
                "n_params": M_tertile["n_features"],
                "nll_is": M_tertile["nll"],
                "beta": M_tertile["beta"].tolist(),
                "features": [
                    "intercept", "jump_curr", "|OFI|", "OFI",
                    "mid*|OFI|", "high*|OFI|", "mid*OFI", "high*OFI",
                ],
            },
            "M_spline": {
                "n_params": M_spline["n_features"],
                "nll_is": M_spline["nll"],
                "beta": M_spline["beta"].tolist(),
                "features": [
                    "intercept", "jump_curr", "|OFI|", "OFI",
                    *[f"spline_abs_{i}" for i in range(K_basis)],
                    *[f"spline_sgn_{i}" for i in range(K_basis)],
                ],
                "beta_abs_main": float(beta_abs_main),
                "beta_ofi_main": float(beta_ofi_main),
                "theta_abs": theta_abs.tolist(),
                "theta_sgn": theta_sgn.tolist(),
            },
        },
        "H1_LRT_spline_vs_base": {
            "chi2_stat": float(lr_stat_spline_vs_base),
            "df": int(df_spline_vs_base),
            "p_value": float(p_spline_vs_base),
            "pass": bool(h1_pass),
        },
        "LRT_tertile_vs_base_reference": {
            "chi2_stat": float(lr_stat_tertile_vs_base),
            "df": int(df_tertile_vs_base),
            "p_value": float(p_tertile_vs_base),
        },
        "H2_DM_spline_vs_tertile": {
            **dm_spline_vs_tertile,
            "pass": bool(h2_pass),
        },
        "DM_spline_vs_base": dm_spline_vs_base,
        "DM_tertile_vs_base": dm_tertile_vs_base,
        "OOS_log_loss": {
            "base": float(loss_base.mean()),
            "tertile": float(loss_tertile.mean()),
            "spline": float(loss_spline.mean()),
        },
        "OOS_AUC": {
            "base": auc_base,
            "tertile": auc_tertile,
            "spline": auc_spline,
        },
        "H3_economic_significance": {
            "oos_mean_total_contrib_log_odds": float(contrib_total.mean()),
            "oos_mean_abs_contrib": float(contrib_abs.mean()),
            "oos_mean_sgn_contrib": float(contrib_sgn.mean()),
            "oos_mean_abs_contrib_magnitude": float(np.abs(contrib_abs).mean()),
            "oos_mean_sgn_contrib_magnitude": float(np.abs(contrib_sgn).mean()),
            "tertile_mean_abs_contrib": float(contrib_tertile_abs.mean()),
            "tertile_mean_sgn_contrib": float(contrib_tertile_sgn.mean()),
            "pass": bool(h3_nontrivial),
        },
        "H4_shape": {
            "description": shape_abs,
            "f_abs_range": [float(f_abs_grid.min()), float(f_abs_grid.max())],
            "f_sgn_range": [float(f_sgn_grid.min()), float(f_sgn_grid.max())],
            "f_abs_at_OOS_Q25Q50Q75": f_at_q.tolist(),
            "oos_vix_quantiles": oos_q.tolist(),
            "pass": bool(h4_sensible),
        },
        "verdict": verdict,
        "h1_pass": bool(h1_pass),
        "h2_pass": bool(h2_pass),
        "h3_pass": bool(h3_nontrivial),
        "h4_pass": bool(h4_sensible),
        "references": [
            "Lee & Mykland (2008) RFS 21(6), 2535-2563",
            "Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88",
            "Hastie & Tibshirani (1990) Generalized Additive Models",
            "Ruppert, Wand, Carroll (2003) Semiparametric Regression",
            "Harvey, Leybourne, Newbold (1997) IJF 13(2), 281-291",
        ],
    }

    out_path = SCRIPT_DIR / "k1131_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"    Saved {out_path}")

    # -----------------------------
    # Plots
    # -----------------------------
    print("\n[15] Plotting spline_beta_vs_vix.png and tertile_vs_spline_comparison.png ...")

    # Plot 1: beta(VIX) curve with CI + tertile step function overlaid
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # (a) f_abs(VIX)
    ax = axes[0]
    ax.fill_between(vix_grid, f_abs_lo, f_abs_hi, color="steelblue", alpha=0.2,
                     label="spline f_abs(VIX) 95% CI")
    ax.plot(vix_grid, f_abs_grid, color="steelblue", lw=2, label="spline f_abs(VIX)")

    # Overlay tertile step function for |OFI| coef
    # Tertile: beta_t[2] (low default) + beta_t[4] (mid) + beta_t[5] (high)
    tertile_abs_low = beta_t[2]
    tertile_abs_mid = beta_t[2] + beta_t[4]
    tertile_abs_high = beta_t[2] + beta_t[5]
    step_x = np.concatenate([
        [vix_grid.min(), is_cutoff_33],
        [is_cutoff_33, is_cutoff_67],
        [is_cutoff_67, vix_grid.max()],
    ])
    step_y = np.concatenate([
        [tertile_abs_low, tertile_abs_low],
        [tertile_abs_mid, tertile_abs_mid],
        [tertile_abs_high, tertile_abs_high],
    ])
    ax.plot(step_x, step_y, color="coral", lw=2, linestyle="--",
             label="tertile f_abs(VIX) (K1128)")

    # Mark IS/OOS VIX distributions with rug plots
    ax.hist(vix_is, bins=40, density=True, alpha=0.15, color="gray",
             bottom=ax.get_ylim()[0], label="IS VIX hist (scaled)")
    ax.set_xlabel("VIX (T-1 lag)")
    ax.set_ylabel("Coefficient on |OFI|")
    ax.set_title("f_abs(VIX): |OFI| coefficient as function of VIX")
    ax.axhline(0, color="black", lw=0.5)
    for k_v in knots:
        ax.axvline(k_v, color="green", lw=0.5, linestyle=":", alpha=0.5)
    ax.axvline(is_cutoff_33, color="coral", lw=0.5, linestyle="--", alpha=0.5)
    ax.axvline(is_cutoff_67, color="coral", lw=0.5, linestyle="--", alpha=0.5)
    ax.legend(fontsize=8, loc="best")

    # (b) f_sgn(VIX)
    ax = axes[1]
    ax.fill_between(vix_grid, f_sgn_lo, f_sgn_hi, color="seagreen", alpha=0.2,
                     label="spline f_sgn(VIX) 95% CI")
    ax.plot(vix_grid, f_sgn_grid, color="seagreen", lw=2, label="spline f_sgn(VIX)")
    tertile_sgn_low = beta_t[3]
    tertile_sgn_mid = beta_t[3] + beta_t[6]
    tertile_sgn_high = beta_t[3] + beta_t[7]
    step_y_sgn = np.concatenate([
        [tertile_sgn_low, tertile_sgn_low],
        [tertile_sgn_mid, tertile_sgn_mid],
        [tertile_sgn_high, tertile_sgn_high],
    ])
    ax.plot(step_x, step_y_sgn, color="coral", lw=2, linestyle="--",
             label="tertile f_sgn(VIX)")
    ax.set_xlabel("VIX (T-1 lag)")
    ax.set_ylabel("Coefficient on OFI (signed)")
    ax.set_title("f_sgn(VIX): signed-OFI coefficient as function of VIX")
    ax.axhline(0, color="black", lw=0.5)
    for k_v in knots:
        ax.axvline(k_v, color="green", lw=0.5, linestyle=":", alpha=0.5)
    ax.legend(fontsize=8, loc="best")

    plt.suptitle("K1131: VIX-dependent |OFI| and OFI coefficients (spline vs tertile)",
                  fontsize=12)
    plt.tight_layout()
    fig_path = SCRIPT_DIR / "spline_beta_vs_vix.png"
    plt.savefig(fig_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    Saved {fig_path}")

    # Plot 2: tertile vs spline OOS comparison (log-loss, AUC, contrib distribution)
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # (a) OOS log-loss
    ax = axes[0]
    names = ["base", "tertile", "spline"]
    losses = [loss_base.mean(), loss_tertile.mean(), loss_spline.mean()]
    aucs = [auc_base, auc_tertile, auc_spline]
    colors = ["gray", "coral", "steelblue"]
    ax.bar(names, losses, color=colors, alpha=0.8)
    for i, v in enumerate(losses):
        ax.text(i, v, f"{v:.5f}", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Mean OOS log-loss (lower better)")
    ax.set_title("OOS log-loss")

    # (b) OOS AUC
    ax = axes[1]
    ax.bar(names, aucs, color=colors, alpha=0.8)
    for i, v in enumerate(aucs):
        ax.text(i, v, f"{v:.4f}", ha="center", va="bottom", fontsize=9)
    ax.axhline(0.5, color="red", lw=0.5, linestyle="--", label="chance")
    ax.set_ylabel("OOS AUC (higher better)")
    ax.set_title("OOS AUC")
    ax.legend(fontsize=8)

    # (c) OOS contribution distributions
    ax = axes[2]
    ax.hist(contrib_tertile_abs, bins=50, alpha=0.5, color="coral",
             label=f"tertile |OFI| contrib (mean={contrib_tertile_abs.mean():+.2e})")
    ax.hist(contrib_abs, bins=50, alpha=0.5, color="steelblue",
             label=f"spline |OFI| contrib (mean={contrib_abs.mean():+.2e})")
    ax.set_xlabel("Contribution to log-odds (OOS)")
    ax.set_ylabel("Frequency")
    ax.set_title("OOS |OFI| coefficient × |OFI| contribution")
    ax.legend(fontsize=8)

    plt.suptitle("K1131 vs K1128 (tertile): OOS comparison", fontsize=12)
    plt.tight_layout()
    fig_path2 = SCRIPT_DIR / "tertile_vs_spline_comparison.png"
    plt.savefig(fig_path2, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    Saved {fig_path2}")

    print(f"\nK1131 complete. Runtime: {runtime:.1f}s  Verdict: {verdict}")
    return results


if __name__ == "__main__":
    main()
