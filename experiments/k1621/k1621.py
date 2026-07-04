"""
K1621 — EM sovereign-credit volatility as a cross-asset uncertainty forestaller
================================================================================

Research question
-----------------
Does the daily realized volatility of EM USD-sovereign-bond ETFs (EMB / PCY /
VWOB) and the change in the EM credit spread (ICE BofA EM HY Corporate OAS, FRED
BAMLEMHBHYCRPIOAS) *lead* the realized volatility of EM equity ETFs
(EEM / EWZ / EWY / EWT / INDA), and is any lead-lag / forecasting gain
conditional on the VIX regime?

All ETF / spread series are treated as **diagnostic proxies for sovereign-credit
uncertainty** — this experiment does NOT use raw sovereign-CDS quotes and does
NOT claim to replicate deal-level or single-country CDS data.

Data-availability note (honest limitation)
------------------------------------------
Following a 2024 ICE licensing change, FRED ICE-BofA OAS series only retain a
rolling ~3-year window (BAMLEMHBHYCRPIOAS starts 2023-07-04). Therefore:
  * PRIMARY forecasting test uses the EMB **realized-vol** credit proxy, which is
    available over the full 2015+ ETF sample (drives the SIGNAL/NULL verdict).
  * The EM-OAS spread-change feature is a SECONDARY, short-sample (2023-07+)
    robustness check + descriptive lead-lag, explicitly flagged as underpowered.

Method (Phase-1 diagnostic; NO GARCH MLE / NO large bootstrap)
--------------------------------------------------------------
1. Descriptive stats + data diagnostics.
2. Lead-lag CCF: EMB RV(t) and OAS-change(t) vs equity RV(t+k), k in [-5, 5].
3. Honest forecasting (log-HAR, Corsi 2009): for each equity ETF compare
      baseline  log-HAR (own lagged r^2 daily/weekly/monthly)
   vs augmented log-HAR + EMB-RV (and, short-sample, + EM-OAS-change)
   on 5-day forward realized variance. Loss = QLIKE (actual/predicted form),
   variance forecasts = exp(log-forecast + 0.5*resid_var)  (lognormal, >0).
4. Cross-asset cluster-robust (K1355): PRIMARY pooled claim aggregates the
   cross-asset loss differential BY DATE, then runs DM-HLN (h=5) on the date
   series. Stacked asset-day DM reported only as a diagnostic.
5. VIX-regime conditional (low vs high).
6. Fixed seed.

Lookahead controls
-------------------
* All predictors sit at forecast origin t; the target uses returns over
  [t+1, t+5] -> predictors strictly precede the target window.
* Expanding-window OOS refit enforces target_end < forecast_origin: a training
  row j admissible for a fit used at origin i requires j + H < i.
* DM-HLN uses horizon h = H = 5 (single horizon; no cross-horizon sharing).
* QLIKE direction is actual/predicted (via volpred.stats.model_evaluation).

Author: VolPred autonomous research agent | Data: yfinance + FRED (all free)
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))
from volpred.stats.model_evaluation import qlike_pointwise  # noqa: E402  (actual/pred QLIKE, K783c)

# ── Reproducibility ──────────────────────────────────────────────────────────
SEED = 42
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
PLOTS = HERE / "plots"
PLOTS.mkdir(exist_ok=True)

# ── Config ───────────────────────────────────────────────────────────────────
START = "2015-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
H = 5                        # forecast horizon (days) — inference horizon == H
ANNUALIZE = 252
BOND_ETFS = ["EMB", "PCY", "VWOB"]
EQUITY_ETFS = ["EEM", "EWZ", "EWY", "EWT", "INDA"]
VIX_TICKER = "^VIX"
FRED_OAS = "BAMLEMHBHYCRPIOAS"   # ICE BofA HY EM Corporate Plus OAS (Percent, 2023-07+)
MIN_TRAIN = 500              # min admissible training rows before OOS starts
MIN_TRAIN_SHORT = 250        # relaxed for the short OAS window
REFIT_EVERY = 21            # refit expanding model monthly
EPS = 1e-8                   # log floor for variance-scale features/targets
HARVEY_T = 3.0              # Harvey (2016) multiple-testing threshold


# ─────────────────────────────────────────────────────────────────────────────
# Data fetch
# ─────────────────────────────────────────────────────────────────────────────
def fetch_yf_close(tickers: list[str]) -> pd.DataFrame:
    import yfinance as yf
    out = {}
    for tk in tickers:
        for attempt in range(3):
            try:
                df = yf.download(tk, start=START, end=END, auto_adjust=True,
                                 progress=False, threads=False)
                if df is None or df.empty:
                    raise ValueError("empty frame")
                col = df["Close"]
                if isinstance(col, pd.DataFrame):
                    col = col.iloc[:, 0]
                out[tk] = col
                break
            except Exception as e:  # noqa: BLE001
                print(f"[yf] {tk} attempt {attempt+1} failed: {e}", file=sys.stderr)
                if attempt == 2:
                    print(f"[yf] {tk} GIVE UP — series missing", file=sys.stderr)
    px = pd.DataFrame(out)
    px.index = pd.to_datetime(px.index)
    return px.sort_index()


def fetch_fred(series_id: str) -> pd.Series:
    import requests
    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        env_local = PROJECT / ".env.local"
        if env_local.exists():
            for line in env_local.read_text().splitlines():
                line = line.strip()
                if line.startswith("FRED_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    break
    if not api_key:
        print("[fred] FRED_API_KEY missing — OAS unavailable", file=sys.stderr)
        return pd.Series(dtype=float, name=series_id)
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {"series_id": series_id, "api_key": api_key, "file_type": "json",
              "observation_start": START}
    last_exc = None
    for i in range(3):
        try:
            resp = requests.get(url, params=params, timeout=45)
            if resp.status_code >= 500:
                last_exc = RuntimeError(f"HTTP {resp.status_code}")
                continue
            resp.raise_for_status()
            obs = resp.json().get("observations", [])
            if not obs:
                raise ValueError("empty observations")
            df = pd.DataFrame(obs)[["date", "value"]]
            df["date"] = pd.to_datetime(df["date"])
            df["value"] = pd.to_numeric(df["value"], errors="coerce")
            s = df.set_index("date")["value"].dropna()
            s.name = series_id
            return s
        except Exception as e:  # noqa: BLE001
            last_exc = e
            print(f"[fred] attempt {i+1} failed: {e}", file=sys.stderr)
    print(f"[fred] GIVE UP: {last_exc}", file=sys.stderr)
    return pd.Series(dtype=float, name=series_id)


# ─────────────────────────────────────────────────────────────────────────────
# Feature engineering (variance scale throughout)
# ─────────────────────────────────────────────────────────────────────────────
def log_returns(px: pd.DataFrame) -> pd.DataFrame:
    return np.log(px / px.shift(1))


def rv_daily(ret: pd.Series) -> pd.Series:
    """Daily variance proxy = r^2 (noisy unbiased proxy for daily variance)."""
    return ret ** 2


def har_components(rv_d: pd.Series) -> pd.DataFrame:
    """HAR daily/weekly/monthly variance components at origin t (info up to t)."""
    return pd.DataFrame({
        "rv_d": rv_d,
        "rv_w": rv_d.rolling(5).mean(),
        "rv_m": rv_d.rolling(22).mean(),
    })


def emb_rv_component(rv_d_emb: pd.Series) -> pd.Series:
    """EMB weekly realized variance (variance scale, matches equity features)."""
    return rv_d_emb.rolling(5).mean()


def forward_rv(rv_d: pd.Series, h: int = H) -> pd.Series:
    """Target: mean daily variance over [t+1, t+h] (strictly future vs origin t).

    Explicit forward window avoids any shift/rolling off-by-one:
    value at index t = mean(rv_d[t+1 .. t+h]).
    """
    vals = rv_d.values
    n = len(vals)
    out = np.full(n, np.nan)
    for i in range(n - h):
        window = vals[i + 1: i + 1 + h]
        if np.all(np.isfinite(window)):
            out[i] = window.mean()
    return pd.Series(out, index=rv_d.index)


def realized_vol_ann(rv_d: pd.Series, window: int) -> pd.Series:
    """Annualized realized vol over a rolling window (descriptive / CCF only)."""
    return np.sqrt(rv_d.rolling(window).mean() * ANNUALIZE)


# ─────────────────────────────────────────────────────────────────────────────
# DM-HLN (Harvey, Leybourne & Newbold 1997 small-sample correction)
# ─────────────────────────────────────────────────────────────────────────────
def dm_hln(loss1: np.ndarray, loss2: np.ndarray, h: int) -> dict:
    """Modified Diebold-Mariano. d = loss1 - loss2 (positive mean => model 2 better).

    LRV uses lags 0..h-1 (MA(h-1) structure of h-step errors).
    HLN factor sqrt((T+1-2h+h(h-1)/T)/T); reference dist = t(T-1).
    """
    from scipy import stats
    d = np.asarray(loss1, float) - np.asarray(loss2, float)
    d = d[np.isfinite(d)]
    T = d.size
    if T < max(20, 2 * h):
        return {"dm_hln_t": np.nan, "p_value": np.nan, "n": int(T),
                "mean_diff": float(np.mean(d)) if T else np.nan}
    d_bar = d.mean()
    dc = d - d_bar
    lrv = float(np.mean(dc * dc))
    for k in range(1, h):
        lrv += 2.0 * float(np.mean(dc[k:] * dc[:-k]))
    if lrv <= 0:
        return {"dm_hln_t": np.nan, "p_value": np.nan, "n": int(T),
                "mean_diff": float(d_bar)}
    dm = d_bar / np.sqrt(lrv / T)
    factor = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    dm_star = dm * factor
    p = 2.0 * (1.0 - stats.t.cdf(abs(dm_star), df=T - 1))
    return {"dm_hln_t": float(dm_star), "p_value": float(p), "n": int(T),
            "mean_diff": float(d_bar)}


# ─────────────────────────────────────────────────────────────────────────────
# Expanding-window OOS log-HAR forecast
# ─────────────────────────────────────────────────────────────────────────────
def _design(df: pd.DataFrame, log_cols: list[str], lin_cols: list[str]) -> np.ndarray:
    parts = [np.ones(len(df))]
    for c in log_cols:
        parts.append(np.log(np.maximum(df[c].values, 0.0) + EPS))
    for c in lin_cols:
        parts.append(df[c].values)
    return np.column_stack(parts)


def oos_forecast(feats: pd.DataFrame, target: pd.Series,
                 log_cols: list[str], lin_cols: list[str],
                 min_train: int = MIN_TRAIN) -> pd.DataFrame:
    """Expanding-window OOS log-HAR forecast enforcing target_end < origin.

    Fit log-target OLS on admissible rows (j+H < i); variance forecast =
    exp(yhat + 0.5*resid_var) with the in-sample lognormal bias correction.
    Returns DataFrame[date] -> (pred, actual) on original variance scale.
    """
    cols = log_cols + lin_cols
    df = feats[cols].copy()
    df["_y"] = target
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    if df.empty:
        return pd.DataFrame(columns=["pred", "actual"])
    X = _design(df, log_cols, lin_cols)
    y_raw = df["_y"].values
    y_log = np.log(np.maximum(y_raw, 0.0) + EPS)
    n = len(df)

    preds = np.full(n, np.nan)
    beta = None
    resid_var = 0.0
    last_refit = -10**9
    for i in range(n):
        train_hi = i - H            # rows 0..i-H-1 satisfy j+H < i
        if train_hi < min_train:
            continue
        if beta is None or (i - last_refit) >= REFIT_EVERY:
            Xtr, ytr = X[:train_hi], y_log[:train_hi]
            beta, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
            resid = ytr - Xtr @ beta
            resid_var = float(np.mean(resid ** 2))
            last_refit = i
        yhat = X[i] @ beta
        preds[i] = np.exp(yhat + 0.5 * resid_var) - EPS

    res = pd.DataFrame({"pred": preds, "actual": y_raw}, index=df.index).dropna()
    res["pred"] = res["pred"].clip(lower=EPS)
    res["actual"] = res["actual"].clip(lower=EPS)
    return res


# ─────────────────────────────────────────────────────────────────────────────
# Cross-correlation (lead-lag)
# ─────────────────────────────────────────────────────────────────────────────
def ccf(x: pd.Series, y: pd.Series, lags: range) -> dict:
    """corr(x(t), y(t+k)) for k in lags. Positive k => x leads y by k days."""
    xy = pd.concat([x, y], axis=1, keys=["x", "y"]).dropna()
    out = {}
    for k in lags:
        if k >= 0:
            a = xy["x"].iloc[:len(xy) - k] if k > 0 else xy["x"]
            b = xy["y"].iloc[k:] if k > 0 else xy["y"]
        else:
            a = xy["x"].iloc[-k:]
            b = xy["y"].iloc[:len(xy) + k]
        out[k] = float(np.corrcoef(a.values, b.values)[0, 1]) if len(a) > 30 else np.nan
    return out


def _pool_by_date(loss_rows: list[dict], h: int) -> dict:
    """K1355 primary: aggregate cross-asset loss diff by date, then DM-HLN."""
    ld = pd.DataFrame(loss_rows)
    bd = ld.groupby("date").agg(l_base=("l_base", "mean"), l_aug=("l_aug", "mean"))
    dm = dm_hln(bd["l_base"].values, bd["l_aug"].values, h)
    qb, qa = float(bd["l_base"].mean()), float(bd["l_aug"].mean())
    return {"n_dates": int(len(bd)), "qlike_baseline": qb, "qlike_augmented": qa,
            "qlike_gain_pct": float(100.0 * (qb - qa) / qb) if qb > 0 else np.nan,
            "dm_hln_t": dm["dm_hln_t"], "dm_hln_p": dm["p_value"]}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    results: dict = {
        "experiment_id": "k1621",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "config": {
            "start": START, "end": END, "horizon_days": H,
            "bond_etfs": BOND_ETFS, "equity_etfs": EQUITY_ETFS,
            "fred_oas": FRED_OAS, "min_train": MIN_TRAIN, "refit_every": REFIT_EVERY,
            "har_spec": "log-HAR (Corsi 2009) with lognormal bias correction",
            "loss": "QLIKE actual/predicted (Patton 2011)",
            "proxy_disclaimer": ("All ETF/OAS series are diagnostic proxies for "
                                 "sovereign-credit uncertainty; NOT raw CDS data."),
            "oas_history_note": ("FRED ICE-BofA OAS retains only ~3yr rolling "
                                 "window since 2024 ICE license change; OAS test "
                                 "is short-sample secondary only."),
        },
    }

    # ---- Fetch ----
    all_etfs = BOND_ETFS + EQUITY_ETFS + [VIX_TICKER]
    print(f"[data] downloading {all_etfs} + FRED {FRED_OAS} ({START}..{END})")
    px = fetch_yf_close(all_etfs)
    oas = fetch_fred(FRED_OAS)

    have_etfs = [c for c in all_etfs if c in px.columns and px[c].notna().sum() > 100]
    missing_etfs = [c for c in all_etfs if c not in have_etfs]
    have_oas = oas.notna().sum() > 100
    print(f"[data] have ETFs={have_etfs} | missing={missing_etfs} | OAS_ok={have_oas} "
          f"(n_oas={int(oas.notna().sum())})")

    ret = log_returns(px)
    rv = {c: rv_daily(ret[c]) for c in have_etfs}
    oas_daily = oas.reindex(px.index).ffill() if have_oas else pd.Series(index=px.index, dtype=float)
    oas_chg5 = oas_daily.diff(5)

    lead_bond = "EMB" if "EMB" in have_etfs else (BOND_ETFS[0] if BOND_ETFS[0] in have_etfs else None)
    equities = [e for e in EQUITY_ETFS if e in have_etfs]

    # ---- Descriptive ----
    desc = {}
    for c in have_etfs:
        s = ret[c].dropna()
        desc[c] = {"n_obs": int(s.size),
                   "first": str(s.index.min().date()) if s.size else None,
                   "last": str(s.index.max().date()) if s.size else None,
                   "daily_ret_std": float(s.std()),
                   "ann_vol_pct": float(s.std() * np.sqrt(ANNUALIZE) * 100)}
    if have_oas:
        os_ = oas.dropna()
        desc["EM_OAS"] = {"series_id": FRED_OAS, "n_obs": int(os_.size),
                          "first": str(os_.index.min().date()),
                          "last": str(os_.index.max().date()),
                          "level_mean_pct": float(os_.mean()),
                          "daily_chg_std_pct": float(oas.diff().std())}
    results["descriptive"] = desc
    results["data_provenance"] = {
        "etfs_available": have_etfs, "etfs_missing": missing_etfs,
        "oas_available": bool(have_oas),
        "oas_start": str(oas.dropna().index.min().date()) if have_oas else None,
        "source": "yfinance auto_adjust close + FRED official API",
    }

    # =====================================================================
    # (1) Lead-lag CCF (descriptive) — de-noised 5d realized vol
    # =====================================================================
    lags = range(-5, 6)
    rv5 = {c: realized_vol_ann(rv[c], 5) for c in have_etfs}
    ccf_res = {"lags": list(lags), "emb_rv_vs_equity": {},
               "oas_chg_vs_equity": {}, "peak_lag": {}}
    if lead_bond:
        for eq in equities:
            c = ccf(rv5[lead_bond], rv5[eq], lags)
            ccf_res["emb_rv_vs_equity"][eq] = c
            pos = {k: v for k, v in c.items() if k >= 0 and np.isfinite(v)}
            if pos:
                pk = max(pos, key=pos.get)
                ccf_res["peak_lag"][eq] = {"lag": pk, "corr": pos[pk]}
    if have_oas:
        for eq in equities:
            ccf_res["oas_chg_vs_equity"][eq] = ccf(oas_chg5, rv5[eq], lags)
    results["lead_lag_ccf"] = ccf_res

    # =====================================================================
    # (2) PRIMARY forecast: baseline log-HAR vs +EMB-RV (full sample)
    # =====================================================================
    base_log = ["rv_d", "rv_w", "rv_m"]
    vix_level = px[VIX_TICKER] if VIX_TICKER in px.columns else pd.Series(index=px.index, dtype=float)
    emb_rvw = emb_rv_component(rv[lead_bond]) if lead_bond else None

    per_asset = {}
    loss_rows = []          # date-level rows for pooling (primary)
    for eq in equities:
        feats = har_components(rv[eq])
        if lead_bond:
            feats["emb_rv_w"] = emb_rvw
        target = forward_rv(rv[eq], H)

        base = oos_forecast(feats, target, base_log, [])
        aug_cols_log = base_log + (["emb_rv_w"] if lead_bond else [])
        aug = oos_forecast(feats, target, aug_cols_log, [])
        common = base.index.intersection(aug.index)
        if len(common) < 100:
            per_asset[eq] = {"n_oos": int(len(common)), "note": "insufficient OOS"}
            continue
        base, aug = base.loc[common], aug.loc[common]
        l_base = qlike_pointwise(base["actual"].values, base["pred"].values)
        l_aug = qlike_pointwise(aug["actual"].values, aug["pred"].values)
        dm = dm_hln(l_base, l_aug, H)
        qb, qa = float(np.mean(l_base)), float(np.mean(l_aug))
        per_asset[eq] = {
            "n_oos": int(len(common)),
            "oos_start": str(common.min().date()), "oos_end": str(common.max().date()),
            "qlike_baseline": qb, "qlike_augmented": qa,
            "qlike_gain": qb - qa,
            "qlike_gain_pct": float(100.0 * (qb - qa) / qb) if qb > 0 else np.nan,
            "dm_hln_t": dm["dm_hln_t"], "dm_hln_p": dm["p_value"],
        }
        for dt, lb, la, vx in zip(common, l_base, l_aug,
                                  vix_level.reindex(common).values):
            loss_rows.append({"date": dt, "asset": eq, "l_base": lb,
                              "l_aug": la, "vix": vx})
    results["forecast_per_asset_primary"] = per_asset

    # =====================================================================
    # (3) Cross-asset cluster-robust pooled DM-HLN (PRIMARY, K1355)
    # =====================================================================
    pooled = {}
    if loss_rows:
        prim = _pool_by_date(loss_rows, H)
        prim["method"] = "date-aggregated cross-asset loss diff -> DM-HLN(h=5)"
        pooled["primary_date_aggregated"] = prim
        ld = pd.DataFrame(loss_rows)
        dm_stack = dm_hln(ld["l_base"].values, ld["l_aug"].values, H)
        pooled["diagnostic_stacked_asset_day"] = {
            "warning": "asset-day iid understates SE; NOT a primary claim (K1355)",
            "n_asset_days": int(len(ld)),
            "dm_hln_t": dm_stack["dm_hln_t"], "dm_hln_p": dm_stack["p_value"],
        }
    results["pooled_cluster_robust_primary"] = pooled

    # =====================================================================
    # (4) VIX-regime conditional (primary EMB-RV spec)
    # =====================================================================
    regime = {}
    if loss_rows:
        ld = pd.DataFrame(loss_rows).dropna(subset=["vix"])
        vmed = float(ld["vix"].median())
        for label, mask in [("low_vix", ld["vix"] < vmed), ("high_vix", ld["vix"] >= vmed),
                            ("vix_below_20", ld["vix"] < 20), ("vix_above_20", ld["vix"] >= 20)]:
            sub = ld[mask]
            if len(sub) < 60:
                continue
            r = _pool_by_date(sub.to_dict("records"), H)
            r["vix_threshold_median"] = vmed
            regime[label] = r
    results["vix_regime"] = regime

    # =====================================================================
    # (5) SECONDARY short-sample: + EM-OAS-change (2023-07+), flagged
    # =====================================================================
    secondary = {"note": "short-sample OAS window; underpowered; not verdict-driving"}
    if have_oas and lead_bond:
        oas_rows = []
        oas_per_asset = {}
        for eq in equities:
            feats = har_components(rv[eq])
            feats["emb_rv_w"] = emb_rvw
            feats["oas_chg5"] = oas_chg5.reindex(feats.index)
            target = forward_rv(rv[eq], H)
            base = oos_forecast(feats, target, base_log, [], min_train=MIN_TRAIN_SHORT)
            aug = oos_forecast(feats, target, base_log + ["emb_rv_w"], ["oas_chg5"],
                               min_train=MIN_TRAIN_SHORT)
            common = base.index.intersection(aug.index)
            if len(common) < 60:
                oas_per_asset[eq] = {"n_oos": int(len(common)), "note": "insufficient OOS"}
                continue
            base, aug = base.loc[common], aug.loc[common]
            l_base = qlike_pointwise(base["actual"].values, base["pred"].values)
            l_aug = qlike_pointwise(aug["actual"].values, aug["pred"].values)
            dm = dm_hln(l_base, l_aug, H)
            qb, qa = float(np.mean(l_base)), float(np.mean(l_aug))
            oas_per_asset[eq] = {
                "n_oos": int(len(common)),
                "oos_start": str(common.min().date()), "oos_end": str(common.max().date()),
                "qlike_gain_pct": float(100.0 * (qb - qa) / qb) if qb > 0 else np.nan,
                "dm_hln_t": dm["dm_hln_t"], "dm_hln_p": dm["p_value"],
            }
            for dt, lb, la in zip(common, l_base, l_aug):
                oas_rows.append({"date": dt, "asset": eq, "l_base": lb, "l_aug": la})
        secondary["per_asset"] = oas_per_asset
        if oas_rows:
            secondary["pooled_date_aggregated"] = _pool_by_date(oas_rows, H)
    results["secondary_oas_shortsample"] = secondary

    # =====================================================================
    # Verdict (Harvey |t|>3.0 on primary pooled claim)
    # =====================================================================
    prim = pooled.get("primary_date_aggregated", {})
    prim_t = prim.get("dm_hln_t", np.nan)
    prim_gain = prim.get("qlike_gain_pct", np.nan)
    n_sig = sum(1 for v in per_asset.values()
                if isinstance(v, dict) and np.isfinite(v.get("dm_hln_t", np.nan))
                and abs(v["dm_hln_t"]) > HARVEY_T and v.get("qlike_gain", 0) > 0)
    if np.isfinite(prim_t) and abs(prim_t) > HARVEY_T and prim_gain > 0:
        verdict = "SIGNAL"
    elif (np.isfinite(prim_t) and abs(prim_t) > 2.0 and prim_gain > 0) or n_sig >= 2:
        verdict = "MIXED"
    else:
        verdict = "NULL"
    results["verdict"] = verdict
    results["verdict_basis"] = {
        "pooled_primary_dm_hln_t": prim_t, "pooled_primary_gain_pct": prim_gain,
        "harvey_threshold": HARVEY_T,
        "n_assets_individually_significant_t3": n_sig,
        "note": ("Primary = date-aggregated pooled DM-HLN (K1355). Positive t and "
                 "positive gain% mean EM-credit features improve equity RV forecast."),
    }

    out_json = HERE / "k1621_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"[out] wrote {out_json}")

    _plot_heatmap(rv5, oas_chg5 if have_oas else None, have_etfs, have_oas)
    _plot_ccf(ccf_res, equities)
    _plot_regime(per_asset, regime, equities)

    print(f"\n=== VERDICT: {verdict} ===")
    print(f"pooled primary DM-HLN t={prim_t}, gain%={prim_gain}, "
          f"individually sig (|t|>3): {n_sig}/{len(equities)}")


def _plot_heatmap(rv5, oas_chg5, have_etfs, have_oas):
    cols = {c: np.log(rv5[c].replace(0, np.nan)) for c in have_etfs}
    if have_oas and oas_chg5 is not None:
        cols["OAS_chg5"] = oas_chg5
    mat = pd.DataFrame(cols).dropna()
    if mat.empty:
        return
    corr = mat.corr()
    fig, ax = plt.subplots(figsize=(9, 8))
    im = ax.imshow(corr.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr))); ax.set_yticks(range(len(corr)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right", fontsize=8)
    ax.set_yticklabels(corr.columns, fontsize=8)
    for i in range(len(corr)):
        for j in range(len(corr)):
            ax.text(j, i, f"{corr.values[i, j]:.2f}", ha="center", va="center", fontsize=7)
    ax.set_title("K1621: Contemporaneous corr of log 5d realized vol\n(EM bond/equity ETFs + EM OAS 5d change)")
    fig.colorbar(im, fraction=0.046, pad=0.04)
    fig.tight_layout(); fig.savefig(PLOTS / "correlation_heatmap.png", dpi=130); plt.close(fig)
    print("[plot] correlation_heatmap.png")


def _plot_ccf(ccf_res, equities):
    emb = ccf_res.get("emb_rv_vs_equity", {})
    if not emb:
        return
    lags = ccf_res["lags"]
    fig, ax = plt.subplots(figsize=(10, 6))
    for eq in equities:
        if eq in emb:
            ax.plot(lags, [emb[eq].get(k, np.nan) for k in lags], marker="o", label=eq)
    ax.axvline(0, color="gray", ls="--", lw=1); ax.axhline(0, color="gray", ls=":", lw=0.8)
    ax.set_xlabel("lag k  (EMB-RV(t) vs equity-RV(t+k);  k>0 = EMB leads)")
    ax.set_ylabel("cross-correlation")
    ax.set_title("K1621: Lead-lag CCF — EMB realized vol vs EM-equity realized vol")
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(PLOTS / "leadlag_ccf.png", dpi=130); plt.close(fig)
    print("[plot] leadlag_ccf.png")


def _plot_regime(per_asset, regime, equities):
    fig, ax = plt.subplots(figsize=(10, 6))
    gains = [per_asset.get(eq, {}).get("qlike_gain_pct", np.nan) for eq in equities]
    x = np.arange(len(equities))
    ax.bar(x, gains, color=["#2a7" if (g or 0) > 0 else "#c33" for g in gains])
    ax.set_xticks(x); ax.set_xticklabels(equities)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("QLIKE gain % (baseline - augmented)/baseline")
    reg_txt = " | ".join(
        f"{k}: gain%={v.get('qlike_gain_pct', float('nan')):.2f}, t={v.get('dm_hln_t', float('nan')):.2f}"
        for k, v in regime.items() if k in ("low_vix", "high_vix"))
    ax.set_title(f"K1621: Per-asset QLIKE gain from EM-credit (EMB-RV) features\n{reg_txt}")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout(); fig.savefig(PLOTS / "regime_forecast_gain.png", dpi=130); plt.close(fig)
    print("[plot] regime_forecast_gain.png")


if __name__ == "__main__":
    main()
