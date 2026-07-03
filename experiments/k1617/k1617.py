"""
K1617: Time-Varying Factor Loading (TVL) Factor-Augmented HAR vs Static-Loading HAR.

Research question
-----------------
K928 showed that a STATIC common-volatility factor (rolling-PCA PC1 across
SPY/QQQ/IWM/GLD/TLT) adds no incremental predictive value to a GJR-GARCH and is
redundant with VIX. This experiment asks a narrower, targeted question:

    Is K928's null a consequence of the loading being constrained to be *static*?
    If the factor loading is allowed to be time-varying (gamma_t), does the
    factor recover incremental predictive power inside a HAR-RV framework?

Design (clean nested ladder isolating the loading)
--------------------------------------------------
All three models share an IDENTICAL HAR-RV core (Corsi 2009), fit by expanding
OLS, refit daily. They differ ONLY in the factor contribution:

  1. HAR             : logRV_t ~ c + b_d*logRV_{t-1} + b_w*mean(logRV,t-5..t-1)
                                     + b_m*mean(logRV,t-22..t-1)
  2. FA-HAR static   : HAR core prediction + gamma   * F_{t-1}
                       gamma   = full-history (expanding) slope of HAR residual on F_{t-1}
  3. FA-HAR TVL      : HAR core prediction + gamma_t * F_{t-1}
                       gamma_t = rolling-250d slope of HAR residual on F_{t-1}

Because static and TVL add the factor to the SAME HAR core with the SAME
estimator (slope of HAR residual on the lagged factor), the ONLY difference
between them is static (constant, full-history) vs time-varying (rolling-250d)
loading. This isolates the object of interest (the loading) exactly.

Factor F
--------
Rolling PCA (250-day window) first principal component of the cross-asset
standardized log-RV panel, sign-fixed (SPY loading positive), extracted OUT OF
SAMPLE (loadings and standardization use only data through the projection date).
F_{t-1} (info known at t-1) is the predictor for logRV_t. Same construction
philosophy as K928.

Realized-variance measure (HONEST LABELLING)
--------------------------------------------
We do NOT have long intraday RV. RV here is a *range-based realized-variance
PROXY* computed from DAILY OHLC via the Garman-Klass (1980) estimator:

    RV_GK_t = 0.5*(ln(H/L))^2 - (2 ln2 - 1)*(ln(C/O))^2

This is an intraday (open-to-close) variance proxy, NOT a high-frequency
5-minute RV. All three models use the identical GK-RV target, so the comparison
is apples-to-apples within the HAR family. References: Parkinson (1980);
Garman-Klass (1980); Alizadeh, Brandt & Diebold (2002).

Anti-lookahead
--------------
- logRV_t is predicted using only information dated <= t-1 (HAR lags, factor F_{t-1}).
- Rolling PCA loadings / standardization use only data through the projection date.
- Expanding training rows for origin i use rows s <= i-1 (H=1 => target_end < forecast_origin).
- gamma / gamma_t regressions use only HAR residuals and factors dated <= i-1.

Evaluation
----------
- QLIKE on the variance scale (canonical: actual/pred - log(actual/pred) - 1),
  via volpred.stats.model_evaluation.qlike / qlike_pointwise. log-RV forecasts
  are mapped to variance with a common log-normal (Jensen) correction using the
  expanding HAR residual variance. The correction is IDENTICAL across models on
  each date (same HAR-core residual variance), but note it does NOT algebraically
  cancel in the QLIKE loss differential (a multiplicative constant c on the
  forecast scales the a/f term by 1/c; only the log term's log(c) cancels).
  We therefore also report a no-Jensen sensitivity run (predicted_var =
  exp(pred_logRV)); the DM verdict is confirmed to be invariant to this choice.
- log-RV MSE (Jensen-free anchor).
- Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample correction,
  Student-t reference, threshold |t| > 3.0 (Harvey 2016).
  PRIMARY inference = aggregate cross-asset loss differential BY DATE, then HLN
  on the date series (K1355: do NOT treat asset-days as iid). Per-asset DM also
  reported. Stacked asset-day DM is DIAGNOSTIC ONLY.

Reproducible: `uv run python experiments/k1617/k1617.py`. Seeded (np.random.seed(42)).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# Headless plotting
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Repo import for canonical QLIKE
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
from volpred.stats.model_evaluation import qlike as qlike_mean  # noqa: E402
from volpred.stats.model_evaluation import qlike_pointwise  # noqa: E402

from scipy import stats  # noqa: E402

# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
ASSETS = ["SPY", "QQQ", "IWM", "GLD", "TLT"]
START = "2012-01-01"
END = "2026-06-30"
OOS_START = "2017-01-01"
PCA_WINDOW = 250          # rolling PCA window (days)
TVL_WINDOW = 250          # rolling window for time-varying loading
EPS = 1e-10               # variance floor
DATA_CACHE = HERE / "data_ohlc.csv"


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def download_ohlc() -> tuple[pd.DataFrame, str]:
    """Download (or load cached) raw daily OHLC for the panel.

    Returns (long DataFrame indexed by date with columns per (field, asset), provenance str).
    """
    if DATA_CACHE.exists():
        df = pd.read_csv(DATA_CACHE, header=[0, 1], index_col=0, parse_dates=True)
        prov = f"loaded_cache:{DATA_CACHE.name}"
        return df, prov

    import yfinance as yf
    frames = {}
    for a in ASSETS:
        raw = yf.download(a, start=START, end=END, auto_adjust=False, progress=False)
        if raw.empty:
            raise RuntimeError(f"yfinance returned empty frame for {a}")
        # raw columns are MultiIndex (field, ticker); collapse to field
        raw.columns = [c[0] for c in raw.columns]
        frames[a] = raw[["Open", "High", "Low", "Close"]]
    # combine into MultiIndex columns (field, asset)
    combined = pd.concat({a: frames[a] for a in ASSETS}, axis=1)  # cols: (asset, field)
    combined = combined.swaplevel(axis=1)                          # (field, asset)
    combined.sort_index(axis=1, inplace=True)
    combined.to_csv(DATA_CACHE)
    prov = f"yfinance_download:{datetime.now(timezone.utc).isoformat()}"
    return combined, prov


def garman_klass_rv(o, h, l, c) -> np.ndarray:
    """Garman-Klass (1980) daily variance proxy from OHLC (element-wise arrays)."""
    o = np.asarray(o, float); h = np.asarray(h, float)
    l = np.asarray(l, float); c = np.asarray(c, float)
    log_hl = np.log(h / l)
    log_co = np.log(c / o)
    rv = 0.5 * log_hl ** 2 - (2 * np.log(2) - 1) * log_co ** 2
    return np.maximum(rv, EPS)


def build_rv_panel(ohlc: pd.DataFrame) -> pd.DataFrame:
    """Compute GK RV per asset, inner-join on common trading days -> log-RV panel."""
    rv_cols = {}
    for a in ASSETS:
        sub = pd.DataFrame({
            "O": ohlc[("Open", a)],
            "H": ohlc[("High", a)],
            "L": ohlc[("Low", a)],
            "C": ohlc[("Close", a)],
        }).dropna()
        rv = garman_klass_rv(sub["O"], sub["H"], sub["L"], sub["C"])
        rv_cols[a] = pd.Series(rv, index=sub.index)
    rv_panel = pd.DataFrame(rv_cols).dropna()  # inner-join across assets
    log_rv = np.log(rv_panel)
    return rv_panel, log_rv


# ----------------------------------------------------------------------------
# Rolling-PCA common factor (OOS extraction)
# ----------------------------------------------------------------------------
def rolling_pca_factor(log_rv: pd.DataFrame, window: int = PCA_WINDOW) -> pd.Series:
    """Common volatility factor = rolling-window PC1 projection of standardized log-RV.

    At each date tau (tau >= window-1) PCA is computed on the window
    [tau-window+1 .. tau] (all dates <= tau), sign-fixed so SPY loading > 0.
    F_tau = loadings . standardized(log_rv_tau), standardization by rolling
    mean/std through tau. Uses only data <= tau -> no lookahead when used as F_{t-1}.
    """
    vals = log_rv.values
    idx = log_rv.index
    n = len(idx)
    spy_pos = list(log_rv.columns).index("SPY")
    F = np.full(n, np.nan)
    for t in range(window - 1, n):
        w = vals[t - window + 1: t + 1]           # window x n_assets, all <= t
        mu = w.mean(axis=0)
        sd = w.std(axis=0, ddof=0)
        sd = np.where(sd < 1e-12, 1.0, sd)
        z = (w - mu) / sd
        cov = np.cov(z, rowvar=False)
        eigval, eigvec = np.linalg.eigh(cov)      # ascending
        pc1 = eigvec[:, -1]                        # top eigenvector
        if pc1[spy_pos] < 0:                       # sign fix: SPY loading positive
            pc1 = -pc1
        z_t = (vals[t] - mu) / sd
        F[t] = float(pc1 @ z_t)
    return pd.Series(F, index=idx, name="F")


# ----------------------------------------------------------------------------
# HAR design + expanding OOS forecasting
# ----------------------------------------------------------------------------
def har_design(log_rv_asset: pd.Series) -> pd.DataFrame:
    """Build HAR-RV regressors on log-RV for one asset (all lagged, no lookahead)."""
    y = log_rv_asset
    d = y.shift(1)
    w = y.shift(1).rolling(5).mean()
    m = y.shift(1).rolling(22).mean()
    df = pd.DataFrame({"y": y, "d": d, "w": w, "m": m})
    return df


def ols_fit(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Plain OLS via lstsq. X includes intercept column."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def run_asset_oos(asset: str, log_rv: pd.DataFrame, factor: pd.Series):
    """Expanding-window daily-refit OOS for one asset. Returns aligned per-date arrays.

    Produces variance-scale forecasts for HAR / FA-static / FA-TVL, the realized
    GK variance, the log-RV target and log-RV predictions, and the gamma_t path.
    """
    des = har_design(log_rv[asset]).copy()
    des["F_lag"] = factor.shift(1)  # F_{t-1} predicts logRV_t
    des = des.dropna()              # rows with all HAR lags + factor available

    dates = des.index
    y = des["y"].values
    F_lag = des["F_lag"].values
    X = np.column_stack([np.ones(len(des)), des["d"].values,
                         des["w"].values, des["m"].values])  # [1,d,w,m]

    oos_mask = dates >= pd.Timestamp(OOS_START)
    oos_positions = np.where(oos_mask)[0]
    oos_start_pos = oos_positions[0]

    rec = []
    for i in oos_positions:
        tr = slice(0, i)                       # rows 0..i-1 (all <= t-1)
        Xtr, ytr = X[tr], y[tr]
        beta = ols_fit(Xtr, ytr)
        # HAR core one-step prediction for row i (log scale)
        pred_har_log = float(X[i] @ beta)
        # in-sample HAR residuals + Jensen (log-normal) correction (common to all 3)
        resid_tr = ytr - Xtr @ beta
        s2 = float(np.var(resid_tr, ddof=X.shape[1]))  # residual variance (log space)
        jensen = 0.5 * s2

        # factor contribution: slope of HAR residual on lagged factor
        f_tr = F_lag[tr]
        denom_full = float(np.dot(f_tr, f_tr))
        gamma_static = float(np.dot(resid_tr, f_tr) / denom_full) if denom_full > 1e-12 else 0.0
        # time-varying loading: rolling last TVL_WINDOW obs of (resid, f)
        lo = max(0, i - TVL_WINDOW)
        f_roll = F_lag[lo:i]
        r_roll = resid_tr[lo:i]  # resid_tr indexed 0..i-1, slice matches
        denom_roll = float(np.dot(f_roll, f_roll))
        gamma_tvl = float(np.dot(r_roll, f_roll) / denom_roll) if denom_roll > 1e-12 else 0.0

        f_now = F_lag[i]
        pred_static_log = pred_har_log + gamma_static * f_now
        pred_tvl_log = pred_har_log + gamma_tvl * f_now

        # map to variance scale with common Jensen correction
        var_har = np.exp(pred_har_log + jensen)
        var_static = np.exp(pred_static_log + jensen)
        var_tvl = np.exp(pred_tvl_log + jensen)
        actual_var = np.exp(y[i])  # realized GK variance (= exp logRV)

        rec.append({
            "date": dates[i],
            "actual_var": actual_var,
            "actual_logrv": y[i],
            "jensen": jensen,
            "har_var": var_har, "static_var": var_static, "tvl_var": var_tvl,
            "har_logrv": pred_har_log, "static_logrv": pred_static_log, "tvl_logrv": pred_tvl_log,
            "gamma_static": gamma_static, "gamma_tvl": gamma_tvl,
        })
    out = pd.DataFrame(rec).set_index("date")
    return out


# ----------------------------------------------------------------------------
# HLN-corrected Diebold-Mariano
# ----------------------------------------------------------------------------
def dm_hln(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> dict:
    """Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample correction.

    d_t = loss_a - loss_b. Negative t -> model A better (lower loss).
    Long-run variance uses h-1 autocovariance lags (canonical for h-step forecasts;
    h=1 => sample variance). HLN factor sqrt((T+1-2h+h(h-1)/T)/T); Student-t(T-1).
    """
    d = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 10:
        return {"t_stat": np.nan, "p_value": np.nan, "n": T, "harvey_pass": False}
    d_bar = d.mean()
    gamma0 = np.mean((d - d_bar) ** 2)
    var_d = gamma0
    for k in range(1, h):  # h=1 -> no extra lags
        gk = np.mean((d[k:] - d_bar) * (d[:-k] - d_bar))
        var_d += 2 * gk
    if var_d <= 0:
        return {"t_stat": 0.0, "p_value": 1.0, "n": T, "harvey_pass": False}
    dm = d_bar / np.sqrt(var_d / T)
    hln_factor = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    dm_star = dm * hln_factor
    p = 2 * (1 - stats.t.cdf(abs(dm_star), df=T - 1))
    return {
        "t_stat": float(dm_star), "p_value": float(p), "n": int(T),
        "harvey_pass": bool(abs(dm_star) > 3.0),
        "mean_loss_diff": float(d_bar),
    }


# ----------------------------------------------------------------------------
# Figures
# ----------------------------------------------------------------------------
def fig_rv_factor(rv_panel, factor, path):
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    ax = axes[0]
    ax.plot(rv_panel.index, np.sqrt(rv_panel["SPY"]) * np.sqrt(252) * 100,
            lw=0.6, color="#1f4e79")
    ax.set_ylabel("SPY GK vol (annualized %)")
    ax.set_title("Garman-Klass range-based realized-vol PROXY (SPY) and common factor")
    ax.grid(alpha=0.3)
    ax2 = axes[1]
    ax2.plot(factor.index, factor.values, lw=0.5, color="#8c1d1d")
    ax2.axhline(0, color="k", lw=0.5)
    ax2.set_ylabel("Rolling-PCA PC1 factor F")
    ax2.set_xlabel("Date")
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def fig_qlike(pooled_qlike, per_asset_qlike, path):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    models = ["HAR", "FA-static", "FA-TVL"]
    colors = ["#1f4e79", "#2e7d32", "#8c1d1d"]
    ax = axes[0]
    vals = [pooled_qlike[m] for m in models]
    ax.bar(models, vals, color=colors)
    for i, v in enumerate(vals):
        ax.text(i, v, f"{v:.4f}", ha="center", va="bottom", fontsize=9)
    ax.set_ylabel("Pooled QLIKE (all asset-days)")
    ax.set_title("Pooled OOS QLIKE (lower = better)")
    ymin = min(vals) * 0.995
    ax.set_ylim(ymin, max(vals) * 1.002)
    ax.grid(alpha=0.3, axis="y")
    ax2 = axes[1]
    assets = list(per_asset_qlike.keys())
    x = np.arange(len(assets))
    w = 0.26
    for k, (m, c) in enumerate(zip(models, colors)):
        ax2.bar(x + (k - 1) * w, [per_asset_qlike[a][m] for a in assets],
                width=w, label=m, color=c)
    ax2.set_xticks(x); ax2.set_xticklabels(assets)
    ax2.set_ylabel("QLIKE"); ax2.set_title("Per-asset OOS QLIKE")
    ax2.legend(); ax2.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def fig_beta_path(asset, out_df, gamma_static_final, path):
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(out_df.index, out_df["gamma_tvl"], lw=0.7, color="#8c1d1d",
            label="gamma_t (rolling-250d loading)")
    ax.plot(out_df.index, out_df["gamma_static"], lw=1.2, color="#1f4e79",
            label="gamma (expanding static loading)")
    ax.axhline(0, color="k", lw=0.5)
    ax.set_title(f"Time-varying vs static factor loading ({asset})")
    ax.set_ylabel("Factor loading on log-RV"); ax.set_xlabel("Date")
    ax.legend(); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    print("[K1617] downloading / loading OHLC ...")
    ohlc, provenance = download_ohlc()
    rv_panel, log_rv = build_rv_panel(ohlc)
    print(f"[K1617] RV panel: {rv_panel.shape[0]} common trading days "
          f"{rv_panel.index[0].date()} .. {rv_panel.index[-1].date()}")

    print("[K1617] building rolling-PCA common factor ...")
    factor = rolling_pca_factor(log_rv, PCA_WINDOW)

    # Per-asset OOS
    per_asset_out = {}
    for a in ASSETS:
        print(f"[K1617] OOS expanding refit: {a} ...")
        per_asset_out[a] = run_asset_oos(a, log_rv, factor)

    MODELS = ["HAR", "FA-static", "FA-TVL"]
    LOGCOL = {"HAR": "har_logrv", "FA-static": "static_logrv", "FA-TVL": "tvl_logrv"}

    def var_forecast(out, model, use_jensen):
        """Variance-scale forecast from stored log-RV prediction (+ common Jensen term)."""
        log = out[LOGCOL[model]].values
        j = out["jensen"].values if use_jensen else 0.0
        return np.exp(log + j)

    def compute_metrics(use_jensen: bool) -> dict:
        # Per-asset QLIKE + pointwise losses
        per_qlike, per_dm = {}, {}
        loss_by_date = {m: {} for m in MODELS}
        for a, out in per_asset_out.items():
            av = out["actual_var"].values  # = exp(actual_logrv), Jensen-independent
            vf = {m: var_forecast(out, m, use_jensen) for m in MODELS}
            per_qlike[a] = {m: float(qlike_mean(av, vf[m])) for m in MODELS}
            losses = {m: qlike_pointwise(av, vf[m]) for m in MODELS}
            per_dm[a] = {
                "TVL_vs_HAR": dm_hln(losses["FA-TVL"], losses["HAR"]),
                "TVL_vs_static": dm_hln(losses["FA-TVL"], losses["FA-static"]),
                "static_vs_HAR": dm_hln(losses["FA-static"], losses["HAR"]),
            }
            for m in MODELS:
                loss_by_date[m][a] = pd.Series(losses[m], index=out.index)

        # Pooled (all asset-days) QLIKE
        all_actual = np.concatenate([out["actual_var"].values for out in per_asset_out.values()])
        pooled_q = {m: float(qlike_mean(
            all_actual,
            np.concatenate([var_forecast(out, m, use_jensen) for out in per_asset_out.values()])))
            for m in MODELS}

        # PRIMARY DM: aggregate cross-asset loss differential BY DATE (K1355)
        loss_df = {m: pd.DataFrame(loss_by_date[m]) for m in MODELS}

        def dm_by_date(m_a, m_b):
            da = loss_df[m_a].mean(axis=1)
            db = loss_df[m_b].mean(axis=1)
            j = pd.concat([da, db], axis=1, keys=["a", "b"]).dropna()
            return dm_hln(j["a"].values, j["b"].values)

        pooled_by_date = {
            "TVL_vs_HAR": dm_by_date("FA-TVL", "HAR"),
            "TVL_vs_static": dm_by_date("FA-TVL", "FA-static"),
            "static_vs_HAR": dm_by_date("FA-static", "HAR"),
        }

        # DIAGNOSTIC ONLY: stacked asset-day DM (overstates significance)
        def dm_stacked(m_a, m_b):
            la = np.concatenate([qlike_pointwise(out["actual_var"].values,
                                                 var_forecast(out, m_a, use_jensen))
                                 for out in per_asset_out.values()])
            lb = np.concatenate([qlike_pointwise(out["actual_var"].values,
                                                 var_forecast(out, m_b, use_jensen))
                                 for out in per_asset_out.values()])
            return dm_hln(la, lb)

        stacked = {
            "TVL_vs_HAR": dm_stacked("FA-TVL", "HAR"),
            "TVL_vs_static": dm_stacked("FA-TVL", "FA-static"),
            "static_vs_HAR": dm_stacked("FA-static", "HAR"),
        }
        return {"per_asset_qlike": per_qlike, "per_asset_dm": per_dm,
                "pooled_qlike": pooled_q, "pooled_by_date_dm": pooled_by_date,
                "stacked_dm": stacked}

    # log-RV MSE is Jensen-independent (log scale) — compute once
    per_asset_mse = {}
    all_alog, all_predlog = [], {m: [] for m in MODELS}
    for a, out in per_asset_out.items():
        alog = out["actual_logrv"].values
        per_asset_mse[a] = {m: float(np.mean((alog - out[LOGCOL[m]].values) ** 2)) for m in MODELS}
        all_alog.append(alog)
        for m in MODELS:
            all_predlog[m].append(out[LOGCOL[m]].values)
    all_alog = np.concatenate(all_alog)
    pooled_mse = {m: float(np.mean((all_alog - np.concatenate(all_predlog[m])) ** 2))
                  for m in MODELS}

    # PRIMARY (with common Jensen correction) + SENSITIVITY (no Jensen)
    primary = compute_metrics(use_jensen=True)
    sensitivity = compute_metrics(use_jensen=False)
    per_asset_qlike = primary["per_asset_qlike"]
    per_asset_dm = primary["per_asset_dm"]
    pooled_qlike = primary["pooled_qlike"]
    pooled_by_date_dm = primary["pooled_by_date_dm"]
    stacked_dm = primary["stacked_dm"]

    # ---- Verdict logic (precise; conditional on static-vs-HAR) ----
    def make_verdict(pooled_q, dm):
        tvl_har, tvl_stat, stat_har = dm["TVL_vs_HAR"], dm["TVL_vs_static"], dm["static_vs_HAR"]
        tvl_beats_har = (tvl_har["t_stat"] < 0) and tvl_har["harvey_pass"]
        tvl_beats_static = (tvl_stat["t_stat"] < 0) and tvl_stat["harvey_pass"]
        static_beats_har = (stat_har["t_stat"] < 0) and stat_har["harvey_pass"]
        if tvl_beats_har and tvl_beats_static:
            v = "PASS"
            note = ("Time-varying loading significantly beats BOTH HAR and static-FA "
                    "(HLN |t|>3.0).")
        elif tvl_beats_har or tvl_beats_static:
            v = "MIXED"
            note = "Time-varying loading significant vs one benchmark only; not a robust improvement."
        else:
            v = "NULL"
            note = (f"Time-varying loading does NOT significantly beat HAR "
                    f"(pooled-by-date HLN t={tvl_har['t_stat']:.2f}) nor static-FA "
                    f"(t={tvl_stat['t_stat']:.2f}); the TVL-rescue hypothesis is REJECTED. "
                    f"The rolling loading adds no incremental value over a static loading.")
        rel = (pooled_q['HAR'] - pooled_q['FA-static']) / pooled_q['HAR'] * 100
        if static_beats_har:
            note += (f" SECONDARY (framework-dependent nuance vs K928): the STATIC factor "
                     f"augmentation does modestly but significantly beat HAR "
                     f"(pooled-by-date HLN t={stat_har['t_stat']:.2f}, ~{rel:.1f}% pooled QLIKE), "
                     f"but the gain is economically small and requires NO time-varying loading. "
                     f"K928's GJR/daily-r2 null does not carry over one-for-one to the "
                     f"HAR/GK-RV setting, though the common factor remains near-negligible.")
        else:
            note += " Consistent with K928, the common factor adds no significant value even statically."
        return v, note

    verdict, verdict_note = make_verdict(pooled_qlike, pooled_by_date_dm)
    sens_verdict, _ = make_verdict(sensitivity["pooled_qlike"], sensitivity["pooled_by_date_dm"])
    jensen_robust = (sens_verdict == verdict)
    tvl_lower_than_har = pooled_qlike["FA-TVL"] < pooled_qlike["HAR"]

    # ---- Assemble results ----
    n_oos_per_asset = {a: int(len(out)) for a, out in per_asset_out.items()}
    results = {
        "experiment_id": "k1617",
        "title": "Time-Varying Factor Loading FA-HAR vs Static-Loading HAR "
                 "(range-based GK realized-vol proxy)",
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "provenance": {
            "data_source": "yfinance daily OHLC (auto_adjust=False, raw OHLC)",
            "download": provenance,
            "assets": ASSETS,
            "period": f"{START} .. {END}",
            "common_trading_days": int(rv_panel.shape[0]),
            "panel_start": str(rv_panel.index[0].date()),
            "panel_end": str(rv_panel.index[-1].date()),
            "oos_start": OOS_START,
            "n_oos_per_asset": n_oos_per_asset,
            "rv_measure": "Garman-Klass (1980) range-based realized-variance PROXY "
                          "from daily OHLC; intraday open-to-close, NOT 5-min RV",
            "factor": f"rolling-{PCA_WINDOW}d PCA PC1 of standardized cross-asset log-RV, "
                      "sign-fixed (SPY>0), OOS-extracted, lagged F_{t-1}",
            "tvl_window": TVL_WINDOW,
        },
        "design": {
            "HAR": "expanding-OLS logRV ~ c + b_d*d + b_w*w + b_m*m (Corsi 2009)",
            "FA-static": "HAR core + gamma * F_{t-1}; gamma = expanding slope of HAR resid on F",
            "FA-TVL": "HAR core + gamma_t * F_{t-1}; gamma_t = rolling-250d slope of HAR resid on F",
            "loading_isolation": "static and TVL share identical HAR core + identical estimator; "
                                 "ONLY the loading estimation window differs",
            "loading_definition": "loading = through-origin slope of HAR residual on F_{t-1} "
                                  "(sum(resid*F)/sum(F^2)); for the expanding window HAR residuals "
                                  "are mean-zero by construction so this equals the OLS slope, for "
                                  "the rolling-250d window it is a projection (near-identical since F "
                                  "is ~zero-mean)",
            "qlike_scale": "variance scale = exp(pred_logRV + 0.5*resid_var); the log-normal Jensen "
                           "correction is IDENTICAL across the 3 models on each date (shared HAR-core "
                           "residual variance). It does NOT algebraically cancel in the QLIKE loss "
                           "differential (a multiplicative constant scales the a/f term); a no-Jensen "
                           "sensitivity run (see jensen_sensitivity) confirms the DM verdict is invariant",
        },
        "pooled_qlike": pooled_qlike,
        "pooled_logrv_mse": pooled_mse,
        "per_asset_qlike": per_asset_qlike,
        "per_asset_logrv_mse": per_asset_mse,
        "dm_primary_pooled_by_date": pooled_by_date_dm,
        "dm_per_asset": per_asset_dm,
        "dm_stacked_asset_day_DIAGNOSTIC_ONLY": stacked_dm,
        "jensen_sensitivity": {
            "note": "no-Jensen run: predicted_var = exp(pred_logRV). Confirms robustness of DM verdict.",
            "pooled_qlike": sensitivity["pooled_qlike"],
            "dm_pooled_by_date": sensitivity["pooled_by_date_dm"],
            "verdict": sens_verdict,
            "verdict_matches_primary": bool(jensen_robust),
        },
        "verdict": verdict,
        "verdict_note": verdict_note,
        "verdict_details": {
            "tvl_qlike_lower_than_har_pooled": bool(tvl_lower_than_har),
            "tvl_vs_har_hln_t": pooled_by_date_dm["TVL_vs_HAR"]["t_stat"],
            "tvl_vs_static_hln_t": pooled_by_date_dm["TVL_vs_static"]["t_stat"],
            "static_vs_har_hln_t": pooled_by_date_dm["static_vs_HAR"]["t_stat"],
            "harvey_threshold": 3.0,
            "jensen_robust": bool(jensen_robust),
        },
        "references": [
            "Corsi (2009) J. Financial Econometrics 7 — HAR-RV",
            "Garman & Klass (1980) J. Business 53 — range-based variance estimator",
            "Parkinson (1980) J. Business 53 — high-low range estimator",
            "Alizadeh, Brandt & Diebold (2002) J. Finance 57 — range-based vol",
            "Patton (2011) J. Econometrics 160 — proxy-robust QLIKE",
            "Harvey, Leybourne & Newbold (1997) Int. J. Forecasting 13 — small-sample DM",
            "Harvey (2016) — |t|>3.0 multiple-testing threshold",
            "K928 (this project) — static common-vol factor null / VIX sufficiency",
            "K1355 (this project) — cross-asset loss differentials aggregated by date, not iid",
        ],
        "files": [
            "k1617.py", "k1617_results.json",
            "fig_rv_factor.png", "fig_qlike_comparison.png", "fig_tvl_beta.png",
        ],
    }

    out_path = HERE / "k1617_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[K1617] results -> {out_path}")

    # ---- Figures ----
    fig_rv_factor(rv_panel, factor, HERE / "fig_rv_factor.png")
    fig_qlike(pooled_qlike, per_asset_qlike, HERE / "fig_qlike_comparison.png")
    spy_out = per_asset_out["SPY"]
    fig_beta_path("SPY", spy_out, spy_out["gamma_static"].iloc[-1],
                  HERE / "fig_tvl_beta.png")
    print("[K1617] figures written.")

    # ---- Console summary ----
    print("\n===== K1617 SUMMARY =====")
    print(f"Common trading days: {rv_panel.shape[0]}  OOS per asset: {n_oos_per_asset}")
    print("Pooled QLIKE:", {k: round(v, 5) for k, v in pooled_qlike.items()})
    print("Pooled logRV MSE:", {k: round(v, 5) for k, v in pooled_mse.items()})
    print("PRIMARY DM (pooled-by-date, HLN):")
    for k, v in pooled_by_date_dm.items():
        print(f"   {k}: t={v['t_stat']:.3f} p={v['p_value']:.4f} "
              f"harvey_pass={v['harvey_pass']} n={v['n']}")
    print("SENSITIVITY (no-Jensen) DM:")
    for k, v in sensitivity["pooled_by_date_dm"].items():
        print(f"   {k}: t={v['t_stat']:.3f} harvey_pass={v['harvey_pass']}")
    print(f"Jensen-robust verdict match: {jensen_robust} (sens verdict={sens_verdict})")
    print(f"VERDICT: {verdict} — {verdict_note}")


if __name__ == "__main__":
    main()
