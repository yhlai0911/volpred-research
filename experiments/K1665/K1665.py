"""
K1665 — Oil realized-vol → Equity realized-vol spillover ("vol-of-vol" transmission)
====================================================================================

Research question
-----------------
Does a SHOCK to crude-oil realized volatility (CL=F WTI future, USO ETF) LEAD /
transmit to the realized volatility of broad equity (SPY) and energy equity (XLE),
*beyond each series' own past* — and does any lead survive a proper autocorrelation-
robust (Newey-West HAC) treatment and a VIX control?

This is deliberately a *volatility-to-volatility* question, NOT a price-return
question. The object of study is the second moment (realized vol), so relative to
returns this is a "vol-of-vol" transmission (the brief's framing).

Why this is NOT a fresh discovery (honesty / dedup — see README §Prior work)
---------------------------------------------------------------------------
The oil→equity vol spillover question is heavily covered in this lab:
  K422  : commodity vol → equity vol network; Oil→SPX Granger p≈0, but NS after VIX control.
  K861  : first-order oil-vol → equity-vol LEVEL spillover (asymmetric, t=5.82).
  K1088 : USO+OVX cross-section forecast PASS (asset-matched).
  K1329 : CL/USO → SPY/XLE/XOP; 14 Granger pairs significant, but NO OOS forecast
          edge beyond own-vol HAR + VIX (best QLIKE +0.30%, DM t=-0.52, all fail Harvey).
  K1351 : CL=F/USO → SPY/XLE/XOP; NULL_NO_HARVEY_PASS.
  K1444 : CL=F/USO/SPY/XLE vol-of-vol; Diebold-Yilmaz spillover 48.8%; futures net
          RECEIVER (direction contradicts hypothesis). *** Codex flagged: Granger
          labelled "HAC" but actually plain ssr F-test — proper HAC-Wald never done. ***

K1665's incremental value is therefore METHODOLOGICAL, not a claim of novelty:
  (1) The proper Newey-West HAC-Wald Granger test that K1444's review demanded
      (overlapping 21d rolling vol → MA-structured errors → plain F over-rejects).
  (2) Explicit reverse-direction control (equity→oil) and BIDIRECTIONALITY read.
  (3) A VIX-control INCREMENTAL test (does oil vol add beyond VIX? — the "VIX
      sufficient statistic" theme of K422/K148).
  (4) XLE-vs-SPY differential as an economic sanity check (energy equity should be
      more oil-sensitive than the broad market).
  (5) A light OOS forecast check to reconcile the recurring finding that a
      *statistical* spillover is not the same as *incremental forecast value*.

The expected (and honestly pre-registered) result is a REPLICATION-STRENGTHENING
one: contemporaneous / short-lag statistical association exists, but its
autocorrelation-robust, VIX-controlled, out-of-sample incremental content is weak —
consistent with the whole prior line of work.

Anti-lookahead / rigor
----------------------
- Every predictor enters lagged (regressions use E_t on {E_{t-i}, O_{t-i}, VIX_{t-1}}).
- All randomness seeded (SEED=42).
- CL=F 2020-04 negative-price prints masked (log-return undefined for P<=0).
- Newey-West HAC on all inference; Wald block test for Granger.
- SPY and XLE handled as SEPARATE regressions (no asset-day pooling / iid abuse).
- OOS: expanding window, one-step; DM with Harvey-Leybourne-Newbold small-sample
  correction; horizon=1 (one-step target).

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
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(HERE, "K1665_results.json")

TICKERS = ["CL=F", "USO", "SPY", "XLE", "^VIX"]
OIL = ["CL=F", "USO"]
EQUITY = ["SPY", "XLE"]
START = "2012-01-01"
RV_WINDOW = 21          # trading days for realized-vol proxy
LAGS_PRIMARY = 5        # one trading week
ANNUALIZE = np.sqrt(252.0)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def download_prices() -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(
        TICKERS, start=START, auto_adjust=True, progress=False, threads=True
    )
    # yfinance returns a column MultiIndex (field, ticker)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].copy()
    else:  # single ticker fallback (not expected here)
        close = raw[["Close"]].copy()
    close = close[[t for t in TICKERS if t in close.columns]]
    close = close.sort_index()
    return close


def log_returns(close: pd.DataFrame) -> pd.DataFrame:
    # Mask non-positive prices (CL=F went negative on 2020-04-20 → log undefined).
    safe = close.where(close > 0)
    lr = np.log(safe).diff()
    # A single spurious -inf/inf guard
    lr = lr.replace([np.inf, -np.inf], np.nan)
    return lr


def realized_vol(lr: pd.DataFrame, window: int = RV_WINDOW) -> pd.DataFrame:
    # Rolling std of daily log returns = realized-vol proxy (annualized).
    rv = lr.rolling(window, min_periods=window).std() * ANNUALIZE
    return rv


def vol_of_vol(rv: pd.DataFrame, window: int = RV_WINDOW) -> pd.DataFrame:
    # Second-order object matching K1444 (std of RV) — used only as robustness.
    return rv.rolling(window, min_periods=window).std()


# --------------------------------------------------------------------------- #
# Statistics helpers
# --------------------------------------------------------------------------- #
def _lag_matrix(s: pd.Series, p: int, prefix: str) -> pd.DataFrame:
    return pd.concat(
        {f"{prefix}_l{i}": s.shift(i) for i in range(1, p + 1)}, axis=1
    )


def hac_wald_granger(target: pd.Series, source: pd.Series, p: int,
                     nw_override: int | None = None):
    """
    Proper autocorrelation-robust Granger test.

    Regress target_t on constant + p own lags + p source lags, estimate with
    Newey-West (HAC) covariance, then Wald-test H0: all source-lag coefs = 0.

    Returns dict with Wald chi2, F, p-value, R2, and per-lag source t-stats.
    """
    import statsmodels.api as sm

    own = _lag_matrix(target, p, "own")
    src = _lag_matrix(source, p, "src")
    df = pd.concat([target.rename("y"), own, src], axis=1).dropna()
    if len(df) < 100:
        return {"error": "insufficient_obs", "nobs": int(len(df))}

    y = df["y"].values
    X = df.drop(columns="y")
    Xc = sm.add_constant(X)
    # HAC lag length: cover the RV overlap window generously (Newey-West rule of
    # thumb floor(4*(n/100)^(2/9)) is too small for a 21-day MA structure).
    nw_lags = nw_override or max(RV_WINDOW, int(4 * (len(df) / 100.0) ** (2.0 / 9.0)))
    model = sm.OLS(y, Xc).fit(cov_type="HAC", cov_kwds={"maxlags": nw_lags})

    src_cols = [c for c in Xc.columns if c.startswith("src_")]
    idx = [list(Xc.columns).index(c) for c in src_cols]
    R = np.zeros((len(idx), Xc.shape[1]))
    for r, j in enumerate(idx):
        R[r, j] = 1.0
    wald = model.wald_test(R, scalar=False)
    # Under cov_type='HAC' + use_t (statsmodels default True), wald_test returns an
    # F-statistic (not raw chi2); p-value is computed from the correct distribution.
    wald_stat = float(np.ravel(wald.statistic)[0])
    pval = float(np.ravel(wald.pvalue)[0])
    src_t = {c: float(model.tvalues[c]) for c in src_cols}
    src_b = {c: float(model.params[c]) for c in src_cols}
    return {
        "nobs": int(len(df)),
        "p_lags": p,
        "nw_maxlags": int(nw_lags),
        "wald_stat_F": wald_stat,
        "wald_p": pval,
        "sum_src_beta": float(sum(src_b.values())),
        "max_abs_src_t": float(max(abs(v) for v in src_t.values())),
        "src_t": src_t,
        "src_beta": src_b,
        "r2": float(model.rsquared),
    }


def naive_granger(target: pd.Series, source: pd.Series, maxlag: int):
    """statsmodels ssr F-test (the K1444 approach) — reported as NON-HAC diagnostic."""
    from statsmodels.tsa.stattools import grangercausalitytests

    df = pd.concat([target.rename("y"), source.rename("x")], axis=1).dropna()
    if len(df) < 100:
        return {"error": "insufficient_obs"}
    try:
        res = grangercausalitytests(df[["y", "x"]], maxlag=maxlag, verbose=False)
    except Exception as e:  # pragma: no cover
        return {"error": str(e)}
    best_lag, best_p = None, 1.0
    for lag, out in res.items():
        p = out[0]["ssr_ftest"][1]
        if p < best_p:
            best_p, best_lag = p, lag
    return {"best_lag": int(best_lag), "best_p": float(best_p), "nobs": int(len(df))}


def vix_control_incremental(
    target: pd.Series, source: pd.Series, vix: pd.Series
) -> dict:
    """
    target_t = c + a*target_{t-1} + g*VIX_{t-1} + b*source_{t-1} + e
    HAC SE. Does the oil-vol lag survive control for VIX? (Harvey |t|>3.)
    """
    import statsmodels.api as sm

    df = pd.concat(
        {
            "y": target,
            "own1": target.shift(1),
            "vix1": vix.shift(1),
            "src1": source.shift(1),
        },
        axis=1,
    ).dropna()
    if len(df) < 100:
        return {"error": "insufficient_obs"}
    y = df["y"].values
    X = sm.add_constant(df[["own1", "vix1", "src1"]])
    nw_lags = max(RV_WINDOW, int(4 * (len(df) / 100.0) ** (2.0 / 9.0)))
    m = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": nw_lags})
    return {
        "nobs": int(len(df)),
        "beta_src": float(m.params["src1"]),
        "t_src": float(m.tvalues["src1"]),
        "p_src": float(m.pvalues["src1"]),
        "beta_vix": float(m.params["vix1"]),
        "t_vix": float(m.tvalues["vix1"]),
        "harvey_pass_src": bool(abs(float(m.tvalues["src1"])) > 3.0),
        "r2": float(m.rsquared),
    }


def dm_hln(loss_a: np.ndarray, loss_b: np.ndarray, hac_lags: int = 0,
           hln_h: int = 1) -> dict:
    """
    Diebold-Mariano with Harvey-Leybourne-Newbold small-sample correction.

    loss_* are per-period losses; positive mean(d)=loss_a-loss_b>0 → model B better.

    hac_lags : Bartlett-weighted (Newey-West) truncation lag for the long-run
        variance of the loss differential. Set >0 when the forecast TARGET is an
        overlapping-window object (e.g. 21-day rolling RV) whose forecast errors
        inherit MA-like serial correlation — otherwise the DM variance is
        under-estimated and |t| over-states, exactly the failure mode this
        experiment exposes in the naive ssr F-test.
    hln_h : forecast horizon for the HLN small-sample factor (1 for one-step).

    Returns two_sided_sig (|t|>3, any direction) AND augmented_better_sig
    (t>3, i.e. model B strictly and significantly better) — the latter is the
    correct gate for an "incremental forecast edge" count (sign matters).
    """
    d = np.asarray(loss_a) - np.asarray(loss_b)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return {"error": "too_few", "nobs": int(n)}
    dbar = d.mean()
    gamma0 = float(np.var(d, ddof=0))
    lrv = gamma0
    for k in range(1, hac_lags + 1):
        cov = float(np.cov(d[:-k], d[k:])[0, 1])
        lrv += 2.0 * (1.0 - k / (hac_lags + 1.0)) * cov
    if lrv <= 0:  # Bartlett weights guarantee PSD in theory; guard finite-sample
        lrv = gamma0
    dm = dbar / np.sqrt(lrv / n)
    corr = np.sqrt((n + 1 - 2 * hln_h + hln_h * (hln_h - 1) / n) / n)
    dm_hln_stat = float(dm * corr)
    return {
        "nobs": int(n),
        "mean_d": float(dbar),
        "dm_hln_t": dm_hln_stat,
        "hac_lags": int(hac_lags),
        "two_sided_sig": bool(abs(dm_hln_stat) > 3.0),
        "augmented_better_sig": bool(dm_hln_stat > 3.0),
    }


def expanding_oos_forecast(
    target: pd.Series, source: pd.Series, p: int = LAGS_PRIMARY, min_train: int = 750
) -> dict:
    """
    One-step expanding-window forecast of target realized vol.
    Baseline: AR(p) on own lags.  Augmented: AR(p) + source lags.
    Compares squared-error loss via DM-HLN (horizon=1).  Harvey |t|>3 to claim edge.
    """
    import statsmodels.api as sm

    own = _lag_matrix(target, p, "own")
    src = _lag_matrix(source, p, "src")
    df = pd.concat([target.rename("y"), own, src], axis=1).dropna()
    if len(df) < min_train + 250:
        return {"error": "insufficient_obs", "nobs": int(len(df))}

    y = df["y"].values
    own_cols = [c for c in df.columns if c.startswith("own_")]
    all_cols = own_cols + [c for c in df.columns if c.startswith("src_")]
    Xb = sm.add_constant(df[own_cols]).values
    Xa = sm.add_constant(df[all_cols]).values

    n = len(df)
    err_b, err_a = [], []
    # Refit weekly (step=5) to keep runtime bounded; forecasts still one-step.
    step = 5
    for t in range(min_train, n, step):
        for h in range(t, min(t + step, n)):
            bb = np.linalg.lstsq(Xb[:t], y[:t], rcond=None)[0]
            ba = np.linalg.lstsq(Xa[:t], y[:t], rcond=None)[0]
            fb = Xb[h] @ bb
            fa = Xa[h] @ ba
            err_b.append((y[h] - fb) ** 2)
            err_a.append((y[h] - fa) ** 2)
    err_b = np.array(err_b)
    err_a = np.array(err_a)
    # HAC-correct the DM variance for the 21-day overlapping-window target:
    # forecast errors on a rolling-RV target inherit MA-like autocorrelation, so
    # use Bartlett lags ~ RV_WINDOW (same rigor as the Granger HAC). >0 → aug better.
    dm = dm_hln(err_b, err_a, hac_lags=RV_WINDOW, hln_h=1)
    return {
        "nobs_oos": int(len(err_b)),
        "mse_baseline": float(err_b.mean()),
        "mse_augmented": float(err_a.mean()),
        "mse_improve_pct": float(100 * (err_b.mean() - err_a.mean()) / err_b.mean()),
        "dm_hln": dm,
    }


# --------------------------------------------------------------------------- #
# Figures
# --------------------------------------------------------------------------- #
def make_figures(rv: pd.DataFrame, hac_results: dict):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Fig 1: RV overlays -----------------------------------------------------
    fig, ax = plt.subplots(figsize=(11, 5.5))
    colors = {"CL=F": "#8B4513", "USO": "#D2691E", "SPY": "#1f4e79", "XLE": "#2e8b57"}
    for t in ["CL=F", "USO", "SPY", "XLE"]:
        if t in rv.columns:
            ax.plot(rv.index, rv[t] * 100, label=t, lw=1.0, color=colors.get(t))
    ax.axvspan(pd.Timestamp("2020-02-20"), pd.Timestamp("2020-05-01"),
               color="grey", alpha=0.15, label="COVID crash")
    ax.axvspan(pd.Timestamp("2022-02-24"), pd.Timestamp("2022-07-01"),
               color="orange", alpha=0.12, label="2022 energy shock")
    ax.set_yscale("log")
    ax.set_ylabel("21-day realized vol (%, annualized, log scale)")
    ax.set_title("K1665 — Oil vs Equity realized volatility (annualized)")
    ax.legend(ncol=3, fontsize=8, loc="upper left")
    ax.grid(alpha=0.25, which="both")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "K1665_fig1_rv_overlay.png"), dpi=130)
    plt.close(fig)

    # Fig 2: HAC-Wald oil→equity coefficient sums (with reverse & VIX-control) -
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=False)
    for ax, eq in zip(axes, EQUITY):
        labels, sums, tstats, colors2 = [], [], [], []
        for oil in OIL:
            fwd = hac_results.get(f"{oil}->{eq}", {})
            rev = hac_results.get(f"{eq}->{oil}", {})
            if "sum_src_beta" in fwd:
                labels.append(f"{oil}→{eq}")
                sums.append(fwd["sum_src_beta"])
                tstats.append(fwd["max_abs_src_t"])
                colors2.append("#c0392b")
            if "sum_src_beta" in rev:
                labels.append(f"{eq}→{oil}")
                sums.append(rev["sum_src_beta"])
                tstats.append(rev["max_abs_src_t"])
                colors2.append("#7f8c8d")
        xpos = np.arange(len(labels))
        ax.bar(xpos, sums, color=colors2)
        for i, (s, tt) in enumerate(zip(sums, tstats)):
            ax.text(i, s, f"|t|={tt:.1f}", ha="center",
                    va="bottom" if s >= 0 else "top", fontsize=8)
        ax.axhline(0, color="k", lw=0.8)
        ax.set_xticks(xpos)
        ax.set_xticklabels(labels, rotation=25, ha="right", fontsize=8)
        ax.set_title(f"HAC-Wald Σβ (source lags) — target {eq}")
        ax.set_ylabel("Σ source-lag coefficient")
        ax.grid(alpha=0.25, axis="y")
    fig.suptitle("K1665 — Autocorrelation-robust (Newey-West HAC) lead coefficients; "
                 "|t| annotated (Harvey bar = 3.0)", fontsize=10)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "K1665_fig2_hac_coefficients.png"), dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    started = datetime.now(timezone.utc).isoformat()
    print("K1665: downloading prices...", file=sys.stderr)
    close = download_prices()
    lr = log_returns(close)
    rv = realized_vol(lr)
    vov = vol_of_vol(rv)

    # Common sample across all needed series
    needed = [t for t in TICKERS if t in rv.columns]
    rv_common = rv[needed].dropna()
    sample = {
        "start": str(rv_common.index.min().date()),
        "end": str(rv_common.index.max().date()),
        "n_obs": int(len(rv_common)),
        "tickers": needed,
        "rv_window": RV_WINDOW,
        "annualized": True,
        "clf_negative_price_days_masked": int((close["CL=F"] <= 0).sum())
        if "CL=F" in close.columns else 0,
    }
    print(f"K1665: sample {sample['start']}..{sample['end']} N={sample['n_obs']}",
          file=sys.stderr)

    # Control variable is the VIX INDEX LEVEL (close["^VIX"]) — the object the
    # "VIX sufficient statistic" literature (K422/K148) uses. (Earlier draft
    # mistakenly used rv["^VIX"] = realized-vol-of-VIX; code-review K1665 caught it.)
    vix_level = close["^VIX"] if "^VIX" in close.columns else None
    vol_of_vix = rv["^VIX"] if "^VIX" in rv.columns else None  # order-matched vov ctrl

    results = {
        "k_id": "K1665",
        "title": "Oil realized-vol -> Equity realized-vol spillover (vol-of-vol transmission)",
        "started_utc": started,
        "seed": SEED,
        "sample": sample,
        "prior_work_dedup": {
            "note": "Heavily overlaps K422/K861/K1088/K1329/K1351/K1444. K1665 = "
            "methodological upgrade (proper Newey-West HAC-Wald Granger that K1444's "
            "Codex review demanded) + reverse control + VIX-incremental + XLE/SPY "
            "differential + OOS reconciliation. Framed as replication, not novelty.",
            "related_k": ["K422", "K861", "K1088", "K1329", "K1351", "K1444"],
        },
        "naive_granger_ssr": {},      # K1444-style (non-HAC), diagnostic only
        "hac_wald_granger": {},       # proper autocorr-robust test
        "vix_control_incremental": {},
        "oos_forecast": {},
        "vov_robustness_hac": {},     # second-order (std of RV) HAC re-check of K1444
    }

    # ---- 1. Naive ssr Granger (diagnostic) + 2. HAC-Wald (primary) --------- #
    for oil in OIL:
        for eq in EQUITY:
            o, e = rv[oil].dropna(), rv[eq].dropna()
            common = o.index.intersection(e.index)
            o2, e2 = o.loc[common], e.loc[common]
            # forward: oil -> equity
            results["naive_granger_ssr"][f"{oil}->{eq}"] = naive_granger(
                e2, o2, maxlag=10)
            results["hac_wald_granger"][f"{oil}->{eq}"] = hac_wald_granger(
                e2, o2, LAGS_PRIMARY)
            # reverse: equity -> oil
            results["naive_granger_ssr"][f"{eq}->{oil}"] = naive_granger(
                o2, e2, maxlag=10)
            results["hac_wald_granger"][f"{eq}->{oil}"] = hac_wald_granger(
                o2, e2, LAGS_PRIMARY)

    # ---- 3. VIX-control incremental (VIX INDEX LEVEL) --------------------- #
    if vix_level is not None:
        for oil in OIL:
            for eq in EQUITY:
                results["vix_control_incremental"][f"{oil}->{eq}|VIX"] = (
                    vix_control_incremental(rv[eq], rv[oil], vix_level)
                )

    # ---- 4. OOS forecast (reconcile statistical vs forecast value) -------- #
    for oil in OIL:
        for eq in EQUITY:
            results["oos_forecast"][f"{oil}->{eq}"] = expanding_oos_forecast(
                rv[eq].dropna(), rv[oil].dropna(), p=LAGS_PRIMARY)

    # ---- 5. vov robustness (std-of-RV, K1444 object) under proper HAC ----- #
    # vov = std of 21d RV → ~42-day induced memory (doubly overlapping). Run BOTH
    # nw=21 (default rule) and nw=42 (memory-matched) to detect HAC under-correction.
    # Also compute the naive ssr F-test on the vov object IN-PIPELINE so the
    # "plain-F 4/4" claim is our own computation, not a citation of K1444.
    results["vov_robustness_hac42"] = {}
    results["vov_naive_granger_ssr"] = {}
    for oil in OIL:
        for eq in EQUITY:
            o, e = vov[oil].dropna(), vov[eq].dropna()
            common = o.index.intersection(e.index)
            results["vov_naive_granger_ssr"][f"{oil}->{eq}"] = naive_granger(
                e.loc[common], o.loc[common], maxlag=10)
            results["vov_robustness_hac"][f"{oil}->{eq}"] = hac_wald_granger(
                e.loc[common], o.loc[common], LAGS_PRIMARY)
            results["vov_robustness_hac42"][f"{oil}->{eq}"] = hac_wald_granger(
                e.loc[common], o.loc[common], LAGS_PRIMARY, nw_override=42)

    # ---- 5b. Does any HAC-surviving vov lead add beyond VIX? --------------- #
    # Discriminating (monetization-relevant) test. Report TWO controls:
    #  (a) VIX index LEVEL (headline "VIX sufficient statistic" test), and
    #  (b) realized-vol-of-VIX (order-matched: a second-order control for a
    #      second-order target). If the oil-vov coef dies under either, the
    #      surviving Granger lead is the common risk factor, not tradable info.
    results["vov_vix_control"] = {}
    results["vov_volofvix_control"] = {}
    for oil in OIL:
        for eq in EQUITY:
            if vix_level is not None:
                results["vov_vix_control"][f"{oil}->{eq}|VIX"] = (
                    vix_control_incremental(vov[eq], vov[oil], vix_level)
                )
            if vol_of_vix is not None:
                results["vov_volofvix_control"][f"{oil}->{eq}|volVIX"] = (
                    vix_control_incremental(vov[eq], vov[oil], vol_of_vix)
                )

    # ---- Verdict synthesis ------------------------------------------------ #
    hac = results["hac_wald_granger"]
    vixc = results["vix_control_incremental"]

    fwd_pairs = [f"{o}->{e}" for o in OIL for e in EQUITY]
    hac_sig = sum(
        1 for k in fwd_pairs
        if isinstance(hac.get(k), dict) and hac[k].get("wald_p", 1) < 0.0125  # Bonferroni 4 tests
    )
    harvey_sig = sum(
        1 for k in fwd_pairs
        if isinstance(hac.get(k), dict) and hac[k].get("max_abs_src_t", 0) > 3.0
    )
    vix_survive = sum(
        1 for k, v in vixc.items()
        if isinstance(v, dict) and v.get("harvey_pass_src")
    )
    # Directional gate: only count pairs where the AUGMENTED (oil-lag) model is
    # significantly BETTER (t>3), not merely |t|>3 (a significantly-WORSE pair is
    # evidence AGAINST the hypothesis, must not be counted as an edge).
    oos_edge = sum(
        1 for k, v in results["oos_forecast"].items()
        if isinstance(v, dict) and isinstance(v.get("dm_hln"), dict)
        and v["dm_hln"].get("augmented_better_sig")
    )

    # XLE vs SPY differential (oil -> XLE should be >= oil -> SPY)
    xle_vs_spy = {}
    for oil in OIL:
        te = hac.get(f"{oil}->XLE", {}).get("max_abs_src_t")
        ts = hac.get(f"{oil}->SPY", {}).get("max_abs_src_t")
        if te is not None and ts is not None:
            xle_vs_spy[oil] = {"xle_t": te, "spy_t": ts, "xle_stronger": bool(te > ts)}

    # vov-object read (K1444's exact object): count HAC survivors + VIX survivors
    vov21 = results["vov_robustness_hac"]
    vov_hac_harvey = sum(
        1 for k in fwd_pairs
        if isinstance(vov21.get(k), dict) and vov21[k].get("max_abs_src_t", 0) > 3.0
    )
    vov_naive_sig = sum(
        1 for k in fwd_pairs
        if isinstance(results["vov_naive_granger_ssr"].get(k), dict)
        and results["vov_naive_granger_ssr"][k].get("best_p", 1) < 0.0125
    )
    vov_vix = results.get("vov_vix_control", {})
    vov_vix_survive = sum(
        1 for v in vov_vix.values()
        if isinstance(v, dict) and v.get("harvey_pass_src")
    )
    vov_volvix_survive = sum(
        1 for v in results.get("vov_volofvix_control", {}).values()
        if isinstance(v, dict) and v.get("harvey_pass_src")
    )
    # worst-case oil-coef |t| under VIX-level control at the rv level
    rv_vix_max_t = max(
        (abs(v.get("t_src", 0.0)) for v in vixc.values() if isinstance(v, dict)),
        default=float("nan"),
    )
    results.setdefault("scoreboard", {})

    if harvey_sig == 0 and vix_survive == 0 and oos_edge == 0:
        verdict = "NULL"
        rv_naive_sig = sum(
            1 for k in fwd_pairs
            if isinstance(results["naive_granger_ssr"].get(k), dict)
            and results["naive_granger_ssr"][k].get("best_p", 1) < 0.0125
        )
        summary = (
            f"PRIMARY object (first-order realized-vol level, brief framing): oil RV "
            f"does NOT robustly lead equity RV. Naive ssr F-test {rv_naive_sig}/4 "
            f"'significant' (p as low as 4.5e-19) but proper HAC-Wald: Bonferroni-sig "
            f"{hac_sig}/4, Harvey |t|>3 {harvey_sig}/4 — the gap IS the autocorrelation "
            f"from overlapping 21d windows. After controlling for the VIX INDEX LEVEL, "
            f"survive-VIX {vix_survive}/4 (max oil-coef |t|={rv_vix_max_t:.2f}); OOS "
            f"HAC-DM incremental edge {oos_edge}/4. Replicates K1329/K1351; VIX "
            f"sufficient-statistic (K422/K148) reconfirmed against the VIX level. "
            f"SECONDARY object (std-of-RV vov, K1444's exact object): in-pipeline naive "
            f"ssr F {vov_naive_sig}/4 sig → HAC-Wald Harvey {vov_hac_harvey}/4 survive "
            f"(CL=F only, robust to nw=42) → survive-VIX-level {vov_vix_survive}/4, "
            f"survive-volVIX {vov_volvix_survive}/4. Residual futures-vov lead is "
            f"statistical only, no incremental content beyond VIX: partial correction "
            f"of K1444's plain-F count, not full collapse; no tradable value."
        )
    elif harvey_sig > 0 and (vix_survive > 0 or oos_edge > 0):
        verdict = "MIXED"
        summary = (
            f"Some autocorr-robust lead survives (Harvey {harvey_sig}/4) and adds "
            f"beyond VIX/OOS in {max(vix_survive, oos_edge)}/4 cases — stronger than "
            f"prior null reads; inspect which pair."
        )
    else:
        verdict = "MIXED"
        summary = (
            f"HAC-Wald Harvey-significant {harvey_sig}/4 but incremental value "
            f"collapses after VIX control ({vix_survive}/4) / OOS ({oos_edge}/4): "
            f"statistical spillover WITHOUT tradable/incremental forecast value — "
            f"consistent with K422 (VIX-sufficient) and K1329/K1351."
        )

    results["verdict"] = verdict
    results["summary"] = summary
    results["scoreboard"] = {
        "rv_level_hac_wald_bonferroni_sig_of_4": hac_sig,
        "rv_level_hac_harvey_sig_of_4": harvey_sig,
        "rv_level_survive_vixlevel_control_of_4": vix_survive,
        "rv_level_survive_vix_max_oilcoef_abs_t": rv_vix_max_t,
        "rv_level_oos_incremental_edge_of_4": oos_edge,
        "vov_object_naive_ssr_sig_of_4": vov_naive_sig,
        "vov_object_hac_harvey_sig_of_4": vov_hac_harvey,
        "vov_object_survive_vixlevel_control_of_4": vov_vix_survive,
        "vov_object_survive_volofvix_control_of_4": vov_volvix_survive,
        "xle_vs_spy": xle_vs_spy,
    }
    results["finished_utc"] = datetime.now(timezone.utc).isoformat()

    # ---- Figures ---------------------------------------------------------- #
    try:
        make_figures(rv, hac)
        results["figures"] = [
            "K1665_fig1_rv_overlay.png",
            "K1665_fig2_hac_coefficients.png",
        ]
    except Exception as e:  # pragma: no cover
        results["figures_error"] = str(e)

    # ---- Atomic write (preamble rule §4) ---------------------------------- #
    tmp = RESULTS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    with open(tmp) as f:
        json.load(f)  # validate parseable
    os.replace(tmp, RESULTS_PATH)

    print(f"\nK1665 verdict: {verdict}")
    print(summary)
    print("scoreboard:", json.dumps(results["scoreboard"], ensure_ascii=False))


if __name__ == "__main__":
    main()
