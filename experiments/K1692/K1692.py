#!/usr/bin/env python
"""
K1692 — Oil volatility → equity/energy-sector volatility spillover
        (vol-of-vol transmission), with oil-RETURN-controlled identification
        and a correct generalized-FEVD (Pesaran-Shin) Diebold-Yilmaz index.
==================================================================================

Research question
-----------------
Does a shock to CRUDE-OIL volatility (CL=F WTI future, USO ETF) transmit to the
volatility of broad equity (SPY) and energy-sector equity (XLE, XOP) — i.e. a
volatility-to-volatility ("vol-of-vol") channel, distinct from the well-known
oil-PRICE → equity-RETURN channel — and does any transmission survive:
  (a) proper autocorrelation-robust (Newey-West HAC-Wald) Granger inference,
  (b) an explicit control for oil's OWN RETURN (so a return effect is not
      mis-read as a volatility effect — the brief's core identification), and
  (c) a correct order-invariant Diebold-Yilmaz connectedness measure?

*** THIS IS NOT A FRESH DISCOVERY (honesty / dedup — see README §Prior work). ***
The oil→equity vol-spillover question is heavily covered in THIS lab and has
CONVERGED to a NULL / directional-NULL after correct inference:
  K1665 : CL=F/USO → SPY/XLE realized-vol + vol-of-vol, proper HAC-Wald Granger,
          VIX-controlled, OOS DM-HLN. Verdict NULL (1st-order fully collapses
          under HAC; 2nd-order vov only CL=F survives HAC but dies under VIX).
  K1444 : CL=F/USO/SPY/XLE vol-of-vol; DY spillover 48.8%; futures net RECEIVER.
          (Codex flagged its "HAC" Granger was actually a plain ssr F-test.)
  K1351 : CL=F/USO → SPY/XLE/XOP; NULL_NO_HARVEY_PASS.
  K1329 : CL/USO → SPY/XLE/XOP; 14 in-sample Granger pairs but NO OOS edge.
  K1647 : oil RV → equity RV, VIX-controlled; directional NULL.
  K1025 : Diebold-Yilmaz connectedness — *** statsmodels .fevd() is CHOLESKY
          (order-dependent), NOT the Pesaran-Shin GFEVD its comment claimed;
          net/direction magnitudes had to be retracted. K1692 hand-rolls KPPS. ***

K1692's incremental value is therefore METHODOLOGICAL / robustness, honestly
pre-registered as most likely REPLICATION-STRENGTHENING, filling three specific
gaps the prior line left open (see README §Differentiation):
  (1) The brief's core identification NOT done before: does oil VOLATILITY add
      beyond oil's own RETURN (signed + squared lagged returns as controls)?
      — separates the "波動效果" from the "報酬效果".
  (2) XOP (oil & gas exploration) added as a 3rd target alongside SPY/XLE, with
      proper HAC-Wald (K1665 lacked XOP; K1329/K1351 used XOP but in-sample only).
  (3) A CORRECT generalized-FEVD (Pesaran & Shin 1998) Diebold-Yilmaz index on
      the full {CL=F,USO,SPY,XLE,XOP} vol system, hand-rolled from sigma_u +
      ma_rep (order-invariant), with a moving-block bootstrap CI — explicitly
      avoiding the K1025 Cholesky-ordering artifact.

Anti-lookahead / rigor
----------------------
- Vol proxy = EWMA(lambda=0.94) daily conditional vol (RiskMetrics):
  sigma^2_t = lambda*sigma^2_{t-1} + (1-lambda)*r^2_{t-1}. It uses only r_{t-1},
  so sigma_t is known at the close of t-1 -> strictly backward, no lookahead.
  Chosen over a 21-day rolling window on purpose: no hard-window overlap
  artifact, so it is appropriate for BOTH the Granger regressions AND the VAR/DY
  connectedness (a rolling window's mechanical overlap inflates VAR persistence
  and connectedness). A 21d-rolling-RV cross-check on the headline pairs
  confirms consistency with K1665.
- Every predictor enters LAGGED (regressions: E_t on {E_{t-i}, O_{t-i}, ...}).
- HAC lag is chosen AFTER measuring the residual autocorrelation (not a blind
  h-1); sensitivity reported (rule: .claude/rules/experiments.md §DM-HAC).
- SPY / XLE / XOP are SEPARATE regressions (no asset-day pooling / iid abuse).
- CL=F 2020-04-20 negative-price prints masked (log-return undefined for P<=0).
- Generalized FEVD is hand-rolled (sigma_u + ma_rep); statsmodels Cholesky
  .fevd() is NEVER called (K1025 lesson; audit_fevd_ordering -> OK_GFEVD).
- OOS incremental forecast is a NESTED comparison (own-lag baseline nested in
  own+source augmented), so it uses the canonical Clark-West (2007) test
  (volpred.stats.model_evaluation.clark_west_test), NOT a raw DM/HLN loss
  differential (invalid under the nested null; nested-dm ratchet).
- All randomness seeded (SEED=42): bootstrap CIs are reproducible.

Author: VolPred autonomous research agent. Run in isolated git worktree.
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SEED = 42
RNG = np.random.default_rng(SEED)
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(HERE, "K1692_results.json")
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "src"))

TICKERS = ["CL=F", "USO", "SPY", "XLE", "XOP", "^VIX"]
OIL = ["CL=F", "USO"]
EQUITY = ["SPY", "XLE", "XOP"]
SYSTEM = ["CL=F", "USO", "SPY", "XLE", "XOP"]  # DY connectedness system
START = "2006-01-01"          # longest common sample (XOP inception 2006-06)
EWMA_LAMBDA = 0.94            # RiskMetrics daily decay
EWMA_BURN = 63               # burn-in dropped so the 1-point causal seed decays
VOV_WINDOW = 21              # rolling std of vol -> vol-of-vol
LAGS = 5                     # one trading week of lags
ANNUALIZE = np.sqrt(252.0)
H_FEVD = 10                  # DY forecast horizon
VAR_MAXLAGS = 5
BOOT_B = 300                 # block-bootstrap replications
BLOCK_LEN = 21               # moving-block length
OOS_YEARS = 3


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def download_prices() -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        TICKERS, start=START, auto_adjust=True, progress=False, threads=True
    )
    close = raw["Close"].copy() if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].copy()
    close = close[[t for t in TICKERS if t in close.columns]].sort_index()
    return close


def log_returns(close: pd.DataFrame) -> pd.DataFrame:
    safe = close.where(close > 0)             # CL=F went negative 2020-04-20
    lr = np.log(safe).diff().replace([np.inf, -np.inf], np.nan)
    return lr


def ewma_vol(lr: pd.DataFrame, lam: float = EWMA_LAMBDA,
             burn: int = EWMA_BURN) -> pd.DataFrame:
    """RiskMetrics EWMA conditional vol, annualized. STRICTLY causal.

    sigma^2_t = lam*sigma^2_{t-1} + (1-lam)*r^2_{t-1}, so sigma_t uses only
    r_{t-1} (known at the close of t-1) -> no lookahead.

    Seed is the FIRST available r^2 alone (a single past point), NOT a forward
    window average -- a window seed would inject up to VOV_WINDOW-1 future
    squared returns into the early sigma_t (the K1692 Codex-review lookahead
    defect). The first `burn` emitted values are then dropped so the noisy
    one-point seed has decayed (half-life ~11d at lam=0.94).
    """
    out = {}
    for col in lr.columns:
        vals = (lr[col] ** 2).values
        sig2 = np.full(len(vals), np.nan)
        valid = np.where(~np.isnan(vals))[0]
        if len(valid) == 0:
            out[col] = pd.Series(sig2, index=lr.index)
            continue
        first = int(valid[0])
        prev = float(vals[first])              # causal seed: first past r^2 only
        for t in range(first + 1, len(vals)):
            rt2 = vals[t - 1]                  # uses r_{t-1} only -> no lookahead
            if np.isnan(rt2):
                sig2[t] = prev
                continue
            prev = lam * prev + (1.0 - lam) * rt2
            sig2[t] = prev
        emitted = np.where(~np.isnan(sig2))[0]  # discard burn-in (seed decay)
        sig2[emitted[:burn]] = np.nan
        out[col] = pd.Series(np.sqrt(sig2) * ANNUALIZE, index=lr.index)
    return pd.DataFrame(out)


def rolling_rv(lr: pd.DataFrame, window: int = VOV_WINDOW) -> pd.DataFrame:
    """21d rolling realized vol (K1665 convention) — cross-check only."""
    return lr.rolling(window, min_periods=window).std() * ANNUALIZE


def vol_of_vol(vol: pd.DataFrame, window: int = VOV_WINDOW) -> pd.DataFrame:
    return vol.rolling(window, min_periods=window).std()


# --------------------------------------------------------------------------- #
# HAC-Wald Granger
# --------------------------------------------------------------------------- #
def _lag_matrix(s: pd.Series, p: int, prefix: str) -> pd.DataFrame:
    return pd.concat({f"{prefix}_l{i}": s.shift(i) for i in range(1, p + 1)}, axis=1)


def _residual_acf(resid, nlags: int = 30) -> list[float]:
    # np.asarray is load-bearing: statsmodels returns resid as a *pandas Series*
    # when exog is a DataFrame, and pandas re-aligns r[k:] * r[:-k] by index
    # (undoing the lag) -> every acf would come out ~1.0. Force positional numpy.
    r = np.asarray(resid, dtype=float)
    r = r - r.mean()
    denom = float(np.sum(r * r))
    if denom == 0:
        return [0.0] * (nlags + 1)
    n = len(r)
    return [float(np.sum(r[k:] * r[: n - k]) / denom) for k in range(nlags + 1)]


def _hac_bandwidth(resid: np.ndarray) -> int:
    """Data-driven HAC lag: measure residual acf, take the largest lag (up to 42)
    whose |acf| still exceeds the ~2/sqrt(n) white-noise band, floored so an
    overlapping-vol MA structure is always covered. NOT a blind h-1."""
    n = len(resid)
    acf = _residual_acf(resid, nlags=42)
    band = 2.0 / np.sqrt(n)
    sig_lags = [k for k in range(1, len(acf)) if abs(acf[k]) > band]
    data_driven = max(sig_lags) if sig_lags else 1
    canonical = int(np.ceil(n ** (1.0 / 3.0)))     # repo canonical floor
    return int(min(42, max(canonical, min(data_driven, 42))))


def hac_wald_granger(target: pd.Series, source: pd.Series, p: int,
                     extra: dict[str, pd.Series] | None = None,
                     nw_override: int | None = None) -> dict:
    """Regress target_t on const + p own lags + p source lags (+ optional extra
    lagged controls), Newey-West HAC cov, Wald-test H0: all source-lag coefs = 0.
    """
    import statsmodels.api as sm

    blocks = [target.rename("y"), _lag_matrix(target, p, "own"), _lag_matrix(source, p, "src")]
    if extra:
        for name, s in extra.items():
            blocks.append(_lag_matrix(s, p, name))
    df = pd.concat(blocks, axis=1).dropna()
    if len(df) < 100:
        return {"error": "insufficient_obs", "nobs": int(len(df))}

    y = df["y"].values
    Xc = sm.add_constant(df.drop(columns="y"))
    ols = sm.OLS(y, Xc).fit()                                   # for residual acf
    nw = nw_override or _hac_bandwidth(ols.resid)
    model = sm.OLS(y, Xc).fit(cov_type="HAC", cov_kwds={"maxlags": nw})

    src_cols = [c for c in Xc.columns if c.startswith("src_")]
    idx = [list(Xc.columns).index(c) for c in src_cols]
    R = np.zeros((len(idx), Xc.shape[1]))
    for r, j in enumerate(idx):
        R[r, j] = 1.0
    wald = model.wald_test(R, scalar=False)
    # HAC lag sensitivity: refit at 2x bandwidth and report the Wald p there too.
    nw2 = int(min(2 * nw, len(df) // 4))
    model2 = sm.OLS(y, Xc).fit(cov_type="HAC", cov_kwds={"maxlags": nw2})
    wald2 = model2.wald_test(R, scalar=False)
    return {
        "nobs": int(len(df)),
        "p_lags": p,
        "nw_maxlags": int(nw),
        "resid_acf1": float(_residual_acf(ols.resid, 1)[1]),
        "wald_stat": float(np.ravel(wald.statistic)[0]),   # robust Wald (chi2/F)
        "wald_p": float(np.ravel(wald.pvalue)[0]),
        "wald_p_2x_lag": float(np.ravel(wald2.pvalue)[0]),  # lag sensitivity
        "nw_maxlags_2x": nw2,
        "src_max_abs_t": float(max(abs(model.tvalues[c]) for c in src_cols)),
        "src_sum_beta": float(sum(model.params[c] for c in src_cols)),
        "src_t": {c: float(model.tvalues[c]) for c in src_cols},
    }


def naive_ssr_granger(target: pd.Series, source: pd.Series, p: int) -> float:
    """Plain statsmodels ssr F Granger p (the NON-HAC comparison that over-rejects
    on overlapping vol; reproduces the K1444-style 'strong significance')."""
    from statsmodels.tsa.stattools import grangercausalitytests

    df = pd.concat([target.rename("y"), source.rename("x")], axis=1).dropna()
    res = grangercausalitytests(df[["y", "x"]], maxlag=[p], verbose=False)
    return float(res[p][0]["ssr_ftest"][1])


# --------------------------------------------------------------------------- #
# Diebold-Yilmaz with hand-rolled generalized FEVD (Pesaran & Shin 1998)
# --------------------------------------------------------------------------- #
def generalized_fevd_from_var(sigma_u: np.ndarray, ma: np.ndarray, H: int) -> np.ndarray:
    """KPPS / Pesaran-Shin generalized FEVD, order-invariant.

    sigma_u : (k,k) VAR residual covariance (statsmodels VARResults.sigma_u)
    ma      : (H+1,k,k) MA coefficients A_h with A_0 = I (VARResults.ma_rep)
    Returns row-normalised theta_tilde (k,k), each row summing to 1.

    Explicitly hand-rolled from sigma_u + ma_rep; statsmodels' Cholesky .fevd()
    is never used (K1025 ordering-artifact lesson).
    """
    k = sigma_u.shape[0]
    sig_diag = np.diag(sigma_u)
    num = np.zeros((k, k))
    den = np.zeros(k)
    for h in range(H):
        Ah = ma[h]                       # (k,k)
        M = Ah @ sigma_u                 # e_i' A_h Sigma e_j = M[i,j]
        num += M ** 2                    # accumulate squared generalized IRFs
        den += np.diag(Ah @ sigma_u @ Ah.T)
    theta = (num / sig_diag[None, :]) / den[:, None]     # theta[i,j]
    theta_tilde = theta / theta.sum(axis=1, keepdims=True)
    return theta_tilde


def dy_connectedness(vol_df: pd.DataFrame, order: list[str], H: int = H_FEVD,
                     maxlags: int = VAR_MAXLAGS) -> dict:
    from statsmodels.tsa.api import VAR

    data = vol_df[order].dropna()
    res = VAR(data).fit(maxlags=maxlags, ic="aic")
    p = int(res.k_ar) if res.k_ar > 0 else 1
    if res.k_ar == 0:
        res = VAR(data).fit(1)
        p = 1
    ma = res.ma_rep(maxn=H)
    theta = generalized_fevd_from_var(np.asarray(res.sigma_u), ma, H)
    k = len(order)
    off = theta.copy()
    np.fill_diagonal(off, 0.0)
    total = 100.0 * off.sum() / k
    from_others = off.sum(axis=1)          # variance of i explained by others
    to_others = off.sum(axis=0)            # i's contribution to others
    net = to_others - from_others
    return {
        "order": order,
        "var_lag_p": p,
        "nobs": int(len(data)),
        "total_connectedness_pct": float(total),
        "from_others": {order[i]: float(from_others[i]) for i in range(k)},
        "to_others": {order[i]: float(to_others[i]) for i in range(k)},
        "net": {order[i]: float(net[i]) for i in range(k)},
        "theta_tilde": theta.tolist(),
        "oil_to_equity_net": float(
            sum(theta[EQUITY.index(e) + len(OIL), order.index(o)]
                for e in EQUITY for o in OIL)
            - sum(theta[order.index(o), EQUITY.index(e) + len(OIL)]
                  for e in EQUITY for o in OIL)
        ) if order == SYSTEM else None,
    }


def _moving_block_bootstrap_index(n: int, block: int, rng) -> np.ndarray:
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n - block + 1, size=n_blocks)
    idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
    return idx


def dy_bootstrap_ci(vol_df: pd.DataFrame, order: list[str], B: int = BOOT_B,
                    H: int = H_FEVD) -> dict:
    """Moving-block bootstrap CI for the total connectedness index (seed-fixed).
    Block bootstrap chosen because the vol series are strongly autocorrelated."""
    from statsmodels.tsa.api import VAR

    data = vol_df[order].dropna()
    res = VAR(data).fit(maxlags=VAR_MAXLAGS, ic="aic")
    p = max(int(res.k_ar), 1)
    resid = res.resid.values
    fitted = data.values[p:] - resid
    from volpred.ops.diagnostics import warn

    totals = []
    n_fail = 0
    for _ in range(B):
        bidx = _moving_block_bootstrap_index(len(resid), BLOCK_LEN, RNG)
        y_star = fitted + resid[bidx]
        try:
            r2 = VAR(pd.DataFrame(y_star, columns=order)).fit(p)
            ma = r2.ma_rep(maxn=H)
            th = generalized_fevd_from_var(np.asarray(r2.sigma_u), ma, H)
            off = th.copy()
            np.fill_diagonal(off, 0.0)
            totals.append(100.0 * off.sum() / len(order))
        except Exception:  # silent-ok: non-stationary resampled VAR fails to fit; skips are counted (n_fail) and surfaced via post-loop warn + n_boot, so observable.
            n_fail += 1
            continue
    if n_fail:
        warn(f"K1692 DY bootstrap: {n_fail}/{B} resamples skipped (VAR fit failed); "
             f"CI computed from {len(totals)} successful resamples")
    totals = np.array(totals)
    return {
        "n_boot": int(len(totals)),
        "n_fail": int(n_fail),
        "total_mean": float(np.mean(totals)),
        "total_ci95": [float(np.percentile(totals, 2.5)), float(np.percentile(totals, 97.5))],
    }


# --------------------------------------------------------------------------- #
# OOS incremental forecast (canonical DM)
# --------------------------------------------------------------------------- #
def oos_incremental_cw(target: pd.Series, source: pd.Series, p: int,
                       oos_start: pd.Timestamp) -> dict:
    """Expanding-window one-step OOS: own-lag baseline vs own+source-lag augmented.

    nested-dm: cw-primary. The baseline (own lags) is NESTED in the augmented
    model (own + source lags), so a raw Diebold-Mariano / HLN loss-differential
    is INVALID under the null (the loss differential degenerates -- Clark & West
    2007). The canonical Clark-West MSPE-adjusted test governs the verdict; a
    positive CW statistic means the larger (augmented) model carries incremental
    predictive content. Raw DM is deliberately NOT used for this nested check.
    """
    from volpred.stats.model_evaluation import clark_west_test

    own = _lag_matrix(target, p, "own")
    src = _lag_matrix(source, p, "src")
    df = pd.concat([target.rename("y"), own, src], axis=1).dropna()
    start_pos = int(np.searchsorted(df.index, oos_start))
    start_pos = max(start_pos, 150)
    if start_pos >= len(df) - 30:
        return {"error": "oos_too_short"}

    own_cols = [c for c in df.columns if c.startswith("own_")]
    aug_cols = own_cols + [c for c in df.columns if c.startswith("src_")]
    y = df["y"].values
    Xb = np.column_stack([np.ones(len(df)), df[own_cols].values])
    Xa = np.column_stack([np.ones(len(df)), df[aug_cols].values])

    y_act, f_small, f_large = [], [], []
    for t in range(start_pos, len(df)):
        beta_b = np.linalg.lstsq(Xb[:t], y[:t], rcond=None)[0]   # train on [:t]
        beta_a = np.linalg.lstsq(Xa[:t], y[:t], rcond=None)[0]
        y_act.append(y[t])
        f_small.append(Xb[t] @ beta_b)                          # nested (small)
        f_large.append(Xa[t] @ beta_a)                          # augmented (large)
    y_act = np.array(y_act); f_small = np.array(f_small); f_large = np.array(f_large)

    cw = clark_west_test(y_act, f_small, f_large, h=1)          # canonical HAC lag
    mse_s = float(np.mean((y_act - f_small) ** 2))
    mse_l = float(np.mean((y_act - f_large) ** 2))
    return {
        "n_oos": int(len(y_act)),
        "mse_improvement_pct": float((mse_s - mse_l) / mse_s * 100.0),
        "cw_t": float(cw["t_stat"]),                # positive -> augmented better
        "cw_p_one_sided": float(cw["p_value_one_sided"]),
        "cw_hac_lag": int(cw.get("hac_lag", 0)),
        "augmented_better_sig": bool(cw["t_stat"] > 3.0),  # Harvey-strict, one-sided
    }


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def make_figures(vol: pd.DataFrame, dy: dict) -> list[str]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    paths = []
    # fig1: vol overlay, log scale, event markers
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for col in SYSTEM:
        ax.plot(vol.index, vol[col], lw=0.8, label=col)
    ax.set_yscale("log")
    for d, txt in [("2020-04-20", "2020 oil crash"), ("2022-03-01", "2022 energy")]:
        ax.axvline(pd.Timestamp(d), color="grey", ls="--", lw=0.7)
        ax.text(pd.Timestamp(d), ax.get_ylim()[1] * 0.7, txt, fontsize=7, rotation=90, va="top")
    ax.set_title("K1692 — EWMA(0.94) annualized volatility, oil vs equity (log scale)")
    ax.set_ylabel("annualized vol")
    ax.legend(ncol=5, fontsize=8)
    fig.tight_layout()
    p1 = os.path.join(HERE, "K1692_fig1_vol_overlay.png")
    fig.savefig(p1, dpi=130)
    plt.close(fig)
    paths.append(p1)

    # fig2: DY net directional spillover bar
    fig, ax = plt.subplots(figsize=(8, 4.5))
    order = dy["order"]
    net = [dy["net"][o] for o in order]
    colors = ["#c0392b" if v > 0 else "#2980b9" for v in net]
    ax.bar(order, net, color=colors)
    ax.axhline(0, color="k", lw=0.8)
    ax.set_title(f"K1692 — DY generalized-FEVD NET connectedness "
                 f"(total={dy['total_connectedness_pct']:.1f}%)  +transmitter / -receiver")
    ax.set_ylabel("net (to − from others)")
    fig.tight_layout()
    p2 = os.path.join(HERE, "K1692_fig2_dy_net_spillover.png")
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    paths.append(p2)

    # fig3: GFEVD connectedness heatmap
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    theta = np.array(dy["theta_tilde"]) * 100.0
    im = ax.imshow(theta, cmap="magma", aspect="auto")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels(order, rotation=45, ha="right")
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels(order)
    for i in range(len(order)):
        for j in range(len(order)):
            ax.text(j, i, f"{theta[i, j]:.0f}", ha="center", va="center",
                    color="white" if theta[i, j] < theta.max() * 0.6 else "black", fontsize=8)
    ax.set_title("K1692 — GFEVD variance shares (%)  row i FROM column j")
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    p3 = os.path.join(HERE, "K1692_fig3_gfevd_heatmap.png")
    fig.savefig(p3, dpi=130)
    plt.close(fig)
    paths.append(p3)
    return paths


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    close = download_prices()
    lr = log_returns(close)
    vol = ewma_vol(lr).dropna(how="all")
    rv21 = rolling_rv(lr)
    vov = vol_of_vol(vol)

    common = vol[SYSTEM].dropna()
    sample = {
        "tickers": TICKERS,
        "start": str(common.index.min().date()),
        "end": str(common.index.max().date()),
        "n_common": int(len(common)),
        "vol_proxy": "EWMA(lambda=0.94) annualized conditional vol (RiskMetrics)",
        "oos_start": str((common.index.max() - pd.DateOffset(years=OOS_YEARS)).date()),
    }
    oos_start = common.index.max() - pd.DateOffset(years=OOS_YEARS)

    # 1) Observation: descriptive stats + correlation + ADF stationarity
    from statsmodels.tsa.stattools import adfuller
    desc = {c: {"mean": float(vol[c].mean()), "std": float(vol[c].std()),
                "skew": float(vol[c].skew()), "max": float(vol[c].max())} for c in SYSTEM}
    corr = vol[SYSTEM].dropna().corr().round(4).to_dict()
    stationarity = {}
    for c in SYSTEM:
        s = vol[c].dropna()
        adf_stat, adf_p = adfuller(s, maxlag=21, autolag=None)[:2]
        stationarity[c] = {"adf_stat": float(adf_stat), "adf_p": float(adf_p),
                           "acf1": float(s.autocorr(1))}

    # 2) HAC-Wald Granger (oil -> equity) on EWMA vol, + naive ssr comparison,
    #    + 21d-rolling-RV cross-check (consistency with K1665)
    granger = {}
    for o in OIL:
        for e in EQUITY:
            key = f"{o}->{e}"
            granger[key] = {
                "hac_wald": hac_wald_granger(vol[e], vol[o], LAGS),
                "naive_ssr_p": naive_ssr_granger(vol[e], vol[o], LAGS),
                "rv21_hac_wald": hac_wald_granger(rv21[e], rv21[o], LAGS),
                "reverse_hac_wald": hac_wald_granger(vol[o], vol[e], LAGS),
            }

    # 2b) vol-of-vol object (K1444 second-order)
    granger_vov = {}
    for o in OIL:
        for e in EQUITY:
            granger_vov[f"{o}->{e}"] = {
                "hac_wald": hac_wald_granger(vov[e], vov[o], LAGS),
                "naive_ssr_p": naive_ssr_granger(vov[e], vov[o], LAGS),
            }

    # 3) *** DIFFERENTIATOR: oil-RETURN-controlled identification ***
    #    Does oil VOL add beyond oil's own signed + squared lagged RETURN?
    oil_ret = lr[OIL]
    oil_ret2 = oil_ret ** 2
    controlled = {}
    controlled_vov = {}
    for o in OIL:
        for e in EQUITY:
            key = f"{o}->{e}"
            controlled[key] = {
                "vol_incr_over_oilret": hac_wald_granger(
                    vol[e], vol[o], LAGS,
                    extra={"oret": oil_ret[o], "oret2": oil_ret2[o]}),
                # continuity with K1665: also control VIX level
                "vol_incr_over_vix": hac_wald_granger(
                    vol[e], vol[o], LAGS, extra={"vix": close["^VIX"]}),
            }
            # Same controls on the 2nd-order vol-of-vol object (K1444 object):
            # the in-sample vov Granger can be Bonferroni-significant, so it must
            # face the identical oil-return / VIX controls before any NULL claim.
            controlled_vov[key] = {
                "vov_incr_over_oilret": hac_wald_granger(
                    vov[e], vov[o], LAGS,
                    extra={"oret": oil_ret[o], "oret2": oil_ret2[o]}),
                "vov_incr_over_vix": hac_wald_granger(
                    vov[e], vov[o], LAGS, extra={"vix": close["^VIX"]}),
            }

    # 4) Diebold-Yilmaz generalized-FEVD connectedness + bootstrap CI
    dy_vol = dy_connectedness(vol, SYSTEM)
    dy_ci = dy_bootstrap_ci(vol, SYSTEM)
    dy_vov = dy_connectedness(vov.dropna(), SYSTEM)

    # 5) OOS incremental forecast — Clark-West (nested; raw DM invalid here)
    oos = {}
    for o in OIL:
        for e in EQUITY:
            oos[f"{o}->{e}"] = oos_incremental_cw(vol[e], vol[o], LAGS, oos_start)

    # ---- verdict logic (honest, pre-registered NULL prior) ----------------- #
    n_pairs = len(OIL) * len(EQUITY)
    bonf = 0.05 / n_pairs

    def _wald_pass(d: dict) -> int:
        return 1 if d.get("wald_p", 1.0) < bonf else 0

    # PRIMARY significance = joint Wald block test (H0: all source lags = 0),
    # Bonferroni-corrected across the 6 pairs. The per-lag max|t| is DESCRIPTIVE
    # ONLY: taking a max over 5 collinear lag coefficients is a within-block
    # multiple comparison and is NOT a valid Harvey single-statistic test — that
    # is exactly why the joint Wald is the primary criterion (matches K1665).
    pairs = list(granger.keys())
    # first-order realized-vol tallies
    hac_wald_pass = sum(_wald_pass(granger[k]["hac_wald"]) for k in pairs)
    ctrl_oilret_wald = sum(_wald_pass(controlled[k]["vol_incr_over_oilret"]) for k in pairs)
    ctrl_vix_wald = sum(_wald_pass(controlled[k]["vol_incr_over_vix"]) for k in pairs)
    oos_edge = sum(1 for v in oos.values() if v.get("augmented_better_sig"))
    # second-order vol-of-vol tallies (Codex-flagged: must be accounted for)
    vov_wald_pass = sum(_wald_pass(granger_vov[k]["hac_wald"]) for k in pairs)
    vov_ctrl_oilret_wald = sum(_wald_pass(controlled_vov[k]["vov_incr_over_oilret"]) for k in pairs)
    vov_ctrl_vix_wald = sum(_wald_pass(controlled_vov[k]["vov_incr_over_vix"]) for k in pairs)

    # secondary descriptive tallies (max|t| > 3 among the 5 lags)
    hac_maxt3 = sum(1 for v in granger.values()
                    if v["hac_wald"].get("src_max_abs_t", 0) > 3.0)
    ctrl_oilret_maxt3 = sum(1 for v in controlled.values()
                            if v["vol_incr_over_oilret"].get("src_max_abs_t", 0) > 3.0)

    # A positive transmission claim requires the SAME pair to be jointly
    # Wald-significant AFTER controlling for oil's own return AND still under a
    # VIX control. First order additionally requires OOS forecast value; the
    # second-order (vov) survives on the in-sample incremental test alone (no
    # separate vov OOS is run). Anything short is the prior line's directional-NULL.
    robust_vol_pairs = [
        k for k in pairs
        if _wald_pass(controlled[k]["vol_incr_over_oilret"])
        and _wald_pass(controlled[k]["vol_incr_over_vix"])
        and oos[k].get("augmented_better_sig", False)
    ]
    robust_vov_pairs = [
        k for k in pairs
        if _wald_pass(controlled_vov[k]["vov_incr_over_oilret"])
        and _wald_pass(controlled_vov[k]["vov_incr_over_vix"])
    ]
    verdict = "PARTIAL_SIGNAL" if (robust_vol_pairs or robust_vov_pairs) else "NULL"

    results = {
        "experiment_id": "K1692",
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "sample": sample,
        "descriptive_stats": desc,
        "vol_correlation": corr,
        "stationarity_adf": stationarity,
        "granger_rv": granger,
        "granger_vov": granger_vov,
        "controlled_identification": controlled,
        "controlled_identification_vov": controlled_vov,
        "diebold_yilmaz_vol": dy_vol,
        "diebold_yilmaz_vol_bootstrap": dy_ci,
        "diebold_yilmaz_vov": dy_vov,
        "oos_incremental": oos,
        "significance": {
            "n_pairs": n_pairs,
            "bonferroni_alpha": bonf,
            "harvey_t_threshold": 3.0,
            "primary_criterion": "joint Wald block test (H0: all source lags=0), Bonferroni",
            "first_order_vol": {
                "wald_bonf_pass_uncontrolled": hac_wald_pass,
                "wald_bonf_pass_after_oilret_control": ctrl_oilret_wald,
                "wald_bonf_pass_after_vix_control": ctrl_vix_wald,
                "oos_directional_edges": oos_edge,
                "robust_positive_pairs": robust_vol_pairs,
            },
            "second_order_vov": {
                "wald_bonf_pass_uncontrolled": vov_wald_pass,
                "wald_bonf_pass_after_oilret_control": vov_ctrl_oilret_wald,
                "wald_bonf_pass_after_vix_control": vov_ctrl_vix_wald,
                "robust_positive_pairs": robust_vov_pairs,
            },
            "secondary_maxt3_uncontrolled": hac_maxt3,
            "secondary_maxt3_after_oilret_control": ctrl_oilret_maxt3,
        },
        "verdict": verdict,
        "prior_work_convergent_null": ["K1665", "K1444", "K1351", "K1329", "K1647"],
    }

    figs = make_figures(vol, dy_vol)
    results["figures"] = [os.path.basename(f) for f in figs]

    with open(RESULTS_PATH, "w") as fh:
        json.dump(results, fh, indent=2, default=str)

    print(f"[K1692] verdict={verdict}  n={sample['n_common']}")
    print(f"  1st-order vol : Wald-Bonf unctrl={hac_wald_pass}/{n_pairs}  "
          f"oil-ret-ctrl={ctrl_oilret_wald}/{n_pairs}  vix-ctrl={ctrl_vix_wald}/{n_pairs}  "
          f"OOS-edge={oos_edge}/{n_pairs}  robust={robust_vol_pairs}")
    print(f"  2nd-order vov : Wald-Bonf unctrl={vov_wald_pass}/{n_pairs}  "
          f"oil-ret-ctrl={vov_ctrl_oilret_wald}/{n_pairs}  vix-ctrl={vov_ctrl_vix_wald}/{n_pairs}  "
          f"robust={robust_vov_pairs}")
    print(f"  DY GFEVD vol : total={dy_vol['total_connectedness_pct']:.1f}% "
          f"CI95={[round(x,2) for x in dy_ci['total_ci95']]}  oil->eq net={dy_vol['oil_to_equity_net']:+.4f}")
    print(f"  DY GFEVD vov : total={dy_vov['total_connectedness_pct']:.1f}% "
          f"oil->eq net={dy_vov['oil_to_equity_net']:+.4f}")
    print(f"[K1692] results -> {RESULTS_PATH}")


if __name__ == "__main__":
    main()
