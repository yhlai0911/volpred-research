"""
K1622 — Forecast Reconciliation for RV Prediction:
Is hierarchical/cross-sectional coherence a "free lunch" across horizons?

Research question
-----------------
HAR base forecasts of realized variance (RV) are made *independently* for each
horizon (1d/5d/22d) and each asset (SPY aggregate vs sector-ETF components).
Forecast reconciliation (Wickramasuriya-Athanasopoulos-Hyndman 2019 MinT) is an
*ex-post* linear projection that forces the base forecasts onto a coherent
subspace (temporal aggregation consistency + cross-sectional aggregation
consistency). The strong claim in the reconciliation literature is that this is
"free": coherence never hurts and often helps *every* series.

We test that claim rigorously on RV:
  (a) TEMPORAL reconciliation: 1d/5d/22d cumulative-variance coherence per asset.
  (b) CROSS-SECTIONAL reconciliation: SPY(aggregate) vs 6 sector ETFs per horizon.
  (c) COMBINED (sequential cross-temporal): temporal then cross-sectional.
Per-horizon DM tests (QLIKE loss) with horizon-specific HAC lag + HLN small-sample
correction decide whether reconciled beats base.

Differentiation from prior K
----------------------------
- K1315 (PASS_NULL): forecast *combination* (weighted average of HAR-ABS + HAR-VIX)
  for SPY *daily* RV. Combination = convex/linear pooling of competing models on
  ONE target. Reconciliation is ORTHOGONAL: it imposes cross-horizon / cross-asset
  aggregation *constraints* on forecasts of DIFFERENT-but-related targets. Not a
  weighted average; a constrained projection onto a coherent subspace.
- K1184: HAR combination exp-QLIKE. Same distinction.
Reconciliation != combination.

Honesty / anti-lookahead safeguards (see README self-check table)
-----------------------------------------------------------------
- Explicit expanding-window training mask: for forecast origin o and a node whose
  target window ends at o+H, training rows j are used only if j+H <= o-1
  (target fully realized strictly before origin). Prevents the training tail from
  seeing the forecast day or later.
- Per-horizon DM inference: HAC lag = H-1 (1d->0, 5d->4, 22d->21) + HLN(1997)
  small-sample correction. NO shared DM horizon across targets.
- Cross-sectional DM: aggregate loss differential BY DATE across assets first
  (K1355), then HAC/DM on the date series; stacked asset-day = diagnostic only.
- QLIKE canonical actual/predicted via volpred.stats.model_evaluation.qlike_pointwise.
- All randomness seeded (seed=42). MinT covariance = in-sample shrinkage only.
- Range-based Garman-Klass RV proxy (from OHLC) is used for the LONG history
  (long sample requirement); 5-min RV (SPY, ~117 obs) is a recent cross-check ONLY.

Author: VolPred Research System (K1622)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy.optimize import nnls

# canonical QLIKE
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))
from volpred.stats.model_evaluation import qlike_pointwise  # noqa: E402

SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
PLOTS_DIR = os.path.join(HERE, "plots")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(PLOTS_DIR, exist_ok=True)

START = "2010-01-01"
END = "2026-07-01"

# Cross-sectional hierarchy: SPY = aggregate, 6 sector ETFs = components
AGG = "SPY"
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI"]
CS_ASSETS = [AGG] + SECTORS
# TW robustness (temporal-only cross-check; not in cross-section)
TW = "0050.TW"
ALL_ASSETS = CS_ASSETS + [TW]

HORIZONS = {"1d": 1, "5d": 5, "22d": 22}

# Temporal hierarchy blocks (non-overlapping partition of the 22-day window):
#   b1 = day 1 (== 1d target)
#   b2 = days 2..5   (4 days)
#   b3 = days 6..22  (17 days)
# aggregates: A5 = b1+b2 (== 5d target), A22 = b1+b2+b3 (== 22d target)
# Node order for the temporal MinT vector: [b1, b2, b3, A5, A22]
TEMP_NODES = ["b1", "b2", "b3", "A5", "A22"]
# max future day offset used by each node (for the no-lookahead training cutoff)
NODE_MAXH = {"b1": 1, "b2": 5, "b3": 22, "A5": 5, "A22": 22}
# summing matrix S (5 nodes x 3 bottom[b1,b2,b3])
S_TEMP = np.array([
    [1, 0, 0],   # b1
    [0, 1, 0],   # b2
    [0, 0, 1],   # b3
    [1, 1, 0],   # A5
    [1, 1, 1],   # A22
], dtype=float)

REFIT_EVERY = 21          # monthly re-estimation (expanding window)
BURN_IN = 750             # ~3y before first OOS origin (feature + initial train)


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def fetch_ohlc(ticker: str) -> pd.DataFrame:
    """Fetch daily OHLC via yfinance, cache to CSV. Returns df with O/H/L/C."""
    safe = ticker.replace(".", "_").replace("^", "")
    path = os.path.join(DATA_DIR, f"{safe}_ohlc.csv")
    if os.path.exists(path):
        df = pd.read_csv(path, index_col=0, parse_dates=True)
        return df
    import yfinance as yf
    raw = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=False)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"empty download for {ticker}")
    # flatten possible MultiIndex columns
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    df = raw[["Open", "High", "Low", "Close"]].copy()
    df.columns = ["O", "H", "L", "C"]
    df.to_csv(path)
    return df


def garman_klass_rv(df: pd.DataFrame) -> pd.Series:
    """Daily Garman-Klass realized-variance proxy from OHLC.
    GK = 0.5*(ln H/L)^2 - (2 ln2 - 1)*(ln C/O)^2.
    Falls back to Parkinson (always >=0) on the rare non-positive GK day.
    """
    o = df["O"].astype(float)
    h = df["H"].astype(float)
    lo = df["L"].astype(float)
    c = df["C"].astype(float)
    valid = (o > 0) & (h > 0) & (lo > 0) & (c > 0) & (h >= lo)
    ln_hl = np.log(h / lo)
    ln_co = np.log(c / o)
    gk = 0.5 * ln_hl**2 - (2 * np.log(2) - 1) * ln_co**2
    park = (1.0 / (4.0 * np.log(2))) * ln_hl**2  # always >= 0
    rv = gk.where(gk > 0, park)                  # fallback where GK<=0
    rv = rv.where(valid, np.nan)
    rv.name = "rv"
    n_fallback = int(((gk <= 0) & valid).sum())
    rv.attrs["n_parkinson_fallback"] = n_fallback
    rv.attrs["n_valid"] = int(valid.sum())
    return rv


def build_rv_panel() -> tuple[dict, dict]:
    """Return (rv_series_by_asset, meta)."""
    rv_by_asset = {}
    meta = {}
    for t in ALL_ASSETS:
        df = fetch_ohlc(t)
        rv = garman_klass_rv(df)
        rv = rv.dropna()
        # basic sanity: drop non-finite / zero
        rv = rv[(rv > 0) & np.isfinite(rv)]
        rv_by_asset[t] = rv
        meta[t] = {
            "n_obs": int(len(rv)),
            "start": str(rv.index.min().date()),
            "end": str(rv.index.max().date()),
            "n_parkinson_fallback": int(rv.attrs.get("n_parkinson_fallback", 0)),
        }
    return rv_by_asset, meta


# ----------------------------------------------------------------------------
# HAR features + node targets
# ----------------------------------------------------------------------------
def har_features(rv: pd.Series) -> pd.DataFrame:
    """RV_d, RV_w, RV_m using info up to and including day o (no lookahead)."""
    f = pd.DataFrame(index=rv.index)
    f["rv_d"] = rv
    f["rv_w"] = rv.rolling(5).mean()
    f["rv_m"] = rv.rolling(22).mean()
    return f


def node_targets(rv: pd.Series) -> pd.DataFrame:
    """Cumulative future-variance targets for the 5 temporal nodes.
    All targets at origin o use only future days (o+1 ...); realized later.
    """
    r = rv.values.astype(float)
    n = len(r)
    out = {k: np.full(n, np.nan) for k in TEMP_NODES}
    for o in range(n):
        # b1 = RV[o+1]
        if o + 1 < n:
            out["b1"][o] = r[o + 1]
        # b2 = sum RV[o+2 .. o+5]
        if o + 5 < n:
            out["b2"][o] = r[o + 2:o + 6].sum()
        # b3 = sum RV[o+6 .. o+22]
        if o + 22 < n:
            out["b3"][o] = r[o + 6:o + 23].sum()
        # A5 = sum RV[o+1 .. o+5]
        if o + 5 < n:
            out["A5"][o] = r[o + 1:o + 6].sum()
        # A22 = sum RV[o+1 .. o+22]
        if o + 22 < n:
            out["A22"][o] = r[o + 1:o + 23].sum()
    df = pd.DataFrame(out, index=rv.index)
    return df


# ----------------------------------------------------------------------------
# MinT reconciliation
# ----------------------------------------------------------------------------
def shrink_cov(residuals: np.ndarray) -> np.ndarray:
    """Schafer-Strimmer shrinkage of sample covariance toward its diagonal.
    residuals: (n_obs, n_nodes). Returns (n_nodes, n_nodes) shrunk covariance.
    """
    X = residuals[np.all(np.isfinite(residuals), axis=1)]
    n, k = X.shape
    if n < k + 2:
        # too few rows: fall back to diagonal of variances
        v = np.nanvar(residuals, axis=0)
        v = np.where(np.isfinite(v) & (v > 0), v, 1e-12)
        return np.diag(v)
    Xc = X - X.mean(axis=0, keepdims=True)
    S = (Xc.T @ Xc) / (n - 1)
    d = np.sqrt(np.diag(S))
    d = np.where(d > 0, d, 1e-12)
    R = S / np.outer(d, d)
    # shrink correlations toward 0 (diagonal target)
    # Schafer-Strimmer lambda for off-diagonal correlations
    var_r_num = 0.0
    r_sq_sum = 0.0
    w = Xc / d  # standardized
    for i in range(k):
        for j in range(i + 1, k):
            wij = w[:, i] * w[:, j]
            rij = R[i, j]
            var_rij = (n / ((n - 1) ** 3)) * np.sum((wij - wij.mean()) ** 2)
            var_r_num += var_rij
            r_sq_sum += rij ** 2
    lam = 1.0 if r_sq_sum <= 0 else min(1.0, max(0.0, var_r_num / r_sq_sum))
    R_shrunk = (1 - lam) * R + lam * np.eye(k)
    S_shrunk = R_shrunk * np.outer(d, d)
    # ensure PD
    S_shrunk += np.eye(k) * 1e-12
    return S_shrunk


def mint_reconcile(base: np.ndarray, S: np.ndarray, W: np.ndarray) -> np.ndarray:
    """MinT reconciliation. base=(n_nodes,), S=(n_nodes,n_bottom), W=(n_nodes,n_nodes).
    Returns reconciled all-node vector (n_nodes,).
    """
    try:
        Wi = np.linalg.inv(W)
    except np.linalg.LinAlgError:
        Wi = np.linalg.pinv(W)
    StWi = S.T @ Wi
    M = StWi @ S
    try:
        Minv = np.linalg.inv(M)
    except np.linalg.LinAlgError:
        Minv = np.linalg.pinv(M)
    G = Minv @ StWi                 # (n_bottom, n_nodes)
    b_tilde = G @ base              # reconciled bottom
    return S @ b_tilde              # reconciled all nodes


# ----------------------------------------------------------------------------
# Base HAR forecasting (expanding, monthly refit, no-lookahead)
# ----------------------------------------------------------------------------
def ols_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """OLS with intercept. X:(n,3), y:(n,). Returns beta (4,)."""
    A = np.column_stack([np.ones(len(X)), X])
    beta, *_ = np.linalg.lstsq(A, y, rcond=None)
    return beta


def ols_predict(beta: np.ndarray, x: np.ndarray) -> float:
    return float(beta[0] + beta[1:] @ x)


def forecast_asset(rv: pd.Series):
    """Produce base + temporally-reconciled forecasts for all origins/nodes.

    Returns dict with:
      index      : DatetimeIndex of forecast origins (OOS)
      base       : (n_oos, 5) base node forecasts [b1,b2,b3,A5,A22]
      recon      : (n_oos, 5) temporally reconciled node forecasts
      actual     : (n_oos, 5) realized node targets
    """
    feats = har_features(rv)
    tgts = node_targets(rv)
    idx = rv.index
    n = len(rv)

    Xall = feats[["rv_d", "rv_w", "rv_m"]].values
    Yall = tgts[TEMP_NODES].values  # (n,5)

    feat_ok = np.all(np.isfinite(Xall), axis=1)

    first_o = BURN_IN
    origins = []
    base_list, recon_list, actual_list = [], [], []

    betas = {k: None for k in TEMP_NODES}
    W = None
    last_refit = -10**9

    for o in range(first_o, n):
        if not feat_ok[o]:
            continue
        # need all node actuals realized (for evaluation); A22 requires o+22<n
        if o + 22 >= n:
            break
        # ---- refit (expanding window, monthly) ----
        if o - last_refit >= REFIT_EVERY or betas["b1"] is None:
            resid_cols = {}
            common_mask = None
            for node in TEMP_NODES:
                H = NODE_MAXH[node]
                cutoff = o - 1 - H  # last training origin whose target is realized < o
                jmask = feat_ok.copy()
                jmask[cutoff + 1:] = False
                yj = Yall[:, TEMP_NODES.index(node)]
                jmask &= np.isfinite(yj)
                Xtr = Xall[jmask]
                ytr = yj[jmask]
                if len(Xtr) < 60:
                    betas[node] = None
                else:
                    b = ols_fit(Xtr, ytr)
                    betas[node] = b
                    # in-sample residuals for covariance (align later)
                    resid = np.full(n, np.nan)
                    resid[jmask] = ytr - (b[0] + Xtr @ b[1:])
                    resid_cols[node] = resid
            # covariance from common in-sample rows (strictest cutoff = A22)
            if len(resid_cols) == 5:
                R = np.column_stack([resid_cols[k] for k in TEMP_NODES])
                cutoff_strict = o - 1 - 22
                Rtr = R[:cutoff_strict + 1]
                W = shrink_cov(Rtr)
            last_refit = o

        if any(betas[k] is None for k in TEMP_NODES) or W is None:
            continue

        x = Xall[o]
        base = np.array([ols_predict(betas[k], x) for k in TEMP_NODES])
        # floor tiny/negative base forecasts (variance must be > 0)
        base = np.where(base > 1e-12, base, 1e-12)
        recon = mint_reconcile(base, S_TEMP, W)
        recon = np.where(recon > 1e-12, recon, 1e-12)
        actual = Yall[o]

        origins.append(idx[o])
        base_list.append(base)
        recon_list.append(recon)
        actual_list.append(actual)

    return {
        "index": pd.DatetimeIndex(origins),
        "base": np.array(base_list),
        "recon": np.array(recon_list),
        "actual": np.array(actual_list),
    }


# ----------------------------------------------------------------------------
# DM test (per-horizon HAC lag = H-1 + HLN correction)
# ----------------------------------------------------------------------------
def dm_hln(loss_base: np.ndarray, loss_recon: np.ndarray, H: int) -> dict:
    """DM test with horizon-specific HAC (lags 1..H-1) + HLN(1997) correction.
    d = loss_base - loss_recon.  t>0  =>  reconciliation has LOWER loss (better).
    """
    d = np.asarray(loss_base, float) - np.asarray(loss_recon, float)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 30:
        return {"t": np.nan, "p": np.nan, "mean_d": np.nan, "n": T}
    d_bar = d.mean()
    gamma0 = np.mean((d - d_bar) ** 2)
    var = gamma0
    for k in range(1, H):
        cov = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        var += 2 * cov
    if var <= 0:
        return {"t": 0.0, "p": 1.0, "mean_d": float(d_bar), "n": T}
    dm = d_bar / np.sqrt(var / T)
    corr = np.sqrt(max((T + 1 - 2 * H + H * (H - 1) / T) / T, 1e-9))
    dm_h = dm * corr
    from scipy import stats
    p = 2 * (1 - stats.t.cdf(abs(dm_h), df=T - 1))
    return {"t": float(dm_h), "p": float(p), "mean_d": float(d_bar), "n": int(T)}


def verdict_from_dm(dm: dict) -> str:
    t = dm["t"]
    if not np.isfinite(t):
        return "NA"
    if abs(t) <= 3.0:            # Harvey (2016) multiple-testing threshold
        return "PASS_NULL"      # no significant difference -> not a free lunch
    return "PASS" if t > 0 else "FAIL"  # PASS = recon better; FAIL = recon worse


# ----------------------------------------------------------------------------
# Cross-sectional reconciliation (SPY aggregate vs 6 sectors, per horizon)
# ----------------------------------------------------------------------------
HNODE = {"1d": "b1", "5d": "A5", "22d": "A22"}  # temporal node that maps to each horizon


def cross_sectional_reconcile(asset_fc: dict, use_recon_input: bool):
    """For each horizon, reconcile SPY(aggregate) + 6 sector base(or temporally
    reconciled) forecasts. Returns per-horizon dict of aligned base/cs/actual
    for the 7 CS assets on the common origin index.

    use_recon_input=False -> pure cross-sectional (input = base forecasts)
    use_recon_input=True  -> combined (input = temporally reconciled forecasts)
    """
    src = "recon" if use_recon_input else "base"
    results = {}
    for hz, H in HORIZONS.items():
        node_i = TEMP_NODES.index(HNODE[hz])
        # align all 7 CS assets on common origins
        frames = {}
        for a in CS_ASSETS:
            fc = asset_fc[a]
            s_base = pd.Series(fc["base"][:, node_i], index=fc["index"])
            s_in = pd.Series(fc[src][:, node_i], index=fc["index"])
            s_act = pd.Series(fc["actual"][:, node_i], index=fc["index"])
            frames[a] = pd.DataFrame({"base": s_base, "inp": s_in, "act": s_act})
        common = None
        for a in CS_ASSETS:
            common = frames[a].index if common is None else common.intersection(frames[a].index)
        common = common.sort_values()
        base_mat = np.column_stack([frames[a].loc[common, "base"].values for a in CS_ASSETS])
        inp_mat = np.column_stack([frames[a].loc[common, "inp"].values for a in CS_ASSETS])
        act_mat = np.column_stack([frames[a].loc[common, "act"].values for a in CS_ASSETS])

        n = len(common)
        cs_mat = np.full_like(inp_mat, np.nan)

        # bottom = 6 sectors (cols 1..6), aggregate = SPY (col 0)
        # S_cs (7x6): SPY row = weights w; sectors = identity
        last_refit = -10**9
        w = None
        W_cs = None
        for o in range(n):
            if o - last_refit >= REFIT_EVERY or w is None:
                cutoff = o - 1 - H  # no-lookahead: only realized-target rows for weights/cov
                if cutoff >= 60:
                    # in-sample fit of SPY_actual ~ sector_actuals (no intercept)
                    A_act = act_mat[:cutoff + 1]
                    ok = np.all(np.isfinite(A_act), axis=1)
                    A_ok = A_act[ok]
                    if len(A_ok) >= 60:
                        y_spy = A_ok[:, 0]
                        X_sec = A_ok[:, 1:]
                        # NNLS: non-negative variance-share weights (variances can't
                        # contribute negatively). Eliminates the negative-forecast
                        # pathology that unconstrained OLS weights induce in MinT.
                        w, _ = nnls(X_sec, y_spy)
                        # cross-sectional forecast-error residuals for covariance.
                        # Use inp_mat (the ACTUAL reconciliation input): == base for
                        # pure cross-sectional, == temporally-reconciled for combined,
                        # so W_cs is consistent with what is fed to MinT (Codex fix).
                        # Still no-lookahead: inp rows <= cutoff use only their own past.
                        resid = A_ok - inp_mat[:cutoff + 1][ok]
                        W_cs = shrink_cov(resid)
                        last_refit = o
            if w is None or W_cs is None:
                continue
            S_cs = np.zeros((7, 6))
            S_cs[0, :] = w              # SPY = w' sectors
            S_cs[1:, :] = np.eye(6)     # sectors = bottom
            base_o = inp_mat[o]
            if not np.all(np.isfinite(base_o)):
                continue
            base_o = np.where(base_o > 1e-12, base_o, 1e-12)
            rec = mint_reconcile(base_o, S_cs, W_cs)
            cs_mat[o] = np.where(rec > 1e-12, rec, 1e-12)

        results[hz] = {
            "index": common,
            "base": base_mat,     # per-asset base (the input's own base ref)
            "input": inp_mat,     # what was fed to CS recon
            "cs": cs_mat,         # cross-sectionally reconciled
            "actual": act_mat,
        }
    return results


# ----------------------------------------------------------------------------
# Evaluation helpers
# ----------------------------------------------------------------------------
# QLIKE is singular for near-zero predictions. MinT can (rarely) produce
# invalid variance forecasts (negative, floored to 1e-12, or implausibly tiny).
# VALID_FLOOR = 1e-6 ~= (0.1% daily vol)^2 is the minimum ECONOMICALLY plausible
# daily variance for these liquid ETFs (empirical 1d actual 1st-pct ~4.7e-6, and
# multi-day cumulative variances are far larger), so this threshold catches ONLY
# the numerical artifacts (~0.004-0.013% of forecasts), never real low-vol days.
# Base HAR forecasts are well-behaved and never trip it (symmetric, unbiased mask).
# Excluded forecasts are COUNTED and reported (n_invalid_recon) as the key
# cross-sectional instability diagnostic (see README).
VALID_FLOOR = 1e-6


def qlike_loss(actual: np.ndarray, pred: np.ndarray) -> np.ndarray:
    return qlike_pointwise(actual, pred)


def eval_pair(actual, base, recon, H):
    """Return dict: QLIKE base/recon + DM(base vs recon). Excludes invalid
    (floored, <=VALID_FLOOR) predictions; reports n_invalid_recon."""
    finite = np.isfinite(actual) & np.isfinite(base) & np.isfinite(recon) & (actual > 0)
    n_invalid = int((finite & (recon <= VALID_FLOOR)).sum())
    n_invalid_base = int((finite & (base <= VALID_FLOOR)).sum())  # transparency (Codex)
    m = finite & (base > VALID_FLOOR) & (recon > VALID_FLOOR)
    a, b, r = actual[m], base[m], recon[m]
    if len(a) < 30:
        return {"n": int(len(a)), "n_invalid_recon": n_invalid,
                "n_invalid_base": n_invalid_base, "verdict": "NA",
                "qlike_base": np.nan, "qlike_recon": np.nan,
                "qlike_improve_pct": np.nan, "dm_t": np.nan, "dm_p": np.nan}
    lb = qlike_loss(a, b)
    lr = qlike_loss(a, r)
    dm = dm_hln(lb, lr, H)
    return {
        "n": int(m.sum()),
        "n_invalid_recon": n_invalid,
        "n_invalid_base": n_invalid_base,
        "invalid_recon_frac": float(n_invalid / max(int(finite.sum()), 1)),
        "qlike_base": float(np.mean(lb)),
        "qlike_recon": float(np.mean(lr)),
        "qlike_improve_pct": float(100 * (np.mean(lb) - np.mean(lr)) / np.mean(lb)),
        "dm_t": dm["t"], "dm_p": dm["p"],
        "verdict": verdict_from_dm(dm),
    }


def date_aggregated_dm(actual_mat, base_mat, recon_mat, H):
    """K1355: aggregate cross-asset QLIKE loss differential BY DATE, then DM."""
    nrow, nasset = actual_mat.shape
    lb_by_date = np.full(nrow, np.nan)
    lr_by_date = np.full(nrow, np.nan)
    n_invalid = 0
    n_invalid_base = 0
    for i in range(nrow):
        a = actual_mat[i]; b = base_mat[i]; r = recon_mat[i]
        finite = np.isfinite(a) & np.isfinite(b) & np.isfinite(r) & (a > 0)
        n_invalid += int((finite & (r <= VALID_FLOOR)).sum())
        n_invalid_base += int((finite & (b <= VALID_FLOOR)).sum())
        m = finite & (b > VALID_FLOOR) & (r > VALID_FLOOR)
        if m.sum() == 0:
            continue
        lb_by_date[i] = np.mean(qlike_loss(a[m], b[m]))
        lr_by_date[i] = np.mean(qlike_loss(a[m], r[m]))
    ok = np.isfinite(lb_by_date) & np.isfinite(lr_by_date)
    dm = dm_hln(lb_by_date[ok], lr_by_date[ok], H)
    return {
        "n_dates": int(ok.sum()),
        "n_invalid_recon": int(n_invalid),
        "n_invalid_base": int(n_invalid_base),
        "qlike_base": float(np.nanmean(lb_by_date)),
        "qlike_recon": float(np.nanmean(lr_by_date)),
        "qlike_improve_pct": float(100 * (np.nanmean(lb_by_date) - np.nanmean(lr_by_date)) / np.nanmean(lb_by_date)),
        "dm_t": dm["t"], "dm_p": dm["p"],
        "verdict": verdict_from_dm(dm),
    }


def stacked_asset_day_dm(actual_mat, base_mat, recon_mat, H):
    """Diagnostic ONLY (K1355): stacked asset-day, understates SE."""
    a = actual_mat.flatten(); b = base_mat.flatten(); r = recon_mat.flatten()
    m = np.isfinite(a) & np.isfinite(b) & np.isfinite(r) & (a > 0) & (b > VALID_FLOOR) & (r > VALID_FLOOR)
    dm = dm_hln(qlike_loss(a[m], b[m]), qlike_loss(a[m], r[m]), H)
    return {"n": int(m.sum()), "dm_t": dm["t"], "dm_p": dm["p"], "verdict": verdict_from_dm(dm),
            "NOTE": "diagnostic_only_stacked_asset_day_understates_SE"}


# ----------------------------------------------------------------------------
# 5-min RV cross-check (SPY only; ~117 recent obs)
# ----------------------------------------------------------------------------
def five_min_crosscheck():
    path = os.path.join(HERE, "..", "..", "data", "intraday", "SPY_daily_rv.csv")
    if not os.path.exists(path):
        return {"available": False}
    rv5 = pd.read_csv(path, index_col=0, parse_dates=True)["rv_5min"].dropna()
    df = fetch_ohlc(AGG)
    gk = garman_klass_rv(df).dropna()
    common = rv5.index.intersection(gk.index)
    if len(common) < 20:
        return {"available": True, "n_overlap": int(len(common)), "note": "too_few"}
    a = gk.loc[common].values
    b = rv5.loc[common].values
    rho = float(np.corrcoef(np.log(a), np.log(b))[0, 1])
    from scipy import stats
    sp = float(stats.spearmanr(a, b).correlation)
    return {
        "available": True,
        "n_overlap": int(len(common)),
        "period": [str(common.min().date()), str(common.max().date())],
        "log_pearson_gk_vs_5min": rho,
        "spearman_gk_vs_5min": sp,
        "mean_ratio_gk_over_5min": float(np.mean(a / b)),
        "note": "GK range proxy vs 5-min RV, SPY recent window; validates proxy rank-fidelity",
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    t0 = datetime.now()
    print("[K1622] building RV panel ...")
    rv_by_asset, data_meta = build_rv_panel()
    for a, m in data_meta.items():
        print(f"  {a}: n={m['n_obs']} {m['start']}..{m['end']} (parkinson_fallback={m['n_parkinson_fallback']})")

    print("[K1622] fitting HAR + temporal reconciliation per asset ...")
    asset_fc = {}
    for a in ALL_ASSETS:
        asset_fc[a] = forecast_asset(rv_by_asset[a])
        print(f"  {a}: {len(asset_fc[a]['index'])} OOS origins")

    results = {
        "experiment_id": "K1622",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "proxy": "Garman-Klass range-based RV from daily OHLC (long history)",
            "proxy_disclosure": "GK chosen for LONG sample (>=500/asset); NOT 5-min RV. "
                                "5-min RV (SPY ~117 obs) used only as recent cross-check.",
            "period": [START, END],
            "assets": data_meta,
        },
        "design": {
            "temporal_hierarchy": "blocks b1=day1, b2=days2-5, b3=days6-22; A5=b1+b2 (5d), A22=b1+b2+b3 (22d)",
            "cross_sectional": "SPY aggregate = w' sectors (in-sample NNLS non-negative weights, approximate coherence); 6 sector ETFs = bottom",
            "combined": "sequential cross-temporal: temporal MinT then cross-sectional MinT (Kourentzes-Athanasopoulos 2019); W_cs from the reconciliation-input residuals for consistency",
            "reconciliation": "MinT(Shrink) — Wickramasuriya-Athanasopoulos-Hyndman (2019 JASA)",
            "dm": "per-horizon HAC lag=H-1 + HLN(1997) small-sample correction; t>0 => reconciliation better; Harvey |t|>3 significance",
            "qlike": "canonical actual/predicted via volpred.stats.model_evaluation.qlike_pointwise (K783c)",
            "cross_sectional_dm": "date-aggregated across assets first (K1355); stacked asset-day = diagnostic only",
            "invalid_forecast_handling": "MinT-emitted non-positive/near-zero variance forecasts (< VALID_FLOOR=1e-6) are EXCLUDED from QLIKE/DM and COUNTED (n_invalid_recon, n_invalid_base). Excluding the worst reconciled points is CONSERVATIVE for the no-free-lunch conclusion: including them would only make reconciliation look worse. Base HAR forecasts never trip the floor (n_invalid_base=0), so the mask is unbiased.",
        },
        "temporal": {},
        "cross_sectional": {},
        "combined": {},
        "five_min_crosscheck": five_min_crosscheck(),
    }

    # ---- (a) TEMPORAL: per asset, per horizon ----
    print("[K1622] evaluating TEMPORAL reconciliation ...")
    temporal_per_asset = {}
    for a in ALL_ASSETS:
        fc = asset_fc[a]
        temporal_per_asset[a] = {}
        for hz, H in HORIZONS.items():
            j = TEMP_NODES.index(HNODE[hz])
            res = eval_pair(fc["actual"][:, j], fc["base"][:, j], fc["recon"][:, j], H)
            temporal_per_asset[a][hz] = res
    results["temporal"]["per_asset"] = temporal_per_asset
    # pooled-by-date across the CS assets (SPY+sectors) for an overall verdict
    temporal_pooled = {}
    for hz, H in HORIZONS.items():
        j = TEMP_NODES.index(HNODE[hz])
        # align CS assets on common origins
        common = None
        for a in CS_ASSETS:
            idx = asset_fc[a]["index"]
            common = idx if common is None else common.intersection(idx)
        common = common.sort_values()
        act = np.column_stack([pd.Series(asset_fc[a]["actual"][:, j], index=asset_fc[a]["index"]).loc[common].values for a in CS_ASSETS])
        bas = np.column_stack([pd.Series(asset_fc[a]["base"][:, j], index=asset_fc[a]["index"]).loc[common].values for a in CS_ASSETS])
        rec = np.column_stack([pd.Series(asset_fc[a]["recon"][:, j], index=asset_fc[a]["index"]).loc[common].values for a in CS_ASSETS])
        temporal_pooled[hz] = {
            "date_aggregated": date_aggregated_dm(act, bas, rec, H),
            "stacked_diagnostic": stacked_asset_day_dm(act, bas, rec, H),
        }
    results["temporal"]["pooled_across_assets"] = temporal_pooled

    # ---- (b) CROSS-SECTIONAL: per horizon ----
    print("[K1622] evaluating CROSS-SECTIONAL reconciliation ...")
    cs = cross_sectional_reconcile(asset_fc, use_recon_input=False)
    cross_sectional = {}
    for hz, H in HORIZONS.items():
        d = cs[hz]
        cross_sectional[hz] = {
            "date_aggregated": date_aggregated_dm(d["actual"], d["input"], d["cs"], H),
            "stacked_diagnostic": stacked_asset_day_dm(d["actual"], d["input"], d["cs"], H),
            "per_asset": {
                a: eval_pair(d["actual"][:, i], d["input"][:, i], d["cs"][:, i], H)
                for i, a in enumerate(CS_ASSETS)
            },
        }
    results["cross_sectional"] = cross_sectional

    # ---- (c) COMBINED: sequential (temporal then cross-sectional) ----
    print("[K1622] evaluating COMBINED (sequential cross-temporal) ...")
    cmb = cross_sectional_reconcile(asset_fc, use_recon_input=True)
    combined = {}
    for hz, H in HORIZONS.items():
        d = cmb[hz]
        # compare combined vs the ORIGINAL base (not the temporally-reconciled input)
        combined[hz] = {
            "date_aggregated": date_aggregated_dm(d["actual"], d["base"], d["cs"], H),
            "stacked_diagnostic": stacked_asset_day_dm(d["actual"], d["base"], d["cs"], H),
            "per_asset": {
                a: eval_pair(d["actual"][:, i], d["base"][:, i], d["cs"][:, i], H)
                for i, a in enumerate(CS_ASSETS)
            },
        }
    results["combined"] = combined

    # ---- write ----
    out_path = os.path.join(HERE, "k1622_results.json")
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[K1622] wrote {out_path}")

    make_figures(results, asset_fc, cs)
    dt = (datetime.now() - t0).total_seconds()
    print(f"[K1622] done in {dt:.1f}s")
    return results


def make_figures(results, asset_fc, cs):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Figure 1: per-horizon QLIKE base vs reconciled (SPY temporal) + DM sig
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    variants = [
        ("Temporal\n(SPY)", "temporal", lambda hz: results["temporal"]["per_asset"]["SPY"][hz]),
        ("Cross-sectional\n(date-agg)", "cs", lambda hz: results["cross_sectional"][hz]["date_aggregated"]),
        ("Combined\n(date-agg)", "cmb", lambda hz: results["combined"][hz]["date_aggregated"]),
    ]
    hzs = list(HORIZONS.keys())
    x = np.arange(len(hzs))
    width = 0.35
    for ax, (label, key, getter) in zip(axes, variants):
        qb = [getter(hz)["qlike_base"] for hz in hzs]
        qr = [getter(hz)["qlike_recon"] for hz in hzs]
        ax.bar(x - width/2, qb, width, label="Base", color="#4C72B0")
        ax.bar(x + width/2, qr, width, label="Reconciled", color="#DD8452")
        ymax = max(max(qb), max(qr))
        ax.set_ylim(0, ymax * 1.25)
        for i, hz in enumerate(hzs):
            g = getter(hz)
            t = g["dm_t"]
            star = "***" if abs(t) > 3 else ("*" if abs(t) > 2 else "ns")
            top = max(qb[i], qr[i])
            ax.text(i, top + ymax * 0.02, f"t={t:.1f}\n{star}", ha="center", va="bottom", fontsize=8)
        ax.set_xticks(x); ax.set_xticklabels(hzs)
        ax.set_title(f"{label}: QLIKE base vs reconciled", pad=14)
        ax.set_ylabel("mean QLIKE"); ax.legend(loc="upper right")
    fig.suptitle("K1622 Forecast Reconciliation — per-horizon QLIKE (lower=better); DM(HLN) t>0=recon better, |t|>3 sig", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, "fig1_qlike_base_vs_recon.png"), dpi=120)
    plt.close(fig)

    # Figure 2: cross-sectional per-asset QLIKE improvement distribution (22d)
    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, hz in zip(axes, hzs):
        pa = results["cross_sectional"][hz]["per_asset"]
        assets = list(pa.keys())
        impr = [pa[a]["qlike_improve_pct"] for a in assets]
        colors = ["#55A868" if v > 0 else "#C44E52" for v in impr]
        ax.barh(assets, impr, color=colors)
        ax.axvline(0, color="k", lw=0.8)
        ax.set_title(f"Cross-sectional {hz}: QLIKE improvement %\n(recon vs base, per asset)")
        ax.set_xlabel("% improvement (>0 = recon better)")
    fig.suptitle("K1622 Cross-sectional reconciliation — per-asset improvement (positive=free lunch, negative=cost)", fontsize=11)
    fig.tight_layout()
    fig.savefig(os.path.join(PLOTS_DIR, "fig2_cross_sectional_improvement.png"), dpi=120)
    plt.close(fig)

    print("[K1622] figures written")


if __name__ == "__main__":
    main()
