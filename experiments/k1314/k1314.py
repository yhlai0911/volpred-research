"""K1314 — Graph Signal Processing HAR (GSP-HAR) honest replication test.

Tests whether a simplified GSP augmentation to standard HAR(1,5,22) produces
Harvey-significant QLIKE improvement vs baseline HAR on a 5-US-ETF panel.

Lookahead-safe by construction:
- All HAR features use rv shifted by 1.
- Graph correlation uses expanding window strictly < t.
- Walk-forward expanding-window OLS refit per day on OOS.

Run: python k1314.py
"""
from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SEED = 42
TICKERS = ["SPY", "QQQ", "GLD", "TLT", "IWM"]
START = "2005-01-01"
END = "2024-12-31"
OOS_START = "2020-01-01"
TAU = 1.0  # heat-kernel diffusion time (fixed, not tuned)
K_NN = 2  # top-k neighbours per node
OUT_DIR = Path(__file__).parent

np.random.seed(SEED)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def fetch_rv() -> pd.DataFrame:
    """Daily squared log returns per ticker (RV proxy)."""
    px = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=False,
        progress=False,
        group_by="ticker",
    )
    closes = pd.DataFrame({t: px[t]["Close"] for t in TICKERS})
    closes = closes.dropna(how="any")
    log_ret = np.log(closes / closes.shift(1))
    rv = (log_ret ** 2).dropna()
    return rv


# ---------------------------------------------------------------------------
# Graph construction (lookahead-safe)
# ---------------------------------------------------------------------------
def build_graph_filter(rv_history: pd.DataFrame, tau: float = TAU, k: int = K_NN) -> np.ndarray:
    """Heat-kernel low-pass filter on top-k Pearson graph.

    rv_history: DataFrame of RV up to t-1 (strictly past).
    Returns: (N, N) filter matrix H = exp(-tau * L).
    """
    corr = rv_history.corr().abs().to_numpy(copy=True)
    n = corr.shape[0]
    np.fill_diagonal(corr, 0.0)
    A = np.zeros_like(corr)
    for i in range(n):
        # top-k by |corr|
        idx = np.argsort(-corr[i])[:k]
        for j in idx:
            A[i, j] = corr[i, j]
    A = 0.5 * (A + A.T)  # symmetrize
    deg = A.sum(axis=1)
    deg_inv_sqrt = np.where(deg > 0, 1.0 / np.sqrt(deg), 0.0)
    D_inv_sqrt = np.diag(deg_inv_sqrt)
    L = np.eye(n) - D_inv_sqrt @ A @ D_inv_sqrt
    # heat kernel via eigendecomp (5x5, trivial)
    w, V = np.linalg.eigh(L)
    H = V @ np.diag(np.exp(-tau * w)) @ V.T
    return H


# ---------------------------------------------------------------------------
# HAR feature builders (all lookahead-safe)
# ---------------------------------------------------------------------------
def har_features(rv: pd.Series) -> pd.DataFrame:
    """Standard HAR(1,5,22) features using rv shifted by 1.

    Target is rv_t; features use rv_{t-1}, mean(rv_{t-5..t-1}), mean(rv_{t-22..t-1}).
    """
    rv_lag = rv.shift(1)
    daily = rv_lag
    weekly = rv_lag.rolling(5).mean()
    monthly = rv_lag.rolling(22).mean()
    feats = pd.DataFrame({"d": daily, "w": weekly, "m": monthly})
    return feats


def gsp_features(rv: pd.DataFrame, asset: str, oos_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Build GSP-filtered HAR features for one asset.

    For each date t in oos_index, compute graph filter H_t from RV strictly < t,
    apply to RV vectors at relevant lags, take asset-i component.
    """
    n_assets = rv.shape[1]
    asset_idx = list(rv.columns).index(asset)
    # For efficiency, also need graph at training-set dates. We'll compute on every date.
    all_dates = rv.index
    # Pre-compute filters for dates we need (training + oos). Use a coarse cadence:
    # refit graph every 21 trading days (monthly) — speeds up by ~21x vs daily and
    # avoids overfitting to short-horizon noise.
    REFIT_EVERY = 21
    filters: dict[pd.Timestamp, np.ndarray] = {}
    # need at least 60 obs for stable correlation
    MIN_HIST = 60
    last_filter = None
    for i, dt in enumerate(all_dates):
        if i < MIN_HIST:
            continue
        if (i - MIN_HIST) % REFIT_EVERY == 0 or last_filter is None:
            past = rv.iloc[:i]  # strictly < t  (note: rv.iloc[:i] excludes row i)
            H = build_graph_filter(past)
            last_filter = H
        filters[dt] = last_filter

    # Apply filter per date to lagged RV vectors
    rv_lag1 = rv.shift(1)
    rv_lag5 = rv.shift(1).rolling(5).mean()
    rv_lag22 = rv.shift(1).rolling(22).mean()

    gsp_d = pd.Series(index=all_dates, dtype=float)
    gsp_w = pd.Series(index=all_dates, dtype=float)
    gsp_m = pd.Series(index=all_dates, dtype=float)
    for dt in all_dates:
        if dt not in filters:
            continue
        H = filters[dt]
        v_d = rv_lag1.loc[dt].values
        v_w = rv_lag5.loc[dt].values
        v_m = rv_lag22.loc[dt].values
        if np.any(np.isnan(v_d)) or np.any(np.isnan(v_w)) or np.any(np.isnan(v_m)):
            continue
        gsp_d.loc[dt] = (H @ v_d)[asset_idx]
        gsp_w.loc[dt] = (H @ v_w)[asset_idx]
        gsp_m.loc[dt] = (H @ v_m)[asset_idx]

    return pd.DataFrame({"gsp_d": gsp_d, "gsp_w": gsp_w, "gsp_m": gsp_m})


# ---------------------------------------------------------------------------
# Walk-forward OLS prediction
# ---------------------------------------------------------------------------
def walk_forward_predict(
    X: pd.DataFrame, y: pd.Series, oos_start: pd.Timestamp, log_target: bool = True
) -> pd.Series:
    """Expanding-window OLS in log-RV space (Corsi 2009 standard), refit each OOS date.

    log_target=True: estimate log(rv) = X β; predict rv = exp(Xβ) (enforces positivity).
    log_target=False: linear OLS on rv (legacy; can produce negative preds, QLIKE-unsafe).
    """
    Xc = X.copy()
    Xc.insert(0, "const", 1.0)
    eps = 1e-12
    if log_target:
        y_use = np.log(y.clip(lower=eps))
    else:
        y_use = y
    full = pd.concat([Xc, y_use.rename("y")], axis=1).dropna()
    oos_idx = full.index[full.index >= oos_start]
    preds = pd.Series(index=oos_idx, dtype=float)
    for dt in oos_idx:
        train = full.loc[full.index < dt]
        if len(train) < 50:
            continue
        Xtr = train.drop(columns="y").values
        ytr = train["y"].values
        beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
        xt = full.loc[dt].drop("y").values
        yhat = float(xt @ beta)
        if log_target:
            # clip to avoid overflow at extreme predictions
            yhat = float(np.exp(np.clip(yhat, -30.0, 5.0)))
        preds.loc[dt] = yhat
    return preds


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
def qlike(y_true: np.ndarray, y_pred: np.ndarray, eps: float = 1e-12) -> np.ndarray:
    """Patton (2011) QLIKE per observation. Lower is better."""
    yt = np.maximum(y_true, eps)
    yp = np.maximum(y_pred, eps)
    r = yt / yp
    return r - np.log(r) - 1.0


def newey_west_se(x: np.ndarray) -> float:
    """HAC SE of mean (Newey-West, bandwidth = floor(n^(1/3)))."""
    n = len(x)
    if n < 5:
        return float("nan")
    L = max(1, int(np.floor(n ** (1 / 3))))
    xd = x - x.mean()
    gamma0 = (xd * xd).sum() / n
    var = gamma0
    for k in range(1, L + 1):
        w = 1.0 - k / (L + 1.0)
        cov = (xd[k:] * xd[:-k]).sum() / n
        var += 2.0 * w * cov
    var = max(var, 0.0)
    return float(np.sqrt(var / n))


def dm_hln_test(d: np.ndarray, h: int = 1) -> dict:
    """Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample correction.

    d_t = loss_baseline_t - loss_alt_t. Positive mean d favours alt.
    """
    d = np.asarray(d, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 5:
        return {"t_stat": float("nan"), "p_value": float("nan"), "n": n}
    se = newey_west_se(d)
    if not np.isfinite(se) or se <= 0:
        return {"t_stat": float("nan"), "p_value": float("nan"), "n": n}
    dm = d.mean() / se
    # HLN correction
    correction = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_hln = dm * correction
    p = 2.0 * (1.0 - stats.t.cdf(abs(t_hln), df=n - 1))
    return {
        "t_stat": float(t_hln),
        "p_value": float(p),
        "n": int(n),
        "mean_d": float(d.mean()),
        "hac_se": float(se),
    }


def multiple_testing_adjustments(p_values: dict[str, float]) -> dict[str, dict[str, float]]:
    """Bonferroni, Holm, and Benjamini-Hochberg adjusted p-values.

    Family is the five per-asset DM-HLN tests. Non-finite p-values remain NaN.
    """
    finite = [(k, float(v)) for k, v in p_values.items() if np.isfinite(v)]
    m = len(finite)
    out = {
        k: {
            "p_value_bonferroni": float("nan"),
            "p_value_holm": float("nan"),
            "p_value_bh_fdr": float("nan"),
        }
        for k in p_values
    }
    if m == 0:
        return out

    for k, p in finite:
        out[k]["p_value_bonferroni"] = float(min(p * m, 1.0))

    ordered = sorted(finite, key=lambda kv: kv[1])
    running_max = 0.0
    for rank, (k, p) in enumerate(ordered, start=1):
        adj = min((m - rank + 1) * p, 1.0)
        running_max = max(running_max, adj)
        out[k]["p_value_holm"] = float(running_max)

    raw_bh = []
    for rank, (k, p) in enumerate(ordered, start=1):
        raw_bh.append((k, min(p * m / rank, 1.0)))
    running_min = 1.0
    for k, adj in reversed(raw_bh):
        running_min = min(running_min, adj)
        out[k]["p_value_bh_fdr"] = float(running_min)

    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print(f"[K1314] start {datetime.now(timezone.utc).isoformat()}")
    print("[K1314] fetching data...")
    rv = fetch_rv()
    print(f"[K1314] rv shape {rv.shape}, period {rv.index[0].date()} .. {rv.index[-1].date()}")

    oos_start_ts = pd.Timestamp(OOS_START)
    results_per_asset: dict[str, dict] = {}
    series_for_chart: dict[str, dict] = {}
    stacked_d_list: list[np.ndarray] = []
    cross_qlike_base: list[float] = []
    cross_qlike_gsp: list[float] = []

    for ticker in TICKERS:
        print(f"\n[K1314] === {ticker} ===")
        y = rv[ticker]
        base_X = har_features(y)
        print(f"[K1314] building GSP features for {ticker} ...")
        gsp_X = gsp_features(rv, ticker, rv.index[rv.index >= oos_start_ts])
        full_X = pd.concat([base_X, gsp_X], axis=1)

        print(f"[K1314] walk-forward baseline HAR ...")
        pred_base = walk_forward_predict(base_X, y, oos_start_ts)
        print(f"[K1314] walk-forward GSP-HAR ...")
        pred_gsp = walk_forward_predict(full_X, y, oos_start_ts)

        aligned = pd.concat(
            [y.rename("y"), pred_base.rename("base"), pred_gsp.rename("gsp")], axis=1
        ).dropna()
        if len(aligned) < 100:
            print(f"[K1314] WARN: only {len(aligned)} OOS obs for {ticker}")

        q_base = qlike(aligned["y"].values, aligned["base"].values)
        q_gsp = qlike(aligned["y"].values, aligned["gsp"].values)
        d_loss = q_base - q_gsp  # positive means gsp better
        stacked_d_list.append(d_loss)
        cross_qlike_base.append(float(np.mean(q_base)))
        cross_qlike_gsp.append(float(np.mean(q_gsp)))

        dm = dm_hln_test(d_loss)
        results_per_asset[ticker] = {
            "n_oos": int(len(aligned)),
            "qlike_baseline": float(np.mean(q_base)),
            "qlike_gsp": float(np.mean(q_gsp)),
            "qlike_improvement_pct": float(
                100.0 * (np.mean(q_base) - np.mean(q_gsp)) / np.mean(q_base)
            ),
            "dm_hln": dm,
            "rv_mean": float(aligned["y"].mean()),
            "rv_std": float(aligned["y"].std()),
        }
        series_for_chart[ticker] = {
            "qlike_baseline": float(np.mean(q_base)),
            "qlike_gsp": float(np.mean(q_gsp)),
        }
        print(
            f"[K1314] {ticker} QLIKE base={np.mean(q_base):.6e} gsp={np.mean(q_gsp):.6e} "
            f"DM t={dm['t_stat']:.3f} p={dm['p_value']:.4f}"
        )

    p_raw = {t: results_per_asset[t]["dm_hln"]["p_value"] for t in TICKERS}
    p_adjusted = multiple_testing_adjustments(p_raw)
    for ticker in TICKERS:
        adj = p_adjusted[ticker]
        results_per_asset[ticker]["dm_hln"].update(
            {
                **adj,
                "reject_5pct_raw": bool(results_per_asset[ticker]["dm_hln"]["p_value"] < 0.05),
                "reject_5pct_bonferroni": bool(adj["p_value_bonferroni"] < 0.05),
                "reject_5pct_holm": bool(adj["p_value_holm"] < 0.05),
                "reject_5pct_bh_fdr": bool(adj["p_value_bh_fdr"] < 0.05),
                "multiple_testing_family": "5 per-asset DM-HLN tests",
            }
        )

    pooled = np.concatenate(stacked_d_list)
    pooled_dm = dm_hln_test(pooled)

    cross_avg = {
        "qlike_baseline_avg": float(np.mean(cross_qlike_base)),
        "qlike_gsp_avg": float(np.mean(cross_qlike_gsp)),
        "qlike_improvement_pct_avg": float(
            100.0 * (np.mean(cross_qlike_base) - np.mean(cross_qlike_gsp))
            / np.mean(cross_qlike_base)
        ),
        "pooled_dm_hln": pooled_dm,
    }

    # Verdict
    sig_count = sum(
        1
        for t in TICKERS
        if np.isfinite(results_per_asset[t]["dm_hln"]["t_stat"])
        and results_per_asset[t]["dm_hln"]["t_stat"] > 3.0
    )
    if sig_count >= 3:
        verdict = "PASS_HARVEY"
    elif sig_count >= 1 or (
        np.isfinite(pooled_dm["t_stat"]) and pooled_dm["t_stat"] > 1.96
    ):
        verdict = "MARGINAL"
    else:
        verdict = "NULL"

    # Optional: load placebo results if k1314_placebo_results.json exists
    placebo_summary = None
    placebo_path = OUT_DIR / "k1314_placebo_results.json"
    if placebo_path.exists():
        try:
            placebo = json.loads(placebo_path.read_text())
            placebo_summary = {
                "ran_at": placebo.get("run_at_utc"),
                "note": (
                    "Random-graph placebo regression. If placebo also shows t>3 in same "
                    "asset, that asset's GSP-HAR gain is likely from extra-regressor noise, "
                    "not graph-signal info."
                ),
                "per_asset": {
                    t: {
                        "dm_t_stat": d["dm_hln"]["t_stat"],
                        "improvement_pct": d["improvement_pct"],
                    }
                    for t, d in placebo.get(
                        "single_seed_reference", placebo.get("per_asset", {})
                    ).items()
                },
                "permutation_tests": placebo.get("permutation_tests"),
            }
        except Exception as e:
            placebo_summary = {"error": str(e)}

    # Refine verdict using placebo
    final_verdict = verdict
    placebo_warning = None
    if placebo_summary and "per_asset" in placebo_summary:
        # Count assets where main t > 3 AND main t > placebo t + 1.0
        robust_passes = []
        for t in TICKERS:
            main_t = results_per_asset[t]["dm_hln"]["t_stat"]
            plc_t = placebo_summary["per_asset"][t]["dm_t_stat"]
            if (
                np.isfinite(main_t)
                and np.isfinite(plc_t)
                and main_t > 3.0
                and main_t > plc_t + 1.0
            ):
                robust_passes.append(t)
        if not robust_passes and verdict != "NULL":
            placebo_warning = (
                "Placebo random graph achieves similar / better DM in some assets — "
                "main result MARGINAL may reflect extra-regressor fitting rather than "
                "graph-signal information. Verdict downgraded."
            )
            final_verdict = "MARGINAL_PLACEBO_INCONCLUSIVE"
        elif robust_passes:
            placebo_warning = f"Survives single-seed placebo in: {robust_passes}."
        spy_perm = (placebo_summary.get("permutation_tests") or {}).get("SPY")
        if spy_perm:
            p_perm = spy_perm["random_distribution"][
                "p_value_ge_observed_improvement_pct"
            ]
            if np.isfinite(p_perm) and p_perm < 0.01:
                placebo_warning = (
                    "SPY survives 100-seed random-graph permutation placebo "
                    f"(empirical p={p_perm:.4f}); other assets remain non-robust."
                )
            elif np.isfinite(p_perm):
                placebo_warning = (
                    "SPY does not pass the pre-registered p<0.01 permutation placebo "
                    f"gate (empirical p={p_perm:.4f})."
                )

    out = {
        "experiment_id": "k1314",
        "title": "Graph Signal Processing HAR (GSP-HAR) honest replication test",
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "config": {
            "tickers": TICKERS,
            "period": {"start": START, "end": END, "oos_start": OOS_START},
            "rv_proxy": "daily squared log return",
            "graph": {"k_nn": K_NN, "tau_heat_kernel": TAU, "refit_every_days": 21},
            "seed": SEED,
        },
        "per_asset": results_per_asset,
        "cross_asset": cross_avg,
        "multiple_testing_adjustment": {
            "family": "5 per-asset DM-HLN tests",
            "methods": ["Bonferroni", "Holm", "Benjamini-Hochberg FDR"],
            "alpha": 0.05,
            "note": (
                "Adjusted p-values are annotations for the per-asset DM table. "
                "QLIKE improvement percentages are raw effect sizes, not p-values."
            ),
        },
        "verdict_raw": verdict,
        "verdict": final_verdict,
        "verdict_definition": {
            "PASS_HARVEY": ">=3/5 assets DM-HLN t > 3.0 in favour of GSP",
            "MARGINAL": ">=1/5 asset t>3 OR pooled t>1.96",
            "NULL": "neither",
            "MARGINAL_PLACEBO_INCONCLUSIVE": (
                "MARGINAL by raw DM but random-graph placebo achieves comparable "
                "improvement — gain likely from extra regressors, not graph info."
            ),
        },
        "placebo": placebo_summary,
        "placebo_warning": placebo_warning,
        "lookahead_free_certification": {
            "har_features_use_shift_1": True,
            "graph_correlation_strictly_past": True,
            "walk_forward_expanding_window": True,
            "oos_refit_per_day": True,
            "seed_fixed": SEED,
            "notes": (
                "All HAR regressors built from rv.shift(1) and earlier rolling means. "
                "Graph filter at date t built from rv.iloc[:i] where i is positional index "
                "of t, which excludes row t (strictly past). Walk-forward OLS uses "
                "train = full.loc[full.index < dt]."
            ),
        },
        "deviations_from_paper": {
            "graph_adjacency": "Pearson top-2 k-NN (paper uses DY framework + abs Pearson)",
            "filter": "heat kernel exp(-tau*L) fixed tau=1.0 (paper uses magnetic Laplacian + learned convex weights)",
            "domain": "spatial only (paper does real+imag GFT with NN fusion)",
            "universe": "5 US ETFs (paper uses 24 global indices)",
            "rv_proxy": "daily squared log return (paper uses 5-min realized variance)",
            "rationale": "tests core GSP idea without architectural confounds; simpler bar = harder to over-claim",
        },
        "references": [
            "Yan H. et al. (2024) arXiv:2410.22706 GSP-HAR",
            "Corsi F. (2009) JFE HAR-RV",
            "Patton A. (2011) JoE robust loss functions",
            "Harvey D., Leybourne S., Newbold P. (1997) IJoF DM small-sample",
            "Holm S. (1979) Scandinavian Journal of Statistics sequential Bonferroni",
            "Benjamini Y., Hochberg Y. (1995) JRSS-B false discovery rate",
        ],
    }
    out_path = OUT_DIR / "k1314_results.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n[K1314] verdict={verdict}  written -> {out_path}")

    # ---------------- chart ----------------
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x = np.arange(len(TICKERS))
    w = 0.38
    qb = [series_for_chart[t]["qlike_baseline"] for t in TICKERS]
    qg = [series_for_chart[t]["qlike_gsp"] for t in TICKERS]
    ax.bar(x - w / 2, qb, w, label="HAR baseline", color="#888888")
    ax.bar(x + w / 2, qg, w, label="GSP-HAR", color="#1f77b4")
    ax.set_xticks(x)
    ax.set_xticklabels(TICKERS)
    ax.set_ylabel("OOS QLIKE (lower=better)")
    ax.set_title(f"K1314 GSP-HAR vs HAR (OOS 2020-2024) — verdict: {verdict}")
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    chart_path = OUT_DIR / "k1314_qlike_chart.png"
    fig.savefig(chart_path, dpi=140)
    plt.close(fig)
    print(f"[K1314] chart -> {chart_path}")


if __name__ == "__main__":
    main()
