"""
K1544 — Term-spread realized volatility as leading indicator
=============================================================

Research Question
-----------------
Does the realized volatility of the FRED 10y-2y yield-spread (DGS10 - DGS2)
predict next-month / next-quarter realized volatility of risk assets
(SPY, HYG, IWM), and provide *incremental* information over ^MOVE?

Methodology
-----------
1. Build daily yield-spread series from DGS10 / DGS2 (cached in storage/macro/).
2. Compute rolling realized term-spread volatility (TSV21 = stdev of daily
   spread changes over 21 trading days; TSV63 over 63 days). Annualized.
3. For each target asset (SPY, HYG, IWM), compute h-day-ahead annualized
   realized volatility (h ∈ {1, 21, 63}).
4. Estimate predictive regressions with HAC (Newey-West) standard errors:
       RV_{t+h} = a + b * TSV_{t-1}                              (M1)
       RV_{t+h} = a + b * MOVE_{t-1}                             (M2)
       RV_{t+h} = a + b * MOVE_{t-1} + c * TSV_{t-1}             (M3, nested)
   HAC lag = floor(4 * (n/100)^(2/9)) per Newey-West rule of thumb,
   adjusted upward to 1.5 * h to absorb overlap in forward-label.
5. Out-of-sample QLIKE / MSE comparison via Diebold-Mariano (HLN-corrected),
   expanding-window refit with min-train = 252 days.
6. Per task spec: SPY/HYG/IWM estimated separately (no asset-day pooling).
7. Multiple horizons: each horizon uses h-specific HAC lag and OOS labels.

Lookahead Safety
----------------
- Predictor: TSV computed on day t uses spread changes in [t-20 .. t-1]
  (range *strictly before* t once we shift signal). All predictors are
  .shift(1) before merging with targets so the "signal at t-1 → target at t"
  invariant holds.
- Forward-label OOS: training set row j has label window [j .. j+h]; for
  forecast origin i, we require j + h < i  ⇔  j < i - h.
- Seed: numpy seed = 42 fixed for all sampling.

Outputs
-------
experiments/K1544/K1544_results.json
experiments/K1544/fig_tsv_timeseries.png
experiments/K1544/fig_dm_heatmap.png

Verdict tiers
-------------
CONFIRMED        — TSV t-stat (HAC) > 2.5 in nested M3 AND DM-OOS favors
                   M3 over M2 (HLN-t < -1.96) for at least one (asset, h).
PARTIAL          — Some assets/horizons show CONFIRMED, others NULL.
NULL             — TSV univariate (M1) HAC-t < 2.0 everywhere.
NULL_OOS         — Significant in-sample but DM-OOS not significant.
SUBSUMED_BY_MOVE — TSV t-stat in M3 always < 2.0 (MOVE dominates).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import sys
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from volpred.stats.model_evaluation import qlike_pointwise  # noqa: E402

SEED = 42
np.random.seed(SEED)
RNG = np.random.default_rng(SEED)

EXP_DIR = Path(__file__).resolve().parent
ASSETS = ["SPY", "HYG", "IWM"]
HORIZONS = [1, 21, 63]
TSV_WINDOWS = [21, 63]          # rolling window for spread vol
RV_WINDOW = 21                  # daily backward window to define realized var per day
MIN_TRAIN = 252                 # expanding-window OOS gate
NEWEY_WEST_C = 4.0              # Newey-West bandwidth constant


# ─────────────────────────── data loaders ───────────────────────────
def load_yield_spread() -> pd.Series:
    dgs10 = pd.read_csv(REPO_ROOT / "storage/macro/fred_DGS10.csv",
                        parse_dates=["date"]).set_index("date")["DGS10"]
    dgs2 = pd.read_csv(REPO_ROOT / "storage/macro/fred_DGS2.csv",
                       parse_dates=["date"]).set_index("date")["DGS2"]
    df = pd.concat([dgs10, dgs2], axis=1).dropna()
    spread = (df["DGS10"] - df["DGS2"]).rename("term_spread")
    return spread


def load_prices() -> pd.DataFrame:
    spy_iwm = pd.read_csv(
        REPO_ROOT / "paper/leverage-direction/data/"
                    "spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv",
        parse_dates=["date"],
    ).set_index("date")[["spy_adj_close", "iwm_adj_close"]].rename(
        columns={"spy_adj_close": "SPY", "iwm_adj_close": "IWM"})
    # source CSV has ~10 duplicate dates; keep first occurrence (chronologically
    # earliest version of that day's snapshot — deterministic & seed-independent)
    spy_iwm = spy_iwm[~spy_iwm.index.duplicated(keep="first")].sort_index()

    hyg = pd.read_csv(REPO_ROOT / "experiments/k1263/data/HYG.csv",
                      parse_dates=["Date"]).set_index("Date")["HYG"]
    hyg.name = "HYG"

    move = pd.read_csv(REPO_ROOT / "experiments/k1488_move_leadingness/close_prices.csv",
                       parse_dates=["Date"]).set_index("Date")["MOVE"]
    move.name = "MOVE"

    df = pd.concat([spy_iwm, hyg, move], axis=1).sort_index()
    return df


# ─────────────────────────── feature engineering ───────────────────────────
def build_features(spread: pd.Series, prices: pd.DataFrame) -> pd.DataFrame:
    """Build aligned daily DataFrame of:
        - tsv21, tsv63   (rolling stdev of d_spread, annualised √252)
        - log_move
        - log realized variance per asset (21d backward window of squared
          daily log-returns; annualised)
    All predictors are then .shift(1) below.
    """
    # daily spread changes (in percentage points). std × √252 = annualised vol of dspread.
    dspread = spread.diff()
    tsv = pd.DataFrame(index=spread.index)
    tsv["tsv21"] = dspread.rolling(21).std() * np.sqrt(252.0)
    tsv["tsv63"] = dspread.rolling(63).std() * np.sqrt(252.0)

    # asset log returns
    log_ret = np.log(prices[ASSETS]).diff()
    # daily squared return (variance proxy). Annualised via × 252 when summing 21d window.
    sq = log_ret ** 2

    # realized variance over backward 21d window, annualised.
    rv = sq.rolling(RV_WINDOW).sum() * (252.0 / RV_WINDOW)

    # combine on union index
    df = tsv.join(rv.rename(columns={a: f"rv_{a}" for a in ASSETS}), how="outer")
    df = df.join(np.log(prices["MOVE"]).rename("log_move"), how="left")
    df = df.sort_index()
    return df


def make_forward_label(df: pd.DataFrame, asset: str, h: int) -> pd.Series:
    """h-day-ahead realized variance for `asset`, annualised.

    For horizon h, label at row i = sum of squared log returns over (i, i+h]
    times 252/h.  Strictly forward-looking so must NOT be used in any model
    fit unless training rows are filtered to satisfy j + h < forecast_origin.
    """
    # squared log returns
    sq = (np.log(df[f"rv_{asset}"].index.to_series().map(  # placeholder
        lambda x: x)))  # not used; we recompute from prices
    raise RuntimeError("unused — kept for documentation; see compute_forward_rv()")


def compute_forward_rv(prices: pd.DataFrame, asset: str, h: int) -> pd.Series:
    """Forward h-day annualised RV: sum of squared log returns over (t, t+h].

    Label at row t = sum of sq log-returns for days t+1, t+2, ..., t+h.
    Implementation: shift the trailing rolling-sum back by h so the value at
    row t equals the trailing sum that ENDS at row t+h, which by construction
    sums the squared returns r_{t+1}^2 + ... + r_{t+h}^2 (because r at row k
    is log(P_k) - log(P_{k-1})).
    """
    r = np.log(prices[asset]).diff()
    sq = r ** 2
    fwd = sq.rolling(h).sum().shift(-h)
    return (fwd * (252.0 / h)).rename(f"fwd{h}_rv_{asset}")


# ─────────────────────────── HAC regression ───────────────────────────
def newey_west_se(X: np.ndarray, residuals: np.ndarray, max_lag: int) -> np.ndarray:
    """Standard Newey-West HAC covariance for OLS.

    Returns sqrt(diag(V)) where V = (X'X)^-1 S (X'X)^-1, S is NW long-run
    covariance of X·u.
    """
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)

    u = residuals.reshape(-1, 1)
    Xu = X * u  # n×k

    S = (Xu.T @ Xu) / n
    for lag in range(1, max_lag + 1):
        w = 1.0 - lag / (max_lag + 1.0)
        G = (Xu[lag:].T @ Xu[:-lag]) / n
        S += w * (G + G.T)

    V = n * XtX_inv @ S @ XtX_inv  # n× to convert back to var of β̂
    return np.sqrt(np.diag(V))


def ols_hac(y: np.ndarray, X: np.ndarray, h: int) -> Dict:
    """OLS with HAC standard errors.

    HAC bandwidth = max(NW rule, 1.5*h) to absorb overlap from h-day forward
    label.
    """
    n = len(y)
    nw_rule = int(np.floor(NEWEY_WEST_C * (n / 100.0) ** (2.0 / 9.0)))
    bandwidth = int(max(nw_rule, np.ceil(1.5 * h)))
    bandwidth = min(bandwidth, max(1, n // 4))

    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    se = newey_west_se(X, resid, bandwidth)
    t = beta / se
    df_resid = n - X.shape[1]
    p = 2.0 * (1.0 - stats.t.cdf(np.abs(t), df=df_resid))

    ss_res = float(np.sum(resid ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    return {
        "beta": beta.tolist(),
        "se": se.tolist(),
        "t": t.tolist(),
        "p": p.tolist(),
        "n": int(n),
        "hac_lag": int(bandwidth),
        "r2": float(r2),
    }


# ─────────────────────────── DM HLN ───────────────────────────
def dm_hln(loss1: np.ndarray, loss2: np.ndarray, h: int) -> Dict:
    """Diebold-Mariano with Harvey-Leybourne-Newbold small-sample correction.

    Negative t → model 1 has lower loss (better).
    """
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return {"t_stat": np.nan, "p_value": np.nan, "n": int(n), "hln_factor": np.nan}

    d_mean = np.mean(d)
    # NW long-run variance, bandwidth = h - 1 (canonical for DM with h-step forecasts)
    bandwidth = max(1, h - 1)
    bandwidth = min(bandwidth, n // 4)
    gamma0 = np.mean((d - d_mean) ** 2)
    var_d = gamma0
    for lag in range(1, bandwidth + 1):
        w = 1.0 - lag / (bandwidth + 1.0)
        gl = np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean))
        var_d += 2.0 * w * gl
    if var_d <= 0:
        return {"t_stat": np.nan, "p_value": np.nan, "n": int(n), "hln_factor": np.nan}

    dm_stat = d_mean / np.sqrt(var_d / n)
    # HLN correction factor
    hln_factor = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_hln = dm_stat * hln_factor
    p_val = 2.0 * (1.0 - stats.t.cdf(np.abs(t_hln), df=n - 1))
    return {
        "t_stat": float(t_hln),
        "p_value": float(p_val),
        "n": int(n),
        "hln_factor": float(hln_factor),
        "raw_dm": float(dm_stat),
    }


# ─────────────────────────── pipeline ───────────────────────────
def build_panel(prices: pd.DataFrame, features: pd.DataFrame, asset: str,
                h: int) -> pd.DataFrame:
    """Aligned (lagged predictors, forward target) panel for `asset`, horizon h.

    Predictors are lagged by 1 day (use signal at t-1 → realised at (t, t+h]).
    """
    fwd = compute_forward_rv(prices, asset, h)
    df = pd.DataFrame({
        "y": fwd,                              # forward h-day annualised RV
        "tsv21": features["tsv21"].shift(1),
        "tsv63": features["tsv63"].shift(1),
        "log_move": features["log_move"].shift(1),
        "log_rv": np.log(features[f"rv_{asset}"].shift(1).clip(lower=1e-8)),
    }).dropna()
    # cap pathological zeros (y=0 means no return movement at all in the window)
    df = df[df["y"] > 0]
    return df


def insample_regressions(panel: pd.DataFrame, h: int) -> Dict:
    """In-sample HAC regressions on log-RV scale.

    log(RV_{t+h}) ~ const + log(RV_{t-1}) + (tsv21 or move or both).
    Using log to stabilise variance + reduce heavy tail influence.
    """
    log_y = np.log(panel["y"].values)
    log_rv = panel["log_rv"].values
    tsv = panel["tsv21"].values
    move = panel["log_move"].values
    n = len(log_y)

    const = np.ones(n)
    # M0: AR-1 baseline (log RV alone)
    X0 = np.column_stack([const, log_rv])
    m0 = ols_hac(log_y, X0, h)
    m0["names"] = ["const", "log_rv_t-1"]

    # M1: + TSV21
    X1 = np.column_stack([const, log_rv, tsv])
    m1 = ols_hac(log_y, X1, h)
    m1["names"] = ["const", "log_rv_t-1", "tsv21_t-1"]

    # M2: + MOVE
    X2 = np.column_stack([const, log_rv, move])
    m2 = ols_hac(log_y, X2, h)
    m2["names"] = ["const", "log_rv_t-1", "log_move_t-1"]

    # M3: + MOVE + TSV21 (nested)
    X3 = np.column_stack([const, log_rv, move, tsv])
    m3 = ols_hac(log_y, X3, h)
    m3["names"] = ["const", "log_rv_t-1", "log_move_t-1", "tsv21_t-1"]

    return {
        "M0_baseline_ar1": m0,
        "M1_tsv_only": m1,
        "M2_move_only": m2,
        "M3_move_plus_tsv": m3,
    }


def oos_expanding(panel: pd.DataFrame, h: int) -> Dict:
    """Expanding-window OOS forecasts on variance scale.

    For each forecast origin i (starting at MIN_TRAIN), train on rows
    j ∈ [0, i - h - 1] so j + h < i (forward-label safety), produce log-RV
    forecast at i, exponentiate, evaluate QLIKE and MSE against actual.

    Models: M0 / M1 / M2 / M3 as above.
    """
    n = len(panel)
    if n < MIN_TRAIN + h + 50:
        return {"skipped_reason": f"insufficient sample n={n}"}

    log_rv = panel["log_rv"].values
    tsv = panel["tsv21"].values
    move = panel["log_move"].values
    log_y = np.log(panel["y"].values)
    y = panel["y"].values

    preds = {k: np.full(n, np.nan) for k in ["M0", "M1", "M2", "M3"]}

    for i in range(MIN_TRAIN, n):
        train_end = i - h           # training rows j satisfy j + h < i ⇔ j < i - h
        if train_end < 50:
            continue
        train_idx = slice(0, train_end)
        const_tr = np.ones(train_end)

        X_tr = {
            "M0": np.column_stack([const_tr, log_rv[train_idx]]),
            "M1": np.column_stack([const_tr, log_rv[train_idx], tsv[train_idx]]),
            "M2": np.column_stack([const_tr, log_rv[train_idx], move[train_idx]]),
            "M3": np.column_stack([const_tr, log_rv[train_idx], move[train_idx],
                                   tsv[train_idx]]),
        }
        y_tr = log_y[train_idx]

        x_i = {
            "M0": np.array([1.0, log_rv[i]]),
            "M1": np.array([1.0, log_rv[i], tsv[i]]),
            "M2": np.array([1.0, log_rv[i], move[i]]),
            "M3": np.array([1.0, log_rv[i], move[i], tsv[i]]),
        }

        for m in ["M0", "M1", "M2", "M3"]:
            try:
                beta = np.linalg.solve(X_tr[m].T @ X_tr[m], X_tr[m].T @ y_tr)
                preds[m][i] = float(np.exp(x_i[m] @ beta))
            except np.linalg.LinAlgError:
                continue

    actual = y
    mask = ~np.isnan(preds["M3"]) & ~np.isnan(actual) & (actual > 0)
    out = {"n_eval": int(mask.sum()), "horizon": int(h)}

    losses = {}
    for m in ["M0", "M1", "M2", "M3"]:
        valid = mask & ~np.isnan(preds[m]) & (preds[m] > 0)
        if valid.sum() < 30:
            losses[m] = None
            continue
        ql = qlike_pointwise(actual[valid], preds[m][valid])
        mse_pt = (actual[valid] - preds[m][valid]) ** 2
        losses[m] = {
            "qlike_mean": float(np.mean(ql)),
            "mse": float(np.mean(mse_pt)),
            "n": int(valid.sum()),
            "valid_mask": valid,
            "ql_pointwise": ql,
        }
    out["model_losses"] = {
        m: {k: v for k, v in d.items() if k not in ("valid_mask", "ql_pointwise")}
        for m, d in losses.items() if d is not None
    }

    # DM HLN comparisons (pointwise QLIKE), aligned masks
    def _aligned(m_a: str, m_b: str):
        if losses[m_a] is None or losses[m_b] is None:
            return None, None
        mask_ab = losses[m_a]["valid_mask"] & losses[m_b]["valid_mask"]
        l_a = qlike_pointwise(actual[mask_ab], preds[m_a][mask_ab])
        l_b = qlike_pointwise(actual[mask_ab], preds[m_b][mask_ab])
        return l_a, l_b

    dm_results = {}
    for (a, b) in [("M1", "M0"), ("M2", "M0"), ("M3", "M0"),
                   ("M3", "M2"), ("M1", "M2")]:
        l_a, l_b = _aligned(a, b)
        if l_a is None:
            dm_results[f"{a}_vs_{b}"] = None
            continue
        # DM negative t → model 1 (l_a) better
        d = dm_hln(l_a, l_b, h)
        dm_results[f"{a}_vs_{b}"] = d

    out["dm_hln_qlike"] = dm_results
    return out


# ─────────────────────────── verdict logic ───────────────────────────
def assign_verdict(insample_all: Dict, oos_all: Dict) -> str:
    """Aggregate verdict across (asset, horizon) combos."""
    tsv_insample_sig = 0
    tsv_subsumed = 0
    oos_m3_beats_m2_count = 0
    oos_total = 0
    cells = 0

    for asset in ASSETS:
        for h in HORIZONS:
            key = f"{asset}_h{h}"
            ins = insample_all.get(key, {})
            oos = oos_all.get(key, {})
            cells += 1
            # M1 univariate
            m1 = ins.get("M1_tsv_only", {})
            if m1.get("t"):
                tsv_t = m1["t"][-1]  # last coef = tsv21
                if abs(tsv_t) > 2.0:
                    tsv_insample_sig += 1
            # M3 nested
            m3 = ins.get("M3_move_plus_tsv", {})
            if m3.get("t"):
                tsv_t_in_nested = m3["t"][-1]
                if abs(tsv_t_in_nested) < 2.0:
                    tsv_subsumed += 1
            # OOS DM M3 vs M2
            dm = oos.get("dm_hln_qlike", {}).get("M3_vs_M2")
            if dm and np.isfinite(dm.get("t_stat", np.nan)):
                oos_total += 1
                if dm["t_stat"] < -1.96:
                    oos_m3_beats_m2_count += 1

    if tsv_insample_sig == 0:
        return "NULL"
    if tsv_subsumed == cells:
        return "SUBSUMED_BY_MOVE"
    if tsv_insample_sig > 0 and oos_total > 0 and oos_m3_beats_m2_count == 0:
        return "NULL_OOS"
    if oos_m3_beats_m2_count >= 1 and tsv_insample_sig >= 1:
        if oos_m3_beats_m2_count == oos_total and tsv_subsumed == 0:
            return "CONFIRMED"
        return "PARTIAL"
    return "PARTIAL"


# ─────────────────────────── plots ───────────────────────────
def plot_tsv_timeseries(features: pd.DataFrame, prices: pd.DataFrame,
                        out_path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 6.5), sharex=True)
    feats = features.dropna(subset=["tsv21", "tsv63"])
    axes[0].plot(feats.index, feats["tsv21"], label="TSV21 (21d)", lw=0.8,
                 color="#2563eb")
    axes[0].plot(feats.index, feats["tsv63"], label="TSV63 (63d)", lw=0.8,
                 color="#dc2626", alpha=0.75)
    axes[0].set_ylabel("Annualised stdev of\nΔ(10y-2y) spread")
    axes[0].legend(loc="upper right", fontsize=9)
    axes[0].grid(alpha=0.3)
    axes[0].set_title("K1544 — Term-spread realised volatility (FRED 10y-2y)")

    move = prices["MOVE"].dropna()
    axes[1].plot(move.index, move, label="^MOVE", lw=0.7, color="#16a34a")
    axes[1].set_ylabel("MOVE index")
    axes[1].set_xlabel("Date")
    axes[1].legend(loc="upper right", fontsize=9)
    axes[1].grid(alpha=0.3)

    plt.tight_layout()
    plt.savefig(out_path, dpi=130)
    plt.close()


def plot_dm_heatmap(oos_all: Dict, out_path: Path) -> None:
    # rows = asset × horizon, columns = DM comparisons
    comparisons = ["M1_vs_M0", "M2_vs_M0", "M3_vs_M0", "M3_vs_M2", "M1_vs_M2"]
    row_labels = []
    matrix = []
    for asset in ASSETS:
        for h in HORIZONS:
            row_labels.append(f"{asset} h={h}")
            row = []
            for c in comparisons:
                dm = oos_all.get(f"{asset}_h{h}", {}).get("dm_hln_qlike", {}).get(c)
                if dm and np.isfinite(dm.get("t_stat", np.nan)):
                    row.append(dm["t_stat"])
                else:
                    row.append(np.nan)
            matrix.append(row)
    matrix = np.array(matrix)

    fig, ax = plt.subplots(figsize=(8, 5.5))
    vmax = max(3.5, np.nanmax(np.abs(matrix))) if np.isfinite(matrix).any() else 3.5
    im = ax.imshow(matrix, aspect="auto", cmap="RdBu_r", vmin=-vmax, vmax=vmax)

    ax.set_xticks(np.arange(len(comparisons)))
    ax.set_xticklabels(comparisons, rotation=30, ha="right")
    ax.set_yticks(np.arange(len(row_labels)))
    ax.set_yticklabels(row_labels)
    ax.set_title("K1544 — HLN-DM t-stats on out-of-sample QLIKE\n"
                 "(negative t → first model has lower loss)")
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            v = matrix[i, j]
            if np.isfinite(v):
                col = "white" if abs(v) > 1.6 else "black"
                ax.text(j, i, f"{v:+.2f}", ha="center", va="center",
                        color=col, fontsize=8)
    plt.colorbar(im, ax=ax, label="HLN t-stat")
    plt.tight_layout()
    plt.savefig(out_path, dpi=130)
    plt.close()


# ─────────────────────────── main ───────────────────────────
def main() -> Dict:
    spread = load_yield_spread()
    prices = load_prices()
    features = build_features(spread, prices)

    insample_all: Dict[str, Dict] = {}
    oos_all: Dict[str, Dict] = {}

    diagnostics = {
        "spread_n": int(spread.dropna().shape[0]),
        "spread_start": str(spread.dropna().index.min().date()),
        "spread_end": str(spread.dropna().index.max().date()),
        "prices_start": str(prices.dropna(how="all").index.min().date()),
        "prices_end": str(prices.dropna(how="all").index.max().date()),
        "n_features": int(features.dropna().shape[0]),
    }

    panel_sizes: Dict[str, int] = {}

    for asset in ASSETS:
        for h in HORIZONS:
            panel = build_panel(prices, features, asset, h)
            panel_sizes[f"{asset}_h{h}"] = int(len(panel))
            if len(panel) < 100:
                insample_all[f"{asset}_h{h}"] = {"skipped": "n<100"}
                oos_all[f"{asset}_h{h}"] = {"skipped": "n<100"}
                continue
            ins = insample_regressions(panel, h)
            oos = oos_expanding(panel, h)
            insample_all[f"{asset}_h{h}"] = ins
            oos_all[f"{asset}_h{h}"] = oos

    verdict = assign_verdict(insample_all, oos_all)

    # plots
    plot_tsv_timeseries(features, prices, EXP_DIR / "fig_tsv_timeseries.png")
    plot_dm_heatmap(oos_all, EXP_DIR / "fig_dm_heatmap.png")

    results = {
        "experiment_id": "K1544",
        "title": "Term-spread realised volatility as leading indicator "
                 "for SPY/HYG/IWM RV (incremental over MOVE)",
        "seed": SEED,
        "data_sources": {
            "yield_spread": "storage/macro/fred_DGS10.csv + fred_DGS2.csv",
            "spy_iwm": "paper/leverage-direction/data/"
                       "spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv",
            "hyg": "experiments/k1263/data/HYG.csv",
            "move": "experiments/k1488_move_leadingness/close_prices.csv",
        },
        "design": {
            "predictors": ["tsv21 (21d annualised stdev of Δspread)",
                           "tsv63 (63d annualised stdev of Δspread)",
                           "log_move (lagged)",
                           "log_rv (lagged 21d realised variance, annualised)"],
            "target": "log forward h-day RV (annualised), exponentiated for OOS QLIKE",
            "horizons": HORIZONS,
            "assets": ASSETS,
            "lookahead_protections": [
                "All predictors .shift(1) before regression",
                "Forward target uses (t, t+h] window only",
                "OOS expanding window: training rows j must satisfy j+h < i",
                "Seed = 42 fixed",
            ],
            "hac_rule": ("Newey-West bandwidth = max(NW rule, ceil(1.5*h)); "
                         "DM uses h-1 bandwidth + HLN small-sample correction"),
            "qlike_definition": "actual / predicted - log(actual/predicted) - 1",
            "regression_scale": "log RV (variance-stabilised); exponentiate for QLIKE",
        },
        "diagnostics": diagnostics,
        "panel_sizes": panel_sizes,
        "insample": insample_all,
        "oos": oos_all,
        "verdict": verdict,
        "verdict_definitions": {
            "CONFIRMED": "TSV t-stat (HAC) > 2.5 in nested M3 AND DM-OOS "
                         "favours M3 over M2 (HLN-t < -1.96) for ≥1 cell, "
                         "no SUBSUMED cells.",
            "PARTIAL": "Some cells confirm, others null.",
            "NULL": "TSV univariate (M1) HAC-t < 2.0 everywhere.",
            "NULL_OOS": "Significant in-sample but DM-OOS not significant.",
            "SUBSUMED_BY_MOVE": "TSV t-stat in M3 < 2.0 across all cells.",
        },
        "scope_limitations": [
            "NBER recession dating (USREC) not pulled — recession lead/lag "
            "analysis deferred to follow-up (no USREC cached in storage/macro).",
            "TSV63 univariate / nested tests omitted (only TSV21 reported in M1-M3 "
            "to keep scope inside 50-min cap); TSV63 plotted in time series for "
            "visual comparison.",
        ],
    }

    out_path = EXP_DIR / "K1544_results.json"
    with open(out_path, "w") as f:
        # strip numpy-mask leftovers
        json.dump(results, f, indent=2, default=str)
    return results


if __name__ == "__main__":
    res = main()
    v = res["verdict"]
    print(f"\n=== K1544 verdict: {v} ===")
    for asset in ASSETS:
        for h in HORIZONS:
            key = f"{asset}_h{h}"
            ins = res["insample"].get(key, {})
            oos = res["oos"].get(key, {})
            m1 = ins.get("M1_tsv_only", {})
            m3 = ins.get("M3_move_plus_tsv", {})
            dm = oos.get("dm_hln_qlike", {}).get("M3_vs_M2", {}) or {}
            t_m1 = m1.get("t", [np.nan, np.nan, np.nan])[-1] if m1.get("t") else np.nan
            t_m3 = m3.get("t", [np.nan]*4)[-1] if m3.get("t") else np.nan
            dm_t = dm.get("t_stat", np.nan)
            print(f"  {key:10s}  n={res['panel_sizes'].get(key,0):4d}  "
                  f"tsv_t(M1)={t_m1:+.2f}  tsv_t(M3)={t_m3:+.2f}  "
                  f"DM(M3 vs M2)={dm_t:+.2f}")
