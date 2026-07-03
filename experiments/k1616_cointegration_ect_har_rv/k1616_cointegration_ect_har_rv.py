"""k1616 | Cointegration error-correction term (ECT) as an additional HAR-RV covariate.

Research question
-----------------
Two cointegrated assets share a long-run equilibrium; their short-run deviation
(the error-correction term, ECT) is a measure of cross-asset disequilibrium.
Economic intuition: when the equilibrium is stretched (|ECT| large), a
correction pressure builds → realized volatility may rise. We test whether
``ECT_{t-1}`` (and ``|ECT_{t-1}|``) provides *incremental* out-of-sample
forecasting power for an asset's realized variance, over and above a standard
Corsi (2009) HAR-RV baseline.

Design (honest, no-lookahead)
-----------------------------
* RV proxy: Garman-Klass daily variance from OHLC (canonical volpred helper).
  Baseline HAR and HAR+ECT use the SAME RV definition -> we test the ECT
  increment, NOT HAR-vs-something-else (avoids the target-mismatch trap in the
  experiment preamble).
* Cointegration GATE: Engle-Granger two-step (statsmodels ``coint`` + ADF on the
  OLS residual), full sample. A pair is only eligible for ECT if cointegration
  is not rejected. Full-sample use here is a *descriptive gate* only (standard
  practice), NOT a forecasting input.
* Forecasting beta: cointegration beta for the OOS ECT feature is re-estimated
  on an EXPANDING window (monthly refit). The forecast for day ``i`` uses beta
  fitted on data through ``i-1`` and prices at ``i-1`` only -> genuinely OOS.
  A static full-sample-beta variant is reported as robustness (it is mildly
  leaky and only used to show sensitivity, never as the headline).
* HAR features are all lagged so they are known at the end of day ``t-1``:
  daily = RV_{t-1}, weekly = mean(RV_{t-5..t-1}), monthly = mean(RV_{t-22..t-1}).
  Target = RV_t. The forecast for day ``i`` uses ZERO information from day ``i``.
* log-RV modelling with log-normal retransformation (exp(pred + 0.5*resid_var)),
  applied identically (each model uses its own residual variance) so the
  comparison is fair.
* Evaluation: QLIKE via ``volpred.stats.model_evaluation.qlike_pointwise``
  (actual/predicted direction), MSE auxiliary. DM test (Newey-West HAC) with
  Harvey-Leybourne-Newbold (1997) small-sample correction. Single 1-step horizon.

All random procedures use a fixed seed.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats as scistats  # noqa: E402
from statsmodels.tsa.stattools import adfuller, coint  # noqa: E402

from volpred.data.preprocessing import compute_garman_klass_vol  # noqa: E402
from volpred.stats.model_evaluation import dm_test, qlike_pointwise  # noqa: E402

SEED = 20260704
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
DB_PATH = REPO / "data" / "cache" / "price_cache.db"

RV_FLOOR = 1e-8          # variance floor (GK is >=0 but can be exactly 0)
INITIAL_TRAIN = 750      # burn-in before first OOS forecast
REFIT_FREQ = 21          # monthly refit of beta + HAR coefficients
HAR_WARMUP = 22          # need 22-day monthly average before a usable HAR row

# ----------------------------------------------------------------------------
# Pair / target configuration
# ----------------------------------------------------------------------------
PAIRS = [
    dict(name="SPY-QQQ", y="SPY", x="QQQ", transform="log",
         targets=["SPY", "QQQ"], start=None,
         note="US large-cap vs Nasdaq-100 equity indices, same 2016- window"),
    dict(name="GLD-TLT", y="GLD", x="TLT", transform="log",
         targets=["GLD", "TLT"], start=None,
         note="Gold vs long Treasuries (safe-haven pair)"),
    dict(name="SPY-EEM", y="SPY", x="EEM", transform="log",
         targets=["EEM"], start=None,
         note="US vs emerging markets (SPY RV already covered by SPY-QQQ)"),
    dict(name="VIX-VIX3M", y="^VIX", x="^VIX3M", transform="level",
         targets=["SPY"], start="2020-01-02",
         note="VIX term-structure ECT (1M vs 3M) predicting SPY realized vol; "
              "strongest economic prior but shorter sample (2020-)"),
]


# ----------------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------------
def load_prices(tickers):
    con = sqlite3.connect(str(DB_PATH))
    qmarks = ",".join("?" for _ in tickers)
    df = pd.read_sql_query(
        f"SELECT ticker, date, open, high, low, close, adj_close "
        f"FROM price_data WHERE ticker IN ({qmarks}) ORDER BY date",
        con, params=list(tickers),
    )
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def gk_variance(sub: pd.DataFrame) -> pd.Series:
    """Garman-Klass daily variance proxy indexed by date."""
    s = compute_garman_klass_vol(sub["open"], sub["high"], sub["low"], sub["close"])
    s.index = sub["date"].values
    return s.clip(lower=RV_FLOOR)


def price_series(sub: pd.DataFrame, transform: str) -> pd.Series:
    """Cointegration price series (adj_close). log for ETFs, level for VIX."""
    p = sub.set_index("date")["adj_close"].astype(float)
    if transform == "log":
        return np.log(p)
    return p


# ----------------------------------------------------------------------------
# Engle-Granger cointegration gate (full sample, descriptive)
# ----------------------------------------------------------------------------
def engle_granger(py: pd.Series, px: pd.Series) -> dict:
    """Two-step EG test both directions + ADF on OLS residual of y~x."""
    common = py.dropna().index.intersection(px.dropna().index)
    py, px = py.loc[common], px.loc[common]

    # statsmodels coint (handles correct cointegration critical values)
    t_yx, p_yx, _ = coint(py.values, px.values)
    t_xy, p_xy, _ = coint(px.values, py.values)

    # OLS y = a + b x -> residual (defines the ECT we will use), ADF on residual
    X = np.column_stack([np.ones(len(px)), px.values])
    beta, *_ = np.linalg.lstsq(X, py.values, rcond=None)
    resid = py.values - X @ beta
    adf_stat, adf_p, *_ = adfuller(resid, autolag="AIC")

    cointegrated = bool(min(p_yx, p_xy) < 0.05 or adf_p < 0.05)
    return {
        "n_obs": int(len(py)),
        "coint_t_y_on_x": float(t_yx), "coint_p_y_on_x": float(p_yx),
        "coint_t_x_on_y": float(t_xy), "coint_p_x_on_y": float(p_xy),
        "ols_alpha": float(beta[0]), "ols_beta": float(beta[1]),
        "resid_adf_stat": float(adf_stat), "resid_adf_p": float(adf_p),
        "cointegrated_5pct": cointegrated,
    }


# ----------------------------------------------------------------------------
# HAR design + OOS engine
# ----------------------------------------------------------------------------
def build_har_frame(rv: pd.Series) -> pd.DataFrame:
    """log-RV HAR features, all lagged so they are known at end of day t-1."""
    logrv = np.log(rv)
    df = pd.DataFrame({"rv": rv.values, "logrv": logrv.values}, index=rv.index)
    df["f_d"] = df["logrv"].shift(1)
    df["f_w"] = df["logrv"].rolling(5).mean().shift(1)
    df["f_m"] = df["logrv"].rolling(22).mean().shift(1)
    return df


def _ols(X: np.ndarray, y: np.ndarray):
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    resid_var = float(np.var(resid, ddof=X.shape[1])) if len(y) > X.shape[1] else 0.0
    return coef, max(resid_var, 0.0)


def run_oos(rv: pd.Series, py: pd.Series, px: pd.Series):
    """Expanding-window OOS forecast for HAR and HAR+ECT.

    Returns dict with aligned arrays: actual, pred_har, pred_ect (expanding beta),
    pred_ect_static (full-sample beta robustness), plus book-keeping.
    """
    har = build_har_frame(rv)
    # align cointegration prices to the RV/HAR index
    common = har.index.intersection(py.index).intersection(px.index)
    har = har.loc[common]
    pyv = py.loc[common].values.astype(float)
    pxv = px.loc[common].values.astype(float)

    logrv = har["logrv"].values
    feats = har[["f_d", "f_w", "f_m"]].values
    rv_arr = har["rv"].values
    n = len(har)

    # rows usable for HAR training/forecasting (features finite)
    usable = np.isfinite(feats).all(axis=1) & np.isfinite(logrv)

    # ---- full-sample (static) beta for robustness variant only ----
    Xstat = np.column_stack([np.ones(n), pxv])
    beta_stat, *_ = np.linalg.lstsq(Xstat, pyv, rcond=None)
    ect_static_all = pyv - (beta_stat[0] + beta_stat[1] * pxv)

    actual, dates = [], []
    pred_har, pred_ect, pred_ect_static = [], [], []
    ect_used = []
    beta_path = []

    coef_har = coef_ect = None
    rvar_har = rvar_ect = 0.0
    beta_c = None  # (a, b) expanding cointegration beta

    start = max(INITIAL_TRAIN, HAR_WARMUP + 1)
    for i in range(start, n):
        if (i - start) % REFIT_FREQ == 0 or coef_har is None:
            # ---- expanding cointegration beta on data through i-1 ----
            Xc = np.column_stack([np.ones(i), pxv[:i]])
            bc, *_ = np.linalg.lstsq(Xc, pyv[:i], rcond=None)
            beta_c = bc
            ect_all = pyv - (bc[0] + bc[1] * pxv)  # residual series w/ current beta
            beta_path.append({"i": int(i), "a": float(bc[0]), "b": float(bc[1])})

            # ---- training rows: usable HAR rows with index < i and ECT_{j-1} known ----
            tr = np.array([j for j in range(HAR_WARMUP + 1, i)
                           if usable[j] and np.isfinite(ect_all[j - 1])])
            if len(tr) < 100:
                continue
            ytr = logrv[tr]
            Xbase = np.column_stack([np.ones(len(tr)), feats[tr]])
            ect_lag = ect_all[tr - 1]
            Xect = np.column_stack([Xbase, ect_lag, np.abs(ect_lag)])
            coef_har, rvar_har = _ols(Xbase, ytr)
            coef_ect, rvar_ect = _ols(Xect, ytr)

        if not usable[i] or coef_har is None:
            continue

        # features for day i are all known at end of day i-1
        xb = np.concatenate([[1.0], feats[i]])
        ect_im1 = pyv[i - 1] - (beta_c[0] + beta_c[1] * pxv[i - 1])   # ECT_{t-1}, expanding beta
        ect_im1_s = ect_static_all[i - 1]                             # ECT_{t-1}, static beta

        ph = float(xb @ coef_har)
        pe = float(np.concatenate([xb, [ect_im1, abs(ect_im1)]]) @ coef_ect)
        # static-beta variant reuses coef_ect structure but with static ECT feature
        pe_s = float(np.concatenate([xb, [ect_im1_s, abs(ect_im1_s)]]) @ coef_ect)

        pred_har.append(np.exp(ph + 0.5 * rvar_har))
        pred_ect.append(np.exp(pe + 0.5 * rvar_ect))
        pred_ect_static.append(np.exp(pe_s + 0.5 * rvar_ect))
        actual.append(rv_arr[i])
        ect_used.append(ect_im1)
        dates.append(har.index[i])

    return {
        "dates": np.array(dates),
        "actual": np.array(actual),
        "pred_har": np.array(pred_har),
        "pred_ect": np.array(pred_ect),
        "pred_ect_static": np.array(pred_ect_static),
        "ect_used": np.array(ect_used),
        "beta_path": beta_path,
        "n_oos": len(actual),
    }


def hln_correct(t_stat: float, n: int, h: int = 1) -> tuple:
    """Harvey-Leybourne-Newbold (1997) small-sample correction of a DM stat."""
    factor = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_hln = t_stat * factor
    p_hln = 2 * (1 - scistats.t.cdf(abs(t_hln), df=n - 1))
    return float(t_hln), float(p_hln)


def evaluate(res: dict) -> dict:
    a = res["actual"]
    ph, pe, pes = res["pred_har"], res["pred_ect"], res["pred_ect_static"]

    loss_har = qlike_pointwise(a, ph)
    loss_ect = qlike_pointwise(a, pe)
    loss_ect_s = qlike_pointwise(a, pes)

    # DM: dm_test(loss1, loss2) -> negative t means model1 (HAR) better,
    # positive t means model2 (HAR+ECT) better.
    dm_t, dm_p = dm_test(loss_har, loss_ect, h=1)
    n = int(np.isfinite(loss_har - loss_ect).sum())
    hln_t, hln_p = hln_correct(dm_t, n)

    dm_t_s, dm_p_s = dm_test(loss_har, loss_ect_s, h=1)
    hln_t_s, hln_p_s = hln_correct(dm_t_s, n)

    q_har, q_ect, q_ect_s = float(loss_har.mean()), float(loss_ect.mean()), float(loss_ect_s.mean())
    mse_har = float(np.mean((a - ph) ** 2))
    mse_ect = float(np.mean((a - pe) ** 2))

    return {
        "n_oos": int(len(a)),
        "qlike_har": q_har,
        "qlike_har_ect": q_ect,
        "qlike_har_ect_static_beta": q_ect_s,
        "qlike_pct_improvement": float((q_har - q_ect) / q_har * 100.0),
        "mse_har": mse_har, "mse_har_ect": mse_ect,
        # positive t => HAR+ECT better
        "dm_t_ect_vs_har": float(dm_t), "dm_p": float(dm_p),
        "hln_t": hln_t, "hln_p": hln_p,
        "dm_t_static_beta": float(dm_t_s), "hln_t_static_beta": hln_t_s,
        "hln_p_static_beta": hln_p_s,
        "ect_helps_dm_5pct": bool(dm_t > 0 and dm_p < 0.05),
        "ect_helps_hln_5pct": bool(hln_t > 0 and hln_p < 0.05),
        "ect_helps_harvey_strict": bool(hln_t > 3.0),  # Harvey (2016) |t|>3
    }


def insample_ect_tstat(rv: pd.Series, py: pd.Series, px: pd.Series) -> dict:
    """Descriptive in-sample HAC t-stats on ECT / |ECT| coefficients (full sample)."""
    har = build_har_frame(rv)
    common = har.index.intersection(py.index).intersection(px.index)
    har = har.loc[common]
    pyv, pxv = py.loc[common].values, px.loc[common].values
    Xc = np.column_stack([np.ones(len(pyv)), pxv])
    bc, *_ = np.linalg.lstsq(Xc, pyv, rcond=None)
    ect = pyv - Xc @ bc
    d = har.copy()
    d["ect_lag"] = np.r_[np.nan, ect[:-1]]
    d["aect_lag"] = np.abs(d["ect_lag"])
    d = d.dropna(subset=["logrv", "f_d", "f_w", "f_m", "ect_lag"])
    y = d["logrv"].values
    X = np.column_stack([np.ones(len(d)), d[["f_d", "f_w", "f_m", "ect_lag", "aect_lag"]].values])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    # Newey-West HAC covariance
    n, k = X.shape
    L = int(np.ceil(4 * (n / 100) ** (2 / 9)))
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for lag in range(1, L + 1):
        w = 1 - lag / (L + 1)
        Xu = X * resid[:, None]
        G = Xu[lag:].T @ Xu[:-lag]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    return {
        "ect_coef": float(coef[4]), "ect_hac_t": float(coef[4] / se[4]),
        "abs_ect_coef": float(coef[5]), "abs_ect_hac_t": float(coef[5] / se[5]),
        "n": int(n), "hac_lag": int(L),
    }


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    all_tickers = sorted({t for p in PAIRS for t in (p["y"], p["x"], *p["targets"])})
    raw = load_prices(all_tickers)
    by_ticker = {t: raw[raw["ticker"] == t].sort_values("date").reset_index(drop=True)
                 for t in all_tickers}

    results = {
        "experiment_id": "k1616",
        "title": "Cointegration error-correction term (ECT) as a HAR-RV covariate",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "rv_proxy": "Garman-Klass daily variance (OHLC, log-RV HAR)",
        "config": {
            "initial_train": INITIAL_TRAIN, "refit_freq_days": REFIT_FREQ,
            "har_warmup": HAR_WARMUP, "rv_floor": RV_FLOOR,
            "retransform": "log-normal exp(pred + 0.5*resid_var), per-model",
            "dm": "Newey-West HAC + Harvey-Leybourne-Newbold small-sample correction",
        },
        "pairs": [],
    }

    fig_cfg = None  # remember one config for the ECT/RV overlay figure
    bar_labels, bar_har, bar_ect = [], [], []

    for pc in PAIRS:
        ysub, xsub = by_ticker[pc["y"]], by_ticker[pc["x"]]
        if pc["start"]:
            start = pd.Timestamp(pc["start"])
            ysub = ysub[ysub["date"] >= start]
            xsub = xsub[xsub["date"] >= start]
        py = price_series(ysub, pc["transform"])
        px = price_series(xsub, pc["transform"])

        eg = engle_granger(py, px)
        pair_entry = {
            "name": pc["name"], "y": pc["y"], "x": pc["x"],
            "transform": pc["transform"], "note": pc["note"],
            "sample_start": pc["start"] or str(py.dropna().index.min().date()),
            "sample_end": str(py.dropna().index.max().date()),
            "cointegration_engle_granger": eg,
            "targets": [],
        }
        print(f"\n=== {pc['name']} | coint p(min)={min(eg['coint_p_y_on_x'], eg['coint_p_x_on_y']):.4f} "
              f"resid_adf_p={eg['resid_adf_p']:.4f} cointegrated={eg['cointegrated_5pct']} ===")

        for tgt in pc["targets"]:
            tsub = by_ticker[tgt]
            if pc["start"]:
                tsub = tsub[tsub["date"] >= pd.Timestamp(pc["start"])]
            rv = gk_variance(tsub)
            res = run_oos(rv, py, px)
            if res["n_oos"] < 252:
                print(f"  [{tgt}] SKIP: only {res['n_oos']} OOS obs")
                continue
            ev = evaluate(res)
            ins = insample_ect_tstat(rv, py, px)
            tgt_entry = {"target": tgt, "oos": ev, "insample_ect": ins,
                         "sample_end_target": str(rv.index.max().date())}
            pair_entry["targets"].append(tgt_entry)
            print(f"  [{tgt}] n_oos={ev['n_oos']} QLIKE HAR={ev['qlike_har']:.5f} "
                  f"HAR+ECT={ev['qlike_har_ect']:.5f} ({ev['qlike_pct_improvement']:+.2f}%) "
                  f"DM_t={ev['dm_t_ect_vs_har']:+.2f} HLN_t={ev['hln_t']:+.2f} p={ev['hln_p']:.3f}")

            bar_labels.append(f"{pc['name']}\n->{tgt}")
            bar_har.append(ev["qlike_har"])
            bar_ect.append(ev["qlike_har_ect"])

            # keep the VIX->SPY config (or first cointegrated) for the overlay fig
            if fig_cfg is None and eg["cointegrated_5pct"]:
                fig_cfg = {"name": pc["name"], "target": tgt, "res": res}

        results["pairs"].append(pair_entry)

    # ---- verdict ----
    any_help = False
    for p in results["pairs"]:
        for t in p["targets"]:
            if t["oos"]["ect_helps_hln_5pct"]:
                any_help = True
    strict_help = any(
        t["oos"]["ect_helps_harvey_strict"]
        for p in results["pairs"] for t in p["targets"]
    )
    results["verdict"] = {
        "any_pair_ect_helps_5pct": any_help,
        "any_pair_ect_helps_harvey_strict": strict_help,
        "summary": (
            "NULL: cointegration ECT provides no robust incremental HAR-RV "
            "forecasting power" if not any_help else
            ("CONDITIONAL: ECT helps at 5% for >=1 pair but not Harvey-strict |t|>3"
             if not strict_help else
             "POSITIVE: ECT helps at Harvey-strict |t|>3 for >=1 pair")
        ),
    }

    out = HERE / "k1616_cointegration_ect_har_rv_results.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nWrote {out}")

    # ---- figures ----
    make_figures(results, fig_cfg, bar_labels, bar_har, bar_ect)


def make_figures(results, fig_cfg, bar_labels, bar_har, bar_ect):
    # Figure 1: ECT time series + target RV overlay
    if fig_cfg is not None:
        res = fig_cfg["res"]
        fig, ax1 = plt.subplots(figsize=(11, 5))
        ax1.plot(res["dates"], res["ect_used"], color="#1f77b4", lw=0.8, label="ECT_{t-1} (expanding beta)")
        ax1.axhline(0, color="grey", lw=0.6, ls="--")
        ax1.set_ylabel("Error-correction term (ECT)", color="#1f77b4")
        ax1.tick_params(axis="y", labelcolor="#1f77b4")
        ax2 = ax1.twinx()
        ax2.plot(res["dates"], np.sqrt(res["actual"]) * np.sqrt(252) * 100,
                 color="#d62728", lw=0.7, alpha=0.7, label="Realized vol (annualized %)")
        ax2.set_ylabel("Annualized realized vol (%)", color="#d62728")
        ax2.tick_params(axis="y", labelcolor="#d62728")
        ax1.set_title(f"k1616 | {fig_cfg['name']} error-correction term vs realized vol "
                      f"(target {fig_cfg['target']})")
        fig.tight_layout()
        fig.savefig(HERE / "k1616_ect_vs_rv.png", dpi=130)
        plt.close(fig)

    # Figure 2: QLIKE bar chart HAR vs HAR+ECT
    if bar_labels:
        x = np.arange(len(bar_labels))
        w = 0.38
        fig, ax = plt.subplots(figsize=(max(8, 1.5 * len(bar_labels)), 5))
        ax.bar(x - w / 2, bar_har, w, label="HAR", color="#4c72b0")
        ax.bar(x + w / 2, bar_ect, w, label="HAR+ECT", color="#dd8452")
        ax.set_xticks(x)
        ax.set_xticklabels(bar_labels, fontsize=8)
        ax.set_ylabel("Mean OOS QLIKE (lower = better)")
        ax.set_title("k1616 | HAR vs HAR+ECT out-of-sample QLIKE by pair->target")
        ax.legend()
        for xi, (h, e) in enumerate(zip(bar_har, bar_ect)):
            ax.text(xi, max(h, e) * 1.01, f"{(h - e) / h * 100:+.1f}%",
                    ha="center", va="bottom", fontsize=7)
        fig.tight_layout()
        fig.savefig(HERE / "k1616_qlike_bar.png", dpi=130)
        plt.close(fig)


if __name__ == "__main__":
    main()
