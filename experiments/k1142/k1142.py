"""
K1142 - Volatility-normalized OFI as alternative specification (bypass K1128/K1131 NULL)
=========================================================================================

Motivation
----------
K1128 (VIX tertile regime split) and K1131 (continuous VIX-dependent spline) both
returned NULL. This suggests that the framing problem — "does OFI predictability
vary with VIX regime?" — may simply be the wrong question. K1128's primary failure
was OOS VIX exceeding IS training range; K1131's linear extrapolation of the
natural-cubic spline worsened OOS AUC (0.496 < 0.50, below chance).

K1131 derived-direction #3 proposed an alternative specification that BYPASSES
regime-switching identification entirely:
    z_absOFI = |OFI|_t / sigma_hat_t   (volatility-normalized magnitude)
    z_sgnOFI = OFI_t   / sigma_hat_t   (volatility-normalized signed)
where sigma_hat_t is a rolling realized vol estimated STRICTLY from the past
60 5-min bars (≈ 5 trading hours; the intraday "memory" window).

The vol-normalized spec treats OFI as a STANDARDIZED signal. Under this
framing, the COVID-era structural VIX shift is absorbed into sigma_hat itself,
so the resulting z_OFI signal is regime-free by construction. No spline.
No tertile cutoff. No distributional assumption on VIX.

Hypothesis comparison
---------------------
M_base (K1128 "M3")         : alpha + b1*jump_curr + b2*|OFI|_t + b3*OFI_t
M_volnorm (K1142 new)       : alpha + b1*jump_curr + b2*z_absOFI + b3*z_sgnOFI
M_realvol_tertile (control) : alpha + b1*jump_curr + b2*|OFI|_t + b3*OFI_t
                              + b4*mid_sigma*|OFI| + b5*hi_sigma*|OFI|
                              + b6*mid_sigma*OFI  + b7*hi_sigma*OFI
    where mid/hi_sigma are IS-sigma-tertile indicators evaluated on
    sigma_hat_t (not VIX). Analogous to K1128 but regime proxy replaced.

Decision logic
--------------
(a) PASS   : M_volnorm DM vs M_base positive with |t| > 2 (Harvey 2016 thresh
             |t|>3 for top-journal publication; |t|>2 for methodological improvement)
(b) NULL   : both |t| <= 2 and log-loss indistinguishable → vol-norm adds nothing
(c) PARTIAL: one direction only (IS or OOS) significant

If M_volnorm PASSES while M_realvol_tertile fails → vol-normalization is
UNIQUE (the continuous standardization matters; simple vol-regime isn't enough).
If both PASS → regime-free signal exists but simple tertile is sufficient.
If M_volnorm NULL → OFI-vol-norm hypothesis also rejected; K1128 story
should emphasize that OFI->jump has no reliable standardization that works
across COVID regime shift.

Lag discipline (strict)
-----------------------
- sigma_hat_t computed from returns r_{t-60}, ..., r_{t-1} (STRICTLY past,
  not including r_t). Implemented as `log_ret.shift(1).rolling(60).std()`
  equivalent, with NaN during first 60 bars of each day.
- For extra safety per task spec, a 12-bar additional lag (shift(12) ≈ 1-hour
  "published" delay) is tested as robustness; primary uses strict 1-bar shift.
- Target jump_{t+1} from K1128/K1131 pipeline (same day only).
- Seed 42 everywhere; L-BFGS-B with L2 ridge 1e-4 (no intercept penalty).

Data: reuse K1124 parquet cache (2017-2021 TAIFEX TX 5-min bars, 73,203 bars,
Lee-Mykland K=16 jump detection gives 115 jumps).

Author: Claude (worktree agent-a11a520c / K1142)
Date: 2026-04-17
"""
from __future__ import annotations

import json
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
from sklearn.metrics import roc_auc_score, brier_score_loss

warnings.filterwarnings("ignore")

np.random.seed(42)
RNG = np.random.default_rng(42)

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_PATH = SCRIPT_DIR.parent / "k1124" / "_cache_bars_2017-01-01_2021-12-31.parquet"

# ============================================================
# Constants (mirror K1128/K1131)
# ============================================================
MU1 = np.sqrt(2.0 / np.pi)
K_WIN = 16           # Lee-Mykland BV window
JUMP_ALPHA = 0.01
SIGMA_WIN = 60       # 60 5-min bars ≈ 5 hours (cross-day rolling; see build below)
IS_YEARS = [2017, 2018, 2019]
OOS_YEARS = [2020, 2021]
SEED = 42


# ============================================================
# Jump detection (IDENTICAL to K1131; DO NOT rewrite)
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
    """Load cached TAIFEX bars + compute jump target + rolling sigma_hat."""
    if verbose:
        print("=" * 70)
        print("K1142 - Volatility-normalized OFI (bypass VIX-regime)")
        print("=" * 70)
        print(f"\n[1] Loading cached bars from {CACHE_PATH.name}")

    assert CACHE_PATH.exists(), f"Cache missing: {CACHE_PATH}. Run K1124 first."
    df = pd.read_parquet(CACHE_PATH)
    df = df.sort_values(["date", "bar"]).reset_index(drop=True)
    if verbose:
        print(f"    Loaded {len(df):,} bars, {df['date'].nunique()} days, "
              f"{df['date'].min()} .. {df['date'].max()}")

    # --- Jump detection (Lee-Mykland, same as K1128/K1131) ---
    if verbose:
        print("\n[2] Lee-Mykland jump detection (K=16, alpha=0.01)")
    all_sigma_lm = np.full(len(df), np.nan)
    all_L = np.full(len(df), np.nan)
    for date, idx in df.groupby("date").groups.items():
        idx_arr = np.array(idx)
        day_df = df.loc[idx_arr]
        s, L = compute_jumps_per_day(day_df, K=K_WIN)
        all_sigma_lm[idx_arr] = s
        all_L[idx_arr] = L
    df["sigma_lm"] = all_sigma_lm
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

    # --- Rolling realized vol sigma_hat (STRICTLY past) ---
    # sigma_hat_t = std(log_ret_{t-SIGMA_WIN}, ..., log_ret_{t-1})
    #
    # Cross-day implementation: roll over the fully-sorted full series so that
    # each bar sees the most recent SIGMA_WIN 5-min return observations. This
    # naturally includes the prior day's last bars when today is early in
    # session (which is correct — overnight gap is encoded in open-open log_ret
    # between last bar yesterday and first bar today). This dramatically reduces
    # NaN wastage (per-day reset would lose first 60 bars of each day → lose
    # the whole day since day length is 60 bars).
    #
    # STRICT lookahead discipline: sigma_hat at row i uses rows [i-SIGMA_WIN, i-1]
    # via `log_ret.shift(1).rolling(SIGMA_WIN)`.
    if verbose:
        print(f"\n[3] Rolling realized sigma_hat_t (window={SIGMA_WIN} bars, "
              f"STRICTLY past, cross-day)")
    r_ser = df["log_ret"]
    # shift(1) removes current bar from the window → strict past
    sigma_series = r_ser.shift(1).rolling(SIGMA_WIN, min_periods=SIGMA_WIN).std()
    # robustness: 12-bar additional lag for "published" realism (shift(12) means
    # sigma at row i uses rows [i-SIGMA_WIN-11, i-12])
    sigma_series_lag12 = r_ser.shift(12).rolling(SIGMA_WIN, min_periods=SIGMA_WIN).std()
    df["sigma_hat"] = sigma_series.values
    df["sigma_hat_lag12"] = sigma_series_lag12.values
    if verbose:
        n_ok = int(np.isfinite(df["sigma_hat"].values).sum())
        print(f"    sigma_hat finite: {n_ok:,} / {len(df):,} ({n_ok/len(df)*100:.1f}%)")
        print(f"    sigma_hat mean/std: {df['sigma_hat'].mean():.6f} / "
              f"{df['sigma_hat'].std():.6f}")

    # --- Valid mask ---
    valid_mask = (
        df["jump_next"].isin([0, 1])
        & df["ofi"].notna()
        & df["log_ret"].notna()
        & np.isfinite(df["L_stat"])
        & np.isfinite(df["sigma_hat"])
        & (df["sigma_hat"] > 1e-10)
    )
    df_valid = df[valid_mask].copy().reset_index(drop=True)

    # Build features
    df_valid["jump_curr"] = df_valid["jump"].clip(lower=0).astype(int)
    df_valid["ofi_t"] = df_valid["ofi"]
    df_valid["ofi_abs_t"] = df_valid["ofi"].abs()
    # vol-normalized (primary)
    df_valid["z_absOFI"] = df_valid["ofi_abs_t"] / df_valid["sigma_hat"]
    df_valid["z_sgnOFI"] = df_valid["ofi_t"] / df_valid["sigma_hat"]
    # vol-normalized lag12 robustness
    sig12_ok = df_valid["sigma_hat_lag12"].notna() & (df_valid["sigma_hat_lag12"] > 1e-10)
    df_valid["z_absOFI_lag12"] = np.where(
        sig12_ok, df_valid["ofi_abs_t"] / df_valid["sigma_hat_lag12"], np.nan)
    df_valid["z_sgnOFI_lag12"] = np.where(
        sig12_ok, df_valid["ofi_t"] / df_valid["sigma_hat_lag12"], np.nan)

    df_valid["year"] = df_valid["date"].dt.year

    if verbose:
        print(f"\n[4] Valid N = {len(df_valid):,}  "
              f"(jumps_next_1 = {int((df_valid['jump_next']==1).sum()):,})")
        print(f"    z_absOFI summary: mean={df_valid['z_absOFI'].mean():.2f}  "
              f"std={df_valid['z_absOFI'].std():.2f}  "
              f"min={df_valid['z_absOFI'].min():.2f}  "
              f"max={df_valid['z_absOFI'].max():.2f}")

    return df_valid, thresh, n_jumps


# ============================================================
# Manual logistic regression (MLE) — identical to K1131
# ============================================================
def sigmoid(z):
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    out[~pos] = np.exp(z[~pos]) / (1.0 + np.exp(z[~pos]))
    return out


def logistic_neg_ll(beta, X, y, l2=0.0):
    z = X @ beta
    lse = np.maximum(z, 0) + np.log1p(np.exp(-np.abs(z)))
    nll = -np.sum(y * z - lse)
    if l2 > 0:
        nll += 0.5 * l2 * np.sum(beta[1:] ** 2)  # no penalty on intercept
    return nll


def logistic_grad(beta, X, y, l2=0.0):
    z = X @ beta
    p = sigmoid(z)
    g = X.T @ (p - y)
    if l2 > 0:
        reg = l2 * beta.copy()
        reg[0] = 0.0
        g = g + reg
    return g


def fit_logistic_mle(X, y, l2=1e-4, init=None):
    n, p = X.shape
    if init is None:
        init = np.zeros(p)
    res = minimize(
        fun=logistic_neg_ll, x0=init, args=(X, y, l2),
        jac=logistic_grad, method="L-BFGS-B",
        options={"maxiter": 500, "ftol": 1e-9, "gtol": 1e-7},
    )
    if not res.success:
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


def predict_proba(X, beta):
    return np.clip(sigmoid(X @ beta), 1e-7, 1 - 1e-7)


def log_loss_per_obs(y, p):
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ============================================================
# DM-HLN (Harvey-Leybourne-Newbold 1997)
# ============================================================
def dm_hln_test(loss1, loss2, name=""):
    """Positive t => loss1 > loss2 => model 2 better (smaller loss)."""
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
# Main
# ============================================================
def main():
    t_start = datetime.now()

    df_valid, gumbel_thresh, n_jumps_total = prepare_data(verbose=True)

    is_mask = df_valid["year"].isin(IS_YEARS)
    oos_mask = df_valid["year"].isin(OOS_YEARS)
    df_is = df_valid.loc[is_mask].copy().reset_index(drop=True)
    df_oos = df_valid.loc[oos_mask].copy().reset_index(drop=True)

    print(f"\n[5] IS: N={len(df_is):,} ({df_is['date'].min().date()}..{df_is['date'].max().date()})"
          f"  jumps={int((df_is['jump_next']==1).sum()):,}")
    print(f"    OOS: N={len(df_oos):,} ({df_oos['date'].min().date()}..{df_oos['date'].max().date()})"
          f"  jumps={int((df_oos['jump_next']==1).sum()):,}")

    sigma_is = df_is["sigma_hat"].values
    sigma_oos = df_oos["sigma_hat"].values
    print(f"\n[6] sigma_hat IS range: [{sigma_is.min():.6f}, {sigma_is.max():.6f}] "
          f"median={np.median(sigma_is):.6f}")
    print(f"    sigma_hat OOS range: [{sigma_oos.min():.6f}, {sigma_oos.max():.6f}] "
          f"median={np.median(sigma_oos):.6f}")

    # --- IS sigma tertile cutoffs (for M_realvol_tertile control) ---
    cut33 = float(np.quantile(sigma_is, 1.0 / 3.0))
    cut67 = float(np.quantile(sigma_is, 2.0 / 3.0))
    print(f"    IS sigma-tertile cutoffs: 33%={cut33:.6f}  67%={cut67:.6f}")

    # --- Build design matrices ---
    def build_features(df_block):
        n = len(df_block)
        ones = np.ones(n)
        jc = df_block["jump_curr"].values.astype(float)
        abs_ofi = df_block["ofi_abs_t"].values.astype(float)
        ofi = df_block["ofi_t"].values.astype(float)
        z_abs = df_block["z_absOFI"].values.astype(float)
        z_sgn = df_block["z_sgnOFI"].values.astype(float)
        sigma = df_block["sigma_hat"].values.astype(float)

        # Tertile indicators on sigma_hat (regime-free analog of VIX tertile)
        mid = ((sigma > cut33) & (sigma <= cut67)).astype(float)
        high = (sigma > cut67).astype(float)

        # M_base (K1128 M3 replication): intercept + jump_curr + |OFI| + OFI
        X_base = np.column_stack([ones, jc, abs_ofi, ofi])

        # M_volnorm (K1142 primary): intercept + jump_curr + z_absOFI + z_sgnOFI
        X_volnorm = np.column_stack([ones, jc, z_abs, z_sgn])

        # M_realvol_tertile (control): intercept + jump_curr + |OFI| + OFI
        # + mid*|OFI| + high*|OFI| + mid*OFI + high*OFI (uses sigma_hat tertile, not VIX)
        X_realvol_tertile = np.column_stack([
            ones, jc, abs_ofi, ofi,
            mid * abs_ofi, high * abs_ofi,
            mid * ofi, high * ofi,
        ])

        return {
            "X_base": X_base,
            "X_volnorm": X_volnorm,
            "X_realvol_tertile": X_realvol_tertile,
            "mid": mid,
            "high": high,
        }

    feats_is = build_features(df_is)
    feats_oos = build_features(df_oos)
    y_is = (df_is["jump_next"].values == 1).astype(int)
    y_oos = (df_oos["jump_next"].values == 1).astype(int)

    # --- Fit ---
    print("\n[7] Fitting M_base, M_volnorm, M_realvol_tertile on IS via MLE...")
    M_base = fit_logistic_mle(feats_is["X_base"], y_is, l2=1e-4)
    M_volnorm = fit_logistic_mle(feats_is["X_volnorm"], y_is, l2=1e-4)
    M_realvol = fit_logistic_mle(feats_is["X_realvol_tertile"], y_is, l2=1e-4)

    for name, M in [("M_base", M_base), ("M_volnorm", M_volnorm),
                    ("M_realvol_tertile", M_realvol)]:
        print(f"    {name}: p={M['n_features']:<2d}  "
              f"nll_is={M['nll']:.4f}  beta={M['beta'].round(4).tolist()}  "
              f"success={M['success']}")

    # --- LRT (IS) ---
    lr_volnorm_vs_base = 2.0 * (M_base["nll"] - M_volnorm["nll"])
    # M_volnorm is NOT nested in M_base (different functional features). Use Vuong-like.
    # For non-nested use AIC / LL diff directly.
    # But still compute chi2 for reporting (degenerate case if same df).
    df_vb = feats_is["X_volnorm"].shape[1] - feats_is["X_base"].shape[1]
    print(f"\n[8] IS model fit:")
    print(f"    LL(base)    = {-M_base['nll']:.4f}")
    print(f"    LL(volnorm) = {-M_volnorm['nll']:.4f}  (delta={M_base['nll']-M_volnorm['nll']:+.4f})")
    print(f"    LL(realvolT)= {-M_realvol['nll']:.4f}  (delta_vs_base={M_base['nll']-M_realvol['nll']:+.4f})")

    lr_realvol_vs_base = 2.0 * (M_base["nll"] - M_realvol["nll"])
    df_rb = feats_is["X_realvol_tertile"].shape[1] - feats_is["X_base"].shape[1]
    p_realvol_vs_base = 1.0 - sp_stats.chi2.cdf(max(lr_realvol_vs_base, 0), df_rb)
    print(f"    LRT realvol_tertile vs base: chi^2={lr_realvol_vs_base:.3f}, "
          f"df={df_rb}, p={p_realvol_vs_base:.5f}")

    # --- IS predictions + loss (for IS DM) ---
    p_base_is = predict_proba(feats_is["X_base"], M_base["beta"])
    p_volnorm_is = predict_proba(feats_is["X_volnorm"], M_volnorm["beta"])
    p_realvol_is = predict_proba(feats_is["X_realvol_tertile"], M_realvol["beta"])
    ls_base_is = log_loss_per_obs(y_is, p_base_is)
    ls_volnorm_is = log_loss_per_obs(y_is, p_volnorm_is)
    ls_realvol_is = log_loss_per_obs(y_is, p_realvol_is)

    # --- OOS predictions + loss ---
    p_base_oos = predict_proba(feats_oos["X_base"], M_base["beta"])
    p_volnorm_oos = predict_proba(feats_oos["X_volnorm"], M_volnorm["beta"])
    p_realvol_oos = predict_proba(feats_oos["X_realvol_tertile"], M_realvol["beta"])

    ls_base_oos = log_loss_per_obs(y_oos, p_base_oos)
    ls_volnorm_oos = log_loss_per_obs(y_oos, p_volnorm_oos)
    ls_realvol_oos = log_loss_per_obs(y_oos, p_realvol_oos)

    # AUC / Brier
    def safe_auc(y, p):
        return float(roc_auc_score(y, p)) if len(np.unique(y)) > 1 else float("nan")
    auc_base_oos = safe_auc(y_oos, p_base_oos)
    auc_volnorm_oos = safe_auc(y_oos, p_volnorm_oos)
    auc_realvol_oos = safe_auc(y_oos, p_realvol_oos)
    auc_base_is = safe_auc(y_is, p_base_is)
    auc_volnorm_is = safe_auc(y_is, p_volnorm_is)
    auc_realvol_is = safe_auc(y_is, p_realvol_is)

    brier_base_oos = float(brier_score_loss(y_oos, p_base_oos))
    brier_volnorm_oos = float(brier_score_loss(y_oos, p_volnorm_oos))
    brier_realvol_oos = float(brier_score_loss(y_oos, p_realvol_oos))

    print("\n[9] OOS metrics:")
    print(f"    log-loss:  base={ls_base_oos.mean():.6f}  "
          f"volnorm={ls_volnorm_oos.mean():.6f}  "
          f"realvolT={ls_realvol_oos.mean():.6f}")
    print(f"    AUC     :  base={auc_base_oos:.4f}  "
          f"volnorm={auc_volnorm_oos:.4f}  "
          f"realvolT={auc_realvol_oos:.4f}")
    print(f"    Brier   :  base={brier_base_oos:.6f}  "
          f"volnorm={brier_volnorm_oos:.6f}  "
          f"realvolT={brier_realvol_oos:.6f}")

    # --- DM-HLN ---
    # Primary: M_volnorm vs M_base (positive t => volnorm better)
    dm_volnorm_vs_base_oos = dm_hln_test(ls_base_oos, ls_volnorm_oos, "volnorm_vs_base_oos")
    dm_volnorm_vs_base_is = dm_hln_test(ls_base_is, ls_volnorm_is, "volnorm_vs_base_is")
    # Control: M_realvol_tertile vs M_base
    dm_realvol_vs_base_oos = dm_hln_test(ls_base_oos, ls_realvol_oos, "realvolT_vs_base_oos")
    dm_realvol_vs_base_is = dm_hln_test(ls_base_is, ls_realvol_is, "realvolT_vs_base_is")
    # Specification horse-race: volnorm vs realvol tertile
    dm_volnorm_vs_realvol_oos = dm_hln_test(ls_realvol_oos, ls_volnorm_oos, "volnorm_vs_realvolT_oos")

    print("\n[10] DM-HLN tests (positive t => 2nd model better):")
    print(f"    IS  volnorm vs base : t={dm_volnorm_vs_base_is['t']:+.3f}  "
          f"(mean_d={dm_volnorm_vs_base_is['mean_d']:+.2e})")
    print(f"    OOS volnorm vs base : t={dm_volnorm_vs_base_oos['t']:+.3f}  "
          f"(mean_d={dm_volnorm_vs_base_oos['mean_d']:+.2e})")
    print(f"    IS  realvolT vs base: t={dm_realvol_vs_base_is['t']:+.3f}")
    print(f"    OOS realvolT vs base: t={dm_realvol_vs_base_oos['t']:+.3f}")
    print(f"    OOS volnorm vs realvolT: t={dm_volnorm_vs_realvol_oos['t']:+.3f}")

    # --- Spearman(fitted prob, realized jump) on OOS ---
    def spearman_to_dict(p, y):
        if len(np.unique(y)) < 2:
            return {"rho": float("nan"), "p": float("nan")}
        rho, p_val = sp_stats.spearmanr(p, y)
        return {"rho": float(rho), "p": float(p_val)}

    sp_base = spearman_to_dict(p_base_oos, y_oos)
    sp_volnorm = spearman_to_dict(p_volnorm_oos, y_oos)
    sp_realvol = spearman_to_dict(p_realvol_oos, y_oos)
    print(f"\n[11] OOS Spearman(p_hat, y):")
    print(f"    base={sp_base['rho']:+.4f} (p={sp_base['p']:.4f})  "
          f"volnorm={sp_volnorm['rho']:+.4f} (p={sp_volnorm['p']:.4f})  "
          f"realvolT={sp_realvol['rho']:+.4f} (p={sp_realvol['p']:.4f})")

    # --- Lag-12 robustness: M_volnorm with sigma_hat_lag12 ---
    print("\n[12] Robustness: lag-12 (≈1 hour) sigma_hat")
    # Subset rows where lag12 is available (drops first 60+12=72 bars/day)
    lag12_is_mask = df_is["z_absOFI_lag12"].notna() & df_is["z_sgnOFI_lag12"].notna()
    lag12_oos_mask = df_oos["z_absOFI_lag12"].notna() & df_oos["z_sgnOFI_lag12"].notna()
    df_is_l12 = df_is[lag12_is_mask].reset_index(drop=True)
    df_oos_l12 = df_oos[lag12_oos_mask].reset_index(drop=True)

    def build_lag12(df_block):
        n = len(df_block)
        ones = np.ones(n)
        jc = df_block["jump_curr"].values.astype(float)
        z_abs = df_block["z_absOFI_lag12"].values.astype(float)
        z_sgn = df_block["z_sgnOFI_lag12"].values.astype(float)
        return np.column_stack([ones, jc, z_abs, z_sgn])

    X_vol_l12_is = build_lag12(df_is_l12)
    X_vol_l12_oos = build_lag12(df_oos_l12)
    # Refit M_base on same lag12 subset for fair comparison
    # (base doesn't depend on sigma, so take the matching subset)
    X_base_l12_is = np.column_stack([
        np.ones(len(df_is_l12)),
        df_is_l12["jump_curr"].values.astype(float),
        df_is_l12["ofi_abs_t"].values.astype(float),
        df_is_l12["ofi_t"].values.astype(float),
    ])
    X_base_l12_oos = np.column_stack([
        np.ones(len(df_oos_l12)),
        df_oos_l12["jump_curr"].values.astype(float),
        df_oos_l12["ofi_abs_t"].values.astype(float),
        df_oos_l12["ofi_t"].values.astype(float),
    ])
    y_is_l12 = (df_is_l12["jump_next"].values == 1).astype(int)
    y_oos_l12 = (df_oos_l12["jump_next"].values == 1).astype(int)

    M_base_l12 = fit_logistic_mle(X_base_l12_is, y_is_l12, l2=1e-4)
    M_volnorm_l12 = fit_logistic_mle(X_vol_l12_is, y_is_l12, l2=1e-4)
    p_base_l12_oos = predict_proba(X_base_l12_oos, M_base_l12["beta"])
    p_volnorm_l12_oos = predict_proba(X_vol_l12_oos, M_volnorm_l12["beta"])
    ls_base_l12 = log_loss_per_obs(y_oos_l12, p_base_l12_oos)
    ls_vol_l12 = log_loss_per_obs(y_oos_l12, p_volnorm_l12_oos)
    dm_lag12 = dm_hln_test(ls_base_l12, ls_vol_l12, "volnorm_lag12_vs_base")
    auc_base_l12 = safe_auc(y_oos_l12, p_base_l12_oos)
    auc_vol_l12 = safe_auc(y_oos_l12, p_volnorm_l12_oos)
    print(f"    N_is_l12={len(df_is_l12):,}  N_oos_l12={len(df_oos_l12):,}")
    print(f"    lag12 DM volnorm vs base: t={dm_lag12['t']:+.3f}  "
          f"AUC: base={auc_base_l12:.4f}  volnorm={auc_vol_l12:.4f}")

    # --- Conditional P(jump | z_absOFI) for plotting ---
    # Empirical bin: group OOS by z_absOFI decile
    z_abs_oos = df_oos["z_absOFI"].values
    deciles = np.quantile(z_abs_oos, np.linspace(0, 1, 11))
    bin_centers = []
    bin_prob = []
    bin_ci_lo = []
    bin_ci_hi = []
    bin_n = []
    for i in range(10):
        mask = (z_abs_oos >= deciles[i]) & (z_abs_oos < deciles[i + 1])
        if i == 9:
            mask = (z_abs_oos >= deciles[i]) & (z_abs_oos <= deciles[i + 1])
        n_b = int(mask.sum())
        if n_b == 0:
            continue
        y_b = y_oos[mask]
        k = int(y_b.sum())
        p_hat = k / n_b
        # Wilson 95% CI
        if n_b > 0:
            z = 1.96
            denom = 1 + z**2 / n_b
            centre = (p_hat + z**2 / (2 * n_b)) / denom
            half = z * np.sqrt(p_hat * (1 - p_hat) / n_b + z**2 / (4 * n_b**2)) / denom
            lo = max(0, centre - half)
            hi = min(1, centre + half)
        else:
            lo, hi = 0.0, 1.0
        bin_centers.append(float((deciles[i] + deciles[i + 1]) / 2))
        bin_prob.append(p_hat)
        bin_ci_lo.append(lo)
        bin_ci_hi.append(hi)
        bin_n.append(n_b)

    # --- Verdict ---
    # Harvey (2016) |t|>3.0 for publication; |t|>2.0 methodological significance
    print("\n" + "=" * 70)
    print("K1142 VERDICT")
    print("=" * 70)

    t_oos = dm_volnorm_vs_base_oos["t"]
    t_is = dm_volnorm_vs_base_is["t"]
    t_realvol_oos = dm_realvol_vs_base_oos["t"]

    harvey_threshold = 3.0
    methodological_threshold = 2.0

    if t_oos >= harvey_threshold and t_is >= harvey_threshold:
        verdict = "PASS_STRONG"
    elif t_oos >= methodological_threshold and t_is >= methodological_threshold:
        verdict = "PASS_METHODOLOGICAL"
    elif t_oos >= methodological_threshold:
        verdict = "PARTIAL_OOS_ONLY"
    elif t_is >= methodological_threshold:
        verdict = "PARTIAL_IS_ONLY"
    else:
        verdict = "NULL"

    # Realvol tertile comparison
    if t_realvol_oos >= methodological_threshold and t_oos >= methodological_threshold:
        realvol_note = "both_spec_work"
    elif t_realvol_oos < methodological_threshold and t_oos >= methodological_threshold:
        realvol_note = "volnorm_unique"
    elif t_realvol_oos >= methodological_threshold and t_oos < methodological_threshold:
        realvol_note = "realvol_tertile_works_volnorm_fails"
    else:
        realvol_note = "both_fail_reinforces_K1128_null"

    print(f"M_volnorm vs base IS  DM t = {t_is:+.3f}")
    print(f"M_volnorm vs base OOS DM t = {t_oos:+.3f}")
    print(f"M_realvol_tertile vs base OOS DM t = {t_realvol_oos:+.3f}")
    print(f"VERDICT: {verdict}")
    print(f"Realvol tertile control: {realvol_note}")

    # --- Save results ---
    runtime = (datetime.now() - t_start).total_seconds()
    print(f"\n[13] Saving results (runtime={runtime:.1f}s)...")

    results = {
        "experiment_id": "K1142",
        "title": "Volatility-normalized OFI (bypass VIX-conditional regime-switching)",
        "timestamp": datetime.now().isoformat(),
        "seed": SEED,
        "runtime_sec": float(runtime),
        "data_source": "TAIFEX TX 5-min bars 2017-2021 (K1124 cache)",
        "is_period": "2017-2019",
        "oos_period": "2020-2021",
        "n_valid": int(len(df_valid)),
        "n_is": int(len(df_is)),
        "n_oos": int(len(df_oos)),
        "n_is_jumps": int(y_is.sum()),
        "n_oos_jumps": int(y_oos.sum()),
        "sigma_window_bars": SIGMA_WIN,
        "jump_detection": {
            "method": "Lee-Mykland K=16 strictly-past BV (same as K1128/K1131)",
            "gumbel_thresh_alpha_0.01": float(gumbel_thresh),
            "n_jumps_total": int(n_jumps_total),
        },
        "is_sigma_tertile_cutoffs": {"cut33": cut33, "cut67": cut67},
        "sigma_hat_summary": {
            "is_min": float(sigma_is.min()), "is_max": float(sigma_is.max()),
            "is_median": float(np.median(sigma_is)),
            "oos_min": float(sigma_oos.min()), "oos_max": float(sigma_oos.max()),
            "oos_median": float(np.median(sigma_oos)),
        },
        "models": {
            "M_base": {
                "features": ["intercept", "jump_curr", "|OFI|", "OFI"],
                "n_params": M_base["n_features"],
                "nll_is": M_base["nll"],
                "beta": M_base["beta"].tolist(),
            },
            "M_volnorm": {
                "features": ["intercept", "jump_curr", "z_absOFI", "z_sgnOFI"],
                "z_absOFI_def": "|OFI|_t / sigma_hat_t  (sigma from past 60 5-min bars, shift(1))",
                "n_params": M_volnorm["n_features"],
                "nll_is": M_volnorm["nll"],
                "beta": M_volnorm["beta"].tolist(),
            },
            "M_realvol_tertile": {
                "features": ["intercept", "jump_curr", "|OFI|", "OFI",
                             "mid*|OFI|", "high*|OFI|", "mid*OFI", "high*OFI"],
                "regime_proxy": "sigma_hat tertile (IS cutoffs)",
                "n_params": M_realvol["n_features"],
                "nll_is": M_realvol["nll"],
                "beta": M_realvol["beta"].tolist(),
            },
        },
        "IS_metrics": {
            "log_loss": {
                "base": float(ls_base_is.mean()),
                "volnorm": float(ls_volnorm_is.mean()),
                "realvol_tertile": float(ls_realvol_is.mean()),
            },
            "AUC": {
                "base": auc_base_is,
                "volnorm": auc_volnorm_is,
                "realvol_tertile": auc_realvol_is,
            },
        },
        "OOS_metrics": {
            "log_loss": {
                "base": float(ls_base_oos.mean()),
                "volnorm": float(ls_volnorm_oos.mean()),
                "realvol_tertile": float(ls_realvol_oos.mean()),
            },
            "AUC": {
                "base": auc_base_oos,
                "volnorm": auc_volnorm_oos,
                "realvol_tertile": auc_realvol_oos,
            },
            "Brier": {
                "base": brier_base_oos,
                "volnorm": brier_volnorm_oos,
                "realvol_tertile": brier_realvol_oos,
            },
            "Spearman_fitted_vs_jump": {
                "base": sp_base,
                "volnorm": sp_volnorm,
                "realvol_tertile": sp_realvol,
            },
        },
        "DM_HLN_tests": {
            "IS_volnorm_vs_base": dm_volnorm_vs_base_is,
            "OOS_volnorm_vs_base": dm_volnorm_vs_base_oos,
            "IS_realvol_tertile_vs_base": dm_realvol_vs_base_is,
            "OOS_realvol_tertile_vs_base": dm_realvol_vs_base_oos,
            "OOS_volnorm_vs_realvol_tertile": dm_volnorm_vs_realvol_oos,
        },
        "LRT_realvol_tertile_vs_base_IS": {
            "chi2": float(lr_realvol_vs_base),
            "df": int(df_rb),
            "p_value": float(p_realvol_vs_base),
        },
        "robustness_lag12": {
            "description": "sigma_hat computed with additional 12-bar lag (1 hour 'published' realism)",
            "n_is_lag12": int(len(df_is_l12)),
            "n_oos_lag12": int(len(df_oos_l12)),
            "DM_volnorm_vs_base": dm_lag12,
            "AUC_OOS": {"base": auc_base_l12, "volnorm": auc_vol_l12},
            "beta_M_volnorm_lag12": M_volnorm_l12["beta"].tolist(),
            "beta_M_base_lag12": M_base_l12["beta"].tolist(),
        },
        "conditional_prob_OOS_by_z_absOFI_decile": {
            "bin_centers": bin_centers,
            "emp_prob_jump": bin_prob,
            "wilson_95_ci_lo": bin_ci_lo,
            "wilson_95_ci_hi": bin_ci_hi,
            "bin_n": bin_n,
        },
        "verdict": verdict,
        "realvol_tertile_note": realvol_note,
        "harvey_threshold_used": harvey_threshold,
        "methodological_threshold": methodological_threshold,
        "references": [
            "Lee & Mykland (2008) RFS 21(6), 2535-2563",
            "Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88",
            "Hansen & Lunde (2005) JoE 7(4), 549-564 (realized vol proxy)",
            "Harvey, Leybourne, Newbold (1997) IJF 13(2), 281-291",
            "Harvey (2016) RFS 29(11), 2824-2859 (|t|>3 threshold)",
        ],
    }

    out_path = SCRIPT_DIR / "k1142_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"    Saved {out_path}")

    # --- Plot 1: AUC curve comparison (ROC) ---
    from sklearn.metrics import roc_curve
    fig, ax = plt.subplots(1, 1, figsize=(7, 6))
    for name, p, color in [("M_base", p_base_oos, "gray"),
                           ("M_volnorm", p_volnorm_oos, "steelblue"),
                           ("M_realvol_tertile", p_realvol_oos, "coral")]:
        fpr, tpr, _ = roc_curve(y_oos, p)
        auc_ = safe_auc(y_oos, p)
        ax.plot(fpr, tpr, lw=1.8, color=color, label=f"{name} (AUC={auc_:.4f})")
    ax.plot([0, 1], [0, 1], "k--", lw=0.5, label="chance")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title(f"K1142 OOS ROC (N={len(y_oos):,}, {int(y_oos.sum())} jumps)")
    ax.legend(loc="lower right")
    plt.tight_layout()
    fig_path = SCRIPT_DIR / "k1142_oos_roc.png"
    plt.savefig(fig_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    Saved {fig_path}")

    # --- Plot 2: Conditional P(jump|z_absOFI) with 95% CI ---
    fig, ax = plt.subplots(1, 1, figsize=(9, 5.5))
    bcenters = np.array(bin_centers)
    bprob = np.array(bin_prob)
    blo = np.array(bin_ci_lo)
    bhi = np.array(bin_ci_hi)
    bn = np.array(bin_n)
    ax.errorbar(bcenters, bprob,
                 yerr=[bprob - blo, bhi - bprob],
                 marker="o", ms=6, lw=1.5, capsize=3,
                 color="steelblue", label="empirical P(jump_{t+1} | z_absOFI_t)")
    # Model-implied curve
    z_grid = np.linspace(bcenters.min(), bcenters.max(), 200)
    # Use mean jump_curr and mean z_sgnOFI=0 for marginal curve
    mean_jc_oos = float(df_oos["jump_curr"].mean())
    beta_v = M_volnorm["beta"]
    # linear predictor: alpha + b1*jc_mean + b2*z_absOFI + b3*0
    eta_grid = beta_v[0] + beta_v[1] * mean_jc_oos + beta_v[2] * z_grid
    p_grid = 1.0 / (1.0 + np.exp(-eta_grid))
    ax.plot(z_grid, p_grid, color="coral", lw=2,
             label=f"M_volnorm fitted (jc=mean={mean_jc_oos:.3f}, z_sgn=0)")
    ax.axhline(y_oos.mean(), color="gray", lw=0.5, linestyle="--",
                label=f"OOS base rate = {y_oos.mean():.4f}")
    ax.set_xlabel("z_absOFI = |OFI|_t / sigma_hat_t  (decile centers)")
    ax.set_ylabel("P(jump at t+1)")
    ax.set_title(
        f"K1142: Conditional jump probability vs vol-normalized |OFI|\n"
        f"OOS 2020-2021 (N={len(y_oos):,}, jumps={int(y_oos.sum())}); "
        f"DM vs base t={t_oos:+.2f}  Verdict: {verdict}"
    )
    # annotate bin N
    for xc, yc, nc in zip(bcenters, bprob, bn):
        ax.annotate(f"n={nc}", (xc, yc), xytext=(0, 8),
                     textcoords="offset points", fontsize=7, ha="center")
    ax.legend(loc="best", fontsize=9)
    plt.tight_layout()
    fig_path2 = SCRIPT_DIR / "k1142_cond_prob.png"
    plt.savefig(fig_path2, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    Saved {fig_path2}")

    print(f"\nK1142 complete. Runtime: {runtime:.1f}s  Verdict: {verdict}")
    return results


if __name__ == "__main__":
    main()
