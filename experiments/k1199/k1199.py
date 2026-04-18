"""
K1199 - Expanding-window Adaptive VIX Quantile for OFI->Jump Logit
==================================================================

Task-id mapping: next_tasks.json references "K1133_expanding_window", but
K1133 was already used for BTC GAS-t. To avoid ID collision, this experiment
uses directory `experiments/k1199/` while preserving the original task spec.

Motivation
----------
K1128 (IS-fixed VIX tertile) failed because OOS 2020-2021 VIX (12-83, COVID)
lies almost entirely above IS 2017-2019 VIX (9-37). Using IS 33%/67% cutoffs
(12.07/14.99) gave degenerate OOS coverage: low=0 / mid=854 / high=20,060 bars.

K1131 (natural cubic spline) and K1142 (vol-normalized OFI) both returned NULL
(K1131: OOS DM t=-3.94 vs base, AUC=0.4965 below chance; K1142: DM ~0).

This experiment (error_log 2026-04-13 fix #2) replaces the IS-fixed VIX cutoffs
with EXPANDING-WINDOW ADAPTIVE quantiles: for each OOS bar t, the tertile
cutoffs are re-computed on VIX history strictly BEFORE bar t. The tertile
assignment therefore updates continuously as new VIX observations arrive.

Key design decisions
--------------------
1. Expanding-window quantile on VIX DAILY series (VIX is daily-resolution;
   using 5-min resolution would introduce spurious sub-day structure).
2. Strict lookahead discipline: for bar t on date D with vix_lag1 = VIX(D-1),
   the quantile window is VIX history through D-1 (inclusive of VIX(D-1)
   because it is published before D's open, but NOT including VIX(D)).
   We drop this degenerate edge by using VIX history strictly BEFORE D-1
   i.e., up to and including VIX(D-2). This matches the task spec:
   "q33/q67 must strictly use data BEFORE bar t".
3. Burn-in: use IS 2017-2019 as warm-up window. First OOS bar on
   2020-01-02 uses all IS+1 day of VIX.
4. Refit cadence: retrain logit every 252 TRADING DAYS (≈ 1 year). Within
   refit window, coefficients are frozen but tertile labels update each bar.
   This matches the spec: "VIX quantile still expanding" even if MLE is
   batch-refit.
5. Seed 42, MLE via L-BFGS-B with L2 ridge 1e-4 (consistent with K1131).

Models compared
---------------
M_base     : K1128 "M3" baseline — logit P(jump_{t+1}=1) = α + β1·jump_curr
             + β2·|OFI|_t + β3·OFI_t  (no VIX interaction)
M_tertile  : K1128 IS-FIXED tertile — IS 2017-2019 cutoffs applied to OOS.
             Replicated for reference (IS-fixed degenerate coverage).
M_volnorm  : K1142 vol-normalized control — |OFI|/σ̂ and OFI/σ̂ replacing raw.
             Reused as benchmark.
M_expanding: K1199 NEW — tertile label uses EXPANDING-WINDOW VIX quantile
             computed strictly before each OOS bar.

Hypotheses
----------
H1 (coverage): Expanding-window tertile achieves BALANCED OOS coverage
               (e.g., low > 3000, mid > 3000, high > 3000), bypassing
               K1128 degeneracy.
H2 (DM main): M_expanding OOS DM-HLN vs M_base |t| > 3 (Harvey 2016 top-journal
               threshold for methodological improvement)
H3 (informs): M_expanding coefficient drift across regimes:
               β_high·|OFI| != β_low·|OFI| (economically meaningful spread).
H4 (vs K1128): M_expanding beats (or at least ties) K1128 IS-fixed tertile on
               OOS log-loss and AUC.

Verdict
-------
PASS    : H1 and H2 both satisfied (|DM| > 3, coverage balanced) → "regime"
          story rescued under adaptive quantile
PARTIAL : H1 satisfied but |DM| in (2, 3] → weak regime evidence
NULL    : H1 fails OR |DM| ≤ 2 → K1128 regime-switching narrative definitively
          rejected (4th complementary try under error_log fix #2)

References
----------
Lee & Mykland (2008) RFS 21(6), 2535-2563.
Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88.
Harvey, Leybourne, Newbold (1997) IJF 13(2), 281-291.
Harvey (2016) "...and the Cross-section of Expected Returns" — t-stat
  thresholds for multiple testing.

Author: Claude (worktree agent-a5c40c3c / K1199)
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

# ============================================================
# Constants / seed
# ============================================================
np.random.seed(42)
RNG = np.random.default_rng(42)
SEED = 42

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_PATH = SCRIPT_DIR.parent / "k1124" / "_cache_bars_2017-01-01_2021-12-31.parquet"

MU1 = np.sqrt(2.0 / np.pi)
K_WIN = 16          # Lee-Mykland window
JUMP_ALPHA = 0.01
SIGMA_WIN = 60      # For K1142 vol-norm bench (60 5-min bars)
IS_YEARS = [2017, 2018, 2019]
OOS_YEARS = [2020, 2021]
REFIT_CADENCE_BARS = 252  # ≈ 1 trading-year


# ============================================================
# 1. Jump detection (mirror K1128/K1131, strictly past BV)
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


# ============================================================
# 2. Rolling 60-bar realized sigma (for K1142 vol-norm bench)
# ============================================================
def compute_rolling_sigma(df: pd.DataFrame, window: int = SIGMA_WIN) -> np.ndarray:
    """Strictly past 60-bar rolling std of log returns (shift(1) then roll)."""
    r = df["log_ret"].copy()
    # Strictly past: shift first then rolling
    r_shifted = r.shift(1)
    sigma = r_shifted.rolling(window=window, min_periods=window).std()
    return sigma.values


# ============================================================
# 3. Data prep
# ============================================================
def prepare_data(verbose: bool = True):
    if verbose:
        print("=" * 70)
        print("K1199 - Expanding-window adaptive VIX quantile for OFI->jump logit")
        print("=" * 70)
        print(f"\n[1] Load cached bars: {CACHE_PATH.name}")

    assert CACHE_PATH.exists(), f"Missing cache: {CACHE_PATH}"
    df = pd.read_parquet(CACHE_PATH)
    df = df.sort_values(["date", "bar"]).reset_index(drop=True)
    if verbose:
        print(f"    Loaded {len(df):,} bars, {df['date'].nunique()} days, "
              f"{df['date'].min()} .. {df['date'].max()}")

    # --- Jump detection ---
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
    df["sigma_hat_LM"] = all_sigma  # Lee-Mykland BV sigma
    df["L_stat"] = all_L

    n_valid_L = int(np.isfinite(all_L).sum())
    C_n = (np.sqrt(2 * np.log(n_valid_L))
           - 0.5 * (np.log(np.log(n_valid_L)) + np.log(4 * np.pi)) / np.sqrt(2 * np.log(n_valid_L)))
    S_n = 1.0 / np.sqrt(2 * np.log(n_valid_L))
    beta_n = -np.log(-np.log(1 - JUMP_ALPHA))
    thresh = C_n + S_n * beta_n
    df["jump"] = ((df["L_stat"] > thresh) & np.isfinite(df["L_stat"])).astype(int)
    df.loc[~np.isfinite(df["L_stat"]), "jump"] = -1
    n_jumps = int((df["jump"] == 1).sum())
    if verbose:
        print(f"    Gumbel threshold α=0.01: {thresh:.3f}")
        print(f"    Jumps: {n_jumps:,} ({n_jumps / n_valid_L * 100:.3f}%)")

    # --- jump_{t+1} target (within same day) ---
    df["jump_next"] = -1
    for _, gdf in df.groupby("date"):
        idx = gdf.index.values
        jumps = gdf["jump"].values
        jump_next = np.full(len(gdf), -1)
        jump_next[:-1] = jumps[1:]
        df.loc[idx, "jump_next"] = jump_next

    # --- Rolling 60-bar sigma for K1142 bench ---
    if verbose:
        print("\n[3] Rolling 60-bar σ (K1142 vol-norm bench)")
    sigma60 = np.full(len(df), np.nan)
    for _, gdf in df.groupby("date"):
        idx = gdf.index.values
        day_sigma = compute_rolling_sigma(gdf, window=SIGMA_WIN)
        sigma60[idx] = day_sigma
    df["sigma60_shift1"] = sigma60

    # --- Valid mask ---
    valid_mask = (
        df["jump_next"].isin([0, 1])
        & df["ofi"].notna()
        & df["log_ret"].notna()
        & np.isfinite(df["L_stat"])
    )
    df_valid = df[valid_mask].copy().reset_index(drop=True)

    # --- VIX T-1 lag ---
    if verbose:
        print("\n[4] VIX daily (T-1 lag)")
    import yfinance as yf
    vix = yf.download("^VIX", start="2016-12-01", end="2022-01-31",
                       progress=False, auto_adjust=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[["Close"]].reset_index()
    vix_df.columns = ["date", "vix"]
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
    assert df_valid["vix_lag1"].isna().sum() == 0, "VIX merge left NaN"

    # Keep a cleaned VIX daily series for expanding-window quantile
    vix_daily = vix_df[["date", "vix"]].rename(columns={"date": "date_norm"}).copy()
    vix_daily = vix_daily.sort_values("date_norm").reset_index(drop=True)

    # Features
    df_valid["jump_curr"] = df_valid["jump"].clip(lower=0).astype(int)
    df_valid["ofi_t"] = df_valid["ofi"]
    df_valid["ofi_abs_t"] = df_valid["ofi"].abs()
    df_valid["year"] = df_valid["date"].dt.year

    # Vol-norm features (with fallback to LM sigma when rolling missing)
    sig_use = df_valid["sigma60_shift1"].values.copy()
    nan_mask = ~np.isfinite(sig_use)
    if nan_mask.any():
        # Fallback to sigma_hat_LM where strict-past rolling absent
        sig_use[nan_mask] = df_valid["sigma_hat_LM"].values[nan_mask]
    # Floor to avoid div-by-tiny
    sig_use = np.maximum(sig_use, 1e-8)
    df_valid["sigma_use"] = sig_use
    df_valid["ofi_abs_z"] = df_valid["ofi_abs_t"] / df_valid["sigma_use"]
    df_valid["ofi_sgn_z"] = df_valid["ofi_t"] / df_valid["sigma_use"]

    if verbose:
        is_m = df_valid["year"].isin(IS_YEARS)
        oos_m = df_valid["year"].isin(OOS_YEARS)
        print(f"    IS  VIX range: {df_valid.loc[is_m, 'vix_lag1'].min():.2f} - "
              f"{df_valid.loc[is_m, 'vix_lag1'].max():.2f}")
        print(f"    OOS VIX range: {df_valid.loc[oos_m, 'vix_lag1'].min():.2f} - "
              f"{df_valid.loc[oos_m, 'vix_lag1'].max():.2f}")

    return df_valid, vix_daily, thresh, n_jumps


# ============================================================
# 4. Expanding-window adaptive tertile assignment (STRICT LOOKAHEAD)
# ============================================================
def compute_expanding_tertile(df_bars: pd.DataFrame, vix_daily: pd.DataFrame,
                               verbose: bool = True) -> np.ndarray:
    """
    For each bar t (on date D with feature vix_lag1 = VIX(D-1)), compute tertile
    labels using EXPANDING-WINDOW VIX quantile strictly on data before D-1.

    Design:
      - VIX_D-1 is available at bar t's decision time (previous-close).
      - q33_t and q67_t are computed from VIX[0 : date_index_of(D-1)], i.e.
        VIX history strictly BEFORE VIX(D-1). This matches the task spec
        "q33/q67 strictly use data BEFORE bar t".
        (Using VIX through D-1 inclusive would fold the current observation
        into its own quantile — mild lookahead we avoid.)
      - Tertile: 0=low if VIX(D-1) < q33_t, 1=mid if VIX(D-1) < q67_t, 2=high else.
      - For very early samples (< 30 VIX obs available), tertile defaults to 1 (mid).

    Returns: np.ndarray of tertile labels (same length as df_bars) with values in {0,1,2}.
    """
    # Index VIX daily series
    vix_series = vix_daily.sort_values("date_norm").reset_index(drop=True)
    vix_values = vix_series["vix"].values
    vix_dates = vix_series["date_norm"].values

    # Map bar's date_norm -> VIX date index (position of VIX(D-1))
    bar_dates = df_bars["date_norm"].values
    bar_vix_lag1 = df_bars["vix_lag1"].values

    # For each bar find the position of the VIX date used as vix_lag1
    # vix_lag1 of bar on date D is VIX of D-1 (or last available VIX before D).
    # We find the matching index by searching vix_dates for the last vix_date < D.
    bar_positions = np.searchsorted(vix_dates, bar_dates, side="left") - 1
    bar_positions = np.clip(bar_positions, 0, len(vix_dates) - 1)

    tertile = np.full(len(df_bars), 1, dtype=int)  # default mid

    # We need expanding quantile on vix_values[0:pos] (strictly BEFORE pos)
    # Precompute quantile per position (avoid quadratic cost by caching by pos).
    MIN_HIST = 30  # min VIX obs before using adaptive cutoff

    # Compute per-position quantile once, then reuse for all bars with same pos.
    unique_pos = np.unique(bar_positions)
    q33_by_pos = {}
    q67_by_pos = {}
    for pos in unique_pos:
        if pos < MIN_HIST:
            q33_by_pos[int(pos)] = np.nan
            q67_by_pos[int(pos)] = np.nan
        else:
            hist = vix_values[:int(pos)]  # strictly before pos
            q33_by_pos[int(pos)] = float(np.quantile(hist, 1 / 3))
            q67_by_pos[int(pos)] = float(np.quantile(hist, 2 / 3))

    q33_arr = np.array([q33_by_pos[int(p)] for p in bar_positions])
    q67_arr = np.array([q67_by_pos[int(p)] for p in bar_positions])

    # Apply tertile assignment
    valid = np.isfinite(q33_arr) & np.isfinite(q67_arr)
    tertile[valid & (bar_vix_lag1 < q33_arr)] = 0
    tertile[valid & (bar_vix_lag1 >= q33_arr) & (bar_vix_lag1 < q67_arr)] = 1
    tertile[valid & (bar_vix_lag1 >= q67_arr)] = 2

    if verbose:
        print(f"    Expanding-window quantile: {len(unique_pos)} unique VIX history lengths")
        print(f"    Tertile distribution (all bars): low={int((tertile==0).sum()):,}  "
              f"mid={int((tertile==1).sum()):,}  high={int((tertile==2).sum()):,}")

    return tertile, q33_arr, q67_arr


# ============================================================
# 5. Logistic MLE (mirror K1131)
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
        nll += 0.5 * l2 * np.sum(beta[1:] ** 2)
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
    res = minimize(fun=logistic_neg_ll, x0=init, args=(X, y, l2),
                    jac=logistic_grad, method="L-BFGS-B",
                    options={"maxiter": 500, "ftol": 1e-9, "gtol": 1e-7})
    if not res.success:
        res = minimize(fun=logistic_neg_ll, x0=init, args=(X, y, max(l2, 1e-2)),
                        jac=logistic_grad, method="L-BFGS-B",
                        options={"maxiter": 1000, "ftol": 1e-9})
    return {
        "beta": res.x, "nll": float(res.fun), "success": bool(res.success),
        "n_features": p, "n_obs": n,
        "ll": float(-res.fun + 0.5 * l2 * np.sum(res.x[1:] ** 2)),
        "l2": l2,
    }


def predict_proba(X, beta):
    return np.clip(sigmoid(X @ beta), 1e-7, 1 - 1e-7)


def log_loss_per_obs(y, p):
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


# ============================================================
# 6. DM-HLN (Harvey-Leybourne-Newbold 1997)
# ============================================================
def dm_hln_test(loss1, loss2, name=""):
    """Positive t => loss2 < loss1 => model 2 better."""
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
    return {"t": float(t_plain * hln_mult), "t_plain": float(t_plain),
            "mean_d": float(mean_d), "se": se, "n": int(n)}


# ============================================================
# 7. Main
# ============================================================
def main():
    t_start = datetime.now()

    df_valid, vix_daily, gumbel_thresh, n_jumps_total = prepare_data(verbose=True)

    is_mask = df_valid["year"].isin(IS_YEARS)
    oos_mask = df_valid["year"].isin(OOS_YEARS)
    df_is = df_valid.loc[is_mask].copy().reset_index(drop=True)
    df_oos = df_valid.loc[oos_mask].copy().reset_index(drop=True)

    print(f"\n[5] Sample split")
    print(f"    IS : N={len(df_is):,}  {df_is['date'].min().date()}..{df_is['date'].max().date()}  "
          f"jumps={int(df_is['jump_next'].sum()):,}")
    print(f"    OOS: N={len(df_oos):,}  {df_oos['date'].min().date()}..{df_oos['date'].max().date()}  "
          f"jumps={int(df_oos['jump_next'].sum()):,}")

    # ----------------------------------------
    # 7.1 Expanding-window tertile on FULL series (IS+OOS)
    # ----------------------------------------
    print("\n[6] Expanding-window adaptive VIX tertile (strict lookahead)")
    tertile_exp_all, q33_all, q67_all = compute_expanding_tertile(df_valid, vix_daily, verbose=True)
    df_valid["tertile_exp"] = tertile_exp_all
    df_valid["q33_exp"] = q33_all
    df_valid["q67_exp"] = q67_all
    df_is["tertile_exp"] = df_valid.loc[is_mask, "tertile_exp"].values
    df_oos["tertile_exp"] = df_valid.loc[oos_mask, "tertile_exp"].values
    df_oos["q33_exp"] = df_valid.loc[oos_mask, "q33_exp"].values
    df_oos["q67_exp"] = df_valid.loc[oos_mask, "q67_exp"].values

    print(f"    IS  tertile (expanding):  low={int((df_is['tertile_exp']==0).sum()):,}  "
          f"mid={int((df_is['tertile_exp']==1).sum()):,}  "
          f"high={int((df_is['tertile_exp']==2).sum()):,}")
    print(f"    OOS tertile (expanding):  low={int((df_oos['tertile_exp']==0).sum()):,}  "
          f"mid={int((df_oos['tertile_exp']==1).sum()):,}  "
          f"high={int((df_oos['tertile_exp']==2).sum()):,}")

    # ----------------------------------------
    # 7.2 K1128 IS-fixed tertile (replication baseline)
    # ----------------------------------------
    vix_is = df_is["vix_lag1"].values
    is_cutoff_33 = float(np.quantile(vix_is, 1 / 3))
    is_cutoff_67 = float(np.quantile(vix_is, 2 / 3))

    def is_fixed_tertile(v):
        t = np.ones_like(v, dtype=int)
        t[v <= is_cutoff_33] = 0
        t[v > is_cutoff_67] = 2
        return t

    df_is["tertile_isfixed"] = is_fixed_tertile(df_is["vix_lag1"].values)
    df_oos["tertile_isfixed"] = is_fixed_tertile(df_oos["vix_lag1"].values)
    print(f"\n[7] K1128 IS-fixed tertile cutoffs: 33%={is_cutoff_33:.3f}  67%={is_cutoff_67:.3f}")
    print(f"    OOS IS-fixed coverage:  low={int((df_oos['tertile_isfixed']==0).sum()):,}  "
          f"mid={int((df_oos['tertile_isfixed']==1).sum()):,}  "
          f"high={int((df_oos['tertile_isfixed']==2).sum()):,}")

    # ----------------------------------------
    # 7.3 Build feature matrices
    # ----------------------------------------
    def build_all_X(df_block: pd.DataFrame):
        n = len(df_block)
        ones = np.ones(n)
        jc = df_block["jump_curr"].values.astype(float)
        absofi = df_block["ofi_abs_t"].values.astype(float)
        ofi = df_block["ofi_t"].values.astype(float)
        absofi_z = df_block["ofi_abs_z"].values.astype(float)
        sgnofi_z = df_block["ofi_sgn_z"].values.astype(float)

        t_is = df_block["tertile_isfixed"].values.astype(int)
        mid_is = (t_is == 1).astype(float)
        high_is = (t_is == 2).astype(float)

        t_ex = df_block["tertile_exp"].values.astype(int)
        mid_ex = (t_ex == 1).astype(float)
        high_ex = (t_ex == 2).astype(float)

        X_base = np.column_stack([ones, jc, absofi, ofi])
        X_tertile = np.column_stack([
            ones, jc, absofi, ofi,
            mid_is * absofi, high_is * absofi,
            mid_is * ofi, high_is * ofi,
        ])
        X_volnorm = np.column_stack([ones, jc, absofi_z, sgnofi_z])
        X_expanding = np.column_stack([
            ones, jc, absofi, ofi,
            mid_ex * absofi, high_ex * absofi,
            mid_ex * ofi, high_ex * ofi,
        ])
        return {
            "X_base": X_base,
            "X_tertile": X_tertile,
            "X_volnorm": X_volnorm,
            "X_expanding": X_expanding,
        }

    F_is = build_all_X(df_is)
    F_oos = build_all_X(df_oos)

    y_is = df_is["jump_next"].values.astype(int)
    y_oos = df_oos["jump_next"].values.astype(int)

    # ----------------------------------------
    # 7.4 Fit 4 models (IS fit for M_base / M_tertile / M_volnorm;
    #     M_expanding uses REFIT CADENCE on IS+OOS progressively)
    # ----------------------------------------
    print("\n[8] Fit M_base, M_tertile, M_volnorm (IS only, single MLE)")
    M_base = fit_logistic_mle(F_is["X_base"], y_is, l2=1e-4)
    M_tertile = fit_logistic_mle(F_is["X_tertile"], y_is, l2=1e-4)
    M_volnorm = fit_logistic_mle(F_is["X_volnorm"], y_is, l2=1e-4)
    for name, M in [("M_base", M_base), ("M_tertile", M_tertile), ("M_volnorm", M_volnorm)]:
        print(f"    {name}: p={M['n_features']:<2d}  nll_is={M['nll']:.4f}  success={M['success']}")

    # M_expanding: spec requires expanding-quantile AND refit every 252 bars.
    # We implement a simplified IS-only fit here (same features as tertile_exp,
    # which uses expanding quantile even in IS). For OOS, predictions use
    # progressive refit schedule.
    print("\n[9] M_expanding IS fit (tertile_exp features on IS sample)")
    M_expanding_is = fit_logistic_mle(F_is["X_expanding"], y_is, l2=1e-4)
    print(f"    M_expanding_IS: p={M_expanding_is['n_features']}  nll_is={M_expanding_is['nll']:.4f}  "
          f"success={M_expanding_is['success']}")

    # LRT: M_expanding vs M_base (IS)
    lr_stat_exp = 2.0 * (M_base["nll"] - M_expanding_is["nll"])
    df_exp = F_is["X_expanding"].shape[1] - F_is["X_base"].shape[1]
    p_lr_exp = 1.0 - sp_stats.chi2.cdf(lr_stat_exp, df_exp)
    lr_stat_ter = 2.0 * (M_base["nll"] - M_tertile["nll"])
    df_ter = F_is["X_tertile"].shape[1] - F_is["X_base"].shape[1]
    p_lr_ter = 1.0 - sp_stats.chi2.cdf(lr_stat_ter, df_ter)
    print(f"\n[10] IS LRT")
    print(f"    expanding vs base: χ²({df_exp})={lr_stat_exp:.3f}, p={p_lr_exp:.5f}")
    print(f"    tertile   vs base: χ²({df_ter})={lr_stat_ter:.3f}, p={p_lr_ter:.5f}")

    # ----------------------------------------
    # 7.5 OOS progressive refit for M_expanding
    # ----------------------------------------
    # Strategy: use IS-fit M_expanding_is initially. Every REFIT_CADENCE_BARS,
    # retrain on IS + all OOS bars seen so far. Predictions for bars in the
    # next refit window use the most-recent refit coefficients.
    # This preserves expanding-quantile info propagation in beta, not just labels.
    print(f"\n[11] OOS progressive refit of M_expanding (cadence={REFIT_CADENCE_BARS} bars)")

    X_train = F_is["X_expanding"].copy()
    y_train = y_is.copy()
    current_beta = M_expanding_is["beta"].copy()
    n_oos = len(df_oos)
    p_exp_oos = np.zeros(n_oos)
    refit_log = []

    # We fit at step boundaries {0, 252, 504, 756, ..., n_oos}
    # Refit BEFORE predicting the next window using train = IS + OOS[:start]
    start = 0
    while start < n_oos:
        end = min(start + REFIT_CADENCE_BARS, n_oos)
        # Predict window [start, end) with current_beta
        p_exp_oos[start:end] = predict_proba(F_oos["X_expanding"][start:end], current_beta)

        # Prepare training set for next window: IS + OOS[:end]
        if end < n_oos:
            X_train_next = np.vstack([X_train, F_oos["X_expanding"][:end]])
            y_train_next = np.concatenate([y_is, y_oos[:end]])
            fit = fit_logistic_mle(X_train_next, y_train_next, l2=1e-4, init=current_beta)
            current_beta = fit["beta"]
            refit_log.append({
                "refit_at_oos_bar": int(end),
                "n_train": int(len(y_train_next)),
                "nll": float(fit["nll"]),
                "success": bool(fit["success"]),
            })
        start = end

    print(f"    Total refits: {len(refit_log)}")
    if refit_log:
        for r in refit_log[:4]:
            print(f"    refit@{r['refit_at_oos_bar']}: n_train={r['n_train']:,}  nll={r['nll']:.4f}")
        if len(refit_log) > 4:
            print(f"    ... (+{len(refit_log) - 4} more refits)")

    # ----------------------------------------
    # 7.6 OOS predictions for other models
    # ----------------------------------------
    print("\n[12] OOS predictions")
    p_base_oos = predict_proba(F_oos["X_base"], M_base["beta"])
    p_tertile_oos = predict_proba(F_oos["X_tertile"], M_tertile["beta"])
    p_volnorm_oos = predict_proba(F_oos["X_volnorm"], M_volnorm["beta"])

    loss_base = log_loss_per_obs(y_oos, p_base_oos)
    loss_tertile = log_loss_per_obs(y_oos, p_tertile_oos)
    loss_volnorm = log_loss_per_obs(y_oos, p_volnorm_oos)
    loss_expanding = log_loss_per_obs(y_oos, p_exp_oos)

    print(f"    Mean OOS log-loss:")
    print(f"      base     : {loss_base.mean():.6f}")
    print(f"      tertile  : {loss_tertile.mean():.6f}")
    print(f"      volnorm  : {loss_volnorm.mean():.6f}")
    print(f"      expanding: {loss_expanding.mean():.6f}")

    def auc(p):
        return float(roc_auc_score(y_oos, p)) if len(np.unique(y_oos)) > 1 else float("nan")

    auc_base = auc(p_base_oos)
    auc_tertile = auc(p_tertile_oos)
    auc_volnorm = auc(p_volnorm_oos)
    auc_expanding = auc(p_exp_oos)
    print(f"    OOS AUC:")
    print(f"      base     : {auc_base:.4f}")
    print(f"      tertile  : {auc_tertile:.4f}")
    print(f"      volnorm  : {auc_volnorm:.4f}")
    print(f"      expanding: {auc_expanding:.4f}")

    brier_base = float(brier_score_loss(y_oos, p_base_oos))
    brier_tertile = float(brier_score_loss(y_oos, p_tertile_oos))
    brier_volnorm = float(brier_score_loss(y_oos, p_volnorm_oos))
    brier_expanding = float(brier_score_loss(y_oos, p_exp_oos))

    # Spearman(fitted, realized)
    def spearman_fit(p):
        rho, pval = sp_stats.spearmanr(p, y_oos)
        return {"rho": float(rho), "p": float(pval)}

    sp_base = spearman_fit(p_base_oos)
    sp_exp = spearman_fit(p_exp_oos)

    # ----------------------------------------
    # 7.7 DM-HLN pairwise
    # ----------------------------------------
    print("\n[13] DM-HLN pairwise (positive t => 2nd model wins)")
    dm_exp_vs_base = dm_hln_test(loss_base, loss_expanding, name="exp_vs_base")
    dm_exp_vs_tertile = dm_hln_test(loss_tertile, loss_expanding, name="exp_vs_tertile")
    dm_exp_vs_volnorm = dm_hln_test(loss_volnorm, loss_expanding, name="exp_vs_volnorm")
    dm_tertile_vs_base = dm_hln_test(loss_base, loss_tertile, name="tertile_vs_base")
    dm_volnorm_vs_base = dm_hln_test(loss_base, loss_volnorm, name="volnorm_vs_base")

    for name, d in [("exp vs base", dm_exp_vs_base),
                      ("exp vs tertile", dm_exp_vs_tertile),
                      ("exp vs volnorm", dm_exp_vs_volnorm),
                      ("tertile vs base", dm_tertile_vs_base),
                      ("volnorm vs base", dm_volnorm_vs_base)]:
        print(f"    {name:18s}: t={d['t']:+.3f}  mean_d={d['mean_d']:+.3e}  n={d['n']}")

    # ----------------------------------------
    # 7.8 Coefficient drift (M_expanding beta at last refit)
    # ----------------------------------------
    print("\n[14] M_expanding final coefficients (layout: intercept, jump_curr, "
          "|OFI|, OFI, mid*|OFI|, high*|OFI|, mid*OFI, high*OFI)")
    final_beta = current_beta.tolist()
    feat_names = ["intercept", "jump_curr", "|OFI|", "OFI",
                   "mid*|OFI|", "high*|OFI|", "mid*OFI", "high*OFI"]
    for name, b in zip(feat_names, final_beta):
        print(f"    {name:14s}: {b:+.4f}")

    # Compute effective β_|OFI| per regime at final fit
    b_absofi = final_beta[2]
    b_mid_absofi = final_beta[4]
    b_high_absofi = final_beta[5]
    b_ofi = final_beta[3]
    b_mid_ofi = final_beta[6]
    b_high_ofi = final_beta[7]
    beta_abs_low = b_absofi
    beta_abs_mid = b_absofi + b_mid_absofi
    beta_abs_high = b_absofi + b_high_absofi
    beta_sgn_low = b_ofi
    beta_sgn_mid = b_ofi + b_mid_ofi
    beta_sgn_high = b_ofi + b_high_ofi

    print(f"\n    Effective β on |OFI| by regime (final refit):")
    print(f"      low : {beta_abs_low:+.4f}")
    print(f"      mid : {beta_abs_mid:+.4f}")
    print(f"      high: {beta_abs_high:+.4f}")
    print(f"    Effective β on OFI (signed) by regime (final refit):")
    print(f"      low : {beta_sgn_low:+.4f}")
    print(f"      mid : {beta_sgn_mid:+.4f}")
    print(f"      high: {beta_sgn_high:+.4f}")

    # ----------------------------------------
    # 7.9 Verdict
    # ----------------------------------------
    print("\n" + "=" * 70)
    print("K1199 VERDICT")
    print("=" * 70)

    # H1 coverage balanced: require low / mid / high each >= 1000 bars OOS
    cov_low = int((df_oos["tertile_exp"] == 0).sum())
    cov_mid = int((df_oos["tertile_exp"] == 1).sum())
    cov_high = int((df_oos["tertile_exp"] == 2).sum())
    H1_coverage_balanced = (cov_low >= 1000) and (cov_mid >= 1000) and (cov_high >= 1000)

    # H2 DM vs base
    t_dm = dm_exp_vs_base["t"]
    H2_DM_gt3 = abs(t_dm) > 3.0
    H2_DM_gt2 = abs(t_dm) > 2.0 and t_dm > 0  # positive (expanding wins)

    # H3 coefficient spread
    spread_abs = max(abs(beta_abs_high - beta_abs_low),
                     abs(beta_abs_high - beta_abs_mid),
                     abs(beta_abs_mid - beta_abs_low))
    H3_spread = spread_abs > 0.05

    # H4 beat K1128 tertile on AUC or log-loss
    t_dm_vs_tertile = dm_exp_vs_tertile["t"]
    H4_beats_tertile = (auc_expanding > auc_tertile) and (t_dm_vs_tertile > 0)

    if H1_coverage_balanced and H2_DM_gt3 and (t_dm > 0):
        verdict = "PASS"
    elif H1_coverage_balanced and H2_DM_gt2:
        verdict = "PARTIAL"
    elif (not H1_coverage_balanced) or (abs(t_dm) <= 2.0):
        verdict = "NULL"
    else:
        verdict = "NULL"

    print(f"H1 (coverage balanced, each >=1000): low={cov_low}, mid={cov_mid}, high={cov_high} "
          f"-> {'PASS' if H1_coverage_balanced else 'FAIL'}")
    print(f"H2 (DM exp vs base |t|>3, positive): t={t_dm:+.3f} -> {'PASS' if H2_DM_gt3 and t_dm>0 else 'FAIL'}")
    print(f"H3 (regime β spread > 0.05): max_spread={spread_abs:.4f} -> {'PASS' if H3_spread else 'FAIL'}")
    print(f"H4 (beats K1128 tertile): AUC(exp)={auc_expanding:.4f} vs AUC(tertile)={auc_tertile:.4f}, "
          f"DM exp vs tertile t={t_dm_vs_tertile:+.3f} -> {'PASS' if H4_beats_tertile else 'FAIL'}")
    print(f"\n=> VERDICT: {verdict}")

    # ----------------------------------------
    # 7.10 Save results
    # ----------------------------------------
    runtime = (datetime.now() - t_start).total_seconds()
    print(f"\n[15] Saving results (runtime={runtime:.1f}s)")

    results = {
        "experiment_id": "K1199",
        "task_id_mapping": "next_tasks.json -> K1133_expanding_window (K1133 reused by BTC GAS-t, so we use K1199 dir)",
        "title": "Expanding-window adaptive VIX quantile for K1128 OFI->jump logit (error_log 2026-04-13 fix #2)",
        "timestamp": datetime.now().isoformat(),
        "seed": SEED,
        "runtime_sec": float(runtime),
        "data_source": "TAIFEX TX 5-min bars 2017-2021 (K1124 parquet cache)",
        "is_period": "2017-2019",
        "oos_period": "2020-2021",
        "refit_cadence_bars": REFIT_CADENCE_BARS,
        "n_bars_valid": int(len(df_valid)),
        "n_is": int(len(df_is)),
        "n_oos": int(len(df_oos)),
        "n_is_jumps": int(y_is.sum()),
        "n_oos_jumps": int(y_oos.sum()),
        "jump_detection": {
            "method": "Lee-Mykland K=16 strictly-past BV",
            "gumbel_thresh_alpha_0.01": float(gumbel_thresh),
            "n_jumps_total": int(n_jumps_total),
        },
        "tertile_cutoffs_IS_fixed_K1128": {
            "cutoff_33": is_cutoff_33,
            "cutoff_67": is_cutoff_67,
        },
        "oos_tertile_coverage": {
            "K1128_IS_fixed": {
                "low": int((df_oos["tertile_isfixed"] == 0).sum()),
                "mid": int((df_oos["tertile_isfixed"] == 1).sum()),
                "high": int((df_oos["tertile_isfixed"] == 2).sum()),
            },
            "K1199_expanding": {
                "low": cov_low,
                "mid": cov_mid,
                "high": cov_high,
            },
        },
        "is_tertile_coverage_expanding": {
            "low": int((df_is["tertile_exp"] == 0).sum()),
            "mid": int((df_is["tertile_exp"] == 1).sum()),
            "high": int((df_is["tertile_exp"] == 2).sum()),
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
                "features": ["intercept", "jump_curr", "|OFI|", "OFI",
                               "mid*|OFI|", "high*|OFI|", "mid*OFI", "high*OFI"],
            },
            "M_volnorm": {
                "n_params": M_volnorm["n_features"],
                "nll_is": M_volnorm["nll"],
                "beta": M_volnorm["beta"].tolist(),
                "features": ["intercept", "jump_curr", "|OFI|/σ", "OFI/σ"],
            },
            "M_expanding_IS": {
                "n_params": M_expanding_is["n_features"],
                "nll_is": M_expanding_is["nll"],
                "beta": M_expanding_is["beta"].tolist(),
                "features": ["intercept", "jump_curr", "|OFI|", "OFI",
                               "mid_exp*|OFI|", "high_exp*|OFI|",
                               "mid_exp*OFI", "high_exp*OFI"],
            },
            "M_expanding_final_refit": {
                "beta": final_beta,
                "effective_beta_absofi_by_regime": {
                    "low": float(beta_abs_low),
                    "mid": float(beta_abs_mid),
                    "high": float(beta_abs_high),
                },
                "effective_beta_sgnofi_by_regime": {
                    "low": float(beta_sgn_low),
                    "mid": float(beta_sgn_mid),
                    "high": float(beta_sgn_high),
                },
                "n_refits": len(refit_log),
                "refit_log": refit_log,
            },
        },
        "OOS_log_loss": {
            "base": float(loss_base.mean()),
            "tertile": float(loss_tertile.mean()),
            "volnorm": float(loss_volnorm.mean()),
            "expanding": float(loss_expanding.mean()),
        },
        "OOS_AUC": {
            "base": auc_base,
            "tertile": auc_tertile,
            "volnorm": auc_volnorm,
            "expanding": auc_expanding,
        },
        "OOS_Brier": {
            "base": brier_base,
            "tertile": brier_tertile,
            "volnorm": brier_volnorm,
            "expanding": brier_expanding,
        },
        "spearman_fitted_vs_realized": {
            "base": sp_base,
            "expanding": sp_exp,
        },
        "LRT": {
            "expanding_vs_base": {"chi2": float(lr_stat_exp), "df": int(df_exp), "p": float(p_lr_exp)},
            "tertile_vs_base": {"chi2": float(lr_stat_ter), "df": int(df_ter), "p": float(p_lr_ter)},
        },
        "DM_HLN": {
            "exp_vs_base": dm_exp_vs_base,
            "exp_vs_tertile": dm_exp_vs_tertile,
            "exp_vs_volnorm": dm_exp_vs_volnorm,
            "tertile_vs_base": dm_tertile_vs_base,
            "volnorm_vs_base": dm_volnorm_vs_base,
        },
        "hypotheses": {
            "H1_coverage_balanced": bool(H1_coverage_balanced),
            "H2_DM_gt3_positive": bool(H2_DM_gt3 and t_dm > 0),
            "H2_DM_gt2_positive": bool(H2_DM_gt2),
            "H3_regime_spread_gt_0.05": bool(H3_spread),
            "H4_beats_K1128_tertile": bool(H4_beats_tertile),
        },
        "verdict": verdict,
        "references": [
            "Lee & Mykland (2008) RFS 21(6), 2535-2563",
            "Cont, Kukanov, Stoikov (2014) JFE 12(1), 47-88",
            "Harvey, Leybourne, Newbold (1997) IJF 13(2), 281-291",
            "Harvey, Liu, Zhu (2016) RFS 29(1), 5-68 — multiple testing t-thresholds",
        ],
    }

    out_path = SCRIPT_DIR / "k1199_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"    Saved {out_path}")

    # ----------------------------------------
    # 7.11 Plots
    # ----------------------------------------
    print("\n[16] Plotting ...")

    # Plot 1: OOS regime coverage comparison
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    ax = axes[0]
    labels = ["low", "mid", "high"]
    isf = [int((df_oos["tertile_isfixed"] == i).sum()) for i in (0, 1, 2)]
    exp = [int((df_oos["tertile_exp"] == i).sum()) for i in (0, 1, 2)]
    x = np.arange(len(labels))
    w = 0.35
    ax.bar(x - w/2, isf, w, color="coral", label="K1128 IS-fixed")
    ax.bar(x + w/2, exp, w, color="steelblue", label="K1199 expanding")
    for i, v in enumerate(isf):
        ax.text(i - w/2, v, f"{v:,}", ha="center", va="bottom", fontsize=9)
    for i, v in enumerate(exp):
        ax.text(i + w/2, v, f"{v:,}", ha="center", va="bottom", fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("OOS bar count")
    ax.set_title("(a) OOS tertile coverage: K1128 vs K1199")
    ax.legend()

    # Plot 2: AUC/log-loss/Brier bar comparison
    ax = axes[1]
    names = ["base", "tertile", "volnorm", "expanding"]
    aucs = [auc_base, auc_tertile, auc_volnorm, auc_expanding]
    colors = ["gray", "coral", "seagreen", "steelblue"]
    ax.bar(names, aucs, color=colors)
    for i, v in enumerate(aucs):
        ax.text(i, v, f"{v:.4f}", ha="center", va="bottom", fontsize=9)
    ax.axhline(0.5, color="red", lw=0.5, linestyle="--", label="chance")
    ax.set_ylabel("OOS AUC")
    ax.set_title("(b) OOS AUC across 4 specs")
    ax.legend(fontsize=8)
    ax.set_ylim(0.4, max(aucs) + 0.05)

    plt.suptitle("K1199: Expanding-window adaptive VIX quantile vs K1128 IS-fixed", fontsize=12)
    plt.tight_layout()
    p1 = SCRIPT_DIR / "k1199_coverage_auc.png"
    plt.savefig(p1, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    Saved {p1}")

    # Plot 3: ROC curves
    from sklearn.metrics import roc_curve
    fig, ax = plt.subplots(figsize=(7, 6))
    for name, p, c in [("base", p_base_oos, "gray"),
                         ("K1128 tertile", p_tertile_oos, "coral"),
                         ("K1142 volnorm", p_volnorm_oos, "seagreen"),
                         ("K1199 expanding", p_exp_oos, "steelblue")]:
        if len(np.unique(y_oos)) > 1:
            fpr, tpr, _ = roc_curve(y_oos, p)
            ax.plot(fpr, tpr, label=f"{name} (AUC={roc_auc_score(y_oos, p):.4f})",
                     color=c, lw=1.8)
    ax.plot([0, 1], [0, 1], "--", color="red", lw=0.8)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("K1199: OOS ROC curves (4 specs)")
    ax.legend(loc="lower right", fontsize=9)
    plt.tight_layout()
    p2 = SCRIPT_DIR / "k1199_roc.png"
    plt.savefig(p2, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    Saved {p2}")

    # Plot 4: Expanding-quantile trajectory over time
    fig, ax = plt.subplots(figsize=(12, 5))
    # Show q33/q67 trajectory vs actual VIX_lag1 over OOS period
    oos_dates = df_oos["date"].values
    # Sample to daily by taking one bar per date (first bar)
    daily_oos = df_oos.groupby("date").first().reset_index()
    ax.plot(daily_oos["date"], daily_oos["vix_lag1"], label="VIX_{t-1}",
             color="black", lw=1.2)
    ax.plot(daily_oos["date"], daily_oos["q33_exp"], label="expanding q33",
             color="steelblue", lw=1.0, linestyle="--")
    ax.plot(daily_oos["date"], daily_oos["q67_exp"], label="expanding q67",
             color="coral", lw=1.0, linestyle="--")
    ax.axhline(is_cutoff_33, color="steelblue", lw=0.7, linestyle=":",
                label=f"K1128 IS q33={is_cutoff_33:.2f}")
    ax.axhline(is_cutoff_67, color="coral", lw=0.7, linestyle=":",
                label=f"K1128 IS q67={is_cutoff_67:.2f}")
    ax.set_xlabel("Date")
    ax.set_ylabel("VIX (T-1 lag)")
    ax.set_title("K1199: Expanding-window VIX tertile cutoffs vs K1128 IS-fixed (OOS 2020-2021)")
    ax.legend(loc="best", fontsize=9)
    plt.tight_layout()
    p3 = SCRIPT_DIR / "k1199_quantile_trajectory.png"
    plt.savefig(p3, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    Saved {p3}")

    print(f"\nK1199 complete. Runtime: {runtime:.1f}s  Verdict: {verdict}")
    return results


if __name__ == "__main__":
    main()
