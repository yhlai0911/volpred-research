#!/usr/bin/env python
"""K1606 — Deposit-flightiness state variable predicting regional-bank realized volatility.

TIME-SERIES REFRAME of the original cross-sectional uninsured-deposit hypothesis.
The original backlog title asked whether a bank's *uninsured-deposit share* has
cross-sectional predictive power for its equity volatility. That needs FFIEC
call-report bank-level uninsured-deposit ratios, which this platform does NOT
have. Instead we run a DATA-AVAILABLE time-series reframe:

    Does an AGGREGATE deposit-flightiness state variable (built from FRED weekly
    total commercial-bank deposits) predict the FUTURE realized volatility of the
    regional-bank ETF (KRE) and its liquid components, incrementally over an
    HAR-RV baseline?

What the reframe SACRIFICES: no bank-level cross-section, no per-bank uninsured
share, no cross-sectional uniqueness claim. It only tests one SYSTEMATIC
time-series regime signal. See README for the full honesty statement.

Method (strict, per .claude/rules/experiments.md):
  * RV proxy: Parkinson daily variance from high-low range.
  * Target: forward H-day AVERAGE RV, y_t = mean(RV_{t+1..t+H}), H=5.
  * Baseline: HAR-RV (RV_d, RV_w=avg5, RV_m=avg22).
  * Augmented: HAR-RV + lagged aggregate deposit-flightiness.
  * Lookahead defence: features use info set at close of day t; target is strictly
    over (t, t+H]. Deposit signal carries an explicit publication-lag (obs date +9
    calendar days availability) before it can enter F_t. OOS expanding refit uses
    an H-row embargo so every training row j satisfies target_end(j)=j+H < origin i.
  * Evaluation: canonical QLIKE (actual/pred - log(actual/pred) - 1) + MSE.
  * Test: Diebold-Mariano with Newey-West HAC at horizon=H, plus a moving-block
    bootstrap on the loss differential (block>=H handles the overlap).
  * Seed fixed = 42.

All numbers come from a live run. No fabrication. If data fetch fails the script
writes data_blocked=true rather than inventing numbers.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

HERE = Path(__file__).resolve().parent
PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))
from volpred.stats.model_evaluation import qlike, qlike_pointwise, mse as mse_fn, dm_test  # noqa: E402

# ── Config ───────────────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)
H = 5                       # forward horizon (trading days) — weekly
START = "2015-01-01"
END = datetime.today().strftime("%Y-%m-%d")
PRICE_START = "2014-06-01"  # extra lead-in for HAR-monthly warmup
FRED_START = "2013-01-01"   # extra lead-in for 52-week deposit z-score
KRE = "KRE"
COMPONENTS = ["ZION", "KEY", "RF", "FITB", "HBAN", "CMA", "MTB", "WAL"]
FRED_SERIES = "DPSACBW027SBOG"   # Deposits, All Commercial Banks, weekly, SA
PUB_LAG_DAYS = 9                 # H.8 publishes prior-Wed data on Fri (+buffer)
TRAIN_FRAC = 0.60
ZWIN = 52                        # weeks for rolling deposit-growth z-score
BOOT_BLOCK = 10                  # moving-block length (>= H, covers overlap)
N_BOOT = 2000
SVB_WINDOW = ("2023-03-08", "2023-03-20")


# ── Data helpers ─────────────────────────────────────────────────────────────
def get_fred_api_key():
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    for fname in (".env.local", ".env"):
        p = PROJECT / fname
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip().startswith("FRED_API_KEY="):
                    return line.split("=", 1)[1].strip()
    return None


def fetch_fred(series_id, api_key):
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": api_key,
              "file_type": "json", "observation_start": FRED_START}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    obs = r.json()["observations"]
    df = pd.DataFrame(obs)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    s = df.dropna(subset=["value"]).set_index("date")["value"].sort_index()
    return s


def fetch_hlc(ticker):
    import yfinance as yf
    df = yf.download(ticker, start=PRICE_START, end=END,
                     auto_adjust=True, progress=False)
    if df is None or len(df) == 0:
        raise RuntimeError(f"yfinance returned empty for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    out = df[["High", "Low", "Close"]].copy()
    out.columns = ["high", "low", "close"]
    return out.dropna()


def parkinson_rv(high, low):
    """Parkinson (1980) daily variance from the high-low range."""
    return (1.0 / (4.0 * np.log(2.0))) * (np.log(high / low)) ** 2


def build_deposit_flightiness(dep_weekly):
    """Aggregate deposit-flightiness state variable, indexed by AVAILABILITY date.

    flightiness = -z(weekly log deposit growth), rolling trailing 52-week window.
    High value = deposits contracting relative to recent norm (outflow stress).
    Availability date = observation date + PUB_LAG_DAYS (publication lag) so the
    signal only enters the information set after it is realistically public.
    """
    g = np.log(dep_weekly).diff()                          # weekly log growth
    roll_mean = g.rolling(ZWIN, min_periods=13).mean()
    roll_std = g.rolling(ZWIN, min_periods=13).std()
    z = (g - roll_mean) / roll_std
    flight = (-z).dropna()
    avail = pd.Series(flight.values,
                      index=flight.index + pd.Timedelta(days=PUB_LAG_DAYS))
    avail = avail[~avail.index.duplicated(keep="last")].sort_index()
    return avail


# ── Modelling ────────────────────────────────────────────────────────────────
def build_panel(hlc, flight_avail):
    """Return a daily DataFrame with HAR features, forward target, deposit signal.

    Timing: all features are known at the close of day t (F_t). Target y_t is the
    average RV strictly over (t, t+H]. Deposit signal is merged as-of BACKWARD so
    each trading day t only sees flightiness whose availability date <= t.
    """
    df = pd.DataFrame(index=hlc.index)
    df["rv"] = parkinson_rv(hlc["high"], hlc["low"])
    df["rv_d"] = df["rv"]
    df["rv_w"] = df["rv"].rolling(5).mean()
    df["rv_m"] = df["rv"].rolling(22).mean()
    # forward H-day average RV: mean(rv_{t+1..t+H})
    df["y"] = df["rv"].rolling(H).mean().shift(-H)

    left = df.reset_index()
    left.columns = ["date"] + list(df.columns)
    left["date"] = left["date"].astype("datetime64[ns]")
    right = flight_avail.reset_index()
    right.columns = ["date", "dep_flight"]
    right["date"] = right["date"].astype("datetime64[ns]")
    merged = pd.merge_asof(left.sort_values("date"),
                           right.sort_values("date"),
                           on="date", direction="backward")
    merged = merged.set_index("date")
    # restrict to the analysis window
    merged = merged.loc[(merged.index >= pd.Timestamp(START))]
    return merged


def ols_fit_predict(X_tr, y_tr, x_pred):
    """Plain OLS via least squares. Returns prediction for the single origin row."""
    beta, *_ = np.linalg.lstsq(X_tr, y_tr, rcond=None)
    return float(x_pred @ beta), beta


def run_oos(panel, use_dep):
    """Expanding-window one-step-ahead OOS with H-embargo. Refit every step.

    For every OOS origin i, the training set is {j : 0 <= j <= i - H - 1} so that
    each training row's label window (ends at j+H) is strictly before origin i
    (j + H < i). No lookahead.

    Returns dict of arrays: dates, actual, pred, plus floored count.
    """
    feat_cols = ["rv_d", "rv_w", "rv_m"] + (["dep_flight"] if use_dep else [])
    # Always drop NaNs on the FULL feature set (incl. dep_flight) so the baseline
    # and augmented models operate on a BYTE-IDENTICAL row population / train split
    # by construction — the only difference is which columns enter X. This removes
    # any theoretical divergence if dep_flight ever had an isolated NaN.
    all_cols = ["rv_d", "rv_w", "rv_m", "dep_flight"]
    sub = panel.dropna(subset=all_cols + ["y"]).copy()
    X = sub[feat_cols].to_numpy(dtype=np.float64)
    X = np.column_stack([np.ones(len(X)), X])       # intercept
    y = sub["y"].to_numpy(dtype=np.float64)
    dates = sub.index.to_numpy()
    n = len(y)

    n_train0 = int(np.floor(TRAIN_FRAC * n))
    origins = range(n_train0, n)

    preds, acts, odates = [], [], []
    floored = 0
    # floor for QLIKE positivity — set to a tiny fraction of median realized RV
    floor = max(1e-12, 1e-3 * float(np.nanmedian(y)))
    for i in origins:
        train_end = i - H - 1          # embargo: j <= i-H-1  <=>  j+H < i
        if train_end < 20:             # need a minimally sized train set
            continue
        X_tr = X[:train_end + 1]
        y_tr = y[:train_end + 1]
        yhat, _ = ols_fit_predict(X_tr, y_tr, X[i])
        if yhat <= floor:
            yhat = floor
            floored += 1
        preds.append(yhat)
        acts.append(y[i])
        odates.append(dates[i])
    return {
        "dates": np.asarray(odates),
        "actual": np.asarray(acts, dtype=np.float64),
        "pred": np.asarray(preds, dtype=np.float64),
        "n_floored": floored,
    }


def block_bootstrap_diff(d, block_len=BOOT_BLOCK, n_boot=N_BOOT, seed=SEED):
    """Moving-block bootstrap on a loss-differential series d.

    Returns (se, z, p_two_sided, ci95_low, ci95_high). Block length >= H so the
    overlap-induced autocorrelation is preserved inside blocks.
    """
    from scipy import stats as _st
    rng = np.random.default_rng(seed)
    d = np.asarray(d, dtype=np.float64)
    n = len(d)
    if n < block_len + 5:
        return (np.nan,) * 5
    n_blocks = int(np.ceil(n / block_len))
    starts_max = n - block_len
    means = np.empty(n_boot)
    ar = np.arange(block_len)
    for b in range(n_boot):
        starts = rng.integers(0, starts_max + 1, size=n_blocks)
        idx = (starts[:, None] + ar[None, :]).ravel()[:n]
        means[b] = d[idx].mean()
    d_obs = float(d.mean())
    se = float(means.std(ddof=1))
    z = d_obs / se if se > 0 else np.nan
    p = float(2 * (1 - _st.norm.cdf(abs(z)))) if np.isfinite(z) else np.nan
    lo, hi = np.percentile(means, [2.5, 97.5])
    return se, float(z), p, float(lo), float(hi)


def newey_west_tstat(y, X, lag):
    """OLS with Newey-West HAC t-stats. Returns (beta, tstats)."""
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    n, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for L in range(1, lag + 1):
        w = 1 - L / (lag + 1)
        Xe = X * resid[:, None]
        G = Xe[L:].T @ Xe[:-L]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    return beta, beta / se


def evaluate_series(res_base, res_aug, label):
    """Compute QLIKE/MSE/DM/bootstrap for one aligned (base, aug) OOS pair."""
    actual = res_aug["actual"]
    yb, ya = res_base["pred"], res_aug["pred"]
    ql_b = qlike(actual, yb)
    ql_a = qlike(actual, ya)
    mse_b = mse_fn(actual, yb)
    mse_a = mse_fn(actual, ya)
    loss_b = qlike_pointwise(actual, yb)
    loss_a = qlike_pointwise(actual, ya)
    dm_t, dm_p = dm_test(loss_a, loss_b, h=H)   # neg t => aug better
    d = loss_a - loss_b                          # <0 favours aug
    se, z, bp, lo, hi = block_bootstrap_diff(d)
    return {
        "label": label,
        "n_oos": int(len(actual)),
        "QLIKE_base": ql_b,
        "QLIKE_aug": ql_a,
        "QLIKE_improvement_pct": float((ql_b - ql_a) / ql_b * 100) if ql_b else np.nan,
        "MSE_base": mse_b,
        "MSE_aug": mse_a,
        "MSE_improvement_pct": float((mse_b - mse_a) / mse_b * 100) if mse_b else np.nan,
        "DM_stat": dm_t,
        "DM_pvalue": dm_p,
        "DM_horizon": H,
        "DM_direction": "negative_t_means_augmented_better",
        "block_bootstrap": {
            "block_len": BOOT_BLOCK, "n_boot": N_BOOT,
            "mean_loss_diff": float(np.mean(d)),
            "se": se, "z": z, "p_two_sided": bp, "ci95": [lo, hi],
        },
        "n_floored_base": int(res_base["n_floored"]),
        "n_floored_aug": int(res_aug["n_floored"]),
    }


# ── Figures ──────────────────────────────────────────────────────────────────
def fig_state_vs_rv(panel, out_path):
    df = panel.copy()
    ann_vol = np.sqrt(df["rv"].clip(lower=0) * 252) * 100  # annualised %, readable
    fig, ax1 = plt.subplots(figsize=(11, 5))
    ax1.plot(df.index, ann_vol, color="#1f77b4", lw=0.8, alpha=0.8,
             label="KRE realized vol (annualized %, Parkinson)")
    ax1.set_ylabel("KRE realized vol (annualized %)", color="#1f77b4")
    ax1.tick_params(axis="y", labelcolor="#1f77b4")
    ax2 = ax1.twinx()
    ax2.plot(df.index, df["dep_flight"], color="#d62728", lw=1.1,
             label="Deposit-flightiness state (−z of weekly deposit growth)")
    ax2.set_ylabel("Deposit-flightiness (−z)", color="#d62728")
    ax2.tick_params(axis="y", labelcolor="#d62728")
    ax2.axhline(0, color="#d62728", lw=0.5, ls=":", alpha=0.5)
    s0, s1 = pd.Timestamp(SVB_WINDOW[0]), pd.Timestamp(SVB_WINDOW[1])
    ax1.axvspan(s0, s1, color="grey", alpha=0.25)
    ax1.annotate("SVB / regional-bank\ncrisis (Mar 2023)",
                 xy=(s0, ax1.get_ylim()[1] * 0.92), fontsize=8, color="black")
    ax1.set_title("Aggregate deposit-flightiness vs KRE realized volatility (2015–2026)")
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    l1, lb1 = ax1.get_legend_handles_labels()
    l2, lb2 = ax2.get_legend_handles_labels()
    ax1.legend(l1 + l2, lb1 + lb2, loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def fig_oos_compare(res_base, res_aug, metrics, out_path):
    actual = res_aug["actual"]
    loss_b = qlike_pointwise(actual, res_base["pred"])
    loss_a = qlike_pointwise(actual, res_aug["pred"])
    cum = np.cumsum(loss_b - loss_a)   # up => augmented cumulatively better
    dates = res_aug["dates"]

    fig, (axL, axR) = plt.subplots(1, 2, figsize=(13, 5),
                                   gridspec_kw={"width_ratios": [1, 1.4]})
    # left: bar QLIKE base vs aug
    axL.bar([0, 1], [metrics["QLIKE_base"], metrics["QLIKE_aug"]],
            color=["#7f7f7f", "#2ca02c"], width=0.6)
    axL.set_xticks([0, 1])
    axL.set_xticklabels(["HAR-RV\n(baseline)", "HAR-RV +\ndeposit-flight"])
    axL.set_ylabel("OOS QLIKE (lower better)")
    axL.set_title(f"OOS QLIKE  (improve {metrics['QLIKE_improvement_pct']:.2f}%)")
    for i, v in enumerate([metrics["QLIKE_base"], metrics["QLIKE_aug"]]):
        axL.text(i, v, f"{v:.4f}", ha="center", va="bottom", fontsize=9)

    # right: cumulative loss differential over time
    axR.plot(dates, cum, color="#2ca02c", lw=1.1)
    axR.axhline(0, color="black", lw=0.6)
    s0, s1 = pd.Timestamp(SVB_WINDOW[0]), pd.Timestamp(SVB_WINDOW[1])
    axR.axvspan(s0, s1, color="grey", alpha=0.25)
    axR.set_title("Cumulative QLIKE gain of augmented model\n(up = deposit-flight helps)")
    axR.set_ylabel("Σ (loss_base − loss_aug)")
    axR.xaxis.set_major_locator(mdates.YearLocator())
    axR.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    dm = metrics["DM_stat"]
    axR.annotate(f"DM t={dm:.2f} (h={H})\np={metrics['DM_pvalue']:.3f}",
                 xy=(0.02, 0.9), xycoords="axes fraction", fontsize=9,
                 bbox=dict(boxstyle="round", fc="white", ec="grey", alpha=0.8))
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


# ── Component-stock robustness (date-aggregated, NOT asset-day iid) ───────────
def run_components(flight_avail):
    """For each component: run OOS, get per-stock loss differential indexed by date.
    Aggregate cross-asset by DATE (mean over available stocks per day), then DM/HAC
    on the date series. Per .claude/rules/experiments.md: never treat asset-day as
    iid; aggregate by date first.
    """
    from volpred.ops.diagnostics import warn
    per_stock = {}
    diff_frames = []
    for tk in COMPONENTS:
        try:
            hlc = fetch_hlc(tk)
            panel = build_panel(hlc, flight_avail)
            rb = run_oos(panel, use_dep=False)
            ra = run_oos(panel, use_dep=True)
            if len(ra["actual"]) < 100:
                warn("k1606_components", "too few oos rows", ticker=tk,
                     n=int(len(ra["actual"])))
                continue
            actual = ra["actual"]
            lb = qlike_pointwise(actual, rb["pred"])
            la = qlike_pointwise(actual, ra["pred"])
            d = la - lb   # <0 favours aug
            s = pd.Series(d, index=pd.to_datetime(ra["dates"]), name=tk)
            diff_frames.append(s)
            per_stock[tk] = {
                "n_oos": int(len(actual)),
                "QLIKE_base": qlike(actual, rb["pred"]),
                "QLIKE_aug": qlike(actual, ra["pred"]),
                "mean_loss_diff": float(np.mean(d)),
            }
        except Exception as e:                       # noqa: BLE001
            warn("k1606_components", "stock failed", ticker=tk, err=str(e))
            continue

    if len(diff_frames) < 3:
        return {"status": "insufficient_stocks", "n_stocks": len(diff_frames),
                "per_stock": per_stock}

    mat = pd.concat(diff_frames, axis=1)
    date_diff = mat.mean(axis=1).dropna()            # cross-asset mean per DATE
    d = date_diff.to_numpy()
    # DM/HAC on the date-aggregated differential (one-sample against 0)
    dm_t, dm_p = dm_test(d, np.zeros_like(d), h=H)
    se, z, bp, lo, hi = block_bootstrap_diff(d)
    return {
        "status": "ok",
        "n_stocks": len(diff_frames),
        "stocks": list(per_stock.keys()),
        "aggregation": "cross-asset mean of loss differential per date, then DM/HAC",
        "n_dates": int(len(d)),
        "mean_date_loss_diff": float(np.mean(d)),
        "DM_stat": dm_t, "DM_pvalue": dm_p, "DM_horizon": H,
        "DM_direction": "negative_t_means_augmented_better",
        "block_bootstrap": {"block_len": BOOT_BLOCK, "se": se, "z": z,
                            "p_two_sided": bp, "ci95": [lo, hi]},
        "per_stock": per_stock,
    }


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    results = {
        "experiment_id": "K1606",
        "title": "Deposit-flightiness state variable predicting regional-bank "
                 "realized volatility (time-series reframe)",
        "reframe_note": "Aggregate deposit-flightiness (FRED weekly total deposits) "
                        "-> KRE regional-bank RV. NOT the original cross-sectional "
                        "uninsured-deposit-share hypothesis (no bank-level FFIEC "
                        "call-report data available). No cross-sectional uniqueness "
                        "claim is made.",
        "run_utc": datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "horizon_days": H,
        "rv_proxy": "Parkinson (high-low range) daily variance",
        "target": "forward H-day average RV: y_t = mean(RV_{t+1..t+H})",
        "oos_scheme": "expanding window, refit every step, embargo=H rows "
                      "(train row j requires j+H < origin i)",
        "train_frac": TRAIN_FRAC,
        "deposit_signal": {
            "series": FRED_SERIES,
            "definition": "-zscore(weekly log deposit growth, rolling 52w)",
            "publication_lag_days": PUB_LAG_DAYS,
            "merge": "as-of backward on trading days (no lookahead)",
        },
        "period": {"start": START, "end": END},
        "data_sources": {
            "prices": "yfinance (auto_adjust=True), KRE + components",
            "deposits": f"FRED {FRED_SERIES} via api.stlouisfed.org",
        },
        "data_blocked": False,
    }

    api_key = get_fred_api_key()
    if not api_key:
        results["data_blocked"] = True
        results["blocker"] = "FRED_API_KEY missing (.env.local/.env)"
        (HERE / "k1606_results.json").write_text(json.dumps(results, indent=2))
        print("DATA BLOCKED: no FRED key")
        return

    try:
        dep_weekly = fetch_fred(FRED_SERIES, api_key)
        flight_avail = build_deposit_flightiness(dep_weekly)
        hlc = fetch_hlc(KRE)
    except Exception as e:                            # noqa: BLE001
        results["data_blocked"] = True
        results["blocker"] = f"data fetch failed: {e}"
        (HERE / "k1606_results.json").write_text(json.dumps(results, indent=2))
        print(f"DATA BLOCKED: {e}")
        return

    panel = build_panel(hlc, flight_avail)
    results["period"]["n_trading_days_in_window"] = int(len(panel))
    results["deposit_signal"]["n_weekly_obs"] = int(len(dep_weekly))

    # Primary: KRE single series
    res_base = run_oos(panel, use_dep=False)
    res_aug = run_oos(panel, use_dep=True)
    # sanity: both OOS must cover identical origins
    assert np.array_equal(res_base["dates"], res_aug["dates"]), "OOS origin mismatch"
    metrics = evaluate_series(res_base, res_aug, "KRE")

    # In-sample descriptive diagnostic: dep_flight coef + Newey-West t (full sample)
    sub = panel.dropna(subset=["rv_d", "rv_w", "rv_m", "dep_flight", "y"]).copy()
    Xa = np.column_stack([np.ones(len(sub)),
                          sub[["rv_d", "rv_w", "rv_m", "dep_flight"]].to_numpy()])
    ya = sub["y"].to_numpy()
    beta, tstats = newey_west_tstat(ya, Xa, lag=2 * H)
    metrics["insample_diagnostic"] = {
        "dep_flight_coef": float(beta[-1]),
        "dep_flight_nw_t": float(tstats[-1]),
        "nw_lag": 2 * H,
        "note": "descriptive in-sample only; primary claim is OOS DM",
    }
    results["primary_KRE"] = metrics

    # Robustness: component basket (date-aggregated cross-asset)
    try:
        results["robustness_components"] = run_components(flight_avail)
    except Exception as e:                            # noqa: BLE001
        results["robustness_components"] = {"status": "error", "err": str(e)}

    # Figures
    fig_state_vs_rv(panel, HERE / "k1606_fig_state_vs_rv.png")
    fig_oos_compare(res_base, res_aug, metrics, HERE / "k1606_fig_oos_compare.png")

    # Honest conclusion
    dm_t = metrics["DM_stat"]
    dm_p = metrics["DM_pvalue"]
    harvey_sig = abs(dm_t) > 3.0
    aug_better = dm_t < 0
    if harvey_sig and aug_better:
        verdict = ("Deposit-flightiness adds statistically robust incremental OOS "
                   "predictive power over HAR-RV (Harvey |t|>3).")
    elif abs(dm_t) > 1.96 and aug_better:
        verdict = ("Deposit-flightiness shows weak/suggestive incremental OOS power "
                   "(|t|>1.96 but below Harvey 3.0 multiple-testing bar); NOT robust.")
    else:
        verdict = ("NULL: deposit-flightiness does NOT add robust incremental OOS "
                   "predictive power over HAR-RV for KRE.")
    results["conclusion"] = verdict
    results["harvey_significant"] = bool(harvey_sig and aug_better)

    (HERE / "k1606_results.json").write_text(json.dumps(results, indent=2, default=float))
    print("=== K1606 primary (KRE) ===")
    print(f"n_oos={metrics['n_oos']}  QLIKE base={metrics['QLIKE_base']:.5f} "
          f"aug={metrics['QLIKE_aug']:.5f}  improve={metrics['QLIKE_improvement_pct']:.2f}%")
    print(f"DM t={dm_t:.3f} p={dm_p:.4f} (h={H}); bootstrap p="
          f"{metrics['block_bootstrap']['p_two_sided']}")
    print(f"in-sample dep_flight coef={beta[-1]:.4g} NW-t={tstats[-1]:.3f}")
    rc = results["robustness_components"]
    if rc.get("status") == "ok":
        print(f"components(date-agg): n_stocks={rc['n_stocks']} "
              f"DM t={rc['DM_stat']:.3f} p={rc['DM_pvalue']:.4f}")
    print("VERDICT:", verdict)


if __name__ == "__main__":
    main()
