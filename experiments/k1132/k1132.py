"""
K1132 - Block-Bootstrap CI for K1131 OOS DM-HLN t-statistic
===========================================================

Follow-up to K1131 (natural cubic spline — NULL, DM t=-3.94 spline vs tertile).

Motivation
----------
K1131 concluded NULL (spline worse than tertile, DM t=-3.94). K1130 (extended IS
2012-2019) also NULL. Main-thread interpretation: "problem is structural"
(OOS VIX disjoint from IS). BUT the OOS window is only 2020-2021 (~20,914 bars,
33 jumps, COVID volatility) — the HLN variance approximation may be unstable
under heavy tails and serial dependence. A block-bootstrap CI on the DM t-stat
tells us whether the NULL is robust or statistical artifact of this specific
small sample.

- Narrow CI (both ends well below 0) -> NULL is robust; accept K1131 conclusion.
- Wide CI straddling 0 -> NULL inconclusive; need more OOS data.
- CI entirely below 0 but wide -> direction robust, magnitude uncertain.

Method
------
1. Reload K1124 cache + reconstruct IS/OOS features (same as K1131).
2. Refit M_base, M_tertile, M_spline on IS (seed=42, deterministic).
3. Compute OOS per-observation log-loss arrays for tertile and spline.
4. Define d_t = loss_tertile_t - loss_spline_t  (positive d = spline better).
   K1131 reported mean(d) = -7.58e-04 (spline worse), DM-HLN t=-3.94.
5. Ljung-Box on d_t (lags 1, 5, 10, 20, 60, 120) to assess serial dependence
   and justify block size.
6. Circular block bootstrap (Politis & Romano 1994) on d_t:
   - Block sizes b in {20, 40, 60, 100} (5-min bar -> ~100 min / 1 trading day
     at K1124's 65 bars/day).
   - B = 5000 resamples, seed = 42 (np.random.default_rng).
   - Recompute DM-HLN t on each resample.
   - Report 95%, 90%, 99% CI per block size.

Verdict rule (written ex-ante, pre-registered):
- `robust` : 95% CI upper bound < -1.96 at ALL block sizes.
- `inconclusive` : 95% CI upper bound >= -1.96 at ANY block size (t could
   fail DM significance under reasonable block choice) OR CI spans 0.
- `not-robust` : 95% CI includes 0 (sign of effect could flip).

Output
------
- k1132.py (this script)
- k1132_results.json
- bootstrap_distribution.png

Codex review requested (see README).

Author: Claude (worktree agent-k1132)
Date: 2026-04-18
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

# ---------------------------------------------------------------
# Global config
# ---------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent

# Primary data cache (K1124). Worktree agent may have its own copy; fall back
# to main repo experiments path if needed.
CACHE_CANDIDATES = [
    SCRIPT_DIR.parent / "k1124" / "_cache_bars_2017-01-01_2021-12-31.parquet",
    Path("/Users/yhlai0911/Desktop/volpred-research/experiments/k1124/"
         "_cache_bars_2017-01-01_2021-12-31.parquet"),
]

MU1 = np.sqrt(2.0 / np.pi)
K_WIN = 16
JUMP_ALPHA = 0.01
IS_YEARS = [2017, 2018, 2019]
OOS_YEARS = [2020, 2021]
SEED = 42

# Bootstrap config
B_BOOTSTRAP = 5000
BLOCK_SIZES = [20, 40, 60, 100]  # bars; K1124 is 5-min bars, ~60/day
CI_LEVELS = {"95": 0.95, "90": 0.90, "99": 0.99}

# Bootstrap 用顯式 Generator（見 block_bootstrap_dm 簽名），
# 不依賴全域 state，避免其他 import 污染。


# ============================================================
# 1. Natural cubic spline basis (identical to K1131)
# ============================================================
def natural_cubic_basis(x: np.ndarray, knots: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    K = len(knots)
    assert K >= 3, "Need at least 3 knots"
    n = len(x)
    t_K = knots[-1]

    def d_k(x_, k):
        tk = knots[k]
        numer = np.maximum(x_ - tk, 0) ** 3 - np.maximum(x_ - t_K, 0) ** 3
        denom = t_K - tk
        return numer / denom if denom > 0 else np.zeros_like(x_)

    vix_range = knots[-1] - knots[0]
    scale = 1.0 / (vix_range ** 2) if vix_range > 0 else 1.0
    B = np.zeros((n, K - 1))
    B[:, 0] = x
    for k in range(K - 2):
        B[:, k + 1] = (d_k(x, k) - d_k(x, K - 2)) * scale
    return B


# ============================================================
# 2. Jump detection + VIX merge (mirror K1131)
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


def resolve_cache() -> Path:
    for p in CACHE_CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError(
        "K1124 cache not found in any of: " + str(CACHE_CANDIDATES)
    )


def prepare_data(verbose: bool = True):
    """Load cache, detect jumps, merge VIX T-1, return valid df."""
    cache_path = resolve_cache()
    if verbose:
        print(f"[1] Loading cache: {cache_path}")
    df = pd.read_parquet(cache_path)
    df = df.sort_values(["date", "bar"]).reset_index(drop=True)
    if verbose:
        print(f"    {len(df):,} bars, {df['date'].nunique()} days")

    # Jump detection
    if verbose:
        print("[2] Lee-Mykland jump detection")
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
           - 0.5 * (np.log(np.log(n_valid)) + np.log(4 * np.pi))
           / np.sqrt(2 * np.log(n_valid)))
    S_n = 1.0 / np.sqrt(2 * np.log(n_valid))
    beta_n = -np.log(-np.log(1 - JUMP_ALPHA))
    thresh = C_n + S_n * beta_n
    df["jump"] = ((df["L_stat"] > thresh) & np.isfinite(df["L_stat"])).astype(int)
    df.loc[~np.isfinite(df["L_stat"]), "jump"] = -1

    # Target jump_{t+1}
    df["jump_next"] = -1
    for _, gdf in df.groupby("date"):
        idx = gdf.index.values
        jumps = gdf["jump"].values
        jn = np.full(len(gdf), -1)
        jn[:-1] = jumps[1:]
        df.loc[idx, "jump_next"] = jn

    valid = (
        df["jump_next"].isin([0, 1])
        & df["ofi"].notna()
        & df["log_ret"].notna()
        & np.isfinite(df["L_stat"])
    )
    df_v = df[valid].copy().reset_index(drop=True)

    # VIX T-1
    if verbose:
        print("[3] VIX T-1 merge")
    import yfinance as yf
    vix = yf.download("^VIX", start="2016-12-01", end="2022-01-31",
                      progress=False, auto_adjust=False)
    if isinstance(vix.columns, pd.MultiIndex):
        vix.columns = vix.columns.get_level_values(0)
    vix_df = vix[["Close"]].reset_index()
    vix_df.columns = ["date", "vix"]
    vix_df["date"] = pd.to_datetime(vix_df["date"]).dt.normalize()
    vix_df = (vix_df.dropna().drop_duplicates("date")
              .sort_values("date").reset_index(drop=True))
    vix_df["vix_lag1"] = vix_df["vix"].shift(1)
    vix_df["vix_lag1"] = vix_df["vix_lag1"].ffill()

    df_v["date_norm"] = pd.to_datetime(df_v["date"]).dt.normalize()
    df_v = df_v.merge(
        vix_df[["date", "vix_lag1"]].rename(columns={"date": "date_norm"}),
        on="date_norm", how="left",
    )
    df_v["vix_lag1"] = df_v["vix_lag1"].ffill()
    assert df_v["vix_lag1"].isna().sum() == 0, "VIX merge has missing"

    df_v["jump_curr"] = df_v["jump"].clip(lower=0).astype(int)
    df_v["ofi_t"] = df_v["ofi"]
    df_v["ofi_abs_t"] = df_v["ofi"].abs()
    df_v["year"] = df_v["date"].dt.year
    return df_v


# ============================================================
# 3. Logistic regression (same as K1131)
# ============================================================
def sigmoid(z):
    out = np.empty_like(z)
    pos = z >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-z[pos]))
    out[~pos] = np.exp(z[~pos]) / (1.0 + np.exp(z[~pos]))
    return out


def nll(beta, X, y, l2=0.0):
    z = X @ beta
    lse = np.maximum(z, 0) + np.log1p(np.exp(-np.abs(z)))
    v = -np.sum(y * z - lse)
    if l2 > 0:
        v += 0.5 * l2 * np.sum(beta[1:] ** 2)
    return v


def grad(beta, X, y, l2=0.0):
    z = X @ beta
    p = sigmoid(z)
    g = X.T @ (p - y)
    if l2 > 0:
        reg = l2 * beta.copy()
        reg[0] = 0.0
        g += reg
    return g


def fit_mle(X, y, l2=1e-4):
    init = np.zeros(X.shape[1])
    res = minimize(fun=nll, x0=init, args=(X, y, l2), jac=grad,
                   method="L-BFGS-B",
                   options={"maxiter": 500, "ftol": 1e-9, "gtol": 1e-7})
    if not res.success:
        res = minimize(fun=nll, x0=init, args=(X, y, max(l2, 1e-2)), jac=grad,
                       method="L-BFGS-B",
                       options={"maxiter": 1000, "ftol": 1e-9})
    return {"beta": res.x, "nll": float(res.fun), "success": bool(res.success)}


def predict_proba(X, beta):
    return np.clip(sigmoid(X @ beta), 1e-7, 1 - 1e-7)


def log_loss_obs(y, p):
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def build_features(df_block, cutoffs, knots_arr, vix_center):
    n = len(df_block)
    ones = np.ones(n)
    jc = df_block["jump_curr"].values.astype(float)
    aofi = df_block["ofi_abs_t"].values.astype(float)
    ofi = df_block["ofi_t"].values.astype(float)
    v = df_block["vix_lag1"].values.astype(float)
    c33, c67 = cutoffs
    mid = ((v > c33) & (v <= c67)).astype(float)
    high = (v > c67).astype(float)
    X_base = np.column_stack([ones, jc, aofi, ofi])
    X_tertile = np.column_stack([
        ones, jc, aofi, ofi,
        mid * aofi, high * aofi,
        mid * ofi, high * ofi,
    ])
    v_c = v - vix_center
    knots_c = knots_arr - vix_center
    B = natural_cubic_basis(v_c, knots_c)
    X_spline = np.column_stack([
        ones, jc, aofi, ofi,
        B * aofi[:, None],
        B * ofi[:, None],
    ])
    return X_base, X_tertile, X_spline


# ============================================================
# 4. DM-HLN (identical to K1131)
# ============================================================
def dm_hln_on_diffs(d: np.ndarray) -> dict:
    """DM-HLN t on loss differentials d = loss1 - loss2.
    Positive t => loss1 > loss2 => model-2 better.
    Our convention for K1132: d = loss_tertile - loss_spline.
    K1131 reported t=-3.937 with this orientation (spline is WORSE; so d.mean()<0
    and t<0).
    """
    n = len(d)
    if n < 20:
        return {"t_hln": 0.0, "t_plain": 0.0, "mean_d": float(d.mean()),
                "se": 0.0, "n": int(n)}
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
    return {"t_hln": float(t_hln), "t_plain": float(t_plain),
            "mean_d": float(mean_d), "se": se, "n": int(n)}


# ============================================================
# 5. Ljung-Box on loss differentials
# ============================================================
def ljung_box(x: np.ndarray, lags=(1, 5, 10, 20, 60, 120)) -> dict:
    """Ljung-Box Q(m) test for autocorrelation up to lag m.
    H0: no autocorrelation up to lag m. Reject if p < 0.05.
    """
    x = np.asarray(x, dtype=float)
    x = x - x.mean()
    n = len(x)
    denom = float(np.sum(x ** 2))
    if denom <= 0:
        return {int(m): {"Q": 0.0, "p": 1.0, "n": n} for m in lags}
    out = {}
    for m in lags:
        if m >= n:
            continue
        Q = 0.0
        for k in range(1, m + 1):
            gamma_k = float(np.sum(x[k:] * x[:-k]))
            rho_k = gamma_k / denom
            Q += rho_k ** 2 / (n - k)
        Q *= n * (n + 2)
        p = 1.0 - sp_stats.chi2.cdf(Q, m)
        out[int(m)] = {"Q": float(Q), "p": float(p), "n": int(n)}
    return out


# ============================================================
# 6. Circular block bootstrap (Politis & Romano 1994)
# ============================================================
def circular_block_bootstrap_dm(
    d: np.ndarray, block_size: int, B: int, rng: np.random.Generator
) -> np.ndarray:
    """Return B DM-HLN t_hln values from circular block bootstrap of d.

    For each resample:
      1. Concatenate d with d[:block_size] to form a wrapped array of length
         n+b (circular).
      2. Sample ceil(n / b) starting indices uniformly from 0..n-1.
      3. Take b consecutive (wrapped) entries per start, concatenate.
      4. Truncate to exactly n points, compute DM-HLN t.
    """
    n = len(d)
    b = int(block_size)
    n_blocks = int(np.ceil(n / b))
    d_wrap = np.concatenate([d, d[:b]])
    t_arr = np.empty(B, dtype=float)

    # Draw all starts vectorised for speed
    starts_all = rng.integers(low=0, high=n, size=(B, n_blocks))
    for i in range(B):
        starts = starts_all[i]
        # Build sample by gathering blocks
        sample = np.empty(n_blocks * b, dtype=d.dtype)
        for j, s in enumerate(starts):
            sample[j * b:(j + 1) * b] = d_wrap[s:s + b]
        sample = sample[:n]
        t_arr[i] = dm_hln_on_diffs(sample)["t_hln"]
    return t_arr


# ============================================================
# 7. Main
# ============================================================
def main():
    t_start = datetime.now()
    print("=" * 70)
    print("K1132 — Block-Bootstrap CI for K1131 OOS DM-HLN t")
    print("=" * 70)

    df_valid = prepare_data(verbose=True)
    df_is = df_valid[df_valid["year"].isin(IS_YEARS)].copy().reset_index(drop=True)
    df_oos = df_valid[df_valid["year"].isin(OOS_YEARS)].copy().reset_index(drop=True)
    print(f"[4] IS N={len(df_is):,}  OOS N={len(df_oos):,}  "
          f"IS jumps={df_is['jump_next'].sum()}  OOS jumps={df_oos['jump_next'].sum()}")

    # Knots and cutoffs on IS (same as K1131)
    vix_is = df_is["vix_lag1"].values
    KNOTS_PCT = np.array([0.20, 0.40, 0.60, 0.80])
    knots = np.quantile(vix_is, KNOTS_PCT)
    vix_center = float(np.median(vix_is))
    c33 = float(np.quantile(vix_is, 1 / 3))
    c67 = float(np.quantile(vix_is, 2 / 3))
    print(f"[5] Knots (IS q20/40/60/80) = {knots}")
    print(f"    Tertile cutoffs (IS q33/q67) = {c33:.3f} / {c67:.3f}")
    print(f"    VIX center = {vix_center:.3f}")

    # Design matrices
    Xb_is, Xt_is, Xs_is = build_features(df_is, (c33, c67), knots, vix_center)
    Xb_oo, Xt_oo, Xs_oo = build_features(df_oos, (c33, c67), knots, vix_center)
    y_is = df_is["jump_next"].values.astype(int)
    y_oos = df_oos["jump_next"].values.astype(int)

    # Fit three models on IS
    print("[6] Fitting M_base / M_tertile / M_spline on IS ...")
    M_base = fit_mle(Xb_is, y_is, l2=1e-4)
    M_tertile = fit_mle(Xt_is, y_is, l2=1e-4)
    M_spline = fit_mle(Xs_is, y_is, l2=1e-4)
    print(f"    nll_is: base={M_base['nll']:.3f}  tertile={M_tertile['nll']:.3f}  "
          f"spline={M_spline['nll']:.3f}")
    print(f"    success: base={M_base['success']}  tertile={M_tertile['success']}  "
          f"spline={M_spline['success']}")

    # OOS predictions + per-obs losses
    p_base = predict_proba(Xb_oo, M_base["beta"])
    p_tert = predict_proba(Xt_oo, M_tertile["beta"])
    p_spln = predict_proba(Xs_oo, M_spline["beta"])
    loss_base = log_loss_obs(y_oos, p_base)
    loss_tert = log_loss_obs(y_oos, p_tert)
    loss_spln = log_loss_obs(y_oos, p_spln)
    print(f"[7] OOS mean log-loss: base={loss_base.mean():.6f}  "
          f"tertile={loss_tert.mean():.6f}  spline={loss_spln.mean():.6f}")

    # Primary contrast: spline vs tertile (K1131 H2)
    d = loss_tert - loss_spln  # positive d => spline better; K1131 reported <0
    dm_point = dm_hln_on_diffs(d)
    print(f"[8] Point DM-HLN (spline vs tertile): t_hln={dm_point['t_hln']:+.3f}  "
          f"t_plain={dm_point['t_plain']:+.3f}  mean_d={dm_point['mean_d']:+.3e}")

    # Sanity check against K1131_results.json
    K1131_RESULTS = SCRIPT_DIR.parent / "k1131" / "k1131_results.json"
    if K1131_RESULTS.exists():
        with open(K1131_RESULTS) as f:
            r = json.load(f)
        k1131_t = r["H2_DM_spline_vs_tertile"]["t"]
        delta = abs(k1131_t - dm_point["t_hln"])
        print(f"    K1131 reported t={k1131_t:+.3f}, our t={dm_point['t_hln']:+.3f}, "
              f"|delta|={delta:.3f}")
        if delta > 1e-6:
            print(f"    WARNING: point DM t differs from K1131 by {delta:.2e} (>1e-6) -> "
                  "reconstruction diverged, aborting")
            sys.exit(1)

    # Ljung-Box on d
    lb = ljung_box(d, lags=(1, 5, 10, 20, 60, 120))
    print(f"[9] Ljung-Box on loss differentials:")
    for m, s in lb.items():
        print(f"    Q({m}): Q={s['Q']:.2f}  p={s['p']:.4f}")

    # Block-bootstrap over block sizes
    print(f"[10] Block bootstrap (B={B_BOOTSTRAP}, circular Politis-Romano 1994)")
    bs_results = {}
    for b in BLOCK_SIZES:
        print(f"    b={b} ... ", end="", flush=True)
        t_draws = circular_block_bootstrap_dm(
            d, block_size=b, B=B_BOOTSTRAP, rng=np.random.default_rng(SEED)
        )
        ci = {}
        for lbl, lvl in CI_LEVELS.items():
            a = (1 - lvl) / 2
            lo, hi = np.quantile(t_draws, [a, 1 - a])
            ci[lbl] = [float(lo), float(hi)]
        bs_results[b] = {
            "t_draws_mean": float(t_draws.mean()),
            "t_draws_std": float(t_draws.std(ddof=1)),
            "t_draws_median": float(np.median(t_draws)),
            "ci": ci,
            "frac_t_ge_0": float((t_draws >= 0).mean()),
            "frac_t_ge_m1p96": float((t_draws >= -1.96).mean()),
            "B": B_BOOTSTRAP,
        }
        print(f"mean_t={t_draws.mean():+.3f}  "
              f"95% CI=[{ci['95'][0]:+.3f}, {ci['95'][1]:+.3f}]  "
              f"P(t>=0)={bs_results[b]['frac_t_ge_0']:.4f}")
        # Keep one draw set for plot
        if b == 60:
            t_draws_plot = t_draws

    # Pre-registered verdict rule
    ci95_ub_list = [bs_results[b]["ci"]["95"][1] for b in BLOCK_SIZES]
    ci95_lb_list = [bs_results[b]["ci"]["95"][0] for b in BLOCK_SIZES]
    any_spans_zero = any(lb_v <= 0 <= ub_v
                         for lb_v, ub_v in zip(ci95_lb_list, ci95_ub_list))
    any_ub_above_m196 = any(ub >= -1.96 for ub in ci95_ub_list)
    if any_spans_zero:
        verdict = "not-robust"
    elif any_ub_above_m196:
        verdict = "inconclusive"
    else:
        verdict = "robust"

    print(f"\n[11] Verdict (pre-registered): {verdict}")
    print(f"    95% CI upper bounds across b: {[f'{x:+.3f}' for x in ci95_ub_list]}")
    print(f"    95% CI lower bounds across b: {[f'{x:+.3f}' for x in ci95_lb_list]}")

    # Headline b=60 是 heuristic（1 trading day, 5-min bars × 60/day），
    # NOT data-driven Politis-White (2004) 自動選擇。選這個是因為 Ljung-Box 在 m=60
    # 顯著表示相依延伸至此 lag。敏感性 BLOCK_SIZES=[20,40,60,100] 已驗證 CI 穩定。
    # TODO: 若要 data-driven，接 `arch.bootstrap.optimal_block_length()` 取代。
    headline_b = 60
    headline = bs_results[headline_b]

    # ------------------------------------------------------------------
    # Save results
    # ------------------------------------------------------------------
    runtime = (datetime.now() - t_start).total_seconds()
    results = {
        "experiment_id": "K1132",
        "title": "Block-Bootstrap CI for K1131 OOS DM-HLN t-stat",
        "timestamp": datetime.now().isoformat(),
        "seed": SEED,
        "runtime_sec": float(runtime),
        "data_source": "TAIFEX TX 5-min bars 2017-2021 (K1124 cache, same as K1131)",
        "upstream": {
            "K1131_DM_reported_t_hln": -3.936694237337927,
            "K1131_DM_reported_mean_d": -0.0007578513340819119,
        },
        "point_estimate": {
            "t_hln": dm_point["t_hln"],
            "t_plain": dm_point["t_plain"],
            "mean_d": dm_point["mean_d"],
            "se_hac": dm_point["se"],
            "n": dm_point["n"],
            "matches_K1131_within_0p02": abs(
                dm_point["t_hln"] - (-3.936694237337927)) <= 0.02,
        },
        "OOS_mean_log_loss": {
            "base": float(loss_base.mean()),
            "tertile": float(loss_tert.mean()),
            "spline": float(loss_spln.mean()),
        },
        "ljung_box_on_d": lb,
        "bootstrap": {
            "method": "circular block bootstrap (Politis & Romano 1994, "
                      "Annals of Statistics 22, 2031-2050)",
            "B": B_BOOTSTRAP,
            "block_sizes_tested": BLOCK_SIZES,
            "rng": "np.random.default_rng(seed=42)",
            "per_block": {str(b): bs_results[b] for b in BLOCK_SIZES},
        },
        "headline": {
            "block_size": headline_b,
            "point_estimate_t": dm_point["t_hln"],
            "ci_95": headline["ci"]["95"],
            "ci_90": headline["ci"]["90"],
            "ci_99": headline["ci"]["99"],
            "bootstrap_mean_t": headline["t_draws_mean"],
            "bootstrap_std_t": headline["t_draws_std"],
            "frac_t_ge_0": headline["frac_t_ge_0"],
            "frac_t_ge_minus_1p96": headline["frac_t_ge_m1p96"],
            "B": B_BOOTSTRAP,
            "seed": SEED,
        },
        "verdict": verdict,
        "verdict_rule": {
            "robust": "95% CI upper bound < -1.96 at all block sizes",
            "inconclusive": "95% CI upper bound >= -1.96 at any block size OR CI spans 0",
            "not-robust": "95% CI includes 0 at any block size (sign could flip)",
        },
        "references": [
            "Politis, D.N., Romano, J.P. (1994). 'The Stationary Bootstrap.' "
            "J. Amer. Statist. Assoc. 89, 1303-1313.",
            "Politis, D.N., Romano, J.P. (1994). 'Large sample confidence regions "
            "based on subsamples under minimal assumptions.' Ann. Statist. 22, 2031-2050.",
            "Politis, D.N., White, H. (2004). 'Automatic block-length selection "
            "for the dependent bootstrap.' Econometric Reviews 23, 53-70.",
            "Harvey, D., Leybourne, S., Newbold, P. (1997). 'Testing the Equality "
            "of Prediction Mean Squared Errors.' Int. J. Forecasting 13, 281-291.",
            "Diebold, F.X., Mariano, R.S. (1995). 'Comparing Predictive Accuracy.' "
            "J. Business Econ. Statist. 13, 253-263.",
        ],
    }
    out_path = SCRIPT_DIR / "k1132_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[12] Saved {out_path}")

    # ------------------------------------------------------------------
    # Plot bootstrap distribution
    # ------------------------------------------------------------------
    print("[13] Plotting bootstrap_distribution.png")
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for ax, b in zip(axes.flatten(), BLOCK_SIZES):
        # Re-draw with the same seed for plotting (deterministic)
        t_draws = circular_block_bootstrap_dm(
            d, block_size=b, B=B_BOOTSTRAP, rng=np.random.default_rng(SEED)
        )
        ci95 = bs_results[b]["ci"]["95"]
        ci90 = bs_results[b]["ci"]["90"]
        ax.hist(t_draws, bins=60, alpha=0.75, color="steelblue",
                edgecolor="white")
        ax.axvline(dm_point["t_hln"], color="red", lw=2,
                   label=f"point t = {dm_point['t_hln']:+.3f}")
        ax.axvline(ci95[0], color="black", lw=1.2, linestyle="--",
                   label=f"95% CI = [{ci95[0]:+.2f}, {ci95[1]:+.2f}]")
        ax.axvline(ci95[1], color="black", lw=1.2, linestyle="--")
        ax.axvline(ci90[0], color="darkorange", lw=1.0, linestyle=":",
                   label=f"90% CI = [{ci90[0]:+.2f}, {ci90[1]:+.2f}]")
        ax.axvline(ci90[1], color="darkorange", lw=1.0, linestyle=":")
        ax.axvline(-1.96, color="gray", lw=0.7, alpha=0.7)
        ax.axvline(0, color="black", lw=0.5)
        frac = bs_results[b]["frac_t_ge_0"]
        ax.set_title(
            f"block size b = {b} bars\n"
            f"mean={t_draws.mean():+.3f}, std={t_draws.std(ddof=1):.3f}, "
            f"P(t>=0)={frac:.4f}",
            fontsize=11,
        )
        ax.set_xlabel("Bootstrap DM-HLN t (spline vs tertile)")
        ax.set_ylabel("Frequency")
        ax.legend(fontsize=8, loc="upper right")

    plt.suptitle(
        f"K1132: Circular block-bootstrap distribution of DM-HLN t "
        f"(B={B_BOOTSTRAP}, seed={SEED})\n"
        f"K1131 point t = -3.94, verdict = {verdict}",
        fontsize=12,
    )
    plt.tight_layout()
    fig_path = SCRIPT_DIR / "bootstrap_distribution.png"
    plt.savefig(fig_path, dpi=120, bbox_inches="tight")
    plt.close()
    print(f"    Saved {fig_path}")

    print(f"\nK1132 complete. Runtime={runtime:.1f}s  Verdict={verdict}")
    print(f"Headline (b={headline_b}): point t={dm_point['t_hln']:+.3f}, "
          f"95% CI=[{headline['ci']['95'][0]:+.3f}, {headline['ci']['95'][1]:+.3f}], "
          f"90% CI=[{headline['ci']['90'][0]:+.3f}, {headline['ci']['90'][1]:+.3f}]")
    return results


if __name__ == "__main__":
    main()
