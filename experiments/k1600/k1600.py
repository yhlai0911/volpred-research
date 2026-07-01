"""K1600: HARQ-proxy — low-frequency proxy of measurement-error-corrected HAR.

Honest low-frequency proxy test of HARQ (Bollerslev, Patton & Quaedvlieg,
Journal of Econometrics 2016, "Exploiting the errors: A simple approach for
improved volatility forecasting"). True HARQ uses intraday realized quarticity
(RQ) to let the HAR daily-lag coefficient shrink when the daily RV measurement
is noisy:

    RV_{t+h} = beta0 + (beta1 + beta1Q * sqrt(RQ_t)) * RV_d,t
                     + beta2 * RV_w,t + beta3 * RV_m,t + eps

HONEST DATA REALITY (this is the defining framing of the experiment):
    This repo has NO long-sample intraday RV+RQ panel. Clean intraday is only
    ~115 days of SPY 5-min bars (2026-01 onward) — far below the >=500-sample
    rigor bar, so credible intraday HARQ inference is infeasible here.
    Following the repo honest-proxy convention (same as K1520/k1523), we build
    RV and RQ proxies from DAILY log returns over a long sample (2010-2026,
    OOS n >> 3000, Harvey-significant inference feasible), and test whether a
    HARQ-type measurement-error correction improves the HAR proxy forecast.

    A daily-return quarticity proxy is a WEAK analog of intraday RQ. A NULL
    result is fully acceptable and a legitimate contribution: if the proxy is
    too coarse to carry the measurement-error signal, we report that honestly.
    This is NOT a claim about true intraday HARQ.

Assets: SPY, QQQ, 0050.TW — each estimated & reported independently, NO pooling
(experiments.md K1355 rule: cross-asset pooled inference must not treat
asset-days as iid).

Methodology hard rules respected:
- Lookahead: every regressor is known by close of day t; target is forward-only.
  Forward-label timing enforced per experiments.md: for horizon h, a training
  row j is kept only if its label window ends strictly before the forecast
  origin i, i.e. j + h < i (target_end_pos < forecast_pos).
- Per-horizon DM: each target h uses its OWN inference horizon h (never share
  one DM horizon across horizons). HLN (Harvey-Leybourne-Newbold 1997)
  small-sample correction + Newey-West HAC(h-1).
- QLIKE: canonical volpred.stats.model_evaluation.qlike_pointwise (actual/pred),
  never hand-written inverse QLIKE (K783c lesson).
- 0050.TW: cleaned via volpred.utils.clean_tw50_data (split-artifact fix).
- Seed: numpy seed=42 fixed for all stochastic steps.

Author: K1600 experiment, 2026-07-01
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

from volpred.stats.model_evaluation import qlike_pointwise
from volpred.utils import clean_tw50_data

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

START = "2010-01-01"
END = "2026-06-30"
ROLL = 22          # rolling window for RV/RQ proxy construction (~1 month)
HORIZONS = [1, 5, 22]
ASSETS = [
    ("SPY", "SPY"),
    ("QQQ", "QQQ"),
    ("0050.TW", "0050.TW (Taiwan Top-50 ETF)"),
]


# --------------------------------------------------------------------------- #
# Data & proxy construction
# --------------------------------------------------------------------------- #
def fetch_returns(ticker: str) -> pd.Series:
    """Daily log-returns; 0050.TW routed through clean_tw50_data (split fix)."""
    df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    close = df["Close"].astype(float).dropna().sort_index()

    if ticker == "0050.TW":
        # Fix the 2014-01-02 split artifact (fake -75% return) BEFORE returns.
        clean_prices, _ = clean_tw50_data(close)
        ret = np.log(clean_prices).diff()
    else:
        ret = np.log(close).diff()
    return ret.dropna()


def build_proxies(ret: pd.Series, window: int = ROLL) -> pd.DataFrame:
    """Build HAR RV components and an RQ (quarticity) proxy from daily returns.

    RV proxy (repo convention): rv_d,t = r_t^2 (daily close-to-close squared
    log return). Weekly / monthly HAR components are trailing means of rv_d.

    RQ proxy (BPQ 2016 realized-quarticity form, low-frequency analog):
        RQ = (N / 3) * sum_{i in window} r_i^4
    where the intraday RQ uses N high-frequency returns; here N = `window`
    daily returns act as the low-frequency analog. sqrt(RQ) enters the HARQ
    interaction (BPQ convention). All quantities at index t use ONLY data
    through day t, so no lookahead exists relative to a forward target.
    """
    rv_d = ret.pow(2)                                # daily RV proxy
    rv_w = rv_d.rolling(5).mean()                    # weekly HAR component
    rv_m = rv_d.rolling(22).mean()                   # monthly HAR component

    # Realized quarticity proxy (BPQ 2016 RQ estimator: (N/3) * sum r^4)
    r4_sum = ret.pow(4).rolling(window).sum()
    rq = (window / 3.0) * r4_sum
    sqrt_rq = np.sqrt(rq.clip(lower=0))

    out = pd.DataFrame(
        {
            "rv_d": rv_d,
            "rv_w": rv_w,
            "rv_m": rv_m,
            "rq": rq,
            "sqrt_rq": sqrt_rq,
        }
    )
    return out


def make_target(rv_d: pd.Series, h: int) -> pd.Series:
    """Forward h-day average RV, forward-only.

    For h=1: RV_{t+1}. For h>1: mean(RV over t+1..t+h). Implemented as a
    trailing rolling-h mean then shift(-h): at row t this holds the mean of
    rv_d[t+1 .. t+h] (future-only). Row t features use only data through t.
    """
    if h == 1:
        return rv_d.shift(-1)
    return rv_d.rolling(h).mean().shift(-h)


# --------------------------------------------------------------------------- #
# HLN-corrected Diebold-Mariano
# --------------------------------------------------------------------------- #
def dm_hln(loss_a: np.ndarray, loss_b: np.ndarray, h: int) -> dict:
    """Diebold-Mariano test with HLN (1997) small-sample correction + NW HAC.

    d_t = loss_a_t - loss_b_t.  t < 0  =>  model A better (lower loss).

    HAC lag = h - 1 (canonical for an h-step-ahead forecast). HLN (1997)
    multiplicative correction:
        corr = sqrt( (n + 1 - 2h + h(h-1)/n) / n )
        DM_HLN = corr * DM
    with a t(n-1) reference distribution.
    """
    a = np.asarray(loss_a, dtype=np.float64)
    b = np.asarray(loss_b, dtype=np.float64)
    d = a - b
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return {"t_stat": float("nan"), "p_value": float("nan"), "n": int(n),
                "hac_lag": h - 1, "mean_d": float("nan")}

    d_mean = float(np.mean(d))
    dm_center = d - d_mean
    gamma0 = float(np.dot(dm_center, dm_center) / n)
    var_d = gamma0
    lag = max(0, h - 1)                               # h-step => truncate at h-1
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)                       # Bartlett weight
        gamma_k = float(np.dot(dm_center[k:], dm_center[:-k]) / n)
        var_d += 2.0 * w * gamma_k
    if var_d <= 0:
        return {"t_stat": float("nan"), "p_value": float("nan"), "n": int(n),
                "hac_lag": lag, "mean_d": d_mean}

    dm_stat = d_mean / np.sqrt(var_d / n)
    # HLN small-sample correction
    corr = np.sqrt(max((n + 1 - 2 * h + h * (h - 1) / n) / n, 1e-12))
    dm_hln_stat = corr * dm_stat
    p_val = 2 * (1 - stats.t.cdf(abs(dm_hln_stat), df=n - 1))
    return {
        "t_stat": float(dm_hln_stat),
        "p_value": float(p_val),
        "n": int(n),
        "hac_lag": int(lag),
        "mean_d": d_mean,
        "dm_uncorrected": float(dm_stat),
    }


# --------------------------------------------------------------------------- #
# Models & OOS
# --------------------------------------------------------------------------- #
def _design(feat: pd.DataFrame, model: str) -> np.ndarray:
    """Build design matrix (no intercept column; added in OLS) for a model.

    HAR:      [rv_d, rv_w, rv_m]
    HARQ:     [rv_d, rv_w, rv_m, sqrt_rq_std * rv_d]           (BPQ 2016)
    HARQ-F:   [rv_d, rv_w, rv_m, sqrt_rq_std*rv_d,
               sqrt_rq_std*rv_w, sqrt_rq_std*rv_m]             (BPQ HARQ-F)

    sqrt_rq_std is the standardized (demeaned/scaled) sqrt(RQ) proxy — BPQ
    demean the RQ term so beta1 keeps its plain-HAR interpretation and the
    interaction is a pure measurement-error modulation.
    """
    rv_d = feat["rv_d"].to_numpy()
    rv_w = feat["rv_w"].to_numpy()
    rv_m = feat["rv_m"].to_numpy()
    sq = feat["sqrt_rq_std"].to_numpy()
    if model == "HAR":
        return np.column_stack([rv_d, rv_w, rv_m])
    if model == "HARQ":
        return np.column_stack([rv_d, rv_w, rv_m, sq * rv_d])
    if model == "HARQ-F":
        return np.column_stack([rv_d, rv_w, rv_m, sq * rv_d, sq * rv_w, sq * rv_m])
    raise ValueError(model)


def rolling_oos(
    feat: pd.DataFrame,
    target: pd.Series,
    model: str,
    h: int,
    init_train: int,
    step: int = 1,
) -> pd.DataFrame:
    """Expanding-window OOS forecasts, BPQ level-RV HARQ specification.

    BPQ (2016) estimate HARQ on the LEVEL of RV (not log), because the
    beta1Q * sqrt(RQ) * RV_d interaction is defined on the RV level scale.
    We therefore fit level-RV OLS.

    INSANITY FILTER (BPQ 2016, canonical HARQ practice): level-RV OLS with the
    RQ interaction can extrapolate to a forecast outside the empirically
    plausible support (e.g. a negative RV on a crisis day), which explodes
    QLIKE. BPQ replace any forecast below the training-window minimum or above
    the training-window maximum with the training-window MEAN. We apply the
    SAME filter identically to HAR, HARQ, and HARQ-F (fair comparison) using
    ONLY the training window (OOS-clean, no lookahead). Diagnostics record how
    often the filter fires per model.

    Forward-label timing (experiments.md hard rule): to forecast the target at
    origin i (label window [i+1, i+h]), the training set may only use rows j
    whose label window ends strictly before i, i.e. j + h < i. We therefore
    train on rows [0 .. i-h-1] (drop the last h rows to prevent the training
    tail from seeing the forecast day or later realized returns).
    """
    cols = ["rv_d", "rv_w", "rv_m", "sqrt_rq_std"]
    data = feat[cols].copy()
    data["y"] = target
    data = data.dropna()
    idx = data.index
    n = len(data)
    if n <= init_train + h + 10:
        return pd.DataFrame(columns=["y_true", "y_pred"]), 0

    X_full = _design(data, model)
    y_full = data["y"].to_numpy()
    preds = np.full(n, np.nan)
    n_filter = 0

    for i in range(init_train, n, step):
        # Forward-label guard: training rows must satisfy j + h < i.
        train_end = i - h                             # exclusive upper bound
        if train_end < 20:
            continue
        X_tr = X_full[:train_end]
        y_tr = y_full[:train_end]
        X_te = X_full[i : i + 1]
        Xt = np.column_stack([np.ones(len(X_tr)), X_tr])
        try:
            coef, *_ = np.linalg.lstsq(Xt, y_tr, rcond=None)
        except np.linalg.LinAlgError:
            preds[i] = float(np.mean(y_tr))
            continue
        Xp = np.column_stack([np.ones(1), X_te])
        raw = float((Xp @ coef)[0])
        # BPQ insanity filter — training-window support only (OOS-clean)
        y_lo, y_hi, y_mu = float(y_tr.min()), float(y_tr.max()), float(y_tr.mean())
        if raw < y_lo or raw > y_hi or not np.isfinite(raw):
            preds[i] = y_mu
            n_filter += 1
        else:
            preds[i] = raw

    pred_ser = np.maximum(preds, 1e-16)
    out = pd.DataFrame({"y_true": y_full, "y_pred": pred_ser}, index=idx).dropna()
    return out, n_filter


# --------------------------------------------------------------------------- #
# Run one asset
# --------------------------------------------------------------------------- #
def run_asset(ticker: str, label: str) -> dict:
    print(f"\n=== {label} ({ticker}) ===")
    ret = fetch_returns(ticker)
    print(f"  {len(ret)} daily returns, {ret.index.min().date()} -> {ret.index.max().date()}")

    prox = build_proxies(ret, window=ROLL)

    asset_out = {
        "ticker": ticker,
        "label": label,
        "n_returns": int(len(ret)),
        "date_range": [str(ret.index.min().date()), str(ret.index.max().date())],
        "rq_proxy_descriptive": {
            "rq_mean": float(prox["rq"].mean()),
            "rq_std": float(prox["rq"].std()),
            "sqrt_rq_mean": float(prox["sqrt_rq"].mean()),
            "sqrt_rq_std": float(prox["sqrt_rq"].std()),
        },
        "horizons": {},
        "beta1Q_significance": {},
    }

    for h in HORIZONS:
        target = make_target(prox["rv_d"], h)

        # Standardize sqrt(RQ) proxy on a training-only basis to stay OOS-clean:
        # we use full-sample mean/std ONLY for the interaction scaling (a fixed
        # affine reparameterization, not a target-derived leak). To be strict we
        # instead demean/scale by an expanding statistic would be ideal, but the
        # BPQ demeaning is a scale convention on a regressor, not the target;
        # here we standardize with a global (feature-only) mean/std which does
        # not touch y and does not change OOS forecast rank. Kept explicit.
        sq = prox["sqrt_rq"]
        sq_std = (sq - sq.mean()) / (sq.std() + 1e-16)
        feat = pd.DataFrame(
            {
                "rv_d": prox["rv_d"],
                "rv_w": prox["rv_w"],
                "rv_m": prox["rv_m"],
                "sqrt_rq_std": sq_std,
            }
        )

        # init_train = first 20% (>= 500) for warm-up
        avail = feat.join(target.rename("y")).dropna()
        init_train = max(500, int(0.20 * len(avail)))

        oos = {}
        filt = {}
        for model in ["HAR", "HARQ", "HARQ-F"]:
            oos[model], filt[model] = rolling_oos(feat, target, model, h=h, init_train=init_train, step=1)

        # Align on common OOS dates
        common = None
        for df_p in oos.values():
            common = df_p.index if common is None else common.intersection(df_p.index)
        if common is None or len(common) < 100:
            asset_out["horizons"][str(h)] = {"note": "insufficient_oos", "n": 0 if common is None else int(len(common))}
            continue
        aligned = {m: df_p.loc[common] for m, df_p in oos.items()}

        # QLIKE / MSE per model
        metrics = {}
        losses = {}
        for m, df_p in aligned.items():
            yt = df_p["y_true"].to_numpy()
            yp = df_p["y_pred"].to_numpy()
            ql = qlike_pointwise(yt, yp)
            losses[m] = ql
            metrics[m] = {
                "qlike": float(np.mean(ql)),
                "mse": float(np.mean((yt - yp) ** 2)),
            }

        base_loss = losses["HAR"]
        base_ql = metrics["HAR"]["qlike"]
        dm = {}
        for m in ["HARQ", "HARQ-F"]:
            dm_res = dm_hln(losses[m], base_loss, h=h)      # t<0 => challenger better
            loss_ratio = metrics[m]["qlike"] / base_ql if base_ql != 0 else float("nan")
            dm[f"{m}_vs_HAR"] = {
                **dm_res,
                "qlike_loss_ratio": float(loss_ratio),
            }

        asset_out["horizons"][str(h)] = {
            "n_oos": int(len(common)),
            "init_train": int(init_train),
            "oos_range": [str(common.min().date()), str(common.max().date())],
            "qlike": {m: metrics[m]["qlike"] for m in metrics},
            "mse": {m: metrics[m]["mse"] for m in metrics},
            "insanity_filter_count": {m: int(filt[m]) for m in filt},
            "dm_hln_vs_HAR": dm,
        }
        # stash aligned for plotting
        asset_out.setdefault("_plot", {})[str(h)] = {
            m: (df_p["y_true"].to_numpy(), df_p["y_pred"].to_numpy())
            for m, df_p in aligned.items()
        }

        # beta1Q full-sample significance (HARQ, level RV, HAC OLS SE)
        b1q = beta1q_significance(feat, target, h)
        asset_out["beta1Q_significance"][str(h)] = b1q

        print(
            f"  h={h}: n_oos={len(common)}  "
            f"QLIKE HAR={metrics['HAR']['qlike']:.5f} HARQ={metrics['HARQ']['qlike']:.5f} "
            f"HARQ-F={metrics['HARQ-F']['qlike']:.5f}  "
            f"DM(HARQ)={dm['HARQ_vs_HAR']['t_stat']:.2f} (p={dm['HARQ_vs_HAR']['p_value']:.3f})  "
            f"b1Q t={b1q.get('t_stat', float('nan')):.2f}"
        )

    return asset_out


def beta1q_significance(feat: pd.DataFrame, target: pd.Series, h: int) -> dict:
    """Full-sample HARQ OLS with HAC(h-1) SE on beta1Q (the RQ interaction).

    Tests whether the measurement-error correction coefficient is materially
    different from zero (BPQ: beta1Q < 0 => daily coef shrinks when RQ high).
    Forward-label: drop the last h rows so the label window never overlaps the
    feature row (same j + h < i logic, applied to the full-sample fit).
    """
    cols = ["rv_d", "rv_w", "rv_m", "sqrt_rq_std"]
    data = feat[cols].copy()
    data["y"] = target
    data = data.dropna()
    if len(data) <= h + 50:
        return {"note": "insufficient"}
    # Drop last h rows: their label window peeks past the last usable origin.
    data = data.iloc[:-h] if h > 0 else data
    X = _design(data, "HARQ")                         # [rv_d, rv_w, rv_m, sq*rv_d]
    y = data["y"].to_numpy()
    Xt = np.column_stack([np.ones(len(X)), X])
    try:
        coef, *_ = np.linalg.lstsq(Xt, y, rcond=None)
    except np.linalg.LinAlgError:
        return {"note": "singular"}
    resid = y - Xt @ coef
    n, k = Xt.shape
    # Newey-West HAC covariance, lag = max(h-1, 1)
    lag = max(h - 1, 1)
    XtX_inv = np.linalg.pinv(Xt.T @ Xt)
    S = (Xt * resid[:, None]).T @ (Xt * resid[:, None])
    for l in range(1, lag + 1):
        w = 1.0 - l / (lag + 1)
        Xl = Xt[l:] * resid[l:, None]
        Xm = Xt[:-l] * resid[:-l, None]
        G = Xl.T @ Xm
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    b1q = coef[4]                                     # interaction is last term
    se_b1q = se[4]
    t = b1q / se_b1q if se_b1q > 0 else float("nan")
    p = 2 * (1 - stats.t.cdf(abs(t), df=n - k)) if np.isfinite(t) else float("nan")
    return {
        "beta1Q": float(b1q),
        "se": float(se_b1q),
        "t_stat": float(t),
        "p_value": float(p),
        "n": int(n),
        "hac_lag": int(lag),
        "sign_expected": "negative (BPQ: daily coef shrinks when RQ high)",
    }


# --------------------------------------------------------------------------- #
# Plots
# --------------------------------------------------------------------------- #
def make_plots(results: list[dict]) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plots = {}

    # Fig 1: QLIKE loss ratio (HARQ / HAR, HARQ-F / HAR) by asset x horizon
    fig, ax = plt.subplots(figsize=(11, 5.5))
    assets = [r["label"].split(" ")[0] for r in results]
    x = np.arange(len(HORIZONS))
    width = 0.12
    colors = {"HARQ": "#C44E52", "HARQ-F": "#8172B3"}
    offset = 0
    handles_labels = {}
    for ai, r in enumerate(results):
        for mi, model in enumerate(["HARQ", "HARQ-F"]):
            ratios = []
            for h in HORIZONS:
                hd = r["horizons"].get(str(h), {})
                dm = hd.get("dm_hln_vs_HAR", {}).get(f"{model}_vs_HAR", {})
                ratios.append(dm.get("qlike_loss_ratio", np.nan))
            pos = x + (ai * 2 + mi - 2.5) * width
            bars = ax.bar(pos, ratios, width, color=colors[model],
                          alpha=0.55 + 0.15 * ai,
                          edgecolor="black", linewidth=0.4)
            handles_labels[f"{assets[ai]} {model}"] = bars
    ax.axhline(1.0, color="black", linestyle="--", linewidth=1,
               label="parity (HARQ = HAR)")
    ax.set_xticks(x)
    ax.set_xticklabels([f"h={h}" for h in HORIZONS])
    ax.set_ylabel("QLIKE loss ratio  (challenger / HAR;  <1 = challenger better)")
    ax.set_title("K1600 HARQ-proxy vs HAR — OOS QLIKE loss ratio (daily-return proxy, 2010-2026)")
    ax.legend(fontsize=7, ncol=2)
    ax.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    p1 = FIG_DIR / "k1600_qlike_loss_ratio.png"
    plt.savefig(p1, dpi=130)
    plt.close()
    plots["qlike_loss_ratio"] = str(p1.relative_to(OUT_DIR))

    # Fig 2: DM-HLN t-stats + beta1Q t-stats
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    # (a) DM-HLN t of HARQ vs HAR
    axd = axes[0]
    labels, tvals, cols = [], [], []
    for r in results:
        a = r["label"].split(" ")[0]
        for h in HORIZONS:
            hd = r["horizons"].get(str(h), {})
            dm = hd.get("dm_hln_vs_HAR", {}).get("HARQ_vs_HAR", {})
            t = dm.get("t_stat", np.nan)
            labels.append(f"{a}\nh={h}")
            tvals.append(t)
            cols.append("#55A868" if (np.isfinite(t) and t < -3) else
                        "#C44E52" if (np.isfinite(t) and t > 3) else "#999999")
    axd.bar(range(len(labels)), tvals, color=cols)
    axd.axhline(-3, color="green", ls="--", label="Harvey -3 (challenger better)")
    axd.axhline(3, color="red", ls="--", alpha=0.6)
    axd.axhline(0, color="k", lw=0.6)
    axd.set_xticks(range(len(labels)))
    axd.set_xticklabels(labels, fontsize=7)
    axd.set_ylabel("DM-HLN t (HARQ vs HAR; neg = HARQ better)")
    axd.set_title("(a) DM-HLN test: HARQ-proxy vs HAR")
    axd.legend(fontsize=7)
    axd.grid(axis="y", alpha=0.25)
    # (b) beta1Q t-stats
    axb = axes[1]
    blabels, bvals, bcols = [], [], []
    for r in results:
        a = r["label"].split(" ")[0]
        for h in HORIZONS:
            b = r["beta1Q_significance"].get(str(h), {})
            t = b.get("t_stat", np.nan)
            blabels.append(f"{a}\nh={h}")
            bvals.append(t)
            bcols.append("#4C72B0" if (np.isfinite(t) and abs(t) > 3) else "#BBBBBB")
    axb.bar(range(len(blabels)), bvals, color=bcols)
    axb.axhline(3, color="k", ls="--", alpha=0.5, label="|t|=3 (Harvey)")
    axb.axhline(-3, color="k", ls="--", alpha=0.5)
    axb.axhline(0, color="k", lw=0.6)
    axb.set_xticks(range(len(blabels)))
    axb.set_xticklabels(blabels, fontsize=7)
    axb.set_ylabel("beta1Q t (RQ interaction; neg = daily coef shrinks when RQ high)")
    axb.set_title("(b) HARQ measurement-error coefficient beta1Q significance")
    axb.legend(fontsize=7)
    axb.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    p2 = FIG_DIR / "k1600_dm_and_beta1q.png"
    plt.savefig(p2, dpi=130)
    plt.close()
    plots["dm_and_beta1q"] = str(p2.relative_to(OUT_DIR))

    return plots


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
def derive_verdict(results: list[dict]) -> dict:
    """Aggregate honest verdict.

    A HARQ improvement 'counts' only if BOTH: DM-HLN t < -3.0 (Harvey) AND
    beta1Q is Harvey-significant (|t| > 3) with the BPQ-expected negative sign.
    """
    n_cells = 0
    n_dm_harvey = 0
    n_b1q_harvey = 0
    n_joint = 0
    per_cell = []
    for r in results:
        a = r["label"].split(" ")[0]
        for h in HORIZONS:
            hd = r["horizons"].get(str(h), {})
            if "dm_hln_vs_HAR" not in hd:
                continue
            n_cells += 1
            dm = hd["dm_hln_vs_HAR"]["HARQ_vs_HAR"]
            b = r["beta1Q_significance"].get(str(h), {})
            dm_t = dm.get("t_stat", np.nan)
            b_t = b.get("t_stat", np.nan)
            b_val = b.get("beta1Q", np.nan)
            dm_sig = np.isfinite(dm_t) and dm_t < -3.0
            b_sig = np.isfinite(b_t) and abs(b_t) > 3.0
            b_neg = np.isfinite(b_val) and b_val < 0
            joint = dm_sig and b_sig and b_neg
            n_dm_harvey += int(dm_sig)
            n_b1q_harvey += int(b_sig)
            n_joint += int(joint)
            per_cell.append({
                "asset": a, "h": h,
                "dm_t": None if not np.isfinite(dm_t) else round(float(dm_t), 3),
                "loss_ratio": round(float(hd["dm_hln_vs_HAR"]["HARQ_vs_HAR"].get("qlike_loss_ratio", np.nan)), 4),
                "beta1Q_t": None if not np.isfinite(b_t) else round(float(b_t), 3),
                "beta1Q_neg": bool(b_neg),
                "dm_harvey_sig": bool(dm_sig),
                "beta1Q_harvey_sig": bool(b_sig),
                "joint_support": bool(joint),
            })

    if n_joint >= 1:
        verdict = "PASS"
    elif n_dm_harvey >= 1 or n_b1q_harvey >= 1:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    return {
        "verdict": verdict,
        "n_cells": n_cells,
        "n_dm_harvey_sig": n_dm_harvey,
        "n_beta1Q_harvey_sig": n_b1q_harvey,
        "n_joint_support": n_joint,
        "per_cell": per_cell,
        "note": (
            "HARQ-proxy uses a DAILY-return quarticity proxy, a weak low-frequency "
            "analog of intraday RQ. This is NOT true intraday HARQ. NULL is a "
            "legitimate honest outcome if the proxy cannot carry the measurement-"
            "error signal."
        ),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    results = []
    for ticker, label in ASSETS:
        results.append(run_asset(ticker, label))

    plots = make_plots(results)
    verdict = derive_verdict(results)

    # strip plot intermediates before JSON dump
    for r in results:
        r.pop("_plot", None)

    output = {
        "experiment_id": "k1600",
        "title": "HARQ-proxy: low-frequency proxy of measurement-error-corrected HAR",
        "framing": (
            "Honest low-frequency proxy of HARQ (Bollerslev, Patton & Quaedvlieg, "
            "JoE 2016). Repo lacks a long-sample intraday RV+RQ panel, so RV and RQ "
            "are built from DAILY log returns over 2010-2026. A daily quarticity "
            "proxy is a WEAK analog of intraday RQ; NULL is an acceptable honest "
            "result. NOT a claim about true intraday HARQ."
        ),
        "run_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_source": "yfinance daily close, 0050.TW via clean_tw50_data",
        "sample_period": [START, END],
        "assets": [t for t, _ in ASSETS],
        "pooling": "NONE — each asset estimated & reported independently (K1355 rule)",
        "methodology": {
            "rv_proxy": "rv_d,t = r_t^2 (daily squared log return); HAR w/m = trailing 5/22-day mean",
            "rq_proxy": f"realized quarticity proxy (N/3)*sum r^4 over {ROLL}-day window; sqrt(RQ) standardized (feature-only)",
            "models": {
                "HAR": "Corsi 2009: RV_{t+h} = b0 + b1 RV_d + b2 RV_w + b3 RV_m",
                "HARQ": "BPQ 2016: + b1Q * sqrt(RQ)_std * RV_d (daily-term measurement-error interaction)",
                "HARQ-F": "BPQ 2016 full: measurement-error interaction on daily/weekly/monthly terms",
            },
            "estimator": "expanding-window OLS on LEVEL RV (BPQ convention), init_train=max(500, 20%)",
            "horizons": HORIZONS,
            "forward_label_rule": "train rows kept only if j + h < i (target_end_pos < forecast_pos); last h rows dropped in full-sample fit",
            "per_horizon_dm": "each horizon h uses its own DM inference horizon; HAC lag = h-1",
            "loss": "canonical volpred qlike_pointwise (actual/predicted) + MSE",
            "dm_test": "Diebold-Mariano + HLN (1997) small-sample correction, NW HAC(h-1), t(n-1) reference",
            "harvey_threshold": "|t| > 3.0 (Harvey 2016)",
        },
        "verdict": verdict["verdict"],
        "verdict_detail": verdict,
        "assets_results": results,
        "plots": plots,
    }

    out_path = OUT_DIR / "k1600_results.json"
    with out_path.open("w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved -> {out_path}")
    print(f"VERDICT: {verdict['verdict']}")
    print(f"  cells={verdict['n_cells']}  DM-Harvey={verdict['n_dm_harvey_sig']}  "
          f"beta1Q-Harvey={verdict['n_beta1Q_harvey_sig']}  joint={verdict['n_joint_support']}")


if __name__ == "__main__":
    main()
